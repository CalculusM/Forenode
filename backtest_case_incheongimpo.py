# -*- coding: utf-8 -*-
"""
백테스트 케이스 #20 — 인천-김포 (인천김포고속도로(주)) · 2군 4호

계획: **협약수익률 세후실질 5.07%(NABO 2009 본문 — 계획 자료 최상급)** · 총사업비 1조4,601억 =
      민간 1조498 + 보조금 4,103('09.3 기준) · 개통 2017.3 · 28.9km(수도권2순환 서측) · 국토부 ·
      MKIF 22.8%(투자 1,281억) · 2기 신규 사업(MRG 무)
실제: 표5-11 '22~'24: 75.5/75.6/76.4% · NABO 수입 '21~'25: 67.2→63.9→62.8→62.0→58.2%
특이: 협약수익률+투자비+상장 펀드 공시 3박자 — 백테스트 자료 완결형 2기 케이스
"""
import numpy as np
from backtest_plan_actual import loo_prior, pct_err

PLAN = {2022: 69366, 2023: 70304, 2024: 71515}
ACT = {2022: 52386, 2023: 53151, 2024: 54641}
REV = {2021: (85028, 57097), 2022: (88738, 56669), 2023: (91403, 57368),
       2024: (95760, 59332), 2025: (99471, 57937)}   # NABO (백만원)
LEN_KM = 28.9
OPEN_YEAR = 2017

def main():
    pri = loo_prior('인천-김포')
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd
    print(f"[LOO prior — 인천-김포 제외] 평균 {mu*100:.1f}% SD {sd:.4f} n={pri['loo_n']} "
          f"(밴드 {p10r*100:.0f}~{p90r*100:.0f}%)")

    print('\n표① 교통량 — 협약(A) vs Forenode(B: LOO P50) vs 실측')
    print(f"{'연도':>5} {'연차':>4} {'협약':>9} {'실측':>9} {'오차A%':>8} {'B':>9} {'오차B%':>8} {'밴드':>5}")
    eA, eB, hits, n = [], [], 0, 0
    for y in sorted(PLAN):
        p, a = PLAN[y], ACT[y]
        b = p * mu
        ea, eb = pct_err(a, p), pct_err(a, b)
        hit = p10r <= a / p <= p90r
        hits += hit; n += 1
        eA.append(abs(ea)); eB.append(abs(eb))
        print(f"{y:>5} {y-OPEN_YEAR+1:>4} {p:>9,} {a:>9,} {ea:>7.1f}% {b:>9,.0f} {eb:>7.1f}% {'적중' if hit else '미적중':>4}")
    print(f"  ▶ MAE ({n}개년): 협약(A) {np.mean(eA):.1f}% vs Forenode(B) {np.mean(eB):.1f}% · 밴드 {hits}/{n}")

    print('\n표② 통행료수입 — 협약 vs 징수 (NABO, 백만원)')
    for y, (pa, aa) in sorted(REV.items()):
        rr = aa / pa
        print(f"  {y}  실현율 {rr*100:>5.1f}%  오차A {(rr-1)*100:+.1f}%  수입prior B {(rr/0.6233-1)*100:+.1f}%")
    rrs = [aa / pa for pa, aa in REV.values()]
    print(f"  ▶ 수입 MAE: A {np.mean([abs((r-1)*100) for r in rrs]):.1f}% vs B "
          f"{np.mean([abs((r/0.6233-1)*100) for r in rrs]):.1f}%")

    print('\n[관찰]')
    print('  · 2기 신규 노선인데 실현율 75~76% 정체 — 광주원주(2기, 80% 근접)와 달리 하위권:')
    print('    2기라고 다 정확하지 않음. LOO P50 근접 여부·밴드로 판정')
    print('  · 수입 실현율 67.2→58.2% 하락 — 교통량(75%대 유지)과의 격차 확대: 요금 동결(2,600원')
    print('    vs 협약 2,800원) 경로. 수입 prior(62.33%)가 근사한 3번째 케이스')
    print('  · 협약수익률 5.07% 확보(NABO 계획 자료) — 2기 수익률 하향 클러스터(광주원주 4.83·')
    print('    부산울산 4.21·안양성남 5.49)의 일원: 1기(8~12%대)와 뚜렷한 세대 차')
    print('  · 보류: 실측 17~21 연도별(MKIF 분기 공시 경로)·운영비·수익률 재구성(DART)')

if __name__ == '__main__':
    main()
