# FAST Core V2 Alignment + 500B — P3-2 공식 실전형 포트폴리오 결과

## 심각도 요약

| CRITICAL | MAJOR | MINOR |
|---:|---:|---:|
| 0 | 425 | 2 |

## 판정

- 이전 공식 CONTROL 재사용: **FAIL**. 현재 승인된 181쌍의 정확한 identity 제외 정책 및 unrestricted PIT 조건과 달라 P3-2 CONTROL을 후보와 동일 조건으로 다시 생성했어. 과거 공식 판정은 그대로 보존해.
- CONTROL / 후보 거래: **1,650 / 247**. 시총·월간 정배열 후보 gate 결과: `{"PASS": 247, "REJECT_ALIGNMENT": 4440, "REJECT_MA_UNAVAILABLE": 473, "REJECT_MCAP_BELOW_500B": 1489}`.
- 미시세 조정가격 입력 124종목: 사유별 `{"DATA_UNAVAILABLE: ADJUSTED_MISSING": 1, "REPOSITORY_V2_TRADING_SESSION_MISMATCH": 123}`. 대표 누락 `182360, 184230, 187790, 192250, 198440, 200130, 203650, 203690, 204620, 204630`(전체 목록은 price-source audit). exact signal-date 시총 UNRESOLVED 신호 0건. 이 입력 누락은 유니버스 분모에서 제외하거나 legacy/API 값으로 대체하지 않았고, 영향 미해결로 A를 CHECK_REQUIRED 처리해.
- P3-2 기간별 예비 A~E 결과는 `gate_results.json`에 있어. 나머지 4개 공식 기간을 실행하지 않았으므로 최종 5기간 판정은 **NOT_FINAL_5WINDOW**, 전체 공식 채택과 기본전략 승격은 **NOT_EVALUATED**야. A FAST Core V2가 공식 기본 전략으로 유지돼.

### P3-2 예비 A~E 판정

| 기준 | CONTROL | Alignment + 500B |
|---|---|---|
| A | CHECK_REQUIRED | CHECK_REQUIRED |
| B | PASS | PASS |
| C | CHECK_REQUIRED (총수익 UNRESOLVED%, CAGR UNRESOLVED%) | PASS (총수익 103.70%, CAGR 16.51%) |
| D | CHECK_REQUIRED (MDD UNRESOLVED%) | CHECK_REQUIRED (MDD -14.82%; CONTROL 상대판정 CHECK_REQUIRED) |
| E | CHECK_REQUIRED (73.92%; 842/1139일) | OBSERVED (99.65%; 1135/1139일) |

- A의 미해결 가격 입력은 124종목({"DATA_UNAVAILABLE: ADJUSTED_MISSING": 1, "REPOSITORY_V2_TRADING_SESSION_MISMATCH": 123}), exact signal-date 시총 UNRESOLVED는 0건이야. 구조 무결성 오류는 0건.

## CONTROL 대비

| 지표 | CONTROL | Alignment + 500B | 후보-대조군 |
|---|---:|---:|---:|
| 종료 자산 (원) | UNRESOLVED | 407,404,794.25 | UNRESOLVED |
| 총수익률 (%) | UNRESOLVED | 103.70 | UNRESOLVED |
| CAGR (%) | UNRESOLVED | 16.51 | UNRESOLVED |
| 포트폴리오 MDD (%) | UNRESOLVED | -14.82 | UNRESOLVED |
| NAV coverage (%) | 73.92 | 99.65 | 25.72 |
| MDD 유형 | CHECK_REQUIRED | OBSERVED | UNRESOLVED |
| MDD peak | 2023-04-07 | 2023-07-31 | UNRESOLVED |
| MDD trough | 2023-10-31 | 2023-10-31 | UNRESOLVED |
| MDD recovery | UNRESOLVED | 2024-04-29 | UNRESOLVED |
| 전체 평가일 | 1,139 | 1,139 | 0.00 |
| 관측 NAV일 | 842 | 1,135 | 293.00 |
| 누락 NAV일 | 297 | 4 | -293.00 |
| 최장 연속 NAV 결측일 | 297 | 1 | -296.00 |
| 미해결 valuation marks | 297 | 4 | -293.00 |
| 적격 진입 시도 | 1,650 | 247 | -1,403.00 |
| 현금 부족 skip | 1,333 | 22 | -1,311.00 |
| 현금 부족 skip 비율 (%) | 80.79 | 8.91 | -71.88 |
| 실제 진입 | 317 | 225 | -92.00 |
| 실현 청산 | 271 | 207 | -64.00 |
| cutoff 미청산 | 46 | 18 | -28.00 |
| 평균 동시 보유 수 | 35.84 | 27.08 | -8.76 |
| 최대 동시 보유 수 | 55 | 52 | -3.00 |
| 실제 청산 승률 (%) | 23.25 | 39.13 | 15.88 |
| 실제 청산 평균 순수익률 (%) | 4.97 | 17.09 | 12.12 |
| 실제 청산 중앙 순수익률 (%) | -15.73 | -14.64 | 1.09 |
| 평균 보유 거래일 | 101.94 | 132.97 | 31.03 |
| 중앙 보유 거래일 | 57.00 | 89.00 | 32.00 |
| 회전율 금액 (원) | 2,991,557,738.59 | 2,318,454,687.10 | -673,103,051.48 |
| 회전율 (초기자본 배수) | 14.96 | 11.59 | -3.37 |
| 평균 자본 활용 (%) | 89.32 | 62.97 | -26.35 |
| 최대 자본 활용 (%) | 99.97 | 99.87 | -0.10 |
| 평균 현금 비중 (%) | 10.68 | 37.03 | 26.35 |
| 최대 동시 보유 수 | 55 | 52 | -3.00 |
| +20% 이상 실제 청산 승자 | 56 | 67 | 11.00 |
| +50% 이상 실제 청산 승자 | 40 | 47 | 7.00 |
| +100% 이상 실제 청산 승자 | 15 | 17 | 2.00 |
| -10% 이하 실제 청산 손실 | 203 | 123 | -80.00 |
| -15% 이하 실제 청산 손실 | 174 | 100 | -74.00 |
| -20% 이하 실제 청산 손실 | 15 | 9 | -6.00 |
| -30% 이하 실제 청산 손실 | 3 | 5 | 2.00 |
| 실제 진입 중 Loss Guard 발동 | 199 | 116 | -83.00 |
| 실제 진입 중 PROGRESSED 도달 | 86 | 101 | 15.00 |
| 실제 진입 중 PROGRESSED 미도달 | 231 | 124 | -107.00 |
| 최대 실제 청산 수익률 (%) | 434.05 | 249.20 | -184.85 |
| 최저 실제 청산 수익률 (%) | -33.23 | -44.39 | -11.16 |
| cutoff 기간 실현 포트폴리오 순손익 (원) | 67,377,717.97 | 176,040,313.64 | 108,662,595.67 |
| 총 수수료 (원) | 448,733.66 | 347,768.20 | -100,965.46 |
| 총 슬리피지 (원) | 2,991,400.82 | 2,318,545.55 | -672,855.27 |
| 지원일 cutoff 청산 | 0 | 1 | 1.00 |
| 지원일 청산 수수료 (원) | 0.00 | 672.17 | 672.17 |
| 지원일 청산 슬리피지 (원) | 0.00 | 4,485.60 | 4,485.60 |
| 상위 5 ticker 실현이익 집중도 (%) | 29.63 | 19.12 | -10.51 |

### 추가 원장 진단

- 평가 거래일 1,139일. CONTROL NAV coverage 73.92%, 후보 99.65%; MDD 종류는 각각 CHECK_REQUIRED / OBSERVED.
- CONTROL V2 신호 원장 cutoff 상태(현금 skip 포함, 실제 포트폴리오 보유 수가 아님): `{"OPEN_AT_CUTOFF": 168, "REALIZED": 1482}`. 후보 신호 원장 상태: `{"OPEN_AT_CUTOFF": 20, "REALIZED": 227}`. 실제 포트폴리오 cutoff 미청산은 표의 46 / 18건이야.
- 실제 포트폴리오 청산 exit reason(현금 skip 제외): CONTROL `{"EXIT3_PROGRESSED_TO_BASE": 1, "EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 2, "EXIT3_PROGRESSED_TO_WEAK": 6, "EXIT4_SCORE_DRAWDOWN_GE_15": 61, "LOSS_GUARD_CLOSE_LE_NEG_15": 199}`, 후보 `{"EXIT3_PROGRESSED_TO_BASE": 1, "EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 4, "EXIT3_PROGRESSED_TO_WEAK": 4, "EXIT4_SCORE_DRAWDOWN_GE_15": 80, "LOSS_GUARD_CLOSE_LE_NEG_15": 116}`.
- 2026-09-01 지원일 cutoff 이전 청산 체결: CONTROL 0건(수수료 0.00원, 슬리피지 0.00원, 실현손익 0.00원), 후보 1건(수수료 672.17원, 슬리피지 4,485.60원, 실현손익 -457,230.31원). 지원일 손익·비용은 평가 cutoff NAV와 기간 성과에서 분리해.
- 실제 청산 원장의 순수익률(0.1% 슬리피지와 양방향 0.015% 수수료 반영) 평균/중앙: CONTROL 4.97% / -15.73%, 후보 17.09% / -14.64%. 최저/최고는 CONTROL -33.23% / 434.05%, 후보 -44.39% / 249.20%.
- 후보 원장에 없는 CONTROL 거래 신호 1,459건 중 CONTROL 포트폴리오에서 체결·실현된 231건의 실제 순손익은 46,568,498.69원(48건 양수)이야. 후보 포트폴리오에 동일하게 재투자했다고 가정한 값은 아니고, 필터로 빠진 CONTROL 수익 기회 진단이야.
- 현금 부족 skip 후 재생성 없음. cash-skip된 후보 원장의 V2 terminal return 평균/중앙은 각각 30.62% / -14.61%이며, 포트폴리오 실현손익이 아닌 기회 진단치야.
- 실제 진입 시도 / 현금 부족 skip: CONTROL 1650 / 1333 (80.79%), 후보 247 / 22 (8.91%). 현금 부족은 공식 A~E 게이트가 아니야.
- 현금 부족률은 공식 PASS/FAIL 게이트가 아니라 실행 제약 진단치로만 보고했어.

## 무결성 / provenance

- 독립 원장 검증 상태: **CHECK_REQUIRED**; 중대 구조 검사 실패 0건. 세부 검사는 `integrity_audit.json` 참조.
- 샘플: 30 ticker, V2 신호 78건, CONTROL 진입 32건, 후보 진입 9건; 정확한 exact-signal KRX partition hash 및 매수·매도 비용·현금·1,139일 NAV 검증 전부 PASS. full run 예상 약 1.14시간, 실제 1.14시간.
- 전체 실행: worker 10, 유니버스 2,552 ticker, CONTROL/후보 signal trade 1,650/247; CPU 4,850.05초, RSS peak 3,140.19 MB.
- Worker 오류 0건 (2,552/2,552 ticker outcome 완료); 포트폴리오 실행 오류 CONTROL/후보 0/0건.
- 계획 commit: `df7f81acf42ba791c51442ba23c432a36eb6b1f7`. 결과 경로: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/`.
- 원천 문서, 실행 코드, Repository V2 adjusted 가격 파일, rolling authority, exact KRX cap partitions 및 산출물 SHA-256은 `source_manifest.json`과 `artifact_hashes.json`에 기록했어.
