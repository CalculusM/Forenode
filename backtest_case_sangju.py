# -*- coding: utf-8 -*-
"""
백테스트 케이스 #22 — 상주-영천 고속도로 (상주영천고속도로(주))

★ 홀드아웃 1호 — 사전 등록본: Forenode_wiki/03-Projects/forenode/prereg-v022-sangju-yeongcheon-2026.md
  (채점 결과 산출 전 커밋 완료 — 가드레일 6)

계획: 최초 실시협약 · 개통 2017.6.27(CEPHIS 기본정보) · 연장 93.9~94km ·
      총사업비 1조3,986억 = 민간 1조1,325억(검색 확인, ✚기준 미상) · 운영 30년
실제: 협약·실측 교통량 '22~'24 (KOTI RR-25-10 표5-11 원표 = TABLE_5_11)
특이: 표5-11 표본 내 → LOO prior(n=59) 필수 · 원장 최초의 '사전 등록 후 채점' 케이스
      ⚠️ 국토부 「민자고속도로 통행료 관리 로드맵」('18.8) 2단계 자금재조달 대상
         (1.31배→1.1배 순차 인하 계획) — 실제 시행 시점·인하율 미확보(✚).
         '22~'24 창에 걸쳤다면 교통량 상향 편향 → 가드레일 4 재채점 대상.
재무축: 감사보고서 로컬 미확보 → 표②~⑤ 산출하지 않음(교통량 단일 축).
"""
import numpy as np
from backtest_plan_actual import TABLE_5_11, loo_prior, pct_err

ROUTE = '상주-영천'
LEN_KM = 93.9
OPEN_DATE = '2017-06-27'


def main():
    rows = TABLE_5_11[ROUTE]
    pri = loo_prior(ROUTE)
    mu, sd = pri['loo_mean'], pri['loo_sd']
    z = 1.2816
    p10r, p90r = mu - z * sd, mu + z * sd

    print('=' * 90)
    print(f'백테스트 V-022 — {ROUTE} (홀드아웃 1호 · 사전 등록 후 채점)')
    print('=' * 90)
    print(f"[LOO prior — {ROUTE} 제외] 평균 {mu*100:.1f}% · SD {sd:.4f} · n={pri['loo_n']} "
          f"(밴드 {p10r*100:.1f}~{p90r*100:.1f}%)")
    print(f"[전체 prior 대조] 평균 {pri['all_mean']*100:.1f}% · SD {pri['all_sd']:.4f} · "
          f"n={pri['all_n']} — LOO로 {(mu-pri['all_mean'])*100:+.2f}%p 이동")

    print('\n' + '=' * 90)
    print('표① 교통량 — 협약(A) vs Forenode LOO P50(B) vs 실측 · 오차 = (실측-추정)/추정')
    print('=' * 90)
    print(f"{'연도':>5} {'협약':>9} {'실측':>9} {'실현율':>8} {'오차A%':>9} "
          f"{'B:P50':>9} {'오차B%':>9} {'밴드':>7}")
    eA, eB, hits = [], [], 0
    for (y, plan, act) in rows:
        b = plan * mu
        ea, eb = pct_err(act, plan), pct_err(act, b)
        ratio = act / plan
        hit = p10r <= ratio <= p90r
        hits += hit
        eA.append(abs(ea))
        eB.append(abs(eb))
        print(f"{y:>5} {plan:>9,} {act:>9,} {ratio*100:>7.1f}% {ea:>8.1f}% "
              f"{b:>9,.0f} {eb:>8.1f}% {'적중' if hit else '미적중':>6}")

    maeA, maeB = float(np.mean(eA)), float(np.mean(eB))
    win = 'B' if maeB < maeA else 'A'
    print(f"\n  ▶ MAE: 협약(A) {maeA:.1f}%  vs  Forenode LOO P50(B) {maeB:.1f}%"
          f"  →  우위 = {win}")
    print(f"  ▶ 밴드 적중: {hits}/{len(rows)}")

    print('\n' + '-' * 90)
    print('사전 등록 기준 대조 (prereg-v022 §3)')
    print('-' * 90)
    print(f"  1차 MAE — 기준 'B MAE < A MAE' → {'충족' if maeB < maeA else '미충족'} "
          f"(B {maeB:.1f}% {'<' if maeB < maeA else '>='} A {maeA:.1f}%)")
    print(f"  2차 밴드 적중 — {hits}/{len(rows)} (기준 없음, 그대로 기록)")
    print(f"  3차 우위 — {win}")

    print('\n' + '-' * 90)
    print('한계 (사전 등록 §4 — 결과와 무관하게 유효)')
    print('-' * 90)
    print("  ① 순수 ex-ante 아님 — LOO는 횡단면 오염만 제거. prior 표본이 '22~'24 동시대라")
    print("     '예측 시점 정보만으로 더 낫다'는 주장 불가(가드레일 5 첫 조건 미충족)")
    print("  ② 3개년·단일 노선 — 단일 증거 이상으로 쓰지 않음")
    print("  ③ 요금 인하 이벤트 ✚ — 로드맵 2단계 자금재조달 대상. 시행 시점 확정 시 재채점")
    print("  ④ 재무축 없음 — 감사보고서 미확보로 교통량 단일 축")

    # 원장 등재용 한 줄
    print('\n[원장 등재용] V-022,상주-영천,2군(홀드아웃·사전등록),%d,%.1f,%.1f,%s,%d,%d'
          % (len(rows), maeA, maeB, win, hits, len(rows)))


if __name__ == '__main__':
    main()
