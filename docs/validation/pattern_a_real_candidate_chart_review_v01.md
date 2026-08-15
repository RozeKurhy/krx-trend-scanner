# Pattern A Real Candidate Chart Review v0.1 설계 및 가이드라인 (Phase 9A)

## 1. 개요 및 목적

`Pattern A Real Candidate Chart Review v0.1`은 Full Universe Scanner v0.1(`13ab6f4`, 2026-08-14 기준)이 선별한 **180개 공인 CANDIDATE 종목 (TRANSITION 168개, EARLY_TREND 12개)**을 대상으로, 사람이 직접 실제 차트(월봉 ➔ 주봉 ➔ 일봉)를 검토하여 정량 지표와 시각적 차트 구조 간의 일치도 및 False Positive 패턴을 수집하고 수동 검증 데이터를 체계적으로 축적하기 위한 Phase이다.

> [!IMPORTANT]
> **Phase 9의 핵심 질문**:
> **"Scanner가 CANDIDATE로 분류한 종목들이 실제 월봉/주봉 구조에서도 대세 상승 초입 후보처럼 보이는가?"**
>
> * 본 단계는 미래 수익률 예측이나 자동 매수 추천을 만드는 단계가 아닙니다.
> * 기계가 180개를 임의로 랭킹하거나 컷오프하지 않고 **180개 전수를 투명하게 보존**하여 인간 전문가의 검토 대상 데이터셋으로 제공합니다.

---

## 2. Phase 9 Review Universe & Integrity

### 2.1 Scanner Source Metadata
* **Source Commit**: `13ab6f4` (Full Universe Scanner Integration v0.1)
* **Scanner As-Of**: `2026-08-14`
* **Source Artifact**: `artifacts/scanner/pattern_a_universe_scan_20260814.csv` (2,528 rows)

### 2.2 Candidate Extraction & Integrity Results
* **Extraction Rule**: `candidate_state == 'candidate'` (Evaluator 공식 계약)
* **Total Candidates Extracted**: **180개 (100% 1 ticker = 1 row)**
  * **TRANSITION**: **168개 (93.33%)**
  * **EARLY_TREND**: **12개 (6.67%)**
* **Duplicate Tickers**: **0건**
* **Non-Candidate Contamination**: **0건**
* **Non-COMMON Contamination**: **0건 (100% 보통주)**
* **Evaluator Not-Ready Contamination**: **0건 (100% Evaluator Ready)**
* **Score Not-Ready Contamination**: **0건 (100% Score Ready)**

---

## 3. Review Artifacts & Data Architecture

```text
artifacts/chart_review/
├── pattern_a_candidate_source_20260814.csv         # Scanner 전체 49개 측정값 원본 (180 rows, Overwrite 허용)
├── pattern_a_candidate_manual_review_20260814.csv  # Compact 측정값 + Human Annotation 컬럼 (180 rows, Overwrite 금지)
└── pattern_a_candidate_review_summary_20260814.json # 수동 검토 진행 현황 Summary
```

### 3.1 Overwrite Protection Policy
* 사용자가 `pattern_a_candidate_manual_review_20260814.csv`에 직접 수동 라벨링을 시작한 이후에는 Scanner 재실행 시 **기존 파일의 수동 입력값이 덮어써지지 않고 철저히 보존**된다.

### 3.2 Manual Review Columns Schema
| Column Name | Type | Initial Value | Allowed Values / Usage |
| :--- | :--- | :--- | :--- |
| `review_status` | String | `UNREVIEWED` | `UNREVIEWED`, `REVIEWED` (Workflow 진행 상태) |
| `monthly_structure` | String | `""` | 장기 하락 종료, 긴 박스권/수렴, 24MA 턴어라운드, 확장 여부 등 메모 |
| `weekly_structure` | String | `""` | 중기 저점 상승, MA 정렬 개선, 상단 저항 돌파 전후 등 메모 |
| `daily_entry_context` | String | `""` | 단기 확장 위치, 진입 타이밍 과도 여부 메모 |
| `manual_pattern_fit` | String | `UNREVIEWED` | `UNREVIEWED`, `GOOD_FIT`, `BORDERLINE`, `NOT_FIT`, `UNCERTAIN` |
| `manual_stage_fit` | String | `UNREVIEWED` | `UNREVIEWED`, `MATCH`, `TOO_EARLY`, `TOO_LATE`, `UNCLEAR` |
| `manual_notes` | String | `""` | 특이사항, 테마/이벤트 급등, 거래정지 등 자유 메모 |

---

## 4. Human Chart Review 가이드라인 및 체크리스트

### 4.1 Review 순서 원칙
> **월봉(Monthly) ➔ 주봉(Weekly) ➔ 일봉(Daily)**
> * 단기 일봉이 좋아 보인다는 이유로 월봉 구조가 미흡한 종목을 `GOOD_FIT`으로 올리지 않습니다.
> * 월봉에서 대세 구조를 먼저 확인하고 주봉에서 추세 개선을 확인한 뒤 일봉을 봅니다.

### 4.2 차트 체크리스트
1. **월봉 (Monthly Review)**:
   * 장기 하락 추세가 실제로 멈추고 횡보/베이스가 충분히 형성되었는가?
   * 24개월 이동평균선(24MA)이 평탄화되거나 완만하게 상방 전환하고 있는가?
   * 이미 큰 상승 파동이 진행되어 과도하게 확장(extended)된 상태는 아닌가?
2. **주봉 (Weekly Review)**:
   * 중기 저점이 점진적으로 높아지고 있는가 (Higher Lows)?
   * 주봉 12주/24주/60주 이동평균선 구조가 꼬임에서 정배열/수렴 방향으로 개선되고 있는가?
   * 단 1회의 급등 이벤트(Spike)로 인해 지표가 왜곡된 것은 아닌가?
3. **일봉 (Daily Review)**:
   * 단기 저항선 돌파 위치 및 이격도가 과도하게 벌어져 있지 않은가?

### 4.3 Manual Pattern Fit 판정 기준
* **GOOD_FIT**: 장기 베이스 형성 후 대세 상승 초입 구조와 시각적으로 잘 부합하는 경우 (매수 추천이 아님).
* **BORDERLINE**: 베이스는 있으나 전환 시점이 다소 불분명하거나 경계에 걸친 경우.
* **NOT_FIT**: 실제로는 장기 하락 진행 중이거나, 단순 급락 후 단기 반등이거나, 이미 대세 상승이 한참 진행된 경우.
* **UNCERTAIN**: 데이터 불규칙, 장기 거래정지, 잦은 감자/병합 등으로 판단이 어려운 경우.

---

## 5. Phase 8 Minor Provenance 및 Backlog 정리

### 5.1 9개 Stage-Unavailable 종목 원인 분석
Scanner 결과에서 `score_ready=True`이나 `stage_ready=False` (`evaluator_reason_codes=('state_insufficient_data',)`, `candidate_state=INSUFFICIENT_DATA`)인 9개 종목의 세부 결측 피처 분석:
* **`weekly_ma12_slope` 결측 (7개 종목)**:
  * `044180` (KD), `065420` (에스아이리소스), `065570` (삼영이엔씨), `206560` (덱스터), `003060` (에이프로젠바이오로직스), `007460` (에이프로젠), `036420` (콘텐트리중앙)
  * 과거 거래정지 또는 주봉 결손 구간으로 인해 12주 주봉 기울기 산출 불가.
* **`ma24_slope_acceleration` / `ma_spread` 결측 (2개 종목)**:
  * `318020` (포인트모바일), `413630` (씨피시스템)
  * 상장 히스토리가 36m~48m 경계에 있거나 월봉 데이터 부족으로 2차 미분 및 12개월 전 스프레드 산출 불가.
* **결론**: Stage Classifier v0.1의 필수 피처 부재로 인한 **정상적인 Fail-Closed 판정**임을 확인.

### 5.2 Phase 8 UNAVAILABLE (316개) 실제 세부 구성
* **Cache Missing**: 42개
* **Score & Stage Unavailable (단기 상장주 등)**: 265개
* **Stage-only Unavailable (피처 결측)**: 9개
* **합계**: $42 + 265 + 9 = \mathbf{316개}$

### 5.3 Technical Debt / Backlog
1. **Universe Double Load Cleanup**: `scan_pattern_a_universe` 내부의 Universe 중복 호출 로직 정리.
2. **NO_DATA_BEFORE_AS_OF Provenance 분리**: 캐시는 존재하나 과거 as_of 이전 데이터가 없는 경우 `CACHE_MISSING` 대신 `NO_DATA_BEFORE_AS_OF`로 정밀 구분.

---

## 6. 단위 및 전체 회귀 테스트 결과

* **Candidate Review Unit Tests (`tests/test_candidate_review.py`)**: **12 passed (100% Green)**
* **Full Test Suite**: **322 passed, 6 skipped, 1 deselected, 0 failed (100% Green)**

---

## 7. Phase 9 진행 상태 및 로드맵

* **Phase 8 (Full Universe Scanner Integration)**: **`DONE`**
* **Phase 9A (Candidate Review Dataset Preparation)**: **`COMPLETED & FROZEN`**
* **Phase 9B (Human Chart Review)**: **`GO (사용자 수동 차트 검토 즉시 착수 가능)`**
* **Phase 10 (Liquidity Filter)**: **`HOLD (Phase 9B 완료 후 착수)`**
