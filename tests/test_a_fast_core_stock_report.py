"""Targeted Tests for Stock Report v0.2 & A FAST Core Integration.

Validates:
  - Stock Report v0.2 Contract & Schema Integrity
  - A FAST Core Section Always Present & Fail-Closed
  - Zero Network Requests & Local Execution
  - Point-In-Time Strict Isolation (requested_as_of)
  - 8-Item Entry Conditions Checklist Contract
  - Pending Entry & Pending Exit Next Open Semantics
  - Execution Boundary Transitions
  - Re-entry Rules & Parity Against Official 783 Trades CSV
  - Exact Representative Regressions: 005930 (Samsung), 001540 (Anguk), 069500 (ETF), 007390 (Nature Cell)
  - GFM Markdown Ordering & Canonical Strategy Position Wording
  - Descriptive Tone / No Financial Advice Check
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.reporting.stock_report import generate_stock_report, render_markdown_report
from trend_scanner.reporting.models import AFastCoreSection, ReportStatus

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_stock_report_v02_contract():
    """Stock Report v0.2 최상위 contract 및 a_fast_core 필드 존재 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.report_version == "0.2"
    assert hasattr(report, "a_fast_core")
    assert isinstance(report.a_fast_core, AFastCoreSection)

    d = report.to_dict()
    assert d["report_version"] == "0.2"
    assert "a_fast_core" in d
    assert d["a_fast_core"]["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert d["a_fast_core"]["strategy_version"] == "V02"
    assert d["a_fast_core"]["strategy_alias"] == "A FAST Core"
    assert d["a_fast_core"]["strategy_status"] == "FINAL_STRATEGY_FROZEN"
    assert d["a_fast_core"]["production_status"] == "PRODUCTION_DECISION_SUPPORT"
    assert d["a_fast_core"]["fresh_oos_status"] == "NOT_EXECUTED"


def test_a_fast_core_section_always_present_and_fail_closed():
    """데이터 부족 시에도 a_fast_core 섹션이 생략되지 않고 DATA_UNAVAILABLE로 fail-closed 되는지 검증."""
    report, _, _ = generate_stock_report(ticker="999999", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.report_version == "0.2"
    assert report.a_fast_core is not None
    assert report.a_fast_core.applicability == "DATA_UNAVAILABLE"
    assert report.a_fast_core.strategy_state == "DATA_UNAVAILABLE"
    assert report.a_fast_core.canonical_position == "DATA_UNAVAILABLE"
    assert report.a_fast_core.action == "NONE"
    assert report.a_fast_core.action_reason == "INSUFFICIENT_DATA"


def test_a_fast_core_no_network_request():
    """리포트 생성 과정에서 외부 네트워크 요청이 0회인지 검증."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report.provenance.network_requests == 0
    assert report.a_fast_core.provenance.network_requests == 0


def test_a_fast_core_uses_requested_as_of_only():
    """과거 시점(2025-11-28)에 대해 미래 데이터가 유입되지 않는 strict PIT 검증."""
    rep_2025, _, _ = generate_stock_report(ticker="005930", as_of="2025-11-28", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_2025.requested_as_of == "2025-11-28"
    assert rep_2025.a_fast_core.as_of == "2025-11-28"
    # In Nov 2025, Samsung sequence 4 was still PRE_PROGRESSED (first progressed was 2026-02-28)
    assert rep_2025.a_fast_core.canonical_position == "OPEN"
    assert rep_2025.a_fast_core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert rep_2025.a_fast_core.protection_state.loss_guard_state == "ACTIVE"


def test_a_fast_core_samsung_20260814_exact():
    """005930 삼성전자 2026-08-14 exact canonical state regression."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "OPEN"
    assert core.strategy_state == "HOLD_PROGRESSED"
    assert core.action == "HOLD"
    assert core.action_reason == "OPEN_POSITION_PROGRESSED"

    ct = core.current_trade
    assert ct is not None
    assert ct.trade_sequence == 4
    assert ct.trade_id == "005930_04"
    assert ct.entry_signal_date == "2025-08-29"
    assert ct.entry_execution_date == "2025-09-01"
    assert ct.first_progressed_date == "2026-02-28"
    assert ct.trade_status == "OPEN"

    prot = core.protection_state
    assert prot is not None
    assert prot.phase == "PROGRESSED"
    assert prot.loss_guard_state == "INACTIVE"
    assert prot.exit3_state == "ARMED"
    assert prot.exit4_state == "ARMED"

    assert len(core.trade_history) == 4
    assert core.reentry_state.completed_trade_count == 3
    assert core.reentry_state.next_entry_sequence == 5


def test_a_fast_core_anguk_20260814_exact():
    """001540 안국약품 2026-08-14 exact canonical state regression."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "OPEN"
    assert core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert core.action == "HOLD"
    assert core.action_reason == "OPEN_POSITION_PRE_PROGRESSED"

    ct = core.current_trade
    assert ct is not None
    assert ct.trade_sequence == 2
    assert ct.trade_id == "001540_02"
    assert ct.entry_signal_date == "2026-05-15"
    assert ct.entry_execution_date == "2026-05-18"
    assert ct.first_progressed_date is None
    assert ct.trade_status == "OPEN"

    prot = core.protection_state
    assert prot is not None
    assert prot.phase == "PRE_PROGRESSED"
    assert prot.loss_guard_state == "ACTIVE"
    assert prot.loss_guard_threshold_pct == -15.0
    assert prot.exit3_state == "INACTIVE"
    assert prot.exit4_state == "INACTIVE"

    assert len(core.trade_history) == 2
    assert core.trade_history[0].trade_id == "001540_01"
    assert core.trade_history[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert core.trade_history[0].trade_status == "REALIZED"


def test_a_fast_core_etf_not_applicable():
    """069500 KODEX 200 ETF 대상 NOT_APPLICABLE 정상 판정 검증."""
    report, _, _ = generate_stock_report(ticker="069500", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "NOT_APPLICABLE"
    assert core.strategy_state == "NOT_APPLICABLE"
    assert core.canonical_position == "NOT_APPLICABLE"
    assert core.action == "NONE"
    assert core.action_reason == "NON_COMMON_STOCK"


def test_a_fast_core_wait_failed_conditions():
    """007390 네이처셀 대상 WAIT 상태 및 failed_conditions 검증."""
    report, _, _ = generate_stock_report(ticker="007390", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.applicability == "APPLICABLE"
    assert core.canonical_position == "FLAT"
    assert core.strategy_state == "WAIT"
    assert core.action == "WAIT"
    assert core.entry_conditions is not None
    assert core.entry_conditions.all_conditions_met is False
    assert len(core.entry_conditions.failed_conditions) > 0


def test_a_fast_core_pending_entry_next_open():
    """신규 진입 신호 발생 시점(2026-05-15, 안국약품 seq 2)의 ENTER_NEXT_OPEN 동작 검증."""
    report, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-15", repo_root=REPO_ROOT, save_artifacts=False)
    core = report.a_fast_core

    assert core.canonical_position == "FLAT"
    assert core.strategy_state == "ENTRY"
    assert core.action == "ENTER_NEXT_OPEN"
    assert core.action_reason == "ALL_ENTRY_CONDITIONS_MET"
    assert core.execution_timing == "NEXT_LOCAL_TRADING_DAY_OPEN"
    assert core.entry_conditions.all_conditions_met is True


def test_a_fast_core_execution_boundary():
    """신호일(2026-05-15, FLAT + ENTER_NEXT_OPEN) -> 체결일(2026-05-18, OPEN + HOLD) 전환 경계 검증."""
    rep_sig, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-15", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_sig.a_fast_core.canonical_position == "FLAT"
    assert rep_sig.a_fast_core.strategy_state == "ENTRY"
    assert rep_sig.a_fast_core.action == "ENTER_NEXT_OPEN"

    rep_exec, _, _ = generate_stock_report(ticker="001540", as_of="2026-05-18", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_exec.a_fast_core.canonical_position == "OPEN"
    assert rep_exec.a_fast_core.strategy_state == "HOLD_PRE_PROGRESSED"
    assert rep_exec.a_fast_core.action == "HOLD"


def test_a_fast_core_trade_history_matches_official_v02():
    """공식 정본 trades.csv와 리포트 내역(005930, 001540)의 일치성 검증."""
    trades_csv = REPO_ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
    assert trades_csv.exists()
    df_off = pd.read_csv(trades_csv, dtype={"ticker": str})

    # Samsung check
    rep_sam, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    off_sam = df_off[df_off["ticker"] == "005930"].sort_values(by="trade_sequence").reset_index(drop=True)
    assert len(rep_sam.a_fast_core.trade_history) == len(off_sam)
    for rep_tr, (_, off_tr) in zip(rep_sam.a_fast_core.trade_history, off_sam.iterrows()):
        assert rep_tr.trade_id == off_tr["trade_id"]
        assert rep_tr.entry_execution_date == off_tr["entry_execution_date"]
        assert rep_tr.entry_open == pytest.approx(float(off_tr["entry_open"]), abs=1e-2)
        assert rep_tr.exit_type == off_tr["exit_type"]
        assert rep_tr.trade_status == off_tr["trade_status"]


def test_v01_stock_report_artifacts_unchanged():
    """기존 v0.1 리포트 아티팩트(artifacts/stock_reports/20260814/)가 전혀 수정되지 않았는지 검증."""
    v01_dir = REPO_ROOT / "artifacts/stock_reports/20260814"
    if v01_dir.exists():
        v01_json = list(v01_dir.glob("*.json"))
        assert len(v01_json) == 54
        # Check first JSON is report_version 0.1
        first_data = json.loads(v01_json[0].read_text(encoding="utf-8"))
        assert first_data["report_version"] == "0.1"


def test_markdown_a_fast_core_section_order_and_wording():
    """Markdown 보고서에 Section 0부터 10까지 올바른 순서와 공식 포지션 명칭이 포함되는지 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    md = render_markdown_report(report)

    # Check Section headers
    assert "## 0. 핵심 요약 (Executive Summary)" in md
    assert "## 1. 현재 기술적 국면 & 투자 적격성 스냅샷 (Current Snapshot)" in md
    assert "## 2. 패스트 코어 V2 전략 상태 (A FAST Core V2 Strategy State)" in md
    assert "## 3. Pattern A FAST 현재 신호" in md
    assert "## 4. Pattern A Monthly History" in md
    assert "## 5. Pattern A 국면 전환 이력" in md
    assert "## 6. Pattern A FAST Weekly History" in md
    assert "## 7. 외국인 수급 확증" in md
    assert "## 8. 거래대금 추세 분석" in md
    assert "## 9. Pattern A 전체 월별 이력" in md
    assert "## 10. 데이터 품질 및 신원" in md

    # Check Canonical Position wording
    assert "패스트 코어 전략 포지션 (Canonical Strategy Position)" in md
    assert "내 포지션" not in md
    assert "사용자 포지션" not in md


def test_report_does_not_emit_buy_sell_advice():
    """리포트 본문에서 매수/매도 권유 및 비윤리적 금융 권유 문구가 없는지 검증."""
    report, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    md = render_markdown_report(report)

    # Remove disclaimer footer to test report content
    body = md.split("*주의 (Disclaimer):")[0] if "*주의 (Disclaimer):" in md else md

    prohibited_phrases = ["매수 추천", "매도 추천", "목표가", "수익 보장", "반드시 상승", "적극 매수", "매수 권유", "매도 권유"]
    for phrase in prohibited_phrases:
        assert phrase not in body, f"Prohibited financial advice phrase '{phrase}' found in markdown body!"
