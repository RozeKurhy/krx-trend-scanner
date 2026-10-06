from __future__ import annotations

import hashlib
import json

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    NAVER_DIRECT_PROVIDER_VERSION,
    NAVER_FETCH_PROVENANCE_ATTR,
    NAVER_FETCH_PROVENANCE_SCHEMA_VERSION,
    NaverDirectAdjustedPriceDataProvider,
)
from trend_scanner.data.adjusted_price_store import (
    NAVER_FETCH_PROVENANCE_FIELD,
    AdjustedPriceStore,
)
from trend_scanner.data.rolling_market_data_refresh import _merge_adjusted_frames


def _xml(*items: str, whitespace: str = "") -> str:
    return f"<protocol>{whitespace}<chartdata>" + "".join(
        f'<item data="{item}"/>{whitespace}' for item in items
    ) + "</chartdata></protocol>"


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code


class _Session:
    def __init__(self, *responses: _Response):
        self.responses = list(responses)

    def get(self, *args, **kwargs):
        return self.responses.pop(0)


def _fetch(text: str):
    provider = NaverDirectAdjustedPriceDataProvider(session=_Session(_Response(text)))
    frame = provider.load_daily("005930", "2024-01-02", "2024-01-03")
    return frame, frame.attrs[NAVER_FETCH_PROVENANCE_ATTR][0]


def test_identical_source_fetches_have_stable_raw_and_parsed_hashes():
    payload = _xml("20240102|100|110|90|105|10", whitespace="\n  ")
    first_frame, first = _fetch(payload)
    second_frame, second = _fetch(payload)

    assert first["raw_payload_sha256"] == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert first["raw_payload_sha256"] == second["raw_payload_sha256"]
    assert first["parsed_ohlc_sha256"] == second["parsed_ohlc_sha256"]
    assert first["parsed_row_count"] == second["parsed_row_count"] == 1
    assert first_frame.equals(second_frame)
    assert first["provider_version"] == NAVER_DIRECT_PROVIDER_VERSION
    assert first["source_descriptor"]["source_authority_id"] == "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1"
    assert pd.Timestamp(first["fetch_utc_timestamp"]).tz_convert("UTC") is not None
    assert first["http_status"] == 200


def test_xml_serialization_change_only_changes_raw_hash():
    compact = _xml("20240102|100|110|90|105|10")
    spaced = _xml("20240102|100|110|90|105|10", whitespace="\n  ")
    _, compact_event = _fetch(compact)
    _, spaced_event = _fetch(spaced)

    assert compact_event["raw_payload_sha256"] != spaced_event["raw_payload_sha256"]
    assert compact_event["parsed_ohlc_sha256"] == spaced_event["parsed_ohlc_sha256"]


def test_source_ohlc_change_changes_raw_and_parsed_hashes():
    _, original = _fetch(_xml("20240102|100|110|90|105|10"))
    _, revised = _fetch(_xml("20240102|100|110|90|106|10"))

    assert original["raw_payload_sha256"] != revised["raw_payload_sha256"]
    assert original["parsed_ohlc_sha256"] != revised["parsed_ohlc_sha256"]


def test_store_connects_each_fetch_to_post_write_hash_and_keeps_old_sidecars_readable(tmp_path):
    payload = _xml("20240102|100|110|90|105|10")
    first_frame, first = _fetch(payload)
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full(
        "005930",
        first_frame,
        metadata_context={"requested_start": "2024-01-02", "requested_end": "2024-01-02"},
    )
    first_metadata = store.load_metadata("005930")
    first_event = first_metadata[NAVER_FETCH_PROVENANCE_FIELD]["records"][0]
    assert first_metadata[NAVER_FETCH_PROVENANCE_FIELD]["schema_version"] == NAVER_FETCH_PROVENANCE_SCHEMA_VERSION
    assert first_event["saved_store_content_sha256"] == first_metadata["content_sha256"]
    assert hashlib.sha256((tmp_path / "adjusted" / "005930.parquet").read_bytes()).hexdigest() == first_metadata["content_sha256"]
    assert payload not in (tmp_path / "adjusted" / "005930.meta.json").read_text()

    second_frame, second = _fetch(_xml("20240103|101|111|91|106|10"))
    combined = pd.concat([store.load_daily("005930"), second_frame]).sort_index()
    combined.attrs.update(source_native_adjusted=True)
    combined.attrs[NAVER_FETCH_PROVENANCE_ATTR] = (second,)
    store.save_full(
        "005930",
        combined,
        metadata_context={"requested_start": "2024-01-02", "requested_end": "2024-01-03"},
    )
    metadata = store.load_metadata("005930")
    events = metadata[NAVER_FETCH_PROVENANCE_FIELD]["records"]
    assert len(events) == 2
    assert events[0]["saved_store_content_sha256"] == first_event["saved_store_content_sha256"]
    assert events[1]["saved_store_content_sha256"] == metadata["content_sha256"]
    assert metadata["content_sha256"] != first_metadata["content_sha256"]
    assert store.load_daily("005930").equals(combined)

    legacy_without_provenance = tmp_path / "adjusted" / "005930.meta.json"
    sidecar = json.loads(legacy_without_provenance.read_text())
    sidecar.pop(NAVER_FETCH_PROVENANCE_FIELD)
    legacy_without_provenance.write_text(json.dumps(sidecar))
    assert len(store.load_daily("005930")) == 2


def test_same_fetch_with_different_saved_rows_has_same_source_hashes_and_different_store_hashes(tmp_path):
    frame, event = _fetch(_xml("20240102|100|110|90|105|10"))
    changed = frame.copy()
    changed.loc[pd.Timestamp("2024-01-02"), "close"] = 106.0

    first_store = AdjustedPriceStore(tmp_path / "first")
    second_store = AdjustedPriceStore(tmp_path / "second")
    context = {"requested_start": "2024-01-02", "requested_end": "2024-01-02"}
    first_store.save_full("005930", frame, metadata_context=context)
    second_store.save_full("005930", changed, metadata_context=context)
    first_event = first_store.load_metadata("005930")[NAVER_FETCH_PROVENANCE_FIELD]["records"][0]
    second_event = second_store.load_metadata("005930")[NAVER_FETCH_PROVENANCE_FIELD]["records"][0]

    assert first_event["raw_payload_sha256"] == second_event["raw_payload_sha256"] == event["raw_payload_sha256"]
    assert first_event["parsed_ohlc_sha256"] == second_event["parsed_ohlc_sha256"] == event["parsed_ohlc_sha256"]
    assert first_event["saved_store_content_sha256"] != second_event["saved_store_content_sha256"]


def test_provenance_does_not_change_parquet_bytes_and_is_preserved_by_rolling_merge(tmp_path):
    first_frame, first_event = _fetch(_xml("20240102|100|110|90|105|10"))
    second_frame, second_event = _fetch(_xml("20240103|101|111|91|106|10"))
    merged = _merge_adjusted_frames(None, [first_frame, second_frame])
    assert len(merged.attrs[NAVER_FETCH_PROVENANCE_ATTR]) == 2

    with_provenance = AdjustedPriceStore(tmp_path / "with")
    without_provenance = AdjustedPriceStore(tmp_path / "without")
    without = merged.copy()
    without.attrs.pop(NAVER_FETCH_PROVENANCE_ATTR)
    requested = {"requested_start": "2024-01-02", "requested_end": "2024-01-03"}
    with_provenance.save_full("005930", merged, metadata_context=requested)
    without_provenance.save_full("005930", without, metadata_context=requested)

    with_meta = with_provenance.load_metadata("005930")
    without_meta = without_provenance.load_metadata("005930")
    assert with_meta["content_sha256"] == without_meta["content_sha256"]
    assert len(with_meta[NAVER_FETCH_PROVENANCE_FIELD]["records"]) == 2
    assert with_meta[NAVER_FETCH_PROVENANCE_FIELD]["records"][0]["raw_payload_sha256"] == first_event["raw_payload_sha256"]
    assert with_meta[NAVER_FETCH_PROVENANCE_FIELD]["records"][1]["raw_payload_sha256"] == second_event["raw_payload_sha256"]
    assert NAVER_FETCH_PROVENANCE_FIELD not in without_meta
