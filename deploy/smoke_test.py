"""Forenode 배포 스모크 시험 (2026-09-28 작성)

목적
  - /_stcore/health 는 서버 프로세스만 확인(스크립트 미실행) = ImportError 등 앱 오류를 잡지 못함
  - 본 스크립트는 Streamlit AppTest 로 app.py 와 pages/* 전 페이지를 실제 1회 실행, 예외 0건 확인

사용
  저장소 루트 또는 어디서든:   python deploy/smoke_test.py
  컨테이너 안:                 docker compose exec -T app python deploy/smoke_test.py   (deploy/ 폴더에서)

외부 호출 차단
  OPENAI_API_KEY 를 이 프로세스 안에서만 빈 값으로 덮어씀
  = 법제 RAG 탭이 키 확인 단계에서 조기 반환, chroma_db·OpenAI 미접근 (실행 중인 서비스에는 영향 없음)

처리된 오류 문구 검사 (2026-09-28 검증 단계 추가)
  앱은 여러 곳에서 예외를 잡아 st.caption·st.warning·st.error 문구로 대체 표시함 = at.exception 에 안 잡힘
  - 환경 오류(실패 판정): 권한·파일 누락·모듈 누락·공유 라이브러리 누락 등 운영체제·설치 표지
      예: pages/2 "통계 점검 요약 일시 로드 불가: [Errno 13] Permission denied" (쓰기 권한 누락)
  - 앱 처리 오류(경고만): "... 실패: ..." 등 앱 로직 문구. 배포 환경과 무관한 기존 결함일 수 있어 판정 제외
      예: app.py XGBoost 탭 "SHAP 분석 실패: too many indices ..." (로컬 shap 0.51.0 에서도 동일 발생)

종료 코드
  0 = 전 페이지 예외·환경 오류 0건(앱 처리 오류 경고는 허용) / 1 = 발생 / 2 = 실행기 오류
"""
import glob
import os
import re
import sys
import time

os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 환경 오류 표지(실패 판정): 운영체제·설치 계열 예외 메시지 공통 문자열
ENV_FAIL = re.compile(r"Errno|Permission denied|No such file|No module named|shared object|Traceback")
# 앱 처리 오류 표지(경고만): 앱 코드 except 문구 형식(2026-09-28 grep 기준)
#   "... 실패: {e}" · "... 불가: {e}" · "... 오류: {e}" · "IFC 처리 실패({e})" · "... 불러오지 못했습니다: {e}"
APP_WARN = re.compile(r"(실패|불가|오류)\s*[:(]|불러오지 못했습니다")


def handled_errors(at):
    """화면에 표시된 처리된 오류 문구(caption·warning·error)를 (환경 오류, 앱 처리 오류) 두 목록으로 반환."""
    env, app = [], []
    for kind in ("error", "warning", "caption"):
        try:
            elems = list(getattr(at, kind))
        except Exception:
            continue
        for el in elems:
            v = str(getattr(el, "value", ""))
            if ENV_FAIL.search(v):
                env.append(f"{kind}: {v[:300]}")
            elif APP_WARN.search(v):
                app.append(f"{kind}: {v[:300]}")
    return env, app


def report(label: str, at, t_start: float, extra: str = "") -> int:
    """한 화면 결과 출력, 실패 판정 건수(예외 + 환경 오류) 반환."""
    n = len(at.exception)
    env, app = handled_errors(at)
    print(f"[smoke] {label}  예외 {n}건  환경 오류 {len(env)}건  앱 처리 오류(경고) {len(app)}건{extra}  {time.time() - t_start:.1f}s")
    for ex in at.exception[:3]:
        print("         예외:", str(ex.value)[:300])
    for h in env[:3]:
        print("         환경 오류:", h)
    for h in app[:3]:
        print("         경고:", h)
    return n + len(env)


def main() -> int:
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as e:  # pragma: no cover
        print(f"[smoke] streamlit.testing 불러오기 실패: {e}")
        return 2

    failed = 0
    t0 = time.time()
    at = AppTest.from_file("app.py", default_timeout=300)
    try:
        at.run()
    except Exception as e:
        print(f"[smoke] app.py 실행기 오류: {type(e).__name__}: {e}")
        return 2
    failed += report("app.py", at, t0, f"  요소 {len(at.main.children)}개")

    # 멀티페이지 문맥 유지를 위해 app.py 세션에서 switch_page 로 이동
    # (페이지 파일 단독 실행 시 st.page_link 가 KeyError 'url_pathname' 을 내는 AppTest 한계 회피)
    for page in sorted(glob.glob("pages/*.py")):
        page = page.replace("\\", "/")
        t1 = time.time()
        try:
            at.switch_page(page)
            at.run()
        except Exception as e:
            print(f"[smoke] {page} 실행기 오류: {type(e).__name__}: {e}")
            return 2
        failed += report(page, at, t1)

    print(f"[smoke] 결과: {'통과' if failed == 0 else '실패'} (예외·환경 오류 합계 {failed}건, 총 {time.time() - t0:.1f}s)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
