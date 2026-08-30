"""Hermetic tests for the authoritative Naver adjusted-price integration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_full_population import FullPopulationRunner
from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_source_authority import (
    AUTHORITY_DECISION_SHA256,
    CURRENT_SOURCE_DESCRIPTOR,
    load_adjusted_price_source_authority,
)
from trend_scanner.data.adjusted_price_store import (
    AdjustedPriceStore,
    LEGACY_SCHEMA_VERSION,
    LEGACY_STORE_VERSION,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.source_contracts import ADJUSTED_PRICE_AUTHORITY_CONTRACT


class Response:
    status_code = 200

    def __init__(self, text: str):
        self.text = text


class Session:
    def __init__(self, text: str, status_code: int = 200):
        self.response = Response(text)
        self.response.status_code = status_code
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _xml(*items: str) -> str:
    return "<protocol><chartdata>" + "".join(f'<item data="{item}"/>' for item in items) + "</chartdata></protocol>"


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [100.0, 101.0], "high": [110.0, 111.0], "low": [90.0, 91.0], "close": [105.0, 106.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )


def test_authority_loader_binds_exact_decision_sha():
    descriptor = load_adjusted_price_source_authority()
    assert descriptor == CURRENT_SOURCE_DESCRIPTOR
    assert descriptor.authority_decision_sha256 == AUTHORITY_DECISION_SHA256


def test_offline_authority_evidence_binds_package_contract():
    source = Path(__file__).resolve().parents[1] / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/authority_closure/v02/authority_closure_decision_v02.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == AUTHORITY_DECISION_SHA256
    assert payload["authority_closure"] == "CLOSED"
    assert payload["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert payload["production_integration_authorized"] is True
    assert payload["all_gates_passed"] is True
    assert payload["fix02_head"] == ADJUSTED_PRICE_AUTHORITY_CONTRACT["fix02_head"]
    assert payload["fix02_tree"] == ADJUSTED_PRICE_AUTHORITY_CONTRACT["fix02_tree"]


def test_runtime_authority_is_cwd_independent(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    session = Session(_xml("20240102|100|110|90|105|123"))
    provider = NaverDirectAdjustedPriceDataProvider(session=session)
    frame = provider.load_daily("005930", "2024-01-02", "2024-01-02")
    assert len(frame) == 1
    assert provider.source_descriptor == CURRENT_SOURCE_DESCRIPTOR
    with pytest.raises(MarketDataError, match="package-owned"):
        load_adjusted_price_source_authority(decision_path=tmp_path / "inaccessible.json")


def test_naver_positive_request_and_ohlc_only_output():
    session = Session(_xml("20240102|100|110|90|105|123", "20240103|101|111|91|106|456"))
    provider = NaverDirectAdjustedPriceDataProvider(session=session)
    frame = provider.load_daily(5930, "2024-01-02", "20240103")
    assert list(frame.columns) == ["open", "high", "low", "close"]
    assert frame.dtypes.tolist() == ["float64"] * 4
    assert session.calls[0][1]["params"] == {
        "symbol": "005930", "timeframe": "day", "count": "5000", "requestType": 1,
        "startTime": "20240102", "endTime": "20240103",
    }
    assert provider.call_audit() == {
        "logical_fetch_count": 1, "naver_http_call_count": 1,
        "successful_fetch_count": 1, "empty_fetch_count": 0,
        "error_fetch_count": 0, "pykrx_fallback_call_count": 0,
        "phantom_row_count": 0,
    }


def test_naver_alpha_and_empty_response():
    session = Session(_xml())
    provider = NaverDirectAdjustedPriceDataProvider(session=session)
    frame = provider.load_daily("0001A0", "2024-01-02", "2024-01-03")
    assert frame.empty and list(frame.columns) == ["open", "high", "low", "close"]
    assert session.calls[0][1]["params"]["symbol"] == "0001A0"
    assert provider.empty_fetch_count == 1


def test_naver_drops_exact_suspension_phantom_and_audits():
    session = Session(
        _xml(
            "20180427|52000|54000|51800|53000|100",
            "20180430|0|0|0|53000|0",
            "20180504|53000|53900|51800|51900|39565391",
        )
    )
    provider = NaverDirectAdjustedPriceDataProvider(session=session)

    frame = provider.load_daily("005930", "2018-04-11", "2018-06-20")

    assert list(frame.index.strftime("%Y-%m-%d")) == ["2018-04-27", "2018-05-04"]
    assert len(frame) == 2
    assert provider.phantom_row_count == 1
    assert provider.call_audit()["phantom_row_count"] == 1
    assert tuple(frame.columns) == ("open", "high", "low", "close")


@pytest.mark.parametrize(
    "payload",
    [
        _xml("20180430|0|0|0|0|0"),
        _xml("20180430|0|53000|52000|52500|100"),
        _xml("20180430|0|0|0|53000|100"),
        _xml("20180430|-1|0|0|53000|0"),
    ],
)
def test_naver_nonpositive_rows_are_adjudicated_source_nonusable(payload: str):
    provider = NaverDirectAdjustedPriceDataProvider(session=Session(payload))
    result = provider.load_daily("005930", "2018-04-11", "2018-06-20")
    assert result.empty
    assert provider.phantom_row_count == 0
    assert provider.source_nonusable_row_count == 1
    assert provider.pykrx_fallback_call_count == 0


def test_naver_relation_anomaly_is_source_truth_and_analytic_invalid():
    provider = NaverDirectAdjustedPriceDataProvider(
        session=Session(_xml("20240102|100|80|90|105|1"))
    )
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")
    assert len(result) == 1
    assert result.attrs["source_native_adjusted"] is True
    assert result.attrs["analytic_invalid_ohlc_count"] == 1
    assert result.loc[pd.Timestamp("2024-01-02"), "high"] == 80


@pytest.mark.parametrize(
    "payload",
    [
        '<chartdata><item data="20180430|52000|54000|51800|53000|100"/></chartdata>',
        "<protocol></protocol>",
    ],
)
def test_naver_wrong_root_or_missing_chartdata_fails_closed(payload: str):
    provider = NaverDirectAdjustedPriceDataProvider(session=Session(payload))

    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2018-04-11", "2018-06-20")


def test_naver_protocol_chartdata_empty_is_typed_empty():
    provider = NaverDirectAdjustedPriceDataProvider(session=Session("<protocol><chartdata></chartdata></protocol>"))

    frame = provider.load_daily("0001A0", "2024-01-02", "2024-01-03")

    assert frame.empty
    assert tuple(frame.columns) == ("open", "high", "low", "close")
    assert provider.empty_fetch_count == 1


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "<chartdata>",
        _xml("20240102|100|110|90|105"),
        _xml("20240102|100|110|90|105|1|extra"),
        _xml("2024xx02|100|110|90|105|1"),
        _xml("20240102|100|110|90|105|1", "20240102|100|110|90|105|1"),
        _xml("20240104|100|110|90|105|1"),
    ],
)
def test_naver_malformed_payloads_fail_closed(payload: str):
    provider = NaverDirectAdjustedPriceDataProvider(session=Session(payload))
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")
    assert provider.pykrx_fallback_call_count == 0
    assert provider.error_fetch_count == 1


def test_naver_transport_error_has_no_pykrx_fallback():
    class FailingSession:
        def get(self, *args, **kwargs):
            raise TimeoutError("synthetic timeout")

    provider = NaverDirectAdjustedPriceDataProvider(session=FailingSession())
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")
    assert provider.pykrx_fallback_call_count == 0
    assert provider.naver_http_call_count == 1


def test_store_v02_roundtrip_and_wrong_descriptor_rejection(tmp_path: Path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame(), source_descriptor=CURRENT_SOURCE_DESCRIPTOR)
    metadata = store.load_metadata("005930")
    assert metadata["schema_version"] == "ADJUSTED_PRICE_V02"
    assert metadata["source_authority_id"] == CURRENT_SOURCE_DESCRIPTOR.source_authority_id
    assert store.is_current_authority_snapshot("005930") is True
    expected_hash = hashlib.sha256((tmp_path / "005930.parquet").read_bytes()).hexdigest()
    assert metadata["content_sha256"] == expected_hash

    wrong = CURRENT_SOURCE_DESCRIPTOR.as_dict() | {"source_name": "PYKRX_ADJUSTED_PRICE"}
    with pytest.raises(MarketDataError, match="PROVIDER_AUTHORITY_MISMATCH"):
        store.save_full("000660", _frame(), source_descriptor=wrong)


def test_legacy_v01_remains_readable_but_non_current(tmp_path: Path):
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", _frame())
    parquet = tmp_path / "005930.parquet"
    metadata_path = tmp_path / "005930.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "schema_version": LEGACY_SCHEMA_VERSION,
            "store_version": LEGACY_STORE_VERSION,
            "source_name": "PYKRX_ADJUSTED_PRICE",
            "source_endpoint": "pykrx.stock.get_market_ohlcv_by_date(adjusted=True)",
        }
    )
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert not store.is_current_authority_snapshot("005930")
    assert len(store.load_daily("005930")) == 2


def test_full_population_defaults_to_naver_and_rejects_spoof(tmp_path: Path):
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    assert isinstance(runner.provider, NaverDirectAdjustedPriceDataProvider)

    class Spoof:
        source_descriptor = CURRENT_SOURCE_DESCRIPTOR.as_dict() | {"source_name": "PYKRX_ADJUSTED_PRICE"}

        def load_daily(self, ticker, start, end):
            return _frame()

    with pytest.raises(MarketDataError, match="PROVIDER_AUTHORITY_MISMATCH"):
        runner._validate_provider_authority(Spoof())
