# -*- coding: utf-8 -*-
"""수입 실현율 범위 표시 전용 모듈 (VP 게이트 B안, 2026-10-05).

- 역할: 화면 캡션·한 장 요약 PDF에 수입 실현율 범위(하위 10%~상위 10%, 중앙값)를 병기할 문구 생성.
- 계산 경로 미사용: 현금흐름·역산·실현율 시나리오(reverse_solver 0.623)는 이 모듈을 쓰지 않는다.
- 하드코딩 금지: 범위 수치·노선 수·연도·비교값은 후보 파일(data/revenue_band_candidate_2026-09.json)에서,
  판정 강도·표기 단서는 게이트 파일(data/revenue_band_gate_2026-10.json)에서 실행 시 읽는다.
- 스냅샷 확인: 후보 파일 내용 sha256(줄바꿈 LF 정규화)·후보 태그·panel_version·판정이 게이트 파일과
  일치할 때만 범위를 돌려준다. 불일치·부재·손상 시 None, 호출부는 기존 문구로 표시(안전 폴백).
"""
import hashlib
import json
import os
from decimal import ROUND_HALF_UP, Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
GATE_PATH = os.path.join(_HERE, "data", "revenue_band_gate_2026-10.json")


def _sha256_lf(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def _int_pct(x: float) -> int:
    """정수 % 반올림(사사오입, 소수 첫째 자리 5 이상 올림)."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dig(d: dict, dotted: str):
    for k in dotted.split("."):
        d = d[k]
    return d


def load_band(gate_path: str = None) -> dict:
    """게이트·후보 파일을 읽어 표시용 범위 dict 반환. 실패 시 None(예외 없음)."""
    try:
        gpath = gate_path or GATE_PATH
        with open(gpath, encoding="utf-8") as f:
            gate = json.load(f)
        if gate.get("display_option") != "B":
            return None
        cpath = os.path.join(_HERE, gate["candidate_file"])
        if _sha256_lf(cpath) != gate["candidate_sha256_lf"]:
            return None
        with open(cpath, encoding="utf-8") as f:
            cand = json.load(f)
        if (cand.get("candidate_tag") != gate["candidate_tag"]
                or cand.get("panel_version") != gate["panel_version"]
                or cand.get("verdict") != "작동"
                or cand.get("adopted_model") != gate["band_model"]):
            return None
        band = cand["band_full_sample"]
        if band.get("model") != gate["band_model"]:
            return None
        years = sorted(int(y) for y in cand["data_summary"]["year_means_complete_routes"]["by_year"])
        ref = gate["reference"]
        ref_value = float(_dig(cand, ref["value_path"]))
        disp = gate["display"]
        return {
            "p10": _int_pct(band["P10_pct"]),
            "p50": _int_pct(band["P50_pct"]),
            "p90": _int_pct(band["P90_pct"]),
            "p10_pct": float(band["P10_pct"]),
            "p50_pct": float(band["P50_pct"]),
            "p90_pct": float(band["P90_pct"]),
            "n_routes": int(cand["data_summary"]["n_routes"]),
            "year_from": years[0],
            "year_to": years[-1],
            "strength": disp["strength"],
            "basis": disp["basis"],
            "validation": disp["validation"],
            "calc_note": disp["calc_note"],
            "ref_value_pct": round(100.0 * ref_value, 1),
            "ref_value_ratio": ref_value,
            "ref_label": ref["label"],
            "ref_source": ref["source"],
            "ref_period": ref["period"],
            "candidate_tag": gate["candidate_tag"],
            "panel_version": gate["panel_version"],
        }
    except Exception:
        return None


def band_short(b: dict, md: bool = False) -> str:
    """짧은 병기: 수입 실현율 범위 {P10}~{P90}%(중앙값 {P50}%, {연도} {노선 수} {기준}, 판정 강도 {강도}).
    md=True: st.caption·st.markdown용. 단일 ~ 2개를 마크다운이 취소선으로 읽으므로 역슬래시로 이스케이프."""
    t = "\\~" if md else "~"
    return (f"수입 실현율 범위 {b['p10']}{t}{b['p90']}%(중앙값 {b['p50']}%, "
            f"{b['year_from']}{t}{b['year_to']}년 {b['n_routes']}개 노선 {b['basis']}, "
            f"판정 강도 {b['strength']})")


def band_detail(b: dict, md: bool = False) -> str:
    """상세 병기(실현율 시나리오·한 장 요약 PDF): 검증 방식·계산 미반영 단서 포함. md는 band_short와 동일."""
    t = "\\~" if md else "~"
    return (f"수입 실현율 범위({b['calc_note']}): {b['p10']}{t}{b['p90']}%(중앙값 {b['p50']}%). "
            f"{b['year_from']}{t}{b['year_to']}년 {b['n_routes']}개 노선 {b['basis']}. "
            f"{b['validation']}, 판정 강도 {b['strength']}.")


def reference_text(b: dict) -> str:
    """비교값: {라벨} {값}%({출처}, {기간}). 값은 후보 파일 models.M0.point."""
    return f"{b['ref_label']} {b['ref_value_pct']:.1f}%({b['ref_source']}, {b['ref_period']})"


def reference_row_label(b: dict) -> str:
    """실현율 시나리오 표 행 라벨 꼬리: ' (수입 {라벨} {기간}, {출처})'."""
    return f" (수입 {b['ref_label']} {b['ref_period']}, {b['ref_source']})"
