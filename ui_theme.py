# -*- coding: utf-8 -*-
"""
Forenode 디자인 시스템 v2 ('26-07-31 잔상 수정)

라이트 = 시안 A 「기관 네이비」 / 다크 = 시안 C 「그래파이트 틸」

핵심 설계 — 테마 전환 잔상 방지:
- 카드·헤더·섹션 박스 등 **화면 골격 색은 전부 CSS**로 정의하고
  `@media (prefers-color-scheme: dark)`로 이중화한다 → 라이트/다크 전환 시
  파이썬 리런 없이 **즉시** 색이 바뀐다(구버전은 서버 렌더 색이 남는 잔상 발생).
- 파이썬 코드에서 쓰는 색(theme() 반환값)은 **모드 중립**이다: 어느 배경에서도
  판독되는 중간톤 + 반투명(rgba) 배경/테두리 + 글자색 inherit. 따라서 리런
  시점의 모드와 무관하게 항상 자연스럽다. (차트 글꼴·축 색은 st.plotly_chart의
  기본 streamlit 테마가 모드별로 입힌다 — 우리는 colorway·격자만 지정.)
- 인쇄물(PDF)은 LIGHT 고정 팔레트를 쓴다(report_generator가 import).

원칙: 그라데이션 금지 · 색 = 판정(ok/warn/bad) 의미로만 · config.toml과 동기화.
"""
from __future__ import annotations

import streamlit as st

# ── 모드 중립 팔레트 — theme()가 반환. 양 모드에서 판독 가능해야 함 ──
NEUTRAL = {
    "type": "auto",
    "bg": "transparent",
    "surface": "rgba(148, 163, 184, 0.10)",
    "border": "rgba(148, 163, 184, 0.35)",
    "text": "inherit",
    "muted": "#94A3B8",
    "primary": "#3B82F6",       # 차트 주계열·강조 (라이트 네이비·다크 틸의 중간 합의색)
    "accent": "#14B8A6",
    "ok": "#16A34A",
    "warn": "#D97706",
    "bad": "#EF4444",
    "ok_bg": "rgba(22, 163, 74, 0.14)",
    "warn_bg": "rgba(217, 119, 6, 0.15)",
    "bad_bg": "rgba(239, 68, 68, 0.14)",
    "accent_bg": "rgba(59, 130, 246, 0.13)",
    "chart": ["#3B82F6", "#14B8A6", "#94A3B8", "#16A34A", "#D97706", "#EF4444", "#8B5CF6"],
    "chart_grid": "rgba(148, 163, 184, 0.30)",
    "chart_band": "rgba(59, 130, 246, 0.12)",
}

# ── 인쇄(PDF)·참고용 고정 팔레트 — 시안 A/C 원색. report_generator는 LIGHT 사용 ──
LIGHT = {
    "type": "light",
    "bg": "#FFFFFF", "surface": "#F8FAFC", "border": "#E2E8F0",
    "text": "#0F172A", "muted": "#64748B",
    "primary": "#1E3A5F", "accent": "#2563EB",
    "ok": "#15803D", "warn": "#B45309", "bad": "#B91C1C",
    "ok_bg": "#ECFDF5", "warn_bg": "#FFFBEB", "bad_bg": "#FEF2F2", "accent_bg": "#EFF6FF",
    "chart": ["#1E3A5F", "#2563EB", "#94A3B8", "#15803D", "#B45309", "#B91C1C", "#0E7490"],
    "chart_grid": "#E2E8F0", "chart_band": "rgba(37, 99, 235, 0.10)",
}
DARK = {
    "type": "dark",
    "bg": "#0F172A", "surface": "#1E293B", "border": "#334155",
    "text": "#F1F5F9", "muted": "#94A3B8",
    "primary": "#2DD4BF", "accent": "#5EEAD4",
    "ok": "#5EEAD4", "warn": "#FBBF24", "bad": "#F87171",
    "ok_bg": "#134E4A", "warn_bg": "#422006", "bad_bg": "#450A0A", "accent_bg": "#164E63",
    "chart": ["#2DD4BF", "#5EEAD4", "#94A3B8", "#4ADE80", "#FBBF24", "#F87171", "#38BDF8"],
    "chart_grid": "#334155", "chart_band": "rgba(45, 212, 191, 0.14)",
}


def theme() -> dict:
    """파이썬 코드에서 쓸 팔레트 — 모드 중립(전환 잔상 없음)."""
    return NEUTRAL


def inject_css() -> None:
    """전역 CSS — 라이트/다크 이중 정의(미디어쿼리) → 전환 즉시 반영.
    app.py set_page_config 직후 1회 호출."""
    st.markdown(
        """
    <style>
    .metric-card {
        background: #F8FAFC; border: 1px solid #E2E8F0; color: #0F172A;
        padding: 14px 10px; border-radius: 10px;
        text-align: center; margin: 4px 0;
        display: flex; flex-direction: column; justify-content: space-between;
        min-height: 118px;
    }
    .metric-card h4 {
        margin: 0; font-size: 11.5px; line-height: 1.25; color: #64748B;
        font-weight: 500;
        min-height: 29px; display: flex; align-items: center; justify-content: center;
    }
    .metric-card h2 {
        margin: 6px 0 0; font-size: clamp(15px, 1.55vw, 23px); font-weight: 700;
        white-space: nowrap; letter-spacing: -0.3px; color: #1E3A5F;
    }
    .metric-card.green h2 { color: #15803D; }
    .metric-card.red h2 { color: #B91C1C; }
    .metric-card.orange h2 { color: #B45309; }
    .metric-card.blue h2 { color: #2563EB; }

    .fn-hd {
        display: flex; align-items: center; gap: 16px; padding: 12px 16px;
        background: #F8FAFC; border: 1px solid #E2E8F0;
        border-radius: 10px; margin-bottom: 20px;
    }
    .fn-hd-title { font-size: 32px; font-weight: 600; color: #1E3A5F; line-height: 1.2; }
    .fn-hd-sub { font-size: 12px; color: #64748B; margin-top: 2px; }
    /* 로고 심볼은 브랜드 원색 고정(네이비 #1F3864 + 주황 #EF9F27) — 테마 무관, '26-07-31 대표 지시 */
    .fn-hd svg .fn-ln { stroke: #1F3864; }
    .fn-hd svg .fn-nd { fill: #1F3864; }
    .fn-hd svg .fn-nd-acc { fill: #EF9F27; }

    .fn-sec {
        background: #F8FAFC; border: 1px solid #E2E8F0;
        border-radius: 10px; padding: 12px 18px; margin: 8px 0;
    }
    .fn-sec-kicker { font-size: 12px; color: #64748B; font-weight: 500; letter-spacing: 0.4px; }
    .fn-sec-title { font-size: 18px; font-weight: 700; color: #1E3A5F; margin-top: 2px; }
    .fn-sec-desc { font-size: 12px; color: #64748B; margin-top: 4px; }

    @media (prefers-color-scheme: dark) {
        .metric-card { background: #1E293B; border-color: #334155; color: #F1F5F9; }
        .metric-card h4 { color: #94A3B8; }
        .metric-card h2 { color: #2DD4BF; }
        .metric-card.green h2 { color: #5EEAD4; }
        .metric-card.red h2 { color: #F87171; }
        .metric-card.orange h2 { color: #FBBF24; }
        .metric-card.blue h2 { color: #38BDF8; }
        .fn-hd { background: #1E293B; border-color: #334155; }
        .fn-hd-title { color: #2DD4BF; }
        .fn-hd-sub { color: #94A3B8; }
        .fn-sec { background: #1E293B; border-color: #334155; }
        .fn-sec-kicker { color: #94A3B8; }
        .fn-sec-title { color: #2DD4BF; }
        .fn-sec-desc { color: #94A3B8; }
    }

    /* 최종 권위 = 실제 렌더된 Streamlit 배경(동기화 스크립트가 body에 표시) —
       사용자가 앱 메뉴로 테마를 바꿔 OS 설정과 어긋나는 경우까지 커버 */
    body[data-fn-theme="light"] .metric-card { background: #F8FAFC; border-color: #E2E8F0; color: #0F172A; }
    body[data-fn-theme="light"] .metric-card h4 { color: #64748B; }
    body[data-fn-theme="light"] .metric-card h2 { color: #1E3A5F; }
    body[data-fn-theme="light"] .metric-card.green h2 { color: #15803D; }
    body[data-fn-theme="light"] .metric-card.red h2 { color: #B91C1C; }
    body[data-fn-theme="light"] .metric-card.orange h2 { color: #B45309; }
    body[data-fn-theme="light"] .metric-card.blue h2 { color: #2563EB; }
    body[data-fn-theme="light"] .fn-hd,
    body[data-fn-theme="light"] .fn-sec { background: #F8FAFC; border-color: #E2E8F0; }
    body[data-fn-theme="light"] .fn-hd-title,
    body[data-fn-theme="light"] .fn-sec-title { color: #1E3A5F; }
    body[data-fn-theme="light"] .fn-hd-sub,
    body[data-fn-theme="light"] .fn-sec-kicker,
    body[data-fn-theme="light"] .fn-sec-desc { color: #64748B; }

    body[data-fn-theme="dark"] .metric-card { background: #1E293B; border-color: #334155; color: #F1F5F9; }
    body[data-fn-theme="dark"] .metric-card h4 { color: #94A3B8; }
    body[data-fn-theme="dark"] .metric-card h2 { color: #2DD4BF; }
    body[data-fn-theme="dark"] .metric-card.green h2 { color: #5EEAD4; }
    body[data-fn-theme="dark"] .metric-card.red h2 { color: #F87171; }
    body[data-fn-theme="dark"] .metric-card.orange h2 { color: #FBBF24; }
    body[data-fn-theme="dark"] .metric-card.blue h2 { color: #38BDF8; }
    body[data-fn-theme="dark"] .fn-hd,
    body[data-fn-theme="dark"] .fn-sec { background: #1E293B; border-color: #334155; }
    body[data-fn-theme="dark"] .fn-hd-title,
    body[data-fn-theme="dark"] .fn-sec-title { color: #2DD4BF; }
    body[data-fn-theme="dark"] .fn-hd-sub,
    body[data-fn-theme="dark"] .fn-sec-kicker,
    body[data-fn-theme="dark"] .fn-sec-desc { color: #94A3B8; }

    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; border-radius: 8px; }
    </style>
    """,
        unsafe_allow_html=True,
    )
    _sync_theme_attr()


def _sync_theme_attr() -> None:
    """실제 렌더된 Streamlit 배경 밝기를 읽어 body[data-fn-theme]를 유지하는
    0px 동기화 스크립트 — 테마가 어떤 경로(OS·앱 메뉴·리로드)로 바뀌어도 추종."""
    try:
        import streamlit.components.v1 as _components
        _components.html(
            """
            <script>
            (function () {
                var doc = window.parent.document;
                function apply() {
                    var app = doc.querySelector('.stApp');
                    if (!app) return;
                    var bg = getComputedStyle(app).backgroundColor;
                    var m = bg.match(/\\d+/g);
                    if (!m) return;
                    var lum = 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
                    doc.body.setAttribute('data-fn-theme', lum < 128 ? 'dark' : 'light');
                }
                apply();
                setInterval(apply, 1000);
            })();
            </script>
            """,
            height=0,
        )
    except Exception:
        pass


def header_html(title: str, subtitle: str) -> str:
    """앱 상단 로고 헤더 — 클래스 기반(모드 전환 즉시 반영)."""
    return (
        '<div class="fn-hd">'
        '<svg width="80" height="50" viewBox="0 0 80 50" xmlns="http://www.w3.org/2000/svg">'
        '<line class="fn-ln" x1="10" y1="35" x2="40" y2="15" stroke-width="2.5"/>'
        '<line class="fn-ln" x1="40" y1="15" x2="70" y2="45" stroke-width="2.5"/>'
        '<line class="fn-ln" x1="70" y1="45" x2="40" y2="15" stroke-width="2.5"/>'
        '<circle class="fn-nd" cx="10" cy="35" r="6"/>'
        '<circle class="fn-nd-acc" cx="40" cy="15" r="8"/>'
        '<circle class="fn-nd" cx="70" cy="45" r="6"/>'
        "</svg>"
        f'<div><div class="fn-hd-title">{title}</div>'
        f'<div class="fn-hd-sub">{subtitle}</div></div></div>'
    )


def section_header(kicker: str, title: str, desc: str = "") -> str:
    """탭·섹션 상단 헤더 HTML — 클래스 기반(모드 전환 즉시 반영)."""
    desc_html = f'<div class="fn-sec-desc">{desc}</div>' if desc else ""
    return (
        f'<div class="fn-sec"><div class="fn-sec-kicker">{kicker}</div>'
        f'<div class="fn-sec-title">{title}</div>{desc_html}</div>'
    )


# phase_tabs 모드 배지 (통계/실적/시뮬) — 반투명 배경(모드 중립)
def mode_badge_colors() -> dict:
    T = theme()
    return {
        "통계": (T["accent"], T["accent_bg"], "📊"),
        "실적": (T["ok"], T["ok_bg"], "📈"),
        "시뮬": (T["warn"], T["warn_bg"], "🧪"),
    }


def apply_plotly_template() -> None:
    """Plotly 전역 기본 — colorway·격자만 지정(모드 중립).
    글꼴·축 글자색은 st.plotly_chart 기본 streamlit 테마가 모드별로 입힌다."""
    import plotly.graph_objects as go
    import plotly.io as pio

    T = theme()
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        colorway=T["chart"],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor=T["chart_grid"], zerolinecolor=T["chart_grid"]),
        yaxis=dict(gridcolor=T["chart_grid"], zerolinecolor=T["chart_grid"]),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    pio.templates["forenode"] = tpl
    pio.templates.default = "forenode"
