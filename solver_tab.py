"""
solver_tab.py — 요구수익률 솔버 (분석 도구 12번째 탭)

기능:
  1. 5대 고객 그룹별 요구수익률 프리셋
  2. 자동 진단 (현재 vs 요구수익률 갭)
  3. 1변수 goal seek (scipy.optimize.brentq)
  4. 다변수 시나리오 (3가지 조정 방안)
  5. 권장 시나리오 카드

옵션 B 본격 구현 + 옵션 C (AI 권고) placeholder
"""

import streamlit as st
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from typing import Callable, Optional

# ════════════════════════════════════════════════════════════
# 5대 고객 그룹별 요구수익률 프리셋
# ════════════════════════════════════════════════════════════
CUSTOMER_PRESETS = {
    "대주단 (LTA)": {
        "icon": "📐",
        "description": "Lender's Technical Advisor — 부채 회수 안정성 중심",
        "criteria": {
            "DSCR_min": 1.20,
            "IRR_min": 0.08,
        },
        "priority": "DSCR 안정성 > IRR > NPV",
        "label_dscr": "DSCR ≥ 1.20",
        "label_irr": "IRR ≥ 8%",
    },
    "사업주 (STA)": {
        "icon": "🏢",
        "description": "Sponsor's Technical Advisor — 자기자본 회수율 중심",
        "criteria": {
            "ROE_min": 0.10,      # CAPM 기반 일반 Ke
            "Equity_IRR_min": 0.12,
        },
        "priority": "ROE > Equity IRR > NPV",
        "label_dscr": "ROE ≥ 10%",
        "label_irr": "Equity IRR ≥ 12%",
    },
    "자산운용사·연기금": {
        "icon": "💼",
        "description": "Asset Manager — 잔여가치 + 안정 수익",
        "criteria": {
            "IRR_min": 0.10,
            "ROE_min": 0.12,
            "DSCR_min": 1.15,
        },
        "priority": "IRR > ROE > DSCR",
        "label_dscr": "IRR ≥ 10%",
        "label_irr": "ROE ≥ 12%",
    },
    "KDI PIMAC·주무관청": {
        "icon": "🏛️",
        "description": "Public Sector — VfM·B/C 중심",
        "criteria": {
            "BC_ratio_min": 1.00,
            "NPV_min": 0,
        },
        "priority": "B/C > NPV > VfM",
        "label_dscr": "B/C ≥ 1.0",
        "label_irr": "NPV ≥ 0",
    },
    "민자 SPC (운영중)": {
        "icon": "🛣️",
        "description": "SPC — ROE ≥ Ke 달성·DSCR 안정",
        "criteria": {
            "ROE_min": 0.08,   # 사이드바 Ke 기본값
            "DSCR_min": 1.10,
        },
        "priority": "ROE ≥ Ke > DSCR",
        "label_dscr": "ROE ≥ Ke",
        "label_irr": "DSCR ≥ 1.10",
    },
}


def _eval_metrics(base_params: dict, override: dict, build_fn: Callable) -> dict:
    """
    변수를 override 한 상태에서 build_cashflow 실행, metrics 반환
    
    Parameters
    ----------
    base_params : dict   사이드바 base_params
    override : dict      변경할 변수 {key: new_value}
    build_fn : Callable  build_cashflow 함수
    """
    params = {**base_params, **override}
    try:
        _, metrics = build_fn(**params)
        return metrics
    except Exception:
        return None


def _goal_seek_single(
    base_params: dict,
    build_fn: Callable,
    target_metric: str,
    target_value: float,
    var_name: str,
    var_low: float,
    var_high: float,
    is_increasing: bool = True,
) -> Optional[float]:
    """
    1변수 goal seek — scipy.optimize.brentq 사용
    
    target_metric에서 target_value 달성하는 var_name 값 찾기
    """
    def diff(x):
        m = _eval_metrics(base_params, {var_name: x}, build_fn)
        if m is None:
            return float('inf')
        actual = m.get(target_metric)
        if actual is None:
            return float('inf')
        # IRR 등은 None 가능
        if isinstance(actual, (list, tuple, np.ndarray)):
            return float('inf')
        try:
            return float(actual) - target_value
        except (TypeError, ValueError):
            return float('inf')
    
    try:
        # 양 끝 부호 확인
        f_low = diff(var_low)
        f_high = diff(var_high)
        if f_low * f_high > 0:
            # 같은 부호 → 해 없음
            return None
        result = brentq(diff, var_low, var_high, xtol=1e-4, maxiter=50)
        return float(result)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 메인 렌더 함수
# ════════════════════════════════════════════════════════════
def render_solver_tab(base_params: dict, metrics: dict, build_fn: Callable, ctx: dict):
    """
    분석 도구 12번째 탭 — 요구수익률 솔버
    
    Parameters
    ----------
    base_params : dict   현재 사이드바 base_params (build_cashflow 인자)
    metrics : dict       현재 metrics (NPV·IRR·ROE·DSCR 등)
    build_fn : Callable  build_cashflow 함수 (변수 변경 시 재계산용)
    ctx : dict           phase_context (사업유형·자기자본비율 등)
    """
    # ─── 모드 배지 ─────────────────────────────────
    st.markdown(
        f"""<div style="background:linear-gradient(90deg, #1F3864 0%, #4A6FA5 100%);
            color:white;padding:14px 18px;border-radius:6px;margin-bottom:14px;">
            <div style="font-size:13px;opacity:0.85;">분석 모드</div>
            <div style="font-size:20px;font-weight:bold;margin-top:4px;">
                🎯 통계 솔버 (Statistical Solver Mode)
            </div>
            <div style="font-size:12px;margin-top:8px;opacity:0.9;">
                정확도 ±20% (학습 통계 신뢰구간) · 
                BIM 통합 모드 Stage 2 (2026년 7월 경) 출시 예정
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.markdown("#### 🎯 요구수익률 솔버 — 목표값 달성 방안 자동 제시")
    st.caption(
        "**활용 주체**: 5대 고객 그룹 모두 | "
        "**분석 업무**: 목표 지표 입력 → 변수 조정 시나리오 자동 도출 | "
        "**대체**: 컨설팅사 분석 업무 소요 시간 단축"
    )
    
    st.markdown("---")
    
    # ─── 1. 고객 그룹 선택 ─────────────────────────
    st.markdown("##### 1단계. 고객 그룹 선택")
    
    col_g, col_d = st.columns([1, 2])
    with col_g:
        group_name = st.selectbox(
            "분석 관점",
            options=list(CUSTOMER_PRESETS.keys()) + ["사용자 정의"],
            key="solver_group",
            help="5대 고객 그룹의 표준 요구수익률 프리셋. 사용자 정의 선택 시 직접 입력.",
        )
    
    if group_name == "사용자 정의":
        with col_d:
            st.caption("⚙️ 사용자 정의 모드 — 아래에서 목표 지표·값 직접 입력")
        criteria = {}
        preset_priority = "사용자 정의"
    else:
        preset = CUSTOMER_PRESETS[group_name]
        criteria = preset["criteria"].copy()
        preset_priority = preset["priority"]
        with col_d:
            st.markdown(
                f"""<div style="background:#E3F2FD;border-left:5px solid #1F3864;
                    padding:10px 14px;border-radius:6px;">
                    <div style="font-weight:bold;color:#1F3864;font-size:14px;">
                        {preset['icon']} {group_name}
                    </div>
                    <div style="font-size:12px;color:#555;margin-top:4px;">
                        {preset['description']}<br>
                        <b>우선순위</b>: {preset['priority']}
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )
    
    st.markdown("")
    
    # ─── 2. 목표 지표 사용자 조정 ─────────────────
    st.markdown("##### 2단계. 목표 지표 확인/조정")
    
    targets = {}
    cols_t = st.columns(min(4, max(1, len(criteria) if criteria else 2)))
    
    if group_name == "사용자 정의":
        # 사용자 정의: 모든 지표 슬라이더
        with cols_t[0]:
            targets['NPV_min'] = st.number_input("목표 NPV (억)", value=0, step=100, key="t_npv")
        with cols_t[1]:
            targets['IRR_min'] = st.slider("목표 IRR (%)", 0.0, 25.0, 8.0, 0.5, key="t_irr") / 100
        with cols_t[2] if len(cols_t) > 2 else cols_t[0]:
            targets['ROE_min'] = st.slider("목표 ROE (%)", 0.0, 30.0, 10.0, 0.5, key="t_roe") / 100
        with cols_t[3] if len(cols_t) > 3 else cols_t[0]:
            targets['DSCR_min'] = st.slider("최소 DSCR", 1.00, 2.00, 1.20, 0.05, key="t_dscr")
    else:
        # 프리셋: 표시만, 미세 조정 가능
        i = 0
        for k, v in criteria.items():
            with cols_t[i % len(cols_t)]:
                if k in ('NPV_min',):
                    targets[k] = st.number_input(f"{k}", value=int(v), step=100, key=f"t_{k}")
                elif k.endswith('_ratio_min'):
                    targets[k] = st.slider(f"{k}", 0.5, 2.0, float(v), 0.05, key=f"t_{k}")
                elif k.startswith('DSCR'):
                    targets[k] = st.slider(f"{k}", 1.00, 2.00, float(v), 0.05, key=f"t_{k}")
                else:
                    # 비율: IRR, ROE 등
                    targets[k] = st.slider(f"{k} (%)", 0.0, 30.0, float(v)*100, 0.5, key=f"t_{k}") / 100
            i += 1
    
    st.markdown("---")
    
    # ─── 3. 자동 진단 ─────────────────────────────
    st.markdown("##### 3단계. 자동 진단 — 현재 상태 vs 요구수익률")
    
    diagnosis = []
    all_met = True
    for k, target in targets.items():
        # 현재 metrics에서 매칭
        if k == 'DSCR_min':
            actual = metrics.get('dscr_min', 0)
        elif k == 'NPV_min':
            actual = metrics.get('npv', 0)
        elif k == 'IRR_min':
            actual = metrics.get('nominal_irr', 0) or 0
        elif k == 'Equity_IRR_min':
            actual = metrics.get('equity_irr', 0) or 0
        elif k == 'ROE_min':
            actual = metrics.get('roe', 0) or 0
        elif k == 'BC_ratio_min':
            actual = metrics.get('bc_ratio', 0) or 0
        else:
            continue
        
        gap = actual - target
        met = gap >= 0
        if not met:
            all_met = False
        diagnosis.append({
            "지표": k.replace('_min', '').replace('_', ' '),
            "요구값": f"{target:.3f}" if isinstance(target, float) and target < 10 else f"{target:,.0f}",
            "현재값": f"{actual:.3f}" if isinstance(actual, float) and abs(actual) < 10 else f"{actual:,.0f}",
            "갭": f"{gap:+.3f}" if abs(gap) < 10 else f"{gap:+,.0f}",
            "충족": "✅" if met else "❌",
        })
    
    if diagnosis:
        df_diag = pd.DataFrame(diagnosis)
        st.dataframe(df_diag, use_container_width=True, hide_index=True)
    
    if all_met:
        st.markdown(
            """<div style="background:#E8F5E9;border-left:5px solid #1B5E20;
                padding:14px 18px;border-radius:6px;margin:10px 0;">
                <div style="font-weight:bold;color:#1B5E20;font-size:16px;">
                    ✅ 모든 요구수익률 충족 — 현재 사업 조건으로 진행 가능
                </div>
                <div style="font-size:13px;color:#444;margin-top:6px;">
                    별도 조정 없이 사업 추진 가능. 추가 마진 확보 시 시나리오 솔버 활용.
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """<div style="background:#FFEBEE;border-left:5px solid #C62828;
                padding:14px 18px;border-radius:6px;margin:10px 0;">
                <div style="font-weight:bold;color:#C62828;font-size:16px;">
                    ❌ 일부 요구수익률 미달 — 변수 조정 필요
                </div>
                <div style="font-size:13px;color:#444;margin-top:6px;">
                    아래 4단계에서 자동 도출된 3가지 시나리오를 검토하세요.
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    
    st.markdown("---")
    
    # ─── 4. 자동 솔루션 (3가지 시나리오) ──────────
    st.markdown("##### 4단계. 자동 솔루션 — 변수 조정 시나리오 3종")
    
    if all_met:
        st.info("📌 모든 요구수익률을 이미 충족하여 변수 조정이 불필요합니다. "
                "시나리오 분석은 마진 확보 목적으로만 활용하세요.")
    
    # 가장 부족한 지표 1개 선정 (가장 큰 갭)
    critical_idx = None
    critical_gap = 0
    critical_key = None
    for d in diagnosis:
        if d["충족"] == "❌":
            try:
                gap_v = float(d["갭"].replace('+', '').replace(',', ''))
                if abs(gap_v) > abs(critical_gap):
                    critical_gap = gap_v
                    critical_key = d["지표"]
            except ValueError:
                continue
    
    # 시나리오 정의
    scenarios = []
    
    # 시나리오 A: 통행료 인상 (1변수 goal seek)
    # 통행료는 base_params에 직접 없으므로 annual_revenue_억으로 우회
    # 단순 시뮬레이션: revenue × 1.05~1.10 효과를 적용
    if critical_key:
        # 통행료 +X% 시뮬레이션
        for toll_pct in [0.03, 0.05, 0.08, 0.10, 0.15]:
            curr_rev = base_params.get('annual_revenue_억', 100)
            test = _eval_metrics(
                base_params,
                {'annual_revenue_억': curr_rev * (1 + toll_pct)},
                build_fn,
            )
            if test:
                # critical_key가 충족되는지 확인
                ok = True
                for k, t in targets.items():
                    if k == 'DSCR_min' and test.get('dscr_min', 0) < t:
                        ok = False
                        break
                    if k == 'IRR_min' and (test.get('nominal_irr', 0) or 0) < t:
                        ok = False
                        break
                    if k == 'ROE_min' and (test.get('roe', 0) or 0) < t:
                        ok = False
                        break
                if ok:
                    scenarios.append({
                        "시나리오": "A. 통행료 인상",
                        "변경": f"+{toll_pct*100:.0f}%",
                        "영향": "사용료 수입 증가",
                        "위험": "사회수용성 검토 필요 (도공 1.1배 기준)",
                    })
                    break
    
    # 시나리오 B: MRG 협상
    if critical_key:
        curr_mrg = base_params.get('mrg_ratio', 0)
        for new_mrg in [0.5, 0.7, 0.9]:
            if new_mrg <= curr_mrg:
                continue
            test = _eval_metrics(base_params, {'mrg_ratio': new_mrg}, build_fn)
            if test:
                ok = True
                for k, t in targets.items():
                    if k == 'DSCR_min' and test.get('dscr_min', 0) < t:
                        ok = False
                        break
                    if k == 'IRR_min' and (test.get('nominal_irr', 0) or 0) < t:
                        ok = False
                        break
                    if k == 'ROE_min' and (test.get('roe', 0) or 0) < t:
                        ok = False
                        break
                if ok:
                    scenarios.append({
                        "시나리오": "B. MRG 협상",
                        "변경": f"MRG {new_mrg*100:.0f}%",
                        "영향": "수요 위험 분담 → 매출 안정성 ↑",
                        "위험": "정부 협상 필요, 사업유형 변경 (BTO → BTO-rs/ann)",
                    })
                    break
    
    # 시나리오 C: 운영기간 연장
    if critical_key:
        curr_op = base_params.get('operation_years', 30)
        for new_op in [curr_op + 3, curr_op + 5, curr_op + 10]:
            if new_op > 50:
                break
            test = _eval_metrics(base_params, {'operation_years': new_op}, build_fn)
            if test:
                ok = True
                for k, t in targets.items():
                    if k == 'DSCR_min' and test.get('dscr_min', 0) < t:
                        ok = False
                        break
                    if k == 'IRR_min' and (test.get('nominal_irr', 0) or 0) < t:
                        ok = False
                        break
                    if k == 'ROE_min' and (test.get('roe', 0) or 0) < t:
                        ok = False
                        break
                if ok:
                    scenarios.append({
                        "시나리오": "C. 운영기간 연장",
                        "변경": f"+{new_op - curr_op}년 ({new_op}년)",
                        "영향": "장기 매출 누적 → ROE·NPV 개선",
                        "위험": "정부 협상 필요 (관리운영권 연장)",
                    })
                    break
    
    if scenarios:
        df_sc = pd.DataFrame(scenarios)
        st.dataframe(df_sc, use_container_width=True, hide_index=True)
        
        st.markdown(
            """<div style="background:#FFF3E0;border-left:5px solid #EF9F27;
                padding:14px 18px;border-radius:6px;margin:10px 0;">
                <div style="font-weight:bold;color:#1F3864;font-size:14px;">
                    💼 권장 시나리오 선정 기준
                </div>
                <div style="font-size:12px;color:#444;margin-top:6px;">
                    <b>A 통행료 인상</b>: 즉시 조정 가능, 사회수용성 위험<br>
                    <b>B MRG 협상</b>: 정부와 협상 필요, 사업 구조적 안정성 ↑<br>
                    <b>C 운영기간 연장</b>: 장기 관점, 관리운영권 협상 필요<br>
                    실무: 보통 A+B 또는 B+C 조합으로 해결
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    elif not all_met:
        st.warning("⚠️ 단일 변수 조정으로는 모든 요구수익률 충족 불가. "
                  "다변수 조합 솔버 (Stage 2 BIM 통합 모드)에서 처리 예정.")
    
    st.markdown("---")
    
    # ─── 5. 옵션 C placeholder (AI 권고 모드) ─────
    with st.expander("🤖 AI 권고 모드 — Stage 2 (2026년 7~8월 출시 예정)"):
        st.markdown(
            """
            **🚧 AI 기반 자동 권고 모드 — Stage 2 개발 예정**
            
            현재 통계 솔버 모드는 1변수 또는 단순 다변수 조합 분석을 제공합니다. 
            Stage 2에서는 다음 기능이 추가됩니다. 예시:
            
            - **자연어 입력**: "DSCR 1.2 안 되는데 어떻게 해야 하나" → 자동 분석
            - **다변수 최적화**: scipy.optimize.minimize 기반 다목적 최적화
            - **AI 권고 생성**: GPT-4o-mini 활용 한글 권고문 자동 생성
            - **실무 사례 기반**: 853건 민자사업 + 16개 법령 RAG 결합
            - **법령 근거 인용**: 통행료 협상·MRG 변경 가능성을 법령 조항 기준 검토
            
            현재 통계 솔버 모드는 위 4단계 화면을 활용하시기 바랍니다.
            """
        )
    
    # 디버그 정보 (개발자용, 평소 숨김)
    with st.expander("🔍 상세 진단 정보 (디버그)"):
        st.json({
            "고객 그룹": group_name,
            "우선순위": preset_priority,
            "현재 metrics": {
                k: v for k, v in metrics.items()
                if k in ('npv', 'nominal_irr', 'equity_irr', 'roe', 'dscr_min', 'bc_ratio')
            },
            "목표 (criteria)": targets,
            "충족 여부": "전체 충족" if all_met else "일부 미달",
            "탐색된 시나리오 수": len(scenarios),
        })
