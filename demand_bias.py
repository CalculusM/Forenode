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
# ⚠️ 교통량 기준과 수입 기준은 별개 지표 — 협약比 실측 '교통량' 평균 81.4%(22개 노선,
#   '22~'24) vs 협약比 '통행료 수입' 10년 평균 62.33%(수입이 체계적으로 더 낮음).
#   (KOTI RR-25-10 p.140·p.45) 본 prior는 교통량 기준.
BENCHMARK_PRIORS = {
    "도로: 국내 실측 22개 노선(KOTI '22~'24)": {
        # 분산 0.041 → 표준편차 ≈ 0.2025. 왜도 ≈0으로 정규 가정 충족(원문).
        "dist": "normal", "p1": 0.814, "p2": 0.2025,
        "median_ratio": 0.814,
        "source": "KOTI RR-25-10 PDF p.140(인쇄본 p.112), A고속도로 제외 22개 민자고속도로 "
                  "'22~'24 협약 대비 실측 교통량 평균 81.4%·분산 0.041(정규성 충족). "
                  "원천: 국토부 '2024년도 민자도로 건설·유지관리 현황 보고서' p.12. "
                  "운영 성숙 노선 포함(개통 초기는 이보다 낮음)",
    },
    "도로: 국제(Bain 2009)": {
        "dist": "normal", "p1": 0.77, "p2": 0.26,
        "median_ratio": 0.77,
        "source": "Bain·S&P 2009 유료도로 개통첫해 실측/예측 Normal(0.77,0.26), n=104",
    },
    "도로: 국내 민자 보수(초기군)": {
        "dist": "lognormal", "p1": 0.55, "p2": 0.30,
        "median_ratio": 0.55,
        "source": "국내 민자도로 초기군 0.4~0.6대(천안논산 47%·인천공항고속 41~50%·우면산 19~26%). "
                  "사례 종합 기반 내부 설정(단일 공식 분포 아님). Bain(2009) 신규 유료화국 "
                  "하위분포 Normal(0.58, 0.26)과 근사해 독립 문헌이 구조를 뒷받침. "
                  "※고속도로 조건부. 도시권·전환수요형은 밴드 밖 실증 3건(백테스트 V-009·011·019)",
    },
    "철도·경전철": {
        "dist": "lognormal", "p1": 0.30, "p2": 0.45,
        "median_ratio": 0.30,
        "source": "인천공항철도 7.3%·의정부 14%·용인 6~26%·김해부산 15% (Flyvbjerg 철도 +106% 과대). "
                  "국제 철도 실증 평균(~0.49)보다 보수적(국내 경전철 극단 사례 반영 내부 설정)",
    },
}


def loo_prior_params(exclude_routes, panel_path=None):
    """묶음 LOO — 실현율 패널에서 지정 노선(들)을 제외한 KOTI prior 파라미터 재계산.

    검증 프로토콜 v2 조건 1(분리): 채점 대상 사업이 prior 학습 표본에 있으면
    해당 노선을 빼고 평균·표준편차를 다시 계산해 그 prior로 채점한다.
    집계 기준 = 노선×연도 풀링(n=62)·표본분산(ddof=1) — KOTI 발표치(평균 81.4%·
    분산 0.041→σ 0.2025)와 전 표본 기준으로 일치함을 확인('26-07-31,
    build_realization_panel.prior_basis_check). backtest_plan_actual.loo_prior와
    동일 기준(전사본 62/62 교차 일치 검증됨).

    Parameters
    ----------
    exclude_routes : str | list[str]
        제외할 노선명(패널 canonical 표기 — 예: "상주-영천", "인천공항").
        묶음(blocked) LOO는 노선군 리스트를 그대로 전달.
    panel_path : str, optional
        data/realization_panel.csv 경로(기본: 모듈 기준 상대 경로).

    Returns
    -------
    dict — {"p1": 평균, "p2": 표준편차, "n_obs": 관측 수, "n_routes": 노선 수,
            "excluded": 실제로 제외된 노선 리스트}
        패널 파일이 없으면 전 표본 발표치(0.814, 0.2025)로 폴백하고
        "fallback": True를 표기한다(과소표기 방지 — 호출부에서 고지).
    """
    import csv
    import os

    if isinstance(exclude_routes, str):
        exclude_routes = [exclude_routes]
    exclude = set(exclude_routes)

    if panel_path is None:
        panel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "data", "realization_panel.csv")
    if not os.path.exists(panel_path):
        return {"p1": 0.814, "p2": 0.2025, "n_obs": 62, "n_routes": 22,
                "excluded": [], "fallback": True}

    ratios, routes, excluded = [], set(), set()
    with open(panel_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["지표"] != "교통량":
                continue
            name = row["노선"]
            if name in exclude:
                excluded.add(name)
                continue
            routes.add(name)
            ratios.append(float(row["실현율_pct"]) / 100.0)

    arr = np.asarray(ratios, dtype=float)
    return {"p1": float(arr.mean()), "p2": float(arr.std(ddof=1)),
            "n_obs": int(len(arr)), "n_routes": int(len(routes)),
            "excluded": sorted(excluded), "fallback": False}


def demand_optimism_band(forecast_traffic, prior="도로: 국제(Bain 2009)",
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
    p = BENCHMARK_PRIORS.get(prior, BENCHMARK_PRIORS["도로: 국제(Bain 2009)"])
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
    # 플래그: 과거 실적상 실측이 예측의 median_ratio 수준 → 그만큼 낙관 가능성.
    # 컷오프 0.60/0.85는 자체 기준 — 국제기관 공식 컷오프 전례 없음('26-07 문헌 검토).
    #   참고 앵커: 법정 재협상 트리거 70%(유료도로법 §23의5, 3년 연속)·MRG 지급하한 50%.
    #   한계: 판정이 선택된 prior의 중앙값에만 의존(입력 교통량 무반영) — 노선별
    #   예측↔실측 매칭(벤치마크 AADT) 확보 시 사업 특이 판정으로 고도화(v2).
    # 문구 원칙: 모호한 명사형 종결 금지 — 판정과 권고를 분명하게 끝맺는다.
    if median_ratio < 0.60:
        flag, level = "수요 낙관편향 위험 높음. 보수적 재검토가 필요합니다", "high"
    elif median_ratio < 0.85:
        flag, level = "수요 낙관편향 주의. 하방 시나리오를 함께 확인하세요", "mid"
    else:
        flag, level = "수요 가정이 과거 실적 범위 안에 있습니다(특이사항 없음)", "low"
    return {
        "prior": prior, "source": p["source"],
        "forecast": float(forecast_traffic),
        "p10": p10, "p50": p50, "p90": p90,
        "median_ratio": median_ratio,
        "haircut_pct": haircut,
        "flag": flag, "level": level,
        "n_sims": int(n_sims),
    }


def prob_ratio_below(threshold=0.70, prior="도로: 국제(Bain 2009)",
                     n_sims=3000, seed=20260625):
    """P(실측/예측 < threshold) — 재협상 트리거 도달 확률의 사전(ex-ante) 근사.

    유료도로법 §23의5: 3년 연속 실측 교통량·통행료수입이 실시협약 대비 70% 미달 시
    주무관청이 실시협약 변경을 요구할 수 있음(KOTI RR-23-19 pp.151-152).
    수요예측 오차는 연차 간 상관이 강한 '수준(level)' 현상이므로 단년 확률을
    3년 연속 조건의 근사 상한으로 사용. 램프업(개통 초기 저조 후 회복,
    예: 마창대교 40%→96.6%, KOTI MP-24-11 p.75)은 미반영 — 보수적 추정.
    """
    p = BENCHMARK_PRIORS.get(prior, BENCHMARK_PRIORS["도로: 국제(Bain 2009)"])
    rng = np.random.default_rng(seed)
    if p["dist"] == "normal":
        ratios = rng.normal(p["p1"], p["p2"], n_sims)
    else:
        ratios = rng.lognormal(np.log(p["p1"]), p["p2"], n_sims)
    ratios = np.clip(ratios, 0.05, 2.0)
    return float((ratios < float(threshold)).mean())


def revenue_haircut_band(annual_revenue_eok, prior="도로: 국제(Bain 2009)"):
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
