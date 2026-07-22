# -*- coding: utf-8 -*-
"""검증 성적표 — 백테스트 원장(V-001~) 공개 페이지. 데이터: data/verification_ledger.csv"""
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="검증 성적표 — Forenode", page_icon="📋", layout="wide")

_HERE = os.path.dirname(os.path.abspath(__file__))
_CSV = os.path.join(_HERE, "..", "data", "verification_ledger.csv")

st.title("📋 검증 성적표")
st.caption("정확성은 주장이 아니라 채점 기록이다 — 운영이 끝나가는 실제 사업으로 모델을 거꾸로 채점한 사후검증 원장. 실패도 기록한다.")

if not os.path.exists(_CSV):
    st.error("data/verification_ledger.csv 없음")
    st.stop()

df = pd.read_csv(_CSV)

# ── ① 스코어보드 ──
scored = df[df["우위"].isin(["A", "B"])]
band_hit = int(pd.to_numeric(df["밴드적중"], errors="coerce").sum())
band_tot = int(pd.to_numeric(df["밴드전체"], errors="coerce").sum())
c1, c2, c3, c4 = st.columns(4)
c1.metric("사후검증 완료", f"{len(df)} / 57 사업")
c2.metric("교통량 밴드 적중", f"{band_hit}/{band_tot} = {band_hit/band_tot*100:.1f}%",
          help="P10~P90(80% 구간) 적중률. 연차별 prior 소급 적용 시 70/95 = 73.7%")
c3.metric("Forenode(B) 우위", f"{int((scored['우위']=='B').sum())}건",
          help="교통량 MAE 기준 — 최초 실시협약 예측(A)과의 대결")
c4.metric("협약(A) 우위 · 채점불가", f"{int((scored['우위']=='A').sum())}건 · {int((df['우위']=='채점불가').sum())}건",
          help="진 것도 기록한다 — A 우위 케이스는 v2 공변량(협약 세대·요금 이벤트 등)의 근거")

st.markdown("---")

# ── ② 대결 차트 ──
st.markdown("##### ⚔️ 협약 예측 vs Forenode — 노선별 교통량 MAE (낮을수록 정확)")
plot_df = df[pd.to_numeric(df["협약_MAE_pct"], errors="coerce").notna()].copy()
fig = go.Figure()
fig.add_trace(go.Bar(y=plot_df["노선"], x=plot_df["협약_MAE_pct"], name="협약(A)",
                     orientation="h", marker_color="#AEB9D4"))
fig.add_trace(go.Bar(y=plot_df["노선"], x=plot_df["Forenode_MAE_pct"], name="Forenode(B)",
                     orientation="h", marker_color="#1F3864"))
fig.update_layout(barmode="group", height=620, margin=dict(l=10, r=10, t=10, b=10),
                  xaxis_title="MAE (%)", legend=dict(orientation="h", y=1.05))
st.plotly_chart(fig, use_container_width=True)

# ── ③ 원장 테이블 ──
st.markdown("##### 📒 원장 (V-001~)")
_g = st.multiselect("군 필터", sorted(df["군"].unique()), default=list(sorted(df["군"].unique())))
st.dataframe(df[df["군"].isin(_g)], use_container_width=True, hide_index=True, height=420)

# ── ④ 패배 → 보완 매핑 ──
st.markdown("##### 🩹 패배 지점 → 정면 보완 (요약)")
st.dataframe(pd.DataFrame([
    ["운영비 통계모드 양방향 오차(−66~+21%)", "매출비례 = 요금 수준의 함수", "실측 원단위 × 시설유형 밴드 (v2)"],
    ["밴드 하단 실패(대구부산·미시령 등)", "경쟁 회랑(계획 노선 포함) 미반영", "공변량: 경쟁 회랑 (v2)"],
    ["밴드 상단 실패(서수원평택 0/5·인천대교)", "요금 이벤트·배후 개발 — 하향 보정의 구조적 전패", "양방향 prior·요금 이벤트 공변량 (v2)"],
    ["초기군 실패 3건(우면산·마창·서수원의왕)", "도시권·전환수요는 고속도로 램프업 모집단이 아님", "시설유형 부분 풀링 (v2)"],
    ["정확 협약축에서 하향 보정 유해(수도권1순환·서울춘천)", "협약 세대(축의 나이) 무시", "공변량: 협약 세대 (v2)"],
], columns=["패배", "원인", "보완"]), use_container_width=True, hide_index=True)

# ── ⑤ 전향 등록 ──
st.markdown("##### 🔏 전향 등록 (사후 끼워맞춤 차단)")
st.markdown(
    "- **REG-2026-001** — 예측 9건 + 예약 5건 사전 봉인(커밋 해시), 1차 채점 2027 상반기.\n"
    "- v2 모델 채택은 **VP-2026-001 시점 절단 리허설**(v1 대비 MAE 3%p 개선 기준) 통과 시에만."
)

# ── ⑥ 방법론 ──
with st.expander("📐 채점 규칙 R1~R7"):
    st.markdown(
        "- **R1** 계획값 = 최초 실시협약 기준(재구조화 시 구간 분리)\n"
        "- **R2** as-of 시점 절단 · LOO(leave-one-out) prior — 자기 자신 제외\n"
        "- **R3** 오차 정의: MAE(실현율 기준) · 오차A=협약, 오차B=Forenode\n"
        "- **R4** 연 단위 수집, 부족 시 5년 블록\n"
        "- **R5** 불변가 통일(CPI)\n"
        "- **R6** 회계 추출 표준: 영업비용 − 무형상각 − 유형감가\n"
        "- **R7** 수익률은 실측 재무로 재구성한 IRR로 대사\n\n"
        "빈칸·미확보는 추정하지 않고 공란(✚ 원칙). 원문: 검증 원장(verification-log)."
    )
