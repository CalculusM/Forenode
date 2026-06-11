# -*- coding: utf-8 -*-
"""[C1] 비-UI 검증: 물량기반 LCC OPEX 상향식이 build_cashflow에 직결되는지.
Streamlit UI 없이 핵심 함수만 호출해 (1) 상향식 시계열 생성, (2) 현금흐름 반영,
(3) 기본(top-down) 경로 불변을 확인한다. 실행: python _test_c1_wiring.py
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

# opex_estimator 순수함수 단독 검증 ----------------------------------
from opex_estimator import (
    estimate_opex_series, estimate_opex_series_bottomup, lcc_to_annual_series,
)

print("=" * 64)
print("[A] opex_estimator 순수함수")
# 합성 lcc_df: 10·20년차 교체 lump + 5년 간격 소액
rows = []
for y in range(1, 31):
    if y % 10 == 0:
        rows.append({"Year": y, "Cost_억": 120.0})
    elif y % 5 == 0:
        rows.append({"Year": y, "Cost_억": 8.0})
lcc_df = pd.DataFrame(rows)
ann = lcc_to_annual_series(lcc_df, 30)
assert ann.shape == (30,), "시계열 길이"
assert abs(ann[9] - 120.0) < 1e-6 and abs(ann[19] - 120.0) < 1e-6, "10/20년차 lump"
assert abs(ann[4] - 8.0) < 1e-6, "5년차 소액"
assert abs(ann[0] - 0.0) < 1e-6, "1년차 0"
print("  lcc_to_annual_series: OK (lump 정확 집계)")

bu = estimate_opex_series_bottomup(lcc_df, annual_revenue_억=1500, operation_years=30,
                                   routine_opex_ratio=0.18, growth_rate=0.025)
assert len(bu["opex_series_억"]) == 30
assert all(v > 0 for v in bu["opex_series_억"]), "routine baseline으로 항상 양수"
# 10년차(=lump)가 9년차보다 커야 (자본적 유지보수 반영)
assert bu["opex_series_억"][9] > bu["opex_series_억"][8], "lump 반영"
assert bu["is_bottomup"] is True
print(f"  bottomup: 평균비율={bu['opex_ratio_avg']*100:.1f}% peak={bu['peak_year']}년차 "
      f"{bu['peak_amount_억']:.0f}억 → OK")

# 빈 lcc_df 방어
empty = estimate_opex_series_bottomup(pd.DataFrame(columns=["Year", "Cost_억"]),
                                      1500, 30)
assert all(v > 0 for v in empty["opex_series_억"]), "빈 LCC도 routine으로 양수"
print("  빈 lcc_df 방어: OK")

# build_cashflow 직결 검증 -------------------------------------------
print("=" * 64)
print("[B] app.build_cashflow 직결 (Streamlit 미실행, import만)")
import app  # main()은 __main__ 아래라 실행 안 됨

base = dict(
    capex_억=8000, annual_revenue_억=1500, construction_years=5, operation_years=30,
    opex_ratio=0.35, discount_rate=0.06, inflation=0.02, growth_rate=0.025,
    equity_ratio=0.25, debt_rate=0.05, business_type="BTO-ann",
)

# (1) 기본 top-down
td = estimate_opex_series(business_type="BTO-ann", annual_revenue_억=1500,
                          operation_years=30, terrain="평지",
                          tunnel_ratio=0.2, bridge_ratio=0.15, growth_rate=0.025)
cf_td, m_td = app.build_cashflow(opex_series_억=np.array(td["opex_series_억"]), **base)

# (2) 상향식 (실제 LCC 엔진 사용)
lcc_real, lcc_total = app.estimate_lcc_maintenance(45.0, 30, 0.06)
bu_real = estimate_opex_series_bottomup(lcc_real, 1500, 30,
                                        routine_opex_ratio=0.18, growth_rate=0.025)
cf_bu, m_bu = app.build_cashflow(opex_series_억=np.array(bu_real["opex_series_억"]), **base)

# (3) opex_series=None (비율 폴백) — 회귀 방지용
cf_fb, m_fb = app.build_cashflow(opex_series_억=None, **base)

import math
def show(tag, m):
    dscr = m.get("dscr_min")
    npv = m.get("npv")
    print(f"  {tag}: dscr_min={dscr:.4f} npv={npv:,.1f}억")
    assert math.isfinite(float(dscr)), f"{tag} dscr_min finite"
    assert math.isfinite(float(npv)), f"{tag} npv finite"
    return dscr

print("  build_cashflow 반환 metrics:")
d_td = show("top-down ", m_td)
d_bu = show("bottom-up", m_bu)
d_fb = show("ratio-fb ", m_fb)

assert len(cf_bu) == len(cf_td), "현금흐름 길이 동일"
# (a) 상향식 입력 시계열이 top-down과 달라야(=연결 효과 있음)
assert not np.allclose(np.array(td["opex_series_억"]),
                       np.array(bu_real["opex_series_억"])), "상향식 시계열이 top-down과 달라야"
# (b) 그 차이가 실제 DSCR로 전파돼야(=OPEX→DSCR 직결 증명)
assert abs(float(d_bu) - float(d_td)) > 1e-6, "상향식 OPEX가 DSCR을 바꿔야(C1 직결)"
print(f"  ✅ DSCR이 모드별로 달라짐(td={d_td:.4f} vs bu={d_bu:.4f}) — OPEX→DSCR 직결(C1) 확인")
print("=" * 64)
print("ALL_C1_TESTS_PASSED")
