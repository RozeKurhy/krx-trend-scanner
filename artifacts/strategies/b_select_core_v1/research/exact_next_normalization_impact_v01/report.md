# B Select exact-next 정규화 영향 검증 V01

| 레벨 | 개수 |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 7 |
| MINOR | 0 |

판정: `B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS`

## 핵심 판정

7건은 원본 P1/P2 source trade ledger에는 존재하지만, 현재 승인된 영구 제외 정책에서 모두 `RAW_DATA_GAP`으로 제외된다. 공식 V03 cash-aware portfolio event stream, 현재 필터 적용 candidate, trade key 기준 노출은 모두 0건이다.
V03 생성 시 exclusion policy hash에 해당하는 Git revision `708a3af65a3ec53bfa9f3f6fb6eab69ea653f579`을 확인했고, 당시 166개 identity 정책에도 대상 7개가 모두 포함됐다.
따라서 공식 포트폴리오에 제외 identity를 다시 넣는 재생은 현재 승인 universe를 바꾸므로 실행하지 않았다. 아래 거래 수익률은 원본 source ledger의 개별 민감도이며 공식 포트폴리오 성과로 해석하지 않는다.

## 7건 거래별 정규화 민감도

| 종목 | 쪽 | 신호일 | 저장 체결일/현행 조정시가 | exact-next일/현행 조정시가 | 당겨진 KRX 세션 | 비용 전 수익률 전→후 | 비용 반영·매도세 전 수익률 전→후 | 변화 | 공식 제외 사유 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 018680 | ENTRY | 2016-02-29 | 2016-03-03 / 15,764 | 2016-03-02 / 14,431 | 1 | 32.3522% → 44.5776% | 32.0481% → 44.2455% | 12.1974%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 072020 | ENTRY | 2017-03-31 | 2017-04-04 / 15,873 | 2017-04-03 / 15,063 | 1 | 4.0824% → 9.6793% | 3.8433% → 9.4274% | 5.5841%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 109820 | ENTRY | 2017-03-31 | 2017-04-04 / 2,586 | 2017-04-03 / 2,510 | 1 | 35.0735% → 39.1633% | 34.7632% → 38.8436% | 4.0805%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 001040 | EXIT | 2017-05-31 | 2017-06-05 / 202,266 | 2017-06-01 / 198,965 | 2 | 23.2758% → 21.2639% | 22.9926% → 20.9853% | -2.0073%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 005030 | EXIT | 2016-05-31 | 2016-06-02 / 1,643 | 2016-06-01 / 1,639 | 1 | 18.2014% → 17.9137% | 17.9299% → 17.6428% | -0.2871%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 014200 | EXIT | 2022-03-31 | 2022-04-04 / 27,378 | 2022-04-01 / 21,072 | 1 | 114.1081% → 64.7924% | 113.6162% → 64.4138% | -49.2024%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |
| 078160 | EXIT | 2018-11-30 | 2018-12-04 / 37,839 | 2018-12-03 / 36,909 | 1 | 8.2444% → 5.5840% | 7.9957% → 5.3414% | -2.6543%p | user-approved permanent exclusion for historical valuation RAW_DATA_GAP |

## Portfolio 포함 여부와 성과 전후

| Window | source ledger 노출 | 현재 필터 candidate 노출 | 공식 portfolio event 노출 | 기말자산 전→후 | 총수익률 전→후 | CAGR 전→후 | MDD 전→후 | 평균 자본 활용률 전→후 | 현금부족 skip 전→후 | 거래수 전→후 | 승률 전→후 | 평균/중앙 수익률 전→후 | 보유기간 평균/중앙 전→후 | tail ≤-15/≤-30/≥+30/≥+50 전→후 | Gate A–E 전→후 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1 | 7 | 0 | 0 | 393,558,408.1543원 → 393,558,408.1543원 | 96.7792% → 96.7792% | 5.4925% → 5.4925% | -16.2092% → -16.2092% | 24.0735% → 24.0735% | 19 → 19 | 464 → 464 / 417 → 417 | 79.1367% → 79.1367% | 12.8828% → 12.8828% / 12.1299% → 12.1299% | 140.1055 → 140.1055 / 43 → 43 | 47/25/74/24 → 47/25/74/24 | PASSPASSPASSPASSPASS → PASSPASSPASSPASSPASS |
| P2-1 | 1 | 0 | 0 | 254,892,899.1638원 → 254,892,899.1638원 | 27.4464% → 27.4464% | 5.6671% → 5.6671% | -22.6397% → -22.6397% | 36.1055% → 36.1055% | 22 → 22 | 193 → 193 / 157 → 157 | 78.3439% → 78.3439% | 15.3771% → 15.3771% / 12.2452% → 12.2452% | 121.1210 → 121.1210 / 43 → 43 | 14/7/33/11 → 14/7/33/11 | PASSPASSPASSPASSPASS → PASSPASSPASSPASSPASS |
| P2-2 | 1 | 0 | 0 | 253,821,074.9707원 → 253,821,074.9707원 | 26.9105% → 26.9105% | 4.3053% → 4.3053% | -22.6397% → -22.6397% | 37.3746% → 37.3746% | 65 → 65 | 254 → 254 / 216 → 216 | 75.9259% → 75.9259% | 12.1053% → 12.1053% / 11.0395% → 11.0395% | 144.6296 → 144.6296 / 43 → 43 | 26/13/40/13 → 26/13/40/13 | PASSPASSPASSPASSPASS → PASSPASSPASSPASSPASS |
| P3-1 | 0 | 0 | 0 | 238,754,565.9384원 → 238,754,565.9384원 | 19.3773% → 19.3773% | 5.3424% → 5.3424% | -19.6158% → -19.6158% | 47.7485% → 47.7485% | 24 → 24 | 154 → 154 / 121 → 121 | 80.1653% → 80.1653% | 15.5814% → 15.5814% / 14.0034% → 14.0034% | 142.0579 → 142.0579 / 44 → 44 | 14/7/29/10 → 14/7/29/10 | PASSPASSPASSPASSPASS → PASSPASSPASSPASSPASS |
| P3-2 | 0 | 0 | 0 | 236,323,528.2399원 → 236,323,528.2399원 | 18.1618% → 18.1618% | 3.6484% → 3.6484% | -19.6158% → -19.6158% | 46.1789% → 46.1789% | 70 → 70 | 212 → 212 / 176 → 176 | 77.2727% → 77.2727% | 12.3316% → 12.3316% / 11.6869% → 11.6869% | 155.6307 → 155.6307 / 44 → 44 | 24/11/35/12 → 24/11/35/12 | PASSPASSPASSPASSPASS → PASSPASSPASSPASSPASS |

## 정확성 검증

- 018680 ENTRY 2016-02-29: 신호 다음 exact KRX 세션 `2016-03-02` 확인; 조정시가 14,431원 유효; 원시 KRX open 12450원 / volume 33,989; 저장일과 listed shares 동일. 반대편 체결은 `2016-05-02` 그대로 유지.
- 072020 ENTRY 2017-03-31: 신호 다음 exact KRX 세션 `2017-04-03` 확인; 조정시가 15,063원 유효; 원시 KRX open 18600원 / volume 89,651; 저장일과 listed shares 동일. 반대편 체결은 `2017-06-01` 그대로 유지.
- 109820 ENTRY 2017-03-31: 신호 다음 exact KRX 세션 `2017-04-03` 확인; 조정시가 2,510원 유효; 원시 KRX open 3765원 / volume 31,695; 저장일과 listed shares 동일. 반대편 체결은 `2018-02-01` 그대로 유지.
- 001040 EXIT 2017-05-31: 신호 다음 exact KRX 세션 `2017-06-01` 확인; 조정시가 198,965원 유효; 원시 KRX open 211000원 / volume 50,989; 저장일과 listed shares 동일. 반대편 체결은 `2017-03-02` 그대로 유지.
- 005030 EXIT 2016-05-31: 신호 다음 exact KRX 세션 `2016-06-01` 확인; 조정시가 1,639원 유효; 원시 KRX open 1815원 / volume 102,239; 저장일과 listed shares 동일. 반대편 체결은 `2015-12-01` 그대로 유지.
- 014200 EXIT 2022-03-31: 신호 다음 exact KRX 세션 `2022-04-01` 확인; 조정시가 21,072원 유효; 원시 KRX open 3510원 / volume 2,845,048; 저장일과 listed shares 동일. 반대편 체결은 `2021-12-01` 그대로 유지.
- 078160 EXIT 2018-11-30: 신호 다음 exact KRX 세션 `2018-12-03` 확인; 조정시가 36,909원 유효; 원시 KRX open 83200원 / volume 71,631; 저장일과 listed shares 동일. 반대편 체결은 `2018-11-01` 그대로 유지.
- P1: 기존 공식 event stream의 실행 체결 881건 중 다음 exact KRX 세션 위반 0건 (`PASS`).
- P2-1: 기존 공식 event stream의 실행 체결 350건 중 다음 exact KRX 세션 위반 0건 (`PASS`).
- P2-2: 기존 공식 event stream의 실행 체결 470건 중 다음 exact KRX 세션 위반 0건 (`PASS`).
- P3-1: 기존 공식 event stream의 실행 체결 275건 중 다음 exact KRX 세션 위반 0건 (`PASS`).
- P3-2: 기존 공식 event stream의 실행 체결 388건 중 다음 exact KRX 세션 위반 0건 (`PASS`).

## 공식 채택 기준, CONTROL, 과거 산출물

- 기존 V03 원판은 MDD closure 전 `HOLD`였고, 기존 공식 MDD closure V01은 정규화 전 `OFFICIAL_STRATEGY_ADOPTED`, 이번 영향 판정 후 `OFFICIAL_STRATEGY_ADOPTED`로 유지된다. 다섯 window의 Gate A–E는 모두 PASS다.
- 현행 portfolio CONTROL로 공식 V03/MDD closure baseline을 그대로 사용할 수 있다. 포함된 체결 전부가 다음 exact KRX 세션이며, 이번 7건은 portfolio에 포함되지 않는다. 별도 normalized portfolio baseline은 만들 필요가 없다.
- 공식 portfolio 산출물 remediation은 필요하지 않다. 기존 source ledger는 legacy 보존본으로 둔다. 단, 원본 ledger 거래 수익률을 별도 화면/분석에 노출한다면 본 7건 sensitivity 표를 함께 참조해야 한다.
- P3-1/P3-2의 source ledger 및 공식 portfolio event 노출은 모두 0건이다. 이 window들은 재생하지 않았다.

## 재현 범위

- 신호 생성·전체 backtest·production 변경은 수행하지 않았다. 현재 Naver 조정 시계열 7종목, exact KRX calendar, 14개 stored/next KRX raw snapshot만 읽었다. raw partitions는 manifest hash 검증을 거쳤다.
- 공식 portfolio 지표의 after 값은 새로 계산한 값이 아니다. 대상 event key가 0건임을 확인했으므로 각 before 값을 동일하게 유지했다. 제외 identity를 되살리는 재생은 하지 않았다.
- 별도 탐색성 current-authority P1 baseline 재생은 공식 event/cash 및 closure parity에 실패해 폐기했다. 그 재생의 원인과 성과 수치는 정규화 영향 판정에 사용하지 않았다.
- 원본 공식 산출물은 수정하지 않았다. 자세한 수치와 hash는 같은 폴더의 CSV/JSON에 저장했다.
