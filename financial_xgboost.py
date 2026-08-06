"""
============================================================
ROADx Phase 3 - Step 3
XGBoost 수익성 등급 분류 학습 + SHAP 분석
============================================================
입력: financial_labeled.csv (Step 2 산출물)
출력: 
  - xgb_model.pkl (학습된 모델)
  - feature_importance.png (전체 feature 중요도)
  - shap_summary.png (SHAP global)
  - shap_force_*.png (SHAP individual - 케이스별)
  - validation_report.html (LOOCV 결과)

전략:
  - 실제 59건 + SMOTE로 B 클래스 보강 (over-fitting 방지)
  - LOOCV (Leave-One-Out) 검증 — 작은 샘플 최적
  - 사업명·연도는 feature에서 제외 (패턴만 학습)
  - SHAP으로 "왜 이 등급인가" 해석

설치:
  pip install xgboost shap imbalanced-learn matplotlib --break-system-packages

실행:
  python financial_xgboost.py
============================================================
"""
import sys
import csv
import json
import pickle
from pathlib import Path
from collections import Counter

import numpy as np


INPUT_CSV = "./financial_labeled.csv"
MODEL_OUT = "./xgb_model.pkl"
FEATURE_NAMES_OUT = "./xgb_features.json"


# ════════════════════════════════════════════════════════════
# 학습에 사용할 Feature 선택
# ════════════════════════════════════════════════════════════
# 핵심 비율만 사용 (절대값은 회사 규모 편향 → 제외)
FEATURE_COLS = [
    # 안정성 (5)
    "부채비율",
    "자기자본비율",
    "유동비율",
    "차입금의존도",
    "고정장기적합률",
    # 수익성 (5)
    "영업이익률",
    "순이익률",
    "ROA_총자산수익률",
    "ROE_자기자본수익률",
    "EBITDA_마진",
    # 활동성 (2)
    "총자산회전율",
    "자기자본회전율",
    # 현금흐름 (3)
    "영업현금흐름_매출비",
    "영업현금흐름_부채상환비",
    "DSCR_근사",
    # 이자 (2)
    "이자보상배율",
    "금융비용_매출비",
    # 파생 (1)
    "유동성지표",
]

LABEL_COL = "등급"
GRADE_MAP = {"A": 0, "B": 1, "C": 2}
GRADE_REVERSE = {v: k for k, v in GRADE_MAP.items()}


def load_data():
    """CSV 로드 + Feature 매트릭스 생성"""
    if not Path(INPUT_CSV).exists():
        print(f"[중지] {INPUT_CSV} 없음 — 먼저 financial_label.py 실행")
        sys.exit(1)
    
    with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    
    X = []
    y = []
    meta = []  # 회사명·연도 (디버깅용)
    skipped = 0
    
    for row in rows:
        grade = row.get(LABEL_COL, "").strip()
        if grade not in GRADE_MAP:
            skipped += 1
            continue
        
        feature_vec = []
        valid = True
        for col in FEATURE_COLS:
            v = row.get(col, "")
            if v == "" or v is None:
                # 결측치는 0으로 (XGBoost는 결측 처리 가능하지만 일관성)
                feature_vec.append(0.0)
            else:
                try:
                    feature_vec.append(float(v))
                except ValueError:
                    feature_vec.append(0.0)
        
        X.append(feature_vec)
        y.append(GRADE_MAP[grade])
        meta.append({
            "회사명": row.get("회사명", "?"),
            "연도": row.get("사업연도", "?"),
            "사유": row.get("등급사유", "")
        })
    
    print(f"  로드: {len(X)}건 (제외 {skipped}건)")
    return np.array(X), np.array(y), meta


def main():
    print("=" * 60)
    print("ROADx Phase 3 - Step 3: XGBoost + SHAP")
    print("=" * 60)
    
    # ─── 라이브러리 임포트 ───
    try:
        import xgboost as xgb
        from sklearn.model_selection import LeaveOneOut, cross_val_predict
        from sklearn.metrics import (
            classification_report, confusion_matrix, accuracy_score
        )
    except ImportError as e:
        print(f"[중지] {e}")
        print("  설치: pip install xgboost scikit-learn --break-system-packages")
        sys.exit(1)
    
    try:
        from imblearn.over_sampling import SMOTE
        HAS_SMOTE = True
    except ImportError:
        print("  [경고] imbalanced-learn 미설치 — SMOTE 미적용")
        print("         설치: pip install imbalanced-learn --break-system-packages")
        HAS_SMOTE = False
    
    try:
        import shap
        HAS_SHAP = True
    except ImportError:
        print("  [경고] shap 미설치 — SHAP 분석 생략")
        HAS_SHAP = False
    
    try:
        import matplotlib
        matplotlib.use("Agg")  # GUI 없이 저장만
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 한글
        plt.rcParams["axes.unicode_minus"] = False
        HAS_PLOT = True
    except ImportError:
        print("  [경고] matplotlib 미설치 — 차트 생략")
        HAS_PLOT = False
    
    # ─── 데이터 로드 ───
    print("\n[1/5] 데이터 로드")
    X, y, meta = load_data()
    print(f"  Feature 수: {X.shape[1]}")

    # 실제 존재하는 등급만으로 클래스 인덱스 재매핑
    # (XGBoost는 0..K-1 연속 라벨을 요구 — 예: B등급 0건이면 {A,C}→{0,1})
    present = sorted(set(y))
    class_index = {c: i for i, c in enumerate(present)}
    y = np.array([class_index[v] for v in y])
    n_classes = len(present)
    grade_reverse = {i: GRADE_REVERSE[c] for i, c in enumerate(present)}
    grade_map = {g: i for i, g in grade_reverse.items()}

    print(f"  클래스 분포 (학습 전):")
    cnt = Counter(y)
    for label_idx, count in sorted(cnt.items()):
        grade = grade_reverse[label_idx]
        print(f"    {grade}등급: {count}건")
    
    # ─── SMOTE 적용 ───
    print("\n[2/5] 클래스 불균형 처리")
    if HAS_SMOTE and len(set(y)) >= 2:
        # 가장 적은 클래스 샘플 수 확인
        min_class_count = min(cnt.values())
        if min_class_count < 6:
            print(f"  [건너뜀] 최소 클래스 {min_class_count}건 — SMOTE k_neighbors 부족")
            X_resampled, y_resampled = X, y
        else:
            # B 클래스를 A 클래스 수에 맞춤 (보수적: A의 80%)
            target_size = int(max(cnt.values()) * 0.8)
            sampling_strategy = {
                label: max(target_size, count) 
                for label, count in cnt.items()
            }
            try:
                # k_neighbors는 최소 클래스 - 1
                k_n = min(5, min_class_count - 1)
                smote = SMOTE(
                    sampling_strategy=sampling_strategy, 
                    k_neighbors=k_n,
                    random_state=42
                )
                X_resampled, y_resampled = smote.fit_resample(X, y)
                print(f"  SMOTE 적용 (k_neighbors={k_n})")
                cnt_new = Counter(y_resampled)
                for label_idx, count in sorted(cnt_new.items()):
                    grade = grade_reverse[label_idx]
                    print(f"    {grade}등급: {count}건 (합성 {count - cnt[label_idx]}건 추가)")
            except Exception as e:
                print(f"  SMOTE 실패: {e} — 원본 사용")
                X_resampled, y_resampled = X, y
    else:
        X_resampled, y_resampled = X, y
    
    # ─── XGBoost 학습 ───
    print("\n[3/5] XGBoost 학습")
    
    # 클래스별 가중치 계산 (불균형 보정)
    class_weights = {}
    for cls, count in Counter(y_resampled).items():
        class_weights[cls] = len(y_resampled) / (len(set(y_resampled)) * count)
    
    sample_weight = np.array([class_weights[cls] for cls in y_resampled])
    
    # 공통 하이퍼파라미터 — 2클래스면 binary:logistic(기본), 3클래스 이상만 multi:softprob
    xgb_params = dict(
        n_estimators=100,
        max_depth=4,           # 작은 데이터 → 얕은 트리
        learning_rate=0.1,
        eval_metric="mlogloss" if n_classes > 2 else "logloss",
        random_state=42,
        n_jobs=-1,
    )
    if n_classes > 2:
        xgb_params.update(objective="multi:softprob", num_class=n_classes)

    model = xgb.XGBClassifier(**xgb_params)
    model.fit(X_resampled, y_resampled, sample_weight=sample_weight)
    
    # 학습 정확도
    train_acc = accuracy_score(y_resampled, model.predict(X_resampled))
    print(f"  학습 정확도: {train_acc:.1%}")
    
    # ─── LOOCV 검증 (원본 데이터로) ───
    print("\n[4/5] LOOCV 검증 (Leave-One-Out)")
    print(f"  {len(X)}회 fold 진행 중...")
    
    # 원본 데이터에 LOOCV (SMOTE 적용 안 함 — 검증의 정직성)
    # 단, 각 fold마다 train에는 SMOTE 적용
    loo = LeaveOneOut()
    loocv_predictions = []
    loocv_actuals = []
    
    for fold_idx, (train_idx, test_idx) in enumerate(loo.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        
        # train에만 SMOTE 적용
        if HAS_SMOTE:
            train_cnt = Counter(y_train)
            min_train = min(train_cnt.values())
            if min_train >= 2:
                k_n = min(5, min_train - 1)
                try:
                    smote_fold = SMOTE(k_neighbors=k_n, random_state=42)
                    X_train, y_train = smote_fold.fit_resample(X_train, y_train)
                except Exception:
                    pass
        
        # 학습
        model_fold = xgb.XGBClassifier(**xgb_params)
        model_fold.fit(X_train, y_train)
        
        pred = model_fold.predict(X_test)[0]
        loocv_predictions.append(pred)
        loocv_actuals.append(y_test[0])
    
    loocv_acc = accuracy_score(loocv_actuals, loocv_predictions)
    print(f"  LOOCV 정확도: {loocv_acc:.1%}")
    
    # 클래스별 정확도
    print(f"\n  Confusion Matrix (실제 → 예측):")
    print(f"  " + " ".join([f"{grade_reverse[i]:>4}" for i in range(n_classes)]))
    cm = confusion_matrix(loocv_actuals, loocv_predictions, labels=list(range(n_classes)))
    for actual_idx, row in enumerate(cm):
        actual_grade = grade_reverse[actual_idx]
        print(f"  {actual_grade} " + " ".join([f"{v:>4}" for v in row]))
    
    # ─── SHAP 분석 ───
    print("\n[5/5] SHAP 분석")
    if HAS_SHAP and HAS_PLOT:
        try:
            print(f"  TreeExplainer 생성")
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            
            # 멀티 클래스 SHAP 처리
            # XGBoost multi-class: shap_values shape = (n_samples, n_features, n_classes)
            # 또는 list of (n_samples, n_features) per class
            
            # Summary plot (global) — 클래스별
            for class_idx in range(n_classes):
                grade = grade_reverse[class_idx]
                
                if isinstance(shap_values, list):
                    sv_class = shap_values[class_idx]
                elif getattr(shap_values, "ndim", 0) == 3:
                    sv_class = shap_values[:, :, class_idx]
                else:
                    # 2클래스(binary:logistic): SHAP은 양성 클래스(인덱스 1) 기준 단일 행렬
                    sv_class = shap_values if class_idx == n_classes - 1 else -shap_values
                
                plt.figure(figsize=(10, 8))
                shap.summary_plot(
                    sv_class, X,
                    feature_names=FEATURE_COLS,
                    show=False,
                    max_display=15,
                )
                plt.title(f"SHAP Feature Importance — {grade}등급 예측", fontsize=14)
                plt.tight_layout()
                plt.savefig(f"shap_summary_{grade}.png", dpi=120, bbox_inches="tight")
                plt.close()
                print(f"  ✓ shap_summary_{grade}.png")
            
            # Feature importance (XGBoost 자체)
            plt.figure(figsize=(10, 8))
            importance_dict = model.get_booster().get_score(importance_type="gain")
            # f0, f1, ... → 실제 feature 이름으로 매핑
            importance_named = {}
            for k, v in importance_dict.items():
                idx = int(k.replace("f", ""))
                importance_named[FEATURE_COLS[idx]] = v
            
            sorted_imp = sorted(importance_named.items(), key=lambda x: x[1], reverse=True)
            names = [x[0] for x in sorted_imp[:15]]
            values = [x[1] for x in sorted_imp[:15]]
            
            plt.barh(range(len(names)), values, color="#1F3864")
            plt.yticks(range(len(names)), names)
            plt.xlabel("Gain")
            plt.title("XGBoost Feature Importance (Top 15)", fontsize=14)
            plt.gca().invert_yaxis()
            plt.tight_layout()
            plt.savefig("feature_importance.png", dpi=120, bbox_inches="tight")
            plt.close()
            print(f"  ✓ feature_importance.png")
            
        except Exception as e:
            print(f"  [에러] SHAP 분석 실패: {e}")
    else:
        print(f"  건너뜀 (라이브러리 부족)")
    
    # ─── 모델 저장 ───
    with open(MODEL_OUT, "wb") as f:
        pickle.dump({
            "model": model,
            "feature_cols": FEATURE_COLS,
            "grade_map": grade_map,
            "grade_reverse": grade_reverse,
            "loocv_accuracy": loocv_acc,
            "train_accuracy": train_acc,
            "n_train": len(X_resampled),
            "n_original": len(X),
        }, f)
    print(f"\n  ✓ {MODEL_OUT}")
    
    # Feature 이름 JSON (Streamlit에서 사용)
    with open(FEATURE_NAMES_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "feature_cols": FEATURE_COLS,
            "grade_map": grade_map,
            "loocv_accuracy": loocv_acc,
            "train_accuracy": train_acc,
            "n_original": len(X),
            "class_distribution": {grade_reverse[k]: v for k, v in Counter(y).most_common()},
        }, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {FEATURE_NAMES_OUT}")
    
    print(f"\n" + "=" * 60)
    print("학습 완료")
    print("=" * 60)
    print(f"  학습 데이터: {len(X)}건 → SMOTE 후 {len(X_resampled)}건")
    print(f"  학습 정확도: {train_acc:.1%}")
    print(f"  LOOCV 정확도: {loocv_acc:.1%}")
    print(f"\n다음 단계: Streamlit 시연 탭 추가")
    print(f"  → xgboost_tab.py")


if __name__ == "__main__":
    main()
