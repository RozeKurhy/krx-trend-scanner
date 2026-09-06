from __future__ import annotations

import json

import pandas as pd

from trend_scanner.data.krx_etf_raw_provider import ETF_ENDPOINT, KrxRawEtfSnapshotProvider
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


class _Response:
    status = 200

    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()
        self.headers = {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _opener(request, timeout):
    assert request.full_url.endswith("/etp/etf_bydd_trd?basDd=20260821")
    assert request.get_method() == "GET"
    assert request.headers.get("Auth_key") == "secret"
    return _Response(
        {
            "OutBlock_1": [
                {
                    "BAS_DD": "20260821",
                    "ISU_CD": "069500",
                    "TDD_OPNPRC": "10,000",
                    "TDD_HGPRC": "10,500",
                    "TDD_LWPRC": "9,900",
                    "TDD_CLSPRC": "10,200",
                    "ACC_TRDVOL": "100",
                    "ACC_TRDVAL": "1,020,000",
                    "MKTCAP": "10,000,000",
                    "LIST_SHRS": "1,000",
                }
            ]
        }
    )


def test_etf_provider_uses_official_route_and_shared_auth_path(tmp_path):
    client = KrxOpenApiClient("secret", opener=_opener, max_transient_retries=0)
    frame = KrxRawEtfSnapshotProvider(client).fetch_snapshot("2026-08-21")
    assert frame.loc[0, "ticker"] == "069500"
    assert int(frame.loc[0, "trading_value"]) == 1_020_000
    assert client.audit[0]["url"].endswith(ETF_ENDPOINT)

    store = KrxRawStockStore(tmp_path / "raw")
    result = store.save_snapshot("ETF", "2026-08-21", frame, ETF_ENDPOINT)
    assert result.status == "COMPLETE"
    assert store.load_ticker("069500", "2026-08-21", "2026-08-21").shape[0] == 1
    assert store.get_manifest("ETF", "2026-08-21")["source_endpoint"] == ETF_ENDPOINT

