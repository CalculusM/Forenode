# -*- coding: utf-8 -*-
"""D1·D4: 추진 노선 파이프라인 데이터셋 빌드(엔진 미반영, research 전용 도구).

입력(스터디 raw 사본, ForenodeMain/_research_sources/pipeline_2026-10/):
  00_image_routes_2026-09.json      추진현황 그림 단계(2026-09-30)
  03_five_input_inputs.json         5개 입력 시험 36건 입력·근거 문자열
  04_five_input_results.json        같은 36건의 실행 입력·문턱(재무 성립선)·권장 협약 수요
  03_forenode_test_inputs_v3.json   보강 입력(교량·터널·차로·중차량) 근거
  08_reality_side.json              실제 쪽 조사(예측 교통량·요금·수익률·출처)
  07_study_v6_tables.json           6판 7절 표 7 실제 결과(2026-10-07), 3절 주무관청·제안자, 미시험 3건
  data/koti_rr2510_return_rates.csv D4 KOTI RR-25-10 투자비계·건설보조금 비율
출력: data/route_pipeline_2026-10.csv(UTF-8 BOM, 한글 헤더, 결측 빈칸), data/route_pipeline_2026-10.meta.json
실행: 저장소 루트에서 python research/build_route_pipeline.py (문턱 재계산은 tests/_helpers 경로, 약 1분 이내)
규칙: 추정으로 빈칸을 메우지 않는다. 36행의 5개 입력(사업방식·연장·민간투자비·통행료·운영기간)은
      04_five_input_results.json의 실행 입력과 동일해야 한다(tests/test_route_pipeline.py가 ±1대 재현을 확인).
"""
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import warnings
from collections import OrderedDict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(os.path.dirname(ROOT), "_research_sources", "pipeline_2026-10")
DATA = os.path.join(ROOT, "data")
OUT_CSV = os.path.join(DATA, "route_pipeline_2026-10.csv")
OUT_META = os.path.join(DATA, "route_pipeline_2026-10.meta.json")
KOTI_CSV = os.path.join(DATA, "koti_rr2510_return_rates.csv")
for _p in (ROOT, os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")

import config_loader                       # noqa: E402
import _helpers as H                       # noqa: E402
from pipeline_loader import route_key      # noqa: E402

PIPELINE_VERSION = "v1_2026-10-07"
ASOF_SURVEY = "2026-10-07"
ASOF_IMAGE = "2026-09-30"
FIVE = ("business_type", "road_length", "total_capex", "toll_per_km", "operation_years")
CONFLICT_TOL = 0.05     # 같은 항목 값이 5% 넘게 다르면 상충값으로 기재(자체 규칙, 반올림 차이 제외)
INPUT_FILES = ["00_image_routes_2026-09.json", "03_five_input_inputs.json", "04_five_input_results.json",
               "03_forenode_test_inputs_v3.json", "08_reality_side.json", "07_study_v6_tables.json"]
IMAGE_STAGE = {"제안단계": "제안", "환경평가단계": "환경평가", "설계단계": "설계", "건설중": "건설중"}
STAGE_ORDER = [("재정 전환", "재정전환"), ("부적격", "부적격"), ("건설 중", "건설"), ("실시협약", "실시협약"),
               ("협상", "협상"), ("재조사", "재조사중"), ("우협", "우협"), ("통과", "통과"), ("조사 중", "조사중"),
               ("의향서", "의향서"), ("미접수", "미접수"), ("접수", "접수")]
CONFLICT_WORDS = ("상충", "범위", "병기", "증액", "원안")
PRIMARY_SOURCE = re.compile(r"\.go\.kr|korea\.kr|pimac|RR-\d|MP-\d")

COLUMNS = [
    "pipeline_version", "노선", "노선_원문표기", "주무관청", "그림단계_asof_2026-09-30", "조사단계_asof_2026-10-07",
    "조사단계_원문", "제안자", "사업방식", "사업방식_근거", "연장_km", "차로", "총사업비_억", "총사업비_기준연월",
    "건설보조금_억", "보상비_억", "민간투자비_억", "민간투자비_근거", "사업비_상충값", "통행료_원km",
    "통행료_연장기준_km", "통행료_근거", "운영기간_년", "운영기간_근거", "교량비율", "터널비율", "구조비율_근거",
    "소형차전용", "적격성_결과", "적격성_일자", "수익률_pct", "수익률_종류", "예측교통량_대일", "예측교통량_종류",
    "협약교통량_대일", "결과상태_2026-10-07", "모형범위", "문턱_재무성립선_5입력", "권장협약수요_5입력",
    "민간투자비_KOTI보조율", "KOTI_출처표", "보조율적용_주의", "문턱_KOTI보조율", "민간투자비_0.70", "문턱_0.70",
    "출처_1차", "출처_2차", "비고",
]
D4_COLUMNS = ["민간투자비_KOTI보조율", "KOTI_출처표", "보조율적용_주의", "문턱_KOTI보조율", "민간투자비_0.70", "문턱_0.70"]


# ── 입력 ──────────────────────────────────────────────────────────────
def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def koti_by_key():
    """KOTI 원표행을 노선 키로. 별칭은 CSV 비고 '(보도 표기 X)'에서 읽고, 표2-2를 표2-3보다 우선."""
    with open(KOTI_CSV, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["행유형"] == "원표행"]
    out = {}
    for r in sorted(rows, key=lambda r: r["출처표"]):
        m = re.search(r"보도 표기 ([^)\s]+)", r["비고"])
        key = route_key(m.group(1) if m else r["노선_원문"])
        out.setdefault(key, r)
    return out


def private_share_alt():
    # 민간투자비 대안 비율 0.70(앱반영방안 D4). config 키(private_share_of_total_cost.sensitivity_alt) 신설 전까지 폴백
    return float(config_loader.load_finance_params().get("private_share_of_total_cost", {}).get("sensitivity_alt", 0.70))


def gov_threshold(five, capex):
    case = H.app_default_case(**{**five, "total_capex": capex})
    t, _ = H.threshold_traffic(case, "gov")
    return int(round(t)) if t else ""


# ── 파생 규칙 ─────────────────────────────────────────────────────────
def stage_code(text):
    text = re.sub(r"사업비 [^,]*보도", "", text)   # '사업비 협상·재조사 보도'는 단계어가 아님
    return next((code for word, code in STAGE_ORDER if word in text), "")


def result_status(text, scope):
    if scope != "신설":
        return "범위밖"
    if "부적격" in text or "재정 전환" in text:
        return "탈락"
    return "통과이상" if any(w in text for w in ("통과", "우협", "실시협약")) else "통과전"


def feasibility(text):
    if "부적격" in text:
        res = "부적격"
    elif any(w in text for w in ("통과", "우협", "실시협약")):
        res = "통과"
    elif "조사 중" in text:
        res = "조사중"
    elif "재정 전환" in text:
        res = "미해당(재정 전환)"
    else:
        res = "미의뢰" if any(w in text for w in ("접수", "의향서")) else ""
    m = re.search(r"(?:통과|부적격)\(([^,)]*)", text)
    raw = m.group(1).strip() if m else ""
    m2 = re.fullmatch(r"(\d{4})\. ?(\d{1,2})\.", raw)
    return res, (f"{m2.group(1)}-{int(m2.group(2)):02d}" if m2 else raw)


def capex_basis_code(text):
    if "×" in text:
        return "총사업비×비율(추정)"
    if "-" in text:
        return "총사업비-보조-보상"
    if "입력값" in text:
        return "입력값"
    return "단가모형" if "단가" in text else ""


def toll_basis(text, toll, default_toll, kind08):
    """근거 문장 우선, 없으면 기본값 여부, 그다음 08 예측 종류(제안서·사전타당성 요금은 같은 문서)."""
    if text:
        if "공고 상한" in text:
            return "공고상한"
        return "제안서" if "제안" in text else "보도"
    if default_toll and abs(float(toll) - float(default_toll)) < 1e-9:
        return "기본값"
    return next((c for c in ("제안서", "사전타당성") if c in kind08), "보도")


def op_basis(text, reported):
    if not reported:
        return "가정"
    if "협약" in text:
        return "협약"
    return "가정" if "가정" in text else "보도"


def tunnel_ratio(structure, v3_ratio):
    """구조 근거 문장의 터널 실제 비율(%). 70% 상한 문구는 제외, 없으면 보강 입력값."""
    cands = [int(x) for x in re.findall(r"터널 (\d+)%", structure) + re.findall(r"(?:지하|터널) [\d.]+km\((\d+)%\)", structure)
             + re.findall(r"(\d+)% 지하", structure)]
    if "상한" in structure:
        cands = [c for c in cands if c != 70]
    return cands[0] / 100 if cands else v3_ratio


def business_basis(op_text, koti_row, bt):
    m = re.search(r"방식 (BTO-a|BTO)[^(]*\(([^)]*)\)", op_text)
    if m:
        return "가정" if "가정" in m.group(0) else "보도"
    if koti_row and koti_row["방식"] == bt:
        return "KOTI RR-25-10 표"
    return "협약" if "협약" in op_text else ""


def conflict_note(cost_text, total_cost, koti_row):
    parts = [s.strip() for s in re.split(r"(?<!\d)\. ", cost_text) if any(w in s for w in CONFLICT_WORDS)]
    if koti_row and total_cost and koti_row["투자비계_억"]:
        inv = float(koti_row["투자비계_억"])
        if abs(inv - total_cost) / total_cost > CONFLICT_TOL:
            parts.append(f"KOTI 투자비계 {inv:,.0f}억({koti_row['출처표']}, {koti_row['기준시점']}, 보상비 포함 여부 미규명)")
    return " / ".join(parts)


def fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ── 빌드 ──────────────────────────────────────────────────────────────
def build():
    image, inputs, results = load(INPUT_FILES[0]), load(INPUT_FILES[1]), load(INPUT_FILES[2])
    v3 = {r["name"]: r for r in load(INPUT_FILES[3])}
    reality = load(INPUT_FILES[4])
    study = load(INPUT_FILES[5])
    koti = koti_by_key()
    alt = private_share_alt()
    bdefaults = config_loader.business_defaults()

    image_stage = {route_key(n): IMAGE_STAGE[g] for g, names in image.items() if g in IMAGE_STAGE for n in names}
    actual = {route_key(r["노선"]): r["실제 결과(2026. 10. 7.)"] for r in study["actual_results"]}
    rank = {route_key(r["노선"]): r for r in study["rank_table"]}
    reality_recs = {}
    for block in reality:
        for rec in block["routes"]:
            reality_recs.setdefault(route_key(rec["name"]), []).append(rec)
    koti_block_keys = {route_key(rec["name"]) for rec in reality[0]["routes"]}

    def agency(key):
        if key in rank and rank[key]["주무관청"]:
            a = rank[key]["주무관청"]
            return "국토교통부" if "국토부" in a else a
        for rec in reality_recs.get(key, []):
            m = re.search(r"\(([^,)]+)", rec["name"])
            if m and m.group(1).strip().endswith(("시", "도")):
                return m.group(1).strip()
        return "국토교통부" if key in image_stage or key in koti_block_keys else ""

    def sources(key):
        p, s = [], []
        for rec in reality_recs.get(key, []):
            for src in rec["sources"]:
                (p if PRIMARY_SOURCE.search(src) else s).append(src)
        return " | ".join(dict.fromkeys(p)), " | ".join(dict.fromkeys(s))

    def forecast_kind(key, aadt):
        for rec in reality_recs.get(key, []):
            kind = rec.get("forecast_kind") or ""
            if rec.get("forecast_aadt") == aadt and kind:
                for w, code in (("제안서", "제안서"), ("사전타당성", "사전타당성"), ("분산", "분산량"), ("협약", "협약")):
                    if w in kind:
                        return code
        return ""

    def reality_text(key, field, word):
        return next((rec[field] for rec in reality_recs.get(key, []) if rec.get(field) and word in rec[field]), "")

    rows = []
    for inp, res in zip(inputs, results):
        assert inp["name"] == res["name"], inp["name"]
        name, key = inp["name"], route_key(inp["name"])
        v, b, five = v3[name], v3[name]["basis"], {k: res["inputs"][k] for k in FIVE}
        kr = koti.get(key)
        scope = "개량운영형=범위밖" if "개량운영형" in name + inp.get("scope", "") else "신설"
        act = actual[key]
        feas, feas_date = feasibility(act)
        total_cost = inp.get("total_project_cost")
        toll_text = b.get("toll") or inp["basis"].get("toll", "")
        rate_text = b.get("rate", "")
        irr = dict(inp.get("extra_criteria", [])).get("real_irr")
        notes = [inp.get("scope", ""), inp.get("basis_label", "")]
        m_op = re.search(r"운영 (\d+)년", b["op"])
        if m_op and int(m_op.group(1)) != five["operation_years"]:
            notes.append(f"운영기간 근거 원문 {m_op.group(1)}년, 5개 입력은 {five['operation_years']}년")
        if kr:
            notes.append(f"KOTI {kr['출처표']} 투자비계 {float(kr['투자비계_억']):,.0f}억·보조율 {kr['건설보조금비율_pct'] or '원표 기호 -'}")
        koti_capex = ""
        if kr and kr["건설보조금비율_pct"]:
            koti_capex = int(round(float(kr["투자비계_억"]) * (1 - float(kr["건설보조금비율_pct"]) / 100)))
        alt_capex = int(round(total_cost * alt)) if total_cost else ""
        subsidy, land = inp.get("subsidy"), inp.get("land")
        row = OrderedDict([
            ("pipeline_version", PIPELINE_VERSION), ("노선", key), ("노선_원문표기", name), ("주무관청", agency(key)),
            ("그림단계_asof_2026-09-30", image_stage.get(key, "그림밖")),
            ("조사단계_asof_2026-10-07", stage_code(act)), ("조사단계_원문", act),
            ("제안자", rank.get(key, {}).get("제안자", "")),
            ("사업방식", five["business_type"]), ("사업방식_근거", business_basis(b["op"], kr, five["business_type"])),
            ("연장_km", five["road_length"]), ("차로", v["lanes"]),
            ("총사업비_억", total_cost),
            ("총사업비_기준연월", (lambda m: f"{m.group(1)}-{int(m.group(2)):02d}" if m else "")(re.search(r"(\d{4})\. ?(\d{1,2})\. 불변", b["cost"]))),
            ("건설보조금_억", subsidy or ""), ("보상비_억", land or ""),     # 0은 미확인 가정값이라 빈칸
            ("민간투자비_억", five["total_capex"]), ("민간투자비_근거", capex_basis_code(res["capex_basis"])),
            ("사업비_상충값", conflict_note(b["cost"], total_cost, kr)),
            ("통행료_원km", five["toll_per_km"]),
            ("통행료_연장기준_km", (lambda m: float(m.group(1)) if m else (five["road_length"] if five["toll_per_km"] != bdefaults[five["business_type"]]["toll"] else ""))(re.search(r"÷ ?([\d.]+) ?km", toll_text))),
            ("통행료_근거", toll_basis(toll_text, five["toll_per_km"], bdefaults[five["business_type"]]["toll"], " ".join(rec.get("forecast_kind") or "" for rec in reality_recs.get(key, [])))),
            ("운영기간_년", five["operation_years"]), ("운영기간_근거", op_basis(b["op"], inp.get("operation_years"))),
            ("교량비율", v["bridge_ratio"]), ("터널비율", tunnel_ratio(b["structure"], v["tunnel_ratio"])),
            ("구조비율_근거", b["structure"]), ("소형차전용", "Y" if v.get("heavy_ratio_pct") == 0 else "N"),
            ("적격성_결과", feas), ("적격성_일자", feas_date),
            ("수익률_pct", round(irr * 100, 2) if irr else ""),
            ("수익률_종류", next((c for c in ("기획단계", "협상단계", "협약") if c in rate_text),
                              "제안서" if irr and reality_text(key, "return_rate", "제안") else "")),
            ("예측교통량_대일", inp.get("forecast_aadt", "")),
            ("예측교통량_종류", forecast_kind(key, inp["forecast_aadt"]) if inp.get("forecast_aadt") else "없음"),
            ("협약교통량_대일", ""),
            ("결과상태_2026-10-07", result_status(act, scope)), ("모형범위", scope),
            ("문턱_재무성립선_5입력", res["thresholds"]["gov"]["traffic"]),
            ("권장협약수요_5입력", res["recommended_agreement_traffic"]),
            ("민간투자비_KOTI보조율", koti_capex), ("KOTI_출처표", kr["출처표"] if kr else ""),
            ("보조율적용_주의", "투자비계 보상비 포함 여부 미규명" if koti_capex != "" else ""),
            ("문턱_KOTI보조율", gov_threshold(five, koti_capex) if koti_capex != "" else ""),
            ("민간투자비_0.70", alt_capex), ("문턱_0.70", gov_threshold(five, alt_capex) if alt_capex != "" else ""),
            ("출처_1차", sources(key)[0]), ("출처_2차", sources(key)[1]),
            ("비고", " / ".join(n for n in notes if n)),
        ])
        rows.append(row)

    # 제안 미확인 1건(3절 순위표 '평가 불가' 행) + 미시험 3건(3절 2-가)
    extra = [dict(rank[k], 노선=k, 모형범위="신설") for k in rank if k not in {r["노선"] for r in rows}]
    extra += study["untested"]
    for e in extra:
        key = e["노선"]
        act = e.get("단계") or e.get("단계(2026. 10. 7.)", "")
        feas, feas_date = feasibility(act)
        a = e.get("주무관청", "")
        row = OrderedDict((c, "") for c in COLUMNS)
        row.update({
            "pipeline_version": PIPELINE_VERSION, "노선": key, "노선_원문표기": key,
            "주무관청": "국토교통부" if "국토부" in a else a,
            "그림단계_asof_2026-09-30": image_stage.get(key, "그림밖"),
            "조사단계_asof_2026-10-07": stage_code(act), "조사단계_원문": act, "제안자": e.get("제안자", ""),
            "연장_km": e.get("연장_km") or "", "민간투자비_근거": "미산출", "적격성_결과": feas, "적격성_일자": feas_date,
            "결과상태_2026-10-07": "미시험", "모형범위": e["모형범위"], "비고": e.get("비고", ""),
        })
        rows.append(row)
    return rows


def write(rows):
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([fmt(r.get(c, "")) for c in COLUMNS])
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:
        head = f"unavailable({e})"
    with open(os.path.join(SRC, "_copy_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    meta = OrderedDict([
        ("pipeline_version", PIPELINE_VERSION), ("built", date.today().isoformat()),
        ("survey_asof", ASOF_SURVEY), ("image_asof", ASOF_IMAGE), ("git_head", head),
        ("engine_reflected", False), ("script", "research/build_route_pipeline.py"),
        ("output", "data/route_pipeline_2026-10.csv"),
        ("rows", {"total": len(rows), "tested": sum(r["결과상태_2026-10-07"] != "미시험" for r in rows),
                  "untested": sum(r["결과상태_2026-10-07"] == "미시험" for r in rows)}),
        ("inputs_sha256", OrderedDict((f"_research_sources/pipeline_2026-10/{n}", sha256(os.path.join(SRC, n))) for n in INPUT_FILES)),
        ("inputs_sha256_koti", {"data/koti_rr2510_return_rates.csv": sha256(KOTI_CSV)}),
        ("source_copy_manifest", manifest),
        ("engine", {"helper": "tests/_helpers.app_default_case(**5개 입력) + threshold_traffic(case, 'gov'), 나머지 입력은 앱 기본값",
                    "five_input_keys": list(FIVE),
                    "anchor_ratio": H.TRAFFIC_ANCHOR_RATIO,
                    "golden_sha256": sha256(os.path.join(ROOT, "tests", "golden_values.json")),
                    "finance_params_sha256": sha256(os.path.join(ROOT, "config", "finance_params.json"))}),
        ("columns_added", {"D4": D4_COLUMNS,
                           "note": "민간투자비_KOTI보조율 = KOTI 투자비계×(1-건설보조금비율/100), 보상비 포함 여부 미규명 플래그 동반. "
                                   "민간투자비_0.70 = 총사업비×대안 비율. 두 문턱은 5개 입력 중 민간투자비만 교체해 재계산. pipeline_version 유지",
                           "private_share_alt": private_share_alt()}),
        ("rules", {
            "결측": "값 미확인은 빈칸. 03 입력의 건설보조금·보상비 0은 미확인 가정값이라 빈칸(차감 산술은 0으로 취급)",
            "조사단계": "7절 표 7 실제 결과 문장에서 단계어 우선순위(재정전환>부적격>건설>실시협약>협상>재조사중>우협>통과>조사중>의향서>미접수>접수)",
            "결과상태": "모형범위 신설 외는 범위밖, 부적격·재정 전환은 탈락, 통과·우협·실시협약은 통과이상, 그 외 통과전, 시험 없음은 미시험",
            "터널비율": "구조 근거 문장의 실제 비율(상한 70% 문구 제외), 없으면 보강 입력값. 엔진 투입 시 로더가 상한 적용",
            "사업비_상충값": f"근거 문장 중 상충·범위·병기·증액·원안 문장 + KOTI 투자비계가 총사업비와 {CONFLICT_TOL:.0%} 넘게 다른 경우",
            "출처등급": "08 출처 중 go.kr·korea.kr·pimac·KOTI 보고서 번호는 1차, 나머지 2차(자체 분류)",
            "제안자": "6판 3절 순위표 공개 보도 기준 회사명. 서면 응답사·미확인은 빈칸",
        }),
    ])
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


if __name__ == "__main__":
    rows = build()
    meta = write(rows)
    print(f"rows={len(rows)} csv={OUT_CSV}\nmeta={OUT_META} git_head={meta['git_head']}")
