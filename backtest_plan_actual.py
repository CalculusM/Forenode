# -*- coding: utf-8 -*-
"""
계획 vs 실제 백테스트 표준 모듈 (backtest_plan_actual.py)

메모리 규칙 R1~R7(rules_backtest_plan_vs_actual)의 구현체 — 전 사업 일괄 적용.
  A = 최초 실시협약 추정 vs 실제 실적 오차
  B = Forenode 재추정(as-of) vs 같은 실적 오차
  오차 = (실제 − 추정) / 추정 × 100%  (R3)

Forenode 엔진은 포크하지 않고 원본을 그대로 사용:
  - build_cashflow: app.py 원문에서 함수 구간을 추출·exec (Streamlit 부팅 회피)
  - demand_bias: BENCHMARK_PRIORS에 LOO prior를 런타임 등록 후 동일 API 호출
  - opex_estimator.estimate_opex_series: 통계 모드 그대로

테스트 케이스: 인천국제공항고속도로 (신공항하이웨이(주))
계획측 1차 출처: KOTI MP-24-11 표 2-16(기존 실시협약 '00.1)·RR-25-10 표 2-3/표 5-11.
"""
import io
import math
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# ────────────────────────────────────────────────────────────
# KOTI RR-25-10 표 5-11 원표 — 22개 민자고속도로 협약·실측 교통량(대/일), '22~'24
# (국토교통부 2025 「2024년도 민자도로의 건설 및 유지·관리 현황에 관한 보고서」 p.12)
# 81.4% prior(demand_bias BENCHMARK_PRIORS)의 원천 표본 → leave-one-out 재계산용 (R2)
# ────────────────────────────────────────────────────────────
TABLE_5_11 = {
    "인천국제공항":   [(2022, 127136, 80996), (2023, 127136, 106510), (2024, 127136, 126089)],
    "천안-논산":     [(2022, 90036, 57995), (2023, 90036, 59346), (2024, 90036, 58819)],
    "대구-부산":     [(2022, 95831, 49089), (2023, 95831, 51440), (2024, 95831, 52210)],
    "서울외곽":      [(2022, 135945, 136219), (2023, 137405, 139678), (2024, 138882, 138057)],
    "부산-울산":     [(2022, 64249, 43818), (2023, 65050, 45624), (2024, 65609, 44915)],
    "서울-춘천":     [(2022, 60903, 62720), (2023, 61322, 60712), (2024, 62246, 64834)],
    "용인-서울":     [(2022, 114145, 94030), (2023, 115090, 94621), (2024, 116033, 95299)],
    "인천대교":      [(2022, 64608, 53154), (2023, 66590, 67964), (2024, 68317, 74108)],
    "서수원-평택":   [(2022, 69693, 81771), (2023, 71181, 81777), (2024, 72701, 82573)],
    "평택-시흥":     [(2022, 75350, 64758), (2023, 76224, 67062), (2024, 77114, 66186)],
    "수원-광명":     [(2022, 77620, 66499), (2023, 77849, 68429), (2024, 78078, 68438)],
    "광주-원주":     [(2022, 59373, 47640), (2023, 59846, 48151), (2024, 60320, 49529)],
    "부산신항제2배후": [(2022, 43626, 20391), (2023, 49719, 21796), (2024, 57315, 20425)],
    "인천-김포":     [(2022, 69366, 52386), (2023, 70304, 53151), (2024, 71515, 54641)],
    "상주-영천":     [(2022, 45724, 32600), (2023, 46378, 33246), (2024, 47052, 33933)],
    "구리-포천":     [(2022, 68112, 55025), (2023, 69642, 57542), (2024, 71225, 58120)],
    "안양-성남":     [(2022, 127390, 83792), (2023, 128209, 65642), (2024, 129619, 92450)],
    "서울-문산":     [(2022, 45827, 45426), (2023, 46193, 47644), (2024, 46620, 48942)],
    "봉담-송산":     [(2022, 30782, 25491), (2023, 39454, 28972), (2024, 44231, 31471)],
    "화성-광주":     [(2022, 24884, 29845), (2023, 25394, 32028), (2024, 35418, 33573)],
    "포천-화도":     [(2024, 37971, 20994)],
    "평택-부여":     [(2024, 48950, 22455)],
}


def loo_prior(exclude_route: str):
    """표 5-11에서 exclude_route를 제외한 (실측/협약) 비율의 평균·표준편차 (R2 LOO).

    KOTI 원문(전체 포함) 평균 81.4%·분산 0.041과의 정합은 all-in 값으로 검증.
    """
    all_in, loo = [], []
    for route, rows in TABLE_5_11.items():
        for (_y, agreed, measured) in rows:
            r = measured / agreed
            all_in.append(r)
            if route != exclude_route:
                loo.append(r)
    all_in, loo = np.array(all_in), np.array(loo)
    return {
        "all_mean": float(all_in.mean()), "all_sd": float(all_in.std(ddof=1)),
        "all_n": int(all_in.size),
        "loo_mean": float(loo.mean()), "loo_sd": float(loo.std(ddof=1)),
        "loo_n": int(loo.size), "excluded": exclude_route,
    }


def load_engine():
    """app.py 원문에서 build_cashflow 함수 구간만 추출·exec.

    Streamlit 앱 전체를 import하면 위젯 코드가 실행되므로, 원본 코드 텍스트를
    그대로 실행해 동일한 함수 객체를 얻는다(로직 포크 없음 — 원문과 바이트 단위 동일).
    """
    src = io.open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    start = src.index("def build_cashflow(")
    end = src.index("def build_pimac_standard_table")
    segment = src[start:end]
    ns = {"np": np, "math": math}
    import pandas as pd
    ns["pd"] = pd
    exec(segment, ns)
    return ns["build_cashflow"]


def pct_err(actual, plan):
    """R3: (실제 − 추정)/추정 × 100%."""
    if plan in (None, 0) or actual is None:
        return None
    return (actual - plan) / plan * 100.0


def block5(series_by_year: dict, start_year: int):
    """R4: 연도별 dict → 개통연차 5년 블록 합계 {'1~5': 합, '6~10': 합, ...}."""
    out = {}
    for y, v in sorted(series_by_year.items()):
        if v is None:
            continue
        op_year = y - start_year + 1
        blk = (op_year - 1) // 5
        key = f"{blk*5+1}~{blk*5+5}년차"
        out.setdefault(key, 0.0)
        out[key] += v
    return out


def reconstructed_irr(cashflows_by_year: dict, base_year: int):
    """R7: 실제 현금흐름(연도 dict, 억원)의 IRR — 단순 뉴턴법 (build_cashflow와 동일 알고리즘)."""
    years = sorted(cashflows_by_year)
    cfs = [cashflows_by_year[y] for y in years]
    offset = [y - base_year for y in years]
    rate = 0.05
    for _ in range(300):
        npv = sum(cf / (1 + rate) ** t for cf, t in zip(cfs, offset))
        d = sum(-t * cf / (1 + rate) ** (t + 1) for cf, t in zip(cfs, offset))
        if abs(d) < 1e-12:
            break
        new = rate - npv / d
        if abs(new - rate) < 1e-9:
            return new
        rate = new
        if abs(rate) > 1.5:
            return float("nan")
    return rate


def register_loo_prior(loo: dict, label: str):
    """demand_bias.BENCHMARK_PRIORS에 LOO prior를 런타임 등록 → Forenode API 그대로 사용."""
    import demand_bias
    demand_bias.BENCHMARK_PRIORS[label] = {
        "dist": "normal", "p1": round(loo["loo_mean"], 4), "p2": round(loo["loo_sd"], 4),
        "median_ratio": round(loo["loo_mean"], 4),
        "source": (f"KOTI RR-25-10 표 5-11 원표에서 {loo['excluded']} 제외 재계산 "
                   f"(LOO, n={loo['loo_n']}) — 백테스트 R2 순환오염 제거"),
    }
    return label


if __name__ == "__main__":
    # ── 자가 점검 1: 표 5-11 정합 (KOTI 원문 평균 81.4%·분산 0.041) ──
    pri = loo_prior("인천국제공항")
    print(f"[표5-11 정합] 전체 평균 {pri['all_mean']*100:.1f}% (원문 81.4%) · "
          f"SD {pri['all_sd']:.4f} (원문 0.2025) · n={pri['all_n']}")
    print(f"[LOO prior — 인천공항 제외] 평균 {pri['loo_mean']*100:.1f}% · "
          f"SD {pri['loo_sd']:.4f} · n={pri['loo_n']}")

    # ── 자가 점검 2: 엔진 추출·스모크 ──
    build_cashflow = load_engine()
    cf, m = build_cashflow(
        capex_억=13727, annual_revenue_억=1500, construction_years=5,
        operation_years=30, opex_ratio=0.25, discount_rate=0.0562,
        inflation=0.0, growth_rate=0.03, equity_ratio=0.25, debt_rate=0.06,
        business_type="BTO", mrg_ratio=0.80,
    )
    print(f"[엔진 스모크] real_irr={m['real_irr']*100:.2f}% · NPV={m['npv']:.0f}억 · "
          f"MRG보전 총액={m['total_mrg_subsidy']:.0f}억 · DSCR_avg={m['dscr_avg']:.2f}")

    # ── 자가 점검 3: LOO prior 등록 → Forenode demand API 동작 ──
    label = register_loo_prior(pri, "_백테스트 LOO(인천공항 제외)")
    import demand_bias
    band = demand_bias.demand_optimism_band(127136, prior=label)
    print(f"[LOO 밴드] 협약 127,136대/일 → P50 {band['p50']:,.0f} "
          f"(P10 {band['p10']:,.0f}~P90 {band['p90']:,.0f}) · {band['flag']}")
