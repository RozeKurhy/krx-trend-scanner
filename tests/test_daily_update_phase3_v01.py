"""Focused tests for Phase 3G status composition and dependency gating."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from trend_scanner.data.daily_update_phase3 import (
    BLOCKED,
    FAILED,
    NOOP_ALREADY_COMPLETE,
    PASS,
    Phase3Coordinator,
    TOP_LEVEL_STEPS,
    _load_script_module,
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
