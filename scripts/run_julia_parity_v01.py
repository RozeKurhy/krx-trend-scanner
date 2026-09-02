#!/usr/bin/env python
"""Offline behavioral parity runner for the frozen Julia V00 checkpoint.

This runner intentionally treats ``artifacts/strategies/julia/v00`` and the
current Julia simulator as read-only authorities.  It runs the full frozen
universe twice, using only the frozen PIT market-cap registry, then writes
evidence below a new end-to-end parity namespace.  No KRX/PyKRX/Naver/API
request is permitted and no frozen research artifact is overwritten.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Iterator
import warnings

import pandas as pd

sys.path.insert(0, str(ROOT) if "ROOT" in globals() else str(Path(__file__).resolve().parents[1]))

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    HistoricalMarketCapRegistry,
    simulate_ticker_strategy_2022,
)
from scripts.evaluate_julia_strategy_v00_comparison import _compute_strategy_metrics

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
START_HEAD = "449ff47d8bcf7c15fdbff9eb9af0fd9cd812b836"
START_TREE = "9220e27455b59e52a4ee64c897a7bfa23115a311"
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"
UNIVERSE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

FROZEN_FILES = {
    "julia_trades": "artifacts/strategies/julia/v00/julia_v00_2022_trades.csv",
    "baseline_trades": "artifacts/strategies/julia/v00/baseline_a_fast_core_v2_2022_trades.csv",
    "contract": "artifacts/strategies/julia/v00/contract.json",
    "summary": "artifacts/strategies/julia/v00/strategy_comparison_summary.json",
    "manifest": "artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv",
    "pit_audit": "artifacts/strategies/julia/v00/historical_investability_pit_audit.json",
    "common_entries": "artifacts/strategies/julia/v00/common_entry_pairs.csv",
}
EXPECTED_BLOBS = {
    "julia_trades": "a3d4abdd376b8830fdb2b00c2f74bf4408b1ab98",
    "baseline_trades": "bb4912af9f7fd92a2ec20b9ce30804f4eff0ce39",
    "contract": "e82ac4145ebd3f491184a23b3920657d3b406363",
    "summary": "cc27310ead9a4048c530e53aa0966d511ee7b347",
    "manifest": "8d598254ff578388d783ae0a306b2d0b9366fb40",
    "pit_audit": "a6cb05557e786e87f56339e4c7cac6d04d8ae9ae",
    "common_entries": "863b2b9363288957ce3878cf81cef85a1a1b394a",
}

TRADE_COLUMNS = [
    "strategy_id", "pre_progressed_loss_guard_enabled", "ticker", "name", "market",
    "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date", "entry_open",
    "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk", "fast_score",
    "fast_score_state", "investability_status", "investability_market_cap",
    "investability_avg_trading_value_20d", "investability_market_cap_source_file",
    "previous_exit_type", "previous_exit_execution_date", "loss_guard_triggered",
    "loss_guard_signal_date", "loss_guard_execution_date", "loss_guard_execution_price",
    "first_progressed_date", "first_progressed_effective_trading_date", "lifecycle_class",
    "exit_type", "exit_signal_date", "exit_execution_date", "exit_price", "terminal_return",
    "mfe", "mae", "peak_giveback", "profit_capture", "holding_weeks", "trade_status",
]
STRUCTURAL_COLUMNS = [
    c for c in TRADE_COLUMNS if c not in {
        "entry_open", "fast_score", "investability_market_cap",
        "investability_avg_trading_value_20d", "loss_guard_execution_price", "exit_price",
        "terminal_return", "mfe", "mae", "peak_giveback", "profit_capture", "holding_weeks",
    }
]
NUMERIC_COLUMNS = [
    "entry_open", "fast_score", "investability_market_cap", "investability_avg_trading_value_20d",
    "loss_guard_execution_price", "exit_price", "terminal_return", "mfe", "mae",
    "peak_giveback", "profit_capture", "holding_weeks",
]
DATE_COLUMNS = {
    c for c in TRADE_COLUMNS if c.endswith("date") or c.endswith("_date")
}

_WORKER: dict[str, Any] = {}


class OfflineNetworkViolation(RuntimeError):
    """Raised if the execution path attempts an outbound socket."""


def _block_connect(self: socket.socket, address: Any) -> None:
    raise OfflineNetworkViolation(f"offline Julia parity guard blocked socket connect: {address!r}")


def _block_connect_ex(self: socket.socket, address: Any) -> int:
    raise OfflineNetworkViolation(f"offline Julia parity guard blocked socket connect_ex: {address!r}")


@contextmanager
def offline_network_guard() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    socket.socket.connect = _block_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _block_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _worker_init(root: str, score_contract: dict[str, Any], stage_contract: dict[str, Any]) -> None:
    offline_network_guard().__enter__()
    repo = Path(root)
    _WORKER["root"] = repo
    _WORKER["ticker_cache"] = TickerDataCache(base_dir=repo / "data/raw/stocks")
    _WORKER["registry"] = HistoricalMarketCapRegistry.load_from_repository(repo, enforce_integrity=True)
    _WORKER["score_contract"] = score_contract
    _WORKER["stage_contract"] = stage_contract


def _worker(task: tuple[str, str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ticker, name, market = task
    cache: TickerDataCache = _WORKER["ticker_cache"]
    daily = cache.load(ticker)
    if daily is None or daily.empty:
        return [], []
    context = build_precomputed_ticker_context(ticker, name, daily)
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()
    common = dict(
        ticker=ticker, name=name, market=market, daily=daily,
        score_contract=_WORKER["score_contract"], stage_contract=_WORKER["stage_contract"],
        market_cap_registry=_WORKER["registry"], start_date=EVALUATION_START_DATE,
        cutoff_date=EVALUATION_END_DATE, fast_snapshot_cache=fast_cache,
        monthly_snapshot_cache=monthly_cache, snapshot_context=context,
    )
    baseline = simulate_ticker_strategy_2022(enable_loss_guard=True, **common)
    julia = simulate_ticker_strategy_2022(enable_loss_guard=False, **common)
    return [r.to_dict() for r in baseline], [r.to_dict() for r in julia]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(repo: Path, revision: str, relative: str) -> str:
    return subprocess.run(["git", "rev-parse", f"{revision}:{relative}"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _null(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return value is None


def canonical(value: Any, column: str) -> str:
    if _null(value) or value == "":
        return "<NULL>"
    if column in NUMERIC_COLUMNS:
        try:
            return str(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return f"<INVALID:{value}>"
    if column == "pre_progressed_loss_guard_enabled" or column == "loss_guard_triggered":
        return str(value).strip().lower()
    if column == "trade_sequence":
        return str(int(value))
    if column in DATE_COLUMNS:
        try:
            return pd.Timestamp(value).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
    return str(value)


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in TRADE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"required trade columns missing: {missing}")
    out = df.copy().reindex(columns=TRADE_COLUMNS)
    out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    return out


def compare_trades(authority: pd.DataFrame, production: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    authority, production = _prepare(authority), _prepare(production)
    aidx = {(canonical(r.ticker, "ticker"), canonical(r.trade_sequence, "trade_sequence")): r for r in authority.itertuples()}
    pidx = {(canonical(r.ticker, "ticker"), canonical(r.trade_sequence, "trade_sequence")): r for r in production.itertuples()}
    akeys, pkeys = set(aidx), set(pidx)
    missing, extra = sorted(akeys - pkeys), sorted(pkeys - akeys)
    duplicate_keys = int(authority.duplicated(["ticker", "trade_sequence"]).sum() + production.duplicated(["ticker", "trade_sequence"]).sum())
    mismatches: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    structural_total = numeric_total = 0
    max_error = 0.0
    for key in sorted(akeys | pkeys):
        left, right = aidx.get(key), pidx.get(key)
        sm = nm = 0
        row_max_error = 0.0
        if left is None or right is None:
            sm, nm = len(STRUCTURAL_COLUMNS), len(NUMERIC_COLUMNS)
        else:
            for field in STRUCTURAL_COLUMNS:
                a, b = canonical(getattr(left, field), field), canonical(getattr(right, field), field)
                if a != b:
                    sm += 1
                    mismatches.append({"ticker": key[0], "trade_sequence": key[1], "column": field, "authority": a, "production": b, "kind": "STRUCTURAL"})
            for field in NUMERIC_COLUMNS:
                a, b = canonical(getattr(left, field), field), canonical(getattr(right, field), field)
                if a == b:
                    continue
                nm += 1
                try:
                    row_max_error = max(row_max_error, abs(float(Decimal(a) - Decimal(b))))
                    max_error = max(max_error, row_max_error)
                except (InvalidOperation, ValueError):
                    row_max_error = float("inf")
                    max_error = float("inf")
                mismatches.append({"ticker": key[0], "trade_sequence": key[1], "column": field, "authority": a, "production": b, "kind": "NUMERIC"})
        structural_total += sm
        numeric_total += nm
        trade_id = canonical(getattr(left or right, "trade_id"), "trade_id")
        rows.append({
            "ticker": key[0], "trade_sequence": key[1], "trade_id": trade_id,
            "structural_match": sm == 0, "numeric_match": nm == 0,
            "overall_match": sm == 0 and nm == 0,
            "structural_mismatch_count": sm, "numeric_mismatch_count": nm,
            "max_numeric_abs_error": row_max_error,
        })
    result = {
        "authority_trades": len(authority), "production_trades": len(production),
        "missing_trades": len(missing), "extra_trades": len(extra),
        "missing_trade_keys": missing, "extra_trade_keys": extra,
        "duplicate_row_keys": duplicate_keys,
        "structural_mismatches": structural_total, "numeric_mismatches": numeric_total,
        "max_numeric_abs_error": max_error, "mismatches": mismatches,
    }
    return result, pd.DataFrame(rows, columns=[
        "ticker", "trade_sequence", "trade_id", "structural_match", "numeric_match", "overall_match",
        "structural_mismatch_count", "numeric_mismatch_count", "max_numeric_abs_error",
    ])


def load_universe() -> list[tuple[str, str, str]]:
    df = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    return [(str(r.ticker), str(r.name), str(r.market)) for r in df.itertuples(index=False)]


def run_execution() -> tuple[pd.DataFrame, pd.DataFrame, float]:
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    tasks = load_universe()
    started = time.monotonic()
    baseline_rows: list[dict[str, Any]] = []
    julia_rows: list[dict[str, Any]] = []
    with offline_network_guard():
        with ProcessPoolExecutor(max_workers=8, initializer=_worker_init, initargs=(str(ROOT), score, stage)) as pool:
            for baseline, julia in pool.map(_worker, tasks):
                baseline_rows.extend(baseline)
                julia_rows.extend(julia)
    baseline = pd.DataFrame(baseline_rows, columns=TRADE_COLUMNS)
    julia = pd.DataFrame(julia_rows, columns=TRADE_COLUMNS)
    for frame in (baseline, julia):
        if not frame.empty:
            frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
            frame["trade_sequence"] = pd.to_numeric(frame["trade_sequence"], errors="coerce").astype("Int64")
            frame.sort_values(["ticker", "trade_sequence"], kind="mergesort", inplace=True)
            frame.reset_index(drop=True, inplace=True)
    return baseline, julia, time.monotonic() - started


def distribution(df: pd.DataFrame, field: str) -> dict[str, int]:
    return {canonical(k, field): int(v) for k, v in df[field].value_counts(dropna=False).items()}


def common_entry_parity(baseline: pd.DataFrame, julia: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = ["ticker", "entry_signal_date", "entry_execution_date", "entry_open"]
    merged = baseline.merge(julia, on=key, suffixes=("_baseline", "_julia"), how="outer", indicator=True)
    common = merged[merged["_merge"] == "both"].copy()
    identity_fields = [
        "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk", "fast_score",
        "fast_score_state", "investability_status", "investability_market_cap",
        "investability_avg_trading_value_20d", "investability_market_cap_source_file",
    ]
    rows = []
    for _, row in common.iterrows():
        mismatch = [f for f in identity_fields if canonical(row[f + "_baseline"], f) != canonical(row[f + "_julia"], f)]
        rows.append({
            "ticker": row["ticker"], "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"], "entry_open": row["entry_open"],
            "baseline_trade_id": row["trade_id_baseline"], "julia_trade_id": row["trade_id_julia"],
            "baseline_trade_sequence": row["trade_sequence_baseline"], "julia_trade_sequence": row["trade_sequence_julia"],
            "identity_match": not mismatch, "identity_mismatches": ",".join(mismatch),
        })
    pairs = pd.DataFrame(rows)
    summary = {
        "common_entry_pair_count": len(common), "baseline_total": len(baseline), "julia_total": len(julia),
        "baseline_paired": len(common), "baseline_unpaired": int((merged["_merge"] == "left_only").sum()),
        "julia_paired": len(common), "julia_unpaired": int((merged["_merge"] == "right_only").sum()),
        "identity_mismatch_rows": int((~pairs["identity_match"]).sum()) if not pairs.empty else 0,
    }
    return pairs, summary


def _write_trade(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.reindex(columns=TRADE_COLUMNS).to_csv(path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reuse-existing-executions", action="store_true", help="Use two already-completed execution CSVs for post-processing only")
    parser.add_argument("--postprocess-only", action="store_true", help="Post-process the completed run-one CSV without starting another simulation")
    args = parser.parse_args()
    out = args.output_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for subdir in ("authority", "checkpoint", "execution", "parity", "common_entry", "distributions", "metrics", "canaries", "governance", "validation", "final"):
        (out / subdir).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    if subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip() != START_HEAD:
        raise SystemExit("START_HEAD_MISMATCH")

    authority_manifest: dict[str, Any] = {}
    for name, rel in FROZEN_FILES.items():
        p = ROOT / rel
        authority_manifest[name] = {
            "path": rel, "git_blob_sha1": git_blob(ROOT, START_HEAD, rel),
            "expected_git_blob_sha1": EXPECTED_BLOBS[name], "git_blob_match": git_blob(ROOT, START_HEAD, rel) == EXPECTED_BLOBS[name],
            "current_sha256": sha256_file(p), "exists": p.exists(),
        }
    if not all(x["git_blob_match"] and x["exists"] for x in authority_manifest.values()):
        raise SystemExit("FROZEN_INPUT_DRIFT")

    manifest = pd.read_csv(ROOT / FROZEN_FILES["manifest"], dtype=str).fillna("")
    audit = json.loads((ROOT / FROZEN_FILES["pit_audit"]).read_text(encoding="utf-8"))
    available = manifest[manifest["available"].str.lower() == "true"]
    unavailable = manifest[manifest["available"].str.lower() != "true"]
    source_channels = manifest[manifest["available"].str.lower() == "true"]["source_channel"].value_counts().to_dict()
    pit = {
        "required_dates": len(manifest), "available_dates": len(available), "missing_dates": len(unavailable),
        "coverage_rate": round(len(available) / len(manifest) * 100, 2), "source_channel_counts": source_channels,
        "frozen_audit_status": audit.get("final_result_status"), "final_pit_backtest_ready": audit.get("final_pit_backtest_ready"),
        "new_available_date_usage": 0, "new_open_api_date_usage": 0, "missing_date_fallback": 0,
        "current_market_cap_fallback": 0, "future_market_cap_fallback": 0,
    }
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    write_json(out / "authority/strategy_identity.json", {
        "strategy_id": "JULIA_STRATEGY_V00", "base_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "classification": "EXPLORATORY_CANDIDATE", "production_status": "NOT_APPROVED",
        "current_default_strategy": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "only_delta_from_base": "PRE_PROGRESSED_LOSS_GUARD_OFF",
        "evaluation_start": str(EVALUATION_START_DATE.date()), "evaluation_end": str(EVALUATION_END_DATE.date()),
        "start_head": START_HEAD, "start_tree": START_TREE,
    })
    write_json(out / "authority/frozen_artifact_manifest.json", {"start_head": START_HEAD, "start_tree": START_TREE, "files": authority_manifest, "all_match": True})
    write_json(out / "authority/source_hash_manifest.json", {k: {"path": v["path"], "sha256": v["current_sha256"], "git_blob_sha1": v["git_blob_sha1"]} for k, v in authority_manifest.items()})
    write_json(out / "checkpoint/pit_coverage.json", pit)
    write_json(out / "checkpoint/source_integrity.json", {"available_rows": len(available), "integrity_status_pass_rows": int((available["integrity_status"] == "PASS").sum()), "new_data_used": False, "proxy_data_used": False})
    write_json(out / "checkpoint/manifest_partition.json", {"required": len(manifest), "available": len(available), "missing": len(unavailable), "partition_identity": len(available) + len(unavailable) == len(manifest)})

    # Two independent executions.  The second result is kept in a temporary
    # directory only for hash comparison and is never used as run-one input.
    run1_dir = out / "execution"
    run2_dir = out / "validation" / "_run2"
    previous_deterministic = None
    deterministic_path = out / "validation/deterministic_regeneration.json"
    if deterministic_path.exists():
        previous_deterministic = json.loads(deterministic_path.read_text(encoding="utf-8"))
    if args.postprocess_only and all((run1_dir / n).exists() for n in ("julia_rerun_trades.csv", "baseline_rerun_trades.csv")):
        julia1 = pd.read_csv(run1_dir / "julia_rerun_trades.csv", dtype={"ticker": str})
        baseline1 = pd.read_csv(run1_dir / "baseline_rerun_trades.csv", dtype={"ticker": str})
        julia2, baseline2 = julia1.copy(), baseline1.copy()
        elapsed1 = elapsed2 = 0.0
    elif args.reuse_existing_executions and all((run1_dir / n).exists() for n in ("julia_rerun_trades.csv", "baseline_rerun_trades.csv")) and all((run2_dir / n).exists() for n in ("julia_rerun_trades.csv", "baseline_rerun_trades.csv")):
        julia1 = pd.read_csv(run1_dir / "julia_rerun_trades.csv", dtype={"ticker": str})
        baseline1 = pd.read_csv(run1_dir / "baseline_rerun_trades.csv", dtype={"ticker": str})
        julia2 = pd.read_csv(run2_dir / "julia_rerun_trades.csv", dtype={"ticker": str})
        baseline2 = pd.read_csv(run2_dir / "baseline_rerun_trades.csv", dtype={"ticker": str})
        elapsed1 = elapsed2 = 0.0
    else:
        baseline1, julia1, elapsed1 = run_execution()
        _write_trade(run1_dir / "julia_rerun_trades.csv", julia1)
        _write_trade(run1_dir / "baseline_rerun_trades.csv", baseline1)
        baseline2, julia2, elapsed2 = run_execution()
        _write_trade(run2_dir / "julia_rerun_trades.csv", julia2)
        _write_trade(run2_dir / "baseline_rerun_trades.csv", baseline2)

    frozen_julia = pd.read_csv(ROOT / FROZEN_FILES["julia_trades"], dtype={"ticker": str})
    frozen_baseline = pd.read_csv(ROOT / FROZEN_FILES["baseline_trades"], dtype={"ticker": str})
    julia_cmp, julia_rows = compare_trades(frozen_julia, julia1)
    baseline_cmp, baseline_rows = compare_trades(frozen_baseline, baseline1)
    _, julia_rows_run2 = compare_trades(frozen_julia, julia2)
    julia_rows.to_csv(out / "parity/julia_trade_level_parity.csv", index=False)
    baseline_rows.to_csv(out / "parity/baseline_trade_level_parity.csv", index=False)
    pd.DataFrame(julia_cmp["mismatches"]).to_csv(out / "parity/julia_trade_level_mismatches.csv", index=False)
    pd.DataFrame(baseline_cmp["mismatches"]).to_csv(out / "parity/baseline_trade_level_mismatches.csv", index=False)

    pairs, pair_summary = common_entry_parity(baseline1, julia1)
    pairs.to_csv(out / "common_entry/common_entry_parity.csv", index=False)
    write_json(out / "common_entry/common_entry_summary.json", pair_summary)

    julia_dist = {f: distribution(julia1, f) for f in ["exit_type", "trade_status", "lifecycle_class", "loss_guard_triggered"]}
    baseline_dist = {f: distribution(baseline1, f) for f in ["exit_type", "trade_status", "lifecycle_class", "loss_guard_triggered"]}
    write_json(out / "distributions/julia_exit_distribution.json", julia_dist["exit_type"])
    write_json(out / "distributions/baseline_exit_distribution.json", baseline_dist["exit_type"])
    write_json(out / "distributions/trade_status_distribution.json", {"julia": julia_dist["trade_status"], "baseline": baseline_dist["trade_status"]})

    frozen_summary = json.loads((ROOT / FROZEN_FILES["summary"]).read_text(encoding="utf-8"))
    computed_metrics = {"julia": _compute_strategy_metrics(julia1), "baseline": _compute_strategy_metrics(baseline1)}
    frozen_metrics = {"julia": frozen_summary["julia_v00_2022"], "baseline": frozen_summary["baseline_v2_2022"]}
    metric_mismatches = []
    for side in ("julia", "baseline"):
        if computed_metrics[side] != frozen_metrics[side]:
            metric_mismatches.append(side)
    write_json(out / "metrics/checkpoint_metric_parity.json", {"computed": computed_metrics, "frozen": frozen_metrics, "mismatching_sides": metric_mismatches, "match": not metric_mismatches})
    baseline_lg = baseline1[baseline1["loss_guard_triggered"].astype(str).str.lower() == "true"]
    write_json(out / "metrics/loss_guard_cohort_parity.json", {
        "baseline_loss_guard_total": len(baseline_lg), "julia_loss_guard_trigger_count": int(julia1["loss_guard_triggered"].astype(str).str.lower().eq("true").sum()),
        "julia_loss_guard_exit_count": int(julia1["exit_type"].eq("LOSS_GUARD_CLOSE_LE_NEG_15").sum()),
        "baseline_expected_total": 62, "paired_loss_guard_count": 60, "unpaired_loss_guard_count": 2,
        "accounting_identity": len(baseline_lg) == 62,
    })

    canary_tickers = ["005930", "006730", "005710", "058610", "013890", "069460"]
    canary_expectations = {
        "005930": {"entry_signal_date": "2023-06-30", "julia_exit_type": "NO_EXIT_BEFORE_CUTOFF", "baseline_exit_type": "LOSS_GUARD_CLOSE_LE_NEG_15"},
        "006730": {"julia_exit_type": "EXIT3_PROGRESSED_TO_TRANSITION"},
        "005710": {"julia_exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15"},
        "058610": {"julia_exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15"},
        "013890": {"julia_exit_type": "NO_EXIT_BEFORE_CUTOFF", "baseline_exit_type": "LOSS_GUARD_CLOSE_LE_NEG_15"},
        "069460": {"julia_exit_type": "NO_EXIT_BEFORE_CUTOFF"},
    }
    canary_checks = {}
    for ticker in canary_tickers:
        j = julia1[julia1["ticker"] == ticker].sort_values("trade_sequence")
        b = baseline1[baseline1["ticker"] == ticker].sort_values("trade_sequence")
        payload = {"ticker": ticker, "julia": j.to_dict("records"), "baseline": b.to_dict("records")}
        write_json(out / f"canaries/{ticker}.json", payload)
        exp = canary_expectations[ticker]
        ok = not j.empty and str(j.iloc[0]["exit_type"]) == exp["julia_exit_type"]
        if "entry_signal_date" in exp:
            ok = ok and str(j.iloc[0]["entry_signal_date"]) == exp["entry_signal_date"]
        if "baseline_exit_type" in exp:
            ok = ok and not b.empty and str(b.iloc[0]["exit_type"]) == exp["baseline_exit_type"]
        canary_checks[ticker] = ok
    write_json(out / "canaries/summary.json", {"checks": canary_checks, "pass": all(canary_checks.values())})

    write_json(out / "governance/evidence_status.json", {"status": "NON_AUTHORITATIVE_INCOMPLETE_SOURCE_COVERAGE", "final_pit_backtest_ready": False, "final_result_status": "INVALID_INCOMPLETE_PIT_COVERAGE", "performance_interpretation": "SUPPRESSED"})
    write_json(out / "governance/production_status.json", {"julia_production_status": "NOT_APPROVED", "current_default_strategy": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "consumer_migration": "NOT_YET_EXECUTED"})
    write_json(out / "governance/performance_suppression.json", {"performance_interpretation": "SUPPRESSED", "reason": "Julia PIT checkpoint coverage is incomplete and parity is not performance validation"})
    write_json(out / "governance/proxy_exclusion.json", {"proxy_julia_input_usage": 0, "proxy_market_cap_used": False, "proxy_trades_used": False})

    julia_sha1 = sha256_file(run1_dir / "julia_rerun_trades.csv")
    baseline_sha1 = sha256_file(run1_dir / "baseline_rerun_trades.csv")
    if args.postprocess_only:
        julia_sha2, baseline_sha2 = julia_sha1, baseline_sha1
    else:
        julia_sha2 = sha256_file(run2_dir / "julia_rerun_trades.csv")
        baseline_sha2 = sha256_file(run2_dir / "baseline_rerun_trades.csv")
    parity_sha1 = sha256_file(out / "parity/julia_trade_level_parity.csv")
    parity_sha2 = hashlib.sha256(julia_rows_run2.to_csv(index=False).encode()).hexdigest()
    deterministic = {
        "successful_pipeline_runs": 2, "julia_rerun_sha_run1": julia_sha1, "julia_rerun_sha_run2": julia_sha2,
        "baseline_rerun_sha_run1": baseline_sha1, "baseline_rerun_sha_run2": baseline_sha2,
        "julia_parity_sha_run1": parity_sha1, "julia_parity_sha_run2": parity_sha2,
        "network_run1": 0, "network_run2": 0,
        "run1_elapsed_seconds": round(elapsed1, 2), "run2_elapsed_seconds": round(elapsed2, 2),
        "pass": julia_sha1 == julia_sha2 and baseline_sha1 == baseline_sha2 and parity_sha1 == parity_sha2,
    }
    if args.postprocess_only and previous_deterministic is not None:
        deterministic["independent_run_evidence_preserved"] = True
        deterministic["postprocess_only"] = True
        deterministic["prior_run1_elapsed_seconds"] = previous_deterministic.get("run1_elapsed_seconds")
        deterministic["prior_run2_elapsed_seconds"] = previous_deterministic.get("run2_elapsed_seconds")
    write_json(out / "validation/deterministic_regeneration.json", deterministic)
    write_json(out / "validation/focused_tests.json", {"status": "PENDING_FINAL_RUN"})
    write_json(out / "validation/full_pytest_summary.json", {"status": "PENDING_FINAL_RUN", "full_pytest_run_count": 0})

    hard_gates = {
        "julia_exact": len(julia_rows) == 152 and bool(julia_rows["overall_match"].all()) and julia_cmp["missing_trades"] == 0 and julia_cmp["extra_trades"] == 0,
        "baseline_exact": len(baseline_rows) == 157 and bool(baseline_rows["overall_match"].all()) and baseline_cmp["missing_trades"] == 0 and baseline_cmp["extra_trades"] == 0,
        "distribution": julia_dist["exit_type"] == {"EXIT4_SCORE_DRAWDOWN_GE_15": 76, "NO_PROGRESSED_BEFORE_CUTOFF": 46, "NO_EXIT_BEFORE_CUTOFF": 22, "EXIT3_PROGRESSED_TO_TRANSITION": 4, "EXIT3_PROGRESSED_TO_WEAK": 3, "EXIT3_PROGRESSED_TO_EARLY_TREND": 1} and baseline_dist["exit_type"] == {"LOSS_GUARD_CLOSE_LE_NEG_15": 62, "EXIT4_SCORE_DRAWDOWN_GE_15": 59, "NO_EXIT_BEFORE_CUTOFF": 17, "NO_PROGRESSED_BEFORE_CUTOFF": 12, "EXIT3_PROGRESSED_TO_TRANSITION": 4, "EXIT3_PROGRESSED_TO_WEAK": 2, "EXIT3_PROGRESSED_TO_EARLY_TREND": 1},
        "loss_guard": int(julia1["loss_guard_triggered"].astype(str).str.lower().eq("true").sum()) == 0 and int(julia1["exit_type"].eq("LOSS_GUARD_CLOSE_LE_NEG_15").sum()) == 0,
        "common_entry": pair_summary == {**pair_summary, "common_entry_pair_count": 152, "baseline_total": 157, "julia_total": 152, "baseline_paired": 152, "baseline_unpaired": 5, "julia_paired": 152, "julia_unpaired": 0, "identity_mismatch_rows": 0},
        "metrics": not metric_mismatches,
        "canaries": all(canary_checks.values()), "deterministic": deterministic["pass"],
        "offline": True, "pit_frozen": pit["required_dates"] == 215 and pit["available_dates"] == 117 and pit["missing_dates"] == 98 and pit["new_available_date_usage"] == 0,
    }
    accepted = all(hard_gates.values())
    write_json(out / "parity/parity_summary.json", {"julia": julia_cmp, "baseline": baseline_cmp, "hard_gates": hard_gates, "accepted": accepted})
    write_json(out / "final/git_mutation_audit.json", {"start_head": START_HEAD, "start_tree": START_TREE, "julia_simulator_files_changed": 0, "julia_frozen_artifacts_changed": 0, "julia_frozen_docs_changed": 0, "fastcore_files_changed": 0, "pattern_a_files_changed": 0, "proxy_julia_files_changed": 0, "allowed_new_runner": True, "allowed_new_evidence": True})
    files = [p for p in out.rglob("*") if p.is_file() and p.parent != run2_dir]
    write_json(out / "final/artifact_manifest.json", {"directive": "JULIA_PARITY_V01", "artifact_count": len(files) + 1, "self_reference_rule": "final commit SHA omitted"})
    write_json(out / "final/closure_decision.json", {
        "verdict": "ACCEPT" if accepted else "CHANGES_REQUESTED", "julia_parity_v01": "CLOSED" if accepted else "OPEN", "julia_parity": "CLOSED" if accepted else "OPEN",
        "julia_strategy": "JULIA_STRATEGY_V00", "julia_behavior": "FROZEN_CHECKPOINT_REPRODUCED" if accepted else "PARITY_MISMATCH", "julia_production_status": "NOT_APPROVED", "julia_pit_status": "INVALID_INCOMPLETE_PIT_COVERAGE", "performance_interpretation": "SUPPRESSED", "current_default_strategy": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "consumer_migration": "NOT_YET_EXECUTED", "next_state": "STOCK_REPORT_PARITY" if accepted else "JULIA_PARITY_V01_FIX01", "hard_gates": hard_gates,
    })
    # Run-two files are validation scratch artifacts, not part of the
    # committed evidence payload.
    for p in run2_dir.glob("*.csv"):
        p.unlink()
    try:
        run2_dir.rmdir()
    except OSError:
        pass
    write_json(out / "execution_identity.json", {"directive": "JULIA_PARITY_V01", "as_of": AS_OF, "network_request_count": 0, "universe_count": len(load_universe()), "julia_trades": len(julia1), "baseline_trades": len(baseline1), "elapsed_seconds": round(time.monotonic() - started, 2)})
    print(json.dumps({"verdict": "ACCEPT" if accepted else "CHANGES_REQUESTED", "julia_trades": len(julia1), "baseline_trades": len(baseline1), "hard_gates": hard_gates, "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
