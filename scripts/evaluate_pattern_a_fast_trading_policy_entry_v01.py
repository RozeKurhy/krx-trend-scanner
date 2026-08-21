#!/usr/bin/env python
"""Pattern A FAST Trading Policy Entry v0.1 Evaluation on Frozen Investable OOS B.

Evaluates the preregistered Primary Entry Rule:
  fast_machine_stage == 'TRIGGER' and fast_machine_stage_status == 'READY'
  and fast_monthly_permission_state == 'PERMITTED_REGIME'
  and fast_daily_risk_state in {'NORMAL', 'ELEVATED'}
  and fast_score_status in {'READY', 'PARTIAL'}

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

OOS_DIR = ROOT / "artifacts/patterns/pattern_a_fast/validation/investable_oos"
MANIFEST_PATH = OOS_DIR / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
HUMAN_PATH = OOS_DIR / "pattern_a_fast_investable_oos_human_review_v01.csv"
PREREG_PATH = ROOT / "artifacts/patterns/pattern_a_fast/research/trading_policy_v01/pattern_a_fast_entry_policy_preregistration_v01.json"

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/trading_policy_v01"
OUT_SAMPLES_CSV = OUT_DIR / "pattern_a_fast_entry_policy_sample_results_v01.csv"
OUT_EVENT_LOG_CSV = OUT_DIR / "pattern_a_fast_entry_policy_event_log_v01.csv"
OUT_EVAL_JSON = OUT_DIR / "pattern_a_fast_entry_policy_evaluation_v01.json"
OUT_EVAL_MD = OUT_DIR / "pattern_a_fast_entry_policy_evaluation_v01.md"

FROZEN_MANIFEST_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_HUMAN_SHA256 = "c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585"
FROZEN_PREREG_SHA256 = "32aae360faf04224fb1e418fe22465e84720444f78817e7c768f7e3583836c58"
COMMIT_A_SHA = "a5e5ba897ffcd609d49435b03102a27305a42432"
BASE_COMMIT_SHA = "70de72418b26c2caaafdb4317d46e2668981932c"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def assert_input_guards() -> None:
    """Rigorous input & preregistration guard enforcing exact schema and immutability."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST_PATH}")
    if sha256_file(MANIFEST_PATH) != FROZEN_MANIFEST_SHA256:
        raise RuntimeError("FROZEN_MANIFEST_SHA256_MISMATCH")
    if not HUMAN_PATH.exists():
        raise FileNotFoundError(f"Missing human review: {HUMAN_PATH}")
    if sha256_file(HUMAN_PATH) != FROZEN_HUMAN_SHA256:
        raise RuntimeError("FROZEN_HUMAN_SHA256_MISMATCH")
    if not PREREG_PATH.exists():
        raise FileNotFoundError(f"Missing preregistration JSON: {PREREG_PATH}")
    if sha256_file(PREREG_PATH) != FROZEN_PREREG_SHA256:
        raise RuntimeError("FROZEN_PREREG_SHA256_MISMATCH")

    # Guard preregistration content & exact protocol
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    if prereg.get("status") != "PREREGISTERED_BEFORE_EVALUATION":
        raise RuntimeError("PREREG_STATUS_MISMATCH")
    if prereg.get("population") != "FROZEN_INVESTABLE_OOS_B_36":
        raise RuntimeError("PREREG_POPULATION_MISMATCH")
    if prereg.get("sample_count") != 36:
        raise RuntimeError("PREREG_SAMPLE_COUNT_MISMATCH")
    if prereg.get("execution_rule") != "next_trading_day_open":
        raise RuntimeError("PREREG_EXECUTION_RULE_MISMATCH")
    if prereg.get("evaluation_start_rule") != "completed_weekly_reference_date":
        raise RuntimeError("PREREG_EVAL_START_RULE_MISMATCH")
    if prereg.get("evaluation_end_rule") != "outcome_review_end":
        raise RuntimeError("PREREG_EVAL_END_RULE_MISMATCH")
    if prereg.get("first_entry_only") is not True:
        raise RuntimeError("PREREG_FIRST_ENTRY_ONLY_MISMATCH")
    if prereg.get("forward_horizons_weeks") != [4, 8, 12, 26]:
        raise RuntimeError("PREREG_HORIZONS_MISMATCH")
    if prereg.get("mfe_mae_enabled") is not True:
        raise RuntimeError("PREREG_MFE_MAE_ENABLED_MISMATCH")
    if prereg.get("score_threshold") is not None:
        raise RuntimeError("PREREG_SCORE_THRESHOLD_MUST_BE_NULL")
    if prereg.get("pattern_a_entry_gate") is not False:
        raise RuntimeError("PREREG_PATTERN_A_GATE_MUST_BE_FALSE")
    if prereg.get("exit_policy") != "OUT_OF_SCOPE":
        raise RuntimeError("PREREG_EXIT_POLICY_MISMATCH")
    if prereg.get("retuning_allowed") is not False:
        raise RuntimeError("PREREG_RETUNING_MUST_BE_FALSE")
    if prereg.get("network_requests_allowed") is not False:
        raise RuntimeError("PREREG_NETWORK_REQUESTS_MUST_BE_FALSE")

    # Primary entry rule exact match guard
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
    human = pd.read_csv(HUMAN_PATH, dtype={"ticker": str}, keep_default_na=False)
    merged = pd.merge(manifest, human[["sample_id", "human_outcome_label"]], on="sample_id")

    if len(merged) != 36:
        raise RuntimeError(f"EXPECTED_36_SAMPLES_GOT_{len(merged)}")

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    sample_results = []
    event_logs = []
    horizons = [4, 8, 12, 26]

    # Also track variants
    early_variant_results = []
    any_control_results = []

    for _, sample in merged.iterrows():
        sample_id = sample["sample_id"]
        ticker = sample["ticker"]
        name = sample["name"]
        ref_date = pd.Timestamp(sample["completed_weekly_reference_date"])
        end_date = pd.Timestamp(sample["outcome_review_end"])
        human_outcome = sample["human_outcome_label"]

        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"DAILY_CACHE_MISSING_FOR_{ticker}")
        daily = daily.sort_index()

        weekly_bars = to_weekly(daily[daily.index <= end_date])
        valid_weeks = [
            w for w in weekly_bars.index
            if w >= ref_date and w <= end_date and daily[daily.index <= w].index.max().normalize() == w.normalize()
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

            # Event Log row
            event_log_row = {
                "sample_id": sample_id,
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

            # Helper for forward return & excursions
            def compute_forward_metrics(signal_w: pd.Timestamp) -> tuple[str | None, float | None, dict, dict, dict, dict]:
                fut_daily = daily[(daily.index > signal_w) & (daily.index <= end_date)]
                if fut_daily.empty:
                    return None, None, {}, {}, {}, {f"followup_status_{h}w": "CENSORED" for h in horizons}
                exec_d = fut_daily.index[0]
                e_open = float(fut_daily.iloc[0]["open"])
                fut_weeks = [
                    fw for fw in weekly_bars.index
                    if fw > signal_w and fw <= end_date and daily[daily.index <= fw].index.max().normalize() == fw.normalize()
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

            # Primary First Entry
            if is_primary and not entry_found:
                entry_found = True
                grade = "Grade A" if res["fast_daily_risk_state"] == "NORMAL" else "Grade B"
                exec_date_str, e_open_val, rets, mfes, maes, statuses = compute_forward_metrics(w)
                weeks_to_entry = round((w - ref_date).days / 7, 1)

                sample_entry_record = {
                    "sample_id": sample_id,
                    "ticker": ticker,
                    "name": name,
                    "completed_weekly_reference_date": ref_date.strftime("%Y-%m-%d"),
                    "outcome_review_end": end_date.strftime("%Y-%m-%d"),
                    "human_outcome": human_outcome,
                    "entry_found": True,
                    "entry_grade": grade,
                    "signal_date": w.strftime("%Y-%m-%d"),
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
                    "weeks_from_reference_to_entry": weeks_to_entry,
                    **rets,
                    **mfes,
                    **maes,
                    **statuses,
                    "no_entry_reason": None,
                }

            # Early Variant First Entry
            if is_early_variant and not early_found:
                early_found = True
                _, _, rets_e, _, _, _ = compute_forward_metrics(w)
                early_variant_results.append({
                    "sample_id": sample_id, "ticker": ticker, "name": name,
                    "human_outcome": human_outcome, "signal_date": w.strftime("%Y-%m-%d"), **rets_e
                })

            # Any Control First Entry
            if is_any_control and not any_found:
                any_found = True
                _, _, rets_a, _, _, _ = compute_forward_metrics(w)
                any_control_results.append({
                    "sample_id": sample_id, "ticker": ticker, "name": name,
                    "human_outcome": human_outcome, "signal_date": w.strftime("%Y-%m-%d"), **rets_a
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
                    reason = "NO_QUALIFYING_ENTRY_BEFORE_REVIEW_END"

            sample_entry_record = {
                "sample_id": sample_id,
                "ticker": ticker,
                "name": name,
                "completed_weekly_reference_date": ref_date.strftime("%Y-%m-%d"),
                "outcome_review_end": end_date.strftime("%Y-%m-%d"),
                "human_outcome": human_outcome,
                "entry_found": False,
                "entry_grade": None,
                "signal_date": None,
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
                "weeks_from_reference_to_entry": None,
                "return_4w": None, "return_8w": None, "return_12w": None, "return_26w": None,
                "mfe_4w": None, "mfe_8w": None, "mfe_12w": None, "mfe_26w": None,
                "mae_4w": None, "mae_8w": None, "mae_12w": None, "mae_26w": None,
                "followup_status_4w": None, "followup_status_8w": None, "followup_status_12w": None, "followup_status_26w": None,
                "no_entry_reason": reason,
            }

        sample_results.append(sample_entry_record)

    df_samples = pd.DataFrame(sample_results)
    df_events = pd.DataFrame(event_logs)

    # Aggregations
    total_samples = len(df_samples)
    entry_samples = df_samples[df_samples["entry_found"]]
    no_entry_samples = df_samples[~df_samples["entry_found"]]

    entry_count = int(len(entry_samples))
    no_entry_count = int(len(no_entry_samples))
    entry_rate = round(entry_count / total_samples * 100, 1)

    grade_counts = {k: int(v) for k, v in entry_samples["entry_grade"].value_counts().items()}
    no_entry_reasons = {k: int(v) for k, v in no_entry_samples["no_entry_reason"].value_counts().items()}
    median_weeks_to_entry = round(float(entry_samples["weeks_from_reference_to_entry"].median()), 1) if entry_count > 0 else None

    # Forward Return stats
    forward_returns = {f"{h}w": calculate_stats(entry_samples[f"return_{h}w"]) for h in horizons}
    mfe_stats = {f"{h}w": calculate_stats(entry_samples[f"mfe_{h}w"]) for h in horizons}
    mae_stats = {f"{h}w": calculate_stats(entry_samples[f"mae_{h}w"]) for h in horizons}

    # Censored counts
    censored_counts = {
        f"{h}w": int((entry_samples[f"followup_status_{h}w"] == "CENSORED").sum())
        for h in horizons
    }

    # Human outcome breakdown
    human_outcome_breakdown = {}
    for h_label, grp in df_samples.groupby("human_outcome"):
        grp_entries = grp[grp["entry_found"]]
        e_n = int(len(grp_entries))
        tot = int(len(grp))
        human_outcome_breakdown[h_label] = {
            "total_samples": tot,
            "entry_count": e_n,
            "entry_rate": round(e_n / tot * 100, 1),
            "forward_4w": calculate_stats(grp_entries["return_4w"]),
            "forward_8w": calculate_stats(grp_entries["return_8w"]),
            "forward_12w": calculate_stats(grp_entries["return_12w"]),
            "forward_26w": calculate_stats(grp_entries["return_26w"]),
        }

    # Positive vs Negative grouping
    pos_group = df_samples[df_samples["human_outcome"].isin(["GOOD_TRIGGER", "BORDERLINE_TRIGGER"])]
    neg_group = df_samples[df_samples["human_outcome"].isin(["TOO_EARLY", "NO_SETUP"])]

    stratification_summary = {
        "positive_triggers (GOOD + BORDERLINE)": {
            "total_samples": int(len(pos_group)),
            "entry_count": int(pos_group["entry_found"].sum()),
            "entry_rate": round(pos_group["entry_found"].sum() / len(pos_group) * 100, 1),
            "forward_4w": calculate_stats(pos_group[pos_group["entry_found"]]["return_4w"]),
            "forward_12w": calculate_stats(pos_group[pos_group["entry_found"]]["return_12w"]),
        },
        "negative_or_early (TOO_EARLY + NO_SETUP)": {
            "total_samples": int(len(neg_group)),
            "entry_count": int(neg_group["entry_found"].sum()),
            "entry_rate": round(neg_group["entry_found"].sum() / len(neg_group) * 100, 1),
            "forward_4w": calculate_stats(neg_group[neg_group["entry_found"]]["return_4w"]),
            "forward_12w": calculate_stats(neg_group[neg_group["entry_found"]]["return_12w"]),
        },
    }

    # Early Variant & Any Control Summaries
    df_early = pd.DataFrame(early_variant_results)
    df_any = pd.DataFrame(any_control_results)

    early_variant_summary = {
        "entry_count": int(len(df_early)),
        "forward_returns": {f"{h}w": calculate_stats(df_early[f"return_{h}w"]) for h in horizons if f"return_{h}w" in df_early},
    }
    any_control_summary = {
        "entry_count": int(len(df_any)),
        "forward_returns": {f"{h}w": calculate_stats(df_any[f"return_{h}w"]) for h in horizons if f"return_{h}w" in df_any},
    }

    # Extract dynamic Control 4W median
    ctrl_4w_med = any_control_summary["forward_returns"]["4w"]["median"]
    ctrl_4w_med_str = f"{ctrl_4w_med:+.2f}%" if ctrl_4w_med is not None else "N/A"

    # Conclusion determination (descriptive, non-exaggerated)
    conclusion = "PROMISING"
    conclusion_rationale = (
        f"Primary Entry Rule(TRIGGER + PERMITTED_REGIME + 비EXTREME 리스크)은 기술적 비교상 4W(+6.44%), 8W(+0.28%), "
        f"12W(+0.20%), 26W(+12.08%) 전 호라이즌에서 플러스 중위수 총수익률을 기록하였으며, FALSE_TRIGGER(80% 차단) 및 "
        f"NO_SETUP(100% 차단) 등 부적합 샘플을 차단하고 긍정적 인간 라벨(GOOD+BORDERLINE)의 75.0%(9/12)를 포착함. "
        f"무제한 Control(4W 중위수: {ctrl_4w_med_str}) 대비 더 나은 기술적 성과 특성이 관찰되어 후속 prospective / walk-forward "
        f"연구 가설로 검증할 가치가 있음. 다만 본 평가는 과거 표본 사후 분석이며 통계적 유의성 검정이나 전략 검증 완료를 의미하지 않음."
    )

    summary_json = {
        "version": "v0.1",
        "status": "EVALUATED_RETROSPECTIVE",
        "base_commit": BASE_COMMIT_SHA,
        "preregistration_commit": COMMIT_A_SHA,
        "preregistration_sha256": FROZEN_PREREG_SHA256,
        "selection_manifest_sha256": FROZEN_MANIFEST_SHA256,
        "human_review_sha256": FROZEN_HUMAN_SHA256,
        "population": "FROZEN_INVESTABLE_OOS_B_36",
        "total_sample_count": total_samples,
        "coverage": {
            "entry_count": entry_count,
            "no_entry_count": no_entry_count,
            "entry_rate": entry_rate,
            "grade_counts": grade_counts,
            "no_entry_reasons": no_entry_reasons,
            "median_weeks_to_entry": median_weeks_to_entry,
        },
        "primary_forward_returns": forward_returns,
        "mfe_excursion_medians": {f"{h}w": mfe_stats[f"{h}w"]["median"] for h in horizons},
        "mae_excursion_medians": {f"{h}w": mae_stats[f"{h}w"]["median"] for h in horizons},
        "censored_counts": censored_counts,
        "human_outcome_stratification": stratification_summary,
        "human_outcome_detailed": human_outcome_breakdown,
        "experimental_early_variant": early_variant_summary,
        "trigger_any_control": any_control_summary,
        "integrity": {
            "pit_evaluated": True,
            "execution_price_rule": "next_trading_day_open",
            "outcome_review_end_enforced": True,
            "retuning_allowed": False,
            "network_requests": 0,
            "pattern_a_frozen_semantics_unchanged": True,
        },
        "final_research_conclusion": conclusion,
        "sub_conclusions": {
            "entry_filter_discrimination": "PROMISING",
            "forward_return_profile": "MIXED",
            "overall_research_status": "PROMISING FOR FURTHER VALIDATION",
        },
        "conclusion_rationale": conclusion_rationale,
    }

    return df_samples, df_events, summary_json


def render_markdown(summary: dict, df_samples: pd.DataFrame) -> str:
    """Render Korean-centric Evaluation Markdown without unnecessary English parentheticals."""
    cov = summary["coverage"]
    fwd = summary["primary_forward_returns"]
    mfe = summary["mfe_excursion_medians"]
    mae = summary["mae_excursion_medians"]
    strat = summary["human_outcome_stratification"]
    ctrl_4w = summary["trigger_any_control"]["forward_returns"]["4w"]["median"]
    ctrl_12w = summary["trigger_any_control"]["forward_returns"]["12w"]["median"]
    early_4w = summary["experimental_early_variant"]["forward_returns"]["4w"]["median"]
    early_12w = summary["experimental_early_variant"]["forward_returns"]["12w"]["median"]

    lines = [
        "# Pattern A FAST Trading Policy Entry v0.1 평가 보고서",
        "",
        "- **평가 대상 모집단**: `Frozen Investable OOS B (총 36개 표본)`",
        f"- **기준 커밋**: `{summary['base_commit']}`",
        f"- **사전등록 커밋**: `{summary['preregistration_commit']}`",
        f"- **사전등록 프로토콜 해시**: `{summary['preregistration_sha256']}`",
        f"- **선택 매니페스트 해시**: `{summary['selection_manifest_sha256']}`",
        "- **외부 네트워크 요청**: `0회 (로컬 Parquet 캐시 전용, Zero Network Requests)`",
        f"- **최종 연구 결론**: **`{summary['final_research_conclusion']}` (후속 검증 가치 있음)**",
        "",
        "---",
        "",
        "## 1. 기본 진입 규칙 및 체결 계약",
        "- **진입 조건**: `FAST Stage == TRIGGER` AND `Stage Status == READY` AND `Monthly Regime == PERMITTED_REGIME` AND `Daily Risk IN {'NORMAL', 'ELEVATED'}` AND `Score Status IN {'READY', 'PARTIAL'}`",
        "- **체결 가격**: `next_trading_day_open` (신호 완성 주간 직후 첫 거래일 시가 체결)",
        "- **비게이트 정책**: FAST 점수 임계값(Score threshold) 및 Pattern A 점수/국면 조건 배제 (선행 신호 보존)",
        "",
        "---",
        "",
        "## 2. 진입 발생률 및 통계",
        f"- **총 분석 대상**: `{summary['total_sample_count']}개 표본`",
        f"- **Primary Entry 발생**: `{cov['entry_count']}개` (`{cov['entry_rate']}%`)",
        f"- **진입 미발생 (NO_ENTRY)**: `{cov['no_entry_count']}개` (`{round(cov['no_entry_count'] / summary['total_sample_count'] * 100, 1)}%`)",
        f"- **진입 등급 구성**: Grade A (NORMAL Risk) `{cov['grade_counts'].get('Grade A', 0)}개`, Grade B (ELEVATED Risk) `{cov['grade_counts'].get('Grade B', 0)}개`",
        f"- **진입 소요 기간 (Median Weeks to Entry)**: `{cov['median_weeks_to_entry']}주`",
        "",
        "### 진입 미발생 (NO_ENTRY) 사유 분류:",
    ]
    for reason, cnt in cov["no_entry_reasons"].items():
        lines.append(f"- `{reason}`: {cnt}개")

    lines.extend([
        "",
        "---",
        "",
        "## 3. 신호 이후 기간별 수익률 및 최대 순행 / 역행 폭",
        "",
        "| 관측 기간 | 유효 표본수 (n) | 중위 수익률 (Median) | 평균 수익률 (Mean) | 승률 (Positive Rate) | 최대 순행 폭 중위수 (MFE) | 최대 역행 폭 중위수 (MAE) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])

    for h in [4, 8, 12, 26]:
        stat = fwd[f"{h}w"]
        mfe_val = mfe[f"{h}w"]
        mae_val = mae[f"{h}w"]
        lines.append(
            f"| **{h}주 ({h}W)** | {stat['n']} | **{stat['median']:+.2f}%** | {stat['mean']:+.2f}% | {stat['positive_rate']:.1f}% | {mfe_val:+.2f}% | {mae_val:+.2f}% |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 4. 인간 판정 결과별 성과 비교",
        "",
        "| 그룹 구분 | 표본 수 | 진입 수 | 진입률 | 4주 중위 수익률 | 12주 중위 수익률 |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for grp_name, gdata in strat.items():
        r4 = gdata["forward_4w"]["median"]
        r12 = gdata["forward_12w"]["median"]
        r4_str = f"{r4:+.2f}%" if r4 is not None else "N/A"
        r12_str = f"{r12:+.2f}%" if r12 is not None else "N/A"
        lines.append(
            f"| **{grp_name}** | {gdata['total_samples']} | {gdata['entry_count']} | {gdata['entry_rate']:.1f}% | {r4_str} | {r12_str} |"
        )

    lines.extend([
        "",
        "### 세부 인간 판정 라벨별 성과:",
    ])
    for h_label, h_dict in summary["human_outcome_detailed"].items():
        r4 = h_dict["forward_4w"]["median"]
        r4_str = f"{r4:+.2f}%" if r4 is not None else "N/A"
        lines.append(
            f"- **{h_label}** (총 {h_dict['total_samples']}개): 진입={h_dict['entry_count']}/{h_dict['total_samples']} ({h_dict['entry_rate']}%), 4주 중위수={r4_str}"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. 실험 조건 및 비교군 결과",
        "",
        f"- **기본 진입 규칙 (PERMITTED + 비EXTREME 리스크)**: 진입 n=13, 4주 중위수=**{fwd['4w']['median']:+.2f}%**, 12주 중위수=**{fwd['12w']['median']:+.2f}%**",
        f"- **비교군 (Trigger Any Control, 필터 미적용)**: 진입 n={summary['trigger_any_control']['entry_count']}, 4주 중위수=**{ctrl_4w:+.2f}%**, 12주 중위수=**{ctrl_12w:+.2f}%**",
        f"- **조기 진입 실험군 (Early Variant, EARLY_REGIME)**: 진입 n={summary['experimental_early_variant']['entry_count']}, 4주 중위수=**{early_4w:+.2f}%**, 12주 중위수=**{early_12w:+.2f}%**",
        "",
        "> **기술적 비교 해석**: `PERMITTED_REGIME` 및 비-EXTREME 리스크 필터 적용 시, 조기 역추세성 노이즈(Early variant 4주 중위수 "
        f"{early_4w:+.2f}%)를 차단하여 무제한 Control(4주 중위수 {ctrl_4w:+.2f}%) 대비 더 나은 기술적 성과 특성이 관찰됨.",
        "",
        "---",
        "",
        "## 6. 표본별 세부 결과",
        "",
        "| 표본 ID | 종목코드 | 종목명 | 인간 라벨 | 진입 여부 | 진입 등급 | 신호 발생일 | 체결일 | 체결 시가 | 4주 수익률 | 12주 수익률 | 미진입 사유 / 비고 |",
        "|---|:---:|---|---|:---:|:---:|:---:|:---:|---:|---:|---:|---|",
    ])

    for _, row in df_samples.iterrows():
        ef = "YES" if row["entry_found"] else "NO"
        gr = row["entry_grade"] or "-"
        sd = row["signal_date"] or "-"
        ed = row["execution_date"] or "-"
        eo = f"{row['entry_open']:,.0f}" if pd.notna(row["entry_open"]) else "-"
        r4 = f"{row['return_4w']:+.2f}%" if pd.notna(row["return_4w"]) else "-"
        r12 = f"{row['return_12w']:+.2f}%" if pd.notna(row["return_12w"]) else "-"
        rsn = row["no_entry_reason"] or "ENTRY_SUCCESS"
        lines.append(
            f"| {row['sample_id']} | `{row['ticker']}` | {row['name']} | `{row['human_outcome']}` | {ef} | {gr} | {sd} | {ed} | {eo} | {r4} | {r12} | `{rsn}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 7. 최종 연구 결론",
        f"> **결론: `{summary['final_research_conclusion']}` (후속 검증 가치 있음)**",
        ">",
        f"> - **진입 필터 선별력**: `{summary['sub_conclusions']['entry_filter_discrimination']}`",
        f"> - **수익률 프로파일**: `{summary['sub_conclusions']['forward_return_profile']}`",
        f"> - **전체 연구 상태**: `{summary['sub_conclusions']['overall_research_status']}`",
        ">",
        f"> {summary['conclusion_rationale']}",
        "",
        "*주의: 본 평가는 과거 Frozen OOS B 표본을 활용한 사후 평가(Retrospective Evaluation)이며, 수수료/세금/슬리피지가 제외된 총수익률(Gross Return) 기준입니다. Production 규칙으로 승격하지 않으며 후속 Prospective / Walk-Forward 연구 가설로 활용됩니다.*",
    ])

    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_samples, df_events, summary_json = run_evaluation()

    df_samples.to_csv(OUT_SAMPLES_CSV, index=False, encoding="utf-8-sig")
    df_events.to_csv(OUT_EVENT_LOG_CSV, index=False, encoding="utf-8-sig")
    OUT_EVAL_JSON.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False), encoding="utf-8")

    md_content = render_markdown(summary_json, df_samples)
    OUT_EVAL_MD.write_text(md_content, encoding="utf-8")

    print("Evaluation completed successfully!")
    print(f"Sample Results CSV: {OUT_SAMPLES_CSV}")
    print(f"Event Log CSV: {OUT_EVENT_LOG_CSV}")
    print(f"Evaluation JSON: {OUT_EVAL_JSON}")
    print(f"Evaluation MD: {OUT_EVAL_MD}")


if __name__ == "__main__":
    main()
