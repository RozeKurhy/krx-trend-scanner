#!/usr/bin/env python3
"""Fresh, offline P2-2 trade-level replay for CONTROL, MA60, and alignment."""

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

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

OUT = Path(__file__).resolve().parent
SHARED_PATH = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py"
PIT_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
SURVIVOR_PATH = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/survivor_universe_audit.csv"
PRIOR_P1_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v02"
PRIOR_P2_1_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_1_ma60_vs_bullish_alignment_simple_backtest_v01"
NEWLY_APPROVED_EXCLUSIONS = {
    ("007720", "KR7007720006"),
    ("011080", "KR7011080009"),
    ("019490", "KR7019490002"),
    ("019570", "KR7019570001"),
    ("066790", "KR7066790007"),
    ("073570", "KR7073570004"),
    ("083660", "KR7083660001"),
}
WORK_ID = "FAST_CORE_V2_LIFECYCLE_PREFIX_INVARIANCE_FIX_V01_P2_2"
FINAL_TOKEN = WORK_ID + "_PASS"
CHECK_TOKEN = WORK_ID + "_CHECK_REQUIRED"
WINDOW_ID = "P2-2"
WINDOW = {"effective_start": "2021-01-04", "effective_end": "2026-08-31", "execution_support": "2026-09-01"}
WORKERS = 10
STRATEGIES = {
    "CONTROL": ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "p2_2_control_trades.csv"),
    "MA60": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER", "p2_2_ma60_trades.csv"),
    "ALIGNMENT": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT", "p2_2_alignment_trades.csv"),
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
    spec = importlib.util.spec_from_file_location("p2_2_shared_simple_replay", SHARED_PATH)
    require(spec is not None and spec.loader is not None, "SHARED_REPLAY_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUT = OUT
    module.WORKERS = WORKERS
    return module


def source_paths(module: Any) -> dict[str, Path]:
    paths = {
        "core_strategy_runner": ROOT / "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
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
        ("permanent_identity_exclusion_registry", ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
        ("lifecycle_settlement_evidence", module.STRATEGY.LIFECYCLE_SETTLEMENT_EVIDENCE_PATH),
        ("lifecycle_event_evidence_v02", module.STRATEGY.LIFECYCLE_EVENT_EVIDENCE_V02_PATH),
    ):
        if path.is_file():
            paths[name] = path
    return paths


def preflight(module: Any) -> tuple[dict[str, Any], Any, Any, Any, Any, Any, frozenset[Any], pd.DataFrame]:
    allowed = {Path(__file__).name, "__pycache__"}
    unexpected = sorted(p.name for p in OUT.iterdir() if p.name not in allowed)
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")
    tracked_changes = sorted(set(git("diff", "--name-only").splitlines()) | set(git("diff", "--cached", "--name-only").splitlines()))
    require(set(tracked_changes) == {'src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py'}, "UNEXPECTED_TRACKED_WORKTREE_CHANGES")
    source_hashes = {}
    for name, path in source_paths(module).items():
        require(path.is_file(), f"INPUT_MISSING:{name}:{path}")
        source_hashes[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        if name != "canonical_strategy":
            require(committed.returncode == 0 and committed.stdout == path.read_bytes(), f"INPUT_HASH_DIFFERS_FROM_HEAD:{name}")
    source_hashes["p2_2_execution_script"] = {
        "path": Path(__file__).relative_to(ROOT).as_posix(),
        "sha256": sha256(Path(__file__)),
        "tracked_at_start": False,
    }
    manifest_path = PIT_DIR / "p2_2_identity_authority_extension_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS", "FROZEN_AUTHORITY_MANIFEST_NOT_PASS")
    require(sha256(PIT_DIR / "merged_trading_calendar.json") == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")
    require(len(PERMANENT_IDENTITY_EXCLUSIONS) == 181, "CURRENT_PERMANENT_EXCLUSION_COUNT_MISMATCH")
    policy_by_identity = {
        (str(ticker).zfill(6), str(isu_cd).strip().upper()): metadata
        for (ticker, isu_cd), metadata in PERMANENT_IDENTITY_EXCLUSIONS.items()
    }
    require(len(policy_by_identity) == len(PERMANENT_IDENTITY_EXCLUSIONS), "PERMANENT_EXCLUSION_IDENTITY_COLLISION")
    require(NEWLY_APPROVED_EXCLUSIONS.issubset(policy_by_identity), "NEWLY_APPROVED_7_NOT_IN_CURRENT_AUTHORITY")
    network = module.network_guard()
    try:
        frozen, base_run, base_gate, universe, authority, roster_survivors = module.load_frozen_context()
        require(len(roster_survivors) == 2539, "FROZEN_SURVIVOR_IDENTITY_COUNT_MISMATCH")
        roster_pairs = {(item[0], item[1]) for item in roster_survivors}
        excluded_roster = frozenset(
            item for item in roster_survivors if (item[0], item[1]) in policy_by_identity
        )
        eligible_survivors = frozenset(roster_survivors - excluded_roster)
        excluded_roster_pairs = roster_pairs & set(policy_by_identity)
        new_seven_overlap = roster_pairs & NEWLY_APPROVED_EXCLUSIONS
        require(len(new_seven_overlap) == 7, "NEWLY_APPROVED_7_NOT_IN_SURVIVOR_ROSTER")
        require(len(excluded_roster) == len(excluded_roster_pairs), "PERMANENT_EXCLUSION_ROSTER_PAIR_NOT_UNIQUE")
        require(not any((item[0], item[1]) in policy_by_identity for item in eligible_survivors), "PERMANENT_EXCLUSION_FILTER_LEAK")
        require(bool(eligible_survivors), "NO_ELIGIBLE_SURVIVORS_AFTER_PERMANENT_EXCLUSIONS")
        run, scoped_gate, window_context = module.context_for_window(base_run, base_gate, eligible_survivors, WINDOW_ID)
        require(window_context["effective_start"] == WINDOW["effective_start"], "P2_2_START_MISMATCH")
        require(window_context["effective_end"] == WINDOW["effective_end"], "P2_2_CUTOFF_MISMATCH")
        require(window_context["execution_support"] == WINDOW["execution_support"], "P2_2_SUPPORT_MISMATCH")
        require(window_context["survivor_identity_count"] == len(eligible_survivors), "P2_2_SURVIVOR_CONTEXT_MISMATCH")
        require(window_context["common_pit_segment_count"] == sum(map(len, run.segments_by_ticker.values())), "P2_2_SEGMENT_CONTEXT_MISMATCH")
        scoped_pairs = {
            (segment.ticker, segment.isu_cd.upper())
            for rows in run.segments_by_ticker.values()
            for segment in rows
        }
        require(not (scoped_pairs & set(policy_by_identity)), "P2_2_WINDOW_PERMANENT_EXCLUSION_LEAK")
        require(network[2]["calls"] == 0, "NETWORK_CALLS_DURING_PREFLIGHT")
    finally:
        module.restore_network_guard(network)
    identity_keys = {
        (segment.ticker, segment.isu_cd, segment.market)
        for rows in run.segments_by_ticker.values()
        for segment in rows
    }
    identity_audit = universe.copy()
    identity_audit["ticker"] = identity_audit["ticker"].astype(str).str.zfill(6)
    identity_audit["isu_cd"] = identity_audit["isu_cd"].astype(str).str.strip().str.upper()
    identity_audit["is_frozen_survivor"] = identity_audit["status"].astype(str).eq("SURVIVOR_COMMON_IDENTITY")
    identity_audit["current_permanent_exclusion"] = [
        (ticker, isu_cd) in policy_by_identity
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    window_identity_keys = {
        (segment.ticker, segment.isu_cd.strip().upper(), segment.market.strip().upper())
        for rows in run.segments_by_ticker.values()
        for segment in rows
    }
    identity_audit["p2_2_window_pit_overlap"] = [
        (ticker, isu_cd, str(market).strip().upper()) in window_identity_keys
        for ticker, isu_cd, market in zip(identity_audit["ticker"], identity_audit["isu_cd"], identity_audit["market"])
    ]
    identity_audit["included_in_p2_2"] = (
        identity_audit["is_frozen_survivor"]
        & ~identity_audit["current_permanent_exclusion"]
        & identity_audit["p2_2_window_pit_overlap"]
    )
    identity_audit["permanent_exclusion_failure_class"] = [
        policy_by_identity.get((ticker, isu_cd), {}).get("failure_class")
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    identity_audit["permanent_exclusion_approval_scope"] = [
        policy_by_identity.get((ticker, isu_cd), {}).get("approval_scope")
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    identity_audit["permanent_exclusion_approved_date"] = [
        policy_by_identity.get((ticker, isu_cd), {}).get("approved_date")
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    identity_audit["permanent_exclusion_reason"] = [
        policy_by_identity.get((ticker, isu_cd), {}).get("reason")
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    pre = {
        "status": "PASS",
        "work_id": WORK_ID,
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "tracked_worktree_clean": not bool(tracked_changes),
        "tracked_changes_at_start": tracked_changes,
        "canonical_source_modified_from_start_head": True,
        "window_id": WINDOW_ID,
        **window_context,
        "workers": WORKERS,
        "strategy_ids": {name: details[0] for name, details in STRATEGIES.items()},
        "survivor_identity_roster_count": len(roster_survivors),
        "permanent_exclusion_registry_count": len(policy_by_identity),
        "survivor_permanent_exclusion_overlap_count": len(excluded_roster),
        "newly_approved_7_survivor_overlap_count": len(new_seven_overlap),
        "eligible_survivor_identity_count": len(eligible_survivors),
        "p2_2_window_pit_identity_key_count": len(identity_keys),
        "permanent_exclusions_applied_by_exact_ticker_isu": True,
        "excluded_survivor_identities": [
            {
                "ticker": ticker,
                "isu_cd": isu_cd,
                "market": market,
                **policy_by_identity[(ticker, isu_cd)],
            }
            for ticker, isu_cd, market in sorted(excluded_roster)
        ],
        "p2_2_identity_key_count": len(identity_keys),
        "p2_2_identity_segment_count": sum(map(len, run.segments_by_ticker.values())),
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
            "previous_p2_2_performance": False,
            "p1_performance": False,
            "p3_2_performance": False,
            "frozen_pit_calendar_reused_as_authority": True,
            "frozen_survivor_identity_roster_reused_as_authority": True,
        },
        "network_calls": 0,
    }
    return pre, frozen, base_run, base_gate, universe, authority, eligible_survivors, identity_audit


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
            "terminal_positive_rate_pct": "terminal_positive_rate_delta_pp",
            "average_terminal_return_pct": "average_terminal_delta_pp",
            "median_terminal_return_pct": "median_terminal_delta_pp",
            "average_realized_return_pct": "average_realized_delta_pp",
            "median_realized_return_pct": "median_realized_delta_pp",
            "average_holding_days": "average_holding_days_delta",
            "median_holding_days": "median_holding_days_delta",
            "progressed_rate_pct": "progressed_rate_delta_pp",
            "loss_guard_rate_pct": "loss_guard_rate_delta_pp",
            "open_at_cutoff_rate_pct": "cutoff_open_rate_delta_pp",
            "max_terminal_return_pct": "max_terminal_return_delta_pp",
            "min_terminal_return_pct": "max_loss_return_delta_pp",
        }
        for source, target in fields.items():
            candidate_value = c.get(source)
            control_value = control.get(source)
            if source == "open_at_cutoff_rate_pct":
                if candidate_value is None or pd.isna(candidate_value):
                    candidate_value = (float(c.get("open_at_cutoff_count", 0)) / count * 100.0) if count else None
                if control_value is None or pd.isna(control_value):
                    control_value = (float(control.get("open_at_cutoff_count", 0)) / base_count * 100.0) if base_count else None
            row[target] = None if candidate_value is None or control_value is None else float(candidate_value) - float(control_value)
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


def load_prior_period_references() -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    specs = {
        "P1": {
            "directory": PRIOR_P1_DIR,
            "manifest": "p1_provenance.json",
            "hash_key": "output_sha256",
            "metrics": "p1_strategy_metrics_reconciled.csv",
            "ledger_prefix": "p1",
        },
        "P2-1": {
            "directory": PRIOR_P2_1_DIR,
            "manifest": "p2_1_provenance.json",
            "hash_key": "output_artifact_sha256",
            "metrics": "p2_1_strategy_metrics_reconciled.csv",
            "ledger_prefix": "p2_1",
        },
    }
    reference_metrics: dict[str, pd.DataFrame] = {}
    provenance: dict[str, Any] = {}
    current_policy = {
        (str(ticker).zfill(6), str(isu_cd).strip().upper())
        for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
    }
    for period, spec in specs.items():
        directory = spec["directory"]
        manifest = json.loads((directory / spec["manifest"]).read_text(encoding="utf-8"))
        expected_statuses = {
            "P1": {"P1_ONLY_REPORT_COMPLETE_P2_1_STOPPED"},
            "P2-1": {"PASS_RECOVERED_FROM_COMPLETE_REPLAY_OUTPUTS"},
        }
        require(manifest.get("status") in expected_statuses[period], f"{period}_REFERENCE_STATUS_INVALID")
        outputs = manifest.get(spec["hash_key"], {})
        require(outputs, f"{period}_REFERENCE_OUTPUT_HASHES_MISSING")
        mismatches = []
        for name, expected in outputs.items():
            path = directory / name
            if not path.is_file():
                mismatches.append(f"MISSING:{name}")
                continue
            expected_hash = expected.get("sha256") if isinstance(expected, dict) else expected
            actual_hash = sha256(path)
            if actual_hash != expected_hash:
                mismatches.append(f"HASH:{name}")
            if isinstance(expected, dict) and path.stat().st_size != expected.get("bytes"):
                mismatches.append(f"SIZE:{name}")
        require(not mismatches, f"{period}_REFERENCE_ARTIFACT_HASH_MISMATCH:{','.join(mismatches)}")

        if period == "P1":
            p1_preflight = json.loads((directory / "preflight.json").read_text(encoding="utf-8"))
            p1_execution = json.loads((directory / "p1_execution_audit.json").read_text(encoding="utf-8"))
            raw_cost = p1_preflight.get("cost_contract", {})
            reference_cost = {
                "buy_commission_rate": raw_cost.get("buy_commission_rate"),
                "sell_commission_rate": raw_cost.get("sell_commission_rate", raw_cost.get("buy_commission_rate")),
                "buy_slippage_rate": raw_cost.get("buy_slippage_rate"),
                "sell_slippage_rate": raw_cost.get("sell_slippage_rate", raw_cost.get("buy_slippage_rate")),
                "transaction_tax_in_returns": raw_cost.get("transaction_tax_in_returns", raw_cost.get("transaction_tax_in_official_returns")),
            }
            reference_workers = p1_execution.get("worker_count")
            require(p1_execution.get("worker_errors") == [], "P1_REFERENCE_WORKER_ERRORS")
            require(all(p1_execution.get("execution", {}).get(name, {}).get("worker_errors") == [] for name in STRATEGIES), "P1_REFERENCE_STRATEGY_WORKER_ERRORS")
        else:
            raw_cost = manifest.get("cost_contract", {})
            reference_cost = {
                "buy_commission_rate": raw_cost.get("buy_commission_rate"),
                "sell_commission_rate": raw_cost.get("sell_commission_rate"),
                "buy_slippage_rate": raw_cost.get("buy_slippage_rate"),
                "sell_slippage_rate": raw_cost.get("sell_slippage_rate"),
                "transaction_tax_in_returns": raw_cost.get("transaction_tax_in_returns"),
            }
            p2_1_execution = json.loads((directory / "p2_1_execution_audit.json").read_text(encoding="utf-8"))
            reference_workers = p2_1_execution.get("worker_count")
            require(p2_1_execution.get("worker_errors") == [], "P2_1_REFERENCE_WORKER_ERRORS")
            require(p2_1_execution.get("integrity_checks", {}).get("worker_error_count") == 0, "P2_1_REFERENCE_WORKER_ERROR_COUNT")
        require(reference_workers == 10, f"{period}_REFERENCE_WORKER_STANDARD_MISMATCH")
        require(
            reference_cost == {
                "buy_commission_rate": 0.00015,
                "sell_commission_rate": 0.00015,
                "buy_slippage_rate": 0.001,
                "sell_slippage_rate": 0.001,
                "transaction_tax_in_returns": False,
            },
            f"{period}_REFERENCE_COST_CONTRACT_MISMATCH",
        )

        metrics = pd.read_csv(directory / spec["metrics"], dtype={"strategy": str})
        require(set(metrics["strategy"].astype(str)) == set(STRATEGIES), f"{period}_REFERENCE_METRICS_INCOMPLETE")
        require(not metrics["strategy"].astype(str).duplicated().any(), f"{period}_REFERENCE_METRICS_DUPLICATE")
        ledger_overlap: dict[str, Any] = {}
        for strategy in STRATEGIES:
            path = directory / f"{spec['ledger_prefix']}_{strategy.lower()}_trades.csv"
            frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str})
            pairs = {
                (str(ticker).zfill(6), str(isu_cd).strip().upper())
                for ticker, isu_cd in zip(frame["ticker"], frame["isu_cd"])
            }
            current_matches = pairs & current_policy
            new_matches = pairs & NEWLY_APPROVED_EXCLUSIONS
            ledger_overlap[strategy] = {
                "trade_rows": int(len(frame)),
                "trades_matching_current_permanent_exclusions": int(sum(
                    1 for ticker, isu_cd in zip(frame["ticker"], frame["isu_cd"])
                    if (str(ticker).zfill(6), str(isu_cd).strip().upper()) in current_policy
                )),
                "distinct_current_excluded_identities_in_ledger": len(current_matches),
                "trades_matching_2026_10_05_seven": int(sum(
                    1 for ticker, isu_cd in zip(frame["ticker"], frame["isu_cd"])
                    if (str(ticker).zfill(6), str(isu_cd).strip().upper()) in NEWLY_APPROVED_EXCLUSIONS
                )),
                "distinct_2026_10_05_excluded_identities_in_ledger": len(new_matches),
            }
        reference_metrics[period] = metrics
        provenance[period] = {
            "status": manifest["status"],
            "manifest_path": (directory / spec["manifest"]).relative_to(ROOT).as_posix(),
            "metrics_path": (directory / spec["metrics"]).relative_to(ROOT).as_posix(),
            "metrics_sha256": sha256(directory / spec["metrics"]),
            "output_artifact_count_hash_verified": len(outputs),
            "worker_count": reference_workers,
            "worker_error_count": 0,
            "cost_contract": reference_cost,
            "permanent_exclusion_trade_overlap": ledger_overlap,
            "used_as_backtest_input": False,
            "used_for_repeatability_comparison_only": True,
        }
    return reference_metrics, provenance


def repeatability_delta_frame(period_metrics: dict[str, pd.DataFrame], current_metrics: pd.DataFrame) -> pd.DataFrame:
    all_periods = {**period_metrics, "P2-2": current_metrics}
    rows = []
    for period in ("P1", "P2-1", "P2-2"):
        deltas, _ = metric_tables(all_periods[period])
        for row in deltas.to_dict("records"):
            rows.append({"period": period, **row})
    return pd.DataFrame(rows)


def repeatability_assessment(frame: pd.DataFrame, period_metrics: dict[str, pd.DataFrame]) -> list[str]:
    def values(candidate: str, field: str) -> list[float]:
        selected = frame.loc[frame["candidate"].eq(candidate)].sort_values("period")
        order = {"P1": 0, "P2-1": 1, "P2-2": 2}
        selected = selected.assign(_order=selected["period"].map(order)).sort_values("_order")
        return [float(v) for v in selected[field]]

    def fmt(items: list[float]) -> str:
        return ", ".join(f"{value:+.2f}" for value in items)

    lines = []
    for candidate, label in (("MA60", "MA60"), ("ALIGNMENT", "Bullish Alignment")):
        reduction = values(candidate, "trade_count_reduction_pct")
        win = values(candidate, "realized_win_rate_delta_pp")
        avg_terminal = values(candidate, "average_terminal_delta_pp")
        avg_holding = values(candidate, "average_holding_days_delta")
        progressed = values(candidate, "progressed_rate_delta_pp")
        win_positive = sum(value > 0 for value in win)
        average_positive = sum(value > 0 for value in avg_terminal)
        holding_shorter = sum(value < 0 for value in avg_holding)
        progressed_signs = {value > 0 for value in progressed if value != 0}
        progressed_consistent = len(progressed_signs) <= 1
        if candidate == "MA60":
            retention = [100.0 - value for value in reduction]
            lines.append(
                f"- {label}: P1/P2-1/P2-2의 거래 감소율은 {fmt(reduction)}% (거래 유지율 {fmt(retention)}%)야. "
                f"승률 우위 {win_positive}/3기간, 평균 terminal 수익 우위 {average_positive}/3기간, "
                f"평균 보유기간 단축 {holding_shorter}/3기간으로 평가해. PROGRESSED 비율 delta는 {fmt(progressed)}%p "
                f"({'같은 방향' if progressed_consistent else '기간별 방향 변동'})이야."
            )
        else:
            concentration_fields = [
                "terminal_ge_20_rate_delta_pp",
                "terminal_ge_50_rate_delta_pp",
                "terminal_ge_100_rate_delta_pp",
            ]
            concentration = [values(candidate, field) for field in concentration_fields]
            concentration_positive = sum(all(v > 0 for v in series) for series in concentration)
            within_band = sum(55.0 <= value <= 60.0 for value in reduction)
            lines.append(
                f"- {label}: 거래 감소율 {fmt(reduction)}% 중 55~60% 범위는 {within_band}/3기간이야. "
                f"승률 우위 {win_positive}/3기간, 평균 terminal 수익 우위 {average_positive}/3기간, "
                f"평균 보유기간 단축 {holding_shorter}/3기간이고, +20/+50/+100% winner 비율이 모두 상승한 기간은 "
                f"{concentration_positive}/3기간이야. PROGRESSED 비율 delta는 {fmt(progressed)}%p "
                f"({'같은 방향' if progressed_consistent else '기간별 방향 변동'})이야."
            )

    for candidate, label in (("MA60", "MA60"), ("ALIGNMENT", "Bullish Alignment")):
        deltas = frame.loc[frame["candidate"].eq(candidate)].copy()
        deltas["_order"] = deltas["period"].map({"P1": 0, "P2-1": 1, "P2-2": 2})
        deltas = deltas.sort_values("_order")
        ten = [float(v) for v in deltas["terminal_le_neg_10_rate_delta_pp"]]
        fifteen = [float(v) for v in deltas["terminal_le_neg_15_rate_delta_pp"]]
        twenty = [float(v) for v in deltas["terminal_le_neg_20_rate_delta_pp"]]
        thirty = [float(v) for v in deltas["terminal_le_neg_30_rate_delta_pp"]]
        medians = []
        for period in ("P1", "P2-1", "P2-2"):
            metrics = period_metrics[period].set_index("strategy")
            medians.append(float(metrics.loc[candidate, "median_terminal_return_pct"]))
        lines.append(
            f"- 공통 위험 {label}: -10/-15% 손실 비율 delta는 {fmt(ten)}/{fmt(fifteen)}%p, "
            f"-20/-30% tail delta는 {fmt(twenty)}/{fmt(thirty)}%p야. 음수는 CONTROL 대비 발생률 감소, "
            f"양수는 증가야. P1/P2-1/P2-2 median terminal은 {fmt(medians)}%야."
        )
    return lines


def historical_rows_by_period(pre: dict[str, Any], period: str) -> int:
    return sum(
        int(item["trades_matching_current_permanent_exclusions"])
        for item in pre["historical_reference"][period]["permanent_exclusion_trade_overlap"].values()
    )


def markdown_report(
    metrics: pd.DataFrame,
    deltas: pd.DataFrame,
    exits: pd.DataFrame,
    checks: dict[str, Any],
    pre: dict[str, Any],
    audit: dict[str, Any],
    repeatability: pd.DataFrame,
    period_metrics: dict[str, pd.DataFrame],
) -> str:
    def f(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"
    historical_rows = sum(
        item["trades_matching_current_permanent_exclusions"]
        for period in ("P1", "P2-1")
        for item in pre["historical_reference"][period]["permanent_exclusion_trade_overlap"].values()
    )
    major_count = int(historical_rows > 0)
    major_message = (
        "과거 P1/P2-1 ledger에 현재 permanent exclusion에 해당하는 거래가 있어 기간 간 비교는 방향성 참고로 제한"
        if major_count else "기간 간 비교에 포함된 과거 거래 authority 차이 없음"
    )
    lines = [
        "# FAST Core V2 P2-2 단순 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 검증 또는 실행 오류 없음 |",
        f"| MAJOR | {major_count} | {major_message} |",
        "| MINOR | 1 | 포트폴리오 equity curve/MDD는 지시 범위 밖이므로 계산하지 않음 |",
        "",
        "## 범위와 입력",
        "",
        f"- 공식 calendar 기간은 2021-01-01~2026-08-31이고 실제 거래일은 {WINDOW['effective_start']}~{WINDOW['effective_end']}; execution support는 {WINDOW['execution_support']}야. cutoff 뒤 신규 진입은 없어.",
        f"- Frozen survivor roster {pre['survivor_identity_roster_count']:,}개 중 최신 exact permanent exclusion authority {pre['permanent_exclusion_registry_count']}개와 겹치는 {pre['survivor_permanent_exclusion_overlap_count']}개를 `(ticker, ISU)`로 제거했어. 2026-10-05 승인 7개 중 roster와 겹친 수는 {pre['newly_approved_7_survivor_overlap_count']}개, 필터 후 roster는 {pre['eligible_survivor_identity_count']:,}개, P2-2 window PIT identity key는 {pre['p2_2_window_pit_identity_key_count']:,}개야.",
        "- CONTROL, MA60 fail-closed, Bullish Alignment은 같은 필터된 survivor identity/PIT, lifecycle, Repository V2, cutoff 및 exact-date MKTCAP 계약을 공유했어. P2-2만 새 replay했어.",
        "- P1/P2-1 결과는 백테스트 입력으로 재사용하지 않았고 반복성 비교에만 읽었어. 이전 ledger에 현재 제외 authority와 겹치는 거래가 있으므로 기간 간 수치는 완전한 동일 universe 비교가 아니야.",
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
        "| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균/중앙 보유 Δ 일 | cutoff-open Δ %p | Loss Guard Δ %p | PROGRESSED Δ %p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in deltas.to_dict("records"):
        lines.append(
            f"| {r['candidate']} | {r['trade_count_delta']} | {f(r['trade_count_reduction_pct'])} | {f(r['realized_win_rate_delta_pp'])} | {f(r['terminal_positive_rate_delta_pp'])} | "
            f"{f(r['average_terminal_delta_pp'])} / {f(r['median_terminal_delta_pp'])} | {f(r['average_realized_delta_pp'])} / {f(r['median_realized_delta_pp'])} | "
            f"{f(r['average_holding_days_delta'])} / {f(r['median_holding_days_delta'])} | {f(r['cutoff_open_rate_delta_pp'])} | {f(r['loss_guard_rate_delta_pp'])} | {f(r['progressed_rate_delta_pp'])} |"
        )
    lines += [
        "",
        "## P1 / P2-1 반복성 평가",
        "",
        "P1/P2-1 delta는 각 기간의 CONTROL 대비 후보 delta야. P2-2는 최신 exact exclusion을 적용했어. 이전 결과에서 제외 목록 identity를 포함한 ledger row가 발견돼 cross-period 평가는 방향성 비교로만 해석해.",
        "",
        "| 기간 | 후보 | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균/중앙 보유 Δ 일 | cutoff-open Δ %p | Loss Guard Δ %p | PROGRESSED Δ %p |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in repeatability.to_dict("records"):
        lines.append(
            f"| {r['period']} | {r['candidate']} | {f(r['trade_count_reduction_pct'])} | {f(r['realized_win_rate_delta_pp'])} | {f(r['terminal_positive_rate_delta_pp'])} | "
            f"{f(r['average_terminal_delta_pp'])} / {f(r['median_terminal_delta_pp'])} | {f(r['average_realized_delta_pp'])} / {f(r['median_realized_delta_pp'])} | "
            f"{f(r['average_holding_days_delta'])} / {f(r['median_holding_days_delta'])} | {f(r['cutoff_open_rate_delta_pp'])} | {f(r['loss_guard_rate_delta_pp'])} | {f(r['progressed_rate_delta_pp'])} |"
        )
    lines += [
        "",
        "### 반복성 해석",
        "",
        *repeatability_assessment(repeatability, period_metrics),
        "",
        "### 대형 승리·손실 rate delta 반복성 (%p)",
        "",
        "| 기간 | 후보 | +20% | +50% | +100% | -10% 이하 | -15% 이하 | -20% 이하 | -30% 이하 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in repeatability.to_dict("records"):
        lines.append(
            f"| {r['period']} | {r['candidate']} | {f(r['terminal_ge_20_rate_delta_pp'])} | {f(r['terminal_ge_50_rate_delta_pp'])} | {f(r['terminal_ge_100_rate_delta_pp'])} | "
            f"{f(r['terminal_le_neg_10_rate_delta_pp'])} | {f(r['terminal_le_neg_15_rate_delta_pp'])} | {f(r['terminal_le_neg_20_rate_delta_pp'])} | {f(r['terminal_le_neg_30_rate_delta_pp'])} |"
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
        "| 전략 | 원본 날짜 non-null (비권위) | 보유 중 PROGRESSED (권위) | 전체 거래 대비 % |",
        "|---|---:|---:|---:|",
    ]
    for r in metrics.to_dict("records"):
        lines.append(f"| {r['strategy']} | {r['progressed_raw_nonempty_field_count']} | {r['progressed_count']} | {f(r['progressed_rate_pct'])} |")
    lines += [
        "",
        "실현 거래는 `entry_execution_date ≤ event ≤ exit_signal_date`, cutoff 미종료는 `entry_execution_date ≤ event ≤ 2026-08-31`, lifecycle 정산 거래는 공식 settlement date까지로 경계를 적용했어. entry 이전과 허용 상한 이후 event는 집계에서 제외했고 per-trade 근거는 `p2_2_progressed_reconciliation_audit.csv`에 있어.",
        "",
        "## Authority / worker / provenance 검증",
        "",
        f"- CONTROL/MA60/Alignment worker는 각 {WORKERS}개, 오류는 각각 0건. 전체 처리 ticker {pre['unique_ticker_count']:,}, P2-2 identity key {pre['p2_2_identity_key_count']:,}, PIT segment {pre['p2_2_identity_segment_count']:,}.",
        f"- 현재 permanent exclusion leakage: {checks['permanent_exclusion_leakage_count']} trade. 정확한 `(ticker, ISU)` 필터와 authority 상세는 `identity_authority_audit.csv`에 있어.",
        f"- Trade key 중복 {checks['duplicate_trade_key_count']}; accepted signal↔trade parity {checks['candidate_signal_parity']}; terminal 수익 재계산 불일치 {checks['net_terminal_recompute_mismatch_count']}; cutoff 뒤 진입 {checks['post_cutoff_entry_count']}.",
        f"- MA60 공식·fail-closed {checks['ma60_filter_check']}; Alignment `signal_day_close > MA20 > MA60`·fail-closed {checks['alignment_filter_check']}; MKTCAP unresolved {checks['control_mcap_unresolved_count']}; network calls {checks['network_calls']}.",
        f"- Frozen PIT SHA-256 `{pre['frozen_pit_sha256']}`; calendar `{pre['frozen_calendar_sha256']}`; survivor roster `{pre['survivor_identity_roster_sha256']}`; permanent exclusion source `{pre['input_source_hashes']['permanent_identity_exclusion_registry']['sha256']}`.",
        f"- P1/P2-1 saved metrics와 trade ledger artifact hash 검증: PASS. 현재 authority와 겹치는 이전 ledger 거래 row는 P1 {historical_rows_by_period(pre, 'P1')}, P2-1 {historical_rows_by_period(pre, 'P2-1')}건이야. 이전 결과에는 백테스트 재실행 없이 검증된 결과만 사용했어.",
        "- 이 작업은 trade-level 비교만 수행했고 portfolio MDD, realistic portfolio, P3-1/P3-2, 5-window 종합 및 공식 채택 판정은 실행하지 않았어.",
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
        pre, frozen, base_run, base_gate, universe, authority, survivors, identity_audit = preflight(module)
        prior_metrics, historical_reference = load_prior_period_references()
        current_cost_contract = {
            "buy_commission_rate": float(pre["cost_contract"]["buy_commission_rate"]),
            "sell_commission_rate": float(pre["cost_contract"]["sell_commission_rate"]),
            "buy_slippage_rate": float(pre["cost_contract"]["buy_slippage_rate"]),
            "sell_slippage_rate": float(pre["cost_contract"]["sell_slippage_rate"]),
            "transaction_tax_in_returns": bool(pre["cost_contract"]["transaction_tax_in_returns"]),
        }
        require(WORKERS == 10 and all(ref["worker_count"] == WORKERS for ref in historical_reference.values()), "PROJECT_WORKER_STANDARD_MISMATCH")
        require(all(ref["cost_contract"] == current_cost_contract for ref in historical_reference.values()), "P2_2_COST_CONTRACT_DIFFERS_FROM_PRIOR_PERIODS")
        require(int(identity_audit["included_in_p2_2"].sum()) == pre["p2_2_identity_key_count"], "IDENTITY_AUTHORITY_AUDIT_CONTEXT_COUNT_MISMATCH")
        pre["historical_reference"] = historical_reference
        pre["cross_period_worker_standard_match"] = True
        pre["cross_period_cost_contract_match"] = True
        pre["historical_comparison_limitation"] = "P1/P2-1 ledgers include rows matching current exact permanent exclusions; use only as directional repeatability reference"
        if "--preflight-only" in sys.argv:
            print(json.dumps({
                "status": "PASS",
                "work_id": WORK_ID,
                "window_id": WINDOW_ID,
                "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
                "window_identity_key_count": pre["p2_2_identity_key_count"],
                "window_segment_count": pre["p2_2_identity_segment_count"],
                "unique_ticker_count": pre["unique_ticker_count"],
                "network_calls": 0,
                "replay_started": False,
                "historical_reference_artifacts_read_only": True,
            }, ensure_ascii=False, indent=2))
            return 0
        write_frame(OUT / "identity_authority_audit.csv", identity_audit)
        write_json(OUT / "prior_period_comparison.json", {
            "status": "PASS",
            "comparison_only": True,
            "backtest_inputs_reused": False,
            "cross_period_cost_contract_match": True,
            "cross_period_worker_standard_match": True,
            "historical_reference": historical_reference,
            "metrics": {period: frame.to_dict("records") for period, frame in prior_metrics.items()},
        })
        write_json(OUT / "preflight.json", pre)
        prices = module.HELPER.PriceCache()
        metrics_raw: list[dict[str, Any]] = []
        STAGE = "P2_2_FULL_REPLAY"
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
        require(len(metrics_raw) == 3 and {m["strategy"] for m in metrics_raw} == set(STRATEGIES), "P2_2_METRICS_INCOMPLETE")
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
                audit_name = f"p2_2_{name.lower()}_signal_audit.csv"
                audit_checks[name] = candidate_audit_check(name, OUT / audit_name, ledger)

        policy_pairs = {
            (str(ticker).zfill(6), str(isu_cd).strip().upper())
            for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
        }
        permanent_exclusion_leakage_count = 0
        for name, ledger in ledgers.items():
            require({"ticker", "isu_cd"}.issubset(ledger.columns), f"{name}_EXCLUSION_AUDIT_KEY_MISSING")
            pairs = list(zip(ledger["ticker"].astype(str).str.zfill(6), ledger["isu_cd"].astype(str).str.strip().str.upper()))
            permanent_exclusion_leakage_count += sum(pair in policy_pairs for pair in pairs)
        require(permanent_exclusion_leakage_count == 0, f"PERMANENT_EXCLUSION_TRADE_LEAKAGE:{permanent_exclusion_leakage_count}")

        control_mcap_path = OUT / "p2_2_control_pit_mcap_audit.csv"
        mcap = pd.read_csv(control_mcap_path, dtype={"ticker": str})
        unresolved = int(mcap.get("status", pd.Series(dtype=str)).astype(str).eq("UNRESOLVED").sum())
        require(unresolved == 0, f"CONTROL_MCAP_UNRESOLVED_ROWS:{unresolved}")
        require(not mcap.empty, "CONTROL_MCAP_AUDIT_EMPTY")
        mcap_keys = ["ticker", "identity", "market", "signal_date"]
        require(all(col in mcap.columns for col in mcap_keys), "CONTROL_MCAP_AUDIT_KEY_MISSING")
        for col in mcap_keys:
            mcap[col] = mcap[col].astype(str)
        mcap_exclusion_pairs = list(zip(mcap["ticker"].astype(str).str.zfill(6), mcap["identity"].astype(str).str.strip().str.upper()))
        control_mcap_permanent_exclusion_leakage_count = sum(pair in policy_pairs for pair in mcap_exclusion_pairs)
        require(control_mcap_permanent_exclusion_leakage_count == 0, f"PERMANENT_EXCLUSION_MKTCAP_AUDIT_LEAKAGE:{control_mcap_permanent_exclusion_leakage_count}")
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
        write_frame(OUT / "p2_2_strategy_metrics.csv", metric_frame)
        write_frame(OUT / "p2_2_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p2_2_large_outcomes.csv", threshold_frame)
        if progression_frames:
            progression = pd.concat(progression_frames, ignore_index=True)
        else:
            progression = pd.DataFrame()
        write_frame(OUT / "p2_2_progressed_reconciliation_audit.csv", progression)
        exit_rows = []
        for name, frame in ledgers.items():
            values = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("(none)").astype(str).value_counts()
            exit_rows.extend({"strategy": name, "exit_type": key, "count": int(value)} for key, value in values.items())
        exit_frame = pd.DataFrame(exit_rows)
        write_frame(OUT / "p2_2_exit_reason_distribution.csv", exit_frame)
        price_audit = pd.DataFrame(prices.audit.values())
        write_frame(OUT / "p2_2_price_store_audit.csv", price_audit)

        repeatability = repeatability_delta_frame(prior_metrics, metric_frame)
        period_metrics = {**prior_metrics, "P2-2": metric_frame}
        write_frame(OUT / "p2_2_repeatability_vs_control.csv", repeatability)

        strategy_worker_error_counts = {
            name: len(execution["execution"][name].get("worker_errors", []))
            for name in STRATEGIES
        }
        strategy_worker_counts = {
            name: int(execution["execution"][name].get("worker_count", 0))
            for name in STRATEGIES
        }
        checks = {
            "worker_error_count": int(sum(strategy_worker_error_counts.values())),
            "strategy_worker_error_counts": strategy_worker_error_counts,
            "strategy_worker_counts": strategy_worker_counts,
            "workers": WORKERS,
            "duplicate_trade_key_count": int(sum(frame["pair_id"].astype(str).duplicated().sum() for frame in ledgers.values())),
            "candidate_signal_parity": all(a.get("accepted_signal_trade_parity") for a in audit_checks.values()),
            "ma60_filter_check": audit_checks.get("MA60", {}).get("filter_formula_and_fail_closed", False),
            "alignment_filter_check": audit_checks.get("ALIGNMENT", {}).get("filter_formula_and_fail_closed", False),
            "net_terminal_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
            "post_cutoff_entry_count": int(sum(pd.to_datetime(frame["entry_execution_date"], errors="coerce").gt(cutoff).sum() for frame in ledgers.values())),
            "control_mcap_unresolved_count": unresolved,
            "control_mcap_trade_entry_pass": True,
            "permanent_exclusion_leakage_count": permanent_exclusion_leakage_count,
            "control_mcap_permanent_exclusion_leakage_count": control_mcap_permanent_exclusion_leakage_count,
            "network_calls": network_calls,
            "processed_ticker_count_each_strategy": pre["unique_ticker_count"],
            "identity_key_count": pre["p2_2_identity_key_count"],
            "identity_segment_count": pre["p2_2_identity_segment_count"],
            "candidate_audits": audit_checks,
            "trade_file_hashes": all_hashes,
            "price_partition_count": int(len(price_audit)),
            "price_partition_hash_metadata_checks_pass": bool(price_audit.empty or (price_audit["metadata_row_count_matches"].astype(bool).all() and price_audit["metadata_date_range_matches"].astype(bool).all())),
        }
        require(checks["worker_error_count"] == 0 and all(count == WORKERS for count in strategy_worker_counts.values()), "STRATEGY_WORKER_COMPLETION_INTEGRITY_FAILURE")
        require(checks["candidate_signal_parity"] and checks["ma60_filter_check"] and checks["alignment_filter_check"], "CANDIDATE_SIGNAL_OR_FILTER_INTEGRITY_FAILURE")
        require(checks["price_partition_hash_metadata_checks_pass"], "PRICE_PARTITION_HASH_METADATA_CHECK_FAILED")
        require(checks["duplicate_trade_key_count"] == 0, "DUPLICATE_TRADE_KEY")
        require(checks["post_cutoff_entry_count"] == 0, "POST_CUTOFF_ENTRY")
        require(checks["permanent_exclusion_leakage_count"] == 0 and checks["control_mcap_permanent_exclusion_leakage_count"] == 0, "PERMANENT_EXCLUSION_LEAKAGE")

        STAGE = "COMPRESS_AND_FINALIZE"
        compressed = []
        for name in (
            "p2_2_control_pit_mcap_audit.csv",
            "p2_2_ma60_signal_audit.csv",
            "p2_2_alignment_signal_audit.csv",
            "p2_2_price_store_audit.csv",
        ):
            compressed.append(compress_verified(OUT / name).name)
        execution.update({
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "worker_count": WORKERS,
            "worker_errors": [],
            "identity_key_count": pre["p2_2_identity_key_count"],
            "identity_segment_count": pre["p2_2_identity_segment_count"],
            "processed_ticker_count_each_strategy": pre["unique_ticker_count"],
            "strategy_trade_counts": {name: int(len(frame)) for name, frame in ledgers.items()},
            "progressed_counts_authoritative": {str(row["strategy"]): int(row["progressed_count"]) for row in metrics},
            "checks": checks,
            "compressed_verified_audits": compressed,
            "elapsed_seconds": time.perf_counter() - started,
        })
        write_json(OUT / "p2_2_execution_audit.json", execution)
        write_frame(OUT / "p2_2_strategy_metrics_reconciled.csv", metric_frame)
        report = markdown_report(metric_frame, deltas, exit_frame, checks, pre, {"threshold_frame": threshold_frame}, repeatability, period_metrics)
        (OUT / "report.md").write_text(report, encoding="utf-8")
        input_hashes = pre["input_source_hashes"]
        artifact_hashes = {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name not in {"p2_2_provenance.json", "run_p2_2_simple_backtest.py"}
        }
        provenance = {
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "work_id": WORK_ID,
            "scope": "P2-2 trade-level simple backtest only",
            "window": WINDOW,
            "worker_count": WORKERS,
            "network_calls": network_calls,
            "result_reuse": pre["result_reuse"],
            "historical_reference": historical_reference,
            "authority": {
                "frozen_pit_sha256": pre["frozen_pit_sha256"],
                "frozen_calendar_sha256": pre["frozen_calendar_sha256"],
                "frozen_manifest_sha256": pre["frozen_manifest_sha256"],
                "survivor_identity_roster_sha256": pre["survivor_identity_roster_sha256"],
                "survivor_identity_roster_count": pre["survivor_identity_roster_count"],
                "p2_2_identity_key_count": pre["p2_2_identity_key_count"],
                "p2_2_identity_segment_count": pre["p2_2_identity_segment_count"],
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
            "cross_period_cost_contract_match": True,
            "cross_period_worker_standard_match": True,
            "metrics_progressed_basis": "entry execution <= event <= exit signal for REALIZED; <= effective cutoff for OPEN_AT_CUTOFF; <= settlement date for LIFECYCLE_SETTLED",
            "no_portfolio_mdd": True,
            "integrity": checks,
            "artifact_sha256": artifact_hashes,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(OUT / "p2_2_provenance.json", provenance)
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
