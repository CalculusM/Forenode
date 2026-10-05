# -*- coding: utf-8 -*-
"""골든값 생성기: 현행 코드로 실제 계산해 tests/golden_values.json에 고정한다.

실행: PYTHONIOENCODING=utf-8 python tests/make_golden.py
- 테스트가 자동 실행하지 않는다(골든은 커밋된 파일이 기준).
- 엔진 계산이 의도적으로 바뀐 경우에만 재생성하고, 바뀐 항목과 사유를 커밋 메시지에 남긴다.
- 데이터 파일은 읽기만 한다. interval_scoring 산출 CSV는 임시 폴더에 쓴다.
"""
import json
import math
import os
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _helpers as H  # noqa: E402  (루트 경로 등록)

sys.path.insert(0, os.path.join(H.ROOT, "research"))

import numpy as np  # noqa: E402


def _f(x):
    """JSON 직렬화: NaN은 None."""
    x = float(x)
    return None if math.isnan(x) else x


def _case_summary(case):
    import app
    bp = case["base_params"]
    _cf, m = app.build_cashflow(**bp)
    return {
        "daily_traffic": case["daily_traffic"],
        "anchor_capped": case["anchor_capped"],
        "annual_revenue_억": _f(bp["annual_revenue_억"]),
        "opex_ratio": _f(bp["opex_ratio"]),
        "opex_series_sum": _f(np.sum(bp["opex_series_억"])),
        "discount_rate": _f(bp["discount_rate"]),
        "debt_rate": _f(bp["debt_rate"]),
        "npv": _f(m["npv"]),
        "dscr_min": _f(m["dscr_min"]),
        "bc_ratio": _f(m["bc_ratio"]),
        "equity_irr": _f(m["equity_irr"]),
        "nominal_irr": _f(m["nominal_irr"]),
        "real_irr": _f(m["real_irr"]),
        "total_mrg_subsidy": _f(m["total_mrg_subsidy"]),
        "total_mcc_subsidy": _f(m["total_mcc_subsidy"]),
    }


def _thresholds(case):
    out = {}
    for key, crit, th in (("gov", "gov", 0.0), ("dscr_1.30", "dscr", 1.30),
                          ("real_irr_0.056", "real_irr", 0.056)):
        t, seek = H.threshold_traffic(case, crit, th)
        out[key] = {"traffic": _f(t) if t is not None else None, "status": seek["status"]}
    return out


def _realization_rows(case):
    import app
    import reverse_solver as rsv
    rows = rsv.realization_scenarios(case["base_params"], app.build_cashflow)
    return [{
        "ratio": r["ratio"],
        "npv": _f(r["metrics"]["npv"]),
        "dscr_min": _f(r["metrics"]["dscr_min"]),
        "equity_irr": _f(r["metrics"]["equity_irr"]),
        "first_profit_op_year": r["first_profit_op_year"],
        "payback_op_year": r["payback_op_year"],
        "mrg_total": _f(r["mrg_total"]),
        "trigger": bool(r["trigger"]),
    } for r in rows]


def _interval():
    import interval_scoring as isc
    with tempfile.TemporaryDirectory() as td:
        full = isc.run_full(out_path=os.path.join(td, "full.csv"))
        r62 = isc.run(out_path=os.path.join(td, "v1.csv"))
    rows = full["rows"]
    recent = [x for x in rows if str(x["연도"]) in ("2022", "2023", "2024")]
    return {
        "full": {"n": full["all"]["n"], "hits": int(sum(x["적중"] for x in rows)),
                 "coverage": full["all"]["coverage"], "mean_width": full["all"]["mean_width"],
                 "mean_IS": full["all"]["mean_IS"]},
        "recent_2022_2024": {"n": len(recent), "hits": int(sum(x["적중"] for x in recent))},
        "traffic_62": r62["all62"],
    }


def _revenue_band():
    import revenue_band_2026_09 as rb
    rev, versions = rb.load_revenue()
    traffic = rb.load_traffic()
    toll = rb.load_toll()
    full = rb.fit_m2([v for _, _, v in traffic], [e for _, _, e, _ in toll], None, 0)
    p10, p50, p90 = full["band"]
    all_routes = sorted({r[0] for r in rev})
    ri = {r: i for i, r in enumerate(all_routes)}
    routes, per_route, _rows, _fp = rb.run_sample(0, "주분석", rb.SAMPLES["주분석"],
                                                 rev, traffic, toll, ri)
    loo = {}
    for m in ("M0", "M2"):
        a = np.array([per_route[m][r] for r in routes], float)
        n = a[:, 1].sum()
        loo[m] = {"hits": int(a[:, 0].sum()), "n": int(n), "coverage": float(a[:, 0].sum() / n),
                  "mean_width": float(a[:, 2].sum() / n), "mean_IS": float(a[:, 3].sum() / n),
                  "MAE_center": float(a[:, 4].sum() / n)}
    return {
        "panel_versions": versions, "n_obs": len(rev), "n_routes": len(all_routes),
        "P10": p10, "P50": p50, "P90": p90,
        "P10_pct": round(100 * p10, 1), "P50_pct": round(100 * p50, 1), "P90_pct": round(100 * p90, 1),
        "loo_main": loo,
    }


def main():
    default = H.app_default_case()
    bt0 = H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0)
    golden = {
        "_meta": {
            "created": "2026-10-05",
            "generator": "tests/make_golden.py",
            "basis": "feat/revenue-band-gate 분기 시점 코드(5e15fde 기준). 수입 실현율 범위 표시 변경 전 계산값",
            "panel_version": "v1_2026-07-31",
        },
        "_tolerance": {
            "money_억": 0.01,
            "ratio": 1e-7,
            "irr": 1e-7,
            "traffic_대": 1.0,
            "band_fraction": 1e-9,
            "score_mean": 1e-9,
            "note": "결정론 계산이라 같은 코드면 차이 0. 허용 오차는 부동소수 연산 순서 차이 흡수용",
        },
        "case_default": _case_summary(default),
        "case_bridge_tunnel_0": _case_summary(bt0),
        "thresholds_default": _thresholds(default),
        "thresholds_bridge_tunnel_0": _thresholds(bt0),
        "realization_scenarios_default": _realization_rows(default),
        "interval_scoring": _interval(),
        "revenue_band": _revenue_band(),
    }
    with open(H.GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2)
    print("생성:", H.GOLDEN_PATH)
    print(json.dumps({k: golden[k] for k in ("thresholds_default", "thresholds_bridge_tunnel_0")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
