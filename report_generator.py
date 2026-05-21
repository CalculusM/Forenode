"""
============================================================
Forenode — PDF 보고서 자동 생성 모듈 (report_generator.py)
============================================================
역할:
  Forenode의 모든 분석 결과를 한 PDF 보고서로 자동 생성.
  사용자가 30초 안에 컨설팅사 수준의 deliverable 확보.

페이지 구성:
  P1: 표지
  P2: 분석 요약 (KPI 6개 + VfM 판단)
  P3: 시점 1 사전 검토 (CAPEX 비교 + OPEX 시계열)
  P4: 시점 4 재구조화 시나리오
  P5: 산출 근거·데이터 출처

기술:
  - reportlab (PDF 생성)
  - matplotlib (차트 이미지)
  - 한글 폰트: Windows 'Malgun Gothic', Linux 'NanumGothic' 또는 'NotoSansCJK'
============================================================
"""
import io
import os
import platform
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image,
    Table, TableStyle, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.graphics.shapes import Drawing, Line, Circle, String


# ════════════════════════════════════════════════════════════
# 한글 폰트 자동 검색 + 등록
# ════════════════════════════════════════════════════════════
def _register_korean_font():
    """OS별 한글 폰트 자동 등록. 등록 성공한 폰트명 반환."""
    candidates = []
    system = platform.system()
    
    if system == "Windows":
        candidates = [
            ("MalgunGothic", "C:/Windows/Fonts/malgun.ttf"),
            ("MalgunGothicBold", "C:/Windows/Fonts/malgunbd.ttf"),
        ]
    elif system == "Darwin":  # macOS
        candidates = [
            ("AppleGothic", "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        ]
    else:  # Linux
        candidates = [
            ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
            ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ("NotoSansCJKBlack", "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"),
        ]
    
    for name, path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception:
                continue
    
    # 폴백: 기본 폰트 (한글 깨질 수 있음)
    return "Helvetica"


_KOR_FONT = _register_korean_font()


def _setup_matplotlib_korean():
    """matplotlib 한글 표시 설정"""
    system = platform.system()
    if system == "Windows":
        plt.rcParams['font.family'] = 'Malgun Gothic'
    elif system == "Darwin":
        plt.rcParams['font.family'] = 'AppleGothic'
    else:
        # Linux: NanumGothic 또는 NotoSansCJK
        for f in ['NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK HK']:
            try:
                plt.rcParams['font.family'] = f
                break
            except Exception:
                continue
    plt.rcParams['axes.unicode_minus'] = False


_setup_matplotlib_korean()


# ════════════════════════════════════════════════════════════
# Forenode 로고 (Drawing 객체)
# ════════════════════════════════════════════════════════════
def _forenode_logo(width_pt: float = 400):
    """
    Forenode 로고를 reportlab Drawing 객체로 반환.
    
    Parameters
    ----------
    width_pt : float
        로고 전체 너비 (포인트 단위, 기본 400pt = 약 141mm)
    
    Returns
    -------
    reportlab.graphics.shapes.Drawing
    """
    # 원본 비율: 480x80 (6:1)
    height_pt = width_pt / 6
    scale = width_pt / 480
    
    d = Drawing(width_pt, height_pt)
    
    # 좌표계: reportlab은 좌하단이 (0, 0). 디자인 좌표계 (좌상단 0,0)에서 변환.
    n1_x, n1_y = 20 * scale, height_pt - 40 * scale
    n2_x, n2_y = 50 * scale, height_pt - 20 * scale
    n3_x, n3_y = 80 * scale, height_pt - 50 * scale
    
    color_primary = colors.HexColor("#1F3864")
    color_accent = colors.HexColor("#EF9F27")
    color_subtitle = colors.HexColor("#888780")
    
    # 연결선 3개 (삼각형 모양)
    d.add(Line(n1_x, n1_y, n2_x, n2_y, strokeColor=color_primary, strokeWidth=2.5 * scale))
    d.add(Line(n2_x, n2_y, n3_x, n3_y, strokeColor=color_primary, strokeWidth=2.5 * scale))
    d.add(Line(n3_x, n3_y, n2_x, n2_y, strokeColor=color_primary, strokeWidth=2.5 * scale))
    
    # 노드 점 3개
    d.add(Circle(n1_x, n1_y, 6 * scale, fillColor=color_primary, strokeColor=None))
    d.add(Circle(n2_x, n2_y, 8 * scale, fillColor=color_accent, strokeColor=None))
    d.add(Circle(n3_x, n3_y, 6 * scale, fillColor=color_primary, strokeColor=None))
    
    # 텍스트 — "Forenode"
    title_font = _KOR_FONT if _KOR_FONT != "Helvetica" else "Helvetica-Bold"
    subtitle_font = _KOR_FONT
    
    d.add(String(
        120 * scale, height_pt - 45 * scale,
        "Forenode",
        fontName=title_font,
        fontSize=34 * scale,
        fillColor=color_primary,
    ))
    
    # 부재 — "BIM·AI 민자사업 인텔리전스"
    d.add(String(
        120 * scale, height_pt - 65 * scale,
        "BIM·AI 민자사업 인텔리전스",
        fontName=subtitle_font,
        fontSize=11 * scale,
        fillColor=color_subtitle,
    ))
    
    return d


# ════════════════════════════════════════════════════════════
# 차트 생성 함수 — matplotlib → PNG bytes
# ════════════════════════════════════════════════════════════
def _chart_opex_series(opex_estimation: dict) -> bytes:
    """OPEX 시계열 차트"""
    opex = opex_estimation['opex_series_억']
    years = list(range(1, len(opex) + 1))
    peak_y = opex_estimation['peak_year']
    
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.fill_between(years, opex, alpha=0.2, color='#1F3864')
    ax.plot(years, opex, color='#1F3864', linewidth=2, marker='o', markersize=3)
    ax.axvline(x=peak_y, linestyle='--', color='#EF9F27', alpha=0.7)
    ax.annotate(
        f'정점 {peak_y}년차',
        xy=(peak_y, opex_estimation['peak_amount_억']),
        xytext=(peak_y + 1, opex_estimation['peak_amount_억']),
        color='#EF9F27', fontsize=9,
    )
    ax.set_xlabel('운영 연차')
    ax.set_ylabel('OPEX (억원)')
    ax.set_title('운영기간 OPEX 시계열 (학습 데이터 기반 자동 산출)')
    ax.grid(True, alpha=0.3)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _chart_capex_comparison(capex_ref: dict, user_capex: int) -> bytes:
    """CAPEX 비교 막대 차트"""
    labels = ['사용자 입력', '회귀 추정\n(중앙값)', '회귀 하한\n(-20%)', '회귀 상한\n(+20%)']
    values = [
        user_capex,
        capex_ref['capex_estimate_억'],
        capex_ref['capex_low_억'],
        capex_ref['capex_high_억'],
    ]
    colors_bar = ['#1F3864', '#1D9E75', '#888888', '#888888']
    
    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.bar(labels, values, color=colors_bar, alpha=0.85)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
            f'{v:,}', ha='center', va='bottom', fontsize=9,
        )
    ax.set_ylabel('CAPEX (억원)')
    ax.set_title('CAPEX 추정 비교')
    ax.grid(True, axis='y', alpha=0.3)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _chart_restructuring(ctx: dict) -> bytes:
    """재구조화 시나리오 NPV 비교"""
    annual_rev = ctx['annual_revenue']
    avg_opex = ctx['opex_estimation']['opex_ratio_avg']
    wacc = ctx['wacc']
    op_years = ctx['operation_years']
    growth = 0.025
    
    # 운영 절반 시점 가정
    current = op_years // 2
    remaining = op_years - current
    extension_list = [0, 5, 10, 20]
    
    scenarios = []
    for ext in extension_list:
        total = remaining + ext
        npv = 0
        for y in range(1, total + 1):
            op_year = current + y
            rev = annual_rev * (1 + growth) ** (op_year - 1)
            opex = rev * avg_opex
            fcf = rev - opex
            npv += fcf / ((1 + wacc) ** y)
        label = '현재 조건' if ext == 0 else f'+{ext}년 연장'
        scenarios.append((label, npv))
    
    labels = [s[0] for s in scenarios]
    values = [s[1] for s in scenarios]
    colors_bar = ['#888888'] + ['#1F3864'] * (len(scenarios) - 1)
    
    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.bar(labels, values, color=colors_bar, alpha=0.85)
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
            f'{v:,.0f}억', ha='center', va='bottom', fontsize=9,
        )
    ax.set_ylabel('잔여 NPV (억원)')
    ax.set_title(f'재구조화 시나리오별 잔여 NPV (운영 {current}년차 기준)')
    ax.grid(True, axis='y', alpha=0.3)
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ════════════════════════════════════════════════════════════
# 메인 함수 — PDF 보고서 생성
# ════════════════════════════════════════════════════════════
def generate_pdf_report(phase_context: dict, project_name: str = "민자도로 분석 사업") -> bytes:
    """
    Forenode 분석 결과 PDF 보고서 생성.
    
    Returns
    -------
    bytes : PDF 파일 내용 (st.download_button에 직접 전달 가능)
    """
    ctx = phase_context
    buf = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
    )
    
    # ─── 스타일 정의 ───
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'KorTitle', parent=styles['Title'],
        fontName=_KOR_FONT, fontSize=28, alignment=TA_CENTER,
        spaceAfter=8, textColor=colors.HexColor('#1F3864'),
    )
    subtitle_style = ParagraphStyle(
        'KorSub', parent=styles['Normal'],
        fontName=_KOR_FONT, fontSize=12, alignment=TA_CENTER,
        spaceAfter=24, textColor=colors.HexColor('#555555'),
    )
    h1_style = ParagraphStyle(
        'KorH1', parent=styles['Heading1'],
        fontName=_KOR_FONT, fontSize=16, alignment=TA_LEFT,
        spaceAfter=8, textColor=colors.HexColor('#1F3864'),
    )
    h2_style = ParagraphStyle(
        'KorH2', parent=styles['Heading2'],
        fontName=_KOR_FONT, fontSize=12, alignment=TA_LEFT,
        spaceAfter=6, textColor=colors.HexColor('#1F3864'),
    )
    body_style = ParagraphStyle(
        'KorBody', parent=styles['Normal'],
        fontName=_KOR_FONT, fontSize=10, alignment=TA_LEFT,
        spaceAfter=6, leading=14,
    )
    caption_style = ParagraphStyle(
        'KorCaption', parent=styles['Normal'],
        fontName=_KOR_FONT, fontSize=8, alignment=TA_LEFT,
        textColor=colors.HexColor('#666666'),
    )
    
    story = []
    
    # ════════════════════════════════════════════════════════
    # P1: 표지
    # ════════════════════════════════════════════════════════
    story.append(Spacer(1, 50 * mm))
    story.append(_forenode_logo(width_pt=400))
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph("민자사업 수익성 분석 보고서", subtitle_style))
    story.append(Spacer(1, 15 * mm))
    
    cover_data = [
        ['사업명', project_name],
        ['사업유형', ctx['business_type']],
        ['연장 / 운영기간', f"{ctx['road_length']} km / {ctx['operation_years']} 년"],
        ['총사업비 (사용자 입력)', f"{ctx['total_capex_user']:,} 억원"],
        ['생성일시', datetime.now().strftime('%Y-%m-%d %H:%M')],
    ]
    t = Table(cover_data, colWidths=[40 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), _KOR_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F5F5')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1F3864')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph(
        "본 보고서는 Forenode 분석 플랫폼이 자동 생성한 결과입니다. "
        "한국 PPP 30년 데이터(13개 SPC + 도로공사 11년치 4,380건)와 "
        "BIM·AI 모델을 기반으로 산출되었습니다.",
        caption_style
    ))
    story.append(PageBreak())
    
    # ════════════════════════════════════════════════════════
    # P2: 분석 요약 — KPI + VfM 판단
    # ════════════════════════════════════════════════════════
    story.append(Paragraph("Ⅰ. 분석 요약", h1_style))
    story.append(Paragraph(
        f"사업 <b>{project_name}</b>에 대한 수익성·재무 분석 핵심 지표입니다.",
        body_style,
    ))
    story.append(Spacer(1, 6 * mm))
    
    metrics = ctx['metrics']
    
    # KPI 표 (3×2)
    npv = metrics['npv']
    irr = metrics['nominal_irr']
    real_irr = metrics['real_irr']
    dscr_min = metrics['dscr_min']
    dscr_avg = metrics['dscr_avg']
    roe = metrics['roe']
    bc = metrics['bc_ratio']
    
    kpi_data = [
        ['지표', '값', '평가', '지표', '값', '평가'],
        [
            'NPV', f'{npv:,.0f} 억',
            '흑자' if npv >= 0 else '적자',
            'IRR (명목)', f'{irr*100:.2f}%',
            f'WACC {ctx["wacc"]*100:.1f}% 대비',
        ],
        [
            'IRR (불변)', f'{real_irr*100:.2f}%', '',
            'DSCR (최소)', f'{dscr_min:.2f}',
            '양호' if dscr_min >= 1.2 else ('경계' if dscr_min >= 1.0 else '위험'),
        ],
        [
            'DSCR (평균)', f'{dscr_avg:.2f}', '',
            'ROE', f'{roe*100:.2f}%', '',
        ],
        [
            'B/C ratio', f'{bc:.2f}',
            '적합' if bc >= 1.0 else '부적합',
            'PSC ratio', f'{bc:.2f}',
            '(B/C 동일)',
        ],
    ]
    t = Table(kpi_data, colWidths=[24*mm, 22*mm, 28*mm, 24*mm, 22*mm, 28*mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), _KOR_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F3864')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))
    
    # VfM 판단
    story.append(Paragraph("VfM 적격성 판단", h2_style))
    
    if bc >= 1.3 and dscr_min >= 1.20:
        judgment = "민자 매우 적합"
        rec = "정부 보전금 없이도 민간 사업주가 수익을 낼 수 있는 구조. BTO 또는 BTO-rs 사업유형 검토 권장."
    elif bc >= 1.0 and dscr_min >= 1.05:
        judgment = "민자 적합"
        rec = "현재 조건으로 사업 추진 가능. 민감도 분석에서 핵심 리스크 변수 확인 필요."
    elif bc >= 0.85:
        judgment = "경계선 — 재구조화 검토"
        rec = "사업 조건 보완 필요. MRG 상향, 운영기간 연장, BTO-ann 전환 등 검토 권장."
    else:
        judgment = "민자 부적합"
        rec = "재정사업 전환 또는 사업계획 전면 재검토 권장."
    
    judgment_data = [
        ['판단 결과', judgment],
        ['권고 사항', rec],
    ]
    t = Table(judgment_data, colWidths=[35 * mm, 115 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), _KOR_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E3F2FD')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1F3864')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(PageBreak())
    
    # ════════════════════════════════════════════════════════
    # P3: 시점 1 — 사전 검토 (CAPEX + OPEX)
    # ════════════════════════════════════════════════════════
    story.append(Paragraph("Ⅱ. 사전 검토 분석 (통계 모드)", h1_style))
    story.append(Paragraph(
        "본 단계는 KDI PIMAC·주무관청·자문사가 민자 적격성을 평가하는 시점입니다. "
        "BIM 없이 한국 PPP 30년 데이터를 학습한 통계 모델로 분석합니다.",
        body_style,
    ))
    story.append(Spacer(1, 4 * mm))
    
    # CAPEX 비교
    story.append(Paragraph("1. CAPEX 추정 비교", h2_style))
    capex_chart = Image(io.BytesIO(_chart_capex_comparison(
        ctx['capex_reference'], ctx['total_capex_user']
    )), width=160*mm, height=72*mm)
    story.append(capex_chart)
    
    in_range = (ctx['capex_reference']['capex_low_억']
                <= ctx['total_capex_user']
                <= ctx['capex_reference']['capex_high_억'])
    range_text = "회귀 신뢰구간 (±20%) 내 위치 — 적정" if in_range else "회귀 신뢰구간 밖 — 재검토 필요"
    story.append(Paragraph(
        f"사용자 입력 {ctx['total_capex_user']:,}억 vs 회귀 추정 "
        f"{ctx['capex_reference']['capex_estimate_억']:,}억. {range_text}.",
        caption_style,
    ))
    story.append(Paragraph(
        f"산출 근거: {ctx['capex_reference']['explanation']}",
        caption_style,
    ))
    story.append(Spacer(1, 6 * mm))
    
    # OPEX 시계열
    story.append(Paragraph("2. OPEX 자동 산출 시계열", h2_style))
    opex_chart = Image(io.BytesIO(_chart_opex_series(ctx['opex_estimation'])),
                       width=160*mm, height=72*mm)
    story.append(opex_chart)
    
    op = ctx['opex_estimation']
    story.append(Paragraph(
        f"평균 OPEX 비율 {op['opex_ratio_avg']*100:.1f}% | "
        f"1년차 {op['opex_series_억'][0]:.0f}억 → 정점 {op['peak_year']}년차 {op['peak_amount_억']:.0f}억",
        caption_style,
    ))
    story.append(Paragraph(
        f"산출 근거: {op['explanation']}",
        caption_style,
    ))
    story.append(PageBreak())
    
    # ════════════════════════════════════════════════════════
    # P4: 시점 4 — 재구조화 시나리오
    # ════════════════════════════════════════════════════════
    story.append(Paragraph("Ⅲ. 재구조화 시나리오 분석", h1_style))
    story.append(Paragraph(
        "운영기간 만료 임박 사업 257건(2024~2030) + 596건(2030 이후) = 853건이 폭증하는 시장입니다. "
        "정부는 관리운영권 설정기간을 50년+α(최대 100년)까지 연장 허용합니다.",
        body_style,
    ))
    story.append(Spacer(1, 4 * mm))
    
    restruct_chart = Image(io.BytesIO(_chart_restructuring(ctx)),
                            width=160*mm, height=72*mm)
    story.append(restruct_chart)
    
    story.append(Paragraph(
        f"운영 {ctx['operation_years']//2}년차 기준 잔여기간 시뮬레이션. "
        "운영기간 연장 시나리오별 잔여 NPV 비교를 통해 정부·SPC 협상 카드를 제시합니다.",
        caption_style,
    ))
    story.append(Spacer(1, 8 * mm))
    
    story.append(Paragraph("📌 협상 시나리오 활용 예", h2_style))
    story.append(Paragraph(
        "• <b>SPC 측</b>: 안전·환경 추가 투자 패키지로 운영기간 연장 협상<br/>"
        "• <b>주무관청 측</b>: 통행료 인하 조건부 운영기간 연장 허용<br/>"
        "• <b>자산운용사 측</b>: 자산 매입 시 잔여 가치 평가 (M&A DD)<br/>"
        "• <b>CEPHIS 측</b>: 운영평가 자료 + 실시협약 변경 검토",
        body_style,
    ))
    story.append(PageBreak())
    
    # ════════════════════════════════════════════════════════
    # P5: 산출 근거 + 데이터 출처
    # ════════════════════════════════════════════════════════
    story.append(Paragraph("Ⅳ. 산출 근거 및 데이터 출처", h1_style))
    story.append(Spacer(1, 4 * mm))
    
    story.append(Paragraph("1. 활용 데이터", h2_style))
    data_sources = [
        ['구분', '출처', '활용'],
        ['재무 (13개 SPC × 5년)', '금융감독원 DART', 'XGBoost 수익성 등급 (LOOCV 93.2%)'],
        ['통행 (TCS·VDS)', '한국도로공사', '수요·통행료 분석'],
        ['운행 (DTG)', '한국교통안전공단', '화물비율·통행 패턴'],
        ['수요 (KTDB OD)', '한국교통연구원', '수요 예측·성장률'],
        ['시설 (54,760건)', '한국도로공사 포장일반', 'Weibull 열화 (β=1.04, η=9.89년)'],
        ['보수 (4,380건)', '한국도로공사 포장보수 11년치', 'OPEX 시계열 자동 산출'],
        ['법제 (16개 법령)', '국가법령정보센터', 'RAG 법제 자문 (1,963 청크)'],
    ]
    t = Table(data_sources, colWidths=[45 * mm, 50 * mm, 55 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), _KOR_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F3864')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CCCCCC')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))
    
    story.append(Paragraph("2. 분석 모델", h2_style))
    story.append(Paragraph(
        "<b>CAPEX 회귀 모델</b>: 노선 특성(연장·차로·지형·교량·터널)에서 km당 단가 추정 (±20% 신뢰구간).<br/>"
        "<b>OPEX 자동 산출</b>: 사업유형 기본 비율 + 노선 보정 + 학습 데이터 연차 패턴.<br/>"
        "<b>현금흐름 모델</b>: S-curve CAPEX 분배, MRG 보전금, 재구조화 통행료 조정 반영.<br/>"
        "<b>Monte Carlo NPV</b>: 1,000회 시뮬레이션으로 NPV 분포 추정.<br/>"
        "<b>Weibull 열화</b>: 357건 보수 데이터로 β=1.044, η=9.89년 도출 (95% CI).<br/>"
        "<b>XGBoost 수익성 등급</b>: 13개 SPC 5년치, SMOTE 적용, LOOCV 정확도 93.2%.",
        body_style,
    ))
    story.append(Spacer(1, 8 * mm))
    
    story.append(Paragraph("3. 한계 및 면책", h2_style))
    story.append(Paragraph(
        "본 보고서는 자동 산출 추정치입니다. 통계 모드 정확도는 ±20%, BIM 모드는 ±5% 수준입니다. "
        "최종 의사결정은 본 보고서 외에 추가 자문(KDI PIMAC, LTA, STA, 법률 자문 등)을 거쳐야 합니다. "
        "본 결과는 분석 시점의 입력 변수에 기반하며, 시장 환경 변화에 따라 재산출이 필요합니다.",
        caption_style,
    ))
    story.append(Spacer(1, 12 * mm))
    
    # 푸터
    story.append(Paragraph(
        "─" * 70 + "<br/>"
        "Forenode — BIM·AI 기반 민자도로 수익성 분석 플랫폼<br/>"
        "© Nexus Infra Solutions · 2026 국토·교통 데이터 활용 경진대회 출품작",
        caption_style,
    ))
    
    # 빌드
    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


# ════════════════════════════════════════════════════════════
# 자가 검증
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("PDF 생성 자가 검증")
    
    # 더미 컨텍스트
    dummy_ctx = {
        'business_type': 'BTO-ann',
        'road_length': 45,
        'lanes': 4,
        'terrain': '평지',
        'bridge_ratio': 0.15,
        'tunnel_ratio': 0.20,
        'total_capex_user': 20725,
        'operation_years': 30,
        'construction_years': 5,
        'annual_revenue': 1500,
        'mrg_ratio': 0.9,
        'restructuring_year': 0,
        'wacc': 0.05,
        'opex_estimation': {
            'opex_ratio_avg': 0.369,
            'opex_series_억': [308 + i * 50 for i in range(30)],
            'peak_year': 30,
            'peak_amount_억': 1788,
            'explanation': 'BTO-ann 기본 35% × 노선보정 1.05 = 평균 36.9%',
        },
        'capex_reference': {
            'capex_estimate_억': 22365,
            'capex_low_억': 17892,
            'capex_high_억': 26838,
            'per_km_억': 497,
            'explanation': '기준 단가 350억/km × 차로 1.00 × 지형 1.00 × 교량·터널 1.42',
        },
        'metrics': {
            'npv': 5234, 'nominal_irr': 0.083, 'real_irr': 0.061,
            'dscr_min': 1.18, 'dscr_avg': 1.42, 'roe': 0.124, 'bc_ratio': 1.18,
        },
    }
    
    pdf = generate_pdf_report(dummy_ctx, "화성-안성 민자고속도로")
    with open("/tmp/forenode_test.pdf", "wb") as f:
        f.write(pdf)
    print(f"✓ PDF 생성 완료: {len(pdf):,} bytes")
