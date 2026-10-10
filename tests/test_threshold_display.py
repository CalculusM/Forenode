# -*- coding: utf-8 -*-
"""사업성 문턱 표시 공용 함수·요금 구조 config·KOTI 수익률 데이터 로더 검증(2026-10 스터디 반영).

계산 경로 불변은 골든 테스트가 맡는다. 여기서는 표시 함수의 값, config 키 존재,
0.056 기준 수익률이 데이터 파일에서 비트 동일하게 읽히는지, 금지 표현 부재를 본다.
"""
import csv
import os
import unittest

import _helpers as H

FORBIDDEN = (chr(0x2014), chr(0x2192), "유일", "예측 시점 이후")   # 줄표·화살표
OLD_LABEL = "협약 평균 수익률 (실질·세후 5.60%, 운영 중 23개)"
CSV = os.path.join(H.DATA, "koti_rr2510_return_rates.csv")


class ThresholdDisplay(unittest.TestCase):
    def setUp(self):
        import threshold_display as thd
        self.thd = thd

    def test_required_toll_at_capacity(self):
        self.assertEqual(self.thd.required_toll_at_capacity(79.7, 104778, 95000), 88)
        self.assertEqual(self.thd.required_toll_at_capacity(80.2, 207117, 95000), 175)

    def test_fiscal_toll_per_km(self):
        for L, want in ((32, 79.7), (15.4, 113.0), (9.6, 151.9), (5.4, 232.1)):
            self.assertEqual(self.thd.fiscal_toll_per_km(L, 900, 44.3, 1.1), want, L)

    def test_condition_sentence(self):
        s = self.thd.condition_core(48207, 95000, 4)
        self.assertIn("48,207대", s)
        self.assertIn("1.97배", s)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, s)
            self.assertNotIn(bad, self.thd.NOTICE)
        self.assertNotIn("**", self.thd.condition_core(48207, 95000, 4, bold=False))


class FinanceConfig(unittest.TestCase):
    def test_fiscal_toll_structure_and_input_max(self):
        import config_loader
        fp = config_loader.load_finance_params()
        fts = fp["fiscal_toll_structure"]
        for k in ("base_won", "per_km_won_class1", "short_route_warn_km", "as_of", "source"):
            self.assertIn(k, fts)
        tb = fp["toll_benchmark"]
        self.assertGreaterEqual(tb["input_max_won_per_km"], tb["observed_proposal_toll_won_per_km"]["max"])


class KotiReturnRates(unittest.TestCase):
    def test_covenant_rate_bit_identical_to_legacy_literal(self):
        import config_loader
        rate, label = config_loader.covenant_return_rate()
        self.assertEqual(rate, 0.056)
        self.assertEqual(label, OLD_LABEL)

    def test_fallback_when_file_missing(self):
        import config_loader
        rate, label = config_loader.covenant_return_rate(path=os.path.join(H.DATA, "없는파일.csv"))
        self.assertEqual((rate, label), (0.056, OLD_LABEL))

    def test_table22_recomputes_to_report_means(self):
        with open(CSV, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        t22 = [r for r in rows if r["출처표"] == "표2-2" and r["행유형"] == "원표행"]
        self.assertEqual(len(t22), 13)
        self.assertAlmostEqual(sum(float(r["수익률_pct"]) for r in t22) / 13, 2.852, places=3)
        self.assertAlmostEqual(sum(float(r["연장_km"]) for r in t22) / 13, 33.86, places=2)
        self.assertEqual(sum(int(r["투자비계_억"]) for r in t22), 212445)
        nego = [r for r in rows if r["출처표"] == "표2-3" and r["행유형"] == "서술평균" and r["단계"] == "협상"]
        self.assertEqual(nego[0]["재현검사"], "불일치")


if __name__ == "__main__":
    unittest.main()
