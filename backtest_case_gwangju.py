# -*- coding: utf-8 -*-
"""
백테스트 케이스 #2 — 광주-원주 고속도로 (제이영동고속도로(주))

R1~R7 적용. 인천공항(V-001)과 동일 방법, 결측 항목은 명시 후 생략.
계획: 최초 실시협약 2008.5.30 · 협약수익률 불변세후 4.83%(RR-25-10 표2-3) ·
      계획 총사업비 14,062억=민간 11,914+보조 2,148 (2009.3 국토해양부, NABO ✚기준미상)
실제: 감사보고서 FY2018~25 로컬 파싱(정정 반영) · 실측 교통량 '19~'24(국토부·KOTI) ·
      준공 보도 총사업비 15,978억(✚정산 여부 미상)
"""
import numpy as np
from backtest_plan_actual import loo_prior, load_engine, pct_err, reconstructed_irr

# ── 교통량 (대/일) — 협약 '19~'21은 공표 비율에서 역산(✚), '22~'24는 원표 ──
PLAN_TRAFFIC = {2019: 58457, 2020: 58460, 2021: 58919,   # ✚역산 (실측÷공표비율)
                2022: 59373, 2023: 59846, 2024: 60320}   # RR-25-10 표5-11 원표
ACT_TRAFFIC = {2019: 45830, 2020: 43903, 2021: 45957,
               2022: 47640, 2023: 48151, 2024: 49529}
# 2017~2018 실측·협약 공백 (국토부 20년 통행량 정책자료 — WAF, 수동 확보 대상)

# ── 재무 (억원, 감사보고서 최신 재작성 기준) ──
REV_TOTAL = {2018: 683.4, 2019: 718.5, 2020: 693.8, 2021: 728.4,
             2022: 746.3, 2023: 797.2, 2024: 875.5, 2025: 907.0}
TOLL = {2018: 576.6, 2019: 611.3, 2020: 587.8, 2021: 620.4,
        2022: 631.9, 2023: 630.0, 2024: 651.1, 2025: 650.6}
SUBSIDY = {2018: 7.2, 2019: 21.8, 2020: 29.9, 2021: 32.2,
           2022: 28.2, 2023: 74.5, 2024: 131.3, 2025: 161.6}  # 미인상·면제 통행료 재정지원
OPEX_TOT = {2018: 491.5, 2019: 523.3, 2020: 498.9, 2021: 511.4,
            2022: 511.6, 2023: 523.4, 2024: 520.9, 2025: 578.3}
AMORT = {2018: 195.1, 2019: 195.1, 2020: 372.8, 2021: 372.8,
         2022: 372.8, 2023: 372.8, 2024: 372.8, 2025: 372.8}  # 2018~19는 구 기준(✚)
CASH_OPEX = {y: round(OPEX_TOT[y] - AMORT[y], 1) for y in OPEX_TOT}

PLAN_RETURN = 4.83          # 불변 세후 (RR-25-10)
PLAN_CAPEX_TOTAL = 14062.0  # 계획 총사업비 (2009.3, ✚불변/경상 미상)
PLAN_CAPEX_PRIVATE = 11914.0
ACT_CAPEX = 15978.0         # 준공 보도 (✚정산 여부 미상)
LEN_KM = 56.95
TAX_EFF = 0.242
CPI = {2008: 81.7, 2012: 91.8, 2013: 93.0, 2014: 94.2, 2015: 94.9, 2016: 95.8,
       2017: 97.6, 2018: 99.1, 2019: 99.5, 2020: 100.0, 2021: 102.5, 2022: 107.7,
       2023: 111.6, 2024: 114.2, 2025: 116.4}
# ※ CPI 2008=81.7 근사(통계청 2020=100), 2026~ 연 2.0% 가정


def main():
    pri = loo_prior('광주-원주')
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd
    print(f"[LOO prior — 광주-원주 제외] 평균 {mu*100:.1f}% · SD {sd:.4f} · n={pri['loo_n']} "
          f"(밴드 {p10r*100:.0f}~{p90r*100:.0f}%)")

    # ══ 표① 교통량 연도별 ══
    print('\n' + '=' * 88)
    print('표① 교통량 — 협약(A) vs Forenode P50(B) vs 실측 · 오차 = (실측-추정)/추정')
    print('=' * 88)
    print(f"{'연도':>5} {'협약':>8} {'실측':>8} {'오차A%':>8} {'B:P50':>8} {'오차B%':>8} {'밴드':>6}")
    eA, eB, hits = [], [], 0
    for y in sorted(PLAN_TRAFFIC):
        p, a = PLAN_TRAFFIC[y], ACT_TRAFFIC[y]
        b = p * mu
        ea, eb = pct_err(a, p), pct_err(a, b)
        hit = p10r <= a / p <= p90r
        hits += hit
        eA.append(abs(ea)); eB.append(abs(eb))
        mark = '✚' if y <= 2021 else ''
        print(f"{y:>5} {p:>8,}{mark} {a:>8,} {ea:>7.1f}% {b:>8,.0f} {eb:>7.1f}% {'적중' if hit else '미적중':>5}")
    print(f"\n  ▶ MAE: 협약(A) {np.mean(eA):.1f}% vs Forenode P50(B) {np.mean(eB):.1f}% "
          f"· 밴드 적중 {hits}/{len(eA)}")

    # ══ 통행료수입 (협약수입 재구성 ✚: 협약교통량 × 실측 평균단가) ══
    unit = TOLL[2019] * 1e8 / (ACT_TRAFFIC[2019] * 365)  # '19 실측 평균단가(원/대)
    print('\n' + '=' * 88)
    print(f'표② 통행료수입 (협약수입 = 협약교통량 × 실측단가 {unit:,.0f}원/대 ✚재구성)')
    print('=' * 88)
    print(f"{'연도':>5} {'협약수입':>8} {'실제수입':>8} {'오차A%':>8} {'B:P50':>8} {'오차B%':>8}")
    for y in sorted(PLAN_TRAFFIC):
        if y not in TOLL:
            continue
        prev = PLAN_TRAFFIC[y] * 365 * unit / 1e8
        b = prev * mu
        print(f"{y:>5} {prev:>8,.0f} {TOLL[y]:>8,.1f} {pct_err(TOLL[y], prev):>7.1f}% "
              f"{b:>8,.0f} {pct_err(TOLL[y], b):>7.1f}%")

    # ══ 운영비 — 협약 계획 미공개 → A 불가, B(통계모드) vs 실측 ══
    print('\n' + '=' * 88)
    print('표③ 운영비 — 협약 계획 미공개(오차A 산출 불가) · Forenode 통계모드(B) vs 실측')
    print('=' * 88)
    import opex_estimator
    act_5y = float(np.mean([CASH_OPEX[y] for y in range(2020, 2025)]))  # '20~'24 (구 회계기준 '18~'19 제외)
    rev1 = PLAN_TRAFFIC[2019] * 365 * unit / 1e8
    est = opex_estimator.estimate_opex_series('BTO', annual_revenue_억=rev1, operation_years=30,
                                              terrain='산지', tunnel_ratio=0.15, bridge_ratio=0.10,
                                              growth_rate=0.008, inflation=0.0, road_length_km=LEN_KM)
    b_opex = float(np.mean(est['opex_series_억']))
    print(f"  실측 현금 OPEX('20~'24 평균): {act_5y:.0f}억/년 (경상) · 원단위 {act_5y/LEN_KM:.1f}억/km/년")
    print(f"  Forenode 통계모드: {b_opex:.0f}억/년 → 오차B {pct_err(act_5y, b_opex):+.1f}%")
    if est.get('warning'):
        print(f"  ⚠ L3 크로스체크: {est['warning']}")

    # ══ 투자비 ══
    print('\n' + '=' * 88)
    print('표④ 투자비 — 계획 14,062억(2009.3 ✚기준미상) vs 준공 보도 15,978억(✚정산미상)')
    print('=' * 88)
    print(f"  오차A {pct_err(ACT_CAPEX, PLAN_CAPEX_TOTAL):+.1f}% (판정 보류 병기 — 불변/경상·보상비 포함 여부 미확정)")

    # ══ 수익률 (R7 재구성) ══
    print('\n' + '=' * 88)
    print('표⑤ 수익률 — 협약 4.83%(불변 세후) vs 재구성 실현 IRR')
    print('=' * 88)
    cf = {}
    for y in range(2012, 2017):  # 건설 5년 균등 가정(✚실집행 연도별 미확보)
        cf[y] = cf.get(y, 0.0) - ACT_CAPEX / 5
    years_op = list(range(2017, 2047))  # 운영 30년 (2046.11 종료)
    for y in years_op:
        if y == 2017:
            rev, opx = REV_TOTAL[2018], CASH_OPEX[2018]  # ✚2017=2018 가정
        elif y in REV_TOTAL:
            rev, opx = REV_TOTAL[y], CASH_OPEX[y]
        else:
            rev, opx = REV_TOTAL[2025], CASH_OPEX[2025]  # 잔여기간 현행 유지
        tax = TAX_EFF * max(0.0, rev - opx - 372.8)
        cf[y] = cf.get(y, 0.0) + rev - opx - tax
    def cpi(y):
        if y in CPI:
            return CPI[y]
        return CPI[2025] * (1.02 ** (y - 2025))
    cf_real = {y: v * CPI[2008] / cpi(y) for y, v in cf.items()}
    irr_real = reconstructed_irr(cf_real, base_year=2008)
    irr_nom = reconstructed_irr(cf, base_year=2008)
    print(f"  재구성 실현 IRR: 실질 {irr_real*100:.2f}% · 명목 {irr_nom*100:.2f}% (세후)")
    print(f"  오차A (실질, vs 협약 4.83%): {pct_err(irr_real*100, PLAN_RETURN):+.1f}%")

    # B-IRR: 엔진 (수요 P50 보정, 협약 OPEX 미공개라 실측 원단위 대용 불가 →
    #        v1 배포 형태 그대로 = 통계모드 OPEX. MRG 없음)
    build_cashflow = load_engine()
    rows = {}
    for tag, ratio in [('P10', p10r), ('P50', mu), ('P90', p90r)]:
        _cf, m = build_cashflow(
            capex_억=PLAN_CAPEX_PRIVATE, annual_revenue_억=rev1 * ratio,
            construction_years=5, operation_years=30,
            opex_series_억=np.array(est['opex_series_억']),
            discount_rate=0.0483, inflation=0.0, growth_rate=0.008,
            equity_ratio=0.25, debt_rate=0.055, business_type='BTO', mrg_ratio=0.0,
        )
        rows[tag] = m['real_irr'] * 100
        print(f"  B-{tag} (실현율 {ratio*100:.0f}%): 세후실질 IRR {m['real_irr']*100:.2f}%")
    print(f"  ▶ 오차: A(협약 4.83%) vs 실현 {irr_real*100:.2f}% → {pct_err(irr_real*100, 4.83):+.1f}% / "
          f"B-P50({rows['P50']:.2f}%) vs 실현 → {pct_err(irr_real*100, rows['P50']):+.1f}%")

    # 관찰: 미인상 보조금 누적
    sub_cum = sum(SUBSIDY.values())
    print(f"\n[관찰] 미인상·면제 통행료 재정지원 누적('18~'25): {sub_cum:,.1f}억 — "
          f"연 7.2억('18)→161.6억('25) 급증. MRG 없는 노선에서도 통행료 동결 비용이 재정으로 전이")


if __name__ == '__main__':
    main()
