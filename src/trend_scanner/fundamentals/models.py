"""Data models for the OpenDART fundamentals core.

The models intentionally keep raw filing identity and normalized values in the
same provenance graph.  They do not contain derived metrics or investment
signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class CorpCodeRecord:
    corp_code: str
    corp_name: str
    stock_code: str
    modify_date: str

    def to_dict(self) -> dict[str, str]:
        return {
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "stock_code": self.stock_code,
            "modify_date": self.modify_date,
        }


@dataclass(frozen=True)
class RegisteredFiling:
    ticker: str
    corp_code: str
    corp_name: str
    bsns_year: str
    reprt_code: str
    report_type: str
    report_nm: str
    rcept_no: str
    rcept_dt: str
    filing_chain_key: str
    correction_flag: bool
    source_retrieved_at: str
    fs_div: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "bsns_year": self.bsns_year,
            "reprt_code": self.reprt_code,
            "report_type": self.report_type,
            "report_nm": self.report_nm,
            "rcept_no": self.rcept_no,
            "rcept_dt": self.rcept_dt,
            "filing_chain_key": self.filing_chain_key,
            "correction_flag": self.correction_flag,
            "source_retrieved_at": self.source_retrieved_at,
            "fs_div": self.fs_div,
        }


@dataclass(frozen=True)
class RawXbrlArtifact:
    corp_code: str
    ticker: str
    rcept_no: str
    reprt_code: str
    rcept_dt: str
    retrieved_at: str
    http_status: int
    content_type: str | None
    byte_length: int
    sha256: str
    member_count: int
    member_names: tuple[str, ...]
    source_url_redacted: str
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "corp_code": self.corp_code,
            "ticker": self.ticker,
            "rcept_no": self.rcept_no,
            "reprt_code": self.reprt_code,
            "rcept_dt": self.rcept_dt,
            "retrieved_at": self.retrieved_at,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "member_count": self.member_count,
            "member_names": list(self.member_names),
            "source_url_redacted": self.source_url_redacted,
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True)
class FinancialObservation:
    ticker: str
    corp_code: str
    company_family: str
    bsns_year: str
    reprt_code: str
    report_type: str
    period_start: str | None
    period_end: str | None
    amount_type: str
    rcept_no: str
    rcept_dt: str
    pit_as_of: str
    pit_availability: str
    pit_granularity: str
    fs_div_requested: str
    fs_div_used: str | None
    fallback_used: bool
    fallback_reason: str | None
    raw_sj_div: str | None
    statement_family: str
    metric: str
    account_id: str | None
    account_nm: str | None
    account_detail: str | None
    value: int | None
    currency: str | None
    source_role: str
    source_sha256: str | None
    resolution_status: str
    reason: str | None = None
    raw_row: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "company_family": self.company_family,
            "bsns_year": self.bsns_year,
            "reprt_code": self.reprt_code,
            "report_type": self.report_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "amount_type": self.amount_type,
            "rcept_no": self.rcept_no,
            "rcept_dt": self.rcept_dt,
            "pit_as_of": self.pit_as_of,
            "pit_availability": self.pit_availability,
            "pit_granularity": self.pit_granularity,
            "fs_div_requested": self.fs_div_requested,
            "fs_div_used": self.fs_div_used,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "raw_sj_div": self.raw_sj_div,
            "statement_family": self.statement_family,
            "metric": self.metric,
            "account_id": self.account_id,
            "account_nm": self.account_nm,
            "account_detail": self.account_detail,
            "value": self.value,
            "currency": self.currency,
            "source_role": self.source_role,
            "source_sha256": self.source_sha256,
            "resolution_status": self.resolution_status,
            "reason": self.reason,
        }
        result["raw_row"] = dict(self.raw_row)
        return result


@dataclass(frozen=True)
class NormalizedFinancialReport:
    ticker: str
    corp_code: str
    company_family: str
    bsns_year: str
    reprt_code: str
    report_type: str
    period_start: str | None
    period_end: str | None
    rcept_no: str
    rcept_dt: str
    pit_as_of: str
    pit_availability: str
    fs_div_requested: str
    fs_div_used: str | None
    fallback_used: bool
    fallback_reason: str | None
    source_sha256: str | None
    observations: tuple[FinancialObservation, ...]
    status: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "company_family": self.company_family,
            "bsns_year": self.bsns_year,
            "reprt_code": self.reprt_code,
            "report_type": self.report_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "rcept_no": self.rcept_no,
            "rcept_dt": self.rcept_dt,
            "pit_as_of": self.pit_as_of,
            "pit_availability": self.pit_availability,
            "fs_div_requested": self.fs_div_requested,
            "fs_div_used": self.fs_div_used,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "source_sha256": self.source_sha256,
            "status": self.status,
            "reason": self.reason,
            "observations": [item.to_dict() for item in self.observations],
        }
