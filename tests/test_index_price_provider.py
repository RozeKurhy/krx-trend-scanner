"""Regression tests for the local/lazy boundaries of the index provider."""

from __future__ import annotations

from pathlib import Path
import sys
import types

import pandas as pd

from trend_scanner.data.index_price_provider import IndexPriceDataProvider


def test_build_sector_mapping_lazy_import_and_contract(tmp_path: Path, monkeypatch):
    """Mocked sector PDF calls execute without NameError or network access."""
    stock = types.ModuleType("pykrx.stock")
    stock.get_index_ticker_name = lambda code: f"sector-{code}"
    stock.get_index_portfolio_deposit_file = lambda code, date: ["1", "000002"]
    pykrx = types.ModuleType("pykrx")
    pykrx.stock = stock
    monkeypatch.setitem(sys.modules, "pykrx", pykrx)
    monkeypatch.setitem(sys.modules, "pykrx.stock", stock)

    output_csv = tmp_path / "sector_mapping.csv"
    output_meta = tmp_path / "sector_mapping.json"
    result = IndexPriceDataProvider().build_sector_mapping(
        as_of="2026-08-14",
        output_csv=output_csv,
        output_meta=output_meta,
        delay_sec=0,
        max_retries=1,
    )

    assert output_csv.exists()
    assert output_meta.exists()
    assert list(result["ticker"]) == ["000001", "000002"]
    assert set(result["market"]) == {"KOSPI"}
    assert set(result["effective_date"]) == {"2026-08-14"}
    loaded = pd.read_csv(output_csv, dtype={"ticker": str, "sector_code": str})
    assert loaded.equals(result)
    assert not result.duplicated(subset=["ticker", "effective_date"]).any()
