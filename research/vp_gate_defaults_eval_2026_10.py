# -*- coding: utf-8 -*-
"""VP 게이트 묶음(P-11 가·나·라·마, P3-01) 판정 근거 산출. 엔진·기본값·config 변경 없음.

기준: research/vp_gate_defaults_criteria_2026-10.md(계산 전 봉인). 절 번호를 주석으로 연결.
실행(저장소 루트): PYTHONIOENCODING=utf-8 python research/vp_gate_defaults_eval_2026_10.py
산출: research/vp_gate_defaults_eval_2026-10.json
숫자 상수는 config·data·raw 파일에서 읽는다. 아래 상수 6개는 봉인 기준값.
"""
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import numpy as np  # noqa: E402

import _helpers as H  # noqa: E402
import app  # noqa: E402
import config_loader  # noqa: E402
import opex_estimator  # noqa: E402
import reverse_solver as rsv  # noqa: E402
import threshold_display as td  # noqa: E402

STUDY_RAW = os.environ.get("FORENODE_STUDY_RAW") or os.path.join(
    os.path.dirname(os.path.dirname(ROOT)), "창업실습_3학년2학기", "시장조사_민자고속도로_추진현황_2026-10", "raw")
OUT = os.path.join(ROOT, "research", "vp_gate_defaults_eval_2026-10.json")

MAE_GAIN_MIN = 5.0        # 기준 2-3 G1 (원/km)
TIE_BREAK_WON = 1.0       # 기준 2-3 동률 폭
N1_MIN_ROUTES = 8         # 기준 3-2 N1
SHIFT_MIN_PCT = 5.0       # 기준 4-3
FIXPOINT_MAX_ITER = 20    # 기준 5-2
OPEX_V2_MIN_POINTS = 14   # 기준 5-3 (v2-overcoming-design 3절)

# 기준 2-1 명단(봉인)
HIGHWAY = ["[후보] 팔공산 관통 고속도로", "영동~오창", "서평택~봉담", "서울~양주",
           "익산~부여(서부내륙 2단계)", "평택~시흥 확장(개량운영형)"]
UNDERGROUND = ["[후보] 제4경인 고속화도로", "[후보] 양재~올림픽대로 지하도로", "[후보] 우면~용산 지하도로"]
INPUT_KEYS = ("business_type", "road_length", "total_capex", "bridge_ratio", "tunnel_ratio", "lanes",
              "construction_years", "operation_years", "growth_pct", "heavy_ratio_pct", "toll_per_km")


def raw(name):
    with open(os.path.join(STUDY_RAW, name), encoding="utf-8") as f:
        return json.load(f)


def gov(case):
    t, seek = H.threshold_traffic(case, "gov")
    return t, seek["status"]


# ── 가안: 통행료 기본값 (기준 2절) ─────────────────────────────────────────
def eval_toll_default():
    five, v3 = raw("03_five_input_inputs.json"), raw("03_forenode_test_inputs_v3.json")
    fp = config_loader.load_finance_params()
    fts, mult = fp["fiscal_toll_structure"], fp["toll_benchmark"]["policy_cap_mult"]
    bd = config_loader.business_defaults()
    rows = []
    for name, grp in [(n, "고속도로형") for n in HIGHWAY] + [(n, "지하·소형차") for n in UNDERGROUND]:
        r = next(x for x in five if x["name"] == name)
        L, rep = r["road_length"], r["toll_reported"]
        opts = {"A": float(bd[r["business_type"]]["toll"]),
                "B": td.fiscal_toll_per_km(L, fts["base_won"], fts["per_km_won_class1"], mult),
                "C": td.fiscal_toll_per_km(L, fts["base_won"], fts["per_km_won_class1"], 1.0)}
        v3r = next((x for x in v3 if x["name"] == name), None)
        rows.append({"name": name, "group": grp, "length_km": L, "toll_reported": rep,
                     "toll_basis": (r.get("basis") or {}).get("toll") or "",
                     "v3_toll_reported": v3r.get("toll_reported") if v3r else None,
                     **{f"toll_{k}": v for k, v in opts.items()},
                     **{f"err_{k}": round(v - rep, 1) for k, v in opts.items()}})
    stats = {}
    for grp in ("고속도로형", "지하·소형차"):
        g = [r for r in rows if r["group"] == grp]
        stats[grp] = {k: {"n": len(g), "mae": round(sum(abs(r[f"err_{k}"]) for r in g) / len(g), 1),
                          "max_abs": round(max(abs(r[f"err_{k}"]) for r in g), 1)} for k in "ABC"}
    hw, ug = stats["고속도로형"], stats["지하·소형차"]
    passing = [k for k in "BC" if hw["A"]["mae"] - hw[k]["mae"] >= MAE_GAIN_MIN and ug[k]["mae"] <= ug["A"]["mae"]]
    if not passing:
        chosen = None
    elif len(passing) == 1 or abs(hw["B"]["mae"] - hw["C"]["mae"]) < TIE_BREAK_WON:
        chosen = "B" if "B" in passing else passing[0]
    else:
        chosen = min(passing, key=lambda k: hw[k]["mae"])
    verdict = f"채택 권고(대표 결정 대기): {chosen}안" if chosen else "근거 부족(A 유지)"
    return {"rows": rows, "stats": stats, "mult_B": mult, "passing": passing, "chosen": chosen, "verdict": verdict,
            "v3_mismatch": [r["name"] for r in rows if r["v3_toll_reported"] not in (None, r["toll_reported"])]}


# ── 나안: BTO-a 운영기간 (기준 3절) ─────────────────────────────────────────
def _op_grade(op):
    if re.search("공고|민투심|요약문|협약", op):
        return "1차·공고"
    if "가정" in op:
        return "가정"
    return "보도" if "보도" in op else "미기재"


def eval_op_years():
    v3 = raw("03_forenode_test_inputs_v3.json")
    with open(os.path.join(STUDY_RAW, "R_koti_local.md"), encoding="utf-8") as f:
        koti = f.read()
    rows = [{"name": r["name"], "operation_years": r.get("operation_years"), "basis": (r.get("basis") or {}).get("op") or "",
             "grade": _op_grade((r.get("basis") or {}).get("op") or "")}
            for r in v3 if r["business_type"] == "BTO-a"]
    def count(grade):
        return sum(1 for r in rows if r["grade"] == grade and (r["operation_years"] or 0) >= 40)
    n1, n_press = count("1차·공고"), count("보도")
    koti_lines = [ln.strip() for ln in koti.splitlines() if "운영기간" in ln and "30년" in ln]
    names_40 = bool(re.search(r"40년[^\n]{0,20}표준|표준[^\n]{0,20}40년", koti))
    n2 = names_40
    verdict = "채택 권고(대표 결정 대기)" if (n1 >= N1_MIN_ROUTES and n2) else "근거 부족(기본 30년 유지)"
    return {"rows": rows, "n_bto_a": len(rows), "n1_primary_ge40": n1, "n_press_ge40": n_press,
            "n_assumed": sum(1 for r in rows if r["grade"] == "가정"), "koti_standard_lines": koti_lines,
            "koti_names_40_standard": n2, "verdict": verdict}


# ── 라안: 성장 경로 용량 상한 (기준 4절) ────────────────────────────────────
def _seek_rev(bp, series_fn, lo_frac=0.02, hi_frac=3.0, tol_억=0.5):
    """reverse_solver.min_revenue_for와 같은 이분법. 1년차 수입 R의 경로 series_fn(R)을 revenue_series_억으로 전달."""
    pred = rsv.make_predicate("gov")

    def ok(R):
        try:
            _, m = app.build_cashflow(**{**bp, "annual_revenue_억": float(R), "revenue_series_억": series_fn(float(R))})
            return pred(m)
        except Exception:
            return False
    cur = float(bp["annual_revenue_억"])
    lo, hi = cur * lo_frac, cur * hi_frac
    if not ok(hi):
        return None, "infeasible"
    if ok(lo):
        return lo, "below_range"
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            hi = mid
        else:
            lo = mid
        if hi - lo < tol_억:
            break
    return hi, "ok"


def growth_path_options(case, growth, cap, years):
    """3안 문턱(대). A 무상한 / B 연도별 min(경로, 한계) / C 권장 수요 경로의 한계 초과 연차 이후 성장 0."""
    K, bp = case["rev_K"], case["base_params"]
    g = np.array([(1 + growth) ** y for y in range(years)])
    y_star = next((y + 1 for y in range(years) if case["daily_traffic"] * g[y] > cap), None)
    fC = np.array([(1 + growth) ** (min(y + 1, y_star or years) - 1) for y in range(years)])
    out = {"y_star_recommended_path": y_star}
    for key, fn in (("A", lambda R: R * g),
                    ("B", lambda R: np.minimum(R / K * g, cap) * K),
                    ("C", lambda R: R * fC)):
        R, status = _seek_rev(bp, fn)
        out[key] = {"status": status, "traffic": None if R is None else R / K}
    ref, _ = gov(case)
    out["A"]["parity_vs_engine"] = abs(out["A"]["traffic"] - ref)
    if out["B"]["status"] == "infeasible":   # 한계 평탄 경로 필요 수입에서 필요 요금(기준 4-2)
        R_flat, st = _seek_rev(bp, lambda R: np.full(years, R))
        out["B"]["flat_cap_required_toll"] = None if R_flat is None else round(case["toll_per_km"] * R_flat / (cap * K), 1)
    if out["C"]["traffic"] and out["C"]["traffic"] > cap:
        out["C"]["required_toll_at_capacity"] = td.required_toll_at_capacity(case["toll_per_km"], out["C"]["traffic"], cap)
    for k in "BC":
        t = out[k]["traffic"]
        out[k]["shift_pct"] = None if t is None else round((t - ref) / ref * 100, 2)
    return out


def eval_growth_cap():
    growth = H.APP_DEFAULT_INPUTS["growth_pct"] / 100
    cap_cfg = config_loader.capacity_gate()
    cap = float(cap_cfg["limit_by_lanes"][str(H.APP_DEFAULT_INPUTS["lanes"])])
    res = {"growth": growth, "cap_limit": cap, "multiple_at_year": {y: round((1 + growth) ** (y - 1), 3) for y in (30, 40, 50)}}
    cases = {}
    for years in (H.APP_DEFAULT_INPUTS["operation_years"], 40):
        case = H.app_default_case(operation_years=years)
        T0, _ = gov(case)
        first_over = lambda T: next((y for y in range(1, years + 1) if T * (1 + growth) ** (y - 1) > cap), None)
        cases[str(years)] = {"gov_threshold": T0, "recommended_daily_traffic": case["daily_traffic"],
                             "anchor_capped": case["anchor_capped"],
                             "first_year_over_cap_threshold_path": first_over(T0),
                             "first_year_over_cap_recommended_path": first_over(case["daily_traffic"]),
                             "options": growth_path_options(case, growth, cap, years)}
    res["cases"] = cases
    o30 = cases[str(H.APP_DEFAULT_INPUTS["operation_years"])]["options"]
    big = any(o30[k]["status"] == "infeasible" or abs(o30[k]["shift_pct"] or 0) >= SHIFT_MIN_PCT for k in "BC")
    res["verdict"] = "보류(VP 게이트 상정, B안 우선, 2027. 1. 8. 이후 묶음)" if big else "보류(영향 미미, 캡션 고지)"
    return res


# ── 마안: 운영비 시계열 앵커 의존 (기준 5절) ─────────────────────────────────
def _sens_sets():
    sens, v3o, fiveo = raw("11_capex_sensitivity.json"), raw("04_forenode_test_results_v3.json"), raw("04_five_input_results.json")
    sets = {}
    for o in sens:
        m = re.search(r"\[\D*?([\d.]+)\]\s*(.*)", o["name"])
        if m:
            sets.setdefault(("five" if "five" in o.get("note", "") else "v3", m.group(2)), {})[float(m.group(1))] = o
    for (tag, base), d in sets.items():
        d[1.0] = next(x for x in (fiveo if tag == "five" else v3o) if x["name"] == base and x.get("toll_scenario") != "flat")
    return sets


def fixpoint(inputs):
    """운영비 시계열을 직전 문턱 수입에서 재산출하는 고정점 반복(기준 5-2 B). 지역 재구현, 엔진 미변경."""
    p = {**H.APP_DEFAULT_INPUTS, **inputs}
    case = H.app_default_case(**inputs)
    T, _ = gov(case)
    hist = [T]
    converged = False
    for _ in range(FIXPOINT_MAX_ITER):
        toll_df = app.estimate_toll_revenue(p["road_length"], int(round(T)), case["toll_per_km"], p["growth_pct"] / 100,
                                            p["heavy_ratio_pct"] / 100, p["heavy_surcharge"], p["operation_years"])
        rev1 = toll_df["Revenue_억"].iloc[0]
        est = opex_estimator.estimate_opex_series(
            business_type=p["business_type"], annual_revenue_억=rev1, operation_years=p["operation_years"],
            terrain=p["terrain"], tunnel_ratio=p["tunnel_ratio"], bridge_ratio=p["bridge_ratio"],
            growth_rate=p["growth_pct"] / 100, inflation=p["infl_pct"] / 100)
        bp = {**case["base_params"], "annual_revenue_억": rev1, "opex_ratio": est["opex_ratio_avg"],
              "opex_series_억": np.array(est["opex_series_억"])}
        T2, _ = gov({**case, "base_params": bp})
        hist.append(T2)
        if T2 is None:
            break
        if abs(T2 - T) < 1:
            T, converged = T2, True
            break
        T = T2
    return {"T_anchor": hist[0], "T_fixpoint": T, "iterations": len(hist) - 1, "converged": converged,
            "history": [None if h is None else round(h) for h in hist]}


def eval_opex_anchor():
    sets = _sens_sets()
    nonmono, kink = [], []
    for (tag, base), d in sets.items():
        ms = sorted(d)
        th = [d[m]["thresholds"]["gov"]["traffic"] for m in ms]
        for i in range(1, len(ms)):
            if th[i] is not None and th[i - 1] is not None and th[i] < th[i - 1]:
                nonmono.append({"set": tag, "route": base, "mult": [ms[i - 1], ms[i]], "gov": [th[i - 1], th[i]]})
        if len(ms) == 4 and None not in th:
            kink.append({"route": base, "gov_by_mult": dict(zip(map(str, ms), th)),
                         "capped_by_mult": {str(m): d[m].get("recommended_exceeds_capacity_limit") for m in ms},
                         "slope_ratio_1.2_over_0.8": round((th[2] - th[1]) / (th[1] - th[0]), 3)})
    cited = {}
    for route in ("용인~충주", "태안~안성", "서창~김포"):
        cited[route] = [{"set": tag, "mult": m, "toll": o["inputs"]["toll_per_km"], "capex": o["inputs"]["total_capex"],
                         "gov": o["thresholds"]["gov"]["traffic"], "capped": o.get("recommended_exceeds_capacity_limit")}
                        for (tag, base), d in sets.items() if base == route for m, o in sorted(d.items())]
    yc = {}
    for tag in ("v3", "five"):
        d = sets[(tag, "용인~충주")]
        for m in sorted(d):
            inp = {k: d[m]["inputs"][k] for k in INPUT_KEYS}
            case = H.app_default_case(**inp)
            T, _ = gov(case)
            yc[f"{tag}_x{m}"] = {"toll": inp["toll_per_km"], "capex": inp["total_capex"],
                                 "opex_sum_억": round(float(np.sum(case["base_params"]["opex_series_억"])), 1),
                                 "opex_ratio_avg": round(case["base_params"]["opex_ratio"], 4),
                                 "anchor_daily_traffic": case["daily_traffic"], "anchor_capped": case["anchor_capped"],
                                 "gov": T, "gov_recorded": d[m]["thresholds"]["gov"]["traffic"],
                                 "fixpoint_B": fixpoint(inp)}
    yc["default"] = {"fixpoint_B": fixpoint({})}
    fps = [v["fixpoint_B"] for v in yc.values()]
    all_conv = all(f["converged"] for f in fps)
    v3t = [yc[f"v3_x{m}"] for m in (0.8, 1.0, 1.2)]
    sr_A = (v3t[2]["gov"] - v3t[1]["gov"]) / (v3t[1]["gov"] - v3t[0]["gov"])
    sr_B = ((v3t[2]["fixpoint_B"]["T_fixpoint"] - v3t[1]["fixpoint_B"]["T_fixpoint"])
            / (v3t[1]["fixpoint_B"]["T_fixpoint"] - v3t[0]["fixpoint_B"]["T_fixpoint"]))
    b_ok = all_conv and abs(sr_B - 1) < abs(sr_A - 1)
    bench = re.search(r"벤치마크\(백테스트 V-001~021 실측 원단위 (\d+)점", inspect.getsource(opex_estimator.estimate_opex_series))
    n_points = int(bench.group(1)) if bench else None
    return {"nonmonotonic_within_set": nonmono, "n_sets": len(sets), "kink_v3": kink, "cited_pairs": cited,
            "yongin_chungju": yc, "slope_ratio_A": round(sr_A, 3), "slope_ratio_B": round(sr_B, 3),
            "B_all_converged": all_conv, "B_meets_criteria": b_ok,
            "opex_unit_points": n_points, "C_evidence": "근거 부족" if (n_points or 0) < OPEX_V2_MIN_POINTS else "검토 가능",
            "verdict": "보류(VP 게이트 상정, B안, 라안과 묶음)" if b_ok else "A 유지(단서 캡션 P-13)"}


# ── P3-01: 터널 70% 상한 (기준 6절) ────────────────────────────────────────
def eval_tunnel_cap():
    v3i, v3o = raw("03_forenode_test_inputs_v3.json"), raw("04_forenode_test_results_v3.json")
    rows = []
    for r in v3i:
        structure = (r.get("basis") or {}).get("structure", "")
        if "터널 70% 상한" not in structure:
            continue
        true_ratio = max(int(p) for p in re.findall(r"(\d+)%", structure)) / 100   # 실제 비율 = 표기 백분율 최대값
        for o in (x for x in v3o if x["name"] == r["name"] and "error" not in x):
            inp = {k: o["inputs"][k] for k in INPUT_KEYS}
            if true_ratio <= inp["tunnel_ratio"]:        # 상한 미만 노선 제외(기준 6-1 대상 4건)
                break
            c0, c1 = H.app_default_case(**inp), H.app_default_case(**{**inp, "tunnel_ratio": true_ratio})
            T0, T1 = gov(c0)[0], gov(c1)[0]
            rows.append({"name": r["name"], "toll_scenario": o["toll_scenario"], "toll": inp["toll_per_km"],
                         "tunnel_cap": inp["tunnel_ratio"], "tunnel_true": true_ratio,
                         "gov_recorded": o["thresholds"]["gov"]["traffic"], "gov_cap": round(T0),
                         "parity_ok": abs(T0 - o["thresholds"]["gov"]["traffic"]) <= 1, "gov_true": round(T1),
                         "delta": round(T1 - T0), "delta_pct": round((T1 - T0) / T0 * 100, 2),
                         "opex_ratio_cap": round(c0["base_params"]["opex_ratio"], 4),
                         "opex_ratio_true": round(c1["base_params"]["opex_ratio"], 4)})
    src = inspect.getsource(opex_estimator._route_adjustment)
    m = re.search(r"tunnel_adj = tunnel_ratio \* ([\d.]+)\s*#?\s*(.*)", src)
    cfg = config_loader.load_params()
    coef = {"value": float(m.group(1)), "inline_comment": m.group(2).strip(),
            "docstring": (opex_estimator._route_adjustment.__doc__ or "").strip(),
            "citation_in_source": bool(re.search(r"출처|근거|source|KOTI|보고서|실측", src)),
            "config_key_exists": any("tunnel" in json.dumps(v, ensure_ascii=False).lower() for v in cfg.values()),
            "config_top_keys": list(cfg.keys())}
    basis_exists = coef["citation_in_source"] and coef["config_key_exists"]
    return {"rows": rows, "tunnel_coefficient": coef,
            "verdict": "채택 권고(대표 결정 대기)" if basis_exists else "근거 부족(상한 유지, 캡션 고지 P-13)"}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    try:
        commit = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = ""
    res = {"_meta": {"as_of": "2026-10-14", "criteria": "research/vp_gate_defaults_criteria_2026-10.md",
                     "engine_commit": commit, "no_default_changed": True,
                     "golden_sha256": _sha(H.GOLDEN_PATH),
                     "finance_params_sha256": _sha(os.path.join(ROOT, "config", "finance_params.json")),
                     "inputs_sha256": {n: _sha(os.path.join(STUDY_RAW, n)) for n in (
                         "03_five_input_inputs.json", "03_forenode_test_inputs_v3.json", "04_forenode_test_results_v3.json",
                         "04_five_input_results.json", "11_capex_sensitivity.json", "R_koti_local.md")}},
           "a_toll_default": eval_toll_default(), "b_op_years": eval_op_years(), "d_growth_cap": eval_growth_cap(),
           "e_opex_anchor": eval_opex_anchor(), "p3_01_tunnel_cap": eval_tunnel_cap()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    for k in ("a_toll_default", "b_op_years", "d_growth_cap", "e_opex_anchor", "p3_01_tunnel_cap"):
        print(k, "::", res[k]["verdict"])
    print("saved", OUT)


if __name__ == "__main__":
    main()
