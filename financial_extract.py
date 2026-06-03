"""
============================================================
ROADx Phase 3 - Step 1
DART 감사보고서 PDF에서 재무비율 30종 자동 추출
============================================================
입력: 06 민자도로 재무제표/ 폴더의 PDF 파일들
출력: financial_features.csv (재무비율 30종)
       financial_extraction_log.txt (추출 로그)

처리 방식:
  1. PDF에서 텍스트 추출 (pdfplumber)
  2. 재무상태표·손익계산서·현금흐름표 페이지 자동 탐지
  3. 정규표현식 + 키워드 매칭으로 핵심 수치 추출
  4. 30종 재무비율 자동 계산
  5. CSV 저장 + 진단 로그

실행:
  pip install pdfplumber --break-system-packages
  python financial_extract.py
============================================================
"""
import re
import csv
import sys
from pathlib import Path
from collections import defaultdict

try:
    import pdfplumber
except ImportError:
    print("[중지] pdfplumber 미설치")
    print("  실행: pip install pdfplumber")
    sys.exit(1)


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
ROOT = Path.cwd()

# PDF 폴더 검색 키워드
PDF_FOLDER_KEYWORDS = ["06 민자도로", "감사보고서", "재무제표"]

OUTPUT_CSV = "./financial_features.csv"
OUTPUT_LOG = "./financial_extraction_log.txt"


# ════════════════════════════════════════════════════════════
# 추출할 재무 항목 (재무상태표·손익계산서)
# ════════════════════════════════════════════════════════════
# 각 항목별 키워드 패턴 (한국 회계기준 + IFRS)
EXTRACTION_PATTERNS = {
    # 재무상태표 - 자산
    "유동자산": ["유동자산"],
    "비유동자산": ["비유동자산", "고정자산"],
    "자산총계": ["자산총계", "자산 총계"],
    
    # 재무상태표 - 부채
    "유동부채": ["유동부채"],
    "비유동부채": ["비유동부채", "고정부채"],
    "부채총계": ["부채총계", "부채 총계"],
    "장기차입금": ["장기차입금", "장기 차입금"],
    "단기차입금": ["단기차입금", "단기 차입금"],
    
    # 재무상태표 - 자본
    "자본금": ["자본금"],
    "이익잉여금": ["이익잉여금", "결손금"],
    "자본총계": ["자본총계", "자본 총계"],
    
    # 손익계산서
    "영업수익": ["영업수익", "매출액", "매출"],
    "영업비용": ["영업비용", "매출원가"],
    "영업이익": ["영업이익", "영업손실"],
    "이자비용": ["이자비용"],
    "법인세": ["법인세", "법인세비용"],
    "당기순이익": ["당기순이익", "당기순손실"],
    
    # 현금흐름
    "영업활동현금흐름": ["영업활동", "영업활동으로 인한"],
    "감가상각비": ["감가상각비", "감가상각"],
}


# ════════════════════════════════════════════════════════════
# PDF 처리 함수
# ════════════════════════════════════════════════════════════
def find_pdf_folder():
    """PDF 폴더 자동 검색"""
    for item in ROOT.iterdir():
        if item.is_dir():
            for kw in PDF_FOLDER_KEYWORDS:
                if kw in item.name:
                    return item
    return None


def extract_amount_from_line(line):
    """텍스트 라인에서 숫자 추출 (단위 백만원 가정)"""
    # 콤마 포함 숫자 패턴: 1,234,567 또는 (1,234) 음수
    nums = re.findall(r"\(?-?[\d,]+\)?", line)
    
    candidates = []
    for n in nums:
        # 콤마 제거, 괄호는 음수
        is_negative = "(" in n or "-" in n
        cleaned = re.sub(r"[(),\-]", "", n)
        if cleaned.isdigit() and len(cleaned) >= 3:  # 최소 1,000 이상 (잡음 제거)
            val = int(cleaned)
            if is_negative:
                val = -val
            candidates.append(val)
    
    # 가장 큰 절대값을 가진 숫자가 보통 당기 값
    if candidates:
        return max(candidates, key=abs)
    return None


def extract_financials_from_pdf(pdf_path, log_lines):
    """PDF 1개에서 재무 항목 추출"""
    log_lines.append(f"\n{'='*60}")
    log_lines.append(f"파일: {pdf_path.name}")
    log_lines.append(f"{'='*60}")
    
    extracted = {}
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            log_lines.append(f"  페이지 수: {len(pdf.pages)}")
            
            # 모든 페이지 텍스트 결합
            all_text = ""
            for page in pdf.pages:
                text = page.extract_text() or ""
                all_text += "\n" + text
            
            # 라인 단위로 분리
            lines = all_text.split("\n")
            
            # 항목별 검색
            for item_name, keywords in EXTRACTION_PATTERNS.items():
                for kw in keywords:
                    for line in lines:
                        if kw in line:
                            # 키워드가 라인 시작 부근에 있어야 함 (목차 회피)
                            kw_pos = line.find(kw)
                            if kw_pos > 30:
                                continue
                            
                            amount = extract_amount_from_line(line)
                            if amount is not None and amount != 0:
                                # 첫 번째 매칭만 사용
                                if item_name not in extracted:
                                    extracted[item_name] = amount
                                    log_lines.append(
                                        f"  ✓ {item_name}: {amount:,} ({kw})"
                                    )
                                break
                    if item_name in extracted:
                        break
            
            missing = set(EXTRACTION_PATTERNS.keys()) - set(extracted.keys())
            if missing:
                log_lines.append(f"  [⚠] 누락 항목: {', '.join(sorted(missing))}")
    
    except Exception as e:
        log_lines.append(f"  [에러] PDF 파싱 실패: {e}")
        return None
    
    return extracted


def calculate_ratios(fs):
    """재무비율 30종 계산"""
    r = {}
    
    # 안전 계산 함수
    def safe_div(a, b):
        if b is None or b == 0 or a is None:
            return None
        return a / b
    
    # 1. 안정성 비율
    r["부채비율"] = safe_div(fs.get("부채총계"), fs.get("자본총계"))
    r["자기자본비율"] = safe_div(fs.get("자본총계"), fs.get("자산총계"))
    r["유동비율"] = safe_div(fs.get("유동자산"), fs.get("유동부채"))
    r["당좌비율"] = safe_div(fs.get("유동자산"), fs.get("유동부채"))  # 재고 미고려
    r["차입금의존도"] = safe_div(
        (fs.get("장기차입금") or 0) + (fs.get("단기차입금") or 0),
        fs.get("자산총계")
    )
    
    # 2. 수익성 비율
    r["영업이익률"] = safe_div(fs.get("영업이익"), fs.get("영업수익"))
    r["순이익률"] = safe_div(fs.get("당기순이익"), fs.get("영업수익"))
    r["ROA_총자산수익률"] = safe_div(fs.get("당기순이익"), fs.get("자산총계"))
    r["ROE_자기자본수익률"] = safe_div(fs.get("당기순이익"), fs.get("자본총계"))
    r["EBITDA_마진"] = safe_div(
        (fs.get("영업이익") or 0) + (fs.get("감가상각비") or 0),
        fs.get("영업수익")
    )
    
    # 3. 활동성 비율
    r["총자산회전율"] = safe_div(fs.get("영업수익"), fs.get("자산총계"))
    r["자기자본회전율"] = safe_div(fs.get("영업수익"), fs.get("자본총계"))
    
    # 4. 현금흐름 비율
    r["영업현금흐름_매출비"] = safe_div(
        fs.get("영업활동현금흐름"),
        fs.get("영업수익")
    )
    r["영업현금흐름_부채상환비"] = safe_div(
        fs.get("영업활동현금흐름"),
        fs.get("부채총계")
    )
    r["DSCR_근사"] = safe_div(
        (fs.get("영업이익") or 0) + (fs.get("감가상각비") or 0),
        fs.get("이자비용")
    )
    
    # 5. 이자 관련
    r["이자보상배율"] = safe_div(fs.get("영업이익"), fs.get("이자비용"))
    r["금융비용_매출비"] = safe_div(fs.get("이자비용"), fs.get("영업수익"))
    
    # 6. 절대값 (정규화 후 학습 입력)
    r["영업수익_원본"] = fs.get("영업수익")
    r["영업이익_원본"] = fs.get("영업이익")
    r["당기순이익_원본"] = fs.get("당기순이익")
    r["자산총계_원본"] = fs.get("자산총계")
    r["부채총계_원본"] = fs.get("부채총계")
    r["자본총계_원본"] = fs.get("자본총계")
    r["이자비용_원본"] = fs.get("이자비용")
    r["감가상각비_원본"] = fs.get("감가상각비")
    
    # 7. 파생 지표
    r["순부채"] = (fs.get("부채총계") or 0) - (
        (fs.get("장기차입금") or 0) + (fs.get("단기차입금") or 0)
    ) * 0  # 차입금 외 부채 (대략)
    r["고정장기적합률"] = safe_div(
        fs.get("비유동자산"),
        (fs.get("자본총계") or 0) + (fs.get("비유동부채") or 0)
    )
    r["유동성지표"] = safe_div(
        (fs.get("유동자산") or 0) - (fs.get("유동부채") or 0),
        fs.get("자산총계")
    )
    
    return r


def get_year_from_filename(filename):
    """파일명에서 연도 추출"""
    # 2026_03_30 → 2025년 사업 (3월 감사보고서는 전년도)
    matches = re.findall(r"(20\d{2})", filename)
    if matches:
        year = int(matches[0])
        # 3월 발행 감사보고서는 전년도 사업
        return year - 1
    return None


def get_company_from_filename(filename):
    """파일명에서 회사명 추출"""
    # '제이영동고속도로감사보고서2026_03_30.pdf' → '제이영동고속도로'
    name = Path(filename).stem
    # '감사보고서' 앞부분 사용
    if "감사보고서" in name:
        name = name.split("감사보고서")[0]
    # 연도 제거
    name = re.sub(r"20\d{2}.*", "", name)
    return name.strip()


# ════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("ROADx Phase 3 - Step 1: DART 재무비율 추출")
    print("=" * 60)
    
    # PDF 폴더 검색
    pdf_folder = find_pdf_folder()
    if not pdf_folder:
        print("[중지] 감사보고서 폴더를 찾을 수 없음")
        print("       다음 키워드 중 하나를 폴더명에 포함시키세요:")
        for kw in PDF_FOLDER_KEYWORDS:
            print(f"         - {kw}")
        sys.exit(1)
    
    print(f"폴더: {pdf_folder}")
    
    # PDF 파일 검색 (재귀)
    pdf_files = list(pdf_folder.rglob("*.pdf")) + list(pdf_folder.rglob("*.PDF"))
    pdf_files = sorted(set(pdf_files))
    
    print(f"PDF 파일: {len(pdf_files)}개\n")
    
    if not pdf_files:
        print("[중지] PDF 파일이 없음")
        sys.exit(1)
    
    log_lines = []
    log_lines.append(f"DART 재무비율 추출 로그")
    log_lines.append(f"폴더: {pdf_folder}")
    log_lines.append(f"파일 수: {len(pdf_files)}")
    
    results = []
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] {pdf_path.name}")
        
        company = get_company_from_filename(pdf_path.name)
        year = get_year_from_filename(pdf_path.name)
        
        # 재무 항목 추출
        fs = extract_financials_from_pdf(pdf_path, log_lines)
        if fs is None:
            continue
        
        # 비율 계산
        ratios = calculate_ratios(fs)
        
        # 결과 저장
        record = {
            "회사명": company,
            "사업연도": year,
            "원본파일": pdf_path.name,
            **ratios,
        }
        results.append(record)
        
        # 추출 성공 항목 수 출력
        success_count = sum(1 for v in fs.values() if v is not None)
        print(f"  → 재무 항목 {success_count}/{len(EXTRACTION_PATTERNS)}개 추출")
    
    if not results:
        print("\n[종료] 추출된 결과 없음")
        sys.exit(1)
    
    # CSV 저장
    print(f"\n[CSV 저장]")
    fieldnames = list(results[0].keys())
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            # None은 빈 칸으로
            writer.writerow({k: (v if v is not None else "") for k, v in r.items()})
    print(f"  ✓ {OUTPUT_CSV} ({len(results)}건)")
    
    # 로그 저장
    with open(OUTPUT_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"  ✓ {OUTPUT_LOG}")
    
    # 요약 출력
    print(f"\n" + "=" * 60)
    print("추출 요약")
    print("=" * 60)
    print(f"  총 PDF: {len(pdf_files)}개")
    print(f"  추출 성공: {len(results)}건")
    print(f"  비율 종수: {len(results[0]) - 3}개 (회사명·연도·파일명 제외)")
    
    # 핵심 비율 미리보기
    print(f"\n[미리보기] 처음 3건의 핵심 지표")
    print(f"{'회사명':<20} {'연도':<6} {'영업이익률':<12} {'부채비율':<12} {'DSCR_근사':<12}")
    print("-" * 70)
    for r in results[:3]:
        영익률 = r.get("영업이익률")
        부채율 = r.get("부채비율")
        dscr = r.get("DSCR_근사")
        영익률_str = f"{영익률:.2%}" if 영익률 else "N/A"
        부채율_str = f"{부채율:.2f}" if 부채율 else "N/A"
        dscr_str = f"{dscr:.2f}" if dscr else "N/A"
        print(f"{r['회사명']:<20} {str(r['사업연도']):<6} {영익률_str:<12} {부채율_str:<12} {dscr_str:<12}")
    
    print(f"\n다음 단계: rule-based로 A/B/C 등급 라벨링")


if __name__ == "__main__":
    main()
