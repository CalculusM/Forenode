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
        return 2
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
