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
        pos = "정상권 미달 — 부실(제이영동 0.31)과 정상 사이"
    else:
        pos = "부실(제이영동 0.31) 이하"
    return {
        "dscr_min": d, "opba_assumed": opba,
        "implied_band": band, "level": level, "investment_grade": ig,
        "market_position": pos,
        "note": "NICE 유료도로 평가방법론 근사 · 시장 벤치마크(천안논산 1.29·제이영동 0.31) 참조 · "
                "정식 등급 아님(사업위험·자본구조·재정지원 가산 별도)",
    }


# ── 2) 하방확률·VaR (MC 분포에서) ──
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
