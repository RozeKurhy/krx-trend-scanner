from __future__ import annotations

import pandas as pd

from scripts.finalize_etf_36_sentinel_closure_validator_v01 import (
    normalize_exit_missing_values,
    validate_existing_artifacts,
    validate_exit_field_consistency,
)


def _trade(status: str, *, signal: object, execution: object, price: object) -> pd.DataFrame:
    return pd.DataFrame([{
        "trade_status": status,
        "exit_signal_date": signal,
        "exit_execution_date": execution,
        "exit_price_raw_open": price,
    }])


def test_open_trade_empty_exit_cells_are_missing() -> None:
    normalized, counts = normalize_exit_missing_values(
        _trade("OPEN_AT_CUTOFF", signal="", execution="", price="")
    )

    assert counts == {"exit_signal_date": 1, "exit_execution_date": 1, "exit_price_raw_open": 1}
    assert validate_exit_field_consistency(normalized)["passed"]


def test_open_trade_whitespace_exit_cells_are_missing() -> None:
    normalized, counts = normalize_exit_missing_values(
        _trade("OPEN_AT_CUTOFF", signal=" \t ", execution="\n", price="   ")
    )

    assert counts == {"exit_signal_date": 1, "exit_execution_date": 1, "exit_price_raw_open": 1}
    assert validate_exit_field_consistency(normalized)["passed"]


def test_realized_trade_with_all_exit_fields_passes() -> None:
    normalized, _ = normalize_exit_missing_values(
        _trade("REALIZED", signal="2024-01-02", execution="2024-01-03", price=100.0)
    )

    result = validate_exit_field_consistency(normalized)
    assert result["passed"]
    assert result["realized_missing_exit_fields_by_name"] == {
        "exit_signal_date": 0,
        "exit_execution_date": 0,
        "exit_price_raw_open": 0,
    }


def test_realized_trade_with_missing_exit_field_fails() -> None:
    normalized, _ = normalize_exit_missing_values(
        _trade("REALIZED", signal="2024-01-02", execution=" ", price=100.0)
    )

    result = validate_exit_field_consistency(normalized)
    assert not result["passed"]
    assert "REALIZED_EXIT_FIELDS_MISSING" in result["errors"]


def test_frozen_certified_ledger_passes_validator() -> None:
    result = validate_existing_artifacts()

    assert result["passed"], result
    assert result["counts"]["open_trade_count"] == 181
    assert result["counts"]["open_missing_exit_execution_count"] == 181
    assert result["counts"]["open_missing_exit_price_count"] == 181
    assert result["counts"]["realized_trade_count"] == 324
