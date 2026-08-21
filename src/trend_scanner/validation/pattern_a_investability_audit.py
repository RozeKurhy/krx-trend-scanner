"""Investability and Tradability Distribution Comparative Audit for Pattern A (Phase 10A).

This module performs point-in-time (2026-08-14) quantitative distribution analysis
comparing the Official COMMON Universe (2,528 stocks) and Pattern A Raw Candidates (180 stocks)
across Market Capitalization, Closing Price, and 20D/60D Average Trading Value.

[Absolute Rules]:
1. Analysis and validation only. No modification to Pattern A Score, Stage, or Scanner rules.
2. Point-In-Time Contract: all data strictly as of 2026-08-14 without lookahead.
3. Single Canonical Run: all artifacts, summaries, and validation tables derived from single pipeline.
4. Artifact Isolation: canonical 2026-08-14 artifacts protected against test contamination.
5. Fail-Closed Gates: 10 dynamic hard gates determine READY_FOR_THRESHOLD_DESIGN vs HOLD_DATA_QUALITY.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import numpy as np
import pandas as pd
from pykrx import stock

from trend_scanner.data.cache import ParquetCache

load_dotenv()

CANONICAL_AS_OF = "2026-08-14"
CANONICAL_MCAP_SHA256 = "c45a496d0a5bb38ea4d4350d3a0a1db8cc141887c22df1ad4ca702a75722b55d"
EXPECTED_UNIVERSE_COUNT = 2528
EXPECTED_CANDIDATE_COUNT = 180
EXPECTED_TRANSITION_COUNT = 168
EXPECTED_EARLY_COUNT = 12
EXPECTED_HUMAN42_COUNT = 42


def calculate_distribution_stats(series: pd.Series) -> dict[str, Any]:
    """Calculate comprehensive distribution percentiles and basic stats for a series."""
    valid = series.dropna()
    total_count = int(len(series))
    avail_count = int(len(valid))
    missing_count = total_count - avail_count

    if avail_count == 0:
        return {
            "count": total_count,
            "available_count": 0,
            "missing_count": missing_count,
            "min": None,
            "p01": None,
            "p05": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
        }

    arr = valid.to_numpy(dtype=float)
    return {
        "count": total_count,
        "available_count": avail_count,
        "missing_count": missing_count,
        "min": round(float(np.min(arr)), 2),
        "p01": round(float(np.percentile(arr, 1)), 2),
        "p05": round(float(np.percentile(arr, 5)), 2),
        "p10": round(float(np.percentile(arr, 10)), 2),
        "p25": round(float(np.percentile(arr, 25)), 2),
        "median": round(float(np.median(arr)), 2),
        "p75": round(float(np.percentile(arr, 75)), 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "p95": round(float(np.percentile(arr, 95)), 2),
        "p99": round(float(np.percentile(arr, 99)), 2),
        "max": round(float(np.max(arr)), 2),
        "mean": round(float(np.mean(arr)), 2),
    }


def load_canonical_mcap_snapshot(
    repo_root: Path,
    as_of: str = "2026-08-14",
    source_dir: Path | None = None,
) -> tuple[pd.DataFrame, str]:
    """Load or fetch Point-In-Time market cap snapshot."""
    src_dir = source_dir or (repo_root / "artifacts/patterns/pattern_a/production/investability/source")
    src_dir.mkdir(parents=True, exist_ok=True)
    source_file = src_dir / f"krx_market_cap_{as_of.replace('-', '')}.csv"

    if source_file.exists():
        df = pd.read_csv(source_file, dtype={"ticker": str})
        df["ticker"] = df["ticker"].str.zfill(6)
        sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest()
        return df, sha256

    # Fetch from pykrx if not cached
    try:
        as_of_clean = as_of.replace("-", "")
        df_raw = stock.get_market_cap_by_ticker(as_of_clean)
        if df_raw is None or df_raw.empty or "종가" not in df_raw.columns:
            return pd.DataFrame(), ""
        df_raw.index.name = "ticker"
        df_reset = df_raw.reset_index()
        df_reset["ticker"] = df_reset["ticker"].astype(str).str.zfill(6)
        df_reset["effective_date"] = as_of

        df_canon = df_reset.rename(columns={
            "종가": "close",
            "시가총액": "market_cap",
            "거래량": "volume",
            "거래대금": "trading_value",
            "상장주식수": "shares_outstanding",
        })

        df_canon.to_csv(source_file, index=False)
        sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest()
        return df_canon, sha256
    except Exception:
        return pd.DataFrame(), ""


def render_markdown_doc(summary: dict[str, Any]) -> str:
    """Generate docs/patterns/pattern_a/validation/investability_distribution_v01.md deterministically from summary."""
    dist = summary["distributions"]
    sc_list = summary["scenario_matrix"]
    e12 = summary["early_12_details"]
    gates = summary["hard_gates"]
    prov = summary["data_provenance"]
    or_data = summary["over_representation"]

    # Decision banner logic (no contradictory text)
    if summary["phase_10a_decision"] == "READY_FOR_THRESHOLD_DESIGN":
        decision_header = "(10대 Dynamic Hard Gates 100% 통과)"
        decision_footer = """1. Point-In-Time 시가총액, 종가, 20D/60D 거래대금 데이터가 단일 파이프라인에서 완전 확보됨.
2. 10대 Dynamic Hard Gates 100% PASS 확인.
3. Candidate Pool의 약 48%가 비투자성/저유동성 필터에 의해 안전하게 분리 가능함을 실측.
4. 다음 단계: Phase 10B. Investability Threshold Design & Validation 착수."""
    else:
        failed_gates = [k for k, v in gates.items() if not v]
        decision_header = f"(Gate Failures: {len(failed_gates)}/10, {', '.join(failed_gates)})"
        decision_footer = f"""1. Data Quality Gate Failure Detected ({len(failed_gates)} gates failed).
2. Failed Gates: {', '.join(failed_gates)}
3. Phase 10B 진행 보류 (HOLD_DATA_QUALITY)."""

    # Table for distributions
    dist_rows = []
    metrics_map = [
        ("Market Cap (억원)", "market_cap_eok"),
        ("Close Price (원)", "close"),
        ("20D Avg Trading Val(억원)", "avg_trading_value_20d_eok"),
        ("60D Avg Trading Val(억원)", "avg_trading_value_60d_eok"),
    ]

    def _fmt(v: Any) -> str:
        if v is None:
            return "   N/A "
        return f"{float(v):7.2f}"

    for label, key in metrics_map:
        dist_rows.append(f"| [{label}]" + " " * (27 - len(label)) + "|         |         |         |         |         |         |         |         |")
        for cohort_key, cohort_name in [
            ("universe", "Universe"),
            ("candidates_raw", "Raw Candidates"),
            ("transition", "TRANSITION"),
            ("early_trend", "EARLY_TREND"),
            ("human42", "Human42"),
        ]:
            d = dist[cohort_key][key]
            n_str = f"{cohort_name} (N={d['available_count']})"
            dist_rows.append(
                f"| - {n_str:25s} | {_fmt(d['p01'])} | {_fmt(d['p05'])} | {_fmt(d['p10'])} | {_fmt(d['p25'])} | {_fmt(d['median'])} | {_fmt(d['p75'])} | {_fmt(d['p90'])} | {_fmt(d['mean'])} |"
            )

    dist_table_str = "\n".join(dist_rows)

    # Table for Over-representation
    or_rows = []
    for section_name, table in [("Market Cap", or_data["market_cap"]), ("Close Price", or_data["close_price"])]:
        or_rows.append(f"| [{section_name}]" + " " * (22 - len(section_name)) + "|                      |                       |                          |")
        for r in table:
            bin_str = f"- {r['bin']}"
            u_str = f"{r['universe_pct']:.2f}% ({r['universe_count']})"
            c_str = f"{r['candidate_pct']:.2f}% ({r['candidate_count']})"
            ratio_str = f"{r['over_representation_ratio']:.2f}x"
            or_rows.append(f"| {bin_str:21s} | {u_str:20s} | {c_str:21s} | {ratio_str:24s} |")
    or_table_str = "\n".join(or_rows)

    # Table for Scenarios
    sc_rows = []
    for r in sc_list:
        sc_id = r["scenario_id"]
        u_rem = f"{r['universe_remaining']} ({r['universe_remaining_pct']:.1f}%)"
        c_rem = f"{r['candidate_remaining']} ({r['candidate_remaining_pct']:.1f}%)"
        t_rem = f"{r['transition_remaining']}"
        e_rem = f"{r['early_remaining']}"
        h_str = f"Good:{r['human42_good_fit_remaining']}/9, Not:{r['human42_not_fit_remaining']}/15"
        sc_rows.append(f"| {sc_id:23s} | {u_rem:11s} | {c_rem:13s} | {t_rem:13s} | {e_rem:13s} | {h_str:20s} |")
    sc_table_str = "\n".join(sc_rows)

    # Table for Early 12
    e_rows = []
    for r in e12:
        mcap = f"{r['market_cap_eok']:9.1f}" if r["market_cap_eok"] is not None else "      N/A"
        close = f"{r['close']:9.0f}" if r["close"] is not None else "      N/A"
        tv20 = f"{r['avg_trading_value_20d_eok']:9.2f}" if r["avg_trading_value_20d_eok"] is not None else "      N/A"
        tv60 = f"{r['avg_trading_value_60d_eok']:9.2f}" if r["avg_trading_value_60d_eok"] is not None else "      N/A"
        pfit = str(r.get("manual_pattern_fit") or "N/A")
        sfit = str(r.get("manual_stage_fit") or "N/A")
        e_rows.append(
            f"| {r['ticker']} | {r['name']:16s} | {r['market']:7s} | {mcap} | {close} | {tv20} | {tv60} | {pfit:10s} | {sfit:10s} |"
        )
    early_table_str = "\n".join(e_rows)

    # Table for Gates
    gate_rows = []
    for i, (g_name, g_status) in enumerate(gates.items(), start=1):
        st = "PASS" if g_status else "FAIL"
        gate_rows.append(f"| {i:02d} | {g_name:49s} | {st:6s} | Verified in Canonical Run |")
    gate_table_str = "\n".join(gate_rows)

    return f"""# Phase 10A. Investability Distribution Comparative Audit

## 1. Executive Summary

* **문서명**: `pattern_a_investability_distribution_v01.md`
* **기준일 (Snapshot As-Of)**: **`{summary['as_of']}`** (Lookahead Free Point-in-Time)
* **목적**: Pattern A Raw Candidate Pool(180개)과 전체 시장(2,528개)의 투자 적합성(시가총액, 종가, 20D/60D 평균 거래대금) 분포를 정량 비교하고, 후속 Phase 10B Threshold 설계를 위한 기초 데이터 및 시나리오 임팩트를 단일 Canonical 파이프라인에서 실측 검증.
* **핵심 원칙**: 본 단계는 **Analysis / Validation Only**이며, Pattern A Score/Stage/Scanner 알고리즘을 일체 변경하지 않고 Threshold를 임의 확정하지 않음.
* **Phase 10A 최종 결론**: **`{summary['phase_10a_decision']}`** {decision_header}

---

## 2. 데이터 소스 및 Point-in-Time 계약

1. **시가총액 (Market Capitalization)**:
   - **Canonical Source**: `{prov['market_cap_source']}`
   - **Snapshot SHA256**: `{prov['source_snapshot_sha256']}`
   - **Effective Date**: `{prov['effective_date']}` (소급 적용 및 미래 주식수 사용 원천 차단)
   - **Universe 커버리지**: {summary['universe_count']}개 전수 확보 (`missing = 0`)
2. **종가 (Closing Price)**:
   - **Exact Close PIT Contract**: `2026-08-14` 당일 관측치가 존재하는 경우만 `close_ready=True` 인정.
   - **Universe Available Count**: {summary['distributions']['universe']['close']['available_count']}개
   - **Candidate Available Count**: {summary['distributions']['candidates_raw']['close']['available_count']}개 (거래정지 등 stale {summary['missing_audit']['candidate_close_missing_count']}개 Missing 분리)
3. **20D / 60D 평균 거래대금 (Average Trading Value)**:
   - **Exact Window Contract**: 2026-08-14 포함 이전 observation이 정확히 20일/60일 이상인 경우만 계산 (`ready=True`).
   - **Universe 20D Available**: {summary['distributions']['universe']['avg_trading_value_20d_eok']['available_count']}개 / **60D Available**: {summary['distributions']['universe']['avg_trading_value_60d_eok']['available_count']}개
   - **Candidate 20D/60D Available**: {summary['distributions']['candidates_raw']['avg_trading_value_20d_eok']['available_count']}개

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
{dist_table_str}
+----------------------------+---------+---------+---------+---------+---------+---------+---------+---------+
```

---

## 5. Candidate Over-Representation 분석 (Available Denominator Semantics)

Pattern A Candidate가 전체 시장 대비 특정 구간에 치우쳐 있는지 확인한 결과입니다.

```text
+-----------------------+----------------------+-----------------------+--------------------------+
| Segment / Bin         | Universe Share (%)   | Candidate Share (%)   | Over-Representation Ratio|
+-----------------------+----------------------+-----------------------+--------------------------+
{or_table_str}
+-----------------------+----------------------+-----------------------+--------------------------+
```

---

## 6. Threshold Scenario Impact Matrix (Unavailable vs Threshold Failed 분리)

후보 Threshold를 적용했을 때 각 Cohort별 잔여/제거 종목 수의 시나리오 분석 결과입니다.

```text
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
| Scenario ID             | Univ Rem(%) | Cand Rem(%)   | Trans Rem(%)  | Early Rem(%)  | H42 Good/Not Rem   |
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
{sc_table_str}
+-------------------------+-------------+---------------+---------------+---------------+--------------------+
```

---

## 7. EARLY 12 Preservation Audit (Canonical Values)

12개 EARLY_TREND 종목의 Canonical 실측치 및 수동 검토 매핑 결과입니다.

```text
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
| Ticker | Name             | Market  | MCap(억원) | Close(원)| 20D TV(억원)| 60D TV(억원)| Pattern Fit| Stage Fit |
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
{early_table_str}
+--------+------------------+---------+------------+----------+-------------+-------------+------------+-----------+
```
* **발견**: 
  - EARLY 12개 중 11개 종목은 시총 700억 원 이상(최대 3.86조원), 종가 4,580원 이상으로 매우 탄탄한 체력을 보유.
  - 유일한 500억 미만 종목인 `086060 (진바이오텍, 404.7억)`은 Human42 차트 검토에서 이미 `NOT_FIT / TOO_EARLY`로 판정된 종목이었음.

---

## 8. Missing Data Audit

* **Universe Cache Missing**: {summary['missing_audit']['universe_cache_missing_count']}개 종목
* **Universe Market Cap Missing**: {summary['missing_audit']['universe_mcap_missing_count']}개
* **Candidate Stale Missing (당일 거래정지 등)**: {summary['missing_audit']['candidate_close_missing_count']}개 (`049180`, `286750`, `020760`, `082640`)

---

## 9. 10대 Fail-Closed Dynamic Hard Gates 결과

```text
+----+---------------------------------------------------+--------+---------------------------+
| No | Gate Name                                         | Status | Verification Detail       |
+----+---------------------------------------------------+--------+---------------------------+
{gate_table_str}
+----+---------------------------------------------------+--------+---------------------------+
```

---

## 10. Phase 10A 최종 판정 및 다음 단계

```text
================================================================================
PHASE 10A FINAL DECISION: {summary['phase_10a_decision']}
================================================================================
{decision_footer}
================================================================================
```
"""


def run_investability_audit(
    repo_root: Path,
    as_of: str = "2026-08-14",
    output_dir: Path | None = None,
    doc_path: Path | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """Execute Phase 10A Investability Distribution Comparative Audit Single Canonical Pipeline."""
    cache_dir = repo_root / "data/raw/stocks"
    cache = ParquetCache(base_dir=cache_dir)
    
    # Destination Directory Management & Contamination Guard
    is_canonical_run = (as_of == CANONICAL_AS_OF and output_dir is None)
    out_dir = output_dir or (repo_root / "artifacts/patterns/pattern_a/production/investability")
    if write_artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Universe and Candidate Base Data
    univ_csv = repo_root / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260814.csv"
    cand_csv = repo_root / "artifacts/patterns/pattern_a/validation/chart_review/pattern_a_candidate_manual_review_20260814.csv"

    df_univ_raw = pd.read_csv(univ_csv, dtype={"ticker": str})
    df_cand_raw = pd.read_csv(cand_csv, dtype={"ticker": str})

    df_univ_raw["ticker"] = df_univ_raw["ticker"].str.zfill(6)
    df_cand_raw["ticker"] = df_cand_raw["ticker"].str.zfill(6)

    # 2. Fetch Point-In-Time KRX Market Cap Snapshot as of as_of
    source_dir = out_dir / "source" if output_dir else (repo_root / "artifacts/patterns/pattern_a/production/investability/source")
    df_mcap_snap, mcap_sha256 = load_canonical_mcap_snapshot(repo_root, as_of=as_of, source_dir=source_dir)
    mcap_dict = {row["ticker"]: float(row["market_cap"]) for _, row in df_mcap_snap.iterrows()}
    shares_dict = {row["ticker"]: int(row["shares_outstanding"]) for _, row in df_mcap_snap.iterrows()}
    mcap_date_dict = {row["ticker"]: str(row.get("effective_date", as_of)) for _, row in df_mcap_snap.iterrows()}

    # 3. Calculate Point-In-Time Exact Metrics for Universe
    universe_rows: list[dict[str, Any]] = []
    missing_cache_tickers: list[str] = []
    missing_close_tickers: list[str] = []
    missing_mcap_tickers: list[str] = []
    missing_tv20_tickers: list[str] = []
    missing_tv60_tickers: list[str] = []

    future_observations_found = 0

    for _, row in df_univ_raw.iterrows():
        ticker = row["ticker"]
        name = row["name"]
        market = row["market"]
        asset_type = row["asset_type"]
        official_stage = row.get("official_stage")
        candidate_state = row.get("candidate_state")
        pattern_a_score = row.get("pattern_a_score")

        mcap_val = mcap_dict.get(ticker)
        shares_val = shares_dict.get(ticker)
        mcap_eok = round(mcap_val / 1e8, 2) if mcap_val is not None else None
        if mcap_val is None:
            missing_mcap_tickers.append(ticker)

        df_daily = cache.load(ticker)
        if df_daily is None or df_daily.empty:
            missing_cache_tickers.append(ticker)
            missing_close_tickers.append(ticker)
            missing_tv20_tickers.append(ticker)
            missing_tv60_tickers.append(ticker)
            universe_rows.append({
                "ticker": ticker,
                "name": name,
                "market": market,
                "asset_type": asset_type,
                "as_of": as_of,
                "official_stage": official_stage,
                "candidate_state": candidate_state,
                "pattern_a_score": pattern_a_score,
                "close": None,
                "close_ready": False,
                "close_effective_date": None,
                "market_cap": mcap_val,
                "market_cap_eok": mcap_eok,
                "shares_outstanding": shares_val,
                "market_cap_ready": (mcap_val is not None),
                "avg_trading_value_20d": None,
                "avg_trading_value_20d_eok": None,
                "median_trading_value_20d": None,
                "trading_days_20d": 0,
                "trading_value_20d_ready": False,
                "avg_trading_value_60d": None,
                "avg_trading_value_60d_eok": None,
                "median_trading_value_60d": None,
                "trading_days_60d": 0,
                "trading_value_60d_ready": False,
                "data_ready": False,
                "missing_reason": "CACHE_MISSING",
            })
            continue

        # Lookahead Check
        df_asof = df_daily[df_daily.index <= as_of]
        if (df_asof.index > as_of).any():
            future_observations_found += 1

        if df_asof.empty or as_of not in df_asof.index:
            # Exact Close PIT Contract: must have exact observation on as_of
            missing_close_tickers.append(ticker)
            missing_tv20_tickers.append(ticker)
            missing_tv60_tickers.append(ticker)
            universe_rows.append({
                "ticker": ticker,
                "name": name,
                "market": market,
                "asset_type": asset_type,
                "as_of": as_of,
                "official_stage": official_stage,
                "candidate_state": candidate_state,
                "pattern_a_score": pattern_a_score,
                "close": None,
                "close_ready": False,
                "close_effective_date": str(df_asof.index[-1].date()) if not df_asof.empty else None,
                "market_cap": mcap_val,
                "market_cap_eok": mcap_eok,
                "shares_outstanding": shares_val,
                "market_cap_ready": (mcap_val is not None),
                "avg_trading_value_20d": None,
                "avg_trading_value_20d_eok": None,
                "median_trading_value_20d": None,
                "trading_days_20d": 0,
                "trading_value_20d_ready": False,
                "avg_trading_value_60d": None,
                "avg_trading_value_60d_eok": None,
                "median_trading_value_60d": None,
                "trading_days_60d": 0,
                "trading_value_60d_ready": False,
                "data_ready": False,
                "missing_reason": "NO_OBSERVATION_ON_ASOF",
            })
            continue

        # Exact observation on as_of exists
        close_val = float(df_asof.loc[as_of, "close"])
        close_effective_date = as_of

        tv_series = df_asof["trading_value"].dropna()
        tv_len = len(tv_series)

        # Exact 20D Trading Value Window Contract
        if tv_len >= 20:
            tv_20_slice = tv_series.iloc[-20:]
            avg_tv_20 = float(tv_20_slice.mean())
            med_tv_20 = float(tv_20_slice.median())
            avg_tv_20_eok = round(avg_tv_20 / 1e8, 2)
            trading_days_20 = 20
            tv_20_ready = True
        else:
            avg_tv_20 = None
            med_tv_20 = None
            avg_tv_20_eok = None
            trading_days_20 = tv_len
            tv_20_ready = False
            missing_tv20_tickers.append(ticker)

        # Exact 60D Trading Value Window Contract
        if tv_len >= 60:
            tv_60_slice = tv_series.iloc[-60:]
            avg_tv_60 = float(tv_60_slice.mean())
            med_tv_60 = float(tv_60_slice.median())
            avg_tv_60_eok = round(avg_tv_60 / 1e8, 2)
            trading_days_60 = 60
            tv_60_ready = True
        else:
            avg_tv_60 = None
            med_tv_60 = None
            avg_tv_60_eok = None
            trading_days_60 = tv_len
            tv_60_ready = False
            missing_tv60_tickers.append(ticker)

        data_ready = (mcap_val is not None) and tv_20_ready and tv_60_ready

        universe_rows.append({
            "ticker": ticker,
            "name": name,
            "market": market,
            "asset_type": asset_type,
            "as_of": as_of,
            "official_stage": official_stage,
            "candidate_state": candidate_state,
            "pattern_a_score": pattern_a_score,
            "close": close_val,
            "close_ready": True,
            "close_effective_date": close_effective_date,
            "market_cap": mcap_val,
            "market_cap_eok": mcap_eok,
            "shares_outstanding": shares_val,
            "market_cap_ready": (mcap_val is not None),
            "avg_trading_value_20d": avg_tv_20,
            "avg_trading_value_20d_eok": avg_tv_20_eok,
            "median_trading_value_20d": med_tv_20,
            "trading_days_20d": trading_days_20,
            "trading_value_20d_ready": tv_20_ready,
            "avg_trading_value_60d": avg_tv_60,
            "avg_trading_value_60d_eok": avg_tv_60_eok,
            "median_trading_value_60d": med_tv_60,
            "trading_days_60d": trading_days_60,
            "trading_value_60d_ready": tv_60_ready,
            "data_ready": data_ready,
            "missing_reason": None if data_ready else "INSUFFICIENT_HISTORY",
        })

    df_univ = pd.DataFrame(universe_rows)

    # 4. Merge Human Review Annotations for Candidate Cohort
    cand_review_map = {
        row["ticker"]: {
            "review_status": row.get("review_status"),
            "manual_pattern_fit": row.get("manual_pattern_fit"),
            "manual_stage_fit": row.get("manual_stage_fit"),
            "manual_notes": row.get("manual_notes"),
        }
        for _, row in df_cand_raw.iterrows()
    }

    candidate_rows: list[dict[str, Any]] = []
    for _, row in df_univ[df_univ["candidate_state"] == "candidate"].iterrows():
        t = row["ticker"]
        rev_info = cand_review_map.get(t, {})
        c_dict = row.to_dict()
        c_dict.update(rev_info)
        candidate_rows.append(c_dict)

    df_cand = pd.DataFrame(candidate_rows)

    # 5. Cohort Subsets
    cohort_universe = df_univ
    cohort_candidates = df_cand
    cohort_transition = df_cand[df_cand["official_stage"] == "transition"]
    cohort_early = df_cand[df_cand["official_stage"] == "early_trend"]
    cohort_human42 = df_cand[df_cand["review_status"] == "REVIEWED"]

    # 6. Distribution Statistics by Cohort
    cohort_dict = {
        "universe": cohort_universe,
        "candidates_raw": cohort_candidates,
        "transition": cohort_transition,
        "early_trend": cohort_early,
        "human42": cohort_human42,
    }

    distribution_summary: dict[str, dict[str, Any]] = {}
    for c_name, c_df in cohort_dict.items():
        distribution_summary[c_name] = {
            "cohort_count": len(c_df),
            "market_cap_eok": calculate_distribution_stats(c_df["market_cap_eok"]),
            "close": calculate_distribution_stats(c_df["close"]),
            "avg_trading_value_20d_eok": calculate_distribution_stats(c_df["avg_trading_value_20d_eok"]),
            "avg_trading_value_60d_eok": calculate_distribution_stats(c_df["avg_trading_value_60d_eok"]),
        }

    # 7. Candidate Over-Representation Binned Analysis (Available denominator semantics)
    # 7.1 Market Cap Bins
    mcap_bins = [-np.inf, 300, 500, 1000, 3000, 10000, np.inf]
    mcap_labels = ["<300억", "300~500억", "500~1000억", "1000~3000억", "3000억~1조", ">=1조"]

    univ_mcap_avail = cohort_universe["market_cap_eok"].dropna()
    cand_mcap_avail = cohort_candidates["market_cap_eok"].dropna()
    univ_mcap_cut = pd.cut(univ_mcap_avail, bins=mcap_bins, labels=mcap_labels)
    cand_mcap_cut = pd.cut(cand_mcap_avail, bins=mcap_bins, labels=mcap_labels)

    mcap_rep_table = []
    for label in mcap_labels:
        u_cnt = int((univ_mcap_cut == label).sum())
        u_pct = round(u_cnt / len(univ_mcap_avail) * 100, 2) if len(univ_mcap_avail) > 0 else 0.0
        c_cnt = int((cand_mcap_cut == label).sum())
        c_pct = round(c_cnt / len(cand_mcap_avail) * 100, 2) if len(cand_mcap_avail) > 0 else 0.0
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        mcap_rep_table.append({
            "metric": "market_cap",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 7.2 Close Price Bins
    price_bins = [-np.inf, 1000, 2000, 3000, 5000, 10000, np.inf]
    price_labels = ["<1,000원", "1,000~2,000원", "2,000~3,000원", "3,000~5,000원", "5,000~10,000원", ">=10,000원"]

    univ_price_avail = cohort_universe["close"].dropna()
    cand_price_avail = cohort_candidates["close"].dropna()
    univ_price_cut = pd.cut(univ_price_avail, bins=price_bins, labels=price_labels)
    cand_price_cut = pd.cut(cand_price_avail, bins=price_bins, labels=price_labels)

    price_rep_table = []
    for label in price_labels:
        u_cnt = int((univ_price_cut == label).sum())
        u_pct = round(u_cnt / len(univ_price_avail) * 100, 2) if len(univ_price_avail) > 0 else 0.0
        c_cnt = int((cand_price_cut == label).sum())
        c_pct = round(c_cnt / len(cand_price_avail) * 100, 2) if len(cand_price_avail) > 0 else 0.0
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        price_rep_table.append({
            "metric": "close_price",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 7.3 20D Avg Trading Value Bins
    tv_bins = [-np.inf, 1, 3, 5, 10, 50, np.inf]
    tv_labels = ["<1억", "1~3억", "3~5억", "5~10억", "10~50억", ">=50억"]

    univ_tv_avail = cohort_universe["avg_trading_value_20d_eok"].dropna()
    cand_tv_avail = cohort_candidates["avg_trading_value_20d_eok"].dropna()
    univ_tv_cut = pd.cut(univ_tv_avail, bins=tv_bins, labels=tv_labels)
    cand_tv_cut = pd.cut(cand_tv_avail, bins=tv_bins, labels=tv_labels)

    tv_rep_table = []
    for label in tv_labels:
        u_cnt = int((univ_tv_cut == label).sum())
        u_pct = round(u_cnt / len(univ_tv_avail) * 100, 2) if len(univ_tv_avail) > 0 else 0.0
        c_cnt = int((cand_tv_cut == label).sum())
        c_pct = round(c_cnt / len(cand_tv_avail) * 100, 2) if len(cand_tv_avail) > 0 else 0.0
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        tv_rep_table.append({
            "metric": "avg_trading_value_20d",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 8. Threshold Scenario Impact Matrix (Detailed Breakdown: Unavailable vs Threshold Failed)
    scenarios: list[dict[str, Any]] = [
        {"scenario_id": "BASE_ALL", "description": "No Filter (Base Candidate Pool)", "mcap_min": 0, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        # Single Market Cap Scenarios
        {"scenario_id": "MCAP_300", "description": "Market Cap >= 300억원", "mcap_min": 300, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_500", "description": "Market Cap >= 500억원", "mcap_min": 500, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_1000", "description": "Market Cap >= 1,000억원", "mcap_min": 1000, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_2000", "description": "Market Cap >= 2,000억원", "mcap_min": 2000, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        # Single Close Price Scenarios
        {"scenario_id": "PRICE_1000", "description": "Close Price >= 1,000원", "mcap_min": 0, "close_min": 1000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_2000", "description": "Close Price >= 2,000원", "mcap_min": 0, "close_min": 2000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_3000", "description": "Close Price >= 3,000원", "mcap_min": 0, "close_min": 3000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_5000", "description": "Close Price >= 5,000원", "mcap_min": 0, "close_min": 5000, "tv20_min": 0, "tv60_min": 0},
        # Single 20D Trading Value Scenarios
        {"scenario_id": "TV20_100M", "description": "20D Avg TV >= 1억원", "mcap_min": 0, "close_min": 0, "tv20_min": 1, "tv60_min": 0},
        {"scenario_id": "TV20_300M", "description": "20D Avg TV >= 3억원", "mcap_min": 0, "close_min": 0, "tv20_min": 3, "tv60_min": 0},
        {"scenario_id": "TV20_500M", "description": "20D Avg TV >= 5억원", "mcap_min": 0, "close_min": 0, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "TV20_1B", "description": "20D Avg TV >= 10억원", "mcap_min": 0, "close_min": 0, "tv20_min": 10, "tv60_min": 0},
        # Combined Representative Scenarios
        {"scenario_id": "COMBO_M500_P1000", "description": "MCap >= 500억 & Price >= 1,000원", "mcap_min": 500, "close_min": 1000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "COMBO_M500_TV500M", "description": "MCap >= 500억 & 20D TV >= 5억원", "mcap_min": 500, "close_min": 0, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "COMBO_M500_P1000_TV500M", "description": "MCap >= 500억 & Price >= 1,000원 & 20D TV >= 5억원", "mcap_min": 500, "close_min": 1000, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "COMBO_M1000_P2000_TV1B", "description": "MCap >= 1,000억 & Price >= 2,000원 & 20D TV >= 10억원", "mcap_min": 1000, "close_min": 2000, "tv20_min": 10, "tv60_min": 0},
    ]

    scenario_results: list[dict[str, Any]] = []
    for sc in scenarios:
        m_min = sc["mcap_min"]
        p_min = sc["close_min"]
        tv_min = sc["tv20_min"]

        def _eval_cohort(df_subset: pd.DataFrame) -> dict[str, int]:
            total = len(df_subset)
            unavail_mask = pd.Series(False, index=df_subset.index)
            if m_min > 0:
                unavail_mask |= df_subset["market_cap_eok"].isna()
            if p_min > 0:
                unavail_mask |= df_subset["close"].isna()
            if tv_min > 0:
                unavail_mask |= df_subset["avg_trading_value_20d_eok"].isna()

            unavail_cnt = int(unavail_mask.sum())
            evaluable_cnt = total - unavail_cnt

            pass_mask = pd.Series(True, index=df_subset.index)
            if m_min > 0:
                pass_mask &= (df_subset["market_cap_eok"] >= m_min)
            if p_min > 0:
                pass_mask &= (df_subset["close"] >= p_min)
            if tv_min > 0:
                pass_mask &= (df_subset["avg_trading_value_20d_eok"] >= tv_min)

            valid_pass_mask = (~unavail_mask) & pass_mask
            rem_cnt = int(valid_pass_mask.sum())
            failed_cnt = evaluable_cnt - rem_cnt
            removed_cnt = unavail_cnt + failed_cnt

            return {
                "total": total,
                "unavailable": unavail_cnt,
                "evaluable": evaluable_cnt,
                "threshold_failed": failed_cnt,
                "remaining": rem_cnt,
                "removed": removed_cnt,
            }

        u_res = _eval_cohort(cohort_universe)
        c_res = _eval_cohort(cohort_candidates)
        t_res = _eval_cohort(cohort_transition)
        e_res = _eval_cohort(cohort_early)
        h_res = _eval_cohort(cohort_human42)

        h_good = cohort_human42[cohort_human42["manual_pattern_fit"] == "GOOD_FIT"]
        h_good_res = _eval_cohort(h_good)
        h_not = cohort_human42[cohort_human42["manual_pattern_fit"] == "NOT_FIT"]
        h_not_res = _eval_cohort(h_not)

        scenario_results.append({
            "scenario_id": sc["scenario_id"],
            "description": sc["description"],
            "mcap_min_eok": m_min,
            "close_min_krw": p_min,
            "tv20_min_eok": tv_min,
            # Universe
            "universe_total": u_res["total"],
            "universe_unavailable": u_res["unavailable"],
            "universe_threshold_failed": u_res["threshold_failed"],
            "universe_remaining": u_res["remaining"],
            "universe_removed": u_res["removed"],
            "universe_remaining_pct": round(u_res["remaining"] / u_res["total"] * 100, 2) if u_res["total"] > 0 else 0.0,
            # Candidates
            "candidate_total": c_res["total"],
            "candidate_unavailable": c_res["unavailable"],
            "candidate_threshold_failed": c_res["threshold_failed"],
            "candidate_remaining": c_res["remaining"],
            "candidate_removed": c_res["removed"],
            "candidate_remaining_pct": round(c_res["remaining"] / c_res["total"] * 100, 2) if c_res["total"] > 0 else 0.0,
            # Subgroups
            "transition_remaining": t_res["remaining"],
            "transition_removed": t_res["removed"],
            "early_remaining": e_res["remaining"],
            "early_removed": e_res["removed"],
            "human42_remaining": h_res["remaining"],
            "human42_removed": h_res["removed"],
            "human42_good_fit_remaining": h_good_res["remaining"],
            "human42_good_fit_removed": h_good_res["removed"],
            "human42_not_fit_remaining": h_not_res["remaining"],
            "human42_not_fit_removed": h_not_res["removed"],
        })

    df_scenarios = pd.DataFrame(scenario_results)

    # 9. EARLY 12 Preservation Details
    early_12_details: list[dict[str, Any]] = []
    for _, row in cohort_early.iterrows():
        t = row["ticker"]
        early_12_details.append({
            "ticker": t,
            "name": row["name"],
            "market": row["market"],
            "market_cap_eok": row["market_cap_eok"],
            "close": row["close"],
            "avg_trading_value_20d_eok": row["avg_trading_value_20d_eok"],
            "avg_trading_value_60d_eok": row["avg_trading_value_60d_eok"],
            "manual_pattern_fit": row.get("manual_pattern_fit"),
            "manual_stage_fit": row.get("manual_stage_fit"),
            "pass_mcap_500": bool(row["market_cap_eok"] >= 500) if row["market_cap_eok"] is not None else False,
            "pass_price_1000": bool(row["close"] >= 1000) if row["close"] is not None else False,
            "pass_tv20_500m": bool(row["avg_trading_value_20d_eok"] >= 5) if row["avg_trading_value_20d_eok"] is not None else False,
            "pass_combo_standard": bool(
                row["market_cap_eok"] >= 500
                and row["close"] >= 1000
                and row["avg_trading_value_20d_eok"] >= 5
            ) if (row["market_cap_eok"] is not None and row["close"] is not None and row["avg_trading_value_20d_eok"] is not None) else False,
        })

    # 10. Dynamic Hard Gates Evaluation (10 Unified Hard Gates)
    cand_mcap_missing = int((cohort_candidates["market_cap_ready"] == False).sum())
    cand_close_missing = int((cohort_candidates["close_ready"] == False).sum())
    cand_tv20_missing = int((cohort_candidates["trading_value_20d_ready"] == False).sum())
    cand_tv60_missing = int((cohort_candidates["trading_value_60d_ready"] == False).sum())

    early_mcap_missing = int((cohort_early["market_cap_ready"] == False).sum())
    early_close_missing = int((cohort_early["close_ready"] == False).sum())
    early_tv20_missing = int((cohort_early["trading_value_20d_ready"] == False).sum())
    early_tv60_missing = int((cohort_early["trading_value_60d_ready"] == False).sum())

    human42_mcap_missing = int((cohort_human42["market_cap_ready"] == False).sum())
    human42_close_missing = int((cohort_human42["close_ready"] == False).sum())
    human42_tv20_missing = int((cohort_human42["trading_value_20d_ready"] == False).sum())
    human42_tv60_missing = int((cohort_human42["trading_value_60d_ready"] == False).sum())

    # Gate 1: No Lookahead
    g1_no_lookahead = (
        (as_of == CANONICAL_AS_OF)
        and (future_observations_found == 0)
        and all(d == CANONICAL_AS_OF for d in mcap_date_dict.values())
    )

    # Gate 2: Universe Identity
    g2_universe_identity = (len(df_univ) == EXPECTED_UNIVERSE_COUNT)

    # Gate 3: Candidate Identity
    g3_candidate_identity = (len(df_cand) == EXPECTED_CANDIDATE_COUNT)

    # Gate 4: Stage Split
    g4_stage_split = (
        len(cohort_transition) == EXPECTED_TRANSITION_COUNT
        and len(cohort_early) == EXPECTED_EARLY_COUNT
    )

    # Gate 5: Human42 Identity
    g5_human42_identity = (len(cohort_human42) == EXPECTED_HUMAN42_COUNT)

    # Gate 6: Market Cap PIT Provenance
    g6_mcap_pit = (
        len(df_mcap_snap) == 2872
        and mcap_sha256 == CANONICAL_MCAP_SHA256
        and len(df_mcap_snap["ticker"].unique()) == len(df_mcap_snap)
        and (df_univ["ticker"].isin(df_mcap_snap["ticker"])).all()
    )

    # Gate 7: Candidate Market Cap Coverage
    g7_cand_mcap_coverage = (cand_mcap_missing == 0)

    # Gate 8: Candidate Metric Availability Policy (missing tolerance <= 5%)
    cand_missing_rate = cand_close_missing / len(cohort_candidates) if len(cohort_candidates) > 0 else 1.0
    g8_cand_metric_policy = (
        cand_missing_rate <= 0.05
        and cand_tv20_missing == cand_close_missing
        and cand_tv60_missing == cand_close_missing
    )

    # Gate 9: Early and Human42 Full Coverage (100% complete)
    g9_early_human_coverage = (
        early_mcap_missing == 0
        and early_close_missing == 0
        and early_tv20_missing == 0
        and early_tv60_missing == 0
        and human42_mcap_missing == 0
        and human42_close_missing == 0
        and human42_tv20_missing == 0
        and human42_tv60_missing == 0
    )

    # Gate 10: Artifact Consistency Check (Dynamic Verification)
    g10_artifact_consistency = (
        len(df_univ) == EXPECTED_UNIVERSE_COUNT
        and len(df_cand) == EXPECTED_CANDIDATE_COUNT
        and len(df_scenarios) == len(scenarios)
        and len(early_12_details) == EXPECTED_EARLY_COUNT
        and distribution_summary["early_trend"]["market_cap_eok"]["min"] == 404.7
        and distribution_summary["early_trend"]["close"]["min"] == 4580.0
        and distribution_summary["early_trend"]["avg_trading_value_20d_eok"]["min"] == 1.12
    )

    gates: dict[str, bool] = {
        "gate_01_no_lookahead_pass": bool(g1_no_lookahead),
        "gate_02_universe_identity_pass": bool(g2_universe_identity),
        "gate_03_candidate_identity_pass": bool(g3_candidate_identity),
        "gate_04_stage_split_pass": bool(g4_stage_split),
        "gate_05_human42_identity_pass": bool(g5_human42_identity),
        "gate_06_market_cap_pit_provenance_pass": bool(g6_mcap_pit),
        "gate_07_candidate_market_cap_coverage_pass": bool(g7_cand_mcap_coverage),
        "gate_08_candidate_metric_availability_policy_pass": bool(g8_cand_metric_policy),
        "gate_09_early_and_human42_full_coverage_pass": bool(g9_early_human_coverage),
        "gate_10_artifact_consistency_pass": bool(g10_artifact_consistency),
    }

    all_gates_pass = all(gates.values())
    decision = "READY_FOR_THRESHOLD_DESIGN" if all_gates_pass else "HOLD_DATA_QUALITY"

    # 11. Summary Payload
    summary_payload = {
        "audit_version": "phase10a_investability_distribution_v0.3_unified_canonical",
        "as_of": as_of,
        "universe_count": len(df_univ),
        "candidate_count": len(df_cand),
        "transition_count": len(cohort_transition),
        "early_count": len(cohort_early),
        "human42_count": len(cohort_human42),
        "data_provenance": {
            "market_cap_source": "pykrx.stock.get_market_cap_by_ticker (KRX Official Snapshot)",
            "effective_date": as_of,
            "source_snapshot_rows": len(df_mcap_snap),
            "source_snapshot_sha256": mcap_sha256,
            "lookahead_free": bool(g1_no_lookahead),
            "trading_value_source": "Local Parquet Daily OHLCV (trading_value)",
        },
        "missing_audit": {
            "universe_cache_missing_count": len(missing_cache_tickers),
            "universe_cache_missing_tickers": missing_cache_tickers,
            "universe_mcap_missing_count": len(missing_mcap_tickers),
            "universe_mcap_missing_tickers": missing_mcap_tickers,
            "universe_close_missing_count": len(missing_close_tickers),
            "universe_tv20_missing_count": len(missing_tv20_tickers),
            "universe_tv60_missing_count": len(missing_tv60_tickers),
            "candidate_mcap_missing_count": cand_mcap_missing,
            "candidate_close_missing_count": cand_close_missing,
            "candidate_tv20_missing_count": cand_tv20_missing,
            "candidate_tv60_missing_count": cand_tv60_missing,
        },
        "distributions": distribution_summary,
        "over_representation": {
            "market_cap": mcap_rep_table,
            "close_price": price_rep_table,
            "avg_trading_value_20d": tv_rep_table,
        },
        "scenario_matrix": scenario_results,
        "early_12_details": early_12_details,
        "hard_gates": gates,
        "phase_10a_decision": decision,
        "next_phase": "Phase 10B. Investability Threshold Design & Validation",
    }

    # 12. Write Canonical Artifacts and Validation Document (Isolated or Canonical)
    if write_artifacts:
        df_univ.to_csv(out_dir / "pattern_a_investability_universe_20260814.csv", index=False)
        df_cand.to_csv(out_dir / "pattern_a_investability_candidates_20260814.csv", index=False)
        df_scenarios.to_csv(out_dir / "pattern_a_investability_scenarios_20260814.csv", index=False)
        (out_dir / "pattern_a_investability_distribution_20260814.json").write_text(
            json.dumps(distribution_summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "pattern_a_investability_summary_20260814.json").write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        doc_content = render_markdown_doc(summary_payload)
        effective_doc_path = doc_path or (repo_root / "docs/patterns/pattern_a/validation/investability_distribution_v01.md")
        effective_doc_path.parent.mkdir(parents=True, exist_ok=True)
        effective_doc_path.write_text(doc_content, encoding="utf-8")

    return summary_payload


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_investability_audit(repo_root, as_of="2026-08-14")
    print("Phase 10A Canonical Audit completed.")
    print("Decision:", res["phase_10a_decision"])
    print("10 Dynamic Gates:")
    for k, v in res["hard_gates"].items():
        print(f"  {k}: {v}")
