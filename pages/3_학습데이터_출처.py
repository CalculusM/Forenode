# -*- coding: utf-8 -*-
"""학습 데이터·출처 — 모델 단위 provenance 페이지 (기관 출처 페이지와 별개)."""
import json
import os

import pandas as pd
import streamlit as st

st.set_page_config(page_title="학습 데이터 출처 — Forenode", page_icon="📚", layout="wide")

import ui_theme
ui_theme.inject_css()
ui_theme.apply_plotly_template()

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")

st.title("📚 학습 데이터 · 출처")
st.caption("모델별로 무엇을, 몇 건, 어디서 학습했는지와 한계를 공개합니다.")

_wb = {}
try:
    with open(os.path.join(_ROOT, "weibull_params.json"), encoding="utf-8") as f:
        _wb = json.load(f)
except Exception:
    pass

MODELS = [
    ("① 수익성 등급 — XGBoost+SHAP",
     "DART 감사보고서 기반 민자 SPC 13개사 5년치 59건",
     "금융감독원 DART(공시)",
     "LOOCV 93.2% — 룰 기반 라벨의 복원 정확도(외부 부실 라벨 검증은 별도 과제)"),
    ("② 시설 열화 — Weibull MLE",
     f"한국도로공사 포장 보수 관측 {_wb.get('n_observed', 357)}건 (전체 {31602:,}구간 중)",
     "공공데이터포털 — 도로공사 포장일반·보수현황",
     _wb.get("interpretation", {}).get("data_note", "보수 집행 기록 = 물리 열화의 대용치")),
    ("③ 운영비(OPEX) — 시계열·LCC",
     "도로공사 보수공사 발주이력 11년치 4,380건 + 수선주기·단가 config + 백테스트 실측 원단위 7점(2.5~33.4억/km/년)",
     "공공데이터포털·건설공사 표준품셈 2026·도로 유지관리 지침(재매핑 중)·백테스트 원장 V-001~021",
     "발주이력은 상대 패턴 신뢰(단위 미명시·백만원 추정) · 매출비례 모드는 양방향 오차 실증 → 원단위 L3 경고 부착"),
    ("④ 자본비(CAPEX) — 회귀 참고치",
     "기준 350억/km(4차로 평지) × 차로·지형·교량·터널 보정",
     "실무 통상 가정(휴리스틱) — 참고범위 ±20%",
     "백테스트 투자비 실측: 인천공항 오차 −1.1% · 계획vs정산 패널 축적 후 실측 회귀로 교체 예정"),
    ("⑤ 법제 자문 — RAG",
     "민간투자법·유료도로법·민간투자사업기본계획 등 16개 법령 1,963청크",
     "국가법령정보센터",
     "생성형 답변 — 조문 원문 대사·개정 추적 주기화 과제"),
]

for name, data, src, limit in MODELS:
    with st.container(border=True):
        st.markdown(f"**{name}**")
        a, b = st.columns([3, 2])
        a.markdown(f"학습 데이터: {data}")
        a.caption(f"한계: {limit}")
        b.markdown(f"출처: {src}")

st.markdown("---")
st.markdown("##### 📉 수요 prior 4종 — (실측/예측) 비율의 기준 분포")
try:
    from demand_bias import BENCHMARK_PRIORS
    rows = []
    for k, p in BENCHMARK_PRIORS.items():
        rows.append([k, p["dist"], p["p1"], p["p2"], p["source"]])
    st.dataframe(pd.DataFrame(rows, columns=["prior", "분포", "중심(p1)", "산포(p2)", "출처"]),
                 use_container_width=True, hide_index=True)
except Exception as e:
    st.caption(f"prior 로드 실패: {e}")

st.markdown("##### 📋 백테스트 실측 패널 (benchmark_panel.csv)")
_bp = os.path.join(_ROOT, "data", "benchmark_panel.csv")
if os.path.exists(_bp):
    st.dataframe(pd.read_csv(_bp), use_container_width=True, hide_index=True)
    st.caption("빈칸 = 미확보(추정치 미기재 원칙). 출처: 백테스트 원장 V-001~021.")

st.page_link("pages/2_검증_성적표.py", label="→ 📋 검증 성적표(원장 채점 기록) 보기")
