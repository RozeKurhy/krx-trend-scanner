krx_historical_market_cap_backfill_v01.md
==================================================
Phase 13J-0 Historical KRX Market Cap PIT Backfill — Correction
==================================================

1. 범위와 최종 상태
-------------------
이 문서는 Phase 13J-0의 historical market-cap PIT source만 기록한다. OOS sample, human review, chart, score/lead/OOS evaluation은 생성하거나 실행하지 않았다.

Final status: HISTORICAL_MARKET_CAP_PIT_READY
Review status: READY_FOR_ADVISOR_13J0_CORRECTION_REVIEW

2. 수정 원인과 기준 계약
-----------------------
Previous v01 mapping used the prior trading day for four holiday candidates.

Advisor review identified that Phase13J requires alignment to the frozen completed W-FRI weekly reference contract, not merely the latest trading day.

기준일은 각 calendar candidate C에 대해 다음 구현을 그대로 실행해 계산한다.

`build_historical_snapshot("000150", "000150", daily, C, include_incomplete_periods=False).weekly_as_of`

`000150` 일봉 cache는 2014-05-26부터 전 22개 candidate를 모두 덮는다. 이 계산으로 나온 completed weekly reference date가 active KRX snapshot의 `requested_date`와 `effective_date`가 되도록 강제했다. 따라서 `effective_date <= calendar_candidate_date`와 `completed_weekly_reference_date == effective_date`가 22개 전부 true다.

The four affected mappings were recomputed mechanically from build_historical_snapshot(..., include_incomplete_periods=False) and replaced with KRX canonical snapshots for the corresponding completed weekly reference dates.

No OOS sample had been selected before this correction, so the issue caused no OOS look-ahead contamination.

3. KRX source와 수집 방식
--------------------------
Provider: KRX Data Marketplace
Product: ALL_STOCK_MARKET_DATA
Official screen: 전종목 시세 (MDC0201020101)

KRX 공식 로그인 후 화면에서 조회일을 입력하고 CSV download control로 export했다. undocumented endpoint, URL parameter 추정, third-party dataset/API는 사용하지 않았다. 이번 보정에서 새로 수집한 snapshot retrieval action은 4건이며, Phase 13J-0 누적 KRX retrieval action은 33건이다.

4. 22개 active reference grid
-----------------------------
| Quarter | Candidate | Completed W-FRI | Requested / Effective | Status | Rows |
|---|---|---|---|---|---:|
| 2020 Q1 | 2020-03-27 | 2020-03-27 | 2020-03-27 | EXACT_COMPLETED_WEEK | 2479 |
| 2020 Q2 | 2020-06-26 | 2020-06-26 | 2020-06-26 | EXACT_COMPLETED_WEEK | 2475 |
| 2020 Q3 | 2020-09-25 | 2020-09-25 | 2020-09-25 | EXACT_COMPLETED_WEEK | 2500 |
| 2020 Q4 | 2020-12-25 | 2020-12-18 | 2020-12-18 | PRIOR_COMPLETED_WEEK | 2524 |
| 2021 Q1 | 2021-03-26 | 2021-03-26 | 2021-03-26 | EXACT_COMPLETED_WEEK | 2558 |
| 2021 Q2 | 2021-06-25 | 2021-06-25 | 2021-06-25 | EXACT_COMPLETED_WEEK | 2573 |
| 2021 Q3 | 2021-09-24 | 2021-09-24 | 2021-09-24 | EXACT_COMPLETED_WEEK | 2581 |
| 2021 Q4 | 2021-12-31 | 2021-12-24 | 2021-12-24 | PRIOR_COMPLETED_WEEK | 2610 |
| 2022 Q1 | 2022-03-25 | 2022-03-25 | 2022-03-25 | EXACT_COMPLETED_WEEK | 2623 |
| 2022 Q2 | 2022-06-24 | 2022-06-24 | 2022-06-24 | EXACT_COMPLETED_WEEK | 2629 |
| 2022 Q3 | 2022-09-30 | 2022-09-30 | 2022-09-30 | EXACT_COMPLETED_WEEK | 2651 |
| 2022 Q4 | 2022-12-30 | 2022-12-23 | 2022-12-23 | PRIOR_COMPLETED_WEEK | 2689 |
| 2023 Q1 | 2023-03-31 | 2023-03-31 | 2023-03-31 | EXACT_COMPLETED_WEEK | 2712 |
| 2023 Q2 | 2023-06-30 | 2023-06-30 | 2023-06-30 | EXACT_COMPLETED_WEEK | 2730 |
| 2023 Q3 | 2023-09-22 | 2023-09-22 | 2023-09-22 | EXACT_COMPLETED_WEEK | 2752 |
| 2023 Q4 | 2023-12-29 | 2023-12-22 | 2023-12-22 | PRIOR_COMPLETED_WEEK | 2788 |
| 2024 Q1 | 2024-03-29 | 2024-03-29 | 2024-03-29 | EXACT_COMPLETED_WEEK | 2802 |
| 2024 Q2 | 2024-06-28 | 2024-06-28 | 2024-06-28 | EXACT_COMPLETED_WEEK | 2817 |
| 2024 Q3 | 2024-09-27 | 2024-09-27 | 2024-09-27 | EXACT_COMPLETED_WEEK | 2834 |
| 2024 Q4 | 2024-12-27 | 2024-12-27 | 2024-12-27 | EXACT_COMPLETED_WEEK | 2866 |
| 2025 Q1 | 2025-03-28 | 2025-03-28 | 2025-03-28 | EXACT_COMPLETED_WEEK | 2879 |
| 2025 Q2 | 2025-06-27 | 2025-06-27 | 2025-06-27 | EXACT_COMPLETED_WEEK | 2875 |

5. 보정 전/후와 새 원본 seal
------------------------------
| Candidate | Old active effective | New completed W-FRI effective | New raw file | Rows (KOSPI/KOSDAQ/KONEX) |
|---|---|---|---|---:|
| 2020-12-25 | 2020-12-24 | 2020-12-18 | krx_market_cap_20201218.csv | 2524 (916/1465/143) |
| 2021-12-31 | 2021-12-30 | 2021-12-24 | krx_market_cap_20211224.csv | 2610 (943/1535/132) |
| 2022-12-30 | 2022-12-29 | 2022-12-23 | krx_market_cap_20221223.csv | 2689 (943/1615/131) |
| 2023-12-29 | 2023-12-28 | 2023-12-22 | krx_market_cap_20231222.csv | 2788 (953/1706/129) |

| New raw file | Raw SHA-256 | Normalized SHA-256 |
|---|---|---|
| krx_market_cap_20201218.csv | 7644cb9d843426b47200bf1c762e0049762aa32fd924c214271bf7effbdef6e2 | 3eec2e37d12e8588a26fbdd11ea9609a7e7e8460413c4bf439182f3e6fa28f4c |
| krx_market_cap_20211224.csv | 04caaf2442cb63f1b52aed78419720019f706216db92d49b9a00358500deb911 | c17696f65577efba2b0b036e02ac5e3b588fd2121b96dc02aa5e80279e5cf2c3 |
| krx_market_cap_20221223.csv | fda6daf22570a76df51c0d6753774dc437aeffdde2d4dd2834121afb9593dae3 | 531d5695b377eaac2ebc00ada6c81edfac12af303d484e4b5c0ee8af009de08b |
| krx_market_cap_20231222.csv | 72d5965dc97b809571488db2b03ee79a5ffd4c701bfb55cadac2d722e794bd31 | 50c820eedd628d871c701c08b5754b8a470ae71b033718466b2bd892dd395765 |

기존 네 raw source와 normalized derivative는 삭제하거나 변경하지 않았다. provenance에서 `SUPERSEDED_NON_REFERENCE_SOURCE`로 남기고, 소비자는 반드시 reference grid의 22 active mapping만 사용한다.

6. PIT safeguards와 검증 결과
------------------------------
All active sources are KRX canonical. 현재 시가총액 대체, 미래 shares 대체, interpolation, third-party market data는 모두 false다. market_cap은 양수, shares_outstanding은 양수, ticker는 snapshot 내 unique이며, `close * shares_outstanding` descriptive anomaly row는 0이다.

기존 Phase10 2025-01-31 source crosscheck는 ticker overlap 2871건이며 close/market_cap/shares_outstanding 각각 2871/2871/2871 동일로 PASS다. 2025-01-31 및 2026-08-14 기존 source는 overwrite하지 않았다.

`reference_grid_sha256`: 181f86abc4a84b1bd770a0864ed2e6946337c949364e7166a2c24e8bc8b0cc3f
`provenance_sha256`: bc9bf3361d21120b0fae1e1e7f26e2ec812009d3864627d6a284a4bfa6fa3764

7. 변경 파일과 테스트
---------------------
- `scripts/backfill_krx_historical_market_cap_v01.py`: frozen completed W-FRI를 기계 계산하고 correction raw CSV를 immutable source로 반영한다.
- `artifacts/investability/history/source/krx_market_cap_20201218.csv`
- `artifacts/investability/history/source/krx_market_cap_20211224.csv`
- `artifacts/investability/history/source/krx_market_cap_20221223.csv`
- `artifacts/investability/history/source/krx_market_cap_20231222.csv`
- `artifacts/investability/history/normalized/krx_market_cap_20201218.csv` 등 4개 derived CSV
- `krx_market_cap_reference_grid_v01.csv`, `krx_historical_market_cap_provenance_v01.csv`, `krx_historical_market_cap_backfill_audit_v01.json`
- `tests/test_krx_historical_market_cap_backfill.py`

실행: `uv run pytest -p no:cacheprovider tests/test_krx_historical_market_cap_backfill.py`
결과: 4 passed (pandas resample deprecation warning 44건만 존재).

8. 다음 행동
------------
STOP. 이 commit에서 Phase 13J-1을 시작하거나 OOS sample/evaluation을 만들지 않는다. 다음 전용 Phase 13J-1 작업에서만 이 frozen active source를 소비한다.
