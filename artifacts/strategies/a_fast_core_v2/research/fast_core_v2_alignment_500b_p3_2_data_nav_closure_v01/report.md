# FAST Core V2 P3-2 데이터·NAV 미해결 보정 및 재판정 V01

| 심각도 | 독립 문제 유형 수 | 문제 유형 기준 |
|---|---:|---|
| CRITICAL | 0 | 원장·계약 무결성의 치명적 구조 오류 |
| MAJOR | 3 | 코엔텍 정산 계약 공백, 123개 identity 범위 가격 로딩 오류, 380440 조정가격 파일 부재 |
| MINOR | 1 | 003690의 실제 거래일 4개 NAV 평가값 결측 |

> 유형 수는 독립 원인 기준이야. 124개 종목, 297일, 4일을 합산한 defect count가 아니고 심각도는 공식 A~E와 별개의 triage야.

## 작업 범위와 결론

- 시작 HEAD와 `origin/main`은 `cbef18c7eed1d7002b16751b1000df2ce9851061`로 일치했어. 기존 V01은 보존하고 신규 폴더에만 저장했어.
- 실패했던 123개 identity만 PIT 관측 시작일 범위로 signal 재평가했어: 123/123 로드 성공, worker 오류 0, CONTROL 새 거래 신호 44건(34종목), 후보 새 거래 신호 4건(4종목), signal-filter audit 133행. 다른 종목의 전략 신호는 재실행하지 않았어.
- 첫 신규 CONTROL 신호가 2022-01-07이라 저장된 신호 cache와 신규 123개 신호만 합쳐 CONTROL/후보의 전체 순차 포트폴리오 흐름을 재생했어. P3-2 기간은 2022-01-03~2026-08-31, 매도 T+1 지원일은 2026-09-01이야.
- A~E는 P3-2만 예비 재판정했어. P1/P2/P3-1, 전략 로직·비용 계약 변경, 운영·웹 변경, 공식 승격은 하지 않았어. 5기간 채택은 `NOT_FINAL_5WINDOW`, 승격은 `NOT_EVALUATED`야.

## A. 코엔텍 기업행동

공시로 2025-05-30 주식교환 완료, 주당 9,000원 현금교부, 2025-06-16 상장폐지를 확인했어. 다만 수정 공시의 2025-06-20은 지급 완료일이 아니라 지급 예정일이야. V01 계약에는 기업행동 미수금 인식·NAV·가용 현금 시점·특별 세금/수수료가 정의돼 있지 않아 정산 규칙이나 NAV를 임의로 넣지 않았어. 상세 근거는 [corporate_action_audit.md](corporate_action_audit.md)에 있어.

원본 V01 CONTROL에서 코엔텍 558주 진입은 실제 체결됐고, 2025-06-16부터 297거래일의 NAV 공백을 만들었어. 신규 123개 신호를 반영한 CONTROL 재생에서는 같은 진입이 `SKIPPED_CASH_UNAVAILABLE`로 바뀌었어. 신규 앞선 체결에 자금이 배분돼 필요액 4,999,844원보다 가용현금 613,269원이 적었고 매도대금은 T+1 대기였어. 따라서 새 원장에는 코엔텍 보유가 없고 297일 공백이 반복되지 않았어. 이건 기업행동 정산으로 고친 결과가 아니라 신호 입력 복원에 따른 현금 재배분/진입 skip이야. 원본 V01 297일 공백과 정산 계약 공백은 계속 기록돼. 새 CONTROL의 결측 1일은 128940의 2022-07-05 가격 mark야.

## B. 124개 가격 입력

- 123개 `REPOSITORY_V2_TRADING_SESSION_MISMATCH`는 전체 source 범위를 조회할 때 identity별 범위가 섞여 생긴 loader 거부였어. 각 adjusted 파일의 첫 날부터 제한해 다시 읽었고, 123개 모두 성공했어. 123개 조정가격 SHA-256이 진단/재평가 사이 모두 일치하고, unresolved session mismatch dates는 전부 PIT 관측 시작 전이야. PIT 내부 미해결 불일치는 0건. PIT 날짜는 관측/진입 자격으로만 취급했고 실제 법적 상장일이라고 추정하지 않았어.
- 이 123개가 기존 V01에서는 signal 생성 전에 제외돼 있었고, 제한 평가에서 CONTROL 44/후보 4 신규 trade signal이 나와 실제 영향이 확인됐어. 신규 signal 중 실제 매수 체결은 CONTROL 7, 후보 2였고 나머지는 현금 부족 skip이야.
- `380440` (`KR7380440008`)는 PIT 기록 `2021-05-21~2023-12-28`의 조정가격 파일 자체가 없어. 신호·거래 영향을 판정할 수 없어 보간/대체 없이 `CHECK_REQUIRED`로 남겼어.
- 종목별 ISU, PIT 범위, 세션 날짜, Repository V2 data range, hashes, 첫 신호 및 group별 영향은 [price_input_124_audit.csv](price_input_124_audit.csv)에 있어.

## C. 후보 003690 네 날짜

2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27은 KRX raw partition이 `COMPLETE`이고 거래량·거래대금이 있는 거래일이야. 따라서 직전 종가 carry 대상인 비거래 placeholder가 아니야. NAV에서 네 날짜를 계속 제외했고 후보는 1,135/1,139일(99.6488%, `OBSERVED`)이야. [candidate_4day_nav_audit.csv](candidate_4day_nav_audit.csv)에 원행·source partition hash·전일 조정종가·원래 missing mark를 보존했어.

## V01 대비 재생 결과

CONTROL의 V01 수익률/CAGR/MDD는 coverage 90% 미만(842/1,139)이어서 미확정이었어. 신규 재생 결과는 아직 380440 한 종목과 128940의 하루 mark가 남아 최종 채택 증거가 아니라 관측치야. 기존 55개 성과지표에 신규 청산 사유 6개 카운트를 덧붙인 비교는 [metrics_comparison.csv](metrics_comparison.csv), [exit_reason_counts.csv](exit_reason_counts.csv)를 봐.

| 지표 | V01 CONTROL | 재생 CONTROL | V01 후보 | 재생 후보 |
|---|---:|---:|---:|---:|
| 종료 자산 | 미확정 | 263,563,030.82원 | 407,404,794.25원 | 416,468,730.33원 |
| 총수익률 / CAGR | 미확정 / 미확정 | 31.78% / 6.11% | 103.70% / 16.51% | 108.23% / 17.06% |
| MDD | 미확정 | -38.70% (`OBSERVED`) | -14.82% (`OBSERVED`) | -13.64% (`OBSERVED`) |
| 유효 NAV / 1,139 | 842 / 1,139 | 1138 / 1,139 | 1,135 / 1,139 | 1135 / 1,139 |
| NAV coverage | 73.9245% | 99.9122% | 99.6488% | 99.6488% |
| 결측 NAV일 | 297 | 1 | 4 | 4 |
| 진입 시도 / 현금 부족 skip | 1,650 / 1,333 | 1694 / 1388 | 247 / 22 | 251 / 25 |
| 실제 진입 / 청산 / cutoff 미청산 | 317 / 271 / 46 | 306 / 263 / 43 | 225 / 207 / 18 | 226 / 208 / 18 |
| 승률 / 평균 청산 수익 / 중앙 청산 수익 | 23.25% / 4.9709% / -15.7326% | 21.29% / 3.1066% / -15.7326% | 39.13% / 17.0949% / -14.6433% | 38.94% / 17.9074% / -14.6904% |
| +20 / +50 / +100% 청산 | 56 / 40 / 15 | 48 / 34 / 13 | 67 / 47 / 17 | 68 / 49 / 18 |
| -10 / -15 / -20 / -30% 청산 | 203 / 174 / 15 / 3 | 200 / 172 / 16 / 4 | 123 / 100 / 9 / 5 | 124 / 101 / 8 / 5 |
| 평균 / 중앙 보유 거래일 | 101.94 / 57 | 101.14 / 54.0 | 132.97 / 89 | 133.30 / 87.5 |
| 최대 / 최소 순수익률 | 434.05% / -33.23% | 434.05% / -35.06% | 249.20% / -44.39% | 249.20% / -44.39% |
| Loss Guard / PROGRESSED | 199 / 86 | 198 / 79 | 116 / 101 | 118 / 100 |

신규 재생에서 **청산 사유별** 실제 체결 수: EXIT3_PROGRESSED_TO_BASE: CONTROL 0, 후보 1; EXIT3_PROGRESSED_TO_EARLY_TREND: CONTROL 2, 후보 2; EXIT3_PROGRESSED_TO_TRANSITION: CONTROL 2, 후보 4; EXIT3_PROGRESSED_TO_WEAK: CONTROL 5, 후보 4; EXIT4_SCORE_DRAWDOWN_GE_15: CONTROL 56, 후보 79; LOSS_GUARD_CLOSE_LE_NEG_15: CONTROL 198, 후보 118. 현금 부족 skip 비율은 CONTROL 81.94%, 후보 9.96%야. skip 비율은 공식 PASS/FAIL 게이트가 아닌 자금배분 진단치야.

## P3-2 예비 A~E

| 게이트 | CONTROL | Alignment + 500B |
|---|---|---|
| A 무결성 | CHECK_REQUIRED — 380440 조정가격 미해결 | CHECK_REQUIRED — 동일 |
| B 비용 | PASS | PASS |
| C 수익성 | PASS | PASS |
| D MDD | 기준 MDD -38.70% (`OBSERVED`) | PASS — 후보 MDD -13.64%; CONTROL 대비 개선 25.07%p |
| E NAV | OBSERVED (1138/1,139, 99.9122%) | OBSERVED (1135/1,139, 99.6488%) |

새 CONTROL MDD -38.70%라 절대 하한 -40%에 가깝고 `OBSERVED`야. D 후보 조건은 절대 MDD와 CONTROL 대비 변화 모두 통과해. A의 남은 조정가격 미해결로 전체 공식 P3-2는 `CHECK_REQUIRED`야.

## Worker·원장·provenance/hash

- 제한 signal worker 10개, 123/123 완료, 오류 0. CONTROL/후보 재생 scope issue 0건, cash conservation 모두 PASS. 신규 signal 행의 실제 entry는 각각 CONTROL 7건, 후보 2건이야.
- 기존 V01 `artifact_hashes.json`의 52개 SHA-256을 현재 다시 확인했고 불일치 0건. 181개 영구 제외 pair count와 원본 hash/preflight hash가 일치했어. KRX 시총 partition authority는 V01의 461/461 독립 검증 결과를 재확인했어.
- 새로 사용한 adjusted price files 123개 hash는 전부 일치해. 원천·코드·실행 범위는 [source_manifest.json](source_manifest.json), 산출물 SHA-256은 [artifact_hashes.json](artifact_hashes.json), 독립 확인은 [integrity_validation.json](integrity_validation.json)에 있어.
- 이 결과는 P3-2 연구 재판정이야. 5기간 공식 채택이나 승격 판정은 하지 않았어.
