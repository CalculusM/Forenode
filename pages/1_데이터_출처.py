# -*- coding: utf-8 -*-
"""데이터 출처 페이지 — 4기관 융합 데이터 상세.

2026-07 멀티페이지 전환: app.py 사이드바 상시 카드(A-09)를 본 페이지로 분리.
"""
import streamlit as st

from data_sources import DATA_SOURCES, render_data_flow_diagram

st.set_page_config(page_title="데이터 출처 — Forenode", page_icon="📊", layout="wide")

import ui_theme
ui_theme.inject_css()
ui_theme.apply_plotly_template()

st.title("📊 데이터 출처 — 4기관 융합")
st.caption("총 16종 데이터셋 · 7개 분석 모듈")

render_data_flow_diagram()

st.markdown("---")

for src in DATA_SOURCES:
    st.markdown(f"#### {src['icon']} {src['name']}  <span style='font-size:0.7em;color:#888'>{src['name_en']}</span>",
                unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**데이터셋**")
        for ds in src["datasets"]:
            st.markdown(f"- {ds}")
    with c2:
        st.markdown("**활용 모듈**")
        st.markdown(" · ".join(f"`{m}`" for m in src["modules"]))
    st.markdown("")
