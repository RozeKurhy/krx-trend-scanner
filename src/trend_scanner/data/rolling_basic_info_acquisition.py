"""Rolling (incremental) Basic Info acquisition -- the production counterpart to
:class:`~trend_scanner.data.krx_historical_instrument_acquisition.HistoricalInstrumentAcquisitionRunner`'s
frozen closure authority.

Directive ``ROLLING_BASIC_INFO_ACQUISITION_V01`` section 5/11: the historical runner's frozen
contract (``2010-01-04..2026-08-21``, exact date list, exact SHA-256, one raw_root, one
checkpoint.json) must never be touched or reused as a mutable target. This module is a SEPARATE
runner, with its own raw_root/checkpoint/final_summary, so it can physically never violate that
exact-match contract (adding files under the historical ``raw_root`` would make
``load_basic_info_snapshots()`` see them as unexpected "extra" files on any historical-scope call).

Shared fetch/validation/persistence primitives (``build_target_pairs``,
``validate_basic_info_response``, ``_atomic_write``, ``_sha256_bytes``) are imported and reused
unchanged from ``krx_historical_instrument_acquisition`` -- this module does not reimplement or copy
them (directive section 10).

Authorized request dates are always *derived*, never caller-injected (directive section 7):
``derive_authorized_dates()`` reads the already-approved rolling raw market manifest
(``KrxRawStockStore``) for dates both KOSPI and KOSDAQ already observed as ``COMPLETE`` trading
sessions, strictly after the current Basic Info frontier and at or before ``target_as_of``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from trend_scanner.data.krx_historical_instrument_acquisition import (
    HISTORICAL_CALENDAR_PATH,
    InstrumentAcquisitionContractError,
    _atomic_write,
    _sha256_bytes,
    build_target_pairs,
    load_historical_trading_calendar,
    validate_basic_info_response,
)
from trend_scanner.universe.historical_authority_reconciliation import (
    ACQUISITION_COMPLETE_STATUS,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
)
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


ROLLING_SCHEMA_VERSION = "KRX_ROLLING_BASIC_INFO_ACQUISITION_V01"
DEFAULT_ROLLING_RAW_ROOT = Path("data/reference/source/history/krx_instrument_master/v01/rolling/basic_info")
DEFAULT_ROLLING_CHECKPOINT_PATH = Path("data/reference/source/history/krx_instrument_master/v01/rolling/checkpoint.json")
DEFAULT_ROLLING_FINAL_SUMMARY_PATH = Path("data/reference/source/history/krx_instrument_master/v01/rolling/acquisition_final_summary.json")


def derive_authorized_dates(
    raw_store: KrxRawStockStore,
    *,
    current_frontier: str,
    target_as_of: str,
) -> list[str]:
    """``AUTHORIZED_REQUEST_DATES = RAW_MANIFEST_COMPLETE_DATES where date > current_frontier and
    date <= target_as_of`` (directive section 7) -- a date only counts when BOTH KOSPI and KOSDAQ
    are observed COMPLETE, since a Basic Info pair always needs both markets."""
    kospi_complete = {str(r["date"]) for r in raw_store.list_manifest("KOSPI") if r.get("status") == "COMPLETE"}
    kosdaq_complete = {str(r["date"]) for r in raw_store.list_manifest("KOSDAQ") if r.get("status") == "COMPLETE"}
    both_complete = kospi_complete & kosdaq_complete
    return sorted(d for d in both_complete if current_frontier < d <= target_as_of)


def current_basic_info_frontier(
    *,
    historical_calendar_path: Path = HISTORICAL_CALENDAR_PATH,
    rolling_checkpoint_path: Path = DEFAULT_ROLLING_CHECKPOINT_PATH,
) -> str:
    """The frozen historical archive's own last date, advanced by whatever the rolling checkpoint
    has already certified COMPLETE for both markets -- never a hardcoded literal."""
    frontier = load_historical_trading_calendar(historical_calendar_path)["last_trading_date"]
    checkpoint_path = Path(rolling_checkpoint_path)
    if not checkpoint_path.exists():
        return frontier
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    by_date_market: dict[str, set[str]] = {}
    for entry in entries.values():
        if entry.get("status") == "COMPLETE":
            bas_dd = str(entry.get("basDd", ""))
            date = f"{bas_dd[:4]}-{bas_dd[4:6]}-{bas_dd[6:8]}" if len(bas_dd) == 8 else ""
            if date:
                by_date_market.setdefault(date, set()).add(str(entry.get("market")))
    both_complete_dates = [d for d, markets in by_date_market.items() if {"KOSPI", "KOSDAQ"}.issubset(markets)]
    return max([frontier, *both_complete_dates])


class RollingBasicInfoAcquisitionRunner:
    """Incremental production Basic Info acquisition against
    ``TIER_A_KRX_OPEN_API_BASIC_INFO`` -- an explicitly-authorized-dates-only counterpart to
    :class:`HistoricalInstrumentAcquisitionRunner`, sharing its fetch/validate/persist primitives
    but never its raw_root, checkpoint, or frozen-calendar validation gate."""

    def __init__(
        self,
        client: KrxOpenApiClient | None,
        quota: LocalKrxOpenApiQuota,
        *,
        raw_root: str | Path = DEFAULT_ROLLING_RAW_ROOT,
        checkpoint_path: str | Path = DEFAULT_ROLLING_CHECKPOINT_PATH,
    ) -> None:
        if quota is None:
            raise ValueError("quota is required")
        self.client = client
        self.quota = quota
        self.raw_root = Path(raw_root)
        self.checkpoint_path = Path(checkpoint_path)

    def _load_manifest(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {"schema_version": ROLLING_SCHEMA_VERSION, "entries": {}}
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "rolling checkpoint is unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("entries", {}), dict):
            raise InstrumentAcquisitionContractError("INTEGRITY_INVALID", "rolling checkpoint shape is invalid")
        return value

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        _atomic_write(self.checkpoint_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))

    def _raw_path(self, pair: dict[str, str]) -> Path:
        return self.raw_root / pair["basDd"][:4] / pair["basDd"] / f"{pair['market']}.json"

    def _verify_complete(self, pair: dict[str, str], entry: dict[str, Any]) -> bool:
        raw_path = Path(str(entry.get("raw_path", "")))
        if not raw_path.is_file() or not entry.get("raw_content_sha256"):
            return False
        content = raw_path.read_bytes()
        if _sha256_bytes(content) != entry.get("raw_content_sha256"):
            return False
        try:
            payload = json.loads(content.decode("utf-8"))
            checked = validate_basic_info_response(payload, bas_dd=pair["basDd"], market=pair["market"], endpoint=pair["endpoint"])
        except (json.JSONDecodeError, InstrumentAcquisitionContractError, UnicodeDecodeError):
            return False
        return checked["row_count"] == int(entry.get("row_count", -1))

    def plan(self, trading_dates: Sequence[str]) -> dict[str, Any]:
        """Network-free dry run (directive section 35/36)."""
        dates = sorted(trading_dates)
        pairs = build_target_pairs(dates, expected_count=None)
        return {
            "status": "DRY_RUN",
            "authorized_date_count": len(dates),
            "authorized_dates": dates,
            "target_pair_count": len(pairs),
        }

    def run(self, trading_dates: Sequence[str], *, resume: bool = True, execute_live: bool = False) -> dict[str, Any]:
        dates = sorted(trading_dates)
        pairs = build_target_pairs(dates, expected_count=None)
        if not execute_live:
            return {"status": "DRY_RUN", "target_count": len(pairs), "completed_count": 0, "pending_count": len(pairs), "new_snapshot_count": 0}
        if self.client is None:
            raise ValueError("rolling live acquisition requires a client")

        manifest = self._load_manifest()
        entries = manifest.setdefault("entries", {})
        completed = failures = 0
        new_snapshot_count = 0
        network_attempts_before = int(getattr(self.client, "request_count", 0))
        retry_before = int(getattr(self.client, "retry_count", 0))
        started = datetime.now(timezone.utc).isoformat()
        paused = False

        for pair in pairs:
            key = f"{pair['basDd']}|{pair['market']}|{pair['endpoint']}"
            existing = entries.get(key)
            if resume and existing and existing.get("status") == "COMPLETE" and self._verify_complete(pair, existing):
                completed += 1
                continue
            entry = {
                "basDd": pair["basDd"], "market": pair["market"], "endpoint": pair["endpoint"], "status": "PENDING",
                "http_status": None, "row_count": None, "raw_content_sha256": None, "raw_path": str(self._raw_path(pair)),
                "schema_validation": "PENDING", "identity_validation": "PENDING", "classification_completeness": "PENDING",
                "started_at_utc": datetime.now(timezone.utc).isoformat(), "completed_at_utc": None, "last_error": None,
            }
            entries[key] = entry
            try:
                response = self.client.fetch(f"/sto/{pair['endpoint']}", pair["basDd"], quota_endpoint_key=pair["endpoint"])
                entry["http_status"] = response.http_status
                if response.http_status != 200:
                    entry["status"] = "FAILED_RETRYABLE" if response.http_status is None or response.http_status >= 500 else "FAILED_PERMANENT"
                    entry["last_error"] = f"HTTP_{response.http_status or 'TRANSPORT'}"
                    failures += 1
                    self._save_manifest(manifest)
                    continue
                checked = validate_basic_info_response(response.payload, bas_dd=pair["basDd"], market=pair["market"], endpoint=pair["endpoint"])
                raw_bytes = json.dumps(response.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                raw_path = self._raw_path(pair)
                _atomic_write(raw_path, raw_bytes)
                entry.update({
                    "status": "COMPLETE", "row_count": checked["row_count"], "raw_content_sha256": _sha256_bytes(raw_bytes),
                    "schema_validation": "PASS", "identity_validation": "PASS",
                    "classification_completeness": checked["classification_completeness"],
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                })
                completed += 1
                new_snapshot_count += 1
            except (KrxOpenApiQuotaExceeded, KrxOpenApiRateLimitError) as exc:
                entry.update({"status": "PAUSED_QUOTA", "last_error": str(exc)})
                failures += 1
                paused = True
                self._save_manifest(manifest)
                break
            except (KrxOpenApiAuthorizationError, KrxOpenApiBudgetError) as exc:
                entry.update({"status": "FAILED_PERMANENT", "last_error": str(exc)})
                failures += 1
                self._save_manifest(manifest)
                break
            except InstrumentAcquisitionContractError as exc:
                entry.update({
                    "status": exc.status, "last_error": str(exc),
                    "schema_validation": "FAIL" if exc.status == "SCHEMA_INVALID" else "PASS",
                    "identity_validation": "FAIL" if exc.status == "IDENTITY_INVALID" else "NOT_EVALUATED",
                })
                failures += 1
            self._save_manifest(manifest)

        return {
            "status": "PAUSED_QUOTA" if paused else ("COMPLETE" if completed == len(pairs) else "PARTIAL"),
            "target_count": len(pairs),
            "completed_count": completed,
            "pending_count": max(0, len(pairs) - completed),
            "failures": failures,
            "new_snapshot_count": new_snapshot_count,
            "network_attempts": int(getattr(self.client, "request_count", 0)) - network_attempts_before,
            "retry_attempts": int(getattr(self.client, "retry_count", 0)) - retry_before,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def write_final_summary(self, trading_dates: Sequence[str], *, final_summary_path: Path = DEFAULT_ROLLING_FINAL_SUMMARY_PATH) -> dict[str, Any]:
        """Write a rolling final_summary.json in the exact shape
        ``load_basic_info_snapshots()``/``_load_acquisition_authority()`` expects (same required
        fields as the historical closure summary) -- so a future ``build_rolling_pit_extension()``
        call against this rolling raw_root/checkpoint/final_summary can validate it unchanged."""
        dates = sorted(trading_dates)
        pairs = build_target_pairs(dates, expected_count=None)
        manifest = self._load_manifest()
        entries = manifest.get("entries", {})
        complete_count = sum(
            1 for pair in pairs
            if entries.get(f"{pair['basDd']}|{pair['market']}|{pair['endpoint']}", {}).get("status") == "COMPLETE"
        )
        checkpoint_bytes = self.checkpoint_path.read_bytes() if self.checkpoint_path.exists() else b""
        all_complete = complete_count == len(pairs)
        payload = {
            "schema_version": ROLLING_SCHEMA_VERSION,
            "status": READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION if all_complete else "INCOMPLETE",
            "runner_status": ACQUISITION_COMPLETE_STATUS if all_complete else "PARTIAL",
            "target_count": len(pairs),
            "completed_count": complete_count,
            "pending_count": len(pairs) - complete_count,
            "checkpoint_manifest_sha256": _sha256_bytes(checkpoint_bytes) if checkpoint_bytes else None,
            "checkpoint_path": str(self.checkpoint_path),
            "raw_root": str(self.raw_root),
            "authorized_dates": dates,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write(final_summary_path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
        return payload


__all__ = [
    "ROLLING_SCHEMA_VERSION",
    "DEFAULT_ROLLING_RAW_ROOT",
    "DEFAULT_ROLLING_CHECKPOINT_PATH",
    "DEFAULT_ROLLING_FINAL_SUMMARY_PATH",
    "derive_authorized_dates",
    "current_basic_info_frontier",
    "RollingBasicInfoAcquisitionRunner",
]
