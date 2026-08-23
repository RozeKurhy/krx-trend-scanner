"""PIT-safe filing-to-canonical financial observation provider."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .corp_code_repository import CorpCodeRepository
from .filing_registry import FilingRegistry
from .models import FinancialObservation, NormalizedFinancialReport, RegisteredFiling
from .opendart_contract import (
    AccountResolutionStatus,
    CompanyFamily,
    CORE_METRIC_SPECS,
    NON_FINANCIAL_ONLY_METRICS,
    PIT_GRANULARITY,
    REPORT_TYPE_BY_CODE,
    classify_company_family,
    resolve_core_account,
    select_statement_basis,
)
from .pit_resolver import PITResolver
from .xbrl_repository import XbrlRepository


NON_FINANCIAL_METRICS = ("assets", "liabilities", "equity", "revenue", "operating_income", "net_income", "operating_cash_flow")
FINANCIAL_METRICS = ("assets", "liabilities", "equity", "net_income", "operating_cash_flow")


def _amount_type(row: Mapping[str, Any], reprt_code: str) -> str:
    if row.get("period_start"):
        return "CUMULATIVE"
    if row.get("period_end"):
        return "CURRENT_PERIOD"
    return "UNKNOWN"


class FinancialStatementProvider:
    def __init__(self, corp_codes: CorpCodeRepository, filings: FilingRegistry, xbrl: XbrlRepository,
                 *, pit: PITResolver | None = None):
        self.corp_codes = corp_codes
        self.filings = filings
        self.xbrl = xbrl
        self.pit = pit or PITResolver()

    def normalize(self, *, ticker: str, bsns_year: str, reprt_code: str, as_of: str | date,
                  company: Mapping[str, Any] | None = None, force_refresh: bool = False,
                  fs_div_requested: str = "CFS") -> NormalizedFinancialReport:
        record = self.corp_codes.get_record(ticker)
        rows = self.filings.list_regular_filings(ticker=ticker, corp_code=record.corp_code,
                                                 bsns_year=str(bsns_year), reprt_code=str(reprt_code),
                                                 force_refresh=force_refresh)
        resolution = self.pit.resolve(rows, as_of=as_of, bsns_year=str(bsns_year), reprt_code=str(reprt_code))
        selected = resolution.selected
        if selected is None:
            return NormalizedFinancialReport(
                ticker=ticker, corp_code=record.corp_code, company_family=CompanyFamily.UNKNOWN.value,
                bsns_year=str(bsns_year), reprt_code=str(reprt_code), report_type=REPORT_TYPE_BY_CODE.get(str(reprt_code), "UNKNOWN"),
                period_start=None, period_end=None, rcept_no="", rcept_dt="", pit_as_of=str(as_of),
                pit_availability=resolution.availability or "FUTURE_FORBIDDEN", fs_div_requested=fs_div_requested,
                fs_div_used=None, fallback_used=False, fallback_reason=None, source_sha256=None,
                observations=(), status=resolution.status, reason=resolution.reason,
            )
        artifact = self.xbrl.fetch(selected, force_refresh=force_refresh)
        raw_rows = self.xbrl.statement_rows(artifact, bsns_year=str(bsns_year), reprt_code=str(reprt_code))
        basis, statement_rows = self.xbrl.basis_rows(raw_rows, fs_div_requested)
        if not basis:
            separate_rows = [row for row in raw_rows if row.get("basis") == "SeparateMember"]
            cfs_status: str | None = None
            ofs_status: str | None = None
            # Only consult the report-level API when the filing-specific XBRL
            # has no consolidated context.  Canonical values still come from
            # the selected rcept_no XBRL artifact, never from this convenience
            # endpoint.
            if self.xbrl.client is not None:
                cfs_response = self.xbrl.client.financial_statements(selected.corp_code, str(bsns_year), str(reprt_code), "CFS")
                cfs_status = cfs_response.status
                if cfs_status == "013":
                    ofs_response = self.xbrl.client.financial_statements(selected.corp_code, str(bsns_year), str(reprt_code), "OFS")
                    ofs_status = ofs_response.status
            basis_selection = select_statement_basis(cfs_status, [], ofs_status, separate_rows)
            if basis_selection.fs_div_used == "OFS":
                basis, statement_rows = "OFS", separate_rows
            else:
                basis, statement_rows = "", []
        family = classify_company_family(company or {}, statement_rows)
        company_family = family["company_family"]
        fallback_used = basis == "OFS"
        fallback_reason = "CFS_DATA_NOT_FOUND" if fallback_used else None
        metrics = FINANCIAL_METRICS if company_family == CompanyFamily.FINANCIAL.value else NON_FINANCIAL_METRICS
        duration_rows = [row for row in statement_rows if row.get("period_start")]
        period_row = duration_rows[0] if duration_rows else (statement_rows[0] if statement_rows else {})
        observations: list[FinancialObservation] = []
        for metric in metrics + tuple(item for item in NON_FINANCIAL_ONLY_METRICS if item not in metrics):
            result = resolve_core_account(statement_rows, metric, company_family)
            selected_row = None
            if result.get("resolution_status") == AccountResolutionStatus.RESOLVED.value:
                candidates = [row for row in statement_rows if row.get("account_id") == result.get("account_id")
                              and row.get("statement_family") == result.get("canonical_statement_family")]
                # The resolver has already applied the tie rule; this lookup only
                # re-attaches the complete raw row for provenance/value parsing.
                selected_row = next((row for row in candidates if row.get("thstrm_amount") == result.get("thstrm_amount")), None)
            row = selected_row or {}
            observations.append(FinancialObservation(
                ticker=ticker, corp_code=record.corp_code, company_family=company_family,
                bsns_year=str(bsns_year), reprt_code=str(reprt_code), report_type=REPORT_TYPE_BY_CODE.get(str(reprt_code), "UNKNOWN"),
                period_start=row.get("period_start") or period_row.get("period_start"),
                period_end=row.get("period_end") or period_row.get("period_end"),
                amount_type=_amount_type(row or period_row, str(reprt_code)), rcept_no=selected.rcept_no,
                rcept_dt=selected.rcept_dt, pit_as_of=str(as_of), pit_availability=resolution.availability or "AVAILABLE",
                pit_granularity=PIT_GRANULARITY, fs_div_requested=fs_div_requested, fs_div_used=basis or None,
                fallback_used=fallback_used, fallback_reason=fallback_reason, raw_sj_div=result.get("raw_sj_div"),
                statement_family=result.get("canonical_statement_family") or CORE_METRIC_SPECS.get(metric, {}).get("family", "UNKNOWN"),
                metric=metric, account_id=result.get("account_id"), account_nm=result.get("account_nm"),
                account_detail=result.get("account_detail"), value=row.get("value") if selected_row else None,
                currency=row.get("currency") if selected_row else None, source_role="FILING_SPECIFIC_RAW",
                source_sha256=artifact.sha256, resolution_status=result.get("resolution_status", "NOT_FOUND"),
                reason=result.get("reason"), raw_row=row,
            ))
        unresolved = [item.metric for item in observations if item.resolution_status not in {"RESOLVED", "NOT_APPLICABLE"}]
        return NormalizedFinancialReport(
            ticker=ticker, corp_code=record.corp_code, company_family=company_family,
            bsns_year=str(bsns_year), reprt_code=str(reprt_code), report_type=REPORT_TYPE_BY_CODE.get(str(reprt_code), "UNKNOWN"),
            period_start=period_row.get("period_start"), period_end=period_row.get("period_end"),
            rcept_no=selected.rcept_no, rcept_dt=selected.rcept_dt, pit_as_of=str(as_of),
            pit_availability=resolution.availability or "AVAILABLE", fs_div_requested=fs_div_requested,
            fs_div_used=basis or None, fallback_used=fallback_used, fallback_reason=fallback_reason,
            source_sha256=artifact.sha256, observations=tuple(observations), status="READY",
            reason=f"UNRESOLVED:{','.join(unresolved)}" if unresolved else None,
        )

    get_report = normalize
