#!/usr/bin/env python3
"""Run the frozen four-strategy comparison across sixteen sector ETFs."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import math
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_market_index_etf_four_strategy_v01 as base
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.pykrx_provider import _is_phantom_holiday_row
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import IdentityLifecycle


SECTOR_ETFS = {
    "091160": "KODEX 반도체",
    "102970": "KODEX 증권",
    "091170": "KODEX 은행",
    "091180": "KODEX 자동차",
    "266420": "KODEX 헬스케어",
    "140700": "KODEX 보험",
    "117700": "KODEX 건설",
    "266370": "KODEX IT",
    "363580": "KODEX 200IT TR",
    "266360": "KODEX K-콘텐츠",
    "117460": "KODEX 에너지화학",
    "117680": "KODEX 철강",
    "102960": "KODEX 기계장비",
    "266410": "KODEX 필수소비재",
    "140710": "KODEX 운송",
    "266390": "KODEX 경기소비재",
}
SUPPORT_END = pd.Timestamp("2026-08-21")
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
SAME_WINDOW_START = pd.Timestamp("2021-04-01")
SOURCE_DIR = ROOT / "data/market/raw/krx_stocks/v01/market=ETF"
DATA_DIR = ROOT / "data/raw/stocks"
OUT_ROOT = ROOT / "artifacts/research/sector_index_etf_four_strategy_v01"
AGGREGATE_SUMMARY_PATH = OUT_ROOT / "aggregate_summary.json"
AGGREGATE_REPORT_PATH = OUT_ROOT / "aggregate_report.md"
STARTING_HEAD = "10374ec062138ccae8b055f787ffe36c5215a419"
BRANCH = "codex/fastcore-fundamentals-simple-backtest-v01"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _source_frames() -> dict[str, pd.DataFrame]:
    dataset = ds.dataset(SOURCE_DIR, format="parquet", partitioning="hive")
    table = dataset.to_table(
        filter=pc.field("ticker").isin(list(SECTOR_ETFS)) & (pc.field("date") <= SUPPORT_END),
        columns=["date", "ticker", *base.REQUIRED_COLUMNS],
    )
    source = table.to_pandas()
    source["ticker"] = source["ticker"].astype(str).str.zfill(6)
    source["date"] = pd.to_datetime(source["date"]).dt.normalize()
    source = source.sort_values(["ticker", "date"]).reset_index(drop=True)
    phantom = _is_phantom_holiday_row(source)
    source = source.loc[~phantom].copy()
    frames: dict[str, pd.DataFrame] = {}
    for ticker in SECTOR_ETFS:
        group = source.loc[source["ticker"] == ticker, ["date", *base.REQUIRED_COLUMNS]].copy()
        group = group.set_index("date").sort_index()
        if group.index.has_duplicates:
            raise AssertionError(f"{ticker}: duplicate local KRX source dates")
        if group.empty:
            raise FileNotFoundError(f"{ticker}: no local KRX source rows")
        frames[ticker] = group
    return frames


def _field_mismatch_count(left: pd.DataFrame, right: pd.DataFrame, common: pd.DatetimeIndex) -> int:
    if not len(common):
        return 0
    left_values = left.loc[common, list(base.REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="raise")
    right_values = right.loc[common, list(base.REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="raise")
    return int((left_values != right_values).any(axis=1).sum())


def prepare_authorities() -> dict[str, dict[str, Any]]:
    source_frames = _source_frames()
    cache = ParquetCache(base_dir=DATA_DIR)
    records: dict[str, dict[str, Any]] = {}
    for ticker, source in source_frames.items():
        path = DATA_DIR / f"{ticker}.parquet"
        existing = cache.load(ticker)
        phantom_rows_filtered = 0
        if existing is None:
            combined = source.copy()
            action = "CREATED_FROM_LOCAL_KRX_RAW_SOURCE"
            rows_added = len(combined)
            added_dates: list[str] = []
            overlap_rows = 0
            mismatch_rows = 0
        else:
            existing = existing.copy()
            existing.index = pd.DatetimeIndex(existing.index).normalize()
            existing = existing.sort_index()
            if tuple(existing.columns) != base.REQUIRED_COLUMNS:
                raise AssertionError(f"{ticker}: existing raw columns differ")
            common = existing.index.intersection(source.index)
            overlap_rows = len(common)
            mismatch_rows = _field_mismatch_count(existing, source, common)
            if mismatch_rows:
                raise AssertionError(f"{ticker}: local KRX overlap mismatches={mismatch_rows}")
            additions = source.loc[source.index.difference(existing.index)]
            additions = additions.loc[additions.index <= SUPPORT_END]
            combined = pd.concat([existing, additions]).sort_index()
            combined = combined.loc[~combined.index.duplicated(keep="first")]
            rows_added = len(additions)
            added_dates = [value.strftime("%Y-%m-%d") for value in additions.index]
            action = "EXTENDED" if rows_added else "UNCHANGED_SUPPORT_ALREADY_PRESENT"
        if combined.index.max() < SUPPORT_END:
            raise AssertionError(f"{ticker}: local authority cannot reach support end")
        if existing is None or rows_added:
            cache.save(ticker, combined)
        records[ticker] = {
            "action": action,
            "rows_added": int(rows_added),
            "added_dates": added_dates,
            "phantom_rows_filtered": int(phantom_rows_filtered),
            "source_overlap_rows": int(overlap_rows),
            "source_overlap_field_mismatches": int(mismatch_rows),
            "source_rows_to_support": int(len(source)),
            "source_period": f"{source.index.min():%Y-%m-%d} ~ {source.index.max():%Y-%m-%d}",
        }
    return records


def _winner(v3: float, julia: float, *, higher_is_better: bool = True) -> str:
    if math.isclose(v3, julia, abs_tol=1e-9):
        return "tie"
    if higher_is_better:
        return "V3" if v3 > julia else "Julia"
    return "V3" if v3 < julia else "Julia"


def _direct_v3_julia(matched: pd.DataFrame, summary: Mapping[str, Any]) -> dict[str, Any]:
    v3 = matched.loc[matched["strategy"] == "V3"].set_index("entry_signal_date")
    julia = matched.loc[matched["strategy"] == "Julia"].set_index("entry_signal_date")
    common = v3.index.intersection(julia.index)
    delta = pd.to_numeric(julia.loc[common, "terminal_return_pct"]) - pd.to_numeric(v3.loc[common, "terminal_return_pct"])
    v3_match = summary["matched_summaries"]["V3"]
    julia_match = summary["matched_summaries"]["Julia"]
    metrics = {
        "mean_return_pct": {"V3": v3_match["mean_return_pct"], "Julia": julia_match["mean_return_pct"], "winner": _winner(v3_match["mean_return_pct"], julia_match["mean_return_pct"])},
        "median_return_pct": {"V3": v3_match["median_return_pct"], "Julia": julia_match["median_return_pct"], "winner": _winner(v3_match["median_return_pct"], julia_match["median_return_pct"])},
        "win_rate_pct": {"V3": v3_match["win_rate_pct"], "Julia": julia_match["win_rate_pct"], "winner": _winner(v3_match["win_rate_pct"], julia_match["win_rate_pct"])},
        "mean_mae_pct": {"V3": v3_match["mean_mae_pct"], "Julia": julia_match["mean_mae_pct"], "winner": _winner(v3_match["mean_mae_pct"], julia_match["mean_mae_pct"])},
    }
    return {
        "paired_count": int(len(common)),
        "mean_delta_pct_julia_minus_v3": round(float(delta.mean()), 6) if len(delta) else None,
        "median_delta_pct_julia_minus_v3": round(float(delta.median()), 6) if len(delta) else None,
        "julia_better_count": int((delta > 0).sum()),
        "v3_better_count": int((delta < 0).sum()),
        "same_count": int((delta == 0).sum()),
        "metric_comparison": metrics,
    }


def _augment_results(aggregate: dict[str, Any]) -> dict[str, Any]:
    for ticker, item in aggregate["etfs"].items():
        if item.get("data") is None:
            continue
        for run in base.RUNS:
            run_summary = item["runs"][run]
            if run_summary["status"] != "COMPLETE":
                continue
            matched_path = OUT_ROOT / ticker / run / "matched_trades.csv"
            matched = pd.read_csv(matched_path)
            run_summary["v3_vs_julia"] = _direct_v3_julia(matched, run_summary)
            _json_write(OUT_ROOT / ticker / run / "summary.json", run_summary)
        item["report"] = _sector_report(item)
        (OUT_ROOT / ticker / "report.md").write_text(item["report"], encoding="utf-8")
    aggregate["work_id"] = "SECTOR_INDEX_ETF_SIXTEEN_UNIVERSE_FOUR_STRATEGY_BACKTEST_V01"
    aggregate["starting_head"] = STARTING_HEAD
    aggregate["branch"] = BRANCH
    aggregate["liquidity_filter_applied"] = False
    aggregate["head_to_head"] = _head_to_head(aggregate)
    aggregate["status"] = "COMPLETE" if all(
        aggregate["etfs"][ticker]["status"] == "COMPLETE" for ticker in SECTOR_ETFS
    ) else "PARTIAL_DATA_GAP"
    _json_write(AGGREGATE_SUMMARY_PATH, aggregate)
    AGGREGATE_REPORT_PATH.write_text(_aggregate_report(aggregate), encoding="utf-8")
    return aggregate


def _head_to_head(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = (
        ("sequential_total_return", "strategies", "total_return_pct", True),
        ("sequential_cagr", "strategies", "cagr_pct", True),
        ("sequential_mdd", "strategies", "mdd_pct", True),
        ("matched_mean_return", "matched_summaries", "mean_return_pct", True),
        ("matched_median_return", "matched_summaries", "median_return_pct", True),
        ("matched_win_rate", "matched_summaries", "win_rate_pct", True),
        ("matched_mean_mae", "matched_summaries", "mean_mae_pct", True),
    )
    result: dict[str, Any] = {}
    for run in base.RUNS:
        result[run] = {}
        for label, section, field, higher_is_better in metrics:
            counts = {"V3_win": 0, "Julia_win": 0, "tie": 0}
            for ticker in SECTOR_ETFS:
                run_summary = aggregate["etfs"][ticker]["runs"][run]
                if run_summary["status"] != "COMPLETE":
                    continue
                v3 = float(run_summary[section]["V3"][field])
                julia = float(run_summary[section]["Julia"][field])
                winner = _winner(v3, julia, higher_is_better=higher_is_better)
                counts["V3_win" if winner == "V3" else "Julia_win" if winner == "Julia" else "tie"] += 1
            result[run][label] = counts
    return result


def _sector_report(item: Mapping[str, Any]) -> str:
    lines = [
        f"# {item['ticker']} {item['name']} Sector ETF Four Strategy Backtest",
        "",
        f"- status: `{item['status']}`",
        f"- authority: `{item['data']['path']}`",
        f"- period: `{item['data']['used_start']} ~ {item['data']['used_end']}` / `{item['data']['rows_used_to_support']}` rows",
        "- liquidity filter: `OFF / threshold 0`",
        "- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`",
        "- cost model: `GROSS / NO_COST_MODEL`",
        "",
    ]
    for run in base.RUNS:
        summary = item["runs"][run]
        if summary["status"] != "COMPLETE":
            lines.extend([f"## {run}", "", f"- status: `{summary['status']}`", f"- reason: `{summary.get('reason', '')}`", ""])
            continue
        lines.extend([f"## {run}", "", f"- common entries: `{summary['common_entry_count']}`", f"- matched identity: `{summary['matched_identity']}`", f"- paired vs V2: `{summary['paired_vs_v2']}`", f"- V3 vs Julia: `{summary['v3_vs_julia']}`", ""])
        rows = []
        for strategy in base.STRATEGIES + ("Buy & Hold",):
            metrics = summary["strategies"][strategy]
            rows.append({"strategy": strategy, "total": metrics.get("total_return_pct"), "cagr": metrics.get("cagr_pct"), "mdd": metrics.get("mdd_pct"), "exposure": metrics.get("exposure_ratio_pct"), "trades": metrics.get("trade_count")})
        lines.extend(["| strategy | total | cagr | mdd | exposure | trades |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        lines.extend(f"| {row['strategy']} | {row['total']} | {row['cagr']} | {row['mdd']} | {row['exposure']} | {row['trades']} |" for row in rows)
        lines.append("")
    return "\n".join(lines)


def _aggregate_report(aggregate: Mapping[str, Any]) -> str:
    lines = [
        "# SECTOR INDEX ETF SIXTEEN UNIVERSE FOUR STRATEGY BACKTEST V01",
        "",
        f"- overall status: `{aggregate['status']}`",
        "- V2/V3/V4/Julia rules unchanged",
        "- liquidity filter: `OFF / threshold 0` for all 16 ETFs",
        "- backtest network requests: `0`",
        "",
        "## ETF status",
        "",
        "| ticker | ETF | long range | same window | period | rows | entries LR/SW |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for ticker, name in SECTOR_ETFS.items():
        item = aggregate["etfs"][ticker]
        data = item.get("data") or {}
        period = f"{data.get('used_start', '')} ~ {data.get('used_end', '')}" if data else ""
        rows = data.get("rows_used_to_support", "") if data else ""
        entries = f"{item['runs']['long_range'].get('common_entry_count', '-')} / {item['runs']['same_window'].get('common_entry_count', '-')}"
        lines.append(f"| {ticker} | {name} | {item['runs']['long_range']['status']} | {item['runs']['same_window']['status']} | {period} | {rows} | {entries} |")
    for run in base.RUNS:
        lines.extend(["", f"## {run} sequential comparison", "", "| ticker | strategy | total | cagr | mdd | exposure | trades |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"])
        for ticker in SECTOR_ETFS:
            summary = aggregate["etfs"][ticker]["runs"][run]
            if summary["status"] != "COMPLETE":
                continue
            for strategy in base.STRATEGIES + ("Buy & Hold",):
                metrics = summary["strategies"][strategy]
                lines.append(f"| {ticker} | {strategy} | {metrics.get('total_return_pct')} | {metrics.get('cagr_pct')} | {metrics.get('mdd_pct')} | {metrics.get('exposure_ratio_pct')} | {metrics.get('trade_count', '')} |")
        lines.extend(["", "### V2 대비 우위 횟수", "", "```json", json.dumps(aggregate["wins"][run], ensure_ascii=False, indent=2), "```"])
        lines.extend(["", "### V3 vs Julia head-to-head", "", "| metric | V3 win | Julia win | tie |", "| --- | ---: | ---: | ---: |"])
        for metric, counts in aggregate["head_to_head"][run].items():
            lines.append(f"| {metric} | {counts['V3_win']} | {counts['Julia_win']} | {counts['tie']} |")
    long_total = aggregate["wins"]["long_range"]["sequential_total"]
    same_total = aggregate["wins"]["same_window"]["sequential_total"]
    lines.extend([
        "",
        "## Data-based answers",
        "",
        f"1. Sector ETF V3/Julia vs V2 sequential total-return wins: LONG RANGE V3 `{long_total['V3']}`, Julia `{long_total['Julia']}`; SAME WINDOW V3 `{same_total['V3']}`, Julia `{same_total['Julia']}`.",
        f"2. V3 vs Julia total/CAGR head-to-head: LONG RANGE `{aggregate['head_to_head']['long_range']['sequential_total_return']}` / `{aggregate['head_to_head']['long_range']['sequential_cagr']}`; SAME WINDOW `{aggregate['head_to_head']['same_window']['sequential_total_return']}` / `{aggregate['head_to_head']['same_window']['sequential_cagr']}`.",
        f"3. Julia MDD stability is represented by the MDD head-to-head counts: LONG RANGE `{aggregate['head_to_head']['long_range']['sequential_mdd']}`, SAME WINDOW `{aggregate['head_to_head']['same_window']['sequential_mdd']}`.",
        "4. Results are reported separately for semiconductors, automobiles, banks, healthcare, construction, and the other specified sectors in the ETF table above.",
        "5. Sector-specific V3/Julia strengths are represented by the per-ETF sequential and matched tables; no sector-specific rule or parameter was introduced.",
        f"6. V4 total/CAGR wins vs V2 are LONG RANGE `{aggregate['wins']['long_range']['sequential_total']['V4']}/{aggregate['wins']['long_range']['sequential_cagr']['V4']}` and SAME WINDOW `{aggregate['wins']['same_window']['sequential_total']['V4']}/{aggregate['wins']['same_window']['sequential_cagr']['V4']}`.",
        "7. This research records evidence only and makes no official promotion or retirement decision.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--tickers", nargs="+", choices=sorted(SECTOR_ETFS), default=None)
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")
    base.ETF_UNIVERSE = SECTOR_ETFS
    base.EXTENSION_RECORDS = prepare_authorities()
    base.OUT_ROOT = OUT_ROOT
    base.AGGREGATE_SUMMARY_PATH = AGGREGATE_SUMMARY_PATH
    base.AGGREGATE_REPORT_PATH = AGGREGATE_REPORT_PATH
    original_v2_kwargs = base._v2_kwargs

    def sector_v2_kwargs(ticker: str, name: str, daily: pd.DataFrame, panel: pd.DataFrame, context: Any, score: dict[str, Any], stage: dict[str, Any], allowed: set[pd.Timestamp] | None, start: pd.Timestamp) -> dict[str, Any]:
        kwargs = original_v2_kwargs(ticker, name, daily, panel, context, score, stage, allowed, start)
        kwargs["identity_lifecycle"] = IdentityLifecycle(
            ticker=ticker,
            isu_cd="ETF_PRICE_ONLY",
            market="ETF",
            effective_from=_date(daily.index.min()),
            effective_to=SUPPORT_END,
        )
        return kwargs

    base._v2_kwargs = sector_v2_kwargs
    selected_tickers = tuple(args.tickers or SECTOR_ETFS)
    audit = base.NetworkAudit()
    try:
        with base.network_guard(audit):
            aggregate = base.run_all(selected_tickers=selected_tickers, apply_liquidity_filter=False)
            aggregate = _augment_results(aggregate)
        aggregate["network_requests"] = audit.request_count
        _json_write(AGGREGATE_SUMMARY_PATH, aggregate)
        AGGREGATE_REPORT_PATH.write_text(_aggregate_report(aggregate), encoding="utf-8")
        if audit.request_count != 0:
            raise AssertionError(f"network requests={audit.request_count}")
        print(json.dumps({"status": aggregate["status"], "etf_status": {ticker: {run: aggregate["etfs"][ticker]["runs"][run]["status"] for run in base.RUNS} for ticker in SECTOR_ETFS}, "network_requests": audit.request_count}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"SECTOR ETF BACKTEST BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
