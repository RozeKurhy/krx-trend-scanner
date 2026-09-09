#!/usr/bin/env python3
"""Reconcile the active F7 output set with the corrected local PIT universe.

This performs no OpenDART or other network request and does not recalculate any
Fundamentals result.  It only separates stale output files already produced
under the prior authority and updates the active index/checkpoint summaries.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-09-04"
DATE_KEY = "20260904"
OUTPUT_ROOT = ROOT / "artifacts/fundamentals/production" / DATE_KEY
TICKERS_DIR = OUTPUT_ROOT / "tickers"
ARCHIVE_DIR = OUTPUT_ROOT / "archive/stale_outside_universe"
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.parquet"
CHECKPOINT_PATH = OUTPUT_ROOT / "daily_quota_checkpoint.json"
INDEX_PATH = OUTPUT_ROOT / "ticker_index.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def load_current_tickers() -> set[str]:
    frame = pd.read_parquet(METADATA_PATH)
    current = frame[frame["effective_date"].astype(str).str[:10] == AS_OF]
    tickers = set(current["ticker"].astype(str).str.strip().str.upper())
    if len(tickers) != len(current):
        raise RuntimeError("duplicate current metadata tickers")
    return tickers


def read_valid_outputs(expected: set[str]) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    valid: list[dict[str, Any]] = []
    outside: list[str] = []
    invalid = 0
    for path in sorted(TICKERS_DIR.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid += 1
            continue
        current_ticker = str(value.get("ticker") or "").strip().upper()
        if current_ticker != path.stem.upper() or value.get("requested_as_of") != AS_OF:
            invalid += 1
            continue
        if current_ticker not in expected:
            outside.append(current_ticker)
            continue
        valid.append(value)
    return valid, outside, {"invalid_output_count": invalid, "outside_universe_count": len(outside), "duplicate_payload_count": 0}


def update_index(valid_tickers: set[str]) -> None:
    rows: list[dict[str, str]] = []
    with INDEX_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            if str(row.get("ticker") or "").strip().upper() in valid_tickers:
                rows.append(row)
    rows.sort(key=lambda row: str(row.get("ticker") or ""))
    with INDEX_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def update_checkpoint(expected: set[str], valid: list[dict[str, Any]], outside: list[str], counts: dict[str, int]) -> None:
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    valid_tickers = {str(value["ticker"]).strip().upper() for value in valid}
    checkpoint["metadata_snapshot_date"] = AS_OF
    checkpoint["requested_as_of"] = AS_OF
    checkpoint["end_completed"] = len(valid_tickers)
    checkpoint["end_remaining"] = len(expected - valid_tickers)
    checkpoint["remaining_tickers"] = sorted(expected - valid_tickers)
    checkpoint["terminal_status_summary_completed"] = dict(sorted(Counter(str(value.get("terminal_status") or "") for value in valid).items()))
    checkpoint["active_universe_reconciliation"] = {
        "authority_date": AS_OF,
        "current_universe_count": len(expected),
        "active_valid_output_count": len(valid_tickers),
        "active_remaining_count": len(expected - valid_tickers),
        "outside_universe_count": len(outside),
        "invalid_output_count": counts["invalid_output_count"],
        "duplicate_payload_count": counts["duplicate_payload_count"],
        "archived_stale_output_count": len(outside),
        "archived_directory": str(ARCHIVE_DIR.relative_to(ROOT)),
        "opendart_recomputed": False,
    }
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_manifest(expected: set[str], valid: list[dict[str, Any]], outside: list[str], counts: dict[str, int]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    valid_tickers = {str(value["ticker"]).strip().upper() for value in valid}
    manifest["metadata_snapshot_date"] = AS_OF
    manifest["requested_as_of"] = AS_OF
    manifest["mode"] = "reconciled_active_output"
    manifest["final_status"] = "IN_PROGRESS"
    manifest["total_universe"] = len(expected)
    manifest["processed_ticker_count"] = len(valid_tickers)
    manifest["active_output_count"] = len(valid_tickers)
    manifest["remaining_ticker_count"] = len(expected - valid_tickers)
    manifest["outside_universe_count"] = len(outside)
    manifest["active_universe_reconciliation"] = {
        "authority": "data/reference/krx_instrument_metadata.parquet",
        "authority_date": AS_OF,
        "current_universe_count": len(expected),
        "active_valid_output_count": len(valid_tickers),
        "active_remaining_count": len(expected - valid_tickers),
        "output_integrity": counts,
        "archived_stale_output_count": len(outside),
        "archived_directory": str(ARCHIVE_DIR.relative_to(ROOT)),
        "calculation_or_filter_rule_changed": False,
        "opendart_recomputed": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    expected = load_current_tickers()
    valid, outside, counts = read_valid_outputs(expected)
    if outside:
        raise RuntimeError(f"active output still contains outside tickers: {outside}")
    valid_tickers = {str(value["ticker"]).strip().upper() for value in valid}
    update_index(valid_tickers)
    update_checkpoint(expected, valid, outside, counts)
    update_manifest(expected, valid, outside, counts)
    print(f"ACTIVE_OUTPUT={len(valid_tickers)} CURRENT_UNIVERSE={len(expected)} REMAINING={len(expected - valid_tickers)} OUTSIDE={len(outside)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
