# -*- coding: utf-8 -*-
"""추진 노선 파이프라인 데이터셋 로더 (data/route_pipeline_2026-10.csv, 엔진 미연동 리서치 자산).

- load_route_pipeline(version=None): CSV를 문자열 DataFrame으로 읽는다(결측은 빈 문자열 유지).
- engine_inputs(row): 한 행을 tests/_helpers.app_default_case(**inputs) 호출용 dict로 변환.
  규칙 ① 소형차전용=Y 이면 heavy_ratio_pct=0 ② 터널비율은 앱 슬라이더 상한(app.py _TUNNEL_MAX)으로 캡
  ③ 빈칸 항목은 키를 넣지 않는다(앱 기본값 사용). 5개 입력(사업방식·연장·민간투자비·통행료·운영기간)은 36행 전부 존재.
- route_key(name): 노선 표기 정규화(접두 [후보]·괄호·도로 종류 접미 제거). 빌드 스크립트·시험과 공유.
"""
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPELINE_CSV = os.path.join(ROOT, "data", "route_pipeline_2026-10.csv")
_ALIAS = {"평택~부여~익산": "익산~부여"}   # KOTI 표기(서부내륙 전체)와 2단계 사업명의 대응 1건

ENGINE_NUMERIC = {   # CSV 열 -> app_default_case 키
    "연장_km": "road_length", "민간투자비_억": "total_capex", "통행료_원km": "toll_per_km",
    "운영기간_년": "operation_years", "교량비율": "bridge_ratio", "터널비율": "tunnel_ratio", "차로": "lanes",
}


def route_key(name: str) -> str:
    s = re.sub(r"^\[[^\]]*\]\s*", "", str(name)).strip()
    s = re.split(r"\s*\(", s)[0]
    s = re.sub(r"\s*확장$", "", s)
    s = re.sub(r"\s*(?:관통\s*)?(?:지하고속도로|고속화도로|고속도로|지하도로)$", "", s).strip()
    return _ALIAS.get(s, s)


def tunnel_cap(default: float = 0.70) -> float:
    """사이드바 터널 비율 입력 상한(config input_limits.tunnel_ratio_max_pct, 앱과 같은 출처). 결손 시 종전 상한 0.70."""
    try:
        import config_loader
        return int(config_loader.load_finance_params()["input_limits"]["tunnel_ratio_max_pct"]) / 100
    except Exception:
        return default


def load_route_pipeline(version: str | None = None, path: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or PIPELINE_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    if version:
        df = df[df["pipeline_version"] == version].reset_index(drop=True)
    return df


def _num(s: str):
    v = float(s)
    return int(v) if v.is_integer() else v


def engine_inputs(row) -> dict:
    out = {"business_type": row["사업방식"]}
    for col, key in ENGINE_NUMERIC.items():
        if str(row.get(col, "")).strip() != "":
            out[key] = _num(row[col])
    if "tunnel_ratio" in out:
        out["tunnel_ratio"] = min(out["tunnel_ratio"], tunnel_cap())
    if row.get("소형차전용", "") == "Y":
        out["heavy_ratio_pct"] = 0
    return out
