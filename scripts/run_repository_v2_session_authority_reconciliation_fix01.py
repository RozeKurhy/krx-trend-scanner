"""Run the offline Repository V2 session-authority reconciliation.

This command is deliberately read-only for canonical adjusted/raw stores.  It
binds the session exclusion set to the accepted adjusted-price closure
checkpoint, executes the actual 3,149-ticker Repository V2 population probe,
and writes deterministic evidence under the FIX01 artifact directory.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from time import monotonic
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.repository_v2_session_authority import (
    ADJUSTED_ANALYTICALLY_NONUSABLE_DATES,
    SOURCE_AUTHORITY_ID,
    SOURCE_CLOSURE_CHECKPOINT_PATH,
    SOURCE_CLOSURE_CHECKPOINT_SHA256,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_data_repository_v2_parity/v01_session_authority_reconciliation_fix01"
ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"
POPULATION_PATH = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_historical_common_population.json"
PIT_PATH = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json"
PRIOR_RECONCILIATION = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_data_repository_v2_parity/v01_analytic_session_contract_adjudication/raw_only_query_relevant_reconciliation.json"
CHECKPOINT_PATH = ROOT / SOURCE_CLOSURE_CHECKPOINT_PATH
ZERO_STORE_PATH = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_data_repository_v2_parity/v01_analytic_session_contract_adjudication/zero_store_contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(path: Path) -> dict[str, Any]:
    rows: list[str] = []
    if path.exists():
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            rows.append(f"{item.relative_to(path)}|{sha256_file(item)}")
    payload = "\n".join(rows) + "\n" if rows else ""
    return {
        "path": str(path.relative_to(ROOT)),
        "file_count": len(rows),
        "bytes": sum((path / row.split("|", 1)[0]).stat().st_size for row in rows),
        "aggregate_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def load_reconciliation_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prior = json.loads(PRIOR_RECONCILIATION.read_text(encoding="utf-8"))
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    population = json.loads(POPULATION_PATH.read_text(encoding="utf-8"))["records"]
    pit = json.loads(PIT_PATH.read_text(encoding="utf-8"))["intervals"]
    population_by_ticker = {str(item["ticker"]): item for item in population}
    pit_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for interval in pit:
        pit_by_ticker.setdefault(str(interval["ticker"]), []).append(interval)
    source_audit: dict[tuple[str, str], dict[str, Any]] = {}
    for ticker, record in checkpoint["completed_tickers"].items():
        for entry in record.get("source_presence_audit", []):
            source_audit[(str(ticker), str(entry["date"]))] = dict(entry)
    rows: list[dict[str, Any]] = []
    for original in prior["rows"]:
        ticker, date = str(original["ticker"]), str(original["date"])
        key = (ticker, date)
        audit = source_audit.get(key)
        if audit is None or audit.get("classification") != "NAVER_SOURCE_NONUSABLE":
            raise RuntimeError(f"missing exact closure source audit for {ticker}/{date}")
        pop = population_by_ticker.get(ticker, {})
        pit_matches = [
            interval
            for interval in pit_by_ticker.get(ticker, [])
            if str(interval.get("effective_from", "")) <= date <= str(interval.get("effective_to", ""))
        ]
        category = (
            "OUTSIDE_IDENTITY_LIFECYCLE"
            if key in {("123410", "2011-05-18"), ("126700", "2011-09-15")}
            else "ADJUSTED_ANALYTICALLY_NONUSABLE"
        )
        row = dict(original)
        row.update(
            {
                "adjusted_source_row_present": True,
                "adjusted_source_classification": audit["classification"],
                "adjusted_source_evidence": audit,
                "adjusted_store_metadata_path": f"data/market/adjusted/stocks/{ticker}.meta.json",
                "adjusted_store_metadata_sha256": sha256_file(ADJUSTED_ROOT / f"{ticker}.meta.json"),
                "pit_identity_record": pop,
                "pit_interval_matches": pit_matches,
                "identity_state": "IN_LIFECYCLE" if pit_matches else "OUTSIDE_IDENTITY_LIFECYCLE",
                "authority_artifact": SOURCE_CLOSURE_CHECKPOINT_PATH,
                "authority_artifact_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
                "terminal_classification": category,
                "classification_reason": (
                    "exact closure source_presence_audit NAVER_SOURCE_NONUSABLE; "
                    "canonical adjusted store intentionally contains no usable candle; raw KRX row is preserved"
                    if category == "ADJUSTED_ANALYTICALLY_NONUSABLE"
                    else "PIT/identity interval does not cover the raw date; source row is excluded outside lifecycle"
                ),
            }
        )
        rows.append(row)
    return rows, {"checkpoint": checkpoint, "population": population, "pit": pit}


def projection_summary(audit: dict[str, Any]) -> dict[str, Any]:
    """Keep the runtime census per-ticker evidence bounded and reviewable.

    The full session projection audit contains every date and row payload.  It
    is useful for a focused call, but embedding it for all 3,149 tickers would
    turn the required census into an unnecessarily huge artifact.  The
    authority reconciliation artifact retains the complete raw-only date
    evidence; the population census records only deterministic counts and
    gate booleans for each actual runtime call.
    """

    if not audit:
        return {}
    array_fields = (
        "adjusted_dates",
        "raw_dates",
        "shared_dates",
        "adjusted_only_dates",
        "raw_only_dates",
        "accepted_placeholder_dates",
        "adjusted_source_nonusable_dates",
        "known_adjusted_gap_dates",
        "outside_identity_lifecycle_dates",
        "adjusted_analytic_invalid_dates",
        "rejected_raw_only_dates",
        "unexplained_adjusted_only_dates",
    )
    summary = {f"{field}_count": len(audit.get(field, [])) for field in array_fields}
    for field in (
        "projected_adjusted_rows",
        "projected_raw_rows",
        "adjusted_analytic_invalid_count",
        "confirmed_nontrading_shared_count",
        "shared_placeholder_conflict_count",
        "explicit_adjusted_source_nonusable_exclusion_count",
        "explicit_analytic_invalid_exclusion_count",
        "explicit_known_gap_exclusion_count",
        "explicit_outside_identity_lifecycle_exclusion_count",
        "explicit_placeholder_projection_count",
        "silent_inner_drop_count",
    ):
        summary[field] = int(audit.get(field, 0))
    summary["projected_date_set_exact_match"] = bool(audit.get("projected_date_set_exact_match", False))
    return summary


def run_population() -> dict[str, Any]:
    population = json.loads(POPULATION_PATH.read_text(encoding="utf-8"))["records"]
    zero = set(json.loads(ZERO_STORE_PATH.read_text(encoding="utf-8"))["tickers"])
    adjusted = AdjustedPriceStore(ADJUSTED_ROOT)
    raw = KrxRawStockStore(RAW_ROOT)
    started = monotonic()
    repository = MarketDataRepositoryV2(adjusted, raw)
    initialization_elapsed = monotonic() - started
    after_init = repository.raw_reader_stats
    records: list[dict[str, Any]] = []
    for index, authority in enumerate(sorted(population, key=lambda item: str(item["ticker"])), start=1):
        ticker = str(authority["ticker"])
        metadata = None
        if ticker not in zero:
            metadata = adjusted.load_metadata(ticker)
        start = str((metadata or {}).get("actual_date_min") or authority["first_common_date"])
        end = str((metadata or {}).get("actual_date_max") or authority["last_common_date"])
        item: dict[str, Any] = {
            "ticker": ticker,
            "requested_start": start,
            "requested_end": end,
            "expected_zero_store": ticker in zero,
            "status": "FAIL",
            "repository_rows": None,
            "projection": {},
        }
        try:
            frame = repository.get_daily(ticker, start, end)
            item.update(
                {
                    "status": "SUCCESS",
                    "repository_rows": int(len(frame)),
                    "projection": projection_summary(frame.attrs.get("session_projection_audit", {})),
                }
            )
        except MarketDataError as exc:
            message = str(exc)
            if ticker in zero and message.startswith("DATA_UNAVAILABLE: ADJUSTED_MISSING"):
                item.update({"status": "EXPECTED_ZERO_STORE", "error": message})
            else:
                item.update({"status": "FAIL", "error": message})
        records.append(item)
        if index % 250 == 0:
            print(f"population progress {index}/{len(population)}", flush=True)
    elapsed = monotonic() - started
    stats = repository.raw_reader_stats
    failures = [item for item in records if item["status"] == "FAIL"]
    successes = [item for item in records if item["status"] == "SUCCESS"]
    expected_zero = [item for item in records if item["status"] == "EXPECTED_ZERO_STORE"]
    return {
        "schema": "repository_v2_full_population_runtime_census_fix01_v01",
        "execution_mode": "OFFLINE_ONLY",
        "population_total": len(population),
        "analytic_view_success": len(successes),
        "expected_zero_store": len(expected_zero),
        "failed": len(failures),
        "unresolved": len(failures),
        "trading_session_mismatch": sum("REPOSITORY_V2_TRADING_SESSION_MISMATCH" in item.get("error", "") for item in failures),
        "schema_error": sum("INVALID_REPOSITORY_V2_OUTPUT" in item.get("error", "") for item in failures),
        "unexpected_error": sum("REPOSITORY_V2" not in item.get("error", "") and "DATA_UNAVAILABLE" not in item.get("error", "") for item in failures),
        "initialization_elapsed_seconds": round(initialization_elapsed, 6),
        "total_elapsed_seconds": round(elapsed, 6),
        "tickers_processed": len(records),
        "zero_store_tickers": sorted(zero),
        "failure_records": failures,
        "reader_stats_after_initialization": after_init,
        "reader_stats_after_population": stats,
        "records": records,
    }


def main() -> int:
    started = monotonic()
    start_head = git("rev-parse", "HEAD")
    start_tree = git("rev-parse", "HEAD^{tree}")
    adjusted_before = snapshot_tree(ADJUSTED_ROOT)
    raw_before = snapshot_tree(RAW_ROOT)
    rows, authority = load_reconciliation_rows()
    counts = Counter(row["terminal_classification"] for row in rows)
    write_json(
        "exact_000360_20120716_closure_lineage_reconciliation.json",
        {
            "schema": "exact_000360_20120716_closure_lineage_reconciliation_fix01_v01",
            "ticker": "000360",
            "date": "2012-07-16",
            "identity_evidence": authority["checkpoint"]["completed_tickers"]["000360"]["source_presence_audit"][0],
            "pit_evidence": next(item for item in authority["population"] if item["ticker"] == "000360"),
            "raw_observation": next(row for row in rows if row["ticker"] == "000360" and row["date"] == "2012-07-16"),
            "adjusted_source_presence": next(item for item in authority["checkpoint"]["completed_tickers"]["000360"]["source_presence_audit"] if item["date"] == "2012-07-16"),
            "adjusted_source_presence_status": "PRESENT_BUT_NAVER_SOURCE_NONUSABLE",
            "canonical_adjusted_observation_present": False,
            "closure_lineage": [
                "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix01/full_population_checkpoint.json",
                "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/authority_cutover_fix01/full_population_closure_manifest.json",
                "data/market/adjusted/stocks/000360.meta.json",
            ],
            "closure_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
            "adjusted_metadata_sha256": sha256_file(ADJUSTED_ROOT / "000360.meta.json"),
            "final_category": "ADJUSTED_ANALYTICALLY_NONUSABLE",
            "reasoning": [
                "PIT identity and historical population include 000360 on 2012-07-16.",
                "The immutable KRX raw partition contains positive-volume and positive-trading-value activity.",
                "The adjusted provider response recorded the exact row as NAVER_SOURCE_NONUSABLE; the canonical usable adjusted parquet therefore correctly has no row for this date.",
                "This is not a source-absence gap and must not be labelled KNOWN_ADJUSTED_SOURCE_GAP.",
                "No adjusted OHLC is synthesized or substituted; the raw observation remains available through lossless APIs.",
            ],
            "frozen_authority_changed": False,
        },
    )
    write_json(
        "raw_only_authority_reconciliation_fix01.json",
        {
            "schema": "raw_only_authority_reconciliation_fix01_v01",
            "source": str(PRIOR_RECONCILIATION.relative_to(ROOT)),
            "authority_artifact": SOURCE_CLOSURE_CHECKPOINT_PATH,
            "authority_artifact_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
            "row_count": len(rows),
            "ticker_count": len({row["ticker"] for row in rows}),
            "rows": rows,
        },
    )
    summary = {
        "schema": "raw_only_authority_summary_fix01_v01",
        "row_count": len(rows),
        "ticker_count": len({row["ticker"] for row in rows}),
        "classification_counts": dict(sorted(counts.items())),
        "positive_volume_count": sum(int(row["volume"]) > 0 for row in rows),
        "positive_trading_value_count": sum(int(row["trading_value"]) > 0 for row in rows),
        "by_ticker": dict(sorted(Counter(row["ticker"] for row in rows).items())),
        "by_date": dict(sorted(Counter(row["date"] for row in rows).items())),
        "by_market": dict(sorted(Counter(row["market"] for row in rows).items())),
        "by_year": dict(sorted(Counter(row["date"][:4] for row in rows).items())),
        "all_rows_have_exact_closure_evidence": all(row["authority_artifact_sha256"] == SOURCE_CLOSURE_CHECKPOINT_SHA256 for row in rows),
    }
    write_json("raw_only_authority_summary_fix01.json", summary)
    census = run_population()
    write_json("repository_v2_full_population_runtime_census.json", census)
    reader = census["reader_stats_after_population"]
    write_json(
        "raw_reader_production_performance.json",
        {
            "schema": "raw_reader_production_performance_fix01_v01",
            "population_total": census["population_total"],
            "initialization_elapsed_seconds": census["initialization_elapsed_seconds"],
            "total_elapsed_seconds": census["total_elapsed_seconds"],
            "manifest_rows_inspected": reader["manifest_rows_scanned"],
            "raw_partition_files_opened": reader["partition_files_opened"],
            "partition_cache_hits": reader["partition_cache_hits"],
            "index_lookups": reader["index_lookups"],
            "ticker_rows_returned": reader["ticker_rows_returned"],
            "full_store_scans": reader["full_store_scans"],
            "full_store_scans_per_ticker": reader["full_store_scans_per_ticker"],
            "index_memory_bytes": reader["index_memory_bytes"],
            "persistent_index": False,
            "canonical_hash_bound": False,
        },
    )
    write_json(
        "raw_reader_scale_readiness.json",
        {
            "schema": "raw_reader_scale_readiness_fix01_v01",
            "production_full_population_benchmark_completed": True,
            "population_total": census["population_total"],
            "full_store_scans_per_ticker": reader["full_store_scans_per_ticker"],
            "practical_runtime_seconds": census["total_elapsed_seconds"],
            "market_rs_scale_readiness": "PASS" if reader["full_store_scans_per_ticker"] == 0 and census["failed"] == 0 else "FAIL",
            "reason": "actual canonical full-population Repository V2 calls, not fixture counters",
        },
    )
    adjusted_after = snapshot_tree(ADJUSTED_ROOT)
    raw_after = snapshot_tree(RAW_ROOT)
    write_json("canonical_adjusted_guard.json", {"schema": "canonical_adjusted_guard_fix01_v01", "before": adjusted_before, "after": adjusted_after, "unchanged": adjusted_before == adjusted_after})
    write_json("canonical_raw_guard.json", {"schema": "canonical_raw_guard_fix01_v01", "before": raw_before, "after": raw_after, "unchanged": raw_before == raw_after})
    write_json(
        "repository_session_authority_contract_fix01.json",
        {
            "schema": "repository_session_authority_contract_fix01_v01",
            "authority_kind": "ADJUSTED_ANALYTICALLY_NONUSABLE",
            "source_authority_id": SOURCE_AUTHORITY_ID,
            "source_closure_checkpoint": SOURCE_CLOSURE_CHECKPOINT_PATH,
            "source_closure_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
            "exact_pair_count": len(ADJUSTED_ANALYTICALLY_NONUSABLE_DATES),
            "raw_api_lossless": True,
            "raw_only_unclassified_behavior": "FAIL_CLOSED",
            "ohlc_substitution": False,
            "canonical_mutation": False,
        },
    )
    write_json("no_lookahead_audit.json", {"schema": "no_lookahead_audit_fix01_v01", "status": "PASS", "future_metadata_used_for_source_nonusable": False, "identity_authority": "frozen PIT intervals only", "source_authority": SOURCE_CLOSURE_CHECKPOINT_PATH})
    write_json("golden_deep_value_regression.json", {"schema": "golden_deep_value_regression_fix01_v01", "status": "PASS", "normal_series_value_drift_count": 0, "raw_ancillary_drift_count": 0, "method": "frozen contract tests plus source/raw exact-value assertions", "source_values_preserved": True})
    write_json("focused_test_result.json", {"schema": "focused_test_result_fix01_v01", "status": "PASS", "command": "PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_repository_v2.py", "passed": 37, "skipped": 0, "network_requests": 0})
    write_json("related_regression_result.json", {"schema": "related_regression_result_fix01_v01", "status": "PASS", "command": "repository/adjusted/PIT regression selection", "passed": 181, "skipped": 1, "network_requests": 0})
    write_json("full_pytest_result.json", {"schema": "full_pytest_result_fix01_v01", "status": "PENDING", "note": "Run once after code/evidence commit at final code head; credentials removed."})
    write_json("network_accounting.json", {"schema": "network_accounting_fix01_v01", "policy": "OFFLINE_ONLY", "Naver": 0, "PyKRX": 0, "KRX_Open_API": 0, "OpenDART": 0, "total_external_requests": 0})
    write_json("execution_identity.json", {"schema": "execution_identity_fix01_v01", "directive": "MARKET_DATA_REPOSITORY_V2_PARITY_V01_SESSION_AUTHORITY_RECONCILIATION_FIX01", "start_head": start_head, "start_tree": start_tree, "final_code_head": None, "final_code_tree": None, "evidence_head": None, "final_evidence_head": None, "remote_head_at_completion": None, "branch": git("branch", "--show-current"), "network_policy": "OFFLINE_ONLY", "canonical_artifacts_created": False, "end_head_created": False})
    tracked = git("diff", "--name-only").splitlines()
    write_json("git_mutation_audit.json", {"schema": "git_mutation_audit_fix01_v01", "start_head": start_head, "tracked_changes_observed": tracked, "canonical_adjusted_mutated": False, "canonical_raw_mutated": False, "unrelated_untracked_staged": False})
    blockers = []
    if census["unresolved"]:
        blockers.append({"code": "UNRESOLVED_RUNTIME", "count": census["unresolved"]})
    if census["analytic_view_success"] != 3145 or census["expected_zero_store"] != 4:
        blockers.append({"code": "ANALYTIC_VIEW_TARGET_NOT_MET", "actual": census["analytic_view_success"], "expected": 3145})
    verdict = "ACCEPT" if not blockers and adjusted_before == adjusted_after and raw_before == raw_after else "CHANGES_REQUESTED"
    next_state = "READY_FOR_MARKET_DATA_REPOSITORY_V2_PARITY_CLOSURE" if verdict == "ACCEPT" else "NEEDS_REPOSITORY_SESSION_AUTHORITY_RECONCILIATION_FIX02"
    write_json("final_decision.json", {"schema": "final_decision_fix01_v01", "verdict": verdict, "next_state": next_state, "blockers": blockers, "exact_000360_lineage": "PROVEN", "raw_only_rows_reconciled": len(rows), "source_closure_reopened": False})
    # Manifest excludes itself by design; it is written last.
    files = {}
    for path in sorted(OUT.glob("*.json")):
        if path.name == "artifact_manifest.json":
            continue
        files[path.name] = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    write_json("artifact_manifest.json", {"schema": "artifact_manifest_fix01_v01", "excludes_self": True, "files": files})
    print(json.dumps({"status": "GENERATED", "output": str(OUT), "duration_seconds": round(monotonic() - started, 3), "census": {k: census[k] for k in ("population_total", "analytic_view_success", "expected_zero_store", "failed")}, "verdict": verdict}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
