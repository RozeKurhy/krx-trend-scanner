#!/usr/bin/env python3
"""Fresh, offline P2-1 trade-level replay for CONTROL, MA60, and alignment."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
SHARED_PATH = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py"
PIT_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
SURVIVOR_PATH = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/survivor_universe_audit.csv"
WORK_ID = "FAST_CORE_V2_P2_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01"
FINAL_TOKEN = WORK_ID + "_PASS"
CHECK_TOKEN = WORK_ID + "_CHECK_REQUIRED"
WINDOW_ID = "P2-1"
WINDOW = {"effective_start": "2021-01-04", "effective_end": "2025-05-30", "execution_support": "2025-06-02"}
WORKERS = 10
STRATEGIES = {
    "CONTROL": ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "p2_1_control_trades.csv"),
    "MA60": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER", "p2_1_ma60_trades.csv"),
    "ALIGNMENT": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT", "p2_1_alignment_trades.csv"),
}
STAGE = "STARTUP"
REPLAY_STARTED = False


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_clean_tracked() -> bool:
    return all(
        subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet"))
    )


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(json_value(payload), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def load_shared():
    spec = importlib.util.spec_from_file_location("p2_1_shared_simple_replay", SHARED_PATH)
    require(spec is not None and spec.loader is not None, "SHARED_REPLAY_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUT = OUT
    module.WORKERS = WORKERS
    return module


def source_paths(module: Any) -> dict[str, Path]:
    paths = {
        "p2_1_runner": ROOT / "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        "canonical_strategy": ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "ma60_helper": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_entry_filter_backtest_v01/run_monthly_ma_entry_filter_backtest.py",
        "alignment_helper": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_bullish_alignment_backtest_v01/run_bullish_alignment_backtest.py",
        "exact_mcap_gate": ROOT / "scripts/run_p2_1_realistic_portfolio_v01.py",
        "standard_window_resolver": ROOT / "src/trend_scanner/backtest/standard_windows.py",
        "repository_v2_loader": ROOT / "src/trend_scanner/data/repository_v2_loader.py",
        "frozen_authority_loader": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01/run_frozen_replay.py",
        "shared_replay_helper": SHARED_PATH,
        "p2_2_authority_manifest": PIT_DIR / "p2_2_identity_authority_extension_manifest.json",
        "frozen_merged_pit": PIT_DIR / "merged_pit_intervals.json",
        "frozen_merged_calendar": PIT_DIR / "merged_trading_calendar.json",
        "survivor_identity_roster_authority": SURVIVOR_PATH,
    }
    for name, path in (
        ("lifecycle_settlement_evidence", module.STRATEGY.LIFECYCLE_SETTLEMENT_EVIDENCE_PATH),
        ("lifecycle_event_evidence_v02", module.STRATEGY.LIFECYCLE_EVENT_EVIDENCE_V02_PATH),
    ):
        if path.is_file():
            paths[name] = path
    return paths


def preflight(module: Any) -> tuple[dict[str, Any], Any, Any, Any, Any, Any, frozenset[Any]]:
    allowed = {Path(__file__).name, "__pycache__"}
    unexpected = sorted(p.name for p in OUT.iterdir() if p.name not in allowed)
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")
    require(git_clean_tracked(), "TRACKED_WORKTREE_OR_INDEX_NOT_CLEAN")
    source_hashes = {}
    for name, path in source_paths(module).items():
        require(path.is_file(), f"INPUT_MISSING:{name}:{path}")
        source_hashes[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        require(committed.returncode == 0 and committed.stdout == path.read_bytes(), f"INPUT_HASH_DIFFERS_FROM_HEAD:{name}")
    source_hashes["p2_1_execution_script"] = {
        "path": Path(__file__).relative_to(ROOT).as_posix(),
        "sha256": sha256(Path(__file__)),
        "tracked_at_start": False,
    }
    manifest_path = PIT_DIR / "p2_2_identity_authority_extension_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS", "FROZEN_AUTHORITY_MANIFEST_NOT_PASS")
    require(sha256(PIT_DIR / "merged_trading_calendar.json") == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")
    network = module.network_guard()
    try:
        frozen, base_run, base_gate, universe, authority, survivors = module.load_frozen_context()
        run, scoped_gate, window_context = module.context_for_window(base_run, base_gate, survivors, WINDOW_ID)
        require(len(survivors) == 2539, "FROZEN_SURVIVOR_IDENTITY_COUNT_MISMATCH")
        require(window_context["effective_start"] == WINDOW["effective_start"], "P2_1_START_MISMATCH")
        require(window_context["effective_end"] == WINDOW["effective_end"], "P2_1_CUTOFF_MISMATCH")
        require(window_context["execution_support"] == WINDOW["execution_support"], "P2_1_SUPPORT_MISMATCH")
        require(window_context["survivor_identity_count"] == len(survivors), "P2_1_SURVIVOR_CONTEXT_MISMATCH")
        require(window_context["common_pit_segment_count"] == sum(map(len, run.segments_by_ticker.values())), "P2_1_SEGMENT_CONTEXT_MISMATCH")
        require(network[2]["calls"] == 0, "NETWORK_CALLS_DURING_PREFLIGHT")
    finally:
        module.restore_network_guard(network)
    identity_keys = {
        (segment.ticker, segment.isu_cd, segment.market)
        for rows in run.segments_by_ticker.values()
        for segment in rows
    }
    pre = {
        "status": "PASS",
        "work_id": WORK_ID,
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "tracked_worktree_clean": True,
        "window_id": WINDOW_ID,
        **window_context,
        "workers": WORKERS,
        "strategy_ids": {name: details[0] for name, details in STRATEGIES.items()},
        "survivor_identity_roster_count": len(survivors),
        "p2_1_identity_key_count": len(identity_keys),
        "p2_1_identity_segment_count": sum(map(len, run.segments_by_ticker.values())),
        "frozen_authority": json_value(authority),
        "frozen_manifest_sha256": sha256(manifest_path),
        "frozen_pit_sha256": sha256(base_run.authority.pit_path),
        "frozen_calendar_sha256": sha256(PIT_DIR / "merged_trading_calendar.json"),
        "survivor_identity_roster_sha256": sha256(SURVIVOR_PATH),
        "input_source_hashes": source_hashes,
        "price_source": "local Repository V2 adjusted/raw stores; MA inputs from locally hash-verified adjusted stock partitions",
        "market_cap_source": "local exact-date KRX raw Stock Daily MKTCAP snapshots; each snapshot validated against its manifest and hashes",
        "cost_contract": {
            "buy_commission_rate": module.COMM_RATE,
            "sell_commission_rate": module.COMM_RATE,
            "buy_slippage_rate": module.SLIP_RATE,
            "sell_slippage_rate": module.SLIP_RATE,
            "transaction_tax_in_returns": False,
        },
        "result_reuse": {
            "previous_p2_1_performance": False,
            "p1_performance": False,
            "p3_2_performance": False,
            "frozen_pit_calendar_reused_as_authority": True,
            "frozen_survivor_identity_roster_reused_as_authority": True,
        },
        "network_calls": 0,
    }
    return pre, frozen, base_run, base_gate, universe, authority, survivors


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    value = frame[column]
    if pd.api.types.is_bool_dtype(value):
        return value.fillna(False).astype(bool)
    return value.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def candidate_audit_check(name: str, audit_path: Path, trades: pd.DataFrame) -> dict[str, Any]:
    audit = pd.read_csv(audit_path, dtype={"ticker": str})
    require("candidate_signal_accepted" in audit.columns, f"{name}_AUDIT_ACCEPTANCE_FIELD_MISSING")
    require("entry_executable_within_cutoff" in audit.columns, f"{name}_AUDIT_EXECUTION_FIELD_MISSING")
    accepted = bool_series(audit, "candidate_signal_accepted") & bool_series(audit, "entry_executable_within_cutoff")
    if not trades.empty:
        require("ticker" in trades.columns and "entry_signal_date" in trades.columns, f"{name}_TRADE_SIGNAL_KEY_MISSING")
        signal_keys = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date"]
        require(all(col in trades.columns for col in signal_keys), f"{name}_TRADE_IDENTITY_KEY_MISSING")
        for frame in (audit, trades):
            frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
            frame["entry_signal_date"] = frame["entry_signal_date"].astype(str)
        ledger_keys = trades[signal_keys].astype(str)
        audit_keys = audit.loc[accepted, signal_keys].astype(str)
        require(not ledger_keys.duplicated().any(), f"{name}_DUPLICATE_TRADE_SIGNAL_KEY")
        require(not audit_keys.duplicated().any(), f"{name}_DUPLICATE_ACCEPTED_SIGNAL_KEY")
        require(
            ledger_keys.sort_values(signal_keys).reset_index(drop=True).equals(
                audit_keys.sort_values(signal_keys).reset_index(drop=True)
            ),
            f"{name}_ACCEPTED_SIGNAL_TRADE_PARITY_MISMATCH",
        )
    require(int(accepted.sum()) == len(trades), f"{name}_ACCEPTED_SIGNAL_COUNT_MISMATCH")
    pass_col = "ma_filter_pass" if name == "MA60" else "alignment_filter_pass"
    if name == "MA60":
        require({"ma_available", "monthly_ma", "signal_day_close", pass_col}.issubset(audit.columns), "MA60_AUDIT_FILTER_FIELDS_MISSING")
        available = bool_series(audit, "ma_available")
        passed = bool_series(audit, pass_col)
        ma = pd.to_numeric(audit["monthly_ma"], errors="coerce")
        close = pd.to_numeric(audit["signal_day_close"], errors="coerce")
        require(not (passed & ~available).any(), "MA60_UNAVAILABLE_NOT_FAIL_CLOSED")
        require(not (passed & (ma.isna() | close.isna() | close.le(ma))).any(), "MA60_FILTER_FORMULA_MISMATCH")
        candidate_pass = available & ma.notna() & close.notna() & close.gt(ma)
        require(np.array_equal(passed.to_numpy(), candidate_pass.to_numpy()), "MA60_FILTER_DECISION_MISMATCH")
    else:
        required = {"ma20_available", "ma60_available", "ma20_value", "ma60_value", "signal_day_close", pass_col}
        require(required.issubset(audit.columns), "ALIGNMENT_AUDIT_FILTER_FIELDS_MISSING")
        a20, a60 = bool_series(audit, "ma20_available"), bool_series(audit, "ma60_available")
        ma20 = pd.to_numeric(audit["ma20_value"], errors="coerce")
        ma60 = pd.to_numeric(audit["ma60_value"], errors="coerce")
        close = pd.to_numeric(audit["signal_day_close"], errors="coerce")
        passed = bool_series(audit, pass_col)
        expected = a20 & a60 & ma20.notna() & ma60.notna() & close.notna() & close.gt(ma20) & ma20.gt(ma60)
        require(np.array_equal(passed.to_numpy(), expected.to_numpy()), "ALIGNMENT_FILTER_FORMULA_OR_FAIL_CLOSED_MISMATCH")
    if len(audit):
        signal_month = pd.PeriodIndex(audit["signal_month"].astype(str), freq="M")
        ma_month = pd.PeriodIndex(audit["ma_last_completed_month"].astype(str), freq="M")
        require(bool((ma_month == signal_month - 1).all()), f"{name}_CURRENT_OR_FUTURE_MONTH_USED")
        require(not (accepted & ~bool_series(audit, pass_col)).any(), f"{name}_ACCEPTED_SIGNAL_FAILED_MA_FILTER")
        require(bool_series(audit, "pit_mcap_pass")[accepted].all(), f"{name}_ACCEPTED_SIGNAL_FAILED_FROZEN_MCAP_GATE")
        accepted_rows = audit.loc[accepted]
        require(accepted_rows["price_source_partition_sha256"].notna().all(), f"{name}_ACCEPTED_SIGNAL_PRICE_PARTITION_HASH_MISSING")
        require(accepted_rows["price_source_metadata_sha256"].notna().all(), f"{name}_ACCEPTED_SIGNAL_PRICE_METADATA_HASH_MISSING")
    return {
        "audit_rows": int(len(audit)),
        "accepted_executable_signals": int(accepted.sum()),
        "trade_count": int(len(trades)),
        "accepted_signal_trade_parity": True,
        "filter_formula_and_fail_closed": True,
        "prior_completed_month_only": True,
        "network_calls": 0,
    }


def progressed_audit(name: str, frame: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[int, pd.DataFrame, int]:
    if frame.empty:
        return 0, pd.DataFrame(), 0
    field = "first_progressed_effective_trading_date"
    raw = frame.get(field, pd.Series(index=frame.index, dtype=object))
    raw_text = raw.astype(str).str.strip()
    raw_nonempty = raw.notna() & ~raw_text.str.lower().isin({"", "nan", "none", "nat"})
    event = pd.to_datetime(raw.where(raw_nonempty), errors="coerce").dt.normalize()
    require(not (raw_nonempty & event.isna()).any(), f"{name}_PROGRESSED_DATE_UNPARSEABLE")
    entry = pd.to_datetime(frame["entry_execution_date"], errors="coerce").dt.normalize()
    status = frame["trade_status"].fillna("").astype(str)
    realized = status.eq("REALIZED")
    open_at_cutoff = status.eq("OPEN_AT_CUTOFF")
    settled = status.eq("LIFECYCLE_SETTLED")
    exit_signal = pd.to_datetime(frame.get("exit_signal_date", pd.Series(index=frame.index, dtype=object)), errors="coerce").dt.normalize()
    settlement = pd.to_datetime(frame.get("settlement_date", pd.Series(index=frame.index, dtype=object)), errors="coerce").dt.normalize()
    require((realized | open_at_cutoff | settled).all(), f"{name}_UNSUPPORTED_TRADE_STATUS_FOR_METRICS")
    require(entry.notna().all(), f"{name}_ENTRY_EXECUTION_DATE_MISSING")
    require(exit_signal[realized].notna().all(), f"{name}_REALIZED_EXIT_SIGNAL_DATE_MISSING")
    require(settlement[settled].notna().all(), f"{name}_LIFECYCLE_SETTLEMENT_DATE_MISSING")
    bound = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    bound.loc[realized] = exit_signal.loc[realized]
    bound.loc[open_at_cutoff] = cutoff
    bound.loc[settled] = settlement.loc[settled]
    counted = event.notna() & entry.le(event) & event.le(bound)
    details = pd.DataFrame({
        "strategy": name,
        "pair_id": frame.get("pair_id", pd.Series(index=frame.index, dtype=object)),
        "ticker": frame.get("ticker", pd.Series(index=frame.index, dtype=object)),
        "trade_status": status,
        "entry_execution_date": entry.dt.strftime("%Y-%m-%d"),
        "first_progressed_effective_trading_date": event.dt.strftime("%Y-%m-%d"),
        "progressed_upper_bound_type": np.select([realized, open_at_cutoff, settled], ["exit_signal_date", "effective_cutoff", "settlement_date"], default="UNSUPPORTED"),
        "progressed_upper_bound_date": bound.dt.strftime("%Y-%m-%d"),
        "raw_field_nonempty": raw_nonempty,
        "authoritative_progressed": counted,
        "exclusion_reason": np.select(
            [~raw_nonempty, event.lt(entry), event.gt(bound)],
            ["NO_EVENT_DATE", "EVENT_BEFORE_ENTRY_EXECUTION", "EVENT_AFTER_ALLOWED_TERMINAL_BOUND"],
            default="COUNTED",
        ),
    })
    return int(counted.sum()), details, int(raw_nonempty.sum())


def validate_ledger(name: str, path: Path, module: Any, cutoff: pd.Timestamp) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(path, dtype={"ticker": str, "pair_id": str, "isu_cd": str})
    require("net_terminal_return_pct" in frame.columns, f"{name}_NET_TERMINAL_RETURN_MISSING")
    if len(frame):
        require(frame["pair_id"].astype(str).is_unique, f"{name}_DUPLICATE_TRADE_KEY")
        require(frame["entry_execution_date"].notna().all(), f"{name}_ENTRY_EXECUTION_DATE_MISSING")
        entry_exec = pd.to_datetime(frame["entry_execution_date"], errors="coerce").dt.normalize()
        require(entry_exec.notna().all() and bool(entry_exec.le(cutoff).all()), f"{name}_ENTRY_AFTER_CUTOFF_OR_INVALID")
        exit_exec = pd.to_datetime(frame.get("exit_execution_date", pd.Series(index=frame.index, dtype=object)), errors="coerce").dt.normalize()
        require(not bool((exit_exec.dropna() > pd.Timestamp(WINDOW["execution_support"])).any()), f"{name}_EXIT_AFTER_SUPPORT_DATE")
        status_check = frame.get("trade_status", pd.Series(index=frame.index, dtype=object)).fillna("").astype(str)
        require(exit_exec[status_check.eq("REALIZED")].notna().all(), f"{name}_REALIZED_EXIT_EXECUTION_DATE_MISSING")
    recomputed = [module.net_terminal_return(row) for row in frame.to_dict("records")]
    stored = pd.to_numeric(frame.get("net_terminal_return_pct", pd.Series(dtype=float)), errors="coerce")
    require(len(stored) == len(frame) and stored.notna().all(), f"{name}_MISSING_TERMINAL_RETURN")
    mismatch = [i for i, (expected, actual) in enumerate(zip(recomputed, stored)) if expected is None or not math.isclose(float(expected), float(actual), rel_tol=0, abs_tol=1e-9)]
    require(not mismatch, f"{name}_NET_TERMINAL_RECOMPUTE_MISMATCH:{len(mismatch)}")
    if len(frame):
        status = frame["trade_status"].fillna("").astype(str)
        realized = status.eq("REALIZED")
        life_settled = status.eq("LIFECYCLE_SETTLED")
        opened = status.eq("OPEN_AT_CUTOFF")
        require((realized | life_settled | opened).all(), f"{name}_UNSUPPORTED_TRADE_STATUS")
        require(int(realized.sum() + life_settled.sum() + opened.sum()) == len(frame), f"{name}_TRADE_STATUS_COUNT_MISMATCH")
        realized_net = pd.to_numeric(frame.get("net_realized_return_pct", pd.Series(index=frame.index, dtype=float)), errors="coerce")
        require(realized_net[realized].notna().all(), f"{name}_REALIZED_RETURN_MISSING")
        if bool(realized.any()):
            require(np.allclose(realized_net[realized], stored[realized], rtol=0, atol=1e-9), f"{name}_REALIZED_NET_RETURN_MISMATCH")
        require(realized_net[~realized].isna().all(), f"{name}_NONREALIZED_HAS_REALIZED_RETURN")
        open_value_date = pd.to_datetime(frame.loc[opened].get("terminal_valuation_date", pd.Series(dtype=object)), errors="coerce").dt.normalize()
        require(open_value_date.notna().all() and bool(open_value_date.le(cutoff).all()), f"{name}_OPEN_POSITION_NOT_VALUED_BY_CUTOFF")
        if bool(life_settled.any()):
            settled_date = pd.to_datetime(frame.loc[life_settled, "settlement_date"], errors="coerce").dt.normalize()
            require(settled_date.notna().all() and bool(settled_date.le(cutoff).all()), f"{name}_LIFECYCLE_SETTLEMENT_AFTER_CUTOFF")
    progressed_count, progressed_detail, raw_progressed_count = progressed_audit(name, frame, cutoff)
    strategy_id = STRATEGIES[name][0]
    metric = module.metric_summary(frame, WINDOW_ID, name, strategy_id)
    terminal = pd.to_numeric(frame.get("net_terminal_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    realized_returns = pd.to_numeric(frame.loc[frame.get("trade_status", pd.Series(dtype=str)).astype(str).eq("REALIZED"), "net_realized_return_pct"], errors="coerce").dropna() if len(frame) else pd.Series(dtype=float)
    holding = pd.to_numeric(frame.get("holding_days", pd.Series(dtype=float)), errors="coerce").dropna()
    metric.update({
        "progressed_count": progressed_count,
        "progressed_rate_pct": (progressed_count / len(frame) * 100.0) if len(frame) else None,
        "progressed_raw_nonempty_field_count": raw_progressed_count,
        "progressed_reconciliation_status": "AUTHORITATIVE_EVENT_WITHIN_ENTRY_AND_TERMINAL_BOUNDS",
        "open_at_cutoff_rate_pct": (float(frame.get("trade_status", pd.Series(dtype=str)).astype(str).eq("OPEN_AT_CUTOFF").sum()) / len(frame) * 100.0) if len(frame) else None,
        "lifecycle_settled_count": int(frame.get("trade_status", pd.Series(dtype=str)).astype(str).eq("LIFECYCLE_SETTLED").sum()),
        "trade_status_count_sum": int(frame.get("trade_status", pd.Series(dtype=str)).astype(str).isin(["REALIZED", "OPEN_AT_CUTOFF", "LIFECYCLE_SETTLED"]).sum()),
        "p25_holding_days": float(holding.quantile(0.25)) if len(holding) else None,
        "p75_holding_days": float(holding.quantile(0.75)) if len(holding) else None,
        "holding_days_available_count": int(len(holding)),
        "net_terminal_recompute_mismatch_count": int(len(mismatch)),
        "net_realized_mean_independent_check_pct": float(realized_returns.mean()) if len(realized_returns) else None,
    })
    return metric, frame, progressed_detail


def compress_verified(path: Path) -> Path:
    raw_hash = sha256(path)
    target = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source, target.open("wb") as raw_out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as zipped:
            shutil.copyfileobj(source, zipped)
    digest = hashlib.sha256()
    with gzip.open(target, "rb") as check:
        for chunk in iter(lambda: check.read(1024 * 1024), b""):
            digest.update(chunk)
    require(digest.hexdigest() == raw_hash, f"GZIP_ROUNDTRIP_HASH_MISMATCH:{path.name}")
    path.unlink()
    return target


def metric_tables(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_name = {str(row["strategy"]): row for row in metrics.to_dict("records")}
    control = by_name["CONTROL"]
    deltas = []
    for name in ("MA60", "ALIGNMENT"):
        c = by_name[name]
        count = int(c["trade_count"])
        base_count = int(control["trade_count"])
        row: dict[str, Any] = {
            "candidate": name,
            "trade_count_delta": count - base_count,
            "trade_count_reduction_pct": ((base_count - count) / base_count * 100.0) if base_count else None,
        }
        fields = {
            "realized_win_rate_pct": "realized_win_rate_delta_pp",
            "average_terminal_return_pct": "average_terminal_delta_pp",
            "median_terminal_return_pct": "median_terminal_delta_pp",
            "average_realized_return_pct": "average_realized_delta_pp",
            "median_realized_return_pct": "median_realized_delta_pp",
            "average_holding_days": "average_holding_days_delta",
            "median_holding_days": "median_holding_days_delta",
            "progressed_rate_pct": "progressed_rate_delta_pp",
            "loss_guard_rate_pct": "loss_guard_rate_delta_pp",
            "max_terminal_return_pct": "max_terminal_return_delta_pp",
            "min_terminal_return_pct": "max_loss_return_delta_pp",
        }
        for source, target in fields.items():
            row[target] = None if c.get(source) is None or control.get(source) is None else float(c[source]) - float(control[source])
        for threshold in (20, 50, 100):
            field = f"terminal_ge_{threshold}"
            row[f"{field}_count_delta"] = int(c[f"{field}_count"]) - int(control[f"{field}_count"])
            row[f"{field}_rate_delta_pp"] = float(c[f"{field}_rate_pct"]) - float(control[f"{field}_rate_pct"])
        for threshold in (10, 15, 20, 30):
            field = f"terminal_le_neg_{threshold}"
            row[f"{field}_count_delta"] = int(c[f"{field}_count"]) - int(control[f"{field}_count"])
            row[f"{field}_rate_delta_pp"] = float(c[f"{field}_rate_pct"]) - float(control[f"{field}_rate_pct"])
        row["loss_guard_count_delta"] = int(c["loss_guard_exit_count"]) - int(control["loss_guard_exit_count"])
        row["progressed_count_delta"] = int(c["progressed_count"]) - int(control["progressed_count"])
        deltas.append(row)
    thresholds = []
    for metric in metrics.to_dict("records"):
        for cutoff, label in ((20, ">=+20%"), (50, ">=+50%"), (100, ">=+100%"), (-10, "<=-10%"), (-15, "<=-15%"), (-20, "<=-20%"), (-30, "<=-30%")):
            prefix = "terminal_ge_" + str(cutoff) if cutoff > 0 else "terminal_le_neg_" + str(abs(cutoff))
            thresholds.append({
                "strategy": metric["strategy"],
                "threshold": label,
                "count": metric[f"{prefix}_count"],
                "rate_pct_of_all_trades": metric[f"{prefix}_rate_pct"],
                "return_basis": "net_terminal_return_pct",
            })
    return pd.DataFrame(deltas), pd.DataFrame(thresholds)


def markdown_report(metrics: pd.DataFrame, deltas: pd.DataFrame, exits: pd.DataFrame, checks: dict[str, Any], pre: dict[str, Any], audit: dict[str, Any]) -> str:
    def f(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"
    lines = [
        "# FAST Core V2 P2-1 단순 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 검증 또는 실행 오류 없음 |",
        "| MAJOR | 0 | worker, 거래 키, 필터, 수익 재계산, provenance 오류 없음 |",
        "| MINOR | 1 | 포트폴리오 equity curve/MDD는 지시 범위 밖이므로 계산하지 않음 |",
        "",
        "## 범위와 입력",
        "",
        f"- 기간: {WINDOW['effective_start']}–{WINDOW['effective_end']}; execution support: {WINDOW['execution_support']}. cutoff 뒤 신규 진입은 제외했어.",
        "- CONTROL, MA60 fail-closed, `signal_day_close > prior completed month MA20 > prior completed month MA60`을 같은 frozen identity/PIT, lifecycle, Repository V2, 비용, cutoff 계약으로 새 replay했어.",
        "- 이전 P2-1, P1, P3-2 성과 파일은 입력 또는 비교에 사용하지 않았어. frozen merged PIT/calendar와 그 authority에 결합된 survivor identity roster만 입력 권한으로 썼어.",
        "- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 비용 반영 net 기준이야.",
        "- 단순 거래 단위 결과라 portfolio MDD와 자본/동시 보유 제약은 산출하지 않았어.",
        "",
        "## 전략별 핵심 지표",
        "",
        "| 전략 | 거래 | 실현 | 생애주기 정산 | cutoff 미종료 | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | PROGRESSED 건수/율 | Loss Guard 건수/율 | 최대 수익 % | 최대 손실 % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in metrics.to_dict("records"):
        lines.append(
            f"| {r['strategy']} | {r['trade_count']} | {r['realized_count']} | {r['lifecycle_settled_count']} | {r['open_at_cutoff_count']} ({f(r['open_at_cutoff_rate_pct'])}%) | {f(r['realized_win_rate_pct'])} | {f(r['terminal_positive_rate_pct'])} | {f(r['average_terminal_return_pct'])} | {f(r['median_terminal_return_pct'])} | "
            f"{f(r['average_realized_return_pct'])} | {f(r['median_realized_return_pct'])} | {f(r['average_holding_days'])} | {f(r['median_holding_days'])} | "
            f"{r['progressed_count']} ({f(r['progressed_rate_pct'])}%) | {r['loss_guard_exit_count']} ({f(r['loss_guard_rate_pct'])}%) | {f(r['max_terminal_return_pct'])} | {f(r['min_terminal_return_pct'])} |"
        )
    lines += [
        "",
        "## 대형 승리·손실",
        "",
        "| 전략 | 구간 | 건수 | 전체 거래 대비 % |",
        "|---|---|---:|---:|",
    ]
    for r in audit["threshold_frame"].to_dict("records"):
        lines.append(f"| {r['strategy']} | {r['threshold']} | {r['count']} | {f(r['rate_pct_of_all_trades'])} |")
    lines += [
        "",
        "## CONTROL 대비 변화",
        "",
        "| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 평균 Δ %p | terminal 중앙 Δ %p | realized 평균 Δ %p | realized 중앙 Δ %p | 평균 보유 Δ 일 | 중앙 보유 Δ 일 | Loss Guard Δ %p | PROGRESSED Δ %p | 최대 수익 Δ %p | 최대 손실 Δ %p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in deltas.to_dict("records"):
        lines.append(
            f"| {r['candidate']} | {r['trade_count_delta']} | {f(r['trade_count_reduction_pct'])} | {f(r['realized_win_rate_delta_pp'])} | "
            f"{f(r['average_terminal_delta_pp'])} | {f(r['median_terminal_delta_pp'])} | {f(r['average_realized_delta_pp'])} | {f(r['median_realized_delta_pp'])} | "
            f"{f(r['average_holding_days_delta'])} | {f(r['median_holding_days_delta'])} | {f(r['loss_guard_rate_delta_pp'])} | {f(r['progressed_rate_delta_pp'])} | "
            f"{f(r['max_terminal_return_delta_pp'])} | {f(r['max_loss_return_delta_pp'])} |"
        )
    lines += [
        "",
        "### 대형 승리·손실 비율 변화",
        "",
        "| 후보 | 구간 | 건수 Δ | 전체 거래 대비 비율 Δ %p |",
        "|---|---|---:|---:|",
    ]
    for r in deltas.to_dict("records"):
        for threshold, label in ((20, ">=+20%"), (50, ">=+50%"), (100, ">=+100%"), (-10, "<=-10%"), (-15, "<=-15%"), (-20, "<=-20%"), (-30, "<=-30%")):
            prefix = "terminal_ge_" + str(threshold) if threshold > 0 else "terminal_le_neg_" + str(abs(threshold))
            lines.append(f"| {r['candidate']} | {label} | {r[f'{prefix}_count_delta']} | {f(r[f'{prefix}_rate_delta_pp'])} |")
    lines += [
        "",
        "## Exit reason 분포",
        "",
        "| 전략 | exit_type | 건수 |",
        "|---|---|---:|",
    ]
    for r in exits.to_dict("records"):
        lines.append(f"| {r['strategy']} | {r['exit_type']} | {r['count']} |")
    lines += [
        "",
        "## PROGRESSED 집계",
        "",
        "`first_progressed_effective_trading_date`가 non-null인 것만으로 세지 않았어. 실현 거래는 entry execution ≤ event ≤ exit signal, cutoff 미종료는 entry execution ≤ event ≤ 2025-05-30 범위로 검증했어. LIFECYCLE_SETTLED가 있으면 정산일을 상한으로 별도 반영했고 건수도 분리했어.",
        "",
        "## 검증과 provenance",
        "",
        f"- Worker: {WORKERS}; worker error: {checks['worker_error_count']}; 처리 ticker: {pre['unique_ticker_count']}; P2-1 identity key: {pre['p2_1_identity_key_count']}; PIT segment: {pre['p2_1_identity_segment_count']}.",
        f"- Trade key 중복: {checks['duplicate_trade_key_count']}; candidate accepted signal↔trade parity: {checks['candidate_signal_parity']}; net terminal 재계산 mismatch: {checks['net_terminal_recompute_mismatch_count']}.",
        f"- MA60 필터·fail-closed: {checks['ma60_filter_check']}; Alignment 식·fail-closed: {checks['alignment_filter_check']}; cutoff 신규 진입 위반: {checks['post_cutoff_entry_count']}.",
        f"- Frozen PIT/calendar/survivor/source hash와 adjusted/raw partition 검증: PASS; 네트워크 호출: {checks['network_calls']}; 완전한 결과만 최종 보고에 사용했어.",
        f"- Frozen PIT SHA-256: `{pre['frozen_pit_sha256']}`; calendar SHA-256: `{pre['frozen_calendar_sha256']}`; survivor identity authority SHA-256: `{pre['survivor_identity_roster_sha256']}`.",
        "- P1 성과 방향 비교는 해당 성과 자료를 읽지 말라는 이번 실행 경계를 지켜 생략했어. P1/P3 성과와 합쳐 채택 판단을 내리지 않았어.",
        "",
        "## 산출물",
        "",
        f"- `{OUT.relative_to(ROOT).as_posix()}/` 아래 metrics, trade ledger, signal/MKTCAP/price audit, execution audit, provenance가 있어.",
        f"- 결과 토큰: `{FINAL_TOKEN}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    global STAGE, REPLAY_STARTED
    started = time.perf_counter()
    module = None
    network_calls = 0
    try:
        STAGE = "PREFLIGHT"
        module = load_shared()
        pre, frozen, base_run, base_gate, universe, authority, survivors = preflight(module)
        write_json(OUT / "preflight.json", pre)
        prices = module.HELPER.PriceCache()
        metrics_raw: list[dict[str, Any]] = []
        STAGE = "P2_1_FULL_REPLAY"
        REPLAY_STARTED = True
        net = module.network_guard()
        try:
            execution = module.run_full_window(WINDOW_ID, base_run, base_gate, survivors, prices, metrics_raw)
            network_calls = int(net[2]["calls"])
        finally:
            module.restore_network_guard(net)
        require(network_calls == 0, "NETWORK_CALLS_DURING_REPLAY")
        require(execution["window_id"] == WINDOW_ID, "EXECUTION_WINDOW_ID_MISMATCH")
        require(execution["worker_count"] == WORKERS, "EXECUTION_WORKER_COUNT_MISMATCH")
        require(execution["worker_errors"] == [], "EXECUTION_WORKER_ERRORS")
        require(len(metrics_raw) == 3 and {m["strategy"] for m in metrics_raw} == set(STRATEGIES), "P2_1_METRICS_INCOMPLETE")
        for name, result in execution["execution"].items():
            require(result.get("worker_count") == WORKERS, f"{name}_WORKER_COUNT_MISMATCH")
            require(result.get("worker_errors") == [], f"{name}_WORKER_ERRORS")
            require(result.get("ticker_count") == pre["unique_ticker_count"], f"{name}_PROCESSED_TICKER_COUNT_MISMATCH")

        STAGE = "RESULT_INTEGRITY"
        cutoff = pd.Timestamp(WINDOW["effective_end"])
        metrics, ledgers, progression_frames = [], {}, []
        audit_checks = {}
        all_hashes = []
        for name, (_strategy_id, filename) in STRATEGIES.items():
            path = OUT / filename
            metric, ledger, progressed = validate_ledger(name, path, module, cutoff)
            metrics.append(metric)
            ledgers[name] = ledger
            if len(progressed):
                progression_frames.append(progressed)
            all_hashes.append({"strategy": name, "trade_file": filename, "sha256": sha256(path)})
            if name != "CONTROL":
                audit_name = f"p2_1_{name.lower()}_signal_audit.csv"
                audit_checks[name] = candidate_audit_check(name, OUT / audit_name, ledger)

        control_mcap_path = OUT / "p2_1_control_pit_mcap_audit.csv"
        mcap = pd.read_csv(control_mcap_path, dtype={"ticker": str})
        unresolved = int(mcap.get("status", pd.Series(dtype=str)).astype(str).eq("UNRESOLVED").sum())
        require(unresolved == 0, f"CONTROL_MCAP_UNRESOLVED_ROWS:{unresolved}")
        require(not mcap.empty, "CONTROL_MCAP_AUDIT_EMPTY")
        mcap_keys = ["ticker", "identity", "market", "signal_date"]
        require(all(col in mcap.columns for col in mcap_keys), "CONTROL_MCAP_AUDIT_KEY_MISSING")
        for col in mcap_keys:
            mcap[col] = mcap[col].astype(str)
        require(not mcap.duplicated(mcap_keys).any(), "CONTROL_MCAP_AUDIT_DUPLICATE_SIGNAL")
        status_by_key = mcap.set_index(mcap_keys)["status"].astype(str)
        control = ledgers["CONTROL"]
        for row in control.to_dict("records"):
            key = (str(row["ticker"]).zfill(6), str(row["isu_cd"]), str(row["market"]), str(row["entry_signal_date"]))
            require(key in status_by_key.index and status_by_key.loc[key] == "PASS", "CONTROL_TRADE_WITHOUT_EXACT_MCAP_PASS")

        metric_frame = pd.DataFrame(metrics)
        require(metric_frame["trade_count"].eq(metric_frame["realized_count"] + metric_frame["open_at_cutoff_count"] + metric_frame["lifecycle_settled_count"]).all(), "TRADE_STATUS_COUNT_MISMATCH")
        require(metric_frame["terminal_return_available_count"].eq(metric_frame["trade_count"]).all(), "MISSING_TERMINAL_RETURN")
        require(metric_frame["net_terminal_recompute_mismatch_count"].eq(0).all(), "NET_TERMINAL_RECOMPUTE_MISMATCH")
        deltas, threshold_frame = metric_tables(metric_frame)
        write_frame(OUT / "p2_1_strategy_metrics.csv", metric_frame)
        write_frame(OUT / "p2_1_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p2_1_large_outcomes.csv", threshold_frame)
        if progression_frames:
            progression = pd.concat(progression_frames, ignore_index=True)
        else:
            progression = pd.DataFrame()
        write_frame(OUT / "p2_1_progressed_reconciliation_audit.csv", progression)
        exit_rows = []
        for name, frame in ledgers.items():
            values = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("(none)").astype(str).value_counts()
            exit_rows.extend({"strategy": name, "exit_type": key, "count": int(value)} for key, value in values.items())
        exit_frame = pd.DataFrame(exit_rows)
        write_frame(OUT / "p2_1_exit_reason_distribution.csv", exit_frame)
        price_audit = pd.DataFrame(prices.audit.values())
        write_frame(OUT / "p2_1_price_store_audit.csv", price_audit)

        checks = {
            "worker_error_count": 0,
            "workers": WORKERS,
            "duplicate_trade_key_count": 0,
            "candidate_signal_parity": all(a.get("accepted_signal_trade_parity") for a in audit_checks.values()),
            "ma60_filter_check": audit_checks.get("MA60", {}).get("filter_formula_and_fail_closed", False),
            "alignment_filter_check": audit_checks.get("ALIGNMENT", {}).get("filter_formula_and_fail_closed", False),
            "net_terminal_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
            "post_cutoff_entry_count": 0,
            "control_mcap_unresolved_count": unresolved,
            "control_mcap_trade_entry_pass": True,
            "network_calls": network_calls,
            "processed_ticker_count_each_strategy": pre["unique_ticker_count"],
            "identity_key_count": pre["p2_1_identity_key_count"],
            "identity_segment_count": pre["p2_1_identity_segment_count"],
            "candidate_audits": audit_checks,
            "trade_file_hashes": all_hashes,
            "price_partition_count": int(len(price_audit)),
            "price_partition_hash_metadata_checks_pass": bool(price_audit.empty or (price_audit["metadata_row_count_matches"].astype(bool).all() and price_audit["metadata_date_range_matches"].astype(bool).all())),
        }
        require(checks["candidate_signal_parity"] and checks["ma60_filter_check"] and checks["alignment_filter_check"], "CANDIDATE_SIGNAL_OR_FILTER_INTEGRITY_FAILURE")
        require(checks["price_partition_hash_metadata_checks_pass"], "PRICE_PARTITION_HASH_METADATA_CHECK_FAILED")
        require(checks["duplicate_trade_key_count"] == 0, "DUPLICATE_TRADE_KEY")
        require(checks["post_cutoff_entry_count"] == 0, "POST_CUTOFF_ENTRY")

        STAGE = "COMPRESS_AND_FINALIZE"
        compressed = []
        for name in (
            "p2_1_control_pit_mcap_audit.csv",
            "p2_1_ma60_signal_audit.csv",
            "p2_1_alignment_signal_audit.csv",
            "p2_1_price_store_audit.csv",
        ):
            compressed.append(compress_verified(OUT / name).name)
        execution.update({
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "worker_count": WORKERS,
            "worker_errors": [],
            "identity_key_count": pre["p2_1_identity_key_count"],
            "identity_segment_count": pre["p2_1_identity_segment_count"],
            "processed_ticker_count_each_strategy": pre["unique_ticker_count"],
            "strategy_trade_counts": {name: int(len(frame)) for name, frame in ledgers.items()},
            "progressed_counts_authoritative": {str(row["strategy"]): int(row["progressed_count"]) for row in metrics},
            "checks": checks,
            "compressed_verified_audits": compressed,
            "elapsed_seconds": time.perf_counter() - started,
        })
        write_json(OUT / "p2_1_execution_audit.json", execution)
        write_frame(OUT / "p2_1_strategy_metrics_reconciled.csv", metric_frame)
        report = markdown_report(metric_frame, deltas, exit_frame, checks, pre, {"threshold_frame": threshold_frame})
        (OUT / "report.md").write_text(report, encoding="utf-8")
        input_hashes = pre["input_source_hashes"]
        artifact_hashes = {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name not in {"p2_1_provenance.json", "run_p2_1_simple_backtest.py"}
        }
        provenance = {
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "work_id": WORK_ID,
            "scope": "P2-1 trade-level simple backtest only",
            "window": WINDOW,
            "worker_count": WORKERS,
            "network_calls": network_calls,
            "result_reuse": pre["result_reuse"],
            "authority": {
                "frozen_pit_sha256": pre["frozen_pit_sha256"],
                "frozen_calendar_sha256": pre["frozen_calendar_sha256"],
                "frozen_manifest_sha256": pre["frozen_manifest_sha256"],
                "survivor_identity_roster_sha256": pre["survivor_identity_roster_sha256"],
                "survivor_identity_roster_count": pre["survivor_identity_roster_count"],
                "p2_1_identity_key_count": pre["p2_1_identity_key_count"],
                "p2_1_identity_segment_count": pre["p2_1_identity_segment_count"],
            },
            "source_hashes": input_hashes,
            "adjusted_price_store_partition_hashes": price_audit[[c for c in ("ticker", "relative_path", "sha256", "metadata_relative_path", "metadata_sha256", "source_authority_id", "source_semantics", "authority_type", "row_count", "actual_date_min", "actual_date_max") if c in price_audit.columns]].to_dict("records"),
            "exact_raw_mcap_partition_audit": {
                "audit_rows": int(len(mcap)),
                "unresolved_rows": unresolved,
                "statuses": mcap["status"].astype(str).value_counts().to_dict(),
                "partition_sha256_values": sorted(set(mcap["partition_file_sha256"].dropna().astype(str))) if "partition_file_sha256" in mcap else [],
                "gate_load_snapshot_hash_validation": "PASS",
            },
            "cost_contract": pre["cost_contract"],
            "metrics_progressed_basis": "entry execution <= event <= exit signal for REALIZED; <= effective cutoff for OPEN_AT_CUTOFF; <= settlement date for LIFECYCLE_SETTLED",
            "no_portfolio_mdd": True,
            "integrity": checks,
            "artifact_sha256": artifact_hashes,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(OUT / "p2_1_provenance.json", provenance)
        return 0
    except Exception as exc:
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            write_json(OUT / "failure.json", {
                "status": "CHECK_REQUIRED",
                "final_token": CHECK_TOKEN,
                "stage": STAGE,
                "replay_started": REPLAY_STARTED,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "automatic_retry": False,
                "partial_output_is_final_result": False,
                "next_action": "stop and report; do not rerun or interpret partial metrics",
            })
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
