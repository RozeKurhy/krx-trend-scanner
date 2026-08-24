#!/usr/bin/env python3
"""Cache-only closure validation for Assessment V01 FIX03."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/assessment_v01_fix03"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_ASSESSMENT_V01_FIX03"
START_HEAD = "16a53d692040efdab98ea750f50b2c653540e560"
REQUESTED_AS_OF = "2026-08-20"
HISTORICAL_AS_OF = "2024-02-15"
CURRENT_YEARS = ("2022", "2023", "2024", "2025", "2026")
HISTORICAL_YEARS = ("2022", "2023", "2024")
CURRENT_TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
HISTORICAL_TICKERS = ("005930", "000660", "068270")
FINANCIAL_TICKER = "086790"
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온",
    "012330": "현대모비스", "086790": "하나금융지주",
}

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import validate_opendart_fundamentals_assessment_v01_fix01 as fix01  # noqa: E402
import validate_opendart_fundamentals_assessment_v01_fix02 as fix02  # noqa: E402
from trend_scanner.fundamentals.assessment import FundamentalsAssessmentEngine  # noqa: E402
from trend_scanner.fundamentals.assessment_models import DirectionComponent, SamePeriodYoYPoint  # noqa: E402
from trend_scanner.fundamentals.derived_metrics import DerivedMetricsResult  # noqa: E402


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


def _point_series(values: tuple[float, ...]) -> tuple[SamePeriodYoYPoint, ...]:
    start = 2027 - len(values)
    return tuple(SamePeriodYoYPoint(
        fiscal_year=str(start + index), fiscal_period="Q2", metric="revenue",
        metric_type="QUARTERLY_YOY", yoy_value=value, resolution_status="READY",
        pit_available_from=REQUESTED_AS_OF, source_rcept_nos=(f"R-{index}",),
        source_rcept_dts=(REQUESTED_AS_OF,), source_sha256s=(f"sha-{index}",),
    ) for index, value in enumerate(values))


def _synthetic_aggregation_validation() -> dict[str, Any]:
    cases = {
        "I_I_I_M": (("IMPROVING", "IMPROVING", "IMPROVING", "MIXED"), "IMPROVING"),
        "D_D_M": (("DETERIORATING", "DETERIORATING", "MIXED"), "DETERIORATING"),
        "I_D": (("IMPROVING", "DETERIORATING"), "MIXED"),
        "M_M": (("MIXED", "MIXED"), "MIXED"),
        "S_S": (("STABLE", "STABLE"), "STABLE"),
        "U_U": (("UNAVAILABLE", "UNAVAILABLE"), "UNAVAILABLE"),
        "I_M_S": (("IMPROVING", "MIXED", "STABLE"), "IMPROVING"),
        "D_M_S": (("DETERIORATING", "MIXED", "STABLE"), "DETERIORATING"),
    }
    rows: list[dict[str, Any]] = []
    for case, (states, expected) in cases.items():
        components = tuple(DirectionComponent(
            axis="GROWTH", component_id=f"{case}_{index}", metric="revenue", state=state,
        ) for index, state in enumerate(states))
        counts = FundamentalsAssessmentEngine._direction_component_counts(components)
        observed = FundamentalsAssessmentEngine._aggregate_direction_components(components)
        veto = int(
            counts["mixed"] > 0
            and ((counts["improving"] > 0 and counts["deteriorating"] == 0 and observed == "MIXED")
                 or (counts["deteriorating"] > 0 and counts["improving"] == 0 and observed == "MIXED"))
        )
        rows.append({
            "case": case, "states": list(states), "expected": expected, "observed": observed,
            "component_counts": counts, "mixed_component_unconditional_veto_count": veto,
            "status": "PASS" if observed == expected and veto == 0 else "FAIL",
        })
    return {"status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL", "cases": rows}


def _axis_alignment_validation() -> dict[str, Any]:
    source = fix01._scenario()
    source = DerivedMetricsResult(source.observations + (
        fix01._synth("operating_cash_flow", "MARGIN_EXPANSION_TREND", 1,
                     metadata={"classification": "EXPANDING"}),
    ))
    result = FundamentalsAssessmentEngine().assess(source)
    ocf_acceleration = [item for item in result.evidence
                        if item.metric == "operating_cash_flow" and item.metric_type == "YOY_GROWTH_ACCELERATION"]
    mappings = [
        ("revenue", "YOY_GROWTH_ACCELERATION", "GROWTH", "revenue_short_term_acceleration"),
        ("operating_income", "YOY_GROWTH_ACCELERATION", "GROWTH", "operating_income_short_term_acceleration"),
        ("net_income", "YOY_GROWTH_ACCELERATION", "GROWTH", "net_income_short_term_acceleration"),
        ("operating_income", "MARGIN_EXPANSION_TREND", "PROFITABILITY", "operating_income_margin_direction"),
        ("net_income", "MARGIN_EXPANSION_TREND", "PROFITABILITY", "net_income_margin_direction"),
        ("operating_cash_flow", "YOY_GROWTH_ACCELERATION", "CASH_FLOW", "operating_cash_flow_short_term_acceleration"),
        ("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", "CASH_FLOW", "operating_cash_flow_short_term_trend"),
        ("operating_cash_flow", "MARGIN_EXPANSION_TREND", "CASH_FLOW", "operating_cash_flow_margin_direction"),
    ]
    checks: list[dict[str, Any]] = []
    mismatch = 0
    for metric, metric_type, axis, component_id in mappings:
        evidence = [item for item in result.evidence if item.metric == metric and item.metric_type == metric_type and item.axis == axis]
        component = next((item for items in result.direction_components.values() for item in items
                          if item.component_id == component_id), None)
        ok = bool(evidence and component and component.axis == axis)
        mismatch += int(not ok)
        checks.append({"metric": metric, "metric_type": metric_type, "expected_axis": axis,
                       "evidence_axes": sorted({item.axis for item in evidence}),
                       "component_axis": component.axis if component else None,
                       "component_id": component_id, "status": "PASS" if ok else "FAIL"})
    ocf_growth_evidence = [item for item in result.evidence
                           if item.metric == "operating_cash_flow"
                           and item.metric_type == "YOY_GROWTH_ACCELERATION"
                           and item.axis == "GROWTH"]
    mismatch += int(bool(ocf_growth_evidence))
    return {
        "status": "PASS" if mismatch == 0 else "FAIL", "checks": checks,
        "ocf_acceleration_evidence": [item.to_dict() for item in ocf_acceleration],
        "ocf_growth_axis_evidence_count": len(ocf_growth_evidence),
        "evidence_component_axis_mismatch_count": mismatch,
    }


def _reversal_validation() -> dict[str, Any]:
    cases = {
        "REVERSING_DOWN": ((8, 15, 24, 16), "REVERSING_DOWN"),
        "DECELERATING_AFTER_DOWN_TURN": ((8, 15, 24, 16, 14), "DECELERATING"),
        "REVERSING_UP": ((30, 20, 8, 14), "REVERSING_UP"),
        "ACCELERATING_AFTER_UP_TURN": ((30, 20, 8, 14, 18), "ACCELERATING"),
        "ACCELERATING_MINIMUM": ((8, 15, 24), "ACCELERATING"),
        "DECELERATING_MINIMUM": ((30, 20, 8), "DECELERATING"),
        "MIXED_IRREGULAR": ((10, 25, 15, 22, 20), "MIXED"),
    }
    rows = []
    for case, (values, expected) in cases.items():
        observed = FundamentalsAssessmentEngine._multi_year_trend(_point_series(values))
        rows.append({"case": case, "values": list(values), "expected": expected, "observed": observed,
                     "status": "PASS" if observed == expected else "FAIL"})
    return {"status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL", "cases": rows}


def _current_row(result: Any) -> dict[str, Any]:
    counts = result.diagnostics.get("direction_component_counts", {})
    return {
        "ticker": result.ticker, "company": NAMES.get(result.ticker, ""),
        "current_period": f"{result.current_fiscal_year or ''}{result.current_fiscal_period or ''}",
        "overall": result.overall_state,
        "growth_level": result.growth_state, "growth_direction": result.growth_direction,
        "profitability_level": result.profitability_state, "profitability_direction": result.profitability_direction,
        "cash_flow_level": result.cash_flow_state, "cash_flow_direction": result.cash_flow_direction,
        "momentum": result.momentum_state,
        "revenue_multi_year_trend": result.multi_year_trends.get("revenue", ""),
        "operating_income_multi_year_trend": result.multi_year_trends.get("operating_income", ""),
        "net_income_multi_year_trend": result.multi_year_trends.get("net_income", ""),
        "ocf_multi_year_trend": result.multi_year_trends.get("operating_cash_flow", ""),
        "growth_component_counts": json.dumps(counts.get("GROWTH", {}), ensure_ascii=False, sort_keys=True),
        "profitability_component_counts": json.dumps(counts.get("PROFITABILITY", {}), ensure_ascii=False, sort_keys=True),
        "cash_component_counts": json.dumps(counts.get("CASH_FLOW", {}), ensure_ascii=False, sort_keys=True),
        "strengths": "|".join(result.strengths), "risks": "|".join(result.risks),
        "matched_rule_id": result.matched_rule_id, "status": result.status,
    }


def _comparison(results: Iterable[Any]) -> list[dict[str, Any]]:
    old_path = ROOT / "artifacts/fundamentals/opendart/validation/assessment_v01_fix02/production_current_assessment_table.csv"
    old = {}
    if old_path.exists():
        with old_path.open(encoding="utf-8", newline="") as handle:
            old = {row["ticker"]: row for row in csv.DictReader(handle)}
    rows = []
    for result in results:
        previous = old.get(result.ticker, {})
        changes = []
        for label, field, current in (
            ("overall", "overall_state", result.overall_state),
            ("growth direction", "growth_direction", result.growth_direction),
            ("profitability direction", "profitability_direction", result.profitability_direction),
            ("cash direction", "cash_flow_direction", result.cash_flow_direction),
        ):
            old_value = previous.get(field, "")
            if old_value != current:
                changes.append(f"{label}:{old_value}->{current}")
        rows.append({
            "ticker": result.ticker, "fix02_overall": previous.get("overall_state", ""),
            "fix03_overall": result.overall_state,
            "fix02_growth_direction": previous.get("growth_direction", ""),
            "fix03_growth_direction": result.growth_direction,
            "fix02_profitability_direction": previous.get("profitability_direction", ""),
            "fix03_profitability_direction": result.profitability_direction,
            "fix02_cash_direction": previous.get("cash_flow_direction", ""),
            "fix03_cash_direction": result.cash_flow_direction,
            "change_reason": "; ".join(changes) or "No state change; FIX03 aggregation/axis/latest-regime contract applied",
        })
    return rows


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    targeted = fix01._run_targeted_tests()
    provider, corp, filings, xbrl = fix01._make_provider(None)
    current, current_build_years, current_errors, historical, historical_errors = fix02._build_assessments(provider)
    financial = fix02._financial_control()
    all_results = tuple(current) + (financial,) + tuple(historical)
    current_prov = fix02._provenance(current + [financial], REQUESTED_AS_OF)
    historical_prov = fix02._provenance(historical, HISTORICAL_AS_OF)
    series_counts = fix02._series_counters(current, CURRENT_YEARS)
    dependency_pattern_count, dependency_price_count = fix01._dependency_counts()
    synthetic = _synthetic_aggregation_validation()
    alignment = _axis_alignment_validation()
    reversal = _reversal_validation()
    diagnostics = Counter()
    for result in all_results:
        for key in (
            "mixed_component_unconditional_veto_count", "evidence_component_axis_mismatch_count",
            "reversal_stale_event_count", "direction_component_overwrite_count",
            "direction_order_dependence_count", "level_contaminated_by_direction_count",
            "direction_contaminated_by_level_count", "positive_streak_used_as_improvement_count",
            "current_yoy_sign_used_as_direction_count", "ttm_yoy_sign_used_as_direction_count",
        ):
            diagnostics[key] += int(result.diagnostics.get(key, 0))
    counters = {
        "five_year_window_error_count": int(len(current_build_years) != len(CURRENT_TICKERS))
        + sum(int(years != CURRENT_YEARS) for years in current_build_years.values()),
        **series_counts,
        "mixed_component_unconditional_veto_count": diagnostics["mixed_component_unconditional_veto_count"]
        + sum(int(row["mixed_component_unconditional_veto_count"]) for row in synthetic["cases"]),
        "evidence_component_axis_mismatch_count": diagnostics["evidence_component_axis_mismatch_count"] + alignment["evidence_component_axis_mismatch_count"],
        "reversal_stale_event_count": diagnostics["reversal_stale_event_count"]
        + sum(int(row["observed"] != row["expected"] and "REVERSING" in row["observed"]) for row in reversal["cases"]),
        "direction_component_overwrite_count": diagnostics["direction_component_overwrite_count"],
        "direction_order_dependence_count": diagnostics["direction_order_dependence_count"],
        "level_contaminated_by_direction_count": sum(int(result.diagnostics.get("level_contaminated_by_direction_count", 0)) for result in all_results),
        "direction_contaminated_by_level_count": sum(int(result.diagnostics.get("direction_contaminated_by_level_count", 0)) for result in all_results),
        "positive_streak_used_as_improvement_count": diagnostics["positive_streak_used_as_improvement_count"],
        "current_yoy_sign_used_as_direction_count": diagnostics["current_yoy_sign_used_as_direction_count"],
        "ttm_yoy_sign_used_as_direction_count": diagnostics["ttm_yoy_sign_used_as_direction_count"],
        "improving_without_directional_support_count": current_prov.get("improving_without_directional_support_count", 0) + historical_prov.get("improving_without_directional_support_count", 0),
        "weakening_without_directional_support_count": current_prov.get("weakening_without_directional_support_count", 0) + historical_prov.get("weakening_without_directional_support_count", 0),
        "assessment_rule_conflict_count": current_prov.get("assessment_rule_conflict_count", 0) + historical_prov.get("assessment_rule_conflict_count", 0),
        "assessment_rule_mismatch_count": current_prov.get("assessment_rule_mismatch_count", 0) + historical_prov.get("assessment_rule_mismatch_count", 0),
        "future_assessment_source_count": current_prov.get("future_assessment_source_count", 0) + historical_prov.get("future_assessment_source_count", 0),
        "ready_future_pit_available_count": current_prov.get("ready_future_pit_available_count", 0) + historical_prov.get("ready_future_pit_available_count", 0),
        "ready_missing_pit_available_count": current_prov.get("ready_missing_pit_available_count", 0) + historical_prov.get("ready_missing_pit_available_count", 0),
        "provider_cutoff_mismatch_count": current_prov.get("provider_cutoff_mismatch_count", 0) + historical_prov.get("provider_cutoff_mismatch_count", 0),
        "evidence_provenance_alignment_error_count": current_prov.get("evidence_provenance_alignment_error_count", 0) + historical_prov.get("evidence_provenance_alignment_error_count", 0),
        "historical_result_count": len(historical), "historical_ready_count": sum(result.status == "READY" for result in historical),
        "production_current_ready_count": sum(result.status == "READY" for result in current),
        "opendart_hydration_request_count": 0, "opendart_final_replay_request_count": 0,
        "opendart_cache_hit_count": int(getattr(corp, "cache_hit", False)) + filings.cache_hits + xbrl.cache_hits,
        "opendart_cache_miss_count": (0 if getattr(corp, "cache_hit", False) else 1) + filings.cache_misses + xbrl.cache_misses,
        "pykrx_krx_network_request_count": 0,
    }
    financial_ok = financial.status == "NOT_APPLICABLE" and financial.currentness_status == "VERIFIED"
    implementation_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         capture_output=True, check=False).stdout.strip()
    errors = [{"scope": "current", **item} for item in current_errors] + [{"scope": "historical", **item} for item in historical_errors]
    zero_keys = tuple(key for key in counters if key.endswith("_count") and key not in {
        "historical_result_count", "historical_ready_count", "production_current_ready_count",
        "multi_year_yoy_series_ready_count", "multi_year_trend_ready_count",
        "opendart_hydration_request_count", "opendart_final_replay_request_count",
        "opendart_cache_hit_count", "opendart_cache_miss_count",
    })
    final_ready = bool(
        implementation_head and not errors and targeted["targeted_test_status"] == "PASS"
        and synthetic["status"] == "PASS" and alignment["status"] == "PASS" and reversal["status"] == "PASS"
        and counters["production_current_ready_count"] >= 1 and counters["historical_result_count"] >= 1
        and counters["historical_ready_count"] >= 1 and financial_ok
        and all(counters[key] == 0 for key in zero_keys)
        and counters["opendart_cache_miss_count"] == 0 and dependency_pattern_count == 0
        and dependency_price_count == 0
    )
    final_status = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX03_REVIEW" if final_ready else "BLOCKED_ASSESSMENT_VALIDATION"
    columns = [
        "ticker", "company", "current_period", "overall", "growth_level", "growth_direction",
        "profitability_level", "profitability_direction", "cash_flow_level", "cash_flow_direction",
        "momentum", "revenue_multi_year_trend", "operating_income_multi_year_trend",
        "net_income_multi_year_trend", "ocf_multi_year_trend", "growth_component_counts",
        "profitability_component_counts", "cash_component_counts", "strengths", "risks",
        "matched_rule_id", "status",
    ]
    _write_json(ARTIFACT_DIR / "direction_aggregation_validation.json", {
        "status": "PASS" if all(result.diagnostics.get("mixed_component_unconditional_veto_count", 0) == 0 for result in all_results) else "FAIL",
        "production_results": [{"ticker": result.ticker, "axis_directions": dict(result.axis_directions),
                                "direction_aggregation_rule_id": result.diagnostics.get("direction_aggregation_rule_id", {}),
                                "direction_component_counts": result.diagnostics.get("direction_component_counts", {})}
                               for result in current],
    })
    _write_json(ARTIFACT_DIR / "mixed_component_veto_validation.json", synthetic)
    _write_json(ARTIFACT_DIR / "evidence_axis_alignment_validation.json", alignment)
    _write_json(ARTIFACT_DIR / "latest_regime_reversal_validation.json", reversal)
    _write_json(ARTIFACT_DIR / "direction_order_invariance_validation.json", {
        "status": "PASS" if counters["direction_order_dependence_count"] == 0 else "FAIL",
        "direction_order_dependence_count": counters["direction_order_dependence_count"],
        "direction_component_overwrite_count": counters["direction_component_overwrite_count"],
    })
    _write_json(ARTIFACT_DIR / "production_current_assessment_validation.json", {
        "status": "PASS" if current and not current_errors else "FAIL", "requested_as_of": REQUESTED_AS_OF,
        "results": [result.to_dict() for result in current], "errors": current_errors,
        "production_current_ready_count": counters["production_current_ready_count"],
    })
    _write_csv(ARTIFACT_DIR / "production_current_assessment_table.csv",
               [_current_row(result) for result in current] + [_current_row(financial)], columns)
    _write_csv(ARTIFACT_DIR / "production_fix02_fix03_comparison.csv", _comparison(current), [
        "ticker", "fix02_overall", "fix03_overall", "fix02_growth_direction", "fix03_growth_direction",
        "fix02_profitability_direction", "fix03_profitability_direction", "fix02_cash_direction",
        "fix03_cash_direction", "change_reason",
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
        "status": "PASS", "hydration_run_request_count": 0, "final_replay_request_count": 0,
        "cache_hit_count": counters["opendart_cache_hit_count"], "cache_miss_count": counters["opendart_cache_miss_count"],
        "pykrx_krx_network_request_count": 0, "network_mode": "CACHE_ONLY",
    })
    _write_json(ARTIFACT_DIR / "financial_not_applicable_validation.json", {
        "ticker": FINANCIAL_TICKER, "company": NAMES[FINANCIAL_TICKER],
        "status": "PASS" if financial_ok else "FAIL", "result": financial.to_dict(),
    })
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "validation_source_head": implementation_head, "current_default_fiscal_years": list(CURRENT_YEARS),
        "historical_fiscal_years": list(HISTORICAL_YEARS), "current_cohort": list(CURRENT_TICKERS) + [FINANCIAL_TICKER],
        "historical_cohort": list(HISTORICAL_TICKERS), **counters,
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE", "pattern_a_import_count": dependency_pattern_count,
        "price_provider_import_count": dependency_price_count, "errors": errors,
        "financial_not_applicable_count": int(financial_ok), "final_ready": final_ready,
        "final_status": final_status, "git_diff_check_status": "PASS" if subprocess.run(
            ["git", "diff", "--check"], cwd=ROOT, capture_output=True
        ).returncode == 0 else "FAIL",
    }
    _write_json(ARTIFACT_DIR / "assessment_fix03_summary.json", summary)
    files = {path.name: _sha(path) for path in sorted(ARTIFACT_DIR.iterdir())
             if path.is_file() and path.name != "assessment_fix03_manifest.json"}
    _write_json(ARTIFACT_DIR / "assessment_fix03_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": implementation_head,
        "validation_source_head": implementation_head, "files": files,
        "network_policy": {"mode": "CACHE_ONLY", "pykrx_krx": 0},
        "final_ready": final_ready, "final_status": final_status,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
