"""Shared explicit frozen-evidence hash helpers.

TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_03: several Phase 13 historical
freeze tests used `git diff --quiet OLD_BASE -- protected_paths` (sometimes on
whole directories) to check "has frozen evidence been tampered with". That
form also fails on any *later, legitimate* repository change under the same
path (docs path migrations, newly added research artifacts, ...), which is a
false positive unrelated to frozen-evidence tampering.

This module holds small, explicit sha256 helpers so each test can assert
"this specific file's content is exactly X" instead of "nothing under this
path/directory changed since some historical commit". Content that already
has an authoritative hash elsewhere (Pattern A Score/Stage in
`trend_scanner.validation.pattern_a_final_closure.EXPECTED_FROZEN_HASHES`) is
reused here, not re-hardcoded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Pattern A core source. pattern_a_evaluator.py / pattern_a_feature_set.py have
# no separate frozen-hash authority elsewhere in the repo (only
# pattern_a_score.py / pattern_a_stage.py do, via EXPECTED_FROZEN_HASHES) --
# their current-HEAD content is recorded here directly. Both are confirmed
# unchanged (pattern_a_evaluator.py) or docstring-path-only changed
# (pattern_a_feature_set.py, Docs IA reorg commit beafd30) relative to every
# relevant historical Phase 13 BASE as of FIX_03.
PATTERN_A_EVALUATOR_SHA256 = "678bef9e9a786bf8c6321d7ad8f1f42c002a87c4bed3174843c9cadc92a0c0a7"
PATTERN_A_FEATURE_SET_SHA256 = "be0d39325e94f9f436abb740202d2cf9b19f22772c208d2bd6a5164d0011eebd"

# scripts/evaluate_pattern_a_fast_oos_v01.py: Docs IA reorganization (commit
# beafd30) updated only the in-file `DOC = Path(...)` docstring-reference
# constant to the new canonical docs path. No evaluation/strategy logic
# changed (verified via `git diff`). Frozen at current HEAD content.
EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256 = "466632ba6fb4f4b0b5701e7f8b37fc0b3a297cd50b543d9f86ed2854ca0b068d"

# Unchanged since their respective historical Phase 13 BASE commits.
RESEARCH_LEAD_TIME_FAILURE_SCRIPT_SHA256 = "98a07bc46b7a2cf8b03f081de2ecbd3cd585b8703255fe65000df221bad21209"
RESEARCH_SCORE_STAGE_PROTOTYPE_SCRIPT_SHA256 = "b56134b1242bbbce1fd78db63661afc173481104f5aa0b74d8b3bf4c6c34adfd"
PREPARE_INVESTABLE_OOS_SCRIPT_SHA256 = "aa96ed3cd25a8618dd0e3271834ffcb166a598a64f1be192ac7d1db5b819f4b0"

# Phase 10 canonical PIT market-cap snapshots (artifacts/investability/source/).
# Not part of the artifacts/investability/history/ provenance-tracked set
# (which is already row-level sha256 sealed elsewhere) -- these two files had
# no explicit hash guard anywhere before FIX_03.
SOURCE_MARKET_CAP_20250131_SHA256 = "32e88ac6ec85da881b48ebea70aae4098e8bb3130fc3223d5594c7eaa682eb83"
SOURCE_MARKET_CAP_20260814_SHA256 = "c45a496d0a5bb38ea4d4350d3a0a1db8cc141887c22df1ad4ca702a75722b55d"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_file_sha256(path: Path, expected_sha256: str) -> None:
    actual = sha256_of(path)
    assert actual == expected_sha256, f"{path}: expected sha256 {expected_sha256}, got {actual}"
