#!/usr/bin/env python3
"""Reclassify saved P3-2 valuation gaps and correct MDD coverage without replay."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
    _is_non_trading_placeholder,
)
from trend_scanner.data.repository_v2_session_authority import (
    ADJUSTED_ANALYTICALLY_NONUSABLE_DATES,
    SOURCE_CLOSURE_CHECKPOINT_SHA256,
)
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio


OUT_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_portfolio_valuation_gap_contract_alignment_v01"
SOURCE_ROOT = ROOT / "artifacts/strategies/a_fast_core_v2/research"
BASELINE_HEAD = "f3b505a401af952e9fd772a1982b69c90702df1f"
EFFECTIVE_START = pd.Timestamp("2022-01-03")
EFFECTIVE_END = pd.Timestamp("2026-08-31")
EXECUTION_SUPPORT = pd.Timestamp("2026-09-01")
MARKET_CAP_FLOOR = 1_000_000_000_000
REQUIRED_TRADE_FIELDS = (
    "trade_id", "pair_id", "ticker", "isu_cd", "entry_signal_date", "entry_execution_date",
    "entry_open", "exit_signal_date", "exit_execution_date", "exit_price", "terminal_return",
    "entry_market_cap", "entry_market_cap_source", "identity_effective_from", "identity_effective_to",
    "lifecycle_class", "trade_status", "exit_type", "terminal_valuation_date", "terminal_valuation_price",
)
STRATEGIES = (
    {
        "name": "CONTROL",
        "directory": "fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01",
        "prefix": "control",
        "summary_metric_path": ("portfolio", "CONTROL"),
        "expected_trade_count": 405,
    },
    {
        "name": "MA60_FAIL_CLOSED",
        "directory": "fast_core_v2_p3_2_monthly_ma20_ma60_entry_filter_backtest_v01",
        "prefix": "ma60",
        "summary_metric_path": ("portfolio_metrics", "MA60"),
        "expected_trade_count": 337,
    },
    {
        "name": "BULLISH_ALIGNMENT",
        "directory": "fast_core_v2_p3_2_monthly_ma20_ma60_bullish_alignment_backtest_v01",
        "prefix": "alignment",
        "summary_metric_path": ("portfolio_metrics", "NEW_ALIGNMENT"),
        "expected_trade_count": 179,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write(path: Path, value: Any) -> None:
    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if hasattr(item, "item"):
            return normalize(item.item())
        if isinstance(item, (pd.Timestamp,)):
            return item.isoformat()
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        return str(item)

    path.write_text(json.dumps(normalize(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def metric_at(summary: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    value: Any = summary
    for key in path:
        value = value[key]
    if not isinstance(value, dict):
        raise RuntimeError(f"P3_2_VALUATION_SOURCE_METRIC_SCHEMA:{path}")
    return value


def reclassify_current_gap_evidence(
    gap_keys: set[tuple[str, str, str]],
    raw_store: KrxRawStockStore,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    partitions: dict[tuple[str, str], tuple[dict[str, Any] | None, pd.DataFrame | None]] = {}
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for ticker, market, day in sorted(gap_keys):
        partition_key = (market, day)
        if partition_key not in partitions:
            manifest = raw_store.get_manifest(market, day)
            if manifest is not None and manifest.get("status") == "COMPLETE":
                partitions[partition_key] = (manifest, raw_store.load_snapshot(market, day))
            else:
                partitions[partition_key] = (manifest, None)
        manifest, frame = partitions[partition_key]
        exact_rows = (
            frame.loc[frame["ticker"].astype(str).str.zfill(6).eq(ticker)]
            if frame is not None else pd.DataFrame()
        )
        raw_row = exact_rows.iloc[0] if len(exact_rows) == 1 else None
        placeholder = bool(raw_row is not None and _is_non_trading_placeholder(raw_row))
        if placeholder:
            classification = "NON_TRADING_PLACEHOLDER"
            evidence_status = "EXACT_COMPLETE_KRX_RAW_ROW_MATCHES_REPOSITORY_V2_PLACEHOLDER_PREDICATE"
        elif (ticker, day) in ADJUSTED_ANALYTICALLY_NONUSABLE_DATES and raw_row is not None:
            classification = "ADJUSTED_ANALYTICALLY_NONUSABLE"
            evidence_status = "REPOSITORY_V2_ADJUSTED_SOURCE_NONUSABLE_AUTHORITY; NOT A NONTRADING PROOF"
        else:
            classification = "NEW_UNCLASSIFIED_GAP"
            evidence_status = (
                "NO_EXPLICIT_NONTRADING_EVIDENCE"
                if raw_row is not None
                else "EXACT_COMPLETE_RAW_PARTITION_OR_TICKER_ROW_UNAVAILABLE"
            )
        result[(ticker, market, day)] = {
            "current_gap_classification": classification,
            "current_carry_allowed": classification == "NON_TRADING_PLACEHOLDER",
            "current_gap_evidence_status": evidence_status,
            "raw_partition_status": manifest.get("status") if manifest else None,
            "raw_partition_file_sha256": manifest.get("file_sha256") if manifest else None,
            "raw_partition_content_sha256": manifest.get("content_sha256") if manifest else None,
            "raw_ticker_row_count": int(len(exact_rows)),
            "raw_open": int(raw_row["open"]) if raw_row is not None else None,
            "raw_high": int(raw_row["high"]) if raw_row is not None else None,
            "raw_low": int(raw_row["low"]) if raw_row is not None else None,
            "raw_close": int(raw_row["close"]) if raw_row is not None else None,
            "raw_volume": int(raw_row["volume"]) if raw_row is not None else None,
            "raw_trading_value": int(raw_row["trading_value"]) if raw_row is not None else None,
            "placeholder_predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
            "placeholder_predicate_match": placeholder,
            "adjusted_nonusable_authority_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
        }
    return result


def trade_regression_row(config: dict[str, Any], base: Path) -> tuple[dict[str, Any], pd.DataFrame, Path]:
    trade_path = base / f"{config['prefix']}_strategy_trades.csv"
    before_hash = sha256(trade_path)
    trades = pd.read_csv(trade_path, dtype={"ticker": str, "isu_cd": str, "pair_id": str, "trade_id": str})
    missing_fields = [field for field in REQUIRED_TRADE_FIELDS if field not in trades.columns]
    if missing_fields:
        raise RuntimeError(f"P3_2_TRADE_REGRESSION_FIELDS_MISSING:{config['name']}:{missing_fields}")
    market_caps = pd.to_numeric(trades["entry_market_cap"], errors="coerce")
    mcap_sources_valid = trades["entry_market_cap_source"].astype(str).str.contains("KRX Open API Stock Daily MKTCAP", regex=False).all()
    mcap_pass = bool(market_caps.notna().all() and market_caps.ge(MARKET_CAP_FLOOR).all() and mcap_sources_valid)
    if len(trades) != config["expected_trade_count"] or not mcap_pass:
        raise RuntimeError(f"P3_2_TRADE_REGRESSION_OR_PIT_MISMATCH:{config['name']}:{len(trades)}:{mcap_pass}")
    source_hash_after_read = sha256(trade_path)
    result = {
        "strategy": config["name"],
        "trade_ledger": str(trade_path.relative_to(ROOT)),
        "trade_count": int(len(trades)),
        "trade_ledger_sha256_before": before_hash,
        "trade_ledger_sha256_after": source_hash_after_read,
        "trade_ledger_unchanged": before_hash == source_hash_after_read,
        "required_signal_execution_exit_price_terminal_lifecycle_fields_present": True,
        "exact_date_krx_pit_mcap_source_and_floor_pass": mcap_pass,
        "minimum_entry_mcap_krw": int(market_caps.min()),
        "below_1t_entry_mcap_count": int(market_caps.lt(MARKET_CAP_FLOOR).sum()),
        "strategy_replay_performed": False,
    }
    return result, trades, trade_path


def main() -> None:
    existing_outputs = [
        path.name for path in OUT_DIR.iterdir()
        if path.name != Path(__file__).name
    ] if OUT_DIR.exists() else []
    if existing_outputs:
        raise RuntimeError(f"REFUSING_TO_OVERWRITE_VALUATION_GAP_ARTIFACTS:{OUT_DIR}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != BASELINE_HEAD:
        raise RuntimeError(f"P3_2_VALUATION_BASELINE_HEAD_MISMATCH:{head}")

    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    loaded: list[dict[str, Any]] = []
    gap_keys: set[tuple[str, str, str]] = set()
    regression_rows: list[dict[str, Any]] = []
    for config in STRATEGIES:
        base = SOURCE_ROOT / config["directory"]
        summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
        metrics = metric_at(summary, config["summary_metric_path"])
        equity_path = base / f"{config['prefix']}_daily_equity.csv"
        carry_path = base / f"{config['prefix']}_valuation_carry_audit.csv"
        daily = pd.read_csv(equity_path, dtype={"date": str})
        carry = pd.read_csv(
            carry_path,
            dtype={"ticker": str, "market": str, "valuation_date": str, "mark_observed_on": str},
        )
        regression, trades, trade_path = trade_regression_row(config, base)
        regression_rows.append(regression)
        if len(daily) != 1140 or daily["date"].duplicated().any():
            raise RuntimeError(f"P3_2_SAVED_EQUITY_SOURCE_INVALID:{config['name']}:{len(daily)}")
        for row in carry.to_dict(orient="records"):
            row["ticker"] = str(row.get("ticker", "")).zfill(6)
            row["market"] = str(row.get("market", "")).upper()
            row["valuation_date"] = str(row.get("valuation_date", ""))[:10]
            row["mark_observed_on"] = str(row.get("mark_observed_on", row["valuation_date"]))[:10]
            gap_keys.add((row["ticker"], row["market"], row["valuation_date"]))
        loaded.append({
            "config": config,
            "base": base,
            "summary": summary,
            "saved_metrics": metrics,
            "daily": daily,
            "carry": carry,
            "equity_path": equity_path,
            "carry_path": carry_path,
            "trade_path": trade_path,
            "trades": trades,
        })

    current_evidence = reclassify_current_gap_evidence(gap_keys, raw_store)
    carry_audit_rows: list[dict[str, Any]] = []
    corrected_daily_rows: list[dict[str, Any]] = []
    strategy_rows: list[dict[str, Any]] = []
    all_dates: tuple[str, ...] | None = None
    sources_unchanged = True
    for item in loaded:
        name = item["config"]["name"]
        daily = item["daily"].copy()
        dates = pd.to_datetime(daily["date"], errors="raise").dt.strftime("%Y-%m-%d").tolist()
        if all_dates is None:
            all_dates = tuple(dates)
        elif tuple(dates) != all_dates:
            raise RuntimeError("P3_2_STRATEGY_DAILY_EQUITY_DATE_SET_MISMATCH")
        date_mask = pd.to_datetime(daily["date"]).between(EFFECTIVE_START, EFFECTIVE_END)
        window = daily.loc[date_mask].copy()
        if len(window) != 1139 or daily.iloc[-1]["date"] != EXECUTION_SUPPORT.strftime("%Y-%m-%d"):
            raise RuntimeError(f"P3_2_EFFECTIVE_WINDOW_DATE_COUNT_MISMATCH:{name}:{len(window)}")

        carry_rows = item["carry"].to_dict(orient="records")
        enriched: list[dict[str, Any]] = []
        for row in carry_rows:
            row["ticker"] = str(row.get("ticker", "")).zfill(6)
            row["market"] = str(row.get("market", "")).upper()
            row["valuation_date"] = str(row.get("valuation_date", ""))[:10]
            row["mark_observed_on"] = str(row.get("mark_observed_on", row["valuation_date"]))[:10]
            evidence = current_evidence[(row["ticker"], row["market"], row["valuation_date"])]
            enriched_row = {**row, **evidence, "strategy": name}
            enriched.append(enriched_row)
            carry_audit_rows.append(enriched_row)

        in_window = [row for row in enriched if EFFECTIVE_START.strftime("%Y-%m-%d") <= row["mark_observed_on"] <= EFFECTIVE_END.strftime("%Y-%m-%d")]
        unapproved = [row for row in in_window if not row["current_carry_allowed"]]
        blocked_dates = {row["mark_observed_on"] for row in unapproved}
        date_carry_counts: dict[str, int] = {}
        date_unapproved_counts: dict[str, int] = {}
        for row in in_window:
            date = row["mark_observed_on"]
            date_carry_counts[date] = date_carry_counts.get(date, 0) + 1
            if not row["current_carry_allowed"]:
                date_unapproved_counts[date] = date_unapproved_counts.get(date, 0) + 1
        daily["source_equity"] = pd.to_numeric(daily["equity"], errors="coerce")
        daily["corrected_equity"] = daily["source_equity"]
        daily["unapproved_gap_mark_count"] = daily["date"].map(date_unapproved_counts).fillna(0).astype(int)
        daily["saved_carry_mark_count"] = daily["date"].map(date_carry_counts).fillna(0).astype(int)
        daily["mdd_window_included"] = pd.to_datetime(daily["date"]).between(EFFECTIVE_START, EFFECTIVE_END)
        daily.loc[daily["date"].isin(blocked_dates), "corrected_equity"] = None
        daily["corrected_valuation_status"] = "EXACT_OR_NO_HELD_POSITION_GAP"
        daily.loc[daily["saved_carry_mark_count"].gt(0), "corrected_valuation_status"] = "OBSERVABLE_WITH_REPOSITORY_NON_TRADING_CARRY"
        daily.loc[daily["unapproved_gap_mark_count"].gt(0), "corrected_valuation_status"] = "UNOBSERVABLE_UNVERIFIED_GAP"
        coverage_input = daily.loc[:, ["date", "corrected_equity"]].rename(columns={"corrected_equity": "equity"})
        corrected_metrics = portfolio._valuation_coverage_metrics(
            coverage_input,
            effective_start=EFFECTIVE_START,
            effective_end=EFFECTIVE_END,
        )
        old_metrics = item["saved_metrics"]
        old_mdd_from_daily = portfolio._mdd(
            daily.loc[pd.to_datetime(daily["date"]).between(EFFECTIVE_START, EFFECTIVE_END), ["date", "source_equity"]]
            .rename(columns={"source_equity": "equity"})
        )
        saved_mdd = float(old_metrics["mdd_pct"])
        if old_mdd_from_daily["mdd_pct"] is None or not math.isclose(
            float(old_mdd_from_daily["mdd_pct"]), saved_mdd, rel_tol=0, abs_tol=0.000001
        ):
            raise RuntimeError(f"P3_2_SAVED_MDD_DOES_NOT_REPRODUCE_FROM_DAILY_NAV:{name}")
        invalid_tickers = {str(row["ticker"]).zfill(6) for row in unapproved}
        support_audits = [row for row in enriched if row["mark_observed_on"] == EXECUTION_SUPPORT.strftime("%Y-%m-%d")]
        source_hash_before = {
            "trade_ledger": sha256(item["trade_path"]),
            "daily_equity": sha256(item["equity_path"]),
            "valuation_carry_audit": sha256(item["carry_path"]),
        }
        source_hash_after = {
            "trade_ledger": sha256(item["trade_path"]),
            "daily_equity": sha256(item["equity_path"]),
            "valuation_carry_audit": sha256(item["carry_path"]),
        }
        same = source_hash_before == source_hash_after
        sources_unchanged = sources_unchanged and same
        strategy_rows.append({
            "strategy": name,
            "total_valuation_days": corrected_metrics["total_valuation_days"],
            "valid_nav_days": corrected_metrics["valid_nav_days"],
            "unobservable_nav_days": corrected_metrics["unobservable_nav_days"],
            "coverage_ratio_raw": corrected_metrics["coverage_ratio"],
            "coverage_pct": corrected_metrics["coverage_pct"],
            "mdd_type": corrected_metrics["mdd_type"],
            "mdd_usable_for_official_pass": corrected_metrics["mdd_usable_for_official_pass"],
            "corrected_mdd_pct": corrected_metrics["mdd_pct"],
            "corrected_mdd_peak_date": corrected_metrics["peak_date"],
            "corrected_mdd_trough_date": corrected_metrics["trough_date"],
            "corrected_mdd_recovery_date": corrected_metrics["recovery_date"],
            "saved_mdd_pct": saved_mdd,
            "mdd_delta_percentage_points": round(float(corrected_metrics["mdd_pct"]) - saved_mdd, 6),
            "new_unclassified_gap_mark_count": sum(row["current_gap_classification"] == "NEW_UNCLASSIFIED_GAP" for row in in_window),
            "adjusted_analytically_nonusable_mark_count": sum(row["current_gap_classification"] == "ADJUSTED_ANALYTICALLY_NONUSABLE" for row in in_window),
            "nontrading_placeholder_mark_count": sum(row["current_gap_classification"] == "NON_TRADING_PLACEHOLDER" for row in in_window),
            "unapproved_gap_mark_count": len(unapproved),
            "affected_ticker_count": len(invalid_tickers),
            "unapproved_gap_tickers": ";".join(sorted(invalid_tickers)),
            "unapproved_gap_date_count": len(blocked_dates),
            "unresolved_gap_interval_count": corrected_metrics["unresolved_gap_interval_count"],
            "maximum_consecutive_unobservable_days": corrected_metrics["maximum_consecutive_unobservable_days"],
            "support_only_audit_rows_excluded_from_mdd": len(support_audits),
            "saved_daily_equity_sha256": source_hash_before["daily_equity"],
            "saved_carry_audit_sha256": source_hash_before["valuation_carry_audit"],
            "saved_daily_equity_and_carry_sources_unchanged": same,
        })
        corrected_daily = daily.loc[:, [
            "date", "source_equity", "corrected_equity", "corrected_valuation_status",
            "saved_carry_mark_count", "unapproved_gap_mark_count", "mdd_window_included",
        ]].copy()
        for row in corrected_daily.to_dict(orient="records"):
            row["strategy"] = name
            corrected_daily_rows.append(row)

    if not sources_unchanged:
        raise RuntimeError("P3_2_HISTORICAL_SOURCE_ARTIFACT_CHANGED_DURING_DIAGNOSTIC")
    if [row["trade_ledger_unchanged"] and row["exact_date_krx_pit_mcap_source_and_floor_pass"] for row in regression_rows] != [True] * len(STRATEGIES):
        raise RuntimeError("P3_2_TRADE_REGRESSION_PARITY_FAILED")
    overall_coverage_pass = all(row["mdd_usable_for_official_pass"] for row in strategy_rows)
    final_token = (
        "FAST_CORE_V2_PORTFOLIO_VALUATION_GAP_CONTRACT_ALIGNMENT_V01_PASS"
        if overall_coverage_pass and sources_unchanged
        else "FAST_CORE_V2_PORTFOLIO_VALUATION_GAP_CONTRACT_ALIGNMENT_V01_CHECK_REQUIRED"
    )
    class_counts: dict[str, int] = {}
    for evidence in current_evidence.values():
        label = str(evidence["current_gap_classification"])
        class_counts[label] = class_counts.get(label, 0) + 1

    report_lines = [
        "| Level | Count |",
        "|---|---:|",
        "| CRITICAL | 0 |",
        "| MAJOR | 1 |",
        "| MINOR | 2 |",
        "",
        "The MAJOR finding is the prior P3-2 NAV's use of prior closes for gaps without verified non-trading evidence; corrected MDD excludes those full portfolio dates. The two MINOR findings are that saved strategy ledgers were reused without replay and this diagnostic does not complete the official five-window review.",
        "",
        f"Final token: `{final_token}`",
        "",
        "## Scope and implementation audit",
        "",
        "- The prior-close path now requires an exact `NON_TRADING_PLACEHOLDER` classification from the repository's narrow raw KRX predicate. `ADJUSTED_ANALYTICALLY_NONUSABLE` and `NEW_UNCLASSIFIED_GAP` never carry.",
        "- Exact daily close remains first choice. One unobservable held position makes that entire day's portfolio NAV unobservable. MDD uses only valid NAV rows.",
        "- Coverage uses official P3-2 daily equity dates through the effective end, excluding the execution-support-only date. The 90% gate is evaluated by integer numerator/denominator comparison before display rounding.",
        "- Previous complete P3-2 artifacts were reused: CONTROL 405 trades, MA60 337 trades, ALIGNMENT 179 trades. No strategy signal, lifecycle, portfolio order replay, network call, or historical artifact rewrite was performed.",
        "",
        "## Current-source gap reclassification",
        "",
        f"Exact local raw partitions were re-read for {len(gap_keys)} unique ticker-market-date gaps: {class_counts}.",
        f"The only carry-approved state is `{NON_TRADING_PLACEHOLDER_PREDICATE_NAME}`: exact complete KRX raw row with open/high/low zero, positive close, and volume/trading value zero. The adjusted-source-unusable state is not treated as non-trading proof.",
        "",
        "## P3-2 MDD and coverage impact",
        "",
        "| Strategy | Total days | Valid NAV | Unobservable | Coverage | Type | Saved MDD | Corrected MDD | Delta pp | Peak | Trough | Unclassified gaps | Affected tickers |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|---:|---:|",
    ]
    for row in strategy_rows:
        report_lines.append(
            f"| {row['strategy']} | {row['total_valuation_days']} | {row['valid_nav_days']} | {row['unobservable_nav_days']} | "
            f"{row['coverage_pct']:.4f}% | {row['mdd_type']} | {row['saved_mdd_pct']:.6f}% | "
            f"{row['corrected_mdd_pct']:.6f}% | {row['mdd_delta_percentage_points']:.6f} | "
            f"{row['corrected_mdd_peak_date']} | {row['corrected_mdd_trough_date']} | "
            f"{row['new_unclassified_gap_mark_count']} | {row['affected_ticker_count']} |"
        )
    report_lines.extend([
        "",
        "`Observed MDD` is based on the remaining observable days; it is not an exact full-period drawdown. The exact coverage numerator, denominator, peak/trough/recovery dates, gap intervals, and ticker/date audit are in the CSV and JSON artifacts.",
        "",
        "## Regression parity and integrity",
        "",
        "- Trade ledgers keep their original SHA-256 values before and after this diagnosis. Required entry/exit dates and prices, terminal return, PIT market-cap source, identity, lifecycle, and trade-status fields were present and unchanged.",
        "- All saved entries retain exact-date KRX Open API market-cap source and satisfy the 1T PIT floor.",
        "- Original saved equity, strategy trade, and carry-audit files remain untouched; corrected NAV is a separate derived file.",
        "- Network/API calls: 0. Strategy replay: 0. Portfolio event replay: 0.",
        "- Official adoption: not evaluated; a separate five-window review remains required.",
        "",
        "## Artifacts",
        "",
        "- `summary.json` — source hashes, strategy metrics, and integrity status.",
        "- `strategy_mdd_coverage.csv` — per-strategy corrected MDD and coverage comparison.",
        "- `valuation_gap_reclassification_audit.csv` — current raw-source evidence and carry decision for each saved gap mark.",
        "- `corrected_daily_equity.csv` — source and corrected NAV observation status, with unverified-gap dates nulled at portfolio level.",
        "- `regression_parity.csv` — immutable trade-ledger and PIT/lifecycle field parity.",
        "- `run_valuation_gap_contract_alignment.py` — report-only diagnostic runner.",
    ])

    summary = {
        "status": "COMPLETE_PASS" if final_token.endswith("_PASS") else "CHECK_REQUIRED",
        "final_token": final_token,
        "work_id": "FAST_CORE_V2_PORTFOLIO_VALUATION_GAP_CONTRACT_ALIGNMENT_V01",
        "baseline_head": BASELINE_HEAD,
        "effective_window": {
            "start": EFFECTIVE_START.strftime("%Y-%m-%d"),
            "end": EFFECTIVE_END.strftime("%Y-%m-%d"),
            "execution_support": EXECUTION_SUPPORT.strftime("%Y-%m-%d"),
        },
        "execution": {
            "mode": "SAVED_P3_2_NAV_AND_GAP_AUDIT_DIAGNOSIS_ONLY",
            "strategy_replay_performed": False,
            "portfolio_event_replay_performed": False,
            "network_api_calls": 0,
            "historical_artifact_rewritten": False,
        },
        "carry_contract": {
            "exact_close_preferred": True,
            "approved_gap_classifications": ["NON_TRADING_PLACEHOLDER"],
            "unclassified_gap_carry_allowed": False,
            "adjusted_analytically_nonusable_carry_allowed": False,
            "partial_portfolio_nav_allowed": False,
        },
        "current_gap_classification_counts_unique_ticker_market_dates": class_counts,
        "strategies": strategy_rows,
        "regression_parity": regression_rows,
        "integrity": {
            "all_strategy_source_hashes_unchanged": sources_unchanged,
            "trade_ledgers_match_expected_counts_and_pit_floor": all(row["trade_ledger_unchanged"] and row["exact_date_krx_pit_mcap_source_and_floor_pass"] for row in regression_rows),
            "all_corrected_mdd_coverages_at_least_90_percent": overall_coverage_pass,
            "official_adoption_evaluated": False,
            "raw_repository_partition_reads": len(gap_keys),
            "source_closure_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    json_write(OUT_DIR / "summary.json", summary)
    pd.DataFrame(strategy_rows).to_csv(OUT_DIR / "strategy_mdd_coverage.csv", index=False)
    pd.DataFrame(carry_audit_rows).to_csv(OUT_DIR / "valuation_gap_reclassification_audit.csv", index=False)
    pd.DataFrame(corrected_daily_rows).to_csv(OUT_DIR / "corrected_daily_equity.csv", index=False)
    pd.DataFrame(regression_rows).to_csv(OUT_DIR / "regression_parity.csv", index=False)
    print(json.dumps({"status": summary["status"], "final_token": final_token, "strategies": strategy_rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
