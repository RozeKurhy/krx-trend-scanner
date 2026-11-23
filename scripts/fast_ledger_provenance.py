"""Seal and validate FAST incremental reports against an earlier canonical corpus."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.reporting.a_fast_canonical_ledger import (
    CANONICAL_LEDGER_INCREMENTAL_V01,
    PUBLISHED_FAST_LEDGER_MODES,
    valid_published_fast_scope,
)
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import PROMOTED_STRATEGY_ID

INCREMENTAL_MANIFEST = "fast_ledger_continuity.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def load_common_reports(directory: Path) -> dict[str, tuple[Path, dict]]:
    result = {}
    for path in sorted((directory / "json").glob("*.json")):
        report = read_json(path)
        if report.get("asset_type") != "COMMON":
            continue
        ticker = report["ticker"]
        if ticker in result:
            raise ValueError(f"FAST_LEDGER_DUPLICATE_COMMON_REPORT:{ticker}")
        result[ticker] = (path, report)
    return result


@dataclass(frozen=True)
class PriorCanonicalLedger:
    proof: dict[str, Any]
    reports: dict[str, tuple[Path, dict]]

    @property
    def retained_tickers(self) -> set[str]:
        return {
            ticker for ticker, (_, report) in self.reports.items()
            if report["a_fast_core"]["trade_history"] or report["a_fast_core"]["action"] == "ENTER_NEXT_OPEN"
        }


def _sealed_prior(root: Path, requested: str, market: str, expected_digest: str) -> PriorCanonicalLedger:
    from scripts.run_daily_update_phase4b_v01 import validate_full_history_alignment_corpus

    directory = root / "artifacts/reporting/stock_reports" / requested.replace("-", "")
    reports = load_common_reports(directory)
    if (directory / INCREMENTAL_MANIFEST).exists():
        validation = validate_incremental_alignment_corpus(directory, requested, market, root=root)
    else:
        validation = validate_full_history_alignment_corpus(directory, requested, market)
    if not validation.get("valid") or validation.get("strategy_replay_digest") != expected_digest:
        raise ValueError("FAST_LEDGER_PREVIOUS_CANONICAL_PROVENANCE_MISMATCH")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path, _ in reports.values()}
    return PriorCanonicalLedger({
        "requested_as_of": requested, "reference_market_date": market,
        "strategy_replay_mode": validation["strategy_replay_mode"],
        "strategy_replay_digest": expected_digest, "report_files_sha256": digest(hashes),
        "report_count": len(hashes),
    }, reports)


def load_published_prior(root: Path, next_request: str, next_market: str) -> PriorCanonicalLedger:
    health = read_json(root / "web/data/health.json")
    monitor = read_json(root / "web/data/strategy-monitor.json")
    request, market = health["requested_as_of"], health["reference_market_date"]
    rows = [r for r in monitor["strategies"] if r.get("id") == PROMOTED_STRATEGY_ID]
    if (
        health["overall_status"] != "NORMAL" or not request < next_request or not market < next_market
        or monitor["requested_as_of"] != request or monitor["reference_market_date"] != market
        or len(rows) != 1 or monitor.get("strategy_replay_mode") not in PUBLISHED_FAST_LEDGER_MODES
        or any(rows[0].get(field) != monitor.get(field) for field in (
            "strategy_replay_mode", "strategy_replay_scope", "strategy_replay_digest",
        ))
    ):
        raise ValueError("FAST_LEDGER_PUBLISHED_PRIOR_INVALID")
    prior = _sealed_prior(root, request, market, monitor["strategy_replay_digest"])
    prior_core = next(iter(prior.reports.values()))[1]["a_fast_core"]
    if (
        prior.proof["strategy_replay_mode"] != monitor["strategy_replay_mode"]
        or prior_core["strategy_replay_scope"] != monitor["strategy_replay_scope"]
    ):
        raise ValueError("FAST_LEDGER_PUBLISHED_PRIOR_SCOPE_MISMATCH")
    return prior


ENTRY_FIELDS = (
    "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date", "entry_open",
    "entry_pattern_a_stage", "previous_exit_type", "strategy_id", "entry_strategy_id", "exit_strategy_id",
)


def trade_events(
    prior: PriorCanonicalLedger, current: dict[str, tuple[Path, dict]], sessions: list[str],
) -> list[dict[str, Any]]:
    if not prior.retained_tickers.issubset(current):
        raise ValueError("FAST_LEDGER_PRIOR_TICKER_LOST")
    events = []
    preserved_days = set(sessions)
    prior_ref = prior.proof["reference_market_date"]
    for ticker, (_, report) in sorted(current.items()):
        core = report["a_fast_core"]
        old_report = prior.reports.get(ticker)
        old = old_report[1]["a_fast_core"] if old_report else {}
        history, earlier = core["trade_history"], old.get("trade_history", [])
        if len(history) < len(earlier):
            raise ValueError(f"FAST_LEDGER_PRIOR_TRADE_LOST:{ticker}")
        pending_entry = old.get("action") == "ENTER_NEXT_OPEN"
        id_seen: set[str] = set()
        prev_end = None
        for i, row in enumerate(history):
            key, status = row["trade_id"], row["trade_status"]
            if (
                key != f"{ticker}_{i+1:02d}" or key in id_seen or row["trade_sequence"] != i+1
                or status not in {"REALIZED", "OPEN_AT_CUTOFF"}
                or status == "OPEN_AT_CUTOFF" and i != len(history)-1
                or prev_end is not None and (row["entry_signal_date"] < prev_end or row["entry_execution_date"] <= prev_end)
                or any(row[field] != PROMOTED_STRATEGY_ID for field in ("strategy_id","entry_strategy_id","exit_strategy_id"))
            ):
                raise ValueError(f"FAST_LEDGER_TRADE_ORDER_OR_LINEAGE_INVALID:{ticker}:{key}")
            id_seen.add(key)
            prev_end = row.get("exit_execution_date")
            if i < len(earlier):
                old_row = earlier[i]
                if old_row["trade_status"] == "REALIZED":
                    if row != old_row:
                        raise ValueError(f"FAST_LEDGER_PRIOR_REALIZED_CHANGED:{ticker}:{key}")
                    continue
                if any(row.get(field) != old_row.get(field) for field in ENTRY_FIELDS):
                    raise ValueError(f"FAST_LEDGER_PRIOR_OPEN_ENTRY_CHANGED:{ticker}:{key}")
                if old_row.get("exit_signal_date") and (
                    row.get("exit_signal_date") != old_row["exit_signal_date"] or row.get("exit_type") != old_row["exit_type"]
                ):
                    raise ValueError(f"FAST_LEDGER_PRIOR_EXIT_PENDING_CHANGED:{ticker}:{key}")
            else:
                day, signal = row["entry_execution_date"], row["entry_signal_date"]
                if pending_entry:
                    expected = old["entry_conditions"]["alignment_mcap_500b_details"]["signal_date"]
                    if signal != expected or signal != prior_ref:
                        raise ValueError(f"FAST_LEDGER_PRIOR_ENTRY_PENDING_CHANGED:{ticker}")
                    pending_entry = False
                elif signal not in preserved_days:
                    raise ValueError(f"FAST_LEDGER_NEW_ENTRY_SIGNAL_OUTSIDE_WINDOW:{ticker}")
                if day not in preserved_days or signal >= day or not math.isfinite(row["entry_open"]) or row["entry_open"] <= 0:
                    raise ValueError(f"FAST_LEDGER_NEW_ENTRY_EXECUTION_INVALID:{ticker}:{key}")
                events.append({"ticker": ticker, "trade_id": key, "kind": "ENTRY", "signal_date": signal,
                               "execution_date": day, "price": row["entry_open"]})
            if status == "REALIZED":
                day, signal = row["exit_execution_date"], row["exit_signal_date"]
                if (
                    day not in preserved_days or not signal or day <= row["entry_execution_date"]
                    or not math.isfinite(row["exit_price"]) or row["exit_price"] <= 0
                ):
                    raise ValueError(f"FAST_LEDGER_NEW_EXIT_EXECUTION_INVALID:{ticker}:{key}")
                events.append({"ticker": ticker, "trade_id": key, "kind": "EXIT", "signal_date": signal,
                               "execution_date": day, "price": row["exit_price"], "reason": row["exit_type"]})
            elif row.get("exit_signal_date") and not (i < len(earlier) and earlier[i].get("exit_signal_date")):
                events.append({"ticker": ticker, "trade_id": key, "kind": "EXIT_PENDING",
                               "signal_date": row["exit_signal_date"], "reason": row["exit_type"]})
        if pending_entry:
            raise ValueError(f"FAST_LEDGER_PRIOR_ENTRY_PENDING_LOST:{ticker}")
        position = core.get("current_trade")
        if core["canonical_position"] == "OPEN":
            if not history or not position or position["trade_id"] != history[-1]["trade_id"] or history[-1]["trade_status"] != "OPEN_AT_CUTOFF":
                raise ValueError(f"FAST_LEDGER_OPEN_PROJECTION_MISMATCH:{ticker}")
            if old.get("current_trade") and position["trade_id"] == old["current_trade"]["trade_id"]:
                original, held = old["protection_state"], core["protection_state"]
                hwm, carried = original["progressed_hwm_score"], held["progressed_hwm_score"]
                if (hwm is not None and (carried is None or carried < hwm)) or any(
                    original[field] is not None and original[field] != held[field]
                    for field in ("first_progressed_date", "first_progressed_effective_trading_date")
                ) or any(original[field] == "ARMED" and held[field] != "ARMED" for field in ("exit3_state", "exit4_state")):
                    raise ValueError(f"FAST_LEDGER_PROTECTION_REGRESSION:{ticker}")
        elif position or (history and history[-1]["trade_status"] == "OPEN_AT_CUTOFF"):
            raise ValueError(f"FAST_LEDGER_OPEN_PROJECTION_MISMATCH:{ticker}")
        if core["action"] == "ENTER_NEXT_OPEN":
            signal = core["entry_conditions"]["alignment_mcap_500b_details"]["signal_date"]
            if signal not in preserved_days:
                raise ValueError(f"FAST_LEDGER_PENDING_ENTRY_OUTSIDE_WINDOW:{ticker}")
            events.append({"ticker": ticker, "trade_id": f"{ticker}_{len(history)+1:02d}",
                           "kind": "ENTRY_PENDING", "signal_date": signal})
    return events


def _material(
    directory: Path, requested: str, market: str, prior: PriorCanonicalLedger, root: Path,
) -> tuple[dict, str, list, dict[str, tuple[Path, dict]]]:
    from scripts.run_daily_update_phase4b_v01 import _canonical_replay_core

    reports = load_common_reports(directory)
    if not reports or not prior.proof["reference_market_date"] < market <= requested:
        raise ValueError("FAST_LEDGER_SCOPE_INVALID")
    calendar = load_rolling_production_market_calendar(root)
    if calendar is None or not calendar.is_trading_day(market):
        raise ValueError("FAST_LEDGER_CALENDAR_INVALID")
    sessions = [str(day)[:10] for day in calendar.trading_dates if prior.proof["reference_market_date"] < str(day)[:10] <= market]
    for _, report in reports.values():
        core = report["a_fast_core"]
        if (
            report["requested_as_of"] != requested or report["reference_market_date"] != market
            or core["strategy_replay_mode"] != CANONICAL_LEDGER_INCREMENTAL_V01 or core["strategy_id"] != PROMOTED_STRATEGY_ID
            or core.get("activation_intervals") or core.get("effective_signal_date") is not None or core.get("promotion_gate_status") is not None
        ):
            raise ValueError("FAST_LEDGER_REPORT_MODE_OR_DATE_INVALID")
    events = trade_events(prior, reports, sessions)
    scope = {
        "type": "PUBLISHED_COMMON_REPORTS", "report_count": len(reports),
        "requested_as_of": requested, "reference_market_date": market, "output_strategy_id": PROMOTED_STRATEGY_ID,
        "prior_canonical": prior.proof, "new_sessions": sessions, "event_count": len(events), "events_sha256": digest(events),
    }
    core_hash = digest({"scope": scope, "reports": {
        ticker: _canonical_replay_core(report["a_fast_core"]) for ticker, (_, report) in reports.items()
    }})
    return scope, core_hash, events, reports


def finalize_incremental_alignment_reports(directory: Path, requested: str, market: str, prior: PriorCanonicalLedger, root: Path) -> dict:
    scope, ledger_hash, events, reports = _material(directory, requested, market, prior, root)
    (directory / INCREMENTAL_MANIFEST).write_text(
        json.dumps({"scope": scope, "digest": ledger_hash, "events": events}, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    for path, report in reports.values():
        report["a_fast_core"].update(strategy_replay_scope=scope, strategy_replay_digest=ledger_hash)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return validate_incremental_alignment_corpus(directory, requested, market, root=root, expected_common_tickers=set(reports))


def validate_incremental_alignment_corpus(
    directory: Path, requested: str, market: str, *, root: Path, expected_common_tickers: set[str] | None = None,
) -> dict:
    try:
        manifest = read_json(directory / INCREMENTAL_MANIFEST)
        scope = manifest["scope"]
        if (
            not valid_published_fast_scope(CANONICAL_LEDGER_INCREMENTAL_V01, scope)
            or scope["requested_as_of"] != requested or scope["reference_market_date"] != market
        ):
            raise ValueError("FAST_LEDGER_SCOPE_DATES_INVALID")
        source = scope["prior_canonical"]
        prior = _sealed_prior(root, source["requested_as_of"], source["reference_market_date"], source["strategy_replay_digest"])
        scope, ledger_hash, events, reports = _material(directory, requested, market, prior, root)
        if (expected_common_tickers is not None and set(reports) != expected_common_tickers
                or manifest != {"scope": scope, "digest": ledger_hash, "events": events}
                or any((report["a_fast_core"].get("strategy_replay_scope"), report["a_fast_core"].get("strategy_replay_digest"))
                     != (scope, ledger_hash) for _, report in reports.values())):
            raise ValueError("FAST_LEDGER_REPORT_OR_MANIFEST_DIGEST_MISMATCH")
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"valid": False, "reason_codes": [str(exc)]}
    return {
        "valid": True, "reason_codes": [], "common_report_count": len(reports),
        "strategy_id": PROMOTED_STRATEGY_ID, "strategy_replay_mode": CANONICAL_LEDGER_INCREMENTAL_V01,
        "strategy_replay_digest": ledger_hash, "computed_strategy_replay_digest": ledger_hash, "strategy_replay_scope": scope,
        "trade_count": sum(len(r["a_fast_core"]["trade_history"]) for _, r in reports.values()),
        "current_open_position_count": sum(r["a_fast_core"]["canonical_position"] == "OPEN" for _, r in reports.values()),
    }
