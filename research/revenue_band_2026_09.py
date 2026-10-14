# -*- coding: utf-8 -*-
"""
통행료 수입 실현율 분포 학습: 후보 산출 스크립트 (2026-09)

목적
    검산 리포트 '통행료 수입 실현율' 행을 단일 점추정(KOTI RR-25-10 p.45, 10년 평균 62.3%)이
    아니라 P10/P50/P90 밴드로 제시할 수 있는지 판정한다. 판정 기준은 보고서
    (창업실습_3학년2학기/연구개발_수입실현율분포_2026-09.md §2)에 결과 계산 전 고정했다.

엔진 미반영 (VP 게이트 원칙)
    demand_bias.py, app.py, reverse_solver.py, interval_scoring.py 는 수정하지 않는다.
    엔진 함수는 읽기 전용 호출만 한다: interval_scoring.interval_score (채점식 동일),
    demand_bias.loo_prior_params (교통량 LOO prior 동일 기계). 산출물은 후보 파일뿐이다.

모형 (사전 고정 3개 + 기준선)
    M0  62.3% 점추정(밴드 없음, 폭 0 구간으로 채점)
    M1  직접 풀링 정규: 학습 노선 전 관측 평균 ± 1.2816·sd (교통량 loo_prior와 같은 기계)
    M2  분해형: 교통량 실현율(교통량 패널 LOO 정규) × 요금 실행률(toll_execution LOO 정규),
        독립 가정 곱의 10/50/90 백분위(결정론 적분: Gauss-Hermite 200점 + 이분법, '26-09-28 몬테카를로 판에서 교체)
    M3  부분 풀링: 일원배치 적률 추정 τ²(노선 간)·σ²(노선 내), 신규 노선 = μ ± z·sqrt(τ²+σ²)

채점
    노선 단위 LOO(채점 노선 전 연도를 학습에서 제외). 포함률·평균 폭·interval score(α=0.2).
    노선 군집 부트스트랩 4000회로 95% 신뢰구간(노선 내 연도 상관 반영).

재현
    PYTHONIOENCODING=utf-8 python research/revenue_band_2026_09.py
    난수 시드 고정(SEED), 입력 파일 sha256을 JSON에 기록.
"""
import csv
import hashlib
import json
import os
import sys
from collections import OrderedDict, defaultdict

sys.dont_write_bytecode = True   # 엔진 폴더에 캐시 파일을 새로 만들지 않음

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from interval_scoring import ALPHA, Z80, interval_score  # noqa: E402  (읽기 전용 재사용)
from demand_bias import loo_prior_params                  # noqa: E402  (읽기 전용 재사용)

DATA = os.path.join(ROOT, "data")
PANEL = os.path.join(DATA, "realization_panel.csv")
TOLL = os.path.join(DATA, "toll_execution_2026-09.csv")
META = os.path.join(DATA, "route_meta.csv")
TRAFFIC_SCORES = os.path.join(DATA, "interval_scores_v1.csv")
OUT_JSON = os.path.join(DATA, "revenue_band_candidate_2026-09.json")
OUT_CSV = os.path.join(DATA, "revenue_band_loo_scores_2026-09.csv")
REPORT_REL = "창업실습_3학년2학기/연구개발_수입실현율분포_2026-09.md"

# ── 사전 고정 상수 (보고서 §2와 동일, 결과 확인 후 변경 금지) ──────────────────────
CANDIDATE_TAG = "revband_cand_2026-09-28"
SEED = 20260928
N_BOOT = 4000          # 노선 군집 부트스트랩 반복
N_MC = 20000           # 호환용(미사용): M2는 '26-09-28부터 결정론 적분
N_MC_BOOT = 4000       # 호환용(미사용): M2는 '26-09-28부터 결정론 적분
M0_POINT = 0.623       # KOTI RR-25-10 p.45, 2014~24 10년 평균 62.33%
TARGET = 0.80
C1B_RANGE = (0.70, 0.90)
TRAFFIC_WIDTH_REF = 0.5178   # interval_scores_v1.csv 62관측 평균 폭(등록 기준값)

RESTRUCTURED_6 = ["인천공항", "천안-논산", "대구-부산", "일산-퇴계원", "부산-울산", "서울-춘천"]
S1_ROUTES = ["인천대교", "평택-시흥", "상주-영천"]      # 재구조화·협약 기준 변경 가능
S2_ROUTES = ["포천-화도", "평택-부여", "화성-광주"]      # 개통 초기 2 + 110.00% 상한 의심 1
SAMPLES = OrderedDict([
    ("주분석", {"exclude": [], "traffic_extra": []}),
    ("S1", {"exclude": S1_ROUTES, "traffic_extra": RESTRUCTURED_6}),
    ("S2", {"exclude": S2_ROUTES, "traffic_extra": []}),
    ("S3", {"exclude": S1_ROUTES + S2_ROUTES, "traffic_extra": RESTRUCTURED_6}),
])
MODELS = ["M0", "M1", "M2", "M3"]
FREE_PARAMS = {"M0": 0, "M1": 2, "M2": 4, "M3": 3}


# ── 입력 ──────────────────────────────────────────────────────────────
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load_revenue():
    rows, versions = [], set()
    with open(PANEL, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["지표"] == "수입":
                rows.append((r["노선"], int(r["연도"]), float(r["실현율_pct"]) / 100.0))
                versions.add(r["panel_version"])
    return rows, sorted(versions)


def load_traffic():
    rows = []
    with open(PANEL, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["지표"] == "교통량":
                rows.append((r["노선"], int(r["연도"]), float(r["실현율_pct"]) / 100.0))
    return rows


def load_toll():
    rows = []
    with open(TOLL, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append((r["노선"], int(r["연도"]), float(r["요금실행률"]),
                         float(r["교통량실현율_pct"]) / 100.0))
    return rows


def load_meta_routes():
    with open(META, encoding="utf-8-sig") as f:
        return {r["노선"]: r for r in csv.DictReader(f)}


def traffic_reference():
    hits, widths, iss = [], [], []
    with open(TRAFFIC_SCORES, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            hits.append(int(r["적중"]))
            widths.append(float(r["폭"]))
            iss.append(float(r["interval_score"]))
    w = float(np.mean(widths))
    assert abs(w - TRAFFIC_WIDTH_REF) < 5e-5, f"교통량 기준 폭 불일치: {w}"
    return {"source": "data/interval_scores_v1.csv (교통량 62관측, LOO 정규 + 초기군 고정)",
            "n": len(hits), "coverage": float(np.mean(hits)), "mean_width": w,
            "mean_IS": float(np.mean(iss))}


# ── 모형 적합 ─────────────────────────────────────────────────────────
def fit_m1(values):
    a = np.asarray(values, float)
    mu, sd = float(a.mean()), float(a.std(ddof=1))
    return {"mu": mu, "sd": sd, "n_obs": int(a.size),
            "band": (mu - Z80 * sd, mu, mu + Z80 * sd)}


def anova_mom(groups):
    """일원배치 적률 추정. groups: list of 1-D arrays (노선별 관측)."""
    groups = [np.asarray(g, float) for g in groups if len(g) > 0]
    k = len(groups)
    n_i = np.array([g.size for g in groups], float)
    N = n_i.sum()
    means = np.array([g.mean() for g in groups])
    grand = float(np.concatenate(groups).mean())
    ssw = float(sum(((g - g.mean()) ** 2).sum() for g in groups))
    ssb = float((n_i * (means - grand) ** 2).sum())
    msw = ssw / (N - k)
    msb = ssb / (k - 1)
    n0 = (N - (n_i ** 2).sum() / N) / (k - 1)
    tau2 = max(0.0, (msb - msw) / n0)
    sig2 = msw
    w = 1.0 / (tau2 + sig2 / n_i)
    mu = float((w * means).sum() / w.sum())
    return {"mu": mu, "tau2": tau2, "sigma2": sig2, "n0": float(n0), "k": k, "N": int(N),
            "ICC": tau2 / (tau2 + sig2) if (tau2 + sig2) > 0 else 0.0}


def fit_m3(groups):
    p = anova_mom(groups)
    s = float(np.sqrt(p["tau2"] + p["sigma2"]))
    p["pred_sd"] = s
    p["band"] = (p["mu"] - Z80 * s, p["mu"], p["mu"] + Z80 * s)
    return p


_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(200)
_GH_W = _GH_W / _GH_W.sum()


def _product_normal_quantiles(mt, st, me, se, probs=(0.10, 0.50, 0.90)):
    """X~N(mt,st) 와 Y~N(me,se) 독립 곱 XY의 분위수(결정론).
    F(z) = E_Y[Phi((z/Y - mt)/st)], Y는 Gauss-Hermite 200점 적분, 분위수는 이분법.
    Y(요금 실행률)는 평균 0.9·표준편차 0.08 수준이라 Y<=0 질량은 무시 가능(가드로 제외)."""
    from math import erf, sqrt
    y = me + se * _GH_X
    keep = y > 1e-9
    y, w = y[keep], _GH_W[keep] / _GH_W[keep].sum()
    vphi = np.vectorize(lambda v: 0.5 * (1.0 + erf(v / sqrt(2.0))))

    def cdf(z):
        return float(np.sum(w * vphi((z / y - mt) / st)))

    lo = (mt - 12 * st) * (me + 12 * se) if mt - 12 * st < 0 else (mt - 12 * st) * max(me - 12 * se, 1e-9)
    hi = (mt + 12 * st) * (me + 12 * se)
    out = []
    for p in probs:
        a, b = lo, hi
        for _ in range(80):
            m = 0.5 * (a + b)
            if cdf(m) < p:
                a = m
            else:
                b = m
        out.append(0.5 * (a + b))
    return tuple(out)


def fit_m2(traffic_vals, toll_vals, rng, n_mc):
    # '26-09-28 검증 반영: 몬테카를로(2만 회 단일 시드) 대신 결정론 적분. rng·n_mc 인자는 호환용으로만 유지.
    t = np.asarray(traffic_vals, float)
    e = np.asarray(toll_vals, float)
    mt, st = float(t.mean()), float(t.std(ddof=1))
    me, se = float(e.mean()), float(e.std(ddof=1))
    p10, p50, p90 = (float(x) for x in _product_normal_quantiles(mt, st, me, se))
    return {"mu_traffic": mt, "sd_traffic": st, "n_traffic": int(t.size),
            "mu_toll": me, "sd_toll": se, "n_toll": int(e.size),
            "band": (p10, p50, p90)}


def by_route(rows):
    d = defaultdict(list)
    for route, _y, v in rows:
        d[route].append(v)
    return d


# ── LOO 채점 ─────────────────────────────────────────────────────────
def run_sample(sample_id, name, spec, rev, traffic, toll, route_index):
    excl = set(spec["exclude"])
    rev_s = [r for r in rev if r[0] not in excl]
    routes = sorted({r[0] for r in rev_s})
    rows_out = []
    per_route = {m: {} for m in MODELS}     # route -> (hits, n, width_sum, is_sum, abs_err_sum)
    fold_params = {m: {} for m in MODELS}

    for route in routes:
        train = [r for r in rev_s if r[0] != route]
        test = [r for r in rev_s if r[0] == route]
        n_train_routes = len({r[0] for r in train})

        bands = {}
        bands["M0"] = (M0_POINT, M0_POINT, M0_POINT)
        m1 = fit_m1([v for _, _, v in train])
        bands["M1"] = m1["band"]
        # M2: 교통량 prior는 demand_bias.loo_prior_params 그대로(채점 노선·표본 제외 노선 제외)
        t_excl = sorted({route} | excl | set(spec["traffic_extra"]))
        tp = loo_prior_params(t_excl, panel_path=PANEL)
        tr_vals = [v for rr, _y, v in traffic if rr not in set(t_excl)]
        assert abs(np.mean(tr_vals) - tp["p1"]) < 1e-12 and abs(np.std(tr_vals, ddof=1) - tp["p2"]) < 1e-12
        e_vals = [e for rr, _y, e, _t in toll if rr not in ({route} | excl)]
        rng = np.random.default_rng([SEED, sample_id, route_index[route]])
        m2 = fit_m2(tr_vals, e_vals, rng, N_MC)
        bands["M2"] = m2["band"]
        m3 = fit_m3(list(by_route(train).values()))
        bands["M3"] = m3["band"]
        fold_params["M1"][route] = {k: m1[k] for k in ("mu", "sd", "n_obs")}
        fold_params["M2"][route] = {k: m2[k] for k in ("mu_traffic", "sd_traffic", "n_traffic",
                                                        "mu_toll", "sd_toll", "n_toll")}
        fold_params["M3"][route] = {k: m3[k] for k in ("mu", "tau2", "sigma2", "ICC")}

        for m in MODELS:
            lo, mid, hi = bands[m]
            hits = n = 0
            wsum = issum = aesum = 0.0
            for _r, y, v in sorted(test, key=lambda x: x[1]):
                hit = int(lo <= v <= hi)
                isc = interval_score(lo, hi, v, ALPHA)
                rows_out.append({
                    "표본": name, "모형": m, "노선": route, "연도": y,
                    "실현율": round(v, 4), "구간L": round(lo, 4), "구간중앙": round(mid, 4),
                    "구간U": round(hi, 4), "폭": round(hi - lo, 4), "적중": hit,
                    "interval_score": round(isc, 4),
                    "학습노선수": "외부상수" if m == "M0" else n_train_routes,
                    "학습관측수": "외부상수" if m == "M0" else len(train),
                })
                hits += hit
                n += 1
                wsum += hi - lo
                issum += isc
                aesum += abs(v - mid)
            per_route[m][route] = (hits, n, wsum, issum, aesum)
    return routes, per_route, rows_out, fold_params


def summarize(routes, per_route, sample_id):
    k = len(routes)
    rng = np.random.default_rng([SEED, sample_id, 999])
    idx = rng.integers(0, k, size=(N_BOOT, k))
    counts = np.zeros((N_BOOT, k))
    for j in range(k):
        counts[:, j] = (idx == j).sum(axis=1)
    arr = {m: np.array([per_route[m][r] for r in routes], float) for m in MODELS}
    out = {}
    boot_is = {}
    for m in MODELS:
        a = arr[m]
        hits, n, ws, iss, ae = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        cov = hits.sum() / n.sum()
        route_cov = float(np.mean(hits / n))
        bn = counts @ n
        b_cov = (counts @ hits) / bn
        b_w = (counts @ ws) / bn
        b_is = (counts @ iss) / bn
        boot_is[m] = b_is
        out[m] = {
            "n_obs": int(n.sum()), "n_routes": k,
            "coverage": float(cov),
            "coverage_ci95": [float(x) for x in np.percentile(b_cov, [2.5, 97.5])],
            "route_weighted_coverage": route_cov,
            "routes_fully_covered": int((hits == n).sum()),
            "routes_fully_missed": int((hits == 0).sum()),
            "mean_width": float(ws.sum() / n.sum()),
            "mean_width_ci95": [float(x) for x in np.percentile(b_w, [2.5, 97.5])],
            "mean_IS": float(iss.sum() / n.sum()),
            "mean_IS_ci95": [float(x) for x in np.percentile(b_is, [2.5, 97.5])],
            "MAE_center": float(ae.sum() / n.sum()),
        }
    for m in MODELS:
        if m == "M0":
            continue
        d = boot_is[m] - boot_is["M0"]
        out[m]["delta_IS_vs_M0"] = out[m]["mean_IS"] - out["M0"]["mean_IS"]
        out[m]["delta_IS_vs_M0_ci95"] = [float(x) for x in np.percentile(d, [2.5, 97.5])]
    pair = {}
    for a_, b_ in (("M1", "M2"), ("M1", "M3"), ("M2", "M3")):
        d = boot_is[a_] - boot_is[b_]
        pair[f"{a_}-{b_}"] = {"delta_IS": out[a_]["mean_IS"] - out[b_]["mean_IS"],
                             "ci95": [float(x) for x in np.percentile(d, [2.5, 97.5])]}
    return out, pair


def criteria(res):
    m0_is = res["M0"]["mean_IS"]
    crit = {}
    for m in MODELS:
        r = res[m]
        lo, hi = r["coverage_ci95"]
        c = OrderedDict([
            ("C1a", bool(lo <= TARGET <= hi)),
            ("C1b", bool(C1B_RANGE[0] <= r["coverage"] <= C1B_RANGE[1])),
            ("C2", bool(r["mean_width"] <= TRAFFIC_WIDTH_REF)),
            ("C3", bool(r["mean_IS"] < m0_is) if m != "M0" else False),
        ])
        c["all_pass"] = all(c.values())
        crit[m] = c
    return crit


# ── 전 표본 적합과 분위수 부트스트랩 ──────────────────────────────────────────
def full_fit(model, rev_s, traffic_s, toll_s, rng):
    if model == "M1":
        return fit_m1([v for _, _, v in rev_s])
    if model == "M3":
        return fit_m3(list(by_route(rev_s).values()))
    if model == "M2":
        return fit_m2([v for _, _, v in traffic_s], [e for _, _, e, _ in toll_s], rng, N_MC)
    raise ValueError(model)


def quantile_bootstrap(model, rev_s, traffic_s, toll_s, sample_id):
    """노선 군집 부트스트랩으로 전 표본 P10/P50/P90의 95% 신뢰구간."""
    rng = np.random.default_rng([SEED, sample_id, 777])
    rev_g = by_route(rev_s)
    rev_routes = sorted(rev_g)
    tr_g = by_route(traffic_s)
    tr_routes = sorted(tr_g)
    to_g = defaultdict(list)
    for r, _y, e, _t in toll_s:
        to_g[r].append(e)
    to_routes = sorted(to_g)
    qs = []
    for _ in range(N_BOOT):
        if model in ("M1", "M3"):
            pick = rng.integers(0, len(rev_routes), len(rev_routes))
            groups = [rev_g[rev_routes[j]] for j in pick]
            if model == "M1":
                band = fit_m1([v for g in groups for v in g])["band"]
            else:
                band = fit_m3(groups)["band"]
        else:
            pt = rng.integers(0, len(tr_routes), len(tr_routes))
            pe = rng.integers(0, len(to_routes), len(to_routes))
            tv = [v for j in pt for v in tr_g[tr_routes[j]]]
            ev = [v for j in pe for v in to_g[to_routes[j]]]
            band = fit_m2(tv, ev, rng, N_MC_BOOT)["band"]
        qs.append(band)
    qs = np.array(qs)
    return {f"P{p}": [float(x) for x in np.percentile(qs[:, i], [2.5, 97.5])]
            for i, p in enumerate((10, 50, 90))}


# ── 기술 통계 ─────────────────────────────────────────────────────────
def descriptives(rev, toll):
    g = by_route(rev)
    route_means = {r: float(np.mean(v)) for r, v in g.items()}
    years = defaultdict(list)
    complete = [r for r, v in g.items() if len(v) == 5]
    for r, y, v in rev:
        if r in complete:
            years[y].append(v)
    t = np.array([x[3] for x in toll])
    e = np.array([x[2] for x in toll])
    tg, eg = defaultdict(list), defaultdict(list)
    for r, _y, ee, tt in toll:
        tg[r].append(tt)
        eg[r].append(ee)
    rm_t = np.array([np.mean(tg[r]) for r in sorted(tg)])
    rm_e = np.array([np.mean(eg[r]) for r in sorted(eg)])
    return {
        "n_obs": len(rev), "n_routes": len(g),
        "obs_mean": float(np.mean([v for _, _, v in rev])),
        "obs_sd": float(np.std([v for _, _, v in rev], ddof=1)),
        "route_mean_of_means": float(np.mean(list(route_means.values()))),
        "min": float(min(v for _, _, v in rev)), "max": float(max(v for _, _, v in rev)),
        "route_means": {r: round(v, 4) for r, v in sorted(route_means.items(), key=lambda x: x[1])},
        "year_means_complete_routes": {"routes": len(complete),
                                        "by_year": {y: round(float(np.mean(v)), 4)
                                                    for y, v in sorted(years.items())}},
        "toll_file": {"n_obs": int(e.size), "n_routes": len(eg),
                      "toll_mean": float(e.mean()), "toll_sd": float(e.std(ddof=1)),
                      "corr_traffic_toll_obs": float(np.corrcoef(t, e)[0, 1]),
                      "corr_traffic_toll_route_means": float(np.corrcoef(rm_t, rm_e)[0, 1])},
    }


def main():
    rev, versions = load_revenue()
    traffic = load_traffic()
    toll = load_toll()
    meta = load_meta_routes()
    ref = traffic_reference()
    all_routes = sorted({r[0] for r in rev})
    route_index = {r: i for i, r in enumerate(all_routes)}
    assert len(rev) == 78 and len(all_routes) == 17, (len(rev), len(all_routes))

    loo, pairs, crits, all_rows, sample_routes = {}, {}, {}, [], {}
    for sid, (name, spec) in enumerate(SAMPLES.items()):
        routes, per_route, rows_out, _fp = run_sample(sid, name, spec, rev, traffic, toll, route_index)
        res, pair = summarize(routes, per_route, sid)
        loo[name], pairs[name], crits[name] = res, pair, criteria(res)
        all_rows.extend(rows_out)
        sample_routes[name] = routes

    # 사후 진단 D1 (결과 확인 후 추가, 판정 미사용): 주분석 표본 그대로 두고 M2 교통량 학습에서
    # 재구조화 6노선만 제외. M2 폭 우위가 수입 모집단 밖(재구조화 노선) 교통량 자료에 기대는지 분리 확인
    d1_spec = {"exclude": [], "traffic_extra": RESTRUCTURED_6}
    d1_routes, d1_pr, _rows, _fp = run_sample(10, "사후진단D1", d1_spec, rev, traffic, toll, route_index)
    d1_res, _pair = summarize(d1_routes, d1_pr, 10)
    d1_crit = criteria(d1_res)

    # 채택: 주분석 4기준 통과 모형 중 평균 IS 최소, 동률 시 자유 모수 적은 모형
    passing = [m for m in ("M1", "M2", "M3") if crits["주분석"][m]["all_pass"]]
    adopted = None
    if passing:
        adopted = sorted(passing, key=lambda m: (round(loo["주분석"][m]["mean_IS"], 6), FREE_PARAMS[m]))[0]
    if adopted is None:
        verdict = "미작동"
        sens_fail = []
    else:
        sens_fail = [s for s in ("S1", "S2", "S3") if not crits[s][adopted]["C1a"]]
        verdict = "작동" if not sens_fail else "조건부 작동"
    best_ref = sorted(("M1", "M2", "M3"), key=lambda m: loo["주분석"][m]["mean_IS"])[0]

    # 전 표본 적합(모든 후보) + 채택(또는 최선 참고) 모형 분위수 부트스트랩
    full = {}
    for sid, (name, spec) in enumerate(SAMPLES.items()):
        excl = set(spec["exclude"])
        rev_s = [r for r in rev if r[0] not in excl]
        tr_s = [r for r in traffic if r[0] not in (excl | set(spec["traffic_extra"]))]
        to_s = [r for r in toll if r[0] not in excl]
        full[name] = {}
        for m in ("M1", "M2", "M3"):
            rng = np.random.default_rng([SEED, sid, 555])
            f = full_fit(m, rev_s, tr_s, to_s, rng)
            band = f.pop("band")
            f["P10"], f["P50"], f["P90"] = band
            full[name][m] = f
    target_model = adopted or best_ref
    q_ci = {}
    for sid, (name, spec) in enumerate(SAMPLES.items()):
        excl = set(spec["exclude"])
        rev_s = [r for r in rev if r[0] not in excl]
        tr_s = [r for r in traffic if r[0] not in (excl | set(spec["traffic_extra"]))]
        to_s = [r for r in toll if r[0] not in excl]
        q_ci[name] = quantile_bootstrap(target_model, rev_s, tr_s, to_s, sid)

    desc = descriptives(rev, toll)
    anyang_in_meta = "안양-성남" in meta

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    def pct(x):
        return round(100.0 * x, 1)

    band_main = full["주분석"][target_model]
    out = OrderedDict()
    out["candidate_tag"] = CANDIDATE_TAG
    out["created"] = "2026-09-28"
    out["panel_version"] = versions[0] if len(versions) == 1 else versions
    out["engine_reflected"] = False
    out["vp_gate"] = ("엔진(demand_bias.py·app.py·reverse_solver.py) 미반영 후보. 반영은 VP 게이트"
                      "(3안 비교·pytest 회귀 재채점) 통과 후에만")
    out["report"] = REPORT_REL
    out["script"] = "research/revenue_band_2026_09.py"
    out["inputs_sha256"] = {os.path.relpath(p, ROOT).replace("\\", "/"): sha256(p)
                            for p in (PANEL, TOLL, META, TRAFFIC_SCORES)}
    out["preregistration"] = {
        "registered": "2026-09-28, LOO 결과 계산 전 (보고서 §2)",
        "interval": "80% 중심구간, 정규 z=1.2816 (interval_scoring.Z80)",
        "scoring": "노선 단위 LOO, interval score alpha=0.2, 노선 군집 부트스트랩 4000회 95% CI",
        "C1a": "LOO 포함률 부트스트랩 95% CI가 0.80 포함",
        "C1b": "LOO 포함률 점추정 0.70~0.90",
        "C2": f"LOO 평균 폭 <= {TRAFFIC_WIDTH_REF} (교통량 밴드 평균 폭)",
        "C3": "LOO 평균 interval score < M0",
        "adopt": "4기준 통과 모형 중 평균 IS 최소, 동률 시 자유 모수 적은 모형",
        "verdict_rule": "작동=채택 모형 존재·S1/S2/S3 전부 C1a 통과, 조건부 작동=채택 모형 존재·민감도 1개 이상 C1a 미통과, 미작동=채택 모형 없음",
        "seed": SEED,
    }
    out["data_summary"] = desc
    out["data_notes"] = {
        "toll_execution_routes": sorted({r[0] for r in toll}),
        "toll_execution_note": "40 route-year·15노선. 화성-광주(상한 의심)·옥산-오창(교통량 없음) 미포함, 서수원-평택 2022 미포함(원 파일 그대로 사용)",
        "anyang_in_route_meta": anyang_in_meta,
        "restructured_6_in_revenue_panel": False,
    }
    out["traffic_band_reference"] = ref
    out["models"] = OrderedDict([
        ("M0", {"desc": "KOTI RR-25-10 p.45 10년 평균 점추정, 밴드 없음", "free_params": 0,
                "point": M0_POINT}),
        ("M1", {"desc": "직접 풀링 정규(노선×연도 풀링, ddof=1)", "free_params": 2,
                "full_sample": {k: full["주분석"]["M1"][k] for k in full["주분석"]["M1"]}}),
        ("M2", {"desc": "교통량 실현율 정규 × 요금 실행률 정규, 독립 가정 곱의 결정론 적분(Gauss-Hermite 200점)", "free_params": 4,
                "full_sample": {k: full["주분석"]["M2"][k] for k in full["주분석"]["M2"]}}),
        ("M3", {"desc": "부분 풀링(일원배치 적률 τ²·σ²), 신규 노선 μ±z·sqrt(τ²+σ²)", "free_params": 3,
                "full_sample": {k: full["주분석"]["M3"][k] for k in full["주분석"]["M3"]}}),
    ])
    out["loo_results"] = {s: {"routes": sample_routes[s], "by_model": loo[s],
                              "criteria": crits[s], "paired_IS": pairs[s]} for s in SAMPLES}
    out["full_sample_bands_by_sample"] = {s: {m: {k: full[s][m][k] for k in ("P10", "P50", "P90")}
                                              for m in full[s]} for s in SAMPLES}
    out["adopted_model"] = adopted
    out["reference_model_if_none"] = None if adopted else best_ref
    out["band_model"] = target_model
    out["band_full_sample"] = {
        "model": target_model, "status": "채택" if adopted else "참고(채택 아님)",
        "P10": band_main["P10"], "P50": band_main["P50"], "P90": band_main["P90"],
        "P10_pct": pct(band_main["P10"]), "P50_pct": pct(band_main["P50"]),
        "P90_pct": pct(band_main["P90"]),
        "bootstrap_ci95": q_ci["주분석"],
    }
    out["band_by_sensitivity"] = {s: {"P10_pct": pct(full[s][target_model]["P10"]),
                                      "P50_pct": pct(full[s][target_model]["P50"]),
                                      "P90_pct": pct(full[s][target_model]["P90"]),
                                      "bootstrap_ci95": q_ci[s]} for s in SAMPLES}
    out["verdict"] = verdict
    out["sensitivity_C1a_fail"] = sens_fail
    out["sensitivity_all_criteria"] = {s: {m: crits[s][m]["all_pass"] for m in ("M1", "M2", "M3")}
                                       for s in ("S1", "S2", "S3")}
    out["post_hoc_diagnostics"] = {
        "note": "결과 확인 후 추가한 진단. 사전 판정 규칙에 사용하지 않음",
        "D1_M2_traffic_excl_restructured6": {
            "desc": "주분석 17노선 채점, M2 교통량 학습에서 재구조화 6노선 제외",
            "M2": {k: d1_res["M2"][k] for k in ("coverage", "coverage_ci95", "mean_width",
                                                 "mean_IS", "mean_IS_ci95")},
            "M2_criteria": d1_crit["M2"],
        },
    }
    out["limitations"] = [
        "수입 패널 2021~2025 동일 시대 자료: 노선 분리 검증일 뿐 시점 분리 검증 아님",
        "유효 표본은 관측 78이 아니라 노선 17(노선 내 연도 상관). 부트스트랩 CI 폭이 넓음",
        "노선 내 연차 하락 경로(통행료 동결 누적)·운영 연차 미반영. 밴드는 연차 무조건부",
        "M2는 교통량·요금 실행률 독립 가정, 요금 실행률 자료는 2022~2024·15노선",
        "M0 62.3%는 표본 중복 가능 외부 상수로 LOO 적용 불가",
        "징수액은 차액보전금·재정보조·IC 초과수입·부가통행료 제외 기준(NABO 각주)",
    ]
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # ── 콘솔 요약 ──
    print(f"[교통량 기준] n={ref['n']} 포함률 {pct(ref['coverage'])}% 폭 {pct(ref['mean_width'])}%p IS {ref['mean_IS']:.3f}")
    for s in SAMPLES:
        print(f"== {s} (노선 {len(sample_routes[s])}, 관측 {loo[s]['M1']['n_obs']})")
        for m in MODELS:
            r, c = loo[s][m], crits[s][m]
            print(f"  {m}: 포함률 {pct(r['coverage'])}% CI[{pct(r['coverage_ci95'][0])}, {pct(r['coverage_ci95'][1])}]"
                  f" 노선가중 {pct(r['route_weighted_coverage'])}% 폭 {pct(r['mean_width'])}%p"
                  f" IS {r['mean_IS']:.3f} CI[{r['mean_IS_ci95'][0]:.3f}, {r['mean_IS_ci95'][1]:.3f}]"
                  f" MAE {pct(r['MAE_center'])}%p | " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in c.items()))
        for k, v in pairs[s].items():
            print(f"    ΔIS {k}: {v['delta_IS']:+.3f} CI[{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]")
    print("채택:", adopted, "| 참고 최선:", best_ref, "| 판정:", verdict, "| 민감도 C1a 미통과:", sens_fail)
    r = d1_res["M2"]
    print(f"[사후진단 D1, 판정 미사용] M2 교통량 학습 재구조화6 제외: 포함률 {pct(r['coverage'])}% "
          f"CI[{pct(r['coverage_ci95'][0])}, {pct(r['coverage_ci95'][1])}] 폭 {pct(r['mean_width'])}%p "
          f"IS {r['mean_IS']:.3f} | " + " ".join(f"{k}={'O' if v else 'X'}" for k, v in d1_crit['M2'].items()))
    for m in ("M0", "M1", "M2", "M3"):
        if m != "M0":
            print(f"  {m} ΔIS vs M0 (주분석): {loo['주분석'][m]['delta_IS_vs_M0']:+.3f} "
                  f"CI{[round(x, 3) for x in loo['주분석'][m]['delta_IS_vs_M0_ci95']]}")
    for s in SAMPLES:
        b = out["band_by_sensitivity"][s]
        print(f"  밴드({target_model}, {s}): P10 {b['P10_pct']} / P50 {b['P50_pct']} / P90 {b['P90_pct']}")
    print("CI(주분석):", {k: [pct(x) for x in v] for k, v in q_ci["주분석"].items()})
    print("기술통계:", json.dumps({k: desc[k] for k in ("obs_mean", "obs_sd", "route_mean_of_means", "min", "max")}, ensure_ascii=False))
    print("연도별(5개년 완비 노선):", desc["year_means_complete_routes"])
    print("요금파일:", desc["toll_file"])
    print("M3 전 표본:", {k: round(v, 4) if isinstance(v, float) else v for k, v in full["주분석"]["M3"].items()})
    print("M2 전 표본:", {k: round(v, 4) if isinstance(v, float) else v for k, v in full["주분석"]["M2"].items()})
    print("생성:", OUT_JSON, OUT_CSV)


if __name__ == "__main__":
    main()
