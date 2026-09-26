#!/usr/bin/env python3
"""Run the approved P1 V02 closure from immutable saved raw artifacts only.

The source P1 run and its raw CSVs are frozen evidence.  This script filters
the approved exact identities into a new evaluation directory, validates the
filtered population, and asks the existing summarizer to recompute aggregates.
It never invokes ticker simulation or writes into the source run directory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import scripts.run_fastcore_neg40_weak_protect_p2_1 as runner  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
    apply_permanent_identity_exclusions,
)


V01_SCOPE = "P1 UNAVAILABLE 12 permanent exclusion V01"
V02_SCOPE = "P1 final exclusion closure V02"
EXPECTED_PREEXISTING = {
    ("010420", "KR7010420008"),
    ("005390", "KR7005390000"),
    ("006390", "KR7006390009"),
    ("031440", "KR7031440001"),
    ("049770", "KR7049770001"),
    ("057050", "KR7057050007"),
    ("138490", "KR7138490008"),
    ("335890", "KR7335890000"),
    ("950110", "KR8392070007"),
    ("069460", "KR7069460004"),
    ("246720", "KR7246720007"),
}
EXPECTED_V01 = {
    ("001140", "KR7001140003"),
    ("009730", "KR7009730003"),
    ("031980", "KR7031980006"),
    ("035290", "KR7035290006"),
    ("036260", "KR7036260008"),
    ("036620", "KR7036620003"),
    ("043710", "KR7043710003"),
    ("044060", "KR7044060002"),
    ("052300", "KR7052300001"),
    ("052400", "KR7052400009"),
    ("068150", "KR7068150002"),
    ("130660", "KR7130660004"),
}
EXPECTED_V02 = {
    ("005950", "KR7005950001"),
    ("002250", "KR7002250009"),
    ("002270", "KR7002270007"),
    ("002550", "KR7002550002"),
    ("003450", "KR7003450004"),
    ("003600", "KR7003600004"),
    ("005190", "KR7005190004"),
    ("008020", "KR7008020000"),
    ("008720", "KR7008720005"),
    ("013450", "KR7013450002"),
    ("016170", "KR7016170003"),
    ("019680", "KR7019680008"),
    ("020760", "KR7020760005"),
    ("031860", "KR7031860000"),
    ("032980", "KR7032980005"),
    ("033630", "KR7033630005"),
    ("033660", "KR7033660002"),
    ("043220", "KR7043220003"),
    ("123100", "KR7123100000"),
    ("130960", "KR7130960008"),
}
RAW_FILENAMES = (
    "control_trades.csv",
    "candidate_trades.csv",
    "paired_trades.csv",
    "p1_matched_trades.csv",
    "p1_soft_events.csv",
)
V02_EXCLUSION_DIRNAME = "raw_only_exclusion_closure_v02"
ALLOWED_FINAL_UNRESOLVED_PAIR_ID = (
    "096300|KR7096300009|KOSPI|2010-01-04|2023-02-01|096300_02"
)


class CheckRequired(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckRequired(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity_pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return {
        (str(ticker).strip().zfill(6), str(isu).strip().upper())
        for ticker, isu in frame[["ticker", "isu_cd"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }


def segment_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item["ticker"]).zfill(6),
        str(item["isu_cd"]).upper(),
        str(item["market"]),
        str(item["effective_from"])[:10],
        str(item["effective_to"])[:10],
    )


def failure_pairs(errors: list[str]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for message in errors:
        ticker = message.split(":", 1)[0].strip().zfill(6)
        pair = message.split(" for ", 1)[-1].split("|")
        require(len(pair) >= 2, f"cannot parse saved worker failure identity: {message}")
        result.add((ticker, pair[1].strip().upper()))
    return result


def build_context(source_manifest: dict[str, Any]) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    calendar = runner.load_rolling_production_market_calendar(ROOT)
    window = runner.resolve_standard_backtest_window("P1", calendar)
    actual_window = tuple(
        value.strftime("%Y-%m-%d")
        for value in (window.effective_start, window.effective_end, window.execution_support)
    )
    require(
        actual_window == ("2014-01-02", "2026-08-31", "2026-09-01"),
        f"P1 window changed: {actual_window}",
    )

    authority_base = runner.load_effective_authority(runner.AUTHORITY_DIR)
    authority, coverage_start, coverage_end = runner._load_p2_2_extended_identity_authority(
        authority_base
    )
    require(
        authority.pit_sha256 == source_manifest.get("effective_pit_sha256"),
        "effective PIT SHA-256 differs from frozen source manifest",
    )

    registered_v01 = {
        identity
        for identity, policy in PERMANENT_IDENTITY_EXCLUSIONS.items()
        if policy.get("approval_scope") == V01_SCOPE
    }
    registered_v02 = {
        identity
        for identity, policy in PERMANENT_IDENTITY_EXCLUSIONS.items()
        if policy.get("approval_scope") == V02_SCOPE
    }
    require(registered_v01 == EXPECTED_V01, "V01 exact exclusion set differs from frozen approval")
    require(registered_v02 == EXPECTED_V02, "V02 exact exclusion set differs from w.md")
    require(not (registered_v01 & registered_v02), "V01 and V02 exact exclusion sets overlap")
    prior_keys = set(PERMANENT_IDENTITY_EXCLUSIONS) - registered_v01 - registered_v02
    require(prior_keys == EXPECTED_PREEXISTING, "pre-existing permanent exclusion exact set changed")
    require(
        set(PERMANENT_IDENTITY_EXCLUSIONS) == EXPECTED_PREEXISTING | EXPECTED_V01 | EXPECTED_V02,
        "permanent exclusion exact-set composition is inconsistent",
    )

    source_intervals = [
        item
        for item in authority.pit_intervals
        if item.get("state") == "COMMON"
        and str(item["effective_from"]) <= actual_window[1]
        and str(item["effective_to"]) >= actual_window[0]
    ]
    original_intervals = [
        item
        for item in source_intervals
        if (str(item["ticker"]).zfill(6), str(item["isu_cd"]).upper()) not in prior_keys
    ]
    v01_success_intervals = [
        item
        for item in source_intervals
        if (str(item["ticker"]).zfill(6), str(item["isu_cd"]).upper())
        not in prior_keys | registered_v01
    ]
    final_intervals = [
        item
        for item in source_intervals
        if (str(item["ticker"]).zfill(6), str(item["isu_cd"]).upper())
        not in set(PERMANENT_IDENTITY_EXCLUSIONS)
    ]

    errors = source_manifest.get("failure_metadata", {}).get("errors", [])
    failed = failure_pairs(errors)
    require(failed == registered_v01, "source full-run failure pairs differ from the 12 V01 exclusions")
    require(source_manifest.get("simulation_status") == "SIMULATION_PARTIAL", "source simulation status is no longer partial")
    require(source_manifest.get("raw_artifacts_status") == "PARTIAL", "source raw status is no longer partial")
    require(source_manifest.get("execution", {}).get("target_tickers") == 2881, "original target ticker count changed")
    require(source_manifest.get("execution", {}).get("processed_tickers") == 2869, "successful raw ticker count changed")
    require(len(errors) == len(registered_v01), "source worker error count differs from V01 failure set")

    original_tickers = {str(item["ticker"]).zfill(6) for item in original_intervals}
    original_segments = {segment_key(item) for item in original_intervals}
    successful_tickers = {str(item["ticker"]).zfill(6) for item in v01_success_intervals}
    successful_segments = {segment_key(item) for item in v01_success_intervals}
    final_tickers = {str(item["ticker"]).zfill(6) for item in final_intervals}
    final_segment_keys = {segment_key(item) for item in final_intervals}
    require(len(original_tickers) == 2881, f"reconstructed original target ticker count changed: {len(original_tickers)}")
    require(len(original_segments) == 2899, f"reconstructed original segment count changed: {len(original_segments)}")
    require(len(successful_tickers) == 2869, f"V01 successful population changed: {len(successful_tickers)}")
    require(len(successful_segments) == 2887, f"V01 successful segment population changed: {len(successful_segments)}")
    successful_identity_set = {
        (str(item["ticker"]).zfill(6), str(item["isu_cd"]).upper())
        for item in v01_success_intervals
    }
    require(registered_v02 <= successful_identity_set, "one or more V02 identities are outside the frozen successful P1 population")
    require(
        final_tickers == successful_tickers - {ticker for ticker, _ in registered_v02},
        "final P1 ticker target does not equal successful V01 target minus V02 exact ticker identities",
    )
    expected_final_segments = {
        segment_key(item)
        for item in v01_success_intervals
        if (str(item["ticker"]).zfill(6), str(item["isu_cd"]).upper()) not in registered_v02
    }
    require(final_segment_keys == expected_final_segments, "final P1 identity-segment exact set mismatch")

    segments = [
        runner.IdentitySegment(
            ticker=str(item["ticker"]).zfill(6),
            isu_cd=str(item["isu_cd"]).upper(),
            market=str(item["market"]),
            effective_from=pd.Timestamp(item["effective_from"]).normalize(),
            effective_to=pd.Timestamp(item["effective_to"]).normalize(),
        )
        for item in source_intervals
    ]
    kept, excluded_segments = apply_permanent_identity_exclusions(segments)
    grouped: dict[str, list[Any]] = {}
    for segment in kept:
        grouped.setdefault(segment.ticker, []).append(segment)
    segments_by_ticker = {
        ticker: tuple(sorted(rows, key=lambda row: (row.effective_from, row.effective_to, row.isu_cd)))
        for ticker, rows in grouped.items()
    }
    context = runner.RunContext(
        window=window,
        calendar=calendar,
        authority=authority,
        segments_by_ticker=segments_by_ticker,
        score_contract=json.loads(runner.SCORE_CONTRACT_PATH.read_text(encoding="utf-8")),
        stage_contract=json.loads(runner.STAGE_CONTRACT_PATH.read_text(encoding="utf-8")),
        loader=None,
        lifecycle_settlements=runner._load_lifecycle_event_catalog(),
        authority_coverage_start=coverage_start,
        authority_coverage_end=coverage_end,
        setup_seconds=0.0,
        permanent_identity_exclusions=tuple(excluded_segments),
    )
    preflight = runner._p3_1_population_preflight(context)
    require(preflight.get("status") == "PASS", f"final P1 population preflight failed: {preflight}")
    return context, preflight, {
        "actual_window": actual_window,
        "prior_exclusions": sorted([list(value) for value in prior_keys]),
        "v01_exclusions": sorted([list(value) for value in registered_v01]),
        "v02_exclusions": sorted([list(value) for value in registered_v02]),
        "total_exclusion_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
        "original_ticker_count": len(original_tickers),
        "original_segment_count": len(original_segments),
        "successful_v01_ticker_count": len(successful_tickers),
        "successful_v01_segment_count": len(successful_segments),
        "final_ticker_count": len(final_tickers),
        "final_segment_count": len(final_segment_keys),
        "final_identity_count": len({(item[0], item[1]) for item in final_segment_keys}),
        "final_tickers": final_tickers,
        "final_segment_keys": final_segment_keys,
        "preflight": preflight,
    }


def read_and_filter_raw(
    source_dir: Path,
    final_identity_set: set[tuple[str, str]],
    policy_keys: set[tuple[str, str]],
    v02_keys: set[tuple[str, str]],
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    paths = {filename: source_dir / filename for filename in RAW_FILENAMES}
    for path in paths.values():
        require(path.is_file() and path.stat().st_size > 0, f"frozen raw artifact missing or empty: {path.name}")
    frames = {
        name: pd.read_csv(
            path,
            dtype={"ticker": str, "isu_cd": str, "pair_id": str, "trade_id": str},
            low_memory=False,
        )
        for name, path in paths.items()
    }
    control = frames["control_trades.csv"]
    candidate = frames["candidate_trades.csv"]
    paired = frames["paired_trades.csv"]
    matched = frames["p1_matched_trades.csv"]
    events = frames["p1_soft_events.csv"]

    control_pairs = set(control["pair_id"].astype(str))
    candidate_pairs = set(candidate["pair_id"].astype(str))
    require(control["pair_id"].is_unique and candidate["pair_id"].is_unique, "source side ledger pair_id is not unique")
    require(control_pairs == candidate_pairs, "source CONTROL/Candidate pair sets differ")
    control_by_pair = control.set_index("pair_id").sort_index()
    candidate_by_pair = candidate.set_index("pair_id").sort_index()
    require(
        control_by_pair["trade_id"].astype(str).equals(candidate_by_pair["trade_id"].astype(str)),
        "source CONTROL/Candidate trade_id differs by pair_id",
    )
    for field in ("ticker", "isu_cd", "entry_signal_date", "entry_execution_date", "market"):
        require(
            control_by_pair[field].fillna("").astype(str).equals(candidate_by_pair[field].fillna("").astype(str)),
            f"source CONTROL/Candidate identity or entry field differs: {field}",
        )
    require(
        (pd.to_numeric(control_by_pair["entry_open"], errors="coerce")
         - pd.to_numeric(candidate_by_pair["entry_open"], errors="coerce"))
        .abs().fillna(0).le(0.005).all(),
        "source CONTROL/Candidate entry_open differs",
    )
    require(paired["pair_id"].is_unique and set(paired["pair_id"].astype(str)) == control_pairs, "source paired ledger pair set mismatch")
    require(matched["pair_id"].is_unique and set(matched["pair_id"].astype(str)) == control_pairs, "source matched ledger pair set mismatch")
    require(
        matched.set_index("pair_id")["trade_id"].astype(str).sort_index().equals(
            control.set_index("pair_id")["trade_id"].astype(str).sort_index()
        ),
        "source matched-ledger trade_id differs from source trades",
    )
    if {"trade_id_control", "trade_id_candidate"}.issubset(paired.columns):
        require(
            paired.set_index("pair_id")["trade_id_control"].astype(str).sort_index().equals(
                paired.set_index("pair_id")["trade_id_candidate"].astype(str).sort_index()
            ),
            "source paired-ledger side trade IDs differ",
        )
    require(set(events["pair_id"].astype(str)).issubset(set(matched["pair_id"].astype(str))), "source soft event references a missing matched pair")
    require(int(events.duplicated(["pair_id", "date", "event_type"]).sum()) == 0, "source soft-event duplicate exists")
    require(
        set(events["event_type"].fillna("").astype(str)) <= {"WEAK_PROTECT", "SOFT_EXIT_SIGNAL"},
        "source soft-event type is outside the P1 contract",
    )

    source_identities = identity_pairs(control)
    require(source_identities <= final_identity_set | v02_keys, "source raw identity lies outside the V01-successful population")
    require(source_identities & v02_keys == v02_keys, "not all 20 V02 identities appear in frozen trade raw")
    require(not (source_identities & (policy_keys - v02_keys)), "a pre-existing or V01-excluded identity unexpectedly appears in frozen trade raw")

    def mask(frame: pd.DataFrame) -> pd.Series:
        normalized = pd.Series(
            list(zip(
                frame["ticker"].fillna("").astype(str).str.strip().str.zfill(6),
                frame["isu_cd"].fillna("").astype(str).str.strip().str.upper(),
            )),
            index=frame.index,
        )
        return normalized.isin(policy_keys)

    control_excluded_ids = set(control.loc[mask(control), "pair_id"].astype(str))
    candidate_excluded_ids = set(candidate.loc[mask(candidate), "pair_id"].astype(str))
    require(control_excluded_ids == candidate_excluded_ids, "V02 exact-pair filter is asymmetric across source sides")
    require(control_excluded_ids, "V02 exclusion filter matched no frozen source trade")
    filtered: dict[str, pd.DataFrame] = {}
    for filename, frame in frames.items():
        if filename in {"control_trades.csv", "candidate_trades.csv"}:
            filtered[filename] = frame.loc[~mask(frame)].copy().reset_index(drop=True)
        else:
            filtered[filename] = frame.loc[
                ~frame["pair_id"].astype(str).isin(control_excluded_ids)
            ].copy().reset_index(drop=True)

    f_control = filtered["control_trades.csv"]
    f_candidate = filtered["candidate_trades.csv"]
    f_paired = filtered["paired_trades.csv"]
    f_matched = filtered["p1_matched_trades.csv"]
    f_events = filtered["p1_soft_events.csv"]
    f_ids = set(f_control["pair_id"].astype(str))
    require(f_ids == set(f_candidate["pair_id"].astype(str)), "filtered CONTROL/Candidate pair symmetry failed")
    require(not (identity_pairs(f_control) & policy_keys), "an exact excluded identity remains in filtered trades")
    require(identity_pairs(f_control) <= final_identity_set, "filtered trade identity lies outside final P1 population")
    require(f_paired["pair_id"].is_unique and set(f_paired["pair_id"].astype(str)) == f_ids, "filtered paired ledger is not exact and unique")
    require(f_matched["pair_id"].is_unique and set(f_matched["pair_id"].astype(str)) == f_ids, "filtered matched ledger is not exact and unique")
    require(
        f_matched.set_index("pair_id")["trade_id"].astype(str).sort_index().equals(
            f_control.set_index("pair_id")["trade_id"].astype(str).sort_index()
        ),
        "filtered matched-ledger trade_id alignment failed",
    )
    require(set(f_events["pair_id"].astype(str)) <= f_ids, "filtered soft-event references a removed trade")
    event_duplicates = int(f_events.duplicated(["pair_id", "date", "event_type"]).sum())
    require(event_duplicates == 0, f"filtered soft-event duplicate count is {event_duplicates}")
    require(set(f_events["event_type"].fillna("").astype(str)) <= {"WEAK_PROTECT", "SOFT_EXIT_SIGNAL"}, "filtered soft-event type is invalid")
    require(len(f_control) == len(f_candidate) == len(f_paired) == len(f_matched), "filtered trade/ledger row counts differ")

    hashes = {filename: sha256(path) for filename, path in paths.items()}
    checks = {
        "source_pair_symmetry": True,
        "source_pair_id_uniqueness": True,
        "source_trade_id_alignment": True,
        "source_paired_and_matched_exact_pair_sets": True,
        "source_soft_event_reference_integrity": True,
        "source_soft_event_duplicate_count": 0,
        "filtered_exact_exclusions_absent": True,
        "filtered_control_candidate_pair_symmetry": True,
        "filtered_paired_and_matched_pair_id_unique_and_exact": True,
        "filtered_trade_id_alignment": True,
        "filtered_soft_event_reference_integrity": True,
        "filtered_soft_event_duplicate_count": event_duplicates,
        "source_identity_count": len(source_identities),
        "source_v02_identity_count": len(source_identities & v02_keys),
        "filtered_identity_count": len(identity_pairs(f_control)),
        "excluded_pair_count": len(control_excluded_ids),
        "source_rows": {name: int(len(frame)) for name, frame in frames.items()},
        "filtered_rows": {name: int(len(frame)) for name, frame in filtered.items()},
        "filtered_event_type_counts": {
            str(key): int(value)
            for key, value in f_events["event_type"].value_counts().sort_index().items()
        },
    }
    return filtered, hashes, checks


def make_eval_manifest(
    source_manifest: dict[str, Any],
    context: Any,
    population: dict[str, Any],
    source_hashes: dict[str, str],
    filtered: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    return {
        "run_id": "run_20260925_standard_full_worker10_v01_raw_only_exclusion_closure_v02",
        "window_id": "P1",
        "p1_only": True,
        "start_head": source_manifest.get("start_head"),
        "evaluation_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "effective_pit_sha256": context.authority.pit_sha256,
        "simulation_status": source_manifest.get("simulation_status"),
        "raw_artifacts_status": source_manifest.get("raw_artifacts_status"),
        "postprocess_status": "PENDING_RAW_ONLY_EVALUATION",
        "source_run_id": source_manifest.get("run_id"),
        "source_manifest_sha256": hashlib.sha256(
            (runner.P1_RUN_DIR / "run_manifest.json").read_bytes()
        ).hexdigest(),
        "source_raw_sha256": source_hashes,
        "permanent_identity_exclusions": [
            {
                "ticker": ticker,
                "isu_cd": isu,
                **PERMANENT_IDENTITY_EXCLUSIONS[(ticker, isu)],
            }
            for ticker, isu in sorted(set(PERMANENT_IDENTITY_EXCLUSIONS))
        ],
        "execution": {
            "workers": source_manifest.get("execution", {}).get("workers"),
            "processed_tickers": population["final_ticker_count"],
            "target_tickers": population["final_ticker_count"],
            "total_segments": population["final_segment_count"],
            "elapsed_seconds": 0.0,
            "setup_seconds": 0.0,
            "repository_load_count": 0,
            "simulation_replay_performed": False,
            "recovery_replay_performed": False,
        },
        "raw_artifacts": {
            key: f"{V02_EXCLUSION_DIRNAME}/{name}"
            for key, name in (
                ("control", "control_trades.csv"),
                ("candidate", "candidate_trades.csv"),
                ("paired", "paired_trades.csv"),
                ("matched_ledger", "p1_matched_trades.csv"),
                ("soft_events", "p1_soft_events.csv"),
            )
        },
        "outputs": [],
        "filtered_rows": {name: int(len(frame)) for name, frame in filtered.items()},
        "population": {
            "final_ticker_count": population["final_ticker_count"],
            "final_segment_count": population["final_segment_count"],
            "final_identity_count": population["final_identity_count"],
        },
    }


def main() -> int:
    runner._configure_run("P1")
    source_dir = runner.RUN_DIR
    source_manifest_path = source_dir / "run_manifest.json"
    eval_dir = source_dir / V02_EXCLUSION_DIRNAME
    cert_path = eval_dir / "p1_raw_only_certification_v02.json"
    summary_path = eval_dir / "summary.json"
    ledger_summary_path = eval_dir / "p1_summary.json"
    require(source_manifest_path.is_file(), "frozen P1 source manifest is missing")
    require(not eval_dir.exists(), f"refusing to overwrite existing V02 evaluation directory: {eval_dir}")
    eval_dir.mkdir(parents=True)
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest_sha = hashlib.sha256(source_manifest_bytes).hexdigest()
    source_manifest = json.loads(source_manifest_bytes)
    source_head = source_manifest.get("start_head")
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_raw_hashes: dict[str, str] = {}
    stage = "INITIAL_PREFLIGHT"
    context = None
    population: dict[str, Any] = {}
    raw_checks: dict[str, Any] = {}
    summary: dict[str, Any] | None = None

    try:
        require(source_manifest.get("window_id") == "P1", "source manifest is not P1")
        context, preflight, population = build_context(source_manifest)
        policy_keys = set(PERMANENT_IDENTITY_EXCLUSIONS)
        v02_keys = set(EXPECTED_V02)
        final_identity_set = {
            (segment.ticker, segment.stable_security_id)
            for rows in context.segments_by_ticker.values()
            for segment in rows
        }
        source_raw_paths = {name: source_dir / name for name in RAW_FILENAMES}
        source_raw_hashes = {name: sha256(path) for name, path in source_raw_paths.items()}
        stage = "FROZEN_RAW_INTEGRITY_AND_FILTER"
        filtered, measured_hashes, raw_checks = read_and_filter_raw(
            source_dir,
            final_identity_set,
            policy_keys,
            v02_keys,
        )
        require(measured_hashes == source_raw_hashes, "source raw changed during integrity read")

        # Verify the event ledger against the unchanged strategy contract before
        # asking the aggregate summarizer to produce any certification summary.
        stage = "BLOCKER_RECHECK"
        control = filtered["control_trades.csv"]
        candidate = filtered["candidate_trades.csv"]
        validation = runner._namespace_p3_gate_fields(
            runner._validate_results(control, candidate, context), "P1"
        )
        source_events = filtered["p1_soft_events.csv"]
        built_events = runner._build_soft_event_ledger(
            [{"soft_events": source_events.to_dict(orient="records")}],
            candidate,
            run=context,
        )
        require(
            len(built_events) == len(source_events),
            "filtered soft-event ledger row count changed under frozen contract",
        )

        stage = "WRITE_SEPARATE_EVALUATION_ARTIFACTS"
        outputs = []
        for filename, frame in filtered.items():
            target = eval_dir / filename
            frame.to_csv(target, index=False, float_format="%.8f")
            outputs.append(str(target.relative_to(ROOT)))
        eval_manifest = make_eval_manifest(
            source_manifest, context, population, source_raw_hashes, filtered
        )
        eval_manifest["outputs"] = outputs.copy()
        runner._json_write(eval_dir / "run_manifest.json", eval_manifest)

        # Reuse only the production aggregate/validation logic. All paths are
        # redirected to the new V02 directory, and raw input is the filtered
        # in-memory copy; no source raw, simulation or recovery replay is used.
        original_globals = {
            "RUN_DIR": runner.RUN_DIR,
            "RUN_ID": runner.RUN_ID,
            "SAMPLE_PATH": runner.SAMPLE_PATH,
            "CONTROL_FULL_PATH": runner.CONTROL_FULL_PATH,
            "INITIAL_FULL_SUMMARY_PATH": runner.INITIAL_FULL_SUMMARY_PATH,
            "CORRECTED_RUN_DIR": runner.CORRECTED_RUN_DIR,
            "MATCHED_LEDGER_PATH": runner.MATCHED_LEDGER_PATH,
            "SOFT_EVENTS_PATH": runner.SOFT_EVENTS_PATH,
            "LEDGER_SUMMARY_PATH": runner.LEDGER_SUMMARY_PATH,
        }
        original_raw_loader = runner._load_raw_artifacts_for_summary
        original_context_loader = runner._load_context

        runner.RUN_ID = "run_20260925_standard_full_worker10_v01_raw_only_exclusion_closure_v02"
        runner.RUN_DIR = eval_dir
        runner.CORRECTED_RUN_DIR = eval_dir
        runner.SAMPLE_PATH = original_globals["SAMPLE_PATH"]
        runner.CONTROL_FULL_PATH = eval_dir / "control_trades.csv"
        runner.INITIAL_FULL_SUMMARY_PATH = summary_path
        runner.MATCHED_LEDGER_PATH = eval_dir / "p1_matched_trades.csv"
        runner.SOFT_EVENTS_PATH = eval_dir / "p1_soft_events.csv"
        runner.LEDGER_SUMMARY_PATH = ledger_summary_path

        def load_filtered_raw(selected_window: str):
            require(selected_window == "P1", f"filtered evaluation cannot load {selected_window}")
            fresh_hashes = {name: sha256(path) for name, path in source_raw_paths.items()}
            require(fresh_hashes == source_raw_hashes, "source raw SHA changed before summary")
            return (
                filtered["control_trades.csv"],
                filtered["candidate_trades.csv"],
                filtered["paired_trades.csv"],
                filtered["p1_matched_trades.csv"],
                filtered["p1_soft_events.csv"],
                eval_manifest,
            )

        def load_light_context(selected_window: str | None = None):
            require(selected_window in (None, "P1"), f"raw-only evaluation cannot load {selected_window}")
            return context

        runner._load_raw_artifacts_for_summary = load_filtered_raw
        runner._load_context = load_light_context
        try:
            stage = "RAW_ONLY_SUMMARY_VALIDATION"
            summary = runner._run_impl("summarize", workers=1, sample_count=1, window_id="P1")
        finally:
            runner._load_raw_artifacts_for_summary = original_raw_loader
            runner._load_context = original_context_loader
            for name, value in original_globals.items():
                setattr(runner, name, value)

        after_hashes = {name: sha256(path) for name, path in source_raw_paths.items()}
        require(after_hashes == source_raw_hashes, "source raw SHA-256 changed during raw-only evaluation")
        require(source_manifest_path.read_bytes() == source_manifest_bytes, "frozen source run manifest changed")

        validation = summary.get("validation", {})
        final_pair_ids = validation.get("p1_authoritative_final_unresolved_pair_ids", [])
        expected_final_pairs = [ALLOWED_FINAL_UNRESOLVED_PAIR_ID]
        required_checks = {
            "summary_status_complete": summary.get("status") == "COMPLETE",
            "summary_p1_replay_pass": summary.get("verdict") == "P1_REPLAY_PASS",
            "population_preflight_pass": summary.get("population_preflight", {}).get("status") == "PASS",
            "duplicate_pair_ids_zero": validation.get("duplicate_pair_ids") == 0,
            "entry_population_parity": validation.get("entry_population_parity") is True,
            "exit_window_violations_zero": validation.get("exit_window_violations") == 0,
            "candidate_unexecuted_signal_zero": validation.get("candidate_unexecuted_signal_count") == 0,
            "candidate_execution_support_missing_zero": validation.get("candidate_execution_support_missing_count") == 0,
            "candidate_overlap_zero": validation.get("candidate_overlap_count") == 0,
            "candidate_stage_asof_future_violations_zero": validation.get("candidate_stage_asof_future_violations") == 0,
            "effective_identity_ended_open_unresolved_zero": validation.get("p1_effective_identity_ended_open_unresolved_count") == 0,
            "effective_terminal_valuation_unresolved_zero": validation.get("p1_effective_terminal_valuation_unresolved_count") == 0,
            "effective_remediable_unresolved_zero": validation.get("p1_effective_remediable_unresolved_count") == 0,
            "matched_remediable_unresolved_zero": validation.get("matched_pairs_remediable_unresolved") == 0,
            "allowed_authoritative_final_pair_preserved": sorted(final_pair_ids) == sorted(expected_final_pairs),
            "lifecycle_gate_control_candidate_symmetric": validation.get("p1_lifecycle_gate_control_candidate_symmetry") is True,
            "lifecycle_gate_unresolved_zero_by_side": all(validation.get("p1_lifecycle_gate_unresolved_zero_by_side", {}).values()),
            "ledger_pair_id_unique": validation.get("ledger_pair_id_unique") is True,
            "ledger_pair_id_set_matches_sources": validation.get("ledger_pair_id_set_matches_sources") is True,
            "ledger_source_trade_id_equal_by_pair": validation.get("ledger_source_trade_id_equal_by_pair") is True,
            "control_candidate_source_trade_id_equal_by_pair": validation.get("control_candidate_source_trade_id_equal_by_pair") is True,
            "all_ledger_aggregates_match_summary": validation.get("all_ledger_aggregates_match_summary") is True,
            "soft_event_duplicates_zero": validation.get("soft_event_duplicates") == 0,
            "soft_exit_execution_contract_pass": validation.get("soft_exit_execution_contract_pass") is True,
            "cutoff_after_soft_event_zero": validation.get("cutoff_after_soft_event_count") == 0,
            "ledger_recomputation_pass": validation.get("ledger_recomputation_pass") is True,
            "source_raw_sha256_preserved": after_hashes == source_raw_hashes,
        }
        require(all(required_checks.values()), f"one or more V02 certification gates failed: {[key for key, value in required_checks.items() if not value]}")

        source_errors = source_manifest.get("failure_metadata", {}).get("errors", [])
        event_counts = {
            str(key): int(value)
            for key, value in filtered["p1_soft_events.csv"]["event_type"].value_counts().sort_index().items()
        }
        final_verdict = "P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS"
        certification = {
            "status": "PASS",
            "verdict": final_verdict,
            "window_id": "P1",
            "source_run_id": source_manifest.get("run_id"),
            "source_head": source_head,
            "evaluation_head": current_head,
            "source_simulation_status_preserved": source_manifest.get("simulation_status"),
            "source_raw_artifacts_status_preserved": source_manifest.get("raw_artifacts_status"),
            "source_full_simulation": {
                "initial_target_tickers": source_manifest.get("execution", {}).get("target_tickers"),
                "successfully_processed_tickers": source_manifest.get("execution", {}).get("processed_tickers"),
                "worker_failure_count": len(source_errors),
                "worker_failure_messages": source_errors,
                "elapsed_seconds": source_manifest.get("execution", {}).get("elapsed_seconds"),
            },
            "permanent_exclusion_transition": {
                "before_v02_count": len(set(PERMANENT_IDENTITY_EXCLUSIONS) - EXPECTED_V02),
                "added_count": len(EXPECTED_V02),
                "total_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
                "added_identities": [list(value) for value in sorted(EXPECTED_V02)],
                "exact_set_pass": True,
            },
            "p1_population": {
                "calendar_start": context.window.window.calendar_start.strftime("%Y-%m-%d"),
                "calendar_end": context.window.window.calendar_end.strftime("%Y-%m-%d"),
                "effective_start": context.window.effective_start.strftime("%Y-%m-%d"),
                "effective_end": context.window.effective_end.strftime("%Y-%m-%d"),
                "execution_support": context.window.execution_support.strftime("%Y-%m-%d"),
                "original_target_tickers": population["original_ticker_count"],
                "successful_v01_tickers": population["successful_v01_ticker_count"],
                "final_evaluation_tickers": population["final_ticker_count"],
                "final_identity_segments": population["final_segment_count"],
                "final_identity_count": population["final_identity_count"],
                "population_preflight": preflight,
            },
            "simulation_replay_performed": False,
            "recovery_replay_performed": False,
            "raw_reused_as_frozen_source": True,
            "source_raw_files_modified": False,
            "source_raw_sha256_before": source_raw_hashes,
            "source_raw_sha256_after": after_hashes,
            "source_raw_sha256_preserved": after_hashes == source_raw_hashes,
            "source_run_manifest_sha256_before": source_manifest_sha,
            "source_run_manifest_preserved": source_manifest_path.read_bytes() == source_manifest_bytes,
            "raw_integrity": raw_checks,
            "blocker_recheck": {
                "005950_soft_exit_execution_mismatch_removed": not (
                    identity_pairs(filtered["candidate_trades.csv"]) & {("005950", "KR7005950001")}
                ),
                "033630_unexecuted_signal_removed": not (
                    identity_pairs(filtered["candidate_trades.csv"]) & {("033630", "KR7033630005")}
                ),
                "lifecycle_19_exact_pairs_removed": not (
                    identity_pairs(filtered["candidate_trades.csv"]) & (EXPECTED_V02 - {("005950", "KR7005950001")})
                ),
                "candidate_unexecuted_signal_count": validation.get("candidate_unexecuted_signal_count"),
                "candidate_execution_support_missing_count": validation.get("candidate_execution_support_missing_count"),
                "soft_exit_execution_contract_pass": validation.get("soft_exit_execution_contract_pass"),
            },
            "unresolved_lifecycle_gate": {
                key: value for key, value in validation.items() if "unresolved" in key or "lifecycle_gate" in key
            },
            "allowed_authoritative_final_unresolved_pair_ids": final_pair_ids,
            "required_checks": required_checks,
            "summary_status": summary.get("status"),
            "summary_verdict": summary.get("verdict"),
            "summary_path": str(summary_path.relative_to(ROOT)),
            "ledger_summary_path": str(ledger_summary_path.relative_to(ROOT)),
            "summary_validation": validation,
            "aggregate_results": {
                "control": summary.get("control"),
                "candidate": summary.get("candidate"),
                "paired": summary.get("paired"),
                "matched_pair_counts": summary.get("matched_pair_counts"),
                "ledger": summary.get("ledger"),
                "soft_events": summary.get("soft_events"),
            },
        }
        summary["status"] = "COMPLETE"
        summary["verdict"] = final_verdict
        summary["certification_verdict"] = final_verdict
        summary["strategy_assessment"] = runner._verdict(summary, validation)
        summary["simulation_replay_performed"] = False
        summary["raw_only_exclusion_filtered_certification"] = certification
        summary["execution"].update(
            {
                "actual_full_seconds": None,
                "setup_seconds": 0.0,
                "repository_v2_load_count": 0,
                "raw_only_summary_execution": True,
                "simulation_replay_performed": False,
                "recovery_replay_performed": False,
            }
        )
        summary["population"]["assessment_universe_ticker_count"] = population["final_ticker_count"]
        summary["population"]["common_identity_segments"] = population["final_segment_count"]
        runner._json_write(summary_path, summary)
        runner._json_write(ledger_summary_path, summary)
        runner._json_write(cert_path, certification)
        eval_manifest = json.loads((eval_dir / "run_manifest.json").read_text(encoding="utf-8"))
        eval_manifest.update(
            {
                "assessment_status": "COMPLETE",
                "certification_status": final_verdict,
                "postprocess_status": "COMPLETE",
                "postprocess_stage": "COMPLETE",
                "summarized_from_raw_artifacts": True,
                "simulation_replay_performed": False,
                "recovery_replay_performed": False,
                "raw_only_exclusion_filtered_certification": certification,
            }
        )
        for path in (summary_path, ledger_summary_path, cert_path):
            rel = str(path.relative_to(ROOT))
            if rel not in eval_manifest["outputs"]:
                eval_manifest["outputs"].append(rel)
        runner._json_write(eval_dir / "run_manifest.json", eval_manifest)
        print(json.dumps({
            "status": "PASS",
            "verdict": final_verdict,
            "v02_exclusions": len(EXPECTED_V02),
            "total_exclusions": len(PERMANENT_IDENTITY_EXCLUSIONS),
            "final_tickers": population["final_ticker_count"],
            "matched_pairs": len(filtered["p1_matched_trades.csv"]),
            "numeric_comparable": summary.get("matched_pair_counts", {}).get("matched_pairs_numeric_comparable"),
            "source_raw_sha256_preserved": True,
            "simulation_replay_performed": False,
            "evaluation_dir": str(eval_dir.relative_to(ROOT)),
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        after_hashes = {}
        try:
            after_hashes = {
                name: sha256(source_dir / name)
                for name in RAW_FILENAMES
                if (source_dir / name).is_file()
            }
        except Exception:
            pass
        failure = {
            "status": "CHECK_REQUIRED",
            "verdict": "CHECK_REQUIRED",
            "stage": stage,
            "reason": f"{type(exc).__name__}: {exc}",
            "window_id": "P1",
            "source_run_id": source_manifest.get("run_id"),
            "source_head": source_head,
            "evaluation_head": current_head,
            "simulation_replay_performed": False,
            "recovery_replay_performed": False,
            "source_raw_sha256_before": source_raw_hashes,
            "source_raw_sha256_after": after_hashes,
            "source_raw_sha256_preserved": bool(source_raw_hashes) and after_hashes == source_raw_hashes,
            "source_run_manifest_sha256_before": source_manifest_sha,
            "source_run_manifest_preserved": source_manifest_path.read_bytes() == source_manifest_bytes,
            "raw_integrity_so_far": raw_checks,
            "population_so_far": {
                key: value
                for key, value in population.items()
                if key not in {"final_tickers", "final_segment_keys"}
            },
            "added_identities": [list(value) for value in sorted(EXPECTED_V02)],
        }
        runner._json_write(cert_path, failure)
        if (eval_dir / "run_manifest.json").is_file():
            eval_manifest = json.loads((eval_dir / "run_manifest.json").read_text(encoding="utf-8"))
        else:
            eval_manifest = {
                "run_id": "run_20260925_standard_full_worker10_v01_raw_only_exclusion_closure_v02",
                "window_id": "P1",
                "source_run_id": source_manifest.get("run_id"),
                "start_head": source_head,
                "simulation_status": source_manifest.get("simulation_status"),
                "raw_artifacts_status": source_manifest.get("raw_artifacts_status"),
                "execution": {"simulation_replay_performed": False, "recovery_replay_performed": False},
                "outputs": [],
            }
        eval_manifest.update(
            {
                "assessment_status": "CHECK_REQUIRED",
                "certification_status": "CHECK_REQUIRED",
                "postprocess_status": "CHECK_REQUIRED",
                "postprocess_error": failure["reason"],
                "simulation_replay_performed": False,
                "recovery_replay_performed": False,
            }
        )
        rel_cert = str(cert_path.relative_to(ROOT))
        if rel_cert not in eval_manifest["outputs"]:
            eval_manifest["outputs"].append(rel_cert)
        runner._json_write(eval_dir / "run_manifest.json", eval_manifest)
        print(json.dumps(failure, ensure_ascii=False, indent=2, default=str))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
