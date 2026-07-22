# -*- coding: utf-8 -*-
"""
백테스트 케이스 #4 — 대구-부산 고속도로 (신대구부산고속도로(주))

계획: 최초 실시협약 2000.12.14(교차확인) · 협약수익률 세후 8.65%(RR-25-10) ·
      투자비 2조7,477억(국토부 공표 '18.12 계열 — 불변/경상 미확인✚) ·
      MRG 90%→77%('08.5 변경), 보장만기 2026.2
실제: 협약·실측 교통량 '17~'19(KOTI 이슈페이퍼)·'22~'24(표5-11)·'21(KIS ~4.7만, 협약 보간✚) ·
      감사보고서 FY2018~24 로컬 · 3차 변경협약 2020.12.22(1종 10,500→5,000, 도공 선투자,
      운영기간 30년 유지 — KIS 원문 확정)
수익률 재구성: 보류 — FY2006~2017 수입 시계열 미확보 (DART 원문·KIS 후속 리포트 경로 기록)
"""
import numpy as np
from backtest_plan_actual import loo_prior, pct_err

PLAN = {2017: 84393, 2018: 86505, 2019: 88700,
        2021: 93400,                       # ✚보간 ('19 88,700→'22 95,831 CAGR 2.6%)
        2022: 95831, 2023: 95831, 2024: 95831}
ACT = {2017: 49374, 2018: 45582, 2019: 44397,
       2021: 47000,                        # KIS '약 4.7만대'
       2022: 49089, 2023: 51440, 2024: 52210}
RESTRUCT = 2021  # 2020.12.24 요금 반값 시행 → 2021~ 변경체제
CASH_OPEX = {2018: 284.2, 2019: 292.2, 2020: 374.9, 2021: 391.9,
             2022: 394.4, 2023: 440.9, 2024: 602.7}
LEN_KM = 82.1

def main():
    pri = loo_prior('대구-부산')
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd
    print(f"[LOO prior — 대구-부산 제외] 평균 {mu*100:.1f}% SD {sd:.4f} n={pri['loo_n']} "
          f"(밴드 {p10r*100:.0f}~{p90r*100:.0f}%)")

    print('\n' + '=' * 92)
    print('표① 교통량 — 협약(A) vs Forenode LOO P50(B) vs 실측')
    print('=' * 92)
    print(f"{'연도':>5} {'체제':>4} {'협약':>8} {'실측':>8} {'오차A%':>8} {'B:P50':>8} {'오차B%':>8} {'밴드':>5}")
    eA, eB, hits, n = [], [], 0, 0
    for y in sorted(PLAN):
        p, a = PLAN[y], ACT[y]
        regime = '변경' if y >= RESTRUCT else '최초'
        b = p * mu
        ea, eb = pct_err(a, p), pct_err(a, b)
        hit = p10r <= a / p <= p90r
        hits += hit; n += 1
        eA.append(abs(ea)); eB.append(abs(eb))
        mark = '✚' if y == 2021 else ''
        print(f"{y:>5} {regime:>4} {p:>8,}{mark} {a:>8,} {ea:>7.1f}% {b:>8,.0f} {eb:>7.1f}% {'적중' if hit else '미적중':>4}")
    print(f"\n  ▶ MAE (7개년): 협약(A) {np.mean(eA):.1f}% vs Forenode(B) {np.mean(eB):.1f}% · 밴드 적중 {hits}/{n}")
    print("  ※ 참고 관찰: 2012년 통행'수입' 협약대비 48.0%(도로업무편람 2012) — 교통량 아님, 시계열 미편입")

    print('\n' + '=' * 92)
    print('표② 운영비 — 협약 계획 미공개(A 불가) · Forenode 통계모드(B) vs 실측')
    print('=' * 92)
    import opex_estimator
    act5 = float(np.mean([CASH_OPEX[y] for y in range(2020, 2025)]))
    est = opex_estimator.estimate_opex_series('BTO', annual_revenue_억=3400.0, operation_years=30,
                                              terrain='산지', tunnel_ratio=0.20, bridge_ratio=0.15,
                                              growth_rate=0.01, inflation=0.0, road_length_km=LEN_KM)
    b_opex = float(np.mean(est['opex_series_억']))
    print(f"  실측 현금 OPEX('20~'24 평균): {act5:.0f}억/년 · 원단위 {act5/LEN_KM:.1f}억/km/년 "
          f"('24 수선비 이벤트 67→203억 포함)")
    print(f"  Forenode 통계모드: {b_opex:.0f}억/년 → 오차B {pct_err(act5, b_opex):+.1f}%")
    if est.get('warning'):
        print(f"  ⚠ L3 크로스체크: {est['warning']}")

    print('\n[관찰]')
    print('  · 실현율 50~58%로 22개 노선 중 최하위권 — LOO P50(82.7%)조차 크게 낙관: 밴드 적중률로 정직 기록')
    print('  · MRG 77% 보장 vs 실측 50~58% → 상시 발동, 누적 1조333억(08~20) + 재구조화 후 보전 체제')
    print('  · 요금 반값(20.12) 후에도 실현율 51→54.5%로 미미한 회복 — 천안논산과 동일 패턴(협약 눈높이 문제)')
    print('  · 보조금이 매출의 69%(24년) — 준재정 사업화. MRG 종료(26.2) 후 첫 실적(KIS 26.6 리포트)이 관전점')
    print('  · 수익률 재구성 보류: FY2006~2017 미확보 (경로: DART 원문 + KIS rs20260617-20.pdf)')

if __name__ == '__main__':
    main()
