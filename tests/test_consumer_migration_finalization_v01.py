"""Consumer Migration Finalization V01 structural and loader gates."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader


ROOT = Path(__file__).resolve().parents[1]
FINALIZATION_SCRIPT_PATH = ROOT / "scripts/run_consumer_migration_finalization_v01.py"


def _load_finalization_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "consumer_migration_finalization_v01_under_test", FINALIZATION_SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scan_row_to_dict_string_keys() -> set[str]:
    """Extract the literal string keys of ``PatternAUniverseScanRow.to_dict()``.

    Uses the AST rather than instantiating the dataclass, since building a
    real ``PatternAUniverseScanRow`` requires populating well over a hundred
    required fields.
    """
    source = (ROOT / "src/trend_scanner/scanner/full_universe_scanner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_def = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "PatternAUniverseScanRow")
    to_dict_fn = next(node for node in ast.walk(class_def) if isinstance(node, ast.FunctionDef) and node.name == "to_dict")
    dict_literal = next(node for node in ast.walk(to_dict_fn) if isinstance(node, ast.Dict))
    keys = set()
    for key_node in dict_literal.keys:
        assert isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)
        keys.add(key_node.value)
    return keys


def test_repository_loader_preserves_compact_provenance_without_large_audit() -> None:
    class FakeRepository:
        def get_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            frame = pd.DataFrame(
                {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0], "trading_value": [1.0]},
                index=pd.DatetimeIndex(["2026-08-14"]),
            )
            frame.attrs["session_projection_audit"] = {
                "adjusted_only_dates": ["2020-01-01"] * 1000,
                "raw_only_dates": ["2020-01-02"] * 1000,
                "explicit_placeholder_projection_count": 2,
                "explicit_known_gap_exclusion_count": 3,
                "explicit_outside_identity_lifecycle_exclusion_count": 4,
                "explicit_adjusted_source_nonusable_exclusion_count": 5,
                "explicit_analytic_invalid_exclusion_count": 6,
                "silent_inner_drop_count": 0,
            }
            return frame

    loaded = RepositoryV2DailyLoader(FakeRepository(), end="2026-08-14").load("005930")
    assert loaded is not None
    assert loaded.attrs["data_authority"] == "MarketDataRepositoryV2"
    assert "session_projection_audit" not in loaded.attrs
    assert loaded.attrs["session_projection_summary"] == {
        "adjusted_only_count": 1000,
        "raw_only_count": 1000,
        "explicit_exclusion_count": 20,
        "silent_inner_drop_count": 0,
    }


def test_production_entrypoints_expose_repository_v2_path() -> None:
    scanner = ast.parse((ROOT / "src/trend_scanner/scanner/full_universe_scanner.py").read_text(encoding="utf-8"))
    report = ast.parse((ROOT / "src/trend_scanner/reporting/stock_report.py").read_text(encoding="utf-8"))
    scanner_fn = next(node for node in ast.walk(scanner) if isinstance(node, ast.FunctionDef) and node.name == "scan_pattern_a_universe")
    report_fn = next(node for node in ast.walk(report) if isinstance(node, ast.FunctionDef) and node.name == "generate_stock_report")
    assert any(arg.arg == "repository" for arg in scanner_fn.args.args)
    assert any(arg.arg == "repository" for arg in report_fn.args.args)
    # ROLLING_MARKET_DATA_AUTHORITY_FINALIZATION_V01 BLOCKER-1: this CLI's --as-of is caller-supplied
    # and can be a live date, so it now goes through build_production_repository_v2 (unconditional
    # rolling-authority boundary enforcement) instead of the opt-in build_repository_v2.
    assert "build_production_repository_v2" in (ROOT / "scripts/run_pattern_a_universe_scanner.py").read_text(encoding="utf-8")
    assert "RepositoryV2DailyLoader" in (ROOT / "scripts/evaluate_pattern_a_fast_core_v02_reentry.py").read_text(encoding="utf-8")
    assert "RepositoryV2DailyLoader" in (ROOT / "scripts/evaluate_julia_strategy_v00_comparison.py").read_text(encoding="utf-8")


def test_finalization_runner_is_offline_and_frozen() -> None:
    source = (ROOT / "scripts/run_consumer_migration_finalization_v01.py").read_text(encoding="utf-8")
    assert 'AS_OF = "2026-08-14"' in source
    assert "offline_network_guard" in source
    assert "from trend_scanner.data.cache import ParquetCache" not in source


def test_finalization_runner_has_observable_shadow_and_accounting_gates() -> None:
    source = (ROOT / "scripts/run_consumer_migration_finalization_v01.py").read_text(encoding="utf-8")
    for marker in (
        "progress_callback",
        "semantic_equivalence.json",
        "session_mismatch_accounting.json",
        "determinism.json",
        "{run_name}_pattern_a.json",
        "{run_name}_stock_report.json",
        "without context vs PrecomputedTickerContext",
    ):
        assert marker in source


def test_fastcore_exposes_explicit_legacy_equivalence_path() -> None:
    source = (ROOT / "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py").read_text(encoding="utf-8")
    assert "use_precomputed_context" in source
    assert "snapshot_context" in source


def test_finalization_temporal_gate_no_longer_uses_date_substring_match() -> None:
    """The RUN1 false-positive root cause (a broad ``"date" in key`` substring
    check) must not reappear -- the fix is an explicit, schema-aware
    allowlist."""
    source = FINALIZATION_SCRIPT_PATH.read_text(encoding="utf-8")
    assert '"date" in str(key).lower()' not in source
    assert "PATTERN_A_TEMPORAL_FIELDS" in source


def test_finalization_temporal_allowlist_matches_scan_row_schema() -> None:
    """``PATTERN_A_TEMPORAL_FIELDS`` must track ``PatternAUniverseScanRow``'s
    actual date-bearing fields exactly, so the allowlist cannot silently
    drift stale as the scan row schema evolves (missing a real date field
    would reintroduce false negatives; a stray extra field would reintroduce
    false positives)."""
    module = _load_finalization_module()
    schema_keys = _scan_row_to_dict_string_keys()
    schema_date_fields = {key for key in schema_keys if "date" in key.lower()} - {"candidate_state"}
    assert module.PATTERN_A_TEMPORAL_FIELDS == schema_date_fields


@pytest.fixture()
def count_rows_after_frozen_as_of():
    module = _load_finalization_module()
    return module._count_rows_after_frozen_as_of


def test_candidate_state_is_not_treated_as_a_temporal_field(count_rows_after_frozen_as_of) -> None:
    """Test A: ``candidate_state`` (a stage label, e.g. "blocked"/"watch")
    must not be counted as a temporal field even though "date" is a
    substring of "candidate"."""
    rows = [{"ticker": "000020", "candidate_state": "blocked"}]
    assert count_rows_after_frozen_as_of(rows, "2026-08-14") == 0


def test_real_temporal_field_within_frozen_as_of_is_not_a_violation(count_rows_after_frozen_as_of) -> None:
    """Test B: a genuine temporal field at or before AS_OF must not count."""
    rows = [{"ticker": "000020", "cache_last_date": "2026-08-14"}]
    assert count_rows_after_frozen_as_of(rows, "2026-08-14") == 0


def test_real_temporal_field_after_frozen_as_of_is_a_violation(count_rows_after_frozen_as_of) -> None:
    """Test C: a genuine temporal field after AS_OF must be caught -- the
    fix must not introduce a false negative."""
    rows = [{"ticker": "000020", "cache_last_date": "2026-08-15"}]
    assert count_rows_after_frozen_as_of(rows, "2026-08-14") == 1


def test_non_temporal_key_with_date_substring_is_ignored(count_rows_after_frozen_as_of) -> None:
    """Test D: a synthetic key that happens to contain the substring "date"
    but is not a real temporal field must not be counted, even when its
    value would lexicographically exceed AS_OF."""
    rows = [{"ticker": "000020", "mandate_status": "zzz_after_as_of_string"}]
    assert count_rows_after_frozen_as_of(rows, "2026-08-14") == 0


def test_population_wide_false_positive_regression(count_rows_after_frozen_as_of) -> None:
    """Direct regression for the RUN1 finding: 2,528 rows each carrying only
    a non-temporal ``candidate_state`` must report zero violations, not a
    count equal to the population."""
    rows = [{"ticker": f"{i:06d}", "candidate_state": "watch"} for i in range(2528)]
    assert count_rows_after_frozen_as_of(rows, "2026-08-14") == 0
