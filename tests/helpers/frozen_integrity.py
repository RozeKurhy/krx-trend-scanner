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

# Scripts: Artifacts IA reorganization updated in-file artifact paths to canonical IA locations.
# Frozen at current HEAD content.
EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256 = "0bd8188846958d7619eb4451b00a1ac14fa68af0b40059bb0c489fbdd76edb65"
RESEARCH_LEAD_TIME_FAILURE_SCRIPT_SHA256 = "becf44a04437885e468e08863cf6d8fdbe401309f44367b4fbaae1be40fd921a"
RESEARCH_SCORE_STAGE_PROTOTYPE_SCRIPT_SHA256 = "618501296768d1c8aa0670d08dbf8b2ec61b514c1e800424eca53e3d6dcdcaae"
PREPARE_INVESTABLE_OOS_SCRIPT_SHA256 = "039ffca48bb45373fb02cb989fb1c3d0a43f8808e988fba25e63bd88d832af8e"

# Phase 10 canonical PIT market-cap snapshots (artifacts/patterns/pattern_a/production/investability/source/).
# Not part of the artifacts/patterns/pattern_a/validation/investability_history/ provenance-tracked set
# (which is already row-level sha256 sealed elsewhere) -- these two files had
# no explicit hash guard anywhere before FIX_03.
SOURCE_MARKET_CAP_20250131_SHA256 = "32e88ac6ec85da881b48ebea70aae4098e8bb3130fc3223d5594c7eaa682eb83"
SOURCE_MARKET_CAP_20260814_SHA256 = "c45a496d0a5bb38ea4d4350d3a0a1db8cc141887c22df1ad4ca702a75722b55d"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_file_sha256(path: Path, expected_sha256: str) -> None:
    actual = sha256_of(path)
    assert actual == expected_sha256, f"{path}: expected sha256 {expected_sha256}, got {actual}"
