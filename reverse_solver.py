# -*- coding: utf-8 -*-
"""
역산(Goal Seek) — 「이 사업이 되려면」: 기준별 최소 필요 교통량 + 흑자 전환 연차

근거(시장 실증·'26-07-29 수렴):
- 한상욱 교수: "교통량 예측은 하지 마라 — 이 수익률을 내려면 최소 요구 교통량이
  얼마인가를 역산하라. 몇 대부터 몇 년 차에 흑자 전환되는지."
- 금광기업 서면 답변(같은 날): "역산(Goal Seek) 시뮬레이션 — 목표 실행률 맞춤 조건 추정."

검증 명세(투명성 원칙):
- 이 모듈은 예측·학습 모델이 아니라 **결정론 역산**이다. 현금흐름 엔진
  build_cashflow의 역함수를 이분법(bisection)으로 푼다. 따라서 훈련/검증 데이터
  분리 문제가 발생하지 않는다.
- 실측 prior(협약 대비 실현율 분포)는 역산 결과의 **위치 참조**(입력 대비 몇 %가
  필요한가 → 실측에서 그 이하로 실현된 노선 비율)에만 쓰이고 계산에는 개입하지 않는다.

계산 경로(전 단계 화면 표기용):
1) 수입 = f(교통량)이 선형이므로 [연수입(억) = 일교통량 × 계수 K],
   K = 통행료(원/km) × 연장(km) × 혼합계수 × 365일 ÷ 1e8 ÷ 1.1(VAT 차감)
   혼합계수 = (1-화물비율) + 화물비율 × 대형할증
2) 기준(정부 게이트/DSCR/목표 수익률)을 통과하는 최소 연수입을 이분법으로 탐색
   — 모든 대상 지표는 수입에 단조증가하므로 이분법이 유일해를 찾는다.
3) 최소 교통량 = 최소 연수입 ÷ K
주의: MRG 보장 기준수입은 annual_revenue와 함께 움직인다(협약 설계 관점 —
  "협약 수요를 얼마로 잡아야 통과하는가"). 운영비는 base_params에 시계열이 있으면
  고정(교통량이 줄어도 운영비는 줄지 않는 보수 가정), 수동 비율 모드면 매출비례.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np


def traffic_revenue_coeff(
    road_length_km: float,
    toll_per_km: float,
    heavy_ratio: float,
    heavy_surcharge: float,
) -> float:
    """연수입(억) = 일교통량(대) × K 의 계수 K. app.py estimate_toll_revenue와 동식."""
    mix = (1.0 - heavy_ratio) + heavy_ratio * heavy_surcharge
    return toll_per_km * road_length_km * mix * 365.0 / 1e8 / 1.1


def _metrics_at(base_params: dict, build_fn: Callable, ann_rev: float):
    try:
        _, m = build_fn(**{**base_params, "annual_revenue_억": float(ann_rev)})
        return m
    except Exception:
        return None


def _safe_ge(value, threshold: float) -> bool:
    """NaN·None 안전 비교 — 산출 불가 지표는 '미충족'으로 본다(과소표기 방지)."""
    if value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v != v:  # NaN
        return False
    return v >= threshold


def make_predicate(criterion: str, threshold: float = 0.0) -> Callable[[dict], bool]:
    """기준별 통과 판정 함수.

    criterion:
      "gov"  — 정부 게이트: 수입/비용 현가비율 ≥ 1.0 그리고 NPV ≥ 0
      "dscr" — 대주단: DSCR 최소 ≥ threshold
      "irr"  — 목표 사업수익률(명목·세후): nominal_irr ≥ threshold
    """
    if criterion == "gov":
        return lambda m: _safe_ge(m.get("bc_ratio"), 1.0) and _safe_ge(m.get("npv"), 0.0)
    if criterion == "dscr":
        return lambda m: _safe_ge(m.get("dscr_min"), threshold)
    if criterion == "irr":
        return lambda m: _safe_ge(m.get("nominal_irr"), threshold)
    raise ValueError(f"unknown criterion: {criterion}")


def min_revenue_for(
    base_params: dict,
    build_fn: Callable,
    predicate: Callable[[dict], bool],
    lo_frac: float = 0.02,
    hi_frac: float = 3.0,
    tol_억: float = 0.5,
) -> dict:
    """기준을 통과하는 최소 연수입(억)을 이분법으로 찾는다.

    반환: {"status": "ok"|"infeasible"|"below_range", "min_rev": float|None,
           "hi_rev": float}  — infeasible = 탐색 상한(hi_frac×현재)에서도 미달.
    """
    cur = float(base_params["annual_revenue_억"])
    lo = cur * lo_frac
    hi = cur * hi_frac

    m_hi = _metrics_at(base_params, build_fn, hi)
    if m_hi is None or not predicate(m_hi):
        return {"status": "infeasible", "min_rev": None, "hi_rev": hi}

    m_lo = _metrics_at(base_params, build_fn, lo)
    if m_lo is not None and predicate(m_lo):
        return {"status": "below_range", "min_rev": lo, "hi_rev": hi}

    for _ in range(60):
        mid = 0.5 * (lo + hi)
        m = _metrics_at(base_params, build_fn, mid)
        if m is not None and predicate(m):
            hi = mid
        else:
            lo = mid
        if hi - lo < tol_억:
            break
    return {"status": "ok", "min_rev": hi, "hi_rev": cur * hi_frac}


def surplus_years(
    base_params: dict, build_fn: Callable, ann_rev: Optional[float] = None
) -> dict:
    """흑자 전환 연차 — 당기 순이익(NetIncome) 첫 양전환 운영연차 + 누적 회수 연차.

    ann_rev 미지정 시 base_params 그대로(현 입력 시나리오).
    """
    params = dict(base_params)
    if ann_rev is not None:
        params["annual_revenue_억"] = float(ann_rev)
    try:
        cf, m = build_fn(**params)
    except Exception:
        return {"first_profit_op_year": None, "payback_year": None}
    con = int(params.get("construction_years", 0) or 0)
    ni = np.asarray(cf["NetIncome"], dtype=float)
    op = ni[con + 1:]
    pos = np.where(op > 0)[0]
    first_profit = int(pos[0]) + 1 if len(pos) else None

    # 누적 회수(payback): 누적 프로젝트 FCF가 최초 적자 후 0 이상으로 회복하는 연차.
    # (엔진 metrics['payback_year']는 0년차 누적=0을 회수로 오판하는 결함이 있어 자체 계산)
    cum = np.asarray(cf["CumProjectFCF"], dtype=float)
    payback_total = None
    neg = np.where(cum < 0)[0]
    if len(neg):
        rec = np.where(cum[neg[0]:] >= 0)[0]
        if len(rec):
            payback_total = int(neg[0] + rec[0])  # 총 연차(건설기 포함)
    payback_op = (payback_total - con) if payback_total is not None else None
    return {
        "first_profit_op_year": first_profit,
        "payback_total_year": payback_total,
        "payback_op_year": payback_op,
    }


def realization_scenarios(
    base_params: dict,
    build_fn: Callable,
    ratios=(1.0, 0.9, 0.814, 0.7, 0.623),
) -> list:
    """실현율 시나리오 — "예측(협약) 대비 실제가 X%라면 지표가 어떻게 되나".

    협약 수요(입력)는 그대로 두고 실현 수입만 ratio배로 낮춘다.
    핵심: forecast_revenue_억을 입력 수입으로 고정 전달 → MRG floor가 협약 기준으로
    정확히 발동한다(엔진 L1 분리 입력 — 역산의 '협약 설계 관점'과 반대 방향).
    앵커 2종(실측): 0.814 = 교통량 실현율 평균(협약 대비 81.4%, KOTI 22개 노선) ·
    0.623 = 통행료 수입 실현율 10년 평균(62.3%, KOTI RR-25-10 p.45·p.140 —
    수입은 교통량보다 체계적으로 더 낮게 실현됨. 수입 분포 자체 학습은 로드맵 ✚).

    반환 행: ratio, metrics(dict), first_profit_op_year, payback_op_year,
             mrg_total(누적 보전액), trigger(§23의5 70% 미달 방향 여부)
    """
    fc = float(base_params["annual_revenue_억"])
    rows = []
    for r in ratios:
        params = {
            **base_params,
            "annual_revenue_억": fc * r,
            "forecast_revenue_억": fc,
        }
        try:
            cf, m = build_fn(**params)
        except Exception:
            continue
        sy = surplus_years(params, build_fn)
        rows.append({
            "ratio": r,
            "metrics": m,
            "first_profit_op_year": sy["first_profit_op_year"],
            "payback_op_year": sy["payback_op_year"],
            "mrg_total": float(m.get("total_mrg_subsidy", 0.0) or 0.0),
            "trigger": r < 0.70,
        })
    return rows
