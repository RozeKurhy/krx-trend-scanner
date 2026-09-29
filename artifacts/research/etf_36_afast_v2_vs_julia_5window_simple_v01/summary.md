# ETF-36 A FAST Core V2 vs Julia V00: 5-window 단순 비교

**Verdict:** `ETF_36_AFAST_V2_VS_JULIA_5WINDOW_SIMPLE_BACKTEST_COMPLETE`

## Universe 및 coverage

V04 공식 37개에서 `474800 KIWOOM 미국원유에너지기업`만 제거했고, 나머지 36개 ticker 집합을 동결했어. 분류는 MARKET_INDEX 12, SECTOR_INDEX 19, COMMODITY_RESOURCE 5야.
일반계좌 매매차익 과세 표시는 KRX V02 product master `TAX_TP_CD`와 일치하는 metadata로만 보관했어(15 taxable / 21 domestic stock ETF non-taxable). 백테스트 PnL에는 추가 세금을 적용하지 않았어.

| Window | Universe | FULL | PARTIAL | NOT_EVALUABLE |
|---|---:|---:|---:|---:|
| P1 | 36 | 0 | 36 | 0 |
| P2-1 | 36 | 28 | 6 | 2 |
| P2-2 | 36 | 28 | 8 | 0 |
| P3-1 | 36 | 30 | 4 | 2 |
| P3-2 | 36 | 30 | 6 | 0 |

평가 불가 종목:

- P2-1 / 449450 PLUS K방산: STRATEGY_READY_AFTER_WINDOW_END
- P2-1 / 453810 KODEX 인도Nifty50: STRATEGY_READY_AFTER_WINDOW_END
- P3-1 / 449450 PLUS K방산: STRATEGY_READY_AFTER_WINDOW_END
- P3-1 / 453810 KODEX 인도Nifty50: STRATEGY_READY_AFTER_WINDOW_END

## 5-window OVERALL 비교

수익률은 거래별 수수료·슬리피지 차감 후, 세금 차감 전이야. win rate와 임계수익 건수는 cutoff 종가 평가(open trade 포함), 평균·중앙 realized return은 종료 체결된 거래만 사용해.

| Window | 전략 | ETF | Trades | Closed / Open | Win % | 평균·중앙 realized % | +50 / +100 | ≤−15 / −30 / −40 | 평균 보유 세션 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | A FAST Core V2 | 36 | 88 | 75 / 13 | 53.41 | 22.39 / -11.90 | 25 / 8 | 30 / 2 / 1 | 353.9 |
| P1 | Julia V00 | 36 | 55 | 37 / 18 | 81.82 | 60.17 / 58.39 | 25 / 10 | 7 / 4 / 4 | 734.8 |
| P2-1 | A FAST Core V2 | 34 | 54 | 34 / 20 | 53.70 | 0.14 / -14.09 | 1 / 0 | 19 / 2 / 2 | 304.9 |
| P2-1 | Julia V00 | 34 | 40 | 13 / 27 | 67.50 | 27.62 / 32.10 | 2 / 0 | 9 / 4 / 3 | 520.5 |
| P2-2 | A FAST Core V2 | 36 | 68 | 55 / 13 | 57.35 | 23.22 / 3.87 | 18 / 7 | 19 / 1 / 1 | 343.5 |
| P2-2 | Julia V00 | 36 | 47 | 29 / 18 | 80.85 | 58.07 / 40.95 | 18 / 9 | 7 / 4 / 4 | 613.6 |
| P3-1 | A FAST Core V2 | 34 | 43 | 26 / 17 | 46.51 | -9.02 / -15.47 | 2 / 0 | 17 / 1 / 1 | 229.7 |
| P3-1 | Julia V00 | 34 | 30 | 4 / 26 | 66.67 | 33.48 / 35.20 | 2 / 0 | 5 / 2 / 2 | 463.7 |
| P3-2 | A FAST Core V2 | 36 | 59 | 47 / 12 | 50.85 | 22.00 / -13.90 | 18 / 7 | 19 / 0 / 0 | 277.5 |
| P3-2 | Julia V00 | 36 | 37 | 20 / 17 | 81.08 | 74.76 / 59.04 | 19 / 9 | 6 / 3 / 2 | 584.5 |

## 카테고리 비교

| Window | Category | 평가 ETF | V2/Julia 거래 수 | V2/Julia win rate % | V2/Julia median realized % | paired ETF-window | 평균 paired 차이 pp |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | MARKET_INDEX | 12 | 21 / 15 | 66.67 / 93.33 | 40.97 / 60.46 | 11 | 8.10 |
| P1 | SECTOR_INDEX | 19 | 54 / 33 | 48.15 / 72.73 | -13.19 / 43.09 | 18 | 12.83 |
| P1 | COMMODITY_RESOURCE | 5 | 13 / 7 | 53.85 / 100.00 | 1.27 / 30.70 | 5 | 14.20 |
| P2-1 | MARKET_INDEX | 11 | 14 / 13 | 64.29 / 61.54 | -4.01 / 40.95 | 11 | 0.12 |
| P2-1 | SECTOR_INDEX | 18 | 31 / 21 | 48.39 / 66.67 | -14.09 / 14.49 | 16 | -0.64 |
| P2-1 | COMMODITY_RESOURCE | 5 | 9 / 6 | 55.56 / 83.33 | -15.66 / 38.10 | 5 | 2.47 |
| P2-2 | MARKET_INDEX | 12 | 16 / 14 | 81.25 / 92.86 | 35.27 / 57.21 | 11 | -0.02 |
| P2-2 | SECTOR_INDEX | 19 | 42 / 27 | 47.62 / 70.37 | -13.19 / 32.10 | 18 | 9.63 |
| P2-2 | COMMODITY_RESOURCE | 5 | 10 / 6 | 60.00 / 100.00 | 20.19 / 43.29 | 5 | 30.12 |
| P3-1 | MARKET_INDEX | 11 | 11 / 11 | 63.64 / 63.64 | -13.88 / 59.04 | 11 | 1.43 |
| P3-1 | SECTOR_INDEX | 18 | 25 / 15 | 40.00 / 66.67 | -15.53 / 11.36 | 15 | 3.71 |
| P3-1 | COMMODITY_RESOURCE | 5 | 7 / 4 | 42.86 / 75.00 | — | 4 | 3.09 |
| P3-2 | MARKET_INDEX | 12 | 15 / 12 | 73.33 / 91.67 | 36.71 / 59.04 | 11 | 7.84 |
| P3-2 | SECTOR_INDEX | 19 | 36 / 21 | 41.67 / 71.43 | -14.08 / 75.16 | 17 | 20.75 |
| P3-2 | COMMODITY_RESOURCE | 5 | 8 / 4 | 50.00 / 100.00 | -15.17 / 52.19 | 4 | 37.65 |

## 반복 특성 읽기

Julia가 V2보다 높은 window 수(최대 5개): win rate 5, median realized return 5, 평균 보유 세션 5.
이 수치는 공식 ETF-36 단순 trade-level 비교의 특성 요약이야. 현실적 포트폴리오 테스트 전 최종 전략 채택 판정으로 해석하지 않아.

## 실행 조건 / 검증

- 기존 KRX raw ETF OHLCV를 재사용했고 시장 재조회 0회, 40D 재계산 0회.
- 독립 ticker/window replay, worker 10개. 시작일 이후 신호만 허용, window cutoff 이후 신규 진입 금지, 기존 execution support만 exit 체결에 허용.
- Portfolio/cash/capital/MDD 분석, 세금 PnL 계산, threshold sweep은 수행하지 않았어.
- 결과 검증: PASS; 오류 0건.
- commit/push 세부 결과는 `r.md`와 작업 완료 응답에 기록해.

## 원시 무거래 행과 기존 계산 경고

KRX raw에는 거래량 0, 종가 양수, 시가·고가·저가 0인 무거래 sentinel이 78개(10 ETF)에 있었어. 원시 데이터 계약대로 값을 보존했고 별도 보정은 하지 않았어.
기존 feature 계산 중 divide-by-zero/invalid runtime warning이 monthly 1451, weekly 947, pivot 37회 관측됐어. 전략 로직은 바꾸지 않았고 거래 ledger의 필수 수치에는 NaN/Inf가 없어.
이 현상은 특히 가장 이른 history 구간 해석의 한계야. 포트폴리오 단계 전 기존 feature 처리를 별도 검토해야 해.
