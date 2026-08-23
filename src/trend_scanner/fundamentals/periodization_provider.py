"""Production PIT orchestration for filing-specific periodization.

The :class:`PeriodizationEngine` is intentionally network agnostic.  This
module is the production boundary that supplies it with *all* filing versions
that were available by the requested EOD, while keeping each anchor's prior
source at the anchor receipt vintage.  It never uses the latest financial
statement endpoint and never combines CFS/OFS contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .corp_code_repository import CorpCodeRepository
from .filing_registry import FilingRegistry
from .models import RegisteredFiling
from .opendart_contract import CompanyFamily, REPORT_TYPE_BY_CODE, classify_company_family
from .period_models import PeriodizationFact, PeriodizationResult
from .periodization import (
    PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD,
    PeriodizationEngine,
    facts_from_xbrl_rows,
)
from .pit_resolver import PITResolver
from .xbrl_repository import XbrlRepository


ANCHOR_REPORT_CODES = ("11013", "11012", "11014", "11011")
PRIOR_REPORT_CODE = {"11012": "11013", "11014": "11012", "11011": "11014"}


class PeriodizationProviderError(RuntimeError):
    """Raised when production periodization cannot establish its PIT inputs."""


def _as_of_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise PeriodizationProviderError(f"Invalid requested_as_of: {value!r}") from None


def _basis_value(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"CFS", "ConsolidatedMember"}:
        return "CFS"
    if text in {"OFS", "SeparateMember"}:
        return "OFS"
    return None


@dataclass(frozen=True)
class PeriodizationBuild:
    """Auditable result of one production periodization build."""

    ticker: str
    fiscal_year: str
    requested_as_of: str
    company_family: str
    filings: tuple[RegisteredFiling, ...]
    facts: tuple[PeriodizationFact, ...]
    result: PeriodizationResult
    anchor_selections: tuple[Mapping[str, Any], ...] = ()
    skipped_anchors: tuple[Mapping[str, Any], ...] = ()
    canonical_duplicate_group_count: int = 0
    canonical_duplicate_fact_removed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "fiscal_year": self.fiscal_year,
            "requested_as_of": self.requested_as_of,
            "company_family": self.company_family,
            "filings": [item.to_dict() for item in self.filings],
            "facts": [item.to_dict() for item in self.facts],
            "result": self.result.to_dict(),
            "anchor_selections": [dict(item) for item in self.anchor_selections],
            "skipped_anchors": [dict(item) for item in self.skipped_anchors],
            "canonical_duplicate_group_count": self.canonical_duplicate_group_count,
            "canonical_duplicate_fact_removed_count": self.canonical_duplicate_fact_removed_count,
        }


class PeriodizationProvider:
    """Build PIT-safe fiscal periods from the registry and filing XBRL cache."""

    def __init__(self, corp_codes: CorpCodeRepository, filings: FilingRegistry,
                 xbrl: XbrlRepository, *, periodizer: PeriodizationEngine | None = None,
                 pit_resolver: PITResolver | None = None):
        self.corp_codes = corp_codes
        self.filings = filings
        self.xbrl = xbrl
        self.periodizer = periodizer or PeriodizationEngine()
        self.pit_resolver = pit_resolver or PITResolver()

    def build(self, ticker: str, fiscal_year: str, requested_as_of: str | date, *,
              company: Mapping[str, Any] | None = None,
              company_metadata: Mapping[str, Any] | None = None,
              force_refresh: bool = False) -> PeriodizationBuild:
        cutoff = _as_of_date(requested_as_of)
        cutoff_text = cutoff.isoformat()
        ticker = str(ticker).strip()
        fiscal_year = str(fiscal_year).strip()
        if not ticker or not fiscal_year:
            raise PeriodizationProviderError("ticker and fiscal_year are required")

        record = self.corp_codes.get_record(ticker)
        metadata = company_metadata if company_metadata is not None else company
        family = self._company_family(metadata)
        all_filings: list[RegisteredFiling] = []
        facts: list[PeriodizationFact] = []
        selections: list[Mapping[str, Any]] = []
        skipped: list[Mapping[str, Any]] = []
        filings_by_code: dict[str, list[RegisteredFiling]] = {}
        prior_pit_states: dict[tuple[str, str], Mapping[str, Any]] = {}
        materialized_keys: set[tuple[str, str]] = set()
        canonical_duplicate_group_count = 0
        canonical_duplicate_fact_removed_count = 0

        def materialize(filing: RegisteredFiling) -> dict[str, Any]:
            """Materialize one filing exactly once for this provider build."""

            nonlocal canonical_duplicate_group_count, canonical_duplicate_fact_removed_count

            key = (str(filing.reprt_code), str(filing.rcept_no))
            if key in materialized_keys:
                return {
                    "materialized": True,
                    "reason": "ALREADY_MATERIALIZED",
                    "reprt_code": filing.reprt_code,
                    "rcept_no": filing.rcept_no,
                    "fact_count": 0,
                    "source_sha256": None,
                    "basis": None,
                }
            artifact = self.xbrl.fetch(filing, force_refresh=force_refresh)
            context_rows = self.xbrl.period_context_rows(
                artifact, bsns_year=fiscal_year, reprt_code=filing.reprt_code,
            )
            selected_rows, basis = self._select_one_basis(context_rows, filing.fs_div)
            if not selected_rows:
                return {
                    "materialized": False,
                    "reason": "NO_PRIMARY_CONTEXT_FOR_BASIS",
                    "reprt_code": filing.reprt_code,
                    "rcept_no": filing.rcept_no,
                    "fact_count": 0,
                    "source_sha256": artifact.sha256,
                    "basis": basis,
                }
            collapse_stats: dict[str, int] = {}
            new_facts = facts_from_xbrl_rows(
                selected_rows, ticker=ticker, corp_code=record.corp_code,
                company_family=family, fiscal_year=fiscal_year, reprt_code=filing.reprt_code,
                report_type=filing.report_type, rcept_no=filing.rcept_no,
                rcept_dt=filing.rcept_dt, fs_div_used=basis,
                source_sha256=artifact.sha256, collapse_stats=collapse_stats,
            )
            canonical_duplicate_group_count += int(collapse_stats.get("group_count", 0))
            canonical_duplicate_fact_removed_count += int(collapse_stats.get("removed_fact_count", 0))
            if not new_facts:
                return {
                    "materialized": False,
                    "reason": "NO_SUPPORTED_FACTS",
                    "reprt_code": filing.reprt_code,
                    "rcept_no": filing.rcept_no,
                    "fact_count": 0,
                    "source_sha256": artifact.sha256,
                    "basis": basis,
                }
            facts.extend(new_facts)
            all_filings.append(filing)
            materialized_keys.add(key)
            return {
                "materialized": True,
                "reason": "MATERIALIZED",
                "reprt_code": filing.reprt_code,
                "rcept_no": filing.rcept_no,
                "fact_count": len(new_facts),
                "source_sha256": artifact.sha256,
                "basis": basis,
            }

        for reprt_code in ANCHOR_REPORT_CODES:
            rows = list(self.filings.list_regular_filings(
                ticker=ticker, corp_code=record.corp_code, bsns_year=fiscal_year,
                reprt_code=reprt_code, as_of=cutoff, force_refresh=force_refresh,
            ))
            rows = [row for row in rows if row.bsns_year == fiscal_year and row.reprt_code == reprt_code]
            filings_by_code[reprt_code] = rows
            selection = self.pit_resolver.resolve(rows, as_of=cutoff, bsns_year=fiscal_year,
                                                  reprt_code=reprt_code)
            selected = selection.selected
            eligible_rcept_nos = self._eligible_rcept_nos(rows, cutoff)
            selections.append({
                "reprt_code": reprt_code,
                "report_type": REPORT_TYPE_BY_CODE.get(reprt_code, "UNKNOWN"),
                "status": selection.status,
                "selected_rcept_no": selection.selected_rcept_no,
                "selected_rcept_dt": selection.selected_rcept_dt,
                "availability": selection.availability,
                "eligible_count": selection.eligible_count,
                "future_count": selection.future_count,
                "candidate_rcept_nos": eligible_rcept_nos,
                "reason": selection.reason,
            })
            if selection.status != "READY":
                skipped.append({"reprt_code": reprt_code, "status": selection.status, "reason": selection.reason})
                continue

            # Keep every version eligible at the requested EOD.  The selected
            # row is the current snapshot; earlier rows are required to
            # reconstruct what a later anchor could have known at its receipt.
            eligible = [row for row in rows if self._receipt(row.rcept_dt) is not None
                        and self._receipt(row.rcept_dt) <= cutoff]
            for filing in sorted(eligible, key=lambda item: (item.rcept_dt, item.rcept_no)):
                materialization = materialize(filing)
                if not materialization["materialized"]:
                    skipped.append({"reprt_code": reprt_code, "rcept_no": filing.rcept_no,
                                    "status": "DATA_UNAVAILABLE", "reason": materialization["reason"]})

        # Make the anchor-specific prior resolution explicit in the production
        # audit trail.  The engine repeats the same receipt-date gate at fact
        # level, but this PITResolver result proves that the orchestration did
        # not rely on a latest-snapshot shortcut.
        for selection_meta in selections:
            code = str(selection_meta["reprt_code"])
            anchor_dt = selection_meta.get("selected_rcept_dt")
            prior_code = PRIOR_REPORT_CODE.get(code)
            if not anchor_dt or not prior_code:
                continue
            prior = self.pit_resolver.resolve(
                filings_by_code.get(prior_code, ()), as_of=str(anchor_dt)[:10],
                bsns_year=fiscal_year, reprt_code=prior_code,
            )
            prior_rows = filings_by_code.get(prior_code, ())
            prior_candidate_rcept_nos = self._eligible_rcept_nos(
                prior_rows, self._receipt(anchor_dt)
            )
            prior_reason = self._canonical_prior_reason(prior.status, prior.reason)
            historical_materialization = {
                "materialized": False,
                "reason": "PRIOR_NOT_READY",
                "reprt_code": prior_code,
                "rcept_no": prior.selected_rcept_no,
                "fact_count": 0,
                "source_sha256": None,
                "basis": None,
            }
            if prior.status == "READY" and prior.selected is not None:
                historical_materialization = materialize(prior.selected)
            selection_meta["prior_pit"] = {
                "reprt_code": prior_code,
                "status": prior.status,
                "selected_rcept_no": prior.selected_rcept_no,
                "selected_rcept_dt": prior.selected_rcept_dt,
                "availability": prior.availability,
                "reason": prior_reason,
                "raw_reason": prior.reason,
                "canonical_reason": prior_reason,
                "candidate_rcept_nos": prior_candidate_rcept_nos,
                "historical_source_materialized": bool(historical_materialization["materialized"]),
                "historical_source_materialization_reason": historical_materialization["reason"],
                "historical_source_fact_count": historical_materialization["fact_count"],
                "historical_source_sha256": historical_materialization["source_sha256"],
            }
            anchor_no = selection_meta.get("selected_rcept_no")
            if anchor_no:
                prior_pit_states[(code, str(anchor_no))] = {
                    "status": prior.status,
                    "reason": prior_reason,
                }

        current_pit_states = {
            str(item["reprt_code"]): {"status": item.get("status"), "reason": item.get("reason")}
            for item in selections
        }
        result = self.periodizer.periodize(
            facts, as_of=cutoff, prior_pit_states=prior_pit_states,
            current_pit_states=current_pit_states,
        )
        return PeriodizationBuild(
            ticker=ticker, fiscal_year=fiscal_year, requested_as_of=cutoff_text,
            company_family=family, filings=tuple(all_filings), facts=tuple(facts),
            result=result, anchor_selections=tuple(selections), skipped_anchors=tuple(skipped),
            canonical_duplicate_group_count=canonical_duplicate_group_count,
            canonical_duplicate_fact_removed_count=canonical_duplicate_fact_removed_count,
        )

    def periodize(self, ticker: str, fiscal_year: str, requested_as_of: str | date, **kwargs: Any) -> PeriodizationResult:
        """Convenience wrapper returning the canonical result only."""

        return self.build(ticker, fiscal_year, requested_as_of, **kwargs).result

    @staticmethod
    def _receipt(value: Any) -> date | None:
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    @classmethod
    def _eligible_rcept_nos(cls, rows: Iterable[RegisteredFiling], cutoff: date | None) -> list[str]:
        if cutoff is None:
            return []
        return sorted({row.rcept_no for row in rows
                       if cls._receipt(row.rcept_dt) is not None and cls._receipt(row.rcept_dt) <= cutoff})

    @staticmethod
    def _canonical_prior_reason(status: str, reason: str | None) -> str | None:
        if status == "AMBIGUOUS" and reason == "MULTIPLE_FILINGS_ON_SAME_DATE":
            return PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
        if status in {"DATA_UNAVAILABLE", "FUTURE_FORBIDDEN"}:
            return "PRIOR_PIT_MISSING"
        return reason

    @staticmethod
    def _company_family(company: Mapping[str, Any] | None) -> str:
        explicit = str((company or {}).get("company_family") or "").strip()
        if explicit in {item.value for item in CompanyFamily}:
            return explicit
        classification = classify_company_family(company or {}, ())
        return str(classification.get("company_family") or CompanyFamily.UNKNOWN.value)

    @staticmethod
    def _select_one_basis(rows: Iterable[Mapping[str, Any]], requested: str | None) -> tuple[list[dict[str, Any]], str | None]:
        values = [dict(row) for row in rows]
        wanted = _basis_value(requested)
        if wanted is None:
            wanted = "CFS" if any(_basis_value(row.get("basis")) == "CFS" for row in values) else "OFS"
        selected = [row for row in values if _basis_value(row.get("basis")) == wanted]
        return selected, wanted if selected else None
