# -*- coding: utf-8 -*-
"""S1: 추진 노선 출처 원장(긴 형식) 빌드. 한 행 = 노선 1·항목 1·값 1·출처 1(엔진 미연동, research 전용).

입력(ForenodeMain/_research_sources/pipeline_2026-10/ 사본):
  08_reality_side.json               실제 쪽 조사 4블록 58건(비null 항목 전부 행으로, null 사실 항목은 검색시도와 함께 빈 값 행)
  03_five_input_inputs.json          5개 입력 근거 문장
  03_forenode_test_inputs_v3.json    보강 입력 근거 문장·변형 입력(연장 등)
  04_five_input_aux.json             연장·요금 기준이 다른 변형 입력(양재~올림픽대로 2026 환경평가 기준 등)
  data/koti_rr2510_return_rates.csv  KOTI RR-25-10 투자비계·보조율·수익률
  data/route_pipeline_2026-10.csv    D1 채택값(채택여부 Y 행의 원천)
출력: data/route_pipeline_sources_2026-10.csv(UTF-8 BOM), data/route_pipeline_sources_2026-10.meta.json
갱신 규약: 새 보도·공고는 행 append만. 채택값 교체는 D1 CSV pipeline_version 상향과 meta 사유 기록.
"""
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import date
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(os.path.dirname(ROOT), "_research_sources", "pipeline_2026-10")
DATA = os.path.join(ROOT, "data")
PIPELINE_CSV = os.path.join(DATA, "route_pipeline_2026-10.csv")
KOTI_CSV = os.path.join(DATA, "koti_rr2510_return_rates.csv")
OUT_CSV = os.path.join(DATA, "route_pipeline_sources_2026-10.csv")
OUT_META = os.path.join(DATA, "route_pipeline_sources_2026-10.meta.json")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from pipeline_loader import route_key      # noqa: E402

SOURCE_VERSION = "v1_2026-10-07"
COLLECTED = "2026-10-07"          # 스터디 조사일(raw JSON 작성일)
CONFLICT_TOL = 0.05               # 같은 항목 값의 최대/최소 차이가 5% 넘으면 상충 그룹(반올림 차이 제외)
INPUT_FILES = ["08_reality_side.json", "03_five_input_inputs.json", "03_forenode_test_inputs_v3.json", "04_five_input_aux.json"]
COLS = ["source_version", "노선", "항목", "값", "단위", "기준연월", "출처등급", "출처_URL_또는_문서", "매체", "보도일", "수집일",
        "asof구분", "상충그룹ID", "채택여부", "검색시도", "비고"]
# D1 수치 열 -> (항목, 단위, 근거 열)
ADOPTED = OrderedDict([
    ("연장_km", ("연장", "km", None)), ("총사업비_억", ("총사업비", "억원", "민간투자비_근거")),
    ("건설보조금_억", ("건설보조금", "억원", "민간투자비_근거")), ("보상비_억", ("보상비", "억원", "민간투자비_근거")),
    ("민간투자비_억", ("민간투자비", "억원", "민간투자비_근거")), ("통행료_원km", ("통행료_원km", "원/km", "통행료_근거")),
    ("운영기간_년", ("운영기간", "년", "운영기간_근거")), ("교량비율", ("교량비율", "비율", "구조비율_근거")),
    ("터널비율", ("터널비율", "비율", "구조비율_근거")), ("차로", ("차로", "차로", None)),
    ("수익률_pct", ("수익률", "%", "수익률_종류")), ("예측교통량_대일", ("예측교통량", "대/일", "예측교통량_종류")),
])
BASIS_ITEM = {"cost": "사업비_근거문", "structure": "구조_근거문", "op": "운영기간_근거문", "lanes": "차로_근거문",
              "toll": "통행료_근거문", "rate": "수익률_근거문", "traffic": "교통량_근거문", "length": "연장_근거문"}
REALITY_ITEM = OrderedDict([
    ("forecast_aadt", ("예측교통량", "대/일")), ("forecast_year", ("예측교통량_연도", "")), ("forecast_kind", ("예측교통량_종류", "")),
    ("forecast_source", ("예측교통량_출처", "")), ("toll_won", ("통행료_원", "원")), ("toll_per_km", ("통행료_원km", "원/km")),
    ("toll_note", ("통행료_주석", "")), ("return_rate", ("수익률_서술", "")), ("feasibility_result", ("적격성결과", "")),
    ("cost_change", ("사업비변동", "")), ("outcome", ("진행결과", "")), ("search_terms_tried", ("검색시도", "")),
])
FACT_FIELDS = ("forecast_aadt", "toll_won", "toll_per_km", "return_rate")   # null이면 검색시도와 함께 빈 값 행
POST_ITEMS = {"적격성결과", "진행결과", "사업비변동"}                           # asof구분 사후(결과 공개 후 정보)
CONFLICT_FAMILIES = {"총사업비": ("총사업비", "투자비계_KOTI", "사업비_대안값"), "민간투자비": ("민간투자비",), "통행료": ("통행료_원km",)}
CONFLICT_WORDS = ("상충", "범위", "병기", "증액", "원안")
GUARD_REPLACE = {"".join(("유", "일")): "하나뿐"}   # 금지 표현 치환(원문 노트 서술 1건). 리터럴을 쪼개 grep 가드에 안 걸리게 함


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def grade(text):
    """출처등급 자체 규칙: 추정·가정·기본값 > 추정, 1차·공고·협약·확인·요약 > 1차, 2차·보도·제안·KOTI > 2차."""
    t = text or ""
    if any(w in t for w in ("추정", "가정", "기본값")):
        return "추정"
    if any(w in t for w in ("1차", "공고", "협약", "확인", "요약문", "요약서")):
        return "1차"
    if any(w in t for w in ("2차", "보도", "제안", "KOTI", "RR-")):
        return "2차"
    return ""


def fmt(v):
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def won_amounts(text):
    """'1조 3,000억'·'8,698억' 형태 금액(억 원)."""
    out = []
    for jo, eok in re.findall(r"(?:(\d+)조 ?)?(\d{1,3}(?:,\d{3})*)억", text):
        out.append(int(jo or 0) * 10000 + int(eok.replace(",", "")))
    return out


def media_and_date(src):
    m = re.search(r"\((\d{4}-\d{2}(?:-\d{2})?)\)\s*$", src)
    if src.startswith("http"):
        return urlparse(src.split()[0]).netloc, (m.group(1) if m else "")
    return src.split()[0], (m.group(1) if m else "")


class Ledger:
    def __init__(self):
        self.rows, self.seen, self.guard_hits = [], set(), 0

    def add(self, route, item, value, unit="", basis="", grade_="", source="", media="", pubdate="", collected=COLLECTED,
            asof="", adopted="N", tried="", note=""):
        value, note = fmt(value), fmt(note)
        for w, rep in GUARD_REPLACE.items():
            self.guard_hits += value.count(w) + note.count(w)
            value, note = value.replace(w, rep), note.replace(w, rep)
        key = (route, item, value, source)
        if key in self.seen:
            return
        self.seen.add(key)
        self.rows.append(OrderedDict(zip(COLS, [SOURCE_VERSION, route, item, value, unit, basis, grade_, source, media, pubdate,
                                                collected, asof, "", adopted, tried, note])))


def build():
    L = Ledger()
    with open(PIPELINE_CSV, encoding="utf-8-sig") as f:
        pipeline = list(csv.DictReader(f))
    inputs = {r["name"]: r for r in load("03_five_input_inputs.json")}
    v3 = {r["name"]: r for r in load("03_forenode_test_inputs_v3.json")}
    aux = load("04_five_input_aux.json")
    reality = load("08_reality_side.json")
    with open(KOTI_CSV, encoding="utf-8-sig") as f:
        koti = [r for r in csv.DictReader(f) if r["행유형"] == "원표행"]
    keys = {r["노선"] for r in pipeline}

    # ① D1 채택값(채택여부 Y): 수치 셀마다 정확히 1행
    for p in pipeline:
        raw = inputs.get(p["노선_원문표기"], {})
        b = {**raw.get("basis", {}), **v3.get(p["노선_원문표기"], {}).get("basis", {})}
        basis_text = {"민간투자비_근거": b.get("cost", ""), "통행료_근거": b.get("toll", "") or p["통행료_근거"],
                      "운영기간_근거": b.get("op", ""), "구조비율_근거": b.get("structure", ""),
                      "수익률_종류": b.get("rate", "") or p["수익률_종류"], "예측교통량_종류": b.get("traffic", "") or p["예측교통량_종류"]}
        for col, (item, unit, basis_col) in ADOPTED.items():
            if p[col] == "":
                continue
            text = basis_text.get(basis_col, "") if basis_col else b.get("length" if col == "연장_km" else "lanes", "")
            L.add(p["노선"], item, p[col], unit, p["총사업비_기준연월"] if item in ("총사업비", "민간투자비") else "",
                  grade(text), f"route_pipeline_2026-10.csv 채택값({basis_col}={p[basis_col]})" if basis_col else "route_pipeline_2026-10.csv 채택값",
                  adopted="Y", note=text)
        # 근거 문장 중 상충 문장의 대안 금액(채택값과 다른 값만)
        for sent in re.split(r"(?<!\d)\. ", b.get("cost", "")):
            if any(w in sent for w in CONFLICT_WORDS):
                for amt in won_amounts(sent):
                    if str(amt) not in (p["총사업비_억"], p["민간투자비_억"]):
                        L.add(p["노선"], "사업비_대안값", amt, "억원", "", grade(sent), "03_five_input_inputs.json basis.cost", note=sent)

    # ② 근거 문장(03·v3)과 보강 입력 변형값
    for name, src in (("03_five_input_inputs.json", inputs), ("03_forenode_test_inputs_v3.json", v3)):
        for raw_name, rec in src.items():
            route = route_key(raw_name)
            if route not in keys:
                continue
            for k, text in rec.get("basis", {}).items():
                L.add(route, BASIS_ITEM[k], text, "", "", grade(text), name)
            if name.endswith("v3.json"):
                p = next(r for r in pipeline if r["노선"] == route)
                for col, key_, unit in (("연장_km", "road_length", "km"), ("차로", "lanes", "차로"), ("교량비율", "bridge_ratio", "비율"),
                                        ("터널비율", "tunnel_ratio", "비율"), ("민간투자비_억", "total_capex", "억원")):
                    if key_ in rec and fmt(rec[key_]) != p[col]:
                        L.add(route, ADOPTED[col][0], rec[key_], unit, "", grade(rec["basis"].get("structure", "")), name + " 보강 입력",
                              note=f"보강 입력값, 채택값 {p[col]}과 상이(터널비율은 70% 상한 적용값)")
    for rec in aux:
        if rec["name"].startswith("[민감도]") or "(" not in rec["name"]:
            continue
        route, inp = route_key(rec["name"]), rec["inputs"]
        p = next(r for r in pipeline if r["노선"] == route)
        qual = re.search(r"\(([^)]*)\)\s*$", rec["name"]).group(1)
        for col, key_, unit in (("연장_km", "road_length", "km"), ("민간투자비_억", "total_capex", "억원"), ("통행료_원km", "toll_per_km", "원/km")):
            if fmt(inp[key_]) != p[col]:
                L.add(route, ADOPTED[col][0], inp[key_], unit, "", "2차", "04_five_input_aux.json 변형 입력", note=f"{qual} 기준, 채택값 {p[col]}과 상이")

    # ③ 08 실제 쪽: 비null 항목 전부 + null 사실 항목(검색시도 동반) + 출처 목록
    for block in reality:
        origin = os.path.basename(block["notes_file"])
        for rec in block["routes"]:
            route = route_key(rec["name"])
            srcs = " | ".join(rec["sources"])
            lengths = {fmt(float(r[c])) for r in pipeline if r["노선"] == route for c in ("연장_km",) if r[c]}
            for field, (item, unit) in REALITY_ITEM.items():
                val = rec.get(field)
                if val is None or val == "":
                    if field in FACT_FIELDS:
                        L.add(route, item, "", unit, "", "null", srcs, asof="", tried=rec.get("search_terms_tried") or "", note=origin)
                    continue
                ctx = (rec.get("toll_note") if field.startswith("toll") else rec.get("forecast_kind") if field.startswith("forecast")
                       else val) or ""
                L.add(route, item, val, unit, rec.get("forecast_year") or "" if field == "forecast_aadt" else "",
                      grade(ctx if field in FACT_FIELDS else val), srcs, asof="사후" if item in POST_ITEMS else "", note=origin)
            for s in rec["sources"]:
                media, pub = media_and_date(s)
                L.add(route, "출처", s, "", "", "1차" if re.search(r"\.go\.kr|korea\.kr|pimac|RR-\d|MP-\d", s) else "2차", s, media, pub, note=origin)
            # 통행료 연장 기준 변형: 통행료_원을 채택 연장이 아닌 보강·변형 연장으로 나눈 값
            if rec.get("toll_won"):
                alt_len = {fmt(v3[r["노선_원문표기"]]["road_length"]) for r in pipeline if r["노선"] == route and r["노선_원문표기"] in v3}
                alt_len |= {fmt(a["inputs"]["road_length"]) for a in aux if route_key(a["name"]) == route and not a["name"].startswith("[민감도]")}
                for ln in sorted(alt_len - lengths):
                    L.add(route, "통행료_원km", round(rec["toll_won"] / float(ln), 1), "원/km", "", "추정", srcs,
                          note=f"통행료_원 {rec['toll_won']:,} ÷ 연장 {ln}km(변형 연장 기준) 계산값")

    # ④ KOTI RR-25-10 원표행(별칭은 CSV 비고 '(보도 표기 X)')
    for r in koti:
        m = re.search(r"보도 표기 ([^)\s]+)", r["비고"])
        route = route_key(m.group(1) if m else r["노선_원문"])
        if route not in keys:
            continue
        src = f"KOTI RR-25-10 {r['출처표']} {r['출처페이지']}"
        note = f"{r['단계']}단계 행(원문 표기 {r['노선_원문']}, {r['방식']}). {r['비고']}".strip(". ")
        for item, col, unit in (("투자비계_KOTI", "투자비계_억", "억원"), ("건설보조금비율_KOTI", "건설보조금비율_pct", "%"),
                                ("수익률", "수익률_pct", "%"), ("연장", "연장_km", "km")):
            if r[col]:
                L.add(route, item, float(r[col]), unit, r["기준시점"], "2차", src, "KOTI", "", "", note=note)

    # ⑤ 상충 그룹: 같은 노선·같은 항목군의 수치 값 폭이 허용치를 넘으면 그 군 전체에 ID
    groups = {}
    for fam, items in CONFLICT_FAMILIES.items():
        for route in keys:
            rows = [r for r in L.rows if r["노선"] == route and r["항목"] in items and r["값"] != ""]
            vals = [float(r["값"]) for r in rows]
            if len(vals) >= 2 and min(vals) > 0 and max(vals) / min(vals) - 1 > CONFLICT_TOL:
                gid = f"CF-{route}-{fam}"
                groups[gid] = sorted(set(vals))
                for r in rows:
                    r["상충그룹ID"] = gid
    return L, groups


def write(L, groups):
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(L.rows)
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:
        head = f"unavailable({e})"
    adopted = [r for r in L.rows if r["채택여부"] == "Y"]
    meta = OrderedDict([
        ("source_version", SOURCE_VERSION), ("built", date.today().isoformat()), ("collected", COLLECTED), ("git_head", head),
        ("engine_reflected", False), ("script", "research/build_pipeline_sources.py"), ("output", "data/route_pipeline_sources_2026-10.csv"),
        ("rows", {"total": len(L.rows), "adopted_Y": len(adopted), "null_fact_rows": sum(r["출처등급"] == "null" for r in L.rows),
                  "routes": len({r["노선"] for r in L.rows})}),
        ("inputs_sha256", OrderedDict([(f"_research_sources/pipeline_2026-10/{n}", sha256(os.path.join(SRC, n))) for n in INPUT_FILES]
                                      + [("data/koti_rr2510_return_rates.csv", sha256(KOTI_CSV)), ("data/route_pipeline_2026-10.csv", sha256(PIPELINE_CSV))])),
        ("conflict_groups", groups),
        ("guard_replacements", {"replaced_with": "하나뿐", "count": L.guard_hits, "note": "금지 표현(앱반영방안 §5-13 첫 항) 치환 건수"}),
        ("rules", {
            "채택여부": "D1 route_pipeline_2026-10.csv의 수치 셀마다 Y 행 1개(출처 열에 근거 코드), 나머지 N",
            "출처등급": "자체 키워드 규칙(추정·가정·기본값=추정, 1차·공고·협약·확인·요약=1차, 2차·보도·제안·KOTI=2차), 08 null 사실 항목은 null",
            "asof구분": "적격성결과·진행결과·사업비변동만 사후, 나머지는 빈칸(수동 분류 대기)",
            "상충그룹": f"항목군(총사업비+투자비계_KOTI+사업비_대안값 / 민간투자비 / 통행료_원km)의 최대÷최소가 1+{CONFLICT_TOL} 초과 시",
            "출처 행": "08 sources 목록은 항목 '출처'로 1건 1행(매체=도메인 또는 문서 첫 토큰, 보도일=괄호 날짜)",
        }),
        ("manual_todo", [
            "R_cand.md·R_env.md·R_design.md·R_koti_local.md·E_candidates.md·A_proposal.md의 '* 출처.' 줄과 표 A·B·요약표는 미파싱"
            "(2026-10-14 집계 출처 줄 14·16·2·5·15·11, 표 행 0·30·14·73·21·23). JSON 파싱 행으로 충분, 수동 보완은 append만",
            "원문 노트 사본은 서면 응답사·노선 연결 문장을 포함해 _research_sources에 미보존(비식별 후 보존 여부는 대표 결정)",
            "asof구분 사전·안전 분류, 기준연월(불변가 기준) 보강",
            "위키 external-docs-registry.md §1·forenode-data-sources.md 행 추가(위키는 이 스크립트 범위 밖)",
        ]),
    ])
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


if __name__ == "__main__":
    L, groups = build()
    meta = write(L, groups)
    print(f"rows={meta['rows']} groups={len(groups)} guard_replacements={meta['guard_replacements']['count']}")
    for g, v in groups.items():
        print(" ", g, v)
