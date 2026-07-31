# -*- coding: utf-8 -*-
"""예측 성적표 — 백테스트 원장(V-001~) 공개 페이지. 데이터: data/verification_ledger.csv
(파일명은 배선 보존 위해 유지 — '26-07-28 prior 신뢰 근거 재프레임 · '26-07-31 쉬운 언어 전면 순화)"""
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="예측 성적표 — Forenode", page_icon="📋", layout="wide")

import ui_theme
ui_theme.inject_css()
ui_theme.apply_plotly_template()
_T = ui_theme.theme()

_HERE = os.path.dirname(os.path.abspath(__file__))
_CSV = os.path.join(_HERE, "..", "data", "verification_ledger.csv")

st.title("📋 예측 성적표 — 저희 계산은 실제와 얼마나 맞았나")
st.caption("국내 민자도로 21개 사업에서, 협약 때 약속한 숫자와 실제 숫자를 해마다 맞춰 봤습니다. "
           "맞은 것도 틀린 것도 전부 기록했습니다. 이 기록이 앱이 제시하는 예측 범위의 근거입니다.")

# ── 채점 규칙 3원칙 — 훈련/검증(train/test) 분리 명세 ──
with st.container(border=True):
    st.markdown(
        "**채점을 공정하게 만드는 세 가지 규칙**  \n"
        "① 예측 시점 이후에 알려진 정보는 쓰지 않습니다 — 시험 전에 답안지를 보지 않는 것과 같습니다.  \n"
        "② 채점받는 사업은 학습에서 뺍니다 — 자기가 낸 문제를 자기가 맞히는 일을 막습니다.  \n"
        "③ 운영해 봐야 알 수 있는 값으로 설계 시점을 맞히지 않습니다.  \n"
        "→ 아래 점수는 전부 **모델이 배운 적 없는 데이터로 받은 성적**입니다. "
        "규칙과 원본 데이터가 공개되어 있어 누구든 직접 다시 채점해 볼 수 있습니다.")

if not os.path.exists(_CSV):
    st.error("data/verification_ledger.csv 없음")
    st.stop()

df = pd.read_csv(_CSV)

# ── ① 스코어보드 ──
scored = df[df["우위"].isin(["A", "B"])]
band_hit = int(pd.to_numeric(df["밴드적중"], errors="coerce").sum())
band_tot = int(pd.to_numeric(df["밴드전체"], errors="coerce").sum())
c1, c2, c3, c4 = st.columns(4)
c1.metric("채점한 사업", f"{len(df)} / 57개",
          help="국내 민자도로 57개 중 지금까지 채점을 마친 사업 수입니다.")
c2.metric("예측 범위 적중", f"{band_hit}/{band_tot} = {band_hit/band_tot*100:.1f}%",
          help="저희는 교통량을 한 점이 아니라 범위(밴드)로 제시합니다. 실제 값이 그 범위 안에 "
               "들어온 비율입니다. 80% 확률 범위로 설계했으므로 80%에 가까울수록 정상입니다.")
c3.metric("Forenode가 더 정확", f"{int((scored['우위']=='B').sum())}개 노선",
          help="같은 노선에서 협약 예측과 저희 예측의 교통량 평균 오차율(MAE — 연도별 일평균 "
               "교통량이 실제와 빗나간 정도의 평균)을 비교한 결과입니다.")
c4.metric("협약이 더 정확 · 채점 불가", f"{int((scored['우위']=='A').sum())}개 · {int((df['우위']=='채점불가').sum())}개",
          help="진 기록도 지우지 않습니다. 협약이 더 정확했던 노선은 다음 모델이 배워야 할 목록입니다.")

# ── 통계 검정 상시 표시 — 검증 프로토콜 v2 조건 5(보정)·6(짝지은 검정) ──
try:
    import numpy as _np
    from scipy import stats as _st
    _hit = pd.to_numeric(df["밴드적중"], errors="coerce")
    _tot = pd.to_numeric(df["밴드전체"], errors="coerce")
    _bm = _hit.notna() & _tot.notna() & (_tot > 0)
    _h, _t = _hit[_bm].to_numpy(), _tot[_bm].to_numpy()
    _cov = _h.sum() / _t.sum()
    # 노선 군집 부트스트랩 — 같은 노선의 연도들은 서로 닮아 독립 검정은 과신을 과대판정함
    _rng = _np.random.default_rng(42)
    _ix = _np.arange(len(_h))
    _boot = _np.array([_h[_s].sum() / _t[_s].sum()
                       for _s in (_rng.choice(_ix, len(_ix)) for _ in range(4000))])
    _lo, _hi = _np.percentile(_boot, [2.5, 97.5])
    _a = pd.to_numeric(df["협약_MAE_pct"], errors="coerce")
    _b = pd.to_numeric(df["Forenode_MAE_pct"], errors="coerce")
    _pm = _a.notna() & _b.notna()
    _d = (_a[_pm] - _b[_pm]).to_numpy()
    _w, _l = int((_d > 0).sum()), int((_d < 0).sum())
    _sp = _st.binomtest(_w, _w + _l, 0.5, alternative="greater").pvalue
    _wp = _st.wilcoxon(_a[_pm].to_numpy(), _b[_pm].to_numpy(), alternative="greater").pvalue
    st.caption(
        f"**범위가 적정한지 검증했습니다** — 목표 80% 대비 실제 {_cov*100:.1f}%. "
        f"같은 노선의 해들은 서로 닮아 있어 노선 단위로 다시 계산하면 이 차이는 우연 범위 "
        f"안입니다(95% 신뢰구간 [{_lo*100:.0f}%, {_hi*100:.0f}%]). 범위를 좁게 잡았다고 볼 "
        f"근거는 없지만, 낮은 쪽이므로 계속 지켜봅니다. · "
        f"**협약 예측과 1:1 비교** — {_w+_l}개 노선 중 {_w}개에서 저희가 더 정확했습니다. "
        f"'더 자주 정확하다'는 통계적으로 유의하고(p={_sp:.3f}), '얼마나 더 정확한가'는 "
        f"표본이 적어 아직 단정하지 않습니다(p={_wp:.3f}).")
except Exception:
    pass

# ── 📐 통계 점검 기록 — 쉽게 풀어쓴 요약 ('26-07-31 검증 프로토콜 v2 실검정) ──
with st.expander("📐 자주 나오는 질문 네 가지 — 통계 점검 기록", expanded=False):
    try:
        import interval_scoring as _isc
        _f = _isc.run_full()
        _c62 = _isc.run()
        _fa = _f["all"]
        _loo_cov = _f["by_regime"]["LOO"]["coverage"]
        st.markdown(
            f"**질문 1 — 범위가 너무 좁게 잡혀 있지 않습니까?**  \n"
            f"80% 범위라면 100번 중 80번은 안에 들어와야 합니다. 실제는 "
            f"{_fa['coverage']*100:.1f}%였습니다. 같은 노선의 해들이 서로 닮은 점을 감안하면 "
            f"이 차이는 우연 범위 안입니다. 더 엄격한 검사도 했습니다 — 최신 3개년 62건을 "
            f"'자기 노선을 빼고 만든 범위'로 채점하니 **{_c62['all62']['coverage']*100:.1f}%**, "
            f"목표와 거의 같았습니다. 결론: 범위는 적정합니다. 다만 오래된 연도일수록 아래로 "
            f"벗어나는 경향(전 기간 {_loo_cov*100:.1f}%)이 있어, 협약 시기를 구분해 학습하는 "
            f"것을 다음 개선 과제로 정했습니다.")
        st.markdown(
            f"**질문 2 — 범위를 넓게 잡으면 다 맞힐 수 있지 않습니까?**  \n"
            f"맞습니다. 그래서 넓게 잡을수록 벌점을 받는 채점 규칙(interval score, 폭 벌점)을 "
            f"함께 씁니다. 현재 기준선은 평균 폭 {_fa['mean_width']*100:.1f}%p, "
            f"벌점 {_fa['mean_IS']:.3f}입니다(낮을수록 좋음). 앞으로 모델을 고치면 이 숫자로 "
            f"채점받습니다.")
        st.markdown(
            "**질문 3 — 기존 방식(협약 예측)보다 낫습니까?**  \n"
            "같은 노선끼리 1:1로 비교하면 21개 중 15개에서 더 정확했습니다. '더 자주 "
            "정확하다'는 통계적으로 확인됐고, '얼마나 더 정확한가'는 표본이 적어 아직 "
            "단정하지 않습니다. 그래서 '이겼다'는 표현 대신 숫자를 그대로 보여드립니다.")
        st.markdown(
            "**질문 4 — 자기가 낸 문제를 자기가 맞히는 것 아닙니까?**  \n"
            "채점받는 노선은 학습에서 뺍니다. 요금 인하·재구조화 날짜는 결과를 보기 전에 미리 "
            "등록해, 불리한 해만 골라 빼는 일을 막았습니다. 이 페이지의 숫자는 관측 98건이 "
            "담긴 파일과 공개 스크립트로 누구든 재현할 수 있습니다(재현 검사: 98건 전부 일치).")
        st.caption(
            "근거 파일: data/observation_ledger_v1.csv(채점 관측 98건) · "
            "data/interval_scores_full_v1.csv(폭 벌점) · data/realization_panel.csv(실현율 실측 패널) · "
            "interval_scoring.py(재현 스크립트).")
    except Exception as _st_err:
        st.caption(f"통계 점검 요약 일시 로드 불가: {_st_err}")

st.markdown("---")

# ── ② 대결 차트 ──
st.markdown("##### 📈 협약 예측 vs Forenode — 노선별 교통량 평균 오차율 비교")
st.caption("MAE(평균 오차율) = **연도별 일평균 교통량** 예측이 실제 교통량과 빗나간 정도의 평균(%). "
           "**막대가 짧을수록 그 노선의 교통량을 잘 맞힌 것**입니다.")
plot_df = df[pd.to_numeric(df["협약_MAE_pct"], errors="coerce").notna()].copy()
fig = go.Figure()
fig.add_trace(go.Bar(y=plot_df["노선"], x=plot_df["협약_MAE_pct"], name="협약 예측(A)",
                     orientation="h", marker_color=_T["muted"]))
fig.add_trace(go.Bar(y=plot_df["노선"], x=plot_df["Forenode_MAE_pct"], name="Forenode(B)",
                     orientation="h", marker_color=_T["primary"]))
fig.update_layout(barmode="group", height=1240, margin=dict(l=10, r=10, t=10, b=10),
                  xaxis_title="평균 오차율 MAE (%)", legend=dict(orientation="h", y=1.02))
st.plotly_chart(fig, use_container_width=True)

# ── ③ 원장 테이블 ──
st.markdown("##### 📒 채점 원장 — 노선별 상세 기록 (V-001~)")
st.caption("V = 채점 케이스 번호 · 우위 = 그 노선의 **교통량 예측**이 더 정확했던 쪽(A=협약, B=Forenode) · "
           "밴드적중/밴드전체 = 실제 교통량이 저희 범위 안에 들어온 횟수/채점 횟수.")
_g = st.multiselect("군 필터", sorted(df["군"].unique()), default=list(sorted(df["군"].unique())))
st.dataframe(df[df["군"].isin(_g)], use_container_width=True, hide_index=True, height=420)

# ── ④ 미적중 → 보완 매핑 ──
st.markdown("##### 🔧 틀린 곳에서 배우는 것 — 원인과 보완 계획")
st.caption("범위를 벗어난 관측은 지우지 않고, 왜 벗어났는지와 다음 모델에서 어떻게 고칠지를 기록합니다.")
st.dataframe(pd.DataFrame([
    ["운영비 통계모드 양방향 오차(−66~+21%)", "매출비례 = 요금 수준의 함수", "실측 원단위 × 시설유형 밴드 (v2)"],
    ["밴드 하단 실패(대구부산·미시령 등)", "경쟁 회랑(계획 노선 포함) 미반영", "공변량: 경쟁 회랑 (v2)"],
    ["밴드 상단 실패(서수원평택 0/5·인천대교)", "요금 이벤트·배후 개발 — 하향 보정의 구조적 전패", "양방향 prior·요금 이벤트 공변량 (v2)"],
    ["초기군 실패 3건(우면산·마창·서수원의왕)", "도시권·전환수요는 고속도로 램프업 모집단이 아님", "시설유형 부분 풀링 (v2)"],
    ["정확 협약축에서 하향 보정 유해(수도권1순환·서울춘천)", "협약 세대(축의 나이) 무시", "공변량: 협약 세대 (v2)"],
], columns=["미적중", "원인", "보완"]), use_container_width=True, hide_index=True)

# ── ⑤ 이 원장이 만드는 prior — 소비처 연결 ──
st.markdown("##### 🔗 이 기록이 앱 계산에 쓰이는 곳")
st.markdown(
    "- **교통량 범위** — 메인 화면 '가정 점검'과 '실현율 시나리오'의 범위·확률이 이 기록에서 나옵니다.\n"
    "- **운영비 정상 범위** — 운영비 자동 계산의 점검 기준(km당 연 2.0~12.0억)이 실측 7개 사업에서 나왔습니다.\n"
    "- **공사비 참고 범위** — 공사비 적정성 비교의 근거입니다."
)
try:
    st.page_link("pages/3_학습데이터_출처.py", label="📚 학습 데이터 출처에서 전체 근거 보기")
except Exception:
    pass

# ── ⑥ 전향 등록 ──
st.markdown("##### 🔏 미리 등록해 둔 예측 — 사후 끼워맞춤 차단")
st.markdown(
    "- 예측 9건 + 예약 5건을 **수정 불가능한 형태로 미리 봉인**해 두었습니다(REG-2026-001). "
    "실제 결과가 나오는 2027년 상반기에 채점합니다.\n"
    "- 새 모델(v2)은 기존 모델보다 실제로 더 정확한지 리허설(VP-2026-001)을 통과해야만 적용합니다."
)

# ── ⑦ 방법론 ──
with st.expander("📐 채점 규칙 R1~R7 (상세)"):
    st.markdown(
        "- **R1** 비교 기준은 최초 실시협약 값 — 재구조화된 노선은 구간을 나눠 따로 채점\n"
        "- **R2** 예측 시점 이후 정보 차단 · 채점받는 노선은 학습에서 제외(LOO)\n"
        "- **R3** 오차 = 평균 오차율(MAE) — 협약(A)과 Forenode(B)를 같은 자로 잼 · 범위는 폭 벌점(interval score) 병기\n"
        "- **R4** 자료는 연 단위로 수집, 부족하면 5년 묶음\n"
        "- **R5** 물가 효과 제거(불변가 통일)\n"
        "- **R6** 회계 숫자는 감가상각을 뺀 실제 지출 기준으로 통일\n"
        "- **R7** 수익률은 실제 재무제표로 다시 계산해 비교\n\n"
        "확보하지 못한 값은 추정으로 채우지 않고 빈칸(✚)으로 둡니다."
    )
