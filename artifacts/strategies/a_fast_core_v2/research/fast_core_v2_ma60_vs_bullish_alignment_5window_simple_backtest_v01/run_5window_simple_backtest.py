#!/usr/bin/env python3
"""Run the five-window, trade-level MA60 vs bullish-alignment comparison."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import csv
import gc
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

OUT = Path(__file__).resolve().parent
WORKERS = 10
WINDOWS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
EXPECTED_WINDOWS = {
    "P1": ("2014-01-02", "2026-08-31", "2026-09-01"),
    "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
    "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
    "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
    "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
}
CONTROL_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
MA60_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER"
ALIGNMENT_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT"
FINAL_TOKEN = "FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01_PASS"
CHECK_TOKEN = "FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01_CHECK_REQUIRED"
FAIL_TOKEN = "FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01_FAIL"

CONTROL_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
MA60_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_entry_filter_backtest_v01"
ALIGNMENT_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_bullish_alignment_backtest_v01"
P3_DIR = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01"
PIT_EXTENSION_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
P3_SOURCE_COMMIT = "f3b505a40"
MA60_SOURCE_COMMIT = "8edb3f5179ff1c9608fc79ec01f93c4fc596ae89"
WORK_ID = "FAST_CORE_V2_MA60_VS_BULLISH_ALIGNMENT_5WINDOW_SIMPLE_BACKTEST_V01"
CURRENT_STAGE = "STARTUP"
CANDIDATE_REPLAY_STARTED = False


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HELPER = load_module(
    "five_window_monthly_ma_helpers",
    MA60_DIR / "run_monthly_ma_entry_filter_backtest.py",
)
ALIGNMENT = load_module(
    "five_window_bullish_alignment_helpers",
    ALIGNMENT_DIR / "run_bullish_alignment_backtest.py",
)
STRATEGY = load_module(
    "five_window_fastcore_strategy",
    ROOT / "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
)
PORTFOLIO = load_module(
    "five_window_exact_mcap_gate",
    ROOT / "scripts/run_p2_1_realistic_portfolio_v01.py",
)
from trend_scanner.backtest.standard_windows import resolve_standard_backtest_window
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2

COMM_RATE = float(PORTFOLIO.COMMISSION_RATE)
SLIP_RATE = float(PORTFOLIO.SLIPPAGE_RATE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def verify_head_blob(path: Path) -> None:
    relative = path.relative_to(ROOT).as_posix()
    committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
    require(committed == path.read_bytes(), f"TRACKED_ARTIFACT_DIFFERS_FROM_HEAD:{relative}")


def preflight() -> dict[str, Any]:
    allowed = {"run_5window_simple_backtest.py", "__pycache__"}
    unexpected = sorted(item.name for item in OUT.iterdir() if item.name not in allowed)
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git_text("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git_text("rev-parse", "HEAD"), git_text("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git_text("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")

    frozen_summary = read_json(CONTROL_DIR / "summary.json")
    frozen_preflight = read_json(CONTROL_DIR / "preflight.json")
    ma60_summary = read_json(MA60_DIR / "summary.json")
    ma60_preflight = read_json(MA60_DIR / "preflight.json")
    alignment_summary = read_json(ALIGNMENT_DIR / "summary.json")
    alignment_preflight = read_json(ALIGNMENT_DIR / "preflight.json")

    require(frozen_summary.get("status") == "COMPLETE", "FROZEN_CONTROL_NOT_COMPLETE")
    require(frozen_summary.get("final_token") == "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE", "FROZEN_CONTROL_TOKEN_MISMATCH")
    require(frozen_summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    require(ma60_summary.get("status") == "COMPLETE" and ma60_summary.get("final_token") == "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_COMPLETE", "SAVED_MA60_NOT_COMPLETE")
    require(ma60_preflight.get("status") == "PASS" and ma60_preflight.get("control_replayed") is False, "SAVED_MA60_PREFLIGHT_INVALID")
    require(ma60_preflight.get("workers") == WORKERS, "SAVED_MA60_WORKER_COUNT_MISMATCH")
    require(ma60_summary.get("integrity_checks", {}).get("all_candidate_checks_pass") is True, "SAVED_MA60_INTEGRITY_FAILED")
    require(ma60_summary.get("worker_results", {}).get("MA60", {}).get("worker_errors") == 0, "SAVED_MA60_WORKER_ERROR")
    require(alignment_summary.get("final_token") == "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01_COMPLETE", "SAVED_ALIGNMENT_NOT_COMPLETE")
    require(alignment_summary.get("exact_rule") == "signal_day_close > prior_completed_month_MA20 > prior_completed_month_MA60", "SAVED_ALIGNMENT_RULE_MISMATCH")
    require(alignment_summary.get("ma_unavailable_policy") == "FAIL_CLOSED", "SAVED_ALIGNMENT_UNAVAILABLE_POLICY_MISMATCH")
    require(alignment_preflight.get("frozen_authority", {}).get("status") == "PASS", "SAVED_ALIGNMENT_AUTHORITY_NOT_PASS")
    require(alignment_summary.get("integrity_checks", {}).get("all_candidate_trades_pass_alignment") is True, "SAVED_ALIGNMENT_RULE_LEAK")
    require(alignment_summary.get("integrity_checks", {}).get("worker_count") == WORKERS, "SAVED_ALIGNMENT_WORKER_COUNT_MISMATCH")
    require(alignment_summary.get("integrity_checks", {}).get("worker_errors") == 0, "SAVED_ALIGNMENT_WORKER_ERROR")

    trade_paths = {
        "control": CONTROL_DIR / "control_strategy_trades.csv",
        "ma60": MA60_DIR / "ma60_strategy_trades.csv",
        "alignment": ALIGNMENT_DIR / "alignment_strategy_trades.csv",
    }
    for path in trade_paths.values():
        verify_head_blob(path)
    require(len(pd.read_csv(trade_paths["control"])) == 405, "SAVED_P3_CONTROL_COUNT_MISMATCH")
    require(len(pd.read_csv(trade_paths["ma60"])) == 337, "SAVED_P3_MA60_COUNT_MISMATCH")
    require(len(pd.read_csv(trade_paths["alignment"])) == 179, "SAVED_P3_ALIGNMENT_COUNT_MISMATCH")

    strategy_source = ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py"
    expected_strategy_sha = ma60_preflight["source_provenance"]["strategy_source_sha256"]
    require(sha256(strategy_source) == expected_strategy_sha, "P3_STRATEGY_SOURCE_HASH_MISMATCH")
    require(git_text("diff", "--quiet", MA60_SOURCE_COMMIT, "HEAD", "--", "scripts/run_fastcore_neg40_weak_protect_p2_1.py") == "", "CORE_RUNNER_CHANGED_SINCE_SAVED_REPLAY")

    # A later governance commit changed only portfolio valuation/MDD logic. The
    # simple strategy source, trade runner, P3 trade ledgers, PIT and prices are
    # byte-identical, so those portfolio-only changes do not invalidate these
    # frozen trade-level results.
    changed_since_alignment = subprocess.check_output(
        ["git", "diff", "--name-only", P3_SOURCE_COMMIT, "HEAD"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    portfolio_runner = "scripts/run_p3_2_realistic_portfolio_v01.py"
    # Later commits added the saved MA60/alignment and partial five-window
    # research outputs. Keep this guard focused on implementation changes;
    # exact frozen P3 trade ledgers and PIT/calendar inputs are hash-checked
    # below and above.
    changed_source_paths = {path for path in changed_since_alignment if path.endswith(".py")}
    require(changed_source_paths.issubset({
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/finalize_partial_report.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_bullish_alignment_backtest_v01/run_bullish_alignment_backtest.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma60_available_only_entry_filter_backtest_v01/recover_saved_outputs.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma60_available_only_entry_filter_backtest_v01/run_monthly_ma60_available_only_backtest.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_portfolio_valuation_gap_contract_alignment_v01/run_valuation_gap_contract_alignment.py",
        "scripts/run_p2_1_realistic_portfolio_v01.py",
        "scripts/run_p2_2_realistic_portfolio_v01.py",
        portfolio_runner,
        "tests/test_p2_1_realistic_portfolio_v01.py",
        "tests/test_p3_2_realistic_portfolio_v01.py",
    }), "UNEXPECTED_POST_P3_SOURCE_CHANGES")
    source_diff = subprocess.check_output(
        ["git", "diff", "--unified=0", P3_SOURCE_COMMIT, "HEAD", "--", portfolio_runner],
        cwd=ROOT,
        text=True,
    )
    require("valuation" in source_diff.lower() and "mdd" in source_diff.lower(), "PORTFOLIO_ONLY_CHANGE_SCOPE_UNVERIFIED")

    for path in [
        CONTROL_DIR / "control_strategy_trades.csv",
        MA60_DIR / "ma60_strategy_trades.csv",
        ALIGNMENT_DIR / "alignment_strategy_trades.csv",
        PIT_EXTENSION_DIR / "merged_pit_intervals.json",
        PIT_EXTENSION_DIR / "merged_trading_calendar.json",
    ]:
        verify_head_blob(path)
    return {
        "status": "PASS",
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "worker_count": WORKERS,
        "p3_saved_results_reused": True,
        "p3_control_trade_count": 405,
        "p3_ma60_trade_count": 337,
        "p3_alignment_trade_count": 179,
        "p3_trade_artifacts_match_head": True,
        "p3_saved_survivor_audit_sha256": frozen_preflight.get("frozen_authority", {}).get("saved_survivor_audit_sha256"),
        "p3_frozen_pit_sha256": frozen_preflight.get("frozen_authority", {}).get("historical_pit_sha256"),
        "p3_frozen_calendar_sha256": frozen_preflight.get("frozen_authority", {}).get("calendar_sha256"),
        "strategy_source_sha256": sha256(strategy_source),
        "base_trade_runner_sha256": sha256(ROOT / "scripts/run_fastcore_neg40_weak_protect_p2_1.py"),
        "post_p3_changes": changed_since_alignment,
        "post_p3_change_scope": "portfolio valuation gap / portfolio MDD governance only; no simple trade, identity, PIT or price generation changes",
        "cost_contract": {
            "buy_commission_rate": COMM_RATE,
            "sell_commission_rate": COMM_RATE,
            "buy_slippage_rate": SLIP_RATE,
            "sell_slippage_rate": SLIP_RATE,
            "transaction_tax_in_official_returns": False,
            "source": "scripts/run_p2_1_realistic_portfolio_v01.py and scripts/run_pattern_b_pure_simple_backtest_v01.py",
        },
        "mdd_contract": "NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY",
        "latest_authority_reads": 0,
        "network_calls": 0,
    }


class NetworkBlocked(RuntimeError):
    pass


def network_guard():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    audit = {"calls": 0}

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit["calls"] += 1
        raise NetworkBlocked(f"offline backtest blocked socket connect to {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit["calls"] += 1
        raise NetworkBlocked(f"offline backtest blocked socket connect_ex to {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    return original_connect, original_connect_ex, audit


def restore_network_guard(state: tuple[Any, Any, dict[str, int]]) -> None:
    socket.socket.connect, socket.socket.connect_ex, _ = state


def load_frozen_context():
    frozen = HELPER.load_frozen_runner()
    run, gate, universe, authority = frozen._load_frozen_context()
    survivors = frozenset(
        (
            str(row.ticker).zfill(6),
            str(row.isu_cd).strip().upper(),
            str(row.market).strip().upper(),
        )
        for row in universe.loc[universe["status"].eq("SURVIVOR_COMMON_IDENTITY")].itertuples(index=False)
    )
    require(len(survivors) == 2539, "FROZEN_SURVIVOR_IDENTITY_COUNT_MISMATCH")
    require(len(run.authority.pit_intervals) > 0, "FROZEN_PIT_INTERVALS_EMPTY")
    return frozen, run, gate, universe, authority, survivors


def context_for_window(base_run: Any, gate: Any, survivors: frozenset[tuple[str, str, str]], window_id: str):
    window = resolve_standard_backtest_window(window_id, base_run.calendar)
    actual = tuple(
        value.strftime("%Y-%m-%d")
        for value in (window.effective_start, window.effective_end, window.execution_support)
    )
    require(actual == EXPECTED_WINDOWS[window_id], f"{window_id}_WINDOW_BOUNDARY_MISMATCH:{actual}")
    segments = []
    for row in base_run.authority.pit_intervals:
        key = (
            str(row.get("ticker", "")).zfill(6),
            str(row.get("isu_cd", "")).strip().upper(),
            str(row.get("market", "")).strip().upper(),
        )
        if row.get("state") != "COMMON" or key not in survivors:
            continue
        start, end = pd.Timestamp(row["effective_from"]).normalize(), pd.Timestamp(row["effective_to"]).normalize()
        if start > window.effective_end or end < window.effective_start:
            continue
        require(start <= end, f"{window_id}_INVALID_PIT_INTERVAL:{key}")
        segments.append(
            STRATEGY.IdentitySegment(
                ticker=key[0],
                isu_cd=key[1],
                market=key[2],
                effective_from=start,
                effective_to=end,
            )
        )
    segments.sort(key=lambda item: (item.ticker, item.effective_from, item.effective_to, item.isu_cd))
    by_ticker: dict[str, list[Any]] = {}
    prior: dict[str, Any] = {}
    for segment in segments:
        previous = prior.get(segment.ticker)
        require(
            previous is None or segment.effective_from > previous.effective_to,
            f"{window_id}_OVERLAPPING_IDENTITY_INTERVAL:{segment.key}",
        )
        prior[segment.ticker] = segment
        by_ticker.setdefault(segment.ticker, []).append(segment)
    require(by_ticker, f"{window_id}_EMPTY_SURVIVOR_PIT_POPULATION")
    repo_loader = RepositoryV2DailyLoader(
        base_run.loader.repository,
        end=window.execution_support,
    )
    scoped_gate = PORTFOLIO.ExactRawMcapGate(ROOT, json.loads(base_run.authority.pit_path.read_text(encoding="utf-8")))
    scoped_gate.active_identity_keys = survivors
    scoped_run = replace(
        base_run,
        window=window,
        segments_by_ticker={ticker: tuple(rows) for ticker, rows in sorted(by_ticker.items())},
        loader=repo_loader,
        entry_signal_gate=scoped_gate,
    )
    return scoped_run, scoped_gate, {
        "window_id": window_id,
        "effective_start": actual[0],
        "effective_end": actual[1],
        "execution_support": actual[2],
        "survivor_identity_count": len(survivors),
        "common_pit_segment_count": len(segments),
        "unique_ticker_count": len(by_ticker),
        "identity_scope": "saved P3-2 exact survivor roster applied to frozen merged COMMON PIT intervals",
    }


def run_control(run: Any, gate: Any, workers: int = WORKERS) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    started = time.perf_counter()
    tickers = sorted(run.segments_by_ticker)

    def process(ticker: str) -> dict[str, Any]:
        result = STRATEGY._process_ticker(ticker, run, official_v2_only=True)
        result["worker_thread"] = threading.current_thread().name
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="simple-control") as pool:
        futures = {pool.submit(process, ticker): ticker for ticker in tickers}
        for index, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if index % 50 == 0 or index == len(futures):
                trades = sum(len(item.get("control_rows", ())) for item in outcomes)
                print(
                    f"CONTROL progress {index}/{len(futures)} trades={trades} "
                    f"mcap_audits={len(gate.audit_frame())} errors={len(errors)} "
                    f"elapsed={time.perf_counter()-started:.1f}s",
                    flush=True,
                )
    require(not errors, "CONTROL_WORKER_ERRORS:" + json.dumps(errors[:10], ensure_ascii=False))
    records = pd.DataFrame([row for item in outcomes for row in item.get("control_rows", ())])
    if not records.empty:
        records = records.sort_values(
            ["ticker", "identity_effective_from", "trade_sequence"],
            kind="mergesort",
        ).reset_index(drop=True)
    timing = {
        "worker_count": workers,
        "worker_errors": errors,
        "ticker_count": len(tickers),
        "strategy_trade_count": int(len(records)),
        "elapsed_seconds": time.perf_counter() - started,
    }
    mcap = gate.audit_frame().copy()
    del outcomes
    gc.collect()
    return records, timing, mcap


def reset_gate_audit(gate: Any) -> None:
    with gate._lock:
        gate._audit.clear()


def net_terminal_return(row: Mapping[str, Any]) -> float | None:
    entry = pd.to_numeric(pd.Series([row.get("entry_open")]), errors="coerce").iloc[0]
    if pd.isna(entry) or not math.isfinite(float(entry)) or float(entry) <= 0:
        return None
    status = str(row.get("trade_status") or "")
    buy_cash = float(entry) * (1.0 + SLIP_RATE) * (1.0 + COMM_RATE)
    if status == "REALIZED":
        price = pd.to_numeric(pd.Series([row.get("exit_price")]), errors="coerce").iloc[0]
        if pd.isna(price) or not math.isfinite(float(price)) or float(price) <= 0:
            return None
        sell_cash = float(price) * (1.0 - SLIP_RATE) * (1.0 - COMM_RATE)
        return (sell_cash / buy_cash - 1.0) * 100.0
    price_raw = row.get("terminal_valuation_price")
    if price_raw is None or str(price_raw).strip().lower() in {"", "nan", "none"}:
        price_raw = row.get("cutoff_valuation_price")
    price = pd.to_numeric(pd.Series([price_raw]), errors="coerce").iloc[0]
    if pd.isna(price) or not math.isfinite(float(price)) or float(price) <= 0:
        return None
    return (float(price) / buy_cash - 1.0) * 100.0


def add_costed_returns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        out["net_terminal_return_pct"] = pd.Series(dtype=float)
        out["net_realized_return_pct"] = pd.Series(dtype=float)
        return out
    terminal = [net_terminal_return(row) for row in out.to_dict("records")]
    out["net_terminal_return_pct"] = terminal
    out["net_realized_return_pct"] = [
        value if str(status) == "REALIZED" else None
        for value, status in zip(terminal, out["trade_status"])
    ]
    return out


def metric_summary(frame: pd.DataFrame, window_id: str, strategy_name: str, strategy_id: str) -> dict[str, Any]:
    records = frame.to_dict("records")
    total = len(records)
    terminal = pd.to_numeric(frame.get("net_terminal_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    realized_frame = frame.loc[frame.get("trade_status", pd.Series(dtype=str)).eq("REALIZED")]
    realized = pd.to_numeric(realized_frame.get("net_realized_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    holding = pd.to_numeric(frame.get("holding_days", pd.Series(dtype=float)), errors="coerce").dropna()
    positive = int((terminal > 0).sum())
    realized_positive = int((realized > 0).sum())
    progressed = frame.get("first_progressed_effective_trading_date", pd.Series([None] * total)).notna()
    loss_guard = frame.get("exit_type", pd.Series([""] * total)).astype(str).eq("LOSS_GUARD_CLOSE_LE_NEG_15")
    thresholds = {
        "terminal_ge_20_count": int((terminal >= 20).sum()),
        "terminal_ge_50_count": int((terminal >= 50).sum()),
        "terminal_ge_100_count": int((terminal >= 100).sum()),
        "terminal_le_neg_10_count": int((terminal <= -10).sum()),
        "terminal_le_neg_15_count": int((terminal <= -15).sum()),
        "terminal_le_neg_20_count": int((terminal <= -20).sum()),
        "terminal_le_neg_30_count": int((terminal <= -30).sum()),
    }
    for name, count in list(thresholds.items()):
        thresholds[name.replace("_count", "_rate_pct")] = float(count / total * 100.0) if total else None
    exits = frame.get("exit_type", pd.Series(dtype=str)).fillna("").astype(str).value_counts().to_dict()
    statuses = frame.get("trade_status", pd.Series(dtype=str)).fillna("").astype(str).value_counts().to_dict()
    end = pd.Timestamp(EXPECTED_WINDOWS[window_id][1])
    support = pd.Timestamp(EXPECTED_WINDOWS[window_id][2])
    entry_exec = pd.to_datetime(frame.get("entry_execution_date", pd.Series(dtype=str)), errors="coerce")
    exit_exec = pd.to_datetime(frame.get("exit_execution_date", pd.Series(dtype=str)), errors="coerce")
    open_count = int(frame.get("trade_status", pd.Series(dtype=str)).eq("OPEN_AT_CUTOFF").sum())
    resolved_terminal_count = int(terminal.notna().sum())
    def quantile(values: pd.Series, q: float) -> float | None:
        return float(values.quantile(q)) if len(values) else None
    return {
        "window_id": window_id,
        "strategy": strategy_name,
        "strategy_id": strategy_id,
        "trade_count": total,
        "realized_count": int(frame.get("trade_status", pd.Series(dtype=str)).eq("REALIZED").sum()),
        "open_at_cutoff_count": open_count,
        "terminal_return_available_count": resolved_terminal_count,
        "realized_return_available_count": int(len(realized)),
        "realized_win_rate_pct": float(realized_positive / len(realized) * 100.0) if len(realized) else None,
        "terminal_positive_rate_pct": float(positive / len(terminal) * 100.0) if len(terminal) else None,
        "average_terminal_return_pct": float(terminal.mean()) if len(terminal) else None,
        "median_terminal_return_pct": float(terminal.median()) if len(terminal) else None,
        "min_terminal_return_pct": float(terminal.min()) if len(terminal) else None,
        "max_terminal_return_pct": float(terminal.max()) if len(terminal) else None,
        "p25_terminal_return_pct": quantile(terminal, 0.25),
        "p75_terminal_return_pct": quantile(terminal, 0.75),
        "average_realized_return_pct": float(realized.mean()) if len(realized) else None,
        "median_realized_return_pct": float(realized.median()) if len(realized) else None,
        "min_realized_return_pct": float(realized.min()) if len(realized) else None,
        "max_realized_return_pct": float(realized.max()) if len(realized) else None,
        "p25_realized_return_pct": quantile(realized, 0.25),
        "p75_realized_return_pct": quantile(realized, 0.75),
        "average_holding_days": float(holding.mean()) if len(holding) else None,
        "median_holding_days": float(holding.median()) if len(holding) else None,
        "min_holding_days": float(holding.min()) if len(holding) else None,
        "max_holding_days": float(holding.max()) if len(holding) else None,
        "progressed_count": int(progressed.sum()),
        "progressed_rate_pct": float(progressed.sum() / total * 100.0) if total else None,
        "loss_guard_exit_count": int(loss_guard.sum()),
        "loss_guard_rate_pct": float(loss_guard.sum() / total * 100.0) if total else None,
        "support_date_entry_execution_count": int((entry_exec.dt.normalize() > end).sum()),
        "support_date_exit_execution_count": int((exit_exec.dt.normalize() > end).sum()),
        "entries_after_support_count": int((entry_exec.dt.normalize() > support).sum()),
        "exit_reason_distribution_json": json.dumps(exits, ensure_ascii=False, sort_keys=True),
        "trade_status_distribution_json": json.dumps(statuses, ensure_ascii=False, sort_keys=True),
        "mdd_pct": None,
        "mdd_status": "NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY",
        **thresholds,
    }


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, encoding="utf-8")


def run_sample(base_run: Any, gate: Any, survivors: frozenset[tuple[str, str, str]], prices: Any) -> dict[str, Any]:
    run, scoped_gate, context = context_for_window(base_run, gate, survivors, "P1")
    tickers = sorted(run.segments_by_ticker)
    sample_count = min(50, len(tickers))
    indices = sorted(set(np.linspace(0, len(tickers) - 1, sample_count, dtype=int).tolist()))
    sample_tickers = [tickers[index] for index in indices]
    sample_run = replace(
        run,
        segments_by_ticker={ticker: run.segments_by_ticker[ticker] for ticker in sample_tickers},
    )
    observations = {}
    reset_gate_audit(scoped_gate)
    control, control_timing, _ = run_control(sample_run, scoped_gate)
    observations["CONTROL"] = control_timing
    del control
    reset_gate_audit(scoped_gate)
    ma60, ma60_result, _ma60_audit, ma60_elapsed = HELPER.candidate_replay(
        sample_run, scoped_gate, prices, "MA60", 60, official_v2_only=True
    )
    observations["MA60"] = {
        "worker_count": WORKERS,
        "worker_errors": ma60_result.get("worker_errors", []),
        "ticker_count": sample_count,
        "strategy_trade_count": int(len(ma60)),
        "elapsed_seconds": ma60_elapsed,
    }
    del ma60, ma60_result, _ma60_audit
    reset_gate_audit(scoped_gate)
    alignment, alignment_result, _alignment_audit = ALIGNMENT.candidate_replay(
        HELPER, sample_run, scoped_gate, prices, official_v2_only=True
    )
    observations["ALIGNMENT"] = {
        "worker_count": WORKERS,
        "worker_errors": alignment_result.get("worker_errors", []),
        "ticker_count": sample_count,
        "strategy_trade_count": int(len(alignment)),
        "elapsed_seconds": float(alignment_result.get("elapsed_seconds", 0.0)),
    }
    del alignment, alignment_result, _alignment_audit
    for name, value in observations.items():
        require(value.get("worker_count") == WORKERS and value.get("worker_errors") == [], f"SAMPLE_{name}_ERROR")
    estimates = {
        name: {
            "estimated_full_seconds": value["elapsed_seconds"] * len(tickers) / sample_count,
            "estimated_full_hours": value["elapsed_seconds"] * len(tickers) / sample_count / 3600.0,
        }
        for name, value in observations.items()
    }
    return {
        "status": "PASS",
        "window_id": "P1",
        "worker_count": WORKERS,
        "sampled_tickers": sample_count,
        "target_tickers": len(tickers),
        "sample_ticker_selection": "evenly spaced over sorted frozen survivor ticker list",
        "sample_runs": observations,
        "rough_full_window_estimate": estimates,
        "warning": "Linear estimate only; P1 runtime varies by ticker history and signal count.",
        "population": context,
    }


def save_p3_reused(
    window_id: str,
    control: pd.DataFrame,
    ma60: pd.DataFrame,
    alignment: pd.DataFrame,
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    sources = {
        "CONTROL": (control, CONTROL_ID),
        "MA60": (ma60, MA60_ID),
        "ALIGNMENT": (alignment, ALIGNMENT_ID),
    }
    counts = {}
    for name, (frame, strategy_id) in sources.items():
        costed = add_costed_returns(frame)
        file_path = OUT / f"{window_id.lower().replace('-', '_')}_{name.lower()}_trades.csv"
        costed.to_csv(file_path, index=False, encoding="utf-8")
        metrics.append(metric_summary(costed, window_id, name, strategy_id))
        counts[name] = len(costed)
    for src, target in [
        (CONTROL_DIR / "control_pit_mcap_audit.csv", OUT / "p3_2_control_pit_mcap_audit.csv"),
        (MA60_DIR / "ma60_signal_audit.csv", OUT / "p3_2_ma60_signal_audit.csv"),
        (ALIGNMENT_DIR / "alignment_signal_audit.csv", OUT / "p3_2_alignment_signal_audit.csv"),
    ]:
        pd.read_csv(src).to_csv(target, index=False, encoding="utf-8")
    return {
        "window_id": window_id,
        "reused_saved_trade_ledgers": True,
        "replay_started": False,
        "strategy_trade_counts": counts,
        "source_artifacts": {
            "control": str((CONTROL_DIR / "control_strategy_trades.csv").relative_to(ROOT)),
            "ma60": str((MA60_DIR / "ma60_strategy_trades.csv").relative_to(ROOT)),
            "alignment": str((ALIGNMENT_DIR / "alignment_strategy_trades.csv").relative_to(ROOT)),
        },
    }


def run_full_window(
    window_id: str,
    base_run: Any,
    gate: Any,
    survivors: frozenset[tuple[str, str, str]],
    prices: Any,
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    run, scoped_gate, context = context_for_window(base_run, gate, survivors, window_id)
    execution = {}
    reset_gate_audit(scoped_gate)
    control, control_timing, mcap_audit = run_control(run, scoped_gate)
    execution["CONTROL"] = control_timing
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_control_pit_mcap_audit.csv", mcap_audit)
    del mcap_audit
    costed_control = add_costed_returns(control)
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_control_trades.csv", costed_control)
    metrics.append(metric_summary(costed_control, window_id, "CONTROL", CONTROL_ID))

    reset_gate_audit(scoped_gate)
    ma60, ma60_result, ma60_audit, ma60_elapsed = HELPER.candidate_replay(
        run, scoped_gate, prices, "MA60", 60, official_v2_only=True
    )
    execution["MA60"] = {
        "worker_count": WORKERS,
        "worker_errors": ma60_result.get("worker_errors", []),
        "ticker_count": int(ma60_result.get("ticker_count", len(run.segments_by_ticker))),
        "strategy_trade_count": int(len(ma60)),
        "raw_signal_audit_count": int(len(ma60_audit)),
        "elapsed_seconds": ma60_elapsed,
    }
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_ma60_signal_audit.csv", ma60_audit)
    costed_ma60 = add_costed_returns(ma60)
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_ma60_trades.csv", costed_ma60)
    metrics.append(metric_summary(costed_ma60, window_id, "MA60", MA60_ID))
    require(not execution["MA60"]["worker_errors"], f"{window_id}_MA60_WORKER_ERRORS")
    del ma60_result, ma60_audit, ma60, costed_ma60
    gc.collect()

    reset_gate_audit(scoped_gate)
    alignment, alignment_result, alignment_audit = ALIGNMENT.candidate_replay(
        HELPER, run, scoped_gate, prices, official_v2_only=True
    )
    execution["ALIGNMENT"] = {
        "worker_count": WORKERS,
        "worker_errors": alignment_result.get("worker_errors", []),
        "ticker_count": int(alignment_result.get("ticker_count", len(run.segments_by_ticker))),
        "strategy_trade_count": int(len(alignment)),
        "raw_signal_audit_count": int(len(alignment_audit)),
        "elapsed_seconds": float(alignment_result.get("elapsed_seconds", 0.0)),
    }
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_alignment_signal_audit.csv", alignment_audit)
    costed_alignment = add_costed_returns(alignment)
    write_frame(OUT / f"{window_id.lower().replace('-', '_')}_alignment_trades.csv", costed_alignment)
    metrics.append(metric_summary(costed_alignment, window_id, "ALIGNMENT", ALIGNMENT_ID))
    require(not execution["ALIGNMENT"]["worker_errors"], f"{window_id}_ALIGNMENT_WORKER_ERRORS")
    require(not control.empty, f"{window_id}_CONTROL_EMPTY")
    require(control["pair_id"].astype(str).is_unique, f"{window_id}_CONTROL_PAIR_ID_NOT_UNIQUE")
    del control, costed_control, ma60_result, ma60_audit, alignment, alignment_result, alignment_audit, costed_alignment
    gc.collect()

    result = {
        **context,
        "reused_saved_trade_ledgers": False,
        "worker_count": WORKERS,
        "execution": execution,
        "worker_errors": [],
    }
    write_json(OUT / f"{window_id.lower().replace('-', '_')}_execution_audit.json", result)
    del run, scoped_gate
    gc.collect()
    return result


def summarize(metrics: pd.DataFrame, provenance: Mapping[str, Any], window_audits: list[dict[str, Any]]) -> dict[str, Any]:
    rows = metrics.to_dict("records")
    by_window: dict[str, dict[str, Any]] = {}
    for window in WINDOWS:
        by_window[window] = {
            row["strategy"]: row
            for row in rows
            if row["window_id"] == window
        }
    require(all(set(by_window[window]) == {"CONTROL", "MA60", "ALIGNMENT"} for window in WINDOWS), "WINDOW_STRATEGY_METRICS_INCOMPLETE")
    comparisons = {}
    for window, values in by_window.items():
        control = values["CONTROL"]
        comparisons[window] = {}
        for name in ("MA60", "ALIGNMENT"):
            candidate = values[name]
            comparisons[window][name] = {
                "average_terminal_delta_pp": candidate["average_terminal_return_pct"] - control["average_terminal_return_pct"],
                "median_terminal_delta_pp": candidate["median_terminal_return_pct"] - control["median_terminal_return_pct"],
                "average_realized_delta_pp": candidate["average_realized_return_pct"] - control["average_realized_return_pct"],
                "realized_win_rate_delta_pp": candidate["realized_win_rate_pct"] - control["realized_win_rate_pct"],
                "trade_count_delta": candidate["trade_count"] - control["trade_count"],
                "average_holding_days_delta": candidate["average_holding_days"] - control["average_holding_days"],
                "terminal_ge_50_count_delta": candidate["terminal_ge_50_count"] - control["terminal_ge_50_count"],
                "terminal_ge_100_count_delta": candidate["terminal_ge_100_count"] - control["terminal_ge_100_count"],
                "terminal_le_neg_15_count_delta": candidate["terminal_le_neg_15_count"] - control["terminal_le_neg_15_count"],
                "terminal_le_neg_30_count_delta": candidate["terminal_le_neg_30_count"] - control["terminal_le_neg_30_count"],
                "mdd_comparison": "NOT_AVAILABLE",
            }
    aggregate = {}
    fields = [
        "trade_count", "realized_count", "open_at_cutoff_count", "realized_win_rate_pct",
        "terminal_positive_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct",
        "average_realized_return_pct", "median_realized_return_pct", "average_holding_days",
        "median_holding_days", "progressed_rate_pct", "loss_guard_rate_pct",
        "terminal_ge_50_count", "terminal_ge_100_count", "terminal_le_neg_15_count",
        "terminal_le_neg_30_count",
    ]
    for name in ("CONTROL", "MA60", "ALIGNMENT"):
        aggregate[name] = {}
        for field in fields:
            values = [by_window[w][name].get(field) for w in WINDOWS]
            numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
            if field.endswith("_count"):
                aggregate[name][f"{field}_five_window_sum"] = int(sum(numeric))
            aggregate[name][f"{field}_window_mean"] = float(np.mean(numeric)) if numeric else None
            aggregate[name][f"{field}_window_min"] = min(numeric) if numeric else None
            aggregate[name][f"{field}_window_max"] = max(numeric) if numeric else None
    summaries = {}
    for candidate in ("MA60", "ALIGNMENT"):
        avg_better = [comparisons[w][candidate]["average_terminal_delta_pp"] > 0 for w in WINDOWS]
        median_better = [comparisons[w][candidate]["median_terminal_delta_pp"] > 0 for w in WINDOWS]
        win_better = [comparisons[w][candidate]["realized_win_rate_delta_pp"] > 0 for w in WINDOWS]
        large_winner_tradeoffs = [
            {
                "window_id": w,
                "ge_50_delta": comparisons[w][candidate]["terminal_ge_50_count_delta"],
                "ge_100_delta": comparisons[w][candidate]["terminal_ge_100_count_delta"],
                "le_neg_15_delta": comparisons[w][candidate]["terminal_le_neg_15_count_delta"],
                "le_neg_30_delta": comparisons[w][candidate]["terminal_le_neg_30_count_delta"],
            }
            for w in WINDOWS
        ]
        summaries[candidate] = {
            "average_terminal_better_windows": int(sum(avg_better)),
            "median_terminal_better_windows": int(sum(median_better)),
            "realized_win_rate_better_windows": int(sum(win_better)),
            "positive_average_terminal_windows": [w for w, improved in zip(WINDOWS, avg_better) if improved],
            "negative_average_terminal_windows": [w for w, improved in zip(WINDOWS, avg_better) if not improved],
            "large_winner_loss_tradeoff_by_window": large_winner_tradeoffs,
            "mdd": "NOT_AVAILABLE",
        }
    needs_check = any(
        row.get("mdd_status") == "NOT_AVAILABLE_IN_EXISTING_SIMPLE_TRADE_LEVEL_REPLAY"
        for row in rows
    )
    return {
        "work_id": WORK_ID,
        "status": "CHECK_REQUIRED" if needs_check else "COMPLETE",
        "final_token": CHECK_TOKEN if needs_check else FINAL_TOKEN,
        "simple_backtest_only": True,
        "portfolio_capital_constraints_applied": False,
        "official_strategy_adoption_decision": "NOT_MADE",
        "window_ids": list(WINDOWS),
        "workers": WORKERS,
        "strategy_ids": {"CONTROL": CONTROL_ID, "MA60": MA60_ID, "ALIGNMENT": ALIGNMENT_ID},
        "cost_contract": provenance["cost_contract"],
        "mdd_contract": provenance["mdd_contract"],
        "window_metrics": by_window,
        "five_window_aggregate": aggregate,
        "deltas_vs_control": comparisons,
        "interpretation_counts": summaries,
        "user_preference_targets": {
            "realized_win_rate_at_least_50_pct": "diagnostic only",
            "median_terminal_at_least_1_pct": "diagnostic only",
            "average_terminal_above_control": "diagnostic only",
            "average_terminal_at_least_10_pct": "diagnostic only",
            "mdd_above_neg_30_pct": "NOT_EVALUABLE; simple equity definition is absent",
        },
        "integrity": {
            "all_15_window_strategy_rows_present": True,
            "one_cost_contract_for_all_strategies": True,
            "same_survivor_projection_and_pit_for_all_strategies": True,
            "same_cutoff_and_execution_support_per_window": True,
            "no_portfolio_capital_constraints": True,
            "no_strategy_adoption_or_promotion": True,
            "mdd_not_substituted_with_portfolio_mdd": True,
            "worker_errors": 0,
        },
        "provenance": dict(provenance),
        "window_execution_audits": window_audits,
    }


def comparison_frame(summary: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for window, strategies in summary["deltas_vs_control"].items():
        for candidate, values in strategies.items():
            rows.append({"window_id": window, "candidate": candidate, **values})
    return pd.DataFrame(rows)


def threshold_frame(metrics: pd.DataFrame) -> pd.DataFrame:
    thresholds = [
        ("terminal_ge_20", "terminal_ge_20_count", "terminal_ge_20_rate_pct"),
        ("terminal_ge_50", "terminal_ge_50_count", "terminal_ge_50_rate_pct"),
        ("terminal_ge_100", "terminal_ge_100_count", "terminal_ge_100_rate_pct"),
        ("terminal_le_neg_10", "terminal_le_neg_10_count", "terminal_le_neg_10_rate_pct"),
        ("terminal_le_neg_15", "terminal_le_neg_15_count", "terminal_le_neg_15_rate_pct"),
        ("terminal_le_neg_20", "terminal_le_neg_20_count", "terminal_le_neg_20_rate_pct"),
        ("terminal_le_neg_30", "terminal_le_neg_30_count", "terminal_le_neg_30_rate_pct"),
    ]
    rows = []
    for row in metrics.to_dict("records"):
        for threshold, count_field, rate_field in thresholds:
            rows.append({
                "window_id": row["window_id"],
                "strategy": row["strategy"],
                "threshold": threshold,
                "count": row.get(count_field),
                "rate_pct_of_all_trades": row.get(rate_field),
                "return_basis": "net terminal return; realized exits plus cutoff marks after entry costs",
            })
    return pd.DataFrame(rows)


def preference_frame(metrics: pd.DataFrame) -> pd.DataFrame:
    control_means = (
        metrics.loc[metrics["strategy"].eq("CONTROL")]
        .set_index("window_id")["average_terminal_return_pct"]
        .to_dict()
    )
    rows = []
    for item in metrics.to_dict("records"):
        avg, median, win = (
            item["average_terminal_return_pct"],
            item["median_terminal_return_pct"],
            item["realized_win_rate_pct"],
        )
        rows.append({
            "window_id": item["window_id"],
            "strategy": item["strategy"],
            "realized_win_rate_ge_50": None if win is None else bool(win >= 50),
            "median_terminal_ge_1": None if median is None else bool(median >= 1),
            "average_terminal_gt_control": None if avg is None else bool(avg > control_means[item["window_id"]]),
            "average_terminal_ge_10": None if avg is None else bool(avg >= 10),
            "mdd_gt_neg_30": "NOT_EVALUABLE",
            "use": "diagnostic only; not an automatic rejection gate",
        })
    return pd.DataFrame(rows)


def render_report(summary: Mapping[str, Any], provenance: Mapping[str, Any]) -> str:
    def show(value: Any, digits: int = 2) -> str:
        return "—" if value is None else f"{float(value):.{digits}f}"

    lines = [
        "# A FAST Core V2 MA60 vs Bullish Alignment 5-window 단순 백테스트",
        "",
        "## 작업 범위",
        "",
        "- CONTROL, MA60 fail-closed, Bullish Alignment을 P1, P2-1, P2-2, P3-1, P3-2에서 거래 단위로 비교했어.",
        "- 포트폴리오 자본·포지션·현금 제약은 적용하지 않았고, 공식 전략 채택 여부도 판단하지 않았어.",
        "- 같은 frozen survivor roster, merged COMMON PIT, KRX 시총 gate, Repository V2 가격, lifecycle을 사용했어.",
        "",
        "## 비용과 MDD",
        "",
        f"- 매수·매도 수수료 각 {COMM_RATE * 100:.4f}%, 매수·매도 슬리피지 각 {SLIP_RATE * 100:.3f}%를 반영하고 거래세는 뺐어.",
        "- 실현 거래는 매수·매도 양쪽 비용을 반영했고, cutoff 미청산 거래는 cutoff 종가와 진입 비용으로 평가했어.",
        "- 단순 거래 재생에는 정해진 equity series/MDD 정의가 없어. 포트폴리오 MDD로 대체하지 않았고 MDD는 N/A, 결과는 CHECK_REQUIRED야.",
        "",
        "## Window별 비교",
        "",
        "| Window | Strategy | Trades | Realized | Open | Realized win % | Avg terminal % | Median terminal % | Avg realized % | Median realized % | Avg hold days | PROGRESSED % | Loss Guard % | +50 | +100 | <=-15 | <=-30 | MDD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for window in WINDOWS:
        for name in ("CONTROL", "MA60", "ALIGNMENT"):
            row = summary["window_metrics"][window][name]
            lines.append(
                f"| {window} | {name} | {row['trade_count']} | {row['realized_count']} | {row['open_at_cutoff_count']} | "
                f"{show(row['realized_win_rate_pct'])} | {show(row['average_terminal_return_pct'])} | "
                f"{show(row['median_terminal_return_pct'])} | {show(row['average_realized_return_pct'])} | "
                f"{show(row['median_realized_return_pct'])} | {show(row['average_holding_days'])} | "
                f"{show(row['progressed_rate_pct'])} | {show(row['loss_guard_rate_pct'])} | "
                f"{row['terminal_ge_50_count']} | {row['terminal_ge_100_count']} | "
                f"{row['terminal_le_neg_15_count']} | {row['terminal_le_neg_30_count']} | N/A |"
            )
    lines += [
        "",
        "## 5-window 종합",
        "",
        "비율·수익률·보유일은 window별 산술 평균과 범위를 함께 봐. 거래 수와 threshold 건수 합계는 중첩 window의 거래를 중복 포함해.",
        "",
        "| Strategy | Mean trades | Trade range | Mean win % | Mean avg terminal % | Mean median terminal % | Mean avg realized % | Mean median realized % | Mean avg hold | Mean median hold | Mean PROGRESSED % | Mean Loss Guard % | +50 sum | +100 sum | <=-15 sum | <=-30 sum | MDD |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("CONTROL", "MA60", "ALIGNMENT"):
        agg = summary["five_window_aggregate"][name]
        trades = [summary["window_metrics"][w][name]["trade_count"] for w in WINDOWS]
        lines.append(
            f"| {name} | {show(agg['trade_count_window_mean'],0)} | {min(trades)}–{max(trades)} | "
            f"{show(agg['realized_win_rate_pct_window_mean'])} | {show(agg['average_terminal_return_pct_window_mean'])} | "
            f"{show(agg['median_terminal_return_pct_window_mean'])} | {show(agg['average_realized_return_pct_window_mean'])} | "
            f"{show(agg['median_realized_return_pct_window_mean'])} | {show(agg['average_holding_days_window_mean'])} | "
            f"{show(agg['median_holding_days_window_mean'])} | {show(agg['progressed_rate_pct_window_mean'])} | "
            f"{show(agg['loss_guard_rate_pct_window_mean'])} | {agg['terminal_ge_50_count_five_window_sum']} | "
            f"{agg['terminal_ge_100_count_five_window_sum']} | {agg['terminal_le_neg_15_count_five_window_sum']} | "
            f"{agg['terminal_le_neg_30_count_five_window_sum']} | N/A |"
        )
    lines += [
        "",
        "## CONTROL 대비 변화",
        "",
        "| Window | Candidate | Avg terminal Δ pp | Median terminal Δ pp | Realized win Δ pp | Trade count Δ | Avg hold Δ days | +50 Δ | +100 Δ | <=-15 Δ | <=-30 Δ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window in WINDOWS:
        for candidate in ("MA60", "ALIGNMENT"):
            d = summary["deltas_vs_control"][window][candidate]
            lines.append(
                f"| {window} | {candidate} | {d['average_terminal_delta_pp']:.2f} | {d['median_terminal_delta_pp']:.2f} | "
                f"{d['realized_win_rate_delta_pp']:.2f} | {d['trade_count_delta']} | {d['average_holding_days_delta']:.2f} | "
                f"{d['terminal_ge_50_count_delta']} | {d['terminal_ge_100_count_delta']} | "
                f"{d['terminal_le_neg_15_count_delta']} | {d['terminal_le_neg_30_count_delta']} |"
            )
    ma60 = summary["interpretation_counts"]["MA60"]
    alignment = summary["interpretation_counts"]["ALIGNMENT"]
    lines += [
        "",
        "## 해석 질문",
        "",
        f"1. MA60의 P3-2 평균 terminal 우위는 전체 다섯 기간 중 {ma60['average_terminal_better_windows']}개 기간에서 관측됐어.",
        f"2. ALIGNMENT은 realized 승률 {alignment['realized_win_rate_better_windows']}/5, 평균 terminal {alignment['average_terminal_better_windows']}/5, 중앙 terminal {alignment['median_terminal_better_windows']}/5개 기간에서 CONTROL보다 높았어. MDD는 equity 정의가 없어 비교할 수 없어.",
        f"3. 평균 terminal 개선 window는 MA60 {', '.join(ma60['positive_average_terminal_windows']) or '없음'}, ALIGNMENT {', '.join(alignment['positive_average_terminal_windows']) or '없음'}이야.",
        "4. +50/+100 승자와 -15/-30 손실 변화는 control_deltas.csv의 window별 델타에서 비교할 수 있어.",
        "5. 거래 수·보유일 변화는 결과 표에 있어. 동시 관측만으로 거래 수가 성과 변화를 일으켰다고 단정하지 않아.",
        "6. 평균 terminal 개선 기간 수로 반복성을 요약했어. 일부 window에만 개선되면 장세 의존 가능성이 있어.",
        "",
        "## 사용자 선호 목표 진단",
        "",
        "실현 승률 50%, 중앙 terminal +1%, 평균 terminal +10%, CONTROL 평균 초과는 preference_diagnostics.csv에서 확인할 수 있어. 진단용이며 자동 탈락 기준이 아니야. MDD -30%는 평가 불가야.",
        "",
        "## Cutoff / open position 처리",
        "",
        "cutoff 뒤 신규 진입은 막고 cutoff 이전 신호의 support date 실행만 허용했어. support date의 진입·청산 수, cutoff 미청산 수, exit reason/status 분포는 window metrics에 있어. open terminal은 cutoff 종가 기준이야.",
        "",
        "## Authority / 재사용",
        "",
        f"- Frozen merged PIT SHA-256: {provenance['pit_sha256']}; calendar SHA-256: {provenance['calendar_sha256']}.",
        f"- 동일 survivor projection: {provenance['survivor_identity_count']} identities, as-of {provenance['survivor_as_of']}.",
        "- P3-2 저장 거래 원장은 exact CONTROL parity, candidate filter audit, worker 10 증거와 대조했어. 이후 Git 변경은 portfolio valuation/MDD 계산이며 simple trade generation, PIT, identity, price path는 바뀌지 않아 재사용했어. 비용 기반 수익률은 다시 계산했어.",
        "- P1, P2-1, P2-2, P3-1은 worker 10으로 새 replay를 했어. 로컬 가격/MKTCAP store만 읽었고 네트워크는 0회야.",
        "",
        "## 산출물",
        "",
        "- summary.json, metrics_by_window.csv, control_deltas.csv, threshold_summary.csv, preference_diagnostics.csv",
        "- window별 trade CSV, candidate signal audit, MKTCAP audit, execution audit",
        "- provenance.json, preflight.json, sample_benchmark.json, price_store_audit.csv, identity_authority_audit.csv",
        "",
        f"결과 토큰: {summary['final_token']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    global CURRENT_STAGE, CANDIDATE_REPLAY_STARTED
    started = time.perf_counter()
    network_state = network_guard()
    try:
        CURRENT_STAGE = "PREFLIGHT"
        pre = preflight()
        OUT.mkdir(parents=True, exist_ok=True)
        write_json(OUT / "preflight.json", pre)
        CURRENT_STAGE = "LOAD_FROZEN_AUTHORITY"
        frozen, base_run, base_gate, universe, authority, survivors = load_frozen_context()
        pit_path = base_run.authority.pit_path
        calendar_path = PIT_EXTENSION_DIR / "merged_trading_calendar.json"
        manifest_path = PIT_EXTENSION_DIR / "p2_2_identity_authority_extension_manifest.json"
        manifest = read_json(manifest_path)
        require(sha256(pit_path) == pre["p3_frozen_pit_sha256"], "FROZEN_PIT_SHA256_MISMATCH")
        require(manifest.get("status") == "PASS", "FROZEN_PIT_MANIFEST_NOT_PASS")
        require(sha256(calendar_path) == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_SHA256_MISMATCH")
        survivor_audit = P3_DIR / "survivor_universe_audit.csv"
        require(survivor_audit.is_file(), "SAVED_SURVIVOR_AUDIT_MISSING")
        require(sha256(survivor_audit) == pre["p3_saved_survivor_audit_sha256"], "SURVIVOR_AUDIT_HASH_MISMATCH")
        pd.read_csv(survivor_audit).to_csv(OUT / "identity_authority_audit.csv", index=False, encoding="utf-8")
        pre.update({
            "frozen_pit_sha256": sha256(pit_path),
            "frozen_calendar_sha256": sha256(calendar_path),
            "survivor_identity_count": len(survivors),
            "survivor_as_of": manifest.get("calendar_frontier"),
        })
        write_json(OUT / "preflight.json", pre)

        CURRENT_STAGE = "SAMPLE_BENCHMARK"
        prices = HELPER.PriceCache()
        CANDIDATE_REPLAY_STARTED = True
        sample = run_sample(base_run, base_gate, survivors, prices)
        write_json(OUT / "sample_benchmark.json", sample)
        require(sample.get("status") == "PASS", "SAMPLE_BENCHMARK_NOT_PASS")

        metrics: list[dict[str, Any]] = []
        window_audits: list[dict[str, Any]] = []
        CURRENT_STAGE = "P3_2_SAVED_RESULT_REUSE"
        control = pd.read_csv(CONTROL_DIR / "control_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
        ma60 = pd.read_csv(MA60_DIR / "ma60_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
        alignment = pd.read_csv(ALIGNMENT_DIR / "alignment_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
        window_audits.append(save_p3_reused("P3-2", control, ma60, alignment, metrics))
        del control, ma60, alignment
        p3_price_audit = pd.read_csv(MA60_DIR / "price_store_audit.csv")
        p3_price_audit.to_csv(OUT / "p3_2_price_store_audit.csv", index=False, encoding="utf-8")

        for window_id in ("P1", "P2-1", "P2-2", "P3-1"):
            CURRENT_STAGE = f"{window_id}_FULL_REPLAY"
            CANDIDATE_REPLAY_STARTED = True
            audit = run_full_window(window_id, base_run, base_gate, survivors, prices, metrics)
            window_audits.append(audit)
            current = pd.DataFrame([row for row in metrics if row["window_id"] == window_id])
            write_frame(OUT / f"{window_id.lower().replace('-', '_')}_strategy_metrics.csv", current)
            write_frame(OUT / "price_store_audit.csv", pd.DataFrame(prices.audit.values()))

        CURRENT_STAGE = "METRICS_AND_REPORT"
        metrics_frame = pd.DataFrame(metrics)
        require(len(metrics_frame) == 15, "EXPECTED_15_WINDOW_STRATEGY_METRICS")
        require(metrics_frame["trade_count"].eq(metrics_frame["realized_count"] + metrics_frame["open_at_cutoff_count"]).all(), "TRADE_STATUS_COUNT_MISMATCH")
        require(metrics_frame["terminal_return_available_count"].eq(metrics_frame["trade_count"]).all(), "MISSING_TERMINAL_RETURN")
        write_frame(OUT / "metrics_by_window.csv", metrics_frame)
        provenance = {
            "work_id": WORK_ID,
            "start_head": pre["start_head"],
            "strategy_source_sha256": pre["strategy_source_sha256"],
            "base_trade_runner_sha256": pre["base_trade_runner_sha256"],
            "pit_sha256": sha256(pit_path),
            "calendar_sha256": sha256(calendar_path),
            "survivor_identity_count": len(survivors),
            "survivor_as_of": pre["survivor_as_of"],
            "identity_scope": "exact saved P3-2 survivor roster across all five windows",
            "p3_saved_control_sha256": sha256(CONTROL_DIR / "control_strategy_trades.csv"),
            "p3_saved_ma60_sha256": sha256(MA60_DIR / "ma60_strategy_trades.csv"),
            "p3_saved_alignment_sha256": sha256(ALIGNMENT_DIR / "alignment_strategy_trades.csv"),
            "post_p3_portfolio_only_changes": pre["post_p3_changes"],
            "price_source": "local Repository V2 adjusted-price partitions; candidate monthly MA from verified adjusted OHLC store",
            "market_cap_source": "local exact-date KRX raw Stock Daily MKTCAP partitions",
            "lifecycle_source": "saved P3 frozen run context and existing lifecycle settlement evidence",
            "worker_count": WORKERS,
            "network_calls": network_state[2]["calls"],
            "cost_contract": pre["cost_contract"],
            "mdd_contract": pre["mdd_contract"],
            "sample_benchmark": sample,
            "window_execution_audits": window_audits,
            "duration_seconds": time.perf_counter() - started,
        }
        require(network_state[2]["calls"] == 0, "NETWORK_CALLS_DETECTED")
        write_json(OUT / "provenance.json", provenance)
        summary = summarize(metrics_frame, provenance, window_audits)
        write_frame(OUT / "control_deltas.csv", comparison_frame(summary))
        write_frame(OUT / "threshold_summary.csv", threshold_frame(metrics_frame))
        write_frame(OUT / "preference_diagnostics.csv", preference_frame(metrics_frame))
        write_json(OUT / "summary.json", summary)
        (OUT / "report.md").write_text(render_report(summary, provenance), encoding="utf-8")
        write_json(OUT / "run_manifest.json", {
            "status": summary["status"],
            "final_token": summary["final_token"],
            "files": sorted(path.name for path in OUT.iterdir() if path.is_file()),
            "elapsed_seconds": time.perf_counter() - started,
            "worker_count": WORKERS,
        })
        return 0
    except Exception:
        raise
    finally:
        restore_network_guard(network_state)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            write_json(
                OUT / "failure.json",
                {
                    "status": "FAIL",
                    "stage": CURRENT_STAGE,
                    "candidate_replay_started": CANDIDATE_REPLAY_STARTED,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "automatic_retry": False,
                },
            )
        except Exception:
            pass
        raise
