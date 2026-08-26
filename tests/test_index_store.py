"""Offline contract tests for INDEX_STORE_V01."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import INDEX_STORE_COLUMNS, IndexStore, MARKET_INDEX_FAMILY


def _frame(*dates: str) -> pd.DataFrame:
    rows = []
    for day in dates:
        for code, name, source in (("1001", "코스피", "KOSPI"), ("2001", "코스닥", "KOSDAQ")):
            rows.append({
                "date": day, "family": MARKET_INDEX_FAMILY, "source_index_class": source,
                "index_code": code, "index_name": name, "open": 100.0, "high": 110.0,
                "low": 90.0, "close": 105.0, "volume": 10, "trading_value": 20.0,
            })
    return pd.DataFrame(rows, columns=list(INDEX_STORE_COLUMNS))


def test_save_load_schema_hash_and_deterministic_order(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-15", "2026-08-14"))
    loaded = store.load_family(MARKET_INDEX_FAMILY)
    assert list(loaded.columns) == list(INDEX_STORE_COLUMNS)
    assert loaded[["date", "index_code"]].values.tolist() == [["2026-08-14", "1001"], ["2026-08-14", "2001"], ["2026-08-15", "1001"], ["2026-08-15", "2001"]]
    assert store.verify_family(MARKET_INDEX_FAMILY)["status"] == "PASS"


@pytest.mark.parametrize("field,value", [("index_code", "9999"), ("volume", -1), ("open", float("nan")), ("trading_value", float("inf"))])
def test_invalid_contract_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    frame = _frame("2026-08-14")
    frame.loc[0, field] = value
    with pytest.raises(MarketDataError):
        IndexStore(tmp_path).save_family_full(MARKET_INDEX_FAMILY, frame)


def test_duplicate_key_fails(tmp_path: Path) -> None:
    frame = pd.concat([_frame("2026-08-14"), _frame("2026-08-14").iloc[[0]]], ignore_index=True)
    with pytest.raises(MarketDataError, match="DUPLICATE"):
        IndexStore(tmp_path).save_family_full(MARKET_INDEX_FAMILY, frame)


def test_filters_return_typed_empty(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-14"))
    empty = store.load_family(MARKET_INDEX_FAMILY, start="2027-01-01")
    assert empty.empty
    assert list(empty.columns) == list(INDEX_STORE_COLUMNS)


def test_tampered_parquet_and_metadata_are_detected(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-14"))
    parquet = tmp_path / "market_index.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")
    with pytest.raises(MarketDataError, match="HASH"):
        store.verify_family(MARKET_INDEX_FAMILY)

    store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-14"))
    meta = tmp_path / "market_index.meta.json"
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["row_count"] = 999
    meta.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MarketDataError):
        store.verify_family(MARKET_INDEX_FAMILY)


def test_failed_new_dataset_does_not_replace_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IndexStore(tmp_path)
    store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-14"))
    before = (tmp_path / "market_index.parquet").read_bytes(), (tmp_path / "market_index.meta.json").read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    with pytest.raises(OSError):
        store.save_family_full(MARKET_INDEX_FAMILY, _frame("2026-08-15"))
    assert before == ((tmp_path / "market_index.parquet").read_bytes(), (tmp_path / "market_index.meta.json").read_bytes())
