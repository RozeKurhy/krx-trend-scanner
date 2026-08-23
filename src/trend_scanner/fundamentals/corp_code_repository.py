"""Persistent corpCode.xml mapping with duplicate-safe ticker lookup."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from .models import CorpCodeRecord
from .opendart_client import OpenDartClient


DEFAULT_CACHE_PATH = Path("data/cache/opendart/corp_code_cache.json")


class CorpCodeError(RuntimeError):
    pass


class UnknownTickerError(CorpCodeError):
    pass


class UnknownCorpCodeError(CorpCodeError):
    pass


class AmbiguousCorpCodeError(CorpCodeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CorpCodeRepository:
    def __init__(self, client: OpenDartClient | None = None, *, cache_path: Path | str = DEFAULT_CACHE_PATH,
                 records: Iterable[CorpCodeRecord] | None = None):
        self.client = client
        self.cache_path = Path(cache_path)
        self.records: tuple[CorpCodeRecord, ...] = tuple(records or ())
        self.source_sha256: str | None = None
        self.retrieved_at: str | None = None
        self.cache_hit = False
        self.duplicate_conflicts: dict[str, tuple[str, ...]] = {}
        if records is not None:
            self._index()

    def _index(self) -> None:
        by_ticker: dict[str, set[str]] = {}
        for row in self.records:
            if row.stock_code:
                by_ticker.setdefault(row.stock_code, set()).add(row.corp_code)
        self.duplicate_conflicts = {ticker: tuple(sorted(values)) for ticker, values in by_ticker.items() if len(values) > 1}

    @classmethod
    def from_cache(cls, path: Path | str) -> "CorpCodeRepository":
        repo = cls(cache_path=path)
        repo._load_cache()
        return repo

    def _load_cache(self) -> bool:
        if not self.cache_path.exists():
            return False
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.records = tuple(CorpCodeRecord(**row) for row in payload.get("records", []))
        self.source_sha256 = payload.get("source_sha256")
        self.retrieved_at = payload.get("retrieved_at")
        self.cache_hit = True
        self._index()
        return True

    def _parse_zip(self, raw: bytes) -> tuple[CorpCodeRecord, ...]:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            names = [name for name in archive.namelist() if name.upper().endswith("CORPCODE.XML")]
            if not names:
                raise CorpCodeError("corpCode ZIP does not contain CORPCODE.xml")
            root = ET.fromstring(archive.read(names[0]))
        rows: list[CorpCodeRecord] = []
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1] != "list":
                continue
            values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
            if values.get("corp_code"):
                rows.append(CorpCodeRecord(
                    corp_code=values.get("corp_code", ""),
                    corp_name=values.get("corp_name", ""),
                    stock_code=values.get("stock_code", ""),
                    modify_date=values.get("modify_date", ""),
                ))
        if not rows:
            raise CorpCodeError("corpCode XML has no records")
        return tuple(rows)

    def refresh(self, *, force_refresh: bool = False) -> dict[str, object]:
        if not force_refresh and self._load_cache():
            return self.metadata()
        if self.client is None:
            raise CorpCodeError("OpenDART client is required for refresh")
        response = self.client.corp_code()
        self.records = self._parse_zip(response.raw)
        self.source_sha256 = hashlib.sha256(response.raw).hexdigest()
        self.retrieved_at = _now()
        self.cache_hit = False
        self._index()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "source_provider": "OPENDART",
            "retrieved_at": self.retrieved_at,
            "source_sha256": self.source_sha256,
            "record_count": len(self.records),
            "records": [item.to_dict() for item in self.records],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.metadata()

    def ensure_loaded(self) -> None:
        if not self.records and not self._load_cache():
            self.refresh()

    def get_corp_code(self, ticker: str) -> str:
        self.ensure_loaded()
        ticker = str(ticker).strip()
        if not (len(ticker) == 6 and ticker.isdigit()):
            raise UnknownTickerError(f"Ticker must be a valid six-digit code: {ticker!r}")
        if ticker in self.duplicate_conflicts:
            raise AmbiguousCorpCodeError(f"Ticker maps to multiple corp_codes: {ticker}")
        matches = [row.corp_code for row in self.records if row.stock_code == ticker]
        if len(matches) != 1:
            raise UnknownTickerError(f"Unknown or invalid ticker: {ticker}")
        return matches[0]

    def get_ticker(self, corp_code: str) -> str:
        self.ensure_loaded()
        matches = [row.stock_code for row in self.records if row.corp_code == str(corp_code).strip() and row.stock_code]
        if not matches:
            raise UnknownCorpCodeError(f"Unknown corp_code: {corp_code}")
        if len(set(matches)) != 1:
            raise AmbiguousCorpCodeError(f"corp_code maps to multiple tickers: {corp_code}")
        return matches[0]

    def get_record(self, ticker: str) -> CorpCodeRecord:
        corp_code = self.get_corp_code(ticker)
        return next(item for item in self.records if item.corp_code == corp_code and item.stock_code == ticker)

    def metadata(self) -> dict[str, object]:
        return {
            "source_provider": "OPENDART",
            "retrieved_at": self.retrieved_at,
            "source_sha256": self.source_sha256,
            "record_count": len(self.records),
            "cache_hit": self.cache_hit,
            "duplicate_conflict_count": len(self.duplicate_conflicts),
        }
