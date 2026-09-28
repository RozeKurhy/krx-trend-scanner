# Pattern B E/T PROGRESSED Candidate V02 공식 포트폴리오 심사

최종 판정: **HOLD**

- 후보 규칙은 V1 동결 조건을 유지했다.
- 각 window의 전체 allowed signal stream을 chronological portfolio state에 공급하고, 현재 보유 상태와 가용 현금으로 신호별 체결 가능성을 새로 결정했다.
- 매수·매도 수수료 0.015%, 양방향 슬리피지 0.1%를 적용했다. 거래세/매도세는 공식 cash path와 모든 공식 지표에서 제외했다.
- 현금 부족은 진단값이며 Gate가 아니다.

## 5-window 결과

| Window | Ending Equity KRW | Profit KRW | Total Return | CAGR | MDD | Type / coverage | Cash shortage rate (reference) | Turnover | Trades / closed | Positive rate / median return | A | B | C | D | E |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|---|---|---|---|
| P1 | UNRESOLVED | UNRESOLVED | UNRESOLVED | UNRESOLVED | -8.02% | OBSERVED_BELOW_90_COVERAGE / 21.69% | 4.96% | 26.85x | 537 / 480 | 78.54% / +11.48% | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-1 | UNRESOLVED | UNRESOLVED | UNRESOLVED | UNRESOLVED | -14.80% | OBSERVED_BELOW_90_COVERAGE / 27.63% | 13.79% | 9.59x | 200 / 158 | 79.11% / +12.61% | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-2 | UNRESOLVED | UNRESOLVED | UNRESOLVED | UNRESOLVED | -14.80% | OBSERVED_BELOW_90_COVERAGE / 21.56% | 23.89% | 12.53x | 258 / 216 | 76.39% / +10.83% | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED |
| P3-1 | UNRESOLVED | UNRESOLVED | UNRESOLVED | UNRESOLVED | -3.63% | OBSERVED_BELOW_90_COVERAGE / 6.35% | 18.42% | 7.27x | 155 / 118 | 80.51% / +13.66% | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED |
| P3-2 | UNRESOLVED | UNRESOLVED | UNRESOLVED | UNRESOLVED | -3.63% | OBSERVED_BELOW_90_COVERAGE / 4.65% | 29.29% | 10.09x | 210 / 173 | 77.46% / +11.26% | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED |

## Trade tail counts

| Window | +30 | +50 | +100 | -30 | -40 | -50 | -60 |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 84 | 28 | 6 | 29 | 16 | 12 | 7 |
| P2-1 | 35 | 13 | 4 | 7 | 1 | 0 | 0 |
| P2-2 | 42 | 16 | 4 | 13 | 5 | 4 | 2 |
| P3-1 | 28 | 10 | 2 | 7 | 1 | 0 | 0 |
| P3-2 | 35 | 13 | 2 | 11 | 3 | 2 | 1 |

Relative D 값은 저장된 MDD를 이용한 수치 비교다. 다섯 기간 모두 candidate coverage가 90% 미만이므로 Relative D PASS는 공식 Gate D를 통과시키지 않으며, 공식 D는 `CHECK_REQUIRED`다.
## Gate 판정

- Gate A: `PASS`
- Gate B: `PASS`
- Gate C: `CHECK_REQUIRED`
- Gate D: `CHECK_REQUIRED`
- Gate E: `CHECK_REQUIRED`

## V2 comparison

| Window | Candidate MDD | V2 MDD | Deterioration pp | Relative D | Candidate Return | V2 Return | Candidate CAGR | V2 CAGR |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| P1 | -8.02% (OBSERVED_BELOW_90_COVERAGE) | -52.25% (OBSERVED) | -44.23 | PASS | UNRESOLVED | 108.39% | UNRESOLVED | 5.97% |
| P2-1 | -14.80% (OBSERVED_BELOW_90_COVERAGE) | -32.71% (OBSERVED) | -17.91 | PASS | UNRESOLVED | 57.33% | UNRESOLVED | 10.85% |
| P2-2 | -14.80% (OBSERVED_BELOW_90_COVERAGE) | -34.54% (OBSERVED) | -19.73 | PASS | UNRESOLVED | 95.85% | UNRESOLVED | 12.62% |
| P3-1 | -3.63% (OBSERVED_BELOW_90_COVERAGE) | -37.34% (EXACT) | -33.72 | PASS | UNRESOLVED | 22.93% | UNRESOLVED | 6.25% |
| P3-2 | -3.63% (OBSERVED_BELOW_90_COVERAGE) | -38.46% (EXACT) | -34.84 | PASS | UNRESOLVED | 49.54% | UNRESOLVED | 9.02% |

## 데이터 gap / 제한

미해결 valuation identity 그룹: 140; 미해결 mark 합계: 24681.
Identity별 window·mark/date·coverage 영향은 `unresolved_valuation_summary.csv`에 있다. 추가 영구 제외는 적용하지 않았다.

대표 미해결 원장에는 P3-2 `181340`에서 1,079일의 정확한 종가 평가 누락, P1 `023430`에서 2,301일 누락이 기록되어 있다. 이러한 미해결 보유 평가 때문에 전체 portfolio equity를 확정할 수 없는 날이 다수 발생했고, 종료 equity도 `UNRESOLVED`다. 가격 대체나 추가 permanent exclusion은 적용하지 않았다. 상세 identity/date별 내역은 `unresolved_valuation_summary.csv` 및 window별 `valuation_audit.csv`에 있다.

## 기존 결과와 범위

V01 산출물과 당시 HOLD 판정은 역사 기록으로 그대로 보존했다. 이번 V02는 최신 A~E 기준에 따른 독립 portfolio-aware replay다.
A FAST Core V2의 기본 전략 지위는 이번 판정으로 바뀌지 않는다.

## 산출물

`summary.json`, `execution_contract.json`, `metadata.json`, `source_hashes.json`, `five_window_summary.csv`, `official_adoption_gates.csv`, `v2_comparison.csv`, `portfolio_metrics.csv`, `trade_distribution.csv`, `cash_shortage_diagnostics.csv`, `valuation_coverage.csv`, `unresolved_valuation_summary.csv`, window별 daily equity 및 portfolio event/audit 파일.
