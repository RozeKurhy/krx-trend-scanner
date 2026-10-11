#!/usr/bin/env python3
"""Regenerate P3-2 report/provenance from completed saved outputs; never replay."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[6]
RUNNER_PATH = OUT / "run_p3_2_corrected_simple_backtest_v02.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("p3_2_saved_output_report_recovery", RUNNER_PATH)
if RUNNER_SPEC is None or RUNNER_SPEC.loader is None:
    raise RuntimeError("P3_2_REPORT_RECOVERY_RUNNER_IMPORT_FAILED")
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


def read_json(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> pd.DataFrame:
    path = OUT / name
    if path.is_file():
        return pd.read_csv(path)
    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.is_file():
        return pd.read_csv(compressed, compression="gzip")
    raise RuntimeError(f"P3_2_SAVED_OUTPUT_MISSING:{name}")


def main() -> None:
    execution = read_json("p3_2_execution_audit.json")
    preflight = read_json("preflight.json")
    sample = read_json("sample_benchmark.json")
    failure = read_json("failure.json")
    prior_recovery_path = OUT / "report_recovery_audit.json"
    prior_recovery = read_json("report_recovery_audit.json") if prior_recovery_path.is_file() else {}
    original_failure = prior_recovery.get("original_failure", failure)
    checks = dict(execution["checks"])

    runner_hash = runner.sha256(RUNNER_PATH)
    if runner_hash != preflight.get("p3_2_execution_script_sha256") or runner_hash != sample.get("source_script_sha256"):
        raise RuntimeError("P3_2_REPORT_RECOVERY_EXECUTION_SCRIPT_HASH_MISMATCH")
    if execution.get("status") != "PASS" or execution.get("final_token") != runner.FINAL_TOKEN:
        raise RuntimeError("P3_2_SAVED_EXECUTION_AUDIT_NOT_PASS")
    if checks.get("all_required_pass") is not True or checks.get("worker_error_count") != 0:
        raise RuntimeError("P3_2_SAVED_INTEGRITY_GATES_NOT_PASS")
    if not checks.get("prefix_invariance_pass") or execution.get("execution", {}).get("reused_saved_trade_ledgers") is not False:
        raise RuntimeError("P3_2_SAVED_REPLAY_OR_PREFIX_STATE_INVALID")
    if not failure.get("replay_started") or failure.get("error_type") != "KeyError" or failure.get("error") != "'post_cutoff_entry_count'":
        raise RuntimeError("P3_2_EXPECTED_REPORT_GENERATION_FAILURE_NOT_FOUND")

    metrics = read_csv("p3_2_strategy_metrics.csv")
    deltas = read_csv("p3_2_deltas_vs_control.csv")
    thresholds = read_csv("p3_2_large_outcomes.csv")
    exits = read_csv("p3_2_exit_reason_distribution.csv")
    annual = read_csv("p3_2_trade_frequency_by_year.csv")
    monthly = read_csv("p3_2_trade_frequency_by_month.csv")
    price_audit = read_csv("p3_2_price_store_audit.csv")

    expected_strategies = {"CONTROL", "MA60", "ALIGNMENT"}
    if set(metrics["strategy"].astype(str)) != expected_strategies:
        raise RuntimeError("P3_2_SAVED_STRATEGY_METRICS_INCOMPLETE")
    for strategy, (_strategy_id, ledger_name) in runner.STRATEGIES.items():
        ledger = read_csv(ledger_name)
        expected_count = int(metrics.loc[metrics["strategy"].eq(strategy), "trade_count"].iloc[0])
        if len(ledger) != expected_count or ledger["pair_id"].astype(str).duplicated().any():
            raise RuntimeError(f"P3_2_SAVED_LEDGER_COUNT_OR_DUPLICATE_FAILURE:{strategy}")
    if checks.get("price_partition_hash_metadata_checks_pass") is not True:
        raise RuntimeError("P3_2_SAVED_PRICE_PARTITION_HASH_METADATA_CHECK_NOT_PASS")
    if not price_audit.empty and not (
        "metadata_row_count_matches" in price_audit.columns
        and "metadata_date_range_matches" in price_audit.columns
        and price_audit["metadata_row_count_matches"].astype(bool).all()
        and price_audit["metadata_date_range_matches"].astype(bool).all()
    ):
        raise RuntimeError("P3_2_SAVED_PRICE_AUDIT_METADATA_MISMATCH")

    # The original template expected one combined field. Preserve the exact
    # signal and execution counts separately to avoid double-counting a trade.
    report_checks = dict(checks)
    report_checks["post_cutoff_entry_count"] = (
        f"signal={checks['post_cutoff_entry_signal_count']}; "
        f"execution={checks['post_cutoff_entry_execution_count']}"
    )
    report = runner.markdown_report(
        metrics,
        deltas,
        exits,
        thresholds,
        report_checks,
        preflight,
        checks["prefix_invariance"],
        annual,
        sample,
        float(execution["elapsed_seconds"]),
    )
    report += (
        "\n\n## 보고서 생성 복구\n\n"
        "- 세 전략 replay와 무결성 검사는 완료됐고 모든 필수 gate는 PASS야.\n"
        "- 최초 보고서 작성은 템플릿의 누락된 `post_cutoff_entry_count` 참조로 중단됐어.\n"
        "- 이 보고서·provenance는 저장된 거래 원장과 감사 산출물에서 재생성했으며, 백테스트 replay는 다시 실행하지 않았어.\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    for csv_name in (
        "p3_2_market_cap_filter_audit.csv",
        "p3_2_ma60_signal_audit.csv",
        "p3_2_alignment_signal_audit.csv",
        "p3_2_price_store_audit.csv",
    ):
        raw_path = OUT / csv_name
        gzip_path = raw_path.with_suffix(raw_path.suffix + ".gz")
        if raw_path.is_file():
            if gzip_path.exists():
                raise RuntimeError(f"P3_2_REFUSING_TO_OVERWRITE_GZIP_AUDIT:{gzip_path.name}")
            runner.p2.compress_verified(raw_path)

    recovery = {
        "status": "RESOLVED_FROM_SAVED_OUTPUTS",
        "original_failure": original_failure,
        "replay_reexecuted": False,
        "saved_execution_status": execution["status"],
        "saved_final_token": execution["final_token"],
        "report_recovery_script_sha256": runner.sha256(Path(__file__)),
        "runner_source_sha256_matches_preflight_and_sample": True,
        "checks": {
            "saved_strategy_metrics_complete": True,
            "saved_trade_ledgers_match_metrics_and_have_unique_pair_ids": True,
            "saved_price_audit_metadata_and_hash_checks": True,
            "worker_errors": checks["worker_error_count"],
            "network_calls": checks["network_calls"],
            "post_cutoff_entry_signal_count": checks["post_cutoff_entry_signal_count"],
            "post_cutoff_entry_execution_count": checks["post_cutoff_entry_execution_count"],
        },
    }
    runner.write_json(OUT / "failure.json", {
        **failure,
        "initial_status": original_failure.get("status"),
        "status": "RESOLVED",
        "final_token": execution["final_token"],
        "recovered_from_saved_outputs": True,
        "replay_reexecuted": False,
        "partial_output_is_final_result": True,
        "resolution": "Report, provenance, and artifact manifest were regenerated from the completed saved replay outputs.",
    })
    runner.write_json(OUT / "report_recovery_audit.json", recovery)
    execution["report_generation_recovery"] = {
        "status": recovery["status"],
        "replay_reexecuted": False,
        "report_recovery_script_sha256": recovery["report_recovery_script_sha256"],
    }
    runner.write_json(OUT / "p3_2_execution_audit.json", execution)

    partition_columns = [
        "ticker", "relative_path", "sha256", "metadata_relative_path", "metadata_sha256",
        "source_authority_id", "source_semantics", "authority_type", "row_count",
        "actual_date_min", "actual_date_max",
    ]
    partition_hashes = price_audit[
        [column for column in partition_columns if column in price_audit.columns]
    ].to_dict("records")
    provenance = {
        "status": execution["status"],
        "final_token": execution["final_token"],
        "work_id": runner.WORK_ID,
        "scope": "P3-2 corrected simple trade-level replay; no portfolio allocation/MDD/adoption claim",
        "window": runner.WINDOW,
        "worker_count": runner.WORKERS,
        "network_calls": checks["network_calls"],
        "market_cap_filter": "NONE",
        "market_cap_based_reject_count": checks["market_cap_based_reject_count"],
        "current_survivor_membership_used": False,
        "permanent_exclusion_registry_count": preflight["permanent_exclusion_registry_count"],
        "permanent_exclusion_duplicate_exact_pair_count": preflight["permanent_exclusion_duplicate_exact_pair_count"],
        "historical_common_identity_key_count": preflight["historical_common_identity_key_count"],
        "historical_common_segment_count": preflight["historical_common_segment_count"],
        "eligible_identity_key_count": preflight["eligible_historical_identity_key_count"],
        "eligible_segment_count": preflight["p3_2_window_pit_segment_count"],
        "unique_ticker_count": preflight["unique_ticker_count"],
        "cost_contract": preflight["cost_contract"],
        "result_reuse": preflight["result_reuse"],
        "p3_1_prefix_invariance": checks["prefix_invariance"],
        "integrity": checks,
        "source_hashes": preflight["input_source_hashes"],
        "p3_1_baseline": preflight["p3_1_baseline"],
        "sample_benchmark": sample,
        "adjusted_price_store_partition_hashes": partition_hashes,
        "execution_script_sha256": runner_hash,
        "report_generation_recovery": recovery,
        "artifact_sha256": {
            path.name: runner.sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name not in {"p3_2_provenance.json", "artifact_manifest.json"}
        },
        "elapsed_seconds": float(execution["elapsed_seconds"]),
    }
    runner.write_json(OUT / "p3_2_provenance.json", provenance)
    files = {
        path.name: runner.sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_manifest.json"
    }
    runner.write_json(OUT / "artifact_manifest.json", {
        "status": execution["status"],
        "final_token": execution["final_token"],
        "files": files,
    })
    manifest = read_json("artifact_manifest.json")
    if not all(runner.sha256(OUT / name) == digest for name, digest in manifest["files"].items()):
        raise RuntimeError("P3_2_RECOVERED_ARTIFACT_MANIFEST_HASH_MISMATCH")
    print(json.dumps({
        "status": execution["status"],
        "final_token": execution["final_token"],
        "replay_reexecuted": False,
        "artifact_manifest_files": len(files),
        "artifact_manifest_hashes_pass": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
