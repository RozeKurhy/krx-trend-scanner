"""COMMON Stock Report projection of the existing Pattern B authority.

This adapter reuses the sealed Pattern B evaluator and operational history
policy. It does not implement feature formulas, state thresholds, or strategy
execution rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from trend_scanner.data.rolling_market_data_refresh import DEFAULT_ROLLING_AUTHORITY_DIR
from trend_scanner.patterns import pattern_b_operational as operational
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b
from trend_scanner.reporting.models import (
    MonthlyObservation,
    PatternBObservation,
    PatternBProvenance,
    PatternBSection,
)
from trend_scanner.universe.instrument_metadata import AssetType


PIT_INTERVALS_SOURCE = (DEFAULT_ROLLING_AUTHORITY_DIR / "merged_pit_intervals.json").as_posix()


def _provenance(
    *,
    history_effective_from: str | None = None,
    history_segment_count: int = 0,
    market_transfer_stitched: bool = False,
    history_stop_reason: str | None = None,
) -> PatternBProvenance:
    return PatternBProvenance(
        market_data_authority="MarketDataRepositoryV2",
        identity_authority="merged_pit_intervals.json",
        source_artifact=PIT_INTERVALS_SOURCE,
        feature_contract_version="V01",
        state_rule_version="PATTERN_B_STATE_RULE_V02",
        operational_contract="PATTERN_B_OPERATIONAL_V02",
        history_effective_from=history_effective_from,
        history_segment_count=history_segment_count,
        market_transfer_stitched=market_transfer_stitched,
        history_stop_reason=history_stop_reason,
    )


def _unavailable(
    *,
    as_of: str,
    reason_code: str,
    reason_detail: str | None = None,
    provenance: PatternBProvenance | None = None,
) -> PatternBSection:
    return PatternBSection(
        applicability="APPLICABLE",
        evaluation_status="UNAVAILABLE",
        pattern_b_state=None,
        as_of=as_of,
        freshness_status=None,
        expected_weekly_bar=None,
        range_36m=None,
        monthly_ma24_distance=None,
        range_52w=None,
        monthly_last_bar=None,
        weekly_last_bar=None,
        reason_codes=[reason_code],
        reason_details=[reason_detail] if reason_detail else [],
        monthly_history=[],
        monthly_history_24m=[],
        provenance=provenance or _provenance(),
    )


def _calendar_dates(payload: dict) -> list[str]:
    for key in ("dates", "trading_dates", "calendar_dates"):
        if key in payload and isinstance(payload[key], list):
            dates = sorted({str(value)[:10] for value in payload[key]})
            if dates:
                return dates
    raise ValueError("merged trading calendar has no date list")


def _monthly_query_dates(
    monthly_observations: Iterable[MonthlyObservation], as_of: str,
) -> list[str]:
    """Use report month observations, translated to the feature contract's MonthEnd labels."""
    target = pd.Timestamp(as_of).normalize()
    month_ends = {
        (pd.Timestamp(observation.as_of).normalize() + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        for observation in monthly_observations
        if pd.Timestamp(observation.as_of).normalize() <= target
    }
    month_ends = {value for value in month_ends if value <= as_of}
    dates = sorted(month_ends)[-11:]
    if not dates or dates[-1] != as_of:
        dates.append(as_of)
    return dates[-12:]


def _monthly_query_dates_24m(
    monthly_observations: Iterable[MonthlyObservation], as_of: str,
) -> list[str]:
    """Return the inclusive t-24M monthly window plus the current as-of sample."""
    target = pd.Timestamp(as_of).normalize()
    target_date = target.strftime("%Y-%m-%d")
    month_ends = {
        (pd.Timestamp(observation.as_of).normalize() + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        for observation in monthly_observations
        if pd.Timestamp(observation.as_of).normalize() <= target
    }
    month_ends = sorted(value for value in month_ends if value <= target_date)
    # At a month-end the current point is already in the monthly observations,
    # so keep the full t-24M..t inclusive 25 rows. Otherwise include 24 month
    # ends plus the exact current as-of point.
    if target_date in month_ends:
        return month_ends[-25:]
    return [*month_ends[-24:], target_date][-25:]


def build_pattern_b_section(
    *,
    ticker: str,
    name: str,
    asset_type: str,
    metadata_provenance_mode: str,
    as_of: str,
    monthly_observations: Iterable[MonthlyObservation],
    repo_root: Path,
    repository,
) -> PatternBSection | None:
    """Build an informational Pattern B section from the current official authority.

    The section is COMMON-only. Historical chart samples call the same official
    evaluator on date-truncated frames from one Repository V2 identity chain.
    """
    if asset_type != AssetType.COMMON.value:
        return None
    if metadata_provenance_mode != "CURRENT_VERIFIED":
        return _unavailable(as_of=as_of, reason_code="COMMON_IDENTITY_NOT_TRUSTED")
    if repository is None:
        return _unavailable(as_of=as_of, reason_code="PATTERN_B_REPOSITORY_NOT_PROVIDED")

    authority_dir = repo_root / DEFAULT_ROLLING_AUTHORITY_DIR
    pit_path = authority_dir / "merged_pit_intervals.json"
    calendar_path = authority_dir / "merged_trading_calendar.json"
    if not pit_path.is_file() or not calendar_path.is_file():
        return _unavailable(as_of=as_of, reason_code="PATTERN_B_ROLLING_AUTHORITY_UNAVAILABLE")

    pit_payload = json.loads(pit_path.read_text(encoding="utf-8"))
    calendar_payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    intervals = [
        interval for interval in pit_payload.get("intervals", [])
        if str(interval.get("ticker", "")).strip().upper() == ticker.upper()
    ]
    active = [
        interval for interval in intervals
        if interval.get("state") == "COMMON"
        and str(interval.get("market", "")).upper() in operational.TRANSFER_MARKETS
        and str(interval.get("effective_from", "")) <= as_of <= str(interval.get("effective_to", ""))
    ]
    if not active:
        return _unavailable(as_of=as_of, reason_code="PATTERN_B_COMMON_IDENTITY_NOT_FOUND")
    if len(active) != 1:
        return _unavailable(as_of=as_of, reason_code="PATTERN_B_COMMON_IDENTITY_AMBIGUOUS")

    trading_dates = _calendar_dates(calendar_payload)
    if as_of not in trading_dates:
        return _unavailable(as_of=as_of, reason_code="PATTERN_B_AS_OF_NOT_IN_MARKET_CALENDAR")

    chain = operational.history_chain(ticker.upper(), active[0], intervals, trading_dates)
    provenance = _provenance(
        history_effective_from=chain.history_effective_from,
        history_segment_count=len(chain.segments),
        market_transfer_stitched=chain.market_transfer_stitched,
        history_stop_reason=chain.stop_reason,
    )
    daily = operational.load_history(repository, ticker.upper(), chain, as_of)
    if daily is None or daily.empty:
        audit = getattr(repository, "query_audit", {}).get(ticker.upper(), {})
        detail = str(audit.get("reason") or "") or None
        return _unavailable(
            as_of=as_of,
            reason_code="PATTERN_B_PRICE_HISTORY_UNAVAILABLE",
            reason_detail=detail,
            provenance=provenance,
        )
    if daily.index.max() > pd.Timestamp(as_of):
        raise ValueError("PATTERN_B_POST_AS_OF_PRICE_ROW")

    current = evaluate_pattern_b(ticker.upper(), daily, as_of, name=name)
    monthly_observations = list(monthly_observations)
    legacy_query_dates = _monthly_query_dates(monthly_observations, as_of)
    query_dates_24m = _monthly_query_dates_24m(monthly_observations, as_of)
    monthly_results_by_date = {}
    for query_date in query_dates_24m:
        result = current if query_date == as_of else evaluate_pattern_b(
            ticker.upper(), daily, query_date, name=name,
        )
        monthly_results_by_date[query_date] = PatternBObservation(
            as_of=result.as_of,
            evaluation_status=result.evaluation_status.value,
            pattern_b_state=result.pattern_b_state,
            range_36m=result.range_36m,
            monthly_ma24_distance=result.monthly_ma24_distance,
            range_52w=result.range_52w,
            monthly_last_bar=result.monthly_last_bar,
            weekly_last_bar=result.weekly_last_bar,
        )
    missing_legacy_dates = sorted(set(legacy_query_dates) - set(monthly_results_by_date))
    if missing_legacy_dates:
        raise ValueError(f"PATTERN_B_24M_HISTORY_MISSING_LEGACY_12M_DATES:{missing_legacy_dates}")
    monthly_results = [monthly_results_by_date[query_date] for query_date in legacy_query_dates]
    monthly_results_24m = [monthly_results_by_date[query_date] for query_date in query_dates_24m]

    return PatternBSection(
        applicability="APPLICABLE",
        evaluation_status=current.evaluation_status.value,
        pattern_b_state=current.pattern_b_state,
        as_of=as_of,
        freshness_status=operational.freshness_status(current.weekly_last_bar, as_of),
        expected_weekly_bar=operational.expected_weekly_bar(as_of),
        range_36m=current.range_36m,
        monthly_ma24_distance=current.monthly_ma24_distance,
        range_52w=current.range_52w,
        monthly_last_bar=current.monthly_last_bar,
        weekly_last_bar=current.weekly_last_bar,
        reason_codes=list(current.reason_codes),
        reason_details=list(current.reason_details),
        monthly_history=monthly_results,
        monthly_history_24m=monthly_results_24m,
        provenance=PatternBProvenance(
            **{
                **provenance.__dict__,
                "feature_contract_version": current.feature_contract_version,
                "state_rule_version": current.state_rule_version,
            }
        ),
    )


__all__ = ["build_pattern_b_section"]
