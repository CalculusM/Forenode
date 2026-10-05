# 카페24 가상서버 이전 보완 절차

- 작성일: 2026. 10. 5.(월)
- 적용 대상: 카페24 가상서버호스팅(리눅스) 자이언트(메모리 4GB·SSD 100GB), 운영체제 Ubuntu 22.04.
- 기준 문서: RUNBOOK_국내이전.md(2026. 9. 28.). 본 문서는 카페24·Ubuntu 22.04 차이 항목만 수록.
- 표기: [직접] 계정·결제·약관 동의·비밀번호 입력 등 직접 수행 항목. [서버] 서버 접속 후 명령 실행. ✚ 미확인 값.
- 상태: 서버 미구매, 명령 미실행. 아래 명령은 Ubuntu 22.04 저장소 패키지 존재 여부까지만 확인.

---

## 1. 카페24 상품 확인 결과(2026. 10. 5. 공식 페이지 열람)

| 항목 | 확인 결과 | 출처 |
|---|---|---|
| 제공 운영체제 | Rocky 8.x, Ubuntu 22.04 중 택일 | 가상서버호스팅 상품 표 |
| 가상 CPU 수 | 상품 표에 CPU 항목 없음 ✚ | 가상서버호스팅 상품 표 |
| 가상화 방식 | 명칭 미기재 ✚ | 상품 표·FAQ |
| 가상화 방식 정황 | 고객 직접 커널 삭제·GRUB 갱신 안내 FAQ 존재, '게스트 OS' 표현 사용. 완전 가상화 정황, 공식 명시 아님 | FAQ 'Ubuntu /boot 용량 확보', FAQ '보안 점검·아웃바운드 포트' |
| Docker 설치·운영 | 미기재 ✚ | 상품 표·FAQ |
| 관리자 권한 | root 권한 제공 | 상품 안내 문구 |
| 사전 설치 | 'OS와 APM 사전 설치' 문구 존재. 리눅스 상품 적용 범위 ✚ | 상품 안내 문구 |
| 설치 시간 | 결제 완료 후 30분 내 설치 | 상품 표 각주 |
| 요금(자이언트) | 월 33,000원(부가세 포함), 설치비 22,000원(부가세 포함) | 상품 표 |
| 기간 할인 | 6개월 5%, 12개월 10%, 24개월 12%, 36개월 15%, 120개월 20% | 상품 표 |
| 백업 | 기본 백업 없음, 고객 책임 | FAQ 'VPS 백업 지원' |
| 운영체제 초기화 | 서비스 최초 신청일 기준 7일 이내 무료, 이후 유료(금액 ✚) | FAQ 'VPS 백업 지원' |
| 사양 변경 | 하위 변경 불가. 일반형·비즈니스·퍼스트클래스 간 상향은 IP·데이터 유지. 자이언트 상향은 신규 서버 개통, IP 변경·데이터 삭제 | FAQ '하위 변경', FAQ '자이언트 변경' |
| 만료 | 만료 후 2주 보관, 이후 삭제·복구 불가 | FAQ '만료 시 자료 삭제' |
| 방화벽 | 운영체제 방화벽 및 카페24 관리 방화벽 병행. 나의서비스관리 > 방화벽 관리에서 수신·발신 규칙 직접 설정 | FAQ '방화벽 서비스' |
| 발신 포트 | 호스트 측 발신 포트 차단 없음 | FAQ '보안 점검·아웃바운드 포트' |
| 회선 | 서버 IP 회선 KT 또는 SK | FAQ '리버스 DNS' |
| 데이터센터 위치 | 리눅스 가상서버 상품 페이지 미기재 ✚ | 상품 페이지 |
| 동일 회사 타 상품 | '개발언어 VPS'(Ubuntu 24.04·Python 3.12)는 일본 데이터센터 명시, 월정액. 국내 체류 목적 부적합, 제외 | 개발언어 VPS 상품 페이지 |

- 출처 주소
  - 상품: https://hosting.cafe24.com/?controller=new_product_page&page=virtual
  - FAQ 분류: https://help.cafe24.com/faq/server-hosting/virtual-server-hosting/
  - 개발언어 VPS: https://hosting.cafe24.com/?controller=new_product_page&page=dev-vps

---

## 2. 운영체제 선택

### 2.1 선택: Ubuntu 22.04

- 사유: 기존 런북 apt 명령 그대로 사용 가능. Rocky 8.x는 dnf 체계, 본 패키지 미검증.
- 기본 파이썬: 3.10(jammy 저장소 python3 3.10.6).
- 필요 패키지 저장소 확인(packages.ubuntu.com, 2026. 10. 5. 열람)

| 패키지 | jammy 판 | 구역 |
|---|---|---|
| docker.io | 29.1.3-0ubuntu3~22.04.2(jammy-updates) | universe |
| docker-compose-v2 | 2.40.3+ds1-0ubuntu1~22.04.1(jammy-updates) | universe |
| docker-buildx | 0.30.1-0ubuntu1~22.04.1(jammy-updates) | universe |
| fonts-nanum | 20200506-1 | universe |

- 판정: 기존 런북 7.1절 설치 명령 Ubuntu 22.04에서 그대로 사용 가능. 단, universe 구역 활성 필수.

### 2.2 보안 지원 기간

- Ubuntu 22.04 표준 보안 지원 종료: 2027. 5. 말(ubuntu.com 2027. 5., endoflife.date 2027. 6. 1.).
- 확장 보안 유지(ESM) 종료: 2032. 4.~5.(Ubuntu Pro 가입 필요).
- 36개월 선납 시 만료 예상: 2029. 10. 전후. 표준 지원 종료 후 약 29개월 운영 구간 발생.
- 대응 후보
  1. 카페24 Ubuntu 24.04 제공 여부 문의(1:1 문의 문항 포함). 24.04 표준 지원 2029. 5. 말 종료.
  2. Ubuntu Pro 확장 보안 유지 적용. 개인 사용 최대 5대 무료(ubuntu.com). 사업 용도 무료 적용 여부 ✚, 계정 생성 [직접].
  3. 2027. 5. 이전 Ubuntu 24.04 재설치 및 재배포. 운영체제 초기화 비용 ✚, 사전 백업 필수.
- 참고: Rocky 8 보안 지원 2029. 5. 31. 종료(endoflife.date). 지원 기간은 길지만 본 런북 미적용.

---

## 3. 경로 판정

| 경로 | 적용 조건 | 앱 파이썬 | 판정 |
|---|---|---|---|
| 가. Docker(권장) | Docker 엔진 정상 기동(4.1절 시험 통과) | 3.12(컨테이너 이미지 고정, 호스트 3.10 무관) | 권장 |
| 나. venv + Python 3.12(deadsnakes) | Docker 불가 판정 시 | 3.12(이미지와 동일) | Docker 불가 시 1순위 |
| 다. venv + 기본 Python 3.10 | 외부 저장소 추가 불가 시 | 3.10 | 비권장, 최후 대안 |

### 3.1 Python 3.10 설치 시 패키지 상한(PyPI, 2026. 10. 5. 열람)

| 패키지 | 최신판 요구 파이썬 | 3.10 설치 가능 범위 |
|---|---|---|
| streamlit | 1.65.0: 3.10 이상 | 설치 가능(protobuf 고정에 따른 별도 상한, 3.2절) |
| numpy | 2.5.3: 3.12 이상, 2.3.0: 3.11 이상 | 2.2 계열 이하 |
| pandas | 3.0.6: 3.11 이상 | 2 계열 이하(정확한 상한 ✚) |
| scipy | 1.18.1: 3.12 이상 | 최신판 불가(정확한 상한 ✚) |
| scikit-learn | 1.9.1·1.8.0: 3.11 이상 | 1.7 계열 이하 |
| xgboost | 3.4.1·3.3.0: 3.12 이상, 3.2.0: 3.10 이상 | 3.2 계열 이하 |
| shap | 0.52.0: 3.12 이상, 0.51.0·0.50.0: 3.11 이상, 0.48.0: 3.9 이상 | 0.48 계열 이하(0.49 계열 ✚) |
| chromadb | 1.5.9: 3.9 이상 | 최신판 가능 |
| ifcopenshell | 0.9.0: 3.10 이상 3.16 미만 | 최신판 가능 |

- 판정: 요구 파이썬 기준 설치 가능. 실제 의존성 해석 결과 미검증 ✚.
- 한계: 로컬 검증 환경(Python 3.14.4, shap 0.51.0, xgboost 3.2.0)과 다른 판 조합. 화면 검증 재수행 필요.
- SHAP 반환 형태 차이: 목록·3차원·2차원 분기 코드 반영 완료(xgboost_tab.py). 판 차이 영향 없음.

### 3.2 공통 확인 사항(경로 무관)

1. protobuf==3.20.3 고정과 Streamlit 판
   - streamlit 1.65.0 요구 조건: protobuf 5.26.1 이상. streamlit 1.56.0 요구 조건: protobuf 3.20 이상.
   - 설치 결과: protobuf 3.20 허용 마지막 판까지 Streamlit 하향 선택. 설치 판 범위 1.56.0 이상 1.65.0 미만 추정 ✚.
   - 조치: 첫 설치 직후 `pip freeze` 판 기록(기존 런북 7.4절 lock 파일 절차 동일).
2. xgb_model.pkl 판 호환
   - 저장 시점 2026. 8. 7. 피클 파일. Docker·Python 3.12 경로 설치 예상 판 xgboost 3.4.1(로컬 3.2.0과 상이).
   - 불러오기 실패 시 화면 표시 문구 '모델 로드 실패: ...'. smoke_test.py 판정상 경고만 출력, 종료 코드 0 가능.
   - 조치: 스모크 시험 출력 경고 목록에서 '모델 로드 실패' 문구 유무 직접 확인. 발생 시 requirements.lock.txt의 xgboost 3.2.0 고정 후 재빌드.

---

## 4. 서버 준비(카페24 차이 항목)

### 4.1 최초 접속·가상화 확인 [직접·서버]

- 접속 정보 확인 [직접]: 나의서비스관리 화면. 초기 접속 방식(root 비밀번호 방식 추정) ✚.
- 최초 접속: `ssh root@<공인IP>`(Windows PowerShell 기본 ssh 사용 가능).
- 가상화·커널 확인

```bash
systemd-detect-virt          # kvm·xen·vmware·microsoft 계열 = 완전 가상화, openvz·lxc = 컨테이너형
uname -r                     # 커널 판
lsb_release -ds              # Ubuntu 22.04.x 확인
nproc && free -h && df -h /  # 가상 CPU 수·메모리·디스크 실측(1:1 문의 답변 대조)
```

- 판정 기준: 컨테이너형(openvz·lxc) 표시 시 Docker 경로 중단, 3절 나 경로 전환.
- 기한: 운영체제 초기화 무료 기간(최초 신청일 기준 7일) 안에 4.1~4.3절 완료.

### 4.2 사전 설치 서비스 점검 [서버]

- 사유: 'OS와 APM 사전 설치' 문구. 아파치 80 포트 점유 시 nginx 기동 실패.

```bash
sudo ss -ltnp | grep -E ':(80|443|3306|8501)\b' || echo "점유 포트 없음"
systemctl list-unit-files | grep -E '^(apache2|httpd|mysql|mariadb)' || echo "APM 미설치"
# 점유 확인 시(서비스 미사용 전제)
sudo systemctl disable --now apache2 mysql 2>/dev/null
```

### 4.3 관리 계정·접속 보안 [서버·직접]

- 기존 런북 6.2절 절차 동일(deploy 계정, 공개키 등록, 비밀번호 접속 차단, 보안 업데이트, 스왑 2GB).
- Windows PC 공개키 등록 예시(ssh-copy-id 미제공 환경)

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh deploy@<공인IP> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

- 시간대(선택): `sudo timedatectl set-timezone Asia/Seoul`.

### 4.4 방화벽 [직접·서버]

- 기존 런북 6.1절 네이버클라우드 ACG 규칙을 카페24 관리 방화벽 규칙으로 대체.

| 방향 | 포트 | 허용 출처 | 용도 |
|---|---|---|---|
| 수신 | 22/TCP | 접속 PC 공인 IP/32 | SSH |
| 수신 | 80/TCP | 전체 | HTTP, 인증서 발급 |
| 수신 | 443/TCP | 전체 | HTTPS |

- 설정 위치 [직접]: 나의서비스관리 > 방화벽 관리.
- 운영체제 방화벽 이중화(선택): 기존 런북 6.2절 ufw 명령 동일. 22번 허용 규칙 선등록 후 활성화.
- 8501 포트: 외부 미개방 유지(compose 127.0.0.1 게시, systemd 127.0.0.1 대기).

---

## 5. 가 경로: Docker 설치(Ubuntu 22.04)

```bash
# universe 구역 활성 확인. Candidate 값이 (none)이면 universe 추가
apt-cache policy docker.io docker-compose-v2 docker-buildx | grep -E '^[a-z]|Candidate'
sudo add-apt-repository -y universe && sudo apt update     # Candidate (none) 시에만

sudo apt install -y git curl nginx docker.io docker-compose-v2 docker-buildx
sudo usermod -aG docker deploy                              # 재로그인 후 적용
docker --version && docker compose version && docker buildx version

# Docker 구동 시험(이미지 1건 내려받기 발생)
sudo docker run --rm hello-world
```

- 판정: hello-world 출력 정상 시 Docker 경로 확정. 이후 기존 런북 7.2절(코드 받기)부터 동일 진행.
- 실패 시: `sudo systemctl status docker`, `sudo journalctl -u docker --no-pager | tail -50` 기록 후 나 경로 전환.
- Docker 공식 저장소(docker-ce) 대안: docs.docker.com/engine/install/ubuntu, Ubuntu 22.04 지원 목록 포함.

---

## 6. 나 경로: venv + Python 3.12(deadsnakes) + systemd

- deadsnakes 저장소: Ubuntu 22.04용 Python 3.12 제공. 저장소 안내상 보안 업데이트 적시성 미보장.
- systemd 유닛: deploy/systemd/forenode.service 그대로 사용(venv 경로 /srv/forenode/venv 동일).

```bash
# 1) 저장소·패키지
sudo apt install -y software-properties-common
sudo add-apt-repository -y universe
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev build-essential \
                    git nginx fonts-nanum libgomp1 tzdata
python3.12 --version
test -f /usr/share/fonts/truetype/nanum/NanumGothic.ttf && echo "나눔고딕 확인"

# 2) 실행 계정·폴더
sudo useradd --system --home-dir /srv/forenode --shell /usr/sbin/nologin forenode
sudo mkdir -p /srv/forenode /etc/forenode && sudo chown forenode:forenode /srv/forenode
sudo -u forenode git clone https://github.com/CalculusM/Forenode.git /srv/forenode/app

# 3) 가상환경(기본 python3 대신 python3.12 지정)
sudo -u forenode python3.12 -m venv /srv/forenode/venv
sudo -u forenode /srv/forenode/venv/bin/python --version          # 3.12.x 확인
sudo -u forenode /srv/forenode/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u forenode /srv/forenode/venv/bin/pip install -r /srv/forenode/app/requirements.txt
sudo -u forenode /srv/forenode/venv/bin/pip freeze > /tmp/forenode_freeze.txt   # 설치 판 기록

# 4) 환경변수 파일(키 값은 서버에서 직접 기입)
sudo install -m 600 -o root -g root /srv/forenode/app/deploy/.env.example /etc/forenode/forenode.env
sudo nano /etc/forenode/forenode.env                                # [직접] OPENAI_API_KEY 기입 또는 공란 유지

# 5) 서비스 등록·기동
sudo cp /srv/forenode/app/deploy/systemd/forenode.service /etc/systemd/system/forenode.service
sudo systemctl daemon-reload && sudo systemctl enable --now forenode
systemctl status forenode --no-pager
curl -s http://127.0.0.1:8501/_stcore/health                       # ok

# 6) 스모크 시험(경고 목록의 '모델 로드 실패' 문구 확인)
cd /srv/forenode/app && sudo -u forenode /srv/forenode/venv/bin/python deploy/smoke_test.py
```

- nginx·도메인·HTTPS: 기존 런북 8.2절·9장 동일.
- 업데이트·롤백: 기존 런북 14장 systemd 절차 동일(추적 파일 3종 원복 후 pull).

### 6.1 다 경로(기본 Python 3.10) 차이

- 1)의 deadsnakes 추가 및 python3.12 계열 설치 대신 `sudo apt install -y python3-venv python3-dev`.
- 3)의 `python3.12 -m venv` 대신 `python3 -m venv`.
- 설치 판: 3.1절 상한 적용. 화면 검증(기존 런북 8.2절 확인 항목) 전 페이지 재수행 필수.

---

## 7. 1:1 문의 답변별 분기

| 답변 | 조치 |
|---|---|
| 데이터센터 국외 | 구매 중단, 국내 체류 목적 불충족 |
| Docker 운영 불허 또는 컨테이너형 가상화 | 나 경로 확정 |
| Ubuntu 24.04 제공 | 24.04 선택. 기본 Python 3.12, 기존 런북 원안 그대로 적용, 2.2절 대응 불요 |
| APM 미설치 선택 가능 | 미설치 선택, 4.2절 생략 |
| 자이언트 가상 CPU 1개 | 사양 유지(1명 접속 실측 최대 메모리 322MB, 메모리 기준 선정). 동시 접속 시 응답 지연 여부 개통 후 측정 |

---

## 8. 미확인 항목(✚) 목록

1. 자이언트 가상 CPU 수.
2. 가상화 방식 명칭.
3. Docker 설치·운영 허용 여부.
4. 데이터센터 국내 위치.
5. 'OS와 APM 사전 설치' 리눅스 상품 적용 범위.
6. 초기 접속 방식(root 비밀번호 또는 키).
7. 운영체제 초기화 비용(신청 7일 경과 후).
8. Ubuntu 24.04 제공 여부.
9. Ubuntu Pro 사업 용도 무료 적용 여부.
10. Python 3.10 경로 pandas·scipy 정확한 설치 상한.
11. protobuf 3.20.3 고정 조건 Streamlit 설치 판.
