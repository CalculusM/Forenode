# -*- coding: utf-8 -*-
"""시나리오 나란히 비교 — 메인에서 '💾 시나리오 저장'한 1~4개를 표·차트·PDF로 비교.
예타 사전 시뮬(제안 전 반복 검토)의 마감 화면. 계산은 저장 시점의 엔진 산출을 그대로 사용(재계산 없음)."""
import io

import pandas as pd
import streamlit as st

st.set_page_config(page_title="시나리오 비교 — Forenode", page_icon="🧮", layout="wide")

st.title("🧮 시나리오 나란히 비교")
st.caption("메인 화면에서 변수를 바꿔 '💾 시나리오 저장'을 반복하면 여기에 쌓입니다(최대 4개) — "
           "이대로 제안하면 어떤 조건이 안전한지 한눈에 비교하세요.")

_saved = st.session_state.get('saved_scenarios', [])

if not _saved:
    st.info("저장된 시나리오가 없습니다. 메인 화면(Forenode)에서 조건을 설정한 뒤 "
            "'💾 시나리오 저장' 버튼을 누르고 돌아오세요.")
    try:
        st.page_link("app.py", label="◀ 메인 화면으로")
    except Exception:
        pass
    st.stop()

df = pd.DataFrame(_saved)

# ── ① 비교 표 ──
st.markdown("##### 📋 비교 표")
_metric_cols = ["NPV(억)", "IRR(%)", "EquityIRR(%)", "EquityMIRR(%)", "DSCR최소",
                "수입/비용현가비율", "정부부담(억)", "회수기간(년)"]
_input_cols = ["사업유형", "연장(km)", "총사업비(억)", "일교통량(대)", "통행료(원/km)", "MRG(%)"]
def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        if v != v:
            return "—"
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


_disp = df[["이름"] + _input_cols + _metric_cols].copy()
for _c in _input_cols + _metric_cols:
    _disp[_c] = _disp[_c].map(_fmt)
st.dataframe(_disp.set_index("이름").T, use_container_width=True, height=530)
st.caption("행 = 입력·지표, 열 = 시나리오. 판정 기준 없이 산출값만 나란히 — 판정은 각 시나리오의 메인 화면 기준.")

# ── ② 비교 차트 ──
st.markdown("##### 📊 지표 비교 차트")
try:
    import plotly.graph_objects as go
    _cc1, _cc2 = st.columns(2)
    with _cc1:
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=df["이름"], y=df["NPV(억)"], name="NPV(억)", marker_color="#1F3864"))
        fig1.add_trace(go.Bar(x=df["이름"], y=df["정부부담(억)"], name="정부부담(억)", marker_color="#EF9F27"))
        fig1.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=30, b=10),
                           title="NPV · 정부 재정부담 (억)")
        st.plotly_chart(fig1, use_container_width=True)
    with _cc2:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df["이름"], y=df["EquityIRR(%)"], name="Equity IRR(%)", marker_color="#0E5A8A"))
        fig2.add_trace(go.Bar(x=df["이름"], y=df["DSCR최소"], name="DSCR 최소", marker_color="#0E8A7B", yaxis="y2"))
        fig2.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=30, b=10),
                           title="Equity IRR(%) · DSCR 최소",
                           yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig2, use_container_width=True)
except Exception as _e:
    st.caption(f"차트 렌더 불가: {_e}")

# ── ③ 내보내기 ──
st.markdown("##### ⬇️ 내보내기")
_x1, _x2 = st.columns(2)
with _x1:
    st.download_button(
        "CSV 다운로드", df.to_csv(index=False).encode("utf-8-sig"),
        file_name="forenode_시나리오비교.csv", mime="text/csv", use_container_width=True)
with _x2:
    def _build_pdf() -> bytes:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.lib import colors as _c
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import ParagraphStyle
        try:
            pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
            _font = "Malgun"
        except Exception:
            _font = "Helvetica"
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=12 * mm,
                                title="Forenode 시나리오 비교")
        _h = ParagraphStyle("h", fontName=_font, fontSize=15, textColor=_c.HexColor("#1F3864"), leading=19)
        _n = ParagraphStyle("n", fontName=_font, fontSize=8, textColor=_c.HexColor("#666666"), leading=11)
        rows = [["구분"] + list(df["이름"])]
        for col in _input_cols + _metric_cols:
            vals = []
            for v in df[col]:
                vals.append(f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
            rows.append([col] + vals)
        t = Table(rows, colWidths=[45 * mm] + [None] * len(df))
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _font), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), _c.HexColor("#1F3864")),
            ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
            ("BACKGROUND", (0, 1), (0, -1), _c.HexColor("#EDF0F6")),
            ("GRID", (0, 0), (-1, -1), 0.4, _c.HexColor("#B7BFD1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story = [Paragraph("Forenode — 시나리오 나란히 비교", _h), Spacer(1, 4 * mm), t, Spacer(1, 4 * mm),
                 Paragraph("저장 시점의 엔진 산출값 비교(재계산 없음) · 판정 기준 미포함 — 상세는 각 시나리오의 본 보고서 참조.", _n)]
        doc.build(story)
        return buf.getvalue()

    try:
        st.download_button(
            "PDF 비교표 다운로드", _build_pdf(),
            file_name="forenode_시나리오비교.pdf", mime="application/pdf", use_container_width=True)
    except Exception as _pe:
        st.caption(f"PDF 생성 불가: {_pe}")

# ── ④ 관리 ──
st.markdown("##### 🗑 관리")
_dcols = st.columns(len(_saved) + 1)
for _i, _s in enumerate(_saved):
    with _dcols[_i]:
        if st.button(f"삭제: {_s['이름']}", key=f"sc_del_{_i}", use_container_width=True):
            _saved.pop(_i)
            st.rerun()
with _dcols[-1]:
    if st.button("전체 삭제", key="sc_del_all", type="secondary", use_container_width=True):
        st.session_state['saved_scenarios'] = []
        st.rerun()
