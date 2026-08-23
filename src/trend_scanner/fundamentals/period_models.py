"""PIT-safe periodization models kept separate from Core observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


INSTANT = "INSTANT"
CUMULATIVE_YTD = "CUMULATIVE_YTD"
STANDALONE_QUARTER = "STANDALONE_QUARTER"
FULL_YEAR = "FULL_YEAR"

READY = "READY"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
PERIOD_AMBIGUOUS = "PERIOD_AMBIGUOUS"
DERIVATION_UNAVAILABLE = "DERIVATION_UNAVAILABLE"
DIRECT_DERIVED_MISMATCH = "DIRECT_DERIVED_MISMATCH"
BASIS_MISMATCH = "BASIS_MISMATCH"
PERIODIZATION_UNSUPPORTED = "PERIODIZATION_UNSUPPORTED"


@dataclass(frozen=True)
class PeriodizationFact:
    """A filing-specific fact/context consumed by :class:`PeriodizationEngine`.

    The model intentionally keeps report identity, period context, and source
    vintage together.  ``fiscal_year`` and ``fiscal_year_start`` should be
    supplied by the filing context when a non-calendar fiscal year is used.
    """

    ticker: str
    corp_code: str
    company_family: str
    fiscal_year: str
    metric: str
    value: int | float | None
    currency: str | None
    reprt_code: str
    report_type: str
    rcept_no: str
    rcept_dt: str
    period_start: str | None
    period_end: str | None
    fs_div_used: str | None = None
    source_sha256: str | None = None
    resolution_status: str = "RESOLVED"
    reason: str | None = None
    fiscal_year_start: str | None = None
    period_semantics: str | None = None
    context_semantics: str | None = None
    duration_days: int | None = None
    instant: str | None = None
    comparative: bool = False
    pit_available_from: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PeriodizationFact":
        data = dict(value)
        data.setdefault("ticker", "")
        data.setdefault("corp_code", "")
        data.setdefault("company_family", "UNKNOWN")
        data.setdefault("fiscal_year", data.get("bsns_year") or "")
        data.setdefault("metric", "")
        data.setdefault("value", data.get("thstrm_amount"))
        data.setdefault("currency", data.get("unitRef"))
        data.setdefault("reprt_code", str(data.get("reprt_code") or ""))
        data.setdefault("report_type", str(data.get("report_type") or "UNKNOWN"))
        data.setdefault("rcept_no", str(data.get("rcept_no") or ""))
        data.setdefault("rcept_dt", str(data.get("rcept_dt") or ""))
        data.setdefault("period_start", data.get("start") or data.get("period_start"))
        data.setdefault("period_end", data.get("end") or data.get("period_end") or data.get("instant"))
        data.setdefault("fs_div_used", data.get("fs_div"))
        data.setdefault("source_sha256", data.get("source_hash"))
        data.setdefault("resolution_status", "RESOLVED")
        data.setdefault("fiscal_year_start", data.get("fiscal_start"))
        data.setdefault("period_semantics", data.get("period_semantics"))
        data.setdefault("context_semantics", data.get("context_semantics"))
        data.setdefault("duration_days", data.get("duration_days"))
        data.setdefault("instant", data.get("instant"))
        data.setdefault("comparative", bool(data.get("comparative", False)))
        data.setdefault("pit_available_from", data.get("pit_available_from") or data.get("rcept_dt"))
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: data[key] for key in allowed if key in data})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "company_family": self.company_family,
            "fiscal_year": self.fiscal_year,
            "fiscal_year_start": self.fiscal_year_start,
            "metric": self.metric,
            "value": self.value,
            "currency": self.currency,
            "reprt_code": self.reprt_code,
            "report_type": self.report_type,
            "rcept_no": self.rcept_no,
            "rcept_dt": self.rcept_dt,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "fs_div_used": self.fs_div_used,
            "source_sha256": self.source_sha256,
            "resolution_status": self.resolution_status,
            "reason": self.reason,
            "period_semantics": self.period_semantics,
            "context_semantics": self.context_semantics,
            "duration_days": self.duration_days,
            "instant": self.instant,
            "comparative": self.comparative,
            "pit_available_from": self.pit_available_from,
        }


@dataclass(frozen=True)
class PriorCumulativeSelection:
    """PIT selection state used by derived-quarter resolution."""

    status: str
    selected: PeriodizationFact | None = None
    eligible: tuple[PeriodizationFact, ...] = ()
    latest_rcept_dt: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PeriodizedFinancialObservation:
    ticker: str
    corp_code: str
    company_family: str
    fiscal_year: str
    fiscal_year_start: str | None
    fiscal_period: str
    period_semantics: str
    period_start: str | None
    period_end: str | None
    metric: str
    value: int | float | None
    currency: str | None
    method: str
    anchor_report_type: str
    anchor_reprt_code: str
    anchor_rcept_no: str
    anchor_rcept_dt: str
    source_rcept_nos: tuple[str, ...] = ()
    source_sha256s: tuple[str, ...] = ()
    fs_div_used: str | None = None
    pit_available_from: str | None = None
    pit_granularity: str = "DAILY_EOD_KST"
    resolution_status: str = READY
    reason: str | None = None
    direct_value: int | float | None = None
    cumulative_value: int | float | None = None
    derived_standalone_value: int | float | None = None
    direct_derived_difference: int | float | None = None
    # Appended at the end to preserve positional-constructor compatibility
    # for existing consumers of the V01 model.
    source_rcept_dts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "company_family": self.company_family,
            "fiscal_year": self.fiscal_year,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_period": self.fiscal_period,
            "period_semantics": self.period_semantics,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "metric": self.metric,
            "value": self.value,
            "currency": self.currency,
            "method": self.method,
            "anchor_report_type": self.anchor_report_type,
            "anchor_reprt_code": self.anchor_reprt_code,
            "anchor_rcept_no": self.anchor_rcept_no,
            "anchor_rcept_dt": self.anchor_rcept_dt,
            "source_rcept_nos": list(self.source_rcept_nos),
            "source_rcept_dts": list(self.source_rcept_dts),
            "source_sha256s": list(self.source_sha256s),
            "fs_div_used": self.fs_div_used,
            "pit_available_from": self.pit_available_from,
            "pit_granularity": self.pit_granularity,
            "resolution_status": self.resolution_status,
            "reason": self.reason,
            "direct_value": self.direct_value,
            "cumulative_value": self.cumulative_value,
            "derived_standalone_value": self.derived_standalone_value,
            "direct_derived_difference": self.direct_derived_difference,
        }


@dataclass(frozen=True)
class DirectDerivedParity:
    metric: str
    fiscal_period: str
    anchor_rcept_no: str
    direct_value: int | float | None
    derived_value: int | float | None
    difference: int | float | None
    status: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "fiscal_period": self.fiscal_period,
            "anchor_rcept_no": self.anchor_rcept_no,
            "direct_value": self.direct_value,
            "derived_value": self.derived_value,
            "difference": self.difference,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PeriodizationResult:
    observations: tuple[PeriodizedFinancialObservation, ...]
    parity: tuple[DirectDerivedParity, ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def __iter__(self):
        return iter(self.observations)

    def __len__(self) -> int:
        return len(self.observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "parity": [item.to_dict() for item in self.parity],
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def as_facts(values: Iterable[PeriodizationFact | Mapping[str, Any]]) -> tuple[PeriodizationFact, ...]:
    return tuple(item if isinstance(item, PeriodizationFact) else PeriodizationFact.from_mapping(item) for item in values)
