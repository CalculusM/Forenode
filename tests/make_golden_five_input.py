# -*- coding: utf-8 -*-
"""5개 입력 사례 골든 생성기(P-09): tests/fixtures/five_input_cases_2026-10.json 6건을 앱 경로로 계산해
tests/golden_five_input.json에 고정한다.

실행: PYTHONIOENCODING=utf-8 python tests/make_golden_five_input.py
- 계산은 tests/_helpers.app_default_case(앱 화면과 같은 순서)로만 한다. 실행기 결과 JSON 값 복사 금지.
- 기준: 재무 성립선(gov)·DSCR 1.30·협약 평균 수익률(config_loader.covenant_return_rate)·픽스처 extra_criteria.
- 엔진 계산이 의도적으로 바뀐 경우에만 재생성하고(단독 커밋), 바뀐 항목과 사유를 커밋 메시지에 남긴다.
"""
import datetime
import json
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _helpers as H  # noqa: E402  (루트 경로 등록)

FIXTURE_PATH = os.path.join(HERE, "fixtures", "five_input_cases_2026-10.json")
GOLDEN_PATH = os.path.join(HERE, "golden_five_input.json")
OVERRIDE_KEYS = ("business_type", "road_length", "operation_years", "heavy_ratio_pct")


def load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def case_overrides(row: dict) -> dict:
    """픽스처 행을 app_default_case 인자로. 민간투자비는 확인값 > 차감 > 전국 비율 추정(threshold_display 공용 함수)."""
    import config_loader
    import threshold_display as thd
    ov = {k: row[k] for k in OVERRIDE_KEYS if row.get(k) is not None}
    if row.get("total_capex") is not None:
        ov["total_capex"] = row["total_capex"]
    else:
        ratio = config_loader.load_finance_params()["private_share_of_total_cost"]["value"]
        ov["total_capex"] = thd.resolve_private_capex(row["total_project_cost"], row.get("subsidy"), row.get("land"), ratio)[0]
    if row.get("toll_reported"):
        ov["toll_per_km"] = float(row["toll_reported"])
    return ov


def thresholds(row: dict) -> dict:
    import config_loader
    rate = config_loader.covenant_return_rate()[0]
    crit = [("gov", "gov", 0.0), ("dscr_1.30", "dscr", 1.30), (f"real_irr_{rate:g}", "real_irr", rate)]
    crit += [(f"{c}_{t}", c, t) for c, t in (row.get("extra_criteria") or [])]
    case = H.app_default_case(**case_overrides(row))
    out = {}
    for key, c, t in crit:
        traffic, seek = H.threshold_traffic(case, c, t)
        out[key] = {"traffic": None if traffic is None else float(traffic), "status": seek["status"]}
    return out


def _git_head() -> str:
    try:
        return subprocess.run(["git", "-C", H.ROOT, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def main():
    fx = load_fixture()
    golden = {
        "_meta": {
            "created": datetime.date.today().isoformat(),
            "generator": "tests/make_golden_five_input.py",
            "basis": "app 경로 app_default_case(toll_per_km·heavy_ratio_pct 오버라이드 포함). 실행기 결과 복사 아님",
            "engine_head": _git_head(),
            "fixture": os.path.relpath(FIXTURE_PATH, H.ROOT).replace(os.sep, "/"),
            "fixture_as_of": fx["_meta"]["as_of"],
            "fixture_version": fx["_meta"]["version"],
            "tolerance": "tests/golden_values.json _tolerance.traffic_대 재사용",
        },
        "cases": {row["name"]: {"inputs": case_overrides(row), "thresholds": thresholds(row)} for row in fx["cases"]},
    }
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2)
    print("생성:", GOLDEN_PATH)
    for name, c in golden["cases"].items():
        print(name, {k: v["traffic"] for k, v in c["thresholds"].items()})


if __name__ == "__main__":
    main()
