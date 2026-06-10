"""
Forenode — IFC 물량 추출기 (ifc_extract.py)

목적
----
BIM IFC 파일을 읽어 사업성/수익성 산정에 필요한 '물량(quantities)'을 구조화해 뽑아낸다.
이것이 Forenode 핵심 가치사슬의 첫 단계다: IFC 형상 → 물량 → CAPEX/도로제원 자동 입력.

이 모듈은 '읽기·정량화'까지만 책임진다. 물량→CAPEX 매핑·앱 입력 자동채움은 후속 단계.

설계 원칙
--------
- 스키마(IFC2X3 / IFC4 / IFC4X3) 무관하게 동작. 인프라(도로·교량) 전용 타입은 있으면 집계, 없으면 건너뜀.
- 수량은 IfcElementQuantity(=Qto_*)에서 추출하고, 이름 휴리스틱으로 길이/면적/체적/개수/중량으로 분류.
- 추정·보정 없음. 모델에 있는 값만 합산해 보고(신뢰성 우선).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import ifcopenshell
import ifcopenshell.util.element as ue


# 수량 프로퍼티 이름 → 카테고리 분류 (대소문자 무시, 부분일치)
def _classify(prop_name: str) -> str | None:
    n = prop_name.lower()
    if "volume" in n:
        return "volume_m3"
    if "area" in n:
        return "area_m2"
    if any(k in n for k in ("length", "perimeter", "width", "height", "depth", "span")):
        return "length_m"
    if "count" in n or "number" in n:
        return "count"
    if "weight" in n or "mass" in n:
        return "weight_kg"
    return None


def _safe_by_type(model, type_name: str) -> int:
    """스키마에 없는 타입이면 0을 반환(예외 삼킴)."""
    try:
        return len(model.by_type(type_name))
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════
# [B] OBS 공종 → OPEX 카테고리 매핑 + 형상 역산 (EX_BIM_매핑표 코드화)
# ════════════════════════════════════════════════════════════
# 매핑 근거: EX 도로 BIM 지침(OBS 공종·표준객체) + IFC4.3 엔티티 + 표준품셈 OPEX 카테고리.
# 측정단위는 app.estimate_lcc_maintenance가 기대하는 단위에 맞춘다:
#   ASPHALT ㎥ · CONCRETE ㎥ · BEARING EA · EXPANSION_JOINT m · GUARDRAIL m
#   DRAINAGE m · LIGHTING EA · PAINT ㎡ · STEEL ton · REBAR ton
# 규칙: (IFC 타입 또는 객체명 키워드) → (OPEX 카테고리, 측정종류). 위에서부터 먼저 매칭.
_MEASURE = ("volume", "length", "area", "count", "weight")
_CATEGORY_RULES = [
    # (카테고리,          ifc_types,                              name_keywords,                 measure)
    ("BEARING",          ("IfcBearing",),                         ("bearing", "받침", "교좌"),     "count"),
    ("EXPANSION_JOINT",  ("IfcExpansionJoint",),                  ("expansion", "신축이음"),       "length"),
    ("GUARDRAIL",        ("IfcRailing",),                         ("guardrail", "난간", "방호"),    "length"),
    ("DRAINAGE",         ("IfcPipeSegment", "IfcDuctSegment"),    ("drain", "배수", "측구", "암거", "집수"), "length"),
    # 부대시설(조명·표지·신호) — 표준품셈 life15 동일 그룹, 개수 기준
    ("LIGHTING",         ("IfcLamp", "IfcLightFixture", "IfcOutlet",
                          "IfcSignal", "IfcSign", "IfcRoadSign"),
                         ("light", "조명", "가로등", "sign", "signal", "표지", "신호"), "count"),
    ("PAINT",            (),                                      ("paint", "도장"),               "area"),
    ("WATERPROOF",       (),                                      ("waterproof", "방수"),          "area"),
    ("ASPHALT",          ("IfcCourse", "IfcPavement"),            ("pavement", "포장", "asphalt", "표층", "기층", "아스팔트"), "volume"),
    ("REBAR",            ("IfcReinforcingBar", "IfcReinforcingElement"), ("rebar", "철근"),         "weight"),
    ("STEEL",            ("IfcPlate", "IfcMember"),               ("steel", "강재", "강판"),        "weight"),
    # 구조부재(거더·교각·기초·벽체·옹벽·슬래브)는 기본 CONCRETE 체적 (국내 PSC 교량 다수)
    ("CONCRETE",         ("IfcBeam", "IfcColumn", "IfcSlab", "IfcWall", "IfcWallStandardCase",
                          "IfcFooting", "IfcPier", "IfcBridgePart", "IfcRetainingWall"),
                         ("concrete", "콘크리트", "거더", "girder", "교각", "기초", "옹벽", "코핑", "라이닝"), "volume"),
]


def _classify_opex(el) -> tuple[str | None, str]:
    """요소 → (OPEX 카테고리, 측정종류). 매칭 없으면 (None, '')."""
    t = el.is_a()
    name = (getattr(el, "Name", "") or "").lower()
    obj_type = (getattr(el, "ObjectType", "") or "").lower()
    for cat, types, kws, measure in _CATEGORY_RULES:
        if types and t in types:
            return cat, measure
        if kws and any(k in name or k in obj_type for k in kws):
            return cat, measure
    return None, ""


def _qto_measure(el, measure: str):
    """Qto에서 측정값 추출(있으면). 단위: volume㎥/area㎡/length m/weight kg."""
    want = {"volume": "volume_m3", "area": "area_m2",
            "length": "length_m", "weight": "weight_kg"}.get(measure)
    if not want:
        return None
    best = None
    for _q, props in ue.get_psets(el, qtos_only=True).items():
        for pn, v in props.items():
            if pn == "id" or not isinstance(v, (int, float)):
                continue
            if _classify(pn) == want:
                best = max(best or 0.0, float(v))
    return best


def _geom_measures(geom):
    """삼각망 → (체적㎥, bbox 최장축 길이 m). util.shape 우선."""
    v = geom.verts
    f = geom.faces
    # 체적 (부호있는 사면체 합)
    vol = 0.0
    for i in range(0, len(f), 3):
        a, b, c = f[i] * 3, f[i + 1] * 3, f[i + 2] * 3
        vol += (v[a] * (v[b + 1] * v[c + 2] - v[b + 2] * v[c + 1])
                - v[a + 1] * (v[b] * v[c + 2] - v[b + 2] * v[c])
                + v[a + 2] * (v[b] * v[c + 1] - v[b + 1] * v[c])) / 6.0
    # bbox 최장축(길이형 부재 근사)
    xs, ys, zs = v[0::3], v[1::3], v[2::3]
    length = 0.0
    if xs:
        length = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    return abs(vol), length


def extract_opex_quantities(path: str) -> dict:
    """IFC → OPEX 카테고리별 물량(estimate_lcc_maintenance 투입용).

    Returns
    -------
    {
      "schema": str, "source_summary": {...},
      "quantities": { "CONCRETE": {"qty": ㎥, "unit": "m3", "source": "qto|geom", "n": int}, ... },
    }
    Qto가 있으면 우선, 없으면 ifcopenshell.geom으로 형상 역산(체적/길이). count는 요소 수.
    """
    import ifcopenshell.geom as _geom
    model = ifcopenshell.open(path)
    settings = _geom.settings()

    agg: dict[str, dict] = {}
    src_count = {"qto": 0, "geom": 0, "count": 0, "skip_area": 0,
                 "geom_fail": 0, "unmapped": 0}

    for el in model.by_type("IfcElement"):
        cat, measure = _classify_opex(el)
        if cat is None:
            # 공종 미분류(타입·객체명으로 매칭 안 됨) — 실제 EX 성과품은 OBS 객체명으로 분류됨.
            src_count["unmapped"] += 1
            continue
        slot = agg.setdefault(cat, {"qty": 0.0, "unit": "", "source": "", "n": 0})
        slot["n"] += 1

        if measure == "count":
            slot["qty"] += 1
            slot["unit"] = "EA"
            slot["source"] = "count"
            src_count["count"] += 1
            continue

        # 1) Qto 우선
        q = _qto_measure(el, measure)
        if q is not None and q > 0:
            val = q / 1000.0 if measure == "weight" else q  # kg→ton
            slot["qty"] += val
            slot["unit"] = {"volume": "m3", "area": "m2", "length": "m", "weight": "ton"}[measure]
            slot["source"] = slot["source"] or "qto"
            src_count["qto"] += 1
            continue

        # 2) 형상 역산 (volume·length만; area는 Qto 없으면 보류)
        if measure == "area":
            src_count["skip_area"] += 1
            continue
        if getattr(el, "Representation", None) is None:
            continue
        try:
            shape = _geom.create_shape(settings, el)
            vol, length = _geom_measures(shape.geometry)
        except Exception:
            src_count["geom_fail"] += 1
            continue
        if measure == "volume" and vol > 1e-9:
            slot["qty"] += vol
            slot["unit"] = "m3"
            slot["source"] = slot["source"] or "geom"
            src_count["geom"] += 1
        elif measure == "length" and length > 1e-9:
            slot["qty"] += length
            slot["unit"] = "m"
            slot["source"] = slot["source"] or "geom"
            src_count["geom"] += 1

    quantities = {c: {"qty": round(d["qty"], 3), "unit": d["unit"],
                      "source": d["source"], "n": d["n"]}
                  for c, d in agg.items() if d["qty"] > 0}
    return {"schema": model.schema, "source_summary": src_count, "quantities": quantities}


def extract_ifc(path: str, *, top_n_types: int = 15) -> dict:
    """IFC 파일에서 물량·구조 요약을 추출해 dict로 반환."""
    model = ifcopenshell.open(path)

    # 프로젝트 메타
    projects = model.by_type("IfcProject")
    project_name = projects[0].Name if projects and projects[0].Name else "(미상)"

    # 엔티티 타입별 개수
    type_counts: dict[str, int] = defaultdict(int)
    for inst in model:
        type_counts[inst.is_a()] += 1

    # 수량 집계: 카테고리 → {요소타입: 합계, "_total": 합계}
    quantities: dict[str, dict[str, float]] = {
        "length_m": defaultdict(float),
        "area_m2": defaultdict(float),
        "volume_m3": defaultdict(float),
        "count": defaultdict(float),
        "weight_kg": defaultdict(float),
    }

    elements = model.by_type("IfcElement")
    for el in elements:
        el_type = el.is_a()
        qsets = ue.get_psets(el, qtos_only=True)  # {QtoName: {prop: value}}
        for _qto_name, props in qsets.items():
            for prop_name, value in props.items():
                if prop_name == "id":
                    continue
                if not isinstance(value, (int, float)):
                    continue
                cat = _classify(prop_name)
                if cat is None:
                    continue
                quantities[cat][el_type] += float(value)
                quantities[cat]["_total"] += float(value)

    # defaultdict → 일반 dict, _total을 먼저 오게 정렬
    quantities_out = {}
    for cat, d in quantities.items():
        if not d:
            continue
        total = d.pop("_total", 0.0)
        ordered = {"_total": round(total, 3)}
        for k, v in sorted(d.items(), key=lambda kv: -kv[1]):
            ordered[k] = round(v, 3)
        quantities_out[cat] = ordered

    # 인프라 전용 타입 존재 여부(IFC4X3 등). 없으면 0.
    infrastructure = {
        "roads": _safe_by_type(model, "IfcRoad"),
        "bridges": _safe_by_type(model, "IfcBridge"),
        "railways": _safe_by_type(model, "IfcRailway"),
        "alignments": _safe_by_type(model, "IfcAlignment"),
    }

    top_types = dict(sorted(type_counts.items(), key=lambda kv: -kv[1])[:top_n_types])

    return {
        "schema": model.schema,
        "project": project_name,
        "element_count": len(elements),
        "entity_count": sum(type_counts.values()),
        "top_entity_types": top_types,
        "quantities": quantities_out,
        "infrastructure": infrastructure,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("사용법: python ifc_extract.py <파일.ifc> [출력.json]")
        print("       python ifc_extract.py --opex <파일.ifc>   # OPEX 카테고리 물량")
        return 2
    if argv[1] == "--opex":
        if len(argv) < 3:
            print("사용법: python ifc_extract.py --opex <파일.ifc>")
            return 2
        try:
            out = extract_opex_quantities(argv[2])
        except Exception as e:
            print(f"[오류] IFC를 읽지 못했습니다: {e}")
            return 1
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    path = argv[1]
    try:
        summary = extract_ifc(path)
    except Exception as e:  # 파일 손상·미지원 스키마 등
        print(f"[오류] IFC를 읽지 못했습니다: {e}")
        return 1
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if len(argv) >= 3:
        with open(argv[2], "w", encoding="utf-8") as f:
            f.write(text)
        print(f"요약을 {argv[2]} 에 저장했습니다.")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
