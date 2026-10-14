# -*- coding: utf-8 -*-
"""⑥ 민감도 1.00배 기준선 = 메인 KPI 패리티.

민감도 탭은 fn_base_params(메인 KPI와 같은 전체 파라미터)를 BaseCase로 매핑해 run_scenario를 돈다.
배수 1.00·금리 가산 0에서 NPV·DSCR 최소·자기자본 IRR이 build_cashflow 메인 값과 같아야 한다.
"""
import math
import unittest

import _helpers as H
from _golden_case import GoldenCase


class SensitivityParity(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import app
        from scenario_engine import one_way_sensitivity, run_scenario
        from sensitivity_tab import _base_case_from_params
        cls.cases = {"case_default": H.app_default_case(),
                     "case_bridge_tunnel_0": H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0)}
        cls.app = app
        cls.run_scenario = staticmethod(run_scenario)
        cls.one_way = staticmethod(one_way_sensitivity)
        cls.to_base = staticmethod(_base_case_from_params)

    def _parity(self, name):
        case = self.cases[name]
        bp = case["base_params"]
        _cf, main = self.app.build_cashflow(**bp)
        base = self.to_base(bp, case["daily_traffic"], 45)
        res = self.run_scenario(base)
        for k in ("npv", "dscr_min", "equity_irr", "nominal_irr", "dscr_avg"):
            a, b = float(res[k]), float(main[k])
            if math.isnan(b):
                self.assertTrue(math.isnan(a), f"{name}.{k}")
            else:
                self.assertEqual(a, b, f"{name}.{k}: 민감도 {a!r} 대 메인 {b!r}")
        # 일방향 민감도 표의 1.00배 행도 같은 값
        for var in ("demand", "capex"):
            sdf = self.one_way(base, var, [0.9, 1.0, 1.1])
            row = sdf[sdf[var] == 1.0].iloc[0]
            self.assertEqual(float(row["npv"]), float(main["npv"]), f"{name} {var} 1.00배 NPV")
            self.assertEqual(float(row["dscr_min"]), float(main["dscr_min"]), f"{name} {var} 1.00배 DSCR")
        sdf = self.one_way(base, "rate", [0.0])
        self.assertEqual(float(sdf.iloc[0]["npv"]), float(main["npv"]), f"{name} 금리 0 NPV")
        # 메인 값 자체도 골든과 일치
        self.assertGolden(main["npv"], self.golden[name]["npv"], "money_억", f"{name}.npv")

    def test_default_case_parity(self):
        self._parity("case_default")

    def test_bridge_tunnel_zero_parity(self):
        self._parity("case_bridge_tunnel_0")


if __name__ == "__main__":
    unittest.main()
