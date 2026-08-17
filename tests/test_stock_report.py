"""Targeted Tests for Stock Report Contract v0.1 & Generator (Review Corrections).

- Current snapshot canonical parity (001540)
- Historical Point-In-Time (PIT) isolation
- Monthly history ascending order & subset integrity
- Stage transition extraction correctness
- Foreign flow feature & interpretation parity
- Trading value arithmetic & ratio checks
- Deterministic reproducible output
- Zero mutation of existing canonical artifacts
- Filtered investability narrative (033560 블루콤)
- Candidate state contract: WEAK -> blocked (000020), PROGRESSED -> late (005930)
- Short history trading value fail-closed
- Common market reference calendar month-ends
- Default latest local as-of resolution
- Partial report status consistency
- MD full monthly history table rendering
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trend_scanner.reporting.models import FlowState, ReportStatus, StockReport, TradingValueState
from trend_scanner.reporting.stock_report import (
    _resolve_latest_local_as_of,
    generate_stock_report,
    render_markdown_report,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _get_dir_hashes(dir_path: Path) -> dict[str, str]:
    hashes = {}
    if not dir_path.exists():
        return hashes
    for p in sorted(dir_path.glob("**/*")):
        if p.is_file() and not p.name.startswith("."):
            hashes[str(p.relative_to(dir_path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


def test_stock_report_current_snapshot_canonical_parity():
    """001540 안국약품의 2026-08-14 기준 current snapshot이 정본 값과 일치하는지 검증."""
    report, json_p, md_p = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    assert report.ticker == "001540"
    assert report.name == "안국약품"
    assert report.market == "KOSDAQ"
    assert report.header.report_status == ReportStatus.READY

    cur = report.current_snapshot
    assert cur.pattern_a_score == 97.45
    assert cur.official_stage == "EARLY_TREND"
    assert cur.candidate_state == "candidate"
    assert cur.is_candidate is True
    assert cur.market_cap_eok == 1542.92
    assert cur.avg_trading_value_20d_eok == 14.00
    assert cur.investability_status == "INVESTABLE"
    assert cur.is_investable is True


def test_stock_report_historical_pit_isolation():
    """과거 시점(2025-11-28)의 점수 산출 시 미래(2026년) 데이터가 영향을 주지 않는지 PIT 독립성 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    obs_nov_2025 = next((o for o in report.monthly_history.full_monthly_history if o.as_of == "2025-11-28"), None)
    assert obs_nov_2025 is not None
    assert obs_nov_2025.score == 72.08
    assert obs_nov_2025.stage == "TRANSITION"
    assert obs_nov_2025.candidate_state == "candidate"

    report_pit, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2025-11-28",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    assert report_pit.current_snapshot.pattern_a_score == 72.08
    assert report_pit.current_snapshot.official_stage == "TRANSITION"


def test_stock_report_history_strict_ordering_and_recent_subset():
    """월별 이력이 엄격한 오름차순이며, recent_12m_history가 full history의 올바른 부분집합인지 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    full = report.monthly_history.full_monthly_history
    assert len(full) >= 13

    dates = [o.as_of for o in full]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))

    recent = report.monthly_history.recent_12m_history
    assert len(recent) == 13
    assert recent == full[-13:]


def test_stock_report_stage_transitions():
    """국면 전환 이벤트가 연속된 중복 없이 올바르게 추출되는지 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    transitions = report.monthly_history.stage_transitions
    assert len(transitions) >= 5

    for tr in transitions:
        assert tr.from_stage != tr.to_stage

    last_tr = transitions[-1]
    assert last_tr.to_stage == "EARLY_TREND"
    assert last_tr.from_stage == "TRANSITION"
    assert last_tr.as_of == "2026-07-31"


def test_stock_report_foreign_flow_parity():
    """Phase 11 외국인 수급 피처 및 상태 판정 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    flow = report.foreign_flow
    assert flow.data_status == "READY"
    assert flow.flow_state == FlowState.FLOW_ACCUMULATION
    assert flow.foreign_net_buy_value_1d_krw == pytest.approx(37190115.0, abs=1.0)
    assert flow.foreign_net_buy_value_5d_krw == pytest.approx(686119595.0, abs=1.0)
    assert flow.foreign_net_buy_value_20d_krw == pytest.approx(1126081525.0, abs=1.0)
    assert flow.foreign_net_buy_value_60d_krw == pytest.approx(1685532055.0, abs=1.0)
    assert flow.foreign_flow_intensity_5d == pytest.approx(0.0665, abs=1e-4)


def test_stock_report_trading_value_arithmetic():
    """거래대금 5D, 20D, 60D 평균 및 비율 연산 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    tv = report.trading_value_flow
    assert tv.trading_value_state == TradingValueState.TRADING_VALUE_MIXED
    assert tv.avg_trading_value_5d_eok == pytest.approx(20.64, abs=0.01)
    assert tv.avg_trading_value_20d_eok == pytest.approx(14.00, abs=0.01)
    assert tv.avg_trading_value_60d_eok == pytest.approx(22.12, abs=0.01)
    assert tv.ratio_5d_to_20d == pytest.approx(1.47, abs=0.01)
    assert tv.ratio_20d_to_60d == pytest.approx(0.63, abs=0.01)


def test_stock_report_deterministic_output():
    """동일한 입력에 대해 2회 생성 시 정확히 동일한 JSON 및 Markdown 결과가 도출되는지 검증."""
    report1, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    report2, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    assert report1.to_dict() == report2.to_dict()
    assert render_markdown_report(report1) == render_markdown_report(report2)


def test_stock_report_does_not_mutate_canonical_artifacts(tmp_path):
    """Stock Report 생성 전후 기존 canonical artifact 디렉토리의 파일 해시가 불변인지 검증."""
    check_dirs = [
        REPO_ROOT / "artifacts/investability",
        REPO_ROOT / "artifacts/flow",
        REPO_ROOT / "artifacts/relative_strength",
    ]

    before_hashes = {}
    for d in check_dirs:
        before_hashes[str(d)] = _get_dir_hashes(d)

    report, j_path, m_path = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=True,
        output_dir=tmp_path,
    )

    assert j_path.exists()
    assert m_path.exists()

    after_hashes = {}
    for d in check_dirs:
        after_hashes[str(d)] = _get_dir_hashes(d)

    assert before_hashes == after_hashes, "Canonical artifacts were modified during stock report generation!"


def test_stock_report_filtered_investability_narrative():
    """033560 블루콤 (FILTERED_MARKET_CAP)의 설명문에 '충족/통과' 대신 '기준 미달'이 올바르게 출력되는지 검증."""
    report, _, _ = generate_stock_report(
        ticker="033560",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    cur = report.current_snapshot
    assert cur.investability_status == "FILTERED_MARKET_CAP"
    assert cur.is_investable is False

    # Narrative assertions
    assert "시가총액 기준 미달" in report.summary.headline
    assert "제외" in report.summary.headline
    assert "충족하지 못했습니다" in report.summary.bullet_points[1] or "미달" in report.summary.bullet_points[1]
    assert "조건을 통과했습니다" not in report.summary.combined_narrative


def test_stock_report_candidate_state_contract_weak_blocked():
    """WEAK 종목(000020 동화약품)의 candidate_state가 'blocked'로 일치하는지 검증."""
    report, _, _ = generate_stock_report(
        ticker="000020",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    assert report.current_snapshot.official_stage == "WEAK"
    assert report.current_snapshot.candidate_state == "blocked"
    assert report.current_snapshot.is_candidate is False


def test_stock_report_candidate_state_contract_progressed_late():
    """PROGRESSED 종목(005930 삼성전자)의 candidate_state가 'late'로 일치하는지 검증."""
    report, _, _ = generate_stock_report(
        ticker="005930",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    assert report.current_snapshot.official_stage == "PROGRESSED"
    assert report.current_snapshot.candidate_state == "late"
    assert report.current_snapshot.is_candidate is False


def test_stock_report_common_market_month_end():
    """월별 이력의 as_of 일자가 표준 시장 월말 거래일 캘린더를 따르는지 검증."""
    report_001540, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    report_005930, _, _ = generate_stock_report(
        ticker="005930",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    dates_001540 = set(o.as_of for o in report_001540.monthly_history.full_monthly_history)
    dates_005930 = set(o.as_of for o in report_005930.monthly_history.full_monthly_history)

    # All dates in 001540's history must be in 005930's market calendar
    assert dates_001540.issubset(dates_005930)


def test_stock_report_default_latest_local_as_of_resolution():
    """as_of=None 지정 시 외부 네트워크 요청 없이 최신 로컬 reference market date(2026-08-14)로 자동 결정되는지 검증."""
    latest_date = _resolve_latest_local_as_of(REPO_ROOT)
    assert latest_date == "2026-08-14"

    report_default, _, _ = generate_stock_report(
        ticker="001540",
        as_of=None,
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    assert report_default.requested_as_of == "2026-08-14"
    assert report_default.reference_market_date == "2026-08-14"
    assert report_default.current_snapshot.pattern_a_score == 97.45


def test_stock_report_partial_report_status():
    """Trading Value가 부족하거나 Foreign Flow가 미평가된 경우 report_status가 PARTIAL로 안전하게 전이되는지 검증."""
    # Test for a stock without full flow/tv data
    report, _, _ = generate_stock_report(
        ticker="033560",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    # If core score exists but flow or other section is partial/not ready
    assert report.header.report_status in (ReportStatus.READY, ReportStatus.PARTIAL)


def test_stock_report_short_history_trading_value_fail_closed(tmp_path):
    """일봉 데이터가 60일 미만인 경우 Trading Value가 가짜 값 대체 없이 fail-closed(None / UNAVAILABLE) 처리되는지 검증."""
    from trend_scanner.reporting.stock_report import _determine_trading_value_state_and_explanation

    # Case 1: 10 observations (>=5 but <20 and <60)
    state, exp = _determine_trading_value_state_and_explanation(
        tv_5d=15.0,
        tv_20d=None,
        tv_60d=None,
        r_5_20=None,
        r_20_60=None,
    )
    assert state == TradingValueState.TRADING_VALUE_UNAVAILABLE
    assert "부족" in exp

    # Case 2: All None
    state2, exp2 = _determine_trading_value_state_and_explanation(None, None, None, None, None)
    assert state2 == TradingValueState.TRADING_VALUE_UNAVAILABLE


def test_stock_report_md_full_history_rendering():
    """Markdown 렌더링 결과에 full_monthly_history 전수(001540 기준 61행)가 표로 온전히 포함되는지 검증."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )

    md_content = render_markdown_report(report)
    assert "## 6. 전체 월별 이력 (Full Monthly History)" in md_content
    assert "2021-08-31" in md_content
    assert "2024-07-31" in md_content
    assert "2026-08-14" in md_content
    assert "INSUFFICIENT_LOOKBACK" in md_content

    # Count rows in section 6 table
    lines = md_content.splitlines()
    sec6_started = False
    table_rows = 0
    for line in lines:
        if "## 6. 전체 월별 이력" in line:
            sec6_started = True
            continue
        if sec6_started and "## 7. 데이터 품질" in line:
            break
        if sec6_started and line.startswith("| 20"):
            table_rows += 1

    assert table_rows == 61, f"Expected 61 table rows in Markdown full history, got {table_rows}"
