# ETF-36 Realistic Portfolio — A FAST Core V2 vs Julia V00 — 15M / 25M V01

**Verdict:** `ETF_36_REALISTIC_PORTFOLIO_AFAST_V2_VS_JULIA_15M_25M_PASS`

## Authority and execution contract

- Input: certified clean-eligibility closure ledger (505 trades), frozen effective spans, official ETF universe (36). No signal regeneration or clean-ready recalculation.
- Portfolio matrix: 5 standard windows × 2 strategies × 2 position caps = 20 results; initial equity is 250,000,000 KRW in every result; worker count is 10.
- The reused realistic engine keeps integer-share fills, no partial buys, no leverage, no concurrent position cap, deterministic ticker/ISU/signal/entry ordering, exits before entries, same-session sale proceeds reusable, and full-size cash-shortage `CASH_SKIP`.
- Existing cost contract: buy/sell commission 0.0150% each side; buy/sell slippage 0.10% each side; ETF sell tax 0.00%. No new tax rule.
- Local raw ETF daily closes value positions through each cutoff. Realized exits on the execution-support session use its open. Remaining open positions retain the exact cutoff close on the support-date curve, with no hypothetical exit costs.
- 15M vs 25M is position-sizing sensitivity only. This report makes no strategy-adoption decision.

## Four-case comparison by window

Each cell reports final equity / CAGR / MDD / CASH_SKIP count and rate / average capital utilization / mean and median holding sessions.

| Window | A FAST / 15M | Julia / 15M | A FAST / 25M | Julia / 25M |
|---|---|---|---|---|
| P1 | 479,513,497 KRW / 5.28% / -21.17% / 10 (12.05%) / 45.96% / 356.3 / 194.0 sess | 545,580,535 KRW / 6.36% / -30.12% / 7 (13.46%) / 51.11% / 751.2 / 780.0 sess | 424,282,165 KRW / 4.27% / -32.45% / 33 (39.76%) / 55.19% / 364.6 / 178.5 sess | 529,744,528 KRW / 6.11% / -40.98% / 21 (40.38%) / 59.48% / 782.8 / 870.0 sess |
| P2-1 | 261,262,777 KRW / 1.00% / -19.13% / 10 (19.23%) / 73.39% / 318.2 / 161.0 sess | 281,217,632 KRW / 2.71% / -19.26% / 11 (28.95%) / 80.60% / 591.0 / 565.0 sess | 232,542,822 KRW / -1.63% / -28.70% / 26 (50.00%) / 82.06% / 346.7 / 161.0 sess | 279,521,933 KRW / 2.56% / -26.73% / 20 (52.63%) / 91.10% / 606.2 / 724.5 sess |
| P2-2 | 438,288,498 KRW / 10.43% / -19.13% / 16 (24.24%) / 76.18% / 361.3 / 171.0 sess | 417,987,183 KRW / 9.51% / -19.26% / 13 (28.89%) / 80.45% / 661.1 / 667.5 sess | 377,261,625 KRW / 7.55% / -28.70% / 33 (50.00%) / 82.83% / 357.3 / 160.0 sess | 406,487,550 KRW / 8.97% / -26.73% / 23 (51.11%) / 87.35% / 632.0 / 423.5 sess |
| P3-1 | 238,472,565 KRW / -1.37% / -16.69% / 8 (18.60%) / 61.51% / 216.4 / 108.0 sess | 262,766,201 KRW / 1.47% / -14.62% / 11 (36.67%) / 71.40% / 535.7 / 555.0 sess | 216,170,999 KRW / -4.17% / -25.73% / 20 (46.51%) / 69.08% / 207.1 / 98.0 sess | 279,985,193 KRW / 3.38% / -14.94% / 17 (56.67%) / 81.68% / 539.8 / 632.0 sess |
| P3-2 | 395,807,840 KRW / 10.36% / -16.69% / 14 (23.73%) / 67.31% / 255.2 / 146.0 sess | 406,003,565 KRW / 10.97% / -14.62% / 13 (35.14%) / 75.51% / 637.2 / 775.0 sess | 369,063,853 KRW / 8.72% / -25.73% / 29 (49.15%) / 73.39% / 233.0 / 114.0 sess | 415,964,804 KRW / 11.55% / -14.94% / 20 (54.05%) / 83.60% / 607.8 / 555.0 sess |

## Portfolio results — all 20 rows

| Window | Scenario | Strategy | Final equity | Total return | CAGR | MDD | Realized PnL | Open terminal PnL | Filled / candidates | CASH_SKIP | Avg / max utilization | Avg / median holdings | Mean / median holding sessions |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 15M | A FAST Core V2 | 479,513,497 KRW | 91.81% | 5.28% | -21.17% | 186,949,611 KRW | 42,563,886 KRW | 73 / 83 | 10 (12.05%) | 45.96% / 98.59% | 8.35 / 8.00 | 356.3 / 194.0 |
| P1 | 15M | Julia V00 | 545,580,535 KRW | 118.23% | 6.36% | -30.12% | 253,506,737 KRW | 42,073,798 KRW | 45 / 52 | 7 (13.46%) | 51.11% / 99.78% | 10.87 / 11.00 | 751.2 / 780.0 |
| P1 | 25M | A FAST Core V2 | 424,282,165 KRW | 69.71% | 4.27% | -32.45% | 155,699,966 KRW | 18,582,198 KRW | 50 / 83 | 33 (39.76%) | 55.19% / 99.48% | 5.85 / 7.00 | 364.6 / 178.5 |
| P1 | 25M | Julia V00 | 529,744,528 KRW | 111.90% | 6.11% | -40.98% | 301,800,996 KRW | -22,056,469 KRW | 31 / 52 | 21 (40.38%) | 59.48% / 99.40% | 7.80 / 8.00 | 782.8 / 870.0 |
| P2-1 | 15M | A FAST Core V2 | 261,262,777 KRW | 4.51% | 1.00% | -19.13% | -7,222,217 KRW | 18,484,995 KRW | 42 / 52 | 10 (19.23%) | 73.39% / 98.91% | 12.33 / 13.00 | 318.2 / 161.0 |
| P2-1 | 15M | Julia V00 | 281,217,632 KRW | 12.49% | 2.71% | -19.26% | 40,836,416 KRW | -9,618,784 KRW | 27 / 38 | 11 (28.95%) | 80.60% / 98.83% | 14.74 / 16.00 | 591.0 / 565.0 |
| P2-1 | 25M | A FAST Core V2 | 232,542,822 KRW | -6.98% | -1.63% | -28.70% | -17,528,813 KRW | 71,635 KRW | 26 / 52 | 26 (50.00%) | 82.06% / 100.00% | 8.32 / 9.00 | 346.7 / 161.0 |
| P2-1 | 25M | Julia V00 | 279,521,933 KRW | 11.81% | 2.56% | -26.73% | 42,540,994 KRW | -13,019,061 KRW | 18 / 38 | 20 (52.63%) | 91.10% / 100.00% | 10.08 / 11.00 | 606.2 / 724.5 |
| P2-2 | 15M | A FAST Core V2 | 438,288,498 KRW | 75.32% | 10.43% | -19.13% | 145,724,612 KRW | 42,563,886 KRW | 50 / 66 | 16 (24.24%) | 76.18% / 99.50% | 13.00 / 14.00 | 361.3 / 171.0 |
| P2-2 | 15M | Julia V00 | 417,987,183 KRW | 67.19% | 9.51% | -19.26% | 164,530,809 KRW | 3,456,374 KRW | 32 / 45 | 13 (28.89%) | 80.45% / 98.83% | 15.24 / 17.00 | 661.1 / 667.5 |
| P2-2 | 25M | A FAST Core V2 | 377,261,625 KRW | 50.90% | 7.55% | -28.70% | 117,053,750 KRW | 10,207,874 KRW | 33 / 66 | 33 (50.00%) | 82.83% / 100.00% | 8.48 / 9.00 | 357.3 / 160.0 |
| P2-2 | 25M | Julia V00 | 406,487,550 KRW | 62.60% | 8.97% | -26.73% | 188,433,437 KRW | -31,945,887 KRW | 22 / 45 | 23 (51.11%) | 87.35% / 100.00% | 10.01 / 11.00 | 632.0 / 423.5 |
| P3-1 | 15M | A FAST Core V2 | 238,472,565 KRW | -4.61% | -1.37% | -16.69% | -40,372,942 KRW | 28,845,507 KRW | 35 / 43 | 8 (18.60%) | 61.51% / 99.85% | 9.05 / 11.00 | 216.4 / 108.0 |
| P3-1 | 15M | Julia V00 | 262,766,201 KRW | 5.11% | 1.47% | -14.62% | 17,680,592 KRW | -4,914,391 KRW | 19 / 30 | 11 (36.67%) | 71.40% / 96.21% | 12.20 / 16.00 | 535.7 / 555.0 |
| P3-1 | 25M | A FAST Core V2 | 216,170,999 KRW | -13.53% | -4.17% | -25.73% | -65,128,988 KRW | 31,299,986 KRW | 23 / 43 | 20 (46.51%) | 69.08% / 99.64% | 5.69 / 7.00 | 207.1 / 98.0 |
| P3-1 | 25M | Julia V00 | 279,985,193 KRW | 11.99% | 3.38% | -14.94% | 29,512,900 KRW | 472,293 KRW | 13 / 30 | 17 (56.67%) | 81.68% / 99.99% | 8.41 / 10.00 | 539.8 / 632.0 |
| P3-2 | 15M | A FAST Core V2 | 395,807,840 KRW | 58.32% | 10.36% | -16.69% | 102,250,135 KRW | 43,557,705 KRW | 45 / 59 | 14 (23.73%) | 67.31% / 99.85% | 10.05 / 11.00 | 255.2 / 146.0 |
| P3-2 | 15M | Julia V00 | 406,003,565 KRW | 62.40% | 10.97% | -14.62% | 139,722,419 KRW | 16,281,146 KRW | 24 / 37 | 13 (35.14%) | 75.51% / 99.81% | 13.42 / 16.00 | 637.2 / 775.0 |
| P3-2 | 25M | A FAST Core V2 | 369,063,853 KRW | 47.63% | 8.72% | -25.73% | 59,322,278 KRW | 59,741,575 KRW | 30 / 59 | 29 (49.15%) | 73.39% / 99.64% | 6.12 / 7.00 | 233.0 / 114.0 |
| P3-2 | 25M | Julia V00 | 415,964,804 KRW | 66.39% | 11.55% | -14.94% | 144,601,079 KRW | 21,363,725 KRW | 17 / 37 | 20 (54.05%) | 83.60% / 99.99% | 9.07 / 10.00 | 607.8 / 555.0 |

## Holding-period distribution

Sessions are inclusive KRX sessions from entry execution through realized exit execution or cutoff for open positions. Calendar days are the date difference between those endpoints. Closed and open-at-cutoff positions are shown separately.

| Window | Scenario | Strategy | Holding class | Filled positions | Mean sessions | Median | P25 | P75 | P90 | Max | Mean / median calendar days |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 15M | A FAST Core V2 | ALL_FILLED_POSITIONS | 73 | 356.3 | 194.0 | 110.0 | 387.0 | 865.4 | 1,447 | 529.5 / 288.0 |
| P1 | 15M | A FAST Core V2 | CLOSED | 62 | 303.4 | 184.0 | 108.5 | 358.5 | 780.7 | 1,447 | 450.1 / 273.5 |
| P1 | 15M | A FAST Core V2 | OPEN_AT_CUTOFF | 11 | 654.9 | 705.0 | 233.0 | 1,029.0 | 1,330.0 | 1,349 | 977.1 / 1,056.0 |
| P1 | 15M | Julia V00 | ALL_FILLED_POSITIONS | 45 | 751.2 | 780.0 | 292.0 | 1,122.0 | 1,365.8 | 2,086 | 1,118.3 / 1,169.0 |
| P1 | 15M | Julia V00 | CLOSED | 29 | 741.3 | 770.0 | 345.0 | 1,037.0 | 1,297.4 | 2,086 | 1,103.0 / 1,156.0 |
| P1 | 15M | Julia V00 | OPEN_AT_CUTOFF | 16 | 769.0 | 855.5 | 280.8 | 1,230.2 | 1,363.0 | 1,807 | 1,146.1 / 1,281.0 |
| P1 | 25M | A FAST Core V2 | ALL_FILLED_POSITIONS | 50 | 364.6 | 178.5 | 84.5 | 426.0 | 936.0 | 1,447 | 541.7 / 261.5 |
| P1 | 25M | A FAST Core V2 | CLOSED | 41 | 318.6 | 175.0 | 80.0 | 360.0 | 847.0 | 1,447 | 472.5 / 258.0 |
| P1 | 25M | A FAST Core V2 | OPEN_AT_CUTOFF | 9 | 574.3 | 444.0 | 124.0 | 870.0 | 1,220.2 | 1,349 | 856.8 / 665.0 |
| P1 | 25M | Julia V00 | ALL_FILLED_POSITIONS | 31 | 782.8 | 870.0 | 341.5 | 1,103.5 | 1,260.0 | 2,086 | 1,165.3 / 1,302.0 |
| P1 | 25M | Julia V00 | CLOSED | 19 | 800.1 | 886.0 | 511.5 | 1,061.0 | 1,212.8 | 2,086 | 1,189.9 / 1,311.0 |
| P1 | 25M | Julia V00 | OPEN_AT_CUTOFF | 12 | 755.5 | 855.5 | 250.0 | 1,190.2 | 1,359.0 | 1,807 | 1,126.2 / 1,281.0 |
| P2-1 | 15M | A FAST Core V2 | ALL_FILLED_POSITIONS | 42 | 318.2 | 161.0 | 68.8 | 469.8 | 984.7 | 1,062 | 471.8 / 232.0 |
| P2-1 | 15M | A FAST Core V2 | CLOSED | 26 | 173.1 | 125.0 | 63.5 | 217.0 | 357.0 | 847 | 254.7 / 182.5 |
| P2-1 | 15M | A FAST Core V2 | OPEN_AT_CUTOFF | 16 | 554.0 | 514.5 | 134.0 | 1,003.2 | 1,046.5 | 1,062 | 824.5 / 770.5 |
| P2-1 | 15M | Julia V00 | ALL_FILLED_POSITIONS | 27 | 591.0 | 565.0 | 180.5 | 966.5 | 1,046.0 | 1,072 | 878.1 / 844.0 |
| P2-1 | 15M | Julia V00 | CLOSED | 9 | 231.4 | 180.0 | 141.0 | 288.0 | 420.6 | 555 | 340.6 / 263.0 |
| P2-1 | 15M | Julia V00 | OPEN_AT_CUTOFF | 18 | 770.7 | 887.5 | 581.8 | 1,023.8 | 1,052.9 | 1,072 | 1,146.8 / 1,319.5 |
| P2-1 | 25M | A FAST Core V2 | ALL_FILLED_POSITIONS | 26 | 346.7 | 161.0 | 63.5 | 523.8 | 1,020.0 | 1,062 | 513.2 / 232.0 |
| P2-1 | 25M | A FAST Core V2 | CLOSED | 17 | 168.2 | 126.0 | 44.0 | 180.0 | 356.4 | 847 | 246.4 / 182.0 |
| P2-1 | 25M | A FAST Core V2 | OPEN_AT_CUTOFF | 9 | 683.9 | 883.0 | 400.0 | 1,044.0 | 1,051.6 | 1,062 | 1,017.2 / 1,313.0 |
| P2-1 | 25M | Julia V00 | ALL_FILLED_POSITIONS | 18 | 606.2 | 724.5 | 166.5 | 981.2 | 1,052.9 | 1,072 | 899.8 / 1,078.5 |
| P2-1 | 25M | Julia V00 | CLOSED | 7 | 201.1 | 162.0 | 133.5 | 180.5 | 330.6 | 555 | 294.9 / 233.0 |
| P2-1 | 25M | Julia V00 | OPEN_AT_CUTOFF | 11 | 863.9 | 937.0 | 836.0 | 1,046.5 | 1,062.0 | 1,072 | 1,284.8 / 1,397.0 |
| P2-2 | 15M | A FAST Core V2 | ALL_FILLED_POSITIONS | 50 | 361.3 | 171.0 | 85.2 | 429.8 | 1,139.4 | 1,349 | 537.2 / 251.5 |
| P2-2 | 15M | A FAST Core V2 | CLOSED | 39 | 278.5 | 160.0 | 80.5 | 277.0 | 808.6 | 1,305 | 413.1 / 231.0 |
| P2-2 | 15M | A FAST Core V2 | OPEN_AT_CUTOFF | 11 | 654.9 | 705.0 | 233.0 | 1,029.0 | 1,330.0 | 1,349 | 977.1 / 1,056.0 |
| P2-2 | 15M | Julia V00 | ALL_FILLED_POSITIONS | 32 | 661.1 | 667.5 | 159.5 | 1,190.2 | 1,323.0 | 1,377 | 984.4 / 997.5 |
| P2-2 | 15M | Julia V00 | CLOSED | 18 | 549.6 | 337.5 | 154.5 | 941.2 | 1,218.7 | 1,305 | 817.3 / 500.5 |
| P2-2 | 15M | Julia V00 | OPEN_AT_CUTOFF | 14 | 804.5 | 903.5 | 304.5 | 1,293.0 | 1,343.3 | 1,377 | 1,199.3 / 1,351.0 |
| P2-2 | 25M | A FAST Core V2 | ALL_FILLED_POSITIONS | 33 | 357.3 | 160.0 | 63.0 | 360.0 | 1,177.2 | 1,349 | 530.3 / 231.0 |
| P2-2 | 25M | A FAST Core V2 | CLOSED | 25 | 288.0 | 146.0 | 63.0 | 182.0 | 1,019.2 | 1,305 | 426.3 / 217.0 |
| P2-2 | 25M | A FAST Core V2 | OPEN_AT_CUTOFF | 8 | 573.6 | 523.5 | 95.5 | 949.5 | 1,236.3 | 1,349 | 855.2 / 783.5 |
| P2-2 | 25M | Julia V00 | ALL_FILLED_POSITIONS | 22 | 632.0 | 423.5 | 129.8 | 1,194.8 | 1,300.5 | 1,377 | 940.0 / 630.0 |
| P2-2 | 25M | Julia V00 | CLOSED | 14 | 591.8 | 368.0 | 146.2 | 1,089.0 | 1,242.3 | 1,305 | 879.9 / 546.0 |
| P2-2 | 25M | Julia V00 | OPEN_AT_CUTOFF | 8 | 702.2 | 740.0 | 115.5 | 1,235.0 | 1,357.4 | 1,377 | 1,045.2 / 1,102.5 |
| P3-1 | 15M | A FAST Core V2 | ALL_FILLED_POSITIONS | 35 | 216.4 | 108.0 | 45.0 | 373.5 | 518.8 | 824 | 321.3 / 162.0 |
| P3-1 | 15M | A FAST Core V2 | CLOSED | 23 | 157.7 | 81.0 | 45.0 | 224.5 | 381.6 | 668 | 232.6 / 122.0 |
| P3-1 | 15M | A FAST Core V2 | OPEN_AT_CUTOFF | 12 | 329.0 | 359.5 | 98.5 | 503.8 | 562.1 | 824 | 491.4 / 539.0 |
| P3-1 | 15M | Julia V00 | ALL_FILLED_POSITIONS | 19 | 535.7 | 555.0 | 499.5 | 695.5 | 796.0 | 829 | 799.5 / 826.0 |
| P3-1 | 15M | Julia V00 | CLOSED | 2 | 471.0 | 471.0 | 429.0 | 513.0 | 538.2 | 555 | 702.0 / 702.0 |
| P3-1 | 15M | Julia V00 | OPEN_AT_CUTOFF | 17 | 543.4 | 555.0 | 506.0 | 731.0 | 803.0 | 829 | 810.9 / 830.0 |
| P3-1 | 25M | A FAST Core V2 | ALL_FILLED_POSITIONS | 23 | 207.1 | 98.0 | 43.0 | 339.5 | 559.2 | 824 | 307.0 / 141.0 |
| P3-1 | 25M | A FAST Core V2 | CLOSED | 16 | 122.7 | 67.5 | 39.8 | 112.0 | 260.0 | 668 | 179.8 / 98.0 |
| P3-1 | 25M | A FAST Core V2 | OPEN_AT_CUTOFF | 7 | 400.0 | 400.0 | 219.0 | 550.5 | 668.6 | 824 | 597.9 / 598.0 |
| P3-1 | 25M | Julia V00 | ALL_FILLED_POSITIONS | 13 | 539.8 | 632.0 | 387.0 | 750.0 | 817.0 | 829 | 804.3 / 942.0 |
| P3-1 | 25M | Julia V00 | CLOSED | 2 | 471.0 | 471.0 | 429.0 | 513.0 | 538.2 | 555 | 702.0 / 702.0 |
| P3-1 | 25M | Julia V00 | OPEN_AT_CUTOFF | 11 | 552.3 | 660.0 | 352.0 | 769.5 | 824.0 | 829 | 822.9 / 984.0 |
| P3-2 | 15M | A FAST Core V2 | ALL_FILLED_POSITIONS | 45 | 255.2 | 146.0 | 65.0 | 360.0 | 690.2 | 1,088 | 379.8 / 217.0 |
| P3-2 | 15M | A FAST Core V2 | CLOSED | 37 | 220.1 | 130.0 | 65.0 | 289.0 | 511.6 | 1,088 | 327.2 / 190.0 |
| P3-2 | 15M | A FAST Core V2 | OPEN_AT_CUTOFF | 8 | 417.1 | 393.0 | 95.5 | 739.0 | 849.7 | 870 | 623.5 / 588.0 |
| P3-2 | 15M | Julia V00 | ALL_FILLED_POSITIONS | 24 | 637.2 | 775.0 | 329.5 | 911.5 | 1,049.3 | 1,134 | 952.5 / 1,162.5 |
| P3-2 | 15M | Julia V00 | CLOSED | 11 | 661.5 | 770.0 | 471.0 | 851.0 | 954.0 | 1,088 | 989.6 / 1,156.0 |
| P3-2 | 15M | Julia V00 | OPEN_AT_CUTOFF | 13 | 616.7 | 841.0 | 292.0 | 937.0 | 1,051.2 | 1,134 | 921.2 / 1,260.0 |
| P3-2 | 25M | A FAST Core V2 | ALL_FILLED_POSITIONS | 30 | 233.0 | 114.0 | 42.5 | 302.0 | 718.6 | 1,088 | 346.4 / 171.5 |
| P3-2 | 25M | A FAST Core V2 | CLOSED | 23 | 178.2 | 98.0 | 43.0 | 161.0 | 395.2 | 1,088 | 263.9 / 141.0 |
| P3-2 | 25M | A FAST Core V2 | OPEN_AT_CUTOFF | 7 | 413.3 | 342.0 | 67.0 | 773.0 | 852.6 | 870 | 617.6 / 511.0 |
| P3-2 | 25M | Julia V00 | ALL_FILLED_POSITIONS | 17 | 607.8 | 555.0 | 292.0 | 954.0 | 1,068.2 | 1,134 | 907.4 / 826.0 |
| P3-2 | 25M | Julia V00 | CLOSED | 6 | 667.8 | 729.0 | 429.0 | 941.2 | 1,021.0 | 1,088 | 997.3 / 1,088.5 |
| P3-2 | 25M | Julia V00 | OPEN_AT_CUTOFF | 11 | 575.0 | 444.0 | 208.0 | 986.5 | 1,055.0 | 1,134 | 858.3 / 665.0 |

## Strategy differences within each sizing scenario

Positive holding-period differences mean Julia held filled positions longer. These are descriptive co-movements with cash use and MDD, not causal estimates.

| Window | Scenario | Julia − V2 CAGR (pp) | Final equity (KRW) | MDD (pp) | CASH_SKIP | Avg utilization (pp) | Mean / median holding sessions | Mean holding calendar days |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 15M | 1.08 | 66,067,037 KRW | -8.95 | -3 | 5.15 | 394.8 / 586.0 | 588.8 |
| P1 | 25M | 1.84 | 105,462,363 KRW | -8.53 | -12 | 4.30 | 418.2 / 691.5 | 623.6 |
| P2-1 | 15M | 1.70 | 19,954,855 KRW | -0.13 | 1 | 7.21 | 272.8 / 404.0 | 406.3 |
| P2-1 | 25M | 4.19 | 46,979,111 KRW | 1.97 | -6 | 9.04 | 259.5 / 563.5 | 386.6 |
| P2-2 | 15M | -0.92 | -20,301,315 KRW | -0.13 | -3 | 4.26 | 299.8 / 496.5 | 447.3 |
| P2-2 | 25M | 1.43 | 29,225,925 KRW | 1.97 | -10 | 4.53 | 274.7 / 263.5 | 409.7 |
| P3-1 | 15M | 2.84 | 24,293,636 KRW | 2.07 | 3 | 9.89 | 319.3 / 447.0 | 478.2 |
| P3-1 | 25M | 7.55 | 63,814,194 KRW | 10.79 | -3 | 12.61 | 332.7 / 534.0 | 497.3 |
| P3-2 | 15M | 0.60 | 10,195,725 KRW | 2.07 | -1 | 8.19 | 382.1 / 629.0 | 572.7 |
| P3-2 | 25M | 2.83 | 46,900,951 KRW | 10.79 | -9 | 10.20 | 374.7 / 441.0 | 561.0 |

## 25M minus 15M sizing sensitivity

| Window | Strategy | Final equity (KRW) | CAGR (pp) | MDD (pp) | CASH_SKIP count | Avg utilization (pp) | Mean / median holding sessions |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | A FAST Core V2 | -55,231,333 KRW | -1.01 | -11.28 | 23 | 9.22 | 8.3 / -15.5 |
| P1 | Julia V00 | -15,836,007 KRW | -0.25 | -10.86 | 14 | 8.37 | 31.7 / 90.0 |
| P2-1 | A FAST Core V2 | -28,719,955 KRW | -2.63 | -9.57 | 16 | 8.67 | 28.5 / 0.0 |
| P2-1 | Julia V00 | -1,695,699 KRW | -0.14 | -7.47 | 9 | 10.50 | 15.2 / 159.5 |
| P2-2 | A FAST Core V2 | -61,026,873 KRW | -2.89 | -9.57 | 17 | 6.64 | -4.0 / -11.0 |
| P2-2 | Julia V00 | -11,499,634 KRW | -0.54 | -7.47 | 10 | 6.91 | -29.1 / -244.0 |
| P3-1 | A FAST Core V2 | -22,301,566 KRW | -2.80 | -9.05 | 12 | 7.57 | -9.3 / -10.0 |
| P3-1 | Julia V00 | 17,218,992 KRW | 1.91 | -0.32 | 6 | 10.28 | 4.0 / 77.0 |
| P3-2 | A FAST Core V2 | -26,743,987 KRW | -1.64 | -9.05 | 15 | 6.08 | -22.1 / -32.0 |
| P3-2 | Julia V00 | 9,961,239 KRW | 0.58 | -0.32 | 7 | 8.09 | -29.5 / -220.0 |

## Validation and output files

- Validation verdict: `ETF_36_REALISTIC_PORTFOLIO_AFAST_V2_VS_JULIA_15M_25M_PASS`; all checks pass: `True`.
- Preflight local-price checks: `True`; entry / realized-exit / open-terminal price mismatch: 0 / 0 / 0.
- Missing/invalid daily closes over all candidate holding spans: 0; local raw OHLC invalid rows: 0.
- New trades / full signal replay / clean-ready recomputation / market refetch / 40D recomputation: 0 / 0 / 0 / 0 / 0. Portfolio ledger replays: 1 batch of 20 results on 10 workers.
- `portfolio_summary.csv`: all 20 portfolio metrics; `filled_trade_ledger.csv`: every filled position; `cash_skip_ledger.csv`: every cash-shortage skip; `holding_period_summary.csv`: holding distributions; `equity_curve.csv`: daily cash, market value, equity, holdings, utilization, and drawdown; `validation.json`: validation details.
