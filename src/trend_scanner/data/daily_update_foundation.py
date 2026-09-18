"""Minimal orchestration for the one-target Daily Update foundation.

The module deliberately owns only sequencing, staging, and final validation.  Raw, adjusted,
PIT, index, and Repository V2 semantics remain in their existing authoritative components.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_detector import CorporateActionSnapshot
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.krx_historical_instrument_acquisition import HistoricalInstrumentAcquisitionRunner
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_MERGED_CALENDAR_PATH,
    DEFAULT_MERGED_PIT_PATH,
    DEFAULT_ROLLING_AUTHORITY_DIR,
    _etf_raw_required_dates,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    PitExtensionResult,
    RollingAuthorityError,
    RollingAuthorityManifest,
    _normalise_session_dates,
    build_rolling_pit_extension,
    load_effective_common_adjusted_population,
    load_rolling_authority,
    resolve_current_identity,
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


def _paired_no_data_dates(raw_store: KrxRawStockStore, target_as_of: str) -> list[str]:
    states: dict[str, dict[str, str]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for row in raw_store.list_manifest(market):
            day = str(row["date"])
            if day <= target_as_of:
                states.setdefault(day, {})[market] = str(row.get("status", "")).upper()
    is_finalized = getattr(raw_store, "is_finalized_no_data", None)
    if not callable(is_finalized):
        # Older test doubles and integrations do not expose the raw-store
        # terminal-observation contract.  Their NO_DATA-shaped placeholders
        # must not suppress a required fetch.
        return []
    return sorted(
        day
        for day, pair in states.items()
        if pair.get("KOSPI") == "NO_DATA"
        and pair.get("KOSDAQ") == "NO_DATA"
        and bool(is_finalized("KOSPI", day))
        and bool(is_finalized("KOSDAQ", day))
    )


def _metric_request_count(result: Mapping[str, Any]) -> int:
    return int(
        result.get(
            "request_count",
            result.get("network_attempts", result.get("runner_result", {}).get("krx_open_api_attempt_count", 0)),
        )
    )


def _physical_write_count(result: Mapping[str, Any]) -> int:
    if "physical_write_count" in result:
        return int(result.get("physical_write_count", 0))
    if result.get("production_write_performed") is True:
        return max(1, int(result.get("updated_date_count", 0)))
    if result.get("status") == "PROMOTED" and result.get("leg") == "market_index":
        return 1
    return 0


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
        corporate_action_state_store: CorporateActionStateStore | None = None,
        corporate_action_refresh_service: CorporateActionRefreshService | None = None,
        corporate_action_snapshot_loader: Callable[[str], Sequence[CorporateActionSnapshot]] | None = None,
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
        self.corporate_action_state_store = corporate_action_state_store
        self.corporate_action_refresh_service = corporate_action_refresh_service
        self.corporate_action_snapshot_loader = corporate_action_snapshot_loader

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
        finalized_no_data = set(_paired_no_data_dates(self.raw_store, target))
        tail_candidates = [
            day for day in _candidate_tail(known_dates, target)
            if day not in finalized_no_data
        ]
        required_candidates = sorted(set(known_dates) | set(tail_candidates))
        etf_required_dates = _etf_raw_required_dates(required_candidates, target)
        complete_raw = sorted(
            set(_paired_complete_dates(self.raw_store, target)) | finalized_no_data
        )
        common_missing = sorted(set(required_candidates) - set(complete_raw))
        etf_missing = [
            day for day in etf_required_dates
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
            try:
                market_index_plan = dict(self.market_index_plan(target))
            except Exception as exc:  # noqa: BLE001 - defer only the known raw-frontier blocker
                reason = str(exc)
                if not reason.startswith("BLOCKED_RAW_MANIFEST_INCOMPLETE_PAIR"):
                    raise
                market_index_plan = _leg_summary(
                    "DEFERRED",
                    reason=reason,
                    blocked=["BLOCKED_RAW_MANIFEST_INCOMPLETE_PAIR"],
                )
        else:
            market_index_plan = _leg_summary("PLAN", reason="INDEX_STORE_CHECK_DEFERRED_TO_LIVE_LEG")
        extension_needed = bool(tail_candidates)
        dirty_state_count = 0
        managed_universe = self._managed_universe(target)
        if self.corporate_action_state_store is not None:
            dirty_state_count = sum(
                state.status in {"DIRTY", "FAILED"}
                and state.ticker in managed_universe
                for state in self.corporate_action_state_store.list_states()
            )
        return {
            "target_as_of": target,
            "current_certified_through": manifest.certified_through,
            "operating_calendar_frontier": authority["operating_frontier"],
            "required_candidate_dates": required_candidates,
            "common_raw": _leg_summary("PLAN", missing=common_missing, reason="REQUIRED_MINUS_COMPLETE"),
            "etf_raw": _leg_summary(
                "PLAN",
                missing=etf_missing,
                required_dates=etf_required_dates,
                reason="REQUIRED_MINUS_COMPLETE",
            ),
            "common_adjusted": common_adjusted_plan,
            "etf_adjusted": etf_adjusted_plan,
            "market_index": market_index_plan,
            "authority_extension_needed": extension_needed,
            "authority_extension_candidates": tail_candidates,
            "network_request_count": 0,
            "production_write_count": 0,
            "production_write_performed": False,
            "authority_promotion": 0,
            "manifest": manifest,
            "corporate_action": {
                "status": "NOT_BOUND" if self.corporate_action_state_store is None else "PLANNED",
                "dirty_ticker_count": dirty_state_count,
                "managed_ticker_count": len(managed_universe),
            },
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
                source_basic_info_frontier=extension.extension_end,
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
        tickers: set[str] = {
            str(t).zfill(6)
            for leg in ("common_adjusted", "etf_adjusted")
            for t in leg_results.get(leg, {}).get("validation_tickers", ())
        }
        # Compatibility for callers/fakes that predate the expanded validation
        # target contract.  This is deliberately additive; updated-only is no
        # longer the production default.
        if not tickers:
            for leg in ("common_adjusted", "etf_adjusted"):
                tickers.update(str(t).zfill(6) for t in leg_results.get(leg, {}).get("updated", []))
        checked = 0
        failures: list[dict[str, str]] = []
        for ticker in sorted(tickers):
            try:
                repo.get_daily(ticker, "1900-01-01", target)
                checked += 1
            except Exception as exc:  # noqa: BLE001 - final repository gate is fail-closed
                failures.append({"ticker": ticker, "error": str(exc)})
        return {
            "status": "PASS" if not failures else "BLOCKED",
            "checked_ticker_count": checked,
            "validation_tickers": sorted(tickers),
            "failures": failures,
            "query_audit": repo.query_audit,
        }

    @staticmethod
    def _pit_population(path: Path, target: str) -> set[str]:
        payload = _read_json(path)
        return {
            str(interval.get("ticker")).zfill(6)
            for interval in payload.get("intervals", [])
            if interval.get("state") == "COMMON"
            and str(interval.get("effective_from", "")) <= target <= str(interval.get("effective_to", ""))
        }

    @staticmethod
    def _pit_identity_keys(path: Path, target: str) -> set[tuple[str, str | None, str | None]]:
        payload = _read_json(path)
        return {
            (
                str(interval.get("ticker")).zfill(6),
                None if interval.get("isu_cd") is None else str(interval.get("isu_cd")),
                None if interval.get("market") is None else str(interval.get("market")),
            )
            for interval in payload.get("intervals", [])
            if interval.get("state") == "COMMON"
            and str(interval.get("effective_from", "")) <= target <= str(interval.get("effective_to", ""))
        }

    def _managed_universe(self, target: str, pit_path: Path | None = None) -> set[str]:
        """Return the exact current staged COMMON population for corporate-action control."""

        effective_pit = pit_path or (self.authority_dir / DEFAULT_MERGED_PIT_PATH.name)
        if effective_pit.exists():
            common = load_effective_common_adjusted_population(
                effective_pit,
                etf_acceptance_tickers=ETF_VALIDATED_ACCEPTANCE_TICKERS,
                identity_as_of=target,
            )
        else:
            common = self.common_adjusted_tickers
        return {normalize_ticker(ticker) for ticker in common}

    @staticmethod
    def _active_pit_identities(
        path: Path,
        target: str,
        tickers: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        payload = _read_json(path)
        intervals_by_ticker: dict[str, list[dict[str, Any]]] = {}
        for interval in payload.get("intervals", []):
            if interval.get("state") != "COMMON" or not interval.get("ticker"):
                continue
            ticker = normalize_ticker(interval["ticker"])
            intervals_by_ticker.setdefault(ticker, []).append(dict(interval))
        identities: dict[str, dict[str, Any]] = {}
        for ticker in {normalize_ticker(value) for value in tickers}:
            resolution = resolve_current_identity(ticker, target, intervals_by_ticker)
            if resolution.status != "RESOLVED" or resolution.interval is None:
                continue
            interval = dict(resolution.interval)
            component_intervals = interval.get("component_intervals", ())
            identity_markets = {
                str(component.get("market"))
                for component in component_intervals
                if component.get("market")
            }
            if interval.get("market"):
                identity_markets.add(str(interval["market"]))
            identities[ticker] = {
                "ticker": ticker,
                "isu_cd": interval.get("isu_cd"),
                "market": interval.get("market"),
                "markets": tuple(sorted(identity_markets)),
                "effective_from": str(interval.get("effective_from", "")),
            }
        return identities

    def _corporate_action_observation_dates(
        self,
        operating_dates: Sequence[str],
        old_boundary: str,
        target: str,
    ) -> list[str]:
        """Return persisted KOSPI/KOSDAQ trading dates in the uncertified window."""

        paired_complete_dates = set(_paired_complete_dates(self.raw_store, target))
        return sorted(
            day
            for day in set(operating_dates) & paired_complete_dates
            if old_boundary < day <= target
        )

    def _corporate_action_snapshots(
        self,
        dates: Sequence[str],
        managed_universe: set[str] | None = None,
    ) -> list[CorporateActionSnapshot]:
        if self.corporate_action_snapshot_loader is not None:
            snapshots: list[CorporateActionSnapshot] = []
            for day in dates:
                snapshots.extend(self.corporate_action_snapshot_loader(day))
            return [
                snapshot
                for snapshot in snapshots
                if managed_universe is None or snapshot.ticker in managed_universe
            ]
        if not hasattr(self.raw_store, "load_snapshot"):
            return []
        by_key: dict[tuple[str, str], CorporateActionSnapshot] = {}
        for day in sorted(set(dates)):
            for market in ("KOSPI", "KOSDAQ", "ETF"):
                try:
                    frame = self.raw_store.load_snapshot(market, day)
                except (FileNotFoundError, OSError, KeyError):
                    continue
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    continue
                for row in frame.itertuples(index=False):
                    ticker = str(getattr(row, "ticker", "")).strip()
                    listed_shares = getattr(row, "listed_shares", None)
                    if not ticker or listed_shares is None:
                        continue
                    snapshot = CorporateActionSnapshot(
                        ticker=ticker,
                        as_of=day,
                        listed_shares=listed_shares,
                        par_value=None,
                        listed_shares_semantics="RAW_DAILY_LISTED_SHARES",
                        source_name=f"KRX_RAW_{market}",
                    )
                    if managed_universe is not None and snapshot.ticker not in managed_universe:
                        continue
                    key = (snapshot.ticker, snapshot.as_of.isoformat())
                    previous = by_key.get(key)
                    if previous is not None and previous.listed_shares != snapshot.listed_shares:
                        raise DailyUpdateFoundationError(
                            f"BLOCKED_CORPORATE_ACTION_SOURCE_CONFLICT:{snapshot.ticker}:{day}"
                        )
                    by_key[key] = snapshot
        return [by_key[key] for key in sorted(by_key)]

    def _corporate_action_baselines(
        self,
        managed_universe: set[str],
        certified_through: str,
        *,
        current_identities: Mapping[str, Mapping[str, Any]] | None = None,
        target_tickers: set[str] | None = None,
    ) -> dict[str, CorporateActionSnapshot]:
        """Load the latest valid raw listed-shares observation at the old boundary."""

        if not hasattr(self.raw_store, "list_manifest") or not hasattr(self.raw_store, "load_snapshot"):
            return {}
        targets = set(managed_universe if target_tickers is None else target_tickers)
        if current_identities is not None:
            targets = {
                ticker
                for ticker in targets
                if ticker in current_identities
                and str(current_identities[ticker].get("effective_from", ""))
                and str(current_identities[ticker].get("effective_from", "")) <= certified_through
            }
        if not targets:
            return {}
        latest: dict[str, CorporateActionSnapshot] = {}
        same_day: dict[tuple[str, str], CorporateActionSnapshot] = {}
        manifest_rows = [
            row
            for market in ("KOSPI", "KOSDAQ", "ETF")
            for row in self.raw_store.list_manifest(market)
        ]
        manifest_rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("market", ""))), reverse=True)
        current_day: str | None = None
        found_on_day: set[str] = set()
        for manifest_row in manifest_rows:
            day = str(manifest_row.get("date", ""))
            if current_day != day:
                targets -= found_on_day
                found_on_day = set()
                current_day = day
            if not targets:
                break
            if day > certified_through or manifest_row.get("status") != "COMPLETE":
                continue
            market = str(manifest_row.get("market", "")).upper()
            try:
                frame = self.raw_store.load_snapshot(market, day)
            except Exception:  # noqa: BLE001 - unavailable historical baseline is non-fatal
                continue
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            for row in frame.itertuples(index=False):
                ticker = str(getattr(row, "ticker", "")).strip()
                listed_shares = getattr(row, "listed_shares", None)
                if not ticker or listed_shares is None:
                    continue
                snapshot = CorporateActionSnapshot(
                    ticker=ticker,
                    as_of=day,
                    listed_shares=listed_shares,
                    par_value=None,
                    listed_shares_semantics="RAW_DAILY_LISTED_SHARES",
                    source_name=f"KRX_RAW_{market}",
                )
                if snapshot.ticker not in targets and snapshot.ticker not in found_on_day:
                    continue
                identity = None if current_identities is None else current_identities.get(snapshot.ticker)
                if current_identities is not None and identity is None:
                    continue
                if identity is not None:
                    effective_from = str(identity.get("effective_from", ""))
                    if effective_from and snapshot.as_of.isoformat() < effective_from:
                        continue
                    allowed_markets = set(identity.get("markets", ()))
                    if not allowed_markets and identity.get("market"):
                        allowed_markets.add(str(identity["market"]))
                    if allowed_markets and market not in allowed_markets:
                        continue
                same_day_key = (snapshot.ticker, snapshot.as_of.isoformat())
                previous_same_day = same_day.get(same_day_key)
                if previous_same_day is not None and previous_same_day.listed_shares != snapshot.listed_shares:
                    raise DailyUpdateFoundationError(
                        f"BLOCKED_CORPORATE_ACTION_SOURCE_CONFLICT:{snapshot.ticker}:{day}"
                    )
                same_day[same_day_key] = snapshot
                previous = latest.get(snapshot.ticker)
                if previous is None or snapshot.as_of > previous.as_of:
                    latest[snapshot.ticker] = snapshot
                found_on_day.add(snapshot.ticker)
        targets -= found_on_day
        return latest

    def _run_corporate_action_phase(
        self,
        target: str,
        observation_dates: Sequence[str],
        *,
        managed_universe: Sequence[str] | set[str] | None = None,
        baseline_boundary: str | None = None,
        current_identities: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state_store = self.corporate_action_state_store
        service = self.corporate_action_refresh_service
        if state_store is None and service is None:
            return {"status": "NOT_BOUND", "observed_count": 0, "dirty_tickers": [], "refreshes": []}
        if state_store is None and service is not None:
            state_store = service.state_store
        if state_store is None or service is None:
            raise DailyUpdateFoundationError("BLOCKED_CORPORATE_ACTION_SERVICE_NOT_BOUND")
        snapshots = self._corporate_action_snapshots(
            observation_dates,
            None if managed_universe is None else {
                normalize_ticker(ticker) for ticker in managed_universe
            },
        )
        if managed_universe is None:
            effective_managed = {
                snapshot.ticker for snapshot in snapshots
            } | {
                state.ticker for state in state_store.list_states()
            }
        else:
            effective_managed = {normalize_ticker(ticker) for ticker in managed_universe}
        observed_tickers = {snapshot.ticker for snapshot in snapshots}
        baseline_targets = {
            ticker
            for ticker in observed_tickers & effective_managed
            if state_store.get(ticker) is None
        }
        if current_identities is not None and baseline_boundary is not None:
            baseline_targets = {
                ticker
                for ticker in baseline_targets
                if ticker in current_identities
                and str(current_identities[ticker].get("effective_from", ""))
                and str(current_identities[ticker].get("effective_from", "")) <= baseline_boundary
            }
        baseline_count = 0
        if baseline_boundary is not None:
            baselines = (
                self._corporate_action_baselines(
                    effective_managed,
                    baseline_boundary,
                    current_identities=current_identities,
                    target_tickers=baseline_targets,
                )
                if baseline_targets
                else {}
            )
            for ticker, baseline in baselines.items():
                state_store.evaluate_and_record(baseline)
                baseline_count += 1
        observed = 0
        for snapshot in snapshots:
            try:
                state_store.evaluate_and_record(snapshot)
                observed += 1
            except Exception as exc:  # noqa: BLE001 - detector/state contract is expected blocker
                raise DailyUpdateFoundationError(
                    f"BLOCKED_CORPORATE_ACTION_OBSERVATION:{snapshot.ticker}:{type(exc).__name__}:{exc}"
                ) from exc
        dirty_tickers = sorted(
            state.ticker
            for state in state_store.list_states()
            if state.status in {"DIRTY", "FAILED"} and state.ticker in effective_managed
        )
        refreshes: list[dict[str, Any]] = []
        for ticker in dirty_tickers:
            result = service.refresh_dirty(ticker, target)
            refreshes.append(asdict(result))
        remaining = [
            state.ticker
            for state in state_store.list_states()
            if state.status in {"DIRTY", "FAILED"} and state.ticker in effective_managed
        ]
        if remaining:
            raise DailyUpdateFoundationError(
                f"BLOCKED_CORPORATE_ACTION_DIRTY_REMAINS:{sorted(remaining)}"
            )
        physical_writes = sum(1 for result in refreshes if result.get("status") == "CLEAN")
        return {
            "status": "PASS",
            "observed_count": observed,
            "baseline_count": baseline_count,
            "managed_ticker_count": len(effective_managed),
            "dirty_tickers": dirty_tickers,
            "remaining_dirty_tickers": [],
            "refreshes": refreshes,
            "physical_write_count": physical_writes,
            "production_write_performed": bool(physical_writes),
        }

    def _validate_required_legs_complete(
        self,
        plan: Mapping[str, Any],
        leg_results: Mapping[str, Any],
    ) -> None:
        """Fail closed unless every required leg has terminal, internally complete coverage."""

        incomplete: list[str] = []

        def result_for(name: str) -> Mapping[str, Any]:
            value = leg_results.get(name, {})
            return value if isinstance(value, Mapping) else {}

        def required_dates_for(name: str) -> list[str]:
            result = result_for(name)
            values = result.get("required_dates")
            if values is None:
                values = plan.get(name, {}).get("required_dates", plan.get("required_candidate_dates", ()))
            if name == "etf_raw":
                return _etf_raw_required_dates(values or (), str(plan["target_as_of"]))
            return _normalise_session_dates(values or ())

        def terminal_raw(market: str, day: str, *, require_complete: bool = False) -> bool:
            row = self.raw_store.get_manifest(market, day)
            if row is None:
                return False
            status = str(row.get("status", "")).upper()
            if status == "COMPLETE":
                return True
            if require_complete or status != "NO_DATA":
                return False
            checker = getattr(self.raw_store, "is_finalized_no_data", None)
            return callable(checker) and bool(checker(market, day))

        common_raw = result_for("common_raw")
        common_required = required_dates_for("common_raw")
        runner_result = common_raw.get("runner_result", {})
        runner_status = (
            str(runner_result.get("status", "")).upper()
            if isinstance(runner_result, Mapping)
            else ""
        )
        if common_raw.get("failures") or runner_status in {"FAILED", "ERROR", "BLOCKED"}:
            incomplete.append("common_raw")
        if common_required and any(
            not (
                terminal_raw("KOSPI", day, require_complete=True)
                and terminal_raw("KOSDAQ", day, require_complete=True)
            )
            and not (
                terminal_raw("KOSPI", day)
                and terminal_raw("KOSDAQ", day)
            )
            for day in common_required
        ):
            incomplete.append("common_raw")
        if not common_required and common_raw.get("missing_dates"):
            incomplete.append("common_raw")

        etf_raw = result_for("etf_raw")
        etf_required = required_dates_for("etf_raw")
        if etf_raw.get("failures") or etf_raw.get("missing_dates"):
            incomplete.append("etf_raw")
        if any(
            self.raw_store.get_manifest("KOSPI", day) is not None
            and str(self.raw_store.get_manifest("KOSPI", day).get("status", "")).upper() == "COMPLETE"
            and not terminal_raw("ETF", day, require_complete=True)
            for day in etf_required
        ):
            incomplete.append("etf_raw")

        def adjusted_complete(name: str) -> bool:
            result = result_for(name)
            if result.get("failures") or result.get("blocked"):
                return False
            expected = {normalize_ticker(ticker) for ticker in result.get("expected_tickers", ())}
            accounted = {
                normalize_ticker(ticker) for ticker in result.get("updated", ())
            }
            accounted.update(
                normalize_ticker(item.get("ticker"))
                for item in result.get("skipped", ())
                if isinstance(item, Mapping) and item.get("ticker")
            )
            return not expected or accounted == expected

        if not adjusted_complete("common_adjusted"):
            incomplete.append("common_adjusted")
        if not adjusted_complete("etf_adjusted"):
            incomplete.append("etf_adjusted")

        if result_for("market_index").get("status") not in {"PROMOTED", "IDEMPOTENT_NOOP"}:
            incomplete.append("market_index")
        corporate_action = result_for("corporate_action")
        if (
            corporate_action.get("status") != "PASS"
            or corporate_action.get("remaining_dirty_tickers")
        ):
            incomplete.append("corporate_action")
        if result_for("repository_v2").get("status") != "PASS":
            incomplete.append("repository_v2")
        if result_for("pit_authority").get("status") not in {"STAGED", "UNCHANGED"}:
            incomplete.append("pit_authority")

        if incomplete:
            unique = ",".join(dict.fromkeys(incomplete))
            raise DailyUpdateFoundationError(f"BLOCKED_REQUIRED_LEG_INCOMPLETE:{unique}")

    def _validate_common_raw_before_downstream(
        self,
        result: Mapping[str, Any],
        required_dates: Sequence[str],
    ) -> None:
        """Stop the cycle immediately when COMMON raw cannot cover the target."""

        runner_result = result.get("runner_result", {})
        runner_result = runner_result if isinstance(runner_result, Mapping) else {}
        blockers = [
            str(item)
            for item in list(result.get("blockers", ())) + list(runner_result.get("blockers", ()))
            if item
        ]
        runner_status = str(runner_result.get("status", "")).upper()
        if runner_status.startswith("BLOCKED_") or runner_status.startswith("BACKFILL_PAUSED_"):
            blockers.append(runner_status)
        if blockers:
            blocker = blockers[0]
            if blocker.startswith("BLOCKED_COMMON_RAW:"):
                raise DailyUpdateFoundationError(blocker)
            raise DailyUpdateFoundationError(f"BLOCKED_COMMON_RAW:{blocker}")
        if result.get("failures"):
            raise DailyUpdateFoundationError("BLOCKED_COMMON_RAW:FAILED")

        required = _normalise_session_dates(required_dates)

        def terminal_pair(day: str) -> bool:
            rows = {
                market: self.raw_store.get_manifest(market, day)
                for market in ("KOSPI", "KOSDAQ")
            }
            statuses = {
                market: str((rows[market] or {}).get("status", "")).upper()
                for market in rows
            }
            if all(statuses[market] == "COMPLETE" for market in rows):
                return True
            if not all(statuses[market] == "NO_DATA" for market in rows):
                return False
            checker = getattr(self.raw_store, "is_finalized_no_data", None)
            return callable(checker) and all(checker(market, day) for market in rows)

        if required and any(not terminal_pair(day) for day in required):
            raise DailyUpdateFoundationError("BLOCKED_COMMON_RAW:BLOCKED_COVERAGE")
        new_boundary = str(result.get("new_boundary", ""))
        if required and (not new_boundary or new_boundary < max(required)):
            raise DailyUpdateFoundationError("BLOCKED_COMMON_RAW:BLOCKED_COVERAGE")

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
        builder_kwargs: dict[str, Any] = {
            "extension_calendar_dates": extension_dates,
            # Continue from the already-published merged authority.  The historical
            # frozen artifacts remain the immutable base of that chain; reusing only
            # the original frozen file here would silently discard prior rolling
            # extensions on the second daily run.
            "frozen_pit_path": self.authority_dir / DEFAULT_MERGED_PIT_PATH.name,
            "historical_calendar_path": self.authority_dir / DEFAULT_MERGED_CALENDAR_PATH.name,
        }
        if self.basic_info_runner is not None:
            raw_root = getattr(self.basic_info_runner, "raw_root", None)
            checkpoint_path = getattr(self.basic_info_runner, "checkpoint_path", None)
            if raw_root is not None:
                builder_kwargs["basic_info_raw_root"] = Path(raw_root)
            if checkpoint_path is not None:
                builder_kwargs["acquisition_checkpoint_path"] = Path(checkpoint_path)
        extension = self.pit_extension_builder(**builder_kwargs)
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
            raw_reason = str(exc)
            migration_required = "ROLLING_MANIFEST_MISSING_MERGED_" in raw_reason
            return {
                "target_as_of": target,
                "final_status": "BLOCKED",
                "status": "BLOCKED",
                "boundary_unchanged": True,
                "reason": "BLOCKED_AUTHORITY_MIGRATION_REQUIRED" if migration_required else raw_reason,
                "authority_migration_required": migration_required,
                "network_request_count": 0,
                "production_write_count": 0,
                "production_write_performed": False,
                "authority_promotion": 0,
            }
        manifest: RollingAuthorityManifest = plan.pop("manifest")
        if dry_run:
            complete_plan = not any(
                plan.get(leg, {}).get("missing_dates")
                or plan.get(leg, {}).get("blocked")
                or plan.get(leg, {}).get("failures")
                for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted", "market_index")
            ) and not plan["authority_extension_needed"] and not plan["corporate_action"]["dirty_ticker_count"]
            return {
                **plan,
                "final_status": "NOOP" if complete_plan else "BLOCKED",
                "status": "DRY_RUN",
                "reason": None if complete_plan else "DRY_RUN_NO_NETWORK_OR_PRODUCTION_WRITE",
                "network_request_count": 0,
                "production_write_count": 0,
                "production_write_performed": False,
                "authority_promotion": 0,
            }
        if (
            not plan["common_raw"]["missing_dates"]
            and not plan["etf_raw"]["missing_dates"]
            and not plan["common_adjusted"].get("missing_dates")
            and not plan["common_adjusted"].get("blocked")
            and not plan["common_adjusted"].get("failures")
            and not plan["etf_adjusted"].get("missing_dates")
            and not plan["market_index"].get("missing_dates")
            and not plan["authority_extension_needed"]
            and not plan["corporate_action"]["dirty_ticker_count"]
            and plan["corporate_action"]["status"] == "PLANNED"
            and (target <= manifest.certified_through or target not in plan["required_candidate_dates"])
        ):
            self._validate_required_legs_complete(
                plan,
                {
                    "common_raw": {"required_dates": plan["required_candidate_dates"]},
                    "etf_raw": {"required_dates": plan["etf_raw"].get("required_dates", ())},
                    "common_adjusted": {"updated": [], "skipped": []},
                    "etf_adjusted": {"updated": [], "skipped": []},
                    "market_index": {"status": "IDEMPOTENT_NOOP"},
                    "corporate_action": {"status": "PASS", "remaining_dirty_tickers": []},
                    "repository_v2": {"status": "PASS"},
                    "pit_authority": {"status": "UNCHANGED"},
                },
            )
            return {
                **plan,
                "final_status": "NOOP",
                "status": "NOOP_ALREADY_COMPLETE",
                "network_request_count": 0,
                "production_write_count": 0,
                "production_write_performed": False,
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
            self._validate_common_raw_before_downstream(
                leg_results["common_raw"],
                required_dates,
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

                staged_pit_path = stage_dir / DEFAULT_MERGED_PIT_PATH.name
                common_tickers = list(self.common_adjusted_tickers)
                population_added: set[str] = set()
                identity_added: set[str] = set()
                if staged_pit_path.exists():
                    common_tickers = load_effective_common_adjusted_population(
                        staged_pit_path,
                        etf_acceptance_tickers=ETF_VALIDATED_ACCEPTANCE_TICKERS,
                        identity_as_of=target,
                    )
                    previous_pit_path = self.authority_dir / DEFAULT_MERGED_PIT_PATH.name
                    if previous_pit_path.exists():
                        population_added = self._pit_population(staged_pit_path, target) - self._pit_population(previous_pit_path, target)
                        staged_identity_keys = self._pit_identity_keys(staged_pit_path, target)
                        previous_identity_keys = self._pit_identity_keys(previous_pit_path, target)
                        identity_added = {
                            ticker
                            for ticker, _isu_cd, _market in staged_identity_keys - previous_identity_keys
                        }
                managed_universe = {
                    normalize_ticker(ticker)
                    for ticker in common_tickers
                }
                current_identities = self._active_pit_identities(
                    staged_pit_path,
                    target,
                    sorted(managed_universe),
                )

                leg_results["etf_raw"] = self._call_refresh(
                    self.etf_raw_updater,
                    manifest.leg_boundaries["etf_raw"],
                    target,
                    required_dates=operating_dates,
                )
                observation_dates = self._corporate_action_observation_dates(
                    operating_dates,
                    old_boundary,
                    target,
                )
                leg_results["corporate_action"] = self._run_corporate_action_phase(
                    target,
                    observation_dates,
                    managed_universe=managed_universe,
                    baseline_boundary=manifest.certified_through,
                    current_identities=current_identities,
                )
                leg_results["pit_authority"]["population_added_tickers"] = sorted(population_added)
                leg_results["pit_authority"]["identity_added_tickers"] = sorted(identity_added)
                if extension is not None and hasattr(self.common_adjusted_updater, "refresh_with_extension"):
                    leg_results["common_adjusted"] = self.common_adjusted_updater.refresh_with_extension(
                        common_tickers,
                        manifest.leg_boundaries["common_adjusted"],
                        target,
                        extension,
                        workdir=stage_dir,
                    )
                else:
                    leg_results["common_adjusted"] = self.common_adjusted_updater.refresh(
                        common_tickers,
                        manifest.leg_boundaries["common_adjusted"],
                        target,
                    )
                if (
                    leg_results["common_adjusted"].get("failures")
                    or leg_results["common_adjusted"].get("blocked")
                ):
                    raise DailyUpdateFoundationError("BLOCKED_COMMON_ADJUSTED_AUTHORITY")
                leg_results["etf_adjusted"] = self.etf_adjusted_updater.refresh(
                    manifest.leg_boundaries["etf_adjusted"], target
                )
                leg_results["common_adjusted"]["validation_tickers"] = sorted(
                    {
                        str(ticker).zfill(6)
                        for ticker in leg_results["common_adjusted"].get("updated", ())
                    }
                    | population_added
                    | identity_added
                )
                leg_results["etf_adjusted"]["validation_tickers"] = list(
                    leg_results["etf_adjusted"].get("expected_tickers", ())
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
                self._validate_required_legs_complete(plan, leg_results)
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
                        "network_request_count": sum(_metric_request_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                        "production_write_count": sum(_physical_write_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                        "production_write_performed": any(_physical_write_count(v) > 0 for v in leg_results.values() if isinstance(v, Mapping)),
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
                        source_basic_info_frontier=extension.extension_end,
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
                    "network_request_count": sum(_metric_request_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                    "production_write_count": sum(_physical_write_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                    "production_write_performed": any(_physical_write_count(v) > 0 for v in leg_results.values() if isinstance(v, Mapping)),
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
                "network_request_count": sum(_metric_request_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                "production_write_count": sum(_physical_write_count(v) for v in leg_results.values() if isinstance(v, Mapping)),
                "production_write_performed": any(_physical_write_count(v) > 0 for v in leg_results.values() if isinstance(v, Mapping)),
                "authority_promotion": 0,
            }


__all__ = ["DailyUpdateFoundation", "DailyUpdateFoundationError", "normalize_target_as_of"]
