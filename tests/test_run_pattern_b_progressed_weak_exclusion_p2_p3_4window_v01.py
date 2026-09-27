from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01 as study


def test_p1_reference_is_frozen_and_matches_the_requested_commit() -> None:
    metadata, summary = study._verify_p1_reference(study.ROOT)

    assert summary["verdict"] == study.P1_REFERENCE_VERDICT
    assert summary["window"]["window_id"] == "P1"
    assert metadata["study_id"] == "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_SIMPLE_V01"


def test_five_window_report_renders_core_and_resolved_terminal_synthesis() -> None:
    _, p1 = study._verify_p1_reference(study.ROOT)
    summaries = {
        window_id: {
            **p1,
            "verdict": f"PATTERN_B_PROGRESSED_WEAK_FILTER_{window_id.replace('-', '_')}_IMPROVED",
        }
        for window_id in study.WINDOW_IDS
    }
    synthesis = pd.DataFrame([
        study._window_synthesis_row(window_id, summary)
        for window_id, summary in {"P1": p1, **summaries}.items()
    ])
    p1_terminal = study._terminal_row("P1", study._terminal_stats(study.ROOT, study.P1_REFERENCE_ROOT))
    terminal_rows = [
        {**p1_terminal, "window": window_id} for window_id in ("P1", *study.WINDOW_IDS)
    ]

    report = study._root_report(p1, summaries, synthesis, pd.DataFrame(terminal_rows))

    assert "5-Window 핵심 지표" in report
    assert "Resolved-terminal 보조 sensitivity" in report
    assert "P2-1 → P2-2" in report
    assert "TEST 평균" in report
    assert "전체 5개 window 중 TEST 평균" in report
    assert "전체 5개 window 중 승률" in report
    assert "전체 5개 window 중 중앙값" in report
    assert "P2/P3 tail 재현성" in report
    assert "다음 연구 단계 유지 근거" in report
    assert "| Window | +30 | +50 | +100 | -30 | -40 | -50 | -60 |" in report


def test_resolved_terminal_metrics_combine_realized_and_exact_open_marks(tmp_path) -> None:
    pd.DataFrame([
        {"trade_status": "REALIZED", "gross_return_pct": 40.0},
        {"trade_status": "REALIZED", "gross_return_pct": -45.0},
    ]).to_csv(tmp_path / "control_trade_ledger.csv", index=False)
    pd.DataFrame([
        {"trade_status": "REALIZED", "gross_return_pct": 60.0},
    ]).to_csv(tmp_path / "test_trade_ledger.csv", index=False)
    pd.DataFrame([
        {"valuation_status": "MARKED_EXACT_CUTOFF_CLOSE", "mark_to_cutoff_gross_return_pct": 30.0},
        {"valuation_status": "UNRESOLVED", "mark_to_cutoff_gross_return_pct": None},
    ]).to_csv(tmp_path / "control_open_positions.csv", index=False)
    pd.DataFrame([
        {"valuation_status": "MARKED_EXACT_CUTOFF_CLOSE", "mark_to_cutoff_gross_return_pct": -60.0},
        {"valuation_status": "UNRESOLVED", "mark_to_cutoff_gross_return_pct": None},
    ]).to_csv(tmp_path / "test_open_positions.csv", index=False)

    result = study._terminal_stats(tmp_path.parent, tmp_path.relative_to(tmp_path.parent))

    assert result["control"]["resolved_terminal_n"] == 3
    assert result["control"]["median_pct"] == 30.0
    assert abs(result["control"]["positive_rate_pct"] - 200.0 / 3) < 1e-9
    assert result["control"]["unresolved_open_count"] == 1
    assert result["test"]["resolved_terminal_n"] == 2
    assert result["test"]["le_60_count"] == 1
    assert result["test"]["unresolved_open_count"] == 1
