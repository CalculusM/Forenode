# -*- coding: utf-8 -*-
"""수입 실현율 범위 표시(VP 게이트 B안) 검증: 판정 기준 B2·B3·B4·B6 + 화면·한 장 요약 반영.

B1(계산 불변)은 골든 테스트 전체(test_*_golden·test_sensitivity_parity·test_app_smoke 파라미터 일치)가,
B5(무예외)는 test_app_smoke가 맡는다. 기준 원문: research/vp_gate_revenue_band_criteria_2026-10.md
"""
import copy
import io
import json
import logging
import os
import tempfile
import unittest
import warnings

import _helpers as H

warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

GATE = os.path.join(H.DATA, "revenue_band_gate_2026-10.json")
CAND = os.path.join(H.DATA, "revenue_band_candidate_2026-09.json")
FORBIDDEN = (chr(0x2014), chr(0x2192), "예측 시점 이후", "노선 유형 불문", "유일", "최초")   # 줄표·화살표
REQUIRED_EVERY = ("판정 강도 약함", "2021~2025년", "17개 노선", "징수 통행료 기준")
REQUIRED_DETAIL = ("노선 분리 검증(시점 분리 아님)", "계산 미반영")
REQUIRED_REFERENCE = ("KOTI RR-25-10", "2014~2024년")
# 현 스냅샷(revband_cand_2026-09-28)의 기대 문구. 후보 파일이 바뀌면 이 값도 의도적으로 갱신
EXPECT_SHORT = "수입 실현율 범위 49~99%(중앙값 73%, 2021~2025년 17개 노선 징수 통행료 기준, 판정 강도 약함)"
EXPECT_DETAIL = ("수입 실현율 범위(표시 전용, 계산 미반영): 49~99%(중앙값 73%). "
                 "2021~2025년 17개 노선 징수 통행료 기준. 노선 분리 검증(시점 분리 아님), 판정 강도 약함.")
EXPECT_REF = "10년 평균 62.3%(KOTI RR-25-10 p.45, 2014~2024년)"
LEGACY_ANCHOR = "수입 실현율 패널 평균 71.2%"


def _texts(rbd, b):
    return {"short": rbd.band_short(b), "detail": rbd.band_detail(b),
            "ref": rbd.reference_text(b), "row": rbd.reference_row_label(b)}


class DisplayModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import revenue_band_display as rbd
        cls.rbd = rbd
        cls.b = rbd.load_band()
        with open(CAND, encoding="utf-8") as f:
            cls.cand = json.load(f)
        with open(GATE, encoding="utf-8") as f:
            cls.gate = json.load(f)

    def test_band_loaded_from_candidate(self):            # B2
        self.assertIsNotNone(self.b, "범위 로드 실패(스냅샷 불일치 또는 파일 결손)")
        bf = self.cand["band_full_sample"]
        self.assertEqual(self.b["p10_pct"], bf["P10_pct"])
        self.assertEqual(self.b["p50_pct"], bf["P50_pct"])
        self.assertEqual(self.b["p90_pct"], bf["P90_pct"])
        self.assertEqual((self.b["p10"], self.b["p50"], self.b["p90"]), (49, 73, 99))
        self.assertEqual(self.b["n_routes"], self.cand["data_summary"]["n_routes"])
        self.assertEqual((self.b["year_from"], self.b["year_to"]), (2021, 2025))
        self.assertEqual(self.b["panel_version"], "v1_2026-07-31")

    def test_texts_exact(self):                            # B2·B3
        t = _texts(self.rbd, self.b)
        self.assertEqual(t["short"], EXPECT_SHORT)
        self.assertEqual(t["detail"], EXPECT_DETAIL)
        self.assertEqual(t["ref"], EXPECT_REF)

    def test_required_phrases(self):                       # B3
        t = _texts(self.rbd, self.b)
        for k in ("short", "detail"):
            for p in REQUIRED_EVERY:
                self.assertIn(p, t[k], f"{k}: '{p}' 누락")
        for p in REQUIRED_DETAIL:
            self.assertIn(p, t["detail"], f"detail: '{p}' 누락")
        for k in ("ref", "row"):
            for p in REQUIRED_REFERENCE:
                self.assertIn(p, t[k], f"{k}: '{p}' 누락")

    def test_forbidden_expressions(self):                  # B4
        t = _texts(self.rbd, self.b)
        with open(os.path.join(H.ROOT, "revenue_band_display.py"), encoding="utf-8") as f:
            src = f.read()
        with open(GATE, encoding="utf-8") as f:
            gate_txt = f.read()
        for name, s in list(t.items()) + [("module", src), ("gate", gate_txt)]:
            for bad in FORBIDDEN:
                self.assertNotIn(bad, s, f"{name}: 금지 표현 '{bad}'")

    def test_no_band_literals_in_code(self):               # B2 하드코딩 금지
        for fn in ("app.py", "revenue_band_display.py"):
            with open(os.path.join(H.ROOT, fn), encoding="utf-8") as f:
                src = f.read()
            for lit in ("49~99", "중앙값 73", "98.8", "0.7300", "0.4896", "0.9884"):
                self.assertNotIn(lit, src, f"{fn}: 범위 수치 '{lit}' 코드 내 고정")

    def test_reference_equals_calc_anchor(self):
        """표시 비교값(후보 파일 M0)과 실현율 시나리오 계산 앵커(reverse_solver)가 같은 값."""
        import inspect

        import reverse_solver as rsv
        ratios = inspect.signature(rsv.realization_scenarios).parameters["ratios"].default
        self.assertEqual(self.b["ref_value_ratio"], ratios[-1])

    def test_gate_file_consistency(self):
        self.assertEqual(self.gate["display_option"], "B")
        self.assertFalse(self.gate["engine_reflected"])
        self.assertEqual(self.gate["candidate_tag"], self.cand["candidate_tag"])
        self.assertEqual(self.gate["panel_version"], self.cand["panel_version"])
        self.assertEqual(self.rbd._sha256_lf(CAND), self.gate["candidate_sha256_lf"])

    # ── B6 안전 폴백 ──
    def _with_gate(self, mutate):
        g = copy.deepcopy(self.gate)
        mutate(g)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "gate.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False)
            return self.rbd.load_band(gate_path=p)

    def test_fallback_missing_gate(self):
        self.assertIsNone(self.rbd.load_band(gate_path=os.path.join(H.DATA, "없는_파일.json")))

    def test_fallback_snapshot_mismatch(self):
        self.assertIsNone(self._with_gate(lambda g: g.update(candidate_sha256_lf="0" * 64)))
        self.assertIsNone(self._with_gate(lambda g: g.update(candidate_tag="other")))
        self.assertIsNone(self._with_gate(lambda g: g.update(panel_version="v0")))
        self.assertIsNone(self._with_gate(lambda g: g.update(display_option="A")))
        self.assertIsNone(self._with_gate(lambda g: g.update(candidate_file="data/없음.json")))

    def test_fallback_corrupt_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "gate.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{ 손상")
            self.assertIsNone(self.rbd.load_band(gate_path=p))

    def test_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = os.path.join(td, "a"), os.path.join(td, "b")
            with open(a, "wb") as f:
                f.write(b'{"x": 1,\r\n "y": 2}\r\n')
            with open(b, "wb") as f:
                f.write(b'{"x": 1,\n "y": 2}\n')
            self.assertEqual(self.rbd._sha256_lf(a), self.rbd._sha256_lf(b))


class _CwdRoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(H.ROOT)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)


def _app():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(os.path.join(H.ROOT, "app.py"), default_timeout=300)


def _captions(at):
    return [c.value for c in at.caption]


class DisplayInApp(_CwdRoot):
    def test_default_screen(self):
        at = _app()
        at.run()
        self.assertEqual([getattr(e, "value", str(e)) for e in at.exception], [])
        caps = _captions(at)
        anchor = [c for c in caps if c.startswith("권장 수요 앵커") or c.startswith("권장선 앵커")]
        self.assertGreaterEqual(len(anchor), 2, anchor)
        for c in anchor:
            self.assertIn(EXPECT_SHORT, c)
            self.assertNotIn(LEGACY_ANCHOR, c)
        self.assertIn(EXPECT_DETAIL, caps)
        scen = [c for c in caps if c.startswith("협약(입력) 교통량 고정")]
        self.assertEqual(len(scen), 1)
        self.assertIn(EXPECT_REF, scen[0])
        self.assertFalse(any("다음 데이터 작업(✚)" in c for c in caps), "구 문구 잔존")
        labels = [v for d in at.dataframe if "실현율" in d.value.columns for v in d.value["실현율"]]
        self.assertIn("62% (수입 10년 평균 2014~2024년, KOTI RR-25-10 p.45)", labels)
        for c in caps:                                      # B4: 화면 수입 실현율 문구 전체
            if "수입 실현율" in c:
                for bad in FORBIDDEN:
                    self.assertNotIn(bad, c, f"금지 표현 '{bad}': {c}")

    def test_forecast_screen(self):
        at = _app()
        at.run()
        at.toggle(key="have_traffic_forecast").set_value(True)
        at.run()
        self.assertEqual([getattr(e, "value", str(e)) for e in at.exception], [])
        prior = [c for c in _captions(at) if c.startswith("ⓘ prior는")]
        self.assertEqual(len(prior), 1, prior)
        self.assertIn(EXPECT_SHORT, prior[0])
        self.assertIn("비교값: 수입 " + EXPECT_REF, prior[0])

    def test_onepager_pdf_sources(self):
        at = _app()
        at.run()
        at.button(key="onepager_btn").click()
        at.run()
        self.assertEqual([getattr(e, "value", str(e)) for e in at.exception], [])
        self.assertFalse(any("한 장 요약 생성 실패" in w.value for w in at.warning))
        pdf = at.session_state["onepager_bytes"]
        self.assertGreater(len(pdf), 1000)
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf 미설치: PDF 본문 대조 생략(생성 무예외만 확인)")
        text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
        compact = "".join(text.split())
        for frag in ("49~99%", "중앙값73%", "판정강도약함", "2014~2024년", "계산미반영"):
            self.assertIn(frag, compact, f"PDF 출처 문구 '{frag}' 누락")

    def test_fallback_screen_when_gate_missing(self):      # B6
        import revenue_band_display as rbd
        saved = rbd.GATE_PATH
        rbd.GATE_PATH = os.path.join(H.DATA, "없는_게이트.json")
        try:
            at = _app()
            at.run()
            self.assertEqual([getattr(e, "value", str(e)) for e in at.exception], [])
            caps = _captions(at)
            self.assertTrue(any(LEGACY_ANCHOR in c for c in caps), "폴백 시 기존 문구 미표시")
            self.assertFalse(any(EXPECT_SHORT in c for c in caps))
            self.assertEqual(at.session_state["fn_base_params"]["capex_억"], 13000)
        finally:
            rbd.GATE_PATH = saved


if __name__ == "__main__":
    unittest.main()
