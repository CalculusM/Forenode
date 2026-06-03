"""
============================================================
ROADx Phase 3 - 통합 OPEX 모델 분석
============================================================
입력:
  ETC_U3_*.csv (포장보수현황) — 4,380건 발주 이력
  ETC_T8_*.csv (포장일반현황) — 54,760건 위치별 공사 이력

전략:
  1. 사업구분별 OPEX 분리 (수선유지 / 개량사업)
  2. 포장형태별 차등 분석 (아스팔트 / 콘크리트)
  3. 노선별 OPEX 패턴 추출 (38개 공통 노선)
  4. 운영기간별 OPEX 시계열 표준화
  5. 민자 관리주체 OPEX 시뮬레이션 모델 도출

산출물:
  - opex_by_event_type.json: 사업구분별 통계
  - opex_by_route.json: 노선별 OPEX 패턴
  - opex_lifecycle.json: 운영기간별 표준 OPEX 곡선
  - opex_summary_chart.png: 시각화

실행:
  python opex_analyze.py
============================================================
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict


# ════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════
REPAIR_CSV = "ETC_U3_07_04_933408.csv"  # 포장보수현황 (실적금액)
PAVEMENT_CSV = "ETC_T8_07_04_822504.csv"  # 포장일반현황 (위치별 이력)

OUTPUT_EVENT = "opex_by_event_type.json"
OUTPUT_ROUTE = "opex_by_route.json"
OUTPUT_LIFECYCLE = "opex_lifecycle.json"
OUTPUT_CHART = "opex_summary_chart.png"

# 실적 단위 (백만원)
REVENUE_UNIT_MILLION_KRW = True


# ════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════
def main():
    print("="*70)
    print("ROADx OPEX 통합 분석")
    print("="*70)
    
    # ─── 데이터 로드 ───
    print("\n[1/6] 데이터 로드")
    repair = pd.read_csv(REPAIR_CSV, encoding="cp949")
    pavement = pd.read_csv(PAVEMENT_CSV, encoding="cp949")
    
    # 날짜 정규화
    repair['공사시작일'] = pd.to_datetime(repair['공사시작일'], errors='coerce')
    repair['공사연도'] = repair['공사시작일'].dt.year
    repair = repair.dropna(subset=['공사연도', '실적', '사업구분'])
    repair['공사연도'] = repair['공사연도'].astype(int)
    
    pavement['관리일자'] = pd.to_numeric(pavement['관리일자'], errors='coerce')
    pavement = pavement.dropna(subset=['관리일자', '공사구분'])
    pavement['관리일자'] = pavement['관리일자'].astype(int)
    
    print(f"  포장보수현황: {len(repair):,}건 ({repair['공사연도'].min()}~{repair['공사연도'].max()})")
    print(f"  포장일반현황: {len(pavement):,}건 ({pavement['관리일자'].min()}~{pavement['관리일자'].max()})")
    
    # ─── 사업구분별 OPEX 통계 ───
    print("\n[2/6] 사업구분별 OPEX 통계")
    
    event_stats = {}
    for biz_type, grp in repair.groupby('사업구분'):
        event_stats[biz_type] = {
            "건수": int(len(grp)),
            "실적_평균_백만원": float(grp['실적'].mean()),
            "실적_중위_백만원": float(grp['실적'].median()),
            "실적_표준편차": float(grp['실적'].std()),
            "실적_최대_백만원": float(grp['실적'].max()),
            "실적_합계_백만원": float(grp['실적'].sum()),
        }
        print(f"  [{biz_type}]")
        print(f"    건수: {len(grp):,}")
        print(f"    실적 평균: {grp['실적'].mean():.1f}백만원")
        print(f"    실적 중위: {grp['실적'].median():.1f}백만원")
        print(f"    실적 합계: {grp['실적'].sum()/1000:.0f}억원")
    
    # ─── 연간 OPEX 시계열 (사업구분별) ───
    # 다운로드 폴더 범위: 2015~2025 (11년치)
    print("\n[3/6] 연도별 OPEX 시계열 (2015~2025)")
    
    yearly_pivot = repair[
        (repair['공사연도'] >= 2015) & (repair['공사연도'] <= 2025)
    ].pivot_table(
        values='실적', 
        index='공사연도', 
        columns='사업구분',
        aggfunc='sum',
        fill_value=0
    )
    
    yearly_count = repair[
        (repair['공사연도'] >= 2015) & (repair['공사연도'] <= 2025)
    ].pivot_table(
        values='실적',
        index='공사연도',
        columns='사업구분',
        aggfunc='count',
        fill_value=0
    )
    
    print(f"  단위: 백만원")
    print(yearly_pivot.to_string())
    
    yearly_avg = {
        "수선유지_연평균_백만원": float(yearly_pivot.get('수선유지사업', pd.Series([0])).mean()) if '수선유지사업' in yearly_pivot.columns else 0,
        "개량_연평균_백만원": float(yearly_pivot.get('개량사업', pd.Series([0])).mean()) if '개량사업' in yearly_pivot.columns else 0,
        "수선유지_연평균_건수": float(yearly_count.get('수선유지사업', pd.Series([0])).mean()) if '수선유지사업' in yearly_count.columns else 0,
        "개량_연평균_건수": float(yearly_count.get('개량사업', pd.Series([0])).mean()) if '개량사업' in yearly_count.columns else 0,
    }
    
    # ─── 노선별 OPEX 패턴 ───
    print("\n[4/6] 노선별 OPEX 패턴 (38개 공통 노선)")
    
    common_routes = set(repair['노선명'].dropna().unique()) & set(pavement['노선명'].dropna().unique())
    
    route_stats = []
    for route in common_routes:
        repair_route = repair[repair['노선명'] == route]
        pavement_route = pavement[pavement['노선명'] == route]
        
        # 노선 길이 추정 (포장일반현황의 시점·종점 max로)
        try:
            route_length_km = float(pd.to_numeric(pavement_route['종점'], errors='coerce').max())
        except:
            route_length_km = 0
        
        if route_length_km < 1 or route_length_km > 1000:
            route_length_km = None
        
        repair_by_type = repair_route.groupby('사업구분')['실적'].agg(['sum', 'mean', 'count'])
        
        period_years = repair_route['공사연도'].max() - repair_route['공사연도'].min() + 1
        if period_years < 1:
            period_years = 1
        
        # 연평균 보수비
        annual_total = repair_route['실적'].sum() / period_years
        annual_per_km = annual_total / route_length_km if route_length_km else None
        
        route_data = {
            "노선명": route,
            "노선길이_km": route_length_km,
            "관측기간_년": int(period_years),
            "보수공사_총건수": int(len(repair_route)),
            "보수실적_총합_억원": float(repair_route['실적'].sum() / 10),
            "연평균_보수비_억원": float(annual_total / 10),
            "연평균_km당_보수비_백만원": float(annual_per_km) if annual_per_km else None,
            "수선유지_건수": int(repair_by_type.loc['수선유지사업', 'count']) if '수선유지사업' in repair_by_type.index else 0,
            "수선유지_평균_백만원": float(repair_by_type.loc['수선유지사업', 'mean']) if '수선유지사업' in repair_by_type.index else 0,
            "개량_건수": int(repair_by_type.loc['개량사업', 'count']) if '개량사업' in repair_by_type.index else 0,
            "개량_평균_백만원": float(repair_by_type.loc['개량사업', 'mean']) if '개량사업' in repair_by_type.index else 0,
        }
        route_stats.append(route_data)
    
    # 연평균 보수비 큰 순으로 정렬
    route_stats.sort(key=lambda x: x['연평균_보수비_억원'], reverse=True)
    
    print(f"\n  Top 10 연평균 보수비 큰 노선:")
    print(f"  {'노선명':<25} {'길이km':>8} {'연평균억원':>10} {'km당백만원':>12}")
    for r in route_stats[:10]:
        length = r['노선길이_km'] if r['노선길이_km'] else 0
        per_km = r['연평균_km당_보수비_백만원'] if r['연평균_km당_보수비_백만원'] else 0
        print(f"  {r['노선명']:<25} {length:>8.0f} {r['연평균_보수비_억원']:>10.1f} {per_km:>12.1f}")
    
    # ─── 운영기간별 OPEX 시계열 표준화 ───
    print("\n[5/6] 운영기간별 OPEX 시계열 표준화")
    
    # 노선별 시작 연도 추정 (포장일반현황의 신설연도 min)
    route_start_year = {}
    for route, grp in pavement.groupby('노선명'):
        # 신설 이벤트 중 가장 빠른 연도
        new_events = grp[grp['공사구분'] == '신설']
        if len(new_events) > 0:
            route_start_year[route] = int(new_events['관리일자'].min())
    
    # 각 보수공사의 운영 N년차 계산
    repair['운영연차'] = None
    for idx, row in repair.iterrows():
        route = row.get('노선명')
        if route in route_start_year:
            repair.at[idx, '운영연차'] = int(row['공사연도']) - route_start_year[route]
    
    repair['운영연차'] = pd.to_numeric(repair['운영연차'], errors='coerce')
    repair_with_age = repair.dropna(subset=['운영연차'])
    repair_with_age = repair_with_age[
        (repair_with_age['운영연차'] >= 0) & (repair_with_age['운영연차'] <= 60)
    ]
    
    print(f"  운영연차 매칭 성공: {len(repair_with_age):,}건 / 전체 {len(repair):,}건")
    
    # 운영연차 그룹화 (5년 단위)
    bins = list(range(0, 65, 5))
    labels = [f"{i}-{i+4}년차" for i in bins[:-1]]
    repair_with_age['연차구간'] = pd.cut(
        repair_with_age['운영연차'].astype(int), 
        bins=bins, 
        labels=labels, 
        include_lowest=True,
        right=False
    )
    
    # 사업구분 × 연차구간 OPEX 통계
    lifecycle_pivot = repair_with_age.pivot_table(
        values='실적',
        index='연차구간',
        columns='사업구분',
        aggfunc='mean',
        observed=True
    )
    
    lifecycle_count = repair_with_age.pivot_table(
        values='실적',
        index='연차구간',
        columns='사업구분',
        aggfunc='count',
        observed=True
    )
    
    print(f"\n  운영연차별 평균 공사비 (백만원):")
    print(lifecycle_pivot.to_string())
    print(f"\n  운영연차별 공사 빈도 (건수):")
    print(lifecycle_count.to_string())
    
    # ─── 시각화 ───
    print("\n[6/6] 시각화")
    
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # (1) 연도별 OPEX 추이
        ax1 = axes[0, 0]
        if '수선유지사업' in yearly_pivot.columns:
            ax1.plot(yearly_pivot.index, yearly_pivot['수선유지사업']/1000, 
                    marker='o', label='수선유지사업', color='#1F3864', linewidth=2)
        if '개량사업' in yearly_pivot.columns:
            ax1.plot(yearly_pivot.index, yearly_pivot['개량사업']/1000, 
                    marker='s', label='개량사업', color='#E24B4A', linewidth=2)
        ax1.set_xlabel('연도')
        ax1.set_ylabel('보수실적 (억원)')
        ax1.set_title('연도별 사업구분 보수실적 (2015~2025)', fontsize=13)
        ax1.legend()
        ax1.grid(alpha=0.3)
        
        # (2) 운영연차별 평균 공사비
        ax2 = axes[0, 1]
        if not lifecycle_pivot.empty:
            x = range(len(lifecycle_pivot.index))
            width = 0.35
            if '수선유지사업' in lifecycle_pivot.columns:
                ax2.bar([i-width/2 for i in x], lifecycle_pivot['수선유지사업'], 
                       width, label='수선유지사업', color='#1F3864', alpha=0.8)
            if '개량사업' in lifecycle_pivot.columns:
                ax2.bar([i+width/2 for i in x], lifecycle_pivot['개량사업'], 
                       width, label='개량사업', color='#E24B4A', alpha=0.8)
            ax2.set_xticks(x)
            ax2.set_xticklabels(lifecycle_pivot.index, rotation=45, ha='right')
            ax2.set_ylabel('평균 공사비 (백만원)')
            ax2.set_title('운영연차별 평균 공사비', fontsize=13)
            ax2.legend()
            ax2.grid(alpha=0.3, axis='y')
        
        # (3) Top 10 노선별 연평균 보수비
        ax3 = axes[1, 0]
        top10 = route_stats[:10]
        names = [r['노선명'][:15] for r in top10]
        values = [r['연평균_보수비_억원'] for r in top10]
        ax3.barh(names, values, color='#1D9E75', alpha=0.8)
        ax3.set_xlabel('연평균 보수비 (억원)')
        ax3.set_title('노선별 연평균 보수비 Top 10', fontsize=13)
        ax3.invert_yaxis()
        ax3.grid(alpha=0.3, axis='x')
        
        # (4) 운영연차별 공사 빈도
        ax4 = axes[1, 1]
        if not lifecycle_count.empty:
            x = range(len(lifecycle_count.index))
            width = 0.35
            if '수선유지사업' in lifecycle_count.columns:
                ax4.bar([i-width/2 for i in x], lifecycle_count['수선유지사업'], 
                       width, label='수선유지사업', color='#1F3864', alpha=0.8)
            if '개량사업' in lifecycle_count.columns:
                ax4.bar([i+width/2 for i in x], lifecycle_count['개량사업'], 
                       width, label='개량사업', color='#E24B4A', alpha=0.8)
            ax4.set_xticks(x)
            ax4.set_xticklabels(lifecycle_count.index, rotation=45, ha='right')
            ax4.set_ylabel('공사 건수')
            ax4.set_title('운영연차별 공사 빈도', fontsize=13)
            ax4.legend()
            ax4.grid(alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(OUTPUT_CHART, dpi=120, bbox_inches='tight')
        plt.close()
        print(f"  ✓ {OUTPUT_CHART}")
    except Exception as e:
        print(f"  [경고] 차트 생성 실패: {e}")
    
    # ─── JSON 저장 ───
    print("\n[저장]")
    
    # 사업구분별 통계
    event_output = {
        "data_source": "한국도로공사 포장보수현황 (공공데이터포털)",
        "data_period": [int(repair['공사연도'].min()), int(repair['공사연도'].max())],
        "단위": "백만원",
        "총_건수": int(len(repair)),
        "사업구분별_통계": event_stats,
        "연도별_OPEX": {
            int(year): {
                col: float(val) for col, val in row.items()
            } 
            for year, row in yearly_pivot.iterrows()
        },
        "연평균_OPEX": yearly_avg,
    }
    with open(OUTPUT_EVENT, 'w', encoding='utf-8') as f:
        json.dump(event_output, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUTPUT_EVENT}")
    
    # 노선별 통계
    route_output = {
        "data_source": "한국도로공사 포장보수현황 + 포장일반현황",
        "단위": "노선길이(km), 보수비(억원), km당단가(백만원)",
        "공통_노선_수": len(common_routes),
        "노선별_통계": route_stats,
    }
    with open(OUTPUT_ROUTE, 'w', encoding='utf-8') as f:
        json.dump(route_output, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUTPUT_ROUTE}")
    
    # 운영연차별 OPEX 표준 곡선
    lifecycle_output = {
        "data_source": "한국도로공사 포장보수현황 + 포장일반현황 (운영연차 매칭)",
        "매칭_샘플수": int(len(repair_with_age)),
        "단위": "백만원 (평균 공사비)",
        "운영연차별_평균공사비": {
            str(idx): {
                str(col): float(val) if pd.notna(val) else None 
                for col, val in row.items()
            }
            for idx, row in lifecycle_pivot.iterrows()
        },
        "운영연차별_공사빈도": {
            str(idx): {
                str(col): int(val) if pd.notna(val) else 0 
                for col, val in row.items()
            }
            for idx, row in lifecycle_count.iterrows()
        },
        "활용_방법": (
            "신규 민자도로 30년 OPEX 시뮬레이션:\n"
            "  - 연차별 평균 공사비 × 빈도 = 연차별 기대 OPEX\n"
            "  - 수선유지사업: 매년 베이스라인 OPEX\n"
            "  - 개량사업: 8~15년 주기 스파이크"
        ),
    }
    with open(OUTPUT_LIFECYCLE, 'w', encoding='utf-8') as f:
        json.dump(lifecycle_output, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUTPUT_LIFECYCLE}")
    
    print("\n" + "="*70)
    print("분석 완료")
    print("="*70)
    print(f"\n핵심 발견:")
    print(f"  1. 사업구분별 단가:")
    print(f"     - 수선유지: 평균 {event_stats.get('수선유지사업', {}).get('실적_평균_백만원', 0):.0f}백만원")
    print(f"     - 개량사업: 평균 {event_stats.get('개량사업', {}).get('실적_평균_백만원', 0):.0f}백만원")
    print(f"  2. 연간 도로공사 보수 예산: 약 {(yearly_avg['수선유지_연평균_백만원']+yearly_avg['개량_연평균_백만원'])/1000:.0f}억원")
    print(f"  3. 노선당 km당 연간 보수비: {np.median([r['연평균_km당_보수비_백만원'] for r in route_stats if r['연평균_km당_보수비_백만원']]):.1f}백만원 (중위)")


if __name__ == "__main__":
    main()
