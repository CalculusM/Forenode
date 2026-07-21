"""
============================================================
Forenode — 공공데이터 기반 민자도로 수익성·적정성 검증 (BIM은 선택 입력)
============================================================
실행: streamlit run app.py
필수: pip install streamlit numpy pandas plotly requests
선택: pip install ifcopenshell  (BIM 파싱용)
============================================================
v2.0  2026-04-22
- discount_rate 중복 키워드 버그 수정
- ECOS 기준금리 자동연동 모듈 통합
- BIM 재료 추출 & 열화곡선 프레임워크 통합
- 감사보고서 실데이터 기반 벤치마크 탑재
- Monte Carlo / Tornado / 현금흐름 / 열화곡선 / 통행료 / 금융구조 탭
============================================================
"""

import streamlit as st
import numpy as np
import pandas as pd
import math
import json
import os
import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from rag_tab import render_rag_tab
from data_sources import (
    render_data_source_sidebar,
    render_data_flow_banner,
    render_data_flow_diagram,
)
from xgboost_tab import render_xgboost_tab
from weibull_tab import render_weibull_tab
from opex_tab import render_opex_tab
from solver_tab import render_solver_tab

# Forenode v2 — 자동 산출 모듈
from opex_estimator import (estimate_opex_series, estimate_opex_series_bottomup,
                            montecarlo_opex_band, load_weibull_ci)
from pretest_regressor import estimate_capex_from_route

# ── Plotly (없으면 matplotlib fallback) ──
try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ════════════════════════════════════════════════════════════
# [ENGINE] 핵심 계산 엔진
# ════════════════════════════════════════════════════════════

def build_cashflow(
    capex_억: float,
    annual_revenue_억: float,
    construction_years: int = 5,
    operation_years: int = 30,
    opex_ratio: float = 0.35,
    opex_series_억: np.ndarray = None,
    discount_rate: float = 0.05,
    inflation: float = 0.02,
    growth_rate: float = 0.02,
    equity_ratio: float = 0.20,
    debt_rate: float = 0.045,
    business_type: str = "BTO-ann",
    mrg_ratio: float = 0.0,
    mrg_years: int = 0,
    forecast_revenue_억: float = None,
    revenue_series_억: np.ndarray = None,
    mcc_ratio: float = 0.0,
    restructuring_year: int = 0,
    equity_recovery_method: str = "원금+수익률",  # 보완 6: '회수안함' / '원금만' / '원금+수익률'
    debt_repayment_method: str = "원리금균등",     # 보완 7: '원리금균등' / '원리금불균등' / '기간조정'
    **kwargs,
):
    """
    현금흐름 구축
    
    신규 인자 (v2):
        business_type   : 사업유형 (BTO/BTO-rs/BTO-ann/BTL/BTO+BTL)
        mrg_ratio       : MRG 보장률 (0.0~1.0). 정부 보전금 발동 기준
        mcc_ratio       : MCC 비용보전율 (0.0~1.0). BTO-a 사업의 운영비 정부 보전

    신규 인자 (v3 — 인천공항 백테스트 L1·L2·L4 반영, 2026-07):
        mrg_years       : MRG 보장기간(운영연차 기준). 0이면 운영기간 전체(하위호환).
                          실협약은 보통 15~20년 한정(예: 인천공항 20년) — L4.
        forecast_revenue_억 : 협약 추정수입 1년차(억). MRG floor의 기준 수입.
                          미지정 시 annual_revenue_억 사용(입력수입=협약수입 가정, 종전 동작).
                          실현 시나리오(annual_revenue_억)와 분리 입력하면 수요 미달형
                          MRG 보전이 올바르게 계산된다 — L1.
        revenue_series_억 : 실현 수입 시계열(운영연차별, 억). 지정 시 annual_revenue_억×
                          growth 대신 사용 — 램프업·경쟁도로 단차 등 비단조 경로 표현 — L2.
        restructuring_year: 재구조화 시점 (0=재구조화 없음, 1~운영기간)
        equity_recovery_method: 자기자본 회수 방법 (BTL 표준 3가지, KDB 자료)
            '회수안함'   : 자기자본을 회수하지 않고 타인자본 금리에 더해서 상환
            '원금만'     : 사업기간 만료시 원금만 회수
            '원금+수익률': 원금에 일정 수익률을 더해서 회수 (기본값)
        debt_repayment_method: 타인자본 회수 방법 (KDB 자료 3가지)
            '원리금균등'  : 매년 원리금 합계 일정 (기본값, 표준)
            '원리금불균등': 운영 후반에 원리금 부담 가중 (대주단 회수 가속)
            '기간조정'    : 타인자본 대출기간 단축 (운영기간보다 짧음, 후반 자기자본 회수)
    """
    # ★ 방어 코드: kwargs 중복 키 제거
    for key in ['discount_rate', 'inflation', 'growth_rate',
                'capex_억', 'annual_revenue_억', 'opex_series_억',
                'construction_years', 'operation_years', 'opex_ratio',
                'equity_ratio', 'debt_rate',
                'business_type', 'mrg_ratio', 'mcc_ratio', 'restructuring_year',
                'mrg_years', 'forecast_revenue_억', 'revenue_series_억',
                'equity_recovery_method', 'debt_repayment_method']:
        kwargs.pop(key, None)

    total_years = construction_years + operation_years
    years = np.arange(0, total_years + 1)

    # 건설기간 CAPEX 분배 (S-curve)
    capex_schedule = np.zeros(total_years + 1)
    if construction_years > 0:
        for y in range(1, construction_years + 1):
            # S-curve 배분
            t = y / construction_years
            w = 3 * t**2 - 2 * t**3  # S-curve weight
            capex_schedule[y] = capex_억 * (w - (3*((y-1)/construction_years)**2 - 2*((y-1)/construction_years)**3))
        # 잔여분 보정
        remainder = capex_억 - capex_schedule.sum()
        capex_schedule[construction_years] += remainder

    # 운영기간 수익 (재구조화 반영)
    revenue = np.zeros(total_years + 1)
    opex = np.zeros(total_years + 1)
    mrg_subsidy = np.zeros(total_years + 1)  # MRG 보전금 (BTO-rs 등 수요 위험 분담)
    mcc_subsidy = np.zeros(total_years + 1)  # MCC 비용보전금 (BTO-a 등 운영비 정부 보전)
    
    for y in range(construction_years + 1, total_years + 1):
        op_year = y - construction_years
        rev_growth = (1 + growth_rate) ** (op_year - 1)
        infl_factor = (1 + inflation) ** (op_year - 1)
        
        # 재구조화 후 통행료 조정 (재구조화 시 통행료 -10% 가정)
        toll_adj = 1.0
        if restructuring_year > 0 and op_year >= restructuring_year:
            toll_adj = 0.90
        
        # L2: 실현 수입 시계열이 주어지면 스칼라×성장률 대신 직접 사용 (램프업·단차 표현)
        if revenue_series_억 is not None and op_year - 1 < len(revenue_series_억):
            revenue[y] = float(revenue_series_억[op_year - 1]) * toll_adj
        else:
            revenue[y] = annual_revenue_억 * rev_growth * toll_adj

        # OPEX — revenue와 동일 basis(성장 반영, 인플레 미적용)로 일치시킴.
        #   ※ 버그수정: estimate_opex_series 시계열은 이미 성장(growth)을 반영하므로
        #     여기서 infl_factor를 또 곱하면 revenue(성장만) 대비 OPEX만 인플레만큼
        #     매년 부풀려져 말년에 OPEX>매출 → CFADS 음수(DSCR_min 음수·LLCR<1) 아티팩트 발생.
        if opex_series_억 is not None and op_year - 1 < len(opex_series_억):
            opex[y] = opex_series_억[op_year - 1]
        else:
            opex[y] = annual_revenue_억 * opex_ratio * rev_growth
        
        # MRG 보전금 (수요 위험 — BTO-rs, BTO-ann)
        # 협약 추정수입(통행료 조정 전) 대비 mrg_ratio를 floor로 보장.
        # 실제(재구조화 통행료 인하 등 반영) 수입이 floor 미만이면 정부가 차액을 보전한다.
        # L1: floor 기준은 forecast_revenue_억(협약 추정수입) — 실현 시나리오와 분리.
        #   미지정 시 annual_revenue_억(종전 동작: 입력수입=협약수입 가정).
        # L4: 보장기간(mrg_years)을 넘긴 연차는 보전 없음 (0 = 전체 기간, 하위호환).
        if mrg_ratio > 0 and (mrg_years <= 0 or op_year <= mrg_years):
            _base_forecast = forecast_revenue_억 if forecast_revenue_억 is not None else annual_revenue_억
            forecast_rev = _base_forecast * rev_growth  # 협약 추정수입(통행료 조정 전)
            guarantee_floor = forecast_rev * mrg_ratio
            if revenue[y] < guarantee_floor:
                mrg_subsidy[y] = guarantee_floor - revenue[y]
                revenue[y] = guarantee_floor

        # MCC 비용보전 (운영비 정부 보전 — BTO-a/BTL의 운영비 가용성 지급)
        # 정부가 운영비의 mcc_ratio만큼을 보전(매출에 가산). 변수 정의와 일치하도록 단순화.
        if mcc_ratio > 0:
            mcc_subsidy[y] = opex[y] * mcc_ratio
            revenue[y] += mcc_subsidy[y]

    # 금융 구조
    debt_amount = capex_억 * (1 - equity_ratio)
    equity_amount = capex_억 * equity_ratio
    
    # 원리금 상환 로직 (보완 7 — KDB 자료 기반 3가지 방법)
    interest_payment = np.zeros(total_years + 1)
    principal_payment = np.zeros(total_years + 1)
    debt_balance = np.zeros(total_years + 1)
    
    # 건설기간 이자(IDC) 자본화: 인출 잔액에 이자를 누적해 부채원금에 가산.
    # IDC는 통상 차입 facility에서 인출되므로 전액 부채로 자본화한다(자기자본 불변).
    idc_total = 0.0
    for y in range(1, construction_years + 1):
        drawn = sum(capex_schedule[1:y+1]) * (1 - equity_ratio)
        idc_total += drawn * debt_rate
        debt_balance[y] = drawn + idc_total
    debt_amount = debt_amount + idc_total
    debt_balance[construction_years] = debt_amount
    
    if debt_repayment_method == "원리금균등":
        # 표준 방식: 매년 원리금 합계 일정 (annuity)
        if debt_rate > 0 and operation_years > 0:
            annuity_factor = debt_rate * (1 + debt_rate) ** operation_years / ((1 + debt_rate) ** operation_years - 1)
            annual_payment = debt_amount * annuity_factor
        else:
            annual_payment = debt_amount / operation_years if operation_years > 0 else 0
        
        for y in range(construction_years + 1, total_years + 1):
            prev_balance = debt_balance[y - 1]
            interest_payment[y] = prev_balance * debt_rate
            principal_payment[y] = min(annual_payment - interest_payment[y], prev_balance)
            principal_payment[y] = max(0, principal_payment[y])
            debt_balance[y] = max(0, prev_balance - principal_payment[y])
    
    elif debt_repayment_method == "원리금불균등":
        # 후반 가중 방식: 원금 상환을 후반에 집중 (대주단 회수 가속)
        # 운영 1/3 시점까지는 원금의 20%, 2/3 시점까지 30%, 마지막 1/3 50% 상환
        if operation_years > 0:
            third = max(1, operation_years // 3)
            schedule = []
            for op_y in range(1, operation_years + 1):
                if op_y <= third:
                    weight = 0.20 / third
                elif op_y <= 2 * third:
                    weight = 0.30 / third
                else:
                    weight = 0.50 / (operation_years - 2 * third)
                schedule.append(debt_amount * weight)
            
            for idx, y in enumerate(range(construction_years + 1, total_years + 1)):
                if idx >= len(schedule):
                    break
                prev_balance = debt_balance[y - 1]
                interest_payment[y] = prev_balance * debt_rate
                principal_payment[y] = min(schedule[idx], prev_balance)
                debt_balance[y] = max(0, prev_balance - principal_payment[y])
    
    else:  # "기간조정" — 타인자본 상환기간을 운영기간보다 짧게 (예: 70%)
        # 후반은 부채 없이 자기자본 회수 집중
        repayment_period = max(5, int(operation_years * 0.7))
        annual_principal = debt_amount / repayment_period
        
        for idx, y in enumerate(range(construction_years + 1, total_years + 1)):
            prev_balance = debt_balance[y - 1]
            interest_payment[y] = prev_balance * debt_rate
            if idx < repayment_period:
                principal_payment[y] = min(annual_principal, prev_balance)
            else:
                principal_payment[y] = 0  # 상환 완료 후 부담 없음
            debt_balance[y] = max(0, prev_balance - principal_payment[y])

    # 감가상각 (정액법, 운영기간에 걸쳐 CAPEX 상각) — 세금방패 반영
    depreciation = np.zeros(total_years + 1)
    if operation_years > 0:
        annual_dep = capex_억 / operation_years
        for y in range(construction_years + 1, total_years + 1):
            depreciation[y] = annual_dep

    # 세금 (법인세)
    tax_rate = kwargs.get('tax_rate', 0.22)
    # 레버드 세금 — 과세소득 = 매출 − 운영비 − 이자 − 감가상각 (당기순이익·DSCR·CFADS 용)
    ebt = revenue - opex - interest_payment - depreciation
    tax = np.maximum(0, ebt * tax_rate)
    net_income = ebt - tax
    # 언레버드 세금 — 프로젝트 FCFF는 자본구조와 무관해야 하므로 이자 차감 없이 과세
    #   (이자 세금방패는 할인율 WACC의 Kd(1−t)에 이미 반영 → 여기서 또 빼면 이중계상)
    ebit = revenue - opex - depreciation
    tax_unlevered = np.maximum(0, ebit * tax_rate)

    # 프로젝트 FCF (세후, FCFF 기준 — 언레버드 세금 적용)
    project_fcf = np.zeros(total_years + 1)
    project_fcf[0] = 0
    for y in range(1, total_years + 1):
        if y <= construction_years:
            project_fcf[y] = -capex_schedule[y]
        else:
            project_fcf[y] = revenue[y] - opex[y] - tax_unlevered[y]

    # 자기자본 FCF (FCFE = 당기순이익 + 감가상각 − 원금상환)
    #  만기 회수액은 '만기 잔존가치(terminal value)'라는 실제 현금흐름에서만 나온다.
    #  잔존가치가 0이면 무에서 현금을 만들 수 없으므로 회수액도 0 (이전: 출처 없는 환상 현금).
    equity_fcf = np.zeros(total_years + 1)
    for y in range(1, total_years + 1):
        if y <= construction_years:
            equity_fcf[y] = -capex_schedule[y] * equity_ratio
        else:
            equity_fcf[y] = net_income[y] + depreciation[y] - principal_payment[y]

    terminal_value = float(kwargs.get('terminal_value_억', 0.0))
    residual_debt = debt_balance[total_years] if total_years < len(debt_balance) else 0.0
    # 만기 잔존가치는 잔존부채를 먼저 상환한 뒤 남는 부분만 자기자본이 회수 가능
    terminal_to_equity_avail = max(0.0, terminal_value - residual_debt)

    equity_recovery_at_end = 0.0  # 사업 만료 시 추가 회수액 (잔존가치 한도 내)
    if equity_recovery_method == "회수안함":
        equity_recovery_at_end = 0.0
    elif equity_recovery_method == "원금만":
        equity_recovery_at_end = min(equity_amount, terminal_to_equity_avail)
    else:  # "원금+수익률"
        equity_recovery_at_end = min(equity_amount * 1.05, terminal_to_equity_avail)
    equity_fcf[total_years] += equity_recovery_at_end

    # 프로젝트 FCFF에도 만기 잔존가치 반영 (부채 상환 전 총가치)
    project_fcf[total_years] += terminal_value

    # NPV 계산
    discount_factors = np.array([1 / (1 + discount_rate)**t for t in years])
    npv = np.sum(project_fcf * discount_factors)

    # IRR 계산 (Newton-Raphson)
    def calc_irr(cashflows, guess=0.08):
        rate = guess
        for _ in range(200):
            npv_val = sum(cf / (1 + rate)**t for t, cf in enumerate(cashflows))
            dnpv = sum(-t * cf / (1 + rate)**(t+1) for t, cf in enumerate(cashflows))
            if abs(dnpv) < 1e-12:
                break
            new_rate = rate - npv_val / dnpv
            if abs(new_rate - rate) < 1e-8:
                return new_rate
            rate = new_rate
            if abs(rate) > 1.0:
                return float('nan')
        return rate

    nominal_irr = calc_irr(project_fcf.tolist())
    
    # 불변 IRR (인플레이션 제거)
    real_irr = (1 + nominal_irr) / (1 + inflation) - 1 if not math.isnan(nominal_irr) else float('nan')
    
    # 자기자본 IRR
    equity_irr = calc_irr(equity_fcf.tolist())

    # 협약 기준 사업수익률 (실질·세전) — 한국 민자 실시협약의 핵심 지표.
    #   세전 사업FCF(매출−운영비−CAPEX, 세금 전)의 IRR을 물가로 디플레이트.
    #   세후 실질은 real_irr로 병기.
    pretax_project_fcf = np.zeros(total_years + 1)
    for _y in range(1, total_years + 1):
        pretax_project_fcf[_y] = (-capex_schedule[_y] if _y <= construction_years
                                  else revenue[_y] - opex[_y])
    pretax_irr = calc_irr(pretax_project_fcf.tolist())
    agreed_return_real_pretax = ((1 + pretax_irr) / (1 + inflation) - 1
                                 if not math.isnan(pretax_irr) else float('nan'))

    # MIRR (수정 IRR) — 재투자율=할인율, 조달율=부채금리. IRR의 재투자·복수해 결함 교정.
    def calc_mirr(cashflows, finance_rate, reinvest_rate):
        cfs = [float(c) for c in cashflows]
        n = len(cfs) - 1
        if n <= 0:
            return float('nan')
        fv_pos = sum(cf * (1 + reinvest_rate) ** (n - t) for t, cf in enumerate(cfs) if cf > 0)
        pv_neg = sum(cf / (1 + finance_rate) ** t for t, cf in enumerate(cfs) if cf < 0)
        if pv_neg == 0 or fv_pos <= 0:
            return float('nan')
        return (fv_pos / (-pv_neg)) ** (1 / n) - 1
    project_mirr = calc_mirr(project_fcf.tolist(), debt_rate, discount_rate)
    equity_mirr = calc_mirr(equity_fcf.tolist(), debt_rate, discount_rate)

    # DSCR (연도별) — CFADS(세후 영업현금 = 매출 − 운영비 − 세금) ÷ 원리금
    dscr_arr = np.zeros(total_years + 1)
    for y in range(construction_years + 1, total_years + 1):
        ds = interest_payment[y] + principal_payment[y]
        if ds > 0:
            dscr_arr[y] = (revenue[y] - opex[y] - tax[y]) / ds
    
    op_dscr = dscr_arr[construction_years + 1: total_years + 1]
    dscr_min = np.min(op_dscr) if len(op_dscr) > 0 else 0
    dscr_avg = np.mean(op_dscr) if len(op_dscr) > 0 else 0

    # ROE
    avg_equity = equity_amount if equity_amount > 0 else 1
    avg_net_income = np.mean(net_income[construction_years+1:]) if operation_years > 0 else 0
    roe = avg_net_income / avg_equity

    # B/C ratio
    pv_benefits = np.sum(revenue * discount_factors)
    pv_costs = np.sum((capex_schedule + opex) * discount_factors)
    bc_ratio = pv_benefits / pv_costs if pv_costs > 0 else 0

    # EBITDA (영업이익 + 감가상각 ≈ 매출 − 운영비) — 대주단 표준 현금흐름 대용
    ebitda = revenue - opex

    # LLCR (Loan Life Coverage Ratio) — 잔여 대출기간 CFADS 현가 ÷ 잔존부채
    # CFADS = 매출 − 운영비 − 세금 (DSCR 분자와 동일 정의)
    cfads = revenue - opex - tax
    # 대출 만기연도(잔존부채가 사실상 0이 되는 시점) — LLCR은 만기까지, PLCR은 사업종료까지
    loan_maturity = total_years
    for _y in range(total_years, construction_years, -1):
        if debt_balance[_y] > 1e-6:
            loan_maturity = _y
            break
    llcr_arr = np.zeros(total_years + 1)   # 잔여 대출기간 CFADS 현가 ÷ 잔존부채
    plcr_arr = np.zeros(total_years + 1)   # 사업 잔여 전기간 CFADS 현가 ÷ 잔존부채 (≥ LLCR)
    for y in range(construction_years + 1, total_years + 1):
        if debt_balance[y] > 1e-9:
            idx_ll = np.arange(y, max(y, loan_maturity) + 1)
            llcr_arr[y] = np.sum(cfads[idx_ll] / (1 + debt_rate) ** (idx_ll - y)) / debt_balance[y]
            idx_pl = np.arange(y, total_years + 1)
            plcr_arr[y] = np.sum(cfads[idx_pl] / (1 + debt_rate) ** (idx_pl - y)) / debt_balance[y]
    op_llcr = llcr_arr[construction_years + 1: total_years + 1]
    op_llcr_pos = op_llcr[op_llcr > 0]
    llcr_min = float(np.min(op_llcr_pos)) if len(op_llcr_pos) > 0 else 0.0
    llcr_avg = float(np.mean(op_llcr_pos)) if len(op_llcr_pos) > 0 else 0.0
    op_plcr = plcr_arr[construction_years + 1: total_years + 1]
    op_plcr_pos = op_plcr[op_plcr > 0]
    plcr_min = float(np.min(op_plcr_pos)) if len(op_plcr_pos) > 0 else 0.0
    ebitda_avg = float(np.mean(ebitda[construction_years + 1:])) if operation_years > 0 else 0.0

    # 선순위 전용 DSCR (overlay) — 선순위 트랜치를 독립 annuity(선순위 금리)로 모델링한 커버리지.
    # 본 현금흐름은 가중평균 금리 기준이며, 이는 '선순위 채무 상환 우선권' 관점의 분석용 overlay다.
    # 선순위 채무상환액 < 전체 채무상환액 이므로 선순위 DSCR ≥ 블렌디드 DSCR.
    senior_ratio = float(kwargs.get('senior_ratio', 1.0))
    senior_rate = float(kwargs.get('senior_rate', debt_rate))
    senior_dscr_arr = np.zeros(total_years + 1)
    if 0 < senior_ratio <= 1.0 and operation_years > 0:
        sr_balance = debt_amount * senior_ratio
        if senior_rate > 0:
            sr_af = senior_rate * (1 + senior_rate) ** operation_years / ((1 + senior_rate) ** operation_years - 1)
            sr_payment = sr_balance * sr_af
        else:
            sr_payment = sr_balance / operation_years
        for y in range(construction_years + 1, total_years + 1):
            sr_int = sr_balance * senior_rate
            sr_prin = max(0.0, min(sr_payment - sr_int, sr_balance))
            sr_ds = sr_int + sr_prin
            if sr_ds > 0:
                senior_dscr_arr[y] = (revenue[y] - opex[y] - tax[y]) / sr_ds
            sr_balance = max(0.0, sr_balance - sr_prin)
    op_sr = senior_dscr_arr[construction_years + 1: total_years + 1]
    op_sr_pos = op_sr[op_sr > 0]
    senior_dscr_min = float(np.min(op_sr_pos)) if len(op_sr_pos) > 0 else 0.0
    senior_dscr_avg = float(np.mean(op_sr_pos)) if len(op_sr_pos) > 0 else 0.0

    # DataFrame 구축
    cf_df = pd.DataFrame({
        'Year': years,
        'CAPEX': -capex_schedule,
        'Revenue': revenue,
        'OPEX': -opex,
        'MRG_Subsidy': mrg_subsidy,
        'MCC_Subsidy': mcc_subsidy,
        'Interest': -interest_payment,
        'Principal': -principal_payment,
        'Depreciation': -depreciation,
        'Tax': -tax,
        'NetIncome': net_income,
        'EBITDA': ebitda,
        'SeniorDSCR': senior_dscr_arr,
        'ProjectFCF': project_fcf,
        'EquityFCF': equity_fcf,
        'CumProjectFCF': np.cumsum(project_fcf),
        'DebtBalance': debt_balance,
        'DSCR': dscr_arr,
        'LLCR': llcr_arr,
        'DiscountFactor': discount_factors,
        'PV_FCF': project_fcf * discount_factors,
    })

    metrics = {
        'npv': npv,
        'nominal_irr': nominal_irr,
        'real_irr': real_irr,
        'agreed_return_real_pretax': agreed_return_real_pretax,  # 협약 기준 사업수익률(실질·세전)
        'equity_irr': equity_irr,
        'project_mirr': project_mirr,
        'equity_mirr': equity_mirr,
        'plcr_min': plcr_min,
        'roe': roe,
        'dscr_min': dscr_min,
        'dscr_avg': dscr_avg,
        'senior_dscr_min': senior_dscr_min,
        'senior_dscr_avg': senior_dscr_avg,
        'llcr_min': llcr_min,
        'llcr_avg': llcr_avg,
        'ebitda_avg': ebitda_avg,
        'bc_ratio': bc_ratio,
        'total_revenue': revenue.sum(),
        'total_opex': opex.sum(),
        'total_interest': interest_payment.sum(),
        'total_mrg_subsidy': mrg_subsidy.sum(),
        'total_mcc_subsidy': mcc_subsidy.sum(),
        'total_govt_burden': mrg_subsidy.sum() + mcc_subsidy.sum(),
        'payback_year': None,
    }

    # Payback period
    cum_fcf = np.cumsum(project_fcf)
    payback_idx = np.where(cum_fcf >= 0)[0]
    if len(payback_idx) > 0:
        metrics['payback_year'] = int(payback_idx[0])

    return cf_df, metrics


def build_pimac_standard_table(cf_df: pd.DataFrame) -> pd.DataFrame:
    """엔진 현금흐름을 KDI PIMAC 표준재무모델 연도별 양식으로 매핑.

    표준 .xlsx에 그대로 붙여넣을 수 있도록 한국어 컬럼·부호 규약(지출=양수 투자비)으로
    재구성한다. 6개 독립 주체가 같은 표준 양식으로 결과를 대조할 수 있게 하는 정합 레이어.
    """
    dep = -cf_df['Depreciation']
    ebitda = cf_df['EBITDA']
    interest = -cf_df['Interest']
    tax = -cf_df['Tax']
    out = pd.DataFrame({
        '연차': cf_df['Year'].astype(int),
        '투자비(억)': -cf_df['CAPEX'],
        '운영수입(억)': cf_df['Revenue'],
        '운영비용(억)': -cf_df['OPEX'],
        '정부보조MRG+MCC(억)': cf_df['MRG_Subsidy'] + cf_df['MCC_Subsidy'],
        'EBITDA(억)': ebitda,
        '감가상각비(억)': dep,
        '영업이익EBIT(억)': ebitda - dep,
        '이자비용(억)': interest,
        '세전이익(억)': cf_df['NetIncome'] + tax,
        '법인세(억)': tax,
        '당기순이익(억)': cf_df['NetIncome'],
        '부채원금상환(억)': -cf_df['Principal'],
        '부채잔액(억)': cf_df['DebtBalance'],
        '프로젝트현금흐름(억)': cf_df['ProjectFCF'],
        'DSCR': cf_df['DSCR'],
        '선순위DSCR': cf_df['SeniorDSCR'],
        'LLCR': cf_df['LLCR'],
    })
    return out.round(2)


def calc_wacc(equity_ratio, cost_of_equity, debt_rate, tax_rate=0.22):
    """WACC 계산 (단순 — 호환성 유지)"""
    debt_ratio = 1 - equity_ratio
    wacc = equity_ratio * cost_of_equity + debt_ratio * debt_rate * (1 - tax_rate)
    return wacc


def calc_wacc_detail(rf, mrp, beta, equity_ratio, debt_rate, tax_rate=0.22,
                      senior_ratio=0.7, senior_rate=None, sub_rate=None, ke=None):
    """
    CAPM 기반 WACC 상세 계산 — 선순위/후순위 부채 구조 반영
    
    실무 자금구조:
        - 자기자본 (equity_ratio %)
        - 선순위채 ((1-equity)*senior_ratio %, 낮은 금리)
        - 후순위채 ((1-equity)*(1-senior_ratio) %, 높은 금리)
    
    Parameters
    ----------
    senior_ratio : float
        타인자본 중 선순위채 비중 (기본 70%)
    senior_rate : float or None
        선순위 금리. None이면 debt_rate 사용 (단순 모드)
    sub_rate : float or None  
        후순위 금리. None이면 debt_rate + 1.5% 사용
    """
    # 사용자가 자기자본비용(Ke)을 직접 지정하면 그 값을 사용, 없으면 CAPM(rf+β·MRP)으로 산출
    if ke is None:
        ke = rf + beta * mrp
    debt_ratio = 1 - equity_ratio
    
    # 선순위/후순위 금리 자동 설정 (사용자 미입력 시)
    if senior_rate is None:
        senior_rate = debt_rate
    if sub_rate is None:
        sub_rate = debt_rate + 0.015  # 후순위는 선순위 대비 +1.5% (시장 통념)
    
    sub_ratio = 1 - senior_ratio
    
    # 가중평균 타인자본 비용
    weighted_kd = senior_ratio * senior_rate + sub_ratio * sub_rate
    
    # WACC = E·Ke + D·Kd(1-t)
    wacc = equity_ratio * ke + debt_ratio * weighted_kd * (1 - tax_rate)
    
    return {
        'ke': ke,
        'kd': weighted_kd,
        'senior_rate': senior_rate,
        'sub_rate': sub_rate,
        'senior_ratio': senior_ratio,
        'sub_ratio': sub_ratio,
        'wacc': wacc,
        'equity_weight': equity_ratio,
        'debt_weight': debt_ratio,
        'senior_weight': debt_ratio * senior_ratio,
        'sub_weight': debt_ratio * sub_ratio,
        'tax_rate': tax_rate, 'rf': rf, 'mrp': mrp, 'beta': beta,
    }


# ════════════════════════════════════════════════════════════
# [MONTE CARLO] 시뮬레이션 엔진 (discount_rate 버그 수정 완료)
# ════════════════════════════════════════════════════════════

def monte_carlo(
    capex_억: float,
    annual_revenue_억: float,
    n_sim: int = 1000,
    discount_rate: float = 0.05,
    inflation: float = 0.02,
    growth_rate: float = 0.02,
    **kwargs,
):
    """
    Monte Carlo NPV 시뮬레이션
    
    ★ FIX: discount_rate 중복 전달 버그 수정
    kwargs에서 build_cashflow의 명시적 인자와 중복되는 키를 제거
    """
    # ★ 핵심 수정: 명시적 인자 키를 kwargs에서 제거
    EXPLICIT_KEYS = {
        'discount_rate', 'inflation', 'growth_rate',
        'capex_억', 'annual_revenue_억',
        'n_sim',
    }
    build_kwargs = {k: v for k, v in kwargs.items() if k not in EXPLICIT_KEYS}

    npv_results = []
    irr_results = []
    dscr_results = []
    roe_results = []

    # 변동성 파라미터
    capex_vol = kwargs.get('capex_volatility', 0.10)
    revenue_vol = kwargs.get('revenue_volatility', 0.15)
    rate_vol = kwargs.get('rate_volatility', 0.10)
    cost_vol = kwargs.get('cost_volatility', 0.08)

    for i in range(n_sim):
        # 확률적 변동 적용
        sc = capex_억 * np.random.lognormal(0, capex_vol)
        sr = annual_revenue_억 * np.random.lognormal(0, revenue_vol)
        sd = max(0.001, discount_rate * np.random.lognormal(0, rate_vol))
        si = inflation * np.random.uniform(0.5, 1.5)
        sg = growth_rate * np.random.uniform(0.5, 1.5)

        try:
            # ★ 수정된 호출: **build_kwargs 사용 (중복 키 없음)
            cf, met = build_cashflow(
                capex_억=sc,
                annual_revenue_억=sr,
                discount_rate=sd,
                inflation=si,
                growth_rate=sg,
                **build_kwargs,
            )
            npv_results.append(met['npv'])
            if not math.isnan(met['nominal_irr']):
                irr_results.append(met['nominal_irr'])
            dscr_results.append(met['dscr_min'])
            roe_results.append(met['roe'])
        except Exception:
            continue

    npv_arr = np.array(npv_results) if npv_results else np.array([0])
    irr_arr = np.array(irr_results) if irr_results else np.array([0])
    dscr_arr = np.array(dscr_results) if dscr_results else np.array([0])

    return {
        'npv': npv_arr,
        'irr': irr_arr,
        'dscr': dscr_arr,
        'roe': np.array(roe_results) if roe_results else np.array([0]),
        'npv_mean': float(np.mean(npv_arr)),
        'npv_std': float(np.std(npv_arr)),
        'npv_p5': float(np.percentile(npv_arr, 5)),
        'npv_p95': float(np.percentile(npv_arr, 95)),
        'irr_mean': float(np.mean(irr_arr)),
        'dscr_mean': float(np.mean(dscr_arr)),
        'prob_negative_npv': float(np.mean(npv_arr < 0)),
        'prob_dscr_below_1': float(np.mean(dscr_arr < 1.0)),
        'n_success': len(npv_results),
        'n_sim': n_sim,
    }


def tornado_analysis(base_params: dict, variation: float = 0.2):
    """토네이도 민감도 분석"""
    _, base_met = build_cashflow(**base_params)
    base_npv = base_met['npv']

    results = []
    sensitive_params = {
        '총사업비(억)': 'capex_억',
        '연간수익(억)': 'annual_revenue_억',
        '할인율': 'discount_rate',
        '물가상승률': 'inflation',
        '성장률': 'growth_rate',
        'OPEX비율': 'opex_ratio',
        '자기자본비율': 'equity_ratio',
        '차입금리': 'debt_rate',
    }

    has_opex_series = base_params.get('opex_series_억') is not None

    for label, param_key in sensitive_params.items():
        if param_key not in base_params:
            continue
        # OPEX비율은 opex_series_억가 있으면 무시되므로(시계열 우선), 시계열 자체를 스케일
        scale_opex_series = (param_key == 'opex_ratio' and has_opex_series)
        if not scale_opex_series:
            base_val = base_params[param_key]
            if base_val == 0:
                continue

        high_params = base_params.copy()
        low_params = base_params.copy()
        if scale_opex_series:
            series = np.asarray(base_params['opex_series_억'], dtype=float)
            high_params['opex_series_억'] = series * (1 + variation)
            low_params['opex_series_억'] = series * (1 - variation)
        else:
            high_params[param_key] = base_val * (1 + variation)
            low_params[param_key] = base_val * (1 - variation)

        _, high_met = build_cashflow(**high_params)
        _, low_met = build_cashflow(**low_params)

        results.append({
            'param': label,
            'low_npv': low_met['npv'],
            'high_npv': high_met['npv'],
            'spread': abs(high_met['npv'] - low_met['npv']),
            'base_npv': base_npv,
        })

    results.sort(key=lambda x: x['spread'], reverse=True)
    return results


# ════════════════════════════════════════════════════════════
# [ECOS] 한국은행 기준금리 자동연동
# ════════════════════════════════════════════════════════════

class ECOSConnector:
    """한국은행 ECOS API 연동"""
    BASE_URL = "https://ecos.bok.or.kr/api"
    
    STAT_CODES = {
        "base_rate": ("722Y001", "0101000"),
        "gov_bond_3y": ("817Y002", "010200000"),
        "gov_bond_5y": ("817Y002", "010200001"),
        "gov_bond_10y": ("817Y002", "010210000"),
        "gov_bond_30y": ("817Y002", "010230000"),
        "cd_91d": ("721Y001", None),
        "cpi": ("901Y009", "0"),
    }

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("ECOS_API_KEY", "")

    def _fetch(self, stat_code, item_code=None, period="M", months_back=6):
        try:
            import requests
        except ImportError:
            return None
        
        if not self.api_key:
            return None

        today = datetime.date.today()
        end_date = today.strftime("%Y%m")
        start_date = (today - datetime.timedelta(days=30 * months_back)).strftime("%Y%m")

        url = (f"{self.BASE_URL}/StatisticSearch/{self.api_key}/json/kr/"
               f"1/20/{stat_code}/{period}/{start_date}/{end_date}")
        if item_code:
            url += f"/{item_code}"

        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if "StatisticSearch" in data and "row" in data["StatisticSearch"]:
                rows = data["StatisticSearch"]["row"]
                latest = rows[-1]
                return {
                    'value': float(latest.get("DATA_VALUE", 0)),
                    'date': latest.get("TIME", ""),
                    'name': latest.get("STAT_NAME", ""),
                }
        except Exception:
            pass
        return None

    def get_all_rates(self) -> Dict:
        """모든 주요 금리 조회"""
        results = {}
        for key, (stat, item) in self.STAT_CODES.items():
            data = self._fetch(stat, item)
            if data:
                results[key] = data
        return results

    def auto_update_params(self) -> Dict:
        """WACC 파라미터 자동 갱신"""
        params = {}
        rates = self.get_all_rates()
        
        if 'gov_bond_10y' in rates:
            params['rf'] = rates['gov_bond_10y']['value'] / 100
        if 'base_rate' in rates:
            params['base_rate'] = rates['base_rate']['value'] / 100
            params['suggested_kd'] = rates['base_rate']['value'] / 100 + 0.015
        if 'cpi' in rates:
            params['inflation'] = rates['cpi']['value'] / 100

        params['updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        params['raw'] = rates
        return params


# ════════════════════════════════════════════════════════════
# [BIM] 재료 추출 & 열화곡선 프레임워크
# ════════════════════════════════════════════════════════════

class MaterialCategory(Enum):
    CONCRETE = "콘크리트"
    REBAR = "철근"
    STEEL = "강재"
    ASPHALT = "아스팔트"
    AGGREGATE = "골재"
    GUARDRAIL = "가드레일"
    BEARING = "교량받침"
    EXPANSION_JOINT = "신축이음"
    WATERPROOF = "방수재"
    PAINT = "도장재"
    DRAINAGE = "배수시설"
    LIGHTING = "조명시설"
    UNKNOWN = "미분류"


# 열화곡선 모델
DETERIORATION_MODELS = {
    MaterialCategory.ASPHALT: {"type": "linear", "rate": 5.0, "life": 20},
    MaterialCategory.CONCRETE: {"type": "weibull", "shape": 2.5, "scale": 50, "life": 50},
    MaterialCategory.STEEL: {"type": "exponential", "k": 0.02, "life": 40},
    MaterialCategory.REBAR: {"type": "exponential", "k": 0.015, "life": 50},
    MaterialCategory.BEARING: {"type": "weibull", "shape": 3.0, "scale": 25, "life": 25},
    MaterialCategory.EXPANSION_JOINT: {"type": "weibull", "shape": 2.0, "scale": 15, "life": 15},
    MaterialCategory.GUARDRAIL: {"type": "linear", "rate": 3.3, "life": 30},
    MaterialCategory.PAINT: {"type": "linear", "rate": 10.0, "life": 10},
    MaterialCategory.WATERPROOF: {"type": "weibull", "shape": 2.0, "scale": 20, "life": 20},
    MaterialCategory.DRAINAGE: {"type": "linear", "rate": 2.5, "life": 40},
    MaterialCategory.LIGHTING: {"type": "linear", "rate": 6.7, "life": 15},
}

# 표준품셈 2026 기반 단가 (원/단위)
STANDARD_COSTS_2026 = {
    MaterialCategory.ASPHALT: 80_000,        # 원/㎥
    MaterialCategory.CONCRETE: 135_000,       # 원/㎥
    MaterialCategory.STEEL: 2_350_000,        # 원/ton
    MaterialCategory.REBAR: 950_000,          # 원/ton
    MaterialCategory.BEARING: 5_000_000,      # 원/개
    MaterialCategory.EXPANSION_JOINT: 3_500_000,  # 원/m
    MaterialCategory.GUARDRAIL: 45_000,       # 원/m
    MaterialCategory.PAINT: 15_000,           # 원/㎡
    MaterialCategory.WATERPROOF: 25_000,      # 원/㎡
    MaterialCategory.DRAINAGE: 80_000,        # 원/m
    MaterialCategory.LIGHTING: 2_000_000,     # 원/기
}


def performance_index(model_info: dict, age: float) -> float:
    """열화곡선에 따른 성능지수 (PI: 0~100)"""
    t = model_info["type"]
    if t == "linear":
        return max(0, 100 - model_info["rate"] * age)
    elif t == "exponential":
        return 100 * math.exp(-model_info["k"] * age)
    elif t == "weibull":
        return 100 * math.exp(-(age / model_info["scale"]) ** model_info["shape"])
    return 100


def generate_deterioration_data(years: int = 30):
    """전체 재료 열화곡선 데이터 생성"""
    data = []
    for cat, model in DETERIORATION_MODELS.items():
        for y in range(0, years + 1):
            pi = performance_index(model, y)
            data.append({
                'Year': y,
                'Material': cat.value,
                'PI': pi,
                'Life': model.get('life', 30),
            })
    return pd.DataFrame(data)


def quantities_from_road_length(road_length_km: float) -> dict:
    """도로 연장 기반 추정 물량(BIM 부재 시 폴백). {MaterialCategory: qty}."""
    return {
        MaterialCategory.ASPHALT: road_length_km * 1000 * 3.5 * 0.05 * 4,  # ㎥ (4차로, 5cm)
        MaterialCategory.CONCRETE: road_length_km * 50,    # ㎥ (교량 등)
        MaterialCategory.GUARDRAIL: road_length_km * 2000,  # m (양측)
        MaterialCategory.BEARING: int(road_length_km / 5) * 8,  # 개
        MaterialCategory.EXPANSION_JOINT: int(road_length_km / 5) * 20,  # m
        MaterialCategory.PAINT: road_length_km * 1000 * 8,  # ㎡
        MaterialCategory.LIGHTING: int(road_length_km * 20),  # 기
        MaterialCategory.DRAINAGE: road_length_km * 2000,   # m
    }


def bim_quantities_to_categories(extracted: dict) -> dict:
    """ifc_extract.extract_opex_quantities() 결과 → {MaterialCategory: qty}.
    카테고리명(문자열, 예 'CONCRETE') → MaterialCategory 매핑. 단위는 이미 일치(㎥/m/EA/ton)."""
    name_to_cat = {c.name: c for c in MaterialCategory}
    out = {}
    for cname, info in (extracted or {}).get("quantities", {}).items():
        cat = name_to_cat.get(cname)
        if cat is not None and float(info.get("qty", 0)) > 0:
            out[cat] = out.get(cat, 0.0) + float(info["qty"])
    return out


def estimate_lcc_from_quantities(quantities: dict, operation_years: int = 30,
                                 discount_rate: float = 0.045):
    """물량 dict({MaterialCategory: qty}) → (lcc_df, total_pv_억). 엔진 본체."""
    lcc_data = []
    total_pv = 0

    for cat, qty in quantities.items():
        if cat not in DETERIORATION_MODELS or cat not in STANDARD_COSTS_2026:
            continue
        model = DETERIORATION_MODELS[cat]
        unit_cost = STANDARD_COSTS_2026[cat]
        life = model.get('life', 30)

        for y in range(1, operation_years + 1):
            pi = performance_index(model, y % life if life > 0 else y)
            cost = 0
            action = ""

            if pi <= 20 or (life > 0 and y % life == 0 and y > 0):
                cost = unit_cost * qty * 1.0
                action = "교체"
            elif pi <= 40:
                cost = unit_cost * qty * 0.25
                action = "대보수"
            elif pi <= 60 and y % 5 == 0:
                cost = unit_cost * qty * 0.05
                action = "일상보수"

            if cost > 0:
                df = 1 / (1 + discount_rate) ** y
                pv = cost * df
                total_pv += pv
                lcc_data.append({
                    'Year': y, 'Material': cat.value,
                    'Action': action, 'Cost_억': cost / 1e8,
                    'PV_억': pv / 1e8,
                })

    return pd.DataFrame(lcc_data), total_pv / 1e8


def estimate_lcc_maintenance(road_length_km: float, operation_years: int = 30,
                              discount_rate: float = 0.045):
    """도로 시설물 LCC 기반 유지관리비 추정 (연장 기반 추정물량 폴백).
    BIM 물량이 있으면 estimate_lcc_from_quantities(bim_quantities_to_categories(...))를 직접 사용."""
    return estimate_lcc_from_quantities(
        quantities_from_road_length(road_length_km), operation_years, discount_rate)


def estimate_lcc_sawtooth_from_config(quantities: dict, operation_years: int = 30,
                                      discount_rate: float = 0.045):
    """[step2] config(별표5 주기·수선율)로 톱니파형 LCC 산출.
    {MaterialCategory: qty} → (lcc_df, total_pv_억). config 없으면 기존 PI엔진 폴백.
    전면교체(cycle_years, renewal_rate) + 부분수리(partial: 단주기·낮은 수선율) 이벤트를 연도에 배치."""
    try:
        import config_loader
        mats = config_loader.materials()
    except Exception:
        mats = {}
    if not mats:
        return estimate_lcc_from_quantities(quantities, operation_years, discount_rate)

    rows = []
    total_pv = 0.0
    for cat, qty in quantities.items():
        m = mats.get(cat.name)
        if not m or qty <= 0:
            continue
        unit = float(m.get("unit_cost_won", 0))
        T = int(m.get("cycle_years", 0) or 0)
        rho = float(m.get("renewal_rate", 1.0))
        partial = m.get("partial") or {}
        pT = int(partial.get("cycle_years", 0) or 0)
        pr = float(partial.get("rate", 0))
        for y in range(1, operation_years + 1):
            cost, action = 0.0, ""
            if T > 0 and y % T == 0:
                cost, action = unit * qty * rho, "전면교체"
            elif pT > 0 and y % pT == 0:
                cost, action = unit * qty * pr, "부분수리"
            if cost > 0:
                pv = cost / (1 + discount_rate) ** y
                total_pv += pv
                rows.append({'Year': y, 'Material': cat.value, 'Action': action,
                             'Cost_억': cost / 1e8, 'PV_억': pv / 1e8})
    return pd.DataFrame(rows), total_pv / 1e8


# ════════════════════════════════════════════════════════════
# [BENCHMARK] 감사보고서 기반 실적 벤치마크
# ════════════════════════════════════════════════════════════

BENCHMARKS = {
    "천안논산 (2025)": {
        "연장": 81.0, "운영개시": 2002, "잔여": 7,
        "영업수익": 2193, "통행료": 1004, "보조금": 1104,
        "영업비용": 923, "영업이익": 1270, "순이익": 1058,
        "차입금": 2126, "자본": 3264, "DSCR": 1.29,
        "이자비용": 374, "배당": 900,
    },
    "제이영동 (2025)": {
        "연장": 56.95, "운영개시": 2016, "잔여": 21,
        "영업수익": 907, "통행료": 651, "보조금": 162,
        "영업비용": 578, "영업이익": 329, "순이익": -531,
        "차입금": 8042, "자본": -2022, "DSCR": 0.31,
        "이자비용": 863, "배당": 0,
    },
}


# ════════════════════════════════════════════════════════════
# [TOLL MODEL] 통행료 수입 추정 모델
# ════════════════════════════════════════════════════════════

def estimate_toll_revenue(
    road_length_km: float,
    daily_traffic: int,
    toll_per_km: float,
    growth_rate: float = 0.025,
    heavy_vehicle_ratio: float = 0.30,
    heavy_vehicle_surcharge: float = 2.5,
    years: int = 30,
):
    """통행료 수입 연도별 추정"""
    data = []
    for y in range(1, years + 1):
        traffic = daily_traffic * (1 + growth_rate) ** (y - 1)
        light = traffic * (1 - heavy_vehicle_ratio)
        heavy = traffic * heavy_vehicle_ratio
        
        daily_rev = (light * toll_per_km * road_length_km +
                     heavy * toll_per_km * road_length_km * heavy_vehicle_surcharge)
        annual_rev = daily_rev * 365 / 1e8  # 억원
        
        data.append({
            'Year': y,
            'DailyTraffic': int(traffic),
            'Revenue_억': round(annual_rev, 1),
        })
    return pd.DataFrame(data)


# ════════════════════════════════════════════════════════════
# [STREAMLIT APP] 메인 UI
# ════════════════════════════════════════════════════════════

def linked_slider_input(label, min_v, max_v, default, step, key, fmt=None, help=None):
    """슬라이더(드래그)와 숫자 입력(키보드)을 한 값에 묶어 함께 노출한다.

    두 위젯은 master 세션 키를 공유하며, 둘 중 하나를 바꾸면 다른 쪽도 즉시 동기화된다.
    이렇게 하면 모드 전환 없이 드래그와 정밀 타이핑을 동시에 지원한다.
    """
    sk = f"_lk_{key}"
    if sk not in st.session_state:
        st.session_state[sk] = default

    def _from_slider():
        st.session_state[sk] = st.session_state[f"{key}_sl"]

    def _from_num():
        st.session_state[sk] = st.session_state[f"{key}_ni"]

    # 위젯 인스턴스화 전에 master 값으로 두 위젯 상태를 시드 → value= 미사용으로 경고 회피
    st.session_state[f"{key}_sl"] = st.session_state[sk]
    st.session_state[f"{key}_ni"] = st.session_state[sk]

    # 소제목(라벨) 옆에 숫자 입력칸을 두고, 그 아래 슬라이더를 전폭으로 배치
    hc1, hc2 = st.sidebar.columns([3, 2], vertical_alignment="center")
    hc1.markdown(f"**{label}**")
    hc2.number_input(
        label, min_value=min_v, max_value=max_v, step=step, key=f"{key}_ni",
        on_change=_from_num, label_visibility="collapsed", format=fmt, help=help,
    )
    st.sidebar.slider(
        label, min_v, max_v, step=step, key=f"{key}_sl",
        on_change=_from_slider, label_visibility="collapsed",
    )
    return st.session_state[sk]


# 사업 프리셋 — 핵심 입력 자동 채움(대표 예시값, 선택 후 자유 수정 가능)
PROJECT_PRESETS = {
    # 태안-안성: 총사업비 37,078억 = 민간투자 21,637 + 건설보조금 7,212 + 보상비 8,229 (PIMAC 적격성조사)
    # → Forenode capex = 민간투자비 21,637억. 통행료/성장률은 현행 민자 실측으로 보정.
    "태안-안성 (94.6km · BTO · 민간투자비)": {
        "business_type": "BTO", "road_length": 95, "total_capex": 21637,
        "construction_years": 6, "operation_years": 30, "daily_traffic": 30000,
        "bridge_ratio": 20, "tunnel_ratio": 7, "lanes": 4, "toll_per_km": 85,
        "growth": 1.5, "heavy_ratio": 30,
    },
    # 천안논산: 1세대 BTO+MRG(총사업비 15,953=민투 11,589). 통행료 '19년 47.9%↓(인하후 ≈61원/km)+정부보전.
    # → capex=민투비 11,589, MRG 보전은 모델상 위험분담(BTO-rs)으로 근사.
    "천안논산 (81km · BTO+MRG)": {
        "business_type": "BTO-rs", "road_length": 81, "total_capex": 11589,
        "construction_years": 5, "operation_years": 30, "daily_traffic": 45000,
        "bridge_ratio": 15, "tunnel_ratio": 8, "lanes": 4, "toll_per_km": 61,
        "growth": 1.5, "heavy_ratio": 27,
    },
    # 제이영동(광주~원주 제2영동): 순수 BTO·MRG 없음(부실, '18 순손실 457억). 운영 30년('16~'46).
    # 총사업비 15,978 → 민투비 ~12,000. 통행료 ≈78원/km.
    "제이영동 (57km · BTO · MRG없음)": {
        "business_type": "BTO", "road_length": 57, "total_capex": 12000,
        "construction_years": 5, "operation_years": 30, "daily_traffic": 35000,
        "bridge_ratio": 22, "tunnel_ratio": 30, "lanes": 4, "toll_per_km": 78,
        "growth": 1.0, "heavy_ratio": 25,
    },
    # 화성-안성: BTO-a(손익공유, 적격성'25.10 통과). 총사업비 20,725 → 민투비 ~13,000 추정. 교통량/통행료 미확정.
    "화성-안성 (45km · BTO-a · 예비)": {
        "business_type": "BTO-ann", "road_length": 45, "total_capex": 13000,
        "construction_years": 5, "operation_years": 30, "daily_traffic": 55000,
        "bridge_ratio": 15, "tunnel_ratio": 20, "lanes": 4, "toll_per_km": 100,
        "growth": 2.0, "heavy_ratio": 30,
    },
}
_BIZ_OPTIONS = ["BTO", "BTO-rs", "BTO-ann", "BTL", "BTO+BTL"]


def main():
    st.set_page_config(
        page_title="Forenode — 민자도로 수익성·적정성 검증",
        page_icon="🛣️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # CSS
    st.markdown("""
    <style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 14px 8px; border-radius: 12px; color: white;
        text-align: center; margin: 4px 0;
        display: flex; flex-direction: column; justify-content: space-between;
        min-height: 118px;
    }
    .metric-card.green { background: linear-gradient(135deg, #11998e, #38ef7d); }
    .metric-card.red { background: linear-gradient(135deg, #eb3349, #f45c43); }
    .metric-card.blue { background: linear-gradient(135deg, #2193b0, #6dd5ed); }
    .metric-card.orange { background: linear-gradient(135deg, #f7971e, #ffd200); }
    .metric-card h4 {
        margin: 0; font-size: 11.5px; line-height: 1.25; opacity: 0.92;
        min-height: 29px; display: flex; align-items: center; justify-content: center;
    }
    .metric-card h2 {
        margin: 6px 0 0; font-size: clamp(15px, 1.55vw, 23px); font-weight: 700;
        white-space: nowrap; letter-spacing: -0.3px;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px; border-radius: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── 사이드바 ──
    st.sidebar.title("⚙️ 시나리오 설정")

    # ─── 사업 프리셋 (핵심 입력 자동 채움) ───
    preset_choice = st.sidebar.selectbox(
        "📁 사업 프리셋 (자동 채움)",
        ["직접 입력"] + list(PROJECT_PRESETS.keys()), index=0,
        help="대표 사업을 고르면 핵심 입력(연장·사업비·교통량·기간·지형 등)이 자동으로 채워집니다. "
             "이후 자유롭게 수정 가능. (대표 예시값)",
    )
    _preset = PROJECT_PRESETS.get(preset_choice, {})
    # 프리셋 변경 시 linked 입력(연장·사업비·교통량)은 세션값으로 시드
    if preset_choice != st.session_state.get("_preset_applied"):
        for _k in ("road_length", "total_capex", "daily_traffic"):
            if _k in _preset:
                st.session_state[f"_lk_{_k}"] = _preset[_k]
        st.session_state["_preset_applied"] = preset_choice

    # ─── 사업 유형 (최상단, 다른 변수의 기본값을 결정) ───
    st.sidebar.subheader("📋 사업 유형")
    business_type = st.sidebar.selectbox(
        "사업 유형 선택",
        options=_BIZ_OPTIONS,
        index=_BIZ_OPTIONS.index(_preset.get("business_type", "BTO-ann")),
        help=(
            "BTO: 수익형 / BTO-rs: 위험분담형(Risk Sharing) / "
            "BTO-ann: 정부지급형(Annuity, BTO-a) / BTL: 임대형 / "
            "BTO+BTL: 결합형 (2024.10 정부 활성화 방안 신규)"
        )
    )
    
    # 사업유형별 기본값 매핑 (mcc 추가: BTO-a/BTL은 운영비 정부 보전 존재)
    # BTO+BTL: 2024.10 정부 활성화 방안 — 상부 BTO + 하부 BTL 결합
    _BIZ_DEFAULTS = {
        "BTO":     {"equity": 25, "opex": 30, "mrg": 0,   "mcc": 0,   "toll": 100, "desc": "수익형 — 운영 수익으로 회수 (정부 위험 분담 없음)"},
        "BTO-rs":  {"equity": 20, "opex": 32, "mrg": 50,  "mcc": 0,   "toll": 90,  "desc": "위험분담형 — 정부·사업자 수요위험 분담 (Risk Sharing)"},
        "BTO-ann": {"equity": 15, "opex": 35, "mrg": 90,  "mcc": 30,  "toll": 130, "desc": "정부지급형(BTO-a) — 운영비 일부 정부 보전 (Annuity)"},
        "BTL":     {"equity": 10, "opex": 40, "mrg": 100, "mcc": 80,  "toll": 0,   "desc": "임대형 — 정부 임대료 + 운영비 보전"},
        "BTO+BTL": {"equity": 18, "opex": 35, "mrg": 60,  "mcc": 50,  "toll": 60,  "desc": "결합형(2024.10 신규) — 상부 BTO 사용료로 하부 BTL 임대료 충당"},
    }
    _bd = _BIZ_DEFAULTS[business_type]
    st.sidebar.caption(f"※ {_bd['desc']}")

    # ─── 핵심 입력 (항상 노출: 연장·사업비·교통량·요금) ───
    st.sidebar.subheader("🏗️ 핵심 입력")
    st.sidebar.caption("슬라이더로 드래그하거나, 옆 칸에 실측치를 직접 입력하세요. "
                       "나머지 조건은 아래 접힌 그룹(▼)에서 조정합니다.")
    road_length = linked_slider_input("연장(km)", 5, 200, 45, 1, "road_length")
    total_capex = linked_slider_input("총사업비(억)", 1000, 100000, 20725, 100, "total_capex")
    daily_traffic = linked_slider_input("일통행량(대)", 5000, 200000, 110000, 500, "daily_traffic")
    toll_per_km = st.sidebar.slider(
        "통행료 km단가(원)", 20, 300,
        _preset.get("toll_per_km", _bd["toll"] if _bd["toll"] > 0 else 80), 5)

    # ─── 노선·수요 상세 (접힘) ───
    with st.sidebar.expander("▼ 노선·수요 상세 (기간·지형·성장률)"):
        construction_years = st.slider("건설기간(년)", 2, 10, _preset.get("construction_years", 5))
        operation_years = st.slider("운영기간(년)", 15, 50, _preset.get("operation_years", 30))
        terrain = st.radio(
            "지형", options=["평지", "구릉", "산악"], index=0, horizontal=True,
            help="지형 난이도에 따라 CAPEX 보정 (평지 1.0 / 구릉 1.3 / 산악 1.8)"
        )
        bridge_ratio = st.slider("교량 비율(%)", 0, 50, _preset.get("bridge_ratio", 15), 1) / 100
        tunnel_ratio = st.slider("터널 비율(%)", 0, 70, _preset.get("tunnel_ratio", 20), 1) / 100
        lanes = st.radio(
            "차로 수", options=[2, 4, 6, 8],
            index=[2, 4, 6, 8].index(_preset.get("lanes", 4)), horizontal=True
        )
        growth = st.slider("교통량 성장률(%)", -2.0, 8.0, float(_preset.get("growth", 2.5)), 0.1)
        heavy_ratio = st.slider("화물비율(%)", 5, 60, _preset.get("heavy_ratio", 30))
        heavy_surcharge = st.slider("대형 차량 할증배율", 1.0, 5.0, 2.50, 0.1)

    # ─── 협약·정부 조건 (접힘) ───
    with st.sidebar.expander("▼ 협약·정부 조건 (MRG·MCC·재구조화)"):
        mrg_ratio = st.slider(
            "MRG 보장률(%)", 0, 100, _bd["mrg"], 5,
            help="MRG = 최소수입보장. 정부가 통행료 수입을 보장하는 비율 (예측 대비). BTO-rs/BTO-ann 활용"
        ) / 100
        mcc_ratio = st.slider(
            "MCC 비용보전율(%)", 0, 100, _bd["mcc"], 5,
            help="MCC = 최소비용보전. 정부가 운영비 초과분을 보전하는 비율. BTO-a/BTL 핵심 변수 (2024.10 정부 활성화 방안 명시)"
        ) / 100
        restructuring_year = st.slider(
            "재구조화 시점(운영년차)", 0, operation_years, 0, 1,
            help="0=재구조화 없음. 1~운영기간 사이 값은 해당 시점에 통행료 -10% 조정"
        )

    # ─── 금융 구조 (접힘) ───
    with st.sidebar.expander("▼ 금융 구조 (자본·금리·커버넌트·물가)"):
        equity_ratio = st.slider("자기자본비율(%)", 5, 50, _bd["equity"]) / 100
        base_rate = st.slider("기준금리(%)", 0.0, 8.0, 2.50, 0.25) / 100
        # 자기자본비용 Ke — CAPM(Ke = rf + β·MRP)으로 산출. rf는 기준금리.
        capm_beta = st.slider(
            "베타(β)", 0.3, 2.0, 0.70, 0.05,
            help="인프라 자산의 체계적 위험. 통상 도로 0.6~0.9 (방어적). 높을수록 Ke↑"
        )
        capm_mrp = st.slider(
            "시장위험프리미엄 MRP(%)", 3.0, 10.0, 6.0, 0.5,
            help="시장수익률−무위험수익률. 국내 통상 5~7%"
        ) / 100
        ke = base_rate + capm_beta * capm_mrp
        st.caption(f"📊 자기자본비용 Ke = {base_rate*100:.2f}% + {capm_beta:.2f}×{capm_mrp*100:.1f}% = **{ke*100:.2f}%** (CAPM)")
    
        # 선순위·후순위 분리 (실무 자금구조)
        senior_ratio_pct = st.slider(
            "타인자본 중 선순위 비중(%)", 50, 95, 70, 5,
            help="실무 표준: 선순위 70% + 후순위 30%. 선순위는 먼저 상환, 후순위는 나중 상환 (금리 차등)"
        )
        senior_ratio = senior_ratio_pct / 100

        senior_spread = st.slider(
            "선순위 가산금리(bp)", 50, 400, 150, 10,
            help="기준금리에 더해지는 선순위 가산금리 (실무 100~250bp)"
        ) / 10000
        sub_spread = st.slider(
            "후순위 가산금리(bp)", 200, 1500, 400, 10,
            help="후순위는 선순위보다 높은 금리 (정상시장 300~600bp; 부실 PPP 주주차입은 1000~1400bp까지)"
        ) / 10000

        senior_rate = base_rate + senior_spread
        sub_rate = base_rate + sub_spread

        # 가중평균 부채금리 (계산 결과)
        debt_rate = senior_ratio * senior_rate + (1 - senior_ratio) * sub_rate
        st.caption(f"📊 가중평균 부채금리: **{debt_rate*100:.2f}%** (선순위 {senior_rate*100:.2f}% × {senior_ratio_pct}% + 후순위 {sub_rate*100:.2f}% × {100-senior_ratio_pct}%)")

        # 호환성용 기존 spread 변수 유지
        spread = senior_spread

        st.markdown("**🏦 대주단 커버넌트** — 딜 텀시트의 DSCR 기준. 판정·민감도·스컬프팅에 일괄 적용.")
        cov_base = st.number_input(
            "Base-case DSCR", min_value=1.00, max_value=2.00, value=1.30, step=0.05,
            help="목표 커버넌트. 통상 1.25~1.40. 스컬프팅·base 판정 기준."
        )
        cov_lockup = st.number_input(
            "Lock-up(배당제한) DSCR", min_value=1.00, max_value=2.00, value=1.20, step=0.05,
            help="이 밑이면 배당(분배) 제한. 통상 1.10~1.20."
        )
        cov_default = st.number_input(
            "Default DSCR", min_value=1.00, max_value=2.00, value=1.05, step=0.05,
            help="이 밑이면 기술적 디폴트 근처. 통상 1.00~1.10."
        )

        infl = st.slider("물가상승률(%)", 0.0, 6.0, 2.0, 0.1)

    # ─── 고급 옵션 ───
    with st.sidebar.expander("▼ 고급 옵션"):
        tax_rate = st.slider("법인세율(%)", 0, 30, 22) / 100
        st.markdown("---")
        
        # 보완 6: 자기자본 회수 방법 3가지 (KDB BTL 자료 표준)
        st.markdown("**💰 자기자본 회수 방법**")
        equity_recovery_method = st.radio(
            "자기자본 회수 방법",
            options=["원금+수익률", "원금만", "회수안함"],
            index=0,
            label_visibility="collapsed",
            help=(
                "BTL 사업의 자기자본 회수 표준 (KDB 자료 기반):\n"
                "• 원금+수익률: 만료 시 자기자본 원금 + 약정 수익률(5%)\n"
                "• 원금만: 사업 만료 시 자기자본 원금만 회수\n"
                "• 회수안함: 자기자본을 별도 회수하지 않고 net income으로만 회수"
            ),
            key="equity_recovery_method",
        )
        
        # 보완 7: 타인자본 회수 방법 3가지 (KDB BTL 자료 표준)
        st.markdown("**🏦 타인자본 회수 방법**")
        debt_repayment_method = st.radio(
            "타인자본 회수 방법",
            options=["원리금균등", "원리금불균등", "기간조정"],
            index=0,
            label_visibility="collapsed",
            help=(
                "타인자본(대출) 상환 방식 (KDB 자료 기반):\n"
                "• 원리금균등: 매년 원리금 합계 일정 (표준 annuity)\n"
                "• 원리금불균등: 운영 후반에 원금 상환 집중 (대주단 회수 가속)\n"
                "• 기간조정: 운영기간보다 짧은 상환기간 (운영 70% 시점에 완료)"
            ),
            key="debt_repayment_method",
        )
        
        st.markdown("---")
        opex_mode = st.radio(
            "OPEX 산출 방식",
            ["자동 (매출비례 top-down)", "물량기반 LCC (상향식·실험)", "수동 입력"],
            index=0,
            help=(
                "• 자동: 학습데이터(도로공사 4,380건) 매출비례 시계열 (기본)\n"
                "• 물량기반 LCC: 물량×표준품셈 단가×열화 상향식 → 현금흐름 직결(C1). "
                "일상 O&M(매출비례 가정) + 자본적 유지보수(LCC) 합산. 실험적·연장기반 추정물량.\n"
                "• 수동: 사용자가 OPEX 비율 직접 입력"
            ),
            key="opex_mode",
        )
        opex_use_bottomup = (opex_mode == "물량기반 LCC (상향식·실험)")
        if opex_mode == "수동 입력":
            opex_ratio_manual = st.slider(
                "OPEX 비율 수동값(% of 매출)", 10, 55, _bd["opex"], 1
            ) / 100
        else:
            opex_ratio_manual = None
        bim_quantities = None
        if opex_use_bottomup:
            opex_routine_ratio = st.slider(
                "일상 O&M 비율(% of 매출, 가정값)", 5, 35, 18, 1,
                help="LCC는 자본적 유지보수만 산출하므로 일상 운영비 baseline을 더한다. "
                     "실측 보정 전까지 가정값.",
            ) / 100
            # BIM(IFC) 업로드 → 형상 물량 자동추출 (없으면 연장 기반 추정)
            _ifc_up = st.file_uploader(
                "BIM(IFC) 업로드 — 물량 자동추출 (선택)", type=["ifc", "IFC"], key="bim_ifc",
                help="업로드하면 형상→물량을 추출해 OPEX를 산정합니다(Qto 없으면 geom 역산). "
                     "미업로드 시 연장 기반 추정물량 사용.",
            )
            st.caption(
                "ⓘ BIM은 선택 입력입니다 — 없어도 협약·공공데이터만으로 전체 분석이 "
                "동작하며, 연결하면 물량 산출이 자동화되어 정밀도가 올라갑니다.")
            if _ifc_up is not None:
                import tempfile
                import os as _os
                from ifc_extract import extract_opex_quantities
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as _tf:
                        _tf.write(_ifc_up.getbuffer())
                        _tmp = _tf.name
                    _ext = extract_opex_quantities(_tmp)
                    bim_quantities = bim_quantities_to_categories(_ext)
                    try:
                        _os.unlink(_tmp)
                    except Exception:
                        pass
                    if bim_quantities:
                        st.success(f"✅ BIM 물량 추출: {len(bim_quantities)}개 공종 "
                                   f"(schema {_ext.get('schema','?')}, geom 역산 포함)")
                    else:
                        st.warning("분류된 물량이 없어 연장 기반 추정으로 진행합니다.")
                except Exception as _e:
                    st.error(f"IFC 처리 실패({_e}) — 연장 기반 추정으로 진행합니다.")
        else:
            opex_routine_ratio = 0.18

    # ECOS 연동
    st.sidebar.markdown("---")
    st.sidebar.subheader("📡 ECOS 금리연동")
    ecos_key = st.sidebar.text_input("API 키", type="password",
                                      help="ecos.bok.or.kr에서 무료 발급")
    if st.sidebar.button("🔄 최신 금리 가져오기", disabled=not ecos_key):
        ecos = ECOSConnector(ecos_key)
        params = ecos.auto_update_params()
        if params.get('rf'):
            st.sidebar.success(f"무위험수익률: {params['rf']*100:.2f}%")
        if params.get('base_rate'):
            st.sidebar.info(f"기준금리: {params['base_rate']*100:.2f}%")
        if params.get('inflation'):
            st.sidebar.info(f"물가상승률: {params['inflation']*100:.2f}%")
        st.sidebar.caption(f"갱신: {params.get('updated_at','')}")

    # ── 수익 추정 ──
    toll_df = estimate_toll_revenue(
        road_length, daily_traffic, toll_per_km,
        growth / 100, heavy_ratio / 100, heavy_surcharge, operation_years
    )
    ann_rev = toll_df['Revenue_억'].iloc[0] if len(toll_df) > 0 else 500

    # WACC 계산 (선순위·후순위 분리 반영)
    wacc_info = calc_wacc_detail(
        rf=base_rate, mrp=capm_mrp, beta=capm_beta,
        equity_ratio=equity_ratio, debt_rate=debt_rate, tax_rate=tax_rate,
        senior_ratio=senior_ratio, senior_rate=senior_rate, sub_rate=sub_rate,
        ke=ke,
    )

    # ── OPEX 자동 산출 (학습 데이터 기반) ──
    opex_estimation = estimate_opex_series(
        business_type=business_type,
        annual_revenue_억=ann_rev,
        operation_years=operation_years,
        terrain=terrain,
        tunnel_ratio=tunnel_ratio,
        bridge_ratio=bridge_ratio,
        growth_rate=growth / 100,
        inflation=infl / 100,
    )
    # 수동 override 우선 → 상향식(LCC) → 자동(top-down)
    if opex_ratio_manual is not None:
        opex_ratio = opex_ratio_manual
        opex_series = None  # 수동값 사용 시 시계열 미사용 (build_cashflow가 비율로 계산)
        opex_source = "수동 입력"
    elif opex_use_bottomup:
        # [C1] 물량기반 LCC 상향식 → 현금흐름 직결
        # [step2] config(별표5) 톱니파형 엔진 사용 (config 없으면 PI엔진 폴백)
        _q_bu = bim_quantities if bim_quantities else quantities_from_road_length(road_length)
        lcc_df_bu, _lcc_total_bu = estimate_lcc_sawtooth_from_config(
            _q_bu, operation_years, wacc_info['wacc'])
        _opex_src_label = "물량기반 LCC (BIM)" if bim_quantities else "물량기반 LCC (연장추정)"
        bu = estimate_opex_series_bottomup(
            lcc_df_bu, ann_rev, operation_years,
            routine_opex_ratio=opex_routine_ratio, growth_rate=growth / 100,
        )
        opex_ratio = bu['opex_ratio_avg']
        opex_series = np.array(bu['opex_series_억'])
        opex_source = _opex_src_label
        # 하류 표시(설명·시계열)도 상향식 결과를 반영하도록 override
        opex_estimation = {**opex_estimation,
                           'opex_series_억': bu['opex_series_억'],
                           'opex_ratio_avg': bu['opex_ratio_avg'],
                           'explanation': bu['explanation'],
                           'peak_year': bu['peak_year'],
                           'peak_amount_억': bu['peak_amount_억']}
    else:
        opex_ratio = opex_estimation['opex_ratio_avg']
        opex_series = np.array(opex_estimation['opex_series_억'])
        opex_source = "자동 산출"

    # ── CAPEX 회귀 참고치 ──
    capex_reference = estimate_capex_from_route(
        road_length_km=road_length,
        lanes=lanes,
        terrain=terrain,
        bridge_ratio=bridge_ratio,
        tunnel_ratio=tunnel_ratio,
        business_type=business_type,
    )

    # 기본 파라미터
    base_params = {
        'capex_억': total_capex,
        'annual_revenue_억': ann_rev,
        'construction_years': construction_years,
        'operation_years': operation_years,
        'opex_ratio': opex_ratio,
        'opex_series_억': opex_series,      # ← 자동 산출 시계열
        'discount_rate': wacc_info['wacc'],
        'inflation': infl / 100,
        'growth_rate': growth / 100,
        'equity_ratio': equity_ratio,
        'debt_rate': debt_rate,
        'senior_ratio': senior_ratio,
        'senior_rate': senior_rate,
        'tax_rate': tax_rate,
        'business_type': business_type,
        'mrg_ratio': mrg_ratio,
        'mcc_ratio': mcc_ratio,
        'restructuring_year': restructuring_year,
        'equity_recovery_method': equity_recovery_method,
        'debt_repayment_method': debt_repayment_method,
    }

    # 기본 현금흐름 계산
    cf_df, metrics = build_cashflow(**base_params)

    # ── [TODO①] OPEX 불확실성 밴드 (Weibull CI 전파) + DSCR 밴드 ──
    opex_band = None
    dscr_band = None
    if opex_series is not None and len(opex_series) > 0:
        try:
            opex_band = montecarlo_opex_band(
                opex_series, weibull_ci=load_weibull_ci(), n_sims=400)
            # P10(낮은 OPEX)→높은 DSCR / P90(높은 OPEX)→낮은 DSCR
            _, _m_lo = build_cashflow(**{**base_params, 'opex_series_억': np.array(opex_band['p10'])})
            _, _m_hi = build_cashflow(**{**base_params, 'opex_series_억': np.array(opex_band['p90'])})
            dscr_band = {'best': _m_lo.get('dscr_min'), 'base': metrics.get('dscr_min'),
                         'worst': _m_hi.get('dscr_min')}
        except Exception:
            opex_band = None
            dscr_band = None

    # PDF 보고서 밴드 차트(_chart_opex_band)가 P10–P90을 그릴 수 있도록 부착
    if opex_band:
        opex_estimation['band'] = opex_band

    render_data_source_sidebar()

    # ============================================================
    # 메인 영역 — Forenode 헤더 (SVG 로고 + 사업명 입력)
    # ============================================================
    st.markdown("""
        <style>
        .forenode-header {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 12px 16px;
            background-color: #f8f9fa;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 0.5px solid #e0e0e0;
        }
        .forenode-logo-text {
            font-size: 32px;
            font-weight: 500;
            color: #1F3864;
            line-height: 1.2;
        }
        .forenode-subtitle {
            font-size: 12px;
            color: #888780;
            margin-top: 2px;
        }
        </style>
        <div class="forenode-header">
            <svg width="80" height="50" viewBox="0 0 80 50" xmlns="http://www.w3.org/2000/svg">
                <line x1="10" y1="35" x2="40" y2="15" stroke="#1F3864" stroke-width="2.5"/>
                <line x1="40" y1="15" x2="70" y2="45" stroke="#1F3864" stroke-width="2.5"/>
                <line x1="70" y1="45" x2="40" y2="15" stroke="#1F3864" stroke-width="2.5"/>
                <circle cx="10" cy="35" r="6" fill="#1F3864"/>
                <circle cx="40" cy="15" r="8" fill="#EF9F27"/>
                <circle cx="70" cy="45" r="6" fill="#1F3864"/>
            </svg>
            <div>
                <div class="forenode-logo-text">Forenode</div>
                <div class="forenode-subtitle">공공데이터 기반 민자도로 수익성·적정성 검증 — 여러 참여자가 같은 기준으로</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 사업명 입력 (별도 라인)
    project_name = st.text_input(
        "📝 분석할 사업명",
        value="",
        placeholder="분석할 민자도로 사업명을 입력하세요 (예: 화성-안성 고속도로)",
        label_visibility="collapsed",
        key="project_name_input",
    )

    # 사업 요약 캡션 (자동 생성)
    if project_name:
        st.caption(
            f"**{project_name}** | "
            f"{business_type} · {road_length}km · {total_capex:,}억원 · "
            f"운영 {operation_years}년"
    )

    # ── 자동 산출 근거 (한 줄) ──
    _capex_in_range = (
        capex_reference['capex_low_억'] <= total_capex <= capex_reference['capex_high_억']
    )
    _capex_check = "✅ 회귀 범위 내" if _capex_in_range else "⚠️ 회귀 범위 밖"
    st.caption(
        f"💡 **자동 산출 근거** | "
        f"OPEX {opex_source}: 평균 {opex_ratio*100:.1f}% "
        f"(1년차 {opex_estimation['opex_series_억'][0]:.0f}억 → "
        f"정점 {opex_estimation['peak_year']}년차 {opex_estimation['peak_amount_억']:.0f}억) | "
        f"CAPEX 회귀참고: {capex_reference['capex_estimate_억']:,}억 "
        f"(±20%: {capex_reference['capex_low_억']:,}~{capex_reference['capex_high_억']:,}) {_capex_check}"
    )

    # ── PDF 보고서·심화탭이 공유하는 분석 컨텍스트 (KPI 위에서 미리 조립) ──
    phase_context = {
        'business_type': business_type,
        'road_length': road_length,
        'lanes': lanes,
        'terrain': terrain,
        'bridge_ratio': bridge_ratio,
        'tunnel_ratio': tunnel_ratio,
        'total_capex_user': total_capex,
        'operation_years': operation_years,
        'construction_years': construction_years,
        'annual_revenue': ann_rev,
        'mrg_ratio': mrg_ratio,
        'mcc_ratio': mcc_ratio,
        'restructuring_year': restructuring_year,
        'equity_recovery_method': equity_recovery_method,
        'debt_repayment_method': debt_repayment_method,
        'opex_estimation': opex_estimation,
        'capex_reference': capex_reference,
        'metrics': metrics,
        'wacc': wacc_info['wacc'],
        # 관점(역할) — 아래 관점 라우터(key='role_lens')의 선택을 PDF 역할 섹션에 반영.
        # 앱 라벨 → report _ROLE_FOCUS 키로 매핑('전체'·미선택은 None → 일반 보고서).
        'role': {
            "대주단": "대주",
            "사업주": "사업주",
            "자산운용사·연기금": "운용사",
            "정부(PIMAC·주무관청)": "주무관청",
            "회계법인": "회계법인",
        }.get(st.session_state.get('role_lens')),
        # 선순위·후순위 자금구조 (v2.1 추가)
        'senior_ratio': senior_ratio,
        'senior_rate': senior_rate,
        'sub_rate': sub_rate,
        # 해지시지급금 (v2.1 추가, 시점 4 재구조화 활용)
        # 통상 해지시지급금은 건설비용과 동일하게 책정 (나무위키·KDB 자료)
        'termination_payment': total_capex,
    }

    # KPI 카드 — 핵심 4종 (나머지 3종은 '전체 지표 보기'로 이동, 2026-07 UI 개편)
    _eirr = metrics.get('equity_irr', float('nan'))
    _eirr_ok = _eirr == _eirr  # NaN guard
    col1, col2, col3, col4 = st.columns(4)

    npv_color = "green" if metrics['npv'] >= 0 else "red"
    with col1:
        st.markdown(f"""<div class="metric-card {npv_color}">
            <h4>NPV (프로젝트·@WACC)</h4><h2>{metrics['npv']:,.0f}억</h2></div>""",
            unsafe_allow_html=True)
    with col2:
        eirr_color = "green" if (_eirr_ok and _eirr > 0) else "red"
        eirr_txt = f"{_eirr*100:.1f}%" if _eirr_ok else "—"
        st.markdown(f"""<div class="metric-card {eirr_color}">
            <h4>자기자본IRR</h4><h2>{eirr_txt}</h2></div>""",
            unsafe_allow_html=True)
    with col3:
        dscr_color = "green" if metrics['dscr_min'] >= 1.0 else "red"
        st.markdown(f"""<div class="metric-card {dscr_color}">
            <h4>DSCR (최소/평균)</h4><h2>{metrics['dscr_min']:.2f} / {metrics['dscr_avg']:.2f}</h2></div>""",
            unsafe_allow_html=True)
    with col4:
        bc_color = "green" if metrics['bc_ratio'] >= 1.0 else "orange"
        st.markdown(f"""<div class="metric-card {bc_color}">
            <h4>B/C ratio</h4><h2>{metrics['bc_ratio']:.2f}</h2></div>""",
            unsafe_allow_html=True)

    with st.expander("📊 전체 지표 보기 (프로젝트IRR·ROE·WACC)"):
        _k1, _k2, _k3 = st.columns(3)
        irr_txt = f"{metrics['nominal_irr']*100:.1f}% / {metrics['real_irr']*100:.1f}%"
        with _k1:
            st.markdown(f"""<div class="metric-card blue">
                <h4>프로젝트IRR(명목/불변·세후)</h4><h2>{irr_txt}</h2></div>""",
                unsafe_allow_html=True)
        with _k2:
            roe_color = "green" if metrics['roe'] > 0 else "red"
            st.markdown(f"""<div class="metric-card {roe_color}">
                <h4>자기자본순이익률(ROE)</h4><h2>{metrics['roe']*100:.1f}%</h2></div>""",
                unsafe_allow_html=True)
        with _k3:
            st.markdown(f"""<div class="metric-card blue">
                <h4>WACC</h4><h2>{wacc_info['wacc']*100:.2f}%</h2></div>""",
                unsafe_allow_html=True)

    st.caption(
        "ⓘ 수익률 표기 기준: 프로젝트 IRR=세후(명목/불변) · 협약수익률=실질·세전(역할별 지표 참조). "
        "민자 실시협약·재구조화 벤치마크는 노선마다 세전경상·세후실질을 병기하므로 비교 시 기준 확인 필수 "
        "(KOTI MP-24-11, 2024, pp.78-86)."
    )

    # ── 🔎 가정 검증 요약 배지 — 판정을 분명한 문장으로 끝맺는다 (상세: 가정 검증 오버레이) ──
    try:
        from demand_bias import demand_optimism_band as _dob, prob_ratio_below as _prb, \
            BENCHMARK_PRIORS as _BP
        from verification_overlays import implied_rating as _irt, \
            agreed_return_position as _arp, TRIGGER_RULES as _TR
        _bp_key = st.session_state.get("demand_prior") or list(_BP.keys())[0]
        _b_db = _dob(daily_traffic, prior=_bp_key)
        _b_dicon = {"high": "🔴", "mid": "🟡", "low": "🟢"}.get(_b_db["level"], "⚪")
        _b_p70 = _prb(_TR["ratio_threshold"], prior=_bp_key)
        if _b_p70 >= 0.50:
            _tg_icon, _tg_msg = "🔴", "도달 위험이 높습니다 — 수요 가정을 보수적으로 재검토하세요"
        elif _b_p70 >= 0.25:
            _tg_icon, _tg_msg = "🟡", "도달 가능성이 있습니다 — 하방 시나리오를 함께 확인하세요"
        else:
            _tg_icon, _tg_msg = "🟢", "도달 가능성이 낮습니다 — 특이사항 없음"
        _b_ap = _arp(metrics.get('real_irr', float('nan')))
        _ap_icon = {"over": "🔴", "under": "🔴", "above": "🟡", "low": "🟡",
                    "recent": "🟢", "btoa": "🟢"}.get(_b_ap["level"], "⚪")
        _ap_msg = {
            "over": "시장 전례 상단(12.0%)을 초과합니다 — 과대 산정 여부를 검토하세요",
            "above": "시장 평균(6.41%)을 상회합니다 — 산정 근거를 확인하세요",
            "recent": "BTO 후기 체결 권역(4~6%) 안에 있습니다 — 특이사항 없음",
            "btoa": "BTO-a 신규 협약 권역(2.85~4%) 안에 있습니다 — 특이사항 없음",
            "low": "시장 하단에 근접합니다 — 투자유인을 점검하세요",
            "under": "시장 전례 하단(2.85%) 미만입니다 — 과소(투자유인 부족) 여부를 검토하세요",
        }.get(_b_ap["level"], "시장 위치를 산출할 수 없습니다")
        _b_ir = _irt(metrics.get('dscr_min', float('nan')))
        _ir_icon = {"ig": "🟢", "edge": "🟡", "spec": "🟡",
                    "default": "🔴"}.get(_b_ir["level"], "⚪")
        _ir_msg = {
            "ig": "투자등급 영역입니다 — 특이사항 없음",
            "edge": "투자등급 경계입니다 — 하방 시나리오를 확인하세요",
            "spec": "투기등급 영역입니다 — 신용보강을 검토하세요",
            "default": "디폴트 위험 영역입니다 — 사업구조 재설계가 필요합니다",
        }.get(_b_ir["level"], "산출할 수 없습니다")
        _b_rirr = metrics.get('real_irr', float('nan'))
        _b_rirr_txt = f"{_b_rirr*100:.1f}%" if _b_rirr == _b_rirr else "—"
        _b_dmin = metrics.get('dscr_min', float('nan'))
        _b_dmin_txt = f"{_b_dmin:.2f}" if _b_dmin == _b_dmin else "—"
        st.markdown("**🔎 가정 검증 요약**")
        st.markdown(
            f"{_b_dicon} **수요** — 입력 교통량은 과거 실적 분포 기준, 예측의 "
            f"{_b_db['median_ratio']*100:.0f}%가 실현 중앙값입니다. {_b_db['flag']}.\n\n"
            f"{_tg_icon} **재협상 트리거** — 실측이 협약 대비 {_TR['ratio_threshold']*100:.0f}% "
            f"미달에 머물 확률이 약 {_b_p70*100:.0f}%입니다. 법정 트리거(유료도로법 §23의5)에 "
            f"{_tg_msg}.\n\n"
            f"{_ap_icon} **협약수익률 위치** — 이 시나리오의 실질 사업수익률(세후) "
            f"{_b_rirr_txt}는 {_ap_msg}.\n\n"
            f"{_ir_icon} **예비 신용등급** — 최소 DSCR {_b_dmin_txt} 기준 {_ir_msg}.")
        st.caption("근거·벤치마크·운영 중 사업 점검은 아래 '🔎 가정 검증 오버레이'에서 확인하세요.")
    except Exception:
        pass

    # ── 🔭 관점별 보기 (role-first — 2026-07 UI 개편: KPI 직후로 승격) ──
    st.markdown("### 🔭 관점별 보기")
    st.caption(
        "주체를 고르면 그 입장에서 가장 중요한 지표·판정과, 더 파볼 심화 도구·what-if 위치를 안내합니다."
    )
    _role = st.radio(
        "관점(역할)",
        ["전체", "대주단", "사업주", "자산운용사·연기금", "정부(PIMAC·주무관청)", "회계법인"],
        horizontal=True, label_visibility="collapsed", key="role_lens",
    )
    _role_slot = st.container(border=True)
    st.markdown("")

    # ════════════════════════════════════════════════════════
    # 📄 PDF 보고서 — 분석 직후 최상단에서 즉시 생성·다운로드
    # ════════════════════════════════════════════════════════
    from datetime import datetime
    _pc1, _pc2 = st.columns([3, 1])
    with _pc1:
        st.markdown("##### 📄 분석 결과를 PDF 보고서로 즉시 출력")
        st.caption(
            "지금 화면의 분석 결과(KPI·OPEX 밴드·현금흐름 지표)를 Forenode 표준 PDF 보고서로 생성합니다. "
            "변수를 바꾼 뒤에는 다시 생성하세요."
        )
    with _pc2:
        if st.button("📄 PDF 보고서 생성", type="primary",
                     use_container_width=True, key="pdf_generate_top"):
            try:
                from report_generator import generate_pdf_report
                with st.spinner("📊 PDF 보고서 생성 중…"):
                    st.session_state['forenode_pdf_bytes'] = generate_pdf_report(
                        phase_context=phase_context,
                        project_name=project_name or "민자도로 분석 사업",
                    )
                st.session_state['forenode_pdf_name'] = (
                    f"Forenode_보고서_{(project_name or '민자도로').replace(' ', '_')}"
                    f"_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                )
            except Exception as _pdf_err:
                st.session_state.pop('forenode_pdf_bytes', None)
                st.error(f"PDF 생성 중 오류: {_pdf_err}")
    if st.session_state.get('forenode_pdf_bytes'):
        st.download_button(
            "⬇️ 생성된 PDF 보고서 다운로드",
            data=st.session_state['forenode_pdf_bytes'],
            file_name=st.session_state.get('forenode_pdf_name', 'Forenode_보고서.pdf'),
            mime="application/pdf",
            use_container_width=True,
            key="pdf_download_top",
        )

    st.markdown("")

    # ── 한 줄 판정 (대주단 커버넌트 입력 기준) ──
    _dmin = metrics['dscr_min']
    _npv = metrics['npv']
    if _npv < 0 or _dmin < cov_default:
        _detail = "부채상환 불가" if _dmin < 1.0 else f"default({cov_default:.2f}) 근처"
        st.error(
            f"🔴 **대주단 기준 사업성 미달** — DSCR_min {_dmin:.2f}({_detail})"
            f"{' · NPV 적자' if _npv < 0 else ''}. 수요·단가·자본구조 가정 재검토 또는 정부 보전(MRG/MCC) 필요."
        )
    elif _dmin < cov_lockup:
        st.warning(
            f"🟡 **여유 얇음** — DSCR_min {_dmin:.2f}가 lock-up(배당제한 {cov_lockup:.2f}) 미만. "
            "배당제한 구간 진입 위험 — DSRA·MRG 흡수 여력 확인 필요."
        )
    elif _dmin < cov_base:
        st.warning(
            f"🟡 **양호하나 base-case({cov_base:.2f}) 미달** — DSCR_min {_dmin:.2f}. "
            "초기 램프업 구간에 한정되면 DSRA·MRG로 흡수되는 표준 프로파일."
        )
    else:
        st.success(
            f"🟢 **대주단 기준 양호** — DSCR_min {_dmin:.2f} ≥ base-case {cov_base:.2f}"
            f"{' · NPV 흑자' if _npv >= 0 else ''}."
        )

    # ── 사업주(지분) 관점 한 줄 ──
    if _eirr_ok:
        if _eirr < 0:
            st.error(f"🔴 **지분 관점** — 자기자본IRR {_eirr*100:.1f}%(원금 손실 구간). 출자 회수 불가.")
        elif _eirr < ke:
            st.warning(
                f"🟡 **지분 관점** — 자기자본IRR {_eirr*100:.1f}%가 요구수익률 Ke {ke*100:.1f}% 미달. "
                "통행료·자본구조·정부 보전 조정 없이는 출자자 수익 기준 미충족."
            )
        else:
            st.success(f"🟢 **지분 관점** — 자기자본IRR {_eirr*100:.1f}% ≥ 요구수익률 Ke {ke*100:.1f}%.")

    # ── 리스크 스냅샷 (핵심 산출물 상단 승격 + 회계법인용 EBITDA 노출) ──
    st.markdown("##### ⚡ 리스크 스냅샷")
    _llcr = metrics.get('llcr_min', float('nan'))
    _ebitda = metrics.get('ebitda_avg', float('nan'))
    _sdscr = metrics.get('senior_dscr_min', float('nan'))
    rc1, rc2, rc3, rc4, rc5 = st.columns(5)
    rc1.metric("DSCR 최소/평균", f"{_dmin:.2f} / {metrics['dscr_avg']:.2f}")
    rc2.metric("선순위 DSCR 최소", f"{_sdscr:.2f}" if _sdscr == _sdscr and _sdscr > 0 else "—",
               help="선순위 트랜치 단독 상환 기준 커버리지(우선권 관점). 블렌디드 DSCR보다 높음.")
    rc3.metric("LLCR 최소", f"{_llcr:.2f}" if _llcr == _llcr else "—")
    rc4.metric("EBITDA 평균(억)", f"{_ebitda:,.0f}" if _ebitda == _ebitda else "—")
    rc5.metric("NPV 적자 여부", "적자" if _npv < 0 else "흑자")
    st.caption(
        "토네이도·몬테카를로·낙관편향·부채 스컬프팅·리스크 등록부는 "
        "**[⏱ 사전 검토 ▸ 🎯 민감도·리스크 등록부]** 탭에서."
    )

    # ── 배당 타임라인 (사업주 현금회수 관점) ──
    _div_df = cf_df[(cf_df['Year'] > construction_years) & (cf_df['DSCR'] > 0)].copy()
    if len(_div_df) > 0:
        _div_df['배당가능'] = _div_df['DSCR'] >= cov_lockup
        _div_df['운영년차'] = (_div_df['Year'] - construction_years).astype(int)
        _allowed = _div_df[_div_df['배당가능']]
        _first_div = int(_allowed['운영년차'].iloc[0]) if len(_allowed) > 0 else None
        _n_allowed = int(_div_df['배당가능'].sum())
        _n_total = len(_div_df)
        with st.expander(
            f"💵 배당 타임라인 (사업주 관점) — "
            + (f"운영 {_first_div}년차부터 배당 가능" if _first_div else "전 기간 배당제한")
            + f" · 배당가능 {_n_allowed}/{_n_total}년",
            expanded=False,
        ):
            st.caption(
                f"lock-up DSCR {cov_lockup:.2f} 이상인 해에만 출자자 배당(분배) 가능 — "
                "그 미만 구간은 현금이 DSRA·상환에 묶여 회수가 지연됩니다."
            )
            import plotly.graph_objects as _go
            _fig = _go.Figure()
            _fig.add_trace(_go.Bar(
                x=_div_df['운영년차'], y=_div_df['DSCR'],
                marker_color=['#2ca02c' if v else '#d62728' for v in _div_df['배당가능']],
                hovertemplate="운영 %{x}년차 · DSCR %{y:.2f}<extra></extra>",
            ))
            _fig.add_hline(y=cov_lockup, line_dash="dash", line_color="#ff7f0e",
                           annotation_text=f"lock-up {cov_lockup:.2f}")
            _fig.update_layout(
                height=260, margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="운영년차", yaxis_title="DSCR",
                showlegend=False,
            )
            st.plotly_chart(_fig, use_container_width=True)
            st.caption("🟢 배당 가능 연차 · 🔴 배당제한(lock-up 미만) 연차")

    st.markdown("")

    with st.expander("ℹ️ 분석 가정 (지표 해석 시 참고)", expanded=False):
        st.markdown(
            "- **NPV·할인율**: 프로젝트 FCFF를 **WACC**로 할인. WACC의 자기자본비용(Ke)은 "
            "**CAPM `Ke = rf + β·MRP`**로 산출(rf=기준금리, β·MRP는 사이드바 입력).\n"
            "- **프로젝트 세금(FCFF)**: 자본구조 중립을 위해 프로젝트 FCF의 법인세는 **이자 차감 없이**(언레버드) "
            "과세 — 이자 세금방패는 할인율 WACC의 `Kd(1−t)`에 이미 반영되므로 **이중계상 방지**.\n"
            "- **당기순이익·DSCR**: 법인세는 **정액법 감가상각·이자 차감 후**(레버드) 과세소득으로 산출. "
            "DSCR 분자=세후 CFADS, 분모=원리금. 건설기간 이자(IDC)는 부채에 자본화.\n"
            "- **ROE**: 연평균 순이익 ÷ **투입 자기자본 원금**(장부 평균자본이 아닌 투입원금 기준).\n"
            "- **B/C ratio**: 사회적 편익이 아닌 **재무적 비율**(매출 PV ÷ (CAPEX+운영비) PV).\n"
            "- **MRG**: 추정수입(통행료 조정 전)의 보장률을 floor로, 실제 수입이 미달할 때만 차액 보전.\n"
            "- **자기자본 만료 회수**: 회수액은 **만기 잔존가치(terminal value)에서 잔존부채를 상환한 잔여분 한도 내**에서만 "
            "인식(출처 없는 현금 생성 방지). 잔존가치 미입력 시 회수액 0."
        )

    # ── KDI PIMAC 표준재무모델 정합 내보내기 ──
    with st.expander("📐 KDI PIMAC 표준재무모델 양식으로 내보내기", expanded=False):
        st.caption(
            "**KDI PIMAC 표준재무모델** 연도별 양식(한국어 컬럼·지출=양수 투자비)으로 변환합니다. "
            "표준 .xlsx에 붙여넣어 셀 단위로 교차검증하세요."
        )
        _pimac_df = build_pimac_standard_table(cf_df)
        st.dataframe(_pimac_df, use_container_width=True, height=280)
        st.download_button(
            "⬇️ 표준양식 CSV 다운로드",
            _pimac_df.to_csv(index=False).encode('utf-8-sig'),
            file_name="forenode_PIMAC표준재무모델.csv",
            mime="text/csv",
            use_container_width=True,
            key="pimac_export_main",
        )

    # ════════════════════════════════════════════════════════
    # 📤 개발자 데이터 핸드오프 (고객 → 개발자 원클릭 전달, MVP=다운로드)
    # ════════════════════════════════════════════════════════
    try:
        from dev_handoff import render_handoff_section
        _scenario_export = {
            "inputs": {
                "business_type": business_type,
                "road_length_km": road_length,
                "total_capex_eok": total_capex,
                "construction_years": construction_years,
                "operation_years": operation_years,
                "terrain": terrain,
                "bridge_ratio": round(float(bridge_ratio), 4),
                "tunnel_ratio": round(float(tunnel_ratio), 4),
                "lanes": lanes,
                "mrg_ratio": round(float(mrg_ratio), 4),
                "mcc_ratio": round(float(mcc_ratio), 4),
                "restructuring_year": restructuring_year,
                "daily_traffic": daily_traffic,
                "growth_pct": growth,
                "heavy_ratio_pct": heavy_ratio,
                "toll_per_km_won": toll_per_km,
                "heavy_surcharge": heavy_surcharge,
                "equity_ratio": round(float(equity_ratio), 4),
                "ke": round(float(ke), 4),
                "base_rate": round(float(base_rate), 4),
                "senior_ratio_pct": senior_ratio_pct,
                "senior_spread": round(float(senior_spread), 6),
                "sub_spread": round(float(sub_spread), 6),
                "debt_rate": round(float(debt_rate), 6),
                "infl_pct": infl,
                "tax_rate": round(float(tax_rate), 4),
                "equity_recovery_method": equity_recovery_method,
                "debt_repayment_method": debt_repayment_method,
                "opex_ratio_manual": opex_ratio_manual,
            },
            "outputs": {
                "npv_eok": round(float(metrics["npv"]), 1),
                "nominal_irr": round(float(metrics["nominal_irr"]), 4),
                "real_irr": round(float(metrics["real_irr"]), 4),
                "roe": round(float(metrics["roe"]), 4),
                "dscr_min": round(float(metrics["dscr_min"]), 3),
                "dscr_avg": round(float(metrics["dscr_avg"]), 3),
                "bc_ratio": round(float(metrics["bc_ratio"]), 3),
                "wacc": round(float(wacc_info["wacc"]), 4),
                "opex_ratio": round(float(opex_ratio), 4),
            },
            "units": {
                "*_ratio / ke / base_rate / *_spread / debt_rate / tax_rate / *_irr / roe / wacc": "소수(0.10 = 10%)",
                "*_pct": "퍼센트(2.5 = 2.5%)",
                "*_eok": "억원",
            },
        }
        render_handoff_section(_scenario_export, project_name=project_name)
    except Exception as _handoff_err:  # 변수 누락 등으로 본 분석이 깨지지 않도록 방어
        st.caption(f"📤 데이터 전달 모듈을 불러오지 못했습니다: {_handoff_err}")

    # ════════════════════════════════════════════════════════
    # 시점 탭 — 민자도로 라이프사이클 4시점
    # ════════════════════════════════════════════════════════
    from phase_tabs import (
        render_phase_pretest,
        render_phase_construction,
        render_phase_operation,
        render_phase_restructuring,
    )
    
    # 시점 탭에 전달할 컨텍스트 (자동 산출 결과 포함)
    # phase_context 는 상단(KPI 카드 위)에서 이미 조립됨 — PDF 보고서 버튼과 심화 탭이 공유

    # (🔭 관점별 보기는 2026-07 UI 개편으로 KPI 직후로 이동 — 아래 _render_role_router 호출부 참조)
    _rl_eirr = metrics.get('equity_irr', float('nan'))
    _rl_eirr_ok = _rl_eirr == _rl_eirr
    _rl_eirr_txt = f"{_rl_eirr*100:.1f}%" if _rl_eirr_ok else "—"
    _rl_sdscr = metrics.get('senior_dscr_min', float('nan'))
    _rl_llcr = metrics.get('llcr_min', float('nan'))
    _rl_ebitda = metrics.get('ebitda_avg', float('nan'))
    _rl_govt = metrics.get('total_govt_burden', 0.0)
    _rl_dmin = metrics['dscr_min']

    with _role_slot:
        if _role == "대주단":
            st.markdown("**📐 대주단 — 부채 회수 안정성 (DSCR·LLCR·스컬프팅)**")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("DSCR 최소/평균", f"{_rl_dmin:.2f} / {metrics['dscr_avg']:.2f}")
            d2.metric("선순위 DSCR 최소", f"{_rl_sdscr:.2f}" if _rl_sdscr == _rl_sdscr and _rl_sdscr > 0 else "—")
            d3.metric("LLCR 최소", f"{_rl_llcr:.2f}" if _rl_llcr == _rl_llcr else "—")
            d4.metric("커버넌트(텀시트)", f"base {cov_base:.2f} / lock {cov_lockup:.2f}")
            if _rl_dmin < cov_default:
                st.error(f"DSCR_min {_rl_dmin:.2f} < default {cov_default:.2f} — 커버넌트 미달, 부채 상환 불안정.")
            elif _rl_dmin < cov_lockup:
                st.warning(f"DSCR_min {_rl_dmin:.2f} < lock-up {cov_lockup:.2f} — 배당제한 구간 진입 위험.")
            else:
                st.success(f"DSCR_min {_rl_dmin:.2f} ≥ lock-up {cov_lockup:.2f} — 부채 회수 안정권.")
            st.caption(
                "심화 ▸ **⏱ 사전 검토 ▸ 민감도·리스크 등록부**(토네이도·몬테카를로·부채 스컬프팅·낙관편향) · "
                "**🏗 시공·자금조달 ▸ 현금흐름**(연도별 DSCR·선순위 DSCR) · "
                "what-if ▸ **🔄 재구조화 ▸ 요구수익률 솔버**(대주단 프리셋)."
            )
        elif _role == "사업주":
            st.markdown("**🏢 사업주(SPC 출자자) — 자기자본 회수 (Equity IRR·배당)**")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("자기자본IRR", _rl_eirr_txt)
            s2.metric("자기자본순이익률(ROE)", f"{metrics['roe']*100:.1f}%")
            s3.metric("요구수익률 Ke", f"{ke*100:.1f}%")
            s4.metric("NPV(프로젝트·@WACC)", f"{metrics['npv']:,.0f}억")
            if _rl_eirr_ok and _rl_eirr >= ke:
                st.success(f"자기자본IRR {_rl_eirr_txt} ≥ 요구수익률 Ke {ke*100:.1f}% — 출자자 수익 기준 충족.")
            elif _rl_eirr_ok and _rl_eirr >= 0:
                st.warning(f"자기자본IRR {_rl_eirr_txt} < Ke {ke*100:.1f}% — 통행료·자본구조·정부 보전 조정 필요.")
            else:
                st.error("자기자본IRR 산출 불가/음수 — 현 가정에서 출자 회수 곤란.")
            with st.expander("📐 추가 재무지표 (협약수익률·MIRR·PLCR)"):
                e1, e2, e3, e4 = st.columns(4)
                _ag = metrics.get('agreed_return_real_pretax')
                e1.metric("협약 사업수익률(실질·세전)", f"{_ag*100:.1f}%" if _ag == _ag else "—")
                _rr = metrics.get('real_irr')
                e2.metric("실질 사업수익률(세후)", f"{_rr*100:.1f}%" if _rr == _rr else "—")
                _pm = metrics.get('project_mirr')
                e3.metric("사업 MIRR", f"{_pm*100:.1f}%" if _pm == _pm else "—")
                e4.metric("PLCR(min)", f"{metrics.get('plcr_min', 0):.2f}")
                st.caption("협약수익률=실시협약 기준(실질·세전, 세후 병기) · MIRR=IRR 재투자·복수해 결함 교정 · "
                           "PLCR=사업 전기간 부채커버(≥LLCR). IRR 단독 판단 금지, NPV·DSCR 병행.")
            st.caption(
                "심화 ▸ **💵 배당 타임라인**(아래 expander) · **🔄 재구조화 단계**(MRG 재협상·관리운영권) · "
                "what-if ▸ **🔄 재구조화 ▸ 요구수익률 솔버**(사업주 프리셋: 목표 IRR 역산)."
            )
        elif _role == "자산운용사·연기금":
            st.markdown("**💼 자산운용사·연기금(FI) — 안정 수익 + 잔여가치**")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("자기자본IRR", _rl_eirr_txt)
            f2.metric("ROE", f"{metrics['roe']*100:.1f}%")
            f3.metric("DSCR 최소", f"{_rl_dmin:.2f}")
            f4.metric("LLCR 최소", f"{_rl_llcr:.2f}" if _rl_llcr == _rl_llcr else "—")
            if _rl_eirr_ok and _rl_eirr >= 0.10 and _rl_dmin >= 1.15:
                st.success("IRR·DSCR 모두 운용 기준선(IRR≥10%·DSCR≥1.15) 충족 — 편입 검토 가능.")
            else:
                st.warning("IRR 또는 DSCR이 운용 기준선(IRR≥10%·DSCR≥1.15) 미달 — 하방 분포 확인 필요.")
            st.caption(
                "심화 ▸ **⏱ 사전 검토 ▸ 민감도·리스크 등록부**(몬테카를로 P10·하방확률)·**MC NPV** · "
                "what-if ▸ **🔄 재구조화 ▸ 요구수익률 솔버**(자산운용사·연기금 프리셋)."
            )
        elif _role == "정부(PIMAC·주무관청)":
            st.markdown("**🏛️ 정부(KDI PIMAC·주무관청) — VfM·재정부담**")
            g1, g2, g3, g4 = st.columns(4)
            g1.metric("B/C ratio", f"{metrics['bc_ratio']:.2f}")
            g2.metric("NPV(억)", f"{metrics['npv']:,.0f}")
            g3.metric("정부 재정부담(MRG+MCC 누적·억)", f"{_rl_govt:,.0f}")
            g4.metric("DSCR 최소", f"{_rl_dmin:.2f}")
            if metrics['bc_ratio'] >= 1.0 and metrics['npv'] >= 0:
                st.success("B/C ≥ 1.0 · NPV ≥ 0 — 재무 타당성 확보(VfM 추가 검토 권장).")
            else:
                st.warning("B/C < 1.0 또는 NPV < 0 — 민자 적격성·정부 보전(MRG/MCC) 설계 재검토 필요.")
            st.caption(
                "심화 ▸ **⏱ 사전 검토**(민자 적격성·통행료 적정성·SPC 벤치마크) · "
                "what-if ▸ **🔄 재구조화 ▸ 요구수익률 솔버**(KDI PIMAC·주무관청 프리셋)."
            )
        elif _role == "회계법인":
            st.markdown("**🧮 회계법인 — 현금흐름 재현성·검증**")
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("EBITDA 평균(억)", f"{_rl_ebitda:,.0f}" if _rl_ebitda == _rl_ebitda else "—")
            a2.metric("NPV(프로젝트·@WACC)", f"{metrics['npv']:,.0f}억")
            a3.metric("DSCR 최소/평균", f"{_rl_dmin:.2f} / {metrics['dscr_avg']:.2f}")
            a4.metric("선순위 DSCR 최소", f"{_rl_sdscr:.2f}" if _rl_sdscr == _rl_sdscr and _rl_sdscr > 0 else "—")
            st.info("검증 포인트: EBITDA=매출−운영비, CFADS=매출−운영비−세금, 세금은 정액 감가상각 반영. 연도별 추적은 현금흐름표에서.")
            st.download_button(
                "⬇️ KDI PIMAC 표준재무모델 양식 CSV — 감사 대조용 납품물",
                build_pimac_standard_table(cf_df).to_csv(index=False).encode('utf-8-sig'),
                file_name="forenode_PIMAC표준재무모델.csv",
                mime="text/csv",
                use_container_width=True,
                key="pimac_export_acct",
            )
            st.caption(
                "납품물 ▸ 위 CSV를 표준 .xlsx에 붙여넣어 주무관청·대주단 모델과 **연도별 셀 단위 대조**. · "
                "심화 ▸ **🏗 시공·자금조달 ▸ 현금흐름**(상세 현금흐름표: EBITDA·DSCR·선순위 DSCR·LLCR + 산정 규약) · "
                "**ℹ️ 분석 가정**(아래 expander)."
            )
        else:  # 전체
            st.caption(
                "전체 보기 — 위 KPI 4종과 검증 요약, 아래 리스크 스냅샷이 종합 요약입니다."
            )

    st.markdown("---")

    # ════════════════════════════════════════════════════════
    # 🔎 가정 검증 오버레이 — 수요 낙관편향 · 예비 신용등급 · 재협상 트리거 (검증 도구)
    # ════════════════════════════════════════════════════════
    with st.expander("🔎 가정 검증 오버레이 — 수요 낙관편향·예비 신용등급·재협상 트리거 (검증 도구)", expanded=False):
        try:
            from demand_bias import demand_optimism_band, prob_ratio_below, BENCHMARK_PRIORS
            from verification_overlays import (implied_rating, renegotiation_triggers,
                                               agreed_return_position, TRIGGER_RULES)
            _vc1, _vc2 = st.columns([3, 2])
            with _vc1:
                st.markdown("**📉 수요 낙관편향 점검**")
                st.caption(
                    "입력 교통량을 과거 실측/예측 분포로 보정해 수요 가정의 낙관 정도를 검증합니다. "
                    "(근거: Bain·S&P 2009 / KOTI 2014 사후평가)"
                )
                _prior = st.selectbox("벤치마크 분포(prior)", list(BENCHMARK_PRIORS.keys()),
                                      key="demand_prior")
                _db = demand_optimism_band(daily_traffic, prior=_prior)
                _icon = {"high": "🔴", "mid": "🟡", "low": "🟢"}.get(_db["level"], "⚪")
                st.markdown(
                    f"입력(예측) **{daily_traffic:,}대/일** → 과거 실적 보정 시 "
                    f"**실제 가능 중앙값 {_db['p50']:,.0f}대/일** (예측의 {_db['median_ratio']*100:.0f}%) · "
                    f"P10~P90 **{_db['p10']:,.0f}~{_db['p90']:,.0f}**")
                st.markdown(f"{_icon} **{_db['flag']}** — 예측 대비 평균 미달폭 약 **{_db['haircut_pct']:.0f}%**")
                _rev_p50 = ann_rev * _db['median_ratio']
                st.caption(
                    f"수입 환산(교통량 선형 가정): 연매출 {ann_rev:,.0f}억 → 보정 중앙값 ≈ **{_rev_p50:,.0f}억**. "
                    f"근거: {_db['source']}")
                st.caption("reference-class 추정 밴드 — 노선별 예측↔실측 매칭 시 정밀화.")
                st.caption(
                    "ⓘ prior는 '교통량' 기준. '수입' 기준은 체계적으로 더 낮음(협약 대비 통행료 수입 "
                    "10년 평균 62.3% vs 교통량 81.4% — KOTI RR-25-10 p.45·p.140) — 수입 검증 시 별도 보정.")
            with _vc2:
                st.markdown("**🏅 예비 신용등급 (근사)**")
                _dmin = metrics.get('dscr_min', float('nan'))
                _ir = implied_rating(_dmin)
                st.metric("최소 DSCR", f"{_dmin:.2f}" if _dmin == _dmin else "—")
                st.markdown(f"→ **{_ir['implied_band']}**")
                st.caption(f"📍 시장 위치: {_ir.get('market_position', '—')}")
                st.caption(_ir['note'])
                st.markdown("**📐 수익률 시장 위치 (양방향)**")
                _rirr = metrics.get('real_irr', float('nan'))
                _ap = agreed_return_position(_rirr)
                _ap_icon = {"over": "🔴", "under": "🔴", "above": "🟡",
                            "low": "🟡", "recent": "🟢", "btoa": "🟢"}.get(_ap["level"], "⚪")
                _rirr_txt = f"{_rirr*100:.1f}%" if _rirr == _rirr else "—"
                st.markdown(f"{_ap_icon} 실질 IRR(세후) **{_rirr_txt}** → {_ap['position']}")
                st.caption(_ap['note'])

            # ⚖️ 재협상 트리거 모니터 — 법정 임계값 대비 점검
            st.markdown("---")
            st.markdown("**⚖️ 재협상 트리거 모니터** — 법정 임계값 대비 점검")
            _tg1, _tg2 = st.columns(2)
            with _tg1:
                _thr = TRIGGER_RULES["ratio_threshold"]
                _p70 = prob_ratio_below(_thr, prior=_prior)
                _p_icon = "🔴" if _p70 >= 0.50 else ("🟡" if _p70 >= 0.25 else "🟢")
                st.markdown(
                    f"{_p_icon} **사전 점검** — 선택한 과거 실적 분포(prior) 기준, 실측이 "
                    f"협약 대비 **{_thr*100:.0f}% 미달에 머물 확률 ≈ {_p70*100:.0f}%**")
                st.caption(
                    "협약 체결 후 3년 연속 교통량·수입이 협약 대비 70% 미달이면 주무관청이 "
                    "실시협약 변경을 요구할 수 있음 — 수요 가정 검증이 곧 재협상 리스크 관리. "
                    "램프업(개통 초기 저조 후 회복) 미반영 보수 추정.")
                st.caption("근거: 유료도로법 §23의5 (KOTI RR-23-19, 2023, pp.151-152)")
            with _tg2:
                st.markdown("**운영 중 사업 점검** — 최근 3개년 실측/협약 비율(%)")
                _ta, _tb, _tc = st.columns(3)
                _r1 = _ta.number_input("2년 전", 0, 200, 100, key="tg_r1")
                _r2 = _tb.number_input("1년 전", 0, 200, 100, key="tg_r2")
                _r3 = _tc.number_input("직전 연도", 0, 200, 100, key="tg_r3")
                _tg = renegotiation_triggers(
                    actual_ratios=[_r1 / 100, _r2 / 100, _r3 / 100])
                _tg_c = _tg["checks"][0]
                if _tg_c["status"] == "trigger":
                    st.error(f"🔴 트리거 성립 — {_tg_c['name']} · {_tg_c['detail']}")
                elif _tg_c["status"] == "watch":
                    st.warning(f"🟡 일부 연도 임계 미달 — {_tg_c['detail']}")
                else:
                    st.success(f"🟢 임계 이상 — {_tg_c['detail']}")
            st.caption(
                "민간투자사업기본계획: 추정 수요 30% 이상 감소 또는 총사업비 20% 이상 증가 시 "
                "민자적격성 재검증 의뢰 대상 (KOTI RR-23-19 pp.185·187). "
                "재구조화로 간 노선의 재구조화 前 실측/예측은 31~70% 수준 (KOTI MP-24-11 pp.65-86).")
        except Exception as _ov_err:
            st.caption(f"검증 오버레이 일시 오류: {_ov_err}")

    st.markdown("---")

    st.markdown("### 🗓️ 사업 시점별 분석 — 단계를 고르면 그 시점의 심화 도구까지 한곳에")
    st.caption(
        "민자도로 라이프사이클 4단계가 주 내비게이션입니다. 각 단계 안에 해당 시점의 심화 도구를 배치했습니다."
    )

    phase_tabs_ui = st.tabs([
        "⏱ 사전 검토", "🏗 시공·자금조달", "🛣 운영", "🔄 재구조화"
    ])

    # ── ⏱ 사전 검토: 단계 브리핑 + 타당성·수요·시장 심화 도구 6종 ──
    with phase_tabs_ui[0]:
        render_phase_pretest(phase_context)
        st.markdown("---")
        st.markdown("##### 🔬 사전 검토 심화 도구")
        tabs_pre = st.tabs([
            "🎯 민감도·리스크 등록부",
            "📊 MC NPV (Monte Carlo)",
            "🌪️ Tornado (민감도)",
            "🔥 통행료 적정성",
            "📋 SPC 벤치마크",
            "🤖 XGBoost 수익성 등급",
        ])
        tab_sensitivity = tabs_pre[0]
        tab_mc = tabs_pre[1]
        tab_tornado = tabs_pre[2]
        tab_toll = tabs_pre[3]
        tab_benchmark = tabs_pre[4]
        tab_xgboost = tabs_pre[5]

        with tab_sensitivity:
            # 지연 import: scenario_engine 이 app.build_cashflow 를 역참조하므로
            # 모듈 상단에서 import 하면 순환 import 발생 → 함수 내부에서 import
            from sensitivity_tab import render_sensitivity_tab
            render_sensitivity_tab(
                base_params,
                daily_traffic=daily_traffic,
                road_length_km=road_length,
                cov_base=cov_base,
                cov_lockup=cov_lockup,
                cov_default=cov_default,
            )

    # ── 🏗 시공·자금조달: 단계 브리핑 + 금융구조·현금흐름 ──
    with phase_tabs_ui[1]:
        render_phase_construction(phase_context)
        st.markdown("---")
        st.markdown("##### 🔬 시공·자금조달 심화 도구")
        tabs_con = st.tabs([
            "🏦 금융구조",
            "📈 현금흐름",
        ])
        tab_finance = tabs_con[0]
        tab_cashflow = tabs_con[1]

    # ── 🛣 운영: 단계 브리핑 + 시설·열화·OPEX ──
    with phase_tabs_ui[2]:
        render_phase_operation(phase_context)
        st.markdown("---")
        st.markdown("##### 🔬 운영 심화 도구")
        tabs_op = st.tabs([
            "📉 열화곡선",
            "🔧 Weibull 열화 분포",
            "💰 OPEX 시계열 모델",
        ])
        tab_deterioration = tabs_op[0]
        tab_weibull = tabs_op[1]
        tab_opex = tabs_op[2]

    # ── 🔄 재구조화: 단계 브리핑 + 요구수익률 솔버·법제 RAG ──
    with phase_tabs_ui[3]:
        render_phase_restructuring(phase_context)
        st.markdown("---")
        st.markdown("##### 🔬 재구조화 심화 도구")
        tabs_rst = st.tabs([
            "🎯 요구수익률 솔버",
            "📚 법제 RAG 자문",
        ])
        tab_solver = tabs_rst[0]
        tab_rag = tabs_rst[1]

        with tab_solver:
            st.markdown(
                """<div style="background:linear-gradient(135deg, #FFF3E0 0%, #FFE0B2 100%);
                    border-left:6px solid #EF9F27;border-radius:8px;
                    padding:12px 18px;margin:8px 0;">
                    <div style="font-size:13px;color:#888;font-weight:600;">━ 전략 의사결정 ━</div>
                    <div style="font-size:18px;font-weight:bold;color:#1F3864;margin-top:2px;">
                        🎯 요구수익률 솔버
                    </div>
                    <div style="font-size:12px;color:#555;margin-top:4px;">
                        5대 고객 그룹별 요구수익률 자동 진단 + 변수 조정 시나리오 자동 도출.
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )
            render_solver_tab(base_params, metrics, build_cashflow, phase_context)
    
    # ── 호환성 매핑: 기존 tabs[0~10] 별칭 (본문 코드 변경 최소화 — 시점 탭 내부로 재배치됨) ──
    tabs = [tab_mc, tab_tornado, tab_cashflow, tab_deterioration, tab_toll,
            tab_finance, tab_benchmark, tab_rag, tab_xgboost, tab_weibull, tab_opex]

    # ━━━━━━━━━━ TAB 1: Monte Carlo ━━━━━━━━━━
    with tabs[0]:
        render_data_flow_banner()
        render_data_flow_diagram()
        st.markdown("---")
        st.subheader("Monte Carlo 시뮬레이션")
        mc_col1, mc_col2 = st.columns([1, 3])

        with mc_col1:
            n_sim = st.slider("시뮬레이션 횟수", 200, 5000, 1000, 100)
            capex_vol = st.slider("사업비 변동성(%)", 1, 30, 10) / 100
            rev_vol = st.slider("수익 변동성(%)", 1, 40, 15) / 100
            rate_vol = st.slider("금리 변동성(%)", 1, 30, 10) / 100

            if st.button("▶ 시뮬레이션 실행", type="primary", use_container_width=True):
                with st.spinner("시뮬레이션 실행 중..."):
                    # 결정론 모델과 동일한 base_params를 그대로 전달 (opex 시계열·만기가치·
                    # 회수방식 등 포함) — monte_carlo가 무작위화하는 5개 키만 제외
                    _mc_randomized = {'capex_억', 'annual_revenue_억',
                                      'discount_rate', 'inflation', 'growth_rate'}
                    mc_extra = {k: v for k, v in base_params.items()
                                if k not in _mc_randomized}
                    mc = monte_carlo(
                        capex_억=total_capex,
                        annual_revenue_억=ann_rev,
                        n_sim=n_sim,
                        discount_rate=wacc_info['wacc'],
                        inflation=infl / 100,
                        growth_rate=growth / 100,
                        capex_volatility=capex_vol,
                        revenue_volatility=rev_vol,
                        rate_volatility=rate_vol,
                        **mc_extra,
                    )
                    st.session_state['mc_results'] = mc

        with mc_col2:
            if 'mc_results' in st.session_state:
                mc = st.session_state['mc_results']

                # 통계
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("평균 NPV", f"{mc['npv_mean']:,.0f}억")
                sc2.metric("NPV 표준편차", f"{mc['npv_std']:,.0f}억")
                sc3.metric("적자 확률", f"{mc['prob_negative_npv']*100:.1f}%")
                sc4.metric("DSCR<1 확률", f"{mc['prob_dscr_below_1']*100:.1f}%")

                # 하방 보강 — VaR(5%)·P10 (단정 아닌 확률·분위로 제시)
                try:
                    from verification_overlays import downside_metrics
                    _dm = downside_metrics(mc.get('npv'), mc.get('dscr'))
                    if 'npv_var5' in _dm:
                        st.caption(
                            f"📉 하방 보강 — NPV VaR(5%, 최악 5분위): **{_dm['npv_var5']:,.0f}억** · "
                            f"NPV P10 {_dm.get('npv_p10', 0):,.0f}억 · DSCR P10 {_dm.get('dscr_p10', 0):.2f}")
                    st.caption(
                        "ⓘ 민감도 변수·범위 참조: KOTI RR-25-10(통행료수입 25~125%·총사업비 70~130%·"
                        "할인율 3~8% 등). 사전 민감도 범위(공사비 85~100%·운영비 80~100%)를 실적"
                        "(106%·70%)이 이탈한 실증 사례 있음(p.163) — 범위는 실적 분포로 보정 권장.")
                except Exception:
                    pass

                if HAS_PLOTLY:
                    fig = make_subplots(rows=1, cols=2,
                                        subplot_titles=["NPV 분포", "DSCR 분포"])
                    fig.add_trace(go.Histogram(x=mc['npv'], nbinsx=40,
                                               marker_color='#667eea', name='NPV'),
                                  row=1, col=1)
                    fig.add_vline(x=0, line_dash="dash", line_color="red", row=1, col=1)
                    fig.add_trace(go.Histogram(x=mc['dscr'], nbinsx=40,
                                               marker_color='#38ef7d', name='DSCR'),
                                  row=1, col=2)
                    fig.add_vline(x=1.0, line_dash="dash", line_color="red", row=1, col=2)
                    fig.update_layout(height=350, showlegend=False,
                                      template="plotly_white",
                                      margin=dict(t=40, b=30))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.bar_chart(pd.DataFrame({'NPV': mc['npv'][:200]}))
            else:
                st.info("왼쪽 패널에서 파라미터 설정 후 '시뮬레이션 실행'을 클릭하세요")

    # ━━━━━━━━━━ TAB 2: Tornado ━━━━━━━━━━
    with tabs[1]:
        st.subheader("Tornado 민감도 분석")
        tornado = tornado_analysis(base_params, variation=0.20)

        if tornado and HAS_PLOTLY:
            fig = go.Figure()
            for item in tornado:
                fig.add_trace(go.Bar(
                    y=[item['param']],
                    x=[item['high_npv'] - item['base_npv']],
                    base=[item['base_npv']],
                    orientation='h', name=f"{item['param']} +20%",
                    marker_color='#38ef7d', showlegend=False,
                ))
                fig.add_trace(go.Bar(
                    y=[item['param']],
                    x=[item['low_npv'] - item['base_npv']],
                    base=[item['base_npv']],
                    orientation='h', name=f"{item['param']} -20%",
                    marker_color='#eb3349', showlegend=False,
                ))
            fig.add_vline(x=metrics['npv'], line_dash="dash", line_color="white")
            fig.update_layout(height=400, template="plotly_white",
                              xaxis_title="NPV (억원)", barmode='overlay',
                              margin=dict(t=20, b=30))
            st.plotly_chart(fig, use_container_width=True)
        elif tornado:
            df_t = pd.DataFrame(tornado)
            st.dataframe(df_t[['param', 'low_npv', 'base_npv', 'high_npv', 'spread']])

    # ━━━━━━━━━━ TAB 3: 현금흐름 ━━━━━━━━━━
    with tabs[2]:
        st.subheader("연도별 현금흐름")
        
        if HAS_PLOTLY:
            fig = make_subplots(rows=2, cols=1,
                                subplot_titles=["프로젝트 FCF & 누적FCF", "DSCR 추이"],
                                row_heights=[0.65, 0.35], vertical_spacing=0.1)

            fig.add_trace(go.Bar(x=cf_df['Year'], y=cf_df['ProjectFCF'],
                                 name='FCF', marker_color='#667eea'), row=1, col=1)
            fig.add_trace(go.Scatter(x=cf_df['Year'], y=cf_df['CumProjectFCF'],
                                     name='누적FCF', line=dict(color='#ffd200', width=2)),
                          row=1, col=1)
            fig.add_hline(y=0, line_dash="dash", line_color="gray", row=1, col=1)

            op_df = cf_df[cf_df['DSCR'] > 0]
            fig.add_trace(go.Scatter(x=op_df['Year'], y=op_df['DSCR'],
                                     name='DSCR', line=dict(color='#38ef7d', width=2),
                                     fill='tozeroy', fillcolor='rgba(56,239,125,0.1)'),
                          row=2, col=1)
            fig.add_hline(y=1.0, line_dash="dash", line_color="red", row=2, col=1)
            fig.add_hline(y=1.3, line_dash="dot", line_color="orange", row=2, col=1)

            fig.update_layout(height=550, template="plotly_white",
                              margin=dict(t=40, b=30))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.line_chart(cf_df.set_index('Year')[['ProjectFCF', 'CumProjectFCF']])

        # ── OPEX 불확실성 밴드 (Weibull CI 전파) ──
        if opex_band:
            st.markdown("##### 🎚️ OPEX 불확실성 밴드 (P10–P90)")
            if dscr_band and all(v is not None for v in dscr_band.values()):
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("DSCR · 낙관 (P10 OPEX)", f"{dscr_band['best']:.2f}")
                dc2.metric("DSCR · 기준 (P50)", f"{dscr_band['base']:.2f}")
                dc3.metric("DSCR · 보수 (P90 OPEX)", f"{dscr_band['worst']:.2f}")
            yrs = list(range(1, len(opex_band['p50']) + 1))
            if HAS_PLOTLY:
                bf = go.Figure()
                bf.add_trace(go.Scatter(x=yrs, y=opex_band['p90'], line=dict(width=0),
                                        showlegend=False, hoverinfo='skip'))
                bf.add_trace(go.Scatter(x=yrs, y=opex_band['p10'], fill='tonexty',
                                        fillcolor='rgba(31,56,100,0.15)', line=dict(width=0),
                                        name='P10–P90'))
                bf.add_trace(go.Scatter(x=yrs, y=opex_band['p50'],
                                        line=dict(color='#1F3864', width=2), name='P50(기준)'))
                bf.update_layout(height=240, template="plotly_white",
                                 margin=dict(t=10, b=20, l=10, r=10),
                                 yaxis_title="OPEX(억/년)", xaxis_title="운영연차")
                st.plotly_chart(bf, use_container_width=True)
            else:
                st.line_chart(pd.DataFrame(
                    {'P10': opex_band['p10'], 'P50': opex_band['p50'], 'P90': opex_band['p90']},
                    index=yrs))
            st.caption(f"※ Weibull 특성수명 CI(η) + 단가 불확실성 전파 (1차 level 밴드, {opex_band['source']}, "
                       f"n={opex_band['n_sims']}). 타이밍-수준 MC(semi-Markov)는 후순위.")

        with st.expander("📋 상세 현금흐름표"):
            display_cols = ['Year', 'CAPEX', 'Revenue', 'OPEX', 'EBITDA', 'Interest',
                           'Principal', 'Tax', 'NetIncome', 'ProjectFCF',
                           'CumProjectFCF', 'DSCR', 'SeniorDSCR', 'LLCR']
            st.dataframe(cf_df[display_cols].style.format({
                col: '{:,.1f}' for col in display_cols if col != 'Year'
            }), use_container_width=True)

            with st.expander("ⓘ EBITDA·LLCR 산정 규약"):
                st.markdown(
                    "- **EBITDA** = 매출 − 운영비 (감가상각·이자·세금 전). 대주단 표준 현금흐름 대용.\n"
                    "- **LLCR**(Loan Life Coverage Ratio) = 해당 연도 이후 잔여 CFADS의 현재가치(부채금리 할인) "
                    "÷ 잔존 부채. CFADS = 매출 − 운영비 − 세금(= DSCR 분자와 동일 정의).\n"
                    "- 이 표의 LLCR은 **연말 잔존부채** 기준, 🎯 민감도·리스크 탭의 LLCR_min은 "
                    "**연초(=직전 연도 말) 잔존부채** 기준 — 시점 규약 차이로 소수점 차이가 발생할 수 있습니다."
                )

    # ━━━━━━━━━━ TAB 4: 열화곡선 ━━━━━━━━━━
    with tabs[3]:
        st.subheader("시설물 열화곡선 & LCC 유지관리비")

        det_df = generate_deterioration_data(operation_years)

        if HAS_PLOTLY:
            fig = px.line(det_df, x='Year', y='PI', color='Material',
                          title="재료별 성능지수(PI) 열화곡선",
                          labels={'PI': '성능지수 (0-100)', 'Year': '경과년수'})
            fig.add_hline(y=40, line_dash="dash", line_color="orange",
                          annotation_text="대보수 기준 (PI=40)")
            fig.add_hline(y=20, line_dash="dash", line_color="red",
                          annotation_text="교체 기준 (PI=20)")
            fig.update_layout(height=400, template="plotly_white",
                              margin=dict(t=50, b=30))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.line_chart(det_df.pivot(index='Year', columns='Material', values='PI'))

        st.markdown("---")
        st.subheader("LCC 유지관리비 추정")
        # 현금흐름과 동일 물량·엔진(config 톱니파형) 기준으로 표시
        _q_disp = bim_quantities if bim_quantities else quantities_from_road_length(road_length)
        lcc_df, lcc_total = estimate_lcc_sawtooth_from_config(
            _q_disp, operation_years, wacc_info['wacc'])
        if bim_quantities:
            st.caption("물량 출처: 업로드된 BIM(IFC) 형상 추출 · 주기/수선율: 별표5(config)")
        else:
            st.caption("물량: 연장 기반 추정 · 주기/수선율: 별표5(config)")

        if opex_source.startswith("물량기반 LCC"):
            st.success(f"✅ [C1] 이 LCC 자본적 유지보수가 현금흐름 OPEX로 직결되어 DSCR에 반영됩니다 "
                       f"(상향식 모드 · {opex_source}). 총 OPEX = 일상 O&M(가정) + 아래 LCC.")
        else:
            st.info("ℹ️ 현재 현금흐름 OPEX는 '자동(매출비례)' 모드입니다. 사이드바에서 "
                    "'물량기반 LCC (상향식·실험)'를 선택하면 아래 LCC가 DSCR에 직결됩니다(C1).")

        if len(lcc_df) > 0:
            lc1, lc2 = st.columns([1, 2])
            with lc1:
                st.metric("유지관리비 현가 합계", f"{lcc_total:,.0f}억원")
                st.metric("연평균 유지관리비", f"{lcc_total/operation_years:,.1f}억원/년")
                st.caption("※ 2026 표준품셈 단가 기준 추정 · 연장기반 추정물량(BIM 연결 시 정밀화)")
            with lc2:
                yearly_lcc = lcc_df.groupby('Year')['PV_억'].sum().reset_index()
                if HAS_PLOTLY:
                    fig = px.bar(yearly_lcc, x='Year', y='PV_억',
                                 title="연도별 유지관리비 (현가)",
                                 labels={'PV_억': '비용(억원)'})
                    fig.update_layout(height=300, template="plotly_white")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.bar_chart(yearly_lcc.set_index('Year'))

            with st.expander("📋 유지관리 상세"):
                st.dataframe(lcc_df, use_container_width=True)

    # ━━━━━━━━━━ TAB 5: 통행료 ━━━━━━━━━━
    with tabs[4]:
        st.subheader("통행료 수입 추정")

        tc1, tc2 = st.columns([2, 1])
        with tc1:
            if HAS_PLOTLY:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Bar(x=toll_df['Year'], y=toll_df['Revenue_억'],
                                     name='통행료수입(억)', marker_color='#667eea'),
                              secondary_y=False)
                fig.add_trace(go.Scatter(x=toll_df['Year'], y=toll_df['DailyTraffic'],
                                         name='일교통량(대)',
                                         line=dict(color='#ffd200', width=2)),
                              secondary_y=True)
                fig.update_layout(height=350, template="plotly_white",
                                  margin=dict(t=30, b=30))
                fig.update_yaxes(title_text="수입(억원)", secondary_y=False)
                fig.update_yaxes(title_text="교통량(대/일)", secondary_y=True)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.bar_chart(toll_df.set_index('Year')['Revenue_억'])

        with tc2:
            st.metric("초년도 수입", f"{toll_df['Revenue_억'].iloc[0]:,.0f}억원")
            st.metric("말년도 수입", f"{toll_df['Revenue_억'].iloc[-1]:,.0f}억원")
            st.metric("누적 수입", f"{toll_df['Revenue_억'].sum():,.0f}억원")
            st.metric("CAGR",
                       f"{((toll_df['Revenue_억'].iloc[-1]/toll_df['Revenue_억'].iloc[0])**(1/operation_years)-1)*100:.2f}%")
        
        # ════════════════════════════════════════════════════════
        # 보완 8: 사용료 적정성 기준 (정부 기준 + 사회수용 영역)
        # 2024.10 정부 활성화 방안: 도로사업의 적정 사용료 = 도공 대비 1.1배 이내
        # ════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("##### 🚦 사용료 적정성 기준 — 정부 정책 부합 검증")
        st.caption(
            "**2024.10 정부 활성화 방안**: 민자도로 통행료 적정 수준 = **한국도로공사 대비 1.1배 이내**."
        )
        
        # 도로공사 km당 통행료 기준 (2024 표준)
        koex_toll_per_km = 60  # 원/km (한국도로공사 평균)
        govt_ceiling = koex_toll_per_km * 1.1  # 도공 1.1배
        social_acceptance_low = koex_toll_per_km * 0.8  # 사회수용 최소
        social_acceptance_high = koex_toll_per_km * 1.3  # 사회수용 최대
        
        col_t1, col_t2, col_t3, col_t4 = st.columns(4)
        col_t1.metric(
            "현재 통행료",
            f"{toll_per_km} 원/km",
            help="사이드바에서 설정한 km당 통행료",
        )
        col_t2.metric(
            "도공 평균",
            f"{koex_toll_per_km} 원/km",
            help="한국도로공사 운영 고속도로 평균 (2024)",
        )
        col_t3.metric(
            "정부 적정 상한",
            f"{govt_ceiling:.0f} 원/km",
            delta=f"도공 ×1.1",
            help="2024.10 정부 활성화 방안 기준",
        )
        
        # 적정성 판정
        ratio_to_koex = toll_per_km / koex_toll_per_km
        if ratio_to_koex <= 1.1:
            verdict = "🟢 적정"
            verdict_color = "#1B5E20"
            verdict_bg = "#E8F5E9"
            verdict_msg = f"도공 대비 **{ratio_to_koex:.2f}배** — 정부 적정 기준(1.1배) 이내. 이익공유 대상 제외 가능."
        elif ratio_to_koex <= 1.3:
            verdict = "🟡 경계"
            verdict_color = "#E65100"
            verdict_bg = "#FFF3E0"
            verdict_msg = f"도공 대비 **{ratio_to_koex:.2f}배** — 정부 적정 기준 초과(1.1배), 사회수용 한계 근접. 통행료 협상 가능성."
        else:
            verdict = "🔴 사회수용 한계 초과"
            verdict_color = "#B71C1C"
            verdict_bg = "#FFCDD2"
            verdict_msg = f"도공 대비 **{ratio_to_koex:.2f}배** — 사회수용 한계 초과. 통행료 인하 협상 또는 정부 보전 필요."
        
        col_t4.metric("적정성 판정", verdict)
        
        st.markdown(
            f"""<div style="background:{verdict_bg};border-left:5px solid {verdict_color};
                padding:12px 16px;border-radius:6px;margin:8px 0;">
                <div style="font-size:13px;color:#333;">
                    {verdict_msg}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        
        # 사회수용 영역 시각화
        if HAS_PLOTLY:
            fig_zone = go.Figure()
            
            # 사회수용 영역 (배경)
            fig_zone.add_shape(
                type="rect",
                x0=0, x1=1, y0=social_acceptance_low, y1=govt_ceiling,
                xref="paper", yref="y",
                fillcolor="#E8F5E9", opacity=0.5, line_width=0,
                layer="below",
            )
            fig_zone.add_shape(
                type="rect",
                x0=0, x1=1, y0=govt_ceiling, y1=social_acceptance_high,
                xref="paper", yref="y",
                fillcolor="#FFF3E0", opacity=0.5, line_width=0,
                layer="below",
            )
            fig_zone.add_shape(
                type="rect",
                x0=0, x1=1, y0=social_acceptance_high, y1=social_acceptance_high * 1.5,
                xref="paper", yref="y",
                fillcolor="#FFCDD2", opacity=0.4, line_width=0,
                layer="below",
            )
            
            # 기준선 3개
            fig_zone.add_hline(y=koex_toll_per_km, line_dash="dash", line_color="#1F3864",
                              annotation_text=f"도공 평균 {koex_toll_per_km}원/km", annotation_position="right")
            fig_zone.add_hline(y=govt_ceiling, line_dash="dash", line_color="#E65100",
                              annotation_text=f"정부 상한 {govt_ceiling:.0f}원/km (×1.1)", annotation_position="right")
            fig_zone.add_hline(y=social_acceptance_high, line_dash="dash", line_color="#D32F2F",
                              annotation_text=f"사회수용 한계 {social_acceptance_high:.0f}원/km (×1.3)", annotation_position="right")
            
            # 현재 통행료 표시
            fig_zone.add_trace(go.Scatter(
                x=[0.5], y=[toll_per_km],
                mode='markers+text',
                marker=dict(size=20, color='#EF9F27', line=dict(color='#1F3864', width=2)),
                text=[f"<b>현재 {toll_per_km}원/km</b>"],
                textposition='top center',
                name='현재 통행료',
            ))
            
            fig_zone.update_layout(
                title="통행료 적정성 영역 (도공 대비 ×1.1 정부 기준)",
                yaxis_title="통행료 (원/km)",
                xaxis=dict(visible=False),
                height=320,
                margin=dict(t=50, b=20, l=40, r=180),
                showlegend=False,
                yaxis=dict(range=[0, max(toll_per_km, social_acceptance_high) * 1.2]),
            )
            st.plotly_chart(fig_zone, use_container_width=True)
        

    # ━━━━━━━━━━ TAB 6: 금융구조 ━━━━━━━━━━
    with tabs[5]:
        st.subheader("금융구조 & WACC 분석")

        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("#### WACC 구성")
            wacc_data = pd.DataFrame({
                '항목': ['무위험수익률(Rf)', '시장리스크프리미엄', '베타(β)',
                        '자기자본비용(Ke)', '타인자본비용(Kd)', '법인세율',
                        '자기자본비중', '타인자본비중', '**WACC**'],
                '값': [f"{wacc_info['rf']*100:.2f}%", f"{wacc_info['mrp']*100:.2f}%",
                       f"{wacc_info['beta']:.2f}", f"{wacc_info['ke']*100:.2f}%",
                       f"{wacc_info['kd']*100:.2f}%", f"{wacc_info['tax_rate']*100:.0f}%",
                       f"{wacc_info['equity_weight']*100:.1f}%",
                       f"{wacc_info['debt_weight']*100:.1f}%",
                       f"**{wacc_info['wacc']*100:.2f}%**"],
            })
            st.dataframe(wacc_data, use_container_width=True, hide_index=True)

        with fc2:
            st.markdown("#### 자본구조")
            equity_amt = total_capex * equity_ratio
            debt_amt = total_capex * (1 - equity_ratio)
            
            if HAS_PLOTLY:
                fig = go.Figure(data=[go.Pie(
                    labels=['자기자본', '타인자본'],
                    values=[equity_amt, debt_amt],
                    marker_colors=['#38ef7d', '#667eea'],
                    hole=0.5,
                    textinfo='label+percent',
                )])
                fig.update_layout(height=300, template="plotly_white",
                                  margin=dict(t=20, b=20))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write(f"자기자본: {equity_amt:,.0f}억 ({equity_ratio*100:.0f}%)")
                st.write(f"타인자본: {debt_amt:,.0f}억 ({(1-equity_ratio)*100:.0f}%)")

        # 부채상환 스케줄
        st.markdown("#### 부채상환 스케줄")
        debt_df = cf_df[cf_df['DebtBalance'] > 0][['Year', 'Interest', 'Principal', 'DebtBalance']]
        if HAS_PLOTLY and len(debt_df) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=debt_df['Year'], y=-debt_df['Interest'],
                                 name='이자', marker_color='#eb3349'))
            fig.add_trace(go.Bar(x=debt_df['Year'], y=-debt_df['Principal'],
                                 name='원금', marker_color='#f45c43'))
            fig.add_trace(go.Scatter(x=debt_df['Year'], y=debt_df['DebtBalance'],
                                     name='잔액', yaxis='y2',
                                     line=dict(color='#ffd200', width=2)))
            fig.update_layout(
                height=350, template="plotly_white", barmode='stack',
                yaxis=dict(title='상환액(억)'),
                yaxis2=dict(title='잔액(억)', overlaying='y', side='right'),
                margin=dict(t=30, b=30),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ━━━━━━━━━━ TAB 7: 벤치마크 ━━━━━━━━━━
    with tabs[6]:
        st.subheader("감사보고서 기반 벤치마크 비교")
        st.caption("2025년 감사보고서 실적 (단위: 억원)")

        bm_df = pd.DataFrame(BENCHMARKS).T
        bm_df.index.name = '사업'

        # 현재 시나리오 추가
        current = {
            "연장": road_length, "운영개시": 2026, "잔여": operation_years,
            "영업수익": round(ann_rev, 0),
            "통행료": round(ann_rev, 0),
            "보조금": 0,
            "영업비용": round(ann_rev * 0.35, 0),
            "영업이익": round(ann_rev * 0.65, 0),
            "순이익": round(metrics.get('npv', 0) / operation_years, 0),
            "차입금": round(total_capex * (1 - equity_ratio), 0),
            "자본": round(total_capex * equity_ratio, 0),
            "DSCR": round(metrics['dscr_avg'], 2),
            "이자비용": round(total_capex * (1-equity_ratio) * debt_rate, 0),
            "배당": 0,
        }
        bm_df.loc["현재 시나리오"] = current

        st.dataframe(bm_df.style.format({
            col: '{:,.0f}' for col in bm_df.columns if col not in ['DSCR', '연장']
        }).format({'DSCR': '{:.2f}', '연장': '{:.1f}'}),
        use_container_width=True)

        if HAS_PLOTLY:
            compare_metrics = ['영업수익', '영업이익', '차입금', '이자비용']
            fig = go.Figure()
            for name in bm_df.index:
                fig.add_trace(go.Bar(
                    x=compare_metrics,
                    y=[bm_df.loc[name, m] for m in compare_metrics],
                    name=name,
                ))
            fig.update_layout(height=350, template="plotly_white",
                              barmode='group', margin=dict(t=30, b=30),
                              yaxis_title="억원")
            st.plotly_chart(fig, use_container_width=True)

    # ───────── TAB 8: 법제 RAG ─────────  
    with tabs[7]:                             
        render_rag_tab()

    with tabs[8]:
        render_xgboost_tab()

    with tabs[9]:
        render_weibull_tab()

    with tabs[10]:
        render_opex_tab()
        
    # ── 하단 정보 ──
    st.markdown("---")
    st.caption(
        "Forenode — 공공데이터 기반 민자도로 수익성·적정성 검증 · "
        "2026 표준품셈 · DART 벤치마크 · ECOS 연동 · BIM(IFC) 선택 입력"
    )


if __name__ == "__main__":
    main()
