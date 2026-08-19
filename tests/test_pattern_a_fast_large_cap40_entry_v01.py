"""Targeted Test Suite for Pattern A FAST Trading Policy Entry v0.1 Large Cap 40 Diagnostic.

Validates all 34 requirements from Section 29 of w.md:
1. Selection manifest exactly 40 items
2. Unique ticker count exactly 40
3. Ranks 1 to 40
4. Selection date 2026-08-14
5. Market-cap source hash check
6. Preregistration hash check
7. Primary Rule exact match
8. No score threshold
9. No Pattern A gate
10. Signal date >= 2021-08-14
11. Signal date <= 2026-08-14
12. PIT input isolation on evaluator execution path
13. Daily data cutoff <= 2026-08-14
14. Max 1 Primary Entry per sample
15. Grade A (NORMAL Risk) correctness
16. Grade B (ELEVATED Risk) correctness
17. EXTREME Risk never triggers Primary Entry
18. EARLY_REGIME never triggers Primary Entry
19. LATE_OR_EXTENDED never triggers Primary Entry
20. Non-TRIGGER stages never trigger Primary Entry
21. Score UNAVAILABLE never triggers Primary Entry
22. execution_date > signal_date
23. execution_date is next immediate trading day
24. entry_price matches exact OPEN
25. No execution beyond data cutoff
26. Cutoff boundary execution handling
27. 4W, 8W, 12W, 26W censoring
28. MFE excursion arithmetic
29. MAE excursion arithmetic and negative sign
30. Trigger Any Control isolated
31. Early Variant isolated
32. Previous FAST v0.1 frozen artifacts SHA unchanged
33. Prohibited OOS validation claims absent
34. Korean report section titles validated
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.evaluate_pattern_a_fast_large_cap40_entry_v01 as eval_script
from scripts.evaluate_pattern_a_fast_large_cap40_entry_v01 import (
    BASE_COMMIT_SHA,
    COMMIT_A_SHA,
    DATA_CUTOFF,
    FROZEN_MANIFEST_SHA256,
    FROZEN_PREREG_SHA256,
    FROZEN_SOURCE_SHA256,
    MANIFEST_PATH,
    OUT_EVAL_JSON,
    OUT_EVAL_MD,
    OUT_EVENT_LOG_CSV,
    OUT_SAMPLES_CSV,
    PREREG_PATH,
    ROOT,
    SELECTION_SOURCE_PATH,
    SIGNAL_END,
    SIGNAL_START,
    render_markdown,
    run_evaluation,
    sha256_file,
)
from trend_scanner.data.cache import ParquetCache

FROZEN_TRADING_POLICY_V01_PREREG_SHA256 = "32aae360faf04224fb1e418fe22465e84720444f78817e7c768f7e3583836c58"


@pytest.fixture(scope="module")
def eval_data():
    df_samples, df_events, summary = run_evaluation()
    return df_samples, df_events, summary


def test_01_02_03_04_manifest_integrity():
    manifest = pd.read_csv(MANIFEST_PATH, dtype={"ticker": str})
    assert len(manifest) == 40
    assert manifest["ticker"].nunique() == 40
    assert list(manifest["rank"]) == list(range(1, 41))
    assert (manifest["selection_date"] == "2026-08-14").all()
    assert (manifest["market_cap_as_of"] == "2026-08-14").all()


def test_05_06_source_and_prereg_hashes():
    assert sha256_file(SELECTION_SOURCE_PATH) == FROZEN_SOURCE_SHA256
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(PREREG_PATH) == FROZEN_PREREG_SHA256


def test_07_08_09_prereg_exact_rule_and_non_gates():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert prereg["score_threshold"] is None
    assert prereg["pattern_a_entry_gate"] is False
    assert prereg["retuning_allowed"] is False
    assert prereg["oos_claim_allowed"] is False

    rule = prereg["primary_entry_rule"]
    assert rule["fast_machine_stage"] == "TRIGGER"
    assert rule["fast_machine_stage_status"] == "READY"
    assert rule["fast_monthly_permission_state"] == "PERMITTED_REGIME"
    assert set(rule["fast_daily_risk_state_in"]) == {"NORMAL", "ELEVATED"}
    assert set(rule["fast_score_status_in"]) == {"READY", "PARTIAL"}


def test_10_11_signal_date_window_boundaries(eval_data):
    df_samples, df_events, _ = eval_data
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        sig_date = pd.Timestamp(row["signal_date"])
        assert sig_date >= SIGNAL_START, f"Signal date {sig_date} before start {SIGNAL_START}"
        assert sig_date <= SIGNAL_END, f"Signal date {sig_date} after end {SIGNAL_END}"


def test_12_pit_interception_execution_path(monkeypatch):
    original_fn = eval_script.evaluate_pattern_a_fast
    interceptions = []

    def wrapped_evaluate(ticker, name, daily, weekly_date, score, stage):
        assert daily.index.max().normalize() <= pd.Timestamp(weekly_date).normalize()
        assert daily[daily.index > pd.Timestamp(weekly_date)].empty
        assert daily.index.max().normalize() <= DATA_CUTOFF
        interceptions.append((ticker, weekly_date))
        return original_fn(ticker, name, daily, weekly_date, score, stage)

    monkeypatch.setattr(eval_script, "evaluate_pattern_a_fast", wrapped_evaluate)
    df_samples, df_events, summary = eval_script.run_evaluation()

    assert len(interceptions) > 0
    assert len(interceptions) == len(df_events)


def test_13_daily_data_cutoff_enforced(eval_data):
    _, df_events, _ = eval_data
    assert (pd.to_datetime(df_events["weekly_date"]) <= DATA_CUTOFF).all()


def test_14_max_one_primary_entry_per_sample(eval_data):
    df_samples, _, _ = eval_data
    assert len(df_samples) == 40
    assert df_samples["ticker"].nunique() == 40


def test_15_16_grade_a_and_b_classification(eval_data):
    df_samples, _, summary = eval_data
    entries = df_samples[df_samples["entry_found"]]
    for _, row in entries.iterrows():
        if row["daily_risk_at_entry"] == "NORMAL":
            assert row["entry_grade"] == "Grade A"
        elif row["daily_risk_at_entry"] == "ELEVATED":
            assert row["entry_grade"] == "Grade B"
        else:
            pytest.fail(f"Unexpected daily risk {row['daily_risk_at_entry']}")


def test_17_18_19_20_21_negative_rule_guards(eval_data):
    _, df_events, _ = eval_data
    for _, ev in df_events.iterrows():
        if ev["daily_risk"] == "EXTREME":
            assert ev["is_primary_entry_event"] is False
        if ev["monthly_regime"] == "EARLY_REGIME":
            assert ev["is_primary_entry_event"] is False
        if ev["monthly_regime"] == "LATE_OR_EXTENDED_REGIME":
            assert ev["is_primary_entry_event"] is False
        if ev["fast_stage"] != "TRIGGER":
            assert ev["is_primary_entry_event"] is False
        if ev["fast_score_status"] not in {"READY", "PARTIAL"}:
            assert ev["is_primary_entry_event"] is False


def test_22_23_24_25_26_execution_contract(eval_data):
    df_samples, _, _ = eval_data
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        daily = cache.load(row["ticker"]).sort_index()
        sig_date = pd.Timestamp(row["signal_date"])
        exec_date = pd.Timestamp(row["execution_date"])

        assert exec_date > sig_date
        assert exec_date <= DATA_CUTOFF

        next_dates = daily[daily.index > sig_date].index
        assert exec_date == next_dates[0]

        expected_open = float(daily.loc[exec_date, "open"])
        assert row["entry_open"] == pytest.approx(expected_open, abs=1e-2)

        sig_close = float(daily.loc[sig_date, "close"])
        if sig_close != expected_open:
            assert row["entry_open"] != sig_close


def test_27_horizon_censoring(eval_data):
    df_samples, _, summary = eval_data
    for h in [4, 8, 12, 26]:
        col_ret = f"return_{h}w"
        col_st = f"followup_status_{h}w"
        censored = df_samples[df_samples[col_st] == "CENSORED"]
        for _, row in censored.iterrows():
            assert pd.isna(row[col_ret])
            assert pd.isna(row[f"mfe_{h}w"])
            assert pd.isna(row[f"mae_{h}w"])


def test_28_29_mfe_mae_arithmetic(eval_data):
    df_samples, _, _ = eval_data
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        for h in [4, 8, 12, 26]:
            if row[f"followup_status_{h}w"] == "COMPLETED":
                assert row[f"mfe_{h}w"] >= -1e-4
                assert row[f"mae_{h}w"] <= 1e-4


def test_30_31_control_and_early_variants_isolated(eval_data):
    _, _, summary = eval_data
    assert summary["trigger_any_control"]["entry_count"] == 40
    assert summary["experimental_early_variant"]["entry_count"] == 7


def test_32_previous_trading_policy_v01_prereg_unmutated():
    prev_prereg = ROOT / "artifacts/pattern_a_fast/trading_policy_v01/pattern_a_fast_entry_policy_preregistration_v01.json"
    assert sha256_file(prev_prereg) == FROZEN_TRADING_POLICY_V01_PREREG_SHA256


def test_33_no_prohibited_oos_claims_in_report(eval_data):
    df_samples, _, summary = eval_data
    md = render_markdown(summary, df_samples)

    # Must contain clear research limitations
    assert "연구 한계" in md
    assert "독립 OOS" in md or "OOS 검증이 아닙니다" in md

    # Must NOT claim OOS validation or statistical significance
    assert "oos validation" not in md.lower()
    assert "virgin oos" not in md.lower()
    assert "independent oos proof" not in md.lower()
    assert "prospective validation" not in md.lower()
    assert "statistically significant" not in md.lower()
    assert "유의미하게 개선" not in md


def test_34_korean_section_titles_rendered(eval_data):
    df_samples, _, summary = eval_data
    md = render_markdown(summary, df_samples)

    assert "## 1. 평가 모집단" in md
    assert "## 2. 진입 정책" in md
    assert "## 3. 진입 발생률" in md
    assert "## 4. 기간별 수익률" in md
    assert "## 5. 최대 순행 / 역행 폭" in md
    assert "## 6. 등급별 결과" in md
    assert "## 7. 비교군 결과 (Trigger Any Control)" in md
    assert "## 8. 조기 진입 실험군 (Early Variant)" in md
    assert "## 9. Pattern A 진단" in md
    assert "## 10. 표본별 결과" in md
    assert "## 11. 연구 한계" in md
    assert "## 12. 최종 결론" in md
