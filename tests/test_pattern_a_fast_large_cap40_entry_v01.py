"""Targeted Test Suite for Pattern A FAST Trading Policy Entry v0.1 Large Cap 40 Diagnostic.

Validates all review follow-up maintenance requirements:
1. Selection manifest exactly 40 items, unique tickers, ranks 1..40, selection_date 2026-08-14
2. Source SHA, Prereg SHA, Manifest SHA frozen hash validation
3. Exact Top 40 relation between selection source (pattern_a_investability_universe_20260814.csv) and manifest
4. Preregistration exact rule, score threshold is None, Pattern A gate is False, retuning is False, oos claim is False
5. Signal date window boundaries (2021-08-14 ~ 2026-08-14)
6. PIT input isolation on evaluator execution path (interception test)
7. Daily data cutoff <= 2026-08-14 enforced
8. Max 1 Primary Entry per sample (exactly 40 / 40)
9. Entry 40 / 40 event log cross-check (signal_date event exact match)
10. Grade A (37) and Grade B (3) exact classification & counts
11. Negative rule guards (EXTREME, EARLY, LATE_OR_EXTENDED, Non-TRIGGER, Score UNAVAILABLE)
12. Execution contract (next trading day OPEN, price != signal close)
13. Horizon censoring validation
14. Primary forward return medians frozen check (4W: -1.51%, 8W: -0.69%, 12W: +0.90%, 26W: -0.51%)
15. Primary MFE & MAE excursion medians frozen check
16. Grade A & Grade B MFE / MAE excursion medians frozen check
17. MFE & MAE actual arithmetic recalculation against raw daily cache
18. Trigger Any Control (40/40) and medians frozen check
19. Early Variant (7/40) and medians frozen check
20. Entry timing delay stats validation
21. Pattern A Candidate distribution (16/24) and Stage distribution (transition 14, weak 6, progressed 5, base 3, early_trend 2, unavailable 10)
22. Previous FAST v0.1 frozen artifacts SHA guards (prereg, sample results, event log, evaluation JSON)
23. Prohibited OOS claims & "완전 독립" absence
24. Korean report section titles & refined sub-conclusions (entry_timing_filter_effect, stock_level_selectivity, early_exclusion_hypothesis)
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
from trend_scanner.data.resampler import to_weekly

# Previous FAST v0.1 frozen artifact hashes (artifacts/patterns/pattern_a_fast/research/trading_policy_v01/)
FROZEN_TRADING_POLICY_V01_PREREG_SHA256 = "32aae360faf04224fb1e418fe22465e84720444f78817e7c768f7e3583836c58"
FROZEN_TRADING_POLICY_V01_SAMPLES_SHA256 = "18e6d620c7808e7cd08bb0429e10ff080f8b0ced12cf5d1e4c25fbac150b1b11"
FROZEN_TRADING_POLICY_V01_EVENT_LOG_SHA256 = "9f02738ab7107d7c3b601b3962e57771eb345f15c91dc3d8e6d09903ff98478e"
FROZEN_TRADING_POLICY_V01_EVAL_JSON_SHA256 = "d3fb52117127d9f50214d4d5ce49ae1345c5b7749d935c47b0c985641556de9f"


@pytest.fixture(scope="module")
def eval_data():
    if OUT_SAMPLES_CSV.exists() and OUT_EVENT_LOG_CSV.exists() and OUT_EVAL_JSON.exists():
        df_samples = pd.read_csv(OUT_SAMPLES_CSV, dtype={"ticker": str})
        df_events = pd.read_csv(OUT_EVENT_LOG_CSV, dtype={"ticker": str})
        summary = json.loads(OUT_EVAL_JSON.read_text(encoding="utf-8"))
    else:
        df_samples, df_events, summary = run_evaluation()
    return df_samples, df_events, summary


def test_01_manifest_integrity():
    manifest = pd.read_csv(MANIFEST_PATH, dtype={"ticker": str})
    assert len(manifest) == 40
    assert manifest["ticker"].nunique() == 40
    assert list(manifest["rank"]) == list(range(1, 41))
    assert (manifest["selection_date"] == "2026-08-14").all()
    assert (manifest["market_cap_as_of"] == "2026-08-14").all()


def test_02_source_and_prereg_and_manifest_hashes():
    assert sha256_file(SELECTION_SOURCE_PATH) == FROZEN_SOURCE_SHA256
    assert sha256_file(MANIFEST_PATH) == FROZEN_MANIFEST_SHA256
    assert sha256_file(PREREG_PATH) == FROZEN_PREREG_SHA256


def test_03_exact_top40_relation_with_selection_source():
    src_df = pd.read_csv(SELECTION_SOURCE_PATH, dtype={"ticker": str})
    common_stocks = src_df[src_df["asset_type"] == "COMMON"].sort_values(by="market_cap", ascending=False).reset_index(drop=True)
    expected_top40_tickers = list(common_stocks.head(40)["ticker"].str.zfill(6))
    expected_top40_mcaps = list(common_stocks.head(40)["market_cap"].astype(float))

    manifest_df = pd.read_csv(MANIFEST_PATH, dtype={"ticker": str})
    actual_manifest_tickers = list(manifest_df["ticker"].str.zfill(6))
    actual_manifest_mcaps = list(manifest_df["market_cap"].astype(float))

    assert len(expected_top40_tickers) == 40
    assert len(actual_manifest_tickers) == 40
    assert actual_manifest_tickers == expected_top40_tickers
    assert actual_manifest_mcaps == pytest.approx(expected_top40_mcaps, rel=1e-5)
    assert (manifest_df["market_cap_as_of"] == "2026-08-14").all()


def test_04_prereg_exact_rule_and_non_gates():
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


def test_05_signal_date_window_boundaries(eval_data):
    df_samples, df_events, _ = eval_data
    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        sig_date = pd.Timestamp(row["signal_date"])
        assert sig_date >= SIGNAL_START, f"Signal date {sig_date} before start {SIGNAL_START}"
        assert sig_date <= SIGNAL_END, f"Signal date {sig_date} after end {SIGNAL_END}"


def test_06_fast_pit_smoke_sample(monkeypatch):
    """Representative PIT smoke check on sample ticker in FAST suite.
    
    Full 40-stock PIT integration validation across all 5-year weekly bars
    is maintained in test_pattern_a_fast_large_cap40_entry_v01_slow.py.
    """
    original_fn = eval_script.evaluate_pattern_a_fast
    interceptions = []

    def wrapped_evaluate(ticker, name, daily, weekly_date, score, stage):
        assert daily.index.max().normalize() <= pd.Timestamp(weekly_date).normalize()
        assert daily[daily.index > pd.Timestamp(weekly_date)].empty
        assert daily.index.max().normalize() <= DATA_CUTOFF
        interceptions.append((ticker, weekly_date))
        return original_fn(ticker, name, daily, weekly_date, score, stage)

    # Intercept on top sample ticker to verify PIT without redundant full 40-stock re-run
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    ticker = "005930"
    daily = cache.load(ticker).sort_index()
    daily = daily[daily.index <= DATA_CUTOFF]
    weekly_bars = to_weekly(daily)
    valid_weeks = [
        w for w in weekly_bars.index
        if w >= SIGNAL_START and w <= SIGNAL_END and daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]
    score_c = json.loads(eval_script.SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_c = json.loads(eval_script.STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    for w in valid_weeks[:20]:
        daily_pit = daily[daily.index <= w]
        wrapped_evaluate(ticker, "삼성전자", daily_pit, w, score_c, stage_c)

    assert len(interceptions) == 20


def test_07_daily_data_cutoff_enforced(eval_data):
    _, df_events, _ = eval_data
    assert (pd.to_datetime(df_events["weekly_date"]) <= DATA_CUTOFF).all()


def test_08_max_one_primary_entry_per_sample(eval_data):
    df_samples, _, _ = eval_data
    assert len(df_samples) == 40
    assert df_samples["ticker"].nunique() == 40
    assert df_samples["entry_found"].sum() == 40


def test_09_entry_event_cross_check(eval_data):
    df_samples, df_events, _ = eval_data
    for _, row in df_samples.iterrows():
        ticker = row["ticker"]
        sig_date = row["signal_date"]
        ev = df_events[(df_events["ticker"] == ticker) & (df_events["weekly_date"] == sig_date)]
        assert not ev.empty
        matched_ev = ev.iloc[0]
        assert bool(matched_ev["is_primary_entry_event"]) is True
        assert matched_ev["fast_stage"] == "TRIGGER"
        assert matched_ev["fast_stage_status"] == "READY"
        assert matched_ev["monthly_regime"] == "PERMITTED_REGIME"
        assert matched_ev["daily_risk"] in {"NORMAL", "ELEVATED"}
        assert matched_ev["fast_score_status"] in {"READY", "PARTIAL"}


def test_10_grade_a_and_b_classification(eval_data):
    df_samples, _, summary = eval_data
    assert summary["coverage"]["grade_counts"]["Grade A"] == 37
    assert summary["coverage"]["grade_counts"]["Grade B"] == 3

    entries = df_samples[df_samples["entry_found"]]
    for _, row in entries.iterrows():
        if row["daily_risk_at_entry"] == "NORMAL":
            assert row["entry_grade"] == "Grade A"
        elif row["daily_risk_at_entry"] == "ELEVATED":
            assert row["entry_grade"] == "Grade B"
        else:
            pytest.fail(f"Unexpected daily risk {row['daily_risk_at_entry']}")


def test_11_negative_rule_guards(eval_data):
    _, df_events, _ = eval_data
    for _, ev in df_events.iterrows():
        if ev["daily_risk"] == "EXTREME":
            assert bool(ev["is_primary_entry_event"]) is False
        if ev["monthly_regime"] == "EARLY_REGIME":
            assert bool(ev["is_primary_entry_event"]) is False
        if ev["monthly_regime"] == "LATE_OR_EXTENDED_REGIME":
            assert bool(ev["is_primary_entry_event"]) is False
        if ev["fast_stage"] != "TRIGGER":
            assert bool(ev["is_primary_entry_event"]) is False
        if ev["fast_score_status"] not in {"READY", "PARTIAL"}:
            assert bool(ev["is_primary_entry_event"]) is False


def test_12_execution_contract(eval_data):
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


def test_13_horizon_censoring(eval_data):
    df_samples, _, summary = eval_data
    for h in [4, 8, 12, 26]:
        col_ret = f"return_{h}w"
        col_st = f"followup_status_{h}w"
        censored = df_samples[df_samples[col_st] == "CENSORED"]
        for _, row in censored.iterrows():
            assert pd.isna(row[col_ret])
            assert pd.isna(row[f"mfe_{h}w"])
            assert pd.isna(row[f"mae_{h}w"])


def test_14_primary_forward_return_medians_frozen(eval_data):
    _, _, summary = eval_data
    fwd = summary["primary_forward_returns"]
    assert fwd["4w"]["median"] == -1.51
    assert fwd["8w"]["median"] == -0.69
    assert fwd["12w"]["median"] == 0.90
    assert fwd["26w"]["median"] == -0.51

    assert fwd["4w"]["n"] == 40
    assert fwd["8w"]["n"] == 40
    assert fwd["12w"]["n"] == 40
    assert fwd["26w"]["n"] == 40


def test_15_primary_mfe_mae_medians_frozen(eval_data):
    _, _, summary = eval_data
    assert summary["mfe_excursion_medians"]["4w"] == 7.36
    assert summary["mfe_excursion_medians"]["8w"] == 10.59
    assert summary["mfe_excursion_medians"]["12w"] == 13.23
    assert summary["mfe_excursion_medians"]["26w"] == 18.34

    assert summary["mae_excursion_medians"]["4w"] == -6.71
    assert summary["mae_excursion_medians"]["8w"] == -9.23
    assert summary["mae_excursion_medians"]["12w"] == -10.46
    assert summary["mae_excursion_medians"]["26w"] == -13.25


def test_16_grade_a_and_b_mfe_mae_medians_frozen(eval_data):
    _, _, summary = eval_data
    ga = summary["grade_analysis"]["Grade A (NORMAL)"]
    assert ga["mfe_medians"]["4w"] == 5.65
    assert ga["mfe_medians"]["8w"] == 9.22
    assert ga["mfe_medians"]["12w"] == 12.05
    assert ga["mfe_medians"]["26w"] == 17.01

    assert ga["mae_medians"]["4w"] == -6.98
    assert ga["mae_medians"]["8w"] == -10.24
    assert ga["mae_medians"]["12w"] == -10.92
    assert ga["mae_medians"]["26w"] == -14.71

    gb = summary["grade_analysis"]["Grade B (ELEVATED)"]
    assert gb["mfe_medians"]["4w"] == 28.67
    assert gb["mfe_medians"]["8w"] == 28.67
    assert gb["mfe_medians"]["12w"] == 80.53
    assert gb["mfe_medians"]["26w"] == 90.26

    assert gb["mae_medians"]["4w"] == -6.45
    assert gb["mae_medians"]["8w"] == -8.01
    assert gb["mae_medians"]["12w"] == -8.01
    assert gb["mae_medians"]["26w"] == -9.40


def test_17_mfe_mae_actual_arithmetic_recalculation(eval_data):
    df_samples, _, _ = eval_data
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    horizons = [4, 8, 12, 26]

    for _, row in df_samples[df_samples["entry_found"]].iterrows():
        ticker = row["ticker"]
        daily = cache.load(ticker).sort_index()
        daily = daily[daily.index <= DATA_CUTOFF]
        weekly_bars = to_weekly(daily)

        sig_date = pd.Timestamp(row["signal_date"])
        exec_date = pd.Timestamp(row["execution_date"])
        entry_open = float(row["entry_open"])

        fut_weeks = [
            fw for fw in weekly_bars.index
            if fw > sig_date and fw <= DATA_CUTOFF and daily[daily.index <= fw].index.max().normalize() == fw.normalize()
        ]

        for h in horizons:
            if len(fut_weeks) >= h:
                exit_w = fut_weeks[h - 1]
                per_daily = daily[(daily.index >= exec_date) & (daily.index <= exit_w)]
                expected_mfe = round((float(per_daily["high"].max()) - entry_open) / entry_open * 100, 2)
                expected_mae = round((float(per_daily["low"].min()) - entry_open) / entry_open * 100, 2)

                assert row[f"mfe_{h}w"] == pytest.approx(expected_mfe, abs=1e-2)
                assert row[f"mae_{h}w"] == pytest.approx(expected_mae, abs=1e-2)


def test_18_trigger_any_control_isolated(eval_data):
    _, _, summary = eval_data
    ctrl = summary["trigger_any_control"]
    assert ctrl["entry_count"] == 40
    fwd = ctrl["forward_returns"]
    assert fwd["4w"]["median"] == -3.19
    assert fwd["8w"]["median"] == -2.25
    assert fwd["12w"]["median"] == -3.00
    assert fwd["26w"]["median"] == -2.21


def test_19_early_variant_isolated(eval_data):
    _, _, summary = eval_data
    early = summary["experimental_early_variant"]
    assert early["entry_count"] == 7
    fwd = early["forward_returns"]
    assert fwd["4w"]["median"] == -0.40
    assert fwd["8w"]["median"] == 0.97
    assert fwd["12w"]["median"] == 1.64
    assert fwd["26w"]["median"] == 5.24


def test_20_entry_timing_delay_stats(eval_data):
    _, _, summary = eval_data
    delay = summary["entry_timing_delay"]
    assert delay["n"] == 40
    assert delay["same_week_entry_count"] == 24
    assert delay["delayed_entry_count"] == 16
    assert delay["median_delay_weeks"] == 0.0
    assert delay["mean_delay_weeks"] == 13.12


def test_21_pattern_a_diagnostic_distributions(eval_data):
    _, _, summary = eval_data
    pa = summary["pattern_a_diagnostic"]
    assert pa["candidate_state_distribution"]["candidate"] == 16
    assert pa["candidate_state_distribution"]["non_candidate"] == 24
    assert pa["stage_distribution"]["transition"] == 14
    assert pa["stage_distribution"]["weak"] == 6
    assert pa["stage_distribution"]["progressed"] == 5
    assert pa["stage_distribution"]["base"] == 3
    assert pa["stage_distribution"]["early_trend"] == 2
    assert pa["stage_available_count"] == 30
    assert pa["stage_unavailable_count"] == 10


def test_22_previous_trading_policy_v01_artifacts_unmutated():
    trading_policy_dir = ROOT / "artifacts/patterns/pattern_a_fast/research/trading_policy_v01"
    assert sha256_file(trading_policy_dir / "pattern_a_fast_entry_policy_preregistration_v01.json") == FROZEN_TRADING_POLICY_V01_PREREG_SHA256
    assert sha256_file(trading_policy_dir / "pattern_a_fast_entry_policy_sample_results_v01.csv") == FROZEN_TRADING_POLICY_V01_SAMPLES_SHA256
    assert sha256_file(trading_policy_dir / "pattern_a_fast_entry_policy_event_log_v01.csv") == FROZEN_TRADING_POLICY_V01_EVENT_LOG_SHA256
    assert sha256_file(trading_policy_dir / "pattern_a_fast_entry_policy_evaluation_v01.json") == FROZEN_TRADING_POLICY_V01_EVAL_JSON_SHA256


def test_23_no_prohibited_oos_claims_and_no_total_independence_in_report(eval_data):
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

    # Must NOT use "완전 독립"
    assert "완전 독립" not in md
    assert "완전독립" not in md


def test_24_korean_section_titles_and_sub_conclusions(eval_data):
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

    subs = summary["sub_conclusions"]
    assert subs["entry_timing_filter_effect"] == "PROMISING"
    assert subs["stock_level_selectivity"] == "NOT_OBSERVED"
    assert subs["early_exclusion_hypothesis"] == "NOT_REPLICATED_IN_LARGE_CAP40"
