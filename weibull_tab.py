"""
============================================================
ROADx Phase 3 - Weibull 열화곡선 탭 모듈
============================================================
역할:
  - 학습된 Weibull 파라미터로 시설물 보수 시점 예측
  - 사용자 입력 (운영기간) → 잔여수명·보수확률 계산
  - 합성 데이터 PoC vs 실데이터 비교 (반출 후 자동)

전제조건:
  - weibull_fit.py로 weibull_params.json 생성 완료
  - weibull_curve.png, weibull_hazard.png 생성 완료

사용법:
  1. 이 파일을 app.py와 같은 폴더에 두기 (weibull_tab.py)
  2. app.py에 import:
       from weibull_tab import render_weibull_tab
  3. 10번째 탭 추가:
       tabs = st.tabs([..., "🔧 Weibull 열화"])
       with tabs[9]:
           render_weibull_tab()
============================================================
"""
import json
from pathlib import Path

import numpy as np
import streamlit as st


# ════════════════════════════════════════════════════════════
# 데이터 로드
# ════════════════════════════════════════════════════════════
@st.cache_data
def load_weibull_params():
    """weibull_params.json 로드"""
    p = Path("./weibull_params.json")
    if not p.exists():
        return None, "weibull_params.json 없음 — weibull_fit.py 먼저 실행"
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"파일 로드 실패: {e}"


# ════════════════════════════════════════════════════════════
# Weibull 함수 (실시간 계산용)
# ════════════════════════════════════════════════════════════
def weibull_survival(t, beta, eta):
    """생존확률 S(t) = exp(-(t/η)^β)"""
    return np.exp(-((np.asarray(t) / eta) ** beta))


def weibull_hazard(t, beta, eta):
    """위험률 h(t) = (β/η) · (t/η)^(β-1)"""
    return (beta / eta) * (np.asarray(t) / eta) ** (beta - 1)


def weibull_failure_prob(t, beta, eta):
    """누적고장확률 F(t) = 1 - S(t)"""
    return 1 - weibull_survival(t, beta, eta)


def remaining_life_at_age(current_age, target_failure_prob, beta, eta):
    """현재 나이에서 목표 손상확률 도달까지 남은 시간"""
    s_current = weibull_survival(current_age, beta, eta)
    if s_current <= 0:
        return 0
    target_s = (1 - target_failure_prob)
    if target_s >= s_current:
        return 0
    # S(t_target) = target_s에서 t_target 역산
    t_target = eta * (-np.log(target_s)) ** (1 / beta)
    return max(0, t_target - current_age)


# ════════════════════════════════════════════════════════════
# UI 렌더링
# ════════════════════════════════════════════════════════════
def render_model_info(params):
    """모델 정보 박스"""
    cols = st.columns(4)
    with cols[0]:
        st.metric(
            "β (shape)",
            f"{params['beta_hat']:.3f}",
            help="고장 모드 — 1보다 크면 마모고장 (시간 갈수록 위험 증가)"
        )
    with cols[1]:
        st.metric(
            "η (scale)",
            f"{params['eta_hat']:.2f}년",
            help="특성수명 — 약 63.2% 손상 발생 시점"
        )
    with cols[2]:
        st.metric(
            "중위수명",
            f"{params['median_life']:.2f}년",
            help="50% 손상 발생 시점"
        )
    with cols[3]:
        st.metric(
            "샘플 수",
            f"{params['n_samples']}건",
            f"관측 {params['n_observed']} · 절단 {params['n_censored']}",
            help="학습에 사용된 포장 손상 관측 데이터"
        )


def render_data_source_badge(params):
    """데이터 출처 명시 (PoC 합성 데이터인지, 실데이터인지)"""
    source = params.get("data_source", "synthetic")
    if source == "synthetic":
        st.warning(
            "🧪 **현재 합성 데이터 PoC 결과** — 한국도로공사 통계 기반 합성 데이터 100건. "
            "공공 실데이터 또는 안심구역 데이터로 갱신 시 자동 학습됩니다."
        )
    else:
        # 데이터 출처 키워드로 정확한 메시지 분기
        if "포장일반현황" in source or "공공데이터포털" in source:
            st.success(
                f"✅ **실데이터 학습 결과** — 출처: {source}. "
                f"공공 OpenAPI 데이터를 시계열 결합하여 보수 이벤트를 추출, MLE로 학습한 모델입니다."
            )
        elif "안심구역" in source or "포장탐지" in source or "대전남부순환" in source:
            st.success(
                f"✅ **안심구역 실데이터 학습** — 출처: {source}. "
                f"안심구역 반출 통계로 학습된 모델입니다."
            )
        else:
            st.success(
                f"✅ **실데이터 학습 결과** — 출처: {source}."
            )


def render_interpretation(params):
    """모델 해석"""
    interp = params.get("interpretation", {})
    mode = interp.get("failure_mode", "?")
    action = interp.get("recommended_action", "?")
    
    color_map = {"마모고장": "#E24B4A", "우발고장": "#EF9F27", "초기고장": "#1D9E75"}
    color = color_map.get(mode, "#999")
    
    st.markdown(
        f"""<div style="background: {color}15;
                        border-left: 4px solid {color};
                        padding: 14px 18px;
                        border-radius: 6px;
                        margin: 12px 0;">
            <div style="font-size: 16px; font-weight: 600;
                        color: {color};">
                고장 모드: {mode}
            </div>
            <div style="font-size: 14px; color: #1a1a2e;
                        margin-top: 6px;">
                권장 조치: <strong>{action}</strong>
            </div>
        </div>""",
        unsafe_allow_html=True
    )


def render_simulator(params):
    """잔여수명 시뮬레이터"""
    st.markdown("### 🎯 시설물 잔여수명 예측")
    st.caption(
        "운영 경과년수와 목표 손상확률을 입력하면, "
        "도달까지의 잔여수명과 권장 보수시점을 계산합니다."
    )
    
    beta = params['beta_hat']
    eta = params['eta_hat']
    
    sim_cols = st.columns(2)
    with sim_cols[0]:
        current_age = st.slider(
            "현재 운영 경과년수 (년)",
            0.0, 30.0, 5.0, 0.5,
            help="평가하려는 시설물의 운영 시작부터 현재까지 경과년수"
        )
    with sim_cols[1]:
        target_prob = st.slider(
            "목표 손상확률 (%)",
            10, 80, 30, 5,
            help="이 확률에 도달하기 전 보수가 필요한 임계점"
        ) / 100
    
    # 계산
    current_failure = weibull_failure_prob(current_age, beta, eta)
    current_hazard = weibull_hazard(current_age, beta, eta)
    remaining = remaining_life_at_age(current_age, target_prob, beta, eta)
    
    # 결과 카드
    st.markdown("#### 📊 예측 결과")
    res_cols = st.columns(3)
    
    with res_cols[0]:
        color = "#E24B4A" if current_failure > 0.5 else (
            "#EF9F27" if current_failure > 0.2 else "#1D9E75"
        )
        st.markdown(
            f"""<div style="background: {color}15;
                            border-top: 4px solid {color};
                            padding: 14px 18px;
                            border-radius: 6px;
                            text-align: center;">
                <div style="font-size: 12px; color: #666;">
                    현재 시점 누적 손상확률
                </div>
                <div style="font-size: 32px; font-weight: 600;
                            color: {color}; margin: 8px 0;">
                    {current_failure:.1%}
                </div>
                <div style="font-size: 11px; color: #999;">
                    {current_age}년 운영 시점
                </div>
            </div>""",
            unsafe_allow_html=True
        )
    
    with res_cols[1]:
        # 잔여수명 색상
        color = "#E24B4A" if remaining < 2 else (
            "#EF9F27" if remaining < 5 else "#1D9E75"
        )
        st.markdown(
            f"""<div style="background: {color}15;
                            border-top: 4px solid {color};
                            padding: 14px 18px;
                            border-radius: 6px;
                            text-align: center;">
                <div style="font-size: 12px; color: #666;">
                    {target_prob:.0%} 손상확률까지 남은 시간
                </div>
                <div style="font-size: 32px; font-weight: 600;
                            color: {color}; margin: 8px 0;">
                    {remaining:.1f}년
                </div>
                <div style="font-size: 11px; color: #999;">
                    이 시점까지 보수 권장
                </div>
            </div>""",
            unsafe_allow_html=True
        )
    
    with res_cols[2]:
        st.markdown(
            f"""<div style="background: #534AB715;
                            border-top: 4px solid #534AB7;
                            padding: 14px 18px;
                            border-radius: 6px;
                            text-align: center;">
                <div style="font-size: 12px; color: #666;">
                    현재 위험률 h(t)
                </div>
                <div style="font-size: 32px; font-weight: 600;
                            color: #534AB7; margin: 8px 0;">
                    {current_hazard:.4f}
                </div>
                <div style="font-size: 11px; color: #999;">
                    /년 (단위시간당 손상률)
                </div>
            </div>""",
            unsafe_allow_html=True
        )
    
    return beta, eta, current_age, target_prob


def render_curves(params, current_age, target_prob):
    """생존곡선 + 위험률 인터랙티브 차트"""
    beta = params['beta_hat']
    eta = params['eta_hat']
    
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.info("Plotly 미설치 — 정적 PNG 차트만 표시")
        if Path("./weibull_curve.png").exists():
            st.image("./weibull_curve.png")
        if Path("./weibull_hazard.png").exists():
            st.image("./weibull_hazard.png")
        return
    
    # 시간 그리드
    t_max = max(eta * 2.5, current_age * 1.5, 25)
    t_grid = np.linspace(0.01, t_max, 200)
    
    # 생존곡선 + 누적고장
    survival = weibull_survival(t_grid, beta, eta)
    failure = 1 - survival
    
    # 신뢰구간 (있는 경우)
    beta_ci = params.get("beta_ci_95")
    eta_ci = params.get("eta_ci_95")
    
    chart_cols = st.columns(2)
    
    with chart_cols[0]:
        st.markdown("**생존곡선 — 시간 경과별 손상 확률**")
        fig1 = go.Figure()
        
        # 신뢰구간 밴드
        if beta_ci and eta_ci:
            f_low = 1 - weibull_survival(t_grid, beta_ci[0], eta_ci[0])
            f_high = 1 - weibull_survival(t_grid, beta_ci[1], eta_ci[1])
            fig1.add_trace(go.Scatter(
                x=t_grid, y=np.maximum(f_low, f_high) * 100,
                mode="lines", line=dict(width=0),
                showlegend=False, hoverinfo="skip"
            ))
            fig1.add_trace(go.Scatter(
                x=t_grid, y=np.minimum(f_low, f_high) * 100,
                mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(83,74,183,0.15)",
                name="95% 신뢰구간", hoverinfo="skip"
            ))
        
        # 메인 곡선
        fig1.add_trace(go.Scatter(
            x=t_grid, y=failure * 100,
            mode="lines",
            line=dict(color="#1F3864", width=3),
            name=f"손상확률 (β={beta:.2f}, η={eta:.2f})",
            hovertemplate="t=%{x:.1f}년 → F(t)=%{y:.1f}%<extra></extra>"
        ))
        
        # 현재 시점 마커
        fig1.add_vline(
            x=current_age,
            line_color="#E24B4A", line_width=2, line_dash="dash",
            annotation_text=f"현재 {current_age}년",
            annotation_position="top right"
        )
        # 목표 손상확률 라인
        fig1.add_hline(
            y=target_prob * 100,
            line_color="#EF9F27", line_width=2, line_dash="dash",
            annotation_text=f"목표 {target_prob:.0%}",
            annotation_position="bottom right"
        )
        
        fig1.update_layout(
            xaxis_title="운영 경과년수 (년)",
            yaxis_title="누적 손상확률 (%)",
            height=380,
            margin=dict(l=50, r=20, t=20, b=50),
            hovermode="x unified",
        )
        st.plotly_chart(fig1, use_container_width=True)
    
    with chart_cols[1]:
        st.markdown("**위험률 함수 — 단위시간당 손상률**")
        hazard = weibull_hazard(t_grid, beta, eta)
        
        # 색상 직접 지정 (hex와 rgba 분리)
        if beta > 1:
            line_color = "#E24B4A"
            fill_color = "rgba(226, 75, 74, 0.15)"
        else:
            line_color = "#1D9E75"
            fill_color = "rgba(29, 158, 117, 0.15)"
        
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=t_grid, y=hazard,
            mode="lines",
            line=dict(color=line_color, width=3),
            fill="tozeroy",
            fillcolor=fill_color,
            hovertemplate="t=%{x:.1f}년 → h(t)=%{y:.4f}/년<extra></extra>"
        ))
        
        fig2.add_vline(
            x=current_age,
            line_color="#E24B4A", line_width=2, line_dash="dash",
            annotation_text=f"현재",
            annotation_position="top right"
        )
        
        fig2.update_layout(
            xaxis_title="운영 경과년수 (년)",
            yaxis_title="위험률 h(t)",
            height=380,
            margin=dict(l=50, r=20, t=20, b=50),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)


# ════════════════════════════════════════════════════════════
# 메인 렌더 함수
# ════════════════════════════════════════════════════════════
def render_weibull_tab():
    """app.py에서 호출하는 메인 함수"""
    st.subheader("🔧 Weibull 열화 모델 — 시설물 보수 예측")
    st.caption(
        "Weibull 분포 최우도추정(MLE)으로 도로 포장의 손상 발생 시점을 학습하고, "
        "신규 사업의 잔여수명·보수시점을 예측합니다."
    )
    
    # 모델 로드
    params, error = load_weibull_params()
    if error:
        st.error(f"❌ {error}")
        with st.expander("📖 학습 방법"):
            st.markdown("""
            1. `pip install scipy numpy matplotlib pandas --break-system-packages`
            2. `python weibull_fit.py` 실행
            3. (선택) 안심구역에서 데이터 반출 후 `pavement_data.csv`로 저장 → 재학습
            4. app.py 재시작
            """)
        return
    
    # 데이터 출처 알림
    render_data_source_badge(params)
    
    # 모델 정보
    st.markdown("---")
    render_model_info(params)
    
    # 모델 해석
    render_interpretation(params)
    
    # 시뮬레이터
    st.markdown("---")
    beta, eta, current_age, target_prob = render_simulator(params)
    
    # 곡선 차트
    st.markdown("---")
    render_curves(params, current_age, target_prob)
    
    # 부가 설명
    st.markdown("---")
    with st.expander("📚 Weibull 모델 해석 가이드"):
        st.markdown("""
        #### 파라미터 해석
        
        - **β (shape, 형상모수)**: 고장 모드 결정
          - β < 1: **초기고장** (시간 갈수록 위험 감소 → 시공 결함)
          - β ≈ 1: **우발고장** (위험률 일정 → 정기점검 충분)
          - β > 1: **마모고장** (시간 갈수록 위험 증가 → 사전 예방보수 필요)
        
        - **η (scale, 척도모수)**: 특성수명
          - 약 63.2% 누적 손상 시점
          - 도로 포장의 경우 일반적으로 8~15년
        
        #### 일반적 가정 vs 실데이터 학습 결과
        **이론 표준 (한국도로공사 가이드)**: β ≈ 2.5, η ≈ 12년 — 마모고장 가정
        
        **공공 실데이터 학습 결과** (포장일반현황 1969~2025, 357건):
        - β ≈ 1.04 → **우발고장 모드**
        - η ≈ 9.9년 → 평균 9~10년 주기
        - **해석**: 한국 고속도로의 대규모 재포장은 시간 의존적 마모보다
          외부 요인(중차량·기상·시공 품질)에 의한 무작위 보수 패턴이 지배적
        
        #### 추가 검증 — 안심구역 데이터
        대전남부순환고속도로 2023 포장탐지 데이터로 추가 학습 시,
        노선별 특수성을 반영한 정밀 모델로 진화 가능합니다.
        공공 데이터(전국 평균) vs 안심구역 데이터(노선 특수) 비교가
        **모델 일반화 능력의 검증 자체**가 됩니다.
        """)


if __name__ == "__main__":
    render_weibull_tab()
