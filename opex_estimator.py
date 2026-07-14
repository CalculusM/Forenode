"""
============================================================
Forenode — OPEX 자동 산출 모듈 (opex_estimator.py)
============================================================
역할:
  사업유형 + 노선 특성 + 운영 연차별 패턴(학습 데이터)으로부터
  30년 OPEX 시계열을 자동 산출하여 수익성·현금흐름에 반영

원칙:
  - OPEX는 분석의 중간 단계이고, 최종 목적은 수익성·현금흐름
  - 학습 데이터(도로공사 4,380건)는 "연차별 변동 패턴"으로 활용
  - 절대값은 사업유형 기본 OPEX 비율(BTO 30%~BTL 40%)을 베이스
  - 노선 보정 + 시간 패턴으로 시계열 생성

근거 데이터:
  - opex_lifecycle.json: 운영 연차별 평균 공사비·빈도
  - opex_pavement_freq.json: 노선별 보수 주기
  - opex_by_event_type.json: 사업구분별 통계

산출 결과:
  - opex_ratio (평균): 매출 대비 평균 OPEX 비율
  - opex_series_30y: 30년 시계열 (억원/년)
  - explanation: 산출 근거 한 줄
============================================================
"""
import json
import os
import numpy as np


# ════════════════════════════════════════════════════════════
# 학습 데이터 로드 (모듈 최초 로딩 시 1회)
# ════════════════════════════════════════════════════════════
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_json(filename):
    path = os.path.join(_BASE_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_LIFECYCLE = _load_json("opex_lifecycle.json")
_FREQ = _load_json("opex_pavement_freq.json")


# ════════════════════════════════════════════════════════════
# 사업유형별 기본 OPEX 비율 (매출 대비, 평균)
# ════════════════════════════════════════════════════════════
BIZ_BASE_OPEX = {
    "BTO": 0.30,
    "BTO-rs": 0.32,
    "BTO-ann": 0.35,
    "BTL": 0.40,
}


# ════════════════════════════════════════════════════════════
# 연차별 OPEX 변동 패턴 (학습 데이터에서 도출)
# ════════════════════════════════════════════════════════════
def _build_lifecycle_pattern() -> np.ndarray:
    """
    opex_lifecycle.json에서 연차별 (평균공사비 × 빈도)를 계산하여
    1에 정규화된 60년 패턴 벡터 반환.
    
    Returns:
        np.ndarray of shape (60,)
        index 0 = 1년차, index 59 = 60년차
    """
    if _LIFECYCLE is None:
        # 폴백: 일정한 패턴 (변동 없음)
        return np.ones(60)
    
    cost = _LIFECYCLE["운영연차별_평균공사비"]
    freq = _LIFECYCLE["운영연차별_공사빈도"]
    
    bucket_5y = []  # 5년 단위 OPEX 가중치
    for key in sorted(cost.keys(), key=lambda k: int(k.split("-")[0])):
        c = cost[key]
        f = freq[key]
        # 개량 + 수선유지 가중합 (빈도로 가중)
        total_cost = (c["개량사업"] * f["개량사업"] +
                      c["수선유지사업"] * f["수선유지사업"])
        total_freq = f["개량사업"] + f["수선유지사업"]
        weighted = total_cost / total_freq if total_freq > 0 else 0
        bucket_5y.append(weighted)
    
    # 1에 정규화 (5~9년차 = 기준 1.0)
    baseline = bucket_5y[1] if len(bucket_5y) > 1 else max(bucket_5y)
    if baseline == 0:
        baseline = max(bucket_5y) if max(bucket_5y) > 0 else 1
    
    bucket_normalized = [b / baseline for b in bucket_5y]
    
    # 5년 단위 → 1년 단위 시계열로 펼치기 (60년 = 12 buckets × 5)
    pattern_60y = np.zeros(60)
    for i, val in enumerate(bucket_normalized):
        start = i * 5
        end = min(start + 5, 60)
        pattern_60y[start:end] = val
    
    return pattern_60y


_LIFECYCLE_PATTERN = _build_lifecycle_pattern()


# ════════════════════════════════════════════════════════════
# 노선 특성별 OPEX 보정 계수
# ════════════════════════════════════════════════════════════
def _route_adjustment(terrain: str, tunnel_ratio: float, bridge_ratio: float) -> float:
    """
    지형·터널·교량 비율에 따른 OPEX 보정 계수.
    
    기준 1.0 = 평지·터널 0%·교량 0%
    
    - 산악 노선: 제설·낙석 관리비 증가
    - 터널: 조명·환기·안전 설비 추가 운영비
    - 교량: 도장·내진 점검 추가
    """
    terrain_adj = {"평지": 0.0, "구릉": 0.03, "산악": 0.08}.get(terrain, 0.0)
    tunnel_adj = tunnel_ratio * 0.20    # 터널 100%면 +20%
    bridge_adj = bridge_ratio * 0.10    # 교량 100%면 +10%
    return 1.0 + terrain_adj + tunnel_adj + bridge_adj


# ════════════════════════════════════════════════════════════
# 메인 함수 — OPEX 시계열 자동 산출
# ════════════════════════════════════════════════════════════
def estimate_opex_series(
    business_type: str,
    annual_revenue_억: float,
    operation_years: int,
    terrain: str = "평지",
    tunnel_ratio: float = 0.20,
    bridge_ratio: float = 0.15,
    growth_rate: float = 0.025,
    inflation: float = 0.02,
    road_length_km: float = None,
) -> dict:
    """
    사업유형 + 노선 특성 + 학습 데이터 패턴으로
    운영기간 OPEX 시계열을 산출.

    Returns
    -------
    dict with keys:
        - opex_ratio_avg : 운영기간 평균 OPEX 비율 (매출 대비)
        - opex_series_억 : list of float, 길이 operation_years
                          각 연도 OPEX 절대값 (억원)
        - peak_year      : OPEX 정점 연차
        - peak_amount_억 : 정점 OPEX 금액
        - explanation    : 산출 근거 한 줄
        - per_km_억      : (road_length_km 지정 시) 연평균 OPEX 원단위 (억/km/년)
        - warning        : (원단위가 실측 벤치마크 범위 밖일 때) 경고문 — L3 크로스체크

    L3 주의(인천공항 백테스트 2026-07): 매출비례 방식은 고요금 노선(km당 수입이 큰
    민자도로)에서 OPEX를 구조적으로 과대 추정한다 — 인천공항 실측 현금 OPEX는
    매출의 ~13%인데 기본비율은 30%대. road_length_km를 주면 원단위(억/km/년)로
    크로스체크해 범위 밖이면 warning을 반환한다(자동 개입 없음 — 검증 도구 원칙).
    """
    # 1. 사업유형 기본 비율
    base_ratio = BIZ_BASE_OPEX.get(business_type, 0.35)
    
    # 2. 노선 보정 계수
    route_factor = _route_adjustment(terrain, tunnel_ratio, bridge_ratio)
    adjusted_base = base_ratio * route_factor
    
    # 3. 연차별 패턴 적용 → 시계열 생성
    pattern = _LIFECYCLE_PATTERN[:operation_years]
    
    # 패턴이 운영기간보다 짧으면 마지막 값으로 연장
    if len(pattern) < operation_years:
        extension = np.full(operation_years - len(pattern), pattern[-1])
        pattern = np.concatenate([pattern, extension])
    
    # 시계열 = 매출 × 조정된 기본 비율 × 연차 패턴 (정규화)
    # 평균 패턴값이 1.0이 되도록 재정규화 → 전체 평균이 adjusted_base와 일치
    pattern_norm = pattern / pattern.mean() if pattern.mean() > 0 else pattern
    
    opex_series = []
    for y in range(operation_years):
        rev_growth = (1 + growth_rate) ** y
        infl_factor = (1 + inflation) ** y
        annual_revenue = annual_revenue_억 * rev_growth
        opex = annual_revenue * adjusted_base * pattern_norm[y]
        # 인플레이션은 패턴 외 추가 적용 안 함 (매출도 이미 성장 반영)
        opex_series.append(round(opex, 2))
    
    opex_arr = np.array(opex_series)
    peak_idx = int(np.argmax(opex_arr))
    peak_amount = float(opex_arr[peak_idx])
    
    explanation = (
        f"{business_type} 기본 {base_ratio*100:.0f}% × "
        f"노선보정 {route_factor:.2f} = 평균 {adjusted_base*100:.1f}% | "
        f"학습데이터(도로공사 11년치 4,380건) 연차 패턴 적용"
    )

    # L3 크로스체크: 원단위(억/km/년) — 실측 벤치마크 대비 범위 검사.
    # 벤치마크: 인천공항고속도로 실측 현금 OPEX(상각·이자 제외, DART FY2015~25 재구성)
    #   ≈ 경상 약 10억/km/년 · 2000년 불변 약 5.8억/km/년 (backtest_case_incheon).
    #   범위(1~12억/km/년)는 이 단일 실측 + 여유폭의 잠정치 — 1군 백테스트 확산 시 갱신.
    per_km = None
    warning = None
    if road_length_km and road_length_km > 0:
        per_km = float(opex_arr.mean()) / float(road_length_km)
        if per_km > 12.0 or per_km < 1.0:
            warning = (
                f"매출비례 추정 원단위 {per_km:.1f}억/km/년이 실측 벤치마크 범위(1~12억/km/년)를 "
                f"벗어났습니다 — 고요금 노선은 매출비례가 과대되기 쉬우니 물량 기반(bottom-up LCC) "
                f"산출 또는 실측 원단위로 재검토하세요"
            )

    return {
        "opex_ratio_avg": adjusted_base,
        "opex_series_억": opex_series,
        "peak_year": peak_idx + 1,
        "peak_amount_억": peak_amount,
        "explanation": explanation,
        "base_ratio": base_ratio,
        "route_factor": route_factor,
        "per_km_억": per_km,
        "warning": warning,
    }


# ════════════════════════════════════════════════════════════
# [C1] 상향식(물량기반 LCC) OPEX 시계열 — 현금흐름 직결
# ════════════════════════════════════════════════════════════
# 배경: estimate_lcc_maintenance(app.py)의 물량×표준단가×열화 LCC 엔진은
#       종전까지 화면 표시만 되고 build_cashflow의 opex_series로 연결되지
#       않았다(C1 단절). 아래 두 함수가 그 연결을 담당한다.
#
# 주의(정직성): LCC 엔진은 "자본적 유지보수(교체·대보수·일상보수)"만 산출하며
#       일상 운영비(징수·인건·제설·일반관리 등 routine O&M)는 포함하지 않는다.
#       따라서 총 OPEX = routine O&M baseline + 자본적 유지보수(LCC)로 구성한다.
#       routine_opex_ratio 기본값은 통행료도로 일상 O&M의 보수적 placeholder이며
#       실측 보정 전까지는 '가정값'임을 산출 설명에 명시한다.
#       또한 현재 LCC 물량은 BIM이 아닌 연장(road_length) 추정식이므로,
#       BIM/IFC 물량 연결 시 이 시계열이 정밀화된다(P1 후속과제).

def lcc_to_annual_series(lcc_df, operation_years):
    """estimate_lcc_maintenance가 반환한 lcc_df(연도별·부재별 'Cost_억')를
    운영연차별 자본적 유지보수비 시계열(억원, 명목·할인 전)로 집계.

    Parameters
    ----------
    lcc_df : DataFrame  (columns 최소 'Year', 'Cost_억')
    operation_years : int

    Returns
    -------
    np.ndarray shape (operation_years,)  # index 0 = 1년차
    """
    series = np.zeros(operation_years)
    if lcc_df is None or len(lcc_df) == 0:
        return series
    try:
        grp = lcc_df.groupby("Year")["Cost_억"].sum()
    except Exception:
        return series
    for yr, val in grp.items():
        idx = int(yr) - 1
        if 0 <= idx < operation_years:
            series[idx] += float(val)
    return series


def estimate_opex_series_bottomup(
    lcc_df,
    annual_revenue_억,
    operation_years,
    routine_opex_ratio: float = 0.18,
    growth_rate: float = 0.025,
) -> dict:
    """상향식(물량기반 LCC) OPEX 시계열 — estimate_opex_series와 동일한 dict 형태로
    반환하여 build_cashflow 경로에 그대로 투입(drop-in)할 수 있다.

    총 OPEX(y) = 일상 O&M(매출비례 baseline) + 자본적 유지보수(LCC, 물량기반)

    - 일상 O&M은 estimate_opex_series와 같이 매출성장만 반영(인플레는 build_cashflow가 적용).
    - LCC 'Cost_억'은 기준연도 명목값이므로 인플레는 build_cashflow가 적용(이중계상 없음).
    """
    cap_maint = lcc_to_annual_series(lcc_df, operation_years)  # 억/년 (기준연도)
    opex_series = []
    for y in range(operation_years):
        rev_growth = (1 + growth_rate) ** y
        routine = annual_revenue_억 * rev_growth * routine_opex_ratio
        opex_series.append(round(routine + float(cap_maint[y]), 2))

    opex_arr = np.array(opex_series)
    avg_ratio = float(opex_arr.mean() / annual_revenue_억) if annual_revenue_억 else 0.0
    peak_idx = int(np.argmax(opex_arr)) if len(opex_arr) else 0
    explanation = (
        f"상향식(실험): 일상 O&M {routine_opex_ratio*100:.0f}%(매출비례·가정값) "
        f"+ 물량기반 LCC 자본적유지보수(연장 추정물량 × 표준품셈 단가 × 열화모델). "
        f"평균 OPEX≈매출의 {avg_ratio*100:.1f}% | ※BIM 물량 연결 시 정밀화 예정"
    )
    return {
        "opex_ratio_avg": avg_ratio,
        "opex_series_억": opex_series,
        "peak_year": peak_idx + 1,
        "peak_amount_억": float(opex_arr[peak_idx]) if len(opex_arr) else 0.0,
        "explanation": explanation,
        "routine_opex_ratio": routine_opex_ratio,
        "cap_maint_series_억": cap_maint.tolist(),
        "is_bottomup": True,
    }


# ════════════════════════════════════════════════════════════
# [TODO①] 불확실성 밴드 — Weibull CI → OPEX P10/P50/P90 전파
# ════════════════════════════════════════════════════════════
# 배경: weibull_fit.py가 포장 열화 Weibull(β, η)과 95% CI(부트스트랩)를 산출하나
#       OPEX 엔진과 미연결이었음. 여기서 η(특성수명) CI를 OPEX 수준 불확실성으로 전파한다.
# 1차(level) 밴드: η가 작을수록 보수 빈도↑ → OPEX↑ (multiplier = η_hat/η_sample).
#   + 단가 불확실성(lognormal). ※타이밍-수준 MC(semi-Markov)는 후순위(🔵).

def load_weibull_ci(path: str = None) -> dict | None:
    """weibull_params.json → {eta_hat, eta_lo, eta_hi, beta_hat, beta_lo, beta_hi}. 없으면 None."""
    p = path or os.path.join(_BASE_DIR, "weibull_params.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    eta_lo = d.get("eta_ci_lower")
    eta_hi = d.get("eta_ci_upper")
    if eta_lo is None and isinstance(d.get("eta_ci_95"), list):
        eta_lo, eta_hi = d["eta_ci_95"]
    beta_lo = d.get("beta_ci_lower")
    beta_hi = d.get("beta_ci_upper")
    if beta_lo is None and isinstance(d.get("beta_ci_95"), list):
        beta_lo, beta_hi = d["beta_ci_95"]
    if d.get("eta_hat") is None or eta_lo is None or eta_hi is None:
        return None
    return {"eta_hat": float(d["eta_hat"]), "eta_lo": float(eta_lo), "eta_hi": float(eta_hi),
            "beta_hat": float(d.get("beta_hat", 1.0)),
            "beta_lo": float(beta_lo) if beta_lo is not None else None,
            "beta_hi": float(beta_hi) if beta_hi is not None else None}


def montecarlo_opex_band(base_series, weibull_ci: dict = None, n_sims: int = 500,
                         cost_cv: float = 0.12, seed: int = 20260612) -> dict:
    """OPEX 시계열 → P10/P50/P90 불확실성 밴드 (몬테카를로).

    Parameters
    ----------
    base_series : list/array  P50 OPEX 시계열(억/년)
    weibull_ci  : load_weibull_ci() 결과. None이면 단가 불확실성만.
    cost_cv     : 단가 변동계수(lognormal). 표준단가 미확정 시 보수적으로 크게.

    Returns dict: p10/p50/p90/mean 시계열 + n_sims + source.
    """
    base = np.asarray(base_series, dtype=float)
    if base.size == 0:
        return {"p10": [], "p50": [], "p90": [], "mean": [], "n_sims": 0, "source": "empty"}
    rng = np.random.default_rng(seed)
    sims = np.empty((n_sims, base.size))
    src = []
    eta_sd = None
    if weibull_ci:
        eta_sd = max(1e-6, (weibull_ci["eta_hi"] - weibull_ci["eta_lo"]) / (2 * 1.96))
        src.append("Weibull η CI")
    src.append(f"단가 cv={cost_cv:.0%}")
    for i in range(n_sims):
        m = 1.0
        if weibull_ci:
            eta_s = max(0.1, rng.normal(weibull_ci["eta_hat"], eta_sd))
            m *= weibull_ci["eta_hat"] / eta_s   # 특성수명↓ → 보수빈도↑ → OPEX↑
        # 단가 lognormal (평균 보존: E[exp(N(-σ²/2, σ²))]=1)
        m *= float(np.exp(rng.normal(-0.5 * cost_cv ** 2, cost_cv)))
        sims[i] = base * m
    return {
        "p10": np.percentile(sims, 10, axis=0).round(2).tolist(),
        "p50": np.percentile(sims, 50, axis=0).round(2).tolist(),
        "p90": np.percentile(sims, 90, axis=0).round(2).tolist(),
        "mean": sims.mean(axis=0).round(2).tolist(),
        "n_sims": n_sims,
        "source": " + ".join(src),
    }


# ════════════════════════════════════════════════════════════
# 자가 검증
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 70)
    print("OPEX 자동 산출 검증")
    print("=" * 70)
    
    # 화성-안성 (BTO-ann, 45km, 평지, 터널 20%, 교량 15%)
    result = estimate_opex_series(
        business_type="BTO-ann",
        annual_revenue_억=1500,
        operation_years=30,
        terrain="평지",
        tunnel_ratio=0.20,
        bridge_ratio=0.15,
    )
    
    print(f"\n[화성-안성 BTO-ann]")
    print(f"  평균 OPEX 비율: {result['opex_ratio_avg']*100:.2f}%")
    print(f"  정점 연차: {result['peak_year']}년차 ({result['peak_amount_억']:.1f}억)")
    print(f"  근거: {result['explanation']}")
    print(f"\n  시계열 (5년 단위 샘플):")
    for y in [1, 5, 10, 15, 20, 25, 30]:
        if y <= 30:
            print(f"    {y:2d}년차: {result['opex_series_억'][y-1]:.1f}억")
    
    # 4가지 사업유형 비교
    print(f"\n[4가지 사업유형 비교 — 평균 OPEX 비율]")
    for biz in ["BTO", "BTO-rs", "BTO-ann", "BTL"]:
        r = estimate_opex_series(biz, 1500, 30, "평지", 0.20, 0.15)
        print(f"  {biz:10s}: {r['opex_ratio_avg']*100:5.2f}% | 1년차 {r['opex_series_억'][0]:.1f}억 | 정점 {r['peak_year']:2d}년차 {r['peak_amount_억']:.1f}억")
    
    # 노선 특성 비교
    print(f"\n[노선 특성 비교 — BTO-ann 기준]")
    for terrain, t, b in [("평지", 0.10, 0.10), ("평지", 0.30, 0.20),
                           ("구릉", 0.20, 0.15), ("산악", 0.40, 0.25)]:
        r = estimate_opex_series("BTO-ann", 1500, 30, terrain, t, b)
        print(f"  {terrain} 터널{t*100:.0f}% 교량{b*100:.0f}%: 평균 {r['opex_ratio_avg']*100:.2f}%")
