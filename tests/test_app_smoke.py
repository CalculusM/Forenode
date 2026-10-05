# -*- coding: utf-8 -*-
"""화면 실행 무예외 + 화면 기본 입력과 테스트 재구성(_helpers.app_default_case) 일치.

streamlit.testing AppTest로 app.py와 pages 4개를 실제 실행한다(브라우저 불필요).
- app.py 기본 실행·교량/터널 0% 실행·예측치 입력 실행: 예외 0건.
- fn_base_params(메인 KPI 계산 파라미터)가 재구성 사례와 같아야 골든 테스트가 화면 값을 대변한다.
"""
import glob
import logging
import os
import unittest
import warnings

import numpy as np

import _helpers as H

warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)
TIMEOUT = 300


def _run_app(setup=None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(H.ROOT, "app.py"), default_timeout=TIMEOUT)
    at.run()
    if setup is not None:
        setup(at)
        at.run()
    return at


def _set_slider(at, label, value):
    hits = [s for s in at.slider if s.label == label]
    if len(hits) != 1:
        raise AssertionError(f"슬라이더 '{label}' {len(hits)}개")
    hits[0].set_value(value)


def _exceptions(at):
    return [getattr(e, "value", str(e)) for e in at.exception]


class _CwdRoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(H.ROOT)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)


def assert_params_equal(tc, actual, expected, label):
    tc.assertEqual(set(actual), set(expected), f"{label} 키 집합")
    for k, v in expected.items():
        a = actual[k]
        if isinstance(v, np.ndarray):
            tc.assertTrue(np.array_equal(np.asarray(a, float), v), f"{label}.{k} 시계열")
        elif isinstance(v, float):
            tc.assertAlmostEqual(float(a), v, places=12, msg=f"{label}.{k}")
        else:
            tc.assertEqual(a, v, f"{label}.{k}")


class AppDefaultParity(_CwdRoot):
    def test_default_run_no_exception_and_params_parity(self):
        at = _run_app()
        self.assertEqual(_exceptions(at), [], "app.py 기본 실행 예외")
        assert_params_equal(self, at.session_state["fn_base_params"],
                            H.app_default_case()["base_params"], "기본값")

    def test_bridge_tunnel_zero_params_parity(self):
        def setup(at):
            _set_slider(at, "교량 비율(%)", 0)
            _set_slider(at, "터널 비율(%)", 0)
        at = _run_app(setup)
        self.assertEqual(_exceptions(at), [], "app.py 교량·터널 0% 실행 예외")
        assert_params_equal(self, at.session_state["fn_base_params"],
                            H.app_default_case(bridge_ratio=0.0, tunnel_ratio=0.0)["base_params"],
                            "교량·터널 0%")

    def test_forecast_input_run_no_exception(self):
        def setup(at):
            at.toggle(key="have_traffic_forecast").set_value(True)
        at = _run_app(setup)
        self.assertEqual(_exceptions(at), [], "app.py 예측치 입력 실행 예외")
        self.assertTrue(at.session_state["have_traffic_forecast"])


class PagesSmoke(_CwdRoot):
    """pages 4개: 실제 사용과 같은 다중 페이지 맥락(app.py에서 switch_page)으로 실행.

    페이지 파일을 단독 실행하면 st.page_link가 다중 페이지 등록 정보를 못 찾아
    하네스 전용 KeyError('url_pathname')가 난다(실서비스 경로 아님).
    """

    def test_pages_no_exception(self):
        from streamlit.testing.v1 import AppTest
        pages = sorted(glob.glob(os.path.join(H.ROOT, "pages", "*.py")))
        self.assertEqual(len(pages), 4, pages)
        for p in pages:
            at = AppTest.from_file(os.path.join(H.ROOT, "app.py"), default_timeout=TIMEOUT)
            at.switch_page(os.path.relpath(p, H.ROOT))
            at.run()
            self.assertEqual(_exceptions(at), [], f"{os.path.basename(p)} 예외")
            self.assertGreaterEqual(len(at.title), 1, f"{os.path.basename(p)} 제목 미표시")


if __name__ == "__main__":
    unittest.main()
