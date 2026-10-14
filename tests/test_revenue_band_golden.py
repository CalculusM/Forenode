# -*- coding: utf-8 -*-
"""④ 수입 실현율 범위 재현: 하위 10% 49.0%·중앙값 73.0%·상위 10% 98.8% (M2 분해형, 결정론 적분).

- 무거운 노선 군집 재표본(4,000회)은 재실행하지 않는다. 결정론 부분(전 표본 적합·주 분석
  노선 분리 교차검증)만 재계산하고, 재표본 결과는 저장 산출물(후보 JSON·관측별 채점 CSV)과 대조.
- 스냅샷 정합: 후보 JSON의 panel_version·입력 4종 sha256이 현 데이터 파일과 일치해야 한다.
"""
import csv
import hashlib
import json
import os
import sys
import unittest

import _helpers as H
from _golden_case import GoldenCase

sys.path.insert(0, os.path.join(H.ROOT, "research"))
CAND = os.path.join(H.DATA, "revenue_band_candidate_2026-09.json")
LOO_CSV = os.path.join(H.DATA, "revenue_band_loo_scores_2026-09.csv")


def eol_agnostic_sha256(raw: bytes) -> set:
    """원본·CRLF·LF 세 가지 줄바꿈 표현의 sha256 집합.

    후보 JSON의 입력 sha256은 Windows 작업 트리(CRLF)에서 기록됐다. 저장소 색인은 LF라
    LF로 체크아웃하는 환경(배포 서버 등)에서도 같은 내용이면 일치로 본다.
    """
    lf = raw.replace(b"\r\n", b"\n")
    return {hashlib.sha256(x).hexdigest() for x in (raw, lf, lf.replace(b"\n", b"\r\n"))}


class RevenueBandGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import revenue_band_2026_09 as rb
        cls.rb = rb
        cls.rev, cls.versions = rb.load_revenue()
        cls.traffic = rb.load_traffic()
        cls.toll = rb.load_toll()
        with open(CAND, encoding="utf-8") as f:
            cls.cand = json.load(f)

    def test_full_sample_band_49_73_98_8(self):
        g = self.golden["revenue_band"]
        full = self.rb.fit_m2([v for _, _, v in self.traffic], [e for _, _, e, _ in self.toll], None, 0)
        p10, p50, p90 = full["band"]
        self.assertGolden(p10, g["P10"], "band_fraction", "P10")
        self.assertGolden(p50, g["P50"], "band_fraction", "P50")
        self.assertGolden(p90, g["P90"], "band_fraction", "P90")
        self.assertEqual((round(100 * p10, 1), round(100 * p50, 1), round(100 * p90, 1)), (49.0, 73.0, 98.8))

    def test_candidate_json_matches_recomputation(self):
        b = self.cand["band_full_sample"]
        g = self.golden["revenue_band"]
        self.assertEqual((b["P10_pct"], b["P50_pct"], b["P90_pct"]), (49.0, 73.0, 98.8))
        for k in ("P10", "P50", "P90"):
            self.assertGolden(b[k], g[k], "band_fraction", f"JSON {k}")
            lo, hi = b["bootstrap_ci95"][k]
            self.assertTrue(lo <= b[k] <= hi, f"{k} 재표본 신뢰구간 안 점추정")

    def test_snapshot_integrity(self):
        self.assertEqual(self.cand["panel_version"], "v1_2026-07-31")
        self.assertEqual(self.versions, ["v1_2026-07-31"])
        self.assertEqual(self.cand["verdict"], "작동")
        self.assertEqual(self.cand["adopted_model"], "M2")
        self.assertFalse(self.cand["engine_reflected"])
        import csv
        with open(os.path.join(H.DATA, "route_meta.csv"), encoding="utf-8-sig") as f:
            meta_routes = {r["노선"] for r in csv.DictReader(f)}
        for rel, sha in self.cand["inputs_sha256"].items():
            if rel == "data/route_meta.csv":
                # 원장 정정 5건(45b24e1, 2026-10-05)으로 파일 해시 변경(6fc79f53에서 941b6ee0). 범위 산출은 이 파일을
                # 노선명 집합에만 쓰므로(research/revenue_band_2026_09.py) 해시 대조 대신 후보 노선의 집합 포함으로 대체
                self.assertTrue(set(self.cand["data_summary"]["year_means_complete_routes"]["routes"]) <= meta_routes,
                                "후보 노선이 route_meta 노선 집합 밖")
                continue
            with open(os.path.join(H.ROOT, rel), "rb") as f:
                self.assertIn(sha, eol_agnostic_sha256(f.read()), f"{rel} sha256")

    def test_loo_main_analysis(self):
        g = self.golden["revenue_band"]["loo_main"]
        rev = self.rev
        all_routes = sorted({r[0] for r in rev})
        ri = {r: i for i, r in enumerate(all_routes)}
        routes, per_route, rows, _fp = self.rb.run_sample(
            0, "주분석", self.rb.SAMPLES["주분석"], rev, self.traffic, self.toll, ri)
        self.assertEqual(len(routes), 17)
        for m in ("M0", "M2"):
            hits = sum(per_route[m][r][0] for r in routes)
            n = sum(per_route[m][r][1] for r in routes)
            self.assertEqual((hits, n), (g[m]["hits"], g[m]["n"]), f"{m} 적중")
            ae = sum(per_route[m][r][4] for r in routes) / n
            self.assertGolden(ae, g[m]["MAE_center"], "score_mean", f"{m} MAE")
            jm = self.cand["loo_results"]["주분석"]["by_model"][m]
            self.assertGolden(ae, jm["MAE_center"], "score_mean", f"{m} MAE 대 JSON")
            self.assertGolden(hits / n, jm["coverage"], "score_mean", f"{m} 포함률 대 JSON")
        self.assertEqual(g["M2"]["hits"], 61)     # 78건 중 61건 = 78.2%
        # 저장 관측별 채점 CSV(소수 4자리)와 재계산 구간 대조
        saved = {}
        with open(LOO_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["표본"] == "주분석" and r["모형"] == "M2":
                    saved[(r["노선"], int(r["연도"]))] = r
        mine = [r for r in rows if r["모형"] == "M2"]
        self.assertEqual(len(mine), len(saved))
        for r in mine:
            s = saved[(r["노선"], r["연도"])]
            self.assertAlmostEqual(r["구간L"], float(s["구간L"]), places=4)
            self.assertAlmostEqual(r["구간U"], float(s["구간U"]), places=4)
            self.assertEqual(r["적중"], int(s["적중"]))


if __name__ == "__main__":
    unittest.main()
