# -*- coding: utf-8 -*-
"""표준 파라미터 config 로더 (config/opex_params.json).

TODO②(별표5/시특법 톱니파형 OPEX)가 이 로더로 파라미터를 읽는다.
파일이 없거나 손상되면 빈 dict가 아니라 안전한 폴백(현 app.py 하드코딩 동치)을 쓰도록
호출부에서 .get(...) 기본값을 함께 둘 것.
"""
import json
import os
from functools import lru_cache

_BASE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_BASE, "config", "opex_params.json")
_FIN_PATH = os.path.join(_BASE, "config", "finance_params.json")


@lru_cache(maxsize=8)
def _load_json_cached(path: str, mtime: float) -> dict:
    """mtime을 캐시 키에 포함 — 파일이 갱신되면(배포 핫스왑 포함) 자동 재로드."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_json(path: str) -> dict:
    try:
        return _load_json_cached(path, os.path.getmtime(path))
    except Exception as e:
        print(f"[config_loader] 로드 실패({e}) — 호출부 폴백 사용", flush=True)
        return {}


def load_params() -> dict:
    """config/opex_params.json 로드 (mtime 캐시). 실패 시 {} 반환."""
    return _load_json(_PATH)


def materials(fallback: dict | None = None) -> dict:
    """OPEX 카테고리별 파라미터 {ASPHALT: {...}, ...}. 없으면 fallback."""
    return load_params().get("materials") or (fallback or {})


def lcc_discount_rate(default: float = 0.045) -> float:
    return float(load_params().get("lcc", {}).get("discount_rate_real", default))


def inspection_cycles(fallback: dict | None = None) -> dict:
    return load_params().get("inspection_cycle_years") or (fallback or {})


def env_factor(level: str = "normal", default: float = 1.0) -> float:
    return float(load_params().get("env_factor_iso15686", {}).get(level, default))


def load_finance_params() -> dict:
    """config/finance_params.json 로드 (mtime 캐시). 실패 시 {} 반환."""
    return _load_json(_FIN_PATH)


def profitability_bands(fallback: list | None = None) -> list:
    """수익성 간이판정 밴드 [{min_bc, min_dscr, judgment, color, recommendation}, ...]."""
    return load_finance_params().get("profitability_screen", {}).get("bands") or (fallback or [])


def business_defaults(fallback: dict | None = None) -> dict:
    """사업유형별 기본값 {BTO: {equity, opex, mrg, mcc, toll, desc}, ...} (단위: %·원/km)."""
    return load_finance_params().get("business_type_defaults") or (fallback or {})


def capacity_gate(fallback: dict | None = None) -> dict:
    """차로수별 일 교통량 경고/한계 게이트 — KHCM 2013 산식+실측 최대('26-08-06)."""
    return load_finance_params().get("capacity_gate") or (fallback or {})


if __name__ == "__main__":
    p = load_params()
    print("로드:", "OK" if p else "FAIL")
    m = materials()
    print(f"materials: {len(m)}종 — 예: ASPHALT cycle={m.get('ASPHALT', {}).get('cycle_years')}년 "
          f"단가={m.get('ASPHALT', {}).get('unit_cost_won')}원/{m.get('ASPHALT', {}).get('unit')}")
    print(f"LCC 할인율: {lcc_discount_rate()}")
    print(f"점검(정밀안전점검) B등급 주기: {inspection_cycles().get('정밀안전점검', {}).get('B')}년")
    print(f"환경계수 high: {env_factor('high')}")
