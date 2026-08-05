# -*- coding: utf-8 -*-
"""
검증 오버레이 (verification_overlays.py) — Forenode

기존 산출(DSCR·NPV·MC 분포)에 얹는 '검증 도구' 지표:
  1) implied_rating  : 최소DSCR → 예비 신용등급 밴드 근사 (금융주관사·재무투자자 설득력)
  2) downside_metrics: MC 분포에서 하방확률·VaR (단정 아닌 확률로 제시)

※ 신규 핵심 계산을 바꾸지 않는 '얹는' 오버레이 — build_cashflow 등 코어 불변.
"""
import numpy as np


# ── 1) 예비 신용등급 매핑 (NICE 유료도로 평가방법론 근사 + 시장 벤치마크) ──
# 한국 회사채 등급: BBB- 이상 투자등급 / BB+ 이하 투기등급(투자부적격).
# 시장 벤치마크(앱 내장 감사보고서 실데이터): 천안논산 DSCR 1.29(정상권)·제이영동 0.31(부실).
# 정상 민자도로 base-case 커버넌트 ≈ 1.2~1.3.
# ⚠️ 정식 등급 아님 — 정식 PF 등급은 사업위험(OPBA)+DSCR+자본구조+재정지원 결합. DSCR 단독 근사.
MARKET_DSCR = {"정상권_천안논산": 1.29, "부실_제이영동": 0.31, "base_covenant": (1.2, 1.3)}


def implied_rating(dscr_min, opba="중(3~5)"):
    """최소 DSCR → 예비 신용프로파일 밴드(근사) + 민자도로 시장 대비 위치."""
    if dscr_min is None or dscr_min != dscr_min:  # NaN guard
        return {"dscr_min": None, "implied_band": "—", "level": "na",
                "investment_grade": None, "market_position": "—",
                "note": "DSCR 산출 불가"}
    d = float(dscr_min)
    # 투자등급(BBB- 이상)/투기등급(BB+ 이하) '영역' 근사
    if d >= 1.30:
        band, level, ig = "투자등급 영역 (≈BBB대)", "ig", True
    elif d >= 1.15:
        band, level, ig = "투자등급 경계 (≈BBB-/BB+)", "edge", True
    elif d >= 1.00:
        band, level, ig = "투기등급 영역 (≈BB/B)", "spec", False
    else:
        band, level, ig = "디폴트 위험 (≈CCC 이하)", "default", False
    # 시장 벤치마크 대비 위치
    if d >= MARKET_DSCR["정상권_천안논산"]:
        pos = "시장 정상권(천안논산 1.29) 이상"
    elif d >= MARKET_DSCR["base_covenant"][0]:
        pos = "시장 base-case 커버넌트(1.2~1.3) 권역"
    elif d >= MARKET_DSCR["부실_제이영동"]:
        pos = "정상권 미달, 부실(제이영동 0.31)과 정상 사이"
    else:
        pos = "부실(제이영동 0.31) 이하"
    return {
        "dscr_min": d, "opba_assumed": opba,
        "implied_band": band, "level": level, "investment_grade": ig,
        "market_position": pos,
        "note": "NICE 유료도로 평가방법론 근사 · 시장 벤치마크(천안논산 1.29·제이영동 0.31) 참조 · "
                "정식 등급 아님(사업위험·자본구조·재정지원 가산 별도)",
    }


# ── 2) 재협상·적격성 재검증 트리거 (법정 임계값) ──
# 근거: 유료도로법 §23의5 — 3년 연속 실측 교통량/통행료수입이 실시협약 대비 70% 미달
#   등의 사유 발생 시 주무관청이 실시협약 변경을 요구할 수 있음(불응 시 재정지원금
#   미지급 가능). 민간투자사업기본계획 — 추정 수요 30% 이상 감소 또는 총사업비 20%
#   이상 증가 시 민자적격성 재검증 의뢰. (KOTI RR-23-19, 2023, pp.151-152·185·187)
TRIGGER_RULES = {
    "ratio_threshold": 0.70,      # 실측/협약 임계
    "consecutive_years": 3,       # 연속 미달 연수
    "demand_revision_cut": 0.30,  # 수요 재추정 감소율 임계
    "capex_overrun": 0.20,        # 총사업비 증가율 임계
    "source": "유료도로법 §23의5 · 민간투자사업기본계획 (KOTI RR-23-19 pp.151-152·185·187)",
}


def renegotiation_triggers(actual_ratios=None, demand_revision_cut=None,
                           capex_overrun=None):
    """운영 중 사업의 법정 재협상·재검증 트리거 사후(ex-post) 점검.

    actual_ratios : 연도별 (실측/협약) 비율 리스트(최신이 마지막). 예: [0.66, 0.68, 0.65]
    demand_revision_cut : 수요 재추정 감소율(소수, 0.30=30% 감소)
    capex_overrun : 총사업비 증가율(소수, 0.20=20% 증가)
    반환: {"checks": [{"name","status(ok/watch/trigger)","detail"}...], "worst": ...}
    """
    checks = []
    if actual_ratios:
        r = [float(x) for x in actual_ratios if x == x]
        thr, n_need = TRIGGER_RULES["ratio_threshold"], TRIGGER_RULES["consecutive_years"]
        below = [x < thr for x in r]
        hit = len(below) >= n_need and all(below[-n_need:])
        status = "trigger" if hit else ("watch" if any(below) else "ok")
        checks.append({
            "name": f"실시협약 변경 요구 (교통량·수입 {thr*100:.0f}% / {n_need}년 연속)",
            "status": status,
            "detail": "최근 실측/협약 = " + " → ".join(f"{x*100:.0f}%" for x in r),
        })
    if demand_revision_cut is not None and demand_revision_cut == demand_revision_cut:
        d = float(demand_revision_cut)
        status = "trigger" if d >= TRIGGER_RULES["demand_revision_cut"] else (
            "watch" if d >= TRIGGER_RULES["demand_revision_cut"] * 0.67 else "ok")
        checks.append({
            "name": "민자적격성 재검증 (수요 30%↑ 감소)",
            "status": status, "detail": f"수요 재추정 감소율 {d*100:.0f}%",
        })
    if capex_overrun is not None and capex_overrun == capex_overrun:
        c = float(capex_overrun)
        status = "trigger" if c >= TRIGGER_RULES["capex_overrun"] else (
            "watch" if c >= TRIGGER_RULES["capex_overrun"] * 0.67 else "ok")
        checks.append({
            "name": "민자적격성 재검증 (총사업비 20%↑ 증가)",
            "status": status, "detail": f"총사업비 증가율 {c*100:.0f}%",
        })
    order = {"trigger": 2, "watch": 1, "ok": 0}
    worst = max((c["status"] for c in checks), key=lambda s: order[s]) if checks else "na"
    return {"rules": TRIGGER_RULES, "checks": checks, "worst": worst}


# ── 3) 협약수익률(약정 사업수익률) 시장 벤치마크 ──
# 근거: KOTI RR-24-12(2024) pp.52-53 — 국내 도로 실시협약 54건 약정 사업수익률(세후):
#   최소 3.70% · 평균 6.41% · 최대 12.0%, 초기(MRG 시대) 9~12% → 이후 체결분 4~6%대.
#   KOTI RR-25-10(2025) pp.42-44 — 최신 3시대 분포(불변 세후): 운영 23개 평균 5.60% /
#   협상 중 BTO-a 4개 평균 3.23% / 기획 단계 13개 평균 2.85%.
#   RR-24-12는 수익률 '과소평가'(2000년 이후 10년 국고채 미만)도 투자 위축 요인으로
#   지적(p.66) → 적정성 검증은 과대·과소 양방향.
MARKET_AGREED_RETURNS = {
    "n": 54, "min": 3.70, "avg": 6.41, "max": 12.0,
    "recent_low": 4.0, "recent_high": 6.0,
    "btoa_pipeline": 2.85, "btoa_nego": 3.23, "operating_avg": 5.60,
    "source": "KOTI RR-24-12 pp.52-53 (도로 54건 약정 사업수익률·세후) · "
              "RR-25-10 pp.42-44 (운영 5.60%·BTO-a 협상 3.23%·기획 2.85%, 불변 세후)",
}


def agreed_return_position(after_tax_return):
    """세후 수익률(소수)을 KOTI 54건 약정 수익률 분포와 비교 — 양방향 적정성.

    ⚠️ 세후 기준끼리만 비교(협약수익률[실질·세전]과 직접 비교 금지 —
    KOTI MP-24-11 pp.78-86: 노선마다 세전경상·세후실질 병기, 기준 불일치 시 오독).
    """
    if after_tax_return is None or after_tax_return != after_tax_return:
        return {"position": "산출 불가", "level": "na", "rate_pct": None,
                "note": MARKET_AGREED_RETURNS["source"]}
    r = float(after_tax_return) * 100.0
    m = MARKET_AGREED_RETURNS
    if r > m["max"]:
        pos, level = f"시장 전례 상단({m['max']:.1f}%) 초과, 과대 가능성 검토", "over"
    elif r >= 9.0:
        pos, level = f"초기 협약(MRG 시대 9~12%) 수준(현 시장 대비 높음)", "above"
    elif r >= m["avg"]:
        pos, level = (f"시장 평균({m['avg']:.2f}%) 상회, 중기 협약 권역"
                      f"(서울춘천 6.98%~수도권1순환 8.51%)", "above")
    elif r >= m["recent_low"]:
        pos, level = (f"BTO 후기 체결 수준({m['recent_low']:.0f}~{m['recent_high']:.0f}%) "
                      f"권역 · 운영 23개 평균 {m['operating_avg']:.2f}% 부근", "recent")
    elif r >= m["btoa_pipeline"]:
        pos, level = (f"BTO-a 신규 세대 권역(기획 {m['btoa_pipeline']:.2f}%~협상 "
                      f"{m['btoa_nego']:.2f}%), 현행 신규 협약 눈높이", "btoa")
    else:
        pos, level = (f"BTO-a 신규 세대 하단({m['btoa_pipeline']:.2f}%) 미만, "
                      f"과소(투자유인 부족) 가능성 검토", "under")
    return {"position": pos, "level": level, "rate_pct": r,
            "note": f"비교기준: {m['source']} · 세후끼리 비교 · 과소평가도 투자 위축 요인"}


# ── 4) 하방확률·VaR (MC 분포에서) ──
def downside_metrics(npv_samples=None, dscr_min_samples=None,
                     equity_irr_samples=None, dscr_threshold=1.0):
    """몬테카를로 표본에서 하방확률·VaR 산출. 표본 없으면 해당 키 생략."""
    out = {}
    if npv_samples is not None and len(npv_samples) > 0:
        a = np.asarray(npv_samples, dtype=float)
        a = a[~np.isnan(a)]
        if a.size:
            out["p_npv_negative"] = float((a < 0).mean())
            out["npv_p10"] = float(np.percentile(a, 10))
            out["npv_p50"] = float(np.percentile(a, 50))
            out["npv_var5"] = float(np.percentile(a, 5))  # 5% VaR(최악 5분위 NPV)
    if dscr_min_samples is not None and len(dscr_min_samples) > 0:
        d = np.asarray(dscr_min_samples, dtype=float)
        d = d[~np.isnan(d)]
        if d.size:
            out["p_dscr_below"] = float((d < dscr_threshold).mean())
            out["dscr_threshold"] = float(dscr_threshold)
            out["dscr_p10"] = float(np.percentile(d, 10))
    if equity_irr_samples is not None and len(equity_irr_samples) > 0:
        e = np.asarray(equity_irr_samples, dtype=float)
        e = e[~np.isnan(e)]
        if e.size:
            out["equity_irr_var5"] = float(np.percentile(e, 5))  # 5% VaR(최악 5분위 IRR)
            out["p_equity_irr_negative"] = float((e < 0).mean())
    return out


if __name__ == "__main__":
    for d in [1.55, 1.30, 1.12, 1.05, 0.80]:
        r = implied_rating(d)
        print(f"DSCR_min {d:.2f} → {r['implied_band']}")
    rng = np.random.default_rng(1)
    npv = rng.normal(500, 1500, 1000)
    dscr = rng.normal(1.2, 0.25, 1000)
    eirr = rng.normal(0.08, 0.06, 1000)
    dm = downside_metrics(npv, dscr, eirr)
    print("하방확률·VaR:", {k: round(v, 3) for k, v in dm.items()})
    # 재협상 트리거 스모크
    for ratios, want in [([0.66, 0.68, 0.65], "trigger"),
                         ([0.66, 0.75, 0.65], "watch"),
                         ([0.95, 1.02, 0.98], "ok")]:
        t = renegotiation_triggers(actual_ratios=ratios)
        assert t["worst"] == want, (ratios, t["worst"])
        print(f"트리거 {ratios} → {t['worst']} · {t['checks'][0]['detail']}")
    t2 = renegotiation_triggers(demand_revision_cut=0.35, capex_overrun=0.10)
    print("재검증:", [(c["name"], c["status"]) for c in t2["checks"]])
    # 협약수익률 위치 스모크
    for rr in [0.13, 0.07, 0.05, 0.038, 0.02, float("nan")]:
        ap = agreed_return_position(rr)
        print(f"세후수익률 {rr if rr == rr else '—'} → [{ap['level']}] {ap['position']}")
