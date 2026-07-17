# -*- coding: utf-8 -*-
"""
백테스트 케이스 #3 — 천안-논산 고속도로 (천안논산고속도로(주))

R1~R7 적용 + R1 부칙(재구조화 구간 분리) 첫 적용.
계획: 최초 실시협약 1997.4.3 · 협약수익률 세후 9.24%(RR-25-10) ·
      계획 총사업비 15,953억=민간 11,589+국고 4,364(✚기준연도 미확인) ·
      MRG 82%/110% 20년(MKIF 공시)
실제: 협약·실측 교통량 11개년(NABO 표5·KOTI 이슈페이퍼 표3-3·표5-11) ·
      감사보고서 FY2018~25 로컬 파싱 · 재구조화 2019.12.18 변경협약(요금 -48%, 기간 연장 없음)
수익률 재구성: 보류 — FY2003~2017 수입 시계열 미확보 (DART 원문 확보 후 산출)
"""
import numpy as np
from backtest_plan_actual import loo_prior, pct_err
import demand_bias

# 협약·실측 (대/일) — '08~'16·'20~'21 공백
PLAN = {2003: 46423, 2004: 48081, 2005: 50344, 2006: 53692, 2007: 55624,
        2017: 80674, 2018: 82842, 2019: 84830,
        2022: 90036, 2023: 90036, 2024: 90036}
ACT = {2003: 21854, 2004: 25189, 2005: 27554, 2006: 30017, 2007: 32390,
       2017: 52806, 2018: 53276, 2019: 54355,
       2022: 57995, 2023: 59346, 2024: 58819}
OPEN_YEAR = 2003  # 개통 2002.12.24 → 1년차 = 2003
RESTRUCT = 2020   # 2019.12.23 요금 반값 시행 → 2020~ 변경체제

# 재무 (억원, 감사보고서 로컬 파싱 — 교차검증 통과)
CASH_OPEX = {2018: 340.9, 2019: 362.6, 2020: 341.6, 2021: 377.5,
             2022: 383.9, 2023: 429.8, 2024: 468.0, 2025: 426.4}
LEN_KM = 81.0

def main():
    pri = loo_prior('천안-논산')
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd
    init = demand_bias.BENCHMARK_PRIORS['도로 — 국내 민자 보수(초기군)']
    mu0 = init['median_ratio']  # 0.55 (개통 초기 전용)
    print(f"[LOO prior — 천안-논산 제외] 평균 {mu*100:.1f}% SD {sd:.4f} n={pri['loo_n']} "
          f"(밴드 {p10r*100:.0f}~{p90r*100:.0f}%) · 초기군 prior 중앙값 {mu0*100:.0f}%")

    print('\n' + '=' * 96)
    print('표① 교통량 — 협약(A) vs Forenode(B: 1~3년차 초기군·4년차+ LOO) vs 실측')
    print('=' * 96)
    print(f"{'연도':>5} {'연차':>4} {'체제':>4} {'협약':>8} {'실측':>8} {'오차A%':>8} {'B적용':>6} {'B:P50':>8} {'오차B%':>8} {'밴드':>5}")
    eA, eB, hits, n = [], [], 0, 0
    eA_orig, eB_orig = [], []  # 최초협약 체제만
    for y in sorted(PLAN):
        age = y - OPEN_YEAR + 1
        regime = '변경' if y >= RESTRUCT else '최초'
        p, a = PLAN[y], ACT[y]
        use0 = age <= 3
        m = mu0 if use0 else mu
        b = p * m
        ea, eb = pct_err(a, p), pct_err(a, b)
        lo, hi = (0.37, 0.81) if use0 else (p10r, p90r)  # 초기군 lognormal P10/P90
        hit = lo <= a / p <= hi
        hits += hit; n += 1
        eA.append(abs(ea)); eB.append(abs(eb))
        if regime == '최초':
            eA_orig.append(abs(ea)); eB_orig.append(abs(eb))
        print(f"{y:>5} {age:>4} {regime:>4} {p:>8,} {a:>8,} {ea:>7.1f}% {'초기군' if use0 else 'LOO':>5} "
              f"{b:>8,.0f} {eb:>7.1f}% {'적중' if hit else '미적중':>4}")
    print(f"\n  ▶ MAE (11개년): 협약(A) {np.mean(eA):.1f}% vs Forenode(B) {np.mean(eB):.1f}% · 밴드 적중 {hits}/{n}")
    print(f"  ▶ 최초협약 체제만(8개년): A {np.mean(eA_orig):.1f}% vs B {np.mean(eB_orig):.1f}%")
    print("  ※ 초기군 prior 출처에 천안논산 초기 실적 포함(순환) — '03~'05 B값은 참고 표기. "
          "LOO만 적용 시 전체 B MAE는 별도 산출:")
    eB_loo = [abs(pct_err(ACT[y], PLAN[y] * mu)) for y in sorted(PLAN)]
    print(f"    LOO 단일 prior 전 연도 적용 시 B MAE {np.mean(eB_loo):.1f}%")

    print('\n' + '=' * 96)
    print('표② 운영비 — 협약 계획 미공개(A 불가) · Forenode 통계모드(B) vs 실측')
    print('=' * 96)
    import opex_estimator
    act5 = float(np.mean([CASH_OPEX[y] for y in range(2020, 2025)]))
    # 협약수입 재구성 불가 → 통계모드 입력은 실측 매출 규모(재구조화 후 통행료+보조금 ~2,100억) 사용 ✚
    est = opex_estimator.estimate_opex_series('BTO', annual_revenue_억=2100.0, operation_years=30,
                                              terrain='평지', tunnel_ratio=0.05, bridge_ratio=0.10,
                                              growth_rate=0.01, inflation=0.0, road_length_km=LEN_KM)
    b_opex = float(np.mean(est['opex_series_억']))
    print(f"  실측 현금 OPEX('20~'24 평균): {act5:.0f}억/년 · 원단위 {act5/LEN_KM:.1f}억/km/년")
    print(f"  Forenode 통계모드: {b_opex:.0f}억/년 → 오차B {pct_err(act5, b_opex):+.1f}%")
    if est.get('warning'):
        print(f"  ⚠ L3 크로스체크: {est['warning']}")

    print('\n[관찰]')
    print('  · 재구조화(2019.12) 후에도 협약대비 실측 65% 수준 유지 — 요금 반값에도 협약 프로파일(90,036)이')
    print('    높아 갭 지속. 인천공항(63.7→99.2% 반등)과 대조적: 협약 눈높이 자체의 차이가 회복 여부를 결정')
    print('  · MRG 82%/110%·20년: 실측 47~66%로 전 기간 보장선(82%) 미달 — MRG 상시 발동 구조였음')
    print('  · 초기 3년(47.1→54.7%)을 초기군 prior(55%)가 근접 — 인천공항·광주원주에 이어 램프업 규칙성 3번째 관찰')
    print('  · 수익률 재구성 보류: FY2003~2017 수입 시계열 미확보 (DART 원문 확보 시 산출 — 경로 기록)')

if __name__ == '__main__':
    main()
