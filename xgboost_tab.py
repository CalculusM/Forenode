"""
============================================================
ROADx Phase 3 - XGBoost 수익성 등급 예측 탭
============================================================
역할:
  - 학습된 XGBoost 모델로 신규 사업의 A/B/C 등급 예측
  - 등급 분류 기준을 명시 (발표·시연용)
  - SHAP 기반 해석 (왜 그 등급인지 설명)
  - 학습 데이터 정보 표시 (LOOCV 정확도 등)

사용법:
  1. 이 파일을 app.py와 같은 폴더에 두기 (xgboost_tab.py)
  2. 같은 폴더에 다음 파일들 필요:
     - xgb_model.pkl
     - xgb_features.json
     - financial_labeled.csv
  3. app.py 상단에 import:
       from xgboost_tab import render_xgboost_tab
  4. 9번째 탭 추가:
       tabs = st.tabs([..., "🎯 수익성 등급"])
       with tabs[8]:
           render_xgboost_tab()
============================================================
"""
import json
import pickle
import csv
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


# ════════════════════════════════════════════════════════════
# 등급 분류 기준 (발표·시연용 - 사용자에게 명시 필수)
# ════════════════════════════════════════════════════════════
GRADE_CRITERIA = {
    "A": {
        "name": "우량",
        "color": "#1D9E75",
        "description": "안정적 수익 + 충분한 상환 능력",
        "conditions": [
            ("영업이익률", "≥", 0.15, "%", 15),
            ("DSCR_근사", "≥", 1.30, "배", 1.30),
            ("부채비율", "≤", 4.00, "배", 4.00),
        ],
        "logic": "AND (모두 충족)",
    },
    "B": {
        "name": "양호",
        "color": "#EF9F27",
        "description": "정상 운영, 일부 지표 약함",
        "conditions": [
            ("영업이익률", "≥", 0.05, "%", 5),
            ("DSCR_근사", "≥", 1.00, "배", 1.00),
            ("부채비율", "≤", 6.00, "배", 6.00),
        ],
        "logic": "AND (모두 충족, A 미달)",
    },
    "C": {
        "name": "주의",
        "color": "#E24B4A",
        "description": "적자 또는 상환 부담 과다",
        "conditions": [
            ("영업이익률", "<", 0.00, "%", 0),
            ("DSCR_근사", "<", 1.00, "배", 1.00),
            ("이자보상배율", "<", 1.00, "배", 1.00),
            ("부채비율", ">", 6.00, "배", 6.00),
        ],
        "logic": "OR (하나라도 해당)",
    },
}


# 입력 슬라이더 정의 (사용자가 조정할 핵심 지표)
INPUT_SLIDERS = [
    # (key, label, min, max, default, step, help)
    ("영업이익률", "영업이익률 (%)", -50.0, 60.0, 12.0, 0.5,
     "영업이익 / 영업수익 × 100. A등급 기준 15% 이상."),
    ("순이익률", "순이익률 (%)", -50.0, 50.0, 8.0, 0.5,
     "당기순이익 / 영업수익 × 100. 영업이익률보다 낮으면 금융비용 부담 큼."),
    ("DSCR_근사", "DSCR 근사 (배)", 0.0, 5.0, 1.25, 0.05,
     "(영업이익+감가상각비) / 이자비용. A등급 1.30 이상, B등급 1.00 이상."),
    ("부채비율", "부채비율 (배)", 0.0, 15.0, 3.5, 0.1,
     "부채총계 / 자본총계. A등급 4.0배 이하, B등급 6.0배 이하."),
    ("이자보상배율", "이자보상배율 (배)", 0.0, 10.0, 1.8, 0.1,
     "영업이익 / 이자비용. 1.0 미만 시 영업이익으로 이자도 못 내는 위험 신호."),
    ("ROA_총자산수익률", "ROA (%)", -10.0, 15.0, 3.0, 0.1,
     "당기순이익 / 자산총계 × 100. 자산 효율성 지표."),
]


# ════════════════════════════════════════════════════════════
# 캐싱: 모델은 한 번만 로드
# ════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="XGBoost 모델 로드 중...")
def load_model():
    """학습된 XGBoost 모델과 메타 정보 로드"""
    model_path = Path("./xgb_model.pkl")
    features_path = Path("./xgb_features.json")
    
    if not model_path.exists():
        return None, "xgb_model.pkl 없음 - financial_xgboost.py 먼저 실행"
    
    if not features_path.exists():
        return None, "xgb_features.json 없음 - fix_json.py 실행"
    
    try:
        with open(model_path, "rb") as f:
            saved = pickle.load(f)
        
        with open(features_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        
        return {
            "model": saved["model"],
            "feature_cols": saved["feature_cols"],
            "grade_map": saved["grade_map"],
            "grade_reverse": saved["grade_reverse"],
            "meta": meta,
        }, None
        
    except Exception as e:
        return None, f"모델 로드 실패: {e}"


@st.cache_data
def load_labeled_data():
    """학습된 59건 데이터 로드 (벤치마크 비교용)"""
    csv_path = Path("./financial_labeled.csv")
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        return df
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 예측 함수
# ════════════════════════════════════════════════════════════
def predict_grade(model_obj, user_inputs):
    """사용자 입력 → 등급 예측"""
    model = model_obj["model"]
    feature_cols = model_obj["feature_cols"]
    grade_reverse = model_obj["grade_reverse"]
    
    # 학습된 18개 feature 중 사용자 입력 6개만 채우고 나머지는 평균값
    feature_vec = np.zeros(len(feature_cols))
    
    # 평균값 사용 (학습 데이터의 대표값)
    df = load_labeled_data()
    if df is not None:
        for i, col in enumerate(feature_cols):
            if col in df.columns:
                values = pd.to_numeric(df[col], errors="coerce").dropna()
                if len(values) > 0:
                    feature_vec[i] = values.median()
    
    # 사용자 입력으로 덮어쓰기 (% 단위는 소수로 변환)
    for key, value in user_inputs.items():
        if key in feature_cols:
            idx = feature_cols.index(key)
            # %는 소수 형태로 저장됨
            if key in ["영업이익률", "순이익률", "ROA_총자산수익률", "ROE_자기자본수익률"]:
                feature_vec[idx] = value / 100.0
            else:
                feature_vec[idx] = value
    
    X_pred = feature_vec.reshape(1, -1)
    
    # 예측
    pred_class = model.predict(X_pred)[0]
    pred_proba = model.predict_proba(X_pred)[0]
    
    grade = grade_reverse.get(int(pred_class), "?")
    proba_dict = {grade_reverse[i]: float(p) for i, p in enumerate(pred_proba)}
    
    return grade, proba_dict, X_pred, feature_vec


def calculate_shap_explanation(model_obj, X_pred):
    """SHAP 값 계산 (가능한 경우)"""
    try:
        import shap
        explainer = shap.TreeExplainer(model_obj["model"])
        shap_values = explainer.shap_values(X_pred)
        # multi-class: list of arrays or 3D array
        return shap_values, explainer
    except Exception:
        return None, None


# ════════════════════════════════════════════════════════════
# UI 렌더링
# ════════════════════════════════════════════════════════════
def render_grade_criteria_box():
    """등급 분류 기준 명시 박스"""
    st.markdown("### 📋 등급 분류 기준")
    
    cols = st.columns(3)
    for i, (grade, info) in enumerate(GRADE_CRITERIA.items()):
        with cols[i]:
            conditions_html = "<br>".join([
                f"• {c[0]} {c[1]} {c[3] if c[3] != '%' else f'{c[4]}%'}"
                for c in info["conditions"]
            ])
            
            st.markdown(
                f"""<div style="background: {info['color']}15;
                                border-left: 4px solid {info['color']};
                                padding: 14px 18px;
                                border-radius: 6px;
                                min-height: 180px;">
                    <div style="font-size: 18px; font-weight: 600; 
                                color: {info['color']}; 
                                margin-bottom: 4px;">
                        {grade}등급 · {info['name']}
                    </div>
                    <div style="font-size: 12px; color: #666;
                                margin-bottom: 10px;">
                        {info['description']}
                    </div>
                    <div style="font-size: 13px; color: #1a1a2e;
                                line-height: 1.7;">
                        {conditions_html}
                    </div>
                    <div style="font-size: 11px; color: #999;
                                margin-top: 10px;
                                font-style: italic;">
                        조건: {info['logic']}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )


def render_model_info(meta):
    """학습 모델 정보 박스"""
    info_cols = st.columns(4)
    
    with info_cols[0]:
        st.metric(
            "학습 데이터",
            f"{meta.get('n_original', 0)}건",
            help="민자고속도로 13개사 5년치 감사보고서"
        )
    
    with info_cols[1]:
        st.metric(
            "SMOTE 후",
            f"{meta.get('n_train', 0)}건",
            help="B 클래스 합성 추가 (불균형 처리)"
        )
    
    with info_cols[2]:
        loocv = meta.get('loocv_accuracy', 0)
        st.metric(
            "LOOCV 정확도",
            f"{loocv:.1%}",
            help="Leave-One-Out Cross-Validation - 작은 샘플 최적 검증"
        )
    
    with info_cols[3]:
        train = meta.get('train_accuracy', 0)
        st.metric(
            "학습 정확도",
            f"{train:.1%}",
            help="학습 데이터에서의 분류 정확도"
        )


def render_prediction_result(grade, proba_dict):
    """예측 결과 표시"""
    info = GRADE_CRITERIA.get(grade, {})
    color = info.get("color", "#999")
    name = info.get("name", "분류불가")
    desc = info.get("description", "")
    
    st.markdown(
        f"""<div style="background: linear-gradient(135deg, 
                        {color} 0%, 
                        {color}cc 100%);
                    color: white;
                    padding: 24px 28px;
                    border-radius: 10px;
                    text-align: center;
                    margin: 16px 0;">
            <div style="font-size: 14px; opacity: 0.85; 
                        margin-bottom: 6px;">
                XGBoost 예측 결과
            </div>
            <div style="font-size: 48px; font-weight: 700;
                        margin: 8px 0;">
                {grade}등급
            </div>
            <div style="font-size: 18px; opacity: 0.95;">
                {name} — {desc}
            </div>
        </div>""",
        unsafe_allow_html=True
    )
    
    # 확률 막대
    st.markdown("**🎲 등급별 예측 확률**")
    proba_cols = st.columns(3)
    for i, g in enumerate(["A", "B", "C"]):
        prob = proba_dict.get(g, 0)
        c = GRADE_CRITERIA[g]["color"]
        with proba_cols[i]:
            st.markdown(
                f"""<div style="text-align: center; padding: 12px;
                                background: {c}10; border-radius: 6px;
                                border-top: 4px solid {c};">
                    <div style="font-size: 13px; color: #666;">
                        {g}등급 ({GRADE_CRITERIA[g]['name']})
                    </div>
                    <div style="font-size: 28px; font-weight: 600;
                                color: {c};">
                        {prob:.1%}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )


def render_shap_explanation(model_obj, X_pred, feature_vec, predicted_grade):
    """SHAP 기반 설명 — 어느 변수가 결정적이었는지"""
    try:
        import shap
    except ImportError:
        st.info("SHAP 라이브러리 미설치 - `pip install shap` 후 사용 가능")
        return
    
    try:
        explainer = shap.TreeExplainer(model_obj["model"])
        shap_values = explainer.shap_values(X_pred)
        
        # 예측된 등급의 SHAP 값
        grade_idx = model_obj["grade_map"].get(predicted_grade, 0)
        
        # 멀티클래스 처리
        if isinstance(shap_values, list):
            sv = shap_values[grade_idx][0]
        else:
            sv = shap_values[0, :, grade_idx]
        
        feature_cols = model_obj["feature_cols"]
        
        # SHAP 값 + feature 값 페어
        shap_data = []
        for i, name in enumerate(feature_cols):
            shap_data.append({
                "변수": name,
                "값": feature_vec[i],
                "SHAP": float(sv[i]),
                "abs_SHAP": abs(float(sv[i]))
            })
        
        # 절대값 기준 정렬, 상위 8개
        shap_data.sort(key=lambda x: x["abs_SHAP"], reverse=True)
        top_data = shap_data[:8]
        
        st.markdown(f"### 🔍 왜 {predicted_grade}등급인가? (SHAP 분석)")
        st.caption(
            f"각 변수가 {predicted_grade}등급 예측에 기여한 정도를 표시합니다. "
            "양수는 그 등급으로 가게 만든 요인, 음수는 멀어지게 만든 요인."
        )
        
        # SHAP 막대 차트 (Plotly)
        try:
            import plotly.graph_objects as go
            
            colors = ["#1D9E75" if d["SHAP"] > 0 else "#E24B4A" for d in top_data]
            
            fig = go.Figure(go.Bar(
                y=[d["변수"] for d in top_data],
                x=[d["SHAP"] for d in top_data],
                orientation="h",
                marker_color=colors,
                text=[f"{d['SHAP']:+.3f} (값: {d['값']:.3f})" for d in top_data],
                textposition="outside",
            ))
            fig.update_layout(
                title=f"{predicted_grade}등급 예측 — SHAP 기여도 Top 8",
                xaxis_title="SHAP 값 (등급 예측에 미치는 영향)",
                yaxis=dict(autorange="reversed"),
                height=400,
                margin=dict(l=120, r=80, t=50, b=40),
                showlegend=False,
            )
            fig.add_vline(x=0, line_color="#999", line_width=1)
            
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            # Plotly 없으면 표로
            st.dataframe(
                pd.DataFrame(top_data)[["변수", "값", "SHAP"]],
                use_container_width=True,
                hide_index=True
            )
        
        # 자연어 해석
        positive_top = [d for d in top_data if d["SHAP"] > 0][:3]
        negative_top = [d for d in top_data if d["SHAP"] < 0][:3]
        
        if positive_top:
            pos_text = ", ".join([f"**{d['변수']}**({d['값']:.2f})" for d in positive_top])
            st.success(f"**{predicted_grade}등급으로 분류된 주요 근거**: {pos_text}")
        
        if negative_top:
            neg_text = ", ".join([f"**{d['변수']}**({d['값']:.2f})" for d in negative_top])
            st.warning(f"**다른 등급으로 갈 뻔한 요인**: {neg_text}")
        
    except Exception as e:
        st.error(f"SHAP 분석 실패: {e}")


def render_benchmark_comparison(user_inputs, df):
    """학습 데이터와 비교 — 비슷한 사업 찾기"""
    if df is None:
        return
    
    st.markdown("### 🔎 유사 사업 사례 (학습 데이터 59건 중)")
    
    # 핵심 지표 4개로 유사도 계산
    target = {
        "영업이익률": user_inputs["영업이익률"] / 100,
        "DSCR_근사": user_inputs["DSCR_근사"],
        "부채비율": user_inputs["부채비율"],
        "이자보상배율": user_inputs["이자보상배율"],
    }
    
    # Z-score 기반 유사도
    distances = []
    for _, row in df.iterrows():
        try:
            d = 0
            for col, target_val in target.items():
                actual_val = pd.to_numeric(row.get(col, 0), errors="coerce")
                if pd.notna(actual_val):
                    # 상대 차이
                    d += ((actual_val - target_val) / max(abs(target_val), 0.5)) ** 2
            distances.append(d ** 0.5)
        except Exception:
            distances.append(float("inf"))
    
    df_with_dist = df.copy()
    df_with_dist["유사도"] = distances
    df_with_dist = df_with_dist.sort_values("유사도").head(3)
    
    cols = st.columns(3)
    for i, (_, row) in enumerate(df_with_dist.iterrows()):
        with cols[i]:
            grade = row.get("등급", "?")
            color = GRADE_CRITERIA.get(grade, {}).get("color", "#999")
            
            st.markdown(
                f"""<div style="background: {color}10;
                                border-top: 4px solid {color};
                                padding: 12px 16px;
                                border-radius: 6px;">
                    <div style="font-size: 13px; font-weight: 500;">
                        #{i+1} 유사 사업
                    </div>
                    <div style="font-size: 16px; font-weight: 600;
                                margin: 6px 0;">
                        {row.get('회사명', '?')}
                    </div>
                    <div style="font-size: 11px; color: #666;">
                        {row.get('사업연도', '?')}년 · 
                        <strong style="color: {color};">{grade}등급</strong>
                    </div>
                    <div style="font-size: 11px; color: #888;
                                margin-top: 8px; line-height: 1.5;">
                        영익률: {pd.to_numeric(row.get('영업이익률', 0), errors='coerce'):.1%}<br>
                        DSCR: {pd.to_numeric(row.get('DSCR_근사', 0), errors='coerce'):.2f}<br>
                        부채비율: {pd.to_numeric(row.get('부채비율', 0), errors='coerce'):.2f}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )


# ════════════════════════════════════════════════════════════
# 메인 렌더 함수 (app.py에서 호출)
# ════════════════════════════════════════════════════════════
def render_xgboost_tab():
    """app.py에서 호출하는 메인 함수"""
    
    st.subheader("🎯 XGBoost 수익성 등급 예측")
    st.caption(
        "민자고속도로 13개사 5년치(59건) DART 감사보고서로 학습한 XGBoost 모델로 "
        "신규 사업의 수익성 등급(A/B/C)을 예측합니다."
    )
    
    # 모델 로드
    model_obj, error = load_model()
    
    if error:
        st.error(f"❌ {error}")
        with st.expander("📖 모델 학습 방법"):
            st.markdown("""
            1. `pip install xgboost shap imbalanced-learn matplotlib --break-system-packages`
            2. `python financial_extract.py` (PDF에서 재무 추출)
            3. `python financial_label.py` (A/B/C 라벨링)
            4. `python financial_xgboost.py` (XGBoost 학습)
            5. `python fix_json.py` (메타정보 저장)
            6. app.py 재시작
            """)
        return
    
    # ── 1. 모델 정보 ──
    st.markdown("---")
    render_model_info(model_obj["meta"])
    
    # ── 2. 등급 분류 기준 ──
    st.markdown("---")
    render_grade_criteria_box()
    
    st.info(
        "💡 **학습 데이터 구성 원칙**: "
        "한국 신용평가 관행 + 민자 BTO 사업의 실제 운영 패턴을 반영한 룰 기반 라벨링. "
        "벤치마크 — 천안논산고속도로 DSCR 1.29 → B등급, 제이영동고속도로 DSCR 0.31 → C등급."
    )
    
    # ── 3. 입력 + 예측 ──
    st.markdown("---")
    st.markdown("### ⚙️ 신규 사업 재무 가정 입력")
    st.caption("슬라이더를 조절하여 신규 입찰 사업의 재무 시나리오를 시뮬레이션하세요.")
    
    # 입력 슬라이더 (2열 배치)
    user_inputs = {}
    
    slider_cols = st.columns(2)
    for i, (key, label, min_v, max_v, default, step, help_text) in enumerate(INPUT_SLIDERS):
        with slider_cols[i % 2]:
            user_inputs[key] = st.slider(
                label,
                min_value=float(min_v),
                max_value=float(max_v),
                value=float(default),
                step=float(step),
                help=help_text,
                key=f"xgb_input_{key}"
            )
    
    # 예측 실행 (자동)
    grade, proba_dict, X_pred, feature_vec = predict_grade(model_obj, user_inputs)
    
    st.markdown("---")
    render_prediction_result(grade, proba_dict)
    
    # ── 4. SHAP 설명 ──
    st.markdown("---")
    render_shap_explanation(model_obj, X_pred, feature_vec, grade)
    
    # ── 5. 유사 사업 사례 ──
    df = load_labeled_data()
    if df is not None:
        st.markdown("---")
        render_benchmark_comparison(user_inputs, df)
    
    # ── 6. 케이스 스터디 ──
    st.markdown("---")
    with st.expander("📚 학습 데이터 분석 — 등급별 SHAP 패턴"):
        st.markdown("""
        #### 등급별 결정 변수 (학습 데이터 SHAP 분석 결과)
        
        **A등급 (28건)**
        - 결정 변수: **DSCR_근사** (압도적)
        - 패턴: DSCR이 명확히 양극화 — 1.30 이상이면 거의 확실히 A
        - 예: 신대구부산고속도로 (DSCR 평균 1.6+)
        
        **C등급 (25건)**
        - 결정 변수: **DSCR_근사 (낮음) + 영업이익률 (음수)**
        - 패턴: A등급의 거울상 - 명확한 부실 신호
        - 예: 제이영동고속도로 (DSCR 0.31, 5년 연속)
        
        **B등급 (6건) - 가장 흥미로운 패턴**
        - 결정 변수: **영업이익률, 순이익률, 영업현금흐름** (균등 분산)
        - 패턴: 단일 변수가 아닌 **복합 조건**으로 분류
        - 예: 거가대교 (5년 연속 B - "안정적이지만 우량 못 미치는" 케이스)
        - **해석**: 해상교량의 구조적 유지관리 부담이 영업이익률에 압력
        """)
    
    # 거가대교 케이스 스터디
    with st.expander("🌉 거가대교 케이스 스터디 (B등급 5년 연속)"):
        st.markdown("""
        #### 왜 거가대교는 5년 연속 B등급에 머물렀는가?
        
        **사실 관계**:
        - 부산 - 거제 BTO-rs 사업, 운영기간 40년 (2010 개통)
        - 통행량은 안정적 (BTO-rs는 통행량 위험 분담)
        - 5년 모두 B등급 (2019, 2020, 2022, 2023, 2024)
        
        **SHAP 분석 결과**:
        - 영업이익률: 5~10% 수준 (A등급 15% 미달, B등급 5% 충족)
        - DSCR: 1.0~1.3 사이 (B등급 통과, A등급 미달)
        - 부채비율: 5~6배 (B등급 한계)
        
        **구조적 원인 (도메인 지식)**:
        해상교량 특유의 유지관리비 부담 — 염해 방지, 케이블 검사, 
        해양 환경 모니터링 등이 수익성을 압박하는 패턴이 모델에 학습됨.
        
        **시사점**: 신규 해상교량 사업 입찰 평가 시 동일 패턴 예상 가능.
        """)


if __name__ == "__main__":
    # 단독 실행 테스트용
    render_xgboost_tab()
