"""
Forenode — IFC 시험 프로토타입 (app_ifc_prototype.py)  ※ 개발자 전용

목적
----
개발자(Forenode) 본인이 BIM IFC 파일을 업로드해, 물량 추출 결과를 확인하고
그 값을 사업성/수익성 모델 입력으로 매핑해 시험하는 내부 도구.
공개 앱(app.py)에는 IFC 기능을 아직 노출하지 않으며, 이 파일은 별도로 둔다.

실행: streamlit run app_ifc_prototype.py

흐름
----
1) IFC 업로드 → ifc_extract.extract_ifc 로 물량·구조 요약
2) 추출 결과 표시(스키마·요소타입별 수량·인프라 타입)
3) 물량 → 시나리오 입력 매핑(IFC 참고치 + 수동 확정)
4) CAPEX 추정 + 현금흐름 계산으로 NPV/IRR/DSCR 즉시 확인

주의: IFC 수량셋(Qto)이 없는 파일은 형상 기반 산출(후속 증분) 전까지 수동 입력으로 진행.
"""
from __future__ import annotations

import os
import tempfile

import streamlit as st

from ifc_extract import extract_ifc

# 엔진 함수는 공개 앱과 100% 동일한 것을 재사용 (중복 구현 금지)
from app import build_cashflow, calc_wacc_detail, estimate_toll_revenue
from pretest_regressor import estimate_capex_from_route


st.set_page_config(page_title="Forenode IFC 프로토타입 (개발자)", page_icon="🧪", layout="wide")

st.title("🧪 Forenode — IFC 시험 프로토타입")
st.caption(
    "**개발자 전용 내부 도구.** BIM IFC 파일을 업로드해 물량 추출 결과를 확인하고 "
    "사업성 모델 입력으로 매핑·시험합니다. 공개 앱(app.py)에는 포함되지 않습니다."
)

# ──────────────────────────────────────────────────────────
# 1) 업로드 & 추출
# ──────────────────────────────────────────────────────────
up = st.file_uploader("IFC 파일 업로드 (.ifc)", type=["ifc"])

summary = None
if up is not None:
    # ifcopenshell은 경로 기반 open이 안정적이라 임시파일로 저장 후 파싱
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        tmp.write(up.getbuffer())
        tmp_path = tmp.name
    try:
        with st.spinner("IFC 파싱 중…"):
            summary = extract_ifc(tmp_path)
    except Exception as e:
        st.error(f"IFC를 읽지 못했습니다: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

if summary:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("스키마", summary["schema"])
    c2.metric("요소(IfcElement) 수", f"{summary['element_count']:,}")
    c3.metric("전체 엔티티 수", f"{summary['entity_count']:,}")
    infra = summary["infrastructure"]
    c4.metric("도로/교량", f"{infra['roads']} / {infra['bridges']}")

    qty = summary.get("quantities", {})
    with st.expander("📐 추출 물량 (요소타입별)", expanded=True):
        if not qty:
            st.warning(
                "이 IFC에는 수량셋(Qto/IfcElementQuantity)이 없습니다. "
                "형상 기반 수량 산출(다음 증분) 전까지는 아래 매핑을 **수동**으로 채워 진행하세요."
            )
        else:
            unit_label = {
                "length_m": "길이 (m)", "area_m2": "면적 (㎡)", "volume_m3": "체적 (㎥)",
                "count": "개수", "weight_kg": "중량 (kg)",
            }
            for cat, d in qty.items():
                rows = [{"요소타입": k, unit_label.get(cat, cat): v}
                        for k, v in d.items() if k != "_total"]
                st.markdown(f"**{unit_label.get(cat, cat)}** · 합계 `{d.get('_total', 0):,.2f}`")
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("🔎 인프라 타입 / 상위 엔티티 / 원본 요약(JSON)"):
        st.write("인프라 타입:", infra)
        st.write("상위 엔티티 타입:", summary["top_entity_types"])
        st.json(summary)

st.divider()

# ──────────────────────────────────────────────────────────
# 2) 물량 → 시나리오 입력 매핑 (IFC 참고치 + 수동 확정)
# ──────────────────────────────────────────────────────────
st.subheader("🔗 물량 → 시나리오 입력 매핑")
st.caption(
    "IFC에서 자동 도출 가능한 값은 기본값으로 제시하고, 개발자가 확정합니다. "
    "현 단계는 도로 연장·구조 비율의 자동 산출이 미완(형상 기반 산출은 후속)이라 **수동 확정**을 전제로 합니다."
)

# IFC 참고치(있으면) — 보수적으로 표면화만, 자동 확정하지 않음
ifc_len_hint = 0.0
if summary and summary.get("quantities", {}).get("length_m"):
    ifc_len_hint = summary["quantities"]["length_m"].get("_total", 0.0) / 1000.0  # m→km (참고용)

col_a, col_b, col_c = st.columns(3)
with col_a:
    road_length = st.number_input(
        "노선 연장 (km)", min_value=0.1, value=float(round(ifc_len_hint, 2)) if ifc_len_hint > 0 else 10.0,
        step=0.1, help="IFC length 합계는 도로 연장이 아닐 수 있음(부재 길이 포함). 반드시 확인.",
    )
    lanes = st.number_input("차로 수", min_value=2, max_value=12, value=4, step=2)
    terrain = st.selectbox("지형", ["평지", "구릉", "산악"], index=0)
with col_b:
    bridge_ratio = st.slider("교량 비율", 0.0, 0.6, 0.15, 0.01)
    tunnel_ratio = st.slider("터널 비율", 0.0, 0.7, 0.20, 0.01)
    business_type = st.selectbox("사업유형", ["BTO", "BTO-rs", "BTO-ann", "BTL", "BTO+BTL"], index=2)
with col_c:
    daily_traffic = st.number_input("일 통행량 (대)", min_value=1000, value=50000, step=1000)
    toll_per_km = st.number_input("km당 통행료 (원)", min_value=10, value=80, step=5)
    construction_years = st.number_input("건설기간 (년)", min_value=1, max_value=10, value=5)
    operation_years = st.number_input("운영기간 (년)", min_value=5, max_value=50, value=30)

# ──────────────────────────────────────────────────────────
# 3) CAPEX 추정 + 현금흐름 계산
# ──────────────────────────────────────────────────────────
if st.button("📊 이 입력으로 사업성 계산", type="primary", use_container_width=True):
    capex = estimate_capex_from_route(
        road_length_km=road_length, lanes=int(lanes), terrain=terrain,
        bridge_ratio=bridge_ratio, tunnel_ratio=tunnel_ratio, business_type=business_type,
    )
    capex_eok = capex["capex_estimate_억"]

    toll_df = estimate_toll_revenue(
        road_length, int(daily_traffic), float(toll_per_km),
        growth_rate=0.025, heavy_vehicle_ratio=0.30, heavy_vehicle_surcharge=2.5,
        years=int(operation_years),
    )
    ann_rev = float(toll_df["Revenue_억"].iloc[0]) if len(toll_df) > 0 else 0.0

    wacc_info = calc_wacc_detail(
        rf=0.035, mrp=0.06, beta=0.7, equity_ratio=0.25, debt_rate=0.05, tax_rate=0.22,
    )

    _, metrics = build_cashflow(
        capex_억=capex_eok, annual_revenue_억=ann_rev,
        construction_years=int(construction_years), operation_years=int(operation_years),
        opex_ratio=0.30, discount_rate=wacc_info["wacc"], inflation=0.02, growth_rate=0.025,
        equity_ratio=0.25, debt_rate=0.05, business_type=business_type, tax_rate=0.22,
    )

    st.success(f"CAPEX 추정 {capex_eok:,.0f}억 (km당 {capex['per_km_억']:.0f}억) · 1년차 수익 {ann_rev:,.1f}억")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("NPV", f"{metrics['npv']:,.0f}억")
    k2.metric("명목 IRR", f"{metrics['nominal_irr']*100:.1f}%")
    k3.metric("DSCR(최소/평균)", f"{metrics['dscr_min']:.2f} / {metrics['dscr_avg']:.2f}")
    k4.metric("WACC", f"{wacc_info['wacc']*100:.2f}%")
    st.caption(
        "※ 일부 금융 가정(자기자본 25%·차입 5%·WACC 표준 등)은 프로토타입 고정값입니다. "
        "정밀 분석은 공개 앱의 시나리오 설정을 사용하세요."
    )
