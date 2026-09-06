"""Offline regression tests for MARKET_RS_AUTHORITY_ATTRIBUTION_FIX02."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository_v2 import (
    KNOWN_ADJUSTED_SOURCE_GAP_DATES,
    KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES,
    _project_analytic_sessions,
)
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parity = _load_script("market_rs_parity_fix02", "run_market_rs_parity_v01.py")
authority = _load_script(
    "market_rs_authority_attribution_fix02",
    "run_market_rs_authority_attribution_fix02.py",
)


def _pair(ticker: str = "446840", date: str = "2025-08-04") -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": date,
        "horizon": "12m",
        "legacy_value": 10.0,
        "repository_value": 20.0,
        "legacy_present": True,
        "repository_present": True,
    }


def _raw_row(*, ticker: str, date: str, placeholder: bool = False) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": pd.Timestamp(date),
        "open": 0 if placeholder else 10,
        "high": 0 if placeholder else 12,
        "low": 0 if placeholder else 9,
        "close": 11,
        "volume": 0 if placeholder else 100,
        "trading_value": 0 if placeholder else 1000,
        "market_cap": 100000,
        "listed_shares": 10000,
    }


def _base_gates() -> dict[str, object]:
    return {
        "unresolved_input_difference_count": 0,
        "unexpected_repository_error_count": 0,
        "current_run_executed": True,
        "current_population_input_count": 2,
        "current_output_row_count": 2,
        "current_silent_row_drop_count": 0,
    }


def test_next_state_routes_unresolved_authority_to_fix02() -> None:
    gates = _base_gates()
    gates["unresolved_input_difference_count"] = 1
    assert parity.derive_next_state(gates) == "NEEDS_MARKET_RS_AUTHORITY_ATTRIBUTION_FIX02"


def test_next_state_routes_repository_and_source_defects_before_generic_parity() -> None:
    gates = _base_gates()
    gates["repository_v2_defect_proven"] = True
    assert parity.derive_next_state(gates) == "NEEDS_REPOSITORY_V2_DEFECT_REVIEW"

    gates = _base_gates()
    gates["source_authority_defect_proven"] = True
    assert parity.derive_next_state(gates) == "NEEDS_MARKET_DATA_SOURCE_AUTHORITY_REVIEW"


def test_next_state_routes_other_parity_blocker_and_pass() -> None:
    gates = _base_gates()
    gates["formula_recalculation_mismatch_count"] = 1
    assert parity.derive_next_state(gates) == "NEEDS_MARKET_RS_PARITY_FIX02"
    assert parity.derive_next_state(_base_gates()) == "SECTOR_RS_PARITY_V01"


def test_horizon_flags_use_actual_finite_result_fields() -> None:
    class Result:
        market_rs_3m = 0.12
        market_rs_6m = float("nan")
        market_rs_12m = None

    assert parity._finite_field(Result(), "market_rs_3m") is True
    assert parity._finite_field(Result(), "market_rs_6m") is False
    assert parity._finite_field(Result(), "market_rs_12m") is False


def test_placeholder_pair_has_exact_nontrading_authority() -> None:
    adjusted = {"date": "2025-08-04", "close": 20.0}
    raw = _raw_row(ticker="123456", date="2025-08-04", placeholder=True)
    classification, evidence = authority._authority_for_pair(
        _pair(ticker="123456"), adjusted, {"source_authority_id": "not-used"}, raw
    )
    assert classification == "APPROVED_NONTRADING_EXCLUSION"
    assert evidence["authority_record_identifier"].startswith("NON_TRADING_PLACEHOLDER_V01")


def test_adjusted_authority_delta_requires_current_source_metadata() -> None:
    pair = _pair(ticker="123456", date="2025-08-05")
    adjusted = {"date": pair["date"], "close": 20.0}
    raw = _raw_row(ticker="123456", date=str(pair["date"]))
    classification, evidence = authority._authority_for_pair(
        pair,
        adjusted,
        {"source_authority_id": CURRENT_SOURCE_DESCRIPTOR.source_authority_id, "content_sha256": "abc"},
        raw,
    )
    assert classification == "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA"
    assert evidence["ratio_diagnostic_only"] is True


def test_unproven_ratio_difference_remains_unresolved() -> None:
    pair = _pair(ticker="123456", date="2025-08-05")
    raw = _raw_row(ticker="123456", date=str(pair["date"]))
    classification, evidence = authority._authority_for_pair(pair, None, None, raw)
    assert classification == "UNRESOLVED"
    assert evidence["authority_artifact_path"] == ""


def test_mixed_pair_authorities_do_not_become_ticker_level_unresolved() -> None:
    dates = ["2025-08-01", "2026-02-06", "2026-05-14"]
    legacy = pd.DataFrame(
        {"close": [2325.0, 1852.0, 1364.0]},
        index=pd.DatetimeIndex(dates),
    )
    repository = pd.DataFrame(
        {"close": [11625.0, 9260.0]},
        index=pd.DatetimeIndex(dates[:2]),
    )
    material_dates = {"12m": dates[0], "6m": dates[1], "3m": dates[2]}
    authority_map = {
        ("006740", dates[0]): {
            "final_classification": "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA",
            "authority_evidence": {"classification": "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA"},
        },
        ("006740", dates[1]): {
            "final_classification": "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA",
            "authority_evidence": {"classification": "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA"},
        },
        ("006740", dates[2]): {
            "final_classification": "APPROVED_NONTRADING_EXCLUSION",
            "authority_evidence": {"classification": "APPROVED_NONTRADING_EXCLUSION"},
        },
    }

    classification, differences, attributions = parity.material_input_comparison(
        "006740", legacy, repository, material_dates, None, authority_map
    )

    assert classification == "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA"
    assert len(differences) == 3
    assert {item["classification"] for item in attributions} == {
        "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA",
        "APPROVED_NONTRADING_EXCLUSION",
    }


def test_446840_pre_identity_sessions_project_with_identity_authority_exclusion() -> None:
    dates = [
        "2025-08-01", "2025-08-04", "2025-08-05", "2025-08-06",
        "2025-08-07", "2025-08-08", "2025-08-11", "2025-08-12",
        "2025-08-13", "2025-08-14",
    ]
    assert KNOWN_ADJUSTED_SOURCE_GAP_DATES == {}
    assert all(("446840", date) in KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES for date in dates[:-1])
    adjusted = pd.DataFrame(
        {"open": [40.0], "high": [42.0], "low": [39.0], "close": [41.0]},
        index=pd.DatetimeIndex([dates[-1]]),
    )
    raw = pd.DataFrame([_raw_row(ticker="446840", date=date) for date in dates]).set_index("date")
    raw.attrs["ticker"] = "446840"

    projected_adjusted, projected_raw, evidence = _project_analytic_sessions(adjusted, raw)

    assert evidence["known_adjusted_gap_dates"] == []
    assert evidence["rejected_raw_only_dates"] == []
    assert evidence["outside_identity_lifecycle_dates"] == dates[:-1]
    assert evidence["explicit_outside_identity_lifecycle_exclusion_count"] == 9
    assert evidence["projected_date_set_exact_match"] is True
    assert list(projected_adjusted.index) == [pd.Timestamp(dates[-1])]
    assert list(projected_raw.index) == [pd.Timestamp(dates[-1])]
    assert projected_adjusted.loc[pd.Timestamp("2025-08-14"), "close"] == 41.0


def test_unknown_raw_only_active_session_still_fails_closed() -> None:
    adjusted = pd.DataFrame(
        {"open": [40.0], "high": [42.0], "low": [39.0], "close": [41.0]},
        index=pd.DatetimeIndex(["2025-08-14"]),
    )
    raw = pd.DataFrame([_raw_row(ticker="123456", date="2025-08-04")]).set_index("date")
    raw.attrs["ticker"] = "123456"
    with pytest.raises(MarketDataError, match="REPOSITORY_V2_TRADING_SESSION_MISMATCH"):
        _project_analytic_sessions(adjusted, raw)
