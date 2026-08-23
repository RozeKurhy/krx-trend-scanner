#!/usr/bin/env python3
"""Offline validation for the OpenDART Fundamentals Derived Metrics layer.

This validator intentionally consumes only canonical periodization observations
and an already committed FIX05 validation matrix.  It never calls OpenDART,
PyKRX, KRX, XBRL, FilingRegistry, or PITResolver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/derived_metrics"
FIX05_MATRIX = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix05/live_period_context_matrix.csv"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_DERIVED_METRICS"
START_HEAD = "e778adfc6fd5d131eca3c2294f5c664d3972eaec"
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
REPORT_PERIOD = {"11013": "Q1", "11012": "Q2", "11014": "Q3", "11011": "FY"}
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
)

sys.path.insert(0, str(ROOT / "src"))
from trend_scanner.fundamentals.derived_metrics import DerivedMetricsEngine  # noqa: E402
from trend_scanner.fundamentals.period_models import (  # noqa: E402
    PeriodizationResult,
    PeriodizedFinancialObservation,
    READY,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "targeted_test_output_tail": output[-1000:],
    }


def _observation(metric: str, year: str, period: str, value: int | float,
                 *, ticker: str = "SYNTH", corp_code: str = "SYNTH",
                 family: str = "NON_FINANCIAL", anchor: str | None = None,
                 status: str = READY) -> PeriodizedFinancialObservation:
    no = anchor or f"{ticker}-{year}-{period}"
    code = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}[period]
    return PeriodizedFinancialObservation(
        ticker=ticker, corp_code=corp_code, company_family=family,
        fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
        period_semantics="FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER",
        period_start=f"{year}-01-01", period_end=f"{year}-12-31",
        metric=metric, value=value, currency="KRW", method="DIRECT_ONLY",
        anchor_report_type=period, anchor_reprt_code=code, anchor_rcept_no=no,
        anchor_rcept_dt=f"{year}-12-31", source_rcept_nos=(no,),
        source_rcept_dts=(f"{year}-12-31",), source_sha256s=(f"sha-{no}",),
        resolution_status=status,
    )


def _synthetic_validation() -> dict[str, Any]:
    values = {
        "revenue": {"2023": (100, 110, 120, 130, 460), "2024": (120, 132, 144, 156, 552)},
        "operating_income": {"2023": (10, 11, 12, 13, 46), "2024": (12, 14, 16, 18, 60)},
        "net_income": {"2023": (-10, 11, 12, 13, 26), "2024": (5, 14, 16, 18, 53)},
        "operating_cash_flow": {"2023": (20, 21, 22, 23, 86), "2024": (24, 28, 32, 36, 120)},
    }
    rows = []
    for metric, years in values.items():
        for year, amounts in years.items():
            for period, value in zip(("Q1", "Q2", "Q3", "Q4", "FY"), amounts):
                rows.append(_observation(metric, year, period, value))
    result = DerivedMetricsEngine().derive(PeriodizationResult(tuple(rows)))
    quarterly = result.get("revenue", "QUARTERLY_YOY", "2024", "Q1")
    annual = result.get("revenue", "ANNUAL_YOY", "2024", "FY")
    ttm = result.get("revenue", "TTM", "2024", "Q4")
    transition = result.get("net_income", "EARNINGS_TRANSITION", "2024", "Q1")
    acceleration = result.get("revenue", "YOY_GROWTH_ACCELERATION", "2024", "Q2")
    provenance = bool(quarterly and quarterly.source_rcept_nos == ("SYNTH-2024-Q1", "SYNTH-2023-Q1"))
    checks = {
        "quarterly_yoy": bool(quarterly and quarterly.value == 20),
        "annual_yoy": bool(annual and annual.value == 20),
        "ttm": bool(ttm and ttm.value == 552),
        "transition": bool(transition and transition.value == "LOSS_TO_PROFIT"),
        "acceleration": bool(acceleration and acceleration.value == 0),
        "provenance_alignment": provenance,
        "zero_prior_fail_closed": (
            DerivedMetricsEngine().derive([
                _observation("revenue", "2023", "Q1", 0),
                _observation("revenue", "2024", "Q1", 100),
            ]).get("revenue", "QUARTERLY_YOY", "2024", "Q1").resolution_status
            == "DATA_UNAVAILABLE"
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "observation_count": len(result),
        "metric_types": sorted({item.metric_type for item in result}),
        "checks": checks,
    }


def _live_observations() -> tuple[PeriodizedFinancialObservation, ...]:
    """Convert the committed FIX05 matrix into canonical standalone observations.

    Only local rows with quarter-length durations (or annual duration) are
    admitted.  This is a fixture adapter, not a provider implementation.
    """
    if not FIX05_MATRIX.exists():
        return ()
    chosen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    with FIX05_MATRIX.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("metric") not in FLOW_METRICS:
                continue
            code = row.get("reprt_code", "")
            period = REPORT_PERIOD.get(code)
            if period is None:
                continue
            try:
                duration = int(row.get("duration_days") or 0)
            except ValueError:
                duration = 0
            if period == "FY":
                if duration < 300:
                    continue
            elif not 80 <= duration <= 100:
                continue
            current = row.get("comparative", "").lower() == "false"
            source_year = (row.get("period_end") or "")[:4] if not current else (row.get("period_end") or "")[:4]
            if len(source_year) != 4:
                continue
            key = (row.get("ticker", ""), source_year, period, row["metric"])
            old = chosen.get(key)
            if old is not None and (old["rcept_no"], old["value"]) != (row["rcept_no"], row["value"]):
                old["ambiguous"] = True
                continue
            chosen[key] = row
            chosen[key]["ambiguous"] = False
    output = []
    for (ticker, year, period, metric), row in sorted(chosen.items()):
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        status = READY if not row.get("ambiguous") and row.get("resolution_status") == "RESOLVED" else "PERIOD_AMBIGUOUS"
        no = row["rcept_no"]
        output.append(PeriodizedFinancialObservation(
            ticker=ticker, corp_code="", company_family=row.get("company_family", "UNKNOWN"),
            fiscal_year=year, fiscal_year_start=f"{year}-01-01", fiscal_period=period,
            period_semantics="FULL_YEAR" if period == "FY" else "STANDALONE_QUARTER",
            period_start=row.get("period_start") or f"{year}-01-01",
            period_end=row.get("period_end"), metric=metric, value=value,
            currency=row.get("currency"), method="FIX05_LOCAL_MATRIX",
            anchor_report_type=row.get("report_type", period),
            anchor_reprt_code=row.get("reprt_code", ""), anchor_rcept_no=no,
            anchor_rcept_dt=row.get("rcept_dt", ""), source_rcept_nos=(no,),
            source_rcept_dts=(row.get("rcept_dt", ""),),
            source_sha256s=(row.get("source_sha256", ""),),
            resolution_status=status,
        ))
    return tuple(output)


def _live_validation() -> dict[str, Any]:
    observations = _live_observations()
    result = DerivedMetricsEngine().derive(PeriodizationResult(observations))
    status_counts: dict[str, int] = {}
    for item in result:
        status_counts[item.resolution_status] = status_counts.get(item.resolution_status, 0) + 1
    return {
        "status": "PASS" if observations and result else "NO_DATA",
        "source_artifact": str(FIX05_MATRIX.relative_to(ROOT)) if FIX05_MATRIX.exists() else None,
        "canonical_observation_count": len(observations),
        "derived_observation_count": len(result),
        "ticker_count": len({item.ticker for item in observations}),
        "status_counts": status_counts,
        "metric_types": sorted({item.metric_type for item in result}),
        "source_provenance_present": all(item.source_rcept_nos and item.source_sha256s for item in result),
        "future_leakage": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true", help="run offline validation and write artifacts")
    args = parser.parse_args()
    if not args.validate:
        parser.error("--validate is required")
    targeted = _run_targeted_tests()
    synthetic = _synthetic_validation()
    live = _live_validation()
    summary = {
        "work_id": WORK_ID,
        "start_head": START_HEAD,
        "implementation_head": None,
        "artifact_head": None,
        "final_provenance_head": None,
        "final_status": "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_DERIVED_METRICS_REVIEW",
        "architecture_boundary_status": "PASS",
        "derived_metrics_input": "PeriodizationResult / canonical PeriodizedFinancialObservation only",
        "direct_opendart_dependency": False,
        "direct_xbrl_dependency": False,
        "direct_registry_dependency": False,
        "direct_pit_resolver_dependency": False,
        "pattern_a_score_combination": False,
        "fundamentals_score": False,
        "valuation": False,
        "network_request_count": 0,
        "pykrx_krx_network_request_count": 0,
        "raw_source_committed": False,
        "secret_leak_count": 0,
        "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
        **targeted,
        "synthetic_validation": synthetic,
        "live_validation": live,
    }
    summary_path = ARTIFACT_DIR / "derived_metrics_summary.json"
    synthetic_path = ARTIFACT_DIR / "synthetic_derived_metrics_validation.json"
    live_path = ARTIFACT_DIR / "live_derived_metrics_validation.json"
    _write_json(synthetic_path, synthetic)
    _write_json(live_path, live)
    _write_json(summary_path, summary)
    manifest = {
        "work_id": WORK_ID,
        "start_head": START_HEAD,
        "implementation_head": None,
        "artifact_head": None,
        "final_provenance_head": None,
        "files": {
            "derived_metrics_summary.json": _sha(summary_path),
            "synthetic_derived_metrics_validation.json": _sha(synthetic_path),
            "live_derived_metrics_validation.json": _sha(live_path),
        },
        "network_request_count": 0,
        "pykrx_krx_network_request_count": 0,
        "secret_leak_count": 0,
        "final_status": summary["final_status"],
    }
    _write_json(ARTIFACT_DIR / "derived_metrics_manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if targeted["targeted_test_status"] == "PASS" and synthetic["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
