"""Regression coverage for the saved V08 Alignment web candidate parity."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREPUBLICATION_WEB = (
    ROOT
    / "artifacts/strategies/a_fast_core_v2/research/"
    / "fast_core_v2_web_prepublication_final_audit_v01/run_20261014/candidate/web"
)
V08_REPORTS = (
    ROOT
    / "artifacts/strategies/a_fast_core_v2/research/"
    / "fast_core_v2_phase4b_source_bound_replay_v08/run_20261014/staging_1459/json"
)
SCRIPT_PATH = ROOT / "scripts/rebuild_fast_web_canonical_alignment_staging_v01.py"
FAST_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "rebuild_fast_web_canonical_alignment_staging_v01_test", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load FAST web alignment staging runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def saved_v08_candidate(tmp_path_factory):
    reports = sorted(V08_REPORTS.glob("*.json")) if V08_REPORTS.is_dir() else []
    stocks_dir = PREPUBLICATION_WEB / "stocks"
    if len(reports) != 1459 or not (PREPUBLICATION_WEB / "stock-index.json").is_file():
        pytest.skip("saved V08 and prepublication candidate artifacts are not available")
    if not stocks_dir.is_dir() or not (PREPUBLICATION_WEB / "strategy-monitor.json").is_file():
        pytest.skip("saved prepublication web candidate is incomplete")

    runner = _load_runner()
    stage_root = tmp_path_factory.mktemp("fast-web-alignment-parity")
    web_root = stage_root / "web"
    web_root.mkdir()
    (web_root / "stocks").symlink_to(stocks_dir, target_is_directory=True)
    source_json = stage_root / "reports" / "20261011" / "json"
    source_json.parent.mkdir(parents=True)
    source_json.symlink_to(V08_REPORTS, target_is_directory=True)

    index = runner.read_json(PREPUBLICATION_WEB / "stock-index.json")
    monitor = runner.read_json(PREPUBLICATION_WEB / "strategy-monitor.json")
    old_monitor = runner.read_json(ROOT / "web/data/strategy-monitor.json")
    return runner, stage_root, index, monitor, old_monitor


def test_saved_v08_candidate_has_exact_423_trade_and_25_open_parity(saved_v08_candidate):
    runner, stage_root, index, monitor, old_monitor = saved_v08_candidate
    result = runner._verify_three_way_parity(
        stage_root, "2026-10-11", "2026-10-08", index, monitor, old_monitor
    )

    assert result["source_report_trade_rows"] == 423
    assert result["web_report_trade_rows"] == 423
    assert result["strategy_monitor_trade_rows"] == 423
    assert result["report_open_positions"] == 25
    assert result["monitor_open_positions"] == 25
    assert result["trade_key_and_values_mismatches"] == 0
    assert result["open_key_and_values_mismatches"] == 0
    assert result["common_report_scope_count"] == 1459
    assert result["fast_strategy_row_count"] == 1
    assert result["b_select_unchanged"] is True
    assert result["julia_unchanged"] is True


def test_saved_v08_candidate_rejects_an_open_exit_reason_value_mismatch(saved_v08_candidate):
    runner, stage_root, index, monitor, old_monitor = saved_v08_candidate
    changed_monitor = copy.deepcopy(monitor)
    fast_row = next(row for row in changed_monitor["strategies"] if row.get("id") == FAST_ID)
    open_trade = next(
        trade for trade in fast_row["trade_history"]
        if trade.get("trade_status") == "OPEN_AT_CUTOFF"
    )
    open_trade["exit_reason"] = "INTENTIONAL_PARITY_MISMATCH"

    with pytest.raises(ValueError, match="trade key or field parity failed"):
        runner._verify_three_way_parity(
            stage_root, "2026-10-11", "2026-10-08", index, changed_monitor, old_monitor
        )


def test_cj_cgv_staging_fill_requires_exact_next_krx_session():
    runner = _load_runner()
    expected_trade = {
        "trade_id": "079160_01",
        "exit_signal_date": "2016-09-30",
        "exit_execution_date": "2016-10-04",
        "exit_price": 52982.0,
        "return_pct": 41.21,
        "trade_status": "REALIZED",
    }

    runner._validate_cj_execution_contract("079160", [expected_trade])

    shifted = {**expected_trade, "exit_execution_date": "2016-10-05", "exit_price": 53489.0}
    with pytest.raises(ValueError, match="CJ_CGV_EXACT_SESSION_FILL_UNVERIFIED"):
        runner._validate_cj_execution_contract("079160", [shifted])


def test_relative_staging_parent_resolves_from_repository_root():
    runner = _load_runner()

    assert runner._rooted_path(Path("artifacts/staging")) == ROOT / "artifacts/staging"
    assert runner._rooted_path(ROOT / "artifacts/staging") == ROOT / "artifacts/staging"


def test_historical_replay_uses_certified_factory_without_current_identity_clamp(monkeypatch):
    runner = _load_runner()
    repository = object()
    calls = []

    def build_repository(repo_root, *, end):
        calls.append((repo_root, end))
        return repository

    class Loader:
        def __init__(self, actual_repository, *, end, historical_identity):
            self.repository = actual_repository
            self.end = end
            self.historical_identity = historical_identity

    monkeypatch.setattr(runner, "build_production_repository_v2", build_repository)
    monkeypatch.setattr(runner, "RepositoryV2DailyLoader", Loader)

    actual_repository, loader = runner._build_historical_replay_inputs(
        "2026-10-08",
        "2026-10-11",
    )

    assert calls == [(ROOT, "2026-10-08")]
    assert actual_repository is repository
    assert loader.repository is repository
    assert loader.end == "2026-10-11"
    assert loader.historical_identity is True
