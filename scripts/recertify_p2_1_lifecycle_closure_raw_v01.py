#!/usr/bin/env python3
"""Close P2-1 from the frozen v02 corrective raw under the current lifecycle contract.

The source ``run_20260925_corrective_full_recert_v02`` CONTROL/Candidate trade
ledgers are frozen evidence.  This script filters exact (ticker, ISU)
exclusions into a new evaluation directory, labels the sealed 096300
authoritative-final pair on the evaluation copy only, and recomputes
summary/validation/certification with the existing runner helpers.  It never
invokes ticker simulation and never writes into the source run directory.
"""

from __future__ import annotations

import argparse
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


SOURCE_RUN_ID = "run_20260925_corrective_full_recert_v02"
SOURCE_START_HEAD = "4536d2bf80681141ad2e43ab6a2f8082ec4df6e3"
SOURCE_RELATIVE_DIR = Path("artifacts/backtests/p2_1_neg40_weak_protect_v01") / SOURCE_RUN_ID
EVALUATION_DIRNAME = "raw_only_lifecycle_closure_v01"
EVALUATION_RUN_ID = f"{SOURCE_RUN_ID}_{EVALUATION_DIRNAME}"
EXPECTED_PIT_SHA256 = "a1952956427c214c21aa2fa293366d9ef092b36ae5afb3b110fd1ae556ccb3b0"
EXPECTED_WINDOW = ("2021-01-04", "2025-05-30", "2025-06-02")
EXPECTED_SOURCE_SEGMENTS = 2657
EXPECTED_SOURCE_TICKERS = 2648
EXPECTED_SOURCE_PAIRS = 1834
RAW_FILENAMES = ("control_trades.csv", "candidate_trades.csv", "paired_trades.csv")

# Registry identities that already appear in the frozen P2-1 raw.  Pinned so a
# registry change cannot silently alter the certified population.
EXPECTED_REGISTRY_RAW_IDENTITIES = {
    ("002270", "KR7002270007"),
    ("005390", "KR7005390000"),
    ("005950", "KR7005950001"),
    ("006390", "KR7006390009"),
    ("010420", "KR7010420008"),
    ("031440", "KR7031440001"),
    ("032980", "KR7032980005"),
    ("036620", "KR7036620003"),
    ("043220", "KR7043220003"),
    ("044060", "KR7044060002"),
    ("049770", "KR7049770001"),
    ("057050", "KR7057050007"),
    ("069460", "KR7069460004"),
    ("138490", "KR7138490008"),
    ("335890", "KR7335890000"),
    ("950110", "KR8392070007"),
}

# The v02 raw preserves these trades as UNRESOLVED_SUCCESSOR with no terminal
# value.  Resolving them would require recomputing successor economics, so the
# closure excludes the exact identities instead (evaluation population only).
P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS: dict[tuple[str, str], dict[str, str]] = {
    identity: {
        "reason": (
            "v02 frozen raw holds UNRESOLVED_SUCCESSOR with no terminal value; "
            "current-contract resolution would require successor re-valuation"
        ),
        "approval_scope": "P2-1 raw-only lifecycle closure V01",
        "policy_version": "p2_1_lifecycle_closure_exclusions_v01",
    }
    for identity in (
        ("008560", "KR7008560005"),
        ("023890", "KR7023890007"),
        ("043290", "KR7043290006"),
        ("046140", "KR7046140000"),
        ("213090", "KR7213090004"),
        ("225330", "KR7225330000"),
        ("282690", "KR7282690007"),
    )
}
ALLOWED_FINAL_UNRESOLVED_PAIR_ID = "096300|KR7096300009|KOSPI|2010-01-04|2023-02-01|096300_01"
FINAL_VERDICT = "P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS"


class CheckRequired(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckRequired(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_hashes(directory: Path) -> dict[str, str]:
    return {path.name: sha256(path) for path in sorted(directory.iterdir()) if path.is_file()}


def identity_series(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(
        list(zip(
            frame["ticker"].fillna("").astype(str).str.strip().str.zfill(6),
            frame["isu_cd"].fillna("").astype(str).str.strip().str.upper(),
        )),
        index=frame.index,
    )


def identity_pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return set(identity_series(frame))


def build_context(calendar_root: Path) -> tuple[Any, dict[str, Any]]:
    calendar = runner.load_rolling_production_market_calendar(calendar_root)
    require(calendar is not None, f"rolling production calendar is missing under {calendar_root}")
    window = runner.resolve_standard_backtest_window("P2-1", calendar)
    actual_window = tuple(
        value.strftime("%Y-%m-%d")
        for value in (window.effective_start, window.effective_end, window.execution_support)
    )
    require(actual_window == EXPECTED_WINDOW, f"P2-1 window changed: {actual_window}")

    authority = runner.load_effective_authority(runner.AUTHORITY_DIR)
    require(authority.pit_sha256 == EXPECTED_PIT_SHA256, "effective PIT SHA-256 differs from v02 source")
    base_calendar = runner.load_historical_trading_calendar(runner.HISTORICAL_IDENTITY_CALENDAR_PATH)

    source_segments = []
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        start = pd.Timestamp(item["effective_from"]).normalize()
        end = pd.Timestamp(item["effective_to"]).normalize()
        if start > window.effective_end or end < window.effective_start:
            continue
        source_segments.append(
            runner.IdentitySegment(
                ticker=str(item["ticker"]).zfill(6),
                isu_cd=str(item["isu_cd"]).upper(),
                market=str(item["market"]),
                effective_from=start,
                effective_to=end,
            )
        )
    source_tickers = {segment.ticker for segment in source_segments}
    require(len(source_segments) == EXPECTED_SOURCE_SEGMENTS, f"P2-1 source segment count changed: {len(source_segments)}")
    require(len(source_tickers) == EXPECTED_SOURCE_TICKERS, f"P2-1 source ticker count changed: {len(source_tickers)}")

    registry_kept, registry_excluded = apply_permanent_identity_exclusions(source_segments)
    kept = []
    closure_excluded = []
    for segment in registry_kept:
        policy = P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS.get((segment.ticker, segment.isu_cd))
        if policy is None:
            kept.append(segment)
            continue
        closure_excluded.append(
            {
                "ticker": segment.ticker,
                "isu_cd": segment.isu_cd,
                "market": segment.market,
                "effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                "effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                **policy,
            }
        )
    require(
        {(item["ticker"], item["isu_cd"]) for item in closure_excluded}
        == set(P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS),
        "one or more closure exclusions are absent from the P2-1 COMMON population",
    )
    grouped: dict[str, list[Any]] = {}
    for segment in sorted(kept, key=lambda row: (row.ticker, row.effective_from, row.effective_to, row.isu_cd)):
        grouped.setdefault(segment.ticker, []).append(segment)
    context = runner.RunContext(
        window=window,
        calendar=calendar,
        authority=authority,
        segments_by_ticker={ticker: tuple(rows) for ticker, rows in grouped.items()},
        score_contract=json.loads(runner.SCORE_CONTRACT_PATH.read_text(encoding="utf-8")),
        stage_contract=json.loads(runner.STAGE_CONTRACT_PATH.read_text(encoding="utf-8")),
        loader=None,
        lifecycle_settlements=runner._load_lifecycle_event_catalog(),
        authority_coverage_start=str(base_calendar["first_trading_date"]),
        authority_coverage_end=str(base_calendar["last_trading_date"]),
        setup_seconds=0.0,
        permanent_identity_exclusions=tuple(registry_excluded + closure_excluded),
    )
    final_identities = {(segment.ticker, segment.isu_cd) for segment in kept}
    return context, {
        "actual_window": list(actual_window),
        "calendar_certified_through": calendar.metadata.get("certified_through"),
        "calendar_manifest_sha256": calendar.metadata.get("manifest_sha256"),
        "source_segment_count": len(source_segments),
        "source_ticker_count": len(source_tickers),
        "registry_excluded_segment_count": len(registry_excluded),
        "registry_excluded_identity_count": len({(item["ticker"], item["isu_cd"]) for item in registry_excluded}),
        "closure_excluded_segment_count": len(closure_excluded),
        "closure_excluded_identity_count": len(P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS),
        "final_segment_count": len(kept),
        "final_ticker_count": len(grouped),
        "final_identity_count": len(final_identities),
        "final_identities": final_identities,
    }


def read_and_filter_raw(
    source_dir: Path,
    final_identities: set[tuple[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frames = {
        name: pd.read_csv(
            source_dir / name,
            dtype={"ticker": str, "isu_cd": str, "pair_id": str, "trade_id": str},
            low_memory=False,
        )
        for name in RAW_FILENAMES
    }
    control = frames["control_trades.csv"]
    candidate = frames["candidate_trades.csv"]
    paired = frames["paired_trades.csv"]

    require(len(control) == len(candidate) == len(paired) == EXPECTED_SOURCE_PAIRS, "source pair count changed")
    require(control["pair_id"].is_unique and candidate["pair_id"].is_unique, "source side pair_id is not unique")
    require(set(control["pair_id"]) == set(candidate["pair_id"]), "source CONTROL/Candidate pair sets differ")
    require(paired["pair_id"].is_unique and set(paired["pair_id"]) == set(control["pair_id"]), "source paired pair set mismatch")
    control_by_pair = control.set_index("pair_id").sort_index()
    candidate_by_pair = candidate.set_index("pair_id").sort_index()
    for field in ("trade_id", "ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date"):
        require(
            control_by_pair[field].fillna("").astype(str).equals(candidate_by_pair[field].fillna("").astype(str)),
            f"source CONTROL/Candidate field differs by pair_id: {field}",
        )
    require(
        (pd.to_numeric(control_by_pair["entry_open"], errors="coerce")
         - pd.to_numeric(candidate_by_pair["entry_open"], errors="coerce"))
        .abs().fillna(0).le(0.005).all(),
        "source CONTROL/Candidate entry_open differs",
    )
    paired_by_pair = paired.set_index("pair_id").sort_index()
    require(
        paired_by_pair["trade_id_control"].astype(str).equals(paired_by_pair["trade_id_candidate"].astype(str))
        and paired_by_pair["trade_id_control"].astype(str).equals(control_by_pair["trade_id"].astype(str)),
        "source paired-ledger trade_id alignment failed",
    )

    source_identities = identity_pairs(control)
    registry_hits = source_identities & set(PERMANENT_IDENTITY_EXCLUSIONS)
    require(
        registry_hits == EXPECTED_REGISTRY_RAW_IDENTITIES,
        f"registry identities in P2-1 raw changed: {sorted(registry_hits ^ EXPECTED_REGISTRY_RAW_IDENTITIES)}",
    )
    closure_keys = set(P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS)
    require(closure_keys <= source_identities, "a closure exclusion does not appear in frozen P2-1 raw")
    require(not (closure_keys & set(PERMANENT_IDENTITY_EXCLUSIONS)), "closure exclusion overlaps the registry")
    policy_keys = registry_hits | closure_keys

    control_mask = identity_series(control).isin(policy_keys)
    candidate_mask = identity_series(candidate).isin(policy_keys)
    control_excluded = set(control.loc[control_mask, "pair_id"])
    candidate_excluded = set(candidate.loc[candidate_mask, "pair_id"])
    require(control_excluded == candidate_excluded, "exact-identity filter is asymmetric across sides")
    registry_pair_ids = set(control.loc[identity_series(control).isin(registry_hits), "pair_id"])
    closure_pair_ids = set(control.loc[identity_series(control).isin(closure_keys), "pair_id"])

    f_control = control.loc[~control_mask].copy().reset_index(drop=True)
    f_candidate = candidate.loc[~candidate_mask].copy().reset_index(drop=True)
    require(set(f_control["pair_id"]) == set(f_candidate["pair_id"]), "filtered CONTROL/Candidate pair symmetry failed")
    require(not (identity_pairs(f_control) & policy_keys), "an excluded identity remains in filtered trades")
    require(identity_pairs(f_control) <= final_identities, "filtered trade identity lies outside the final population")

    checks = {
        "source_pair_count": len(control),
        "source_identity_count": len(source_identities),
        "source_pair_symmetry": True,
        "source_pair_id_uniqueness": True,
        "source_trade_id_alignment": True,
        "source_paired_exact_pair_set": True,
        "registry_identity_count_in_raw": len(registry_hits),
        "registry_excluded_pair_count": len(registry_pair_ids),
        "registry_excluded_pair_ids": sorted(registry_pair_ids),
        "closure_identity_count": len(closure_keys),
        "closure_excluded_pair_count": len(closure_pair_ids),
        "closure_excluded_pair_ids": sorted(closure_pair_ids),
        "excluded_pair_count": len(control_excluded),
        "filtered_pair_count": len(f_control),
        "filtered_identity_count": len(identity_pairs(f_control)),
        "filtered_exact_exclusions_absent": True,
        "filtered_control_candidate_pair_symmetry": True,
    }
    return f_control, f_candidate, checks


def label_authoritative_final(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply HEAD's lifecycle certification class to the evaluation copy.

    The v02 raw predates the ``lifecycle_certification_class`` column.  The
    label follows the exact rule in ``_mark_unresolved_lifecycle``: only the
    sealed 096300 liquidation evidence is authoritative-final; any other
    unresolved lifecycle row stays remediable.
    """
    labeled = frame.copy()
    states = labeled["lifecycle_state"].fillna("").astype(str)
    source_isus = labeled["lifecycle_source_isu_cd"].fillna("").astype(str).str.upper()
    authoritative = (
        states.eq("UNRESOLVED_SETTLEMENT")
        & labeled["lifecycle_event_type"].fillna("").astype(str).eq("LIQUIDATION_UNRESOLVED")
        & source_isus.isin(runner.AUTHORITATIVE_FINAL_UNRESOLVED_SOURCE_ISUS)
        & labeled["lifecycle_evidence_id"].fillna("").astype(str).eq("KRX-LIFECYCLE-" + source_isus)
    )
    unresolved = states.isin(runner.UNRESOLVED_LIFECYCLE_STATES)
    labeled["lifecycle_certification_class"] = None
    labeled.loc[unresolved, "lifecycle_certification_class"] = runner.REMEDIABLE_UNRESOLVED
    labeled.loc[authoritative, "lifecycle_certification_class"] = runner.AUTHORITATIVE_FINAL_UNRESOLVED
    return labeled


def rename_gate_fields(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        ("p2_1_" + key[len("p3_1_"):] if key.startswith("p3_1_") else key): value
        for key, value in validation.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / SOURCE_RELATIVE_DIR)
    parser.add_argument(
        "--calendar-root",
        type=Path,
        default=ROOT,
        help="repository root that holds data/market/rolling_authority (read-only)",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / SOURCE_RELATIVE_DIR / EVALUATION_DIRNAME)
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    eval_dir = args.output_dir.resolve()
    manifest_path = source_dir / "run_manifest.json"
    require(manifest_path.is_file(), f"frozen P2-1 source manifest is missing: {manifest_path}")
    require(not eval_dir.exists(), f"refusing to overwrite existing evaluation directory: {eval_dir}")
    require(eval_dir.parent == source_dir or source_dir not in eval_dir.parents, "evaluation output must not replace source files")

    source_hashes = directory_hashes(source_dir)
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    eval_dir.mkdir(parents=True)
    stage = "INITIAL_PREFLIGHT"
    raw_checks: dict[str, Any] = {}
    population: dict[str, Any] = {}
    cert_path = eval_dir / "p2_1_raw_only_certification_v01.json"

    try:
        require(source_manifest.get("run_id") == SOURCE_RUN_ID, "source manifest run_id changed")
        require(source_manifest.get("window_id") == "P2-1", "source manifest is not P2-1")
        require(source_manifest.get("start_head") == SOURCE_START_HEAD, "source start head changed")
        require(source_manifest.get("effective_pit_sha256") == EXPECTED_PIT_SHA256, "source PIT SHA changed")
        require(source_manifest.get("status") == "COMPLETE_WITH_UNRESOLVED", "source run status changed")

        stage = "POPULATION_CONTEXT"
        context, population = build_context(args.calendar_root.resolve())
        final_identities = population["final_identities"]

        stage = "FROZEN_RAW_INTEGRITY_AND_FILTER"
        control, candidate, raw_checks = read_and_filter_raw(source_dir, final_identities)

        stage = "LIFECYCLE_CLASS_LABEL"
        control = label_authoritative_final(control)
        candidate = label_authoritative_final(candidate)
        for side, frame in (("CONTROL", control), ("Candidate", candidate)):
            labeled_pairs = sorted(
                frame.loc[
                    frame["lifecycle_certification_class"].eq(runner.AUTHORITATIVE_FINAL_UNRESOLVED),
                    "pair_id",
                ]
            )
            require(labeled_pairs == [ALLOWED_FINAL_UNRESOLVED_PAIR_ID], f"{side} authoritative-final label set: {labeled_pairs}")

        stage = "RAW_ONLY_SUMMARY_VALIDATION"
        control = control.sort_values(
            ["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort"
        ).reset_index(drop=True)
        candidate = candidate.sort_values(
            ["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort"
        ).reset_index(drop=True)
        paired = control.merge(candidate, on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one")
        cutoff_date = context.window.effective_end.strftime("%Y-%m-%d")

        validation = rename_gate_fields(runner._validate_results(control, candidate, context))
        numeric_pair_ids = runner._numeric_comparable_pair_ids(control, candidate)
        control_metrics = runner._metrics(control, performance_pair_ids=numeric_pair_ids)
        candidate_metrics = runner._metrics(candidate, performance_pair_ids=numeric_pair_ids)
        paired_metrics = runner._paired_summary(control, candidate)
        candidate_diagnostics = runner._candidate_diagnostics(control, candidate)
        matched_pair_counts = {
            **runner._matched_pair_counts(control, candidate),
            **runner._matched_pair_certification_counts(control, candidate),
        }
        ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date=cutoff_date)
        ledger_aggregates = runner._ledger_aggregates(ledger)
        ledger_reconciliation = {
            "control_metrics_match_summary": runner._nested_values_equal(ledger_aggregates["control"], control_metrics),
            "candidate_metrics_match_summary": runner._nested_values_equal(ledger_aggregates["candidate"], candidate_metrics),
            "paired_metrics_match_summary": runner._nested_values_equal(ledger_aggregates["paired"], paired_metrics),
        }
        ledger_trade_ids = ledger.set_index("pair_id")["trade_id"].astype(str).sort_index()
        validation.update(
            {
                "ledger_pair_id_unique": bool(ledger["pair_id"].is_unique),
                "ledger_pair_id_set_matches_sources": set(ledger["pair_id"]) == set(control["pair_id"]) == set(candidate["pair_id"]),
                "ledger_source_trade_id_equal_by_pair": bool(
                    ledger_trade_ids.equals(control.set_index("pair_id")["trade_id"].astype(str).sort_index())
                    and ledger_trade_ids.equals(candidate.set_index("pair_id")["trade_id"].astype(str).sort_index())
                ),
                "control_candidate_pair_id_sets_equal": set(control["pair_id"]) == set(candidate["pair_id"]),
                "control_candidate_source_trade_id_equal_by_pair": bool(
                    paired["trade_id_control"].astype(str).equals(paired["trade_id_candidate"].astype(str))
                ),
                "paired_pair_id_unique": bool(paired["pair_id"].is_unique),
                "all_ledger_aggregates_match_summary": all(ledger_reconciliation.values()),
                "terminal_numeric_symmetry": bool(
                    pd.to_numeric(paired["terminal_return_control"], errors="coerce").isna().equals(
                        pd.to_numeric(paired["terminal_return_candidate"], errors="coerce").isna()
                    )
                ),
            }
        )
        after_hashes = directory_hashes(source_dir)
        required_checks = {
            "control_candidate_pair_population_symmetry": validation["control_candidate_pair_id_sets_equal"],
            "matched_paired_exact_set": validation["ledger_pair_id_set_matches_sources"],
            "pair_id_unique": validation.get("duplicate_pair_ids") == 0
            and validation["ledger_pair_id_unique"]
            and validation["paired_pair_id_unique"],
            "source_trade_alignment": validation["ledger_source_trade_id_equal_by_pair"]
            and validation["control_candidate_source_trade_id_equal_by_pair"],
            "entry_population_parity": validation.get("entry_population_parity") is True,
            "lifecycle_gate_remediable_unresolved_zero": validation.get("p2_1_effective_remediable_unresolved_count") == 0
            and matched_pair_counts.get("matched_pairs_remediable_unresolved") == 0,
            "lifecycle_gate_symmetric": validation.get("p2_1_lifecycle_gate_control_candidate_symmetry") is True,
            "authoritative_final_allowed_class_only": sorted(
                validation.get("p2_1_authoritative_final_unresolved_pair_ids", [])
            ) == [ALLOWED_FINAL_UNRESOLVED_PAIR_ID]
            and matched_pair_counts.get("matched_pairs_authoritative_excluded") == 1,
            "unexecuted_signal_zero": validation.get("candidate_unexecuted_signal_count") == 0,
            "execution_support_missing_zero": validation.get("candidate_execution_support_missing_count") == 0,
            "candidate_overlap_zero": validation.get("candidate_overlap_count") == 0,
            "candidate_stage_asof_future_violations_zero": validation.get("candidate_stage_asof_future_violations") == 0,
            "exit_window_violations_zero": validation.get("exit_window_violations") == 0,
            "terminal_numeric_comparison_symmetry": validation["terminal_numeric_symmetry"],
            "ledger_aggregate_reconciliation_within_tolerance": validation["all_ledger_aggregates_match_summary"],
            "frozen_raw_sha256_unchanged": after_hashes == source_hashes,
        }
        require(
            all(required_checks.values()),
            f"certification gates failed: {[key for key, value in required_checks.items() if not value]}",
        )

        stage = "WRITE_SEPARATE_EVALUATION_ARTIFACTS"
        outputs = {
            "control_trades.csv": control,
            "candidate_trades.csv": candidate,
            "paired_trades.csv": paired,
            "p2_1_matched_trades.csv": ledger,
        }
        for filename, frame in outputs.items():
            frame.to_csv(eval_dir / filename, index=False, float_format="%.8f")

        exclusion_records = {
            "registry_identities": [
                {"ticker": ticker, "isu_cd": isu, **PERMANENT_IDENTITY_EXCLUSIONS[(ticker, isu)]}
                for ticker, isu in sorted(EXPECTED_REGISTRY_RAW_IDENTITIES)
            ],
            "closure_identities": [
                {"ticker": ticker, "isu_cd": isu, **policy}
                for (ticker, isu), policy in sorted(P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS.items())
            ],
        }
        population_report = {key: value for key, value in population.items() if key != "final_identities"}
        summary: dict[str, Any] = {
            "status": "COMPLETE",
            "work_id": "P2_1_RAW_ONLY_LIFECYCLE_CLOSURE_V01",
            "window_id": "P2-1",
            "source_run_id": SOURCE_RUN_ID,
            "source_head": SOURCE_START_HEAD,
            "evaluation_head": current_head,
            "runner_sha256": runner._sha256(Path(runner.__file__).resolve()),
            "closure_script_sha256": sha256(Path(__file__).resolve()),
            "strategy_ids": {"control": runner.V2_STRATEGY_ID, "candidate": runner.CANDIDATE_STRATEGY_ID},
            "window": {
                "calendar_start": context.window.window.calendar_start.strftime("%Y-%m-%d"),
                "calendar_end": context.window.window.calendar_end.strftime("%Y-%m-%d"),
                "effective_start": context.window.effective_start.strftime("%Y-%m-%d"),
                "effective_end": context.window.effective_end.strftime("%Y-%m-%d"),
                "execution_support": context.window.execution_support.strftime("%Y-%m-%d"),
            },
            "population": {
                **population_report,
                "tickers_with_entries": int(control["ticker"].nunique()),
                "control_entry_count": len(control),
                "candidate_entry_count": len(candidate),
            },
            "exclusions": exclusion_records,
            "control": control_metrics,
            "candidate": candidate_metrics,
            "paired": paired_metrics,
            "matched_pair_counts": matched_pair_counts,
            "candidate_diagnostics": candidate_diagnostics,
            "ledger": {
                "path": EVALUATION_DIRNAME + "/p2_1_matched_trades.csv",
                "row_count": int(len(ledger)),
                "aggregates_recomputed_from_full_ledger": ledger_aggregates,
                "aggregate_reconciliation": ledger_reconciliation,
                "float_tolerance_pp": runner.AGGREGATE_FLOAT_TOLERANCE_PP,
            },
            "validation": validation,
            "simulation_replay_performed": False,
            "verdict": FINAL_VERDICT,
            "certification_verdict": FINAL_VERDICT,
        }
        summary["strategy_assessment"] = runner._verdict(summary, validation)
        certification = {
            "status": "PASS",
            "verdict": FINAL_VERDICT,
            "window_id": "P2-1",
            "source_run_id": SOURCE_RUN_ID,
            "source_head": SOURCE_START_HEAD,
            "evaluation_head": current_head,
            "population": population_report,
            "raw_integrity": raw_checks,
            "exclusions": exclusion_records,
            "allowed_authoritative_final_unresolved_pair_ids": [ALLOWED_FINAL_UNRESOLVED_PAIR_ID],
            "required_checks": required_checks,
            "simulation_replay_performed": False,
            "ticker_replay_performed": False,
            "recovery_replay_performed": False,
            "sample_replay_performed": False,
            "source_raw_files_modified": False,
            "source_sha256_before": source_hashes,
            "source_sha256_after": after_hashes,
            "source_sha256_preserved": after_hashes == source_hashes,
            "summary_path": EVALUATION_DIRNAME + "/summary.json",
        }
        manifest = {
            "run_id": EVALUATION_RUN_ID,
            "window_id": "P2-1",
            "source_run_id": SOURCE_RUN_ID,
            "source_head": SOURCE_START_HEAD,
            "evaluation_head": current_head,
            "effective_pit_sha256": context.authority.pit_sha256,
            "certification_status": FINAL_VERDICT,
            "simulation_replay_performed": False,
            "outputs": [*outputs, "summary.json", cert_path.name, "run_manifest.json"],
        }
        runner._json_write(eval_dir / "summary.json", summary)
        runner._json_write(cert_path, certification)
        runner._json_write(eval_dir / "run_manifest.json", manifest)
        print(json.dumps({
            "status": "PASS",
            "verdict": FINAL_VERDICT,
            "matched_pairs": matched_pair_counts.get("matched_pairs_total"),
            "numeric_comparable": matched_pair_counts.get("matched_pairs_numeric_comparable"),
            "final_tickers": population["final_ticker_count"],
            "source_sha256_preserved": True,
            "evaluation_dir": str(eval_dir),
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        after_hashes = directory_hashes(source_dir)
        failure = {
            "status": "CHECK_REQUIRED",
            "verdict": "CHECK_REQUIRED",
            "stage": stage,
            "reason": f"{type(exc).__name__}: {exc}",
            "window_id": "P2-1",
            "source_run_id": SOURCE_RUN_ID,
            "evaluation_head": current_head,
            "simulation_replay_performed": False,
            "source_sha256_before": source_hashes,
            "source_sha256_after": after_hashes,
            "source_sha256_preserved": after_hashes == source_hashes,
            "raw_integrity_so_far": raw_checks,
            "population_so_far": {key: value for key, value in population.items() if key != "final_identities"},
        }
        runner._json_write(cert_path, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2, default=str))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
