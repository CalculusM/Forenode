"""
헤드리스 검증 스크립트 (임시) — app_ifc_prototype.py의 파이프라인을 Streamlit UI 없이 재현.

목적: IFC 추출 → CAPEX → toll → WACC → cashflow → NPV/IRR/DSCR/WACC 전 구간이
에러 없이 수식대로 산출되는지 확인. (전체 사업 인풋이 없어 값은 부정확할 수 있으나
'수식·기능이 정상 작동하는지'를 본다.)

실행: python _smoke_ifc_pipeline.py
"""
from __future__ import annotations

import os
import sys

from ifc_extract import extract_ifc
from app import build_cashflow, calc_wacc_detail, estimate_toll_revenue
from pretest_regressor import estimate_capex_from_route

DOWNLOADS = os.path.expanduser("~/Downloads")
SAMPLES = [
    os.path.join(DOWNLOADS, "Infra-Road.ifc"),
    os.path.join(DOWNLOADS, "Infra-Bridge.ifc"),
]


def run_pipeline(summary: dict) -> None:
    """프로토타입 매핑 로직과 동일하게 엔진을 한 바퀴 돌린다."""
    # IFC length 합계 → 노선 연장 참고치 (m→km). 없으면 기본 10km.
    ifc_len_hint = 0.0
    qmap = summary.get("quantities", {})
    if qmap.get("length_m"):
        ifc_len_hint = qmap["length_m"].get("_total", 0.0) / 1000.0
    road_length = round(ifc_len_hint, 2) if ifc_len_hint > 0 else 10.0

    # 프로토타입 고정 매핑 입력 (수동 확정 전제의 기본값)
    lanes, terrain = 4, "평지"
    bridge_ratio, tunnel_ratio = 0.15, 0.20
    business_type = "BTO-a"
    daily_traffic, toll_per_km = 50000, 80
    construction_years, operation_years = 5, 30

    capex = estimate_capex_from_route(
        road_length_km=road_length, lanes=lanes, terrain=terrain,
        bridge_ratio=bridge_ratio, tunnel_ratio=tunnel_ratio, business_type=business_type,
    )
    capex_eok = capex["capex_estimate_억"]

    toll_df = estimate_toll_revenue(
        road_length, daily_traffic, float(toll_per_km),
        growth_rate=0.025, heavy_vehicle_ratio=0.30, heavy_vehicle_surcharge=2.5,
        years=operation_years,
    )
    ann_rev = float(toll_df["Revenue_억"].iloc[0]) if len(toll_df) > 0 else 0.0

    wacc_info = calc_wacc_detail(
        rf=0.035, mrp=0.06, beta=0.7, equity_ratio=0.25, debt_rate=0.05, tax_rate=0.22,
    )

    cf_df, metrics = build_cashflow(
        capex_억=capex_eok, annual_revenue_억=ann_rev,
        construction_years=construction_years, operation_years=operation_years,
        opex_ratio=0.30, discount_rate=wacc_info["wacc"], inflation=0.02, growth_rate=0.025,
        equity_ratio=0.25, debt_rate=0.05, business_type=business_type, tax_rate=0.22,
    )

    print(f"    노선연장(추정)  : {road_length} km  (IFC length합계 기반 참고치)")
    print(f"    CAPEX          : {capex_eok:,.0f}억  (km당 {capex['per_km_억']:.0f}억)")
    print(f"    1년차 수익      : {ann_rev:,.1f}억")
    print(f"    WACC           : {wacc_info['wacc']*100:.2f}%")
    print(f"    NPV            : {metrics['npv']:,.0f}억")
    print(f"    명목 IRR        : {metrics['nominal_irr']*100:.2f}%")
    print(f"    DSCR 최소/평균  : {metrics['dscr_min']:.2f} / {metrics['dscr_avg']:.2f}")
    print(f"    현금흐름 행수    : {len(cf_df)}  (건설{construction_years}+운영{operation_years})")


def main() -> int:
    for path in SAMPLES:
        name = os.path.basename(path)
        print("=" * 70)
        print(f"[{name}]")
        if not os.path.exists(path):
            print(f"  (파일 없음: {path})")
            continue
        try:
            summary = extract_ifc(path)
        except Exception as e:
            print(f"  [추출 실패] {e}")
            continue

        print(f"  스키마={summary['schema']}  요소={summary['element_count']:,}  "
              f"엔티티={summary['entity_count']:,}")
        print(f"  인프라타입: {summary['infrastructure']}")
        q = summary.get("quantities", {})
        if not q:
            print("  물량(Qto): 없음 → length 미검출, 노선연장 기본값(10km)으로 진행")
        else:
            for cat, d in q.items():
                print(f"  물량[{cat}] _total={d.get('_total', 0):,.2f}  "
                      f"(요소타입 {len([k for k in d if k != '_total'])}종)")
        print("  --- 엔진 파이프라인 ---")
        try:
            run_pipeline(summary)
            print("  >>> 파이프라인 OK")
        except Exception as e:
            import traceback
            print(f"  [파이프라인 실패] {e}")
            traceback.print_exc()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
