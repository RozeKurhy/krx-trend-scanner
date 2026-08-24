#!/usr/bin/env python3
"""Assessment V01 FIX02 validation.

This validator keeps the Assessment boundary pure, expands the current
lookback to five fiscal years, and records same-period YoY/component evidence.
OpenDART is cache-first and bounded; PyKRX/KRX are never imported or called.
"""

from __future__ import annotations

import argparse
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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/assessment_v01_fix02"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_ASSESSMENT_V01_FIX02"
START_HEAD = "4e588516fc1dc6f598ba186b3b69f87ac0d76f97"
REQUESTED_AS_OF = "2026-08-20"
HISTORICAL_AS_OF = "2024-02-15"
CURRENT_YEARS = ("2022", "2023", "2024", "2025", "2026")
HISTORICAL_YEARS = ("2022", "2023", "2024")
CURRENT_TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
HISTORICAL_TICKERS = ("005930", "000660", "068270")
FINANCIAL_TICKER = "086790"
MAX_OPENDART_REQUESTS = 80
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온",
    "012330": "현대모비스", "086790": "하나금융지주",
}

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import validate_opendart_fundamentals_assessment_v01_fix01 as fix01  # noqa: E402
from trend_scanner.fundamentals.assessment import FundamentalsAssessmentEngine  # noqa: E402
from trend_scanner.fundamentals.derived_metrics import DerivedMetricsResult  # noqa: E402
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsBuild  # noqa: E402
from trend_scanner.fundamentals.period_models import PeriodizationResult  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild  # noqa: E402


class RequestBudgetExceeded(RuntimeError):
    pass


class BoundedOpenDartClient80(fix01.OpenDartClient):
    def _check_budget(self) -> None:
        if len(self.audit) >= MAX_OPENDART_REQUESTS:
            raise RequestBudgetExceeded(
                f"OpenDART request budget {MAX_OPENDART_REQUESTS} reached; no retry was attempted"
            )

    def get_json(self, endpoint: str, params: dict[str, Any]):  # type: ignore[override]
        self._check_budget()
        return super().get_json(endpoint, params)

    def get_binary(self, endpoint: str, params: dict[str, Any]):  # type: ignore[override]
        self._check_budget()
        return super().get_binary(endpoint, params)


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
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _targeted_tests() -> dict[str, Any]:
    return fix01._run_targeted_tests()


def _bulk_hydrate_ticker(client: BoundedOpenDartClient80, corp, *, ticker: str,
                         years: tuple[str, ...], requested_as_of: str) -> dict[str, Any]:
    """Hydrate all missing regular-report caches for one ticker in one date window.

    The FIX01 helper queried the same filing registry window once per fiscal
    year.  FIX02 keeps the same cache contract but groups those lookups by
    ticker, which makes the explicit 80-request OpenDART budget meaningful.
    """
    record = corp.get_record(ticker)
    missing_by_year = {
        year: [code for code in fix01.REPORT_CODES if not fix01._cache_covers(
            fix01._cache_path(record.corp_code, year, code),
            required_start=f"{year}-01-01", requested_as_of=requested_as_of,
        )]
        for year in years
    }
    missing_by_year = {year: codes for year, codes in missing_by_year.items() if codes}
    if not missing_by_year:
        return {"ticker": ticker, "status": "CACHE_COVERED", "request_count": 0}

    bgn_de = f"{min(years)}0101"
    end_de = requested_as_of.replace("-", "")
    raw_rows: list[dict[str, Any]] = []
    responses: list[Any] = []
    page_no = 1
    total_page: int | None = None
    while True:
        response = client.list_filings(record.corp_code, bgn_de=bgn_de, end_de=end_de,
                                        page_no=page_no, page_count=100)
        responses.append(response)
        if response.http_status != 200 or response.status != "000":
            raise RuntimeError(f"OpenDART filing registry failed for {ticker}: status={response.status}")
        payload = response.payload if isinstance(response.payload, dict) else {}
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
            raise RuntimeError(f"OpenDART filing registry pagination exceeded for {ticker}")

    retrieved_at = datetime.now(timezone.utc).isoformat()
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw_rows:
        item = fix01.to_registered_filing(row, ticker=ticker, retrieved_at=retrieved_at)
        if item is not None and (item.bsns_year, item.reprt_code) in {
            (year, code) for year, codes in missing_by_year.items() for code in codes
        }:
            parsed.setdefault((item.bsns_year, item.reprt_code), {})[item.rcept_no] = item
    source_hash = hashlib.sha256(b"".join(response.raw for response in responses)).hexdigest()
    written: list[str] = []
    for year, codes in missing_by_year.items():
        for code in codes:
            rows = sorted(parsed.get((year, code), {}).values(), key=lambda item: (item.rcept_dt, item.rcept_no))
            metadata = {
                "source_provider": "OPENDART", "source_kind": "BOUNDED_CACHE_HYDRATION_BULK",
                "corp_code": record.corp_code, "ticker": ticker, "bsns_year": year, "reprt_code": code,
                "request_parameters": {"corp_code": record.corp_code, "bgn_de": bgn_de, "end_de": end_de},
                "request_window": {"bgn_de": bgn_de, "end_de": end_de},
                "coverage_start": f"{year}-01-01", "coverage_end": requested_as_of,
                "retrieved_at": retrieved_at, "page_count_requested": 100, "pages_fetched": len(responses),
                "total_count": len(raw_rows), "total_page": total_page or len(responses),
                "http_status": 200, "api_status": "000", "source_sha256": source_hash,
                "record_count": len(rows), "cache_complete": True, "cache_hit": False,
            }
            path = fix01._cache_path(record.corp_code, year, code)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"metadata": metadata, "filings": [row.to_dict() for row in rows]},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(f"{year}:{code}")
    return {"ticker": ticker, "status": "HYDRATED", "request_count": len(responses),
            "missing_cache_keys": written, "filing_count": sum(len(rows) for rows in parsed.values())}


def _hydrate_missing(client: BoundedOpenDartClient80, corp) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for ticker in CURRENT_TICKERS:
        records.append(_bulk_hydrate_ticker(
            client, corp, ticker=ticker, years=CURRENT_YEARS, requested_as_of=REQUESTED_AS_OF,
        ))
    # Current caches are stamped through REQUESTED_AS_OF, so they also satisfy
    # the historical PIT cutoff; no duplicate historical network request is made.
    return records


def _financial_control():
    dummy_period = PeriodizationBuild(
        ticker=FINANCIAL_TICKER, fiscal_year="2026", requested_as_of=REQUESTED_AS_OF,
        company_family="FINANCIAL", filings=(), facts=(), result=PeriodizationResult(()),
    )
    build = DerivedMetricsBuild(
        ticker=FINANCIAL_TICKER, requested_as_of=REQUESTED_AS_OF, fiscal_years=CURRENT_YEARS,
        periodization_builds=(dummy_period,), canonical_observations=(), result=DerivedMetricsResult(()),
    )
    return FundamentalsAssessmentEngine().assess(
        build, requested_as_of=REQUESTED_AS_OF, assessment_scope="CURRENT_AS_OF",
        expected_current_fiscal_year="2026",
    )


def _build_assessments(provider):
    current: list[Any] = []
    current_build_years: dict[str, tuple[str, ...]] = {}
    current_errors: list[dict[str, Any]] = []
    for ticker in CURRENT_TICKERS:
        try:
            build = provider.derived_metrics_provider.build(
                ticker, CURRENT_YEARS, REQUESTED_AS_OF,
                company_metadata=fix01._metadata(ticker), force_refresh=False,
            )
            current_build_years[ticker] = tuple(build.fiscal_years)
            current.append(provider.assessment_engine.assess(
                build, requested_as_of=REQUESTED_AS_OF, assessment_scope="CURRENT_AS_OF",
                expected_current_fiscal_year="2026",
            ))
        except Exception as exc:
            current_errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    historical: list[Any] = []
    historical_errors: list[dict[str, Any]] = []
    for ticker in HISTORICAL_TICKERS:
        try:
            build = provider.derived_metrics_provider.build(
                ticker, HISTORICAL_YEARS, HISTORICAL_AS_OF,
                company_metadata=fix01._metadata(ticker), force_refresh=False,
            )
            historical.append(provider.assessment_engine.assess(
                build, requested_as_of=HISTORICAL_AS_OF, assessment_scope="EXPLICIT_RANGE",
            ))
        except Exception as exc:
            historical_errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    return current, current_build_years, current_errors, historical, historical_errors


def _point_value(point: Any) -> str:
    return "" if point.yoy_value is None else str(point.yoy_value)


def _sequence(series: Any) -> str:
    return "|".join(f"{point.fiscal_year}{point.fiscal_period}:{_point_value(point)}" for point in series.points)


def _current_row(result: Any) -> dict[str, Any]:
    series = result.same_period_yoy_series
    def seq(metric: str) -> str:
        return _sequence(series[metric]) if metric in series else ""
    return {
        "ticker": result.ticker, "company": NAMES.get(result.ticker, ""),
        "company_family": result.company_family, "assessment_scope": result.assessment_scope,
        "currentness_status": result.currentness_status, "requested_as_of": result.requested_as_of,
        "current_fiscal_year": result.current_fiscal_year, "current_period": result.current_fiscal_period,
        "overall_state": result.overall_state,
        "growth_level": result.growth_state, "growth_direction": result.growth_direction,
        "growth_multi_year_trend": result.multi_year_trends.get("revenue", ""),
        "profitability_level": result.profitability_state, "profitability_direction": result.profitability_direction,
        "cash_flow_level": result.cash_flow_state, "cash_flow_direction": result.cash_flow_direction,
        "cash_flow_multi_year_trend": result.multi_year_trends.get("operating_cash_flow", ""),
        "momentum": result.momentum_state,
        "revenue_yoy_sequence": seq("revenue"), "operating_income_yoy_sequence": seq("operating_income"),
        "net_income_yoy_sequence": seq("net_income"), "ocf_yoy_sequence": seq("operating_cash_flow"),
        "strengths": "|".join(result.strengths), "risks": "|".join(result.risks),
        "matched_rule_id": result.matched_rule_id, "matched_candidate_rules": "|".join(result.matched_candidate_rules),
        "status": result.status,
    }


def _multi_year_rows(results: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for metric, series in sorted(result.same_period_yoy_series.items()):
            values = {point.fiscal_year: _point_value(point) for point in series.points}
            rows.append({
                "ticker": result.ticker, "company": NAMES.get(result.ticker, ""),
                "current_period": series.fiscal_period, "metric": metric,
                "yoy_2022": values.get("2022", ""), "yoy_2023": values.get("2023", ""),
                "yoy_2024": values.get("2024", ""), "yoy_2025": values.get("2025", ""),
                "yoy_2026": values.get("2026", ""),
                "usable_yoy_point_count": series.usable_yoy_point_count,
                "multi_year_trend": series.trend_state,
                "short_term_direction": result.short_term_directions.get(metric, "UNAVAILABLE"),
            })
    return rows


def _series_counters(results: Iterable[Any], expected_years: tuple[str, ...]) -> dict[str, int]:
    counters = Counter()
    for result in results:
        for metric, series in result.same_period_yoy_series.items():
            expected_type = "ANNUAL_YOY" if series.fiscal_period == "FY" else "QUARTERLY_YOY"
            if len(series.points) != len(expected_years) or any(
                point.fiscal_period != series.fiscal_period or point.metric_type != expected_type
                for point in series.points
            ):
                counters["same_period_series_mismatch_count"] += 1
            years = [int(value) for value in series.contiguous_fiscal_years]
            if any(right != left + 1 for left, right in zip(years, years[1:])):
                counters["non_contiguous_series_wrongly_used_count"] += 1
            recomputed = FundamentalsAssessmentEngine._multi_year_trend(
                tuple(point for point in series.points
                      if point.fiscal_year in series.contiguous_fiscal_years)
            )
            if recomputed != series.trend_state:
                counters["multi_year_trend_mismatch_count"] += 1
            if series.usable_yoy_point_count >= 3:
                counters["multi_year_yoy_series_ready_count"] += 1
            if series.trend_state != "INSUFFICIENT_DATA":
                counters["multi_year_trend_ready_count"] += 1
    return {key: int(value) for key, value in counters.items()}


def _provenance(results: Iterable[Any], cutoff: str) -> dict[str, int]:
    counters = Counter(fix01._provenance_counts(results, cutoff))
    cutoff_date = date.fromisoformat(cutoff)
    for result in results:
        for series in result.same_period_yoy_series.values():
            for point in series.points:
                if point.resolution_status != "READY":
                    continue
                pit = point.pit_available_from
                if not pit:
                    counters["ready_missing_pit_available_count"] += 1
                else:
                    try:
                        if date.fromisoformat(pit[:10]) > cutoff_date:
                            counters["ready_future_pit_available_count"] += 1
                    except ValueError:
                        counters["evidence_provenance_alignment_error_count"] += 1
                if not (len(point.source_rcept_nos) == len(point.source_rcept_dts) == len(point.source_sha256s)):
                    counters["evidence_provenance_alignment_error_count"] += 1
                for source_dt in point.source_rcept_dts:
                    try:
                        if source_dt and date.fromisoformat(source_dt[:10]) > cutoff_date:
                            counters["future_assessment_source_count"] += 1
                    except ValueError:
                        counters["evidence_provenance_alignment_error_count"] += 1
    return {key: int(value) for key, value in counters.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hydrate", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    fix01._load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    targeted = _targeted_tests()
    client = BoundedOpenDartClient80(api_key=key) if args.hydrate and key else None
    hydration_records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    budget_exceeded = False
    if args.hydrate and not key:
        errors.append({"scope": "network", "error_type": "MISSING_OPENDART_API_KEY"})
    provider, corp, filings, xbrl = fix01._make_provider(client)
    hydration_request_count = 0
    hydration_audit: list[dict[str, Any]] = []
    if client is not None:
        try:
            corp.ensure_loaded()
            hydration_records = _hydrate_missing(client, corp)
            # Warm all XBRL artifacts needed by the cohorts while the bounded
            # client is active.  The actual assessment replay below is
            # deliberately rebuilt from a client-less provider.
            warm_current, _, warm_current_errors, warm_historical, warm_historical_errors = _build_assessments(provider)
            warm_errors = warm_current_errors + warm_historical_errors
            if any(item.get("error_type") == "RequestBudgetExceeded" for item in warm_errors):
                budget_exceeded = True
                errors.extend({"scope": "hydration_warmup", **item} for item in warm_errors
                              if item.get("error_type") == "RequestBudgetExceeded")
            hydration_records.append({
                "stage": "XBRL_WARMUP", "current_error_count": len(warm_current_errors),
                "historical_error_count": len(warm_historical_errors),
                "current_result_count": len(warm_current), "historical_result_count": len(warm_historical),
            })
            hydration_request_count = len(client.audit)
            hydration_audit = list(client.audit)
        except RequestBudgetExceeded as exc:
            budget_exceeded = True
            hydration_request_count = len(client.audit)
            errors.append({"scope": "hydration", "error_type": type(exc).__name__, "message": str(exc)})
            hydration_audit = list(client.audit)
        except Exception as exc:
            hydration_request_count = len(client.audit)
            errors.append({"scope": "hydration", "error_type": type(exc).__name__, "message": str(exc)})
            hydration_audit = list(client.audit)
        finally:
            client.audit.clear()
        # Never let the final replay issue a request after the bounded
        # hydration phase, including after a budget exception.
        provider, corp, filings, xbrl = fix01._make_provider(None)

    current, current_build_years, current_errors, historical, historical_errors = _build_assessments(provider)
    errors.extend({"scope": "current", **item} for item in current_errors)
    errors.extend({"scope": "historical", **item} for item in historical_errors)
    financial = _financial_control()
    current_all = current + [financial]
    all_results = tuple(current_all) + tuple(historical)
    current_prov = _provenance(current_all, REQUESTED_AS_OF)
    historical_prov = _provenance(historical, HISTORICAL_AS_OF)
    series_counts = _series_counters(current, CURRENT_YEARS)
    dependency_pattern_count, dependency_price_count = fix01._dependency_counts()
    final_replay_request_count = len(client.audit) if client is not None else 0

    level_contamination = sum(int(result.diagnostics.get("level_contaminated_by_direction_count", 0)) for result in all_results)
    direction_contamination = sum(int(result.diagnostics.get("direction_contaminated_by_level_count", 0)) for result in all_results)
    overwrite_count = sum(int(result.diagnostics.get("direction_component_overwrite_count", 0)) for result in all_results)
    order_dependence = sum(int(result.diagnostics.get("direction_order_dependence_count", 0)) for result in all_results)
    positive_streak_count = sum(int(result.diagnostics.get("positive_streak_used_as_improvement_count", 0)) for result in all_results)
    current_yoy_sign_count = sum(int(result.diagnostics.get("current_yoy_sign_used_as_direction_count", 0)) for result in all_results)
    ttm_yoy_sign_count = sum(int(result.diagnostics.get("ttm_yoy_sign_used_as_direction_count", 0)) for result in all_results)
    current_production_ready = sum(result.status == "READY" for result in current)
    historical_result_count = len(historical)
    historical_ready_count = sum(result.status == "READY" for result in historical)
    financial_ok = financial.status == "NOT_APPLICABLE" and financial.currentness_status == "VERIFIED"

    counters = {
        "five_year_window_error_count": int(len(current_build_years) != len(CURRENT_TICKERS)) +
        sum(int(years != CURRENT_YEARS) for years in current_build_years.values()),
        "same_period_series_mismatch_count": series_counts.get("same_period_series_mismatch_count", 0),
        "non_contiguous_series_wrongly_used_count": series_counts.get("non_contiguous_series_wrongly_used_count", 0),
        "multi_year_trend_mismatch_count": series_counts.get("multi_year_trend_mismatch_count", 0),
        "level_contaminated_by_direction_count": level_contamination,
        "direction_contaminated_by_level_count": direction_contamination,
        "direction_component_overwrite_count": overwrite_count,
        "direction_order_dependence_count": order_dependence,
        "positive_streak_used_as_improvement_count": positive_streak_count,
        "current_yoy_sign_used_as_direction_count": current_yoy_sign_count,
        "ttm_yoy_sign_used_as_direction_count": ttm_yoy_sign_count,
        "improving_without_directional_support_count": current_prov.get("improving_without_directional_support_count", 0) + historical_prov.get("improving_without_directional_support_count", 0),
        "weakening_without_directional_support_count": current_prov.get("weakening_without_directional_support_count", 0) + historical_prov.get("weakening_without_directional_support_count", 0),
        "assessment_rule_conflict_count": current_prov.get("assessment_rule_conflict_count", 0) + historical_prov.get("assessment_rule_conflict_count", 0),
        "assessment_rule_mismatch_count": current_prov.get("assessment_rule_mismatch_count", 0) + historical_prov.get("assessment_rule_mismatch_count", 0),
        "future_assessment_source_count": current_prov.get("future_assessment_source_count", 0) + historical_prov.get("future_assessment_source_count", 0),
        "ready_future_pit_available_count": current_prov.get("ready_future_pit_available_count", 0) + historical_prov.get("ready_future_pit_available_count", 0),
        "ready_missing_pit_available_count": current_prov.get("ready_missing_pit_available_count", 0) + historical_prov.get("ready_missing_pit_available_count", 0),
        "provider_cutoff_mismatch_count": current_prov.get("provider_cutoff_mismatch_count", 0) + historical_prov.get("provider_cutoff_mismatch_count", 0),
        "evidence_provenance_alignment_error_count": current_prov.get("evidence_provenance_alignment_error_count", 0) + historical_prov.get("evidence_provenance_alignment_error_count", 0),
        "historical_result_count": historical_result_count,
        "historical_ready_count": historical_ready_count,
        "production_current_ready_count": current_production_ready,
        "multi_year_yoy_series_ready_count": series_counts.get("multi_year_yoy_series_ready_count", 0),
        "multi_year_trend_ready_count": series_counts.get("multi_year_trend_ready_count", 0),
        "opendart_hydration_request_count": hydration_request_count,
        "opendart_final_replay_request_count": final_replay_request_count,
        "opendart_cache_hit_count": int(getattr(corp, "cache_hit", False)) + filings.cache_hits + xbrl.cache_hits,
        "opendart_cache_miss_count": (0 if getattr(corp, "cache_hit", False) else int(client is not None)) + filings.cache_misses + xbrl.cache_misses,
        "pykrx_krx_network_request_count": 0,
    }
    required_zero = tuple(key for key in counters if key.endswith("_count") and key not in {
        "historical_result_count", "historical_ready_count", "production_current_ready_count",
        "multi_year_yoy_series_ready_count", "multi_year_trend_ready_count",
        "opendart_hydration_request_count", "opendart_final_replay_request_count",
        "opendart_cache_hit_count", "opendart_cache_miss_count",
    })
    final_ready = bool(
        not errors and not budget_exceeded and targeted["targeted_test_status"] == "PASS"
        and current_production_ready >= 1 and historical_result_count >= 1 and historical_ready_count >= 1
        and counters["multi_year_yoy_series_ready_count"] >= 1 and counters["multi_year_trend_ready_count"] >= 1
        and financial_ok and all(counters[key] == 0 for key in required_zero)
        and final_replay_request_count == 0 and hydration_request_count <= MAX_OPENDART_REQUESTS
        and dependency_pattern_count == 0 and dependency_price_count == 0
    )
    implementation_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         capture_output=True, check=False).stdout.strip()
    final_status = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX02_REVIEW" if final_ready else (
        "BLOCKED_NETWORK_BUDGET_EXCEEDED" if budget_exceeded else "BLOCKED_ASSESSMENT_FIX02_VALIDATION"
    )

    current_columns = ["ticker", "company", "company_family", "assessment_scope", "currentness_status",
                       "requested_as_of", "current_fiscal_year", "current_period", "overall_state",
                       "growth_level", "growth_direction", "growth_multi_year_trend", "profitability_level",
                       "profitability_direction", "cash_flow_level", "cash_flow_direction",
                       "cash_flow_multi_year_trend", "momentum", "revenue_yoy_sequence",
                       "operating_income_yoy_sequence", "net_income_yoy_sequence", "ocf_yoy_sequence",
                       "strengths", "risks", "matched_rule_id", "matched_candidate_rules", "status"]
    _write_json(ARTIFACT_DIR / "five_year_window_validation.json", {
        "status": "PASS" if not counters["five_year_window_error_count"] else "FAIL",
        "expected_years": list(CURRENT_YEARS), "build_years": current_build_years,
    })
    _write_json(ARTIFACT_DIR / "multi_year_yoy_trend_validation.json", {
        "status": "PASS" if counters["multi_year_trend_mismatch_count"] == 0 else "FAIL",
        "results": [{"ticker": result.ticker, "series": {
            metric: series.to_dict() for metric, series in result.same_period_yoy_series.items()
        }} for result in current],
        "multi_year_yoy_series_ready_count": counters["multi_year_yoy_series_ready_count"],
        "multi_year_trend_ready_count": counters["multi_year_trend_ready_count"],
    })
    _write_json(ARTIFACT_DIR / "level_direction_separation_validation.json", {
        "status": "PASS" if counters["level_contaminated_by_direction_count"] == 0 and counters["direction_contaminated_by_level_count"] == 0 else "FAIL",
        "level_contaminated_by_direction_count": counters["level_contaminated_by_direction_count"],
        "direction_contaminated_by_level_count": counters["direction_contaminated_by_level_count"],
    })
    _write_json(ARTIFACT_DIR / "direction_component_validation.json", {
        "status": "PASS" if all(counters[key] == 0 for key in (
            "direction_component_overwrite_count", "positive_streak_used_as_improvement_count",
            "current_yoy_sign_used_as_direction_count", "ttm_yoy_sign_used_as_direction_count",
        )) else "FAIL",
        "results": [{"ticker": result.ticker, "direction_components": {
            axis: [item.to_dict() for item in items]
            for axis, items in result.direction_components.items()
        }} for result in current],
    })
    _write_json(ARTIFACT_DIR / "direction_order_invariance_validation.json", {
        "status": "PASS" if counters["direction_order_dependence_count"] == 0 else "FAIL",
        "direction_order_dependence_count": counters["direction_order_dependence_count"],
        "direction_component_overwrite_count": counters["direction_component_overwrite_count"],
    })
    _write_json(ARTIFACT_DIR / "production_current_assessment_validation.json", {
        "status": "PASS" if current and not current_errors else "FAIL",
        "requested_as_of": REQUESTED_AS_OF, "results": [result.to_dict() for result in current],
        "errors": current_errors, "production_current_ready_count": current_production_ready,
    })
    _write_csv(ARTIFACT_DIR / "production_current_assessment_table.csv",
               [_current_row(result) for result in current_all], current_columns)
    _write_csv(ARTIFACT_DIR / "production_multi_year_yoy_table.csv", _multi_year_rows(current), [
        "ticker", "company", "current_period", "metric", "yoy_2022", "yoy_2023", "yoy_2024",
        "yoy_2025", "yoy_2026", "usable_yoy_point_count", "multi_year_trend", "short_term_direction",
    ])
    _write_json(ARTIFACT_DIR / "historical_pit_regression.json", {
        "status": "PASS" if historical and not historical_errors else "FAIL",
        "requested_as_of": HISTORICAL_AS_OF, "fiscal_years": list(HISTORICAL_YEARS),
        "cohort": list(HISTORICAL_TICKERS), "results": [result.to_dict() for result in historical],
        "errors": historical_errors,
    })
    _write_json(ARTIFACT_DIR / "assessment_provenance_validation.json", {
        "status": "PASS" if all(counters[key] == 0 for key in (
            "future_assessment_source_count", "ready_future_pit_available_count",
            "ready_missing_pit_available_count", "provider_cutoff_mismatch_count",
            "evidence_provenance_alignment_error_count")) else "FAIL",
        "current": current_prov, "historical": historical_prov,
    })
    _write_json(ARTIFACT_DIR / "network_audit.json", {
        "status": "PASS" if hydration_request_count <= MAX_OPENDART_REQUESTS and final_replay_request_count == 0 and not budget_exceeded else "FAIL",
        "max_opendart_requests": MAX_OPENDART_REQUESTS,
        "hydration_run_request_count": hydration_request_count,
        "final_replay_request_count": final_replay_request_count,
        "cache_hit_count": counters["opendart_cache_hit_count"],
        "cache_miss_count": counters["opendart_cache_miss_count"],
        "hydration_records": hydration_records, "budget_exceeded": budget_exceeded,
        "pykrx_krx_network_request_count": 0,
        "opendart_request_endpoints": dict(Counter(item.get("endpoint", "") for item in hydration_audit)),
    })
    _write_json(ARTIFACT_DIR / "financial_not_applicable_validation.json", {
        "ticker": FINANCIAL_TICKER, "company": NAMES[FINANCIAL_TICKER],
        "status": "PASS" if financial_ok else "FAIL", "result": financial.to_dict(),
    })
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "assessment_architecture": "DerivedMetricsBuild -> pure level selectors + direction components -> FundamentalsAssessmentResult",
        "current_default_fiscal_years": list(CURRENT_YEARS), "historical_fiscal_years": list(HISTORICAL_YEARS),
        "current_cohort": list(CURRENT_TICKERS) + [FINANCIAL_TICKER], "historical_cohort": list(HISTORICAL_TICKERS),
        **counters, "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "pattern_a_import_count": dependency_pattern_count,
        "price_provider_import_count": dependency_price_count, "errors": errors,
        "financial_not_applicable_count": int(financial_ok), "final_ready": final_ready,
        "final_status": final_status, "git_diff_check_status": "PASS" if subprocess.run(
            ["git", "diff", "--check"], cwd=ROOT, capture_output=True
        ).returncode == 0 else "FAIL",
    }
    _write_json(ARTIFACT_DIR / "assessment_fix02_summary.json", summary)
    files = {path.name: _sha(path) for path in sorted(ARTIFACT_DIR.iterdir())
             if path.is_file() and path.name != "assessment_fix02_manifest.json"}
    _write_json(ARTIFACT_DIR / "assessment_fix02_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "files": files, "network_policy": {"opendart_max_requests": MAX_OPENDART_REQUESTS, "pykrx_krx": 0},
        "final_ready": final_ready, "final_status": final_status,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
