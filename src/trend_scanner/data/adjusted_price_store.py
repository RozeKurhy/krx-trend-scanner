"""Persistent, mutable adjusted-OHLC store with sidecar provenance."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any, Mapping

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    normalize_ticker,
    validate_adjusted_ohlc,
)
from trend_scanner.data.errors import MarketDataError


DEFAULT_ADJUSTED_PRICE_STORE_DIR = Path("data/market/adjusted/stocks")
PHYSICAL_COLUMNS = ("date", "ticker", "open", "high", "low", "close")
SCHEMA_VERSION = "ADJUSTED_PRICE_V01"
STORE_VERSION = "ADJUSTED_PRICE_STORE_V01"
SOURCE_NAME = "PYKRX_ADJUSTED_PRICE"
SOURCE_ENDPOINT = "pykrx.stock.get_market_ohlcv_by_date(adjusted=True)"
SOURCE_SEMANTICS = "ADJUSTED_OHLC_ONLY"
AUTHORITY_TYPE = "AUTHORITATIVE"
_SECRET_MARKERS = ("KRX_OPEN_API_AUTH_KEY", "KRX_ID", "KRX_PW")
_CALLER_METADATA_FIELDS = frozenset(("requested_start", "requested_end"))
_RESERVED_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "store_version",
        "ticker",
        "source_name",
        "source_endpoint",
        "source_semantics",
        "authority_type",
        "actual_date_min",
        "actual_date_max",
        "row_count",
        "ticker_count",
        "generated_at",
        "last_success_at",
        "content_sha256",
    }
)
_METADATA_FIELDS = (
    "schema_version",
    "store_version",
    "ticker",
    "source_name",
    "source_endpoint",
    "source_semantics",
    "authority_type",
    "requested_start",
    "requested_end",
    "actual_date_min",
    "actual_date_max",
    "row_count",
    "ticker_count",
    "generated_at",
    "last_success_at",
    "content_sha256",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_date(value: Any) -> str:
    return pd.Timestamp(value).date().isoformat()


def _normalise_requested_date(value: Any, field: str) -> str:
    try:
        return _iso_date(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"metadata {field}가 유효한 date-like 값이 아닙니다: {value!r}") from exc


def _normalise_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Extract a strict OHLC frame and optional input ticker column."""

    if not isinstance(frame, pd.DataFrame):
        raise MarketDataError("AdjustedPriceStore 입력은 pandas DataFrame이어야 합니다.")
    columns = set(frame.columns)
    ticker_value: str | None = None
    if "ticker" in columns:
        expected = set(ADJUSTED_OHLC_COLUMNS) | {"ticker"}
        if columns != expected:
            raise MarketDataError(f"입력 frame schema가 잘못되었습니다: {list(frame.columns)}")
        ticker_values = frame["ticker"].map(normalize_ticker)
        if ticker_values.nunique(dropna=False) != 1:
            raise MarketDataError("하나의 ticker snapshot에 여러 종목코드가 섞였습니다.")
        ticker_value = str(ticker_values.iloc[0]) if not ticker_values.empty else None
        frame = frame.drop(columns=["ticker"])
    elif tuple(frame.columns) != ADJUSTED_OHLC_COLUMNS:
        raise MarketDataError(f"입력 frame schema가 정확히 OHLC가 아닙니다: {list(frame.columns)}")

    try:
        index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="raise"))
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"거래일 index 변환에 실패했습니다: {exc}") from exc
    if index.tz is not None:
        index = index.tz_localize(None)
    result = frame.copy()
    result.index = index.rename(None)
    for column in ADJUSTED_OHLC_COLUMNS:
        numeric = pd.to_numeric(result[column], errors="coerce")
        if numeric.isna().any():
            raise MarketDataError(f"{column}에 숫자로 변환할 수 없는 값 또는 NaN이 있습니다.")
        result[column] = numeric.astype("float64")
    validate_adjusted_ohlc(result)
    return result[list(ADJUSTED_OHLC_COLUMNS)], ticker_value


def _physical_to_frame(physical: pd.DataFrame, expected_ticker: str) -> pd.DataFrame:
    if tuple(physical.columns) != PHYSICAL_COLUMNS:
        raise MarketDataError(f"Parquet physical schema가 잘못되었습니다: {list(physical.columns)}")
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(physical["date"], errors="raise"))
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"Parquet date column 변환에 실패했습니다: {exc}") from exc
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    try:
        tickers = physical["ticker"].map(normalize_ticker)
    except MarketDataError:
        raise
    if tickers.nunique(dropna=False) != 1 or tickers.iloc[0] != expected_ticker:
        raise MarketDataError("Parquet ticker column과 요청 ticker가 일치하지 않습니다.")
    frame = physical[list(ADJUSTED_OHLC_COLUMNS)].copy()
    frame.index = dates.rename(None)
    for column in ADJUSTED_OHLC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    validate_adjusted_ohlc(frame)
    return frame


def _assert_no_secret_metadata(metadata: Mapping[str, Any]) -> None:
    serialized = json.dumps(dict(metadata), ensure_ascii=False)
    if any(marker in serialized for marker in _SECRET_MARKERS):
        raise MarketDataError("metadata에 credential marker를 기록할 수 없습니다.")


def _validate_metadata(metadata: Mapping[str, Any], ticker: str, frame: pd.DataFrame, digest: str) -> None:
    missing = [field for field in _METADATA_FIELDS if field not in metadata]
    if missing:
        raise MarketDataError(f"metadata 필드가 부족합니다: {missing}")
    _assert_no_secret_metadata(metadata)
    if metadata["schema_version"] != SCHEMA_VERSION or metadata["store_version"] != STORE_VERSION:
        raise MarketDataError("metadata schema/store version이 일치하지 않습니다.")
    if normalize_ticker(metadata["ticker"]) != ticker:
        raise MarketDataError("metadata ticker가 요청 ticker와 일치하지 않습니다.")
    if metadata["source_name"] != SOURCE_NAME or metadata["source_semantics"] != SOURCE_SEMANTICS:
        raise MarketDataError("metadata source provenance가 AdjustedPriceStore 계약과 다릅니다.")
    if metadata["source_endpoint"] != SOURCE_ENDPOINT:
        raise MarketDataError("metadata source_endpoint가 AdjustedPriceStore 계약과 다릅니다.")
    if metadata["authority_type"] != AUTHORITY_TYPE:
        raise MarketDataError("metadata authority_type이 AUTHORITATIVE가 아닙니다.")
    if int(metadata["ticker_count"]) != 1 or int(metadata["row_count"]) != len(frame):
        raise MarketDataError("metadata row/ticker count가 parquet와 일치하지 않습니다.")
    if not frame.empty:
        if metadata["actual_date_min"] != _iso_date(frame.index.min()) or metadata["actual_date_max"] != _iso_date(frame.index.max()):
            raise MarketDataError("metadata date bounds가 parquet와 일치하지 않습니다.")
    if metadata["content_sha256"] != digest:
        raise MarketDataError("metadata content_sha256와 parquet hash가 일치하지 않습니다.")
    requested_start = _normalise_requested_date(metadata["requested_start"], "requested_start")
    requested_end = _normalise_requested_date(metadata["requested_end"], "requested_end")
    if requested_start > requested_end:
        raise MarketDataError("metadata requested_start가 requested_end보다 늦습니다.")
    if not frame.empty and (
        _iso_date(frame.index.min()) < requested_start
        or _iso_date(frame.index.max()) > requested_end
    ):
        raise MarketDataError("metadata requested bounds가 실제 frame 범위를 포함하지 않습니다.")
    for field in ("generated_at", "last_success_at"):
        timestamp = pd.Timestamp(metadata[field])
        if timestamp.tzinfo is None:
            raise MarketDataError(f"metadata {field}가 timezone-aware가 아닙니다.")


class AdjustedPriceStore:
    """Ticker-scoped full-replacement store for adjusted OHLC history."""

    def __init__(self, base_dir: Path | str = DEFAULT_ADJUSTED_PRICE_STORE_DIR) -> None:
        self.base_dir = Path(base_dir)

    def _parquet_path(self, ticker: str) -> Path:
        return self.base_dir / f"{normalize_ticker(ticker)}.parquet"

    def _metadata_path(self, ticker: str) -> Path:
        return self.base_dir / f"{normalize_ticker(ticker)}.meta.json"

    def exists(self, ticker: str) -> bool:
        return self._parquet_path(ticker).exists() and self._metadata_path(ticker).exists()

    def load_metadata(self, ticker: str) -> dict[str, Any]:
        path = self._metadata_path(ticker)
        if not path.exists():
            if self._parquet_path(ticker).exists():
                raise MarketDataError("Parquet는 존재하지만 metadata sidecar가 없습니다.")
            raise FileNotFoundError(path)
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketDataError(f"metadata를 읽을 수 없습니다: {path}") from exc
        if not isinstance(metadata, dict):
            raise MarketDataError("metadata가 JSON object가 아닙니다.")
        return metadata

    def _read_pair(self, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
        normalized = normalize_ticker(ticker)
        parquet_path = self._parquet_path(normalized)
        metadata_path = self._metadata_path(normalized)
        if not parquet_path.exists() and not metadata_path.exists():
            raise FileNotFoundError(parquet_path)
        if not parquet_path.exists() or not metadata_path.exists():
            raise MarketDataError("Parquet와 metadata sidecar pair가 완전하지 않습니다.")
        digest = _sha256(parquet_path)
        metadata = self.load_metadata(normalized)
        try:
            physical = pd.read_parquet(parquet_path)
        except Exception as exc:
            raise MarketDataError(f"Parquet를 읽을 수 없습니다: {parquet_path}") from exc
        frame = _physical_to_frame(physical, normalized)
        _validate_metadata(metadata, normalized, frame, digest)
        return frame, metadata

    def load_daily(self, ticker: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        frame, _ = self._read_pair(ticker)
        if start is not None:
            frame = frame.loc[pd.Timestamp(start):]
        if end is not None:
            frame = frame.loc[:pd.Timestamp(end)]
        return frame.copy()

    def save_full(self, ticker: str, frame: pd.DataFrame, metadata_context: Mapping[str, Any] | None = None) -> None:
        normalized = normalize_ticker(ticker)
        adjusted, input_ticker = _normalise_frame(frame)
        if input_ticker is not None and input_ticker != normalized:
            raise MarketDataError("입력 ticker column과 요청 ticker가 일치하지 않습니다.")
        if adjusted.empty:
            raise MarketDataError("empty adjusted price snapshot은 저장할 수 없습니다.")

        self.base_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temp_parquet = self.base_dir / f".{normalized}.parquet.tmp_{token}"
        temp_metadata = self.base_dir / f".{normalized}.meta.json.tmp_{token}"
        final_parquet = self._parquet_path(normalized)
        final_metadata = self._metadata_path(normalized)
        context = dict(metadata_context or {})
        unknown_keys = set(context) - _CALLER_METADATA_FIELDS
        if unknown_keys:
            raise MarketDataError(
                "metadata_context에 Store-owned 또는 허용되지 않은 field가 있습니다: "
                f"{sorted(unknown_keys)}"
            )
        now = datetime.now(timezone.utc).isoformat()
        requested_start = _normalise_requested_date(
            context.get("requested_start", adjusted.index.min()), "requested_start"
        )
        requested_end = _normalise_requested_date(
            context.get("requested_end", adjusted.index.max()), "requested_end"
        )
        if requested_start > requested_end:
            raise MarketDataError("requested_start가 requested_end보다 늦습니다.")
        if _iso_date(adjusted.index.min()) < requested_start or _iso_date(adjusted.index.max()) > requested_end:
            raise MarketDataError("requested bounds가 입력 frame 범위를 포함하지 않습니다.")
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "store_version": STORE_VERSION,
            "ticker": normalized,
            "source_name": SOURCE_NAME,
            "source_endpoint": SOURCE_ENDPOINT,
            "source_semantics": SOURCE_SEMANTICS,
            "authority_type": AUTHORITY_TYPE,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "actual_date_min": _iso_date(adjusted.index.min()),
            "actual_date_max": _iso_date(adjusted.index.max()),
            "row_count": int(len(adjusted)),
            "ticker_count": 1,
            "generated_at": now,
            "last_success_at": now,
            "content_sha256": "",
        }
        _assert_no_secret_metadata(metadata)

        physical = pd.DataFrame(
            {
                "date": adjusted.index,
                "ticker": [normalized] * len(adjusted),
                "open": adjusted["open"].to_numpy(dtype="float64"),
                "high": adjusted["high"].to_numpy(dtype="float64"),
                "low": adjusted["low"].to_numpy(dtype="float64"),
                "close": adjusted["close"].to_numpy(dtype="float64"),
            },
            columns=list(PHYSICAL_COLUMNS),
        )
        old_parquet_backup = self.base_dir / f".{normalized}.parquet.backup_{token}"
        old_metadata_backup = self.base_dir / f".{normalized}.meta.json.backup_{token}"
        parquet_replaced = False
        metadata_replaced = False
        try:
            physical.to_parquet(temp_parquet, index=False)
            read_back = pd.read_parquet(temp_parquet)
            roundtrip = _physical_to_frame(read_back, normalized)
            if len(roundtrip) != len(adjusted):
                raise MarketDataError("Parquet read-back 행 수가 입력과 다릅니다.")
            digest = _sha256(temp_parquet)
            metadata["content_sha256"] = digest
            _validate_metadata(metadata, normalized, roundtrip, digest)
            temp_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _validate_metadata(json.loads(temp_metadata.read_text(encoding="utf-8")), normalized, roundtrip, digest)

            if final_parquet.exists():
                shutil.copy2(final_parquet, old_parquet_backup)
            if final_metadata.exists():
                shutil.copy2(final_metadata, old_metadata_backup)
            os.replace(temp_parquet, final_parquet)
            parquet_replaced = True
            os.replace(temp_metadata, final_metadata)
            metadata_replaced = True
        except Exception:
            if parquet_replaced:
                if final_parquet.exists():
                    final_parquet.unlink()
                if old_parquet_backup.exists():
                    os.replace(old_parquet_backup, final_parquet)
            if metadata_replaced:
                if final_metadata.exists():
                    final_metadata.unlink()
                if old_metadata_backup.exists():
                    os.replace(old_metadata_backup, final_metadata)
            raise
        finally:
            for path in (temp_parquet, temp_metadata, old_parquet_backup, old_metadata_backup):
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def latest_date(self, ticker: str) -> pd.Timestamp | None:
        try:
            frame = self.load_daily(ticker)
        except FileNotFoundError:
            return None
        return None if frame.empty else frame.index.max()

    def list_cached_tickers(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(
            path.stem
            for path in self.base_dir.glob("*.parquet")
            if path.is_file() and not path.name.startswith(".") and self._metadata_path(path.stem).exists()
        )


__all__ = [
    "AUTHORITY_TYPE",
    "DEFAULT_ADJUSTED_PRICE_STORE_DIR",
    "PHYSICAL_COLUMNS",
    "SCHEMA_VERSION",
    "SOURCE_ENDPOINT",
    "SOURCE_NAME",
    "SOURCE_SEMANTICS",
    "STORE_VERSION",
    "AdjustedPriceStore",
]
