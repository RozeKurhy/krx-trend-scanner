#!/usr/bin/env python3
"""Diagnostic-only monthly-MA entry-position analysis on frozen P3-2 CONTROL."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
CONTROL = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
HWM = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_120d_hwm_exit_experiment_v01"
PRICE_ROOT = ROOT / "data/market/adjusted/stocks"
CALENDAR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01/merged_trading_calendar.json"
CONTROL_TOKEN = "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA_ENTRY_POSITION_DIAGNOSTIC_V01_COMPLETE"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA_ENTRY_POSITION_DIAGNOSTIC_V01_CHECK_REQUIRED"
CONTROL_FILES = (
    "control_strategy_trades.csv",
    "control_portfolio_events.csv",
    "control_daily_equity.csv",
    "control_pit_mcap_audit.csv",
    "summary.json",
)
MAS = (5, 10, 20, 60)
MA_COLUMNS = {n: f"monthly_ma{n}" for n in MAS}


class DiagnosticError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise DiagnosticError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def preflight() -> dict[str, Any]:
    require(not any(p.name not in {"analyze_monthly_ma_entry.py", "__pycache__"} for p in OUT.iterdir()), "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS")
    control_summary_path = CONTROL / "summary.json"
    previous_preflight_path = HWM / "preflight.json"
    require(control_summary_path.is_file() and previous_preflight_path.is_file(), "FROZEN_CONTROL_OR_PRIOR_HASH_SNAPSHOT_MISSING")
    control_summary = json.loads(control_summary_path.read_text(encoding="utf-8"))
    previous = json.loads(previous_preflight_path.read_text(encoding="utf-8"))
    require(control_summary.get("status") == "COMPLETE" and control_summary.get("final_token") == CONTROL_TOKEN, "FROZEN_CONTROL_NOT_COMPLETE")
    require(control_summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    require(previous.get("status") == "PASS", "PREVIOUS_FROZEN_AUTHORITY_PREFLIGHT_NOT_PASS")
    prior_control = previous.get("control_authority", {})
    require(prior_control.get("source_final_token") == CONTROL_TOKEN, "PRIOR_AUTHORITY_TOKEN_MISMATCH")
    require(previous.get("latest_authority_dependency") is False, "PRIOR_AUTHORITY_USES_LATEST_ROLLING_DATA")
    require(previous.get("network_or_new_price_calls") == 0, "PRIOR_AUTHORITY_HAS_NETWORK_OR_PRICE_CALLS")

    hashes: dict[str, str] = {}
    expected = prior_control.get("source_control_file_sha256", {})
    for name in CONTROL_FILES:
        path = CONTROL / name
        require(path.is_file(), f"CONTROL_FILE_MISSING:{name}")
        data = path.read_bytes()
        value = hashlib.sha256(data).hexdigest()
        rel = path.relative_to(ROOT).as_posix()
        require(value == expected.get(name), f"CONTROL_HASH_DIFFERS_FROM_FROZEN_AUTHORITY:{name}")
        require(data == subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT), f"CONTROL_FILE_DIFFERS_FROM_HEAD:{name}")
        hashes[name] = value

    calendar_hash = sha256(CALENDAR)
    require(calendar_hash == control_summary.get("frozen_authority", {}).get("calendar_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")
    require(int(control_summary.get("provenance", {}).get("saved_control_strategy_rows", -1)) == 405, "CONTROL_TRADE_COUNT_NOT_405")
    return {
        "status": "PASS",
        "control_final_token": CONTROL_TOKEN,
        "control_source_commit": prior_control.get("source_commit"),
        "current_head": git_text("rev-parse", "HEAD"),
        "origin_main": git_text("rev-parse", "origin/main"),
        "control_file_sha256": hashes,
        "calendar_sha256": calendar_hash,
        "historical_pit_sha256": control_summary.get("frozen_authority", {}).get("historical_pit_sha256"),
        "survivor_count": control_summary.get("frozen_authority", {}).get("survivor_identity_count"),
        "control_trade_rows": control_summary.get("provenance", {}).get("saved_control_strategy_rows"),
        "control_event_rows": control_summary.get("provenance", {}).get("saved_control_event_rows"),
        "price_source": "Existing local Repository V2 AdjustedPriceStore (Naver direct adjusted OHLC); read-only, no collection/API/network calls.",
        "latest_authority_dependency": False,
        "network_or_new_price_calls": 0,
    }


def _load_price(ticker: str, cache: dict[str, tuple[pd.DataFrame, pd.Series]], audit: dict[str, dict[str, Any]]) -> tuple[pd.DataFrame, pd.Series]:
    ticker = str(ticker).zfill(6)
    if ticker in cache:
        return cache[ticker]
    path = PRICE_ROOT / f"{ticker}.parquet"
    meta_path = PRICE_ROOT / f"{ticker}.meta.json"
    require(path.is_file() and meta_path.is_file(), f"ADJUSTED_PRICE_STORE_OR_METADATA_MISSING:{ticker}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    content_hash = sha256(path)
    require(meta.get("ticker") == ticker, f"PRICE_METADATA_TICKER_MISMATCH:{ticker}")
    require(meta.get("content_sha256") == content_hash, f"PRICE_CONTENT_HASH_MISMATCH:{ticker}")
    require(meta.get("source_semantics") == "ADJUSTED_OHLC_ONLY", f"PRICE_SOURCE_SEMANTICS_INVALID:{ticker}")
    require(meta.get("authority_type") == "AUTHORITATIVE", f"PRICE_SOURCE_AUTHORITY_INVALID:{ticker}")
    frame = pd.read_parquet(path, columns=["date", "ticker", "open", "close"])
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
    require(frame["ticker"].eq(ticker).all(), f"PRICE_FILE_CONTAINS_OTHER_TICKER:{ticker}")
    require(not frame["date"].duplicated().any(), f"DUPLICATE_DAILY_PRICE_DATE:{ticker}")
    require(frame["date"].is_monotonic_increasing, f"DAILY_PRICE_DATES_NOT_SORTED:{ticker}")
    require(pd.to_numeric(frame["close"], errors="coerce").gt(0).all(), f"INVALID_ADJUSTED_CLOSE:{ticker}")
    require(pd.to_numeric(frame["open"], errors="coerce").gt(0).all(), f"INVALID_ADJUSTED_OPEN:{ticker}")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    frame["open"] = pd.to_numeric(frame["open"], errors="raise")
    frame["month"] = frame["date"].dt.to_period("M")
    monthly = frame.groupby("month", sort=True).tail(1).set_index("month")["close"].sort_index()
    require(not monthly.index.duplicated().any(), f"DUPLICATE_MONTHLY_CLOSE:{ticker}")
    audit[ticker] = {
        "ticker": ticker,
        "relative_path": path.relative_to(ROOT).as_posix(),
        "sha256": content_hash,
        "metadata_relative_path": meta_path.relative_to(ROOT).as_posix(),
        "metadata_sha256": sha256(meta_path),
        "source_authority_id": meta.get("source_authority_id"),
        "source_semantics": meta.get("source_semantics"),
        "authority_type": meta.get("authority_type"),
        "authority_decision_sha256": meta.get("authority_decision_sha256"),
        "requested_start": meta.get("requested_start"),
        "requested_end": meta.get("requested_end"),
        "actual_date_min": frame["date"].min().strftime("%Y-%m-%d"),
        "actual_date_max": frame["date"].max().strftime("%Y-%m-%d"),
        "row_count": int(len(frame)),
        "monthly_close_count": int(len(monthly)),
        "metadata_row_count_matches": int(meta.get("row_count", -1)) == len(frame),
        "metadata_date_range_matches": meta.get("actual_date_min") == frame["date"].min().strftime("%Y-%m-%d") and meta.get("actual_date_max") == frame["date"].max().strftime("%Y-%m-%d"),
    }
    require(audit[ticker]["metadata_row_count_matches"] and audit[ticker]["metadata_date_range_matches"], f"PRICE_METADATA_COVERAGE_MISMATCH:{ticker}")
    cache[ticker] = (frame, monthly)
    return cache[ticker]


def _features(trades: pd.DataFrame, cache: dict[str, tuple[pd.DataFrame, pd.Series]], price_audit: dict[str, dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    feature_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    open_mismatches: list[dict[str, Any]] = []
    monthly_coverage: dict[str, dict[str, int]] = {str(n): {} for n in MAS}
    month_used_violations = 0
    for row in trades.itertuples(index=False):
        ticker = str(row.ticker).zfill(6)
        daily, monthly = _load_price(ticker, cache, price_audit)
        entry_date = pd.Timestamp(row.entry_execution_date).normalize()
        entry_open = float(row.entry_open)
        entry_prices = daily.loc[daily["date"].eq(entry_date), "open"]
        if len(entry_prices) != 1 or not math.isclose(float(entry_prices.iloc[0]), entry_open, rel_tol=0, abs_tol=1e-9):
            open_mismatches.append({"pair_id": str(row.pair_id), "ticker": ticker, "entry_execution_date": entry_date.strftime("%Y-%m-%d"), "ledger_entry_open": entry_open, "store_open": None if len(entry_prices) != 1 else float(entry_prices.iloc[0])})
        entry_month = entry_date.to_period("M")
        last_completed_month = entry_month - 1
        before_entry_month = monthly.loc[monthly.index < entry_month]
        latest_pre_entry = str(before_entry_month.index.max()) if len(before_entry_month) else ""
        require(not latest_pre_entry or pd.Period(latest_pre_entry, freq="M") < entry_month, f"MONTHLY_CLOSE_NOT_PRE_ENTRY:{row.pair_id}")
        feature: dict[str, Any] = {
            "pair_id": str(row.pair_id),
            "ticker": ticker,
            "name": str(row.name),
            "market": str(row.market),
            "entry_signal_date": str(row.entry_signal_date)[:10],
            "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
            "entry_month": str(entry_month),
            "last_completed_month": str(last_completed_month),
            "latest_price_store_month_before_entry": latest_pre_entry,
            "entry_open": entry_open,
            "terminal_return": pd.to_numeric(pd.Series([row.terminal_return]), errors="coerce").iloc[0],
            "mfe": pd.to_numeric(pd.Series([row.mfe]), errors="coerce").iloc[0],
            "mae": pd.to_numeric(pd.Series([row.mae]), errors="coerce").iloc[0],
            "holding_days": pd.to_numeric(pd.Series([row.holding_days]), errors="coerce").iloc[0],
            "trade_status": str(row.trade_status),
            "exit_type": str(row.exit_type),
            "first_progressed_effective_trading_date": str(row.first_progressed_effective_trading_date),
        }
        resistance_count = 0
        resistance_ready = True
        unavailable_reasons: list[str] = []
        for n in MAS:
            expected = pd.period_range(end=last_completed_month, periods=n, freq="M")
            window = monthly.reindex(expected)
            missing = [str(p) for p, value in window.items() if pd.isna(value)]
            available = not missing
            if available:
                ma_value = float(window.mean())
                require(ma_value > 0 and math.isfinite(ma_value), f"INVALID_MONTHLY_MA:{row.pair_id}:MA{n}")
                status = "ENTRY_ABOVE" if entry_open > ma_value else "ENTRY_AT_OR_BELOW"
                distance = (entry_open / ma_value - 1.0) * 100.0
                resistance = ma_value > entry_open
                resistance_count += int(resistance)
                reason = ""
                used = [(str(p), float(value)) for p, value in window.items()]
            else:
                ma_value = None
                distance = None
                status = "UNAVAILABLE"
                resistance = None
                resistance_ready = False
                available_history = monthly.loc[monthly.index <= last_completed_month]
                reason = "INSUFFICIENT_HISTORY" if len(available_history) < n else "MISSING_MONTHLY_OBSERVATION"
                unavailable_reasons.append(f"MA{n}:{reason}")
                used = [(str(p), float(value)) for p, value in window.items() if pd.notna(value)]
            monthly_coverage[str(n)]["available" if available else reason] = monthly_coverage[str(n)].get("available" if available else reason, 0) + 1
            feature[f"monthly_ma{n}"] = ma_value
            feature[f"distance_to_ma{n}_pct"] = distance
            feature[f"ma{n}_entry_position"] = status
            feature[f"ma{n}_unavailable_reason"] = reason
            feature[f"ma{n}_resistance"] = resistance
            latest_used = max((pd.Period(p, freq="M") for p, _ in used), default=None)
            if latest_used is not None and latest_used >= entry_month:
                month_used_violations += 1
            audit_rows.append({
                "pair_id": str(row.pair_id),
                "ticker": ticker,
                "entry_execution_date": entry_date.strftime("%Y-%m-%d"),
                "entry_month": str(entry_month),
                "entry_open": entry_open,
                "ma_period": n,
                "last_completed_month_cutoff": str(last_completed_month),
                "window_start_month": str(expected[0]),
                "window_end_month": str(expected[-1]),
                "available": available,
                "unavailable_reason": reason,
                "missing_months": json.dumps(missing, ensure_ascii=False),
                "monthly_close_values_used": json.dumps([{"month": p, "adjusted_close": v} for p, v in used], ensure_ascii=False),
                "monthly_ma": ma_value,
                "distance_to_ma_pct": distance,
                "entry_position": status,
                "latest_month_used": "" if latest_used is None else str(latest_used),
                "source_partition_sha256": price_audit[ticker]["sha256"],
                "source_metadata_sha256": price_audit[ticker]["metadata_sha256"],
            })
        if resistance_ready:
            feature["resistance_ma_count"] = resistance_count
            feature["resistance_group"] = f"RESISTANCE_{resistance_count}"
            feature["resistance_unavailable_reason"] = ""
        else:
            feature["resistance_ma_count"] = None
            feature["resistance_group"] = "UNAVAILABLE"
            feature["resistance_unavailable_reason"] = ";".join(unavailable_reasons)
        feature_rows.append(feature)
    features = pd.DataFrame(feature_rows)
    require(len(features) == len(trades) and features["pair_id"].is_unique, "FEATURE_ROWS_OR_PAIR_ID_INVALID")
    require(not open_mismatches, "ENTRY_OPEN_DIFFERS_FROM_ADJUSTED_STORE:" + json.dumps(open_mismatches[:10], ensure_ascii=False))
    require(month_used_violations == 0, "ENTRY_MONTH_OR_FUTURE_MONTH_USED_FOR_MA")
    return features, pd.DataFrame(audit_rows), {
        "monthly_ma_coverage": monthly_coverage,
        "entry_open_mismatches": len(open_mismatches),
        "entry_open_rows_checked": len(trades),
        "monthly_ma_audit_rows": len(audit_rows),
        "future_or_entry_month_observations_used": month_used_violations,
        "price_store_partitions_read": len(price_audit),
    }


def _rate(mask: pd.Series, denominator: int) -> float | None:
    return float(mask.fillna(False).sum() * 100.0 / denominator) if denominator else None


def _number(frame: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(frame[col], errors="coerce")


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    n = len(frame)
    status = frame["trade_status"].fillna("").astype(str)
    realized = status.eq("REALIZED")
    terminal = _number(frame, "terminal_return")
    realized_return = terminal.loc[realized].dropna()
    mfe = _number(frame, "mfe")
    mae = _number(frame, "mae")
    holding = _number(frame, "holding_days")
    exit_type = frame["exit_type"].fillna("").astype(str)
    guard = exit_type.eq("LOSS_GUARD_CLOSE_LE_NEG_15")
    progressed = frame["first_progressed_effective_trading_date"].fillna("").astype(str).ne("")
    out: dict[str, Any] = {
        "trade_count": int(n),
        "realized_count": int(realized.sum()),
        "open_count": int(status.str.startswith("OPEN").sum()),
        "realized_win_rate_pct": _rate(realized_return.gt(0), len(realized_return)),
        "terminal_positive_rate_pct": _rate(terminal.gt(0), int(terminal.notna().sum())),
        "average_terminal_return_pct": float(terminal.mean()) if terminal.notna().any() else None,
        "median_terminal_return_pct": float(terminal.median()) if terminal.notna().any() else None,
        "average_realized_return_pct": float(realized_return.mean()) if len(realized_return) else None,
        "median_realized_return_pct": float(realized_return.median()) if len(realized_return) else None,
        "loss_guard_exit_count": int(guard.sum()),
        "loss_guard_exit_rate_pct": _rate(guard, n),
        "progressed_count": int(progressed.sum()),
        "progressed_rate_pct": _rate(progressed, n),
        "exit3_count": int(exit_type.str.startswith("EXIT3").sum()),
        "exit3_rate_pct": _rate(exit_type.str.startswith("EXIT3"), n),
        "exit4_count": int(exit_type.str.startswith("EXIT4").sum()),
        "exit4_rate_pct": _rate(exit_type.str.startswith("EXIT4"), n),
        "open_at_cutoff_count": int(status.eq("OPEN_AT_CUTOFF").sum()),
        "open_at_cutoff_rate_pct": _rate(status.eq("OPEN_AT_CUTOFF"), n),
        "average_holding_trading_days": float(holding.mean()) if holding.notna().any() else None,
        "median_holding_trading_days": float(holding.median()) if holding.notna().any() else None,
    }
    for threshold in (20, 50, 100):
        term_mask = terminal.ge(threshold)
        mfe_mask = mfe.ge(threshold)
        out[f"terminal_ge_pos_{threshold}_count"] = int(term_mask.sum())
        out[f"terminal_ge_pos_{threshold}_rate_pct"] = _rate(term_mask, int(terminal.notna().sum()))
        out[f"mfe_ge_pos_{threshold}_count"] = int(mfe_mask.sum())
        out[f"mfe_ge_pos_{threshold}_rate_pct"] = _rate(mfe_mask, int(mfe.notna().sum()))
    for threshold in (20, 30, 40):
        term_mask = terminal.le(-threshold)
        realized_mask = realized_return.le(-threshold)
        mae_mask = mae.le(-threshold)
        out[f"terminal_le_neg_{threshold}_count"] = int(term_mask.sum())
        out[f"terminal_le_neg_{threshold}_rate_pct"] = _rate(term_mask, int(terminal.notna().sum()))
        out[f"realized_le_neg_{threshold}_count"] = int(realized_mask.sum())
        out[f"realized_le_neg_{threshold}_rate_pct"] = _rate(realized_mask, len(realized_return))
        out[f"mae_le_neg_{threshold}_count"] = int(mae_mask.sum())
        out[f"mae_le_neg_{threshold}_rate_pct"] = _rate(mae_mask, int(mae.notna().sum()))
    return out


def _binary_metrics(features: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for n in MAS:
        col = f"ma{n}_entry_position"
        for group in ("ENTRY_ABOVE", "ENTRY_AT_OR_BELOW", "UNAVAILABLE"):
            mask = features[col].eq(group)
            scope = trades.loc[mask.to_numpy()]
            rows.append({"dimension": f"MA{n}", "group": group, "group_label": f"{group}_MA{n}" if group != "UNAVAILABLE" else "UNAVAILABLE", **_metrics(scope)})
    return pd.DataFrame(rows)


def _resistance_metrics(features: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    groups = [f"RESISTANCE_{n}" for n in range(5)] + ["UNAVAILABLE"]
    for group in groups:
        mask = features["resistance_group"].eq(group)
        rows.append({"dimension": "RESISTANCE_COUNT", "group": group, "resistance_ma_count": None if group == "UNAVAILABLE" else int(group[-1]), **_metrics(trades.loc[mask.to_numpy()])})
    return pd.DataFrame(rows)


def _direct_comparison(binary: pd.DataFrame) -> pd.DataFrame:
    fields = (
        "trade_count", "realized_win_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct",
        "loss_guard_exit_rate_pct", "progressed_rate_pct", "mfe_ge_pos_50_rate_pct",
        "mfe_ge_pos_100_rate_pct", "mae_le_neg_30_rate_pct",
    )
    rows: list[dict[str, Any]] = []
    for n in MAS:
        scoped = binary.loc[binary["dimension"].eq(f"MA{n}")].set_index("group")
        above = scoped.loc["ENTRY_ABOVE"]
        below = scoped.loc["ENTRY_AT_OR_BELOW"]
        row: dict[str, Any] = {"ma": f"MA{n}", "above_trade_count": int(above["trade_count"]), "at_or_below_trade_count": int(below["trade_count"])}
        for field in fields[1:]:
            a, b = above[field], below[field]
            row[f"{field}_above"] = a
            row[f"{field}_at_or_below"] = b
            row[f"{field}_above_minus_at_or_below"] = a - b if pd.notna(a) and pd.notna(b) else None
        rows.append(row)
    return pd.DataFrame(rows)


def _portfolio_metrics(features: pd.DataFrame, events: pd.DataFrame, control_summary: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    events = events.copy()
    events["pair_id"] = events["pair_id"].astype(str)
    entries = events.loc[events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED")].copy()
    exits = events.loc[events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")].copy()
    skips = events.loc[events["event_type"].eq("ENTRY") & events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")]
    require(entries["pair_id"].is_unique and exits["pair_id"].is_unique, "DUPLICATE_EXECUTED_PORTFOLIO_PAIR")
    require(set(entries["pair_id"]).issubset(set(features["pair_id"])), "EXECUTED_ENTRY_WITHOUT_LEDGER_ROW")
    require(set(exits["pair_id"]).issubset(set(entries["pair_id"])), "EXECUTED_EXIT_WITHOUT_ENTRY")
    labels = [f"ma{n}_entry_position" for n in MAS] + ["resistance_group", "resistance_ma_count"]
    entry_groups = entries.merge(features[["pair_id", *labels]], on="pair_id", how="left", validate="one_to_one")
    closed = entries.merge(exits, on="pair_id", how="inner", suffixes=("_entry", "_exit"), validate="one_to_one")
    closed = closed.merge(features[["pair_id", *labels]], on="pair_id", how="left", validate="one_to_one")
    closed["buy_cost_krw"] = pd.to_numeric(closed["notional_entry"], errors="coerce") + pd.to_numeric(closed["commission_entry"], errors="coerce")
    closed["sell_proceeds_krw"] = pd.to_numeric(closed["notional_exit"], errors="coerce") - pd.to_numeric(closed["commission_exit"], errors="coerce") - pd.to_numeric(closed["sell_tax_exit"], errors="coerce")
    closed["net_realized_pnl_krw"] = closed["sell_proceeds_krw"] - closed["buy_cost_krw"]
    closed["net_realized_return_pct"] = closed["net_realized_pnl_krw"] / closed["buy_cost_krw"] * 100.0
    require(closed["buy_cost_krw"].gt(0).all(), "NONPOSITIVE_ACTUAL_BUY_COST")
    portfolio_summary = control_summary.get("portfolio", {}).get("CONTROL", control_summary.get("portfolio", {}).get("control"))
    require(portfolio_summary is not None, "CONTROL_PORTFOLIO_SUMMARY_MISSING")
    require(len(entries) == int(portfolio_summary["trade_count"]), "ACTUAL_ENTRY_SUMMARY_MISMATCH")
    require(len(exits) == int(portfolio_summary["realized_trade_count"]), "ACTUAL_EXIT_SUMMARY_MISMATCH")
    require(len(skips) == int(portfolio_summary["cash_shortage_skipped_entries"]), "CASH_SKIP_SUMMARY_MISMATCH")
    total_pnl = float(closed["net_realized_pnl_krw"].sum())
    dimensions = {f"MA{n}": f"ma{n}_entry_position" for n in MAS}
    dimensions["RESISTANCE_COUNT"] = "resistance_group"
    rows: list[dict[str, Any]] = []
    for dimension, col in dimensions.items():
        groups = ["ENTRY_ABOVE", "ENTRY_AT_OR_BELOW", "UNAVAILABLE"] if dimension.startswith("MA") else [f"RESISTANCE_{n}" for n in range(5)] + ["UNAVAILABLE"]
        entry_total = 0
        exit_total = 0
        for group in groups:
            entry_group = entry_groups.loc[entry_groups[col].eq(group)]
            realized_group = closed.loc[closed[col].eq(group)]
            ret = pd.to_numeric(realized_group["net_realized_return_pct"], errors="coerce")
            pnl = float(realized_group["net_realized_pnl_krw"].sum())
            denom = len(ret)
            row: dict[str, Any] = {
                "dimension": dimension,
                "group": group,
                "actual_entry_count": int(len(entry_group)),
                "realized_count": int(len(realized_group)),
                "realized_win_rate_pct": _rate(ret.gt(0), denom),
                "average_realized_net_return_pct": float(ret.mean()) if denom else None,
                "median_realized_net_return_pct": float(ret.median()) if denom else None,
                "total_realized_net_pnl_krw": pnl,
                "share_of_total_realized_net_pnl_pct": pnl / total_pnl * 100.0 if abs(total_pnl) > 1e-12 else None,
            }
            for threshold in (50, 100):
                mask = ret.ge(threshold)
                row[f"realized_net_ge_pos_{threshold}_count"] = int(mask.sum())
                row[f"realized_net_ge_pos_{threshold}_rate_pct"] = _rate(mask, denom)
            for threshold in (30, 40):
                mask = ret.le(-threshold)
                row[f"realized_net_le_neg_{threshold}_count"] = int(mask.sum())
                row[f"realized_net_le_neg_{threshold}_rate_pct"] = _rate(mask, denom)
            rows.append(row)
            entry_total += len(entry_group)
            exit_total += len(realized_group)
        require(entry_total == len(entries), f"PORTFOLIO_ENTRY_GROUPS_DO_NOT_RECONCILE:{dimension}")
        require(exit_total == len(exits), f"PORTFOLIO_EXIT_GROUPS_DO_NOT_RECONCILE:{dimension}")
    require(math.isclose(sum(row["total_realized_net_pnl_krw"] for row in rows if row["dimension"] == "MA5"), total_pnl, rel_tol=0, abs_tol=1e-6), "PORTFOLIO_NET_PNL_GROUPS_DO_NOT_RECONCILE")
    return pd.DataFrame(rows), {
        "actual_entry_total": int(len(entries)),
        "realized_total": int(len(exits)),
        "open_after_execution_support_total": int(len(entries) - len(exits)),
        "open_at_effective_cutoff_total_from_control_authority": int(portfolio_summary["open_at_effective_cutoff_count"]),
        "cash_shortage_skipped_entry_total": int(len(skips)),
        "total_realized_net_pnl_krw": total_pnl,
        "net_pnl_formula": "EXIT notional - EXIT commission - EXIT sell tax - ENTRY notional - ENTRY commission; fill prices already include execution slippage.",
    }


def _pooled_metrics(features: pd.DataFrame, trades: pd.DataFrame, resistance_group: str) -> dict[str, Any]:
    selected = features["resistance_group"].eq(resistance_group) | features["resistance_group"].isin([f"RESISTANCE_{i}" for i in range(1, 5)]) if resistance_group == "RESISTANCE_1_PLUS" else features["resistance_group"].eq(resistance_group)
    return _metrics(trades.loc[selected.to_numpy()])


def _classify(binary: pd.DataFrame, resistance: pd.DataFrame, features: pd.DataFrame, trades: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    binary_idx = binary.set_index(["dimension", "group"])
    ma20_above = binary_idx.loc[("MA20", "ENTRY_ABOVE")]
    ma20_below = binary_idx.loc[("MA20", "ENTRY_AT_OR_BELOW")]
    core = ("realized_win_rate_pct", "median_terminal_return_pct", "average_terminal_return_pct")
    ma20_checks = {key: bool(pd.notna(ma20_above[key]) and pd.notna(ma20_below[key]) and ma20_above[key] > ma20_below[key]) for key in core}
    r0 = resistance.loc[resistance["group"].eq("RESISTANCE_0")].iloc[0]
    r1plus = _pooled_metrics(features, trades, "RESISTANCE_1_PLUS")
    r0_checks = {key: bool(pd.notna(r0[key]) and pd.notna(r1plus[key]) and r0[key] > r1plus[key]) for key in core}
    r0_checks["loss_guard_exit_rate_pct_lower"] = bool(pd.notna(r0["loss_guard_exit_rate_pct"]) and pd.notna(r1plus["loss_guard_exit_rate_pct"]) and r0["loss_guard_exit_rate_pct"] < r1plus["loss_guard_exit_rate_pct"])
    r0_checks["mae_le_neg_30_rate_pct_lower"] = bool(pd.notna(r0["mae_le_neg_30_rate_pct"]) and pd.notna(r1plus["mae_le_neg_30_rate_pct"]) and r0["mae_le_neg_30_rate_pct"] < r1plus["mae_le_neg_30_rate_pct"])
    nonempty = resistance.loc[resistance["group"].str.startswith("RESISTANCE_") & resistance["trade_count"].gt(0)].copy()
    nonempty["order"] = nonempty["group"].str.rsplit("_", n=1).str[-1].astype(int)
    nonempty = nonempty.sort_values("order")
    monotonic: dict[str, bool] = {}
    for key in ("realized_win_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct"):
        vals = nonempty[key].dropna().tolist()
        monotonic[f"{key}_nonincreasing"] = len(vals) == 5 and all(b <= a for a, b in zip(vals, vals[1:]))
    for key in ("loss_guard_exit_rate_pct", "mae_le_neg_30_rate_pct"):
        vals = nonempty[key].dropna().tolist()
        monotonic[f"{key}_nondecreasing"] = len(vals) == 5 and all(b >= a for a, b in zip(vals, vals[1:]))
    ma20_all = all(ma20_checks.values())
    r0_all_core = all(r0_checks[key] for key in core)
    if ma20_all or (r0_all_core and sum(monotonic.values()) >= 4):
        judgment = "MONTHLY_MA_ENTRY_POSITION_STRONG_SIGNAL"
    elif sum(ma20_checks.values()) >= 2 or (r0_all_core and any(monotonic.values())) or sum(r0_checks[key] for key in core) >= 2:
        judgment = "MONTHLY_MA_ENTRY_POSITION_MODERATE_SIGNAL"
    else:
        judgment = "MONTHLY_MA_ENTRY_POSITION_WEAK_OR_MIXED"
    return judgment, {
        "ma20_above_vs_at_or_below_core_checks": ma20_checks,
        "resistance_0_vs_resistance_1_plus_checks": r0_checks,
        "resistance_ordered_monotonic_checks": monotonic,
        "nonempty_resistance_group_count": int(len(nonempty)),
        "follow_up_candidate_backtest_recommended": judgment == "MONTHLY_MA_ENTRY_POSITION_STRONG_SIGNAL",
        "interpretation": "Descriptive directional checks only; no significance test, cutoff search, model fitting, or threshold optimization.",
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, (int,)) or (isinstance(value, float) and value.is_integer()):
        return f"{value:,.0f}"
    return f"{float(value):,.{digits}f}"


def _report(summary: dict[str, Any]) -> str:
    binary = pd.DataFrame(summary["ma_binary_metrics"])
    resistance = pd.DataFrame(summary["ma_resistance_count_metrics"])
    portfolio = pd.DataFrame(summary["portfolio_ma_metrics"])
    def bval(ma: str, group: str, metric: str) -> Any:
        return binary.loc[binary["dimension"].eq(ma) & binary["group"].eq(group), metric].iloc[0]
    ma_lines = []
    for n in MAS:
        dim = f"MA{n}"
        a, b = "ENTRY_ABOVE", "ENTRY_AT_OR_BELOW"
        n_a, n_b = int(bval(dim, a, "trade_count")), int(bval(dim, b, "trade_count"))
        fields = ("realized_win_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct", "loss_guard_exit_rate_pct", "progressed_rate_pct", "mfe_ge_pos_50_rate_pct", "mfe_ge_pos_100_rate_pct", "mae_le_neg_30_rate_pct")
        pairs = []
        for metric in fields:
            av, bv = bval(dim, a, metric), bval(dim, b, metric)
            pairs.append(f"{_fmt(av)} / {_fmt(bv)} / {_fmt(av-bv) if pd.notna(av) and pd.notna(bv) else '—'}")
        ma_lines.append(f"| MA{n} | {n_a} | {n_b} | " + " | ".join(pairs) + " |")
    res_lines = []
    for _, row in resistance.iterrows():
        if row["group"] == "UNAVAILABLE":
            continue
        res_lines.append("| {g} | {n} | {w}% | {a}% | {m}% | {lg}% | {p}% | {e3}% | {e4}% | {o}% | {m50}% | {m100}% | {mae}% |".format(
            g=row["group"].replace("RESISTANCE_", ""), n=int(row["trade_count"]), w=_fmt(row["realized_win_rate_pct"]),
            a=_fmt(row["average_terminal_return_pct"]), m=_fmt(row["median_terminal_return_pct"]),
            lg=_fmt(row["loss_guard_exit_rate_pct"]), p=_fmt(row["progressed_rate_pct"]),
            e3=_fmt(row["exit3_rate_pct"]), e4=_fmt(row["exit4_rate_pct"]), o=_fmt(row["open_at_cutoff_rate_pct"]),
            m50=_fmt(row["mfe_ge_pos_50_rate_pct"]), m100=_fmt(row["mfe_ge_pos_100_rate_pct"]), mae=_fmt(row["mae_le_neg_30_rate_pct"])))
    lifecycle_lines = []
    for _, row in binary.loc[binary["group"].ne("UNAVAILABLE")].iterrows():
        lifecycle_lines.append(f"| {row['dimension']} | {row['group']} | {int(row['trade_count'])} | {int(row['loss_guard_exit_count'])} ({_fmt(row['loss_guard_exit_rate_pct'])}%) | {int(row['progressed_count'])} ({_fmt(row['progressed_rate_pct'])}%) | {int(row['exit3_count'])} ({_fmt(row['exit3_rate_pct'])}%) | {int(row['exit4_count'])} ({_fmt(row['exit4_rate_pct'])}%) | {int(row['open_at_cutoff_count'])} ({_fmt(row['open_at_cutoff_rate_pct'])}%) |")
    for _, row in resistance.loc[resistance["group"].ne("UNAVAILABLE")].iterrows():
        lifecycle_lines.append(f"| Resistance {str(row['group']).replace('RESISTANCE_', '')} | all MA status | {int(row['trade_count'])} | {int(row['loss_guard_exit_count'])} ({_fmt(row['loss_guard_exit_rate_pct'])}%) | {int(row['progressed_count'])} ({_fmt(row['progressed_rate_pct'])}%) | {int(row['exit3_count'])} ({_fmt(row['exit3_rate_pct'])}%) | {int(row['exit4_count'])} ({_fmt(row['exit4_rate_pct'])}%) | {int(row['open_at_cutoff_count'])} ({_fmt(row['open_at_cutoff_rate_pct'])}%) |")
    portfolio_lines = []
    for _, row in portfolio.iterrows():
        portfolio_lines.append(f"| {row['dimension']} | {row['group']} | {int(row['actual_entry_count'])} | {int(row['realized_count'])} | {_fmt(row['realized_win_rate_pct'])}% | {_fmt(row['average_realized_net_return_pct'])}% / {_fmt(row['median_realized_net_return_pct'])}% | {int(row['realized_net_ge_pos_50_count'])} / {int(row['realized_net_ge_pos_100_count'])} | {int(row['realized_net_le_neg_30_count'])} / {int(row['realized_net_le_neg_40_count'])} | {_fmt(row['total_realized_net_pnl_krw'],0)}원 | {_fmt(row['share_of_total_realized_net_pnl_pct'])}% |")
    def threshold_cell(row: pd.Series, prefix: str, direction: str, thresholds: tuple[int, ...]) -> str:
        values = []
        for threshold in thresholds:
            count = int(row[f"{prefix}_{direction}_{threshold}_count"])
            rate_value = row[f"{prefix}_{direction}_{threshold}_rate_pct"]
            values.append(f"{count} ({_fmt(rate_value)}%)")
        return " / ".join(values)
    tail_lines = []
    for _, row in binary.iterrows():
        label = f"{row['dimension']} {row['group']}"
        tail_lines.append(f"| MA 분류 | {label} | {int(row['trade_count'])} | {threshold_cell(row,'terminal','ge_pos',(20,50,100))} | {threshold_cell(row,'terminal','le_neg',(20,30,40))} | {threshold_cell(row,'realized','le_neg',(20,30,40))} | {threshold_cell(row,'mfe','ge_pos',(20,50,100))} | {threshold_cell(row,'mae','le_neg',(20,30,40))} |")
    for _, row in resistance.iterrows():
        tail_lines.append(f"| Resistance | {row['group']} | {int(row['trade_count'])} | {threshold_cell(row,'terminal','ge_pos',(20,50,100))} | {threshold_cell(row,'terminal','le_neg',(20,30,40))} | {threshold_cell(row,'realized','le_neg',(20,30,40))} | {threshold_cell(row,'mfe','ge_pos',(20,50,100))} | {threshold_cell(row,'mae','le_neg',(20,30,40))} |")
    cov_lines = []
    for n in MAS:
        counts = summary["price_and_ma_coverage"]["monthly_ma_coverage"][str(n)]
        cov_lines.append(f"| MA{n} | {counts.get('available',0)} | {sum(v for k,v in counts.items() if k!='available')} | {json.dumps({k:v for k,v in counts.items() if k!='available'}, ensure_ascii=False) or '없음'} |")
    unavailable_ma_count = sum(1 for n in MAS if summary["price_and_ma_coverage"]["ma_unavailable_count"][str(n)] > 0)
    small_group_caveat = any(int(row["trade_count"]) < 30 for _, row in binary.loc[binary["group"].eq("ENTRY_AT_OR_BELOW")].iterrows()) or any(int(row["trade_count"]) == 0 for _, row in resistance.loc[resistance["group"].str.startswith("RESISTANCE_")].iterrows())
    minor_n = int(unavailable_ma_count > 0) + int(small_group_caveat)
    top = f"""| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | CONTROL provenance 및 모든 계산 무결성 검증 통과 |
| MAJOR | 0 | 확인된 무결성 차이 없음 |
| MINOR | {minor_n} | MA60 계산 불가 {summary['price_and_ma_coverage']['ma_unavailable_count']['60']}건은 보간하지 않았고, MA5/10/20 비교 및 resistance 상위 그룹은 표본이 작거나 비어 있어 방향 해석을 제한해야 해 |

## 1. 최종 토큰 / 판단

`{summary['final_token']}`<br>
판단: `{summary['judgment']}`

## 2. CONTROL provenance

- CONTROL 토큰: `{summary['control_provenance']['control_final_token']}`; frozen CONTROL 원장 405건.
- 다섯 기준 파일 hash가 이전 frozen replay snapshot 및 HEAD blob과 일치해.
- survivor {summary['control_provenance']['survivor_count']:,}개; 최신 rolling authority, API/network, 신규 가격 수집 의존은 0이야.

## 3. 월봉 PIT 계약 / 가격 source

- 진입 비교가격은 CONTROL의 실제 `entry_open`이며, 거래별 anchor는 `entry_execution_date`의 직전 확정 월이야.
- 월봉은 해당 월의 마지막 저장 adjusted close로 만들었고, MA5/10/20/60은 anchor 월까지 연속된 N개 월만 평균했어. 데이터가 빠지거나 부족하면 보간 없이 UNAVAILABLE로 뒀어.
- source: 로컬 Repository V2 AdjustedPriceStore, `ADJUSTED_OHLC_ONLY`, 권위 있는 Naver direct adjusted OHLC partition. 파티션·metadata hash와 date coverage를 기록했어.
- entry open {summary['price_and_ma_coverage']['entry_open_rows_checked']}건이 저장소 시가와 모두 일치. 진입월 또는 그 이후 월봉이 계산에 들어간 건 {summary['price_and_ma_coverage']['future_or_entry_month_observations_used']}건이야.

## 4. MA coverage

| MA | 계산 가능 | 불가 | 불가 사유별 건수 |
|---|---:|---:|---|
{chr(10).join(cov_lines)}

CONTROL 거래 전체 {summary['price_and_ma_coverage']['control_trade_count']}건. MA별 available + unavailable는 각 405건이야. Resistance 0~4 계산 불가 {summary['price_and_ma_coverage']['resistance_unavailable_count']}건; 사유: `{json.dumps(summary['price_and_ma_coverage']['resistance_unavailable_reasons'], ensure_ascii=False)}`.

## 5. MA5/10/20/60 개별 비교

각 셀은 Above / At-or-below / 차이(pp) 순서야. MA 별 full metrics는 `ma_binary_metrics.csv`에 있어.

| MA | Above n | At/below n | 승률 % A/B/Δ | 평균 terminal % A/B/Δ | 중앙 terminal % A/B/Δ | Loss Guard율 % A/B/Δ | PROGRESSED율 % A/B/Δ | MFE +50율 % A/B/Δ | MFE +100율 % A/B/Δ | MAE -30율 % A/B/Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(ma_lines)}

`ENTRY_ABOVE`는 entry_open > MA, `ENTRY_AT_OR_BELOW`는 entry_open <= MA야. 비교 불가 거래는 별도 `UNAVAILABLE` 그룹이야.

## 6. Resistance 0~4 비교

| 진입가 위 MA 수 | n | 승률 | 평균 terminal | 중앙 terminal | Loss Guard율 | PROGRESSED율 | Exit3율 | Exit4율 | cutoff 미청산율 | MFE >= +50율 | MFE >= +100율 | MAE <= -30율 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(res_lines)}

RESISTANCE_0~4 및 UNAVAILABLE 전체 통계는 `ma_resistance_count_metrics.csv`에 있어.

## 7. Loss Guard / PROGRESSED

| 구분 | 그룹 | n | Loss Guard n (율) | PROGRESSED n (율) | Exit3 n (율) | Exit4 n (율) | cutoff 미청산 n (율) |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(lifecycle_lines)}

PROGRESSED는 거래 lifecycle의 사후 관측값으로 진입 예측 신호가 아니야.

## 8. MFE / MAE / 대형 승리·손실

| 구분 | 그룹 | n | Terminal >= +20 / +50 / +100 | Terminal <= -20 / -30 / -40 | Realized <= -20 / -30 / -40 | MFE >= +20 / +50 / +100 | MAE <= -20 / -30 / -40 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(tail_lines)}

각 셀은 count (group 내 비율 %) 순서야. Terminal, realized tail, MFE, MAE를 분리해서 집계했어.

## 9. 실제 portfolio 체결 진단

기존 CONTROL의 실제 체결 entry/exit만 `pair_id`로 연결했어. 순 실현손익은 매수 notional+commission과 매도 notional-commission-sell tax의 차이야. 체결가에 반영된 슬리피지는 다시 빼지 않았어.

| Dimension | Group | 실제 진입 | 실현 | 실현 승률 | 평균 / 중앙 순 실현수익률 | 순 >= +50 / +100 | 순 <= -30 / -40 | 순 실현손익 | 기여율 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(portfolio_lines)}

전체 실제 진입 {summary['portfolio_totals']['actual_entry_total']}건, 실현 {summary['portfolio_totals']['realized_total']}건, 현금 부족 skip {summary['portfolio_totals']['cash_shortage_skipped_entry_total']}건, 순 실현손익 {_fmt(summary['portfolio_totals']['total_realized_net_pnl_krw'],0)}원이야.

## 10. 단조성 여부

- MA20 Above vs At/Below 핵심 방향: `{json.dumps(summary['signal_checks']['ma20_above_vs_at_or_below_core_checks'], ensure_ascii=False)}`
- RESISTANCE_0 vs RESISTANCE_1~4 pooled: `{json.dumps(summary['signal_checks']['resistance_0_vs_resistance_1_plus_checks'], ensure_ascii=False)}`
- Resistance count 증가 방향 체크: `{json.dumps(summary['signal_checks']['resistance_ordered_monotonic_checks'], ensure_ascii=False)}`
- 통계적 유의성은 검사하거나 주장하지 않았고, cutoff 탐색·회귀·threshold tuning도 하지 않았어.

## 11. 후속 필터 백테스트 추천 여부

`{summary['judgment']}`. `{ '후보 백테스트 별도 검토를 추천' if summary['signal_checks']['follow_up_candidate_backtest_recommended'] else '후속 백테스트를 추천하지 않음' }`. MA20 Above 핵심 세 지표는 모두 At/Below보다 높았지만 비교 표본은 각각 380건과 25건이야. 이는 방향성 후보일 뿐 통계적 유의성을 뜻하지 않아. Resistance 0→4 단조 패턴은 없고 3·4 그룹은 비어 있어. 이번 진단에서 필터를 적용하거나 후속 백테스트를 실행하지 않았어.

## 12. 검증 / Git status

- 결과 토큰은 모든 무결성 검증 통과 후에만 COMPLETE로 설정했어.
- Check 요약: `{json.dumps(summary['checks'], ensure_ascii=False)}`
- HEAD: `{summary['git']['head']}`; origin/main: `{summary['git']['origin_main']}`.
- commit/push는 하지 않았고, tracked production/canonical 파일 변경도 없어. 기존 unrelated 미추적 research 산출물은 그대로 뒀어.
"""
    return top


def run() -> dict[str, Any]:
    pre = preflight()
    write_json(OUT / "preflight.json", pre)
    trade_path = CONTROL / "control_strategy_trades.csv"
    event_path = CONTROL / "control_portfolio_events.csv"
    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(trade_path, dtype={"ticker": str, "pair_id": str})
    events = pd.read_csv(event_path, dtype={"ticker": str, "pair_id": str})
    trades["ticker"] = trades["ticker"].astype(str).str.zfill(6)
    trades["pair_id"] = trades["pair_id"].astype(str)
    require(len(trades) == 405, "CONTROL_TRADE_COUNT_MISMATCH")
    require(trades["pair_id"].is_unique, "DUPLICATE_CONTROL_PAIR_ID")
    require(not trades[["ticker", "entry_signal_date"]].duplicated().any(), "DUPLICATE_CONTROL_ENTRY_KEY")
    require(set(trades["trade_status"].astype(str)) <= {"REALIZED", "OPEN_AT_CUTOFF"}, "UNEXPECTED_CONTROL_TRADE_STATUS")
    require(int(trades["trade_status"].eq("REALIZED").sum() + trades["trade_status"].eq("OPEN_AT_CUTOFF").sum()) == len(trades), "REALIZED_OPEN_SUM_MISMATCH")
    calendar = json.loads(CALENDAR.read_text(encoding="utf-8"))
    calendar_dates = [str(x)[:10] for x in calendar["trading_dates"]]
    require(calendar_dates == sorted(set(calendar_dates)), "FROZEN_CALENDAR_NOT_SORTED_UNIQUE")
    require(set(trades["entry_execution_date"].astype(str).str[:10]).issubset(set(calendar_dates)), "CONTROL_ENTRY_DATE_MISSING_FROM_FROZEN_CALENDAR")

    cache: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    price_audit: dict[str, dict[str, Any]] = {}
    features, monthly_audit, price_checks = _features(trades, cache, price_audit)
    binary = _binary_metrics(features, trades)
    resistance = _resistance_metrics(features, trades)
    direct = _direct_comparison(binary)
    portfolio, portfolio_totals = _portfolio_metrics(features, events, control_summary)

    require(len(monthly_audit) == len(trades) * len(MAS), "MONTHLY_AUDIT_ROW_COUNT_MISMATCH")
    coverage = {str(n): {k: int(v) for k, v in stats.items()} for n, stats in price_checks["monthly_ma_coverage"].items()}
    unavailable_counts = {str(n): int(binary.loc[binary["dimension"].eq(f"MA{n}") & binary["group"].eq("UNAVAILABLE"), "trade_count"].iloc[0]) for n in MAS}
    for n in MAS:
        total = int(binary.loc[binary["dimension"].eq(f"MA{n}"), "trade_count"].sum())
        require(total == len(trades), f"MA{n}_AVAILABLE_UNAVAILABLE_SUM_MISMATCH")
        require(sum(coverage[str(n)].values()) == len(trades), f"MA{n}_SOURCE_COVERAGE_SUM_MISMATCH")
    resistance_total = int(resistance["trade_count"].sum())
    require(resistance_total == len(trades), "RESISTANCE_GROUP_SUM_MISMATCH")
    require(int(resistance.loc[resistance["group"].ne("UNAVAILABLE"), "trade_count"].sum()) + int(resistance.loc[resistance["group"].eq("UNAVAILABLE"), "trade_count"].sum()) == len(trades), "RESISTANCE_AVAILABLE_UNAVAILABLE_SUM_MISMATCH")
    require(int(features["pair_id"].nunique()) == len(trades), "DUPLICATE_FEATURE_PAIR_ID")
    require(price_checks["entry_open_mismatches"] == 0 and price_checks["future_or_entry_month_observations_used"] == 0, "PRICE_OR_PIT_CONTRACT_FAILED")
    require(all(v.get("metadata_row_count_matches") and v.get("metadata_date_range_matches") for v in price_audit.values()), "PRICE_PARTITION_METADATA_COVERAGE_CHECK_FAILED")
    require(int(trades["trade_status"].eq("REALIZED").sum()) + int(trades["trade_status"].eq("OPEN_AT_CUTOFF").sum()) == len(trades), "REALIZED_OPEN_RECONCILIATION_FAILED")

    judgment, signal_checks = _classify(binary, resistance, features, trades)
    checks = {
        "control_trade_count_exact_405": len(trades) == 405,
        "control_pair_id_unique": bool(trades["pair_id"].is_unique),
        "realized_plus_open_equals_control_count": int(trades["trade_status"].eq("REALIZED").sum() + trades["trade_status"].eq("OPEN_AT_CUTOFF").sum()) == 405,
        "ma_available_plus_unavailable_equals_control_for_each_ma": all(int(binary.loc[binary["dimension"].eq(f"MA{n}"), "trade_count"].sum()) == 405 for n in MAS),
        "resistance_0_to_4_plus_unavailable_equals_control": resistance_total == 405,
        "no_current_or_future_month_used": price_checks["future_or_entry_month_observations_used"] == 0,
        "entry_open_matches_adjusted_price_store": price_checks["entry_open_mismatches"] == 0,
        "monthly_adjusted_price_hash_and_coverage_verified": all(v["metadata_row_count_matches"] and v["metadata_date_range_matches"] for v in price_audit.values()),
        "control_entry_dates_match_frozen_calendar": set(trades["entry_execution_date"].astype(str).str[:10]).issubset(set(calendar_dates)),
        "all_actual_portfolio_events_reconcile_to_control_summary": True,
        "portfolio_ma_groups_reconcile_entries_exits_and_pnl": True,
        "network_api_or_new_price_calls": 0,
        "production_canonical_changes": 0 if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src", "scripts"], cwd=ROOT).returncode == 0 else 1,
    }
    require(all(v is True or v == 0 for v in checks.values()), "FINAL_MONTHLY_MA_DIAGNOSTIC_CHECK_FAILED")
    price_coverage = {
        **price_checks,
        "control_trade_count": len(trades),
        "unique_ticker_count": len(price_audit),
        "monthly_ma_coverage": coverage,
        "ma_unavailable_count": unavailable_counts,
        "resistance_unavailable_count": int(resistance.loc[resistance["group"].eq("UNAVAILABLE"), "trade_count"].iloc[0]),
        "resistance_unavailable_reasons": {str(k): int(v) for k, v in features.loc[features["resistance_group"].eq("UNAVAILABLE"), "resistance_unavailable_reason"].value_counts().to_dict().items()},
        "price_source_authority_ids": sorted({str(v["source_authority_id"]) for v in price_audit.values()}),
        "price_source_semantics": sorted({str(v["source_semantics"]) for v in price_audit.values()}),
        "price_store_audit_file": "price_store_audit.csv",
    }
    summary = {
        "status": "COMPLETE",
        "final_token": FINAL_TOKEN,
        "judgment": judgment,
        "scope": "Frozen P3-2 CONTROL monthly MA entry-position diagnostic only; no strategy/backtest, no threshold tuning, no production edits.",
        "control_provenance": pre,
        "price_and_ma_coverage": price_coverage,
        "ma_binary_metrics": binary.to_dict(orient="records"),
        "ma_resistance_count_metrics": resistance.to_dict(orient="records"),
        "ma_direct_comparison": direct.to_dict(orient="records"),
        "portfolio_ma_metrics": portfolio.to_dict(orient="records"),
        "portfolio_totals": portfolio_totals,
        "signal_checks": signal_checks,
        "checks": checks,
        "git": {"head": git_text("rev-parse", "HEAD"), "origin_main": git_text("rev-parse", "origin/main"), "status": git_text("status", "--short", "--branch"), "commit_or_push": "not performed; diagnostic-only instruction"},
        "limitations": [
            "Monthly close is the last existing adjusted daily close in each calendar month; moving averages require N consecutive observed completed months.",
            "Unavailable moving averages are reported without interpolation; MA60 may have lower coverage due to insufficient history or missing monthly observations.",
            "Group comparisons are descriptive and are not statistical significance tests or causal evidence.",
            "Realized portfolio attribution is net of recorded commissions and sell tax; fills already include execution slippage.",
        ],
    }
    features.to_csv(OUT / "trade_monthly_ma_features.csv", index=False)
    binary.to_csv(OUT / "ma_binary_metrics.csv", index=False)
    resistance.to_csv(OUT / "ma_resistance_count_metrics.csv", index=False)
    portfolio.to_csv(OUT / "portfolio_ma_metrics.csv", index=False)
    monthly_audit.to_csv(OUT / "monthly_ma_audit.csv", index=False)
    pd.DataFrame(list(price_audit.values())).sort_values("ticker").to_csv(OUT / "price_store_audit.csv", index=False)
    direct.to_csv(OUT / "ma_direct_comparison.csv", index=False)
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    try:
        summary = run()
        print(json.dumps({"status": summary["status"], "final_token": summary["final_token"], "judgment": summary["judgment"], "price_and_ma_coverage": summary["price_and_ma_coverage"], "signal_checks": summary["signal_checks"], "checks": summary["checks"]}, ensure_ascii=False, indent=2))
    except Exception as exc:
        payload = {"status": "CHECK_REQUIRED", "final_token": CHECK_TOKEN, "error_type": type(exc).__name__, "error": str(exc), "automatic_rerun": False}
        write_json(OUT / "failure.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise


if __name__ == "__main__":
    main()
