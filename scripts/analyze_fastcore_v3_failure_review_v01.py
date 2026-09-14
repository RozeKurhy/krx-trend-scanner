#!/usr/bin/env python3
"""Review FastCore V3 failure modes from the immutable official matched A/B."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_fastcore_v3_simple_v00 as v3
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    clip_to_identity_lifecycle,
)


OFFICIAL_DIR = ROOT / "artifacts/backtests/fastcore_v3_matched_ab_official_v01"
MATCHED_PATH = OFFICIAL_DIR / "matched_trades.csv"
OFFICIAL_SUMMARY_PATH = OFFICIAL_DIR / "summary.json"
OFFICIAL_ROBUSTNESS_PATH = OFFICIAL_DIR / "robustness.csv"
OFFICIAL_EXIT_REASON_PATH = OFFICIAL_DIR / "exit_reason_diagnostics.csv"
OFFICIAL_REPRESENTATIVE_PATH = OFFICIAL_DIR / "representative_cases.csv"

OUT_DIR = ROOT / "artifacts/backtests/fastcore_v3_failure_review_v01"
SUMMARY_PATH = OUT_DIR / "summary.json"
PRE_WINNER_PATH = OUT_DIR / "pre_winner_threshold_diagnostics.csv"
WINNER_SIDE_EFFECT_PATH = OUT_DIR / "winner_side_effect_diagnostics.csv"
REPORT_PATH = OUT_DIR / "report.md"
VALIDATION_DOC_PATH = ROOT / "docs/patterns/pattern_a_fast/validation/version_03_matched_ab_failure_review.md"

EXPECTED_TRADES = 973
EXPECTED_UNIQUE_TICKERS = 542
EXPECTED_PERIOD = ("2021-04-01", "2026-08-14", "2026-08-21")
THRESHOLDS = (-10.0, -15.0, -20.0, -30.0)
PRE_WINNER = "PRE_WINNER_LT_20"
WINNER_CAPABLE = "WINNER_CAPABLE_GE_20"
WINNER_CAPABLE_BEFORE_ACTIVATION = "WINNER_CAPABLE_GE_20_BEFORE_ACTIVATION"
V2_EXIT_CATEGORIES = ("LOSS_GUARD", "EXIT3", "EXIT4", "OPEN_AT_CUTOFF")
V3_EXIT_REASONS = ("SOFT_EXIT", "HARD_EXIT", "OPEN_AT_CUTOFF")


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _round(value: Any, digits: int = 6) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _mean_median(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    if frame.empty:
        return None, None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None, None
    return _round(values.mean()), _round(values.median())


def _normalise_matched(path: Path = MATCHED_PATH) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ticker": str, "control_trade_id": str})
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    frame["control_trade_id"] = frame["control_trade_id"].astype(str).str.strip()
    return frame


def validate_official_input(matched: pd.DataFrame, official_summary: Mapping[str, Any]) -> None:
    """Fail closed unless the immutable official matched result is unchanged."""
    if len(matched) != EXPECTED_TRADES:
        raise AssertionError(f"official matched rows must remain {EXPECTED_TRADES}: {len(matched)}")
    if int(matched["ticker"].nunique()) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError("official matched unique ticker count changed")
    if int(matched["control_trade_id"].duplicated().sum()) != 0:
        raise AssertionError("official matched control identity is duplicated")
    if official_summary.get("status") != "COMPLETE":
        raise AssertionError("official matched summary is not COMPLETE")
    period = (
        str(official_summary.get("evaluation_start")),
        str(official_summary.get("signal_cutoff")),
        str(official_summary.get("execution_support_end")),
    )
    if period != EXPECTED_PERIOD:
        raise AssertionError(f"official matched period changed: {period}")
    if int(official_summary.get("network_requests", -1)) != 0:
        raise AssertionError("official matched result does not certify network_requests=0")
    if int(official_summary["integrity"]["matched_rows"]) != EXPECTED_TRADES:
        raise AssertionError("official matched integrity count changed")
    cohort_counts = matched["full_path_mfe_cohort"].value_counts().to_dict()
    if int(cohort_counts.get(PRE_WINNER, 0)) != 236 or int(cohort_counts.get(WINNER_CAPABLE, 0)) != 737:
        raise AssertionError(f"official cohort counts changed: {cohort_counts}")


def cohort_counts(matched: pd.DataFrame) -> dict[str, int]:
    counts = matched["full_path_mfe_cohort"].value_counts()
    return {PRE_WINNER: int(counts.get(PRE_WINNER, 0)), WINNER_CAPABLE: int(counts.get(WINNER_CAPABLE, 0))}


def first_winner_activation_date(path: pd.DataFrame, entry_open: float) -> pd.Timestamp | None:
    """Return the first date running HIGH HWM reaches +20%, or None."""
    if path.empty:
        return None
    highs = pd.to_numeric(path["high"], errors="coerce")
    if highs.isna().any():
        raise AssertionError("daily HIGH contains non-numeric values")
    hwm = highs.cummax().clip(lower=float(entry_open))
    activation = hwm / float(entry_open) - 1.0 >= 0.20 - 1e-12
    dates = path.index[activation]
    return pd.Timestamp(dates[0]).normalize() if len(dates) else None


def first_breach_trading_days(path: pd.DataFrame, entry_open: float, threshold_pct: float) -> int | None:
    """Return zero-based trading days from entry to first completed CLOSE breach."""
    threshold = float(threshold_pct) / 100.0
    for offset, (_date, close) in enumerate(path["close"].items()):
        close_return = float(close) / float(entry_open) - 1.0
        if close_return <= threshold + 1e-12:
            return offset
    return None


def _identity_path(row: Mapping[str, Any], daily: pd.DataFrame) -> pd.DataFrame:
    lifecycle = IdentityLifecycle(
        ticker=str(row["ticker"]).zfill(6),
        isu_cd=str(row["isu_cd"]),
        market=str(row["market"]),
        effective_from=pd.Timestamp(row["identity_effective_from"]).normalize(),
        effective_to=min(pd.Timestamp(row["identity_effective_to"]).normalize(), pd.Timestamp(EXPECTED_PERIOD[2])),
    )
    clipped = clip_to_identity_lifecycle(daily, lifecycle)
    if clipped is None or clipped.empty:
        raise RuntimeError(f"missing identity-scoped daily data for {row['control_trade_id']}")
    entry_date = pd.Timestamp(row["entry_execution_date"]).normalize()
    path = clipped.loc[clipped.index >= entry_date].sort_index()
    if path.empty:
        raise RuntimeError(f"missing post-entry daily path for {row['control_trade_id']}")
    return path


def _load_daily_by_ticker(matched: pd.DataFrame) -> dict[str, pd.DataFrame]:
    repository = v3.build_repository_v2(ROOT, end=pd.Timestamp(EXPECTED_PERIOD[2]))
    loader = v3.RepositoryV2DailyLoader(repository, end=pd.Timestamp(EXPECTED_PERIOD[2]))
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in sorted(matched["ticker"].unique()):
        daily = loader.load(str(ticker))
        if daily is None or daily.empty:
            raise RuntimeError(f"missing local Repository V2 prices for {ticker}")
        daily_by_ticker[str(ticker)] = daily
    return daily_by_ticker


def build_pre_winner_threshold_diagnostics(matched: pd.DataFrame, daily_by_ticker: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    activation_days: list[int] = []
    for row in matched.to_dict("records"):
        path = _identity_path(row, daily_by_ticker[str(row["ticker"])])
        entry_open = float(row["entry_open"])
        activation_date = first_winner_activation_date(path, entry_open)
        cohort = str(row["full_path_mfe_cohort"])
        if cohort == PRE_WINNER:
            if activation_date is not None:
                raise AssertionError(f"pre-winner unexpectedly activates: {row['control_trade_id']}")
            analysis_cohort = PRE_WINNER
            analysis_path = path
        elif cohort == WINNER_CAPABLE:
            if activation_date is None:
                raise AssertionError(f"winner-capable lacks +20% activation: {row['control_trade_id']}")
            activation_days.append(int(path.index.get_loc(activation_date)))
            analysis_cohort = WINNER_CAPABLE_BEFORE_ACTIVATION
            analysis_path = path.loc[path.index < activation_date]
        else:
            raise AssertionError(f"unknown official cohort: {cohort}")
        for threshold in THRESHOLDS:
            rows.append({
                "control_trade_id": str(row["control_trade_id"]),
                "threshold": threshold,
                "cohort": analysis_cohort,
                "breach_days": first_breach_trading_days(analysis_path, entry_open, threshold),
            })

    detail = pd.DataFrame(rows)
    aggregate_rows: list[dict[str, Any]] = []
    for (threshold, cohort), frame in detail.groupby(["threshold", "cohort"], sort=True):
        breaches = pd.to_numeric(frame["breach_days"], errors="coerce").dropna()
        trade_count = len(frame)
        aggregate_rows.append({
            "threshold": float(threshold),
            "cohort": cohort,
            "trade_count": trade_count,
            "breach_count": int(len(breaches)),
            "breach_rate": _round(len(breaches) / trade_count * 100.0),
            "median_days_to_first_breach": _round(breaches.median()),
            "p25_days_to_first_breach": _round(breaches.quantile(0.25)),
            "p75_days_to_first_breach": _round(breaches.quantile(0.75)),
            "no_breach_count": int(trade_count - len(breaches)),
            "activation_reached_count": 0 if cohort == PRE_WINNER else trade_count,
            "trading_day_definition": "entry execution day = 0",
        })
    aggregate = pd.DataFrame(aggregate_rows).sort_values(["cohort", "threshold"], kind="mergesort").reset_index(drop=True)
    cohort_summary = {
        "pre_winner_activation_count": 0,
        "winner_capable_activation_count": len(activation_days),
        "winner_capable_activation_day_median": _round(pd.Series(activation_days).median()) if activation_days else None,
        "winner_capable_activation_day_p25": _round(pd.Series(activation_days).quantile(0.25)) if activation_days else None,
        "winner_capable_activation_day_p75": _round(pd.Series(activation_days).quantile(0.75)) if activation_days else None,
    }
    return aggregate, cohort_summary


def _return_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    v2_mean, v2_median = _mean_median(frame, "v2_terminal_return")
    v3_mean, v3_median = _mean_median(frame, "v3_terminal_return")
    delta_mean, delta_median = _mean_median(frame, "return_delta_v3_minus_v2")
    return {
        "trade_count": len(frame),
        "v2_mean_return": v2_mean,
        "v2_median_return": v2_median,
        "v3_mean_return": v3_mean,
        "v3_median_return": v3_median,
        "paired_mean_delta": delta_mean,
        "paired_median_delta": delta_median,
        "v2_mean_mae": _mean_median(frame, "v2_mae")[0],
        "v3_mean_mae": _mean_median(frame, "v3_strategy_path_mae")[0],
        "v2_median_holding": _mean_median(frame, "v2_holding_days")[1],
        "v3_median_holding": _mean_median(frame, "v3_holding_days")[1],
        "v2_open_count": int((frame["v2_trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "v3_open_count": int((frame["v3_trade_status"] == "OPEN_AT_CUTOFF").sum()),
        "v2_open_rate": _round((frame["v2_trade_status"] == "OPEN_AT_CUTOFF").mean() * 100.0) if len(frame) else None,
        "v3_open_rate": _round((frame["v3_trade_status"] == "OPEN_AT_CUTOFF").mean() * 100.0) if len(frame) else None,
        "v2_ge_50_count": int((pd.to_numeric(frame["v2_terminal_return"], errors="coerce") >= 50.0).sum()),
        "v3_ge_50_count": int((pd.to_numeric(frame["v3_terminal_return"], errors="coerce") >= 50.0).sum()),
        "v2_ge_100_count": int((pd.to_numeric(frame["v2_terminal_return"], errors="coerce") >= 100.0).sum()),
        "v3_ge_100_count": int((pd.to_numeric(frame["v3_terminal_return"], errors="coerce") >= 100.0).sum()),
        "v2_mean_giveback": _mean_median(frame, "v2_giveback")[0],
        "v2_median_giveback": _mean_median(frame, "v2_giveback")[1],
        "v3_mean_giveback": _mean_median(frame, "v3_giveback")[0],
        "v3_median_giveback": _mean_median(frame, "v3_giveback")[1],
        "improved_count": int((frame["improved_worsened_same"] == "improved").sum()),
        "worsened_count": int((frame["improved_worsened_same"] == "worsened").sum()),
        "same_count": int((frame["improved_worsened_same"] == "same").sum()),
    }


def build_v2_exit_cross_tab(matched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cohort in (PRE_WINNER, WINNER_CAPABLE):
        for exit_category in V2_EXIT_CATEGORIES:
            frame = matched[(matched["full_path_mfe_cohort"] == cohort) & (matched["v2_exit_category"] == exit_category)]
            metrics = _return_metrics(frame)
            rows.append({"cohort": cohort, "v2_exit_category": exit_category, **metrics})
    return pd.DataFrame(rows)


def _representative_records(frame: pd.DataFrame, case_type: str, limit: int = 10, ascending: bool = True) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    ordered = frame.sort_values(
        ["return_delta_v3_minus_v2", "ticker", "entry_execution_date", "control_trade_id"],
        ascending=[ascending, True, True, True],
        kind="mergesort",
    ).head(limit)
    fields = [
        "ticker", "name", "market", "control_trade_id", "entry_execution_date", "entry_open",
        "v2_exit_category", "v2_terminal_return", "v3_exit_reason", "v3_terminal_return",
        "return_delta_v3_minus_v2", "v2_giveback", "v3_giveback", "v2_holding_days", "v3_holding_days",
    ]
    return [{"case_type": case_type, "rank": rank, **{field: row.get(field) for field in fields}} for rank, row in enumerate(ordered.to_dict("records"), 1)]


def build_winner_side_effect_diagnostics(matched: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    winner = matched[matched["full_path_mfe_cohort"] == WINNER_CAPABLE]
    rows: list[dict[str, Any]] = []

    def add(section: str, group: str, values: Mapping[str, Any]) -> None:
        rows.append({"section": section, "group": group, **values})

    basic = _return_metrics(winner)
    add("COHORT_SUMMARY", WINNER_CAPABLE, basic)

    reason_summary: dict[str, Any] = {}
    for reason in V3_EXIT_REASONS:
        frame = winner[winner["v3_exit_reason"] == reason]
        metrics = _return_metrics(frame)
        row = {
            **metrics,
            "v3_mean_return": metrics["v3_mean_return"],
            "v3_median_return": metrics["v3_median_return"],
            "v2_ge_50_count": metrics["v2_ge_50_count"],
            "v2_ge_100_count": metrics["v2_ge_100_count"],
            "v3_ge_50_count": metrics["v3_ge_50_count"],
            "v3_ge_100_count": metrics["v3_ge_100_count"],
        }
        add("V3_EXIT_REASON", reason, row)
        reason_summary[reason] = row

    damage_sets = {
        "V2_GE_50_V3_LT_50": (pd.to_numeric(winner["v2_terminal_return"], errors="coerce") >= 50.0) & (pd.to_numeric(winner["v3_terminal_return"], errors="coerce") < 50.0),
        "V2_GE_100_V3_LT_100": (pd.to_numeric(winner["v2_terminal_return"], errors="coerce") >= 100.0) & (pd.to_numeric(winner["v3_terminal_return"], errors="coerce") < 100.0),
    }
    damage_summary: dict[str, Any] = {}
    for group, mask in damage_sets.items():
        frame = winner[mask]
        mean_delta, median_delta = _mean_median(frame, "return_delta_v3_minus_v2")
        distribution = dict(sorted(Counter(frame["v3_exit_reason"].astype(str)).items()))
        representatives = _representative_records(frame, group, ascending=True)
        values = {
            "trade_count": len(frame),
            "paired_mean_delta": mean_delta,
            "paired_median_delta": median_delta,
            "v3_exit_reason_distribution": json.dumps(distribution, ensure_ascii=False, sort_keys=True),
        }
        add("DAMAGE_SET", group, values)
        for representative in representatives:
            add("DAMAGE_REPRESENTATIVE", group, {"representative_rank": representative["rank"], **representative})
        damage_summary[group] = {
            "trade_count": len(frame),
            "paired_mean_delta": mean_delta,
            "paired_median_delta": median_delta,
            "v3_exit_reason_distribution": distribution,
            "representatives": representatives,
        }

    improvement_representatives = _representative_records(winner, "WINNER_CAPABLE_LARGEST_IMPROVEMENT", ascending=False)
    for representative in improvement_representatives:
        add("IMPROVEMENT_REPRESENTATIVE", "WINNER_CAPABLE_LARGEST_IMPROVEMENT", {"representative_rank": representative["rank"], **representative})

    return pd.DataFrame(rows), {
        "basic": basic,
        "v3_exit_reason": reason_summary,
        "large_winner_damage": damage_summary,
        "largest_improvement_representatives": improvement_representatives,
    }


def _threshold_summary_rows(thresholds: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: (value.item() if hasattr(value, "item") else value) for key, value in row.items()}
        for row in thresholds.to_dict("records")
    ]


def _build_report(summary: Mapping[str, Any], thresholds: pd.DataFrame, cross_tab: pd.DataFrame, side_effect: Mapping[str, Any]) -> str:
    conclusions = summary["conclusions"]
    lines = [
        "# FastCore V3 공식 A/B 실패 사례 검토",
        "",
        "## 결론 요약",
        "",
        f"- V3 전체: `{conclusions['overall']}`",
        f"- Pre-Winner: `{conclusions['pre_winner']}`",
        f"- Winner HWM: `{conclusions['winner_hwm']}`",
        f"- 후속 연구 가치: `{conclusions['future_research']}`",
        "",
        "공식 matched A/B 973건은 재실행하거나 수정하지 않고 불변 입력으로 사용했다. 이번 문서는 V3 규칙이나 새 후보를 설계하지 않는 실패 원인 진단이다.",
        "",
        "## 공식 A/B 결과 요약",
        "",
        f"- Pre-Winner: `{summary['cohorts'][PRE_WINNER]['trade_count']}`건",
        f"- Winner-capable: `{summary['cohorts'][WINNER_CAPABLE]['trade_count']}`건",
        f"- V2/V3 mean return: `{summary['overall']['v2_mean_return']}% / {summary['overall']['v3_mean_return']}%`",
        f"- V2/V3 median return: `{summary['overall']['v2_median_return']}% / {summary['overall']['v3_median_return']}%`",
        f"- V2/V3 <= -30%: `{summary['overall']['v2_tail_le_30_count']} / {summary['overall']['v3_tail_le_30_count']}`",
        f"- V2/V3 >= +50%: `{summary['overall']['v2_ge_50_count']} / {summary['overall']['v3_ge_50_count']}`",
        "",
        "## Pre-Winner 문제",
        "",
        f"V3 Pre-Winner {summary['pre_winner_analysis']['trade_count']}건은 모두 +20% activation에 도달하지 않았고, V3에서는 `{summary['pre_winner_analysis']['v3_open_count']}/{summary['pre_winner_analysis']['trade_count']}`건이 OPEN_AT_CUTOFF로 남았다.",
        "",
        "| threshold | cohort | breach rate | median days | P25 | P75 | no breach |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in thresholds.to_dict("records"):
        lines.append(f"| {row['threshold']}% | {row['cohort']} | {row['breach_rate']}% | {row['median_days_to_first_breach']} | {row['p25_days_to_first_breach']} | {row['p75_days_to_first_breach']} | {row['no_breach_count']} |")
    lines.extend([
        "",
        "Trading days are zero-based from the entry execution day. Winner-capable rows are measured strictly before their first +20% activation date.",
        "",
        "## 미래 Winner와의 구분 가능성",
        "",
        "진단용 손실선은 규칙 선택이나 threshold optimization에 사용하지 않았다. 같은 표의 Winner-capable pre-activation 행은 최종적으로 +20% activation에 도달한 737건의 activation 이전 경로만 나타낸다.",
        "",
        "## Winner HWM 성과",
        "",
        f"- Winner-capable mean return V2/V3: `{side_effect['basic']['v2_mean_return']}% / {side_effect['basic']['v3_mean_return']}%`",
        f"- Winner-capable median return V2/V3: `{side_effect['basic']['v2_median_return']}% / {side_effect['basic']['v3_median_return']}%`",
        f"- paired mean/median delta: `{side_effect['basic']['paired_mean_delta']}% / {side_effect['basic']['paired_median_delta']}%`",
        f"- V2/V3 >= +50%: `{side_effect['basic']['v2_ge_50_count']} / {side_effect['basic']['v3_ge_50_count']}`",
        f"- V2/V3 >= +100%: `{side_effect['basic']['v2_ge_100_count']} / {side_effect['basic']['v3_ge_100_count']}`",
        f"- improved/worsened/same: `{side_effect['basic']['improved_count']} / {side_effect['basic']['worsened_count']} / {side_effect['basic']['same_count']}`",
        "",
        "| V3 exit reason | count | V3 mean return | V3 median return | paired mean delta | V2 >= +50 | V2 >= +100 | V3 >= +50 | V3 >= +100 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for reason, values in side_effect["v3_exit_reason"].items():
        lines.append(f"| {reason} | {values['trade_count']} | {values['v3_mean_return']} | {values['v3_median_return']} | {values['paired_mean_delta']} | {values['v2_ge_50_count']} | {values['v2_ge_100_count']} | {values['v3_ge_50_count']} | {values['v3_ge_100_count']} |")
    lines.extend([
        "",
        "## 대형 Winner 훼손",
        "",
    ])
    for group, values in side_effect["large_winner_damage"].items():
        lines.extend([
            f"- `{group}`: `{values['trade_count']}`건, paired mean/median delta `{values['paired_mean_delta']}% / {values['paired_median_delta']}%`, V3 exit reason `{values['v3_exit_reason_distribution']}`",
        ])
    lines.extend([
        "",
        "대표 최악 사례와 전체 deterministic 목록은 `winner_side_effect_diagnostics.csv`에 기록했다.",
        "",
        "## V2 청산 사유와 full-path 결과",
        "",
        "`pre_winner_threshold_diagnostics.csv`와 함께 공식 matched 입력의 V2 청산 사유 교차표는 summary.json의 `v2_exit_cross_tab`에 보존했다. 특히 V2 Loss Guard로 종료된 Winner-capable 거래 수는 `" + str(summary['v2_loss_guard_winner_capable_count']) + "`건이다.",
        "",
        "## 종합 판단",
        "",
        f"- Pre-Winner 분류: `{conclusions['pre_winner']}` — {conclusions['pre_winner_reason']}",
        f"- Winner HWM 분류: `{conclusions['winner_hwm']}` — {conclusions['winner_hwm_reason']}",
        f"- 후속 연구: `{conclusions['future_research']}` — {conclusions['future_research_reason']}",
        "",
        "이번 작업에서는 구체적인 stop threshold, FAST state 조합, V4/V3.1 규칙을 확정하지 않았고 기존 V3도 수정하지 않았다.",
        "",
        "## 실행 제한 및 무결성",
        "",
        f"- network requests: `{summary['network_requests']}`",
        "- 공식 A/B rerun: `NO`",
        "- V3 rule change: `NO`",
        "- new candidate design: `NO`",
        f"- official artifact modified: `{summary['official_artifact_modified']}`",
        "",
    ])
    return "\n".join(lines)


def _build_validation_document(summary: Mapping[str, Any], thresholds: pd.DataFrame, cross_tab: pd.DataFrame, side_effect: Mapping[str, Any]) -> str:
    report = _build_report(summary, thresholds, cross_tab, side_effect)
    return report.replace("# FastCore V3 공식 A/B 실패 사례 검토", "# A FAST Core V3 공식 A/B 실패 사례 검토", 1)


def run_analysis() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matched = _normalise_matched()
    official_summary = _json_read(OFFICIAL_SUMMARY_PATH)
    validate_official_input(matched, official_summary)
    daily_by_ticker = _load_daily_by_ticker(matched)
    thresholds, activation_summary = build_pre_winner_threshold_diagnostics(matched, daily_by_ticker)
    cross_tab = build_v2_exit_cross_tab(matched)
    side_effect_csv, side_effect = build_winner_side_effect_diagnostics(matched)
    overall = _return_metrics(matched)
    overall["v2_tail_le_30_count"] = int((pd.to_numeric(matched["v2_terminal_return"], errors="coerce") <= -30.0).sum())
    overall["v3_tail_le_30_count"] = int((pd.to_numeric(matched["v3_terminal_return"], errors="coerce") <= -30.0).sum())
    pre_winner_frame = matched[matched["full_path_mfe_cohort"] == PRE_WINNER]
    winner_frame = matched[matched["full_path_mfe_cohort"] == WINNER_CAPABLE]
    pre_winner_analysis = {
        **_return_metrics(pre_winner_frame),
        "trade_count": len(pre_winner_frame),
        "v3_open_count": int((pre_winner_frame["v3_trade_status"] == "OPEN_AT_CUTOFF").sum()),
    }
    winner_analysis = _return_metrics(winner_frame)
    loss_guard_winner_count = int(((winner_frame["v2_exit_category"] == "LOSS_GUARD")).sum())
    robustness = _json_read(OFFICIAL_SUMMARY_PATH).get("preregistered_decision", {}).get("default_promotion_robustness", {})
    conclusions = {
        "overall": "OFFICIAL_ADOPTION_FAILED",
        "pre_winner": "PRIMARY_FAILURE_SOURCE",
        "pre_winner_reason": "236건 전부 activation 없이 V3 OPEN_AT_CUTOFF에 남았고, V3 terminal loss와 holding이 V2보다 크게 악화됐다.",
        "winner_hwm": "PROMISING_WITH_TAIL_COST",
        "winner_hwm_reason": "Winner-capable 평균·중앙값과 giveback 일부는 개선됐지만 +50%/+100% 대형 Winner가 줄고 큰 훼손 집합이 확인됐다.",
        "future_research": "NEW_CANDIDATE_JUSTIFIED",
        "future_research_reason": "Pre-Winner 보호와 Winner 보존을 분리한 다음 후보 연구의 근거는 있으나, 이번 작업에서는 새 규칙을 설계하지 않는다.",
    }
    summary: dict[str, Any] = {
        "work_id": "FASTCORE_V3_FAILURE_REVIEW_V01",
        "status": "COMPLETE",
        "official_ab_rerun": False,
        "official_artifact_modified": False,
        "network_requests": None,
        "evaluation_start": EXPECTED_PERIOD[0],
        "signal_cutoff": EXPECTED_PERIOD[1],
        "execution_support_end": EXPECTED_PERIOD[2],
        "final_valuation": "2026-08-21 CLOSE",
        "official_input": {
            "matched_trades": str(MATCHED_PATH.relative_to(ROOT)),
            "summary": str(OFFICIAL_SUMMARY_PATH.relative_to(ROOT)),
            "robustness": str(OFFICIAL_ROBUSTNESS_PATH.relative_to(ROOT)),
            "exit_reason_diagnostics": str(OFFICIAL_EXIT_REASON_PATH.relative_to(ROOT)),
            "representative_cases": str(OFFICIAL_REPRESENTATIVE_PATH.relative_to(ROOT)),
        },
        "integrity": {
            "matched_rows": len(matched),
            "unique_tickers": int(matched["ticker"].nunique()),
            "duplicated_control_trade_identity": int(matched["control_trade_id"].duplicated().sum()),
            "cohort_sum": int(len(pre_winner_frame) + len(winner_frame)),
            "pass": True,
        },
        "cohorts": {
            PRE_WINNER: {"trade_count": len(pre_winner_frame), "definition": "full_path_raw_mfe < +20%"},
            WINNER_CAPABLE: {"trade_count": len(winner_frame), "definition": "full_path_raw_mfe >= +20%"},
        },
        "overall": overall,
        "pre_winner_analysis": pre_winner_analysis,
        "winner_capable_analysis": winner_analysis,
        "activation_summary": activation_summary,
        "pre_winner_threshold_diagnostics": _threshold_summary_rows(thresholds),
        "v2_exit_cross_tab": _threshold_summary_rows(cross_tab),
        "v2_loss_guard_winner_capable_count": loss_guard_winner_count,
        "winner_side_effect": side_effect,
        "official_preregistered_decision": _json_read(OFFICIAL_SUMMARY_PATH)["preregistered_decision"],
        "official_robustness_summary": robustness,
        "conclusions": conclusions,
        "mdd": "NOT_EVALUATED",
        "outputs": {
            "summary": str(SUMMARY_PATH.relative_to(ROOT)),
            "pre_winner_threshold_diagnostics": str(PRE_WINNER_PATH.relative_to(ROOT)),
            "winner_side_effect_diagnostics": str(WINNER_SIDE_EFFECT_PATH.relative_to(ROOT)),
            "report": str(REPORT_PATH.relative_to(ROOT)),
            "validation_document": str(VALIDATION_DOC_PATH.relative_to(ROOT)),
        },
    }
    return summary, thresholds, side_effect_csv, cross_tab


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run to execute the local-only failure review")
    audit = v3.NetworkAudit()
    try:
        with v3.network_guard(audit):
            summary, thresholds, side_effect_csv, cross_tab = run_analysis()
        summary["network_requests"] = audit.request_count
        if audit.request_count != 0:
            summary["status"] = "FAIL"
            raise AssertionError(f"network_requests must be 0, got {audit.request_count}")
        report = _build_report(summary, thresholds, cross_tab, summary["winner_side_effect"])
        document = _build_validation_document(summary, thresholds, cross_tab, summary["winner_side_effect"])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        thresholds.to_csv(PRE_WINNER_PATH, index=False, lineterminator="\n")
        side_effect_csv.to_csv(WINNER_SIDE_EFFECT_PATH, index=False, lineterminator="\n")
        _json_write(SUMMARY_PATH, summary)
        REPORT_PATH.write_text(report, encoding="utf-8")
        VALIDATION_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        VALIDATION_DOC_PATH.write_text(document, encoding="utf-8")
        print(json.dumps({
            "status": summary["status"],
            "pre_winner": summary["cohorts"][PRE_WINNER]["trade_count"],
            "winner_capable": summary["cohorts"][WINNER_CAPABLE]["trade_count"],
            "network_requests": summary["network_requests"],
            "pre_winner_classification": summary["conclusions"]["pre_winner"],
            "winner_hwm_classification": summary["conclusions"]["winner_hwm"],
            "future_research": summary["conclusions"]["future_research"],
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"FASTCORE V3 FAILURE REVIEW BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
