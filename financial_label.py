"""
============================================================
ROADx Phase 3 - Step 2
재무비율 → 수익성 A/B/C 등급 라벨링 (rule-based)
============================================================
입력: financial_features.csv (Step 1 산출물)
출력: financial_labeled.csv (등급 라벨 추가)
       labeling_report.html (등급별 요약 리포트)

라벨링 기준 (한국 신용평가 관행 + 민자 사업 특성):
  
  A등급 (우량): 안정적 수익 + 충분한 상환 능력
    - 영업이익률 ≥ 15% AND
    - DSCR_근사 ≥ 1.30 AND
    - 부채비율 ≤ 4.00
  
  B등급 (양호): 정상 운영, 일부 지표 약함
    - 영업이익률 ≥ 5% AND
    - DSCR_근사 ≥ 1.00 AND
    - 부채비율 ≤ 6.00
  
  C등급 (주의): 적자 또는 상환 부담
    - 위 조건에 미달

벤치마크 (실제 사례):
  - 천안논산고속도로 2024: DSCR 1.29 → B등급
  - 제이영동고속도로 2024: DSCR 0.31 → C등급

실행:
  python financial_label.py
============================================================
"""
import csv
import sys
from pathlib import Path
from collections import Counter, defaultdict


INPUT_CSV = "./financial_features.csv"
OUTPUT_CSV = "./financial_labeled.csv"
OUTPUT_HTML = "./labeling_report.html"


# ════════════════════════════════════════════════════════════
# 등급 분류 규칙
# ════════════════════════════════════════════════════════════
def classify_grade(row):
    """
    재무비율 → A/B/C 등급
    반환: (등급, 사유)
    """
    # 안전 변환
    def f(key):
        try:
            v = row.get(key, "")
            if v == "" or v is None:
                return None
            return float(v)
        except (ValueError, TypeError):
            return None
    
    영익률 = f("영업이익률")
    dscr = f("DSCR_근사")
    부채비율 = f("부채비율")
    이자보상 = f("이자보상배율")
    순이익률 = f("순이익률")
    
    # 핵심 지표 모두 누락 시 등급 불능
    if all(x is None for x in [영익률, dscr, 부채비율]):
        return "?", "주요 지표 추출 실패"

    # 수익성·상환능력 지표가 하나도 없으면(건설중 SPC 등) 수익성 등급 판정 불가
    # — 부채비율 하나만으로 A/B를 주면 학습 데이터가 오염됨
    if 영익률 is None and dscr is None:
        return "?", "수익성 지표 없음 (건설중 등) — 등급 판정 불가"
    
    # 적자 사업: 무조건 C
    if 영익률 is not None and 영익률 < 0:
        return "C", f"영업적자 (영업이익률 {영익률:.1%})"
    if 순이익률 is not None and 순이익률 < -0.05:
        return "C", f"당기순손실 (순이익률 {순이익률:.1%})"
    
    # DSCR 1.0 미만: 무조건 C
    if dscr is not None and dscr < 1.0:
        return "C", f"DSCR 1.0 미만 ({dscr:.2f})"
    
    # 이자 미충당: 무조건 C
    if 이자보상 is not None and 이자보상 < 1.0:
        return "C", f"이자보상배율 1.0 미만 ({이자보상:.2f})"
    
    # 부채비율 과다: B 이상 불가
    if 부채비율 is not None and 부채비율 > 6.0:
        return "C", f"부채비율 600% 초과 ({부채비율:.1f})"
    
    # A등급 조건
    a_conditions = []
    if 영익률 is not None:
        a_conditions.append(영익률 >= 0.15)
    if dscr is not None:
        a_conditions.append(dscr >= 1.30)
    if 부채비율 is not None:
        a_conditions.append(부채비율 <= 4.0)
    
    if a_conditions and all(a_conditions):
        reason_parts = []
        if 영익률 is not None:
            reason_parts.append(f"영익률 {영익률:.1%}")
        if dscr is not None:
            reason_parts.append(f"DSCR {dscr:.2f}")
        return "A", f"우량 ({', '.join(reason_parts)})"
    
    # B등급 조건
    b_conditions = []
    if 영익률 is not None:
        b_conditions.append(영익률 >= 0.05)
    if dscr is not None:
        b_conditions.append(dscr >= 1.00)
    if 부채비율 is not None:
        b_conditions.append(부채비율 <= 6.0)
    
    if b_conditions and all(b_conditions):
        reason_parts = []
        if 영익률 is not None:
            reason_parts.append(f"영익률 {영익률:.1%}")
        if dscr is not None:
            reason_parts.append(f"DSCR {dscr:.2f}")
        return "B", f"양호 ({', '.join(reason_parts)})"
    
    # 그 외: C
    return "C", "조건 미달"


def main():
    print("=" * 60)
    print("ROADx Phase 3 - Step 2: A/B/C 등급 라벨링")
    print("=" * 60)
    
    # 입력 파일 확인
    if not Path(INPUT_CSV).exists():
        print(f"[중지] {INPUT_CSV} 없음")
        print("       먼저 financial_extract.py 실행")
        sys.exit(1)
    
    # CSV 로드
    with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"입력: {len(rows)}건\n")
    
    # 라벨링
    labeled = []
    grade_counts = Counter()
    grade_companies = defaultdict(list)
    
    for row in rows:
        grade, reason = classify_grade(row)
        row["등급"] = grade
        row["등급사유"] = reason
        labeled.append(row)
        grade_counts[grade] += 1
        grade_companies[grade].append({
            "회사": row.get("회사명", "?"),
            "연도": row.get("사업연도", "?"),
            "사유": reason,
        })
        print(f"  [{grade}] {row.get('회사명', '?')} ({row.get('사업연도', '?')}): {reason}")
    
    # CSV 저장
    fieldnames = list(rows[0].keys())
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(labeled)
    print(f"\n[저장] {OUTPUT_CSV}")
    
    # HTML 리포트
    grade_color = {"A": "#1D9E75", "B": "#EF9F27", "C": "#E24B4A", "?": "#999"}
    grade_label = {"A": "우량", "B": "양호", "C": "주의", "?": "분류불가"}
    
    html_rows = []
    for grade in ["A", "B", "C", "?"]:
        if grade not in grade_companies:
            continue
        items = grade_companies[grade]
        html_rows.append(f"""
        <div style="margin: 16px 0;">
            <div style="background: {grade_color[grade]}; color: white;
                        padding: 8px 16px; border-radius: 4px 4px 0 0;
                        font-weight: 500;">
                {grade}등급 ({grade_label[grade]}) — {len(items)}건
            </div>
            <div style="background: {grade_color[grade]}15;
                        border-left: 4px solid {grade_color[grade]};
                        padding: 12px 16px;">
                {'<br>'.join(f"• <strong>{i['회사']} {i['연도']}</strong>: {i['사유']}" for i in items)}
            </div>
        </div>
        """)
    
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>ROADx 수익성 등급 분류 결과</title>
<style>
body {{ font-family: 'Segoe UI', '맑은 고딕', sans-serif; 
       max-width: 900px; margin: 30px auto; padding: 20px;
       background: #f5f7fa; color: #1a1a2e; }}
h1 {{ color: #1F3864; }}
.summary {{ display: flex; gap: 16px; margin: 20px 0; }}
.summary > div {{ flex: 1; padding: 16px; border-radius: 8px;
                  text-align: center; color: white; }}
.summary .count {{ font-size: 32px; font-weight: 600; }}
.summary .label {{ font-size: 14px; opacity: 0.9; }}
</style>
</head>
<body>
<h1>📊 ROADx 수익성 A/B/C 등급 분류</h1>
<p>입력 {len(rows)}건의 민자 SPC 재무 데이터를 rule-based로 분류한 결과입니다.</p>

<div class="summary">
    <div style="background: #1D9E75;">
        <div class="count">{grade_counts.get('A', 0)}</div>
        <div class="label">A등급 (우량)</div>
    </div>
    <div style="background: #EF9F27;">
        <div class="count">{grade_counts.get('B', 0)}</div>
        <div class="label">B등급 (양호)</div>
    </div>
    <div style="background: #E24B4A;">
        <div class="count">{grade_counts.get('C', 0)}</div>
        <div class="label">C등급 (주의)</div>
    </div>
    <div style="background: #999;">
        <div class="count">{grade_counts.get('?', 0)}</div>
        <div class="label">분류불가</div>
    </div>
</div>

<h2>등급별 상세</h2>
{''.join(html_rows)}

<h2>분류 기준</h2>
<table style="width: 100%; border-collapse: collapse; background: white;">
<tr style="background: #D5E8F0;">
    <th style="padding: 10px; text-align: left;">등급</th>
    <th style="padding: 10px; text-align: left;">조건 (모두 충족)</th>
</tr>
<tr><td style="padding: 10px; border: 1px solid #eee;"><strong style="color: #1D9E75;">A</strong></td>
    <td style="padding: 10px; border: 1px solid #eee;">영업이익률 ≥ 15% · DSCR_근사 ≥ 1.30 · 부채비율 ≤ 400%</td></tr>
<tr><td style="padding: 10px; border: 1px solid #eee;"><strong style="color: #EF9F27;">B</strong></td>
    <td style="padding: 10px; border: 1px solid #eee;">영업이익률 ≥ 5% · DSCR_근사 ≥ 1.00 · 부채비율 ≤ 600%</td></tr>
<tr><td style="padding: 10px; border: 1px solid #eee;"><strong style="color: #E24B4A;">C</strong></td>
    <td style="padding: 10px; border: 1px solid #eee;">위 조건 미달 · 영업적자 · DSCR 1.0 미만 · 이자보상배율 1.0 미만</td></tr>
</table>

<p style="margin-top: 30px; font-size: 13px; color: #666;">
ROADx 시스템 / Phase 3 Step 2 / Rule-based labeling for XGBoost training
</p>
</body></html>"""
    
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[저장] {OUTPUT_HTML}")
    
    # 요약
    print(f"\n" + "=" * 60)
    print("등급 분포")
    print("=" * 60)
    for grade in ["A", "B", "C", "?"]:
        if grade in grade_counts:
            count = grade_counts[grade]
            pct = count / len(rows) * 100
            print(f"  {grade}등급: {count}건 ({pct:.0f}%)")
    
    print(f"\n다음 단계: XGBoost 학습 + SHAP 분석")
    print(f"  python financial_xgboost.py")


if __name__ == "__main__":
    main()
