# -*- coding: utf-8 -*-
"""Forenode 사업성 문턱 역산 일괄 실행기(2026-10 민자고속도로 추진현황 스터디 raw/threshold_run.py 승격판).

리서치·영업 재료 전용, 앱 화면 기능화 금지(rnd-ontrack §8). 다노선 배치 화면 등 제품 기능으로 옮기지 않는다.
엔진 호출 경로는 앱 화면·회귀 테스트와 동일(tests/_helpers.app_default_case, 요금은 부트스트랩 앵커·운영비 시계열까지 주입).

사용: python research/threshold_batch_2026_10.py --routes PATH [--out PATH] [--scenarios fiscal,flat]
routes JSON: 노선 목록 또는 {"_meta": ..., "cases": [...]}. 항목 키
  name, business_type, road_length, lanes, bridge_ratio, tunnel_ratio, construction_years, operation_years,
  growth_pct, heavy_ratio_pct, forecast_aadt, note, toll_reported(보도·공고·추정 요금, 원/km)
  total_capex          : 민간투자비(억 원). 지정 시 그대로 사용.
  total_project_cost   : 총사업비(억 원). subsidy·land(건설보조금·보상비)가 함께 있으면 차감,
                         없으면 config private_share_of_total_cost 비율로 추정.
  둘 다 없으면 pretest_regressor 단가 모형으로 추정(참고 범위).
  scenarios            : 노선별 시나리오 목록(없으면 --scenarios). flat = 사업 유형 기본 요금,
                         fiscal = 재정요금 구조 환산값(toll_reported가 있으면 reported로 대체), reported = toll_reported.
  extra_criteria       : [["real_irr", 0.025], ...] 노선별 추가 기준(기획단계·제안자 수익률 등)
출력: 기준별 문턱(재무 성립선·DSCR 1.30·협약 평균 수익률·추가 기준)·권장 협약 수요·차로 용량·여유 배수·
      용량 내 성립 필요 통행료(수입 비례 근사)·공사비 참고 범위. 숫자 상수는 config/finance_params.json에서 읽는다.
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _helpers as H                     # noqa: E402
import config_loader                     # noqa: E402
import pretest_regressor as pr           # noqa: E402
import threshold_display as thd          # noqa: E402

_FP = config_loader.load_finance_params()
FISCAL = _FP["fiscal_toll_structure"]
FISCAL_MULT = _FP["toll_benchmark"]["policy_cap_mult"]
PRIVATE_SHARE = _FP.get("private_share_of_total_cost", {}).get("value", 0.594)   # fallback until config key lands
COVENANT_RATE, COVENANT_LABEL = config_loader.covenant_return_rate()
CRIT = {"gov": ("gov", 0.0), "dscr_1.30": ("dscr", 1.30), f"real_irr_{COVENANT_RATE:g}": ("real_irr", COVENANT_RATE)}
CASE_KEYS = ("business_type", "road_length", "bridge_ratio", "tunnel_ratio", "lanes",
             "construction_years", "operation_years", "growth_pct", "heavy_ratio_pct")


def resolve_capex(r: dict):
    """민간투자비 결정: 입력값 > 총사업비 차감 > 총사업비×전국 비율 > 단가 모형. (값, 근거, 모형 추정 dict|None)."""
    if r.get("total_capex") is not None:
        return r["total_capex"], "민간투자비 입력값", None
    if r.get("total_project_cost") is not None:
        capex, basis = thd.resolve_private_capex(r["total_project_cost"], r.get("subsidy"), r.get("land"), PRIVATE_SHARE)
        return capex, basis, None
    est = pr.estimate_capex_from_route(r["road_length"], r.get("lanes", 4), r.get("terrain", "평지"),
                                       r.get("bridge_ratio", 0.15), r.get("tunnel_ratio", 0.20),
                                       r.get("business_type", "BTO-a"))
    return est["capex_estimate_억"], "단가 모형 추정", est


def scenario_case(r: dict, scenario: str) -> dict:
    """시나리오별 요금 결정. flat = 기본 요금(None), reported = toll_reported, fiscal = 재정 구조 환산(보도 요금 있으면 reported)."""
    rr = dict(r)
    rr.pop("toll_per_km", None)
    if scenario == "flat":
        rr["toll_scenario"] = "flat"
    elif scenario == "reported" or rr.get("toll_reported"):
        if not rr.get("toll_reported"):
            raise ValueError("reported 시나리오에 toll_reported 없음")
        rr["toll_per_km"] = float(rr["toll_reported"])
        rr["toll_scenario"] = "reported"
    else:
        rr["toll_per_km"] = thd.fiscal_toll_per_km(rr["road_length"], FISCAL["base_won"],
                                                   FISCAL["per_km_won_class1"], FISCAL_MULT)
        rr["toll_scenario"] = "fiscal"
    return rr


def run_one(r: dict) -> dict:
    ov = {k: r[k] for k in CASE_KEYS if r.get(k) is not None}
    capex, basis, est = resolve_capex(r)
    ov["total_capex"] = capex
    ov["toll_per_km"] = r.get("toll_per_km")          # None = 사업 유형 기본 요금
    case = H.app_default_case(**ov)
    inputs = {k: ov.get(k, H.APP_DEFAULT_INPUTS.get(k)) for k in CASE_KEYS + ("total_capex",)}
    inputs["toll_per_km"] = case["toll_per_km"]
    out = {"name": r["name"], "group": r.get("group", ""), "toll_scenario": r.get("toll_scenario", ""),
           "inputs": inputs, "capex_basis": basis, "total_project_cost": r.get("total_project_cost"),
           "capex_estimated": basis != "민간투자비 입력값"}
    for k in ("as_of", "basis", "source", "confidence"):
        if k in r:
            out[k] = r[k]
    if est:
        out["capex_estimate"] = est
    ref = pr.estimate_capex_from_route(inputs["road_length"], inputs["lanes"], r.get("terrain", "평지"),
                                       inputs["bridge_ratio"], inputs["tunnel_ratio"])
    out["capex_reference_range_억"] = [ref["capex_low_억"], ref["capex_high_억"]]
    out["capex_in_reference_range"] = ref["capex_low_억"] <= capex <= ref["capex_high_억"]
    out["capex_per_km_억"] = round(capex / inputs["road_length"], 1)
    cap = config_loader.capacity_gate()
    lanes = str(inputs["lanes"])
    out["capacity"] = {"warn": cap["warn_by_lanes"][lanes], "limit": cap["limit_by_lanes"][lanes]}
    crit = dict(CRIT)
    for c, t in (r.get("extra_criteria") or []):
        crit[f"{c}_{t}"] = (c, t)
    th = {}
    for key, (c, t) in crit.items():
        traffic, seek = H.threshold_traffic(case, c, t)
        th[key] = {"traffic": None if traffic is None else round(traffic), "status": seek["status"]}
    out["thresholds"] = th
    gov = th["gov"]["traffic"]
    if gov:
        limit = out["capacity"]["limit"]
        rec = gov / H.TRAFFIC_ANCHOR_RATIO
        out["recommended_agreement_traffic"] = round(rec)
        out["recommended_exceeds_capacity_limit"] = rec > limit
        out["gov_threshold_vs_capacity"] = round(gov / limit, 3)
        out["headroom"] = thd.headroom(limit, gov)
        if gov > limit:
            out["toll_per_km_needed_at_capacity"] = thd.required_toll_at_capacity(case["toll_per_km"], gov, limit)
        if r.get("forecast_aadt"):
            out["forecast_aadt"] = r["forecast_aadt"]
            out["forecast_over_gov_threshold"] = round(r["forecast_aadt"] / gov, 3)
    out["note"] = r.get("note", "")
    return out


def run_all(routes: list, scenarios: list) -> list:
    res = []
    for r in routes:
        for sc in (r.get("scenarios") or scenarios):
            try:
                res.append(run_one(scenario_case(r, sc)))
            except Exception as e:      # 한 노선 실패가 전체를 막지 않도록
                res.append({"name": r.get("name"), "toll_scenario": sc, "error": repr(e), "note": r.get("note", "")})
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--routes", required=True, help="노선 입력 JSON(목록 또는 {cases: [...]})")
    ap.add_argument("--out", help="결과 JSON 경로(생략 시 표준 출력 요약만)")
    ap.add_argument("--scenarios", default="fiscal,flat", help="노선에 scenarios가 없을 때 쓰는 기본 목록(쉼표 구분)")
    a = ap.parse_args(argv)
    with open(a.routes, encoding="utf-8") as f:
        data = json.load(f)
    routes = data["cases"] if isinstance(data, dict) else data
    res = run_all(routes, a.scenarios.split(","))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    for o in res:
        if "error" in o:
            print(f'{o["name"]}: ERROR {o["error"]}')
            continue
        t = o["thresholds"]
        base = " / ".join(f"{k} {v['traffic']}" for k, v in t.items())
        print(f'{o["name"]} [{o["toll_scenario"]} {o["inputs"]["toll_per_km"]}원/km]: {base} | 권장 {o.get("recommended_agreement_traffic")} '
              f'| 여유 {o.get("headroom")} | 필요요금 {o.get("toll_per_km_needed_at_capacity", "-")} | capex {o["inputs"]["total_capex"]} '
              f'({o["capex_basis"]}, {o["capex_per_km_억"]}억/km) 참고범위 {o["capex_reference_range_억"]}')
    errors = sum("error" in o for o in res)
    print(f"완료 {len(res)}건, 오류 {errors}건")
    return errors


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
