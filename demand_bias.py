# -*- coding: utf-8 -*-
"""
수요예측 낙관편향 보정 (demand_bias.py) — Forenode 검증 오버레이

핵심: 사업자/예타가 제출한 '예측 교통량'에 과거 (실측/예측) 분포(prior)를 곱해
'실제 가능' 교통량의 P10/P50/P90 밴드와 낙관편향 플래그를 산출한다.
적자를 흑자로 바꾸는 게 아니라, 수요 가정이 과거 실적 대비 낙관적인지 '검증'하는 도구.

근거(공개·1차):
- Bain·S&P(2009) 유료도로 개통첫해 실측/예측 = Normal(0.77, 0.26), n=104.
- KOTI 「2014 국가교통DB 사후평가」: 244개 SOC 중 실측/예측<50% = 131개(53%).
- 국내 민자도로 초기군 0.4~0.6대 / 철도·경전철 5~15%.
리서치 노트: Forenode_wiki/05-Resources/demand-optimism-bias-benchmark.md
※ prior는 reference-class 추정치 — 점추정 아닌 '밴드'로만 제시(오버클레임 금지).
"""
import numpy as np

# (실측/예측) ratio 벤치마크 prior. 사용자가 사업유형에 맞게 선택.
BENCHMARK_PRIORS = {
    "도로 — 국제(Bain 2009)": {
        "dist": "normal", "p1": 0.77, "p2": 0.26,
        "median_ratio": 0.77,
        "source": "Bain·S&P 2009 유료도로 개통첫해 실측/예측 Normal(0.77,0.26), n=104",
    },
    "도로 — 국내 민자 보수(초기군)": {
        "dist": "lognormal", "p1": 0.55, "p2": 0.30,
        "median_ratio": 0.55,
        "source": "국내 민자도로 초기군 0.4~0.6대(천안논산 47%·인천공항고속 47~50%·우면산 19~26%)",
    },
    "철도·경전철": {
        "dist": "lognormal", "p1": 0.30, "p2": 0.45,
        "median_ratio": 0.30,
        "source": "인천공항철도 7.3%·의정부 14%·용인 6~26%·김해부산 15% (Flyvbjerg 철도 +106% 과대)",
    },
}


def demand_optimism_band(forecast_traffic, prior="도로 — 국제(Bain 2009)",
                         n_sims=3000, seed=20260625):
    """예측 교통량 × (실측/예측) prior → 실제 가능 교통량 밴드 + 낙관편향 진단.

    Parameters
    ----------
    forecast_traffic : float  예측(입력) 일평균 교통량
    prior : str  BENCHMARK_PRIORS 키
    Returns
    -------
    dict (P10/P50/P90 교통량, 예측 대비 비율, haircut%, 플래그, 출처)
    """
    p = BENCHMARK_PRIORS.get(prior, BENCHMARK_PRIORS["도로 — 국제(Bain 2009)"])
    rng = np.random.default_rng(seed)
    if p["dist"] == "normal":
        ratios = rng.normal(p["p1"], p["p2"], n_sims)
    else:  # lognormal: p1=median, p2=sigma(of log)
        ratios = rng.lognormal(np.log(p["p1"]), p["p2"], n_sims)
    ratios = np.clip(ratios, 0.05, 2.0)  # 물리적 범위(예측의 5%~200%)
    sims = float(forecast_traffic) * ratios
    p10, p50, p90 = (float(x) for x in np.percentile(sims, [10, 50, 90]))
    median_ratio = float(p["median_ratio"])
    haircut = (1.0 - median_ratio) * 100.0
    # 플래그: 과거 실적상 실측이 예측의 median_ratio 수준 → 그만큼 낙관 가능성
    if median_ratio < 0.60:
        flag, level = "낙관 가능성 매우 높음", "high"
    elif median_ratio < 0.85:
        flag, level = "낙관 가능성 있음", "mid"
    else:
        flag, level = "보통", "low"
    return {
        "prior": prior, "source": p["source"],
        "forecast": float(forecast_traffic),
        "p10": p10, "p50": p50, "p90": p90,
        "median_ratio": median_ratio,
        "haircut_pct": haircut,
        "flag": flag, "level": level,
        "n_sims": int(n_sims),
    }


def revenue_haircut_band(annual_revenue_eok, prior="도로 — 국제(Bain 2009)"):
    """연매출(억)에 수요 prior를 적용한 '실제 가능' 매출 밴드(수입은 교통량에 ~선형 가정)."""
    b = demand_optimism_band(1.0, prior=prior)  # ratio 분포만 사용
    return {
        "p50_revenue": float(annual_revenue_eok) * b["p50"],
        "p10_revenue": float(annual_revenue_eok) * b["p10"],
        "p90_revenue": float(annual_revenue_eok) * b["p90"],
        "median_ratio": b["median_ratio"], "flag": b["flag"], "level": b["level"],
        "source": b["source"],
    }


if __name__ == "__main__":
    for pr in BENCHMARK_PRIORS:
        r = demand_optimism_band(30000, prior=pr)
        print(f"[{pr}] 예측 30,000 → 실제 P50 {r['p50']:,.0f} "
              f"(P10 {r['p10']:,.0f}~P90 {r['p90']:,.0f}) · "
              f"중앙비율 {r['median_ratio']:.2f} · haircut {r['haircut_pct']:.0f}% · {r['flag']}")
