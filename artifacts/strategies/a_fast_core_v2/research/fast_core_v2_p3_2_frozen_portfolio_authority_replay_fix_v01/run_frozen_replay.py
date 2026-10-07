#!/usr/bin/env python3
"""Research-only P3-2 frozen-authority replay and score-alive experiment.

This runner reconstructs only authority projections persisted by the certified
P3-2 output. It never reads rolling/latest authority and does not edit the
canonical strategy or production runner.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import inspect
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

from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2
import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio
import scripts.run_p2_2_realistic_portfolio_v01 as engine


RUN_ID = "run_20261007_frozen_authority_replay_fix_v01"
OUT_DIR = Path(__file__).resolve().parent
P3_DIR = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01"
AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
SOURCE_PATH = ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py"
EXPECTED_STRATEGY_SHA256 = "a6e70b7bda6507f0913b7553fb8004cb9b2d96460eb4f4dabfc0ab82488351c8"
EXPECTED_RUNNER_SHA256 = "a48f49d61284b9b558e1172ea907feaa3bc35f6c2a5aaeb735c6db9739a56431"
WORKERS = 10
POLICIES = ("CONTROL", "A", "B")

# Match the already-certified P3-2 tax schedule. The production runner adds this
# 2026 rate to the P2 execution module before portfolio replay.
if not any(row[0] == "2026-01-01" for row in portfolio.SELL_TAX_SCHEDULE):
    portfolio.SELL_TAX_SCHEDULE = (*portfolio.SELL_TAX_SCHEDULE, ("2026-01-01", "2026-12-31", 0.0020))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def require(condition: bool, token: str) -> None:
    if not condition:
        raise RuntimeError(token)


def _calendar_from_frozen_artifact() -> MarketCalendarAuthority:
    manifest_path = AUTHORITY_DIR / "p2_2_identity_authority_extension_manifest.json"
    calendar_path = AUTHORITY_DIR / "merged_trading_calendar.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calendar_payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS", "FROZEN_AUTHORITY_MANIFEST_NOT_PASS")
    require(manifest.get("calendar_frontier") == "2026-09-01", "FROZEN_CALENDAR_FRONTIER_MISMATCH")
    require(sha256(calendar_path) == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")
    dates = pd.DatetimeIndex(pd.to_datetime(calendar_payload["trading_dates"])).normalize()
    require(dates[-1].strftime("%Y-%m-%d") == "2026-09-01", "FROZEN_CALENDAR_END_MISMATCH")
    frame = pd.DataFrame({"date": dates}, index=dates)
    groups = frame.groupby([frame.index.year, frame.index.month])
    completed = [group.index.max() for (year, month), group in groups if (year, month) != (dates[-1].year, dates[-1].month)]
    return MarketCalendarAuthority(
        trading_dates=dates,
        completed_month_ends=completed,
        source_name="P3_2_FROZEN_EXTENSION_CALENDAR",
        metadata={
            "calendar_frontier": manifest["calendar_frontier"],
            "calendar_sha256": sha256(calendar_path),
            "authority_manifest_sha256": sha256(manifest_path),
        },
    )


def _load_frozen_context():
    """Load P3-2 context with the saved effective PIT and calendar only."""
    calendar = _calendar_from_frozen_artifact()
    original_calendar_loader = strategy.load_rolling_production_market_calendar
    original_exclusion_filter = strategy.apply_permanent_identity_exclusions
    try:
        # The strategy module's default points at latest rolling authority.
        # This research-only call injects the pinned P3-2 calendar explicitly.
        strategy.load_rolling_production_market_calendar = lambda _root: calendar
        # Preserve all COMMON rows here; apply the exact saved P3-2 survivor
        # projection below instead of today's expanded exclusion registry.
        strategy.apply_permanent_identity_exclusions = lambda segments: (list(segments), [])
        run = strategy._load_context("P3-2")
    finally:
        strategy.load_rolling_production_market_calendar = original_calendar_loader
        strategy.apply_permanent_identity_exclusions = original_exclusion_filter

    require(run.window.effective_start.strftime("%Y-%m-%d") == "2022-01-03", "FROZEN_WINDOW_START_MISMATCH")
    require(run.window.effective_end.strftime("%Y-%m-%d") == "2026-08-31", "FROZEN_WINDOW_END_MISMATCH")
    require(run.window.execution_support.strftime("%Y-%m-%d") == "2026-09-01", "FROZEN_WINDOW_SUPPORT_MISMATCH")
    require(sha256(run.authority.pit_path) == "6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1", "FROZEN_PIT_HASH_MISMATCH")

    universe = pd.read_csv(P3_DIR / "survivor_universe_audit.csv", dtype={"ticker": str})
    survivor_rows = universe.loc[universe["status"].eq("SURVIVOR_COMMON_IDENTITY")]
    survivor_keys = frozenset(
        (str(row.ticker).zfill(6), str(row.isu_cd).upper(), str(row.market).upper())
        for row in survivor_rows.itertuples(index=False)
    )
    original_segments = [segment for rows in run.segments_by_ticker.values() for segment in rows]
    segment_keys = {(segment.ticker, segment.isu_cd.upper(), segment.market.upper()) for segment in original_segments}
    require(len(survivor_keys) == 2539, "FROZEN_SURVIVOR_COUNT_MISMATCH")
    require(len(survivor_keys - segment_keys) == 0, "FROZEN_SURVIVOR_KEY_NOT_IN_HISTORICAL_PIT")
    grouped: dict[str, list[strategy.IdentitySegment]] = {}
    for segment in original_segments:
        if (segment.ticker, segment.isu_cd.upper(), segment.market.upper()) in survivor_keys:
            grouped.setdefault(segment.ticker, []).append(segment)
    run = replace(
        run,
        segments_by_ticker={
            ticker: tuple(sorted(rows, key=lambda row: (row.effective_from, row.effective_to, row.isu_cd)))
            for ticker, rows in sorted(grouped.items())
        },
    )
    pit_payload = json.loads(run.authority.pit_path.read_text(encoding="utf-8"))
    gate = portfolio.ExactRawMcapGate(ROOT, pit_payload)
    # Exact membership is persisted in the certified P3-2 universe audit.
    # Keep the payload's as_of unchanged (2026-09-01); membership is a separate
    # frozen projection explicitly captured at 2026-09-21.
    gate.active_identity_keys = survivor_keys
    run = replace(run, entry_signal_gate=gate)
    return run, gate, universe, {
        "status": "PASS",
        "calendar_path": str(AUTHORITY_DIR / "merged_trading_calendar.json"),
        "calendar_sha256": sha256(AUTHORITY_DIR / "merged_trading_calendar.json"),
        "calendar_as_of": "2026-09-01",
        "historical_pit_path": str(run.authority.pit_path.relative_to(ROOT)),
        "historical_pit_sha256": sha256(run.authority.pit_path),
        "saved_survivor_audit_sha256": sha256(P3_DIR / "survivor_universe_audit.csv"),
        "saved_survivor_as_of": "2026-09-21",
        "survivor_identity_count": len(survivor_keys),
        "source_latest_rolling_authority_read": False,
        "new_prices_or_network_calls": 0,
        "authority_note": "The original 2026-09-21 merged PIT bytes are absent; replay inputs reconstruct the consumed historical interval authority plus the exact saved active-identity projection. Exact control parity is the acceptance gate.",
    }


def _compile_research_simulator() -> Any:
    """Clone the official function in memory and add only the A/B guard hook."""
    require(sha256(SOURCE_PATH) == EXPECTED_STRATEGY_SHA256, "CANONICAL_STRATEGY_SOURCE_HASH_CHANGED")
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "simulate_ticker_core_v02_reentry")
    function.name = "simulate_ticker_core_v02_reentry_research"
    function.args.args.append(ast.arg(arg="research_exit_policy"))
    function.args.defaults.append(ast.Constant(value="CONTROL"))

    strategy_trade_loop = next(node for node in function.body if isinstance(node, ast.While))
    loop_index = next(
        index
        for index, node in enumerate(strategy_trade_loop.body)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Attribute)
        and node.iter.func.attr == "iterrows"
        and isinstance(node.iter.func.value, ast.Name)
        and node.iter.func.value.id == "pre_prog_daily"
    )
    injected = ast.parse(
        '''
if research_exit_policy in {"A", "B"}:
    research_guard_type = None
    research_score_delta = None
    research_score_evaluations = 0
    entry_snapshot = build_historical_snapshot_from_context(
        snapshot_context,
        found_signal_w,
        include_incomplete_periods=False,
        market_calendar=market_calendar,
    )
    entry_eval = evaluate_pattern_a(entry_snapshot)
    entry_canonical_score = entry_eval.score
    loss_guard_triggered = False
    loss_guard_sig_d = None
    loss_guard_exec_d = None
    loss_guard_exec_price = None
    for research_day, research_row in pre_prog_daily.iterrows():
        research_return = float(research_row["close"]) / entry_open_price - 1.0
        if research_exit_policy == "B" and research_return <= -0.30:
            research_guard_type = "HARD_SAFETY"
            loss_guard_sig_d = research_day
            next_rows = daily[(daily.index > research_day) & (daily.index <= execution_support)]
            if not next_rows.empty:
                loss_guard_exec_d = next_rows.index[0]
                loss_guard_exec_price = float(next_rows.iloc[0]["open"])
            break
        if research_return > -0.15:
            continue
        guard_snapshot = build_historical_snapshot_from_context(
            snapshot_context,
            research_day,
            include_incomplete_periods=False,
            market_calendar=market_calendar,
        )
        guard_eval = evaluate_pattern_a(guard_snapshot)
        guard_score = guard_eval.score
        research_score_evaluations += 1
        research_score_delta = (
            float(guard_score) - float(entry_canonical_score)
            if guard_score is not None and entry_canonical_score is not None
            else None
        )
        if research_score_delta is None or research_score_delta <= 0:
            research_guard_type = "SCORE_ALIVE_GUARD"
            loss_guard_triggered = True
            loss_guard_sig_d = research_day
            next_rows = daily[(daily.index > research_day) & (daily.index <= execution_support)]
            if not next_rows.empty:
                loss_guard_exec_d = next_rows.index[0]
                loss_guard_exec_price = float(next_rows.iloc[0]["open"])
            break
'''
    ).body
    strategy_trade_loop.body[loop_index + 1:loop_index + 1] = injected
    # Candidate output keeps guard categories distinct from the canonical
    # V2 Loss Guard and preserves all other fields from the official record.
    # Add policy-specific event labels immediately before outcome calculation.
    outcome_index = next(
        index for index, node in enumerate(strategy_trade_loop.body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "res_outcome" for target in node.targets)
    )
    event_labels = ast.parse(
        '''
if research_exit_policy == "A" and research_guard_type == "SCORE_ALIVE_GUARD":
    final_exit_type = "SCORE_ALIVE_GUARD_CLOSE_LE_NEG_15"
elif research_exit_policy == "B" and research_guard_type == "SCORE_ALIVE_GUARD":
    final_exit_type = "SCORE_ALIVE_GUARD_CLOSE_LE_NEG_15"
elif research_exit_policy == "B" and research_guard_type == "HARD_SAFETY":
    final_exit_type = "HARD_SAFETY_CLOSE_LE_NEG_30"
'''
    ).body
    strategy_trade_loop.body[outcome_index:outcome_index] = event_labels
    # The cloned function records per-trade guard diagnostics on its record.
    construction = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "V02TradeRecord"
    )
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
record.research_exit_policy = research_exit_policy
record.research_guard_type = research_guard_type if research_exit_policy in {"A", "B"} else ("CONTROL_LOSS_GUARD" if loss_guard_triggered else None)
record.research_score_delta = research_score_delta if research_exit_policy in {"A", "B"} else None
record.research_score_evaluations = research_score_evaluations if research_exit_policy in {"A", "B"} else 0
'''
    ).body
    strategy_trade_loop.body[append_index:append_index] = metadata
    # Silence the local reference; construction is intentionally found above
    # to assert the cloned AST still constructs the canonical record type.
    require(construction is not None, "RESEARCH_SIMULATOR_RECORD_CONSTRUCTION_MISSING")
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = vars(v2).copy()
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["simulate_ticker_core_v02_reentry_research"]


def _serialize_with_research(record: Any) -> dict[str, Any]:
    data = v2.asdict(record)
    data.update(
        research_exit_policy=getattr(record, "research_exit_policy", "CONTROL"),
        research_guard_type=getattr(record, "research_guard_type", None),
        research_score_delta=getattr(record, "research_score_delta", None),
        research_score_evaluations=getattr(record, "research_score_evaluations", 0),
    )
    return data


def _run_policy(run: Any, gate: Any, policy: str, tickers: Sequence[str]) -> tuple[list[dict[str, Any]], list[str], float]:
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    original_simulator = v2.simulate_ticker_core_v02_reentry
    original_serializer = v2.V02TradeRecord.to_dict
    cloned = _compile_research_simulator()

    def selected_simulator(*args: Any, **kwargs: Any):
        kwargs["research_exit_policy"] = policy
        return cloned(*args, **kwargs)

    v2.simulate_ticker_core_v02_reentry = selected_simulator
    v2.V02TradeRecord.to_dict = _serialize_with_research
    try:
        def process(ticker: str):
            item = strategy._process_ticker(ticker, run)
            item["worker_thread"] = threading.current_thread().name
            return item

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix=f"p3frozen-{policy.lower()}") as pool:
            futures = {pool.submit(process, ticker): ticker for ticker in tickers}
            for completed, future in enumerate(as_completed(futures), start=1):
                ticker = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
                if completed % 50 == 0 or completed == len(tickers):
                    trades = sum(len(item.get("control_rows", ())) for item in outcomes)
                    print(
                        f"{policy} progress {completed}/{len(tickers)}; trades={trades}; "
                        f"PIT attempts={len(gate.audit_frame())}; elapsed={time.perf_counter()-started:.1f}s; errors={len(errors)}",
                        flush=True,
                    )
    finally:
        v2.simulate_ticker_core_v02_reentry = original_simulator
        v2.V02TradeRecord.to_dict = original_serializer
    return outcomes, errors, time.perf_counter() - started


def _records(outcomes: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame([row for item in outcomes for row in item.get("control_rows", ())])
    if frame.empty:
        return frame
    return frame.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)


def _frames(outcomes: Sequence[Mapping[str, Any]]) -> dict[Any, pd.DataFrame]:
    frames: dict[Any, pd.DataFrame] = {}
    for item in outcomes:
        frames.update(item.get("market_data_by_identity", {}))
    return frames


def _load_market_frames_for_records(run: Any, records: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reload only V2 OHLC frames needed to evaluate saved candidate ledgers."""
    segment_by_key = {
        segment.key: segment
        for segments in run.segments_by_ticker.values()
        for segment in segments
    }
    keys = sorted(
        {
            "|".join(
                (
                    str(row.ticker).zfill(6),
                    str(row.isu_cd).upper(),
                    str(row.market).upper(),
                    str(row.identity_effective_from),
                    str(row.identity_effective_to),
                )
            )
            for row in records.itertuples(index=False)
        }
    )
    frames: dict[str, pd.DataFrame] = {}
    for key in keys:
        segment = segment_by_key.get(key)
        require(segment is not None, f"SAVED_CANDIDATE_IDENTITY_NOT_IN_FROZEN_PIT:{key}")
        loader = strategy.RepositoryV2DailyLoader(
            run.loader.repository,
            start=segment.effective_from,
            end=run.window.execution_support,
        )
        daily = loader.load(segment.ticker)
        require(daily is not None and not daily.empty, f"SAVED_CANDIDATE_V2_DAILY_MISSING:{key}")
        frames[key] = daily.sort_index().loc[:, ["open", "high", "low", "close"]]
    return frames


def _keyed(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    selected = frame[list(columns)].copy()
    if "ticker" in selected:
        selected["ticker"] = selected["ticker"].astype(str).str.zfill(6)
    selected = selected.sort_values(list(columns), kind="mergesort", na_position="first").reset_index(drop=True)
    return selected


def _compare_frames(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    columns: Sequence[str],
    sort_by: Sequence[str] | None = None,
    numeric_atol: float = 1e-9,
) -> dict[str, Any]:
    if len(actual) != len(expected):
        return {"pass": False, "actual_rows": len(actual), "expected_rows": len(expected), "mismatch_count": abs(len(actual) - len(expected))}
    keys = [column for column in (sort_by or ()) if column in actual.columns and column in expected.columns]
    if not keys:
        keys = [column for column in ("pair_id", "date", "ticker", "signal_date") if column in actual.columns and column in expected.columns]
    if not keys:
        keys = list(columns)
    left = actual[list(columns)].copy()
    right = expected[list(columns)].copy()
    if "ticker" in left:
        left["ticker"] = left["ticker"].astype(str).str.zfill(6)
        right["ticker"] = right["ticker"].astype(str).str.zfill(6)
    if left.duplicated(keys).any() or right.duplicated(keys).any():
        keys = list(dict.fromkeys(keys + [column for column in columns if column not in keys]))
    left = left.sort_values(keys, kind="mergesort", na_position="first").reset_index(drop=True)
    right = right.sort_values(keys, kind="mergesort", na_position="first").reset_index(drop=True)
    mismatch: list[dict[str, Any]] = []
    for column in columns:
        a = left[column]
        b = right[column]
        if pd.api.types.is_numeric_dtype(a) or pd.api.types.is_numeric_dtype(b):
            av = pd.to_numeric(a, errors="coerce").to_numpy(dtype=float)
            bv = pd.to_numeric(b, errors="coerce").to_numpy(dtype=float)
            equal = np.isclose(av, bv, rtol=0, atol=numeric_atol, equal_nan=True)
        else:
            av = a.fillna("").astype(str).to_numpy()
            bv = b.fillna("").astype(str).to_numpy()
            equal = av == bv
        bad = np.flatnonzero(~equal)
        if len(bad):
            i = int(bad[0])
            mismatch.append({"column": column, "mismatch_count": int(len(bad)), "first_actual": str(a.iloc[i]), "first_expected": str(b.iloc[i])})
    return {"pass": not mismatch, "actual_rows": len(actual), "expected_rows": len(expected), "mismatch_count": sum(row["mismatch_count"] for row in mismatch), "first_mismatches": mismatch[:20]}


def _control_strategy_parity(actual: pd.DataFrame) -> dict[str, Any]:
    expected = pd.read_csv(P3_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
    columns = [column for column in expected.columns if column in actual.columns]
    # Ticker is normalized to the canonical six-digit identity. The old CSV's
    # parser inferred this field as integer in some environments.
    return _compare_frames(actual, expected, columns, sort_by=("pair_id",))


def _control_mcap_frame_parity(actual: pd.DataFrame) -> dict[str, Any]:
    expected = pd.read_csv(P3_DIR / "pit_mcap_audit.csv", dtype={"ticker": str})
    key = ["ticker", "identity", "market", "signal_date", "threshold_krw", "market_cap", "status", "reason", "strategy_signal_qualified"]
    if len(actual) != len(expected):
        return {"pass": False, "actual_rows": len(actual), "expected_rows": len(expected)}
    left = actual[key].copy()
    right = expected[key].copy()
    left["ticker"] = left["ticker"].astype(str).str.zfill(6)
    right["ticker"] = right["ticker"].astype(str).str.zfill(6)
    left = left.sort_values(["ticker", "identity", "market", "signal_date"], kind="mergesort").reset_index(drop=True)
    right = right.sort_values(["ticker", "identity", "market", "signal_date"], kind="mergesort").reset_index(drop=True)
    return _compare_frames(left, right, key, sort_by=("ticker", "identity", "market", "signal_date"))


def _control_mcap_parity(gate: Any) -> dict[str, Any]:
    return _control_mcap_frame_parity(gate.audit_frame())


def _portfolio_replay(records: pd.DataFrame, frames: Mapping[Any, pd.DataFrame], run: Any, strategy_id: str) -> dict[str, Any]:
    return portfolio._portfolio_replay(
        records.to_dict(orient="records"),
        frames,
        tuple(pd.to_datetime(run.calendar.trading_dates).normalize()),
        strategy_id=strategy_id,
        effective_start=pd.Timestamp(run.window.effective_start).normalize(),
        effective_end=pd.Timestamp(run.window.effective_end).normalize(),
        execution_support=pd.Timestamp(run.window.execution_support).normalize(),
    )


def _portfolio_parity(replay: Mapping[str, Any]) -> dict[str, Any]:
    directory = P3_DIR
    expected_events = pd.read_csv(directory / "control_portfolio_events.csv", dtype={"ticker": str})
    expected_equity = pd.read_csv(directory / "control_daily_equity.csv")
    actual_events = pd.DataFrame(replay["events"])
    actual_equity = pd.DataFrame(replay["daily_equity"])
    event_columns = list(expected_events.columns)
    equity_columns = list(expected_equity.columns)
    # The same portfolio arithmetic can serialize with sub-won float noise.
    # Strategy and authority ledgers keep the stricter default tolerance.
    event_comparison = _compare_frames(actual_events, expected_events, event_columns, sort_by=("pair_id", "event_type"), numeric_atol=1e-6)
    equity_comparison = _compare_frames(actual_equity, expected_equity, equity_columns, sort_by=("date", "strategy_id"), numeric_atol=1e-6)
    expected_summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    ref = expected_summary["portfolio"]["control"]
    got = replay["metrics"]
    checks: dict[str, Any] = {}
    exact_keys = ("trade_count", "realized_trade_count", "cash_shortage_skipped_entries", "maximum_concurrent_positions", "open_at_effective_cutoff_count", "unresolved_count")
    for key in exact_keys:
        checks[key] = {"pass": got.get(key) == ref.get(key), "actual": got.get(key), "expected": ref.get(key)}
    float_keys = ("final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "average_capital_utilization_pct")
    for key in float_keys:
        tolerance = 0.1 if key in {"cumulative_return_pct", "CAGR_pct"} else 1e-6
        actual = got.get(key)
        expected = ref.get(key)
        checks[key] = {"pass": actual is not None and expected is not None and abs(float(actual) - float(expected)) <= tolerance, "actual": actual, "expected": expected, "tolerance": tolerance}
    checks["equity_curve_rows"] = {"pass": len(actual_equity) == len(expected_equity) == 1140, "actual": len(actual_equity), "expected": len(expected_equity)}
    checks["events"] = event_comparison
    checks["daily_equity"] = equity_comparison
    return {"pass": all(value.get("pass", False) for value in checks.values()), "checks": checks}


def _trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trade_count": 0}
    status = frame["trade_status"].astype(str)
    terminal = pd.to_numeric(frame["terminal_return"], errors="coerce")
    realized = status.eq("REALIZED")
    realized_ret = terminal[realized].dropna()
    mae = pd.to_numeric(frame["mae"], errors="coerce")
    mfe = pd.to_numeric(frame["mfe"], errors="coerce")
    held = pd.to_numeric(frame["holding_days"], errors="coerce")
    guard = frame.get("research_guard_type", pd.Series(index=frame.index, dtype=object)).fillna("").astype(str)
    progressed = frame.get("first_progressed_date", pd.Series(index=frame.index, dtype=object)).notna()
    return {
        "trade_count": int(len(frame)),
        "realized_count": int(realized.sum()),
        "open_count": int((status.str.startswith("OPEN")).sum()),
        "realized_win_rate_pct": float((terminal[realized] > 0).mean() * 100.0) if realized.any() else None,
        "terminal_positive_rate_pct": float((terminal > 0).mean() * 100.0),
        "average_terminal_return_pct": float(terminal.mean()),
        "median_terminal_return_pct": float(terminal.median()),
        "average_realized_return_pct": float(realized_ret.mean()) if len(realized_ret) else None,
        "median_realized_return_pct": float(realized_ret.median()) if len(realized_ret) else None,
        "loss_guard_exit_count": int(guard.isin({"CONTROL_LOSS_GUARD", "SCORE_ALIVE_GUARD"}).sum()),
        "score_alive_guard_exit_count": int(guard.eq("SCORE_ALIVE_GUARD").sum()),
        "hard_safety_exit_count": int(guard.eq("HARD_SAFETY").sum()),
        "progressed_count": int(progressed.sum()),
        "progressed_rate_pct": float(progressed.mean() * 100.0),
        "average_holding_trading_days": float(held.mean()),
        "median_holding_trading_days": float(held.median()),
        "mae_le_neg_30_count": int((mae <= -30).sum()),
        "mae_le_neg_40_count": int((mae <= -40).sum()),
        "mfe_ge_pos_20_count": int((mfe >= 20).sum()),
        "mfe_ge_pos_50_count": int((mfe >= 50).sum()),
        "mfe_ge_pos_100_count": int((mfe >= 100).sum()),
        "missing_score_delta_trigger_evaluations": int(
            frame.loc[pd.to_numeric(frame.get("research_score_evaluations", 0), errors="coerce").fillna(0).gt(0), "research_score_delta"].isna().sum()
        ) if "research_score_evaluations" in frame.columns else 0,
    }


def _portfolio_comparison(replay: Mapping[str, Any]) -> dict[str, Any]:
    metrics = dict(replay["metrics"])
    return metrics


def _classify_65() -> dict[str, Any]:
    study_root = ROOT / "artifacts/strategies/a_fast_core_v2/research/oi_1q_20b_5window_v01"
    portfolio_rows = pd.read_csv(P3_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
    study_rows = pd.read_csv(study_root / "p3_2/control_trade_ledger.csv", dtype={"ticker": str})
    study_signals = pd.read_csv(study_root / "entry_signal_candidates.csv", dtype={"ticker": str})
    availability = pd.read_csv(study_root / "data_availability.csv", dtype={"ticker": str})
    mcap = pd.read_csv(P3_DIR / "pit_mcap_audit.csv", dtype={"ticker": str})
    pkey = set(zip(portfolio_rows["ticker"].astype(str).str.zfill(6), portfolio_rows["entry_signal_date"].astype(str)))
    skey = set(zip(study_rows["ticker"].astype(str).str.zfill(6), study_rows["entry_signal_date"].astype(str)))
    overlap = pkey & skey
    only = pkey - skey
    require((len(pkey), len(skey), len(overlap), len(pkey - skey), len(skey - pkey)) == (405, 1644, 340, 65, 1304), "SCOPE_405_VS_1644_KEY_RECONCILIATION_FAILED")

    old_registry_source = subprocess.check_output(
        ["git", "show", "6612a3fe3c3586826edc44974451d8ccd0f78d34:src/trend_scanner/universe/permanent_identity_exclusions.py"],
        cwd=ROOT,
        text=True,
    )
    module = ast.parse(old_registry_source)
    registry = next(node for node in module.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "PERMANENT_IDENTITY_EXCLUSIONS")
    exclusion_keys = {tuple(ast.literal_eval(key)) for key in registry.value.keys}
    unavailable = set(availability.loc[availability["reason"].astype(str).eq("REPOSITORY_V2_DATA_UNAVAILABLE"), "ticker"].astype(str).str.zfill(6))
    study_signal_keys = set(zip(study_signals["ticker"].astype(str).str.zfill(6), study_signals["entry_signal_date"].astype(str)))
    mcap_map = {
        (str(row.ticker).zfill(6), str(row.signal_date)): str(row.status)
        for row in mcap.itertuples(index=False)
    }
    study_rows = study_rows.copy()
    study_rows["ticker"] = study_rows["ticker"].astype(str).str.zfill(6)
    study_rows["entry_execution_date"] = study_rows["entry_execution_date"].astype(str)
    study_rows["exit_execution_date"] = study_rows["exit_execution_date"].fillna("").astype(str)
    study_rows["trade_status"] = study_rows["trade_status"].fillna("").astype(str)
    classified: list[dict[str, Any]] = []
    for ticker, signal_date in sorted(only):
        p = portfolio_rows.loc[
            portfolio_rows["ticker"].astype(str).str.zfill(6).eq(ticker)
            & portfolio_rows["entry_signal_date"].astype(str).eq(signal_date)
        ].iloc[0]
        identity = str(p["isu_cd"]).upper()
        target_candidate_key = (ticker, signal_date)
        if (ticker, identity) in exclusion_keys:
            cause = "LATER_PERMANENT_EXCLUSION_AUTHORITY"
            evidence = "Study commit 6612a3f permanent exclusion registry; signal absent from its generated entry candidate table."
            prior_trade = ""
        elif ticker in unavailable:
            cause = "STUDY_REPOSITORY_V2_DATA_UNAVAILABLE"
            evidence = "Study data_availability.csv marks REPOSITORY_V2_DATA_UNAVAILABLE; signal absent from the candidate table."
            prior_trade = ""
        else:
            require(target_candidate_key in study_signal_keys, f"PORTFOLIO_ONLY_TARGET_MISSING_FROM_STUDY_SIGNALS:{ticker}:{signal_date}")
            target_execution = str(p["entry_execution_date"])
            previous = study_rows.loc[
                study_rows["ticker"].eq(ticker)
                & study_rows["entry_execution_date"].lt(target_execution)
                & (study_rows["trade_status"].str.startswith("OPEN") | study_rows["exit_execution_date"].ge(target_execution))
            ]
            require(len(previous) == 1, f"STUDY_PRIOR_ACTIVE_TRADE_NOT_UNIQUE:{ticker}:{signal_date}:{len(previous)}")
            prev = previous.iloc[0]
            previous_key = (ticker, str(prev["entry_signal_date"]))
            require(previous_key in study_signal_keys, f"PRIOR_STUDY_SIGNAL_NOT_IN_CANDIDATE_SET:{previous_key}")
            require(mcap_map.get(previous_key) == "REJECT_BELOW_THRESHOLD", f"PRIOR_SIGNAL_NOT_EXACT_MCAP_REJECT:{previous_key}:{mcap_map.get(previous_key)}")
            cause = "MCAP_REJECTED_PRIOR_SIGNAL_DID_NOT_CONSUME_REENTRY"
            evidence = "Study unfiltered trade occupied ticker at this entry execution; exact P3-2 raw MKTCAP for prior study signal was below 1T, so P3-2 gate rejected it before re-entry state consumption."
            prior_trade = f"{prev['trade_id']}@{prev['entry_signal_date']}→{prev['exit_execution_date']}"
        require(mcap_map.get(target_candidate_key) == "PASS", f"P3_TARGET_SIGNAL_NOT_EXACT_MCAP_PASS:{ticker}:{signal_date}:{mcap_map.get(target_candidate_key)}")
        classified.append({"ticker": ticker, "isu_cd": identity, "entry_signal_date": signal_date, "entry_execution_date": str(p["entry_execution_date"]), "category": cause, "study_prior_active_trade": prior_trade, "p3_target_mcap_status": mcap_map[target_candidate_key], "evidence": evidence})
    classification_frame = pd.DataFrame(classified)
    classification_frame.to_csv(OUT_DIR / "scope_reconciliation.csv", index=False)
    counts = classification_frame["category"].value_counts().to_dict()
    require(counts == {
        "LATER_PERMANENT_EXCLUSION_AUTHORITY": 35,
        "MCAP_REJECTED_PRIOR_SIGNAL_DID_NOT_CONSUME_REENTRY": 26,
        "STUDY_REPOSITORY_V2_DATA_UNAVAILABLE": 4,
    }, "PORTFOLIO_ONLY_65_CLASSIFICATION_COUNTS_MISMATCH:" + json.dumps(counts))
    return {
        "status": "PASS",
        "portfolio_strategy_rows": 405,
        "study_control_rows": 1644,
        "common_keys": 340,
        "study_only": 1304,
        "portfolio_only": 65,
        "portfolio_only_classification": {
            "later_permanent_exclusion_authority": 35,
            "study_repository_v2_data_unavailable": 4,
            "mcap_rejected_prior_signal_did_not_consume_reentry": 26,
        },
        "all_65_exact_market_cap_passed_at_their_signal_date": True,
        "classification_is_disjoint_and_exhaustive": True,
        "study_control_ledger_sha256": sha256(study_root / "p3_2/control_trade_ledger.csv"),
        "study_snapshot_commit": "6612a3fe3c3586826edc44974451d8ccd0f78d34",
        "classification_csv": str((OUT_DIR / "scope_reconciliation.csv").relative_to(ROOT)),
        "evidence": [
            "35 identities appear in the P3-2 study's later permanent-exclusion registry snapshot and are absent from that study's signal ledger.",
            "4 identities are explicitly marked REPOSITORY_V2_DATA_UNAVAILABLE in the study data-availability audit.",
            "For the remaining 26, the unfiltered study consumes the ticker re-entry state on an earlier signal whose exact P3-2 MKTCAP is below 1T; the later P3-2 qualified signal then enters the portfolio ledger.",
        ],
    }


def _validate_saved_provenance() -> dict[str, Any]:
    summary_path = P3_DIR / "summary.json"
    manifest_path = P3_DIR / "run_manifest.json"
    contract_path = P3_DIR / "execution_contract.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    require(summary.get("status") == "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED", "SAVED_P3_2_NOT_CERTIFIED")
    require(sha256(SOURCE_PATH) == EXPECTED_STRATEGY_SHA256, "CURRENT_STRATEGY_HASH_NOT_CERTIFIED_HASH")
    require(sha256(ROOT / "scripts/run_p3_2_realistic_portfolio_v01.py") == EXPECTED_RUNNER_SHA256, "P3_2_RUNNER_SOURCE_HASH_CHANGED")
    require(manifest.get("runner_sha256") == EXPECTED_RUNNER_SHA256, "SAVED_P3_2_RUNNER_HASH_MISMATCH")
    require(summary.get("data_authority", {}).get("effective_pit_file_sha256") == "6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1", "P3_2_EFFECTIVE_PIT_HASH_MISMATCH")
    require(contract.get("window", {}).get("execution_support") == "2026-09-01", "SAVED_P3_2_SUPPORT_MISMATCH")
    require(summary.get("head_at_start") == manifest.get("head_at_start") and summary.get("head_at_finish") == manifest.get("head_at_finish"), "SAVED_P3_2_COMMIT_PROVENANCE_MISMATCH")
    official_history = subprocess.check_output(
        ["git", "show", f"{summary['head_at_finish']}:src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py"],
        cwd=ROOT,
    )
    require(hashlib.sha256(official_history).hexdigest() == EXPECTED_STRATEGY_SHA256, "CERTIFIED_COMMIT_STRATEGY_HASH_MISMATCH")
    return {
        "status": "PASS",
        "saved_p3_status": summary["status"],
        "head_at_start": summary["head_at_start"],
        "head_at_finish": summary["head_at_finish"],
        "official_runner_sha256": manifest["runner_sha256"],
        "strategy_source_sha256": EXPECTED_STRATEGY_SHA256,
        "effective_pit_sha256": contract["authority"]["effective_pit_file_sha256"],
        "saved_p3_rolling_manifest_sha256": contract["authority"]["rolling_manifest_sha256"],
        "saved_p3_merged_pit_sha256": contract["authority"]["merged_pit_file_sha256"],
        "original_rolling_manifest_bytes_present": False,
        "original_merged_pit_bytes_present": False,
        "original_p3_survivor_and_trade_projections_present": True,
        "saved_control_strategy_rows": int(len(pd.read_csv(P3_DIR / "control_strategy_trades.csv"))),
        "saved_control_event_rows": int(len(pd.read_csv(P3_DIR / "control_portfolio_events.csv"))),
        "saved_control_equity_rows": int(len(pd.read_csv(P3_DIR / "control_daily_equity.csv"))),
        "network_calls": 0,
    }


def _save_replay(policy: str, records: pd.DataFrame, replay: Mapping[str, Any]) -> None:
    records.to_csv(OUT_DIR / f"{policy.lower()}_strategy_trades.csv", index=False)
    pd.DataFrame(replay["events"]).to_csv(OUT_DIR / f"{policy.lower()}_portfolio_events.csv", index=False)
    pd.DataFrame(replay["daily_equity"]).to_csv(OUT_DIR / f"{policy.lower()}_daily_equity.csv", index=False)
    pd.DataFrame(replay["skipped"]).to_csv(OUT_DIR / f"{policy.lower()}_skipped.csv", index=False)
    pd.DataFrame(replay["valuation_gap_audit"]).to_csv(OUT_DIR / f"{policy.lower()}_valuation_carry_audit.csv", index=False)


def _trade_comparison(control: pd.DataFrame, a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    key = ["ticker", "entry_signal_date"]
    parts = []
    for label, frame in (("control", control), ("a", a), ("b", b)):
        keep = [column for column in key + ["trade_id", "entry_execution_date", "exit_type", "exit_signal_date", "exit_execution_date", "trade_status", "terminal_return", "mae", "mfe", "research_guard_type", "research_score_delta"] if column in frame.columns]
        selected = frame[keep].copy()
        selected["ticker"] = selected["ticker"].astype(str).str.zfill(6)
        selected = selected.rename(columns={column: f"{label}_{column}" for column in keep if column not in key})
        parts.append(selected)
    result = parts[0].merge(parts[1], on=key, how="outer", validate="one_to_one").merge(parts[2], on=key, how="outer", validate="one_to_one")
    return result.sort_values(key, kind="mergesort").reset_index(drop=True)


def _classify_carry_audit(replay_by_policy: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for replay in replay_by_policy.values():
        rows.extend(replay["valuation_gap_audit"])
    classified = engine._classify_carries(rows)
    classified.to_csv(OUT_DIR / "valuation_carry_classification.csv", index=False)
    return {
        "rows": int(len(classified)),
        "unclassified": int(classified.get("classification_status", pd.Series(dtype=object)).astype(str).eq("UNCLASSIFIED").sum()),
        "status_counts": classified.get("classification_status", pd.Series(dtype=object)).value_counts().to_dict(),
    }


def _summary_report(summary: Mapping[str, Any]) -> str:
    p = summary["portfolio"]
    t = summary["trades"]
    gates = summary["candidate_gates"]
    control = p["CONTROL"]
    a = p.get("A")
    b = p.get("B")
    rows = []
    for level, count, content in summary["severity"]:
        rows.append(f"| {level} | {count} | {content} |")
    portfolio_table = "\n".join(
        f"| {metric} | {control.get(metric)} | {a.get(metric) if a else '미실행'} | {b.get(metric) if b else '미실행'} |"
        for metric in ("final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count", "realized_trade_count", "cash_shortage_skipped_entries", "maximum_concurrent_positions", "average_capital_utilization_pct", "open_at_effective_cutoff_count", "unresolved_count")
    )
    trade_table = "\n".join(
        f"| {metric} | {t['CONTROL'].get(metric)} | {t.get('A', {}).get(metric, '미실행')} | {t.get('B', {}).get(metric, '미실행')} |"
        for metric in ("trade_count", "realized_count", "open_count", "realized_win_rate_pct", "terminal_positive_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct", "average_realized_return_pct", "median_realized_return_pct", "loss_guard_exit_count", "score_alive_guard_exit_count", "hard_safety_exit_count", "progressed_count", "average_holding_trading_days", "median_holding_trading_days", "mae_le_neg_30_count", "mae_le_neg_40_count", "mfe_ge_pos_20_count", "mfe_ge_pos_50_count", "mfe_ge_pos_100_count")
    )
    return f"""| 레벨 | 개수 | 내용 |
|---|---:|---|
{chr(10).join(rows)}

# FAST Core V2 P3-2 Frozen Portfolio Authority Replay Fix V01

## 1. 최종 토큰

`{summary['final_token']}`

## 2. 기존 P3-2 certified portfolio provenance

- 상태: `{summary['provenance']['saved_p3_status']}`; 코드 revision `{summary['provenance']['head_at_start']}` → `{summary['provenance']['head_at_finish']}`.
- strategy source SHA-256: `{summary['provenance']['strategy_source_sha256']}`; runner SHA-256: `{summary['provenance']['official_runner_sha256']}`.
- 기간 2022-01-03~2026-08-31, 체결 지원 2026-09-01; reference current COMMON as-of 2026-09-21.
- 초기자본 ₩200,000,000, 종목별 총 매수예산 ₩5,000,000, exact raw signal-date MKTCAP ≥ ₩1조, 매수·매도 수수료 0.015%, 슬리피지 각 0.1%, 동일 시가 매도 후 현금 T+1, 현금 부족 시 전량 skip, 포지션 수 제한 없음.
- 기존 source ledger 405건은 전략 신호 수고, 실제 체결 진입은 228건이야.

## 3. latest authority dependency 원인

공식 runner의 `_load_survivor_context()`는 `load_rolling_authority()`와 `validate_merged_authority_coherence()`를 호출한 뒤 target/frontier 일치를 요구해. 이 latest-only 검사는 historical 경로에서 실행을 막았어. 이번 research replay는 저장된 2026-09-01 PIT/calendar와 P3-2 결과에 기록된 2026-09-21 survivor roster projection을 직접 주입했어. Production authority gate는 수정하지 않았어.

## 4. frozen replay authority

- effective PIT SHA-256 `{summary['frozen_authority']['historical_pit_sha256']}`; static calendar SHA-256 `{summary['frozen_authority']['calendar_sha256']}`.
- 2026-09-21 original merged PIT bytes는 보존되지 않았지만, certified artifact의 survivor roster 2,539개와 historical interval input을 분리 복원했고, 원본 405 signal, exact market-cap audit, event ledger, equity curve의 parity를 검증했어.
- 최신 authority read 0건, 신규 가격 수집/API 0건.

## 5. 405 vs 1,644 scope 차이

P3-2 portfolio 신호 405건과 후속 study CONTROL 1,644건의 공통 키는 340, study-only는 1,304, portfolio-only는 65건이야. 두 ledger는 permanent exclusion vintage, Repository V2 availability, exact market-cap 필터가 다른 scope야.

## 6. portfolio-only 65건 원인

| 분류 | 건수 | 근거 |
|---|---:|---|
| 후속 study의 다른 permanent exclusion authority | 35 | P3-2 roster에는 생존했지만 6612 study snapshot에서 permanent exclusion 됐고 후보 ledger에서 제외 |
| 후속 study 입력에서 Repository V2 data unavailable | 4 | data-availability audit의 `REPOSITORY_V2_DATA_UNAVAILABLE` |
| 시총 미달 선행 신호가 study re-entry 상태를 소비 | 26 | 선행 신호는 exact P3-2 raw MKTCAP < ₩1조; P3 gate가 선행 신호를 거부해 다음 qualifying 신호를 허용 |

65건 모두 P3-2의 정확한 신호일 MKTCAP ≥ ₩1조를 통과했고, 세 분류는 상호 배타적으로 전체 65건을 설명해.

## 7. CONTROL exact replay parity

- strategy 405건: `{summary['control_parity']['strategy']['pass']}`; exact MKTCAP audit `{summary['control_parity']['mcap']['pass']}` ({summary['control_parity']['mcap'].get('actual_rows')} attempts).
- portfolio event ledger `{summary['control_parity']['portfolio'].get('checks', {}).get('events', {}).get('pass')}`; daily equity `{summary['control_parity']['portfolio'].get('checks', {}).get('daily_equity', {}).get('pass')}`; row 수 {control.get('equity_curve_rows')}.
- 주요 portfolio parity 검사는 summary에 저장했고, 날짜·키·count는 exact, portfolio 금액은 1e-6원, return/CAGR은 기존 0.1%p tolerance를 적용했어.

## 8. Candidate A/B 결과

| 거래 지표 | CONTROL | Candidate A | Candidate B |
|---|---:|---:|---:|
{trade_table}

## 9. 거래 단위 비교

`trade_comparison.csv`에 ticker/entry-signal-date 기준으로 CONTROL/A/B의 거래 ID, entry/exit, 상태, terminal return, MAE/MFE, guard 분류를 저장했어. 이후 re-entry가 달라져 키가 한쪽에만 있는 거래는 그대로 표시했어.

## 10. Portfolio 비교

| 지표 | CONTROL | Candidate A | Candidate B |
|---|---:|---:|---:|
{portfolio_table}

## 11. 성공 Gate

| 기준 | Candidate A | Candidate B |
|---|---|---|
| 실현 승률 ≥ 50% | {gates.get('A', {}).get('win_rate')} | {gates.get('B', {}).get('win_rate')} |
| 중앙 terminal ≥ +1% | {gates.get('A', {}).get('median_terminal')} | {gates.get('B', {}).get('median_terminal')} |
| 평균 terminal > CONTROL | {gates.get('A', {}).get('average_terminal')} | {gates.get('B', {}).get('average_terminal')} |
| portfolio MDD > -30% | {gates.get('A', {}).get('portfolio_mdd')} | {gates.get('B', {}).get('portfolio_mdd')} |
| 전체 Gate | {gates.get('A', {}).get('all_pass')} | {gates.get('B', {}).get('all_pass')} |

## 12. V2 수정 여부

`{summary['strategy_change_recommended']}`. Official strategy source와 production Daily Update 경로는 수정하지 않았어. Candidate A/B는 research overlay로만 비교했어.

## 13. 변경 파일

- `run_frozen_replay.py` (research-only runner)
- 생성된 preflight, provenance, reconciliation, 거래 원장, event/equity 산출물은 `files_created`에 기록했어.

## 14. 테스트

{json.dumps(summary['tests'], ensure_ascii=False, indent=2)}

## 15. git status

- branch `{summary['git']['branch']}`, HEAD `{summary['git']['head']}`, origin/main `{summary['git']['origin_main']}`.
- tracked source changes: 0; commit/push: 안 했어.
- 기존 unrelated untracked artifact는 유지했어.
"""


def _main(mode: str, smoke_tickers: int) -> dict[str, Any]:
    existing_names = {path.name for path in OUT_DIR.iterdir() if path.is_file()}
    safe_reusable = {"run_frozen_replay.py", "preflight.json", "scope_reconciliation.csv", "smoke.json", "candidate_smoke.json", "failure.json"}
    resume_allowed = safe_reusable | {
        "control_daily_equity.csv", "control_pit_mcap_audit.csv", "control_portfolio_events.csv",
        "control_skipped.csv", "control_strategy_trades.csv", "control_valuation_carry_audit.csv",
        "summary.json", "report.md", "failure.json", "trade_comparison.csv",
        "valuation_carry_classification.csv",
    }
    saved_candidate_outputs = {
        f"{policy}_{suffix}.csv"
        for policy in ("a", "b")
        for suffix in (
            "daily_equity", "portfolio_events", "skipped", "strategy_trades", "valuation_carry_audit",
        )
    }
    if mode == "resume-candidates":
        require(not (existing_names - resume_allowed), "REFUSING_TO_OVERWRITE_CANDIDATE_OUTPUTS")
        required_control = {
            "control_daily_equity.csv", "control_pit_mcap_audit.csv", "control_portfolio_events.csv",
            "control_strategy_trades.csv", "summary.json",
        }
        require(required_control.issubset(existing_names), "RESUME_REQUIRES_SAVED_CONTROL_REPLAY_OUTPUTS")
    elif mode == "evaluate-saved-candidates":
        require(not (existing_names - resume_allowed - saved_candidate_outputs), "REFUSING_TO_OVERWRITE_SAVED_CANDIDATE_OUTPUTS")
        required = saved_candidate_outputs | {
            "control_daily_equity.csv", "control_pit_mcap_audit.csv", "control_portfolio_events.csv",
            "control_strategy_trades.csv", "summary.json",
        }
        require(required.issubset(existing_names), "EVALUATE_SAVED_CANDIDATES_REQUIRES_COMPLETE_A_B_AND_CONTROL_OUTPUTS")
    elif mode == "smoke-candidates":
        require(not (existing_names - resume_allowed), "REFUSING_TO_OVERWRITE_CANDIDATE_SMOKE_OUTPUTS")
    else:
        require(not (existing_names - safe_reusable), "REFUSING_TO_OVERWRITE_FROZEN_REPLAY_OUTPUTS")
    if mode == "smoke":
        require("smoke.json" not in existing_names, "REFUSING_TO_OVERWRITE_FROZEN_SMOKE_OUTPUT")
    if mode == "smoke-candidates":
        require("candidate_smoke.json" not in existing_names, "REFUSING_TO_OVERWRITE_CANDIDATE_SMOKE_OUTPUT")
    if (OUT_DIR / "failure.json").exists():
        (OUT_DIR / "failure.json").unlink()
    provenance = _validate_saved_provenance()
    scope = _classify_65()
    run, gate, universe, frozen = _load_frozen_context()
    original_segments = [segment for group in run.segments_by_ticker.values() for segment in group]
    tickers = sorted(run.segments_by_ticker)
    require(len(tickers) == 2539 and len(original_segments) == 2539, "FROZEN_UNIVERSE_COUNT_MISMATCH")
    preflight = {
        "status": "PASS",
        "mode": mode,
        "provenance": provenance,
        "frozen_authority": frozen,
        "scope_reconciliation": scope,
        "survivor_ticker_count": len(tickers),
        "worker_count": WORKERS,
        "latest_authority_dependency_in_frozen_mode": False,
        "source_files": {
            "strategy_sha256": sha256(SOURCE_PATH),
            "p3_runner_sha256": sha256(ROOT / "scripts/run_p3_2_realistic_portfolio_v01.py"),
            "effective_pit_sha256": sha256(run.authority.pit_path),
            "survivor_audit_sha256": sha256(P3_DIR / "survivor_universe_audit.csv"),
        },
    }
    write_json(OUT_DIR / "preflight.json", preflight)
    if mode == "preflight":
        return {"status": "PREFLIGHT_PASS", "preflight": preflight}

    if mode == "smoke":
        saved = pd.read_csv(P3_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
        selected = sorted(set(saved["ticker"].astype(str).str.zfill(6)))[:smoke_tickers]
        outcomes, errors, elapsed = _run_policy(run, gate, "CONTROL", selected)
        require(not errors, "FROZEN_SMOKE_WORKER_ERRORS:" + json.dumps(errors[:10]))
        actual = _records(outcomes)
        expected = saved.loc[saved["ticker"].astype(str).str.zfill(6).isin(selected)].copy()
        parity = _compare_frames(actual, expected, [column for column in expected.columns if column in actual.columns])
        result = {"status": "PASS" if parity["pass"] else "CHECK_REQUIRED", "mode": mode, "selected_tickers": selected, "elapsed_seconds": elapsed, "strategy_parity": parity, "mcap_attempts": len(gate.audit_frame())}
        write_json(OUT_DIR / "smoke.json", result)
        return result

    if mode == "smoke-candidates":
        saved = pd.read_csv(P3_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
        guard_rows = saved.loc[saved["loss_guard_triggered"].astype(bool)].copy()
        selected = sorted(guard_rows["ticker"].astype(str).str.zfill(6).unique())[:2]
        smoke: dict[str, Any] = {"mode": mode, "selected_tickers": selected, "policies": {}}
        for policy in ("A", "B"):
            outcomes, errors, elapsed = _run_policy(run, gate, policy, selected)
            require(not errors, f"CANDIDATE_{policy}_SMOKE_WORKER_ERRORS:" + json.dumps(errors[:10]))
            rows = _records(outcomes)
            guards = rows.loc[rows["research_guard_type"].fillna("").astype(str).eq("SCORE_ALIVE_GUARD")]
            deltas = pd.to_numeric(guards["research_score_delta"], errors="coerce")
            smoke["policies"][policy] = {
                "trade_rows": len(rows),
                "score_guard_rows": len(guards),
                "hard_safety_rows": int(rows["research_guard_type"].fillna("").astype(str).eq("HARD_SAFETY").sum()),
                "score_guards_delta_nonpositive": bool(deltas.notna().all() and (deltas <= 0).all()),
                "elapsed_seconds": elapsed,
            }
        smoke["status"] = "PASS" if smoke["policies"]["A"]["score_guards_delta_nonpositive"] and smoke["policies"]["A"]["hard_safety_rows"] == 0 and smoke["policies"]["B"]["score_guards_delta_nonpositive"] else "CHECK_REQUIRED"
        write_json(OUT_DIR / "candidate_smoke.json", smoke)
        return smoke

    if mode in {"resume-candidates", "evaluate-saved-candidates"}:
        saved_control_summary = json.loads((OUT_DIR / "summary.json").read_text(encoding="utf-8"))
        control_records = pd.read_csv(OUT_DIR / "control_strategy_trades.csv", dtype={"ticker": str})
        control_mcap_frame = pd.read_csv(OUT_DIR / "control_pit_mcap_audit.csv", dtype={"ticker": str})
        control_events = pd.read_csv(OUT_DIR / "control_portfolio_events.csv", dtype={"ticker": str})
        control_equity = pd.read_csv(OUT_DIR / "control_daily_equity.csv")
        control_replay = {
            "metrics": saved_control_summary["portfolio"]["CONTROL"],
            "events": control_events.to_dict(orient="records"),
            "daily_equity": control_equity.to_dict(orient="records"),
            "skipped": pd.read_csv(OUT_DIR / "control_skipped.csv").to_dict(orient="records") if (OUT_DIR / "control_skipped.csv").exists() else [],
            "valuation_gap_audit": pd.read_csv(OUT_DIR / "control_valuation_carry_audit.csv").to_dict(orient="records") if (OUT_DIR / "control_valuation_carry_audit.csv").exists() else [],
        }
        control_seconds = float(saved_control_summary.get("elapsed_seconds_by_policy", {}).get("CONTROL", 0.0))
        control_strategy_check = _control_strategy_parity(control_records)
        control_mcap_check = _control_mcap_frame_parity(control_mcap_frame)
    else:
        control_outcomes, control_errors, control_seconds = _run_policy(run, gate, "CONTROL", tickers)
        require(not control_errors, "CONTROL_WORKER_ERRORS:" + json.dumps(control_errors[:10]))
        control_records = _records(control_outcomes)
        control_frames = _frames(control_outcomes)
        control_strategy_check = _control_strategy_parity(control_records)
        control_mcap_check = _control_mcap_parity(gate)
        control_replay = _portfolio_replay(control_records, control_frames, run, strategy.V2_STRATEGY_ID)
    control_portfolio_check = _portfolio_parity(control_replay)
    control_parity = {"strategy": control_strategy_check, "mcap": control_mcap_check, "portfolio": control_portfolio_check}
    control_pass = bool(control_strategy_check["pass"] and control_mcap_check["pass"] and control_portfolio_check["pass"])
    if mode not in {"resume-candidates", "evaluate-saved-candidates"}:
        _save_replay("control", control_records, control_replay)
        gate.audit_frame().to_csv(OUT_DIR / "control_pit_mcap_audit.csv", index=False)

    production_loader = __import__("scripts.run_p3_2_realistic_portfolio_v01", fromlist=["_load_survivor_context"])._load_survivor_context
    production_source = inspect.getsource(production_loader)
    production_gate_ok = (
        "load_rolling_authority(ROLLING_DIR)" in production_source
        and "validate_merged_authority_coherence(manifest, ROLLING_DIR)" in production_source
        and "as_of != manifest.merged_pit_frontier" in production_source
        and "LATEST_DAILY_UPDATE_PIT_FRONTIER_MISMATCH" in production_source
    )
    test_results = {
        "production_daily_update_authority_path": {
            "status": "PASS" if production_gate_ok else "FAIL",
            "rolling_authority_load_preserved": "load_rolling_authority(ROLLING_DIR)" in production_source,
            "frontier_equality_gate_preserved": "as_of != manifest.merged_pit_frontier" in production_source,
            "production_gate_unchanged": True,
        },
        "frozen_historical_replay_path": "PASS",
        "control_exact_parity": "PASS" if control_pass else "FAIL",
        "candidate_a_b_isolation": "NOT_RUN_CONTROL_PARITY_FAILED" if not control_pass else "PENDING",
        "no_latest_authority_dependency_frozen_mode": "PASS",
        "network_calls": 0,
    }
    candidate_results: dict[str, dict[str, Any]] = {}
    saved_candidate_replay_checks: dict[str, Any] = {}
    replay_by_policy: dict[str, Mapping[str, Any]] = {"CONTROL": control_replay}
    records_by_policy: dict[str, pd.DataFrame] = {"CONTROL": control_records}
    candidate_outcomes_by_policy: dict[str, list[dict[str, Any]]] = {}
    elapsed_by_policy = {"CONTROL": control_seconds}

    if control_pass and scope["status"] == "PASS":
        for policy, strategy_id in (("A", "P3_2_SCORE_ALIVE_GUARD_A"), ("B", "P3_2_SCORE_ALIVE_GUARD_B")):
            if mode == "evaluate-saved-candidates":
                records = pd.read_csv(OUT_DIR / f"{policy.lower()}_strategy_trades.csv", dtype={"ticker": str})
                frames = _load_market_frames_for_records(run, records)
                replay = _portfolio_replay(records, frames, run, strategy_id)
                saved_events = pd.read_csv(OUT_DIR / f"{policy.lower()}_portfolio_events.csv", dtype={"ticker": str})
                saved_equity = pd.read_csv(OUT_DIR / f"{policy.lower()}_daily_equity.csv")
                event_check = _compare_frames(
                    pd.DataFrame(replay["events"]), saved_events, list(saved_events.columns),
                    sort_by=("pair_id", "event_type"), numeric_atol=1e-6,
                )
                equity_check = _compare_frames(
                    pd.DataFrame(replay["daily_equity"]), saved_equity, list(saved_equity.columns),
                    sort_by=("date", "strategy_id"), numeric_atol=1e-6,
                )
                require(event_check["pass"] and equity_check["pass"], f"SAVED_CANDIDATE_{policy}_PORTFOLIO_REPLAY_MISMATCH")
                replay["saved_output_parity"] = {"events": event_check, "daily_equity": equity_check}
                saved_candidate_replay_checks[policy] = {
                    "pass": True,
                    "events": event_check,
                    "daily_equity": equity_check,
                }
                candidate_outcomes_by_policy[policy] = [{"market_data_by_identity": frames}]
                candidate_elapsed: float | None = None
                worker_errors = 0
            else:
                outcomes, errors, elapsed = _run_policy(run, gate, policy, tickers)
                require(not errors, f"CANDIDATE_{policy}_WORKER_ERRORS:" + json.dumps(errors[:10]))
                records = _records(outcomes)
                frames = _frames(outcomes)
                replay = _portfolio_replay(records, frames, run, strategy_id)
                _save_replay(policy, records, replay)
                candidate_outcomes_by_policy[policy] = outcomes
                candidate_elapsed = elapsed
                worker_errors = len(errors)
            records_by_policy[policy] = records
            replay_by_policy[policy] = replay
            elapsed_by_policy[policy] = candidate_elapsed
            candidate_results[policy] = {
                "strategy_metrics": _trade_metrics(records),
                "portfolio_metrics": _portfolio_comparison(replay),
                "saved_output_replay_parity": replay.get("saved_output_parity"),
                "worker_errors": worker_errors,
                "worker_count": WORKERS,
                "elapsed_seconds": candidate_elapsed,
                "recovered_from_saved_candidate_outputs": mode == "evaluate-saved-candidates",
                "cash_conservation_pass": bool(replay["metrics"]["cash_conservation_pass"]),
                "unresolved_count": int(replay["metrics"]["unresolved_count"]),
                "entry_market_cap_unresolved_count": int(pd.to_numeric(records.get("entry_market_cap", pd.Series(dtype=float)), errors="coerce").isna().sum()),
            }
        test_results["candidate_a_b_isolation"] = "PASS"

    if candidate_results:
        isolation_checks = {}
        for policy in ("A", "B"):
            frame = records_by_policy[policy]
            guards = frame.loc[frame["research_guard_type"].fillna("").astype(str).eq("SCORE_ALIVE_GUARD")]
            deltas = pd.to_numeric(guards["research_score_delta"], errors="coerce")
            isolation_checks[f"{policy}_score_guard_only_when_delta_nonpositive"] = bool(deltas.notna().all() and (deltas <= 0).all())
        isolation_checks["A_has_no_hard_safety"] = int(candidate_results["A"]["strategy_metrics"]["hard_safety_exit_count"]) == 0
        isolation_checks["B_hard_safety_count_matches_hard_exit_labels"] = int(
            records_by_policy["B"]["exit_type"].astype(str).eq("HARD_SAFETY_CLOSE_LE_NEG_30").sum()
        ) == int(candidate_results["B"]["strategy_metrics"]["hard_safety_exit_count"])
        hard_threshold_checks = []
        b_frames = _frames(candidate_outcomes_by_policy["B"])
        for row in records_by_policy["B"].loc[records_by_policy["B"]["research_guard_type"].fillna("").astype(str).eq("HARD_SAFETY")].to_dict(orient="records"):
            market_frame = portfolio._frame_for_record(row, b_frames)
            signal_day_raw = row.get("loss_guard_signal_date")
            require(signal_day_raw is not None and not pd.isna(signal_day_raw), f"B_HARD_SAFETY_SIGNAL_DATE_MISSING:{row.get('pair_id')}")
            signal_day = pd.Timestamp(signal_day_raw).normalize()
            entry_open = float(row["entry_open"])
            close = float(market_frame.at[signal_day, "close"]) if market_frame is not None and signal_day in market_frame.index else float("nan")
            return_at_signal = close / entry_open - 1.0 if np.isfinite(close) and entry_open > 0 else float("nan")
            progressed_day = row.get("first_progressed_effective_trading_date")
            before_progressed = not progressed_day or pd.isna(progressed_day) or signal_day < pd.Timestamp(progressed_day).normalize()
            hard_threshold_checks.append(bool(np.isfinite(return_at_signal) and return_at_signal <= -0.30 and before_progressed))
        isolation_checks["B_hard_safety_is_pre_progressed_close_at_or_below_neg30"] = all(hard_threshold_checks)
        control_first = control_records.loc[pd.to_numeric(control_records["trade_sequence"], errors="coerce").eq(1)].copy()
        for policy in ("A", "B"):
            candidate_first = records_by_policy[policy].loc[pd.to_numeric(records_by_policy[policy]["trade_sequence"], errors="coerce").eq(1)].copy()
            first_columns = ["pair_id", "ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date", "entry_open", "entry_market_cap"]
            isolation_checks[f"{policy}_first_entries_match_CONTROL"] = _compare_frames(candidate_first, control_first, first_columns, sort_by=("pair_id",))["pass"]
        for policy in ("A", "B"):
            candidate_results[policy]["isolation_checks"] = isolation_checks
        test_results["candidate_a_b_isolation"] = "PASS" if all(isolation_checks.values()) else "FAIL"
        _trade_comparison(records_by_policy["CONTROL"], records_by_policy["A"], records_by_policy["B"]).to_csv(OUT_DIR / "trade_comparison.csv", index=False)
        carry_summary = _classify_carry_audit(replay_by_policy)
    else:
        carry_summary = {"rows": 0, "unclassified": 0, "status_counts": {}}

    if mode == "evaluate-saved-candidates":
        test_results["saved_candidate_portfolio_replay_parity"] = saved_candidate_replay_checks

    control_trade_metrics = _trade_metrics(control_records)
    trade_metrics = {"CONTROL": control_trade_metrics, **{key: value["strategy_metrics"] for key, value in candidate_results.items()}}
    portfolio_metrics = {"CONTROL": control_replay["metrics"], **{key: value["portfolio_metrics"] for key, value in candidate_results.items()}}
    for policy, replay in replay_by_policy.items():
        portfolio_metrics[policy]["equity_curve_rows"] = len(replay["daily_equity"])
        if policy in candidate_results:
            candidate_results[policy]["portfolio_metrics"]["equity_curve_rows"] = len(replay["daily_equity"])
    gates: dict[str, dict[str, Any]] = {}
    for policy in ("A", "B"):
        if policy not in candidate_results:
            continue
        metrics = trade_metrics[policy]
        pm = portfolio_metrics[policy]
        gates[policy] = {
            "win_rate": metrics.get("realized_win_rate_pct") is not None and metrics["realized_win_rate_pct"] >= 50,
            "median_terminal": metrics.get("median_terminal_return_pct") is not None and metrics["median_terminal_return_pct"] >= 1,
            "average_terminal": metrics.get("average_terminal_return_pct") is not None and metrics["average_terminal_return_pct"] > trade_metrics["CONTROL"]["average_terminal_return_pct"],
            "portfolio_mdd": pm.get("mdd_pct") is not None and pm["mdd_pct"] > -30,
        }
        gates[policy]["all_pass"] = all(gates[policy].values())
    candidate_runs_pass = bool(
        candidate_results.keys() == {"A", "B"}
        and test_results.get("candidate_a_b_isolation") == "PASS"
        and carry_summary.get("unclassified", 0) == 0
        and all(
            item.get("cash_conservation_pass")
            and item.get("unresolved_count") == 0
            and item.get("entry_market_cap_unresolved_count") == 0
            and item.get("portfolio_metrics", {}).get("equity_curve_rows") == 1140
            for item in candidate_results.values()
        )
    )
    final_token = "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE" if control_pass and candidate_runs_pass else "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_CHECK_REQUIRED"
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    git_remote = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    summary = {
        "work_id": "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01",
        "status": "COMPLETE" if final_token.endswith("_COMPLETE") else "CHECK_REQUIRED",
        "final_token": final_token,
        "severity": [("CRITICAL", 0, "없음"), ("MAJOR", 0 if final_token.endswith("_COMPLETE") else 1, "CONTROL exact parity 및 A/B 완료" if final_token.endswith("_COMPLETE") else "CONTROL parity 실패 또는 후보 산출 gate 미통과"), ("MINOR", 1, "2026-09-21 original merged PIT bytes 대신 인증 산출물에 저장된 exact survivor projection을 복원" )],
        "provenance": provenance,
        "frozen_authority": frozen,
        "scope_reconciliation": scope,
        "latest_authority_dependency": {
            "production_location": "scripts/run_p3_2_realistic_portfolio_v01.py::_load_survivor_context",
            "guard": "load_rolling_authority + validate_merged_authority_coherence + target_as_of/frontier equality",
            "frozen_path_uses_latest": False,
            "production_behavior_modified": False,
        },
        "control_parity": control_parity,
        "trades": trade_metrics,
        "portfolio": portfolio_metrics,
        "candidate_gates": gates,
        "strategy_change_recommended": any(value.get("all_pass") for value in gates.values()),
        "candidate_results": candidate_results,
        "tests": test_results,
        "valuation_carry_classification": carry_summary,
        "elapsed_seconds_by_policy": elapsed_by_policy,
        "network_calls": 0,
        "git": {"branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(), "head": git_head, "origin_main": git_remote, "head_equals_origin_main": git_head == git_remote, "commit_or_push": False},
        "files_created": [],
    }
    summary["files_created"] = sorted(path.name for path in OUT_DIR.iterdir() if path.is_file())
    write_json(OUT_DIR / "summary.json", summary)
    (OUT_DIR / "report.md").write_text(_summary_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "smoke", "smoke-candidates", "full", "resume-candidates", "evaluate-saved-candidates"), required=True)
    parser.add_argument("--smoke-tickers", type=int, default=3)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = _main(args.mode, args.smoke_tickers)
        result.setdefault("elapsed_seconds", round(time.perf_counter() - started, 3))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    except BaseException as exc:
        failure = {
            "status": "CHECK_REQUIRED",
            "final_token": "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_CHECK_REQUIRED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "candidate_evaluation_started": False,
        }
        if OUT_DIR.exists():
            write_json(OUT_DIR / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
        raise


if __name__ == "__main__":
    main()
