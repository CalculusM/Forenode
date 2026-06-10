# -*- coding: utf-8 -*-
"""EX 도로 BIM 객체분류(OBS)·속성(Pset)·LOD → Forenode 추출 스키마/OPEX 파라미터 매핑표 → PDF.
실행: python _make_mapping_pdf.py  → EX_BIM_매핑표.pdf

근거(1차자료 직접확인[확인]):
  - 2016 한국도로공사 EX-BIM 가이드라인 ver.1.0 (OBS/Pset/LOD/수량분류)
  - 2023 국가철도공단 철도 BIM 적용지침 (동일 국토부/buildingSMART-KR 인프라 BIM 표준 프레임)
  - buildingSMART IFC4.3(IFC4X3_ADD2) 엔티티 + 형상→물량 기술검증(_ifc_techcheck.py)
주의: 2023 「고속도로 BIM 적용지침」 본문 PDF 직링크 미확보 → 도로 OBS 구조는 위 동일표준에서 재현[확인/일부 추정].
"""
import html
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, PageBreak)
from reportlab.lib.styles import ParagraphStyle

pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBd", "C:/Windows/Fonts/malgunbd.ttf"))
pdfmetrics.registerFontFamily("Malgun", normal="Malgun", bold="MalgunBd")

NAVY = colors.HexColor("#1F3864")
ORANGE = colors.HexColor("#EF9F27")
HEADBG = colors.HexColor("#1F3864")
ROW1 = colors.HexColor("#F4F6FB")
ROW2 = colors.white
GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#C9D3E6")

OUT = "EX_BIM_매핑표.pdf"
PAGE = landscape(A4)
CONTENT_W = PAGE[0] - 28 * mm

H1 = ParagraphStyle("h1", fontName="MalgunBd", fontSize=15, textColor=NAVY, leading=19)
SUB = ParagraphStyle("sub", fontName="Malgun", fontSize=8.5, textColor=GREY, leading=12)
H2 = ParagraphStyle("h2", fontName="MalgunBd", fontSize=11, textColor=NAVY, leading=14, spaceBefore=7, spaceAfter=3)
TH = ParagraphStyle("th", fontName="MalgunBd", fontSize=8.2, textColor=colors.white, leading=10.5)
TD = ParagraphStyle("td", fontName="Malgun", fontSize=7.7, textColor=colors.HexColor("#222222"), leading=10)
TDB = ParagraphStyle("tdb", fontName="MalgunBd", fontSize=7.7, textColor=NAVY, leading=10)
NOTE = ParagraphStyle("note", fontName="Malgun", fontSize=8, textColor=GREY, leading=11.5)


def P(t, s=TD):
    return Paragraph(html.escape(t).replace("\n", "<br/>"), s)


def mk_table(head, rows, widths, boldcol0=True):
    data = [[P(h, TH) for h in head]]
    for r in rows:
        data.append([P(c, TDB if (boldcol0 and i == 0) else TD) for i, c in enumerate(r)])
    t = Table(data, colWidths=[CONTENT_W * w for w in widths], repeatRows=1)
    sty = [("BACKGROUND", (0, 0), (-1, 0), HEADBG),
           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("GRID", (0, 0), (-1, -1), 0.4, LINE),
           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    for i in range(1, len(data)):
        sty.append(("BACKGROUND", (0, i), (-1, i), ROW1 if i % 2 else ROW2))
    t.setStyle(TableStyle(sty))
    return t


def main():
    doc = SimpleDocTemplate(OUT, pagesize=PAGE, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    S = []
    S.append(Paragraph("EX 도로 BIM(OBS·Pset·LOD) → Forenode 추출 스키마 / OPEX 파라미터 매핑", H1))
    S.append(Paragraph("도로 코어 기준 · 1차자료: 2016 EX-BIM 가이드라인 + 2023 철도 BIM 적용지침(동일 국토부 표준) · "
                       "IFC4.3(IFC4X3_ADD2) 엔티티 · 형상→물량 기술검증 반영 · 2026-06-10", SUB))
    S.append(HRFlowable(width="100%", thickness=1.2, color=ORANGE, spaceBefore=4, spaceAfter=6))

    # 1. OBS 7단계 + 공종별 표준객체 → IFC → 물량 → OPEX (핵심)
    S.append(Paragraph("1. 공종(OBS)별 표준객체 → IFC4.3 엔티티 → 물량 → OPEX 모델  [확인: 지침 표준객체명]", H2))
    S.append(mk_table(
        ["공종(OBS)", "지침 표준객체 (실제 명칭)", "IFC4.3 엔티티", "추출 물량", "OPEX 매핑(열화·단가)"],
        [
            ["선형(기준)", "도로 선형(평면·종단·캔트)", "IfcAlignment", "연장 L(m)", "전 공종 물량 산정 기준"],
            ["토공", "흙깎기(토사/리핑/발파)·흙쌓기(노체/노상)·비탈면보호공·연약지반처리", "IfcEarthworksCut/Fill", "체적(㎥)", "사면관리(유지비중 낮음)"],
            ["옹벽공", "보강토옹벽·콘크리트옹벽", "IfcRetainingWall/IfcWall", "체적(㎥)", "CONCRETE × 단가"],
            ["포장공", "동상방지층·보조기층·기층·중간층·표층·프라임/택코팅·교면포장", "IfcCourse/IfcPavement", "면적(㎡)·체적(㎥)", "ASPHALT(linear, life20)"],
            ["교량공", "기초·벽체·기둥·코핑·거더·교좌장치(받침)·신축이음", "IfcBeam/IfcBearing/IfcExpansionJoint", "체적·개수·길이", "CONCRETE/STEEL/REBAR/BEARING/EXP_JOINT"],
            ["교량받침(세분류)", "선단;Linear·포트;Pot·황동;Oilles·로커;Rocker·로울러;Roller·핀;Pin·피봇;Pivot·탄성고무;Rubber", "IfcBearing(PredefinedType)", "개수(EA)", "BEARING(weibull, life25)"],
            ["터널공", "갱문·지보공·숏크리트·락볼트·콘크리트라이닝", "IfcTunnel/proxy", "체적·길이", "CONCRETE/STEEL"],
            ["배수공", "L/U/V형측구·산마루측구·종/횡배수관·다이크·맹암거·집수정", "IfcPipeSegment/IfcDrainageSystem", "길이(m)·개소", "DRAINAGE(linear, life40)"],
            ["부대공", "표지·신호·조명·방호울타리(난간)", "IfcSignal/IfcSign/IfcLamp/IfcRailing", "개수·길이", "GUARDRAIL(life30)/LIGHTING(life15)"],
        ],
        [0.13, 0.31, 0.20, 0.13, 0.23]))

    # 2. OBS 명명규칙 + Pset 5필드
    S.append(Paragraph("2. 객체명 규칙 · 속성(Pset) 5필드 → Forenode 사용처  [확인]", H2))
    S.append(mk_table(
        ["구분", "지침 정의(실제)", "Forenode 사용처"],
        [
            ["OBS 7단계 WBS", "①도로시설 ②공종 ③시설물 ④방향공간 ⑤확장공간 ⑥작업관리단위1 ⑦작업관리단위2", "추출 스키마 계층키 직접 채택"],
            ["객체명 규칙", "WBS7작업명_재료/형식_위치/이름 (예: 표층_아스팔트_본선상행)", "정규식으로 공종·재료·위치 파싱"],
            ["Pset 5필드", "속성분류 / 속성명 / 속성표현 / 입력주체 / 속성설명", "추출 결과표 열 구조"],
            ["핵심 객체속성", "객체명칭·객체형상·객체재료(fck=30MPa, fy=400MPa)·시설물규격·관리기관·CWBS코드", "재료·강도 → 단가·열화 파라미터 보정"],
        ],
        [0.16, 0.52, 0.32]))

    # 3. LOD → 수량종류 → 신뢰도
    S.append(Paragraph("3. LOD(=LOG형상+LOI정보) → 수량 종류 → OPEX 추출 신뢰도  [확인]", H2))
    S.append(mk_table(
        ["LOD", "지침 의미", "산출 수량", "Forenode 활용(OPEX)"],
        [
            ["100", "개념(선·기호)", "—", "미사용"],
            ["200", "개략형상(기본설계)", "개략 수량·크기·위치", "타당성·개략 OPEX"],
            ["300", "정밀형상(실시설계, 권장)", "자동·연동수량(정밀)", "실시설계 물량 → 본 OPEX"],
            ["350", "300+철근모델·접합부 상세", "+철근량", "콘크리트 보수 LCC 단가에 직결"],
            ["400/500", "제작 / 준공(as-built)", "제품정보 / 현장검증", "유지관리 LOI(자산정보) 인계"],
        ],
        [0.07, 0.27, 0.26, 0.40]))
    S.append(Spacer(1, 3))
    S.append(mk_table(
        ["수량 3분류(지침)", "예시", "신뢰도 / 처리"],
        [
            ["자동수량", "체적·면적·길이·개수", "신뢰 — geom으로 산출/검증(_ifc_techcheck)"],
            ["연동수량", "거푸집·동바리·비계·신축이음", "계산식 속성 연동 — 부분 신뢰"],
            ["수동수량", "품질시험·계측·가설사무실", "보정 대상 — OPEX 산식서 별도 처리"],
        ],
        [0.18, 0.40, 0.42]))

    S.append(PageBreak())
    # 4. 6D/유지관리 인계 + 폴백규칙
    S.append(Paragraph("4. 6D·유지관리 인계 근거 (제품 내러티브)  [확인]", H2))
    for b in [
        "준공 BIM 모델(LOD500)은 <b>유지관리용 분류체계·상세수준·관련정보 포함</b> 의무화 가능 — 활용목적: 현황·이력·점검·상태평가 (2016 도로지침 §7).",
        "BIM 실행계획에 <b>자산정보 획득 전략 — 자산정보모델(AIM, ISO 15686-4)</b> + 교환포맷에 <b>유지관리용 COBie</b> 명시(IFC 병행).",
        "지침이 한국도로공사 <b>HBMS(교량관리)·HPMS(포장관리)</b> 연계를 명시 → ① 'BIM 성과품에 OPEX용 자산정보가 이미 규정' 내러티브, "
        "② HBMS/HPMS가 OPEX 백테스트 <b>유지관리비 실적 출처 후보</b>(K-apt 대신 도로 코어 actual).",
    ]:
        S.append(Paragraph("• " + b, NOTE))

    S.append(Paragraph("5. Forenode 추출 폴백 규칙 (핵심)", H2))
    for b in [
        "① IfcElementQuantity(Qto)가 있으면 우선 사용.",
        "② Qto가 없으면(공개 IFC4.3 도로데모 6/6이 Qto=0 — 기술검증 확인) <b>ifcopenshell.geom으로 형상에서 체적·길이 직접 산출</b>(역산). "
        "검증완료: 도로체 sectioned-solid 3,888㎥·swept 8,550㎥·alignment 950/1,029m.",
        "③ LOD200=길이·면적·개소 / LOD300=정밀 자동·연동 / LOD350=철근량까지 → 추출 신뢰도 가중치.",
        "④ 재료(IfcMaterial) 미기재 시 OBS 공종 분류로 재료·단가·열화모델 폴백 매핑.",
        "⑤ 물량 × 표준품셈 단가 × 열화모델 → 생애주기 OPEX(자본적 유지보수) → 현금흐름(DSCR, C1 연결).",
    ]:
        S.append(Paragraph("• " + b, NOTE))

    S.append(Spacer(1, 6))
    S.append(Paragraph(
        "※ 한계/확인필요: (a) 2023 「고속도로 BIM 적용지침」 본문 PDF 직링크 미확보 — 위 OBS/Pset/LOD는 2016 도로 + 2023 철도(동일 국토부 표준)에서 [확인], "
        "도로 본문 부속서(표준분류체계·Pset 전체 코드집) 전수는 ex.co.kr/buildingSMART-KR 엑셀 부속서 별도 입수 권장. "
        "(b) 공개 도로 IFC 다수가 IFC4X3_RC3 → ifcopenshell 0.8.5 미지원(통합 갭).", NOTE))

    doc.build(S)
    print("저장:", OUT)


if __name__ == "__main__":
    main()
