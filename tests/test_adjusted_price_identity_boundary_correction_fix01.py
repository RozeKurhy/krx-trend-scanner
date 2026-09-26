"""test_adjusted_price_identity_boundary_correction_fix01.py

Offline acceptance tests for the identity-boundary correction.
"""

from __future__ import annotations

import csv
from collections import Counter
import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.repository_v2 import (
    KNOWN_ADJUSTED_SOURCE_GAP_DATES,
    KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES,
    _project_analytic_sessions,
)


ROOT = Path(__file__).resolve().parents[1]
FIX02 = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix02"


def test_ticker_continuity_is_not_identity_continuity() -> None:
    regression = json.loads((FIX02 / "validation/446840_regression.json").read_text(encoding="utf-8"))
    assert regression["status"] == "PASS"
    assert regression["ticker"] == "446840"
    assert regression["canonical_requested_start"] == regression["canonical_date_min"] == "2025-08-14"
    assert regression["source_row_exists_pre_boundary"] is True
    assert regression["identity_eligible_pre_boundary"] is False
    assert regression["analytic_eligible_pre_boundary"] is False
    assert regression["invariants_passed"] is True


def test_source_presence_is_preserved_but_not_analytic_eligibility() -> None:
    regression = json.loads((FIX02 / "validation/446840_regression.json").read_text(encoding="utf-8"))
    assert regression["source_row_exists_pre_boundary"] is True
    assert regression["identity_eligible_pre_boundary"] is False
    assert regression["analytic_eligible_pre_boundary"] is False
    assert regression["known_adjusted_source_gap_dates_contains_446840"] is False
    assert regression["network_requests"] == 0


def test_identity_authority_excludes_exact_pre_boundary_pairs_without_gap_fallback() -> None:
    dates = [
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06",
        "2025-08-07", "2025-08-08", "2025-08-11", "2025-08-12",
        "2025-08-13", "2025-08-14",
    ]
    adjusted = pd.DataFrame(
        {"open": [40.0], "high": [42.0], "low": [39.0], "close": [41.0]},
        index=pd.DatetimeIndex([dates[-1]]),
    )
    raw = pd.DataFrame(
        {
            "ticker": ["446840"] * len(dates),
            "open": [40] * len(dates), "high": [42] * len(dates),
            "low": [39] * len(dates), "close": [41] * len(dates),
            "volume": [10] * len(dates), "trading_value": [10] * len(dates),
            "market_cap": [100] * len(dates), "listed_shares": [100] * len(dates),
        },
        index=pd.DatetimeIndex(dates),
    )
    raw.attrs["ticker"] = "446840"
    _, projected_raw, evidence = _project_analytic_sessions(adjusted, raw)
    assert KNOWN_ADJUSTED_SOURCE_GAP_DATES == {}
    assert evidence["outside_identity_lifecycle_dates"] == dates[:-1]
    assert list(projected_raw.index) == [pd.Timestamp("2025-08-14")]


def test_true_same_identity_repair_path_remains_storage_compatible(tmp_path: Path) -> None:
    """An explicit same-identity repair can still write a bounded leading interval."""

    store = AdjustedPriceStore(tmp_path)
    frame = pd.DataFrame(
        {"open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5], "close": [10.2, 11.2]},
        index=pd.DatetimeIndex(["2025-01-02", "2025-01-03"]),
    )
    frame.attrs["source_native_adjusted"] = True
    store.save_full("999999", frame, metadata_context={"requested_start": "2025-01-02", "requested_end": "2025-01-03"})
    restored = store.load_daily("999999")
    assert restored.index.min() == pd.Timestamp("2025-01-02")
    assert len(restored) == 2
    assert ("999999", "2025-01-02") not in KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES


def test_candidate_audit_closes_the_exact_46_without_silent_drop() -> None:
    audit_dir = FIX02 / "missing_raw"
    summary = json.loads((audit_dir / "missing_raw_summary.json").read_text(encoding="utf-8"))
    assert summary["input_population_count"] == summary["output_census_count"] == 660
    assert summary["unique_identity_count"] == 660
    assert summary["silent_drop_count"] == 0
    assert summary["raw_cache_absence_is_source_absence_proof"] is False
    assert summary["broad_live_scan_performed"] is False
    with (audit_dir / "missing_raw_identity_census.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == summary["output_census_count"]
    assert len({(row["ticker"], row["first_common_date"], row["last_common_date"]) for row in rows}) == summary["unique_identity_count"]
    observed = Counter(row["risk_classification"] for row in rows)
    assert {key: observed.get(key, 0) for key in summary["risk_classification_counts"]} == summary["risk_classification_counts"]


def test_previously_captured_naver_response_is_offline_and_no_fallback() -> None:
    # Versioned synthetic Naver protocol fixture: parser coverage without
    # depending on a retired live-response artifact.
    dates = [
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06", "2025-08-07",
        "2025-08-08", "2025-08-11", "2025-08-12", "2025-08-13", "2025-08-14",
    ]
    response = "<protocol><chartdata>" + "".join(
        f'<item data="{date.replace("-", "")}|40|42|39|41|10"/>' for date in dates
    ) + "</chartdata></protocol>"

    class _Response:
        status_code = 200

        def __init__(self, text: str):
            self.text = text

    class _Session:
        def get(self, *args, **kwargs):
            return _Response(response)

    provider = NaverDirectAdjustedPriceDataProvider(session=_Session())
    frame = provider.load_daily("446840", "2025-08-01", "2025-08-14")
    assert len(frame) == 10
    assert frame.index.min() == pd.Timestamp("2025-08-01")
    assert frame.index.max() == pd.Timestamp("2025-08-14")
    assert provider.pykrx_fallback_call_count == 0
