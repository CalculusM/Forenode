# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
# Forenode 앱 컨테이너 이미지 (국내 서버 이전용, 2026-09-28 작성)
#
# 빌드 위치: 저장소 루트(build context = 저장소 루트)
#   docker build -f deploy/Dockerfile -t forenode-app:latest .
#   또는 deploy/ 에서  docker compose build
# 제외 규칙: deploy/Dockerfile.dockerignore (BuildKit이 Dockerfile 옆 파일을 자동 적용)
#
# 파이썬 버전 판단 근거
#   - 로컬 검증 환경: Python 3.14.4 (streamlit 1.56.0, 기동·AppTest 통과)
#   - .devcontainer: 3.11 / Streamlit 공식 Docker 예시: 3.12-slim
#   - requirements.txt 하한(numpy>=1.24, scikit-learn>=1.3 등) 및 ifcopenshell·xgboost·chromadb
#     휠 제공 범위를 모두 만족하는 중간값 3.12 채택. 필요 시 --build-arg PYTHON_VERSION=3.11 등으로 변경
# ------------------------------------------------------------------
ARG PYTHON_VERSION=3.12

# ---------- 1단계: 의존성 빌드 (컴파일러는 이 단계에만 존재) ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# apt 설치 중 대화형 질문(tzdata 지역 선택 등) 차단, 빌드 단계에만 적용
ARG DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# requirements.lock.txt 가 deploy/ 에 있으면 고정 버전으로 설치(재현성·롤백용), 없으면 requirements.txt 그대로 설치
# (대괄호 표기 = 파일이 없어도 COPY 실패하지 않게 하는 와일드카드)
COPY requirements.txt deploy/requirements.lock.tx[t] ./
RUN pip install --upgrade pip setuptools wheel \
 && if [ -f requirements.lock.txt ]; then \
        echo "[build] requirements.lock.txt 사용"; pip install -r requirements.lock.txt; \
    else \
        echo "[build] requirements.txt 사용(버전 미고정)"; pip install -r requirements.txt; \
    fi

# ---------- 2단계: 실행 이미지 ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/opt/venv/bin:${PATH}" \
    TZ=Asia/Seoul \
    MPLCONFIGDIR=/tmp/matplotlib \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    ANONYMIZED_TELEMETRY=False

# apt 패키지
#   - packages.txt (Streamlit Cloud와 동일 목록, 현재 fonts-nanum 1건)
#       report_generator.py 가 /usr/share/fonts/truetype/nanum/NanumGothic.ttf 를 직접 등록 = 한글 PDF 필수
#   - libgomp1: xgboost·scikit-learn OpenMP 런타임 (slim 이미지 결손 보강, 무해)
#   - tzdata: TZ=Asia/Seoul 적용 (보고서 생성일 등 datetime.now() 표기)
#   - sed 처리: Windows 체크아웃 시 CRLF 줄끝·주석·빈 줄 제거
COPY packages.txt /tmp/packages.txt
RUN apt-get update \
 && { sed -e 's/\r$//' -e 's/#.*$//' /tmp/packages.txt; echo libgomp1; echo tzdata; } \
    | xargs -r apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* /tmp/packages.txt \
 && test -f /usr/share/fonts/truetype/nanum/NanumGothic.ttf

# 비루트 실행 사용자
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# 코드는 root 소유(앱 사용자 읽기 전용). 예외 2건만 앱 사용자 쓰기 허용
#   - chroma_db: chromadb 가 열 때 sqlite 파일을 갱신
#     (로컬에서도 앱 실행 후 chroma_db/*.sqlite3·*.bin 이 수정 상태로 바뀌는 것 확인됨. 컨테이너 재생성 시 원본 복귀 = 참조 전용 색인이라 무방)
#   - data/interval_scores_v1.csv · data/interval_scores_full_v1.csv: pages/2_검증_성적표.py 가 렌더마다
#     interval_scoring.run()·run_full() 을 호출해 두 파일을 다시 씀. 쓰기 불가 시 예외가 화면 안에서 처리되어
#     "통계 점검 요약 일시 로드 불가: Permission denied" 문구로 대체됨(스모크 시험 예외 0건으로 통과해 버리는 유형)
#     파일 단위 권한만 부여(폴더 쓰기 불요: 기존 파일 덮어쓰기)
COPY . /app
RUN chown -R app:app /app/chroma_db \
 && for f in /app/data/interval_scores_v1.csv /app/data/interval_scores_full_v1.csv; do \
        touch "$f" && chown app:app "$f"; \
    done

USER app

EXPOSE 8501

# 헬스체크: Streamlit 내장 엔드포인트 /_stcore/health (정상 시 본문 "ok")
# curl 미설치 이미지이므로 파이썬 표준 라이브러리로 확인
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).read().strip()==b'ok' else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
