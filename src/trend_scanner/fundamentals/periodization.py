"""PIT-safe fiscal periodization for filing-specific Fundamentals facts.

This module creates period semantics only.  It deliberately does not calculate
growth, margins, TTM, scores, or valuation measures.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from dataclasses import replace
from typing import Any, Iterable, Mapping

from .models import FinancialObservation
from .opendart_contract import CompanyFamily, PIT_GRANULARITY, REPORT_TYPE_BY_CODE
from .period_models import (
    BASIS_MISMATCH,
    CUMULATIVE_YTD,
    DATA_UNAVAILABLE,
    DERIVATION_UNAVAILABLE,
    DIRECT_DERIVED_MISMATCH,
    DirectDerivedParity,
    FULL_YEAR,
    INSTANT,
    PERIOD_AMBIGUOUS,
    PERIODIZATION_UNSUPPORTED,
    PeriodizationFact,
    PeriodizationResult,
    PeriodizedFinancialObservation,
    PriorCumulativeSelection,
    READY,
    STANDALONE_QUARTER,
    as_facts,
)


class PeriodizationError(RuntimeError):
    pass


FLOW_METRICS = frozenset({"revenue", "operating_income", "net_income", "operating_cash_flow"})
INSTANT_METRICS = frozenset({"assets", "liabilities", "equity"})
FINANCIAL_NON_APPLICABLE = frozenset({"revenue", "operating_income"})
ACCOUNT_TO_METRIC = {
    "ifrs-full_Assets": "assets",
    "ifrs-full_Liabilities": "liabilities",
    "ifrs-full_Equity": "equity",
    "ifrs-full_Revenue": "revenue",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "operating_cash_flow",
}

REPORT_PERIODS = {
    "11013": ("Q1", "Q1_YTD", "Q1_END", "Q1"),
    "11012": ("Q2", "H1_YTD", "H1_END", "H1"),
    "11014": ("Q3", "9M_YTD", "Q3_END", "9M"),
    "11011": ("Q4", "FY", "FY_END", "FY"),
}
REPORT_CODE_ORDER = ("11013", "11012", "11014", "11011")
PRIOR_CUMULATIVE_CODE = {"11012": "11013", "11014": "11012", "11011": "11014"}
PRIOR_READY = "READY"
PRIOR_MISSING = "MISSING"
PRIOR_AMBIGUOUS = "AMBIGUOUS"
PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD = "PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD"


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else (str(value) if value not in (None, "") else None)


def _number(value: Any) -> int | float | None:
    if value in (None, "", "-", "—", "–"):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def _difference(later: Any, earlier: Any) -> int | float | None:
    left, right = _number(later), _number(earlier)
    if left is None or right is None:
        return None
    return left - right


def _valid_source(fact: PeriodizationFact) -> bool:
    return fact.resolution_status in {"RESOLVED", "READY"} and _number(fact.value) is not None


def _is_comparative(fact: PeriodizationFact) -> bool:
    text = " ".join(str(item or "").upper() for item in (fact.context_semantics, fact.period_semantics))
    return fact.comparative or "COMPARATIVE" in text or "PRIOR" in text


def _semantic(fact: PeriodizationFact) -> str:
    explicit = str(fact.period_semantics or fact.context_semantics or "").upper()
    if explicit in {INSTANT, "INSTANT_CONTEXT"}:
        return INSTANT
    if explicit in {CUMULATIVE_YTD, "CUMULATIVE", "FISCAL_YTD", "YTD", FULL_YEAR}:
        return CUMULATIVE_YTD
    if explicit in {STANDALONE_QUARTER, "CURRENT_QUARTER", "DIRECT_STANDALONE", "STANDALONE"}:
        return STANDALONE_QUARTER
    if fact.instant and not fact.period_start:
        return INSTANT
    if fact.period_start and fact.fiscal_year_start and fact.period_start == fact.fiscal_year_start:
        return CUMULATIVE_YTD
    return "UNKNOWN"


def _duration_days(fact: PeriodizationFact) -> int | None:
    if fact.duration_days is not None:
        try:
            return int(fact.duration_days)
        except (TypeError, ValueError):
            return None
    start, end = _parse_date(fact.period_start), _parse_date(fact.period_end)
    return (end - start).days + 1 if start and end and end >= start else None


def _standard_duration(code: str, days: int | None, semantic: str) -> bool:
    if days is None or semantic == INSTANT:
        return True
    # Broad bounds allow leap years and 52/53-week calendars while rejecting
    # a stub 4-month/5-month period being silently quarterized.
    if semantic == STANDALONE_QUARTER:
        return 60 <= days <= 110
    bounds = {"11013": (70, 110), "11012": (140, 210), "11014": (220, 300), "11011": (330, 400)}
    low, high = bounds.get(code, (1, 400))
    return low <= days <= high


def _fiscal_year_start(facts: Iterable[PeriodizationFact]) -> str | None:
    explicit = sorted({str(item.fiscal_year_start) for item in facts if item.fiscal_year_start})
    if len(explicit) == 1:
        return explicit[0]
    if len(explicit) > 1:
        return None
    starts = sorted(str(item.period_start) for item in facts if item.period_start and _semantic(item) == CUMULATIVE_YTD)
    return starts[0] if starts else None


def _identity(fact: PeriodizationFact) -> tuple[str, str, str, str, str]:
    return (fact.ticker, fact.corp_code, fact.company_family, fact.fiscal_year, fact.metric)


def _coherence(anchor: PeriodizationFact, prior: PeriodizationFact | None, fiscal_start: str | None) -> tuple[bool, str | None]:
    if prior is None:
        return False, "MISSING_PRIOR_CUMULATIVE"
    if _identity(anchor) != _identity(prior):
        return False, "IDENTITY_MISMATCH"
    if anchor.fs_div_used != prior.fs_div_used:
        return False, BASIS_MISMATCH
    if (anchor.currency or "") != (prior.currency or ""):
        return False, "CURRENCY_MISMATCH"
    anchor_start = anchor.fiscal_year_start or (anchor.period_start if _semantic(anchor) == CUMULATIVE_YTD else None)
    prior_start = prior.fiscal_year_start or (prior.period_start if _semantic(prior) == CUMULATIVE_YTD else None)
    if not fiscal_start or not anchor_start or not prior_start:
        return False, "FISCAL_START_UNRESOLVED"
    if anchor_start != fiscal_start or prior_start != fiscal_start:
        return False, "FISCAL_START_MISMATCH"
    anchor_end, prior_end = _parse_date(anchor.period_end), _parse_date(prior.period_end)
    if anchor_end and prior_end and prior_end >= anchor_end:
        return False, "NON_CHRONOLOGICAL_PERIODS"
    if not _valid_source(anchor) or not _valid_source(prior):
        return False, "SOURCE_NOT_RESOLVED"
    return True, None


class PeriodizationEngine:
    """Build canonical fiscal-period observations from PIT-safe context facts."""

    def __init__(self, *, pit_granularity: str = PIT_GRANULARITY):
        self.pit_granularity = pit_granularity

    def periodize(
        self,
        values: Iterable[PeriodizationFact | FinancialObservation | Mapping[str, Any]],
        *,
        as_of: str | date | None = None,
    ) -> PeriodizationResult:
        facts = self._prepare(values, as_of=as_of)
        observations: list[PeriodizedFinancialObservation] = []
        parity: list[DirectDerivedParity] = []
        diagnostics: list[Mapping[str, Any]] = []
        groups: dict[tuple[str, str, str, str, str], list[PeriodizationFact]] = defaultdict(list)
        for fact in facts:
            groups[_identity(fact)].append(fact)

        for identity, group in sorted(groups.items()):
            observations_for_group, parity_for_group, diagnostic_for_group = self._periodize_group(group)
            observations.extend(observations_for_group)
            parity.extend(parity_for_group)
            diagnostics.extend(diagnostic_for_group)
        diagnostics.extend(self._annual_sum_diagnostics(observations))
        observations.sort(key=lambda item: (item.ticker, item.fiscal_year, item.metric, item.anchor_rcept_dt,
                                            item.fiscal_period, item.period_semantics, item.anchor_rcept_no))
        return PeriodizationResult(tuple(observations), tuple(parity), tuple(diagnostics))

    @staticmethod
    def _annual_sum_diagnostics(observations: list[PeriodizedFinancialObservation]) -> list[Mapping[str, Any]]:
        """Compare an annual direct value with a single, PIT-aligned quarter vintage.

        This is deliberately diagnostic only: the annual filing remains the
        authority for FY.  A previous implementation used a dict keyed only by
        fiscal period, which could silently combine a late correction with an
        older annual filing.  Each annual anchor now receives its own
        diagnostic version, and a future correction is ineligible by receipt
        date.
        """
        groups: dict[tuple[str, str, str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
        for item in observations:
            groups[(item.ticker, item.fiscal_year, item.metric, item.company_family)].append(item)
        diagnostics: list[Mapping[str, Any]] = []
        for (ticker, fiscal_year, metric, family), items in groups.items():
            annuals = [item for item in items if item.fiscal_period == "FY" and item.resolution_status == READY]
            for annual in sorted(annuals, key=lambda item: (_parse_date(item.anchor_rcept_dt) or date.min,
                                                              item.anchor_rcept_no)):
                annual_dt = _parse_date(annual.anchor_rcept_dt)
                selected: dict[str, PeriodizedFinancialObservation] = {}
                ambiguous: list[str] = []
                unavailable: list[str] = []
                for period in ("Q1", "Q2", "Q3"):
                    candidates = [item for item in items
                                  if item.fiscal_period == period and item.resolution_status == READY
                                  and annual_dt is not None
                                  and _parse_date(item.anchor_rcept_dt) is not None
                                  and _parse_date(item.anchor_rcept_dt) <= annual_dt]
                    if not candidates:
                        unavailable.append(period)
                        continue
                    latest_dt = max(_parse_date(item.anchor_rcept_dt) or date.min for item in candidates)
                    latest = [item for item in candidates if (_parse_date(item.anchor_rcept_dt) or date.min) == latest_dt]
                    # More than one distinct filing at the same EOD is not a
                    # deterministic vintage; do not overwrite one in a dict.
                    by_anchor = {item.anchor_rcept_no: item for item in latest}
                    if len(by_anchor) != 1:
                        ambiguous.append(period)
                        continue
                    selected[period] = next(iter(by_anchor.values()))

                # Q4 is produced by the annual anchor itself.  Requiring the
                # same rcept_no prevents a later annual correction from being
                # paired with an earlier FY diagnostic version.
                q4 = [item for item in items if item.fiscal_period == "Q4" and item.resolution_status == READY
                      and item.anchor_reprt_code == "11011" and item.anchor_rcept_no == annual.anchor_rcept_no]
                if len(q4) == 1:
                    selected["Q4"] = q4[0]
                elif len(q4) > 1:
                    ambiguous.append("Q4")
                else:
                    unavailable.append("Q4")

                base = {
                    "metric": metric, "ticker": ticker, "fiscal_year": fiscal_year,
                    "company_family": family, "annual_anchor_rcept_no": annual.anchor_rcept_no,
                    "annual_anchor_rcept_dt": annual.anchor_rcept_dt,
                    "quarter_anchor_rcept_nos": {key: value.anchor_rcept_no for key, value in selected.items()},
                }
                if ambiguous:
                    diagnostics.append({**base, "status": PERIOD_AMBIGUOUS, "reason": "MULTIPLE_VINTAGES_AT_SAME_EOD",
                                        "ambiguous_periods": ambiguous})
                    continue
                if unavailable or len(selected) != 4:
                    diagnostics.append({**base, "status": "DIAGNOSTIC_UNAVAILABLE",
                                        "reason": "MISSING_PIT_ALIGNED_QUARTER", "unavailable_periods": unavailable})
                    continue
                values = [_number(selected[key].value) for key in ("Q1", "Q2", "Q3", "Q4")]
                if any(value is None for value in values) or _number(annual.value) is None:
                    diagnostics.append({**base, "status": "DIAGNOSTIC_UNAVAILABLE", "reason": "VALUE_MISSING"})
                    continue
                quarter_sum = sum(values)
                difference = quarter_sum - _number(annual.value)
                diagnostics.append({
                    **base, "quarter_sum": quarter_sum, "annual_value": _number(annual.value),
                    "difference": difference, "status": "MATCH" if difference == 0 else "MISMATCH",
                })
        return diagnostics

    def canonical_series(self, values: Iterable[PeriodizationFact | FinancialObservation | Mapping[str, Any]],
                         *, as_of: str | date | None = None) -> PeriodizationResult:
        return self.periodize(values, as_of=as_of)

    def _prepare(self, values: Iterable[PeriodizationFact | FinancialObservation | Mapping[str, Any]],
                 *, as_of: str | date | None) -> tuple[PeriodizationFact, ...]:
        cutoff = _parse_date(as_of)
        if as_of is not None and cutoff is None:
            raise PeriodizationError(f"Invalid periodization as_of: {as_of!r}")
        prepared: list[PeriodizationFact] = []
        for raw in values:
            if isinstance(raw, PeriodizationFact):
                fact = raw
            elif isinstance(raw, FinancialObservation):
                data = raw.to_dict()
                data["fiscal_year"] = raw.bsns_year
                data["period_semantics"] = CUMULATIVE_YTD if raw.amount_type == "CUMULATIVE" else None
                data["pit_available_from"] = raw.rcept_dt
                fact = PeriodizationFact.from_mapping(data)
            else:
                fact = PeriodizationFact.from_mapping(raw)
            if _is_comparative(fact):
                continue
            receipt = _parse_date(fact.rcept_dt)
            if cutoff and receipt and receipt > cutoff:
                continue
            if not fact.fiscal_year:
                raise PeriodizationError(f"fiscal_year is required for {fact.rcept_no}")
            if fact.metric not in FLOW_METRICS and fact.metric not in INSTANT_METRICS:
                continue
            prepared.append(fact)
        return tuple(prepared)

    def _periodize_group(self, group: list[PeriodizationFact]):
        observations: list[PeriodizedFinancialObservation] = []
        parity: list[DirectDerivedParity] = []
        diagnostics: list[Mapping[str, Any]] = []
        if not group:
            return observations, parity, diagnostics
        fiscal_start = _fiscal_year_start(group)
        if fiscal_start is None:
            candidate_starts = sorted(str(item.period_start) for item in group if item.period_start)
            fiscal_start = candidate_starts[0] if candidate_starts else None
        if fiscal_start:
            group = [item if item.fiscal_year_start else replace(item, fiscal_year_start=fiscal_start) for item in group]
        is_financial = group[0].company_family == CompanyFamily.FINANCIAL.value
        metric = group[0].metric
        if group[0].company_family == CompanyFamily.UNKNOWN.value:
            return observations, parity, ({"metric": metric, "status": DATA_UNAVAILABLE,
                                            "reason": "COMPANY_FAMILY_UNKNOWN"},)
        if is_financial and metric in FINANCIAL_NON_APPLICABLE:
            return [self._not_applicable(group[0], fiscal_start)], parity, diagnostics

        by_anchor: dict[tuple[str, str], list[PeriodizationFact]] = defaultdict(list)
        for fact in group:
            if fact.reprt_code in REPORT_PERIODS:
                by_anchor[(fact.reprt_code, fact.rcept_no)].append(fact)
        for (code, anchor_no), anchor_facts in sorted(by_anchor.items(), key=lambda item: (_parse_date(item[1][0].rcept_dt) or date.min, item[0])):
            anchor = min(anchor_facts, key=lambda item: (_parse_date(item.rcept_dt) or date.min, item.rcept_no))
            period_info = REPORT_PERIODS[code]
            semantic_map = defaultdict(list)
            for fact in anchor_facts:
                semantic = _semantic(fact)
                if not _standard_duration(code, _duration_days(fact), semantic):
                    observations.append(self._unavailable(fact, fiscal_start, period_info[0], PERIODIZATION_UNSUPPORTED,
                                                         "NON_STANDARD_FISCAL_PERIOD"))
                    continue
                if semantic == "UNKNOWN":
                    observations.append(self._unavailable(fact, fiscal_start, period_info[0], PERIOD_AMBIGUOUS,
                                                         "PERIOD_CONTEXT_AMBIGUOUS"))
                    continue
                semantic_map[semantic].append(fact)
            cumulative = semantic_map.get(CUMULATIVE_YTD, [])
            direct = semantic_map.get(STANDALONE_QUARTER, [])
            instants = semantic_map.get(INSTANT, [])
            if metric in INSTANT_METRICS:
                observations.extend(self._instant_candidates(instants or cumulative, fiscal_start, period_info[2]))
                continue
            if cumulative:
                if len(cumulative) == 1:
                    if _valid_source(cumulative[0]):
                        observations.append(self._cumulative(cumulative[0], fiscal_start, period_info[1]))
                    else:
                        observations.append(self._unavailable(cumulative[0], fiscal_start, period_info[1],
                                                             DATA_UNAVAILABLE, "SOURCE_NOT_RESOLVED"))
                else:
                    observations.append(self._unavailable(anchor, fiscal_start, period_info[1], PERIOD_AMBIGUOUS,
                                                         "MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS"))
            elif code in {"11012", "11014", "11011"}:
                observations.append(self._unavailable(anchor, fiscal_start, period_info[1], DATA_UNAVAILABLE,
                                                     "CUMULATIVE_CONTEXT_MISSING"))

            if code == "11013":
                direct_candidate = self._unique(direct)
                if direct_candidate is not None and not _valid_source(direct_candidate):
                    direct_candidate = None
                if direct_candidate is not None and cumulative and len(cumulative) == 1:
                    observations.append(self._resolve_direct_derived(anchor, fiscal_start, "Q1", direct_candidate,
                                                                      cumulative[0].value, cumulative[0], parity))
                elif direct_candidate is not None:
                    observations.append(self._standalone(direct_candidate, fiscal_start, "Q1", "DIRECT_ONLY"))
                elif len(cumulative) == 1 and _valid_source(cumulative[0]):
                    observations.append(self._standalone(cumulative[0], fiscal_start, "Q1", "DIRECT_EQUIVALENT_YTD"))
                else:
                    observations.append(self._unavailable(anchor, fiscal_start, "Q1", DATA_UNAVAILABLE,
                                                         "Q1_STANDALONE_UNAVAILABLE"))
                continue

            prior_selection = self._prior_cumulative_selection(group, code, anchor)
            prior = prior_selection.selected
            if len(cumulative) > 1 or len(direct) > 1:
                observations.append(self._unavailable(anchor, fiscal_start, period_info[0], PERIOD_AMBIGUOUS,
                                                     "MULTIPLE_CURRENT_PERIOD_CONTEXTS"))
                continue
            direct_candidate = self._unique(direct)
            if direct_candidate is not None and not _valid_source(direct_candidate):
                direct_candidate = None
            cumulative_candidate = self._unique(cumulative)
            if cumulative_candidate is not None and not _valid_source(cumulative_candidate):
                cumulative_candidate = None
            derived_value = None
            derived_reason = None
            if cumulative_candidate is not None:
                if prior_selection.status == PRIOR_AMBIGUOUS:
                    derived_reason = prior_selection.reason or PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
                else:
                    coherent, derived_reason = _coherence(cumulative_candidate, prior, fiscal_start)
                if prior_selection.status != PRIOR_AMBIGUOUS and coherent:
                    derived_value = _difference(cumulative_candidate.value, prior.value)
                else:
                    derived_reason = derived_reason or DERIVATION_UNAVAILABLE
            if code == "11011":
                period_label = "Q4"
            else:
                period_label = period_info[0]
            if direct_candidate is not None and derived_value is not None:
                observations.append(self._resolve_direct_derived(anchor, fiscal_start, period_label,
                                                                  direct_candidate, derived_value,
                                                                  cumulative_candidate, parity,
                                                                  prior=prior))
            elif direct_candidate is not None:
                observations.append(self._standalone(direct_candidate, fiscal_start, period_label, "DIRECT_ONLY"))
            elif derived_value is not None:
                observations.append(self._derived(anchor, fiscal_start, period_label, cumulative_candidate, prior,
                                                  derived_value, "DERIVED_DIFFERENCE"))
            else:
                status = (PERIOD_AMBIGUOUS if prior_selection.status == PRIOR_AMBIGUOUS
                          else DERIVATION_UNAVAILABLE if cumulative_candidate is not None else DATA_UNAVAILABLE)
                observations.append(self._unavailable(anchor, fiscal_start, period_label, status,
                                                     derived_reason or "STANDALONE_UNAVAILABLE"))
        return observations, parity, diagnostics

    @staticmethod
    def _unique(values: list[PeriodizationFact]) -> PeriodizationFact | None:
        return values[0] if len(values) == 1 else None

    def _prior_cumulative_selection(self, group: list[PeriodizationFact], code: str,
                                    anchor: PeriodizationFact) -> PriorCumulativeSelection:
        prior_code = PRIOR_CUMULATIVE_CODE[code]
        anchor_dt = _parse_date(anchor.rcept_dt)
        if anchor_dt is None:
            return PriorCumulativeSelection(PRIOR_MISSING, reason="PRIOR_PIT_ANCHOR_RECEIPT_UNRESOLVED")
        candidates = [item for item in group
                      if item.reprt_code == prior_code and _semantic(item) == CUMULATIVE_YTD
                      and _valid_source(item) and _parse_date(item.rcept_dt) is not None
                      and _parse_date(item.rcept_dt) <= anchor_dt]
        if not candidates:
            return PriorCumulativeSelection(PRIOR_MISSING, reason="MISSING_PRIOR_CUMULATIVE")
        latest_dt = max(_parse_date(item.rcept_dt) for item in candidates)
        latest = tuple(item for item in candidates if _parse_date(item.rcept_dt) == latest_dt)
        distinct_rcept_nos = {item.rcept_no for item in latest}
        latest_text = latest_dt.isoformat() if latest_dt else None
        if len(distinct_rcept_nos) > 1:
            return PriorCumulativeSelection(
                PRIOR_AMBIGUOUS, eligible=latest, latest_rcept_dt=latest_text,
                reason=PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD,
            )
        return PriorCumulativeSelection(PRIOR_READY, selected=latest[0], eligible=latest,
                                        latest_rcept_dt=latest_text)

    def _prior_cumulative(self, group: list[PeriodizationFact], code: str,
                          anchor: PeriodizationFact) -> PeriodizationFact | None:
        """Backward-compatible selected-fact accessor; ambiguity returns None."""

        return self._prior_cumulative_selection(group, code, anchor).selected

    def _base(self, fact: PeriodizationFact, fiscal_start: str | None, period: str, semantic: str,
              *, value: Any, method: str, source: list[PeriodizationFact], status: str = READY,
              reason: str | None = None, direct: Any = None, cumulative: Any = None,
              derived: Any = None, difference: Any = None) -> PeriodizedFinancialObservation:
        return PeriodizedFinancialObservation(
            ticker=fact.ticker, corp_code=fact.corp_code, company_family=fact.company_family,
            fiscal_year=fact.fiscal_year, fiscal_year_start=fiscal_start, fiscal_period=period,
            period_semantics=semantic, period_start=fact.period_start, period_end=fact.period_end,
            metric=fact.metric, value=_number(value), currency=fact.currency, method=method,
            anchor_report_type=fact.report_type or REPORT_TYPE_BY_CODE.get(fact.reprt_code, "UNKNOWN"),
            anchor_reprt_code=fact.reprt_code, anchor_rcept_no=fact.rcept_no, anchor_rcept_dt=fact.rcept_dt,
            source_rcept_nos=tuple(item.rcept_no for item in source),
            source_rcept_dts=tuple(item.rcept_dt for item in source),
            source_sha256s=tuple(item.source_sha256 or "" for item in source),
            fs_div_used=fact.fs_div_used, pit_available_from=fact.pit_available_from or fact.rcept_dt,
            pit_granularity=self.pit_granularity, resolution_status=status, reason=reason,
            direct_value=_number(direct), cumulative_value=_number(cumulative),
            derived_standalone_value=_number(derived), direct_derived_difference=_number(difference),
        )

    def _cumulative(self, fact, fiscal_start, period):
        semantic = CUMULATIVE_YTD if period != "FY" else CUMULATIVE_YTD
        method = "DIRECT_FULL_YEAR" if period == "FY" else "DIRECT_CUMULATIVE"
        return self._base(fact, fiscal_start, period, semantic, value=fact.value, method=method, source=[fact], cumulative=fact.value)

    def _standalone(self, fact, fiscal_start, period, method):
        return self._base(fact, fiscal_start, period, STANDALONE_QUARTER, value=fact.value, method=method, source=[fact], direct=fact.value)

    def _derived(self, anchor, fiscal_start, period, cumulative, prior, value, method):
        return self._base(anchor, fiscal_start, period, STANDALONE_QUARTER, value=value, method=method,
                          source=[cumulative, prior], cumulative=cumulative.value, derived=value)

    def _resolve_direct_derived(self, anchor, fiscal_start, period, direct, derived_value, cumulative, parity, *, prior=None):
        difference = _difference(direct.value, derived_value)
        same = difference == 0
        parity.append(DirectDerivedParity(direct.metric, period, anchor.rcept_no, _number(direct.value),
                                           _number(derived_value), difference, "MATCH" if same else "MISMATCH"))
        if not same:
            return self._base(anchor, fiscal_start, period, STANDALONE_QUARTER, value=None,
                              method="NONE", source=[direct, cumulative] + ([prior] if prior else []),
                              status=DIRECT_DERIVED_MISMATCH, reason="DIRECT_DERIVED_MISMATCH",
                              direct=direct.value, cumulative=cumulative.value, derived=derived_value,
                              difference=difference)
        return self._base(direct, fiscal_start, period, STANDALONE_QUARTER, value=direct.value,
                          method="DIRECT_VALIDATED_BY_DERIVATION", source=[direct, cumulative] + ([prior] if prior else []),
                          direct=direct.value, cumulative=cumulative.value, derived=derived_value, difference=difference)

    def _instant_candidates(self, values, fiscal_start, period):
        if len(values) == 1 and _valid_source(values[0]):
            fact = values[0]
            return [self._base(fact, fiscal_start, period, INSTANT, value=fact.value,
                               method="DIRECT_INSTANT", source=[fact])]
        if values:
            return [self._unavailable(values[0], fiscal_start, period, PERIOD_AMBIGUOUS,
                                      "MULTIPLE_CURRENT_INSTANT_CONTEXTS")]
        return []

    def _unavailable(self, fact, fiscal_start, period, status, reason):
        return self._base(fact, fiscal_start, period, STANDALONE_QUARTER if period.startswith("Q") else CUMULATIVE_YTD,
                          value=None, method="NONE", source=[fact], status=status, reason=reason)

    def _not_applicable(self, fact, fiscal_start):
        return self._base(fact, fiscal_start, "NOT_APPLICABLE", CUMULATIVE_YTD, value=None,
                          method="NOT_APPLICABLE", source=[fact], status="NOT_APPLICABLE",
                          reason="FINANCIAL_COMPANY_NON_FINANCIAL_METRIC")


def periodize_facts(values: Iterable[PeriodizationFact | FinancialObservation | Mapping[str, Any]], *,
                    as_of: str | date | None = None) -> PeriodizationResult:
    return PeriodizationEngine().periodize(values, as_of=as_of)


def periodize_fiscal_year(values: Iterable[PeriodizationFact | FinancialObservation | Mapping[str, Any]], *,
                          as_of: str | date | None = None) -> PeriodizationResult:
    return periodize_facts(values, as_of=as_of)


def facts_from_xbrl_rows(rows: Iterable[Mapping[str, Any]], *, ticker: str, corp_code: str,
                         company_family: str, fiscal_year: str, reprt_code: str,
                         report_type: str | None = None, rcept_no: str, rcept_dt: str,
                         fs_div_used: str | None, source_sha256: str | None,
                         fiscal_year_start: str | None = None) -> tuple[PeriodizationFact, ...]:
    """Adapt ``XbrlRepository.period_context_rows`` into periodization facts.

    Fiscal start is taken from the earliest non-comparative duration context
    unless supplied explicitly.  Context dates remain the authority; report
    code only labels the filing sequence.
    """
    values = [dict(row) for row in rows if ACCOUNT_TO_METRIC.get(str(row.get("account_id") or ""))]
    if fiscal_year_start is None:
        starts = sorted({str(row.get("period_start")) for row in values
                         if row.get("period_start") and not row.get("comparative")})
        fiscal_year_start = starts[0] if starts else None
    result: list[PeriodizationFact] = []
    for row in values:
        metric = ACCOUNT_TO_METRIC[str(row.get("account_id"))]
        if metric in INSTANT_METRICS or row.get("instant"):
            semantic = INSTANT
        elif row.get("period_start") and fiscal_year_start and row.get("period_start") == fiscal_year_start:
            semantic = CUMULATIVE_YTD
        elif row.get("period_start"):
            semantic = STANDALONE_QUARTER
        else:
            semantic = "UNKNOWN"
        result.append(PeriodizationFact(
            ticker=ticker, corp_code=corp_code, company_family=company_family, fiscal_year=str(fiscal_year),
            fiscal_year_start=fiscal_year_start, metric=metric, value=row.get("value"),
            currency=row.get("currency"), reprt_code=str(reprt_code),
            report_type=report_type or str(row.get("report_type") or REPORT_TYPE_BY_CODE.get(str(reprt_code), "UNKNOWN")),
            rcept_no=rcept_no, rcept_dt=rcept_dt, period_start=row.get("period_start"),
            period_end=row.get("period_end") or row.get("instant"), fs_div_used=fs_div_used,
            source_sha256=source_sha256, period_semantics=semantic,
            context_semantics=row.get("context_semantics"), duration_days=row.get("duration_days"),
            instant=row.get("instant"), comparative=bool(row.get("comparative")),
            pit_available_from=rcept_dt,
        ))
    return tuple(result)
