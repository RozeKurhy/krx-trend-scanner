# Pattern B + PROGRESSED 이전 WEAK 제외 P1 단순 백테스트 V01

판정: `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED`

## 기간 및 계약

- Window `P1`; calendar range 2014-01-01~2026-08-31; resolver 결과 2014-01-02~2026-08-31; execution support 2026-09-01.
- CONTROL은 `Pattern B DEPRESSED 신규 진입 + 진입일 Pattern A exact PROGRESSED`; TEST는 동일 조건에서 이전 authoritative Stage가 `WEAK`인 신규 진입만 제외했어. `UNAVAILABLE`은 허용했어.
- CONTROL/TEST를 P1 시작부터 각각 독립 replay했어. P1 시작 전 포지션 carry-in은 없고, TEST를 CONTROL 원장에서 사후 삭제해 만들지 않았어.
- P1 종료일 이후 신규 진입 체결은 막았어. 2026-09-01 support는 2026-08-31까지 확정된 exit 신호의 체결에만 썼어. 미청산은 2026-08-31 exact adjusted close로 평가했어.
- 비용: 매수/매도 수수료 0.015%, 매수/매도 슬리피지 0.10%, 실제 매도일·시장별 역사적 세금표. 핵심 성과 비교는 기존 simple strategy 계약대로 gross야.
- 동일 ISU 동시 보유 0, 부분체결은 사용하지 않았어. PIT universe·identity·permanent exclusion 및 completed monthly Pattern B 입력은 기존 계약을 유지했어.

## CONTROL / TEST 비교

| 시나리오 | P1 raw B 진입 | A PROGRESSED 통과 | WEAK 제외 | 체결/실현/미청산 | 미청산률 | 평균/중앙 gross | 승률 | PF | 기대값 | +20 / +50 / +100 | -20 / -30 / -50 | Deep 도달 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 19,371 | 803 | 0 | 798/715/83 | 10.40% | 12.01%/12.10% | 77.20% | 3.22 | 12.01% | 30.91%/6.15%/0.98% | 9.79%/6.99%/2.52% | 171 (21.43%) |
| TEST | 19,371 | 803 | 107 | 694/622/72 | 10.37% | 12.52%/12.25% | 78.94% | 3.57 | 12.52% | 31.35%/6.27%/0.96% | 9.00%/6.27%/2.25% | 134 (19.31%) |

평균·중앙 수익률은 실현 거래 gross 기준이야. MFE/MAE와 보유기간은 realized/open 체결 원장의 P1 경로 지표고, 비용 반영 전후 수익률은 `control_vs_test.csv`에 같이 있어.

## Pattern B DEEP 도달 cohort

| 시나리오 | 체결 | DEEP 도달 | 도달률 | DEEP 실현 승률 | 평균/중앙 gross | 평균/중앙 MAE | DEEP open |
|---|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 798 | 171 | 21.43% | 17.69% | -21.09%/-20.72% | -61.95%/-62.70% | 41 |
| TEST | 694 | 134 | 19.31% | 16.83% | -21.89%/-23.36% | -62.19%/-63.72% | 33 |

## 미청산 P1 cutoff 평가

| 시나리오 | 미청산 | exact 평가 | 미해결 | 평가 평균/중앙 gross | -30 이하 | -50 이하 | cutoff Pattern B 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| CONTROL | 83 | 67 | 16 | -30.19%/-26.25% | 30 (44.78%) | 24 (35.82%) | {"DEEP_DEPRESSED": 28, "DEPRESSED": 53, "OVERHEATED": 2} |
| TEST | 72 | 60 | 12 | -28.52%/-19.74% | 25 (41.67%) | 20 (33.33%) | {"DEEP_DEPRESSED": 23, "DEPRESSED": 47, "OVERHEATED": 2} |

## WEAK 제외 직접 효과

`weak_exclusion_direct_effect.csv`는 CONTROL에서 WEAK-origin으로 실제 체결된 거래, CONTROL 원장의 사후 삭제 참고값, 독립 TEST, TEST에서만 새로 생긴 entry key를 비교해. 승·패는 실현 gross 수익률 기준이고, 사후 삭제와 독립 TEST 차이를 마지막 행에 따로 계산했어.

| 비교군 | 후보/key | 체결/실현/open | 승/패 | 중앙 gross | 승률 | +50% | -30% | -50% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL_WEAK_ORIGIN_FILLED | 107 | 104/93/11 | 61/32 | 10.80% | 65.59% | 5 (5.38%) | 11 (11.83%) | 4 (4.30%) |
| CONTROL_SIMPLE_AFTER_THE_FACT_WEAK_DELETION | 696 | 694/622/72 | 491/131 | 12.25% | 78.94% | 39 (6.27%) | 39 (6.27%) | 14 (2.25%) |
| TEST_INDEPENDENT_REPLAY | 696 | 694/622/72 | 491/131 | 12.25% | 78.94% | 39 (6.27%) | 39 (6.27%) | 14 (2.25%) |
| TEST_NEW_ENTRY_KEYS_VS_CONTROL | 0 | 0/0/0 | 0/0 | — | — | 0 (—) | 0 (—) | 0 (—) |
| TEST_INDEPENDENT_MINUS_CONTROL_POSTHOC | 0 | 0/0/0 | 0/0 | 0.00% | 0.00% | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |

## P1 진입연도 비교

연도별 filled/realized/open과 중앙수익·승률·+50·-30·미청산률은 `annual_comparison.csv`에 기록했어. 2026년 진입은 기간 종료로 오른쪽 검열 영향이 있어.

## 사전 판정 규칙 적용

- float 비교 허용오차는 절대 0.1 percentage point야. TEST 품질 지표의 CONTROL 대비 변화(중앙 gross/승률/+50)는 {"median_gross_pct": 0.15328916597355757, "win_rate_pct": 1.736109549614369, "ge_50_rate_pct": 0.11625030917635382}.
- 핵심 위험 개선(control minus test: -30/-50/DEEP)은 {"le_30_rate_pct": 0.7229105299844854, "le_50_rate_pct": 0.266678658961617, "deep_arrival_rate_pct": 2.1202140798682585}. 개선 지표 3/3; 연도별 손실률 개선 관측 [2017, 2019, 2021, 2022, 2023, 2025].
- `IMPROVED` 조건의 품질 비악화=True, 위험 2개 이상 개선=True, 개선 분포 3개 이상 연도=True.
- 최종 판정 `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED`. cutoff open tail은 보조 지표로만 봤어.

## 검증

- P1 resolver exact: 2014-01-02~2026-08-31, support 2026-09-01; raw linkage mismatch 0; 미래 Pattern A 입력 0.
- TEST WEAK-origin 진입 통과 0; entry after P1 end 0; exact P1 cutoff/open evaluations 127/28; 동일 ISU overlap CONTROL/TEST 0/0.
- Repository V2 tickers 616; adjusted OHLC rows 1,693,937; silent inner drops 0; workers 10.
- lifecycle spot checks 30/30; focused tests, py_compile, git diff --check 실행. 전체 pytest는 실행하지 않았어.

## 최종 질문

1. tail risk: realized -30/-50 개선(control-test)은 `{"le_30": 0.7229105299844854, "le_50": 0.266678658961617}` pp, DEEP 도달률 개선은 `2.12` pp야. 사전 기준상 3개 중 3개가 0.1pp 이상 개선됐어.
2. median/win/+50 의미 있는 훼손 여부: `False` (0/3 지표가 0.1pp 초과 악화). TEST−CONTROL 변화는 `{"median_gross_pct": 0.15328916597355757, "win_rate_pct": 1.736109549614369, "ge_50_rate_pct": 0.11625030917635382}` pp야.
3. 독립 재생 뒤의 변화: TEST weak-origin 통과 `0`건, CONTROL weak-origin 실제 체결 `104`건. 사후 삭제 대비 TEST 독립 replay의 체결 수 차이는 `0`건이야. CONTROL weak-origin과 비-WEAK 사후삭제군의 손실률을 위 표에서 직접 비교했어.
4. 정식 개선안으로 다음 단계에 넘길 근거: `있어`. 이 결론은 사전 판정 규칙을 그대로 적용했어.
5. 판정: `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED`.

## 산출물

`control_vs_test.csv`, CONTROL/TEST trade·open ledger, `entry_filter_audit.csv`, `weak_exclusion_direct_effect.csv`, `deep_cohort_comparison.csv`, `annual_comparison.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.
