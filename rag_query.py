"""
============================================================
ROADx RAG 질의 스크립트 v4 (RetrievalQA 우회)
============================================================
v4 수정사항:
  - langchain.chains.RetrievalQA 미사용 (deprecated 회피)
  - vectordb.similarity_search() + ChatOpenAI.invoke() 직접 호출
  - 의존성 최소화: langchain-openai, langchain-community만 필요
  - 처리 흐름이 명시적이라 디버깅 쉬움
============================================================
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY or not OPENAI_API_KEY.startswith("sk-"):
    print("[중지] OPENAI_API_KEY 미설정")
    sys.exit(1)
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


# ════════════════════════════════════════════════════════════
# Import (langchain 메인 패키지 불필요)
# ════════════════════════════════════════════════════════════
try:
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
except ImportError:
    print("[중지] langchain-openai 미설치")
    print("  설치: pip install langchain-openai")
    sys.exit(1)

try:
    from langchain_community.vectorstores import Chroma
except ImportError:
    print("[중지] langchain-community 미설치")
    print("  설치: pip install langchain-community")
    sys.exit(1)


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
PERSIST_DIR = "./chroma_db"
EMBED_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
TOP_K = 10

if not Path(PERSIST_DIR).exists():
    print(f"[중지] {PERSIST_DIR} 폴더가 없습니다.")
    sys.exit(1)


# ════════════════════════════════════════════════════════════
# 개선된 한국어 답변 프롬프트
# ════════════════════════════════════════════════════════════
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


def format_context(docs):
    """검색된 청크를 GPT에 전달할 형태로 포맷"""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "?")
        page = doc.metadata.get("page", "")
        page_str = f" (p.{page})" if page != "" else ""
        parts.append(f"[자료 {i}: {source}{page_str}]\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)


def ask(vectordb, llm, question):
    """질문 → 검색 → 답변 (직접 구현)"""
    # 1. 벡터 검색
    docs = vectordb.similarity_search(question, k=TOP_K)
    
    if not docs:
        return "검색된 자료가 없습니다.", []
    
    # 2. 컨텍스트 구성
    context = format_context(docs)
    
    # 3. GPT 호출
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
# 메인
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("ROADx 법제 RAG 질의응답 시스템 v4 (RetrievalQA 우회)")
    print(f"  벡터DB: {PERSIST_DIR}")
    print(f"  검색 청크 수: {TOP_K}")
    print("=" * 60)
    print("종료: 빈 줄 입력 또는 Ctrl+C")
    print()

    embeddings = OpenAIEmbeddings(model=EMBED_MODEL)
    vectordb = Chroma(
        persist_directory=PERSIST_DIR,
        embedding_function=embeddings,
    )
    
    try:
        doc_count = vectordb._collection.count()
        print(f"  로드 완료: {doc_count:,}개 청크 검색 가능")
        print()
    except Exception:
        pass

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)

    print("─" * 60)
    print("추천 시연 질문:")
    print("  1. 사회기반시설 민간투자법상 BTO 방식의 정의는?")
    print("  2. 사업시행자 지정의 자격 요건은 무엇인가요?")
    print("  3. 시설물 안전 및 유지관리에 관한 특별법상 정기점검 주기는?")
    print("  4. 민자사업의 환경영향평가 절차를 설명해주세요")
    print("  5. 민간투자사업의 사용료 결정 방법은?")
    print("─" * 60)

    while True:
        try:
            q = input("\n질문 ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료.")
            break

        if not q:
            print("종료.")
            break

        try:
            answer, docs = ask(vectordb, llm, q)
        except Exception as e:
            print(f"[에러] {e}")
            continue

        print("\n" + "─" * 60)
        print("답변:")
        print(answer)
        print(f"\n근거 자료 (검색된 청크 상위 {TOP_K}개):")
        seen = set()
        for doc in docs:
            src = doc.metadata.get("source", "?")
            page = doc.metadata.get("page", "")
            key = f"{src}:{page}"
            if key in seen:
                continue
            seen.add(key)
            page_str = f" (p.{page})" if page != "" else ""
            print(f"  - {src}{page_str}")
        print("─" * 60)


if __name__ == "__main__":
    main()
