"""Bounded F6 representative/negative validation for Fundamentals V1.

This harness consumes only local synthetic F2/F3/F4 results and the local
Stock Report generator.  It never hydrates fundamentals or calls a provider.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft7Validator

# The script is also invoked directly (`uv run python scripts/...`), where
# Python puts `scripts/` rather than the repository root on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_stock_report_v05_fundamentals import _f3_observation, _inputs
from trend_scanner.fundamentals.derived_metrics import (
    BASIS_MISMATCH,
    CURRENCY_MISMATCH,
    DerivedMetricObservation,
    DerivedMetricsResult,
)
from trend_scanner.fundamentals.fundamentals_filter import (
    FILTERED_NET_LOSS,
    FundamentalsFilter,
    FundamentalsFilterResult,
    NOT_APPLICABLE as FILTER_NOT_APPLICABLE,
    PASS as FILTER_PASS,
)
from trend_scanner.fundamentals.period_models import PERIOD_AMBIGUOUS
from trend_scanner.reporting.fundamentals_report import (
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    build_fundamentals_section,
)
from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report


ARTIFACT_DIR = ROOT / "artifacts/fundamentals/validation/f6_representative_validation"
SCHEMA_PATH = ROOT / "docs/reporting/stock_report/schema_v05.json"
AS_OF = "2026-06-30"


def _fresh() -> tuple[Any, Any, FundamentalsFilterResult]:
    return _inputs()


def _clone_f3(item: Any, **changes: Any) -> DerivedMetricObservation:
    """Clone the slot-based F3 observation with one identity override."""
    return DerivedMetricObservation(
        changes.get("ticker", item.ticker),
        changes.get("corp_code", item.corp_code),
        changes.get("company_family", item.company_family),
        changes.get("fiscal_year", item.fiscal_year),
        changes.get("fiscal_period", item.fiscal_period),
        changes.get("metric", item.metric),
        changes.get("metric_type", item.metric_type),
        changes.get("value", item.value),
        unit=changes.get("unit", item.unit),
        resolution_status=changes.get("resolution_status", item.resolution_status),
        reason=changes.get("reason", item.reason),
        period_end=changes.get("period_end", item.period_end),
        source_rcept_nos=changes.get("source_rcept_nos", item.source_rcept_nos),
        source_rcept_dts=changes.get("source_rcept_dts", item.source_rcept_dts),
        source_sha256s=changes.get("source_sha256s", item.source_sha256s),
        requested_as_of=changes.get("requested_as_of", item.requested_as_of),
        pit_available_from=changes.get("pit_available_from", item.pit_available_from),
        metadata=changes.get("metadata", item.metadata),
    )


def _section(f2: Any, f3: Any, f4: Any, *, asset_type: str = "COMMON") -> Any:
    return build_fundamentals_section(f2, f3, f4, AS_OF, asset_type)


def _evaluate_f4(f2: Any, f3: Any) -> FundamentalsFilterResult:
    """Run the production F4 evaluator over the local synthetic F2/F3 inputs."""
    return FundamentalsFilter().evaluate(f2, f3, requested_as_of=AS_OF)


def _normal_f4_inputs() -> tuple[Any, Any, FundamentalsFilterResult]:
    f2, f3, _ = _fresh()
    return f2, f3, _evaluate_f4(f2, f3)


def _filtered_f4_inputs() -> tuple[Any, Any, FundamentalsFilterResult]:
    f2, f3, _ = _fresh()
    # Change only the target F3 observations.  F4 must derive the filtered
    # status and its numeric evidence itself; no F4 result mutation is allowed.
    f3.observations = tuple(
        _clone_f3(item, value=-1_000_000_000)
        if item.metric == "net_income" and item.metric_type == "TTM" and item.fiscal_year == "2026" and item.fiscal_period == "Q2"
        else _clone_f3(item, value=-1.25)
        if item.metric == "net_income" and item.metric_type == "TTM_NET_MARGIN" and item.fiscal_year == "2026" and item.fiscal_period == "Q2"
        else item
        for item in f3.observations
    )
    return f2, f3, _evaluate_f4(f2, f3)


def _financial_f4_inputs() -> tuple[Any, Any, FundamentalsFilterResult]:
    f2, f3, _ = _fresh()
    f2.company_family = "FINANCIAL"
    f2.quarters = tuple(replace(item, company_family="FINANCIAL") for item in f2.quarters)
    f2.annuals = tuple(replace(item, company_family="FINANCIAL") for item in f2.annuals)
    f3.observations = tuple(_clone_f3(item, company_family="FINANCIAL") for item in f3.observations)
    return f2, f3, _evaluate_f4(f2, f3)


def _f4_evidence(result: FundamentalsFilterResult) -> dict[str, Any]:
    return {
        "actual_f4_status": result.status,
        "actual_f4_passed": result.passed,
        "actual_f4_ttm_net_income": result.ttm_net_income,
        "actual_f4_company_family": result.company_family,
    }


def _case01() -> Any:
    f2, f3, f4 = _normal_f4_inputs()
    return _section(f2, f3, f4)


def _case02() -> Any:
    f2, f3, f4 = _filtered_f4_inputs()
    return _section(f2, f3, f4)


def _case03() -> Any:
    f2, f3, f4 = _financial_f4_inputs()
    return _section(f2, f3, f4)


def _case04() -> Any:
    return build_fundamentals_section(None, None, None, AS_OF, "ETF")


def _case05() -> Any:
    return build_fundamentals_section(None, None, None, AS_OF, "COMMON")


def _case06() -> Any:
    f2, f3, f4 = _fresh()
    f2.quarters = tuple(
        item for item in f2.quarters
        if not (item.metric == "revenue" and item.fiscal_year == "2025" and item.fiscal_period == "Q2")
    )
    return _section(f2, f3, f4)


def _case07() -> Any:
    f2, f3, f4 = _fresh()
    f2.annuals = tuple(
        item for item in f2.annuals
        if not (item.metric == "revenue" and item.fiscal_year == "2023")
    )
    return _section(f2, f3, f4)


def _case08() -> Any:
    f2, f3, f4 = _fresh()
    f3.observations = f3.observations + (
        _f3_observation("revenue", "TTM", 2026, "Q2", 81_000_000_000, requested_as_of="2026-03-31"),
    )
    return _section(f2, f3, f4)


def _case09() -> Any:
    f2, f3, f4 = _fresh()
    f3.observations = f3.observations + (
        _f3_observation("revenue", "TTM", 2026, "Q3", 999, ticker="OTHER", requested_as_of="2027-01-01"),
    )
    return _section(f2, f3, f4)


def _case10() -> Any:
    f2, f3, f4 = _fresh()
    return _section(f2, f3, replace(f4, ticker="OTHER"))


def _case11() -> Any:
    f2, f3, f4 = _fresh()
    f3.observations = tuple(
        item for item in f3.observations
        if not (item.fiscal_year == "2026" and item.fiscal_period == "Q2" and item.metric_type.startswith("TTM"))
    )
    # A newer endpoint is intentionally present: the adapter must not fall
    # forward from F4.latest_quarter=2026Q2 to 2026Q3.
    f3.observations = f3.observations + (
        _f3_observation("operating_income", "TTM", 2026, "Q3", 9_000_000_000),
        _f3_observation("net_income", "TTM", 2026, "Q3", 7_000_000_000),
    )
    return _section(f2, f3, f4)


def _case12() -> Any:
    f2, f3, f4 = _fresh()
    target = next(item for item in f2.quarters if item.metric == "revenue" and item.fiscal_year == "2025" and item.fiscal_period == "Q2")
    f2.quarters = tuple(
        replace(item, resolution_status=PERIOD_AMBIGUOUS, reason="F6_AMBIGUOUS") if item is target else item
        for item in f2.quarters
    )
    return _section(f2, f3, f4)


_EXPECTED_CASES: dict[str, dict[str, Any]] = {
    "CASE 01 — NORMAL PASS": {"status": "READY", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 02 — FILTERED": {"status": "READY", "filter_status": "FILTERED_NET_LOSS", "passed": False, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 03 — FINANCIAL": {"status": "NOT_APPLICABLE", "filter_status": "NOT_APPLICABLE", "passed": False, "asset_type": "COMMON", "company_family": "FINANCIAL"},
    "CASE 04 — ETF/NON-COMMON": {"status": "NOT_APPLICABLE", "filter_status": "NOT_APPLICABLE", "passed": False, "asset_type": "ETF", "company_family": "N/A"},
    "CASE 05 — INPUT ABSENT": {"status": "DATA_UNAVAILABLE", "filter_status": "DATA_UNAVAILABLE", "passed": False, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 06 — QUARTER GAP": {"status": "PARTIAL", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 07 — ANNUAL GAP": {"status": "PARTIAL", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 08 — AS_OF MISMATCH": {"status": "DATA_UNAVAILABLE", "filter_status": "DATA_UNAVAILABLE", "passed": False, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 09 — OTHER TICKER": {"status": "READY", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 10 — IDENTITY MISMATCH": {"status": "DATA_UNAVAILABLE", "filter_status": "DATA_UNAVAILABLE", "passed": False, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 11 — TTM ENDPOINT MISSING": {"status": "DATA_UNAVAILABLE", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
    "CASE 12 — AMBIGUITY/BASIS/CURRENCY": {"status": "PARTIAL", "filter_status": "PASS", "passed": True, "asset_type": "COMMON", "company_family": "NON_FINANCIAL"},
}


def _validate_section(case_id: str, section: Any) -> dict[str, Any]:
    expected = _EXPECTED_CASES[case_id]
    assert section.data_status == expected["status"], (case_id, section.data_status, expected["status"])
    assert section.filter_status == expected["filter_status"], (case_id, section.filter_status, expected["filter_status"])
    assert section.filter_passed is expected["passed"], (case_id, section.filter_passed, expected["passed"])
    row = {
        "case_id": case_id,
        "expected_status": expected["status"],
        "expected_filter_status": expected["filter_status"],
        "expected_passed": expected["passed"],
        "asset_type": expected["asset_type"],
        "company_family": expected["company_family"],
        "actual_status": section.data_status,
        "actual_filter_status": section.filter_status,
        "actual_passed": section.filter_passed,
        "actual_f4_status": None,
        "actual_f4_passed": None,
        "actual_f4_ttm_net_income": None,
        "actual_f4_company_family": None,
        # Report-level validation is populated only for the five selected
        # representative outputs below.  The remaining matrix cases are
        # section-only and must not be reported as if a report was rendered.
        "json_schema_valid": None,
        "markdown_valid": None,
        "summary_fundamentals_consistent": None,
        "as_of_consistent": None,
        "non_integration_guard": None,
        "result": "PASS",
        "reason": section.reason or "",
    }
    return row


def _assert_case_matrix(f4_results: dict[str, FundamentalsFilterResult]) -> list[dict[str, Any]]:
    cases: list[tuple[str, Callable[[], Any]]] = [
        ("CASE 01 — NORMAL PASS", _case01),
        ("CASE 02 — FILTERED", _case02),
        ("CASE 03 — FINANCIAL", _case03),
        ("CASE 04 — ETF/NON-COMMON", _case04),
        ("CASE 05 — INPUT ABSENT", _case05),
        ("CASE 06 — QUARTER GAP", _case06),
        ("CASE 07 — ANNUAL GAP", _case07),
        ("CASE 08 — AS_OF MISMATCH", _case08),
        ("CASE 09 — OTHER TICKER", _case09),
        ("CASE 10 — IDENTITY MISMATCH", _case10),
        ("CASE 11 — TTM ENDPOINT MISSING", _case11),
        ("CASE 12 — AMBIGUITY/BASIS/CURRENCY", _case12),
    ]
    sections = [(name, builder()) for name, builder in cases]
    results: list[dict[str, Any]] = []

    s = sections[0][1]
    assert s.applicability == "APPLICABLE" and s.data_status == "READY"
    assert s.filter_status == "PASS" and s.filter_passed is True
    f4 = f4_results["CASE 01 — NORMAL PASS"]
    assert f4.status == FILTER_PASS and f4.passed is True
    assert f4.ttm_net_income == 6_000_000_000
    assert [row.quarter for row in s.quarterly] == [
        "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4",
        "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2",
    ]
    assert [row.fiscal_year for row in s.annual] == ["2021", "2022", "2023", "2024", "2025"]
    assert s.summary.ttm_operating_income_krw == 8_000_000_000
    assert s.summary.ttm_net_income_krw == 6_000_000_000
    results.append(_validate_section("CASE 01 — NORMAL PASS", s))

    s = sections[1][1]
    assert s.data_status == "READY" and s.filter_status == "FILTERED_NET_LOSS" and s.filter_passed is False
    f4 = f4_results["CASE 02 — FILTERED"]
    assert f4.status == FILTERED_NET_LOSS and f4.passed is False
    assert f4.ttm_net_income == -1_000_000_000 and f4.ttm_net_income <= 0
    assert s.summary.ttm_net_income_krw == -1_000_000_000 and s.summary.ttm_net_income_krw <= 0
    results.append(_validate_section("CASE 02 — FILTERED", s))

    s = sections[2][1]
    assert s.applicability == NOT_APPLICABLE and s.data_status == NOT_APPLICABLE
    assert s.filter_status == FILTER_NOT_APPLICABLE and s.filter_passed is False
    f4 = f4_results["CASE 03 — FINANCIAL"]
    assert f4.company_family == "FINANCIAL"
    assert f4.status == FILTER_NOT_APPLICABLE and f4.passed is False
    assert all(
        getattr(s.summary, field) is None
        for field in (
            "latest_fy_revenue_krw", "latest_4q_avg_revenue_krw", "ttm_revenue_krw",
            "ttm_operating_income_krw", "ttm_net_income_krw", "ttm_operating_cash_flow_krw",
            "ttm_operating_margin_pct", "ttm_net_margin_pct",
            "ttm_operating_cash_flow_margin_pct", "ttm_roe_pct", "latest_debt_ratio_pct",
        )
    )
    results.append(_validate_section("CASE 03 — FINANCIAL", s))

    s = sections[3][1]
    assert s.applicability == NOT_APPLICABLE and s.data_status == NOT_APPLICABLE and s.filter_passed is False
    results.append(_validate_section("CASE 04 — ETF/NON-COMMON", s))

    s = sections[4][1]
    assert s.applicability == "APPLICABLE" and s.data_status == DATA_UNAVAILABLE
    assert s.reason == "FUNDAMENTALS_INPUT_NOT_PROVIDED"
    results.append(_validate_section("CASE 05 — INPUT ABSENT", s))

    s = sections[5][1]
    gap = next(row for row in s.quarterly if row.quarter == "2025Q2")
    assert len(s.quarterly) == 12 and gap.revenue_krw is None and gap.status != "READY"
    results.append(_validate_section("CASE 06 — QUARTER GAP", s))

    s = sections[6][1]
    gap = next(row for row in s.annual if row.fiscal_year == "2023")
    assert len(s.annual) == 5 and gap.revenue_krw is None and gap.status != "READY"
    results.append(_validate_section("CASE 07 — ANNUAL GAP", s))

    s = sections[7][1]
    assert s.data_status == DATA_UNAVAILABLE and s.reason == "AS_OF_MISMATCH"
    assert s.filter_status == DATA_UNAVAILABLE and s.filter_passed is False
    results.append(_validate_section("CASE 08 — AS_OF MISMATCH", s))

    s = sections[8][1]
    assert s.data_status == "READY" and s.summary.ttm_revenue_krw == 80_000_000_000
    results.append(_validate_section("CASE 09 — OTHER TICKER", s))

    s = sections[9][1]
    assert s.data_status == DATA_UNAVAILABLE and s.reason == "IDENTITY_MISMATCH"
    assert s.filter_passed is False and s.diagnostics
    # Corp-code and company-family mismatches are also fail-closed representatives.
    f2, f3, f4 = _fresh()
    corp_mismatch = DerivedMetricsResult(
        tuple(_clone_f3(item, corp_code="99999999") for item in f3.observations)
    )
    corp_section = _section(f2, corp_mismatch, f4)
    assert corp_section.data_status == DATA_UNAVAILABLE and corp_section.diagnostics
    f2.company_family = "FINANCIAL"
    family_section = _section(f2, f3, f4)
    assert family_section.data_status == DATA_UNAVAILABLE and family_section.reason == "IDENTITY_MISMATCH"
    results.append(_validate_section("CASE 10 — IDENTITY MISMATCH", s))

    s = sections[10][1]
    assert s.data_status == DATA_UNAVAILABLE
    assert s.summary.ttm_operating_income_krw is None and s.summary.ttm_net_income_krw is None
    results.append(_validate_section("CASE 11 — TTM ENDPOINT MISSING", s))

    s = sections[11][1]
    gap = next(row for row in s.quarterly if row.quarter == "2025Q2")
    assert gap.revenue_krw is None and gap.status == DATA_UNAVAILABLE
    # The same adapter path treats basis/currency non-ready statuses as null;
    # no fallback or zero substitution is introduced.
    f2, f3, f4 = _fresh()
    target = next(item for item in f2.quarters if item.metric == "revenue" and item.fiscal_year == "2025" and item.fiscal_period == "Q2")
    f2.quarters = tuple(replace(item, resolution_status=BASIS_MISMATCH, reason="F6_BASIS") if item is target else item for item in f2.quarters)
    basis_section = _section(f2, f3, f4)
    assert next(row for row in basis_section.quarterly if row.quarter == "2025Q2").revenue_krw is None
    f2, f3, f4 = _fresh()
    target = next(item for item in f2.quarters if item.metric == "revenue" and item.fiscal_year == "2025" and item.fiscal_period == "Q2")
    f2.quarters = tuple(replace(item, resolution_status=CURRENCY_MISMATCH, reason="F6_CURRENCY") if item is target else item for item in f2.quarters)
    currency_section = _section(f2, f3, f4)
    assert next(row for row in currency_section.quarterly if row.quarter == "2025Q2").revenue_krw is None
    results.append(_validate_section("CASE 12 — AMBIGUITY/BASIS/CURRENCY", s))
    for case_id in (
        "CASE 01 — NORMAL PASS", "CASE 02 — FILTERED", "CASE 03 — FINANCIAL",
    ):
        results_by_id = next(item for item in results if item["case_id"] == case_id)
        results_by_id.update(_f4_evidence(f4_results[case_id]))
    return results


def _validate_report_outputs(
    sections: list[dict[str, Any]],
    f4_results: dict[str, FundamentalsFilterResult],
    *,
    write_artifacts: bool,
) -> dict[str, Any]:
    base_report, _, _ = generate_stock_report(
        ticker="001540", as_of="2026-06-30", repo_root=ROOT,
        save_artifacts=False, fundamentals_section=None,
    )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    selected = [("CASE 01 — NORMAL PASS", _case01()), ("CASE 02 — FILTERED", _case02()),
                ("CASE 03 — FINANCIAL", _case03()), ("CASE 04 — ETF/NON-COMMON", _case04()),
                ("CASE 05 — INPUT ABSENT", _case05())]
    # Fundamentals is an additive injection.  Keep direct references to the
    # production-relevant pre-existing sections and compare them individually;
    # a broad recursive diff would incorrectly treat the intentional summary
    # bullet and report fundamentals section as regressions.
    non_integration_fields = (
        "current_snapshot", "monthly_history", "pattern_a_fast", "a_fast_core",
        "foreign_flow", "relative_strength", "sector_relative_strength",
        "trading_value_flow",
    )
    expected_markers = {
        "CASE 01 — NORMAL PASS": ("READY",),
        "CASE 02 — FILTERED": ("FILTERED_NET_LOSS",),
        "CASE 03 — FINANCIAL": ("NOT_APPLICABLE",),
        "CASE 04 — ETF/NON-COMMON": ("NOT_APPLICABLE",),
        "CASE 05 — INPUT ABSENT": ("DATA_UNAVAILABLE",),
    }
    expected_summary = {
        "CASE 01 — NORMAL PASS": ("Filter PASS",),
        "CASE 02 — FILTERED": ("Filter FILTERED_NET_LOSS",),
        "CASE 03 — FINANCIAL": ("NOT_APPLICABLE",),
        "CASE 04 — ETF/NON-COMMON": ("NOT_APPLICABLE",),
        "CASE 05 — INPUT ABSENT": ("DATA_UNAVAILABLE", "FUNDAMENTALS_INPUT_NOT_PROVIDED"),
    }
    output_rows: dict[str, dict[str, Any]] = {}
    for name, section in selected:
        # This is the actual F5 integration path under test.  Do not assemble
        # a StockReport with dataclasses.replace, which bypasses generator
        # summary construction and v0.5 serialization behavior.
        report, _, _ = generate_stock_report(
            ticker="001540", as_of="2026-06-30", repo_root=ROOT,
            save_artifacts=False, fundamentals_section=section,
        )
        payload = report.to_dict()
        schema_errors = list(validator.iter_errors(payload))
        markdown = render_markdown_report(report)
        summary_bullets = [bullet for bullet in report.summary.bullet_points if bullet.startswith("펀더멘털:")]
        summary_fundamentals_consistent = len(summary_bullets) == 1 and all(
            marker in summary_bullets[0] for marker in expected_summary[name]
        )
        if name in {"CASE 01 — NORMAL PASS", "CASE 02 — FILTERED"}:
            value = section.summary.latest_fy_revenue_krw
            value_marker = f"{float(value) / 100_000_000:,.1f}억원"
            summary_fundamentals_consistent = summary_fundamentals_consistent and value_marker in summary_bullets[0]
            ni_value = f4_results[name].ttm_net_income
            ni_marker = f"{float(ni_value) / 100_000_000:,.1f}억원"
            summary_fundamentals_consistent = summary_fundamentals_consistent and ni_marker in summary_bullets[0]
        if name == "CASE 01 — NORMAL PASS":
            assert "DATA_UNAVAILABLE" not in summary_bullets[0]
            assert "FUNDAMENTALS_INPUT_NOT_PROVIDED" not in summary_bullets[0]
        elif name == "CASE 02 — FILTERED":
            assert "Filter PASS" not in summary_bullets[0]
            assert "FUNDAMENTALS_INPUT_NOT_PROVIDED" not in summary_bullets[0]
            assert "60.0억원" not in summary_bullets[0]
        as_of_consistent = (
            report.requested_as_of == section.requested_as_of
            and report.header.requested_as_of == section.requested_as_of
            and payload["fundamentals"]["requested_as_of"] == payload["requested_as_of"]
        )
        markdown_valid = (
            markdown.count("## 1.5. 펀더멘털 (Fundamentals)") == 1
            and markdown.index("## 1. 현재 기술적 국면") < markdown.index("## 1.5. 펀더멘털") < markdown.index("## 2. 패스트 코어")
            and "최근 12개 분기" in markdown and "최근 5개년" in markdown
            and all(marker in markdown for marker in expected_markers[name])
            and summary_fundamentals_consistent
        )
        non_integration_checks = {
            "header.report_status": report.header.report_status == base_report.header.report_status,
            **{field: getattr(report, field) == getattr(base_report, field) for field in non_integration_fields},
            "candidate_state": report.current_snapshot.candidate_state == base_report.current_snapshot.candidate_state,
            "investability_state": report.current_snapshot.investability_status == base_report.current_snapshot.investability_status,
            "strategy_state": report.a_fast_core.strategy_state == base_report.a_fast_core.strategy_state,
            "canonical_position": report.a_fast_core.canonical_position == base_report.a_fast_core.canonical_position,
            "action": report.a_fast_core.action == base_report.a_fast_core.action,
        }
        non_integration_guard = all(non_integration_checks.values())
        assert not schema_errors, schema_errors
        assert report.report_version == "0.5"
        assert summary_fundamentals_consistent
        assert as_of_consistent
        assert markdown_valid
        assert non_integration_guard
        output_rows[name] = {
            "json_schema_valid": True,
            "markdown_valid": True,
            "summary_fundamentals_consistent": True,
            "as_of_consistent": True,
            "non_integration_guard": True,
            "summary_bullet": summary_bullets[0],
            "report_requested_as_of": report.requested_as_of,
            "fundamentals_requested_as_of": section.requested_as_of,
        }
        if name in f4_results:
            output_rows[name].update(_f4_evidence(f4_results[name]))
        if write_artifacts:
            stem = name.split(" — ", 1)[0].lower().replace(" ", "")
            (ARTIFACT_DIR / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (ARTIFACT_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")
    return {
        "report": output_rows,
        "base_report": base_report,
        "non_integration_guard": all(row["non_integration_guard"] for row in output_rows.values()),
    }


def run_validation(*, write_artifacts: bool = False) -> dict[str, Any]:
    f4_results = {
        "CASE 01 — NORMAL PASS": _normal_f4_inputs()[2],
        "CASE 02 — FILTERED": _filtered_f4_inputs()[2],
        "CASE 03 — FINANCIAL": _financial_f4_inputs()[2],
    }
    results = _assert_case_matrix(f4_results)
    report_validation = _validate_report_outputs(results, f4_results, write_artifacts=write_artifacts)
    report_outputs = report_validation["report"]
    for result in results:
        output = report_outputs.get(result["case_id"])
        if output is not None:
            result.update(output)
    if write_artifacts:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        fieldnames = ["case_id", "case_name", "asset_type", "company_family", "expected_status", "actual_status", "expected_filter_status", "actual_filter_status", "expected_passed", "actual_passed", "actual_f4_status", "actual_f4_passed", "actual_f4_ttm_net_income", "actual_f4_company_family", "json_schema_valid", "markdown_valid", "summary_fundamentals_consistent", "as_of_consistent", "non_integration_guard", "result", "reason"]
        with (ARTIFACT_DIR / "representative_validation.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for result in results:
                writer.writerow({
                    "case_id": result["case_id"].split(" — ", 1)[0],
                    "case_name": result["case_id"], "asset_type": result["asset_type"],
                    "company_family": result["company_family"], "expected_status": result["expected_status"],
                    "actual_status": result["actual_status"], "expected_filter_status": result["expected_filter_status"],
                    "actual_filter_status": result["actual_filter_status"], "expected_passed": result["expected_passed"],
                    "actual_passed": result["actual_passed"], "json_schema_valid": result["json_schema_valid"],
                    "actual_f4_status": result["actual_f4_status"],
                    "actual_f4_passed": result["actual_f4_passed"],
                    "actual_f4_ttm_net_income": result["actual_f4_ttm_net_income"],
                    "actual_f4_company_family": result["actual_f4_company_family"],
                    "markdown_valid": result["markdown_valid"],
                    "summary_fundamentals_consistent": result["summary_fundamentals_consistent"],
                    "as_of_consistent": result["as_of_consistent"],
                    "non_integration_guard": result["non_integration_guard"],
                    "result": result["result"], "reason": result["reason"],
                })
        summary = {
            "validation": "F6",
            "total_cases": len(results),
            "pass_count": sum(item["result"] == "PASS" for item in results),
            "fail_count": sum(item["result"] != "PASS" for item in results),
            "network_requests": 0,
            "cases": results,
            "report_outputs": report_validation["report"],
            "f4_representatives": {
                case_id: _f4_evidence(f4_results[case_id]) for case_id in f4_results
            },
        }
        (ARTIFACT_DIR / "representative_validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "cases": results,
        "report": report_validation["report"],
        "f4": {case_id: _f4_evidence(result) for case_id, result in f4_results.items()},
        "total_cases": len(results),
    }


if __name__ == "__main__":
    summary = run_validation(write_artifacts=True)
    print(json.dumps({"total_cases": summary["total_cases"], "pass_count": sum(item["result"] == "PASS" for item in summary["cases"])}, ensure_ascii=False))
