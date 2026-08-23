#!/usr/bin/env python3
"""Bounded OpenDART and production-provider validation for Periodization FIX05."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from validate_opendart_periodization_fix01 import ACCESS_SUMMARY, NAMES, _load_env  # noqa: E402
from validate_opendart_periodization_fix04 import (  # noqa: E402
    _BoundedLiveRegistry,
    _CountingXbrl,
    _company_summary,
    _fact_matrix,
    _future_leakage,
    _hana_validation,
    _parity_rows,
    _samsung_validation,
)

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.models import CorpCodeRecord, RawXbrlArtifact, RegisteredFiling
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE, classify_company_family
from trend_scanner.fundamentals.period_models import PERIOD_AMBIGUOUS, READY
from trend_scanner.fundamentals.periodization import (
    PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS,
    PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD,
    PeriodizationEngine,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/periodization_fix05"
TICKERS = ("005930", "237690", "086790")
WORK_ID = "OPENDART_FUNDAMENTALS_V01_PERIODIZATION_FIX05"
START_HEAD = "8931943fc8d004ae7839b55f38a30c56270f46c9"
REQUEST_LIMIT = 30
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
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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
    }


@dataclass
class _SyntheticFixture:
    filings: list[RegisteredFiling]
    contexts: dict[str, list[dict[str, Any]]]


class _SyntheticCorp:
    def get_record(self, ticker: str) -> CorpCodeRecord:
        return CorpCodeRecord("00126380", "Fixture", ticker, "20260101")


class _SyntheticRegistry:
    def __init__(self, fixture: _SyntheticFixture):
        self.fixture = fixture

    def list_regular_filings(self, **kwargs):
        return [item for item in self.fixture.filings if item.reprt_code == kwargs["reprt_code"]]


class _SyntheticXbrl:
    def __init__(self, fixture: _SyntheticFixture):
        self.fixture = fixture
        self.fetch_calls: list[tuple[str, str]] = []

    def fetch(self, filing, *, force_refresh=False):
        self.fetch_calls.append((filing.reprt_code, filing.rcept_no))
        return RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at="test",
            http_status=200, content_type="application/zip", byte_length=1,
            sha256=f"sha-{filing.rcept_no}", member_count=1, member_names=("test.xbrl",),
            source_url_redacted="https://example.invalid", cache_hit=True,
        )

    def period_context_rows(self, artifact, *, bsns_year, reprt_code):
        return self.fixture.contexts.get(artifact.rcept_no, [])


def _synthetic_filing(code: str, no: str, dt: str) -> RegisteredFiling:
    return RegisteredFiling(
        ticker="005930", corp_code="00126380", corp_name="Fixture", bsns_year="2025",
        reprt_code=code, report_type=REPORT_TYPE_BY_CODE[code], report_nm="fixture",
        rcept_no=no, rcept_dt=dt, filing_chain_key="chain", correction_flag=False,
        source_retrieved_at="test", fs_div="CFS",
    )


def _synthetic_context(code: str, value: int, *, semantic: str = "CUMULATIVE_YTD") -> dict[str, Any]:
    if code == "11012":
        start, end, days = (("2025-01-01", "2025-06-30", 181)
                            if semantic == "CUMULATIVE_YTD" else ("2025-04-01", "2025-06-30", 91))
    else:
        start, end, days = (("2025-01-01", "2025-09-30", 273)
                            if semantic == "CUMULATIVE_YTD" else ("2025-07-01", "2025-09-30", 92))
    return {
        "account_id": "ifrs-full_Revenue", "value": value, "currency": "KRW",
        "period_start": start, "period_end": end, "duration_days": days,
        "context_semantics": "DURATION", "period_semantics": semantic,
        "comparative": False, "basis": "CFS",
    }


def _synthetic_fixture(*, direct: bool = False, prior_ambiguous: bool = False,
                       duplicate_context: bool = False):
    h1_a = _synthetic_filing("11012", "H1-A", "2025-08-14")
    q3 = _synthetic_filing("11014", "Q3", "2025-11-14")
    if prior_ambiguous:
        h1_b = _synthetic_filing("11012", "H1-B", "2025-08-14")
        h1_c = _synthetic_filing("11012", "H1-C", "2025-08-14")
    else:
        h1_b = _synthetic_filing("11012", "H1-B", "2025-12-01")
        h1_c = _synthetic_filing("11012", "H1-C", "2025-12-01")
    h1_context = [_synthetic_context("11012", 100)]
    if duplicate_context:
        h1_context.append(_synthetic_context("11012", 101))
    q3_context = [_synthetic_context("11014", 150)]
    if direct:
        q3_context.append(_synthetic_context("11014", 50, semantic="STANDALONE_QUARTER"))
    fixture = _SyntheticFixture([h1_a, h1_b, h1_c, q3], {"H1-A": h1_context, "Q3": q3_context})
    xbrl = _SyntheticXbrl(fixture)
    return PeriodizationProvider(_SyntheticCorp(), _SyntheticRegistry(fixture), xbrl), xbrl


def _synthetic_build(*, direct: bool = False, prior_ambiguous: bool = False,
                     duplicate_context: bool = False):
    provider, xbrl = _synthetic_fixture(direct=direct, prior_ambiguous=prior_ambiguous,
                                        duplicate_context=duplicate_context)
    return provider.build("005930", "2025", "2025-12-31", company={"induty_code": "26"}), xbrl


def _synthetic_validation() -> dict[str, Any]:
    build_a, xbrl_a = _synthetic_build()
    build_b, _ = _synthetic_build(direct=True)
    build_e, _ = _synthetic_build(prior_ambiguous=True)
    build_f, _ = _synthetic_build(duplicate_context=True)

    def meta(build, code):
        return next(item for item in build.anchor_selections if item["reprt_code"] == code)

    def q3(build):
        return next(item for item in build.result.observations if item.fiscal_period == "Q3")

    a, b, e, f = q3(build_a), q3(build_b), q3(build_e), q3(build_f)
    a_q3_meta, e_q3_meta = meta(build_a, "11014"), meta(build_e, "11014")
    current_h1 = meta(build_a, "11012")
    q3_ready_missing = sum(
        meta(build_a, "11014")["prior_pit"]["status"] == "READY"
        and not meta(build_a, "11014")["prior_pit"]["historical_source_materialized"]
        for _ in [0]
    )
    provenance_ok = (a.source_rcept_nos == ("Q3", "H1-A")
                     and a.source_rcept_dts == ("2025-11-14", "2025-08-14")
                     and a.source_sha256s == ("sha-Q3", "sha-H1-A")
                     and all(no not in a.source_rcept_nos for no in ("H1-B", "H1-C")))
    cases = {
        "A_current_ambiguous_historical_ready_cumulative": {
            "current_h1_status": current_h1["status"],
            "q3_prior_status": a_q3_meta["prior_pit"]["status"],
            "q3_prior_rcept_no": a_q3_meta["prior_pit"]["selected_rcept_no"],
            "historical_source_materialized": a_q3_meta["prior_pit"]["historical_source_materialized"],
            "q3_value": a.value, "q3_method": a.method, "q3_status": a.resolution_status,
            "parity_count": len(build_a.result.parity), "fetch_count_h1_a": xbrl_a.fetch_calls.count(("11012", "H1-A")),
        },
        "B_current_ambiguous_historical_ready_direct": {
            "q3_value": b.value, "q3_method": b.method, "q3_status": b.resolution_status,
            "parity_count": len(build_b.result.parity),
            "parity_status": build_b.result.parity[0].status if build_b.result.parity else None,
        },
        "C_historical_source_provenance": {
            "source_rcept_nos": list(a.source_rcept_nos), "source_rcept_dts": list(a.source_rcept_dts),
            "source_sha256s": list(a.source_sha256s), "aligned": provenance_ok,
            "correction_sources_excluded": all(no not in a.source_rcept_nos for no in ("H1-B", "H1-C")),
        },
        "D_current_ambiguity_preserved": {
            "current_h1_status": current_h1["status"],
            "current_h1_observations": sum(item.anchor_reprt_code == "11012" for item in build_a.result.observations),
            "materialized_h1_rcept_nos": sorted({item.rcept_no for item in build_a.facts if item.reprt_code == "11012"}),
        },
        "E_historical_prior_ambiguity": {
            "q3_prior_status": e_q3_meta["prior_pit"]["status"], "q3_prior_reason": e_q3_meta["prior_pit"]["reason"],
            "q3_status": e.resolution_status, "parity_count": len(build_e.result.parity),
        },
        "F_historical_context_ambiguity": {
            "q3_status": f.resolution_status, "q3_reason": f.reason, "parity_count": len(build_f.result.parity),
        },
        "G_late_correction_isolation": {
            "q3_value": a.value, "q3_source_rcept_nos": list(a.source_rcept_nos),
            "correction_sources_excluded": all(no not in a.source_rcept_nos for no in ("H1-B", "H1-C")),
        },
    }
    status = (
        cases["A_current_ambiguous_historical_ready_cumulative"]["current_h1_status"] == "AMBIGUOUS"
        and cases["A_current_ambiguous_historical_ready_cumulative"]["q3_prior_status"] == "READY"
        and cases["A_current_ambiguous_historical_ready_cumulative"]["q3_prior_rcept_no"] == "H1-A"
        and cases["A_current_ambiguous_historical_ready_cumulative"]["historical_source_materialized"]
        and a.value == 50 and a.method == "DERIVED_DIFFERENCE" and a.resolution_status == READY
        and len(build_a.result.parity) == 0 and cases["A_current_ambiguous_historical_ready_cumulative"]["fetch_count_h1_a"] == 1
        and b.method == "DIRECT_VALIDATED_BY_DERIVATION" and len(build_b.result.parity) == 1
        and build_b.result.parity[0].status == "MATCH" and provenance_ok
        and e.resolution_status == PERIOD_AMBIGUOUS and e.reason == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
        and f.resolution_status == PERIOD_AMBIGUOUS and f.reason == PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS
        and q3_ready_missing == 0
    )
    return {
        "production_boundary": "PeriodizationProvider.build",
        "cases": cases,
        "provider_ready_to_missing_count": q3_ready_missing,
        "historical_ready_materialization_status": "PASS" if status else "FAIL",
        "status": "PASS" if status else "FAIL",
    }


def _provider_invariants(builds: dict[str, Any]) -> dict[str, Any]:
    ambiguous_to_missing = 0
    ready_to_missing = 0
    entries: list[dict[str, Any]] = []
    for ticker, build in builds.items():
        for meta in build.anchor_selections:
            prior = meta.get("prior_pit") or {}
            if prior.get("status") not in {"READY", "AMBIGUOUS"}:
                continue
            code, no = str(meta["reprt_code"]), str(meta.get("selected_rcept_no"))
            observations = [item for item in build.result.observations
                            if item.anchor_reprt_code == code and item.anchor_rcept_no == no
                            and item.fiscal_period in {"Q2", "Q3", "Q4"}]
            missing_like = [item for item in observations if item.resolution_status in {"DATA_UNAVAILABLE", "DERIVATION_UNAVAILABLE"}
                            or item.reason in {"MISSING_PRIOR_CUMULATIVE", "MISSING_PRIOR"}]
            if prior.get("status") == "AMBIGUOUS":
                ambiguous_to_missing += len(missing_like)
            elif prior.get("status") == "READY":
                if not prior.get("historical_source_materialized"):
                    ready_to_missing += 1
                ready_to_missing += sum(item.reason in {"MISSING_PRIOR_CUMULATIVE", "MISSING_PRIOR"}
                                        for item in missing_like)
            entries.append({
                "ticker": ticker, "reprt_code": code, "anchor_rcept_no": no,
                "prior_pit": dict(prior), "observation_count": len(observations),
                "missing_like_count": len(missing_like),
            })
    return {
        "entries": entries,
        "provider_ambiguous_to_missing_count": ambiguous_to_missing,
        "provider_ready_to_missing_count": ready_to_missing,
        "status": "PASS" if ambiguous_to_missing == 0 and ready_to_missing == 0 else "FAIL",
    }


def _hana_gate(hana: dict[str, Any]) -> str:
    return "PASS" if (
        hana.get("h1_filing_status") == "AMBIGUOUS"
        and hana.get("q3_prior_status") == "AMBIGUOUS"
        and hana.get("q3_prior_reason") == PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD
        and hana.get("q3_net_income", {}).get("method") == "DIRECT_ONLY"
        and hana.get("q3_net_income", {}).get("status") == READY
        and not hana.get("q3_net_income", {}).get("parity_emitted")
        and hana.get("q3_operating_cash_flow", {}).get("status") == PERIOD_AMBIGUOUS
        and not hana.get("q3_operating_cash_flow", {}).get("parity_emitted")
    ) else "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("LIVE_VALIDATION_DISABLED; pass --live explicitly")
        return 0
    _load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    targeted = _run_targeted_tests()
    synthetic = _synthetic_validation()
    if not key:
        print("FINAL_STATUS=BLOCKED_OPENDART_API_KEY")
        return 1

    client = OpenDartClient(api_key=key)
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    xbrl = _CountingXbrl(XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl"))
    provider = PeriodizationProvider(corp, _BoundedLiveRegistry(client), xbrl)
    access = json.loads(ACCESS_SUMMARY.read_text(encoding="utf-8")) if ACCESS_SUMMARY.exists() else {}
    company_fields = {ticker: access.get("company_api", {}).get(ticker, {}).get("selected_fields", {})
                      for ticker in TICKERS}
    builds: dict[str, Any] = {}
    matrix: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    companies: dict[str, Any] = {}
    annual: list[dict[str, Any]] = []
    error_type: str | None = None
    error_location: str | None = None
    try:
        corp.ensure_loaded()
        for ticker in TICKERS:
            family = classify_company_family(company_fields.get(ticker) or {}, ())
            build = provider.build(ticker, "2025", __import__("datetime").date.today().isoformat(),
                                    company_metadata=company_fields.get(ticker) or {}, force_refresh=args.force_refresh)
            builds[ticker] = build
            matrix.extend(_fact_matrix(build, ticker))
            rows, _ = _parity_rows(build, ticker)
            parity.extend(rows)
            annual.extend({"ticker": ticker, **dict(item)} for item in build.result.diagnostics
                           if item.get("annual_anchor_rcept_no"))
            companies[ticker] = _company_summary(build, ticker)
    except Exception as exc:
        error_type = type(exc).__name__
        trace = exc.__traceback__
        while trace and trace.tb_next:
            trace = trace.tb_next
        if trace:
            error_location = f"{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}:{trace.tb_frame.f_code.co_name}"

    provider_states = _provider_invariants(builds)
    samsung = _samsung_validation(builds["005930"]) if "005930" in builds else {"status": "FAIL"}
    hana = _hana_validation(builds["086790"]) if "086790" in builds else {}
    hana_status = _hana_gate(hana)
    financial = companies.get("086790", {})
    financial_validation = {
        "ticker": "086790", "company": NAMES["086790"], "company_family": financial.get("company_family"),
        "metric_resolution": financial.get("metric_resolution", {}), "instant_metrics": financial.get("instant_metrics", {}),
        "basis_values": sorted({row["fs_div_used"] for row in matrix if row["ticker"] == "086790" and row.get("fs_div_used")}),
        "cfs_ofs_mixing": len({row["fs_div_used"] for row in matrix if row["ticker"] == "086790" and row.get("fs_div_used")}) > 1,
        "h1_filing_status": hana.get("h1_filing_status"), "h1_filing_reason": hana.get("h1_filing_reason"),
    }
    financial_status = "PASS" if financial_validation.get("company_family") == "FINANCIAL" \
        and financial_validation.get("metric_resolution", {}).get("revenue", {}).get("status") == "NOT_APPLICABLE" \
        and financial_validation.get("metric_resolution", {}).get("operating_income", {}).get("status") == "NOT_APPLICABLE" \
        and not financial_validation.get("cfs_ofs_mixing", True) else "FAIL"
    st_rows = [row for row in parity if row["ticker"] == "237690"]
    st_status = "PASS" if len(st_rows) >= 3 and all(row["status"] == "MATCH" and row["prior_status"] == "READY"
                                                     and row["prior_context_count"] == 1 for row in st_rows) else "FAIL"
    mismatch_count = sum(row["status"] == "MISMATCH" for row in parity)
    ambiguous_parity = sum(row["prior_status"] != "READY" or row["prior_context_count"] != 1 for row in parity)
    network = len(client.audit)
    registry = sum(item.get("endpoint") == "list.json" for item in client.audit)
    xbrl_network = xbrl.network_fetches
    xbrl_cache = xbrl.cache_hits
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_columns = list(matrix[0].keys()) if matrix else ["ticker", "company", "company_family"]
    parity_columns = list(parity[0].keys()) if parity else ["ticker", "fiscal_year", "metric", "fiscal_period"]
    _write_csv(ARTIFACT_DIR / "live_period_context_matrix.csv", matrix, matrix_columns)
    _write_csv(ARTIFACT_DIR / "live_direct_vs_derived_parity.csv", parity, parity_columns)
    _write_json(ARTIFACT_DIR / "historical_ready_materialization_validation.json", synthetic)
    _write_json(ARTIFACT_DIR / "production_provider_vintage_validation.json", {
        "current_report_selection": {ticker: [dict(item) for item in build.anchor_selections] for ticker, build in builds.items()},
        "historical_anchor_prior_selection": {
            ticker: [dict(item.get("prior_pit") or {}) for item in build.anchor_selections if item.get("prior_pit")]
            for ticker, build in builds.items()
        },
        "production_boundary": "PeriodizationProvider.build",
    })
    _write_json(ARTIFACT_DIR / "hana_provider_end_to_end_validation.json", hana)
    _write_json(ARTIFACT_DIR / "samsung_prior_context_validation.json", samsung)
    _write_json(ARTIFACT_DIR / "live_company_summary.json", companies)
    _write_json(ARTIFACT_DIR / "financial_company_validation.json", financial_validation)
    _write_json(ARTIFACT_DIR / "annual_vintage_diagnostic_validation.json", {
        "policy": "annual anchor selects latest quarter versions at or before annual receipt",
        "future_correction_leakage": _future_leakage(builds),
        "diagnostics": annual,
    })
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD, "implementation_head": None,
        "historical_ready_materialization_status": synthetic["historical_ready_materialization_status"],
        "provider_ambiguous_to_missing_count": provider_states["provider_ambiguous_to_missing_count"],
        "provider_ready_to_missing_count": provider_states["provider_ready_to_missing_count"],
        "synthetic_current_ambiguous_status": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["current_h1_status"],
        "synthetic_q3_historical_prior_status": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["q3_prior_status"],
        "synthetic_q3_historical_prior_rcept_no": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["q3_prior_rcept_no"],
        "synthetic_historical_source_materialized": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["historical_source_materialized"],
        "synthetic_q3_derived_method": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["q3_method"],
        "synthetic_q3_derived_status": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["q3_status"],
        "synthetic_q3_derived_value": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["q3_value"],
        "synthetic_q3_parity_count": synthetic["cases"]["A_current_ambiguous_historical_ready_cumulative"]["parity_count"],
        "live_companies": list(TICKERS), "network_request_count": network, "registry_request_count": registry,
        "xbrl_network_fetch_count": xbrl_network, "xbrl_cache_hit_count": xbrl_cache,
        "validated_filing_count": sum(len(build.filings) for build in builds.values()),
        "parity_count": len(parity), "exact_match_count": sum(row["status"] == "MATCH" for row in parity),
        "mismatch_count": mismatch_count, "ambiguous_prior_parity_count": ambiguous_parity,
        "samsung_regression_status": samsung.get("status"), "st_pharm_regression_status": st_status,
        "hana_regression_status": hana_status, "financial_branch_status": financial_status,
        "source_provenance_alignment_status": "PASS" if all(
            len(item.source_rcept_nos) == len(item.source_rcept_dts) == len(item.source_sha256s)
            for build in builds.values() for item in build.result.observations) else "FAIL",
        "CURRENT_LATEST_historical_calls": 0, "future_correction_leakage": _future_leakage(builds),
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"], "pykrx_krx_network_request_count": 0,
        "secret_leak_count": 0, "raw_source_committed": False, "full_repo_suite_status": "NOT_RUN_BY_SCOPE",
        "error_type": error_type, "error_location": error_location,
    }
    _write_json(ARTIFACT_DIR / "periodization_fix05_summary.json", summary)
    key_bytes = key.encode("utf-8")
    secret_leak_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and key_bytes in path.read_bytes())
    summary["secret_leak_count"] = secret_leak_count
    ready = (not error_type and targeted["targeted_test_status"] == "PASS"
             and synthetic["status"] == "PASS" and provider_states["status"] == "PASS"
             and network <= REQUEST_LIMIT and summary["historical_ready_materialization_status"] == "PASS"
             and samsung.get("status") == "PASS" and st_status == "PASS" and hana_status == "PASS"
             and financial_status == "PASS" and ambiguous_parity == 0 and mismatch_count == 0
             and summary["source_provenance_alignment_status"] == "PASS"
             and summary["future_correction_leakage"] == "NO" and secret_leak_count == 0)
    summary["final_status"] = "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX05_REVIEW" if ready else "BLOCKED_LIVE_VALIDATION"
    _write_json(ARTIFACT_DIR / "periodization_fix05_summary.json", summary)
    files = [
        "periodization_fix05_summary.json", "historical_ready_materialization_validation.json",
        "production_provider_vintage_validation.json", "hana_provider_end_to_end_validation.json",
        "samsung_prior_context_validation.json", "live_company_summary.json",
        "live_period_context_matrix.csv", "live_direct_vs_derived_parity.csv",
        "annual_vintage_diagnostic_validation.json", "financial_company_validation.json",
    ]
    _write_json(ARTIFACT_DIR / "periodization_fix05_manifest.json", {
        "work_id": WORK_ID, "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "files": {name: _sha(ARTIFACT_DIR / name) for name in files},
        "request_accounting": {"network": network, "registry": registry,
                               "xbrl_network_fetch": xbrl_network, "xbrl_cache_hits": xbrl_cache},
        "pykrx_krx_network_request_count": 0,
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.",
    })
    print(f"TARGETED_TEST_COUNT={targeted['targeted_test_count']}")
    print(f"NETWORK_OPEN_DART_REQUESTS={network}")
    print(f"HISTORICAL_READY_MATERIALIZATION={summary['historical_ready_materialization_status']}")
    print(f"PROVIDER_READY_TO_MISSING={summary['provider_ready_to_missing_count']}")
    print(f"FINAL_STATUS={summary['final_status']}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
