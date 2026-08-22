README.md

# Run 1 Diagnostic Evidence (pre-comparator-fix)

이 폴더의 3개 JSON은 BACKTEST_PERFORMANCE_ENGINEERING_V01의 **1차 Full
Universe Run**(전체 2,506종목, 최적화 엔진) 결과다. 이 run 자체의 계산은
정확했다 — 아래 값이 실측 증거다.

- Baseline: golden 845 / optimized 845 (trade count 정확 일치)
- Julia: golden 687 / optimized 687 (trade count 정확 일치)
- `baseline`/`julia`의 `metrics_diff`, `loss_guard_cohort_diff`,
  `proxy_validation_diff` 전부 빈 배열 `[]` — 집계 지표(평균/중앙값/분포/
  loss guard cohort/proxy validation summary) **완전 일치**
- `runtime_comparison.json`: 전체 82.99분(4979.56초), historical 330분
  대비 3.98배. Primary 4855.67초 vs Sensitivity 91.1초 — warm cache 재사용
  효과 실측 확인.

**단, `exact_trade_identity`가 `false`로 찍혀 있고 `full_parity_summary.json`에
필드 단위 mismatch(baseline 2001건, julia 3779건)가 표시되어 있다.** 이건
실제 계산 차이가 아니라 **비교 로직(comparator) 버그**였다: golden CSV는
디스크 CSV round-trip을 거친 값인데, 이 run 당시의 optimized 값은 메모리
DataFrame을 CSV round-trip 없이 바로 문자열 비교해서, float 표현
(`1083419202799.9999` vs `1083419202800.0`)과 `None`/`NaN` 표현 차이가
false mismatch로 잡혔다. 표준 Python으로 직접 재현해 확인했고, 근본 수정을
`src/trend_scanner/backtest/parity.py`(golden/optimized 양쪽 모두 실제
디스크 CSV를 통해 비교)에 반영했다.

이 폴더는 **그 진단 과정의 증거**로 보존한다(현재 상태를 나타내지 않음).
comparator 수정 후 최종 Full Run은 아직 재실행 전이며, 재실행 후 진짜
`full_parity_summary.json`은 `artifacts/performance/backtest_engine_v01/`
루트에 새로 생성된다.
