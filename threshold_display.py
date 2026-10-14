# -*- coding: utf-8 -*-
"""사업성 문턱 표시 전용 공용 함수(2026-10, 민자고속도로 추진현황 스터디 반영).

- 계산 경로 미사용: 현금흐름·역산은 reverse_solver. 여기는 역산된 문턱값으로 화면 문구와
  필요 통행료를 만든다. 기본값·골든 불변.
- 앱과 일괄 실행기(스터디 raw/threshold_run.py)가 같은 함수를 써서 round/ceil 불일치를 없앤다.
- 숫자 리터럴 없음: 요금 구조 상수는 config/finance_params.json(fiscal_toll_structure)에서 호출부가 읽어 넘긴다.
"""
import math

NOTICE = "자체 기준의 성립 조건 표시. 적격성 통과 여부와 무관, 경제성(B/C)·정책성 미산출."


def required_toll_at_capacity(toll_per_km: float, gov_traffic: float, cap_limit: float) -> int:
    """차로 한계 교통량에서 재무 성립선이 맞춰지는 km당 통행료(원, 올림).

    수입 비례 근사(문턱 수입 = 요금 × 교통량 비례), 수요 탄력 미반영.
    """
    return math.ceil(toll_per_km * gov_traffic / cap_limit)


def fiscal_toll_per_km(length_km: float, base_won: float, per_km_won: float, mult: float = 1.0) -> float:
    """재정고속도로 요금 구조(기본요금 + 1종 주행요금 × 연장) × 배수를 연장으로 나눈 실효 km당 요금(소수 1자리)."""
    return round((base_won + per_km_won * length_km) * mult / length_km, 1)


def resolve_private_capex(total_cost: float, subsidy: float | None, land: float | None, ratio: float) -> tuple:
    """민간투자비 환산: 건설보조금·보상비가 모두 있으면 차감, 아니면 총사업비×전국 비율(추정). (값, 근거 라벨)."""
    if subsidy is not None and land is not None:
        return round(total_cost - subsidy - land), "총사업비-건설보조금-보상비"
    return round(total_cost * ratio), f"총사업비×{ratio}(추정, 전국 비율)"


def headroom(cap_limit: float, gov_traffic: float) -> float:
    """용량 여유 배수 = 차로 한계 교통량 ÷ 재무 성립선 문턱(소수 2자리)."""
    return round(cap_limit / gov_traffic, 2)


def condition_core(gov_traffic: float, cap_limit: float, lanes: int, bold: bool = True) -> str:
    """성립 조건 문장(개조식): 문턱 교통량과 차로 한계 대비 여유 배수."""
    b = "**" if bold else ""
    return (f"성립 조건(재무 성립선, 자체 기준): 일 통행량 {b}{gov_traffic:,.0f}대{b} 이상. "
            f"왕복 {lanes}차로 한계(일 {cap_limit:,.0f}대) 대비 여유 {b}{headroom(cap_limit, gov_traffic):.2f}배{b}.")
