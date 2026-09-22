"""Focused tests for Phase 3G status composition and dependency gating."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import hydrate_fundamentals_v1_production as fundamentals
import trend_scanner.data.daily_update_phase3 as phase3
from trend_scanner.data.daily_update_phase3 import (
    BLOCKED,
    FAILED,
    NOOP_ALREADY_COMPLETE,
    PASS,
    Phase3Coordinator,
    TOP_LEVEL_STEPS,
    _fundamentals_runner,
    _load_script_module,
    _run_step,
    _sector_rs_ranking_runner,
    compose_phase3_status,
)


def _runner(status: str, calls: list[str], name: str) -> Callable[[str], dict[str, str]]:
    def run(target_as_of: str) -> dict[str, str]:
        calls.append(f"{name}:{target_as_of}")
        return {"status": status, "target_as_of": target_as_of}

    return run


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ({name: NOOP_ALREADY_COMPLETE for name in TOP_LEVEL_STEPS}, NOOP_ALREADY_COMPLETE),
        ({name: PASS if name == "foreign_flow" else NOOP_ALREADY_COMPLETE for name in TOP_LEVEL_STEPS}, PASS),
        ({name: BLOCKED if name == "market_rs" else PASS for name in TOP_LEVEL_STEPS}, BLOCKED),
        ({name: FAILED if name == "fundamentals" else BLOCKED for name in TOP_LEVEL_STEPS}, FAILED),
    ],
)
def test_compose_phase3_status_contract(statuses: dict[str, str], expected: str) -> None:
    assert compose_phase3_status(statuses) == expected


def test_coordinator_passes_one_target_and_keeps_sector_index_internal() -> None:
    calls: list[str] = []
    coordinator = Phase3Coordinator(
        foreign_flow=_runner(PASS, calls, "foreign"),
        fundamentals=_runner(NOOP_ALREADY_COMPLETE, calls, "fundamentals"),
        market_rs=_runner(PASS, calls, "market"),
        sector_membership=_runner(NOOP_ALREADY_COMPLETE, calls, "membership"),
        sector_index=_runner(NOOP_ALREADY_COMPLETE, calls, "sector_index"),
        sector_rs_ranking=_runner(PASS, calls, "ranking"),
    )

    result = coordinator.execute("2026-09-17")

    assert result.overall_status == PASS
    assert tuple(result.steps) == TOP_LEVEL_STEPS
    assert all(call.endswith(":2026-09-17") for call in calls)
    assert result.steps["sector_rs"].status == PASS
    assert result.steps["sector_rs"].details["sector_index"]["status"] == NOOP_ALREADY_COMPLETE
    assert "sector_index" not in result.steps


@pytest.mark.parametrize("dependency_status", [BLOCKED, FAILED])
def test_membership_dependency_stops_sector_index_and_ranking(dependency_status: str) -> None:
    calls: list[str] = []
    coordinator = Phase3Coordinator(
        foreign_flow=_runner(PASS, calls, "foreign"),
        fundamentals=_runner(PASS, calls, "fundamentals"),
        market_rs=_runner(PASS, calls, "market"),
        sector_membership=_runner(dependency_status, calls, "membership"),
        sector_index=_runner(PASS, calls, "sector_index"),
        sector_rs_ranking=_runner(PASS, calls, "ranking"),
    )

    result = coordinator.execute("2026-09-17")

    assert result.overall_status == dependency_status
    assert result.steps["sector_rs"].status == dependency_status
    assert not any(call.startswith("sector_index:") for call in calls)
    assert not any(call.startswith("ranking:") for call in calls)


@pytest.mark.parametrize("index_status", [BLOCKED, FAILED])
def test_sector_index_dependency_stops_ranking(index_status: str) -> None:
    calls: list[str] = []
    coordinator = Phase3Coordinator(
        foreign_flow=_runner(PASS, calls, "foreign"),
        fundamentals=_runner(PASS, calls, "fundamentals"),
        market_rs=_runner(PASS, calls, "market"),
        sector_membership=_runner(PASS, calls, "membership"),
        sector_index=_runner(index_status, calls, "sector_index"),
        sector_rs_ranking=_runner(PASS, calls, "ranking"),
    )

    result = coordinator.execute("2026-09-17")

    assert result.overall_status == index_status
    assert result.steps["sector_rs"].status == index_status
    assert any(call.startswith("sector_index:") for call in calls)
    assert not any(call.startswith("ranking:") for call in calls)


def test_script_loader_registers_dataclass_module(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "fixture.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Fixture:\n"
        "    value: str\n",
        encoding="utf-8",
    )

    module = _load_script_module(tmp_path, "fixture.py")

    assert module.Fixture("ok").value == "ok"


@pytest.mark.parametrize(
    ("artifact_effective_date", "expected_status"),
    [
        ("2026-09-17", BLOCKED),
        ("2026-10-01", NOOP_ALREADY_COMPLETE),
    ],
)
def test_sector_rs_noop_requires_current_membership_effective_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_effective_date: str,
    expected_status: str,
) -> None:
    target = "2026-10-05"
    output_dir = tmp_path / "data/analytics/sector_rs_ranking/v01"
    output_dir.mkdir(parents=True)
    compact = target.replace("-", "")
    parquet_path = output_dir / f"sector_rs_ranking_{compact}.parquet"
    parquet_path.touch()
    (output_dir / f"sector_rs_ranking_{compact}_meta.json").write_text(
        json.dumps(
            {
                "as_of": target,
                "membership_effective_date": artifact_effective_date,
                "scope": {"type": "TARGET_PIT_COMMON_POPULATION"},
                "target_common_population": 1,
            }
        ),
        encoding="utf-8",
    )
    target_common = pd.DataFrame({"ticker": ["000001"], "market": ["KOSPI"]})
    frame = pd.DataFrame({"ticker": ["000001"], "market": ["KOSPI"], "as_of": [target]})
    membership = target_common.assign(sector_code="001", sector_name="Fixture")
    monkeypatch.setattr(
        phase3,
        "resolve_sector_membership_snapshot_for_target",
        lambda *_args, **_kwargs: (membership, "2026-10-01", tmp_path / "membership.parquet", {}),
    )
    monkeypatch.setattr(phase3, "load_local_target_universe", lambda *_args, **_kwargs: target_common)
    monkeypatch.setattr(phase3.pd, "read_parquet", lambda *_args, **_kwargs: frame)
    monkeypatch.setattr(
        phase3,
        "_load_script_module",
        lambda *_args, **_kwargs: pytest.fail("invalid existing artifact must not rebuild"),
    )

    result = _run_step(_sector_rs_ranking_runner(tmp_path), target)

    assert result.status == expected_status
    if expected_status == BLOCKED:
        assert result.details["reason"] == "EXISTING_SECTOR_RS_ARTIFACT_INVALID"


def test_fundamentals_manifest_changes_requested_is_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = "2026-10-05"
    manifest_path = tmp_path / "artifacts/fundamentals/production/20261005/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"final_status": "CHANGES_REQUESTED"}), encoding="utf-8")
    monkeypatch.setattr(
        phase3,
        "_load_script_module",
        lambda *_args, **_kwargs: SimpleNamespace(run=lambda *_args, **_kwargs: 1),
    )

    result = _fundamentals_runner(tmp_path, tmp_path / "env.md", "2026-10-05")(target)

    assert result["status"] == FAILED
    assert result["manifest_final_status"] == "CHANGES_REQUESTED"


def _write_fundamentals_output(
    path: Path,
    *,
    ticker: str,
    requested_as_of: str,
    runner_version: str | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "runner_version": runner_version or fundamentals.RUNNER_VERSION,
                "ticker": ticker,
                "requested_as_of": requested_as_of,
                "terminal_status": "PASS",
            }
        ),
        encoding="utf-8",
    )


def _fundamentals_noop_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    outputs: dict[str, str],
    runner_versions: dict[str, str] | None = None,
) -> tuple[Callable[[str], dict[str, object]], SimpleNamespace]:
    target = "2026-10-05"
    manifest_path = tmp_path / "artifacts/fundamentals/production/20261005/manifest.json"
    tickers_dir = manifest_path.parent / "tickers"
    tickers_dir.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "requested_as_of": target,
                "mode": "full",
                "final_status": PASS,
                "metadata_snapshot_date": "2026-10-01",
                "total_universe": 2,
                "universe_source": "target_basic_info_and_existing_product_metadata",
            }
        ),
        encoding="utf-8",
    )
    for filename, payload in outputs.items():
        path = tickers_dir / filename
        if payload == "MALFORMED":
            path.write_text("{not-json", encoding="utf-8")
        else:
            _write_fundamentals_output(
                path,
                ticker=payload,
                requested_as_of=target,
                runner_version=(runner_versions or {}).get(filename),
            )
    monkeypatch.setattr(
        phase3,
        "load_target_production_universe",
        lambda *_args, **_kwargs: (
            [{"ticker": "A"}, {"ticker": "B"}],
            "2026-10-01",
        ),
    )
    module = SimpleNamespace(
        inspect_target_production_outputs=fundamentals.inspect_target_production_outputs,
        run=lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(phase3, "_load_script_module", lambda *_args, **_kwargs: module)
    return phase3._fundamentals_runner(tmp_path, tmp_path / "env.md", target), module


@pytest.mark.parametrize(
    "outputs",
    [
        {"A.json": "A", "B.json": "B", "C.json": "C"},
        {"A.json": "A"},
        {"A.json": "A", "B.json": "MALFORMED"},
        {"A.json": "A", "B.json": "A"},
    ],
)
def test_fundamentals_noop_rejects_non_exact_production_output_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outputs: dict[str, str],
) -> None:
    runner, _module = _fundamentals_noop_fixture(tmp_path, monkeypatch, outputs=outputs)

    result = runner("2026-10-05")

    assert result["status"] != NOOP_ALREADY_COMPLETE


def test_fundamentals_noop_accepts_clean_exact_production_output_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, module = _fundamentals_noop_fixture(
        tmp_path,
        monkeypatch,
        outputs={"A.json": "A", "B.json": "B"},
    )
    called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return 1

    module.run = unexpected_run
    result = runner("2026-10-05")

    assert result["status"] == NOOP_ALREADY_COMPLETE
    assert result["output_integrity"]["missing_count"] == 0
    assert result["output_integrity"]["extra_count"] == 0
    assert result["output_integrity"]["invalid_count"] == 0
    assert result["output_integrity"]["duplicate_count"] == 0
    assert called is False


def test_fundamentals_noop_rejects_unsupported_runner_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, module = _fundamentals_noop_fixture(
        tmp_path,
        monkeypatch,
        outputs={"A.json": "A", "B.json": "B"},
        runner_versions={"B.json": "UNSUPPORTED_OLD_RUNNER"},
    )

    inspection = module.inspect_target_production_outputs(
        tmp_path / "artifacts/fundamentals/production/20261005/tickers",
        expected_tickers={"A", "B"},
        requested_as_of="2026-10-05",
    )
    result = runner("2026-10-05")

    assert inspection["invalid_count"] == 1
    assert inspection["invalid"] == ["B.json"]
    assert result["status"] != NOOP_ALREADY_COMPLETE
