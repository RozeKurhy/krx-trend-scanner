#!/usr/bin/env python3
"""Research-only Candidate C replay against the certified frozen P3-2 control."""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
BASE_RUNNER_PATH = BASE_DIR / "run_frozen_replay.py"
BASE_SPEC = importlib.util.spec_from_file_location("p3_2_frozen_authority_replay", BASE_RUNNER_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:
    raise RuntimeError("FROZEN_CONTROL_HELPER_IMPORT_FAILED")
base = importlib.util.module_from_spec(BASE_SPEC)
sys.modules[BASE_SPEC.name] = base
BASE_SPEC.loader.exec_module(base)

OUT_DIR = Path(__file__).resolve().parent
CONTROL_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
CANDIDATE_STRATEGY_ID = "P3_2_V2_120D_HWM_NEG20_C"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_120D_HWM_EXIT_EXPERIMENT_V01_COMPLETE"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_120D_HWM_EXIT_EXPERIMENT_V01_CHECK_REQUIRED"
WORKERS = 10
CONTROL_FILES = (
    "control_strategy_trades.csv",
    "control_portfolio_events.csv",
    "control_daily_equity.csv",
    "control_pit_mcap_audit.csv",
    "summary.json",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _require(condition: bool, token: str) -> None:
    if not condition:
        raise RuntimeError(token)


def _verify_control_inputs() -> dict[str, Any]:
    summary_path = BASE_DIR / "summary.json"
    preflight_path = BASE_DIR / "preflight.json"
    _require(summary_path.is_file() and preflight_path.is_file(), "FROZEN_CONTROL_SUMMARY_OR_PREFLIGHT_MISSING")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    _require(summary.get("status") == "COMPLETE", "FROZEN_CONTROL_NOT_COMPLETE")
    _require(summary.get("final_token") == "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE", "FROZEN_CONTROL_TOKEN_MISMATCH")
    _require(summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    _require(all(bool(value.get("pass")) for value in summary.get("control_parity", {}).values()), "FROZEN_CONTROL_PARITY_COMPONENT_FAILED")
    _require(preflight.get("status") == "PASS", "FROZEN_CONTROL_PREFLIGHT_NOT_PASS")
    _require(preflight.get("latest_authority_dependency_in_frozen_mode") is False, "FROZEN_CONTROL_USES_LATEST_AUTHORITY")
    _require(preflight.get("survivor_ticker_count") == 2539 and preflight.get("worker_count") == 10, "FROZEN_CONTROL_UNIVERSE_OR_WORKERS_MISMATCH")
    expected_authority = summary.get("frozen_authority", {})
    _require(expected_authority.get("historical_pit_sha256") == "6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1", "FROZEN_CONTROL_PIT_HASH_MISMATCH")
    _require(expected_authority.get("calendar_sha256") == "cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2", "FROZEN_CONTROL_CALENDAR_HASH_MISMATCH")
    _require(expected_authority.get("saved_survivor_audit_sha256") == "313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506", "FROZEN_CONTROL_SURVIVOR_HASH_MISMATCH")
    _require(expected_authority.get("survivor_identity_count") == 2539, "FROZEN_CONTROL_SURVIVOR_COUNT_MISMATCH")
    _require(summary.get("network_calls") == 0 and expected_authority.get("new_prices_or_network_calls") == 0, "FROZEN_CONTROL_NETWORK_CALLS_NONZERO")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    file_hashes: dict[str, str] = {}
    for filename in CONTROL_FILES:
        path = BASE_DIR / filename
        _require(path.is_file(), f"FROZEN_CONTROL_FILE_MISSING:{filename}")
        rel = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(["git", "show", f"{head}:{rel}"], cwd=ROOT)
        actual = path.read_bytes()
        _require(actual == committed, f"FROZEN_CONTROL_FILE_DIFFERS_FROM_HEAD:{filename}")
        file_hashes[filename] = _sha256_bytes(actual)
    return {
        "status": "PASS",
        "source_directory": str(BASE_DIR.relative_to(ROOT)),
        "source_final_token": summary["final_token"],
        "source_commit": head,
        "source_control_file_sha256": file_hashes,
        "control_strategy_rows": int(summary["provenance"]["saved_control_strategy_rows"]),
        "control_mcap_rows": int(summary["control_parity"]["mcap"]["actual_rows"]),
        "control_event_rows": int(summary["provenance"]["saved_control_event_rows"]),
        "control_equity_rows": int(summary["provenance"]["saved_control_equity_rows"]),
        "window": {"start": "2022-01-03", "end": "2026-08-31", "execution_support": "2026-09-01"},
        "survivor_identities": 2539,
        "historical_pit_sha256": expected_authority["historical_pit_sha256"],
        "calendar_sha256": expected_authority["calendar_sha256"],
        "survivor_projection_sha256": expected_authority["saved_survivor_audit_sha256"],
        "latest_authority_dependency": False,
        "network_or_new_price_calls": 0,
    }


def _compile_candidate_c() -> Any:
    """AST-clone exact V2 and add only the post-120-session close-HWM exit."""
    strategy_source = base.SOURCE_PATH.read_text(encoding="utf-8")
    _require(_sha256(base.SOURCE_PATH) == base.EXPECTED_STRATEGY_SHA256, "CANONICAL_V2_SOURCE_HASH_CHANGED")
    tree = ast.parse(strategy_source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "simulate_ticker_core_v02_reentry")
    function.name = "simulate_ticker_core_v02_reentry_candidate_c"
    function.args.args.append(ast.arg(arg="research_hwm_policy"))
    function.args.defaults.append(ast.Constant(value="C"))
    strategy_trade_loop = next(node for node in function.body if isinstance(node, ast.While))
    outcome_index = next(
        index for index, node in enumerate(strategy_trade_loop.body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "res_outcome" for target in node.targets)
    )
    hwm_code = ast.parse(
        '''
research_hwm_signal_d = None
research_hwm_exec_d = None
research_hwm_exec_open = None
research_hwm_peak_d = None
research_hwm_close = None
research_hwm_signal_close = None
research_hwm_holding_days = None
research_hwm_return_from_entry_pct = None
research_hwm_signal_return_from_entry_pct = None
research_hwm_drawdown_pct = None
research_hwm_exit_applied = False
research_hwm_suppression_reason = None
if research_hwm_policy == "C":
    hwm_daily = daily[(daily.index >= entry_exec_date) & (daily.index <= valuation_cutoff)]
    if final_sig_d is not None:
        hwm_daily = hwm_daily[hwm_daily.index <= final_sig_d]
    close_hwm = None
    close_hwm_peak_d = None
    for hwm_holding_day, (hwm_day, hwm_row) in enumerate(hwm_daily.iterrows(), start=1):
        completed_close = float(hwm_row["close"])
        if close_hwm is None or completed_close > close_hwm:
            close_hwm = completed_close
            close_hwm_peak_d = hwm_day
        if hwm_holding_day < 120:
            continue
        hwm_drawdown = completed_close / close_hwm - 1.0 if close_hwm else 0.0
        if hwm_drawdown <= -0.20:
            research_hwm_signal_d = hwm_day
            research_hwm_exec_rows = daily[(daily.index > hwm_day) & (daily.index <= execution_support)]
            if not research_hwm_exec_rows.empty:
                research_hwm_exec_d = research_hwm_exec_rows.index[0]
                research_hwm_exec_open = float(research_hwm_exec_rows.iloc[0]["open"])
            research_hwm_peak_d = close_hwm_peak_d
            research_hwm_close = float(close_hwm)
            research_hwm_signal_close = completed_close
            research_hwm_holding_days = int(hwm_holding_day)
            research_hwm_return_from_entry_pct = (close_hwm / entry_open_price - 1.0) * 100.0
            research_hwm_signal_return_from_entry_pct = (completed_close / entry_open_price - 1.0) * 100.0
            research_hwm_drawdown_pct = hwm_drawdown * 100.0
            if final_sig_d is None or hwm_day < final_sig_d:
                final_sig_d = hwm_day
                final_exit_type = "EXIT_120D_CLOSE_HWM_DRAWDOWN_LE_NEG20"
                research_hwm_exit_applied = True
            else:
                research_hwm_suppression_reason = "SAME_DATE_EXISTING_V2_EXIT_PRIORITY"
            break
'''
    ).body
    strategy_trade_loop.body[outcome_index:outcome_index] = hwm_code
    append_index = next(
        index for index, node in enumerate(strategy_trade_loop.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "append"
        and any(isinstance(arg, ast.Name) and arg.id == "record" for arg in node.value.args)
    )
    metadata = ast.parse(
        '''
record.research_hwm_policy = research_hwm_policy
record.research_hwm_signal_date = research_hwm_signal_d.strftime("%Y-%m-%d") if research_hwm_signal_d is not None else None
record.research_hwm_execution_date = research_hwm_exec_d.strftime("%Y-%m-%d") if research_hwm_exec_d is not None else None
record.research_hwm_execution_open = research_hwm_exec_open
record.research_hwm_peak_date = research_hwm_peak_d.strftime("%Y-%m-%d") if research_hwm_peak_d is not None else None
record.research_hwm_close = research_hwm_close
record.research_hwm_signal_close = research_hwm_signal_close
record.research_hwm_holding_days = research_hwm_holding_days
record.research_hwm_return_from_entry_pct = research_hwm_return_from_entry_pct
record.research_hwm_signal_return_from_entry_pct = research_hwm_signal_return_from_entry_pct
record.research_hwm_drawdown_pct = research_hwm_drawdown_pct
record.research_hwm_exit_applied = research_hwm_exit_applied
record.research_hwm_suppression_reason = research_hwm_suppression_reason
'''
    ).body
    strategy_trade_loop.body[append_index:append_index] = metadata
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = vars(base.v2).copy()
    exec(compile(module, str(base.SOURCE_PATH), "exec"), namespace)
    return namespace["simulate_ticker_core_v02_reentry_candidate_c"]


def _serialize_candidate_c(record: Any) -> dict[str, Any]:
    data = base.v2.asdict(record)
    names = (
        "research_hwm_policy", "research_hwm_signal_date", "research_hwm_execution_date",
        "research_hwm_execution_open", "research_hwm_peak_date", "research_hwm_close",
        "research_hwm_signal_close", "research_hwm_holding_days", "research_hwm_return_from_entry_pct",
        "research_hwm_signal_return_from_entry_pct", "research_hwm_drawdown_pct",
        "research_hwm_exit_applied", "research_hwm_suppression_reason",
    )
    data.update({name: getattr(record, name, None) for name in names})
    return data


def _run_candidate(run: Any, tickers: Sequence[str]) -> tuple[list[dict[str, Any]], list[str], float]:
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    original_simulator = base.v2.simulate_ticker_core_v02_reentry
    original_serializer = base.v2.V02TradeRecord.to_dict
    candidate_simulator = _compile_candidate_c()

    def selected_simulator(*args: Any, **kwargs: Any):
        kwargs["research_hwm_policy"] = "C"
        return candidate_simulator(*args, **kwargs)

    base.v2.simulate_ticker_core_v02_reentry = selected_simulator
    base.v2.V02TradeRecord.to_dict = _serialize_candidate_c
    try:
        def process(ticker: str) -> dict[str, Any]:
            item = base.strategy._process_ticker(ticker, run)
            item["worker_thread"] = threading.current_thread().name
            return item

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p3-2-hwm-c") as pool:
            futures = {pool.submit(process, ticker): ticker for ticker in tickers}
            for completed, future in enumerate(as_completed(futures), start=1):
                ticker = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
                if completed % 50 == 0 or completed == len(tickers):
                    rows = sum(len(item.get("control_rows", ())) for item in outcomes)
                    print(
                        f"C progress {completed}/{len(tickers)}; strategy_rows={rows}; "
                        f"PIT attempts={len(run.entry_signal_gate.audit_frame())}; "
                        f"elapsed={time.perf_counter()-started:.1f}s; errors={len(errors)}",
                        flush=True,
                    )
    finally:
        base.v2.simulate_ticker_core_v02_reentry = original_simulator
        base.v2.V02TradeRecord.to_dict = original_serializer
    return outcomes, errors, time.perf_counter() - started


def _records(outcomes: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    return base._records(outcomes)


def _entry_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).zfill(6), str(row.get("entry_signal_date", row.get("signal_date", "")))[:10]


def _actual_entries(events: pd.DataFrame) -> set[tuple[str, str]]:
    executed = events.loc[
        events["event_type"].astype(str).eq("ENTRY")
        & events["event_status"].astype(str).eq("EXECUTED")
    ]
    return {
        (str(row.ticker).zfill(6), str(row.signal_date)[:10])
        for row in executed.itertuples(index=False)
    }


def _trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    status = frame.get("trade_status", pd.Series(index=frame.index, dtype=object)).astype(str)
    terminal = pd.to_numeric(frame.get("terminal_return", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    realized = status.eq("REALIZED")
    realized_return = terminal[realized].dropna()
    mfe = pd.to_numeric(frame.get("mfe", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    mae = pd.to_numeric(frame.get("mae", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    holding = pd.to_numeric(frame.get("holding_days", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    progressed = frame.get("first_progressed_date", pd.Series(index=frame.index, dtype=object)).notna()
    exit_type = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("").astype(str)
    guard_count = int(exit_type.eq("LOSS_GUARD_CLOSE_LE_NEG_15").sum())
    out: dict[str, Any] = {
        "trade_count": int(len(frame)),
        "realized_count": int(realized.sum()),
        "open_count": int(status.str.startswith("OPEN").sum()),
        "realized_win_rate_pct": float((terminal[realized] > 0).mean() * 100) if realized.any() else None,
        "terminal_positive_rate_pct": float((terminal > 0).mean() * 100) if terminal.notna().any() else None,
        "average_terminal_return_pct": float(terminal.mean()),
        "median_terminal_return_pct": float(terminal.median()),
        "average_realized_return_pct": float(realized_return.mean()) if len(realized_return) else None,
        "median_realized_return_pct": float(realized_return.median()) if len(realized_return) else None,
        "average_holding_trading_days": float(holding.mean()),
        "median_holding_trading_days": float(holding.median()),
        "p25_holding_trading_days": float(holding.quantile(0.25)),
        "p75_holding_trading_days": float(holding.quantile(0.75)),
        "loss_guard_exit_count": guard_count,
        "exit_3_count": int(exit_type.str.startswith("EXIT3_").sum()),
        "exit_4_count": int(exit_type.eq("EXIT4_SCORE_DRAWDOWN_GE_15").sum()),
        "hwm_120d_exit_count": int(exit_type.eq("EXIT_120D_CLOSE_HWM_DRAWDOWN_LE_NEG20").sum()),
        "progressed_count": int(progressed.sum()),
        "progressed_rate_pct": float(progressed.mean() * 100) if len(frame) else None,
    }
    for threshold in (20, 50, 100):
        out[f"terminal_ge_pos_{threshold}_count"] = int((terminal >= threshold).sum())
        out[f"mfe_ge_pos_{threshold}_count"] = int((mfe >= threshold).sum())
    for threshold in (20, 30, 40, 50, 60):
        out[f"terminal_le_neg_{threshold}_count"] = int((terminal <= -threshold).sum())
        out[f"realized_le_neg_{threshold}_count"] = int((realized_return <= -threshold).sum())
    for threshold in (20, 30, 40):
        out[f"mae_le_neg_{threshold}_count"] = int((mae <= -threshold).sum())
    return out


def _entry_set_metrics(keys: set[tuple[str, str]], lookup: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    rows = [lookup[key] for key in sorted(keys) if key in lookup]
    terminal = pd.to_numeric(pd.Series([row.get("terminal_return") for row in rows]), errors="coerce")
    mfe = pd.to_numeric(pd.Series([row.get("mfe") for row in rows]), errors="coerce")
    mae = pd.to_numeric(pd.Series([row.get("mae") for row in rows]), errors="coerce")
    positive = terminal > 0
    result: dict[str, Any] = {
        "n": len(rows),
        "average_terminal_return_pct": float(terminal.mean()) if terminal.notna().any() else None,
        "median_terminal_return_pct": float(terminal.median()) if terminal.notna().any() else None,
        "positive_count": int(positive.sum()),
        "positive_rate_pct": float(positive.mean() * 100) if len(rows) else None,
        "average_mfe_pct": float(mfe.mean()) if mfe.notna().any() else None,
        "average_mae_pct": float(mae.mean()) if mae.notna().any() else None,
    }
    for threshold in (50, 100):
        result[f"terminal_ge_pos_{threshold}_count"] = int((terminal >= threshold).sum())
    for threshold in (30, 40):
        result[f"terminal_le_neg_{threshold}_count"] = int((terminal <= -threshold).sum())
    return result


def _hwm_audit(records: pd.DataFrame, frames: Mapping[Any, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    output: list[dict[str, Any]] = []
    triggered = records.loc[records.get("research_hwm_signal_date", pd.Series(index=records.index, dtype=object)).notna()]
    validation_errors: list[str] = []
    for row in triggered.to_dict(orient="records"):
        frame = base.portfolio._frame_for_record(row, frames)
        key = str(row.get("pair_id", ""))
        if frame is None:
            validation_errors.append(f"MISSING_FRAME:{key}")
            continue
        entry = pd.Timestamp(row["entry_execution_date"]).normalize()
        signal = pd.Timestamp(row["research_hwm_signal_date"]).normalize()
        held = frame.loc[(frame.index >= entry) & (frame.index <= signal)]
        if held.empty:
            validation_errors.append(f"EMPTY_HWM_HOLDING_PATH:{key}")
            continue
        closes = pd.to_numeric(held["close"], errors="coerce")
        peak = float(closes.max())
        peak_date = closes.loc[closes.eq(peak)].index[0]
        signal_close = float(closes.iloc[-1])
        entry_open = float(row["entry_open"])
        drawdown_pct = (signal_close / peak - 1.0) * 100.0
        hwm_return = (peak / entry_open - 1.0) * 100.0
        signal_return = (signal_close / entry_open - 1.0) * 100.0
        exec_rows = frame.loc[frame.index > signal]
        exec_date = exec_rows.index[0] if not exec_rows.empty else None
        exec_open = float(exec_rows.iloc[0]["open"]) if not exec_rows.empty else None
        actual_return = (exec_open / entry_open - 1.0) * 100.0 if exec_open is not None else None
        applied = bool(row.get("research_hwm_exit_applied"))
        held_count = int(len(held))
        if held_count < 120:
            validation_errors.append(f"HWM_TRIGGER_BEFORE_120_SESSIONS:{key}:{held_count}")
        if drawdown_pct > -20.0 + 1e-9:
            validation_errors.append(f"HWM_TRIGGER_ABOVE_NEG20:{key}:{drawdown_pct}")
        if int(row.get("research_hwm_holding_days") or 0) != held_count:
            validation_errors.append(f"HWM_HOLDING_SESSION_COUNT_MISMATCH:{key}")
        if not np.isclose(peak, float(row["research_hwm_close"]), rtol=0, atol=0.011):
            validation_errors.append(f"HWM_CLOSE_MISMATCH:{key}")
        if str(peak_date.strftime("%Y-%m-%d")) != str(row["research_hwm_peak_date"]):
            validation_errors.append(f"HWM_PEAK_DATE_MISMATCH:{key}")
        if applied:
            if str(row["exit_type"]) != "EXIT_120D_CLOSE_HWM_DRAWDOWN_LE_NEG20":
                validation_errors.append(f"APPLIED_HWM_EXIT_LABEL_MISMATCH:{key}")
            if exec_date is None or str(exec_date.strftime("%Y-%m-%d")) != str(row["exit_execution_date"]):
                validation_errors.append(f"HWM_NEXT_SESSION_EXECUTION_MISMATCH:{key}")
            if actual_return is not None and str(row["trade_status"]) == "REALIZED":
                if not np.isclose(actual_return, float(row["terminal_return"]), rtol=0, atol=0.011):
                    validation_errors.append(f"HWM_NEXT_OPEN_RETURN_MISMATCH:{key}")
        output.append({
            "ticker": str(row["ticker"]).zfill(6),
            "pair_id": key,
            "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"],
            "holding_trading_days": held_count,
            "hwm_peak_date": peak_date.strftime("%Y-%m-%d"),
            "close_hwm": peak,
            "close_hwm_return_from_entry_pct": hwm_return,
            "exit_signal_date": signal.strftime("%Y-%m-%d"),
            "signal_close": signal_close,
            "signal_close_return_from_entry_pct": signal_return,
            "hwm_drawdown_pct": drawdown_pct,
            "next_session_execution_date": exec_date.strftime("%Y-%m-%d") if exec_date is not None else None,
            "next_session_open": exec_open,
            "actual_next_open_return_from_entry_pct": actual_return,
            "candidate_trade_terminal_return_pct": row.get("terminal_return"),
            "applied_to_trade": applied,
            "suppression_reason": row.get("research_hwm_suppression_reason"),
        })
    audit = pd.DataFrame(output)
    return audit, {"trigger_rows": int(len(triggered)), "applied_exit_count": int(triggered.get("research_hwm_exit_applied", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()), "validation_errors": validation_errors, "status": "PASS" if not validation_errors else "FAIL"}


def _keyed_records(frame: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in frame.to_dict(orient="records"):
        key = _entry_key(row)
        if key in result:
            raise RuntimeError(f"DUPLICATE_TICKER_SIGNAL_TRADE_KEY:{key}")
        result[key] = row
    return result


def _has_prior_hwm_exit(records: pd.DataFrame, ticker: str, before_date: str) -> bool:
    exits = records.loc[
        records["ticker"].astype(str).str.zfill(6).eq(ticker)
        & records.get("research_hwm_exit_applied", pd.Series(False, index=records.index)).fillna(False).astype(bool)
    ]
    if exits.empty:
        return False
    return bool((pd.to_datetime(exits["exit_execution_date"], errors="coerce") <= pd.Timestamp(before_date)).any())


def _build_comparisons(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    control_events: pd.DataFrame,
    candidate_events: pd.DataFrame,
    candidate_skipped: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    control_lookup = _keyed_records(control)
    candidate_lookup = _keyed_records(candidate)
    control_actual = _actual_entries(control_events)
    candidate_actual = _actual_entries(candidate_events)
    common_actual = control_actual & candidate_actual
    control_only = control_actual - candidate_actual
    candidate_only = candidate_actual - control_actual
    skipped_keys = {
        (str(row.ticker).zfill(6), str(row.signal_date)[:10])
        for row in candidate_skipped.itertuples(index=False)
        if str(getattr(row, "event_status", "")).startswith("SKIPPED") or "CASH" in str(getattr(row, "skip_reason", ""))
    }

    def classify_control_only(key: tuple[str, str]) -> str:
        if key in candidate_lookup and key in skipped_keys:
            return "CANDIDATE_SIGNAL_CASH_SHORTAGE"
        if key in candidate_lookup:
            return "CANDIDATE_SIGNAL_NOT_EXECUTED_OTHER"
        control_row = control_lookup.get(key, {})
        if _has_prior_hwm_exit(candidate, key[0], str(control_row.get("entry_execution_date", key[1]))):
            return "CANDIDATE_LIFECYCLE_REENTRY_PATH_CHANGED_SIGNAL_ABSENT"
        return "OTHER_UNEXPLAINED_CONTROL_ONLY"

    opportunity_rows: list[dict[str, Any]] = []
    for key in sorted(control_only):
        row = control_lookup.get(key, {})
        opportunity_rows.append({"ticker": key[0], "entry_signal_date": key[1], "set": "CONTROL_ONLY", "cause": classify_control_only(key), **{field: row.get(field) for field in ("terminal_return", "mfe", "mae", "trade_status", "exit_type")}})
    for key in sorted(candidate_only):
        row = candidate_lookup.get(key, {})
        cause = "CANDIDATE_NEW_SIGNAL_AFTER_HWM_REENTRY" if key not in control_lookup and _has_prior_hwm_exit(candidate, key[0], str(row.get("entry_execution_date", key[1]))) else ("CANDIDATE_SIGNAL_NOT_ACTUALLY_ENTERED_BY_CONTROL" if key in control_lookup else "OTHER_CANDIDATE_ONLY")
        opportunity_rows.append({"ticker": key[0], "entry_signal_date": key[1], "set": "CANDIDATE_C_ONLY", "cause": cause, **{field: row.get(field) for field in ("terminal_return", "mfe", "mae", "trade_status", "exit_type")}})
    for key in sorted(common_actual):
        c0 = control_lookup.get(key, {})
        c1 = candidate_lookup.get(key, {})
        opportunity_rows.append({"ticker": key[0], "entry_signal_date": key[1], "set": "COMMON_ACTUAL_ENTRY", "cause": "COMMON", "control_terminal_return": c0.get("terminal_return"), "candidate_terminal_return": c1.get("terminal_return"), "terminal_return_delta_pct": (float(c1["terminal_return"]) - float(c0["terminal_return"])) if pd.notna(c0.get("terminal_return")) and pd.notna(c1.get("terminal_return")) else None, "terminal_return": c1.get("terminal_return"), "mfe": c1.get("mfe"), "mae": c1.get("mae"), "trade_status": c1.get("trade_status"), "exit_type": c1.get("exit_type")})
    opportunity = pd.DataFrame(opportunity_rows)

    comparisons: list[dict[str, Any]] = []
    matched_rows: list[dict[str, Any]] = []
    for key in sorted(set(control_lookup) | set(candidate_lookup)):
        c0 = control_lookup.get(key)
        c1 = candidate_lookup.get(key)
        row = {
            "ticker": key[0], "entry_signal_date": key[1],
            "control_signal_exists": c0 is not None, "candidate_c_signal_exists": c1 is not None,
            "control_actual_entry": key in control_actual, "candidate_c_actual_entry": key in candidate_actual,
            "control_trade_id": c0.get("trade_id") if c0 else None,
            "candidate_c_trade_id": c1.get("trade_id") if c1 else None,
            "control_entry_execution_date": c0.get("entry_execution_date") if c0 else None,
            "candidate_c_entry_execution_date": c1.get("entry_execution_date") if c1 else None,
            "control_exit_type": c0.get("exit_type") if c0 else None,
            "candidate_c_exit_type": c1.get("exit_type") if c1 else None,
            "control_exit_signal_date": c0.get("exit_signal_date") if c0 else None,
            "candidate_c_exit_signal_date": c1.get("exit_signal_date") if c1 else None,
            "control_terminal_return_pct": c0.get("terminal_return") if c0 else None,
            "candidate_c_terminal_return_pct": c1.get("terminal_return") if c1 else None,
            "terminal_return_delta_pct": (float(c1["terminal_return"]) - float(c0["terminal_return"])) if c0 and c1 and pd.notna(c0.get("terminal_return")) and pd.notna(c1.get("terminal_return")) else None,
            "control_mfe_pct": c0.get("mfe") if c0 else None,
            "candidate_c_mfe_pct": c1.get("mfe") if c1 else None,
            "control_mae_pct": c0.get("mae") if c0 else None,
            "candidate_c_mae_pct": c1.get("mae") if c1 else None,
            "candidate_hwm_exit_applied": bool(c1.get("research_hwm_exit_applied")) if c1 else False,
        }
        comparisons.append(row)
        if key in common_actual and c0 and c1:
            delta = float(c1["terminal_return"]) - float(c0["terminal_return"])
            matched_rows.append({
                "ticker": key[0], "entry_signal_date": key[1],
                "control_trade_id": c0.get("trade_id"), "candidate_c_trade_id": c1.get("trade_id"),
                "control_terminal_return_pct": c0.get("terminal_return"),
                "candidate_c_terminal_return_pct": c1.get("terminal_return"),
                "terminal_return_delta_pct": delta,
                "comparison": "IMPROVED" if delta > 0 else "WORSENED" if delta < 0 else "UNCHANGED",
                "control_mfe_pct": c0.get("mfe"), "candidate_c_mfe_pct": c1.get("mfe"),
                "control_mae_pct": c0.get("mae"), "candidate_c_mae_pct": c1.get("mae"),
            })
    comparison_frame = pd.DataFrame(comparisons).sort_values(["ticker", "entry_signal_date"], kind="mergesort").reset_index(drop=True)
    matched_frame = pd.DataFrame(matched_rows).sort_values(["ticker", "entry_signal_date"], kind="mergesort").reset_index(drop=True) if matched_rows else pd.DataFrame()
    if len(matched_frame):
        delta = pd.to_numeric(matched_frame["terminal_return_delta_pct"], errors="coerce")
        common_summary = {
            "n": int(len(matched_frame)),
            "improved_count": int((delta > 0).sum()),
            "worsened_count": int((delta < 0).sum()),
            "unchanged_count": int((delta == 0).sum()),
            "average_terminal_return_delta_pct": float(delta.mean()),
            "median_terminal_return_delta_pct": float(delta.median()),
        }
    else:
        common_summary = {"n": 0, "improved_count": 0, "worsened_count": 0, "unchanged_count": 0, "average_terminal_return_delta_pct": None, "median_terminal_return_delta_pct": None}
    control_only_rows = {key: control_lookup[key] for key in control_only if key in control_lookup}
    candidate_only_rows = {key: candidate_lookup[key] for key in candidate_only if key in candidate_lookup}
    control_only_stats = _entry_set_metrics(control_only, control_lookup)
    candidate_only_stats = _entry_set_metrics(candidate_only, candidate_lookup)
    causes = opportunity.loc[opportunity["set"].eq("CONTROL_ONLY"), "cause"].value_counts().to_dict() if not opportunity.empty else {}
    opportunity_summary = {
        "control_actual_entry_count": len(control_actual),
        "candidate_c_actual_entry_count": len(candidate_actual),
        "common_actual_entry_count": len(common_actual),
        "control_only": {**control_only_stats, "cause_counts": causes},
        "candidate_c_only": candidate_only_stats,
        "common_actual_entry_terminal_delta": common_summary,
        "net_actual_entry_count_change": len(candidate_actual) - len(control_actual),
        "control_only_plus_50_winners": control_only_stats["terminal_ge_pos_50_count"],
        "candidate_c_only_plus_50_winners": candidate_only_stats["terminal_ge_pos_50_count"],
        "net_plus_50_winners": candidate_only_stats["terminal_ge_pos_50_count"] - control_only_stats["terminal_ge_pos_50_count"],
        "control_only_plus_100_winners": control_only_stats["terminal_ge_pos_100_count"],
        "candidate_c_only_plus_100_winners": candidate_only_stats["terminal_ge_pos_100_count"],
        "net_plus_100_winners": candidate_only_stats["terminal_ge_pos_100_count"] - control_only_stats["terminal_ge_pos_100_count"],
    }
    return comparison_frame, opportunity, opportunity_summary, common_summary


def _isolation_checks(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    hwm_audit: pd.DataFrame,
    control_events: pd.DataFrame,
    candidate_events: pd.DataFrame,
) -> dict[str, Any]:
    first_fields = [
        "ticker", "entry_signal_date", "entry_execution_date", "entry_open", "entry_pattern_a_stage",
        "fast_stage", "monthly_regime", "daily_risk", "fast_score", "fast_score_state", "entry_market_cap",
    ]
    control_first = control.sort_values(["ticker", "trade_sequence"], kind="mergesort").groupby("ticker", as_index=False).head(1).reset_index(drop=True)
    candidate_first = candidate.sort_values(["ticker", "trade_sequence"], kind="mergesort").groupby("ticker", as_index=False).head(1).reset_index(drop=True)
    first_entry = base._compare_frames(candidate_first, control_first, first_fields, sort_by=("ticker",))
    c_lookup = _keyed_records(candidate)
    control_lookup = _keyed_records(control)
    shared = sorted(set(c_lookup) & set(control_lookup))
    invariant_fields = [
        "ticker", "entry_signal_date", "entry_execution_date", "entry_open", "entry_pattern_a_stage",
        "fast_stage", "monthly_regime", "daily_risk", "fast_score", "fast_score_state", "entry_market_cap",
        "first_progressed_date", "first_progressed_effective_trading_date", "lifecycle_class",
        "loss_guard_triggered", "loss_guard_signal_date",
    ]
    common_c = pd.DataFrame([c_lookup[key] for key in shared])
    common_control = pd.DataFrame([control_lookup[key] for key in shared])
    common_state = base._compare_frames(common_c, common_control, invariant_fields, sort_by=("ticker", "entry_signal_date")) if shared else {"pass": False, "actual_rows": 0, "expected_rows": 0}
    outcome_fields = ["ticker", "entry_signal_date", "exit_type", "exit_signal_date", "exit_execution_date", "exit_price", "terminal_return", "mfe", "mae", "trade_status"]
    unaffected_keys = [
        key for key in shared
        if not bool(c_lookup[key].get("research_hwm_exit_applied"))
        and not _has_prior_hwm_exit(candidate, key[0], str(c_lookup[key].get("entry_execution_date", key[1])))
    ]
    unaffected_candidate = pd.DataFrame([c_lookup[key] for key in unaffected_keys])
    unaffected_control = pd.DataFrame([control_lookup[key] for key in unaffected_keys])
    unaffected_outcomes = base._compare_frames(
        unaffected_candidate, unaffected_control, outcome_fields,
        sort_by=("ticker", "entry_signal_date"), numeric_atol=1e-9,
    ) if unaffected_keys else {"pass": True, "actual_rows": 0, "expected_rows": 0, "mismatch_count": 0}
    c_hwm = candidate.loc[candidate["exit_type"].astype(str).eq("EXIT_120D_CLOSE_HWM_DRAWDOWN_LE_NEG20")]
    hwm_rows = hwm_audit.loc[hwm_audit["applied_to_trade"].astype(bool)] if not hwm_audit.empty else pd.DataFrame()
    hwm_labels = int(len(c_hwm)) == int(len(hwm_rows)) and bool(c_hwm["exit_signal_date"].astype(str).eq(c_hwm["research_hwm_signal_date"].astype(str)).all())
    direct_hwm_keys = {_entry_key(row) for row in c_hwm.to_dict(orient="records")}
    prior_hwm_violations = []
    for key in set(control_lookup) - set(c_lookup):
        ref = control_lookup[key]
        if not _has_prior_hwm_exit(candidate, key[0], str(ref.get("entry_execution_date", key[1]))):
            prior_hwm_violations.append(key)
    candidate_only_violations = []
    for key in set(c_lookup) - set(control_lookup):
        row = c_lookup[key]
        if not _has_prior_hwm_exit(candidate, key[0], str(row.get("entry_execution_date", key[1]))):
            candidate_only_violations.append(key)
    control_actual = _actual_entries(control_events)
    candidate_actual = _actual_entries(candidate_events)
    changed_actual_without_hwm = []
    for key in control_actual ^ candidate_actual:
        c_row = c_lookup.get(key)
        ref_row = control_lookup.get(key)
        date = (c_row or ref_row or {}).get("entry_execution_date", key[1])
        if not _has_prior_hwm_exit(candidate, key[0], str(date)):
            changed_actual_without_hwm.append(key)
    return {
        "first_entry_signal_and_execution_match_CONTROL": first_entry,
        "common_trade_entry_and_existing_lifecycle_fields_match_CONTROL": common_state,
        "unaffected_common_trade_outcomes_match_CONTROL": unaffected_outcomes,
        "hwm_exit_label_and_audit_count_match": hwm_labels,
        "all_hwm_exit_rows_are_post_120_session_by_audit": bool(hwm_audit.empty or hwm_audit.loc[hwm_audit["applied_to_trade"].astype(bool), "holding_trading_days"].ge(120).all()),
        "all_later_or_missing_signals_trace_to_prior_hwm_reentry": len(prior_hwm_violations) == 0 and len(candidate_only_violations) == 0,
        "control_only_without_prior_hwm_count": len(prior_hwm_violations),
        "candidate_only_without_prior_hwm_count": len(candidate_only_violations),
        "actual_entry_set_changes_without_prior_hwm_count": len(changed_actual_without_hwm),
        "unexplained_control_only_keys": [list(key) for key in sorted(prior_hwm_violations)[:20]],
        "unexplained_candidate_only_keys": [list(key) for key in sorted(candidate_only_violations)[:20]],
        "unexplained_actual_entry_keys": [list(key) for key in sorted(changed_actual_without_hwm)[:20]],
        "status": "PASS" if first_entry.get("pass") and common_state.get("pass") and unaffected_outcomes.get("pass") and hwm_labels and len(prior_hwm_violations) == 0 and len(candidate_only_violations) == 0 and len(changed_actual_without_hwm) == 0 else "FAIL",
    }


def _report(summary: Mapping[str, Any]) -> str:
    c0, c1 = summary["trades"]["CONTROL"], summary["trades"]["Candidate C"]
    p0, p1 = summary["portfolio"]["CONTROL"], summary["portfolio"]["Candidate C"]
    opp = summary["opportunity_cost"]
    severity = "| 레벨 | 개수 | 내용 |\n|---|---:|---|\n| CRITICAL | 0 | 없음 |\n| MAJOR | {major} | {major_text} |\n| MINOR | {minor} | {minor_text} |".format(
        major=0 if summary["status"] == "COMPLETE" else 1,
        major_text="없음" if summary["status"] == "COMPLETE" else "실험 무결성 또는 필수 gate 미확인",
        minor=1,
        minor_text="2026-09-21 original merged PIT bytes 대신 인증 산출물의 survivor projection을 복원",
    )
    trade_keys = (
        "trade_count", "realized_count", "open_count", "realized_win_rate_pct", "terminal_positive_rate_pct",
        "average_terminal_return_pct", "median_terminal_return_pct", "average_realized_return_pct", "median_realized_return_pct",
        "average_holding_trading_days", "median_holding_trading_days", "p25_holding_trading_days", "p75_holding_trading_days",
        "loss_guard_exit_count", "exit_3_count", "exit_4_count", "hwm_120d_exit_count", "progressed_count", "progressed_rate_pct",
        "terminal_ge_pos_20_count", "terminal_ge_pos_50_count", "terminal_ge_pos_100_count",
        "mfe_ge_pos_20_count", "mfe_ge_pos_50_count", "mfe_ge_pos_100_count",
        "terminal_le_neg_20_count", "terminal_le_neg_30_count", "terminal_le_neg_40_count", "terminal_le_neg_50_count", "terminal_le_neg_60_count",
        "realized_le_neg_20_count", "realized_le_neg_30_count", "realized_le_neg_40_count", "realized_le_neg_50_count", "realized_le_neg_60_count",
        "mae_le_neg_20_count", "mae_le_neg_30_count", "mae_le_neg_40_count",
    )
    trade_table = "\n".join(f"| {key} | {c0.get(key)} | {c1.get(key)} |" for key in trade_keys)
    portfolio_keys = (
        "final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count", "realized_trade_count",
        "open_at_effective_cutoff_count", "average_holding_trading_days", "median_holding_trading_days",
        "turnover_krw", "turnover_multiple", "average_capital_utilization_pct", "average_cash_ratio_pct",
        "average_concurrent_positions", "maximum_concurrent_positions", "cash_shortage_skipped_entries",
        "total_buy_notional_krw", "total_sell_notional_krw", "total_commissions_krw", "total_sell_tax_krw",
        "slippage_impact_krw", "cash_conservation_pass", "unresolved_count",
        "realized_return_ge_pos_50_count", "realized_return_ge_pos_100_count",
        "realized_return_le_neg_30_count", "realized_return_le_neg_40_count", "realized_return_le_neg_50_count", "realized_return_le_neg_60_count",
    )
    portfolio_table = "\n".join(f"| {key} | {p0.get(key)} | {p1.get(key)} |" for key in portfolio_keys)
    only_table = "\n".join(
        f"| {name} | {value.get('n')} | {value.get('average_terminal_return_pct')} | {value.get('median_terminal_return_pct')} | {value.get('positive_count')} / {value.get('positive_rate_pct')}% | {value.get('terminal_ge_pos_50_count')} | {value.get('terminal_ge_pos_100_count')} | {value.get('terminal_le_neg_30_count')} / {value.get('terminal_le_neg_40_count')} | {value.get('average_mfe_pct')} / {value.get('average_mae_pct')} |"
        for name, value in (("CONTROL only", opp["control_only"]), ("Candidate C only", opp["candidate_c_only"]))
    )
    gate = summary["success_gates"]
    return f"""{severity}

# FAST Core V2 P3-2 — 120D + HWM Exit Experiment V01

## 1. 최종 토큰

`{summary['final_token']}`

## 2. CONTROL frozen authority 확인

- 선행 frozen replay token `{summary['control_authority']['source_final_token']}`; P3-2 CONTROL 입력 5개 파일은 현재 HEAD에 저장된 바이트와 SHA-256이 모두 일치해.
- 기간 2022-01-03~2026-08-31, execution support 2026-09-01, survivor identities 2,539개, MKTCAP gate ≥ ₩1조.
- 초기자본 ₩200,000,000, 종목당 매수예산 ₩5,000,000, position cap 없음. 수수료/슬리피지/매도세/T+1 규칙은 저장된 P3-2 CONTROL 설정을 그대로 사용했어.
- CONTROL 2,539종목 strategy replay는 재실행하지 않았어. baseline source commit `{summary['control_authority']['source_commit']}`.
- frozen effective PIT SHA `{summary['control_authority']['historical_pit_sha256']}`, calendar SHA `{summary['control_authority']['calendar_sha256']}`, survivor projection SHA `{summary['control_authority']['survivor_projection_sha256']}`.

## 3. Candidate C exact rule

- 진입, re-entry, -15% pre-PROGRESSED Loss Guard, Exit 3 및 Exit 4는 certified V2 simulator의 AST clone에서 그대로 유지했어. canonical source hash `{summary['integrity']['canonical_strategy_sha256']}`이고 production source는 수정하지 않았어.
- entry_execution_date부터 daily KRX session을 1일로 세어 120번째 completed session EOD부터, 진입 후 completed close의 누적 HWM 대비 종가 drawdown이 -20% 이하일 때 exit signal을 냈어. 다음 local trading session open에 체결했어.
- 기존 signal이 더 이르면 기존 signal, 같은 날이면 기존 V2 exit를 유지하도록 우선순위를 구현했어.

## 4. Strategy metrics

| 지표 | CONTROL | Candidate C |
|---|---:|---:|
{trade_table}

## 5. Holding period / MFE / MAE

위 거래 표에 평균·중앙 및 P25/P75 보유 거래일, MFE/MAE threshold count를 함께 기록했어. 거래일은 종목의 Repository V2 completed daily session 기준이야.

## 6. Large winners / large losses

- terminal +20/+50/+100, realized -20/-30/-40/-50/-60, MAE -20/-30/-40의 거래 수는 위 표와 `summary.json`에 있어.
- Candidate C HWM trigger rows `{summary['hwm_audit']['trigger_rows']}`, 실제 적용된 신규 exit `{summary['hwm_audit']['applied_exit_count']}`. 신규 exit 당시 120-session minimum 및 close-based HWM -20% 조건 validation `{summary['hwm_audit']['status']}`.
- 상세 신호일/종가 HWM/진입 대비 수익/실행일 next open/실제 next-open 수익은 `hwm_exit_audit.csv`에 있어.

## 7. Realistic portfolio metrics

| 지표 | CONTROL | Candidate C |
|---|---:|---:|
{portfolio_table}

## 8. Lost/gained opportunity analysis

| 실제 진입 집합 | n | 평균 terminal | 중앙 terminal | positive count / rate | +50 | +100 | -30 / -40 | 평균 MFE / MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{only_table}

- 실제 진입 공통 {opp['common_actual_entry_count']}건; CONTROL-only {opp['control_only']['n']}건; Candidate C-only {opp['candidate_c_only']['n']}건.
- CONTROL-only 원인: `{json.dumps(opp['control_only'].get('cause_counts', {}), ensure_ascii=False)}`.
- +50 winner lost/gained/net: {opp['control_only_plus_50_winners']} / {opp['candidate_c_only_plus_50_winners']} / {opp['net_plus_50_winners']}; +100: {opp['control_only_plus_100_winners']} / {opp['candidate_c_only_plus_100_winners']} / {opp['net_plus_100_winners']}.
- 실제 진입 순변화 {opp['net_actual_entry_count_change']}; turnover 변화 ₩{p1.get('turnover_krw', 0)-p0.get('turnover_krw', 0):,.0f} ({p0.get('turnover_multiple')}x → {p1.get('turnover_multiple')}x); portfolio 평균 보유일 {p0.get('average_holding_trading_days')} → {p1.get('average_holding_trading_days')}.

## 9. Common actual-entry direct comparison

- 공통 실제 진입 terminal return delta: n={summary['common_entry_delta']['n']}, improved={summary['common_entry_delta']['improved_count']}, worsened={summary['common_entry_delta']['worsened_count']}, unchanged={summary['common_entry_delta']['unchanged_count']}, 평균 delta={summary['common_entry_delta']['average_terminal_return_delta_pct']}, 중앙 delta={summary['common_entry_delta']['median_terminal_return_delta_pct']} 퍼센트포인트.
- 거래별 비교는 `trade_comparison.csv`, 기회 집합과 cause는 `opportunity_cost_analysis.csv`에 저장했어.

## 10. Success gate / V2 recommendation

| 필수 기준 | Candidate C | 통과 |
|---|---:|---|
| 실현 승률 ≥ 50% | {c1.get('realized_win_rate_pct')}% | {gate.get('win_rate')} |
| 중앙 terminal ≥ +1% | {c1.get('median_terminal_return_pct')}% | {gate.get('median_terminal')} |
| 평균 terminal > CONTROL | {c1.get('average_terminal_return_pct')}% vs {c0.get('average_terminal_return_pct')}% | {gate.get('average_terminal')} |
| portfolio MDD > -30% | {p1.get('mdd_pct')}% | {gate.get('portfolio_mdd')} |
| 평균 terminal > +10% (strong preference) | {c1.get('average_terminal_return_pct')}% | {gate.get('average_terminal_gt_10')} |
| 전체 mandatory gate | — | {gate.get('all_pass')} |

V2 official strategy 변경 추천: `{summary['strategy_change_recommended']}`. 필수 gate 실패 시 5-window 확장·threshold sweep·후속 자동실험은 하지 않아.

## 11. Tests / integrity

{json.dumps(summary['tests'], ensure_ascii=False, indent=2)}

## 12. Git status

- branch `{summary['git']['branch']}`, HEAD `{summary['git']['head']}`, origin/main `{summary['git']['origin_main']}`.
- tracked source changes {summary['git']['tracked_source_changes']}; 이번 작업 자동 commit/push 안 했어.
- 기존 unrelated untracked 산출물은 수정하거나 stage하지 않았어.
"""


def _run(mode: str, smoke_tickers: int) -> dict[str, Any]:
    allowed = {"run_120d_hwm_experiment.py", "preflight.json", "smoke.json", "failure.json"}
    existing = {path.name for path in OUT_DIR.iterdir() if path.is_file()}
    _require(not (existing - allowed), "REFUSING_TO_OVERWRITE_CANDIDATE_C_OUTPUTS")
    control_info = _verify_control_inputs()
    run, gate, universe, frozen = base._load_frozen_context()
    tickers = sorted(run.segments_by_ticker)
    _require(len(tickers) == 2539, "FROZEN_CANDIDATE_UNIVERSE_COUNT_MISMATCH")
    _require(frozen.get("historical_pit_sha256") == control_info["historical_pit_sha256"], "CANDIDATE_FROZEN_PIT_DIFFERS_FROM_CONTROL")
    _require(frozen.get("calendar_sha256") == control_info["calendar_sha256"], "CANDIDATE_FROZEN_CALENDAR_DIFFERS_FROM_CONTROL")
    production_runner_hash = _sha256(ROOT / "scripts/run_p3_2_realistic_portfolio_v01.py")
    _require(production_runner_hash == base.EXPECTED_RUNNER_SHA256, "PRODUCTION_P3_RUNNER_CHANGED")
    preflight = {
        "status": "PASS", "mode": mode, "control_authority": control_info,
        "candidate_frozen_authority": frozen, "survivor_ticker_count": len(tickers),
        "workers": WORKERS, "latest_authority_dependency": False,
        "network_or_new_price_calls": 0,
        "canonical_strategy_sha256": _sha256(base.SOURCE_PATH),
        "production_runner_sha256": production_runner_hash,
        "candidate_strategy_id": CANDIDATE_STRATEGY_ID,
    }
    _write_json(OUT_DIR / "preflight.json", preflight)
    if mode == "preflight":
        return {"status": "PREFLIGHT_PASS", "preflight": preflight}

    control = pd.read_csv(BASE_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
    if mode == "smoke":
        candidates = control.copy()
        candidates["holding_days"] = pd.to_numeric(candidates["holding_days"], errors="coerce")
        candidates["peak_giveback"] = pd.to_numeric(candidates["peak_giveback"], errors="coerce")
        shortlist = candidates.loc[candidates["holding_days"].ge(120)].sort_values(["peak_giveback", "holding_days"], ascending=False)
        selected = list(dict.fromkeys(shortlist["ticker"].astype(str).str.zfill(6).tolist()))[:smoke_tickers]
        _require(bool(selected), "HWM_SMOKE_TICKERS_NOT_FOUND")
        outcomes, errors, elapsed = _run_candidate(run, selected)
        records = _records(outcomes)
        frames = base._frames(outcomes)
        audit, audit_checks = _hwm_audit(records, frames)
        control_selected = control.loc[control["ticker"].astype(str).str.zfill(6).isin(selected)].copy()
        empty_events = pd.DataFrame(columns=["ticker", "signal_date", "event_type", "event_status"])
        isolation = _isolation_checks(control_selected, records, audit, empty_events, empty_events)
        result = {
            "mode": "smoke", "status": "CHECK_REQUIRED" if errors or audit_checks["validation_errors"] or isolation["status"] != "PASS" else "PASS",
            "selected_tickers": selected, "strategy_rows": int(len(records)), "worker_errors": errors[:20],
            "elapsed_seconds": elapsed, "hwm_audit": audit_checks, "isolation_checks": isolation,
            "hwm_exit_types": records["exit_type"].value_counts().to_dict() if not records.empty else {},
            "first_entries": records.sort_values(["ticker", "trade_sequence"]).groupby("ticker", as_index=False).head(1)[["ticker", "entry_signal_date", "entry_execution_date", "entry_open"]].to_dict(orient="records") if not records.empty else [],
        }
        _write_json(OUT_DIR / "smoke.json", result)
        _require(result["status"] == "PASS", "CANDIDATE_C_SMOKE_VALIDATION_FAILED")
        return result

    _require(mode == "full", "UNSUPPORTED_MODE")
    _require(smoke_tickers == 0, "FULL_MODE_SMOKE_ARGUMENT_MISMATCH")
    control_records = pd.read_csv(BASE_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
    control_events = pd.read_csv(BASE_DIR / "control_portfolio_events.csv", dtype={"ticker": str})
    control_equity = pd.read_csv(BASE_DIR / "control_daily_equity.csv")
    control_summary = json.loads((BASE_DIR / "summary.json").read_text(encoding="utf-8"))
    control_portfolio = control_summary["portfolio"]["CONTROL"]

    started = time.perf_counter()
    outcomes, worker_errors, candidate_seconds = _run_candidate(run, tickers)
    candidate = _records(outcomes)
    frames = base._frames(outcomes)
    gate.audit_frame().to_csv(OUT_DIR / "candidate_c_pit_mcap_audit.csv", index=False)
    candidate.to_csv(OUT_DIR / "candidate_c_strategy_trades.csv", index=False)
    _require(not worker_errors, "CANDIDATE_C_WORKER_ERRORS:" + json.dumps(worker_errors[:20]))
    _require(not candidate.empty, "CANDIDATE_C_STRATEGY_LEDGER_EMPTY")

    hwm_audit, hwm_checks = _hwm_audit(candidate, frames)
    hwm_audit.to_csv(OUT_DIR / "hwm_exit_audit.csv", index=False)
    _require(hwm_checks["status"] == "PASS", "CANDIDATE_C_HWM_AUDIT_FAILED:" + json.dumps(hwm_checks.get("validation_errors", [])[:20]))

    candidate_replay = base._portfolio_replay(candidate, frames, run, CANDIDATE_STRATEGY_ID)
    pd.DataFrame(candidate_replay["events"]).to_csv(OUT_DIR / "candidate_c_portfolio_events.csv", index=False)
    pd.DataFrame(candidate_replay["daily_equity"]).to_csv(OUT_DIR / "candidate_c_daily_equity.csv", index=False)
    pd.DataFrame(candidate_replay["skipped"]).to_csv(OUT_DIR / "candidate_c_skipped.csv", index=False)
    pd.DataFrame(candidate_replay["valuation_gap_audit"]).to_csv(OUT_DIR / "candidate_c_valuation_carry_audit.csv", index=False)
    _require(bool(candidate_replay["metrics"].get("cash_conservation_pass")), "CANDIDATE_C_CASH_CONSERVATION_FAILED")
    _require(int(candidate_replay["metrics"].get("unresolved_count", -1)) == 0, "CANDIDATE_C_UNRESOLVED_POSITIONS")
    _require(len(candidate_replay["daily_equity"]) == 1140, "CANDIDATE_C_EQUITY_CURVE_ROW_COUNT_MISMATCH")
    candidate_mcap = gate.audit_frame()
    _require(int(candidate_mcap.get("status", pd.Series(dtype=object)).astype(str).eq("UNRESOLVED").sum()) == 0, "CANDIDATE_C_MCAP_UNRESOLVED")

    control_first = control_records.sort_values(["ticker", "trade_sequence"], kind="mergesort").groupby("ticker", as_index=False).head(1)
    candidate_first = candidate.sort_values(["ticker", "trade_sequence"], kind="mergesort").groupby("ticker", as_index=False).head(1)
    first_fields = ["ticker", "entry_signal_date", "entry_execution_date", "entry_open", "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk", "fast_score", "fast_score_state", "entry_market_cap"]
    first_entry_check = base._compare_frames(candidate_first, control_first, first_fields, sort_by=("ticker",))
    _require(first_entry_check["pass"], "CANDIDATE_C_FIRST_ENTRY_DIFFERS_FROM_CONTROL")
    comparison, opportunity, opportunity_summary, common_delta = _build_comparisons(
        control_records, candidate, control_events, pd.DataFrame(candidate_replay["events"]), pd.DataFrame(candidate_replay["skipped"])
    )
    comparison.to_csv(OUT_DIR / "trade_comparison.csv", index=False)
    opportunity.to_csv(OUT_DIR / "opportunity_cost_analysis.csv", index=False)
    isolation = _isolation_checks(control_records, candidate, hwm_audit, control_events, pd.DataFrame(candidate_replay["events"]))
    _require(isolation["status"] == "PASS", "CANDIDATE_C_ISOLATION_FAILED:" + json.dumps(isolation, ensure_ascii=False))

    control_trade_metrics = _trade_metrics(control_records)
    candidate_trade_metrics = _trade_metrics(candidate)
    candidate_portfolio_metrics = dict(candidate_replay["metrics"])
    candidate_portfolio_metrics["equity_curve_rows"] = len(candidate_replay["daily_equity"])
    carry_rows = base.engine._classify_carries(candidate_replay["valuation_gap_audit"])
    carry_rows.to_csv(OUT_DIR / "valuation_carry_classification.csv", index=False)
    carry_summary = {
        "rows": int(len(carry_rows)),
        "unclassified": int(carry_rows.get("classification_status", pd.Series(dtype=object)).astype(str).eq("UNCLASSIFIED").sum()),
        "status_counts": carry_rows.get("classification_status", pd.Series(dtype=object)).value_counts().to_dict(),
    }
    _require(carry_summary["unclassified"] == 0, "CANDIDATE_C_UNCLASSIFIED_VALUATION_CARRY")

    c = candidate_trade_metrics
    p = candidate_portfolio_metrics
    gates = {
        "win_rate": c.get("realized_win_rate_pct") is not None and c["realized_win_rate_pct"] >= 50,
        "median_terminal": c.get("median_terminal_return_pct") is not None and c["median_terminal_return_pct"] >= 1,
        "average_terminal": c.get("average_terminal_return_pct") is not None and c["average_terminal_return_pct"] > control_trade_metrics["average_terminal_return_pct"],
        "portfolio_mdd": p.get("mdd_pct") is not None and p["mdd_pct"] > -30,
    }
    gates["average_terminal_gt_10"] = c.get("average_terminal_return_pct") is not None and c["average_terminal_return_pct"] > 10
    gates["all_pass"] = all(gates[key] for key in ("win_rate", "median_terminal", "average_terminal", "portfolio_mdd"))
    strategy_change_recommended = bool(gates["all_pass"])

    current_sha = _sha256(base.SOURCE_PATH)
    _require(current_sha == control_summary["provenance"]["strategy_source_sha256"], "CANONICAL_STRATEGY_CHANGED_DURING_EXPERIMENT")
    _require(_sha256(ROOT / "scripts/run_p3_2_realistic_portfolio_v01.py") == control_summary["provenance"]["official_runner_sha256"], "PRODUCTION_RUNNER_CHANGED_DURING_EXPERIMENT")
    latest_guard_source = __import__("scripts.run_p3_2_realistic_portfolio_v01", fromlist=["_load_survivor_context"])
    loader_source = __import__("inspect").getsource(latest_guard_source._load_survivor_context)
    production_guard = all(token in loader_source for token in ("load_rolling_authority(ROLLING_DIR)", "validate_merged_authority_coherence(manifest, ROLLING_DIR)", "as_of != manifest.merged_pit_frontier"))
    _require(production_guard, "PRODUCTION_DAILY_UPDATE_AUTHORITY_GUARD_CHANGED")
    tests = {
        "frozen_control_authority_and_file_hashes": "PASS",
        "control_2539_strategy_replay_rerun": "NOT_RUN_BY_DESIGN",
        "candidate_c_frozen_historical_replay": "PASS",
        "candidate_c_first_entry_parity": "PASS" if first_entry_check["pass"] else "FAIL",
        "candidate_c_pre_hwm_state_and_lifecycle_parity": "PASS" if isolation["common_trade_entry_and_existing_lifecycle_fields_match_CONTROL"]["pass"] else "FAIL",
        "candidate_c_hwm_120_completed_sessions_close_only": hwm_checks["status"],
        "candidate_c_reentry_changes_trace_to_hwm_exit": "PASS" if isolation["all_later_or_missing_signals_trace_to_prior_hwm_reentry"] else "FAIL",
        "cash_conservation": "PASS" if p.get("cash_conservation_pass") else "FAIL",
        "unresolved_positions": int(p.get("unresolved_count", -1)),
        "unresolved_mcap": int(candidate_mcap.get("status", pd.Series(dtype=object)).astype(str).eq("UNRESOLVED").sum()),
        "valuation_carry_unclassified": carry_summary["unclassified"],
        "production_daily_update_authority_path_unchanged": "PASS",
        "latest_authority_or_network_dependency": "NONE",
        "network_calls_or_new_prices": 0,
        "worker_errors": len(worker_errors),
    }
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    git_remote = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    git_status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True)
    own_rel = OUT_DIR.relative_to(ROOT).as_posix()
    tracked_source_changes = int(bool(subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py", "scripts/run_p3_2_realistic_portfolio_v01.py"], cwd=ROOT, text=True).strip()))
    required_integrity_pass = (
        first_entry_check["pass"] and isolation["status"] == "PASS" and hwm_checks["status"] == "PASS"
        and p.get("cash_conservation_pass") and p.get("unresolved_count") == 0
        and carry_summary["unclassified"] == 0 and not worker_errors and not tracked_source_changes
    )
    final_token = FINAL_TOKEN if required_integrity_pass else CHECK_TOKEN
    summary = {
        "work_id": "FAST_CORE_V2_P3_2_120D_HWM_EXIT_EXPERIMENT_V01",
        "status": "COMPLETE" if final_token == FINAL_TOKEN else "CHECK_REQUIRED",
        "final_token": final_token,
        "severity": [["CRITICAL", 0, "없음"], ["MAJOR", 0 if required_integrity_pass else 1, "없음" if required_integrity_pass else "integrity 또는 replay gate 확인 필요"], ["MINOR", 1, "2026-09-21 original merged PIT bytes 대신 인증 산출물의 exact survivor projection 사용"]],
        "control_authority": control_info,
        "frozen_authority": frozen,
        "candidate_rule": {
            "entry_and_existing_exit_rules": "certified V2 clone; unchanged",
            "hwm_start": "120th KRX daily session including entry_execution_date",
            "hwm_value": "highest completed daily close since entry, including signal-day close",
            "trigger": "signal_day_close / close_hwm - 1 <= -0.20",
            "execution": "next local KRX trading session open",
            "same_day_priority": "existing V2 exit before new HWM exit",
        },
        "integrity": {"canonical_strategy_sha256": current_sha, "production_runner_sha256": _sha256(ROOT / "scripts/run_p3_2_realistic_portfolio_v01.py"), "tracked_source_changes": tracked_source_changes},
        "trades": {"CONTROL": control_trade_metrics, "Candidate C": candidate_trade_metrics},
        "portfolio": {"CONTROL": control_portfolio, "Candidate C": candidate_portfolio_metrics},
        "candidate_hwm_signal_count": hwm_checks["trigger_rows"],
        "hwm_audit": hwm_checks,
        "trade_opportunity_sets": opportunity_summary,
        "opportunity_cost": opportunity_summary,
        "common_entry_delta": common_delta,
        "candidate_first_entry_parity": first_entry_check,
        "candidate_isolation": isolation,
        "success_gates": gates,
        "strategy_change_recommended": strategy_change_recommended,
        "tests": tests,
        "valuation_carry_classification": carry_summary,
        "elapsed_seconds": {"candidate_c_strategy_replay": candidate_seconds, "total": time.perf_counter() - started},
        "network_calls_or_new_prices": 0,
        "git": {
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
            "head": git_head, "origin_main": git_remote, "head_equals_origin_main": git_head == git_remote,
            "tracked_source_changes": tracked_source_changes, "commit_or_push": False,
            "working_tree_status": git_status,
            "this_artifact_directory": own_rel,
        },
        "files_created": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(OUT_DIR / "summary.json", summary)
    (OUT_DIR / "report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "smoke", "full"), required=True)
    parser.add_argument("--smoke-tickers", type=int, default=4)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = _run(args.mode, args.smoke_tickers)
        result.setdefault("elapsed_seconds", round(time.perf_counter() - started, 3))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    except BaseException as exc:
        failure = {
            "status": "CHECK_REQUIRED", "final_token": CHECK_TOKEN,
            "error_type": type(exc).__name__, "error": str(exc),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "automatic_rerun": False,
        }
        if OUT_DIR.exists():
            _write_json(OUT_DIR / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
        raise


if __name__ == "__main__":
    main()
