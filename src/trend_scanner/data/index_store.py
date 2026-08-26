"""Network-free persistent storage for INDEX_STORE_V01 families.

The store is deliberately independent from KRX clients, PyKRX and validation
artifacts.  A complete family is validated in memory and written to temporary
files before the two production files are replaced.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import pandas as pd

from trend_scanner.data.errors import MarketDataError


INDEX_STORE_SCHEMA_VERSION = "INDEX_STORE_V01"
MARKET_INDEX_FAMILY = "MARKET_INDEX"
DEFAULT_INDEX_STORE_ROOT = Path("data/market/index/v01")
MARKET_INDEX_FILENAME = "market_index.parquet"
MARKET_INDEX_META_FILENAME = "market_index.meta.json"
INDEX_STORE_COLUMNS = (
    "date",
    "family",
    "source_index_class",
    "index_code",
    "index_name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
)
_OHLC_FIELDS = ("open", "high", "low", "close")
_NUMERIC_FIELDS = _OHLC_FIELDS + ("volume", "trading_value")
_MARKET_INDEX_CODES = frozenset({"1001", "2001"})


def _typed_empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="string"),
            "family": pd.Series([], dtype="string"),
            "source_index_class": pd.Series([], dtype="string"),
            "index_code": pd.Series([], dtype="string"),
            "index_name": pd.Series([], dtype="string"),
            **{field: pd.Series([], dtype="float64") for field in _OHLC_FIELDS},
            "volume": pd.Series([], dtype="int64"),
            "trading_value": pd.Series([], dtype="float64"),
        },
        columns=list(INDEX_STORE_COLUMNS),
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_strings(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        raise MarketDataError("INDEX_STORE_INVALID_DATE")
    return pd.Series(parsed.dt.strftime("%Y-%m-%d"), index=values.index, dtype="string")


def _finite(series: pd.Series) -> pd.Series:
    return series.map(lambda value: isinstance(value, (int, float)) and math.isfinite(float(value)))


def normalize_index_frame(frame: pd.DataFrame, family: str = MARKET_INDEX_FAMILY) -> pd.DataFrame:
    """Validate and normalize a family frame without touching the filesystem."""

    family = str(family).strip()
    if family == "":
        raise MarketDataError("INDEX_STORE_INVALID_FAMILY")
    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != INDEX_STORE_COLUMNS:
        raise MarketDataError("INDEX_STORE_SCHEMA_ERROR")
    result = frame.copy()
    result["date"] = _date_strings(result["date"])
    for field in ("family", "source_index_class", "index_code", "index_name"):
        result[field] = result[field].astype("string")
        if result[field].isna().any() or result[field].str.strip().eq("").any():
            raise MarketDataError(f"INDEX_STORE_INVALID_{field.upper()}")
    if not result["family"].eq(family).all():
        raise MarketDataError("INDEX_STORE_FAMILY_MISMATCH")
    result["index_code"] = result["index_code"].str.strip()
    if family == MARKET_INDEX_FAMILY and not result["index_code"].isin(_MARKET_INDEX_CODES).all():
        raise MarketDataError("INDEX_STORE_INVALID_MARKET_INDEX_CODE")
    for field in _NUMERIC_FIELDS:
        result[field] = pd.to_numeric(result[field], errors="coerce")
        if result[field].isna().any() or not _finite(result[field]).all():
            raise MarketDataError(f"INDEX_STORE_INVALID_NUMERIC_{field.upper()}")
    if (result[list(_OHLC_FIELDS)] <= 0).any().any():
        raise MarketDataError("INDEX_STORE_INVALID_OHLC")
    if (result["volume"] < 0).any() or (result["volume"] % 1 != 0).any():
        raise MarketDataError("INDEX_STORE_INVALID_VOLUME")
    if (result["trading_value"] < 0).any():
        raise MarketDataError("INDEX_STORE_INVALID_TRADING_VALUE")
    if not result.empty:
        relation = (
            (result["high"] >= result["open"])
            & (result["high"] >= result["low"])
            & (result["high"] >= result["close"])
            & (result["low"] <= result["open"])
            & (result["low"] <= result["close"])
        )
        if not relation.all():
            raise MarketDataError("INDEX_STORE_INVALID_OHLC_RELATION")
    if result.duplicated(subset=["date", "family", "index_code"]).any():
        raise MarketDataError("INDEX_STORE_DUPLICATE_KEY")
    result["volume"] = result["volume"].astype("int64")
    for field in _OHLC_FIELDS + ("trading_value",):
        result[field] = result[field].astype("float64")
    return result.sort_values(["date", "index_code"], kind="mergesort").reset_index(drop=True)


class IndexStore:
    """Atomic, deterministic local storage for INDEX_STORE_V01."""

    def __init__(self, root: Path | str = DEFAULT_INDEX_STORE_ROOT) -> None:
        self.root = Path(root)

    def _paths(self, family: str, output_parquet: Path | None = None, output_meta: Path | None = None) -> tuple[Path, Path]:
        family = str(family).strip()
        if output_parquet is not None or output_meta is not None:
            if output_parquet is None or output_meta is None:
                raise ValueError("output_parquet and output_meta must be provided together")
            return Path(output_parquet), Path(output_meta)
        if family == MARKET_INDEX_FAMILY:
            return self.root / MARKET_INDEX_FILENAME, self.root / MARKET_INDEX_META_FILENAME
        safe = family.lower()
        return self.root / f"{safe}.parquet", self.root / f"{safe}.meta.json"

    def _metadata(self, frame: pd.DataFrame, family: str, content_sha256: str, context: Mapping[str, Any] | None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        metadata: dict[str, Any] = {
            "schema_version": INDEX_STORE_SCHEMA_VERSION,
            "family": family,
            "source_name": "KRX_OPEN_API_MARKET_INDEX" if family == MARKET_INDEX_FAMILY else "INDEX_STORE",
            "source_endpoints": ["/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"] if family == MARKET_INDEX_FAMILY else [],
            "source_semantics": "KRX_REPRESENTATIVE_MARKET_INDEX" if family == MARKET_INDEX_FAMILY else "INDEX_STORE_FAMILY",
            "date_min": str(frame["date"].min()) if not frame.empty else "",
            "date_max": str(frame["date"].max()) if not frame.empty else "",
            "row_count": int(len(frame)),
            "index_count": int(frame["index_code"].nunique()),
            "index_codes": sorted(frame["index_code"].astype(str).unique().tolist()),
            "generation_timestamp": now,
            "last_success_at": now,
            "content_sha256": content_sha256,
            "parquet_sha256": content_sha256,
            "mapping_contract_version": "KRX_MARKET_INDEX_MAP_V01" if family == MARKET_INDEX_FAMILY else None,
            "mapping_contract_sha256": "",
        }
        if context:
            metadata.update(dict(context))
        metadata["schema_version"] = INDEX_STORE_SCHEMA_VERSION
        metadata["family"] = family
        metadata["content_sha256"] = content_sha256
        metadata["parquet_sha256"] = content_sha256
        return metadata

    def save_family_full(
        self,
        family: str,
        dataframe: pd.DataFrame,
        metadata_context: Mapping[str, Any] | None = None,
        *,
        output_parquet: Path | None = None,
        output_meta: Path | None = None,
    ) -> dict[str, Any]:
        family = str(family).strip()
        normalized = normalize_index_frame(dataframe, family)
        parquet_path, meta_path = self._paths(family, output_parquet, output_meta)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_fd, parquet_name = tempfile.mkstemp(prefix=f".{parquet_path.name}.", suffix=".tmp", dir=parquet_path.parent)
        meta_fd, meta_name = tempfile.mkstemp(prefix=f".{meta_path.name}.", suffix=".tmp", dir=meta_path.parent)
        os.close(parquet_fd)
        os.close(meta_fd)
        parquet_tmp = Path(parquet_name)
        meta_tmp = Path(meta_name)
        old_parquet = parquet_path.read_bytes() if parquet_path.exists() else None
        old_meta = meta_path.read_bytes() if meta_path.exists() else None
        try:
            normalized.to_parquet(parquet_tmp, index=False)
            digest = file_sha256(parquet_tmp)
            metadata = self._metadata(normalized, family, digest, metadata_context)
            meta_tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(parquet_tmp, parquet_path)
            try:
                os.replace(meta_tmp, meta_path)
            except Exception:
                if old_parquet is None:
                    parquet_path.unlink(missing_ok=True)
                else:
                    parquet_path.write_bytes(old_parquet)
                raise
        finally:
            parquet_tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)
        return metadata

    def _read_verified(self, family: str) -> tuple[pd.DataFrame, dict[str, Any], Path, Path]:
        parquet_path, meta_path = self._paths(family)
        if not parquet_path.exists() or not meta_path.exists():
            raise MarketDataError("INDEX_STORE_MISSING_FILES")
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MarketDataError("INDEX_STORE_METADATA_READ_ERROR") from exc
        digest = file_sha256(parquet_path)
        if metadata.get("content_sha256", metadata.get("parquet_sha256")) != digest:
            raise MarketDataError("INDEX_STORE_HASH_MISMATCH")
        try:
            frame = pd.read_parquet(parquet_path)
        except Exception as exc:
            raise MarketDataError("INDEX_STORE_READ_ERROR") from exc
        normalized = normalize_index_frame(frame, family)
        if metadata.get("schema_version") != INDEX_STORE_SCHEMA_VERSION or metadata.get("family") != family:
            raise MarketDataError("INDEX_STORE_METADATA_CONTRACT_ERROR")
        if int(metadata.get("row_count", -1)) != len(normalized):
            raise MarketDataError("INDEX_STORE_ROW_COUNT_MISMATCH")
        if str(metadata.get("date_min", "")) != (str(normalized["date"].min()) if not normalized.empty else ""):
            raise MarketDataError("INDEX_STORE_DATE_RANGE_MISMATCH")
        if str(metadata.get("date_max", "")) != (str(normalized["date"].max()) if not normalized.empty else ""):
            raise MarketDataError("INDEX_STORE_DATE_RANGE_MISMATCH")
        if sorted(map(str, metadata.get("index_codes", []))) != sorted(normalized["index_code"].astype(str).unique().tolist()):
            raise MarketDataError("INDEX_STORE_CODE_METADATA_MISMATCH")
        return normalized, metadata, parquet_path, meta_path

    def load_family(
        self,
        family: str,
        start: str | None = None,
        end: str | None = None,
        index_codes: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> pd.DataFrame:
        frame, _, _, _ = self._read_verified(str(family).strip())
        if start is not None:
            start_text = pd.Timestamp(start).strftime("%Y-%m-%d")
            frame = frame[frame["date"] >= start_text]
        if end is not None:
            end_text = pd.Timestamp(end).strftime("%Y-%m-%d")
            frame = frame[frame["date"] <= end_text]
        if index_codes is not None:
            allowed = {str(code) for code in index_codes}
            frame = frame[frame["index_code"].astype(str).isin(allowed)]
        if frame.empty:
            return _typed_empty()
        return frame.sort_values(["date", "index_code"], kind="mergesort").reset_index(drop=True)

    def verify_family(self, family: str) -> dict[str, Any]:
        frame, metadata, parquet_path, meta_path = self._read_verified(str(family).strip())
        return {
            "status": "PASS",
            "valid": True,
            "family": str(family).strip(),
            "path": str(parquet_path),
            "meta_path": str(meta_path),
            "schema_version": metadata["schema_version"],
            "row_count": int(len(frame)),
            "index_count": int(frame["index_code"].nunique()),
            "index_codes": sorted(frame["index_code"].astype(str).unique().tolist()),
            "date_min": str(frame["date"].min()) if not frame.empty else "",
            "date_max": str(frame["date"].max()) if not frame.empty else "",
            "content_sha256": metadata.get("content_sha256"),
        }


__all__ = [
    "DEFAULT_INDEX_STORE_ROOT",
    "INDEX_STORE_COLUMNS",
    "INDEX_STORE_SCHEMA_VERSION",
    "MARKET_INDEX_FAMILY",
    "MARKET_INDEX_FILENAME",
    "MARKET_INDEX_META_FILENAME",
    "IndexStore",
    "file_sha256",
    "normalize_index_frame",
]
