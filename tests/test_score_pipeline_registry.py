# -*- coding: utf-8 -*-
"""REG-2026-003 채점 실행기(research/score_pipeline_registry.py) 회귀: 빈 원장 예외 0, 참고 교통량 S-A 비율 재현."""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
import score_pipeline_registry as S  # noqa: E402

STUB_GOV = 80115   # 시험 픽스처: 스터디 04_five_input_results.json 성남~서초 재무 성립선 문턱(요금 기본값)
STUB = {"meta": {"registry_id": "REG-2026-003", "registry_version": "v1", "sealed_at": "stub", "engine_commit": "0000000",
                 "golden_sha256": "00000000", "panel_version": "stub", "constants_used": {"private_share_of_total_cost": 0.5}},
        "routes": [{"노선": "성남~서초", "reference": {"요금_조건": "기본", "문턱_재무성립선": STUB_GOV, "통행료_원km": 85.0,
                                                  "민간투자비_억": 1, "총사업비_억": 1, "구간": "B"}}]}


class ScorePipelineRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = os.path.join(self.tmp.name, "reg.json")
        with open(self.reg, "w", encoding="utf-8") as f:
            json.dump(STUB, f, ensure_ascii=False)
        self.outcomes = os.path.join(self.tmp.name, "outcomes.csv")
        self.scores = os.path.join(self.tmp.name, "pipeline_registry_scores_2026-12-31.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_outcomes(self, rows):
        with open(self.outcomes, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=S.OUTCOME_COLS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    def _run(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            S.main(["--date", "2026-12-31", "--registry", self.reg, "--outcomes", self.outcomes, "--out-dir", self.tmp.name])
        return buf.getvalue()

    def test_empty_outcomes_no_exception(self):
        self._write_outcomes([])
        out = self._run()
        self.assertIn("채점 가능 0건", out)
        self.assertIn("## R-002", out)
        self.assertTrue(os.path.exists(self.scores))

    def test_reference_traffic_ratio_is_proxy(self):
        self._write_outcomes([{"노선": "성남~서초", "결과종류": "참고", "값": "48000", "공개일": "2026-06",
                               "출처": "전략환경영향평가 요약문 분산 교통량", "출처등급": "1차", "비고": "시험"}])
        out = self._run()
        with open(self.scores, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["비율"]), 0.60, delta=0.01)
        self.assertEqual(rows[0]["대용축"], "Y")
        self.assertEqual(rows[0]["S-B_정합"], "채점 불가")
        self.assertIn("채점 가능 1건", out)


if __name__ == "__main__":
    unittest.main()
