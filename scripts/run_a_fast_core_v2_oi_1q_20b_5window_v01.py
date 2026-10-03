#!/usr/bin/env python3
"""A FAST Core V2 latest disclosed 1Q operating income >= KRW 2B research replay.

This runner keeps the official V2 simulator unchanged. It discovers every
qualifying V2 entry signal in the PIT COMMON universe, evaluates only the
reusable B Select V03 operating-income PIT rule from local OpenDART caches,
then independently replays CONTROL and TEST20 for each standard window.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
import hashlib
import json
import multiprocessing
from pathlib import Path
import socket
import sys
import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts import run_b_select_core_oi_1q_filter_5window_v03 as oi_pit  # noqa: E402
from trend_scanner.backtest.standard_windows import (  # noqa: E402
    STANDARD_BACKTEST_WINDOWS,
    resolve_standard_backtest_window,
)
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar  # noqa: E402
from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.data.rolling_market_data_refresh import _content_digest  # noqa: E402
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
)

from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (  # noqa: E402
    simulate_ticker_core_v02_reentry,
)
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2_core  # noqa: E402

STUDY_ID = "A_FAST_CORE_V2_OI_1Q_20B_5WINDOW_V01"
OUTPUT = ROOT / "artifacts/strategies/a_fast_core_v2/research/oi_1q_20b_5window_v01"
PIT_PATH = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
ROLLING_MANIFEST_PATH = ROOT / "data/market/rolling_authority/manifest.json"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
OI_MIN_KRW = 2_000_000_000
WINDOW_DIR = {window_id: OUTPUT / window_id.lower().replace("-", "_") for window_id in WINDOW_IDS}
WORKERS = 10
_WORKER_STATE: dict[str, Any] = {}
_V2_EVALUATION_MEMO: dict[tuple[Any, ...], dict[str, Any]] = {}
_V2_EVALUATION_ORIGINAL = v2_core.evaluate_pattern_a_fast
_CONTRACT_FINGERPRINTS: dict[int, str] = {}


class ResearchInputError(RuntimeError):
    pass


def _contract_fingerprint(contract: Mapping[str, Any]) -> str:
    identity = id(contract)
    cached = _CONTRACT_FINGERPRINTS.get(identity)
    if cached is not None:
        return cached
    payload = json.dumps(contract, sort_keys=True, ensure_ascii=False, default=str)
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    _CONTRACT_FINGERPRINTS[identity] = fingerprint
    return fingerprint


def _memoized_evaluate_pattern_a_fast(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    as_of: pd.Timestamp,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    *,
    context: Any = None,
    market_calendar: Any = None,
) -> dict[str, Any]:
    """Reuse identical weekly V2 evaluations across independent window replays."""
    date = pd.Timestamp(as_of).normalize()
    first = pd.Timestamp(daily.index[0]).strftime("%Y-%m-%d") if len(daily.index) else ""
    last = pd.Timestamp(daily.index[-1]).strftime("%Y-%m-%d") if len(daily.index) else ""
    calendar_meta = getattr(market_calendar, "metadata", {}) or {}
    key = (
        str(ticker).zfill(6),
        date.strftime("%Y-%m-%d"),
        len(daily),
        first,
        last,
        _contract_fingerprint(score_contract),
        _contract_fingerprint(stage_contract),
        str(calendar_meta.get("authority_version", "")),
        str(calendar_meta.get("calendar_frontier", "")),
    )
    if key not in _V2_EVALUATION_MEMO:
        _V2_EVALUATION_MEMO[key] = _V2_EVALUATION_ORIGINAL(
            ticker,
            name,
            daily,
            date,
            score_contract,
            stage_contract,
            context=context,
            market_calendar=market_calendar,
        )
    return dict(_V2_EVALUATION_MEMO[key])


v2_core.evaluate_pattern_a_fast = _memoized_evaluate_pattern_a_fast


@contextmanager
def network_guard():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(self: socket.socket, address: Any) -> Any:  # noqa: ARG001
        raise RuntimeError("network access is prohibited during this cache-only research run")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, (np.integer, np.floating, np.bool_)):
            value = value.item()
        if value is pd.NA or value is pd.NaT:
            return None
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(payload), ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).upper(),
        pd.Timestamp(row.get("entry_signal_date")).strftime("%Y-%m-%d"),
    )


def membership(intervals: list[dict[str, Any]], day: pd.Timestamp) -> dict[str, Any] | None:
    date_text = pd.Timestamp(day).strftime("%Y-%m-%d")
    matches = [
        row for row in intervals
        if str(row["effective_from"])[:10] <= date_text <= str(row["effective_to"])[:10]
    ]
    if len(matches) > 1:
        raise ResearchInputError(f"overlapping COMMON identity intervals on {date_text}")
    return matches[0] if matches else None


def load_pit_universe() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pit = json.loads(PIT_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(ROLLING_MANIFEST_PATH.read_text(encoding="utf-8"))
    intervals = pit.get("intervals")
    if not isinstance(intervals, list) or pit.get("schema_version") != "MERGED_PIT_V01":
        raise ResearchInputError("merged PIT authority has an unexpected schema")
    digest = _content_digest(intervals)
    if digest != pit.get("content_digest") or digest != manifest.get("merged_pit_digest"):
        raise ResearchInputError("merged PIT authority digest does not match its manifest")
    common = [
        row for row in intervals
        if row.get("state") == "COMMON" and row.get("market") in {"KOSPI", "KOSDAQ"}
    ]
    excluded = [
        row for row in common
        if (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper()) in PERMANENT_IDENTITY_EXCLUSIONS
    ]
    kept = [row for row in common if row not in excluded]
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in kept:
        normalized = dict(row)
        normalized["ticker"] = str(row["ticker"]).zfill(6)
        normalized["isu_cd"] = str(row["isu_cd"]).upper()
        by_ticker[normalized["ticker"]].append(normalized)
    multiple_identities = {
        ticker: sorted({str(row["isu_cd"]) for row in rows})
        for ticker, rows in by_ticker.items()
        if len({str(row["isu_cd"]) for row in rows}) != 1
    }
    if multiple_identities:
        raise ResearchInputError(
            f"ticker reuse is ambiguous after permanent exclusions: {list(multiple_identities.items())[:8]}"
        )
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda row: (row["effective_from"], row["effective_to"], row["market"]))
    provenance = {
        "path": "data/market/rolling_authority/merged_pit_intervals.json",
        "manifest_path": "data/market/rolling_authority/manifest.json",
        "schema_version": pit["schema_version"],
        "target_as_of": pit.get("target_as_of"),
        "pit_frontier": pit.get("pit_frontier"),
        "source_basic_info_frontier": pit.get("source_basic_info_frontier"),
        "content_digest": digest,
        "all_common_stock_intervals": len(common),
        "excluded_common_segments": len(excluded),
        "excluded_identity_count": len({(r["ticker"], r["isu_cd"]) for r in excluded}),
        "eligible_common_segments": len(kept),
        "eligible_ticker_count": len(by_ticker),
        "eligible_stable_identity_count": len({(r["ticker"], r["isu_cd"]) for r in kept}),
        "permanent_exclusion_authority_version": "permanent_identity_exclusions_v01",
        "permanent_exclusion_identity_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
        "multiple_isu_ticker_count_after_exclusions": 0,
    }
    return dict(by_ticker), provenance


def resolve_windows(calendar: Any) -> dict[str, Any]:
    resolved = {window_id: resolve_standard_backtest_window(window_id, calendar) for window_id in WINDOW_IDS}
    for window_id, result in resolved.items():
        if result.execution_support <= result.effective_end:
            raise ResearchInputError(f"{window_id}: execution support is not after the window end")
    return resolved


def candidate_from_signal(
    *,
    ticker: str,
    daily: pd.DataFrame,
    intervals: list[dict[str, Any]],
    signal_date: pd.Timestamp,
    result: Mapping[str, Any],
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> tuple[dict[str, Any] | None, str | None]:
    signal_date = pd.Timestamp(signal_date).normalize()
    if signal_date < window_start or signal_date > window_end:
        return None, "OUTSIDE_SIGNAL_WINDOW"
    pos = daily.index.searchsorted(signal_date, side="right") - 1
    if pos < 0:
        return None, "NO_SIGNAL_INFORMATION_DATE"
    information_date = pd.Timestamp(daily.index[pos]).normalize()
    future = daily.index[daily.index > signal_date]
    if len(future) == 0:
        return None, "NO_EXECUTION_SUPPORT"
    execution_date = pd.Timestamp(future[0]).normalize()
    if execution_date > window_end:
        return None, "ENTRY_EXECUTION_AFTER_CUTOFF"
    signal_member = membership(intervals, signal_date)
    info_member = membership(intervals, information_date)
    execution_member = membership(intervals, execution_date)
    if signal_member is None or info_member is None or execution_member is None:
        return None, "NOT_COMMON_AT_SIGNAL_INFORMATION_OR_EXECUTION"
    identity = str(signal_member["isu_cd"]).upper()
    if (
        str(info_member["isu_cd"]).upper() != identity
        or str(execution_member["isu_cd"]).upper() != identity
    ):
        return None, "IDENTITY_CHANGED_ACROSS_ENTRY"
    market_at_signal = str(signal_member["market"])
    return {
        "candidate_id": f"{ticker}|{identity}|{signal_date.strftime('%Y-%m-%d')}",
        "ticker": ticker,
        "isu_cd": identity,
        "market_at_signal": market_at_signal,
        "entry_signal_date": signal_date.strftime("%Y-%m-%d"),
        "entry_signal_information_date": information_date.strftime("%Y-%m-%d"),
        "entry_execution_date": execution_date.strftime("%Y-%m-%d"),
        "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
        "fast_stage": str(result.get("fast_machine_stage") or ""),
        "fast_status": str(result.get("fast_machine_stage_status") or ""),
        "monthly_permission_state": str(result.get("fast_monthly_permission_state") or ""),
        "daily_risk_state": str(result.get("fast_daily_risk_state") or ""),
        "fast_score": result.get("fast_score"),
        "fast_score_status": str(result.get("fast_score_status") or ""),
    }, None


class SignalGate:
    def __init__(
        self,
        *,
        ticker: str,
        daily: pd.DataFrame,
        intervals: list[dict[str, Any]],
        window_start: pd.Timestamp,
        window_end: pd.Timestamp,
        mode: str,
        evaluation_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.ticker = ticker
        self.daily = daily
        self.intervals = intervals
        self.window_start = window_start
        self.window_end = window_end
        self.mode = mode
        self.evaluation_by_key = evaluation_by_key or {}
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.attempt_status = Counter()
        self.reject_reasons = Counter()

    def __call__(self, signal_date: pd.Timestamp, result: Mapping[str, Any]) -> bool:
        candidate, reason = candidate_from_signal(
            ticker=self.ticker,
            daily=self.daily,
            intervals=self.intervals,
            signal_date=signal_date,
            result=result,
            window_start=self.window_start,
            window_end=self.window_end,
        )
        if candidate is None:
            self.reject_reasons[str(reason)] += 1
            return False
        key = row_key(candidate)
        if self.mode == "discover":
            if key in self.rows:
                raise ResearchInputError(f"duplicate discovered entry signal: {key}")
            self.rows[key] = candidate
            return False
        evaluation = self.evaluation_by_key.get(key)
        if evaluation is None:
            raise ResearchInputError(f"PIT evaluation missing for entry candidate {key}")
        status = str(evaluation.get("oi_status") or "")
        if status not in {oi_pit.PASS, oi_pit.FAIL, oi_pit.UNAVAILABLE}:
            raise ResearchInputError(f"unexpected PIT status for {key}: {status}")
        self.attempt_status[status] += 1
        self.rows[key] = candidate
        if self.mode == "control":
            return True
        if self.mode == "test20":
            return status == oi_pit.PASS
        raise ResearchInputError(f"unknown replay gate mode: {self.mode}")


def load_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return score, stage


def _init_worker(state: dict[str, Any]) -> None:
    global _WORKER_STATE
    _WORKER_STATE = state


def _discover_one_ticker(ticker: str) -> dict[str, Any]:
    state = _WORKER_STATE
    _V2_EVALUATION_MEMO.clear()
    loader: RepositoryV2DailyLoader = state["loader"]
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        return {
            "ticker": ticker,
            "rows": [],
            "unavailable": {"ticker": ticker, "reason": "REPOSITORY_V2_DATA_UNAVAILABLE"},
            "rejections": {},
        }
    intervals = state["by_ticker"][ticker]
    full_window = state["resolved"]["P1"]
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    gate = SignalGate(
        ticker=ticker,
        daily=daily,
        intervals=intervals,
        window_start=full_window.effective_start,
        window_end=full_window.effective_end,
        mode="discover",
    )
    replay = simulate_ticker_core_v02_reentry(
        ticker=ticker,
        name=ticker,
        market=str(intervals[0]["market"]),
        daily=daily,
        score_contract=state["score_contract"],
        stage_contract=state["stage_contract"],
        cutoff_date=full_window.effective_end,
        snapshot_context=context,
        market_calendar=state["calendar"],
        entry_search_start=full_window.effective_start,
        signal_cutoff_date=full_window.effective_end,
        execution_support_date=full_window.execution_support,
        strict_errors=True,
        entry_execution_cutoff_date=full_window.effective_end,
        entry_signal_cutoff_date=full_window.effective_end,
        entry_signal_filter=gate,
    )
    if replay:
        raise ResearchInputError(f"discovery callback unexpectedly entered a trade for {ticker}")
    return {
        "ticker": ticker,
        "rows": list(gate.rows.values()),
        "unavailable": None,
        "rejections": dict(gate.reject_reasons),
    }


def discovery_scan(
    *,
    loader: RepositoryV2DailyLoader,
    by_ticker: Mapping[str, list[dict[str, Any]]],
    resolved: Mapping[str, Any],
    calendar: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, str]], dict[str, int]]:
    full_window = resolved["P1"]
    rows: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    aggregate_rejections = Counter()
    tickers = sorted(by_ticker)
    started = time.monotonic()
    state = {
        "loader": loader,
        "by_ticker": dict(by_ticker),
        "resolved": dict(resolved),
        "calendar": calendar,
        "score_contract": score_contract,
        "stage_contract": stage_contract,
    }
    completed = 0
    with ProcessPoolExecutor(
        max_workers=min(WORKERS, len(tickers)),
        mp_context=multiprocessing.get_context("fork"),
        initializer=_init_worker,
        initargs=(state,),
    ) as pool:
        futures = [pool.submit(_discover_one_ticker, ticker) for ticker in tickers]
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            rows.extend(result["rows"])
            if result["unavailable"] is not None:
                unavailable.append(result["unavailable"])
            aggregate_rejections.update(result["rejections"])
            if completed % 50 == 0 or completed == len(tickers):
                print(
                    f"signal discovery {completed}/{len(tickers)} tickers; candidates={len(rows)}; "
                    f"elapsed={time.monotonic() - started:.1f}s",
                    flush=True,
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "candidate_id", "ticker", "isu_cd", "market_at_signal", "entry_signal_date",
                "entry_signal_information_date", "entry_execution_date", "pattern_a_stage",
                "fast_stage", "fast_status", "monthly_permission_state", "daily_risk_state",
                "fast_score", "fast_score_status",
            ]
        )
    if not frame.empty:
        frame = frame.sort_values(["entry_signal_date", "ticker", "isu_cd"], kind="mergesort").reset_index(drop=True)
        if frame.duplicated(["ticker", "isu_cd", "entry_signal_date"]).any():
            raise ResearchInputError("duplicate entry candidates in the discovery ledger")
    return frame, unavailable, dict(aggregate_rejections)


def evaluate_candidates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], int]:
    if frame.empty:
        empty = pd.DataFrame(columns=["ticker", "isu_cd", "entry_signal_date", "oi_status", "oi_reason"])
        return empty, {
            "future_disclosure_reference_count": 0,
            "non_same_quarter_yoy_count": 0,
            "rule_recompute_mismatch_count": 0,
            "yoy_percent_contract_violation_count": 0,
        }, 0
    candidate_records = frame[
        ["ticker", "isu_cd", "entry_signal_date", "market_at_signal"]
    ].to_dict("records")
    evaluated = oi_pit.evaluate_fundamentals(candidate_records)
    if evaluated.empty:
        raise ResearchInputError("the reused B Select PIT evaluator returned no rows")
    return validate_and_normalize_evaluations(evaluated, frame)


def validate_and_normalize_evaluations(
    evaluated: pd.DataFrame,
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], int]:
    evaluated = evaluated.copy()
    evaluated["ticker"] = evaluated["ticker"].astype(str).str.zfill(6)
    evaluated["isu_cd"] = evaluated["isu_cd"].astype(str).str.upper()
    evaluated["entry_signal_date"] = evaluated["entry_signal_date"].astype(str).str[:10]
    key_columns = ["ticker", "isu_cd", "entry_signal_date"]
    if evaluated.duplicated(key_columns).any():
        raise ResearchInputError("duplicate PIT evaluation keys")
    expected = set(
        (str(row.ticker).zfill(6), str(row.isu_cd).upper(), str(row.entry_signal_date)[:10])
        for row in candidates.itertuples(index=False)
    )
    actual = {
        (str(row.ticker), str(row.isu_cd), str(row.entry_signal_date))
        for row in evaluated.itertuples(index=False)
    }
    if expected != actual:
        raise ResearchInputError("PIT evaluation key set differs from the discovered candidate set")
    audit = oi_pit.audit_evaluations(evaluated)
    fallback_count = 0
    for column in ("oi_reason", "rule_branch", "latest_quarter_reason"):
        if column in evaluated:
            fallback_count += int(
                evaluated[column].astype(str).str.contains("fallback", case=False, regex=False).sum()
            )
    if any(int(value) != 0 for value in audit.values()) or fallback_count:
        raise ResearchInputError(f"PIT audit failed: audit={audit}, fallback_count={fallback_count}")
    if "source_oi_status" not in evaluated:
        evaluated["source_oi_status"] = evaluated["oi_status"].astype(str)
    source_status = evaluated["source_oi_status"].astype(str)
    mismatch = source_status.eq("BASIS_OR_CURRENCY_MISMATCH")
    evaluated.loc[mismatch, "oi_status"] = oi_pit.UNAVAILABLE
    evaluated.loc[mismatch, "oi_reason"] = "BASIS_OR_CURRENCY_MISMATCH"
    allowed_statuses = {oi_pit.PASS, oi_pit.FAIL, oi_pit.UNAVAILABLE}
    normalized = set(evaluated["oi_status"].astype(str))
    if not normalized <= allowed_statuses:
        raise ResearchInputError(f"unexpected operating-income statuses after fail-closed mapping: {sorted(normalized - allowed_statuses)}")
    return evaluated, audit, fallback_count


def trade_return_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = []
    unresolved = 0
    for row in records:
        try:
            value = float(row.get("terminal_return"))
        except (TypeError, ValueError):
            unresolved += 1
            continue
        if not np.isfinite(value):
            unresolved += 1
            continue
        values.append(value)
    array = np.asarray(values, dtype=float)
    n = len(array)
    return {
        "trade_count": len(records),
        "resolved_trade_count": n,
        "unresolved_trade_count": unresolved,
        "realized_count": sum(str(row.get("trade_status")) == "REALIZED" for row in records),
        "open_at_cutoff_count": sum(str(row.get("trade_status")) == "OPEN_AT_CUTOFF" for row in records),
        "mean_pct": float(array.mean()) if n else None,
        "median_pct": float(np.median(array)) if n else None,
        "win_rate_pct": float((array > 0).mean() * 100) if n else None,
        "loss_rate_pct": float((array < 0).mean() * 100) if n else None,
        "ge_50_count": int((array >= 50).sum()) if n else 0,
        "ge_50_rate_pct": float((array >= 50).mean() * 100) if n else None,
        "worst_pct": float(array.min()) if n else None,
        "p10_pct": float(np.percentile(array, 10)) if n else None,
    }


def overlap_audit(records: list[dict[str, Any]]) -> dict[str, int]:
    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        rows_by_ticker[str(row["ticker"])].append(row)
    overlap = 0
    same_open = 0
    for rows in rows_by_ticker.values():
        rows.sort(key=lambda row: (str(row["entry_execution_date"]), int(row["trade_sequence"])))
        previous_exit: pd.Timestamp | None = None
        for row in rows:
            entry = pd.Timestamp(row["entry_execution_date"]).normalize()
            if previous_exit is not None and entry <= previous_exit:
                overlap += 1
                if entry == previous_exit:
                    same_open += 1
            exit_date = row.get("exit_execution_date")
            previous_exit = pd.Timestamp(exit_date).normalize() if exit_date else None
    return {"overlapping_positions": overlap, "same_open_exit_reentry": same_open}


def _replay_one_ticker(ticker: str) -> dict[str, Any]:
    state = _WORKER_STATE
    _V2_EVALUATION_MEMO.clear()
    loader: RepositoryV2DailyLoader = state["loader"]
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        raise ResearchInputError(f"Repository V2 data disappeared between discovery and replay: {ticker}")
    intervals = state["by_ticker"][ticker]
    market = str(intervals[0]["market"])
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    outputs: dict[str, dict[str, list[dict[str, Any]]]] = {
        window_id: {"CONTROL": [], "TEST20": []} for window_id in WINDOW_IDS
    }
    audit: dict[str, Any] = {
        window_id: {
            "control_attempt_status_counts": Counter(),
            "test20_attempt_status_counts": Counter(),
            "control_filter_rejections": Counter(),
            "test20_filter_rejections": Counter(),
        }
        for window_id in WINDOW_IDS
    }
    for window_id in WINDOW_IDS:
        window = state["resolved"][window_id]
        for group, mode in (("CONTROL", "control"), ("TEST20", "test20")):
            gate = SignalGate(
                ticker=ticker,
                daily=daily,
                intervals=intervals,
                window_start=window.effective_start,
                window_end=window.effective_end,
                mode=mode,
                evaluation_by_key=state["evaluation_by_key"],
            )
            records = simulate_ticker_core_v02_reentry(
                ticker=ticker,
                name=ticker,
                market=market,
                daily=daily,
                score_contract=state["score_contract"],
                stage_contract=state["stage_contract"],
                cutoff_date=window.effective_end,
                snapshot_context=context,
                market_calendar=state["calendar"],
                entry_search_start=window.effective_start,
                signal_cutoff_date=window.effective_end,
                execution_support_date=window.execution_support,
                strict_errors=True,
                entry_execution_cutoff_date=window.effective_end,
                entry_signal_cutoff_date=window.effective_end,
                entry_signal_filter=gate,
            )
            enriched = []
            for record in records:
                row = record.to_dict()
                matches = [
                    (key, value) for key, value in gate.rows.items()
                    if key[0] == str(ticker).zfill(6) and key[2] == str(row["entry_signal_date"])
                ]
                if len(matches) != 1:
                    raise ResearchInputError(
                        f"trade entry does not resolve to one PIT identity: {ticker}/{row['entry_signal_date']}"
                    )
                key, candidate = matches[0]
                evaluation = state["evaluation_by_key"][key]
                row["isu_cd"] = key[1]
                row["entry_signal_information_date"] = candidate["entry_signal_information_date"]
                row["market_at_signal"] = candidate["market_at_signal"]
                row["oi_status"] = str(evaluation.get("oi_status") or "")
                row["source_oi_status"] = str(evaluation.get("source_oi_status") or evaluation.get("oi_status") or "")
                row["oi_reason"] = str(evaluation.get("oi_reason") or "")
                row["latest_quarter"] = str(evaluation.get("latest_quarter") or "")
                row["current_operating_income"] = evaluation.get("current_operating_income")
                row["prior_operating_income"] = evaluation.get("prior_operating_income")
                row["yoy_pct"] = evaluation.get("yoy_pct")
                row["filter_applied"] = group == "TEST20"
                row["trade_key"] = "|".join(key)
                enriched.append(row)
            outputs[window_id][group].extend(enriched)
            target = audit[window_id]
            target[f"{mode}_attempt_status_counts"].update(gate.attempt_status)
            target[f"{mode}_filter_rejections"].update(gate.reject_reasons)
    return {
        "ticker": ticker,
        "outputs": outputs,
        "audit": {
            window_id: {key: dict(value) for key, value in window_audit.items()}
            for window_id, window_audit in audit.items()
        },
    }


def run_replays(
    *,
    loader: RepositoryV2DailyLoader,
    by_ticker: Mapping[str, list[dict[str, Any]]],
    candidates: pd.DataFrame,
    evaluations: pd.DataFrame,
    resolved: Mapping[str, Any],
    calendar: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, Any]]:
    evaluation_by_key = {
        row_key(row): row
        for row in evaluations.to_dict("records")
    }
    candidate_tickers = sorted(set(candidates["ticker"].astype(str).str.zfill(6))) if not candidates.empty else []
    outputs: dict[str, dict[str, list[dict[str, Any]]]] = {
        window_id: {"CONTROL": [], "TEST20": []} for window_id in WINDOW_IDS
    }
    audit: dict[str, Any] = {
        window_id: {
            "control_attempt_status_counts": Counter(),
            "test20_attempt_status_counts": Counter(),
            "control_filter_rejections": Counter(),
            "test20_filter_rejections": Counter(),
        }
        for window_id in WINDOW_IDS
    }
    started = time.monotonic()
    state = {
        "loader": loader,
        "by_ticker": dict(by_ticker),
        "evaluation_by_key": evaluation_by_key,
        "resolved": dict(resolved),
        "calendar": calendar,
        "score_contract": score_contract,
        "stage_contract": stage_contract,
    }
    completed = 0
    if candidate_tickers:
        with ProcessPoolExecutor(
            max_workers=min(WORKERS, len(candidate_tickers)),
            mp_context=multiprocessing.get_context("fork"),
            initializer=_init_worker,
            initargs=(state,),
        ) as pool:
            futures = [pool.submit(_replay_one_ticker, ticker) for ticker in candidate_tickers]
            for future in as_completed(futures):
                result = future.result()
                completed += 1
                for window_id in WINDOW_IDS:
                    for group in ("CONTROL", "TEST20"):
                        outputs[window_id][group].extend(result["outputs"][window_id][group])
                    for key, value in result["audit"][window_id].items():
                        audit[window_id][key].update(value)
                if completed % 25 == 0 or completed == len(candidate_tickers):
                    print(
                        f"independent replay {completed}/{len(candidate_tickers)} candidate tickers; "
                        f"elapsed={time.monotonic() - started:.1f}s",
                        flush=True,
                    )
    for window_id in WINDOW_IDS:
        for group in ("CONTROL", "TEST20"):
            outputs[window_id][group].sort(
                key=lambda row: (
                    str(row["ticker"]),
                    str(row["entry_signal_date"]),
                    int(row["trade_sequence"]),
                )
            )
            if group == "TEST20" and any(row["oi_status"] != oi_pit.PASS for row in outputs[window_id][group]):
                raise ResearchInputError(f"{window_id}: TEST20 contains a non-PASS entry")
            audit[window_id][f"{group.lower()}_overlap"] = overlap_audit(outputs[window_id][group])
    return outputs, audit


def evaluate_comparison(
    outputs: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    candidates: pd.DataFrame,
    evaluations: pd.DataFrame,
    resolved: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    eval_by_key = {row_key(row): row for row in evaluations.to_dict("records")}
    rows = []
    diagnostic = []
    integrity: dict[str, Any] = {}
    for window_id in WINDOW_IDS:
        control = list(outputs[window_id]["CONTROL"])
        test = list(outputs[window_id]["TEST20"])
        control_keys = {row_key(row) for row in control}
        test_keys = {row_key(row) for row in test}
        shared = control_keys & test_keys
        control_metrics = trade_return_metrics(control)
        test_metrics = trade_return_metrics(test)
        retention = len(shared) / len(control_keys) * 100 if control_keys else None
        test_volume_ratio = len(test_keys) / len(control_keys) * 100 if control_keys else None
        winner_keys = {
            row_key(row) for row in control
            if pd.notna(row.get("terminal_return")) and float(row["terminal_return"]) >= 50
        }
        loser_keys = {
            row_key(row) for row in control
            if pd.notna(row.get("terminal_return")) and float(row["terminal_return"]) < 0
        }
        status_counts = Counter()
        if not candidates.empty:
            start = resolved[window_id].effective_start.strftime("%Y-%m-%d")
            end = resolved[window_id].effective_end.strftime("%Y-%m-%d")
            subset = candidates.loc[
                candidates["entry_signal_date"].between(start, end, inclusive="both")
            ]
            for row in subset.to_dict("records"):
                status_counts[str(eval_by_key[row_key(row)]["oi_status"])] += 1
        for group, metrics in (("CONTROL", control_metrics), ("TEST20", test_metrics)):
            rows.append({
                "window_id": window_id,
                "scenario": group,
                **metrics,
                "control_trade_retention_pct": retention if group == "TEST20" else 100.0,
                "test_to_control_trade_count_pct": test_volume_ratio if group == "TEST20" else 100.0,
                "exact_shared_trade_count": len(shared) if group == "TEST20" else len(control_keys),
                "test_only_trade_count": len(test_keys - control_keys) if group == "TEST20" else 0,
            })
        kept_winners = len(winner_keys & test_keys)
        removed_losses = len(loser_keys - test_keys)
        diagnostic.append({
            "window_id": window_id,
            "raw_eligible_signal_pass": status_counts[oi_pit.PASS],
            "raw_eligible_signal_fail": status_counts[oi_pit.FAIL],
            "raw_eligible_signal_unavailable": status_counts[oi_pit.UNAVAILABLE],
            "control_trade_count": len(control_keys),
            "test20_trade_count": len(test_keys),
            "exact_shared_trade_count": len(shared),
            "test_only_trade_count": len(test_keys - control_keys),
            "control_ge_50_winner_count": len(winner_keys),
            "control_ge_50_winners_kept": kept_winners,
            "control_ge_50_winner_retention_pct": kept_winners / len(winner_keys) * 100 if winner_keys else None,
            "control_loss_trade_count": len(loser_keys),
            "control_losses_removed": removed_losses,
            "control_loss_removal_pct": removed_losses / len(loser_keys) * 100 if loser_keys else None,
        })
        integrity[window_id] = {
            "control_trade_count": len(control),
            "test20_trade_count": len(test),
            "control_test_key_intersection_count": len(shared),
            "test20_non_pass_entries": sum(row.get("oi_status") != oi_pit.PASS for row in test),
            "control_overlaps": overlap_audit(control),
            "test20_overlaps": overlap_audit(test),
            "signal_date_violations": sum(
                not (
                    resolved[window_id].effective_start.strftime("%Y-%m-%d")
                    <= str(row["entry_signal_date"])
                    <= resolved[window_id].effective_end.strftime("%Y-%m-%d")
                )
                for row in [*control, *test]
            ),
            "entry_execution_after_cutoff": sum(
                str(row["entry_execution_date"])[:10] > resolved[window_id].effective_end.strftime("%Y-%m-%d")
                for row in [*control, *test]
            ),
            "exit_execution_after_support": sum(
                bool(row.get("exit_execution_date"))
                and str(row["exit_execution_date"])[:10] > resolved[window_id].execution_support.strftime("%Y-%m-%d")
                for row in [*control, *test]
            ),
        }
    return pd.DataFrame(rows), pd.DataFrame(diagnostic), integrity


def attach_replay_attempt_counts(
    diagnostics: pd.DataFrame,
    replay_audit: Mapping[str, Any],
) -> pd.DataFrame:
    records = diagnostics.to_dict("records")
    for row in records:
        audit_row = replay_audit[row["window_id"]]
        row["control_attempt_count"] = sum(audit_row["control_attempt_status_counts"].values())
        row["test20_attempt_count"] = sum(audit_row["test20_attempt_status_counts"].values())
    return pd.DataFrame(records)


def format_number(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}"


def build_official_scope_audit(
    current_control_path: Path,
    official_ledger_path: Path,
    official_reproduction: Mapping[str, Any],
) -> dict[str, Any]:
    official = pd.read_csv(official_ledger_path, dtype={"ticker": "string"})
    current = pd.read_csv(current_control_path, dtype={"ticker": "string"})
    for frame in (official, current):
        frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
        frame["entry_signal_date"] = frame["entry_signal_date"].astype(str).str[:10]
    official_keys = set(zip(official["ticker"], official["entry_signal_date"]))
    current_keys = set(zip(current["ticker"], current["entry_signal_date"]))
    return {
        "full_study_comparable_to_official_ledger": False,
        "comparability_reasons": [
            "official parity runner uses the 2026-08-14 investability universe with market_cap >= KRW 100B and avg_trading_value_20d >= KRW 300M; this study is required to use no such filters",
            "official parity runner reads data/raw/stocks through ParquetCache; this study uses MarketDataRepositoryV2 for both scenarios",
            "official ledger covers 2017-04-28 through 2026-08-07; study P1 covers 2014-01-02 through 2026-08-31",
        ],
        "official_ledger": {
            "path": str(official_ledger_path.relative_to(ROOT)),
            "rows": len(official),
            "tickers": int(official["ticker"].nunique()),
            "first_entry_signal_date": str(official["entry_signal_date"].min()),
            "last_entry_signal_date": str(official["entry_signal_date"].max()),
            "market_data_source": "data/raw/stocks via ParquetCache",
            "universe_source": "pattern_a_investability_universe_20260814.csv",
            "market_cap_floor_krw": 100_000_000_000,
            "average_20d_trading_value_floor_krw": 300_000_000,
            "as_of": "2026-08-14",
        },
        "study_p1_control": {
            "path": str(current_control_path.relative_to(ROOT)),
            "rows": len(current),
            "tickers": int(current["ticker"].nunique()),
            "first_entry_signal_date": str(current["entry_signal_date"].min()),
            "last_entry_signal_date": str(current["entry_signal_date"].max()),
            "market_data_source": "MarketDataRepositoryV2",
            "market_cap_filter": False,
            "trading_value_filter": False,
            "window_start": "2014-01-02",
            "window_end": "2026-08-31",
        },
        "descriptive_entry_key_overlap": {
            "key": ["ticker", "entry_signal_date"],
            "shared_count": len(official_keys & current_keys),
            "official_keys_absent_from_study_p1": len(official_keys - current_keys),
            "study_p1_keys_absent_from_official": len(current_keys - official_keys),
            "interpret_as_parity": False,
        },
        "official_core_reproduction": dict(official_reproduction),
    }


def severity_counts(
    *,
    integrity: Mapping[str, Any],
    pit_audit: Mapping[str, Any],
    fallback_count: int,
    data_gaps: list[dict[str, str]],
    parity: Mapping[str, Any],
    scope_audit: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, int]:
    critical = int(parity.get("verdict") != "ACCEPT")
    critical += sum(int(value) for value in pit_audit.values())
    critical += int(fallback_count > 0)
    for item in integrity.values():
        critical += int(item["test20_non_pass_entries"] > 0)
        critical += int(item["signal_date_violations"] > 0)
        critical += int(item["entry_execution_after_cutoff"] > 0)
        critical += int(item["exit_execution_after_support"] > 0)
        critical += int(item["control_overlaps"]["overlapping_positions"] > 0)
        critical += int(item["test20_overlaps"]["overlapping_positions"] > 0)
    major = int(bool(data_gaps)) + int(not scope_audit.get("full_study_comparable_to_official_ledger", False))
    minor = int(metadata["pit_status_counts"].get(oi_pit.UNAVAILABLE, 0))
    return {"CRITICAL": critical, "MAJOR": major, "MINOR": minor}


def render_report(
    *,
    comparisons: pd.DataFrame,
    diagnostics: pd.DataFrame,
    integrity: Mapping[str, Any],
    pit_audit: Mapping[str, Any],
    fallback_count: int,
    data_gaps: list[dict[str, str]],
    parity: Mapping[str, Any],
    scope_audit: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> str:
    severity = severity_counts(
        integrity=integrity,
        pit_audit=pit_audit,
        fallback_count=fallback_count,
        data_gaps=data_gaps,
        parity=parity,
        scope_audit=scope_audit,
        metadata=metadata,
    )
    lines = [
        "# A FAST Core V2 최근 1Q 영업이익 20억 5-window 연구 V01",
        "",
        "## 검수 수준",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        f'| CRITICAL | {severity["CRITICAL"]} |',
        f'| MAJOR | {severity["MAJOR"]} |',
        f'| MINOR | {severity["MINOR"]} |',
        "",
        "## 5개 표준 기간 CONTROL vs TEST20 PRIMARY 비교",
        "",
        "| 기간 | 그룹 | 거래 수 | TEST 보존율 | 평균 % | 중앙값 % | 승률 % | 손실률 % | >=50% 건수/비율 | 최악 % | p10 % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window_id in WINDOW_IDS:
        for group in ("CONTROL", "TEST20"):
            row = comparisons.loc[
                comparisons["window_id"].eq(window_id) & comparisons["scenario"].eq(group)
            ].iloc[0]
            retained = "—" if group == "CONTROL" else format_number(row["control_trade_retention_pct"])
            ge50 = f'{int(row["ge_50_count"])} / {format_number(row["ge_50_rate_pct"])}'
            lines.append(
                f'| {window_id} | {group} | {int(row["trade_count"])} | {retained} | '
                f'{format_number(row["mean_pct"])} | {format_number(row["median_pct"])} | '
                f'{format_number(row["win_rate_pct"])} | {format_number(row["loss_rate_pct"])} | '
                f'{ge50} | {format_number(row["worst_pct"])} | {format_number(row["p10_pct"])} |'
            )
    lines.extend([
        "",
        "## 1. PIT coverage / PASS·FAIL·UNAVAILABLE",
        "",
        f'- AFAST 조건을 만족하고 entry 날짜·정보 날짜·익일 체결일의 PIT COMMON 검사를 통과한 원시 신호: {metadata["candidate_count"]}건.',
        f'- 전체 PIT 판정: PASS {metadata["pit_status_counts"].get(oi_pit.PASS, 0)}건, FAIL {metadata["pit_status_counts"].get(oi_pit.FAIL, 0)}건, UNAVAILABLE {metadata["pit_status_counts"].get(oi_pit.UNAVAILABLE, 0)}건.',
        f'- 재사용 판정기의 BASIS_OR_CURRENCY_MISMATCH {metadata.get("source_pit_status_counts", {}).get("BASIS_OR_CURRENCY_MISMATCH", 0)}건은 비교 불가로 보고 UNAVAILABLE에 포함해 진입을 차단했다. 원본 status는 PIT 평가 파일과 trade ledger에 보존했다.',
        f'- PIT audit: future disclosure {pit_audit.get("future_disclosure_reference_count", 0)}건, same-quarter YoY mismatch {pit_audit.get("non_same_quarter_yoy_count", 0)}건, rule arithmetic mismatch {pit_audit.get("rule_recompute_mismatch_count", 0)}건, YoY contract mismatch {pit_audit.get("yoy_percent_contract_violation_count", 0)}건, prior-quarter fallback {fallback_count}건.',
        "- UNAVAILABLE은 진입 불가로 fail-closed 처리했다.",
        "",
        "| 기간 | PASS | FAIL | UNAVAILABLE | CONTROL 실제 진입 시도 | TEST20 실제 진입 시도 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for row in diagnostics.to_dict("records"):
        lines.append(
            f'| {row["window_id"]} | {row["raw_eligible_signal_pass"]} | {row["raw_eligible_signal_fail"]} | '
            f'{row["raw_eligible_signal_unavailable"]} | {row.get("control_attempt_count", 0)} | {row.get("test20_attempt_count", 0)} |'
        )
    lines.extend([
        "",
        "## 2. CONTROL의 >=50% winner 보존",
        "",
        "| 기간 | CONTROL winner | TEST20 보존 | 보존율 |",
        "|---|---:|---:|---:|",
    ])
    for row in diagnostics.to_dict("records"):
        lines.append(
            f'| {row["window_id"]} | {row["control_ge_50_winner_count"]} | {row["control_ge_50_winners_kept"]} | '
            f'{format_number(row["control_ge_50_winner_retention_pct"])}% |'
        )
    lines.extend([
        "",
        "## 3. CONTROL 손실 거래 제거",
        "",
        "| 기간 | CONTROL 손실 거래 | TEST20에서 제거 | 제거율 |",
        "|---|---:|---:|---:|",
    ])
    for row in diagnostics.to_dict("records"):
        lines.append(
            f'| {row["window_id"]} | {row["control_loss_trade_count"]} | {row["control_losses_removed"]} | '
            f'{format_number(row["control_loss_removal_pct"])}% |'
        )
    lines.extend([
        "",
        "## 4. 기간별 특이점",
        "",
    ])
    for window_id in WINDOW_IDS:
        row = diagnostics.loc[diagnostics["window_id"].eq(window_id)].iloc[0]
        testrow = comparisons.loc[
            comparisons["window_id"].eq(window_id) & comparisons["scenario"].eq("TEST20")
        ].iloc[0]
        lines.append(
            f'- {window_id}: TEST20은 CONTROL과 정확히 같은 진입 키 {row["exact_shared_trade_count"]}건을 보존했고, '
            f'별도 진입 {row["test_only_trade_count"]}건이 발생했다. 미해결 terminal 수는 {int(testrow["unresolved_trade_count"])}건.'
        )
    lines.extend([
        "",
        "## 5. 전체 해석",
        "",
        "이 결과는 A FAST Core V2의 공식 규칙과 lifecycle을 유지하고, entry 시점 PIT 영업이익 조건 하나만 추가한 연구 비교다. 중앙값·승률·손실률·p10은 5개 기간 모두 개선됐지만 평균은 3개 기간만 개선됐고 P2-1은 하락, P3-1은 사실상 보합이다. CONTROL의 >=50% winner 보존은 18.9–46.3%에 그친 반면 CONTROL 손실은 56.6–82.9% 제거됐다. loser-filter 성격은 보이지만 큰 winner도 상당수 제거해 일관 우위로 판정할 수 없다. 공식 전략 변경·승격 결론은 내리지 않는다.",
        "",
        f'- 시작 HEAD: {metadata["starting_git"]["head"]}',
        f'- 기존 공식 V2 구현 재현 확인: {parity.get("verdict")} ({parity.get("authority_trades")} authority / {parity.get("production_trades")} reproduced trades). 이 parity는 2026-08-14 투자 가능 종목 universe와 legacy raw cache 범위다.',
        f'- 기존 공식 원장과 이번 P1은 직접 같은 범위가 아니다: 공식 {scope_audit["official_ledger"]["rows"]}건/{scope_audit["official_ledger"]["tickers"]}종목, 이번 P1 {scope_audit["study_p1_control"]["rows"]}건/{scope_audit["study_p1_control"]["tickers"]}종목. 이번 지시서의 무시총·무거래대금 조건 및 Repository V2 데이터 기준을 우선해 별도 비교했으며, 두 거래 수를 직접 parity로 해석하지 않았다.',
        f'- 공식 원장과 P1의 descriptive `(ticker, entry_signal_date)` 교집합은 {scope_audit["descriptive_entry_key_overlap"]["shared_count"]}건이며, 서로 다른 universe·market data·기간이므로 이 건수도 parity 판정이 아니다.',
        f'- PIT authority digest: {metadata["pit_authority"]["content_digest"]}.',
        f'- Permanent exclusion: {metadata["pit_authority"]["excluded_identity_count"]} identities, {metadata["pit_authority"]["excluded_common_segments"]} COMMON segments; CONTROL/TEST20 동일 적용.',
        f'- Market-data source: MarketDataRepositoryV2; signal cutoff 2026-08-31, exit execution support is the next KRX session.',
        f'- Local Repository V2 data gaps: {len(data_gaps)} ticker identities; see data_availability.csv.',
        "- External requests 0건. 공식 전략 코드와 공식 문서는 변경하지 않았고 push하지 않았다.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    started = time.monotonic()
    start_head = git("rev-parse", "HEAD")
    start_tree = git("rev-parse", "HEAD^{tree}")
    if (OUTPUT / "summary.json").exists():
        raise ResearchInputError(f"study output already exists; refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metadata_path = OUTPUT / "execution_metadata.json"
    prior_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    candidate_path = OUTPUT / "entry_signal_candidates.csv"
    evaluation_path = OUTPUT / "oi_entry_evaluations.csv"
    availability_path = OUTPUT / "data_availability.csv"
    prior_metadata_mtime = metadata_path.stat().st_mtime if metadata_path.exists() else float("inf")
    cached_discovery_files_newer = (
        candidate_path.exists()
        and evaluation_path.exists()
        and candidate_path.stat().st_mtime >= prior_metadata_mtime
        and evaluation_path.stat().st_mtime >= prior_metadata_mtime
    )
    pit_by_ticker, pit_provenance = load_pit_universe()
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise ResearchInputError("rolling production market calendar unavailable")
    resolved = resolve_windows(calendar)
    score_contract, stage_contract = load_contracts()
    authority_end = pd.Timestamp(calendar.max_observed_trading_date).normalize()
    max_support = max(item.execution_support for item in resolved.values())
    if max_support > authority_end:
        raise ResearchInputError(f"market calendar does not cover execution support: {max_support} > {authority_end}")
    boundaries = {
        window_id: {
            "calendar_start": result.window.calendar_start.strftime("%Y-%m-%d"),
            "calendar_end": result.window.calendar_end.strftime("%Y-%m-%d"),
            "effective_start": result.effective_start.strftime("%Y-%m-%d"),
            "effective_end": result.effective_end.strftime("%Y-%m-%d"),
            "execution_support": result.execution_support.strftime("%Y-%m-%d"),
        }
        for window_id, result in resolved.items()
    }
    input_metadata = {
        "study_id": STUDY_ID,
        "starting_git": {"head": start_head, "tree": start_tree, "branch": git("branch", "--show-current")},
        "strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "test_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02_OI_1Q_20B_RESEARCH_V01",
        "control_delta": "none",
        "test_delta": "entry eligibility only: latest disclosed 1Q operating income >= KRW 2B and same-quarter YoY >= +1% only when prior-year quarter is positive",
        "filter_threshold_krw": OI_MIN_KRW,
        "periods": boundaries,
        "pit_authority": pit_provenance,
        "market_calendar": {
            "authority": calendar.metadata.get("authority_version"),
            "certified_through": str(calendar.metadata.get("certified_through")),
            "frontier": str(calendar.metadata.get("calendar_frontier")),
            "last_observed_trading_date": str(calendar.max_observed_trading_date.date()),
        },
        "score_contract_sha256": sha256_file(SCORE_CONTRACT_PATH),
        "stage_contract_sha256": sha256_file(STAGE_CONTRACT_PATH),
        "official_v2_simulator_sha256": sha256_file(ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py"),
        "b_select_oi_pit_source_sha256": sha256_file(ROOT / "src/trend_scanner/backtest/b_select_core_oi_1q_v03.py"),
        "b_select_pit_runner_sha256": sha256_file(ROOT / "scripts/run_b_select_core_oi_1q_filter_5window_v03.py"),
        "market_data_source": "MarketDataRepositoryV2",
        "fundamentals_source": "local OpenDART FilingRegistry and XBRL cache; socket connections blocked",
        "entry_execution_cutoff": "no entry execution after each window effective_end",
        "exit_execution_support": "only exit signals on or before effective_end can fill on the next KRX session",
        "no_market_cap_filter": True,
        "no_trading_value_filter": True,
        "no_portfolio_cap": True,
        "no_prior_quarter_fallback": True,
        "no_future_disclosure": True,
        "official_strategy_files_modified": False,
        "worker_count": WORKERS,
        "parallel_context": "fork; each ticker processed independently; read-only market authority",
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "push": False,
    }
    checkpoint_fields = (
        "study_id", "starting_git", "periods", "pit_authority", "market_calendar",
        "score_contract_sha256", "stage_contract_sha256", "official_v2_simulator_sha256",
        "b_select_oi_pit_source_sha256", "b_select_pit_runner_sha256", "market_data_source",
        "filter_threshold_krw", "test_delta", "no_prior_quarter_fallback", "no_future_disclosure",
        "worker_count",
    )
    checkpoint_matches = bool(prior_metadata) and all(
        prior_metadata.get(field) == input_metadata.get(field) for field in checkpoint_fields
    )
    resume_from_pit_checkpoint = checkpoint_matches and cached_discovery_files_newer
    write_json(OUTPUT / "execution_metadata.json", input_metadata)
    write_json(
        OUTPUT / "window_boundaries.json",
        {
            "standard_window_source": "src/trend_scanner/backtest/standard_windows.py",
            "windows": boundaries,
            "all_effective_boundaries_resolved_from_market_calendar": True,
        },
    )

    output_end = max(item.execution_support for item in resolved.values())
    repository = build_repository_v2(ROOT, end=output_end)
    loader = RepositoryV2DailyLoader(repository, start="2010-01-01", end=output_end)
    full_window = resolved["P1"]
    score_contract_sha = sha256_file(SCORE_CONTRACT_PATH)
    stage_contract_sha = sha256_file(STAGE_CONTRACT_PATH)
    print(
        f"Repository V2 ready; eligible identities={pit_provenance['eligible_stable_identity_count']}; "
        f"frontier={pit_provenance['pit_frontier']}; P1={full_window.effective_start.date()}..{full_window.effective_end.date()}",
        flush=True,
    )
    with network_guard():
        if resume_from_pit_checkpoint:
            print("Resuming verified candidate/PIT checkpoint; both ledgers predate this invocation and match authority metadata.", flush=True)
            candidates = pd.read_csv(candidate_path, dtype={
                "ticker": "string", "isu_cd": "string", "entry_signal_date": "string",
            })
            if candidates.duplicated(["ticker", "isu_cd", "entry_signal_date"]).any():
                raise ResearchInputError("cached candidate ledger contains duplicate entry keys")
            data_gaps = pd.read_csv(availability_path, dtype={"ticker": "string"}).to_dict("records") if availability_path.exists() else []
            raw_evaluations = pd.read_csv(evaluation_path, dtype={
                "ticker": "string", "isu_cd": "string", "entry_signal_date": "string",
            })
            evaluated, pit_audit, fallback_count = validate_and_normalize_evaluations(raw_evaluations, candidates)
            discovery_rejections = {
                "resumed_from_verified_candidate_pit_checkpoint": True,
                "rejection_counts_available": False,
            }
        else:
            candidates, data_gaps, discovery_rejections = discovery_scan(
                loader=loader,
                by_ticker=pit_by_ticker,
                resolved=resolved,
                calendar=calendar,
                score_contract=score_contract,
                stage_contract=stage_contract,
            )
            write_csv(candidate_path, candidates)
            write_csv(availability_path, pd.DataFrame(data_gaps, columns=["ticker", "reason"]))
            evaluated, pit_audit, fallback_count = evaluate_candidates(candidates)
        write_csv(OUTPUT / "oi_entry_evaluations.csv", evaluated)
        if not evaluated.empty:
            merged = candidates.merge(
                evaluated,
                on=["ticker", "isu_cd", "entry_signal_date"],
                how="left",
                validate="one_to_one",
            )
            if merged["oi_status"].isna().any():
                raise ResearchInputError("candidate-to-PIT merge has missing status rows")
            status_counts = Counter(merged["oi_status"].astype(str))
        else:
            status_counts = Counter()
        if len(set(status_counts).intersection({oi_pit.PASS, oi_pit.FAIL, oi_pit.UNAVAILABLE})) != len(status_counts):
            raise ResearchInputError(f"unexpected operating-income status values: {dict(status_counts)}")
        source_status_counts = Counter(evaluated["source_oi_status"].astype(str)) if not evaluated.empty else Counter()
        write_json(OUTPUT / "pit_audit.json", {
            "pit_integrity": pit_audit,
            "fallback_count": fallback_count,
            "status_counts": dict(status_counts),
            "source_status_counts": dict(source_status_counts),
            "basis_currency_mismatch_normalized_to_unavailable": int(source_status_counts.get("BASIS_OR_CURRENCY_MISMATCH", 0)),
            "basis_currency_mismatch_policy": "not comparable for the requested OI rule; fail closed as UNAVAILABLE while preserving source_oi_status",
            "candidate_count": len(candidates),
            "candidate_identity_key": ["ticker", "isu_cd", "entry_signal_date"],
            "as_of": "entry_signal_date",
            "latest_quarter_only": True,
            "prior_quarter_fallback": False,
            "rule": {
                "minimum_current_operating_income_krw": OI_MIN_KRW,
                "if_prior_year_quarter_positive": "current / prior >= 1.01",
                "if_prior_year_quarter_zero_or_negative": "current >= 2B and positive",
                "unavailable": "fail closed; no entry",
            },
        })
        # CONTROL/TEST20 replay is independent per window and uses only PIT
        # signal evaluations. No completed CONTROL trades are post-filtered.
        outputs, replay_audit = run_replays(
            loader=loader,
            by_ticker=pit_by_ticker,
            candidates=candidates,
            evaluations=evaluated,
            resolved=resolved,
            calendar=calendar,
            score_contract=score_contract,
            stage_contract=stage_contract,
        )
    for window_id in WINDOW_IDS:
        window_dir = WINDOW_DIR[window_id]
        for group in ("CONTROL", "TEST20"):
            write_csv(window_dir / f"{group.lower()}_trade_ledger.csv", pd.DataFrame(outputs[window_id][group]))
        for key, value in replay_audit[window_id].items():
            if isinstance(value, Counter):
                replay_audit[window_id][key] = dict(value)
    comparisons, diagnostics, integrity = evaluate_comparison(outputs, candidates, evaluated, resolved)
    # Attach live replay attempt counts to the window diagnostics.
    diagnostics = attach_replay_attempt_counts(diagnostics, replay_audit)
    write_csv(OUTPUT / "window_comparison.csv", comparisons)
    write_csv(OUTPUT / "pit_and_retention_diagnostics.csv", diagnostics)
    write_json(OUTPUT / "replay_integrity.json", integrity)
    write_json(OUTPUT / "replay_attempt_audit.json", replay_audit)
    write_json(OUTPUT / "signal_discovery_rejections.json", discovery_rejections)

    parity_path = OUTPUT / "parity_v02_official_reproduction/final/closure_decision.json"
    parity = json.loads(parity_path.read_text(encoding="utf-8")) if parity_path.exists() else {"verdict": "MISSING"}
    if parity.get("verdict") != "ACCEPT":
        raise ResearchInputError(f"official V2 CONTROL reproduction did not ACCEPT: {parity}")
    manual_parity_path = OUTPUT / "parity_v02_official_reproduction/manual_control_reproduction.json"
    manual_parity = json.loads(manual_parity_path.read_text(encoding="utf-8")) if manual_parity_path.exists() else {}
    parity.update({key: manual_parity[key] for key in (
        "authority_trades", "production_trades", "authority_tickers", "production_tickers",
    ) if key in manual_parity})
    official_ledger_path = OUTPUT / "parity_v02_official_reproduction/production/production_fastcore_trades_20260814.csv"
    scope_audit = build_official_scope_audit(WINDOW_DIR["P1"] / "control_trade_ledger.csv", official_ledger_path, manual_parity)
    write_json(OUTPUT / "official_control_scope_audit.json", scope_audit)
    metadata = dict(input_metadata)
    metadata.update({
        "candidate_count": len(candidates),
        "candidate_ticker_count": int(candidates["ticker"].nunique()) if not candidates.empty else 0,
        "pit_status_counts": dict(status_counts),
        "source_pit_status_counts": dict(source_status_counts),
        "basis_currency_mismatch_normalized_to_unavailable": int(source_status_counts.get("BASIS_OR_CURRENCY_MISMATCH", 0)),
        "missing_market_data_ticker_count": len(data_gaps),
        "repository_v2_loader_count": len(pit_by_ticker) + int(candidates["ticker"].nunique()) if not candidates.empty else len(pit_by_ticker),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "replay_integrity": integrity,
        "pit_audit": pit_audit,
        "fallback_count": fallback_count,
        "official_control_scope_audit": scope_audit,
    })
    report = render_report(
        comparisons=comparisons,
        diagnostics=diagnostics,
        integrity=integrity,
        pit_audit=pit_audit,
        fallback_count=fallback_count,
        data_gaps=data_gaps,
        parity=parity,
        scope_audit=scope_audit,
        metadata=metadata,
    )
    (OUTPUT / "report.md").write_text(report + "\n", encoding="utf-8")
    summary = {
        "study_id": STUDY_ID,
        "status": "COMPLETE_WITH_RECORDED_LIMITATIONS" if data_gaps or status_counts.get(oi_pit.UNAVAILABLE, 0) else "COMPLETE",
        "official_v2_reproduction": parity,
        "official_control_scope_audit": scope_audit,
        "candidate_count": len(candidates),
        "candidate_ticker_count": int(candidates["ticker"].nunique()) if not candidates.empty else 0,
        "pit_status_counts": dict(status_counts),
        "source_pit_status_counts": dict(source_status_counts),
        "basis_currency_mismatch_normalized_to_unavailable": int(source_status_counts.get("BASIS_OR_CURRENCY_MISMATCH", 0)),
        "pit_audit": pit_audit,
        "prior_quarter_fallback_count": fallback_count,
        "market_data_gaps": len(data_gaps),
        "metrics": comparisons.to_dict("records"),
        "diagnostics": diagnostics.to_dict("records"),
        "integrity": integrity,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "push": False,
    }
    summary["severity_counts"] = severity_counts(
        integrity=integrity,
        pit_audit=pit_audit,
        fallback_count=fallback_count,
        data_gaps=data_gaps,
        parity=parity,
        scope_audit=scope_audit,
        metadata=metadata,
    )
    write_json(OUTPUT / "summary.json", summary)
    print(json.dumps({
        "status": summary["status"],
        "candidate_count": len(candidates),
        "pit_status_counts": dict(status_counts),
        "source_pit_status_counts": dict(source_status_counts),
        "windows": comparisons.to_dict("records"),
        "output": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False, default=str))
    return 0


def finalize_existing_outputs() -> int:
    """Rebuild report metadata from completed ledgers without rerunning replays."""
    summary_path = OUTPUT / "summary.json"
    if not summary_path.exists():
        raise ResearchInputError(f"completed summary is missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    comparisons = pd.read_csv(OUTPUT / "window_comparison.csv")
    diagnostics = pd.read_csv(OUTPUT / "pit_and_retention_diagnostics.csv")
    integrity = json.loads((OUTPUT / "replay_integrity.json").read_text(encoding="utf-8"))
    replay_audit = json.loads((OUTPUT / "replay_attempt_audit.json").read_text(encoding="utf-8"))
    diagnostics = attach_replay_attempt_counts(diagnostics, replay_audit)
    write_csv(OUTPUT / "pit_and_retention_diagnostics.csv", diagnostics)
    pit_artifact = json.loads((OUTPUT / "pit_audit.json").read_text(encoding="utf-8"))
    execution_metadata = json.loads((OUTPUT / "execution_metadata.json").read_text(encoding="utf-8"))
    data_availability_path = OUTPUT / "data_availability.csv"
    data_gaps = pd.read_csv(data_availability_path, dtype={"ticker": "string"}).to_dict("records") if data_availability_path.exists() else []
    parity_path = OUTPUT / "parity_v02_official_reproduction/final/closure_decision.json"
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    manual_parity_path = OUTPUT / "parity_v02_official_reproduction/manual_control_reproduction.json"
    manual_parity = json.loads(manual_parity_path.read_text(encoding="utf-8")) if manual_parity_path.exists() else {}
    parity.update({key: manual_parity[key] for key in (
        "authority_trades", "production_trades", "authority_tickers", "production_tickers",
    ) if key in manual_parity})
    official_ledger_path = OUTPUT / "parity_v02_official_reproduction/production/production_fastcore_trades_20260814.csv"
    scope_audit = build_official_scope_audit(WINDOW_DIR["P1"] / "control_trade_ledger.csv", official_ledger_path, manual_parity)
    pit_audit = pit_artifact["pit_integrity"]
    fallback_count = int(pit_artifact.get("fallback_count", 0))
    status_counts = summary.get("pit_status_counts", {})
    source_status_counts = summary.get("source_pit_status_counts", {})
    metadata = dict(execution_metadata)
    metadata.update({
        "candidate_count": int(summary.get("candidate_count", 0)),
        "candidate_ticker_count": int(summary.get("candidate_ticker_count", 0)),
        "pit_status_counts": status_counts,
        "source_pit_status_counts": source_status_counts,
        "missing_market_data_ticker_count": len(data_gaps),
        "official_control_scope_audit": scope_audit,
        "pit_audit": pit_audit,
        "fallback_count": fallback_count,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    })
    write_json(OUTPUT / "official_control_scope_audit.json", scope_audit)
    report = render_report(
        comparisons=comparisons,
        diagnostics=diagnostics,
        integrity=integrity,
        pit_audit=pit_audit,
        fallback_count=fallback_count,
        data_gaps=data_gaps,
        parity=parity,
        scope_audit=scope_audit,
        metadata=metadata,
    )
    (OUTPUT / "report.md").write_text(report + "\n", encoding="utf-8")
    summary.update({
        "official_v2_reproduction": parity,
        "official_control_scope_audit": scope_audit,
        "diagnostics": diagnostics.to_dict("records"),
        "severity_counts": severity_counts(
            integrity=integrity,
            pit_audit=pit_audit,
            fallback_count=fallback_count,
            data_gaps=data_gaps,
            parity=parity,
            scope_audit=scope_audit,
            metadata=metadata,
        ),
    })
    execution_metadata.update({
        "runner_sha256": metadata["runner_sha256"],
        "official_control_scope_audit": scope_audit,
    })
    write_json(OUTPUT / "execution_metadata.json", execution_metadata)
    write_json(summary_path, summary)
    print(json.dumps({"finalized": True, "severity_counts": summary["severity_counts"], "scope_audit": scope_audit}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--finalize-existing"]:
        raise SystemExit(finalize_existing_outputs())
    raise SystemExit(main())
