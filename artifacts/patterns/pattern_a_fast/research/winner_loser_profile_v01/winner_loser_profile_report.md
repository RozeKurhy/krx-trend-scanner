# A FAST Core V2 — 고수익·손실 거래 특성 비교 V01

## 최종 판정: `ENTRY_PROFILE_WEAK__DEEP_LOSS_IS_POST_ENTRY_EXIT_MECHANICS`

- 진입 시점 특성만으로 +50% 이상 winner를 가려낼 수 있는 반복 특성은 없다. `WIN_50` 대비 전체에서 `CONSISTENT`로 나온 feature는 0개다.
- -30% 이하 loser에서는 진입 특성의 기울기가 반복해서 보인다. 해당 거래일수록 KOSDAQ 비중이 높았다. 52주 가중이동평균 기울기(`wma52_slope_1w`)가 가파르고, 변동성이 높고, 이미 많이 오른 위치였다. 다만 크기는 AUC 0.56~0.65 수준이다.
- 큰 손실은 진입 직후 무너진 거래가 아니다. 보유 중 먼저 크게 오른 뒤 청산 신호 없이 되돌아온 장기 보유 거래가 대부분이다. 진입 필터보다 PROGRESSED 이후 청산 공백 쪽이 설명력이 크다.

새 백테스트, 신규 signal, threshold 변경, 네트워크 호출은 모두 0건이다.

## 1. 입력 원장과 중복 제거

윈도우별 원장은 `docs/patterns/pattern_a_fast/strategy/FAST_CORE_V2_NEG40_WEAK_PROTECT_5_WINDOW_SYNTHESIS_V01.md`가 지정한 인증본의 CONTROL `control_trades.csv`만 사용했다.

| 윈도우 | 인증 상태 | 행 | 수치 비교 가능 |
|---|---|---:|---:|
| P1 | `P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS` | 4,983 | 4,982 |
| P2-1 | `P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS` | 1,801 | 1,800 |
| P2-2 | `COMPLETE` / aggregate reconciliation PASS | 2,424 | 2,424 |
| P3-1 | `P3_1_REPLAY_PASS` | 1,174 | 1,173 |
| P3-2 | `P3_2_REPLAY_PASS` (영구 제외 12 pair 적용) | 1,793 | 1,792 |

- **입력 게이트:** 5개 윈도우 모두 synthesis 문서의 CONTROL 값과 정확히 일치했다. 확인한 값은 n, 양수 비율, 평균, 중앙값, ≤-30/-40/-50/-60 건수, ≥+30/+50/+100 건수다. 따라서 필터와 수익률 계약이 synthesis와 같다.
- **수익률 계약:** 원장의 `terminal_return`을 그대로 쓴다. `OPEN_AT_CUTOFF`는 윈도우 cutoff 시점 평가값이며 synthesis와 같은 기준이다. `REALIZED`와 `LIFECYCLE_SETTLED`만 쓰는 closed-only는 민감도 점검으로 따로 봤다.
- **제외 대상:** 구버전·교정 전 원장, CHECK_REQUIRED 원장, 실제형 포트폴리오(`run_20260926_realistic_mcap1t_*`)는 `ledger_inventory.csv`에 상태와 함께 기록하고 분석에서 뺐다.
- **Pooled 모집단:** 선택된 인증본들이 뺀 identity의 합집합(50개)을 모든 윈도우에 똑같이 적용해 77행을 뺐다. 종료 평가값이 없는 authoritative-final 1건(`096300`)의 4행도 뺐다.
- **중복 제거:** 키는 `(ticker, isu_cd, entry_signal_date, entry_execution_date)`다. `trade_id`와 `pair_id`는 윈도우마다 순번이 다시 시작하므로 키로 쓰지 않았다.
  - 대표값 우선순위는 P1 > P3-2 > P2-2 > P2-1 > P3-1이다. cutoff가 늦은 쪽을 먼저 쓰고, 같은 cutoff끼리는 현재 lifecycle 계약 재인증본을 먼저 쓴다.
  - 12,094행이 **5,380건**이 되었고, 6,714행이 중복으로 빠졌다.
  - 같은 cutoff에서 수익률이 다른 identity는 4건이다: 138580(0.01pp), 029960(0.67pp), 115390(1.03pp), 019440(3.12pp).
  - 4건 모두 OPEN_AT_CUTOFF 평가값 차이이고, 이전 계약으로 실행된 P2-2가 끼어 있다. 대표값은 P1 값을 쓰므로 그룹 배정에는 영향이 없다.
- **윈도우 중첩:** P2-1⊂P2-2, P3-1⊂P3-2는 기간상 포함 관계다. 그러나 거래는 종목별 경로에 의존하므로 17건과 12건이 포함되지 않는다. 경로를 바꾸는 요인은 영구 제외, 데이터 authority, 이전 거래 이력이다.
  - 이 때문에 5개 윈도우의 방향 일치는 독립된 다섯 번의 확인이 아니다.
  - 그래서 겹치지 않는 두 기간(진입 2021년 이전 2,889건 / 2021년 이후 2,491건)의 방향 일치를 반복성 등급의 필수 조건으로 넣었다.

## 2. 그룹 건수 (pooled dedup 5,380건)

| 그룹 | 건수 | 그중 OPEN_AT_CUTOFF |
|---|---:|---:|
| `WIN_50` (≥+50%) | 830 | 46 |
| `WIN_100` (≥+100%) | 346 | 21 |
| `POSITIVE` (>0%) | 1,673 | 157 |
| `LOSS_ANY` (≤0%) | 3,707 | 125 |
| `LOSS_30` (≤-30%) | 110 | 56 |
| `LOSS_50` (≤-50%) | 41 | 32 |
| `LOSS_60` (≤-60%, 참고) | 28 | 25 |

`LOSS_50`은 윈도우별 표본이 7~42건이다. 등급 판정에 쓸 수 있는 윈도우는 P1, P2-1, P2-2 세 개뿐이다. closed-only 기준으로는 9건밖에 남지 않으므로 해석을 약하게 둔다.

## 3. 진입 feature와 판정 규칙

feature 목록과 등급 기준은 결과를 보기 전에 코드에 고정했다.

- **원장 필드:** `market`, `entry_pattern_a_stage`, `daily_risk`, `fast_score`, `fast_score_state`, `entry_kind`
  - `entry_kind`는 `previous_exit_type`으로 만든 REENTRY/FIRST_IN_WINDOW 구분이다. 윈도우 시작일에 따라 값이 달라진다.
- **공식 경로로 복원한 값:**
  - `pattern_a_score`, `fast_weekly_core_score`, `fast_conditional_status`
  - FAST 계약의 직접 입력값 11개: `range_position_24m`, `monthly_down_month_ratio_12m`, `distance_to_prior_26w_high_pct`, `close_vs_wma200_pct`, `higher_weekly_low_count_13w`, `wma52_slope_1w`, `wma12_vs_wma26_pct`, `weeks_since_26w_close_breakout`, `post_breakout_min_low_vs_level_pct_26w`, `recent_5d_max_gap_abs_pct`, `atr_14_pct`
  - 모두 `evaluate_pattern_a_fast`와 같은 snapshot·feature 함수로 복원했다.
- **투자가능성:** PIT 시가총액은 raw daily `market_cap`의 신호일 정확값이다. 20·60일 평균 거래대금과 투자가능성 상태는 `evaluate_investability`로 계산했다.
- **분산 없음:** `fast_stage`(전부 TRIGGER)와 `monthly_regime`(전부 PERMITTED_REGIME)은 진입 계약상 상수다. 그래서 구분력을 평가할 수 없다.

**복원 검증** (5,428개 신호 키):
- READY 5,428건, Pattern A 단계 불일치 0건, 원장 `fast_score` 불일치 0건
- 신호일까지 자른 일봉으로 다시 계산한 누수 점검 20건 불일치 0건
- 기존 `fastcore_v2_entry_pattern_score_bucket_v02`와 겹치는 3,345건의 Pattern A score 최대 차이 0.00005

**효과 크기:** 수치형은 rank AUC다. 그룹 값이 비교군보다 클 확률이며 0.5는 구분력 없음을 뜻한다. 범주형은 비율 차이(pp)다.

**반복성 등급:**
- `INSUFFICIENT_EVIDENCE`: pooled 양쪽 중 한쪽 n<10이거나, 양쪽 n≥10인 윈도우가 3개 미만
- `WEAK`: |AUC-0.5|<0.05 또는 |비율 차이|<5pp
- `CONSISTENT`: 등급 산정이 가능한 윈도우의 80% 이상이 pooled와 같은 방향이고, 겹치지 않는 두 기간도 모두 같은 방향
- `MIXED`: 그 외

## 4. Winner profile

| 비교 | CONSISTENT | 주요 내용 |
|---|---:|---|
| `WIN_50` vs 나머지 | 0 | 투자가능 비중 -7.3pp, REENTRY -5.2pp, ATR·거래대금 약간 낮음. 모두 MIXED |
| `WIN_100` vs 나머지 | 1 | 시총 1,000억 미만(`FILTERED_MARKET_CAP`) 비중 39.0% vs 27.3% (+11.7pp, 윈도우 `++++-`, 두 기간 `++`) |

- `WIN_100`은 소형주 쪽으로 약간 기울었다.
  - 거래대금과 시가총액 중앙값도 낮지만(20일 거래대금 15.7억 vs 25.2억, 시총 1,373억 vs 1,947억) MIXED다. P1·P2-1과 P2-2·P3 윈도우의 방향이 반대라서다.
  - KOSPI와 KOSDAQ 안에서 각각 봐도 소형주 쪽 기울기는 유지된다(+9.8pp / +13.7pp).
- `fast_score`와 `pattern_a_score`는 `WIN_50`과 `WIN_100` 모두에서 WEAK다(AUC 0.50~0.51).

## 5. Loser profile

### `LOSS_ANY` vs 양수 수익

CONSISTENT는 3개이며 모두 크기가 작다.

- `range_position_24m` 낮음: AUC 0.44
- ATR 높음: AUC 0.55
- 20일 거래대금 높음: AUC 0.55

`LOSS_ANY`의 89.3%(3,309건)는 PROGRESSED 이전 -15% Loss Guard 청산이다. 그래서 진입 특성과의 관계가 약하다.

### `LOSS_30` vs 나머지

CONSISTENT는 12개다. 5개 윈도우와 두 기간 모두 대체로 같은 방향이었다.

| feature | LOSS_30 | 나머지 | 효과 |
|---|---:|---:|---:|
| KOSDAQ 비중 | 70.0% | 53.7% | +16.3pp |
| `wma52_slope_1w` 중앙값 | 0.0068 | 0.0037 | AUC 0.649 |
| `atr_14_pct` | 0.0479 | 0.0419 | AUC 0.597 |
| `range_position_24m` | 0.598 | 0.542 | AUC 0.582 |
| `wma12_vs_wma26_pct` | 0.064 | 0.045 | AUC 0.579 |
| `close_vs_wma200_pct` | 0.201 | 0.156 | AUC 0.557 |
| `post_breakout_min_low_vs_level_pct_26w` | -0.068 | -0.041 | AUC 0.417 |
| REENTRY 비중 | 50.9% | 59.7% | -8.7pp |
| `fast_score` | 77.89 | 76.85 | AUC 0.560 |

- **요약:** 이미 가파르게 오르고 변동성이 크며 많이 오른 위치에서 들어간 거래였다.
- **closed-only 민감도:** 54건만 남지만 12개 모두 같은 방향이고 대부분 더 강해졌다.
- **시장 분할:** KOSPI와 KOSDAQ 안에서 각각 봐도 같은 방향이다. ATR, 이동평균 이격, gap은 KOSDAQ 쪽에서 더 뚜렷하다.

### `LOSS_50` vs 나머지

CONSISTENT는 4개다. 판정 가능 윈도우가 3개이고 표본이 41건이라 참고용으로만 본다.

- KOSDAQ 비중 +9.5pp
- `wma52_slope_1w` AUC 0.647
- `atr_14_pct` AUC 0.622
- `pattern_a_score` 낮음: 51.1 vs 60.5, AUC 0.423

## 6. Extreme contrast

### `WIN_50` (830) vs `LOSS_30` (110)

CONSISTENT는 11개이며 전부 5개 윈도우와 두 기간에서 같은 방향이다.

- KOSDAQ 비중: 52.9% vs 70.0% (-17.1pp)
- `wma52_slope_1w`: AUC 0.331 (winner가 완만함)
- `atr_14_pct`: AUC 0.364 (winner가 변동성 낮음)
- `wma12_vs_wma26_pct`: AUC 0.401
- `post_breakout_min_low_vs_level_pct_26w`: AUC 0.584 (winner가 돌파 후 눌림이 얕음)
- `range_position_24m`: AUC 0.421
- `close_vs_wma200_pct`: AUC 0.422

### `WIN_100` (346) vs `LOSS_50` (41)

CONSISTENT는 6개이며 판정 가능 윈도우는 3개다.

- `wma52_slope_1w`: AUC 0.321
- `atr_14_pct`: AUC 0.349
- `pattern_a_score`: AUC 0.594 (60.6 vs 51.1)
- `distance_to_prior_26w_high_pct`: AUC 0.574
- KOSDAQ 비중 -9.9pp

## 7. 진입 후 특성 (서술용, 예측 profile 아님)

MFE, MAE, 보유기간, giveback은 거래가 끝난 뒤에야 알 수 있는 값이다. 결과가 섞여 있으므로 설명용으로만 본다. 고정 20/40/60 거래일 MAE·MFE와 -15/-30/-40 최초 도달 시점은 CONTROL 원장에 없고 새로 만들지 않았다.

| | WIN_50 | LOSS_30 | LOSS_50 |
|---|---:|---:|---:|
| 첫 PROGRESSED까지 일수(중앙값) | 169 | 119.5 | 127 |
| 보유일수(중앙값) | 211 | 1,050 | 1,382 |
| MFE 중앙값 | +133% | +50% | +48% |
| peak giveback 중앙값 | 34 | 103 | 116 |
| OPEN_AT_CUTOFF 비중 | 5.5% | 50.9% | 78.0% |
| coverage 경로(SKIPPED + PROGRESSED_WITHOUT_DIRECT_HANDOFF) | 12.3% | 55.5% | 78.0% |
| Loss Guard 청산 비중 | 0% | 17.3% | 4.9% |

- **LOSS_30·LOSS_50의 전형:** 빠르게 PROGRESSED에 도달해 +50% 안팎까지 오른 뒤 되돌아왔다. Exit3·Exit4가 발동하지 않은 채 수년간 보유되다 cutoff에서 평가되었다.
- **원인:** 청산 계약의 coverage 공백이다. EARLY_TREND를 건너뛰었거나 직접 handoff 없이 PROGRESSED에 도달한 경로가 여기에 해당한다. 이는 기존 NEG40 Candidate 연구가 겨냥한 구간과 같다.
- **첫 PROGRESSED 시점의 handoff 경로:** 진입 후 비교적 이르게 알 수 있는 값 중 가장 강하게 갈린다(`post_entry_descriptive_profile.csv`, `lifecycle_class`).
  - coverage 경로 비중은 LOSS_30 55.5%, LOSS_50 78.0%다. WIN_50은 12.3%, WIN_100은 11.3%다.
  - WIN_50 vs LOSS_30에서 `NORMAL_EARLY_TREND_HANDOFF` 비중은 87.0% vs 35.5%(+51.5pp)다. WIN_100 vs LOSS_50에서는 88.7% vs 19.5%(+69.2pp)다.
  - 이 차이는 5개 윈도우(LOSS_50은 3개)와 두 기간에서 모두 CONSISTENT다.
- **첫 PROGRESSED까지 일수:** AUC는 0.66(WIN_50 vs LOSS_30), 0.68(WIN_100 vs LOSS_50)이다. 가장 강한 진입 feature인 `wma52_slope_1w`(0.33/0.32)와 크기가 비슷하다.
- **증거가 아닌 값:** 거래 전체 기준 MFE, MAE, giveback, profit_capture의 AUC 0.88~1.0은 그룹 정의상 당연히 나오는 값이다. 구분력의 증거로 쓰지 않는다.

## 8. 실전성 점검 (사분위 서술, cutoff 제안 아님)

`entry_feature_quartile_descriptive.csv` 기준 가장 강한 진입 feature 두 개를 보면 아래와 같다.

- **`wma52_slope_1w`:** 상위 사분위와 하위 사분위를 비교했다.
  - LOSS_30 비율 3.8% vs 1.3%
  - WIN_50 비율 13.7% vs 17.0%
  - 평균 수익률 9.4% vs 10.6%
  - 상위 사분위를 모두 빼면 LOSS_30 51건을 피하는 대신 WIN_50 184건도 잃는다.
- **`atr_14_pct`:** 상위 사분위와 하위 사분위를 비교했다.
  - LOSS_30 비율 3.0% vs 1.2%
  - WIN_50 비율 12.4% vs 18.4%
  - 평균 수익률 7.4% vs 14.1%

LOSS_30의 기저율이 2.0%라서 AUC 0.6대 feature로는 winner 손실 없이 tail만 걸러내기 어렵다.

## 9. 질문별 답

1. **+50% winner에 반복되는 진입 특성이 있는가?** 없다. CONSISTENT 0개이고 MIXED 5개(투자가능 비중, REENTRY, ATR, 거래대금)도 윈도우별 방향이 갈린다.
2. **+100% winner에서 더 강한 특성이 있는가?** 시총 1,000억 미만 비중만 CONSISTENT다(+11.7pp). 거래대금·시총이 낮은 쪽 기울기는 MIXED다.
3. **-30% loser에 반복되는 진입 특성이 있는가?** 있다. KOSDAQ, 가파른 52주 기울기, 높은 ATR, 높은 24개월 위치, 큰 이동평균 이격, 첫 진입이 반복된다. 효과는 AUC 0.56~0.65로 작다.
4. **-50% loser에 반복되는 특성이 있는가?** -30%와 같은 방향(기울기, ATR, KOSDAQ)에 낮은 Pattern A score가 더해진다. 판정 가능 윈도우가 3개이고 표본이 41건이라 약한 증거다.
5. **winner와 loser를 가장 잘 구분하는 feature는?** `wma52_slope_1w`(AUC 0.33/0.32), `atr_14_pct`(0.36/0.35), KOSDAQ 비중(-17pp)이다.
6. **여러 window에서 반복되는가?** `LOSS_30` 관련 특성은 5개 윈도우와 겹치지 않는 두 기간에서 모두 같은 방향이다. KOSPI·KOSDAQ 각각에서도 같은 방향이다. `monthly_regime`은 상수라 regime별 분리는 할 수 없다.
7. **Pattern A score 자체는 구분력이 약한가?** 그렇다. WIN_50, WIN_100, LOSS_ANY, LOSS_30에서 모두 WEAK다(AUC 0.49~0.52). 예외는 표본이 작은 LOSS_50(AUC 0.42)뿐이다. 기존 연구 결론과 일치한다. -35/-40/-45 tail timing은 CONTROL 원장에 없어 다시 확인하지 못했다.
8. **진입 특성만으로 쓸 만한 profile이 있는가?** 없다. 사분위 서술상 tail을 줄이는 만큼 winner도 함께 줄어든다.
9. **진입 후 초기 특성이 더 명확한가?** 첫 PROGRESSED까지 걸린 기간의 구분력은 진입 feature와 비슷하다. 첫 PROGRESSED 시점의 handoff 경로는 훨씬 강하다. coverage 경로 비중이 LOSS_30 55.5%, LOSS_50 78.0%인데 WIN_50은 12.3%다. deep loss 대부분은 이 경로에서 청산 신호 없이 되돌아온 장기 보유 거래다.
10. **추가 연구 가치가 있는가?** 진입 필터 연구 가치는 낮다. 가치가 있는 쪽은 PROGRESSED 이후, 특히 coverage 경로의 청산 공백이다. 진입 시 기울기와 ATR은 그 연구에서 조건 변수로 참고할 수 있다. 새 전략안은 만들지 않았다.

## 10. 해석 주의

- 상관을 인과로 읽지 않는다. cutoff는 새로 튜닝하지 않았다.
- 윈도우끼리 겹치므로 윈도우 일치는 독립 반복이 아니다. 겹치지 않는 두 기간의 일치를 함께 봐야 한다.
- LOSS_30의 절반과 LOSS_50의 78%는 cutoff 평가 미청산 거래다. cutoff가 달라지면 값도 달라진다.
- REENTRY 비중은 윈도우 시작일에 따라 달라진다. LOSS_30에서 REENTRY 비중이 낮은 이유는 보유 가능 기간 차이일 수도 있다. 재진입 거래는 윈도우 안에서 늦게 시작하므로 수년간 미청산으로 남을 시간이 짧다.
- `window_consistency.csv`의 윈도우별 결과는 각 윈도우 자체 인증 모집단 기준이다. pooled처럼 제외 합집합을 적용하지 않았다.

## 산출물

| 파일 | 내용 |
|---|---|
| `ledger_inventory.csv` | 5개 윈도우 원장 목록, 상태, SHA-256 |
| `dedup_trade_index.csv` | 중복 제거 5,380건과 관측 윈도우 |
| `group_counts.csv` | pooled, 윈도우, 두 기간, closed-only 그룹 건수 |
| `entry_feature_profile.csv` | 7개 비교 × 진입 feature의 pooled 통계, AUC, 등급 |
| `window_consistency.csv` | 윈도우와 두 기간별 효과 |
| `extreme_contrast.csv` | WIN_50 vs LOSS_30, WIN_100 vs LOSS_50 |
| `post_entry_descriptive_profile.csv` | 진입 후 특성(서술용) |
| `group_lifecycle_mechanics.csv` | 그룹별 lifecycle, exit, status 구성 |
| `entry_feature_quartile_descriptive.csv` | 사분위별 결과 비율(서술용) |
| `entry_feature_enrichment.csv` / `entry_feature_enrichment_audit.json` | 진입 feature 복원 캐시와 검증 |
| `winner_loser_profile_summary.json` | 입력 게이트, dedup, 등급 규칙, 민감도, 시장 분할 |

재현 방법은 `python scripts/analyze_fastcore_v2_winner_loser_profile_v01.py enrich` 다음 `analyze`다. `analyze`는 같은 입력에서 SHA가 같은 산출물을 만든다.
