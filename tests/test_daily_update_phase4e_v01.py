"""Focused tests for Phase 4E status synthesis and execution ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_daily_update_phase4e_v01 as phase4e


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS", "PASS", "PASS", "PASS"], "PASS"),
        (["NOOP", "NOOP", "NOOP", "NOOP"], "NOOP_ALREADY_COMPLETE"),
        (["PASS", "NOOP", "PASS", "NOOP"], "PASS"),
        (["PASS", "BLOCKED", "PASS", "NOOP"], "BLOCKED"),
        (["PASS", "PASS", "FAILED", "NOOP"], "FAILED"),
    ],
)
def test_synthesize_overall_status(statuses: list[str], expected: str) -> None:
    assert phase4e.synthesize_overall_status(statuses) == expected


def test_run_order_and_same_target_are_preserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def fake(name: str, status: str):
        def _runner(target_as_of: str, **kwargs: object) -> dict[str, str]:
            calls.append((name, target_as_of))
            return {"status": status}

        return _runner

    monkeypatch.setattr(phase4e, "run_phase4a", fake("4A", "PASS"))
    monkeypatch.setattr(phase4e, "run_phase4b", fake("4B", "NOOP"))
    monkeypatch.setattr(phase4e, "run_phase4c", fake("4C", "PASS"))
    monkeypatch.setattr(phase4e, "run_phase4d", fake("4D", "PASS"))

    result = phase4e.run_phase4e("2026-09-17", execute_live=False, root=tmp_path)

    assert calls == [("4A", "2026-09-17"), ("4B", "2026-09-17"), ("4C", "2026-09-17"), ("4D", "2026-09-17")]
    assert result["overall_status"] == "PASS"
    assert [result["phases"][name]["status"] for name in ("4A", "4B", "4C", "4D")] == [
        "PASS", "NOOP_ALREADY_COMPLETE", "PASS", "PASS"
    ]


@pytest.mark.parametrize("blocked_status", ["BLOCKED", "FAILED"])
def test_blocked_or_failed_phase_fail_fast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, blocked_status: str) -> None:
    calls: list[str] = []

    def phase_a(target_as_of: str, **kwargs: object) -> dict[str, str]:
        calls.append("4A")
        return {"status": "PASS"}

    def phase_b(target_as_of: str, **kwargs: object) -> dict[str, str]:
        calls.append("4B")
        return {"status": blocked_status}

    def should_not_run(target_as_of: str, **kwargs: object) -> dict[str, str]:
        calls.append("unexpected")
        return {"status": "PASS"}

    monkeypatch.setattr(phase4e, "run_phase4a", phase_a)
    monkeypatch.setattr(phase4e, "run_phase4b", phase_b)
    monkeypatch.setattr(phase4e, "run_phase4c", should_not_run)
    monkeypatch.setattr(phase4e, "run_phase4d", should_not_run)

    result = phase4e.run_phase4e("2026-09-17", root=tmp_path)

    assert calls == ["4A", "4B"]
    assert result["overall_status"] == blocked_status
    assert set(result["phases"]) == {"4A", "4B"}


def test_parser_requires_target_and_exposes_explicit_live_flag() -> None:
    with pytest.raises(SystemExit):
        phase4e.build_parser().parse_args([])
    args = phase4e.build_parser().parse_args(["--target-as-of", "2026-09-17", "--execute-live"])
    assert args.target_as_of == "2026-09-17"
    assert args.execute_live is True
