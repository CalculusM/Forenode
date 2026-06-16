# -*- coding: utf-8 -*-
"""[TODO①] Weibull CI → OPEX 밴드 비-UI 검증.
실행: python _test_opex_band.py
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
from opex_estimator import (estimate_opex_series, load_weibull_ci, montecarlo_opex_band)

print("=" * 60)
# 1) weibull_params.json에서 실제 CI 로드
ci = load_weibull_ci()
assert ci is not None, "weibull_params.json CI 로드 실패"
assert ci["eta_lo"] < ci["eta_hat"] < ci["eta_hi"], "η CI 순서"
print(f"[A] Weibull CI 로드 OK: η={ci['eta_hat']} ({ci['eta_lo']}~{ci['eta_hi']}), β={ci['beta_hat']}")

# 2) 베이스 OPEX 시계열
base = np.array(estimate_opex_series("BTO-ann", 1500, 30, "평지", 0.2, 0.15)["opex_series_억"])
band = montecarlo_opex_band(base, weibull_ci=ci, n_sims=800)
p10 = np.array(band["p10"]); p50 = np.array(band["p50"]); p90 = np.array(band["p90"])

# 3) 밴드 순서·유한·중앙값 보존
assert len(p10) == len(base) == 30
assert np.all(p10 <= p50 + 1e-6) and np.all(p50 <= p90 + 1e-6), "P10<=P50<=P90"
assert np.all(np.isfinite(p10)) and np.all(np.isfinite(p90))
# 평균보존 multiplier → P50 ≈ base (±15%)
rel = np.abs(p50 - base) / np.where(base == 0, np.nan, base)
assert np.nanmean(rel) < 0.15, f"P50가 base에서 과도이탈({np.nanmean(rel):.2f})"
print(f"[B] 밴드 OK: source='{band['source']}', n={band['n_sims']}")
print(f"    1년차  P10/P50/P90 = {p10[0]:.1f} / {p50[0]:.1f} / {p90[0]:.1f}")
print(f"    10년차 P10/P50/P90 = {p10[9]:.1f} / {p50[9]:.1f} / {p90[9]:.1f}")
width = float(np.mean((p90 - p10) / np.where(p50 == 0, np.nan, p50)))
print(f"    평균 밴드폭 (P90-P10)/P50 = {width:.1%}")

# 4) Weibull CI 포함 시 밴드가 단가-only보다 넓어야 (η 불확실성 추가됨)
band_cost = montecarlo_opex_band(base, weibull_ci=None, n_sims=800)
w_full = np.mean(np.array(band["p90"]) - np.array(band["p10"]))
w_cost = np.mean(np.array(band_cost["p90"]) - np.array(band_cost["p10"]))
assert w_full > w_cost, "Weibull CI 추가 시 밴드가 더 넓어야"
print(f"[C] Weibull CI 효과 확인: 밴드폭 {w_cost:.1f}(단가만) → {w_full:.1f}(η CI 추가)")

# 5) 빈 입력 방어
assert montecarlo_opex_band([], ci)["n_sims"] == 0
print("[D] 빈 입력 방어 OK")
print("=" * 60); print("ALL_BAND_TESTS_PASSED")
