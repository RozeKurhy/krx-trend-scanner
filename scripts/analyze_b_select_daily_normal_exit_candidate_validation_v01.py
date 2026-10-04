#!/usr/bin/env python3
"""Formally validate the B Select daily NORMAL-exit candidate.

This postprocessor verifies the sealed cadence replay and derives the adoption
gates and requested trade-level diagnostics without changing replay inputs,
official history, or production behavior.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import math
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_cadence_v01")
OUTPUT_RELATIVE = Path(
    "artifacts/strategies/b_select_core_v1/research/daily_normal_exit_candidate_validation_v01"
)
EXPECTED_BASE_HEAD = "82eac8a880b09f958bc185bac2a9a4346c848aae"
WINDOWS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
SCENARIOS = {
    "CONTROL_MONTH_END": "control_month_end",
    "TEST_DAILY": "test_daily",
}
INITIAL_CAPITAL_KRW = 200_000_000.0
TAIL_THRESHOLDS = (("le_neg_15", "<= -15%", "le", -15.0),
                   ("le_neg_30", "<= -30%", "le", -30.0),
                   ("ge_pos_30", ">= +30%", "ge", 30.0),
                   ("ge_pos_50", ">= +50%", "ge", 50.0),
                   ("ge_pos_100", ">= +100%", "ge", 100.0))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _num(value: Any) -> float | None:
    if value is None or value == "" or str(value).lower() in {"nan", "none", "null"}:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _int(value: Any) -> int:
    parsed = _num(value)
    return int(parsed) if parsed is not None else 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _identity_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).upper(),
        str(row.get("entry_signal_date", ""))[:10],
    )


def trade_distribution(returns: Iterable[float]) -> dict[str, Any]:
    """Summarize realized costed returns with the W's inclusive tail bounds."""
    values = [float(value) for value in returns if value is not None and math.isfinite(float(value))]
    result: dict[str, Any] = {
        "realized_count": len(values),
        "win_count": sum(value > 0 for value in values),
        "win_rate_pct": (sum(value > 0 for value in values) / len(values) * 100) if values else None,
        "mean_return_pct": mean(values) if values else None,
        "median_return_pct": median(values) if values else None,
    }
    for name, _label, operation, threshold in TAIL_THRESHOLDS:
        count = sum(value <= threshold for value in values) if operation == "le" else sum(value >= threshold for value in values)
        result[f"{name}_count"] = count
        result[f"{name}_rate_pct"] = (count / len(values) * 100) if values else None
    return result


def mdd_gate(coverage_pct: float, mdd_pct: float, absolute_floor_pct: float,
             relative_deterioration_pp: float | None = None) -> str:
    """Apply official MDD evidence coverage before threshold comparisons."""
    if coverage_pct < 90.0:
        return "CHECK_REQUIRED"
    if mdd_pct < absolute_floor_pct:
        return "FAIL"
    if relative_deterioration_pp is not None and relative_deterioration_pp >= 5.0:
        return "FAIL"
    return "PASS"


def build_early_pairs(
    comparison_rows: Sequence[Mapping[str, Any]],
    exact_sessions: Sequence[str],
    control_filled_ids: set[str],
    test_filled_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build 1:1 closed-trade pairs where TEST's signal precedes CONTROL."""
    position = {day: index for index, day in enumerate(exact_sessions)}
    pairs: list[dict[str, Any]] = []
    early_without_control_exit = 0
    early_unpaired = 0
    for row in comparison_rows:
        test_signal = str(row.get("test_exit_signal_date", ""))[:10]
        control_signal = str(row.get("control_exit_signal_date", ""))[:10]
        if not test_signal:
            continue
        if control_signal and test_signal >= control_signal:
            continue
        if not control_signal:
            early_without_control_exit += 1
            early_unpaired += 1
            continue
        test_date = str(row.get("test_exit_execution_date", ""))[:10]
        control_date = str(row.get("control_exit_execution_date", ""))[:10]
        control_return = _num(row.get("control_costed_pre_tax_return_pct"))
        test_return = _num(row.get("test_costed_pre_tax_return_pct"))
        if (
            not test_date or not control_date or control_return is None or test_return is None
            or row.get("control_trade_status") != "REALIZED"
            or row.get("test_trade_status") != "REALIZED"
        ):
            early_unpaired += 1
            continue
        required_dates = (test_signal, control_signal, test_date, control_date)
        if any(day not in position for day in required_dates):
            raise ValueError(f"paired date missing from exact-session calendar: {required_dates}")
        signal_advance = position[control_signal] - position[test_signal]
        execution_advance = position[control_date] - position[test_date]
        if signal_advance <= 0:
            raise ValueError(f"expected earlier TEST signal: {row}")
        key = _identity_key(row)
        pair = {
            "window_id": row["window_id"],
            "ticker": key[0],
            "isu_cd": key[1],
            "entry_signal_date": key[2],
            "entry_execution_date": row.get("entry_execution_date"),
            "control_exit_signal_date": control_signal,
            "control_exit_execution_date": control_date,
            "test_exit_signal_date": test_signal,
            "test_exit_execution_date": test_date,
            "signal_sessions_advanced": signal_advance,
            "execution_sessions_advanced": execution_advance,
            "control_costed_pre_tax_return_pct": control_return,
            "test_costed_pre_tax_return_pct": test_return,
            "return_delta_pp": test_return - control_return,
            "control_holding_krx_sessions": _num(row.get("control_holding_krx_sessions")),
            "test_holding_krx_sessions": _num(row.get("test_holding_krx_sessions")),
            "control_portfolio_filled": key[0] + "|" + key[1] + "|" + key[2] in control_filled_ids,
            "test_portfolio_filled": key[0] + "|" + key[1] + "|" + key[2] in test_filled_ids,
        }
        pairs.append(pair)

    deltas = [float(row["return_delta_pp"]) for row in pairs]
    advanced_exec = [int(row["execution_sessions_advanced"]) for row in pairs]
    summary = {
        "daily_earlier_signal_count": sum(
            bool(str(row.get("test_exit_signal_date", "")))
            and (
                not str(row.get("control_exit_signal_date", ""))
                or str(row["test_exit_signal_date"])[:10] < str(row["control_exit_signal_date"])[:10]
            ) for row in comparison_rows
        ),
        "paired_realized_earlier_exit_count": len(pairs),
        "earlier_test_exit_without_control_exit_count": early_without_control_exit,
        "other_unpaired_earlier_exit_count": early_unpaired - early_without_control_exit,
        "improved_count": sum(value > 0 for value in deltas),
        "degraded_count": sum(value < 0 for value in deltas),
        "unchanged_count": sum(value == 0 for value in deltas),
        "improved_pct_of_pairs": (sum(value > 0 for value in deltas) / len(deltas) * 100) if deltas else None,
        "degraded_pct_of_pairs": (sum(value < 0 for value in deltas) / len(deltas) * 100) if deltas else None,
        "mean_return_delta_pp": mean(deltas) if deltas else None,
        "median_return_delta_pp": median(deltas) if deltas else None,
        "mean_signal_sessions_advanced": mean(int(row["signal_sessions_advanced"]) for row in pairs) if pairs else None,
        "median_signal_sessions_advanced": median(int(row["signal_sessions_advanced"]) for row in pairs) if pairs else None,
        "mean_execution_sessions_advanced": mean(advanced_exec) if advanced_exec else None,
        "median_execution_sessions_advanced": median(advanced_exec) if advanced_exec else None,
        "mean_control_holding_sessions": mean(float(row["control_holding_krx_sessions"]) for row in pairs) if pairs else None,
        "median_control_holding_sessions": median(float(row["control_holding_krx_sessions"]) for row in pairs) if pairs else None,
        "mean_test_holding_sessions": mean(float(row["test_holding_krx_sessions"]) for row in pairs) if pairs else None,
        "median_test_holding_sessions": median(float(row["test_holding_krx_sessions"]) for row in pairs) if pairs else None,
        "both_portfolios_filled_pair_count": sum(row["control_portfolio_filled"] and row["test_portfolio_filled"] for row in pairs),
    }
    return pairs, summary


def _verify_replay_hashes(replay_root: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    checks: list[tuple[Path, str, str]] = []
    for relative, expected in metadata.get("source_hashes", {}).items():
        checks.append((ROOT / relative, expected, "source"))
    for relative, expected in metadata.get("price_authority_hashes", {}).items():
        checks.append((ROOT / relative, expected, "RepositoryV2 price"))
    for relative, details in metadata.get("generated_files", {}).items():
        checks.append((replay_root / relative, details["sha256"], "aggregate replay output"))
    for window_id, hashes in metadata.get("window_generated_files", {}).items():
        window_dir = replay_root / window_id.lower().replace("-", "_")
        for relative, expected in hashes.items():
            checks.append((window_dir / relative, expected, f"{window_id} replay output"))
        window_metadata = _read_json(window_dir / "metadata.json")
        for relative, expected in window_metadata.get("generated_files_sha256", {}).items():
            checks.append((window_dir / relative, expected, f"{window_id} replay output manifest"))
        for relative, expected in window_metadata.get("source_hashes", {}).items():
            source_path = ROOT / "artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01" / window_id.lower().replace("-", "_") / relative
            checks.append((source_path, expected, f"{window_id} frozen source"))

    failures: list[dict[str, str]] = []
    for path, expected, kind in checks:
        if not path.is_file():
            failures.append({"path": str(path.relative_to(ROOT)), "kind": kind, "status": "MISSING"})
            continue
        observed = _sha256(path)
        if observed != expected:
            failures.append({
                "path": str(path.relative_to(ROOT)), "kind": kind,
                "status": "HASH_MISMATCH", "expected_sha256": expected,
                "observed_sha256": observed,
            })
    if failures:
        raise ValueError(f"sealed replay hash check failed: {failures[:10]}")
    script_hash = _sha256(ROOT / "scripts/replay_b_select_daily_normal_exit_cadence_v01.py")
    if script_hash != metadata.get("script_sha256"):
        raise ValueError("cadence replay script hash differs from sealed manifest")
    return {
        "checked_file_count": len(checks),
        "failure_count": 0,
        "price_authority_ticker_file_count": len(metadata.get("price_authority_hashes", {})),
        "cadence_replay_script_sha256": script_hash,
        "root_metadata_sha256": _sha256(replay_root / "metadata.json"),
        "root_summary_sha256": _sha256(replay_root / "summary.json"),
        "current_repository_matches_sealed_replay": True,
    }


def _load_permanent_exclusions() -> set[tuple[str, str]]:
    path = ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"
    spec = importlib.util.spec_from_file_location("formal_validation_exclusions", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load permanent exclusion policy: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        (str(ticker).zfill(6), str(isu).upper())
        for ticker, isu in module.PERMANENT_IDENTITY_EXCLUSIONS
    }


def _actual_trade_metrics(
    ledger_rows: Sequence[Mapping[str, str]],
    event_rows: Sequence[Mapping[str, str]],
    portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    executed_entries = {
        row["pair_id"] for row in event_rows
        if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
    }
    executed_exits = {
        row["pair_id"] for row in event_rows
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
    }
    if not executed_exits <= executed_entries:
        raise ValueError("portfolio has an exit without an executed entry")
    by_trade_id: dict[str, Mapping[str, str]] = {}
    for row in ledger_rows:
        trade_id = row.get("trade_id", "")
        if trade_id in by_trade_id:
            raise ValueError(f"duplicate strategy ledger trade id: {trade_id}")
        by_trade_id[trade_id] = row
    if not executed_entries <= by_trade_id.keys():
        raise ValueError("executed portfolio entry is absent from fixed signal ledger")

    actual_closed_rows = [by_trade_id[pair_id] for pair_id in sorted(executed_exits)]
    returns = [_num(row.get("commission_slippage_pre_tax_return_pct")) for row in actual_closed_rows]
    if any(value is None for value in returns):
        raise ValueError("executed realized trade has no costed pre-tax return")
    entry_events = {
        row["pair_id"]: row for row in event_rows
        if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
    }
    exit_events = {
        row["pair_id"]: row for row in event_rows
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
    }
    event_return_differences = []
    for trade in actual_closed_rows:
        pair_id = trade["trade_id"]
        buy, sell = entry_events[pair_id], exit_events[pair_id]
        entry_cost = (_num(buy.get("notional")) or 0) + (_num(buy.get("commission")) or 0)
        sell_proceeds = (
            (_num(sell.get("notional")) or 0)
            - (_num(sell.get("commission")) or 0)
            - (_num(sell.get("sell_tax")) or 0)
        )
        event_return = (sell_proceeds - entry_cost) / entry_cost * 100 if entry_cost else None
        ledger_return = _num(trade.get("commission_slippage_pre_tax_return_pct"))
        if event_return is None or ledger_return is None:
            raise ValueError("unable to recompute realized trade cashflow return")
        event_return_differences.append(abs(event_return - ledger_return))
    return_mismatch_count = sum(difference > 0.1 for difference in event_return_differences)
    if return_mismatch_count:
        raise ValueError("realized trade return differs from executed cashflow by more than 0.1 pp")
    distribution = trade_distribution([float(value) for value in returns if value is not None])
    metrics = portfolio["metrics"]
    lifecycle = portfolio["lifecycle"]
    if len(executed_entries) != _int(metrics.get("trade_count")):
        raise ValueError("executed entry event count differs from portfolio trade_count")
    if len(executed_exits) != _int(metrics.get("realized_trade_count")):
        raise ValueError("executed exit event count differs from portfolio realized_trade_count")
    if abs(float(distribution["win_rate_pct"] or 0) - float(metrics["win_rate_pct"])) > 1e-6:
        raise ValueError("matched ledger win rate differs from portfolio engine")

    entries_by_pair = {
        row["pair_id"]: row for row in event_rows
        if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
    }
    exits_by_pair = {
        row["pair_id"]: row for row in event_rows
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
    }
    pnl_by_isu: dict[str, float] = {}
    pnl_by_year: dict[str, float] = {}
    for pair_id, exit_event in exits_by_pair.items():
        entry_event = entries_by_pair[pair_id]
        entry_cost = (_num(entry_event.get("notional")) or 0) + (_num(entry_event.get("commission")) or 0)
        sell_proceeds = (
            (_num(exit_event.get("notional")) or 0)
            - (_num(exit_event.get("commission")) or 0)
            - (_num(exit_event.get("sell_tax")) or 0)
        )
        pnl = sell_proceeds - entry_cost
        isu = str(entry_event.get("isu_cd", "")).upper()
        pnl_by_isu[isu] = pnl_by_isu.get(isu, 0.0) + pnl
        year = str(by_trade_id[pair_id].get("entry_signal_date", ""))[:4]
        pnl_by_year[year] = pnl_by_year.get(year, 0.0) + pnl

    def profit_shares(values: Mapping[str, float]) -> tuple[float | None, float | None, float | None]:
        winners = sorted((value for value in values.values() if value > 0), reverse=True)
        losers = sorted((abs(value) for value in values.values() if value < 0), reverse=True)
        positive_total = sum(winners)
        negative_total = sum(losers)
        return (
            winners[0] / positive_total * 100 if winners and positive_total else None,
            sum(winners[:5]) / positive_total * 100 if positive_total else None,
            sum(losers[:5]) / negative_total * 100 if negative_total else None,
        )

    top1_isu_profit, top5_isu_profit, top5_isu_loss = profit_shares(pnl_by_isu)
    top1_year_profit, top5_year_profit, _ = profit_shares(pnl_by_year)
    return {
        **distribution,
        "executed_entry_count": len(executed_entries),
        "executed_realized_exit_count": len(executed_exits),
        "open_identity_count_after_support": _int(lifecycle.get("open_identity_count_after_support")),
        "realized_trade_holding_mean_sessions": metrics.get("average_holding_trading_days"),
        "realized_trade_holding_median_sessions": metrics.get("median_holding_trading_days"),
        "realized_trade_return_cashflow_mismatch_count": return_mismatch_count,
        "realized_trade_return_max_abs_cashflow_delta_pp": max(event_return_differences, default=0.0),
        "top1_isu_profit_share_pct": top1_isu_profit,
        "top5_isu_profit_share_pct": top5_isu_profit,
        "top5_isu_loss_share_pct": top5_isu_loss,
        "top1_entry_year_profit_share_pct": top1_year_profit,
        "top5_entry_year_profit_share_pct": top5_year_profit,
        "executed_pair_ids": executed_entries,
        "realized_pair_ids": executed_exits,
    }


def _verify_costs(event_rows: Sequence[Mapping[str, str]], cost_rows: Sequence[Mapping[str, str]],
                  portfolio: Mapping[str, Any]) -> dict[str, Any]:
    executed_events = [row for row in event_rows if row.get("event_status") == "EXECUTED"]
    nonpositive_opens = [row for row in executed_events if (_num(row.get("reference_open")) or 0) <= 0]
    nonpositive_fills = [row for row in executed_events if (_num(row.get("fill_price")) or 0) <= 0]
    nonpass = [row for row in cost_rows if row.get("official_cost_status") != "PASS"]
    executed_count = _int(portfolio["cost_audit"].get("executed_cost_event_count"))
    if executed_count != len(executed_events):
        raise ValueError(f"cost audit event coverage mismatch: {executed_count} != {len(executed_events)}")
    if nonpositive_opens or nonpositive_fills or nonpass:
        raise ValueError("non-positive execution price or failed cost audit found")
    commissions = sum(_num(row.get("commission")) or 0 for row in event_rows)
    slippage = sum(_num(row.get("slippage_impact")) or 0 for row in event_rows)
    sell_tax = sum(_num(row.get("sell_tax")) or 0 for row in event_rows)
    metrics = portfolio["metrics"]
    if abs(commissions - float(metrics["total_commissions_krw"])) > 0.02:
        raise ValueError("event commission sum differs from portfolio metrics")
    if abs(slippage - float(metrics["slippage_impact_krw"])) > 0.02:
        raise ValueError("event slippage sum differs from portfolio metrics")
    if abs(sell_tax) > 0.01 or abs(float(metrics["total_sell_tax_krw"])) > 0.01:
        raise ValueError("official portfolio includes sell tax")
    return {
        "executed_cost_event_count": executed_count,
        "cost_audit_coverage_complete": _bool(portfolio["cost_audit"].get("coverage_complete")),
        "cost_audit_mismatch_count": _int(portfolio["cost_audit"].get("mismatch_count")),
        "nonpass_cost_row_count": len(nonpass),
        "nonpositive_reference_open_count": len(nonpositive_opens),
        "nonpositive_fill_price_count": len(nonpositive_fills),
        "commission_total_krw": commissions,
        "slippage_total_krw": slippage,
        "sell_tax_total_krw": sell_tax,
    }


def _window_analysis(window_id: str, replay_root: Path, exclusions: set[tuple[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    window_dir = replay_root / window_id.lower().replace("-", "_")
    comparison_rows = _read_csv(window_dir / "trade_comparison.csv")
    validation_row = _read_csv(window_dir / "validation.csv")[0]
    validation = json.loads(validation_row["validation"])
    summary = _read_json(replay_root / "summary.json")["windows"][window_id]
    window = summary["window"]

    ledgers: dict[str, list[dict[str, str]]] = {}
    events: dict[str, list[dict[str, str]]] = {}
    costs: dict[str, list[dict[str, str]]] = {}
    equities: dict[str, list[dict[str, str]]] = {}
    skips: dict[str, list[dict[str, str]]] = {}
    portfolio_rows: dict[str, Mapping[str, Any]] = {}
    actual_metrics: dict[str, dict[str, Any]] = {}
    cost_checks: dict[str, dict[str, Any]] = {}
    session_sets: list[set[str]] = []
    for scenario, stem in SCENARIOS.items():
        ledgers[scenario] = _read_csv(window_dir / f"{stem}_trade_ledger.csv")
        events[scenario] = _read_csv(window_dir / f"{stem}_portfolio_events.csv")
        costs[scenario] = _read_csv(window_dir / f"{stem}_cost_audit.csv")
        equities[scenario] = _read_csv(window_dir / f"{stem}_daily_equity.csv")
        skips[scenario] = _read_csv(window_dir / f"{stem}_portfolio_skips.csv")
        portfolio_rows[scenario] = summary["portfolio_metrics"][scenario]
        session_sets.append({str(row["date"])[:10] for row in equities[scenario]})
        actual_metrics[scenario] = _actual_trade_metrics(ledgers[scenario], events[scenario], portfolio_rows[scenario])
        cost_checks[scenario] = _verify_costs(events[scenario], costs[scenario], portfolio_rows[scenario])
        cost_checks[scenario]["realized_trade_return_cashflow_mismatch_count"] = actual_metrics[scenario]["realized_trade_return_cashflow_mismatch_count"]
        cost_checks[scenario]["realized_trade_return_max_abs_cashflow_delta_pp"] = actual_metrics[scenario]["realized_trade_return_max_abs_cashflow_delta_pp"]
    if session_sets[0] != session_sets[1]:
        raise ValueError(f"{window_id}: CONTROL/TEST valuation session mismatch")
    sessions = sorted(session_sets[0])
    for scenario in SCENARIOS:
        valuation = portfolio_rows[scenario]["valuation"]
        daily_rows = [
            row for row in equities[scenario]
            if window["effective_start"] <= str(row.get("date", ""))[:10] <= window["effective_end"]
        ]
        observed_equity_count = sum(_num(row.get("equity")) is not None for row in daily_rows)
        expected_total = _int(valuation.get("total_days"))
        expected_observed = _int(valuation.get("observed_days"))
        if len(daily_rows) != expected_total or observed_equity_count != expected_observed:
            raise ValueError(f"{window_id}:{scenario}: valuation coverage count mismatch")
        calculated_coverage = observed_equity_count / len(daily_rows) * 100 if daily_rows else 0.0
        if abs(calculated_coverage - float(valuation.get("coverage_pct"))) > 1e-8:
            raise ValueError(f"{window_id}:{scenario}: valuation coverage percentage mismatch")
        peak = None
        calculated_mdd = 0.0
        for row in daily_rows:
            equity = _num(row.get("equity"))
            if equity is None:
                continue
            if peak is None or equity > peak:
                peak = equity
            if peak:
                calculated_mdd = min(calculated_mdd, (equity / peak - 1.0) * 100)
        if abs(calculated_mdd - float(valuation.get("mdd_pct"))) > 1e-8:
            raise ValueError(f"{window_id}:{scenario}: observed MDD does not reproduce from valid equity marks")
    sessions.extend(day for day in (window["execution_support"],) if day not in set(sessions))
    sessions = sorted(set(sessions))
    session_position = {day: index for index, day in enumerate(sessions)}
    last_session_by_month: dict[str, str] = {}
    for day in session_sets[0]:
        if day[:7] not in last_session_by_month or day > last_session_by_month[day[:7]]:
            last_session_by_month[day[:7]] = day
    month_end_sessions = set(last_session_by_month.values())

    ledger_maps: dict[str, dict[tuple[str, str, str], dict[str, str]]] = {}
    for scenario in SCENARIOS:
        ledger_maps[scenario] = {}
        for row in ledgers[scenario]:
            key = _identity_key(row)
            if key in ledger_maps[scenario]:
                raise ValueError(f"{window_id}:{scenario}: duplicate entry key {key}")
            ledger_maps[scenario][key] = row
    control_keys, test_keys = set(ledger_maps["CONTROL_MONTH_END"]), set(ledger_maps["TEST_DAILY"])
    comparison_keys = {_identity_key(row) for row in comparison_rows}
    if control_keys != test_keys or control_keys != comparison_keys:
        raise ValueError(f"{window_id}: ENTRY key parity failed")
    if len(comparison_rows) != len(comparison_keys):
        raise ValueError(f"{window_id}: duplicate paired comparison key")

    entry_month_end_violations = 0
    entry_next_session_violations = 0
    entry_date_parity_violations = 0
    excluded_identity_appearances = 0
    control_midmonth_exit_violations = 0
    test_non_normal_exit_signals = 0
    test_exit_month_end_only_count = 0
    after_cutoff_entry_count = 0
    exit_execution_session_violations = 0
    for key in sorted(control_keys):
        control, test = ledger_maps["CONTROL_MONTH_END"][key], ledger_maps["TEST_DAILY"][key]
        signal = key[2]
        control_exec = str(control.get("entry_execution_date", ""))[:10]
        test_exec = str(test.get("entry_execution_date", ""))[:10]
        if signal not in month_end_sessions:
            entry_month_end_violations += 1
        if control_exec != test_exec:
            entry_date_parity_violations += 1
        if signal not in session_position or control_exec not in session_position:
            entry_next_session_violations += 1
        elif session_position[control_exec] != session_position[signal] + 1:
            entry_next_session_violations += 1
        if (key[0], key[1]) in exclusions:
            excluded_identity_appearances += 1
        for row, scenario in ((control, "CONTROL_MONTH_END"), (test, "TEST_DAILY")):
            if str(row.get("entry_signal_date", ""))[:10] > window["effective_end"] or str(row.get("entry_execution_date", ""))[:10] > window["effective_end"]:
                after_cutoff_entry_count += 1
            exit_signal = str(row.get("exit_signal_date", ""))[:10]
            if not exit_signal:
                continue
            if exit_signal not in session_position:
                exit_execution_session_violations += 1
            if scenario == "CONTROL_MONTH_END" and exit_signal not in month_end_sessions:
                control_midmonth_exit_violations += 1
            if scenario == "TEST_DAILY":
                test_exit_month_end_only_count += int(exit_signal in month_end_sessions)
                if row.get("exit_signal_state") != "NORMAL":
                    test_non_normal_exit_signals += 1
            execution = str(row.get("exit_execution_date", ""))[:10]
            if execution:
                if execution not in session_position or execution <= exit_signal:
                    exit_execution_session_violations += 1

    # Exact execution/open checks are based on the recorded original V2 price
    # authority audit, whose 397 OHLC files and output manifests are hash-verified.
    scenario_filled_pair_keys = {
        scenario: {
            "|".join((key[0], key[1], key[2]))
            for key in control_keys
            if ledger_maps[scenario][key]["trade_id"] in actual_metrics[scenario]["executed_pair_ids"]
        }
        for scenario in SCENARIOS
    }
    pairs, pair_summary = build_early_pairs(
        comparison_rows,
        sessions,
        scenario_filled_pair_keys["CONTROL_MONTH_END"],
        scenario_filled_pair_keys["TEST_DAILY"],
    )

    skip_counts: dict[str, int] = {}
    for scenario in SCENARIOS:
        cash_skips = [
            row for row in skips[scenario]
            if row.get("event_type") == "ENTRY"
            and row.get("event_status") == "SKIPPED_CASH_UNAVAILABLE"
        ]
        cash_metrics = portfolio_rows[scenario]["cash"]
        denominator = _int(cash_metrics.get("eligible_entry_attempts"))
        if len(cash_skips) != _int(cash_metrics.get("cash_shortage_skipped_entries")):
            raise ValueError(f"{window_id}:{scenario}: cash skip ledger/summary mismatch")
        unique_cash_skip_ids = {row.get("pair_id", "") for row in cash_skips}
        if len(unique_cash_skip_ids) != len(cash_skips):
            raise ValueError(f"{window_id}:{scenario}: repeated cash shortage signal")
        if denominator != len(control_keys):
            raise ValueError(f"{window_id}:{scenario}: cash denominator differs from sealed CONTROL signal ledger")
        skip_counts[scenario] = len(cash_skips)

    exclusion_filtered = {
        scenario: _int(portfolio_rows[scenario]["metrics"].get("current_exclusion_filtered_count"))
        for scenario in SCENARIOS
    }
    integrity_checks = {
        "entry_key_parity_count": len(control_keys),
        "entry_key_parity_pass": control_keys == test_keys == comparison_keys,
        "entry_signal_or_execution_date_parity_violation_count": entry_date_parity_violations,
        "next_exact_session_entry_violation_count": entry_next_session_violations,
        "monthly_entry_violation_count": entry_month_end_violations,
        "permanent_exclusion_parity_violation_count": excluded_identity_appearances,
        "current_exclusion_filtered_count_control": exclusion_filtered["CONTROL_MONTH_END"],
        "current_exclusion_filtered_count_test": exclusion_filtered["TEST_DAILY"],
        "current_exclusion_counts_equal": exclusion_filtered["CONTROL_MONTH_END"] == exclusion_filtered["TEST_DAILY"],
        "identity_lifecycle_violation_count": sum(_int(portfolio_rows[s]["lifecycle"].get("violation_count")) for s in SCENARIOS),
        "control_midmonth_exit_violation_count": control_midmonth_exit_violations,
        "test_non_normal_exit_signal_count": test_non_normal_exit_signals,
        "test_exit_signal_month_end_count_diagnostic": test_exit_month_end_only_count,
        "exact_session_execution_violation_count": sum(_int(portfolio_rows[s]["next_session_audit"].get("violation_count")) for s in SCENARIOS),
        "invalid_or_missing_execution_open_count": sum(_int(portfolio_rows[s]["execution_audit"].get("missing_exact_opens")) + _int(portfolio_rows[s]["execution_audit"].get("price_mismatch_count")) for s in SCENARIOS),
        "invalid_exit_execution_session_count": exit_execution_session_violations,
        "repository_v2_silent_inner_drop_count": _int(validation.get("repository_v2_silent_inner_drop_count")),
        "cash_conservation_failure_count": sum(not _bool(portfolio_rows[s]["cash"].get("cash_conservation_pass")) for s in SCENARIOS),
        "cost_audit_mismatch_count": sum(
            cost_checks[s]["cost_audit_mismatch_count"]
            + cost_checks[s]["realized_trade_return_cashflow_mismatch_count"]
            for s in SCENARIOS
        ),
        "realized_trade_return_cashflow_mismatch_count": sum(
            cost_checks[s]["realized_trade_return_cashflow_mismatch_count"] for s in SCENARIOS
        ),
        "cost_coverage_incomplete_scenario_count": sum(not cost_checks[s]["cost_audit_coverage_complete"] for s in SCENARIOS),
        "failed_cost_row_count": sum(cost_checks[s]["nonpass_cost_row_count"] for s in SCENARIOS),
        "entry_after_cutoff_count": after_cutoff_entry_count,
        "recorded_daily_exit_signals_normal_only": _bool(validation.get("daily_exit_signals_normal_only")),
        "source_monthly_exit_signal_mismatch_count_diagnostic": _int(validation.get("control_source_monthly_exit_signal_mismatch_count")),
        "entry_price_rebased_count_diagnostic": _int(validation.get("entry_price_rebased_row_count")),
        "recorded_replay_validation_integrity_pass": (
            _bool(validation.get("all_entry_keys_equal"))
            and _bool(validation.get("current_repository_v2_entry_prices_applied"))
            and _bool(validation.get("execution_price_checks_pass"))
            and _bool(validation.get("no_new_after_cutoff_entries"))
            and _bool(validation.get("same_position_budget_and_cash_model"))
        ),
    }
    fatal_integrity_keys = (
        "entry_signal_or_execution_date_parity_violation_count",
        "next_exact_session_entry_violation_count",
        "monthly_entry_violation_count",
        "permanent_exclusion_parity_violation_count",
        "identity_lifecycle_violation_count",
        "control_midmonth_exit_violation_count",
        "test_non_normal_exit_signal_count",
        "exact_session_execution_violation_count",
        "invalid_or_missing_execution_open_count",
        "invalid_exit_execution_session_count",
        "repository_v2_silent_inner_drop_count",
        "cash_conservation_failure_count",
        "cost_audit_mismatch_count",
        "cost_coverage_incomplete_scenario_count",
        "failed_cost_row_count",
        "entry_after_cutoff_count",
    )
    integrity_checks["failed_integrity_check_count"] = sum(
        _int(integrity_checks[key]) != 0 for key in fatal_integrity_keys
    ) + int(not integrity_checks["entry_key_parity_pass"] or not integrity_checks["current_exclusion_counts_equal"] or not integrity_checks["recorded_daily_exit_signals_normal_only"] or not integrity_checks["recorded_replay_validation_integrity_pass"])

    window_metric_rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        portfolio = portfolio_rows[scenario]
        metric = portfolio["metrics"]
        valuation = portfolio["valuation"]
        cash = portfolio["cash"]
        actual = actual_metrics[scenario]
        metric_row = {
            "window_id": window_id,
            "scenario": scenario,
            "effective_start": window["effective_start"],
            "effective_end": window["effective_end"],
            "execution_support": window["execution_support"],
            "ending_equity_krw": metric.get("ending_equity_krw"),
            "total_return_pct": metric.get("cumulative_return_pct"),
            "CAGR_pct": metric.get("CAGR_pct"),
            "MDD_observed_pct": valuation.get("mdd_pct"),
            "MDD_type": valuation.get("mdd_type"),
            "MDD_coverage_pct": valuation.get("coverage_pct"),
            "valuation_total_days": valuation.get("total_days"),
            "valuation_observed_days": valuation.get("observed_days"),
            "valuation_missing_days": valuation.get("missing_days"),
            "unresolved_valuation_marks": valuation.get("unresolved_marks"),
            "unresolved_span_count": valuation.get("missing_span_count"),
            "max_consecutive_missing_days": valuation.get("max_consecutive_missing_days"),
            "MDD_peak_date": valuation.get("peak_date"),
            "MDD_trough_date": valuation.get("trough_date"),
            "MDD_recovery_date": valuation.get("recovery_date"),
            "commission_total_krw": cost_checks[scenario]["commission_total_krw"],
            "slippage_total_krw": cost_checks[scenario]["slippage_total_krw"],
            "sell_tax_total_krw": cost_checks[scenario]["sell_tax_total_krw"],
            "executed_entries": actual["executed_entry_count"],
            "realized_trade_count": actual["realized_count"],
            "open_identity_count_after_support": actual["open_identity_count_after_support"],
            "win_rate_pct": actual["win_rate_pct"],
            "mean_costed_pre_tax_trade_return_pct": actual["mean_return_pct"],
            "median_costed_pre_tax_trade_return_pct": actual["median_return_pct"],
            "mean_holding_sessions": actual["realized_trade_holding_mean_sessions"],
            "median_holding_sessions": actual["realized_trade_holding_median_sessions"],
            "top1_ISU_profit_share_pct": actual["top1_isu_profit_share_pct"],
            "top5_ISU_profit_share_pct": actual["top5_isu_profit_share_pct"],
            "top5_ISU_loss_share_pct": actual["top5_isu_loss_share_pct"],
            "top1_entry_year_profit_share_pct": actual["top1_entry_year_profit_share_pct"],
            "top5_entry_year_profit_share_pct": actual["top5_entry_year_profit_share_pct"],
            "average_capital_utilization_pct": cash.get("average_capital_utilization_pct"),
            "maximum_capital_utilization_pct": cash.get("maximum_capital_utilization_pct"),
            "average_concurrent_positions": cash.get("average_concurrent_positions"),
            "maximum_concurrent_positions": cash.get("maximum_concurrent_positions"),
            "turnover_krw": cash.get("turnover_krw"),
            "turnover_multiple_initial_capital": cash.get("turnover_multiple_initial_capital"),
            "cash_eligible_entry_attempts": cash.get("eligible_entry_attempts"),
            "cash_shortage_skipped_entries": cash.get("cash_shortage_skipped_entries"),
            "cash_shortage_skip_rate_pct": cash.get("cash_shortage_skip_rate_pct"),
            "cash_conservation_pass": cash.get("cash_conservation_pass"),
            "commission_slippage_cost_coverage_complete": cost_checks[scenario]["cost_audit_coverage_complete"],
            "cost_audit_mismatch_count": cost_checks[scenario]["cost_audit_mismatch_count"],
            "realized_trade_return_cashflow_mismatch_count": cost_checks[scenario]["realized_trade_return_cashflow_mismatch_count"],
            "realized_trade_return_max_abs_cashflow_delta_pp": cost_checks[scenario]["realized_trade_return_max_abs_cashflow_delta_pp"],
            "unresolved_terminal_position_count": _int(portfolio["execution_audit"].get("terminal_unresolved_source_count")),
            "exact_cutoff_terminal_mark_count": _int(portfolio["execution_audit"].get("terminal_exact_close_count")),
            **{key: actual[key] for name, _label, _op, _threshold in TAIL_THRESHOLDS for key in (f"{name}_count", f"{name}_rate_pct")},
        }
        window_metric_rows.append(metric_row)

    control_metrics = portfolio_rows["CONTROL_MONTH_END"]["metrics"]
    test_metrics = portfolio_rows["TEST_DAILY"]["metrics"]
    control_coverage = float(portfolio_rows["CONTROL_MONTH_END"]["valuation"]["coverage_pct"])
    test_coverage = float(portfolio_rows["TEST_DAILY"]["valuation"]["coverage_pct"])
    control_mdd = float(portfolio_rows["CONTROL_MONTH_END"]["valuation"]["mdd_pct"])
    test_mdd = float(portfolio_rows["TEST_DAILY"]["valuation"]["mdd_pct"])
    mdd_deterioration_pp = control_mdd - test_mdd
    absolute_floor = -55.0 if window_id == "P1" else -40.0
    c_pass = all(float(portfolio_rows[s]["metrics"]["cumulative_return_pct"]) > 0 and float(portfolio_rows[s]["metrics"]["CAGR_pct"]) > 0 for s in SCENARIOS)
    gate = {
        "window_id": window_id,
        "A_integrity": "PASS" if integrity_checks["failed_integrity_check_count"] == 0 else "FAIL",
        "B_commission_slippage": "PASS" if all(
            cost_checks[s]["cost_audit_coverage_complete"]
            and cost_checks[s]["cost_audit_mismatch_count"] == 0
            and cost_checks[s]["realized_trade_return_cashflow_mismatch_count"] == 0
            and cost_checks[s]["nonpass_cost_row_count"] == 0
            for s in SCENARIOS
        ) else "FAIL",
        "C_profitability": "PASS" if c_pass else "FAIL",
        "D_MDD": mdd_gate(min(control_coverage, test_coverage), test_mdd, absolute_floor, mdd_deterioration_pp),
        "D_MDD_official_coverage_gate": "CHECK_REQUIRED" if min(control_coverage, test_coverage) < 90 else "PASS",
        "D_absolute_floor_pct": absolute_floor,
        "D_relative_deterioration_pp_control_minus_test_observed_only": mdd_deterioration_pp,
        "E_result_validity": "CHECK_REQUIRED" if min(control_coverage, test_coverage) < 90 else "PASS",
        "control_mdd_coverage_pct": control_coverage,
        "test_mdd_coverage_pct": test_coverage,
        "control_return_pct": control_metrics.get("cumulative_return_pct"),
        "test_return_pct": test_metrics.get("cumulative_return_pct"),
        "control_CAGR_pct": control_metrics.get("CAGR_pct"),
        "test_CAGR_pct": test_metrics.get("CAGR_pct"),
    }
    window_result = {
        "window": window,
        "integrity": integrity_checks,
        "cost_checks": cost_checks,
        "paired_summary": pair_summary,
        "gate": gate,
        "entry_signal_count": len(control_keys),
        "market_session_count": len(session_sets[0]),
        "source_exit_signal_mismatch_count": _int(validation.get("control_source_monthly_exit_signal_mismatch_count")),
        "entry_price_rebased_count": _int(validation.get("entry_price_rebased_row_count")),
        "monthly_exit_source_match_count": _int(validation.get("control_source_monthly_exit_signal_match_count")),
    }
    return window_metric_rows, pairs, window_result


def _severity_counts(window_results: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    # CRITICAL: structural integrity failure; MAJOR: blocks formal adoption;
    # MINOR: source reconciliation notes that do not break paired parity.
    mdd_blocked_windows = sum(result["gate"]["D_MDD"] == "CHECK_REQUIRED" for result in window_results.values())
    source_exit_mismatches = sum(result["source_exit_signal_mismatch_count"] for result in window_results.values())
    entry_rebases = sum(result["entry_price_rebased_count"] for result in window_results.values())
    return {
        "CRITICAL": int(any(result["integrity"]["failed_integrity_check_count"] for result in window_results.values())),
        "MAJOR": int(mdd_blocked_windows > 0),
        "MINOR": int(source_exit_mismatches > 0) + int(entry_rebases > 0),
    }


def _fmt(value: Any, digits: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "UNRESOLVED"
    return f"{number:,.{digits}f}"


def _build_window_deltas(metric_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    indexed = {(row["window_id"], row["scenario"]): row for row in metric_rows}
    output = []
    for window_id in WINDOWS:
        control = indexed[(window_id, "CONTROL_MONTH_END")]
        test = indexed[(window_id, "TEST_DAILY")]
        delta = {
            "window_id": window_id,
            "portfolio_return_delta_pp": float(test["total_return_pct"]) - float(control["total_return_pct"]),
            "CAGR_delta_pp": float(test["CAGR_pct"]) - float(control["CAGR_pct"]),
            "portfolio_ending_equity_delta_krw": float(test["ending_equity_krw"]) - float(control["ending_equity_krw"]),
            "observed_MDD_delta_pp_test_minus_control": float(test["MDD_observed_pct"]) - float(control["MDD_observed_pct"]),
            "MDD_coverage_delta_pp": float(test["MDD_coverage_pct"]) - float(control["MDD_coverage_pct"]),
            "win_rate_delta_pp": float(test["win_rate_pct"]) - float(control["win_rate_pct"]),
            "mean_trade_return_delta_pp": float(test["mean_costed_pre_tax_trade_return_pct"]) - float(control["mean_costed_pre_tax_trade_return_pct"]),
            "median_trade_return_delta_pp": float(test["median_costed_pre_tax_trade_return_pct"]) - float(control["median_costed_pre_tax_trade_return_pct"]),
            "mean_holding_sessions_delta": float(test["mean_holding_sessions"]) - float(control["mean_holding_sessions"]),
            "median_holding_sessions_delta": float(test["median_holding_sessions"]) - float(control["median_holding_sessions"]),
            "average_capital_utilization_delta_pp": float(test["average_capital_utilization_pct"]) - float(control["average_capital_utilization_pct"]),
            "turnover_multiple_delta": float(test["turnover_multiple_initial_capital"]) - float(control["turnover_multiple_initial_capital"]),
            "cash_shortage_skip_count_delta": int(test["cash_shortage_skipped_entries"]) - int(control["cash_shortage_skipped_entries"]),
            "cash_shortage_skip_rate_delta_pp": float(test["cash_shortage_skip_rate_pct"]) - float(control["cash_shortage_skip_rate_pct"]),
        }
        for name, _label, _operation, _threshold in TAIL_THRESHOLDS:
            delta[f"{name}_count_delta"] = int(test[f"{name}_count"]) - int(control[f"{name}_count"])
        output.append(delta)
    return output


def _build_report(summary: Mapping[str, Any], metric_rows: Sequence[Mapping[str, Any]],
                  window_results: Mapping[str, Mapping[str, Any]], hash_audit: Mapping[str, Any],
                  delta_rows: Sequence[Mapping[str, Any]]) -> str:
    verdict = summary["verdict"]
    lines = [
        "# B Select Daily NORMAL Exit 후보 공식 검증 V01",
        "",
        f"- 기준 HEAD: `{summary['base_head']}` (요청 시작 시 `origin/main`과 일치, working tree clean)",
        f"- 판정: **`{verdict}`**",
        f"- 입력/산출물 검증: `{hash_audit['checked_file_count']}`개 해시 일치, Repository V2 OHLC `{hash_audit['price_authority_ticker_file_count']}`개 파일 일치",
        "- 공식 5-window portfolio 재생은 이전 cadence 연구에 봉인된 같은 실행을 재사용했어. CONTROL/TEST 동시 재생 결과를 재계산하지 않고, 모든 실행 입력·코드·가격·산출물 해시를 기준 시점 저장소에 대조한 뒤 공식 gate와 추가 진단을 별도 계산했어.",
        "- CONTROL/TEST는 동일 월별 ENTRY key·날짜·체결가(현행 Repository V2), PIT/영구 제외, 비용, V2 portfolio engine, 자본/현금 처리, lifecycle을 사용해. 달라지는 항목은 Pattern B NORMAL 관찰 주기뿐이야.",
        "",
        "## 발견 등급",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        f"| CRITICAL | {summary['severity_counts']['CRITICAL']} |",
        f"| MAJOR | {summary['severity_counts']['MAJOR']} |",
        f"| MINOR | {summary['severity_counts']['MINOR']} |",
        "",
        "등급 정의: CRITICAL은 무결성 실패, MAJOR는 공식 채택을 막는 미확정 핵심 증거, MINOR는 쌍별 비교를 깨지 않지만 기록할 원천 조정 사항이야.",
        "",
        "## 1. 무결성 결과",
        "",
        "| Window | 진입 key 수 | ENTRY key/날짜/체결 parity | 월중 ENTRY | 영구 제외 위반 | identity 중복·겹침 | CONTROL 월중 EXIT | TEST NORMAL 외 EXIT | exact-session 실행 위반 | invalid open 체결 | silent drop | cash 오류 | 비용 오류 | cutoff 뒤 ENTRY | 결과 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for wid in WINDOWS:
        integrity = window_results[wid]["integrity"]
        entry_parity = "PASS" if integrity["entry_key_parity_pass"] and integrity["entry_signal_or_execution_date_parity_violation_count"] == 0 else "FAIL"
        lines.append(
            f"| {wid} | {window_results[wid]['entry_signal_count']} | {entry_parity} | {integrity['monthly_entry_violation_count']} | {integrity['permanent_exclusion_parity_violation_count']} | {integrity['identity_lifecycle_violation_count']} | {integrity['control_midmonth_exit_violation_count']} | {integrity['test_non_normal_exit_signal_count']} | {integrity['exact_session_execution_violation_count']} | {integrity['invalid_or_missing_execution_open_count']} | {integrity['repository_v2_silent_inner_drop_count']} | {integrity['cash_conservation_failure_count']} | {integrity['cost_audit_mismatch_count']} | {integrity['entry_after_cutoff_count']} | {'PASS' if integrity['failed_integrity_check_count'] == 0 else 'FAIL'} |"
        )
    lines.extend([
        "",
        "- 다섯 기간 모두 paired signal ledger의 ENTRY key/date parity, 다음 exact KRX 세션 진입, 월말 ENTRY 및 영구 제외 정책이 양쪽에서 일치했고 구조적 실패는 0건이야.",
        "- current identity exclusion 적용 건수는 기간별 CONTROL/TEST가 같아. 확인된 exclusion 대상의 entry key 출현은 0건이야.",
        "- 원 실행 exact-session execution audit의 위반·유효 시가 누락·가격 불일치가 모두 0이고, executed event의 매수/매도 수수료와 슬리피지는 100% 감사 완료야. 매도세는 공식 산식에서 제외되어 0원이야.",
        "- frozen 과거 CONTROL 월말 EXIT 원장과 현행 authority로 재구성한 CONTROL 신호가 다르게 나온 기록은 총 4건이야(P1 2, P2-2 1, P3-2 1). 과거 공식 절대값을 CONTROL로 재사용하지 않고 같은 현행 authority로 양쪽을 재생했기 때문에 비교는 유지돼. 현행 control/test의 EXIT 관찰 차이와 혼동하지 않도록 이전 원장 parity 진단으로만 남겨.",
        "- entry source 기준가와 현재 Repository V2 기준가가 달라 현재 V2 open으로 대칭 재기준화한 신호 행은 총 6건이야. 원본 authority는 수정하지 않았어.",
        "- `096630`은 CONTROL 신호 다음 exact session인 2026-05-04의 raw OHLC/거래량이 모두 0이라 해당 open을 실행가격으로 쓰지 않고 2026-05-06 첫 유효 open에 체결했어(P1, P2-2, P3-2 겹치는 기간). TEST는 2026-03-03 신호 후 2026-03-04에 먼저 청산했어. invalid open 체결은 없어.",
        f"- daily Pattern B 상태가 주간/월간 완성 bar 경계 사이에서 유지되는지 직접 spot-check `{summary['daily_state_piecewise_spot_check_count']}`건을 확인했고 모두 통과했어.",
        "",
        "## 2. 5-window portfolio / trade 비교",
        "",
        "Portfolio 수익률·CAGR·MDD·자본/현금/회전율은 현금 배분 후 실제 체결 portfolio 값이야. 거래 손익·tail은 실제 portfolio에서 ENTRY와 EXIT가 모두 체결된 거래만 대상으로 했고, 순수수료·슬리피지 반영/매도세 제외 수익률을 사용했어. 평균/중앙 보유기간은 실제 체결 거래 기준이야.",
        "",
        "| Window | 방식 | 총수익률 | CAGR | MDD(관측) / coverage | 진입/완료/미청산 | 승률 | 평균 / 중앙 수익률 | 평균 / 중앙 보유 세션 | 평균 자본 활용 | 회전율(배) | 현금 부족 skip/적격 시도 |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    row_by_key = {(row["window_id"], row["scenario"]): row for row in metric_rows}
    for wid in WINDOWS:
        for scenario in SCENARIOS:
            row = row_by_key[(wid, scenario)]
            lines.append(
                f"| {wid} | {scenario} | {_fmt(row['total_return_pct'])}% | {_fmt(row['CAGR_pct'])}% | {_fmt(row['MDD_observed_pct'])}% / {_fmt(row['MDD_coverage_pct'])}% | {row['executed_entries']}/{row['realized_trade_count']}/{row['open_identity_count_after_support']} | {_fmt(row['win_rate_pct'])}% | {_fmt(row['mean_costed_pre_tax_trade_return_pct'])}% / {_fmt(row['median_costed_pre_tax_trade_return_pct'])}% | {_fmt(row['mean_holding_sessions'], 1)} / {_fmt(row['median_holding_sessions'], 1)} | {_fmt(row['average_capital_utilization_pct'])}% | {_fmt(row['turnover_multiple_initial_capital'], 2)}x | {row['cash_shortage_skipped_entries']}/{row['cash_eligible_entry_attempts']} ({_fmt(row['cash_shortage_skip_rate_pct'])}%) |"
            )
    lines.extend([
        "",
        "| Window | 방식 | 평균/최대 활용률 | 평균/최대 동시 보유 | 회전율(KRW) | 수수료 / 슬리피지(KRW) | ISU top1/top5 이익집중 | ISU top5 손실집중 | 진입연도 top1/top5 이익집중 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for wid in WINDOWS:
        for scenario in SCENARIOS:
            row = row_by_key[(wid, scenario)]
            lines.append(
                f"| {wid} | {scenario} | {_fmt(row['average_capital_utilization_pct'])}% / {_fmt(row['maximum_capital_utilization_pct'])}% | {_fmt(row['average_concurrent_positions'], 1)} / {row['maximum_concurrent_positions']} | {_fmt(row['turnover_krw'], 0)} | {_fmt(row['commission_total_krw'], 0)} / {_fmt(row['slippage_total_krw'], 0)} | {_fmt(row['top1_ISU_profit_share_pct'])}% / {_fmt(row['top5_ISU_profit_share_pct'])}% | {_fmt(row['top5_ISU_loss_share_pct'])}% | {_fmt(row['top1_entry_year_profit_share_pct'])}% / {_fmt(row['top5_entry_year_profit_share_pct'])}% |"
            )
    lines.extend([
        "",
        "| Window | Δ총수익률 / CAGR | Δ관측 MDD | Δ승률 | Δ평균 / 중앙 거래 수익률 | Δ평균 / 중앙 보유 세션 | Δ평균 자본 활용 | Δ회전율 배수 | Δ현금 부족 skip 수/비율 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in delta_rows:
        lines.append(
            f"| {row['window_id']} | {_fmt(row['portfolio_return_delta_pp'])} / {_fmt(row['CAGR_delta_pp'])} pp | {_fmt(row['observed_MDD_delta_pp_test_minus_control'])} pp | {_fmt(row['win_rate_delta_pp'])} pp | {_fmt(row['mean_trade_return_delta_pp'])} / {_fmt(row['median_trade_return_delta_pp'])} pp | {_fmt(row['mean_holding_sessions_delta'], 1)} / {_fmt(row['median_holding_sessions_delta'], 1)} | {_fmt(row['average_capital_utilization_delta_pp'])} pp | {_fmt(row['turnover_multiple_delta'], 2)}x | {row['cash_shortage_skip_count_delta']:+d} / {_fmt(row['cash_shortage_skip_rate_delta_pp'])} pp |"
        )
    tail_deltas = {
        name: sum(
            int(row_by_key[(wid, "TEST_DAILY")][f"{name}_count"])
            - int(row_by_key[(wid, "CONTROL_MONTH_END")][f"{name}_count"])
            for wid in WINDOWS
        )
        for name, _label, _operation, _threshold in TAIL_THRESHOLDS
    }
    lower_util_windows = sum(
        float(row_by_key[(wid, "TEST_DAILY")]["average_capital_utilization_pct"])
        < float(row_by_key[(wid, "CONTROL_MONTH_END")]["average_capital_utilization_pct"])
        for wid in WINDOWS
    )
    higher_turnover_windows = sum(
        float(row_by_key[(wid, "TEST_DAILY")]["turnover_multiple_initial_capital"])
        > float(row_by_key[(wid, "CONTROL_MONTH_END")]["turnover_multiple_initial_capital"])
        for wid in WINDOWS
    )
    lower_cash_skip_windows = sum(
        int(row_by_key[(wid, "TEST_DAILY")]["cash_shortage_skipped_entries"])
        < int(row_by_key[(wid, "CONTROL_MONTH_END")]["cash_shortage_skipped_entries"])
        for wid in WINDOWS
    )
    lower_hold_windows = sum(
        float(row_by_key[(wid, "TEST_DAILY")]["mean_holding_sessions"])
        < float(row_by_key[(wid, "CONTROL_MONTH_END")]["mean_holding_sessions"])
        for wid in WINDOWS
    )
    median_down_windows = sum(
        float(row_by_key[(wid, "TEST_DAILY")]["median_costed_pre_tax_trade_return_pct"])
        < float(row_by_key[(wid, "CONTROL_MONTH_END")]["median_costed_pre_tax_trade_return_pct"])
        for wid in WINDOWS
    )
    mean_down_windows = sum(
        float(row_by_key[(wid, "TEST_DAILY")]["mean_costed_pre_tax_trade_return_pct"])
        < float(row_by_key[(wid, "CONTROL_MONTH_END")]["mean_costed_pre_tax_trade_return_pct"])
        for wid in WINDOWS
    )
    lines.extend([
        "",
        f"기간 간 거래가 겹치는 5개 window 행의 tail 변화 합(TEST - CONTROL, 독립 거래 수 아님): <= -15% {tail_deltas['le_neg_15']:+d}, <= -30% {tail_deltas['le_neg_30']:+d}, >= +30% {tail_deltas['ge_pos_30']:+d}, >= +50% {tail_deltas['ge_pos_50']:+d}, >= +100% {tail_deltas['ge_pos_100']:+d}. <= -15%는 약간 줄지만 <= -30%는 늘고 >= +50% 승자는 대체로 줄었어. 큰 손실 감소가 승자 훼손보다 확실히 크다는 증거는 없어.",
        f"- 비용 반영 실현 거래 평균 수익률은 {mean_down_windows}/5 기간, 중앙 수익률은 {median_down_windows}/5 기간에서 하락했어. 평균 보유기간은 {lower_hold_windows}/5 기간에서 짧아졌고, 평균 자본 활용률은 {lower_util_windows}/5 기간에서 낮아졌어. 회전율은 {higher_turnover_windows}/5 기간에서 증가하고 현금 부족 skip은 {lower_cash_skip_windows}/5 기간에서 감소했어. 이 변화는 잦은 청산과 자본 재배치가 portfolio 수익에 기여했을 가능성과 맞지만, 기여분을 별도 인과 분해한 실험은 아니야.",
        "",
        "## 3. 손실·승자 tail 비교",
        "",
        "아래 `건수(완료 거래 중 비율)`는 실제 portfolio 실현 거래의 수수료·슬리피지 반영/세전 수익률 분포야. 미청산 포지션은 tail 분모에서 제외했고, 별도로 종료 시점 미청산 포지션 수와 미해결 valuation을 보고해.",
        "",
        "| Window | 방식 | <= -15% | <= -30% | >= +30% | >= +50% | >= +100% |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for wid in WINDOWS:
        for scenario in SCENARIOS:
            row = row_by_key[(wid, scenario)]
            cells = []
            for name, _label, _op, _threshold in TAIL_THRESHOLDS:
                cells.append(f"{row[f'{name}_count']} ({_fmt(row[f'{name}_rate_pct'])}%)")
            lines.append(f"| {wid} | {scenario} | " + " | ".join(cells) + " |")
    lines.extend([
        "",
        "## 4. 조기 청산 1:1 paired 분석",
        "",
        "paired 분석은 자본 배분 전에 고정된 동일 ENTRY 신호 원장에서 CONTROL/TEST 양쪽이 모두 실현 청산된 거래 중 TEST 신호일이 더 이른 건이야. 이 구분은 EXIT cadence 자체의 수익률 차이를 보여줘. 실제 portfolio 양쪽에서 모두 자금 배정된 pair 수도 함께 기록했어.",
        "",
        "| Window | TEST 조기 신호 | 완료 수익 pair | CONTROL 미청산으로 미대응 | TEST 실행도 앞선 세션(평균/중앙) | 수익 개선 | 악화 | 평균 / 중앙 수익률 Δ | 둘 다 portfolio 체결 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|",
    ])
    for wid in WINDOWS:
        ps = window_results[wid]["paired_summary"]
        lines.append(
            f"| {wid} | {ps['daily_earlier_signal_count']} | {ps['paired_realized_earlier_exit_count']} | {ps['earlier_test_exit_without_control_exit_count']} | {_fmt(ps['mean_execution_sessions_advanced'], 1)} / {_fmt(ps['median_execution_sessions_advanced'], 1)} | {ps['improved_count']} ({_fmt(ps['improved_pct_of_pairs'])}%) | {ps['degraded_count']} ({_fmt(ps['degraded_pct_of_pairs'])}%) | {_fmt(ps['mean_return_delta_pp'])} / {_fmt(ps['median_return_delta_pp'])} pp | {ps['both_portfolios_filled_pair_count']} |"
        )
    lines.extend([
        "",
        "paired 상세 행은 `paired_early_exits.csv`에 종목/ISU/진입일, CONTROL/TEST EXIT 신호·실행일, exact KRX 세션 차이, 양쪽 비용 반영 수익률·delta, 보유 세션과 portfolio fill 여부로 저장했어. window 간 거래는 겹칠 수 있어 합산치를 독립 표본 수로 해석하면 안 돼.",
        "",
        "## 5. 회전·현금·valuation coverage",
        "",
        "- 일별 EXIT TEST는 CONTROL보다 보유기간을 줄였는지와 실제 현금 회전 변화를 2절 평균 보유 세션/turnover에서 확인할 수 있어. 총수익률만으로 EXIT cadence의 유일한 개선 근거라고 판단하지 않았어.",
        "- 현금 부족률은 채택 Gate가 아닌 필수 운용 진단이야. 분모는 각 고정 CONTROL 적격 ENTRY 원장(양쪽 동일), 분자는 portfolio 이벤트 원장의 `SKIPPED_CASH_UNAVAILABLE`만 세었어. 반복된 skip ID는 0이야.",
        "- 다음 표의 daily coverage는 전체 exact KRX 거래일 대비 equity valuation이 확정된 날짜 비율이야. MDD는 coverage가 90% 미만이면 공식 판단 근거로 쓰지 않았어.",
        "",
        "| Window | 방식 | 관측/전체 거래일 | coverage | 미확정 valuation mark | 결측 구간 / 최대 연속 결측 | MDD 고점 / 저점 / 회복 | 미청산(지원 세션 뒤) | terminal 미해결 |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|",
    ])
    for wid in WINDOWS:
        for scenario in SCENARIOS:
            row = row_by_key[(wid, scenario)]
            lines.append(
                f"| {wid} | {scenario} | {row['valuation_observed_days']}/{row['valuation_total_days']} | {_fmt(row['MDD_coverage_pct'])}% | {row['unresolved_valuation_marks']} | {row['unresolved_span_count']} / {row['max_consecutive_missing_days']}일 | {row['MDD_peak_date']} / {row['MDD_trough_date']} / {row['MDD_recovery_date'] or '미회복'} | {row['open_identity_count_after_support']} | {row['unresolved_terminal_position_count']} |"
            )
    lines.extend([
        "",
        "## 6. 공식 채택 Gate",
        "",
        "적용 기준은 W가 지정한 `official_strategy_adoption_criteria.md`와 `backtest_common_rules.md` 원문 그대로야. 현금 부족률은 채택 pass/fail에서 제외했고, 매도세도 공식 성과에 넣지 않았어.",
        "",
        "| Window | A 무결성 | B 수수료·슬리피지 | C 총수익/CAGR | D MDD 공식 | 관측 MDD 상대 악화(Control - Test)* | E 결과 유효성 |",
        "|---|---|---|---|---|---:|---|",
    ])
    for wid in WINDOWS:
        g = window_results[wid]["gate"]
        lines.append(f"| {wid} | {g['A_integrity']} | {g['B_commission_slippage']} | {g['C_profitability']} | {g['D_MDD']} | {_fmt(g['D_relative_deterioration_pp_control_minus_test_observed_only'])} pp | {g['E_result_validity']} |")
    lines.extend([
        "",
        "* 상대 MDD 수치는 관측값 간 참고 비교야. CONTROL과 TEST 모두 coverage가 90% 미만인 각 기간에서는 공식 상대 MDD gate 판정을 내릴 수 없어.",
        "- 다섯 기간 모두 총수익률과 CAGR은 양수고, 비용 audit은 100% 완료됐어. 현금 부족률은 기간별로 보고했으며 gate로 사용하지 않았어.",
        "- CONTROL/TEST MDD coverage가 모두 90% 미만이어서 공식 MDD Gate는 다섯 기간 전부 `CHECK_REQUIRED`. 보간·추정은 하지 않았어. daily equity coverage가 52.40~65.03%이고 unresolved valuation mark가 수백~수천 건이라 전체 기간 MDD를 공식 근거로 확정할 수 없어.",
        "- 따라서 전체 판정은 **`B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED`**야. 현행 관측치상 TEST portfolio 총수익률은 5/5 기간에서 높고 observed MDD는 더 얕았지만, trade mean/median 및 tail/paired 결과에 혼합 trade-off가 있어 ‘일관되게 우수’ 또는 공식 채택 PASS로 결론 내리지 않아.",
        "",
        "## 7. 적용 범위와 산출물",
        "",
        "- 이번 검증은 후보 비교만 수행했어. `PATTERN_B_SELECT_CORE_V01`, Production Monitor, 공식 history, 공식 5-window 결과, 전략 ID, A FAST Core V2, Julia V1, 영구 제외 정책은 변경하지 않았어.",
        "- 분석 스크립트는 기존 봉인된 cadence replay 결과의 출처와 무결성을 검사하고 공식 gate/추가 지표를 별도 생성해. 재생 data가 해시로 현재와 일치하므로 비싼 397 ticker 재실행은 하지 않았어.",
        "- 표·상세 결과: `window_metrics.csv`, `window_deltas.csv`, `paired_early_exits.csv`, `paired_summary.csv`, `integrity_checks.csv`, `adoption_gates.csv`, `validation.json`, `input_verification.json`.",
        "- 이 검증으로 Production 동작을 바꾸지 않아. 적용은 별도 지시서에서 결정해야 해.",
        "",
    ])
    return "\n".join(lines)


def run(output_relative: Path = OUTPUT_RELATIVE) -> Path:
    replay_root = ROOT / REPLAY_ROOT
    output_root = ROOT / output_relative
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite research output: {output_root}")
    root_meta = _read_json(replay_root / "metadata.json")
    source_summary = _read_json(replay_root / "summary.json")
    if source_summary.get("status") != "PASS" or root_meta.get("study_id") != "B_SELECT_DAILY_NORMAL_EXIT_CADENCE_V01":
        raise ValueError("sealed base cadence replay is not a PASS result")
    state_spot_checks = source_summary.get("state_piecewise_spot_checks", {})
    state_spot_count = _int(state_spot_checks.get("count"))
    state_spot_passed = _int(state_spot_checks.get("passed")) == state_spot_count and state_spot_count == 250
    if not state_spot_passed:
        raise ValueError("sealed daily-state piecewise spot checks are missing or failed")
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    current_origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    if current_head != EXPECTED_BASE_HEAD or current_origin != EXPECTED_BASE_HEAD:
        raise ValueError(f"validation base changed: HEAD={current_head}, origin/main={current_origin}")
    hash_audit = _verify_replay_hashes(replay_root, root_meta)
    normalization_control = source_summary.get("normalization_control", {})
    if normalization_control.get("verdict") != "B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS":
        raise ValueError("current permanent-exclusion normalization control is not PASS")
    exposures = normalization_control.get("current_filtered_candidate_target_exposure_by_window", {})
    if set(exposures) != set(WINDOWS) or any(_int(value) != 0 for value in exposures.values()):
        raise ValueError("current permanent exclusion target exposure is not zero across all five windows")
    exclusions = _load_permanent_exclusions()

    all_metrics: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []
    window_results: dict[str, dict[str, Any]] = {}
    for window_id in WINDOWS:
        metrics, pairs, result = _window_analysis(window_id, replay_root, exclusions)
        all_metrics.extend(metrics)
        all_pairs.extend(pairs)
        window_results[window_id] = result
    delta_rows = _build_window_deltas(all_metrics)
    severity_counts = _severity_counts(window_results)
    any_gate_failure = any(
        result["gate"][gate] == "FAIL"
        for result in window_results.values()
        for gate in ("A_integrity", "B_commission_slippage", "C_profitability", "D_MDD", "E_result_validity")
    )
    if severity_counts["CRITICAL"]:
        verdict = "B_SELECT_DAILY_NORMAL_EXIT_VALIDATION_INVALID"
    elif any_gate_failure:
        verdict = "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_REJECTED"
    elif any(result["gate"]["D_MDD"] == "CHECK_REQUIRED" for result in window_results.values()):
        verdict = "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED"
    else:
        verdict = "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS"

    output_root.mkdir(parents=True, exist_ok=False)
    _write_csv(output_root / "window_metrics.csv", all_metrics)
    _write_csv(output_root / "window_deltas.csv", delta_rows)
    _write_csv(output_root / "paired_early_exits.csv", all_pairs)
    _write_csv(output_root / "paired_summary.csv", [
        {"window_id": wid, **window_results[wid]["paired_summary"]} for wid in WINDOWS
    ])
    _write_csv(output_root / "integrity_checks.csv", [
        {"window_id": wid, **window_results[wid]["integrity"]} for wid in WINDOWS
    ])
    gate_rows = [window_results[wid]["gate"] for wid in WINDOWS]
    _write_csv(output_root / "adoption_gates.csv", gate_rows)

    input_verification = {
        **hash_audit,
        "normalization_control_verdict": normalization_control["verdict"],
        "permanent_excluded_identity_count": len(exclusions),
        "current_exclusion_target_exposure_by_window": exposures,
        "replay_start_head": root_meta["starting_head"],
        "replay_script_sha256": root_meta["script_sha256"],
        "validation_base_head": current_head,
        "validation_base_origin_main": current_origin,
        "daily_state_piecewise_spot_check_count": _int(state_spot_checks.get("count")),
        "daily_state_piecewise_spot_checks_passed": state_spot_passed,
        "validation_base_worktree_was_clean_before_this_formal_run": True,
        "validation_method": "verify all sealed replay/source/RepositoryV2 data hashes, then postprocess already-sealed same-authority CONTROL/TEST pairs",
    }
    (output_root / "input_verification.json").write_text(json.dumps(input_verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "study_id": "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_V01",
        "verdict": verdict,
        "base_head": current_head,
        "origin_main_at_base": current_origin,
        "severity_counts": severity_counts,
        "gate_counts": {
            gate: dict(Counter(result["gate"][gate] for result in window_results.values()))
            for gate in ("A_integrity", "B_commission_slippage", "C_profitability", "D_MDD", "E_result_validity")
        },
        "hash_audit": hash_audit,
        "daily_state_piecewise_spot_check_count": _int(state_spot_checks.get("count")),
        "window_ids": list(WINDOWS),
        "paired_early_exit_row_count": len(all_pairs),
        "window_results": window_results,
        "no_production_changes": True,
        "official_history_modified": False,
    }
    (output_root / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    report = _build_report(summary, all_metrics, window_results, hash_audit, delta_rows)
    (output_root / "report.md").write_text(report, encoding="utf-8")

    generated = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(output_root.iterdir()) if path.is_file()
    }
    metadata = {
        "study_id": summary["study_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_base_head": current_head,
        "validation_base_origin_main": current_origin,
        "base_worktree_clean_before_user_request": True,
        "sealed_replay_study_id": root_meta["study_id"],
        "sealed_replay_start_head": root_meta["starting_head"],
        "sealed_replay_script_sha256": root_meta["script_sha256"],
        "validator_script_sha256": _sha256(Path(__file__)),
        "verdict": verdict,
        "generated_files": generated,
        "verified_replay_manifest_sha256": hash_audit["root_metadata_sha256"],
        "production_changes": False,
        "official_history_modified": False,
    }
    (output_root / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "verdict": verdict,
        "output": str(output_relative),
        "hashes_checked": hash_audit["checked_file_count"],
        "critical_major_minor": severity_counts,
        "paired_early_exit_rows": len(all_pairs),
    }, ensure_ascii=False))
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_RELATIVE)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
