# Pattern B + PROGRESSED 이전 WEAK 제외 P3-1 단순 백테스트 V01

판정: `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED`

## 기간 및 계약

- Window `P3-1`; calendar range 2022-01-01~2025-05-31; resolver 결과 2022-01-03~2025-05-30; execution support 2025-06-02.
- CONTROL은 `Pattern B DEPRESSED 신규 진입 + 진입일 Pattern A exact PROGRESSED`; TEST는 동일 조건에서 이전 authoritative Stage가 `WEAK`인 신규 진입만 제외했어. `UNAVAILABLE`은 허용했어.
- CONTROL/TEST를 P3-1 시작부터 각각 독립 replay했어. 시작 전 포지션 carry-in은 없고, TEST를 CONTROL 원장에서 사후 삭제해 만들지 않았어.
- P3-1 종료일 이후 신규 진입 체결은 막았어. 2025-06-02 support는 2025-05-30까지 확정된 exit 신호의 체결에만 썼어. 미청산은 2025-05-30 exact adjusted close로 평가했어.
- 비용: 매수/매도 수수료 0.015%, 매수/매도 슬리피지 0.10%, 실제 매도일·시장별 역사적 세금표. 핵심 성과 비교는 기존 simple strategy 계약대로 gross야.
- 동일 ISU 동시 보유 0, 부분체결은 사용하지 않았어. PIT universe·identity·permanent exclusion 및 completed monthly Pattern B 입력은 기존 계약을 유지했어.

## CONTROL / TEST 비교

| 시나리오 | P3-1 raw B 진입 | A PROGRESSED 통과 | WEAK 제외 | 체결/실현/미청산 | 미청산률 | 평균 gross | 승률 | 중앙 gross | PF | 기대값 | +20 / +50 / +100 | -20 / -30 / -50 | Deep 도달 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 7,047 | 282 | 0 | 279/215/64 | 22.94% | 15.52% | 82.79% | 14.04% | 5.33 | 15.52% | 33.95%/7.44%/0.93% | 7.44%/5.12%/0.00% | 74 (26.52%) |
| TEST | 7,047 | 282 | 45 | 236/186/50 | 21.19% | 15.50% | 83.33% | 13.69% | 5.62 | 15.50% | 33.33%/7.53%/1.08% | 6.99%/4.84%/0.00% | 60 (25.42%) |

평균·중앙 수익률은 실현 거래 gross 기준이야. MFE/MAE와 보유기간은 realized/open 체결 원장의 window 경로 지표고, 비용 반영 전후 수익률은 `control_vs_test.csv`에 같이 있어.

## Pattern B DEEP 도달 cohort

| 시나리오 | 체결 | DEEP 도달 | 도달률 | DEEP 실현 승률 | 평균/중앙 gross | 평균/중앙 MAE | DEEP open |
|---|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 279 | 74 | 26.52% | 22.86% | -13.10%/-18.71% | -54.41%/-55.29% | 39 |
| TEST | 236 | 60 | 25.42% | 24.14% | -14.13%/-18.71% | -54.01%/-56.51% | 31 |

## 미청산 P3-1 cutoff 평가

| 시나리오 | 미청산 | exact 평가 | 미해결 | 평가 평균/중앙 gross | -30 이하 | -50 이하 | cutoff Pattern B 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| CONTROL | 64 | 59 | 5 | -35.87%/-42.93% | 37 (62.71%) | 16 (27.12%) | {"DEEP_DEPRESSED": 24, "DEPRESSED": 40} |
| TEST | 50 | 47 | 3 | -36.49%/-43.63% | 30 (63.83%) | 14 (29.79%) | {"DEEP_DEPRESSED": 19, "DEPRESSED": 31} |

## WEAK 제외 직접 효과

`weak_exclusion_direct_effect.csv`는 CONTROL에서 WEAK-origin으로 실제 체결된 거래, CONTROL 원장의 사후 삭제 참고값, 독립 TEST, TEST에서만 새로 생긴 entry key를 비교해. 승·패는 실현 gross 수익률 기준이고, 사후 삭제와 독립 TEST 차이를 마지막 행에 따로 계산했어.

| 비교군 | 후보/key | 체결/실현/open | 승/패 | 평균 gross | 중앙 gross | 승률 | +50% | -30% | -50% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL_WEAK_ORIGIN_FILLED | 45 | 43/29/14 | 23/6 | 15.64% | 16.59% | 79.31% | 2 (6.90%) | 2 (6.90%) | 0 (0.00%) |
| CONTROL_SIMPLE_AFTER_THE_FACT_WEAK_DELETION | 237 | 236/186/50 | 155/31 | 15.50% | 13.69% | 83.33% | 14 (7.53%) | 9 (4.84%) | 0 (0.00%) |
| TEST_INDEPENDENT_REPLAY | 237 | 236/186/50 | 155/31 | 15.50% | 13.69% | 83.33% | 14 (7.53%) | 9 (4.84%) | 0 (0.00%) |
| TEST_NEW_ENTRY_KEYS_VS_CONTROL | 0 | 0/0/0 | 0/0 | — | — | — | 0 (—) | 0 (—) | 0 (—) |
| TEST_INDEPENDENT_MINUS_CONTROL_POSTHOC | 0 | 0/0/0 | 0/0 | 0.00% | 0.00% | 0.00% | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |

## P3-1 진입연도 비교

연도별 filled/realized/open과 중앙수익·승률·+50·-30·미청산률은 `annual_comparison.csv`에 기록했어. 2025년 진입은 기간 종료로 오른쪽 검열 영향이 있어.

## 사전 판정 규칙 적용

- float 비교 허용오차는 절대 0.1 percentage point야. TEST 품질 지표의 CONTROL 대비 변화(중앙 gross/승률/+50)는 {"median_gross_pct": -0.34638450927097075, "win_rate_pct": 0.5426356589147474, "ge_50_rate_pct": 0.08502125531382898}.
- 핵심 위험 개선(control minus test: -30/-50/DEEP)은 {"le_30_rate_pct": 0.2775693923480871, "le_50_rate_pct": 0.0, "deep_arrival_rate_pct": 1.0995686774801037}. 개선 지표 2/3; 연도별 손실률 개선 관측 [2022].
- `IMPROVED` 조건의 품질 비악화=False, 위험 2개 이상 개선=True, 개선 분포 3개 이상 연도=False.
- 최종 판정 `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED`. cutoff open tail은 보조 지표로만 봤어.

## 검증

- standard resolver exact: 2022-01-03~2025-05-30, support 2025-06-02; raw linkage mismatch 0; 미래 Pattern A 입력 0.
- TEST WEAK-origin 진입 통과 0; entry after window end 0; exact cutoff/open evaluations 106/8; 동일 ISU overlap CONTROL/TEST 0/0.
- Repository V2 tickers 247; adjusted OHLC rows 201,719; silent inner drops 0; workers 10.
- lifecycle spot checks 30/30; focused tests, py_compile, git diff --check 실행. 전체 pytest는 실행하지 않았어.

## 최종 질문

1. tail risk: realized -30/-50 개선(control-test)은 `{"le_30": 0.2775693923480871, "le_50": 0.0}` pp, DEEP 도달률 개선은 `1.10` pp야. 사전 기준상 3개 중 2개가 0.1pp 이상 개선됐어.
2. median/win/+50 의미 있는 훼손 여부: `True` (1/3 지표가 0.1pp 초과 악화). TEST−CONTROL 변화는 `{"median_gross_pct": -0.34638450927097075, "win_rate_pct": 0.5426356589147474, "ge_50_rate_pct": 0.08502125531382898}` pp야.
3. 독립 재생 뒤의 변화: TEST weak-origin 통과 `0`건, CONTROL weak-origin 실제 체결 `43`건. 사후 삭제 대비 TEST 독립 replay의 체결 수 차이는 `0`건이야. CONTROL weak-origin과 비-WEAK 사후삭제군의 손실률을 위 표에서 직접 비교했어.
4. 다음 단계 연구 근거: `아직 충분하지 않아`. 이 결론은 P1과 같은 사전 판정 규칙을 그대로 적용했어.
5. 판정: `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED`.

## 산출물

`control_vs_test.csv`, CONTROL/TEST trade·open ledger, `entry_filter_audit.csv`, `weak_exclusion_direct_effect.csv`, `deep_cohort_comparison.csv`, `annual_comparison.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.
