"""OpenDART Fundamentals V01 architecture contracts.

The module is deliberately network-independent.  It defines the PIT filing
selection, statement-basis, statement-family, company-family, and canonical
account-resolution rules that a later provider implementation may consume.
No score, valuation, ranking, or Stock Report integration belongs here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PIT_GRANULARITY = "DAILY_EOD_KST"
SAME_DAY_AVAILABILITY = "AVAILABLE_AT_EOD"
REPORT_TYPE_BY_CODE = {
    "11013": "Q1",
    "11012": "HALF_YEAR",
    "11014": "Q3",
    "11011": "ANNUAL",
}


class StatementFamily(str, Enum):
    BALANCE_SHEET = "BALANCE_SHEET"
    INCOME_STATEMENT = "INCOME_STATEMENT"
    CASH_FLOW = "CASH_FLOW"
    EQUITY_CHANGES = "EQUITY_CHANGES"
    UNKNOWN = "UNKNOWN"


class CompanyFamily(str, Enum):
    NON_FINANCIAL = "NON_FINANCIAL"
    FINANCIAL = "FINANCIAL"
    UNKNOWN = "UNKNOWN"


class FilingSelectionStatus(str, Enum):
    READY = "READY"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"
    FUTURE_FORBIDDEN = "FUTURE_FORBIDDEN"


class AccountResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_CORRECTION_MARKERS = re.compile(
    r"\[(?:기재정정|첨부정정|첨부추가|정정|자진공시)\]|\((?:기재정정|첨부정정|첨부추가|정정)\)"
)
_WHITESPACE = re.compile(r"\s+")


def redact_url(url: str) -> str:
    """Return a request URL safe for logs and committed artifacts."""

    parts = urlsplit(url)
    query = [
        (key, "<REDACTED>" if key == "crtfc_key" else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _normalise_report_name(value: Any) -> str:
    text = _CORRECTION_MARKERS.sub("", str(value or ""))
    return _WHITESPACE.sub("", text).strip()


@dataclass(frozen=True)
class FilingRecord:
    """Minimal filing registry row needed for PIT selection."""

    ticker: str
    corp_code: str
    bsns_year: str
    reprt_code: str
    report_nm: str
    rcept_no: str
    rcept_dt: str
    fs_div: str | None = None
    filing_chain_key: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "FilingRecord":
        return cls(
            ticker=str(row.get("ticker") or row.get("stock_code") or ""),
            corp_code=str(row.get("corp_code") or ""),
            bsns_year=str(row.get("bsns_year") or row.get("fiscal_year") or ""),
            reprt_code=str(row.get("reprt_code") or ""),
            report_nm=str(row.get("report_nm") or ""),
            rcept_no=str(row.get("rcept_no") or ""),
            rcept_dt=str(row.get("rcept_dt") or ""),
            fs_div=str(row.get("fs_div")) if row.get("fs_div") is not None else None,
            filing_chain_key=(
                str(row.get("filing_chain_key") or row.get("chain_key"))
                if (row.get("filing_chain_key") or row.get("chain_key"))
                else None
            ),
        )

    @property
    def parsed_date(self) -> date | None:
        return _parse_date(self.rcept_dt)

    @property
    def report_type(self) -> str | None:
        return REPORT_TYPE_BY_CODE.get(self.reprt_code)

    @property
    def derived_chain_key(self) -> str | None:
        if self.filing_chain_key:
            return self.filing_chain_key
        name = _normalise_report_name(self.report_nm)
        if not name:
            return None
        return f"{self.bsns_year}:{self.reprt_code}:{name}"


@dataclass(frozen=True)
class FilingSelection:
    status: str
    selected: FilingRecord | None
    eligible: tuple[FilingRecord, ...]
    future: tuple[FilingRecord, ...]
    availability: str | None
    reason: str


def select_pit_filing(
    filings: Iterable[FilingRecord | Mapping[str, Any]],
    as_of: str | date,
    bsns_year: str,
    reprt_code: str,
) -> FilingSelection:
    """Select the latest unambiguous filing available by DAILY_EOD_KST.

    A filing chain key is required to distinguish original and correction
    submissions.  If list data cannot provide a key, a conservative normalized
    report name is used; missing identity or multiple independent chains fail
    closed as ``AMBIGUOUS`` rather than selecting the first row.
    """

    cutoff = _parse_date(as_of)
    if cutoff is None:
        return FilingSelection(
            status=FilingSelectionStatus.DATA_UNAVAILABLE.value,
            selected=None,
            eligible=(),
            future=(),
            availability=None,
            reason="INVALID_AS_OF",
        )

    records = [item if isinstance(item, FilingRecord) else FilingRecord.from_mapping(item) for item in filings]
    matching = [
        item for item in records
        if item.bsns_year == str(bsns_year) and item.reprt_code == str(reprt_code)
    ]
    parsed = [(item, item.parsed_date) for item in matching]
    eligible = tuple(item for item, filed_on in parsed if filed_on is not None and filed_on <= cutoff)
    future = tuple(item for item, filed_on in parsed if filed_on is not None and filed_on > cutoff)
    if not eligible:
        status = FilingSelectionStatus.FUTURE_FORBIDDEN.value if future else FilingSelectionStatus.DATA_UNAVAILABLE.value
        return FilingSelection(
            status=status,
            selected=None,
            eligible=(),
            future=future,
            availability=None,
            reason="NO_ELIGIBLE_FILING" if future else "NO_MATCHING_FILING",
        )

    groups: dict[str, list[FilingRecord]] = defaultdict(list)
    for item in eligible:
        if item.derived_chain_key is None:
            return FilingSelection(
                status=FilingSelectionStatus.AMBIGUOUS.value,
                selected=None,
                eligible=eligible,
                future=future,
                availability=None,
                reason="FILING_CHAIN_IDENTITY_UNKNOWN",
            )
        groups[item.derived_chain_key].append(item)
    if len(groups) != 1:
        return FilingSelection(
            status=FilingSelectionStatus.AMBIGUOUS.value,
            selected=None,
            eligible=eligible,
            future=future,
            availability=None,
            reason="MULTIPLE_FILING_CHAINS",
        )

    chain = next(iter(groups.values()))
    max_date = max(item.parsed_date for item in chain if item.parsed_date is not None)
    same_day = [item for item in chain if item.parsed_date == max_date]
    if len({item.rcept_no for item in same_day}) != 1:
        return FilingSelection(
            status=FilingSelectionStatus.AMBIGUOUS.value,
            selected=None,
            eligible=eligible,
            future=future,
            availability=None,
            reason="MULTIPLE_FILINGS_ON_SAME_DATE",
        )

    selected = max(chain, key=lambda item: (item.parsed_date or date.min, item.rcept_no))
    availability = SAME_DAY_AVAILABILITY if selected.parsed_date == cutoff else "AVAILABLE"
    return FilingSelection(
        status=FilingSelectionStatus.READY.value,
        selected=selected,
        eligible=eligible,
        future=future,
        availability=availability,
        reason="LATEST_ELIGIBLE_FILING",
    )


RAW_TO_STATEMENT_FAMILY: dict[str, StatementFamily] = {
    "BS": StatementFamily.BALANCE_SHEET,
    "IS": StatementFamily.INCOME_STATEMENT,
    "CIS": StatementFamily.INCOME_STATEMENT,
    "CF": StatementFamily.CASH_FLOW,
    "SCE": StatementFamily.EQUITY_CHANGES,
}


def map_statement_family(raw_sj_div: Any) -> str:
    """Map raw OpenDART ``sj_div`` while preserving the raw value upstream."""

    raw = str(raw_sj_div or "").strip().upper()
    return RAW_TO_STATEMENT_FAMILY.get(raw, StatementFamily.UNKNOWN).value


def classify_company_family(
    company: Mapping[str, Any] | None,
    financial_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return evidence-based initial family classification, not a full sector engine."""

    company = company or {}
    fields = company.get("selected_fields") if isinstance(company.get("selected_fields"), Mapping) else company
    industry_code = str((fields or {}).get("induty_code") or "").strip()
    evidence: list[str] = []
    if industry_code.startswith("64"):
        evidence.append(f"induty_code:{industry_code}")
        return {"company_family": CompanyFamily.FINANCIAL.value, "evidence": evidence, "status": "FIXTURE_CONFIDENT"}
    if industry_code:
        evidence.append(f"induty_code:{industry_code}")
        return {"company_family": CompanyFamily.NON_FINANCIAL.value, "evidence": evidence, "status": "FIXTURE_CONFIDENT"}

    names = " ".join(str(row.get("account_nm") or "") for row in financial_rows)
    if any(term in names for term in ("순영업이익", "순이자이익", "대손비용")):
        evidence.append("financial_account_structure")
        return {"company_family": CompanyFamily.FINANCIAL.value, "evidence": evidence, "status": "STRUCTURE_DIAGNOSTIC"}
    return {"company_family": CompanyFamily.UNKNOWN.value, "evidence": evidence, "status": "INSUFFICIENT_EVIDENCE"}


@dataclass(frozen=True)
class BasisSelection:
    status: str
    fs_div_used: str | None
    fallback_used: bool
    fallback_reason: str | None
    row_count: int
    reason: str


def _usable_rows(status: str | None, rows: Sequence[Mapping[str, Any]]) -> bool:
    return str(status or "") == "000" and bool(rows)


def select_statement_basis(
    cfs_status: str | None,
    cfs_rows: Sequence[Mapping[str, Any]],
    ofs_status: str | None = None,
    ofs_rows: Sequence[Mapping[str, Any]] = (),
) -> BasisSelection:
    """Select one report-level basis; never mix CFS and OFS account rows."""

    if _usable_rows(cfs_status, cfs_rows):
        return BasisSelection("READY", "CFS", False, None, len(cfs_rows), "CFS_PREFERRED")
    if str(cfs_status or "") == "013":
        if _usable_rows(ofs_status, ofs_rows):
            return BasisSelection("READY", "OFS", True, "CFS_DATA_NOT_FOUND", len(ofs_rows), "OFS_FALLBACK")
        return BasisSelection("DATA_UNAVAILABLE", None, False, "CFS_DATA_NOT_FOUND", 0, "NO_USABLE_CFS_OR_OFS")
    if str(cfs_status or "") in {"", "000"}:
        return BasisSelection("DATA_UNAVAILABLE", None, False, "CFS_EMPTY_OR_UNPARSEABLE", 0, "CFS_NOT_USABLE")
    return BasisSelection("DATA_UNAVAILABLE", None, False, f"CFS_API_ERROR_{cfs_status}", 0, "CFS_ERROR_NO_SILENT_OFS_FALLBACK")


CORE_METRIC_SPECS: dict[str, dict[str, Any]] = {
    "assets": {"family": StatementFamily.BALANCE_SHEET.value, "ids": ("ifrs-full_Assets",), "aliases": ("자산총계",)},
    "liabilities": {"family": StatementFamily.BALANCE_SHEET.value, "ids": ("ifrs-full_Liabilities",), "aliases": ("부채총계",)},
    "equity": {"family": StatementFamily.BALANCE_SHEET.value, "ids": ("ifrs-full_Equity",), "aliases": ("자본총계",)},
    "revenue": {"family": StatementFamily.INCOME_STATEMENT.value, "ids": ("ifrs-full_Revenue",), "aliases": ("매출액", "매출")},
    "operating_income": {"family": StatementFamily.INCOME_STATEMENT.value, "ids": ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"), "aliases": ("영업이익",)},
    "net_income": {"family": StatementFamily.INCOME_STATEMENT.value, "ids": ("ifrs-full_ProfitLoss",), "aliases": ("당기순이익", "연결당기순이익")},
    "operating_cash_flow": {"family": StatementFamily.CASH_FLOW.value, "ids": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",), "aliases": ("영업활동현금흐름", "영업활동으로 인한 현금흐름")},
}
NON_FINANCIAL_ONLY_METRICS = frozenset({"revenue", "operating_income"})


def _row_statement_family(row: Mapping[str, Any]) -> str:
    return str(row.get("statement_family") or map_statement_family(row.get("sj_div")))


def _rank_account_candidate(row: Mapping[str, Any], spec: Mapping[str, Any]) -> tuple[int, int, int, str]:
    account_id = str(row.get("account_id") or "")
    raw_sj_div = str(row.get("sj_div") or "").upper()
    id_rank = 0 if account_id in spec["ids"] else 1
    # Prefer IS over CIS when both are valid income-family contexts.  CIS is
    # still a first-class fallback for companies such as ST Pharm.
    raw_rank = 0 if raw_sj_div == "IS" else (1 if raw_sj_div == "CIS" else 2)
    detail_rank = 0 if not str(row.get("account_detail") or "").strip() else 1
    ord_value = str(row.get("ord") or "")
    return id_rank, raw_rank, detail_rank, ord_value


def resolve_core_account(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    company_family: str,
) -> dict[str, Any]:
    """Resolve one metric using statement context and an explicit tie rule."""

    spec = CORE_METRIC_SPECS.get(metric)
    if spec is None:
        return {"metric": metric, "resolution_status": AccountResolutionStatus.NOT_FOUND.value, "match_count": 0}
    if company_family == CompanyFamily.FINANCIAL.value and metric in NON_FINANCIAL_ONLY_METRICS:
        return {
            "metric": metric,
            "company_family": company_family,
            "resolution_status": AccountResolutionStatus.NOT_APPLICABLE.value,
            "match_count": 0,
            "reason": "NON_FINANCIAL_ONLY_METRIC",
        }

    candidates: list[Mapping[str, Any]] = []
    for row in rows:
        if _row_statement_family(row) != spec["family"]:
            continue
        account_id = str(row.get("account_id") or "")
        account_nm = str(row.get("account_nm") or "").strip()
        if account_id in spec["ids"] or (not account_id and account_nm in spec["aliases"]):
            candidates.append(row)
    if not candidates:
        return {
            "metric": metric,
            "company_family": company_family,
            "canonical_statement_family": spec["family"],
            "resolution_status": AccountResolutionStatus.NOT_FOUND.value,
            "match_count": 0,
        }

    ranked = sorted(candidates, key=lambda row: _rank_account_candidate(row, spec))
    best_rank = _rank_account_candidate(ranked[0], spec)
    best = [row for row in ranked if _rank_account_candidate(row, spec) == best_rank]
    result: dict[str, Any] = {
        "metric": metric,
        "company_family": company_family,
        "candidate_account_id": str(ranked[0].get("account_id") or "") or None,
        "account_nm": ranked[0].get("account_nm"),
        "raw_sj_div": ranked[0].get("sj_div"),
        "canonical_statement_family": spec["family"],
        "match_count": len(candidates),
    }
    if len(best) != 1:
        result["resolution_status"] = AccountResolutionStatus.AMBIGUOUS.value
        result["reason"] = "TIED_CANDIDATES_REQUIRE_PERIOD_OR_CONTEXT_RULE"
        return result
    selected = best[0]
    result.update({
        "resolution_status": AccountResolutionStatus.RESOLVED.value,
        "account_id": selected.get("account_id"),
        "account_detail": selected.get("account_detail"),
        "ord": selected.get("ord"),
        "thstrm_amount": selected.get("thstrm_amount"),
    })
    return result
