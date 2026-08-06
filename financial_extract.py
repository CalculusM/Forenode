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
    "자본총계": ["자본총계", "자본 총계", "자 본 총 계"],
    
    # 손익계산서
    # (주의) 순수 "매출" 키워드는 재무상태표 "매출채권"·현금흐름표 "매출 등 수익활동"에
    # 오매칭되므로 금지. 매출원가형 SPC 손익서 계정(통행료수입 등)을 직접 나열한다.
    "영업수익": ["영업수익", "매출액", "도로운영수익", "통행료수익", "통행료수입"],
    "영업비용": ["영업비용", "매출원가"],
    "영업이익": ["영업이익", "영업손실"],
    "이자비용": ["이자비용"],
    "법인세": ["법인세", "법인세비용"],
    "당기순이익": ["당기순이익", "당기순손실"],

    # 현금흐름
    "영업활동현금흐름": ["영업활동", "영업활동으로 인한"],
    "감가상각비": ["감가상각비"],
    # 관리운영권(무형자산) 상각 — 민자 SPC의 지배적 상각 항목.
    # 손익계산서가 기능별 분류라 판관비 소액만 노출되는 노선이 있어
    # 손익·현금흐름·주석 전체에서 최대값(=연간 총상각액)을 취한다 (MAX_ITEMS 참조).
    "무형자산상각비": ["무형자산상각비", "관리운영권상각비", "관리운영권상각액"],
}

# 문서 전체에서 단위환산 후 최대값을 취하는 항목 (총액이 여러 곳에 분해 표기되는 상각류)
MAX_ITEMS = {"감가상각비", "무형자산상각비"}

# 손실 계정 라벨: 표에는 양수로 인쇄되지만 의미는 음수 → 부호 반전
LOSS_KEYWORDS = {"당기순손실", "영업손실", "결손금"}

# 손익계산서 구간(손익계산서 제목 ~ 현금흐름표 제목)에서만 찾는 항목.
# 건설중 SPC는 손익서에 이자비용 계정이 없는데(차입원가 전액 자본화),
# 전체 검색 시 현금흐름 보충주석의 "이자비용 등" 잔액이 혼입됨 → 구간 제한으로 차단.
PL_SCOPED_ITEMS = {"영업수익", "영업비용", "영업이익", "이자비용", "법인세", "당기순이익"}


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


# 금액 토큰: 콤마 3자리 그룹 필수(1,000 이상) — 주석번호·연도 등 잡음 차단.
# 괄호는 음수. 표의 당기 칸이 "-"(해당액 없음)인 경우도 토큰으로 잡는다.
_TOKEN_RE = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?|(?<!\S)-(?!\S)")
# "(주석5,16)", "(주 12)" 등 계정명 뒤 주석 참조 괄호 제거용
_NOTE_RE = re.compile(r"\([^()]*주[^()]*\)")
# 단위 선언: "(단위 : 원)" / "(단위: 천원)" / "(단위: 백만원)" / "(단위: 주)" ...
_UNIT_RE = re.compile(r"단\s*위\s*[::]\s*([^)\s]+)")


def _unit_multiplier(unit_word, prev):
    """단위 선언 문자열 → 원 환산 배수. 금액 단위가 아니면 None(해당 구간 스킵)."""
    if "백만" in unit_word and "원" in unit_word:
        return 1_000_000
    if "천" in unit_word and "원" in unit_word:
        return 1_000
    if "원" in unit_word:  # "원" (억원·달러 표기는 본 데이터셋에 없음)
        return 1
    return None  # 주식수(주)·%·배 등 비금액 단위


def find_keyword_start(line, norm, kw):
    """계정 키워드를 원문(위치≤30) 또는 공백제거본(위치≤15)에서 탐색.
    감사보고서 표 라벨은 '자 본 총 계'처럼 글자 사이 공백이 흔함.
    반환: 금액 탐색 시작 위치(원문 기준) 또는 None(미매칭)."""
    p = line.find(kw)
    if 0 <= p <= 30:
        return p + len(kw)
    q = norm.find(kw.replace(" ", ""))
    if 0 <= q <= 15:
        # 라벨 문자열에는 콤마 숫자가 없으므로 라인 처음부터 금액을 찾아도 안전
        return 0
    return None


def first_amount_after(line, kw_pos, kw_len):
    """계정 키워드 뒤 첫 금액(=당기 칸) 반환.
    반환: (status, value) — status: 'amount' | 'dash'(당기 없음) | 'none'(금액 없음)
    기존 max-abs 방식은 당기·전기 중 큰 값을 취해 전기값 혼입을 일으켰음."""
    seg = line[kw_pos + kw_len:]
    seg = _NOTE_RE.sub(" ", seg)
    m = _TOKEN_RE.search(seg)
    if not m:
        return "none", None
    tok = m.group(0)
    if tok == "-":
        return "dash", None
    neg = tok.startswith("(")
    val = int(re.sub(r"[(),]", "", tok))
    return "amount", -val if neg else val


def extract_financials_from_pdf(pdf_path, log_lines):
    """PDF 1개에서 재무 항목 추출 (모든 금액을 원 단위로 정규화)"""
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

            # 라인 단위로 분리 + 라인별 유효 단위(가장 최근 단위 선언) 추적
            lines = all_text.split("\n")
            line_units = []
            cur_mult = 1  # 선언 전 기본: 원
            for line in lines:
                um = _UNIT_RE.search(line)
                if um:
                    cur_mult = _unit_multiplier(um.group(1), cur_mult)
                line_units.append(cur_mult)

            # 재무제표 구간 앵커: 재무상태표 → 손익계산서 → 현금흐름표 제목 라인
            # 목차에도 같은 제목이 나오므로, 제목 직후 몇 줄 안에 "(단위: ...)" 선언이
            # 따라오는 실제 재무제표 페이지 제목만 인정한다.
            def _is_real_title(idx):
                return any(
                    _UNIT_RE.search(lines[j])
                    for j in range(idx + 1, min(idx + 6, len(lines)))
                )

            bs_i = pl_i = cf_i = None
            for i, line in enumerate(lines):
                n = re.sub(r"\s+", "", line)
                if bs_i is None and "재무상태표" in n[:6] and _is_real_title(i):
                    bs_i = i
                elif pl_i is None and bs_i is not None and "손익계산서" in n[:8] and _is_real_title(i):
                    pl_i = i
                elif cf_i is None and pl_i is not None and "현금흐름표" in n[:8] and _is_real_title(i):
                    cf_i = i
            if pl_i is not None and cf_i is not None:
                pl_range = (pl_i, cf_i)
                log_lines.append(f"  손익계산서 구간: 라인 {pl_i}~{cf_i}")
            else:
                pl_range = None  # 앵커 실패 시 전체 검색(기존 동작)

            # 공백 제거본 (띄어쓰기 라벨 "자 본 총 계" 등 매칭용)
            norm_lines = [re.sub(r"\s+", "", l) for l in lines]

            # 항목별 검색
            for item_name, keywords in EXTRACTION_PATTERNS.items():
                if item_name in MAX_ITEMS:
                    # 상각류: 손익서(기능별 분류)에는 판관비 소액만 나오는 노선이 있어
                    # 문서 전체(손익·현금흐름·주석)에서 단위환산 후 최대값 = 연간 총액을 취함
                    best = None
                    best_src = None
                    for li, line in enumerate(lines):
                        mult = line_units[li]
                        if mult is None:
                            continue
                        for kw in keywords:
                            start = find_keyword_start(line, norm_lines[li], kw)
                            if start is None:
                                continue
                            status, amount = first_amount_after(line, start, 0)
                            if status == "amount" and amount is not None and amount > 0:
                                v = amount * mult
                                if best is None or v > best:
                                    best = v
                                    best_src = f"{kw}, x{mult}"
                    if best is not None:
                        extracted[item_name] = best
                        log_lines.append(f"  ✓ {item_name}: {best:,} ({best_src}, max)")
                else:
                    # 일반 항목: 문서 순서상 첫 매칭 라인의 첫 금액(=당기 칸)
                    if item_name in PL_SCOPED_ITEMS and pl_range is not None:
                        scan = range(pl_range[0], pl_range[1])
                    else:
                        scan = range(len(lines))
                    done = False
                    for li in scan:
                        line = lines[li]
                        mult = line_units[li]
                        if mult is None:
                            continue
                        norm = norm_lines[li]
                        for kw in keywords:
                            start = find_keyword_start(line, norm, kw)
                            if start is None:
                                continue
                            # "부채와자본총계"류 합계 라인이 "자본총계"로 오매칭되는 것 차단
                            if item_name == "자본총계":
                                prefix = norm[:norm.find(kw.replace(" ", ""))]
                                if "부채" in prefix:
                                    continue
                            status, amount = first_amount_after(line, start, 0)
                            if status == "amount" and amount is not None and amount != 0:
                                if kw in LOSS_KEYWORDS and amount > 0:
                                    amount = -amount
                                extracted[item_name] = amount * mult
                                log_lines.append(
                                    f"  ✓ {item_name}: {extracted[item_name]:,} ({kw}, x{mult})"
                                )
                                done = True
                            elif status == "dash":
                                # 당기 칸이 '-' = 당기 해당액 없음 → 값 미기록으로 확정.
                                # (뒤쪽 주석 표로 넘어가면 전기값·잔액 등 오염값을 줍게 됨)
                                log_lines.append(f"  - {item_name}: 당기 '-' ({kw}) → 미기록")
                                done = True
                            if done:
                                break
                        if done:
                            break

            # 자본총계 직접 추출 실패 시(라벨과 금액이 다른 라인으로 분리된 PDF)
            # 회계 항등식 자본총계 = 자산총계 - 부채총계 로 도출 (자본잠식이면 음수)
            if ("자본총계" not in extracted
                    and extracted.get("자산총계") is not None
                    and extracted.get("부채총계") is not None):
                extracted["자본총계"] = extracted["자산총계"] - extracted["부채총계"]
                log_lines.append(
                    f"  ✓ 자본총계: {extracted['자본총계']:,} (자산총계-부채총계 항등식 도출)"
                )

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

    # 총 상각비(D&A) = 유형 감가상각비 + 무형자산(관리운영권) 상각비
    # 민자 SPC는 관리운영권 상각이 지배적 — 유형만 쓰면 EBITDA≈영업이익으로 왜곡됨
    if fs.get("감가상각비") is None and fs.get("무형자산상각비") is None:
        총상각비 = None
    else:
        총상각비 = (fs.get("감가상각비") or 0) + (fs.get("무형자산상각비") or 0)
    
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
        (fs.get("영업이익") or 0) + (총상각비 or 0),
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
        (fs.get("영업이익") or 0) + (총상각비 or 0),
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
    r["무형자산상각비_원본"] = fs.get("무형자산상각비")
    
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
        # 감사보고서가 아닌 PDF(실시협약서 등)는 재무 항목이 거의 안 나옴 → 행 생성 제외
        if len(fs) < 5:
            print(f"  → 재무 항목 {len(fs)}개 — 감사보고서 아님, 건너뜀")
            log_lines.append(f"  [건너뜀] 추출 항목 {len(fs)}개 < 5 — 감사보고서 아닌 PDF로 판단")
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
