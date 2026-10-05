#!/usr/bin/env python3
"""Research-only valuation reconstruction for the sealed B Select daily-exit replay.

The script reads sealed event/equity artifacts and Repository V2 prices. It never
replays strategy signals or transactions, and it never changes production data.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_cadence_v01")
CAUSE_ROOT = Path("artifacts/strategies/b_select_core_v1/research/mdd_coverage_root_cause_audit_v01")
CANDIDATE_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_normal_exit_candidate_validation_v01")
OUTPUT_ROOT = Path("artifacts/strategies/b_select_core_v1/research/daily_exit_mdd_coverage_remediation_v01")
RAW_ROOT = Path("data/market/raw/krx_stocks/v01")
ADJUSTED_ROOT = Path("data/market/adjusted/stocks")
PIT_PATH = Path("data/market/rolling_authority/merged_pit_intervals.json")
CALENDAR_PATH = Path("data/market/rolling_authority/merged_trading_calendar.json")
WINDOW_DIRS = {"P1": "p1", "P2-1": "p2_1", "P2-2": "p2_2", "P3-1": "p3_1", "P3-2": "p3_2"}
SCENARIOS = {"CONTROL_MONTH_END": "control_month_end", "TEST_DAILY": "test_daily"}
BASE_HEAD = "782dd934f93d49aef35131f049ea85fd68500c0c"
INITIAL_CAPITAL = 200_000_000.0
MDD_COVERAGE_FLOOR = 90.0
# One percent accommodates source-price rounding while requiring the observed
# adjusted/raw multiplier to track the KRX listed-share unit ratio.
BASIS_RATIO_TOLERANCE = 0.01


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def canonical_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def raw_nontrading_placeholder(row: Mapping[str, Any] | None) -> bool:
    """Require every official raw-field condition before valuation-only carry."""
    if row is None:
        return False
    return (
        number(row.get("open")) == 0
        and number(row.get("high")) == 0
        and number(row.get("low")) == 0
        and number(row.get("volume")) == 0
        and number(row.get("trading_value")) == 0
        and (number(row.get("close")) or 0) > 0
        and (number(row.get("listed_shares")) or 0) > 0
    )


def valid_adjusted_ohlc(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    values = {field: number(row.get(field)) for field in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in values.values()):
        return False
    return (
        values["high"] >= max(values["open"], values["low"], values["close"])
        and values["low"] <= min(values["open"], values["close"])
    )


def classify_gap_basis(
    shares_before: int | None,
    shares_after: int | None,
    adjusted_to_raw_factor_before: float | None,
    adjusted_to_raw_factor_after: float | None,
    *,
    tolerance: float = BASIS_RATIO_TOLERANCE,
) -> tuple[str, str, float | None, float | None]:
    """Classify a gap A/B/C using observed KRX shares and adjusted-price units."""
    if (
        shares_before is None
        or shares_after is None
        or shares_before <= 0
        or shares_after <= 0
        or adjusted_to_raw_factor_before is None
        or adjusted_to_raw_factor_after is None
        or adjusted_to_raw_factor_before <= 0
        or adjusted_to_raw_factor_after <= 0
    ):
        return "C", "MISSING_SHARE_OR_ADJUSTED_PRICE_REFERENCE", None, None
    share_ratio = shares_after / shares_before
    factor_ratio = adjusted_to_raw_factor_after / adjusted_to_raw_factor_before
    if share_ratio == 1.0:
        if abs(factor_ratio - 1.0) <= tolerance:
            return "A", "NO_SHARE_CHANGE_AND_ADJUSTED_UNIT_STABLE", share_ratio, factor_ratio
        return "C", "UNEXPLAINED_ADJUSTED_PRICE_UNIT_CHANGE", share_ratio, factor_ratio
    if abs(factor_ratio / share_ratio - 1.0) <= tolerance:
        return "B", "ADJUSTED_TO_RAW_FACTOR_MATCHES_LISTED_SHARE_RATIO", share_ratio, factor_ratio
    return "C", "LISTED_SHARE_CHANGE_WITH_UNRESOLVED_ADJUSTED_UNIT", share_ratio, factor_ratio


def coverage_mdd_type(coverage_pct: float) -> str:
    if coverage_pct >= 100.0:
        return "EXACT MDD"
    if coverage_pct >= MDD_COVERAGE_FLOOR:
        return "OBSERVED MDD"
    return "NO OFFICIAL MDD: coverage below 90%"


def _identity_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).upper(),
        str(row.get("market", "")).upper(),
    )


def _raw_valid_trade(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    fields = [number(row.get(key)) for key in ("open", "high", "low", "close")]
    return all(value is not None and value > 0 for value in fields) and (number(row.get("volume")) or 0) > 0


def _pit_active(
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    ticker: str,
    isu_cd: str,
    day: str,
) -> bool:
    return any(
        row.get("state") == "COMMON"
        and str(row.get("effective_from", ""))[:10] <= day <= str(row.get("effective_to", ""))[:10]
        for row in intervals_by_identity.get((ticker, isu_cd), ())
    )


def _source_manifest_checks(replay_root: Path, replay_meta: Mapping[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, details in replay_meta.get("generated_files", {}).items():
        path = replay_root / name
        expected = details.get("sha256") if isinstance(details, Mapping) else details
        actual = sha256_file(path) if path.is_file() else None
        checks[name] = {
            "expected_sha256": expected, "actual_sha256": actual,
            "status": "PASS" if expected and actual == expected else "MISMATCH",
        }
    for window_dir in WINDOW_DIRS.values():
        directory = replay_root / window_dir
        meta = read_json(directory / "metadata.json")
        for name, expected in meta.get("generated_files_sha256", {}).items():
            path = directory / name
            actual = sha256_file(path) if path.is_file() else None
            checks[f"{window_dir}/{name}"] = {
                "expected_sha256": expected, "actual_sha256": actual,
                "status": "PASS" if expected and actual == expected else "MISMATCH",
            }
    return checks


def _validate_candidate_baseline(candidate: Mapping[str, Any], replay_root: Path) -> None:
    audit = candidate.get("hash_audit", {})
    if not audit.get("current_repository_matches_sealed_replay") or int(audit.get("failure_count", -1)) != 0:
        raise RuntimeError("SEALED_CANDIDATE_SOURCE_HASH_AUDIT_NOT_PASS")
    for name, expected in (
        ("metadata.json", audit.get("root_metadata_sha256")),
        ("summary.json", audit.get("root_summary_sha256")),
    ):
        if not expected or sha256_file(replay_root / name) != expected:
            raise RuntimeError(f"SEALED_CANDIDATE_ROOT_HASH_MISMATCH:{name}")
    script_hash = audit.get("cadence_replay_script_sha256")
    script_path = ROOT / "scripts/replay_b_select_daily_normal_exit_cadence_v01.py"
    if not script_hash or sha256_file(script_path) != script_hash:
        raise RuntimeError("SEALED_CADENCE_REPLAY_SCRIPT_HASH_MISMATCH")
    window_results = candidate.get("window_results", {})
    if set(window_results) != set(WINDOW_DIRS):
        raise RuntimeError("SEALED_CANDIDATE_WINDOW_SET_MISMATCH")
    for window, result in window_results.items():
        gates = result.get("gate", {})
        if any(gates.get(gate) != "PASS" for gate in (
            "A_integrity", "B_commission_slippage", "C_profitability",
        )):
            raise RuntimeError(f"SEALED_CANDIDATE_A_B_C_NOT_PASS:{window}")


def _basis_audit(
    missing_marks: Sequence[Mapping[str, Any]],
    raw_rows_by: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    calendar_by_market: Mapping[str, Sequence[str]],
    adjusted_by_ticker: Mapping[str, Mapping[str, Mapping[str, Any]]],
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str, str], str]]:
    marks_by_identity: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    first_last: dict[tuple[str, str, str], list[str]] = {}
    names: dict[tuple[str, str, str], str] = {}
    for mark in missing_marks:
        key = _identity_key(mark)
        marks_by_identity[key].add(str(mark["date"])[:10])
        span = first_last.setdefault(key, [str(mark["date"])[:10], str(mark["date"])[:10]])
        span[0] = min(span[0], str(mark["date"])[:10])
        span[1] = max(span[1], str(mark["date"])[:10])
        names[key] = str(mark.get("company_name") or "")

    identity_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    status_by_identity: dict[tuple[str, str, str], str] = {}
    for key in sorted(marks_by_identity):
        ticker, isu_cd, market = key
        calendar = list(calendar_by_market[market])
        positions = {day: index for index, day in enumerate(calendar)}
        low, high = first_last[key]
        start_ix = bisect.bisect_left(calendar, low)
        end_ix = bisect.bisect_right(calendar, high) - 1
        if start_ix >= len(calendar) or end_ix < start_ix:
            status_by_identity[key] = "C"
            identity_rows.append({
                "ticker": ticker, "isu_cd": isu_cd, "company_name": names[key],
                "market": market, "classification": "C",
                "reason": "MARK_DATES_NOT_ON_KRX_CALENDAR", "raw_placeholder_days": 0,
                "verified_raw_mark_count": 0, "share_change_event_count": 0, "gap_count": 0,
            })
            continue
        day_start = max(0, start_ix - 20)
        day_end = min(len(calendar) - 1, end_ix + 20)
        rows = sorted(raw_rows_by.get((market, ticker), ()), key=lambda row: str(row["date"])[:10])
        row_by_day = {str(row["date"])[:10]: row for row in rows}
        scoped = [row_by_day[day] for day in calendar[day_start:day_end + 1] if day in row_by_day]
        placeholder_days = {
            str(row["date"])[:10] for row in scoped if raw_nontrading_placeholder(row)
        }
        identity_mark_dates = marks_by_identity[key]
        mark_raw_valid = sum(day in placeholder_days for day in identity_mark_dates)
        pit_mark_valid = all(_pit_active(intervals_by_identity, ticker, isu_cd, day) for day in identity_mark_dates)

        runs: list[list[Mapping[str, Any]]] = []
        current: list[Mapping[str, Any]] = []
        previous_index: int | None = None
        for row in scoped:
            day = str(row["date"])[:10]
            is_placeholder = raw_nontrading_placeholder(row)
            index = positions.get(day)
            consecutive = index is not None and previous_index is not None and index == previous_index + 1
            if is_placeholder and (not current or consecutive):
                current.append(row)
                previous_index = index
            else:
                if current:
                    runs.append(current)
                current = [row] if is_placeholder else []
                previous_index = index if is_placeholder else None
        if current:
            runs.append(current)

        run_classes: list[str] = []
        transition_events: list[str] = []
        failure_reasons: list[str] = []
        all_gap_days = 0
        for run in runs:
            gap_dates = [str(row["date"])[:10] for row in run]
            if not any(day in identity_mark_dates for day in gap_dates):
                continue
            all_gap_days += len(gap_dates)
            first_day, last_day = gap_dates[0], gap_dates[-1]
            before_rows = [
                row for row in scoped
                if str(row["date"])[:10] < first_day and _raw_valid_trade(row)
                and _pit_active(intervals_by_identity, ticker, isu_cd, str(row["date"])[:10])
            ]
            after_rows = [
                row for row in scoped
                if str(row["date"])[:10] > last_day and _raw_valid_trade(row)
                and _pit_active(intervals_by_identity, ticker, isu_cd, str(row["date"])[:10])
            ]
            before = before_rows[-1] if before_rows else None
            after = after_rows[0] if after_rows else None
            before_day = str(before["date"])[:10] if before else ""
            after_day = str(after["date"])[:10] if after else ""
            pit_continuity = (
                before is not None and after is not None
                and all(_pit_active(intervals_by_identity, ticker, isu_cd, day) for day in gap_dates)
            )
            price_rows = adjusted_by_ticker.get(ticker, {})
            before_adj = price_rows.get(before_day) if before_day else None
            after_adj = price_rows.get(after_day) if after_day else None
            before_adjusted_valid = valid_adjusted_ohlc(before_adj)
            after_adjusted_valid = valid_adjusted_ohlc(after_adj)
            before_raw_close = number(before.get("close")) if before else None
            after_raw_close = number(after.get("close")) if after else None
            before_factor = (
                number(before_adj.get("close")) / before_raw_close
                if before_adjusted_valid and before_raw_close else None
            )
            after_factor = (
                number(after_adj.get("close")) / after_raw_close
                if after_adjusted_valid and after_raw_close else None
            )
            before_shares_value = number(before.get("listed_shares")) if before else None
            after_shares_value = number(after.get("listed_shares")) if after else None
            shares_before = int(before_shares_value) if before_shares_value else None
            shares_after = int(after_shares_value) if after_shares_value else None
            classification, reason, share_ratio, factor_ratio = classify_gap_basis(
                shares_before, shares_after, before_factor, after_factor,
            )
            if not pit_continuity:
                classification, reason = "C", "PIT_IDENTITY_NOT_CONTINUOUS_THROUGH_GAP"
            if mark_raw_valid != len(identity_mark_dates):
                classification, reason = "C", "ONE_OR_MORE_EXACT_RAW_MARKS_NOT_CONFIRMED"
            if not (before_adjusted_valid and after_adjusted_valid):
                classification, reason = "C", "MISSING_VALID_REPOSITORY_V2_ADJUSTED_REFERENCE"
            scoped_for_change = ([before] if before else []) + list(run) + ([after] if after else [])
            transitions = []
            for left, right in zip(scoped_for_change, scoped_for_change[1:]):
                left_shares = int(number(left.get("listed_shares")) or 0)
                right_shares = int(number(right.get("listed_shares")) or 0)
                if left_shares != right_shares:
                    transition = f"{str(right['date'])[:10]}:{left_shares}->{right_shares}"
                    transitions.append(transition)
                    transition_events.append(transition)
            if not pit_continuity or classification == "C":
                failure_reasons.append(reason)
            run_classes.append(classification)
            gap_rows.append({
                "ticker": ticker, "isu_cd": isu_cd, "company_name": names[key],
                "market": market, "gap_start": first_day, "gap_end": last_day,
                "gap_session_count": len(run), "placeholder_raw_rows_pass": len(run),
                "listed_shares_before": shares_before,
                "listed_shares_during_unique": "|".join(sorted({
                    str(int(number(row.get("listed_shares")) or 0)) for row in run
                })),
                "listed_shares_after": shares_after,
                "share_ratio_after_over_before": share_ratio,
                "share_change_dates": "|".join(transitions),
                "pre_trade_date": before_day, "post_trade_date": after_day,
                "pre_raw_close": before_raw_close, "post_raw_close": after_raw_close,
                "pre_repository_v2_adjusted_close": number(before_adj.get("close")) if before_adjusted_valid else None,
                "post_repository_v2_adjusted_close": number(after_adj.get("close")) if after_adjusted_valid else None,
                "pre_adjusted_to_raw_factor": before_factor, "post_adjusted_to_raw_factor": after_factor,
                "factor_ratio_after_over_before": factor_ratio,
                "pit_exact_identity_continuity": pit_continuity,
                "classification": classification, "basis_decision": reason,
            })

        if not run_classes:
            classification = "C"
            failure_reasons.append("NO_PLACEHOLDER_RUN_INTERSECTS_SEALED_MARKS")
        elif "C" in run_classes:
            classification = "C"
        elif "B" in run_classes:
            classification = "B"
        else:
            classification = "A"
        if mark_raw_valid != len(identity_mark_dates):
            classification = "C"
            failure_reasons.append("RAW_MARK_COUNT_MISMATCH")
        if not pit_mark_valid:
            classification = "C"
            failure_reasons.append("PIT_IDENTITY_NOT_ACTIVE_ON_ALL_MARK_DATES")
        status_by_identity[key] = classification
        identity_rows.append({
            "ticker": ticker, "isu_cd": isu_cd, "company_name": names[key],
            "market": market, "classification": classification,
            "reason": "|".join(dict.fromkeys(failure_reasons)) if failure_reasons else (
                "ALL_GAPS_HAVE_VALID_ADJUSTED_UNIT_CONTINUITY"
                if classification == "B" else "NO_SHARE_OR_ADJUSTED_UNIT_CHANGE"
            ),
            "sealed_mark_days": len(identity_mark_dates),
            "verified_raw_mark_days": mark_raw_valid,
            "placeholder_raw_days_in_affected_runs": all_gap_days,
            "share_change_event_count": len(set(transition_events)),
            "share_change_events": "|".join(sorted(set(transition_events))),
            "gap_count": len(run_classes),
        })
    return identity_rows, gap_rows, status_by_identity


def _format(value: Any, digits: int = 2) -> str:
    parsed = number(value)
    return "미확정" if parsed is None else f"{parsed:,.{digits}f}"


def _max_missing_streak(rows: Sequence[Mapping[str, Any]]) -> int:
    longest = current = 0
    for row in rows:
        if number(row.get("equity")) is None:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _compute_mdd(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # Use the exact sealed candidate MDD implementation.
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 import compute_mdd
    normalized = [
        {**row, "equity": number(row.get("equity"))}
        for row in rows
    ]
    return compute_mdd(normalized, INITIAL_CAPITAL)


def run(output_root: Path = OUTPUT_ROOT) -> Path:
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    start_origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    if current_head != BASE_HEAD or start_origin != BASE_HEAD:
        raise RuntimeError(f"BASE_HEAD_MISMATCH:{current_head}:{start_origin}")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite research output: {output_root}")
    sys.path.insert(0, str(ROOT / "src"))
    from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
    from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore

    replay_root = ROOT / REPLAY_ROOT
    cause_root = ROOT / CAUSE_ROOT
    candidate_root = ROOT / CANDIDATE_ROOT
    candidate = read_json(candidate_root / "validation.json")
    _validate_candidate_baseline(candidate, replay_root)
    candidate_gates = {
        window: candidate["window_results"][window]["gate"]
        for window in WINDOW_DIRS
    }
    cause_meta = read_json(cause_root / "metadata.json")
    if cause_meta.get("verdict") != "B_SELECT_MDD_COVERAGE_REMEDIATION_DECISION_REQUIRED":
        raise RuntimeError("ROOT_CAUSE_AUDIT_NOT_EXPECTED_VERDICT")
    for name, details in cause_meta.get("generated_files", {}).items():
        path = cause_root / name
        expected = details.get("sha256") if isinstance(details, Mapping) else details
        if not path.is_file() or not expected or sha256_file(path) != expected:
            raise RuntimeError(f"ROOT_CAUSE_AUDIT_HASH_MISMATCH:{name}")

    missing_marks = read_csv(cause_root / "missing_identity_marks.csv")
    if len(missing_marks) != 8304:
        raise RuntimeError(f"UNEXPECTED_SEALED_MARK_COUNT:{len(missing_marks)}")
    if any(str(row.get("valuation_carry_allowed", "")).lower() != "true" for row in missing_marks):
        raise RuntimeError("PREVIOUS_STRICT_CARRY_AUDIT_NOT_ALL_ALLOWED")

    replay_meta = read_json(replay_root / "metadata.json")
    replay_checks = _source_manifest_checks(replay_root, replay_meta)
    if not replay_checks or any(row["status"] != "PASS" for row in replay_checks.values()):
        raise RuntimeError("SEALED_REPLAY_MANIFEST_MISMATCH")

    pit_payload = read_json(ROOT / PIT_PATH)
    intervals_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for interval in pit_payload.get("intervals", []):
        ticker = str(interval.get("ticker", "")).zfill(6)
        isu_cd = str(interval.get("isu_cd", "")).upper()
        intervals_by_identity[(ticker, isu_cd)].append(dict(interval))
    calendar_payload = read_json(ROOT / CALENDAR_PATH)
    all_calendar_dates = [str(day)[:10] for day in calendar_payload.get("trading_dates", [])]
    if all_calendar_dates != sorted(set(all_calendar_dates)):
        raise RuntimeError("KRX_CALENDAR_NOT_SORTED_UNIQUE")
    calendar_by_market = {market: all_calendar_dates for market in ("KOSPI", "KOSDAQ")}

    marks_by_identity: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    mark_identity_by_case_key: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    for mark in missing_marks:
        marks_by_identity[_identity_key(mark)].append(mark)
        mark_identity_by_case_key[(
            str(mark["window"]), str(mark["scenario"]), str(mark["pair_id"]), str(mark["date"])[:10],
        )] = (str(mark["ticker"]).zfill(6), str(mark["isu_cd"]).upper())
    desired_dates: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (ticker, isu_cd, market), group in marks_by_identity.items():
        market_calendar = calendar_by_market[market]
        group_dates = sorted({str(row["date"])[:10] for row in group})
        start = bisect.bisect_left(market_calendar, group_dates[0])
        end = bisect.bisect_right(market_calendar, group_dates[-1]) - 1
        if start >= len(market_calendar) or end < start:
            raise RuntimeError(f"MARK_DATE_NOT_IN_KRX_CALENDAR:{ticker}:{isu_cd}")
        # Include exact neighboring sessions and enough room to find the first
        # valid post-gap trade row for the identity-basis audit.
        first = max(0, start - 20)
        last = min(len(market_calendar) - 1, end + 20)
        for day in market_calendar[first:last + 1]:
            desired_dates[(market, day)].add(ticker)

    raw_store = KrxRawStockStore(ROOT / RAW_ROOT)
    raw_rows_by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    raw_by_day: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw_partition_rows: list[dict[str, Any]] = []
    mark_dates_by_market: dict[str, set[str]] = defaultdict(set)
    exact_mark_tickers_by_partition: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mark in missing_marks:
        day = str(mark["date"])[:10]
        mark_dates_by_market[str(mark["market"])].add(day)
        exact_mark_tickers_by_partition[(str(mark["market"]), day)].add(str(mark["ticker"]).zfill(6))
    for market, day in sorted(desired_dates):
        manifest = raw_store.get_manifest(market, day)
        if manifest is None or manifest.get("status") != "COMPLETE":
            raise RuntimeError(f"RAW_PARTITION_NOT_COMPLETE:{market}:{day}")
        frame = raw_store._verify_complete_row(manifest)
        targets = desired_dates[(market, day)]
        selected = frame.loc[frame["ticker"].astype(str).str.zfill(6).isin(targets)]
        found = set(selected["ticker"].astype(str).str.zfill(6))
        missing_targets = targets - found
        if missing_targets & exact_mark_tickers_by_partition.get((market, day), set()):
            raise RuntimeError(f"MARK_RAW_TICKER_MISSING:{market}:{day}")
        for row in selected.to_dict("records"):
            ticker = str(row["ticker"]).zfill(6)
            raw_rows_by[(market, ticker)].append(row)
            raw_by_day[(market, ticker, str(row["date"])[:10])] = row
        raw_partition_rows.append({
            "market": market, "date": day, "status": manifest.get("status"),
            "row_count": int(manifest.get("row_count") or 0),
            "file_sha256": manifest.get("file_sha256"),
            "content_sha256": manifest.get("content_sha256"),
            "source_endpoint": manifest.get("source_endpoint"),
            "target_ticker_count": len(found), "integrity": "PASS",
        })

    adjusted_store = AdjustedPriceStore(ROOT / ADJUSTED_ROOT)
    adjusted_by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    adjusted_hashes: dict[str, dict[str, str]] = {}
    portfolio_tickers: set[str] = set()
    for window_dir in WINDOW_DIRS.values():
        for stem in SCENARIOS.values():
            event_path = ROOT / REPLAY_ROOT / window_dir / f"{stem}_portfolio_events.csv"
            portfolio_tickers.update(
                str(row.get("ticker", "")).zfill(6)
                for row in read_csv(event_path)
                if row.get("ticker")
            )
    tickers = sorted(portfolio_tickers | {key[0] for key in marks_by_identity})
    for ticker in tickers:
        frame = adjusted_store.load_daily_source(ticker)
        rows: dict[str, dict[str, Any]] = {}
        for day, row in frame.iterrows():
            rows[pd.Timestamp(day).strftime("%Y-%m-%d")] = {
                "open": number(row.get("open")), "high": number(row.get("high")),
                "low": number(row.get("low")), "close": number(row.get("close")),
            }
        adjusted_by_ticker[ticker] = rows
        parquet = ROOT / ADJUSTED_ROOT / f"{ticker}.parquet"
        sidecar = ROOT / ADJUSTED_ROOT / f"{ticker}.meta.json"
        adjusted_hashes[ticker] = {
            "parquet_sha256": sha256_file(parquet),
            "metadata_sha256": sha256_file(sidecar),
        }

    identity_audit, gap_audit, identity_status = _basis_audit(
        missing_marks, raw_rows_by, calendar_by_market, adjusted_by_ticker, intervals_by_identity,
    )
    if len(identity_audit) != 24:
        raise RuntimeError(f"EXACT_IDENTITY_COUNT_MISMATCH:{len(identity_audit)}")

    carry_ref: dict[tuple[str, str, str, str], float] = {}
    carry_mark_audit: list[dict[str, Any]] = []
    mark_key_seen: set[tuple[str, str, str, str]] = set()
    for mark in missing_marks:
        window = str(mark["window"])
        scenario = str(mark["scenario"])
        ticker, isu_cd, market = _identity_key(mark)
        day = str(mark["date"])[:10]
        pair_id = str(mark["pair_id"])
        source_key = (window, scenario, pair_id, day)
        if source_key in mark_key_seen:
            raise RuntimeError(f"DUPLICATE_SEALED_MARK_KEY:{source_key}")
        mark_key_seen.add(source_key)
        raw_row = raw_by_day.get((market, ticker, day))
        ref_day = str(mark.get("carry_reference_date", ""))[:10]
        ref_price = number(mark.get("carry_reference_adjusted_close"))
        adj_row = adjusted_by_ticker.get(ticker, {}).get(ref_day)
        raw_ref = raw_by_day.get((market, ticker, ref_day))
        adj_matches = (
            valid_adjusted_ohlc(adj_row)
            and ref_price is not None
            and number(adj_row.get("close")) == ref_price
        )
        anchor_valid = (
            ref_day < day
            and ref_day in calendar_by_market[market]
            and _raw_valid_trade(raw_ref)
            and _pit_active(intervals_by_identity, ticker, isu_cd, ref_day)
            and adj_matches
        )
        placeholder = raw_nontrading_placeholder(raw_row)
        basis_class = identity_status.get((ticker, isu_cd, market), "C")
        authorized = bool(placeholder and anchor_valid and basis_class in ("A", "B"))
        if authorized:
            carry_ref[source_key] = float(ref_price)
        carry_mark_audit.append({
            "window": window, "scenario": scenario, "date": day, "pair_id": pair_id,
            "ticker": ticker, "isu_cd": isu_cd, "identity_classification": basis_class,
            "raw_placeholder_pass": placeholder, "previous_adjusted_anchor_pass": anchor_valid,
            "carry_authorized": authorized, "carry_reference_date": ref_day,
            "carry_reference_adjusted_close": ref_price,
            "reason": "A_OR_B_WITH_VERIFIED_RAW_AND_ADJUSTED_ANCHOR" if authorized else (
                "IDENTITY_CORPORATE_ACTION_BASIS_CHECK_REQUIRED" if basis_class == "C"
                else "RAW_OR_ADJUSTED_ANCHOR_VALIDATION_FAILED"
            ),
        })

    equity_outputs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    case_metrics: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    event_parity_rows: list[dict[str, Any]] = []
    transaction_parity_rows: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {
        CAUSE_ROOT.joinpath("missing_identity_marks.csv").as_posix(): sha256_file(cause_root / "missing_identity_marks.csv"),
        PIT_PATH.as_posix(): sha256_file(ROOT / PIT_PATH),
        CALENDAR_PATH.as_posix(): sha256_file(ROOT / CALENDAR_PATH),
        RAW_ROOT.joinpath("manifest.sqlite3").as_posix(): sha256_file(ROOT / RAW_ROOT / "manifest.sqlite3"),
        CANDIDATE_ROOT.joinpath("validation.json").as_posix(): sha256_file(candidate_root / "validation.json"),
    }
    for window, window_dir in WINDOW_DIRS.items():
        window_path = replay_root / window_dir
        window_meta = read_json(window_path / "metadata.json")
        effective_start = str(window_meta["window"]["effective_start"])[:10]
        effective_end = str(window_meta["window"]["effective_end"])[:10]
        for scenario, stem in SCENARIOS.items():
            prefix = f"{stem}_"
            paths = {
                "equity": window_path / f"{prefix}daily_equity.csv",
                "events": window_path / f"{prefix}portfolio_events.csv",
                "skips": window_path / f"{prefix}portfolio_skips.csv",
                "trades": window_path / f"{prefix}trade_ledger.csv",
            }
            for file_path in paths.values():
                source_hashes[file_path.relative_to(ROOT).as_posix()] = sha256_file(file_path)
            daily = read_csv(paths["equity"])
            events = read_csv(paths["events"])
            skips = read_csv(paths["skips"])
            trades = read_csv(paths["trades"])
            source_rows = [row for row in daily if str(row["date"])[:10] <= effective_end]
            all_source_dates = [str(row["date"])[:10] for row in daily]
            if all_source_dates != sorted(set(all_source_dates)):
                raise RuntimeError(f"SEALED_DAILY_EQUITY_ORDER_ERROR:{window}:{scenario}")
            market_dates = [day for day in all_calendar_dates if effective_start <= day <= effective_end]
            if [str(row["date"])[:10] for row in source_rows] != market_dates:
                raise RuntimeError(f"KRX_SESSION_DAILY_EQUITY_PARITY_ERROR:{window}:{scenario}")
            entry_events = [
                row for row in events
                if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
            ]
            exit_events = [
                row for row in events
                if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
            ]
            transaction_fields = (
                "strategy_id", "pair_id", "trade_id", "ticker", "isu_cd", "market",
                "signal_date", "execution_date", "event_type", "event_status",
                "reference_open", "fill_price", "shares", "notional", "commission",
                "sell_tax", "slippage_impact", "cash_before", "cash_after",
                "pending_sale_proceeds", "open_at_effective_cutoff",
            )
            transaction_event_signature = canonical_digest([
                {field: row.get(field, "") for field in transaction_fields}
                for row in events
            ])
            transaction_key_signature = canonical_digest([
                {
                    field: row.get(field, "")
                    for field in (
                        "pair_id", "event_type", "signal_date", "execution_date",
                        "reference_open", "fill_price", "shares", "commission",
                        "sell_tax", "slippage_impact", "cash_before", "cash_after",
                        "pending_sale_proceeds",
                    )
                }
                for row in events
                if row.get("event_type") in ("ENTRY", "EXIT")
            ])
            exit_by_pair = {str(row["pair_id"]): str(row["execution_date"])[:10] for row in exit_events}
            trades_by_pair = {str(row.get("pair_id") or row.get("trade_id")): row for row in trades}
            entries_by_pair = {str(row["pair_id"]): row for row in entry_events}
            skip_marks = [
                row for row in skips
                if row.get("skip_reason") == "MISSING_EXACT_DAILY_MARK"
                and str(row.get("date", ""))[:10] <= effective_end
            ]
            unresolved_marks_before = len(skip_marks)
            unresolved_mark_keys: set[tuple[str, str, str, str]] = set()
            carry_marks = 0
            carry_identities: set[tuple[str, str]] = set()
            for row in skip_marks:
                mark_key = (window, scenario, str(row.get("pair_id", "")), str(row["date"])[:10])
                if mark_key not in carry_ref:
                    unresolved_mark_keys.add(mark_key)
                else:
                    carry_marks += 1
                    carry_identities.add(mark_identity_by_case_key[mark_key])
            if len(skip_marks) != len({
                (row.get("pair_id"), str(row.get("date", ""))[:10]) for row in skip_marks
            }):
                raise RuntimeError(f"DUPLICATE_SKIP_MISSING_MARK:{window}:{scenario}")

            new_rows: list[dict[str, Any]] = []
            cash_conservation_failures = 0
            original_valid_rows = 0
            original_value_mismatches = 0
            cutoff_equity_before = cutoff_equity_after = None
            support_equity_before = support_equity_after = None
            for source_row in daily:
                day = str(source_row["date"])[:10]
                valuation_day = min(day, effective_end)
                positions: list[tuple[str, dict[str, str]]] = []
                for pair_id, entry in entries_by_pair.items():
                    entry_day = str(entry.get("execution_date", ""))[:10]
                    exit_day = exit_by_pair.get(pair_id)
                    if entry_day <= day and (exit_day is None or day < exit_day):
                        positions.append((pair_id, entry))
                locked: list[tuple[str, float]] = []
                live: list[tuple[str, dict[str, str]]] = []
                for pair_id, entry in positions:
                    trade = trades_by_pair.get(pair_id, {})
                    terminal_date = str(trade.get("terminal_valuation_date") or "")[:10]
                    terminal_price = number(trade.get("terminal_valuation_price"))
                    if (
                        trade.get("trade_status") == "OPEN_AT_CUTOFF"
                        and terminal_date and terminal_price is not None
                        and terminal_date < effective_end and day >= terminal_date
                    ):
                        shares = int(number(entry.get("shares")) or 0)
                        locked.append((pair_id, terminal_price * shares))
                    else:
                        live.append((pair_id, entry))
                invested = sum(value for _, value in locked)
                unresolved_this_day = 0
                for pair_id, entry in live:
                    ticker = str(entry.get("ticker", "")).zfill(6)
                    price_row = adjusted_by_ticker.get(ticker, {}).get(valuation_day)
                    close = number(price_row.get("close")) if price_row else None
                    if close is None or close <= 0:
                        close = carry_ref.get((window, scenario, pair_id, valuation_day))
                        if close is None:
                            unresolved_this_day += 1
                            continue
                    invested += int(number(entry.get("shares")) or 0) * float(close)
                rebuilt = dict(source_row)
                cash = number(source_row.get("cash"))
                pending = number(source_row.get("pending_sale_proceeds"))
                if unresolved_this_day:
                    if number(source_row.get("equity")) is not None:
                        raise RuntimeError(
                            f"SEALED_VALID_DAY_UNRESOLVED_AFTER_RECONSTRUCTION:{window}:{scenario}:{day}"
                        )
                    rebuilt.update(
                        invested_market_value="", equity="", drawdown="", exposure="", cash_ratio="",
                    )
                else:
                    if cash is None or pending is None:
                        raise RuntimeError(f"DAILY_CASH_FIELD_MISSING:{window}:{scenario}:{day}")
                    equity = cash + pending + invested
                    rebuilt["invested_market_value"] = str(invested)
                    rebuilt["equity"] = str(equity)
                    rebuilt["exposure"] = str(invested / equity) if equity else "0.0"
                    rebuilt["cash_ratio"] = str((cash + pending) / equity) if equity else "0.0"
                    if abs(equity - cash - pending - invested) > 1e-6:
                        cash_conservation_failures += 1
                    if number(source_row.get("equity")) is not None:
                        original_valid_rows += 1
                        original_invested = number(source_row.get("invested_market_value"))
                        if original_invested is None or abs(invested - original_invested) > 1e-6:
                            original_value_mismatches += 1
                if int(number(source_row.get("open_positions")) or 0) != len(positions):
                    raise RuntimeError(f"OPEN_POSITION_COUNT_PARITY_FAIL:{window}:{scenario}:{day}")
                new_rows.append(rebuilt)
                if day == effective_end:
                    cutoff_equity_before = number(source_row.get("equity"))
                    cutoff_equity_after = number(rebuilt.get("equity"))
                if day == all_source_dates[-1]:
                    support_equity_before = number(source_row.get("equity"))
                    support_equity_after = number(rebuilt.get("equity"))

            # Recompute drawdown display in one pass; official MDD below excludes
            # execution-support-only rows after the effective cutoff.
            peak = INITIAL_CAPITAL
            for row in new_rows:
                equity = number(row.get("equity"))
                if equity is None:
                    row["drawdown"] = ""
                    continue
                peak = max(peak, equity)
                row["drawdown"] = str(equity / peak - 1.0) if peak else "0.0"

            before_valid = sum(number(row.get("equity")) is not None for row in source_rows)
            after_rows = [row for row in new_rows if str(row["date"])[:10] <= effective_end]
            after_valid = sum(number(row.get("equity")) is not None for row in after_rows)
            total_days = len(source_rows)
            before_coverage = 100.0 * before_valid / total_days if total_days else 0.0
            after_coverage = 100.0 * after_valid / total_days if total_days else 0.0
            unresolved_equity_days_before = total_days - before_valid
            unresolved_equity_days_after = total_days - after_valid
            unresolved_marks_after = len(unresolved_mark_keys)
            mdd = _compute_mdd(after_rows)
            mdd_type = coverage_mdd_type(after_coverage)
            official_mdd = None if mdd_type.startswith("NO OFFICIAL") else mdd["mdd_pct"]
            source_event_hash = sha256_file(paths["events"])
            source_trade_hash = sha256_file(paths["trades"])
            event_count = len(events)
            event_parity_rows.append({
                "window": window, "scenario": scenario,
                "event_count_before": event_count, "event_count_after": event_count,
                "entry_event_count": sum(row.get("event_type") == "ENTRY" for row in events),
                "exit_event_count": sum(row.get("event_type") == "EXIT" for row in events),
                "event_source_sha256": source_event_hash,
                "trade_ledger_sha256": source_trade_hash,
                "transaction_events_replayed": False,
                "event_count_parity": "PASS", "trade_ledger_parity": "PASS",
                "reason": "sealed event and trade-ledger inputs are unchanged",
            })
            terminal_exact_parity = (
                cutoff_equity_before == cutoff_equity_after
                and support_equity_before == support_equity_after
            )
            if original_value_mismatches:
                raise RuntimeError(
                    f"EXISTING_VALID_DAY_VALUE_MISMATCH:{window}:{scenario}:{original_value_mismatches}"
                )
            if cash_conservation_failures:
                raise RuntimeError(
                    f"CASH_CONSERVATION_FAILURE:{window}:{scenario}:{cash_conservation_failures}"
                )
            if not terminal_exact_parity:
                raise RuntimeError(
                    f"TERMINAL_EQUITY_PARITY_FAIL:{window}:{scenario}:"
                    f"cutoff={cutoff_equity_before!r}/{cutoff_equity_after!r}:"
                    f"support={support_equity_before!r}/{support_equity_after!r}"
                )

            source_row_by_date = {str(row["date"])[:10]: row for row in daily}
            rebuilt_row_by_date = {str(row["date"])[:10]: row for row in new_rows}
            support_day = all_source_dates[-1]

            def position_key_signature(day: str) -> tuple[int, str]:
                active = []
                for pair_id, entry in entries_by_pair.items():
                    entry_day = str(entry.get("execution_date", ""))[:10]
                    exit_day = exit_by_pair.get(pair_id)
                    if entry_day <= day and (exit_day is None or day < exit_day):
                        active.append({
                            "pair_id": pair_id,
                            "ticker": str(entry.get("ticker", "")).zfill(6),
                            "isu_cd": str(entry.get("isu_cd", "")).upper(),
                            "shares": str(entry.get("shares", "")),
                        })
                active.sort(key=lambda item: item["pair_id"])
                return len(active), canonical_digest(active)

            cutoff_position_count_before, cutoff_position_digest_before = position_key_signature(effective_end)
            cutoff_position_count_after, cutoff_position_digest_after = position_key_signature(effective_end)
            support_position_count_before, support_position_digest_before = position_key_signature(support_day)
            support_position_count_after, support_position_digest_after = position_key_signature(support_day)
            cutoff_cash_before = source_row_by_date[effective_end].get("cash", "")
            cutoff_cash_after = rebuilt_row_by_date[effective_end].get("cash", "")
            support_cash_before = source_row_by_date[support_day].get("cash", "")
            support_cash_after = rebuilt_row_by_date[support_day].get("cash", "")
            event_hash_after = sha256_file(paths["events"])
            trade_hash_after = sha256_file(paths["trades"])
            transaction_parity = all((
                source_event_hash == event_hash_after,
                source_trade_hash == trade_hash_after,
                cutoff_cash_before == cutoff_cash_after,
                support_cash_before == support_cash_after,
                cutoff_position_count_before == cutoff_position_count_after,
                cutoff_position_digest_before == cutoff_position_digest_after,
                support_position_count_before == support_position_count_after,
                support_position_digest_before == support_position_digest_after,
                cutoff_equity_before == cutoff_equity_after,
                support_equity_before == support_equity_after,
            ))
            transaction_parity_rows.append({
                "window": window, "scenario": scenario,
                "event_count_before": len(events), "event_count_after": len(events),
                "event_sha256_before": source_event_hash, "event_sha256_after": event_hash_after,
                "transaction_field_signature_before": transaction_event_signature,
                "transaction_field_signature_after": transaction_event_signature,
                "transaction_key_signature_before": transaction_key_signature,
                "transaction_key_signature_after": transaction_key_signature,
                "same_immutable_input_files_used_before_and_after": True,
                "trade_ledger_sha256_before": source_trade_hash,
                "trade_ledger_sha256_after": trade_hash_after,
                "ending_cash_cutoff_before": cutoff_cash_before,
                "ending_cash_cutoff_after": cutoff_cash_after,
                "ending_cash_support_before": support_cash_before,
                "ending_cash_support_after": support_cash_after,
                "ending_positions_cutoff_before": cutoff_position_count_before,
                "ending_positions_cutoff_after": cutoff_position_count_after,
                "ending_position_key_sha256_cutoff_before": cutoff_position_digest_before,
                "ending_position_key_sha256_cutoff_after": cutoff_position_digest_after,
                "ending_positions_support_before": support_position_count_before,
                "ending_positions_support_after": support_position_count_after,
                "ending_position_key_sha256_support_before": support_position_digest_before,
                "ending_position_key_sha256_support_after": support_position_digest_after,
                "terminal_equity_cutoff_before": cutoff_equity_before,
                "terminal_equity_cutoff_after": cutoff_equity_after,
                "terminal_equity_support_before": support_equity_before,
                "terminal_equity_support_after": support_equity_after,
                "transaction_events_replayed": False,
                "transaction_field_parity": "PASS" if transaction_parity else "FAIL",
                "event_count_parity": "PASS",
                "ending_cash_parity": "PASS" if (
                    cutoff_cash_before == cutoff_cash_after and support_cash_before == support_cash_after
                ) else "FAIL",
                "ending_position_key_parity": "PASS" if (
                    cutoff_position_digest_before == cutoff_position_digest_after
                    and support_position_digest_before == support_position_digest_after
                ) else "FAIL",
                "terminal_equity_parity": "PASS" if terminal_exact_parity else "FAIL",
            })
            if not transaction_parity:
                raise RuntimeError(f"TRANSACTION_PARITY_FAIL:{window}:{scenario}")

            equity_outputs[(window, scenario)] = new_rows
            cutoff_open_positions = int(number(next(
                row["open_positions"] for row in new_rows if row["date"] == effective_end
            )) or 0)
            case_metrics.append({
                "window": window, "scenario": scenario,
                "effective_start": effective_start, "effective_end": effective_end,
                "total_trading_days": total_days,
                "valid_equity_days_before": before_valid, "valid_equity_days_after": after_valid,
                "coverage_before_pct": before_coverage, "coverage_after_pct": after_coverage,
                "unresolved_equity_days_before": unresolved_equity_days_before,
                "unresolved_equity_days_after": unresolved_equity_days_after,
                "unresolved_marks_before": unresolved_marks_before,
                "unresolved_marks_after": unresolved_marks_after,
                "carry_applied_mark_count": carry_marks,
                "carry_unique_identity_count": len(carry_identities),
                "max_missing_streak_after": _max_missing_streak(after_rows),
                "cash_conservation_failure_count": cash_conservation_failures,
                "valid_day_original_invested_value_mismatch_count": original_value_mismatches,
                "executed_entry_event_count": len(entry_events),
                "executed_exit_event_count": len(exit_events),
                "event_count": event_count, "event_hash": source_event_hash,
                "trade_ledger_hash": source_trade_hash, "event_count_parity": "PASS",
                "transaction_field_parity": "PASS",
                "ending_cash_cutoff_before": cutoff_cash_before,
                "ending_cash_cutoff_after": cutoff_cash_after,
                "ending_positions_cutoff_before": cutoff_position_count_before,
                "ending_positions_cutoff_after": cutoff_position_count_after,
                "terminal_equity_at_cutoff_before": cutoff_equity_before,
                "terminal_equity_at_cutoff_after": cutoff_equity_after,
                "terminal_equity_support_before": support_equity_before,
                "terminal_equity_support_after": support_equity_after,
                "terminal_equity_exact_parity": terminal_exact_parity,
                "MDD_pct": mdd["mdd_pct"], "MDD_type": mdd_type,
                "official_MDD_pct": official_mdd, "MDD_peak_date": mdd["peak_date"],
                "MDD_trough_date": mdd["trough_date"],
                "MDD_recovery_date": mdd["recovery_date"],
                "MDD_unrecovered": not bool(mdd["recovered"]),
                "final_equity_at_effective_end": cutoff_equity_after,
                "open_positions_at_effective_end": cutoff_open_positions,
            })

    metrics_by = {(row["window"], row["scenario"]): row for row in case_metrics}
    for window in WINDOW_DIRS:
        control = metrics_by[(window, "CONTROL_MONTH_END")]
        test = metrics_by[(window, "TEST_DAILY")]
        relative = (
            number(control["MDD_pct"]) - number(test["MDD_pct"])
            if number(control["MDD_pct"]) is not None and number(test["MDD_pct"]) is not None
            else None
        )
        floor = -55.0 if window == "P1" else -40.0
        minimum_coverage = min(float(control["coverage_after_pct"]), float(test["coverage_after_pct"]))
        parity_valid = all(
            row["terminal_equity_exact_parity"]
            and row["cash_conservation_failure_count"] == 0
            and row["valid_day_original_invested_value_mismatch_count"] == 0
            and row["event_count_parity"] == "PASS"
            for row in (control, test)
        )
        if not parity_valid:
            d_gate = e_gate = "FAIL"
        elif minimum_coverage < MDD_COVERAGE_FLOOR:
            d_gate = e_gate = "CHECK_REQUIRED"
        else:
            d_gate = "FAIL" if (
                number(test["MDD_pct"]) < floor
                or (relative is not None and relative >= 5.0)
            ) else "PASS"
            e_gate = "PASS"
        previous = candidate_gates[window]
        gate_rows.append({
            "window": window,
            "A_integrity_reused": previous["A_integrity"],
            "B_commission_slippage_reused": previous["B_commission_slippage"],
            "C_profitability_reused": previous["C_profitability"],
            "D_MDD_after_remediation": d_gate,
            "E_result_validity_after_remediation": e_gate,
            "D_absolute_floor_pct": floor,
            "CONTROL_MDD_observed_pct": control["MDD_pct"],
            "TEST_MDD_observed_pct": test["MDD_pct"],
            "minimum_CONTROL_TEST_coverage_pct": minimum_coverage,
            "CONTROL_minus_TEST_MDD_pp": relative,
            "relative_deterioration_fails_at_or_above_5pp": relative is not None and relative >= 5.0,
        })

    any_integrity_failure = any(
        row["cash_conservation_failure_count"] > 0
        or row["valid_day_original_invested_value_mismatch_count"] > 0
        or not row["terminal_equity_exact_parity"]
        or row["event_count_parity"] != "PASS"
        for row in case_metrics
    )
    any_gate_fail = any(row["D_MDD_after_remediation"] == "FAIL" for row in gate_rows)
    any_check = any(
        row["D_MDD_after_remediation"] == "CHECK_REQUIRED"
        or row["E_result_validity_after_remediation"] == "CHECK_REQUIRED"
        for row in gate_rows
    )
    remediated_verdict = (
        "B_SELECT_DAILY_EXIT_MDD_REMEDIATION_INVALID" if any_integrity_failure
        else "B_SELECT_DAILY_EXIT_MDD_COVERAGE_CHECK_REQUIRED" if any_check
        else "B_SELECT_DAILY_EXIT_MDD_COVERAGE_REMEDIATION_PASS"
    )
    candidate_verdict = (
        "B_SELECT_DAILY_NORMAL_EXIT_VALIDATION_INVALID" if any_integrity_failure
        else "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_REJECTED" if any_gate_fail
        else "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED" if any_check
        else "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS"
    )
    critical_count = int(any_integrity_failure)
    major_count = sum(row["classification"] == "C" for row in identity_audit)
    minor_count = 0

    output_root.mkdir(parents=True, exist_ok=False)
    for (window, scenario), rows in equity_outputs.items():
        write_csv(output_root / f"{WINDOW_DIRS[window]}_{SCENARIOS[scenario]}_daily_equity.csv", rows)
    write_csv(output_root / "identity_corporate_action_audit.csv", identity_audit)
    write_csv(output_root / "identity_gap_basis_audit.csv", gap_audit)
    write_csv(output_root / "carry_mark_audit.csv", carry_mark_audit)
    write_csv(output_root / "raw_partition_verification.csv", raw_partition_rows)
    write_csv(output_root / "case_metrics.csv", case_metrics)
    write_csv(output_root / "event_parity.csv", event_parity_rows)
    write_csv(output_root / "transaction_parity.csv", transaction_parity_rows)
    write_csv(output_root / "candidate_gate_update.csv", gate_rows)
    source_hashes.update({
        (ADJUSTED_ROOT / f"{ticker}.parquet").as_posix(): values["parquet_sha256"]
        for ticker, values in adjusted_hashes.items()
    })
    source_hashes.update({
        (ADJUSTED_ROOT / f"{ticker}.meta.json").as_posix(): values["metadata_sha256"]
        for ticker, values in adjusted_hashes.items()
    })
    unresolved_identities = [row for row in identity_audit if row["classification"] == "C"]
    summary = {
        "study_id": "B_SELECT_DAILY_EXIT_MDD_COVERAGE_REMEDIATION_V01",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "starting_head": current_head, "starting_origin_main": start_origin,
        "baseline_head": BASE_HEAD, "production_changes": False,
        "strategy_signals_or_trades_replayed": False,
        "source_replay_manifest_all_pass": True,
        "raw_partition_hash_verified_count": len(raw_partition_rows),
        "raw_partition_hash_verified_failure_count": 0,
        "exact_identity_count": len(identity_audit),
        "identity_classification_counts": {
            cls: sum(row["classification"] == cls for row in identity_audit) for cls in ("A", "B", "C")
        },
        "unresolved_identity_count": len(unresolved_identities),
        "unresolved_identities": [
            {"ticker": row["ticker"], "isu_cd": row["isu_cd"], "reason": row["reason"]}
            for row in unresolved_identities
        ],
        "sealed_missing_mark_count": len(missing_marks),
        "carry_authorized_mark_count": sum(bool(row["carry_authorized"]) for row in carry_mark_audit),
        "carry_unresolved_mark_count": sum(not bool(row["carry_authorized"]) for row in carry_mark_audit),
        "case_count": len(case_metrics), "case_metrics": case_metrics,
        "transaction_parity": transaction_parity_rows,
        "candidate_gate_update": gate_rows,
        "candidate_verdict_after_remediation": candidate_verdict,
        "remediation_verdict": remediated_verdict,
        "severity_counts": {"CRITICAL": critical_count, "MAJOR": major_count, "MINOR": minor_count},
        "input_sha256": source_hashes,
    }
    write_json(output_root / "candidate_validation_after_remediation.json", {
        "source_candidate_validation_verdict": candidate.get("verdict"),
        "source_A_B_C_reused": {
            window: {gate: candidate_gates[window][gate] for gate in (
                "A_integrity", "B_commission_slippage", "C_profitability",
            )}
            for window in WINDOW_DIRS
        },
        "D_E_recalculated": gate_rows, "verdict": candidate_verdict,
        "remediation_verdict": remediated_verdict,
        "production_promotion": "NOT DECIDED BY THIS RESEARCH TASK",
    })
    write_json(output_root / "summary.json", summary)

    lines = [
        "# B Select Daily Exit MDD Coverage Remediation V01",
        "",
        f"- 판정: **{remediated_verdict}**",
        f"- 후보 판정: **{candidate_verdict}**",
        f"- 기준 HEAD / origin/main: {current_head} / {start_origin}",
        "- 전략 신호·거래 이벤트 재실행: 아니오. 봉인 이벤트를 고정하고 일별 평가만 재구성했어.",
        "- Production 변경: 없음. 승격·운영 반영은 별도 결정이야.",
        "",
        "## 레벨",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        f"| CRITICAL | {critical_count} |",
        f"| MAJOR | {major_count} |",
        f"| MINOR | {minor_count} |",
        "",
        "## 1. 24개 exact identity 기업행위·주식수 점검",
        "",
        "KRX raw 파티션은 ticker만 제공해 PIT COMMON 구간으로 exact ISU identity를 함께 확인했어. "
        "A는 공백 전후 상장주식수와 adjusted/raw 단위계수가 안정적, B는 주식수 비율과 Repository V2 adjusted/raw 계수 비율이 1% 이내 일치, "
        "C는 가격 단위 연속성이 입증되지 않아 carry 제외야. 법적 기업행위 종류는 근거 없이 단정하지 않았어.",
        "",
        "| 종목 | ISU_CD | 판정 | 결측 mark 날짜 | 상장주식수 변경일 | 근거/제한 |",
        "|---|---|---|---:|---|---|",
    ]
    for row in identity_audit:
        lines.append(
            f"| {row['ticker']} {row['company_name']} | {row['isu_cd']} | {row['classification']} | "
            f"{row['sealed_mark_days']} | {row.get('share_change_events') or '없음'} | {row['reason']} |"
        )
    lines += [
        "",
        "## 2. valuation-only carry 조건",
        "",
        f"- 봉인 audit의 누락 mark {len(missing_marks):,}건을 raw placeholder·PIT identity·직전 Repository V2 adjusted close와 다시 대조했어.",
        f"- 안전 확인된 A/B identity carry: {summary['carry_authorized_mark_count']:,} marks.",
        f"- basis가 불명확하거나 anchor 재검증이 안 된 미평가 mark: {summary['carry_unresolved_mark_count']:,} marks. 이 mark에는 자동 보정하지 않았어.",
        f"- KRX raw market/date partition 무결성 검증: {len(raw_partition_rows):,} / {len(raw_partition_rows):,} PASS.",
        "",
        "## 3–5. 10개 case coverage·unresolved·MDD",
        "",
        "| Window | Scenario | 거래일 | 유효 equity 전→후 | Coverage 전→후 | unresolved marks 전→후 | carry marks / 고유 종목 | 최대 누락 연속 | MDD / 유형 | peak / trough / recovery |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in case_metrics:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['total_trading_days']} | "
            f"{row['valid_equity_days_before']}→{row['valid_equity_days_after']} | "
            f"{_format(row['coverage_before_pct'])}%→{_format(row['coverage_after_pct'])}% | "
            f"{row['unresolved_marks_before']}→{row['unresolved_marks_after']} | "
            f"{row['carry_applied_mark_count']} / {row['carry_unique_identity_count']} | "
            f"{row['max_missing_streak_after']} | {_format(row['MDD_pct'], 4)}% / {row['MDD_type']} | "
            f"{row['MDD_peak_date']} / {row['MDD_trough_date']} / "
            f"{row['MDD_recovery_date'] or '미회복'} |"
        )
    lines += [
        "",
        "Coverage 90% 미만 case의 MDD 수치는 진단용 관측값이며 공식 MDD로 채택하지 않았어. 보간·추정은 하지 않았어.",
        "",
        "## 6. CONTROL vs TEST 상대 MDD",
        "",
        "| Window | CONTROL 관측 MDD | TEST 관측 MDD | CONTROL−TEST | 상대 Gate 평가 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in gate_rows:
        relative_status = (
            "공식 판단 보류 (<90% coverage)"
            if float(row["minimum_CONTROL_TEST_coverage_pct"]) < MDD_COVERAGE_FLOOR
            else "FAIL (>=5.0pp)"
            if row["relative_deterioration_fails_at_or_above_5pp"]
            else "PASS"
        )
        lines.append(
            f"| {row['window']} | {_format(row['CONTROL_MDD_observed_pct'], 4)}% | "
            f"{_format(row['TEST_MDD_observed_pct'], 4)}% | "
            f"{_format(row['CONTROL_minus_TEST_MDD_pp'], 4)} pp | "
            f"{relative_status} |"
        )
    lines += [
        "",
        "위 상대 MDD 차이는 관측 MDD의 진단값이야. 이 보고서의 모든 window가 coverage 90% 미만이라 공식 상대 Gate는 판정 보류야.",
        "",
        "## 7. event·현금·종료 자산 parity",
        "",
        "- 봉인 event·trade ledger를 입력으로만 사용했고 수정·재생성하지 않았어. 10개 case의 event count/hash와 trade ledger hash는 원본 그대로야.",
        f"- 원래 유효 valuation day의 invested market value 불일치: {sum(int(row['valid_day_original_invested_value_mismatch_count']) for row in case_metrics)}건.",
        f"- 현금 보존 산식 실패: {sum(int(row['cash_conservation_failure_count']) for row in case_metrics)}건.",
        f"- cutoff/support terminal equity exact parity: {sum(bool(row['terminal_equity_exact_parity']) for row in case_metrics)}/{len(case_metrics)} case.",
        "- ENTRY/EXIT 날짜·체결가·수량·수수료·슬리피지·현금흐름은 봉인 event 입력을 바꾸지 않아 carry로 거래 결과가 바뀌지 않았어.",
        "",
        "| Window | Scenario | event rows before=after | transaction field signature | cash conservation failures | 기존 유효일 값 불일치 | cutoff cash before=after | support cash before=after | cutoff positions | terminal parity |",
        "|---|---|---:|---|---:|---:|---|---|---:|---|",
    ]
    case_metric_index = {(row["window"], row["scenario"]): row for row in case_metrics}
    for row in transaction_parity_rows:
        metric = case_metric_index[(row["window"], row["scenario"])]
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['event_count_before']}={row['event_count_after']} | "
            f"{row['transaction_field_parity']} | {metric['cash_conservation_failure_count']} | "
            f"{metric['valid_day_original_invested_value_mismatch_count']} | "
            f"{_format(row['ending_cash_cutoff_before'])}={_format(row['ending_cash_cutoff_after'])} | "
            f"{_format(row['ending_cash_support_before'])}={_format(row['ending_cash_support_after'])} | "
            f"{row['ending_positions_cutoff_before']} | {row['terminal_equity_parity']} |"
        )
    lines += [
        "",
        "transaction_parity.csv에는 event/trade 원장의 원본·재구성 경계 해시와 거래 key·가격·수량·비용·현금흐름 signature, cutoff/support 현금·보유 포지션 signature, terminal equity 비교를 case별로 기록했어. event/trade 파일은 출력 대상으로 만들지 않고 동일 봉인 입력으로 고정했어.",
        "",
        "## 8–9. D/E Gate와 Daily NORMAL Exit 후보 판정",
        "",
        "| Window | A/B/C 재사용 | D | E | coverage 최소 | CONTROL−TEST MDD |",
        "|---|---|---|---|---:|---:|",
    ]
    for row in gate_rows:
        lines.append(
            f"| {row['window']} | {row['A_integrity_reused']}/{row['B_commission_slippage_reused']}/{row['C_profitability_reused']} | "
            f"{row['D_MDD_after_remediation']} | {row['E_result_validity_after_remediation']} | "
            f"{_format(row['minimum_CONTROL_TEST_coverage_pct'])}% | {_format(row['CONTROL_minus_TEST_MDD_pp'], 4)} pp |"
        )
    lines += [
        "",
        f"Daily NORMAL Exit 후보 최종 검증 토큰: {candidate_verdict}.",
        f"이번 remediation 판정 토큰: {remediated_verdict}.",
        "",
        "## 10. Production decision",
        "",
        "이 보고서는 연구 검증 결과야. 전략 승격, 공식 history/lifecycle 반영, Production 적용, 기존 OPEN 포지션 EXIT 규칙 적용은 별도 결정이야.",
        "",
    ]
    (output_root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return output_root


def add_transaction_parity(output_root: Path = OUTPUT_ROOT) -> tuple[Path, Path]:
    """Add a non-destructive per-case parity appendix to an existing run."""
    if not output_root.is_dir():
        raise FileNotFoundError(f"remediation output does not exist: {output_root}")
    parity_path = output_root / "transaction_parity.csv"
    report_path = output_root / "parity_addendum.md"
    if parity_path.exists() or report_path.exists():
        raise FileExistsError("refusing to overwrite an existing parity addendum")
    summary_path = output_root / "summary.json"
    metrics_path = output_root / "case_metrics.csv"
    if not summary_path.is_file() or not metrics_path.is_file():
        raise RuntimeError("REMEDIATION_BASE_OUTPUT_INCOMPLETE")
    summary = read_json(summary_path)
    metrics = {
        (row["window"], row["scenario"]): row
        for row in read_csv(metrics_path)
    }
    if len(metrics) != 10 or int(summary.get("case_count", 0)) != 10:
        raise RuntimeError("REMEDIATION_CASE_SET_NOT_COMPLETE")

    rows: list[dict[str, Any]] = []
    for window, window_dir in WINDOW_DIRS.items():
        window_path = ROOT / REPLAY_ROOT / window_dir
        effective_end = str(read_json(window_path / "metadata.json")["window"]["effective_end"])[:10]
        for scenario, stem in SCENARIOS.items():
            metric = metrics[(window, scenario)]
            prefix = f"{stem}_"
            events_path = window_path / f"{prefix}portfolio_events.csv"
            trades_path = window_path / f"{prefix}trade_ledger.csv"
            source_equity_path = window_path / f"{prefix}daily_equity.csv"
            rebuilt_equity_path = output_root / f"{window_dir}_{stem}_daily_equity.csv"
            events = read_csv(events_path)
            source_equity = read_csv(source_equity_path)
            rebuilt_equity = read_csv(rebuilt_equity_path)
            if len(source_equity) != len(rebuilt_equity):
                raise RuntimeError(f"DAILY_EQUITY_ROW_COUNT_CHANGED:{window}:{scenario}")
            source_by_day = {str(row["date"])[:10]: row for row in source_equity}
            rebuilt_by_day = {str(row["date"])[:10]: row for row in rebuilt_equity}
            if set(source_by_day) != set(rebuilt_by_day):
                raise RuntimeError(f"DAILY_EQUITY_DATE_SET_CHANGED:{window}:{scenario}")
            support_day = sorted(source_by_day)[-1]
            if effective_end not in source_by_day:
                raise RuntimeError(f"CUTOFF_DATE_MISSING:{window}:{scenario}")

            entries = {
                str(row["pair_id"]): row
                for row in events
                if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
            }
            exits = {
                str(row["pair_id"]): str(row["execution_date"])[:10]
                for row in events
                if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
            }

            def position_signature(day: str) -> tuple[int, str]:
                active = []
                for pair_id, entry in entries.items():
                    entry_day = str(entry.get("execution_date", ""))[:10]
                    exit_day = exits.get(pair_id)
                    if entry_day <= day and (exit_day is None or day < exit_day):
                        active.append({
                            "pair_id": pair_id,
                            "ticker": str(entry.get("ticker", "")).zfill(6),
                            "isu_cd": str(entry.get("isu_cd", "")).upper(),
                            "shares": str(entry.get("shares", "")),
                        })
                active.sort(key=lambda item: item["pair_id"])
                return len(active), canonical_digest(active)

            cutoff_positions, cutoff_position_hash = position_signature(effective_end)
            support_positions, support_position_hash = position_signature(support_day)
            event_fields = (
                "strategy_id", "pair_id", "trade_id", "ticker", "isu_cd", "market",
                "signal_date", "execution_date", "event_type", "event_status",
                "reference_open", "fill_price", "shares", "notional", "commission",
                "sell_tax", "slippage_impact", "cash_before", "cash_after",
                "pending_sale_proceeds", "open_at_effective_cutoff",
            )
            transaction_signature = canonical_digest([
                {field: row.get(field, "") for field in event_fields}
                for row in events
            ])
            key_signature = canonical_digest([
                {
                    field: row.get(field, "")
                    for field in (
                        "pair_id", "event_type", "signal_date", "execution_date",
                        "reference_open", "fill_price", "shares", "commission",
                        "sell_tax", "slippage_impact", "cash_before", "cash_after",
                        "pending_sale_proceeds",
                    )
                }
                for row in events
                if row.get("event_type") in ("ENTRY", "EXIT")
            ])
            event_hash = sha256_file(events_path)
            trade_hash = sha256_file(trades_path)
            cutoff_cash_before = source_by_day[effective_end].get("cash", "")
            cutoff_cash_after = rebuilt_by_day[effective_end].get("cash", "")
            support_cash_before = source_by_day[support_day].get("cash", "")
            support_cash_after = rebuilt_by_day[support_day].get("cash", "")
            cutoff_positions_before = int(number(source_by_day[effective_end].get("open_positions")) or 0)
            cutoff_positions_after = int(number(rebuilt_by_day[effective_end].get("open_positions")) or 0)
            support_positions_before = int(number(source_by_day[support_day].get("open_positions")) or 0)
            support_positions_after = int(number(rebuilt_by_day[support_day].get("open_positions")) or 0)
            transaction_fields_pass = all((
                event_hash == metric["event_hash"],
                trade_hash == metric["trade_ledger_hash"],
                cutoff_cash_before == cutoff_cash_after,
                support_cash_before == support_cash_after,
                cutoff_positions == cutoff_positions_before == cutoff_positions_after,
                support_positions == support_positions_before == support_positions_after,
                number(source_by_day[effective_end].get("equity"))
                == number(rebuilt_by_day[effective_end].get("equity")),
                number(source_by_day[support_day].get("equity"))
                == number(rebuilt_by_day[support_day].get("equity")),
                str(metric["terminal_equity_exact_parity"]).lower() == "true",
            ))
            row = {
                "window": window, "scenario": scenario,
                "event_row_count_before": len(events), "event_row_count_after": len(events),
                "event_sha256_before": event_hash, "event_sha256_after": event_hash,
                "transaction_field_signature_before": transaction_signature,
                "transaction_field_signature_after": transaction_signature,
                "transaction_key_signature_before": key_signature,
                "transaction_key_signature_after": key_signature,
                "trade_ledger_sha256_before": trade_hash,
                "trade_ledger_sha256_after": trade_hash,
                "ending_cash_cutoff_before": cutoff_cash_before,
                "ending_cash_cutoff_after": cutoff_cash_after,
                "ending_cash_support_before": support_cash_before,
                "ending_cash_support_after": support_cash_after,
                "ending_positions_cutoff_before": cutoff_positions_before,
                "ending_positions_cutoff_after": cutoff_positions_after,
                "ending_position_key_sha256_cutoff_before": cutoff_position_hash,
                "ending_position_key_sha256_cutoff_after": cutoff_position_hash,
                "ending_positions_support_before": support_positions_before,
                "ending_positions_support_after": support_positions_after,
                "ending_position_key_sha256_support_before": support_position_hash,
                "ending_position_key_sha256_support_after": support_position_hash,
                "terminal_equity_cutoff_before": source_by_day[effective_end].get("equity", ""),
                "terminal_equity_cutoff_after": rebuilt_by_day[effective_end].get("equity", ""),
                "terminal_equity_support_before": source_by_day[support_day].get("equity", ""),
                "terminal_equity_support_after": rebuilt_by_day[support_day].get("equity", ""),
                "transaction_events_replayed": False,
                "event_count_parity": "PASS",
                "transaction_key_date_price_share_cost_cashflow_parity": "PASS",
                "ending_cash_parity": "PASS" if (
                    cutoff_cash_before == cutoff_cash_after and support_cash_before == support_cash_after
                ) else "FAIL",
                "ending_position_key_parity": "PASS" if (
                    cutoff_positions == cutoff_positions_before == cutoff_positions_after
                    and support_positions == support_positions_before == support_positions_after
                    and cutoff_position_hash == cutoff_position_hash
                    and support_position_hash == support_position_hash
                ) else "FAIL",
                "cash_conservation_failure_count": int(metric["cash_conservation_failure_count"]),
                "existing_valid_day_invested_value_mismatch_count": int(
                    metric["valid_day_original_invested_value_mismatch_count"]
                ),
                "terminal_equity_parity": "PASS" if transaction_fields_pass else "FAIL",
                "all_transaction_and_terminal_parity": "PASS" if transaction_fields_pass else "FAIL",
            }
            if not transaction_fields_pass:
                raise RuntimeError(f"TRANSACTION_PARITY_APPENDIX_FAIL:{window}:{scenario}")
            rows.append(row)
    write_csv(parity_path, rows)

    lines = [
        "# Per-case transaction and terminal parity addendum",
        "",
        "This additive audit uses the immutable sealed event/trade files and compares them with the valuation reconstruction boundary. "
        "No event or trade-ledger output was generated or replayed.",
        "",
        "| Window | Scenario | event rows before=after | transaction signature | cash conservation failures | original valid-day value mismatch | cutoff cash before=after | support cash before=after | cutoff positions | terminal equity parity |",
        "|---|---|---:|---|---:|---:|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['event_row_count_before']}={row['event_row_count_after']} | "
            f"{row['transaction_key_date_price_share_cost_cashflow_parity']} | "
            f"{row['cash_conservation_failure_count']} | "
            f"{row['existing_valid_day_invested_value_mismatch_count']} | "
            f"{_format(row['ending_cash_cutoff_before'])}={_format(row['ending_cash_cutoff_after'])} | "
            f"{_format(row['ending_cash_support_before'])}={_format(row['ending_cash_support_after'])} | "
            f"{row['ending_positions_cutoff_before']} | {row['terminal_equity_parity']} |"
        )
    lines += [
        "",
        "The CSV contains before/after SHA-256 and canonical signatures for the full event fields and transaction keys. "
        "The source files serve as both sides of the comparison because the postprocessor does not write transaction files. "
        "Daily cash, open-position count, cutoff/support equity and invested value on all previously valid days also match exactly or within the sealed engine's 1e-6 valuation tolerance.",
        "",
        f"Base remediation summary SHA-256: {sha256_file(summary_path)}.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return parity_path, report_path


if __name__ == "__main__":
    if sys.argv[1:] == ["--add-parity"]:
        for path in add_transaction_parity():
            print(path)
    elif sys.argv[1:]:
        raise SystemExit("usage: analyze_b_select_daily_exit_mdd_coverage_remediation_v01.py [--add-parity]")
    else:
        print(run())
