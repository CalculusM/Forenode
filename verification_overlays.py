# -*- coding: utf-8 -*-
"""
검증 오버레이 (verification_overlays.py) — Forenode

기존 산출(DSCR·NPV·MC 분포)에 얹는 '검증 도구' 지표:
  1) implied_rating  : 최소DSCR → 예비 신용등급 밴드 근사 (금융주관사·재무투자자 설득력)
  2) downside_metrics: MC 분포에서 하방확률·VaR (단정 아닌 확률로 제시)

※ 신규 핵심 계산을 바꾸지 않는 '얹는' 오버레이 — build_cashflow 등 코어 불변.
"""
import numpy as np


# ── 1) 예비 신용등급 매핑 (S&P 일반 PF 방법론 근사) ──
# ⚠️ S&P 기준표는 저작권 → 자체 근사 그리드. '정식 등급 아님' 라벨 필수.
def implied_rating(dscr_min, opba="중(3~5)"):
    """최소 DSCR → 예비 신용프로파일 밴드(근사). 운영기 사업평가(OPBA)는 간이 가정."""
    if dscr_min is None or dscr_min != dscr_min:  # NaN guard
        return {"dscr_min": None, "implied_band": "—", "level": "na",
                "note": "DSCR 산출 불가"}
    if dscr_min >= 1.40:
        band, level = "투자등급 상단 (≈BBB+/A-)", "ig_high"
    elif dscr_min >= 1.20:
        band, level = "투자등급 (≈BBB)", "ig"
    elif dscr_min >= 1.10:
        band, level = "투자등급 경계 (≈BBB-/BB+)", "edge"
    elif dscr_min >= 1.00:
        band, level = "투기등급 (≈BB/B)", "spec"
    else:
        band, level = "디폴트 위험 (≈CCC 이하)", "default"
    return {
        "dscr_min": float(dscr_min), "opba_assumed": opba,
        "implied_band": band, "level": level,
        "note": "S&P 일반 PF 방법론(OPBA×최소DSCR) 근사 — 자체 그리드·정식 등급 아님",
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
