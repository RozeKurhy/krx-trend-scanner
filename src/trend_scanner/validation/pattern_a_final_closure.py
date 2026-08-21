"""Deterministic Pattern A Final Production Closure Generator and Evidence Audit Suite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.patterns.pattern_a_stage import (
    classify_pattern_a_stage,
    EPISODE_PEAK_AVG_CHG,
    EPISODE_BREAK_MA24_SLOPE,
    EPISODE_BREAK_RANGE_POSITION,
)
from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS

_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}

HISTORICAL_SCANNER_FROZEN_COMMIT: str = "13ab6f416a0de77e89c7e0412467eb393e07c6dc"
HISTORICAL_FROZEN_SCANNER_HASH: str = "6191be6f84aca63f7f3a813c94b272582cacb517adf15dd9ceb74c357c6d8e60"

# Frozen contract SHA256 hashes of core Pattern A production modules (Strictly Decoupled & Immutable)
EXPECTED_FROZEN_HASHES = {
    # DOCS_INFORMATION_ARCHITECTURE_REORGANIZATION_V01: only in-file docstring/
    # comment references to moved docs/ paths were updated (e.g.
    # docs/validation/pattern_a_stage.md -> docs/patterns/pattern_a/validation/
    # stage_label_audit_freeze.md). No Stage/Score rule, threshold, or formula
    # changed — verified via `git diff` containing only docs-path substitutions.
    "pattern_a_stage.py": "af881b94d33314855c2bf1a0b516a7e61a0b511fed5ae3597743f86fc247a435",
    # DOCS_INFORMATION_ARCHITECTURE_REORGANIZATION_FIX_01: docstring/comment
    # references to docs/patterns/pattern_a/archive/legacy_full_history.md
    # were updated to docs/patterns/pattern_a/spec/production_authority.md
    # (the archive/ location was a structural contradiction — this doc is
    # the current Score/Stage authority, not a superseded historical
    # document). No Stage/Score rule, threshold, or formula changed —
    # verified via `git diff` containing only docs-path substitutions.
    "pattern_a_score.py": "5b9d1ccc84901609f9fea4db66e9ef7ff783e7f528f63febcfb741bf36fdd8d4",
    # Phase 13 added only PIT-truncated raw monthly/weekly frame exposure for
    # research. FeatureRow construction and Pattern A score/stage semantics
    # remain the frozen production behavior.
    # fix(pit) b5228b5/b9c837f (KRX actual market month-end completed-period
    # authority): _drop_incomplete_current_month만 calendar-month-end 근사에서
    # 실제 KRX 거래소 캘린더(MarketCalendarAuthority) 기준으로 교체됨. 검증됨:
    # Pattern A Stage/Score semantic 변경 없음, build_feature_row 미변경,
    # PIT/no-lookahead 유지(fail-closed 강화만 추가).
    "historical_snapshot.py": "793014cbf434acadafcc59b1ae9fc50b59980178c1aeba71bc39d6d9f8a3d250",
}


def compute_file_sha256(filepath: Path) -> str:
    """Compute sha256 hash of a file."""
    if not filepath.exists():
        return ""
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


def audit_score_stage_independence(repo_root: Path, cache: ParquetCache) -> bool:
    """Explicitly verify that Score and Stage remain decoupled."""
    daily = cache.load("003100")
    if daily is None or daily.empty:
        return False
    snap = build_historical_snapshot("003100", "선광", daily, "2024-12-31", include_incomplete_periods=False)
    # 1. Stage does not raise without score
    stage_res = classify_pattern_a_stage(snap)
    # 2. Score does not raise without stage
    score_res = score_pattern_a(snap.features)
    # 3. Score result contains independent numeric score
    return (
        isinstance(stage_res.stage, PatternAStage)
        and isinstance(score_res.pattern_a_score, (int, float))
    )


def run_pattern_a_final_closure_audit(
    repo_root: Path,
    as_of: str = "2026-08-14",
    run_live_scanner: bool = True,
) -> dict[str, Any]:
    """Execute live verification of all 10 closure gates and output pattern_a_final_closure.json."""
    cache_dir = repo_root / "data" / "raw" / "stocks"
    cache = ParquetCache(base_dir=cache_dir)
    out_dir = repo_root / "artifacts" / "patterns" / "pattern_a" / "validation" / "closure"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Source Identity & Constant Audit
    stage_constants_pass = (
        EPISODE_PEAK_AVG_CHG == 0.30
        and EPISODE_BREAK_MA24_SLOPE == -0.045
        and EPISODE_BREAK_RANGE_POSITION == 0.20
    )

    source_audit_records = {}
    all_hashes_match = True
    for fname, expected_hash in EXPECTED_FROZEN_HASHES.items():
        if fname in ("pattern_a_stage.py", "pattern_a_score.py"):
            fpath = repo_root / "src/trend_scanner/patterns" / fname
        elif fname == "historical_snapshot.py":
            fpath = repo_root / "src/trend_scanner/validation" / fname
        else:
            fpath = repo_root / fname

        actual_hash = compute_file_sha256(fpath)
        is_match = (actual_hash == expected_hash)
        if not is_match:
            all_hashes_match = False
        source_audit_records[fname] = {
            "expected_frozen_hash": expected_hash,
            "actual_head_hash": actual_hash,
            "match": is_match,
        }

    # Record scanner provenance separately (Phase 8 Historical Frozen vs Phase 10C Downstream Integration)
    scanner_fpath = repo_root / "src/trend_scanner/scanner/full_universe_scanner.py"
    current_scanner_hash = compute_file_sha256(scanner_fpath)
    source_audit_records["full_universe_scanner.py"] = {
        "historical_frozen_hash": HISTORICAL_FROZEN_SCANNER_HASH,
        "historical_frozen_commit": HISTORICAL_SCANNER_FROZEN_COMMIT,
        "current_downstream_scanner_hash": current_scanner_hash,
        "downstream_enriched": True,
    }

    source_identity_pass = all_hashes_match and stage_constants_pass

    # 2. Score / Stage Independence Audit
    score_stage_independence_pass = audit_score_stage_independence(repo_root, cache)

    # 3. Calibration 46 Live Evaluation
    calib_exact = 0
    calib_adj = 0
    calib_sev = 0
    for s in PATTERN_A_STAGE_LABELS:
        daily = cache.load(s.ticker)
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        res = classify_pattern_a_stage(snap)
        diff = abs(_STAGE_ORDER[res.stage] - _STAGE_ORDER[s.audited_stage])
        if diff == 0:
            calib_exact += 1
        elif diff == 1:
            calib_adj += 1
        else:
            calib_sev += 1

    calibration_pass = (calib_exact == 38 and calib_adj == 5 and calib_sev == 3)

    # 4. OOS 35 Live Evaluation
    oos_exact = 0
    oos_adj = 0
    oos_sev = 0
    for s in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(s.ticker)
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        res = classify_pattern_a_stage(snap)
        diff = abs(_STAGE_ORDER[res.stage] - _STAGE_ORDER[s.manual_stage])
        if diff == 0:
            oos_exact += 1
        elif diff == 1:
            oos_adj += 1
        else:
            oos_sev += 1

    oos_pass = (oos_exact == 24 and oos_adj == 10 and oos_sev == 1)

    # 5. 079550 LIG넥스원 Dynamic Lookup & Known Limitation Audit
    # Dynamically find audited ground truth from PATTERN_A_STAGE_LABELS
    spec_079550 = next(
        (s for s in PATTERN_A_STAGE_LABELS if s.ticker == "079550" and s.snapshot_date == "2023-12-31"),
        None,
    )
    lig_audited_truth = spec_079550.audited_stage.value if spec_079550 else "unknown"

    daily_lig = cache.load("079550")
    snap_lig_2021 = build_historical_snapshot("079550", "LIG넥스원", daily_lig, "2021-12-31", include_incomplete_periods=False)
    snap_lig_2023 = build_historical_snapshot("079550", "LIG넥스원", daily_lig, "2023-12-31", include_incomplete_periods=False)
    res_lig_2021 = classify_pattern_a_stage(snap_lig_2021)
    res_lig_2023 = classify_pattern_a_stage(snap_lig_2023)

    lig_prod_output = res_lig_2023.stage.value if res_lig_2023.stage else "unknown"
    frozen_stage_behavior_reproduction_pass = (
        res_lig_2021.stage == PatternAStage.PROGRESSED
        and res_lig_2023.stage == PatternAStage.EARLY_TREND
    )
    lifecycle_known_limitation_preserved = (
        lig_audited_truth == "progressed"
        and lig_prod_output == "early_trend"
        and frozen_stage_behavior_reproduction_pass
    )

    # 6. Phase8 Scanner Live Reproduction & Candidate Identity Diff
    frozen_csv_path = repo_root / "artifacts/patterns/pattern_a/validation/chart_review/pattern_a_candidate_manual_review_20260814.csv"
    df_frozen = pd.read_csv(frozen_csv_path, dtype={"ticker": str})
    df_frozen["ticker"] = df_frozen["ticker"].str.zfill(6)
    frozen_cand_dict = dict(zip(df_frozen["ticker"], df_frozen["official_stage"]))

    if run_live_scanner:
        scan_res = scan_pattern_a_universe(cache=cache_dir, as_of=as_of)
        univ_count = scan_res.summary.official_common_total
        cand_rows = [r for r in scan_res.rows if r.candidate_state == PatternACandidateState.CANDIDATE]
        cand_count = len(cand_rows)
        trans_count = sum(1 for r in cand_rows if r.official_stage and r.official_stage.value == "transition")
        early_count = sum(1 for r in cand_rows if r.official_stage and r.official_stage.value == "early_trend")
        live_cand_dict = {r.ticker: r.official_stage.value for r in cand_rows if r.official_stage}

        phase8_reproduction_pass = (
            univ_count == 2528
            and cand_count == 180
            and trans_count == 168
            and early_count == 12
        )
    else:
        # Fast mode: do not forge pass
        univ_count = 0
        cand_count = 0
        trans_count = 0
        early_count = 0
        live_cand_dict = {}
        phase8_reproduction_pass = False

    frozen_keys = set(frozen_cand_dict.keys())
    live_keys = set(live_cand_dict.keys())

    missing_tickers = sorted(list(frozen_keys - live_keys))
    extra_tickers = sorted(list(live_keys - frozen_keys))
    stage_changed = sorted([
        t for t in (frozen_keys & live_keys)
        if frozen_cand_dict[t] != live_cand_dict[t]
    ])

    identity_diff_pass = (
        run_live_scanner
        and len(missing_tickers) == 0
        and len(extra_tickers) == 0
        and len(stage_changed) == 0
    )

    # 7. Fail-Closed Final Decision Derivation
    all_gates_pass = (
        source_identity_pass
        and score_stage_independence_pass
        and calibration_pass
        and oos_pass
        and frozen_stage_behavior_reproduction_pass
        and lifecycle_known_limitation_preserved
        and phase8_reproduction_pass
        and identity_diff_pass
    )

    if all_gates_pass:
        final_production_decision = "KEEP_CURRENT_PRODUCTION"
        pattern_a_stage_research_status = "CLOSED"
    else:
        final_production_decision = "HOLD"
        pattern_a_stage_research_status = "HOLD_PENDING_GATE_FAILURE"

    # 8. Assemble Closure Payload
    payload = {
        "closure_version": "v0.1_final_production_closure",
        "closure_date": "2026-08-16",
        "source_checkpoint": "b4478449465f46511d23df62f2928130f9ac364d",
        "stage_production_version": "v0.1",
        "stage_frozen_commit": "43ee01ca086c5d33bbf195bed67e161f5a315bf5",
        "score_production_version": "v0.2",
        "scanner_frozen_commit": "13ab6f416a0de77e89c7e0412467eb393e07c6dc",
        "source_integrity": {
            "stage_constants_pass": stage_constants_pass,
            "source_identity_pass": source_identity_pass,
            "source_audit": source_audit_records,
        },
        "score_stage_independence_pass": score_stage_independence_pass,
        "calibration_exact": calib_exact,
        "calibration_adjacent": calib_adj,
        "calibration_severe": calib_sev,
        "calibration_pass": calibration_pass,
        "oos_exact": oos_exact,
        "oos_adjacent": oos_adj,
        "oos_severe": oos_sev,
        "oos_pass": oos_pass,
        "scanner_universe_count": univ_count,
        "scanner_candidate_count": cand_count,
        "scanner_transition_count": trans_count,
        "scanner_early_count": early_count,
        "phase8_reproduction_pass": phase8_reproduction_pass,
        "candidate_identity_diff": {
            "missing_tickers": missing_tickers,
            "extra_tickers": extra_tickers,
            "stage_changed_tickers": stage_changed,
            "identity_diff_pass": identity_diff_pass,
        },
        "frozen_stage_behavior_reproduction_pass": frozen_stage_behavior_reproduction_pass,
        "lifecycle_known_limitation_preserved": lifecycle_known_limitation_preserved,
        "079550_audited_truth": lig_audited_truth,
        "079550_production_output": lig_prod_output,
        "all_hard_gates_pass": all_gates_pass,
        "known_limitation_count": 8,
        "stage_v02_status": "HOLD / NOT PRODUCTION",
        "stage_v03_status": "CLOSED",
        "stage_v04_status": "CLOSED",
        "final_production_decision": final_production_decision,
        "pattern_a_stage_research_status": pattern_a_stage_research_status,
        "next_phase": "SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW",
    }

    (out_dir / "pattern_a_final_closure.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_pattern_a_final_closure_audit(repo_root, run_live_scanner=True)
    print("Pattern A Final Production Closure Audit generated successfully with fail-closed gates.")
