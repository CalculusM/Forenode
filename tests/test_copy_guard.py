# -*- coding: utf-8 -*-
"""금지 문구 가드(2026-10 추진현황 스터디 A1) + 수정 페이지 AppTest 스모크.

- 줄표(U+2014)·화살표(U+2192)·금지 표현이 app.py·pages·threshold_display.py·report_generator.py·README·봉인 CSV에 0건.
- .py는 문자열 리터럴만 검사(주석·docstring 제외, ast). README·CSV는 전문 검사.
- 본 변경 이전부터 있던 잔존은 ALLOW에 명시(메인 세션 정정 대상, 정정 시 항목 삭제).
- pages/1·2·3을 app.py에서 switch_page로 실행(test_app_smoke.PagesSmoke와 같은 경로), 예외 0.
"""
import ast
import glob
import logging
import os
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS = (chr(0x2014), chr(0x2192), "예측 시점 이후", "유일", "15/21", "21개 중 15개", "정부 게이트", "회귀 범위",
          "CAPEX 회귀", "회귀 추정", "회귀 기반", "국내 실측 회귀","학습한 통계", "학습 통계",
          "재협상 트리거 사전 확률", "BIM 기반")
PY_FILES = ["app.py", "threshold_display.py", "report_generator.py"] + sorted(glob.glob(os.path.join(ROOT, "pages", "*.py")))
TEXT_FILES = ["README.md"] + sorted(glob.glob(os.path.join(ROOT, "data", "*registry*.csv")))
# 알려진 잔존: (상대경로, 해당 줄에 포함된 문자열). 본 작업 이전부터 존재, 메인 세션 판단·정정 대상.
ALLOW = (
    ("pages/2_검증_성적표.py", 'replace(" — "'),                # 원장 표시 치환 로직(문자 자체)
    ("pages/2_검증_성적표.py", 'replace(" → "'),
    ("pages/2_검증_성적표.py", r"(\d+)→(\d+)%"),
)   # '21개 중 15개' 질문 3 서술은 e39b0fd(헤드라인 정리)에서 제거됨, 2026-10-14 병합으로 해소


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _string_hits(path):
    """.py 파일의 문자열 리터럴(docstring 제외) 중 금지 토큰 포함 (줄번호, 토큰, 원문 줄)."""
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
            docs.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            seg = lines[node.lineno - 1:node.end_lineno]   # 여러 줄 이어 쓴 리터럴은 구간 전체로 대조
            for t in TOKENS:
                if t in node.value:
                    ln = next((i for i, l in enumerate(seg, node.lineno) if t in l), node.lineno)
                    out.append((ln, t, lines[ln - 1], "\n".join(seg)))
    return out


def _text_hits(path):
    return [(i, t, l, l) for i, l in enumerate(open(path, encoding="utf-8").read().splitlines(), 1)
            for t in TOKENS if t in l]


class CopyGuard(unittest.TestCase):
    def test_no_forbidden_phrases(self):
        bad = []
        for f in PY_FILES + TEXT_FILES:
            p = os.path.join(ROOT, f)
            if not os.path.exists(p):
                continue
            rel = _rel(p)
            for ln, tok, line, seg in (_string_hits(p) if p.endswith(".py") else _text_hits(p)):
                if not any(a == rel and sub in seg for a, sub in ALLOW):
                    bad.append(f"{rel}:{ln} [{tok!r}] {line.strip()[:80]}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_allowlist_still_needed(self):
        """정정된 잔존은 ALLOW에서도 지워 가드를 다시 조인다."""
        for rel, sub in ALLOW:
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            self.assertIn(sub, src, f"ALLOW 항목 불필요: {rel} {sub!r}")


class PagesRun(unittest.TestCase):
    def test_pages_1_2_3_no_exception(self):
        warnings.filterwarnings("ignore")
        logging.getLogger("streamlit").setLevel(logging.ERROR)
        from streamlit.testing.v1 import AppTest
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            for p, marker in (("1_데이터_출처.py", "계산 미연동"), ("2_검증_성적표.py", "제안 전 노선 문턱 봉인"),
                              ("3_학습데이터_출처.py", "계산 미연동(참고 데이터)")):
                at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=300)
                at.switch_page(os.path.join("pages", p))
                at.run()
                self.assertEqual([getattr(e, "value", str(e)) for e in at.exception], [], f"{p} 예외")
                self.assertGreaterEqual(len(at.title), 1, f"{p} 제목 미표시")
                texts = [e.value for e in list(at.markdown) + list(at.caption)]
                self.assertTrue(any(marker in t for t in texts), f"{p} '{marker}' 미표시")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
