# B Select Daily Exit MDD Coverage 원인 감사 V01

- 판정: **`B_SELECT_MDD_COVERAGE_REMEDIATION_DECISION_REQUIRED`**
- 기준 HEAD / origin/main: `c0840955d85d9641394367b02d8b6027944388d8` / `c0840955d85d9641394367b02d8b6027944388d8`
- MDD 원장 전체 15,098 window×scenario 거래일 중 미확정 equity 6,454행 (42.75%).
- missing mark 8,304행, exact identity 24개, KRX raw market/date partition 1,773개(결측 원장 1,753 + carry 기준일 20)를 manifest로 검증했어.
- 비거래 placeholder: 8,304/8,304; valuation-only 직전 종가 적용 진단 가능: 8,304/8,304 marks.
- 최신 rolling KRX basic-info: 2026-09-11; PIT frontier: 2026-10-02.
- 작업 범위는 원인 감사와 무변경 진단 계산이야. 전략, production, 공식 history, 중앙 영구 제외 authority와 기존 cadence 산출물은 고치지 않았어.
- 이 분석은 봉인된 cadence replay의 missing marks를 사후 분해했어. 백테스트나 portfolio engine을 다시 실행하지 않았어.

## 레벨

| 레벨 | 개수 |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 1 |
| MINOR | 0 |

## 1. Coverage gap 전체 요약

각 기간의 missing day를 일별 equity 행, open-position 수, `MISSING_EXACT_DAILY_MARK` skip 원장으로 1:1 대조했어.

| Window | 방식 | 전체 거래일 | 미확정 equity 일 | 현금-only 누락 | 보유+missing mark | 보유+skip 없는 누락 | 대조 |
|---|---|---:|---:|---:|---:|---:|---|
| P1 | CONTROL_MONTH_END | 3107 | 1472 | 0 | 1472 | 0 | PASS |
| P1 | TEST_DAILY | 3107 | 1454 | 0 | 1454 | 0 | PASS |
| P2-1 | CONTROL_MONTH_END | 1082 | 398 | 0 | 398 | 0 | PASS |
| P2-1 | TEST_DAILY | 1082 | 397 | 0 | 397 | 0 | PASS |
| P2-2 | CONTROL_MONTH_END | 1387 | 486 | 0 | 486 | 0 | PASS |
| P2-2 | TEST_DAILY | 1387 | 485 | 0 | 485 | 0 | PASS |
| P3-1 | CONTROL_MONTH_END | 834 | 397 | 0 | 397 | 0 | PASS |
| P3-1 | TEST_DAILY | 834 | 396 | 0 | 396 | 0 | PASS |
| P3-2 | CONTROL_MONTH_END | 1139 | 485 | 0 | 485 | 0 | PASS |
| P3-2 | TEST_DAILY | 1139 | 484 | 0 | 484 | 0 | PASS |

현금-only 누락은 0일, missing mark 없이 equity만 빠진 날은 0일이야. 따라서 빈 포트폴리오의 cash valuation 누락이나 skip과 무관한 equity-row 생성 누락은 이 원장에서 발견되지 않았어.

## 2. 원인별 기여도

같은 날 여러 identity가 미평가일 수 있어 원인별 missing-day 수와 비율은 **비가산**이야. 표의 marks는 exact identity/date 행 수야.

| Window | 방식 | 원인 | 영향 missing days | 전체 거래일 | 비율 | missing marks | identity 수 |
|---|---|---|---:|---:|---:|---:|---:|
| P1 | CONTROL_MONTH_END | TRADING_SUSPENDED_OR_NON_TRADING | 1472 | 3107 | 47.38% | 2280 | 24 |
| P1 | TEST_DAILY | TRADING_SUSPENDED_OR_NON_TRADING | 1454 | 3107 | 46.80% | 2214 | 17 |
| P2-1 | CONTROL_MONTH_END | TRADING_SUSPENDED_OR_NON_TRADING | 398 | 1082 | 36.78% | 410 | 4 |
| P2-1 | TEST_DAILY | TRADING_SUSPENDED_OR_NON_TRADING | 397 | 1082 | 36.69% | 409 | 3 |
| P2-2 | CONTROL_MONTH_END | TRADING_SUSPENDED_OR_NON_TRADING | 486 | 1387 | 35.04% | 574 | 14 |
| P2-2 | TEST_DAILY | TRADING_SUSPENDED_OR_NON_TRADING | 485 | 1387 | 34.97% | 525 | 10 |
| P3-1 | CONTROL_MONTH_END | TRADING_SUSPENDED_OR_NON_TRADING | 397 | 834 | 47.60% | 409 | 3 |
| P3-1 | TEST_DAILY | TRADING_SUSPENDED_OR_NON_TRADING | 396 | 834 | 47.48% | 408 | 2 |
| P3-2 | CONTROL_MONTH_END | TRADING_SUSPENDED_OR_NON_TRADING | 485 | 1139 | 42.58% | 562 | 12 |
| P3-2 | TEST_DAILY | TRADING_SUSPENDED_OR_NON_TRADING | 484 | 1139 | 42.49% | 513 | 8 |

## 3. 영향도 상위 exact identity

영향도는 5 window × 2 scenario에 반복해 기록된 exact missing mark 수 기준이야. window 간 중복을 포함하므로 독립 거래 수는 아니야.

| ticker | ISU_CD | 최신 KRX 종목명 | 원인 | 최초/마지막 결측일 | missing marks | 전체 gap 비중 | 최대 연속 거래일 | 영향 window | exclusion |
|---|---|---|---|---|---:|---:|---:|---|---|
| 019490 | KR7019490002 | 엑시큐어하이트론 | TRADING_SUSPENDED_OR_NON_TRADING | 2022-03-29 / 2024-09-24 | 3960 | 47.69% | 394 | P1|P2-1|P2-2|P3-1|P3-2 | NO |
| 066790 | KR7066790007 | 씨씨에스 | TRADING_SUSPENDED_OR_NON_TRADING | 2018-07-09 / 2021-04-09 | 1358 | 16.35% | 679 | P1 | NO |
| 103230 | KR7103230009 | 에스앤더블류 | TRADING_SUSPENDED_OR_NON_TRADING | 2021-02-16 / 2023-03-27 | 1046 | 12.60% | 523 | P1 | NO |
| 083660 | KR7083660001 | CSA 코스믹 | TRADING_SUSPENDED_OR_NON_TRADING | 2019-02-14 / 2022-12-15 | 844 | 10.16% | 392 | P1 | NO |
| 032680 | KR7032680001 | 소프트센 | TRADING_SUSPENDED_OR_NON_TRADING | 2023-04-14 / 2023-05-02 | 120 | 1.45% | 12 | P1|P2-1|P2-2|P3-1|P3-2 | NO |
| 001380 | KR7001380005 | SG글로벌 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-04-10 / 2026-05-08 | 114 | 1.37% | 19 | P1|P2-2|P3-2 | NO |
| 007720 | KR7007720006 | 소노스퀘어 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-06-17 / 2026-07-13 | 114 | 1.37% | 19 | P1|P2-2|P3-2 | NO |
| 023760 | KR7023760002 | 한국캐피탈 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-07-30 / 2026-08-26 | 114 | 1.37% | 19 | P1|P2-2|P3-2 | NO |
| 105550 | KR7105550008 | 엣지파운드리 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-07-21 / 2026-08-11 | 96 | 1.16% | 16 | P1|P2-2|P3-2 | NO |
| 227610 | KR7227610003 | 아우딘퓨쳐스 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-05-04 / 2026-05-27 | 96 | 1.16% | 16 | P1|P2-2|P3-2 | NO |
| 900250 | KYG2115T1076 | 크리스탈신소재 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-05-29 / 2026-06-22 | 96 | 1.16% | 16 | P1|P2-2|P3-2 | NO |
| 019570 | KR7019570001 | GMI벤처 | TRADING_SUSPENDED_OR_NON_TRADING | 2017-05-16 / 2017-07-06 | 74 | 0.89% | 37 | P1 | NO |
| 011080 | KR7011080009 | 형지I&C | TRADING_SUSPENDED_OR_NON_TRADING | 2026-04-10 / 2026-05-06 | 51 | 0.61% | 17 | P1|P2-2|P3-2 | NO |
| 234100 | KR7234100006 | 폴라리스세원 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-04-29 / 2026-05-22 | 48 | 0.58% | 16 | P1|P2-2|P3-2 | NO |
| 096630 | KR7096630009 | 에스코넥 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-04-13 / 2026-05-04 | 45 | 0.54% | 15 | P1|P2-2|P3-2 | NO |
| 069640 | KR7069640001 | 한세엠케이 | TRADING_SUSPENDED_OR_NON_TRADING | 2026-04-24 / 2026-05-12 | 44 | 0.53% | 11 | P1|P2-2 | NO |
| 073570 | KR7073570004 | 리튬포어스 | TRADING_SUSPENDED_OR_NON_TRADING | 2017-10-26 / 2017-11-14 | 28 | 0.34% | 14 | P1 | NO |
| 123010 | KR7123010001 | MSDI | TRADING_SUSPENDED_OR_NON_TRADING | 2020-04-01 / 2020-04-16 | 22 | 0.26% | 11 | P1 | NO |
| 001000 | KR7001000009 | 신라섬유 | TRADING_SUSPENDED_OR_NON_TRADING | 2016-03-15 / 2016-03-31 | 13 | 0.16% | 13 | P1 | NO |
| 121850 | KR7121850002 | 코이즈 | TRADING_SUSPENDED_OR_NON_TRADING | 2021-12-21 / 2021-12-21 | 6 | 0.07% | 1 | P1|P2-1|P2-2 | NO |
| 900100 | USU652221081 | 파이온엑스 | TRADING_SUSPENDED_OR_NON_TRADING | 2017-12-06 / 2018-01-23 | 6 | 0.07% | 1 | P1 | NO |
| 015020 | KR7015020001 | 이스타코 | TRADING_SUSPENDED_OR_NON_TRADING | 2024-12-12 / 2024-12-12 | 5 | 0.06% | 1 | P1|P2-1|P2-2|P3-1|P3-2 | NO |
| 023790 | KR7023790009 | 동일스틸럭스 | TRADING_SUSPENDED_OR_NON_TRADING | 2025-09-04 / 2025-09-10 | 2 | 0.02% | 1 | P1 | NO |
| 093240 | KR7093240000 | 형지엘리트 | TRADING_SUSPENDED_OR_NON_TRADING | 2016-04-14 / 2016-04-21 | 2 | 0.02% | 1 | P1 | NO |

아래는 전체 24 identity의 window/scenario별 세부값이야. 보유 거래일은 봉인 ENTRY/EXIT execution event 사이에서 exact identity 포지션이 열린 KRX 거래일 수로 계산했고, 전체 행은 `identity_impact.csv`에도 저장했어.

| ticker | ISU_CD | Window | 방식 | 최초/마지막 결측일 | 고유 결측일 | 최대 연속 거래일 | 해당 범위 보유 거래일 | 범위 missing mark 비중 |
|---|---|---|---|---|---:|---:|---:|---:|
| 001000 | KR7001000009 | P1 | CONTROL_MONTH_END | 2016-03-15 / 2016-03-31 | 13 | 13 | 123 | 0.57% |
| 001380 | KR7001380005 | P1 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-08 | 19 | 19 | 388 | 0.83% |
| 001380 | KR7001380005 | P1 | TEST_DAILY | 2026-04-10 / 2026-05-08 | 19 | 19 | 355 | 0.86% |
| 001380 | KR7001380005 | P2-2 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-08 | 19 | 19 | 366 | 3.31% |
| 001380 | KR7001380005 | P2-2 | TEST_DAILY | 2026-04-10 / 2026-05-08 | 19 | 19 | 347 | 3.62% |
| 001380 | KR7001380005 | P3-2 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-08 | 19 | 19 | 324 | 3.38% |
| 001380 | KR7001380005 | P3-2 | TEST_DAILY | 2026-04-10 / 2026-05-08 | 19 | 19 | 324 | 3.70% |
| 007720 | KR7007720006 | P1 | CONTROL_MONTH_END | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 0.83% |
| 007720 | KR7007720006 | P1 | TEST_DAILY | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 0.86% |
| 007720 | KR7007720006 | P2-2 | CONTROL_MONTH_END | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 3.31% |
| 007720 | KR7007720006 | P2-2 | TEST_DAILY | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 3.62% |
| 007720 | KR7007720006 | P3-2 | CONTROL_MONTH_END | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 3.38% |
| 007720 | KR7007720006 | P3-2 | TEST_DAILY | 2026-06-17 / 2026-07-13 | 19 | 19 | 203 | 3.70% |
| 011080 | KR7011080009 | P1 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-06 | 17 | 17 | 305 | 0.75% |
| 011080 | KR7011080009 | P2-2 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-06 | 17 | 17 | 286 | 2.96% |
| 011080 | KR7011080009 | P3-2 | CONTROL_MONTH_END | 2026-04-10 / 2026-05-06 | 17 | 17 | 286 | 3.02% |
| 015020 | KR7015020001 | P1 | CONTROL_MONTH_END | 2024-12-12 / 2024-12-12 | 1 | 1 | 715 | 0.04% |
| 015020 | KR7015020001 | P2-1 | CONTROL_MONTH_END | 2024-12-12 / 2024-12-12 | 1 | 1 | 715 | 0.24% |
| 015020 | KR7015020001 | P2-2 | CONTROL_MONTH_END | 2024-12-12 / 2024-12-12 | 1 | 1 | 715 | 0.17% |
| 015020 | KR7015020001 | P3-1 | CONTROL_MONTH_END | 2024-12-12 / 2024-12-12 | 1 | 1 | 715 | 0.24% |
| 015020 | KR7015020001 | P3-2 | CONTROL_MONTH_END | 2024-12-12 / 2024-12-12 | 1 | 1 | 715 | 0.18% |
| 019490 | KR7019490002 | P1 | CONTROL_MONTH_END | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 17.37% |
| 019490 | KR7019490002 | P1 | TEST_DAILY | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 17.89% |
| 019490 | KR7019490002 | P2-1 | CONTROL_MONTH_END | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 96.59% |
| 019490 | KR7019490002 | P2-1 | TEST_DAILY | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 96.82% |
| 019490 | KR7019490002 | P2-2 | CONTROL_MONTH_END | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 68.99% |
| 019490 | KR7019490002 | P2-2 | TEST_DAILY | 2022-03-29 / 2024-09-24 | 396 | 394 | 677 | 75.43% |
| 019490 | KR7019490002 | P3-1 | CONTROL_MONTH_END | 2022-03-29 / 2024-09-24 | 396 | 394 | 636 | 96.82% |
| 019490 | KR7019490002 | P3-1 | TEST_DAILY | 2022-03-29 / 2024-09-24 | 396 | 394 | 636 | 97.06% |
| 019490 | KR7019490002 | P3-2 | CONTROL_MONTH_END | 2022-03-29 / 2024-09-24 | 396 | 394 | 636 | 70.46% |
| 019490 | KR7019490002 | P3-2 | TEST_DAILY | 2022-03-29 / 2024-09-24 | 396 | 394 | 636 | 77.19% |
| 019570 | KR7019570001 | P1 | CONTROL_MONTH_END | 2017-05-16 / 2017-07-06 | 37 | 37 | 464 | 1.62% |
| 019570 | KR7019570001 | P1 | TEST_DAILY | 2017-05-16 / 2017-07-06 | 37 | 37 | 464 | 1.67% |
| 023760 | KR7023760002 | P1 | CONTROL_MONTH_END | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 0.83% |
| 023760 | KR7023760002 | P1 | TEST_DAILY | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 0.86% |
| 023760 | KR7023760002 | P2-2 | CONTROL_MONTH_END | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 3.31% |
| 023760 | KR7023760002 | P2-2 | TEST_DAILY | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 3.62% |
| 023760 | KR7023760002 | P3-2 | CONTROL_MONTH_END | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 3.38% |
| 023760 | KR7023760002 | P3-2 | TEST_DAILY | 2026-07-30 / 2026-08-26 | 19 | 19 | 42 | 3.70% |
| 023790 | KR7023790009 | P1 | CONTROL_MONTH_END | 2025-09-04 / 2025-09-10 | 2 | 1 | 734 | 0.09% |
| 032680 | KR7032680001 | P1 | CONTROL_MONTH_END | 2023-04-14 / 2023-05-02 | 12 | 12 | 61 | 0.53% |
| 032680 | KR7032680001 | P1 | TEST_DAILY | 2023-04-14 / 2023-05-02 | 12 | 12 | 21 | 0.54% |
| 032680 | KR7032680001 | P2-1 | CONTROL_MONTH_END | 2023-04-14 / 2023-05-02 | 12 | 12 | 61 | 2.93% |
| 032680 | KR7032680001 | P2-1 | TEST_DAILY | 2023-04-14 / 2023-05-02 | 12 | 12 | 21 | 2.93% |
| 032680 | KR7032680001 | P2-2 | CONTROL_MONTH_END | 2023-04-14 / 2023-05-02 | 12 | 12 | 61 | 2.09% |
| 032680 | KR7032680001 | P2-2 | TEST_DAILY | 2023-04-14 / 2023-05-02 | 12 | 12 | 21 | 2.29% |
| 032680 | KR7032680001 | P3-1 | CONTROL_MONTH_END | 2023-04-14 / 2023-05-02 | 12 | 12 | 61 | 2.93% |
| 032680 | KR7032680001 | P3-1 | TEST_DAILY | 2023-04-14 / 2023-05-02 | 12 | 12 | 21 | 2.94% |
| 032680 | KR7032680001 | P3-2 | CONTROL_MONTH_END | 2023-04-14 / 2023-05-02 | 12 | 12 | 61 | 2.14% |
| 032680 | KR7032680001 | P3-2 | TEST_DAILY | 2023-04-14 / 2023-05-02 | 12 | 12 | 21 | 2.34% |
| 066790 | KR7066790007 | P1 | CONTROL_MONTH_END | 2018-07-09 / 2021-04-09 | 679 | 679 | 1557 | 29.78% |
| 066790 | KR7066790007 | P1 | TEST_DAILY | 2018-07-09 / 2021-04-09 | 679 | 679 | 1551 | 30.67% |
| 069640 | KR7069640001 | P1 | CONTROL_MONTH_END | 2026-04-24 / 2026-05-12 | 11 | 11 | 1202 | 0.48% |
| 069640 | KR7069640001 | P1 | TEST_DAILY | 2026-04-24 / 2026-05-12 | 11 | 11 | 1202 | 0.50% |
| 069640 | KR7069640001 | P2-2 | CONTROL_MONTH_END | 2026-04-24 / 2026-05-12 | 11 | 11 | 1202 | 1.92% |
| 069640 | KR7069640001 | P2-2 | TEST_DAILY | 2026-04-24 / 2026-05-12 | 11 | 11 | 1202 | 2.10% |
| 073570 | KR7073570004 | P1 | CONTROL_MONTH_END | 2017-10-26 / 2017-11-14 | 14 | 14 | 347 | 0.61% |
| 073570 | KR7073570004 | P1 | TEST_DAILY | 2017-10-26 / 2017-11-14 | 14 | 14 | 347 | 0.63% |
| 083660 | KR7083660001 | P1 | CONTROL_MONTH_END | 2019-02-14 / 2022-12-15 | 422 | 392 | 1131 | 18.51% |
| 083660 | KR7083660001 | P1 | TEST_DAILY | 2019-02-14 / 2022-12-15 | 422 | 392 | 1131 | 19.06% |
| 093240 | KR7093240000 | P1 | CONTROL_MONTH_END | 2016-04-14 / 2016-04-21 | 2 | 1 | 674 | 0.09% |
| 096630 | KR7096630009 | P1 | CONTROL_MONTH_END | 2026-04-13 / 2026-05-04 | 15 | 15 | 424 | 0.66% |
| 096630 | KR7096630009 | P2-2 | CONTROL_MONTH_END | 2026-04-13 / 2026-05-04 | 15 | 15 | 424 | 2.61% |
| 096630 | KR7096630009 | P3-2 | CONTROL_MONTH_END | 2026-04-13 / 2026-05-04 | 15 | 15 | 424 | 2.67% |
| 103230 | KR7103230009 | P1 | CONTROL_MONTH_END | 2021-02-16 / 2023-03-27 | 523 | 523 | 804 | 22.94% |
| 103230 | KR7103230009 | P1 | TEST_DAILY | 2021-02-16 / 2023-03-27 | 523 | 523 | 804 | 23.62% |
| 105550 | KR7105550008 | P1 | CONTROL_MONTH_END | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 0.70% |
| 105550 | KR7105550008 | P1 | TEST_DAILY | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 0.72% |
| 105550 | KR7105550008 | P2-2 | CONTROL_MONTH_END | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 2.79% |
| 105550 | KR7105550008 | P2-2 | TEST_DAILY | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 3.05% |
| 105550 | KR7105550008 | P3-2 | CONTROL_MONTH_END | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 2.85% |
| 105550 | KR7105550008 | P3-2 | TEST_DAILY | 2026-07-21 / 2026-08-11 | 16 | 16 | 263 | 3.12% |
| 121850 | KR7121850002 | P1 | CONTROL_MONTH_END | 2021-12-21 / 2021-12-21 | 1 | 1 | 83 | 0.04% |
| 121850 | KR7121850002 | P1 | TEST_DAILY | 2021-12-21 / 2021-12-21 | 1 | 1 | 64 | 0.05% |
| 121850 | KR7121850002 | P2-1 | CONTROL_MONTH_END | 2021-12-21 / 2021-12-21 | 1 | 1 | 83 | 0.24% |
| 121850 | KR7121850002 | P2-1 | TEST_DAILY | 2021-12-21 / 2021-12-21 | 1 | 1 | 64 | 0.24% |
| 121850 | KR7121850002 | P2-2 | CONTROL_MONTH_END | 2021-12-21 / 2021-12-21 | 1 | 1 | 83 | 0.17% |
| 121850 | KR7121850002 | P2-2 | TEST_DAILY | 2021-12-21 / 2021-12-21 | 1 | 1 | 64 | 0.19% |
| 123010 | KR7123010001 | P1 | CONTROL_MONTH_END | 2020-04-01 / 2020-04-16 | 11 | 11 | 102 | 0.48% |
| 123010 | KR7123010001 | P1 | TEST_DAILY | 2020-04-01 / 2020-04-16 | 11 | 11 | 69 | 0.50% |
| 227610 | KR7227610003 | P1 | CONTROL_MONTH_END | 2026-05-04 / 2026-05-27 | 16 | 16 | 851 | 0.70% |
| 227610 | KR7227610003 | P1 | TEST_DAILY | 2026-05-04 / 2026-05-27 | 16 | 16 | 820 | 0.72% |
| 227610 | KR7227610003 | P2-2 | CONTROL_MONTH_END | 2026-05-04 / 2026-05-27 | 16 | 16 | 851 | 2.79% |
| 227610 | KR7227610003 | P2-2 | TEST_DAILY | 2026-05-04 / 2026-05-27 | 16 | 16 | 820 | 3.05% |
| 227610 | KR7227610003 | P3-2 | CONTROL_MONTH_END | 2026-05-04 / 2026-05-27 | 16 | 16 | 851 | 2.85% |
| 227610 | KR7227610003 | P3-2 | TEST_DAILY | 2026-05-04 / 2026-05-27 | 16 | 16 | 820 | 3.12% |
| 234100 | KR7234100006 | P1 | CONTROL_MONTH_END | 2026-04-29 / 2026-05-22 | 16 | 16 | 1038 | 0.70% |
| 234100 | KR7234100006 | P2-2 | CONTROL_MONTH_END | 2026-04-29 / 2026-05-22 | 16 | 16 | 1038 | 2.79% |
| 234100 | KR7234100006 | P3-2 | CONTROL_MONTH_END | 2026-04-29 / 2026-05-22 | 16 | 16 | 1038 | 2.85% |
| 900100 | USU652221081 | P1 | CONTROL_MONTH_END | 2017-12-06 / 2018-01-23 | 3 | 1 | 634 | 0.13% |
| 900100 | USU652221081 | P1 | TEST_DAILY | 2017-12-06 / 2018-01-23 | 3 | 1 | 591 | 0.14% |
| 900250 | KYG2115T1076 | P1 | CONTROL_MONTH_END | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 0.70% |
| 900250 | KYG2115T1076 | P1 | TEST_DAILY | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 0.72% |
| 900250 | KYG2115T1076 | P2-2 | CONTROL_MONTH_END | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 2.79% |
| 900250 | KYG2115T1076 | P2-2 | TEST_DAILY | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 3.05% |
| 900250 | KYG2115T1076 | P3-2 | CONTROL_MONTH_END | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 2.85% |
| 900250 | KYG2115T1076 | P3-2 | TEST_DAILY | 2026-05-29 / 2026-06-22 | 16 | 16 | 689 | 3.12% |

상위 1/3/5 identity가 전체 missing valuation marks의 47.69% / 76.64% / 88.25%를 차지해.

## 4. P1 1,310일 연속 결측

| 방식 | 시작 | 끝 | 최대 연속 거래일 | 구간 내 미평가 identity 기여 marks |
|---|---|---|---:|---|
| CONTROL_MONTH_END | 2018-07-09 | 2023-10-31 | 1310 | 066790:KR7066790007(679)|103230:KR7103230009(523)|083660:KR7083660001(422)|019490:KR7019490002(394)|032680:KR7032680001(12)|123010:KR7123010001(11)|121850:KR7121850002(1) |
| TEST_DAILY | 2018-07-09 | 2023-10-31 | 1310 | 066790:KR7066790007(679)|103230:KR7103230009(523)|083660:KR7083660001(422)|019490:KR7019490002(394)|032680:KR7032680001(12)|123010:KR7123010001(11)|121850:KR7121850002(1) |

이 구간은 단일 identity 1개가 1,310일 지속된 것이 아니라, 결측 기간이 겹치는 비거래 identity들이 구간을 이어 붙인 형태인지 표의 contributor를 기준으로 구분했어.

## 5. P2/P3 394일 결측

| Window | 방식 | 시작 | 끝 | 최대 연속 거래일 | 구간 내 기여 identity |
|---|---|---|---|---:|---|
| P2-1 | CONTROL_MONTH_END | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P2-1 | TEST_DAILY | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P2-2 | CONTROL_MONTH_END | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P2-2 | TEST_DAILY | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P3-1 | CONTROL_MONTH_END | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P3-1 | TEST_DAILY | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P3-2 | CONTROL_MONTH_END | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |
| P3-2 | TEST_DAILY | 2022-03-29 | 2023-10-31 | 394 | 019490:KR7019490002(394)|032680:KR7032680001(12) |

## 6–8. 상장상태·제외정책·equity 생성

- missing mark exact identity는 24개야. 각 identity의 같은 ticker·ISU COMMON PIT interval과 최신 KRX basic-info 등재 여부를 identity CSV에 저장했어. 상폐·successor는 PIT/기본정보가 뒷받침할 때만 분류했고, 이름이나 ticker만으로 추정하지 않았어.
- 중앙 영구 제외 authority는 174개 identity야. 봉인 replay의 exclusion authority SHA-256과 현재 파일은 일치해. 감사 대상과 겹친 exact identity/mark는 0개/0건이야. 과거 RAW_DATA_GAP 제외 115개, terminal/delisting 제외 3개, successor-resolution 제외 7개 중 다시 나타난 identity는 각각 0/0/0개야. 자동 exclusion은 하지 않았어.
- 빈 equity일 6,454행은 모두 보유 포지션과 missing mark에 대응하고, cash-only 누락과 skip 없는 equity 누락은 0이야. portfolio equity 생성 버그는 발견되지 않았어.
- KRX raw 행은 `KRX_RAW_STOCK_V01` manifest의 file/content SHA-256과 schema를 검증했어. 정확한 0-OHLC placeholder에 volume/trading value 0, close>0, listed shares>0이면 KRX 일별 원장상 비거래로만 분류했어. 공시 원인·법적 거래정지 사유는 별도 원문이 확인되지 않으면 추정하지 않았어.

## 9. 변경 없는 coverage 시나리오

시나리오 B는 모든 미평가 포지션이 exact KRX 비거래 placeholder이고, 같은 identity의 직전 exact KRX session에 거래된 정상 Repository V2 adjusted close가 있을 때만 valuation-only carry를 계산했어. 거래신호·체결·지표에는 적용하지 않았어.
시나리오 C는 현재 산출물이 이미 174개 중앙 exclusion을 적용했고 missing mark leakage가 0이어서 현재 coverage와 같아. exclusion이 뒤늦게 필요한 행은 발견되지 않았어.

| Window | 방식 | 총일수 | A 현재 coverage | B carry 회복일 | B 예상 coverage | C 제외 회복일 | C 예상 coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL_MONTH_END | 3107 | 52.62% | 1472 | 100.00% | 0 | 52.62% |
| P1 | TEST_DAILY | 3107 | 53.20% | 1454 | 100.00% | 0 | 53.20% |
| P2-1 | CONTROL_MONTH_END | 1082 | 63.22% | 398 | 100.00% | 0 | 63.22% |
| P2-1 | TEST_DAILY | 1082 | 63.31% | 397 | 100.00% | 0 | 63.31% |
| P2-2 | CONTROL_MONTH_END | 1387 | 64.96% | 486 | 100.00% | 0 | 64.96% |
| P2-2 | TEST_DAILY | 1387 | 65.03% | 485 | 100.00% | 0 | 65.03% |
| P3-1 | CONTROL_MONTH_END | 834 | 52.40% | 397 | 100.00% | 0 | 52.40% |
| P3-1 | TEST_DAILY | 834 | 52.52% | 396 | 100.00% | 0 | 52.52% |
| P3-2 | CONTROL_MONTH_END | 1139 | 57.42% | 485 | 100.00% | 0 | 57.42% |
| P3-2 | TEST_DAILY | 1139 | 57.51% | 484 | 100.00% | 0 | 57.51% |

## 10. 최소 remediation 제안

전 기간 공통 forward-fill이나 새 permanent exclusion, lifecycle 엔진 수정을 제안하지 않아. KRX 원장에서 정밀하게 확인된 비거래 날짜에 한해서 동일 identity의 직전 정상 종가를 portfolio valuation에만 유지하는 좁은 규칙을 사용자 승인 후 진단 재구성에 적용하는 안이 최소 범위야. 승인 전에는 이번 보고의 시나리오 B가 진단치로만 남아.
- 직전 정상 종가가 검증되지 않은 raw gap·identity gap은 `UNRESOLVED`로 유지해야 해.
- 해당 identity 추가 영구 제외는 현재 자료로 지지되지 않아. 중앙 exclusion authority는 수정하지 않았어.
- 기존 봉인 거래 이벤트를 사용해 valuation/equity만 재구성한 뒤 coverage/MDD gate를 재판정하면 돼. 전략은 재백테스트하지 않아.

## Git / 검증

- 기준 저장소: `c0840955d85d9641394367b02d8b6027944388d8` / `origin/main` `c0840955d85d9641394367b02d8b6027944388d8`.
- 유효 KRX raw partition 검증: 1,773개; 실패 0개.
- root/window replay manifest 및 adjusted file SHA-256 검증 결과는 `input_verification.json`에 있어.
- 산출물: `missing_valuation_days.csv`, `missing_identity_marks.csv`, `identity_impact.csv`, `cause_contribution.csv`, `scenario_coverage.csv`, `day_classification.csv`, `top_identity_shares.csv`, `longest_missing_streaks.csv`, `raw_partition_audit.csv`, `summary.json`.
