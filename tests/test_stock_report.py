"""Targeted Tests for Stock Report Contract v0.1 & Generator (Final Sealing).

- Monthly Close Parity & PIT Exact Date Contract
- Missing Exact Close Fail-Closed (No Nearest-Day Fallback)
- Full History All Available Months Coverage (Not Truncated to 24M)
- Initial Insufficient Lookback (Price Present vs Score Unavailable)
- First Available Pattern A Metadata
- Market Calendar Unavailable -> PARTIAL Report Status
- Exact Report Status Semantics (READY, PARTIAL, DATA_UNAVAILABLE)
- GitHub Flavored Markdown (GFM) Tables (Close Column & No ASCII Box Lines)
- Existing Parity Preservation (001540 Current Snapshot, Flow, TV, Transitions)
- Zero Artifact Mutation & Zero Network Requests
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.flow.foreign_flow import FlowDataStatus, ForeignFlowFeatureResult
from trend_scanner.reporting.models import (
    CurrentSnapshot,
    FlowState,
    ForeignFlowSection,
    MonthlyObservation,
    ReportHeader,
    ReportStatus,
    ReportSummary,
    StockReport,
    TradingValueFlowSection,
    TradingValueState,
)
from trend_scanner.reporting.stock_report import (
    _determine_trading_value_state_and_explanation,
    _get_reference_market_month_ends,
    _resolve_latest_local_as_of,
    generate_stock_report,
    render_markdown_report,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def report_001540_20260814() -> StockReport:
    """TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_V01 (P1): 이 파일에서
    (ticker=001540, as_of=2026-08-14, repo_root=REPO_ROOT, save_artifacts=False)
    조합으로 read-only assertion만 하는 test 9개가 각자 generate_stock_report()를
    반복 호출하던 것을 이 module-scoped fixture 하나로 통합한다. Mutation이나
    monkeypatch가 있는 test(예: 결정론 검증, tmp_path 격리 검증)는 이 fixture를
    사용하지 않고 그대로 독립 호출을 유지한다."""
    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    return report


def _get_dir_hashes(dir_path: Path) -> dict[str, str]:
    hashes = {}
    if not dir_path.exists():
        return hashes
    for p in sorted(dir_path.glob("**/*")):
        if p.is_file() and not p.name.startswith("."):
            hashes[str(p.relative_to(dir_path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


def test_stock_report_current_snapshot_canonical_parity(report_001540_20260814: StockReport):
    """001540 안국약품의 2026-08-14 기준 current snapshot이 정본 값과 일치하는지 검증."""
    report = report_001540_20260814

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


def test_stock_report_monthly_close_parity(report_001540_20260814: StockReport):
    """001540의 각 MonthlyObservation.close가 로컬 일봉 exact date close와 일치하는지 검증."""
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    df_raw = cache.load("001540")
    report = report_001540_20260814

    full = report.monthly_history.full_monthly_history
    check_dates = ["2021-08-31", "2024-07-31", "2025-08-29", "2026-06-30", "2026-07-31"]
    for dt in check_dates:
        obs = next((o for o in full if o.as_of == dt), None)
        assert obs is not None, f"Missing observation for {dt}"
        expected_close = float(df_raw.loc[dt, "close"])
        assert obs.close == pytest.approx(expected_close, abs=1e-2)


def test_stock_report_missing_exact_close(tmp_path):
    """특정 market month end row가 결측된 경우 close/score가 None이며 fail-closed 되는지 검증."""
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    df_raw = cache.load("001540")
    df_missing = df_raw.drop(index=pd.Timestamp("2026-07-31"))

    tmp_cache_dir = tmp_path / "data/raw/stocks"
    tmp_cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_cache = ParquetCache(base_dir=tmp_cache_dir)
    tmp_cache.save("001540", df_missing)
    df_samsung = cache.load("005930")
    tmp_cache.save("005930", df_samsung)

    report, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2026-08-14",
        repo_root=tmp_path,
        save_artifacts=False,
    )

    obs_july = next((o for o in report.monthly_history.full_monthly_history if o.as_of == "2026-07-31"), None)
    assert obs_july is not None
    assert obs_july.close is None
    assert obs_july.score is None
    assert obs_july.stage == "UNAVAILABLE"
    assert obs_july.candidate_state == "insufficient_data"
    assert obs_july.data_available is False
    assert obs_july.reason == "NO_EXACT_MARKET_MONTH_END_OBSERVATION"


def test_stock_report_full_history_coverage(report_001540_20260814: StockReport):
    """001540 기준 로컬 가격 데이터 최초 월부터 requested_as_of까지 60개월 전체가 생성되는지 검증."""
    report = report_001540_20260814

    hist = report.monthly_history
    assert hist.history_start_as_of == "2021-08-31"
    assert hist.history_end_as_of == "2026-07-31"
    assert hist.observation_count == 60
    assert len(hist.full_monthly_history) == 60
    assert hist.recent_12m_observation_count == 13


def test_stock_report_initial_insufficient_lookback(report_001540_20260814: StockReport):
    """초기 lookback 부족 구간에서 가격(close)은 존재하고 Pattern A Score/Stage는 UNAVAILABLE인지 검증."""
    report = report_001540_20260814

    obs_first = report.monthly_history.full_monthly_history[0]
    assert obs_first.as_of == "2021-08-31"
    assert obs_first.close == 12300.0
    assert obs_first.score is None
    assert obs_first.stage == "UNAVAILABLE"
    assert obs_first.candidate_state == "insufficient_data"
    assert obs_first.data_available is False
    assert obs_first.reason == "INSUFFICIENT_LOOKBACK"


def test_stock_report_first_available_pattern_a(report_001540_20260814: StockReport):
    """001540 기준 최초 Pattern A 산출월 및 산출 가능 개월 수 메타데이터 검증."""
    report = report_001540_20260814

    hist = report.monthly_history
    assert hist.first_pattern_a_available_as_of == "2024-07-31"
    assert hist.pattern_a_available_observation_count == 25


def test_stock_report_market_calendar_unavailable_report_status(tmp_path):
    """005930 reference market calendar가 없을 때 MARKET_CALENDAR_UNAVAILABLE 및 PARTIAL 상태 전이 검증."""
    cache = ParquetCache(base_dir=REPO_ROOT / "data/raw/stocks")
    df_001540 = cache.load("001540")

    tmp_cache_dir = tmp_path / "data/raw/stocks"
    tmp_cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_cache = ParquetCache(base_dir=tmp_cache_dir)
    tmp_cache.save("001540", df_001540)
    # Note: 005930 is intentionally NOT saved to tmp_cache

    with patch("trend_scanner.reporting.stock_report._get_reference_market_month_ends", return_value=[]):
        report, _, _ = generate_stock_report(
            ticker="001540",
            as_of="2026-08-14",
            repo_root=tmp_path,
            save_artifacts=False,
        )

    assert report.data_quality.quality_status == "MARKET_CALENDAR_UNAVAILABLE"
    assert report.header.report_status == ReportStatus.PARTIAL
    assert report.monthly_history.full_monthly_history == []


def test_stock_report_status_exact_contract_semantics(report_001540_20260814: StockReport):
    """Report status exact contract semantics (READY vs PARTIAL vs DATA_UNAVAILABLE)."""
    # 1. 001540 is INVESTABLE and all ready -> READY
    assert report_001540_20260814.header.report_status == ReportStatus.READY

    # 2. 033560 is FILTERED_MARKET_CAP and has all data ready -> READY
    report_filtered, _, _ = generate_stock_report(ticker="033560", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report_filtered.header.report_status == ReportStatus.READY

    # 3. Core unavailable (999999) -> DATA_UNAVAILABLE
    report_unavail, _, _ = generate_stock_report(ticker="999999", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert report_unavail.header.report_status == ReportStatus.DATA_UNAVAILABLE


def test_stock_report_gfm_tables(report_001540_20260814: StockReport):
    """Markdown 렌더링 결과가 GitHub Flavored Markdown (GFM) table 문법을 따르며 종가 컬럼을 포함하는지 검증."""
    md = render_markdown_report(report_001540_20260814)

    # Check GFM table headers and separators with close column
    assert "| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |" in md
    assert "|---|---:|---:|---|---|---|" in md
    assert "| 구간 | 순매수 금액 | 거래대금 대비 강도 | 양수 거래일 |" in md
    assert "|---|---:|---:|---:|" in md
    assert "| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |" in md
    assert "|---|---:|---:|---|---|---|---|" in md

    # Check that NO ASCII box border lines exist (+---+)
    assert "+---" not in md
    assert "+---+" not in md
    assert "+===" not in md


def test_stock_report_historical_pit_isolation(report_001540_20260814: StockReport):
    """과거 시점(2025-11-28)의 점수 산출 시 미래(2026년) 데이터가 영향을 주지 않는지 PIT 독립성 검증."""
    report = report_001540_20260814

    obs_nov_2025 = next((o for o in report.monthly_history.full_monthly_history if o.as_of == "2025-11-28"), None)
    assert obs_nov_2025 is not None
    assert obs_nov_2025.score == 74.16
    assert obs_nov_2025.stage == "TRANSITION"
    assert obs_nov_2025.candidate_state == "candidate"

    report_pit, _, _ = generate_stock_report(
        ticker="001540",
        as_of="2025-11-28",
        repo_root=REPO_ROOT,
        save_artifacts=False,
    )
    assert report_pit.current_snapshot.pattern_a_score == 74.16
    assert report_pit.current_snapshot.official_stage == "TRANSITION"


def test_stock_report_stage_transitions(report_001540_20260814: StockReport):
    """국면 전환 이벤트가 연속된 중복 없이 올바르게 추출되는지 검증."""
    report = report_001540_20260814

    transitions = report.monthly_history.stage_transitions
    assert len(transitions) >= 5

    for tr in transitions:
        assert tr.from_stage != tr.to_stage

    last_tr = transitions[-1]
    assert last_tr.to_stage == "EARLY_TREND"
    assert last_tr.from_stage == "TRANSITION"
    assert last_tr.as_of == "2026-07-31"


def test_stock_report_foreign_flow_parity(report_001540_20260814: StockReport):
    """Phase 11 외국인 수급 피처 및 상태 판정 검증."""
    flow = report_001540_20260814.foreign_flow
    assert flow.data_status == "READY"
    assert flow.flow_state == FlowState.FLOW_ACCUMULATION
    assert flow.foreign_net_buy_value_1d_krw == pytest.approx(37190115.0, abs=1.0)
    assert flow.foreign_net_buy_value_5d_krw == pytest.approx(686119595.0, abs=1.0)
    assert flow.foreign_net_buy_value_20d_krw == pytest.approx(1126081525.0, abs=1.0)
    assert flow.foreign_net_buy_value_60d_krw == pytest.approx(1685532055.0, abs=1.0)
    assert flow.foreign_flow_intensity_5d == pytest.approx(0.0665, abs=1e-4)


def test_stock_report_trading_value_arithmetic(report_001540_20260814: StockReport):
    """거래대금 5D, 20D, 60D 평균 및 비율 연산 검증."""
    tv = report_001540_20260814.trading_value_flow
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
        REPO_ROOT / "artifacts/patterns/pattern_a/production/investability",
        REPO_ROOT / "artifacts/patterns/pattern_a/production/flow",
        REPO_ROOT / "artifacts/patterns/pattern_a/validation/relative_strength",
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


def test_stock_report_default_output_path_is_canonical(tmp_path):
    """generate_stock_report()의 output_dir 미지정 시 기본 저장 경로가
    artifacts/reporting/stock_reports/<YYYYMMDD>/ (버전 디렉터리 없는 canonical 구조)인지 검증.
    실제 production artifact를 건드리지 않기 위해 isolated repo_root(tmp_path)에
    필요한 read-only 입력 디렉터리만 symlink한 fake root를 사용한다."""
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    (fake_root / "data").symlink_to(REPO_ROOT / "data")
    (fake_root / "artifacts").mkdir()
    for name in ("investability", "flow", "pattern_a_fast"):
        (fake_root / "artifacts" / name).symlink_to(REPO_ROOT / "artifacts" / name)

    report, json_path, md_path = generate_stock_report(
        ticker="005930",
        as_of="2026-08-14",
        repo_root=fake_root,
        save_artifacts=True,
    )

    assert json_path is not None and md_path is not None
    assert json_path.parent == fake_root / "artifacts/reporting/stock_reports/20260814"
    assert json_path.parent == md_path.parent
    assert "v0.2" not in str(json_path)
    assert json_path.exists()
    assert md_path.exists()


def test_stock_report_candidate_state_contract_weak_and_progressed():
    """Candidate state contract: 000020(WEAK) -> blocked, 005930(PROGRESSED) -> late."""
    rep_weak, _, _ = generate_stock_report(ticker="000020", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_weak.current_snapshot.official_stage == "WEAK"
    assert rep_weak.current_snapshot.candidate_state == "blocked"

    rep_prog, _, _ = generate_stock_report(ticker="005930", as_of="2026-08-14", repo_root=REPO_ROOT, save_artifacts=False)
    assert rep_prog.current_snapshot.official_stage == "PROGRESSED"
    assert rep_prog.current_snapshot.candidate_state == "late"


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

    assert "시가총액 기준 미달" in report.summary.headline
    assert "제외" in report.summary.headline
    assert "충족하지 못했습니다" in report.summary.bullet_points[2]
    assert "조건을 통과했습니다" not in report.summary.combined_narrative
