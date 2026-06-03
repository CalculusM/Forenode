"""
sensitivity_tab.py — 민감도·시나리오·리스크 등록부 UI (pre3.0 신규)

포지셔닝: "수요는 외부 입력, Forenode는 그 가정에 대한 민감도·리스크를 자동화한다."
이 탭은 수요를 예측하지 않는다. 사용자가 넣은 BASE(수요·공사비·금리)를 흔들어
DSCR·LLCR·IRR·NPV 반응과 대주단 실사(DD)용 리스크 등록부를 산출한다.

scenario_engine.py(순수 계산)를 호출만 한다. app.py 에서:
    from sensitivity_tab import render_sensitivity_tab
    render_sensitivity_tab(base_params, daily_traffic=..., benchmark_aadt=...)
"""
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from scenario_engine import (
    BaseCase, run_scenario, one_way_sensitivity, tornado,
    monte_carlo, risk_register, optimism_flag, sculpt_debt,
)


# DSCR covenant 밴드 (PF 대주단 실무)
_DSCR_BASE = 1.30      # base-case
_DSCR_LOCKUP = 1.20    # 배당제한(lock-up)
_DSCR_DEFAULT = 1.05   # 기술적 default 근처


def _base_case_from_params(base_params: dict, daily_traffic: float = 0.0,
                           road_length_km: float = 0.0) -> BaseCase:
    """app.py 의 base_params dict → scenario_engine.BaseCase 매핑."""
    return BaseCase(
        capex_억=base_params["capex_억"],
        annual_revenue_억=base_params["annual_revenue_억"],
        wacc=base_params["discount_rate"],
        debt_rate=base_params["debt_rate"],
        construction_years=base_params["construction_years"],
        operation_years=base_params["operation_years"],
        opex_ratio=base_params["opex_ratio"],
        inflation=base_params["inflation"],
        growth_rate=base_params["growth_rate"],
        equity_ratio=base_params["equity_ratio"],
        business_type=base_params["business_type"],
        tax_rate=base_params.get("tax_rate", 0.22),
        mrg_ratio=base_params.get("mrg_ratio", 0.0),
        mcc_ratio=base_params.get("mcc_ratio", 0.0),
        daily_traffic=daily_traffic,
        road_length_km=road_length_km,
    )


def render_sensitivity_tab(base_params: dict, daily_traffic: float = 0.0,
                           road_length_km: float = 0.0,
                           benchmark_aadt=None,
                           cov_base: float = _DSCR_BASE,
                           cov_lockup: float = _DSCR_LOCKUP,
                           cov_default: float = _DSCR_DEFAULT):
    st.subheader("민감도 · 시나리오 · 리스크 등록부")
    st.caption(
        "수요·통행량은 **외부 입력 가정**으로 둡니다(Forenode는 수요를 예측하지 않습니다). "
        "이 탭은 그 가정을 흔들었을 때 DSCR·LLCR·IRR·NPV가 어떻게 움직이는지와, "
        "대주단·운용사 실사에서 요구하는 리스크 등록부를 자동 산출합니다."
    )

    base = _base_case_from_params(base_params, daily_traffic, road_length_km)

    # 참고: 민감도 시나리오는 OPEX를 비율(opex_ratio)로 단순화해 재계산하므로
    # 메인 화면(자동 OPEX 시계열) DSCR과 소수점 단위 차이가 날 수 있습니다.
    try:
        base_res = run_scenario(base)
    except Exception as e:
        st.error(f"기준 시나리오 계산 실패: {e}")
        return

    # ── 기준 케이스 요약 ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("기준 NPV(억)", f"{base_res['npv']:,.0f}")
    c2.metric("기준 자기자본IRR", f"{base_res['equity_irr']*100:,.1f}%"
              if not np.isnan(base_res['equity_irr']) else "—")
    c3.metric("기준 DSCR_min", f"{base_res['dscr_min']:.2f}")
    c4.metric("기준 LLCR_min", f"{base_res['llcr_min']:.2f}"
              if not np.isnan(base_res['llcr_min']) else "—")
    st.caption(f"DSCR covenant(텀시트 입력) — base {cov_base:.2f} / lock-up {cov_lockup:.2f} / default {cov_default:.2f}")

    with st.expander("ⓘ 이 탭의 LLCR이 현금흐름표 LLCR과 소수점 차이가 나는 이유"):
        st.markdown(
            "이 탭의 **LLCR_min**은 각 운영연도 **연초(직전 연도 말) 잔존부채** 기준으로, "
            "현금흐름표의 LLCR은 **연말 잔존부채** 기준으로 계산합니다. 둘 다 통용되는 관행이며 "
            "시점 규약 차이일 뿐 오류가 아닙니다. 또한 민감도 시나리오는 OPEX를 비율로 단순화해 "
            "재계산하므로 메인 화면(자동 OPEX 시계열)과도 소수점 단위 차이가 있을 수 있습니다."
        )

    st.divider()

    # ── 1. 토네이도 (어떤 변수가 DSCR을 가장 흔드나) ──
    st.markdown("##### 1. 토네이도 — DSCR_min 민감도 순위")
    metric_label = {"dscr_min": "DSCR_min", "npv": "NPV", "equity_irr": "자기자본IRR"}
    tmetric = st.selectbox("토네이도 기준 지표", ["dscr_min", "npv", "equity_irr"],
                           format_func=lambda k: metric_label[k], key="sens_tornado_metric")
    try:
        tdf = tornado(base, metric=tmetric)
        base_metric = tdf.attrs.get("base_metric", base_res[tmetric])
        var_kr = {"demand": "수요 ±20%", "capex": "공사비 −10%/+30%", "rate": "금리 ±150bp"}
        fig = go.Figure()
        for _, row in tdf.iterrows():
            lo, hi = row["metric_low"], row["metric_high"]
            fig.add_trace(go.Bar(
                y=[var_kr.get(row["variable"], row["variable"])],
                x=[hi - lo], base=min(lo, hi), orientation="h",
                marker_color="#3b6ea5", showlegend=False,
                hovertemplate=f"low={lo:.2f}<br>high={hi:.2f}<extra></extra>",
            ))
        fig.add_vline(x=base_metric, line_dash="dash", line_color="#888",
                      annotation_text=f"기준 {base_metric:.2f}")
        fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title=metric_label[tmetric])
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"토네이도 계산 실패: {e}")

    st.divider()

    # ── 2. 일방향 민감도 ──
    st.markdown("##### 2. 일방향 민감도")
    var = st.radio("변수 선택", ["demand", "capex", "rate"], horizontal=True,
                   format_func=lambda v: {"demand": "수요(매출)", "capex": "공사비",
                                          "rate": "금리(절대 가산)"}[v], key="sens_oneway_var")
    if var == "rate":
        values = [-0.015, -0.010, -0.005, 0.0, 0.005, 0.010, 0.015]
        xlabel = "금리 가산(%p)"
        xfmt = [f"{v*100:+.1f}" for v in values]
    else:
        values = [0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30]
        xlabel = "수요 배수" if var == "demand" else "공사비 배수"
        xfmt = [f"{v:.2f}×" for v in values]
    try:
        sdf = one_way_sensitivity(base, var, values)
        sdf.insert(0, "케이스", xfmt)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=xfmt, y=sdf["dscr_min"], name="DSCR_min",
                                  mode="lines+markers", line_color="#3b6ea5"))
        fig2.add_hline(y=cov_lockup, line_dash="dot", line_color="#d9822b",
                       annotation_text=f"lock-up {cov_lockup:.2f}")
        fig2.add_hline(y=cov_default, line_dash="dot", line_color="#c0392b",
                       annotation_text=f"default {cov_default:.2f}")
        fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                           xaxis_title=xlabel, yaxis_title="DSCR_min")
        st.plotly_chart(fig2, use_container_width=True)
        show = sdf.copy()
        for col in ("npv",):
            show[col] = show[col].map(lambda x: f"{x:,.0f}")
        for col in ("nominal_irr",):
            show[col] = show[col].map(lambda x: f"{x*100:.1f}%" if not np.isnan(x) else "—")
        for col in ("dscr_min", "llcr_min", "ebitda_avg"):
            show[col] = show[col].map(lambda x: f"{x:.2f}" if not np.isnan(x) else "—")
        show = show.rename(columns={"npv": "NPV(억)", "nominal_irr": "명목IRR",
                                    "dscr_min": "DSCR_min", "llcr_min": "LLCR_min",
                                    "ebitda_avg": "EBITDA평균(억)"})
        st.dataframe(show.drop(columns=[var]), use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"일방향 민감도 계산 실패: {e}")

    st.divider()

    # ── 3. 몬테카를로 하방확률 ──
    st.markdown("##### 3. 몬테카를로 — 하방 리스크 확률")
    mc1, mc2, mc3 = st.columns(3)
    demand_sd = mc1.slider("수요 변동성(σ)", 0.05, 0.40, 0.15, 0.01, key="sens_mc_dsd")
    capex_sd = mc2.slider("공사비 변동성(σ)", 0.05, 0.30, 0.10, 0.01, key="sens_mc_csd")
    bias = mc3.slider("수요 평균보정(낙관편향 차감)", -0.20, 0.05, 0.0, 0.01,
                      key="sens_mc_bias",
                      help="민자도로 통행량 예측은 실측 대비 평균 과대(−20% 안팎) 경향. "
                           "음(-)으로 두면 보수적 보정 시나리오.")
    if st.button("몬테카를로 실행 (2,000회)", key="sens_mc_run"):
        with st.spinner("시뮬레이션 중…"):
            try:
                mc = monte_carlo(base, n=2000, demand_sd=demand_sd, capex_sd=capex_sd,
                                 demand_mean_bias=bias,
                                 lockup_dscr=cov_lockup, default_dscr=cov_default)
                k1, k2, k3 = st.columns(3)
                k1.metric("NPV<0 확률", f"{mc['prob_npv_negative']*100:.1f}%")
                k2.metric(f"DSCR<{cov_lockup:.2f}(lock-up) 확률", f"{mc['prob_dscr_below_lockup']*100:.1f}%")
                k3.metric(f"DSCR<{cov_default:.2f}(default) 확률", f"{mc['prob_dscr_below_default']*100:.1f}%")
                dist = pd.DataFrame({
                    "지표": ["NPV(억)", "DSCR_min", "명목IRR", "LLCR_min"],
                    "P10": [mc['npv']['p10'], mc['dscr_min']['p10'],
                            mc['nominal_irr']['p10'], mc['llcr_min']['p10']],
                    "P50": [mc['npv']['p50'], mc['dscr_min']['p50'],
                            mc['nominal_irr']['p50'], mc['llcr_min']['p50']],
                    "P90": [mc['npv']['p90'], mc['dscr_min']['p90'],
                            mc['nominal_irr']['p90'], mc['llcr_min']['p90']],
                })
                st.dataframe(dist, use_container_width=True, hide_index=True)
                st.caption("분포 파라미터는 가정값입니다. 안심구역 차량통행 변동성 통계로 교체 예정(검증필요).")
            except Exception as e:
                st.warning(f"몬테카를로 실패: {e}")

    st.divider()

    # ── 4. 낙관편향 플래그 ──
    st.markdown("##### 4. 수요 낙관편향 플래그")
    flag = optimism_flag(daily_traffic, benchmark_aadt)
    if not flag.get("evaluated", False):
        st.info(
            f"{flag.get('note', '평가 보류')}\n\n"
            "참고(가정·검증필요): 국내 은행 의뢰 통행량은 실측 대비 약 +20% 과대, "
            "S&P(2005)는 P3 toll road 1년차 실적이 예측 대비 평균 −23%로 보고했습니다. "
            "비교노선 분포가 들어오면 입력 통행량의 낙관 정도를 자동 표시합니다."
        )
    else:
        if flag["flag"]:
            st.warning(flag["message"])
        else:
            st.success(flag["message"])

    st.divider()

    # ── 5. 부채 스컬프팅 ──
    st.markdown("##### 5. 부채 스컬프팅 — 지속가능 부채한도")
    tgt = st.slider("목표 DSCR(평탄)", 1.10, 1.60, float(cov_base), 0.05, key="sens_sculpt_tgt")
    try:
        sc = sculpt_debt(base, target_dscr=tgt)
        s1, s2, s3 = st.columns(3)
        s1.metric("스컬프팅 부채한도(억)", f"{sc['sculpted_debt_억']:,.0f}")
        s2.metric("현재 부채(억)", f"{sc['current_debt_억']:,.0f}")
        s3.metric("여유(억)", f"{sc['headroom_억']:+,.0f}",
                  delta_color="normal" if sc['headroom_억'] >= 0 else "inverse")
        if sc["headroom_억"] >= 0:
            st.success(f"현금흐름이 목표 DSCR {tgt:.2f}를 유지하면서 현재 부채를 떠받칩니다 "
                       f"(여유 {sc['headroom_억']:,.0f}억).")
        else:
            st.warning(f"목표 DSCR {tgt:.2f} 기준 지속가능 부채한도가 현재 부채보다 "
                       f"{abs(sc['headroom_억']):,.0f}억 부족합니다. 부채 축소·만기 연장·자기자본 확대 검토 필요.")
        st.caption("CFADS를 목표 DSCR로 나눈 원리금 흐름의 현가 = 지속가능 부채한도(분석용 독립 계산).")
    except Exception as e:
        st.warning(f"부채 스컬프팅 계산 실패: {e}")

    st.divider()

    # ── 6. 리스크 등록부 ──
    st.markdown("##### 6. 리스크 등록부 (대주단 DD 산출물)")
    try:
        rdf = risk_register(base)
        st.dataframe(rdf, use_container_width=True, hide_index=True)
        st.caption(f"기준 DSCR_min {rdf.attrs.get('base_dscr_min')} · "
                   f"기준 NPV {rdf.attrs.get('base_npv'):,.0f}억. 충격폭은 실무 통상 가정값.")
    except Exception as e:
        st.warning(f"리스크 등록부 계산 실패: {e}")
