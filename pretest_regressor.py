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
  - 사업유형(BTO/BTO-rs/BTO-a/BTL)

출력:
  - 추정 CAPEX (억원, ±20% 참고범위 — 실무 통상 가정 휴리스틱)
  - 추정 OPEX 비율 (%)
  - 수익성 간이판정 (수입PV/CAPEX 비율 — PIMAC VfM과 다른 지표)

기술 스택:
  - sklearn.linear_model.LinearRegression (1차 모델)
  - 향후: sklearn.ensemble.GradientBoostingRegressor 또는 XGBoost
============================================================
"""
import numpy as np


# ════════════════════════════════════════════════════════════
# 사업유형별 기본값 매핑 — config/finance_params.json 단일 출처
# ('26-07-26 2계통 통일: 구 자체 값(BTO-a toll 80 등)은 휴면 경로 전용·근거 미확보라
#  실사용(app.py 사이드바) 값으로 통일. 폴백 = config 동치)
# ════════════════════════════════════════════════════════════
import config_loader as _cfg

_DEFAULTS_FALLBACK = {
    "BTO":     {"equity": 25, "opex": 30, "mrg": 0,   "mcc": 0,  "toll": 100, "desc": "수익형 — 운영 수익으로 회수 (정부 위험 분담 없음)"},
    "BTO-rs":  {"equity": 20, "opex": 32, "mrg": 50,  "mcc": 0,  "toll": 90,  "desc": "위험분담형 — 정부·사업자 수요위험 분담 (Risk Sharing)"},
    "BTO-a":   {"equity": 15, "opex": 35, "mrg": 90,  "mcc": 30, "toll": 130, "desc": "정부지급형(BTO-a) — 운영비 일부 정부 보전 (Annuity)"},
    "BTL":     {"equity": 10, "opex": 40, "mrg": 100, "mcc": 80, "toll": 0,   "desc": "임대형 — 정부 임대료 + 운영비 보전"},
    "BTO+BTL": {"equity": 18, "opex": 35, "mrg": 60,  "mcc": 50, "toll": 60,  "desc": "결합형(2024.10 신규) — 상부 BTO 사용료로 하부 BTL 임대료 충당"},
}


def _to_ratio_schema(d: dict) -> dict:
    """config 표기(%·원/km) → 이 모듈 표기(비율·원/km)."""
    return {bt: {
        "equity_ratio": v.get("equity", 0) / 100.0,
        "opex_ratio": v.get("opex", 0) / 100.0,
        "mrg_ratio": v.get("mrg", 0) / 100.0,
        "mcc_ratio": v.get("mcc", 0) / 100.0,
        "toll_per_km": v.get("toll", 0),
        "description": v.get("desc", ""),
    } for bt, v in d.items()}


BUSINESS_TYPE_DEFAULTS = _to_ratio_schema(_cfg.business_defaults(fallback=_DEFAULTS_FALLBACK))


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
    business_type: str = "BTO-a",
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
    business_type: str = "BTO-a",
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
    return BUSINESS_TYPE_DEFAULTS.get(business_type, BUSINESS_TYPE_DEFAULTS["BTO-a"])


# ════════════════════════════════════════════════════════════
# 수익성 간이판정 — 화면(phase_tabs)·PDF(report_generator) 공용 판정 함수
# ('26-07-26 3중 하드코딩 단일화: 구 휴면 vfm_judgment 제거 — 경계값 0.8은
#  활성 로직 0.85로 통일. 임계·문구 단일 출처 = config/finance_params.json)
# ════════════════════════════════════════════════════════════
_SCREEN_BANDS_FALLBACK = [
    {"min_bc": 1.3, "min_dscr": 1.20, "judgment": "수익성 매우 양호", "color": "#1D9E75",
     "recommendation": "정부 보전금 없이도 민간 사업주가 수익을 낼 수 있는 구조입니다. BTO 또는 BTO-rs 사업유형 검토 권장."},
    {"min_bc": 1.0, "min_dscr": 1.05, "judgment": "수익성 확보", "color": "#1F3864",
     "recommendation": "현재 MRG·자기자본비율 등 조건으로 사업 추진 가능. 민감도 분석에서 핵심 리스크 변수를 확인하세요."},
    {"min_bc": 0.85, "min_dscr": None, "judgment": "경계선 — 재구조화 검토", "color": "#EF9F27",
     "recommendation": "사업 조건 보완 필요. MRG 보장률 상향, 운영기간 연장, 또는 BTO-a 전환 등 시나리오 비교를 권합니다."},
    {"min_bc": None, "min_dscr": None, "judgment": "수익성 미달", "color": "#D45F5F",
     "recommendation": "현행 조건으로는 수익성 확보가 어렵습니다. 정부 보전 설계, 재정사업 전환 또는 사업계획 재검토를 권합니다."},
]


def profitability_screen(bc_ratio: float, dscr_min: float) -> dict:
    """
    수익성 간이판정 — 수입/비용 현가비율(B/C) + 최소 DSCR 밴드 판정.

    ※ 자체 간이규약 — PIMAC 적격성(AHP·VfM) 판정과 다른 지표(명칭 혼동 방지,
    '26-07 실무 정합 감사). 반환: {judgment, color, recommendation, min_bc, min_dscr}.
    """
    bands = _cfg.profitability_bands(fallback=_SCREEN_BANDS_FALLBACK)
    _defaults = {"judgment": "판정 불가", "color": "#999999", "recommendation": ""}
    for b in bands:
        ok_bc = b.get("min_bc") is None or bc_ratio >= b["min_bc"]
        ok_dscr = b.get("min_dscr") is None or dscr_min >= b["min_dscr"]
        if ok_bc and ok_dscr:
            return {**_defaults, **dict(b)}  # config 부분 결손 방어
    return {**_defaults, **dict(bands[-1])} if bands else dict(_defaults)
