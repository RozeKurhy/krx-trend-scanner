#!/usr/bin/env python3
"""Build an isolated P2-2 PIT identity extension from verified local KRX sources.

This uses the existing bounded rolling PIT builder and publisher, but writes to a
new versioned authority directory. It never mutates the frozen authority or the
production rolling authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.krx_historical_instrument_acquisition import (
    load_bounded_basic_info_snapshots,
    load_historical_trading_calendar,
)
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    build_rolling_pit_extension,
    load_rolling_authority,
    validate_merged_authority_coherence,
    write_merged_pit_extension,
)
from trend_scanner.universe.historical_authority_reconciliation import (
    classify_full_universe,
    load_supplemental_authority_records,
)
from trend_scanner.universe.survivorship_safe_denominator_freeze import pit_denominator_manifest_sha256


BASE_AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
OUTPUT_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
HISTORICAL_CALENDAR_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
ROLLING_SOURCE_ROOT = ROOT / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info"
ROLLING_CHECKPOINT_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/rolling/checkpoint.json"
ROLLING_SUMMARY_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/rolling/acquisition_final_summary.json"
SUPPLEMENTAL_AUTHORITY_DIR = ROOT / "data/reference/source/history/krx_instrument_master/v01/supplemental_authority"
REQUESTED_EFFECTIVE_END = "2026-08-31"
EXECUTION_SUPPORT = "2026-09-01"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def overlap_projection(
    intervals: Sequence[Mapping[str, Any]],
    *,
    boundary: str,
) -> list[tuple[str, str, str, str, str, str]]:
    projected = []
    for interval in intervals:
        start = str(interval["effective_from"])
        if start > boundary:
            continue
        projected.append(
            (
                str(interval["ticker"]),
                str(interval["isu_cd"]),
                str(interval["market"]),
                str(interval.get("state", "COMMON")),
                start,
                min(str(interval["effective_to"]), boundary),
            )
        )
    return sorted(projected)


def validate_intervals(intervals: Sequence[Mapping[str, Any]], *, coverage_end: str) -> None:
    exact_keys: set[tuple[str, str, str, str, str]] = set()
    prior_by_ticker: dict[str, tuple[str, str]] = {}
    for interval in sorted(intervals, key=lambda row: (str(row["ticker"]), str(row["effective_from"]))):
        ticker = str(interval.get("ticker", ""))
        isu_cd = str(interval.get("isu_cd", ""))
        market = str(interval.get("market", ""))
        start = str(interval.get("effective_from", ""))
        end = str(interval.get("effective_to", ""))
        key = (ticker, isu_cd, market, start, end)
        if not all((ticker, isu_cd, market, start, end)) or start > end or end > coverage_end:
            raise RuntimeError(f"INVALID_PIT_INTERVAL:{key}")
        if interval.get("state") != "COMMON":
            raise RuntimeError(f"NON_COMMON_INTERVAL_IN_PIT_AUTHORITY:{key}")
        if key in exact_keys:
            raise RuntimeError(f"DUPLICATE_PIT_INTERVAL:{key}")
        exact_keys.add(key)
        prior = prior_by_ticker.get(ticker)
        if prior is not None and start <= prior[1]:
            raise RuntimeError(f"OVERLAPPING_TICKER_IDENTITY_INTERVAL:{ticker}:{prior}:{(start, end)}")
        prior_by_ticker[ticker] = (start, end)


def main() -> int:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing authority artifact directory: {OUTPUT_DIR}")

    base = load_effective_authority(BASE_AUTHORITY_DIR)
    base_calendar = load_historical_trading_calendar(HISTORICAL_CALENDAR_PATH)
    old_boundary = str(base_calendar["last_trading_date"])

    rolling_manifest = load_rolling_authority(DEFAULT_ROLLING_AUTHORITY_DIR)
    _rolling_pit, rolling_calendar = validate_merged_authority_coherence(
        rolling_manifest,
        DEFAULT_ROLLING_AUTHORITY_DIR,
    )
    rolling_dates = tuple(str(day) for day in rolling_calendar.get("trading_dates", ()))
    extension_dates = tuple(
        day for day in rolling_dates if old_boundary < day <= EXECUTION_SUPPORT
    )
    if not extension_dates or extension_dates[-1] != EXECUTION_SUPPORT:
        raise RuntimeError("ROLLING_CALENDAR_DOES_NOT_COVER_EXECUTION_SUPPORT")
    if REQUESTED_EFFECTIVE_END not in extension_dates:
        raise RuntimeError("ROLLING_CALENDAR_DOES_NOT_COVER_P2_2_CUTOFF")

    source_summary = json.loads(ROLLING_SUMMARY_PATH.read_text(encoding="utf-8"))
    if (
        source_summary.get("status") != "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
        or source_summary.get("runner_status") != "COMPLETE"
        or int(source_summary.get("completed_count", -1)) != int(source_summary.get("target_count", -2))
        or not set(extension_dates).issubset(set(source_summary.get("authorized_dates", ())))
        or sha256_file(ROLLING_CHECKPOINT_PATH) != source_summary.get("checkpoint_manifest_sha256")
    ):
        raise RuntimeError("ROLLING_BASIC_INFO_ACQUISITION_SUMMARY_NOT_READY_FOR_EXTENSION")

    supplemental = load_supplemental_authority_records(SUPPLEMENTAL_AUTHORITY_DIR)
    extension = build_rolling_pit_extension(
        extension_calendar_dates=extension_dates,
        frozen_pit_path=base.pit_path,
        historical_calendar_path=HISTORICAL_CALENDAR_PATH,
        basic_info_raw_root=ROLLING_SOURCE_ROOT,
        acquisition_checkpoint_path=ROLLING_CHECKPOINT_PATH,
        supplemental_authority=supplemental,
    )
    if tuple(extension.merged_calendar_dates) != tuple(sorted(set(base_calendar["trading_dates"]) | set(extension_dates))):
        raise RuntimeError("MERGED_CALENDAR_DATE_SET_MISMATCH")
    if overlap_projection(base.pit_intervals, boundary=old_boundary) != overlap_projection(
        extension.merged_intervals,
        boundary=old_boundary,
    ):
        raise RuntimeError("HISTORICAL_PIT_OVERLAP_CHANGED")

    coverage_end = str(extension.merged_calendar_dates[-1])
    validate_intervals(extension.merged_intervals, coverage_end=coverage_end)
    if pit_denominator_manifest_sha256(extension.merged_intervals) == base.pit_sha256:
        raise RuntimeError("PIT_EXTENSION_DID_NOT_CHANGE_AUTHORITY")

    bounded_input = load_bounded_basic_info_snapshots(
        ROLLING_SOURCE_ROOT,
        extension_dates,
        checkpoint_path=ROLLING_CHECKPOINT_PATH,
    )
    if not bounded_input.ready:
        raise RuntimeError(f"BOUNDED_BASIC_INFO_NOT_READY:{bounded_input.errors}")
    classified = classify_full_universe(
        bounded_input.snapshots,
        expected_dates=extension_dates,
        supplemental_authority=supplemental,
    )
    unresolved = [
        {
            "ticker": ticker,
            "isu_cd": str(interval.get("ISU_CD") or ""),
            "market": str(interval.get("market") or ""),
            "effective_from": str(interval["effective_from"]),
            "effective_to": str(interval["effective_to"]),
            "reason": str(interval.get("classification_reason") or ""),
        }
        for ticker, rows in classified.items()
        for interval in rows
        if interval.get("classification") == "UNRESOLVED"
    ]
    frozen_identity_keys = {
        (str(row.get("ticker")), str(row.get("isu_cd")), str(row.get("market")))
        for row in base.pit_intervals
        if str(row.get("effective_to")) == old_boundary
    }
    unresolved_continuing_frozen_identities = [
        item
        for item in unresolved
        if (item["ticker"], item["isu_cd"], item["market"]) in frozen_identity_keys
    ]
    if unresolved_continuing_frozen_identities:
        raise RuntimeError(
            "UNRESOLVED_IDENTITY_INTERRUPTS_FROZEN_COMMON_CONTINUITY: "
            f"{unresolved_continuing_frozen_identities}"
        )

    p2_2_segments = [
        row
        for row in extension.merged_intervals
        if str(row["effective_from"]) <= REQUESTED_EFFECTIVE_END
        and str(row["effective_to"]) >= "2021-01-04"
    ]
    cutoff_tickers = {
        str(row["ticker"])
        for row in extension.merged_intervals
        if str(row["effective_from"]) <= REQUESTED_EFFECTIVE_END
        and str(row["effective_to"]) >= REQUESTED_EFFECTIVE_END
    }
    support_continuity_tickers = {
        str(row["ticker"])
        for row in extension.merged_intervals
        if str(row["effective_from"]) <= REQUESTED_EFFECTIVE_END
        and str(row["effective_to"]) >= EXECUTION_SUPPORT
    }
    if not p2_2_segments or not cutoff_tickers:
        raise RuntimeError("P2_2_POPULATION_BUILD_EMPTY")
    if coverage_end != EXECUTION_SUPPORT:
        raise RuntimeError(f"PIT_IDENTITY_SUPPORT_FRONTIER_MUST_STOP_AT_2026_09_01:{coverage_end}")

    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    builder_path = ROOT / "src/trend_scanner/data/rolling_market_data_refresh.py"
    write_merged_pit_extension(
        extension,
        OUTPUT_DIR,
        built_against_certified_through=old_boundary,
        target_as_of=EXECUTION_SUPPORT,
        source_basic_info_frontier=EXECUTION_SUPPORT,
        source_basic_info_acquired_at_utc=str(source_summary.get("completed_at_utc") or ""),
    )
    pit_output = OUTPUT_DIR / "merged_pit_intervals.json"
    calendar_output = OUTPUT_DIR / "merged_trading_calendar.json"
    pit_payload = json.loads(pit_output.read_text(encoding="utf-8"))
    calendar_payload = json.loads(calendar_output.read_text(encoding="utf-8"))
    if calendar_payload.get("calendar_frontier") != coverage_end:
        raise RuntimeError("PUBLISHED_CALENDAR_FRONTIER_MISMATCH")
    if pit_payload.get("pit_frontier") != max(str(row["effective_to"]) for row in extension.merged_intervals):
        raise RuntimeError("PUBLISHED_PIT_FRONTIER_MISMATCH")

    manifest = {
        "schema": "p2_2_identity_authority_extension_v01",
        "status": "PASS",
        "builder": "trend_scanner.data.rolling_market_data_refresh.build_rolling_pit_extension + write_merged_pit_extension",
        "builder_source_path": "src/trend_scanner/data/rolling_market_data_refresh.py",
        "builder_source_sha256": sha256_file(builder_path),
        "implementation_head": git_head,
        "base_authority_path": str(BASE_AUTHORITY_DIR.relative_to(ROOT)),
        "base_effective_pit_file_sha256": sha256_file(base.pit_path),
        "base_pit_manifest_sha256": base.pit_sha256,
        "base_interval_count": base.pit_count,
        "base_coverage_start": base_calendar["first_trading_date"],
        "base_coverage_end": old_boundary,
        "requested_effective_end": REQUESTED_EFFECTIVE_END,
        "execution_support": EXECUTION_SUPPORT,
        "coverage_start": base_calendar["first_trading_date"],
        "coverage_end": coverage_end,
        "extension_dates": list(extension_dates),
        "overlap_through_2026_08_21_preserved": True,
        "overlap_interval_projection_count": len(overlap_projection(extension.merged_intervals, boundary=old_boundary)),
        "new_common_interval_count": len(extension.merged_intervals) - base.pit_count,
        "new_ticker_count": extension.new_ticker_count,
        "pit_interval_count": len(extension.merged_intervals),
        "pit_manifest_sha256": pit_denominator_manifest_sha256(extension.merged_intervals),
        "pit_frontier": pit_payload.get("pit_frontier"),
        "calendar_frontier": calendar_payload.get("calendar_frontier"),
        "p2_2_overlapping_identity_segment_count": len(p2_2_segments),
        "p2_2_cutoff_common_ticker_count": len(cutoff_tickers),
        "execution_support_same_identity_ticker_count": len(support_continuity_tickers),
        "identity_interval_validation": "PASS",
        "duplicate_interval_count": 0,
        "overlapping_ticker_identity_count": 0,
        "unresolved_identity_count_fail_closed": len(unresolved),
        "unresolved_identities_fail_closed": unresolved,
        "unresolved_interruption_of_frozen_common_identity_count": 0,
        "source": {
            "authority": "KRX Open API Basic Info exact-date snapshots",
            "rolling_calendar_manifest_sha256": rolling_manifest.manifest_sha256,
            "rolling_calendar_file_sha256": sha256_file(DEFAULT_ROLLING_AUTHORITY_DIR / "merged_trading_calendar.json"),
            "rolling_acquisition_summary_path": str(ROLLING_SUMMARY_PATH.relative_to(ROOT)),
            "rolling_acquisition_summary_sha256": sha256_file(ROLLING_SUMMARY_PATH),
            "rolling_checkpoint_path": str(ROLLING_CHECKPOINT_PATH.relative_to(ROOT)),
            "rolling_checkpoint_sha256": sha256_file(ROLLING_CHECKPOINT_PATH),
            "supplemental_authority_directory": str(SUPPLEMENTAL_AUTHORITY_DIR.relative_to(ROOT)),
            "supplemental_authority_record_count": len(supplemental),
            "network_requests": 0,
        },
        "merged_pit_file_sha256": sha256_file(pit_output),
        "merged_calendar_file_sha256": sha256_file(calendar_output),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "p2_2_full_replay_executed": False,
        "other_window_executed": False,
    }
    write_json(OUTPUT_DIR / "p2_2_identity_authority_extension_manifest.json", manifest)
    print(json.dumps({
        "status": "P2_2_IDENTITY_AUTHORITY_EXTENSION_READY",
        "coverage_start": manifest["coverage_start"],
        "coverage_end": manifest["coverage_end"],
        "requested_effective_end": REQUESTED_EFFECTIVE_END,
        "execution_support": EXECUTION_SUPPORT,
        "base_interval_count": base.pit_count,
        "extended_interval_count": len(extension.merged_intervals),
        "new_common_interval_count": manifest["new_common_interval_count"],
        "new_ticker_count": extension.new_ticker_count,
        "p2_2_population_segments": len(p2_2_segments),
        "p2_2_cutoff_common_tickers": len(cutoff_tickers),
        "same_identity_execution_support_tickers": len(support_continuity_tickers),
        "unresolved_fail_closed_count": len(unresolved),
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
