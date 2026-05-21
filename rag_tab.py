"""
============================================================
ROADx 법제 RAG 탭 모듈 v3 (추천 질문 클릭 버그 수정)
============================================================
v3 수정사항:
  - st.text_input의 key 직접 업데이트 (value 우선순위 문제 해결)
  - 추천 질문 클릭 → 입력란 자동 채움 정상 작동
  - 코드 단순화

사용법: rag_tab.py로 저장 → app.py와 같은 폴더에 두기
============================================================
"""
import os
import streamlit as st
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
PERSIST_DIR = "./chroma_db"
EMBED_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
TOP_K = 10

RECOMMENDED_QUESTIONS = [
    "민자도로 운영기간 종료 후 시설은 어떻게 되나요?",
    "BTO와 BTL 방식의 차이는 무엇인가요?",
    "민간투자사업의 사용료 결정 방법은?",
    "사업시행자 지정의 자격 요건은 무엇인가요?",
    "관리운영권 설정기간 만료 전 시설점검은 언제 실시하나요?",
    "도로법상 도로의 정의는 무엇인가요?",
    "정기안전점검과 정밀안전점검의 주기는?",
]

SYSTEM_PROMPT = """당신은 민자도로 사업의 법률 전문가입니다.
제공된 법령·행정규칙 자료를 근거로 한국어로 답변하세요.

핵심 규칙:
1. 자료에 명시된 조항·정의·절차·수치만 답변. 추측 금지.
2. 표(table)나 특정 사업의 개별 수치는 일반 답변의 근거로 사용 금지.
   예: 자료에 '08~'27처럼 특정 사업의 수치가 보여도
   일반 질문(예: "민자도로 운영기간은?")의 답으로 쓰지 말 것.
3. 일반 원칙(운영기간 한도, 점검 주기 등)은 다음 우선순위로 답변:
   ① 사회기반시설에 대한 민간투자법 본문 조항
   ② 시행령 본문 조항
   ③ 민간투자사업기본계획 본문 조항 (표·예시 제외)
   ④ 도로법, 유료도로법, 시설물안전법 등 관련법
4. 답이 없으면 "제공된 자료에서 명확한 근거를 찾지 못했습니다"라고 답변.
5. 답변 끝에 어떤 조항·문서를 참조했는지 명시.
   예: "(근거: 사회기반시설에 대한 민간투자법 제25조)"
"""


# ════════════════════════════════════════════════════════════
# 캐싱: ChromaDB와 LLM은 한 번만 로드
# ════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="법제 RAG 시스템 로드 중...")
def load_rag_system():
    """벡터DB와 LLM을 로드 (앱 실행 후 1회만)"""
    
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or not api_key.startswith("sk-"):
        return None, "OPENAI_API_KEY 미설정 — .env 파일에 키를 추가하세요"
    
    if not Path(PERSIST_DIR).exists():
        return None, f"{PERSIST_DIR} 폴더가 없습니다. rag_index_v3.py를 먼저 실행하세요."
    
    try:
        from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    except ImportError:
        return None, "langchain-openai 미설치 — pip install langchain-openai"
    
    try:
        from langchain_community.vectorstores import Chroma
    except ImportError:
        return None, "langchain-community 미설치 — pip install langchain-community"
    
    try:
        embeddings = OpenAIEmbeddings(model=EMBED_MODEL)
        vectordb = Chroma(
            persist_directory=PERSIST_DIR,
            embedding_function=embeddings,
        )
        try:
            chunk_count = vectordb._collection.count()
        except Exception:
            chunk_count = "?"
        
        llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
        
        return {
            "vectordb": vectordb,
            "llm": llm,
            "chunk_count": chunk_count,
        }, None
        
    except Exception as e:
        return None, f"로드 실패: {e}"


# ════════════════════════════════════════════════════════════
# 질의 처리
# ════════════════════════════════════════════════════════════
def format_context(docs):
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "?")
        page = doc.metadata.get("page", "")
        page_str = f" (p.{page})" if page != "" else ""
        parts.append(f"[자료 {i}: {source}{page_str}]\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)


def ask_rag(system, question):
    vectordb = system["vectordb"]
    llm = system["llm"]
    
    docs = vectordb.similarity_search(question, k=TOP_K)
    if not docs:
        return "검색된 자료가 없습니다.", []
    
    context = format_context(docs)
    user_msg = f"""[제공된 자료]
{context}

[질문]
{question}

[답변]"""
    
    response = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg}
    ])
    
    answer = response.content if hasattr(response, "content") else str(response)
    return answer, docs


# ════════════════════════════════════════════════════════════
# 메인 렌더 함수
# ════════════════════════════════════════════════════════════
def render_rag_tab():
    """app.py에서 호출하는 메인 함수"""
    
    st.subheader("📚 법제 RAG 자연어 질의응답")
    st.caption("민투법·도로법·민간투자사업기본계획 등 16개 법령(1,963 청크)에서 GPT-4o-mini가 근거를 찾아 답변합니다")
    
    # 시스템 로드
    system, error = load_rag_system()
    
    if error:
        st.error(f"❌ {error}")
        with st.expander("📖 RAG 시스템 설정 방법"):
            st.markdown("""
            **1단계**: `.env` 파일에 `OPENAI_API_KEY=sk-...` 추가  
            **2단계**: `pip install langchain-openai langchain-community chromadb python-dotenv`  
            **3단계**: `python rag_index_v3.py` (1회만)  
            **4단계**: app.py 재시작
            """)
        return
    
    # 시스템 정보
    info_col1, info_col2, info_col3 = st.columns(3)
    with info_col1:
        st.metric("인덱싱된 청크", 
                  f"{system['chunk_count']:,}개" if isinstance(system['chunk_count'], int) else system['chunk_count'])
    with info_col2:
        st.metric("검색 모델", "embedding-3-small")
    with info_col3:
        st.metric("답변 모델", "gpt-4o-mini")
    
    st.markdown("---")
    
    # ★ 핵심 수정: rag_input 키를 직접 관리
    # 세션 상태 초기화
    if "rag_history" not in st.session_state:
        st.session_state.rag_history = []
    if "rag_input" not in st.session_state:
        st.session_state.rag_input = ""
    
    # 추천 질문 버튼 - 클릭 시 rag_input 키를 직접 업데이트
    st.markdown("**💡 추천 질문** (클릭하면 자동 입력)")
    
    cols = st.columns(3)
    for i, q in enumerate(RECOMMENDED_QUESTIONS):
        col = cols[i % 3]
        with col:
            label = q[:25] + ("..." if len(q) > 25 else "")
            if st.button(f"🔍 {label}", 
                         key=f"rec_q_{i}", 
                         help=q,
                         use_container_width=True):
                # ★ 핵심: rag_input 키를 직접 업데이트
                st.session_state.rag_input = q
                st.rerun()
    
    st.markdown("---")
    
    # 질문 입력 - key만 사용, value 미사용
    st.markdown("**❓ 직접 질문 입력**")
    
    user_question = st.text_input(
        "질문",
        key="rag_input",   # ★ value 파라미터 제거, key만 사용
        placeholder="예: 민자도로 사업 종료 후 시설 처리는?",
        label_visibility="collapsed",
    )
    
    submit_col, clear_col = st.columns([1, 5])
    with submit_col:
        submit = st.button("🚀 질문하기", type="primary", use_container_width=True)
    with clear_col:
        if st.button("🗑️ 대화 초기화", use_container_width=False):
            st.session_state.rag_history = []
            # 입력란 초기화는 위젯 재생성 후 다음 rerun에 반영
            if "rag_input" in st.session_state:
                del st.session_state.rag_input
            st.rerun()
    
    # 질문 처리
    if submit and user_question.strip():
        with st.spinner(f"🔎 관련 법령 검색 중... (예상 비용: 약 7~12원)"):
            try:
                answer, docs = ask_rag(system, user_question)
                
                st.session_state.rag_history.insert(0, {
                    "question": user_question,
                    "answer": answer,
                    "sources": [
                        {
                            "name": doc.metadata.get("source", "?"),
                            "page": doc.metadata.get("page", ""),
                            "preview": doc.page_content[:200].replace("\n", " "),
                        }
                        for doc in docs
                    ]
                })
                # 입력란 비우기
                if "rag_input" in st.session_state:
                    del st.session_state.rag_input
                st.rerun()
                
            except Exception as e:
                st.error(f"질의 실패: {e}")
    
    # 답변 히스토리 표시
    if st.session_state.rag_history:
        st.markdown("---")
        st.markdown(f"**💬 대화 기록** ({len(st.session_state.rag_history)}건)")
        
        for i, item in enumerate(st.session_state.rag_history):
            with st.container():
                st.markdown(f"#### 🟦 Q{len(st.session_state.rag_history) - i}. {item['question']}")
                
                answer_html = item['answer'].replace("\n", "<br>")
                st.markdown(
                    f"""<div style="background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                                    padding: 16px 20px; border-radius: 8px; 
                                    color: #1a1a2e; margin: 8px 0;
                                    line-height: 1.6;">
                        <strong>📝 답변:</strong><br>{answer_html}
                    </div>""",
                    unsafe_allow_html=True
                )
                
                with st.expander(f"📚 근거 자료 ({len(item['sources'])}건 검색됨)"):
                    seen = set()
                    for src in item['sources']:
                        key = f"{src['name']}:{src['page']}"
                        if key in seen:
                            continue
                        seen.add(key)
                        page_str = f" (p.{src['page']})" if src['page'] != "" else ""
                        st.markdown(f"**📄 {src['name']}{page_str}**")
                        st.caption(f"미리보기: {src['preview']}...")
                
                st.markdown("---")
    else:
        st.info("👆 추천 질문을 클릭하거나 직접 질문을 입력해보세요.")
