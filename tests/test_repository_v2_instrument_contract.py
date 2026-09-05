from types import SimpleNamespace

import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository_v2_instrument_contract import (
    ETF_CONTRACT,
    SUPPORTED_INSTRUMENT_TYPES,
    repository_v2_contract_for,
    repository_v2_contract_for_metadata,
)


def test_common_and_etf_share_the_repository_v2_contract_surface():
    assert SUPPORTED_INSTRUMENT_TYPES == ("COMMON", "ETF")
    assert repository_v2_contract_for("ETF") == ETF_CONTRACT
    assert ETF_CONTRACT.volume_authority == ETF_CONTRACT.trading_value_authority
    assert "legacy" not in ETF_CONTRACT.raw_ohlc_authority.lower()


def test_etf_requires_formal_metadata_classification():
    formal = SimpleNamespace(asset_type="ETF", is_trusted_for_production=True)
    assert repository_v2_contract_for_metadata(formal).instrument_type == "ETF"
    heuristic = SimpleNamespace(asset_type="ETF", is_trusted_for_production=False)
    with pytest.raises(MarketDataError, match="INSTRUMENT_CLASSIFICATION_UNTRUSTED"):
        repository_v2_contract_for_metadata(heuristic)


def test_unknown_instrument_type_fails_closed():
    with pytest.raises(MarketDataError, match="UNSUPPORTED_INSTRUMENT_TYPE"):
        repository_v2_contract_for("ETN")
