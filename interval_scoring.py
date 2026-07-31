# -*- coding: utf-8 -*-
"""
Interval score(폭 벌점) 최초 산출 — 검증 프로토콜 v2 조건 4 이행

목적: 밴드 채점을 0·1 적중만으로 하면 밴드를 넓힐수록 이기는 게임이 가능하다.
80% 중심구간의 interval score(Gneiting & Raftery 2007)를 R3 보조 지표로 병기해
커버리지와 선명도(sharpness·폭)를 동시에 벌점화한다.

IS_α(L,U;r) = (U−L) + (2/α)·(L−r)·1{r<L} + (2/α)·(r−U)·1{r>U},  α=0.2
(낮을수록 좋음 — 폭이 좁으면서 관측을 담아야 최소)

표본·밴드 규약 (케이스 스크립트와 동일 기계):
- 관측 = data/realization_panel.csv 교통량 62건(22노선×'22~'24, KOTI 표5-11)
- 밴드 = 노선별 LOO prior(자기 노선 제외 61−k 관측) 정규 분위수 mu ± 1.2816·sd
  → 62관측 전체가 leave-one-route-out 교차검증 셋이 된다(자기 학습 데이터 채점 아님)
- 개통 초기(운영 1~3년차 — 포천-화도·평택-부여 '24) = 초기군 고정 밴드 0.37~0.81
  (케이스 규약과 동일: demand_bias '국내 민자 보수(초기군)' lognormal P10/P90)
출력: data/interval_scores_v1.csv + 요약(커버리지·평균 폭·평균 IS)
"""
import csv
import os

import numpy as np

from backtest_plan_actual import loo_prior

Z80 = 1.2816
ALPHA = 0.2
EARLY_BAND = (0.37, 0.81)   # 초기군(운영 1~3년차) 고정 밴드 — 케이스 규약
EARLY_ROUTES_2024 = {"포천-화도", "평택-부여"}   # '24 개통 → '24 관측 = 운영 1년차

# 원장(verification_ledger) 채점 대상 13노선 — route-overlap-audit 확정
LEDGER_OVERLAP = {
    "인천공항", "광주-원주", "천안-논산", "대구-부산", "일산-퇴계원", "서울-춘천",
    "부산-울산", "인천대교", "서수원-평택", "용인-서울", "인천-김포", "안양-성남", "상주-영천",
}
# loo_prior(표5-11)의 원문 노선명 매핑 (패널 canonical → 표5-11 표기)
TO_TABLE = {"인천공항": "인천국제공항", "일산-퇴계원": "서울외곽",
            "부산신항제2배후": "부산신항 제2배후"}


def interval_score(lo: float, hi: float, r: float, alpha: float = ALPHA) -> float:
    s = hi - lo
    if r < lo:
        s += (2.0 / alpha) * (lo - r)
    elif r > hi:
        s += (2.0 / alpha) * (r - hi)
    return s


def run(panel_path: str = None, out_path: str = None) -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    panel_path = panel_path or os.path.join(here, "data", "realization_panel.csv")
    out_path = out_path or os.path.join(here, "data", "interval_scores_v1.csv")

    obs = []
    with open(panel_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["지표"] == "교통량":
                obs.append((row["노선"], int(row["연도"]), float(row["실현율_pct"]) / 100.0))

    rows = []
    for canon, year, r in obs:
        table_name = TO_TABLE.get(canon, canon)
        if canon in EARLY_ROUTES_2024:
            lo, hi = EARLY_BAND
            band_src = "초기군 고정(운영 1~3년차)"
        else:
            pri = loo_prior(table_name)
            mu, sd = pri["loo_mean"], pri["loo_sd"]
            lo, hi = mu - Z80 * sd, mu + Z80 * sd
            band_src = f"LOO 정규(n={pri['loo_n']})"
        hit = int(lo <= r <= hi)
        rows.append({
            "노선": canon, "연도": year, "실현율": round(r, 4),
            "밴드L": round(lo, 4), "밴드U": round(hi, 4), "폭": round(hi - lo, 4),
            "적중": hit, "interval_score": round(interval_score(lo, hi, r), 4),
            "밴드근거": band_src,
            "원장채점군": int(canon in LEDGER_OVERLAP),
        })

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def agg(subset):
        a = [x for x in rows if subset(x)]
        return {
            "n": len(a),
            "coverage": sum(x["적중"] for x in a) / len(a),
            "mean_width": float(np.mean([x["폭"] for x in a])),
            "mean_IS": float(np.mean([x["interval_score"] for x in a])),
        }

    return {
        "all62": agg(lambda x: True),
        "ledger13": agg(lambda x: x["원장채점군"] == 1),
        "out_path": out_path,
        "rows": rows,
    }


# 원장 노선명 → 표5-11 표기 (관측 원장 전체 IS용)
LEDGER_TO_TABLE = {
    "인천공항고속도로": "인천국제공항",
    "광주-원주(제2영동)": "광주-원주",
    "수도권1순환 퇴계원-일산": "서울외곽",
}


def run_full(obs_path: str = None, out_path: str = None) -> dict:
    """관측 원장(observation_ledger_v1.csv) 98관측 전체 interval score.

    밴드는 각 관측의 '밴드체계' 열(케이스 스크립트가 실제 적용한 기계) 그대로:
    LOO=노선별 제외 prior / 전체62=전 표본 prior / 초기군=0.37~0.81 고정.
    재산출 적중을 원장 밴드적중과 케이스 단위로 대사한다(재현 검증).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    obs_path = obs_path or os.path.join(here, "data", "observation_ledger_v1.csv")
    out_path = out_path or os.path.join(here, "data", "interval_scores_full_v1.csv")

    rows = []
    with open(obs_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            r = float(row["실현율_pct"]) / 100.0
            regime = row["밴드체계"]
            if regime == "초기군":
                lo, hi = EARLY_BAND
            else:
                name = LEDGER_TO_TABLE.get(row["노선"], row["노선"])
                pri = loo_prior(name)   # 표본 외 노선이면 loo == 전체 62관측
                mu, sd = pri["loo_mean"], pri["loo_sd"]
                lo, hi = mu - Z80 * sd, mu + Z80 * sd
            rows.append({
                "V": row["V"], "노선": row["노선"], "연도": row["연도"],
                "실현율": round(r, 4), "밴드체계": regime,
                "밴드L": round(lo, 4), "밴드U": round(hi, 4),
                "폭": round(hi - lo, 4), "적중": int(lo <= r <= hi),
                "interval_score": round(interval_score(lo, hi, r), 4),
            })

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def agg(sub):
        a = [x for x in rows if sub(x)]
        if not a:
            return {"n": 0}
        return {"n": len(a), "coverage": sum(x["적중"] for x in a) / len(a),
                "mean_width": float(np.mean([x["폭"] for x in a])),
                "mean_IS": float(np.mean([x["interval_score"] for x in a]))}

    return {
        "all": agg(lambda x: True),
        "by_regime": {k: agg(lambda x, k=k: x["밴드체계"] == k)
                      for k in ("LOO", "전체62", "초기군")},
        "rows": rows, "out_path": out_path,
    }


if __name__ == "__main__":
    res = run()
    for k in ("all62", "ledger13"):
        a = res[k]
        print(f"[{k}] n={a['n']} · 커버리지 {a['coverage']*100:.1f}% (목표 80%) · "
              f"평균 폭 {a['mean_width']*100:.1f}%p · 평균 IS {a['mean_IS']:.3f}")
    worst = sorted(res["rows"], key=lambda x: -x["interval_score"])[:5]
    print("IS 벌점 상위 5:", [(w["노선"], w["연도"], w["interval_score"]) for w in worst])
    print("생성:", res["out_path"])
