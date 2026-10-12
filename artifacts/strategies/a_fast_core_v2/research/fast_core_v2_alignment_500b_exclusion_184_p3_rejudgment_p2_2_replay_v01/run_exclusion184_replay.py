from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
BASE = "29ac6c85af0524c279a41cb0d820b9b646671a91"
P2 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_full_run_v02"
REG = "src/trend_scanner/universe/permanent_identity_exclusions.py"
TARGET = {("138580", "KR7138580006"), ("003410", "KR7003410008")}
EVAL_START = pd.Timestamp("2021-01-04")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
RUN_JOURNAL = OUT / "run_journal.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    try:
        import numpy as np
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def current_git_state() -> dict[str, Any]:
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    diff = subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True).splitlines()
    return {"branch": branch, "head": head, "origin_main": origin, "tracked_unstaged_paths": diff, "tracked_staged_paths": staged}


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_source_manifest(engine_script: Path) -> dict[str, Any]:
    old = json.loads((P2 / "source_manifest.json").read_text(encoding="utf-8"))
    files: dict[str, dict[str, Any]] = {}
    for row in old.get("files", []):
        path = Path(row.get("absolute_path") or row["path"])
        if not path.is_file():
            raise RuntimeError(f"SOURCE_FILE_MISSING:{row['path']}")
        if row["path"] == REG:
            # The source manifest reflects the new approved policy, while the previous
            # V02 baseline hash is retained separately in exclusion_policy_audit.json.
            actual_sha = sha(ROOT / REG)
        else:
            actual_sha = sha(path)
            if actual_sha != row["sha256"] or path.stat().st_size != int(row["bytes"]):
                raise RuntimeError(f"UNRELATED_FROZEN_SOURCE_CHANGED:{row['path']}")
        key = str(path.resolve())
        files[key] = {
            "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else row["path"],
            **({"absolute_path": str(path)} if not path.is_relative_to(ROOT) else {}),
            "sha256": actual_sha,
            "bytes": path.stat().st_size,
        }

    bundle_dirs = {
        "P3_1": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01",
        "P3_2": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01",
        "P3_2_CLOSURE": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01",
        "P3_2_READJ": ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01",
        "P2_2_V02": P2,
    }
    evidence = pd.read_csv(OUT / "source_artifact_hash_evidence.csv", dtype=str, keep_default_na=False)
    for item in evidence.to_dict("records"):
        f = bundle_dirs[item["bundle"]] / item["path"]
        if not f.is_file() or sha(f) != item["sha256"] or f.stat().st_size != int(item["bytes"]):
            raise RuntimeError(f"REFERENCE_ARTIFACT_CHANGED:{item['bundle']}:{item['path']}")
        key = str(f.resolve())
        files[key] = {"path": str(f.relative_to(ROOT)), "sha256": item["sha256"], "bytes": int(item["bytes"])}

    local_sources = [
        OUT / "prepare_exclusion184_inputs.py",
        OUT / "run_exclusion184_replay.py",
        OUT / "finalize_p2_2_exclusion184.py",
        OUT / "run_finalizer_exclusion184.py",
        OUT / "plan.md",
        OUT / "execution_contract.json",
        OUT / "exclusion_policy_audit.json",
        OUT / "p3_1_rejudgment.json",
        OUT / "p3_2_rejudgment.json",
        OUT / "p2_2_input_exclusion_audit.json",
        OUT / "control_trades.csv",
        OUT / "candidate_trades.csv",
        OUT / "candidate_signal_filter_audit.csv",
        OUT / "control_signal_trade_inputs.csv",
        OUT / "candidate_signal_trade_inputs.csv",
        OUT / "p2_2_removed_signal_row_evidence.csv",
        OUT / "source_artifact_hash_evidence.csv",
        OUT / "preflight.json",
        OUT / "p2_2_current_preflight.json",
        OUT / "active_pit_missing_sessions.csv",
        OUT / "identity_price_preflight.csv",
        OUT / "repository_v2_adjusted_price_file_hashes.csv",
        OUT / "ticker_price_source_audit.csv",
        OUT / "raw_partition_preflight.csv",
        OUT / "signal_date_krx_partition_hashes.csv",
        OUT / "p2_v02_preflight_182.json",
        OUT / "p2_v02_execution_contract_182.json",
        OUT / "p2_v02_source_manifest_182.json",
    ]
    for f in local_sources:
        if f.is_file():
            files[str(f.resolve())] = {"path": str(f.relative_to(ROOT)), "sha256": sha(f), "bytes": f.stat().st_size}

    rows = sorted(files.values(), key=lambda x: x["path"])
    manifest = {
        "schema": "fast_core_v2_alignment_500b_exclusion_184_p2_2_source_manifest_v01",
        "baseline": current_git_state(),
        "current_policy": {
            "pair_count": 184,
            "canonical_sha256": "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e",
            "registry_path": REG,
            "registry_sha256": sha(ROOT / REG),
        },
        "p2_2_saved_signal_source": str(P2.relative_to(ROOT)),
        "p2_2_signal_evaluation_run_count": 0,
        "reference_artifact_hash_files_verified": len(evidence),
        "files": rows,
    }
    write_json(OUT / "source_manifest.json", manifest)
    return manifest


def filter_active_missing(path: Path, segments: dict) -> tuple[int, int, dict[str, int]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    ticker_col = "ticker" if "ticker" in frame.columns else None
    isu_col = next((x for x in ("isu_cd", "standard_isu_cd") if x in frame.columns), None)
    before = len(frame)
    if ticker_col:
        ticker = frame[ticker_col].astype(str).str.zfill(6)
        if isu_col:
            isu = frame[isu_col].astype(str).str.upper()
            mask = ~((ticker == "138580") & (isu == "KR7138580006")) & ~((ticker == "003410") & (isu == "KR7003410008"))
        else:
            # These ticker codes have no surviving exact active identity in the new authority.
            mask = ~ticker.isin(["138580", "003410"])
        frame = frame.loc[mask].copy()
    reason_col = next((x for x in ("reason", "missing_reason", "classification") if x in frame.columns), None)
    counts = frame[reason_col].value_counts().sort_index().to_dict() if reason_col else {}
    frame.to_csv(OUT / "active_pit_missing_sessions.csv", index=False)
    return before, len(frame), {str(k): int(v) for k, v in counts.items()}


def preflight() -> tuple[Any, Any, Any, Any, dict, pd.DataFrame, dict]:
    git = current_git_state()
    if git["branch"] != "main" or git["head"] != BASE or git["origin_main"] != BASE:
        raise RuntimeError(f"BASELINE_OR_BRANCH_MISMATCH:{git}")
    if git["tracked_staged_paths"] or git["tracked_unstaged_paths"] != [REG]:
        raise RuntimeError(f"UNEXPECTED_TRACKED_CHANGES:{git}")
    for name in ("p3_1_rejudgment.json", "p3_2_rejudgment.json"):
        if not json.loads((OUT / name).read_text()).get("preconditions_pass"):
            raise RuntimeError(f"P3_REJUDGMENT_NOT_READY:{name}")
    expected_hash = sha(ROOT / REG)
    if expected_hash != "0bb2e441cf428df56ad94ab33b08fd033737ee9216029016311b5cb3524d8d3a":
        raise RuntimeError("CURRENT_POLICY_SOURCE_HASH_CHANGED")

    base_runner = import_module(
        "p2_v02_frozen_replay_module",
        P2 / "run_p2_2_replay.py",
    )
    base_runner.OUT = OUT
    engine = base_runner.load_engine()
    calendar, _pit_payload, _calendar_payload, segments = engine.build_authority()
    ticker_set = set(segments)
    interval_count = sum(len(items) for items in segments.values())
    if len(ticker_set) != 2571 or interval_count != 2580:
        raise RuntimeError(f"CURRENT_AUTHORITY_UNEXPECTED:{len(ticker_set)}:{interval_count}")
    for ticker, isu in TARGET:
        if ticker in segments and any(str(seg.isu_cd).strip().upper() == isu for seg in segments[ticker]):
            raise RuntimeError(f"EXCLUDED_IDENTITY_REMAINS_ACTIVE:{ticker}:{isu}")

    old_prices = pd.read_csv(P2 / "identity_price_preflight.csv", dtype=str, keep_default_na=False)
    if old_prices["ticker"].astype(str).str.zfill(6).duplicated().any():
        raise RuntimeError("FROZEN_PRICE_PREFLIGHT_TICKER_DUPLICATE")
    prices = old_prices.loc[old_prices["ticker"].astype(str).str.zfill(6).isin(ticker_set)].copy()
    if set(prices["ticker"].astype(str).str.zfill(6)) != ticker_set or len(prices) != len(ticker_set):
        raise RuntimeError("CURRENT_UNIVERSE_PRICE_PREFLIGHT_COVERAGE_MISMATCH")
    prices.to_csv(OUT / "identity_price_preflight.csv", index=False)
    price_hash_path = P2 / "repository_v2_adjusted_price_file_hashes.csv"
    price_hashes = pd.read_csv(price_hash_path, dtype=str, keep_default_na=False)
    price_hashes = price_hashes.loc[price_hashes["ticker"].astype(str).str.zfill(6).isin(ticker_set)].copy()
    price_hashes.to_csv(OUT / "repository_v2_adjusted_price_file_hashes.csv", index=False)

    ticker_audit = pd.read_csv(P2 / "ticker_price_source_audit.csv", dtype=str, keep_default_na=False)
    ticker_audit = ticker_audit.loc[ticker_audit["ticker"].astype(str).str.zfill(6).isin(ticker_set)].copy()
    if len(ticker_audit) != len(ticker_set):
        raise RuntimeError("CURRENT_UNIVERSE_TICKER_AUDIT_COVERAGE_MISMATCH")
    ticker_audit.to_csv(OUT / "ticker_price_source_audit.csv", index=False)

    raw = pd.read_csv(OUT / "raw_partition_preflight.csv", dtype=str, keep_default_na=False)
    if len(raw) != 2776 or not raw.get("status", pd.Series(dtype=str)).eq("COMPLETE").all():
        raise RuntimeError("RAW_PARTITION_PREFLIGHT_NOT_COMPLETE_2776")
    pit_missing_before, pit_missing_after, reason_counts = filter_active_missing(P2 / "active_pit_missing_sessions.csv", segments)

    pre = json.loads((P2 / "preflight.json").read_text(encoding="utf-8"))
    pre["schema"] = "fast_core_v2_alignment_500b_exclusion_184_preflight_v01"
    pre["task_id"] = "FAST_CORE_V2_ALIGNMENT_500B_EXCLUDE_2_P3_READJUDGE_P2_2_REPLAY_V01"
    pre["generated_before_full_portfolio_replay"] = True
    pre["baseline"] = {**git, "tracked_changes_expected": [REG], "existing_untracked_items_preserved": True}
    pre["universe"]["common_intervals_after_exclusions"] = interval_count
    pre["universe"]["eligible_tickers_after_exclusions"] = len(ticker_set)
    pre["universe"]["current_exclusion_pair_count"] = 184
    pre["universe"]["permanent_exclusion_file_sha256"] = expected_hash
    pre["universe"]["permanent_exclusion_canonical_sha256"] = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"
    pre["universe"]["permanent_exclusion_hash_matches_directive"] = True
    pre["universe"]["excluded_target_interval_rows"] = 2
    pre["universe"]["prior_pair_count"] = 182
    pre["universe"]["identity_overlap_check"] = "PASS; exact excluded pairs absent; ticker reuse for any other ISU remains eligible"
    pre["repository_v2_input_preflight"]["unique_tickers_checked"] = len(ticker_set)
    pre["repository_v2_input_preflight"]["load_status_counts"] = ticker_audit["load_status"].value_counts().sort_index().to_dict()
    pre["repository_v2_input_preflight"]["unavailable_or_error_tickers"] = ticker_audit.loc[ticker_audit["load_status"].isin(["ERROR", "ADJUSTED_FILE_UNAVAILABLE", "EMPTY"]), "ticker"].tolist()
    pre["repository_v2_input_preflight"]["active_pit_missing_session_count_before_exact_exclusion"] = pit_missing_before
    pre["repository_v2_input_preflight"]["active_pit_missing_session_count_after_exact_exclusion"] = pit_missing_after
    pre["repository_v2_input_preflight"]["active_pit_missing_session_reason_counts"] = reason_counts
    pre["repository_v2_input_preflight"]["source"] = "Verified V02 Repository V2 price and PIT preflight filtered by the 184-pair current exact universe; no signal evaluation."
    pre["reference_inputs"] = {
        "p2_v02_artifact_hashes_verified": True,
        "p2_v02_reference_artifact_files": 55,
        "p3_rejudgment_preconditions_pass": True,
        "saved_signal_rows": {"CONTROL": len(pd.read_csv(OUT/"control_trades.csv")), "ALIGNMENT_MCAP_500B": len(pd.read_csv(OUT/"candidate_trades.csv")), "candidate_filter_audit": len(pd.read_csv(OUT/"candidate_signal_filter_audit.csv"))},
        "signal_evaluation_run_count": 0,
        "raw_market_date_partitions": len(raw),
    }
    write_json(OUT / "preflight.json", pre)

    preflight_summary = {
        "status": "PREFLIGHT_PASS",
        "baseline": git,
        "registry_source_sha256": expected_hash,
        "registry_canonical_sha256": pre["universe"]["permanent_exclusion_canonical_sha256"],
        "exact_policy_pair_count": 184,
        "eligible_tickers": len(ticker_set),
        "common_intervals": interval_count,
        "filtered_price_preflight_rows": len(prices),
        "filtered_price_hash_rows": len(price_hashes),
        "filtered_ticker_source_audit_rows": len(ticker_audit),
        "active_pit_missing_rows_before": pit_missing_before,
        "active_pit_missing_rows_after": pit_missing_after,
        "raw_date_market_partitions": len(raw),
        "raw_partitions_complete": True,
        "p3_1_and_p3_2_rejudgments_pass": True,
        "signal_rows": pre["reference_inputs"]["saved_signal_rows"],
        "signal_evaluation_run_count": 0,
        "portfolio_replay_started": False,
    }
    write_json(OUT / "p2_2_current_preflight.json", preflight_summary)
    manifest = build_source_manifest(Path(__file__).resolve())
    preflight_summary["source_manifest_file_count"] = len(manifest["files"])
    write_json(OUT / "p2_2_current_preflight.json", preflight_summary)
    manifest = build_source_manifest(Path(__file__).resolve())
    journal = {"status": "PREFLIGHT_READY", "control_replays_started": 0, "candidate_replays_started": 0, "automatic_retry": False, "preflight": preflight_summary}
    write_json(RUN_JOURNAL, journal)
    return base_runner, engine, calendar, segments, prices, journal


def run_full() -> int:
    if RUN_JOURNAL.is_file():
        journal = json.loads(RUN_JOURNAL.read_text(encoding="utf-8"))
        if journal.get("status") != "PREFLIGHT_READY" or journal.get("control_replays_started") or journal.get("candidate_replays_started"):
            raise RuntimeError("REPLAY_ALREADY_STARTED_OR_COMPLETED; AUTOMATIC_RETRY_DISABLED")
    else:
        _, _, _, _, _, journal = preflight()
    base_runner, engine, calendar, segments, prices, _ = preflight()
    # preflight() is read-only except new research outputs; it rebuilds authority but does not evaluate signals or portfolio.
    if json.loads(RUN_JOURNAL.read_text(encoding="utf-8")).get("status") != "PREFLIGHT_READY":
        raise RuntimeError("PREFLIGHT_STATE_INVALID")
    started = time.perf_counter()
    cpu_started = time.process_time()
    repo = base_runner.build_repository_v2(ROOT, end=SUPPORT.strftime("%Y-%m-%d"))
    control_rows = pd.read_csv(OUT / "control_trades.csv").to_dict("records")
    candidate_rows = pd.read_csv(OUT / "candidate_trades.csv").to_dict("records")
    candidate_audit = pd.read_csv(OUT / "candidate_signal_filter_audit.csv", dtype=str, keep_default_na=False)
    if not control_rows or not candidate_rows or candidate_audit.empty:
        raise RuntimeError("FILTERED_SIGNAL_INPUTS_EMPTY")
    for rows in (control_rows, candidate_rows):
        if any((str(row.get("ticker","")).zfill(6),str(row.get("isu_cd","")).strip().upper()) in TARGET for row in rows):
            raise RuntimeError("EXCLUDED_PAIR_PRESENT_IN_REPLAY_INPUT")
    current = json.loads(RUN_JOURNAL.read_text(encoding="utf-8"))
    current.update({"status":"CONTROL_REPLAY_STARTED","control_replays_started":1,"candidate_replays_started":0,"automatic_retry":False})
    write_json(RUN_JOURNAL,current)
    base_runner.install_bounded_portfolio_loader(engine, prices)
    control = base_runner.run_group(engine, calendar, segments, repo, control_rows)
    base_runner.write_group_outputs("", "control", control)
    current.update({"status":"CONTROL_REPLAY_COMPLETE","control_replays_started":1,"candidate_replays_started":0,"control_metrics":control["metrics"]})
    write_json(RUN_JOURNAL,current)

    current.update({"status":"CANDIDATE_REPLAY_STARTED","candidate_replays_started":1})
    write_json(RUN_JOURNAL,current)
    candidate = base_runner.run_group(engine, calendar, segments, repo, candidate_rows)
    base_runner.write_group_outputs("", "candidate", candidate)
    current.update({"status":"FULL_REPLAY_COMPLETE","candidate_replays_started":1,"candidate_metrics":candidate["metrics"]})
    write_json(RUN_JOURNAL,current)

    execution = {
        "schema":"fast_core_v2_alignment_500b_p2_2_exclusion_184_execution_v01",
        "mode":"FULL","status":"FULL_COMPLETED","replay_mode":"SAVED_SIGNAL_LEDGER_REUSE",
        "evaluated_ticker_count":0,"eligible_universe_ticker_count":len(segments),
        "worker_error_count":0,"workers":0,
        "signal_evaluation_run_count":0,"control_portfolio_replay_count":1,"candidate_portfolio_replay_count":1,
        "wall_seconds_including_portfolio_replays":round(time.perf_counter()-started,3),
        "cpu_seconds":round(time.process_time()-cpu_started,3),
        "control_metrics":control["metrics"],"candidate_metrics":candidate["metrics"],
        "scope_issue_counts":{"CONTROL":len(control.get("scope_issues",[])),"ALIGNMENT_MCAP_500B":len(candidate.get("scope_issues",[]))},
        "support_day_exit_only":True,"support_day_in_cutoff_nav":False,
        "exact_policy_pair_count":184,"exact_policy_canonical_sha256":"5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e",
        "new_ticker_universe_count":len(segments),"saved_signal_rows":{"CONTROL":len(control_rows),"ALIGNMENT_MCAP_500B":len(candidate_rows),"candidate_filter_audit":len(candidate_audit)},
        "automatic_full_run_retry":False,"external_api_requests":0,
    }
    write_json(OUT/"full_run_execution.json",execution)
    write_json(RUN_JOURNAL,{**current,"status":"FULL_COMPLETED","execution":execution})
    return 0


def main() -> int:
    if "--preflight-only" in sys.argv:
        preflight()
        print(json.dumps(json.loads((OUT/"p2_2_current_preflight.json").read_text()),ensure_ascii=False,indent=2))
        return 0
    if "--execute-full" in sys.argv:
        return run_full()
    raise SystemExit("Use --preflight-only or --execute-full")

if __name__ == "__main__":
    raise SystemExit(main())

