# -*- coding: utf-8 -*-
"""노선 문턱표 v0(P1-05): 추진현황 스터디 결과 JSON에서 노선당 Markdown 1장을 만든다.

리서치·영업 재료 전용(회신 후 2차 단계·검산 납품), 앱 화면 기능화 금지(rnd-ontrack §8). 발송 전 대표 승인.
첫 접촉 메일 첨부 금지. 성립 조건(문턱·권장 수요·여유 배수·조건 변경 경로)만 싣고 등급·통과 여부는 싣지 않는다.

입력(스터디 raw 폴더): 04_forenode_test_results_v3.json(2절 입력 결과, 기준·사업 유형 기본 요금 고정 행),
  04_five_input_results.json(5개 입력), 11_capex_sensitivity.json(사업비 ×0.8·×1.2·×1.4), 03_forenode_test_inputs_v3.json(근거 문구).
엔진 호출(앱 경로 tests/_helpers): 2절 입력 재구성으로 재무 성립선 문턱 재검(JSON과 1대 이내, 불일치 시 중단),
  용량 초과 시 필요 보조금(reverse_solver.max_capex_for, 한계 교통량 수입 기준), 요금 배수 없는 재정 구조 환산 민감도.
숫자 상수는 config/finance_params.json에서 읽는다. 응답자·접촉사 정보는 입력에 없고 출력에도 쓰지 않는다.

사용: python research/pipeline_sheet.py --routes "용인~광주 고속화도로,서울~양주" [--raw DIR] [--out DIR]
"""
import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _helpers as H                     # noqa: E402
import config_loader                     # noqa: E402
import threshold_display as thd          # noqa: E402

# 스터디 폴더 기본 위치(저장소 형제 폴더). 다른 위치는 --raw 로 지정
DEFAULT_RAW = os.path.join(ROOT, "..", "..", "창업실습_3학년2학기", "시장조사_민자고속도로_추진현황_2026-10", "raw")
DEFAULT_OUT = os.path.join(ROOT, "research", "out", "pipeline_sheets_2026-10")
FIXTURE_META = os.path.join(ROOT, "tests", "fixtures", "five_input_cases_2026-10.json")
RESULTS, FIVE, CAPEX_SENS, INPUTS = ("04_forenode_test_results_v3.json", "04_five_input_results.json",
                                     "11_capex_sensitivity.json", "03_forenode_test_inputs_v3.json")
FORBIDDEN = (chr(0x2014), chr(0x2192), "유일", "예측 시점 이후", "15/21", "21개 중 15개", "정부 게이트", "회귀 범위", "미통과")
_FP = config_loader.load_finance_params()
FISCAL, MULT = _FP["fiscal_toll_structure"], _FP["toll_benchmark"]["policy_cap_mult"]
SHARE = _FP["private_share_of_total_cost"]
ANCHOR = _FP["demand_anchor"]


def _norm(name: str) -> str:
    return re.sub(r"^\[[^\]]*\]\s*", "", name)


def _load(raw: str, fn: str) -> list:
    with open(os.path.join(raw, fn), encoding="utf-8") as f:
        return json.load(f)


STATUS = {"ok": "산출", "below_range": "탐색 하한 미만", "infeasible": "산출 불가"}


def _grade(text: str) -> str:
    """근거 문구에서 등급 추출. 문구가 없으면 빈칸(추정 금지)."""
    if not text:
        return ""
    for word, g in (("확인", "확인값"), ("추정", "추정"), ("가정", "추정"), ("공고", "공고"), ("보도", "보도"), ("2차", "2차")):
        if word in text:
            return g
    return "출처 미표기"


def _fmt(x, unit="") -> str:
    return "" if x is None else f"{x:,.0f}{unit}"


def _panel_version() -> str:
    try:
        with open(os.path.join(H.DATA, "realization_panel.csv"), encoding="utf-8-sig") as f:
            return next(csv.DictReader(f))["panel_version"]
    except Exception:
        return H.load_golden()["_meta"].get("panel_version", "")


def _git_head() -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def _engine(res: dict) -> dict:
    """2절 입력으로 앱 경로 재구성. 재무 성립선 문턱이 JSON과 1대 이내가 아니면 중단(엔진·JSON 불일치)."""
    import app
    import reverse_solver as rsv
    case = H.app_default_case(**res["inputs"])
    gov, _ = H.threshold_traffic(case, "gov")
    assert abs(gov - res["thresholds"]["gov"]["traffic"]) <= H.load_golden()["_tolerance"]["traffic_대"], \
        f'{res["name"]}: 엔진 재검 {gov:.0f} vs JSON {res["thresholds"]["gov"]["traffic"]}'
    out = {"subsidy": 0.0}
    if gov > case["cap_limit"]:
        out["subsidy"] = rsv.max_capex_for(case["base_params"], app.build_cashflow, rsv.make_predicate("gov"),
                                           ann_rev=case["rev_K"] * case["cap_limit"]).get("subsidy_억")
    if res["toll_scenario"] == "fiscal":
        ov = {**res["inputs"], "toll_per_km": thd.fiscal_toll_per_km(res["inputs"]["road_length"], FISCAL["base_won"],
                                                                     FISCAL["per_km_won_class1"])}
        t, _ = H.threshold_traffic(H.app_default_case(**ov), "gov")
        out["fiscal_no_mult"] = (ov["toll_per_km"], t)
    return out


def _sens_row(label: str, r: dict | None, extra: str = "") -> str:
    if not r:
        return f"| {label} | | | | {extra or '자료 없음'} |"
    return (f"| {label} | {r['inputs']['toll_per_km']} | {_fmt(r['thresholds']['gov']['traffic'])} | "
            f"{_fmt(r.get('recommended_agreement_traffic'))} | {extra} |")


def build_sheet(route: str, raw: str, repro: dict) -> str:
    rows = [r for r in _load(raw, RESULTS) if _norm(r["name"]) == route and "error" not in r]
    res = next(r for r in rows if r["toll_scenario"] != "flat")
    flat = next((r for r in rows if r["toll_scenario"] == "flat"), None)
    five = next((r for r in _load(raw, FIVE) if _norm(r["name"]) == route), None)
    sens = [r for r in _load(raw, CAPEX_SENS) if _norm(re.sub(r"^\[사업비 [^\]]*\]\s*", "", r["name"])) == route]
    basis = next(r for r in _load(raw, INPUTS) if _norm(r["name"]) == route).get("basis", {})
    inp, th, cap = res["inputs"], res["thresholds"], res["capacity"]
    gov, limit = th["gov"]["traffic"], cap["limit"]
    eng = _engine(res)
    rate, rate_label = config_loader.covenant_return_rate()
    toll_src = {"reported": basis.get("toll", "보도·공고 요금"), "fiscal": "재정요금 구조 환산값(기본요금+1종 주행요금, 제안 배수 적용)",
                "flat": "사업 유형 기본 요금"}[res["toll_scenario"]]
    inputs7 = [
        ("사업 유형", inp["business_type"], basis.get("type", ""), _grade(basis.get("type", ""))),
        ("연장(km)", inp["road_length"], basis.get("length", ""), _grade(basis.get("length", ""))),
        ("민간투자비(억 원)", _fmt(inp["total_capex"]), basis.get("cost", ""),
         {"민간투자비 입력값": "확인값", "총사업비-건설보조금-보상비": "차감"}.get(res["capex_basis"], "추정")),
        ("통행료(원/km)", inp["toll_per_km"], toll_src, {"reported": _grade(toll_src), "fiscal": "환산", "flat": "기본값"}[res["toll_scenario"]]),
        ("운영기간(년)", inp["operation_years"], basis.get("op", ""), _grade(basis.get("op", ""))),
        ("구조 비율(교량·터널)", f"{inp['bridge_ratio']:.0%}·{inp['tunnel_ratio']:.0%}", basis.get("structure", ""), _grade(basis.get("structure", ""))),
        ("차로(왕복)", inp["lanes"], basis.get("lanes", ""), _grade(basis.get("lanes", ""))),
    ]
    th_rows = [("재무 성립선(자체 기준)", th["gov"], "수입/비용 현가비율 1.0·NPV 0 이상"),
               ("DSCR 1.30(대주단 기준)", th["dscr_1.30"], "최소 DSCR"),
               (rate_label, th[f"real_irr_{rate:g}"], "실질 세후 사업수익률")]
    for key, v in th.items():
        if key.startswith("real_irr_") and key != f"real_irr_{rate:g}":
            th_rows.append((f"노선 수익률 기준(실질 세후 {float(key.split('_')[-1]):.2%})", v, basis.get("rate", "노선 공개 수익률")))
    lo, hi = res["capex_reference_range_억"]
    need_toll, sub = res.get("toll_per_km_needed_at_capacity"), eng["subsidy"]
    L = [
        f"# 노선 문턱표 v0: {route}",
        "",
        f"생성 {repro['date']} · 조사 as_of {repro['as_of']} · 입력 기준 2절(구조 비율·공사기간 노선값). {thd.NOTICE}",
        "",
        "## 1. 입력 7종과 근거 등급",
        "",
        "| 항목 | 적용 값 | 근거 | 등급 | 귀사 값 대입란 |",
        "|---|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |  |" for a, b, c, d in inputs7],
        "",
        "## 2. 문턱(기준별 최소 일 통행량, 대/일)",
        "",
        "| 기준 | 문턱 | 상태 | 정의 |",
        "|---|---|---|---|",
        *[f"| {a} | {_fmt(v['traffic'])} | {STATUS.get(v['status'], v['status'])} | {c} |" for a, v, c in th_rows],
        "",
        "## 3. 권장 협약 수요·차로 용량",
        "",
        f"- 권장 협약 수요: {_fmt(res.get('recommended_agreement_traffic'), '대')} (재무 성립선 문턱 ÷ 교통량 실현율 앵커 {ANCHOR['traffic_realization_mean']}, {ANCHOR['n_routes']}개 노선 평균).",
        f"- 왕복 {inp['lanes']}차로 용량: 경고 {_fmt(cap['warn'], '대')}, 한계 {_fmt(limit, '대')}. 여유 배수 {thd.headroom(limit, gov):.2f}배(한계 ÷ 문턱).",
        f"- {thd.condition_core(gov, limit, inp['lanes'], bold=False)}",
        *([f"- 공개 참고 교통량(비교점, 채점·대조 아님): {_fmt(res['forecast_aadt'], '대')}, 재무 성립선 문턱 대비 {res['forecast_over_gov_threshold']}배. 출처: {basis.get('traffic', '')}."]
          if res.get("forecast_aadt") else []),
        "",
        "## 4. 조건 변경 경로(한계 교통량 초과 시)",
        "",
        f"- 용량 내 성립 필요 통행료(수입 비례 근사, 수요 탄력 미반영): {f'{need_toll}원/km' if need_toll else '해당 없음(한계 내 성립)'}.",
        f"- 필요 건설보조금(민간투자비 축소분, 한계 교통량 수입 기준): {f'{sub:,.0f}억 원' if sub else '0억 원(한계 내 성립)'}.",
        "",
        "## 5. 공사비 참고 범위",
        "",
        f"- 민간투자비 {_fmt(inp['total_capex'], '억 원')}({res['capex_basis']}), km당 {res['capex_per_km_억']}억 원.",
        f"- 단가 모형 참고 범위 {_fmt(lo)}~{_fmt(hi)}억 원, 범위 {'내' if res['capex_in_reference_range'] else '밖'}. 모형은 지상 고속도로 단가 기준, 지하·대심도 노선은 범위 밖이 정상.",
        "",
        "## 6. 민감도",
        "",
        "| 시나리오 | 통행료(원/km) | 재무 성립선 문턱 | 권장 협약 수요 | 비고 |",
        "|---|---|---|---|---|",
        _sens_row("기준(2절 입력)", res, f"운영 {inp['operation_years']}년"),
        _sens_row("사업 유형 기본 요금 고정", flat, "요금 외 동일"),
        (f"| 재정 구조 환산, 제안 배수 없음 | {eng['fiscal_no_mult'][0]} | {_fmt(eng['fiscal_no_mult'][1])} | "
         f"{_fmt(eng['fiscal_no_mult'][1] / H.TRAFFIC_ANCHOR_RATIO)} | 엔진 재실행 |") if "fiscal_no_mult" in eng
        else "| 재정 구조 환산, 제안 배수 없음 | | | | 해당 없음(보도·공고 요금 적용 노선) |",
        _sens_row("5개 입력만(구조 비율·공사기간 기본값)", five, f"운영 {five['inputs']['operation_years']}년" if five else ""),
        *[_sens_row(f"사업비 {re.search(r'\[사업비 ([^\]]*)\]', r['name']).group(1)}",
                    r, f"민간투자비 {_fmt(r['inputs']['total_capex'])}억 원, {r.get('note', '')}") for r in sens],
        "",
        "## 7. 단서(인쇄 필수 9개)",
        "",
        f"1. 민간투자비 근거: {res['capex_basis']}. 총사업비×{SHARE['value']} 추정값은 {SHARE['as_of']}년 전국 비율(민간투자비 {_fmt(SHARE['numerator_eok'])}억 원 ÷ 투자비 {_fmt(SHARE['denominator_eok'])}억 원), 확인 사례 분산 {SHARE['dispersion']}. 추정 노선은 실제값 대입 필요.",
        f"2. 요금 가정: 재정요금 구조(기본요금 {FISCAL['base_won']}원 + 1종 주행요금 {FISCAL['per_km_won_class1']}원/km) × 제안 배수 {MULT} 환산값. 배수 근거는 2차 출처, 지하·소형차 전용 노선에는 과소. 본 노선 적용 요금: {toll_src}.",
        f"3. 구조 비율: {basis.get('structure', '기본값')}. 추정값은 운영비 산정에 오차.",
        f"4. 터널 비율 {inp['tunnel_ratio']:.0%} 적용. 앱 입력 상한 적용 노선은 초과분 유지관리비 과소 반영 가능.",
        "5. 손익공유형(BTO-a) 최소사업운영비 보전·초과이익 공유 산식 미구현, 보전 없음 가정(보수).",
        "6. 개량운영형 사업 구조 미적용(신설 노선 기준 계산).",
        "7. 적격성 조사(KDI PIMAC) 판정 아님. 예측·협약 교통량과 미대조, 경제성(B/C)·정책성 미산출. 성립 조건 수치만 제시.",
        "8. 문턱은 권장 수요 앵커 기준 운영비 규모에 의존. 차로 수·사업비 변경 시 문턱이 비단조로 이동 가능.",
        f"9. 재현 정보: 엔진 커밋 {repro['head']}, panel_version {repro['panel_version']}, 데이터 as_of {repro['as_of']}, 결과 파일 {RESULTS}·{FIVE}·{CAPEX_SENS}, 생성 스크립트 research/pipeline_sheet.py.",
        "",
    ]
    text = "\n".join(L)
    bad = [w for w in FORBIDDEN if w in text]
    assert not bad, f"{route}: 금지 표현 {bad}"
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--routes", required=True, help="노선명 쉼표 구분(결과 JSON name에서 [후보] 등 꼬리표 제외)")
    ap.add_argument("--raw", default=DEFAULT_RAW)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    with open(FIXTURE_META, encoding="utf-8") as f:
        as_of = json.load(f)["_meta"]["as_of"]
    repro = {"date": datetime.date.today().isoformat(), "as_of": as_of, "head": _git_head(), "panel_version": _panel_version()}
    os.makedirs(a.out, exist_ok=True)
    for route in [r.strip() for r in a.routes.split(",") if r.strip()]:
        path = os.path.join(a.out, f"{route}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_sheet(route, a.raw, repro))
        print("생성:", path)


if __name__ == "__main__":
    main()
