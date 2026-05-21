"""
============================================================
ROADx 4기관 데이터 출처 모듈 (가점 ② 융합데이터 증빙)
============================================================
역할:
  - Streamlit 사이드바에 4기관 출처 카드 표시 (항상 노출)
  - 첫 탭 상단에 데이터 흐름도 표시
  - 시연 영상에서 가점 ② "주관기관 융합데이터" 증빙 자동 노출

사용법:
  1. 이 파일을 app.py와 같은 폴더에 두세요 (data_sources.py)
  2. app.py 상단 import 부분에 추가:
       from data_sources import render_data_source_sidebar, render_data_flow_banner
  3. main() 함수 시작 부분(set_page_config 다음)에 추가:
       render_data_source_sidebar()
  4. tabs[0] (현금흐름 탭) 시작 부분에 추가:
       render_data_flow_banner()
============================================================
"""
import streamlit as st


# ════════════════════════════════════════════════════════════
# 4기관 데이터 출처 정보
# ════════════════════════════════════════════════════════════
DATA_SOURCES = [
    {
        "code": "EX",
        "name": "한국도로공사",
        "name_en": "Korea Expressway Corporation",
        "icon": "🛣️",
        "color": "#0F4C81",
        "datasets": [
            "TCS 통행료 수납 데이터 (5년)",
            "VDS 차량검지 데이터 (1분 단위)",
            "노선·시설물 정보 9건",
            "민자도로 운영 통계",
        ],
        "modules": ["현금흐름", "통행료", "벤치마크"],
    },
    {
        "code": "KOTI",
        "name": "한국교통연구원",
        "name_en": "Korea Transport Institute",
        "icon": "🚆",
        "color": "#1D9E75",
        "datasets": [
            "KTDB 여객 OD (전국)",
            "KTDB 화물 OD",
            "교통량 분석용 네트워크",
            "개인통행실태조사 2021",
        ],
        "modules": ["통행료", "Monte Carlo"],
    },
    {
        "code": "KOTSA",
        "name": "한국교통안전공단",
        "name_en": "Korea Transportation Safety Authority",
        "icon": "🚛",
        "color": "#BA7517",
        "datasets": [
            "DTG 운행기록 (사업용)",
            "운행기록장치 세부정보",
            "화물자동차 통행실태 2022",
            "차종·중량 분류 데이터",
        ],
        "modules": ["열화곡선", "Tornado"],
    },
    {
        "code": "FIN",
        "name": "DART · HUG · ECOS",
        "name_en": "Financial Data Sources",
        "icon": "💼",
        "color": "#534AB7",
        "datasets": [
            "민자 SPC 11개사 감사보고서",
            "천안논산·제이영동 5년치",
            "주택도시보증공사 연차보고서",
            "한국은행 ECOS 금리·물가",
        ],
        "modules": ["현금흐름", "금융구조", "벤치마크"],
    },
]


def render_data_source_sidebar():
    """사이드바에 4기관 출처 카드 표시 (항상 노출)"""
    with st.sidebar:
        st.markdown("### 📊 데이터 출처")
        st.caption("4기관 융합 데이터 활용")
        
        for src in DATA_SOURCES:
            with st.container():
                st.markdown(
                    f"""<div style="background: {src['color']}15;
                                    border-left: 3px solid {src['color']};
                                    padding: 8px 12px;
                                    margin: 6px 0;
                                    border-radius: 4px;">
                        <div style="font-size: 13px; font-weight: 500; 
                                    color: {src['color']};">
                            {src['icon']} {src['name']}
                        </div>
                        <div style="font-size: 11px; color: #666; 
                                    margin-top: 2px;">
                            데이터 {len(src['datasets'])}종 · 활용 {len(src['modules'])}개 모듈
                        </div>
                    </div>""",
                    unsafe_allow_html=True
                )
        
        st.markdown("---")
        st.caption("총 16종 데이터셋 · 7개 분석 모듈")
        
        # 상세 내역 expander
        with st.expander("📋 데이터셋 상세"):
            for src in DATA_SOURCES:
                st.markdown(f"**{src['icon']} {src['name']}**")
                for ds in src['datasets']:
                    st.caption(f"  • {ds}")
                st.markdown("")


def render_data_flow_banner():
    """첫 화면 상단에 4기관 데이터 흐름 배너 표시"""
    
    st.markdown(
        """<div style="background: linear-gradient(90deg, 
                        #0F4C81 0%, 
                        #1D9E75 33%, 
                        #BA7517 66%, 
                        #534AB7 100%);
                    padding: 2px;
                    border-radius: 8px;
                    margin: 0 0 16px 0;">
            <div style="background: white;
                        padding: 14px 18px;
                        border-radius: 6px;">
                <div style="display: flex; 
                            justify-content: space-between; 
                            align-items: center;
                            flex-wrap: wrap;
                            gap: 12px;">
                    <div style="font-size: 14px; font-weight: 500; 
                                color: #1a1a2e;">
                        🔗 4기관 융합 데이터 분석 시스템
                    </div>
                    <div style="font-size: 12px; color: #666;">
                        도로공사 · 교통연구원 · 교통안전공단 · 금융기관
                    </div>
                </div>
            </div>
        </div>""",
        unsafe_allow_html=True
    )


def render_data_flow_diagram():
    """데이터 흐름도 (탭 내부에서 호출 가능)"""
    
    st.markdown("#### 📊 데이터 → 분석 모듈 매핑")
    
    # 표 형태로 4기관 → 모듈 매핑
    cols = st.columns(4)
    for i, src in enumerate(DATA_SOURCES):
        with cols[i]:
            st.markdown(
                f"""<div style="background: {src['color']}10;
                                border-top: 4px solid {src['color']};
                                padding: 12px;
                                border-radius: 6px;
                                min-height: 200px;">
                    <div style="font-size: 24px; text-align: center;">
                        {src['icon']}
                    </div>
                    <div style="font-size: 13px; 
                                font-weight: 500;
                                text-align: center;
                                color: {src['color']};
                                margin: 6px 0;">
                        {src['name']}
                    </div>
                    <div style="font-size: 10px; 
                                color: #999;
                                text-align: center;
                                margin-bottom: 10px;">
                        {src['name_en']}
                    </div>
                    <div style="font-size: 11px; color: #555;
                                line-height: 1.6;">
                        <strong>데이터 {len(src['datasets'])}종</strong><br>
                        {'<br>'.join(['• ' + d[:20] + ('...' if len(d) > 20 else '') 
                                      for d in src['datasets'][:3]])}
                    </div>
                    <div style="font-size: 10px; 
                                color: {src['color']};
                                margin-top: 8px;
                                padding-top: 8px;
                                border-top: 1px dashed {src['color']}40;">
                        활용 모듈: {' · '.join(src['modules'])}
                    </div>
                </div>""",
                unsafe_allow_html=True
            )
    
    st.markdown("")
    
    # 통합 메시지
    st.info(
        "🎯 **융합 분석의 가치**: "
        "교통량 데이터(도로공사·교통연구원) × "
        "차량 특성(교통안전공단) × "
        "재무 구조(DART·HUG·한국은행) → "
        "단일 출처로는 불가능한 **수익성·열화·리스크 통합 예측** 가능"
    )
