# FAST Core V2 Alignment + 500B — P2-2 표본 게이트 결과

## 이슈 유형 수

| 심각도 | 유형 수 | 유형 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 1 | 029960_OPEN_AFTER_CASH_SHARE_EXCHANGE_NO_CONFIRMED_SETTLEMENT |
| MINOR | 2 | 003690_ACTIVE_TRADE_DAYS_WITHOUT_VALID_ADJUSTED_MARK, 128940_ACTIVE_TRADE_DAY_WITHOUT_VALID_ADJUSTED_MARK |

## 실행 결과와 범위

- 전수 preflight: **PASS**. 2021-01-04~2026-08-31 정확 거래일 1,387일, 지원일 2026-09-01; 적격 2,573종목. raw market/date partition 2,776/2,776 COMPLETE.
- PIT 활성일 중 합성 adjusted+raw 행이 없는 날짜는 105,059건/956개 ticker였어. 분류: 승인 raw 비거래 placeholder 76,791, 공유 비거래 placeholder 26,367, adjusted analytic-invalid 1,899, source-nonusable 2. Unclassified raw-only / unexplained adjusted-only는 각각 0 / 0건; adjusted 파일 해시는 2,573/2,573 검증.
- 영구 제외 182쌍 canonical SHA-256 `9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12` 일치, (380440, KR7380440008) 제외. MA60 예열은 2016-01~2020-12.
- 대표 표본 32개, 10 workers, worker 오류 0건. 표본 replay 191.2초; 보수적 전수 예상 1.278시간.
- 전체 실행은 시작하지 않았어. 표본 validation이 CHECK_REQUIRED이며 CONTROL NAV coverage가 90% 미만이라 W의 필수 통과 조건을 만족하지 못했어.
- 최초 표본 시도는 Repository V2 상세 audit metadata 복사 성능 회귀 때문에 완료 전에 중단했어. loader를 공식 요약 metadata 경로와 맞춘 뒤 저장된 유효 결과는 수정하지 않고 corrected sample을 완료했어. validator CSV 타입 호환 수정도 별도 기록했어.
- P1/P2-1/P3 재생, 전략 튜닝, 운영 코드/기본 전략 변경, 외부 API 호출은 없었어.

## 공식 A~E 판정

| 게이트 | CONTROL | 후보 | 범위 |
|---|---|---|---|
| A 무결성 | CHECK_REQUIRED | CHECK_REQUIRED | 표본에서 실제 보유 종목 mark/기업행동 문제가 확인됨 |
| B 비용 | NOT_EVALUATED (표본 PASS) | NOT_EVALUATED (표본 PASS) | 전수 원장 미실행 |
| C 수익성 | NOT_EVALUATED | NOT_EVALUATED | 전수 P2-2 아님 |
| D MDD | NOT_EVALUATED (표본 CHECK_REQUIRED) | NOT_EVALUATED (표본 OBSERVED) | CONTROL coverage 77.58%; 후보 99.71% |
| E 유효성 | NOT_EVALUATED (표본 CHECK_REQUIRED) | NOT_EVALUATED (표본 OBSERVED) | 전수 평가 미실행 |

## 표본 포트폴리오 지표 (진단 전용, 공식 P2-2 결과 아님)

수익률·MDD·자산 비교는 32개 표본에 한정돼. CONTROL의 결측 NAV 때문에 종료자산·총수익률·CAGR 및 공식 MDD를 계산하지 않았어. 승률·순수익률·보유기간은 cutoff 전 실제 청산된 표본 거래만 분모로 사용해.

| 지표 | CONTROL 표본 | 후보 표본 | 후보−CONTROL 표본 |
|---|---:|---:|---:|
| 종료 자산(원) | — | 216,023,485.69 | — |
| 총수익률(%) | — | 8.01 | — |
| CAGR(%) | — | 1.37 | — |
| NAV coverage 기준 MDD(표본 %) | — | -3.95 | — |
| 유효 NAV 관측 MDD(%) | -7.41 | -3.95 | 3.46 |
| NAV coverage(%) | 77.58 | 99.71 | 22.13 |
| 유효 NAV 일수 | 1,076.00 | 1,383.00 | 307.00 |
| NAV 결측일 | 311.00 | 4.00 | -307.00 |
| 최장 연속 NAV 결측일 | 297.00 | 1.00 | -296.00 |
| 미해결 mark 수 | 311.00 | 4.00 | -307.00 |
| 적격 진입 시도 | 38.00 | 13.00 | -25.00 |
| 현금 부족 skip | 0.00 | 0.00 | 0.00 |
| 현금 부족 skip율(%) | 0.00 | 0.00 | 0.00 |
| 실매수 | 38.00 | 13.00 | -25.00 |
| 실현 청산 | 36.00 | 12.00 | -24.00 |
| cutoff 미청산 | 2.00 | 1.00 | -1.00 |
| 지원일 청산 | 0.00 | 0.00 | 0.00 |
| 실현 거래 | 36.00 | 12.00 | -24.00 |
| 승률(%) | 22.22 | 58.33 | 36.11 |
| 평균 순수익률(%) | 0.43 | 21.97 | 21.54 |
| 중앙 순수익률(%) | -15.70 | 21.96 | 37.66 |
| 평균 보유 거래일 | 143.39 | 224.75 | 81.36 |
| 중앙 보유 거래일 | 65.00 | 185.00 | 120.00 |
| 최대 거래수익률(%) | 118.18 | 83.15 | -35.03 |
| 최대 거래손실률(%) | -24.41 | -18.76 | 5.65 |
| +20% 이상 거래 | 8.00 | 7.00 | -1.00 |
| +50% 이상 거래 | 5.00 | 3.00 | -2.00 |
| +100% 이상 거래 | 1.00 | 0.00 | -1.00 |
| -10% 이하 거래 | 28.00 | 5.00 | -23.00 |
| -15% 이하 거래 | 23.00 | 5.00 | -18.00 |
| -20% 이하 거래 | 3.00 | 0.00 | -3.00 |
| -30% 이하 거래 | 0.00 | 0.00 | 0.00 |
| Loss Guard 매수 | 27.00 | 5.00 | -22.00 |
| PROGRESSED 매수 | 10.00 | 8.00 | -2.00 |
| 평균 동시보유 | 4.16 | 2.09 | -2.07 |
| 최대 동시보유 | 8.00 | 5.00 | -3.00 |
| 평균 자본 활용률(%) | 11.73 | 6.30 | -5.43 |
| 최대 자본 활용률(%) | 23.76 | 16.17 | -7.59 |
| 평균 현금비중(%) | 88.27 | 93.70 | 5.43 |
| 총 회전 금액(원) | 368,132,671.25 | 136,832,861.65 | -231,299,809.60 |
| 회전율 배수 | 1.84 | 0.68 | -1.16 |
| 수수료(원) | 55,219.90 | 20,524.93 | -34,694.97 |
| 슬리피지(원) | 368,124.14 | 136,841.38 | -231,282.77 |
| 최고 실현손익 종목 | 12,030.00 | 270.00 | -11,760.00 |
| 상위 승자 손익 집중도(%) | 31.42 | 24.92 | -6.51 |

### 표본 NAV 및 비용

- CONTROL: 유효 1076/1387일 (77.58%), 결측 311일, 최장 연속 결측 297일, 관측 MDD -7.41% (`CHECK_REQUIRED`). 종료자산/NAV 기반 총수익률은 산출하지 않았어.
- 후보: 유효 1383/1387일 (99.71%), 결측 4일, 최장 연속 결측 1일, 관측 MDD -3.95% (`OBSERVED`). 표본 종료자산은 216,023,485.69원이지만 전수 공식 성과가 아니야.
- 표본 후보 필터 감사: {"PASS": 13, "REJECT_ALIGNMENT": 61, "REJECT_MA_UNAVAILABLE": 13, "REJECT_MCAP_BELOW_500B": 11}. exact signal-date market-cap partition/후보 trade parity 및 표본 비용·현금 invariant는 validation에 기록됐어.
- CONTROL 청산 사유: {"EXIT3_PROGRESSED_TO_TRANSITION": 2, "EXIT4_SCORE_DRAWDOWN_GE_15": 7, "LOSS_GUARD_CLOSE_LE_NEG_15": 27}; 후보 청산 사유: {"EXIT3_PROGRESSED_TO_TRANSITION": 2, "EXIT4_SCORE_DRAWDOWN_GE_15": 5, "LOSS_GUARD_CLOSE_LE_NEG_15": 5}.

## 미해결 이슈와 전체 실행 차단 사유

1. **029960 / KR7029960002 (MAJOR)** — 표본 CONTROL이 2024-11-18에 558주를 매수했고 cutoff에도 보유 중이야. 2025-05-30 주식교환 이후 2025-06-16 상장폐지, 주당 9,000원 현금교부 예정 공시가 기존 corporate-action 감사에 있지만 실제 입금/세금/수수료 및 계좌 정산 증빙은 없어. 2025-06-16~2026-08-31 297 거래일의 adjusted mark가 없어 NAV coverage가 77.58%로 내려갔어. 계약에 기업행동 정산이 없어서 9,000원×558주를 수익·미수금으로 임의 입력하지 않았고, 029960을 유니버스에서 빼지도 않았어.
2. **003690 / KR7003690005 (MINOR)** — raw 거래행이 있는 날짜에 adjusted mark가 없어 비거래 carry를 쓸 수 없어. 표본 CONTROL 13일, 후보 4일. 기존 P3-2의 네 날짜 진단과 겹치지만 P2-2 표본 영향으로 별도 기록했어.
3. **128940 / KR7128940004 (MINOR)** — 2022-07-05 실제 거래행의 mark 1일 누락; 비거래 placeholder가 아니라 carry하지 않았어.
- 010780/141070의 두 classified source-anomaly 날짜는 sample에 포함했어. 해당 날짜에 held-position missing mark는 발생하지 않았어. 이 종목의 sample trade는 정상 거래일 구간에서 별도 처리됐어.
- 따라서 CONTROL 표본 coverage <90%여서 `sample_validation.json`은 CHECK_REQUIRED. 계약상 전수 실행을 시작하지 않았고, P2-2 공식 성과/채택 판정은 보류야.

## 판정 상태와 다음 결정

- P2-2: sample gate `CHECK_REQUIRED`; full run 미실행. `NOT_FINAL_5WINDOW`, 후보 채택 `NOT_EVALUATED`, 기본 승격 `NOT_EVALUATED`; 기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 유지.
- 029960 교부금 입금 증빙과 기업행동 현금 정산 규칙이 정해지기 전에는 full P2-2를 재개하지 않아. raw 거래일 adjusted mark 문제도 임의 채우기/종목 제외 없이 별도 근거가 필요해.
- 정확한 표본 원장·NAV·missing mark·issue exposure·통계는 `sample_*` 산출물, `sample_identity_exposure_audit.csv`, `sample_issue_exposure.csv`, `metrics_comparison.csv`, `sample_annual_market_diagnostics.csv`에 있어.
