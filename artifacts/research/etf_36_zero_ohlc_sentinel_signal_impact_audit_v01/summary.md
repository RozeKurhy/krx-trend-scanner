# ETF-36 Zero-OHLC Sentinel Signal Impact Audit V01

Verdict: ETF_36_ZERO_OHLC_SENTINEL_SIGNAL_IMPACT_AUDIT_CHECK_REQUIRED

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 반사실 재계산으로 확정된 수정 거래 없음; 실제 변경 수는 미판정 |
| MAJOR | 12 | 신호 경로에 직접 노출된 기존 거래 ID 수 (변경 확정 수가 아닌 위험 노출 수) |
| MINOR | 2863 | 신호 결정에 쓰이지 않는 non-finite 진단 feature 평가 건수 |

## 판정 근거

원시 sentinel 78행 / 10개 ETF가 completed weekly/monthly bars로 집계됐어. 전체 5-window 백테스트는 재실행하지 않았고, 영향 가능 기간의 10개 ETF evaluator만 2,172회 평가했어. 거래 원장은 기존 기록 그대로 읽어 대조했어.

- sentinel_affected_evaluation_count: 1,736 (ticker × window × strategy × evaluation date)
- 고유 ticker × evaluation date: 828
- sentinel_affected_entry_candidate_count: 53 (고정 entry gate 및 실제 PIT 자격 통과; position 상태는 제외)
- entry contract만 통과한 후보 평가: 117
- sentinel_affected_entry_signal_count: 12 (기존 ledger signal date와 입력 노출 날짜 일치)
- sentinel_affected_trade_count: 12개 trade identity 직접 노출. 실제로 바뀐 identity 수는 반사실 평가 없이는 확정할 수 없어.
- 진단값: distance-from-low 계열 2,826건은 +Inf, pivot_low_slope 37건은 NaN. 이 진단 feature들은 entry contract에 사용되지 않아.

A FAST는 월봉 range_position_24m, 주봉 higher_weekly_low_count_13w, 일봉 recent_5d_max_gap_abs_pct / atr_14_pct를 entry gate에서 읽어. Pattern A entry stage와 score도 36개월 저점 기반 range_position / range_36m을 읽고, ETF-36 자격 필터는 최근 20회 volume 평균을 사용해. 영향 경로가 진단 전용 feature에 한정되지 않아.

### 직접 노출된 기존 신호/거래

| 종목 | Window | Strategy | Evaluation / signal date | 노출 feature | 추정 at-risk trade |
|---|---|---|---|---|---:|
| 139230 | P1 | JULIA_STRATEGY_V00 | 2017-03-17 | fast.range_position_24m|pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 139230 | P1 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2017-03-17 | fast.range_position_24m|pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 157490 | P1 | JULIA_STRATEGY_V00 | 2019-09-06 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 157490 | P1 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2019-09-06 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P1 | JULIA_STRATEGY_V00 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P1 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P2-1 | JULIA_STRATEGY_V00 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P2-1 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P2-2 | JULIA_STRATEGY_V00 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 160580 | P2-2 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2021-01-29 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 228800 | P1 | JULIA_STRATEGY_V00 | 2019-01-11 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |
| 228800 | P1 | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2019-01-11 | pattern_a.range_position_36m|pattern_a.range_36m | 1 |

위 행은 sentinel이 포함된 입력을 소비한 기존 ledger 진입 신호의 노출 목록이야. 정제된 데이터에서 해당 거래가 실제로 달라졌다고 단정하지는 않아. 무거래 행의 canonical 대체 OHLCV 규칙이 정해지지 않았고 원시 행 변경 및 자동 재실행이 금지돼 있어, verdict는 CHECK_REQUIRED야. 기존 단순 백테스트를 certified PASS로 승격할 수 없어.

### Feature exposure 요약

| Ticker | Feature | Role | Affected evaluation dates | First | Last |
|---|---|---|---:|---|---|
| 133690 | fast.atr_14_pct | A FAST daily risk entry gate | 2 | 2014-08-22 | 2014-08-29 |
| 133690 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 11 | 2014-08-22 | 2014-11-07 |
| 133690 | fast.range_position_24m | A FAST monthly permission gate | 33 | 2016-01-08 | 2016-08-26 |
| 133690 | pattern_a.range_36m | Pattern A score availability and score input | 32 | 2017-01-06 | 2017-08-25 |
| 133690 | pattern_a.range_position_36m | Pattern A stage entry gate | 32 | 2017-01-06 | 2017-08-25 |
| 133690 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 4 | 2014-08-22 | 2014-09-12 |
| 139230 | fast.atr_14_pct | A FAST daily risk entry gate | 21 | 2014-01-24 | 2015-06-19 |
| 139230 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 44 | 2014-03-28 | 2015-08-28 |
| 139230 | fast.range_position_24m | A FAST monthly permission gate | 72 | 2016-01-08 | 2017-06-23 |
| 139230 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 11 | 2014-01-17 | 2015-06-05 |
| 139230 | pattern_a.range_36m | Pattern A score availability and score input | 72 | 2017-01-06 | 2018-06-22 |
| 139230 | pattern_a.range_position_36m | Pattern A stage entry gate | 72 | 2017-01-06 | 2018-06-22 |
| 139230 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 27 | 2014-02-07 | 2015-06-26 |
| 140700 | fast.atr_14_pct | A FAST daily risk entry gate | 3 | 2015-11-13 | 2015-11-27 |
| 140700 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 11 | 2015-11-13 | 2016-02-05 |
| 140700 | fast.range_position_24m | A FAST monthly permission gate | 93 | 2016-01-08 | 2017-11-24 |
| 140700 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 1 | 2015-11-13 | 2015-11-13 |
| 140700 | pattern_a.range_36m | Pattern A score availability and score input | 94 | 2017-01-06 | 2018-11-23 |
| 140700 | pattern_a.range_position_36m | Pattern A stage entry gate | 94 | 2017-01-06 | 2018-11-23 |
| 140700 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 4 | 2015-11-13 | 2015-12-04 |
| 157490 | fast.atr_14_pct | A FAST daily risk entry gate | 17 | 2014-03-14 | 2016-12-23 |
| 157490 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 47 | 2014-03-28 | 2017-03-03 |
| 157490 | fast.range_position_24m | A FAST monthly permission gate | 139 | 2016-01-08 | 2018-12-21 |
| 157490 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 6 | 2014-03-14 | 2016-12-09 |
| 157490 | pattern_a.range_36m | Pattern A score availability and score input | 149 | 2017-01-06 | 2019-12-27 |
| 157490 | pattern_a.range_position_36m | Pattern A stage entry gate | 149 | 2017-01-06 | 2019-12-27 |
| 157490 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 22 | 2014-03-14 | 2017-01-06 |
| 160580 | fast.atr_14_pct | A FAST daily risk entry gate | 32 | 2014-01-24 | 2018-06-15 |
| 160580 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 60 | 2014-03-28 | 2018-08-24 |
| 160580 | fast.range_position_24m | A FAST monthly permission gate | 152 | 2016-01-08 | 2020-05-22 |
| 160580 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 16 | 2014-01-10 | 2018-06-01 |
| 160580 | pattern_a.range_36m | Pattern A score availability and score input | 200 | 2017-01-06 | 2021-05-28 |
| 160580 | pattern_a.range_position_36m | Pattern A stage entry gate | 200 | 2017-01-06 | 2021-05-28 |
| 160580 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 40 | 2014-02-07 | 2018-06-29 |
| 195980 | fast.atr_14_pct | A FAST daily risk entry gate | 3 | 2014-11-21 | 2014-12-05 |
| 195980 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 13 | 2014-11-21 | 2015-02-13 |
| 195980 | fast.range_position_24m | A FAST monthly permission gate | 29 | 2016-04-29 | 2016-11-25 |
| 195980 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 1 | 2014-11-21 | 2014-11-21 |
| 195980 | pattern_a.range_36m | Pattern A score availability and score input | 29 | 2017-04-28 | 2017-11-24 |
| 195980 | pattern_a.range_position_36m | Pattern A stage entry gate | 29 | 2017-04-28 | 2017-11-24 |
| 195980 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 4 | 2014-11-21 | 2014-12-12 |
| 228800 | fast.atr_14_pct | A FAST daily risk entry gate | 15 | 2015-12-04 | 2016-12-23 |
| 228800 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 41 | 2016-01-08 | 2017-03-03 |
| 228800 | fast.range_position_24m | A FAST monthly permission gate | 62 | 2017-09-29 | 2018-12-21 |
| 228800 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 7 | 2015-12-04 | 2016-12-09 |
| 228800 | pattern_a.range_36m | Pattern A score availability and score input | 64 | 2018-09-28 | 2019-12-27 |
| 228800 | pattern_a.range_position_36m | Pattern A stage entry gate | 64 | 2018-09-28 | 2019-12-27 |
| 228800 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 19 | 2015-12-04 | 2016-12-23 |
| 228810 | fast.atr_14_pct | A FAST daily risk entry gate | 25 | 2015-11-06 | 2017-09-29 |
| 228810 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 66 | 2016-01-08 | 2017-12-08 |
| 228810 | fast.range_position_24m | A FAST monthly permission gate | 100 | 2017-09-29 | 2019-09-27 |
| 228810 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 9 | 2015-11-06 | 2017-09-15 |
| 228810 | pattern_a.range_36m | Pattern A score availability and score input | 101 | 2018-09-28 | 2020-09-25 |
| 228810 | pattern_a.range_position_36m | Pattern A stage entry gate | 101 | 2018-09-28 | 2020-09-25 |
| 228810 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 35 | 2015-11-06 | 2017-10-20 |
| 241180 | fast.atr_14_pct | A FAST daily risk entry gate | 25 | 2016-05-13 | 2017-06-02 |
| 241180 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 50 | 2016-06-24 | 2017-08-11 |
| 241180 | fast.range_position_24m | A FAST monthly permission gate | 64 | 2018-03-02 | 2019-05-24 |
| 241180 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 10 | 2016-09-23 | 2017-05-19 |
| 241180 | pattern_a.range_36m | Pattern A score availability and score input | 61 | 2019-03-08 | 2020-05-22 |
| 241180 | pattern_a.range_position_36m | Pattern A stage entry gate | 61 | 2019-03-08 | 2020-05-22 |
| 241180 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 30 | 2016-05-13 | 2017-06-09 |
| 266410 | fast.atr_14_pct | A FAST daily risk entry gate | 10 | 2017-04-21 | 2017-09-01 |
| 266410 | fast.higher_weekly_low_count_13w | A FAST stage and required score input | 20 | 2017-06-23 | 2017-11-10 |
| 266410 | fast.range_position_24m | A FAST monthly permission gate | 25 | 2019-03-08 | 2019-08-23 |
| 266410 | fast.recent_5d_max_gap_abs_pct | A FAST daily risk entry gate | 4 | 2017-04-07 | 2017-08-18 |
| 266410 | pattern_a.range_36m | Pattern A score availability and score input | 26 | 2020-02-28 | 2020-08-28 |
| 266410 | pattern_a.range_position_36m | Pattern A stage entry gate | 26 | 2020-02-28 | 2020-08-28 |
| 266410 | pit.avg_volume_20d | Point-in-time ETF entry eligibility | 12 | 2017-04-28 | 2017-09-08 |

진단 전용 distance_from_low 계열은 sentinel 포함 rolling low가 0이라 +Inf가 되고, pivot_low_slope는 0 pivot 평균 분모에서 NaN이 발생했어. A FAST entry contract 및 Pattern A 점수/stage는 이 feature들을 읽지 않아. pivot_low_slope와 range_position_52w는 해당 전략 판정에 사용되지 않아. 실제 비유한값 종류와 정확한 evaluation date는 sentinel_feature_impact.csv에서 확인할 수 있어.

## 검증

- ticker / row: 10 / 78
- universe 변경: 0; universe SHA 유지
- trade ledger 변경: 0; SHA 4444e0d56566cf497802509faaf42e9340c9c6e01ebe9a5ff4ff74844396a7bc 유지
- strategy source 변경: 0; KRX market refetch 0; 40D 재계산 0; 전체 ETF-36 5-window backtest 재실행 0
- 영향 ETF evaluator replay: 10개만, 2,172회
- 검증 checks: PASS (오류 없음)

## 산출물

- sentinel_rows.csv: sentinel별 weekly/monthly bar 소속 및 bar 내 양수 OHLC 행 수
- sentinel_feature_impact.csv: 영향을 받은 evaluation date별 입력 feature, 실제 값, non-finite 여부
- sentinel_signal_impact.csv: window/strategy별 evaluation, 후보 판정, PIT 자격, 원 ledger signal 교차
- sentinel_trade_impact.csv: 기존 ledger 거래의 직접 entry-date 노출 여부
- validation.json: count, SHA, 실행 제한 및 verdict
