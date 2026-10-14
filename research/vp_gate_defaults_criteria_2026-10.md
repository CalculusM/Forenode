# 기본값·계산 경로 VP 게이트 묶음 판정 기준 (계산 전 봉인)

- 작성일: 2026. 10. 14.(화).
- 문서 성격: 앱 반영 방안 P-11(가·나·라·마)·P3-01 준비 단계의 3안 비교 판정 기준. 평가 계산 전 작성, 별도 커밋 봉인.
- 적용 범위: 판정 근거 산출만. 엔진·기본값·config 변경 0건. 채택 권고가 나와도 반영은 VP 게이트(골든 재생성 단독 커밋)·대표 승인·2027. 1. 8. 이후.
- 변경 규칙: 커밋 이후 본 문서 기준 변경 없음. 불가피한 변경은 새 문서로만 기록.
- 입력 파일: config/finance_params.json(fiscal_toll_structure·toll_benchmark·business_type_defaults·capacity_gate), tests/_helpers.py(app_default_case·threshold_traffic·TRAFFIC_ANCHOR_RATIO), 스터디 raw(03_forenode_test_inputs_v3.json, 03_five_input_inputs.json, 04_forenode_test_results_v3.json, 04_five_input_results.json, 11_capex_sensitivity.json, R_koti_local.md).
- 평가 스크립트: research/vp_gate_defaults_eval_2026_10.py. 결과 문서: research/vp_gate_defaults_result_2026-10.md.

## 0. 봉인 시점 열람 범위

- 스터디 6판 본문 2절·6절·7절, 앱 반영 방안(0절·2절·5절·7절) 열람 완료. 7절 대조 2의 서술(고속도로형 6건 환산값 ±2~7원, 지하·소형차 3건 50~68% 과소)은 봉인 전 인지 상태. 가안 판정 결과 사실상 예견 가능.
- raw/11_capex_sensitivity.json 구조 열람 완료(74건 = 2절 19건×3배수 + 7절 15건×1.2 + 85원 기준선 2건). 수치 대조는 미실행.
- R_koti_local.md 열람 완료. 1.13-10항(RR-22-18 p.113 운영기간 30년 이상, 표준실시협약 제10조 30년)은 봉인 전 인지 상태. 나안 판정 결과 사실상 예견 가능.
- opex_estimator.py·config/opex_params.json 열람 완료(터널 계수 위치 확인 목적).
- 3안 평가 계산·엔진 호출 전부 미실행.

## 1. 공통 규칙

- 숫자 상수는 config·data·raw 파일에서 읽기. 스크립트 내 스터디 결과·요금 구조·앵커·용량 숫자 고정 0건. 판정 기준값(아래 각 절의 문턱)만 스크립트 상수로 두고 본 문서 절 번호를 주석으로 연결.
- 판정 라벨 3종: 채택 권고(대표 결정 대기) / 근거 부족 / 보류(VP 게이트 상정). 어느 라벨이든 기본값 변경 0건.
- 결과 문서에 '기본값 변경 없음' 명기. 스터디 성립 조건 구분(A·B·C)은 인용하지 않음.
- 지하·소형차 전용 노선 요금은 어떤 기본값 안에서도 노선 요금 입력 필수(P-02 체크박스·P-05 경고 유지).

## 2. 가안: 통행료 기본값 3안

### 2-1. 대상·입력

- 대상 9건: 스터디 7절 1-다 통행료 확보 9건. 03_five_input_inputs.json의 toll_reported 가운데 보도·추정·공고 상한 계산값 9건(명단 고정).
  - 고속도로형 6건: 팔공산 관통, 영동~오창, 서평택~봉담, 서울~양주, 익산~부여(서부내륙 2단계), 평택~시흥 확장(개량운영형).
  - 지하·소형차 전용 3건: 제4경인 고속화도로, 양재~올림픽대로 지하도로, 우면~용산 지하도로.
- 교차 확인: 03_forenode_test_inputs_v3.json의 toll_reported 6건과 값 일치(불일치 시 결과 문서에 기록, 판정은 five_input 값 기준).
- 연장: 03_five_input_inputs.json의 road_length(요금 근거와 같은 연장 기준).
- 비교 대상 요금: toll_reported(원/km). 보도·추정·계산값 혼재, 출처 등급은 결과 표에 병기.

### 2-2. 3안 정의

- A 현행: business_type_defaults[사업유형].toll 고정(현행 자동값).
- B 재정요금 구조×배수: threshold_display.fiscal_toll_per_km(연장, fiscal_toll_structure.base_won, fiscal_toll_structure.per_km_won_class1, toll_benchmark.policy_cap_mult).
- C 재정요금 구조×1.0: 같은 함수, 배수 1.0.

### 2-3. 지표·판정 규칙

- 지표: 군별 평균 절대 오차(MAE, 원/km)와 최대 절대 오차(원/km). 오차 = 안의 요금 − toll_reported.
- B 또는 C의 채택 권고 조건(전부 충족).
  - G1 고속도로형 6건 MAE가 A 대비 5.0원/km 이상 개선.
  - G2 지하·소형차 3건 MAE가 A보다 크지 않음.
- B·C 모두 충족 시: 고속도로형 MAE가 낮은 안. 두 안의 차이가 1.0원/km 미만이면 B(배수 1.1은 toll_benchmark.note에 출처 기재, 1.0은 정책 근거 없음).
- 어느 안도 미충족: 근거 부족, A 유지.
- 지하·소형차 3건은 어떤 안에서도 요금 입력 필수 규칙 병행. 군별 결과는 '기본값이 노선 요금을 대신할 수 없음'의 근거로만 사용.

## 3. 나안: BTO-a 운영기간 기본 30년에서 40년

### 3-1. 근거표

- 03_forenode_test_inputs_v3.json에서 business_type이 BTO-a인 노선의 operation_years와 basis.op.
- 출처 등급 분류(basis.op 문자열 키워드): 1차·공고 = 공고·민투심·요약문·협약 포함, 보도 = 보도 포함(가정 미포함), 가정 = 가정 포함(1차·공고 키워드 없을 때). 가정 등급은 집계 제외.
- KOTI 대조: R_koti_local.md에서 운영기간 표준을 명시한 문장(1.13-10항). 40년을 표준으로 명시한 1차 문서 유무.

### 3-2. 판정 규칙

- 채택 권고 조건(전부 충족).
  - N1 1차·공고 등급으로 40년 이상이 확인되는 BTO-a 노선 8건 이상.
  - N2 1차 문서(민간투자사업기본계획 또는 KOTI 보고서)가 40년을 표준 운영기간으로 명시.
- 미충족 시 근거 부족. 보도 등급 건수는 참고 수치로만 기록.

## 4. 라안: 성장 경로 용량 상한

### 4-1. 측정

- 대상: tests/_helpers.app_default_case() 기본 사례(운영 30년) 및 운영 40년 사례. 성장률 APP_DEFAULT_INPUTS.growth_pct, 한계 capacity_gate.limit_by_lanes[차로].
- 산출: 재무 성립선 문턱 경로(문턱×성장)와 권장 수요 경로(app_default_case daily_traffic×성장)가 한계를 처음 초과하는 운영 연차, 30·40·50년차 배수((1+성장률)^(연차−1)).

### 4-2. 3안 정의(스크립트 내 지역 재구현, 엔진 미변경)

- A 현행: 무상한 성장. reverse_solver.min_revenue_for와 같은 값. 지역 재구현의 패리티 확인(1대 이내).
- B 연도별 상한: 후보 교통량 T의 경로를 연도별 min(T×(1+g)^(y−1), 한계)로 자르고 revenue_series_억으로 app.build_cashflow에 전달. T 이분법.
- C 한계 도달 후 성장 0: 권장 수요 경로가 한계를 처음 초과하는 연차 y*를 고정, 모든 후보 경로의 성장 계수를 (1+g)^(min(y, y*)−1)로 둠. T 이분법.
- 공통: 운영비 시계열은 base_params 값 고정(현행 역산 규약, 교통량이 줄어도 운영비 불변). 판정 함수 gov(수입/비용 현가비율 1.0 이상·NPV 0 이상).
- B에서 한계 평탄 경로(모든 연도 한계)로도 미성립이면 '용량 내 미성립'으로 표기하고 평탄 경로 필요 수입을 이분법으로 구해 필요 요금(현행 요금×필요 수입÷평탄 수입)을 병기. C에서 T가 한계를 넘으면 threshold_display.required_toll_at_capacity로 필요 요금 병기.

### 4-3. 판정 규칙

- 기본 사례에서 B 또는 C 문턱이 A 대비 5% 이상 이동(또는 용량 내 미성립): 보류(VP 게이트 상정, 2027. 1. 8. 이후 묶음). 상정 시 우선안은 B(연도별 상한이 용량 게이트 정의와 일치).
- 5% 미만: 보류(영향 미미, 캡션 고지로 갈음).
- 채택 권고는 본 단계에서 내지 않음(골든 전면 변경 항목).

## 5. 마안: 운영비 시계열 앵커 의존

### 5-1. 측정

- 비단조 점검: 11_capex_sensitivity.json을 입력 세트별(2절 v3 재정요금 구조 19건×배수 0.8·1.0·1.2·1.4, 7절 five 15건×배수 1.0·1.2)로 묶고 같은 세트 안에서 사업비 배수 증가에 문턱이 감소하는 쌍의 수. 1.0 배수는 04_forenode_test_results_v3.json(flat 제외)·04_five_input_results.json에서 읽음.
- 앱 반영 방안 7절 1에 인용된 비단조 쌍 3건(용인~충주, 태안~안성, 서창~김포)의 양쪽 입력 세트·요금을 표로 대조.
- 기울기 꺾임: v3 세트 노선별 (문턱1.2−문턱1.0)÷(문턱1.0−문턱0.8)과 각 배수의 recommended_exceeds_capacity_limit.
- 용인~충주 정량: 04_forenode_test_results_v3.json(재정요금 구조)·04_five_input_results.json(85원)의 inputs와 11_capex_sensitivity.json ×1.2 inputs로 app_default_case 호출, base_params['opex_series_억'] 합계·앵커(daily_traffic·anchor_capped)·gov 문턱을 기준 대 +20%로 대조.

### 5-2. 3안 정의

- A 현행 유지+단서: 계산 불변. 캡션에 '운영비 규모는 권장 수요 앵커(용량 상한 적용) 기준' 고지.
- B 문턱 수렴값 고정점 반복: 운영비 시계열을 앵커 수입이 아니라 직전 반복의 문턱 수입에서 산출, |문턱 변화| 1대 미만까지 반복(최대 20회). 기본 사례·용인~충주 4사례에 지역 재구현으로 적용.
- C 원단위 밴드(OPEX v2): 실측 원단위 14점 이상 축적 후 시설유형 밴드(forward-registry/v2-overcoming-design 3절). 본 단계 계산 불가.

### 5-3. 판정 규칙

- 같은 세트 안 비단조 쌍 0건이면 '비단조' 서술은 입력 세트 혼용 결과로 기록하고, 앵커 의존의 실측 근거는 기울기 꺾임·운영비 합계 변화로 대체.
- B의 VP 게이트 상정 조건(전부 충족): 5사례 전부 20회 안에 수렴, 용인~충주 v3 세트에서 기울기 비율이 A보다 1.0에 가까움.
- C는 원단위 점수 14점 미만이면 근거 부족.
- 종합: B 조건 충족 시 보류(VP 게이트 상정, 라안과 묶음), 미충족 시 A 유지(단서 캡션은 P-13으로).

## 6. P3-01: 터널 비율 70% 상한·운영비 터널 계수

### 6-1. 측정

- 대상 4건: 03_forenode_test_inputs_v3.json에서 basis.structure에 '터널 70% 상한'이 적힌 노선(사상~해운대, 구리~성남, 시흥~송파, 제2용인~서울). 실제 비율은 basis.structure의 백분율 표기에서 읽음.
- 04_forenode_test_results_v3.json의 해당 노선 inputs(요금 시나리오별)로 app_default_case를 호출해 기록된 gov 문턱 재현(1대 이내). 같은 inputs에서 tunnel_ratio만 실제 비율로 바꿔 재실행, 차이(대·%) 산출. 엔진은 비율 상한 없음(상한은 화면 슬라이더 _TUNNEL_MAX).
- 터널 계수 출처 점검: opex_estimator._route_adjustment의 계수 값·근거 문장, config/opex_params.json의 노선 보정 키 유무.

### 6-2. 판정 규칙

- 상한 상향 채택 권고 조건(전부 충족): 터널 운영비 원단위 근거(실측 원단위 또는 공표 단가) 존재, 터널 계수가 config 키로 외부화되고 출처 기재.
- 근거 없으면 근거 부족. 허용 조치는 캡션 고지(P-13)뿐. 차이 수치는 '과소 반영 폭'의 참고값으로만 기록.

## 7. 판정 순서

- 가·나 근거 산출, 라·마 지역 재구현 패리티 확인 후 3안 산출, P3-01 재현·재실행, 결과 문서 작성. 기준 변경 0건.
