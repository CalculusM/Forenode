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
    
    return {
        "opex_ratio_avg": adjusted_base,
        "opex_series_억": opex_series,
        "peak_year": peak_idx + 1,
        "peak_amount_억": peak_amount,
        "explanation": explanation,
        "base_ratio": base_ratio,
        "route_factor": route_factor,
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
