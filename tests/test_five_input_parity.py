# -*- coding: utf-8 -*-
"""5개 입력 재현 경로 패리티(2026-10 스터디 결함 P-01 회귀 방지).

스터디 실행기는 요금을 수입 계수에만 넣고 부트스트랩 앵커·운영비 시계열은 85원/km로 계산해
요금이 85원이 아닌 노선의 문턱이 앱 화면과 최대 36% 어긋났다. 이 테스트는
app_default_case(toll_per_km=...)가 사업 유형 기본 요금을 바꿔 호출한 경로(앱과 같은 순서)와
같은 문턱을 내는지, 요금 미지정 시 기존 기본값 경로가 그대로인지 본다.
"""
import unittest
import warnings

import _helpers as H

warnings.filterwarnings("ignore")
UNDERGROUND = dict(business_type="BTO", road_length=5.4, total_capex=7366, operation_years=40, toll_per_km=463)


def _via_default_path(**kw):
    """자동값 함수가 그 요금을 돌려주게 해 '요금 미지정' 경로로 호출. 오버라이드 경로와 같은 결과여야 요금이 앵커·운영비까지 같은 순서로 반영된 것."""
    import config_loader
    kw = dict(kw)
    toll = kw.pop("toll_per_km")
    orig = config_loader.default_toll_per_km
    config_loader.default_toll_per_km = lambda bt, length: toll
    try:
        return H.app_default_case(**kw)
    finally:
        config_loader.default_toll_per_km = orig


class FiveInputParity(unittest.TestCase):
    def test_default_toll_follows_config_mode(self):
        import config_loader
        case = H.app_default_case()
        self.assertEqual(case["toll_per_km"], config_loader.default_toll_per_km("BTO-a", 45))
        self.assertEqual(config_loader.load_finance_params()["toll_default"]["mode"], "fiscal_structure")
        self.assertEqual(config_loader.default_toll_per_km("BTL", 45), 80)   # 요금 없는 유형은 종전 폴백

    def test_toll_override_reaches_bootstrap_and_opex(self):
        a = H.app_default_case(**UNDERGROUND)
        b = _via_default_path(**UNDERGROUND)
        self.assertEqual(a["toll_per_km"], 463)
        self.assertEqual(a["daily_traffic"], b["daily_traffic"])
        self.assertEqual(a["rev_K"], b["rev_K"])
        self.assertEqual(float(a["base_params"]["annual_revenue_억"]), float(b["base_params"]["annual_revenue_억"]))
        ta, _ = H.threshold_traffic(a, "gov")
        tb, _ = H.threshold_traffic(b, "gov")
        self.assertAlmostEqual(ta, tb, delta=1.0)

    def test_heavy_ratio_override_reaches_revenue_coeff(self):
        import reverse_solver as rsv
        case = H.app_default_case(heavy_ratio_pct=0)
        self.assertEqual(case["rev_K"], rsv.traffic_revenue_coeff(45, case["toll_per_km"], 0.0, 1.5))


class AppUndergroundInputs(unittest.TestCase):
    """확장된 사이드바 범위(연장 소수·요금 463·중차량 0)가 화면에서 들어가고 재구성 사례와 일치(P-02)."""

    def test_sidebar_accepts_underground_route_and_matches_helper(self):
        import os
        from test_app_smoke import _exceptions, _run_app, _set_slider, assert_params_equal
        cwd = os.getcwd()
        os.chdir(H.ROOT)
        try:
            at = _run_app()
            [s for s in at.selectbox if s.label == "사업 유형 선택"][0].set_value("BTO")
            _set_slider(at, "연장(km)", 5.4)
            _set_slider(at, "민간투자비(억)", 7400)
            _set_slider(at, "운영기간(년)", 40)
            _set_slider(at, "화물비율(%)", 0)
            at.run()
            _set_slider(at, "통행료 km단가(원)", 463)   # 사업 유형 변경 재시드 뒤에 요금 입력(실사용 순서)
            at.run()
            self.assertEqual(_exceptions(at), [], "지하 노선 입력 실행 예외")
            expected = H.app_default_case(business_type="BTO", road_length=5.4, total_capex=7400,
                                          operation_years=40, heavy_ratio_pct=0, toll_per_km=463)
            assert_params_equal(self, at.session_state["fn_base_params"], expected["base_params"], "지하 노선")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
