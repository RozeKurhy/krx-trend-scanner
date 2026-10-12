# FAST Core V2 Alignment + 500B — P3-1 공식 실전형 포트폴리오 결과

## 심각도 요약

| CRITICAL | MAJOR | MINOR |
|---:|---:|---:|
| 0 | 3 | 0 |

## 판정

- 이전 공식 CONTROL 재사용: **FAIL**. 현재 승인된 182쌍의 정확한 identity 제외 정책 및 unrestricted PIT 조건과 달라 P3-1 CONTROL을 후보와 동일 조건으로 다시 생성했어. 과거 공식 판정은 그대로 보존해.
- CONTROL / 후보 거래: **1,069 / 175**. 시총·월간 정배열 후보 gate 결과: `{"PASS": 180, "REJECT_ALIGNMENT": 2401, "REJECT_MA_UNAVAILABLE": 356, "REJECT_MCAP_BELOW_500B": 1083}`.
- Repository V2 가격 미해결 117 ticker: 재검 결과 reason은 `{"UNCLASSIFIED_RAW_ONLY_SESSION": 117}`. 117개 모두 파일 readable이고 P3-1 가격범위와 교차해. 전체 이력 기본 범위 로딩 중 raw-only 원시일 45,272개가 비거래 placeholder 조건을 통과하지 못했고, exact PIT 및 2017-01~2021-12 예열 범위 안에 든 날짜는 0개였어. 그래도 전체범위 호출이 종목 전체를 fail-closed 처리해 신호가 ledger에 포함되지 않아 영향 미해결로 두고 A를 CHECK_REQUIRED 처리했어. 전체 목록과 날짜별 비교는 `repository_v2_unavailable_cause_audit.csv`에 있어. exact signal-date 시총 UNRESOLVED 신호는 0건이야.
- 380440 영구 제외 정책을 두 그룹 공통 pre-signal 유니버스에 적용했어. P3-2 저장 산출물 55/55개 해시가 기존 감사와 일치하고, 저장된 거래/현금/이벤트/valuation 행은 0개야. P3-2 재실행은 하지 않았고 이전 A 상태는 그대로 CHECK_REQUIRED야. 완전 가격자료였다면 어떤 신호가 나왔을지는 UNKNOWN이야.
- 코엔텍(029960) 기업행동 점검: `CHECK_REQUIRED`. CONTROL은 교환 효력일·cutoff에 558주 1건이 열려 있었고, 후보는 0건이야. 지원일 청산은 0건이며 확인하지 못한 교부금·세금·입금일을 임의 회계 처리하지 않았어.
- P3-1 기간별 예비 A~E 결과는 `gate_results.json`에 있어. 나머지 4개 공식 기간을 실행하지 않았으므로 최종 5기간 판정은 **NOT_FINAL_5WINDOW**, 전체 공식 채택과 기본전략 승격은 **NOT_EVALUATED**야. A FAST Core V2가 공식 기본 전략으로 유지돼.

### P3-1 예비 A~E 판정

| 기준 | CONTROL | Alignment + 500B |
|---|---|---|
| A | CHECK_REQUIRED | CHECK_REQUIRED |
| B | PASS | PASS |
| C | PASS (총수익 26.61%, CAGR 7.18%) | PASS (총수익 29.11%, CAGR 7.80%) |
| D | CHECK_REQUIRED (MDD -39.30%) | CHECK_REQUIRED (MDD -14.82%; CONTROL 상대판정 CHECK_REQUIRED) |
| E | EXACT (100.00%; 834/834일) | OBSERVED (99.52%; 830/834일) |

- A의 미해결 Repository V2 ticker 117개는 broad-history session mismatch 때문에 full run에서 fail-closed됐어. raw-only mismatch는 P3-1 PIT/예열 window 바깥에서만 관측됐지만 해당 ticker의 signal ledger가 없어 결과 영향은 UNKNOWN이야. exact signal-date 시총 UNRESOLVED는 0건, 구조 무결성 오류는 0건.

## CONTROL 대비

| 지표 | CONTROL | Alignment + 500B | 후보-대조군 |
|---|---:|---:|---:|
| 종료 자산 (원) | 253,210,255.52 | 258,212,861.05 | 5,002,605.53 |
| 총수익률 (%) | 26.61 | 29.11 | 2.50 |
| CAGR (%) | 7.18 | 7.80 | 0.62 |
| 포트폴리오 MDD (%) | -39.30 | -14.82 | 24.48 |
| NAV coverage (%) | 100.00 | 99.52 | -0.48 |
| MDD 유형 | EXACT | OBSERVED | UNRESOLVED |
| MDD peak | 2023-04-07 | 2023-07-31 | UNRESOLVED |
| MDD trough | 2023-10-31 | 2023-10-31 | UNRESOLVED |
| MDD recovery | UNRESOLVED | 2024-04-29 | UNRESOLVED |
| 전체 평가일 | 834 | 834 | 0.00 |
| 관측 NAV일 | 834 | 830 | -4.00 |
| 누락 NAV일 | 0 | 4 | 4.00 |
| 최장 연속 NAV 결측일 | 0 | 1 | 1.00 |
| 미해결 valuation marks | 0 | 4 | 4.00 |
| 적격 진입 시도 | 1,069 | 175 | -894.00 |
| 현금 부족 skip | 830 | 15 | -815.00 |
| 현금 부족 skip 비율 (%) | 77.64 | 8.57 | -69.07 |
| 실제 진입 | 239 | 160 | -79.00 |
| 실현 청산 | 199 | 129 | -70.00 |
| cutoff 미청산 | 40 | 31 | -9.00 |
| 평균 동시 보유 수 | 32.60 | 22.84 | -9.75 |
| 최대 동시 보유 수 | 42 | 38 | -4.00 |
| 실제 청산 승률 (%) | 18.59 | 29.46 | 10.86 |
| 실제 청산 평균 순수익률 (%) | 0.04 | 3.16 | 3.12 |
| 실제 청산 중앙 순수익률 (%) | -15.89 | -15.41 | 0.48 |
| 평균 보유 거래일 | 81.15 | 96.28 | 15.13 |
| 중앙 보유 거래일 | 54.00 | 60.00 | 6.00 |
| 회전율 금액 (원) | 2,176,801,943.11 | 1,452,363,352.17 | -724,438,590.95 |
| 회전율 (초기자본 배수) | 10.88 | 7.26 | -3.62 |
| 평균 자본 활용 (%) | 89.23 | 59.50 | -29.73 |
| 최대 자본 활용 (%) | 99.97 | 99.06 | -0.91 |
| 평균 현금 비중 (%) | 10.77 | 40.50 | 29.73 |
| 최대 동시 보유 수 | 42 | 38 | -4.00 |
| +20% 이상 실제 청산 승자 | 32 | 28 | -4.00 |
| +50% 이상 실제 청산 승자 | 21 | 15 | -6.00 |
| +100% 이상 실제 청산 승자 | 6 | 5 | -1.00 |
| -10% 이하 실제 청산 손실 | 159 | 89 | -70.00 |
| -15% 이하 실제 청산 손실 | 138 | 75 | -63.00 |
| -20% 이하 실제 청산 손실 | 10 | 6 | -4.00 |
| -30% 이하 실제 청산 손실 | 2 | 3 | 1.00 |
| 실제 진입 중 Loss Guard 발동 | 158 | 85 | -73.00 |
| 실제 진입 중 PROGRESSED 도달 | 53 | 52 | -1.00 |
| 실제 진입 중 PROGRESSED 미도달 | 186 | 108 | -78.00 |
| 최대 실제 청산 수익률 (%) | 434.05 | 217.63 | -216.42 |
| 최저 실제 청산 수익률 (%) | -32.61 | -44.39 | -11.78 |
| cutoff 기간 실현 포트폴리오 순손익 (원) | 683,633.82 | 20,425,471.22 | 19,741,837.40 |
| 총 수수료 (원) | 326,520.29 | 217,854.50 | -108,665.79 |
| 총 슬리피지 (원) | 2,176,607.19 | 1,452,232.45 | -724,374.74 |
| 지원일 cutoff 청산 | 0 | 0 | 0.00 |
| 지원일 청산 수수료 (원) | 0.00 | 0.00 | 0.00 |
| 지원일 청산 슬리피지 (원) | 0.00 | 0.00 | 0.00 |
| 상위 5 ticker 실현이익 집중도 (%) | 46.44 | 40.90 | -5.55 |

### 추가 원장 진단

- 평가 거래일 834일. CONTROL NAV coverage 100.00%, 후보 99.52%; MDD 종류는 각각 EXACT / OBSERVED.
- 후보 unresolved valuation marks 4건은 ticker `003690`, 날짜 `2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27`이야. actual raw row가 placeholder가 아닌 날 adjusted mark가 없어 carry를 허용하지 않았고, 그 4일 때문에 후보 NAV가 830/834일 관측됐어.
- CONTROL V2 신호 원장 cutoff 상태(현금 skip 포함, 실제 포트폴리오 보유 수가 아님): `{"OPEN_AT_CUTOFF": 198, "REALIZED": 871}`. 후보 신호 원장 상태: `{"OPEN_AT_CUTOFF": 33, "REALIZED": 142}`. 실제 포트폴리오 cutoff 미청산은 표의 CONTROL 40건 / 후보 31건이야.
- 실제 포트폴리오 청산 exit reason(현금 skip 제외): CONTROL `{"EXIT3_PROGRESSED_TO_EARLY_TREND": 1, "EXIT3_PROGRESSED_TO_WEAK": 3, "EXIT4_SCORE_DRAWDOWN_GE_15": 37, "LOSS_GUARD_CLOSE_LE_NEG_15": 158}`, 후보 `{"EXIT3_PROGRESSED_TO_TRANSITION": 2, "EXIT3_PROGRESSED_TO_WEAK": 2, "EXIT4_SCORE_DRAWDOWN_GE_15": 40, "LOSS_GUARD_CLOSE_LE_NEG_15": 85}`.
- 2025-06-02 지원일 cutoff 이전 청산 체결: CONTROL 0건(수수료 0.00원, 슬리피지 0.00원, 실현손익 0.00원), 후보 0건(수수료 0.00원, 슬리피지 0.00원, 실현손익 0.00원). 지원일 손익·비용은 평가 cutoff NAV와 기간 성과에서 분리해.
- 실제 청산 원장의 순수익률(0.1% 슬리피지와 양방향 0.015% 수수료 반영) 평균/중앙: CONTROL 0.04% / -15.89%, 후보 3.16% / -15.41%. 최저/최고는 CONTROL -32.61% / 434.05%, 후보 -44.39% / 217.63%.
- 후보 원장에 없는 CONTROL 거래 신호 932건 중 CONTROL 포트폴리오에서 체결·실현된 164건의 실제 순손익은 -16,727,085.11원(24건 양수)이야. 후보 포트폴리오에 동일하게 재투자했다고 가정한 값은 아니고, 필터로 빠진 CONTROL 수익 기회 진단이야.
- 현금 부족 skip 후 재생성 없음. cash-skip된 후보 원장의 V2 terminal return 평균/중앙은 각각 -6.12% / -14.99%이며, 포트폴리오 실현손익이 아닌 기회 진단치야.
- 실제 진입 시도 / 현금 부족 skip: CONTROL 1069 / 830 (77.64%), 후보 175 / 15 (8.57%). 현금 부족은 공식 A~E 게이트가 아니야.
- 현금 부족률은 공식 PASS/FAIL 게이트가 아니라 실행 제약 진단치로만 보고했어.

## 무결성 / provenance

- 독립 원장 검증 상태: **CHECK_REQUIRED**; 중대 구조 검사 실패 0건. 세부 검사는 `integrity_audit.json` 참조.
- Severity는 독립 문제 유형 수야(행·종목·날짜 수가 아님). 유형은 `issue_summary.json`에 있어: MAJOR `["P3-1 PIT ticker histories fail Repository V2 raw/adjusted session-set validation under the full-history loader", "At least one held-position valuation mark on an actual KRX session is unresolved", "P3-1 portfolio exposure intersects the unresolved Koentec cash-exchange settlement"]`.
- 대표 샘플: 30 ticker, CONTROL/후보 신호거래 23/4, 후보 필터 감사 72행; worker 10, 측정시간 172.05초, 예상 전체 1.07시간. 샘플/전체 실행 요약은 각각 `sample_benchmark.json`, `full_run_execution.json`에 있어.
- 전체 실행: worker 10, 유니버스 2,460 ticker, CONTROL/후보 signal trade 1,069/175; 벽시계 3,070.61초 (51.2분), CPU 3,404.38초, RSS peak 3,078.67 MB.
- Worker 오류 0건 (2,460/2,460 ticker outcome 완료); 포트폴리오 실행 오류 CONTROL/후보 0/0건.
- 계획/정책 봉인 commit: `adf4e7e69907cc9b13cafb941a5c3aecde924181`. 결과 경로: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/`.
- 원천 문서, 실행 코드, Repository V2 adjusted 가격 파일, rolling authority, exact KRX cap partitions 및 산출물 SHA-256은 `source_manifest.json`과 `artifact_hashes.json`에 기록했어.
