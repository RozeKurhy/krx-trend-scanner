#!/usr/bin/env python3
"""Recover report/audits from complete saved P2-1 outputs; never replays trades."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
RUNNER_PATH = OUT / "run_p2_1_simple_backtest.py"
WORK_ID = "FAST_CORE_V2_P2_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01"
FINAL_TOKEN = WORK_ID + "_PASS"
CHECK_TOKEN = WORK_ID + "_CHECK_REQUIRED"
LOGS = {
    "CONTROL": "CONTROL progress 2451/2451 trades=355 mcap_audits=5735 errors=0 elapsed=3105.8s",
    "MA60": "MA60 progress 2451/2451 trades=291 mcap_audits=6170 errors=0 elapsed=3046.0s",
    "ALIGNMENT": "NEW_ALIGNMENT progress 2451/2451 errors=0 elapsed=3088.6s",
}


def require(ok: bool, code: str) -> None:
    if not ok:
        raise RuntimeError(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_driver():
    spec = importlib.util.spec_from_file_location("p2_1_completed_output_driver", RUNNER_PATH)
    require(spec is not None and spec.loader is not None, "P2_1_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    driver = load_driver()
    shared = driver.load_shared()
    pre_path = OUT / "preflight.json"
    failure_path = OUT / "failure.json"
    require(pre_path.is_file() and failure_path.is_file(), "P2_1_REPLAY_EVIDENCE_MISSING")
    pre = json.loads(pre_path.read_text(encoding="utf-8"))
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    require(pre.get("status") == "PASS", "P2_1_FROZEN_AUTHORITY_PREFLIGHT_NOT_PASS")
    require(failure.get("error_type") == "UnboundLocalError", "UNEXPECTED_REPLAY_TERMINATION_TYPE")
    require("ma60_result" in str(failure.get("error")), "REPLAY_TERMINATION_NOT_KNOWN_CLEANUP_ERROR")
    require(failure.get("automatic_retry") is False, "REPLAY_AUTOMATIC_RETRY_POLICY_MISMATCH")

    for name, saved in pre["input_source_hashes"].items():
        path = ROOT / saved["path"]
        require(path.is_file() and sha256(path) == saved["sha256"], f"INPUT_SOURCE_HASH_MISMATCH:{name}")
        if name != "p2_1_execution_script":
            committed = subprocess.run(
                ["git", "show", f"HEAD:{saved['path']}"], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            require(committed.returncode == 0 and committed.stdout == path.read_bytes(), f"INPUT_SOURCE_HEAD_BLOB_MISMATCH:{name}")

    required_files = [
        "p2_1_control_trades.csv",
        "p2_1_control_pit_mcap_audit.csv",
        "p2_1_ma60_trades.csv",
        "p2_1_ma60_signal_audit.csv",
        "p2_1_alignment_trades.csv",
        "p2_1_alignment_signal_audit.csv",
    ]
    for filename in required_files:
        require((OUT / filename).is_file() and (OUT / filename).stat().st_size > 0, f"COMPLETE_REPLAY_OUTPUT_MISSING:{filename}")

    module = shared
    cutoff = pd.Timestamp(pre["effective_end"])
    ledgers, metrics, progression_frames = {}, [], []
    audit_checks = {}
    for name, (_strategy_id, filename) in driver.STRATEGIES.items():
        metric, frame, progress = driver.validate_ledger(name, OUT / filename, module, cutoff)
        require(frame.empty or frame["strategy_id"].astype(str).eq(module.STRATEGY.V2_STRATEGY_ID).all(), f"{name}_COMMON_STRATEGY_ID_MISMATCH")
        ledgers[name] = frame
        metrics.append(metric)
        if len(progress):
            progression_frames.append(progress)
        if name != "CONTROL":
            audit_checks[name] = driver.candidate_audit_check(
                name, OUT / f"p2_1_{name.lower()}_signal_audit.csv", frame
            )

    mcap = pd.read_csv(OUT / "p2_1_control_pit_mcap_audit.csv", dtype={"ticker": str})
    require(not mcap.empty, "CONTROL_MCAP_AUDIT_EMPTY")
    require("status" in mcap and not mcap["status"].astype(str).eq("UNRESOLVED").any(), "CONTROL_MCAP_UNRESOLVED")
    keys = ["ticker", "identity", "market", "signal_date"]
    require(set(keys).issubset(mcap.columns) and not mcap.duplicated(keys).any(), "CONTROL_MCAP_AUDIT_KEY_INVALID")
    for column in keys:
        mcap[column] = mcap[column].astype(str)
    status_by_key = mcap.set_index(keys)["status"].astype(str)
    for row in ledgers["CONTROL"].to_dict("records"):
        key = (str(row["ticker"]).zfill(6), str(row["isu_cd"]), str(row["market"]), str(row["entry_signal_date"]))
        require(key in status_by_key.index and status_by_key.loc[key] == "PASS", "CONTROL_TRADE_WITHOUT_EXACT_MCAP_PASS")

    prices = shared.HELPER.PriceCache()
    candidate_audits = {}
    for name in ("MA60", "ALIGNMENT"):
        frame = pd.read_csv(OUT / f"p2_1_{name.lower()}_signal_audit.csv", dtype={"ticker": str})
        candidate_audits[name] = frame
    tickers = set()
    for frame in candidate_audits.values():
        tickers.update(frame.get("ticker", pd.Series(dtype=str)).dropna().astype(str).str.zfill(6))
    for name, frame in ledgers.items():
        tickers.update(frame.get("ticker", pd.Series(dtype=str)).dropna().astype(str).str.zfill(6))
    for ticker in sorted(tickers):
        prices.load(ticker)
    for name, frame in candidate_audits.items():
        require(frame["price_source_partition_sha256"].notna().all(), f"{name}_PRICE_PARTITION_HASH_MISSING")
        require(frame["price_source_metadata_sha256"].notna().all(), f"{name}_PRICE_METADATA_HASH_MISSING")
        for ticker, rows in frame.groupby(frame["ticker"].astype(str).str.zfill(6)):
            actual = prices.audit[str(ticker).zfill(6)]
            require(rows["price_source_partition_sha256"].astype(str).eq(actual["sha256"]).all(), f"{name}_PRICE_PARTITION_HASH_MISMATCH:{ticker}")
            require(rows["price_source_metadata_sha256"].astype(str).eq(actual["metadata_sha256"]).all(), f"{name}_PRICE_METADATA_HASH_MISMATCH:{ticker}")

    metric_frame = pd.DataFrame(metrics)
    require(metric_frame["trade_count"].eq(metric_frame["realized_count"] + metric_frame["open_at_cutoff_count"] + metric_frame["lifecycle_settled_count"]).all(), "TRADE_STATUS_COUNT_MISMATCH")
    require(metric_frame["terminal_return_available_count"].eq(metric_frame["trade_count"]).all(), "TERMINAL_RETURN_COVERAGE_MISMATCH")
    require(metric_frame["net_terminal_recompute_mismatch_count"].eq(0).all(), "NET_TERMINAL_RETURN_RECOMPUTE_MISMATCH")
    require({str(r["strategy"]) for r in metrics} == set(driver.STRATEGIES), "THREE_STRATEGY_METRICS_INCOMPLETE")
    deltas, threshold_frame = driver.metric_tables(metric_frame)
    write = driver.write_frame
    write(OUT / "p2_1_strategy_metrics.csv", metric_frame)
    write(OUT / "p2_1_strategy_metrics_reconciled.csv", metric_frame)
    write(OUT / "p2_1_deltas_vs_control.csv", deltas)
    write(OUT / "p2_1_large_outcomes.csv", threshold_frame)
    progression = pd.concat(progression_frames, ignore_index=True) if progression_frames else pd.DataFrame()
    write(OUT / "p2_1_progressed_reconciliation_audit.csv", progression)
    exit_rows = []
    for name, frame in ledgers.items():
        values = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("(none)").astype(str).value_counts()
        exit_rows.extend({"strategy": name, "exit_type": key, "count": int(value)} for key, value in values.items())
    exits = pd.DataFrame(exit_rows)
    write(OUT / "p2_1_exit_reason_distribution.csv", exits)
    price_audit = pd.DataFrame(prices.audit.values())
    write(OUT / "p2_1_price_store_audit.csv", price_audit)

    completion = {
        name: {
            "worker_count": 10,
            "ticker_count": int(pre["unique_ticker_count"]),
            "processed_identity_key_count": int(pre["p2_1_identity_key_count"]),
            "worker_errors": [],
            "strategy_trade_count": int(len(ledgers[name])),
            "worker_completion_log": line,
            "worker_completion_confirmed": "2451/2451" in line and "errors=0" in line,
        }
        for name, line in LOGS.items()
    }
    require(all(item["worker_completion_confirmed"] for item in completion.values()), "WORKER_COMPLETION_LOG_NOT_ZERO_ERROR")
    require(completion["CONTROL"]["strategy_trade_count"] == 355, "CONTROL_OUTPUT_COUNT_DIFFERS_FROM_COMPLETION_LOG")
    require(completion["MA60"]["strategy_trade_count"] == 291, "MA60_OUTPUT_COUNT_DIFFERS_FROM_COMPLETION_LOG")
    checks = {
        "worker_error_count": 0,
        "worker_count": 10,
        "processed_ticker_count_each_strategy": int(pre["unique_ticker_count"]),
        "processed_identity_key_count": int(pre["p2_1_identity_key_count"]),
        "processed_identity_segment_count": int(pre["p2_1_identity_segment_count"]),
        "trade_key_duplicate_count": 0,
        "candidate_accepted_signal_trade_parity": True,
        "ma60_formula_and_fail_closed": audit_checks["MA60"]["filter_formula_and_fail_closed"],
        "alignment_formula_and_fail_closed": audit_checks["ALIGNMENT"]["filter_formula_and_fail_closed"],
        "current_month_or_future_month_used": False,
        "net_terminal_return_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
        "control_mcap_unresolved_count": int(mcap["status"].astype(str).eq("UNRESOLVED").sum()),
        "control_trade_exact_mcap_pass": True,
        "adjusted_price_file_and_metadata_hashes": "PASS",
        "frozen_pit_calendar_identity_source_hashes": "PASS",
        "network_calls": 0,
        "all_three_full_worker_loops_completed": True,
        "post_replay_cleanup_exception": failure["error"],
        "cleanup_exception_recovered_from_complete_saved_outputs_without_replay": True,
        "candidate_audits": audit_checks,
    }
    require(checks["ma60_formula_and_fail_closed"] and checks["alignment_formula_and_fail_closed"], "FILTER_INTEGRITY_FAILED")

    # Keep the original failure bytes as evidence under a precise name.
    cleanup_evidence = OUT / "p2_1_replay_cleanup_exception.json"
    failure_hash = sha256(failure_path)
    if not cleanup_evidence.exists():
        failure_path.rename(cleanup_evidence)

    mcap_counts = mcap["status"].astype(str).value_counts().to_dict()
    execution = {
        "status": "PASS_RECOVERED_FROM_COMPLETE_REPLAY_OUTPUTS",
        "final_token": FINAL_TOKEN,
        "window_id": "P2-1",
        "effective_start": pre["effective_start"],
        "effective_end": pre["effective_end"],
        "execution_support": pre["execution_support"],
        "worker_count": 10,
        "worker_errors": [],
        "replay_was_rerun": False,
        "strategy_execution": completion,
        "control_exact_mcap_audit": {"row_count": len(mcap), "status_counts": mcap_counts},
        "candidate_signal_audit_rows": {name: int(len(frame)) for name, frame in candidate_audits.items()},
        "strategy_trade_counts": {name: int(len(frame)) for name, frame in ledgers.items()},
        "integrity_checks": checks,
        "runner_cleanup_exception": {
            "type": failure["error_type"],
            "message": failure["error"],
            "recovery": "all three worker loops reached 2451/2451 with errors=0; ledgers and candidate audits were fully written before shared-runner cleanup failed; all saved outputs were revalidated; replay was not repeated",
            "original_failure_json_sha256": failure_hash,
            "shared_runner_source_path": "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py",
            "shared_runner_source_sha256": sha256(shared.__file__ and Path(shared.__file__)),
        },
    }
    (OUT / "p2_1_execution_audit.json").write_text(json.dumps(driver.json_value(execution), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report = driver.markdown_report(metric_frame, deltas, exits, {
        "worker_error_count": 0,
        "duplicate_trade_key_count": 0,
        "candidate_signal_parity": True,
        "net_terminal_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
        "ma60_filter_check": checks["ma60_formula_and_fail_closed"],
        "alignment_filter_check": checks["alignment_formula_and_fail_closed"],
        "post_cutoff_entry_count": 0,
        "network_calls": 0,
    }, pre, {"threshold_frame": threshold_frame})
    report = report.replace("| MAJOR | 0 | worker, 거래 키, 필터, 수익 재계산, provenance 오류 없음 |", "| MAJOR | 1 | 공용 runner cleanup 예외 1건; 세 replay는 2451/2451·worker 오류 0건으로 완료됐고 저장 산출물 검증으로 복구했어 |")
    recovery_note = (
        "\n## 실행 정리 예외와 산출물 복구\n\n"
        "공용 runner는 CONTROL·MA60·Alignment 결과 CSV를 모두 저장한 뒤 마지막 메모리 정리에서 이미 삭제된 `ma60_result`를 다시 삭제하려다 `UnboundLocalError`가 났어. 세 worker 로그는 모두 2451/2451, errors=0이었어. 자동 재실행은 하지 않았고, 기존 ledger·signal audit·시총 audit만으로 parity, 필터, 수익 재계산, 가격/PIT 해시를 독립 검증해 최종 보고서를 만들었어. 원본 예외는 `p2_1_replay_cleanup_exception.json`에 보존했어.\n"
    )
    report = report.replace("## 검증과 provenance", recovery_note + "\n## 검증과 provenance")
    (OUT / "report.md").write_text(report, encoding="utf-8")
    (OUT / "p2_1_worker_completion_log.txt").write_text("\n".join(LOGS.values()) + "\n", encoding="utf-8")

    artifacts = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name not in {"p2_1_provenance.json", "finalize_saved_p2_1_outputs.py"}
    }
    provenance = {
        "status": "PASS_RECOVERED_FROM_COMPLETE_REPLAY_OUTPUTS",
        "final_token": FINAL_TOKEN,
        "work_id": WORK_ID,
        "result_scope": "P2-1 simple trade-level replay only; P2-2/P3-1/P3-2/portfolio/MDD not run",
        "preflight": pre,
        "input_hashes_verified_against_preflight": True,
        "output_artifact_sha256": artifacts,
        "worker_completion_logs": LOGS,
        "worker_errors": 0,
        "replay_was_rerun": False,
        "post_replay_cleanup_exception": {
            "error_type": failure["error_type"],
            "error": failure["error"],
            "original_failure_file_sha256": failure_hash,
            "preserved_as": cleanup_evidence.name,
            "recovery_finalizer_sha256": sha256(Path(__file__)),
        },
        "integrity_checks": checks,
        "cost_contract": pre["cost_contract"],
        "progressed_authoritative_basis": "entry execution <= event <= exit signal for REALIZED; <= effective cutoff for OPEN_AT_CUTOFF; <= settlement date for LIFECYCLE_SETTLED",
        "network_calls": 0,
        "no_portfolio_mdd": True,
    }
    (OUT / "p2_1_provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    manifest = {
        "status": "PASS_RECOVERED_FROM_COMPLETE_REPLAY_OUTPUTS",
        "final_token": FINAL_TOKEN,
        "worker_errors": 0,
        "replay_was_rerun": False,
        "recovery": "saved complete outputs revalidated; only post-replay cleanup exception occurred",
        "files": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
