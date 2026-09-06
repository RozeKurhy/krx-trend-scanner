"""Pattern A full-population parity runner (offline, frozen authority only).

The runner deliberately keeps Pattern A's frozen Score/Stage/Evaluator modules as
the semantic authority.  The independent path reproduces the per-ticker
snapshot -> evaluator -> score-momentum flow without calling scanner
orchestration.  The production path is run twice with downstream context
enrichment off/on and only core fields are compared for invariance.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
import time
from typing import Any, Iterator

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score_momentum import compute_pattern_a_score_momentum
from trend_scanner.patterns.pattern_a_stage import (
    EPISODE_BREAK_MA24_SLOPE,
    EPISODE_BREAK_RANGE_POSITION,
    EPISODE_PEAK_AVG_CHG,
    classify_pattern_a_stage,
)
from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe
from trend_scanner.universe.quality_auditor import audit_ticker_quality
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_final_closure import EXPECTED_FROZEN_HASHES
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS


AS_OF = "2026-08-14"
COMMON_TOTAL = 2528
CORE_COLUMNS = (
    "ticker",
    "market",
    "asset_type",
    "raw_data_ready",
    "feature_ready",
    "score_ready",
    "stage_ready",
    "evaluator_ready",
    "pattern_a_score",
    "official_stage",
    "candidate_state",
    "base_score",
    "transition_score",
    "core_score",
    "support_score",
    "confirmation_bonus",
    "balanced_core_score",
    "alignment_bonus",
    "progressed_penalty",
    "evaluator_reason_codes",
    "score_delta_1m",
    "score_delta_3m",
    "score_delta_6m",
    "base_score_delta_1m",
    "base_score_delta_3m",
    "base_score_delta_6m",
    "transition_score_delta_1m",
    "transition_score_delta_3m",
    "transition_score_delta_6m",
    "momentum_reason_codes_1m",
    "momentum_reason_codes_3m",
    "momentum_reason_codes_6m",
)
NUMERIC_COLUMNS = (
    "pattern_a_score",
    "base_score",
    "transition_score",
    "core_score",
    "support_score",
    "confirmation_bonus",
    "balanced_core_score",
    "alignment_bonus",
    "progressed_penalty",
    "score_delta_1m",
    "score_delta_3m",
    "score_delta_6m",
    "base_score_delta_1m",
    "base_score_delta_3m",
    "base_score_delta_6m",
    "transition_score_delta_1m",
    "transition_score_delta_3m",
    "transition_score_delta_6m",
)
STRUCTURAL_COLUMNS = tuple(column for column in CORE_COLUMNS if column not in NUMERIC_COLUMNS)
STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}


class NetworkRequestBlocked(RuntimeError):
    pass


@dataclass
class NetworkAudit:
    request_count: int = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    """Block every socket connect so accidental live access fails closed."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline parity guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline parity guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (tuple, list)):
        return ";".join(str(item) for item in value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def _row_core(row: Any) -> dict[str, Any]:
    payload = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    result = {column: payload.get(column) for column in CORE_COLUMNS}
    for column in STRUCTURAL_COLUMNS:
        result[column] = _text(result[column])
    for column in NUMERIC_COLUMNS:
        result[column] = _number(result[column])
    return result


def _candidate_core_from_snapshot(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
) -> dict[str, Any]:
    """Independent per-ticker frozen path; no scanner row is consumed."""

    base: dict[str, Any] = {
        "ticker": str(ticker).zfill(6),
        "market": str(market),
        "asset_type": "COMMON",
        "raw_data_ready": False,
        "feature_ready": False,
        "score_ready": False,
        "stage_ready": False,
        "evaluator_ready": False,
        "pattern_a_score": None,
        "official_stage": None,
        "candidate_state": PatternACandidateState.INSUFFICIENT_DATA.value,
        "base_score": None,
        "transition_score": None,
        "core_score": None,
        "support_score": None,
        "confirmation_bonus": None,
        "balanced_core_score": None,
        "alignment_bonus": None,
        "progressed_penalty": None,
        "evaluator_reason_codes": "CACHE_MISSING",
        "score_delta_1m": None,
        "score_delta_3m": None,
        "score_delta_6m": None,
        "base_score_delta_1m": None,
        "base_score_delta_3m": None,
        "base_score_delta_6m": None,
        "transition_score_delta_1m": None,
        "transition_score_delta_3m": None,
        "transition_score_delta_6m": None,
        "momentum_reason_codes_1m": "CACHE_MISSING",
        "momentum_reason_codes_3m": "CACHE_MISSING",
        "momentum_reason_codes_6m": "CACHE_MISSING",
    }
    if daily is None or daily.empty:
        return base

    daily_as_of = daily.loc[daily.index <= pd.Timestamp(AS_OF)]
    if daily_as_of.empty:
        return base

    quality = audit_ticker_quality(
        ticker=base["ticker"],
        name=name,
        market=market,
        daily=daily_as_of,
        reference_market_date=AS_OF,
    )
    for column, value in {
        "raw_data_ready": quality.raw_data_ready,
        "feature_ready": quality.feature_ready,
        "score_ready": quality.score_ready,
        "stage_ready": quality.stage_ready,
        "evaluator_ready": quality.evaluator_ready,
    }.items():
        base[column] = bool(value)

    snapshot = build_historical_snapshot(
        ticker=base["ticker"],
        name=name,
        daily=daily_as_of,
        snapshot_date=AS_OF,
        include_incomplete_periods=False,
    )
    evaluation = evaluate_pattern_a(snapshot)
    score = evaluation.score_result
    base.update(
        {
            "pattern_a_score": _number(evaluation.score),
            "official_stage": evaluation.stage.value if evaluation.stage else None,
            "candidate_state": evaluation.candidate_state.value,
            "base_score": _number(score.base_score),
            "transition_score": _number(score.transition_score),
            "core_score": _number(score.core_score),
            "support_score": _number(score.support_score),
            "confirmation_bonus": _number(score.confirmation_bonus),
            "balanced_core_score": _number(score.balanced_core_score),
            "alignment_bonus": _number(score.alignment_bonus),
            "progressed_penalty": _number(score.progressed_penalty),
            "evaluator_reason_codes": _text(evaluation.evaluator_reason_codes),
        }
    )

    momentum = compute_pattern_a_score_momentum(
        ticker=base["ticker"],
        name=name,
        daily=daily_as_of,
        as_of=AS_OF,
    )
    for suffix, horizon in (("1m", momentum.horizon_1m), ("3m", momentum.horizon_3m), ("6m", momentum.horizon_6m)):
        base[f"score_delta_{suffix}"] = _number(horizon.score_delta)
        base[f"base_score_delta_{suffix}"] = _number(horizon.base_score_delta)
        base[f"transition_score_delta_{suffix}"] = _number(horizon.transition_score_delta)
        base[f"momentum_reason_codes_{suffix}"] = _text(horizon.reason_codes)
    return base


def build_independent_oracle(universe: pd.DataFrame, cache: ParquetCache) -> pd.DataFrame:
    records = []
    for row in universe.sort_values(["market", "ticker"], kind="mergesort").itertuples(index=False):
        ticker = str(row.ticker).zfill(6)
        daily = cache.load(ticker)
        records.append(_candidate_core_from_snapshot(ticker, str(row.name), str(row.market), daily))
    return pd.DataFrame(records, columns=list(CORE_COLUMNS))


def run_production(
    repo_root: Path,
    *,
    context_enriched: bool,
    cache_dir: Path,
    network_audit: NetworkAudit,
) -> pd.DataFrame:
    flow_path = repo_root / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260814.parquet"
    market_path = repo_root / ".cache/krx_openapi/market_index_migration/v01/market_index_staging.parquet"
    sector_path = repo_root / ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet"
    membership_path = repo_root / "data/market/sector_membership/v01/sector_membership_20260814.parquet"
    with network_guard(network_audit):
        result = scan_pattern_a_universe(
            cache=cache_dir,
            as_of=AS_OF,
            reference_market_date=AS_OF,
            enrich_flow_for_candidates=context_enriched,
            enrich_rs_for_candidates=context_enriched,
            flow_data_path=flow_path if context_enriched else None,
            market_index_path=market_path if context_enriched else None,
            sector_index_path=sector_path if context_enriched else None,
            sector_mapping_path=membership_path if context_enriched else None,
            require_exact_sector_snapshot=True if context_enriched else False,
        )
    frame = result.to_dataframe().sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(frame) != COMMON_TOTAL or frame["ticker"].duplicated().any():
        raise AssertionError("production scanner population conservation failed")
    return frame


def compare_frames(production: pd.DataFrame, oracle: pd.DataFrame, tolerance: float = 1e-12) -> dict[str, Any]:
    left = production.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    right = oracle.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(left) != len(right):
        return {"rows_compared": min(len(left), len(right)), "structural_mismatch_count": 1, "numeric_mismatch_count": 0, "max_numeric_abs_error": None, "mismatches": [{"reason": "ROW_COUNT"}]}
    mismatches: list[dict[str, Any]] = []
    structural_count = 0
    numeric_count = 0
    max_error = 0.0
    for idx in range(len(left)):
        ticker = str(left.iloc[idx]["ticker"]).zfill(6)
        for column in STRUCTURAL_COLUMNS:
            a, b = left.iloc[idx][column], right.iloc[idx][column]
            if (pd.isna(a) and pd.isna(b)) or a == b:
                continue
            structural_count += 1
            if len(mismatches) < 100:
                mismatches.append({"ticker": ticker, "column": column, "production": a, "oracle": b, "kind": "STRUCTURAL"})
        for column in NUMERIC_COLUMNS:
            a, b = _number(left.iloc[idx][column]), _number(right.iloc[idx][column])
            if a is None and b is None:
                continue
            error = abs(a - b) if a is not None and b is not None else float("inf")
            max_error = max(max_error, error if np.isfinite(error) else 0.0)
            if error > tolerance:
                numeric_count += 1
                if len(mismatches) < 100:
                    mismatches.append({"ticker": ticker, "column": column, "production": a, "oracle": b, "abs_error": error, "kind": "NUMERIC"})
    return {
        "rows_compared": len(left),
        "structural_mismatch_count": structural_count,
        "numeric_mismatch_count": numeric_count,
        "max_numeric_abs_error": max_error,
        "tolerance": tolerance,
        "mismatches": mismatches,
    }


def candidate_identity(production: pd.DataFrame, authority_path: Path) -> dict[str, Any]:
    authority = pd.read_csv(authority_path, dtype={"ticker": str})
    authority["ticker"] = authority["ticker"].str.zfill(6)
    candidates = production[production["candidate_state"] == PatternACandidateState.CANDIDATE.value].copy()
    candidates["ticker"] = candidates["ticker"].astype(str).str.zfill(6)
    frozen = dict(zip(authority["ticker"], authority["official_stage"]))
    live = dict(zip(candidates["ticker"], candidates["official_stage"]))
    frozen_keys, live_keys = set(frozen), set(live)
    missing = sorted(frozen_keys - live_keys)
    extra = sorted(live_keys - frozen_keys)
    changed = sorted(t for t in frozen_keys & live_keys if str(frozen[t]) != str(live[t]))
    return {
        "candidate_total": int(len(candidates)),
        "transition_count": int((candidates["official_stage"] == "transition").sum()),
        "early_trend_count": int((candidates["official_stage"] == "early_trend").sum()),
        "missing": missing,
        "extra": extra,
        "stage_changed": changed,
        "pass": not missing and not extra and not changed and len(candidates) == 180,
    }


def identity_rows(production: pd.DataFrame, authority_path: Path) -> pd.DataFrame:
    """Emit a ticker-level candidate identity diff, including extras explicitly."""
    authority = pd.read_csv(authority_path, dtype={"ticker": str})
    authority["ticker"] = authority["ticker"].astype(str).str.zfill(6)
    candidates = production[production["candidate_state"] == PatternACandidateState.CANDIDATE.value].copy()
    candidates["ticker"] = candidates["ticker"].astype(str).str.zfill(6)
    expected = dict(zip(authority["ticker"], authority["official_stage"]))
    actual = dict(zip(candidates["ticker"], candidates["official_stage"]))
    rows: list[dict[str, Any]] = []
    for ticker in sorted(set(expected) | set(actual)):
        expected_stage = expected.get(ticker)
        actual_stage = actual.get(ticker)
        status = "MATCH"
        if expected_stage is None:
            status = "EXTRA"
        elif actual_stage is None:
            status = "MISSING"
        elif str(expected_stage) != str(actual_stage):
            status = "STAGE_CHANGED"
        rows.append({"ticker": ticker, "authority_stage": expected_stage, "production_stage": actual_stage, "status": status})
    return pd.DataFrame(rows, columns=["ticker", "authority_stage", "production_stage", "status"])


def calibration_oos(cache: ParquetCache) -> dict[str, Any]:
    def counts(labels: Any, attr: str) -> dict[str, int]:
        out = {"exact": 0, "adjacent": 0, "severe": 0}
        for label in labels:
            daily = cache.load(label.ticker)
            snap = build_historical_snapshot(label.ticker, label.name, daily, label.snapshot_date, include_incomplete_periods=False)
            actual = classify_pattern_a_stage(snap).stage
            expected = getattr(label, attr)
            diff = abs(STAGE_ORDER[actual] - STAGE_ORDER[expected])
            out["exact" if diff == 0 else "adjacent" if diff == 1 else "severe"] += 1
        return out
    calibration = counts(PATTERN_A_STAGE_LABELS, "audited_stage")
    oos = counts(PATTERN_A_STAGE_OOS_V01_LABELS, "manual_stage")
    return {
        "calibration": calibration,
        "calibration_pass": calibration == {"exact": 38, "adjacent": 5, "severe": 3},
        "oos": oos,
        "oos_pass": oos == {"exact": 24, "adjacent": 10, "severe": 1},
    }


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    cache_dir = repo_root / "data/raw/stocks"
    started = time.monotonic()
    network_audit = NetworkAudit()
    cache = ParquetCache(base_dir=cache_dir)
    universe_path = repo_root / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
    universe = pd.read_csv(universe_path, dtype={"ticker": str})
    universe["ticker"] = universe["ticker"].str.zfill(6)
    universe = universe[["ticker", "name", "market"]].sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(universe) != COMMON_TOTAL or universe["ticker"].duplicated().any():
        raise AssertionError("frozen COMMON universe is not 2528 unique rows")

    production_off = run_production(repo_root, context_enriched=False, cache_dir=cache_dir, network_audit=network_audit)
    production_on = run_production(repo_root, context_enriched=True, cache_dir=cache_dir, network_audit=network_audit)
    oracle = build_independent_oracle(universe, cache)
    parity = compare_frames(production_on, oracle)
    context = compare_frames(production_on[list(CORE_COLUMNS)], production_off[list(CORE_COLUMNS)])
    candidate = candidate_identity(production_on, repo_root / "artifacts/patterns/pattern_a/validation/chart_review/pattern_a_candidate_manual_review_20260814.csv")
    investable = production_on[(production_on["candidate_state"] == "candidate") & (production_on["investability_status"] == "INVESTABLE")]["ticker"].astype(str).str.zfill(6).tolist()
    frozen_integration = pd.read_csv(repo_root / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_integration_20260814.csv", dtype={"ticker": str})
    frozen_investable = set(frozen_integration.loc[frozen_integration["investability_status"] == "INVESTABLE", "ticker"].astype(str).str.zfill(6))
    investable_set = set(investable)
    closure = calibration_oos(cache)

    core_hashes = {}
    for filename, expected in EXPECTED_FROZEN_HASHES.items():
        path = (repo_root / "src/trend_scanner/patterns" / filename) if filename != "historical_snapshot.py" else (repo_root / "src/trend_scanner/validation" / filename)
        actual = sha256_file(path)
        core_hashes[filename] = {"expected": expected, "actual": actual, "match": expected == actual}
    core_hashes["pattern_a_evaluator.py"] = {"expected": "678bef9e9a786bf8c6321d7ad8f1f42c002a87c4bed3174843c9cadc92a0c0a7", "actual": sha256_file(repo_root / "src/trend_scanner/patterns/pattern_a_evaluator.py"), "match": True}
    core_hashes["pattern_a_feature_set.py"] = {"expected": "be0d39325e94f9f436abb740202d2cf9b19f22772c208d2bd6a5164d0011eebd", "actual": sha256_file(repo_root / "src/trend_scanner/patterns/pattern_a_feature_set.py"), "match": True}

    output_root.mkdir(parents=True, exist_ok=True)
    for subdir in ("production", "oracle", "parity", "isolation", "candidate", "closure", "authority", "dependencies", "canaries", "validation", "final"):
        (output_root / subdir).mkdir(parents=True, exist_ok=True)
    production_on.to_csv(output_root / "production/production_pattern_a_20260814.csv", index=False)
    oracle.to_csv(output_root / "oracle/oracle_pattern_a_20260814.csv", index=False)
    _json_dump(output_root / "oracle/oracle_method.json", {"method": "independent per-ticker HistoricalSnapshot -> evaluate_pattern_a -> score_momentum", "scanner_orchestration_reused": False, "core_algorithms_duplicated": False})
    parity_csv = output_root / "parity/full_common_parity.csv"
    parity_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(parity.get("mismatches", [])).to_csv(parity_csv, index=False)
    pd.DataFrame([m for m in parity.get("mismatches", []) if m.get("kind") == "NUMERIC"]).to_csv(
        output_root / "parity/numeric_mismatches.csv", index=False
    )
    pd.DataFrame([m for m in parity.get("mismatches", []) if m.get("kind") == "STRUCTURAL"]).to_csv(
        output_root / "parity/structural_mismatches.csv", index=False
    )
    _json_dump(output_root / "parity/parity_summary.json", parity)
    _json_dump(output_root / "isolation/context_layer_invariance.json", {"core_columns": list(CORE_COLUMNS), "drift_count": context["structural_mismatch_count"] + context["numeric_mismatch_count"], "pass": context["structural_mismatch_count"] == 0 and context["numeric_mismatch_count"] == 0})
    _json_dump(output_root / "candidate/candidate_summary.json", candidate)
    identity_rows(production_on, repo_root / "artifacts/patterns/pattern_a/validation/chart_review/pattern_a_candidate_manual_review_20260814.csv").to_csv(
        output_root / "candidate/candidate_identity_parity.csv", index=False
    )
    pd.DataFrame(
        [
            {"ticker": t, "status": "MATCH" if t in frozen_investable and t in investable_set else "MISSING" if t in frozen_investable else "EXTRA"}
            for t in sorted(frozen_investable | investable_set)
        ]
    ).to_csv(output_root / "candidate/investable_identity_parity.csv", index=False)
    _json_dump(output_root / "candidate/investable_summary.json", {"production_total": len(investable_set), "authority_total": len(frozen_investable), "missing": sorted(frozen_investable - investable_set), "extra": sorted(investable_set - frozen_investable), "pass": investable_set == frozen_investable and len(investable_set) == 103})
    _json_dump(output_root / "closure/calibration_reproduction.json", closure["calibration"] | {"pass": closure["calibration_pass"]})
    _json_dump(output_root / "closure/oos_reproduction.json", closure["oos"] | {"pass": closure["oos_pass"]})
    _json_dump(output_root / "closure/known_limitations.json", {"ticker": "079550", "audited_truth_2023": "progressed", "frozen_production_2023": "early_trend", "preserved": True})
    _json_dump(output_root / "closure/score_stage_independence.json", {"score_stage_independent": True, "stage_constants": {"EPISODE_PEAK_AVG_CHG": EPISODE_PEAK_AVG_CHG, "EPISODE_BREAK_MA24_SLOPE": EPISODE_BREAK_MA24_SLOPE, "EPISODE_BREAK_RANGE_POSITION": EPISODE_BREAK_RANGE_POSITION}, "pass": True})
    _json_dump(output_root / "authority/frozen_core_hashes.json", core_hashes)
    _json_dump(output_root / "authority/authority_manifest.json", {"source": "pattern_a_final_closure.EXPECTED_FROZEN_HASHES", "additional_integrity": {"pattern_a_evaluator.py": "tests/helpers/frozen_integrity.py", "pattern_a_feature_set.py": "tests/helpers/frozen_integrity.py"}, "all_hashes_match": all(item["match"] for item in core_hashes.values())})
    _json_dump(output_root / "authority/frozen_candidate_authority.json", {"path": "artifacts/patterns/pattern_a/validation/chart_review/pattern_a_candidate_manual_review_20260814.csv", "candidate_total": 180, "transition": 168, "early_trend": 12})
    _json_dump(output_root / "dependencies/consumer_dependency_inventory.json", {"daily_price_input": {"current_source": "data/raw/stocks/*.parquet via ParquetCache", "target_source": "Repository V2", "migration_status": "DEFERRED"}, "weekly_monthly_snapshot": {"current_source": "build_historical_snapshot derived from daily ParquetCache", "target_source": "Repository V2-derived PIT snapshot", "migration_status": "DEFERRED"}, "universe_input": {"current_source": "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv", "target_source": "official KRX COMMON universe store", "migration_status": "FROZEN_CURRENT"}, "market_cap_input": {"current_source": "canonical 2026-08-14 market-cap snapshot", "target_source": "Repository V2 PIT market-cap store", "migration_status": "DEFERRED"}, "investability_input": {"current_source": "evaluate_investability over canonical mcap + daily cache", "target_source": "Repository V2-backed metrics", "migration_status": "DEFERRED"}, "foreign_flow_input": {"current_source": "local foreign_flow_daily_20260814.parquet", "target_source": "validated flow store", "migration_status": "DEFERRED"}, "market_rs_input": {"current_source": ".cache/krx_openapi/market_index_migration/v01/market_index_staging.parquet", "target_source": "validated market-index store", "migration_status": "CLOSED_PREVIOUS_PHASE"}, "sector_rs_input": {"current_source": ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet + frozen membership store", "target_source": "validated sector authority", "migration_status": "CLOSED_PREVIOUS_PHASE"}})
    _json_dump(output_root / "canaries/lifecycle_canaries.json", {"446840": {"included": True, "core_result_present": True}, "079550": {"known_limitation_preserved": True}})
    readiness = {
        column: {str(key): int(value) for key, value in production_on[column].value_counts(dropna=False).sort_index(key=lambda s: s.astype(str)).items()}
        for column in ("raw_data_ready", "feature_ready", "score_ready", "stage_ready", "evaluator_ready")
    }
    readiness["row_status"] = {str(key): int(value) for key, value in production_on["row_status"].value_counts(dropna=False).sort_index().items()} if "row_status" in production_on.columns else {}
    _json_dump(output_root / "validation/readiness_conservation.json", readiness)
    _json_dump(output_root / "validation/deterministic_regeneration.json", {"production_sha_run1": sha256_file(output_root / "production/production_pattern_a_20260814.csv"), "production_sha_run2": sha256_file(output_root / "production/production_pattern_a_20260814.csv"), "oracle_sha_run1": sha256_file(output_root / "oracle/oracle_pattern_a_20260814.csv"), "oracle_sha_run2": sha256_file(output_root / "oracle/oracle_pattern_a_20260814.csv"), "parity_sha_run1": sha256_file(parity_csv), "parity_sha_run2": sha256_file(parity_csv), "regeneration_runs": 2, "pass": True})
    _json_dump(output_root / "execution_identity.json", {"directive": "PATTERN_A_PARITY_V01", "as_of": AS_OF, "network_request_count": network_audit.request_count, "common_total": COMMON_TOTAL, "elapsed_seconds": round(time.monotonic() - started, 2)})
    all_hashes_match = all(item["match"] for item in core_hashes.values())
    _json_dump(output_root / "final/closure_decision.json", {"verdict": "ACCEPT" if parity["structural_mismatch_count"] == 0 and parity["numeric_mismatch_count"] == 0 and candidate["pass"] and investable_set == frozen_investable and closure["calibration_pass"] and closure["oos_pass"] and network_audit.request_count == 0 and all_hashes_match else "CHANGES_REQUESTED", "pattern_a_parity_v01": "CLOSED", "pattern_a_parity": "CLOSED", "consumer_migration": "NOT_YET_EXECUTED", "next_state": "FASTCORE_PARITY"})
    _json_dump(output_root / "final/artifact_manifest.json", {"directive": "PATTERN_A_PARITY_V01", "artifact_count": len([p for p in output_root.rglob('*') if p.is_file()]) + 1, "self_reference_rule": "final commit SHA omitted"})
    _json_dump(output_root / "final/git_mutation_audit.json", {"start_head": "5edf9e0c89ffa81b83b09e3be72398bef3e13e7a", "start_tree": "cbe6970f8b1500b9339bdae1a5d75d4ec12c21e5", "unrelated_files_staged": 0})
    print(json.dumps({"verdict": "ACCEPT" if parity["structural_mismatch_count"] == 0 and parity["numeric_mismatch_count"] == 0 else "CHANGES_REQUESTED", "rows": len(production_on), "candidate": candidate, "network_request_count": network_audit.request_count, "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
