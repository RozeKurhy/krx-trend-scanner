# ETF V3 vs Julia Integrated Comparison V01

## A. 실험 범위

이 문서는 이미 확정된 artifact를 재사용하여 ETF 21개에서 V3와 Julia의 결과를 통합 비교한다.

- 시장지수 ETF 5개: 229200, 292190, 226490, 156080, 226980
- 섹터지수 ETF 16개: 091160, 102970, 091170, 091180, 266420, 140700, 117700, 266370, 363580, 266360, 117460, 117680, 102960, 266410, 140710, 266390
- 전체 universe: 21개
- 비교 전략: V3 vs Julia
- 비교 구간: LONG RANGE와 SAME WINDOW를 분리
- 자료: `market_index_etf_four_strategy_v01` 및 `sector_index_etf_four_strategy_v01`의 확정 aggregate/개별 summary
- 재백테스트, 네트워크 호출, 전략·production 코드 수정: 없음

각 ETF를 동일한 1개 비교 단위로 취급했으며, 21개 결과를 하나의 포트폴리오 수익률로 합산하지 않았다. 가격·거래대금 필터 조건은 각 확정 실험의 최종 조건을 그대로 따랐다. 특히 섹터 corrected artifact는 가격·거래대금 필터가 꺼진 조건이다. `return` 수치는 원본 artifact의 sequential metric 단위를 유지한다.

전체 21개는 LONG RANGE와 SAME WINDOW 모두 각 지표에서 evaluable 21/21이다.

## B. 시장지수 ETF 5개 direct head-to-head

각 셀은 `V3 승 / Julia 승 / tie`이며, MDD·MAE는 덜 음수인 쪽을 우위로 판정했다.

| 지표 | LONG RANGE | SAME WINDOW |
|---|---:|---:|
| sequential total return | 1 / 4 / 0 | 2 / 3 / 0 |
| sequential CAGR | 1 / 4 / 0 | 2 / 3 / 0 |
| sequential MDD | 0 / 5 / 0 | 0 / 4 / 1 |
| matched mean return | 1 / 4 / 0 | 1 / 4 / 0 |
| matched median return | 1 / 4 / 0 | 1 / 4 / 0 |
| matched win rate | 0 / 0 / 5 | 0 / 0 / 5 |
| matched mean MAE | 1 / 0 / 4 | 1 / 0 / 4 |

각 구간의 분모는 5/5이다.

## C. 섹터지수 ETF 16개 direct head-to-head

| 지표 | LONG RANGE | SAME WINDOW |
|---|---:|---:|
| sequential total return | 5 / 11 / 0 | 7 / 8 / 1 |
| sequential CAGR | 5 / 11 / 0 | 7 / 8 / 1 |
| sequential MDD | 6 / 6 / 4 | 7 / 3 / 6 |
| matched mean return | 3 / 13 / 0 | 5 / 10 / 1 |
| matched median return | 3 / 12 / 1 | 6 / 9 / 1 |
| matched win rate | 5 / 0 / 11 | 5 / 0 / 11 |
| matched mean MAE | 12 / 0 / 4 | 10 / 0 / 6 |

각 구간의 분모는 16/16이다.

## D. 전체 21개 ETF 통합 head-to-head

시장 5개와 섹터 16개의 ETF-level 판정을 합산했다. 각 셀은 `V3 승 / Julia 승 / tie`이다.

| 지표 | LONG RANGE (21/21) | SAME WINDOW (21/21) |
|---|---:|---:|
| sequential total return | 6 / 15 / 0 | 9 / 11 / 1 |
| sequential CAGR | 6 / 15 / 0 | 9 / 11 / 1 |
| sequential MDD | 6 / 11 / 4 | 7 / 7 / 7 |
| matched mean return | 4 / 17 / 0 | 6 / 14 / 1 |
| matched median return | 4 / 16 / 1 | 7 / 13 / 1 |
| matched win rate | 5 / 0 / 16 | 5 / 0 / 16 |
| matched mean MAE | 13 / 0 / 8 | 11 / 0 / 10 |

수익률 계열에서 Julia 우위는 LONG RANGE와 SAME WINDOW 모두 다수였고, MDD에서는 SAME WINDOW에 동률이 상대적으로 많았다.

## E. 수익 차이의 크기

각 ETF의 `Julia sequential total return - V3 sequential total return`을 사용했다. 평균과 median은 ETF-level simple mean/median이며, 수익 차이의 단위는 원본 artifact의 return 단위이다.

| universe | 구간 | ETF-level simple mean | median | Julia 양수 우위 | V3 음수 우위 | tie |
|---|---|---:|---:|---:|---:|---:|
| 시장 5 | LONG RANGE | 47.493444 | 13.092871 | 4 | 1 | 0 |
| 시장 5 | SAME WINDOW | 24.500240 | 8.195543 | 3 | 2 | 0 |
| 섹터 16 | LONG RANGE | 16.663935 | 14.594094 | 11 | 5 | 0 |
| 섹터 16 | SAME WINDOW | 12.030328 | 9.608721 | 8 | 7 | 1 |
| 전체 21 | LONG RANGE | 24.004294 | 13.342783 | 15 | 6 | 0 |
| 전체 21 | SAME WINDOW | 14.999355 | 8.195543 | 11 | 9 | 1 |

## F. 위험 차이

### MDD

MDD는 덜 음수인 값을 우위로 판정했다.

| universe | 구간 | V3 우위 | Julia 우위 | tie |
|---|---|---:|---:|---:|
| 시장 5 | LONG RANGE | 0 | 5 | 0 |
| 시장 5 | SAME WINDOW | 0 | 4 | 1 |
| 섹터 16 | LONG RANGE | 6 | 6 | 4 |
| 섹터 16 | SAME WINDOW | 7 | 3 | 6 |
| 전체 21 | LONG RANGE | 6 | 11 | 4 |
| 전체 21 | SAME WINDOW | 7 | 7 | 7 |

### Matched mean MAE

MAE도 덜 음수인 값을 우위로 판정했다.

| universe | 구간 | V3 우위 | Julia 우위 | tie |
|---|---|---:|---:|---:|
| 시장 5 | LONG RANGE | 1 | 0 | 4 |
| 시장 5 | SAME WINDOW | 1 | 0 | 4 |
| 섹터 16 | LONG RANGE | 12 | 0 | 4 |
| 섹터 16 | SAME WINDOW | 10 | 0 | 6 |
| 전체 21 | LONG RANGE | 13 | 0 | 8 |
| 전체 21 | SAME WINDOW | 11 | 0 | 10 |

## G. 수익-위험 조합

수익 우위와 MDD 우위를 동시에 분류했다. 마지막 열은 return tie 케이스이며, 괄호 안은 그중 MDD tie인 개수이다.

| universe | 구간 | Julia 수익 + Julia MDD | Julia 수익 + V3 MDD | Julia 수익 + MDD tie | V3 수익 + V3 MDD | V3 수익 + Julia MDD | V3 수익 + MDD tie | return tie |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 시장 5 | LONG RANGE | 4 | 0 | 0 | 0 | 1 | 0 | 0 |
| 시장 5 | SAME WINDOW | 3 | 0 | 0 | 0 | 1 | 1 | 0 |
| 섹터 16 | LONG RANGE | 3 | 5 | 3 | 1 | 3 | 1 | 0 |
| 섹터 16 | SAME WINDOW | 0 | 4 | 4 | 3 | 3 | 1 | 1 (MDD tie 1) |
| 전체 21 | LONG RANGE | 7 | 5 | 3 | 1 | 4 | 1 | 0 |
| 전체 21 | SAME WINDOW | 3 | 4 | 4 | 3 | 4 | 2 | 1 (MDD tie 1) |

LONG RANGE 전체에서 Julia 수익 우위 15건 중 Julia MDD 우위는 7건, V3 MDD 우위는 5건, 동률은 3건이었다. 따라서 Julia의 수익 우위가 일관된 위험 개선만으로 설명되지는 않는다.

## H. 평균 보유기간과 거래 특성

보유일은 sequential summaries의 거래 건수를 가중치로 사용한 `trade-count weighted mean`이다. Exposure는 보조 지표로 ETF-level simple mean을 표시했다.

| universe | 구간 | 전략 | 총 trade count | 평균 보유일 | 평균 exposure |
|---|---|---|---:|---:|---:|
| 시장 5 | LONG RANGE | V3 | 7 | 650.571429 | 41.118790% |
| 시장 5 | LONG RANGE | Julia | 6 | 724.000000 | 38.731005% |
| 시장 5 | SAME WINDOW | V3 | 5 | 592.200000 | 44.870086% |
| 시장 5 | SAME WINDOW | Julia | 5 | 553.600000 | 41.935170% |
| 섹터 16 | LONG RANGE | V3 | 45 | 426.355556 | 42.856687% |
| 섹터 16 | LONG RANGE | Julia | 29 | 763.172414 | 49.111502% |
| 섹터 16 | SAME WINDOW | V3 | 32 | 300.656250 | 45.387017% |
| 섹터 16 | SAME WINDOW | Julia | 18 | 646.333333 | 54.982021% |
| 전체 21 | LONG RANGE | V3 | 52 | 456.538462 | 42.442902% |
| 전체 21 | LONG RANGE | Julia | 35 | 756.457143 | 46.639955% |
| 전체 21 | SAME WINDOW | V3 | 37 | 340.054054 | 45.263939% |
| 전체 21 | SAME WINDOW | Julia | 23 | 626.173913 | 51.875628% |

전체 기준으로 Julia의 거래 수는 V3보다 적었고, 거래 단위 가중 평균 보유일은 LONG RANGE에서 299.918681일, SAME WINDOW에서 286.119859일 더 길었다. 이는 수익 차이를 단기 신호 우위만으로 해석하지 않도록 하는 중요한 특성 차이다.

## I. 시장지수와 섹터지수의 일관성

1. Julia의 수익 우위는 시장지수에만 국한되지 않는다. sequential total return 기준으로 시장은 LONG 4/5, SAME 3/5, 섹터는 LONG 11/16, SAME 8/16에서 Julia가 우위였다.
2. 섹터지수에서도 수익 우위가 반복된다. 다만 SAME WINDOW 섹터에서는 V3 7건, Julia 8건, tie 1건으로 차이가 LONG RANGE보다 좁다.
3. 방향은 두 universe와 두 구간에서 대체로 일관된다. 전체 sequential total return은 LONG 15 대 6, SAME 11 대 9로 Julia가 앞서지만 SAME에서는 동률 1건이 있다.
4. Julia 수익 우위와 V3 MDD 우위가 동시에 나타난 경우는 전체에서 LONG 5건, SAME 4건이다. 동시에 Julia 수익 우위와 Julia MDD 우위인 경우도 LONG 7건, SAME 3건이므로, 수익 우위의 위험 특성은 단일 방향이 아니다.
5. 보유기간 차이는 크다. 전체 trade-count weighted 평균은 Julia가 LONG RANGE에서 756.46일 대 V3 456.54일, SAME WINDOW에서 626.17일 대 V3 340.05일이다. 그러므로 두 전략의 결과는 거래 빈도와 보유기간 구조가 다른 비교로 해석해야 한다.

## J. KODEX200 별도 참고

`kodex200_four_strategy_reproduction_v01`은 별도 실험 패키지이므로 21개 통합 분모에 포함하지 않았다. 해당 패키지의 LONG RANGE 실제 strategies 요약에서 V3는 sequential total return 306.358047, CAGR 11.757126, MDD -35.987929였고 Julia는 각각 296.858678, 11.547738, -40.653863이었다. 이 별도 결과만 보면 V3가 수익과 MDD 모두 우위인 방향이다.

단, 이 패키지의 reference comparison은 MDD equity-curve marking convention divergence를 별도 경고한다. 또한 SAME WINDOW에서 동일 조건의 Julia 결과가 없으므로 SAME 비교는 하지 않는다. 따라서 KODEX200은 통합 결론을 변경하는 자료가 아니라 방향 참고로만 사용한다.

## K. 최종 결론

- 수익성: 확정된 21개 ETF에서 Julia가 sequential total return과 CAGR의 ETF-level 승리 건수에서 LONG RANGE와 SAME WINDOW 모두 앞선다. matched mean/median return도 Julia 우위가 다수다.
- 위험: MDD는 LONG RANGE에서 Julia 우위가 더 많지만, SAME WINDOW 전체는 V3 7 / Julia 7 / tie 7로 동률이 많다. matched mean MAE는 두 구간 모두 V3 우위 또는 tie만 관찰됐다.
- 보유기간: Julia는 거래 수가 적고 평균 보유기간이 더 길다. 전체 기준 차이는 LONG RANGE 약 300일, SAME WINDOW 약 286일이다.
- 일관성: 수익 우위는 시장지수와 섹터지수 모두에서 반복되지만, 위험 우위는 일관된 단일 방향이 아니다.
- 다음 단계: 이 정도의 ETF-level 비교 증거는 Julia를 동일한 공식 검증 프레임에서 추가 검증할 근거는 제공한다. 그러나 이것만으로 공식 전략 승격, V3 폐기, V2 역할 변경, 자금배분 또는 ETF 전용 공식전략 확정을 결론내리지는 않는다.
