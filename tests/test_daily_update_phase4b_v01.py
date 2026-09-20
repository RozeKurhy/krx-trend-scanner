"""Phase 4B production runner (scripts/run_daily_update_phase4b_v01.py) targeted tests.

Runner orchestration만 검증한다 (Scanner 입력 로딩/검증, candidate_state == CANDIDATE
선택, staging/promote, fail-closed 처리). ``generate_stock_report()`` 자체의 내부 산식은
기존 test_stock_report*.py / test_a_fast_core_stock_report.py 스위트가 이미 검증하므로
여기서는 monkeypatch로 대체해 무겁고 느린 실제 전체 리포트 계산을 반복하지 않는다.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_daily_update_phase4b_v01 as phase4b
from trend_scanner.reporting.fundamentals_report import FundamentalsArtifactUnavailable


TARGET = "2026-09-17"
SCANNER_COLUMNS = ["ticker", "name", "market", "candidate_state"]


def _write_scanner_artifacts(
    root: Path,
    target_as_of: str,
    rows: list[dict[str, str]],
    *,
    reference_market_date: str | None = None,
    requested_as_of_override: str | None = None,
    rows_emitted_override: int | None = None,
) -> None:
    scanner_dir = root / "artifacts/patterns/pattern_a/production/scanner"
    scanner_dir.mkdir(parents=True, exist_ok=True)
    dt_clean = target_as_of.replace("-", "")
    csv_path = scanner_dir / f"pattern_a_universe_scan_{dt_clean}.csv"
    summary_path = scanner_dir / f"pattern_a_universe_scan_{dt_clean}_summary.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCANNER_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    summary = {
        "requested_as_of": requested_as_of_override if requested_as_of_override is not None else target_as_of,
        "reference_market_date": reference_market_date if reference_market_date is not None else target_as_of,
        "rows_emitted": rows_emitted_override if rows_emitted_override is not None else len(rows),
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def _write_fundamentals_artifact(root: Path, target_as_of: str, ticker: str, *, valid: bool = True) -> None:
    dt_clean = target_as_of.replace("-", "")
    fund_dir = root / "artifacts/fundamentals/production" / dt_clean / "tickers"
    fund_dir.mkdir(parents=True, exist_ok=True)
    if not valid:
        return
    payload = {
        "ticker": ticker,
        "requested_as_of": target_as_of,
        "f5_ready": {
            "applicability": "APPLICABLE",
            "data_status": "PARTIAL",
            "reason": "TEST",
            "requested_as_of": target_as_of,
            "company_family": "NON_FINANCIAL",
            "currency": "KRW",
            "filter_status": "PASS",
            "filter_passed": True,
            "filter_reasons": [],
            "summary": {},
            "quarterly": [],
            "annual": [],
            "diagnostics": [],
        },
    }
    (fund_dir / f"{ticker}.json").write_text(json.dumps(payload), encoding="utf-8")


def _fake_generate_stock_report(
    *, ticker, as_of, repo_root, repository, fundamentals_section, reference_market_date, output_dir, save_artifacts,
):
    json_dir = Path(output_dir) / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_version": "0.5",
        "requested_as_of": as_of,
        "reference_market_date": reference_market_date,
        "a_fast_core": {"strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02"},
    }
    json_path = json_dir / f"{ticker}.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    md_path = Path(output_dir) / f"{ticker}.md"
    md_path.write_text(f"# {ticker}", encoding="utf-8")
    fake_report = SimpleNamespace(
        report_version="0.5",
        a_fast_core=SimpleNamespace(strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02"),
        requested_as_of=as_of,
        reference_market_date=reference_market_date,
    )
    return fake_report, json_path, md_path


@pytest.fixture
def patched_runner(monkeypatch):
    """generate_stock_report / build_production_repository_v2를 대체해 runner
    orchestration만 빠르게 검증한다."""
    monkeypatch.setattr(phase4b, "generate_stock_report", _fake_generate_stock_report)
    monkeypatch.setattr(phase4b, "build_production_repository_v2", lambda root, end: "FAKE_REPOSITORY_V2")
    return monkeypatch


def _candidate_rows(tickers: list[str]) -> list[dict[str, str]]:
    return [{"ticker": t, "name": f"종목{t}", "market": "KOSPI", "candidate_state": "candidate"} for t in tickers]


# --- A. exact-target scanner artifact만 사용 -------------------------------------


def test_a_loads_exact_target_scanner_artifact_only(tmp_path, patched_runner):
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    # 다른 날짜 artifact가 존재해도 무시되어야 한다.
    _write_scanner_artifacts(tmp_path, "2026-09-04", _candidate_rows(["999999"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["requested_as_of"] == TARGET
    assert result["scanner_candidate_count"] == 1
    assert result["promoted"] is True


# --- B. wrong-date scanner → fail ------------------------------------------------


def test_b_wrong_date_scanner_summary_fails_closed(tmp_path, patched_runner):
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]), requested_as_of_override="2026-09-16")
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    with pytest.raises(phase4b.Phase4BError, match="REQUESTED_AS_OF_MISMATCH"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


def test_b_missing_scanner_artifact_fails_closed(tmp_path, patched_runner):
    with pytest.raises(phase4b.Phase4BError, match="SCANNER_CSV_MISSING"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


def test_b_row_count_mismatch_fails_closed(tmp_path, patched_runner):
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]), rows_emitted_override=5)
    with pytest.raises(phase4b.Phase4BError, match="ROW_COUNT_MISMATCH"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


def test_b_duplicate_ticker_fails_closed(tmp_path, patched_runner):
    rows = _candidate_rows(["000050", "000050"])
    _write_scanner_artifacts(tmp_path, TARGET, rows, rows_emitted_override=2)
    with pytest.raises(phase4b.Phase4BError, match="DUPLICATE_TICKERS"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


# --- C. scanner 재실행 없음 --------------------------------------------------------


def test_c_scanner_is_never_re_invoked(tmp_path, patched_runner, monkeypatch):
    import trend_scanner.scanner.full_universe_scanner as scanner_module

    def _forbidden(*args, **kwargs):
        raise AssertionError("scan_pattern_a_universe() must not be called by Phase 4B")

    monkeypatch.setattr(scanner_module, "scan_pattern_a_universe", _forbidden)

    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)
    assert result["promoted"] is True


# --- D. candidate_state == CANDIDATE만 선택 ---------------------------------------


def test_d_only_candidate_state_rows_are_selected():
    rows = [
        {"ticker": "000001", "name": "A", "market": "KOSPI", "candidate_state": "candidate"},
        {"ticker": "000002", "name": "B", "market": "KOSPI", "candidate_state": "watch"},
        {"ticker": "000003", "name": "C", "market": "KOSPI", "candidate_state": "late"},
        {"ticker": "000004", "name": "D", "market": "KOSPI", "candidate_state": "blocked"},
        {"ticker": "000005", "name": "E", "market": "KOSPI", "candidate_state": "insufficient_data"},
        {"ticker": "000006", "name": "F", "market": "KOSPI", "candidate_state": "candidate"},
    ]
    selected = phase4b.select_candidate_tickers(rows)
    assert selected == ["000001", "000006"]


# --- E. 과거 report directory가 target set에 영향 없음 -----------------------------


def test_e_stale_canonical_directory_is_fully_replaced_not_merged(tmp_path, patched_runner):
    canonical_dir = tmp_path / "artifacts/reporting/stock_reports" / TARGET.replace("-", "")
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "json").mkdir()
    (canonical_dir / "json" / "999999.json").write_text("{}", encoding="utf-8")
    (canonical_dir / "999999.md").write_text("stale", encoding="utf-8")

    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["promoted"] is True
    json_tickers = {p.stem for p in (canonical_dir / "json").glob("*.json")}
    md_tickers = {p.stem for p in canonical_dir.glob("*.md")}
    assert json_tickers == {"000050"}
    assert md_tickers == {"000050"}


# --- F. fundamentals missing/mismatch → fail --------------------------------------


def test_f_missing_fundamentals_artifact_fails_closed_and_does_not_promote(tmp_path, patched_runner):
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050", "000060"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")
    # 000060 fundamentals artifact 없음 (fail-closed 대상)

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["promoted"] is False
    assert result["generation_error_count"] == 1
    errored = {e["ticker"] for e in result["generation_errors"]}
    assert errored == {"000060"}
    canonical_dir = tmp_path / "artifacts/reporting/stock_reports" / TARGET.replace("-", "")
    assert not canonical_dir.exists()


def test_f_fundamentals_helper_raises_on_missing_artifact(tmp_path):
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    with pytest.raises(FundamentalsArtifactUnavailable, match="FUNDAMENTALS_ARTIFACT_MISSING"):
        load_fundamentals_section_from_production_artifact("000050", TARGET, tmp_path)


def test_f_fundamentals_helper_raises_on_missing_f5_ready(tmp_path):
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    fund_dir = tmp_path / "artifacts/fundamentals/production" / TARGET.replace("-", "") / "tickers"
    fund_dir.mkdir(parents=True)
    payload = {"ticker": "000050", "requested_as_of": TARGET}  # f5_ready 없음
    (fund_dir / "000050.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FundamentalsArtifactUnavailable, match="F5_READY_MISSING"):
        load_fundamentals_section_from_production_artifact("000050", TARGET, tmp_path)


def test_f_fundamentals_helper_raises_on_ticker_mismatch(tmp_path):
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    fund_dir = tmp_path / "artifacts/fundamentals/production" / TARGET.replace("-", "") / "tickers"
    fund_dir.mkdir(parents=True)
    payload = {
        "ticker": "000099",  # mismatch vs requested ticker below
        "requested_as_of": TARGET,
        "f5_ready": {
            "applicability": "APPLICABLE", "data_status": "PARTIAL", "reason": None,
            "requested_as_of": TARGET, "company_family": "NON_FINANCIAL", "currency": "KRW",
            "filter_status": "PASS", "filter_passed": True, "filter_reasons": [],
            "summary": {}, "quarterly": [], "annual": [], "diagnostics": [],
        },
    }
    (fund_dir / "000050.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FundamentalsArtifactUnavailable, match="TICKER_MISMATCH"):
        load_fundamentals_section_from_production_artifact("000050", TARGET, tmp_path)


def test_f_fundamentals_helper_raises_on_requested_as_of_mismatch(tmp_path):
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    fund_dir = tmp_path / "artifacts/fundamentals/production" / TARGET.replace("-", "") / "tickers"
    fund_dir.mkdir(parents=True)
    payload = {
        "ticker": "000050",
        "requested_as_of": "2026-09-16",  # mismatch
        "f5_ready": {
            "applicability": "APPLICABLE", "data_status": "PARTIAL", "reason": None,
            "requested_as_of": "2026-09-16", "company_family": "NON_FINANCIAL", "currency": "KRW",
            "filter_status": "PASS", "filter_passed": True, "filter_reasons": [],
            "summary": {}, "quarterly": [], "annual": [], "diagnostics": [],
        },
    }
    (fund_dir / "000050.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FundamentalsArtifactUnavailable, match="AS_OF_MISMATCH"):
        load_fundamentals_section_from_production_artifact("000050", TARGET, tmp_path)


def test_f_fundamentals_helper_terminal_data_unavailable_is_not_a_failure(tmp_path):
    """artifact 내부의 정상 terminal 상태(DATA_UNAVAILABLE)는 실패가 아니다."""
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    fund_dir = tmp_path / "artifacts/fundamentals/production" / TARGET.replace("-", "") / "tickers"
    fund_dir.mkdir(parents=True)
    payload = {
        "ticker": "000050",
        "requested_as_of": TARGET,
        "f5_ready": {
            "applicability": "NOT_APPLICABLE", "data_status": "DATA_UNAVAILABLE",
            "reason": "CORP_CODE_MISSING", "requested_as_of": TARGET,
            "company_family": None, "currency": "KRW",
            "filter_status": "DATA_UNAVAILABLE", "filter_passed": False, "filter_reasons": [],
            "summary": {}, "quarterly": [], "annual": [], "diagnostics": [],
        },
    }
    (fund_dir / "000050.json").write_text(json.dumps(payload), encoding="utf-8")

    section = load_fundamentals_section_from_production_artifact("000050", TARGET, tmp_path)
    assert section.data_status == "DATA_UNAVAILABLE"


# --- Scanner input validation: reference_market_date after target ----------------


def test_reference_market_date_after_target_fails_closed(tmp_path, patched_runner):
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]), reference_market_date="2026-09-18")
    with pytest.raises(phase4b.Phase4BError, match="REFERENCE_MARKET_DATE_AFTER_TARGET"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


# --- reference_market_date threading into generated report ------------------------


def test_non_trading_day_reference_market_date_is_passed_through(tmp_path, patched_runner):
    """비거래일 target_as_of: requested_as_of는 target_as_of, reference_market_date는
    scanner summary 값을 그대로 report에 전달해야 한다 (재계산하지 않음)."""
    target = "2026-09-12"  # 토요일(비거래일) 가정
    ref_date = "2026-09-11"
    _write_scanner_artifacts(tmp_path, target, _candidate_rows(["000050"]), reference_market_date=ref_date)
    _write_fundamentals_artifact(tmp_path, target, "000050")

    captured: dict = {}

    def _capturing_fake(**kwargs):
        captured.update(kwargs)
        return _fake_generate_stock_report(**kwargs)

    patched_runner.setattr(phase4b, "generate_stock_report", _capturing_fake)
    result = phase4b.run_phase4b(target, root=tmp_path)

    assert captured["as_of"] == target
    assert captured["reference_market_date"] == ref_date
    assert result["requested_as_of"] == target
    assert result["reference_market_date"] == ref_date
