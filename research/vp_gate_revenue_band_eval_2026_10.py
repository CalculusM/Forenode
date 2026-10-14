# -*- coding: utf-8 -*-
"""수입 실현율 범위 서비스 반영 3개 안 평가 (VP 게이트, 2026-10-05)

판정 기준: research/vp_gate_revenue_band_criteria_2026-10.md (커밋 0724c5e, 계산 전 봉인).
이 스크립트는 기준을 읽어 적용만 한다. 기준값 변경 금지.

평가 범위
    P1~P3 공통 선행 조건, C1~C3 중앙값 교체 기준, C안 산출물 변화량 기록(판정 미사용).
    B1~B6은 구현 후 회귀 테스트(tests/)로 검증하므로 여기서는 계산하지 않는다.
엔진 미수정: app·reverse_solver·interval_scoring·research/revenue_band_2026_09는 읽기 전용 호출.
산출: research/vp_gate_revenue_band_eval_2026-10.json
재현: PYTHONIOENCODING=utf-8 python research/vp_gate_revenue_band_eval_2026_10.py (수 초)
"""
import hashlib
import json
import math
import os
import sys
import tempfile
import warnings
from collections import OrderedDict

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import revenue_band_2026_09 as rb   # noqa: E402  (읽기 전용 재사용)
import _helpers as H                # noqa: E402  (앱 기본값 사례 재구성)

CAND = os.path.join(ROOT, "data", "revenue_band_candidate_2026-09.json")
OUT = os.path.join(HERE, "vp_gate_revenue_band_eval_2026-10.json")
CRITERIA_DOC = "research/vp_gate_revenue_band_criteria_2026-10.md"
CRITERIA_COMMIT = "0724c5e"

# ── 봉인 기준값 (criteria 문서와 동일) ─────────────────────────────────
P3_TOL_PCTPT = 0.05          # 범위 재현 허용 차이(%p)
C1_MIN_IMPROVE_PCTPT = 3.0   # VP-2026-001 'MAE 3%p 이상 개선'
C2_N_BOOT = 4000
C2_SEED = 20261005
C_ANCHOR = 0.730             # C안: 중앙값 73.0%를 0.623 자리에 사용


def sha256_match(path, expected):
    """줄바꿈 무관 대조: 원본·LF·CRLF 표현 중 하나라도 일치하면 같은 내용.
    후보 JSON의 입력 sha256은 Windows 작업 트리(CRLF)에서 기록, 저장소 색인은 LF."""
    with open(path, "rb") as f:
        raw = f.read()
    lf = raw.replace(b"\r\n", b"\n")
    return expected in {hashlib.sha256(x).hexdigest() for x in (raw, lf, lf.replace(b"\n", b"\r\n"))}


def _nan2none(x):
    x = float(x)
    return None if math.isnan(x) else x


def loo_abs_errors(sample_name, rev, traffic, toll, route_index, sid):
    """노선 분리 폴드별 M0(0.623)·M2(폴드 중앙값) 절대 오차 합, 노선 단위."""
    spec = rb.SAMPLES[sample_name]
    routes, per_route, _rows, _fp = rb.run_sample(sid, sample_name, spec, rev, traffic, toll, route_index)
    n = np.array([per_route["M2"][r][1] for r in routes], float)
    ae0 = np.array([per_route["M0"][r][4] for r in routes], float)
    ae2 = np.array([per_route["M2"][r][4] for r in routes], float)
    return routes, n, ae0, ae2


def main():
    with open(CAND, encoding="utf-8") as f:
        cand = json.load(f)
    rev, versions = rb.load_revenue()
    traffic = rb.load_traffic()
    toll = rb.load_toll()
    all_routes = sorted({r[0] for r in rev})
    route_index = {r: i for i, r in enumerate(all_routes)}
    out = OrderedDict()
    out["criteria_doc"] = CRITERIA_DOC
    out["criteria_commit"] = CRITERIA_COMMIT
    out["candidate_tag"] = cand["candidate_tag"]
    out["panel_version"] = cand["panel_version"]

    # ── P1 후보 판정 ──
    p1 = cand["verdict"] == "작동" and cand["adopted_model"] == "M2"
    # ── P2 스냅샷 정합 ──
    sha_ok = {rel: sha256_match(os.path.join(ROOT, rel), sha) for rel, sha in cand["inputs_sha256"].items()}
    p2 = cand["panel_version"] == "v1_2026-07-31" and versions == ["v1_2026-07-31"] and all(sha_ok.values())
    # ── P3 범위 재현 ──
    full = rb.fit_m2([v for _, _, v in traffic], [e for _, _, e, _ in toll], None, 0)
    rec = dict(zip(("P10", "P50", "P90"), full["band"]))
    diff = {k: abs(rec[k] - cand["band_full_sample"][k]) * 100 for k in rec}
    p3 = all(d <= P3_TOL_PCTPT for d in diff.values())
    out["preconditions"] = {
        "P1": {"pass": p1, "verdict": cand["verdict"], "adopted_model": cand["adopted_model"]},
        "P2": {"pass": p2, "panel_versions": versions, "sha256_match": sha_ok},
        "P3": {"pass": p3, "recomputed": rec, "abs_diff_pctpt": diff, "tol_pctpt": P3_TOL_PCTPT},
    }

    # ── C1 중앙값 정확도 (주 분석, 노선 분리) ──
    routes, n, ae0, ae2 = loo_abs_errors("주분석", rev, traffic, toll, route_index, 0)
    N = n.sum()
    mae0, mae2 = ae0.sum() / N, ae2.sum() / N
    improve = (mae0 - mae2) * 100
    c1 = improve >= C1_MIN_IMPROVE_PCTPT
    # ── C2 개선 견고성: 노선 군집 재표본 ──
    rng = np.random.default_rng(C2_SEED)
    k = len(routes)
    idx = rng.integers(0, k, size=(C2_N_BOOT, k))
    counts = np.zeros((C2_N_BOOT, k))
    for j in range(k):
        counts[:, j] = (idx == j).sum(axis=1)
    b_imp = (counts @ (ae0 - ae2)) / (counts @ n) * 100
    ci = [float(x) for x in np.percentile(b_imp, [2.5, 97.5])]
    c2 = ci[0] > 0
    # 노선별 개선 부호(참고)
    route_gain = {r: float((ae0[i] - ae2[i]) / n[i] * 100) for i, r in enumerate(routes)}
    # ── C3 민감도 ──
    sens = {}
    for sid, s in ((1, "S1"), (2, "S2"), (3, "S3")):
        _r, ns, a0, a2 = loo_abs_errors(s, rev, traffic, toll, route_index, sid)
        imp = (a0.sum() - a2.sum()) / ns.sum() * 100
        sens[s] = {"n_obs": int(ns.sum()), "n_routes": len(_r), "MAE_M0_pct": a0.sum() / ns.sum() * 100,
                   "MAE_M2_pct": a2.sum() / ns.sum() * 100, "improve_pctpt": imp, "positive": imp > 0}
    c3 = all(v["positive"] for v in sens.values())
    # 참고(판정 미사용): 전 표본 중앙값 73.0%를 그대로 쓴 표본 내 오차
    obs = np.array([v for _, _, v in rev])
    insample = {"MAE_0.623_pct": float(np.mean(np.abs(obs - 0.623)) * 100),
                "MAE_0.730_pct": float(np.mean(np.abs(obs - C_ANCHOR)) * 100)}
    insample["improve_pctpt"] = insample["MAE_0.623_pct"] - insample["MAE_0.730_pct"]
    out["option_C"] = {
        "C1": {"pass": bool(c1), "n_obs": int(N), "n_routes": k, "MAE_M0_0.623_pct": mae0 * 100,
               "MAE_M2_fold_median_pct": mae2 * 100, "improve_pctpt": improve,
               "threshold_pctpt": C1_MIN_IMPROVE_PCTPT},
        "C2": {"pass": bool(c2), "n_boot": C2_N_BOOT, "seed": C2_SEED, "improve_ci95_pctpt": ci,
               "route_gain_pctpt": route_gain,
               "routes_gain_positive": int(sum(1 for v in route_gain.values() if v > 0))},
        "C3": {"pass": bool(c3), "by_sample": sens},
        "reference_in_sample_not_used": insample,
        "all_pass": bool(c1 and c2 and c3),
    }

    # ── C안 산출물 변화량 기록 (판정 미사용) ──
    import app
    import reverse_solver as rsv
    import interval_scoring as isc
    changes = {}
    for label, ov in (("기본값", {}), ("교량·터널 0%", {"bridge_ratio": 0.0, "tunnel_ratio": 0.0})):
        bp = H.app_default_case(**ov)["base_params"]
        cur = rsv.realization_scenarios(bp, app.build_cashflow)
        alt = rsv.realization_scenarios(bp, app.build_cashflow, ratios=(1.0, 0.9, 0.814, 0.7, C_ANCHOR))

        def row(r):
            m = r["metrics"]
            return {"ratio": r["ratio"], "npv": _nan2none(m["npv"]), "dscr_min": _nan2none(m["dscr_min"]),
                    "equity_irr": _nan2none(m["equity_irr"]),
                    "first_profit_op_year": r["first_profit_op_year"],
                    "payback_op_year": r["payback_op_year"], "trigger_below_70": bool(r["trigger"])}
        a, b = row(cur[-1]), row(alt[-1])
        unchanged_rows = all(
            row(x) == row(y) for x, y in zip(cur[:-1], alt[:-1]))
        changes[label] = {"current_0.623": a, "option_C_0.730": b,
                          "npv_delta": b["npv"] - a["npv"],
                          "dscr_min_delta": b["dscr_min"] - a["dscr_min"],
                          "trigger_flip": a["trigger_below_70"] != b["trigger_below_70"],
                          "other_4_rows_unchanged": unchanged_rows}
    with tempfile.TemporaryDirectory() as td:
        full_sc = isc.run_full(out_path=os.path.join(td, "f.csv"))
    hits = int(sum(x["적중"] for x in full_sc["rows"]))
    out["option_C_change_record"] = {
        "realization_scenario_revenue_row": changes,
        "traffic_scoring_98": {"hits": hits, "n": len(full_sc["rows"]),
                               "note": "교통량 채점은 수입 앵커와 무관. C안 적용 시에도 변화 없음"},
    }

    pre_ok = p1 and p2 and p3
    out["decision_inputs"] = {
        "preconditions_pass": bool(pre_ok),
        "C_all_pass": out["option_C"]["all_pass"],
        "B": "구현 후 tests/ 회귀 스위트로 B1~B6 검증",
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))   # numpy 스칼라

    print("P1", p1, "P2", p2, "P3", p3, {k: round(v, 6) for k, v in diff.items()})
    print(f"C1 MAE 0.623 {mae0*100:.2f}% / M2 폴드 중앙값 {mae2*100:.2f}% / 개선 {improve:.2f}%p "
          f"(기준 {C1_MIN_IMPROVE_PCTPT}%p) {'통과' if c1 else '미통과'}")
    print(f"C2 개선 95% CI [{ci[0]:.2f}, {ci[1]:.2f}]%p {'통과' if c2 else '미통과'} "
          f"| 개선 양수 노선 {out['option_C']['C2']['routes_gain_positive']}/{k}")
    for s, v in sens.items():
        print(f"C3 {s}: 개선 {v['improve_pctpt']:+.2f}%p ({v['n_routes']}노선 {v['n_obs']}건)")
    print("C3", "통과" if c3 else "미통과", "| C 전체", out["option_C"]["all_pass"])
    print("참고 표본 내:", {k: round(v, 2) for k, v in insample.items()})
    for lab, ch in changes.items():
        print(lab, json.dumps(ch, ensure_ascii=False))
    print("교통량 채점", hits, "/", len(full_sc["rows"]))
    print("생성:", OUT)


if __name__ == "__main__":
    main()
