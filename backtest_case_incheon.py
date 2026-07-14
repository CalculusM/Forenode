# -*- coding: utf-8 -*-
"""
백테스트 케이스 #1 — 인천국제공항고속도로 (신공항하이웨이(주))

A = 최초 실시협약(1995.10.27) 추정 vs 실제 실적 오차 (R1·R3)
B = Forenode 재추정(as-of, LOO prior) vs 같은 실적 오차 (R2)

데이터 출처(수집 워크플로 2026-07-13):
  계획: NABO 예산현안분석 22호(협약 교통량 2001~2030 원표)·KOTI MP-24-11 표2-16
        (총사업비 13,727억·운영비 9,064억, 2000.1.1 불변가)·법인세 판례(수익률 9.7%→9.36%)
  실제: DART 감사보고서 FY2016~25 원문 파싱(매출·매출원가·무형상각·판관비 역산)·
        NABO(실측교통량 01~07·MRG 01~07)·KOTI RR-25-10 표5-11(실측 22~24)·
        CEPHIS API(실측 20~21)·국감/언론(MRG 잔여연도·수입 누계 앵커)
"""
import numpy as np
from backtest_plan_actual import (loo_prior, load_engine, pct_err, block5,
                                  reconstructed_irr, register_loo_prior, TABLE_5_11)

억 = 1.0  # 단위: 억원

# ── 물가 지수 (통계청 소비자물가지수, 2020=100 — 근사치; R5 불변가 통일용) ──
# 협약 운임조정 자체가 CPI 연동(표2-16)이므로 GDP디플레이터 대신 CPI 채택(계약 정합).
CPI = {1995: 52.1, 1996: 54.6, 1997: 57.0, 1998: 61.3, 1999: 61.8, 2000: 63.2,
       2001: 65.7, 2002: 67.5, 2003: 69.9, 2004: 72.4, 2005: 74.4, 2006: 76.1,
       2007: 78.0, 2008: 81.7, 2009: 83.9, 2010: 86.4, 2011: 89.9, 2012: 91.8,
       2013: 93.0, 2014: 94.2, 2015: 94.9, 2016: 95.8, 2017: 97.6, 2018: 99.1,
       2019: 99.5, 2020: 100.0, 2021: 102.5, 2022: 107.7, 2023: 111.6,
       2024: 114.2, 2025: 116.4, 2026: 118.7, 2027: 121.1, 2028: 123.5,
       2029: 126.0, 2030: 128.5}

# ── 계획 (최초 실시협약, R1) ──
PLAN_TRAFFIC = {2001: 110622, 2002: 121496, 2003: 133438, 2004: 146554,
                2005: 119026, 2006: 125322, 2007: 131965, 2008: 138930,
                2009: 146282, 2010: 93094, 2011: 95920, 2012: 98936,
                2013: 102056, 2014: 105282, 2015: 108620, 2016: 112074,
                2017: 115635, 2018: 119340, 2019: 123168, 2020: 127136}
for _y in range(2021, 2031):
    PLAN_TRAFFIC[_y] = 127136

PLAN_CAPEX_TOTAL_불변00 = 13727.0     # 총사업비 (2000.1.1 불변, KOTI 표2-16)
PLAN_SUBSIDY_RATIO = 0.078            # 건설보조금 비율 (RR-25-10 표2-3)
PLAN_CAPEX_PRIVATE_경상 = 14766.0     # 통행료 산정 기초 총민간투자비 (개통보도, 경상)
PLAN_OPEX_30Y_불변00 = 9064.0         # 운영비+유지비 30년 총액 (2000.1.1 불변)
PLAN_OPEX_YR_불변00 = PLAN_OPEX_30Y_불변00 / 30.0   # 연 302.1억 (균등 가정 — 협약 연도별 프로파일 미공개)
PLAN_RETURN = 9.7                     # 최초 협약 사업수익률 % (판례: 2015 재조달로 9.36%로 인하)
PLAN_RETURN_2015 = 9.36
MRG_RATE_1ST = 0.90                   # 1차 변경협약(2000.12.27) 보장 90% → 2004.4.21 80%
MRG_RATE_2ND = 0.80

# ── 실제 (R6 회계 추출 적용) ──
ACT_TRAFFIC = {2001: 51939, 2002: 54244, 2003: 55323, 2004: 59780,
               2005: 62831, 2006: 65571, 2007: 68711,
               # 2008~2019 일평균 실측 공백 (KOTI·CEPHIS 미공표 구간) — 2016 61.4% 보도는 참고
               2020: 68272, 2021: 67439, 2022: 80996, 2023: 106510, 2024: 126089}

ACT_INVEST_경상 = {1995: 121, 1996: 600, 1997: 2141, 1998: 4091, 1999: 4259,
                   2000: 2855, 2001: 527, 2002: 7, 2003: 1}   # 합계 14,602 (NABO 부표5)

TOLL_REV = {2001: 1062.0, 2015: 1430.6, 2016: 1526.7, 2017: 1602.1, 2018: 1708.7,
            2019: 1795.9, 2020: 1248.8, 2021: 1251.1, 2022: 1477.4, 2023: 1701.2,
            2024: 1227.9, 2025: 1262.8}   # 통행료수익 (DART·언론, 경상)
CUM_TOLL_01_19 = 24160.0                  # 누적 통행료수입 앵커 (사이다뉴스)

SUBSIDY = {2001: 591, 2002: 683, 2003: 953, 2004: 1009, 2005: 660, 2006: 710,
           2007: 763,
           # 2008~2014 개별 미공개 — 구간합계 6,453억(누계 차감 도출) 균등 배분
           2015: 1031.9, 2016: 881.2, 2017: 815.0, 2018: 794.5, 2019: 818.5,
           2020: 800.3, 2021: 1485.2,  # 2021은 2020 운영분 정산의 교부시점 인식(주석)
           2022: 140.6, 2023: 193.4, 2024: 1068.7, 2025: 1858.8}
for _y in range(2008, 2015):
    SUBSIDY[_y] = 6453.0 / 7.0

# DART 원문 (FY2015~25): 매출 / 매출원가 / 영업이익 / 무형자산상각(CF)
DART = {  # 연도: (매출, 매출원가, 영업이익, 무형상각CF)
    2015: (2465.1, 750.3, 1652.1, 486.1), 2016: (2410.2, 749.9, 1611.6, 486.8),
    2017: (2418.8, 788.0, 1580.3, 520.2), 2018: (2505.1, 846.2, 1599.2, 508.6),
    2019: (2616.6, 879.0, 1676.8, 508.1), 2020: (2050.6, 845.0, 1146.4, 499.9),
    2021: (2737.5, 846.5, 1833.5, 511.7), 2022: (1619.0, 817.8, 740.2, 514.1),
    2023: (1896.4, 850.6, 975.0, 515.8), 2024: (2298.6, 861.0, 1374.2, 518.2),
    2025: (3125.7, 906.2, 2155.6, 528.7),
}
AMORT_CONCESSION = 475.3  # 관리운영권 정액상각 (경상 고정, FY2016 주석)
TAX_EFF = 0.242           # 법인세+지방소득세 실효 근사

# R6: 현금 운영비 = 매출원가 + 판관비(역산: 매출-매출원가-영업이익) - 무형상각(CF)
ACT_CASH_OPEX = {}
for y, (rev, cogs, opin, amort) in DART.items():
    sga = rev - cogs - opin
    ACT_CASH_OPEX[y] = cogs + sga - amort

# 수입 앵커 (KOTI RR-22-18·서울도시연구): 협약 대비 실제 통행료수입 비율
REV_RATIO_ANCHORS = {"2001~2014 평균": 44.7, "2020": 34.2}


def fill_actual_revenue():
    """2002~2014 통행료수입 재구성: 누계 앵커(01~19 = 2조4,160억)에서 15~19 실측·01 실측을
    차감한 잔여 15,034억을 교통량×요금지수 비례 배분 (가정 명시: 08~14 교통량 68,700 flat)."""
    known_15_19 = sum(TOLL_REV[y] for y in range(2015, 2020))
    residual = CUM_TOLL_01_19 - known_15_19 - TOLL_REV[2001]
    toll_idx = {2002: 6100, 2003: 6400, 2004: 6400, 2005: 6700, 2006: 6700,
                2007: 6700, 2008: 7100, 2009: 7300, 2010: 7500, 2011: 7500,
                2012: 7500, 2013: 7600, 2014: 7600}
    tr = dict(ACT_TRAFFIC)
    for y in range(2008, 2015):
        tr[y] = 68700.0  # 2007 실측(68,711)·2016 역산(≈68.8천) 사이 평탄 가정
    w = {y: tr[y] * toll_idx[y] for y in range(2002, 2015)}
    s = sum(w.values())
    return {y: residual * w[y] / s for y in range(2002, 2015)}


def plan_revenue_series():
    """협약 통행료수입 재구성 (경상): 협약교통량 × 협약 평균단가.
    단가는 2020 수입비율 앵커(34.2%)로 캘리브레이션: 협약수입2020경상 = 실제2020/0.342."""
    plan_rev_2020 = TOLL_REV[2020] / 0.342
    unit_불변00 = plan_rev_2020 * (CPI[2000] / CPI[2020]) / (PLAN_TRAFFIC[2020] * 365) * 1e8  # 원/대
    out = {}
    for y, t in PLAN_TRAFFIC.items():
        out[y] = t * 365 * unit_불변00 / 1e8 * (CPI[y] / CPI[2000])  # 경상 억원
    return out, unit_불변00


def act_opex_series_full():
    """2001~2014 현금 운영비: 2015 실측(326.9억)을 CPI로 역스케일 (가정 명시)."""
    base15 = ACT_CASH_OPEX[2015]
    out = dict(ACT_CASH_OPEX)
    for y in range(2001, 2015):
        out[y] = base15 * CPI[y] / CPI[2015]
    return out


def realized_project_irr(act_rev_full, act_opex_full, verbose=False):
    """R7: 실제 현금흐름 재구성 세후 프로젝트 IRR (1995 기점, 실질).
    2026~2030 잔여기간 = 현행 유지(2024~25 평균 수입·2025 운영비)."""
    fcf = {}
    for y, inv in ACT_INVEST_경상.items():
        fcf[y] = fcf.get(y, 0.0) - inv
    tail_rev = np.mean([TOLL_REV[2024] + SUBSIDY[2024], TOLL_REV[2025] + SUBSIDY[2025]])
    for y in range(2001, 2031):
        if y <= 2025:
            rev = act_rev_full[y] + SUBSIDY[y]
            opex = act_opex_full[y]
        else:
            rev, opex = tail_rev, ACT_CASH_OPEX[2025]
        tax = TAX_EFF * max(0.0, rev - opex - AMORT_CONCESSION)
        fcf[y] = fcf.get(y, 0.0) + rev - opex - tax
    # 실질화: 각 연도 FCF를 1995 불변가로 디플레이트 후 IRR → 실질 IRR
    fcf_real = {y: v * CPI[1995] / CPI[y] for y, v in fcf.items()}
    irr_real = reconstructed_irr(fcf_real, base_year=1995)
    irr_nom = reconstructed_irr(fcf, base_year=1995)
    if verbose:
        print(f"    (재구성 명목 IRR {irr_nom*100:.2f}% / 실질 IRR {irr_real*100:.2f}%)")
    return irr_real, irr_nom


def main():
    pri = loo_prior("인천국제공항")
    mu, sd = pri["loo_mean"], pri["loo_sd"]
    z90 = 1.2816
    p10r, p90r = mu - z90 * sd, mu + z90 * sd

    plan_rev, unit = plan_revenue_series()
    act_rev_fill = fill_actual_revenue()
    act_rev_full = dict(TOLL_REV); act_rev_full.update(act_rev_fill)
    act_opex_full = act_opex_series_full()

    # 캘리브레이션 정합 점검: 01~14 수입비율이 앵커 44.7%와 맞는가
    pr_s = sum(plan_rev[y] for y in range(2001, 2015))
    ar_s = sum(act_rev_full[y] for y in range(2001, 2015))
    print(f"[캘리브레이션] 협약 평균단가(2000불변) {unit:,.0f}원/대 · "
          f"01~14 수입비율 재현 {ar_s/pr_s*100:.1f}% (앵커 44.7%)")

    # ══ 표 ① — 연도별 실시협약 vs 실제 오차 (교통량) ══
    print("\n" + "=" * 100)
    print("표 ① 연도별 오차 — 교통량 (대/일) · 오차 = (실제-협약)/협약")
    print("=" * 100)
    print(f"{'연도':>5} {'협약':>9} {'실측':>9} {'오차A%':>8}   {'B:P50':>9} {'오차B%':>8} {'밴드(P10~P90)적중':>14}")
    errA_list, errB_list = [], []
    for y in sorted(PLAN_TRAFFIC):
        if y > 2024:
            continue
        p = PLAN_TRAFFIC[y]
        a = ACT_TRAFFIC.get(y)
        b50 = p * mu
        if a is None:
            print(f"{y:>5} {p:>9,} {'—':>9} {'—':>8}   {b50:>9,.0f} {'—':>8} {'—':>14}")
            continue
        eA = pct_err(a, p); eB = pct_err(a, b50)
        hit = "적중" if (p10r <= a / p <= p90r) else "미적중"
        errA_list.append(abs(eA)); errB_list.append(abs(eB))
        print(f"{y:>5} {p:>9,} {a:>9,} {eA:>7.1f}%   {b50:>9,.0f} {eB:>7.1f}% {hit:>12}")
    print(f"\n  ▶ 평균절대오차(MAE): 협약(A) {np.mean(errA_list):.1f}% vs Forenode P50(B) {np.mean(errB_list):.1f}% "
          f"(관측 {len(errA_list)}개년)")
    cover = sum(1 for y in ACT_TRAFFIC if p10r <= ACT_TRAFFIC[y]/PLAN_TRAFFIC[y] <= p90r)
    print(f"  ▶ Forenode P10~P90 밴드 적중: {cover}/{len(ACT_TRAFFIC)}개년 "
          f"(밴드 = 협약의 {p10r*100:.0f}%~{p90r*100:.0f}%)")

    # ══ 표 ① 계속 — 수입·운영비·투자비 ══
    print("\n" + "=" * 100)
    print("표 ① 계속 — 통행료수입 (경상 억원, 02~14 실적은 누계앵커 재구성)")
    print("=" * 100)
    print(f"{'구간':>12} {'협약수입':>10} {'실제수입':>10} {'오차A%':>8}   {'B:P50':>10} {'오차B%':>8}")
    for blk in [(2001, 2005), (2006, 2010), (2011, 2015), (2016, 2020), (2021, 2025)]:
        ps = sum(plan_rev[y] for y in range(blk[0], blk[1] + 1))
        as_ = sum(act_rev_full[y] for y in range(blk[0], blk[1] + 1))
        b = ps * mu
        print(f"{f'{blk[0]}~{blk[1]}':>12} {ps:>10,.0f} {as_:>10,.0f} {pct_err(as_, ps):>7.1f}%   "
              f"{b:>10,.0f} {pct_err(as_, b):>7.1f}%")

    print("\n" + "=" * 100)
    print("표 ① 계속 — 운영비용 5년 블록 (R4·R6, 2000.1.1 불변가 억원) · 협약 = 연 302.1억 균등 가정")
    print("=" * 100)
    print(f"{'운영연차':>10} {'협약(불변)':>10} {'실제(불변)':>10} {'오차A%':>8}")
    opex_real = {y: ACT_CASH_OPEX[y] * CPI[2000] / CPI[y] for y in ACT_CASH_OPEX}
    blocks_act = block5(opex_real, start_year=2001)
    for key, val in blocks_act.items():
        n_years = min(5, len([1 for y in opex_real if f"{((y-2001)//5)*5+1}~{((y-2001)//5)*5+5}년차" == key]))
        plan_b = PLAN_OPEX_YR_불변00 * n_years
        print(f"{key:>10} {plan_b:>10,.0f} {val:>10,.0f} {pct_err(val, plan_b):>7.1f}%")

    print("\n투자비: 협약 민간투자비 14,766억(경상 기준, 통행료 산정 기초) vs 실집행 14,602억(NABO 연도별 합계)"
          f" → 오차 {pct_err(14602, 14766):+.1f}% (기준 병존: 협약 총사업비 13,727억은 2000.1.1 불변가로 직접 비교 불가)")

    # ══ 수익률 (R7) ══
    irr_real, irr_nom = realized_project_irr(act_rev_full, act_opex_full, verbose=False)
    print("\n" + "=" * 100)
    print("표 ① 계속 — 수익률 (세후 기준)")
    print("=" * 100)
    print(f"  협약(A 계획): 최초 9.7% (2015 재조달 후 9.36%) | 실제 재구성: 실질 {irr_real*100:.2f}% · 명목 {irr_nom*100:.2f}%")
    print(f"  오차A(실질, vs 9.7%): {pct_err(irr_real*100, PLAN_RETURN):+.1f}%  ※MRG 수령 포함 실현치")

    # ══ B — Forenode 엔진 재추정 (as-of) ══
    print("\n" + "=" * 100)
    print("표 ② A vs B — Forenode 엔진 수익률 재추정 (불변가 모델, inflation=0)")
    print("=" * 100)
    build_cashflow = load_engine()
    capex_priv_불변 = PLAN_CAPEX_TOTAL_불변00 * (1 - PLAN_SUBSIDY_RATIO)
    rev1_불변 = plan_rev[2001] * CPI[2000] / CPI[2001]  # 첫해 협약수입 (불변)
    g = (PLAN_TRAFFIC[2020] / PLAN_TRAFFIC[2001]) ** (1 / 19) - 1
    rows = []
    for tag, ratio in [("P10", p10r), ("P50", mu), ("P90", p90r)]:
        # v3 정식 API (L1·L4 수정 후): 협약수입(forecast)과 실현수입(annual_revenue)을
        # 분리 입력, MRG 보장기간 20년 명시 — 재스케일 우회 불필요.
        cf, m = build_cashflow(
            capex_억=capex_priv_불변, annual_revenue_억=rev1_불변 * ratio,
            forecast_revenue_억=rev1_불변, mrg_ratio=MRG_RATE_2ND, mrg_years=20,
            construction_years=5, operation_years=30,
            opex_series_억=np.full(30, PLAN_OPEX_YR_불변00),
            discount_rate=0.0562, inflation=0.0, growth_rate=g,
            equity_ratio=0.30, debt_rate=0.09, business_type="BTO",
        )
        rows.append((tag, ratio, m))
        print(f"  B-{tag} (실현율 {ratio*100:.0f}%): 세후실질 IRR {m['real_irr']*100:.2f}% · "
              f"MRG보전 30년 {m['total_mrg_subsidy']:,.0f}억 · DSCR평균 {m['dscr_avg']:.2f}")
    b50_irr = rows[1][2]['real_irr'] * 100
    print(f"\n  ▶ 수익률 오차: A(협약 9.7% 약속) vs 실제 {irr_real*100:.2f}% → 오차A {pct_err(irr_real*100, 9.7):+.1f}%")
    print(f"                B(Forenode P50 {b50_irr:.2f}%) vs 실제 {irr_real*100:.2f}% → 오차B {pct_err(irr_real*100, b50_irr):+.1f}%")
    print(f"  ▶ MRG 재정소요 사전경고: B-P10~P50 보전금 {rows[0][2]['total_mrg_subsidy']:,.0f}~{rows[1][2]['total_mrg_subsidy']:,.0f}억 "
          f"(실제 20년 지급 1조6,667억 경상 ≈ 불변 1.2조 내외)")

    # ══ B — Forenode OPEX 통계모드 검증 ══
    print("\n" + "=" * 100)
    print("표 ② 계속 — 운영비: 협약(A) vs Forenode 통계모드(B) vs 실제 (불변 억원/년)")
    print("=" * 100)
    import opex_estimator
    est = opex_estimator.estimate_opex_series("BTO", annual_revenue_억=rev1_불변,
                                              operation_years=30, terrain="평지",
                                              tunnel_ratio=0.0, bridge_ratio=0.15,
                                              growth_rate=g, inflation=0.0,
                                              road_length_km=40.2)
    b_opex_yr = float(np.mean(est["opex_series_억"]))
    if est.get("warning"):
        print(f"  ⚠ L3 크로스체크 경고 발동: {est['warning']}")
    act_yr_불변 = float(np.mean([opex_real[y] for y in range(2015, 2025)]))
    print(f"  협약 계획: {PLAN_OPEX_YR_불변00:,.0f}억/년 | Forenode 통계모드: {b_opex_yr:,.0f}억/년 "
          f"({est['explanation']})")
    print(f"  실제(15~24 평균, 불변): {act_yr_불변:,.0f}억/년")
    print(f"  → 오차A {pct_err(act_yr_불변, PLAN_OPEX_YR_불변00):+.1f}% vs 오차B {pct_err(act_yr_불변, b_opex_yr):+.1f}%")


if __name__ == "__main__":
    main()
