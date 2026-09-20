"""Focused contract tests for the Phase 4A scanner CLI entrypoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_pattern_a_universe_scanner.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("phase4a_scanner_runner", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary() -> SimpleNamespace:
    return SimpleNamespace(
        official_common_total=2,
        scan_target_count=2,
        rows_emitted=2,
        cache_present_count=2,
        cache_missing_count=0,
        raw_ready_count=2,
        score_ready_count=2,
        stage_ready_count=2,
        evaluator_ready_count=2,
        momentum_current_ready_count=2,
        momentum_1m_ready_count=2,
        momentum_3m_ready_count=2,
        momentum_6m_ready_count=2,
        scanner_error_count=0,
        stage_distribution={},
        candidate_state_distribution={},
        score_distribution={"count": 2, "mean": 1.0, "median": 1.0, "min": 1.0, "max": 1.0, "q25": 1.0, "q75": 1.0},
    )


def test_parse_args_requires_explicit_as_of() -> None:
    module = _load_runner_module()

    with pytest.raises(SystemExit) as exc_info:
        module.parse_args([])

    assert exc_info.value.code == 2


def test_reference_market_date_uses_target_when_target_is_trading_day() -> None:
    module = _load_runner_module()
    calendar = SimpleNamespace(
        trading_dates=pd.DatetimeIndex(["2026-09-16", "2026-09-17"])
    )

    assert module.resolve_reference_market_date("2026-09-17", calendar) == "2026-09-17"


def test_reference_market_date_preserves_saturday_target_and_uses_prior_friday() -> None:
    module = _load_runner_module()
    calendar = SimpleNamespace(
        trading_dates=pd.DatetimeIndex(["2026-09-10", "2026-09-11"])
    )

    assert module.resolve_reference_market_date("2026-09-12", calendar) == "2026-09-11"


@pytest.mark.parametrize(
    ("calendar", "reason"),
    [
        (None, "ROLLING_PRODUCTION_CALENDAR_UNAVAILABLE"),
        (SimpleNamespace(trading_dates=pd.DatetimeIndex(["2026-09-14"])), "NO_DATE_AT_OR_BEFORE"),
    ],
)
def test_reference_market_date_fails_closed_without_eligible_authority(
    calendar: object | None,
    reason: str,
) -> None:
    module = _load_runner_module()

    with pytest.raises(RuntimeError, match=reason):
        module.resolve_reference_market_date("2026-09-12", calendar)


def test_full_common_validation_rejects_scanner_errors() -> None:
    module = _load_runner_module()
    summary = _summary()
    summary.scanner_error_count = 1

    with pytest.raises(RuntimeError, match="FULL_COMMON_SCAN_SCANNER_ERRORS:1"):
        module.validate_full_common_scan(summary, is_full_common_scan=True)


def test_runner_wires_selected_phase3_membership_and_repository_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_runner_module()
    target = "2026-09-17"
    selected_path = ROOT / "data/market/sector_membership/v01/sector_membership_20260917.parquet"
    repository = object()
    sector_mapping = {"005930": ("1001", "전기전자", "2026-09-17", "MAPPED")}
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(
            as_of=target,
            cache_dir="data/raw/stocks",
            output_dir="artifacts/patterns/pattern_a/production/scanner",
            market=None,
            tickers=None,
            limit=None,
            enrich_market_rs_cross_section=False,
        ),
    )
    monkeypatch.setattr(module, "logger", Mock())
    monkeypatch.setattr(module, "build_production_repository_v2", lambda root, *, end: repository)
    monkeypatch.setattr(
        module,
        "load_rolling_production_market_calendar",
        lambda _root: SimpleNamespace(trading_dates=pd.DatetimeIndex(["2026-09-17"])),
    )
    monkeypatch.setattr(
        module,
        "resolve_sector_membership_snapshot_for_target",
        lambda as_of, *, repo_root: (pd.DataFrame(), "2026-09-17", selected_path, {"snapshot_effective_date": "2026-09-17"}),
    )

    def fake_mapping(as_of: str, *, path: Path, repo_root: Path):
        captured["mapping_as_of"] = as_of
        captured["mapping_path"] = path
        return sector_mapping

    monkeypatch.setattr(module, "load_sector_mapping_exact_snapshot", fake_mapping)

    def fake_scan(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            summary=_summary(),
            save_artifacts=lambda *, output_dir: (Path(output_dir) / "scan.csv", Path(output_dir) / "summary.json"),
        )

    monkeypatch.setattr(module, "scan_pattern_a_universe", fake_scan)

    module.main()

    assert captured["as_of"] == target
    assert captured["reference_market_date"] == target
    assert captured["repository"] is repository
    assert captured["sector_mapping"] == sector_mapping
    assert captured["sector_mapping_snapshot_date"] == "2026-09-17"
    assert captured["mapping_as_of"] == "2026-09-17"
    assert captured["mapping_path"] == selected_path
    assert captured["target_markets"] is None
    assert captured["target_tickers"] is None
    assert captured["limit"] is None
