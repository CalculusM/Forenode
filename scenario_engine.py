"""
Forenode — 민감도·시나리오 엔진 (scenario_engine.py)   ※ pre3.0 신규 핵심 모듈

포지셔닝
--------
"수요는 외부 입력, 우리는 그 가정에 대한 민감도·리스크를 자동화한다."
이 모듈은 수요 예측기가 아니다. 사용자가 넣은 BASE 가정(수요·공사비·금리)을
변수로 흔들어 DSCR·LLCR·IRR·NPV가 어떻게 움직이는지(일방향·토네이도·몬테카를로)와
리스크 등록부를 산출한다. 대주단·운용사 실사(DD)에서 실제로 요구하는 산출물.

설계 원칙
--------
- app.py 를 수정하지 않는다. 엔진 함수(build_cashflow 등)를 import 만 한다.
- LLCR·EBITDA 는 build_cashflow 가 돌려주는 cf_df 에서 외부 계산한다(엔진 불변).
- debt sculpting 은 상환 스케줄이 build_cashflow 내부라 여기서 계산 불가 → app.py 작업으로 보류.
- 벤치마크(낙관편향 플래그)는 안심구역 통행 변동성 데이터 확보 전까지 '가정'으로 명시.

용어
----
- CFADS  : 부채상환가능현금흐름 = 매출 − 운영비 − 세금 (app.py DSCR 분자와 동일 정의)
- DSCR   : CFADS ÷ 원리금
- LLCR   : 잔여 대출기간 CFADS 현재가치(부채금리 할인) ÷ 잔존 부채
- EBITDA : 매출 − 운영비 (감가상각·이자·세금 전)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable

import numpy as np
import pandas as pd

# 엔진은 공개 앱과 100% 동일한 것을 재사용 (중복 구현 금지, app.py 미수정)
from app import build_cashflow, calc_wacc_detail, estimate_toll_revenue
from pretest_regressor import estimate_capex_from_route


# ════════════════════════════════════════════════════════════
# BASE 케이스 정의
# ════════════════════════════════════════════════════════════
@dataclass
class BaseCase:
    """민감도 분석의 기준점. 모든 시나리오는 이 값에 배수/델타를 적용해 생성."""
    capex_억: float
    annual_revenue_억: float
    wacc: float
    debt_rate: float
    construction_years: int = 5
    operation_years: int = 30
    opex_ratio: float = 0.30
    inflation: float = 0.02
    growth_rate: float = 0.025
    equity_ratio: float = 0.25
    business_type: str = "BTO-ann"
    tax_rate: float = 0.22
    mrg_ratio: float = 0.0
    mcc_ratio: float = 0.0
    # 참고용 입력(낙관편향 플래그 등에 사용)
    daily_traffic: float = 0.0
    road_length_km: float = 0.0

    def to_kwargs(self) -> dict:
        return dict(
            capex_억=self.capex_억,
            annual_revenue_억=self.annual_revenue_억,
            construction_years=self.construction_years,
            operation_years=self.operation_years,
            opex_ratio=self.opex_ratio,
            discount_rate=self.wacc,
            inflation=self.inflation,
            growth_rate=self.growth_rate,
            equity_ratio=self.equity_ratio,
            debt_rate=self.debt_rate,
            business_type=self.business_type,
            tax_rate=self.tax_rate,
            mrg_ratio=self.mrg_ratio,
            mcc_ratio=self.mcc_ratio,
        )


def make_base_case(
    road_length_km: float,
    lanes: int = 4,
    terrain: str = "평지",
    bridge_ratio: float = 0.15,
    tunnel_ratio: float = 0.20,
    business_type: str = "BTO-ann",
    daily_traffic: int = 50000,
    toll_per_km: float = 80.0,
    construction_years: int = 5,
    operation_years: int = 30,
    equity_ratio: float = 0.25,
    debt_rate: float = 0.05,
    rf: float = 0.035,
    mrp: float = 0.06,
    beta: float = 0.7,
    tax_rate: float = 0.22,
    opex_ratio: float = 0.30,
    inflation: float = 0.02,
    growth_rate: float = 0.025,
) -> BaseCase:
    """노선 파라미터 → CAPEX·수익·WACC 를 엔진으로 산출해 BASE 케이스 구성."""
    capex = estimate_capex_from_route(
        road_length_km=road_length_km, lanes=lanes, terrain=terrain,
        bridge_ratio=bridge_ratio, tunnel_ratio=tunnel_ratio, business_type=business_type,
    )
    capex_eok = capex["capex_estimate_억"]

    toll_df = estimate_toll_revenue(
        road_length_km, int(daily_traffic), float(toll_per_km),
        growth_rate=growth_rate, heavy_vehicle_ratio=0.30, heavy_vehicle_surcharge=2.5,
        years=operation_years,
    )
    ann_rev = float(toll_df["Revenue_억"].iloc[0]) if len(toll_df) > 0 else 0.0

    wacc_info = calc_wacc_detail(
        rf=rf, mrp=mrp, beta=beta, equity_ratio=equity_ratio,
        debt_rate=debt_rate, tax_rate=tax_rate,
    )

    return BaseCase(
        capex_억=capex_eok, annual_revenue_억=ann_rev,
        wacc=wacc_info["wacc"], debt_rate=debt_rate,
        construction_years=construction_years, operation_years=operation_years,
        opex_ratio=opex_ratio, inflation=inflation, growth_rate=growth_rate,
        equity_ratio=equity_ratio, business_type=business_type, tax_rate=tax_rate,
        daily_traffic=daily_traffic, road_length_km=road_length_km,
    )


# ════════════════════════════════════════════════════════════
# LLCR · EBITDA — cf_df 에서 외부 계산 (app.py 불변)
# ════════════════════════════════════════════════════════════
def _extended_metrics(cf_df: pd.DataFrame, construction_years: int,
                      operation_years: int, debt_rate: float) -> dict:
    """build_cashflow 가 돌려준 cf_df 로 LLCR·EBITDA 를 계산해 추가."""
    cs = construction_years
    total = cs + operation_years

    # cf_df 부호 규약: OPEX/Tax/Interest/Principal 은 음수 저장
    rev = cf_df["Revenue"].to_numpy()
    opex_col = cf_df["OPEX"].to_numpy()          # = -opex
    tax_col = cf_df["Tax"].to_numpy()            # = -tax
    debt_bal = cf_df["DebtBalance"].to_numpy()

    cfads = rev + opex_col + tax_col             # 매출 − 운영비 − 세금
    ebitda = rev + opex_col                      # 매출 − 운영비

    op_slice = slice(cs + 1, total + 1)
    ebitda_op = ebitda[op_slice]

    # LLCR(프로젝트): 대출 인출 시점(건설 종료)에서 잔여 CFADS 현가 ÷ 초기 부채
    initial_debt = debt_bal[cs] if debt_bal[cs] > 0 else np.nan
    disc = np.array([1.0 / (1 + debt_rate) ** (y - cs) for y in range(cs + 1, total + 1)])
    pv_cfads_all = float(np.sum(cfads[op_slice] * disc))
    llcr_project = pv_cfads_all / initial_debt if initial_debt and not np.isnan(initial_debt) else np.nan

    # LLCR(연차별 최소): 각 운영연도 시작 잔존부채 대비 잔여 CFADS 현가
    llcr_annual = []
    for k in range(cs + 1, total + 1):
        bal = debt_bal[k - 1]
        if bal <= 1e-9:
            continue
        d = np.array([1.0 / (1 + debt_rate) ** (y - k) for y in range(k, total + 1)])
        pv = float(np.sum(cfads[k:total + 1] * d))
        llcr_annual.append(pv / bal)
    llcr_min = float(np.min(llcr_annual)) if llcr_annual else np.nan

    return {
        "ebitda_total": float(np.sum(ebitda_op)),
        "ebitda_avg": float(np.mean(ebitda_op)) if len(ebitda_op) else 0.0,
        "llcr_project": float(llcr_project),
        "llcr_min": llcr_min,
    }


# ════════════════════════════════════════════════════════════
# 단일 시나리오 실행
# ════════════════════════════════════════════════════════════
def run_scenario(base: BaseCase, demand_mult: float = 1.0,
                 capex_mult: float = 1.0, rate_delta: float = 0.0) -> dict:
    """
    BASE 에 배수/델타를 적용해 한 시나리오를 산출.
    - demand_mult : 수요(=연수익) 배수.  수요 -20% → 0.80
    - capex_mult  : 공사비 배수.        공사비 +30% → 1.30
    - rate_delta  : 금리 충격(절대).    +150bp → 0.015 (부채금리·할인율에 동시 가산)
                    ※ 가정: 금리 상승이 WACC에 그대로 전가된다고 단순화.
    """
    kw = base.to_kwargs()
    kw["annual_revenue_억"] = base.annual_revenue_억 * demand_mult
    kw["capex_억"] = base.capex_억 * capex_mult
    kw["debt_rate"] = max(0.0, base.debt_rate + rate_delta)
    kw["discount_rate"] = max(1e-6, base.wacc + rate_delta)

    cf_df, metrics = build_cashflow(**kw)
    ext = _extended_metrics(cf_df, base.construction_years,
                            base.operation_years, kw["debt_rate"])

    return {
        "demand_mult": demand_mult, "capex_mult": capex_mult, "rate_delta": rate_delta,
        "npv": metrics["npv"],
        "nominal_irr": metrics["nominal_irr"],
        "equity_irr": metrics["equity_irr"],
        "dscr_min": metrics["dscr_min"],
        "dscr_avg": metrics["dscr_avg"],
        **ext,
    }


# ════════════════════════════════════════════════════════════
# 일방향 민감도 / 토네이도
# ════════════════════════════════════════════════════════════
_VAR_SETTERS: dict[str, Callable[[float], dict]] = {
    "demand": lambda v: {"demand_mult": v},
    "capex": lambda v: {"capex_mult": v},
    "rate": lambda v: {"rate_delta": v},
}


def one_way_sensitivity(base: BaseCase, var: str, values: list[float],
                        metric: str = "dscr_min") -> pd.DataFrame:
    """한 변수를 values 범위로 스윕 → 지표 변화 표."""
    if var not in _VAR_SETTERS:
        raise ValueError(f"var must be one of {list(_VAR_SETTERS)}")
    rows = []
    for v in values:
        res = run_scenario(base, **_VAR_SETTERS[var](v))
        rows.append({var: v, **{m: res[m] for m in
                                ("npv", "nominal_irr", "dscr_min", "llcr_min", "ebitda_avg")}})
    return pd.DataFrame(rows)


def tornado(base: BaseCase, metric: str = "dscr_min",
            spec: dict[str, tuple[float, float]] | None = None) -> pd.DataFrame:
    """
    각 변수의 (low, high) 충격에 따른 지표 스윙을 정렬해 토네이도 데이터로 반환.
    spec 기본값: 수요 ±20%, 공사비 −10%/+30%, 금리 ±150bp (실무 통상 범위, 조정 가능).
    """
    base_val = run_scenario(base)[metric]
    spec = spec or {
        "demand": (0.80, 1.20),
        "capex": (0.90, 1.30),
        "rate": (-0.015, 0.015),
    }
    rows = []
    for var, (lo, hi) in spec.items():
        m_lo = run_scenario(base, **_VAR_SETTERS[var](lo))[metric]
        m_hi = run_scenario(base, **_VAR_SETTERS[var](hi))[metric]
        rows.append({
            "variable": var, "low_input": lo, "high_input": hi,
            "metric_low": m_lo, "metric_high": m_hi,
            "swing": abs(m_hi - m_lo),
        })
    df = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    df.attrs["base_metric"] = base_val
    return df


# ════════════════════════════════════════════════════════════
# 몬테카를로 — 하방 리스크 확률
# ════════════════════════════════════════════════════════════
def monte_carlo(base: BaseCase, n: int = 2000,
                demand_sd: float = 0.15, capex_sd: float = 0.10,
                rate_sd: float = 0.01, demand_mean_bias: float = 0.0,
                seed: int = 42,
                lockup_dscr: float = 1.20, default_dscr: float = 1.00) -> dict:
    """
    수요·공사비·금리를 분포에서 샘플링해 지표 분포·하방확률 산출.
    - demand: 정규(평균 1+bias, 표준편차 demand_sd).  낙관편향을 bias<0 로 보정 가능.
    - capex : 정규(평균 1, 표준편차 capex_sd), 하한 0.5
    - rate  : 정규(평균 0, 표준편차 rate_sd) 절대 델타
    ※ 분포 파라미터는 사용자 입력/안심구역 통행 변동성 통계로 교체 전까지 '가정'.
    """
    rng = np.random.default_rng(seed)
    dm = np.clip(rng.normal(1.0 + demand_mean_bias, demand_sd, n), 0.2, None)
    cm = np.clip(rng.normal(1.0, capex_sd, n), 0.5, None)
    rd = rng.normal(0.0, rate_sd, n)

    npvs, dscrs, irrs, llcrs = [], [], [], []
    for i in range(n):
        r = run_scenario(base, demand_mult=float(dm[i]),
                         capex_mult=float(cm[i]), rate_delta=float(rd[i]))
        npvs.append(r["npv"]); dscrs.append(r["dscr_min"])
        irrs.append(r["nominal_irr"]); llcrs.append(r["llcr_min"])
    npvs = np.array(npvs); dscrs = np.array(dscrs)
    irrs = np.array(irrs); llcrs = np.array(llcrs)

    def pct(a):
        return {"p10": float(np.nanpercentile(a, 10)),
                "p50": float(np.nanpercentile(a, 50)),
                "p90": float(np.nanpercentile(a, 90))}

    return {
        "n": n,
        "npv": pct(npvs), "dscr_min": pct(dscrs),
        "nominal_irr": pct(irrs), "llcr_min": pct(llcrs),
        "prob_npv_negative": float(np.mean(npvs < 0)),
        "prob_dscr_below_1_2": float(np.mean(dscrs < 1.20)),   # 고정 1.20 참조(하위호환)
        "prob_dscr_below_1_0": float(np.mean(dscrs < 1.00)),   # 고정 1.00 참조(하위호환)
        "prob_dscr_below_lockup": float(np.mean(dscrs < lockup_dscr)),
        "prob_dscr_below_default": float(np.mean(dscrs < default_dscr)),
        "prob_llcr_below_1_2": float(np.nanmean(llcrs < 1.20)),
    }


# ════════════════════════════════════════════════════════════
# 낙관편향 플래그 (벤치마크 기반)
# ════════════════════════════════════════════════════════════
def optimism_flag(input_aadt: float, benchmark_aadt: np.ndarray | None = None,
                  warn_percentile: float = 80.0) -> dict:
    """
    입력 통행량이 비교노선 분포에서 상위 몇 %인지 → 낙관편향 경고.
    benchmark_aadt 미지정 시 평가 불가(안심구역 통행 변동성 데이터로 채울 자리).
    """
    if benchmark_aadt is None or len(benchmark_aadt) == 0:
        return {"evaluated": False,
                "note": "벤치마크 분포 미확보(안심구역 차량통행지표로 채울 자리) — 평가 보류"}
    benchmark_aadt = np.asarray(benchmark_aadt, dtype=float)
    pctl = float((benchmark_aadt < input_aadt).mean() * 100.0)
    return {
        "evaluated": True,
        "input_aadt": input_aadt,
        "percentile": pctl,
        "flag": pctl >= warn_percentile,
        "message": (f"입력 통행량이 비교노선 상위 {100 - pctl:.0f}% — 낙관편향 점검 권장"
                    if pctl >= warn_percentile else
                    f"입력 통행량이 비교노선 분포 {pctl:.0f} 분위 — 정상 범위"),
    }


# ════════════════════════════════════════════════════════════
# 부채 스컬프팅 — 목표 DSCR을 평탄하게 떠받치는 지속가능 부채한도
# ════════════════════════════════════════════════════════════
def sculpt_debt(base: BaseCase, target_dscr: float = 1.30) -> dict:
    """
    각 운영연도 CFADS를 목표 DSCR로 나눠 '감당 가능한 원리금'을 정하고,
    그 원리금 흐름의 현가로 지속가능 부채한도를 역산(스컬프팅)한다.

    build_cashflow 의 상환 루프를 다시 짜지 않는 '분석용' 독립 계산이다.
    "이 현금흐름이 떠받칠 수 있는 부채 규모와 평탄 DSCR 프로파일"을 보여준다.
    sculpted_debt 가 현재 부채(=CAPEX×(1−자기자본비율))보다 작으면,
    목표 DSCR 유지를 위해 부채를 줄이거나 만기를 늘려야 한다는 신호.
    """
    cf_df, _ = build_cashflow(**base.to_kwargs())
    cs, total = base.construction_years, base.construction_years + base.operation_years
    op = slice(cs + 1, total + 1)
    rev = cf_df["Revenue"].to_numpy()[op]
    opex_col = cf_df["OPEX"].to_numpy()[op]   # 음수
    tax_col = cf_df["Tax"].to_numpy()[op]     # 음수
    cfads = rev + opex_col + tax_col          # 매출 − 운영비 − 세금

    ds = np.clip(cfads / target_dscr, 0, None)
    r = base.debt_rate
    sculpted = float(sum(d / (1 + r) ** (i + 1) for i, d in enumerate(ds)))
    current_debt = float(base.capex_억 * (1 - base.equity_ratio))

    return {
        "target_dscr": target_dscr,
        "sculpted_debt_억": sculpted,
        "current_debt_억": current_debt,
        "headroom_억": sculpted - current_debt,
        "annual_debt_service_억": ds,
        "implied_tenor": int(len(ds)),
    }


# ════════════════════════════════════════════════════════════
# 리스크 등록부 (대주단 DD 산출물)
# ════════════════════════════════════════════════════════════
def risk_register(base: BaseCase) -> pd.DataFrame:
    """표준 리스크 항목별 충격 → 지표 영향을 표로. 대주단 실사 리스크 등록부 형식."""
    base_res = run_scenario(base)
    items = [
        ("수요 하방", "수요 −20%", {"demand_mult": 0.80}),
        ("공사비 초과", "공사비 +30%", {"capex_mult": 1.30}),
        ("금리 상승", "+150bp", {"rate_delta": 0.015}),
        ("복합 스트레스", "수요−20%·공사비+15%·금리+100bp",
         {"demand_mult": 0.80, "capex_mult": 1.15, "rate_delta": 0.010}),
    ]
    rows = []
    for risk, shock, kw in items:
        r = run_scenario(base, **kw)
        rows.append({
            "리스크": risk, "충격(가정)": shock,
            "DSCR_min": round(r["dscr_min"], 2),
            "ΔDSCR_min": round(r["dscr_min"] - base_res["dscr_min"], 2),
            "LLCR_min": round(r["llcr_min"], 2),
            "NPV(억)": round(r["npv"], 0),
            "NPV<0": "예" if r["npv"] < 0 else "아니오",
        })
    df = pd.DataFrame(rows)
    df.attrs["base_dscr_min"] = round(base_res["dscr_min"], 2)
    df.attrs["base_npv"] = round(base_res["npv"], 0)
    return df
