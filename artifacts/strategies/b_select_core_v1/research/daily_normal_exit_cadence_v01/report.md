# B Select Core V1 — 월말 vs 일별 NORMAL 청산 cadence 연구 V01

실행 상태: **PASS**

## 비교 정의

- CONTROL은 매월 마지막 exact KRX 거래일에 Pattern B `NORMAL`을 확인하고, 다음 exact KRX 세션부터 유효한 Repository V2 시가가 처음 확인되는 시점에 청산해.
- TEST는 보유 중 모든 exact KRX 세션의 close 기준 Pattern B `NORMAL`을 확인하고, 다음 exact KRX 세션부터 유효한 Repository V2 시가가 처음 확인되는 시점에 청산해.
- ENTRY는 해시 검증된 기존 후보 원장의 월말 신호·다음 exact KRX 세션을 양쪽에서 그대로 사용해.
- Pattern B V01 feature contract와 sealed State Rule V02, Repository V2, PIT COMMON identity, 최신 승인 영구 제외, 200M 초기자본, 5M 종목 예산, 현금·수수료·슬리피지 계약을 양쪽에 동일 적용했어. 공식 portfolio 지표에는 매도세금을 넣지 않았어.
- 월별 후보 원장의 종목·신호일·실행일은 고정했어. 저장된 과거 진입가는 조정가격 기준 차이를 확인하기 위해 보존하고, 두 시나리오 모두 현재 Repository V2에서 체결 가능한 해당 시가를 연구용 진입가로 사용했어.
- 바뀐 변수는 NORMAL 확인 cadence 하나야. 공식 production/history와 기존 5-window 파일은 수정하지 않았어.
- 일별 evaluator는 완료 MonthEnd/W-FRI bar만 보므로 상태 갱신 경계와 entry execution date에서 평가했어. 월봉/주봉 경계 사이 상태가 동일한지 250개 직접 as-of 대조를 수행했어.

## 5-window 비교

| Window | Scenario | Filled | Closed | Open | Portfolio equity | Return | CAGR | MDD | MDD type / coverage | Cash skip | Avg utilization | Gross win / median | Costed pre-tax median | Mean / median hold |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---|
| P1 | CONTROL_MONTH_END | 483 | 435 | 48 | 402,693,097 KRW | 101.35% | 5.68% | -12.53% | OBSERVED_BELOW_90_COVERAGE / 52.62% | 3.52% | 23.72% | 79.77% / 12.60% | 12.34% | 142.3 / 43.0 |
| P1 | TEST_DAILY | 483 | 446 | 37 | 433,273,696 KRW | 116.64% | 6.30% | -11.20% | OBSERVED_BELOW_90_COVERAGE / 53.20% | 1.24% | 19.50% | 83.41% / 12.25% | 12.00% | 120.1 / 24.0 |
| P2-1 | CONTROL_MONTH_END | 215 | 176 | 39 | 254,893,158 KRW | 27.45% | 5.67% | -15.36% | OBSERVED_BELOW_90_COVERAGE / 63.22% | 10.23% | 36.10% | 80.11% / 13.82% | 13.56% | 159.3 / 44.0 |
| P2-1 | TEST_DAILY | 215 | 179 | 36 | 275,624,833 KRW | 37.81% | 7.56% | -14.65% | OBSERVED_BELOW_90_COVERAGE / 63.31% | 6.05% | 30.14% | 87.71% / 14.27% | 14.00% | 142.6 / 42.0 |
| P2-2 | CONTROL_MONTH_END | 319 | 271 | 48 | 256,764,725 KRW | 28.38% | 4.52% | -17.46% | OBSERVED_BELOW_90_COVERAGE / 64.96% | 20.06% | 37.38% | 79.34% / 13.31% | 13.05% | 143.3 / 43.0 |
| P2-2 | TEST_DAILY | 319 | 282 | 37 | 309,938,110 KRW | 54.97% | 8.06% | -14.65% | OBSERVED_BELOW_90_COVERAGE / 65.03% | 11.91% | 30.13% | 84.75% / 14.22% | 13.96% | 124.0 / 30.0 |
| P3-1 | CONTROL_MONTH_END | 178 | 142 | 36 | 238,754,825 KRW | 19.38% | 5.34% | -15.35% | OBSERVED_BELOW_90_COVERAGE / 52.40% | 13.48% | 47.75% | 81.69% / 15.28% | 15.02% | 167.2 / 62.0 |
| P3-1 | TEST_DAILY | 178 | 145 | 33 | 242,975,912 KRW | 21.49% | 5.89% | -14.71% | OBSERVED_BELOW_90_COVERAGE / 52.52% | 12.36% | 41.62% | 85.52% / 14.91% | 14.65% | 150.0 / 43.0 |
| P3-2 | CONTROL_MONTH_END | 282 | 235 | 47 | 240,035,533 KRW | 20.02% | 4.00% | -17.66% | OBSERVED_BELOW_90_COVERAGE / 57.42% | 24.47% | 46.18% | 80.85% / 14.27% | 14.00% | 144.7 / 43.0 |
| P3-2 | TEST_DAILY | 282 | 246 | 36 | 271,782,896 KRW | 35.89% | 6.81% | -14.71% | OBSERVED_BELOW_90_COVERAGE / 57.51% | 19.15% | 38.42% | 83.74% / 14.59% | 14.32% | 124.7 / 42.0 |

## Cadence effect

| Window | Daily earlier exits | Median sessions advanced | Mean costed trade-return Δ | Portfolio return Δ | MDD Δ | Entry key parity | Frozen monthly exit-signal parity |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 240 | 5.0 | -0.14pp | 15.29pp | 1.33pp | True | 481/483 |
| P2-1 | 91 | 2.0 | 1.36pp | 10.37pp | 0.72pp | True | 215/215 |
| P2-2 | 148 | 1.0 | 1.55pp | 26.59pp | 2.82pp | True | 318/319 |
| P3-1 | 63 | 0.0 | -0.43pp | 2.11pp | 0.65pp | True | 178/178 |
| P3-2 | 119 | 0.0 | 0.53pp | 15.87pp | 2.95pp | True | 281/282 |

## 검증과 해석 경계

- 첫 연구의 verdict token은 `B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS`이고, 해당 연구에서 7개 discrepancy의 현재 영구 제외 적용 후 5-window 공식 event exposure가 0임을 확인했어.
- exact-session entry/exit 실행 위반: 0; 현재 Repository V2 진입가로 재기준화된 고정 원장 행: 6; 동일 ISU 겹침: 0; V2 silent inner drop: 0; portfolio cash conservation 실패: 0; cost audit mismatch: 0.
- 일별 상태와 경계 업데이트 구현의 직접 중간일 검수: 250/250.
- CONTROL 월말 청산 원장과 현행 Repository V2에서 재구성한 월말 NORMAL 신호가 다르면 비교표는 동일 현행 원천에서 재구성한 CONTROL/TEST 결과야. 그 경우 저장된 공식 지표와 절대 수치는 직접 동등 비교하지 않아.
- 이 cadence 연구는 기존 공식 채택 기준을 다시 심사하거나 B Select 채택 상태를 변경하지 않아. Portfolio 결과는 연구용 동시비교이며 production 적용 승인이 아니야.

## 산출물

`summary.json`, `metadata.json`, `window_comparison.csv`, `trade_comparison.csv`, `state_observation_audit.csv`, `daily_state_piecewise_spot_checks.csv`; 각 기간별 CONTROL/TEST 거래원장, 포트폴리오 이벤트, 일별 equity 및 execution audit.
