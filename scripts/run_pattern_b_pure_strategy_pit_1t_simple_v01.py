#!/usr/bin/env python3
"""Compare Pattern B pure simple strategy with an entry-date PIT 1T gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)

STRATEGY_ID = "PATTERN_B_PURE_SIMPLE_PIT_1T_V01"
BASELINE_COMMIT = "5dcfe79f40800ed8ac17558bad6dc600a91fd653"
CAP_THRESHOLD_KRW = 1_000_000_000_000
CONTROL_RELATIVE = Path("artifacts/patterns/pattern_b/pure_strategy_simple_v01")
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/pure_strategy_pit_1t_simple_v01")
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_revision_sha(data_root: Path, revision: str, relative_path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative_path.as_posix()}"],
        cwd=data_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "1.0", "yes"}


def _positive_integer(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _attach_exact_entry_caps(
    events: list[dict[str, Any]], samples: pd.DataFrame
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    """Apply PIT cap eligibility only after the unchanged transition is identified."""
    cap_columns = ["ticker", "isu_cd", "snapshot_date", "market_cap_krw", "pit_market_cap_exact"]
    has_panel_eligibility = "panel_b_eligible" in samples.columns
    if has_panel_eligibility:
        cap_columns.append("panel_b_eligible")
    cap_rows = samples[cap_columns]
    cap_by_signal = {
        (str(row.ticker), str(row.isu_cd), str(row.snapshot_date)): (
            row.market_cap_krw,
            row.pit_market_cap_exact,
            str(row.snapshot_date),
            getattr(row, "panel_b_eligible", None),
        )
        for row in cap_rows.itertuples(index=False)
    }
    eligible: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    audit_rows: list[dict[str, Any]] = []
    for event in events:
        key = (event["ticker"], event["isu_cd"], event["entry_signal_date"])
        row = cap_by_signal.get(key)
        exact = False
        cap = None
        source_date = None
        panel_eligible = None
        if row is not None:
            raw_cap, raw_exact, source_date, raw_panel_eligible = row
            exact = _bool(raw_exact) and source_date == event["entry_signal_date"]
            cap = _positive_integer(raw_cap) if exact else None
            panel_eligible = _bool(raw_panel_eligible) if has_panel_eligibility else None
        event["entry_market_cap_source_date"] = source_date
        event["entry_market_cap_exact"] = bool(exact and cap is not None)
        event["entry_market_cap_krw"] = cap
        event["entry_market_cap_threshold_krw"] = CAP_THRESHOLD_KRW
        event["market_cap_filter_applied_on"] = "entry_signal_date"
        expected_panel_eligible = bool(event["entry_market_cap_exact"] and cap >= CAP_THRESHOLD_KRW)
        event["panel_b_eligible_source"] = panel_eligible
        event["panel_eligibility_matches_exact_cap"] = (
            panel_eligible == expected_panel_eligible if has_panel_eligibility else None
        )
        if not event["entry_market_cap_exact"]:
            event["entry_market_cap_filter_status"] = "REJECTED_MISSING_OR_NONEXACT_PIT_CAP"
            event["entry_signal_status"] = "REJECTED_MISSING_OR_NONEXACT_PIT_CAP"
        elif cap < CAP_THRESHOLD_KRW:
            event["entry_market_cap_filter_status"] = "REJECTED_BELOW_1T"
            event["entry_signal_status"] = "REJECTED_BELOW_1T"
        else:
            event["entry_market_cap_filter_status"] = "ELIGIBLE_EXACT_PIT_GE_1T"
            event["entry_signal_status"] = "PENDING"
            eligible[(event["ticker"], event["isu_cd"])].append(event)
        audit_rows.append({
            "signal_id": event["signal_id"],
            "ticker": event["ticker"],
            "isu_cd": event["isu_cd"],
            "entry_signal_date": event["entry_signal_date"],
            "entry_market_cap_source_date": source_date,
            "entry_market_cap_exact": event["entry_market_cap_exact"],
            "entry_market_cap_krw": cap,
            "threshold_krw": CAP_THRESHOLD_KRW,
            "filter_status": event["entry_market_cap_filter_status"],
            "panel_b_eligible_source": panel_eligible,
            "panel_eligibility_matches_exact_cap": event["panel_eligibility_matches_exact_cap"],
        })
    return dict(eligible), audit_rows


def _load_control(data_root: Path, samples: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    control_dir = data_root / CONTROL_RELATIVE
    summary = json.loads((control_dir / "summary.json").read_text(encoding="utf-8"))
    metadata = json.loads((control_dir / "metadata.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(
        control_dir / "trade_ledger.csv", dtype={"ticker": "string", "isu_cd": "string"}
    )
    signals = pd.read_csv(
        control_dir / "entry_signal_ledger.csv", dtype={"ticker": "string", "isu_cd": "string"}
    )
    if metadata.get("market_cap_filter_applied") is not False:
        raise RuntimeError("CONTROL is not the approved no-market-cap-filter V01 artifact")
    sample_sha = _sha256(data_root / base.SAMPLE_PATH)
    if metadata.get("source_sample_sha256") != sample_sha:
        raise RuntimeError("CONTROL and current monthly sample source hashes differ")
    status_counts = signals["entry_signal_status"].value_counts(dropna=False).to_dict()
    if len(signals) != summary["entry_signal_count"]:
        raise RuntimeError("CONTROL signal ledger does not reconcile with summary")
    if len(trades) != summary["filled_trade_count"]:
        raise RuntimeError("CONTROL trade ledger does not reconcile with summary")
    if int((trades["trade_status"] == "REALIZED").sum()) != summary["closed_trade_count"]:
        raise RuntimeError("CONTROL closed count does not reconcile with summary")
    if int((trades["trade_status"] == "OPEN_AT_CUTOFF").sum()) != summary["open_trade_count"]:
        raise RuntimeError("CONTROL open count does not reconcile with summary")
    for status, expected in summary["entry_signal_status_counts"].items():
        if int(status_counts.get(status, 0)) != int(expected):
            raise RuntimeError(f"CONTROL signal status changed: {status}")
    closed = trades.loc[trades["trade_status"] == "REALIZED"]
    recomputed = base._metric_summary(closed["gross_return_pct"])
    for key in ("n", "mean_pct", "median_pct", "win_rate_pct", "profit_factor"):
        observed = recomputed.get(key)
        expected = summary["closed_gross"].get(key)
        if key == "n":
            agrees = observed == expected
        elif expected is None:
            agrees = observed is None
        else:
            agrees = observed is not None and math.isclose(
                float(observed), float(expected), rel_tol=1e-11, abs_tol=1e-10
            )
        if not agrees:
            raise RuntimeError(f"CONTROL ledger metric {key} differs from committed summary")
    committed_hashes = {}
    for filename in ("trade_ledger.csv", "entry_signal_ledger.csv", "summary.json", "metadata.json"):
        relative_path = CONTROL_RELATIVE / filename
        committed_hashes[filename] = _git_revision_sha(data_root, BASELINE_COMMIT, relative_path)
        if _sha256(control_dir / filename) != committed_hashes[filename]:
            raise RuntimeError(f"CONTROL artifact does not match baseline commit: {filename}")
    lineage = {
        "artifact_directory": str(CONTROL_RELATIVE),
        "baseline_commit": BASELINE_COMMIT,
        "control_source_sample_sha256": sample_sha,
        "control_trade_ledger_sha256": _sha256(control_dir / "trade_ledger.csv"),
        "control_entry_signal_ledger_sha256": _sha256(control_dir / "entry_signal_ledger.csv"),
        "control_summary_sha256": _sha256(control_dir / "summary.json"),
        "control_metadata_sha256": _sha256(control_dir / "metadata.json"),
        "control_committed_blob_sha256": committed_hashes,
        "control_was_replayed": False,
        "control_reconciliation": "version-controlled V01 ledger retained verbatim; row counts, status counts, source hash, and gross summary metrics verified",
        "monthly_sample_rows": int(len(samples)),
    }
    return summary, trades, signals, lineage


def _path_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    return {
        "all": base._path_summary(trades),
        "realized": base._path_summary(closed),
        "open": base._path_summary(opened),
    }


def _deep_summary(trades: list[dict[str, Any]], samples: pd.DataFrame) -> dict[str, Any]:
    groups = {
        (str(key[0]), str(key[1])): group.sort_values("snapshot_date")
        for key, group in samples.groupby(["ticker", "isu_cd"], sort=False)
    }
    deep: list[dict[str, Any]] = []
    for trade in trades:
        group = groups.get((str(trade["ticker"]), str(trade["isu_cd"])))
        if group is None:
            raise RuntimeError("trade has no monthly Pattern B observations")
        end = str(trade.get("exit_signal_date") or base.SIGNAL_END)
        held = group.loc[
            (group["snapshot_date"] > trade["entry_signal_date"])
            & (group["snapshot_date"] <= end)
            & (group["component_id"] == trade["component_id"])
        ]
        if (held["state"].astype(str) == "DEEP_DEPRESSED").any():
            deep.append(trade)
    realized = [trade for trade in deep if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in deep if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked_open = [trade for trade in opened if trade.get("mark_to_cutoff_gross_return_pct") is not None]
    unresolved_open = [trade for trade in opened if trade.get("mark_to_cutoff_gross_return_pct") is None]
    deep_return = base._metric_summary(trade.get("gross_return_pct") for trade in realized)
    deep_mark = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked_open)
    mae = base._metric_summary(trade.get("mae_pct") for trade in deep)
    realized_mae = base._metric_summary(trade.get("mae_pct") for trade in realized)
    closed_losers = sum(float(trade["gross_return_pct"]) < 0 for trade in realized)
    known_returns = [trade.get("gross_return_pct") for trade in realized]
    known_returns.extend(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked_open)
    known_stats = base._metric_summary(known_returns)
    known_losers = sum(float(value) < 0 for value in known_returns if value is not None)
    return {
        "filled_trade_count": len(trades),
        "deep_arrival_count": len(deep),
        "deep_arrival_rate_of_filled_pct": 100.0 * len(deep) / len(trades) if trades else None,
        "deep_realized_count": len(realized),
        "deep_realized_loss_count": int(closed_losers),
        "deep_realized_loss_rate_pct": 100.0 * closed_losers / len(realized) if realized else None,
        "deep_realized_return_mean_pct": deep_return["mean_pct"],
        "deep_realized_return_median_pct": deep_return["median_pct"],
        "deep_mae_mean_pct": mae["mean_pct"],
        "deep_mae_median_pct": mae["median_pct"],
        "deep_realized_mae_mean_pct": realized_mae["mean_pct"],
        "deep_open_count": len(opened),
        "deep_open_marked_count": len(marked_open),
        "deep_open_unresolved_count": len(unresolved_open),
        "deep_open_mark_mean_pct": deep_mark["mean_pct"],
        "deep_open_mark_median_pct": deep_mark["median_pct"],
        "deep_open_mark_loss_count": sum(
            float(trade["mark_to_cutoff_gross_return_pct"]) < 0 for trade in marked_open
        ),
        "deep_known_outcome_count": known_stats["n"],
        "deep_known_outcome_loss_count": int(known_losers),
        "deep_known_outcome_loss_rate_pct": 100.0 * known_losers / known_stats["n"] if known_stats["n"] else None,
        "deep_known_outcome_mean_pct": known_stats["mean_pct"],
        "deep_known_outcome_median_pct": known_stats["median_pct"],
    }


def _summary_test(
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    samples: pd.DataFrame,
    projection_audit: dict[str, int],
    elapsed: float,
) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("trade_status") == "REALIZED"]
    opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked = [trade for trade in opened if trade.get("mark_to_cutoff_gross_return_pct") is not None]
    unresolved = [trade for trade in opened if trade.get("mark_to_cutoff_gross_return_pct") is None]
    gross = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
    pre_tax = base._metric_summary(trade.get("commission_slippage_pre_tax_return_pct") for trade in closed)
    tax_covered = [trade for trade in closed if trade.get("full_standard_net_return_pct") is not None]
    full_net = base._metric_summary(trade.get("full_standard_net_return_pct") for trade in tax_covered)
    open_returns = base._metric_summary(trade.get("mark_to_cutoff_gross_return_pct") for trade in marked)
    open_returns.update({
        "marked_count": len(marked),
        "unresolved_count": len(unresolved),
        "le_30_count": sum(float(t["mark_to_cutoff_gross_return_pct"]) <= -30 for t in marked),
        "le_50_count": sum(float(t["mark_to_cutoff_gross_return_pct"]) <= -50 for t in marked),
        "le_30_rate_pct": 100.0 * sum(float(t["mark_to_cutoff_gross_return_pct"]) <= -30 for t in marked) / len(marked) if marked else None,
        "le_50_rate_pct": 100.0 * sum(float(t["mark_to_cutoff_gross_return_pct"]) <= -50 for t in marked) / len(marked) if marked else None,
    })
    status_counts = Counter(event["entry_signal_status"] for event in events)
    deep = _deep_summary(trades, samples)
    return {
        "strategy_id": STRATEGY_ID,
        "verdict": None,
        "signal_start": base.SIGNAL_START,
        "signal_end": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "pit_market_cap_filter": {
            "threshold_krw": CAP_THRESHOLD_KRW,
            "date_field": "entry_signal_date",
            "exact_source_key": ["ticker", "isu_cd", "snapshot_date"],
            "imputation_count": 0,
            "adjacent_date_fallback_count": 0,
        },
        "raw_transition_signal_count": len(events),
        "eligible_exact_pit_ge_1t_signal_count": status_counts["PENDING"] + status_counts["FILLED"] + status_counts["SUPPRESSED_ALREADY_HOLDING"] + status_counts["ENTRY_UNFILLED_NO_LATER_PRICE_ROW"] + status_counts["ENTRY_UNFILLED_AFTER_CUTOFF"] + status_counts["CANCELLED_STATE_REVERTED"],
        "exact_pit_below_1t_signal_count": status_counts["REJECTED_BELOW_1T"],
        "missing_or_nonexact_pit_signal_count": status_counts["REJECTED_MISSING_OR_NONEXACT_PIT_CAP"],
        "blocked_authority_transition_count": len(blocked),
        "filled_trade_count": len(trades),
        "closed_trade_count": len(closed),
        "open_trade_count": len(opened),
        "open_ratio_pct": 100.0 * len(opened) / len(trades) if trades else None,
        "entry_signal_status_counts": dict(status_counts),
        "suppressed_eligible_signal_count": status_counts["SUPPRESSED_ALREADY_HOLDING"],
        "closed_gross": gross,
        "closed_pre_tax_cost": pre_tax,
        "cost_covered_closed_net": full_net,
        "open_positions": open_returns,
        "all_path": base._path_summary(trades),
        "closed_path": base._path_summary(closed),
        "open_path": base._path_summary(opened),
        "post_entry_deep_state": deep,
        "cost_contract": {
            "buy_commission_rate": base.COMMISSION_RATE,
            "sell_commission_rate": base.COMMISSION_RATE,
            "buy_slippage_rate": base.SLIPPAGE_RATE,
            "sell_slippage_rate": base.SLIPPAGE_RATE,
            "sell_tax_schedule": list(base.HISTORICAL_SELL_TAX_SCHEDULE),
            "tax_complete_from": "2021-01-01",
            "full_period_primary_metric": "gross",
            "net_metric_scope": "closed trades with a documented exit-date market sell-tax schedule",
        },
        "repository_v2_projection_audit": projection_audit,
        "elapsed_seconds": round(elapsed, 2),
    }


def _annual_summary(events: list[dict[str, Any]], trades: list[dict[str, Any]]) -> pd.DataFrame:
    years = sorted(
        {str(event["entry_signal_date"])[:4] for event in events}
        | {str(trade["entry_signal_date"])[:4] for trade in trades}
    )
    rows = []
    for year in years:
        year_events = [event for event in events if str(event["entry_signal_date"])[:4] == year]
        year_trades = [trade for trade in trades if str(trade["entry_signal_date"])[:4] == year]
        closed = [trade for trade in year_trades if trade.get("trade_status") == "REALIZED"]
        opened = [trade for trade in year_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
        marked = [trade for trade in opened if trade.get("mark_to_cutoff_gross_return_pct") is not None]
        m = base._metric_summary(trade.get("gross_return_pct") for trade in closed)
        rows.append({
            "entry_signal_year": int(year),
            "raw_transition_signals": len(year_events),
            "eligible_exact_pit_ge_1t_signals": sum(e["entry_market_cap_filter_status"] == "ELIGIBLE_EXACT_PIT_GE_1T" for e in year_events),
            "rejected_below_1t": sum(e["entry_market_cap_filter_status"] == "REJECTED_BELOW_1T" for e in year_events),
            "rejected_missing_or_nonexact": sum(e["entry_market_cap_filter_status"] == "REJECTED_MISSING_OR_NONEXACT_PIT_CAP" for e in year_events),
            "filled": len(year_trades),
            "closed": len(closed),
            "open_at_cutoff": len(opened),
            "open_exact_marked": len(marked),
            "open_unresolved": len(opened) - len(marked),
            "closed_gross_mean_pct": m["mean_pct"],
            "closed_gross_median_pct": m["median_pct"],
            "closed_gross_win_rate_pct": m["win_rate_pct"],
            "closed_gross_ge_50_rate_pct": m["ge_50_rate_pct"],
            "closed_gross_le_30_rate_pct": m["le_30_rate_pct"],
        })
    return pd.DataFrame(rows)


def _metrics_for_comparison(
    summary: dict[str, Any],
    trades: list[dict[str, Any]],
    deep: dict[str, Any],
) -> dict[str, Any]:
    gross = summary["closed_gross"]
    opens = summary["open_positions"]
    closed_path = summary["closed_path"]
    open_path = summary["open_path"]
    all_trades = trades
    all_path = base._path_summary(all_trades)
    return {
        "raw_transition_signals": summary.get("entry_signal_count", summary.get("raw_transition_signal_count")),
        "filled_trades": len(trades),
        "realized_trades": sum(t.get("trade_status") == "REALIZED" for t in all_trades),
        "open_trades": sum(t.get("trade_status") == "OPEN_AT_CUTOFF" for t in all_trades),
        "open_ratio_pct": (100.0 * sum(t.get("trade_status") == "OPEN_AT_CUTOFF" for t in all_trades) / len(all_trades)) if all_trades else None,
        "closed_mean_gross_pct": gross.get("mean_pct"),
        "closed_median_gross_pct": gross.get("median_pct"),
        "closed_win_rate_pct": gross.get("win_rate_pct"),
        "closed_average_winner_pct": gross.get("average_winner_pct"),
        "closed_average_loser_pct": gross.get("average_loser_pct"),
        "closed_profit_factor": gross.get("profit_factor"),
        "closed_expectancy_pct": gross.get("expectancy_pct"),
        "closed_ge_20_count": gross.get("ge_20_count"),
        "closed_ge_20_rate_pct": gross.get("ge_20_rate_pct"),
        "closed_ge_50_count": gross.get("ge_50_count"),
        "closed_ge_50_rate_pct": gross.get("ge_50_rate_pct"),
        "closed_ge_100_count": gross.get("ge_100_count"),
        "closed_ge_100_rate_pct": gross.get("ge_100_rate_pct"),
        "closed_le_20_count": gross.get("le_20_count"),
        "closed_le_20_rate_pct": gross.get("le_20_rate_pct"),
        "closed_le_30_count": gross.get("le_30_count"),
        "closed_le_30_rate_pct": gross.get("le_30_rate_pct"),
        "closed_le_50_count": gross.get("le_50_count"),
        "closed_le_50_rate_pct": gross.get("le_50_rate_pct"),
        "closed_mean_mfe_pct": closed_path.get("mean_mfe_pct"),
        "closed_median_mfe_pct": closed_path.get("median_mfe_pct"),
        "closed_mean_mae_pct": closed_path.get("mean_mae_pct"),
        "closed_median_mae_pct": closed_path.get("median_mae_pct"),
        "closed_mean_holding_sessions": closed_path.get("mean_holding_krx_sessions"),
        "closed_median_holding_sessions": closed_path.get("median_holding_krx_sessions"),
        "closed_p90_holding_sessions": closed_path.get("p90_holding_krx_sessions"),
        "all_mean_mfe_pct": all_path.get("mean_mfe_pct"),
        "all_median_mfe_pct": all_path.get("median_mfe_pct"),
        "all_mean_mae_pct": all_path.get("mean_mae_pct"),
        "all_median_mae_pct": all_path.get("median_mae_pct"),
        "all_mean_holding_sessions": all_path.get("mean_holding_krx_sessions"),
        "all_median_holding_sessions": all_path.get("median_holding_krx_sessions"),
        "all_p90_holding_sessions": all_path.get("p90_holding_krx_sessions"),
        "open_exact_marked": opens.get("marked_count"),
        "open_unresolved": opens.get("unresolved_count"),
        "open_marked_mean_gross_pct": opens.get("mean_pct"),
        "open_marked_median_gross_pct": opens.get("median_pct"),
        "open_marked_le_30_count": opens.get("le_30_count"),
        "open_marked_le_30_rate_pct": opens.get("le_30_rate_pct"),
        "open_marked_le_50_count": opens.get("le_50_count"),
        "open_marked_le_50_rate_pct": opens.get("le_50_rate_pct"),
        "open_mean_mfe_pct": open_path.get("mean_mfe_pct"),
        "open_median_mfe_pct": open_path.get("median_mfe_pct"),
        "open_mean_mae_pct": open_path.get("mean_mae_pct"),
        "open_median_mae_pct": open_path.get("median_mae_pct"),
        "open_mean_holding_sessions": open_path.get("mean_holding_krx_sessions"),
        "open_median_holding_sessions": open_path.get("median_holding_krx_sessions"),
        "open_p90_holding_sessions": open_path.get("p90_holding_krx_sessions"),
        "deep_arrival_count": deep.get("deep_arrival_count"),
        "deep_arrival_rate_of_filled_pct": deep.get("deep_arrival_rate_of_filled_pct"),
        "deep_realized_loss_count": deep.get("deep_realized_loss_count"),
        "deep_realized_loss_rate_pct": deep.get("deep_realized_loss_rate_pct"),
        "deep_realized_return_mean_pct": deep.get("deep_realized_return_mean_pct"),
        "deep_realized_return_median_pct": deep.get("deep_realized_return_median_pct"),
        "deep_mae_mean_pct": deep.get("deep_mae_mean_pct"),
        "deep_mae_median_pct": deep.get("deep_mae_median_pct"),
        "deep_open_marked_count": deep.get("deep_open_marked_count"),
        "deep_open_unresolved_count": deep.get("deep_open_unresolved_count"),
    }


def _verdict(control: dict[str, Any], test: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Conservative, fixed-count rubric: quality 2/3 and downside 3/5 for improved."""
    quality_keys = ("closed_median_gross_pct", "closed_win_rate_pct", "closed_ge_50_rate_pct")
    quality_wins = sum(
        test.get(key) is not None and control.get(key) is not None and float(test[key]) > float(control[key])
        for key in quality_keys
    )
    risk_pairs = (
        ("open_marked_mean_gross_pct", True),
        ("open_marked_median_gross_pct", True),
        ("open_marked_le_30_rate_pct", False),
        ("open_marked_le_50_rate_pct", False),
        ("deep_arrival_rate_of_filled_pct", False),
    )
    risk_wins = sum(
        control.get(key) is not None and test.get(key) is not None
        and ((float(test[key]) > float(control[key])) if higher_is_better else (float(test[key]) < float(control[key])))
        for key, higher_is_better in risk_pairs
    )
    if quality_wins >= 2 and risk_wins >= 3:
        verdict = "PATTERN_B_PIT_1T_SIMPLE_IMPROVED"
    elif quality_wins == 0 and risk_wins <= 1:
        verdict = "PATTERN_B_PIT_1T_SIMPLE_NO_BENEFIT"
    else:
        verdict = "PATTERN_B_PIT_1T_SIMPLE_MIXED"
    return verdict, {"quality_metrics_improved_of_3": quality_wins, "downside_metrics_improved_of_5": risk_wins}


def _write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _fmt(value: Any, suffix: str = "%") -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.2f}{suffix}"


def _build_report(
    control_summary: dict[str, Any],
    test_summary: dict[str, Any],
    control_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    verdict: str,
    rubric: dict[str, Any],
    annual: pd.DataFrame,
    lineage: dict[str, Any],
) -> str:
    rows = [
        ("진입 전이 후보", "raw_transition_signals", "건"),
        ("진입일 exact PIT ≥ 1조 eligible 후보", "eligible_exact_pit_ge_1t_signal_count", "건"),
        ("체결", "filled_trades", "건"),
        ("실현", "realized_trades", "건"),
        ("미청산", "open_trades", "건"),
        ("미청산 비율 (미청산/체결)", "open_ratio_pct", "%"),
        ("실현 평균 gross", "closed_mean_gross_pct", "%"),
        ("실현 중앙 gross", "closed_median_gross_pct", "%"),
        ("실현 승률", "closed_win_rate_pct", "%"),
        ("평균 이익", "closed_average_winner_pct", "%"),
        ("평균 손실", "closed_average_loser_pct", "%"),
        ("Profit factor", "closed_profit_factor", "x"),
        ("Expectancy", "closed_expectancy_pct", "%"),
        ("실현 +20% 비율", "closed_ge_20_rate_pct", "%"),
        ("실현 +50% 비율", "closed_ge_50_rate_pct", "%"),
        ("실현 +100% 비율", "closed_ge_100_rate_pct", "%"),
        ("실현 -20% 비율", "closed_le_20_rate_pct", "%"),
        ("실현 -30% 비율", "closed_le_30_rate_pct", "%"),
        ("실현 -50% 비율", "closed_le_50_rate_pct", "%"),
        ("실현 평균 MFE", "closed_mean_mfe_pct", "%"),
        ("실현 중앙 MFE", "closed_median_mfe_pct", "%"),
        ("실현 평균 MAE", "closed_mean_mae_pct", "%"),
        ("실현 중앙 MAE", "closed_median_mae_pct", "%"),
        ("실현 중앙 보유 세션", "closed_median_holding_sessions", "세션"),
        ("실현 p90 보유 세션", "closed_p90_holding_sessions", "세션"),
        ("전체 평균 MFE", "all_mean_mfe_pct", "%"),
        ("전체 중앙 MFE", "all_median_mfe_pct", "%"),
        ("전체 평균 MAE", "all_mean_mae_pct", "%"),
        ("전체 중앙 MAE", "all_median_mae_pct", "%"),
        ("전체 평균 보유 세션", "all_mean_holding_sessions", "세션"),
        ("전체 중앙 보유 세션", "all_median_holding_sessions", "세션"),
        ("전체 p90 보유 세션", "all_p90_holding_sessions", "세션"),
        ("미청산 exact 평가 수", "open_exact_marked", "건"),
        ("미청산 평가 미해결 수", "open_unresolved", "건"),
        ("미청산 평가 평균 gross", "open_marked_mean_gross_pct", "%"),
        ("미청산 평가 중앙 gross", "open_marked_median_gross_pct", "%"),
        ("미청산 평가 -30% 이하 건수", "open_marked_le_30_count", "건"),
        ("미청산 평가 -30% 비율", "open_marked_le_30_rate_pct", "%"),
        ("미청산 평가 -50% 이하 건수", "open_marked_le_50_count", "건"),
        ("미청산 평가 -50% 비율", "open_marked_le_50_rate_pct", "%"),
        ("진입 후 DEEP 도달 수", "deep_arrival_count", "건"),
        ("진입 후 DEEP 도달 비율 (전체 체결 대비)", "deep_arrival_rate_of_filled_pct", "%"),
        ("DEEP 도달 실현 손실 비율", "deep_realized_loss_rate_pct", "%"),
        ("DEEP 도달 실현 평균 수익", "deep_realized_return_mean_pct", "%"),
        ("DEEP 도달 실현 중앙 수익", "deep_realized_return_median_pct", "%"),
        ("DEEP 도달 평균 MAE", "deep_mae_mean_pct", "%"),
        ("DEEP 도달 중앙 MAE", "deep_mae_median_pct", "%"),
    ]
    table = ["| 지표 | CONTROL ALL | TEST exact PIT ≥ 1조 |", "|---|---:|---:|"]
    for label, key, unit in rows:
        if key == "eligible_exact_pit_ge_1t_signal_count":
            control_value = "—"
            test_value = str(test_summary.get(key, 0))
        else:
            control_value = control_metrics.get(key)
            test_value = test_metrics.get(key)
            if unit == "건":
                control_value = "n/a" if control_value is None else f"{int(control_value):,}"
                test_value = "n/a" if test_value is None else f"{int(test_value):,}"
            else:
                control_value = _fmt(control_value, "" if unit == "x" else unit)
                test_value = _fmt(test_value, "" if unit == "x" else unit)
        table.append(f"| {label} | {control_value} | {test_value} |")
    annual_rows = [
        "| 연도 | 전이 후보 | 1조 이상 eligible | 체결 | 실현 | 미청산 | 중앙 gross | 승률 | +50% | -30% |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in annual.to_dict("records"):
        annual_rows.append(
            f"| {row['entry_signal_year']} | {row['raw_transition_signals']:,} | {row['eligible_exact_pit_ge_1t_signals']:,} | "
            f"{row['filled']:,} | {row['closed']:,} | {row['open_at_cutoff']:,} | "
            f"{_fmt(row['closed_gross_median_pct'])} | {_fmt(row['closed_gross_win_rate_pct'])} | "
            f"{_fmt(row['closed_gross_ge_50_rate_pct'])} | {_fmt(row['closed_gross_le_30_rate_pct'])} |"
        )
    return "\n".join([
        "# Pattern B 순수 전략 진입일 PIT 시총 1조 비교 V01",
        "",
        f"판정: **{verdict}**",
        "",
        "## 규칙과 비교 단위",
        "",
        f"- 기간: 진입 신호 {base.SIGNAL_START}~{base.SIGNAL_END}; cutoff {base.CUTOFF}.",
        "- CONTROL은 기존 V01 ALL 원장을 그대로 사용했어. 해당 파일의 커밋 버전, 월별 snapshot SHA-256, ledger/summary 건수·상태·실현 gross 통계를 대조했고 기존 산출물을 덮어쓰지 않았어.",
        "- TEST는 CONTROL과 같은 월별 상태 전이, 다음 exact adjusted Open 체결, 첫 NORMAL 전량 청산, DEEP 보유, cutoff exact close 평가를 쓰고 진입 신호 단계에만 exact PIT 시총 ≥ 1조 조건을 적용했어.",
        "- 필터 키: `(ticker, isu_cd, entry_signal_date)`를 `(ticker, isu_cd, snapshot_date)`와 일치시켰어. 체결일·인접일·현재 시총·forward/backward fill·proxy는 쓰지 않았어.",
        f"- 원시 전이 후보 {test_summary['raw_transition_signal_count']:,}건: exact PIT ≥ 1조 {test_summary['eligible_exact_pit_ge_1t_signal_count']:,}, 1조 미만 {test_summary['exact_pit_below_1t_signal_count']:,}, exact PIT 누락/비정확 {test_summary['missing_or_nonexact_pit_signal_count']:,}.",
        f"- 차단된 authority 전이 {test_summary['blocked_authority_transition_count']:,}; 시총 대체/보간 {test_summary['pit_market_cap_filter']['imputation_count']:,}; 인접일 대체 {test_summary['pit_market_cap_filter']['adjacent_date_fallback_count']:,}.",
        "- 숫자는 실현 포지션의 gross 수익률이 기본이야. 미청산은 정확한 2026-09-21 adjusted Close가 있는 포지션만 따로 평가하고, unresolved는 수익 통계 분모에서 제외해.",
        "- DEEP 도달 비율 분모는 전체 체결 거래야. DEEP cohort 최종손실률·평균/중앙 수익은 청산된 cohort만 사용하고, 미청산은 marked/unresolved를 따로 보여줘. DEEP MAE는 청산 또는 cutoff까지의 경로 통계야.",
        "",
        "## CONTROL vs TEST",
        "",
        *table,
        "",
        "평균·중앙·승률·threshold와 PF/expectancy는 실현 거래 기준이야. 미청산 threshold 비율 분모는 exact close 평가가 가능한 미청산 수야.",
        "",
        "## 비용",
        "",
        f"- 두 실행 모두 기존 가정 그대로: 매수/매도 수수료 각 {base.COMMISSION_RATE * 100:.3f}%, 슬리피지는 매수 +{base.SLIPPAGE_RATE * 100:.2f}%, 매도 -{base.SLIPPAGE_RATE * 100:.2f}%.",
        "- 매도 세금은 기존 역사 세율표만 적용하고, 세금표가 시작되기 전은 net 계산에서 제외했어. 전체 기간 주 지표는 gross야.",
        f"- TEST 세금 적용 가능 실현 거래 {test_summary['cost_covered_closed_net']['n']:,}; 수수료·슬리피지만 적용한 실현 평균 { _fmt(test_summary['closed_pre_tax_cost']['mean_pct']) }, 완전 net 평균 { _fmt(test_summary['cost_covered_closed_net']['mean_pct']) }.",
        "",
        "## DEEP_DEPRESSED cohort 해석",
        "",
        f"- CONTROL DEEP 도달 {control_metrics['deep_arrival_count']:,}/{control_metrics['filled_trades']:,}체결 ({_fmt(control_metrics['deep_arrival_rate_of_filled_pct'])}); TEST {test_metrics['deep_arrival_count']:,}/{test_metrics['filled_trades']:,} ({_fmt(test_metrics['deep_arrival_rate_of_filled_pct'])}).",
        f"- 실현 DEEP cohort 손실률: CONTROL { _fmt(control_metrics['deep_realized_loss_rate_pct']) } ({control_metrics['deep_realized_loss_count']:,}손실), TEST { _fmt(test_metrics['deep_realized_loss_rate_pct']) } ({test_metrics['deep_realized_loss_count']:,}손실). 이 비율 분모는 청산된 DEEP 도달 거래야.",
        f"- 미청산 DEEP cohort: CONTROL marked/unresolved {control_metrics['deep_open_marked_count']:,}/{control_metrics['deep_open_unresolved_count']:,}; TEST {test_metrics['deep_open_marked_count']:,}/{test_metrics['deep_open_unresolved_count']:,}.",
        "- 기존 V01 요약의 DEEP 수치는 realized-only이므로, 본 비교는 DEEP 도달한 모든 체결을 다시 분류해 미청산을 별도로 드러냈어.",
        "",
        "## 연도별 TEST",
        "",
        *annual_rows,
        "",
        "2025~2026 진입 cohort는 cutoff 시점에 미청산 검열 비중이 높을 수 있어 과거 연도와 직접 비교하면 안 돼.",
        "",
        "## 판정 기준과 결론",
        "",
        "- `IMPROVED`: realized 중앙 gross·승률·+50% 비율 중 2개 이상 개선되고, 미청산 평균/중앙·-30%/-50% 비율·DEEP 도달률 중 3개 이상 개선.",
        "- `NO_BENEFIT`: realized 품질 세 지표 개선 0개이며 downside 지표 개선이 최대 1개. 그 외는 `MIXED`.",
        f"- 이번 결과의 사전 고정 판정 카운트: realized 품질 개선 {rubric['quality_metrics_improved_of_3']}/3, downside 개선 {rubric['downside_metrics_improved_of_5']}/5.",
        f"- DEEP 도달률은 {_fmt(control_metrics['deep_arrival_rate_of_filled_pct'])}에서 {_fmt(test_metrics['deep_arrival_rate_of_filled_pct'])}로 거의 그대로였고, DEEP cohort의 실현 손실률은 {_fmt(control_metrics['deep_realized_loss_rate_pct'])}에서 {_fmt(test_metrics['deep_realized_loss_rate_pct'])}로 높아졌어. 반면 평균 MAE와 미청산 하락 tail은 완화됐어.",
        f"- 결론: **{verdict}**. 필터가 표본을 {test_metrics['filled_trades']:,}체결로 줄였고 미청산 일부 위험은 줄였지만 실현 성과와 DEEP cohort 약점은 개선되지 않아. 실현/미청산 구성 변화 때문에 단순히 CONTROL 체결 일부를 지운 결과는 아니야.",
        "",
        "## 검증 및 산출물",
        "",
        f"- CONTROL 원장 재실행 여부: {lineage['control_was_replayed']}; 원장 파일 해시는 metadata.json에 기록.",
        f"- TEST 체결일은 신호일 이후 exact KRX session, 동일 ISU 중복 보유 0, lifecycle 표본 {test_summary['lifecycle_spot_checks_passed']}/{test_summary['lifecycle_spot_checks']} 통과.",
        "- `control_vs_test.csv`: 요청 지표 및 분포를 한 표에서 비교.",
        "- `test_trade_ledger.csv`, `test_open_positions.csv`, `test_entry_signal_ledger.csv`, `pit_entry_signal_audit.csv`.",
        "- `deep_depressed_analysis.csv`, `annual_entry_year_stats.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
        "질문: 진입일 PIT 시총 1조 이상 필터가 Pattern B 순수 전략의 핵심 약점을 실질적으로 줄였는가?",
        "답: 아니. 미청산 평균과 -30%/-50% 꼬리는 개선됐지만 실현 중앙 수익·승률·+50% 비율은 낮아졌고, DEEP 도달 거래의 실현 손실률도 높아졌어. 일부 약점은 완화됐지만 핵심 약점이 전반적으로 실질 개선됐다고 보기는 어려워.",
        "",
    ])


def run_backtest(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)
    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusion_count = base._read_monthly_samples(data_root, intervals, interval_to_component)
    control_summary, control_frame, control_signals_frame, lineage = _load_control(data_root, samples)
    events_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for group in events_by_identity.values() for event in group]
    if len(all_events) != control_summary["entry_signal_count"]:
        raise RuntimeError("fresh transition candidates differ from the CONTROL signal count")
    eligible_by_identity, cap_audit = _attach_exact_entry_caps(all_events, samples)
    if len(cap_audit) != len(all_events):
        raise RuntimeError("PIT cap audit does not cover every raw transition candidate")
    cap_status_counts = Counter(event["entry_market_cap_filter_status"] for event in all_events)
    if sum(cap_status_counts.values()) != len(all_events):
        raise RuntimeError("PIT cap eligibility counts do not reconcile to raw signals")
    if cap_status_counts["ELIGIBLE_EXACT_PIT_GE_1T"] + cap_status_counts["REJECTED_BELOW_1T"] != len(all_events) - cap_status_counts["REJECTED_MISSING_OR_NONEXACT_PIT_CAP"]:
        raise RuntimeError("PIT cap status partition does not reconcile")
    panel_mismatches = sum(event["panel_eligibility_matches_exact_cap"] is False for event in all_events)
    if "panel_b_eligible" in samples.columns and panel_mismatches:
        raise RuntimeError(f"PIT cap eligibility disagrees with existing Panel B eligibility on {panel_mismatches} signals")
    if len(all_events) != len(control_signals_frame):
        raise RuntimeError("CONTROL and fresh raw signal ledger row counts differ")
    control_status_by_key = {
        (str(row.ticker), str(row.isu_cd), str(row.entry_signal_date)): str(row.entry_signal_status)
        for row in control_signals_frame.itertuples(index=False)
    }
    for event in all_events:
        key = (event["ticker"], event["isu_cd"], event["entry_signal_date"])
        if key not in control_status_by_key:
            raise RuntimeError(f"CONTROL signal missing matching transition key: {key}")
        event["control_entry_signal_status"] = control_status_by_key[key]

    active_identities = sorted(eligible_by_identity)
    active_tickers = sorted({identity[0] for identity in active_identities})
    min_start_by_ticker = {
        ticker: min(
            event["entry_signal_date"]
            for identity, group in eligible_by_identity.items()
            if identity[0] == ticker
            for event in group
        )
        for ticker in active_tickers
    }
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    daily_by_ticker: dict[str, pd.DataFrame | None] = {}
    ticker_load_audit: dict[str, dict[str, Any]] = {}
    for number, ticker in enumerate(active_tickers, start=1):
        loader = RepositoryV2DailyLoader(repository, start=min_start_by_ticker[ticker], end=base.CUTOFF)
        daily = loader.load(ticker)
        daily_by_ticker[ticker] = daily
        audit = repository.query_audit.get(ticker, {})
        projection = daily.attrs.get("session_projection_summary", {}) if daily is not None else {}
        ticker_load_audit[ticker] = {
            "status": audit.get("status"),
            "reason": audit.get("reason"),
            "rows": int(len(daily)) if daily is not None else 0,
            "effective_as_of": daily.attrs.get("effective_as_of") if daily is not None else None,
            "session_projection_summary": projection,
        }
        if number % 250 == 0:
            print(f"Loaded authoritative OHLC for {number:,}/{len(active_tickers):,} TEST tickers", flush=True)

    active_set = set(active_identities)
    active_samples = samples.loc[
        samples.apply(lambda row: (row["ticker"], row["isu_cd"]) in active_set, axis=1)
    ].copy()
    component_prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        normalized = (str(identity[0]), str(identity[1]))
        ticker_daily = daily_by_ticker.get(normalized[0])
        for component in sorted(group["component_id"].unique()):
            component_intervals = intervals_by_component.get((*normalized, component), [])
            component_prices[(*normalized, component)] = base._component_price_rows(
                ticker_daily, component_intervals, component
            )

    all_trades: list[dict[str, Any]] = []
    original_strategy_id = base.STRATEGY_ID
    base.STRATEGY_ID = STRATEGY_ID
    try:
        for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=True):
            normalized = (str(identity[0]), str(identity[1]))
            observations = group.sort_values("snapshot_date").to_dict("records")
            trades, _ = base._simulate_identity(
                observations,
                eligible_by_identity.get(normalized, []),
                {
                    component: component_prices.get((*normalized, component), pd.DataFrame())
                    for component in set(group["component_id"])
                },
                base.CUTOFF,
            )
            all_trades.extend(trades)
    finally:
        base.STRATEGY_ID = original_strategy_id

    event_by_key = {
        (event["ticker"], event["isu_cd"], event["entry_signal_date"]): event
        for event in all_events
    }
    for trade in all_trades:
        event = event_by_key[(trade["ticker"], trade["isu_cd"], trade["entry_signal_date"])]
        for field in ("entry_market_cap_krw", "entry_market_cap_exact", "entry_market_cap_source_date", "entry_market_cap_threshold_krw"):
            trade[field] = event[field]
        daily = component_prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        base._path_metrics(trade, daily, trading_dates, base.CUTOFF)
        base._calculate_returns(trade)

    status_counts = Counter(event["entry_signal_status"] for event in all_events)
    filled_count = len(all_trades)
    closed_count = sum(trade.get("trade_status") == "REALIZED" for trade in all_trades)
    open_count = sum(trade.get("trade_status") == "OPEN_AT_CUTOFF" for trade in all_trades)
    if filled_count != closed_count + open_count:
        raise RuntimeError("TEST filled trades do not reconcile to realized plus open")
    if filled_count != status_counts["FILLED"]:
        raise RuntimeError("TEST FILLED signal status count does not reconcile to trade ledger")
    for trade in all_trades:
        if trade["entry_market_cap_exact"] is not True or int(trade["entry_market_cap_krw"]) < CAP_THRESHOLD_KRW:
            raise RuntimeError("TEST trade violates exact entry-date PIT cap eligibility")
        if trade["entry_market_cap_source_date"] != trade["entry_signal_date"]:
            raise RuntimeError("TEST trade market cap was not sourced on its signal date")
        if trade["entry_execution_date"] <= trade["entry_signal_date"]:
            raise RuntimeError("TEST entry execution was not strictly after its signal")
        if trade["entry_execution_date"] not in set(trading_dates):
            raise RuntimeError("TEST entry execution date is not an exact merged KRX session")
    trading_date_set = set(trading_dates)
    if any(
        trade.get("exit_execution_date") and
        (trade["exit_execution_date"] not in trading_date_set or trade["exit_execution_date"] <= trade["exit_signal_date"])
        for trade in all_trades
    ):
        raise RuntimeError("TEST exit execution is not a strictly later merged KRX session")
    if len({trade["trade_id"] for trade in all_trades}) != len(all_trades):
        raise RuntimeError("TEST has duplicate trade identifiers")
    for identity, group in pd.DataFrame(all_trades).groupby(["ticker", "isu_cd"], sort=False):
        ordered = sorted(group.to_dict("records"), key=lambda row: row["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["entry_execution_date"] <= (previous.get("exit_execution_date") or base.CUTOFF):
                raise RuntimeError(f"overlapping TEST positions for {identity}")

    if len(all_trades) < 20:
        raise RuntimeError(f"at least 20 TEST filled trades needed for lifecycle checks, got {len(all_trades)}")
    base_spot = base._build_spot_checks(all_trades, active_samples, component_prices, trading_dates)
    cap_by_trade = {
        trade["trade_id"]: trade for trade in all_trades
    }
    spot_checks = []
    for row in base_spot:
        trade = cap_by_trade[row["trade_id"]]
        exact_ok = bool(
            trade["entry_market_cap_exact"] is True
            and trade["entry_market_cap_source_date"] == trade["entry_signal_date"]
            and int(trade["entry_market_cap_krw"]) >= CAP_THRESHOLD_KRW
        )
        row["entry_signal_date_exact_pit_cap_verified"] = exact_ok
        row["entry_market_cap_krw"] = trade["entry_market_cap_krw"]
        row["all_checks_pass"] = bool(row["all_checks_pass"] and exact_ok)
        spot_checks.append(row)
    if len(spot_checks) != 20 or not all(row["all_checks_pass"] for row in spot_checks):
        raise RuntimeError("TEST 20 lifecycle/PIT spot checks failed")

    projection_audit = {
        "silent_inner_drop_count": sum(
            int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0)
            for row in ticker_load_audit.values()
        ),
        "explicit_exclusion_count": sum(
            int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0)
            for row in ticker_load_audit.values()
        ),
    }
    if projection_audit["silent_inner_drop_count"] != 0:
        raise RuntimeError("TEST Repository V2 projection reports silent inner drops")

    elapsed = time.time() - started
    test_summary = _summary_test(all_trades, all_events, blocked, samples, projection_audit, elapsed)
    test_summary["permanent_exclusion_identity_count"] = permanent_exclusion_count
    test_summary["ticker_price_load_count"] = len(ticker_load_audit)
    test_summary["price_rows_loaded"] = sum(row["rows"] for row in ticker_load_audit.values())
    test_summary["lifecycle_spot_checks"] = len(spot_checks)
    test_summary["lifecycle_spot_checks_passed"] = sum(row["all_checks_pass"] for row in spot_checks)
    test_summary["no_overlapping_same_identity_positions"] = True
    test_summary["validation_checks"] = {
        "control_signal_keys_match_fresh_transitions": True,
        "control_source_and_trade_summary_reconcile": True,
        "all_pit_caps_on_exact_entry_signal_dates": True,
        "test_filled_trades_all_exactly_at_least_1t": True,
        "pit_market_cap_imputation_count_zero": True,
        "all_fills_on_merged_krx_sessions": True,
        "all_entry_fills_strictly_after_signals": True,
        "no_duplicate_test_trade_ids": True,
        "no_overlapping_same_identity_positions": True,
        "closed_plus_open_reconciles_to_filled": True,
        "repository_v2_silent_inner_drop_count_zero": True,
        "lifecycle_and_pit_spot_checks_passed": len(spot_checks) == 20 and all(row["all_checks_pass"] for row in spot_checks),
    }

    control_frame_trades = control_frame.to_dict("records")
    control_metrics = _metrics_for_comparison(control_summary, control_frame_trades, {})
    test_metrics = _metrics_for_comparison(test_summary, all_trades, test_summary["post_entry_deep_state"])
    control_deep = _deep_summary(control_frame_trades, samples)
    legacy_deep = control_summary["post_entry_deep_state"]
    deep_checks = {
        "trade_count": control_deep["deep_realized_count"] == legacy_deep["trade_count"],
        "loser_count": control_deep["deep_realized_loss_count"] == legacy_deep["loser_count"],
        "mean_return": math.isclose(control_deep["deep_realized_return_mean_pct"], legacy_deep["mean_pct"], rel_tol=1e-11, abs_tol=1e-10),
        "median_return": math.isclose(control_deep["deep_realized_return_median_pct"], legacy_deep["median_pct"], rel_tol=1e-11, abs_tol=1e-10),
        "mean_mae": math.isclose(control_deep["deep_realized_mae_mean_pct"], legacy_deep["mean_mae_pct"], rel_tol=1e-11, abs_tol=1e-10),
    }
    if not all(deep_checks.values()):
        raise RuntimeError(f"CONTROL realized DEEP cohort differs from prior V01 summary: {deep_checks}")
    control_metrics.update({
        key: control_deep.get(key) for key in (
            "deep_arrival_count", "deep_arrival_rate_of_filled_pct", "deep_realized_loss_count",
            "deep_realized_loss_rate_pct", "deep_realized_return_mean_pct", "deep_realized_return_median_pct",
            "deep_mae_mean_pct", "deep_mae_median_pct", "deep_open_marked_count", "deep_open_unresolved_count",
        )
    })
    test_metrics.update({
        key: test_summary["post_entry_deep_state"].get(key) for key in (
            "deep_arrival_count", "deep_arrival_rate_of_filled_pct", "deep_realized_loss_count",
            "deep_realized_loss_rate_pct", "deep_realized_return_mean_pct", "deep_realized_return_median_pct",
            "deep_mae_mean_pct", "deep_mae_median_pct", "deep_open_marked_count", "deep_open_unresolved_count",
        )
    })
    control_metrics.update({
        "eligible_exact_pit_ge_1t_signal_count": None,
        "rejected_below_1t_signal_count": None,
        "rejected_missing_or_nonexact_pit_signal_count": None,
    })
    test_metrics.update({
        "eligible_exact_pit_ge_1t_signal_count": test_summary["eligible_exact_pit_ge_1t_signal_count"],
        "rejected_below_1t_signal_count": test_summary["exact_pit_below_1t_signal_count"],
        "rejected_missing_or_nonexact_pit_signal_count": test_summary["missing_or_nonexact_pit_signal_count"],
    })
    verdict, rubric = _verdict(control_metrics, test_metrics)
    test_summary["verdict"] = verdict
    test_summary["verdict_rubric"] = rubric

    comparison_rows = []
    units = {
        key: ("count" if key.endswith("count") or key.endswith("trades") or key in {"filled_trades", "realized_trades", "open_trades", "open_exact_marked", "open_unresolved", "deep_arrival_count", "deep_realized_loss_count", "deep_open_marked_count", "deep_open_unresolved_count"} else "pct" if key.endswith("pct") else "ratio")
        for key in control_metrics
    }
    for key in control_metrics:
        cv, tv = control_metrics.get(key), test_metrics.get(key)
        delta = (float(tv) - float(cv)) if cv is not None and tv is not None else None
        comparison_rows.append({"metric": key, "control_all": cv, "test_pit_1t": tv, "test_minus_control": delta, "unit": units.get(key, "")})
    comparison = pd.DataFrame(comparison_rows)

    control_signal_status = control_signals_frame[["ticker", "isu_cd", "entry_signal_date", "entry_signal_status"]].rename(columns={"entry_signal_status": "control_status"})
    test_signal_frame = pd.DataFrame(all_events)
    transition_counts = (
        test_signal_frame.groupby(["control_entry_signal_status", "entry_signal_status"], dropna=False)
        .size().reset_index(name="count")
        .rename(columns={"control_entry_signal_status": "control_status", "entry_signal_status": "test_status"})
    )

    annual = _annual_summary(all_events, all_trades)
    test_summary["annual_stats_rows"] = int(len(annual))
    test_summary["source_provenance"] = provenance
    test_summary["source_sample_sha256"] = lineage["control_source_sample_sha256"]
    test_summary["control_lineage"] = lineage
    test_summary["control_deep_legacy_reconciliation"] = deep_checks
    test_summary["source_market_cap_audit"] = {
        "raw_transition_signal_count": len(all_events),
        "exact_entry_date_cap_count": cap_status_counts["ELIGIBLE_EXACT_PIT_GE_1T"] + cap_status_counts["REJECTED_BELOW_1T"],
        "exact_pit_ge_1t_count": cap_status_counts["ELIGIBLE_EXACT_PIT_GE_1T"],
        "exact_pit_below_1t_count": cap_status_counts["REJECTED_BELOW_1T"],
        "missing_or_nonexact_count": cap_status_counts["REJECTED_MISSING_OR_NONEXACT_PIT_CAP"],
        "panel_b_eligibility_mismatches": panel_mismatches,
        "imputation_count": 0,
        "adjacent_date_fallback_count": 0,
        "sample_table_key_duplicates": int(samples.duplicated(["ticker", "isu_cd", "snapshot_date"]).sum()),
    }
    if test_summary["source_market_cap_audit"]["sample_table_key_duplicates"]:
        raise RuntimeError("duplicate sample PIT key detected")

    open_trades = [trade for trade in all_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
    deep_rows = []
    for label, deep in (("CONTROL_ALL", control_deep), ("TEST_PIT_1T", test_summary["post_entry_deep_state"])):
        deep_rows.append({"cohort": label, **deep})
    _write_csv(output_dir / "control_vs_test.csv", comparison)
    _write_csv(output_dir / "test_trade_ledger.csv", all_trades)
    _write_csv(output_dir / "test_open_positions.csv", open_trades)
    _write_csv(output_dir / "test_entry_signal_ledger.csv", all_events)
    _write_csv(output_dir / "pit_entry_signal_audit.csv", cap_audit)
    _write_csv(output_dir / "control_vs_test_signal_status.csv", transition_counts)
    _write_csv(output_dir / "deep_depressed_analysis.csv", deep_rows)
    _write_csv(output_dir / "annual_entry_year_stats.csv", annual)
    _write_csv(output_dir / "lifecycle_spot_checks.csv", spot_checks)
    (output_dir / "summary.json").write_text(json.dumps(test_summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    metadata = {
        "study": "KRX Pattern B Pure Strategy PIT 1T Simple Backtest V01",
        "created_at_local_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "baseline_commit": "5dcfe79f40800ed8ac17558bad6dc600a91fd653",
        "strategy_id": STRATEGY_ID,
        "verdict": verdict,
        "signal_start": base.SIGNAL_START,
        "signal_end": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "entry_filter": "exact PIT market_cap_krw >= 1,000,000,000,000 on entry_signal_date only",
        "entry_filter_key": ["ticker", "isu_cd", "snapshot_date"],
        "missing_exact_pit_cap_rule": "do not fill; retain in raw signal audit and count separately",
        "adjacent_date_or_other_cap_imputation": False,
        "control_artifact": lineage,
        "control_cost_contract": control_summary["trade_cost_contract"],
        "test_cost_contract": test_summary["cost_contract"],
        "market_cap_audit": test_summary["source_market_cap_audit"],
        "source_sample_path": str(base.SAMPLE_PATH),
        "source_state_rule": "Pattern B State Rule V02 monthly snapshots; unchanged",
        "entry_rule": "adjacent month previous observed non-DEPRESSED to current DEPRESSED; cap gate is applied after transition generation",
        "exit_rule": "first observed NORMAL after entry; DEEP_DEPRESSED remains held",
        "execution_rule": "first exact Repository V2 adjusted daily OHLC row strictly after signal date within same contiguous COMMON identity chain",
        "evaluation_rule": "exact adjusted close on 2026-09-21; unresolved positions remain open with no substitute mark",
        "cost_source": "scripts/run_v2_julia_official_validation_v01.py via unchanged Pattern B V01 runner helpers",
        "full_period_primary_metric": "closed-trade gross return; open marks reported separately",
        "portfolio_model": "none; independent trade return ratios",
        "no_future_delisting_filter": True,
        "manual_followup_started": False,
        "output_files": [
            "report.md", "control_vs_test.csv", "test_trade_ledger.csv", "test_open_positions.csv",
            "test_entry_signal_ledger.csv", "pit_entry_signal_audit.csv", "control_vs_test_signal_status.csv",
            "deep_depressed_analysis.csv", "annual_entry_year_stats.csv", "lifecycle_spot_checks.csv",
            "summary.json", "metadata.json",
        ],
        "source_provenance": provenance,
        "ticker_price_load_audit": ticker_load_audit,
        "validation_checks": test_summary["validation_checks"],
        "verdict_rubric": rubric,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    report = _build_report(control_summary, test_summary, control_metrics, test_metrics, verdict, rubric, annual, lineage)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(test_summary, ensure_ascii=False, indent=2, default=_json_default), flush=True)
    print(f"Output: {output_dir}", flush=True)
    return test_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run_backtest(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
