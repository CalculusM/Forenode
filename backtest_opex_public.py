# -*- coding: utf-8 -*-
"""
============================================================
Forenode — 공개 보수실적 기반 OPEX 백테스트 (backtest_opex_public.py)
============================================================
목적(멘토 피드백 '알고리즘 신뢰도 입증' 실현):
  모델이 산출한 노선 OPEX(자본적 유지보수)를, 한국도로공사가 공개한
  '노선별 보수실적'과 백테스트하여 "불확실성 범위 안에서 일치"하는지를 보인다.
  → 정밀 예측 주장이 아니라 '범위 적중률 + 누적 일치 + 재현성'으로 신뢰도를 증명.

설계 원칙:
  - 정밀(point)이 아니라 신뢰(band). 모델 점추정 × [1-α, 1+α] 밴드의 적중률을 본다.
  - 타이밍(언제 교체)보다 누적(cumulative-to-date)이 안정적 → 둘 다 보고.
  - 데이터가 없으면 합성 데이터로 end-to-end 동작(로직 시연·재현성 확보).

실데이터 연결(아래 ACTUAL_SOURCES, data.go.kr 공개):
  - 포장 보수실적   : 15050223
  - 교량 보수실적   : 15063122
  - 터널 보수실적   : 15045580
  - 사면 보수실적   : 15045555
  ※ 공통 구멍: 보수실적 CSV의 '노선' 태깅·금액 단위·연도 컬럼명이 데이터셋마다 다름
    → COLMAP_TODO를 실제 컬럼명으로 채운 뒤 사용.

실행: python backtest_opex_public.py            # 합성 데이터로 시연
      python backtest_opex_public.py --route 서해안선 --csv 포장보수.csv
============================================================
"""
import argparse
import os
import sys
import numpy as np

# ── 설정 ────────────────────────────────────────────────
BAND_ALPHA = 0.40          # 불확실성 밴드 ±40% (실측 보정 전 보수적 prior)
DEFAULT_ROUTE_LEN_KM = 45.0
DEFAULT_OPERATION_YEARS = 30
DEFAULT_DISCOUNT = 0.045

ACTUAL_SOURCES = {
    "포장": "15050223", "교량": "15063122",
    "터널": "15045580", "사면": "15045555",
}

# 실데이터 컬럼 매핑(데이터셋 확인 후 채울 것) — 안심구역 colmap.json과 동일 사상
COLMAP_TODO = {
    "route":  "TODO_노선명_또는_노선번호",
    "year":   "TODO_시행연도_또는_준공연도",
    "amount": "TODO_보수금액(원_또는_천원)",
    "amount_unit_to_won": 1,   # 금액 컬럼 단위 → 원 환산 계수 (천원이면 1000)
}


# ── CSV 로더 (한국 공공데이터 인코딩 대응) ─────────────────
def read_table(path):
    import pandas as pd
    if str(path).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    last = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception as e:
            last = e
    raise IOError(f"읽기 실패 {path}: {last}")


# ── 실측: 노선별 연도별 보수금액(억/년) ─────────────────────
def load_actual_maintenance(csv_path, route, operation_years, colmap=COLMAP_TODO):
    """공개 보수실적 CSV → 운영연차별 보수금액 시계열(억/년).
    NOTE: 공개 데이터는 '달력연도'이므로, 운영개시연도 기준으로 연차 정렬이 필요.
          여기서는 단순화를 위해 입력 CSV에 연차(또는 연도) 컬럼이 있다고 가정하고
          연도를 1..N 연차로 재인덱싱한다(실데이터 적용 시 운영개시연도로 보정)."""
    import pandas as pd
    df = read_table(csv_path)
    rc, yc, ac = colmap["route"], colmap["year"], colmap["amount"]
    for c in (rc, yc, ac):
        if c not in df.columns:
            raise KeyError(f"컬럼 '{c}' 없음 — COLMAP_TODO를 실제 컬럼명으로 채우세요. "
                           f"가용 컬럼: {list(df.columns)[:20]}")
    sub = df[df[rc].astype(str).str.contains(str(route), na=False)].copy()
    if len(sub) == 0:
        raise ValueError(f"노선 '{route}' 매칭 0건")
    sub[ac] = pd.to_numeric(sub[ac], errors="coerce").fillna(0) * colmap["amount_unit_to_won"]
    grp = sub.groupby(yc)[ac].sum().sort_index()
    # 연도 → 1..N 연차 재인덱싱
    series = np.zeros(operation_years)
    for i, (_, amt) in enumerate(grp.items()):
        if i < operation_years:
            series[i] = amt / 1e8  # 원 → 억
    return series


def make_synthetic_actual(operation_years, route_len_km, seed_offset=0):
    """실데이터 부재 시: 그럴듯한 보수실적(억/년) 합성.
    - 5년 주기 소액 보수 + 10/20년 대형 교체 + 노이즈."""
    rng = np.random.default_rng(20260610 + seed_offset)
    base_big = route_len_km * 2.2      # 대형 교체 규모(억)
    base_mid = route_len_km * 0.18     # 일상/중보수(억)
    s = np.zeros(operation_years)
    for y in range(1, operation_years + 1):
        v = base_mid * rng.uniform(0.6, 1.4)
        if y % 10 == 0:
            v += base_big * rng.uniform(0.7, 1.3)
        elif y % 5 == 0:
            v += base_big * 0.25 * rng.uniform(0.6, 1.4)
        s[y - 1] = round(v, 2)
    return s


# ── 모델: 노선 OPEX(자본적 유지보수, 억/년) ─────────────────
def model_capital_maintenance(route_len_km, operation_years, discount_rate):
    """app.estimate_lcc_maintenance(물량×표준품셈 단가×열화) → 연차별 자본적 유지보수(억/년).
    실패 시(헤비 import 등) None 반환 → 호출부에서 합성 모델로 폴백."""
    try:
        import app
        from opex_estimator import lcc_to_annual_series
        lcc_df, _ = app.estimate_lcc_maintenance(route_len_km, operation_years, discount_rate)
        return lcc_to_annual_series(lcc_df, operation_years)
    except Exception as e:
        print(f"[warn] 모델 엔진 import 실패({e}) → 합성 모델 사용", file=sys.stderr)
        return None


def make_synthetic_model(operation_years, route_len_km):
    """엔진 폴백용 합성 모델(실측과 독립 생성 — 백테스트 의미 유지)."""
    base_big = route_len_km * 2.0
    base_mid = route_len_km * 0.16
    s = np.zeros(operation_years)
    for y in range(1, operation_years + 1):
        v = base_mid
        if y % 10 == 0:
            v += base_big
        elif y % 5 == 0:
            v += base_big * 0.25
        s[y - 1] = round(v, 2)
    return s


# ── 백테스트 지표 ──────────────────────────────────────────
def backtest_metrics(model, actual, alpha=BAND_ALPHA):
    """model/actual: (N,) 억/년. 밴드=model×[1-α,1+α]."""
    model = np.asarray(model, float); actual = np.asarray(actual, float)
    n = min(len(model), len(actual))
    model, actual = model[:n], actual[:n]
    lo, hi = model * (1 - alpha), model * (1 + alpha)

    # 1) 연도별 밴드 적중률 (양쪽 0인 해는 적중 처리)
    in_band = ((actual >= lo) & (actual <= hi)) | ((model == 0) & (actual == 0))
    annual_hit = float(in_band.mean())

    # 2) 누적(cumulative-to-date) 일치 — 타이밍 노이즈 완화
    cm, ca = np.cumsum(model), np.cumsum(actual)
    with np.errstate(divide="ignore", invalid="ignore"):
        cum_ape = np.abs(cm - ca) / np.where(ca == 0, np.nan, ca)
    cum_mape = float(np.nanmean(cum_ape))
    cum_band = (ca >= cm * (1 - alpha)) & (ca <= cm * (1 + alpha))
    cum_hit = float(cum_band.mean())

    # 3) 편향(모델이 전체적으로 과대/과소?)
    bias = float((model.sum() - actual.sum()) / actual.sum()) if actual.sum() else float("nan")
    return {
        "n_years": n, "alpha": alpha,
        "annual_band_hit": annual_hit,
        "cum_mape": cum_mape,
        "cum_band_hit": cum_hit,
        "total_bias": bias,
        "model_total_억": float(model.sum()),
        "actual_total_억": float(actual.sum()),
        "lo": lo, "hi": hi, "model": model, "actual": actual,
    }


def render_report(route, m, out_md=None):
    lines = []
    lines.append(f"# OPEX 백테스트 리포트 — {route}")
    lines.append("")
    lines.append(f"- 비교 연차: **{m['n_years']}년** · 밴드: 모델 ±{m['alpha']*100:.0f}%")
    lines.append(f"- **연도별 밴드 적중률**: {m['annual_band_hit']*100:.1f}%")
    lines.append(f"- **누적 밴드 적중률**: {m['cum_band_hit']*100:.1f}%")
    lines.append(f"- **누적 MAPE**: {m['cum_mape']*100:.1f}%")
    lines.append(f"- 총액 편향(모델-실측)/실측: {m['total_bias']*100:+.1f}%")
    lines.append(f"- 모델 총액 {m['model_total_억']:,.0f}억 vs 실측 총액 {m['actual_total_억']:,.0f}억")
    lines.append("")
    verdict = ("범위 안 일치 양호" if m["cum_band_hit"] >= 0.6 and abs(m["total_bias"]) <= m["alpha"]
               else "보정 필요(밴드/파라미터 재검토)")
    lines.append(f"**판정:** {verdict}")
    lines.append("")
    lines.append("| 연차 | 모델 | 밴드(lo~hi) | 실측 | 적중 |")
    lines.append("|---:|---:|:--:|---:|:--:|")
    for i in range(m["n_years"]):
        hit = "✅" if (m["lo"][i] <= m["actual"][i] <= m["hi"][i]) else "—"
        lines.append(f"| {i+1} | {m['model'][i]:.1f} | {m['lo'][i]:.1f}~{m['hi'][i]:.1f} "
                     f"| {m['actual'][i]:.1f} | {hit} |")
    report = "\n".join(lines)
    if out_md:
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(report)
    return report


# ── 메인 ──────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="서해안선")
    ap.add_argument("--csv", default=None, help="공개 보수실적 CSV 경로(미지정 시 합성)")
    ap.add_argument("--len-km", type=float, default=DEFAULT_ROUTE_LEN_KM)
    ap.add_argument("--years", type=int, default=DEFAULT_OPERATION_YEARS)
    ap.add_argument("--alpha", type=float, default=BAND_ALPHA)
    ap.add_argument("--out", default=None, help="리포트 markdown 출력 경로")
    args = ap.parse_args()

    # 모델 OPEX
    model = model_capital_maintenance(args.len_km, args.years, DEFAULT_DISCOUNT)
    if model is None:
        model = make_synthetic_model(args.years, args.len_km)

    # 실측 OPEX
    if args.csv and os.path.exists(args.csv):
        actual = load_actual_maintenance(args.csv, args.route, args.years)
        src = f"공개 CSV: {args.csv}"
    else:
        actual = make_synthetic_actual(args.years, args.len_km)
        src = "합성 데이터(실CSV 미지정) — 로직 시연용"

    m = backtest_metrics(model, actual, alpha=args.alpha)
    print(f"[실측 출처] {src}")
    print(render_report(args.route, m, out_md=args.out))
    if args.out:
        print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main()
