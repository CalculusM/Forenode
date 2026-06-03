"""
============================================================
ROADx RAG 인덱싱 v3 (재귀 검색 + 진단 강화)
============================================================
v3 수정사항:
  - 폴더 내 .txt를 재귀 검색 (laws/ 등 하위 폴더 포함)
  - 법령 폴더 진단 출력 강화 (어떤 파일이 있는지 보여줌)
  - 표준품셈 기본 OFF (시연용 RAG는 법령이 핵심)
  - 인덱싱 시작 전 사용자 확인 단계 추가
============================================================
"""
import os
import sys
import csv
import time
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

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.vectorstores import Chroma
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_core.documents import Document
except ImportError as e:
    print(f"[중지] 라이브러리 미설치: {e}")
    sys.exit(1)


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
ROOT = Path.cwd()

# ★ 법령만 인덱싱 (시연 핵심)
INCLUDE_PUMSE = False     # 표준품셈 PDF (이미 처리됨)
INCLUDE_AUDIT = False     # 감사보고서 PDF

TARGET_FOLDERS = {
    "법령": ["07 법령", "법령"],
}
if INCLUDE_PUMSE:
    TARGET_FOLDERS["표준품셈"] = ["03 단가", "표준품셈"]
if INCLUDE_AUDIT:
    TARGET_FOLDERS["감사보고서"] = ["06 민자도로", "감사보고서"]

PERSIST_DIR = "./chroma_db"
INDEX_CSV = "./indexed_files.csv"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50
TARGET_TPM = 35_000


def find_folder(keywords):
    for item in ROOT.iterdir():
        if not item.is_dir():
            continue
        for kw in keywords:
            if kw in item.name:
                return item
    return None


def diagnose_folder(folder):
    """폴더 내용 진단 출력"""
    print(f"\n  [진단] {folder.name} 폴더 내용:")
    
    txt_files = list(folder.rglob("*.txt"))
    xml_files = list(folder.rglob("*.xml"))
    pdf_files = list(folder.rglob("*.pdf"))
    other_files = [
        f for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() not in [".txt", ".xml", ".pdf"]
    ]
    
    print(f"    .txt 파일: {len(txt_files)}개")
    if txt_files:
        for f in txt_files[:5]:
            rel = f.relative_to(folder)
            print(f"      - {rel} ({f.stat().st_size:,} bytes)")
        if len(txt_files) > 5:
            print(f"      ... 외 {len(txt_files)-5}개")
    
    print(f"    .xml 파일: {len(xml_files)}개")
    print(f"    .pdf 파일: {len(pdf_files)}개")
    print(f"    기타: {len(other_files)}개")
    
    return txt_files


def load_text_files_recursive(folder):
    """재귀적으로 .txt 파일 모두 로드"""
    txt_files = diagnose_folder(folder)
    
    if not txt_files:
        print(f"\n  [⚠] {folder.name} 폴더에 .txt 파일이 없습니다!")
        print(f"      law_download_v3.py 실행 결과를 확인하세요.")
        return []
    
    docs = []
    for txt in sorted(txt_files):
        try:
            content = txt.read_text(encoding="utf-8")
            if len(content) < 100:
                print(f"    [건너뜀] {txt.name} (내용 부족, {len(content)}자)")
                continue
            docs.append(Document(
                page_content=content,
                metadata={
                    "source": txt.name,
                    "category": folder.name,
                    "type": "법령",
                }
            ))
            print(f"    ✓ {txt.name} ({len(content):,}자)")
        except Exception as e:
            print(f"    [⚠] {txt.name}: {e}")
    return docs


def load_pdf_files(folder, category_name):
    docs = []
    for pdf in sorted(folder.rglob("*.pdf")):
        try:
            t0 = time.time()
            loader = PyPDFLoader(str(pdf))
            pages = loader.load()
            for p in pages:
                p.metadata["source"] = pdf.name
                p.metadata["category"] = folder.name
                p.metadata["type"] = category_name
            docs.extend(pages)
            print(f"    ✓ {pdf.name} ({len(pages)}쪽, {time.time()-t0:.1f}초)")
        except Exception as e:
            print(f"    [⚠] {pdf.name}: {e}")
    return docs


def estimate_tokens(text):
    return len(text) / 2.5


def embed_in_batches(chunks, embeddings, persist_dir):
    persist_path = Path(persist_dir)
    if persist_path.exists():
        import shutil
        shutil.rmtree(persist_path)
        print(f"  (기존 {persist_dir} 삭제)")
    
    first_batch = chunks[:BATCH_SIZE]
    print(f"\n  [배치 1] 0~{len(first_batch)} 임베딩 중...")
    
    vectordb = None
    retry = 0
    while vectordb is None and retry < 3:
        try:
            vectordb = Chroma.from_documents(
                documents=first_batch,
                embedding=embeddings,
                persist_directory=persist_dir,
            )
        except Exception as e:
            retry += 1
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 30 * retry
                print(f"  [TPM 한도] {wait}초 대기 후 재시도 ({retry}/3)")
                time.sleep(wait)
            else:
                raise
    
    total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(BATCH_SIZE, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        
        batch_tokens = sum(estimate_tokens(c.page_content) for c in batch)
        sleep_sec = max(0, batch_tokens * 60 / TARGET_TPM)
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        
        retry = 0
        while retry < 3:
            try:
                vectordb.add_documents(batch)
                break
            except Exception as e:
                retry += 1
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    wait = 30 * retry
                    print(f"  [TPM 한도] {wait}초 대기 후 재시도 ({retry}/3)")
                    time.sleep(wait)
                else:
                    print(f"  [에러] 배치 {batch_num}: {e}")
                    break
        
        progress = (i + len(batch)) / len(chunks) * 100
        if batch_num % max(1, total_batches // 10) == 0 or batch_num == total_batches:
            print(f"  [배치 {batch_num}/{total_batches}] {progress:.0f}% 완료")
    
    return vectordb


def main():
    print("=" * 60)
    print("ROADx RAG 인덱싱 v3 (재귀 검색 + 진단)")
    print("=" * 60)
    print(f"작업 폴더: {ROOT}")
    print(f"표준품셈 포함: {INCLUDE_PUMSE}")
    print(f"감사보고서 포함: {INCLUDE_AUDIT}")
    print()

    all_docs = []

    print("[1/3] 법령·행정규칙 텍스트 파일 로드")
    folder = find_folder(TARGET_FOLDERS["법령"])
    if folder:
        print(f"  폴더: {folder.name}")
        all_docs.extend(load_text_files_recursive(folder))
    else:
        print(f"  [⚠] 법령 폴더를 찾을 수 없음")
        print(f"  ROOT={ROOT}")
        print(f"  하위 폴더들:")
        for item in ROOT.iterdir():
            if item.is_dir():
                print(f"    - {item.name}")
        sys.exit(1)

    if INCLUDE_PUMSE and "표준품셈" in TARGET_FOLDERS:
        folder = find_folder(TARGET_FOLDERS["표준품셈"])
        if folder:
            print(f"\n[1b] 표준품셈 PDF 로드 ({folder.name})")
            all_docs.extend(load_pdf_files(folder, "표준품셈"))

    if INCLUDE_AUDIT and "감사보고서" in TARGET_FOLDERS:
        folder = find_folder(TARGET_FOLDERS["감사보고서"])
        if folder:
            print(f"\n[1c] 감사보고서 PDF 로드 ({folder.name})")
            all_docs.extend(load_pdf_files(folder, "감사보고서"))

    if not all_docs:
        print("\n[종료] 로드된 문서 없음")
        sys.exit(1)

    print(f"\n[2/3] 청킹")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", ". ", " ", ""],
    )
    chunks = splitter.split_documents(all_docs)
    
    total_chars = sum(len(c.page_content) for c in chunks)
    est_tokens = total_chars / 2.5
    est_cost_usd = est_tokens * 0.02 / 1_000_000
    est_minutes = max(est_tokens / TARGET_TPM, len(chunks) / 60)
    
    print(f"  ✓ 총 {len(all_docs)}개 문서 → {len(chunks):,}개 청크")
    print(f"  예상 토큰: 약 {est_tokens:,.0f}")
    print(f"  예상 비용: ${est_cost_usd:.4f} ≈ 약 {est_cost_usd * 1400:.0f}원")
    print(f"  예상 시간: 약 {est_minutes:.1f}분")
    
    # 사용자 확인
    print()
    answer = input(f"  진행하시겠습니까? (y/n): ").strip().lower()
    if answer != "y":
        print("  취소됨")
        sys.exit(0)

    print(f"\n[3/3] OpenAI 임베딩 + ChromaDB 저장 ({EMBED_MODEL})")
    
    t0 = time.time()
    embeddings = OpenAIEmbeddings(model=EMBED_MODEL)
    vectordb = embed_in_batches(chunks, embeddings, PERSIST_DIR)
    elapsed = time.time() - t0
    print(f"\n  ✓ 완료 ({elapsed/60:.1f}분, {len(chunks)/elapsed:.1f}청크/초)")

    sources = {}
    for c in chunks:
        src = c.metadata.get("source", "?")
        sources[src] = sources.get(src, 0) + 1
    
    with open(INDEX_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["파일명", "청크수"])
        for src, cnt in sorted(sources.items()):
            writer.writerow([src, cnt])
    print(f"  ✓ {INDEX_CSV} 저장 ({len(sources)}개 파일)")

    print("\n" + "=" * 60)
    print("테스트 질의: '민자도로 운영기간 종료 후 시설은 어떻게 되는가?'")
    print("=" * 60)
    test_results = vectordb.similarity_search(
        "민자도로 운영기간 종료 후 시설은 어떻게 되는가?", k=3
    )
    for i, doc in enumerate(test_results, 1):
        print(f"\n[검색 결과 {i}] 출처: {doc.metadata.get('source', '?')}")
        preview = doc.page_content[:200].replace("\n", " ")
        print(f"  {preview}...")

    print("\n" + "=" * 60)
    print("인덱싱 완료. 다음: python rag_query.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
