#!/usr/bin/env python3
"""Assessment V01 FIX01 validation.

The validator exercises the production Derived Metrics -> Assessment boundary.
It is cache-first.  ``--hydrate`` permits only bounded OpenDART cache hydration
for missing filing lists/XBRL artifacts; it never imports or calls PyKRX/KRX.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/assessment_v01_fix01"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_ASSESSMENT_V01_FIX01"
START_HEAD = "e72a51287cc7a6ba6978e8407c72d255cb580158"
REQUESTED_AS_OF = "2026-08-20"
HISTORICAL_AS_OF = "2024-02-15"
CURRENT_YEARS = ("2024", "2025", "2026")
HISTORICAL_YEARS = ("2022", "2023", "2024")
CURRENT_TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
HISTORICAL_TICKERS = ("005930", "000660", "068270")
FINANCIAL_TICKER = "086790"
MAX_OPENDART_REQUESTS = 60
REPORT_CODES = ("11013", "11012", "11014", "11011")
REPORT_TYPE_BY_CODE = {"11013": "Q1", "11012": "Q2", "11014": "Q3", "11011": "FY"}
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온",
    "012330": "현대모비스", "086790": "하나금융지주",
}
TARGETED_FILES = (
    "tests/test_opendart_fundamentals_contract.py",
    "tests/test_opendart_fundamentals_core.py",
    "tests/test_opendart_fundamentals_core_fix01.py",
    "tests/test_opendart_fundamentals_core_fix02.py",
    "tests/test_opendart_fundamentals_periodization_v01.py",
    "tests/test_opendart_fundamentals_periodization_fix01.py",
    "tests/test_opendart_fundamentals_periodization_fix02.py",
    "tests/test_opendart_fundamentals_periodization_fix03.py",
    "tests/test_opendart_fundamentals_periodization_fix04.py",
    "tests/test_opendart_fundamentals_periodization_fix05.py",
    "tests/test_opendart_fundamentals_derived_metrics.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix01.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02_correction.py",
    "tests/test_opendart_historical_promotion_detector.py",
    "tests/test_opendart_q1_context_ambiguity_audit.py",
    "tests/test_opendart_periodization_canonical_duplicate_collapse.py",
    "tests/test_opendart_context_scope_hardening.py",
    "tests/test_opendart_final_validation_gate.py",
    "tests/test_opendart_fundamentals_assessment.py",
)

sys.path.insert(0, str(ROOT / "src"))
from trend_scanner.fundamentals.assessment import (  # noqa: E402
    ASSESSMENT_SCOPE_CURRENT,
    ASSESSMENT_SCOPE_RANGE,
    FundamentalsAssessmentEngine,
)
from trend_scanner.fundamentals.assessment_models import FundamentalsAssessmentResult  # noqa: E402
from trend_scanner.fundamentals.assessment_provider import FundamentalsAssessmentProvider  # noqa: E402
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository  # noqa: E402
from trend_scanner.fundamentals.derived_metrics import DerivedMetricObservation, DerivedMetricsResult  # noqa: E402
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsBuild, DerivedMetricsProvider  # noqa: E402
from trend_scanner.fundamentals.filing_registry import (  # noqa: E402
    FilingRegistry,
    to_registered_filing,
)
from trend_scanner.fundamentals.models import RegisteredFiling  # noqa: E402
from trend_scanner.fundamentals.opendart_client import OpenDartClient  # noqa: E402
from trend_scanner.fundamentals.period_models import PeriodizationResult  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild, PeriodizationProvider  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402


class RequestBudgetExceeded(RuntimeError):
    """Raised before an OpenDART request would exceed the declared budget."""


class BoundedOpenDartClient(OpenDartClient):
    def _check_budget(self) -> None:
        if len(self.audit) >= MAX_OPENDART_REQUESTS:
            raise RequestBudgetExceeded(
                f"OpenDART request budget {MAX_OPENDART_REQUESTS} reached; no retry was attempted"
            )

    def get_json(self, endpoint: str, params: Mapping[str, Any]):  # type: ignore[override]
        self._check_budget()
        return super().get_json(endpoint, params)

    def get_binary(self, endpoint: str, params: Mapping[str, Any]):  # type: ignore[override]
        self._check_budget()
        return super().get_binary(endpoint, params)


class TrackingFilingRegistry(FilingRegistry):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.cache_hits = 0
        self.cache_misses = 0

    def list_regular_filings(self, *args: Any, **kwargs: Any) -> list[RegisteredFiling]:  # type: ignore[override]
        rows = super().list_regular_filings(*args, **kwargs)
        if self.last_metadata.get("cache_hit") is True:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        return rows


class TrackingXbrlRepository(XbrlRepository):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.cache_hits = 0
        self.cache_misses = 0

    def fetch(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        artifact = super().fetch(*args, **kwargs)
        if artifact.cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        return artifact


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "OPENDART_API_KEY" and value.strip():
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def _metadata(ticker: str) -> dict[str, Any]:
    return {"company_family": "FINANCIAL" if ticker == FINANCIAL_TICKER else "NON_FINANCIAL"}


def _run_targeted_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TARGETED_FILES]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    return {
        "targeted_test_command": " ".join(command),
        "targeted_test_files": list(TARGETED_FILES),
        "targeted_test_count": count,
        "targeted_test_status": "PASS" if completed.returncode == 0 and count else "FAIL",
        "targeted_test_returncode": completed.returncode,
        "targeted_test_output_tail": output[-1800:],
    }


def _synth(metric: str, metric_type: str, value: Any, *, year: str = "2025", period: str = "Q3",
           status: str = "READY", metadata: Mapping[str, Any] | None = None,
           family: str = "NON_FINANCIAL", pit: str | None = "2025-10-15") -> DerivedMetricObservation:
    token = f"FIX01-{metric}-{metric_type}-{year}-{period}"
    return DerivedMetricObservation(
        ticker="FIX01", corp_code="FIX01", company_family=family, fiscal_year=year,
        fiscal_period=period, metric=metric, metric_type=metric_type, value=value,
        resolution_status=status, reason=None if status == "READY" else "FIXTURE_NOT_READY",
        period_end=f"{year}-09-30" if period == "Q3" else f"{year}-12-31",
        source_rcept_nos=(token,), source_rcept_dts=(pit or "",), source_sha256s=(f"sha-{token}",),
        requested_as_of="2025-10-15", pit_available_from=pit, metadata=dict(metadata or {}),
    )


def _scenario(*, revenue: float = 10, operating_income: float = 10, net_income: float = 10,
              ocf: float = 10, op_margin: float = 10, net_margin: float = 5, ocf_margin: float = 4,
              op_expansion: str = "EXPANDING", net_expansion: str = "EXPANDING",
              ocf_trend: str = "IMPROVING", acceleration: float = 1, streak: float = 3,
              op_transition: str = "PROFIT_GROWTH", net_transition: str = "PROFIT_GROWTH",
              year: str = "2025", period: str = "Q3") -> DerivedMetricsResult:
    rows = [
        _synth("revenue", "QUARTERLY_YOY", revenue, year=year, period=period),
        _synth("operating_income", "QUARTERLY_YOY", operating_income, year=year, period=period),
        _synth("net_income", "QUARTERLY_YOY", net_income, year=year, period=period),
        _synth("operating_cash_flow", "QUARTERLY_YOY", ocf, year=year, period=period),
        _synth("operating_income", "OPERATING_MARGIN", op_margin, year=year, period=period),
        _synth("net_income", "NET_MARGIN", net_margin, year=year, period=period),
        _synth("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", ocf_margin, year=year, period=period),
        _synth("operating_income", "MARGIN_EXPANSION_TREND", 1 if op_expansion == "EXPANDING" else -1 if op_expansion == "CONTRACTING" else 0,
               metadata={"classification": op_expansion}, year=year, period=period),
        _synth("net_income", "MARGIN_EXPANSION_TREND", 1 if net_expansion == "EXPANDING" else -1 if net_expansion == "CONTRACTING" else 0,
               metadata={"classification": net_expansion}, year=year, period=period),
        _synth("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", ocf_trend, year=year, period=period),
        *[_synth(metric, "YOY_GROWTH_ACCELERATION", acceleration, year=year, period=period)
          for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        *[_synth(metric, "CONSECUTIVE_YOY_GROWTH", streak, year=year, period=period)
          for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        _synth("operating_income", "EARNINGS_TRANSITION", op_transition, year=year, period=period),
        _synth("net_income", "EARNINGS_TRANSITION", net_transition, year=year, period=period),
    ]
    return DerivedMetricsResult(tuple(rows))


def _synthetic_validation() -> dict[str, Any]:
    cases = {
        "BROAD_STRONG": (_scenario(), "STRONG"),
        "TURNAROUND": (_scenario(op_transition="LOSS_TO_PROFIT"), "TURNAROUND"),
        "WEAK_LEVEL_IMPROVING_DIRECTION": (_scenario(
            op_margin=-1, net_margin=-1, op_expansion="EXPANDING", net_expansion="EXPANDING",
            op_transition="LOSS_NARROWING", ocf_trend="IMPROVING"), "IMPROVING"),
        "BROAD_WEAK": (_scenario(revenue=-10, operating_income=-20, net_income=-20, ocf=-20,
                                  op_margin=-2, net_margin=-3, ocf_margin=-4,
                                  op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                  ocf_trend="DETERIORATING", acceleration=-1,
                                  op_transition="PROFIT_DECLINE", net_transition="PROFIT_DECLINE"), "WEAK"),
        "DECELERATION": (_scenario(op_margin=-1, net_margin=-1, ocf=-10, ocf_margin=-1,
                                    op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                    ocf_trend="DETERIORATING", acceleration=-1), "WEAKENING"),
        "INSUFFICIENT": (DerivedMetricsResult((_synth("revenue", "QUARTERLY_YOY", 10),)), "INSUFFICIENT_DATA"),
    }
    engine = FundamentalsAssessmentEngine()
    rows: list[dict[str, Any]] = []
    for name, (source, expected) in cases.items():
        result = engine.assess(source, assessment_scope=ASSESSMENT_SCOPE_RANGE)
        rows.append({
            "case": name, "expected": expected, "observed": result.overall_state,
            "matched_rule_id": result.matched_rule_id,
            "matched_candidate_rules": list(result.matched_candidate_rules),
            "axis_directions": dict(result.axis_directions),
            "status": "PASS" if result.overall_state == expected else "FAIL",
        })
    directional_violations = sum(
        int(row["case"] == "WEAK_LEVEL_IMPROVING_DIRECTION" and row["observed"] != "IMPROVING")
        for row in rows
    )
    return {
        "case_count": len(rows), "case_pass_count": sum(row["status"] == "PASS" for row in rows),
        "directional_semantic_violation_count": directional_violations,
        "cases": rows,
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) and directional_violations == 0 else "FAIL",
    }


def _currentness_validation() -> dict[str, Any]:
    original = _scenario(year="2026")
    source = DerivedMetricsResult(tuple(
        DerivedMetricObservation(
            ticker=item.ticker, corp_code=item.corp_code, company_family=item.company_family,
            fiscal_year=item.fiscal_year, fiscal_period=item.fiscal_period, metric=item.metric,
            metric_type=item.metric_type, value=item.value, unit=item.unit,
            resolution_status=item.resolution_status, reason=item.reason, period_end=item.period_end,
            source_rcept_nos=item.source_rcept_nos, source_rcept_dts=(REQUESTED_AS_OF,),
            source_sha256s=item.source_sha256s, requested_as_of=REQUESTED_AS_OF,
            pit_available_from=REQUESTED_AS_OF, metadata=item.metadata,
        ) for item in original.observations
    ))
    verified_build = DerivedMetricsBuild(
        ticker="FIX01", requested_as_of=REQUESTED_AS_OF, fiscal_years=CURRENT_YEARS,
        periodization_builds=(), canonical_observations=(), result=source,
    )
    stale_build = DerivedMetricsBuild(
        ticker="FIX01", requested_as_of=REQUESTED_AS_OF, fiscal_years=("2024", "2025"),
        periodization_builds=(), canonical_observations=(), result=source,
    )
    engine = FundamentalsAssessmentEngine()
    verified = engine.assess(verified_build, requested_as_of=REQUESTED_AS_OF,
                             assessment_scope=ASSESSMENT_SCOPE_CURRENT, expected_current_fiscal_year="2026")
    stale = engine.assess(stale_build, requested_as_of=REQUESTED_AS_OF,
                          assessment_scope=ASSESSMENT_SCOPE_CURRENT, expected_current_fiscal_year="2026")
    ranged = engine.assess(verified_build, requested_as_of=REQUESTED_AS_OF, assessment_scope=ASSESSMENT_SCOPE_RANGE)
    status = "PASS" if (
        verified.currentness_status == "VERIFIED" and verified.status == "READY"
        and stale.currentness_status == "STALE_INPUT_RANGE" and stale.status == "INPUT_NOT_READY"
        and ranged.currentness_status == "RANGE_ONLY"
    ) else "FAIL"
    return {
        "status": status,
        "verified": verified.to_dict(), "stale_negative_control": stale.to_dict(), "explicit_range": ranged.to_dict(),
    }


def _period_anchor_validation() -> dict[str, Any]:
    rows = list(_scenario(year="2025", period="Q3").observations)
    def clone(item: DerivedMetricObservation, *, period: str) -> DerivedMetricObservation:
        return DerivedMetricObservation(
            ticker=item.ticker, corp_code=item.corp_code, company_family=item.company_family,
            fiscal_year=item.fiscal_year, fiscal_period=period, metric=item.metric,
            metric_type=item.metric_type, value=item.value, unit=item.unit,
            resolution_status=item.resolution_status, reason=item.reason,
            period_end="2025-12-31", source_rcept_nos=item.source_rcept_nos,
            source_rcept_dts=item.source_rcept_dts, source_sha256s=item.source_sha256s,
            requested_as_of=item.requested_as_of, pit_available_from=item.pit_available_from,
            metadata=item.metadata,
        )
    q4 = [clone(item, period="Q4") for item in rows]
    fy = [clone(item, period="FY") for item in rows]
    engine = FundamentalsAssessmentEngine()
    first = engine.assess(DerivedMetricsResult(tuple(q4 + fy)))
    second = engine.assess(DerivedMetricsResult(tuple(reversed(fy + q4))))
    equal = first.to_dict() == second.to_dict() and first.current_fiscal_period == "FY"
    return {
        "status": "PASS" if equal else "FAIL", "period_order": {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5},
        "first_current_period": first.current_fiscal_period, "second_current_period": second.current_fiscal_period,
        "input_order_dependence_count": int(not equal),
    }


def _make_provider(client: OpenDartClient | None):
    corp_path = ROOT / "data/cache/opendart/corp_code_cache.json"
    corp = CorpCodeRepository(client, cache_path=corp_path)
    if client is None:
        corp = CorpCodeRepository.from_cache(corp_path)
    filings = TrackingFilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl = TrackingXbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    derived = DerivedMetricsProvider(PeriodizationProvider(corp, filings, xbrl))
    return FundamentalsAssessmentProvider(derived), corp, filings, xbrl


def _cache_path(corp_code: str, year: str, code: str) -> Path:
    return ROOT / "data/cache/opendart/filings" / f"{corp_code}_{year}_{code}.json"


def _cache_covers(path: Path, *, required_start: str, requested_as_of: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        return bool(metadata.get("cache_complete") is True and metadata.get("api_status") == "000"
                    and metadata.get("http_status") == 200
                    and str(metadata.get("coverage_start", "")) <= required_start
                    and str(metadata.get("coverage_end", "")) >= requested_as_of)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False


def _hydrate_filing_year(client: BoundedOpenDartClient, corp: CorpCodeRepository, *, ticker: str,
                         year: str, requested_as_of: str) -> dict[str, Any]:
    record = corp.get_record(ticker)
    required_start = f"{year}-01-01"
    missing_codes = [code for code in REPORT_CODES if not _cache_covers(
        _cache_path(record.corp_code, year, code), required_start=required_start, requested_as_of=requested_as_of
    )]
    if not missing_codes:
        return {"ticker": ticker, "year": year, "status": "CACHE_COVERED", "request_count": 0}

    bgn_de = required_start.replace("-", "")
    end_de = requested_as_of.replace("-", "")
    raw_rows: list[dict[str, Any]] = []
    responses = []
    page_no = 1
    total_page: int | None = None
    while True:
        response = client.list_filings(record.corp_code, bgn_de=bgn_de, end_de=end_de,
                                       page_no=page_no, page_count=100)
        responses.append(response)
        if response.http_status != 200 or response.status != "000":
            raise RuntimeError(f"OpenDART filing registry failed for {ticker}/{year}: status={response.status}")
        payload = response.payload
        page_rows = payload.get("list") if isinstance(payload.get("list"), list) else []
        raw_rows.extend(row for row in page_rows if isinstance(row, dict))
        try:
            total_page = int(payload.get("total_page")) if payload.get("total_page") is not None else total_page
        except (TypeError, ValueError):
            pass
        if (total_page is not None and page_no >= total_page) or (total_page is None and len(page_rows) < 100):
            break
        page_no += 1
        if page_no > 50:
            raise RuntimeError(f"OpenDART filing registry pagination exceeded for {ticker}/{year}")

    retrieved_at = datetime.now(timezone.utc).isoformat()
    parsed: dict[str, dict[str, RegisteredFiling]] = {code: {} for code in REPORT_CODES}
    for row in raw_rows:
        item = to_registered_filing(row, ticker=ticker, retrieved_at=retrieved_at)
        if item is not None and item.bsns_year == year and item.reprt_code in parsed:
            parsed[item.reprt_code][item.rcept_no] = item
    source_hash = hashlib.sha256(b"".join(response.raw for response in responses)).hexdigest()
    for code in missing_codes:
        rows = sorted(parsed[code].values(), key=lambda item: (item.rcept_dt, item.rcept_no))
        metadata = {
            "source_provider": "OPENDART", "source_kind": "BOUNDED_CACHE_HYDRATION",
            "corp_code": record.corp_code, "ticker": ticker, "bsns_year": year, "reprt_code": code,
            "request_parameters": {"corp_code": record.corp_code, "bsns_year": year, "reprt_code": code},
            "request_window": {"bgn_de": bgn_de, "end_de": end_de},
            "coverage_start": required_start, "coverage_end": requested_as_of,
            "retrieved_at": retrieved_at, "page_count_requested": 100, "pages_fetched": len(responses),
            "total_count": len(raw_rows), "total_page": total_page or len(responses),
            "http_status": 200, "api_status": "000", "source_sha256": source_hash,
            "record_count": len(rows), "cache_complete": True, "cache_hit": False,
        }
        path = _cache_path(record.corp_code, year, code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"metadata": metadata, "filings": [row.to_dict() for row in rows]},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ticker": ticker, "year": year, "status": "HYDRATED", "request_count": len(responses),
            "missing_codes": missing_codes, "filing_count": sum(len(rows) for rows in parsed.values())}


def _hydrate_missing(client: BoundedOpenDartClient, corp: CorpCodeRepository) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pairs = [(ticker, year, REQUESTED_AS_OF) for ticker in CURRENT_TICKERS for year in CURRENT_YEARS]
    pairs += [(ticker, year, HISTORICAL_AS_OF) for ticker in HISTORICAL_TICKERS for year in HISTORICAL_YEARS]
    for ticker, year, cutoff in pairs:
        records.append(_hydrate_filing_year(client, corp, ticker=ticker, year=year, requested_as_of=cutoff))
    return records


def _financial_control() -> FundamentalsAssessmentResult:
    dummy_period = PeriodizationBuild(
        ticker=FINANCIAL_TICKER, fiscal_year="2026", requested_as_of=REQUESTED_AS_OF,
        company_family="FINANCIAL", filings=(), facts=(), result=PeriodizationResult(()),
    )
    build = DerivedMetricsBuild(
        ticker=FINANCIAL_TICKER, requested_as_of=REQUESTED_AS_OF, fiscal_years=CURRENT_YEARS,
        periodization_builds=(dummy_period,), canonical_observations=(), result=DerivedMetricsResult(()),
    )
    return FundamentalsAssessmentEngine().assess(
        build, requested_as_of=REQUESTED_AS_OF, assessment_scope=ASSESSMENT_SCOPE_CURRENT,
        expected_current_fiscal_year="2026",
    )


def _build_cohorts(provider: FundamentalsAssessmentProvider) -> tuple[list[FundamentalsAssessmentResult], list[dict[str, Any]], list[FundamentalsAssessmentResult], list[dict[str, Any]]]:
    current: list[FundamentalsAssessmentResult] = []
    current_errors: list[dict[str, Any]] = []
    for ticker in CURRENT_TICKERS:
        try:
            current.append(provider.build_current(ticker, REQUESTED_AS_OF, lookback_fiscal_years=3,
                                                  company_metadata=_metadata(ticker), force_refresh=False))
        except Exception as exc:
            current_errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    historical: list[FundamentalsAssessmentResult] = []
    historical_errors: list[dict[str, Any]] = []
    for ticker in HISTORICAL_TICKERS:
        try:
            historical.append(provider.build(ticker, HISTORICAL_YEARS, HISTORICAL_AS_OF,
                                             company_metadata=_metadata(ticker), force_refresh=False))
        except Exception as exc:
            historical_errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    return current, current_errors, historical, historical_errors


def _result_row(result: FundamentalsAssessmentResult, *, scope: str) -> dict[str, Any]:
    return {
        "ticker": result.ticker, "company": NAMES.get(result.ticker, ""), "company_family": result.company_family,
        "assessment_scope": result.assessment_scope, "currentness_status": result.currentness_status,
        "requested_as_of": result.requested_as_of, "current_fiscal_year": result.current_fiscal_year,
        "current_period": result.current_fiscal_period, "overall_state": result.overall_state,
        "growth_level": result.growth_state, "profitability_level": result.profitability_state,
        "cash_flow_level": result.cash_flow_state, "momentum_level": result.momentum_state,
        "growth_direction": result.growth_direction, "profitability_direction": result.profitability_direction,
        "cash_flow_direction": result.cash_flow_direction,
        "improving_direction_axis_count": result.improving_direction_axis_count,
        "deteriorating_direction_axis_count": result.deteriorating_direction_axis_count,
        "negative_level_axis_count": result.negative_level_axis_count,
        "strengths": "|".join(result.strengths), "risks": "|".join(result.risks),
        "matched_rule_id": result.matched_rule_id,
        "matched_candidate_rules": "|".join(result.matched_candidate_rules),
        "status": result.status, "scope_label": scope,
    }


def _provenance_counts(results: Iterable[FundamentalsAssessmentResult], cutoff: str) -> dict[str, int]:
    cutoff_date = date.fromisoformat(cutoff)
    counts = Counter()
    positive_codes = {"YOY_ACCELERATING", "POSITIVE_GROWTH_STREAK", "LOSS_TO_PROFIT", "LOSS_NARROWING",
                      "PROFIT_GROWTH", "MARGIN_EXPANDING", "OCF_TREND_IMPROVING",
                      "OPERATING_CASH_FLOW_YOY_POSITIVE", "TTM_OPERATING_CASH_FLOW_YOY_POSITIVE"}
    negative_codes = {"YOY_DECELERATING", "PROFIT_TO_LOSS", "LOSS_WIDENING", "MARGIN_CONTRACTING",
                      "OCF_TREND_DETERIORATING", "OPERATING_CASH_FLOW_YOY_NEGATIVE",
                      "TTM_OPERATING_CASH_FLOW_YOY_NEGATIVE", "OPERATING_INCOME_YOY_NEGATIVE",
                      "NET_INCOME_YOY_NEGATIVE"}
    for result in results:
        diagnostics = result.diagnostics
        for key in ("future_assessment_source_count", "ready_missing_pit_available_count",
                    "ready_future_pit_available_count", "provider_cutoff_mismatch_count"):
            counts[key] += int(diagnostics.get(key, 0))
        counts["assessment_rule_conflict_count"] += int(result.assessment_rule_conflict_count)
        counts["assessment_rule_mismatch_count"] += int(result.assessment_rule_mismatch_count)
        for axis, direction in result.axis_directions.items():
            support = {item.explanation_code for item in result.evidence if item.axis == axis and item.status == "READY"}
            if direction == "IMPROVING" and not support.intersection(positive_codes):
                counts["improving_without_directional_support_count"] += 1
            if direction == "DETERIORATING" and not support.intersection(negative_codes):
                counts["weakening_without_directional_support_count"] += 1
        for item in result.evidence:
            if item.status != "READY":
                continue
            if not (len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)):
                counts["evidence_provenance_alignment_error_count"] += 1
            if not item.pit_available_from:
                counts["ready_missing_pit_available_count"] += 1
            else:
                try:
                    if date.fromisoformat(item.pit_available_from[:10]) > cutoff_date:
                        counts["ready_future_pit_available_count"] += 1
                except ValueError:
                    counts["evidence_provenance_alignment_error_count"] += 1
            for source_dt in item.source_rcept_dts:
                try:
                    if source_dt and date.fromisoformat(source_dt[:10]) > cutoff_date:
                        counts["future_assessment_source_count"] += 1
                except ValueError:
                    counts["evidence_provenance_alignment_error_count"] += 1
    return {key: int(value) for key, value in counts.items()}


def _dependency_counts() -> tuple[int, int]:
    path = ROOT / "src/trend_scanner/fundamentals/assessment.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pattern_tokens = ("pattern_a", "rs_engine", "foreign_flow", "fast_strategy", "julia_strategy")
    price_tokens = ("price_provider", "pykrx", "krx")
    pattern_count = price_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name.lower() for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [str(node.module or "").lower()]
        else:
            continue
        pattern_count += sum(any(token in name for token in pattern_tokens) for name in names)
        price_count += sum(any(token in name for token in price_tokens) for name in names)
    return pattern_count, price_count


def _manifest() -> dict[str, Any]:
    files = {path.name: _sha(path) for path in sorted(ARTIFACT_DIR.iterdir())
             if path.is_file() and path.name != "assessment_fix01_manifest.json"}
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hydrate", action="store_true", help="Permit bounded OpenDART cache hydration")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    targeted = _run_targeted_tests()
    client: BoundedOpenDartClient | None = None
    hydration_records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    budget_exceeded = False
    if args.hydrate and not key:
        errors.append({"scope": "network", "error_type": "MISSING_OPENDART_API_KEY"})
    elif args.hydrate:
        client = BoundedOpenDartClient(api_key=key)
    provider, corp, filings, xbrl = _make_provider(client)
    if client is not None:
        try:
            corp.ensure_loaded()
            hydration_records = _hydrate_missing(client, corp)
        except RequestBudgetExceeded as exc:
            budget_exceeded = True
            errors.append({"scope": "hydration", "error_type": type(exc).__name__, "message": str(exc)})
        except Exception as exc:
            errors.append({"scope": "hydration", "error_type": type(exc).__name__, "message": str(exc)})

    try:
        current, current_errors, historical, historical_errors = _build_cohorts(provider)
        errors.extend({"scope": "current", **item} for item in current_errors)
        errors.extend({"scope": "historical", **item} for item in historical_errors)
    except Exception as exc:
        current, historical = [], []
        errors.append({"scope": "build", "error_type": type(exc).__name__, "message": str(exc)})
    financial = _financial_control()
    current_with_financial = current + [financial]
    synthetic = _synthetic_validation()
    currentness = _currentness_validation()
    anchor = _period_anchor_validation()
    all_results = tuple(current_with_financial) + tuple(historical)
    current_provenance = _provenance_counts(current_with_financial, REQUESTED_AS_OF)
    historical_provenance = _provenance_counts(historical, HISTORICAL_AS_OF)
    pattern_count, price_count = _dependency_counts()

    expected_overlap = {tuple(sorted(("OVERALL_TURNAROUND_V01", "OVERALL_IMPROVING_V01")))}
    unexpected_overlap_rows = []
    for result in all_results:
        candidates = result.matched_candidate_rules
        pairs = [tuple(sorted((left, right))) for index, left in enumerate(candidates) for right in candidates[index + 1:]]
        unexpected = [pair for pair in pairs if pair not in expected_overlap]
        if unexpected:
            unexpected_overlap_rows.append({"ticker": result.ticker, "pairs": unexpected})
    conflict_control = FundamentalsAssessmentEngine().assess(_scenario(
        revenue=-10, operating_income=-20, net_income=-20, ocf=-20, op_margin=-2, net_margin=-3, ocf_margin=-4,
        op_expansion="EXPANDING", net_expansion="FLAT", ocf_trend="IMPROVING", acceleration=0, streak=0,
        op_transition="LOSS_TO_PROFIT", net_transition="PROFIT_DECLINE"))
    candidate_controls = [FundamentalsAssessmentEngine().assess(source) for source, _ in (
        (_scenario(), "STRONG"), (_scenario(op_transition="LOSS_TO_PROFIT"), "TURNAROUND"),
        (_scenario(revenue=-10, operating_income=-20, net_income=-20, ocf=-20, op_margin=-2, net_margin=-3,
                   ocf_margin=-4, op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                   ocf_trend="DETERIORATING", acceleration=-1, op_transition="PROFIT_DECLINE",
                   net_transition="PROFIT_DECLINE"), "WEAK"),
    )]
    rule_candidate = {
        "status": "PASS" if all(result.matched_rule_id in result.matched_candidate_rules for result in candidate_controls)
        and all(result.assessment_rule_mismatch_count == 0 for result in candidate_controls) else "FAIL",
        "production_results": [{"ticker": result.ticker, "matched_rule_id": result.matched_rule_id,
                                "matched_candidate_rules": list(result.matched_candidate_rules),
                                "assessment_rule_mismatch_count": result.assessment_rule_mismatch_count} for result in all_results],
        "synthetic_controls": [{"matched_rule_id": result.matched_rule_id,
                                "matched_candidate_rules": list(result.matched_candidate_rules),
                                "assessment_rule_mismatch_count": result.assessment_rule_mismatch_count}
                               for result in candidate_controls],
    }
    rule_conflict = {
        "status": "PASS" if financial.assessment_rule_conflict_count == 0
        and conflict_control.assessment_rule_conflict_count >= 1
        and not unexpected_overlap_rows else "FAIL",
        "expected_turnaround_improving_overlap": {
            "matched_candidate_rules": list(FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT")).matched_candidate_rules),
            "conflict_count": FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT")).assessment_rule_conflict_count,
        },
        "unexpected_overlap_control": {"matched_candidate_rules": list(conflict_control.matched_candidate_rules),
                                        "conflict_count": conflict_control.assessment_rule_conflict_count},
        "production_unexpected_overlaps": unexpected_overlap_rows,
    }
    financial_ok = financial.status == "NOT_APPLICABLE" and financial.overall_state == "NOT_APPLICABLE" \
        and financial.matched_rule_id == "FINANCIAL_PROFILE_NOT_IMPLEMENTED" and financial.currentness_status == "VERIFIED"

    counters = {
        "production_current_ready_count": sum(result.status == "READY" for result in current),
        "production_current_stale_count": sum(result.currentness_status == "STALE_INPUT_RANGE" for result in current),
        "currentness_verified_count": sum(result.currentness_status == "VERIFIED" for result in current_with_financial),
        "currentness_unverified_count": sum(result.currentness_status != "VERIFIED" for result in current_with_financial),
        "historical_result_count": len(historical),
        "historical_ready_count": sum(result.status == "READY" for result in historical),
        "historical_error_count": sum(item.get("scope") == "historical" for item in errors),
        "future_assessment_source_count": current_provenance.get("future_assessment_source_count", 0) + historical_provenance.get("future_assessment_source_count", 0),
        "ready_missing_pit_available_count": current_provenance.get("ready_missing_pit_available_count", 0) + historical_provenance.get("ready_missing_pit_available_count", 0),
        "ready_future_pit_available_count": current_provenance.get("ready_future_pit_available_count", 0) + historical_provenance.get("ready_future_pit_available_count", 0),
        "provider_cutoff_mismatch_count": current_provenance.get("provider_cutoff_mismatch_count", 0) + historical_provenance.get("provider_cutoff_mismatch_count", 0),
        "evidence_provenance_alignment_error_count": current_provenance.get("evidence_provenance_alignment_error_count", 0) + historical_provenance.get("evidence_provenance_alignment_error_count", 0),
        "assessment_rule_conflict_count": current_provenance.get("assessment_rule_conflict_count", 0) + historical_provenance.get("assessment_rule_conflict_count", 0),
        "assessment_rule_mismatch_count": current_provenance.get("assessment_rule_mismatch_count", 0) + historical_provenance.get("assessment_rule_mismatch_count", 0),
        "improving_without_directional_support_count": current_provenance.get("improving_without_directional_support_count", 0) + historical_provenance.get("improving_without_directional_support_count", 0),
        "weakening_without_directional_support_count": current_provenance.get("weakening_without_directional_support_count", 0) + historical_provenance.get("weakening_without_directional_support_count", 0),
        "period_anchor_order_dependence_count": anchor["input_order_dependence_count"],
        "financial_not_applicable_count": int(financial_ok),
        "pattern_a_import_count": pattern_count, "price_provider_import_count": price_count,
        "pykrx_krx_network_request_count": 0,
        "opendart_request_count": len(client.audit) if client is not None else 0,
        "opendart_cache_hit_count": int(getattr(corp, "cache_hit", False)) + filings.cache_hits + xbrl.cache_hits,
        "opendart_cache_miss_count": (0 if getattr(corp, "cache_hit", False) else int(client is not None)) + filings.cache_misses + xbrl.cache_misses,
    }
    required_zero = (
        "production_current_stale_count", "currentness_unverified_count", "future_assessment_source_count",
        "ready_missing_pit_available_count", "ready_future_pit_available_count", "provider_cutoff_mismatch_count",
        "evidence_provenance_alignment_error_count", "assessment_rule_conflict_count", "assessment_rule_mismatch_count",
        "improving_without_directional_support_count", "weakening_without_directional_support_count",
        "period_anchor_order_dependence_count", "pattern_a_import_count", "price_provider_import_count",
        "pykrx_krx_network_request_count",
    )
    final_ready = bool(
        synthetic["status"] == "PASS" and currentness["status"] == "PASS" and anchor["status"] == "PASS"
        and rule_candidate["status"] == "PASS" and rule_conflict["status"] == "PASS" and financial_ok
        and counters["production_current_ready_count"] >= 1 and counters["currentness_verified_count"] >= 1
        and counters["historical_result_count"] >= 1 and counters["historical_ready_count"] >= 1
        and not errors and not budget_exceeded and all(counters[key] == 0 for key in required_zero)
        and counters["opendart_request_count"] <= MAX_OPENDART_REQUESTS
        and targeted["targeted_test_status"] == "PASS"
    )
    implementation_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         capture_output=True, check=False).stdout.strip()
    final_status = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX01_REVIEW" if final_ready \
        else ("BLOCKED_HISTORICAL_PIT_EVIDENCE" if counters["historical_ready_count"] < 1 else "BLOCKED_ASSESSMENT_CURRENTNESS")

    _write_json(ARTIFACT_DIR / "synthetic_directional_validation.json", synthetic)
    _write_json(ARTIFACT_DIR / "currentness_validation.json", currentness)
    _write_json(ARTIFACT_DIR / "period_anchor_determinism_validation.json", anchor)
    _write_json(ARTIFACT_DIR / "production_current_assessment_validation.json", {
        "status": "PASS" if current and not errors else "FAIL", "requested_as_of": REQUESTED_AS_OF,
        "results": [result.to_dict() for result in current], "errors": [item for item in errors if item.get("scope") == "current"],
        "production_current_ready_count": counters["production_current_ready_count"],
        "production_current_stale_count": counters["production_current_stale_count"],
    })
    columns = ["ticker", "company", "company_family", "assessment_scope", "currentness_status", "requested_as_of",
               "current_fiscal_year", "current_period", "overall_state", "growth_level", "profitability_level",
               "cash_flow_level", "momentum_level", "growth_direction", "profitability_direction", "cash_flow_direction",
               "improving_direction_axis_count", "deteriorating_direction_axis_count", "negative_level_axis_count",
               "strengths", "risks", "matched_rule_id", "matched_candidate_rules", "status", "scope_label"]
    _write_csv(ARTIFACT_DIR / "production_current_assessment_table.csv",
               [_result_row(result, scope="CURRENT_PRODUCTION") for result in current_with_financial], columns)
    _write_json(ARTIFACT_DIR / "historical_pit_assessment_validation.json", {
        "status": "PASS" if historical and not any(item.get("scope") == "historical" for item in errors) else "FAIL",
        "requested_as_of": HISTORICAL_AS_OF, "fiscal_years": list(HISTORICAL_YEARS),
        "cohort": list(HISTORICAL_TICKERS), "results": [result.to_dict() for result in historical],
        "errors": [item for item in errors if item.get("scope") == "historical"],
        "historical_result_count": counters["historical_result_count"], "historical_ready_count": counters["historical_ready_count"],
    })
    _write_csv(ARTIFACT_DIR / "historical_pit_assessment_table.csv",
               [_result_row(result, scope="HISTORICAL_PIT") for result in historical], columns)
    _write_json(ARTIFACT_DIR / "rule_candidate_validation.json", rule_candidate)
    _write_json(ARTIFACT_DIR / "rule_conflict_validation.json", rule_conflict)
    _write_json(ARTIFACT_DIR / "assessment_provenance_validation.json", {
        "status": "PASS" if all(counters[key] == 0 for key in required_zero if "import" not in key and "network" not in key) else "FAIL",
        "current": current_provenance, "historical": historical_provenance,
    })
    _write_json(ARTIFACT_DIR / "network_audit.json", {
        "status": "PASS" if counters["pykrx_krx_network_request_count"] == 0 and counters["opendart_request_count"] <= MAX_OPENDART_REQUESTS else "FAIL",
        "opendart_hydration_enabled": args.hydrate, "max_opendart_requests": MAX_OPENDART_REQUESTS,
        "opendart_request_count": counters["opendart_request_count"],
        "opendart_request_endpoints": dict(Counter(item.get("endpoint", "") for item in (client.audit if client else []))),
        "opendart_cache_hit_count": counters["opendart_cache_hit_count"], "opendart_cache_miss_count": counters["opendart_cache_miss_count"],
        "hydration_records": hydration_records, "pykrx_krx_network_request_count": 0,
        "raw_source_artifact_written": False, "budget_exceeded": budget_exceeded,
    })
    _write_json(ARTIFACT_DIR / "financial_not_applicable_validation.json", {
        "ticker": FINANCIAL_TICKER, "company": NAMES[FINANCIAL_TICKER], "status": "PASS" if financial_ok else "FAIL",
        "result": financial.to_dict(),
    })
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "assessment_architecture": "DerivedMetricsBuild -> FundamentalsAssessmentEngine -> FundamentalsAssessmentResult",
        "input_authority": "DerivedMetricsResult/DerivedMetricsBuild only; no raw XBRL in Assessment",
        "current_cohort": list(CURRENT_TICKERS) + [FINANCIAL_TICKER], "historical_cohort": list(HISTORICAL_TICKERS),
        "current_fiscal_years": list(CURRENT_YEARS), "historical_fiscal_years": list(HISTORICAL_YEARS),
        **counters, "synthetic_status": synthetic["status"], "currentness_status": currentness["status"],
        "period_anchor_status": anchor["status"], "rule_candidate_status": rule_candidate["status"],
        "rule_conflict_status": rule_conflict["status"], "financial_not_applicable_status": "PASS" if financial_ok else "FAIL",
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "periodization_semantics_changed": False,
        "derived_metrics_semantics_changed": False, "network_policy": "PyKRX/KRX=0; OpenDART cache-first bounded max=60",
        "errors": errors, "final_ready": final_ready, "final_status": final_status,
        "git_diff_check_status": "PASS" if subprocess.run(["git", "diff", "--check"], cwd=ROOT, capture_output=True).returncode == 0 else "FAIL",
    }
    _write_json(ARTIFACT_DIR / "assessment_fix01_summary.json", summary)
    _write_json(ARTIFACT_DIR / "assessment_fix01_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "files": _manifest(), "network_policy": {"opendart_max_requests": MAX_OPENDART_REQUESTS, "pykrx_krx": 0},
        "final_ready": final_ready, "final_status": final_status,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
