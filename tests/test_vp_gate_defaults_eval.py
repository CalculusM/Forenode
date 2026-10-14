# -*- coding: utf-8 -*-
"""research/vp_gate_defaults_eval_2026_10.py 지역 재구현의 자기 점검(엔진·골든 미변경).

실행: python -m unittest tests.test_vp_gate_defaults_eval
스터디 raw 파일이 없는 환경에서는 파일 의존 검사만 건너뛴다.
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -m unittest tests.xxx 실행 시 tests/ 미포함
import _helpers as H  # noqa: E402

_EVAL = os.path.join(H.ROOT, "research", "vp_gate_defaults_eval_2026_10.py")
_spec = importlib.util.spec_from_file_location("vp_gate_defaults_eval", _EVAL)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


class GrowthPathOptions(unittest.TestCase):
    def test_option_a_matches_engine_and_cap_cannot_lower_threshold(self):
        case = H.app_default_case()
        growth = H.APP_DEFAULT_INPUTS["growth_pct"] / 100
        out = ev.growth_path_options(case, growth, case["cap_limit"], H.APP_DEFAULT_INPUTS["operation_years"])
        self.assertLessEqual(out["A"]["parity_vs_engine"], 1.0)
        ref = out["A"]["traffic"]
        for k in "BC":
            self.assertIn(out[k]["status"], ("ok", "infeasible", "below_range"))
            if out[k]["traffic"] is not None:
                self.assertGreaterEqual(out[k]["traffic"], ref - 1)   # 성장을 자르면 문턱은 내려갈 수 없음


class FixPoint(unittest.TestCase):
    def test_default_case_converges_below_anchor_threshold(self):
        fp = ev.fixpoint({})
        self.assertTrue(fp["converged"])
        # 기본 사례는 권장 수요 앵커(한계 캡)가 문턱보다 높아 운영비가 과대, 고정점은 앵커 기준값 이하
        self.assertLessEqual(fp["T_fixpoint"], fp["T_anchor"] + 1)


class OpGrade(unittest.TestCase):
    def test_grade_keywords(self):
        self.assertEqual(ev._op_grade("운영 50년(국토부 공고 2026-957호)"), "1차·공고")
        self.assertEqual(ev._op_grade("운영 40년 가정(미보도)"), "가정")
        self.assertEqual(ev._op_grade("운영 40년(보도)"), "보도")
        self.assertEqual(ev._op_grade(""), "미기재")


@unittest.skipUnless(os.path.isdir(ev.STUDY_RAW), "스터디 raw 폴더 없음")
class StudyFiles(unittest.TestCase):
    def test_toll_default_groups_and_rule(self):
        r = ev.eval_toll_default()
        self.assertEqual(r["stats"]["고속도로형"]["A"]["n"], 6)
        self.assertEqual(r["stats"]["지하·소형차"]["A"]["n"], 3)
        self.assertTrue(r["chosen"] is None or r["chosen"] in r["passing"])

    def test_tunnel_rows_reproduce_recorded_thresholds(self):
        r = ev.eval_tunnel_cap()
        self.assertEqual(len({row["name"] for row in r["rows"]}), 4)
        self.assertTrue(all(row["parity_ok"] for row in r["rows"]))
        self.assertTrue(all(row["tunnel_true"] > row["tunnel_cap"] for row in r["rows"]))


if __name__ == "__main__":
    unittest.main()
