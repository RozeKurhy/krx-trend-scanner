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
가격 구조 -> 장기 추세 -> 투자 적합성 필터 -> 수급 확인 -> 상대강도 -> 펀더멘털
```

순으로 증거를 쌓고, 각 Pattern A~F는 먼저 독립적으로 검증한 뒤
마지막 단계에서 Market Leader Score로 통합한다.

## Status 표기 규칙

각 Phase는 다음 status 중 하나를 쓴다: `DONE` / `IN PROGRESS` / `NEXT` /
`PLANNED` / `BLOCKED`.

## Current Status

**Pattern A Core Engine**: **`DONE / FROZEN`**

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
| Pattern A Stage Classifier v0.1 (`43ee01c`) | DONE | Rule-based Lifecycle 분류기 (Calibration 38/5/3, OOS 24/10/1) |
| Pattern A Evaluator Integration v0.1 (`51fc202`) | DONE | Single-stock 종단간 통합 API 및 Candidate State |
| Data Quality & Universe Preparation v0.1 (`0ce8012`) | DONE | Fail-Closed 종목명 조회, 36m 계약, 품질 감사 |
| Pattern A Score Momentum v0.1 (`707c594`) | DONE | Calendar 1M/3M/6M Raw & Component Delta 측정 계층 |
| Official Common Stock Cache Population | DONE | Full Population & Audit `8983e65`, final docs `7ff45fe` |
| Full Universe Scanner Integration | DONE | Official COMMON 2,528개 스캔 및 매트릭스 통합 완료 (`13ab6f4`) |
| Real Candidate Chart Review (Phase 9A/9B) | DONE | Phase 9A (Dataset Prep) & Phase 9B (Human42 Review) 완료 |
| Stage v0.2 Candidate Research | HOLD | PRESEAL 미달 및 026910 미해결로 프로덕션 미채택 (`d975f66`) |
| Stage v0.3 Existing Feature Research | CLOSED | 가설 A~G 벤치마크 훼손 확인 (`NO_GENERALIZABLE_RULE_FOUND`, `6f3c061`) |
| Stage v0.4 Multi-Year Feature Research | CLOSED | 5년 구조 피처 9종 분리 한계 확인 (`NO_USEFUL_MULTI_YEAR_FEATURE_FOUND`, `5be5b42`) |
| Pattern A Final Production Closure | DONE | 10대 Hard Gate 전수 통과 및 공식 영구 동결 (`05d03e1`) |
| Pattern A Stage Research Lifecycle | CLOSED | 알고리즘 연구 종료 (`KEEP_CURRENT_PRODUCTION`) |

**Pattern B~F**: 미착수(PLANNED)  
**전체 시장 Scanner**: 완료(DONE - Phase 8 Integration 및 Phase 9B Review 완료)  
**현재 진행 단계**: **`Phase 10 Investability & Tradability Filter (NEXT)`**  
**Market Leader Score**: 미착수(PLANNED - Phase 18)  

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
* Manual Stage Truth Set 46건(Exact 38, Adj 5, Sev 3 / 82.6%) 및 OOS 35건(Exact 24, Adj 10, Sev 1 / 68.6%) 검증 통과
* Stage는 Score를 참조하지 않고 오직 주가/이평선 구조적 위치만 평가하는 완전 독립 계층

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

## Phase 7. Official Common Stock Cache Population — DONE

KOSPI / KOSDAQ 보통주 2,528개 대상 원자적 캐시(Atomic Write) 구축 및 데이터 무결성 검증 완료.

핵심 증거:
* Full Population & Final Audit: `8983e65`
* Final Documentation & Provenance Cleanup: `7ff45fe`

핵심 성과:
* Official COMMON Coverage 98.34% (2,486 / 2,528) 달성
* 구조적 오염 0건 (Future/Duplicate/Unsorted/Schema Violations 0, Temp Residue 0)
* Contract Critical Readiness 87.09% ~ 89.34% 확보 (6M Momentum 2,165개 계산 가능)

---

## Phase 8. Full Universe Scanner Integration — DONE (`13ab6f4`)

Official KRX KOSPI / KOSDAQ `AssetType.COMMON` universe를 대상으로 Pattern A Score, Official Stage, Candidate State, Score Momentum, Readiness 및 Quality Flags를 종목별 단일 row로 통합.

핵심 성과 및 계약:
* **평가 대상 (Evaluation Scope)**: Official KRX KOSPI / KOSDAQ 보통주 (`AssetType.COMMON`) 2,528개 전수 스캔 완료 (Row Emitted 2,528개 100% 일치)
* **제외 자산 (Excluded Assets)**: PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX 엄격 배제
* **Fail-Closed 보존**: Cache Missing 42개 + Score/Stage Unavailable 265개 + Stage-only Unavailable 9개 = 총 UNAVAILABLE 316개 row 유지 및 `INSUFFICIENT_DATA` 처리
* **예외 격리**: Scanner Calculation Errors 0건 달성
* **매트릭스 아티팩트 생성**: `artifacts/scanner/pattern_a_universe_scan_20260814.csv` 및 `summary.json`

---

## Phase 9. Real Candidate Chart Review & Structural Audit — DONE

Scanner CANDIDATE 종목을 사람이 직접 검토(월봉 ➔ 주봉 ➔ 일봉)하여 실제 품질과 구조적 한계를 확인하고, Stage 연구 사이클을 거쳐 최종 Production을 동결한 검증 단계.

구성 및 핵심 성과:
* **Phase 9A. Candidate Review Dataset Preparation — DONE**:
  * 180개 공인 CANDIDATE 종목 (TRANSITION 168개, EARLY_TREND 12개) 추출 및 무결성 검증 완료
  * Review Dataset 아티팩트(`pattern_a_candidate_source_20260814.csv`, `pattern_a_candidate_manual_review_20260814.csv`, `summary.json`) 생성 및 Overwrite Protection / Source Lock 적용
* **Phase 9B. Human Chart Review & Evidence — DONE**:
  * **Human42 Evidence**: EARLY_TREND 12건 전수 + Exploratory TRANSITION 30건 표본에 대한 상세 수동 차트 검토 수행
  * EARLY_TREND 적합률 83.3% (Good Fit 7, Borderline 3, Not Fit 2)
  * TRANSITION의 Premature, Recycled, Too Early/Late 오탐 유형 및 8대 Known Limitation 규명
* **후속 Stage 연구 및 Final Production Closure — DONE**:
  * Stage v0.2 Candidate (`d975f66`): PRESEAL 미달로 프로덕션 기각 (`HOLD`)
  * Stage v0.3 Existing Feature Research (`6f3c061`): 일반화 규칙 부재 확인 (`CLOSED`)
  * Stage v0.4 Multi-Year Feature Research (`5be5b42`): 5년 구조 피처 한계 확인 (`CLOSED`)
  * Pattern A Final Production Closure (`05d03e1`): **`KEEP_CURRENT_PRODUCTION`** 공식 확정 및 Stage Research 영구 종료

---

## Phase 10. Investability & Tradability Filter — NEXT

목적: Pattern A Candidate 중 실제로 사람이 검토하거나 실전 투자 대상으로 고려할 가치가 낮은 비투자성 / 극저유동성 종목을 사전에 분리한다.

핵심 설계 및 철학:
* **독립 필터링 계층**: 시가총액, 주가 수준, 거래대금, 유동성 기준은 Pattern A Score/Stage 알고리즘 자체에 섞지 않고 Scanner 후속 계층에서 분리 처리.
* **데이터 기반 Threshold 결정**: 특정 임계값을 사전 하드코딩하지 않고, 현재 180개 Candidate 코호트의 실측 분포(시가총액, 종가, 20D/60D 평균 거래대금 등)를 조사한 후 별도 검증을 통해 결정.
* **향후 확장**: 거래정지, 관리종목 등 실전 투자 부적합 조건 연계.

---

## Phase 11. Flow Confirmation Infrastructure — PLANNED

목적: 외국인 및 기관 순매수 수급 확인을 위한 독립 인프라 구축.

핵심 방향:
* **우선순위**: 외국인 수급 ➔ 기관 수급 ➔ 외인/기관 양매수
* **주요 측정 지표**: Foreign Net Buy 5D / 20D / 60D, Accumulation Trend, Net Buy / Trading Value Ratio
* **원칙**: 초기에는 절대적 Hard Filter가 아닌 독립 Confirmation Axis로 운영 (외인 미유입 초기 후보군 배제 방지).

---

## Phase 12. Relative Strength Infrastructure — PLANNED

목적: KOSPI, KOSDAQ 지수 및 업종 대비 상대강도(RS) 산출 인프라 구축.

핵심 방향:
* KOSPI / KOSDAQ / 섹터 대비 RS (3M, 6M, 12M Horizon)
* Pattern A Score에 단순 합산하지 않고 독립적인 시장 선도력 확인 축으로 검증.

---

## Phase 13 ~ 17. Pattern B ~ F — PLANNED

* **Phase 13. Pattern B**: 장기 하락 추세 종료 및 Stage 2 전환형
* **Phase 14. Pattern C**: 신고가 직전 고점 압축형
* **Phase 15. Pattern D**: 상대강도 선행형
* **Phase 16. Pattern E**: 장기 변동성 수축형 (VCP)
* **Phase 17. Pattern F**: 실적 턴어라운드 + 차트 선행형

---

## Phase 18. Pattern Score Matrix & Market Leader Score — PLANNED

독립적인 Pattern A~F 점수와 Investability 결과, RS, 수급(Flow), 모멘텀, 실적 증거를 종합한 시장 주도주 종합 점수 체계 구축.

---

## Phase 19. Walk Forward / Paper Validation — PLANNED

과거 시점 시뮬레이션 및 실시간 전진 추적 검증.

---

## Phase 20. Production Scanner & Operational Dashboard — PLANNED

CLI / Web 대시보드, 관심종목 워크플로우, 실시간 알림 등 최종 운영 시스템 구축.

---

## Near Term Milestones

1. Pattern A Score Design v0.2 — DONE
2. Pattern A v0.2 OOS2 Validation — DONE
3. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)
4. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)
5. Data Quality / Universe Preparation v0.1 — DONE (`0ce8012`)
6. Pattern A Score Momentum v0.1 — DONE (`707c594`)
7. Official Common Stock Cache Population — DONE (`8983e65`, `7ff45fe`)
8. Full Universe Scanner Integration — DONE (`13ab6f4`)
9. Real Candidate Chart Review (Phase 9A Dataset Prep & 9B Human42 Review) — DONE
10. Pattern A Final Production Closure (`05d03e1`) — DONE
11. Phase 10 Investability & Tradability Filter — NEXT

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
* **Principle 11**: Pattern detection과 Investability filtering은 철저히 분리한다 (시총, 주가, 거래대금은 Pattern A Score/Stage에 섞지 않음).
* **Principle 12**: Flow 및 Relative Strength는 독립 Confirmation Axis로 시작하며 초기에는 절대적 Hard Filter로 사용하지 않는다.
* **Principle 13**: 한두 종목의 오분류를 고치기 위해 Frozen Pattern rule을 임의로 다시 열지 않으며, Pattern A는 Final Closure 이후 영구 동결(Frozen Algorithm)으로 취급한다.
