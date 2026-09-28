#!/usr/bin/env python3
"""Valuation-only MDD closure for the frozen Pattern B V03 portfolio outputs.

This script does not generate signals, replay orders, or modify the V03 source
artifact. It revalues only the positions implied by the already-executed V03
events and applies the approved suspension carry rule to the five exact
identities listed below.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


V03_REL = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v03"
)
V03_REFERENCE_COMMIT = "c5502f64e985cdd07d6d307e9ffcac2214ec9fa8"
DIAGNOSTIC_REL = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v02_gap_diagnostic_v01/"
    "identity_classification.csv"
)
PIT_REL = Path("data/market/rolling_authority/merged_pit_intervals.json")
CALENDAR_REL = Path("data/market/rolling_authority/merged_trading_calendar.json")
ADJUSTED_REL = Path("data/market/adjusted/stocks")
RAW_REL = Path("data/market/raw/krx_stocks/v01")
OUTPUT_REL = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v03_mdd_closure_v01"
)

APPROVED_IDENTITIES = {
    ("019490", "KR7019490002"),
    ("019570", "KR7019570001"),
    ("066790", "KR7066790007"),
    ("083660", "KR7083660001"),
    ("103230", "KR7103230009"),
}
WINDOWS = {
    "p1": "P1",
    "p2_1": "P2-1",
    "p2_2": "P2-2",
    "p3_1": "P3-1",
    "p3_2": "P3-2",
}
ABSOLUTE_MDD_LIMITS = {
    "P1": -55.0,
    "P2-1": -40.0,
    "P2-2": -40.0,
    "P3-1": -40.0,
    "P3-2": -40.0,
}
RELATIVE_MDD_LIMIT_PP = 5.0
MIN_OBSERVED_COVERAGE = 90.0
EXPECTED_COVERAGE = {
    "P1": 95.27,
    "P2-1": 98.71,
    "P2-2": 92.65,
    "P3-1": 98.44,
    "P3-2": 91.13,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null"}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def normalize_ticker(value: Any) -> str:
    return str(value).strip().zfill(6)


def normalize_isu(value: Any) -> str:
    return str(value).strip().upper()


def raw_candle_is_normal(row: dict[str, Any] | pd.Series | None) -> bool:
    """True only for a normal, traded KRX row, never a suspension placeholder."""
    if row is None:
        return False
    values = {key: number(row.get(key)) for key in ("open", "high", "low", "close", "volume", "trading_value")}
    if any(value is None for value in values.values()):
        return False
    if any(values[key] <= 0 for key in ("open", "high", "low", "close", "volume", "trading_value")):
        return False
    return (
        values["high"] >= max(values["open"], values["low"], values["close"])
        and values["low"] <= min(values["open"], values["high"], values["close"])
    )


def load_candidate_dates() -> dict[tuple[str, str], list[str]]:
    path = ROOT / DIAGNOSTIC_REL
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["isu_cd"] = frame["isu_cd"].map(normalize_isu)
    rows = {(row.ticker, row.isu_cd): row for row in frame.itertuples(index=False)}
    if set(rows) & APPROVED_IDENTITIES != APPROVED_IDENTITIES:
        raise RuntimeError("The diagnostic does not contain exactly the five approved identities")
    result: dict[tuple[str, str], list[str]] = {}
    for identity in sorted(APPROVED_IDENTITIES):
        row = rows[identity]
        if row.classification != "APPROVED_SUSPENSION_CARRY_CANDIDATE":
            raise RuntimeError(f"Diagnostic classification mismatch: {identity}")
        dates = sorted({value for value in row.carry_candidate_dates.split(";") if value})
        if len(dates) != int(row.carry_candidate_unique_dates):
            raise RuntimeError(f"Diagnostic carry-date count mismatch: {identity}")
        if not dates:
            raise RuntimeError(f"No approved carry dates: {identity}")
        result[identity] = dates
    return result


def load_pit_intervals() -> dict[tuple[str, str], dict[str, Any]]:
    raw = load_json(ROOT / PIT_REL)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for identity in APPROVED_IDENTITIES:
        matches = []
        for value in raw.get("intervals", []):
            if (
                normalize_ticker(value.get("ticker")) == identity[0]
                and normalize_isu(value.get("isu_cd")) == identity[1]
                and value.get("state") == "COMMON"
            ):
                matches.append(dict(value))
        if len(matches) != 1:
            raise RuntimeError(f"Expected one exact PIT COMMON interval for {identity}; got {len(matches)}")
        result[identity] = matches[0]
    return result


def make_raw_row_loader(
    raw_store: KrxRawStockStore,
    expected_rows: dict[tuple[str, str], set[str]],
) -> tuple[Any, dict[tuple[str, str, str], dict[str, Any] | None], dict[str, Any]]:
    row_cache: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    loaded_tickers: dict[tuple[str, str], set[str]] = defaultdict(set)
    partition_rows: dict[tuple[str, str], dict[str, dict[str, Any] | None]] = defaultdict(dict)
    manifests: dict[str, Any] = {}

    def get_raw_row(market: str, day: str, ticker: str) -> dict[str, Any] | None:
        partition_key = (market, day)
        row_key = (market, day, ticker)
        if row_key in row_cache:
            return row_cache[row_key]
        wanted = set(expected_rows.get(partition_key, set())) | {ticker}
        missing_wanted = wanted - loaded_tickers[partition_key]
        if missing_wanted:
            manifest = raw_store.get_manifest(market, day)
            if manifest is None or manifest.get("status") != "COMPLETE":
                raise RuntimeError(f"No complete exact KRX raw partition for {market} {day}")
            snapshot = raw_store.load_snapshot(market, day)
            normalized_tickers = snapshot["ticker"].astype(str).map(normalize_ticker)
            for wanted_ticker in sorted(missing_wanted):
                matches = snapshot.loc[normalized_tickers == wanted_ticker]
                if len(matches) > 1:
                    raise RuntimeError(f"Duplicate KRX ticker rows: {market} {day} {wanted_ticker}")
                if matches.empty:
                    row = None
                else:
                    row = {column: matches.iloc[0][column] for column in snapshot.columns}
                partition_rows[partition_key][wanted_ticker] = row
                row_cache[(market, day, wanted_ticker)] = row
                loaded_tickers[partition_key].add(wanted_ticker)
            if f"{market}/{day}" not in manifests:
                manifests[f"{market}/{day}"] = {
                    "market": market,
                    "date": day,
                    "status": manifest.get("status"),
                    "file_path": manifest.get("file_path"),
                    "file_sha256": manifest.get("file_sha256"),
                    "content_sha256": manifest.get("content_sha256"),
                }
        return partition_rows[partition_key].get(ticker)

    return get_raw_row, row_cache, manifests


def validate_carry_sources(
    candidates: dict[tuple[str, str], list[str]],
    intervals: dict[tuple[str, str], dict[str, Any]],
    calendar: list[str],
    get_raw_row: Any,
    adjusted_store: AdjustedPriceStore,
) -> tuple[dict[tuple[str, str], dict[str, dict[str, Any]]], dict[str, pd.DataFrame], list[dict[str, Any]]]:
    calendar_set = set(calendar)
    calendar_position = {day: index for index, day in enumerate(calendar)}
    adjusted_frames: dict[str, pd.DataFrame] = {}
    validated: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    validation_rows: list[dict[str, Any]] = []

    for identity in sorted(APPROVED_IDENTITIES):
        ticker, isu_cd = identity
        interval = intervals[identity]
        market = str(interval["market"]).upper()
        interval_start = str(interval["effective_from"])[:10]
        interval_end = str(interval["effective_to"])[:10]
        adjusted = adjusted_store.load_daily_source(ticker)
        adjusted_frames[ticker] = adjusted

        def adjusted_normal_close(day: str) -> float | None:
            stamp = pd.Timestamp(day)
            if stamp not in adjusted.index:
                return None
            row = adjusted.loc[stamp]
            if isinstance(row, pd.DataFrame):
                raise RuntimeError(f"Duplicate adjusted rows: {ticker} {day}")
            values = [number(row.get(field)) for field in ("open", "high", "low", "close")]
            if any(value is None or value <= 0 for value in values):
                return None
            return float(values[3])

        def last_normal_adjusted_before(day: str) -> tuple[str, float, dict[str, Any]]:
            if day not in calendar_position:
                raise RuntimeError(f"Carry date is not in merged KRX trading calendar: {day}")
            index = calendar_position[day] - 1
            minimum = bisect.bisect_left(calendar, interval_start)
            while index >= minimum:
                prior_day = calendar[index]
                if prior_day > interval_end:
                    index -= 1
                    continue
                raw_row = get_raw_row(market, prior_day, ticker)
                adjusted_close = adjusted_normal_close(prior_day)
                if raw_candle_is_normal(raw_row) and adjusted_close is not None:
                    return prior_day, adjusted_close, raw_row
                index -= 1
            raise RuntimeError(f"No prior normal exact adjusted close for {identity} before {day}")

        identity_validated: dict[str, dict[str, Any]] = {}
        for day in candidates[identity]:
            if day not in calendar_set:
                raise RuntimeError(f"Approved carry date is not a merged KRX session: {identity} {day}")
            if not interval_start <= day <= interval_end:
                raise RuntimeError(f"PIT boundary violation: {identity} {day}")
            raw_row = get_raw_row(market, day, ticker)
            if raw_row is None:
                raise RuntimeError(f"Approved carry date has no exact raw ticker row: {identity} {day}")
            raw_values = {field: number(raw_row.get(field)) for field in ("open", "high", "low", "close", "volume", "trading_value")}
            if not (
                raw_values["open"] == 0
                and raw_values["high"] == 0
                and raw_values["low"] == 0
                and raw_values["close"] is not None
                and raw_values["close"] > 0
                and raw_values["volume"] == 0
                and raw_values["trading_value"] == 0
            ):
                raise RuntimeError(f"Raw KRX suspension placeholder predicate failed: {identity} {day} {raw_values}")
            prior_day, prior_close, prior_raw = last_normal_adjusted_before(day)
            adjusted_on_candidate = adjusted_normal_close(day)
            validated_row = {
                "ticker": ticker,
                "isu_cd": isu_cd,
                "valuation_date": day,
                "source_status": "APPROVED_SUSPENSION_RAW_PLACEHOLDER_VALID",
                "market": market,
                "pit_effective_from": interval_start,
                "pit_effective_to": interval_end,
                "raw_open": raw_values["open"],
                "raw_high": raw_values["high"],
                "raw_low": raw_values["low"],
                "raw_close": raw_values["close"],
                "raw_volume": raw_values["volume"],
                "raw_trading_value": raw_values["trading_value"],
                "adjusted_source_row_on_candidate_date": adjusted_on_candidate is not None,
                "used_price_date": prior_day,
                "used_price": prior_close,
                "prior_normal_raw_volume": number(prior_raw.get("volume")),
                "prior_normal_raw_trading_value": number(prior_raw.get("trading_value")),
                "used_for_execution": False,
            }
            identity_validated[day] = validated_row
            validation_rows.append(validated_row)
        validated[identity] = identity_validated

    total_expected = sum(len(days) for days in candidates.values())
    if len(validation_rows) != total_expected:
        raise RuntimeError(f"Carry source validation count mismatch: {len(validation_rows)} != {total_expected}")
    if len({(row["ticker"], row["isu_cd"], row["valuation_date"]) for row in validation_rows}) != total_expected:
        raise RuntimeError("Duplicate approved carry identity/date evidence")
    return validated, adjusted_frames, validation_rows


def load_adjusted_frame(ticker: str, store: AdjustedPriceStore, cache: dict[str, pd.DataFrame | None]) -> pd.DataFrame | None:
    if ticker not in cache:
        try:
            cache[ticker] = store.load_daily_source(ticker)
        except FileNotFoundError:
            cache[ticker] = None
    return cache[ticker]


def event_positions(events: pd.DataFrame) -> list[dict[str, Any]]:
    executed = events.loc[events["event_status"] == "EXECUTED"].copy()
    positions: list[dict[str, Any]] = []
    for pair_id, group in executed.groupby("pair_id", sort=True):
        entries = group.loc[group["event_type"] == "ENTRY"]
        exits = group.loc[group["event_type"] == "EXIT"]
        if len(entries) != 1 or len(exits) > 1:
            raise RuntimeError(f"Executed event lifecycle is not one entry/at most one exit: {pair_id}")
        entry = entries.iloc[0]
        exit_date = str(exits.iloc[0]["execution_date"])[:10] if len(exits) else None
        if exit_date is not None and exit_date < str(entry["execution_date"])[:10]:
            raise RuntimeError(f"Exit predates entry: {pair_id}")
        tickers = {normalize_ticker(value) for value in group["ticker"].unique()}
        identities = {normalize_isu(value) for value in group["isu_cd"].unique()}
        if len(tickers) != 1 or len(identities) != 1:
            raise RuntimeError(f"Ticker or exact identity changed within executed position: {pair_id}")
        shares = number(entry["shares"])
        if shares is None or shares <= 0:
            raise RuntimeError(f"Invalid entry shares: {pair_id}")
        positions.append({
            "pair_id": str(pair_id),
            "ticker": next(iter(tickers)),
            "isu_cd": next(iter(identities)),
            "market": str(entry["market"]).upper(),
            "entry_date": str(entry["execution_date"])[:10],
            "exit_date": exit_date,
            "shares": float(shares),
        })
    return positions


def calculate_mdd(rows: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    valid = [(str(row["date"]), float(row["equity"])) for row in rows if row["equity"] is not None]
    if not valid:
        return {"mdd_pct": None, "peak_date": None, "trough_date": None, "recovery_date": None, "recovered": False}
    peak_value = float(initial_capital)
    peak_date = valid[0][0]
    worst = 0.0
    worst_peak_value = peak_value
    worst_peak_date = peak_date
    worst_trough_date: str | None = None
    recovery_date: str | None = None
    for day, equity in valid:
        if equity >= peak_value:
            peak_value = equity
            peak_date = day
        drawdown = (equity / peak_value - 1.0) * 100.0 if peak_value else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak_value = peak_value
            worst_peak_date = peak_date
            worst_trough_date = day
            recovery_date = None
        elif (
            worst_trough_date is not None
            and day > worst_trough_date
            and equity >= worst_peak_value
            and recovery_date is None
        ):
            recovery_date = day
    return {
        "mdd_pct": worst if worst_trough_date is not None else 0.0,
        "peak_date": worst_peak_date,
        "trough_date": worst_trough_date,
        "recovery_date": recovery_date,
        "recovered": recovery_date is not None,
    }


def aggregate_gate_status(statuses: list[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "CHECK_REQUIRED" in statuses:
        return "CHECK_REQUIRED"
    return "PASS"


def unresolved_spans_for_window(
    window_id: str,
    dates: list[str],
    unresolved_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    date_position = {day: index for index, day in enumerate(dates)}
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in unresolved_rows:
        if row["window"] == window_id:
            grouped[(row["pair_id"], row["ticker"], row["isu_cd"])].append(row["valuation_date"])
    spans: list[dict[str, Any]] = []
    for (pair_id, ticker, isu_cd), missing_dates in grouped.items():
        positions = sorted(date_position[day] for day in set(missing_dates))
        if not positions:
            continue
        first = previous = positions[0]
        length = 1
        for current in positions[1:]:
            if current == previous + 1:
                previous = current
                length += 1
                continue
            spans.append({
                "window": window_id,
                "ticker": ticker,
                "isu_cd": isu_cd,
                "pair_id": pair_id,
                "start_date": dates[first],
                "end_date": dates[previous],
                "consecutive_missing_sessions": length,
            })
            first = previous = current
            length = 1
        spans.append({
            "window": window_id,
            "ticker": ticker,
            "isu_cd": isu_cd,
            "pair_id": pair_id,
            "start_date": dates[first],
            "end_date": dates[previous],
            "consecutive_missing_sessions": length,
        })
    return spans


def main() -> None:
    v03_root = ROOT / V03_REL
    output = ROOT / OUTPUT_REL
    output.mkdir(parents=True, exist_ok=True)
    v03_summary_path = v03_root / "summary.json"
    v03_summary = load_json(v03_summary_path)
    if v03_summary.get("verdict") != "HOLD":
        raise RuntimeError(f"Frozen V03 original verdict is not HOLD: {v03_summary.get('verdict')}")

    candidate_dates = load_candidate_dates()
    pit_intervals = load_pit_intervals()
    calendar_obj = load_json(ROOT / CALENDAR_REL)
    trading_calendar = [str(value)[:10] for value in calendar_obj.get("trading_dates", [])]
    if trading_calendar != sorted(set(trading_calendar)):
        raise RuntimeError("Merged KRX trading calendar is not sorted and unique")

    adjusted_store = AdjustedPriceStore(ROOT / ADJUSTED_REL)
    raw_store = KrxRawStockStore(ROOT / RAW_REL)
    expected_raw_rows: dict[tuple[str, str], set[str]] = defaultdict(set)
    for identity, dates in candidate_dates.items():
        market = str(pit_intervals[identity]["market"]).upper()
        for day in dates:
            expected_raw_rows[(market, day)].add(identity[0])
    get_raw_row, raw_cache, raw_manifest_hashes = make_raw_row_loader(raw_store, expected_raw_rows)
    carry_prices, adjusted_cache, carry_source_rows = validate_carry_sources(
        candidate_dates, pit_intervals, trading_calendar, get_raw_row, adjusted_store
    )

    baseline_hashes: dict[str, str] = {}
    baseline_hashes[str(v03_summary_path.relative_to(ROOT))] = sha256_file(v03_summary_path)
    daily_rows_out: list[dict[str, Any]] = []
    carry_audit: list[dict[str, Any]] = []
    unresolved_audit: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    unresolved_spans: list[dict[str, Any]] = []
    window_results: dict[str, Any] = {}
    adjusted_frames: dict[str, pd.DataFrame | None] = dict(adjusted_cache)
    cash_path_hashes: dict[str, str] = {}

    for short_name, window_id in WINDOWS.items():
        window_dir = v03_root / short_name
        paths = {
            "daily_equity": window_dir / "daily_equity.csv",
            "portfolio_events": window_dir / "portfolio_events.csv",
            "valuation_audit": window_dir / "valuation_audit.csv",
            "portfolio_metrics": window_dir / "portfolio_metrics.json",
            "valuation_coverage": window_dir / "valuation_coverage.json",
            "official_adoption_gates": window_dir / "official_adoption_gates.json",
            "input_audit": window_dir / "input_audit.json",
            "cost_audit_summary": window_dir / "cost_audit_summary.json",
            "cash_audit": window_dir / "cash_audit.csv",
            "execution_contract": window_dir / "execution_contract.json",
            "v2_reference": window_dir / "v2_reference.json",
        }
        for name, path in paths.items():
            if not path.exists():
                raise RuntimeError(f"Missing frozen V03 {name}: {path}")
            baseline_hashes[str(path.relative_to(ROOT))] = sha256_file(path)

        metrics = load_json(paths["portfolio_metrics"])
        base_gates_obj = load_json(paths["official_adoption_gates"])
        base_gates = base_gates_obj.get("gates", {})
        input_audit = load_json(paths["input_audit"])
        cost_audit = load_json(paths["cost_audit_summary"])
        contract = load_json(paths["execution_contract"])
        v2_ref = load_json(paths["v2_reference"])
        v2_mdd = number(v2_ref.get("mdd_pct"))
        effective_end = str(metrics["effective_end"])[:10]
        initial_capital = float(metrics["initial_capital_krw"])
        contract_window = contract.get("window", {})
        if contract_window.get("window_id") != window_id or str(contract_window.get("effective_end", ""))[:10] != effective_end:
            raise RuntimeError(f"V03 execution-contract boundary mismatch: {window_id}")

        # These PASS results are frozen from the original portfolio run; if any
        # prerequisite is not clean, do not present a valuation closure as final.
        if [base_gates.get(key) for key in ("A", "B", "C")] != ["PASS", "PASS", "PASS"]:
            raise RuntimeError(f"Frozen V03 A/B/C gates are not all PASS: {window_id} {base_gates}")
        if metrics.get("cash_conservation_pass") is not True:
            raise RuntimeError(f"Frozen V03 cash conservation is not PASS: {window_id}")
        if int(metrics.get("unresolved_execution_event_count", -1)) != 0:
            raise RuntimeError(f"Frozen V03 unresolved execution count is nonzero: {window_id}")
        if int(input_audit.get("exclusion_leakage_count", -1)) != 0 or input_audit.get("exclusion_leakage_zero") is not True:
            raise RuntimeError(f"Frozen V03 exclusion leakage check failed: {window_id}")
        if int(cost_audit.get("mismatch_count", -1)) != 0 or cost_audit.get("coverage_complete") is not True:
            raise RuntimeError(f"Frozen V03 cost audit failed: {window_id}")
        price_audit = input_audit.get("execution_price_audit", {})
        for key in (
            "missing_exact_opens",
            "price_mismatch_count",
            "next_session_execution_violation_count",
            "terminal_unresolved_source_count",
        ):
            if int(price_audit.get(key, 0) or 0) != 0:
                raise RuntimeError(f"Frozen V03 execution price audit failed: {window_id} {key}")
        if v2_mdd is None:
            raise RuntimeError(f"Missing frozen V2 MDD reference: {window_id}")

        daily = pd.read_csv(paths["daily_equity"], dtype=str, keep_default_na=False)
        events = pd.read_csv(paths["portfolio_events"], dtype=str, keep_default_na=False)
        valuation_audit = pd.read_csv(paths["valuation_audit"], dtype=str, keep_default_na=False)
        positions = event_positions(events)
        frozen_unresolved_marks = {
            (str(row["pair_id"]), str(row["valuation_date"])[:10])
            for _, row in valuation_audit.iterrows()
            if row["status"] == "UNRESOLVED_MISSING_EXACT_DAILY_CLOSE"
        }
        base_dates = [str(value)[:10] for value in daily["date"].tolist()]
        if base_dates != sorted(set(base_dates)):
            raise RuntimeError(f"V03 daily equity dates are duplicated or unordered: {window_id}")
        daily = daily.assign(_date=daily["date"].map(lambda value: str(value)[:10]))
        effective_daily = daily.loc[daily["_date"] <= effective_end].copy()
        dates = effective_daily["_date"].tolist()
        if not dates:
            raise RuntimeError(f"No daily portfolio valuations through effective end: {window_id}")

        # Keep the source cash and pending proceeds path byte-for-value stable.
        cash_source_rows = [
            (row["_date"], number(row["cash"]), number(row["pending_sale_proceeds"]))
            for _, row in effective_daily.iterrows()
        ]
        cash_path_payload = json.dumps(cash_source_rows, separators=(",", ":"), ensure_ascii=False)
        cash_path_hashes[window_id] = hashlib.sha256(cash_path_payload.encode("utf-8")).hexdigest()

        # The original daily open-position count is the reconciliation control
        # for the frozen executed entry/exit ledger.
        rows_by_date: dict[str, dict[str, Any]] = {}
        for _, source in effective_daily.iterrows():
            day = source["_date"]
            rows_by_date[day] = {
                "date": day,
                "cash": number(source["cash"]),
                "pending_sale_proceeds": number(source["pending_sale_proceeds"]),
                "baseline_equity": number(source["equity"]),
                "baseline_valuation_valid": truth(source["valuation_valid"]),
                "baseline_open_positions": int(float(source["open_positions"])),
            }

        # Ensure every frozen executed trade position that can be valued has
        # a source adjusted-price frame. Frames are cached across all windows.
        for ticker in sorted({row["ticker"] for row in positions}):
            load_adjusted_frame(ticker, adjusted_store, adjusted_frames)

        closure_rows: list[dict[str, Any]] = []
        for day in dates:
            source = rows_by_date[day]
            cash = source["cash"]
            pending = source["pending_sale_proceeds"]
            if cash is None or pending is None:
                raise RuntimeError(f"Frozen cash path has a missing value: {window_id} {day}")
            open_positions = [
                position for position in positions
                if position["entry_date"] <= day and (position["exit_date"] is None or day < position["exit_date"])
            ]
            if len(open_positions) != source["baseline_open_positions"]:
                raise RuntimeError(
                    f"Executed position count mismatch: {window_id} {day} "
                    f"{len(open_positions)} != {source['baseline_open_positions']}"
                )

            invested = 0.0
            mark_ok = True
            for position in open_positions:
                identity = (position["ticker"], position["isu_cd"])
                approved_day = carry_prices.get(identity, {}).get(day)
                if approved_day is not None:
                    price = float(approved_day["used_price"])
                    carry_audit.append({
                        "window": window_id,
                        "ticker": position["ticker"],
                        "isu_cd": position["isu_cd"],
                        "valuation_date": day,
                        "source_status": "APPROVED_SUSPENSION_CARRY_APPLIED",
                        "used_price_date": approved_day["used_price_date"],
                        "used_price": price,
                        "carry_reason": "Exact PIT identity; raw KRX OHLC=0 with positive close and zero volume/value; prior normal adjusted close.",
                        "used_for_execution": False,
                        "pair_id": position["pair_id"],
                        "shares": position["shares"],
                        "raw_open": approved_day["raw_open"],
                        "raw_high": approved_day["raw_high"],
                        "raw_low": approved_day["raw_low"],
                        "raw_close": approved_day["raw_close"],
                        "raw_volume": approved_day["raw_volume"],
                        "raw_trading_value": approved_day["raw_trading_value"],
                        "market": approved_day["market"],
                        "pit_effective_from": approved_day["pit_effective_from"],
                        "pit_effective_to": approved_day["pit_effective_to"],
                    })
                elif (position["pair_id"], day) in frozen_unresolved_marks:
                    # The frozen V03 audit is the boundary for exact marks.
                    # Do not turn a residual gap into an unapproved adjustment-
                    # source fill, even if that source exposes a repeated value.
                    price = None
                else:
                    frame = adjusted_frames.get(position["ticker"])
                    stamp = pd.Timestamp(day)
                    if frame is None or stamp not in frame.index:
                        price = None
                    else:
                        mark = frame.loc[stamp]
                        if isinstance(mark, pd.DataFrame):
                            raise RuntimeError(f"Duplicate adjusted mark: {window_id} {position['ticker']} {day}")
                        ohlc = [number(mark.get(field)) for field in ("open", "high", "low", "close")]
                        price = float(ohlc[3]) if all(value is not None and value > 0 for value in ohlc) else None
                if price is None:
                    mark_ok = False
                    unresolved_audit.append({
                        "window": window_id,
                        "valuation_date": day,
                        "ticker": position["ticker"],
                        "isu_cd": position["isu_cd"],
                        "pair_id": position["pair_id"],
                        "reason": (
                            "FROZEN_V03_UNRESOLVED_MARK_NOT_APPROVED_FOR_CARRY"
                            if (position["pair_id"], day) in frozen_unresolved_marks
                            else "NO_EXACT_ADJUSTED_CLOSE_AND_NOT_AN_APPROVED_CARRY_DATE"
                        ),
                    })
                else:
                    invested += position["shares"] * price

            equity = cash + pending + invested if mark_ok else None
            if source["baseline_valuation_valid"]:
                baseline_equity = source["baseline_equity"]
                if equity is None or baseline_equity is None or not math.isclose(equity, baseline_equity, rel_tol=0.0, abs_tol=0.01):
                    raise RuntimeError(
                        f"Frozen V03 valid-equity parity failed: {window_id} {day} "
                        f"closure={equity} baseline={baseline_equity}"
                    )
            closure_rows.append({
                "window": window_id,
                "date": day,
                "cash": cash,
                "pending_sale_proceeds": pending,
                "invested_market_value": invested if mark_ok else None,
                "equity": equity,
                "open_positions": len(open_positions),
                "valuation_valid": bool(mark_ok),
            })

        total_days = len(closure_rows)
        observed_days = sum(row["valuation_valid"] for row in closure_rows)
        missing_days = total_days - observed_days
        coverage_pct = 100.0 * observed_days / total_days if total_days else 0.0
        expected_coverage = EXPECTED_COVERAGE[window_id]
        if abs(coverage_pct - expected_coverage) > 0.1:
            raise RuntimeError(
                f"Coverage sanity check outside 0.1 percentage point: {window_id} "
                f"{coverage_pct} vs {expected_coverage}"
            )
        mdd = calculate_mdd(closure_rows, initial_capital)
        if missing_days == 0:
            mdd_type = "EXACT"
        elif coverage_pct >= MIN_OBSERVED_COVERAGE:
            mdd_type = "OBSERVED"
        else:
            mdd_type = "OBSERVED_BELOW_90_COVERAGE"
        if coverage_pct >= MIN_OBSERVED_COVERAGE and mdd["mdd_pct"] is not None:
            relative_deterioration = v2_mdd - float(mdd["mdd_pct"])
            absolute_pass = float(mdd["mdd_pct"]) >= ABSOLUTE_MDD_LIMITS[window_id]
            relative_pass = relative_deterioration < RELATIVE_MDD_LIMIT_PP
            gate_d = "PASS" if absolute_pass and relative_pass else "FAIL"
        else:
            relative_deterioration = None
            absolute_pass = None
            relative_pass = None
            gate_d = "CHECK_REQUIRED"

        e_issues = []
        if coverage_pct < MIN_OBSERVED_COVERAGE:
            e_issues.append("VALUATION_COVERAGE_BELOW_90_PERCENT")
        if metrics.get("final_equity") is None:
            e_issues.append("TERMINAL_EQUITY_UNRESOLVED")
        if int(metrics.get("unresolved_execution_event_count", 0) or 0):
            e_issues.append("UNRESOLVED_EXECUTION_EVENT")
        if metrics.get("cumulative_return_pct") is None or metrics.get("CAGR_pct") is None:
            e_issues.append("RETURN_OR_CAGR_UNAVAILABLE")
        gate_e = "CHECK_REQUIRED" if e_issues else "PASS"
        gates = {"A": base_gates["A"], "B": base_gates["B"], "C": base_gates["C"], "D": gate_d, "E": gate_e}
        if len(gates) != 5:
            raise RuntimeError(f"Expected five adoption gates: {window_id}")

        window_carries = [row for row in carry_audit if row["window"] == window_id]
        unresolved_marks = [row for row in unresolved_audit if row["window"] == window_id]
        window_spans = unresolved_spans_for_window(window_id, dates, unresolved_marks)
        unresolved_spans.extend(window_spans)
        max_unresolved_run = max((row["consecutive_missing_sessions"] for row in window_spans), default=0)
        if max_unresolved_run > 20:
            raise RuntimeError(f"A remaining unapproved valuation gap exceeds 20 sessions: {window_id} {max_unresolved_run}")
        missing_dates = [row["date"] for row in closure_rows if not row["valuation_valid"]]
        check_row = {
            "window": window_id,
            "base_v03_verdict": "HOLD",
            "coverage_pct": coverage_pct,
            "total_days": total_days,
            "observed_days": observed_days,
            "missing_days": missing_days,
            "remaining_unresolved_marks": len(unresolved_marks),
            "remaining_unresolved_mark_spans": len(window_spans),
            "max_consecutive_unresolved_mark_sessions": max_unresolved_run,
            "carry_applied_marks": len(window_carries),
            "mdd_pct": mdd["mdd_pct"],
            "mdd_type": mdd_type,
            "mdd_peak_date": mdd["peak_date"],
            "mdd_trough_date": mdd["trough_date"],
            "mdd_recovery_date": mdd["recovery_date"],
            "mdd_recovered": mdd["recovered"],
            "v2_mdd_pct": v2_mdd,
            "relative_mdd_deterioration_pp": relative_deterioration,
            "absolute_mdd_limit_pct": ABSOLUTE_MDD_LIMITS[window_id],
            "absolute_mdd_pass": absolute_pass,
            "relative_mdd_pass": relative_pass,
            "total_return_pct_frozen": metrics.get("cumulative_return_pct"),
            "cagr_pct_frozen": metrics.get("CAGR_pct"),
            "ending_equity_krw_frozen": metrics.get("ending_equity_krw"),
            "gates": gates,
        }
        coverage_rows.append({key: value for key, value in check_row.items() if key not in {"base_v03_verdict", "gates"}})
        gate_rows.append({
            "window": window_id,
            **{f"gate_{key}": value for key, value in gates.items()},
            "coverage_pct": coverage_pct,
            "mdd_pct": mdd["mdd_pct"],
            "mdd_type": mdd_type,
            "v2_mdd_pct": v2_mdd,
            "relative_mdd_deterioration_pp": relative_deterioration,
            "absolute_mdd_pass": absolute_pass,
            "relative_mdd_pass": relative_pass,
            "unresolved_execution_event_count": metrics.get("unresolved_execution_event_count"),
            "cash_conservation_pass": metrics.get("cash_conservation_pass"),
            "exclusion_leakage_count": input_audit.get("exclusion_leakage_count"),
            "cost_audit_mismatch_count": cost_audit.get("mismatch_count"),
            "carry_applied_marks": len(window_carries),
            "remaining_unresolved_marks": len(unresolved_marks),
            "remaining_unresolved_mark_spans": len(window_spans),
            "max_consecutive_unresolved_mark_sessions": max_unresolved_run,
        })
        for row in closure_rows:
            row["mdd_type"] = mdd_type
            row["coverage_pct"] = coverage_pct
            daily_rows_out.append(row)

        window_results[window_id] = {
            **check_row,
            "missing_equity_dates": missing_dates,
            "portfolio_metrics_preserved": {
                "trade_count": metrics.get("trade_count"),
                "win_rate_pct": metrics.get("win_rate_pct"),
                "profit_krw": metrics.get("profit_krw"),
                "total_return_pct": metrics.get("cumulative_return_pct"),
                "CAGR_pct": metrics.get("CAGR_pct"),
                "ending_equity_krw": metrics.get("ending_equity_krw"),
                "final_equity_at_effective_close": metrics.get("final_equity_at_effective_close"),
                "cash_conservation_pass": metrics.get("cash_conservation_pass"),
                "unresolved_execution_event_count": metrics.get("unresolved_execution_event_count"),
            },
            "source_audits_preserved": {
                "base_gates_A_B_C": {key: base_gates[key] for key in ("A", "B", "C")},
                "exclusion_leakage_count": input_audit.get("exclusion_leakage_count"),
                "execution_price_audit": price_audit,
                "cost_audit": cost_audit,
            },
        }

    all_gate_statuses = {key: [row[f"gate_{key}"] for row in gate_rows] for key in "ABCDE"}
    aggregate_gates = {key: aggregate_gate_status(values) for key, values in all_gate_statuses.items()}
    if any(status == "FAIL" for status in aggregate_gates.values()):
        verdict = "NOT_ADOPTED"
    elif any(status == "CHECK_REQUIRED" for status in aggregate_gates.values()):
        verdict = "HOLD"
    else:
        verdict = "OFFICIAL_STRATEGY_ADOPTED"

    if any(row["used_for_execution"] is not False for row in carry_audit):
        raise RuntimeError("Carry execution usage must remain exactly false")
    if len(carry_source_rows) != sum(len(value) for value in candidate_dates.values()):
        raise RuntimeError("Approved candidate source-date coverage is incomplete")
    if len({row["window"] + row["date"] for row in daily_rows_out}) != len(daily_rows_out):
        raise RuntimeError("Duplicate closure daily equity row")

    # Keep the original V03 metrics and trade artifacts immutable.
    current_baseline_hashes = {path: sha256_file(ROOT / path) for path in baseline_hashes}
    if current_baseline_hashes != baseline_hashes:
        raise RuntimeError("A frozen V03 baseline file changed during valuation closure")
    if (ROOT / V03_REL / "report.md").exists():
        baseline_hashes[str((ROOT / V03_REL / "report.md").relative_to(ROOT))] = sha256_file(ROOT / V03_REL / "report.md")

    source_files = {
        **baseline_hashes,
        str(DIAGNOSTIC_REL): sha256_file(ROOT / DIAGNOSTIC_REL),
        str(PIT_REL): sha256_file(ROOT / PIT_REL),
        str(CALENDAR_REL): sha256_file(ROOT / CALENDAR_REL),
        str(RAW_REL / "manifest.sqlite3"): sha256_file(ROOT / RAW_REL / "manifest.sqlite3"),
        str(Path(__file__).resolve().relative_to(ROOT)): sha256_file(Path(__file__).resolve()),
    }
    adjusted_hashes: dict[str, dict[str, str]] = {}
    for ticker, frame in adjusted_frames.items():
        if frame is None:
            continue
        parquet = adjusted_store._parquet_path(ticker)
        metadata = adjusted_store._metadata_path(ticker)
        adjusted_hashes[ticker] = {
            str(parquet.relative_to(ROOT)): sha256_file(parquet),
            str(metadata.relative_to(ROOT)): sha256_file(metadata),
        }
        source_files.update(adjusted_hashes[ticker])
    subprocess.run(
        ["git", "cat-file", "-e", f"{V03_REFERENCE_COMMIT}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    source_hash_obj = {
        "schema": "pattern_b_v03_valuation_mdd_closure_source_hashes_v01",
        "v03_reference_commit": V03_REFERENCE_COMMIT,
        "v03_original_artifact": str(V03_REL),
        "diagnostic": str(DIAGNOSTIC_REL),
        "approved_identity_count": len(APPROVED_IDENTITIES),
        "approved_identity_date_count": sum(len(value) for value in candidate_dates.values()),
        "approved_identities": [
            {"ticker": ticker, "isu_cd": isu_cd, "candidate_date_count": len(candidate_dates[(ticker, isu_cd)])}
            for ticker, isu_cd in sorted(APPROVED_IDENTITIES)
        ],
        "raw_partition_count_validated": len(raw_manifest_hashes),
        "raw_partitions": [raw_manifest_hashes[key] for key in sorted(raw_manifest_hashes)],
        "adjusted_sources": adjusted_hashes,
        "files": dict(sorted(source_files.items())),
    }

    validation = {
        "schema": "pattern_b_v03_valuation_mdd_closure_validation_v01",
        "carry_identity_count": len(APPROVED_IDENTITIES),
        "carry_identity_date_count": len(carry_source_rows),
        "carry_identity_date_source_violations": 0,
        "pit_boundary_violations": 0,
        "raw_placeholder_predicate_violations": 0,
        "missing_prior_normal_adjusted_close": 0,
        "carry_used_for_execution_count": sum(bool(row["used_for_execution"]) for row in carry_audit),
        "signal_or_state_generation_performed": False,
        "entry_exit_or_terminal_execution_replayed": False,
        "full_backtest_replayed": False,
        "baseline_v03_valid_equity_parity": "PASS",
        "cash_and_pending_sale_path_preserved": "PASS",
        "cash_pending_path_sha256_by_window": cash_path_hashes,
        "position_count_parity": "PASS",
        "gate_abc_inherited_exactly": "PASS",
        "unresolved_execution_event_count_all_zero": all(row["unresolved_execution_event_count"] == 0 for row in gate_rows),
        "cash_conservation_all_pass": all(row["cash_conservation_pass"] is True for row in gate_rows),
        "exclusion_leakage_all_zero": all(row["exclusion_leakage_count"] == 0 for row in gate_rows),
        "execution_cost_mismatch_all_zero": all(row["cost_audit_mismatch_count"] == 0 for row in gate_rows),
        "execution_price_audit_mismatch_all_zero": True,
        "coverage_mdd_v2_relative_parity_tolerance_pp": 0.1,
        "coverage_expected_sanity_check": "PASS",
        "remaining_unresolved_mark_span_count": len(unresolved_spans),
        "remaining_max_consecutive_unresolved_mark_sessions": max(
            (row["consecutive_missing_sessions"] for row in unresolved_spans), default=0
        ),
        "remaining_unresolved_spans_within_20_sessions": all(
            row["consecutive_missing_sessions"] <= 20 for row in unresolved_spans
        ),
        "gate_rows": len(gate_rows),
        "gate_outcome_count": sum(len(row) for row in all_gate_statuses.values()),
        "worktree_v03_baseline_unchanged": True,
        "raw_repository_v2_read_initialization": "NOT_USED; exact KRX snapshots were individually hash-validated through KrxRawStockStore.",
    }
    if validation["gate_outcome_count"] != 25:
        raise RuntimeError("Expected exactly 25 A-E gate outcomes")

    write_csv(
        output / "carry_source_validation.csv",
        carry_source_rows,
        [
            "ticker", "isu_cd", "valuation_date", "source_status", "market",
            "pit_effective_from", "pit_effective_to", "raw_open", "raw_high", "raw_low",
            "raw_close", "raw_volume", "raw_trading_value", "adjusted_source_row_on_candidate_date",
            "used_price_date", "used_price", "prior_normal_raw_volume", "prior_normal_raw_trading_value",
            "used_for_execution",
        ],
    )
    write_csv(
        output / "carry_audit.csv",
        carry_audit,
        [
            "window", "ticker", "isu_cd", "valuation_date", "source_status", "used_price_date",
            "used_price", "carry_reason", "used_for_execution", "pair_id", "shares", "raw_open",
            "raw_high", "raw_low", "raw_close", "raw_volume", "raw_trading_value", "market",
            "pit_effective_from", "pit_effective_to",
        ],
    )
    write_csv(
        output / "unresolved_valuation_gaps.csv",
        unresolved_audit,
        ["window", "valuation_date", "ticker", "isu_cd", "pair_id", "reason"],
    )
    write_csv(
        output / "unresolved_gap_spans.csv",
        unresolved_spans,
        ["window", "ticker", "isu_cd", "pair_id", "start_date", "end_date", "consecutive_missing_sessions"],
    )
    write_csv(
        output / "daily_equity_closure.csv",
        daily_rows_out,
        [
            "window", "date", "cash", "pending_sale_proceeds", "invested_market_value", "equity",
            "open_positions", "valuation_valid", "mdd_type", "coverage_pct",
        ],
    )
    write_csv(
        output / "valuation_coverage.csv",
        coverage_rows,
        [
            "window", "coverage_pct", "total_days", "observed_days", "missing_days",
            "remaining_unresolved_marks", "carry_applied_marks", "mdd_pct", "mdd_type",
            "remaining_unresolved_mark_spans", "max_consecutive_unresolved_mark_sessions",
            "mdd_peak_date", "mdd_trough_date", "mdd_recovery_date", "mdd_recovered", "v2_mdd_pct",
            "relative_mdd_deterioration_pp", "absolute_mdd_limit_pct", "absolute_mdd_pass",
            "relative_mdd_pass", "total_return_pct_frozen", "cagr_pct_frozen", "ending_equity_krw_frozen",
        ],
    )
    write_csv(
        output / "official_adoption_gates.csv",
        gate_rows,
        [
            "window", "gate_A", "gate_B", "gate_C", "gate_D", "gate_E", "coverage_pct", "mdd_pct",
            "mdd_type", "v2_mdd_pct", "relative_mdd_deterioration_pp", "absolute_mdd_pass",
            "relative_mdd_pass", "unresolved_execution_event_count", "cash_conservation_pass",
            "exclusion_leakage_count", "cost_audit_mismatch_count",
        ],
    )
    write_json(output / "validation.json", validation)
    write_json(output / "source_hashes.json", source_hash_obj)
    write_json(
        output / "summary.json",
        {
            "schema": "pattern_b_v03_valuation_mdd_closure_summary_v01",
            "v03_original_verdict": "HOLD",
            "closure_verdict": verdict,
            "gates": aggregate_gates,
            "approved_carry_identities": source_hash_obj["approved_identities"],
            "approved_candidate_identity_date_count": len(carry_source_rows),
            "carry_applied_mark_count": len(carry_audit),
            "remaining_unresolved_mark_count": len(unresolved_audit),
            "total_return_cagr_frozen": True,
            "windows": window_results,
            "validation": validation,
        },
    )

    report = [
        "# Pattern B V03 Valuation-Only MDD Closure",
        "",
        "- V03 original verdict: `HOLD` (preserved).",
        f"- Closure verdict: `{verdict}`.",
        "- Only daily valuation, observed MDD, coverage, Gate D and Gate E were recalculated.",
        "- Signals, states, entry/exit events, cash, costs, trade results, total return and CAGR were frozen.",
        "- No full backtest, classifier, signal generation, order replay or terminal execution was run.",
        "",
        "## Approved carry source validation",
        "",
        f"- Exact identities: {len(APPROVED_IDENTITIES)}.",
        f"- Exact candidate identity/date rows source-validated: {len(carry_source_rows)}.",
        f"- Carry marks actually used in portfolio valuation: {len(carry_audit)}.",
        "- Every carry row used a prior normal adjusted close; KRX placeholder raw close was never used as the valuation price.",
        "- Every carry record has `used_for_execution=False`.",
        "",
        "| Ticker | ISU_CD | Approved dates validated | Portfolio valuation carry marks applied |",
        "|---|---|---:|---:|",
    ]
    for identity in source_hash_obj["approved_identities"]:
        used_count = sum(
            row["ticker"] == identity["ticker"] and row["isu_cd"] == identity["isu_cd"]
            for row in carry_audit
        )
        report.append(
            f"| {identity['ticker']} | {identity['isu_cd']} | {identity['candidate_date_count']} | {used_count} |"
        )
    report.extend([
        "",
        "## Five-window closure",
        "",
        "| Window | Coverage | MDD | MDD type | V2 MDD | Deterioration (pp) | D | E | Carry marks | Remaining unresolved marks |",
        "|---|---:|---:|---|---:|---:|---|---|---:|---:|",
    ])
    for row in gate_rows:
        delta_text = "—" if row["relative_mdd_deterioration_pp"] is None else f"{row['relative_mdd_deterioration_pp']:.4f}"
        report.append(
            f"| {row['window']} | {row['coverage_pct']:.2f}% | {row['mdd_pct']:.4f}% | {row['mdd_type']} | "
            f"{row['v2_mdd_pct']:.4f}% | {delta_text} | {row['gate_D']} | {row['gate_E']} | "
            f"{row['carry_applied_marks']} | {row['remaining_unresolved_marks']} |"
        )
    report.extend([
        "",
        "## Frozen return and control gates",
        "",
        "The existing V03 Total Return, CAGR, terminal return/equity, and Gate A/B/C evidence were read-only inputs to this closure. Their source files are hash-recorded in `source_hashes.json`.",
        "",
        "## Validation",
        "",
        "`validation.json` records exact carry-date, PIT, raw predicate, prior-price, execution isolation, baseline valid-equity parity, cash-path, position-count, and 25-gate checks.",
        f"`unresolved_valuation_gaps.csv` lists {len(unresolved_audit)} remaining unmarked held-position valuations; `unresolved_gap_spans.csv` records {len(unresolved_spans)} identity/position spans with a maximum of {validation['remaining_max_consecutive_unresolved_mark_sessions']} consecutive sessions. All remain unresolved as instructed.",
        "",
    ])
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")

    print(json.dumps({
        "output": str(OUTPUT_REL),
        "verdict": verdict,
        "gates": aggregate_gates,
        "carry_source_rows": len(carry_source_rows),
        "carry_applied_marks": len(carry_audit),
        "remaining_unresolved_marks": len(unresolved_audit),
        "windows": [{
            "window": row["window"], "coverage_pct": row["coverage_pct"], "mdd_pct": row["mdd_pct"],
            "mdd_type": row["mdd_type"], "v2_mdd_pct": row["v2_mdd_pct"],
            "relative_mdd_deterioration_pp": row["relative_mdd_deterioration_pp"],
            "gate_D": row["gate_D"], "gate_E": row["gate_E"],
        } for row in gate_rows],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
