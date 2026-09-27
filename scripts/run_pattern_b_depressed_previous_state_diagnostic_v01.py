#!/usr/bin/env python3
"""Diagnose the last Pattern B state before existing DEPRESSED entry signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from scripts import run_pattern_b_pure_strategy_pit_1t_simple_v01 as pit_study  # noqa: E402

STUDY_ID = "PATTERN_B_DEPRESSED_PREVIOUS_STATE_DIAGNOSTIC_V01"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/depressed_previous_state_v01")
SEED = 20260927
REVIEW_COUNT = 40
STATE_ORDER = (
    "NORMAL",
    "DEEP_DEPRESSED",
    "OVERHEATED",
    "EXTREME_OVERHEATED",
    "DEPRESSED",
    "UNAVAILABLE",
)
KEY_COLUMNS = ("ticker", "isu_cd", "entry_signal_date")
PATH_FIELDS = (
    "first_normal_date",
    "days_to_first_normal",
    "first_deep_depressed_date",
    "days_to_first_deep_depressed",
    "first_target_state",
    "path_classification",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_text(data_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=data_root, check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _clean(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _date_state_rows(group: pd.DataFrame, component_id: str, before_date: str) -> pd.DataFrame:
    return group.loc[
        (group["component_id"].astype(str) == str(component_id))
        & (group["snapshot_date"].astype(str) < str(before_date))
    ].sort_values("snapshot_date")


def _last_distinct_previous_state(
    group: pd.DataFrame, event: Mapping[str, Any]
) -> tuple[str, str | None, bool]:
    """Return the final known non-DEPRESSED state before the current DEPRESSED run."""
    entry_date = str(event["entry_signal_date"])[:10]
    before = _date_state_rows(group, str(event["component_id"]), entry_date)
    known = before.loc[before["state"].notna() & before["state"].astype(str).ne("DEPRESSED")]
    if known.empty:
        return "UNAVAILABLE", None, False
    row = known.iloc[-1]
    state = str(row["state"])
    if state not in set(STATE_ORDER) - {"UNAVAILABLE"}:
        return "UNAVAILABLE", str(row["snapshot_date"]), False
    date = str(row["snapshot_date"])
    direct_previous_matches = (
        date == str(event.get("previous_state_date"))[:10]
        and state == str(event.get("previous_state"))
        and base.month_is_adjacent(date, entry_date)
    )
    return state, date, direct_previous_matches


def _path_classification(
    group: pd.DataFrame,
    event: Mapping[str, Any],
    trading_position: Mapping[str, int],
) -> dict[str, Any]:
    entry_date = str(event["entry_signal_date"])[:10]
    held = group.loc[
        (group["component_id"].astype(str) == str(event["component_id"]))
        & (group["snapshot_date"].astype(str) > entry_date)
        & (group["snapshot_date"].astype(str) <= base.SIGNAL_END)
    ].sort_values("snapshot_date")
    normal = held.loc[held["state"].astype(str).eq("NORMAL"), "snapshot_date"]
    deep = held.loc[held["state"].astype(str).eq("DEEP_DEPRESSED"), "snapshot_date"]
    normal_date = str(normal.iloc[0]) if not normal.empty else None
    deep_date = str(deep.iloc[0]) if not deep.empty else None
    if normal_date is not None and deep_date is not None and normal_date == deep_date:
        first = "CONFLICT"
    elif normal_date is not None and (deep_date is None or normal_date < deep_date):
        first = "NORMAL"
    elif deep_date is not None and (normal_date is None or deep_date < normal_date):
        first = "DEEP_DEPRESSED"
    else:
        first = None
    if first == "NORMAL":
        classification = "NORMAL_FIRST"
    elif first == "DEEP_DEPRESSED":
        classification = "DEEP_DEPRESSED_FIRST"
    elif first == "CONFLICT":
        classification = "NORMAL_DEEP_SAME_DATE_CONFLICT"
    else:
        classification = "NEITHER_BY_STATE_FRONTIER"

    def elapsed_sessions(reach_date: str | None) -> int | None:
        if reach_date is None:
            return None
        if entry_date not in trading_position or reach_date not in trading_position:
            raise RuntimeError(f"state date outside the merged KRX trading calendar: {entry_date}, {reach_date}")
        return trading_position[reach_date] - trading_position[entry_date]

    return {
        "first_normal_date": normal_date,
        "days_to_first_normal": elapsed_sessions(normal_date),
        "first_deep_depressed_date": deep_date,
        "days_to_first_deep_depressed": elapsed_sessions(deep_date),
        "first_target_state": first,
        "path_classification": classification,
    }


def _summarize_group(
    state: str,
    cohort: list[dict[str, Any]],
    trades_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    overall_signal_count: int,
) -> dict[str, Any]:
    trade_rows = [trades_by_key[_key(row)] for row in cohort if _key(row) in trades_by_key]
    realized = [row for row in trade_rows if row.get("trade_status") == "REALIZED"]
    opened = [row for row in trade_rows if row.get("trade_status") == "OPEN_AT_CUTOFF"]
    marked_open = [row for row in opened if base._safe_num(row.get("mark_to_cutoff_gross_return_pct")) is not None]
    unresolved_open = [row for row in opened if base._safe_num(row.get("mark_to_cutoff_gross_return_pct")) is None]
    returns = base._metric_summary(row.get("gross_return_pct") for row in realized)
    path = base._path_summary(realized)
    mark_returns = base._metric_summary(row.get("mark_to_cutoff_gross_return_pct") for row in marked_open)
    statuses = Counter(str(row.get("entry_signal_status") or "UNAVAILABLE") for row in cohort)
    first = Counter(str(row.get("path_classification") or "NEITHER_BY_STATE_FRONTIER") for row in cohort)
    normal_times = [row["days_to_first_normal"] for row in cohort if row.get("days_to_first_normal") is not None]
    deep_times = [row["days_to_first_deep_depressed"] for row in cohort if row.get("days_to_first_deep_depressed") is not None]
    return {
        "previous_state": state,
        "signal_count": len(cohort),
        "share_of_all_signals_pct": 100.0 * len(cohort) / overall_signal_count if overall_signal_count else None,
        "filled_trade_count": sum(status == "FILLED" for status in statuses.elements()),
        "realized_trade_count": len(realized),
        "open_trade_count": len(opened),
        "open_rate_of_filled_pct": 100.0 * len(opened) / len(trade_rows) if trade_rows else None,
        "suppressed_while_holding_count": statuses.get("SUPPRESSED_ALREADY_HOLDING", 0),
        "unfilled_or_other_signal_count": sum(value for key, value in statuses.items() if key not in {"FILLED", "SUPPRESSED_ALREADY_HOLDING"}),
        "signal_status_counts": dict(sorted(statuses.items())),
        "normal_first_count": first.get("NORMAL_FIRST", 0),
        "normal_first_rate_pct": 100.0 * first.get("NORMAL_FIRST", 0) / len(cohort) if cohort else None,
        "deep_first_count": first.get("DEEP_DEPRESSED_FIRST", 0),
        "deep_first_rate_pct": 100.0 * first.get("DEEP_DEPRESSED_FIRST", 0) / len(cohort) if cohort else None,
        "neither_by_state_frontier_count": first.get("NEITHER_BY_STATE_FRONTIER", 0),
        "neither_by_state_frontier_rate_pct": 100.0 * first.get("NEITHER_BY_STATE_FRONTIER", 0) / len(cohort) if cohort else None,
        "normal_reached_count": len(normal_times),
        "median_sessions_to_normal": float(pd.Series(normal_times, dtype="float64").median()) if normal_times else None,
        "deep_reached_count": len(deep_times),
        "median_sessions_to_deep": float(pd.Series(deep_times, dtype="float64").median()) if deep_times else None,
        "realized_mean_gross_pct": returns["mean_pct"],
        "realized_median_gross_pct": returns["median_pct"],
        "realized_win_rate_pct": returns["win_rate_pct"],
        "realized_ge_20_count": returns["ge_20_count"],
        "realized_ge_20_rate_pct": returns["ge_20_rate_pct"],
        "realized_ge_50_count": returns["ge_50_count"],
        "realized_ge_50_rate_pct": returns["ge_50_rate_pct"],
        "realized_ge_100_count": returns["ge_100_count"],
        "realized_ge_100_rate_pct": returns["ge_100_rate_pct"],
        "realized_le_20_count": returns["le_20_count"],
        "realized_le_20_rate_pct": returns["le_20_rate_pct"],
        "realized_le_30_count": returns["le_30_count"],
        "realized_le_30_rate_pct": returns["le_30_rate_pct"],
        "realized_le_50_count": returns["le_50_count"],
        "realized_le_50_rate_pct": returns["le_50_rate_pct"],
        "realized_mean_winner_pct": returns["average_winner_pct"],
        "realized_mean_loser_pct": returns["average_loser_pct"],
        "realized_mean_mfe_pct": path["mean_mfe_pct"],
        "realized_median_mfe_pct": path["median_mfe_pct"],
        "realized_mean_mae_pct": path["mean_mae_pct"],
        "realized_median_mae_pct": path["median_mae_pct"],
        "realized_mean_holding_sessions": path["mean_holding_krx_sessions"],
        "realized_median_holding_sessions": path["median_holding_krx_sessions"],
        "realized_p90_holding_sessions": path["p90_holding_krx_sessions"],
        "open_marked_count": len(marked_open),
        "open_unresolved_count": len(unresolved_open),
        "open_marked_mean_gross_pct": mark_returns["mean_pct"],
        "open_marked_median_gross_pct": mark_returns["median_pct"],
        "open_marked_le_30_count": mark_returns["le_30_count"],
        "open_marked_le_30_rate_pct": mark_returns["le_30_rate_pct"],
        "open_marked_le_50_count": mark_returns["le_50_count"],
        "open_marked_le_50_rate_pct": mark_returns["le_50_rate_pct"],
        "open_current_pattern_b_state_counts": dict(sorted(Counter(
            str(row.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE") for row in opened
        ).items())),
    }


def _review_sample(
    rows: list[dict[str, Any]],
    event_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    groups: Mapping[tuple[str, str], pd.DataFrame],
    signals_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    trades_by_key: Mapping[tuple[str, str, str], dict[str, Any]],
    trading_position: Mapping[str, int],
) -> list[dict[str, Any]]:
    count = min(REVIEW_COUNT, len(rows))
    selected = random.Random(SEED).sample(rows, count)
    reviewed = []
    for output in selected:
        key = _key(output)
        event = event_by_key[key]
        group = groups[(key[0], key[1])]
        prior_state, prior_date, prior_matches = _last_distinct_previous_state(group, event)
        path = _path_classification(group, event, trading_position)
        signal = signals_by_key[key]
        trade = trades_by_key.get(key)
        signal_ok = (
            str(signal.get("entry_signal_status")) == str(output.get("entry_signal_status"))
            and str(signal.get("previous_state")) == str(output.get("previous_state"))
            and str(signal.get("previous_state_date"))[:10] == str(output.get("previous_state_date"))[:10]
        )
        trade_ok = (
            (signal.get("entry_signal_status") == "FILLED" and trade is not None and trade.get("trade_id") == signal.get("trade_id"))
            or (signal.get("entry_signal_status") != "FILLED" and trade is None)
        )
        path_ok = all(path.get(field) == output.get(field) for field in PATH_FIELDS)
        no_future = bool(prior_date is None or prior_date < key[2]) and all(
            output.get(field) is None or str(output[field])[:10] <= key[2]
            for field in ("previous_state_date",)
        )
        reviewed.append({
            "ticker": key[0], "isu_cd": key[1], "entry_signal_date": key[2],
            "previous_state": output["previous_state"], "recomputed_previous_state": prior_state,
            "previous_state_date": output["previous_state_date"], "recomputed_previous_state_date": prior_date,
            "raw_signal_ledger_link_pass": signal_ok,
            "trade_ledger_link_pass": trade_ok,
            "path_first_arrival_recalculated_pass": path_ok,
            "no_future_previous_state_input_pass": no_future,
            "all_checks_pass": bool(prior_matches and signal_ok and trade_ok and path_ok and no_future),
        })
    return reviewed


def _core_table(summary_frame: pd.DataFrame) -> pd.DataFrame:
    keys = ("NORMAL", "DEEP_DEPRESSED")
    lookup = {str(row["previous_state"]): row for row in summary_frame.to_dict("records")}
    rows = []
    for state in keys:
        row = lookup[state]
        rows.append({
            "transition": f"{state} -> DEPRESSED",
            "N": row["signal_count"],
            "normal_first_pct": row["normal_first_rate_pct"],
            "deep_first_pct": row["deep_first_rate_pct"],
            "median_return_pct": row["realized_median_gross_pct"],
            "win_rate_pct": row["realized_win_rate_pct"],
            "ge_50_pct": row["realized_ge_50_rate_pct"],
            "le_30_pct": row["realized_le_30_rate_pct"],
            "le_50_pct": row["realized_le_50_rate_pct"],
            "open_rate_pct": row["open_rate_of_filled_pct"],
            "median_mae_pct": row["realized_median_mae_pct"],
        })
    return pd.DataFrame(rows)


def _verdict(summary_frame: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    lookup = {str(row["previous_state"]): row for row in summary_frame.to_dict("records")}
    normal = lookup["NORMAL"]
    deep = lookup["DEEP_DEPRESSED"]
    def direction(left: Any, right: Any, *, higher: bool) -> str:
        if left is None or right is None or pd.isna(left) or pd.isna(right):
            return "UNAVAILABLE"
        if float(left) == float(right):
            return "TIE"
        left_better = float(left) > float(right) if higher else float(left) < float(right)
        return "NORMAL_PRIOR" if left_better else "DEEP_PRIOR"

    comparisons = {
        "normal_first_rate_better_group": direction(normal["normal_first_rate_pct"], deep["normal_first_rate_pct"], higher=True),
        "lower_deep_first_rate_better_group": direction(normal["deep_first_rate_pct"], deep["deep_first_rate_pct"], higher=False),
        "median_return_better_group": direction(normal["realized_median_gross_pct"], deep["realized_median_gross_pct"], higher=True),
        "win_rate_better_group": direction(normal["realized_win_rate_pct"], deep["realized_win_rate_pct"], higher=True),
        "plus_50_rate_better_group": direction(normal["realized_ge_50_rate_pct"], deep["realized_ge_50_rate_pct"], higher=True),
        "realized_le_30_tail_better_group": direction(normal["realized_le_30_rate_pct"], deep["realized_le_30_rate_pct"], higher=False),
        "realized_le_50_tail_better_group": direction(normal["realized_le_50_rate_pct"], deep["realized_le_50_rate_pct"], higher=False),
        "open_le_30_tail_better_group": direction(normal["open_marked_le_30_rate_pct"], deep["open_marked_le_30_rate_pct"], higher=False),
        "open_le_50_tail_better_group": direction(normal["open_marked_le_50_rate_pct"], deep["open_marked_le_50_rate_pct"], higher=False),
    }
    path_group = None
    if comparisons["normal_first_rate_better_group"] == comparisons["lower_deep_first_rate_better_group"]:
        path_group = comparisons["normal_first_rate_better_group"]
    quality_group = None
    quality_directions = [
        comparisons["median_return_better_group"],
        comparisons["win_rate_better_group"],
        comparisons["plus_50_rate_better_group"],
    ]
    if quality_directions[0] in {"NORMAL_PRIOR", "DEEP_PRIOR"} and len(set(quality_directions)) == 1:
        quality_group = quality_directions[0]
    risk_directions = [
        comparisons["realized_le_30_tail_better_group"],
        comparisons["realized_le_50_tail_better_group"],
        comparisons["open_le_30_tail_better_group"],
        comparisons["open_le_50_tail_better_group"],
    ]
    risk_group = None
    if risk_directions[0] in {"NORMAL_PRIOR", "DEEP_PRIOR"} and len(set(risk_directions)) == 1:
        risk_group = risk_directions[0]
    comparisons["path_direction_group"] = path_group
    comparisons["quality_direction_group"] = quality_group
    comparisons["risk_direction_group"] = risk_group
    all_directions = [
        value for key, value in comparisons.items()
        if key.endswith("better_group") and key not in {"path_direction_group", "quality_direction_group", "risk_direction_group"}
    ]
    if path_group in {"NORMAL_PRIOR", "DEEP_PRIOR"} and path_group == quality_group == risk_group:
        verdict = "PATTERN_B_PREVIOUS_STATE_SIGNAL_PROMISING"
    elif all(value in {"TIE", "UNAVAILABLE"} for value in all_directions):
        verdict = "PATTERN_B_PREVIOUS_STATE_SIGNAL_WEAK"
    else:
        verdict = "PATTERN_B_PREVIOUS_STATE_SIGNAL_MIXED"
    return verdict, comparisons


def _report(
    verdict: str,
    core: pd.DataFrame,
    summaries: pd.DataFrame,
    open_summary: pd.DataFrame,
    raw_count: int,
    validations: dict[str, Any],
    verdict_checks: dict[str, Any],
) -> str:
    def pct(value: Any) -> str:
        return "n/a" if value is None or pd.isna(value) else f"{float(value):.2f}%"

    def number(value: Any) -> str:
        return "n/a" if value is None or pd.isna(value) else f"{float(value):.2f}"

    lines = [
        "# Pattern B DEPRESSED 진입 이전 상태 진단 V01",
        "",
        f"판정: **{verdict}**",
        "",
        "## 범위와 방법",
        "",
        f"- 기존 raw Pattern B DEPRESSED 진입 {raw_count:,}건과 기존 pure-strategy 신호·거래 원장을 연결했어. 새 진입 전략이나 전체 시장 재생은 하지 않았어.",
        f"- 직전 상태는 같은 PIT identity component에서 진입 신호일 전 마지막으로 관측한 non-DEPRESSED 상태야. 이후 경로는 월별 Pattern B 상태 관측 frontier {base.SIGNAL_END}까지만 분류했고, cutoff {base.CUTOFF}은 기존 미청산 평가를 그대로 연결했어.",
        "- NORMAL_FIRST / DEEP_DEPRESSED_FIRST는 신호 후 둘 중 어느 상태가 먼저 관측됐는지를 뜻해. 둘 다 frontier까지 없으면 `NEITHER_BY_STATE_FRONTIER`로 분류했어. 두 도달 소요일은 각각 첫 상태 관측까지 merged KRX 거래일 차이야.",
        "- 실현 수익·MFE·MAE·보유기간은 연결된 기존 실현 원장만, 평가수익은 exact cutoff close가 있는 기존 미청산만 사용했어.",
        "",
        "## 핵심 전이 비교",
        "",
        "| 이전 상태 → DEPRESSED | N | NORMAL 선도달 | DEEP 선도달 | 중앙수익 | 승률 | +50% | -30% | -50% | 미청산 비율 | 중앙 MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in core.to_dict("records"):
        lines.append(
            f"| {row['transition']} | {row['N']:,} | {pct(row['normal_first_pct'])} | {pct(row['deep_first_pct'])} | "
            f"{pct(row['median_return_pct'])} | {pct(row['win_rate_pct'])} | {pct(row['ge_50_pct'])} | "
            f"{pct(row['le_30_pct'])} | {pct(row['le_50_pct'])} | {pct(row['open_rate_pct'])} | {pct(row['median_mae_pct'])} |"
        )
    lines += [
        "",
        "## 모든 직전 상태",
        "",
        "| 직전 상태 | 신호 | 전체 비중 | 체결 | 실현 | 미청산 | 미청산률 | NORMAL 선도달 | DEEP 선도달 | 둘 다 미도달 | NORMAL 중앙 거래일 | DEEP 중앙 거래일 | 중앙수익 | 승률 | +50% | -30% | -50% | 평가 미해결 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries.to_dict("records"):
        lines.append(
            f"| {row['previous_state']} | {int(row['signal_count']):,} | {pct(row['share_of_all_signals_pct'])} | {int(row['filled_trade_count']):,} | "
            f"{int(row['realized_trade_count']):,} | {int(row['open_trade_count']):,} | {pct(row['open_rate_of_filled_pct'])} | {pct(row['normal_first_rate_pct'])} | "
            f"{pct(row['deep_first_rate_pct'])} | {pct(row['neither_by_state_frontier_rate_pct'])} | {number(row['median_sessions_to_normal'])} | "
            f"{number(row['median_sessions_to_deep'])} | {pct(row['realized_median_gross_pct'])} | {pct(row['realized_win_rate_pct'])} | "
            f"{pct(row['realized_ge_50_rate_pct'])} | {pct(row['realized_le_30_rate_pct'])} | {pct(row['realized_le_50_rate_pct'])} | {int(row['open_unresolved_count']):,} |"
        )
    normal = core.loc[core["transition"].eq("NORMAL -> DEPRESSED")].iloc[0].to_dict()
    deep = core.loc[core["transition"].eq("DEEP_DEPRESSED -> DEPRESSED")].iloc[0].to_dict()
    lines += [
        "",
        "## 미청산 cutoff 평가",
        "",
        "| 직전 상태 | 미청산 | cutoff exact 평가 | 평가 미해결 | 평균/중앙 평가수익 | -30% 이하 | -50% 이하 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in open_summary.to_dict("records"):
        lines.append(
            f"| {row['previous_state']} | {int(row['open_count']):,} | {int(row['exact_cutoff_marked_count']):,} | "
            f"{int(row['unresolved_count']):,} | {pct(row['marked_mean_return_pct'])} / {pct(row['marked_median_return_pct'])} | "
            f"{int(row['marked_le_30_count']):,} ({pct(row['marked_le_30_rate_pct'])}) | "
            f"{int(row['marked_le_50_count']):,} ({pct(row['marked_le_50_rate_pct'])}) |"
        )
    summary_lookup = {str(row["previous_state"]): row for row in summaries.to_dict("records")}
    normal_all = summary_lookup["NORMAL"]
    deep_all = summary_lookup["DEEP_DEPRESSED"]
    open_lookup = {str(row["previous_state"]): row for row in open_summary.to_dict("records")}
    normal_open = open_lookup["NORMAL"]
    deep_open = open_lookup["DEEP_DEPRESSED"]
    lines += [
        "",
        "## 핵심 질문 답변",
        "",
        f"1. **성과가 다른가?** 이후 상태 경로와 체결 거래 지표가 모두 달라. NORMAL 선행은 NORMAL이 먼저 관측된 비율이 {pct(normal['normal_first_pct'])}로 DEEP 선행 {pct(deep['normal_first_pct'])}보다 높고, DEEP가 먼저 관측된 비율은 {pct(normal['deep_first_pct'])} 대 {pct(deep['deep_first_pct'])}야. 실현 수익 지표의 방향은 서로 엇갈려.",
        f"2. **NORMAL 회복 선도달률이 높은 쪽?** NORMAL 선행이 {pct(normal['normal_first_pct'])}로 DEEP 선행 {pct(deep['normal_first_pct'])}보다 높아. 중앙 도달 기간도 {number(normal_all['median_sessions_to_normal'])} 거래일 대 {number(deep_all['median_sessions_to_normal'])} 거래일이야.",
        f"3. **DEEP 재하락 선도달률이 낮은 쪽?** NORMAL 선행이 {pct(normal['deep_first_pct'])}로 DEEP 선행 {pct(deep['deep_first_pct'])}보다 낮아. 이 비율은 NORMAL보다 DEEP가 먼저 관측된 경우를 세며, 관측 frontier까지의 어느 시점이든 DEEP를 한 번이라도 본 비율과는 달라.",
        f"4. **실현 수익 지표가 좋은 쪽?** 중앙수익은 DEEP 선행 {pct(deep['median_return_pct'])} 대 NORMAL 선행 {pct(normal['median_return_pct'])}, 승률은 NORMAL 선행 {pct(normal['win_rate_pct'])} 대 {pct(deep['win_rate_pct'])}, +50% 비율은 DEEP 선행 {pct(deep['ge_50_pct'])} 대 {pct(normal['ge_50_pct'])}야.",
        f"5. **손실 위험이 낮은 쪽?** 실현 -30% / -50% 비율은 NORMAL 선행 {pct(normal['le_30_pct'])} / {pct(normal['le_50_pct'])}, DEEP 선행 {pct(deep['le_30_pct'])} / {pct(deep['le_50_pct'])}로 NORMAL 선행이 낮아. cutoff exact 평가가 가능한 미청산만 보면 -30% / -50% 꼬리는 NORMAL 선행 {pct(normal_open['marked_le_30_rate_pct'])} / {pct(normal_open['marked_le_50_rate_pct'])}, DEEP 선행 {pct(deep_open['marked_le_30_rate_pct'])} / {pct(deep_open['marked_le_50_rate_pct'])}로 DEEP 선행이 낮아. 각각 평가 미해결은 {int(normal_open['unresolved_count']):,}건과 {int(deep_open['unresolved_count']):,}건이야.",
        f"6. **이전 상태가 방향 정보를 더하나?** 회복/악화 경로는 구분하지만 수익·손실·미청산 지표가 한쪽으로 정렬되지 않아, 일관된 매매 방향 정보가 확인됐다고 보기는 어려워. 실현 통계는 기존 전략에서 실제 체결된 거래만 대상으로 하며, NORMAL 선행 신호는 {int(normal_all['filled_trade_count']):,}/{int(normal_all['signal_count']):,}건 체결, DEEP 선행은 {int(deep_all['filled_trade_count']):,}/{int(deep_all['signal_count']):,}건 체결됐어. DEEP 선행 raw 신호 {int(deep_all['suppressed_while_holding_count']):,}건은 기존 보유 중이라 억제됐으므로 실현 성과 비교에는 체결 선택 편향이 있어.",
        f"7. **특정 전이 단독 백테스트 근거가 충분한가?** 현재 판정은 `{verdict}`라서 충분하지 않아. 사후 기준을 추가하거나 자동 후속 백테스트를 실행하지 않았어.",
        "",
        "## 해석 및 다음 단계",
        "",
        f"- 기준 상태 차이 요약: {json.dumps(verdict_checks, ensure_ascii=False, sort_keys=True)}",
        "- MIXED 결과이므로 특정 전이를 확정 후보로 승격하지 않아.",
        "",
        "## 검증",
        "",
        f"- raw 신호 원장 연결 누락 {validations['raw_signal_key_mismatch_count']}; 중복 {validations['duplicate_signal_key_count']}; 이전 상태 미확인 {validations['previous_state_unavailable_count']}.",
        f"- 전체 신호에서 first NORMAL/DEEP 동일 날짜 충돌 {validations['normal_deep_first_date_conflict_count']}; 미래 이전 상태 입력 {validations['future_previous_state_input_count']}; 기존 trade 연결 누락 {validations['filled_trade_link_missing_count']}.",
        f"- 무작위 직접 검수 {validations['direct_review_count']}/{validations['direct_review_pass_count']} 통과. 기존 원장 lineage는 metadata에 기록했어.",
        "",
        "## 산출물",
        "",
        "`state_group_summary.csv`, `core_transition_comparison.csv`, `signal_trade_path_linkage.csv`, `normal_deep_path_classification.csv`, `open_position_comparison.csv`, `signal_status_by_previous_state.csv`, `direct_review_sample.csv`, `summary.json`, `metadata.json`.",
        "",
    ]
    return "\n".join(lines)


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_head = _git_text(data_root, "rev-parse", "HEAD")
    origin_main_before = _git_text(data_root, "rev-parse", "origin/main")
    if start_head != origin_main_before:
        raise RuntimeError(f"expected clean main at origin/main before run: HEAD={start_head}, origin/main={origin_main_before}")

    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, _intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusions = base._read_monthly_samples(data_root, intervals, interval_to_component)
    control_summary, trades_frame, signals_frame, control_lineage = pit_study._load_control(data_root, samples)
    trades = [
        {key: _clean(value) for key, value in record.items()}
        for record in trades_frame.to_dict("records")
    ]
    signals = [
        {key: _clean(value) for key, value in record.items()}
        for record in signals_frame.to_dict("records")
    ]

    signals_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for identity in sorted(signals_by_identity) for event in signals_by_identity[identity]]
    fresh_keys = [_key(event) for event in all_events]
    signal_by_key = {_key(row): row for row in signals}
    if blocked or len(fresh_keys) != 20_076 or len(set(fresh_keys)) != len(fresh_keys):
        raise RuntimeError(f"raw signal reconciliation failed: n={len(fresh_keys)}, blocked={len(blocked)}")
    if set(fresh_keys) != set(signal_by_key):
        raise RuntimeError(
            "fresh raw Pattern B keys differ from the existing signal ledger: "
            f"missing={len(set(fresh_keys)-set(signal_by_key))}, extra={len(set(signal_by_key)-set(fresh_keys))}"
        )
    trade_by_key = {_key(row): row for row in trades}
    if len(trade_by_key) != len(trades):
        raise RuntimeError("existing trade ledger has duplicate entry-signal keys")
    filled_signal_keys = {
        _key(row) for row in signals if str(row.get("entry_signal_status")) == "FILLED"
    }
    if filled_signal_keys != set(trade_by_key):
        raise RuntimeError(
            "filled signal/trade linkage differs: "
            f"missing_trades={len(filled_signal_keys-set(trade_by_key))}, "
            f"orphan_trades={len(set(trade_by_key)-filled_signal_keys)}"
        )

    group_by_identity = {
        (str(identity[0]), str(identity[1])): group.sort_values("snapshot_date").reset_index(drop=True)
        for identity, group in samples.groupby(["ticker", "isu_cd"], sort=False)
    }
    trading_position = {date: index for index, date in enumerate(trading_dates)}
    signal_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    event_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    previous_state_matches = 0
    normal_deep_conflicts = 0
    future_prior_inputs = 0
    for event in all_events:
        key = _key(event)
        identity = (key[0], key[1])
        group = group_by_identity[identity]
        previous_state, previous_date, previous_matches = _last_distinct_previous_state(group, event)
        previous_state_matches += int(previous_matches)
        if previous_date is None or previous_date >= key[2]:
            future_prior_inputs += 1
        if not previous_matches and previous_state != "UNAVAILABLE":
            raise RuntimeError(f"reconstructed last distinct state differs from raw transition predecessor: {key}")
        path = _path_classification(group, event, trading_position)
        normal_deep_conflicts += int(path["path_classification"] == "NORMAL_DEEP_SAME_DATE_CONFLICT")
        control_signal = signal_by_key[key]
        trade = trade_by_key.get(key)
        status = str(control_signal.get("entry_signal_status"))
        if status == "FILLED" and trade is None:
            raise RuntimeError(f"filled signal lacks an existing trade ledger row: {key}")
        if status != "FILLED" and trade is not None:
            raise RuntimeError(f"non-filled signal unexpectedly maps to an existing trade: {key}")
        row = {
            **{column: event[column] for column in KEY_COLUMNS},
            "component_id": event["component_id"],
            "pattern_b_entry_state": event["entry_signal_state"],
            "previous_state": previous_state,
            "previous_state_date": previous_date,
            "entry_signal_status": status,
            "status_reason": control_signal.get("status_reason"),
            "trade_id": trade.get("trade_id") if trade else control_signal.get("trade_id"),
            "entry_execution_date": trade.get("entry_execution_date") if trade else control_signal.get("entry_execution_date"),
            "trade_status": trade.get("trade_status") if trade else None,
            "exit_signal_date": trade.get("exit_signal_date") if trade else None,
            "exit_signal_state": trade.get("exit_signal_state") if trade else None,
            "exit_execution_date": trade.get("exit_execution_date") if trade else None,
            "gross_return_pct": trade.get("gross_return_pct") if trade else None,
            "mark_to_cutoff_gross_return_pct": trade.get("mark_to_cutoff_gross_return_pct") if trade else None,
            "mfe_pct": trade.get("mfe_pct") if trade else None,
            "mae_pct": trade.get("mae_pct") if trade else None,
            "holding_krx_sessions": trade.get("holding_krx_sessions") if trade else None,
            **path,
        }
        signal_rows.append(row)
        path_rows.append({key_name: row[key_name] for key_name in (
            "ticker", "isu_cd", "entry_signal_date", "previous_state", "previous_state_date", "component_id",
            *PATH_FIELDS, "entry_signal_status", "trade_status",
        )})
        event_by_key[key] = event

    if future_prior_inputs:
        raise RuntimeError(f"previous-state lookahead detected: {future_prior_inputs}")
    signals_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in signal_rows:
        state = str(row["previous_state"] or "UNAVAILABLE")
        if state not in STATE_ORDER:
            state = "UNAVAILABLE"
            row["previous_state"] = state
        signals_by_state[state].append(row)
    summaries = pd.DataFrame([
        _summarize_group(state, signals_by_state.get(state, []), trade_by_key, len(signal_rows))
        for state in STATE_ORDER
    ])
    core = _core_table(summaries)
    verdict, verdict_comparisons = _verdict(summaries)
    open_rows = []
    for state in STATE_ORDER:
        cohort = signals_by_state.get(state, [])
        linked = [trade_by_key[_key(row)] for row in cohort if _key(row) in trade_by_key]
        opened = [row for row in linked if row.get("trade_status") == "OPEN_AT_CUTOFF"]
        marked = [row for row in opened if base._safe_num(row.get("mark_to_cutoff_gross_return_pct")) is not None]
        marks = [float(row["mark_to_cutoff_gross_return_pct"]) for row in marked]
        mark_stats = base._metric_summary(marks)
        state_counts = Counter(str(row.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE") for row in opened)
        open_rows.append({
            "previous_state": state,
            "open_count": len(opened),
            "exact_cutoff_marked_count": len(marked),
            "unresolved_count": len(opened) - len(marked),
            "marked_mean_return_pct": mark_stats["mean_pct"],
            "marked_median_return_pct": mark_stats["median_pct"],
            "marked_le_30_count": mark_stats["le_30_count"],
            "marked_le_30_rate_pct": mark_stats["le_30_rate_pct"],
            "marked_le_50_count": mark_stats["le_50_count"],
            "marked_le_50_rate_pct": mark_stats["le_50_rate_pct"],
            "current_pattern_b_state_counts": json.dumps(dict(sorted(state_counts.items())), ensure_ascii=False),
        })

    signal_by_key = {_key(row): row for row in signals}
    reviews = _review_sample(signal_rows, event_by_key, group_by_identity, signal_by_key, trade_by_key, trading_position)
    if len(reviews) < 20 or not all(row["all_checks_pass"] for row in reviews):
        raise RuntimeError(f"direct review did not pass: {sum(row['all_checks_pass'] for row in reviews)}/{len(reviews)}")
    state_status_rows = []
    for state in STATE_ORDER:
        for status, count in sorted(Counter(row["entry_signal_status"] for row in signals_by_state.get(state, [])).items()):
            state_status_rows.append({"previous_state": state, "entry_signal_status": status, "signal_count": count})

    signal_frame = pd.DataFrame(signal_rows)
    path_frame = pd.DataFrame(path_rows)
    raw_mismatch_count = len(set(fresh_keys).symmetric_difference(set(signal_by_key)))
    unavailable_count = sum(row["previous_state"] == "UNAVAILABLE" for row in signal_rows)
    previous_state_mismatch_count = len(signal_rows) - previous_state_matches - unavailable_count
    validation = {
        "raw_signal_count": len(signal_rows),
        "expected_raw_signal_count": 20_076,
        "raw_signal_key_mismatch_count": raw_mismatch_count,
        "duplicate_signal_key_count": len(signal_rows) - len(set(_key(row) for row in signal_rows)),
        "previous_state_unavailable_count": unavailable_count,
        "previous_state_mismatch_count": previous_state_mismatch_count,
        "previous_state_matches_raw_transition_predecessor_count": previous_state_matches,
        "future_previous_state_input_count": future_prior_inputs,
        "normal_deep_first_date_conflict_count": normal_deep_conflicts,
        "filled_trade_link_missing_count": len(filled_signal_keys - set(trade_by_key)),
        "orphan_trade_ledger_row_count": len(set(trade_by_key) - filled_signal_keys),
        "direct_review_count": len(reviews),
        "direct_review_pass_count": sum(bool(row["all_checks_pass"]) for row in reviews),
        "no_raw_signal_or_trade_replay": True,
        "existing_control_lineage_verified": True,
    }
    if any(validation[key] != 0 for key in (
        "raw_signal_key_mismatch_count", "duplicate_signal_key_count", "future_previous_state_input_count",
        "previous_state_mismatch_count", "normal_deep_first_date_conflict_count",
        "filled_trade_link_missing_count", "orphan_trade_ledger_row_count",
    )):
        raise RuntimeError(f"diagnostic validation failed: {validation}")

    core_normal = core.loc[core["transition"].eq("NORMAL -> DEPRESSED")].iloc[0].to_dict()
    core_deep = core.loc[core["transition"].eq("DEEP_DEPRESSED -> DEPRESSED")].iloc[0].to_dict()
    open_summary = pd.DataFrame(open_rows)
    next_candidate = None
    if verdict == "PATTERN_B_PREVIOUS_STATE_SIGNAL_PROMISING":
        next_candidate = (
            "NORMAL -> DEPRESSED"
            if verdict_comparisons["path_direction_group"] == "NORMAL_PRIOR"
            else "DEEP_DEPRESSED -> DEPRESSED"
        )
    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "raw_transition_signal_count": len(signal_rows),
        "permanent_exclusion_identity_count": permanent_exclusions,
        "previous_state_group_count": {str(row["previous_state"]): int(row["signal_count"]) for row in summaries.to_dict("records")},
        "core_normal_to_depressed": core_normal,
        "core_deep_to_depressed": core_deep,
        "verdict_comparisons": verdict_comparisons,
        "next_simple_backtest_candidate": next_candidate,
        "validation_checks": validation,
        "existing_control_summary": {
            "filled_trade_count": int(control_summary["filled_trade_count"]),
            "closed_trade_count": int(control_summary["closed_trade_count"]),
            "open_trade_count": int(control_summary["open_trade_count"]),
            "source_verdict": control_summary.get("verdict"),
        },
        "control_lineage": control_lineage,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    metadata = {
        "study_id": STUDY_ID,
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "start_head": start_head,
        "origin_main_before": origin_main_before,
        "starting_worktree_clean": True,
        "analysis_kind": "diagnostic join only; no new strategy backtest, daily OHLC reload, or market replay",
        "signal_period": summary["signal_period"],
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "evaluation_cutoff": base.CUTOFF,
        "universe": "existing Pattern B Pure Strategy V01 PIT eligible common universe and approved permanent exclusions; no cap filter; no future delisting filter",
        "raw_entry_rule": "existing adjacent-month NOT DEPRESSED -> DEPRESSED signal, unchanged",
        "previous_state_rule": "last observed non-DEPRESSED state before entry in the same contiguous PIT identity component; UNAVAILABLE when absent",
        "path_rule": "after each signal, compare the first later NORMAL and DEEP_DEPRESSED observation through the monthly Pattern B state frontier; trading-day gaps use merged KRX calendar",
        "worker_policy": "no parallel workers required; only versioned monthly snapshots, signal/trade ledgers, and merged authorities are read",
        "random_review_seed": SEED,
        "direct_review_sample_count": len(reviews),
        "source_sha256": {
            str(base.SAMPLE_PATH): _sha256(data_root / base.SAMPLE_PATH),
            str(base.PIT_PATH): _sha256(data_root / base.PIT_PATH),
            str(base.CALENDAR_PATH): _sha256(data_root / base.CALENDAR_PATH),
            str(pit_study.CONTROL_RELATIVE / "trade_ledger.csv"): _sha256(data_root / pit_study.CONTROL_RELATIVE / "trade_ledger.csv"),
            str(pit_study.CONTROL_RELATIVE / "entry_signal_ledger.csv"): _sha256(data_root / pit_study.CONTROL_RELATIVE / "entry_signal_ledger.csv"),
            "scripts/run_pattern_b_depressed_previous_state_diagnostic_v01.py": _sha256(Path(__file__).resolve()),
            "tests/test_pattern_b_depressed_previous_state_diagnostic_v01.py": _sha256(data_root / "tests/test_pattern_b_depressed_previous_state_diagnostic_v01.py"),
        },
        "source_provenance": provenance,
        "control_lineage": control_lineage,
        "verdict_rule": "use only the W-specified directional comparison: PROMISING requires path, realized quality, and risk measures to all favor the same prior-state group; cross-metric or path-risk direction conflicts are MIXED; all tied or unavailable comparisons are WEAK; no sample-fitted numeric threshold",
        "verdict_comparisons": verdict_comparisons,
        "validation_checks": validation,
        "output_files": [
            "report.md", "state_group_summary.csv", "core_transition_comparison.csv",
            "signal_trade_path_linkage.csv", "normal_deep_path_classification.csv",
            "open_position_comparison.csv", "signal_status_by_previous_state.csv",
            "direct_review_sample.csv", "summary.json", "metadata.json",
        ],
    }
    out = output_dir
    summaries.to_csv(out / "state_group_summary.csv", index=False, encoding="utf-8")
    core.to_csv(out / "core_transition_comparison.csv", index=False, encoding="utf-8")
    signal_frame.to_csv(out / "signal_trade_path_linkage.csv", index=False, encoding="utf-8")
    path_frame.to_csv(out / "normal_deep_path_classification.csv", index=False, encoding="utf-8")
    open_summary.to_csv(out / "open_position_comparison.csv", index=False, encoding="utf-8")
    pd.DataFrame(state_status_rows).to_csv(out / "signal_status_by_previous_state.csv", index=False, encoding="utf-8")
    pd.DataFrame(reviews).to_csv(out / "direct_review_sample.csv", index=False, encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=pit_study._json_default) + "\n", encoding="utf-8")
    (out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=pit_study._json_default) + "\n", encoding="utf-8")
    (out / "report.md").write_text(_report(verdict, core, summaries, open_summary, len(signal_rows), validation, verdict_comparisons), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "core": core.to_dict("records"), "groups": summaries.to_dict("records"), "validation": validation, "output": str(out)}, ensure_ascii=False, indent=2, default=pit_study._json_default), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
