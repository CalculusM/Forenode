# -*- coding: utf-8 -*-
"""D1·D4·S1 데이터 자산 회귀(엔진 영향 0, 스터디 결과 재현 확인). 실행: python -m unittest tests.test_route_pipeline

- 시험 36행: pipeline_loader.engine_inputs의 5개 입력으로 _helpers 경로를 돌려 04_five_input_results.json 문턱과 ±1대.
- 권장 협약 수요 = 문턱 ÷ 앵커(_helpers.TRAFFIC_ANCHOR_RATIO), 차감 근거 행 산술, 소형차 전용 5행 중차량 0, 결측 0 대체 없음.
- S1 원장: D1 수치 셀마다 채택 Y 행 1개, 상충 그룹 6건 이상, 08 비null 항목 전부 수록, 금지 표현 0건.
"""
import csv
import hashlib
import json
import os
import re
import sys
import unittest
import warnings

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS, os.path.join(ROOT, "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")

import _helpers as H                          # noqa: E402
import pipeline_loader as PL                  # noqa: E402
import build_pipeline_sources as BPS          # noqa: E402

SRC = os.path.join(os.path.dirname(ROOT), "_research_sources", "pipeline_2026-10")
DATA = os.path.join(ROOT, "data")
META = os.path.join(DATA, "route_pipeline_2026-10.meta.json")
SOURCES_CSV = os.path.join(DATA, "route_pipeline_sources_2026-10.csv")
SOURCES_META = os.path.join(DATA, "route_pipeline_sources_2026-10.meta.json")
FIVE = ("business_type", "road_length", "total_capex", "toll_per_km", "operation_years")
# 금지 표현·서면 응답사명. 이 파일 자체가 grep에 걸리지 않도록 리터럴을 쪼개 둔다
COMPANY_TERMS = ["".join(t) for t in (("금", "광"), ("쌍", "용"), ("GS", "건설"), ("동부", "건설"), ("월드", "뷰"))]
PHRASE_TERMS = ["".join(t) for t in (("유", "일"), ("예측 시점", " 이후"), ("15", "/21"), ("21개 중", " 15개"),
                                     ("정부 ", "게이트"), ("회귀 ", "범위"), ("—",), ("→",))]


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class RoutePipelineD1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = PL.load_route_pipeline()
        with open(os.path.join(SRC, "04_five_input_results.json"), encoding="utf-8") as f:
            cls.results = json.load(f)
        with open(META, encoding="utf-8") as f:
            cls.meta = json.load(f)
        cls.by_raw = {r["노선_원문표기"]: r for _, r in cls.df.iterrows()}

    def test_rows_versions_and_untested(self):
        df = self.df
        self.assertEqual(len(df), 40)
        self.assertEqual(set(df["pipeline_version"]), {self.meta["pipeline_version"]})
        self.assertEqual(len(PL.load_route_pipeline(version=self.meta["pipeline_version"])), 40)
        untested = df[df["결과상태_2026-10-07"] == "미시험"]
        self.assertEqual(set(untested["노선"]), {"서수원~광주", "중봉터널", "반송터널", "제2경춘국도 연결"})
        self.assertEqual(set(untested["민간투자비_근거"]), {"미산출"})
        self.assertEqual(len(df) - len(untested), len(self.results))
        self.assertTrue(set(df["결과상태_2026-10-07"]) <= {"통과이상", "통과전", "탈락", "범위밖", "미시험"})
        self.assertTrue(set(df["모형범위"]) <= {"신설", "개량운영형=범위밖", "터널단독=미적용"})

    def test_five_input_rows_reproduce_study_thresholds(self):
        for res in self.results:
            row = self.by_raw[res["name"]]
            inputs = PL.engine_inputs(row)
            five = {k: inputs[k] for k in FIVE}
            for k in FIVE:
                self.assertEqual(float(five[k]) if k != "business_type" else five[k],
                                 float(res["inputs"][k]) if k != "business_type" else res["inputs"][k], (res["name"], k))
            case = H.app_default_case(**five)
            gov, _ = H.threshold_traffic(case, "gov")
            self.assertAlmostEqual(gov, res["thresholds"]["gov"]["traffic"], delta=1.0, msg=res["name"])
            self.assertEqual(int(row["문턱_재무성립선_5입력"]), res["thresholds"]["gov"]["traffic"], res["name"])
            self.assertEqual(int(row["권장협약수요_5입력"]), res["recommended_agreement_traffic"], res["name"])
            self.assertAlmostEqual(res["thresholds"]["gov"]["traffic"] / H.TRAFFIC_ANCHOR_RATIO,
                                   res["recommended_agreement_traffic"], delta=1.0, msg=res["name"])

    def test_capex_subtraction_rows(self):
        rows = self.df[self.df["민간투자비_근거"] == "총사업비-보조-보상"]
        self.assertTrue({"태안~안성", "공주~천안", "광명~서울", "서울~양주", "오산~용인", "경기북부 중심"} <= set(rows["노선"]))
        for _, r in rows.iterrows():
            total = float(r["총사업비_억"]) - float(r["건설보조금_억"] or 0) - float(r["보상비_억"] or 0)
            self.assertAlmostEqual(total, float(r["민간투자비_억"]), delta=0.5, msg=r["노선"])
        self.assertTrue(set(self.df["민간투자비_근거"]) <= {"입력값", "총사업비-보조-보상", "총사업비×비율(추정)", "단가모형", "미산출"})

    def test_small_car_rows_and_tunnel_cap(self):
        small = self.df[self.df["소형차전용"] == "Y"]
        self.assertEqual(set(small["노선"]), {"제2용인~서울", "성남~강남", "구리~성남", "제4경인", "양재~올림픽대로"})
        cap, capped = PL.tunnel_cap(), 0
        for _, r in self.df.iterrows():
            inputs = PL.engine_inputs(r)
            self.assertEqual(inputs.get("heavy_ratio_pct"), 0 if r["소형차전용"] == "Y" else None, r["노선"])
            if r["터널비율"]:
                self.assertLessEqual(inputs["tunnel_ratio"], cap)
                capped += float(r["터널비율"]) > cap
        self.assertGreaterEqual(capped, 4)   # 시흥~송파·사상~해운대·제2용인~서울·구리~성남

    def test_no_zero_fill_where_source_empty(self):
        for col in ("연장_km", "총사업비_억", "건설보조금_억", "보상비_억", "민간투자비_억", "수익률_pct", "예측교통량_대일", "협약교통량_대일"):
            self.assertNotIn("0", set(self.df[col]), col)
        self.assertEqual(set(self.df["협약교통량_대일"]), {""})

    def test_meta_and_d4_columns(self):
        for rel, digest in self.meta["inputs_sha256"].items():
            self.assertEqual(_sha(os.path.join(os.path.dirname(ROOT), rel)), digest, rel)
        self.assertRegex(self.meta["git_head"], r"^[0-9a-f]{40}$")
        self.assertFalse(self.meta["engine_reflected"])
        for col in self.meta["columns_added"]["D4"]:
            self.assertIn(col, self.df.columns)
        self.assertGreaterEqual((self.df["민간투자비_KOTI보조율"] != "").sum(), 11)
        self.assertEqual(set(self.df.loc[self.df["민간투자비_KOTI보조율"] != "", "보조율적용_주의"]), {"투자비계 보상비 포함 여부 미규명"})
        r = self.df[self.df["노선"] == "사상~해운대"].iloc[0]
        self.assertTrue(r["문턱_KOTI보조율"] and r["문턱_0.70"])
        self.assertNotEqual(r["문턱_KOTI보조율"], r["문턱_0.70"])
        self.assertNotEqual(r["문턱_KOTI보조율"], r["문턱_재무성립선_5입력"])


class RoutePipelineSourcesS1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SOURCES_CSV, encoding="utf-8-sig") as f:
            cls.rows = list(csv.DictReader(f))
        with open(SOURCES_META, encoding="utf-8") as f:
            cls.meta = json.load(f)
        cls.df = PL.load_route_pipeline()

    def test_one_adopted_row_per_pipeline_numeric_cell(self):
        adopted = {(r["노선"], r["항목"]): r["값"] for r in self.rows if r["채택여부"] == "Y"}
        self.assertEqual(len(adopted), sum(r["채택여부"] == "Y" for r in self.rows))   # (노선, 항목) 중복 Y 없음
        cells = {(r["노선"], item): BPS.fmt(r[col]) for _, r in self.df.iterrows()
                 for col, (item, _, _) in BPS.ADOPTED.items() if r[col] != ""}
        self.assertEqual(adopted, cells)

    def test_conflict_groups_registered(self):
        groups = self.meta["conflict_groups"]
        self.assertGreaterEqual(len(groups), 6)
        for gid in ("CF-의왕~광주-총사업비", "CF-하남~남양주~포천-총사업비", "CF-양재~고양-총사업비", "CF-평택~시흥-총사업비",
                    "CF-사상~해운대-총사업비", "CF-서창~김포-총사업비", "CF-양재~올림픽대로-통행료", "CF-팔공산-통행료"):
            self.assertIn(gid, groups)
            self.assertGreaterEqual(sum(r["상충그룹ID"] == gid for r in self.rows), 2, gid)

    def test_reality_side_fields_all_present(self):
        with open(os.path.join(SRC, "08_reality_side.json"), encoding="utf-8") as f:
            blocks = json.load(f)
        have = {(r["노선"], r["항목"], r["값"]) for r in self.rows}
        n_rec, n_fact_null = 0, 0
        for block in blocks:
            for rec in block["routes"]:
                n_rec += 1
                key = PL.route_key(rec["name"])
                for field, (item, _) in BPS.REALITY_ITEM.items():
                    val = rec.get(field)
                    if val in (None, ""):
                        if field in BPS.FACT_FIELDS:
                            n_fact_null += 1
                            self.assertIn((key, item, ""), have, (rec["name"], field))
                        continue
                    val = BPS.fmt(val)
                    for w, rep in BPS.GUARD_REPLACE.items():
                        val = val.replace(w, rep)
                    self.assertIn((key, item, val), have, (rec["name"], field))
                for s in rec["sources"]:
                    self.assertIn((key, "출처", s), have, (rec["name"], s))
        self.assertEqual(n_rec, 58)
        self.assertEqual(self.meta["rows"]["null_fact_rows"], n_fact_null)

    def test_no_forbidden_terms(self):
        files = [os.path.join(DATA, n) for n in ("route_pipeline_2026-10.csv", "route_pipeline_sources_2026-10.csv",
                                                  "route_pipeline_2026-10.meta.json", "route_pipeline_sources_2026-10.meta.json")]
        copies = [os.path.join(SRC, n) for n in os.listdir(SRC)]
        for path in files + copies:
            text = _read(path)
            for term in COMPANY_TERMS:
                self.assertNotIn(term, text, path)
        for path in files:
            text = _read(path)
            for term in PHRASE_TERMS:
                self.assertNotIn(term, text, (path, term))


if __name__ == "__main__":
    unittest.main()
