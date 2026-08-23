"""Production orchestration from PeriodizationProvider to DerivedMetricsEngine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .derived_metrics import DerivedMetricsEngine, DerivedMetricsResult
from .period_models import PeriodizationResult, PeriodizedFinancialObservation
from .periodization_provider import PeriodizationBuild, PeriodizationProvider


def _as_of(value: str | date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"Invalid requested_as_of: {value!r}") from None


@dataclass(frozen=True)
class DerivedMetricsBuild:
    """Auditable result of one multi-year production derived-metrics build."""

    ticker: str
    requested_as_of: str
    fiscal_years: tuple[str, ...]
    periodization_builds: tuple[PeriodizationBuild, ...]
    canonical_observations: tuple[PeriodizedFinancialObservation, ...]
    result: DerivedMetricsResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "requested_as_of": self.requested_as_of,
            "fiscal_years": list(self.fiscal_years),
            "periodization_builds": [item.to_dict() for item in self.periodization_builds],
            "canonical_observations": [item.to_dict() for item in self.canonical_observations],
            "result": self.result.to_dict(),
        }


class DerivedMetricsProvider:
    """Call the real periodization boundary, then derive from canonical output."""

    def __init__(self, periodization_provider: PeriodizationProvider,
                 derived_engine: DerivedMetricsEngine | None = None):
        self.periodization_provider = periodization_provider
        self.derived_engine = derived_engine or DerivedMetricsEngine()

    def build(self, ticker: str, fiscal_years: Iterable[str] | str,
              requested_as_of: str | date, *,
              company: Mapping[str, Any] | None = None,
              company_metadata: Mapping[str, Any] | None = None,
              force_refresh: bool = False) -> DerivedMetricsBuild:
        years = (str(fiscal_years),) if isinstance(fiscal_years, (str, int)) else tuple(
            str(year) for year in fiscal_years
        )
        if not years:
            raise ValueError("fiscal_years must not be empty")
        cutoff = _as_of(requested_as_of)
        builds = tuple(
            self.periodization_provider.build(
                str(ticker), year, cutoff, company=company,
                company_metadata=company_metadata, force_refresh=force_refresh,
            )
            for year in years
        )
        canonical = tuple(
            observation
            for build in builds
            for observation in build.result.observations
        )
        result = self.derived_engine.derive(
            PeriodizationResult(canonical), requested_as_of=cutoff,
        )
        return DerivedMetricsBuild(
            ticker=str(ticker), requested_as_of=cutoff, fiscal_years=years,
            periodization_builds=builds, canonical_observations=canonical,
            result=result,
        )
