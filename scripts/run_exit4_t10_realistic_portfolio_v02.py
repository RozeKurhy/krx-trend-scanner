#!/usr/bin/env python3
"""Replay the certified T15 entries as T15 and T10 realistic portfolios.

The frozen P2-1/P2-2/P3-2 control ledgers supply the common eligible entry
universe. The already-validated Exit4 threshold sensitivity ledger supplies
only the T10 counterfactual exits for affected trades. Portfolio cash, fills,
T+1 release, costs, and daily equity are replayed with the certified engine.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio


WORK_ID = "PATTERN_A_FAST_CORE_V2_EXIT4_T10_REALISTIC_PORTFOLIO_V02"
RUN_ID = "run_20260927_exit4_t10_realistic_portfolio_v02"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/exit4_t10_realistic_portfolio_v02"
RUN_OUTPUT_DIR = OUTPUT_DIR / RUN_ID
THRESHOLD_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/exit4_threshold_sensitivity_v01"
THRESHOLD_TRADES = THRESHOLD_DIR / "trade_level_comparison.csv"
THRESHOLD_SUMMARY = THRESHOLD_DIR / "summary.json"

WINDOWS: dict[str, dict[str, str]] = {
    "P2-1": {
        "folder": "p2_1_neg40_weak_protect_v01",
        "panel": "REALISTIC_P2-1_ELIGIBLE",
        "start": "2021-01-04",
        "end": "2025-05-30",
        "support": "2025-06-02",
    },
    "P2-2": {
        "folder": "p2_2_neg40_weak_protect_v01",
        "panel": "REALISTIC_P2-2_ELIGIBLE",
        "start": "2021-01-04",
        "end": "2026-08-31",
        "support": "2026-09-01",
    },
    "P3-2": {
        "folder": "p3_2_neg40_weak_protect_v01",
        "panel": "REALISTIC_P3-2_ELIGIBLE",
        "start": "2022-01-03",
        "end": "2026-08-31",
        "support": "2026-09-01",
    },
}
SOURCE_RUN_ID = "run_20260926_realistic_mcap1t_worker10_v01"
T15_STRATEGY_ID = strategy.V2_STRATEGY_ID
T10_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_EXIT4_T10_RESEARCH_V02"
T10_EXIT4_TYPE = "EXIT4_SCORE_DRAWDOWN_GE_10"
ENTRY_PARITY_FIELDS = (
    "ticker",
    "trade_id",
    "trade_sequence",
    "entry_signal_date",
    "entry_execution_date",
    "entry_pattern_a_stage",
    "market",
    "isu_cd",
    "identity_effective_from",
    "identity_effective_to",
)
ENTRY_NUMERIC_FIELDS = ("entry_open", "entry_market_cap")
EXIT_OUTCOME_FIELDS = {
    "strategy_id",
    "exit_type",
    "exit_signal_date",
    "exit_execution_date",
    "exit_price",
    "terminal_return",
    "mfe",
    "mae",
    "peak_giveback",
    "profit_capture",
    "holding_weeks",
    "holding_days",
    "trade_status",
    "terminal_valuation_date",
    "terminal_valuation_price",
    "terminal_valuation_source",
    "terminal_valuation_at_cutoff",
}
REPLAY_COMPARISON_FIELDS = (
    "final_equity",
    "final_equity_at_effective_close",
    "cumulative_return_pct",
    "CAGR_pct",
    "mdd_pct",
    "trade_count",
    "realized_trade_count",
    "win_rate_pct",
    "turnover_krw",
    "cash_shortage_skipped_entries",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("trade_id", "")),
        str(row.get("entry_signal_date", ""))[:10],
    )


def _pair_id(row: Mapping[str, Any]) -> str:
    return str(row.get("pair_id", ""))


def _clean(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _round_or_none(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return round(numeric, digits) if math.isfinite(numeric) else None


def _source_run_dir(window_id: str) -> Path:
    return ROOT / "artifacts/backtests" / WINDOWS[window_id]["folder"] / SOURCE_RUN_ID


def _load_source(window_id: str) -> tuple[dict[str, Any], pd.DataFrame, dict[str, str]]:
    source_dir = _source_run_dir(window_id)
    summary_path = source_dir / "summary.json"
    trades_path = source_dir / "control_strategy_trades.csv"
    pit_path = source_dir / "pit_mcap_audit.csv"
    contract_path = source_dir / "execution_contract.json"
    if not all(path.is_file() for path in (summary_path, trades_path, pit_path, contract_path)):
        raise FileNotFoundError(f"CERTIFIED_T15_SOURCE_ARTIFACT_MISSING:{window_id}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_status = f"{window_id.replace('-', '_')}_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED"
    if summary.get("window_id") != window_id or summary.get("status") != expected_status:
        raise RuntimeError(f"T15_SOURCE_NOT_CERTIFIED:{window_id}:{summary.get('status')}")
    if summary.get("strategy_ids", {}).get("control") != T15_STRATEGY_ID:
        raise RuntimeError(f"T15_SOURCE_STRATEGY_MISMATCH:{window_id}")
    frame = pd.read_csv(trades_path, dtype={"ticker": str, "trade_id": str, "isu_cd": str})
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
    frame["trade_id"] = frame["trade_id"].astype(str)
    if frame.empty or frame["pair_id"].astype(str).duplicated().any():
        raise RuntimeError(f"T15_SOURCE_LEDGER_EMPTY_OR_DUPLICATED:{window_id}")
    hashes = {
        "summary.json": _sha256(summary_path),
        "control_strategy_trades.csv": _sha256(trades_path),
        "pit_mcap_audit.csv": _sha256(pit_path),
        "execution_contract.json": _sha256(contract_path),
    }
    filter_path = source_dir / "filtered_universe_audit.csv"
    if filter_path.is_file():
        hashes["filtered_universe_audit.csv"] = _sha256(filter_path)
    return summary, frame, hashes


def validate_t15_alignment(control: pd.DataFrame, comparisons: pd.DataFrame) -> dict[str, Any]:
    """Require each archived T10 path to match the certified T15 trade row."""
    left = control.copy()
    right = comparisons.copy()
    left["_key"] = left.apply(_key, axis=1)
    right["_key"] = right.apply(_key, axis=1)
    if left["_key"].duplicated().any() or right["_key"].duplicated().any():
        raise RuntimeError("T15_ALIGNMENT_DUPLICATE_TRADE_KEY")
    by_key = left.set_index("_key", drop=False)
    missing = [key for key in right["_key"] if key not in by_key.index]
    if missing:
        raise RuntimeError(f"T15_ALIGNMENT_TRADE_MISSING:{len(missing)}")
    checks = {
        "exit_type": 0,
        "exit_signal_date": 0,
        "exit_execution_date": 0,
        "exit_price": 0,
        "terminal_return": 0,
        "mfe": 0,
        "mae": 0,
        "holding_days": 0,
    }
    for item in right.to_dict(orient="records"):
        source = by_key.loc[[item["_key"]]].iloc[0]
        pairs = (
            ("exit_type", "t15_exit_type"),
            ("exit_signal_date", "t15_signal_label"),
            ("exit_execution_date", "t15_exit_date"),
        )
        for source_col, analysis_col in pairs:
            a, b = _clean(source.get(source_col)), _clean(item.get(analysis_col))
            a = str(a)[:10] if a is not None else None
            b = str(b)[:10] if b is not None else None
            if a != b:
                raise RuntimeError(f"T15_ALIGNMENT_FAILED:{source_col}:{item.get('trade_id')}:{a}:{b}")
            checks[source_col] += 1
        for source_col, analysis_col in (
            ("exit_price", "t15_exit_price"),
            ("terminal_return", "t15_terminal_return"),
            ("mfe", "t15_mfe"),
            ("mae", "t15_mae"),
            ("holding_days", "t15_holding_days"),
        ):
            a = pd.to_numeric(pd.Series([source.get(source_col)]), errors="coerce").iloc[0]
            b = pd.to_numeric(pd.Series([item.get(analysis_col)]), errors="coerce").iloc[0]
            if pd.isna(a) and pd.isna(b):
                equal = True
            elif pd.isna(a) or pd.isna(b):
                equal = False
            else:
                equal = math.isclose(float(a), float(b), rel_tol=0, abs_tol=0.011)
            if not equal:
                raise RuntimeError(f"T15_ALIGNMENT_FAILED:{source_col}:{item.get('trade_id')}:{a}:{b}")
            checks[source_col] += 1
    return {
        "status": "PASS",
        "affected_trade_count": int(len(right)),
        "matched_t15_trade_count": int(len(right)),
        "field_checks": checks,
        "exact_common_entry_key": True,
    }


def validate_entry_parity(control: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    if len(control) != len(candidate):
        raise RuntimeError("T15_T10_ENTRY_COUNT_MISMATCH")
    a, b = control.copy(), candidate.copy()
    a["_key"] = a.apply(_key, axis=1)
    b["_key"] = b.apply(_key, axis=1)
    if a["_key"].duplicated().any() or b["_key"].duplicated().any():
        raise RuntimeError("T15_T10_DUPLICATE_ENTRY_KEY")
    joined = a.merge(b, on="_key", suffixes=("_t15", "_t10"), validate="one_to_one")
    for field in ENTRY_PARITY_FIELDS:
        left = joined[f"{field}_t15"].fillna("").astype(str)
        right = joined[f"{field}_t10"].fillna("").astype(str)
        if not left.equals(right):
            raise RuntimeError(f"T15_T10_ENTRY_PARITY_FAILED:{field}")
    for field in ENTRY_NUMERIC_FIELDS:
        left = pd.to_numeric(joined[f"{field}_t15"], errors="coerce")
        right = pd.to_numeric(joined[f"{field}_t10"], errors="coerce")
        if not np.allclose(left, right, rtol=0, atol=1e-9, equal_nan=True):
            raise RuntimeError(f"T15_T10_ENTRY_PARITY_FAILED:{field}")
    return {"status": "PASS", "entry_rows": len(joined), "entry_key_sets_equal": True}


def validate_exit_only_parity(control: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    """Ensure all strategy-ledger fields outside exits and derived outcomes are unchanged."""
    a, b = control.copy(), candidate.copy()
    a["_key"] = a.apply(_key, axis=1)
    b["_key"] = b.apply(_key, axis=1)
    if a["_key"].duplicated().any() or b["_key"].duplicated().any():
        raise RuntimeError("EXIT_ONLY_PARITY_DUPLICATE_ENTRY_KEY")
    if set(a["_key"]) != set(b["_key"]):
        raise RuntimeError("EXIT_ONLY_PARITY_ENTRY_IDENTITY_SET_MISMATCH")
    joined = a.merge(b, on="_key", suffixes=("_t15", "_t10"), validate="one_to_one")
    fields = [column for column in control.columns if column not in EXIT_OUTCOME_FIELDS]
    changed: list[str] = []
    for field in fields:
        left = joined[f"{field}_t15"].fillna("<NA>").astype(str)
        right = joined[f"{field}_t10"].fillna("<NA>").astype(str)
        if not left.equals(right):
            changed.append(field)
    if changed:
        raise RuntimeError(f"EXIT_ONLY_PARITY_NON_EXIT_FIELDS_CHANGED:{','.join(changed)}")
    if not candidate["strategy_id"].astype(str).eq(T10_STRATEGY_ID).all():
        raise RuntimeError("EXIT_ONLY_PARITY_TEST_STRATEGY_ID_MISMATCH")
    return {
        "status": "PASS",
        "entry_rows": len(joined),
        "non_exit_strategy_fields_compared": fields,
        "changed_fields_within_allowed_exit_outcomes": sorted(EXIT_OUTCOME_FIELDS.intersection(control.columns)),
    }


def _validate_source_execution_contract(window_id: str, contract: Mapping[str, Any], expected_pit_sha: str) -> dict[str, Any]:
    cap = contract.get("market_cap_filter", {})
    authority = contract.get("authority", {})
    portfolio_contract = contract.get("portfolio", {})
    checks = {
        "exact_entry_signal_date_mcap": cap.get("exact_entry_signal_date_only") is True,
        "no_proxy_or_nearest_date": (
            cap.get("no_proxy_or_nearest_date_or_fill") is True
            or cap.get("no_proxy_nearest_date_or_fill") is True
        ),
        "mcap_threshold_krw_1t": cap.get("threshold_krw") == 1_000_000_000_000,
        "mcap_unresolved_zero": cap.get("unresolved_count") == 0,
        "pit_authority_matches_current": authority.get("effective_pit_file_sha256") == expected_pit_sha,
        "worker_count_10": authority.get("worker_count") == 10,
        "initial_capital_krw_200m": portfolio_contract.get("initial_capital_krw") == 200_000_000.0,
        "position_budget_krw_5m": portfolio_contract.get("per_ticker_total_buy_cash_budget_krw") == 5_000_000.0,
        "no_concurrent_position_cap": portfolio_contract.get("position_cap") is None,
        "commission_rates_15bp": portfolio_contract.get("buy_commission_rate") == 0.00015
        and portfolio_contract.get("sell_commission_rate") == 0.00015,
        "slippage_rates_10bp": portfolio_contract.get("buy_slippage_rate") == 0.001
        and portfolio_contract.get("sell_slippage_rate") == 0.001,
        "t_plus_1_cash_release": str(portfolio_contract.get("cash_release", "")).startswith("next certified local trading session"),
        "full_order_no_partial_fill": portfolio_contract.get("partial_fill") is False,
        "same_control_strategy_id": contract.get("strategy_ids", {}).get("control") == T15_STRATEGY_ID,
        "window_scope_matches": contract.get("scope") == f"{window_id} only",
    }
    failed = [name for name, okay in checks.items() if not okay]
    if failed:
        raise RuntimeError(f"SOURCE_EXECUTION_CONTRACT_MISMATCH:{window_id}:{','.join(failed)}")
    return {"status": "PASS", "checks": checks}


def validate_pit_entry_rows(control: pd.DataFrame, pit_audit_path: Path) -> dict[str, Any]:
    audit = pd.read_csv(pit_audit_path, dtype={"ticker": str})
    audit["ticker"] = audit["ticker"].astype(str).str.zfill(6)
    audit["signal_date"] = audit["signal_date"].astype(str).str[:10]
    entries = control[["ticker", "entry_signal_date", "entry_market_cap"]].copy()
    entries["ticker"] = entries["ticker"].astype(str).str.zfill(6)
    entries["entry_signal_date"] = entries["entry_signal_date"].astype(str).str[:10]
    matched = entries.merge(
        audit[["ticker", "signal_date", "market_cap", "status", "source"]],
        left_on=["ticker", "entry_signal_date"],
        right_on=["ticker", "signal_date"],
        how="left",
        validate="one_to_one",
    )
    if matched["market_cap"].isna().any() or not matched["status"].eq("PASS").all():
        raise RuntimeError("PIT_ENTRY_AUDIT_MISSING_OR_NOT_PASS")
    entry_cap = pd.to_numeric(matched["entry_market_cap"], errors="coerce")
    audit_cap = pd.to_numeric(matched["market_cap"], errors="coerce")
    if entry_cap.isna().any() or (entry_cap < 1_000_000_000_000).any():
        raise RuntimeError("PIT_ENTRY_MARKET_CAP_BELOW_THRESHOLD_OR_MISSING")
    if not np.allclose(entry_cap, audit_cap, rtol=0, atol=0.01):
        raise RuntimeError("PIT_ENTRY_MARKET_CAP_MISMATCH")
    if not matched["source"].astype(str).str.contains("KRX Open API Stock Daily MKTCAP", regex=False).all():
        raise RuntimeError("PIT_ENTRY_AUDIT_SOURCE_MISMATCH")
    return {
        "status": "PASS",
        "entry_rows": int(len(matched)),
        "exact_ticker_signal_date_rows": True,
        "threshold_krw": 1_000_000_000_000,
        "market_cap_values_match_certified_audit": True,
        "future_or_proxy_rows": 0,
    }


def _segment_key(record: Mapping[str, Any]) -> str:
    return "|".join(
        (
            str(record.get("ticker", "")).zfill(6),
            str(record.get("isu_cd", "")),
            str(record.get("market", "")),
            str(record.get("identity_effective_from", "")),
            str(record.get("identity_effective_to", "")),
        )
    )


def _load_frames(
    window_id: str,
    source: pd.DataFrame,
    run: Any,
    effective_start: pd.Timestamp,
    effective_end: pd.Timestamp,
    support: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    segments = {
        segment.key: segment
        for grouped in run.segments_by_ticker.values()
        for segment in grouped
    }
    records = source.to_dict(orient="records")
    needed_keys = {_segment_key(row) for row in records}
    missing = sorted(needed_keys - set(segments))
    if missing:
        raise RuntimeError(f"SOURCE_IDENTITY_NOT_IN_WINDOW_AUTHORITY:{window_id}:{len(missing)}")
    loader = strategy.RepositoryV2DailyLoader(
        run.loader.repository,
        start=effective_start,
        end=support,
    )
    ticker_frames: dict[str, pd.DataFrame] = {}
    sparse_entry_open_fallback_tickers: list[str] = []
    for ticker in sorted({segments[key].ticker for key in needed_keys}):
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            source_rows = [row for row in records if str(row.get("ticker", "")).zfill(6) == ticker]
            entry_marks: dict[pd.Timestamp, float] = {}
            for row in source_rows:
                date_raw = _clean(row.get("entry_execution_date"))
                price_raw = pd.to_numeric(pd.Series([row.get("entry_open")]), errors="coerce").iloc[0]
                if date_raw is None or pd.isna(price_raw) or float(price_raw) <= 0:
                    raise RuntimeError(f"MISSING_REPOSITORY_V2_AND_CERTIFIED_ENTRY_OPEN:{window_id}:{ticker}")
                day = pd.Timestamp(date_raw).normalize()
                price = float(price_raw)
                if day in entry_marks and not math.isclose(entry_marks[day], price, rel_tol=0, abs_tol=0.011):
                    raise RuntimeError(f"CONFLICTING_CERTIFIED_ENTRY_OPEN:{window_id}:{ticker}:{day.date()}")
                entry_marks[day] = price
            if not entry_marks:
                raise RuntimeError(f"MISSING_REPOSITORY_V2_FRAME_WITHOUT_ENTRY_MARKS:{window_id}:{ticker}")
            daily = pd.DataFrame(
                {"open": list(entry_marks.values())},
                index=pd.DatetimeIndex(list(entry_marks.keys()), name=None),
            ).sort_index()
            sparse_entry_open_fallback_tickers.append(ticker)
        ticker_frames[ticker] = daily

    frames: dict[str, pd.DataFrame] = {}
    for key in sorted(needed_keys):
        segment = segments[key]
        daily = ticker_frames[segment.ticker]
        lower = max(effective_start, segment.effective_from)
        upper = min(support, segment.effective_to)
        price_columns = [column for column in ("open", "high", "low", "close") if column in daily.columns]
        scoped = daily.loc[(daily.index >= lower) & (daily.index <= upper), price_columns].sort_index().copy()
        settlement = strategy._confirmed_lifecycle_event_for_segment(
            segment,
            tuple(getattr(run, "lifecycle_settlements", ())),
            effective_end,
            run.segments_by_ticker,
        )
        if settlement is not None:
            settlement_day = strategy._event_effective_date(settlement)
            scoped = scoped.loc[scoped.index < settlement_day]
        if scoped.empty:
            raise RuntimeError(f"EMPTY_WINDOW_IDENTITY_FRAME:{window_id}:{key}")
        frames[key] = scoped
    return frames, {
        "identity_frame_count": len(frames),
        "ticker_frame_count": len(ticker_frames),
        "repository_v2_load_calls": int(loader.load_count),
        "sparse_entry_open_fallback_tickers": sparse_entry_open_fallback_tickers,
        "sparse_fallback_scope": "certified strategy-ledger entry_open only; valid only if T15 and T10 both skip every entry; any fill fails validation",
        "network_calls": 0,
    }


def _gap_classifications(source_dir: Path) -> dict[tuple[str, str], str]:
    candidates = (
        source_dir / "valuation_gap_closure_audit.csv",
        source_dir / "valuation_carry_audit.csv",
    )
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        return {}
    frame = pd.read_csv(path, dtype={"ticker": str})
    if not {"ticker", "valuation_date", "gap_classification"}.issubset(frame.columns):
        return {}
    result: dict[tuple[str, str], str] = {}
    for row in frame[["ticker", "valuation_date", "gap_classification"]].dropna().to_dict(orient="records"):
        result[(str(row["ticker"]).zfill(6), str(row["valuation_date"])[:10])] = str(row["gap_classification"])
    return result


def build_t10_ledger(
    control: pd.DataFrame,
    comparisons: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    effective_end: pd.Timestamp,
) -> pd.DataFrame:
    """Change only T10 Exit4 path outcomes while preserving every entry row."""
    result = control.copy(deep=True)
    result["strategy_id"] = T10_STRATEGY_ID
    result["_key"] = result.apply(_key, axis=1)
    indices = {key: idx for idx, key in enumerate(result["_key"].tolist())}
    for item in comparisons.to_dict(orient="records"):
        key = _key(item)
        if key not in indices:
            raise RuntimeError(f"T10_PATH_WITHOUT_CONTROL_TRADE:{key}")
        idx = indices[key]
        exit_type = _clean(item.get("t10_exit_type"))
        signal = _clean(item.get("t10_signal_label"))
        execution = _clean(item.get("t10_exit_date"))
        price = _clean(item.get("t10_exit_price"))
        score_drawdown = _clean(item.get("t10_score_drop_at_signal"))
        if exit_type is None:
            raise RuntimeError(f"T10_EXIT_TYPE_MISSING:{key}")
        if "EXIT4" in str(exit_type):
            if score_drawdown is None or float(score_drawdown) < 10.0:
                raise RuntimeError(f"T10_EXIT4_SCORE_DRAWDOWN_BELOW_THRESHOLD:{key}:{score_drawdown}")
            exit_type = T10_EXIT4_TYPE
        result.at[idx, "exit_type"] = str(exit_type)
        result.at[idx, "exit_signal_date"] = str(signal)[:10] if signal is not None else None
        result.at[idx, "exit_execution_date"] = str(execution)[:10] if execution is not None else None
        result.at[idx, "exit_price"] = float(price) if price is not None else np.nan
        for target, source_col in (
            ("terminal_return", "t10_terminal_return"),
            ("mfe", "t10_mfe"),
            ("mae", "t10_mae"),
            ("peak_giveback", "t10_giveback"),
            ("holding_days", "t10_holding_days"),
        ):
            value = _clean(item.get(source_col))
            result.at[idx, target] = float(value) if value is not None else np.nan
        holding_days = _clean(item.get("t10_holding_days"))
        result.at[idx, "holding_weeks"] = round(float(holding_days) / 5.0, 1) if holding_days is not None else np.nan
        mfe, terminal = _clean(item.get("t10_mfe")), _clean(item.get("t10_terminal_return"))
        result.at[idx, "profit_capture"] = (
            round(float(terminal) / float(mfe), 4)
            if mfe is not None and terminal is not None and float(mfe) > 0
            else np.nan
        )
        if execution is None:
            result.at[idx, "trade_status"] = "OPEN_AT_CUTOFF"
            frame = frames.get(_segment_key(result.iloc[idx].to_dict()))
            if frame is None:
                raise RuntimeError(f"T10_OPEN_TRADE_PRICE_FRAME_MISSING:{key}")
            entry_date = pd.Timestamp(result.at[idx, "entry_execution_date"]).normalize()
            marks = frame.loc[(frame.index >= entry_date) & (frame.index <= effective_end)]
            if marks.empty:
                raise RuntimeError(f"T10_OPEN_TRADE_TERMINAL_MARK_MISSING:{key}")
            terminal_date = pd.Timestamp(marks.index[-1]).normalize()
            result.at[idx, "terminal_valuation_date"] = terminal_date.strftime("%Y-%m-%d")
            result.at[idx, "terminal_valuation_price"] = float(marks.iloc[-1]["close"])
            result.at[idx, "terminal_valuation_source"] = "RepositoryV2DailyLoader.close"
            result.at[idx, "terminal_valuation_at_cutoff"] = terminal_date == effective_end
        else:
            result.at[idx, "trade_status"] = "REALIZED"
            result.at[idx, "terminal_valuation_date"] = None
            result.at[idx, "terminal_valuation_price"] = np.nan
            result.at[idx, "terminal_valuation_source"] = None
            result.at[idx, "terminal_valuation_at_cutoff"] = np.nan
    result = result.drop(columns=["_key"])
    validate_entry_parity(control, result)
    return result


def _quantiles(values: Sequence[Any]) -> dict[str, Any]:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {
        "n": int(len(series)),
        "mean": _round_or_none(series.mean()),
        "median": _round_or_none(series.median()),
        "p25": _round_or_none(series.quantile(0.25)),
        "p75": _round_or_none(series.quantile(0.75)),
    }


def portfolio_trade_details(
    replay: Mapping[str, Any],
    ledger: pd.DataFrame,
    trading_dates: Sequence[pd.Timestamp],
    effective_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join fills and exits into net-after-cost trade outcomes."""
    events = pd.DataFrame(replay["events"])
    if events.empty:
        raise RuntimeError("PORTFOLIO_REPLAY_EVENT_LEDGER_EMPTY")
    entries = events.loc[events["event_type"].eq("ENTRY")].copy()
    entry_decisions = entries[["pair_id", "trade_id", "ticker", "event_status", "reason", "execution_date"]].rename(
        columns={"event_status": "entry_status", "reason": "entry_decision_reason", "execution_date": "entry_fill_date"}
    )
    fills = entries.loc[entries["event_status"].eq("EXECUTED")].copy().set_index("pair_id", drop=False)
    exits = events.loc[events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")].copy()
    if exits["pair_id"].astype(str).duplicated().any():
        raise RuntimeError("MULTIPLE_EXECUTED_EXITS_FOR_PAIR")
    exit_by_pair = exits.set_index("pair_id", drop=False)
    ledger_by_pair = ledger.set_index("pair_id", drop=False)
    sessions = tuple(pd.Timestamp(day).normalize() for day in trading_dates)
    detail_rows: list[dict[str, Any]] = []
    for pair_id, entry in fills.iterrows():
        if pair_id not in ledger_by_pair.index:
            raise RuntimeError(f"EXECUTED_ENTRY_NOT_IN_STRATEGY_LEDGER:{pair_id}")
        source = ledger_by_pair.loc[pair_id]
        if isinstance(source, pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_STRATEGY_PAIR_ID:{pair_id}")
        buy_cost = float(entry["notional"]) + float(entry["commission"])
        exit_row = exit_by_pair.loc[pair_id] if pair_id in exit_by_pair.index else None
        if isinstance(exit_row, pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_EXECUTED_EXIT:{pair_id}")
        closed = exit_row is not None
        sell_proceeds = None
        net_pnl = None
        net_return_pct = None
        exit_date = None
        exit_reason = None
        if closed:
            sell_proceeds = float(exit_row["notional"]) - float(exit_row["commission"]) - float(exit_row["sell_tax"])
            net_pnl = sell_proceeds - buy_cost
            net_return_pct = (net_pnl / buy_cost * 100.0) if buy_cost else None
            exit_date = str(exit_row["execution_date"])
            exit_reason = str(exit_row["reason"])
        start_day = pd.Timestamp(entry["execution_date"]).normalize()
        end_day = pd.Timestamp(exit_date).normalize() if exit_date else effective_end
        holding_days = sum(start_day <= session <= end_day for session in sessions)
        mfe = pd.to_numeric(pd.Series([source.get("mfe")]), errors="coerce").iloc[0]
        mae = pd.to_numeric(pd.Series([source.get("mae")]), errors="coerce").iloc[0]
        capture = net_return_pct / float(mfe) if closed and not pd.isna(mfe) and float(mfe) > 0 else None
        giveback = float(mfe) - net_return_pct if closed and not pd.isna(mfe) and net_return_pct is not None else None
        detail_rows.append(
            {
                "pair_id": str(pair_id),
                "trade_id": str(source.get("trade_id", "")),
                "ticker": str(source.get("ticker", "")).zfill(6),
                "market": source.get("market"),
                "entry_signal_date": str(source.get("entry_signal_date", ""))[:10],
                "entry_execution_date": str(entry["execution_date"]),
                "entry_fill_price": float(entry["fill_price"]),
                "entry_shares": int(entry["shares"]),
                "buy_cost_after_slippage_and_commission_krw": buy_cost,
                "filled": True,
                "closed": bool(closed),
                "exit_execution_date": exit_date,
                "exit_fill_price": float(exit_row["fill_price"]) if closed else None,
                "exit_reason": exit_reason,
                "sell_proceeds_after_commission_and_tax_krw": sell_proceeds,
                "net_realized_pnl_krw": net_pnl,
                "net_realized_return_pct": net_return_pct,
                "mfe_pct": None if pd.isna(mfe) else float(mfe),
                "mae_pct": None if pd.isna(mae) else float(mae),
                "net_profit_capture_ratio": capture,
                "net_mfe_giveback_pp": giveback,
                "holding_trading_days": int(holding_days),
                "portfolio_open_at_effective_cutoff": not bool(closed),
                "source_exit_type": str(source.get("exit_type", "")),
            }
        )
    return pd.DataFrame(detail_rows), entry_decisions


def trade_statistics(details: pd.DataFrame) -> dict[str, Any]:
    closed = details.loc[details["closed"]].copy() if not details.empty else details.copy()
    returns = pd.to_numeric(closed.get("net_realized_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    pnl = pd.to_numeric(closed.get("net_realized_pnl_krw", pd.Series(dtype=float)), errors="coerce").dropna()
    wins = returns[returns > 1e-10]
    losses = returns[returns < -1e-10]
    flats = returns[returns.abs() <= 1e-10]
    positive_pnl = pnl[pnl > 0].sum()
    negative_pnl = pnl[pnl < 0].sum()
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    return {
        "total_filled_entries": int(len(details)),
        "total_closed_trades": int(len(returns)),
        "open_at_effective_cutoff": int(len(details) - int(details["closed"].sum())) if not details.empty else 0,
        "winning_trades_net_after_costs": int(len(wins)),
        "losing_trades_net_after_costs": int(len(losses)),
        "flat_trades_net_after_costs": int(len(flats)),
        "win_rate_pct": _round_or_none(100.0 * len(wins) / len(returns)) if len(returns) else None,
        "average_win_pct": _round_or_none(wins.mean()) if len(wins) else None,
        "median_win_pct": _round_or_none(wins.median()) if len(wins) else None,
        "average_loss_pct": _round_or_none(losses.mean()) if len(losses) else None,
        "median_loss_pct": _round_or_none(losses.median()) if len(losses) else None,
        "payoff_ratio": _round_or_none(avg_win / abs(avg_loss)) if avg_win is not None and avg_loss else None,
        "profit_factor": _round_or_none(positive_pnl / abs(negative_pnl)) if negative_pnl else None,
        "expectancy_per_trade_net_pct": _round_or_none(returns.mean()) if len(returns) else None,
        "expectancy_per_trade_net_krw": _round_or_none(pnl.mean()) if len(pnl) else None,
        "total_realized_pnl_net_after_costs_krw": _round_or_none(pnl.sum()),
    }


def return_distribution(details: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(
        details.loc[details["closed"], "net_realized_return_pct"] if not details.empty else pd.Series(dtype=float),
        errors="coerce",
    ).dropna()
    result = _quantiles(returns.tolist())
    for threshold in (20, 30, 50, 100, 200):
        result[f"ge_pos_{threshold}_count"] = int((returns >= threshold).sum())
    for threshold in (15, 30, 50, 60):
        result[f"le_neg_{threshold}_count"] = int((returns <= -threshold).sum())
    return result


def mfe_mae_statistics(details: pd.DataFrame) -> dict[str, Any]:
    mfe = _quantiles(details.get("mfe_pct", pd.Series(dtype=float)).tolist())
    mae = _quantiles(details.get("mae_pct", pd.Series(dtype=float)).tolist())
    closed = details.loc[details["closed"]] if not details.empty else details
    giveback = _quantiles(closed.get("net_mfe_giveback_pp", pd.Series(dtype=float)).tolist())
    capture = _quantiles(closed.get("net_profit_capture_ratio", pd.Series(dtype=float)).tolist())
    result: dict[str, Any] = {
        "filled_trade_mfe_pct": mfe,
        "filled_trade_mae_pct": mae,
        "realized_net_giveback_pp": giveback,
        "realized_net_profit_capture_ratio": capture,
    }
    for threshold in (50, 100):
        winners = closed.loc[pd.to_numeric(closed.get("net_realized_return_pct"), errors="coerce").ge(threshold)] if not closed.empty else closed
        result[f"ge_pos_{threshold}_winner_capture_ratio"] = _quantiles(
            winners.get("net_profit_capture_ratio", pd.Series(dtype=float)).tolist()
        )
    return result


def holding_statistics(details: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(details.get("holding_trading_days", pd.Series(dtype=float)), errors="coerce").dropna()
    result = _quantiles(values.tolist())
    result.update(
        {
            "le_60_trading_days": int((values <= 60).sum()),
            "le_120_trading_days": int((values <= 120).sum()),
            "gt_250_trading_days": int((values > 250).sum()),
            "over_1y_definition": "more than 250 local trading sessions",
        }
    )
    return result


def _classify_exit(exit_type: Any) -> str:
    value = str(exit_type or "").upper()
    if "NO_EXIT" in value or "NO_PROGRESSED" in value:
        return "No exit"
    if "EXIT4" in value:
        return "Exit4"
    if "EXIT3" in value:
        return "Exit3"
    if "LOSS_GUARD" in value or "LOSSGUARD" in value:
        return "Loss Guard"
    return "Other"


def exit_structure_summary(
    window_id: str,
    strategy_name: str,
    ledger: pd.DataFrame,
    details: pd.DataFrame,
    comparisons: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize strategy exits and the subset that actually filled in the portfolio."""
    path = ledger.copy()
    path["_exit_class"] = path["exit_type"].map(_classify_exit)
    panel = comparisons.copy()
    panel["_key"] = panel.apply(_key, axis=1)
    score_col = "t15_score_drop_at_signal" if strategy_name == "T15" else "t10_score_drop_at_signal"
    score_by_key = {
        row["_key"]: _clean(row.get(score_col)) for row in panel.to_dict(orient="records")
    }
    realized = details.loc[details["closed"]].copy() if not details.empty else details.copy()
    if not realized.empty:
        realized["_exit_class"] = realized["source_exit_type"].map(_classify_exit)
    rows: list[dict[str, Any]] = []
    all_keys = path.apply(_key, axis=1)
    for exit_class in ("Exit4", "Exit3", "Loss Guard", "Other", "No exit"):
        group = path.loc[path["_exit_class"].eq(exit_class)]
        returns = pd.to_numeric(group.get("terminal_return", pd.Series(dtype=float)), errors="coerce")
        holds = pd.to_numeric(group.get("holding_days", pd.Series(dtype=float)), errors="coerce")
        actual_drawdown = pd.to_numeric(
            pd.Series([score_by_key.get(key) for key, keep in zip(all_keys, path["_exit_class"].eq("Exit4")) if keep]),
            errors="coerce",
        ).dropna() if exit_class == "Exit4" else pd.Series(dtype=float)
        executed = realized.loc[realized["_exit_class"].eq(exit_class)] if not realized.empty else realized
        net_returns = pd.to_numeric(executed.get("net_realized_return_pct", pd.Series(dtype=float)), errors="coerce")
        executed_holds = pd.to_numeric(executed.get("holding_trading_days", pd.Series(dtype=float)), errors="coerce")
        rows.append(
            {
                "window": window_id,
                "strategy": strategy_name,
                "exit_class": exit_class,
                "strategy_path_exit_count": int(len(group)),
                "portfolio_executed_closed_fill_count": int(len(executed)),
                "path_return_mean_pct": _round_or_none(returns.mean()),
                "path_return_median_pct": _round_or_none(returns.median()),
                "path_holding_days_mean": _round_or_none(holds.mean()),
                "path_holding_days_median": _round_or_none(holds.median()),
                "portfolio_net_return_mean_pct": _round_or_none(net_returns.mean()),
                "portfolio_net_return_median_pct": _round_or_none(net_returns.median()),
                "portfolio_holding_days_mean": _round_or_none(executed_holds.mean()),
                "portfolio_holding_days_median": _round_or_none(executed_holds.median()),
                "exit4_actual_score_drawdown_sample_count": int(len(actual_drawdown)) if exit_class == "Exit4" else 0,
                "exit4_actual_score_drawdown_mean_pt": _round_or_none(actual_drawdown.mean()) if exit_class == "Exit4" else None,
                "exit4_actual_score_drawdown_median_pt": _round_or_none(actual_drawdown.median()) if exit_class == "Exit4" else None,
            }
        )
        rows[-1]["open_at_effective_cutoff_count"] = (
            int(group["trade_status"].astype(str).eq("OPEN_AT_CUTOFF").sum())
            if exit_class == "No exit" and "trade_status" in group
            else 0
        )
    return pd.DataFrame(rows)


def _entry_map(entry_decisions: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if entry_decisions.empty:
        return {}
    return {str(row["pair_id"]): row for row in entry_decisions.to_dict(orient="records")}


def rotation_analysis(
    window_id: str,
    t15_details: pd.DataFrame,
    t10_details: pd.DataFrame,
    t15_entries: pd.DataFrame,
    t10_entries: pd.DataFrame,
    t15_ledger: pd.DataFrame,
    t10_ledger: pd.DataFrame,
    trading_dates: Sequence[pd.Timestamp],
    effective_end: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    t15_event = _entry_map(t15_entries)
    t10_event = _entry_map(t10_entries)
    t15_detail = {str(row["pair_id"]): row for row in t15_details.to_dict(orient="records")}
    t10_detail = {str(row["pair_id"]): row for row in t10_details.to_dict(orient="records")}
    t15_records = {str(row["pair_id"]): row for row in t15_ledger.to_dict(orient="records")}
    t10_records = {str(row["pair_id"]): row for row in t10_ledger.to_dict(orient="records")}
    session_index = {pd.Timestamp(day).normalize(): index for index, day in enumerate(trading_dates)}
    early: list[dict[str, Any]] = []
    for pair_id, detail in t10_detail.items():
        if not detail.get("closed") or "EXIT4" not in str(detail.get("exit_reason", "")):
            continue
        c = t15_records[pair_id]
        t10_date = pd.Timestamp(detail["exit_execution_date"]).normalize()
        control_exit_raw = c.get("exit_execution_date")
        control_exit = None if control_exit_raw is None or pd.isna(control_exit_raw) else pd.Timestamp(control_exit_raw).normalize()
        if control_exit is not None and t10_date >= control_exit:
            continue
        next_session = session_index.get(t10_date, -1) + 1
        cash_available_date = (
            pd.Timestamp(trading_dates[next_session]).strftime("%Y-%m-%d")
            if 0 <= next_session < len(trading_dates)
            else None
        )
        t15_pos = session_index.get(control_exit) if control_exit is not None else None
        t10_pos = session_index.get(t10_date)
        proceeds = detail.get("sell_proceeds_after_commission_and_tax_krw")
        early.append(
            {
                "window": window_id,
                "pair_id": pair_id,
                "trade_id": detail.get("trade_id"),
                "ticker": detail.get("ticker"),
                "t10_exit_date": t10_date.strftime("%Y-%m-%d"),
                "t10_cash_available_date_t_plus_1": cash_available_date,
                "t15_exit_date": control_exit.strftime("%Y-%m-%d") if control_exit is not None else None,
                "exit_advance_trading_days_vs_t15": int(t15_pos - t10_pos) if t15_pos is not None and t10_pos is not None else None,
                "t10_net_sale_proceeds_krw": proceeds,
                "t10_net_realized_pnl_krw": detail.get("net_realized_pnl_krw"),
                "t15_was_filled": pair_id in t15_detail,
            }
        )
    extra_fills: list[str] = []
    t15_only_fills: list[str] = []
    for pair_id in sorted(set(t15_event) | set(t10_event)):
        t15_status = str(t15_event.get(pair_id, {}).get("entry_status", ""))
        t10_status = str(t10_event.get(pair_id, {}).get("entry_status", ""))
        if t10_status == "EXECUTED" and t15_status == "SKIPPED_CASH_UNAVAILABLE":
            extra_fills.append(pair_id)
        if t15_status == "EXECUTED" and t10_status != "EXECUTED":
            t15_only_fills.append(pair_id)
    extra_closed = [t10_detail[key] for key in extra_fills if key in t10_detail and t10_detail[key].get("closed")]
    t15_only_closed = [t15_detail[key] for key in t15_only_fills if key in t15_detail and t15_detail[key].get("closed")]
    metrics = {
        "executed_early_exit4_cash_release_count": len(early),
        "median_exit_advance_trading_days_when_t15_also_closed": _round_or_none(
            pd.Series([r["exit_advance_trading_days_vs_t15"] for r in early if r["exit_advance_trading_days_vs_t15"] is not None]).median()
        ),
        "t10_only_fills_previously_cash_skipped_by_t15": len(extra_fills),
        "t10_only_fills_closed_by_window_support": len(extra_closed),
        "t10_only_fills_net_realized_pnl_krw": _round_or_none(
            sum(float(row["net_realized_pnl_krw"]) for row in extra_closed)
        ),
        "t10_only_fills_still_open_at_cutoff": sum(
            1 for key in extra_fills if key in t10_detail and not t10_detail[key].get("closed")
        ),
        "t15_only_fills": len(t15_only_fills),
        "t15_only_fills_closed_by_window_support": len(t15_only_closed),
        "t15_only_fills_net_realized_pnl_krw": _round_or_none(
            sum(float(row["net_realized_pnl_krw"]) for row in t15_only_closed)
        ),
        "cash_release_policy": "T+1; sale proceeds are unavailable to same-day entries",
        "incremental_fill_attribution": (
            "T10 executed while T15 skipped the same eligible entry for cash shortage; cash is fungible, "
            "so this is a portfolio-level comparison and not a one-exit-to-one-entry earmark"
        ),
    }
    return metrics, pd.DataFrame(early)


def paired_trade_rows(
    window_id: str,
    control: pd.DataFrame,
    t10: pd.DataFrame,
    t15_details: pd.DataFrame,
    t10_details: pd.DataFrame,
    t15_entries: pd.DataFrame,
    t10_entries: pd.DataFrame,
) -> pd.DataFrame:
    base = control[[
        "pair_id", "trade_id", "ticker", "entry_signal_date", "entry_execution_date",
        "exit_type", "exit_signal_date", "exit_execution_date", "holding_days",
    ]].copy()
    base["ticker"] = base["ticker"].astype(str).str.zfill(6)
    base = base.rename(columns={
        "exit_type": "t15_exit_type", "exit_signal_date": "t15_exit_signal_date",
        "exit_execution_date": "t15_exit_execution_date", "holding_days": "t15_holding_days",
    })
    t10_cols = t10[["pair_id", "exit_type", "exit_signal_date", "exit_execution_date", "holding_days"]].rename(
        columns={
            "exit_type": "t10_exit_type", "exit_signal_date": "t10_exit_signal_date",
            "exit_execution_date": "t10_exit_execution_date", "holding_days": "t10_holding_days",
        }
    )
    base = base.merge(t10_cols, on="pair_id", validate="one_to_one")
    base["holding_days_delta_t10_minus_t15"] = (
        pd.to_numeric(base["t10_holding_days"], errors="coerce")
        - pd.to_numeric(base["t15_holding_days"], errors="coerce")
    )
    t15_d = t15_details.add_prefix("t15_").rename(columns={"t15_pair_id": "pair_id"})
    t10_d = t10_details.add_prefix("t10_").rename(columns={"t10_pair_id": "pair_id"})
    base = base.merge(
        t15_d[[
            "pair_id", "t15_filled", "t15_closed", "t15_net_realized_pnl_krw",
            "t15_net_realized_return_pct", "t15_mfe_pct", "t15_mae_pct",
            "t15_holding_trading_days", "t15_exit_reason",
        ]],
        on="pair_id", how="left", validate="one_to_one",
    )
    base = base.merge(
        t10_d[[
            "pair_id", "t10_filled", "t10_closed", "t10_net_realized_pnl_krw",
            "t10_net_realized_return_pct", "t10_mfe_pct", "t10_mae_pct",
            "t10_holding_trading_days", "t10_exit_reason",
        ]],
        on="pair_id", how="left", validate="one_to_one",
    )
    for side, events in (("t15", t15_entries), ("t10", t10_entries)):
        event = events[["pair_id", "entry_status", "entry_decision_reason"]].rename(
            columns={"entry_status": f"{side}_entry_status", "entry_decision_reason": f"{side}_entry_decision_reason"}
        )
        base = base.merge(event, on="pair_id", validate="one_to_one")
    base["portfolio_net_realized_pnl_delta_t10_minus_t15_krw"] = (
        pd.to_numeric(base["t10_net_realized_pnl_krw"], errors="coerce").fillna(0)
        - pd.to_numeric(base["t15_net_realized_pnl_krw"], errors="coerce").fillna(0)
    )
    base["net_realized_return_delta_t10_minus_t15_pp"] = (
        pd.to_numeric(base["t10_net_realized_return_pct"], errors="coerce")
        - pd.to_numeric(base["t15_net_realized_return_pct"], errors="coerce")
    )
    base["realized_holding_days_delta_t10_minus_t15"] = (
        pd.to_numeric(base["t10_holding_trading_days"], errors="coerce")
        - pd.to_numeric(base["t15_holding_trading_days"], errors="coerce")
    )
    base.insert(0, "window", window_id)
    return base


def winner_and_tail_summary(paired: pd.DataFrame, t15_details: pd.DataFrame, t10_details: pd.DataFrame, window_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    both = paired.loc[paired["t15_filled"].fillna(False) & paired["t10_filled"].fillna(False)]
    both_closed = both.loc[both["t15_closed"].fillna(False) & both["t10_closed"].fillna(False)]
    result: dict[str, Any] = {"window": window_id, "both_filled_trade_count": int(len(both)), "both_filled_and_closed_trade_count": int(len(both_closed))}
    for threshold in (50, 100, 200):
        t15r = pd.to_numeric(both_closed[f"t15_net_realized_return_pct"], errors="coerce")
        t10r = pd.to_numeric(both_closed[f"t10_net_realized_return_pct"], errors="coerce")
        result[f"ge_{threshold}_winner_gained"] = int(((t10r >= threshold) & (t15r < threshold)).sum())
        result[f"ge_{threshold}_winner_lost"] = int(((t15r >= threshold) & (t10r < threshold)).sum())
    diff = pd.to_numeric(both_closed["portfolio_net_realized_pnl_delta_t10_minus_t15_krw"], errors="coerce")
    result["t10_better_trade_count"] = int((diff > 0).sum())
    result["t15_better_trade_count"] = int((diff < 0).sum())
    result["equal_trade_count"] = int((diff == 0).sum())
    result["median_paired_return_delta_pp"] = _round_or_none(
        pd.to_numeric(both_closed["t10_net_realized_return_pct"], errors="coerce").sub(
            pd.to_numeric(both_closed["t15_net_realized_return_pct"], errors="coerce")
        ).median()
    )
    t15_returns = pd.to_numeric(both_closed["t15_net_realized_return_pct"], errors="coerce")
    t10_returns = pd.to_numeric(both_closed["t10_net_realized_return_pct"], errors="coerce")
    result["t15_winner_to_t10_loser_or_flat_count"] = int(((t15_returns > 0) & (t10_returns <= 0)).sum())
    result["t15_loser_or_flat_to_t10_winner_count"] = int(((t15_returns <= 0) & (t10_returns > 0)).sum())
    result["t15_winner_to_t10_loser_count"] = int(((t15_returns > 0) & (t10_returns < 0)).sum())
    result["t15_winner_to_t10_flat_count"] = int(((t15_returns > 0) & (t10_returns == 0)).sum())
    result["t15_nonwinner_to_t10_winner_count"] = int(((t15_returns <= 0) & (t10_returns > 0)).sum())
    paired_pnl_delta = pd.to_numeric(
        both_closed["portfolio_net_realized_pnl_delta_t10_minus_t15_krw"], errors="coerce"
    )
    result["paired_both_closed_t15_net_pnl_krw"] = _round_or_none(
        pd.to_numeric(both_closed["t15_net_realized_pnl_krw"], errors="coerce").sum()
    )
    result["paired_both_closed_t10_net_pnl_krw"] = _round_or_none(
        pd.to_numeric(both_closed["t10_net_realized_pnl_krw"], errors="coerce").sum()
    )
    result["paired_both_closed_net_pnl_delta_t10_minus_t15_krw"] = _round_or_none(paired_pnl_delta.sum())
    ranked_t15 = both_closed.sort_values("t15_net_realized_pnl_krw", ascending=False)
    for excluded_count in (1, 5):
        excluded_pair_ids = set(ranked_t15.head(excluded_count)["pair_id"].astype(str))
        keep = ~both_closed["pair_id"].astype(str).isin(excluded_pair_ids)
        result[f"paired_net_pnl_delta_excluding_top_{excluded_count}_t15_contributors_krw"] = _round_or_none(
            pd.to_numeric(
                both_closed.loc[keep, "portfolio_net_realized_pnl_delta_t10_minus_t15_krw"], errors="coerce"
            ).sum()
        )
        result[f"excluded_top_{excluded_count}_t15_contributor_count"] = min(excluded_count, len(both_closed))
    top_harmed = both_closed.sort_values("portfolio_net_realized_pnl_delta_t10_minus_t15_krw").head(10)
    top_rows = []
    for rank, row in enumerate(top_harmed.to_dict(orient="records"), start=1):
        top_rows.append(
            {
                "window": window_id,
                "rank_most_t10_harmed": rank,
                "trade_id": row["trade_id"],
                "ticker": row["ticker"],
                "t15_net_realized_return_pct": row["t15_net_realized_return_pct"],
                "t10_net_realized_return_pct": row["t10_net_realized_return_pct"],
                "return_delta_pp": _round_or_none(float(row["t10_net_realized_return_pct"]) - float(row["t15_net_realized_return_pct"])),
                "portfolio_net_realized_pnl_delta_t10_minus_t15_krw": row["portfolio_net_realized_pnl_delta_t10_minus_t15_krw"],
            }
        )
    tail: dict[str, Any] = {"window": window_id}
    for side, details in (("t15", t15_details), ("t10", t10_details)):
        closed = details.loc[details["closed"]]
        returns = pd.to_numeric(closed["net_realized_return_pct"], errors="coerce").dropna()
        pnl = pd.to_numeric(closed["net_realized_pnl_krw"], errors="coerce")
        for threshold in (15, 30, 50, 60):
            mask = returns <= -threshold
            tail[f"{side}_le_neg_{threshold}_count"] = int(mask.sum())
            tail[f"{side}_le_neg_{threshold}_loss_pnl_krw"] = _round_or_none(pnl.loc[mask].sum())
    t15_ret = pd.to_numeric(both_closed.get("t15_net_realized_return_pct"), errors="coerce")
    t10_ret = pd.to_numeric(both_closed.get("t10_net_realized_return_pct"), errors="coerce")
    for threshold in (30, 50):
        t15_deep = t15_ret.le(-threshold)
        t10_recovered = t10_ret.gt(-threshold)
        tail[f"paired_t15_le_neg_{threshold}_t10_above_threshold_count"] = int((t15_deep & t10_recovered).sum())
        tail[f"paired_t15_le_neg_{threshold}_t10_positive_count"] = int((t15_deep & t10_ret.gt(0)).sum())
    return result, top_rows, tail


def _stats_rows(window: str, strategy_name: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {"window": window, "strategy": strategy_name, **bundle}


def _baseline_replay_parity(actual: Mapping[str, Any], baseline: Mapping[str, Any], window_id: str) -> dict[str, Any]:
    mismatches: dict[str, Any] = {}
    for field in REPLAY_COMPARISON_FIELDS:
        a, b = actual.get(field), baseline.get(field)
        if a is None and b is None:
            continue
        if a is None or b is None or not math.isclose(float(a), float(b), rel_tol=0, abs_tol=0.02):
            mismatches[field] = {"replayed": a, "certified": b}
    if mismatches:
        raise RuntimeError(f"CERTIFIED_T15_PORTFOLIO_REPLAY_DIVERGED:{window_id}:{json.dumps(mismatches,sort_keys=True)}")
    return {"status": "PASS", "compared_metrics": list(REPLAY_COMPARISON_FIELDS), "source_replay_equal": True}


def _validate_sparse_fallback_nonfill(
    replay: Mapping[str, Any], tickers: Sequence[str], strategy_name: str, window_id: str
) -> dict[str, Any]:
    events = pd.DataFrame(replay["events"])
    if not tickers:
        return {"status": "PASS", "fallback_tickers": [], "executed_fallback_entries": 0, "cash_skip_entries": 0}
    fallback_entries = events.loc[
        events["event_type"].eq("ENTRY")
        & events["ticker"].astype(str).str.zfill(6).isin(set(tickers))
    ]
    executed = fallback_entries.loc[fallback_entries["event_status"].eq("EXECUTED")]
    if not executed.empty:
        raise RuntimeError(
            f"SPARSE_FALLBACK_POSITION_FILLED_REQUIRES_FULL_V2_FRAME:{window_id}:{strategy_name}:"
            f"{','.join(sorted(executed['ticker'].astype(str).unique()))}"
        )
    if fallback_entries.empty or not fallback_entries["event_status"].eq("SKIPPED_CASH_UNAVAILABLE").all():
        raise RuntimeError(f"SPARSE_FALLBACK_NOT_CASH_SKIPPED:{window_id}:{strategy_name}")
    return {
        "status": "PASS",
        "fallback_tickers": list(tickers),
        "executed_fallback_entries": 0,
        "cash_skip_entries": int(len(fallback_entries)),
        "entry_statuses": sorted(fallback_entries["event_status"].dropna().astype(str).unique()),
    }


def _run_window(window_id: str, comparisons: pd.DataFrame, start_head: str) -> dict[str, Any]:
    spec = WINDOWS[window_id]
    source_dir = _source_run_dir(window_id)
    source_summary, control, source_hashes = _load_source(window_id)
    execution_contract = json.loads((source_dir / "execution_contract.json").read_text(encoding="utf-8"))
    threshold_panel = comparisons.loc[comparisons["panel"].eq(spec["panel"])].copy()
    if threshold_panel.empty:
        raise RuntimeError(f"T10_THRESHOLD_PANEL_EMPTY:{window_id}")
    threshold_alignment = validate_t15_alignment(control, threshold_panel)

    run = strategy._load_context(window_id)
    effective_start = pd.Timestamp(run.window.effective_start).normalize()
    effective_end = pd.Timestamp(run.window.effective_end).normalize()
    support = pd.Timestamp(run.window.execution_support).normalize()
    if (effective_start.strftime("%Y-%m-%d"), effective_end.strftime("%Y-%m-%d"), support.strftime("%Y-%m-%d")) != (
        spec["start"], spec["end"], spec["support"]
    ):
        raise RuntimeError(f"WINDOW_CONTRACT_MISMATCH:{window_id}")
    source_authority_sha = source_summary.get("data_authority", {}).get("effective_pit_file_sha256")
    current_authority_sha = _sha256(run.authority.pit_path)
    if source_authority_sha and source_authority_sha != current_authority_sha:
        raise RuntimeError(f"EFFECTIVE_PIT_AUTHORITY_CHANGED:{window_id}")
    source_contract_validation = _validate_source_execution_contract(
        window_id, execution_contract, current_authority_sha
    )
    pit_entry_validation = validate_pit_entry_rows(control, source_dir / "pit_mcap_audit.csv")
    frames, frame_meta = _load_frames(window_id, control, run, effective_start, effective_end, support)
    t10 = build_t10_ledger(control, threshold_panel, frames, effective_end)
    entry_parity = validate_entry_parity(control, t10)
    exit_only_parity = validate_exit_only_parity(control, t10)
    calendar = tuple(pd.to_datetime(run.calendar.trading_dates).normalize())
    gap_classes = _gap_classifications(source_dir)

    t15_replay = portfolio._portfolio_replay(
        control.to_dict(orient="records"), frames, calendar,
        strategy_id=T15_STRATEGY_ID,
        effective_start=effective_start,
        effective_end=effective_end,
        execution_support=support,
        gap_classifications=gap_classes,
    )
    t15_parity = _baseline_replay_parity(
        t15_replay["metrics"], source_summary["portfolio"]["control"], window_id
    )
    t10_replay = portfolio._portfolio_replay(
        t10.to_dict(orient="records"), frames, calendar,
        strategy_id=T10_STRATEGY_ID,
        effective_start=effective_start,
        effective_end=effective_end,
        execution_support=support,
        gap_classifications=gap_classes,
    )
    fallback_tickers = frame_meta["sparse_entry_open_fallback_tickers"]
    sparse_fallback_validation = {
        "T15": _validate_sparse_fallback_nonfill(t15_replay, fallback_tickers, "T15", window_id),
        "T10": _validate_sparse_fallback_nonfill(t10_replay, fallback_tickers, "T10", window_id),
    }
    t15_details, t15_entries = portfolio_trade_details(t15_replay, control, calendar, effective_end)
    t10_details, t10_entries = portfolio_trade_details(t10_replay, t10, calendar, effective_end)
    rotation, early_exit_rows = rotation_analysis(
        window_id, t15_details, t10_details, t15_entries, t10_entries, control, t10, calendar, effective_end
    )
    exit_structure = pd.concat(
        [
            exit_structure_summary(window_id, "T15", control, t15_details, threshold_panel),
            exit_structure_summary(window_id, "T10", t10, t10_details, threshold_panel),
        ],
        ignore_index=True,
    )
    paired = paired_trade_rows(window_id, control, t10, t15_details, t10_details, t15_entries, t10_entries)
    winner_summary, top_harmed, tail_summary = winner_and_tail_summary(
        paired, t15_details, t10_details, window_id
    )

    t15_metrics = dict(t15_replay["metrics"])
    t10_metrics = dict(t10_replay["metrics"])
    t15_stats = trade_statistics(t15_details)
    t10_stats = trade_statistics(t10_details)
    t15_dist, t10_dist = return_distribution(t15_details), return_distribution(t10_details)
    t15_mfe, t10_mfe = mfe_mae_statistics(t15_details), mfe_mae_statistics(t10_details)
    t15_hold, t10_hold = holding_statistics(t15_details), holding_statistics(t10_details)
    detail_bundle = {
        "T15": {"portfolio": t15_metrics, "trade_statistics": t15_stats, "return_distribution": t15_dist,
                "mfe_mae": t15_mfe, "holding_period": t15_hold},
        "T10": {"portfolio": t10_metrics, "trade_statistics": t10_stats, "return_distribution": t10_dist,
                "mfe_mae": t10_mfe, "holding_period": t10_hold},
    }
    return {
        "window_id": window_id,
        "window": {"effective_start": spec["start"], "effective_end": spec["end"], "execution_support": spec["support"]},
        "source_dir": source_dir,
        "source_summary": source_summary,
        "source_hashes": source_hashes,
        "t15_ledger": control,
        "t10_ledger": t10,
        "t15_replay": t15_replay,
        "t10_replay": t10_replay,
        "t15_details": t15_details,
        "t10_details": t10_details,
        "t15_entries": t15_entries,
        "t10_entries": t10_entries,
        "paired": paired,
        "early_exit_rows": early_exit_rows,
        "t15_parity": t15_parity,
        "threshold_alignment": threshold_alignment,
        "entry_parity": entry_parity,
        "exit_only_parity": exit_only_parity,
        "source_contract_validation": source_contract_validation,
        "pit_entry_validation": pit_entry_validation,
        "sparse_fallback_validation": sparse_fallback_validation,
        "frame_meta": frame_meta,
        "rotation": rotation,
        "winner_summary": winner_summary,
        "top_harmed": top_harmed,
        "tail_summary": tail_summary,
        "exit_structure": exit_structure,
        "detail_bundle": detail_bundle,
        "threshold_panel": spec["panel"],
        "authority_sha256": current_authority_sha,
        "start_head": start_head,
    }


def _flatten_tables(results: Sequence[Mapping[str, Any]]) -> dict[str, pd.DataFrame]:
    portfolio_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    return_rows: list[dict[str, Any]] = []
    mfe_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    rotation_rows: list[dict[str, Any]] = []
    paired_rows: list[pd.DataFrame] = []
    early_rows: list[pd.DataFrame] = []
    winner_rows: list[dict[str, Any]] = []
    harmed_rows: list[dict[str, Any]] = []
    tail_rows: list[dict[str, Any]] = []
    trade_detail_rows: list[pd.DataFrame] = []
    equity_rows: list[pd.DataFrame] = []
    event_rows: list[pd.DataFrame] = []
    ledger_rows: list[pd.DataFrame] = []
    exit_structure_rows: list[pd.DataFrame] = []
    for result in results:
        window_id = result["window_id"]
        for strategy_name, replay_key in (("T15", "t15_replay"), ("T10", "t10_replay")):
            metrics = dict(result[replay_key]["metrics"])
            account = {
                key: metrics.get(key)
                for key in (
                    "final_equity", "final_equity_at_effective_close", "cumulative_return_pct", "CAGR_pct", "mdd_pct",
                    "trade_count", "realized_trade_count", "win_rate_pct", "turnover_krw", "turnover_multiple",
                    "average_capital_utilization_pct", "average_cash_ratio_pct", "cash_shortage_skipped_entries",
                    "maximum_concurrent_positions", "open_at_effective_cutoff_count", "unresolved_count",
                )
            }
            account["total_realized_pnl_net_after_costs_krw"] = result["detail_bundle"][strategy_name]["trade_statistics"]["total_realized_pnl_net_after_costs_krw"]
            portfolio_rows.append({"window": window_id, "strategy": strategy_name, **account})
            trade_rows.append(_stats_rows(window_id, strategy_name, result["detail_bundle"][strategy_name]["trade_statistics"]))
            return_rows.append({"window": window_id, "strategy": strategy_name, **result["detail_bundle"][strategy_name]["return_distribution"]})
            mfe_rows.append({"window": window_id, "strategy": strategy_name, **result["detail_bundle"][strategy_name]["mfe_mae"]})
            holding_rows.append({"window": window_id, "strategy": strategy_name, **result["detail_bundle"][strategy_name]["holding_period"]})
            details = result[f"{strategy_name.lower()}_details"].copy()
            details.insert(0, "window", window_id)
            details.insert(1, "strategy", strategy_name)
            trade_detail_rows.append(details)
            curve = pd.DataFrame(result[replay_key]["daily_equity"]).copy()
            curve.insert(0, "window", window_id)
            curve.insert(1, "strategy", strategy_name)
            equity_rows.append(curve)
            events = pd.DataFrame(result[replay_key]["events"]).copy()
            events.insert(0, "window", window_id)
            events.insert(1, "strategy", strategy_name)
            event_rows.append(events)
            ledger = result[f"{strategy_name.lower()}_ledger"].copy()
            ledger.insert(0, "window", window_id)
            ledger.insert(1, "strategy", strategy_name)
            ledger_rows.append(ledger)
        rotation_rows.append({"window": window_id, **result["rotation"]})
        paired_rows.append(result["paired"])
        early_rows.append(result["early_exit_rows"])
        winner_rows.append(result["winner_summary"])
        harmed_rows.extend(result["top_harmed"])
        tail_rows.append(result["tail_summary"])
        exit_structure_rows.append(result["exit_structure"])

    account_df = pd.DataFrame(portfolio_rows)
    delta_rows = []
    for window_id, group in account_df.groupby("window", sort=False):
        t15 = group.loc[group["strategy"].eq("T15")].iloc[0]
        t10 = group.loc[group["strategy"].eq("T10")].iloc[0]
        row: dict[str, Any] = {"window": window_id, "strategy": "T10_MINUS_T15"}
        for col in account_df.columns:
            if col in {"window", "strategy"}:
                continue
            left, right = pd.to_numeric(pd.Series([t10[col]]), errors="coerce").iloc[0], pd.to_numeric(pd.Series([t15[col]]), errors="coerce").iloc[0]
            row[col] = float(left - right) if not pd.isna(left) and not pd.isna(right) else None
        delta_rows.append(row)
    account_df = pd.concat([account_df, pd.DataFrame(delta_rows)], ignore_index=True)
    window_metric_rows: list[dict[str, Any]] = []
    for result in results:
        window_id = result["window_id"]
        side_values: dict[str, dict[str, Any]] = {}
        for side in ("T15", "T10"):
            replay = result[f"{side.lower()}_replay"]["metrics"]
            bundle = result["detail_bundle"][side]
            stats, dist = bundle["trade_statistics"], bundle["return_distribution"]
            mfe_mae, holding = bundle["mfe_mae"], bundle["holding_period"]
            side_values[side] = {
                "Final Asset (KRW)": replay.get("final_equity"),
                "Cumulative return (%)": replay.get("cumulative_return_pct"),
                "CAGR (%)": replay.get("CAGR_pct"),
                "MDD (%)": replay.get("mdd_pct"),
                "Win rate (%)": stats.get("win_rate_pct"),
                "Mean net realized return (%)": dist.get("mean"),
                "Median net realized return (%)": dist.get("median"),
                "Profit factor": stats.get("profit_factor"),
                "Median MFE (%)": mfe_mae["filled_trade_mfe_pct"].get("median"),
                "Median MAE (%)": mfe_mae["filled_trade_mae_pct"].get("median"),
                "Median net profit capture": mfe_mae["realized_net_profit_capture_ratio"].get("median"),
                "Median holding days": holding.get("median"),
                "Mean holding days": holding.get("mean"),
                "Holding days P25": holding.get("p25"),
                "Holding days P75": holding.get("p75"),
                "Turnover multiple": replay.get("turnover_multiple"),
                "Cash shortage skips": replay.get("cash_shortage_skipped_entries"),
                "Net return >= +50% count": dist.get("ge_pos_50_count"),
                "Net return >= +100% count": dist.get("ge_pos_100_count"),
                "Net return <= -30% count": dist.get("le_neg_30_count"),
                "Net return <= -50% count": dist.get("le_neg_50_count"),
                "Average invested capital (%)": replay.get("average_capital_utilization_pct"),
                "Average idle cash (%)": replay.get("average_cash_ratio_pct"),
            }
        for metric in side_values["T15"]:
            t15_value, t10_value = side_values["T15"][metric], side_values["T10"][metric]
            t15_num = pd.to_numeric(pd.Series([t15_value]), errors="coerce").iloc[0]
            t10_num = pd.to_numeric(pd.Series([t10_value]), errors="coerce").iloc[0]
            window_metric_rows.append(
                {
                    "window": window_id,
                    "metric": metric,
                    "T15": t15_value,
                    "T10": t10_value,
                    "T10_minus_T15": float(t10_num - t15_num) if not pd.isna(t10_num) and not pd.isna(t15_num) else None,
                }
            )
    return {
        "portfolio_summary.csv": account_df,
        "trade_statistics.csv": pd.DataFrame(trade_rows),
        "return_distribution.csv": pd.DataFrame(return_rows),
        "mfe_mae_comparison.csv": pd.DataFrame(mfe_rows),
        "holding_period_comparison.csv": pd.DataFrame(holding_rows),
        "capital_rotation_analysis.csv": pd.DataFrame(rotation_rows),
        "paired_trade_comparison.csv": pd.concat(paired_rows, ignore_index=True),
        "early_exit4_cash_release.csv": pd.concat(early_rows, ignore_index=True),
        "winner_impact.csv": pd.concat([pd.DataFrame(winner_rows), pd.DataFrame(harmed_rows)], ignore_index=True, sort=False),
        "tail_impact.csv": pd.DataFrame(tail_rows),
        "window_metric_comparison.csv": pd.DataFrame(window_metric_rows),
        "exit_structure.csv": pd.concat(exit_structure_rows, ignore_index=True),
        "portfolio_trade_detail.csv": pd.concat(trade_detail_rows, ignore_index=True),
        "daily_equity.csv": pd.concat(equity_rows, ignore_index=True),
        "portfolio_events.csv": pd.concat(event_rows, ignore_index=True),
        "strategy_trades.csv": pd.concat(ledger_rows, ignore_index=True),
    }


def _verdict(results: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    by_window: dict[str, Any] = {}
    advantage_count = 0
    account_improved_count = 0
    for result in results:
        t15 = result["t15_replay"]["metrics"]
        t10 = result["t10_replay"]["metrics"]
        t15_trade = trade_statistics(result["t15_details"])
        t10_trade = trade_statistics(result["t10_details"])
        tail_summary = result["tail_summary"]
        final_up = float(t10["final_equity"]) > float(t15["final_equity"])
        cagr_up = float(t10["CAGR_pct"]) > float(t15["CAGR_pct"])
        account_up = final_up and cagr_up
        structure_up = (
            (t10_trade["win_rate_pct"] or 0) > (t15_trade["win_rate_pct"] or 0)
            or (t10_trade["profit_factor"] or 0) > (t15_trade["profit_factor"] or 0)
            or (t10_trade["expectancy_per_trade_net_pct"] or 0) > (t15_trade["expectancy_per_trade_net_pct"] or 0)
        )
        mdd_delta = float(t10["mdd_pct"]) - float(t15["mdd_pct"])
        tail_worse = (
            tail_summary["t10_le_neg_30_count"] > tail_summary["t15_le_neg_30_count"]
            or tail_summary["t10_le_neg_50_count"] > tail_summary["t15_le_neg_50_count"]
        )
        risk_ok = mdd_delta >= -1.0 and not tail_worse
        rotation_pnl = float(result["rotation"].get("t10_only_fills_net_realized_pnl_krw") or 0)
        rotation_helped = rotation_pnl > 0
        supported = account_up and structure_up and risk_ok and rotation_helped
        advantage_count += int(supported)
        account_improved_count += int(account_up)
        by_window[result["window_id"]] = {
            "final_asset_up": final_up,
            "CAGR_up": cagr_up,
            "win_loss_structure_improved": structure_up,
            "MDD_delta_pp": _round_or_none(mdd_delta),
            "tail_not_worse": not tail_worse,
            "incremental_filled_trade_realized_pnl_positive": rotation_helped,
            "supports_T10": supported,
        }
    if advantage_count >= 2:
        verdict = "T10_PORTFOLIO_ADVANTAGE_SUPPORTED"
    elif account_improved_count == 0:
        verdict = "T15_REMAINS_PREFERRED"
    else:
        verdict = "MIXED_NO_CLEAR_PORTFOLIO_WINNER"
    return verdict, {"window_decisions": by_window, "supported_windows": advantage_count, "account_improved_windows": account_improved_count}


def _render_report(results: Sequence[Mapping[str, Any]], tables: Mapping[str, pd.DataFrame], verdict: str, verdict_detail: Mapping[str, Any], provenance: Mapping[str, Any]) -> str:
    portfolio_df = tables["portfolio_summary.csv"]
    trade_df = tables["trade_statistics.csv"]
    ret_df = tables["return_distribution.csv"]
    cap_df = tables["capital_rotation_analysis.csv"]
    winner_df = pd.DataFrame([result["winner_summary"] for result in results])
    tail_df = tables["tail_impact.csv"]

    def fmt(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):,.{digits}f}"

    out = [
        "# Exit4 T10 realistic portfolio comparison",
        "",
        f"- Work: `{WORK_ID}`",
        "- Control: `PATTERN_A_FAST_FINAL_STRATEGY_V02`, Exit4 HWM drawdown 15pt",
        "- Test: identical frozen eligible entry rows and strategy rules; only Exit4 HWM drawdown changes to 10pt",
        "- Execution: next local trading day open; KRW 200M initial capital; KRW 5M target position; T+1 sale-proceeds release; existing commission, tax, slippage and reinvestment rules",
        "- Position cap: none. Market cap: exact signal-date KRX raw MKTCAP >= KRW 1T; current-common identity and permanent exclusions reused from certified source runs",
        "- Portfolio and win/loss return metrics are net of actual modeled execution costs. MFE/MAE remain price-path percentages.",
        "- T10 exits come from the existing T10/T15 path analysis; only T10 and T15 data columns were used. No threshold sweep was rerun.",
        "",
        "## Verdict",
        "",
        f"**`{verdict}`**",
        "",
        "Window rule: support requires higher Final Asset and CAGR, an improved net win/loss measure, MDD no more than 1pp worse with no increase in -30/-50 tail counts, and positive realized P/L from incremental T10 fills. The final rule requires at least two of three windows.",
        "",
        "## Account performance",
        "",
        "Final Asset uses the execution-support-inclusive equity reported by the certified replay; positions still open at effective cutoff remain valued at the cutoff close.",
        "",
        "| Window | Strategy | Final Asset (KRW) | Cum. return | CAGR | MDD | Total realized P/L net (KRW) | Turnover | Filled / realized | Cash-short skips |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in portfolio_df.to_dict(orient="records"):
        out.append(
            f"| {row['window']} | {row['strategy']} | {fmt(row.get('final_equity'),0)} | {fmt(row.get('cumulative_return_pct'))}% | {fmt(row.get('CAGR_pct'))}% | {fmt(row.get('mdd_pct'))}% | {fmt(row.get('total_realized_pnl_net_after_costs_krw'),0)} | {fmt(row.get('turnover_multiple'))}x | {fmt(row.get('trade_count'),0)} / {fmt(row.get('realized_trade_count'),0)} | {fmt(row.get('cash_shortage_skipped_entries'),0)} |"
        )
    out.extend(["", "## Win/Loss statistics", "", "| Window | Strategy | Closed | Win / loss / flat | Win rate | Avg / median win | Avg / median loss | Payoff | Profit factor | Expectancy / trade |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in trade_df.to_dict(orient="records"):
        out.append(
            f"| {row['window']} | {row['strategy']} | {fmt(row.get('total_closed_trades'),0)} | {fmt(row.get('winning_trades_net_after_costs'),0)} / {fmt(row.get('losing_trades_net_after_costs'),0)} / {fmt(row.get('flat_trades_net_after_costs'),0)} | {fmt(row.get('win_rate_pct'))}% | {fmt(row.get('average_win_pct'))}% / {fmt(row.get('median_win_pct'))}% | {fmt(row.get('average_loss_pct'))}% / {fmt(row.get('median_loss_pct'))}% | {fmt(row.get('payoff_ratio'))} | {fmt(row.get('profit_factor'))} | {fmt(row.get('expectancy_per_trade_net_pct'))}%"
        )
    out.extend(["", "## Return distribution", "", "Counts use net realized trade returns after costs.", "", "| Window | Strategy | Mean | Median | P25 / P75 | >= +20% | >= +30% | >= +50% | >= +100% | >= +200% | <= -15% | <= -30% | <= -50% | <= -60% |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in ret_df.to_dict(orient="records"):
        out.append(
            f"| {row['window']} | {row['strategy']} | {fmt(row.get('mean'))}% | {fmt(row.get('median'))}% | {fmt(row.get('p25'))}% / {fmt(row.get('p75'))}% | {fmt(row.get('ge_pos_20_count'),0)} | {fmt(row.get('ge_pos_30_count'),0)} | {fmt(row.get('ge_pos_50_count'),0)} | {fmt(row.get('ge_pos_100_count'),0)} | {fmt(row.get('ge_pos_200_count'),0)} | {fmt(row.get('le_neg_15_count'),0)} | {fmt(row.get('le_neg_30_count'),0)} | {fmt(row.get('le_neg_50_count'),0)} | {fmt(row.get('le_neg_60_count'),0)} |"
        )
    out.extend(["", "## MFE / MAE", "", "Capture ratio is net realized return after costs divided by MFE, for closed fills with positive MFE. Giveback is MFE minus that net realized return. MFE/MAE distributions are across filled trades; capture and giveback use closed fills.", "", "| Window | Strategy | MFE mean / median / P25 / P75 | MAE mean / median / P25 / P75 | Median net giveback | Median net capture | +50 / +100 capture |", "|---|---|---:|---:|---:|---:|---:|"])
    for row in tables["mfe_mae_comparison.csv"].to_dict(orient="records"):
        mfe, mae = row.get("filled_trade_mfe_pct", {}), row.get("filled_trade_mae_pct", {})
        gb, cap = row.get("realized_net_giveback_pp", {}), row.get("realized_net_profit_capture_ratio", {})
        c50, c100 = row.get("ge_pos_50_winner_capture_ratio", {}), row.get("ge_pos_100_winner_capture_ratio", {})
        out.append(f"| {row['window']} | {row['strategy']} | {fmt(mfe.get('mean'))}% / {fmt(mfe.get('median'))}% / {fmt(mfe.get('p25'))}% / {fmt(mfe.get('p75'))}% | {fmt(mae.get('mean'))}% / {fmt(mae.get('median'))}% / {fmt(mae.get('p25'))}% / {fmt(mae.get('p75'))}% | {fmt(gb.get('median'))}pp | {fmt(cap.get('median'))} | {fmt(c50.get('median'))} / {fmt(c100.get('median'))} |")
    out.extend(["", "## Holding & capital rotation", "", "| Window | Strategy | Mean / median / P25 / P75 holding | <=60 / <=120 / >250 days | Avg invested / idle capital | Turnover | Cash skips | Early executed Exit4 | T10-only fills vs T15 cash skips | Their realized P/L (KRW) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for window_id in WINDOWS:
        cap = cap_df.loc[cap_df["window"].eq(window_id)].iloc[0].to_dict()
        for strategy_name in ("T15", "T10"):
            acc = portfolio_df.loc[portfolio_df["window"].eq(window_id) & portfolio_df["strategy"].eq(strategy_name)].iloc[0].to_dict()
            hold = tables["holding_period_comparison.csv"].loc[
                tables["holding_period_comparison.csv"]["window"].eq(window_id)
                & tables["holding_period_comparison.csv"]["strategy"].eq(strategy_name)
            ].iloc[0].to_dict()
            extra = cap if strategy_name == "T10" else {}
            out.append(
                f"| {window_id} | {strategy_name} | {fmt(hold.get('mean'))} / {fmt(hold.get('median'))} / {fmt(hold.get('p25'))} / {fmt(hold.get('p75'))}d | {fmt(hold.get('le_60_trading_days'),0)} / {fmt(hold.get('le_120_trading_days'),0)} / {fmt(hold.get('gt_250_trading_days'),0)} | {fmt(acc.get('average_capital_utilization_pct'))}% / {fmt(acc.get('average_cash_ratio_pct'))}% | {fmt(acc.get('turnover_multiple'))}x | {fmt(acc.get('cash_shortage_skipped_entries'),0)} | {fmt(extra.get('executed_early_exit4_cash_release_count'),0) if extra else '—'} | {fmt(extra.get('t10_only_fills_previously_cash_skipped_by_t15'),0) if extra else '—'} | {fmt(extra.get('t10_only_fills_net_realized_pnl_krw'),0) if extra else '—'} |"
            )
    out.extend(["", "Holding rows show mean / median / P25 / P75 in trading sessions. Incremental fills are eligible entries that T10 actually executed while T15 skipped for insufficient cash. Cash is fungible, so the comparison does not earmark an individual exit's proceeds to one entry.", "", "## Exit structure", "", "Path exit counts/returns use the strategy ledger for all eligible entries. Portfolio closed-fill columns show the subset that actually executed and realized; score drawdown is measured at the T15/T10 signal and is only available for Exit4 rows in the archived threshold comparison.", "", "| Window | Strategy | Exit class | Path count | Closed fills | Path return avg / median | Path hold avg / median | Actual score drawdown avg / median |", "|---|---|---|---:|---:|---:|---:|---:|"])
    for row in tables["exit_structure.csv"].to_dict(orient="records"):
        score = "—"
        if row.get("exit_class") == "Exit4":
            score = f"{fmt(row.get('exit4_actual_score_drawdown_mean_pt'))} / {fmt(row.get('exit4_actual_score_drawdown_median_pt'))}pt (n={fmt(row.get('exit4_actual_score_drawdown_sample_count'),0)})"
        out.append(f"| {row['window']} | {row['strategy']} | {row['exit_class']} | {fmt(row.get('strategy_path_exit_count'),0)} | {fmt(row.get('portfolio_executed_closed_fill_count'),0)} | {fmt(row.get('path_return_mean_pct'))}% / {fmt(row.get('path_return_median_pct'))}% | {fmt(row.get('path_holding_days_mean'))} / {fmt(row.get('path_holding_days_median'))}d | {score} |")
    out.extend(["", "## Winner impact", "", "| Window | Both filled & closed | +50 gained / lost | +100 gained / lost | +200 gained / lost | T10 / T15 better paired trades | Median paired return delta |", "|---|---:|---:|---:|---:|---:|---:|"])
    for row in winner_df.to_dict(orient="records"):
        out.append(f"| {row['window']} | {fmt(row.get('both_filled_and_closed_trade_count'),0)} | {fmt(row.get('ge_50_winner_gained'),0)} / {fmt(row.get('ge_50_winner_lost'),0)} | {fmt(row.get('ge_100_winner_gained'),0)} / {fmt(row.get('ge_100_winner_lost'),0)} | {fmt(row.get('ge_200_winner_gained'),0)} / {fmt(row.get('ge_200_winner_lost'),0)} | {fmt(row.get('t10_better_trade_count'),0)} / {fmt(row.get('t15_better_trade_count'),0)} | {fmt(row.get('median_paired_return_delta_pp'))}pp |")
    out.append("")
    for row in winner_df.to_dict(orient="records"):
        out.append(
            f"- {row['window']}: T15 winner → T10 loser/flat `{fmt(row.get('t15_winner_to_t10_loser_or_flat_count'),0)}` "
            f"(loser `{fmt(row.get('t15_winner_to_t10_loser_count'),0)}`, flat `{fmt(row.get('t15_winner_to_t10_flat_count'),0)}`); "
            f"T15 loser/flat → T10 winner `{fmt(row.get('t15_loser_or_flat_to_t10_winner_count'),0)}`. "
            f"Paired P/L delta after excluding top 1 / top 5 T15 contributors: "
            f"{fmt(row.get('paired_net_pnl_delta_excluding_top_1_t15_contributors_krw'),0)} / "
            f"{fmt(row.get('paired_net_pnl_delta_excluding_top_5_t15_contributors_krw'),0)} KRW."
        )
    out.extend(["", "The two sensitivity totals use trades filled and closed in both portfolios and remove the largest T15 realized P/L contributors. They are paired-trade attribution checks, not recomputed account curves. The 10 largest T10 portfolio-contribution reductions are in `winner_impact.csv`; the full paired ledger includes exit reasons, exit dates and holding-day deltas.", "", "## Tail impact", "", "| Window | <=-30 T15 / T10 (loss P/L KRW) | <=-50 T15 / T10 (loss P/L KRW) | <=-60 T15 / T10 | T15 <=-30 improved to above -30 | T15 <=-50 improved to above -50 |", "|---|---:|---:|---:|---:|---:|"])
    for row in tail_df.to_dict(orient="records"):
        out.append(f"| {row['window']} | {row['t15_le_neg_30_count']} / {row['t10_le_neg_30_count']} ({fmt(row.get('t15_le_neg_30_loss_pnl_krw'),0)} / {fmt(row.get('t10_le_neg_30_loss_pnl_krw'),0)}) | {row['t15_le_neg_50_count']} / {row['t10_le_neg_50_count']} ({fmt(row.get('t15_le_neg_50_loss_pnl_krw'),0)} / {fmt(row.get('t10_le_neg_50_loss_pnl_krw'),0)}) | {row['t15_le_neg_60_count']} / {row['t10_le_neg_60_count']} | {fmt(row.get('paired_t15_le_neg_30_t10_above_threshold_count'),0)} | {fmt(row.get('paired_t15_le_neg_50_t10_above_threshold_count'),0)} |")
    out.extend(["", "## Window consistency", "", "| Window | T10 advantage supported | Final asset up | CAGR up | Structure improved | MDD delta | Tail not worse | Incremental fill P/L positive |", "|---|---|---|---|---|---:|---|---|"])
    for window_id, row in verdict_detail["window_decisions"].items():
        out.append(f"| {window_id} | {row['supports_T10']} | {row['final_asset_up']} | {row['CAGR_up']} | {row['win_loss_structure_improved']} | {fmt(row['MDD_delta_pp'])}pp | {row['tail_not_worse']} | {row['incremental_filled_trade_realized_pnl_positive']} |")
    out.extend(["", "", "## Window-specific T10 vs T15 metric table", "", "Delta is T10 minus T15; win-rate delta is in percentage points. Windows overlap, so their account assets are not pooled."])
    window_comparison = tables["window_metric_comparison.csv"]
    for window_id in WINDOWS:
        out.extend(["", f"### {window_id}", "", "| Metric | T15 | T10 | Delta |", "|---|---:|---:|---:|"])
        for row in window_comparison.loc[window_comparison["window"].eq(window_id)].to_dict(orient="records"):
            metric = row["metric"]
            digits = 0 if "count" in metric.lower() or "skip" in metric.lower() or "(krw)" in metric.lower() else 2
            out.append(f"| {metric} | {fmt(row.get('T15'),digits)} | {fmt(row.get('T10'),digits)} | {fmt(row.get('T10_minus_T15'),digits)} |")
    out.extend(["", "## Final interpretation", "", f"Result: `{verdict}`. See each window table for win-rate pp, mean/median return, MFE/MAE, holding, turnover, tail and account deltas; the rotation and winner/tail sections quantify cash reuse and large-winner/loss transitions. This is a research comparison only; it does not promote or alter the production strategy.", "", "## Validation & provenance", ""])
    for result in results:
        out.append(
            f"- {result['window_id']}: certified T15 replay parity PASS; archived T15 path alignment PASS ({result['threshold_alignment']['matched_t15_trade_count']} affected trades); entry identity parity PASS ({result['entry_parity']['entry_rows']} rows); all non-exit strategy fields parity PASS; frozen execution/PIT contract PASS; unresolved={result['t10_replay']['metrics']['unresolved_count']}; cash conservation={result['t10_replay']['metrics']['cash_conservation_pass']}."
        )
    for result in results:
        fallback_tickers = result["frame_meta"]["sparse_entry_open_fallback_tickers"]
        if not fallback_tickers:
            continue
        fallback_validation = result["sparse_fallback_validation"]
        out.append(
            f"- {result['window_id']}: RepositoryV2 returned no composite frame for {', '.join(fallback_tickers)}. "
            f"Certified strategy-ledger entry opens were used only for cash checks; T15/T10 cash-skip entries="
            f"{fallback_validation['T15']['cash_skip_entries']}/{fallback_validation['T10']['cash_skip_entries']}; "
            "neither replay filled a fallback ticker, so no position mark or exit was simulated from that sparse row. "
            "Any such fill blocks validation."
        )
    out.extend([
        "- Source T15 strategy ledgers are the certified 2026-09-26 realistic portfolio artifacts; exact signal-date raw PIT market-cap audit was reused without network calls.",
        "- Baseline source hashes and effective PIT authority hashes are recorded in `summary.json`.",
        "- Pooled account-level performance is not summed because the windows overlap and each has its own start/end; cross-window consistency is reported instead.",
        "",
        "## Git",
        "",
        f"- Start HEAD: `{provenance['start_head']}`",
        f"- End HEAD: `{provenance['end_head']}`",
        "- Commit: not created",
        "- Push: not performed",
        f"- HEAD == origin/main: `{provenance['head_matches_origin_main']}`",
        "",
    ])
    return "\n".join(out)


def run(window_ids: Sequence[str] | None = None) -> dict[str, Any]:
    selected = list(window_ids or WINDOWS)
    unknown = sorted(set(selected) - set(WINDOWS))
    if unknown or not selected:
        raise ValueError(f"UNSUPPORTED_WINDOW_SELECTION:{unknown}")
    if RUN_OUTPUT_DIR.exists():
        raise RuntimeError(f"REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:{RUN_OUTPUT_DIR}")
    start_head = _git_head()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    threshold_summary = json.loads(THRESHOLD_SUMMARY.read_text(encoding="utf-8"))
    if threshold_summary.get("control_threshold_pt") != 15.0 or threshold_summary.get("thresholds_pt") is None:
        raise RuntimeError("EXIT4_THRESHOLD_SOURCE_CONTRACT_MISMATCH")
    if not THRESHOLD_TRADES.is_file():
        raise FileNotFoundError("EXIT4_THRESHOLD_TRADE_LEDGER_MISSING")
    comparisons = pd.read_csv(THRESHOLD_TRADES, dtype={"ticker": str, "trade_id": str})
    # Reuse the validated source schedule that includes 2026 executions.
    if not any(str(row[0]) == "2026-01-01" for row in portfolio.SELL_TAX_SCHEDULE):
        portfolio.SELL_TAX_SCHEDULE = (*portfolio.SELL_TAX_SCHEDULE, ("2026-01-01", "2026-12-31", 0.0020))
    results = []
    original_repository_builder = strategy.build_repository_v2
    shared_repository: dict[str, Any] = {}

    def build_shared_repository(root: Path | str, *, end: str | pd.Timestamp) -> Any:
        if "repository" not in shared_repository:
            shared_repository["repository"] = original_repository_builder(root, end=end)
        return shared_repository["repository"]

    strategy.build_repository_v2 = build_shared_repository
    try:
        for index, window_id in enumerate(selected, start=1):
            print(f"[{index}/{len(selected)}] loading and replaying {window_id}", flush=True)
            result = _run_window(window_id, comparisons, start_head)
            results.append(result)
            print(
                f"[{window_id}] T15 replay parity PASS; eligible={result['entry_parity']['entry_rows']}; "
                f"T10 fills={result['t10_replay']['metrics']['trade_count']}; "
                f"unresolved={result['t10_replay']['metrics']['unresolved_count']}",
                flush=True,
            )
    finally:
        strategy.build_repository_v2 = original_repository_builder
    if selected != list(WINDOWS):
        raise RuntimeError("FINAL_REPORT_REQUIRES_ALL_THREE_WINDOWS")
    verdict, verdict_detail = _verdict(results)
    tables = _flatten_tables(results)
    end_head = _git_head()
    origin_end = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    provenance = {
        "start_head": start_head,
        "end_head": end_head,
        "origin_main_at_start": origin,
        "origin_main_at_end": origin_end,
        "head_matches_origin_main": end_head == origin_end,
        "threshold_source_sha256": _sha256(THRESHOLD_TRADES),
        "threshold_source_summary_sha256": _sha256(THRESHOLD_SUMMARY),
        "threshold_source_scope": "T10 and T15 columns only; no new sweep",
        "portfolio_engine": "scripts.run_p2_1_realistic_portfolio_v01._portfolio_replay",
        "initial_capital_krw": portfolio.INITIAL_CAPITAL,
        "position_budget_krw": portfolio.POSITION_BUDGET,
        "workers_in_certified_source_runs": 10,
        "portfolio_replay_mode": "deterministic sequential event replay with certified cost and T+1 cash rules",
        "network_calls": 0,
    }
    validation = {
        "status": "PASS" if all(
            result["t15_parity"]["status"] == "PASS"
            and result["threshold_alignment"]["status"] == "PASS"
            and result["entry_parity"]["status"] == "PASS"
            and result["exit_only_parity"]["status"] == "PASS"
            and result["source_contract_validation"]["status"] == "PASS"
            and result["pit_entry_validation"]["status"] == "PASS"
            and all(item["status"] == "PASS" for item in result["sparse_fallback_validation"].values())
            and result["t10_replay"]["metrics"]["cash_conservation_pass"]
            and result["t10_replay"]["metrics"]["unresolved_count"] == 0
            for result in results
        ) else "CHECK_REQUIRED",
        "windows": {
            result["window_id"]: {
                "certified_t15_replay_parity": result["t15_parity"],
                "threshold_t15_alignment": result["threshold_alignment"],
                "entry_parity": result["entry_parity"],
                "exit_only_strategy_parity": result["exit_only_parity"],
                "frozen_source_execution_contract": result["source_contract_validation"],
                "exact_pit_entry_validation": result["pit_entry_validation"],
                "sparse_entry_open_nonfill_validation": result["sparse_fallback_validation"],
                "t10_cash_conservation_pass": result["t10_replay"]["metrics"]["cash_conservation_pass"],
                "t10_unresolved_count": result["t10_replay"]["metrics"]["unresolved_count"],
                "price_frame_loading": result["frame_meta"],
            }
            for result in results
        },
    }
    summary = {
        "work_id": WORK_ID,
        "run_id": RUN_ID,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "strategy_contract": {
            "control_strategy_id": T15_STRATEGY_ID,
            "test_strategy_id": T10_STRATEGY_ID,
            "control_exit4_threshold_pt": 15,
            "test_exit4_threshold_pt": 10,
            "only_strategy_delta": "PROGRESSED Exit4 HWM drawdown trigger 15pt -> 10pt",
            "same_entry_universe": True,
            "loss_guard_exit3_lifecycle_reentry_execution_universe_mcap_costs_and_position_sizing": "frozen to certified T15 source contract",
        },
        "analysis_scope": "realistic portfolio P2-1, P2-2, P3-2; no simple full replay; same entry identities; cash/capital reallocation is replayed",
        "pooled_account_reference": "not summed: windows overlap and have different effective boundaries",
        "validation": validation,
        "provenance": provenance,
        "windows": {
            result["window_id"]: {
                "window": result["window"],
                "source_status": result["source_summary"]["status"],
                "source_strategy_ids": result["source_summary"]["strategy_ids"],
                "source_hashes": result["source_hashes"],
                "effective_pit_authority_sha256": result["authority_sha256"],
                "threshold_panel": result["threshold_panel"],
                "threshold_alignment": result["threshold_alignment"],
                "entry_parity": result["entry_parity"],
                "T15": result["detail_bundle"]["T15"],
                "T10": result["detail_bundle"]["T10"],
                "T15_portfolio_metrics": result["t15_replay"]["metrics"],
                "T10_portfolio_metrics": result["t10_replay"]["metrics"],
                "capital_rotation": result["rotation"],
                "paired_winner_impact": result["winner_summary"],
                "tail_impact": result["tail_summary"],
                "exit_structure": result["exit_structure"].to_dict(orient="records"),
            }
            for result in results
        },
    }
    if RUN_OUTPUT_DIR.exists():
        raise RuntimeError(f"OUTPUT_PATH_APPEARED_DURING_RUN:{RUN_OUTPUT_DIR}")
    RUN_OUTPUT_DIR.mkdir(parents=True)
    for filename, frame in tables.items():
        frame.to_csv(RUN_OUTPUT_DIR / filename, index=False)
    for result in results:
        window_id = result["window_id"].lower().replace("-", "_")
        result["t15_ledger"].to_csv(RUN_OUTPUT_DIR / f"{window_id}_t15_strategy_trades.csv", index=False)
        result["t10_ledger"].to_csv(RUN_OUTPUT_DIR / f"{window_id}_t10_strategy_trades.csv", index=False)
    summary_path = RUN_OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = _render_report(results, tables, verdict, verdict_detail, provenance)
    (RUN_OUTPUT_DIR / "final_report.md").write_text(report, encoding="utf-8")
    manifest = {
        "run_id": RUN_ID,
        "work_id": WORK_ID,
        "status": validation["status"],
        "artifact_sha256": {
            path.name: _sha256(path)
            for path in sorted(RUN_OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        },
    }
    (RUN_OUTPUT_DIR / "artifact_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": validation["status"], "verdict": verdict, "run_output_dir": str(RUN_OUTPUT_DIR), "validation": validation}, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=(*WINDOWS.keys(), "all"), default="all")
    args = parser.parse_args()
    selected = list(WINDOWS) if args.window == "all" else [args.window]
    run(selected)


if __name__ == "__main__":
    main()
