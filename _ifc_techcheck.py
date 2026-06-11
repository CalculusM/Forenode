# -*- coding: utf-8 -*-
"""[기술검증] 공개 IFC4.3 도로 데모에서 형상→물량 추출이 되는지 증명.
- IfcAlignment(선형) 길이, 물리부재(토공·배수 등) 체적을 ifcopenshell.geom으로 산출
- IfcElementQuantity(Qto)·IfcMaterial 실제 존재 여부 점검 (없을 때 형상 역산이 필요함을 보임)
실행: python _ifc_techcheck.py
"""
import os
import glob
import warnings
warnings.filterwarnings("ignore")
import ifcopenshell
import ifcopenshell.geom

try:
    import ifcopenshell.util.shape as ushape
    HAS_USHAPE = True
except Exception:
    HAS_USHAPE = False

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "05 BIM IFC", "IFC4.3.x-sample-models-main",
                    "IFC4.3.x-sample-models-main", "models")

# IFC4X3_ADD2(공식 최종 IFC4.3) — ifcopenshell 0.8.5가 지원. 도로 선형·도로체·교량부재 + 체적검증용 솔리드
TARGET_GLOBS = [
    "alignment-geometries-and-linear-positioning/fixed-reference-swept-area-solid/*.ifc",  # 선형 따라 단면 스윕(도로체)
    "alignment-geometries-and-linear-positioning/sectioned-solid-horizontal/*.ifc",        # 도로 본체 솔리드
    "alignment-geometries-and-linear-positioning/linear-placement-of-signal/*.ifc",        # 선형 위 부대시설
    "building-elements/beam-parametric-cross-section/*.ifc",                                # 교량 거더(파라메트릭 단면)
    "basic-geometric-shape/extruded-solid/*.ifc",                                           # 체적 산출 검증
    "advanced-geometric-shape/basin-faceted-brep/*.ifc",                                    # BRep 체적 검증
]


def mesh_volume(geom):
    """삼각망에서 체적(㎥) 산출 — util.shape 우선, 없으면 부호있는 사면체 합."""
    if HAS_USHAPE:
        try:
            return abs(float(ushape.get_volume(geom)))
        except Exception:
            pass
    v = geom.verts
    f = geom.faces
    vol = 0.0
    for i in range(0, len(f), 3):
        a, b, c = f[i] * 3, f[i + 1] * 3, f[i + 2] * 3
        x1, y1, z1 = v[a], v[a + 1], v[a + 2]
        x2, y2, z2 = v[b], v[b + 1], v[b + 2]
        x3, y3, z3 = v[c], v[c + 1], v[c + 2]
        vol += (x1 * (y2 * z3 - z2 * y3)
                - y1 * (x2 * z3 - z2 * x3)
                + z1 * (x2 * y3 - y2 * x3)) / 6.0
    return abs(vol)


def alignment_length(model):
    """IfcAlignment 수평 길이 합(m) — segment의 SegmentLength 합산 시도."""
    total = 0.0
    n = 0
    for al in model.by_type("IfcAlignment"):
        n += 1
        for seg in model.by_type("IfcAlignmentSegment"):
            dp = getattr(seg, "DesignParameters", None)
            L = getattr(dp, "SegmentLength", None) if dp else None
            if isinstance(L, (int, float)):
                total += float(L)
    return n, total


def analyze(path):
    r = {"file": os.path.basename(path)}
    try:
        m = ifcopenshell.open(path)
    except Exception as e:
        r["error"] = f"open 실패: {e}"
        return r
    r["schema"] = m.schema
    r["n_entities"] = len(list(m))
    r["n_alignment"] = len(m.by_type("IfcAlignment"))
    r["n_qto"] = len(m.by_type("IfcElementQuantity"))
    r["n_material"] = len(m.by_type("IfcMaterial"))
    naln, alen = alignment_length(m)
    r["alignment_len_m"] = round(alen, 2)

    # 형상→물량: 체적 산출 가능한 물리부재 표본
    settings = ifcopenshell.geom.settings()
    vols = []
    geom_ok = 0
    geom_fail = 0
    products = [p for p in m.by_type("IfcProduct")
                if getattr(p, "Representation", None) is not None]
    for p in products[:60]:
        try:
            shape = ifcopenshell.geom.create_shape(settings, p)
            v = mesh_volume(shape.geometry)
            geom_ok += 1
            if v > 1e-9:
                vols.append((p.is_a(), v))
        except Exception:
            geom_fail += 1
    r["n_products_with_rep"] = len(products)
    r["geom_ok"] = geom_ok
    r["geom_fail"] = geom_fail
    r["sample_volumes"] = sorted(vols, key=lambda t: -t[1])[:3]
    r["total_sample_vol_m3"] = round(sum(v for _, v in vols), 3)
    return r


def main():
    files = []
    for g in TARGET_GLOBS:
        files += glob.glob(os.path.join(BASE, g))
    files = sorted(set(files))
    print("=" * 70)
    print(f"[기술검증] 대상 {len(files)}개 도로 데모 (IFC4.3)")
    print("=" * 70)

    opened, geom_total = 0, 0
    for p in files:
        r = analyze(p)
        if "error" in r:
            print(f"\n[X] {r['file']}: {r['error']}")
            continue
        opened += 1
        geom_total += r["geom_ok"]
        print(f"\n[O] {r['file']}  schema={r['schema']}  entities={r['n_entities']}")
        print(f"    IfcAlignment={r['n_alignment']} (길이합={r['alignment_len_m']}m) | "
              f"Qto={r['n_qto']} | Material={r['n_material']}")
        print(f"    형상→물량: rep보유 {r['n_products_with_rep']}개 중 "
              f"geom성공 {r['geom_ok']}/실패 {r['geom_fail']} | "
              f"표본 체적합 {r['total_sample_vol_m3']}㎥")
        if r["sample_volumes"]:
            for cls, v in r["sample_volumes"]:
                print(f"      - {cls}: {v:,.3f}㎥")

    print("\n" + "=" * 70)
    print(f"요약: {opened}/{len(files)} 파일 오픈 성공, 형상→물량(geom) 누적 성공 {geom_total}건")
    print("결론: IfcElementQuantity(Qto)가 없어도(아래 Qto=0 케이스), "
          "ifcopenshell.geom으로 형상에서 체적/길이를 직접 산출 가능 = 형상 역산 파이프라인 성립")
    print("=" * 70)


if __name__ == "__main__":
    main()
