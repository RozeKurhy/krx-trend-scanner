#!/usr/bin/env python3
"""Re-evaluate only P3-1's 117 exact Repository V2 price-input identities."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
P32 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01"
PRICE_DIR = ROOT / "data/market/adjusted/stocks"
EVAL_START = pd.Timestamp("2022-01-03")
CUTOFF = pd.Timestamp("2025-05-30")
SUPPORT = pd.Timestamp("2025-06-02")
WARMUP_START = pd.Timestamp("2017-01-01")
WORKERS = 10

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.repository_v2_loader import build_repository_v2
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def load_runner():
    path = P31 / "run_official_realistic_replay.py"
    spec = importlib.util.spec_from_file_location("p31_official_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P31_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def verify_hash_manifest(folder: Path) -> dict[str, Any]:
    payload = json.loads((folder / "artifact_hashes.json").read_text(encoding="utf-8"))
    checked = 0
    mismatches: list[dict[str, Any]] = []
    for row in payload.get("files", []):
        path = folder / row["path"]
        if not path.is_file():
            mismatches.append({"path": row["path"], "reason": "MISSING"})
            continue
        digest = sha256(path)
        size = path.stat().st_size
        checked += 1
        if digest != row.get("sha256") or size != row.get("bytes"):
            mismatches.append({"path": row["path"], "expected_sha256": row.get("sha256"), "actual_sha256": digest, "expected_bytes": row.get("bytes"), "actual_bytes": size})
    return {"checked": checked, "expected": len(payload.get("files", [])), "mismatches": mismatches, "pass": checked == len(payload.get("files", [])) and not mismatches, "manifest_sha256": sha256(folder / "artifact_hashes.json")}


class CachedDailyLoader:
    def __init__(self, ticker: str, frame: pd.DataFrame):
        self.ticker = ticker
        self.frame = frame

    def load(self, ticker: str) -> pd.DataFrame | None:
        if str(ticker).zfill(6) != self.ticker:
            raise RuntimeError(f"CACHED_DAILY_LOADER_TICKER_MISMATCH:{ticker}:{self.ticker}")
        return self.frame


def main() -> int:
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin_main = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if head != "bef07ad77f56222b468c3efb65f04008735cec5c" or origin_main != head or branch != "main":
        raise RuntimeError(f"BASELINE_NOT_SEALED:{branch}:{head}:{origin_main}")

    runner = load_runner()
    p31_hash_audit = verify_hash_manifest(P31)
    p32_hash_audit = verify_hash_manifest(P32)
    if not p31_hash_audit["pass"] or not p32_hash_audit["pass"]:
        raise RuntimeError(f"REFERENCE_ARTIFACT_HASH_MISMATCH:{p31_hash_audit['mismatches'][:2]}:{p32_hash_audit['mismatches'][:2]}")

    p31_integrity = json.loads((P31 / "integrity_audit.json").read_text(encoding="utf-8"))
    old_preflight = json.loads((P31 / "preflight.json").read_text(encoding="utf-8"))
    p31_unavailable = sorted(str(x).zfill(6) for x in p31_integrity["unresolved_universe_price_tickers"])
    bounds = pd.read_csv(P31 / "identity_repository_v2_bounds.csv", dtype=str, keep_default_na=False)
    bounds["ticker"] = bounds["ticker"].str.zfill(6)
    bounds["isu_cd"] = bounds["isu_cd"].str.strip().str.upper()
    target_bounds = bounds[bounds["ticker"].isin(p31_unavailable)].copy()
    target_bounds = target_bounds[target_bounds["repository_v2_range_intersects_p3_1_pit"].str.lower().isin({"true", "1"})]
    target_pairs = {(r.ticker, r.isu_cd) for r in target_bounds.itertuples(index=False)}
    if len(target_pairs) != 117 or len(target_bounds) != 117 or set(target_bounds["ticker"]) != set(p31_unavailable):
        raise RuntimeError(f"P31_TARGET_IDENTITY_SET_INVALID:{len(p31_unavailable)}:{len(target_bounds)}:{len(target_pairs)}")

    p32_audit = pd.read_csv(P32 / "price_input_124_audit.csv", dtype=str, keep_default_na=False)
    p32_audit["ticker"] = p32_audit["ticker"].str.zfill(6)
    p32_audit["isu_cd"] = p32_audit["isu_cd"].str.strip().str.upper()
    p32_records = p32_audit.to_dict("records")
    p32_pairs = {(r["ticker"], r["isu_cd"]) for r in p32_records if r.get("targeted_data_status") == "AVAILABLE"}
    p32_target_match = target_pairs & p32_pairs
    if p32_target_match != target_pairs:
        raise RuntimeError(f"P31_117_NOT_ALL_IN_P32_BOUNDED_SUCCESS:{len(p32_target_match)}/117")

    # Confirm the frozen authority and exact KRX calendar have not drifted.
    calendar, pit_payload, calendar_payload, segments_by_ticker = runner.build_authority()
    current_pairs = {
        (str(segment.ticker).zfill(6), str(segment.isu_cd).strip().upper(), str(segment.market).strip().upper(), segment.effective_from.strftime("%Y-%m-%d"), segment.effective_to.strftime("%Y-%m-%d"))
        for segments in segments_by_ticker.values() for segment in segments
    }
    prior_pairs = {
        (str(r.ticker).zfill(6), str(r.isu_cd).strip().upper(), str(r.market).strip().upper(), str(r.pit_effective_from), str(r.pit_effective_to))
        for r in bounds.itertuples(index=False)
    }
    if current_pairs != prior_pairs:
        raise RuntimeError(f"P31_PIT_AUTHORITY_SET_CHANGED:{len(current_pairs)}:{len(prior_pairs)}")
    eval_sessions = [pd.Timestamp(d).normalize() for d in calendar.trading_dates if EVAL_START <= pd.Timestamp(d).normalize() <= CUTOFF]
    if len(eval_sessions) != 834 or eval_sessions[0] != EVAL_START or eval_sessions[-1] != CUTOFF:
        raise RuntimeError(f"P31_CALENDAR_MISMATCH:{len(eval_sessions)}")

    current_exclusions = {(str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS}
    canonical_payload = {"schema": "sorted_exact_pair_json_v01", "pairs": [list(pair) for pair in sorted(current_exclusions)]}
    canonical_exclusion_hash = hashlib.sha256(json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    expected_exclusion_hash = old_preflight.get("universe", {}).get("permanent_exclusion_registry_canonical_sha256")
    registry_source = ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"
    registry_source_hash = sha256(registry_source)
    if len(current_exclusions) != 182 or canonical_exclusion_hash != expected_exclusion_hash or registry_source_hash != old_preflight.get("universe", {}).get("permanent_exclusion_registry_source_sha256"):
        raise RuntimeError("PERMANENT_EXCLUSION_REGISTRY_DRIFT")
    if target_pairs & current_exclusions:
        raise RuntimeError("TARGET_PAIR_LEAKS_PERMANENT_EXCLUSIONS")

    required_source_paths = [
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/validation/backtest_common_rules.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "src/trend_scanner/patterns/pattern_a_fast_evaluator.py",
        "src/trend_scanner/data/repository_v2.py",
        "src/trend_scanner/data/repository_v2_loader.py",
        "src/trend_scanner/data/krx_raw_stock_store.py",
        "scripts/run_v2_official_adoption_revalidation_v02.py",
        "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        "data/market/rolling_authority/manifest.json",
        "data/market/rolling_authority/merged_pit_intervals.json",
        "data/market/rolling_authority/merged_trading_calendar.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
    ]
    source_hashes = {rel: sha256(ROOT / rel) for rel in required_source_paths}
    sealed_source_manifest = json.loads((P31 / "source_manifest.json").read_text(encoding="utf-8"))
    sealed_source_map = {row["path"]: row["sha256"] for row in sealed_source_manifest.get("source_files", []) + sealed_source_manifest.get("authority_data_files", [])}
    source_hash_mismatches = []
    for rel, digest in source_hashes.items():
        expected_digest = sealed_source_map.get(rel)
        if expected_digest is None:
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True)
            if tracked.returncode == 0:
                baseline_bytes = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT)
                expected_digest = hashlib.sha256(baseline_bytes).hexdigest()
        if expected_digest != digest:
            source_hash_mismatches.append({"path": rel, "sealed_sha256": expected_digest, "current_sha256": digest})
    if source_hash_mismatches:
        raise RuntimeError(f"SEALED_P31_SOURCE_HASH_MISMATCH:{source_hash_mismatches[:5]}")

    # Hash-check all 2,343 previously available adjusted files before reusing their ledgers.
    old_price_hashes = pd.read_csv(P31 / "repository_v2_adjusted_price_file_hashes.csv", dtype=str, keep_default_na=False)
    def hash_old_price(row: dict[str, str]) -> dict[str, Any]:
        path = ROOT / row["path"]
        actual = sha256(path) if path.is_file() else None
        return {"ticker": str(row["ticker"]).zfill(6), "path": row["path"], "expected_sha256": row["sha256"], "actual_sha256": actual, "pass": actual == row["sha256"]}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p31-baseline-hash") as pool:
        old_price_hash_results = list(pool.map(hash_old_price, old_price_hashes.to_dict("records")))
    old_price_hash_mismatches = [row for row in old_price_hash_results if not row["pass"]]
    if len(old_price_hash_results) != 2343 or old_price_hash_mismatches:
        raise RuntimeError(f"P31_2343_REUSED_PRICE_HASH_MISMATCH:{len(old_price_hash_results)}:{len(old_price_hash_mismatches)}")

    # Previous full-range diagnosis must show every raw-only mismatch outside P3-1 PIT and MA60 warmup.
    cause = pd.read_csv(P31 / "repository_v2_unavailable_cause_audit.csv", dtype=str, keep_default_na=False)
    cause["ticker"] = cause["ticker"].str.zfill(6)
    cause_by_ticker = {r["ticker"]: r for r in cause.to_dict("records")}
    p32_by_pair = {(r["ticker"], r["isu_cd"]): r for r in p32_records}
    old_cause_ok = True
    for ticker, _isu in target_pairs:
        row = cause_by_ticker.get(ticker, {})
        old_cause_ok &= row.get("unclassified_raw_only_dates_inside_p3_1_pit_or_ma_warmup") == "0"
        old_cause_ok &= row.get("projected_date_set_exact_match") == "False"
        p32row = p32_by_pair[(ticker, _isu)]
        old_cause_ok &= p32row.get("all_unresolved_dates_before_pit_start") == "True"
        old_cause_ok &= p32row.get("unresolved_mismatch_dates_inside_pit", "") == ""
    if not old_cause_ok:
        raise RuntimeError("P3_1_FULL_RANGE_MISMATCH_NOT_PROVEN_PRE_PIT_AND_WARMUP")

    preflight = {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_preflight_v01",
        "work_id": "FAST_CORE_V2_ALIGNMENT_500B_P3_1_117_PRICE_NAV_CLOSURE_V01",
        "status": "PASS",
        "branch": branch,
        "baseline_head": head,
        "baseline_origin_main": origin_main,
        "plan_commit": "adf4e7e69907cc9b13cafb941a5c3aecde924181",
        "old_p3_1_artifact_hashes": p31_hash_audit,
        "p3_2_artifact_hashes": p32_hash_audit,
        "p3_1_reused_adjusted_price_files": {"count": len(old_price_hash_results), "mismatches": len(old_price_hash_mismatches)},
        "target_identity_pairs": {"count": len(target_pairs), "p3_2_bounded_load_matches": len(p32_target_match), "extra_identity_or_ticker_rows": len(target_bounds) - len(target_pairs)},
        "targeted_full_range_mismatch_cause": {"all_raw_only_mismatches_outside_p3_1_pit_and_ma60_warmup": old_cause_ok},
        "rolling_authority": {"identity_rows": len(current_pairs), "matches_p3_1_bounds": current_pairs == prior_pairs, "evaluation_sessions": len(eval_sessions), "calendar_matches": len(eval_sessions) == 834},
        "permanent_exclusions": {"pair_count": len(current_exclusions), "canonical_sha256": canonical_exclusion_hash, "source_sha256": registry_source_hash, "matches_sealed_p3_1": canonical_exclusion_hash == expected_exclusion_hash},
        "source_hashes": source_hashes,
        "workers": WORKERS,
        "strategy_rule_changes": False,
        "p1_p2_or_p3_2_execution": False,
        "external_api_calls": 0,
    }
    write_json(OUT / "preflight.json", preflight)

    repository = build_repository_v2(ROOT, end=SUPPORT)
    score_contract = json.loads((ROOT / runner.SCORE_CONTRACT_PATH.relative_to(ROOT)).read_text(encoding="utf-8"))
    stage_contract = json.loads((ROOT / runner.STAGE_CONTRACT_PATH.relative_to(ROOT)).read_text(encoding="utf-8"))
    mcap = runner.ExactSignalMcap()
    adjusted_store = AdjustedPriceStore(PRICE_DIR)
    p32_row_map = p32_by_pair
    bounds_rows = {(r.ticker, r.isu_cd): r._asdict() for r in target_bounds.itertuples(index=False)}
    outcomes: dict[str, dict[str, Any]] = {}
    audit_loads: dict[str, dict[str, Any]] = {}

    def worker(pair: tuple[str, str]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        ticker, isu = pair
        identity = bounds_rows[pair]
        adjusted_path = ROOT / identity["repository_v2_path"]
        file_hash = sha256(adjusted_path)
        expected = p32_row_map[pair]["adjusted_file_sha256_expected"]
        if file_hash != expected or file_hash != identity["repository_v2_file_sha256"]:
            raise RuntimeError(f"TARGET_ADJUSTED_FILE_HASH_MISMATCH:{ticker}")
        adjusted_frame = adjusted_store.load_daily(ticker)
        if adjusted_frame.empty:
            raise RuntimeError(f"TARGET_ADJUSTED_FILE_EMPTY:{ticker}")
        adjusted_first = adjusted_frame.index.min().normalize()
        adjusted_last = adjusted_frame.index.max().normalize()
        row_start = max(adjusted_first, pd.Timestamp(identity["pit_effective_from"]).normalize())
        row_start_text = row_start.strftime("%Y-%m-%d")
        try:
            raw_composed = repository.get_daily(ticker, row_start_text, SUPPORT.strftime("%Y-%m-%d"))
        except Exception as exc:
            return ticker, {
                "ticker": ticker, "isu_cd": isu, "data_status": "ERROR", "errors": [f"{type(exc).__name__}:{str(exc)[:300]}"],
                "control_trades": [], "candidate_trades": [], "audits": [],
            }, {
                "ticker": ticker, "isu_cd": isu, "market": identity["market"], "pit_effective_from": identity["pit_effective_from"], "pit_effective_to": identity["pit_effective_to"],
                "adjusted_file_sha256_current": file_hash, "adjusted_rows": len(adjusted_frame), "adjusted_first": adjusted_first.strftime("%Y-%m-%d"), "adjusted_last": adjusted_last.strftime("%Y-%m-%d"),
                "bounded_load_start": row_start_text, "bounded_load_end": SUPPORT.strftime("%Y-%m-%d"), "load_status": "ERROR", "first_error": f"{type(exc).__name__}:{str(exc)[:300]}",
            }
        if raw_composed is None or raw_composed.empty:
            return ticker, {
                "ticker": ticker, "isu_cd": isu, "data_status": "DATA_UNAVAILABLE", "errors": ["REPOSITORY_V2_EMPTY"],
                "control_trades": [], "candidate_trades": [], "audits": [],
            }, {
                "ticker": ticker, "isu_cd": isu, "market": identity["market"], "pit_effective_from": identity["pit_effective_from"], "pit_effective_to": identity["pit_effective_to"],
                "adjusted_file_sha256_current": file_hash, "adjusted_rows": len(adjusted_frame), "adjusted_first": adjusted_first.strftime("%Y-%m-%d"), "adjusted_last": adjusted_last.strftime("%Y-%m-%d"),
                "bounded_load_start": row_start_text, "bounded_load_end": SUPPORT.strftime("%Y-%m-%d"), "load_status": "EMPTY", "first_error": "REPOSITORY_V2_EMPTY",
            }
        projection = raw_composed.attrs.get("session_projection_audit", {})
        daily = raw_composed.sort_index().copy()
        compact_audit = {
            "adjusted_only_count": len(projection.get("adjusted_only_dates", ())),
            "raw_only_count": len(projection.get("raw_only_dates", ())),
            "explicit_exclusion_count": sum(int(projection.get(k, 0) or 0) for k in (
                "explicit_placeholder_projection_count", "explicit_known_gap_exclusion_count", "explicit_outside_identity_lifecycle_exclusion_count",
                "explicit_adjusted_source_nonusable_exclusion_count", "explicit_analytic_invalid_exclusion_count")),
            "silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
        }
        daily.attrs = {
            "data_authority": "MarketDataRepositoryV2",
            "session_projection_summary": compact_audit,
            "requested_start": row_start_text,
            "requested_end": SUPPORT.strftime("%Y-%m-%d"),
            "effective_as_of": daily.index.max().strftime("%Y-%m-%d"),
        }
        load_info = {
            "ticker": ticker, "isu_cd": isu, "market": identity["market"], "pit_effective_from": identity["pit_effective_from"], "pit_effective_to": identity["pit_effective_to"],
            "adjusted_file_sha256_expected": expected, "adjusted_file_sha256_current": file_hash,
            "adjusted_rows": len(adjusted_frame), "adjusted_first": adjusted_first.strftime("%Y-%m-%d"), "adjusted_last": adjusted_last.strftime("%Y-%m-%d"),
            "bounded_load_start": row_start_text, "bounded_load_end": SUPPORT.strftime("%Y-%m-%d"), "load_status": "AVAILABLE",
            "targeted_daily_rows": len(daily), "targeted_first_daily_date": daily.index.min().strftime("%Y-%m-%d"), "targeted_last_daily_date": daily.index.max().strftime("%Y-%m-%d"),
            "projection_adjusted_only_count": len(projection.get("adjusted_only_dates", ())),
            "projection_unexplained_adjusted_only_count": len(projection.get("unexplained_adjusted_only_dates", ())),
            "projection_raw_only_count": len(projection.get("raw_only_dates", ())),
            "projection_rejected_raw_only_count": len(projection.get("rejected_raw_only_dates", ())),
            "projection_projected_date_set_exact_match": bool(projection.get("projected_date_set_exact_match")),
            "projection_silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
            "pit_internal_unresolved_session_count": len(projection.get("unexplained_adjusted_only_dates", ())) + len(projection.get("rejected_raw_only_dates", ())),
            "first_error": "",
        }
        outcome = runner.evaluator_rows_for_ticker(
            ticker, loader=CachedDailyLoader(ticker, daily), calendar=calendar, segments_by_ticker=segments_by_ticker,
            score_contract=score_contract, stage_contract=stage_contract, mcap_resolver=mcap,
        )
        if outcome.get("data_status") != "AVAILABLE" or outcome.get("errors"):
            load_info["load_status"] = str(outcome.get("data_status"))
            load_info["first_error"] = "|".join(str(x) for x in outcome.get("errors", []))
        # The target is one exact identity per ticker in P3-1. Any extra identity is a scope error.
        emitted = {(str(row["ticker"]).zfill(6), str(row["isu_cd"]).strip().upper()) for row in outcome.get("control_trades", []) + outcome.get("candidate_trades", [])}
        emitted |= {(str(row["ticker"]).zfill(6), str(row.get("isu_cd") or "").strip().upper()) for row in outcome.get("audits", []) if row.get("pit_status") == "PASS"}
        if emitted - {pair}:
            load_info["scope_error"] = sorted([list(x) for x in emitted - {pair}])
        return ticker, outcome, load_info

    runner.install_per_ticker_evaluation_cache()
    print(f"P3-1 targeted evaluation: {len(target_pairs)} exact identities / workers={WORKERS}", flush=True)
    errors: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p3-1-price-restore") as pool:
        futures = {pool.submit(worker, pair): pair for pair in sorted(target_pairs)}
        for future in as_completed(futures):
            ticker, outcome, load_info = future.result()
            outcomes[ticker] = outcome
            audit_loads[ticker] = load_info
            if outcome.get("errors") or outcome.get("data_status") != "AVAILABLE" or load_info.get("scope_error"):
                errors.append({"ticker": ticker, "errors": outcome.get("errors", []), "data_status": outcome.get("data_status"), "scope_error": load_info.get("scope_error")})
            if len(outcomes) % 20 == 0 or len(outcomes) == len(target_pairs):
                print(f"completed {len(outcomes)}/{len(target_pairs)}; worker-errors={len(errors)}", flush=True)

    control_rows = [row for outcome in outcomes.values() for row in outcome.get("control_trades", [])]
    candidate_rows = [row for outcome in outcomes.values() for row in outcome.get("candidate_trades", [])]
    filter_rows = [row for outcome in outcomes.values() for row in outcome.get("audits", [])]
    control_rows.sort(key=lambda r: (r["entry_execution_date"], str(r["ticker"]).zfill(6), r["isu_cd"], r["entry_signal_date"], r["trade_id"]))
    candidate_rows.sort(key=lambda r: (r["entry_execution_date"], str(r["ticker"]).zfill(6), r["isu_cd"], r["entry_signal_date"], r["trade_id"]))
    filter_rows.sort(key=lambda r: (r["signal_date"], str(r["ticker"]).zfill(6), str(r.get("isu_cd") or "")))

    # Every target signal/audit must bind to exactly the frozen P3-1 identity.
    if any((str(row["ticker"]).zfill(6), str(row["isu_cd"]).strip().upper()) not in target_pairs for row in control_rows + candidate_rows):
        raise RuntimeError("TARGET_TRADE_IDENTITY_SCOPE_LEAK")
    audit_keys = [(str(r["ticker"]).zfill(6), str(r.get("isu_cd") or "").strip().upper(), str(r["signal_date"])[:10]) for r in filter_rows]
    audit_unique = len(audit_keys) == len(set(audit_keys))
    if not audit_unique:
        raise RuntimeError("TARGET_FILTER_AUDIT_DUPLICATE_IDENTITY_SIGNAL")

    pd.DataFrame(control_rows).to_csv(OUT / "targeted_control_signal_trades.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(OUT / "targeted_candidate_signal_trades.csv", index=False)
    pd.DataFrame(filter_rows).to_csv(OUT / "targeted_signal_filter_audit.csv", index=False)
    worker_rows = []
    for ticker, outcome in sorted(outcomes.items()):
        worker_rows.append({k: outcome.get(k) for k in ("ticker", "data_status", "unavailable_reason", "daily_rows", "first_daily_date", "last_daily_date", "evaluation_cache_hits", "evaluation_cache_misses", "errors")})
    pd.DataFrame(worker_rows).to_csv(OUT / "worker_results.csv", index=False)

    p32_by_pair = {(r["ticker"], r["isu_cd"]): r for r in p32_audit.to_dict("records")}
    bounds_by_pair = {(str(r["ticker"]).zfill(6), str(r["isu_cd"]).strip().upper()): r for r in target_bounds.to_dict("records")}
    cause_by_ticker = {str(r["ticker"]).zfill(6): r for r in cause.to_dict("records")}
    audit_rows: list[dict[str, Any]] = []
    for pair in sorted(target_pairs):
        info = audit_loads.get(pair[0], {})
        outcome = outcomes.get(pair[0], {})
        prior = p32_by_pair[pair]
        prior_cause = cause_by_ticker[pair[0]]
        target = bounds_by_pair[pair]
        applicable = [s for s in segments_by_ticker[pair[0]] if s.isu_cd.strip().upper() == pair[1]]
        in_window = [s for s in applicable if s.effective_from <= CUTOFF and s.effective_to >= EVAL_START]
        months_covered = None
        if info.get("adjusted_first"):
            first_month = pd.Timestamp(info["adjusted_first"]).to_period("M")
            months_covered = max(0, len(pd.period_range(first_month, pd.Period("2021-12", freq="M"))))
        audit_rows.append({
            "ticker": pair[0], "isu_cd": pair[1], "market": target["market"],
            "pit_effective_from": target["pit_effective_from"], "pit_effective_to": target["pit_effective_to"],
            "p3_1_eval_pit_from": max(pd.Timestamp(target["pit_effective_from"]), EVAL_START).strftime("%Y-%m-%d"),
            "p3_1_eval_pit_to": min(pd.Timestamp(target["pit_effective_to"]), CUTOFF).strftime("%Y-%m-%d"),
            "adjusted_file_path": target["repository_v2_path"],
            "adjusted_file_sha256_expected": prior["adjusted_file_sha256_expected"],
            "adjusted_file_sha256_current": info.get("adjusted_file_sha256_current"),
            "adjusted_file_hash_match": info.get("adjusted_file_sha256_current") == prior["adjusted_file_sha256_expected"],
            "adjusted_rows": info.get("adjusted_rows"), "adjusted_first": info.get("adjusted_first"), "adjusted_last": info.get("adjusted_last"),
            "bounded_load_start": info.get("bounded_load_start"), "bounded_load_end": info.get("bounded_load_end"),
            "targeted_data_status": info.get("load_status"), "targeted_daily_rows": info.get("targeted_daily_rows"),
            "targeted_first_daily_date": info.get("targeted_first_daily_date"), "targeted_last_daily_date": info.get("targeted_last_daily_date"),
            "projection_adjusted_only_count": info.get("projection_adjusted_only_count"),
            "projection_unexplained_adjusted_only_count": info.get("projection_unexplained_adjusted_only_count"),
            "projection_raw_only_count": info.get("projection_raw_only_count"),
            "projection_rejected_raw_only_count": info.get("projection_rejected_raw_only_count"),
            "projection_date_sets_exact": info.get("projection_projected_date_set_exact_match"),
            "projection_silent_inner_drops": info.get("projection_silent_inner_drop_count"),
            "pit_internal_unresolved_session_count": info.get("pit_internal_unresolved_session_count"),
            "old_full_range_raw_mismatch_dates": prior.get("unresolved_expected_session_date_count"),
            "old_full_range_mismatches_inside_p3_1_pit_or_ma60_warmup": prior_cause.get("unclassified_raw_only_dates_inside_p3_1_pit_or_ma_warmup"),
            "old_mismatches_all_before_pit_start": prior.get("all_unresolved_dates_before_pit_start"),
            "required_first_ma60_warmup_month": WARMUP_START.strftime("%Y-%m"),
            "calendar_months_available_through_2021_12": months_covered,
            "signal_audit_rows": sum(1 for r in outcome.get("audits", [])),
            "control_trade_signal_rows": len(outcome.get("control_trades", [])),
            "candidate_trade_signal_rows": len(outcome.get("candidate_trades", [])),
            "candidate_ma_unavailable_signal_count": sum(str(r.get("ma_status")) == "MA_UNAVAILABLE" for r in outcome.get("audits", [])),
            "candidate_ma_missing_window_count": sum(str(r.get("ma_reason")) == "MISSING_PRIOR_COMPLETED_MONTH_BARS" for r in outcome.get("audits", [])),
            "pit_segment_count": len(in_window),
            "first_error": info.get("first_error", ""),
            "scope_error": json.dumps(info.get("scope_error", []), ensure_ascii=False),
        })
    pd.DataFrame(audit_rows).sort_values(["ticker", "isu_cd"]).to_csv(OUT / "price_input_117_audit.csv", index=False)

    partition_rows = []
    for (market, day), (manifest, _caps, error) in sorted(mcap.cache.items()):
        partition_rows.append({
            "market": market, "partition_date": day,
            "status": None if manifest is None else manifest.get("status"),
            "file_path": None if manifest is None else manifest.get("file_path"),
            "file_sha256": None if manifest is None else manifest.get("file_sha256"),
            "content_sha256": None if manifest is None else manifest.get("content_sha256"),
            "resolution_error": error,
        })
    pd.DataFrame(partition_rows).to_csv(OUT / "targeted_signal_date_krx_partition_hashes.csv", index=False)

    status_counts = pd.Series([r.get("candidate_status") for r in filter_rows]).value_counts().sort_index().to_dict() if filter_rows else {}
    audit = pd.DataFrame(audit_rows)
    projection_ok = bool(audit["targeted_data_status"].eq("AVAILABLE").all()) and bool(audit["adjusted_file_hash_match"].all()) and bool(pd.to_numeric(audit["pit_internal_unresolved_session_count"], errors="coerce").fillna(1).eq(0).all()) and bool(audit["projection_date_sets_exact"].map(lambda x: str(x).lower() == "true").all()) and bool(pd.to_numeric(audit["projection_silent_inner_drops"], errors="coerce").fillna(1).eq(0).all())
    candidate_ma_rows = [r for r in filter_rows if r.get("seen_in_candidate_scan")]
    ma_window_end_before_signal = all(
        not r.get("ma60_window_last_month") or str(r.get("ma60_window_last_month")) < str(r.get("signal_date"))[:7]
        for r in candidate_ma_rows
    )
    mcap_unresolved = sum(r.get("mcap_status") == "UNRESOLVED" for r in candidate_ma_rows)
    execution = {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_targeted_execution_v01",
        "status": "TARGETED_EVALUATION_COMPLETE" if not errors and len(outcomes) == 117 and projection_ok and ma_window_end_before_signal and mcap_unresolved == 0 else "CHECK_REQUIRED",
        "identity_pairs": 117,
        "workers": WORKERS,
        "worker_outcomes": len(outcomes),
        "worker_error_count": len(errors),
        "worker_errors": errors,
        "bounded_projection_integrity_pass": projection_ok,
        "candidate_monthly_window_end_precedes_signal_month": ma_window_end_before_signal,
        "candidate_mcap_unresolved_signal_count": int(mcap_unresolved),
        "target_control_trade_signal_rows": len(control_rows),
        "target_candidate_trade_signal_rows": len(candidate_rows),
        "target_filter_audit_rows": len(filter_rows),
        "candidate_filter_status_counts": status_counts,
        "raw_signal_date_partition_count": len(mcap.cache),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "candidate_signal_examples": [{k: r.get(k) for k in ("ticker", "isu_cd", "signal_date", "candidate_status", "market_cap_krw", "ma_status", "ma_reason")} for r in filter_rows if r.get("candidate_status") == "PASS"][:30],
    }
    write_json(OUT / "targeted_execution.json", execution)
    write_json(OUT / "targeted_signal_evaluation_raw.json", outcomes)
    write_json(OUT / "replay_decision.json", {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_replay_decision_v01",
        "status": "TARGETED_SIGNALS_AVAILABLE_FOR_PORTFOLIO_REPLAY" if execution["status"] == "TARGETED_EVALUATION_COMPLETE" and (control_rows or candidate_rows) else "NO_NEW_PORTFOLIO_SIGNAL_ROWS" if execution["status"] == "TARGETED_EVALUATION_COMPLETE" else "CHECK_REQUIRED",
        "targeted_identity_count": 117, "workers": WORKERS,
        "new_control_trade_signal_rows": len(control_rows), "new_candidate_trade_signal_rows": len(candidate_rows),
        "new_signal_rows_have_possible_cash_impact": bool(control_rows or candidate_rows),
        "portfolio_replay_required": bool(control_rows or candidate_rows),
        "next_action": "Replay CONTROL and candidate sequentially from 2022-01-03 after merging verified V01 ledgers." if control_rows or candidate_rows else "Reuse V01 portfolio ledgers after hash verification; no new target entry rows were emitted.",
        "p3_2_signal_or_trade_ledgers_copied": False,
        "unresolved_data_errors": errors,
    })
    print(json.dumps({k: execution[k] for k in ("status", "identity_pairs", "workers", "worker_outcomes", "worker_error_count", "target_control_trade_signal_rows", "target_candidate_trade_signal_rows", "target_filter_audit_rows", "candidate_filter_status_counts", "elapsed_seconds")}, ensure_ascii=False, indent=2), flush=True)
    return 0 if execution["status"] == "TARGETED_EVALUATION_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
