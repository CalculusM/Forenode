# -*- coding: utf-8 -*-
"""_tmp_ifc_probe.py — IFC 샘플 해부 프로브 (로컬 조사용 임시 스크립트)

사용법: python _tmp_ifc_probe.py <파일.ifc> [파일2.ifc ...]
출력: 엔티티 히스토그램 상위20, 인프라 타입 존재, Pset/Qto, 재료/분류, CostItem, Alignment 연장
"""
import sys
from collections import Counter

import ifcopenshell
import ifcopenshell.util.element as ue


def safe_by_type(m, t):
    try:
        return m.by_type(t)
    except Exception:
        return []


def probe(path):
    print("=" * 72)
    print(f"FILE: {path}")
    m = ifcopenshell.open(path)
    print(f"schema: {m.schema}  (schema_identifier: {getattr(m, 'schema_identifier', m.schema)})")

    # 1) 엔티티 히스토그램 상위 20
    hist = Counter(inst.is_a() for inst in m)
    print(f"total instances: {sum(hist.values())}")
    print("-- top 20 entity types --")
    for t, n in hist.most_common(20):
        print(f"  {t:45s} {n}")

    # 2) 인프라 전용 타입
    infra = ["IfcAlignment", "IfcRoad", "IfcRoadPart", "IfcBridge", "IfcBridgePart",
             "IfcPavement", "IfcCourse", "IfcEarthworksCut", "IfcEarthworksFill",
             "IfcEarthworksElement", "IfcTunnel", "IfcKerb", "IfcBearing",
             "IfcRailing", "IfcSign", "IfcSignal", "IfcGeotechnicalStratum"]
    print("-- infra types present --")
    for t in infra:
        n = len(safe_by_type(m, t))
        if n:
            print(f"  {t}: {n}")

    # 3) Pset 이름 (IsDefinedBy 경유) 상위 10 + Qto
    pset_names = Counter()
    qto_count = 0
    qto_filled = 0
    for rel in safe_by_type(m, "IfcRelDefinesByProperties"):
        pd = rel.RelatingPropertyDefinition
        if pd is None:
            continue
        if pd.is_a("IfcElementQuantity"):
            qto_count += 1
            try:
                for q in (pd.Quantities or []):
                    for attr in ("LengthValue", "AreaValue", "VolumeValue",
                                 "CountValue", "WeightValue", "TimeValue"):
                        v = getattr(q, attr, None)
                        if isinstance(v, (int, float)) and v != 0:
                            qto_filled += 1
                            break
            except Exception:
                pass
        else:
            pset_names[getattr(pd, "Name", None) or "(무명)"] += 1
    print(f"-- Psets via IsDefinedBy: {sum(pset_names.values())} rels, "
          f"{len(pset_names)} distinct names; top 10 --")
    for nm, n in pset_names.most_common(10):
        print(f"  {nm}: {n}")
    print(f"IfcElementQuantity(Qto) 정의 수: {qto_count}, 값 채워진 quantity 수: {qto_filled}")

    # 4) 재료 / 분류
    n_mat = len(safe_by_type(m, "IfcMaterial"))
    n_relmat = len(safe_by_type(m, "IfcRelAssociatesMaterial"))
    mats = [x.Name for x in safe_by_type(m, "IfcMaterial")][:10]
    n_cls = len(safe_by_type(m, "IfcClassification"))
    n_clsref = len(safe_by_type(m, "IfcClassificationReference"))
    print(f"IfcMaterial: {n_mat} (연결 IfcRelAssociatesMaterial: {n_relmat}) 예시: {mats}")
    print(f"IfcClassification: {n_cls}, IfcClassificationReference: {n_clsref}")
    if n_clsref:
        refs = safe_by_type(m, "IfcClassificationReference")[:5]
        for r in refs:
            print(f"   ref: Identification={getattr(r,'Identification',None)} Name={getattr(r,'Name',None)}")

    # 5) 비용
    print(f"IfcCostItem: {len(safe_by_type(m,'IfcCostItem'))}, "
          f"IfcCostSchedule: {len(safe_by_type(m,'IfcCostSchedule'))}")

    # 6) Alignment 연장 (수평 세그먼트 길이 합)
    aligns = safe_by_type(m, "IfcAlignment")
    if aligns:
        total = 0.0
        nseg = 0
        for seg in safe_by_type(m, "IfcAlignmentHorizontalSegment"):
            L = getattr(seg, "SegmentLength", None)
            if isinstance(L, (int, float)):
                total += abs(L)
                nseg += 1
        print(f"IfcAlignment: {len(aligns)}개, 수평세그먼트 {nseg}개, 연장 합계 ≈ {total:,.1f} m")
        for a in aligns[:3]:
            print(f"   alignment name: {getattr(a,'Name',None)}")
    print()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        try:
            probe(p)
        except Exception as e:
            print(f"[실패] {p}: {type(e).__name__}: {e}")
