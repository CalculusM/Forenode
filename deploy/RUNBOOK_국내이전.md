# Forenode 서비스 서버 국내 이전 런북

- 작성일: 2026-09-28
- 상태: 준비 패키지 (서버 미생성 · 미배포 · deploy/ 폴더 미커밋)
- 대상 저장소: github.com/CalculusM/Forenode (public, 기본 브랜치 main, 2026-09-28 gh 조회)
- 범례: **[대표]** 대표 직접 수행(계정·결제·약관 동의·DNS·키 입력) · **[서버]** 서버 접속 후 명령 실행 · **[확인]** 결과 확인 항목
- 원칙: 실제 키 값 문서·저장소 기입 금지 · 확보 못 한 값은 ✚ 표기

---

## 1. 이전 목적

- 현행 Streamlit Community Cloud 한계 3건
  - 약관상 개인·비상업 용도 한정(personal and non-commercial): 유료 전환·기관 제안 단계에서 약관 위반 소지
  - 미국 단일 호스팅: 보안 1페이저 "데이터 국내 체류" 항목이 '목표' 상태에 머묾
  - 12시간 무방문 시 절전: GitHub Actions keep-awake 크론(2시간 주기)으로 우회 중
- 이전 목표: 국내 리전 단일 서버(2vCPU·4GB)에 앱 컨테이너 1개와 nginx(HTTPS) 구성, 상시 기동

---

## 2. 현행 앱 점검 결과 (2026-09-28 코드 확인)

| 항목 | 확인 결과 | 배포 반영 |
|---|---|---|
| 파이썬 | 로컬 3.14.4 · .devcontainer 3.11 · requirements는 하한만 지정 | 이미지 3.12(slim-bookworm, Streamlit 공식 Docker 예시와 동일 계열), 빌드 인자로 변경 가능 |
| requirements.txt | 20개 패키지, protobuf==3.20.3 외 전부 하한(>=)만 지정 | 빌드 시점마다 최신판 설치 구조. 첫 빌드 직후 lock 파일 생성 권장(7.4) |
| packages.txt | fonts-nanum 1건. 로컬 파일은 CRLF, 저장소 저장본은 LF | Dockerfile에서 CRLF·주석 제거 후 설치, 폰트 파일 존재 검사로 누락 시 빌드 실패 처리 |
| 한글 폰트 | report_generator.py가 /usr/share/fonts/truetype/nanum/NanumGothic.ttf 직접 등록 | 필요(fonts-nanum 설치) |
| 환경변수 | OPENAI_API_KEY(법제 RAG 탭 전용, rag_tab.py) · ECOS_API_KEY(app.py ECOSConnector 폴백, 사이드바 입력 우선) · st.secrets 미사용 | .env.example 2항목 |
| 로컬 .env | OPENAI_API_KEY 1항목 존재(값 미열람), git 미추적 | 서버 .env에 대표 직접 기입 |
| pages/ | 4개: 1_데이터_출처 · 2_검증_성적표 · 3_학습데이터_출처 · 4_시나리오_비교 | 전부 이미지 포함 |
| data/ | 109KB, 추적 파일 9건 | 포함 |
| chroma_db | 27MB, git 추적 5건. rag_tab.py가 런타임에 ./chroma_db 열람(RAG 사용 중) | 포함. chromadb가 열 때 sqlite 파일을 갱신하므로 앱 사용자 쓰기 권한 부여 |
| 상대경로 열람 | ./xgb_model.pkl · ./weibull_params.json · ./chroma_db 등 | 작업 폴더 = 저장소 루트 고정 |
| 런타임 쓰기 | IFC 업로드 임시파일(/tmp) · chroma_db · data/interval_scores_v1.csv · data/interval_scores_full_v1.csv(pages/2가 렌더마다 interval_scoring.run()·run_full()로 재작성, 검증 단계 발견) | 코드 폴더 읽기 전용, /tmp·chroma_db·점수 CSV 2개만 쓰기(파일 단위 권한) |
| 대용량 원천 폴더 | 02 교통량데이터 약 5.5GB 등 13개 폴더, .gitignore 제외 | 이미지 제외(Streamlit Cloud 배포본과 동일 범위) |
| keep-awake 크론 | .github/workflows/keep-streamlit-awake.yml, cron '23 */2 * * *', 상태 active, 최근 3회 성공(최종 2026-09-28 05:31 UTC 실행, 로그 "App awake") | 이전 후 비활성화(16장) |
| 외부 전송 | OpenAI API(RAG) · chromadb 익명 텔레메트리(기본 켜짐) · Streamlit 사용 통계(기본 켜짐) | 텔레메트리 2종은 환경변수로 끔(ANONYMIZED_TELEMETRY=False, STREAMLIT_BROWSER_GATHER_USAGE_STATS=false) |

---

## 3. 산출물 목록 (deploy/)

| 파일 | 용도 |
|---|---|
| Dockerfile | 2단계 빌드(컴파일러는 빌드 단계에만), python:3.12-slim-bookworm, packages.txt·libgomp1·tzdata 설치, 비루트 사용자(uid 10001), 쓰기 예외 2건(chroma_db · 점수 CSV 2개), HEALTHCHECK /_stcore/health |
| Dockerfile.dockerignore | 빌드 제외 규칙(.dockerignore 역할). build context가 저장소 루트이므로 deploy/.dockerignore는 Docker가 읽지 않음, BuildKit이 Dockerfile 옆 이 파일을 자동 적용. chroma_db 포함 사유 기록 |
| docker-compose.yml | restart: unless-stopped · env_file: .env · 127.0.0.1:8501 게시 · 메모리 상한 3GB · 로그 순환(10MB×5) |
| .env.example | 환경변수 2항목 빈 값 예시 |
| nginx/forenode.conf | 80 포트 사이트 설정, 웹소켓 필수 헤더, 업로드 상한 200MB, certbot 절차 주석 |
| systemd/forenode.service | Docker 없이 venv로 운영하는 대안 유닛(준비 명령 주석 포함) |
| smoke_test.py | AppTest로 app.py와 pages/* 전 페이지 1회 실행, 예외 0건 확인(헬스체크 보완). 화면 안에서 처리된 오류 문구도 검사: 환경 오류(Errno·권한·모듈 누락 등)는 실패, 앱 처리 오류("... 실패: ...")는 경고만 |
| update.sh | git pull · 재빌드 · 재기동 · 헬스체크 · 스모크 시험, 실패 시 직전 이미지 자동 복귀 |
| .gitattributes | deploy/ 하위 LF 줄끝 고정(Windows 체크아웃 시 CRLF 혼입 방지) |
| RUNBOOK_국내이전.md | 본 문서 |

---

## 4. 로컬 기동 시험 결과 (2026-09-28)

### 4.1 필수 시험: streamlit run 기동

- 환경: Windows 11 Home · Python 3.14.4 · streamlit 1.56.0 · 저장소 작업 폴더 그대로 사용
- 명령: `python -m streamlit run app.py --server.headless true --server.port 8599 --browser.gatherUsageStats false` 백그라운드 실행(PYTHONIOENCODING=utf-8)

| 확인 항목 | 결과 |
|---|---|
| /_stcore/health | **ok**, 기동 후 약 7초 만에 응답(1초 간격 폴링, 상한 90초) |
| 메인 페이지 GET / | **HTTP 200**, 4,876바이트, `<title>Streamlit</title>` · `<div id="root">` 확인 |
| /_stcore/host-config | HTTP 200 |
| 멀티페이지 경로 /검증_성적표 | HTTP 200 |
| 웹소켓 /_stcore/stream 업그레이드 | HTTP/1.1 101 Switching Protocols (nginx 프록시 대상 경로 확인) |
| 종료 | python.exe(PID 34180) 종료, 8599 포트 해제 확인 |

- 부수 확인: 시험 전후 chroma_db 파일 수정 시각 불변(2026-08-07 00:10:19) · git status 변화 없음 = 저장소 무변경
- 한계: HTTP 요청만으로는 app.py 스크립트 미실행(Streamlit은 브라우저 세션 연결 후 실행). 스크립트 오류 검출은 4.2 보완 시험으로 확인

### 4.2 보완 시험: 스크립트 실행 (Streamlit AppTest)

- 방법: git 추적 파일만 스크래치 폴더로 복사(29MB, .env 미포함 = 서버 배포본과 동일 구성) 후 deploy/smoke_test.py 실행

| 대상 | 결과 |
|---|---|
| app.py | 예외 0건, 최상위 요소 41개, 첫 실행 11.8초(콜드) · 재실행 3.2~3.5초 |
| pages/1~4 | 전부 예외 0건 (app.py 세션에서 switch_page 이동) |
| 음성 대조 | pages/1에 RuntimeError 주입 시 "예외 1건 · 실패 · 종료 코드 1" 검출 확인 후 원복 |
| 메모리 | 2회 실행 후 작업 집합 최대 약 317MiB (RAG 비활성 조건, Windows API 측정) |

- 참고: 페이지 파일 단독 AppTest 실행 시 pages/3에서 KeyError 'url_pathname' 발생. st.page_link의 멀티페이지 문맥 부재에 따른 시험 도구 한계이며 switch_page 방식에서 0건 = 앱 결함 아님

### 4.3 Docker 빌드

- 로컬 PC Docker 미설치(`docker: command not found`) = **docker build 미시도**
- 대체 정적 확인
  - docker-compose.yml YAML 구문 해석 정상
  - update.sh `bash -n` 구문 검사 정상 · smoke_test.py 컴파일 정상
  - 빌드 context 모의 판정(제외 규칙 적용): 108개 파일 · 28.7MiB. 저장소 추적 파일 중 제외는 .devcontainer · .github 2건(의도). .env 제외 · chroma_db 포함 · deploy/smoke_test.py 포함 확인
  - 로컬 판정 시 미추적 작업 파일 4건(research/ 등)이 context에 들어감. 서버는 git clone 기준이라 해당 없음
- 서버 첫 빌드에서 확인할 미검증 항목: Linux 의존성 해석(17장 1번), `nginx -t`, systemd 유닛 기동

### 4.4 검증 단계 재시험 (2026-09-28, 별도 검증 절차)

| 확인 항목 | 결과 |
|---|---|
| 기동 재현(8598 포트, 127.0.0.1 대기) | /_stcore/health **ok**(약 2.4초) · GET / HTTP 200(4,876바이트) · /_stcore/host-config 200 · 종료 후 프로세스·포트 잔존 0건 · chroma_db 수정 시각 불변 |
| 컨테이너 권한 모의 | git 추적 파일 사본(git archive HEAD, 29MB, 스크래치 폴더)에서 파일 쓰기 권한 제한 후 smoke_test.py 실행 |
| 모의 결과(수정 전 권한) | 점수 CSV 2개 읽기 전용 조건: pages/2 "자주 나오는 질문 네 가지" 구역이 "통계 점검 요약 일시 로드 불가: [Errno 13] Permission denied" 문구로 대체. 예외는 화면 안에서 처리되어 at.exception 0건 = 기존 판정 방식은 통과. 보강 판정 방식은 환경 오류 1건 · 종료 코드 1 |
| 조치 | Dockerfile에 점수 CSV 2개 파일 단위 쓰기 권한 추가 · smoke_test.py에 처리된 오류 문구 검사 추가 |
| 모의 결과(수정 후 권한) | chroma_db · 점수 CSV 2개 외 전 파일 읽기 전용 조건: 전 페이지 예외 0건 · 환경 오류 0건 · 신규 파일 생성 0건 · 변경 파일은 점수 CSV 2개만 · 종료 코드 0 |
| 기존 앱 결함(경고) | app.py XGBoost 탭 "SHAP 분석 실패: too many indices for array" 1건. 로컬 원본 환경(shap 0.51.0 · xgboost 3.2.0)에서도 동일 = 배포 무관, 17장 9번 |

---

## 5. 서버 생성 [대표]

- 1안: 네이버클라우드 Server, High CPU-g2 2vCPU·4GB, 기본 디스크 50GB, 공인 IP 1개
  - 리전: 한국(KR)
  - OS 이미지: Ubuntu 24.04 권장(기본 python3가 3.12 = 이미지와 동일 버전). 목록에 없으면 Ubuntu 22.04와 Docker 경로 사용
  - 인증키(.pem): 대표 PC에만 보관, 저장소·메일 첨부 금지
  - 공인 IP 할당 후 주소 기록(도메인 A 레코드에 사용)
- 대안: 가비아 High CPU(월 55,000원, 스토리지 별도) · NHN Cloud(스타트업 크레딧 조건 확인 후, 15장)
- 계정 생성 · 본인 인증 · 결제수단 등록 · 약관 동의 · 서버 생성 실행 = 전부 대표 몫

---

## 6. 접속·보안그룹

### 6.1 인바운드 규칙 (네이버클라우드 ACG, 타사 명칭은 보안그룹)

| 포트 | 허용 출처 | 용도 |
|---|---|---|
| 22/TCP | 대표 접속지 공인 IP/32만 | SSH |
| 80/TCP | 0.0.0.0/0 | HTTP (certbot 인증, HTTPS 전환) |
| 443/TCP | 0.0.0.0/0 | HTTPS |

- 8501 미개방: compose가 127.0.0.1에만 게시, 외부 접근은 nginx 경유만 허용

### 6.2 최초 접속·초기 보안 [대표 일부 · 서버]

- 최초 접속: `ssh -i <인증키.pem> root@<공인IP>` (초기 관리자 비밀번호 확인은 콘솔에서 대표 수행)
- 관리 계정 생성: `adduser deploy && usermod -aG sudo deploy`, deploy 계정에 SSH 공개키 등록
- 비밀번호 로그인 차단: /etc/ssh/sshd_config 의 `PasswordAuthentication no`, 새 세션으로 키 접속 확인 후 `systemctl restart ssh`
- 방화벽 이중화(선택): `ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable`
  - Docker 게시 포트는 ufw 규칙을 우회하나, 본 구성은 127.0.0.1 게시라 영향 없음
- 보안 업데이트: `apt update && apt -y upgrade && apt install -y unattended-upgrades`
- 스왑 2GB(선택, 첫 빌드 중 메모리 부족 예방)
  ```bash
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

---

## 7. 설치 (Docker 경로, 권장)

### 7.1 패키지 [서버]

```bash
sudo apt update
sudo apt install -y git curl nginx docker.io docker-compose-v2 docker-buildx
sudo usermod -aG docker deploy      # 재로그인 후 적용
docker --version && docker compose version && docker buildx version
```

- Ubuntu 저장소에 docker-compose-v2 · docker-buildx 패키지가 없을 때: Docker 공식 문서(docs.docker.com/engine/install/ubuntu)의 apt 저장소 절차 사용
- BuildKit 필수 사유: Dockerfile.dockerignore 자동 적용. `docker buildx version` 출력 확인 필수

### 7.2 코드 받기 [서버]

```bash
sudo mkdir -p /srv/forenode && sudo chown deploy:deploy /srv/forenode
git clone https://github.com/CalculusM/Forenode.git /srv/forenode/app
```

- 저장소 public = 인증 불필요. private 전환 시 배포 키(읽기 전용) 등록 필요 [대표]
- 전제: deploy/ 폴더가 main에 커밋·push된 상태 [대표 컨펌]

### 7.3 환경변수 [대표]

```bash
cd /srv/forenode/app/deploy
cp .env.example .env && chmod 600 .env
nano .env        # OPENAI_API_KEY 값은 대표가 직접 기입
```

- 비워 두면 법제 RAG 탭만 안내 문구 표시, 나머지 기능 정상(4.2 시험 조건과 동일)
- .env 사본은 대표 보관(서버 재구축 시 유일한 비밀 정보)

### 7.4 첫 빌드·기동 [서버]

```bash
cd /srv/forenode/app/deploy
docker compose up -d --build
docker compose ps            # STATUS 에 (healthy) 표시 확인, 최대 약 90초
```

- 버전 고정 파일 생성(첫 빌드 성공 직후 권장)
  ```bash
  docker compose exec -T app pip freeze > requirements.lock.txt
  ```
  - deploy/requirements.lock.txt 커밋 시 이후 빌드가 같은 버전 설치(Dockerfile 자동 분기) [대표 컨펌 후 커밋]
  - 커밋 경로: 대표 PC로 복사(`scp deploy@<공인IP>:/srv/forenode/app/deploy/requirements.lock.txt .`) 후 저장소에 커밋, 서버 사본은 삭제(다음 git pull 시 미추적 파일 충돌 방지)
  - 사유: requirements.txt 대부분 하한만 지정. 코드 내 `use_container_width` 71곳 · `st.components.v1.html` 1곳(ui_theme.py)이 Streamlit 제거 예고 API(로컬 1.56.0 실행 시 경고 확인) = 향후 재빌드 때 최신 Streamlit 설치로 화면 오류 가능

---

## 8. 배포

### 8.1 앱 확인 [서버 · 확인]

```bash
curl -s http://127.0.0.1:8501/_stcore/health              # ok
docker compose exec -T app python deploy/smoke_test.py     # 결과: 통과 (예외·환경 오류 합계 0건, SHAP 경고 1건은 기존 결함)
```

### 8.2 nginx 연결 [서버]

```bash
sudo cp /srv/forenode/app/deploy/nginx/forenode.conf /etc/nginx/sites-available/forenode
sudo sed -i 's/app.example.kr/<확보한 도메인>/g' /etc/nginx/sites-available/forenode
sudo ln -s /etc/nginx/sites-available/forenode /etc/nginx/sites-enabled/forenode
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

- 도메인 확보 전 임시 확인: server_name 을 `_` 로 두고 `http://<공인IP>/` 접속
- [확인] 브라우저 화면 로드 완료("Connecting..." 정지 없음) · 사이드바 입력 반응 · 페이지 4개 이동

---

## 9. 도메인·HTTPS

- 도메인 구입 [대표]: 비용 ✚ (등록기관·도메인 종류별 상이)
- DNS A 레코드 등록 [대표]: `<도메인> = <공인IP>`, 전파 확인 `dig +short <도메인>`
- 인증서 발급 [대표 실행, 약관 동의·이메일 입력 포함]
  ```bash
  sudo apt install -y certbot python3-certbot-nginx
  sudo certbot --nginx -d <도메인> --redirect
  ```
  - certbot이 nginx 설정에 443 블록·인증서 경로 추가, 80 요청을 443으로 전환
- [확인] `curl -I https://<도메인>/` 200 · 브라우저 자물쇠 표시 · 화면 정상 로드(웹소켓 wss 연결)
- HSTS: HTTPS 정상 확인 후 forenode.conf 의 Strict-Transport-Security 줄 주석 해제, `sudo nginx -t && sudo systemctl reload nginx`
- 갱신: certbot 타이머 자동 갱신(Let's Encrypt 인증서 90일). 점검 `systemctl list-timers | grep certbot`, `sudo certbot renew --dry-run`

---

## 10. 헬스체크

- 컨테이너: Dockerfile HEALTHCHECK, 30초 간격 · 제한 5초 · 기동 유예 90초 · 3회 연속 실패 시 unhealthy
  - 주의: Docker는 unhealthy 상태만으로 컨테이너를 재시작하지 않음. restart 정책은 프로세스 종료 시에만 작동
- 수동 확인
  - 서버 내부: `curl -s http://127.0.0.1:8501/_stcore/health`
  - 외부: `curl -s https://<도메인>/_stcore/health`
- 한계: /_stcore/health 의 ok는 서버 프로세스 정상만 의미, 앱 스크립트 오류는 `smoke_test.py` 로 확인
- 외부 감시(선택): keep-awake 워크플로를 헬스 감시용으로 전환하는 방안. 크론에서 `https://<도메인>/_stcore/health` 확인, 실패 시 GitHub 실패 알림 메일 수신 = 신규 계정 불필요 [대표 컨펌 후 워크플로 수정]

---

## 11. 로그

- 앱: `docker compose logs -f --tail 200 app` (json-file, 10MB×5개 순환, 최대 약 50MB)
- nginx: /var/log/nginx/access.log · error.log (Ubuntu logrotate 기본 적용)
- systemd 경로 사용 시: `journalctl -u forenode -f`

| 증상 | 주요 원인 | 조치 |
|---|---|---|
| 화면 "Connecting..." 정지 | 웹소켓 헤더 누락 · 프록시 타임아웃 | forenode.conf 의 Upgrade · Connection 헤더, proxy_read_timeout 확인 |
| 502 Bad Gateway | 컨테이너 미기동 또는 기동 중 | `docker compose ps`, `docker compose logs --tail 200 app` |
| PDF 한글 깨짐 | 폰트 미설치 | 빌드 로그의 fonts-nanum 설치 확인(누락 시 빌드 단계에서 실패하도록 검사 포함) |
| RAG 탭 "OPENAI_API_KEY가 설정되지 않았습니다" | .env 미기입 | .env 수정 후 `docker compose up -d` (컨테이너 재생성 필요, restart로는 환경변수 미반영) |
| 413 Request Entity Too Large | 업로드 상한 | forenode.conf 의 client_max_body_size |
| 빌드 중 프로세스 강제 종료 | 메모리 부족 | 6.2 스왑 설정 후 재빌드 |

---

## 12. 업데이트

- 표준 절차 [서버]
  ```bash
  cd /srv/forenode/app/deploy && bash update.sh
  ```
  - 자동 순서: 현재 이미지 보존(prev · 커밋 태그) · `git pull --ff-only` · 재빌드 · 재기동 · 헬스체크(최대 120초) · 스모크 시험
  - 어느 단계든 실패 시 prev 이미지로 자동 복귀, 소스 폴더는 원인 확인용으로 유지
- 수동 절차
  ```bash
  docker tag forenode-app:latest forenode-app:prev
  git -C /srv/forenode/app pull --ff-only
  docker compose up -d --build
  curl -s http://127.0.0.1:8501/_stcore/health
  docker compose exec -T app python deploy/smoke_test.py
  ```
- 서버에서 코드 직접 수정 금지(git pull 충돌 원인). 수정은 저장소 main 반영 후 pull
- 병행 기간 참고: main push 시 Streamlit Cloud도 재빌드됨(Streamlit Cloud 앱 삭제 전까지)

---

## 13. 롤백

- 이미지 롤백(빠름, 재빌드 없음)
  ```bash
  docker image ls forenode-app                        # prev · 커밋 태그 목록
  docker tag forenode-app:prev forenode-app:latest    # 또는 forenode-app:<커밋 7자리>
  docker compose up -d --no-build
  ```
- 소스 롤백
  ```bash
  git -C /srv/forenode/app checkout <커밋>
  docker compose up -d --build
  # 원인 수정 후 복귀: git -C /srv/forenode/app checkout main && bash update.sh
  ```
- 이미지 정리: `docker image prune` (태그 없는 이미지만 삭제). 디스크 50GB 기준 월 1회 `df -h` 점검
- systemd 경로: 이미지 롤백 불가, 소스 롤백 후 `pip install -r requirements.txt` 재실행 · `sudo systemctl restart forenode`

---

## 14. Docker 없는 대안 (systemd · venv)

- 파일: deploy/systemd/forenode.service (준비 명령 전체를 파일 상단 주석에 수록)
- 구성: /srv/forenode/app(코드) · /srv/forenode/venv(가상환경) · /etc/forenode/forenode.env(권한 600) · 실행 계정 forenode
- Docker 경로 대비 차이
  - 장점: Docker 설치 불필요, 메모리 부담 소폭 감소
  - 단점: 이미지 단위 롤백 불가 · OS 파이썬 버전 의존(Ubuntu 24.04 = 3.12, 22.04 = 3.10이면 3.11 이상을 요구하는 최신판 대신 구버전 설치 가능성) · apt 패키지(fonts-nanum · libgomp1) 수동 관리
- 업데이트
  - systemd 경로는 앱이 저장소 폴더에서 직접 실행되어 추적 파일 3종을 갱신함 = 서비스 정지 후 원복, 이후 pull(Docker 경로는 이미지 사본만 갱신되어 해당 없음)
    - chroma_db: chromadb가 열 때 sqlite 파일 갱신
    - data/interval_scores_v1.csv · data/interval_scores_full_v1.csv: pages/2 렌더마다 재작성. 내용은 저장소본과 같으나 줄끝이 CRLF로 바뀌어 수정 상태로 표시(검증 단계 대조 확인)
  ```bash
  sudo systemctl stop forenode
  sudo -u forenode git -C /srv/forenode/app checkout -- chroma_db data/interval_scores_v1.csv data/interval_scores_full_v1.csv
  sudo -u forenode git -C /srv/forenode/app pull --ff-only
  sudo -u forenode /srv/forenode/venv/bin/pip install -r /srv/forenode/app/requirements.txt
  sudo systemctl start forenode
  sudo -u forenode /srv/forenode/venv/bin/python /srv/forenode/app/deploy/smoke_test.py
  ```
- nginx 설정은 Docker 경로와 동일(127.0.0.1:8501 프록시)
- 두 경로 동시 사용 금지(포트 충돌)

---

## 15. 비용표 (월 기준, 부가세 별도)

| 구분 | 구성 | 월 비용 | 근거 · 비고 |
|---|---|---|---|
| 현행 | Streamlit Community Cloud | 0원 | 무료 · 비상업 한정 |
| 1안 서버 | 네이버클라우드 High CPU-g2 2vCPU·4GB · 기본 디스크 50GB | 69,120원 | 공식 요금표 2026-09-18 확인값(희망사다리 사용계획서 산출근거와 동일), 생성 전 콘솔 요금 재확인 필요 |
| 1안 공인 IP | 1개 | 약 4,088원 | 시간당 5.6원 × 730시간, 2026-09-18 확인값 |
| **1안 합계** | | **약 73,208원** | 산식 69,120 + 4,088. 부가세 포함 약 80,529원 |
| 1안 연간 | | 약 878,496원 | 월 합계 × 12. 부가세 포함 약 966,346원 |
| 1안 네트워크 | 외부 송신 트래픽 | ✚ | 무료 구간 · 초과 단가 콘솔 확인 필요 |
| 대안 가비아 | High CPU | 55,000원 + 스토리지 ✚ | 무약정, 트래픽 1TB 포함, 스토리지 별도(2026-09-18 확인값) |
| 대안 KT | 2vCPU·4GB급 | 79,500원 | 루트 디스크 20GB 포함(2026-09-18 확인값) |
| 대안 NHN Cloud | m2.c2m4 | 약 67,890원 + 디스크·IP ✚ | 시간당 93원 × 730시간, 디스크·IP 별도(2026-09-18 확인값). 스타트업 크레딧: 2025-05 보도 기준 1,000만원 즉시 지급 또는 최대 5,400만원 사용량 차등 지급 중 택1, 타 클라우드 사용 중 기업도 신청 가능, GPU · 일부 마켓플레이스 상품 제외. 2026년 지속 여부 · 세부 자격 ✚ |
| 공통 도메인 | 대표 선택 | ✚ | 등록기관별 상이 |
| 공통 인증서 | Let's Encrypt | 0원 | certbot 자동 갱신 |
| 공통 OpenAI API | RAG 사용량 비례 | ✚ | 호스팅 이전과 무관(현행과 동일) |

- NHN Cloud 크레딧 출처: 전자신문 2025-05-15 기사(etnews.com/20250515000398) 및 같은 시기 보도. 신청 전 NHN Cloud 공식 안내로 재확인 필요
- 사업자별 확인값 출처: 창업실습_3학년2학기/희망사다리_취창업지원금_사용계획서_초안_2026-09.md "조사 근거 요약"(2026-09-18, 공식 원문 확인)
- 지원금 사용계획 대조: 1안 6개월분 439,248원(73,208원 × 6), 부가세 포함 483,173원 = 사용계획서 금액과 일치

---

## 16. 이전 후 할 일 (권장 순서)

1. **병행 운영** [대표]: 새 주소 정상 확인 기간 설정, 기간 중 두 주소 모두 유지
2. **사이트·문서 링크 교체**: `forenode.streamlit.app` 을 새 주소로 교체 (2026-09-28 검색 결과)
   - Forenode_wiki/assets/site-public/index.html 3곳(191 · 209 · 450행) = 공개 사이트 원본
   - Forenode_wiki/assets/site/index.html 1곳(130행)
   - Forenode_wiki/05-Resources/forenode-proposal-2026.md 1곳(16행)
   - Forenode_wiki/05-Resources/outreach-email-templates-2026.md · assets/pitch_v13_video_and_script.md (streamlit.app 언급)
   - Forenode_wiki/assets/site-archive/ 3건(v2~v4) = 보관본, 교체 불요
   - README.md: streamlit.app 링크 없음(로컬 실행 안내만). 운영 주소 1줄 추가 권장
   - Netlify 재배포(`netlify deploy --prod`) [대표 컨펌]
   - 이미 발송된 메일 · 신청서 속 링크는 회수 불가 = Streamlit Cloud 앱 삭제 시점 판단에 반영
3. **keep-awake 크론 비활성화** [대표 컨펌]
   - `gh workflow disable keep-streamlit-awake.yml -R CalculusM/Forenode` 또는 워크플로 파일 삭제 커밋
   - 대안: 10장 헬스 감시 워크플로로 전환
4. **Streamlit Cloud 앱 처리** [대표, share.streamlit.io 대시보드]

   | 선택지 | 장점 | 단점 |
   |---|---|---|
   | 즉시 삭제 | 약관 리스크 · 미국 사본 즉시 해소 | 구 링크 즉시 불능 |
   | 병행 후 삭제(권장) | 링크 교체 · 재배포 완료 확인 후 전환 | 병행 기간 동안 비상업 약관 조건 유지 |
   | 유지 | 구 링크 유지 | 유료 전환 · 기관 제안 전 삭제 필요, 국내 체류 '적용' 전환 불가 |

5. **보안 1페이저 '국내 체류' 문구를 '목표'에서 '적용'으로 전환하는 시점**: 아래 조건 전부 충족 시
   - 국내 서버 운영 개시 및 사이트 링크 교체 완료
   - Streamlit Cloud 앱 삭제(미국 사본 소멸)
   - 텔레메트리 2종 비활성 확인: `docker compose exec app env | grep -E "GATHER_USAGE|TELEMETRY"`
   - 외부 전송 예외 명시: 법제 RAG 탭 질의 텍스트는 OpenAI API(미국)로 전송. 서버 .env에 키 미기입 시 해당 전송 없음
   - 소스 저장소(GitHub, 미국)는 고객 데이터 미포함 = 체류 대상 아님을 각주 처리
   - 수정 대상 위치: 보안아키텍처_1페이저.md §3의 3번 항목("데이터 국내 체류(data residency) 목표. 현행 데모는 해외 호스팅(미국 리전)") 및 §5 표 "데이터 국내 체류(목표)" 행
   - 문구 예시: "서비스 서버 국내 리전 운영(데이터 국내 체류 적용). 예외: 법제 RAG 탭 질의는 OpenAI API 전송(질의문 한정, 탭 비활성 가능)"
6. **내부 기록 갱신**: 호스팅 이전 P3 항목 완료 처리, 마케팅 사이트 TODO 반영

---

## 17. 알려진 위험·미검증 항목

1. **Linux 의존성 해석 미검증**(Docker 미설치로 로컬 빌드 불가)
   - requirements의 protobuf==3.20.3 고정 · 로컬 검증 환경은 protobuf 6.33.6(고정값과 불일치 상태로 동작)
   - chromadb 1.5.8이 요구하는 opentelemetry 계열 최신판은 protobuf 5 이상 요구 = pip가 구버전 opentelemetry로 역추적 필요
   - 같은 requirements로 Streamlit Cloud 앱 기동 중: 2026-09-28 05:32 UTC 크론 로그 "App awake", 페이지 제목 "Forenode: 민자 사업 발굴·제안 솔루션 엔진" 확인(앱 스크립트 실행 상태) = 해석 가능성 높음, 단 Streamlit Cloud 파이썬 버전 ✚ · pip 역추적으로 빌드 시간 증가 가능
   - 첫 빌드 실패 시 조치 후보: protobuf 고정 조정(Streamlit Cloud 조합과 달라지는 변경 = 대표 컨펌 사항)
2. **Streamlit 버전 미고정**: 제거 예고 API 사용(7.4). 첫 빌드 후 lock 파일 커밋으로 차단
3. **pages/4 시나리오 비교 PDF 한글**: 폰트 경로가 Windows 전용(C:/Windows/Fonts/malgun.ttf) = Linux 서버(현행 Streamlit Cloud 포함)에서 Helvetica 폴백, 한글 깨짐 추정. 수정 후보: report_generator.py의 한글 폰트 등록 함수 재사용(앱 코드 변경이라 본 패키지 범위 밖)
4. **IFC 업로드**: ifcopenshell Linux 휠의 형상 역산 동작 서버 미검증. 추출 중 예외 발생 시 /tmp 임시파일 삭제 누락 경로 존재(app.py 1450행 부근, 삭제가 try 블록 안쪽) = 컨테이너 재생성 시 소멸하나 무보존 원칙 관점 보완 후보
5. **unhealthy 자동 재시작 없음**(10장)
6. **단일 서버 구성**: 장애 복구 동안 서비스 중단. 앱 자체 저장 상태 없음(코드 = GitHub, 비밀 = .env) = .env 사본만 별도 보관 필요
7. **용량 미측정**: 동시 접속 한도 · RAG 사용 시 메모리 증가분 미측정(1세션 약 0.3GB만 실측)
8. **외부 노출 가능성**: 로컬 시험 시 Streamlit이 0.0.0.0 대기 표시. 서버에서는 compose 127.0.0.1 게시(Docker) · --server.address 127.0.0.1(systemd)로 차단
9. **XGBoost 탭 SHAP 분석 실패(기존 앱 결함)**: xgboost_tab.py render_shap_explanation 이 shap_values 를 3차원 배열로 가정, shap 0.51.0 은 2차원 반환. 화면에는 "SHAP 분석 실패" 오류 문구 표시, 나머지 기능 정상. 로컬 원본 환경에서도 재현 = 배포 무관. 수정은 앱 코드 변경이라 본 패키지 범위 밖(스모크 시험은 경고로만 출력)
10. **런타임 쓰기 파일 추가 발견 시**: 코드 폴더 읽기 전용 구성이므로 새 쓰기 경로는 화면 안 "Permission denied" 문구로 드러남. smoke_test.py 환경 오류 검사로 검출, Dockerfile 쓰기 예외 목록에 파일 단위 추가

---

## 18. 대표 몫 체크리스트

- [ ] deploy/ 폴더 커밋 · push 컨펌 (현재 미커밋)
- [ ] 클라우드 사업자 선택: 1안 네이버클라우드 · 가비아 · NHN Cloud(크레딧 조건 확인)
- [ ] NHN Cloud 크레딧 신청 여부 판단(선택 시 신청서 제출)
- [ ] 계정 생성 · 본인 인증 · 결제수단 등록 · 약관 동의
- [ ] 서버 생성(KR 리전 · Ubuntu 24.04 · 2vCPU·4GB) 및 인증키 보관
- [ ] 공인 IP 할당 · 인바운드 22(대표 IP) · 80 · 443 설정
- [ ] 초기 관리자 비밀번호 확인 · 변경
- [ ] 서버 .env 에 OPENAI_API_KEY 기입 또는 RAG 비활성 결정
- [ ] 도메인 구입 · DNS A 레코드 등록
- [ ] certbot 실행(약관 동의 · 이메일 입력)
- [ ] requirements.lock.txt 커밋 · push 컨펌
- [ ] 사이트 링크 교체 · Netlify 재배포 컨펌
- [ ] keep-awake 워크플로 비활성화(또는 헬스 감시 전환) 컨펌
- [ ] Streamlit Cloud 앱 삭제 시점 결정 · 실행
- [ ] 보안 1페이저 '국내 체류' 문구 전환 승인
