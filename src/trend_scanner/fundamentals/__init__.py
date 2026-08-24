"""PIT-safe OpenDART fundamentals foundation."""

from .opendart_contract import (
    PIT_GRANULARITY,
    BasisSelection,
    FilingRecord,
    FilingSelection,
    StatementFamily,
    classify_company_family,
    map_statement_family,
    redact_url,
    resolve_core_account,
    select_pit_filing,
    select_statement_basis,
)
from .corp_code_repository import CorpCodeRepository
from .filing_registry import FilingRegistry
from .financial_statement_provider import FinancialStatementProvider
from .models import FinancialObservation, NormalizedFinancialReport, RegisteredFiling
from .opendart_client import OpenDartClient
from .pit_resolver import PITResolver
from .xbrl_repository import XbrlRepository
from .period_models import PeriodizationFact, PeriodizationResult, PeriodizedFinancialObservation, PriorCumulativeSelection
from .periodization import PeriodizationEngine, facts_from_xbrl_rows, periodize_facts, periodize_fiscal_year
from .periodization_provider import PeriodizationBuild, PeriodizationProvider, PeriodizationProviderError
from .derived_metrics import (
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    DATA_UNAVAILABLE,
    DerivedMetricObservation,
    DerivedMetricsEngine,
    DerivedMetricsError,
    DerivedMetricsResult,
    INPUT_NOT_READY,
    NOT_APPLICABLE,
    UNDEFINED_BASE,
    calculate_derived_metrics,
    derive_metrics,
)
from .derived_metrics_provider import DerivedMetricsBuild, DerivedMetricsProvider
from .assessment_models import AssessmentEvidence, FundamentalsAssessmentResult
from .assessment import (
    ASSESSMENT_SCOPE_CURRENT,
    ASSESSMENT_SCOPE_RANGE,
    CURRENTNESS_RANGE_ONLY,
    CURRENTNESS_STALE,
    CURRENTNESS_VERIFIED,
    FundamentalsAssessment,
    FundamentalsAssessmentEngine,
    assess_fundamentals,
)
from .assessment_provider import FundamentalsAssessmentProvider

__all__ = [
    "PIT_GRANULARITY",
    "BasisSelection",
    "FilingRecord",
    "FilingSelection",
    "StatementFamily",
    "classify_company_family",
    "map_statement_family",
    "redact_url",
    "resolve_core_account",
    "select_pit_filing",
    "select_statement_basis",
    "CorpCodeRepository",
    "FilingRegistry",
    "FinancialStatementProvider",
    "FinancialObservation",
    "NormalizedFinancialReport",
    "RegisteredFiling",
    "OpenDartClient",
    "PITResolver",
    "XbrlRepository",
    "PeriodizationFact",
    "PeriodizationResult",
    "PeriodizedFinancialObservation",
    "PriorCumulativeSelection",
    "PeriodizationEngine",
    "facts_from_xbrl_rows",
    "periodize_facts",
    "periodize_fiscal_year",
    "PeriodizationBuild",
    "PeriodizationProvider",
    "PeriodizationProviderError",
    "DerivedMetricObservation",
    "DerivedMetricsEngine",
    "DerivedMetricsError",
    "DerivedMetricsResult",
    "DATA_UNAVAILABLE",
    "INPUT_NOT_READY",
    "UNDEFINED_BASE",
    "NOT_APPLICABLE",
    "BASIS_MISMATCH",
    "CURRENCY_MISMATCH",
    "calculate_derived_metrics",
    "derive_metrics",
    "DerivedMetricsBuild",
    "DerivedMetricsProvider",
    "AssessmentEvidence",
    "FundamentalsAssessmentResult",
    "FundamentalsAssessment",
    "FundamentalsAssessmentEngine",
    "assess_fundamentals",
    "FundamentalsAssessmentProvider",
    "ASSESSMENT_SCOPE_CURRENT",
    "ASSESSMENT_SCOPE_RANGE",
    "CURRENTNESS_RANGE_ONLY",
    "CURRENTNESS_STALE",
    "CURRENTNESS_VERIFIED",
]
