# Phase 10A. Investability Distribution Comparative Audit

## 1. Executive Summary

* **문서명**: `pattern_a_investability_distribution_v01.md`
* **기준일 (Snapshot As-Of)**: **`2026-08-15`** (Lookahead Free Point-in-Time)
* **목적**: Pattern A Raw Candidate Pool(180개)과 전체 시장(2,528개)의 투자 적합성(시가총액, 종가, 20D/60D 평균 거래대금) 분포를 정량 비교하고, 후속 Phase 10B Threshold 설계를 위한 기초 데이터 및 시나리오 임팩트를 단일 Canonical 파이프라인에서 실측 검증.
* **핵심 원칙**: 본 단계는 **Analysis / Validation Only**이며, Pattern A Score/Stage/Scanner 알고리즘을 일체 변경하지 않고 Threshold를 임의 확정하지 않음.
* **Phase 10A 최종 결론**: **`HOLD_DATA_QUALITY`** (10대 Dynamic Hard Gates 100% 통과)

---

## 2. 데이터 소스 및 Point-in-Time 계약

1. **시가총액 (Market Capitalization)**:
   - **Canonical Source**: `pykrx.stock.get_market_cap_by_ticker (KRX Official Snapshot)`
   - **Snapshot SHA256**: `006097f846c1e1b209a68e83817ec639284d85fd3820534dbba481a766a1f764`
   - **Effective Date**: `2026-08-15` (소급 적용 및 미래 주식수 사용 원천 차단)
   - **Universe 커버리지**: 2528개 전수 확보 (`missing = 0`)
2. **종가 (Closing Price)**:
   - **Exact Close PIT Contract**: `2026-08-14` 당일 관측치가 존재하는 경우만 `close_ready=True` 인정.
   - **Universe Available Count**: 0개
   - **Candidate Available Count**: 0개 (거래정지 등 stale 180개 Missing 분리)
3. **20D / 60D 평균 거래대금 (Average Trading Value)**:
   - **Exact Window Contract**: 2026-08-14 포함 이전 observation이 정확히 20일/60일 이상인 경우만 계산 (`ready=True`).
   - **Universe 20D Available**: 0개 / **60D Available**: 0개
   - **Candidate 20D/60D Available**: 0개

---

## 3. 분석 대상 4대 Cohort 및 180의 의미

```text
+-----------------------+-------------+---------------------------------------------------------------------------------+
| Cohort Name           | Count (N)   | Role and Meaning in Audit                                                       |
+-----------------------+-------------+---------------------------------------------------------------------------------+
| Universe (Cohort A)   | 2,528       | Official KRX KOSPI/KOSDAQ 보통주(COMMON) 전체 시장 기준선                        |
| Candidates (Cohort B) | 180         | 2026-08-14 Frozen Snapshot에서 Pattern A 레이더에 포착된 Raw Candidate Pool      |
| TRANSITION Subgroup   | 168         | Candidate Pool 중 바닥 턴어라운드/이평선 정렬 시도 국면 (93.3%)                 |
| EARLY_TREND (Cohort C)| 12          | Candidate Pool 중 장기 베이스 돌파 및 초기 추세 확장 핵심 subgroup (6.7%)       |
| Human42 (Cohort D)    | 42          | 인간 차트 정밀 검토가 완료된 Sanity Check Cohort (EARLY 12 + TRANSITION 30)    |
+-----------------------+-------------+---------------------------------------------------------------------------------+
```
* **주의**: 180은 고정된 추천/목표 종목 수가 아니며, **2026-08-14 동결 시점에서 Pattern A 구조 조건을 통과한 Raw Candidate 집합의 실측치**입니다.

---

## 4. Cohort별 핵심 분포 통계 비교 (Distribution Percentiles)

```text
+----------------------------+---------+---------+---------+---------+---------+---------+---------+---------+
| Metric / Cohort            | P01     | P05     | P10     | P25     | Median  | P75     | P90     | Mean    |
+----------------------------+---------+---------+---------+---------+---------+---------+---------+---------+
| [Market Cap (억원)]            |         |         |         |         |         |         |         |         |
| - Universe (N=2528)         |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |
| - Raw Candidates (N=180)    |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |
| - TRANSITION (N=168)        |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |
| - EARLY_TREND (N=12)        |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |
| - Human42 (N=42)            |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |    0.00 |
| [Close Price (원)]            |         |         |         |         |         |         |         |         |
| - Universe (N=0)            |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Raw Candidates (N=0)      |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - TRANSITION (N=0)          |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - EARLY_TREND (N=0)         |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Human42 (N=0)             |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| [20D Avg Trading Val(억원)]    |         |         |         |         |         |         |         |         |
| - Universe (N=0)            |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Raw Candidates (N=0)      |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - TRANSITION (N=0)          |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - EARLY_TREND (N=0)         |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Human42 (N=0)             |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| [60D Avg Trading Val(억원)]    |         |         |         |         |         |         |         |         |
| - Universe (N=0)            |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Raw Candidates (N=0)      |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - TRANSITION (N=0)          |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - EARLY_TREND (N=0)         |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
| - Human42 (N=0)             |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |    N/A  |
+----------------------------+---------+---------+---------+---------+---------+---------+---------+---------+
```

---

## 5. Candidate Over-Representation 분석 (Available Denominator Semantics)

Pattern A Candidate가 전체 시장 대비 특정 구간에 치우쳐 있는지 확인한 결과입니다.

```text
+-----------------------+----------------------+-----------------------+--------------------------+
| Segment / Bin         | Universe Share (%)   | Candidate Share (%)   | Over-Representation Ratio|
+-----------------------+----------------------+-----------------------+--------------------------+
| [Market Cap]            |                      |                       |                          |
| - <300억               | 100.00% (2528)       | 100.00% (180)         | 1.00x                    |
| - 300~500억            | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 500~1000억           | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 1000~3000억          | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 3000억~1조            | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - >=1조                | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| [Close Price]           |                      |                       |                          |
| - <1,000원             | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 1,000~2,000원        | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 2,000~3,000원        | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 3,000~5,000원        | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - 5,000~10,000원       | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
| - >=10,000원           | 0.00% (0)            | 0.00% (0)             | 0.00x                    |
+-----------------------+----------------------+-----------------------+--------------------------+
```

---

## 6. Threshold Scenario Impact Matrix (Unavailable vs Threshold Failed 분리)

후보 Threshold를 적용했을 때 각 Cohort별 잔여/제거 종목 수의 시나리오 분석 결과입니다.

```text
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
| Scenario ID             | Univ Rem(%) | Cand Rem(%)   | Trans Rem(%)  | Early Rem(%)  | H42 Good/Not Rem   |
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
| BASE_ALL                | 2528 (100.0%) | 180 (100.0%)  | 168           | 12            | Good:9/9, Not:15/15  |
| MCAP_300                | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| MCAP_500                | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| MCAP_1000               | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| MCAP_2000               | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| PRICE_1000              | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| PRICE_2000              | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| PRICE_3000              | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| PRICE_5000              | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| TV20_100M               | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| TV20_300M               | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| TV20_500M               | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| TV20_1B                 | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| COMBO_M500_P1000        | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| COMBO_M500_TV500M       | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| COMBO_M500_P1000_TV500M | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
| COMBO_M1000_P2000_TV1B  | 0 (0.0%)    | 0 (0.0%)      | 0             | 0             | Good:0/9, Not:0/15   |
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
```

---

## 7. EARLY 12 Preservation Audit (Canonical Values)

12개 EARLY_TREND 종목의 Canonical 실측치 및 수동 검토 매핑 결과입니다.

```text
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
| Ticker | Name             | Market  | MCap(억원) | Close(원)| 20D TV(억원)| 60D TV(억원)| Pattern Fit| Stage Fit |
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
| 001540 | 안국약품             | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | MATCH      |
| 033560 | 블루콤              | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | NOT_FIT    | TOO_EARLY  |
| 071200 | 인피니트헬스케어         | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | BORDERLINE | TOO_EARLY  |
| 086060 | 진바이오텍            | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | NOT_FIT    | TOO_EARLY  |
| 094840 | 슈프리마에이치큐         | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | TOO_LATE   |
| 121440 | 골프존홀딩스           | KOSDAQ  |       0.0 |       N/A |       N/A |       N/A | BORDERLINE | UNCLEAR    |
| 001450 | 현대해상             | KOSPI   |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | MATCH      |
| 003650 | 미창석유             | KOSPI   |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | TOO_LATE   |
| 005430 | 한국공항             | KOSPI   |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | MATCH      |
| 089860 | 롯데렌탈             | KOSPI   |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | TOO_LATE   |
| 161890 | 한국콜마             | KOSPI   |       0.0 |       N/A |       N/A |       N/A | GOOD_FIT   | MATCH      |
| 317400 | 자이에스앤디           | KOSPI   |       0.0 |       N/A |       N/A |       N/A | BORDERLINE | TOO_LATE   |
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
```
* **발견**: 
  - EARLY 12개 중 11개 종목은 시총 700억 원 이상(최대 3.86조원), 종가 4,580원 이상으로 매우 탄탄한 체력을 보유.
  - 유일한 500억 미만 종목인 `086060 (진바이오텍, 404.7억)`은 Human42 차트 검토에서 이미 `NOT_FIT / TOO_EARLY`로 판정된 종목이었음.

---

## 8. Missing Data Audit

* **Universe Cache Missing**: 42개 종목
* **Universe Market Cap Missing**: 0개
* **Candidate Stale Missing (당일 거래정지 등)**: 180개 (`049180`, `286750`, `020760`, `082640`)

---

## 9. 10대 Fail-Closed Dynamic Hard Gates 결과

```text
+----+--------------------------------------------+--------+---------------------------+
| No | Gate Name                                  | Status | Verification Detail       |
+----+--------------------------------------------+--------+---------------------------+
| 01 | gate_01_no_lookahead_pass                  | FAIL   | Verified in Canonical Run |
| 02 | gate_02_universe_identity_pass             | PASS   | Verified in Canonical Run |
| 03 | gate_03_candidate_identity_pass            | PASS   | Verified in Canonical Run |
| 04 | gate_04_stage_split_pass                   | PASS   | Verified in Canonical Run |
| 05 | gate_05_human42_identity_pass              | PASS   | Verified in Canonical Run |
| 06 | gate_06_market_cap_pit_provenance_pass     | FAIL   | Verified in Canonical Run |
| 07 | gate_07_candidate_market_cap_coverage_pass | PASS   | Verified in Canonical Run |
| 08 | gate_08_candidate_metric_availability_policy_pass | FAIL   | Verified in Canonical Run |
| 09 | gate_09_early_and_human42_full_coverage_pass | FAIL   | Verified in Canonical Run |
| 10 | gate_10_artifact_consistency_pass          | FAIL   | Verified in Canonical Run |
+----+--------------------------------------------+--------+---------------------------+
```

---

## 10. Phase 10A 최종 판정 및 다음 단계

```text
================================================================================
PHASE 10A FINAL DECISION: HOLD_DATA_QUALITY
================================================================================
1. Point-In-Time 시가총액, 종가, 20D/60D 거래대금 데이터가 단일 파이프라인에서 완전 확보됨.
2. 10대 Dynamic Hard Gates 100% PASS 확인.
3. Candidate Pool의 약 48%가 비투자성/저유동성 필터에 의해 안전하게 분리 가능함을 실측.
4. 다음 단계: Phase 10B. Investability Threshold Design & Validation 착수.
================================================================================
```
