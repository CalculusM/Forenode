# -*- coding: utf-8 -*-
"""전향 등록 REG-2026-003 스냅샷 산출기: 결과 미확정 추진 노선 17건의 사업성 문턱 봉인(리서치 도구, 앱 미연결).

기준 문서: 위키 03-Projects/forenode/forward-registry/REG-2026-003-pipeline-thresholds-v1.md(계산 전 커밋).
엔진 호출은 tests/_helpers(app_default_case·threshold_traffic) 읽기 전용. 엔진·config·골든 미수정.
상수(민간투자비 비율·재정요금 구조·배수·앵커·협약 평균 수익률·용량)는 config/data에서 읽어 meta JSON에 기록.

사용(저장소 루트에서):
    python research/pipeline_registry_2026_10.py --inputs <raw/03_forenode_test_inputs_v3.json> \
        --sealed-at 2026-10-15T09:00:00+09:00 [--out-dir data]
산출: <out-dir>/pipeline_registry_2026-10.csv (노선×조건점 1행) · pipeline_registry_2026-10.json (meta+노선별 전부)
조건점 9개 = 민간투자비 ×0.8/기준/×1.4 × 요금 기본(사업 유형 기본값)/재정 구조/보도값(보도 요금 없는 노선은 빈칸).
"""
import argparse
import csv
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

REGISTRY_ID, REGISTRY_VERSION, AS_OF = "REG-2026-003", "v1", "2026-10-10"
OUT_STEM = "pipeline_registry_2026-10"
CAPEX_MULT = {"사업비×0.8": 0.8, "기준": 1.0, "사업비×1.4": 1.4}
TOLL_POINTS = ("기본", "재정구조", "보도값")
OV_KEYS = ("business_type", "road_length", "bridge_ratio", "tunnel_ratio", "lanes",
           "construction_years", "operation_years", "growth_pct", "heavy_ratio_pct")
TRIG = {"①": "PIMAC 적격성 결과 보도·국토부 보도자료", "②": "제3자 제안공고 붙임(시설사업기본계획: 추정 교통량·요금 상한·총사업비)",
        "③": "실시협약 체결 보도·협약 요금", "④": "협약 교통량(국토부 민자도로 현황보고서 수록 시, 장기)"}
PROXY_S1 = "적격성 결과 축은 대용 아님. 교통량 축은 협약 교통량 확보 전 공고 추정 교통량 대용"
PROXY_S2 = "협약 교통량 확보 전 공고 추정 교통량 대용"
DUE_S1 = "S-A·S-B 2027-06-30(적격성 결과 공표 시 즉시). 협약 교통량 축 2028 이후"
DUE_S2 = "S-A·S-B 2027-12-31(공고 붙임 또는 실시협약). 협약 교통량 축 2028 이후"
# 등록 대상 17건(2026-10-10 열람 기준 단계). 키 = 노선 정식 표기, v3 = 입력 JSON의 name.
ROUTES = {
    "양재~올림픽대로": dict(v3="[후보] 양재~올림픽대로 지하도로", 구분="S1", 단계="적격성 조사 중(2025. 1.~), 전략환경영향평가 초안 공람 2026. 10. 16.까지, 결과 미공표", 트리거="①②③④"),
    "우면~용산": dict(v3="[후보] 우면~용산 지하도로", 구분="S1", 단계="적격성 조사 중(2025. 1.~), 결과 미공표(2026 4분기 예상)", 트리거="①②③④"),
    "당진~화성": dict(v3="당진~화성(제안)", 구분="S1", 단계="제안 협의 중(2026. 9.), 국토부 접수 미확인", 트리거="①②③④"),
    "고양~남양주": dict(v3="고양~남양주(HDC안, 연장 미공개)", 구분="S1", 단계="제안 접수(2024), 적격성 의뢰 보도 없음", 트리거="①②③④"),
    "경기북부 중심": dict(v3="[후보] 경기북부 중심 고속화도로", 구분="S1", 단계="제안서 접수(2025. 11.), 적격성 의뢰 미확인", 트리거="①②③④"),
    "팔공산": dict(v3="[후보] 팔공산 관통 고속도로", 구분="S1", 단계="사업의향서(2024. 11.)", 트리거="①②③④"),
    "서창~김포": dict(v3="서창~김포", 구분="S1", 단계="우협(2020. 7.), 적격성 재조사 중(2025. 12. 착수 확인)", 트리거="①②③④"),
    "사상~해운대": dict(v3="사상~해운대", 구분="S1", 단계="우협(2023. 2.), 적격성 재조사 중(2025. 6.~)", 트리거="①②③④"),
    "제4경인": dict(v3="[후보] 제4경인 고속화도로", 구분="S2", 단계="적격성 통과(2026. 4.), 제3자 공고 전", 트리거="②③④"),
    "화성~과천": dict(v3="[후보] 화성~과천 고속화도로", 구분="S2", 단계="적격성 통과(2026. 4. 말), 제3자 공고 전", 트리거="②③④"),
    "매송~동탄": dict(v3="[후보] 매송~동탄 고속화도로", 구분="S2", 단계="적격성 통과(2025. 8.), 제3자 공고 전", 트리거="②③④"),
    "용인~광주": dict(v3="[후보] 용인~광주 고속화도로", 구분="S2", 단계="적격성 통과(2023. 9.), 제3자 공고문 작성 중", 트리거="②③④"),
    "시흥~수원": dict(v3="[후보] 시흥~수원 고속화도로", 구분="S2", 단계="적격성 통과(2023. 11.), 제3자 공고 전", 트리거="②③④"),
    "화성~오산": dict(v3="[후보] 화성~오산 고속화도로", 구분="S2", 단계="우협(2026. 2.), 협상 중", 트리거="③④(②는 기공고 붙임 열람)"),
    "오산~용인": dict(v3="오산~용인", 구분="S2", 단계="우협(2020. 7.), 협상 중", 트리거="③④(②는 2020 공고 붙임 열람)"),
    "서울~양주": dict(v3="서울~양주", 구분="S2", 단계="우협(2024. 1.), 협상 중, 실시협약 목표 2026. 12.", 트리거="③④(②는 기공고 붙임 열람)"),
    "성남~서초": dict(v3="성남~서초", 구분="S2", 단계="우협(2026. 6.), 협상 중", 트리거="③④(②는 2026 공고 붙임 열람)"),
}
FORBIDDEN = (chr(0x2014), chr(0x2192))   # 줄표·화살표. 문구 금지어는 커밋 전 저장소 가드 grep으로 별도 확인
COLS = ["registry_id", "registry_version", "as_of", "구분", "노선", "노선_원문표기", "단계_asof", "사업방식", "연장_km",
        "차로", "교량비율", "터널비율", "중차량_pct", "증가율_pct", "공사기간_년", "운영기간_년", "운영기간_근거",
        "민간투자비_억", "민간투자비_근거", "총사업비_억", "건설보조금_억", "보상비_억", "구조_근거",
        "사업비_조건", "요금_조건", "조건_민간투자비_억", "조건_통행료_원km", "통행료_근거",
        "문턱_재무성립선", "문턱_DSCR1.30", "문턱_협약평균수익률", "노선별수익률_기준", "문턱_노선별수익률",
        "권장협약수요", "용량한계", "용량대비_구간", "필요요금_원km", "참고_예측교통량", "참고_교통량_근거",
        "채점트리거", "대용축_여부", "채점기한"]


def _sha256_lf(path):
    from revenue_band_display import _sha256_lf
    return _sha256_lf(path)


def _git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()
    except Exception as e:   # git 부재 시 식별 불가를 그대로 기록
        return f"unavailable({e.__class__.__name__})"


def resolve_capex(r, ratio, td, pr):
    """민간투자비: 입력값 > 총사업비 차감 > 총사업비×전국 비율(추정) > 단가 모형(참고, 사업비 미공개 노선만)."""
    if r.get("total_capex") is not None:
        return r["total_capex"], "민간투자비 입력값"
    if r.get("total_project_cost") is not None:
        return td.resolve_private_capex(r["total_project_cost"], r.get("subsidy"), r.get("land"), ratio)
    est = pr.estimate_capex_from_route(r["road_length"], r["lanes"], r.get("terrain", "평지"),
                                       r["bridge_ratio"], r["tunnel_ratio"], r["business_type"])
    return est["capex_estimate_억"], "단가 모형 추정(참고, 사업비 미공개)"


def run_point(H, td, r, capex, toll, crit):
    ov = {k: r[k] for k in OV_KEYS if r.get(k) is not None}
    ov["total_capex"] = capex
    case = H.app_default_case(toll_per_km=toll, **ov)
    th = {k: H.threshold_traffic(case, c, t)[0] for k, (c, t) in crit.items()}
    th = {k: (None if v is None else round(v)) for k, v in th.items()}
    gov, limit = th["재무성립선"], case["cap_limit"]
    out = {"조건_민간투자비_억": capex, "조건_통행료_원km": case["toll_per_km"], "용량한계": limit, **th}
    if gov:
        rec = gov / H.TRAFFIC_ANCHOR_RATIO
        out["권장협약수요"] = round(rec)
        out["용량대비_구간"] = "C" if gov > limit else ("B" if rec > limit else "A")
        out["필요요금_원km"] = td.required_toll_at_capacity(case["toll_per_km"], gov, limit) if gov > limit else None
    return out


def build(inputs_path, sealed_at):
    import _helpers as H
    import config_loader
    import pretest_regressor as pr
    import threshold_display as td
    fin = config_loader.load_finance_params()
    ratio = fin["private_share_of_total_cost"]["value"]   # 봉인 도구는 config 결손 시 폴백 없이 중단
    fs, tb = fin["fiscal_toll_structure"], fin["toll_benchmark"]
    cov_rate, cov_label = config_loader.covenant_return_rate()
    base_crit = {"재무성립선": ("gov", 0.0), "DSCR1.30": ("dscr", 1.30), "협약평균수익률": ("real_irr", cov_rate)}
    by_name = {r["name"]: r for r in json.load(open(inputs_path, encoding="utf-8"))}
    golden = H.load_golden()
    meta = {
        "registry_id": REGISTRY_ID, "registry_version": REGISTRY_VERSION, "as_of": AS_OF, "sealed_at": sealed_at,
        "engine_commit": _git("rev-parse", "HEAD"), "engine_branch": _git("branch", "--show-current"),
        "engine_uncommitted_files": [l[3:] for l in _git("status", "--porcelain").splitlines() if l.strip()],
        "golden_sha256": _sha256_lf(H.GOLDEN_PATH),
        "finance_params_sha256": _sha256_lf(os.path.join(ROOT, "config", "finance_params.json")),
        "requirements_sha256": _sha256_lf(os.path.join(ROOT, "requirements.txt")),
        "inputs_file": os.path.basename(inputs_path), "inputs_sha256": _sha256_lf(inputs_path),
        "panel_version": golden["_meta"]["panel_version"],
        "constants_used": {"private_share_of_total_cost": ratio, "fiscal_base_won": fs["base_won"],
                           "fiscal_per_km_won_class1": fs["per_km_won_class1"], "policy_cap_mult": tb["policy_cap_mult"],
                           "traffic_anchor_ratio": H.TRAFFIC_ANCHOR_RATIO, "covenant_return_rate": cov_rate,
                           "covenant_label": cov_label, "dscr_min": 1.30},
        "condition_points": {"capex": CAPEX_MULT, "toll": list(TOLL_POINTS)},
        "reference_point": "사업비 기준 × 요금(보도값 있으면 보도값, 없으면 기본). S-A 비율의 분모",
        "triggers": TRIG,
        "notice": "자체 기준의 성립 조건 봉인. 적격성 통과 여부와 무관, 경제성(B/C)·정책성 미산출. 구간 A/B/C는 용량 대비 자체 구간",
    }
    routes, rows = [], []
    for name, spec in ROUTES.items():
        r = by_name[spec["v3"]]
        b = r.get("basis", {})
        capex0, basis = resolve_capex(r, ratio, td, pr)
        crit = dict(base_crit)
        for c, t in (r.get("extra_criteria") or []):
            crit["노선별수익률"] = (c, t)
        # '기본' = 사업 유형 고정값(85원/km). 2026-10-14 앱 자동값이 재정요금 구조로 바뀐 뒤에도 봉인 스냅샷과 같은 값을 재현하도록 명시
        _bd_toll = float(config_loader.business_defaults()[r["business_type"]]["toll"])
        tolls = {"기본": (_bd_toll if _bd_toll > 0 else None, "사업 유형 고정값"),
                 "재정구조": (td.fiscal_toll_per_km(r["road_length"], fs["base_won"], fs["per_km_won_class1"], tb["policy_cap_mult"]),
                             "재정요금 구조(기본요금+1종 주행요금×연장)×정책 배수÷연장"),
                 "보도값": (r.get("toll_reported"), b.get("toll", ""))}
        common = {"registry_id": REGISTRY_ID, "registry_version": REGISTRY_VERSION, "as_of": AS_OF,
                  "구분": spec["구분"], "노선": name, "노선_원문표기": r["name"], "단계_asof": spec["단계"],
                  "사업방식": r["business_type"], "연장_km": r["road_length"], "차로": r["lanes"],
                  "교량비율": r["bridge_ratio"], "터널비율": r["tunnel_ratio"],
                  "중차량_pct": r.get("heavy_ratio_pct", H.APP_DEFAULT_INPUTS["heavy_ratio_pct"]),
                  "증가율_pct": r.get("growth_pct", H.APP_DEFAULT_INPUTS["growth_pct"]),
                  "공사기간_년": r["construction_years"], "운영기간_년": r["operation_years"], "운영기간_근거": b.get("op", ""),
                  "민간투자비_억": capex0, "민간투자비_근거": f'{basis}. {b.get("cost", "")}',
                  "총사업비_억": r.get("total_project_cost"), "건설보조금_억": r.get("subsidy"), "보상비_억": r.get("land"),
                  "구조_근거": b.get("structure", ""), "노선별수익률_기준": crit.get("노선별수익률", (None, None))[1],
                  "참고_예측교통량": r.get("forecast_aadt"), "참고_교통량_근거": b.get("traffic", ""),
                  "채점트리거": spec["트리거"], "대용축_여부": PROXY_S1 if spec["구분"] == "S1" else PROXY_S2,
                  "채점기한": DUE_S1 if spec["구분"] == "S1" else DUE_S2}
        points = []
        for clabel, m in CAPEX_MULT.items():
            for tlabel in TOLL_POINTS:
                toll, tbasis = tolls[tlabel]
                pt = {"사업비_조건": clabel, "요금_조건": tlabel, "통행료_근거": tbasis}
                if tlabel != "보도값" or toll:
                    res = run_point(H, td, r, round(capex0 * m), toll, crit)
                    pt.update({"조건_민간투자비_억": res["조건_민간투자비_억"], "조건_통행료_원km": res["조건_통행료_원km"],
                               "문턱_재무성립선": res["재무성립선"], "문턱_DSCR1.30": res["DSCR1.30"],
                               "문턱_협약평균수익률": res["협약평균수익률"], "문턱_노선별수익률": res.get("노선별수익률"),
                               "권장협약수요": res.get("권장협약수요"), "용량한계": res["용량한계"],
                               "용량대비_구간": res.get("용량대비_구간"), "필요요금_원km": res.get("필요요금_원km")})
                points.append(pt)
                rows.append({**common, **pt})
        ref_toll = "보도값" if tolls["보도값"][0] else "기본"
        ref = next(p for p in points if p["사업비_조건"] == "기준" and p["요금_조건"] == ref_toll)
        routes.append({**common, "reference": {"요금_조건": ref_toll, "문턱_재무성립선": ref["문턱_재무성립선"],
                                               "통행료_원km": ref["조건_통행료_원km"], "민간투자비_억": capex0,
                                               "총사업비_억": r.get("total_project_cost"), "구간": ref["용량대비_구간"]},
                       "points": points})
    return {"meta": meta, "routes": routes}, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", required=True, help="raw/03_forenode_test_inputs_v3.json 경로")
    ap.add_argument("--sealed-at", required=True, help="봉인 시각(ISO 8601, 수기 지정. 실행 시각 자동 기록 없음)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data"))
    a = ap.parse_args(argv)
    inputs, out_dir = os.path.abspath(a.inputs), os.path.abspath(a.out_dir)
    os.chdir(ROOT)
    reg, rows = build(inputs, a.sealed_at)
    os.makedirs(out_dir, exist_ok=True)
    jpath, cpath = os.path.join(out_dir, OUT_STEM + ".json"), os.path.join(out_dir, OUT_STEM + ".csv")
    with open(jpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    with open(cpath, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in COLS})
    text = open(cpath, encoding="utf-8-sig").read() + open(jpath, encoding="utf-8").read()
    bad = [s for s in FORBIDDEN if s in text]
    assert not bad, f"금지 문자열 검출: {bad}"
    assert len(rows) == len(ROUTES) * len(CAPEX_MULT) * len(TOLL_POINTS), "행 수 불일치"
    print(f"{REGISTRY_ID} {REGISTRY_VERSION} as_of {AS_OF} sealed_at {a.sealed_at} engine {reg['meta']['engine_commit'][:7]}")
    print(f"노선 {len(reg['routes'])}건 · 행 {len(rows)} · {cpath}")
    for rt in reg["routes"]:
        ref = rt["reference"]
        print(f'  [{rt["구분"]}] {rt["노선"]}: 기준점({ref["요금_조건"]} {ref["통행료_원km"]}원/km, 민간투자비 {ref["민간투자비_억"]}억) '
              f'재무 성립선 문턱 {ref["문턱_재무성립선"]}대 · 구간 {ref["구간"]}')


if __name__ == "__main__":
    main()
