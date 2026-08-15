# KRX Trend Scanner Development Roadmap

이 문서는 향후 작업 순서의 기준 문서다. 새로운 아이디어가 생겨도 바로
구현하지 않고, 어느 Phase에 속하는지 먼저 이 문서에서 위치를 정한다.

## 핵심 목표

이 프로젝트의 최종 목표는 단순히 **"이미 상승 중인 강한 종목"**을
찾는 것이 아니다.

최종 목표는:

> 대세 상승이 만들어지기 시작하는 종목을 여러 독립적인 패턴과
> 시장 신호를 이용해 조기에 탐지하는 것

기본 철학:

```text
가격 구조 -> 장기 추세 -> 상대강도 -> 거래대금 -> 수급 -> 펀더멘털
```

순으로 증거를 쌓고, 각 Pattern A~F는 먼저 독립적으로 검증한 뒤
마지막 단계에서 Market Leader Score로 통합한다.

## Status 표기 규칙

각 Phase는 다음 status 중 하나를 쓴다: `DONE` / `IN PROGRESS` / `NEXT` /
`PLANNED` / `BLOCKED`.

## Current Status

**Pattern A Core Engine**

| 단계 | 상태 | 상세/커밋 |
|---|---|---|
| Feature Validation | DONE | 17개 기본 Feature 검증 완료 |
| Historical Snapshot Validation | DONE | Lookahead 없는 과거 시점 재현 |
| Holdout Validation | DONE | OOS Case 29건 고정 |
| Negative Control | DONE | False turn & Non-pattern 종목 검증 |
| Outcome Audit | DONE | 사후 성과 독립 감사 |
| Base / Expansion Validation | DONE | 베이스 및 확장 구조 검증 |
| Feature Set Freeze v0.1 | DONE | Feature 계약 확정 |
| Score Design v0.1 (freeze `6e7cc95`) | DONE | 1세대 스코어 설계 |
| Score Design v0.2 (implementation freeze `fffce85`) | DONE | Core/Support 조화평균, 페널티 구조 |
| Pattern A v0.2 OOS2 Validation | DONE | 38건 OOS2 검증 완료 |
| Pattern A Stage Truth Set Freeze (46건) | DONE | Manual Stage 라벨링 확정 |
| Pattern A Stage Classifier v0.1 (`43ee01c`) | DONE | Rule-based Lifecycle 분류기 (OOS 35건 100% 통과) |
| Pattern A Evaluator Integration v0.1 (`51fc202`) | DONE | Single-stock 종단간 통합 API 및 Candidate State |
| Data Quality & Universe Preparation v0.1 (`0ce8012`) | DONE | Fail-Closed 종목명 조회, 36m 계약, 품질 감사 |
| Pattern A Score Momentum v0.1 (`707c594`) | DONE | Calendar 1M/3M/6M Raw & Component Delta 측정 계층 |
| Official Common Stock Cache Population | IN PROGRESS | KRX 공식 보통주 유니버스 일봉 캐시 수집 (Pipeline 완료, Full Population 진행 중) |
| Full Universe Scanner Integration | PLANNED | 전 종목 일괄 스캔 및 순위/모멘텀 분석 |

**Pattern B~F**: 미착수(NOT STARTED)  
**전체 시장 Scanner**: 준비 중(HOLD - Full Population 완료 대기)  
**Market Leader Score**: 미착수(NOT STARTED)  

---

## Phase 1. Pattern A Score v0.2 — DONE (`fffce85`)

목표: Pattern A Score의 구조적 문제를 해결하고 최종 v0.2 Score를 freeze한다.

핵심 작업:
* Core / Supporting interaction 재설계 (ma24_slope 중심 조화평균 결합)
* weekly_ma12_slope와 ma24_slope_acceleration의 보조 확인 구조화
* alignment bonus 및 Already Progressed penalty 적용
* 0~100 유계 클리핑 및 해석 가능한 세부 점수 분해

---

## Phase 2. Pattern A v0.2 OOS2 Validation — DONE

v0.2를 완전히 freeze한 뒤, 독립적인 새로운 종목/날짜 38건(OOS2)에 적용해 검증했다.

핵심 결과:
* Frozen Pattern A Score v0.2 적용 및 OOS2 전 과정에서 Score 무수정 원칙 준수
* Weak Core + Strong Support 억제 개선 확인
* Hard Negative False Turn 4건 개별 component 분해 완료
* v0.3 improvement evidence 기록

---

## Phase 3. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)

Score와 완전히 독립적인 주가 사이클 상의 lifecycle 위치 분류기.

목표 Stage:
* `WEAK`: 장기 하락 또는 베이스 미형성 국면
* `BASE`: 장기 횡보 및 지지선 구축 국면
* `TRANSITION`: 단기/중기 이평선 정렬 및 턴어라운드 시도 국면
* `EARLY_TREND`: 장기 베이스 돌파 및 초기 추세 확장 국면
* `PROGRESSED`: 장기 추세 과열 및 이격 과다 국면

핵심 결과:
* Manual Stage Truth Set 46건 및 OOS 35건 fixture 100% 통과 (Green)
* Stage는 Score를 참조하지 않고 오직 주가/이평선 구조적 위치만 평가

---

## Phase 4. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)

종목코드, 종목명, 일봉 데이터, 기준일(`as_of`)을 입력받아 Pattern A 분석 결과를 일관되게 반환하는 Public API.

핵심 구조:
* Public API: `evaluate_pattern_a(ticker, name, daily, as_of)`
* 통합 결과: `PatternAEvaluationResult` (Score, Stage, Candidate State, Feature Snapshot, Flags 등)
* 해석 상태(Candidate State): `CANDIDATE`, `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`

---

## Phase 5. Data Quality & Universe Preparation v0.1 — DONE (`0ce8012`)

전체 시장 스캐너 실행 전 데이터 무결성을 보장하기 위한 감사 계층.

핵심 결과:
* Name Lookup Fail-Closed 정책 (조회 실패 시 ticker fallback 대신 `MarketDataError` 발생)
* 36 Completed Monthly Bars 계약 일치 (`_drop_incomplete_current_month` 적용)
* UNSORTED_DATE 감지 시 `raw_data_ready = False` 처리
* QualityAuditor를 통한 캐시 무결성 검증

---

## Phase 6. Pattern A Score Momentum v0.1 — DONE (`707c594`)

Frozen Pattern A Score v0.2를 완료된 월봉(Completed Monthly) 시간축으로 반복 평가하여 Score 변화량을 산출하는 순수 측정 계층(Pure Measurement Layer).

핵심 설계:
* Public API: `compute_pattern_a_score_momentum(ticker, name, daily, as_of)`
* Exact Calendar Horizons: 정확한 1M($T-1$), 3M($T-3$), 6M($T-6$) Calendar Month 말일 시점 비교 (No Silent Backfill)
* Raw Score Delta & Component Delta 분해 (진단용 분해 관측값 제공)
* 히스토리 요구조건 및 Partial Readiness: Current(36m), 1M(37m), 3M(39m), 6M(42m)
* Error Provenance 분리: `INSUFFICIENT_HISTORY_*`, `MISSING_MONTHLY_OBSERVATION_*`, `OBSERVATION_ERROR_*`

---

## Phase 7. Official Common Stock Cache Population — IN PROGRESS

KOSPI / KOSDAQ 전체 보통주 유니버스의 일봉 데이터를 KRX로부터 안정적으로 수집/캐싱.

핵심 작업:
* KOSPI / KOSDAQ 보통주 티커 목록 공식 추출 (우선주, ETF, ETN, 스팩, 리츠 제외)
* PyKRX 기반 증분 일봉 데이터 수집 및 로컬 Parquet 캐시 구축
* Data Quality 감사 실행 및 정합성 검증

---

## Phase 8. Full Universe Scanner Integration — PLANNED (HOLD)

전체 유니버스를 대상으로 Pattern A Score, Stage, Score Momentum을 일괄 산출하고 다차원으로 분석.

핵심 작업:
* Universe 병렬/배치 평가 파이프라인 구축
* 다차원 결과 매트릭스 (Score × Stage × Momentum 1M/3M/6M)
* 상위 후보군 필터링 및 리포팅

---

## Phase 9. Real Candidate Chart Review — PLANNED

Scanner 상위 후보를 사람이 직접 검토 (월봉 -> 주봉 -> 일봉).

목적:
* Score가 높은데 실제 차트상 이상한 종목, Corporate Action 왜곡, 하락 추세 반등, 과열 종목 발견
* False Positive 케이스 수집 및 v0.3 개선 증거 축적

---

## Phase 10. Liquidity / Trading Value Filter — PLANNED

실전 Scanner에서 거래 빈약 종목을 걸러내기 위한 별도 축 (20일/60일 평균 거래대금 등).

---

## Phase 11. Relative Strength Infrastructure — PLANNED

KOSPI, KOSDAQ 지수 및 업종 대비 상대강도(RS) 산출 인프라 구축 (3M, 6M, 12M RS).

---

## Phase 12. Flow Confirmation — PLANNED

외국인 / 기관 순매수 수급 확인 축.

---

## Phase 13 ~ 17. Pattern B ~ F — PLANNED

* **Pattern B**: 장기 하락 추세 종료 및 Stage 2 전환형
* **Pattern C**: 신고가 직전 고점 압축형
* **Pattern D**: 상대강도 선행형
* **Pattern E**: 장기 변동성 수축형 (VCP)
* **Pattern F**: 실적 턴어라운드 + 차트 선행형

---

## Phase 18. Pattern Score Matrix & Market Leader Score — PLANNED

독립적인 Pattern A~F 점수와 RS, 수급, 실적, 모멘텀을 종합한 시장 주도주 종합 점수.

---

## Phase 19. Walk Forward / Paper Validation — PLANNED

과거 시점 시뮬레이션 및 실시간 전진 추적 검증.

---

## Phase 20. Production Scanner — PLANNED

최종 운영 형태의 웹/CLI 대시보드 및 알림 시스템.

---

## Near Term Milestones

1. Pattern A Score Design v0.2 — DONE
2. Pattern A v0.2 OOS2 Validation — DONE
3. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)
4. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)
5. Data Quality / Universe Preparation v0.1 — DONE (`0ce8012`)
6. Pattern A Score Momentum v0.1 — DONE (`707c594`)
7. Official Common Stock Cache Population — IN PROGRESS
8. Full Universe Scanner Integration — PLANNED (HOLD)
9. Real Candidate Chart Review — PLANNED

---

## Development Principles

* **Principle 1**: Pattern별 Feature를 먼저 독립 검증한다.
* **Principle 2**: 한 Pattern에서 실패한 Feature를 다른 Pattern에서도 자동 폐기하지 않는다.
* **Principle 3**: 미래 수익률을 이용해 threshold를 최적화하지 않는다.
* **Principle 4**: OOS 데이터를 본 순간 그 데이터는 다음 버전의 development data가 된다.
* **Principle 5**: Score, Stage, Score Momentum을 독립된 축으로 분리한다.
* **Principle 6**: 가능하면 Hard Filter보다 해석 가능한 soft scoring을 우선한다.
* **Principle 7**: 전체 Score가 높은 이유를 사람이 설명할 수 있어야 한다.
* **Principle 8**: 월봉 / 주봉이 장기 추세 판단의 기본이고 일봉은 단기 추세와 진입 timing 확인에 사용한다.
* **Principle 9**: 실제 전체 시장 Scanner를 돌린 뒤 나오는 예상하지 못한 false positive를 중요한 검증 데이터로 취급한다.
* **Principle 10**: Pattern A~F가 충분히 검증되기 전에는 Market Leader Score를 성급하게 만들지 않는다.
