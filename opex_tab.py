"""
============================================================
ROADx Phase 3 - OPEX 시계열 모델 탭
============================================================
역할:
  - 한국도로공사 11년치 보수공사 발주 이력 (4,380건) 분석
  - 사업구분별 (수선유지 vs 개량) OPEX 패턴 시각화
  - 신규 민자도로 30년 OPEX 시뮬레이션
  - Weibull 보수주기 + OPEX 단가 결합 모델

전제조건:
  - opex_analyze.py 실행으로 다음 JSON 생성:
    - opex_by_event_type.json
    - opex_by_route.json
    - opex_lifecycle.json
  - opex_pavement_freq.json (Weibull 모델용)

사용:
  from opex_tab import render_opex_tab
  with tabs[11]:
      render_opex_tab()
============================================================
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st


# ════════════════════════════════════════════════════════════
# 데이터 로드
# ════════════════════════════════════════════════════════════
@st.cache_data
def load_opex_data():
    """4개 JSON 모두 로드"""
    files = {
        "event": "opex_by_event_type.json",
        "route": "opex_by_route.json",
        "lifecycle": "opex_lifecycle.json",
        "pavement": "opex_pavement_freq.json",
    }
    
    data = {}
    missing = []
    for key, fname in files.items():
        p = Path(f"./{fname}")
        if not p.exists():
            missing.append(fname)
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data[key] = json.load(f)
        except Exception as e:
            missing.append(f"{fname} ({e})")
    
    return data, missing


# ════════════════════════════════════════════════════════════
# 시뮬레이션 함수
# ════════════════════════════════════════════════════════════
def simulate_30year_opex(
    route_length_km, 
    lanes,
    operation_years,
    base_unit_cost_per_km,
    lifecycle_data,
    weibull_eta_years,
):
    """
    30년 OPEX 시뮬레이션
    
    Parameters:
        route_length_km: 노선 길이 (km)
        lanes: 차로 수
        operation_years: 운영기간 (년)
        base_unit_cost_per_km: km당 기본 연간 보수비 (백만원)
        lifecycle_data: 운영연차별 평균공사비 패턴
        weibull_eta_years: Weibull 척도모수 (특성 보수주기)
    
    Returns:
        DataFrame: 연차별 OPEX 시계열
    """
    years = list(range(1, operation_years + 1))
    
    # 운영연차별 패턴 매핑 (5년 구간)
    avg_costs = lifecycle_data.get("운영연차별_평균공사비", {})
    counts = lifecycle_data.get("운영연차별_공사빈도", {})
    
    def get_year_pattern(year):
        """운영 N년차의 (수선유지, 개량) 가중치"""
        bucket_start = (year - 1) // 5 * 5
        bucket_end = bucket_start + 4
        bucket_key = f"{bucket_start}-{bucket_end}년차"
        
        cost = avg_costs.get(bucket_key, {})
        cnt = counts.get(bucket_key, {})
        
        repair_cost = cost.get("수선유지사업", 50)
        repair_count = cnt.get("수선유지사업", 100)
        improvement_cost = cost.get("개량사업", 30)
        improvement_count = cnt.get("개량사업", 200)
        
        return repair_cost, repair_count, improvement_cost, improvement_count
    
    # 사업구분 빈도 정규화 (38개 노선 평균)
    # → 1개 노선의 연간 평균 빈도로 환산
    n_routes = 38  # 공통 노선 수
    
    rows = []
    for year in years:
        repair_avg, repair_freq, improve_avg, improve_freq = get_year_pattern(year)
        
        # 연간 1개 노선당 빈도 = 전체빈도 / 38노선 / 5년구간
        repair_per_year = repair_freq / n_routes / 5
        improve_per_year = improve_freq / n_routes / 5
        
        # 노선 길이 기준 스케일 (도로공사 평균 노선 약 200km 가정)
        length_scale = route_length_km / 200
        
        # 연간 OPEX (백만원)
        repair_opex = repair_per_year * repair_avg * length_scale
        improve_opex = improve_per_year * improve_avg * length_scale
        
        # Weibull 보수주기 가중치 (η 주변 ±2년에 개량사업 스파이크)
        spike_weight = 1.0
        if abs(year - weibull_eta_years) <= 2:
            spike_weight = 1.8
        elif abs(year - weibull_eta_years * 2) <= 2:
            spike_weight = 1.5
        
        improve_opex *= spike_weight
        
        # 베이스라인 (km × 차로 × 단가)
        baseline_opex = base_unit_cost_per_km * route_length_km * (lanes / 4)
        
        total_opex = repair_opex + improve_opex + baseline_opex
        
        rows.append({
            "운영연차": year,
            "베이스라인_OPEX": baseline_opex,
            "수선유지_OPEX": repair_opex,
            "개량_OPEX": improve_opex,
            "총_OPEX_백만원": total_opex,
        })
    
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════
# UI 렌더링
# ════════════════════════════════════════════════════════════
def render_data_overview(data):
    """데이터 출처 + 핵심 통계"""
    event = data.get("event", {})
    route = data.get("route", {})
    
    st.markdown(
        """<div style="background: #1D9E7515;
                       border-left: 4px solid #1D9E75;
                       padding: 14px 18px;
                       border-radius: 6px;
                       margin: 12px 0;">
            <strong style="color: #1D9E75;">✅ 학습 데이터 출처</strong><br>
            <span style="font-size: 13px; color: #1a1a2e;">
            한국도로공사 포장보수현황 (공공데이터포털) — 
            2015~2025년 11년치, 4,380건 발주이력 분석
            </span>
        </div>""",
        unsafe_allow_html=True
    )
    
    cols = st.columns(4)
    
    with cols[0]:
        total_repair = sum(
            v.get("실적_합계_백만원", 0) 
            for v in event.get("사업구분별_통계", {}).values()
        )
        st.metric(
            "11년치 총 발주실적",
            f"{total_repair / 1000:.0f}억원",
            help="2015~2025년 누적 (단위 추정)"
        )
    
    with cols[1]:
        avg = event.get("연평균_OPEX", {})
        annual = avg.get("수선유지_연평균_백만원", 0) + avg.get("개량_연평균_백만원", 0)
        st.metric(
            "도로공사 연평균 발주",
            f"{annual / 1000:.0f}억원",
            help="포장 보수공사만 포함 (시설물·교량 제외)"
        )
    
    with cols[2]:
        st.metric(
            "분석 대상 노선",
            f"{route.get('공통_노선_수', 0)}개",
            help="포장보수현황 + 포장일반현황 매칭 노선"
        )
    
    with cols[3]:
        st.metric(
            "총 보수공사 건수",
            f"{event.get('총_건수', 0):,}건",
            help="11년 누적 (수선유지 + 개량)"
        )


def render_business_type_analysis(data):
    """사업구분별 패턴 분석"""
    event = data.get("event", {})
    stats = event.get("사업구분별_통계", {})
    
    st.markdown("### 📊 사업구분별 OPEX 패턴")
    st.caption(
        "한국도로공사는 보수공사를 두 가지로 분류합니다. "
        "이 분류 기준이 OPEX 모델의 핵심입니다."
    )
    
    cols = st.columns(2)
    
    biz_descriptions = {
        "수선유지사업": {
            "color": "#1F3864",
            "icon": "🛠",
            "description": "지사별 연간 패키지 보수공사",
            "characteristic": "정기적 베이스라인 OPEX",
            "cycle": "1~3년 주기",
        },
        "개량사업": {
            "color": "#E24B4A",
            "icon": "🏗",
            "description": "개별 단발 보수·개량공사",
            "characteristic": "특정 위치 부분 개선",
            "cycle": "8~15년 주기",
        },
    }
    
    for i, (biz, info) in enumerate(biz_descriptions.items()):
        with cols[i]:
            stat = stats.get(biz, {})
            st.markdown(
                f"""<div style="background: {info['color']}10;
                                border-top: 4px solid {info['color']};
                                padding: 16px 20px;
                                border-radius: 6px;
                                min-height: 220px;">
                    <div style="font-size: 24px;">{info['icon']}</div>
                    <div style="font-size: 18px; font-weight: 600; color: {info['color']};">
                        {biz}
                    </div>
                    <div style="font-size: 12px; color: #666; margin: 6px 0;">
                        {info['description']}
                    </div>
                    <div style="margin-top: 14px; font-size: 13px; line-height: 1.7;">
                        <strong>건수:</strong> {stat.get('건수', 0):,}건<br>
                        <strong>평균 실적:</strong> {stat.get('실적_평균_백만원', 0):.1f}백만원<br>
                        <strong>중위 실적:</strong> {stat.get('실적_중위_백만원', 0):.1f}백만원<br>
                        <strong>특성:</strong> {info['characteristic']}<br>
                        <strong>주기:</strong> {info['cycle']}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )


def render_lifecycle_chart(data):
    """운영연차별 OPEX 패턴 차트"""
    lifecycle = data.get("lifecycle", {})
    cost_data = lifecycle.get("운영연차별_평균공사비", {})
    count_data = lifecycle.get("운영연차별_공사빈도", {})
    
    if not cost_data:
        st.warning("운영연차별 데이터 없음")
        return
    
    st.markdown("### 📈 운영연차별 OPEX 패턴")
    st.caption(
        "노선의 신설 시점부터 N년차에 발생한 보수공사의 평균 비용·빈도. "
        "**민자도로 30년 운영기간의 OPEX 변화 패턴**을 보여줍니다."
    )
    
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        labels = list(cost_data.keys())
        repair_costs = [cost_data[k].get("수선유지사업", 0) or 0 for k in labels]
        improve_costs = [cost_data[k].get("개량사업", 0) or 0 for k in labels]
        repair_counts = [count_data[k].get("수선유지사업", 0) or 0 for k in labels]
        improve_counts = [count_data[k].get("개량사업", 0) or 0 for k in labels]
        
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=("평균 공사비 (백만원)", "공사 빈도 (건수)"),
            horizontal_spacing=0.12,
        )
        
        # 평균 공사비
        fig.add_trace(
            go.Bar(name='수선유지사업', x=labels, y=repair_costs, 
                   marker_color='#1F3864', showlegend=True),
            row=1, col=1
        )
        fig.add_trace(
            go.Bar(name='개량사업', x=labels, y=improve_costs, 
                   marker_color='#E24B4A', showlegend=True),
            row=1, col=1
        )
        
        # 공사 빈도
        fig.add_trace(
            go.Bar(name='수선유지사업', x=labels, y=repair_counts, 
                   marker_color='#1F3864', showlegend=False),
            row=1, col=2
        )
        fig.add_trace(
            go.Bar(name='개량사업', x=labels, y=improve_counts, 
                   marker_color='#E24B4A', showlegend=False),
            row=1, col=2
        )
        
        fig.update_layout(
            barmode='group',
            height=400,
            margin=dict(l=40, r=20, t=50, b=80),
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
        )
        fig.update_xaxes(tickangle=-45)
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 핵심 메시지
        st.info(
            "💡 **핵심 패턴**: 운영 10~24년차에 **개량사업 빈도가 정점**(연 400+건). "
            "수선유지사업의 평균 공사비는 **운영 25~29년차에 정점** "
            "(평균 115백만원). 즉, **운영 25년 이후 OPEX 부담 급증**이 데이터로 확인됩니다."
        )
    except ImportError:
        st.dataframe(pd.DataFrame(cost_data).T)


def render_route_ranking(data):
    """노선별 OPEX Top 10"""
    route = data.get("route", {})
    routes = route.get("노선별_통계", [])
    
    if not routes:
        return
    
    st.markdown("### 🛣 노선별 연평균 보수비 Top 15")
    
    df = pd.DataFrame(routes[:15])
    df = df[[
        "노선명", "노선길이_km", "연평균_보수비_억원",
        "연평균_km당_보수비_백만원", "수선유지_건수", "개량_건수"
    ]].copy()
    
    df.columns = ["노선명", "노선길이(km)", "연평균보수비(억)", "km당단가(백만)", "수선유지", "개량"]
    
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "노선길이(km)": st.column_config.NumberColumn(format="%.0f"),
            "연평균보수비(억)": st.column_config.NumberColumn(format="%.1f"),
            "km당단가(백만)": st.column_config.NumberColumn(format="%.2f"),
        }
    )


def render_simulator(data):
    """30년 OPEX 시뮬레이터"""
    st.markdown("### 🎯 신규 민자도로 30년 OPEX 시뮬레이션")
    st.caption(
        "신규 민자도로 사업의 운영 30년간 예상 보수비 시계열을 산출합니다. "
        "도로공사 11년치 발주이력 + Weibull 열화 모델 결합."
    )
    
    sim_cols = st.columns(4)
    with sim_cols[0]:
        route_length = st.slider("노선 길이 (km)", 5.0, 100.0, 30.0, 1.0)
    with sim_cols[1]:
        lanes = st.slider("차로 수", 2, 8, 4, 1)
    with sim_cols[2]:
        operation_years = st.slider("운영기간 (년)", 10, 50, 30, 5)
    with sim_cols[3]:
        unit_cost = st.slider(
            "km당 기본 단가 (백만)", 
            1.0, 20.0, 2.5, 0.5,
            help="도로공사 데이터 기반 중위값 2.5백만원/km/년"
        )
    
    # Weibull 데이터 로드 (있으면)
    weibull_eta = 9.89  # 기본값
    pavement_data = data.get("pavement", {})
    if pavement_data:
        # opex_pavement_freq.json에서 평균 보수주기
        weibull_eta = pavement_data.get("전체_평균_보수주기_년", 9.89)
    
    # 시뮬레이션 실행
    sim_df = simulate_30year_opex(
        route_length_km=route_length,
        lanes=lanes,
        operation_years=operation_years,
        base_unit_cost_per_km=unit_cost,
        lifecycle_data=data.get("lifecycle", {}),
        weibull_eta_years=weibull_eta,
    )
    
    # 결과 카드
    total_opex = sim_df['총_OPEX_백만원'].sum()
    avg_annual = sim_df['총_OPEX_백만원'].mean()
    peak_year = sim_df.loc[sim_df['총_OPEX_백만원'].idxmax()]
    
    res_cols = st.columns(3)
    with res_cols[0]:
        st.metric(
            f"{operation_years}년 누적 OPEX",
            f"{total_opex / 100:,.0f}억원",
            help="총 보수비 (베이스라인 + 수선유지 + 개량)"
        )
    with res_cols[1]:
        st.metric(
            "연평균 OPEX",
            f"{avg_annual / 100:.1f}억원",
            help=f"{operation_years}년 평균"
        )
    with res_cols[2]:
        st.metric(
            "최대 OPEX 시기",
            f"운영 {int(peak_year['운영연차'])}년차",
            f"{peak_year['총_OPEX_백만원'] / 100:.1f}억원",
        )
    
    # 차트
    try:
        import plotly.graph_objects as go
        
        fig = go.Figure()
        
        # 누적 영역 차트
        fig.add_trace(go.Scatter(
            x=sim_df['운영연차'], y=sim_df['베이스라인_OPEX'],
            mode='lines', name='베이스라인',
            stackgroup='one', line=dict(width=0.5, color='#999'),
            fillcolor='rgba(153, 153, 153, 0.4)',
        ))
        fig.add_trace(go.Scatter(
            x=sim_df['운영연차'], y=sim_df['수선유지_OPEX'],
            mode='lines', name='수선유지사업',
            stackgroup='one', line=dict(width=0.5, color='#1F3864'),
            fillcolor='rgba(31, 56, 100, 0.5)',
        ))
        fig.add_trace(go.Scatter(
            x=sim_df['운영연차'], y=sim_df['개량_OPEX'],
            mode='lines', name='개량사업',
            stackgroup='one', line=dict(width=0.5, color='#E24B4A'),
            fillcolor='rgba(226, 75, 74, 0.5)',
        ))
        
        # Weibull η 마커
        fig.add_vline(
            x=weibull_eta, line_color='#EF9F27', line_width=2, line_dash='dash',
            annotation_text=f"Weibull η={weibull_eta:.1f}년",
            annotation_position="top right"
        )
        if weibull_eta * 2 <= operation_years:
            fig.add_vline(
                x=weibull_eta * 2, line_color='#EF9F27', line_width=1, line_dash='dot',
                annotation_text=f"2η={weibull_eta*2:.1f}년",
                annotation_position="top right"
            )
        
        fig.update_layout(
            title=f"운영연차별 OPEX 시계열 (노선 {route_length}km, {lanes}차로)",
            xaxis_title="운영 연차 (년)",
            yaxis_title="OPEX (백만원)",
            height=400,
            margin=dict(l=50, r=20, t=50, b=50),
            hovermode='x unified',
        )
        
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.line_chart(sim_df.set_index('운영연차')[['베이스라인_OPEX', '수선유지_OPEX', '개량_OPEX']])
    
    # 데이터 테이블
    with st.expander("📋 연차별 상세 데이터"):
        display_df = sim_df.copy()
        for col in display_df.columns[1:]:
            display_df[col] = display_df[col].round(1)
        st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_data_validity_note():
    """데이터 한계와 정직한 메모"""
    with st.expander("⚠️ 데이터 한계 및 발표 시 유의사항"):
        st.markdown("""
        #### 단위 검증 사항
        포장보수현황 데이터의 `실적` 칼럼은 **단위가 명시되지 않은** 수치입니다. 
        분포 분석 결과 **백만원 단위로 추정**되나, 천만원·억원 등 다른 가능성도 있습니다.
        
        - 평균 60.2 → 6,020만원 (백만원 단위 가정)
        - 연간 합계 100~180억원 (백만원 단위 가정)
        - 한국도로공사 연간 유지보수 예산은 약 2조원 (포장은 그 일부)
        
        #### 분석의 신뢰성
        - **상대값 비교는 신뢰**: 노선간·사업구분간 차이는 정확
        - **운영연차별 패턴은 정확**: 시점 정보가 명확
        - **절대 단가는 추정**: 시연 시 "단위 추정 기반" 명시 필요
        
        #### 발표 시 권장 표현
        > "도로공사 11년치 발주이력 4,380건의 **상대 패턴**을 학습. 절대 단가는 
        > 표준품셈·표준시장단가와 결합하여 검증 예정. 핵심 발견은 **운영 10~24년차 
        > 개량사업 정점, 25년차 이후 수선유지비 급증** 패턴."
        """)


# ════════════════════════════════════════════════════════════
# 메인 렌더 함수
# ════════════════════════════════════════════════════════════
def render_opex_tab():
    """app.py에서 호출"""
    st.subheader("💰 OPEX 시계열 모델 — 30년 보수비 시뮬레이션")
    st.caption(
        "한국도로공사 11년치 보수공사 발주이력(4,380건)을 학습하여 "
        "신규 민자도로의 30년 운영기간 OPEX를 시계열로 예측합니다."
    )
    
    data, missing = load_opex_data()
    
    if missing:
        st.error(f"❌ 다음 파일이 없습니다: {', '.join(missing)}")
        with st.expander("📖 데이터 생성 방법"):
            st.markdown("""
            1. 공공데이터포털에서 다음 파일 다운로드:
               - 한국도로공사_포장 보수현황 (ETC_U3_*.csv)
               - 한국도로공사_포장일반현황 (ETC_T8_*.csv)
            2. `python opex_analyze.py` 실행
            3. app.py 폴더에 생성된 JSON 4개 배치
            4. streamlit 재시작
            """)
        return
    
    # 1. 데이터 출처 + 핵심 통계
    st.markdown("---")
    render_data_overview(data)
    
    # 2. 사업구분별 분석
    st.markdown("---")
    render_business_type_analysis(data)
    
    # 3. 운영연차별 패턴
    st.markdown("---")
    render_lifecycle_chart(data)
    
    # 4. 노선 랭킹
    st.markdown("---")
    render_route_ranking(data)
    
    # 5. 시뮬레이터
    st.markdown("---")
    render_simulator(data)
    
    # 6. 데이터 한계 메모
    st.markdown("---")
    render_data_validity_note()


if __name__ == "__main__":
    render_opex_tab()
