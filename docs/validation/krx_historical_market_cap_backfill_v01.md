krx_historical_market_cap_backfill_v01.md
==================================================
Phase 13J-0 Historical KRX Market Cap PIT Backfill
==================================================

1. Purpose
Phase 13J-1의 historical investability PIT block을 해소하기 위해 2020 Q1~2025 Q2 common quarterly reference candidates의 official KRX market-cap snapshots만 local immutable source로 백필했다. OOS sample, human review, chart, score/lead/OOS evaluation은 생성하거나 실행하지 않았다.

2. Blocking Dependency
기존 13J-1 blocked audit은 raw OHLCV cache에 historical market_cap과 shares_outstanding이 없음을 확인했다. 이 Phase는 그 dependency만 분리해서 해결한다. 기존 blocked audit 자체와 Phase 13I-2 결과는 변경하지 않는다.

3. KRX Canonical Source and Retrieval Method
Provider: KRX Data Marketplace. Product: ALL_STOCK_MARKET_DATA. Official screen: 전종목 시세 (MDC0201020101).

KRX 계정으로 공식 화면에 로그인한 후, 조회일자를 입력하고 화면의 CSV download control로 순차 export했다. undocumented endpoint나 parameter를 추측하지 않았고 third-party dataset/API는 사용하지 않았다. Source URL/endpoint string은 research contract로 봉인하지 않는다.

4. Reference Grid and Holiday Resolution
| Quarter | Candidate | Effective date | Status | Rows |
|---|---|---|---|---:|
| 2020 Q1 | 2020-03-27 | 2020-03-27 | EXACT_TRADING_DATE | 2479 |
| 2020 Q2 | 2020-06-26 | 2020-06-26 | EXACT_TRADING_DATE | 2475 |
| 2020 Q3 | 2020-09-25 | 2020-09-25 | EXACT_TRADING_DATE | 2500 |
| 2020 Q4 | 2020-12-25 | 2020-12-24 | HOLIDAY_FALLBACK | 2530 |
| 2021 Q1 | 2021-03-26 | 2021-03-26 | EXACT_TRADING_DATE | 2558 |
| 2021 Q2 | 2021-06-25 | 2021-06-25 | EXACT_TRADING_DATE | 2573 |
| 2021 Q3 | 2021-09-24 | 2021-09-24 | EXACT_TRADING_DATE | 2581 |
| 2021 Q4 | 2021-12-31 | 2021-12-30 | HOLIDAY_FALLBACK | 2610 |
| 2022 Q1 | 2022-03-25 | 2022-03-25 | EXACT_TRADING_DATE | 2623 |
| 2022 Q2 | 2022-06-24 | 2022-06-24 | EXACT_TRADING_DATE | 2629 |
| 2022 Q3 | 2022-09-30 | 2022-09-30 | EXACT_TRADING_DATE | 2651 |
| 2022 Q4 | 2022-12-30 | 2022-12-29 | HOLIDAY_FALLBACK | 2690 |
| 2023 Q1 | 2023-03-31 | 2023-03-31 | EXACT_TRADING_DATE | 2712 |
| 2023 Q2 | 2023-06-30 | 2023-06-30 | EXACT_TRADING_DATE | 2730 |
| 2023 Q3 | 2023-09-22 | 2023-09-22 | EXACT_TRADING_DATE | 2752 |
| 2023 Q4 | 2023-12-29 | 2023-12-28 | HOLIDAY_FALLBACK | 2787 |
| 2024 Q1 | 2024-03-29 | 2024-03-29 | EXACT_TRADING_DATE | 2802 |
| 2024 Q2 | 2024-06-28 | 2024-06-28 | EXACT_TRADING_DATE | 2817 |
| 2024 Q3 | 2024-09-27 | 2024-09-27 | EXACT_TRADING_DATE | 2834 |
| 2024 Q4 | 2024-12-27 | 2024-12-27 | EXACT_TRADING_DATE | 2866 |
| 2025 Q1 | 2025-03-28 | 2025-03-28 | EXACT_TRADING_DATE | 2879 |
| 2025 Q2 | 2025-06-27 | 2025-06-27 | EXACT_TRADING_DATE | 2875 |

Holiday fallback was not inferred from weekday arithmetic. KRX candidate responses with no positive canonical market_cap were followed by an earlier KRX query until a populated official snapshot was returned. The requested candidate and resolved effective_date are both retained.

5. Raw and Normalized Schema
Raw CSV bytes are immutable under `artifacts/investability/history/source/`; filename, provenance, and SHA-256 bind each raw export to its effective_date. The KRX raw Korean headers and bytes are preserved. Derived normalized CSVs are separate under `normalized/` with ticker, name, raw_market, normalized market, close, volume, trading_value, market_cap, shares_outstanding, effective_date. Missing values are not changed to zero.

6. PIT Safeguards
market_cap field source is KRX_CANONICAL. Market identity comes from KRX historical market field. Current market cap substitution, current listing-state substitution, future shares substitution, backward/forward fill, interpolation, and third-party market data are all false. KOSPI/KOSDAQ/KONEX mapping is derived only from the per-snapshot KRX market value.

7. Provenance and Validation
There are 22 reference mappings and 22 unique effective-date source files. All snapshots have unique tickers, positive canonical market_cap, positive shares_outstanding, and non-negative close where present. `close * shares_outstanding` is a descriptive cross-check only; 1% relative-error anomaly rows: 0. It is not a production threshold.

The official 2025-01-31 UI export was compared to the pre-existing Phase10 local source: ticker overlap and close/market_cap/shares_outstanding equality all PASS. Existing 2025-01-31 and 2026-08-14 source files were not overwritten.

8. Files
- `krx_market_cap_reference_grid_v01.csv`: 22 candidate-to-effective mappings and raw hashes.
- `krx_historical_market_cap_provenance_v01.csv`: KRX product/screen, retrieval metadata, raw and normalized hashes.
- `krx_historical_market_cap_backfill_audit_v01.json`: sealed source list, counts, safeguards, status.
- `krx_historical_market_cap_crosscheck_anomalies_v01.csv`: descriptive anomalies (empty in this run).

9. Final Status
All 22 candidates are covered by KRX canonical historical snapshots. Sample generated: 0. OOS evaluation run: false. Network provider: KRX only. Snapshot retrieval actions: 29.

Final status: HISTORICAL_MARKET_CAP_PIT_READY.

10. Next Step
STOP. Do not resume Phase 13J-1 in this commit. A later dedicated Phase 13J-1 task may consume these frozen local sources.
