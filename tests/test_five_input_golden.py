# -*- coding: utf-8 -*-
"""5개 입력 사례 골든 회귀(P-09): 픽스처 6건의 기준별 문턱이 tests/golden_five_input.json과 일치하는지,
일괄 실행기(research/threshold_batch_2026_10.py)가 우면~용산 사례에서 앱 경로(_helpers)와 같은 문턱을 내는지 본다.

실행: python -m unittest tests.test_five_input_golden
허용 오차는 tests/golden_values.json의 _tolerance.traffic_대(GoldenCase)만 쓴다.
"""
import json
import os
import sys
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _helpers as H  # noqa: E402
import make_golden_five_input as mg  # noqa: E402
from _golden_case import GoldenCase  # noqa: E402

warnings.filterwarnings("ignore")
PARITY_CASE = "우면~용산 지하도로"


class FiveInputGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = mg.load_fixture()["cases"]
        with open(mg.GOLDEN_PATH, encoding="utf-8") as f:
            cls.five = json.load(f)

    def test_fixture_and_golden_cover_six_cases(self):
        self.assertEqual(len(self.rows), 6)
        self.assertEqual(set(self.five["cases"]), {r["name"] for r in self.rows})

    def test_thresholds_match_golden(self):
        for row in self.rows:
            got = mg.thresholds(row)
            exp = self.five["cases"][row["name"]]["thresholds"]
            self.assertEqual(set(got), set(exp), row["name"])
            for key in exp:
                self.assertEqual(got[key]["status"], exp[key]["status"], f'{row["name"]} {key}')
                self.assertGolden(got[key]["traffic"], exp[key]["traffic"], "traffic_대", f'{row["name"]} {key}')

    def test_batch_runner_matches_helper_path(self):
        """실행기 경로 == 앱 경로(P-01 요금 주입 패리티 회귀 방지). 실행기는 정수 반올림이라 traffic_대 오차 적용."""
        sys.path.insert(0, os.path.join(H.ROOT, "research"))
        import threshold_batch_2026_10 as tb
        row = next(r for r in self.rows if r["name"] == PARITY_CASE)
        out = tb.run_one(tb.scenario_case(row, "reported"))
        self.assertNotIn("error", out)
        self.assertEqual(out["inputs"]["toll_per_km"], float(row["toll_reported"]))
        self.assertEqual(out["inputs"]["heavy_ratio_pct"], row["heavy_ratio_pct"])
        helper = mg.thresholds(row)
        self.assertEqual(set(out["thresholds"]), set(helper))
        for key, v in helper.items():
            self.assertGolden(out["thresholds"][key]["traffic"], v["traffic"], "traffic_대", f"runner {key}")


if __name__ == "__main__":
    unittest.main()
