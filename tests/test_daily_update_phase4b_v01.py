"""Phase 4B production runner (scripts/run_daily_update_phase4b_v01.py) targeted tests.

Runner orchestration만 검증한다 (Scanner 입력 로딩/검증, 발행 target
집합(continuity ∪ candidate) 계산, staging/promote, fail-closed 처리).
``generate_stock_report()`` 자체의 내부 산식은 기존 test_stock_report*.py /
test_a_fast_core_stock_report.py 스위트가 이미 검증하므로 여기서는 monkeypatch로
대체해 무겁고 느린 실제 전체 리포트 계산을 반복하지 않는다.
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
PREVIOUS = "2026-09-04"
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


_VALID_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"


def _write_previous_corpus(
    root: Path,
    previous_date: str,
    entries: list[tuple[str, str, str | None]],
    *,
    report_version: str = "0.5",
    requested_as_of: str | None = None,
    strategy_id: str | None = _VALID_STRATEGY_ID,
    duplicate_last: bool = False,
) -> Path:
    """entries: [(ticker, asset_type, canonical_position_or_None), ...]

    기본값은 audit_previous_corpus()의 신규 fail-closed 검증을 모두 통과하는
    "정상" previous corpus를 만든다. report_version/requested_as_of/strategy_id를
    명시적으로 다르게 주면 해당 검증 실패 케이스를 재현할 수 있다.
    """
    dt_clean = previous_date.replace("-", "")
    corpus_dir = root / "artifacts/reporting/stock_reports" / dt_clean
    json_dir = corpus_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    effective_as_of = requested_as_of if requested_as_of is not None else previous_date
    for ticker, asset_type, position in entries:
        payload: dict = {
            "ticker": ticker,
            "asset_type": asset_type,
            "report_version": report_version,
            "requested_as_of": effective_as_of,
        }
        if position is not None or strategy_id is not None:
            a_fast_core: dict = {}
            if strategy_id is not None:
                a_fast_core["strategy_id"] = strategy_id
            if position is not None:
                a_fast_core["canonical_position"] = position
            payload["a_fast_core"] = a_fast_core
        (json_dir / f"{ticker}.json").write_text(json.dumps(payload), encoding="utf-8")
        (corpus_dir / f"{ticker}.md").write_text(f"# {ticker}", encoding="utf-8")
    if duplicate_last and entries:
        dup_ticker = entries[-1][0]
        # 동일 ticker로 실제 서로 다른 파일 두 개를 만들어 진짜 "중복 ticker"를 재현한다
        # (파일명이 아니라 JSON 내부 ticker 필드 기준 중복 판정을 검증하기 위함).
        dup_path = json_dir / f"{dup_ticker}__dup.json"
        dup_payload = json.loads((json_dir / f"{dup_ticker}.json").read_text(encoding="utf-8"))
        dup_path.write_text(json.dumps(dup_payload), encoding="utf-8")
    return corpus_dir


def _default_previous_corpus(root: Path, previous_date: str = PREVIOUS) -> Path:
    """target 티커들과 겹치지 않는 최소 previous corpus. continuity에 영향 없이
    ``find_previous_canonical_report_dir`` / ``audit_previous_corpus``가 정상 동작하게 한다."""
    return _write_previous_corpus(root, previous_date, [("900000", "COMMON", "FLAT")])


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


def _rows_with_states(states: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"ticker": t, "name": f"종목{t}", "market": "KOSPI", "candidate_state": s}
        for t, s in states.items()
    ]


# --- A. exact-target scanner artifact만 사용 -------------------------------------


def test_a_loads_exact_target_scanner_artifact_only(tmp_path, patched_runner):
    _default_previous_corpus(tmp_path)
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    # 다른 날짜 scanner artifact가 존재해도 무시되어야 한다.
    _write_scanner_artifacts(tmp_path, "2026-09-10", _candidate_rows(["999999"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["requested_as_of"] == TARGET
    assert result["scanner_candidate_count"] == 1
    assert result["report_target_count"] == 1
    assert result["promoted"] is True


# --- B. wrong-date scanner → fail (previous corpus 조회 이전에 fail-closed) -------


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


def test_b_no_previous_corpus_fails_closed(tmp_path, patched_runner):
    """previous canonical report directory가 전혀 없으면 fail-closed한다."""
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    with pytest.raises(phase4b.Phase4BError, match="PREVIOUS_CORPUS_NOT_FOUND"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


# --- C. scanner 재실행 없음 --------------------------------------------------------


def test_c_scanner_is_never_re_invoked(tmp_path, patched_runner, monkeypatch):
    import trend_scanner.scanner.full_universe_scanner as scanner_module

    def _forbidden(*args, **kwargs):
        raise AssertionError("scan_pattern_a_universe() must not be called by Phase 4B")

    monkeypatch.setattr(scanner_module, "scan_pattern_a_universe", _forbidden)

    _default_previous_corpus(tmp_path)
    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)
    assert result["promoted"] is True


# --- D. candidate_state == CANDIDATE만 선택 (pure function) ------------------------


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


# --- E. 과거 report directory(target 당일)가 target set에 영향 없음 -----------------


def test_e_stale_canonical_directory_is_fully_replaced_not_merged(tmp_path, patched_runner):
    _default_previous_corpus(tmp_path)

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
    _default_previous_corpus(tmp_path)
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


def test_g_f5_ready_inner_as_of_mismatch_fails_closed_even_if_outer_matches(tmp_path):
    """상위 artifact 날짜(payload.requested_as_of)가 맞아도 f5_ready.requested_as_of가
    다르면 fail-closed해야 한다."""
    from trend_scanner.reporting.fundamentals_report import load_fundamentals_section_from_production_artifact

    fund_dir = tmp_path / "artifacts/fundamentals/production" / TARGET.replace("-", "") / "tickers"
    fund_dir.mkdir(parents=True)
    payload = {
        "ticker": "000050",
        "requested_as_of": TARGET,  # outer 일치
        "f5_ready": {
            "applicability": "APPLICABLE", "data_status": "PARTIAL", "reason": None,
            "requested_as_of": "2026-09-04",  # inner 불일치
            "company_family": "NON_FINANCIAL", "currency": "KRW",
            "filter_status": "PASS", "filter_passed": True, "filter_reasons": [],
            "summary": {}, "quarterly": [], "annual": [], "diagnostics": [],
        },
    }
    (fund_dir / "000050.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FundamentalsArtifactUnavailable, match="F5_READY_AS_OF_MISMATCH"):
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
    _write_previous_corpus(tmp_path, "2026-09-01", [("900000", "COMMON", "FLAT")])
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


# ==================================================================================
# Report target continuity (PHASE4B_REPORT_TARGET_CONTINUITY_FIX_V01)
# ==================================================================================


# --- pure function: compute_report_target -----------------------------------------


def test_continuity_a_target_is_intersection_union_candidate():
    """previous COMMON {A,B,C}, current COMMON {A,B,D}, current CANDIDATE {D}
    -> target {A,B,D}."""
    target = phase4b.compute_report_target(
        previous_common={"A", "B", "C"},
        previous_open=set(),
        current_common={"A", "B", "D"},
        current_candidates={"D"},
    )
    assert set(target) == {"A", "B", "D"}


def test_continuity_c_new_candidate_not_in_previous_common_is_included():
    target = phase4b.compute_report_target(
        previous_common={"A"},
        previous_open=set(),
        current_common={"A", "D"},
        current_candidates={"D"},
    )
    assert "D" in target


def test_continuity_d_past_common_dropped_from_current_common_and_not_open_is_excluded():
    """previous COMMON {A,B,C}, C가 current COMMON에 없고 OPEN도 아니면 target에서 제외."""
    target = phase4b.compute_report_target(
        previous_common={"A", "B", "C"},
        previous_open=set(),
        current_common={"A", "B"},
        current_candidates=set(),
    )
    assert "C" not in target
    assert set(target) == {"A", "B"}


def test_continuity_e_previous_open_in_current_common_is_preserved():
    target = phase4b.compute_report_target(
        previous_common={"A", "B"},
        previous_open={"B"},
        current_common={"A", "B"},
        current_candidates=set(),
    )
    assert "B" in target


def test_continuity_e_previous_open_missing_from_current_common_fails_closed():
    with pytest.raises(phase4b.Phase4BError, match="OPEN_POSITION_OUTSIDE_CURRENT_COMMON"):
        phase4b.compute_report_target(
            previous_common={"A", "B"},
            previous_open={"C"},  # OPEN이었지만 current_common에 없음
            current_common={"A", "B"},
            current_candidates=set(),
        )


# --- B. non-COMMON 제외 (audit_previous_corpus 레벨) --------------------------------


def test_continuity_b_previous_non_common_excluded_from_previous_common(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS,
        [
            ("000010", "COMMON", "FLAT"),
            ("500001", "ETF", None),
            ("005935", "PREFERRED", None),
        ],
    )
    audit = phase4b.audit_previous_corpus(corpus_dir)
    assert audit.common == {"000010"}
    assert audit.non_common == {"500001", "005935"}


# --- F. target-day partial(기존 20260917) 무시 -------------------------------------


def test_continuity_f_target_day_partial_directory_never_used_as_previous_source(tmp_path, patched_runner):
    """기존 target 당일(20260917) partial corpus가 있어도 previous source로 쓰지 않는다."""
    _default_previous_corpus(tmp_path, PREVIOUS)
    # target 당일에 잘못 좁게 만들어진 기존 285개짜리 partial-style corpus를 시뮬레이션.
    _write_previous_corpus(tmp_path, TARGET, [("111111", "COMMON", "OPEN")])

    _write_scanner_artifacts(tmp_path, TARGET, _candidate_rows(["000050"]))
    _write_fundamentals_artifact(tmp_path, TARGET, "000050")

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["previous_corpus_dir"].endswith(PREVIOUS.replace("-", ""))
    assert result["promoted"] is True
    # target 당일 partial에만 있던 111111이 continuity로 새어 들어오지 않아야 한다.
    json_tickers = {p.stem for p in (tmp_path / "artifacts/reporting/stock_reports" / TARGET.replace("-", "") / "json").glob("*.json")}
    assert "111111" not in json_tickers


# --- 전체 통합: continuity + candidate 조합이 실제 run_phase4b에 반영되는지 ----------


def test_continuity_full_run_target_includes_continuity_and_candidates(tmp_path, patched_runner):
    _write_previous_corpus(
        tmp_path, PREVIOUS,
        [
            ("000010", "COMMON", "OPEN"),      # continuity 유지 대상(OPEN)
            ("000020", "COMMON", "FLAT"),      # continuity 유지 대상(FLAT, current COMMON에 존재)
            ("000030", "COMMON", "FLAT"),      # current COMMON에서 빠짐, OPEN 아니므로 제외되어야 함
            ("500001", "ETF", None),           # 비COMMON, target 제외
        ],
    )
    rows = _rows_with_states({
        "000010": "watch",       # current에서는 candidate 아님 -> continuity로만 포함
        "000020": "blocked",
        "000040": "candidate",   # 신규 candidate
    })
    _write_scanner_artifacts(tmp_path, TARGET, rows)
    for t in ("000010", "000020", "000040"):
        _write_fundamentals_artifact(tmp_path, TARGET, t)

    result = phase4b.run_phase4b(TARGET, root=tmp_path)

    assert result["promoted"] is True
    assert result["previous_common_count"] == 3
    assert result["previous_open_count"] == 1
    assert result["continuity_count"] == 2  # 000010, 000020 (000030은 current_common에 없음)
    assert result["new_candidate_count"] == 1  # 000040
    assert result["report_target_count"] == 3  # 000010, 000020, 000040
    json_tickers = {p.stem for p in (tmp_path / "artifacts/reporting/stock_reports" / TARGET.replace("-", "") / "json").glob("*.json")}
    assert json_tickers == {"000010", "000020", "000040"}


def test_continuity_open_outside_current_common_fails_closed_end_to_end(tmp_path, patched_runner):
    _write_previous_corpus(
        tmp_path, PREVIOUS,
        [("000030", "COMMON", "OPEN")],  # OPEN인데 current scanner COMMON에서 사라질 예정
    )
    rows = _rows_with_states({"000040": "candidate"})
    _write_scanner_artifacts(tmp_path, TARGET, rows)
    _write_fundamentals_artifact(tmp_path, TARGET, "000040")

    with pytest.raises(phase4b.Phase4BError, match="OPEN_POSITION_OUTSIDE_CURRENT_COMMON"):
        phase4b.run_phase4b(TARGET, root=tmp_path)


# ==================================================================================
# Production Default Final Fix (PHASE4B_PRODUCTION_DEFAULT_FINAL_FIX_V01)
# ==================================================================================


# --- A/B. CLI --max-workers 기본값/override ---------------------------------------


def test_a_cli_default_max_workers_is_4():
    args = phase4b.build_parser().parse_args(["--target-as-of", "2026-09-17"])
    assert args.max_workers == 4


def test_b_cli_explicit_max_workers_1_overrides_default():
    args = phase4b.build_parser().parse_args(["--target-as-of", "2026-09-17", "--max-workers", "1"])
    assert args.max_workers == 1


def test_run_phase4b_internal_default_max_workers_is_still_1():
    """run_phase4b()의 내부 기본값은 그대로 1(순차)이어야 한다 -- CLI 기본값 변경과
    별개로 테스트/직접 호출 호환성을 위해 유지된다."""
    import inspect

    sig = inspect.signature(phase4b.run_phase4b)
    assert sig.parameters["max_workers"].default == 1


# --- C~F. previous canonical corpus fail-closed 검증 -------------------------------


def test_c_previous_corpus_duplicate_ticker_fails_closed(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS, [("900000", "COMMON", "FLAT")], duplicate_last=True,
    )
    with pytest.raises(phase4b.Phase4BError, match="PHASE4B_PREVIOUS_CORPUS_DUPLICATE_TICKER"):
        phase4b.audit_previous_corpus(corpus_dir)


def test_d_previous_corpus_wrong_report_version_fails_closed(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS, [("900000", "COMMON", "FLAT")], report_version="0.4",
    )
    with pytest.raises(phase4b.Phase4BError, match="PHASE4B_PREVIOUS_CORPUS_REPORT_VERSION_MISMATCH"):
        phase4b.audit_previous_corpus(corpus_dir)


def test_e_previous_corpus_wrong_requested_as_of_fails_closed(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS, [("900000", "COMMON", "FLAT")], requested_as_of="2026-09-03",
    )
    with pytest.raises(phase4b.Phase4BError, match="PHASE4B_PREVIOUS_CORPUS_AS_OF_MISMATCH"):
        phase4b.audit_previous_corpus(corpus_dir)


def test_f_previous_corpus_wrong_strategy_id_fails_closed(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS, [("900000", "COMMON", "FLAT")], strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V01",
    )
    with pytest.raises(phase4b.Phase4BError, match="PHASE4B_PREVIOUS_CORPUS_STRATEGY_ID_MISMATCH"):
        phase4b.audit_previous_corpus(corpus_dir)


def test_f_previous_corpus_missing_strategy_id_fails_closed(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS, [("900000", "COMMON", "FLAT")], strategy_id=None,
    )
    with pytest.raises(phase4b.Phase4BError, match="PHASE4B_PREVIOUS_CORPUS_STRATEGY_ID_MISMATCH"):
        phase4b.audit_previous_corpus(corpus_dir)


# --- G. 정상 previous corpus -> PASS -----------------------------------------------


def test_g_valid_previous_corpus_passes_audit(tmp_path):
    corpus_dir = _write_previous_corpus(
        tmp_path, PREVIOUS,
        [("900000", "COMMON", "OPEN"), ("900001", "COMMON", "FLAT"), ("900002", "ETF", None)],
    )
    audit = phase4b.audit_previous_corpus(corpus_dir)
    assert audit.total == 3
    assert audit.common == {"900000", "900001"}
    assert audit.non_common == {"900002"}
    assert audit.open_tickers == {"900000"}


def test_g_default_previous_corpus_fixture_passes_audit(tmp_path):
    """이 테스트 파일의 다른 continuity 테스트들이 쓰는 기본 fixture
    (_default_previous_corpus)도 신규 검증을 통과해야 한다."""
    corpus_dir = _default_previous_corpus(tmp_path)
    audit = phase4b.audit_previous_corpus(corpus_dir)
    assert audit.total == 1
    assert audit.common == {"900000"}


def test_g_real_20260904_corpus_passes_audit_read_only():
    """실제 2026-09-04 canonical corpus(운영 previous source)가 신규 fail-closed
    검증을 통과하는지 read-only로 확인한다."""
    root = Path(__file__).resolve().parents[1]
    corpus_dir = root / "artifacts/reporting/stock_reports/20260904"
    if not corpus_dir.exists():
        pytest.skip("local 20260904 production corpus not present in this environment")
    audit = phase4b.audit_previous_corpus(corpus_dir)
    assert audit.total == 1836
    assert len(audit.common) == 1808
    assert len(audit.non_common) == 28
    assert len(audit.open_tickers) == 232
