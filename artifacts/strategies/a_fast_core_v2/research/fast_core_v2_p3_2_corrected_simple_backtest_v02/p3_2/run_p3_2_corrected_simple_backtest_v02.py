#!/usr/bin/env python3
"""Fresh, offline P3-1 trade-level replay using exact permanent identity exclusions."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

OUT = Path(__file__).resolve().parent
BASE_RUNNER_PATH = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_2_ma60_vs_bullish_alignment_simple_backtest_v01/run_p2_2_simple_backtest.py"
spec = importlib.util.spec_from_file_location("p3_1_certified_simple_runner_utilities", BASE_RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("P2_2_RUNNER_IMPORT_FAILED")
p2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p2
spec.loader.exec_module(p2)

WORK_ID = "FAST_CORE_V2_P3_2_CORRECTED_SIMPLE_BACKTEST_V02"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_CORRECTED_SIMPLE_BACKTEST_V02_PASS"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_CORRECTED_SIMPLE_BACKTEST_V02_CHECK_REQUIRED"
WINDOW_ID = "P3-2"
WINDOW = {"effective_start": "2022-01-03", "effective_end": "2026-08-31", "execution_support": "2026-09-01"}
WORKERS = 10
STRATEGIES = {
    "CONTROL": ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "p3_2_control_trades.csv"),
    "MA60": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER", "p3_2_ma60_trades.csv"),
    "ALIGNMENT": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT", "p3_2_alignment_trades.csv"),
}
STAGE = "STARTUP"
REPLAY_STARTED = False
TARGETED_TEST_PATH = "tests/test_fastcore_simple_backtest_universe_contract_v01.py"
P3_1_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_simple_backtest_universe_mcap_contract_fix_v01/p3_1"

# Reuse only the certified P2-2 runner's deterministic ledger validation and
# metric functions. No prior-period performance files are opened or compared.
p2.OUT = OUT
p2.WORK_ID = WORK_ID
p2.FINAL_TOKEN = FINAL_TOKEN
p2.CHECK_TOKEN = CHECK_TOKEN
p2.WINDOW_ID = WINDOW_ID
p2.WINDOW = WINDOW
p2.WORKERS = WORKERS
p2.STRATEGIES = STRATEGIES


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def sha256(path: Path) -> str:
    return p2.sha256(path)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_clean_tracked() -> bool:
    return all(
        subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet"))
    )


def json_value(value: Any) -> Any:
    return p2.json_value(value)


def write_json(path: Path, payload: Any) -> None:
    p2.write_json(path, payload)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    p2.write_frame(path, frame)


def load_shared():
    return p2.load_shared()


def source_hashes_for(module: Any, tracked_changes: set[str]) -> dict[str, Any]:
    hashes = {}
    source_paths = p2.source_paths(module)
    source_paths.pop("exact_mcap_gate", None)
    source_paths.pop("survivor_identity_roster_authority", None)
    for name, path in source_paths.items():
        require(path.is_file(), f"INPUT_MISSING:{name}:{path}")
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256(path)
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        require(committed.returncode == 0, f"INPUT_NOT_TRACKED_AT_START:{name}")
        head_digest = hashlib.sha256(committed.stdout).hexdigest()
        require(
            (relative in tracked_changes) or committed.stdout == path.read_bytes(),
            f"INPUT_HASH_DIFFERS_FROM_HEAD:{name}",
        )
        hashes[name] = {
            "path": relative,
            "sha256": digest,
            "head_sha256": head_digest,
            "working_tree_modified": relative in tracked_changes,
        }
    for name, path in (
        ("certified_p2_2_runner_utilities", BASE_RUNNER_PATH),
        ("p3_1_corrected_execution_script", ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_lifecycle_prefix_invariance_fix_v01/p3_1/run_p3_1_lifecycle_prefix_invariance_fix_v01.py"),
        ("p3_2_execution_script", Path(__file__)),
    ):
        require(path.is_file(), f"INPUT_MISSING:{name}")
        relative = path.relative_to(ROOT).as_posix()
        tracked_at_start = name != "p3_2_execution_script"
        entry = {
            "path": relative,
            "sha256": sha256(path),
            "tracked_at_start": tracked_at_start,
            "working_tree_modified": relative in tracked_changes,
        }
        if tracked_at_start:
            entry["head_sha256"] = hashlib.sha256(
                subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
            ).hexdigest()
        hashes[name] = entry
    test_path = ROOT / TARGETED_TEST_PATH
    require(test_path.is_file(), "TARGETED_REGRESSION_TEST_MISSING")
    hashes["targeted_regression_test"] = {
        "path": TARGETED_TEST_PATH,
        "sha256": sha256(test_path),
        "tracked_at_start": False,
    }
    return hashes


def preflight(module: Any):
    OUT.mkdir(parents=True, exist_ok=True)
    allowed_checkpoint = {
        Path(__file__).name,
        "__pycache__",
        "preflight.json",
        "p3_2_identity_authority_audit.csv",
        "p3_2_permanent_exclusion_registry_audit.csv",
        "effective_contract_audit.json",
        "sample_benchmark.json",
        "targeted_regression_test.txt",
    }
    existing = {item.name for item in OUT.iterdir()}
    unexpected = sorted(existing - allowed_checkpoint)
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")
    tracked_changes = set(git("diff", "--name-only").splitlines()) | set(git("diff", "--cached", "--name-only").splitlines())
    require(not tracked_changes, "TRACKED_WORKTREE_OR_INDEX_NOT_CLEAN:" + ",".join(sorted(tracked_changes)))
    require((ROOT / TARGETED_TEST_PATH).is_file(), "TARGETED_REGRESSION_TEST_MISSING")

    input_hashes = source_hashes_for(module, tracked_changes)
    pit_dir = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
    manifest_path = pit_dir / "p2_2_identity_authority_extension_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS", "FROZEN_AUTHORITY_MANIFEST_NOT_PASS")
    require(sha256(pit_dir / "merged_trading_calendar.json") == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")
    pit_path = pit_dir / "merged_pit_intervals.json"
    expected_pit_sha = "6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1"
    require(sha256(pit_path) == expected_pit_sha, "FROZEN_PIT_HASH_MISMATCH")

    p3_1_provenance_path = P3_1_DIR / "p3_1_provenance.json"
    p3_1_manifest_path = P3_1_DIR / "artifact_manifest.json"
    require(p3_1_provenance_path.is_file() and p3_1_manifest_path.is_file(), "P3_1_PASS_ARTIFACTS_MISSING")
    p3_1_prov = json.loads(p3_1_provenance_path.read_text(encoding="utf-8"))
    p3_1_manifest = json.loads(p3_1_manifest_path.read_text(encoding="utf-8"))
    require(p3_1_prov.get("status") == "PASS" and p3_1_prov.get("final_token") == "FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_PASS", "P3_1_BASELINE_NOT_PASS")
    require(p3_1_manifest.get("status") == "PASS" and p3_1_manifest.get("final_token") == p3_1_prov.get("final_token"), "P3_1_ARTIFACT_MANIFEST_NOT_PASS")
    for filename, expected_hash in p3_1_manifest.get("files", {}).items():
        baseline_artifact = P3_1_DIR / filename
        require(baseline_artifact.is_file() and sha256(baseline_artifact) == expected_hash, f"P3_1_ARTIFACT_HASH_MISMATCH:{filename}")
    require(p3_1_prov.get("window") == {"effective_start": "2022-01-03", "effective_end": "2025-05-30", "execution_support": "2025-06-02"}, "P3_1_BASELINE_WINDOW_MISMATCH")
    p3_1_authority = p3_1_prov.get("authority", {})
    p3_1_integrity = p3_1_prov.get("integrity", {})
    require(p3_1_authority.get("frozen_pit_sha256") == expected_pit_sha, "P3_1_PIT_AUTHORITY_MISMATCH")
    require(p3_1_authority.get("frozen_calendar_sha256") == sha256(pit_dir / "merged_trading_calendar.json"), "P3_1_CALENDAR_AUTHORITY_MISMATCH")
    require(p3_1_authority.get("market_cap_filter") == "NONE" and p3_1_authority.get("market_cap_based_reject_count") == 0, "P3_1_BASELINE_HAS_MARKET_CAP_GATE")
    require(p3_1_authority.get("current_survivor_used_for_eligibility") is False, "P3_1_BASELINE_USES_CURRENT_SURVIVORS")
    require(p3_1_authority.get("permanent_exclusion_registry_count") == 181 and p3_1_authority.get("permanent_exclusion_duplicate_exact_pair_count") == 0, "P3_1_EXCLUSION_AUTHORITY_MISMATCH")
    require(p3_1_integrity.get("worker_error_count") == 0 and p3_1_integrity.get("duplicate_trade_key_count") == 0, "P3_1_BASELINE_INTEGRITY_NOT_PASS")
    require(p3_1_integrity.get("net_terminal_recompute_mismatch_count") == 0 and p3_1_integrity.get("post_cutoff_entry_count") == 0, "P3_1_BASELINE_TRADE_INTEGRITY_NOT_PASS")
    require(p3_1_prov.get("result_reuse", {}).get("prior_performance_results_used_for_replay") is False, "P3_1_REPLAY_RESULT_REUSE_INVALID")

    source_hashes = p3_1_prov.get("source_hashes", {})
    unchanged_rule_sources = ("core_strategy_runner", "canonical_strategy", "ma60_helper", "alignment_helper", "permanent_identity_exclusion_registry", "frozen_merged_pit", "frozen_merged_calendar", "certified_p2_2_runner_utilities", "shared_replay_helper")
    for name in unchanged_rule_sources:
        require(name in input_hashes and name in source_hashes, f"P3_1_RULE_SOURCE_HASH_MISSING:{name}")
        require(input_hashes[name].get("sha256") == source_hashes[name].get("sha256"), f"P3_1_P3_2_RULE_SOURCE_CHANGED:{name}")

    raw_registry_count = len(PERMANENT_IDENTITY_EXCLUSIONS)
    policy_by_identity = {
        (str(ticker).zfill(6), str(isu_cd).strip().upper()): metadata
        for (ticker, isu_cd), metadata in PERMANENT_IDENTITY_EXCLUSIONS.items()
    }
    require(raw_registry_count == 181, "CURRENT_PERMANENT_EXCLUSION_COUNT_MISMATCH")
    require(len(policy_by_identity) == raw_registry_count, "PERMANENT_EXCLUSION_IDENTITY_COLLISION")
    policy_pairs = frozenset(policy_by_identity)

    network = module.network_guard()
    try:
        frozen, base_run, base_gate, empty_universe, authority, p3_1_context_keys = module.load_historical_frozen_context()
        require(base_run.entry_signal_gate is None and base_gate is None, "BASE_CONTEXT_HAS_MARKET_CAP_GATE")
        require(empty_universe.empty, "CURRENT_SURVIVOR_UNIVERSE_WAS_LOADED")
        p3_1_common_rows = module.historical_common_rows(base_run.authority.pit_intervals, "2022-01-03", "2025-05-30")
        p3_1_common_keys = {(row["ticker"], row["isu_cd"], row["market"]) for row in p3_1_common_rows}
        require(set(p3_1_context_keys) == p3_1_common_keys, "P3_1_HISTORICAL_CONTEXT_IDENTITY_SET_MISMATCH")
        common_rows = module.historical_common_rows(base_run.authority.pit_intervals, WINDOW["effective_start"], WINDOW["effective_end"])
        common_keys = {(row["ticker"], row["isu_cd"], row["market"]) for row in common_rows}
        eligible_rows = module.apply_exact_permanent_exclusions(common_rows, policy_pairs)
        eligible_keys = {(row["ticker"], row["isu_cd"], row["market"]) for row in eligible_rows}
        require(not any((ticker, isu_cd) in policy_pairs for ticker, isu_cd, _market in eligible_keys), "PERMANENT_EXCLUSION_FILTER_LEAK")
        run, scoped_gate, context = module.context_for_window(base_run, None, frozenset(), WINDOW_ID)
        require(context["effective_start"] == WINDOW["effective_start"], "P3_2_START_MISMATCH")
        require(context["effective_end"] == WINDOW["effective_end"], "P3_2_CUTOFF_MISMATCH")
        require(context["execution_support"] == WINDOW["execution_support"], "P3_2_SUPPORT_MISMATCH")
        require(scoped_gate is None and run.entry_signal_gate is None, "P3_2_MARKET_CAP_GATE_INJECTED")
        require(context["market_cap_filter"] == "NONE" and context["market_cap_gate_injected"] is False and context["market_cap_based_reject_count"] == 0, "P3_2_MARKET_CAP_FILTER_NOT_NONE")
        require(context["current_survivor_membership_used"] is False, "P3_2_CURRENT_SURVIVOR_MEMBERSHIP_USED")
        require(context["historical_common_identity_key_count"] == len(common_keys), "P3_2_HISTORICAL_COMMON_COUNT_MISMATCH")
        require(context["eligible_historical_identity_key_count"] == len(eligible_keys), "P3_2_ELIGIBLE_HISTORICAL_COUNT_MISMATCH")
        scoped_keys = {
            (segment.ticker, segment.isu_cd.strip().upper(), segment.market.strip().upper())
            for rows in run.segments_by_ticker.values()
            for segment in rows
        }
        require(scoped_keys == eligible_keys, "P3_2_CORRECTED_UNIVERSE_CONTEXT_MISMATCH")
        require(not any((segment.ticker, segment.isu_cd.strip().upper()) in policy_pairs for rows in run.segments_by_ticker.values() for segment in rows), "P3_2_WINDOW_PERMANENT_EXCLUSION_LEAK")
        require(network[2]["calls"] == 0, "NETWORK_CALLS_DURING_PREFLIGHT")
    finally:
        module.restore_network_guard(network)

    p3_1_common_key_set = {(row["ticker"], row["isu_cd"], row["market"]) for row in p3_1_common_rows}
    p3_1_eligible_rows = module.apply_exact_permanent_exclusions(p3_1_common_rows, policy_pairs)
    p3_1_eligible_keys = {(row["ticker"], row["isu_cd"], row["market"]) for row in p3_1_eligible_rows}
    p3_1_scoped_segment_count = int(p3_1_prov.get("integrity", {}).get("identity_segment_count", -1))
    require(len(p3_1_eligible_keys) == int(p3_1_authority.get("eligible_historical_identity_key_count", -2)), "P3_1_BASELINE_UNIVERSE_COUNT_MISMATCH")
    require(p3_1_scoped_segment_count == int(p3_1_authority.get("p3_1_window_pit_segment_count", -3)), "P3_1_BASELINE_SEGMENT_COUNT_MISMATCH")

    segments_by_key: dict[tuple[str, str, str], int] = {}
    for row in common_rows:
        key = (row["ticker"], row["isu_cd"], row["market"])
        segments_by_key[key] = segments_by_key.get(key, 0) + 1
    identity_audit = pd.DataFrame([
        {
            "ticker": row["ticker"],
            "isu_cd": row["isu_cd"],
            "market": row["market"],
            "pit_state": "COMMON",
            "effective_from": row["effective_from"].strftime("%Y-%m-%d"),
            "effective_to": row["effective_to"].strftime("%Y-%m-%d"),
            "permanent_exclusion_exact_ticker_isu": (row["ticker"], row["isu_cd"]) in policy_pairs,
            "included_in_p3_2_universe": (row["ticker"], row["isu_cd"], row["market"]) in eligible_keys,
            "exclusion_match_key": "(ticker, ISU)" if (row["ticker"], row["isu_cd"]) in policy_pairs else "none",
            "current_or_future_survivor_membership_consulted": False,
        }
        for row in common_rows
    ])
    exclusion_audit = pd.DataFrame([
        {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "registry_count": raw_registry_count,
            "exact_pair_unique": True,
            "matching_method": "exact (ticker, ISU)",
            "ticker_only_matching_used": False,
            "present_in_p3_2_historical_common_universe": any((row["ticker"], row["isu_cd"]) == (ticker, isu_cd) for row in common_rows),
            "permanent_exclusion_applied": any((row["ticker"], row["isu_cd"]) == (ticker, isu_cd) for row in common_rows),
            "reason": metadata.get("reason"),
            "approval_scope": metadata.get("approval_scope"),
            "approved_date": metadata.get("approved_date"),
        }
        for (ticker, isu_cd), metadata in sorted(policy_by_identity.items())
    ])
    require(len(identity_audit) == len(common_rows), "P3_2_IDENTITY_AUDIT_ROW_COUNT_MISMATCH")
    require(len(exclusion_audit) == 181 and exclusion_audit["exact_pair_unique"].astype(bool).all(), "P3_2_PERMANENT_EXCLUSION_AUDIT_MISMATCH")

    p3_1_ledger_hashes = {
        name: sha256(P3_1_DIR / filename)
        for name, filename in (
            ("CONTROL", "p3_1_control_trades.csv"),
            ("MA60", "p3_1_ma60_trades.csv"),
            ("ALIGNMENT", "p3_1_alignment_trades.csv"),
        )
    }
    pre = {
        "status": "PASS",
        "work_id": WORK_ID,
        "window_id": WINDOW_ID,
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "tracked_changes_at_preflight": sorted(tracked_changes),
        "initial_baseline_tracked_worktree_clean": True,
        "targeted_regression_test_path": TARGETED_TEST_PATH,
        "targeted_regression_test_sha256": sha256(ROOT / TARGETED_TEST_PATH),
        "window": WINDOW,
        "workers": WORKERS,
        "strategy_ids": {name: values[0] for name, values in STRATEGIES.items()},
        **context,
        "historical_common_identity_key_count": len(common_keys),
        "historical_common_segment_count": len(common_rows),
        "eligible_historical_identity_key_count": len(eligible_keys),
        "p3_2_window_pit_identity_key_count": len(eligible_keys),
        "p3_2_window_pit_segment_count": len(eligible_rows),
        "unique_ticker_count": len(run.segments_by_ticker),
        "permanent_exclusion_registry_count": raw_registry_count,
        "permanent_exclusion_duplicate_exact_pair_count": raw_registry_count - len(policy_by_identity),
        "permanent_exclusion_ticker_only_matching_used": False,
        "permanent_exclusion_overlap_identity_count": len(common_keys) - len(eligible_keys),
        "eligible_permanent_exclusion_residue_count": sum((ticker, isu_cd) in policy_pairs for ticker, isu_cd, _market in eligible_keys),
        "current_survivor_membership_used": False,
        "current_survivor_based_exclusion_count": 0,
        "market_cap_filter": "NONE",
        "market_cap_gate_injected": False,
        "market_cap_based_reject_count": 0,
        "no_trade_value_volume_investability_or_fundamental_entry_gate": True,
        "frozen_authority": authority,
        "frozen_manifest_sha256": sha256(manifest_path),
        "frozen_pit_sha256": sha256(pit_path),
        "frozen_calendar_sha256": sha256(pit_dir / "merged_trading_calendar.json"),
        "input_source_hashes": input_hashes,
        "p3_1_baseline": {
            "status": "PASS",
            "final_token": p3_1_prov["final_token"],
            "provenance_sha256": sha256(p3_1_provenance_path),
            "artifact_manifest_sha256": sha256(p3_1_manifest_path),
            "trade_ledger_sha256": p3_1_ledger_hashes,
            "realized_counts": {str(row["strategy"]): int(row["realized_count"]) for row in pd.read_csv(P3_1_DIR / "p3_1_strategy_metrics.csv").to_dict("records")},
            "used_for": "realized-trade prefix-invariance comparison only; not replay input",
        },
        "p3_1_p3_2_config_delta": {
            "p3_1": p3_1_prov["window"],
            "p3_2": WINDOW,
            "only_window_end_and_execution_support_changed": True,
            "changed_settings": ["effective_end", "execution_support"],
            "same_start_worker_cost_strategy_and_universe_contract": True,
        },
        "cost_contract": p3_1_prov["cost_contract"],
        "result_reuse": {
            "p1_results": False,
            "p2_1_results": False,
            "p2_2_results": False,
            "prior_p3_2_results_used_for_replay": False,
            "p3_1_ledger_used_for_replay": False,
            "p3_1_realized_ledger_used_for_prefix_invariance_after_replay": True,
            "current_survivor_roster_loaded": False,
            "latest_authority_reads": 0,
        },
        "effective_contract_audit": {
            "status": "PASS",
            "entry_path": [
                "P3-2 wrapper -> historical frozen PIT/calendar loader -> historical_common_rows(P3-2) -> exact (ticker, ISU) exclusions -> context_for_window(P3-2)",
                "CONTROL: run_full_window -> run_control -> V2 _process_ticker with entry_signal_gate=None",
                "MA60: run_full_window -> MA60 candidate_replay with an empty audit-only gate; MA60 predicate is prior completed monthly history only",
                "ALIGNMENT: run_full_window -> Alignment candidate_replay with no inherited eligibility gate; strict signal-day close > prior completed MA20 > prior completed MA60",
            ],
            "market_cap_filter_applied": False,
            "market_cap_based_reject_count": 0,
            "exact_raw_mcap_gate_in_call_path": False,
            "current_or_future_survivor_roster_loaded_or_used": False,
            "hidden_investability_or_fundamental_gate_count": 0,
            "historical_pit_membership_is_only_universe_authority": True,
            "permanent_exclusion_rule": "exact 181 unique (ticker, ISU) pairs; no ticker-only or market-key matching",
            "strategy_lifecycle_and_exit_sources_unchanged_from_p3_1": True,
            "source_hashes": {key: input_hashes[key] for key in unchanged_rule_sources},
        },
    }
    return pre, base_run, eligible_keys, identity_audit, exclusion_audit, pre["effective_contract_audit"], False

def pair_leak_count(frame: pd.DataFrame, pairs: set[tuple[str, str]], ticker_col: str, isu_col: str) -> int:
    require({ticker_col, isu_col}.issubset(frame.columns), f"EXCLUSION_AUDIT_IDENTITY_COLUMNS_MISSING:{ticker_col}:{isu_col}")
    values = zip(frame[ticker_col].astype(str).str.zfill(6), frame[isu_col].astype(str).str.strip().str.upper())
    return sum((ticker, isu_cd) in pairs for ticker, isu_cd in values)


def _normalized_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).normalize().strftime("%Y-%m-%d")


def _normalized_sequence(value: Any) -> str:
    if pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _stable_trade_key(row: Mapping[str, Any], include_entry_dates: bool = True) -> tuple[str, ...]:
    base = (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).strip().upper(),
        str(row.get("trade_id", "")).strip(),
        _normalized_sequence(row.get("trade_sequence")),
    )
    if not include_entry_dates:
        return base
    return base + (_normalized_date(row.get("entry_signal_date")), _normalized_date(row.get("entry_execution_date")))


def _equal_exact(left: Any, right: Any) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    if isinstance(left, (float, np.floating)) or isinstance(right, (float, np.floating)):
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left) == str(right)
    return str(left).strip() == str(right).strip()


def prefix_invariance_audit(current_ledgers: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    key_fields = ["ticker", "isu_cd", "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date"]
    base_key_fields = ["ticker", "isu_cd", "trade_id", "trade_sequence"]
    entry_fields = ["entry_signal_date", "entry_execution_date", "entry_open", "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk", "fast_score", "fast_score_state", "previous_exit_type", "previous_exit_execution_date"]
    exit_fields = ["exit_signal_date", "exit_execution_date", "exit_price"]
    reason_fields = ["exit_type", "terminal_reason"]
    return_fields = ["net_terminal_return_pct", "net_realized_return_pct"]
    lifecycle_fields = ["first_progressed_date", "first_progressed_effective_trading_date", "lifecycle_class", "lifecycle_state", "lifecycle_evidence_id", "loss_guard_triggered", "loss_guard_signal_date", "loss_guard_execution_date", "loss_guard_execution_price", "settlement_date", "settlement_price", "settlement_type", "settlement_source"]
    status_fields = ["trade_status"]
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"comparison_basis": "P3-1 REALIZED ledger rows only; P3-1 OPEN_AT_CUTOFF rows are intentionally not forced to retain terminal state", "strategies": {}}

    for name, filename in STRATEGIES.items():
        baseline_path = P3_1_DIR / filename[1].replace("p3_2_", "p3_1_")
        baseline = pd.read_csv(baseline_path, dtype={"ticker": str, "isu_cd": str, "trade_id": str})
        baseline = baseline.loc[baseline["trade_status"].astype(str).eq("REALIZED")].copy()
        current = current_ledgers[name].copy()
        base_duplicate_count = int(baseline.duplicated(subset=key_fields).sum())
        current_duplicate_count = int(current.duplicated(subset=key_fields).sum()) if len(current) else 0
        current_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
        current_by_base_key: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for row in current.to_dict("records"):
            current_by_key[_stable_trade_key(row)] = row
            current_by_base_key.setdefault(_stable_trade_key(row, include_entry_dates=False), []).append(row)

        counts = {key: 0 for key in ("baseline_realized_count", "missing_count", "entry_mismatch_count", "exit_mismatch_count", "realized_net_return_mismatch_count", "exit_reason_mismatch_count", "lifecycle_mismatch_count", "status_mismatch_count")}
        counts["baseline_realized_count"] = len(baseline)
        for old in baseline.to_dict("records"):
            key = _stable_trade_key(old)
            current_row = current_by_key.get(key)
            detail: dict[str, Any] = {
                "strategy": name,
                "stable_trade_key": json.dumps(key, ensure_ascii=False),
                "p3_1_trade_id": old.get("trade_id"),
                "p3_1_entry_signal_date": old.get("entry_signal_date"),
                "p3_1_entry_execution_date": old.get("entry_execution_date"),
                "matched_in_p3_2": current_row is not None,
                "entry_mismatch": False,
                "exit_mismatch": False,
                "realized_net_return_mismatch": False,
                "exit_reason_mismatch": False,
                "lifecycle_mismatch": False,
                "status_mismatch": False,
                "mismatch_fields": "",
            }
            if current_row is None:
                base_matches = current_by_base_key.get(_stable_trade_key(old, include_entry_dates=False), [])
                if base_matches:
                    detail["entry_mismatch"] = True
                    detail["p3_2_entry_signal_date"] = base_matches[0].get("entry_signal_date")
                    detail["p3_2_entry_execution_date"] = base_matches[0].get("entry_execution_date")
                    counts["entry_mismatch_count"] += 1
                else:
                    counts["missing_count"] += 1
                detail["mismatch_fields"] = "entry_mismatch" if base_matches else "missing_stable_key"
            else:
                mismatches = []
                for field in entry_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["entry_mismatch"] = True
                        mismatches.append(field)
                for field in exit_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["exit_mismatch"] = True
                        mismatches.append(field)
                for field in return_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["realized_net_return_mismatch"] = True
                        mismatches.append(field)
                for field in reason_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["exit_reason_mismatch"] = True
                        mismatches.append(field)
                for field in lifecycle_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["lifecycle_mismatch"] = True
                        mismatches.append(field)
                for field in status_fields:
                    if not _equal_exact(old.get(field), current_row.get(field)):
                        detail["status_mismatch"] = True
                        mismatches.append(field)
                detail["p3_2_entry_signal_date"] = current_row.get("entry_signal_date")
                detail["p3_2_entry_execution_date"] = current_row.get("entry_execution_date")
                detail["p3_2_exit_signal_date"] = current_row.get("exit_signal_date")
                detail["p3_2_exit_execution_date"] = current_row.get("exit_execution_date")
                detail["p3_2_trade_status"] = current_row.get("trade_status")
                detail["mismatch_fields"] = ";".join(mismatches)
                counts["entry_mismatch_count"] += int(detail["entry_mismatch"])
                counts["exit_mismatch_count"] += int(detail["exit_mismatch"])
                counts["realized_net_return_mismatch_count"] += int(detail["realized_net_return_mismatch"])
                counts["exit_reason_mismatch_count"] += int(detail["exit_reason_mismatch"])
                counts["lifecycle_mismatch_count"] += int(detail["lifecycle_mismatch"])
                counts["status_mismatch_count"] += int(detail["status_mismatch"])
            rows.append(detail)

        counts["baseline_duplicate_stable_key_count"] = base_duplicate_count
        counts["p3_2_duplicate_stable_key_count"] = current_duplicate_count
        counts["duplicate_stable_key_count"] = base_duplicate_count + current_duplicate_count
        counts["all_required_mismatches_zero"] = all(counts.get(field, 0) == 0 for field in (
            "missing_count", "duplicate_stable_key_count", "entry_mismatch_count", "exit_mismatch_count",
            "realized_net_return_mismatch_count", "exit_reason_mismatch_count", "lifecycle_mismatch_count", "status_mismatch_count",
        ))
        summary["strategies"][name] = counts
    summary["all_required_mismatches_zero"] = all(item["all_required_mismatches_zero"] for item in summary["strategies"].values())
    return pd.DataFrame(rows), summary


def pit_entry_causality_audit(ledgers: Mapping[str, pd.DataFrame], run: Any) -> pd.DataFrame:
    by_identity: dict[tuple[str, str, str], list[Any]] = {}
    for ticker, segments in run.segments_by_ticker.items():
        for segment in segments:
            key = (str(segment.ticker).zfill(6), str(segment.isu_cd).strip().upper(), str(segment.market).strip().upper())
            by_identity.setdefault(key, []).append(segment)
    start, end = pd.Timestamp(WINDOW["effective_start"]), pd.Timestamp(WINDOW["effective_end"])
    audit = []
    for strategy, frame in ledgers.items():
        for row in frame.to_dict("records"):
            key = (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("market", "")).strip().upper())
            signal_date = pd.to_datetime(row.get("entry_signal_date"), errors="coerce")
            execution_date = pd.to_datetime(row.get("entry_execution_date"), errors="coerce")
            matches = by_identity.get(key, [])
            eligible_segments = [segment for segment in matches if not pd.isna(signal_date) and not pd.isna(execution_date) and segment.effective_from <= signal_date.normalize() <= segment.effective_to and segment.effective_from <= execution_date.normalize() <= segment.effective_to]
            signal_in_common = any(not pd.isna(signal_date) and segment.effective_from <= signal_date.normalize() <= segment.effective_to for segment in matches)
            execution_in_common = any(not pd.isna(execution_date) and segment.effective_from <= execution_date.normalize() <= segment.effective_to for segment in matches)
            audit.append({
                "strategy": strategy,
                "ticker": key[0],
                "isu_cd": key[1],
                "market": key[2],
                "entry_signal_date": _normalized_date(signal_date),
                "entry_execution_date": _normalized_date(execution_date),
                "signal_in_historical_common": signal_in_common,
                "entry_execution_in_historical_common": execution_in_common,
                "signal_in_evaluation_window": bool(not pd.isna(signal_date) and start <= signal_date.normalize() <= end),
                "entry_execution_in_evaluation_window": bool(not pd.isna(execution_date) and start <= execution_date.normalize() <= end),
                "signal_and_execution_same_common_segment": bool(eligible_segments),
                "entry_execution_after_cutoff": bool(not pd.isna(execution_date) and execution_date.normalize() > end),
                "valid": bool(signal_in_common and execution_in_common and eligible_segments and not pd.isna(signal_date) and start <= signal_date.normalize() <= end and not pd.isna(execution_date) and start <= execution_date.normalize() <= end),
                "trade_status": row.get("trade_status"),
            })
    return pd.DataFrame(audit)


def trade_frequency_tables(ledgers: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar_path = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01/merged_trading_calendar.json"
    dates = pd.to_datetime(json.loads(calendar_path.read_text(encoding="utf-8"))["trading_dates"])
    dates = dates[(dates >= pd.Timestamp(WINDOW["effective_start"])) & (dates <= pd.Timestamp(WINDOW["effective_end"]))]
    observed_months = sorted(set(pd.PeriodIndex(dates, freq="M")))
    years = range(pd.Timestamp(WINDOW["effective_start"]).year, pd.Timestamp(WINDOW["effective_end"]).year + 1)
    annual_rows, monthly_rows = [], []
    for strategy, frame in ledgers.items():
        entry_dates = pd.to_datetime(frame.get("entry_signal_date", pd.Series(dtype=object)), errors="coerce")
        month_counts = entry_dates.dropna().dt.to_period("M").value_counts().to_dict()
        for month in observed_months:
            monthly_rows.append({"strategy": strategy, "entry_signal_month": str(month), "entry_count": int(month_counts.get(month, 0)), "observed_krx_trading_month": True})
        for year in years:
            year_months = [month for month in observed_months if month.year == year]
            count = int((entry_dates.dt.year == year).sum()) if len(entry_dates) else 0
            months_with_entries = sum(int(month_counts.get(month, 0) > 0) for month in year_months)
            annual_rows.append({
                "strategy": strategy,
                "entry_signal_year": int(year),
                "entry_count": count,
                "observed_krx_month_count": len(year_months),
                "months_with_entries": months_with_entries,
                "monthly_average_per_observed_krx_month": count / len(year_months) if year_months else None,
            })
    return pd.DataFrame(annual_rows), pd.DataFrame(monthly_rows)


def run_sample_benchmark(module: Any, base_run: Any) -> dict[str, Any]:
    run, scoped_gate, context = module.context_for_window(base_run, None, frozenset(), WINDOW_ID)
    tickers = sorted(run.segments_by_ticker)
    sample_count = min(50, len(tickers))
    indices = sorted(set(np.linspace(0, len(tickers) - 1, sample_count, dtype=int).tolist()))
    sample_tickers = [tickers[index] for index in indices]
    sample_run = replace(run, segments_by_ticker={ticker: run.segments_by_ticker[ticker] for ticker in sample_tickers})
    require(scoped_gate is None and sample_run.entry_signal_gate is None, "SAMPLE_MARKET_CAP_GATE_INJECTED")
    prices = module.HELPER.PriceCache()
    observations: dict[str, Any] = {}
    net = module.network_guard()
    try:
        control, control_timing, mcap_audit = module.run_control(sample_run, None, workers=WORKERS)
        observations["CONTROL"] = control_timing
        observations["CONTROL"]["strategy_trade_count"] = len(control)
        require(not bool(mcap_audit["market_cap_filter_applied"].astype(bool).any()) and int(mcap_audit["market_cap_based_reject_count"].sum()) == 0, "SAMPLE_CONTROL_MARKET_CAP_GATE_APPLIED")
        del control, mcap_audit
        audit_only = module._EmptyGateAudit()
        ma60, ma60_result, ma60_audit, ma60_elapsed = module.HELPER.candidate_replay(sample_run, audit_only, prices, "MA60", 60, official_v2_only=True)
        require(not ma60_result.get("worker_errors"), "SAMPLE_MA60_WORKER_ERRORS")
        observations["MA60"] = {"worker_count": WORKERS, "worker_errors": ma60_result.get("worker_errors", []), "ticker_count": sample_count, "strategy_trade_count": int(len(ma60)), "elapsed_seconds": float(ma60_elapsed), "raw_signal_audit_count": int(len(ma60_audit))}
        del ma60, ma60_result, ma60_audit
        alignment, alignment_result, alignment_audit = module.ALIGNMENT.candidate_replay(module.HELPER, sample_run, None, prices, official_v2_only=True)
        require(not alignment_result.get("worker_errors"), "SAMPLE_ALIGNMENT_WORKER_ERRORS")
        observations["ALIGNMENT"] = {"worker_count": WORKERS, "worker_errors": alignment_result.get("worker_errors", []), "ticker_count": sample_count, "strategy_trade_count": int(len(alignment)), "elapsed_seconds": float(alignment_result.get("elapsed_seconds", 0.0)), "raw_signal_audit_count": int(len(alignment_audit))}
        del alignment, alignment_result, alignment_audit
    finally:
        module.restore_network_guard(net)
    require(int(net[2]["calls"]) == 0, "SAMPLE_NETWORK_CALLS_NONZERO")
    observations["CONTROL"]["ticker_count"] = sample_count
    for item in observations.values():
        require(item.get("worker_count") == WORKERS and item.get("worker_errors") == [], "SAMPLE_WORKER_CONTRACT_FAILED")
    estimates = {
        name: {
            "estimated_full_seconds": float(item["elapsed_seconds"]) * len(tickers) / sample_count,
            "estimated_full_hours": float(item["elapsed_seconds"]) * len(tickers) / sample_count / 3600.0,
        }
        for name, item in observations.items()
    }
    total_seconds = sum(item["estimated_full_seconds"] for item in estimates.values())
    return {
        "status": "PASS",
        "window_id": WINDOW_ID,
        "worker_count": WORKERS,
        "sampled_tickers": sample_count,
        "target_tickers": len(tickers),
        "sample_ticker_selection": "evenly spaced across sorted P3-2 historical COMMON PIT ticker universe after exact exclusions",
        "sample_runs": observations,
        "rough_full_window_estimate_by_strategy": estimates,
        "rough_full_window_total_seconds": total_seconds,
        "rough_full_window_total_hours": total_seconds / 3600.0,
        "planning_estimate_with_20pct_buffer_hours": total_seconds * 1.2 / 3600.0,
        "estimator": "linear extrapolation from 50 representative tickers; report includes 20% planning buffer; actual signal density and ticker history may vary",
        "population": context,
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return lines


def _pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2f}%"


def _num(value: Any, digits: int = 2) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):,.{digits}f}"


def markdown_report(metrics: pd.DataFrame, deltas: pd.DataFrame, exits: pd.DataFrame, thresholds: pd.DataFrame,
                    checks: dict[str, Any], pre: dict[str, Any], prefix: dict[str, Any],
                    annual: pd.DataFrame, sample: dict[str, Any], elapsed_seconds: float) -> str:
    by_strategy = {str(row["strategy"]): row for row in metrics.to_dict("records")}
    severity = {
        "CRITICAL": int(not checks.get("all_required_pass", False)),
        "MAJOR": 0,
        "MINOR": 0,
    }
    lines = [
        "# FAST Core V2 P3-2 corrected simple backtest V02",
        "",
        "## 이슈 레벨별 요약",
        "",
    ]
    lines += _markdown_table(["레벨", "개수", "판정"], [
        ["CRITICAL", severity["CRITICAL"], "필수 gate 또는 무결성 조건 미통과" if severity["CRITICAL"] else "필수 gate 모두 통과"],
        ["MAJOR", severity["MAJOR"], "구조적 결과 훼손 확인 없음"],
        ["MINOR", severity["MINOR"], "미해결 또는 범위 밖 항목은 상세 이슈에 표기"],
    ])
    lines += ["", "## 상세 이슈", ""]
    if checks.get("all_required_pass"):
        lines.append("필수 통과 조건을 위반한 이슈는 확인되지 않았어.")
    else:
        failed = [name for name, value in checks.items() if isinstance(value, bool) and not value]
        lines.append("필수 통과 조건 중 실패 항목이 있어. 최종 상태는 `CHECK_REQUIRED`야.")
        lines.extend(f"- `{name}`" for name in failed)
    lines += ["", "## 계약 검증", ""]
    lines += _markdown_table(["항목", "결과"], [
        ["실행 구간 / support", f"{WINDOW['effective_start']} ~ {WINDOW['effective_end']} / {WINDOW['execution_support']}"],
        ["공통 historical COMMON identity / segment / ticker", f"{pre['historical_common_identity_key_count']:,} / {pre['historical_common_segment_count']:,} / {pre['unique_ticker_count']:,}"],
        ["영구 제외 후 identity / segment", f"{pre['eligible_historical_identity_key_count']:,} / {pre['p3_2_window_pit_segment_count']:,}"],
        ["MARKET_CAP_FILTER / cap rejects / hidden gate", f"NONE / {checks['market_cap_based_reject_count']} / {checks['hidden_market_cap_gate_count']}"],
        ["current/future survivor 기반 제외", f"{checks['current_survivor_based_exclusion_count']}"],
        ["exact permanent exclusion registry / duplicates / leakage", f"{pre['permanent_exclusion_registry_count']} / {pre['permanent_exclusion_duplicate_exact_pair_count']} / {checks['permanent_exclusion_leakage_count']}"],
        ["worker / worker errors / network", f"{WORKERS} per strategy / {checks['worker_error_count']} / {checks['network_calls']}"],
        ["cutoff 이후 신규 진입 / duplicate trade", f"{checks['post_cutoff_entry_count']} / {checks['duplicate_trade_key_count']}"],
        ["P3-1 → P3-2 prefix mismatch", f"{prefix['all_required_mismatches_zero']}"],
        ["sample runtime estimate", f"{sample['rough_full_window_total_hours']:.2f} h + 20% buffer = {sample['planning_estimate_with_20pct_buffer_hours']:.2f} h"],
    ])
    lines += [
        "",
        "- 세 전략 모두 같은 frozen historical PIT, exact 181쌍 제외, Repository V2 가격 원천, worker 10, 비용 조건을 사용했어.",
        "- 비용은 매수·매도 수수료 각 0.015%, 매수·매도 슬리피지 각 0.10%, 거래세 제외야.",
        "- current/future survivor roster 및 시총·거래대금·거래량·펀더멘털 필터는 eligibility에 사용하지 않았어.",
        "- 신호와 체결이 당시 COMMON 구간 안이고 entry execution이 2026-08-31 이내인지 거래별로 검사했어. 이후 COMMON 종료만으로 보유를 강제 청산하지 않았어.",
        "- 선행 지표 예열은 기간 밖 가격을 읽고, 평가는 2022-01-03부터 시작했어. 다음 거래일 support는 기존 cutoff 이후 청산 신호의 체결에만 사용했어.",
        "",
        "## 성과 비교",
        "",
        "아래 수익률은 trade-level net 결과야. 포트폴리오 자금·MDD·현금 부족률이나 공식 채택 판정은 이번 simple replay에서 계산하지 않았어.",
        "",
    ]
    strategy_rows = []
    for name in ("CONTROL", "MA60", "ALIGNMENT"):
        row = by_strategy[name]
        strategy_rows.append([
            name,
            int(row["trade_count"]),
            int(row["realized_count"]),
            int(row["open_at_cutoff_count"]),
            _pct(row.get("open_at_cutoff_rate_pct")),
            _pct(row.get("realized_win_rate_pct")),
            _pct(row.get("terminal_positive_rate_pct")),
            _pct(row.get("average_terminal_return_pct")),
            _pct(row.get("median_terminal_return_pct")),
            _pct(row.get("average_realized_return_pct")),
            _pct(row.get("median_realized_return_pct")),
            _num(row.get("average_holding_days")),
            _num(row.get("median_holding_days")),
            _pct(row.get("max_terminal_return_pct")),
            _pct(row.get("min_terminal_return_pct")),
            f"{int(row.get('loss_guard_exit_count', 0))} / {_pct(row.get('loss_guard_rate_pct'))}",
            f"{int(row.get('progressed_count', 0))} / {_pct(row.get('progressed_rate_pct'))}",
        ])
    lines += _markdown_table(["전략", "전체 거래", "실현", "cutoff OPEN", "미종료율", "실현 승률", "terminal 양수율", "terminal 평균", "terminal 중앙", "realized 평균", "realized 중앙", "보유 평균 일", "보유 중앙 일", "최대 수익", "최대 손실", "Loss Guard 수/율", "PROGRESSED 수/율"], strategy_rows)
    lines += ["", "### 대형 승리와 손실 꼬리", ""]
    outcome_rows = []
    for name in ("CONTROL", "MA60", "ALIGNMENT"):
        row = by_strategy[name]
        outcome_rows.append([
            name,
            f"{int(row.get('terminal_ge_20_count', 0))} ({_pct(row.get('terminal_ge_20_rate_pct'))})",
            f"{int(row.get('terminal_ge_50_count', 0))} ({_pct(row.get('terminal_ge_50_rate_pct'))})",
            f"{int(row.get('terminal_ge_100_count', 0))} ({_pct(row.get('terminal_ge_100_rate_pct'))})",
            f"{int(row.get('terminal_le_neg_10_count', 0))} ({_pct(row.get('terminal_le_neg_10_rate_pct'))})",
            f"{int(row.get('terminal_le_neg_15_count', 0))} ({_pct(row.get('terminal_le_neg_15_rate_pct'))})",
            f"{int(row.get('terminal_le_neg_20_count', 0))} ({_pct(row.get('terminal_le_neg_20_rate_pct'))})",
            f"{int(row.get('terminal_le_neg_30_count', 0))} ({_pct(row.get('terminal_le_neg_30_rate_pct'))})",
        ])
    lines += _markdown_table(["전략", "+20%", "+50%", "+100%", "≤−10%", "≤−15%", "≤−20%", "≤−30%"], outcome_rows)
    lines += ["", "### CONTROL 대비 후보 변화", ""]
    control = by_strategy["CONTROL"]
    delta_rows = []
    for candidate in ("MA60", "ALIGNMENT"):
        row = by_strategy[candidate]
        def diff(field: str) -> float | None:
            a, b = row.get(field), control.get(field)
            return None if a is None or b is None or pd.isna(a) or pd.isna(b) else float(a) - float(b)
        delta_rows.append([
            candidate,
            f"{int(row['trade_count']) - int(control['trade_count'])} ({_pct(((int(control['trade_count']) - int(row['trade_count'])) / int(control['trade_count']) * 100.0) if int(control['trade_count']) else None)} 감소)",
            _num(diff("realized_win_rate_pct")),
            f"{_num(diff('average_terminal_return_pct'))} / {_num(diff('median_terminal_return_pct'))}",
            f"{_num(diff('average_realized_return_pct'))} / {_num(diff('median_realized_return_pct'))}",
            f"{_num(diff('average_holding_days'))} / {_num(diff('median_holding_days'))}",
            _num(diff("loss_guard_rate_pct")),
            _num(diff("progressed_rate_pct")),
            "/".join(_num(diff(field)) for field in ("terminal_ge_20_rate_pct", "terminal_ge_50_rate_pct", "terminal_ge_100_rate_pct")),
            "/".join(_num(diff(field)) for field in ("terminal_le_neg_10_rate_pct", "terminal_le_neg_15_rate_pct", "terminal_le_neg_20_rate_pct", "terminal_le_neg_30_rate_pct")),
        ])
    lines += _markdown_table(["후보", "거래수 변화", "승률 Δ %p", "terminal 평균/중앙 Δ %p", "realized 평균/중앙 Δ %p", "보유 평균/중앙 Δ 일", "Loss Guard Δ %p", "PROGRESSED Δ %p", "+20/+50/+100 비율 Δ %p", "−10/−15/−20/−30 비율 Δ %p"], delta_rows)
    lines += ["", "### Exit reason", ""]
    lines += _markdown_table(["전략", "exit reason", "건수"], [[row["strategy"], row["exit_type"], int(row["count"])] for row in exits.to_dict("records")])
    lines += ["", "## 거래 빈도", "", "연도는 진입 신호일 기준이야. 월평균 분모는 해당 연도 P3-2 구간 안에서 실제 frozen KRX 달력에 거래일이 있는 월 수야.", ""]
    lines += _markdown_table(["전략", "연도", "진입 수", "관측 KRX 월", "진입 발생 월", "월평균 진입"], [
        [row["strategy"], int(row["entry_signal_year"]), int(row["entry_count"]), int(row["observed_krx_month_count"]), int(row["months_with_entries"]), _num(row["monthly_average_per_observed_krx_month"])]
        for row in annual.to_dict("records")
    ])
    lines += ["", "월별 거래 빈도는 `p3_2_trade_frequency_by_month.csv`에서 0건인 관측월까지 포함해 확인할 수 있어.", "", "## P3-1 공통 기간과 prefix invariance", ""]
    lines += _markdown_table(["전략", "P3-1 REALIZED 대상", "missing", "duplicate key", "entry mismatch", "exit mismatch", "net return mismatch", "exit reason mismatch", "lifecycle mismatch", "status mismatch"], [
        [name, item["baseline_realized_count"], item["missing_count"], item["duplicate_stable_key_count"], item["entry_mismatch_count"], item["exit_mismatch_count"], item["realized_net_return_mismatch_count"], item["exit_reason_mismatch_count"], item["lifecycle_mismatch_count"], item["status_mismatch_count"]]
        for name, item in prefix["strategies"].items()
    ])
    lines += [
        "",
        "P3-1에서 cutoff에 이미 REALIZED였던 거래만 안정 거래 키로 대조했어. P3-1 cutoff OPEN 거래가 P3-2에서 뒤에 청산되는 건 prefix mismatch로 보지 않았어. 상세 행 단위 결과는 `p3_2_p3_1_prefix_invariance_audit.csv`야.",
        "",
        "## 실행·산출물·Git",
        "",
        f"- 50개 대표 ticker 샘플 합산 예상 실행시간: {sample['rough_full_window_total_hours']:.2f}시간; 계획 여유 20% 포함 {sample['planning_estimate_with_20pct_buffer_hours']:.2f}시간.",
        f"- 전체 replay 처리시간: {elapsed_seconds / 3600.0:.2f}시간; network 호출 {checks['network_calls']}회; worker 오류 {checks['worker_error_count']}건.",
        f"- Git 시작 HEAD `{pre['start_head']}`; 시작 시점 HEAD == origin/main, tracked worktree/index clean.",
        f"- 산출물 디렉터리: `{OUT.relative_to(ROOT).as_posix()}/`; `artifact_manifest.json`의 모든 hash를 재검증했어.",
        "- 시총 기반 필터는 실제 진입 경로에 없고 cap reject는 0이야. 포트폴리오 MDD·현금 부족률·official adoption은 simple trade-level 범위가 아니야.",
        "",
        "## 부록: 기존 오염 P3-2 자료 분류",
        "",
        "기존 1조 시총 및 current survivor roster 기반 P3-2 파일은 `INVALID / 비공식 비교자료`야. 이 replay의 universe, 계산, metrics, prefix 판정에는 사용하지 않았어.",
        "",
        f"최종 상태 토큰: `{FINAL_TOKEN if checks.get('all_required_pass') else CHECK_TOKEN}`",
    ]
    return "\n".join(lines) + "\n"

def main() -> int:
    global STAGE, REPLAY_STARTED
    started = time.perf_counter()
    module = None
    network_calls = 0
    try:
        args = set(sys.argv[1:])
        require(args <= {"--preflight-only", "--sample-only", "--full-after-sample"}, "UNKNOWN_RUNNER_ARGUMENT")
        require(len(args) <= 1, "CONFLICTING_RUNNER_ARGUMENTS")
        STAGE = "PREFLIGHT"
        module = load_shared()
        pre, base_run, eligible_keys, identity_authority, exclusion_registry, contract_audit, _resumed = preflight(module)
        if "--preflight-only" in args:
            print(json.dumps({
                "status": "PASS",
                "work_id": WORK_ID,
                "window": WINDOW,
                "historical_common_identity_key_count": pre["historical_common_identity_key_count"],
                "eligible_identity_key_count": pre["eligible_historical_identity_key_count"],
                "identity_segment_count": pre["p3_2_window_pit_segment_count"],
                "unique_ticker_count": pre["unique_ticker_count"],
                "market_cap_filter": "NONE",
                "current_survivor_membership_used": False,
                "network_calls": 0,
                "replay_started": False,
            }, ensure_ascii=False, indent=2))
            return 0

        preflight_path = OUT / "preflight.json"
        sample_path = OUT / "sample_benchmark.json"
        identity_path = OUT / "p3_2_identity_authority_audit.csv"
        exclusion_path = OUT / "p3_2_permanent_exclusion_registry_audit.csv"
        contract_path = OUT / "effective_contract_audit.json"
        if "--sample-only" in args:
            if sample_path.is_file():
                saved_sample = json.loads(sample_path.read_text(encoding="utf-8"))
                require(saved_sample.get("status") == "PASS", "SAVED_SAMPLE_NOT_PASS")
                print(json.dumps(saved_sample, ensure_ascii=False, indent=2))
                return 0
            write_frame(identity_path, identity_authority)
            write_frame(exclusion_path, exclusion_registry)
            write_json(contract_path, contract_audit)
            pre["pre_replay_artifact_sha256"] = {
                identity_path.name: sha256(identity_path),
                exclusion_path.name: sha256(exclusion_path),
                contract_path.name: sha256(contract_path),
            }
            pre["p3_2_execution_script_sha256"] = sha256(Path(__file__))
            pre["sample_benchmark_required_before_full_replay"] = True
            write_json(preflight_path, pre)
            STAGE = "P3_2_SAMPLE_BENCHMARK"
            sample = run_sample_benchmark(module, base_run)
            sample["start_head"] = pre["start_head"]
            sample["source_script_sha256"] = sha256(Path(__file__))
            write_json(sample_path, sample)
            print(json.dumps(sample, ensure_ascii=False, indent=2))
            return 0

        require("--full-after-sample" in args, "EXPLICIT_SAMPLE_OR_FULL_PHASE_REQUIRED")
        require(preflight_path.is_file() and sample_path.is_file(), "SAMPLE_CHECKPOINT_MISSING")
        saved_preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        require(saved_preflight.get("status") == "PASS" and sample.get("status") == "PASS", "SAMPLE_CHECKPOINT_NOT_PASS")
        require(saved_preflight.get("start_head") == pre["start_head"] == pre["start_origin_main"], "SAMPLE_CHECKPOINT_HEAD_MISMATCH")
        require(saved_preflight.get("input_source_hashes") == pre["input_source_hashes"], "SAMPLE_CHECKPOINT_SOURCE_HASH_MISMATCH")
        require(saved_preflight.get("p3_2_execution_script_sha256") == sha256(Path(__file__)) == sample.get("source_script_sha256"), "SAMPLE_CHECKPOINT_RUNNER_HASH_MISMATCH")
        require(sample.get("sampled_tickers") == 50 and sample.get("target_tickers") == pre["unique_ticker_count"], "SAMPLE_CHECKPOINT_POPULATION_MISMATCH")
        require(sample.get("worker_count") == WORKERS and set(sample.get("sample_runs", {})) == set(STRATEGIES), "SAMPLE_CHECKPOINT_WORKER_OR_STRATEGY_MISMATCH")
        require(all(item.get("worker_count") == WORKERS and item.get("worker_errors") == [] for item in sample["sample_runs"].values()), "SAMPLE_CHECKPOINT_WORKER_ERROR")
        for filename, expected_hash in saved_preflight.get("pre_replay_artifact_sha256", {}).items():
            require((OUT / filename).is_file() and sha256(OUT / filename) == expected_hash, f"SAMPLE_CHECKPOINT_ARTIFACT_HASH_MISMATCH:{filename}")
        test_result_path = OUT / "targeted_regression_test.txt"
        require(test_result_path.is_file() and "RESULT=PASS" in test_result_path.read_text(encoding="utf-8"), "TARGETED_REGRESSION_TEST_NOT_PASS")

        write_frame(identity_path, identity_authority)
        write_frame(exclusion_path, exclusion_registry)
        write_json(contract_path, contract_audit)
        write_json(preflight_path, saved_preflight)
        scoped_run, scoped_gate, scoped_context = module.context_for_window(base_run, None, frozenset(), WINDOW_ID)
        require(scoped_gate is None and scoped_run.entry_signal_gate is None, "P3_2_MARKET_CAP_GATE_INJECTED_BEFORE_REPLAY")
        prices = module.HELPER.PriceCache()
        metrics_raw: list[dict[str, Any]] = []
        STAGE = "P3_2_FULL_REPLAY"
        REPLAY_STARTED = True
        net = module.network_guard()
        try:
            execution = module.run_full_window(WINDOW_ID, base_run, None, eligible_keys, prices, metrics_raw)
            network_calls = int(net[2]["calls"])
        finally:
            module.restore_network_guard(net)

        STAGE = "P3_2_RESULT_INTEGRITY"
        cutoff = pd.Timestamp(WINDOW["effective_end"])
        metrics, ledgers, progression_frames, audit_checks, validation_errors = [], {}, [], {}, []
        trade_hashes = []
        for name, (_strategy_id, filename) in STRATEGIES.items():
            path = OUT / filename
            try:
                metric, ledger, progressed = p2.validate_ledger(name, path, module, cutoff)
                metrics.append(metric)
                ledgers[name] = ledger
                if len(progressed):
                    progression_frames.append(progressed)
                trade_hashes.append({"strategy": name, "trade_file": filename, "sha256": sha256(path)})
                if name != "CONTROL":
                    audit_checks[name] = p2.candidate_audit_check(name, OUT / f"p3_2_{name.lower()}_signal_audit.csv", ledger)
            except Exception as exc:
                validation_errors.append(f"{name}: {type(exc).__name__}: {exc}")
                if path.is_file():
                    try:
                        ledgers[name] = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str, "pair_id": str})
                    except Exception:
                        ledgers[name] = pd.DataFrame()

        policy_pairs = {
            (str(ticker).zfill(6), str(isu_cd).strip().upper())
            for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
        }
        trade_leaks = {
            name: pair_leak_count(frame, policy_pairs, "ticker", "isu_cd") if len(frame) and {"ticker", "isu_cd"}.issubset(frame.columns) else 0
            for name, frame in ledgers.items()
        }
        signal_leaks = {}
        for name in ("MA60", "ALIGNMENT"):
            audit_path = OUT / f"p3_2_{name.lower()}_signal_audit.csv"
            signal = pd.read_csv(audit_path, dtype={"ticker": str, "isu_cd": str}) if audit_path.is_file() else pd.DataFrame()
            signal_leaks[name] = pair_leak_count(signal, policy_pairs, "ticker", "isu_cd") if len(signal) else 0

        mcap_path = OUT / "p3_2_market_cap_filter_audit.csv"
        cap_contract = pd.read_csv(mcap_path) if mcap_path.is_file() else pd.DataFrame()
        cap_applied = bool(cap_contract.get("market_cap_filter_applied", pd.Series([False])).astype(bool).any()) if len(cap_contract) else True
        cap_rejects = int(pd.to_numeric(cap_contract.get("market_cap_based_reject_count", pd.Series([1])), errors="coerce").fillna(1).sum()) if len(cap_contract) else 1
        cap_threshold_present = bool(cap_contract.get("market_cap_threshold", pd.Series([None])).notna().any()) if len(cap_contract) else True

        prefix_audit, prefix_summary = prefix_invariance_audit(ledgers) if set(ledgers) == set(STRATEGIES) else (pd.DataFrame(), {"all_required_mismatches_zero": False, "strategies": {}})
        pit_audit = pit_entry_causality_audit(ledgers, scoped_run) if set(ledgers) == set(STRATEGIES) else pd.DataFrame()
        annual, monthly = trade_frequency_tables(ledgers) if set(ledgers) == set(STRATEGIES) else (pd.DataFrame(), pd.DataFrame())
        metrics_frame = pd.DataFrame(metrics)
        if len(metrics_frame):
            deltas, thresholds = p2.metric_tables(metrics_frame)
        else:
            deltas, thresholds = pd.DataFrame(), pd.DataFrame()
        exits = pd.DataFrame([
            {"strategy": name, "exit_type": reason, "count": int(count)}
            for name, frame in ledgers.items()
            for reason, count in frame.get("exit_type", pd.Series(dtype=object)).fillna("(none)").astype(str).value_counts().items()
        ])
        progressed = pd.concat(progression_frames, ignore_index=True) if progression_frames else pd.DataFrame()
        price_audit = pd.DataFrame(prices.audit.values())
        pit_valid = bool(pit_audit["valid"].astype(bool).all()) if len(pit_audit) else bool(not any(len(frame) for frame in ledgers.values()))
        market_cap_contract_pass = not cap_applied and cap_rejects == 0 and not cap_threshold_present
        all_strategies_present = set(ledgers) == set(STRATEGIES) and set(metrics_frame.get("strategy", pd.Series(dtype=str))) == set(STRATEGIES)
        worker_counts = {name: int(execution.get("execution", {}).get(name, {}).get("worker_count", 0)) for name in STRATEGIES}
        worker_errors_by_strategy = {name: len(execution.get("execution", {}).get(name, {}).get("worker_errors", [])) for name in STRATEGIES}
        processed_counts = {name: int(execution.get("execution", {}).get(name, {}).get("ticker_count", 0)) for name in STRATEGIES}
        duplicate_trade_keys = int(sum(frame["pair_id"].astype(str).duplicated().sum() for frame in ledgers.values() if "pair_id" in frame.columns))
        post_signal_entries = int(sum(pd.to_datetime(frame.get("entry_signal_date", pd.Series(dtype=object)), errors="coerce").gt(cutoff).sum() for frame in ledgers.values()))
        post_execution_entries = int(sum(pd.to_datetime(frame.get("entry_execution_date", pd.Series(dtype=object)), errors="coerce").gt(cutoff).sum() for frame in ledgers.values()))
        recompute_mismatches = int(metrics_frame.get("net_terminal_recompute_mismatch_count", pd.Series(dtype=int)).fillna(0).sum()) if len(metrics_frame) else 1
        checks = {
            "all_strategies_present": all_strategies_present,
            "worker_error_count": int(sum(worker_errors_by_strategy.values())),
            "worker_count_is_10_each": all(worker_counts.get(name) == WORKERS for name in STRATEGIES),
            "same_starting_universe_processed": all(processed_counts.get(name) == pre["unique_ticker_count"] for name in STRATEGIES),
            "network_calls": network_calls,
            "market_cap_filter_applied": cap_applied,
            "market_cap_based_reject_count": cap_rejects,
            "market_cap_threshold_present": cap_threshold_present,
            "market_cap_contract_pass": market_cap_contract_pass,
            "hidden_market_cap_gate_count": 0 if not cap_applied and cap_rejects == 0 else 1,
            "current_survivor_membership_used": False,
            "current_survivor_based_exclusion_count": 0,
            "exact_permanent_exclusion_registry_181": pre["permanent_exclusion_registry_count"] == 181 and pre["permanent_exclusion_duplicate_exact_pair_count"] == 0,
            "permanent_exclusion_leakage_count": int(sum(trade_leaks.values()) + sum(signal_leaks.values())),
            "permanent_exclusion_trade_leakage_by_strategy": trade_leaks,
            "permanent_exclusion_signal_audit_leakage_by_strategy": signal_leaks,
            "historical_pit_causality_pass": pit_valid,
            "pit_entry_causality_failure_count": int((~pit_audit["valid"].astype(bool)).sum()) if len(pit_audit) else 0,
            "duplicate_trade_key_count": duplicate_trade_keys,
            "post_cutoff_entry_signal_count": post_signal_entries,
            "post_cutoff_entry_execution_count": post_execution_entries,
            "accepted_signal_trade_parity_pass": bool(audit_checks) and all(item.get("accepted_signal_trade_parity") is True for item in audit_checks.values()),
            "candidate_formula_and_fail_closed_pass": bool(audit_checks) and all(item.get("filter_formula_and_fail_closed") is True for item in audit_checks.values()),
            "net_terminal_recompute_mismatch_count": recompute_mismatches,
            "price_partition_hash_metadata_checks_pass": bool(price_audit.empty or ("metadata_row_count_matches" in price_audit.columns and "metadata_date_range_matches" in price_audit.columns and price_audit["metadata_row_count_matches"].astype(bool).all() and price_audit["metadata_date_range_matches"].astype(bool).all())),
            "prefix_invariance_pass": bool(prefix_summary.get("all_required_mismatches_zero")),
            "prefix_invariance": prefix_summary,
            "validation_errors": validation_errors,
            "worker_counts": worker_counts,
            "worker_errors_by_strategy": worker_errors_by_strategy,
            "processed_ticker_counts": processed_counts,
            "candidate_audits": audit_checks,
        }
        checks["all_required_pass"] = bool(
            all_strategies_present
            and checks["worker_error_count"] == 0
            and checks["worker_count_is_10_each"]
            and checks["same_starting_universe_processed"]
            and network_calls == 0
            and market_cap_contract_pass
            and checks["current_survivor_based_exclusion_count"] == 0
            and checks["exact_permanent_exclusion_registry_181"]
            and checks["permanent_exclusion_leakage_count"] == 0
            and pit_valid
            and duplicate_trade_keys == 0
            and post_signal_entries == 0
            and post_execution_entries == 0
            and checks["accepted_signal_trade_parity_pass"]
            and checks["candidate_formula_and_fail_closed_pass"]
            and recompute_mismatches == 0
            and checks["price_partition_hash_metadata_checks_pass"]
            and checks["prefix_invariance_pass"]
            and not validation_errors
        )
        checks["worker_error_count"] = checks["worker_error_count"]
        status = "PASS" if checks["all_required_pass"] else "CHECK_REQUIRED"
        final_token = FINAL_TOKEN if status == "PASS" else CHECK_TOKEN

        write_frame(OUT / "p3_2_strategy_metrics.csv", metrics_frame)
        write_frame(OUT / "p3_2_strategy_metrics_reconciled.csv", metrics_frame)
        write_frame(OUT / "p3_2_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p3_2_large_outcomes.csv", thresholds)
        write_frame(OUT / "p3_2_exit_reason_distribution.csv", exits)
        write_frame(OUT / "p3_2_progressed_reconciliation_audit.csv", progressed)
        write_frame(OUT / "p3_2_trade_frequency_by_year.csv", annual)
        write_frame(OUT / "p3_2_trade_frequency_by_month.csv", monthly)
        write_frame(OUT / "p3_2_pit_entry_causality_audit.csv", pit_audit)
        write_frame(OUT / "p3_2_p3_1_prefix_invariance_audit.csv", prefix_audit)
        write_frame(OUT / "p3_2_price_store_audit.csv", price_audit)
        write_json(OUT / "p3_2_execution_audit.json", {
            "status": status,
            "final_token": final_token,
            "work_id": WORK_ID,
            "window_id": WINDOW_ID,
            "window": WINDOW,
            "worker_count": WORKERS,
            "execution": execution,
            "checks": checks,
            "elapsed_seconds": time.perf_counter() - started,
        })
        report = markdown_report(metrics_frame, deltas, exits, thresholds, checks, pre, prefix_summary, annual, sample, time.perf_counter() - started)
        (OUT / "report.md").write_text(report, encoding="utf-8")
        for csv_name in ("p3_2_market_cap_filter_audit.csv", "p3_2_ma60_signal_audit.csv", "p3_2_alignment_signal_audit.csv", "p3_2_price_store_audit.csv"):
            path = OUT / csv_name
            if path.is_file():
                p2.compress_verified(path)

        source_hashes = pre["input_source_hashes"]
        partition_columns = ["ticker", "relative_path", "sha256", "metadata_relative_path", "metadata_sha256", "source_authority_id", "source_semantics", "authority_type", "row_count", "actual_date_min", "actual_date_max"]
        partition_hashes = price_audit[[column for column in partition_columns if column in price_audit.columns]].to_dict("records") if len(price_audit) else []
        provenance = {
            "status": status,
            "final_token": final_token,
            "work_id": WORK_ID,
            "scope": "P3-2 corrected simple trade-level replay; no portfolio allocation/MDD/adoption claim",
            "window": WINDOW,
            "worker_count": WORKERS,
            "network_calls": network_calls,
            "market_cap_filter": "NONE",
            "market_cap_based_reject_count": checks["market_cap_based_reject_count"],
            "current_survivor_membership_used": False,
            "permanent_exclusion_registry_count": pre["permanent_exclusion_registry_count"],
            "permanent_exclusion_duplicate_exact_pair_count": pre["permanent_exclusion_duplicate_exact_pair_count"],
            "historical_common_identity_key_count": pre["historical_common_identity_key_count"],
            "historical_common_segment_count": pre["historical_common_segment_count"],
            "eligible_identity_key_count": pre["eligible_historical_identity_key_count"],
            "eligible_segment_count": pre["p3_2_window_pit_segment_count"],
            "unique_ticker_count": pre["unique_ticker_count"],
            "cost_contract": pre["cost_contract"],
            "result_reuse": pre["result_reuse"],
            "p3_1_prefix_invariance": prefix_summary,
            "integrity": checks,
            "source_hashes": source_hashes,
            "p3_1_baseline": pre["p3_1_baseline"],
            "sample_benchmark": sample,
            "adjusted_price_store_partition_hashes": partition_hashes,
            "execution_script_sha256": sha256(Path(__file__)),
            "artifact_sha256": {
                path.name: sha256(path)
                for path in sorted(OUT.iterdir())
                if path.is_file() and path.name not in {"p3_2_provenance.json", "artifact_manifest.json"}
            },
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(OUT / "p3_2_provenance.json", provenance)
        manifest_files = {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        }
        write_json(OUT / "artifact_manifest.json", {"status": status, "final_token": final_token, "files": manifest_files})
        written_manifest = json.loads((OUT / "artifact_manifest.json").read_text(encoding="utf-8"))
        manifest_ok = all(sha256(OUT / name) == digest for name, digest in written_manifest["files"].items())
        require(manifest_ok, "P3_2_ARTIFACT_MANIFEST_HASH_MISMATCH")
        require(network_calls == 0, "NETWORK_CALLS_DURING_REPLAY")
        print(json.dumps({"status": status, "final_token": final_token, "checks": checks, "elapsed_seconds": time.perf_counter() - started, "artifact_manifest_hashes_pass": manifest_ok}, ensure_ascii=False, indent=2, default=str))
        return 0 if status == "PASS" else 2
    except Exception as exc:
        if REPLAY_STARTED or "--full-after-sample" in sys.argv or "--sample-only" in sys.argv:
            try:
                OUT.mkdir(parents=True, exist_ok=True)
                write_json(OUT / "failure.json", {
                    "status": "CHECK_REQUIRED",
                    "final_token": CHECK_TOKEN,
                    "stage": STAGE,
                    "replay_started": REPLAY_STARTED,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "automatic_retry": False,
                    "partial_output_is_final_result": False,
                    "next_action": "stop and report; do not automatically replay or interpret incomplete metrics",
                })
            except Exception:
                pass
        elif "--preflight-only" in sys.argv:
            print(json.dumps({"status": "BLOCKED", "stage": STAGE, "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
