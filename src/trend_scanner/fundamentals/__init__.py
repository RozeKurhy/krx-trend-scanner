"""Architecture-stage contracts for OpenDART Fundamentals.

This package intentionally contains small, production-independent contracts
only.  It does not fetch data, calculate scores, or integrate Stock Reports.
"""

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
]
