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
* **Phase 9B (Human Chart Review)**: **`IN PROGRESS (EARLY_TREND 12/12 완료, TRANSITION 30/168 샘플 완료, 총 42/180 검토 완료)`**
* **Phase 10 (Liquidity Filter)**: **`HOLD (Phase 9B 완료 후 착수)`**

---

## 8. Phase 9B: EARLY_TREND 12개 수동 차트 검토 결과 및 핵심 발견점

### 8.1 검토 진행 현황
* **대상 종목**: `EARLY_TREND` 12개 전 종목 (100% 검토 완료)
* **검토 관점**: 월봉 및 주봉 구조 중심 (일봉은 단기 진입 및 이격 맥락 확인용)

### 8.2 정량적 집계 결과

```text
+-----------------------+-------+------------+
| Manual Pattern Fit    | Count | Ratio (%)  |
+-----------------------+-------+------------+
| GOOD_FIT              | 7     | 58.3%      |
| BORDERLINE            | 3     | 25.0%      |
| NOT_FIT               | 2     | 16.7%      |
+-----------------------+-------+------------+
| Fit Ratio (GOOD+BORD) | 10    | 83.3%      |
+-----------------------+-------+------------+

+-----------------------+-------+------------+
| Manual Stage Fit      | Count | Ratio (%)  |
+-----------------------+-------+------------+
| MATCH                 | 4     | 33.3%      |
| TOO_EARLY             | 3     | 25.0%      |
| TOO_LATE              | 4     | 33.3%      |
| UNCLEAR               | 1     | 8.3%       |
+-----------------------+-------+------------+
```

### 8.3 종목별 세부 판정 요약
1. **`001540` 안국약품**: `GOOD_FIT` / `MATCH` (월/주봉 바닥 베이스 완성, 24MA 상방 안착, 12,000원 지지 시도 대세 초입)
2. **`033560` 블루콤**: `NOT_FIT` / `TOO_EARLY` (장기 하락 미종료, 바닥 모호, 월봉 60MA 단기 반등에 불과)
3. **`071200` 인피니트헬스케어**: `BORDERLINE` / `TOO_EARLY` (주봉 저점 상승 중이나 장기 저항 10,000~11,000원 돌파 전으로 초입 판단은 이름)
4. **`086060` 진바이오텍**: `NOT_FIT` / `TOO_EARLY` (월/주봉 이평선 꼬임, 베이스 형성 미성숙)
5. **`094840` 슈프리마에이치큐**: `GOOD_FIT` / `TOO_LATE` (패턴 자체는 우수하나 2026년 4월 초가 이상적 진입점, 현재는 늦음)
6. **`121440` 골프존홀딩스**: `BORDERLINE` / `UNCLEAR` (장기 하락 멈추고 베이스 형성 중이나 주봉 정배열 미완성 및 지지 미확인)
7. **`001450` 현대해상**: `GOOD_FIT` / `MATCH` (38,000원 돌파 후 신고가 48,000원 도전, 완벽한 대세 상승 초입)
8. **`003650` 미창석유**: `GOOD_FIT` / `TOO_LATE` (2025년 상반기 신고가 돌파 후 이미 시세가 크게 진행됨)
9. **`005430` 한국공항**: `GOOD_FIT` / `MATCH` (2025년 7월 돌파 및 2026년 6월 80,000원 신고가 돌파, 강한 대세 상승 시작)
10. **`089860` 롯데렌탈**: `GOOD_FIT` / `TOO_LATE` (7월 초 36,000원이 적기, 1.5달 만에 +60% 급등하여 늦음)
11. **`161890` 한국콜마**: `GOOD_FIT` / `MATCH` (62,000원 지지 후 신고가 돌파, 건강한 파동의 대세 상승 초입)
12. **`317400` 자이에스앤디**: `BORDERLINE` / `TOO_LATE` (단기간 2배 급등으로 이격 과다, 진행 속도 과속)

### 8.4 핵심 인사이트 (Timing의 양방향성 발견)
* **Pattern A 후보 방향성 및 구조적 품질**: `GOOD_FIT + BORDERLINE` 비율이 **83.3%**로 시스템의 종목 발굴 퀄리티는 매우 높음.
* **Stage Timing의 양방향 오차 (Two-Way Error)**:
  * `TOO_EARLY` (3개: 블루콤, 인피니트헬스케어, 진바이오텍)
  * `TOO_LATE` (4개: 슈프리마에이치큐, 미창석유, 롯데렌탈, 자이에스앤디)
* **설계적 결론**:
  * 단순히 단일 임계값(Threshold)을 위나 아래로 이동시키는 1차원적 조정으로는 `EARLY_TREND` 타이밍을 최적화할 수 없음.
  * **인간 검토자의 `EARLY_TREND` 기준**: "충분히 성숙한 장기 베이스 종료 ➔ 주봉 구조 정배열 개선 ➔ 대세 상승이 '막 시작'되었으나 '아직 과도하게 진행되지 않은' 신선한 초입 구간!"

---

## 9. Phase 9B: TRANSITION 30개 샘플 수동 차트 검토 결과 및 5대 핵심 발견점

### 9.1 검토 샘플 구성
* **샘플 수**: 총 30개 (KOSDAQ 25개 + 시장 편향 완화를 위한 KOSPI 5개)
* **인간 검토자의 TRANSITION 판정 기준**:
  * TRANSITION은 완성된 Pattern A일 필요가 없으며, **`BORDERLINE + MATCH`가 정상적이고 건강한 기대 결과**임.
  * 진정한 TRANSITION 조건: "충분히 성숙한 월봉 베이스 + 주봉 저점 상승(Higher Low) + 주봉 이평선 개선 + 장기 저항선으로의 방향성 접근 또는 매물 소화".

### 9.2 정량적 집계 결과

```text
+-----------------------+-------+------------+
| Manual Pattern Fit    | Count | Ratio (%)  |
+-----------------------+-------+------------+
| GOOD_FIT              | 2     | 6.7%       |
| BORDERLINE            | 15    | 50.0%      |
| NOT_FIT               | 13    | 43.3%      |
+-----------------------+-------+------------+

+-----------------------+-------+------------+
| Manual Stage Fit      | Count | Ratio (%)  |
+-----------------------+-------+------------+
| MATCH                 | 13    | 43.3%      |
| TOO_EARLY             | 13    | 43.3%      |
| TOO_LATE              | 4     | 13.3%      |
| UNCLEAR               | 0     | 0.0%       |
+-----------------------+-------+------------+

+-----------------------+-------+------------+
| Pattern / Stage Combo | Count | Ratio (%)  |
+-----------------------+-------+------------+
| BORDERLINE / MATCH    | 12    | 40.0%      |
| GOOD_FIT / MATCH      | 1     | 3.3%       |
| BORDERLINE / TOO_EARLY| 3     | 10.0%      |
| NOT_FIT / TOO_EARLY   | 10    | 33.3%      |
| NOT_FIT / TOO_LATE    | 3     | 10.0%      |
| GOOD_FIT / TOO_LATE   | 1     | 3.3%       |
+-----------------------+-------+------------+
```

### 9.3 TRANSITION 5대 핵심 발견점 (Main Findings)

1. **`BORDERLINE + MATCH` (40.0%)의 정상성과 건강성**:
   * TRANSITION은 구조상 '미완성' 단계이므로 완성된 돌파나 완전 정배열이 없어도 되며, `BORDERLINE + MATCH`가 가장 자연스러운 상태임.
2. **최대 오차 원인: 조기 전환 (Premature Transition - 43.3%)**:
   * 장기 횡보 기간이 길거나, 저가권에 위치하거나, 저항선에 단순히 근접했다는 이유만으로 스캐너가 TRANSITION으로 잡았으나, **실제로는 주봉 저점 상승도 없고 이평선 개선도 없어 `BASE`에 머물러야 하는 종목들** (예: 매일홀딩스, 푸른저축은행, 진로발효, KCC건설, 광진실업, 오스템, 케이엘넷, 디지아이, 유수홀딩스, 금호전기).
   * *핵심 교훈: 단순히 저항선에 닿았다고 해서 TRANSITION이 되는 것이 아님.*
3. **과거 시세 재활용 가짜 양성 (Old Transition Recycle False Positive - 10.0%)**:
   * 과거에 이미 한 번 시세를 냈거나 돌파를 시도했다가 꺾여서 **주봉 저점 상승 구조가 깨지고 이평선이 역배열로 악화되었는데, 스캐너가 이를 새로운 TRANSITION으로 오인**하는 현상 (예: 대동기어, 예림당, 레드캡투어).
4. **스테이지 지연 (Stage Lag - 3.3%)**:
   * 한국기업평가처럼 이미 신고가 돌파 후 눌림목 지지 테스트 중인 우수한 종목이 TRANSITION에 머물러 있는 현상 (➔ 실제로는 EARLY_TREND에 가까움).
5. **모범 레퍼런스 케이스 (Gold Standard Cases)**:
   * **`000370` 한화손해보험**, **`017650` 대림제지**, **`017890` 한국알콜**, **`036190` 금화피에스시**, **`000050` 경방**, **`000850` 화천기공**.
   * *공통 특징: 성숙한 월봉 베이스 + 주봉 저점 상승 + 주봉 이평선 정배열 전환 + 장기 저항선 접근/소화 + 과도한 진행 없음.*


