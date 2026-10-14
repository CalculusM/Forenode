# -*- coding: utf-8 -*-
"""① build_cashflow 앱 기본값 사례 골든 + ⑤ MRG·MCC 기본 0 확인.

기본값 사례: 직접 입력·BTO-a·연장 45km·민간투자비 13,000억·통행료 85원/km·운영 30년·
건설 5년·예측치 미입력(문턱 역산 앵커, 4차로 한계 95,000대 캡). 교량·터널 0% 사례 병행.
"""
import inspect
import unittest

import numpy as np

import _helpers as H
from _golden_case import GoldenCase

KEYS_MONEY = ("npv", "annual_revenue_억", "opex_series_sum", "total_mrg_subsidy", "total_mcc_subsidy")
KEYS_RATIO = ("dscr_min", "bc_ratio", "opex_ratio", "discount_rate", "debt_rate")
KEYS_IRR = ("equity_irr", "nominal_irr", "real_irr")


class CashflowGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import app
        cls.app = app
        cls.cases = {"case_default": H.app_default_case(),
                     "case_bridge_tunnel_0": H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0)}

    def _check(self, name):
        case = self.cases[name]
        g = self.golden[name]
        bp = case["base_params"]
        _cf, m = self.app.build_cashflow(**bp)
        self.assertEqual(case["daily_traffic"], g["daily_traffic"], f"{name} 기준 교통량")
        self.assertEqual(case["anchor_capped"], g["anchor_capped"], f"{name} 용량 캡 여부")
        actual = dict(m)
        actual.update({"annual_revenue_억": bp["annual_revenue_억"], "opex_ratio": bp["opex_ratio"],
                       "opex_series_sum": float(np.sum(bp["opex_series_억"])),
                       "discount_rate": bp["discount_rate"], "debt_rate": bp["debt_rate"]})
        for k in KEYS_MONEY:
            self.assertGolden(actual[k], g[k], "money_억", f"{name}.{k}")
        for k in KEYS_RATIO:
            self.assertGolden(actual[k], g[k], "ratio", f"{name}.{k}")
        for k in KEYS_IRR:
            self.assertGolden(actual[k], g[k], "irr", f"{name}.{k}")

    def test_default_case(self):
        self._check("case_default")

    def test_bridge_tunnel_zero_case(self):
        self._check("case_bridge_tunnel_0")

    def test_default_inputs_match_app_defaults(self):
        bp = self.cases["case_default"]["base_params"]
        self.assertEqual(bp["capex_억"], 13000)
        self.assertEqual(bp["business_type"], "BTO-a")
        self.assertEqual(bp["operation_years"], 30)
        import config_loader
        self.assertEqual(self.cases["case_default"]["toll_per_km"], config_loader.default_toll_per_km("BTO-a", 45))   # 2026-10-14 재정요금 구조 자동값


class MrgMccDefaultZero(unittest.TestCase):
    """⑤ MRG·MCC 기본 0: 폐지 제도라 신규 사업 기본값은 0(레거시 재현 전용)."""

    def test_config_defaults_zero_except_btl(self):
        import config_loader
        bd = config_loader.business_defaults()
        for bt in ("BTO", "BTO-rs", "BTO-a", "BTO+BTL"):
            self.assertEqual(bd[bt]["mrg"], 0, f"{bt} MRG 기본")
            self.assertEqual(bd[bt]["mcc"], 0, f"{bt} MCC 기본")

    def test_build_cashflow_signature_defaults_zero(self):
        import app
        sig = inspect.signature(app.build_cashflow)
        self.assertEqual(sig.parameters["mrg_ratio"].default, 0.0)
        self.assertEqual(sig.parameters["mcc_ratio"].default, 0.0)

    def test_default_case_no_subsidy(self):
        import app
        bp = H.app_default_case()["base_params"]
        self.assertEqual(bp["mrg_ratio"], 0.0)
        self.assertEqual(bp["mcc_ratio"], 0.0)
        _cf, m = app.build_cashflow(**bp)
        self.assertEqual(float(m["total_mrg_subsidy"]), 0.0)
        self.assertEqual(float(m["total_mcc_subsidy"]), 0.0)
        self.assertEqual(float(m["total_govt_burden"]), 0.0)


if __name__ == "__main__":
    unittest.main()
