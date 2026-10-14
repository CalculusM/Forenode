# -*- coding: utf-8 -*-
"""② reverse_solver 재무 성립선 문턱 교통량 골든 + 실현율 시나리오 5개 행(계산 경로 불변 증명용).

- 교량·터널 0% 조건: 재무 성립선 84,545대·DSCR 1.30 이상 106,939대·실질 세후 5.60% 113,021대
  (2026. 9. 28. 발송 초안 첨부 화면 수치와 동일 조건).
- 기본값 조건(교량 15%·터널 20%): 골든 고정값.
- 실현율 시나리오 기본 비율 (1.0, 0.9, 0.814, 0.7, 0.623)과 행별 지표: 수입 실현율 범위
  '표시' 반영(B안) 전후 동일해야 한다.
"""
import inspect
import unittest

import _helpers as H
from _golden_case import GoldenCase

PUBLISHED_BT0 = {"gov": 84545, "dscr_1.30": 106939, "real_irr_0.056": 113021}


class ThresholdGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cases = {"thresholds_default": H.app_default_case(),
                     "thresholds_bridge_tunnel_0": H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0)}
        cls.crit = {"gov": ("gov", 0.0), "dscr_1.30": ("dscr", 1.30), "real_irr_0.056": ("real_irr", 0.056)}

    def _check(self, name):
        for key, (crit, th) in self.crit.items():
            t, seek = H.threshold_traffic(self.cases[name], crit, th)
            g = self.golden[name][key]
            self.assertEqual(seek["status"], g["status"], f"{name}.{key} 상태")
            self.assertGolden(t, g["traffic"], "traffic_대", f"{name}.{key}")

    def test_default_thresholds(self):
        self._check("thresholds_default")

    def test_bridge_tunnel_zero_thresholds(self):
        self._check("thresholds_bridge_tunnel_0")

    def test_bridge_tunnel_zero_matches_published_figures(self):
        # 공개 수치(2026-09 첨부·신청서)는 통행료 85원/km 고정 조건에서 산출. 2026-10-14 자동값 변경 뒤에도 그 조건으로 재현
        import config_loader
        case = H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0,
                                  toll_per_km=config_loader.business_defaults()["BTO-a"]["toll"])
        for key, published in PUBLISHED_BT0.items():
            crit, th = self.crit[key]
            t, _seek = H.threshold_traffic(case, crit, th)
            self.assertEqual(round(t), published, f"{key}: {t:.1f}대, 공개 수치 {published}대")


class RealizationScenarioGolden(GoldenCase):
    def test_default_ratios_unchanged(self):
        import reverse_solver as rsv
        ratios = inspect.signature(rsv.realization_scenarios).parameters["ratios"].default
        self.assertEqual(tuple(ratios), (1.0, 0.9, 0.814, 0.7, 0.623))

    def test_rows_match_golden(self):
        import app
        import reverse_solver as rsv
        rows = rsv.realization_scenarios(H.app_default_case()["base_params"], app.build_cashflow)
        g_rows = self.golden["realization_scenarios_default"]
        self.assertEqual(len(rows), len(g_rows))
        for r, g in zip(rows, g_rows):
            lab = f"ratio {g['ratio']}"
            self.assertEqual(r["ratio"], g["ratio"])
            self.assertGolden(r["metrics"]["npv"], g["npv"], "money_억", lab + " npv")
            self.assertGolden(r["metrics"]["dscr_min"], g["dscr_min"], "ratio", lab + " dscr_min")
            self.assertGolden(r["metrics"]["equity_irr"], g["equity_irr"], "irr", lab + " equity_irr")
            self.assertEqual(r["first_profit_op_year"], g["first_profit_op_year"], lab + " 흑자 전환")
            self.assertEqual(r["payback_op_year"], g["payback_op_year"], lab + " 누적 회수")
            self.assertGolden(r["mrg_total"], g["mrg_total"], "money_억", lab + " MRG")
            self.assertEqual(bool(r["trigger"]), g["trigger"], lab + " 70% 미달 표시")


if __name__ == "__main__":
    unittest.main()
