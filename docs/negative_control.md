# Negative Control Validation v0.1

## 상태

Historical Snapshot Validation v0.1까지는 "나중에 크게 오른 종목"의
pre_breakout/early_trend/trend_progressed 구조만 봤다. 이 문서가 다루는
Negative Control Validation은 반대로, 당시에는 비슷하게 좋아 보였지만
상승이 이어지지 않았거나 돌파에 실패했거나 다시 하락한 사례를 모아서
false positive 가능성을 확인한다. Pattern A 점수/가중치/threshold/Hard
Filter는 여전히 만들지 않는다.

## 핵심 원칙: 미래 가격은 라벨링에만, Feature 계산에는 절대 사용 금지

Negative Control 사례를 고르려면 "그 이후 정말 실패했는지" 확인해야 하고,
이건 snapshot_date 이후의 가격을 보지 않고는 판단할 수 없다. 하지만 이건
**라벨(사람이 이해하기 위한 문자열)을 정하는 데만** 쓴다.

Feature 계산은 지금까지와 완전히 동일한 경로를 탄다.
`build_historical_snapshot()`이 `daily[daily.index <= snapshot_date]`로
자른 데이터만 `build_feature_row()`에 넘기므로, 미래 가격이 Feature 계산에
섞여 들어가는 경로는 존재하지 않는다. "실패를 미리 알고 있었다"는 정보는
라벨 문자열 하나에만 담기고, 숫자 계산에는 전혀 반영되지 않는다.

날짜 선정도 같은 원칙을 지킨다: monthly raw close(파생 Feature 아님)만
보고 "당시엔 상승할 것처럼 보였던 시점"을 먼저 고정한 뒤, 그 이후 가격이
실제로 어떻게 됐는지 확인해서 라벨만 붙였다. Feature 값(`ma24_slope`,
`ma_spread`, `compression_ratio`, `weekly_ma12_slope` 등)은 날짜를 고정하기
전까지 전혀 조회하지 않았다.

## 세트 구성

`data/processed/historical_snapshots.csv`의 `set` 컬럼으로 세 세트를
구분한다.

* `exploration`: 068270/035420/005930/000660. Feature 값을 보고 날짜를
  골라서 선택 편향이 있다. 참고용으로만 CSV에 남긴다.
* `holdout`: 005380/051910/000270/006400/012330. raw close만 보고 날짜를
  고정했다. **핵심 positive 비교 기준**(`pre_breakout`/`early_trend`)은
  이 세트에서만 가져온다.
* `negative_control`: 003550/010130/011170/009150/018260/032830/034730/
  011200. raw close만 보고 "당시 좋아 보였지만 실패한 시점"을 골랐다.

## Negative Control 사례

| 종목 | 날짜 | label | 선정 근거(raw close만 근거) |
|---|---|---|---|
| 003550 LG | 2020-12-31 | failed_breakout | 2018~2020 장기 박스권(53k~86k) 이후 신고가 돌파(82,658). 하지만 이후 4개월 만에 119,500까지 더 오르다 그대로 반전해 2025년까지 74k~95k 박스에 재갇힘 |
| 010130 고려아연 | 2022-06-30 | failed_breakout | 2018~2022 박스권(356k~595k) 중 상단 근접 시점. 다음 달(2022-08) 672,000까지 급등했지만 곧바로 477,500으로 반락, 이후 1년 넘게 박스 재진입 |
| 011170 롯데케미칼 | 2023-01-31 | failed_higher_low | 2022-09 저점(137,161) 대비 반등 중이던 시점(176,800). 2023-03 190,800까지 더 오르다 반전해 2026년까지 지속 하락(56,700까지) — 저점 반등이 장기 추세로 이어지지 못함 |
| 009150 삼성전기 | 2022-12-31 | failed_momentum | 2022-09 저점(112,000) 이후 반등 중(130,500). 이후 152,700(2023-03)까지 오르다 다시 124,300(2023-10)까지 밀림 — 단기 반등이 장기 추세로 안 이어짐 |
| 018260 삼성에스디에스 | 2023-07-31 | failed_breakout | 장기 하락(2018 256k→2022 115k) 후 반등 초입처럼 보이던 시점(128,300). 2023-11 168,400까지 올랐지만 2024-12 127,800까지 재하락 — 반등분을 1년 만에 반납 |
| 032830 삼성생명 | 2021-02-28 | failed_ma24_turn | 2020-03 COVID 저점(43,000)에서 반등 중이던 시점(75,000, +74%). 2021-05 83,800까지 더 오르다 반전해 2021-11 59,800까지 밀리고, 2024년 전까지 62k~73k 박스에서 벗어나지 못함 |
| 034730 SK | 2020-12-31 | failed_weekly_turn | 다년 박스권(2016~2020, 140k~330k) 중 신고가 근접 시점(240,500). 2021-01 311,000으로 그 박스권 상단을 뚫었지만 그대로 4년 넘게 재하락(2025-03 129,600까지) — 그 311,000이 4년간 고점으로 남음 |
| 011200 HMM | 2024-10-31 | failed_breakout | 2021년 급등(3,100→47,900) 이후 형성된 다년 박스권(2022~2026, 약 14k~24k) 안에서 반등 시도 초입 시점(17,120). 2025-07 23,450까지 올랐지만 2026-06 18,610까지 재하락 — 박스권을 못 벗어남 |

카카오(035720)는 조회 시 다음 위반으로 제외했다(provider의 1원 이내
보정 정책을 이번 스코프에서 확장하지 않았기 때문).

* 날짜: 2018-05-16
* 원본 값: open=22981, high=23481, low=22780, close=23483
* 위반 종류: `high(23481) < close(23483)`, 차이 2원 — 1원 보정 임계값을
  초과해 provider가 손대지 않고 그대로 뒀고, `validate_ohlcv`가
  `MarketDataError`로 거부했다.

나머지 8종목은 전부 `validate_ohlcv` 통과, 새로 발견된 데이터 품질
문제는 없다.

## 조건 비교

`src/trend_scanner/validation/negative_control_analysis.py`가 그룹별
min/median/max와 단일/조합 조건 발생 비율(k/n, %)을 계산한다. 계산과 출력을
분리하는 기존 원칙을 그대로 따른다 — 이 모듈은 계산만 하고,
`scripts/negative_control_validate.py`가 CSV/표 출력을 담당한다.

비교 대상 조건(15번 항목 Combination A~E 그대로):

* 단일: `weekly_ma12_slope>0`, `ma24_slope>0`, `ma24_slope_acceleration>0`
* A: `weekly_ma12_slope>0 & ma24_slope<=0`
* B: `weekly_ma12_slope>0 & ma24_slope_acceleration>0`
* C: `weekly_ma12_slope>0 & range_position<0.6`
* D: `ma24_slope>0 & ma24_slope_acceleration>0`
* E: `weekly_ma12_slope>0 & ma24_slope>0 & ma24_slope_acceleration>0`

threshold를 확정하거나 가중치를 매기지 않는다 — "지금 후보로 거론되는
조건이 실패 사례에서 얼마나 자주도 나타나는가"만 관찰한다. 실제 수치와
해석은 완료 보고에 정리한다.
