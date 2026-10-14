# -*- coding: utf-8 -*-
"""REG-2026-003 채점 실행기(R2): 봉인 스냅샷 JSON(읽기 전용) + 결과 원장 CSV(append만) 입력, 채점 CSV 출력.

채점 정의(기준 문서 3절, 결과 보기 전 봉인):
  S-A 조건 격차: 결과값 ÷ 봉인 기준점 값(교통량·요금·총사업비)의 비율 기록. 적중·미적중 없음.
  S-B 엔진 정합: 공고총사업비 + 공고요금상한(또는 협약요금) + 공고추정교통량(또는 협약교통량)이 모두 있는 노선만
      봉인 입력에 확정 입력을 덮어 재실행한 재무 성립선 문턱 ÷ 교통량. 0.75~1.25 안이면 정합. 셋 중 하나라도 없으면 '채점 불가'.
  S-C 방향 참고: 적격성결과가 부적격·재정전환인 노선의 봉인 기준점 구간이 C였는지 건수만. 판별력 서술 없음.
결과 원장 열: 노선,결과종류,값,공개일,출처,출처등급,비고. 값 단위 = 교통량 대/일, 요금 원/km, 사업비 억 원.
사용(저장소 루트에서):
    python research/score_pipeline_registry.py --date 2026-12-31 [--registry data/pipeline_registry_2026-10.json]
        [--outcomes data/route_pipeline_outcomes.csv] [--out-dir data]
"""
import argparse
import csv
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

OUTCOME_COLS = ["노선", "결과종류", "값", "공개일", "출처", "출처등급", "비고"]
TRAFFIC_KINDS = ("공고추정교통량", "협약교통량", "참고")
TOLL_KINDS = ("공고요금상한", "협약요금")
COST_KIND, RESULT_KIND = "공고총사업비", "적격성결과"
NEGATIVE_RESULTS = ("부적격", "재정전환", "재정 전환", "탈락")
SB_BAND, SB_TARGET = (0.75, 1.25), 0.70
SCORE_COLS = ["채점일", "노선", "결과종류", "값", "공개일", "출처등급", "축", "대용축", "봉인기준값", "비율",
              "S-B_재실행문턱", "S-B_비율", "S-B_정합", "비고"]


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _rerun_gov(route, meta, cost, toll):
    """봉인 입력에 확정 총사업비(×봉인 비율, 추정)·확정 요금을 덮어 재무 성립선 문턱 재실행(봉인 엔진 커밋에서 실행할 것)."""
    import _helpers as H
    ov = {"business_type": route["사업방식"], "road_length": route["연장_km"], "bridge_ratio": route["교량비율"],
          "tunnel_ratio": route["터널비율"], "lanes": route["차로"], "construction_years": route["공사기간_년"],
          "operation_years": route["운영기간_년"], "growth_pct": route["증가율_pct"], "heavy_ratio_pct": route["중차량_pct"],
          "total_capex": round(cost * meta["constants_used"]["private_share_of_total_cost"])}
    gov, _ = H.threshold_traffic(H.app_default_case(toll_per_km=toll, **ov), "gov")
    return None if gov is None else round(gov)


def score(reg, outcomes, date=""):
    routes = {r["노선"]: r for r in reg["routes"]}
    rows, by_route = [], {}
    for o in outcomes:
        r = routes.get(o["노선"])
        row = {"채점일": date, **{k: o.get(k, "") for k in ("노선", "결과종류", "값", "공개일", "출처등급", "비고")}}
        if r is None:
            rows.append({**row, "비고": "봉인 목록 외 노선, 채점 제외"})
            continue
        ref, kind, val = r["reference"], o["결과종류"], _num(o.get("값"))
        by_route.setdefault(o["노선"], {})[kind] = val
        if kind in TRAFFIC_KINDS:
            row.update(축="S-A 교통량", 대용축="N" if kind == "협약교통량" else "Y", 봉인기준값=ref["문턱_재무성립선"])
        elif kind in TOLL_KINDS:
            row.update(축="S-A 요금", 대용축="N", 봉인기준값=ref["통행료_원km"])
        elif kind == COST_KIND:
            row.update(축="S-A 사업비", 대용축="N", 봉인기준값=ref.get("총사업비_억"))
        elif kind == RESULT_KIND:
            row.update(축="S-C", 대용축="N", 봉인기준값=ref["구간"])
        else:
            row["비고"] = f"결과종류 미정의({kind})"
        base = row.get("봉인기준값")
        if val is not None and isinstance(base, (int, float)) and base:
            row["비율"] = round(val / base, 3)
        rows.append(row)
    sb = {}
    for name, got in by_route.items():
        cost = got.get(COST_KIND)
        toll = next((got[k] for k in TOLL_KINDS if got.get(k) is not None), None)
        traffic = next((got[k] for k in ("협약교통량", "공고추정교통량") if got.get(k) is not None), None)
        if None in (cost, toll, traffic):
            sb[name] = "채점 불가"
            continue
        gov = _rerun_gov(routes[name], reg["meta"], cost, toll)
        ratio = None if not gov else round(gov / traffic, 3)
        sb[name] = {"재실행문턱": gov, "비율": ratio, "정합": ratio is not None and SB_BAND[0] <= ratio <= SB_BAND[1]}
    for row in rows:
        v = sb.get(row["노선"])
        if isinstance(v, dict) and row["결과종류"] in ("협약교통량", "공고추정교통량"):
            row.update({"S-B_재실행문턱": v["재실행문턱"], "S-B_비율": v["비율"], "S-B_정합": "정합" if v["정합"] else "비정합"})
        elif v == "채점 불가" and row.get("축", "").startswith("S-A"):
            row["S-B_정합"] = "채점 불가"
    neg = [n for n, g in by_route.items() if str(outcomes_value(outcomes, n, RESULT_KIND)) in NEGATIVE_RESULTS]
    sb_done = [v for v in sb.values() if isinstance(v, dict)]
    summary = {
        "채점 가능": len([r for r in rows if r.get("축")]),
        "S-A 건수": len([r for r in rows if r.get("축", "").startswith("S-A") and r.get("비율") is not None]),
        "S-A 대용축 건수": len([r for r in rows if r.get("대용축") == "Y"]),
        "S-B 정합": sum(1 for v in sb_done if v["정합"]), "S-B n": len(sb_done),
        "S-B 채점 불가 노선": sorted(n for n, v in sb.items() if v == "채점 불가"),
        "S-C 부적격·재정전환 건수": len(neg),
        "S-C 그중 봉인 구간 C": sum(1 for n in neg if routes[n]["reference"]["구간"] == "C"),
    }
    return rows, summary


def outcomes_value(outcomes, name, kind):
    return next((o.get("값") for o in outcomes if o["노선"] == name and o["결과종류"] == kind), None)


def log_entry(reg, summary, date, out_csv):
    m = reg["meta"]
    sb = f'{summary["S-B 정합"]}/{summary["S-B n"]}' if summary["S-B n"] else "채점 가능 노선 0(정합 판정 없음)"
    return "\n".join([
        f"## R-002 · {date} · 전향 등록 채점 · {m['registry_id']} {m['registry_version']} (제안 전 노선 문턱 봉인)",
        f"- 방법: 기준 문서 3절 채점 정의 S-A·S-B·S-C 그대로. 봉인 엔진 {m['engine_commit'][:7]} · golden {m['golden_sha256'][:8]} · panel {m['panel_version']}",
        f"- 데이터: 결과 원장 {summary['채점 가능']}건(대용축 {summary['S-A 대용축 건수']}건). 봉인 JSON 불변(sealed_at {m['sealed_at']})",
        f"- 결과: S-A 비율 기록 {summary['S-A 건수']}건 · S-B 정합 {sb}(사전 선언 목표 {SB_TARGET:.0%}, 구간 {SB_BAND[0]}~{SB_BAND[1]}) · "
        f"S-C 부적격·재정전환 {summary['S-C 부적격·재정전환 건수']}건 중 봉인 구간 C {summary['S-C 그중 봉인 구간 C']}건(건수만, 판별력 서술 없음)",
        "- 관찰: (수기 기입. 비율 해석은 조건 격차 보고로 한정)",
        f"- 산출물: {out_csv}",
        f"- 한계: S-B 채점 불가 노선 {len(summary['S-B 채점 불가 노선'])}건 · 대용축(공고 추정 교통량·분산량)은 협약 교통량 아님 · 공고총사업비 재실행은 봉인 비율 환산(추정)",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="채점일(YYYY-MM-DD). 출력 파일명에 사용")
    ap.add_argument("--registry", default=os.path.join(ROOT, "data", "pipeline_registry_2026-10.json"))
    ap.add_argument("--outcomes", default=os.path.join(ROOT, "data", "route_pipeline_outcomes.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data"))
    a = ap.parse_args(argv)
    with open(a.registry, encoding="utf-8") as f:
        reg = json.load(f)
    with open(a.outcomes, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        assert rd.fieldnames == OUTCOME_COLS, f"결과 원장 열 불일치: {rd.fieldnames}"
        outcomes = [o for o in rd if o.get("노선")]
    rows, summary = score(reg, outcomes, a.date)
    os.makedirs(a.out_dir, exist_ok=True)
    out_csv = os.path.join(a.out_dir, f"pipeline_registry_scores_{a.date}.csv")
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCORE_COLS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in SCORE_COLS})
    print(f"채점 가능 {summary['채점 가능']}건 · {json.dumps(summary, ensure_ascii=False)}")
    print(log_entry(reg, summary, a.date, os.path.relpath(out_csv, ROOT)))


if __name__ == "__main__":
    main()
