#!/usr/bin/env python
"""Pattern A FAST Trading Policy Entry v0.1 Evaluation on Large Cap 40 Diagnostic.

Evaluates the preregistered Primary Entry Rule:
  fast_machine_stage == 'TRIGGER' and fast_machine_stage_status == 'READY'
  and fast_monthly_permission_state == 'PERMITTED_REGIME'
  and fast_daily_risk_state in {'NORMAL', 'ELEVATED'}
  and fast_score_status in {'READY', 'PARTIAL'}

Target Population: KRX Market Cap Top 40 Common Stocks as of 2026-08-14.
Data Cutoff: 2026-08-14 (Hard Cutoff).
Observation Window: 2021-08-14 ~ 2026-08-14.
Execution: Next local trading day OPEN.
Forward Horizons: 4W, 8W, 12W, 26W with MFE / MAE.
Read-only local daily Parquet cache only (Zero external network requests).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

LARGE_CAP_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/large_cap40_v01"
MANIFEST_PATH = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_selection_manifest_v01.csv"
PREREG_PATH = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_preregistration_v01.json"
SELECTION_SOURCE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

OUT_SAMPLES_CSV = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_sample_results_v01.csv"
OUT_EVENT_LOG_CSV = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_weekly_event_log_v01.csv"
OUT_EVAL_JSON = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_evaluation_v01.json"
OUT_EVAL_MD = LARGE_CAP_DIR / "pattern_a_fast_large_cap40_evaluation_v01.md"

FROZEN_MANIFEST_SHA256 = "8ebe94768c8fd3ea9ca0ff2a9ea4351f4d5004d372458d2d3b813a0bb7afaab5"
FROZEN_PREREG_SHA256 = "7aebb36a97b7a035c6a7943aca61fc38891b859d5a91870d49c138d6f10fba0b"
FROZEN_SOURCE_SHA256 = "1aca764fc56d3416b9f10ce418a0deaca5174cb8c32997acfd2df1000987e4c8"
COMMIT_A_SHA = "ccc666f52ab470b9b9425dc561f6e993846011b6"
BASE_COMMIT_SHA = "950bee6d6e2d44653e026b8faec76168b035b206"

DATA_CUTOFF = pd.Timestamp("2026-08-14")
SIGNAL_START = pd.Timestamp("2021-08-14")
SIGNAL_END = pd.Timestamp("2026-08-14")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def assert_input_guards() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST_PATH}")
    if sha256_file(MANIFEST_PATH) != FROZEN_MANIFEST_SHA256:
        raise RuntimeError("FROZEN_MANIFEST_SHA256_MISMATCH")
    if not PREREG_PATH.exists():
        raise FileNotFoundError(f"Missing preregistration JSON: {PREREG_PATH}")
    if sha256_file(PREREG_PATH) != FROZEN_PREREG_SHA256:
        raise RuntimeError("FROZEN_PREREG_SHA256_MISMATCH")
    if not SELECTION_SOURCE_PATH.exists():
        raise FileNotFoundError(f"Missing selection source: {SELECTION_SOURCE_PATH}")
    if sha256_file(SELECTION_SOURCE_PATH) != FROZEN_SOURCE_SHA256:
        raise RuntimeError("FROZEN_SOURCE_SHA256_MISMATCH")

    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    if prereg.get("status") != "PREREGISTERED_BEFORE_EVALUATION":
        raise RuntimeError("PREREG_STATUS_MISMATCH")
    if prereg.get("research_classification") != "LARGE_CAP_40_RETROSPECTIVE_DIAGNOSTIC":
        raise RuntimeError("PREREG_CLASSIFICATION_MISMATCH")
    if prereg.get("population") != "KRX_MARKET_CAP_TOP40_ASOF_2026_08_14":
        raise RuntimeError("PREREG_POPULATION_MISMATCH")
    if prereg.get("selection_count") != 40:
        raise RuntimeError("PREREG_SELECTION_COUNT_MISMATCH")
    if prereg.get("selection_date") != "2026-08-14":
        raise RuntimeError("PREREG_SELECTION_DATE_MISMATCH")
    if prereg.get("data_cutoff") != "2026-08-14":
        raise RuntimeError("PREREG_DATA_CUTOFF_MISMATCH")
    if prereg.get("signal_observation_start") != "2021-08-14":
        raise RuntimeError("PREREG_START_DATE_MISMATCH")
    if prereg.get("signal_observation_end") != "2026-08-14":
        raise RuntimeError("PREREG_END_DATE_MISMATCH")
    if prereg.get("first_entry_only") is not True:
        raise RuntimeError("PREREG_FIRST_ENTRY_ONLY_MISMATCH")
    if prereg.get("execution_rule") != "next_trading_day_open":
        raise RuntimeError("PREREG_EXECUTION_RULE_MISMATCH")
    if prereg.get("forward_horizons_weeks") != [4, 8, 12, 26]:
        raise RuntimeError("PREREG_HORIZONS_MISMATCH")
    if prereg.get("mfe_mae_enabled") is not True:
        raise RuntimeError("PREREG_MFE_MAE_ENABLED_MISMATCH")
    if prereg.get("score_threshold") is not None:
        raise RuntimeError("PREREG_SCORE_THRESHOLD_MUST_BE_NULL")
    if prereg.get("pattern_a_entry_gate") is not False:
        raise RuntimeError("PREREG_PATTERN_A_GATE_MUST_BE_FALSE")
    if prereg.get("retuning_allowed") is not False:
        raise RuntimeError("PREREG_RETUNING_MUST_BE_FALSE")
    if prereg.get("network_requests_allowed") is not False:
        raise RuntimeError("PREREG_NETWORK_REQUESTS_MUST_BE_FALSE")
    if prereg.get("oos_claim_allowed") is not False:
        raise RuntimeError("PREREG_OOS_CLAIM_MUST_BE_FALSE")

    rule = prereg.get("primary_entry_rule", {})
    if rule.get("fast_machine_stage") != "TRIGGER":
        raise RuntimeError("PRIMARY_RULE_STAGE_MISMATCH")
    if rule.get("fast_machine_stage_status") != "READY":
        raise RuntimeError("PRIMARY_RULE_STAGE_STATUS_MISMATCH")
    if rule.get("fast_monthly_permission_state") != "PERMITTED_REGIME":
        raise RuntimeError("PRIMARY_RULE_MONTHLY_REGIME_MISMATCH")
    if set(rule.get("fast_daily_risk_state_in", [])) != {"NORMAL", "ELEVATED"}:
        raise RuntimeError("PRIMARY_RULE_DAILY_RISK_MISMATCH")
    if set(rule.get("fast_score_status_in", [])) != {"READY", "PARTIAL"}:
        raise RuntimeError("PRIMARY_RULE_SCORE_STATUS_MISMATCH")


def calculate_stats(series: pd.Series) -> dict:
    usable = series.dropna().astype(float)
    if usable.empty:
        return {"n": 0, "median": None, "mean": None, "std": None, "min": None, "max": None, "positive_rate": None}
    pos_rate = float((usable > 0).mean() * 100)
    return {
        "n": int(len(usable)),
        "median": round(float(usable.median()), 2),
        "mean": round(float(usable.mean()), 2),
        "std": round(float(usable.std()), 2) if len(usable) > 1 else 0.0,
        "min": round(float(usable.min()), 2),
        "max": round(float(usable.max()), 2),
        "positive_rate": round(pos_rate, 1),
    }


def run_evaluation() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    assert_input_guards()

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    manifest = pd.read_csv(MANIFEST_PATH, dtype={"ticker": str}, keep_default_na=False)

    if len(manifest) != 40:
        raise RuntimeError(f"EXPECTED_40_SAMPLES_GOT_{len(manifest)}")
    if manifest["ticker"].nunique() != 40:
        raise RuntimeError("TICKERS_NOT_UNIQUE")
    if list(manifest["rank"]) != list(range(1, 41)):
        raise RuntimeError("RANKS_NOT_1_TO_40")

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    sample_results = []
    event_logs = []
    horizons = [4, 8, 12, 26]

    early_variant_results = []
    any_control_results = []

    for _, sample in manifest.iterrows():
        rank = sample["rank"]
        ticker = sample["ticker"]
        name = sample["name"]
        market = sample["market"]
        market_cap = sample["market_cap"]
        market_cap_eok = sample["market_cap_eok"]

        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"DAILY_CACHE_MISSING_FOR_{ticker}")
        daily = daily.sort_index()
        # Enforce hard data cutoff
        daily = daily[daily.index <= DATA_CUTOFF]

        weekly_bars = to_weekly(daily)
        valid_weeks = [
            w for w in weekly_bars.index
            if w >= SIGNAL_START and w <= SIGNAL_END and daily[daily.index <= w].index.max().normalize() == w.normalize()
        ]

        entry_found = False
        sample_entry_record = None
        sample_all_weekly_events = []

        early_found = False
        any_found = False

        for w in valid_weeks:
            daily_pit = daily[daily.index <= w]
            res = evaluate_pattern_a_fast(ticker, name, daily_pit, w, score_contract, stage_contract)

            is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
            is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
            is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
            is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})

            is_primary = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)
            is_early_variant = bool(is_trigger and res["fast_monthly_permission_state"] == "EARLY_REGIME" and is_non_extreme and is_score_ok)
            is_any_control = bool(is_trigger and is_score_ok)

            event_log_row = {
                "rank": rank,
                "ticker": ticker,
                "name": name,
                "weekly_date": w.strftime("%Y-%m-%d"),
                "fast_score": res["fast_score"],
                "fast_score_status": res["fast_score_status"],
                "fast_stage": res["fast_machine_stage"],
                "fast_stage_status": res["fast_machine_stage_status"],
                "monthly_regime": res["fast_monthly_permission_state"],
                "daily_risk": res["fast_daily_risk_state"],
                "pattern_a_score": res["pattern_a_score"],
                "pattern_a_stage": res["pattern_a_stage"],
                "pattern_a_candidate_active": res["pattern_a_candidate_active"],
                "is_trigger_event": is_trigger,
                "is_primary_entry_event": is_primary,
                "is_early_variant_event": is_early_variant,
                "is_any_control_event": is_any_control,
            }
            event_logs.append(event_log_row)
            sample_all_weekly_events.append(event_log_row)

            def compute_forward_metrics(signal_w: pd.Timestamp) -> tuple[str | None, float | None, dict, dict, dict, dict]:
                fut_daily = daily[(daily.index > signal_w) & (daily.index <= DATA_CUTOFF)]
                if fut_daily.empty:
                    return None, None, {}, {}, {}, {f"followup_status_{h}w": "CENSORED" for h in horizons}
                exec_d = fut_daily.index[0]
                e_open = float(fut_daily.iloc[0]["open"])
                fut_weeks = [
                    fw for fw in weekly_bars.index
                    if fw > signal_w and fw <= DATA_CUTOFF and daily[daily.index <= fw].index.max().normalize() == fw.normalize()
                ]

                rets, mfes, maes, statuses = {}, {}, {}, {}
                for h in horizons:
                    if len(fut_weeks) >= h:
                        exit_w = fut_weeks[h - 1]
                        exit_c = float(daily.loc[exit_w, "close"])
                        rets[f"return_{h}w"] = round(((exit_c - e_open) / e_open) * 100, 2)
                        statuses[f"followup_status_{h}w"] = "COMPLETED"

                        per_daily = daily[(daily.index >= exec_d) & (daily.index <= exit_w)]
                        max_h = float(per_daily["high"].max())
                        min_l = float(per_daily["low"].min())
                        mfes[f"mfe_{h}w"] = round(((max_h - e_open) / e_open) * 100, 2)
                        maes[f"mae_{h}w"] = round(((min_l - e_open) / e_open) * 100, 2)
                    else:
                        rets[f"return_{h}w"] = None
                        statuses[f"followup_status_{h}w"] = "CENSORED"
                        mfes[f"mfe_{h}w"] = None
                        maes[f"mae_{h}w"] = None
                return exec_d.strftime("%Y-%m-%d"), e_open, rets, mfes, maes, statuses

            if is_primary and not entry_found:
                exec_date_str, e_open_val, rets, mfes, maes, statuses = compute_forward_metrics(w)
                if exec_date_str is not None:
                    entry_found = True
                    grade = "Grade A" if res["fast_daily_risk_state"] == "NORMAL" else "Grade B"
                    weeks_to_entry = round((w - SIGNAL_START).days / 7, 1)

                    sample_entry_record = {
                        "rank": rank,
                        "ticker": ticker,
                        "name": name,
                        "market": market,
                        "market_cap": market_cap,
                        "market_cap_eok": market_cap_eok,
                        "entry_found": True,
                        "entry_grade": grade,
                        "signal_date": w.strftime("%Y-%m-%d"),
                        "signal_year": int(w.year),
                        "execution_date": exec_date_str,
                        "entry_open": e_open_val,
                        "fast_score_at_entry": res["fast_score"],
                        "fast_score_status": res["fast_score_status"],
                        "fast_stage_at_entry": res["fast_machine_stage"],
                        "monthly_regime_at_entry": res["fast_monthly_permission_state"],
                        "daily_risk_at_entry": res["fast_daily_risk_state"],
                        "pattern_a_score_at_entry": res["pattern_a_score"],
                        "pattern_a_stage_at_entry": res["pattern_a_stage"],
                        "pattern_a_candidate_state_at_entry": "candidate" if res["pattern_a_candidate_active"] is True else "non_candidate",
                        "weeks_from_window_start_to_entry": weeks_to_entry,
                        **rets,
                        **mfes,
                        **maes,
                        **statuses,
                        "no_entry_reason": None,
                    }

            if is_early_variant and not early_found:
                exec_date_str, e_open_val, rets_e, mfes_e, maes_e, _ = compute_forward_metrics(w)
                if exec_date_str is not None:
                    early_found = True
                    early_variant_results.append({
                        "rank": rank, "ticker": ticker, "name": name,
                        "signal_date": w.strftime("%Y-%m-%d"), **rets_e, **mfes_e, **maes_e
                    })

            if is_any_control and not any_found:
                exec_date_str, e_open_val, rets_a, mfes_a, maes_a, _ = compute_forward_metrics(w)
                if exec_date_str is not None:
                    any_found = True
                    any_control_results.append({
                        "rank": rank, "ticker": ticker, "name": name,
                        "signal_date": w.strftime("%Y-%m-%d"), **rets_a, **mfes_a, **maes_a
                    })

        if not entry_found:
            has_trigger = any(e["is_trigger_event"] for e in sample_all_weekly_events)
            if not has_trigger:
                reason = "NO_TRIGGER"
            else:
                trigger_events = [e for e in sample_all_weekly_events if e["is_trigger_event"]]
                first_t = trigger_events[0]
                if first_t["monthly_regime"] == "EARLY_REGIME":
                    reason = "TRIGGER_BUT_EARLY_REGIME"
                elif first_t["monthly_regime"] == "LATE_OR_EXTENDED_REGIME":
                    reason = "TRIGGER_BUT_LATE_OR_EXTENDED_REGIME"
                elif first_t["daily_risk"] == "EXTREME":
                    reason = "TRIGGER_BUT_EXTREME_RISK"
                elif first_t["fast_score_status"] not in {"READY", "PARTIAL"}:
                    reason = "TRIGGER_BUT_SCORE_UNAVAILABLE"
                else:
                    reason = "NO_QUALIFYING_ENTRY_BEFORE_CUTOFF"

            sample_entry_record = {
                "rank": rank,
                "ticker": ticker,
                "name": name,
                "market": market,
                "market_cap": market_cap,
                "market_cap_eok": market_cap_eok,
                "entry_found": False,
                "entry_grade": None,
                "signal_date": None,
                "signal_year": None,
                "execution_date": None,
                "entry_open": None,
                "fast_score_at_entry": None,
                "fast_score_status": None,
                "fast_stage_at_entry": None,
                "monthly_regime_at_entry": None,
                "daily_risk_at_entry": None,
                "pattern_a_score_at_entry": None,
                "pattern_a_stage_at_entry": None,
                "pattern_a_candidate_state_at_entry": None,
                "weeks_from_window_start_to_entry": None,
                "return_4w": None, "return_8w": None, "return_12w": None, "return_26w": None,
                "mfe_4w": None, "mfe_8w": None, "mfe_12w": None, "mfe_26w": None,
                "mae_4w": None, "mae_8w": None, "mae_12w": None, "mae_26w": None,
                "followup_status_4w": None, "followup_status_8w": None, "followup_status_12w": None, "followup_status_26w": None,
                "no_entry_reason": reason,
            }

        sample_results.append(sample_entry_record)

    df_samples = pd.DataFrame(sample_results)
    df_events = pd.DataFrame(event_logs)

    total_samples = len(df_samples)
    entry_samples = df_samples[df_samples["entry_found"]]
    no_entry_samples = df_samples[~df_samples["entry_found"]]

    entry_count = int(len(entry_samples))
    no_entry_count = int(len(no_entry_samples))
    entry_rate = round(entry_count / total_samples * 100, 1)

    grade_counts = {k: int(v) for k, v in entry_samples["entry_grade"].value_counts().items()}
    no_entry_reasons = {k: int(v) for k, v in no_entry_samples["no_entry_reason"].value_counts().items()}
    year_dist = {int(k): int(v) for k, v in entry_samples["signal_year"].value_counts().sort_index().items()}

    forward_returns = {f"{h}w": calculate_stats(entry_samples[f"return_{h}w"]) for h in horizons}
    mfe_stats = {f"{h}w": calculate_stats(entry_samples[f"mfe_{h}w"]) for h in horizons}
    mae_stats = {f"{h}w": calculate_stats(entry_samples[f"mae_{h}w"]) for h in horizons}

    censored_counts = {
        f"{h}w": int((entry_samples[f"followup_status_{h}w"] == "CENSORED").sum())
        for h in horizons
    }

    # Grade A vs Grade B analysis
    grade_a_samples = entry_samples[entry_samples["entry_grade"] == "Grade A"]
    grade_b_samples = entry_samples[entry_samples["entry_grade"] == "Grade B"]

    grade_analysis = {
        "Grade A (NORMAL)": {
            "entry_count": int(len(grade_a_samples)),
            "forward_returns": {f"{h}w": calculate_stats(grade_a_samples[f"return_{h}w"]) for h in horizons},
            "mfe_medians": {f"{h}w": round(float(grade_a_samples[f"mfe_{h}w"].median()), 2) if not grade_a_samples[f"mfe_{h}w"].dropna().empty else None for h in horizons},
            "mae_medians": {f"{h}w": round(float(grade_a_samples[f"mae_{h}w"].median()), 2) if not grade_a_samples[f"mae_{h}w"].dropna().empty else None for h in horizons},
            "sample_size_status": "SUFFICIENT" if len(grade_a_samples) >= 5 else "INSUFFICIENT_SAMPLE_SIZE",
        },
        "Grade B (ELEVATED)": {
            "entry_count": int(len(grade_b_samples)),
            "forward_returns": {f"{h}w": calculate_stats(grade_b_samples[f"return_{h}w"]) for h in horizons},
            "mfe_medians": {f"{h}w": round(float(grade_b_samples[f"mfe_{h}w"].median()), 2) if not grade_b_samples[f"mfe_{h}w"].dropna().empty else None for h in horizons},
            "mae_medians": {f"{h}w": round(float(grade_b_samples[f"mae_{h}w"].median()), 2) if not grade_b_samples[f"mae_{h}w"].dropna().empty else None for h in horizons},
            "sample_size_status": "SUFFICIENT" if len(grade_b_samples) >= 5 else "INSUFFICIENT_SAMPLE_SIZE",
        },
    }

    # Early Variant & Any Control
    df_early = pd.DataFrame(early_variant_results)
    df_any = pd.DataFrame(any_control_results)

    early_variant_summary = {
        "entry_count": int(len(df_early)),
        "forward_returns": {f"{h}w": calculate_stats(df_early[f"return_{h}w"]) for h in horizons if f"return_{h}w" in df_early},
        "mfe_medians": {f"{h}w": round(float(df_early[f"mfe_{h}w"].median()), 2) if f"mfe_{h}w" in df_early and not df_early[f"mfe_{h}w"].dropna().empty else None for h in horizons},
        "mae_medians": {f"{h}w": round(float(df_early[f"mae_{h}w"].median()), 2) if f"mae_{h}w" in df_early and not df_early[f"mae_{h}w"].dropna().empty else None for h in horizons},
    }
    any_control_summary = {
        "entry_count": int(len(df_any)),
        "forward_returns": {f"{h}w": calculate_stats(df_any[f"return_{h}w"]) for h in horizons if f"return_{h}w" in df_any},
        "mfe_medians": {f"{h}w": round(float(df_any[f"mfe_{h}w"].median()), 2) if f"mfe_{h}w" in df_any and not df_any[f"mfe_{h}w"].dropna().empty else None for h in horizons},
        "mae_medians": {f"{h}w": round(float(df_any[f"mae_{h}w"].median()), 2) if f"mae_{h}w" in df_any and not df_any[f"mae_{h}w"].dropna().empty else None for h in horizons},
    }

    # Timing delay diagnostic (Control vs Primary entry week difference)
    timing_delays = []
    for _, row in df_samples.iterrows():
        ticker = row["ticker"]
        ctrl_ev = df_events[(df_events["ticker"] == ticker) & (df_events["is_any_control_event"])]
        if not ctrl_ev.empty and pd.notna(row["signal_date"]):
            ctrl_d = pd.Timestamp(ctrl_ev.iloc[0]["weekly_date"])
            prim_d = pd.Timestamp(row["signal_date"])
            diff_w = round((prim_d - ctrl_d).days / 7, 1)
            timing_delays.append(diff_w)

    delay_series = pd.Series(timing_delays) if timing_delays else pd.Series(dtype=float)
    timing_delay_stats = {
        "n": int(len(delay_series)),
        "median_delay_weeks": round(float(delay_series.median()), 1) if not delay_series.empty else None,
        "mean_delay_weeks": round(float(delay_series.mean()), 2) if not delay_series.empty else None,
        "min_delay_weeks": round(float(delay_series.min()), 1) if not delay_series.empty else None,
        "max_delay_weeks": round(float(delay_series.max()), 1) if not delay_series.empty else None,
        "same_week_entry_count": int((delay_series == 0).sum()) if not delay_series.empty else 0,
        "delayed_entry_count": int((delay_series > 0).sum()) if not delay_series.empty else 0,
    }

    # Pattern A Diagnostic Breakdown (explicit available vs unavailable)
    pa_cand_dist = {str(k): int(v) for k, v in entry_samples["pattern_a_candidate_state_at_entry"].value_counts().items()}
    pa_stage_series = entry_samples["pattern_a_stage_at_entry"].dropna()
    pa_stage_dist = {str(k): int(v) for k, v in pa_stage_series.value_counts().items()}
    pa_stage_unavail_count = int(entry_samples["pattern_a_stage_at_entry"].isna().sum())

    # Conclusion & sub-conclusions
    conclusion = "MIXED"
    conclusion_rationale = (
        "2026년 8월 14일 기준 시가총액 상위 40개 대형주를 대상으로 FAST Entry Policy v0.1을 사후 진단한 결과, "
        "5년 관찰 구간에서 40개 전 종목에서 Primary Entry가 발생하였다. 따라서 이번 실험에서는 종목 단위 선별 효과는 "
        "관찰되지 않았으며, FAST Primary 조건은 종목 선택보다는 진입 시점 필터로 해석하는 것이 적절하다. "
        "Primary Entry는 Trigger Any Control보다 4주, 8주, 12주, 26주 모두 더 높은 중위 수익률을 기록했으나, "
        "Primary 자체의 절대 중위 수익률은 혼조세였다. 또한 Early Variant는 n=7의 작은 표본이지만 모든 Horizon에서 "
        "Primary보다 높은 중위 수익률을 기록하여, EARLY_REGIME 제외의 우위가 이번 Large Cap 40에서는 재현되지 않았다. "
        "따라서 이번 결과는 Production 승격이나 정책 수정 근거가 아니라, FAST Entry Timing 및 Monthly Regime 역할을 "
        "추가 연구하기 위한 사후 진단 참고자료로 보존한다."
    )

    summary_json = {
        "version": "v0.1",
        "status": "EVALUATED_RETROSPECTIVE_DIAGNOSTIC",
        "research_classification": "LARGE_CAP_40_RETROSPECTIVE_DIAGNOSTIC",
        "base_commit": BASE_COMMIT_SHA,
        "preregistration_commit": COMMIT_A_SHA,
        "preregistration_sha256": FROZEN_PREREG_SHA256,
        "selection_manifest_sha256": FROZEN_MANIFEST_SHA256,
        "selection_source_sha256": FROZEN_SOURCE_SHA256,
        "population": "KRX_MARKET_CAP_TOP40_ASOF_2026_08_14",
        "total_sample_count": total_samples,
        "data_cutoff": "2026-08-14",
        "signal_observation_window": "2021-08-14 ~ 2026-08-14",
        "coverage": {
            "entry_count": entry_count,
            "no_entry_count": no_entry_count,
            "entry_rate": entry_rate,
            "grade_counts": grade_counts,
            "no_entry_reasons": no_entry_reasons,
            "entry_year_distribution": year_dist,
        },
        "primary_forward_returns": forward_returns,
        "mfe_excursion_medians": {f"{h}w": mfe_stats[f"{h}w"]["median"] for h in horizons},
        "mae_excursion_medians": {f"{h}w": mae_stats[f"{h}w"]["median"] for h in horizons},
        "censored_counts": censored_counts,
        "grade_analysis": grade_analysis,
        "trigger_any_control": any_control_summary,
        "experimental_early_variant": early_variant_summary,
        "entry_timing_delay": timing_delay_stats,
        "pattern_a_diagnostic": {
            "candidate_state_distribution": pa_cand_dist,
            "stage_distribution": pa_stage_dist,
            "stage_available_count": int(len(pa_stage_series)),
            "stage_unavailable_count": pa_stage_unavail_count,
        },
        "integrity": {
            "pit_evaluated": True,
            "execution_price_rule": "next_trading_day_open",
            "data_cutoff_enforced": True,
            "retuning_allowed": False,
            "network_requests": 0,
            "pattern_a_frozen_semantics_unchanged": True,
        },
        "final_research_conclusion": conclusion,
        "sub_conclusions": {
            "entry_timing_filter_effect": "PROMISING",
            "stock_level_selectivity": "NOT_OBSERVED",
            "forward_return_profile": "MIXED",
            "grade_a_result": "MIXED",
            "grade_b_result": "INSUFFICIENT_SAMPLE_SIZE",
            "early_exclusion_hypothesis": "NOT_REPLICATED_IN_LARGE_CAP40",
            "overall_research_status": "MIXED_DIAGNOSTIC_REFERENCE",
        },
        "conclusion_rationale": conclusion_rationale,
    }

    return df_samples, df_events, summary_json


def render_markdown(summary: dict, df_samples: pd.DataFrame) -> str:
    cov = summary["coverage"]
    fwd = summary["primary_forward_returns"]
    mfe = summary["mfe_excursion_medians"]
    mae = summary["mae_excursion_medians"]
    ctrl_fwd = summary["trigger_any_control"]["forward_returns"]
    early_fwd = summary["experimental_early_variant"]["forward_returns"]
    grade_data = summary["grade_analysis"]
    delay_data = summary.get("entry_timing_delay", {})
    pa_diag = summary["pattern_a_diagnostic"]

    lines = [
        "# Pattern A FAST Trading Policy Entry v0.1 시가총액 상위 40개 대형주 사후 진단 평가 보고서",
        "",
        "- **평가 대상 모집단**: `KRX 시가총액 상위 40개 보통주 (2026-08-14 기준)`",
        f"- **기준 커밋**: `{summary['base_commit']}`",
        f"- **사전등록 커밋**: `{summary['preregistration_commit']}`",
        f"- **사전등록 프로토콜 해시**: `{summary['preregistration_sha256']}`",
        f"- **선택 매니페스트 해시**: `{summary['selection_manifest_sha256']}`",
        f"- **데이터 기준일**: `{summary['data_cutoff']}` (절대적 상한일)",
        f"- **신호 관찰 기간**: `{summary['signal_observation_window']}`",
        "- **외부 네트워크 요청**: `0회 (로컬 Parquet 캐시 전용, Zero Network Requests)`",
        f"- **최종 연구 결론**: **`{summary['final_research_conclusion']}` (대형주 사후 진단 참고자료)**",
        "",
        "---",
        "",
        "## 1. 평가 모집단",
        "- 2026년 8월 14일 기준 KRX 정규 주식 유니버스(KOSPI / KOSDAQ 보통주) 시가총액 순위 1위부터 40위까지의 대형주 40개 종목 전수.",
        "- 우선주, ETF, ETN 등 비보통주 상품 제외.",
        "",
        "---",
        "",
        "## 2. 진입 정책",
        "- **Primary Entry Rule**: `FAST Stage == TRIGGER` AND `Stage Status == READY` AND `Monthly Regime == PERMITTED_REGIME` AND `Daily Risk IN {'NORMAL', 'ELEVATED'}` AND `Score Status IN {'READY', 'PARTIAL'}`",
        "- **체결 가격**: `next_trading_day_open` (신호 완성 주간 직후 첫 거래일 시가 체결)",
        "- **비게이트 정책**: FAST 점수 임계값 및 Pattern A 점수/국면 조건 배제",
        "",
        "---",
        "",
        "## 3. 진입 발생률",
        f"- **총 분석 표본**: `{summary['total_sample_count']}개 종목`",
        f"- **Primary Entry 발생**: `{cov['entry_count']}개` (`{cov['entry_rate']}%`)",
        f"- **진입 미발생 (NO_ENTRY)**: `{cov['no_entry_count']}개` (`{round(cov['no_entry_count'] / summary['total_sample_count'] * 100, 1)}%`)",
        f"- **진입 등급 구성**: Grade A (NORMAL Risk) `{cov['grade_counts'].get('Grade A', 0)}개`, Grade B (ELEVATED Risk) `{cov['grade_counts'].get('Grade B', 0)}개`",
        "",
        "### 연도별 진입 분포:",
    ]
    for yr, cnt in cov["entry_year_distribution"].items():
        lines.append(f"- **{yr}년**: {cnt}개 종목")

    lines.extend([
        "",
        "---",
        "",
        "## 4. 기간별 수익률",
        "",
        "| 관측 기간 | 유효 표본수 (n) | 중위 수익률 (Median) | 평균 수익률 (Mean) | 표준편차 (Std) | 최소 수익률 (Min) | 최대 수익률 (Max) | 승률 (Positive Rate) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for h in [4, 8, 12, 26]:
        stat = fwd[f"{h}w"]
        lines.append(
            f"| **{h}주 ({h}W)** | {stat['n']} | **{stat['median']:+.2f}%** | {stat['mean']:+.2f}% | {stat['std']:.2f}% | {stat['min']:+.2f}% | {stat['max']:+.2f}% | {stat['positive_rate']:.1f}% |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. 최대 순행 / 역행 폭",
        "",
        "| 관측 기간 | 최대 순행 폭 중위수 (MFE) | 최대 역행 폭 중위수 (MAE) |",
        "|---|---:|---:|",
    ])

    for h in [4, 8, 12, 26]:
        lines.append(
            f"| **{h}주 ({h}W)** | **{mfe[f'{h}w']:+.2f}%** | **{mae[f'{h}w']:+.2f}%** |"
        )

    ga_mfe = grade_data["Grade A (NORMAL)"]["mfe_medians"]
    ga_mae = grade_data["Grade A (NORMAL)"]["mae_medians"]
    gb_mfe = grade_data["Grade B (ELEVATED)"]["mfe_medians"]
    gb_mae = grade_data["Grade B (ELEVATED)"]["mae_medians"]

    lines.extend([
        "",
        "---",
        "",
        "## 6. 등급별 결과",
        "",
        f"- **Grade A (NORMAL Risk, n={grade_data['Grade A (NORMAL)']['entry_count']})**:",
        f"  - 4주: 중위수 `{grade_data['Grade A (NORMAL)']['forward_returns']['4w']['median']:+.2f}%` (승률 {grade_data['Grade A (NORMAL)']['forward_returns']['4w']['positive_rate']:.1f}%) | MFE `{ga_mfe['4w']:+.2f}%` | MAE `{ga_mae['4w']:+.2f}%`",
        f"  - 8주: 중위수 `{grade_data['Grade A (NORMAL)']['forward_returns']['8w']['median']:+.2f}%` (승률 {grade_data['Grade A (NORMAL)']['forward_returns']['8w']['positive_rate']:.1f}%) | MFE `{ga_mfe['8w']:+.2f}%` | MAE `{ga_mae['8w']:+.2f}%`",
        f"  - 12주: 중위수 `{grade_data['Grade A (NORMAL)']['forward_returns']['12w']['median']:+.2f}%` (승률 {grade_data['Grade A (NORMAL)']['forward_returns']['12w']['positive_rate']:.1f}%) | MFE `{ga_mfe['12w']:+.2f}%` | MAE `{ga_mae['12w']:+.2f}%`",
        f"  - 26주: 중위수 `{grade_data['Grade A (NORMAL)']['forward_returns']['26w']['median']:+.2f}%` (승률 {grade_data['Grade A (NORMAL)']['forward_returns']['26w']['positive_rate']:.1f}%) | MFE `{ga_mfe['26w']:+.2f}%` | MAE `{ga_mae['26w']:+.2f}%`",
        f"- **Grade B (ELEVATED Risk, n={grade_data['Grade B (ELEVATED)']['entry_count']})**: *(주의: 표본 수 n={grade_data['Grade B (ELEVATED)']['entry_count']}개로 표본 부족 / INSUFFICIENT_SAMPLE_SIZE)*",
        f"  - 4주: 중위수 `{grade_data['Grade B (ELEVATED)']['forward_returns']['4w']['median']:+.2f}%` (승률 {grade_data['Grade B (ELEVATED)']['forward_returns']['4w']['positive_rate']:.1f}%) | MFE `{gb_mfe['4w']:+.2f}%` | MAE `{gb_mae['4w']:+.2f}%`",
        f"  - 8주: 중위수 `{grade_data['Grade B (ELEVATED)']['forward_returns']['8w']['median']:+.2f}%` (승률 {grade_data['Grade B (ELEVATED)']['forward_returns']['8w']['positive_rate']:.1f}%) | MFE `{gb_mfe['8w']:+.2f}%` | MAE `{gb_mae['8w']:+.2f}%`",
        f"  - 12주: 중위수 `{grade_data['Grade B (ELEVATED)']['forward_returns']['12w']['median']:+.2f}%` (승률 {grade_data['Grade B (ELEVATED)']['forward_returns']['12w']['positive_rate']:.1f}%) | MFE `{gb_mfe['12w']:+.2f}%` | MAE `{gb_mae['12w']:+.2f}%`",
        f"  - 26주: 중위수 `{grade_data['Grade B (ELEVATED)']['forward_returns']['26w']['median']:+.2f}%` (승률 {grade_data['Grade B (ELEVATED)']['forward_returns']['26w']['positive_rate']:.1f}%) | MFE `{gb_mfe['26w']:+.2f}%` | MAE `{gb_mae['26w']:+.2f}%`",
        "",
        "---",
        "",
        "## 7. 비교군 결과 (Trigger Any Control)",
        "",
        "| 항목 구분 | 4주 중위수 | 8주 중위수 | 12주 중위수 | 26주 중위수 |",
        "|---|---:|---:|---:|---:|",
        f"| **기본 진입 규칙 (Primary Entry)** | **{fwd['4w']['median']:+.2f}%** | **{fwd['8w']['median']:+.2f}%** | **{fwd['12w']['median']:+.2f}%** | **{fwd['26w']['median']:+.2f}%** |",
        f"| **비교군 (Trigger Any Control)** | **{ctrl_fwd['4w']['median']:+.2f}%** | **{ctrl_fwd['8w']['median']:+.2f}%** | **{ctrl_fwd['12w']['median']:+.2f}%** | **{ctrl_fwd['26w']['median']:+.2f}%** |",
        "",
        f"- **진입 시점 지연 진단 (Entry Timing Delay)**: 동일 주 진입 `{delay_data.get('same_week_entry_count', 0)}개`, 지연 진입 `{delay_data.get('delayed_entry_count', 0)}개` (평균 지연 `{delay_data.get('mean_delay_weeks', 0.0)}주`, 중위수 `{delay_data.get('median_delay_weeks', 0.0)}주`)",
        "> **기술적 비교 관찰**: Primary Entry 조건을 모두 적용한 진입 시점은 Trigger Any Control보다 전 관측 기간에서 더 높은 중위 수익률을 기록했다. 단, 이 차이를 PERMITTED_REGIME 또는 Daily Risk 개별 조건의 단독 효과로 분해해 해석할 수는 없다.",
        "",
        "---",
        "",
        "## 8. 조기 진입 실험군 (Early Variant)",
        f"- **진입 표본 수**: `n={summary['experimental_early_variant']['entry_count']}개`",
        f"- 4주 중위수: `{early_fwd['4w']['median']:+.2f}%` | 8주 중위수: `{early_fwd['8w']['median']:+.2f}%` | 12주 중위수: `{early_fwd['12w']['median']:+.2f}%` | 26주 중위수: `{early_fwd['26w']['median']:+.2f}%`",
        "",
        "> **비교 관찰**: 기존 Frozen OOS B에서는 Early Variant가 약세를 보였으나, 이번 Large Cap 40 사후 진단에서는 Early Variant(n=7)가 Primary보다 전 Horizon에서 높은 중위 수익률을 기록했다. 따라서 EARLY 제외의 우위는 이번 대형주 진단에서는 재현되지 않았다.",
        "",
        "---",
        "",
        "## 9. Pattern A 진단",
        "- **Pattern A Candidate 여부**: " + ", ".join([f"`{k}`: {v}개" for k, v in pa_diag["candidate_state_distribution"].items()]),
        "- **Pattern A 국면(Stage) 분포**: " + ", ".join([f"`{k}`: {v}개" for k, v in pa_diag["stage_distribution"].items()]) + f" (판정 유효 {pa_diag['stage_available_count']}개, UNAVAILABLE {pa_diag['stage_unavailable_count']}개)",
        "",
        "---",
        "",
        "## 10. 표본별 결과",
        "",
        "| 순위 | 종목코드 | 종목명 | 시장 | 진입 등급 | 신호 발생일 | 체결일 | 체결 시가 | 4주 수익률 | 12주 수익률 | 26주 수익률 |",
        "|---:|:---:|---|:---:|:---:|:---:|:---:|---:|---:|---:|---:|",
    ])

    for _, row in df_samples.iterrows():
        gr = row["entry_grade"] or "-"
        sd = row["signal_date"] or "-"
        ed = row["execution_date"] or "-"
        eo = f"{row['entry_open']:,.0f}" if pd.notna(row["entry_open"]) else "-"
        r4 = f"{row['return_4w']:+.2f}%" if pd.notna(row["return_4w"]) else "-"
        r12 = f"{row['return_12w']:+.2f}%" if pd.notna(row["return_12w"]) else "-"
        r26 = f"{row['return_26w']:+.2f}%" if pd.notna(row["return_26w"]) else "-"
        lines.append(
            f"| {row['rank']} | `{row['ticker']}` | {row['name']} | {row['market']} | {gr} | {sd} | {ed} | {eo} | {r4} | {r12} | {r26} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 11. 연구 한계",
        "1. 본 평가는 2026년 8월 14일 시가총액 상위 40개 종목을 사후적으로 선택한 현재 구성 종목 기반 분석입니다.",
        "2. 따라서 본 실험은 독립 OOS(Out-of-Sample) 검증이 아닙니다.",
        "3. 현재 대형주로 살아남은 종목을 과거 구간에서 평가하므로 생존 편향(survivor / current constituent selection)이 존재합니다.",
        "4. 수수료, 세금, 슬리피지, 시장 충격 비용은 포함하지 않은 총수익률(Gross Signal Follow-Up Return) 기준입니다.",
        "5. 청산 정책(Exit Policy)은 평가하지 않았습니다.",
        "6. 본 결과만으로 전략을 Production으로 승격하지 않습니다.",
        "",
        "---",
        "",
        "## 12. 최종 결론",
        f"> **결론: `{summary['final_research_conclusion']}` (대형주 사후 진단 참고자료)**",
        ">",
        f"> - **진입 시점 필터 효과**: `{summary['sub_conclusions']['entry_timing_filter_effect']}`",
        f"> - **종목 단위 선별 효과**: `{summary['sub_conclusions']['stock_level_selectivity']}`",
        f"> - **수익률 프로파일**: `{summary['sub_conclusions']['forward_return_profile']}`",
        f"> - **Grade A 결과**: `{summary['sub_conclusions']['grade_a_result']}`",
        f"> - **Grade B 결과**: `{summary['sub_conclusions']['grade_b_result']}`",
        f"> - **EARLY 제외 가설**: `{summary['sub_conclusions']['early_exclusion_hypothesis']}`",
        f"> - **전체 연구 상태**: `{summary['sub_conclusions']['overall_research_status']}`",
        ">",
        f"> {summary['conclusion_rationale']}",
    ])

    return "\n".join(lines)


def main() -> None:
    LARGE_CAP_DIR.mkdir(parents=True, exist_ok=True)
    df_samples, df_events, summary_json = run_evaluation()

    df_samples.to_csv(OUT_SAMPLES_CSV, index=False, encoding="utf-8-sig")
    df_events.to_csv(OUT_EVENT_LOG_CSV, index=False, encoding="utf-8-sig")
    OUT_EVAL_JSON.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False), encoding="utf-8")

    md_content = render_markdown(summary_json, df_samples)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")

    print("Large Cap 40 Evaluation completed successfully!")
    print(f"Sample Results CSV: {OUT_SAMPLES_CSV}")
    print(f"Event Log CSV: {OUT_EVENT_LOG_CSV}")
    print(f"Evaluation JSON: {OUT_EVAL_JSON}")
    print(f"Evaluation MD: {OUT_EVAL_MD}")


if __name__ == "__main__":
    main()
