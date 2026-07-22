# -*- coding: utf-8 -*-
"""
백테스트 케이스 #21 — 안양-성남 (제이경인연결고속도로(주)) · 2군 5호

계획: **협약수익률 세후실질 5.49%(NABO 2009 본문)** · 총사업비 7,393억 = 민간 5,962 +
      보조금 1,431('09.3) · 개통 2017.9 · 21.9km(제2경인 연장) · 국토부 · 도공 10% 출자
실제: 표5-11 '22~'24: 65.8/51.2(이례 저점)/71.3% · NABO 수입: 82.4→70.1→54.9→76.3→78.6%
특이: '23 교통량 51.2%·수입 54.9% 동반 급락 후 '24 회복 — 일시 이벤트(원인 규명 과제):
      연간 변동성이 프로파일 해석을 좌우하는 사례
"""
import numpy as np
from backtest_plan_actual import loo_prior, pct_err

PLAN = {2022: 127390, 2023: 128209, 2024: 129619}
ACT = {2022: 83792, 2023: 65642, 2024: 92450}
REV = {2021: (51861, 42750), 2022: (60708, 42577), 2023: (57547, 31593),
       2024: (57966, 44247), 2025: (58386, 45917)}   # NABO (백만원)
LEN_KM = 21.9
OPEN_YEAR = 2017

def main():
    pri = loo_prior('안양-성남')
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd
    print(f"[LOO prior — 안양-성남 제외] 평균 {mu*100:.1f}% SD {sd:.4f} n={pri['loo_n']} "
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
    print('  · 23년 교통량 51.2%·수입 54.9% 동반 급락 → 24년 71.3%·76.3% 회복 — 일시 이벤트')
    print('    (공사·우회? 원인 규명 과제): 연 단위 변동성이 큰 노선은 단년 채점이 위험 — 다년')
    print('    블록 채점(R4 5년 블록)의 필요성을 교통량 축에서도 확인')
    print('  · 협약 12.7만대(대형 축) vs 실측 6.6~9.2만 — 2기인데 하위권 실현율(51~71%):')
    print('    인천김포(75%)와 함께 "2기 신규 ≠ 자동 정확"의 증거 축적')
    print('  · 수익률 5.49%(NABO) — 2기 하향 클러스터 일원')
    print('  · 보류: 23 급락 원인·실측 17~21·운영비·수익률 재구성(DART 제이경인연결)')

if __name__ == '__main__':
    main()
