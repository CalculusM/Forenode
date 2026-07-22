# -*- coding: utf-8 -*-
"""
감사보고서 PDF 일괄 파서 — 백테스트 R6 회계 추출 표준 도구

사용: python parse_audit_reports.py "06 민자도로 재무제표\<노선폴더>"
원리: 연도 = 파일명 제출일(YYYY.MM.DD)의 연도 − 1 (텍스트 추출 순서 비의존 — 검증된 규칙).
      손익계산서 앵커(영업수익) 이후에서 계정 키워드별 [당기, 전기] 숫자 쌍 추출.
      파일 간 "당기 = 차기 파일의 전기" 교차검증 그리드를 출력 — 불일치 시 정정공시 흔적.
검증 이력: 제이영동(V-002)·천안논산(V-003)·신대구부산(V-004)에서 교차검증 통과.
주의: 노선마다 계정과목이 다름(통행료수입/통행료수익/도로운영수익, 도로관리원가 유무 등)
      — KEYWORDS에 양쪽 패턴 포함. 새 패턴이면 최신 PDF의 손익 구간을 먼저 눈으로 확인할 것.
"""
import fitz, re, os, io, json, sys

KEYWORDS = [
    ('영업수익', '영업수익'), ('도로운영수익', '도로운영수익'), ('통행료수익', '통행료수익'),
    ('통행료수입', '통행료수입'), ('부속사업수익', '부속사업수익'), ('부속시설수익', '부속시설수익'),
    ('보조금수익', '보조금수익'), ('보조금수입', '보조금수입'), ('임대료수입', '임대료수입'),
    ('영업비용', '영업비용'), ('도로관리원가', '도로관리원가'), ('판관비', '판매비와관리비'),
    ('유형감가', '감가상각비'), ('무형상각', '무형자산상각비'),
    ('당기순이익', '당기순이익'), ('당기순손실', '당기순손실'),
]


def nums_after(text, kw, n=2, start=0, window=300):
    i = text.find(kw, start)
    if i < 0:
        return None
    seg = text[i:i + window]
    found = re.findall(r'\(?\d{1,3}(?:,\d{3}){2,}\)?', seg)
    vals = []
    for f in found[:n]:
        neg = f.startswith('(')
        v = int(re.sub(r'[(),]', '', f))
        vals.append(-v if neg else v)
    return vals if len(vals) == n else None


def parse_dir(directory):
    results = {}
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith('.pdf'):
            continue
        d = fitz.open(os.path.join(directory, fn))
        full = '\n'.join(pg.get_text() for pg in d)
        d.close()
        fm = re.search(r'\((20\d\d)\.\d\d\.\d\d\)', fn)
        cur_year = int(fm.group(1)) - 1 if fm else None
        is_idx = max(full.find('I. 영업수익'), full.find('Ⅰ. 영업수익'))
        if is_idx < 0:
            is_idx = full.find('영업수익')
        row = {'file': fn[-15:-4], 'year': cur_year}
        for key, kw in KEYWORDS:
            row[key] = nums_after(full, kw, start=is_idx if is_idx > 0 else 0)
        results[fn] = row
    return results


def print_grid(results):
    def eok(v):
        return round(v / 1e8, 1) if v is not None else None
    keys = [k for k, _ in KEYWORDS]
    print('파일(제출) 귀속 | ' + ' | '.join(keys))
    for fn, r in results.items():
        for gi, tag in [(0, '당'), (1, '전')]:
            yr = (r['year'] - gi) if r['year'] else '?'
            cells = [eok(r[k][gi]) if r[k] else None for k in keys]
            print(f"{r['file']} {yr}{tag} | " + ' | '.join(str(c if c is not None else '—') for c in cells))


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if not target:
        print(__doc__)
        sys.exit(0)
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(os.path.abspath(__file__)), target)
    res = parse_dir(target)
    out = os.path.join(target, '_parsed.json')
    io.open(out, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, indent=1))
    print_grid(res)
    print('\nsaved:', out)
