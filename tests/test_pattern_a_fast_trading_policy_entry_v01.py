"""Targeted Test Suite for Pattern A FAST Trading Policy Entry v0.1 Maintenance.

Validates all maintenance requirements from Section 8 of w.md:
1. Preregistration SHA256 guard
2. Preregistration exact rule & schema guard
3. Sample count 36 guard
4. Retuning allowed false guard
5. Network requests allowed false guard
6. PIT execution-path interception guard (verifying zero future bars passed to evaluator)
7. Next trading day OPEN execution rule preservation
8. Primary Entry 13 samples invariance
9. Grade A (12) / Grade B (1) invariance
10. Forward returns medians invariance (4W +6.44%, 8W +0.28%, 12W +0.20%, 26W +12.08%)
11. MFE / MAE medians invariance
12. Trigger Any Control invariance
13. Early Variant invariance
14. Markdown renderer dynamically matches summary values (e.g. -0.24%)
15. Markdown contains no 'statistically significant' / 'significantly' claims
16. 기존 frozen 연구 입력값(Manifest/Human Review/Preregistration) 무결성 및 불변 검증
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.evaluate_pattern_a_fast_trading_policy_entry_v01 as eval_script
from scripts.evaluate_pattern_a_fast_trading_policy_entry_v01 import (
    BASE_COMMIT_SHA,
    COMMIT_A_SHA,
    FROZEN_HUMAN_SHA256,
    FROZEN_MANIFEST_SHA256,
    FROZEN_PREREG_SHA256,
    HUMAN_PATH,
    MANIFEST_PATH,
    OUT_EVAL_JSON,
    OUT_EVAL_MD,
    OUT_EVENT_LOG_CSV,
    OUT_SAMPLES_CSV,
    PREREG_PATH,
    ROOT,
    render_markdown,
    run_evaluation,
    sha256_file,
)
from trend_scanner.data.cache import ParquetCache


@pytest.fixture(scope="module")
def eval_data():
    df_samples, df_events, summary = run_evaluation()
    return df_samples, df_events, summary


def test_01_preregistration_sha_guard():
    assert sha256_file(PREREG_PATH) == FROZEN_PREREG_SHA256
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(HUMAN_PATH) == FROZEN_HUMAN_SHA256


def test_02_03_04_05_preregistration_exact_protocol_guards():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert prereg["status"] == "PREREGISTERED_BEFORE_EVALUATION"
    assert prereg["population"] == "FROZEN_INVESTABLE_OOS_B_36"
    assert prereg["sample_count"] == 36
    assert prereg["execution_rule"] == "next_trading_day_open"
    assert prereg["evaluation_start_rule"] == "completed_weekly_reference_date"
    assert prereg["evaluation_end_rule"] == "outcome_review_end"
    assert prereg["first_entry_only"] is True
    assert prereg["forward_horizons_weeks"] == [4, 8, 12, 26]
    assert prereg["mfe_mae_enabled"] is True
    assert prereg["score_threshold"] is None
    assert prereg["pattern_a_entry_gate"] is False
    assert prereg["exit_policy"] == "OUT_OF_SCOPE"
    assert prereg["retuning_allowed"] is False
    assert prereg["network_requests_allowed"] is False

    rule = prereg["primary_entry_rule"]
    assert rule["fast_machine_stage"] == "TRIGGER"
    assert rule["fast_machine_stage_status"] == "READY"
    assert rule["fast_monthly_permission_state"] == "PERMITTED_REGIME"
    assert set(rule["fast_daily_risk_state_in"]) == {"NORMAL", "ELEVATED"}
    assert set(rule["fast_score_status_in"]) == {"READY", "PARTIAL"}


def test_06_pit_interception_execution_path_no_future_bars(monkeypatch):
    """Intercept evaluate_pattern_a_fast during run_evaluation to assert zero future bars passed."""
    original_fn = eval_script.evaluate_pattern_a_fast
    interceptions = []

    def wrapped_evaluate(ticker, name, daily, weekly_date, score, stage):
        # Assert that the maximum date in the daily slice is <= weekly_date
        assert daily.index.max().normalize() <= pd.Timestamp(weekly_date).normalize(), (
            f"Future bar detected: max daily date {daily.index.max()} > weekly date {weekly_date}"
        )
        # Assert that no daily row exceeds weekly_date
        future_rows = daily[daily.index > pd.Timestamp(weekly_date)]
        assert future_rows.empty, f"Future rows found in daily slice for {ticker} at {weekly_date}"

        interceptions.append((ticker, weekly_date, daily.index.max()))
        return original_fn(ticker, name, daily, weekly_date, score, stage)

    monkeypatch.setattr(eval_script, "evaluate_pattern_a_fast", wrapped_evaluate)
    df_samples, df_events, summary = eval_script.run_evaluation()

    assert len(interceptions) > 0
    assert len(interceptions) == len(df_events)


def test_07_next_trading_day_open_rule_maintained(eval_data):
    df_samples, _, _ = eval_data
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        daily = cache.load(row["ticker"]).sort_index()
        sig_date = pd.Timestamp(row["signal_date"])
        exec_date = pd.Timestamp(row["execution_date"])

        assert exec_date > sig_date
        next_dates = daily[daily.index > sig_date].index
        assert exec_date == next_dates[0]

        expected_open = float(daily.loc[exec_date, "open"])
        assert row["entry_open"] == pytest.approx(expected_open, abs=1e-2)

        sig_close = float(daily.loc[sig_date, "close"])
        if sig_close != expected_open:
            assert row["entry_open"] != sig_close


def test_08_09_primary_entry_samples_and_grades_invariance(eval_data):
    """13→14 entry_count 등 아래 기댓값 변경 근거: w.md Fix D §7-§9 원인 분석 결과
    CALENDAR_AUTHORITY_CAUSALITY = CONFIRMED (r.md 참고). INV_OOS_B_029(002350)의
    2025-05-30 signal week가 fix(pit) b5228b5/b9c837f(KRX 실제 시장 월말 거래일
    기준 completed-month authority) 적용으로 monthly_regime이
    EARLY_REGIME -> PERMITTED_REGIME으로 재분류되어 Early Variant에서
    Primary Entry로 이동한 것이 유일한 원인이며, 다른 12개 기존 samples의
    signal_date/execution_date/entry_grade는 완전히 동일하게 유지됨을 확인함."""
    df_samples, _, summary = eval_data
    assert len(df_samples) == 36
    assert summary["coverage"]["entry_count"] == 14
    assert summary["coverage"]["no_entry_count"] == 22
    assert summary["coverage"]["grade_counts"] == {"Grade A": 13, "Grade B": 1}
    assert summary["coverage"]["median_weeks_to_entry"] == 21.5


def test_10_primary_forward_returns_medians_invariance(eval_data):
    """4w만 INV_OOS_B_029 추가로 변경(위 test_08_09 docstring 참고). 8w/12w/26w는
    029의 forward window가 그 horizon까지 도달하지 못해(CENSORED) 완전히 불변."""
    _, _, summary = eval_data
    fwd = summary["primary_forward_returns"]
    assert fwd["4w"]["median"] == 5.84
    assert fwd["4w"]["mean"] == 3.97
    assert fwd["4w"]["positive_rate"] == 53.8

    assert fwd["8w"]["median"] == 0.28
    assert fwd["8w"]["mean"] == 10.01
    assert fwd["8w"]["positive_rate"] == 54.5

    assert fwd["12w"]["median"] == 0.20
    assert fwd["12w"]["mean"] == 4.69
    assert fwd["12w"]["positive_rate"] == 50.0

    assert fwd["26w"]["median"] == 12.08
    assert fwd["26w"]["mean"] == 7.90
    assert fwd["26w"]["positive_rate"] == 75.0


def test_11_mfe_mae_medians_invariance(eval_data):
    """4w MFE/MAE만 INV_OOS_B_029 추가로 변경(위 test_08_09 docstring 참고).
    MAE 4w(-8.34 -> -8.72)는 w.md에 명시되지 않았으나 동일한 원인(029 편입)으로
    확인됨 — r.md에 범위 밖 발견사항으로 별도 기록."""
    _, _, summary = eval_data
    assert summary["mfe_excursion_medians"] == {"4w": 7.96, "8w": 15.46, "12w": 15.71, "26w": 25.49}
    assert summary["mae_excursion_medians"] == {"4w": -8.72, "8w": -8.72, "12w": -11.34, "26w": -15.24}


def test_12_trigger_any_control_invariance(eval_data):
    _, _, summary = eval_data
    ctrl = summary["trigger_any_control"]
    assert ctrl["entry_count"] == 19
    assert ctrl["forward_returns"]["4w"]["median"] == -0.24
    assert ctrl["forward_returns"]["12w"]["median"] == -0.66


def test_13_early_variant_invariance(eval_data):
    """4->3 entry_count: INV_OOS_B_029가 Early Variant에서 Primary Entry로 이동
    (위 test_08_09 docstring 참고). 남은 3개 samples(008/012/013)는 signal_date까지
    완전히 동일. 12w median은 029가 그 horizon에서 이미 CENSORED였기 때문에 불변."""
    _, _, summary = eval_data
    early = summary["experimental_early_variant"]
    assert early["entry_count"] == 3
    assert early["forward_returns"]["4w"]["median"] == -7.90
    assert early["forward_returns"]["12w"]["median"] == -3.47


def test_14_15_markdown_rendering_dynamic_and_no_exaggeration(eval_data):
    df_samples, _, summary = eval_data
    md = render_markdown(summary, df_samples)

    # Verify dynamic control value is present in markdown
    assert "-0.24%" in md
    assert "-0.23%" not in md

    # Verify exaggerated phrases are absent
    assert "significantly" not in md.lower()
    assert "statistically significant" not in md.lower()
    assert "유의미하게 개선" not in md
    assert "통계적으로 개선" not in md
    assert "통계적 유의미" not in md

    # Verify pure Korean section headers
    assert "## 1. 기본 진입 규칙 및 체결 계약" in md
    assert "## 2. 진입 발생률 및 통계" in md
    assert "## 3. 신호 이후 기간별 수익률 및 최대 순행 / 역행 폭" in md
    assert "## 4. 인간 판정 결과별 성과 비교" in md
    assert "## 5. 실험 조건 및 비교군 결과" in md
    assert "## 6. 표본별 세부 결과" in md
    assert "## 7. 최종 연구 결론" in md

    # Verify unnecessary English parentheticals are removed
    assert "(Evaluation Population)" not in md
    assert "(Base Commit)" not in md
    assert "(Coverage & Entry Statistics)" not in md
    assert "(Forward Returns & Excursions)" not in md
    assert "(Human Outcome Stratification)" not in md
    assert "(Variant & Control Comparison)" not in md
    assert "(Sample-by-Sample Results)" not in md
    assert "(Final Research Conclusion)" not in md


def test_16_existing_contracts_and_manifests_unmutated():
    """기존 frozen 연구 입력값(Manifest/Human Review/Preregistration) 무결성 및 불변 검증."""
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(HUMAN_PATH) == FROZEN_HUMAN_SHA256
    assert sha256_file(PREREG_PATH) == FROZEN_PREREG_SHA256
