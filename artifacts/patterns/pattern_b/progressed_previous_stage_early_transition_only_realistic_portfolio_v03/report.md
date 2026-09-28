# Pattern B E/T PROGRESSED Candidate V02 공식 포트폴리오 심사

최종 판정: **HOLD**

- 후보 규칙은 V1 동결 조건을 유지했다.
- 각 window의 전체 allowed signal stream을 chronological portfolio state에 공급하고, 현재 보유 상태와 가용 현금으로 신호별 체결 가능성을 새로 결정했다.
- 매수·매도 수수료 0.015%, 양방향 슬리피지 0.1%를 적용했다. 거래세/매도세는 공식 cash path와 모든 공식 지표에서 제외했다.
- 현금 부족은 진단값이며 Gate가 아니다.

## 5-window 결과

| Window | Profit KRW | Total Return | CAGR | MDD | Type / coverage | Cash skip (reference) | Turnover | Trades / closed | Positive / median | A | B | C | D | E |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|---|---|---|---|
| P1 | 193,558,408.15 | 96.78% | 5.49% | -13.41% | OBSERVED_BELOW_90_COVERAGE / 52.62% | 3.93% | 23.33x | 464.00 / 417.00 | 79.14% / 12.13% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-1 | 54,892,899.16 | 27.45% | 5.67% | -15.36% | OBSERVED_BELOW_90_COVERAGE / 63.22% | 10.23% | 9.34x | 193.00 / 157.00 | 78.34% / 12.25% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-2 | 53,821,074.97 | 26.91% | 4.31% | -18.30% | OBSERVED_BELOW_90_COVERAGE / 64.96% | 20.38% | 12.38x | 254.00 / 216.00 | 75.93% / 11.04% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P3-1 | 38,754,565.94 | 19.38% | 5.34% | -15.35% | OBSERVED_BELOW_90_COVERAGE / 52.40% | 13.48% | 7.34x | 154.00 / 121.00 | 80.17% / 14.00% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P3-2 | 36,323,528.24 | 18.16% | 3.65% | -18.50% | OBSERVED_BELOW_90_COVERAGE / 57.42% | 24.82% | 10.23x | 212.00 / 176.00 | 77.27% / 11.69% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |

## Gate 판정

- Gate A: `PASS`
- Gate B: `PASS`
- Gate C: `PASS`
- Gate D: `CHECK_REQUIRED`
- Gate E: `CHECK_REQUIRED`

## V2 comparison

| Window | Candidate MDD | V2 MDD | Deterioration pp | Relative D | Candidate Return | V2 Return | Candidate CAGR | V2 CAGR |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| P1 | -13.41% (OBSERVED_BELOW_90_COVERAGE) | -52.25% (OBSERVED) | -38.84 | PASS | 96.78% | 108.39% | 5.49% | 5.97% |
| P2-1 | -15.36% (OBSERVED_BELOW_90_COVERAGE) | -32.71% (OBSERVED) | -17.34 | PASS | 27.45% | 57.33% | 5.67% | 10.85% |
| P2-2 | -18.30% (OBSERVED_BELOW_90_COVERAGE) | -34.54% (OBSERVED) | -16.24 | PASS | 26.91% | 95.85% | 4.31% | 12.62% |
| P3-1 | -15.35% (OBSERVED_BELOW_90_COVERAGE) | -37.34% (EXACT) | -21.99 | PASS | 19.38% | 22.93% | 5.34% | 6.25% |
| P3-2 | -18.50% (OBSERVED_BELOW_90_COVERAGE) | -38.46% (EXACT) | -19.96 | PASS | 18.16% | 49.54% | 3.65% | 9.02% |

## 데이터 gap / 제한

미해결 valuation identity 그룹: 57; 미해결 mark 합계: 4235.
Identity별 window·mark/date·coverage 영향은 `unresolved_valuation_summary.csv`에 있다. 추가 영구 제외는 적용하지 않았다.

## 기존 결과와 범위

V01 산출물과 당시 HOLD 판정은 역사 기록으로 그대로 보존했다. 이번 V02는 최신 A~E 기준에 따른 독립 portfolio-aware replay다.
A FAST Core V2의 기본 전략 지위는 이번 판정으로 바뀌지 않는다.

## 산출물

`summary.json`, `execution_contract.json`, `metadata.json`, `source_hashes.json`, `five_window_summary.csv`, `official_adoption_gates.csv`, `v2_comparison.csv`, `portfolio_metrics.csv`, `trade_distribution.csv`, `cash_shortage_diagnostics.csv`, `valuation_coverage.csv`, `unresolved_valuation_summary.csv`, window별 daily equity 및 portfolio event/audit 파일.
