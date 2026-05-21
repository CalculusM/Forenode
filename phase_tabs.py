"""
============================================================
Forenode — 시점 탭 모듈 (phase_tabs.py)
============================================================
역할:
  민자도로 사업의 라이프사이클 4단계 시점별 입력·분석 모듈

시점 1: 사전 검토 (PFS·VfM)  — 통계 모드, BIM 없음, ±20%
시점 2: 시공·자금조달 (LTA·STA) — BIM 모드 placeholder, ±5%
시점 3: 운영 (CEPHIS 평가)    — 실적 비교
시점 4: 재구조화 (실시협약변경) — 잔여기간 시뮬

호출 흐름:
  app.py → render_phase_xxx(phase_context) → 메인 영역에 렌더

phase_context dict keys:
  business_type, road_length, lanes, terrain, bridge_ratio, tunnel_ratio,
  total_capex_user, operation_years, construction_years, annual_revenue,
  mrg_ratio, restructuring_year, opex_estimation, capex_reference, metrics, wacc
============================================================
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go


# ════════════════════════════════════════════════════════════
# 공통 — 모드 배지
# ════════════════════════════════════════════════════════════
def _render_mode_badge(mode: str, accuracy: str, description: str):
    palette = {
        "통계": ("#EF9F27", "#FFF8E1", "📊"),
        "BIM": ("#1D9E75", "#E8F5E9", "🏗️"),
        "실적": ("#1F3864", "#E3F2FD", "📈"),
        "시뮬": ("#534AB7", "#F3E5F5", "🔄"),
    }
    color, bg, icon = palette.get(mode, ("#888", "#F5F5F5", "•"))
    st.markdown(
        f"""<div style="background:{bg};border-left:4px solid {color};
            padding:10px 14px;border-radius:4px;margin:8px 0 16px 0;">
            <strong style="color:{color};">{icon} {mode} 모드</strong>
            &nbsp;·&nbsp;<span style="font-size:13px;">정확도 {accuracy}</span><br>
            <span style="font-size:12px;color:#555;">{description}</span>
        </div>""",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════
# 시점 1: 사전 검토 (PFS·VfM) — 통계 모드 본격 구현
# ════════════════════════════════════════════════════════════
def render_phase_pretest(ctx: dict):
    _render_mode_badge(
        mode="통계",
        accuracy="±20%",
        description=(
            "BIM 없는 사전 검토 단계. 한국 PPP 30년 데이터(13개 SPC + 도로공사 11년치 4,380건)를 "
            "학습한 통계 모델로 CAPEX·OPEX·수익성을 추정합니다."
        ),
    )

    st.markdown("#### ⏱ 사전 검토 단계 — 민자 적격성 조사")
    st.caption(
        "**활용 주체**: KDI PIMAC · 주무관청 · 자문사 | "
        "**분석 업무**: PFS(예비타당성), VfM(민자 vs 재정 비교), 사업제안 평가"
    )

    st.markdown("---")

    # A. 노선 특성
    st.markdown("##### 📋 입력 노선 특성")
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("연장", f"{ctx['road_length']} km")
    col_b.metric("차로", f"{ctx['lanes']} 차로")
    col_c.metric("지형", ctx['terrain'])
    col_d.metric("교량·터널", f"{ctx['bridge_ratio']*100:.0f}% · {ctx['tunnel_ratio']*100:.0f}%")

    st.markdown("")

    # B. CAPEX 비교
    st.markdown("##### 💰 CAPEX 추정 비교")
    capex_ref = ctx['capex_reference']
    user_capex = ctx['total_capex_user']

    col_l, col_m, col_r = st.columns(3)
    with col_l:
        st.metric("사용자 입력", f"{user_capex:,} 억",
                  help="사업계획서 또는 정부 고시 기준값")
    with col_m:
        st.metric("회귀 추정 (중앙값)", f"{capex_ref['capex_estimate_억']:,} 억",
                  delta=f"{(capex_ref['capex_estimate_억'] - user_capex):+,} 억 vs 사용자",
                  help="노선 특성 기반 통계 추정")
    with col_r:
        in_range = capex_ref['capex_low_억'] <= user_capex <= capex_ref['capex_high_억']
        status = "✅ 적정 범위" if in_range else "⚠️ 범위 밖"
        st.metric("회귀 신뢰구간 (±20%)",
                  f"{capex_ref['capex_low_억']:,} ~ {capex_ref['capex_high_억']:,}",
                  delta=status,
                  delta_color="normal" if in_range else "inverse")

    with st.expander("📐 회귀 산출 근거"):
        st.code(capex_ref['explanation'])
        st.caption(
            f"km당 단가: **{capex_ref['per_km_억']:,} 억/km** | "
            f"적용 보정: 차로 수, 지형, 교량·터널 비율"
        )

    st.markdown("")

    # C. OPEX 시계열
    st.markdown("##### ⚙️ OPEX 자동 산출 시계열")
    opex_est = ctx['opex_estimation']

    col_o1, col_o2, col_o3 = st.columns(3)
    col_o1.metric("평균 OPEX 비율", f"{opex_est['opex_ratio_avg']*100:.1f}%",
                  help="운영기간 전체 평균")
    col_o2.metric("1년차 OPEX", f"{opex_est['opex_series_억'][0]:.0f} 억")
    col_o3.metric(f"정점 ({opex_est['peak_year']}년차)",
                  f"{opex_est['peak_amount_억']:.0f} 억")

    opex_series = opex_est['opex_series_억']
    years = list(range(1, len(opex_series) + 1))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=opex_series,
        mode='lines+markers',
        name='OPEX',
        line=dict(color='#1F3864', width=2),
        fill='tozeroy',
        fillcolor='rgba(31,56,100,0.1)',
    ))
    fig.add_vline(
        x=opex_est['peak_year'],
        line_dash="dash", line_color="#EF9F27",
        annotation_text=f"정점 {opex_est['peak_year']}년차"
    )
    fig.update_layout(
        title="운영기간 OPEX 시계열 (학습 데이터 기반 자동 산출)",
        xaxis_title="운영 연차",
        yaxis_title="OPEX (억원)",
        height=320,
        margin=dict(t=40, b=40, l=40, r=20),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("📐 OPEX 산출 근거"):
        st.code(opex_est['explanation'])
        st.caption(
            "학습 데이터 패턴: 5~9년차 기준(1.0배) → 10~24년차 개량 정점 → "
            "25~29년차 수선유지 급증 → 운영기간 후반 OPEX 점진 증가"
        )

    st.markdown("")

    # D. VfM 판단
    st.markdown("##### ⚖️ VfM 적격성 판단")

    metrics = ctx['metrics']
    npv = metrics['npv']
    irr = metrics['nominal_irr']
    dscr_min = metrics['dscr_min']
    bc = metrics['bc_ratio']
    psc_ratio = bc

    if psc_ratio >= 1.3 and dscr_min >= 1.20:
        judgment = "민자 매우 적합"
        color = "#1D9E75"
        recommendation = (
            "정부 보전금 없이도 민간 사업주가 수익을 낼 수 있는 구조입니다. "
            "BTO 또는 BTO-rs 사업유형 검토 권장."
        )
    elif psc_ratio >= 1.0 and dscr_min >= 1.05:
        judgment = "민자 적합"
        color = "#1F3864"
        recommendation = (
            "현재 MRG·자기자본비율 등 조건으로 사업 추진 가능. "
            "민감도 분석(Tornado 탭)에서 핵심 리스크 변수를 확인하세요."
        )
    elif psc_ratio >= 0.85:
        judgment = "경계선 — 재구조화 검토"
        color = "#EF9F27"
        recommendation = (
            "사업 조건 보완 필요. MRG 보장률 상향, 운영기간 연장, "
            "또는 BTO-ann 전환 등 시나리오 비교를 권합니다 (재구조화 탭 참조)."
        )
    else:
        judgment = "민자 부적합"
        color = "#D45F5F"
        recommendation = (
            "민자 추진 시 수익성 확보가 어렵습니다. "
            "재정사업 전환 또는 사업계획 전면 재검토를 권합니다."
        )

    st.markdown(
        f"""<div style="background:#F8F9FA;border-left:5px solid {color};
            padding:14px 18px;border-radius:6px;margin:8px 0;">
            <div style="font-size:18px;font-weight:bold;color:{color};">판단: {judgment}</div>
            <div style="margin-top:8px;font-size:13px;color:#444;">{recommendation}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    col_v1, col_v2, col_v3, col_v4 = st.columns(4)
    col_v1.metric("PSC ratio (B/C)", f"{psc_ratio:.2f}",
                  delta="≥1.0 적합" if psc_ratio >= 1.0 else "<1.0 부족",
                  delta_color="normal" if psc_ratio >= 1.0 else "inverse")
    col_v2.metric("NPV", f"{npv:,.0f} 억",
                  delta="흑자" if npv >= 0 else "적자",
                  delta_color="normal" if npv >= 0 else "inverse")
    col_v3.metric("IRR (명목)", f"{irr*100:.1f}%",
                  delta=f"WACC {ctx['wacc']*100:.1f}% 대비",
                  delta_color="normal" if irr >= ctx['wacc'] else "inverse")
    col_v4.metric("DSCR (최소)", f"{dscr_min:.2f}",
                  delta="≥1.2 양호" if dscr_min >= 1.2 else ("≥1.0 경계" if dscr_min >= 1.0 else "위험"),
                  delta_color="normal" if dscr_min >= 1.2 else "inverse")

    st.markdown("")
    st.caption(
        "💡 **사전 검토 다음 단계** — 사업이 고시되어 설계 BIM이 생성되면 "
        "**🏗 시공·자금조달 탭**에서 BIM 모드로 ±5% 정확도 분석으로 전환됩니다."
    )


# ════════════════════════════════════════════════════════════
# 시점 2: 시공·자금조달 — 통계 모드 본격 구현 (LTA·STA 양쪽)
# ════════════════════════════════════════════════════════════
def render_phase_construction(ctx: dict):
    """
    시점 2: 시공·자금조달 단계.
    
    구성:
        A. LTA(대주단) 관점 — 자금조달 구조·이자 자본화·시공 리스크
        B. STA(사업주) 관점 — CI/FI/SI 자본 구성·공기 지연·공사비 변동 위험
        C. 통합 KPI — 시공기간 자금 흐름·시점 연결 메시지
    
    데이터 출처:
        - 자금구조: phase_context의 senior_ratio/rate, sub_rate
        - CAPEX 분배: 시점 1의 회귀 추정
        - 정부 보전: phase_context의 mcc_ratio (2024.10 정부 활성화 방안)
    """
    _render_mode_badge(
        mode="통계",
        accuracy="±20%",
        description=(
            "사업 고시 이후 시공·자금조달 단계용. 대주단(LTA)·사업주(STA) 양쪽 관점에서 "
            "자금조달 구조, 시공기간 자금 인출 일정, 공기 지연·공사비 변동 위험을 분석합니다. "
            "BIM(IFC) 통합 모드는 Stage 2(7~8월)에 ±5% 정확도로 출시 예정."
        ),
    )

    st.markdown("#### 🏗 시공·자금조달 단계 — Technical Due Diligence")
    st.caption(
        "**활용 주체**: 대주단(LTA) · 사업주(STA) · EPC 시공사 · 자문사 | "
        "**분석 업무**: 자금조달 구조 검증, 시공 리스크 평가, 공기·공사비 위험 시뮬레이션"
    )

    # 기본 변수 추출
    total_capex = ctx['total_capex_user']
    construction_years = ctx['construction_years']
    operation_years = ctx['operation_years']
    business_type = ctx['business_type']
    metrics = ctx['metrics']
    capex_ref = ctx['capex_reference']
    
    # 자금구조 (v2.1 신규 — phase_context에서 추출)
    senior_ratio = ctx.get('senior_ratio', 0.7)
    senior_rate = ctx.get('senior_rate', 0.04)
    sub_rate = ctx.get('sub_rate', 0.065)
    # equity_ratio는 base_params에 없을 수 있으므로 metrics에서 역산하거나 기본값
    # 호환성: ctx에 직접 추가 안 했으면 BIZ 기본값으로 추정
    equity_ratio = {"BTO": 0.25, "BTO-rs": 0.20, "BTO-ann": 0.15, "BTL": 0.10, "BTO+BTL": 0.18}.get(business_type, 0.20)
    
    # 자금 규모 (절대값)
    equity_amount = total_capex * equity_ratio
    debt_amount = total_capex - equity_amount
    senior_amount = debt_amount * senior_ratio
    sub_amount = debt_amount * (1 - senior_ratio)
    
    # LTA·STA 공통 변수 (각 섹션에서 사용 — 스코프 보장)
    annual_rev = ctx['annual_revenue']
    avg_opex_ratio = ctx['opex_estimation']['opex_ratio_avg']
    wacc = ctx['wacc']
    avg_debt_rate = senior_ratio * senior_rate + (1 - senior_ratio) * sub_rate
    
    st.markdown("---")
    
    # ════════════════════════════════════════════════════════════
    # 시점 2 핵심 KPI — 시공기간 자금 흐름
    # ════════════════════════════════════════════════════════════
    st.markdown("##### 📊 시공기간 자금 흐름 핵심 KPI")
    
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    col_k1.metric(
        "총사업비 (CAPEX)",
        f"{total_capex:,} 억",
        help=f"회귀 추정: {capex_ref['capex_estimate_억']:,}억 ±{capex_ref['capex_high_억']-capex_ref['capex_estimate_억']:,}억",
    )
    col_k2.metric(
        "자기자본 (Equity)",
        f"{equity_amount:,.0f} 억",
        delta=f"{equity_ratio*100:.0f}%",
        help="사업주(CI·FI·SI) 출자금",
    )
    col_k3.metric(
        "선순위 대출",
        f"{senior_amount:,.0f} 억",
        delta=f"{senior_rate*100:.2f}%",
        help=f"타인자본 중 {senior_ratio*100:.0f}%, 우선 상환",
    )
    col_k4.metric(
        "후순위 대출",
        f"{sub_amount:,.0f} 억",
        delta=f"{sub_rate*100:.2f}%",
        help=f"타인자본 중 {(1-senior_ratio)*100:.0f}%, 금리 차등",
    )

    st.markdown("---")

    # ════════════════════════════════════════════════════════════
    # 화면 분기: LTA / STA 선택
    # ════════════════════════════════════════════════════════════
    perspective = st.radio(
        "🎯 분석 관점 선택",
        options=["📐 LTA (대주단·Lender)", "🏢 STA (사업주·Sponsor)", "🔁 통합 비교"],
        horizontal=True,
        key="phase2_perspective",
        help="동일한 사업을 LTA·STA 어느 관점에서 분석할지 선택. 보고서·협상 자료가 관점에 따라 달라집니다."
    )

    st.markdown("")

    # ════════════════════════════════════════════════════════════
    # A. LTA (대주단) 관점
    # ════════════════════════════════════════════════════════════
    if "LTA" in perspective or "통합" in perspective:
        st.markdown("##### 📐 LTA (Lender's Technical Advisor) — 대주단 관점")
        st.caption(
            "대주단은 **부도 위험·DSCR 안정성·시공 일정 준수**가 핵심 관심사. "
            "선순위 대출 회수 가능성을 정량 평가합니다."
        )
        
        # 시공기간 S-curve 자금 인출 일정
        st.markdown("**📈 시공기간 자금 인출 일정 (S-curve)**")
        
        years_construction = np.arange(0, construction_years + 1)
        s_curve_progress = np.zeros(construction_years + 1)
        capex_draw = np.zeros(construction_years + 1)
        for y in range(1, construction_years + 1):
            t = y / construction_years
            # S-curve: 3t² - 2t³ (smoothstep)
            cum_progress = 3 * t**2 - 2 * t**3
            s_curve_progress[y] = cum_progress
            t_prev = (y - 1) / construction_years
            cum_prev = 3 * t_prev**2 - 2 * t_prev**3
            capex_draw[y] = total_capex * (cum_progress - cum_prev)
        
        equity_draw = capex_draw * equity_ratio
        senior_draw = capex_draw * (1 - equity_ratio) * senior_ratio
        sub_draw = capex_draw * (1 - equity_ratio) * (1 - senior_ratio)
        
        fig_scurve = go.Figure()
        fig_scurve.add_trace(go.Bar(
            x=years_construction[1:], y=equity_draw[1:],
            name='자기자본', marker_color='#1F3864',
        ))
        fig_scurve.add_trace(go.Bar(
            x=years_construction[1:], y=senior_draw[1:],
            name='선순위 대출', marker_color='#4A6FA5',
        ))
        fig_scurve.add_trace(go.Bar(
            x=years_construction[1:], y=sub_draw[1:],
            name='후순위 대출', marker_color='#EF9F27',
        ))
        fig_scurve.update_layout(
            title="시공기간 연도별 자금 인출 (S-curve 분배)",
            xaxis_title="시공 연차",
            yaxis_title="자금 인출액 (억원)",
            barmode='stack',
            height=320,
            margin=dict(t=40, b=40, l=40, r=20),
            legend=dict(orientation='h', y=-0.2),
        )
        st.plotly_chart(fig_scurve, use_container_width=True)
        
        # 건설기간 이자 자본화 (Interest During Construction, IDC)
        idc_total = 0
        for y in range(1, construction_years + 1):
            cum_debt_draw = sum(senior_draw[1:y+1] + sub_draw[1:y+1])
            # 평균 부채 잔액에 가중평균 금리 적용
            avg_rate = senior_ratio * senior_rate + (1 - senior_ratio) * sub_rate
            idc_total += cum_debt_draw * avg_rate * 0.5  # 연중 평균 가정
        
        col_idc1, col_idc2, col_idc3 = st.columns(3)
        col_idc1.metric(
            "건설기간 총 인출액",
            f"{capex_draw.sum():,.0f} 억",
            help="S-curve 분배 합계 = 총 CAPEX",
        )
        col_idc2.metric(
            "건설기간 이자 자본화 (IDC)",
            f"{idc_total:,.0f} 억",
            delta=f"{idc_total/total_capex*100:.1f}% of CAPEX",
            help="시공기간 중 발생하는 대출 이자. CAPEX에 자본화됨",
        )
        col_idc3.metric(
            "운영 개시 시점 부채 잔액",
            f"{debt_amount + idc_total:,.0f} 억",
            help="시공 완료 시점에 운영 단계로 이월되는 총 부채",
        )
        
        st.markdown("")
        
        # 운영기간 DSCR 시계열 (대주단 핵심 지표)
        st.markdown("**📉 운영기간 DSCR 시계열 (대주단 회수 안정성)**")
        st.caption(
            "DSCR(Debt Service Coverage Ratio) = (영업현금흐름) / (원리금 상환). "
            "대주단 표준 기준 **DSCR ≥ 1.2** (1.2 미만 시 부도 위험 신호)."
        )
        
        # ctx에서 이미 계산된 DSCR 데이터 활용 — metrics에 min·avg만 있으므로 시계열은 재계산
        # 단순화: 평균 ROE·매출 성장 기반 DSCR 시계열 추정
        dscr_series = []
        annual_rev = ctx['annual_revenue']
        avg_opex_ratio = ctx['opex_estimation']['opex_ratio_avg']
        annual_principal = debt_amount / operation_years if operation_years > 0 else 0
        debt_balance = debt_amount + idc_total  # IDC 포함
        
        avg_debt_rate = senior_ratio * senior_rate + (1 - senior_ratio) * sub_rate
        
        for op_year in range(1, operation_years + 1):
            rev = annual_rev * (1 + 0.025) ** (op_year - 1)
            opex_y = rev * avg_opex_ratio
            interest_y = debt_balance * avg_debt_rate
            principal_y = min(annual_principal, debt_balance)
            ds = interest_y + principal_y
            cf = rev - opex_y
            dscr_y = cf / ds if ds > 0 else 0
            dscr_series.append(dscr_y)
            debt_balance = max(0, debt_balance - principal_y)
        
        dscr_arr = np.array(dscr_series)
        
        fig_dscr = go.Figure()
        fig_dscr.add_trace(go.Scatter(
            x=list(range(1, operation_years + 1)),
            y=dscr_arr,
            mode='lines+markers',
            name='DSCR',
            line=dict(color='#1F3864', width=2.5),
            marker=dict(size=6),
        ))
        # 임계선 1.2
        fig_dscr.add_hline(
            y=1.2, line_dash='dash', line_color='#D32F2F',
            annotation_text="대주단 기준 1.2", annotation_position='right',
        )
        # 임계선 1.0
        fig_dscr.add_hline(
            y=1.0, line_dash='dot', line_color='#888',
            annotation_text="부도 임계 1.0", annotation_position='right',
        )
        fig_dscr.update_layout(
            title="운영기간 DSCR 시계열 (대주단 회수 안정성)",
            xaxis_title="운영 연차",
            yaxis_title="DSCR",
            height=320,
            margin=dict(t=40, b=40, l=40, r=80),
            showlegend=False,
        )
        st.plotly_chart(fig_dscr, use_container_width=True)
        
        # 시공 리스크 카드 (대주단 의사결정 자료)
        st.markdown("**⚠️ 시공 리스크 평가 (대주단 의사결정 자료)**")
        
        dscr_min_lta = float(np.min(dscr_arr)) if len(dscr_arr) > 0 else 0
        years_below_12 = int(np.sum(dscr_arr < 1.2)) if len(dscr_arr) > 0 else 0
        years_below_10 = int(np.sum(dscr_arr < 1.0)) if len(dscr_arr) > 0 else 0
        
        if dscr_min_lta >= 1.3:
            risk_level = "🟢 SAFE"
            risk_color = "#1B5E20"
            risk_bg = "#E8F5E9"
            risk_msg = "DSCR 안정. 대주단 금리 협상 시 유리한 위치."
        elif dscr_min_lta >= 1.2:
            risk_level = "🟡 WARNING"
            risk_color = "#E65100"
            risk_bg = "#FFF3E0"
            risk_msg = f"DSCR 임계선 근접. 운영 {years_below_12}년차에 1.2 미달. 자기자본 확충 또는 MRG 활용 검토."
        elif dscr_min_lta >= 1.0:
            risk_level = "🟠 CRITICAL"
            risk_color = "#C62828"
            risk_bg = "#FFEBEE"
            risk_msg = f"부도 위험 시그널. {years_below_12}년 1.2 미달, 부도 임계 1.0 근접. 사업구조 재검토 필요."
        else:
            risk_level = "🔴 DEFAULT RISK"
            risk_color = "#B71C1C"
            risk_bg = "#FFCDD2"
            risk_msg = f"부도 위험 매우 높음. {years_below_10}년 1.0 미달. 본 구조로는 자금조달 불가."
        
        st.markdown(
            f"""<div style="background:{risk_bg};border-left:5px solid {risk_color};
                padding:14px 18px;border-radius:6px;margin:8px 0;">
                <div style="font-weight:bold;color:{risk_color};font-size:16px;">
                    {risk_level} — 최소 DSCR {dscr_min_lta:.2f}
                </div>
                <div style="margin-top:6px;font-size:13px;color:#333;">
                    {risk_msg}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

        if "통합" in perspective:
            st.markdown("---")

    # ════════════════════════════════════════════════════════════
    # B. STA (사업주) 관점
    # ════════════════════════════════════════════════════════════
    if "STA" in perspective or "통합" in perspective:
        st.markdown("##### 🏢 STA (Sponsor's Technical Advisor) — 사업주 관점")
        st.caption(
            "사업주는 **자기자본 회수율(ROE)·공기 준수·공사비 통제**가 핵심 관심사. "
            "CI/FI/SI 자본 구성과 시공 위험 분담을 정량 평가합니다."
        )
        
        # CI/FI/SI 자기자본 구성 (보완 9 흡수)
        st.markdown("**💼 자기자본 구성 (CI · FI · SI)**")
        st.caption(
            "민자사업 자기자본은 **CI(건설투자자), FI(금융투자자), SI(운영투자자)** 3그룹으로 구성. "
            "MRG 시대(2000년대 초반)는 CI:FI = 10:90~30:70 비율이 일반적, 현재는 사업유형별 상이."
        )
        
        # 사업유형별 CI/FI/SI 기본값 (실무 관행 기반)
        ci_fi_si_defaults = {
            "BTO":     {"ci": 40, "fi": 50, "si": 10},
            "BTO-rs":  {"ci": 30, "fi": 60, "si": 10},
            "BTO-ann": {"ci": 25, "fi": 65, "si": 10},
            "BTL":     {"ci": 20, "fi": 70, "si": 10},
            "BTO+BTL": {"ci": 28, "fi": 62, "si": 10},
        }
        default = ci_fi_si_defaults.get(business_type, {"ci": 30, "fi": 60, "si": 10})
        
        col_cifi1, col_cifi2, col_cifi3 = st.columns(3)
        with col_cifi1:
            ci_ratio = st.slider(
                "CI 비중(%) — 건설투자자",
                0, 100, default["ci"], 5,
                key="phase2_ci_ratio",
                help="건설 기성금 수익 목적. 시공사 컨소시엄의 출자 비율",
            )
        with col_cifi2:
            fi_ratio = st.slider(
                "FI 비중(%) — 금융투자자",
                0, 100, default["fi"], 5,
                key="phase2_fi_ratio",
                help="대출 이자수익 목적. 은행·증권사·연기금 출자 비율",
            )
        with col_cifi3:
            si_ratio = st.slider(
                "SI 비중(%) — 운영투자자",
                0, 100, default["si"], 5,
                key="phase2_si_ratio",
                help="운영 수익 목적. 운영사·인프라 자산운용사 출자 비율",
            )
        
        total_cifi = ci_ratio + fi_ratio + si_ratio
        if total_cifi != 100:
            st.warning(f"⚠️ CI + FI + SI 합계 = {total_cifi}% (100%가 되도록 조정 권장)")
        
        ci_amount = equity_amount * ci_ratio / 100
        fi_amount = equity_amount * fi_ratio / 100
        si_amount = equity_amount * si_ratio / 100
        
        # 시각화
        fig_cifi = go.Figure()
        fig_cifi.add_trace(go.Pie(
            labels=['CI (건설투자자)', 'FI (금융투자자)', 'SI (운영투자자)'],
            values=[ci_amount, fi_amount, si_amount],
            marker_colors=['#1F3864', '#4A6FA5', '#EF9F27'],
            textinfo='label+percent+value',
            textposition='inside',
        ))
        fig_cifi.update_layout(
            title=f"자기자본 구성 ({equity_amount:,.0f}억)",
            height=280,
            margin=dict(t=40, b=20, l=20, r=20),
            showlegend=False,
        )
        st.plotly_chart(fig_cifi, use_container_width=True)
        
        st.markdown("")
        
        # 공기 지연 시나리오 (사업주의 핵심 위험)
        st.markdown("**⏱ 공기 지연 시나리오 분석**")
        st.caption("시공 지연이 사업 NPV·IRR에 미치는 영향. 사업주는 EPC 계약상 손해배상·지체상금 부담.")
        
        delay_scenarios = [
            {"label": "정상 공기", "delay_years": 0},
            {"label": "+1년 지연", "delay_years": 1},
            {"label": "+2년 지연", "delay_years": 2},
            {"label": "+3년 지연", "delay_years": 3},
        ]
        
        base_npv_sta = metrics['npv']
        # avg_debt_rate, wacc는 함수 상단에서 이미 정의됨 (스코프 안전)
        
        delay_results = []
        for sc in delay_scenarios:
            # 지연 시 영향: 매출 시작 지연 + 이자 자본화 추가 + 운영기간 단축
            delay = sc['delay_years']
            
            # 이자 자본화 추가 (지연된 기간 동안 부채 이자 발생)
            additional_idc = debt_amount * avg_debt_rate * delay
            
            # 매출 손실 (지연 기간 동안 매출 0)
            revenue_loss = annual_rev * delay if delay > 0 else 0
            
            # NPV 영향 추정 (단순화: 운영 1년치 NPV 손실 + IDC 증가)
            opex_y = annual_rev * avg_opex_ratio
            net_cf_per_year = annual_rev - opex_y
            
            # 지연 기간의 NPV 손실 = 연차별 net CF 미실현
            npv_loss = 0
            for d in range(1, delay + 1):
                # 지연된 연차의 net CF를 현가로 계산
                npv_loss += net_cf_per_year / ((1 + wacc) ** (construction_years + d))
            
            adjusted_npv = base_npv_sta - npv_loss - additional_idc
            
            delay_results.append({
                "시나리오": sc['label'],
                "추가 이자 자본화 (억)": additional_idc,
                "매출 손실 (억)": npv_loss,
                "조정 NPV (억)": adjusted_npv,
                "Base 대비 (억)": adjusted_npv - base_npv_sta,
            })
        
        df_delay = pd.DataFrame(delay_results)
        df_delay["추가 이자 자본화 (억)"] = df_delay["추가 이자 자본화 (억)"].round(0).astype(int)
        df_delay["매출 손실 (억)"] = df_delay["매출 손실 (억)"].round(0).astype(int)
        df_delay["조정 NPV (억)"] = df_delay["조정 NPV (억)"].round(0).astype(int)
        df_delay["Base 대비 (억)"] = df_delay["Base 대비 (억)"].round(0).astype(int)
        
        st.dataframe(df_delay, use_container_width=True, hide_index=True)
        
        st.markdown("")
        
        # 공사비 변동 위험 분담 (보완 11 흡수 — 2024.10 정부 활성화 방안)
        st.markdown("**🛡️ 공사비 변동 위험 분담 (2024.10 정부 활성화 방안)**")
        st.caption(
            "정부의 **「민간투자 활성화 방안」(2024.10, 24-19-4)**은 BTO 사업의 "
            "공사비 변동 위험을 정부·사업자가 분담하는 특례를 신설. "
            "공사비 상승률이 GDP디플레이터·CPI 차이를 초과할 경우 정부 보전."
        )
        
        col_cost1, col_cost2 = st.columns(2)
        with col_cost1:
            cost_inflation = st.slider(
                "예상 공사비 상승률(%)",
                0.0, 15.0, 5.0, 0.5,
                key="phase2_cost_inflation",
                help="시공기간 중 자재·인건비 등 공사비 상승률 (CPI + α)",
            ) / 100
        with col_cost2:
            govt_share = st.slider(
                "정부 부담 비율(%)",
                0, 100, 50, 5,
                key="phase2_govt_share",
                help="공사비 초과분 중 정부 보전 비율 (2024.10 정부 활성화 방안 기준 협상)",
            ) / 100
        
        cost_overrun = total_capex * cost_inflation
        sponsor_burden = cost_overrun * (1 - govt_share)
        govt_burden_cost = cost_overrun * govt_share
        
        col_cb1, col_cb2, col_cb3 = st.columns(3)
        col_cb1.metric(
            "예상 공사비 초과액",
            f"{cost_overrun:,.0f} 억",
            help=f"CAPEX × 상승률 = {total_capex:,} × {cost_inflation*100:.1f}%",
        )
        col_cb2.metric(
            "사업주 부담",
            f"{sponsor_burden:,.0f} 억",
            delta=f"{(1-govt_share)*100:.0f}%",
            help="사업주가 자체 부담하는 공사비 초과분 (자기자본·후순위로 조달)",
        )
        col_cb3.metric(
            "정부 보전",
            f"{govt_burden_cost:,.0f} 억",
            delta=f"{govt_share*100:.0f}%",
            help="2024.10 정부 활성화 방안에 따른 공사비 분담 특례",
        )

        if "통합" in perspective:
            st.markdown("---")

    # ════════════════════════════════════════════════════════════
    # C. 통합 비교 (LTA vs STA 의사결정 매트릭스)
    # ════════════════════════════════════════════════════════════
    if "통합" in perspective:
        st.markdown("##### 🔁 LTA vs STA — 시공·자금조달 의사결정 비교")
        st.caption("동일 사업에 대해 대주단·사업주가 우선시하는 지표 차이를 정리.")
        
        compare_data = [
            {
                "지표": "최우선 관심사",
                "LTA (대주단)": "부도 위험 최소화",
                "STA (사업주)": "자기자본 회수율 최대화",
            },
            {
                "지표": "핵심 KPI",
                "LTA (대주단)": "DSCR ≥ 1.2",
                "STA (사업주)": "ROE ≥ Ke",
            },
            {
                "지표": "선호 자본구조",
                "LTA (대주단)": "자기자본 비율 ↑ (위험 분담)",
                "STA (사업주)": "타인자본 비율 ↑ (레버리지)",
            },
            {
                "지표": "선호 금리 구조",
                "LTA (대주단)": "선순위 비중 ↑ + 가산금리 ↑",
                "STA (사업주)": "후순위 활용 + 금리 인하 협상",
            },
            {
                "지표": "공사비 변동 시",
                "LTA (대주단)": "정부 보전 확대 선호",
                "STA (사업주)": "정부 보전 + EPC 계약 보호 동시",
            },
            {
                "지표": "MRG·MCC 활용",
                "LTA (대주단)": "MRG 확대 (수입 안정)",
                "STA (사업주)": "MCC 확대 (운영비 위험 ↓)",
            },
        ]
        df_compare = pd.DataFrame(compare_data)
        st.dataframe(df_compare, use_container_width=True, hide_index=True)
        
        st.markdown(
            f"""<div style="background:#E3F2FD;border-left:5px solid #1F3864;
                padding:14px 18px;border-radius:6px;margin:8px 0;">
                <div style="font-weight:bold;color:#1F3864;font-size:15px;">
                    💡 Forenode 통합 가치 — 양쪽 모두에게 같은 분석 도구
                </div>
                <div style="margin-top:6px;font-size:13px;color:#444;">
                    기존: LTA·STA가 각자 컨설팅사·자문사 별도 의뢰 (건당 수개월·수억원).<br>
                    Forenode: 동일 입력으로 양쪽 보고서를 30초에 자동 생성, 협상 시 동일 데이터 기반.
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ════════════════════════════════════════════════════════════
    # BIM 모드 안내 (작은 placeholder)
    # ════════════════════════════════════════════════════════════
    with st.expander("📁 BIM(IFC) 모드 — Stage 2 (2026년 7~8월 출시 예정)"):
        uploaded_ifc = st.file_uploader(
            "IFC 파일 업로드 (자재 BoM 자동 추출, ±5% 정확도)",
            type=["ifc", "ifczip"],
            disabled=True,
            key="phase2_ifc_upload",
        )
        st.info(
            "🚧 **BIM 통합 모드 — Stage 2 개발 예정**\n\n"
            "안심구역 데이터(구조물 영상분석 + 교량 점검내역, PET 동형암호결합)와 "
            "IFC 자재 BoM을 통합하여 CAPEX 정확도를 ±20%(통계) → ±5%(BIM)로 개선합니다. "
            "현재 통계 모드 분석은 위 LTA·STA·통합 화면을 활용하세요."
        )


# ════════════════════════════════════════════════════════════
# 시점 3: 운영 — 실적 비교
# ════════════════════════════════════════════════════════════
def render_phase_operation(ctx: dict):
    _render_mode_badge(
        mode="실적",
        accuracy="±5%",
        description=(
            "운영기간 중 분석용. 실시협약 가정 통행량·수익 vs 실제 실적을 비교하여 "
            "운영평가·자금재조달·사후관리 보고서를 생성합니다."
        ),
    )

    st.markdown("#### 🛣 운영 단계 — 운영평가·자금재조달")
    st.caption(
        "**활용 주체**: CEPHIS(민자도로관리지원센터) · KDI PIMAC · 주무관청 | "
        "**분석 업무**: 운영평가, 자금재조달(Refinancing), 사후관리 보고"
    )

    st.markdown("---")

    st.markdown("##### 📈 운영 실적 입력")
    col_y, col_t = st.columns(2)
    with col_y:
        elapsed_years = st.slider(
            "운영 경과 연차", 1, ctx['operation_years'], 5,
            help="현재 시점의 운영 연차",
            key="phase3_elapsed",
        )
    with col_t:
        actual_traffic_ratio = st.slider(
            "실적 통행량 비율 (가정 대비 %)", 50, 150, 80,
            help="실시협약 가정 통행량 대비 실제 통행량 비율",
            key="phase3_actual",
        ) / 100

    st.markdown("")

    st.markdown("##### 📊 가정 vs 실적 비교")

    annual_rev = ctx['annual_revenue']
    growth = 0.025
    years_array = list(range(1, elapsed_years + 1))

    assumed_rev = [annual_rev * (1 + growth) ** (y - 1) for y in years_array]
    actual_rev = [r * actual_traffic_ratio for r in assumed_rev]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years_array, y=assumed_rev,
        name='실시협약 가정', marker_color='#1F3864', opacity=0.6,
    ))
    fig.add_trace(go.Bar(
        x=years_array, y=actual_rev,
        name='실제 실적', marker_color='#EF9F27',
    ))
    fig.update_layout(
        title=f"운영 {elapsed_years}년차까지 수익 비교",
        xaxis_title="운영 연차",
        yaxis_title="연간 수익 (억원)",
        barmode='group',
        height=320,
        margin=dict(t=40, b=40, l=40, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    gap_pct = (actual_traffic_ratio - 1.0) * 100
    if gap_pct < -15:
        msg = f"⚠️ **실적이 가정 대비 {abs(gap_pct):.0f}% 미달** — MRG 발동 요건 검토, 재구조화 협상 권장"
        color = "#D45F5F"
    elif gap_pct < 0:
        msg = f"📉 **실적이 가정 대비 {abs(gap_pct):.0f}% 미달** — 시장 변동 범위, 지속 모니터링"
        color = "#EF9F27"
    elif gap_pct < 15:
        msg = f"✅ **실적이 가정 대비 +{gap_pct:.0f}%** — 안정적 운영"
        color = "#1D9E75"
    else:
        msg = f"📈 **실적이 가정 대비 +{gap_pct:.0f}%** — 자금재조달(Refinancing) 검토 호기"
        color = "#1F3864"

    st.markdown(
        f"""<div style="background:#F8F9FA;border-left:5px solid {color};
            padding:12px 16px;border-radius:6px;margin:8px 0;">
            <span style="color:{color};font-weight:bold;">{msg}</span>
        </div>""",
        unsafe_allow_html=True,
    )

    st.markdown("")
    st.caption(
        "💡 **운영기간 활용 예** — 매년 CEPHIS 운영평가 자료 생성, "
        "통행량 미달 시 MRG 청구 근거 자료, 5~10년 주기 자금재조달 검토. "
        "**Stage 2(8월)** 실제 통행 실적 CSV 업로드 기능 추가 예정."
    )


# ════════════════════════════════════════════════════════════
# 시점 4: 재구조화 — 잔여기간 시뮬레이션
# ════════════════════════════════════════════════════════════
def render_phase_restructuring(ctx: dict):
    _render_mode_badge(
        mode="시뮬",
        accuracy="±5%",
        description=(
            "운영기간 만료 협상·M&A 거래용. 잔여기간과 운영기간 연장 시나리오를 "
            "시뮬레이션하여 협상 카드와 잔여 가치를 산출합니다."
        ),
    )

    st.markdown("#### 🔄 재구조화 단계 — 운영기간 연장·자산 거래")
    st.caption(
        "**활용 주체**: 주무관청 · SPC · CEPHIS · 자산운용사 | "
        "**분석 업무**: 운영기간 연장 협상, 실시협약 변경, M&A Due Diligence"
    )

    st.markdown("---")

    st.markdown("##### 🎯 잔여기간 연장 시나리오")

    col_a, col_b = st.columns(2)
    with col_a:
        current_op_year = st.slider(
            "현재 운영 연차", 1, ctx['operation_years'], min(20, ctx['operation_years']),
            help="현재 시점 (운영 기준)",
            key="phase4_current",
        )
    with col_b:
        extension_options = st.multiselect(
            "검토할 연장 시나리오 (년)",
            options=[5, 10, 15, 20, 30],
            default=[5, 10, 20],
            key="phase4_ext",
        )

    remaining = ctx['operation_years'] - current_op_year
    st.info(f"📍 잔여 운영기간: **{remaining}년** (총 {ctx['operation_years']}년 중 {current_op_year}년 경과)")

    if not extension_options:
        st.warning("연장 시나리오를 1개 이상 선택하세요.")
        return

    st.markdown("")

    st.markdown("##### 📊 시나리오별 잔여 NPV")

    annual_rev = ctx['annual_revenue']
    avg_opex_ratio = ctx['opex_estimation']['opex_ratio_avg']
    wacc = ctx['wacc']
    growth = 0.025

    scenarios = []
    base_npv = 0
    for y in range(1, remaining + 1):
        op_year = current_op_year + y
        rev = annual_rev * (1 + growth) ** (op_year - 1)
        opex = rev * avg_opex_ratio
        fcf = rev - opex
        base_npv += fcf / ((1 + wacc) ** y)
    scenarios.append(("현재 조건", remaining, base_npv, 0))

    for ext in extension_options:
        total_remaining = remaining + ext
        npv = 0
        for y in range(1, total_remaining + 1):
            op_year = current_op_year + y
            rev = annual_rev * (1 + growth) ** (op_year - 1)
            opex = rev * avg_opex_ratio
            fcf = rev - opex
            npv += fcf / ((1 + wacc) ** y)
        gain = npv - base_npv
        scenarios.append((f"+{ext}년 연장", total_remaining, npv, gain))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[s[0] for s in scenarios],
        y=[s[2] for s in scenarios],
        text=[f"{s[2]:,.0f}억" for s in scenarios],
        textposition='outside',
        marker_color=['#888888'] + ['#1F3864'] * (len(scenarios) - 1),
        name='잔여 NPV',
    ))
    fig.update_layout(
        title="연장 시나리오별 잔여 NPV (현가)",
        xaxis_title="시나리오",
        yaxis_title="NPV (억원)",
        height=340,
        margin=dict(t=40, b=40, l=40, r=20),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    df_sc = pd.DataFrame(scenarios, columns=["시나리오", "총 잔여기간(년)", "잔여 NPV(억)", "현재 대비 +α(억)"])
    df_sc["잔여 NPV(억)"] = df_sc["잔여 NPV(억)"].round(0).astype(int)
    df_sc["현재 대비 +α(억)"] = df_sc["현재 대비 +α(억)"].round(0).astype(int)
    st.dataframe(df_sc, use_container_width=True, hide_index=True)

    best = max(scenarios[1:], key=lambda x: x[3]) if len(scenarios) > 1 else None
    if best:
        st.markdown(
            f"""<div style="background:#E3F2FD;border-left:5px solid #1F3864;
                padding:14px 18px;border-radius:6px;margin:8px 0;">
                <div style="font-weight:bold;color:#1F3864;font-size:15px;">
                    🎯 권장 협상 카드: {best[0]}
                </div>
                <div style="margin-top:6px;font-size:13px;color:#444;">
                    잔여 NPV {best[2]:,.0f}억 → 현재 조건 대비 <strong>+{best[3]:,.0f}억</strong> 추가 수익. 
                    정부에 통행료 인하 또는 안전·환경 투자로 공공 편익 제시 시 협상 우위 확보.
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("")
    st.caption(
        "💡 **재구조화 활용 예** — 운영기간 만료 직전 SPC 또는 자산운용사가 정부와 협상. "
        "또는 자산 거래(M&A) 시 잔여 가치 평가. "
        "**Stage 2** 안전·환경 투자 패키지 자동 산출 추가 예정."
    )
    
    # ════════════════════════════════════════════════════════════
    # 해지시지급금 분석 — 정부 부담 시뮬레이션 (v2.1 신규)
    # ════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("##### ⚠️ 해지시지급금 분석 — SPC 파산 시 정부 부담")
    st.caption(
        "**해지시지급금**(Termination Payment) = SPC가 도산하거나 실시협약이 해지될 때 "
        "정부가 SPC에 지급해야 하는 금액. 통상 **건설비용과 같도록** 책정됨 (KDB·민간투자법 표준). "
        "운영주체 부재 시 정부가 시설을 인수해야 하므로 재정 부담이 큼 (예: 서울 9호선 인수 검토 사례)."
    )
    
    termination_payment = ctx.get('termination_payment', ctx['total_capex_user'])
    
    col_t1, col_t2, col_t3 = st.columns(3)
    col_t1.metric(
        "해지시지급금",
        f"{termination_payment:,.0f}억",
        help="건설비용과 동일하게 책정 (실시협약 표준)",
    )
    
    # 잔여기간 비례 환산 (현실: 운영연차에 따라 감소하기도 함)
    proportional_payment = termination_payment * (remaining / ctx['operation_years'])
    col_t2.metric(
        "잔여기간 비례",
        f"{proportional_payment:,.0f}억",
        help="운영기간 진행에 따라 감액되는 경우 (실시협약별 상이)",
    )
    
    # 정부 부담 (해지시지급금 - 잔여 NPV)
    govt_burden = max(0, termination_payment - base_npv)
    col_t3.metric(
        "정부 순부담",
        f"{govt_burden:,.0f}억",
        delta=f"잔여 NPV {base_npv:,.0f}억 차감 후",
        help="정부가 시설을 인수할 때 실질 부담액 = 해지시지급금 - 잔여 NPV. 양수일수록 정부 손실 ↑",
    )
    
    st.markdown("")
    
    # 협상 카드 비교
    st.markdown("##### 🤝 해지 vs 협상 — 정부·SPC 의사결정 매트릭스")
    
    # 4가지 시나리오 비교
    decision_data = [
        {
            "주체": "정부",
            "선택": "해지 인수",
            "결과 (억)": -govt_burden,
            "의미": f"건설비용 {termination_payment:,.0f}억 지급, 잔여 NPV {base_npv:,.0f}억 회수",
        },
        {
            "주체": "정부",
            "선택": "협상 (통행료 인하)",
            "결과 (억)": -(base_npv * 0.1),  # 가정: 통행료 -10% 협상
            "의미": "통행료 인하 보전 부담 (해지 대비 부담 감소)",
        },
        {
            "주체": "SPC",
            "선택": "도산 → 해지",
            "결과 (억)": termination_payment - ctx['total_capex_user'],
            "의미": "건설비용 회수 (단, 운영권 상실)",
        },
        {
            "주체": "SPC",
            "선택": "협상 (운영기간 연장)",
            "결과 (억)": best[3] if best else 0,
            "의미": f"운영기간 연장으로 추가 수익 확보",
        },
    ]
    
    df_decision = pd.DataFrame(decision_data)
    st.dataframe(
        df_decision,
        use_container_width=True,
        hide_index=True,
        column_config={
            "결과 (억)": st.column_config.NumberColumn(format="%d"),
        },
    )
    
    # 협상 권고
    govt_save_by_negotiation = govt_burden - (base_npv * 0.1)
    if govt_save_by_negotiation > 0:
        st.markdown(
            f"""<div style="background:#FFF3E0;border-left:5px solid #EF9F27;
                padding:14px 18px;border-radius:6px;margin:8px 0;">
                <div style="font-weight:bold;color:#1F3864;font-size:15px;">
                    💼 협상 권고: 정부·SPC 모두 협상이 우위
                </div>
                <div style="margin-top:6px;font-size:13px;color:#444;">
                    정부는 해지 시 <strong>{govt_burden:,.0f}억</strong> 손실 vs 협상 시 <strong>{base_npv*0.1:,.0f}억</strong> 손실
                    (절감액 <strong>{govt_save_by_negotiation:,.0f}억</strong>).
                    SPC는 도산 시 운영권 상실 vs 협상 시 운영기간 연장으로 <strong>+{best[3] if best else 0:,.0f}억</strong> 확보 가능.
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    
    st.caption(
        "💡 본 분석은 시뮬레이션 모델로, 실제 협상은 실시협약 조항·정치적 고려·이용자 편익에 따라 달라짐. "
        "**활용 예**: KDI PIMAC 재구조화 분쟁조정, CEPHIS 사업구조 개선 정책 수립, 자산운용사 M&A 입찰가 산정."
    )
