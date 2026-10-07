#!/usr/bin/env python3
"""Research-only P3-2 MA20/MA60 entry-close filter replay."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
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

OUT = Path(__file__).resolve().parent
CONTROL = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
PRIOR_DIAGNOSTIC = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma_entry_position_diagnostic_v01"
PRICE_ROOT = ROOT / "data/market/adjusted/stocks"
WORKERS = 10
PERIODS = {"MA20": 20, "MA60": 60}
CONTROL_TOKEN = "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_COMPLETE"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_CHECK_REQUIRED"
CURRENT_STAGE = "STARTUP"
CONTROL_FILES = (
    "control_strategy_trades.csv",
    "control_portfolio_events.csv",
    "control_daily_equity.csv",
    "control_pit_mcap_audit.csv",
    "summary.json",
)


class BacktestCheckRequired(RuntimeError):
    pass


def require(ok: bool, token: str) -> None:
    if not ok:
        raise BacktestCheckRequired(token)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_frozen_runner():
    path = CONTROL / "run_frozen_replay.py"
    spec = importlib.util.spec_from_file_location("frozen_p3_2_replay_for_ma_entry_filter", path)
    require(spec is not None and spec.loader is not None, "FROZEN_REPLAY_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def preflight(frozen: Any) -> tuple[dict[str, Any], Any, Any, pd.DataFrame]:
    attempt_one = {
        "initial_attempt_failure.json", "initial_attempt_preflight.json",
        "initial_attempt_summary.json", "initial_attempt_report.md",
    }
    allowed_before_run = {"run_monthly_ma_entry_filter_backtest.py", "__pycache__", "failure.json", "preflight.json", "summary.json", "report.md", *attempt_one}
    require(not any(path.name not in allowed_before_run for path in OUT.iterdir()), "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS")
    require(not any(path.name.startswith("attempt_02_") for path in OUT.iterdir()), "REFUSING_FURTHER_AUTOMATIC_RETRY")
    existing_attempt_one = {path.name for path in OUT.iterdir() if path.name in attempt_one}
    require(not existing_attempt_one or existing_attempt_one == attempt_one, "INCOMPLETE_PRIOR_ATTEMPT_AUDIT")
    prior_failure = OUT / "failure.json"
    if prior_failure.is_file():
        failure = json.loads(prior_failure.read_text(encoding="utf-8"))
        require(
            failure.get("final_token") == CHECK_TOKEN
            and failure.get("stage") == "CONTROL_SIGNAL_PARITY"
            and failure.get("candidate_replay_started") is False
            and failure.get("error_type") == "BacktestCheckRequired"
            and "CONTROL_REPOSITORY_V2_DATA_MISSING" in failure.get("error", ""),
            "REFUSING_TO_RETRY_NON_INITIALIZATION_FAILURE",
        )
    prior_summary = OUT / "summary.json"
    if prior_summary.is_file():
        summary = json.loads(prior_summary.read_text(encoding="utf-8"))
        require(
            summary.get("status") == "CHECK_REQUIRED"
            and summary.get("candidate_replay_started") is False
            and summary.get("failure", {}).get("stage") == "CONTROL_SIGNAL_PARITY",
            "REFUSING_TO_RETRY_AFTER_CANDIDATE_EVALUATION",
        )
        saved_preflight = OUT / "preflight.json"
        require(saved_preflight.is_file() and json.loads(saved_preflight.read_text(encoding="utf-8")).get("status") == "PASS", "INITIAL_FAILURE_PREFLIGHT_NOT_PASS")
    prior_path = PRIOR_DIAGNOSTIC / "preflight.json"
    require(prior_path.is_file(), "PRIOR_CONTROL_HASH_SNAPSHOT_MISSING")
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    require(prior.get("status") == "PASS", "PRIOR_FROZEN_CONTROL_PREFLIGHT_NOT_PASS")
    require(prior.get("control_final_token") == CONTROL_TOKEN, "PRIOR_CONTROL_TOKEN_MISMATCH")
    require(prior.get("latest_authority_dependency") is False, "PRIOR_AUTHORITY_USES_LATEST_ROLLING_DATA")
    require(prior.get("network_or_new_price_calls") == 0, "PRIOR_AUTHORITY_HAS_NETWORK_OR_PRICE_CALLS")

    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    require(control_summary.get("status") == "COMPLETE" and control_summary.get("final_token") == CONTROL_TOKEN, "FROZEN_CONTROL_NOT_COMPLETE")
    require(control_summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    require(control_summary.get("control_parity", {}).get("strategy", {}).get("pass") is True, "FROZEN_CONTROL_STRATEGY_PARITY_NOT_PASS")
    require(control_summary.get("control_parity", {}).get("portfolio", {}).get("pass") is True, "FROZEN_CONTROL_PORTFOLIO_PARITY_NOT_PASS")

    control_hashes: dict[str, str] = {}
    expected_hashes = prior.get("control_file_sha256", {})
    for name in CONTROL_FILES:
        path = CONTROL / name
        require(path.is_file(), f"CONTROL_FILE_MISSING:{name}")
        value = sha256(path)
        require(value == expected_hashes.get(name), f"CONTROL_HASH_DIFFERS_FROM_FROZEN_SNAPSHOT:{name}")
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
        require(committed == path.read_bytes(), f"CONTROL_FILE_DIFFERS_FROM_HEAD:{name}")
        control_hashes[name] = value

    provenance = frozen._validate_saved_provenance()
    run, gate, universe, authority = frozen._load_frozen_context()
    trades = pd.read_csv(CONTROL / "control_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    trades["ticker"] = trades["ticker"].astype(str).str.zfill(6)
    trades["pair_id"] = trades["pair_id"].astype(str)
    require(len(trades) == 405 and trades["pair_id"].is_unique, "FROZEN_CONTROL_TRADE_LEDGER_INVALID")
    require(not trades[["ticker", "entry_signal_date"]].duplicated().any(), "DUPLICATE_CONTROL_SIGNAL_KEY")
    require(len(universe.loc[universe["status"].eq("SURVIVOR_COMMON_IDENTITY")]) == 2539, "FROZEN_SURVIVOR_COUNT_NOT_2539")
    require(git_text("rev-parse", "HEAD") == git_text("rev-parse", "origin/main"), "START_HEAD_NOT_ORIGIN_MAIN")

    return {
        "status": "PASS",
        "control_final_token": CONTROL_TOKEN,
        "control_hashes": control_hashes,
        "previous_diagnostic_preflight_head": prior.get("current_head"),
        "current_head": git_text("rev-parse", "HEAD"),
        "origin_main": git_text("rev-parse", "origin/main"),
        "current_head_equals_origin_main": True,
        "source_provenance": provenance,
        "frozen_authority": authority,
        "frozen_control_trade_count": len(trades),
        "frozen_control_survivor_identity_count": 2539,
        "workers": WORKERS,
        "latest_rolling_authority_read": False,
        "network_calls": 0,
        "control_replayed": False,
        "price_source": "Existing local Repository V2 adjusted price partitions (Naver direct adjusted OHLC), read-only.",
    }, run, gate, trades


class PriceCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._frames: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
        self.audit: dict[str, dict[str, Any]] = {}

    def load(self, ticker: str) -> tuple[pd.DataFrame, pd.Series]:
        ticker = str(ticker).zfill(6)
        with self._lock:
            if ticker in self._frames:
                return self._frames[ticker]
            path = PRICE_ROOT / f"{ticker}.parquet"
            meta_path = PRICE_ROOT / f"{ticker}.meta.json"
            require(path.is_file() and meta_path.is_file(), f"ADJUSTED_PRICE_STORE_OR_METADATA_MISSING:{ticker}")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            file_hash = sha256(path)
            require(meta.get("ticker") == ticker, f"PRICE_METADATA_TICKER_MISMATCH:{ticker}")
            require(meta.get("content_sha256") == file_hash, f"PRICE_CONTENT_HASH_MISMATCH:{ticker}")
            require(meta.get("source_semantics") == "ADJUSTED_OHLC_ONLY", f"PRICE_SOURCE_SEMANTICS_INVALID:{ticker}")
            require(meta.get("authority_type") == "AUTHORITATIVE", f"PRICE_SOURCE_AUTHORITY_INVALID:{ticker}")
            frame = pd.read_parquet(path, columns=["date", "ticker", "open", "close"])
            frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
            frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
            require(frame["ticker"].eq(ticker).all(), f"PRICE_FILE_CONTAINS_OTHER_TICKER:{ticker}")
            require(not frame["date"].duplicated().any(), f"DUPLICATE_DAILY_PRICE_DATE:{ticker}")
            require(frame["date"].is_monotonic_increasing, f"DAILY_PRICE_DATES_NOT_SORTED:{ticker}")
            frame["open"] = pd.to_numeric(frame["open"], errors="raise")
            frame["close"] = pd.to_numeric(frame["close"], errors="raise")
            require(frame["open"].gt(0).all() and frame["close"].gt(0).all(), f"INVALID_ADJUSTED_OHLC:{ticker}")
            frame["month"] = frame["date"].dt.to_period("M")
            monthly = frame.groupby("month", sort=True).tail(1).set_index("month")["close"].sort_index()
            require(not monthly.index.duplicated().any(), f"DUPLICATE_MONTHLY_CLOSE:{ticker}")
            min_date = frame["date"].min().strftime("%Y-%m-%d")
            max_date = frame["date"].max().strftime("%Y-%m-%d")
            self.audit[ticker] = {
                "ticker": ticker,
                "relative_path": path.relative_to(ROOT).as_posix(),
                "sha256": file_hash,
                "metadata_relative_path": meta_path.relative_to(ROOT).as_posix(),
                "metadata_sha256": sha256(meta_path),
                "source_authority_id": meta.get("source_authority_id"),
                "source_semantics": meta.get("source_semantics"),
                "authority_type": meta.get("authority_type"),
                "authority_decision_sha256": meta.get("authority_decision_sha256"),
                "actual_date_min": min_date,
                "actual_date_max": max_date,
                "row_count": len(frame),
                "monthly_close_count": len(monthly),
                "metadata_row_count_matches": int(meta.get("row_count", -1)) == len(frame),
                "metadata_date_range_matches": meta.get("actual_date_min") == min_date and meta.get("actual_date_max") == max_date,
            }
            require(self.audit[ticker]["metadata_row_count_matches"] and self.audit[ticker]["metadata_date_range_matches"], f"PRICE_METADATA_COVERAGE_MISMATCH:{ticker}")
            self._frames[ticker] = (frame, monthly)
            return self._frames[ticker]

    def signal_features(self, ticker: str, daily: pd.DataFrame, signal_date: pd.Timestamp, periods: Mapping[str, int]) -> dict[str, Any]:
        ticker = str(ticker).zfill(6)
        signal_date = pd.Timestamp(signal_date).normalize()
        frame, monthly = self.load(ticker)
        day_rows = frame.loc[frame["date"].eq(signal_date), "close"]
        require(len(day_rows) == 1, f"SIGNAL_CLOSE_MISSING_OR_DUPLICATED_IN_ADJUSTED_STORE:{ticker}:{signal_date.date()}")
        close = float(day_rows.iloc[0])
        require(signal_date in daily.index, f"SIGNAL_CLOSE_MISSING_IN_REPOSITORY_V2:{ticker}:{signal_date.date()}")
        repository_close = float(daily.at[signal_date, "close"])
        require(math.isclose(close, repository_close, rel_tol=0, abs_tol=1e-9), f"SIGNAL_CLOSE_REPOSITORY_V2_PRICE_STORE_MISMATCH:{ticker}:{signal_date.date()}")
        cutoff = signal_date.to_period("M") - 1
        values: dict[str, Any] = {
            "signal_day_close": close,
            "signal_month": str(signal_date.to_period("M")),
            "ma_last_completed_month": str(cutoff),
            "price_source_partition_sha256": self.audit[ticker]["sha256"],
            "price_source_metadata_sha256": self.audit[ticker]["metadata_sha256"],
        }
        for name, size in periods.items():
            expected = pd.period_range(end=cutoff, periods=size, freq="M")
            window = monthly.reindex(expected)
            missing = [str(period) for period, value in window.items() if pd.isna(value)]
            available = not missing
            ma = float(window.mean()) if available else None
            require(ma is None or (ma > 0 and math.isfinite(ma)), f"INVALID_{name}:{ticker}:{signal_date.date()}")
            values[f"{name.lower()}_value"] = ma
            values[f"{name.lower()}_available"] = available
            values[f"{name.lower()}_pass"] = bool(available and close > ma)
            values[f"{name.lower()}_unavailable_reason"] = "" if available else (
                "INSUFFICIENT_HISTORY" if int((monthly.index <= cutoff).sum()) < size else "MISSING_MONTHLY_OBSERVATION"
            )
            values[f"{name.lower()}_window_start_month"] = str(expected[0])
            values[f"{name.lower()}_window_end_month"] = str(expected[-1])
            values[f"{name.lower()}_missing_months"] = json.dumps(missing, ensure_ascii=False)
            values[f"{name.lower()}_monthly_closes_used"] = json.dumps(
                [{"month": str(period), "adjusted_close": float(value)} for period, value in window.items() if pd.notna(value)],
                ensure_ascii=False,
            )
            require(str(expected[-1]) < str(signal_date.to_period("M")), f"CURRENT_MONTH_OR_FUTURE_USED_FOR_{name}:{ticker}:{signal_date.date()}")
        return values


def find_segment(run: Any, ticker: str, market: str, signal_date: pd.Timestamp):
    matches = [
        segment for segment in run.segments_by_ticker.get(str(ticker).zfill(6), ())
        if segment.market.upper() == str(market).upper()
        and segment.effective_from <= signal_date <= segment.effective_to
    ]
    require(len(matches) == 1, f"SIGNAL_IDENTITY_NOT_UNIQUE:{ticker}:{signal_date.date()}:{len(matches)}")
    return matches[0]


def frozen_control_signal_parity(run: Any, trades: pd.DataFrame, prices: PriceCache) -> tuple[pd.DataFrame, dict[str, Any]]:
    loader_type = type(run.loader)
    v2_rows: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for row in trades.itertuples(index=False):
        ticker = str(row.ticker).zfill(6)
        signal_date = pd.Timestamp(row.entry_signal_date).normalize()
        segment = find_segment(run, ticker, row.market, signal_date)
        require(segment.isu_cd.upper() == str(row.isu_cd).upper(), f"CONTROL_SIGNAL_IDENTITY_MISMATCH:{row.pair_id}")
        identity_key = segment.key
        if identity_key not in v2_rows:
            scoped_loader = loader_type(
                run.loader.repository,
                start=segment.effective_from,
                end=run.window.execution_support,
            )
            loaded = scoped_loader.load(ticker)
            require(loaded is not None and not loaded.empty, f"CONTROL_REPOSITORY_V2_DATA_MISSING:{ticker}:{identity_key}")
            v2_rows[identity_key] = loaded
        daily = v2_rows[identity_key]
        features = prices.signal_features(ticker, daily, signal_date, PERIODS)
        execution_date = pd.Timestamp(row.entry_execution_date).normalize()
        store_frame, _ = prices.load(ticker)
        open_rows = store_frame.loc[store_frame["date"].eq(execution_date), "open"]
        require(len(open_rows) == 1, f"CONTROL_ENTRY_OPEN_MISSING_OR_DUPLICATED:{row.pair_id}")
        store_open = float(open_rows.iloc[0])
        ledger_open = float(row.entry_open)
        require(math.isclose(store_open, ledger_open, rel_tol=0, abs_tol=1e-9), f"CONTROL_ENTRY_OPEN_PRICE_MISMATCH:{row.pair_id}")
        repository_open = float(daily.at[execution_date, "open"])
        require(math.isclose(repository_open, ledger_open, rel_tol=0, abs_tol=1e-9), f"CONTROL_ENTRY_OPEN_REPOSITORY_V2_MISMATCH:{row.pair_id}")
        item = {
            "pair_id": row.pair_id,
            "ticker": ticker,
            "isu_cd": row.isu_cd,
            "market": row.market,
            "entry_signal_date": signal_date.strftime("%Y-%m-%d"),
            "entry_execution_date": execution_date.strftime("%Y-%m-%d"),
            "signal_day_close": features["signal_day_close"],
            "entry_open": ledger_open,
            "overnight_gap_pct": (ledger_open / features["signal_day_close"] - 1.0) * 100.0,
            "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
            "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
        }
        for name in PERIODS:
            prefix = name.lower()
            ma = features[f"{prefix}_value"]
            signal_status = "UNAVAILABLE" if ma is None else ("ABOVE" if features["signal_day_close"] > ma else "AT_OR_BELOW")
            open_status = "UNAVAILABLE" if ma is None else ("ABOVE" if ledger_open > ma else "AT_OR_BELOW")
            comparable = ma is not None
            item.update({
                f"{prefix}_value": ma,
                f"{prefix}_last_completed_month": features["ma_last_completed_month"],
                f"{prefix}_signal_close_class": signal_status,
                f"{prefix}_entry_open_class": open_status,
                f"{prefix}_classification_comparable": comparable,
                f"{prefix}_classification_same": signal_status == open_status,
                f"{prefix}_overnight_gap_flip": bool(comparable and signal_status != open_status),
                f"{prefix}_above_to_at_or_below": bool(open_status == "ABOVE" and signal_status == "AT_OR_BELOW"),
                f"{prefix}_at_or_below_to_above": bool(open_status == "AT_OR_BELOW" and signal_status == "ABOVE"),
                f"{prefix}_unavailable_reason": features[f"{prefix}_unavailable_reason"],
            })
        rows.append(item)
    parity = pd.DataFrame(rows).sort_values(["ticker", "entry_signal_date"], kind="mergesort").reset_index(drop=True)
    require(len(parity) == 405 and parity["pair_id"].is_unique, "CONTROL_SIGNAL_PARITY_ROWS_INVALID")
    summary: dict[str, Any] = {"control_trade_rows": len(parity), "entry_open_price_mismatches": 0, "signal_close_repo_v2_price_mismatches": 0}
    for name in PERIODS:
        p = name.lower()
        comp = parity[f"{p}_classification_comparable"]
        same = parity[f"{p}_classification_same"]
        flips = parity[f"{p}_overnight_gap_flip"]
        summary[name] = {
            "same_count_including_unavailable": int(same.sum()),
            "same_rate_including_unavailable_pct": float(same.mean() * 100),
            "comparable_count": int(comp.sum()),
            "unavailable_count": int((~comp).sum()),
            "same_count_comparable": int((same & comp).sum()),
            "same_rate_comparable_pct": float((same & comp).sum() * 100 / comp.sum()) if comp.any() else None,
            "overnight_gap_flip_count": int(flips.sum()),
            "overnight_gap_flip_rate_comparable_pct": float(flips.sum() * 100 / comp.sum()) if comp.any() else None,
            "above_to_at_or_below_count": int(parity[f"{p}_above_to_at_or_below"].sum()),
            "at_or_below_to_above_count": int(parity[f"{p}_at_or_below_to_above"].sum()),
        }
    return parity, summary


def candidate_replay(run: Any, gate: Any, prices: PriceCache, period_name: str, size: int) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, float]:
    from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2
    import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy

    policy = period_name.lower()
    original_simulator = v2.simulate_ticker_core_v02_reentry
    audit_rows: list[dict[str, Any]] = []
    audit_lock = threading.Lock()

    def selected_simulator(*args: Any, **kwargs: Any):
        ticker = str(kwargs["ticker"]).zfill(6)
        market = str(kwargs["market"])
        daily = kwargs["daily"]
        pit_filter = kwargs.get("entry_signal_filter")

        def candidate_filter(signal_date: pd.Timestamp, result: Mapping[str, Any]) -> bool:
            day = pd.Timestamp(signal_date).normalize()
            segment = find_segment(run, ticker, market, day)
            pit_pass = bool(pit_filter(day, result)) if pit_filter is not None else True
            features = prices.signal_features(ticker, daily, day, {period_name: size})
            ma_pass = bool(features[f"{policy}_pass"])
            accepted = bool(pit_pass and ma_pass)
            later_sessions = daily.index[(daily.index > day) & (daily.index <= pd.Timestamp(kwargs.get("execution_support_date")).normalize())]
            next_session = pd.Timestamp(later_sessions[0]).normalize() if len(later_sessions) else None
            entry_cutoff = pd.Timestamp(kwargs.get("entry_execution_cutoff_date")).normalize()
            entry_executable = next_session is not None and next_session <= entry_cutoff
            audit = {
                "ticker": ticker,
                "isu_cd": segment.isu_cd,
                "market": segment.market,
                "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                "identity_key": segment.key,
                "entry_signal_date": day.strftime("%Y-%m-%d"),
                "candidate": period_name,
                "raw_v2_eligible_signal": True,
                "pit_mcap_pass": pit_pass,
                "signal_day_close": features["signal_day_close"],
                "signal_month": features["signal_month"],
                "ma_last_completed_month": features["ma_last_completed_month"],
                "monthly_ma": features[f"{policy}_value"],
                "ma_available": features[f"{policy}_available"],
                "ma_unavailable_reason": features[f"{policy}_unavailable_reason"],
                "ma_filter_pass": ma_pass,
                "candidate_signal_accepted": accepted,
                "next_local_session_date": next_session.strftime("%Y-%m-%d") if next_session is not None else None,
                "entry_execution_cutoff_date": entry_cutoff.strftime("%Y-%m-%d"),
                "entry_executable_within_cutoff": entry_executable,
                "filter_decision": "ACCEPT" if accepted else ("PIT_REJECT" if not pit_pass else "MA_BLOCK"),
                "monthly_window_start": features[f"{policy}_window_start_month"],
                "monthly_window_end": features[f"{policy}_window_end_month"],
                "monthly_missing_months": features[f"{policy}_missing_months"],
                "monthly_closes_used": features[f"{policy}_monthly_closes_used"],
                "price_source_partition_sha256": features["price_source_partition_sha256"],
                "price_source_metadata_sha256": features["price_source_metadata_sha256"],
            }
            with audit_lock:
                audit_rows.append(audit)
            return accepted

        kwargs["entry_signal_filter"] = candidate_filter
        return original_simulator(*args, **kwargs)

    v2.simulate_ticker_core_v02_reentry = selected_simulator
    errors: list[str] = []
    outcomes: list[dict[str, Any]] = []
    started = time.perf_counter()
    tickers = sorted(run.segments_by_ticker)
    try:
        def process(ticker: str):
            outcome = strategy._process_ticker(ticker, run)
            outcome["worker_thread"] = threading.current_thread().name
            return outcome

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix=f"ma-filter-{policy}") as pool:
            futures = {pool.submit(process, ticker): ticker for ticker in tickers}
            for completed, future in enumerate(as_completed(futures), start=1):
                ticker = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
                if completed % 50 == 0 or completed == len(tickers):
                    total = sum(len(item.get("control_rows", ())) for item in outcomes)
                    print(f"{period_name} progress {completed}/{len(tickers)} trades={total} mcap_audits={len(gate.audit_frame())} errors={len(errors)} elapsed={time.perf_counter()-started:.1f}s", flush=True)
    finally:
        v2.simulate_ticker_core_v02_reentry = original_simulator
    require(not errors, f"{period_name}_WORKER_ERRORS:" + json.dumps(errors[:10], ensure_ascii=False))

    records = pd.DataFrame([row for outcome in outcomes for row in outcome.get("control_rows", ())])
    if records.empty:
        records = pd.DataFrame()
    else:
        records = records.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    audit_frame = pd.DataFrame(audit_rows)
    if audit_frame.empty:
        audit_frame = pd.DataFrame(columns=["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "candidate_signal_accepted"])
    audit_key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date"]
    if not records.empty:
        records["ticker"] = records["ticker"].astype(str).str.zfill(6)
        audit_frame["ticker"] = audit_frame["ticker"].astype(str).str.zfill(6)
        candidate_trade_keys = records[audit_key].copy()
        pass_keys = audit_frame.loc[audit_frame["candidate_signal_accepted"] & audit_frame["entry_executable_within_cutoff"], audit_key].copy()
        require(not pass_keys.duplicated().any(), f"{period_name}_DUPLICATE_ACCEPTED_SIGNAL_AUDIT")
        require(not candidate_trade_keys.duplicated().any(), f"{period_name}_DUPLICATE_CANDIDATE_TRADE_SIGNAL")
        left = candidate_trade_keys.sort_values(audit_key).reset_index(drop=True)
        right = pass_keys.sort_values(audit_key).reset_index(drop=True)
        require(left.equals(right), f"{period_name}_ACCEPTED_SIGNAL_TO_TRADE_LEDGER_MISMATCH")
        joined = records.merge(audit_frame[audit_key + ["signal_day_close", "monthly_ma", "ma_filter_pass", "candidate_signal_accepted", "ma_last_completed_month"]], on=audit_key, how="left", validate="one_to_one")
        require(joined["candidate_signal_accepted"].fillna(False).all(), f"{period_name}_TRADE_WITHOUT_MA_PASS")
        require(joined["ma_filter_pass"].fillna(False).all(), f"{period_name}_MA_FILTER_TRADE_LEAK")
        records = joined
    return records, {"outcomes": outcomes, "worker_errors": errors, "elapsed_seconds": time.perf_counter() - started}, audit_frame, time.perf_counter() - started


def strategy_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trade_count": 0, "realized_count": 0, "open_count": 0}
    status = frame.get("trade_status", pd.Series(index=frame.index, dtype=object)).fillna("").astype(str)
    realized = status.eq("REALIZED")
    terminal = pd.to_numeric(frame.get("terminal_return", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    realized_terminal = terminal.loc[realized].dropna()
    mfe = pd.to_numeric(frame.get("mfe", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    mae = pd.to_numeric(frame.get("mae", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    holding = pd.to_numeric(frame.get("holding_days", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    exit_type = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("").astype(str)
    progressed_col = frame.get("first_progressed_effective_trading_date", frame.get("first_progressed_date", pd.Series(index=frame.index, dtype=object)))
    progressed = progressed_col.notna() & progressed_col.astype(str).ne("")
    out: dict[str, Any] = {
        "trade_count": len(frame),
        "realized_count": int(realized.sum()),
        "open_count": int(status.str.startswith("OPEN").sum()),
        "realized_win_rate_pct": float(realized_terminal.gt(0).mean() * 100) if len(realized_terminal) else None,
        "terminal_positive_rate_pct": float(terminal.dropna().gt(0).mean() * 100) if terminal.notna().any() else None,
        "average_terminal_return_pct": float(terminal.mean()) if terminal.notna().any() else None,
        "median_terminal_return_pct": float(terminal.median()) if terminal.notna().any() else None,
        "average_realized_return_pct": float(realized_terminal.mean()) if len(realized_terminal) else None,
        "median_realized_return_pct": float(realized_terminal.median()) if len(realized_terminal) else None,
        "average_holding_trading_days": float(holding.mean()) if holding.notna().any() else None,
        "median_holding_trading_days": float(holding.median()) if holding.notna().any() else None,
        "progressed_count": int(progressed.sum()),
        "progressed_rate_pct": float(progressed.mean() * 100) if len(frame) else None,
        "loss_guard_exit_count": int(exit_type.str.contains("LOSS_GUARD", regex=False).sum()),
        "loss_guard_rate_pct": float(exit_type.str.contains("LOSS_GUARD", regex=False).mean() * 100) if len(frame) else None,
        "exit3_count": int(exit_type.str.startswith("EXIT3").sum()),
        "exit4_count": int(exit_type.str.startswith("EXIT4").sum()),
    }
    for threshold in (20, 50, 100):
        out[f"terminal_ge_pos_{threshold}_count"] = int(terminal.ge(threshold).sum())
        out[f"mfe_ge_pos_{threshold}_count"] = int(mfe.ge(threshold).sum())
    for threshold in (20, 30, 40):
        out[f"terminal_le_neg_{threshold}_count"] = int(terminal.le(-threshold).sum())
        out[f"mae_le_neg_{threshold}_count"] = int(mae.le(-threshold).sum())
    return out


def blocked_signal_analysis(control: pd.DataFrame, parity: pd.DataFrame, ma_name: str, candidate_trades: pd.DataFrame, audit: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    p = ma_name.lower()
    blocked = parity.loc[parity[f"{p}_signal_close_class"].ne("ABOVE")].copy()
    blocked_ids = set(blocked["pair_id"].astype(str))
    blocked_trades = control.loc[control["pair_id"].astype(str).isin(blocked_ids)].copy()
    blocked_metrics = strategy_metrics(blocked_trades)
    blocked_metrics["candidate"] = ma_name
    blocked_metrics["blocked_control_signal_count"] = len(blocked)

    key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date"]
    control_keys = set(map(tuple, control[key].astype(str).itertuples(index=False, name=None)))
    candidate_only = candidate_trades.loc[
        [tuple(map(str, row)) not in control_keys for row in candidate_trades[key].itertuples(index=False, name=None)]
    ].copy() if not candidate_trades.empty else pd.DataFrame(columns=candidate_trades.columns)
    candidate_only_metrics = strategy_metrics(candidate_only)
    candidate_only_metrics["candidate"] = ma_name
    # Explain each newly possible later entry by the latest earlier CONTROL signal blocked in the same PIT identity.
    blocked_key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    mapping: list[dict[str, Any]] = []
    if not candidate_only.empty:
        prior = blocked[[*blocked_key, "entry_signal_date", "pair_id"]].copy()
        prior["entry_signal_date"] = pd.to_datetime(prior["entry_signal_date"])
        for row in candidate_only.itertuples(index=False):
            day = pd.Timestamp(row.entry_signal_date)
            match = prior.loc[
                prior[blocked_key].astype(str).eq(pd.Series({k: str(getattr(row, k)) for k in blocked_key})).all(axis=1)
                & prior["entry_signal_date"].lt(day)
            ].sort_values("entry_signal_date")
            mapping.append({
                "candidate": ma_name,
                "candidate_pair_id": row.pair_id,
                "ticker": row.ticker,
                "entry_signal_date": row.entry_signal_date,
                "prior_blocked_control_pair_id": match.iloc[-1]["pair_id"] if not match.empty else None,
                "prior_blocked_control_signal_date": match.iloc[-1]["entry_signal_date"].strftime("%Y-%m-%d") if not match.empty else None,
                "linked_to_prior_control_block": not match.empty,
            })
    followup_map = pd.DataFrame(mapping)
    later_accepts_by_identity: dict[tuple[str, ...], set[str]] = {}
    audit_key = [*blocked_key, "entry_signal_date"]
    if not audit.empty:
        accepted = audit.loc[
            audit["candidate_signal_accepted"].fillna(False)
            & audit["entry_executable_within_cutoff"].fillna(False)
        ]
        for row in accepted[audit_key].itertuples(index=False, name=None):
            ident = tuple(map(str, row[:-1]))
            later_accepts_by_identity.setdefault(ident, set()).add(str(row[-1]))
    blocked_followed = 0
    distinct_followup_signal_keys: set[tuple[str, ...]] = set()
    for row in blocked.itertuples(index=False):
        ident = tuple(str(getattr(row, key_name)) for key_name in blocked_key)
        later = sorted(day for day in later_accepts_by_identity.get(ident, set()) if day > str(row.entry_signal_date))
        if later:
            blocked_followed += 1
            distinct_followup_signal_keys.add((*ident, later[0]))
    result = {
        "candidate": ma_name,
        "raw_v2_eligible_signal_count": int(len(audit)),
        "pit_mcap_rejected_signal_count": int((~audit["pit_mcap_pass"].fillna(False)).sum()) if not audit.empty else 0,
        "ma_filter_blocked_pit_qualified_signal_count": int((audit["pit_mcap_pass"].fillna(False) & ~audit["ma_filter_pass"].fillna(False)).sum()) if not audit.empty else 0,
        "ma_filter_passed_pit_qualified_signal_count": int((audit["pit_mcap_pass"].fillna(False) & audit["ma_filter_pass"].fillna(False)).sum()) if not audit.empty else 0,
        "accepted_signal_without_executable_entry_count": int((audit["candidate_signal_accepted"].fillna(False) & ~audit["entry_executable_within_cutoff"].fillna(False)).sum()) if not audit.empty else 0,
        "ma_unavailable_pit_qualified_signal_count": int((audit["pit_mcap_pass"].fillna(False) & ~audit["ma_available"].fillna(False)).sum()) if not audit.empty else 0,
        "blocked_control_signal_count": len(blocked),
        "blocked_control_signal_with_later_accepted_signal_count": blocked_followed,
        "distinct_later_accepted_signal_count_after_block": len(distinct_followup_signal_keys),
        "blocked_control_trade_metrics": blocked_metrics,
        "candidate_only_followup_trade_metrics": candidate_only_metrics,
        "candidate_only_trade_count_linked_to_prior_block": int(followup_map["linked_to_prior_control_block"].sum()) if not followup_map.empty else 0,
        "candidate_only_trade_count_without_prior_block_link": int((~followup_map["linked_to_prior_control_block"]).sum()) if not followup_map.empty else len(candidate_only),
    }
    return result, blocked_trades, pd.concat([followup_map, pd.DataFrame([{"candidate": ma_name, "row_type": "BLOCKED_CONTROL_SUMMARY", **blocked_metrics}, {"candidate": ma_name, "row_type": "CANDIDATE_ONLY_FOLLOWUP_SUMMARY", **candidate_only_metrics}])], ignore_index=True, sort=False)


def trade_key_frame(records: pd.DataFrame) -> pd.DataFrame:
    key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date"]
    frame = records[key].copy()
    for column in key:
        frame[column] = frame[column].fillna("").astype(str)
    return frame.drop_duplicates()


def actual_realized_returns(events: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    entries = events.loc[events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED")].copy()
    exits = events.loc[events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")].copy()
    entry_by_pair = entries.set_index("pair_id", drop=False)
    record_by_pair = records.set_index("pair_id", drop=False)
    rows: list[dict[str, Any]] = []
    for event in exits.itertuples(index=False):
        pair_id = str(event.pair_id)
        if pair_id not in entry_by_pair.index or pair_id not in record_by_pair.index:
            continue
        entry = entry_by_pair.loc[pair_id]
        rec = record_by_pair.loc[pair_id]
        buy_cost = float(entry["notional"]) + float(entry["commission"])
        proceeds = float(event.notional) - float(event.commission) - float(event.sell_tax)
        if buy_cost <= 0:
            continue
        ret = (proceeds / buy_cost - 1.0) * 100.0
        rows.append({
            "ticker": str(rec["ticker"]).zfill(6),
            "isu_cd": str(rec["isu_cd"]),
            "market": str(rec["market"]),
            "identity_effective_from": str(rec["identity_effective_from"]),
            "identity_effective_to": str(rec["identity_effective_to"]),
            "entry_signal_date": str(rec["entry_signal_date"]),
            "entry_execution_date": str(rec["entry_execution_date"]),
            "pair_id": pair_id,
            "net_realized_return_pct": ret,
        })
    return pd.DataFrame(rows)


def opportunity_analysis(control_events: pd.DataFrame, control: pd.DataFrame, candidate_events: pd.DataFrame, candidate: pd.DataFrame, candidate_name: str, control_portfolio: Mapping[str, Any], candidate_portfolio: Mapping[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    control_exec = control_events.loc[control_events["event_type"].eq("ENTRY") & control_events["event_status"].eq("EXECUTED")].copy()
    candidate_exec = candidate_events.loc[candidate_events["event_type"].eq("ENTRY") & candidate_events["event_status"].eq("EXECUTED")].copy()
    control_actual_keys = set(map(tuple, trade_key_frame(control).loc[control["pair_id"].isin(control_exec["pair_id"])].itertuples(index=False, name=None)))
    candidate_actual_keys = set(map(tuple, trade_key_frame(candidate).loc[candidate["pair_id"].isin(candidate_exec["pair_id"])].itertuples(index=False, name=None)))
    common = control_actual_keys & candidate_actual_keys
    only_control = control_actual_keys - candidate_actual_keys
    only_candidate = candidate_actual_keys - control_actual_keys
    control_returns = actual_realized_returns(control_events, control)
    candidate_returns = actual_realized_returns(candidate_events, candidate)
    ret_key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date"]
    winner_stats: dict[str, Any] = {}
    winner_rows: list[dict[str, Any]] = []
    for threshold in (50, 100):
        c_winners = set(map(tuple, control_returns.loc[control_returns["net_realized_return_pct"].ge(threshold), ret_key].astype(str).itertuples(index=False, name=None)))
        a_winners = set(map(tuple, candidate_returns.loc[candidate_returns["net_realized_return_pct"].ge(threshold), ret_key].astype(str).itertuples(index=False, name=None)))
        lost = c_winners - a_winners
        gained = a_winners - c_winners
        winner_stats[f"net_realized_ge_pos_{threshold}"] = {
            "control_count": len(c_winners),
            "candidate_count": len(a_winners),
            "lost_count": len(lost),
            "gained_count": len(gained),
            "net_count_change": len(a_winners) - len(c_winners),
        }
        winner_rows.extend([{"candidate": candidate_name, "threshold_pct": threshold, "change_type": "CONTROL_WINNER_LOST", "trade_key": json.dumps(key)} for key in sorted(lost)])
        winner_rows.extend([{"candidate": candidate_name, "threshold_pct": threshold, "change_type": "CANDIDATE_WINNER_GAINED", "trade_key": json.dumps(key)} for key in sorted(gained)])
    cash_skips_control = int(control_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE").sum())
    cash_skips_candidate = int(candidate_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE").sum())
    summary = {
        "candidate": candidate_name,
        "control_actual_entry_count": len(control_actual_keys),
        "candidate_actual_entry_count": len(candidate_actual_keys),
        "common_actual_entry_count": len(common),
        "control_only_actual_entry_count": len(only_control),
        "candidate_only_actual_entry_count": len(only_candidate),
        "control_cash_shortage_skips": cash_skips_control,
        "candidate_cash_shortage_skips": cash_skips_candidate,
        "cash_shortage_skip_change": cash_skips_candidate - cash_skips_control,
        "control_realized_actual_trade_count": len(control_returns),
        "candidate_realized_actual_trade_count": len(candidate_returns),
        "realized_winner_change": winner_stats,
        "actual_trade_key_scope": "ticker + PIT identity interval + signal date + execution date; full portfolio uses each candidate's own global cash path.",
    }
    return summary, pd.DataFrame(winner_rows)


def render_report(summary: Mapping[str, Any]) -> str:
    authority = summary["preflight"]["frozen_authority"]
    parity = summary["signal_close_vs_entry_open_parity"]
    trade = summary["strategy_metrics"]
    port = summary["portfolio_metrics"]
    gate = summary["success_gates"]
    severity = summary["severity"]
    def rows_for(keys: Sequence[str], values: Mapping[str, Any], names: Mapping[str, str] | None = None) -> str:
        names = names or {}
        return "\n".join(f"| {names.get(key, key)} | {values.get(key)} |" for key in keys)
    trade_keys = ["trade_count", "realized_count", "open_count", "realized_win_rate_pct", "terminal_positive_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct", "average_realized_return_pct", "median_realized_return_pct", "average_holding_trading_days", "median_holding_trading_days", "progressed_count", "progressed_rate_pct", "loss_guard_exit_count", "loss_guard_rate_pct", "exit3_count", "exit4_count", "terminal_ge_pos_20_count", "terminal_ge_pos_50_count", "terminal_ge_pos_100_count", "mfe_ge_pos_20_count", "mfe_ge_pos_50_count", "mfe_ge_pos_100_count", "terminal_le_neg_20_count", "terminal_le_neg_30_count", "terminal_le_neg_40_count", "mae_le_neg_20_count", "mae_le_neg_30_count", "mae_le_neg_40_count"]
    portfolio_keys = ["final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count", "realized_trade_count", "open_at_effective_cutoff_count", "cash_shortage_skipped_entries", "average_concurrent_positions", "maximum_concurrent_positions", "average_capital_utilization_pct", "average_cash_ratio_pct", "turnover_multiple", "average_holding_trading_days", "median_holding_trading_days", "realized_return_ge_pos_50_count", "realized_return_ge_pos_100_count", "realized_return_le_neg_30_count", "realized_return_le_neg_40_count", "realized_return_le_neg_50_count", "realized_return_le_neg_60_count", "cash_conservation_pass", "unresolved_count"]
    lines = [
        "# P3-2 월간 MA20 / MA60 신호 종가 진입 필터 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
    ]
    lines.extend(f"| {level} | {count} | {content} |" for level, count, content in severity)
    lines += [
        "",
        f"## 1. 최종 토큰\n\n`{summary['final_token']}`",
        "",
        "## 2. Authority / PIT",
        "",
        f"- Frozen CONTROL 405건을 재사용했고 CONTROL replay는 다시 돌리지 않았어. 저장 CONTROL parity, 파일 SHA-256, 현재 HEAD blob, frozen P3-2 source/PIT/calendar 검증은 모두 PASS야.",
        f"- 기간 2022-01-03~2026-08-31, execution support 2026-09-01, survivor identity {authority.get('survivor_identity_count')}개, worker {summary['preflight']['workers']}개.",
        "- 이전 rolling authority를 읽지 않았고 네트워크/API/신규 가격 수집은 0회야. 공식 전략 파일과 production 경로는 수정하지 않았어.",
        "",
        "## 3. 신호 종가 vs 다음 날 시가 분류 일치",
        "",
        "두 가격 모두 `entry_signal_date` 직전 확정 월봉 MA와 비교했어. 비교 가능한 거래만 분모로 한 동일 분류율과 전체 405건 분류율을 함께 표시해.",
        "",
        "| MA | comparable | unavailable | same | same rate (comparable) | same rate (405) | gap flip | Above→At/Below | At/Below→Above |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in PERIODS:
        p = parity[name]
        lines.append(f"| {name} | {p['comparable_count']} | {p['unavailable_count']} | {p['same_count_comparable']} | {p['same_rate_comparable_pct']:.2f}% | {p['same_rate_including_unavailable_pct']:.2f}% | {p['overnight_gap_flip_count']} | {p['above_to_at_or_below_count']} | {p['at_or_below_to_above_count']} |")
    lines += [
        "",
        "## 4. Candidate 규칙",
        "",
        "- MA20: 기존 V2 eligible 신호에서 signal-day completed close가 signal 월 직전 확정월까지의 연속 20개 월봉 adjusted close 평균보다 클 때 통과.",
        "- MA60: 같은 기준으로 연속 60개 월봉 평균보다 클 때 통과.",
        "- 이력이 부족하거나 누락된 월봉이 있으면 해당 신호는 통과하지 않고 unavailable로 기록했어. 필터 통과 후 체결은 기존 next local trading day open이야.",
        "- 기존 PIT 시총 gate가 먼저 그대로 평가되고 MA gate가 뒤따라. 차단은 포지션·cooldown·가상 exit를 만들지 않고 다음 eligible signal로 진행해.",
        "",
        "## 5. 전략 성과",
        "",
        "| 지표 | CONTROL | MA20 | MA60 |",
        "|---|---:|---:|---:|",
    ]
    for key in trade_keys:
        lines.append(f"| {key} | {summary['strategy_metrics']['CONTROL'].get(key)} | {summary['strategy_metrics'].get('MA20', {}).get(key)} | {summary['strategy_metrics'].get('MA60', {}).get(key)} |")
    lines += [
        "",
        "## 6. PROGRESSED / Loss Guard / MFE / MAE",
        "",
        "상세 건수는 전략 성과 표에 포함했어. terminal은 cutoff 평가를 포함하고 realized return은 실현 거래에 한정했어.",
        "",
        "## 7. 현실 포트폴리오",
        "",
        "| 지표 | CONTROL | MA20 | MA60 |",
        "|---|---:|---:|---:|",
    ]
    for key in portfolio_keys:
        lines.append(f"| {key} | {summary['portfolio_metrics']['CONTROL'].get(key)} | {summary['portfolio_metrics'].get('MA20', {}).get(key)} | {summary['portfolio_metrics'].get('MA60', {}).get(key)} |")
    lines += [
        "",
        "## 8. 차단 거래 / 신규 후속 거래",
        "",
        "| 후보 | CONTROL 신호 차단 | 실현 승률 | 평균 terminal | 중앙 terminal | Loss Guard | PROGRESSED | terminal +50 / +100 | MFE +50 / +100 | MAE -30 / -40 | 새 후속 거래 | 차단 후 나중 accepted 신호가 있었던 차단 수 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in PERIODS:
        item = summary['blocked_signal_analysis'][name]
        m = item['blocked_control_trade_metrics']
        n = item['candidate_only_followup_trade_metrics']
        lines.append(f"| {name} | {item['blocked_control_signal_count']} | {m.get('realized_win_rate_pct')}% | {m.get('average_terminal_return_pct')}% | {m.get('median_terminal_return_pct')}% | {m.get('loss_guard_exit_count')} ({m.get('loss_guard_rate_pct')}%) | {m.get('progressed_count')} ({m.get('progressed_rate_pct')}%) | {m.get('terminal_ge_pos_50_count')} / {m.get('terminal_ge_pos_100_count')} | {m.get('mfe_ge_pos_50_count')} / {m.get('mfe_ge_pos_100_count')} | {m.get('mae_le_neg_30_count')} / {m.get('mae_le_neg_40_count')} | {n.get('trade_count')} | {item['blocked_control_signal_with_later_accepted_signal_count']} |")
    lines.append("")
    lines.append("새 후속 거래별 연결 정보는 `filter_blocked_signal_analysis.csv`에 있고, Control의 앞선 차단 신호와 같은 PIT identity 안에서 후속 거래를 연결했어.")
    lines += [
        "",
        "## 9. Portfolio opportunity cost",
        "",
        "| 후보 | CONTROL-only actual entries | Candidate-only actual entries | common actual entries | cash skip CONTROL→후보 | +50 winners lost/gained/net | +100 winners lost/gained/net |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in PERIODS:
        item = summary['opportunity_cost'][name]
        w50 = item['realized_winner_change']['net_realized_ge_pos_50']
        w100 = item['realized_winner_change']['net_realized_ge_pos_100']
        lines.append(f"| {name} | {item['control_only_actual_entry_count']} | {item['candidate_only_actual_entry_count']} | {item['common_actual_entry_count']} | {item['control_cash_shortage_skips']}→{item['candidate_cash_shortage_skips']} ({item['cash_shortage_skip_change']:+}) | {w50['lost_count']} / {w50['gained_count']} / {w50['net_count_change']:+} | {w100['lost_count']} / {w100['gained_count']} / {w100['net_count_change']:+} |")
    lines += [
        "",
        "실제 체결 키는 종목·PIT identity·신호일·체결일로 비교했어. 포트폴리오 재생은 각 정책별 global cash path를 그대로 사용했어.",
        "",
        "## 10. 성공 Gate",
        "",
        "| 기준 | MA20 | MA60 |",
        "|---|---|---|",
    ]
    for key, label in [("realized_win_rate_ge_50_pct", "실현 승률 ≥ 50%"), ("median_terminal_ge_1_pct", "중앙 terminal ≥ +1%"), ("average_terminal_above_control", "평균 terminal > CONTROL"), ("portfolio_mdd_above_neg_30_pct", "portfolio MDD > -30%")]:
        lines.append(f"| {label} | {gate['MA20'][key]} | {gate['MA60'][key]} |")
    lines += [
        f"| 전체 gate 통과 | {gate['MA20']['all_pass']} | {gate['MA60']['all_pass']} |",
        "",
        "final equity / CAGR / cash shortage / winner 수 / turnover·utilization 비교는 위 현실 포트폴리오 표와 기계 판독용 `summary.json`에 있어.",
        "",
        "## 11. 후속 5-window 검증 추천",
        "",
        f"{summary['five_window_recommendation']}",
        "",
        "P3-2 단일 구간 결과만으로 공식 전략 승격은 하지 않았어.",
        "",
        "## 12. 테스트 / integrity",
        "",
        f"- Check 결과: `{json.dumps(summary['integrity_checks'], ensure_ascii=False, sort_keys=True)}`",
        "- candidate 각 worker 수 10, raw eligible signals = PIT rejected + PIT-qualified MA blocked + PIT-qualified MA passed로 reconciled.",
        "- accepted signals와 후보 거래 원장을 identity/signal-date 기준으로 one-to-one 대조했어.",
        "- 현금 보존, unresolved positions, daily equity row count 1,140개를 후보별 확인했어.",
        "- MA 입력 경로는 signal-day close만 사용해. `entry_open`은 진입 필터에 전달되지 않아.",
        "",
        "## 13. Git commit / push",
        "",
        f"- 산출물 생성 전 상태: branch `{summary.get('git', {}).get('branch', 'unknown')}`, HEAD `{summary.get('git', {}).get('pre_publish_head', 'unknown')}`, origin/main `{summary.get('git', {}).get('pre_publish_origin_main', 'unknown')}`.",
        f"- 산출물 생성 전 HEAD == origin/main: {summary.get('git', {}).get('pre_publish_head_equals_origin_main', 'unknown')}; ahead/behind: {summary.get('git', {}).get('pre_publish_ahead_behind', 'unknown')}.",
        "- 이 산출물 디렉터리만 커밋·푸시하고, 완료 후 HEAD == origin/main 검증 결과와 commit SHA를 r.md에 기록해.",
        "",
        "## 산출물",
        "",
        *[f"- `{name}`" for name in summary.get("files_created", [])],
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    global CURRENT_STAGE
    CURRENT_STAGE = "PREFLIGHT"
    frozen = load_frozen_runner()
    pre, run_context, gate, control = preflight(frozen)
    archive_prefix = "attempt_02_" if (OUT / "initial_attempt_summary.json").exists() else "initial_attempt_"
    for name in ("failure.json", "preflight.json", "summary.json", "report.md"):
        existing = OUT / name
        if existing.is_file():
            existing.replace(OUT / f"{archive_prefix}{name}")
    write_json(OUT / "preflight.json", pre)
    CURRENT_STAGE = "CONTROL_SIGNAL_PARITY"
    prices = PriceCache()
    parity, parity_summary = frozen_control_signal_parity(run_context, control, prices)
    parity.to_csv(OUT / "signal_close_vs_entry_open_ma_parity.csv", index=False)

    control_events = pd.read_csv(CONTROL / "control_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    control_daily = pd.read_csv(CONTROL / "control_daily_equity.csv")
    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    trade_metrics: dict[str, Any] = {"CONTROL": frozen._trade_metrics(control)}
    portfolio_metrics: dict[str, Any] = {"CONTROL": dict(control_summary["portfolio"]["CONTROL"])}
    audit_by_candidate: dict[str, pd.DataFrame] = {}
    events_by_candidate: dict[str, pd.DataFrame] = {}
    trades_by_candidate: dict[str, pd.DataFrame] = {}
    blocked_summary: dict[str, Any] = {}
    blocked_analysis_frames: list[pd.DataFrame] = []
    opportunity_summary: dict[str, Any] = {}
    opportunity_rows: list[pd.DataFrame] = []
    worker_results: dict[str, Any] = {}
    identity_segment_by_key = {
        segment.key: segment
        for segments in run_context.segments_by_ticker.values()
        for segment in segments
    }

    CURRENT_STAGE = "CANDIDATE_REPLAY"
    for name, size in PERIODS.items():
        print(f"Starting independent {name} candidate replay with {WORKERS} workers", flush=True)
        records, run_info, audit, elapsed = candidate_replay(run_context, gate, prices, name, size)
        audit.to_csv(OUT / f"{name.lower()}_signal_audit.csv", index=False)
        frames = frozen._frames(run_info["outcomes"])
        strategy_id = f"PATTERN_A_FAST_FINAL_STRATEGY_V02_{name}_ENTRY_FILTER"
        if not records.empty:
            records = records.copy()
            records["strategy_id"] = strategy_id
            require(records["pair_id"].is_unique, f"{name}_PAIR_ID_NOT_UNIQUE")
        replay = frozen._portfolio_replay(records, frames, run_context, strategy_id)
        pd.DataFrame(replay["events"]).to_csv(OUT / f"{name.lower()}_portfolio_events.csv", index=False)
        pd.DataFrame(replay["daily_equity"]).to_csv(OUT / f"{name.lower()}_daily_equity.csv", index=False)
        records.to_csv(OUT / f"{name.lower()}_strategy_trades.csv", index=False)
        pd.DataFrame(replay["skipped"]).to_csv(OUT / f"{name.lower()}_skipped.csv", index=False)
        pd.DataFrame(replay["valuation_gap_audit"]).to_csv(OUT / f"{name.lower()}_valuation_carry_audit.csv", index=False)
        audit_by_candidate[name] = audit
        events_by_candidate[name] = pd.DataFrame(replay["events"])
        trades_by_candidate[name] = records
        trade_metrics[name] = strategy_metrics(records)
        portfolio_metrics[name] = dict(replay["metrics"])
        portfolio_metrics[name]["equity_curve_rows"] = len(replay["daily_equity"])
        worker_results[name] = {
            "worker_count": WORKERS,
            "worker_errors": len(run_info["worker_errors"]),
            "elapsed_seconds": elapsed,
            "ticker_count": len(run_context.segments_by_ticker),
            "strategy_trade_count": len(records),
            "raw_signal_audit_count": len(audit),
        }
        blocked, _, blocked_table = blocked_signal_analysis(control, parity, name, records, audit)
        blocked_summary[name] = blocked
        blocked_analysis_frames.append(blocked_table)
        opp, opp_rows = opportunity_analysis(control_events, control, events_by_candidate[name], records, name, portfolio_metrics["CONTROL"], portfolio_metrics[name])
        opportunity_summary[name] = opp
        opportunity_rows.append(opp_rows)

    pd.concat(blocked_analysis_frames, ignore_index=True, sort=False).to_csv(OUT / "filter_blocked_signal_analysis.csv", index=False)
    pd.concat(opportunity_rows, ignore_index=True, sort=False).to_csv(OUT / "opportunity_cost_analysis.csv", index=False)
    pd.DataFrame(prices.audit.values()).sort_values("ticker").to_csv(OUT / "price_store_audit.csv", index=False)

    # Candidate-specific entry, lifecycle and portfolio integrity gates.
    integrity: dict[str, Any] = {
        "frozen_authority_hashes_and_head_blobs": True,
        "saved_control_exact_parity": True,
        "frozen_control_not_replayed": True,
        "latest_rolling_authority_reads": 0,
        "network_api_or_new_price_calls": 0,
        "signal_close_equals_repository_v2_and_adjusted_store": True,
        "entry_open_equals_repository_v2_and_adjusted_store": True,
        "current_or_future_month_observations_used": 0,
        "workers": WORKERS,
        "candidate_worker_errors": 0,
        "accepted_signal_to_trade_ledger_one_to_one": True,
        "all_candidate_trades_passed_signal_close_filter": True,
        "production_or_canonical_source_changes": 0,
    }
    for name in PERIODS:
        pm = portfolio_metrics[name]
        audit = audit_by_candidate[name]
        raw = len(audit)
        pit_reject = int((~audit["pit_mcap_pass"].fillna(False)).sum()) if raw else 0
        ma_block = int((audit["pit_mcap_pass"].fillna(False) & ~audit["ma_filter_pass"].fillna(False)).sum()) if raw else 0
        ma_pass = int((audit["pit_mcap_pass"].fillna(False) & audit["ma_filter_pass"].fillna(False)).sum()) if raw else 0
        executable_pass = int((audit["candidate_signal_accepted"].fillna(False) & audit["entry_executable_within_cutoff"].fillna(False)).sum()) if raw else 0
        checks = {
            "signal_count_reconciles": raw == pit_reject + ma_block + ma_pass,
            "worker_errors_zero": worker_results[name]["worker_errors"] == 0,
            "cash_conservation_pass": bool(pm.get("cash_conservation_pass")),
            "unresolved_count_zero": int(pm.get("unresolved_count", -1)) == 0,
            "equity_curve_1140_rows": int(pm.get("equity_curve_rows", -1)) == 1140,
            "trades_equal_executable_accepted_signals": len(trades_by_candidate[name]) == executable_pass,
        }
        integrity[name] = checks
    integrity["all_candidate_checks_pass"] = all(
        all(integrity[name].values()) for name in PERIODS
    )

    control_avg = trade_metrics["CONTROL"].get("average_terminal_return_pct")
    gates: dict[str, Any] = {}
    for name in PERIODS:
        tm, pm = trade_metrics[name], portfolio_metrics[name]
        gates[name] = {
            "realized_win_rate_ge_50_pct": tm.get("realized_win_rate_pct") is not None and tm["realized_win_rate_pct"] >= 50,
            "median_terminal_ge_1_pct": tm.get("median_terminal_return_pct") is not None and tm["median_terminal_return_pct"] >= 1,
            "average_terminal_above_control": tm.get("average_terminal_return_pct") is not None and control_avg is not None and tm["average_terminal_return_pct"] > control_avg,
            "portfolio_mdd_above_neg_30_pct": pm.get("mdd_pct") is not None and pm["mdd_pct"] > -30,
        }
        gates[name]["all_pass"] = all(gates[name].values())

    def clearly_better(name: str) -> bool:
        tm, pm = trade_metrics[name], portfolio_metrics[name]
        control_pm = portfolio_metrics["CONTROL"]
        winners_50 = opportunity_summary[name]["realized_winner_change"]["net_realized_ge_pos_50"]
        winners_100 = opportunity_summary[name]["realized_winner_change"]["net_realized_ge_pos_100"]
        return bool(
            gates[name]["all_pass"]
            and pm.get("final_equity", 0) > control_pm.get("final_equity", 0)
            and pm.get("CAGR_pct", 0) > control_pm.get("CAGR_pct", 0)
            and pm.get("cash_shortage_skipped_entries", math.inf) <= control_pm.get("cash_shortage_skipped_entries", math.inf)
            and tm.get("terminal_ge_pos_50_count", 0) >= trade_metrics["CONTROL"].get("terminal_ge_pos_50_count", 0) - 2
            and tm.get("terminal_ge_pos_100_count", 0) >= trade_metrics["CONTROL"].get("terminal_ge_pos_100_count", 0) - 1
            and winners_50["lost_count"] <= 2
            and winners_100["lost_count"] <= 1
        )

    recommend = [name for name in PERIODS if clearly_better(name)]
    checks_pass = bool(integrity["all_candidate_checks_pass"])
    final_token = FINAL_TOKEN if checks_pass else CHECK_TOKEN
    files_created = sorted(path.name for path in OUT.iterdir() if path.is_file() and path.name not in {"report.md", "summary.json"})
    summary = {
        "work_id": "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01",
        "status": "COMPLETE" if final_token == FINAL_TOKEN else "CHECK_REQUIRED",
        "final_token": final_token,
        "severity": [("CRITICAL", 0 if checks_pass else 1, "없음" if checks_pass else "하나 이상의 무결성 검사가 미통과"), ("MAJOR", 0 if checks_pass else 1, "Frozen CONTROL과 MA20/MA60 독립 replay 완료" if checks_pass else "재생/현금/원장 검증 결과 확인 필요"), ("MINOR", 2, "P3-2 단일 구간으로 공식 전략 승격 불가; MA 미가용 신호는 fail-closed 처리")],
        "preflight": pre,
        "signal_close_vs_entry_open_parity": parity_summary,
        "signal_close_vs_entry_open_rows": len(parity),
        "strategy_metrics": trade_metrics,
        "portfolio_metrics": portfolio_metrics,
        "candidate_signal_counts": {name: blocked_summary[name] for name in PERIODS},
        "blocked_signal_analysis": blocked_summary,
        "opportunity_cost": opportunity_summary,
        "success_gates": gates,
        "five_window_recommendation": (f"다음 단계에서 별도 5-window validation 검토를 추천: {', '.join(recommend)}가 사용자 Gate 및 CONTROL 대비 포트폴리오 우위 기준을 충족했어." if recommend else "이번 P3-2 결과에서는 명확한 우위 기준을 충족한 후보가 없어 5-window validation을 추천하지 않아."),
        "integrity_checks": integrity,
        "worker_results": worker_results,
        "price_store_partition_count": len(prices.audit),
        "network_calls": 0,
        "production_or_canonical_changes": 0,
        "elapsed_seconds_by_candidate": {name: worker_results[name]["elapsed_seconds"] for name in PERIODS},
        "git": {
            "branch": git_text("branch", "--show-current"),
            "pre_publish_head": git_text("rev-parse", "HEAD"),
            "pre_publish_origin_main": git_text("rev-parse", "origin/main"),
            "pre_publish_head_equals_origin_main": git_text("rev-parse", "HEAD") == git_text("rev-parse", "origin/main"),
            "pre_publish_ahead_behind": git_text("rev-list", "--left-right", "--count", "origin/main...HEAD"),
            "post_publish_verification": "recorded in r.md after push",
        },
        "files_created": files_created,
    }
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(render_report(summary), encoding="utf-8")
    summary["files_created"] = sorted(path.name for path in OUT.iterdir() if path.is_file())
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    global CURRENT_STAGE
    started = time.perf_counter()
    try:
        result = run()
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_json(OUT / "summary.json", result)
        (OUT / "report.md").write_text(render_report(result), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    except BaseException as exc:
        failure = {
            "status": "CHECK_REQUIRED",
            "final_token": CHECK_TOKEN,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "stage": CURRENT_STAGE,
            "candidate_replay_started": CURRENT_STAGE == "CANDIDATE_REPLAY",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "automatic_rerun": False,
        }
        if OUT.exists():
            write_json(OUT / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
        raise


if __name__ == "__main__":
    main()
