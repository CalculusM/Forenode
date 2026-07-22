"""
============================================================
ROADx Phase 3 - Weibull MLE 열화 학습 (PoC)
============================================================
역할:
  - 도로 포장 열화 데이터를 Weibull 분포로 적합
  - shape (β), scale (η) 파라미터 최우도추정 (MLE)
  - 안심구역 실데이터 도착 전 PoC용
  - 안심구역 데이터 도착 시 INPUT_CSV만 교체하면 그대로 작동

데이터 모드:
  - 합성 데이터 (현재 PoC): 한국도로공사 통계 기반 100건 생성
  - 실데이터: pavement_data.csv 입력 시 자동 사용
  
  CSV 형식 (안심구역 반출 시):
    pavement_age, traffic_load, ESAL_cumulative, distress_observed (0/1), 
    distress_time_years (열화 발생 시점), 
    censored (0/1, 우중도 절단 여부)

CSV 칼럼 매핑:
  - distress_time_years: 손상 첫 발생 시점 (단위: 년)
  - censored=1: 관측 종료까지 손상 없음 (right-censored)
  
출력:
  - weibull_params.json (β, η, 95% CI, 데이터 출처)
  - weibull_curve.png (생존곡선)
  - weibull_hazard.png (위험률 함수)
  - weibull_data_used.csv (학습에 사용한 데이터 백업)

설치:
  pip install scipy numpy matplotlib pandas --break-system-packages

실행:
  python weibull_fit.py
============================================================
"""
import sys
import json
import csv
from pathlib import Path

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
INPUT_CSV = "./pavement_data.csv"   # 실데이터 도착 시 이 파일 자동 사용
OUTPUT_PARAMS = "./weibull_params.json"
OUTPUT_CURVE = "./weibull_curve.png"
OUTPUT_HAZARD = "./weibull_hazard.png"
OUTPUT_DATA = "./weibull_data_used.csv"

# 합성 데이터 파라미터 (한국도로공사 도로포장 열화 통계 기반)
# 도로공사 표준 열화곡선: β=2.5 (마모고장), η=12년 (특성수명)
SYNTHETIC_BETA_TRUE = 2.5
SYNTHETIC_ETA_TRUE = 12.0
SYNTHETIC_N = 100
SYNTHETIC_SEED = 42


# ════════════════════════════════════════════════════════════
# 합성 데이터 생성
# ════════════════════════════════════════════════════════════
def generate_synthetic_data():
    """
    한국도로공사 통계 기반 합성 포장 열화 데이터.
    실제 도로공사 보고서: 아스팔트 포장 평균 수명 8~12년,
    중차량 비율에 따라 4~15년 분포.
    """
    np.random.seed(SYNTHETIC_SEED)
    
    print("[합성 데이터 생성]")
    print(f"  진실값: β={SYNTHETIC_BETA_TRUE} (shape, 마모고장)")
    print(f"  진실값: η={SYNTHETIC_ETA_TRUE} (scale, 특성수명)")
    print(f"  샘플 수: {SYNTHETIC_N}")
    
    # Weibull 분포에서 샘플링
    distress_times = np.random.weibull(SYNTHETIC_BETA_TRUE, SYNTHETIC_N) * SYNTHETIC_ETA_TRUE
    
    # 30% 우중도 절단 (관측 종료까지 손상 안 본 케이스)
    observation_period = 15.0  # 15년 관측
    censored = (distress_times > observation_period).astype(int)
    distress_times = np.minimum(distress_times, observation_period)
    
    # 부가 정보 (다양성 표현용)
    pavement_age = np.random.uniform(1, 20, SYNTHETIC_N)
    traffic_load = np.random.lognormal(8, 0.5, SYNTHETIC_N)  # AADT
    esal = traffic_load * pavement_age * 0.15 * 1e3  # 누적 ESAL 근사
    
    df = pd.DataFrame({
        "pavement_age": pavement_age,
        "traffic_load": traffic_load,
        "ESAL_cumulative": esal,
        "distress_observed": (1 - censored).astype(int),
        "distress_time_years": distress_times,
        "censored": censored,
    })
    
    # 합성 데이터 저장
    df.to_csv(OUTPUT_DATA, index=False, encoding="utf-8-sig")
    print(f"  [{OUTPUT_DATA}] 저장")
    
    return df, "synthetic"


# ════════════════════════════════════════════════════════════
# 실데이터 로드
# ════════════════════════════════════════════════════════════
def load_real_data():
    """실데이터 로드 — 출처는 pavement_summary.json에서 자동 감지"""
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    required_cols = ["distress_time_years", "censored"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[중지] 필수 칼럼 누락: {missing}")
        sys.exit(1)

    # 데이터 출처 자동 감지: pavement_summary.json이 있으면 거기서 읽음
    data_source_label = "real"  # 기본값
    period = []
    summary_path = Path("./pavement_summary.json")
    if summary_path.exists():
        try:
            import json as _json
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = _json.load(f)
            src = summary.get("data_source", "")
            period = summary.get("data_period_year_range", []) or []
            if src:
                data_source_label = src
        except Exception:
            pass

    print(f"[실데이터 로드]")
    print(f"  파일: {INPUT_CSV}")
    print(f"  출처: {data_source_label}")
    print(f"  샘플 수: {len(df)}")
    print(f"  관측 손상: {(df['censored']==0).sum()}건")
    print(f"  우중도 절단: {(df['censored']==1).sum()}건")

    df.to_csv(OUTPUT_DATA, index=False, encoding="utf-8-sig")
    return df, data_source_label, period


# ════════════════════════════════════════════════════════════
# Weibull MLE 적합 (우중도 절단 고려)
# ════════════════════════════════════════════════════════════
def weibull_mle_with_censoring(times, censored):
    """
    우중도 절단(right-censoring)을 고려한 Weibull MLE.
    
    Parameters:
        times: array of observation times
        censored: 1 if censored (관측 종료까지 손상 없음), 0 if observed (손상 관측)
    
    Returns:
        beta_hat, eta_hat (MLE 추정치)
    """
    from scipy import optimize
    
    def neg_log_likelihood(params):
        beta, eta = params
        if beta <= 0 or eta <= 0:
            return 1e10
        
        # 손상 관측된 케이스: log f(t) = log(β/η) + (β-1)·log(t/η) - (t/η)^β
        # 절단된 케이스: log S(t) = -(t/η)^β
        observed_mask = (censored == 0)
        censored_mask = (censored == 1)
        
        # 시간이 0인 경우 방지
        t_safe = np.maximum(times, 1e-10)
        
        # 손상 관측 부분
        log_lik_observed = (
            np.log(beta / eta)
            + (beta - 1) * np.log(t_safe / eta)
            - (t_safe / eta) ** beta
        )
        
        # 절단 부분 (생존확률만 기여)
        log_lik_censored = -((t_safe / eta) ** beta)
        
        total_log_lik = (
            log_lik_observed[observed_mask].sum() 
            + log_lik_censored[censored_mask].sum()
        )
        
        return -total_log_lik
    
    # 초기값: 모멘트 추정
    # β ≈ (mean / std)^1.086, η ≈ mean / Γ(1+1/β)
    from scipy.special import gamma as gamma_fn
    mean_t = np.mean(times)
    std_t = np.std(times) + 1e-6
    beta_init = max(0.5, (mean_t / std_t) ** 1.086)
    eta_init = mean_t / gamma_fn(1 + 1/beta_init)
    
    # 최적화
    result = optimize.minimize(
        neg_log_likelihood,
        x0=[beta_init, eta_init],
        method="Nelder-Mead",
        options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 5000}
    )
    
    beta_hat, eta_hat = result.x
    return beta_hat, eta_hat, result


def compute_confidence_intervals(times, censored, beta_hat, eta_hat, n_bootstrap=200):
    """부트스트랩으로 95% 신뢰구간 추정"""
    print(f"  부트스트랩 {n_bootstrap}회 실행 중...")
    
    n = len(times)
    betas = []
    etas = []
    
    np.random.seed(SYNTHETIC_SEED)
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, size=n, replace=True)
        t_boot = times[idx]
        c_boot = censored[idx]
        try:
            b, e, _ = weibull_mle_with_censoring(t_boot, c_boot)
            if 0.1 < b < 10 and 0.5 < e < 100:  # 이상치 필터
                betas.append(b)
                etas.append(e)
        except Exception:
            continue
    
    if len(betas) < 30:
        return None, None, None, None
    
    beta_ci = (np.percentile(betas, 2.5), np.percentile(betas, 97.5))
    eta_ci = (np.percentile(etas, 2.5), np.percentile(etas, 97.5))
    
    return beta_ci, eta_ci, betas, etas


# ════════════════════════════════════════════════════════════
# 시각화
# ════════════════════════════════════════════════════════════
def plot_survival_curve(times, censored, beta, eta, data_source):
    """Weibull 생존 곡선 + Kaplan-Meier 비교"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        return False
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Weibull 이론 생존곡선
    t_grid = np.linspace(0, np.max(times) * 1.2, 200)
    survival_weibull = np.exp(-((t_grid / eta) ** beta))
    
    ax.plot(t_grid, survival_weibull, color="#1F3864", linewidth=2.5,
            label=f"Weibull MLE (β={beta:.2f}, η={eta:.2f})")
    
    # Kaplan-Meier 경험 생존곡선 (비교용)
    sorted_idx = np.argsort(times)
    t_sorted = times[sorted_idx]
    c_sorted = censored[sorted_idx]
    
    n = len(t_sorted)
    survival_km = []
    s = 1.0
    for i, (t, c) in enumerate(zip(t_sorted, c_sorted)):
        n_at_risk = n - i
        if c == 0:  # 손상 관측
            s *= (n_at_risk - 1) / n_at_risk
        survival_km.append(s)
    
    ax.step(t_sorted, survival_km, where="post", color="#E24B4A",
            linewidth=1.5, label="Kaplan-Meier 경험분포", alpha=0.7)
    
    # 임계점 표시: η (63.2%)와 보수 임계 (50%)
    eta_50 = eta * (np.log(2)) ** (1/beta)
    ax.axhline(0.632, color="#999", linestyle=":", alpha=0.5)
    ax.axhline(0.5, color="#EF9F27", linestyle=":", alpha=0.7)
    ax.axvline(eta, color="#999", linestyle=":", alpha=0.5)
    ax.axvline(eta_50, color="#EF9F27", linestyle=":", alpha=0.7)
    
    ax.text(eta + 0.3, 0.65, f"η={eta:.1f}년\n(특성수명)",
            fontsize=9, color="#666")
    ax.text(eta_50 + 0.3, 0.52, f"중위수명\n{eta_50:.1f}년",
            fontsize=9, color="#EF9F27")
    
    ax.set_xlabel("운영 경과 시간 (년)", fontsize=12)
    ax.set_ylabel("생존 확률 S(t)", fontsize=12)
    ax.set_title(f"Weibull 열화 생존곡선 — {data_source}", fontsize=14)
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    ax.set_xlim([0, np.max(times) * 1.2])
    ax.set_ylim([0, 1.05])
    
    plt.tight_layout()
    plt.savefig(OUTPUT_CURVE, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  ✓ {OUTPUT_CURVE}")
    return True


def plot_hazard_function(beta, eta, data_source):
    """Weibull 위험률 함수 (시간이 갈수록 고장률이 어떻게 변하는가)"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        return False
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    t_grid = np.linspace(0.1, eta * 2.5, 200)
    hazard = (beta / eta) * (t_grid / eta) ** (beta - 1)
    
    color = "#E24B4A" if beta > 1 else "#1D9E75"
    ax.plot(t_grid, hazard, color=color, linewidth=2.5)
    ax.fill_between(t_grid, 0, hazard, color=color, alpha=0.15)
    
    # 고장 모드 해석
    if beta > 1.5:
        mode = "마모고장 (시간이 갈수록 위험 증가 → 예방보수 필요)"
    elif beta > 0.9:
        mode = "우발고장 (위험률 일정 → 정기점검)"
    else:
        mode = "초기고장 (시간 갈수록 위험 감소 → 시공 결함)"
    
    ax.set_xlabel("운영 경과 시간 (년)", fontsize=12)
    ax.set_ylabel("위험률 h(t)", fontsize=12)
    ax.set_title(f"Weibull 위험률 함수 — {mode}\n(β={beta:.2f}, η={eta:.2f})",
                 fontsize=14)
    ax.grid(alpha=0.3)
    
    # 권장 보수시점 표시
    maintenance_time = eta * 0.5  # 50% 위험 도달 시점 근사
    ax.axvline(maintenance_time, color="#EF9F27", linestyle="--", alpha=0.7,
               label=f"권장 사전보수 시점 ≈ {maintenance_time:.1f}년")
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(OUTPUT_HAZARD, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  ✓ {OUTPUT_HAZARD}")
    return True


# ════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("ROADx Phase 3 - Weibull MLE 열화 학습")
    print("=" * 60)
    
    # 데이터 로드 (실데이터 우선)
    if Path(INPUT_CSV).exists():
        df, data_source, data_period = load_real_data()
    else:
        print(f"[안내] {INPUT_CSV} 없음 — 합성 데이터로 PoC 진행")
        print("       (안심구역에서 데이터 반출 후 이 파일 위치에 배치하면 자동 적용)\n")
        df, data_source = generate_synthetic_data()
        data_period = []
    
    times = df["distress_time_years"].values
    censored = df["censored"].values.astype(int)
    
    print(f"\n[Weibull MLE 적합]")
    print(f"  데이터 출처: {data_source}")
    print(f"  관측 시간 범위: [{times.min():.2f}, {times.max():.2f}] 년")
    print(f"  관측 비율: {(censored==0).sum()}/{len(times)} = {(censored==0).mean():.1%}")
    
    # MLE 적합
    beta_hat, eta_hat, result = weibull_mle_with_censoring(times, censored)
    print(f"\n[추정 결과]")
    print(f"  β (shape) = {beta_hat:.3f}")
    print(f"  η (scale) = {eta_hat:.3f} 년")
    print(f"  -log L = {result.fun:.2f}")
    print(f"  수렴 여부: {result.success}")
    
    # 신뢰구간
    print(f"\n[부트스트랩 신뢰구간]")
    beta_ci, eta_ci, betas, etas = compute_confidence_intervals(
        times, censored, beta_hat, eta_hat
    )
    if beta_ci:
        print(f"  β 95% CI: [{beta_ci[0]:.3f}, {beta_ci[1]:.3f}]")
        print(f"  η 95% CI: [{eta_ci[0]:.3f}, {eta_ci[1]:.3f}] 년")
    
    # 합성 데이터인 경우 진실값과 비교
    if data_source == "synthetic":
        print(f"\n[합성 데이터 검증]")
        print(f"  진실 β={SYNTHETIC_BETA_TRUE} → 추정 {beta_hat:.3f} "
              f"(오차 {abs(beta_hat - SYNTHETIC_BETA_TRUE)/SYNTHETIC_BETA_TRUE:.1%})")
        print(f"  진실 η={SYNTHETIC_ETA_TRUE} → 추정 {eta_hat:.3f} "
              f"(오차 {abs(eta_hat - SYNTHETIC_ETA_TRUE)/SYNTHETIC_ETA_TRUE:.1%})")
    
    # 해석
    print(f"\n[열화 패턴 해석]")
    if beta_hat > 1.5:
        print(f"  마모고장 모드 (β > 1.5): 사전 예방보수가 효과적")
    elif beta_hat > 0.9:
        print(f"  우발고장 모드 (β ≈ 1): 정기점검으로 충분")
    else:
        print(f"  초기고장 모드 (β < 1): 시공 품질 점검 필요")
    
    median_life = eta_hat * (np.log(2)) ** (1/beta_hat)
    print(f"  중위 수명: {median_life:.1f}년 (50% 손상 발생 시점)")
    print(f"  특성 수명: {eta_hat:.1f}년 (63.2% 손상 발생 시점)")
    
    # 시각화
    print(f"\n[시각화]")
    plot_survival_curve(times, censored, beta_hat, eta_hat, data_source)
    plot_hazard_function(beta_hat, eta_hat, data_source)
    
    # JSON 저장 — 소비자(opex_estimator 등) 키 스키마와 일치
    from scipy.special import gamma as _gamma_fn
    n = len(times)
    k = 2
    logL = float(-result.fun)
    mean_life = eta_hat * _gamma_fn(1 + 1 / beta_hat)
    output = {
        "beta_hat": round(float(beta_hat), 3),
        "eta_hat": round(float(eta_hat), 2),
        "median_life": round(float(median_life), 2),
        "beta_ci_lower": round(float(beta_ci[0]), 3) if beta_ci else None,
        "beta_ci_upper": round(float(beta_ci[1]), 3) if beta_ci else None,
        "eta_ci_lower": round(float(eta_ci[0]), 2) if eta_ci else None,
        "eta_ci_upper": round(float(eta_ci[1]), 2) if eta_ci else None,
        "n_samples": int(n),
        "n_observed": int((censored == 0).sum()),
        "n_censored": int((censored == 1).sum()),
        "data_source": data_source,
        "data_period_year_range": data_period if data_period else None,
        "log_likelihood": round(logL, 2),
        "aic": round(2 * k - 2 * logL, 2),
        "bic": round(k * np.log(n) - 2 * logL, 2),
        "converged": bool(result.success),
        "interpretation": {
            "beta_meaning": (
                f"β = {beta_hat:.3f} "
                + ("> 1.5 → 마모성(시간 경과에 따라 위험률 증가)" if beta_hat > 1.5
                   else ("≈ 1 → 위험률 일정" if beta_hat > 0.9 else "< 1 → 초기 집중"))
            ),
            "eta_meaning": f"η = {eta_hat:.2f}년 → 누적 발생 확률 63.2% 도달 시점",
            "expected_repairs_30y": f"30년 운영 시 약 {30.0 / mean_life:.2f}회 보수 예상",
            "data_note": (
                "관측치 = 보수 '집행' 기록(예산·일정 의존) — 물리 열화 시점의 대용치. "
                "무보수 31,245구간은 보수기록 관측창(11년) 밖 이력 결손으로 절단 포함 적합이 "
                "비식별(η 발산 실검증 '26-07-22)되어 제외 — 적합 표본은 보수 관측 구간만"
            ),
        },
    }
    
    with open(OUTPUT_PARAMS, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUTPUT_PARAMS}")
    
    print(f"\n" + "=" * 60)
    print("학습 완료")
    print("=" * 60)
    print(f"\n다음 단계:")
    print(f"  1. Streamlit 'weibull_tab.py' 작성")
    print(f"  2. 안심구역 회원가입 후 대전남부순환 데이터 신청")
    print(f"  3. 데이터 반출 후 {INPUT_CSV} 위치에 배치 → 자동 재학습")


if __name__ == "__main__":
    main()
