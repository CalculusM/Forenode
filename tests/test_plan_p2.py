# -*- coding: utf-8 -*-
"""앱 반영 방안 2차(P-07 민간투자비 환산, P-10·P-13 캡션, P-12 프리셋 데이터화, P-11c 앵커 config 단일화) 검증.
계산 경로 불변은 골든 테스트가 맡는다. 여기서는 config·데이터 파일 값과 화면 동작, 입력 파라미터 일치를 본다."""
import inspect
import logging
import os
import unittest
import warnings

import _helpers as H

warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)


class ConfigAssets(unittest.TestCase):
    def test_anchor_single_source(self):
        import config_loader
        import reverse_solver as rsv
        a = config_loader.demand_anchor()["traffic_realization_mean"]
        self.assertEqual(a, 0.814)
        self.assertEqual(H.TRAFFIC_ANCHOR_RATIO, a)
        ratios = inspect.signature(rsv.realization_scenarios).parameters["ratios"].default
        self.assertIn(a, ratios, "실현율 시나리오 기본 비율 목록에 앵커 행이 있어야 화면 '유력 시나리오'가 잡힌다")

    def test_presets_file_matches_fallback(self):
        import app
        import config_loader
        p = config_loader.project_presets()
        self.assertEqual(set(p), set(app._PRESET_FALLBACK))
        for name, vals in app._PRESET_FALLBACK.items():
            for k, v in vals.items():
                self.assertEqual(p[name][k], v, f"{name}.{k}")
            self.assertTrue(p[name]["basis"] and p[name]["as_of"] and p[name]["source"], name)
        self.assertIs(app.PROJECT_PRESETS, app.PROJECT_PRESETS)

    def test_resolve_private_capex(self):
        import threshold_display as thd
        self.assertEqual(thd.resolve_private_capex(37078, 7212, 8229, 0.594), (21637, "총사업비-건설보조금-보상비"))
        v, basis = thd.resolve_private_capex(21800, None, None, 0.594)
        self.assertEqual(v, 12949)
        self.assertIn("추정", basis)

    def test_koti_planning_returns(self):
        import config_loader
        k = config_loader.koti_planning_returns()          # 기본 = 손익공유형(BTO-a) 12건, BTO 1건(평택~시흥) 제외
        self.assertEqual(k["n"], 12)
        self.assertAlmostEqual(k["mean"], (2.852 * 13 - 4.59) / 12, places=2)
        self.assertEqual((k["min"], k["max"]), (2.41, 3.05))
        self.assertEqual(config_loader.koti_planning_returns(business_type="BTO")["n"], 1)
        self.assertIsNone(config_loader.koti_planning_returns(path=os.path.join(H.DATA, "없는파일.csv")))


class AppCapexConverter(unittest.TestCase):
    def test_apply_sets_capex_and_keeps_parity(self):
        from test_app_smoke import _exceptions, _run_app, assert_params_equal
        cwd = os.getcwd()
        os.chdir(H.ROOT)
        try:
            at = _run_app()
            at.number_input(key="cv_total").set_value(37078)
            at.checkbox(key="cv_known").set_value(True)
            at.run()
            at.number_input(key="cv_sub").set_value(7212)
            at.number_input(key="cv_land").set_value(8229)
            at.run()
            at.button(key="cv_apply").click()
            at.run()
            self.assertEqual(_exceptions(at), [], "환산 적용 실행 예외")
            self.assertEqual(at.session_state["_lk_total_capex"], 21637)
            self.assertEqual(at.session_state["capex_basis"], "총사업비-건설보조금-보상비")
            assert_params_equal(self, at.session_state["fn_base_params"],
                                H.app_default_case(total_capex=21637)["base_params"], "환산 적용")
            texts = [c.value for c in at.caption]
            self.assertTrue(any("민간투자비 근거" in t for t in texts))
            self.assertTrue(any("WACC" in t for t in texts), "재무 성립선 기준 수익률 캡션")
            self.assertTrue(any("차로 한계" in t for t in texts), "성장 경로 한계 도달 캡션")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
