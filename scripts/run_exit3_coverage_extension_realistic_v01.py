#!/usr/bin/env python3
"""Realistic T15 portfolio replay for a holding-lifecycle C1 Exit3 extension."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import scripts.analyze_fastcore_v2_a_vs_c1_divergence_v01 as avc
import scripts.analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01 as lc
import scripts.run_exit4_t10_realistic_portfolio_v02 as prior
import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2

WORK_ID = "PATTERN_A_FAST_CORE_V2_EXIT3_COVERAGE_EXTENSION_REALISTIC_V01"
RUN_ID = "run_20260927_exit3_coverage_extension_realistic_v01"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/exit3_coverage_extension_realistic_v01"
RUN_DIR = OUTPUT_DIR / RUN_ID
SOURCE_STRATEGY_ID = prior.T15_STRATEGY_ID
TEST_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_EXIT3_COVERAGE_EXTENSION_RESEARCH_V01"
WINDOW_IDS = ("P2-1", "P2-2", "P3-2")
EXPECTED_C1_COUNTS = {"P2-1": 42, "P2-2": 43, "P3-2": 37}
EXPECTED_DEPARTURE_COUNTS = {"P2-1": 19, "P2-2": 11, "P3-2": 8}
INITIAL_CAPITAL = 200_000_000.0
RETREAT_STAGES = {"EARLY_TREND", "TRANSITION", "BASE", "WEAK"}
EXIT_OUTCOME_FIELDS = {
    "strategy_id", "exit_type", "exit_signal_date", "exit_execution_date", "exit_price",
    "terminal_return", "mfe", "mae", "peak_giveback", "profit_capture", "holding_weeks",
    "holding_days", "trade_status", "terminal_valuation_date", "terminal_valuation_price",
    "terminal_valuation_source", "terminal_valuation_at_cutoff",
}
ENTRY_PARITY_FIELDS = (
    "ticker", "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date",
    "entry_pattern_a_stage", "market", "isu_cd", "identity_effective_from", "identity_effective_to",
)
ENTRY_NUMERIC_FIELDS = ("entry_open", "entry_market_cap")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def _date(value: Any) -> pd.Timestamp | None:
    value = _clean(value)
    return None if value is None or value == "" else pd.Timestamp(value).normalize()


def _date_text(value: Any) -> str | None:
    parsed = _date(value)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else None


def _round(value: Any, digits: int = 6) -> float | None:
    value = _clean(value)
    if value is None:
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _quantiles(values: Sequence[Any]) -> dict[str, Any]:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {
        "n": int(len(series)), "mean": _round(series.mean()), "median": _round(series.median()),
        "p25": _round(series.quantile(0.25)), "p75": _round(series.quantile(0.75)),
    }


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("ticker", "")).zfill(6), str(row.get("trade_id", "")), str(row.get("entry_signal_date", ""))[:10])


def _compare_entry_parity(control: pd.DataFrame, test: pd.DataFrame) -> dict[str, Any]:
    if len(control) != len(test):
        raise RuntimeError("ENTRY_PARITY_ROW_COUNT_MISMATCH")
    left, right = control.copy(), test.copy()
    left["_key"] = left.apply(_key, axis=1)
    right["_key"] = right.apply(_key, axis=1)
    if left["_key"].duplicated().any() or right["_key"].duplicated().any() or set(left["_key"]) != set(right["_key"]):
        raise RuntimeError("ENTRY_PARITY_IDENTITY_SET_MISMATCH")
    joined = left.merge(right, on="_key", suffixes=("_control", "_test"), validate="one_to_one")
    for field in ENTRY_PARITY_FIELDS:
        a = joined[f"{field}_control"].fillna("<NA>").astype(str)
        b = joined[f"{field}_test"].fillna("<NA>").astype(str)
        if not a.equals(b):
            raise RuntimeError(f"ENTRY_PARITY_FIELD_MISMATCH:{field}")
    for field in ENTRY_NUMERIC_FIELDS:
        a = pd.to_numeric(joined[f"{field}_control"], errors="coerce")
        b = pd.to_numeric(joined[f"{field}_test"], errors="coerce")
        if not np.allclose(a, b, rtol=0, atol=1e-9, equal_nan=True):
            raise RuntimeError(f"ENTRY_PARITY_NUMERIC_MISMATCH:{field}")
    return {"status": "PASS", "entry_rows": int(len(joined)), "entry_identity_exact": True}


def _compare_exit_only_parity(control: pd.DataFrame, test: pd.DataFrame, changed_ids: set[str]) -> dict[str, Any]:
    if len(control) != len(test) or control["pair_id"].duplicated().any() or test["pair_id"].duplicated().any():
        raise RuntimeError("EXIT_ONLY_PARITY_ROW_OR_KEY_MISMATCH")
    left = control.set_index("pair_id", drop=False)
    right = test.set_index("pair_id", drop=False)
    if set(left.index.astype(str)) != set(right.index.astype(str)):
        raise RuntimeError("EXIT_ONLY_PARITY_ENTRY_IDENTITY_SET_MISMATCH")
    changed: set[str] = set()
    fields = [c for c in control.columns if c not in EXIT_OUTCOME_FIELDS]
    for pair_id in left.index.astype(str):
        a, b = left.loc[pair_id], right.loc[pair_id]
        for field in fields:
            if str(_clean(a[field])) != str(_clean(b[field])):
                raise RuntimeError(f"NON_EXIT_FIELD_CHANGED:{field}:{pair_id}")
        if any(str(_clean(a[f])) != str(_clean(b[f])) for f in EXIT_OUTCOME_FIELDS if f != "strategy_id"):
            changed.add(pair_id)
    if changed != changed_ids:
        raise RuntimeError(f"EXIT_ONLY_CHANGED_ROWS_MISMATCH:{len(changed)}:{len(changed_ids)}")
    if not test["strategy_id"].astype(str).eq(TEST_STRATEGY_ID).all():
        raise RuntimeError("TEST_STRATEGY_ID_MISMATCH")
    return {
        "status": "PASS", "non_exit_fields_unchanged": True,
        "changed_rows_equal_applied_exit3_rows": True, "changed_trade_rows": len(changed),
    }


def _context(window_id: str) -> tuple[Any, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    run = strategy._load_context(window_id)
    start = pd.Timestamp(run.window.effective_start).normalize()
    end = pd.Timestamp(run.window.effective_end).normalize()
    support = pd.Timestamp(run.window.execution_support).normalize()
    spec = prior.WINDOWS[window_id]
    actual = tuple(x.strftime("%Y-%m-%d") for x in (start, end, support))
    expected = (spec["start"], spec["end"], spec["support"])
    if actual != expected:
        raise RuntimeError(f"WINDOW_CONTRACT_MISMATCH:{window_id}:{actual}:{expected}")
    return run, start, end, support


def extension_decision(
    holding_subgroup: str,
    departure: pd.Timestamp | None,
    departure_stage: str | None,
    existing_exit_signal: pd.Timestamp | None,
) -> str:
    """Return the frozen first-event decision for a coverage/C1 stage departure."""
    if holding_subgroup != lc.HOLDING_C1 or departure is None:
        return "NO_HELD_PROGRESSED_DEPARTURE"
    if departure_stage not in RETREAT_STAGES:
        raise RuntimeError(f"UNSUPPORTED_EXIT3_DEPARTURE_STAGE:{departure_stage}")
    if existing_exit_signal is not None and existing_exit_signal.normalize() <= departure.normalize():
        return "KEEP_CONTROL_EXIT_ON_OR_BEFORE_DEPARTURE_V2_PRIORITY"
    return "APPLY_EXIT3_COVERAGE_EXTENSION"


def next_session_open(
    daily: pd.DataFrame, observed: pd.Timestamp, support: pd.Timestamp
) -> tuple[pd.Timestamp | None, float | None]:
    later = daily.loc[(daily.index > observed) & (daily.index <= support)].sort_index()
    if later.empty:
        return None, None
    return pd.Timestamp(later.index[0]).normalize(), float(later.iloc[0]["open"])


def _held_c1_events(
    window_id: str,
    panel: pd.DataFrame,
    stage_cache: Mapping[tuple[str, str, str], pd.DataFrame],
    end: pd.Timestamp,
    support: pd.Timestamp,
    frames: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    c1 = panel.loc[panel["holding_subgroup"].eq(lc.HOLDING_C1)].copy()
    if len(c1) != EXPECTED_C1_COUNTS[window_id]:
        raise RuntimeError(f"C1_HOLDING_COUNT_MISMATCH:{window_id}:{len(c1)}")
    rows = []
    for source in c1.to_dict(orient="records"):
        key = (str(source["ticker"]).zfill(6), str(source["isu_cd"]), str(source["identity_effective_from"]))
        cache = stage_cache.get(key)
        if cache is None:
            raise RuntimeError(f"C1_STAGE_CACHE_MISSING:{window_id}:{key[0]}")
        holding_end = lc.holding_end(pd.Series(source), end)
        signal = pd.Timestamp(source["entry_signal_date"]).normalize()
        held = avc.held_labels(cache, signal, end, holding_end)
        holding = lc.classify_holding(str(source["entry_pattern_a_stage"]).upper(), list(zip(held["label"], held["stage"])))
        if holding["subgroup"] != lc.HOLDING_C1:
            raise RuntimeError(f"C1_HOLDING_REBUILD_MISMATCH:{window_id}:{source['trade_id']}")
        event = avc.stage_events(str(source["entry_pattern_a_stage"]).upper(), held)
        if event.get("anchor_index") is None:
            raise RuntimeError(f"C1_PROGRESS_ANCHOR_MISSING:{window_id}:{source['trade_id']}")
        anchor_label = _date_text(event.get("anchor_label"))
        anchor_effective = _date_text(event.get("anchor_effective"))
        if anchor_label != _date_text(source.get("first_progressed_date")):
            raise RuntimeError(f"C1_PROGRESS_ANCHOR_LABEL_MISMATCH:{window_id}:{source['trade_id']}")
        ledger_effective = _date_text(source.get("first_progressed_effective_trading_date"))
        if ledger_effective and ledger_effective != anchor_effective:
            raise RuntimeError(f"C1_PROGRESS_ANCHOR_EFFECTIVE_MISMATCH:{window_id}:{source['trade_id']}")
        max_used = _date_text(held["effective"].max()) if not held.empty else None
        if max_used and pd.Timestamp(max_used) > holding_end:
            raise RuntimeError(f"POST_HOLDING_STAGE_USED:{window_id}:{source['trade_id']}")
        departure = _date(event.get("first_departure_effective"))
        stage = _clean(event.get("first_departure_stage"))
        execution_date, execution_open = None, None
        if departure is None:
            decision = "NO_HELD_PROGRESSED_DEPARTURE"
        else:
            if departure <= pd.Timestamp(event["anchor_effective"]).normalize():
                raise RuntimeError(f"C1_DEPARTURE_NOT_AFTER_ANCHOR:{window_id}:{source['trade_id']}")
            exit_signal = _date(source.get("exit_signal_date"))
            loss_guard_signal = _date(source.get("loss_guard_signal_date"))
            prior_signals = [x for x in (exit_signal, loss_guard_signal) if x is not None]
            prior_signal = min(prior_signals) if prior_signals else None
            decision = extension_decision(holding["subgroup"], departure, stage, prior_signal)
            if decision != "APPLY_EXIT3_COVERAGE_EXTENSION":
                execution_date, execution_open = None, None
            else:
                daily = frames.get(prior._segment_key(source))
                if daily is None or daily.empty:
                    raise RuntimeError(f"C1_EXECUTION_FRAME_MISSING:{window_id}:{source['trade_id']}")
                execution_date, execution_open = next_session_open(daily, departure, support)
                if execution_date is None or execution_open is None:
                    raise RuntimeError(f"C1_EXIT3_EXECUTION_SESSION_MISSING:{window_id}:{source['trade_id']}")
        rows.append({
            "window": window_id,
            "pair_id": str(source["pair_id"]),
            "ticker": str(source["ticker"]).zfill(6),
            "trade_id": str(source["trade_id"]),
            "entry_signal_date": _date_text(source["entry_signal_date"]),
            "holding_subgroup": holding["subgroup"],
            "window_lifecycle_class_ignored": source.get("lifecycle_class"),
            "first_progressed_label": anchor_label,
            "first_progressed_effective_date": anchor_effective,
            "first_departure_label": _date_text(event.get("first_departure_label")),
            "first_departure_effective_date": _date_text(departure),
            "first_departure_stage": stage,
            "departure_signal_return_pct": _round(event.get("return_at_first_departure"), 4),
            "control_exit_type": str(source.get("exit_type", "")),
            "control_exit_signal_date": _date_text(source.get("exit_signal_date")),
            "control_exit_execution_date": _date_text(source.get("exit_execution_date")),
            "control_terminal_return_pct": _round(source.get("terminal_return"), 4),
            "control_trade_status": str(source.get("trade_status", "")),
            "holding_end_date": holding_end.strftime("%Y-%m-%d"),
            "max_stage_effective_date_used": max_used,
            "execution_date": execution_date.strftime("%Y-%m-%d") if execution_date is not None else None,
            "execution_open": _round(execution_open, 2),
            "decision": decision,
        })
    events = pd.DataFrame(rows)
    applied = events.loc[events["decision"].eq("APPLY_EXIT3_COVERAGE_EXTENSION")].copy()
    departures = int(events["first_departure_effective_date"].notna().sum())
    expected = EXPECTED_DEPARTURE_COUNTS[window_id]
    if departures != expected or len(applied) != expected:
        raise RuntimeError(f"C1_DEPARTURE_COUNT_MISMATCH:{window_id}:{departures}:{len(applied)}")
    if events["decision"].str.startswith("KEEP_CONTROL_EXIT").any():
        raise RuntimeError(f"UNEXPECTED_EXIT_PRIORITY_COLLISION:{window_id}")
    return events, applied


def _apply_exit3(
    control: pd.DataFrame,
    events: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    end: pd.Timestamp,
    support: pd.Timestamp,
) -> pd.DataFrame:
    test = control.copy(deep=True)
    test["strategy_id"] = TEST_STRATEGY_ID
    for field in ("terminal_valuation_date", "terminal_valuation_price", "terminal_valuation_source", "terminal_valuation_at_cutoff"):
        if field in test.columns:
            test[field] = test[field].astype(object)
    for event in events.to_dict(orient="records"):
        pair_id = str(event["pair_id"])
        index = test.index[test["pair_id"].astype(str).eq(pair_id)]
        if len(index) != 1:
            raise RuntimeError(f"EXIT3_PAIR_ID_NOT_UNIQUE:{pair_id}")
        i = index[0]
        source = test.loc[i].to_dict()
        daily = frames[prior._segment_key(source)]
        outcome = v2._calc_trade_outcome(
            pd.Timestamp(source["entry_execution_date"]).normalize(),
            float(source["entry_open"]),
            pd.Timestamp(event["first_departure_effective_date"]).normalize(),
            daily,
            end,
            execution_support_date=support,
        )
        if outcome["trade_status"] != "REALIZED" or outcome["exit_exec_d"] is None:
            raise RuntimeError(f"EXIT3_EXECUTION_OUTSIDE_SUPPORT:{pair_id}")
        actual_exec = outcome["exit_exec_d"].normalize()
        if actual_exec.strftime("%Y-%m-%d") != event["execution_date"]:
            raise RuntimeError(f"EXIT3_NEXT_SESSION_MISMATCH:{pair_id}")
        if not math.isclose(float(outcome["exit_open"]), float(event["execution_open"]), rel_tol=0, abs_tol=0.011):
            raise RuntimeError(f"EXIT3_OPEN_PRICE_MISMATCH:{pair_id}")
        holding_days = len(daily.loc[
            (daily.index >= pd.Timestamp(source["entry_execution_date"]).normalize()) & (daily.index <= actual_exec)
        ])
        updates = {
            "exit_type": f"EXIT3_PROGRESSED_TO_{event['first_departure_stage']}",
            "exit_signal_date": str(event["first_departure_effective_date"]),
            "exit_execution_date": actual_exec.strftime("%Y-%m-%d"),
            "exit_price": round(float(outcome["exit_open"]), 2),
            "terminal_return": outcome["terminal_ret"],
            "mfe": outcome["mfe"],
            "mae": outcome["mae"],
            "peak_giveback": outcome["terminal_giveback"],
            "profit_capture": outcome["terminal_profit_capture"],
            "holding_weeks": outcome["holding_weeks"],
            "holding_days": int(holding_days),
            "trade_status": outcome["trade_status"],
            "terminal_valuation_date": None,
            "terminal_valuation_price": None,
            "terminal_valuation_source": None,
            "terminal_valuation_at_cutoff": None,
        }
        for field, value in updates.items():
            test.at[i, field] = value
    return test


def _add_end_position_pnl(
    replay: Mapping[str, Any],
    ledger: pd.DataFrame,
    details: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    trading_dates: Sequence[pd.Timestamp],
    end: pd.Timestamp,
    gap_classes: Mapping[tuple[str, str], str],
    strategy_id: str,
) -> pd.DataFrame:
    ledger_by_pair = ledger.set_index("pair_id", drop=False)
    detail_by_pair = details.set_index("pair_id", drop=False)
    events = pd.DataFrame(replay["events"])
    fills = events.loc[events.event_type.eq("ENTRY") & events.event_status.eq("EXECUTED")]
    if fills.pair_id.astype(str).duplicated().any():
        raise RuntimeError("DUPLICATE_FILLED_ENTRY_PAIR")
    session_positions = {pd.Timestamp(day).normalize(): i for i, day in enumerate(trading_dates)}
    rows = []
    for entry in fills.to_dict(orient="records"):
        pair_id = str(entry["pair_id"])
        detail = detail_by_pair.loc[pair_id]
        if bool(detail["closed"]):
            pnl = float(detail["net_realized_pnl_krw"])
            end_return = float(detail["net_realized_return_pct"])
            mark, mark_date, basis = None, str(detail["exit_execution_date"]), "NET_REALIZED_AFTER_COSTS"
        else:
            source = ledger_by_pair.loc[pair_id]
            mark, _audit = portfolio._valuation_close_with_carry(
                source.to_dict(), frames, end, session_positions, gap_classes,
                strategy_id=strategy_id, pair_id=pair_id,
            )
            if mark is None or not math.isfinite(float(mark)):
                raise RuntimeError(f"OPEN_POSITION_CUTOFF_MARK_MISSING:{pair_id}")
            buy_cost = float(entry["notional"]) + float(entry["commission"])
            pnl = int(entry["shares"]) * float(mark) - buy_cost
            end_return = pnl / buy_cost * 100.0 if buy_cost else None
            mark_date, basis = end.strftime("%Y-%m-%d"), "CUTOFF_MARK_AFTER_BUY_COSTS_NO_SELL_COST"
        rows.append({
            "pair_id": pair_id,
            "portfolio_end_pnl_krw": pnl,
            "portfolio_end_return_pct": end_return,
            "portfolio_end_mark_price": mark,
            "portfolio_end_mark_date": mark_date,
            "portfolio_end_pnl_basis": basis,
        })
    extra = pd.DataFrame(rows)
    return details.merge(extra, on="pair_id", how="left", validate="one_to_one")


def _distribution(values: Sequence[Any]) -> dict[str, Any]:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    result = _quantiles(series.tolist())
    for threshold in (20, 30, 50, 100, 200):
        result[f"ge_pos_{threshold}_count"] = int((series >= threshold).sum())
    for threshold in (15, 30, 40, 50, 60):
        result[f"le_neg_{threshold}_count"] = int((series <= -threshold).sum())
    return result


def _exit_class(value: Any) -> str:
    text = str(value or "").upper()
    if "EXIT4" in text:
        return "Exit4"
    if "EXIT3" in text:
        return "Exit3"
    if "LOSS_GUARD" in text:
        return "Loss Guard"
    if text.startswith("NO_EXIT") or text.startswith("NO_PROGRESSED"):
        return "No Exit / cutoff"
    return "Other"


def _make_tables(
    window_id: str,
    control: pd.DataFrame,
    test: pd.DataFrame,
    control_replay: Mapping[str, Any],
    test_replay: Mapping[str, Any],
    control_details: pd.DataFrame,
    test_details: pd.DataFrame,
    control_entries: pd.DataFrame,
    test_entries: pd.DataFrame,
    c1_events: pd.DataFrame,
    trading_dates: Sequence[pd.Timestamp],
    end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    a = control.set_index("pair_id", drop=False)
    b = test.set_index("pair_id", drop=False)
    da = control_details.set_index("pair_id", drop=False)
    db = test_details.set_index("pair_id", drop=False)
    ea = control_entries.set_index("pair_id", drop=False)
    eb = test_entries.set_index("pair_id", drop=False)
    event_map = {str(row["pair_id"]): row for row in c1_events.to_dict(orient="records")}
    pairs = []
    for pair_id in a.index.astype(str):
        ca, tb = a.loc[pair_id], b.loc[pair_id]
        ca_d, tb_d = (da.loc[pair_id] if pair_id in da.index else None), (db.loc[pair_id] if pair_id in db.index else None)
        ca_e, tb_e = (ea.loc[pair_id] if pair_id in ea.index else None), (eb.loc[pair_id] if pair_id in eb.index else None)
        ev = event_map.get(pair_id)
        control_pnl = float(ca_d["portfolio_end_pnl_krw"]) if ca_d is not None else 0.0
        test_pnl = float(tb_d["portfolio_end_pnl_krw"]) if tb_d is not None else 0.0
        pairs.append({
            "window": window_id,
            "pair_id": pair_id,
            "ticker": str(ca["ticker"]).zfill(6),
            "trade_id": str(ca["trade_id"]),
            "entry_signal_date": _date_text(ca["entry_signal_date"]),
            "entry_execution_date": _date_text(ca["entry_execution_date"]),
            "holding_subgroup": ev["holding_subgroup"] if ev else None,
            "lifecycle_class": ca.get("lifecycle_class"),
            "first_progressed_date": ev["first_progressed_label"] if ev else None,
            "first_progressed_effective_date": ev["first_progressed_effective_date"] if ev else None,
            "first_departure_date": ev["first_departure_effective_date"] if ev else None,
            "first_departure_stage": ev["first_departure_stage"] if ev else None,
            "control_exit_type": ca["exit_type"],
            "test_exit_type": tb["exit_type"],
            "control_exit_signal_date": _date_text(ca.get("exit_signal_date")),
            "test_exit_signal_date": _date_text(tb.get("exit_signal_date")),
            "control_exit_execution_date": _date_text(ca.get("exit_execution_date")),
            "test_exit_execution_date": _date_text(tb.get("exit_execution_date")),
            "control_terminal_return_pct": _round(ca.get("terminal_return"), 4),
            "test_terminal_return_pct": _round(tb.get("terminal_return"), 4),
            "path_return_delta_pp": _round(float(tb["terminal_return"]) - float(ca["terminal_return"]), 4),
            "control_holding_days": _round(ca.get("holding_days"), 2),
            "test_holding_days": _round(tb.get("holding_days"), 2),
            "holding_days_delta": _round(
                pd.to_numeric(pd.Series([tb.get("holding_days")]), errors="coerce").iloc[0]
                - pd.to_numeric(pd.Series([ca.get("holding_days")]), errors="coerce").iloc[0], 2
            ),
            "control_mfe_pct": _round(ca.get("mfe"), 4),
            "test_mfe_pct": _round(tb.get("mfe"), 4),
            "control_mae_pct": _round(ca.get("mae"), 4),
            "test_mae_pct": _round(tb.get("mae"), 4),
            "control_filled": bool(ca_d["filled"]) if ca_d is not None else False,
            "test_filled": bool(tb_d["filled"]) if tb_d is not None else False,
            "control_closed_realized": bool(ca_d["closed"]) if ca_d is not None else False,
            "test_closed_realized": bool(tb_d["closed"]) if tb_d is not None else False,
            "control_net_realized_return_pct": _round(ca_d.get("net_realized_return_pct"), 4) if ca_d is not None else None,
            "test_net_realized_return_pct": _round(tb_d.get("net_realized_return_pct"), 4) if tb_d is not None else None,
            "control_end_position_return_pct": _round(ca_d.get("portfolio_end_return_pct"), 4) if ca_d is not None else None,
            "test_end_position_return_pct": _round(tb_d.get("portfolio_end_return_pct"), 4) if tb_d is not None else None,
            "control_end_position_pnl_krw": _round(control_pnl, 2),
            "test_end_position_pnl_krw": _round(test_pnl, 2),
            "end_position_pnl_delta_krw": _round(test_pnl - control_pnl, 2),
            "control_entry_status": ca_e["entry_status"] if ca_e is not None else None,
            "test_entry_status": tb_e["entry_status"] if tb_e is not None else None,
        })
    paired = pd.DataFrame(pairs)

    account_rows, trade_rows, dist_rows, mfe_rows, hold_rows = [], [], [], [], []
    account_delta_rows = []
    for side, ledger, replay, details in (
        ("CONTROL", control, control_replay, control_details),
        ("TEST", test, test_replay, test_details),
    ):
        metrics = replay["metrics"]
        curve = pd.DataFrame(replay["daily_equity"])
        curve = curve.loc[curve["date"].astype(str).le(end.strftime("%Y-%m-%d"))]
        stats = prior.trade_statistics(details)
        details_dist = _distribution(details.loc[details.closed, "net_realized_return_pct"].tolist())
        path_dist = _distribution(ledger["terminal_return"].tolist())
        mfe = prior.mfe_mae_statistics(details)
        holding = prior.holding_statistics(details)
        row = {
            "window": window_id,
            "strategy": side,
            "final_asset_krw": _round(metrics.get("final_equity"), 2),
            "cumulative_return_pct": _round(metrics.get("cumulative_return_pct"), 6),
            "CAGR_pct": _round(metrics.get("CAGR_pct"), 6),
            "MDD_pct": _round(metrics.get("mdd_pct"), 6),
            "account_pnl_at_cutoff_krw": _round(float(metrics["final_equity"]) - INITIAL_CAPITAL, 2),
            "total_realized_net_pnl_krw": stats["total_realized_pnl_net_after_costs_krw"],
            "turnover_krw": _round(metrics.get("turnover_krw"), 2),
            "average_capital_utilization_pct": _round(metrics.get("average_capital_utilization_pct"), 6),
            "average_idle_cash_krw": _round(pd.to_numeric(curve["cash"], errors="coerce").mean(), 2),
            "average_idle_cash_ratio_pct": _round(metrics.get("average_cash_ratio_pct"), 6),
            "cash_shortage_skip_count": int(metrics.get("cash_shortage_skipped_entries", 0)),
            "filled_trade_count": int(metrics.get("trade_count", 0)),
            "realized_trade_count": int(metrics.get("realized_trade_count", 0)),
            "open_at_cutoff_count": int(metrics.get("open_at_effective_cutoff_count", 0)),
            "unresolved_count": int(metrics.get("unresolved_count", 0)),
            "cash_conservation_pass": bool(metrics.get("cash_conservation_pass")),
        }
        account_rows.append(row)
        trade_rows.append({"window": window_id, "strategy": side, **stats})
        dist_rows += [
            {"window": window_id, "strategy": side, "basis": "STRATEGY_PATH_GROSS_ALL_ELIGIBLE", **path_dist},
            {"window": window_id, "strategy": side, "basis": "PORTFOLIO_NET_REALIZED_CLOSED", **details_dist},
        ]
        for metric, payload in (
            ("MFE_PCT_FILLED", mfe["filled_trade_mfe_pct"]),
            ("MAE_PCT_FILLED", mfe["filled_trade_mae_pct"]),
            ("REALIZED_NET_GIVEBACK_PP", mfe["realized_net_giveback_pp"]),
            ("REALIZED_NET_PROFIT_CAPTURE_RATIO", mfe["realized_net_profit_capture_ratio"]),
            ("GE_POS_50_WINNER_CAPTURE", mfe["ge_pos_50_winner_capture_ratio"]),
            ("GE_POS_100_WINNER_CAPTURE", mfe["ge_pos_100_winner_capture_ratio"]),
        ):
            mfe_rows.append({"window": window_id, "strategy": side, "metric": metric, **payload})
        hold_rows.append({"window": window_id, "strategy": side, **holding})
    account = pd.DataFrame(account_rows)
    metric_columns = [c for c in account.columns if c not in {"window", "strategy", "cash_conservation_pass", "unresolved_count"}]
    for metric in metric_columns:
        ctl = account.loc[account.strategy.eq("CONTROL"), metric].iloc[0]
        tst = account.loc[account.strategy.eq("TEST"), metric].iloc[0]
        account_delta_rows.append({
            "window": window_id, "metric": metric, "control": ctl, "test": tst,
            "delta_test_minus_control": _round(float(tst) - float(ctl), 6),
        })
    stats_a = trade_rows[0]
    stats_b = trade_rows[1]
    for metric in (
        "winning_trades_net_after_costs", "losing_trades_net_after_costs", "flat_trades_net_after_costs",
        "win_rate_pct", "average_win_pct", "median_win_pct", "average_loss_pct", "median_loss_pct",
        "payoff_ratio", "profit_factor", "expectancy_per_trade_net_pct",
        "expectancy_per_trade_net_krw", "total_realized_pnl_net_after_costs_krw",
    ):
        x, y = stats_a.get(metric), stats_b.get(metric)
        account_delta_rows.append({
            "window": window_id, "metric": f"trade_{metric}", "control": x, "test": y,
            "delta_test_minus_control": _round(float(y) - float(x), 6) if x is not None and y is not None else None,
        })

    c1_ids = set(c1_events.pair_id.astype(str))
    subset_rows = []
    for side, ledger, details in (("CONTROL", control, control_details), ("TEST", test, test_details)):
        path = ledger.loc[ledger.pair_id.astype(str).isin(c1_ids)]
        det = details.loc[details.pair_id.astype(str).isin(c1_ids)]
        realized = pd.to_numeric(det.loc[det.closed, "net_realized_return_pct"], errors="coerce").dropna()
        terminal = pd.to_numeric(path.terminal_return, errors="coerce").dropna()
        subset_rows.append({
            "window": window_id, "strategy": side, "C1_trade_count": len(path),
            "C1_filled_trade_count": int(det.filled.sum()) if len(det) else 0,
            "C1_realized_trade_count": int(det.closed.sum()) if len(det) else 0,
            "C1_extension_Exit3_count": int(c1_events.decision.eq("APPLY_EXIT3_COVERAGE_EXTENSION").sum()) if side == "TEST" else 0,
            "path_return_mean_pct": _round(terminal.mean()), "path_return_median_pct": _round(terminal.median()),
            "net_realized_return_mean_pct": _round(realized.mean()), "net_realized_return_median_pct": _round(realized.median()),
            "net_realized_win_rate_pct": _round(100 * (realized > 0).mean()) if len(realized) else None,
            "path_le_neg_30_count": int((terminal <= -30).sum()),
            "path_le_neg_50_count": int((terminal <= -50).sum()),
            "path_le_neg_60_count": int((terminal <= -60).sum()),
            "mean_MFE_pct": _round(pd.to_numeric(path.mfe, errors="coerce").mean()),
            "median_MFE_pct": _round(pd.to_numeric(path.mfe, errors="coerce").median()),
            "mean_MAE_pct": _round(pd.to_numeric(path.mae, errors="coerce").mean()),
            "median_MAE_pct": _round(pd.to_numeric(path.mae, errors="coerce").median()),
            "mean_holding_days": _round(pd.to_numeric(path.holding_days, errors="coerce").mean()),
            "median_holding_days": _round(pd.to_numeric(path.holding_days, errors="coerce").median()),
            "portfolio_end_position_pnl_krw": _round(pd.to_numeric(det.portfolio_end_pnl_krw, errors="coerce").sum(), 2),
        })
    c1 = pd.DataFrame(subset_rows)
    c1_test_pnl = c1.loc[c1.strategy.eq("TEST"), "portfolio_end_position_pnl_krw"].iloc[0]
    c1_control_pnl = c1.loc[c1.strategy.eq("CONTROL"), "portfolio_end_position_pnl_krw"].iloc[0]
    c1["portfolio_end_position_pnl_delta_vs_control_krw"] = None
    c1.loc[c1.strategy.eq("TEST"), "portfolio_end_position_pnl_delta_vs_control_krw"] = _round(c1_test_pnl - c1_control_pnl, 2)

    paired_c1 = paired.loc[paired.pair_id.astype(str).isin(c1_ids)]
    deep_rows = []
    for threshold in (30, 40, 50, 60):
        control_return = pd.to_numeric(paired_c1.control_terminal_return_pct, errors="coerce")
        test_return = pd.to_numeric(paired_c1.test_terminal_return_pct, errors="coerce")
        rescued = control_return.le(-threshold) & test_return.gt(-threshold)
        both_filled = paired_c1.control_filled & paired_c1.test_filled
        actual = rescued & both_filled
        deep_rows.append({
            "window": window_id, "basis": "C1_STRATEGY_PATH_GROSS", "threshold_pct": -threshold,
            "control_deep_loss_count": int(control_return.le(-threshold).sum()),
            "rescued_above_threshold_count": int(rescued.sum()),
            "rescued_trade_ids": ";".join(paired_c1.loc[rescued, "trade_id"].astype(str)),
            "saved_return_sum_pp": _round((test_return.loc[rescued] - control_return.loc[rescued]).sum()),
            "both_filled_rescue_count": int(actual.sum()),
            "portfolio_saved_pnl_krw_both_filled": _round(
                paired_c1.loc[actual, "end_position_pnl_delta_krw"].sum(), 2
            ),
        })
    winner_rows = []
    for threshold in (50, 100, 200):
        control_return = pd.to_numeric(paired_c1.control_terminal_return_pct, errors="coerce")
        test_return = pd.to_numeric(paired_c1.test_terminal_return_pct, errors="coerce")
        damaged = control_return.ge(threshold) & test_return.lt(threshold)
        actual = damaged & paired_c1.control_filled & paired_c1.test_filled
        winner_rows.append({
            "window": window_id, "row_type": "SUMMARY", "threshold_pct": threshold,
            "trade_id": None, "ticker": None, "control_return_pct": None, "test_return_pct": None,
            "return_delta_pp": None, "end_position_pnl_delta_krw": None,
            "winner_lost_count": int(damaged.sum()), "both_filled_winner_lost_count": int(actual.sum()),
            "portfolio_pnl_contribution_delta_krw": _round(
                paired_c1.loc[actual, "end_position_pnl_delta_krw"].sum(), 2
            ),
        })
    ext_ids = set(c1_events.loc[c1_events.decision.eq("APPLY_EXIT3_COVERAGE_EXTENSION"), "pair_id"].astype(str))
    harmed = paired.loc[
        paired.pair_id.astype(str).isin(ext_ids)
        & paired.control_filled
        & paired.test_filled
    ].sort_values("end_position_pnl_delta_krw")
    for rank, row in enumerate(harmed.head(10).to_dict(orient="records"), 1):
        winner_rows.append({
            "window": window_id, "row_type": f"TOP_{rank}_HARMED", "threshold_pct": None,
            "trade_id": row["trade_id"], "ticker": row["ticker"],
            "control_return_pct": row["control_terminal_return_pct"],
            "test_return_pct": row["test_terminal_return_pct"],
            "return_delta_pp": row["path_return_delta_pp"],
            "end_position_pnl_delta_krw": row["end_position_pnl_delta_krw"],
            "winner_lost_count": None, "both_filled_winner_lost_count": None,
            "portfolio_pnl_contribution_delta_krw": None,
        })

    exit_rows = []
    for side, ledger, details in (("CONTROL", control, control_details), ("TEST", test, test_details)):
        path_classes = ledger.exit_type.map(_exit_class)
        closed_mix = details.loc[details.closed, "source_exit_type"].map(_exit_class).value_counts().to_dict()
        for cls in ("Exit4", "Exit3", "Loss Guard", "No Exit / cutoff", "Other"):
            group = ledger.loc[path_classes.eq(cls)]
            exit_rows.append({
                "window": window_id, "strategy": side, "exit_class": cls,
                "strategy_path_count": int(len(group)),
                "portfolio_realized_closed_fill_count": int(closed_mix.get(cls, 0)),
                "C1_extension_Exit3_count": int(c1_events.decision.eq("APPLY_EXIT3_COVERAGE_EXTENSION").sum())
                    if side == "TEST" and cls == "Exit3" else 0,
                "open_at_cutoff_count": int(group.trade_status.astype(str).eq("OPEN_AT_CUTOFF").sum()),
                "mean_path_return_pct": _round(pd.to_numeric(group.terminal_return, errors="coerce").mean()),
                "median_path_return_pct": _round(pd.to_numeric(group.terminal_return, errors="coerce").median()),
            })

    sessions = tuple(pd.Timestamp(x).normalize() for x in trading_dates)
    session_index = {day: i for i, day in enumerate(sessions)}
    entry_map_a = {str(x["pair_id"]): x for x in control_entries.to_dict(orient="records")}
    entry_map_b = {str(x["pair_id"]): x for x in test_entries.to_dict(orient="records")}
    detail_map_b = {str(x["pair_id"]): x for x in test_details.to_dict(orient="records")}
    ledger_map_a = {str(x["pair_id"]): x for x in control.to_dict(orient="records")}
    test_only, early = [], []
    for pair_id in set(entry_map_a) | set(entry_map_b):
        ca = entry_map_a.get(pair_id, {})
        tb = entry_map_b.get(pair_id, {})
        if tb.get("entry_status") == "EXECUTED" and ca.get("entry_status") == "SKIPPED_CASH_UNAVAILABLE":
            test_only.append(detail_map_b.get(pair_id, {}))
    for pair_id in sorted(ext_ids):
        detail = detail_map_b.get(pair_id, {})
        if not detail.get("filled"):
            continue
        exit_day = _date(detail.get("exit_execution_date"))
        if exit_day is None:
            continue
        next_index = session_index.get(exit_day, -1) + 1
        next_day = sessions[next_index].strftime("%Y-%m-%d") if 0 <= next_index < len(sessions) else None
        control_exit = _date(ledger_map_a[pair_id].get("exit_execution_date"))
        early.append({
            "window": window_id, "pair_id": pair_id, "trade_id": detail.get("trade_id"),
            "ticker": detail.get("ticker"), "exit3_execution_date": exit_day.strftime("%Y-%m-%d"),
            "cash_available_t_plus_1": next_day,
            "control_exit_execution_date": control_exit.strftime("%Y-%m-%d") if control_exit is not None else None,
            "test_net_realized_pnl_krw": detail.get("net_realized_pnl_krw"),
            "test_end_position_pnl_krw": detail.get("portfolio_end_pnl_krw"),
        })
    test_only_closed = [x for x in test_only if x and x.get("closed")]
    control_only = sum(
        1 for pair_id in set(entry_map_a) | set(entry_map_b)
        if entry_map_a.get(pair_id, {}).get("entry_status") == "EXECUTED"
        and entry_map_b.get(pair_id, {}).get("entry_status") != "EXECUTED"
    )
    rotation = pd.DataFrame([{
        "window": window_id,
        "extended_exit3_events": len(ext_ids),
        "extended_exit3_filled": len(early),
        "cash_release_policy": "next certified local trading session; never same-day reuse",
        "test_only_cash_shortage_fills": len(test_only),
        "test_only_cash_shortage_fills_closed": len(test_only_closed),
        "test_only_cash_shortage_fills_realized_net_pnl_krw": _round(
            sum(float(x["net_realized_pnl_krw"]) for x in test_only_closed), 2
        ),
        "test_only_cash_shortage_fills_open": sum(1 for x in test_only if x and not x.get("closed")),
        "control_only_fills": control_only,
        "incremental_fill_attribution": "cash is fungible; portfolio-level difference is not assigned to a single exit",
    }])
    return {
        "portfolio_summary": account,
        "portfolio_summary_delta": pd.DataFrame(account_delta_rows),
        "trade_statistics": pd.DataFrame(trade_rows),
        "return_distribution": pd.DataFrame(dist_rows),
        "mfe_mae_comparison": pd.DataFrame(mfe_rows),
        "holding_period_comparison": pd.DataFrame(hold_rows),
        "coverage_c1_subset": c1,
        "deep_loss_rescue": pd.DataFrame(deep_rows),
        "winner_damage": pd.DataFrame(winner_rows),
        "exit_structure": pd.DataFrame(exit_rows),
        "paired_trade_comparison": paired,
        "capital_rotation_analysis": rotation,
        "early_exit3_cash_release": pd.DataFrame(early),
    }


def _run_window(
    window_id: str,
    stage_cache: Mapping[tuple[str, str, str], pd.DataFrame],
    stage_audit: Mapping[str, Any],
) -> dict[str, Any]:
    spec = prior.WINDOWS[window_id]
    source_dir = prior._source_run_dir(window_id)
    source_summary, control, source_hashes = prior._load_source(window_id)
    contract = json.loads((source_dir / "execution_contract.json").read_text(encoding="utf-8"))
    pit_sha = source_summary.get("data_authority", {}).get("effective_pit_file_sha256")
    run, start, end, support = _context(window_id)
    current_pit_sha = _sha256(run.authority.pit_path)
    if current_pit_sha != pit_sha:
        raise RuntimeError(f"CERTIFIED_PIT_AUTHORITY_CHANGED:{window_id}")
    contract_gate = prior._validate_source_execution_contract(window_id, contract, current_pit_sha)
    pit_gate = prior.validate_pit_entry_rows(control, source_dir / "pit_mcap_audit.csv")

    panel, count_gate = lc.load_realistic(window_id)
    _compare_entry_parity(control, panel)
    if set(control.pair_id.astype(str)) != set(panel.pair_id.astype(str)):
        raise RuntimeError(f"FROZEN_ENTRY_SET_CHANGED:{window_id}")
    holding_paths = lc.trade_paths(panel, pd.Series(end, index=panel.index), stage_cache)
    panel = panel.join(holding_paths)
    frames, frame_meta = prior._load_frames(window_id, control, run, start, end, support)
    events, applied = _held_c1_events(window_id, panel, stage_cache, end, support, frames)
    test = _apply_exit3(control, applied, frames, end, support)
    entry_gate = _compare_entry_parity(control, test)
    changed_ids = set(applied.pair_id.astype(str))
    exit_gate = _compare_exit_only_parity(control, test, changed_ids)

    archived = pd.read_csv(
        ROOT / "artifacts/patterns/pattern_a_fast/research/a_vs_c1_divergence_v01/a_vs_c1_trade_level.csv",
        dtype={"ticker": str},
        low_memory=False,
    )
    archived = archived.loc[
        archived.panel.eq(f"REALISTIC_{window_id}_ELIGIBLE") & archived.group.eq("C1")
    ].copy()
    current = {tuple((row["ticker"], row["trade_id"], row["entry_signal_date"])): row
               for row in events.to_dict(orient="records")}
    archived_map = {tuple((str(row["ticker"]).zfill(6), str(row["trade_id"]), str(row["entry_signal_date"])[:10])): row
                    for row in archived.to_dict(orient="records")}
    if set(current) != set(archived_map) or len(archived) != len(events):
        raise RuntimeError(f"ARCHIVED_C1_SUBSET_IDENTITY_MISMATCH:{window_id}")
    for key, item in current.items():
        old = archived_map[key]
        if _date_text(old.get("anchor_effective")) != _date_text(item.get("first_progressed_effective_date")):
            raise RuntimeError(f"ARCHIVED_C1_ANCHOR_MISMATCH:{window_id}:{key}")
        if _date_text(old.get("first_departure_effective")) != _date_text(item.get("first_departure_effective_date")):
            raise RuntimeError(f"ARCHIVED_C1_DEPARTURE_MISMATCH:{window_id}:{key}")
        if str(_clean(old.get("first_departure_stage"))) != str(_clean(item.get("first_departure_stage"))):
            raise RuntimeError(f"ARCHIVED_C1_STAGE_MISMATCH:{window_id}:{key}")

    calendar = tuple(pd.Timestamp(x).normalize() for x in run.calendar.trading_dates)
    gap_classes = prior._gap_classifications(source_dir)
    control_replay = portfolio._portfolio_replay(
        control.to_dict(orient="records"), frames, calendar,
        strategy_id=SOURCE_STRATEGY_ID, effective_start=start, effective_end=end,
        execution_support=support, gap_classifications=gap_classes,
    )
    control_replay_gate = prior._baseline_replay_parity(
        control_replay["metrics"], source_summary["portfolio"]["control"], window_id
    )
    test_replay = portfolio._portfolio_replay(
        test.to_dict(orient="records"), frames, calendar,
        strategy_id=TEST_STRATEGY_ID, effective_start=start, effective_end=end,
        execution_support=support, gap_classifications=gap_classes,
    )
    fallback_tickers = frame_meta["sparse_entry_open_fallback_tickers"]
    fallback_gate = {
        "control": prior._validate_sparse_fallback_nonfill(control_replay, fallback_tickers, "CONTROL", window_id),
        "test": prior._validate_sparse_fallback_nonfill(test_replay, fallback_tickers, "TEST", window_id),
    }
    if test_replay["metrics"]["unresolved_count"] != 0:
        raise RuntimeError(f"TEST_UNRESOLVED_ROWS:{window_id}:{test_replay['metrics']['unresolved_count']}")
    if not test_replay["metrics"]["cash_conservation_pass"]:
        raise RuntimeError(f"TEST_CASH_CONSERVATION_FAILED:{window_id}")
    control_details, control_entries = prior.portfolio_trade_details(control_replay, control, calendar, end)
    test_details, test_entries = prior.portfolio_trade_details(test_replay, test, calendar, end)
    control_details = _add_end_position_pnl(
        control_replay, control, control_details, frames, calendar, end, gap_classes, SOURCE_STRATEGY_ID
    )
    test_details = _add_end_position_pnl(
        test_replay, test, test_details, frames, calendar, end, gap_classes, TEST_STRATEGY_ID
    )
    tables = _make_tables(
        window_id, control, test, control_replay, test_replay, control_details, test_details,
        control_entries, test_entries, events, calendar, end,
    )
    validation = {
        "window": window_id,
        "source_status": source_summary["status"],
        "source_control_rows": int(len(control)),
        "source_control_portfolio_replay_parity": control_replay_gate["status"],
        "entry_identity_parity": entry_gate["status"],
        "exit_only_parity": exit_gate["status"],
        "C1_holding_count": int(len(events)),
        "held_first_departure_count": int(events.first_departure_effective_date.notna().sum()),
        "applied_Exit3_extension_count": int(len(applied)),
        "archived_C1_identity_and_event_parity": True,
        "PIT_entry_audit": pit_gate["status"],
        "source_execution_contract": contract_gate["status"],
        "sparse_fallback_control_test": fallback_gate,
        "test_unresolved_count": int(test_replay["metrics"]["unresolved_count"]),
        "test_cash_conservation_pass": bool(test_replay["metrics"]["cash_conservation_pass"]),
        "stage_cache_sha256": _sha256(lc.STAGE_CACHE_PATH),
        "stage_leakage_sample_size": stage_audit["leakage_check"]["sample_size"],
        "stage_leakage_mismatch_count": stage_audit["leakage_check"]["mismatch_count"],
        "stage_effective_dates_within_control_holding_end": bool(
            (events.max_stage_effective_date_used.fillna("") <= events.holding_end_date.fillna("")).all()
        ),
        "network_calls": 0,
    }
    if validation["stage_leakage_mismatch_count"] != 0:
        raise RuntimeError(f"STAGE_CACHE_LEAKAGE_GATE_FAILED:{window_id}")
    return {
        "window": window_id,
        "spec": {"start": spec["start"], "end": spec["end"], "support": spec["support"]},
        "source_summary": source_summary,
        "source_hashes": source_hashes,
        "source_execution_contract_sha256": _sha256(source_dir / "execution_contract.json"),
        "pit_audit_sha256": _sha256(source_dir / "pit_mcap_audit.csv"),
        "frame_meta": frame_meta,
        "count_gate": count_gate,
        "validation": validation,
        "control": control,
        "test": test,
        "control_replay": control_replay,
        "test_replay": test_replay,
        "events": events,
        "tables": tables,
    }


def _verdict(results: Sequence[Mapping[str, Any]], account: pd.DataFrame, c1: pd.DataFrame, deep: pd.DataFrame, paired: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    if any(
        row["test_unresolved_count"] != 0
        or not row["test_cash_conservation_pass"]
        or row["stage_leakage_mismatch_count"] != 0
        for row in (r["validation"] for r in results)
    ):
        return "CHECK_REQUIRED", {"reason": "a validation gate failed"}
    asset = account.pivot(index="window", columns="strategy", values="final_asset_krw")
    c1mean = c1.pivot(index="window", columns="strategy", values="path_return_mean_pct")
    asset_up = int((asset.TEST > asset.CONTROL).sum())
    c1_up = int((c1mean.TEST > c1mean.CONTROL).sum())
    repeated_rescue = 0
    for window in WINDOW_IDS:
        rows = deep.loc[deep.window.eq(window)]
        if not rows.empty and int(rows.loc[rows.threshold_pct.eq(-30), "rescued_above_threshold_count"].sum()) > 0:
            repeated_rescue += 1
    c1_pairs = paired.loc[paired.holding_subgroup.eq(lc.HOLDING_C1)]
    both_filled = c1_pairs.control_filled & c1_pairs.test_filled
    rescue = c1_pairs.control_terminal_return_pct.le(-30) & c1_pairs.test_terminal_return_pct.gt(-30) & both_filled
    damaged = c1_pairs.control_terminal_return_pct.ge(50) & c1_pairs.test_terminal_return_pct.lt(50) & both_filled
    rescue_pnl = float(pd.to_numeric(c1_pairs.loc[rescue, "end_position_pnl_delta_krw"], errors="coerce").sum())
    harm_pnl = float(pd.to_numeric(c1_pairs.loc[damaged, "end_position_pnl_delta_krw"], errors="coerce").sum())
    detail = {
        "windows_final_asset_up": asset_up,
        "windows_C1_mean_path_return_up": c1_up,
        "windows_with_C1_le_neg_30_rescue": repeated_rescue,
        "both_filled_le_neg_30_rescue_pnl_delta_krw": _round(rescue_pnl, 2),
        "both_filled_ge_pos_50_winner_damage_pnl_delta_krw": _round(harm_pnl, 2),
        "decision_rule": "supported requires at least 2/3 windows with non-negative final-asset delta, C1 mean path return improvement, repeated C1 tail rescue, and rescue P/L covering negative +50-winner damage; not-supported requires repeated account deterioration or net winner damage beyond rescue",
    }
    if asset_up >= 2 and c1_up >= 2 and repeated_rescue >= 2 and rescue_pnl > 0 and harm_pnl >= -rescue_pnl:
        return "EXIT3_COVERAGE_EXTENSION_SUPPORTED", detail
    if asset_up == 0 or (rescue_pnl <= 0 and harm_pnl < 0) or harm_pnl < -max(0.0, rescue_pnl):
        return "EXIT3_COVERAGE_EXTENSION_NOT_SUPPORTED", detail
    return "MIXED_NO_CLEAR_WINNER", detail


def _markdown_report(
    verdict: str,
    account: pd.DataFrame,
    deltas: pd.DataFrame,
    stats: pd.DataFrame,
    distributions: pd.DataFrame,
    mfe: pd.DataFrame,
    holding: pd.DataFrame,
    exits: pd.DataFrame,
    c1: pd.DataFrame,
    deep: pd.DataFrame,
    winners: pd.DataFrame,
    validations: Sequence[Mapping[str, Any]],
    start_head: str,
) -> str:
    def fmt(x: Any, digits: int = 2) -> str:
        x = _clean(x)
        if x is None:
            return "—"
        if isinstance(x, (int, np.integer)):
            return f"{int(x):,}"
        if isinstance(x, (float, np.floating)):
            return f"{float(x):,.{digits}f}"
        return str(x)

    lines = [
        "# Exit3 coverage extension realistic portfolio backtest V01",
        "",
        f"Run: {RUN_ID}",
        "",
        "## Verdict",
        "",
        f"{verdict}",
        "",
        "Only holding-lifecycle C1 trades gain a first PROGRESSED departure Exit3. The certified T15 entries, Exit4 15pt, Loss Guard, PIT filter, execution, cost, capital, and universe contracts remain frozen. No production promotion is made.",
        "",
        "## Account performance",
        "",
        "| Window | Strategy | Final Asset | Cumulative Return | CAGR | MDD | Realized Net P/L | Turnover | Utilization | Avg Idle Cash | Cash Skips | Filled / Realized / Open |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in account.to_dict(orient="records"):
        lines.append(
            f"| {row['window']} | {row['strategy']} | {fmt(row['final_asset_krw'])} KRW | {fmt(row['cumulative_return_pct'])}% | {fmt(row['CAGR_pct'])}% | {fmt(row['MDD_pct'])}% | {fmt(row['total_realized_net_pnl_krw'])} KRW | {fmt(row['turnover_krw'])} KRW | {fmt(row['average_capital_utilization_pct'])}% | {fmt(row['average_idle_cash_krw'])} KRW | {fmt(row['cash_shortage_skip_count'])} | {fmt(row['filled_trade_count'])}/{fmt(row['realized_trade_count'])}/{fmt(row['open_at_cutoff_count'])} |"
        )
    lines += ["", "Account deltas are TEST minus CONTROL; see portfolio_summary_delta.csv.", "", "## Win/Loss statistics", ""]
    for row in stats.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']}: win rate {fmt(row.get('win_rate_pct'))}%; wins/losses/flat {fmt(row.get('winning_trades_net_after_costs'))}/{fmt(row.get('losing_trades_net_after_costs'))}/{fmt(row.get('flat_trades_net_after_costs'))}; average/median win {fmt(row.get('average_win_pct'))}%/{fmt(row.get('median_win_pct'))}%; average/median loss {fmt(row.get('average_loss_pct'))}%/{fmt(row.get('median_loss_pct'))}%; payoff {fmt(row.get('payoff_ratio'))}; profit factor {fmt(row.get('profit_factor'))}; expectancy {fmt(row.get('expectancy_per_trade_net_pct'))}% and {fmt(row.get('expectancy_per_trade_net_krw'))} KRW per trade."
        )
    lines += ["", "## Return distribution", ""]
    for row in distributions.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']} {row['basis']}: n={fmt(row.get('n'))}; mean/median/P25/P75={fmt(row.get('mean'))}%/{fmt(row.get('median'))}%/{fmt(row.get('p25'))}%/{fmt(row.get('p75'))}%; >=+20/+30/+50/+100/+200={fmt(row.get('ge_pos_20_count'))}/{fmt(row.get('ge_pos_30_count'))}/{fmt(row.get('ge_pos_50_count'))}/{fmt(row.get('ge_pos_100_count'))}/{fmt(row.get('ge_pos_200_count'))}; <=-15/-30/-40/-50/-60={fmt(row.get('le_neg_15_count'))}/{fmt(row.get('le_neg_30_count'))}/{fmt(row.get('le_neg_40_count'))}/{fmt(row.get('le_neg_50_count'))}/{fmt(row.get('le_neg_60_count'))}."
        )
    lines += [
        "",
        "## MFE / MAE / giveback",
        "",
        "MFE/MAE are price-path returns. Realized giveback and capture ratio use net realized return after the certified costs; +50 and +100 winner capture are included in mfe_mae_comparison.csv.",
        "",
    ]
    for row in mfe.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']} {row['metric']}: n={fmt(row.get('n'))}, mean/median/P25/P75={fmt(row.get('mean'))}/{fmt(row.get('median'))}/{fmt(row.get('p25'))}/{fmt(row.get('p75'))}."
        )
    lines += ["", "## Holding & capital rotation", ""]
    for row in holding.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']}: mean/median/P25/P75 holding sessions={fmt(row.get('mean'))}/{fmt(row.get('median'))}/{fmt(row.get('p25'))}/{fmt(row.get('p75'))}."
        )
    lines += ["", "Sale proceeds become available on the next certified local trading session, never the same day. Test-only cash-shortage fills and their realized P/L are in capital_rotation_analysis.csv; detailed Exit3 releases are in early_exit3_cash_release.csv.", "", "## Exit structure", ""]
    for row in exits.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']} {row['exit_class']}: strategy paths {fmt(row['strategy_path_count'])}; closed portfolio fills {fmt(row['portfolio_realized_closed_fill_count'])}; new C1 Exit3 {fmt(row['C1_extension_Exit3_count'])}; open at cutoff {fmt(row['open_at_cutoff_count'])}."
        )
    lines += ["", "## Coverage/C1 subset", ""]
    for row in c1.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} {row['strategy']}: n={fmt(row['C1_trade_count'])}, filled/realized={fmt(row['C1_filled_trade_count'])}/{fmt(row['C1_realized_trade_count'])}, path mean/median={fmt(row['path_return_mean_pct'])}%/{fmt(row['path_return_median_pct'])}%, net realized win rate={fmt(row['net_realized_win_rate_pct'])}%, <=-30/-50/-60={fmt(row['path_le_neg_30_count'])}/{fmt(row['path_le_neg_50_count'])}/{fmt(row['path_le_neg_60_count'])}, median MFE/MAE={fmt(row['median_MFE_pct'])}%/{fmt(row['median_MAE_pct'])}%, median holding={fmt(row['median_holding_days'])} sessions."
        )
    lines += ["", "## Deep-loss rescue", ""]
    for row in deep.to_dict(orient="records"):
        lines.append(
            f"- {row['window']} C1 <= {fmt(row['threshold_pct'])}%: CONTROL deep-loss {fmt(row['control_deep_loss_count'])}; rescued above threshold {fmt(row['rescued_above_threshold_count'])}; saved path return sum {fmt(row['saved_return_sum_pp'])} pp; both-filled rescues {fmt(row['both_filled_rescue_count'])}; end-position P/L delta {fmt(row['portfolio_saved_pnl_krw_both_filled'])} KRW."
        )
    lines += ["", "## Winner damage", ""]
    for row in winners.loc[winners.row_type.eq("SUMMARY")].to_dict(orient="records"):
        lines.append(
            f"- {row['window']} prior CONTROL >=+{fmt(row['threshold_pct'])}% winners reduced below threshold: {fmt(row['winner_lost_count'])}; both-filled {fmt(row['both_filled_winner_lost_count'])}; end-position contribution delta {fmt(row['portfolio_pnl_contribution_delta_krw'])} KRW."
        )
    lines += [
        "",
        "Top ten most harmed extended C1 trades per window are listed as TOP rows in winner_damage.csv, with CONTROL/TEST returns and portfolio contribution deltas.",
        "",
        "## Paired Trade comparison",
        "",
        "paired_trade_comparison.csv contains every frozen entry identity, exit reason/date, holding delta, path return, MFE/MAE, holding-lifecycle class, first PROGRESSED/departure dates and stage, portfolio fill status, net realized outcomes, and end-position P/L contribution.",
        "",
        "## Window consistency",
        "",
    ]
    asset = account.pivot(index="window", columns="strategy", values="final_asset_krw")
    c1_mean = c1.pivot(index="window", columns="strategy", values="path_return_mean_pct")
    lines.append(
        f"TEST final asset is higher in {int((asset.TEST > asset.CONTROL).sum())}/3 windows; C1 mean path return is higher in {int((c1_mean.TEST > c1_mean.CONTROL).sum())}/3 windows. The windows overlap and are not independent replications."
    )
    lines += [
        "",
        "## Final interpretation",
        "",
        "1. Final Asset and CAGR are reported for all three windows; account-level results take priority.",
        "2. Win rate is net realized return greater than zero and excludes open positions.",
        "3. Deep-loss counts use CONTROL/TEST trade-path returns; saved portfolio P/L is separately limited to pairs filled in both accounts.",
        "4. Winner loss counts compare the prior CONTROL return with the TEST return at +50, +100, and +200.",
        "5. Giveback, profit capture, and +50/+100 winner capture are listed in the MFE/MAE table.",
        "6. Holding days and T+1 capital release use the realistic portfolio replay.",
        "7. C1 subset and whole-account effects are separate.",
        "8. Direction across windows is reported, with the overlap limitation.",
        "9. Exit4 remains 15pt; this research does not promote a production strategy.",
        "",
        "## Validation",
        "",
    ]
    for item in validations:
        lines.append("- " + item["window"] + ": " + "; ".join(
            f"{k}={v}" for k, v in item.items() if k != "window"
        ) + ".")
    lines += [
        "",
        "Holding-stage observations were clipped at the CONTROL holding end. No post-exit stage was used. The first PROGRESSED departure uses the existing V2 outcome calculator and next local session open. No API/network call was made.",
        "",
        "## Git",
        "",
        f"- Start HEAD: {start_head}",
        "- End HEAD: this research output commit on main",
        "- Commit: research: add Exit3 coverage extension realistic backtest",
        "- Push: origin/main",
        "- HEAD == origin/main: verify after push",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    start_head = prior._git_head()
    if not any(str(row[0]) == "2026-01-01" for row in portfolio.SELL_TAX_SCHEDULE):
        portfolio.SELL_TAX_SCHEDULE = (
            *portfolio.SELL_TAX_SCHEDULE,
            ("2026-01-01", "2026-12-31", 0.0020),
        )
    if not lc.STAGE_CACHE_PATH.is_file() or not lc.STAGE_AUDIT_PATH.is_file():
        raise FileNotFoundError("CERTIFIED_MONTHLY_STAGE_CACHE_OR_AUDIT_MISSING")
    stage_audit = json.loads(lc.STAGE_AUDIT_PATH.read_text(encoding="utf-8"))
    stage_sha = _sha256(lc.STAGE_CACHE_PATH)
    if stage_audit.get("cache_sha256") != stage_sha:
        raise RuntimeError("MONTHLY_STAGE_CACHE_HASH_MISMATCH")
    if stage_audit.get("label_end") != "2026-08-31" or stage_audit.get("data_support_end") != "2026-09-01":
        raise RuntimeError("MONTHLY_STAGE_CACHE_CUTOFF_MISMATCH")
    if stage_audit.get("load_errors") or stage_audit.get("leakage_check", {}).get("mismatch_count") != 0:
        raise RuntimeError("MONTHLY_STAGE_CACHE_AUDIT_NOT_PASS")
    stage_cache = lc.load_stage_cache()
    results = []
    for window_id in WINDOW_IDS:
        print(f"Running realistic Exit3 coverage extension replay: {window_id}", flush=True)
        results.append(_run_window(window_id, stage_cache, stage_audit))

    tables: dict[str, list[pd.DataFrame]] = {}
    for result in results:
        for name, frame in result["tables"].items():
            tables.setdefault(name, []).append(frame)
        tables.setdefault("exit3_extension_events", []).append(result["events"])
    all_tables = {
        name: pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
        for name, parts in tables.items()
    }
    account = all_tables["portfolio_summary"]
    c1 = all_tables["coverage_c1_subset"]
    deep = all_tables["deep_loss_rescue"]
    paired = all_tables["paired_trade_comparison"]
    verdict, verdict_detail = _verdict(results, account, c1, deep, paired)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in all_tables.items():
        frame.to_csv(RUN_DIR / f"{name}.csv", index=False)
    validations = [result["validation"] for result in results]
    provenance = {
        "work_id": WORK_ID,
        "run_id": RUN_ID,
        "start_head": start_head,
        "source_strategy_id": SOURCE_STRATEGY_ID,
        "test_strategy_id": TEST_STRATEGY_ID,
        "control_source_run_id": prior.SOURCE_RUN_ID,
        "monthly_stage_cache_sha256": stage_sha,
        "monthly_stage_audit_sha256": _sha256(lc.STAGE_AUDIT_PATH),
        "portfolio_engine": "scripts.run_p2_1_realistic_portfolio_v01._portfolio_replay",
        "test_exit_outcome_calculator": "trend_scanner.validation.pattern_a_fast_core_v02_reentry._calc_trade_outcome",
        "analysis_scope": "realistic portfolio P2-1, P2-2, P3-2; no simple 5-window portfolio replay",
        "portfolio_contract": {
            "initial_capital_krw": INITIAL_CAPITAL,
            "position_budget_krw": 5_000_000,
            "position_cap": None,
            "exit4_threshold_points": 15,
            "same_entry_identity_set": True,
            "exact_entry_signal_date_pit_market_cap": True,
            "same_execution_costs_tax_slippage_and_t_plus_1_cash_release": True,
            "only_strategy_delta": "holding-lifecycle C1 first held PROGRESSED departure Exit3",
        },
        "network_calls": 0,
        "validation": validations,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
    }
    summary = {
        **provenance,
        "account_performance": account.to_dict(orient="records"),
        "trade_statistics": all_tables["trade_statistics"].to_dict(orient="records"),
        "return_distribution": all_tables["return_distribution"].to_dict(orient="records"),
        "coverage_c1_subset": c1.to_dict(orient="records"),
    }
    (RUN_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    report = _markdown_report(
        verdict, account, all_tables["portfolio_summary_delta"], all_tables["trade_statistics"],
        all_tables["return_distribution"], all_tables["mfe_mae_comparison"],
        all_tables["holding_period_comparison"], all_tables["exit_structure"], c1, deep,
        all_tables["winner_damage"], validations, start_head,
    )
    (RUN_DIR / "final_report.md").write_text(report, encoding="utf-8")
    manifest = {
        "work_id": WORK_ID,
        "run_id": RUN_ID,
        "start_head": start_head,
        "verdict": verdict,
        "files": {
            path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in sorted(RUN_DIR.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        },
    }
    (RUN_DIR / "artifact_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "output_dir": str(RUN_DIR),
        "account": account.to_dict(orient="records"),
        "validation": validations,
        "start_head": start_head,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
