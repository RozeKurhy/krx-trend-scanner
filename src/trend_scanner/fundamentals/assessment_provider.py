"""Production boundary for Fundamentals Assessment.

The provider delegates data acquisition to the existing DerivedMetricsProvider
and passes that exact build, ticker, fiscal years, and PIT cutoff to the pure
assessment engine.  It has no direct OpenDART/XBRL/network access.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .assessment import (
    ASSESSMENT_SCOPE_CURRENT,
    ASSESSMENT_SCOPE_RANGE,
    FundamentalsAssessmentEngine,
)
from .assessment_models import FundamentalsAssessmentResult
from .derived_metrics_provider import DerivedMetricsProvider


def _as_of(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"Invalid requested_as_of: {value!r}") from None


class FundamentalsAssessmentProvider:
    """Build one deterministic assessment from the Derived Metrics boundary."""

    def __init__(self, derived_metrics_provider: DerivedMetricsProvider,
                 assessment_engine: FundamentalsAssessmentEngine | None = None):
        self.derived_metrics_provider = derived_metrics_provider
        self.assessment_engine = assessment_engine or FundamentalsAssessmentEngine()

    def build(
        self,
        ticker: str,
        fiscal_years: Iterable[str] | str,
        requested_as_of: str | date,
        *,
        company: Mapping[str, Any] | None = None,
        company_metadata: Mapping[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> FundamentalsAssessmentResult:
        cutoff = _as_of(requested_as_of)
        derived_build = self.derived_metrics_provider.build(
            str(ticker), fiscal_years, cutoff, company=company,
            company_metadata=company_metadata, force_refresh=force_refresh,
        )
        # A caller-provided fiscal-year list is an explicit range, not a claim
        # about the full current filing universe.
        return self.assessment_engine.assess(
            derived_build, requested_as_of=cutoff,
            assessment_scope=ASSESSMENT_SCOPE_RANGE,
        )

    def build_current(
        self,
        ticker: str,
        requested_as_of: str | date,
        *,
        lookback_fiscal_years: int = 5,
        company: Mapping[str, Any] | None = None,
        company_metadata: Mapping[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> FundamentalsAssessmentResult:
        """Build a CURRENT_AS_OF assessment over a configurable ending-Y window."""

        cutoff = _as_of(requested_as_of)
        if lookback_fiscal_years < 1:
            raise ValueError("lookback_fiscal_years must be >= 1")
        year = int(cutoff[:4])
        fiscal_years = tuple(str(value) for value in range(year - lookback_fiscal_years + 1, year + 1))
        derived_build = self.derived_metrics_provider.build(
            str(ticker), fiscal_years, cutoff, company=company,
            company_metadata=company_metadata, force_refresh=force_refresh,
        )
        return self.assessment_engine.assess(
            derived_build, requested_as_of=cutoff,
            assessment_scope=ASSESSMENT_SCOPE_CURRENT,
            expected_current_fiscal_year=str(year),
        )

    assess = build
