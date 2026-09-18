"""Minimal orchestration for the one-target Daily Update foundation.

The module deliberately owns only sequencing, staging, and final validation.  Raw, adjusted,
PIT, index, and Repository V2 semantics remain in their existing authoritative components.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_historical_instrument_acquisition import HistoricalInstrumentAcquisitionRunner
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_MERGED_CALENDAR_PATH,
    DEFAULT_MERGED_PIT_PATH,
    DEFAULT_ROLLING_AUTHORITY_DIR,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    PitExtensionResult,
    RollingAuthorityError,
    RollingAuthorityManifest,
    _normalise_session_dates,
    build_rolling_pit_extension,
    load_rolling_authority,
    validate_merged_authority_coherence,
    write_merged_pit_extension,
    write_rolling_authority,
)


class DailyUpdateFoundationError(RuntimeError):
    """Expected, reportable failure of the single-target daily foundation."""


def normalize_target_as_of(value: str | date | pd.Timestamp) -> str:
    """Validate the sole production date input without consulting system time."""

    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise DailyUpdateFoundationError("BLOCKED_INVALID_TARGET_AS_OF")
    try:
        parsed = pd.Timestamp(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DailyUpdateFoundationError("BLOCKED_INVALID_TARGET_AS_OF") from exc
    if parsed.strftime("%Y-%m-%d") != text:
        raise DailyUpdateFoundationError("BLOCKED_INVALID_TARGET_AS_OF")
    return parsed.date().isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DailyUpdateFoundationError(f"BLOCKED_AUTHORITY_PAYLOAD:{path}")
    return payload


def _paired_complete_dates(raw_store: KrxRawStockStore, target_as_of: str) -> list[str]:
    states: dict[str, dict[str, str]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for row in raw_store.list_manifest(market):
            day = str(row["date"])
            if day <= target_as_of:
                states.setdefault(day, {})[market] = str(row.get("status", "")).upper()
    return sorted(
        day for day, pair in states.items()
        if pair.get("KOSPI") == "COMPLETE" and pair.get("KOSDAQ") == "COMPLETE"
    )


def _calendar_dates(authority_dir: Path, target_as_of: str) -> list[str]:
    path = authority_dir / DEFAULT_MERGED_CALENDAR_PATH.name
    payload = _read_json(path)
    return sorted(day for day in _normalise_session_dates(payload.get("trading_dates", [])) if day <= target_as_of)


def _candidate_tail(calendar_dates: Sequence[str], target_as_of: str) -> list[str]:
    if not calendar_dates or target_as_of <= max(calendar_dates):
        return []
    start = (pd.Timestamp(max(calendar_dates)) + pd.Timedelta(1, unit="D")).date().isoformat()
    return [day.date().isoformat() for day in pd.bdate_range(start, target_as_of)]


def _leg_summary(
    status: str,
    *,
    missing: Sequence[str] = (),
    updated: int = 0,
    requests: int = 0,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "missing_date_count": len(tuple(missing)),
        "missing_dates": list(missing),
        "updated_date_count": int(updated),
        "request_count": int(requests),
    }
    if reason:
        result["reason"] = reason
    result.update(extra)
    return result


class DailyUpdateFoundation:
    """Sequence the existing legs and promote authority only after all validations pass."""

    def __init__(
        self,
        *,
        authority_dir: Path = DEFAULT_ROLLING_AUTHORITY_DIR,
        raw_store: KrxRawStockStore,
        adjusted_store: AdjustedPriceStore,
        common_adjusted_tickers: Sequence[str] = (),
        common_raw_updater: Any,
        etf_raw_updater: Any,
        common_adjusted_updater: Any,
        etf_adjusted_updater: Any,
        market_index_refresh: Callable[[str], Mapping[str, Any]] | None = None,
        market_index_plan: Callable[[str], Mapping[str, Any]] | None = None,
        repository_validator: Callable[[str, Path, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        basic_info_runner: HistoricalInstrumentAcquisitionRunner | None = None,
        pit_extension_builder: Callable[..., PitExtensionResult] = build_rolling_pit_extension,
        pit_extension_writer: Callable[..., Any] = write_merged_pit_extension,
    ) -> None:
        self.authority_dir = Path(authority_dir)
        self.raw_store = raw_store
        self.adjusted_store = adjusted_store
        self.common_adjusted_tickers = tuple(str(t).zfill(6) for t in common_adjusted_tickers)
        self.common_raw_updater = common_raw_updater
        self.etf_raw_updater = etf_raw_updater
        self.common_adjusted_updater = common_adjusted_updater
        self.etf_adjusted_updater = etf_adjusted_updater
        self.market_index_refresh = market_index_refresh
        self.market_index_plan = market_index_plan
        self.repository_validator = repository_validator or self._default_repository_validator
        self.basic_info_runner = basic_info_runner
        self.pit_extension_builder = pit_extension_builder
        self.pit_extension_writer = pit_extension_writer

    def _load_state(self, target_as_of: str) -> tuple[RollingAuthorityManifest, dict[str, Any]]:
        manifest = load_rolling_authority(self.authority_dir)
        pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, self.authority_dir)
        calendar_dates = sorted(
            day for day in _normalise_session_dates(calendar_payload.get("trading_dates", [])) if day <= target_as_of
        )
        return manifest, {
            "pit": pit_payload,
            "calendar": calendar_payload,
            "calendar_dates": calendar_dates,
            "calendar_frontier": calendar_payload.get("calendar_frontier", ""),
            "operating_frontier": max(calendar_dates, default=""),
        }

    def plan(self, target_as_of: str | date | pd.Timestamp) -> dict[str, Any]:
        target = normalize_target_as_of(target_as_of)
        manifest, authority = self._load_state(target)
        known_dates = authority["calendar_dates"]
        tail_candidates = _candidate_tail(known_dates, target)
        required_candidates = sorted(set(known_dates) | set(tail_candidates))
        complete_raw = _paired_complete_dates(self.raw_store, target)
        common_missing = sorted(set(required_candidates) - set(complete_raw))
        etf_missing = [
            day for day in required_candidates
            if self.raw_store.get_manifest("KOSPI", day) is not None
            and self.raw_store.get_manifest("KOSPI", day).get("status") == "COMPLETE"
            and not (
                self.raw_store.get_manifest("ETF", day) is not None
                and self.raw_store.get_manifest("ETF", day).get("status") in {"COMPLETE", "NO_DATA"}
            )
        ]
        if hasattr(self.common_adjusted_updater, "plan"):
            common_adjusted_plan = dict(
                self.common_adjusted_updater.plan(
                    self.common_adjusted_tickers,
                    manifest.leg_boundaries["common_adjusted"],
                    target,
                )
            )
        else:
            common_adjusted_plan = _leg_summary("PLAN", reason="PIT_AND_STORE_CHECK_DEFERRED_TO_LIVE_LEG")
        if hasattr(self.etf_adjusted_updater, "plan"):
            etf_adjusted_plan = dict(
                self.etf_adjusted_updater.plan(manifest.leg_boundaries["etf_adjusted"], target)
            )
        else:
            etf_adjusted_plan = _leg_summary("PLAN", reason="RAW_AND_STORE_CHECK_DEFERRED_TO_LIVE_LEG")
        if self.market_index_plan is not None:
            market_index_plan = dict(self.market_index_plan(target))
        else:
            market_index_plan = _leg_summary("PLAN", reason="INDEX_STORE_CHECK_DEFERRED_TO_LIVE_LEG")
        extension_needed = bool(tail_candidates)
        return {
            "target_as_of": target,
            "current_certified_through": manifest.certified_through,
            "operating_calendar_frontier": authority["operating_frontier"],
            "required_candidate_dates": required_candidates,
            "common_raw": _leg_summary("PLAN", missing=common_missing, reason="REQUIRED_MINUS_COMPLETE"),
            "etf_raw": _leg_summary("PLAN", missing=etf_missing, reason="REQUIRED_MINUS_COMPLETE"),
            "common_adjusted": common_adjusted_plan,
            "etf_adjusted": etf_adjusted_plan,
            "market_index": market_index_plan,
            "authority_extension_needed": extension_needed,
            "authority_extension_candidates": tail_candidates,
            "network_request_count": 0,
            "production_write_count": 0,
            "authority_promotion": 0,
            "manifest": manifest,
        }

    @staticmethod
    def _call_refresh(updater: Any, boundary: str, target: str, **kwargs: Any) -> Mapping[str, Any]:
        try:
            return updater.refresh(boundary, target, **kwargs)
        except TypeError as exc:
            if kwargs and "unexpected keyword argument" in str(exc):
                return updater.refresh(boundary, target)
            raise

    def _stage_authority(
        self,
        extension: PitExtensionResult | None,
        manifest: RollingAuthorityManifest,
        stage_dir: Path,
        target: str,
    ) -> tuple[Path, dict[str, Any]]:
        stage_dir.mkdir(parents=True, exist_ok=True)
        if extension is None:
            for name in ("merged_pit_intervals.json", "merged_trading_calendar.json"):
                shutil.copy2(self.authority_dir / name, stage_dir / name)
            refs = {
                "merged_pit_digest": manifest.merged_pit_digest,
                "merged_pit_frontier": manifest.merged_pit_frontier,
                "merged_pit_schema_version": manifest.merged_pit_schema_version,
                "merged_calendar_digest": manifest.merged_calendar_digest,
                "merged_calendar_frontier": manifest.merged_calendar_frontier,
                "merged_calendar_schema_version": manifest.merged_calendar_schema_version,
            }
        else:
            publish = self.pit_extension_writer(
                extension,
                stage_dir,
                built_against_certified_through=manifest.certified_through,
                target_as_of=target,
            )
            refs = {
                key: getattr(publish, key)
                for key in (
                    "merged_pit_digest", "merged_pit_frontier", "merged_pit_schema_version",
                    "merged_calendar_digest", "merged_calendar_frontier", "merged_calendar_schema_version",
                )
            }
        staged = replace(
            manifest,
            certified_through=manifest.certified_through,
            leg_boundaries=dict(manifest.leg_boundaries),
            generated_at=manifest.generated_at,
            **refs,
        ).with_digest()
        write_rolling_authority(staged, stage_dir)
        validate_merged_authority_coherence(staged, stage_dir)
        return stage_dir, refs

    def _default_repository_validator(self, target: str, authority_dir: Path, leg_results: Mapping[str, Any]) -> Mapping[str, Any]:
        repo = MarketDataRepositoryV2(
            AdjustedPriceStore(self.adjusted_store.base_dir),
            self.raw_store,
            rolling_authority_dir=authority_dir,
        )
        tickers: set[str] = set()
        for leg in ("common_adjusted", "etf_adjusted"):
            tickers.update(str(t).zfill(6) for t in leg_results.get(leg, {}).get("updated", []))
        checked = 0
        for ticker in sorted(tickers):
            repo.get_daily(ticker, "1900-01-01", target)
            checked += 1
        return {"status": "PASS", "checked_ticker_count": checked, "query_audit": repo.query_audit}

    def _build_extension(
        self,
        extension_dates: Sequence[str],
        *,
        execute_live: bool,
        target: str,
    ) -> tuple[PitExtensionResult | None, dict[str, Any]]:
        if not extension_dates:
            return None, _leg_summary("UNCHANGED", reason="NO_NEW_OPERATING_TRADING_DATES")
        if self.basic_info_runner is None:
            raise DailyUpdateFoundationError("BLOCKED_BASIC_INFO_ACQUISITION_REQUIRED")
        acquisition = self.basic_info_runner.run_bounded(extension_dates, resume=True, execute_live=execute_live)
        if execute_live and acquisition.get("status") != "COMPLETE":
            raise DailyUpdateFoundationError(f"BLOCKED_BASIC_INFO_ACQUISITION:{acquisition.get('status')}")
        extension = self.pit_extension_builder(extension_calendar_dates=extension_dates)
        return extension, _leg_summary(
            "STAGED",
            updated=len(extension_dates),
            requests=int(acquisition.get("network_attempts", 0)),
            extension_start=extension.extension_start,
            extension_end=extension.extension_end,
            acquisition=acquisition,
        )

    def execute(self, target_as_of: str | date | pd.Timestamp, *, dry_run: bool = True) -> dict[str, Any]:
        target = normalize_target_as_of(target_as_of)
        try:
            plan = self.plan(target)
        except (DailyUpdateFoundationError, RollingAuthorityError) as exc:
            return {
                "target_as_of": target,
                "final_status": "BLOCKED",
                "status": "BLOCKED",
                "boundary_unchanged": True,
                "reason": str(exc),
                "network_request_count": 0,
                "production_write_count": 0,
                "authority_promotion": 0,
            }
        manifest: RollingAuthorityManifest = plan.pop("manifest")
        if dry_run:
            complete_plan = not any(
                plan.get(leg, {}).get("missing_dates")
                for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted", "market_index")
            ) and not plan["authority_extension_needed"]
            return {
                **plan,
                "final_status": "NOOP" if complete_plan else "BLOCKED",
                "status": "DRY_RUN",
                "reason": None if complete_plan else "DRY_RUN_NO_NETWORK_OR_PRODUCTION_WRITE",
                "network_request_count": 0,
                "production_write_count": 0,
                "authority_promotion": 0,
            }
        if (
            not plan["common_raw"]["missing_dates"]
            and not plan["etf_raw"]["missing_dates"]
            and not plan["common_adjusted"].get("missing_dates")
            and not plan["etf_adjusted"].get("missing_dates")
            and not plan["market_index"].get("missing_dates")
            and not plan["authority_extension_needed"]
            and (target <= manifest.certified_through or target not in plan["required_candidate_dates"])
        ):
            return {
                **plan,
                "final_status": "NOOP",
                "status": "NOOP_ALREADY_COMPLETE",
                "network_request_count": 0,
                "production_write_count": 0,
                "authority_promotion": 0,
            }

        leg_results: dict[str, Any] = {}
        old_boundary = manifest.certified_through
        try:
            required_dates = plan["required_candidate_dates"]
            leg_results["common_raw"] = self._call_refresh(
                self.common_raw_updater,
                manifest.leg_boundaries["common_raw"],
                target,
                required_dates=required_dates,
            )
            operating_dates = sorted(
                set(_calendar_dates(self.authority_dir, target))
                | set(day for day in _paired_complete_dates(self.raw_store, target) if day > plan["operating_calendar_frontier"])
            )
            extension_dates = [day for day in operating_dates if day > plan["operating_calendar_frontier"]]
            with tempfile.TemporaryDirectory(prefix="daily_update_authority_") as temporary:
                stage_dir = Path(temporary)
                extension, authority_result = self._build_extension(extension_dates, execute_live=True, target=target)
                leg_results["pit_authority"] = authority_result
                _stage_dir, authority_refs = self._stage_authority(extension, manifest, stage_dir, target)

                leg_results["etf_raw"] = self._call_refresh(
                    self.etf_raw_updater,
                    manifest.leg_boundaries["etf_raw"],
                    target,
                    required_dates=operating_dates,
                )
                if extension is not None and hasattr(self.common_adjusted_updater, "refresh_with_extension"):
                    leg_results["common_adjusted"] = self.common_adjusted_updater.refresh_with_extension(
                        self.common_adjusted_tickers,
                        manifest.leg_boundaries["common_adjusted"],
                        target,
                        extension,
                        workdir=stage_dir,
                    )
                else:
                    leg_results["common_adjusted"] = self.common_adjusted_updater.refresh(
                        self.common_adjusted_tickers,
                        manifest.leg_boundaries["common_adjusted"],
                        target,
                    )
                leg_results["etf_adjusted"] = self.etf_adjusted_updater.refresh(
                    manifest.leg_boundaries["etf_adjusted"], target
                )
                if self.market_index_refresh is not None:
                    leg_results["market_index"] = dict(self.market_index_refresh(target))
                else:
                    leg_results["market_index"] = _leg_summary("SKIPPED", reason="INDEX_REFRESH_NOT_BOUND")

                new_boundaries = {
                    leg: str(leg_results[leg].get("new_boundary", manifest.leg_boundaries[leg]))
                    for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")
                }
                new_certified = min(new_boundaries.values())
                staged_manifest = replace(
                    manifest,
                    certified_through=new_certified,
                    leg_boundaries=new_boundaries,
                    previous_boundary=old_boundary,
                    **authority_refs,
                ).with_digest()
                # Copy the staged authority files already validated above and bind the candidate
                # manifest to them before Repository V2 reads the changed range.
                write_rolling_authority(staged_manifest, stage_dir)
                validate_merged_authority_coherence(staged_manifest, stage_dir)
                leg_results["repository_v2"] = dict(self.repository_validator(target, stage_dir, leg_results))
                if leg_results["repository_v2"].get("status") != "PASS":
                    raise DailyUpdateFoundationError("BLOCKED_REPOSITORY_V2_VALIDATION")
                if new_certified <= old_boundary:
                    update_observed = bool(
                        plan["common_raw"]["missing_dates"]
                        or plan["etf_raw"]["missing_dates"]
                        or any(
                            int(result.get("updated_date_count", 0)) > 0
                            or bool(result.get("updated"))
                            for result in leg_results.values()
                            if isinstance(result, Mapping)
                        )
                    )
                    return {
                        "target_as_of": target,
                        "final_status": "PASS" if update_observed else "NOOP",
                        "status": "VALIDATED_NO_PROMOTION" if update_observed else "NO_ADVANCE",
                        "certified_through": old_boundary,
                        "boundary_unchanged": True,
                        "leg_results": leg_results,
                        "network_request_count": sum(int(v.get("request_count", 0)) for v in leg_results.values() if isinstance(v, Mapping)),
                        "production_write_count": 0,
                        "authority_promotion": 0,
                    }
                # Final authority promotion is deliberately last.  The canonical merged files are
                # written only after every data leg and Repository V2 candidate read has passed.
                if extension is not None:
                    publish = self.pit_extension_writer(
                        extension,
                        self.authority_dir,
                        built_against_certified_through=old_boundary,
                        target_as_of=target,
                    )
                    staged_manifest = replace(
                        staged_manifest,
                        merged_pit_digest=publish.merged_pit_digest,
                        merged_pit_frontier=publish.merged_pit_frontier,
                        merged_pit_schema_version=publish.merged_pit_schema_version,
                        merged_calendar_digest=publish.merged_calendar_digest,
                        merged_calendar_frontier=publish.merged_calendar_frontier,
                        merged_calendar_schema_version=publish.merged_calendar_schema_version,
                    ).with_digest()
                write_rolling_authority(staged_manifest, self.authority_dir)
                validate_merged_authority_coherence(staged_manifest, self.authority_dir)
                return {
                    "target_as_of": target,
                    "final_status": "PASS",
                    "status": "PROMOTED",
                    "certified_through": new_certified,
                    "previous_boundary": old_boundary,
                    "leg_results": leg_results,
                    "network_request_count": sum(int(v.get("request_count", v.get("runner_result", {}).get("krx_open_api_attempt_count", 0))) for v in leg_results.values() if isinstance(v, Mapping)),
                    "production_write_count": 1,
                    "authority_promotion": 1,
                }
        except Exception as exc:  # noqa: BLE001 - normalize expected and unexpected failures alike
            return {
                "target_as_of": target,
                "final_status": "BLOCKED" if isinstance(exc, (DailyUpdateFoundationError, RollingAuthorityError)) else "FAILED",
                "status": "BLOCKED" if isinstance(exc, (DailyUpdateFoundationError, RollingAuthorityError)) else "FAILED",
                "certified_through": old_boundary,
                "boundary_unchanged": True,
                "leg_results": leg_results,
                "reason": str(exc),
                "network_request_count": sum(int(v.get("request_count", v.get("runner_result", {}).get("krx_open_api_attempt_count", 0))) for v in leg_results.values() if isinstance(v, Mapping)),
                "production_write_count": 0,
                "authority_promotion": 0,
            }


__all__ = ["DailyUpdateFoundation", "DailyUpdateFoundationError", "normalize_target_as_of"]
