# -*- coding: utf-8 -*-
"""회귀 테스트 공용 도우미.

- 저장소 루트를 sys.path에 넣어 엔진 모듈(app·reverse_solver 등)을 import 가능하게 한다.
- app_default_case(): app.py main()의 기본 입력 경로(예측치 미입력·직접 입력·BTO-a)를
  Streamlit 없이 같은 엔진 함수로 재구성한다. 화면 실행 결과(fn_base_params)와의 일치는
  test_app_smoke.AppDefaultParity가 확인한다(재구성이 화면과 어긋나면 그 테스트가 실패).
- 데이터 파일은 읽기만 한다. 산출 파일이 필요한 함수는 임시 폴더 경로를 넘긴다.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "data")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_values.json")

# app.py 사이드바 기본값(직접 입력·BTO-a·예측치 미입력). 값이 바뀌면 화면 일치 테스트가 잡는다.
APP_DEFAULT_INPUTS = {
    "business_type": "BTO-a",
    "road_length": 45,
    "total_capex": 13000,
    "operation_years": 30,
    "construction_years": 5,
    "terrain": "평지",
    "bridge_ratio": 0.15,
    "tunnel_ratio": 0.20,
    "lanes": 4,
    "growth_pct": 2.5,
    "heavy_ratio_pct": 30,
    "toll_per_km": None,     # None = 사업 유형 기본 요금(화면 자동값). 노선 요금 재현 시 override
    "heavy_surcharge": 1.5,
    "base_rate": 0.025,
    "capm_beta": 0.70,
    "capm_mrp": 0.06,
    "senior_ratio": 0.70,
    "senior_spread": 0.015,
    "sub_spread": 0.07,
    "infl_pct": 2.0,
    "tax_rate": 0.22,
    "restructuring_year": 0,
    "restructuring_toll_cut_pct": 0,
    "ancillary_revenue": 0.0,
    "equity_recovery_method": "원금+수익률",
    "debt_repayment_method": "원리금균등",
}
TRAFFIC_ANCHOR_RATIO = 0.814   # app.py 권장 협약 수요 앵커(문턱 ÷ 0.814)와 동일


def load_golden() -> dict:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def app_default_case(**overrides) -> dict:
    """app.py main() 기본 경로 재구성. overrides로 bridge_ratio·tunnel_ratio 등 교체 가능.

    반환: base_params(app의 fn_base_params와 같은 키), daily_traffic, rev_K, cap_limit, anchor_capped
    """
    import numpy as np

    import app
    import config_loader
    import reverse_solver as rsv
    from opex_estimator import estimate_opex_series

    p = dict(APP_DEFAULT_INPUTS)
    p.update(overrides)
    bt = p["business_type"]
    bd = config_loader.business_defaults()[bt]
    # 요금은 앱과 같은 순서로 부트스트랩 앵커·운영비 시계열까지 반영(수입 계수만 바꾸면 문턱이 어긋남, 2026-10-07)
    toll_per_km = p["toll_per_km"] if p.get("toll_per_km") else (bd["toll"] if bd["toll"] > 0 else 80)
    equity_ratio = bd["equity"] / 100
    mrg_ratio = bd["mrg"] / 100
    mcc_ratio = bd["mcc"] / 100
    ke = p["base_rate"] + p["capm_beta"] * p["capm_mrp"]
    senior_rate = p["base_rate"] + p["senior_spread"]
    sub_rate = p["base_rate"] + p["sub_spread"]
    debt_rate = p["senior_ratio"] * senior_rate + (1 - p["senior_ratio"]) * sub_rate
    wacc_info = app.calc_wacc_detail(
        rf=p["base_rate"], mrp=p["capm_mrp"], beta=p["capm_beta"],
        equity_ratio=equity_ratio, debt_rate=debt_rate, tax_rate=p["tax_rate"],
        senior_ratio=p["senior_ratio"], senior_rate=senior_rate, sub_rate=sub_rate, ke=ke)

    cap = config_loader.capacity_gate()
    cap_limit = float(cap["limit_by_lanes"][str(p["lanes"])])
    heavy = p["heavy_ratio_pct"] / 100
    growth = p["growth_pct"] / 100
    infl = p["infl_pct"] / 100
    rev_K = rsv.traffic_revenue_coeff(p["road_length"], toll_per_km, heavy, p["heavy_surcharge"])

    common = {
        "construction_years": p["construction_years"], "operation_years": p["operation_years"],
        "discount_rate": wacc_info["wacc"], "inflation": infl, "growth_rate": growth,
        "equity_ratio": equity_ratio, "debt_rate": debt_rate,
        "senior_ratio": p["senior_ratio"], "senior_rate": senior_rate, "tax_rate": p["tax_rate"],
        "business_type": bt, "mrg_ratio": mrg_ratio, "mcc_ratio": mcc_ratio,
        "restructuring_year": p["restructuring_year"],
        "restructuring_toll_adj": 1 + p["restructuring_toll_cut_pct"] / 100,
        "equity_recovery_method": p["equity_recovery_method"],
        "debt_repayment_method": p["debt_repayment_method"],
    }
    boot_params = {"capex_억": p["total_capex"],
                   "annual_revenue_억": max(500.0, rev_K * cap_limit),
                   "opex_ratio": bd["opex"] / 100, "opex_series_억": None, **common}
    boot = rsv.min_revenue_for(boot_params, app.build_cashflow, rsv.make_predicate("gov"))
    anchor_capped = False
    if boot.get("min_rev") and rev_K > 0:
        anchor = boot["min_rev"] / rev_K / TRAFFIC_ANCHOR_RATIO
        if anchor > cap_limit:
            anchor = cap_limit
            anchor_capped = True
        daily_traffic = int(round(anchor))
    else:
        daily_traffic = int(cap_limit)
        anchor_capped = True

    toll_df = app.estimate_toll_revenue(
        p["road_length"], daily_traffic, toll_per_km, growth, heavy,
        p["heavy_surcharge"], p["operation_years"])
    ann_rev = toll_df["Revenue_억"].iloc[0]
    opex_est = estimate_opex_series(
        business_type=bt, annual_revenue_억=ann_rev, operation_years=p["operation_years"],
        terrain=p["terrain"], tunnel_ratio=p["tunnel_ratio"], bridge_ratio=p["bridge_ratio"],
        growth_rate=growth, inflation=infl)
    base_params = {
        "capex_억": p["total_capex"],
        "annual_revenue_억": ann_rev,
        "construction_years": p["construction_years"],
        "operation_years": p["operation_years"],
        "opex_ratio": opex_est["opex_ratio_avg"],
        "opex_series_억": np.array(opex_est["opex_series_억"]),
        "discount_rate": wacc_info["wacc"],
        "inflation": infl,
        "growth_rate": growth,
        "equity_ratio": equity_ratio,
        "debt_rate": debt_rate,
        "senior_ratio": p["senior_ratio"],
        "senior_rate": senior_rate,
        "tax_rate": p["tax_rate"],
        "business_type": bt,
        "mrg_ratio": mrg_ratio,
        "mcc_ratio": mcc_ratio,
        "ancillary_revenue_억": p["ancillary_revenue"],
        "restructuring_year": p["restructuring_year"],
        "restructuring_toll_adj": 1 + p["restructuring_toll_cut_pct"] / 100,
        "equity_recovery_method": p["equity_recovery_method"],
        "debt_repayment_method": p["debt_repayment_method"],
    }
    return {"base_params": base_params, "daily_traffic": daily_traffic, "rev_K": rev_K,
            "cap_limit": cap_limit, "anchor_capped": anchor_capped, "toll_per_km": toll_per_km}


def threshold_traffic(case: dict, criterion: str, threshold: float = 0.0):
    """app.py 사업성 문턱 표와 같은 계산: 기준 통과 최소 연수입 ÷ K."""
    import app
    import reverse_solver as rsv
    seek = rsv.min_revenue_for(case["base_params"], app.build_cashflow,
                               rsv.make_predicate(criterion, threshold))
    if seek["status"] in ("ok", "below_range") and case["rev_K"] > 0:
        return seek["min_rev"] / case["rev_K"], seek
    return None, seek
