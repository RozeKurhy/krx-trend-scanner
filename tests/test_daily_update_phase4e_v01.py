"""Focused tests for Phase 4E status synthesis and execution ordering."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_daily_update_phase4e_v01 as phase4e
from scripts import run_daily_update_phase4c_v01 as phase4c
from scripts import run_daily_update_phase4d_v01 as phase4d
from scripts import run_daily_update_phase4b_v01 as phase4b
from scripts import run_pattern_a_universe_scanner as phase4a


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


def _write_scanner_fixture(
    root: Path,
    target: str = "2026-09-17",
    reference_market_date: str | None = None,
) -> None:
    scanner_dir = root / "artifacts/patterns/pattern_a/production/scanner"
    scanner_dir.mkdir(parents=True)
    dt = target.replace("-", "")
    with (scanner_dir / f"pattern_a_universe_scan_{dt}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "candidate_state"])
        writer.writeheader()
        writer.writerow({"ticker": "000001", "candidate_state": "CANDIDATE"})
    (scanner_dir / f"pattern_a_universe_scan_{dt}_summary.json").write_text(
        json.dumps(
            {
                "requested_as_of": target,
                "reference_market_date": reference_market_date or target,
                "official_common_total": 1,
                "scan_target_count": 1,
                "rows_emitted": 1,
                "scanner_error_count": 0,
            }
        ),
        encoding="utf-8",
    )


def _write_report(path: Path, target: str, ticker: str = "000001") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "json" / f"{ticker}_stock_report.json").parent.mkdir(parents=True, exist_ok=True)
    (path / "json" / f"{ticker}_stock_report.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "asset_type": "COMMON",
                "report_version": "0.5",
                "requested_as_of": target,
                "reference_market_date": target,
                "a_fast_core": {
                    "strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
                    "canonical_position": "CLOSED",
                },
            }
        ),
        encoding="utf-8",
    )
    (path / f"{ticker}_stock_report.md").write_text("# report\n", encoding="utf-8")


def _write_web_fixture(
    root: Path,
    target: str = "2026-09-17",
    reference_market_date: str | None = None,
) -> None:
    web = root / "web/data"
    stocks = web / "stocks"
    stocks.mkdir(parents=True)
    ref = reference_market_date or target
    common = {"requested_as_of": target, "reference_market_date": ref}
    index = {
        **common,
        "items": [{"ticker": "000001", "report_available": True}],
        "available_report_count": 1,
    }
    report = {
        "technical_details": {
            "requested_as_of": target,
            "reference_market_date": ref,
            "report_version": "0.5",
        },
        "strategy": {"id": "PATTERN_A_FAST_FINAL_STRATEGY_V02"},
    }
    market = {**common, "items": [{"ticker": "000001"}], "scope": {"report_count": 1}}
    strategy = {
        **common,
        "items": [{"ticker": "000001"}],
        "scope": {"report_count": 1},
        "strategy": {"id": "PATTERN_A_FAST_FINAL_STRATEGY_V02"},
    }
    sector = {**common, "as_of": ref, "items": [{"ticker": "000001", "report_available": True}]}
    foreign = {**common, "as_of": ref, "items": [{"ticker": "000001", "report_available": True}]}
    health = {
        **common,
        "stock_reports": {
            "ready": True,
            "source_json_count": 1,
            "web_compact_count": 1,
            "web_index_available_report_count": 1,
        },
    }
    for name, payload in {
        "stock-index.json": index,
        "market-ranking.json": market,
        "strategy-monitor.json": strategy,
        "sector-rs-ranking.json": sector,
        "foreign-net-buy-ranking.json": foreign,
        "health.json": health,
    }.items():
        (web / name).write_text(json.dumps(payload), encoding="utf-8")
    (stocks / "000001.json").write_text(json.dumps(report), encoding="utf-8")


def _patch_calendar(monkeypatch: pytest.MonkeyPatch, *trading_dates: str) -> None:
    monkeypatch.setattr(
        phase4a,
        "load_rolling_production_market_calendar",
        lambda root: SimpleNamespace(trading_dates=list(trading_dates)),
    )


def test_phase4a_valid_exact_artifact_skips_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_scanner_fixture(tmp_path)
    _patch_calendar(monkeypatch, "2026-09-17")
    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: pytest.fail("4A reran"))
    monkeypatch.setattr(phase4e, "run_phase4b", lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(phase4e, "run_phase4c", lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(phase4e, "run_phase4d", lambda *args, **kwargs: {"status": "PASS"})

    result = phase4e.run_phase4e("2026-09-17", root=tmp_path)

    assert result["phases"]["4A"]["status"] == "NOOP_ALREADY_COMPLETE"


def test_phase4b_valid_exact_corpus_skips_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_scanner_fixture(tmp_path)
    _patch_calendar(monkeypatch, "2026-09-17")
    reports = tmp_path / "artifacts/reporting/stock_reports"
    _write_report(reports / "20260916", "2026-09-16")
    _write_report(reports / "20260917", "2026-09-17")
    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(phase4e, "run_phase4b", lambda *args, **kwargs: pytest.fail("4B reran"))
    monkeypatch.setattr(phase4e, "run_phase4c", lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(phase4e, "run_phase4d", lambda *args, **kwargs: {"status": "PASS"})

    result = phase4e.run_phase4e("2026-09-17", root=tmp_path)

    assert result["phases"]["4B"]["status"] == "NOOP_ALREADY_COMPLETE"


def test_all_noop_uses_read_only_prechecks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_scanner_fixture(tmp_path)
    _patch_calendar(monkeypatch, "2026-09-17")
    reports = tmp_path / "artifacts/reporting/stock_reports"
    _write_report(reports / "20260916", "2026-09-16")
    _write_report(reports / "20260917", "2026-09-17")
    _write_web_fixture(tmp_path)
    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: pytest.fail("4A ran"))
    monkeypatch.setattr(phase4e, "run_phase4b", lambda *args, **kwargs: pytest.fail("4B ran"))
    monkeypatch.setattr(phase4e, "run_phase4c", lambda *args, **kwargs: pytest.fail("4C ran"))
    monkeypatch.setattr(phase4e, "run_phase4d", lambda *args, **kwargs: pytest.fail("4D ran"))

    result = phase4e.run_phase4e("2026-09-17", root=tmp_path)

    assert result["overall_status"] == "NOOP_ALREADY_COMPLETE"
    assert [result["phases"][name]["status"] for name in ("4A", "4B", "4C", "4D")] == [
        "NOOP_ALREADY_COMPLETE",
        "NOOP_ALREADY_COMPLETE",
        "NOOP_ALREADY_COMPLETE",
        "NOOP_ALREADY_COMPLETE",
    ]


def test_phase4d_standalone_valid_payload_returns_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_scanner_fixture(tmp_path)
    _write_web_fixture(tmp_path)
    _patch_calendar(monkeypatch, "2026-09-17")
    monkeypatch.setattr(phase4d, "ROOT", tmp_path)

    result = phase4d.run_phase4d("2026-09-17", execute_live=True, root=tmp_path)

    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["web_data_writes"] == 0


def test_trading_day_reference_authority_allows_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_scanner_fixture(tmp_path, "2026-09-17", "2026-09-17")
    _patch_calendar(monkeypatch, "2026-09-17")

    result = phase4e._phase4a_noop_precheck("2026-09-17", root=tmp_path)

    assert result is not None
    assert result["status"] == "NOOP_ALREADY_COMPLETE"


def test_non_trading_day_reference_authority_allows_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = "2026-09-20"  # Sunday
    reference = "2026-09-18"  # Friday
    _write_scanner_fixture(tmp_path, target, reference)
    _patch_calendar(monkeypatch, "2026-09-17", reference)

    result = phase4e._phase4a_noop_precheck(target, root=tmp_path)

    assert result is not None
    assert result["status"] == "NOOP_ALREADY_COMPLETE"
    assert result["reference_market_date"] == reference


def test_stale_reference_is_blocked_and_not_recomputed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = "2026-09-20"
    _write_scanner_fixture(tmp_path, target, "2026-09-17")
    _patch_calendar(monkeypatch, "2026-09-18")
    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: pytest.fail("4A recomputed"))

    result = phase4e.run_phase4e(target, root=tmp_path)

    assert result["overall_status"] == "BLOCKED"
    assert result["phases"]["4A"]["status"] == "BLOCKED"
    assert "PHASE4A_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH" in result["phases"]["4A"]["result"]["error"]


def test_scanner_and_web_stale_reference_is_blocked_even_when_they_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = "2026-09-20"
    stale_reference = "2026-09-17"
    _write_scanner_fixture(tmp_path, target, stale_reference)
    _write_web_fixture(tmp_path, target, stale_reference)
    _patch_calendar(monkeypatch, "2026-09-18")

    with pytest.raises(phase4d.Phase4DError, match="PHASE4D_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH"):
        phase4d.inspect_published_payload(tmp_path, target)


def test_future_reference_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = "2026-09-20"
    _write_scanner_fixture(tmp_path, target, "2026-09-21")
    _patch_calendar(monkeypatch, "2026-09-18")

    result = phase4e.run_phase4e(target, root=tmp_path)

    assert result["overall_status"] == "BLOCKED"
    assert result["phases"]["4A"]["status"] == "BLOCKED"


def test_phase4c_is_called_once_and_4d_reuses_its_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"phase4c": 0, "phase4d_context": None}

    monkeypatch.setattr(phase4e, "run_phase4a", lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(phase4e, "run_phase4b", lambda *args, **kwargs: {"status": "PASS"})

    def phase4c_runner(*args: object, **kwargs: object) -> dict[str, object]:
        calls["phase4c"] += 1
        return {"status": "PASS", "network_calls": 0, "web_data_writes": 0}

    def phase4d_runner(*args: object, **kwargs: object) -> dict[str, object]:
        calls["phase4d_context"] = kwargs.get("phase4c_result")
        return {"status": "PASS"}

    monkeypatch.setattr(phase4e, "run_phase4c", phase4c_runner)
    monkeypatch.setattr(phase4e, "run_phase4d", phase4d_runner)

    result = phase4e.run_phase4e("2026-09-17", root=tmp_path)

    assert result["overall_status"] == "PASS"
    assert calls["phase4c"] == 1
    assert calls["phase4d_context"] == {"status": "PASS", "network_calls": 0, "web_data_writes": 0}


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (phase4c.Phase4CError("PHASE4C_SECTOR_RS_AUTHORITY_MISSING"), "BLOCKED"),
        (phase4c.Phase4CError("PHASE4C_MARKET_RS_REFERENCE_MARKET_DATE_MISMATCH"), "BLOCKED"),
        (phase4d.Phase4DError("PHASE4D_JSON_OBJECT_REQUIRED"), "FAILED"),
        (phase4d.Phase4DError("PHASE4D_NONFINITE_VALUE"), "FAILED"),
        (RuntimeError("unexpected runtime error"), "FAILED"),
    ],
)
def test_exception_status_contract(exc: BaseException, expected: str) -> None:
    assert phase4e._exception_status(exc) == expected
