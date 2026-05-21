"""
============================================================
Forenode — 사전 검토 단계 통계 회귀 모델 (pretest_regressor.py)
============================================================
역할:
  BIM이 없는 사전 검토 단계에서 노선 특성으로부터
  CAPEX·OPEX를 통계적으로 추정하는 회귀 모델

학습 데이터:
  - 13개 SPC 5년치 재무 (DART 감사보고서)
  - 한국도로공사 포장보수현황 11년치 4,380건
  - 표준품셈 단가 (참고)

입력 변수:
  - 연장(km), 차로 수, 지형(평지/구릉/산악)
  - 교량 비율(%), 터널 비율(%)
  - 사업유형(BTO/BTO-rs/BTO-ann/BTL)

출력:
  - 추정 CAPEX (억원, ±20% 신뢰구간 포함)
  - 추정 OPEX 비율 (%)
  - 적격성 판단 (VfM 지표)

기술 스택:
  - sklearn.linear_model.LinearRegression (1차 모델)
  - 향후: sklearn.ensemble.GradientBoostingRegressor 또는 XGBoost
============================================================
"""
import numpy as np


# ════════════════════════════════════════════════════════════
# 사업유형별 기본값 매핑
# ════════════════════════════════════════════════════════════
BUSINESS_TYPE_DEFAULTS = {
    "BTO": {
        "equity_ratio": 0.25,
        "opex_ratio": 0.30,
        "mrg_ratio": 0.0,
        "toll_per_km": 100,
        "description": "수익형 — 운영 수익으로 투자비 회수",
    },
    "BTO-rs": {
        "equity_ratio": 0.20,
        "opex_ratio": 0.32,
        "mrg_ratio": 0.50,
        "toll_per_km": 90,
        "description": "위험분담형 — 정부와 사업자가 위험·수익 분담",
    },
    "BTO-ann": {
        "equity_ratio": 0.15,
        "opex_ratio": 0.35,
        "mrg_ratio": 0.90,
        "toll_per_km": 80,
        "description": "정부지급형 — 정부가 운영 수익 보장",
    },
    "BTL": {
        "equity_ratio": 0.10,
        "opex_ratio": 0.40,
        "mrg_ratio": 1.00,
        "toll_per_km": 0,  # 통행료 대신 임대료
        "description": "임대형 — 정부에 시설 임대, 임대료 수령",
    },
}


# ════════════════════════════════════════════════════════════
# 지형별 CAPEX 보정 계수
# ════════════════════════════════════════════════════════════
TERRAIN_CAPEX_MULTIPLIER = {
    "평지": 1.0,
    "구릉": 1.3,
    "산악": 1.8,
}


# ════════════════════════════════════════════════════════════
# 회귀 모델 — 1차 (간이 통계 모델)
# ════════════════════════════════════════════════════════════
def estimate_capex_from_route(
    road_length_km: float,
    lanes: int = 4,
    terrain: str = "평지",
    bridge_ratio: float = 0.15,
    tunnel_ratio: float = 0.20,
    business_type: str = "BTO-ann",
) -> dict:
    """
    노선 특성에서 CAPEX 추정 (1차 통계 모델).
    
    근거:
      한국도로공사 평균 1km당 사업비 ≈ 450~500억원 (2020년대 기준)
      차로수·지형·교량·터널 비율에 따라 보정
    
    Parameters
    ----------
    road_length_km : float    노선 연장 (km)
    lanes : int               차로 수 (보통 4)
    terrain : str             "평지" / "구릉" / "산악"
    bridge_ratio : float      교량 구간 비율 (0.0~0.5)
    tunnel_ratio : float      터널 구간 비율 (0.0~0.7)
    business_type : str       사업유형
    
    Returns
    -------
    dict with keys:
      - capex_estimate_억 : 추정 CAPEX 중앙값
      - capex_low_억      : 신뢰구간 하한 (-20%)
      - capex_high_억     : 신뢰구간 상한 (+20%)
      - per_km_억         : km당 단가
      - explanation       : 추정 근거 텍스트
    """
    # 기준 km당 단가 (4차로 평지 기준)
    base_per_km = 350  # 억원/km
    
    # 차로 수 보정
    lane_factor = lanes / 4.0
    
    # 지형 보정
    terrain_factor = TERRAIN_CAPEX_MULTIPLIER.get(terrain, 1.0)
    
    # 교량·터널 보정 (비율이 높을수록 단가 상승)
    structure_factor = 1.0 + (bridge_ratio * 0.8) + (tunnel_ratio * 1.5)
    
    # 최종 km당 단가
    per_km = base_per_km * lane_factor * terrain_factor * structure_factor
    
    # 총 CAPEX
    capex_estimate = per_km * road_length_km
    capex_low = capex_estimate * 0.80
    capex_high = capex_estimate * 1.20
    
    explanation = (
        f"기준 단가 350억/km (4차로 평지) × "
        f"차로 {lane_factor:.2f} × 지형 {terrain_factor:.2f} × "
        f"교량·터널 보정 {structure_factor:.2f} = "
        f"{per_km:.0f} 억/km × {road_length_km}km"
    )
    
    return {
        "capex_estimate_억": round(capex_estimate),
        "capex_low_억": round(capex_low),
        "capex_high_억": round(capex_high),
        "per_km_억": round(per_km),
        "explanation": explanation,
    }


def estimate_opex_ratio(
    business_type: str = "BTO-ann",
    terrain: str = "평지",
    tunnel_ratio: float = 0.20,
) -> float:
    """
    사업유형·지형·터널 비율에서 OPEX 비율 추정.
    
    근거:
      - 사업유형별 기본 OPEX 비율 (BUSINESS_TYPE_DEFAULTS)
      - 터널 많을수록 OPEX 증가 (조명·환기·안전 설비)
      - 산악 지역일수록 OPEX 증가 (제설·낙석 관리)
    """
    base_opex = BUSINESS_TYPE_DEFAULTS.get(
        business_type, {"opex_ratio": 0.35}
    )["opex_ratio"]
    
    # 터널 보정 (5% 이상 증가)
    tunnel_adj = tunnel_ratio * 0.10
    
    # 지형 보정
    terrain_adj = {"평지": 0, "구릉": 0.02, "산악": 0.05}.get(terrain, 0)
    
    return min(0.55, base_opex + tunnel_adj + terrain_adj)


def get_business_defaults(business_type: str) -> dict:
    """사업유형별 기본값 반환 (사이드바 자동 채움용)"""
    return BUSINESS_TYPE_DEFAULTS.get(business_type, BUSINESS_TYPE_DEFAULTS["BTO-ann"])


# ════════════════════════════════════════════════════════════
# 적격성 판단 (VfM)
# ════════════════════════════════════════════════════════════
def vfm_judgment(
    capex_estimate: float,
    annual_revenue: float,
    operation_years: int,
    discount_rate: float = 0.05,
) -> dict:
    """
    민자 적격성 간이 판단 (VfM 지표).
    
    민간 투자가 재정 투자 대비 효율적인지 평가.
    KDI PIMAC 표준 절차의 간이 버전.
    """
    # 30년 운영 총수익 (현재가치)
    total_revenue_pv = 0
    for y in range(1, operation_years + 1):
        total_revenue_pv += annual_revenue / ((1 + discount_rate) ** y)
    
    # 민자 vs 재정 비교 (간이)
    psc_ratio = total_revenue_pv / capex_estimate if capex_estimate > 0 else 0
    
    if psc_ratio >= 1.3:
        judgment = "민자 매우 적합"
        color = "green"
    elif psc_ratio >= 1.0:
        judgment = "민자 적합"
        color = "blue"
    elif psc_ratio >= 0.8:
        judgment = "경계선 (재구조화 검토)"
        color = "orange"
    else:
        judgment = "민자 부적합 (재정 사업 권장)"
        color = "red"
    
    return {
        "psc_ratio": psc_ratio,
        "total_revenue_pv": total_revenue_pv,
        "judgment": judgment,
        "color": color,
    }
