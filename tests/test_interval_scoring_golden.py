# -*- coding: utf-8 -*-
"""③ interval_scoring 전체 채점: 관측 98건 중 70건 범위 적중, 최근 3개년 40건 중 32건.

산출 CSV는 임시 폴더에 쓴다(data/ 산출 파일 불변).
"""
import os
import tempfile
import unittest

import _helpers as H  # noqa: F401  (루트 경로 등록)
from _golden_case import GoldenCase


class IntervalScoringGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import interval_scoring as isc
        with tempfile.TemporaryDirectory() as td:
            cls.full = isc.run_full(out_path=os.path.join(td, "full.csv"))
            cls.r62 = isc.run(out_path=os.path.join(td, "v1.csv"))

    def test_full_98_70(self):
        g = self.golden["interval_scoring"]["full"]
        rows = self.full["rows"]
        self.assertEqual(len(rows), 98)
        self.assertEqual(sum(x["적중"] for x in rows), 70)
        self.assertEqual(self.full["all"]["n"], g["n"])
        self.assertGolden(self.full["all"]["coverage"], g["coverage"], "score_mean", "coverage")
        self.assertGolden(self.full["all"]["mean_width"], g["mean_width"], "score_mean", "mean_width")
        self.assertGolden(self.full["all"]["mean_IS"], g["mean_IS"], "score_mean", "mean_IS")
        self.assertAlmostEqual(70 / 98 / 0.80, 0.892857, places=5)   # 80% 목표 대비 비율 산식 확인

    def test_recent_three_years_40_32(self):
        recent = [x for x in self.full["rows"] if str(x["연도"]) in ("2022", "2023", "2024")]
        self.assertEqual(len(recent), 40)
        self.assertEqual(sum(x["적중"] for x in recent), 32)

    def test_traffic_band_62(self):
        g = self.golden["interval_scoring"]["traffic_62"]
        a = self.r62["all62"]
        self.assertEqual(a["n"], 62)
        for k in ("coverage", "mean_width", "mean_IS"):
            self.assertGolden(a[k], g[k], "score_mean", f"traffic_62.{k}")


if __name__ == "__main__":
    unittest.main()
