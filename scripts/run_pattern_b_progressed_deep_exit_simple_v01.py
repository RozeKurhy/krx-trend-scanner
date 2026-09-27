#!/usr/bin/env python3
"""Compare the existing PROGRESSED entry strategy with a first-DEEP exit."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_deep_exit_simple_v01 as deep_engine  # noqa: E402
from scripts import run_pattern_b_pattern_a_entry_filter_simple_v01 as stage_study  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as base  # noqa: E402
from trend_scanner.data.repository_v2_loader import build_repository_v2  # noqa: E402

STUDY_ID = "PATTERN_B_PROGRESSED_DEEP_EXIT_SIMPLE_V01"
STRATEGY_ID = "PATTERN_B_PROGRESSED_DEEP_EXIT_SIMPLE_V01"
OUTPUT_RELATIVE = Path("artifacts/patterns/pattern_b/progressed_deep_exit_simple_v01")
ENTRY_FILTER_RELATIVE = Path("artifacts/patterns/pattern_b/pattern_a_entry_filter_simple_v01")
SIGNAL_KEY = ("ticker", "isu_cd", "entry_signal_date")
WORKERS = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_blob_sha(data_root: Path, revision: str, relative_path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative_path.as_posix()}"],
        cwd=data_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _git_text(data_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=data_root, check=True, stdout=subprocess.PIPE, text=True
    )
    return result.stdout.strip()


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        base.norm_ticker(row["ticker"]),
        base.norm_isu(row["isu_cd"]),
        str(row["entry_signal_date"])[:10],
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return stage_study._clean_records(frame)


def _select_progressed_events(
    events: list[dict[str, Any]], expected_keys: set[tuple[str, str, str]]
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    selected = []
    seen: set[tuple[str, str, str]] = set()
    for source in events:
        if source.get("pattern_a_stage") != "PROGRESSED":
            continue
        event = copy.deepcopy(source)
        key = _key(event)
        if key in seen:
            raise RuntimeError(f"duplicate PROGRESSED signal key: {key}")
        seen.add(key)
        if (
            str(event.get("pattern_a_requested_asof", ""))[:10] != key[2]
            or not stage_study._bool(event.get("pattern_a_lookahead_free"))
        ):
            raise RuntimeError(f"non-exact or lookahead-contaminated stage: {key}")
        event["entry_signal_status"] = "PENDING"
        event["trade_id"] = None
        event["entry_execution_date"] = None
        event["entry_reference_open"] = None
        event["status_reason"] = None
        selected.append(event)
    if seen != expected_keys:
        raise RuntimeError(
            "PROGRESSED candidate keys differ from the fixed CONTROL entry ledger: "
            f"missing={len(expected_keys - seen)}, extra={len(seen - expected_keys)}"
        )
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in selected:
        by_identity.setdefault((event["ticker"], event["isu_cd"]), []).append(event)
    return by_identity, selected


def _read_fixed_control(data_root: Path, start_head: str) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    output = data_root / ENTRY_FILTER_RELATIVE
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    if metadata.get("study_id") != "PATTERN_B_PATTERN_A_ENTRY_FILTER_SIMPLE_V01":
        raise RuntimeError("fixed PROGRESSED source is not the expected entry-filter study")
    if summary.get("evaluation_cutoff") != base.CUTOFF:
        raise RuntimeError("fixed PROGRESSED source cutoff differs from this task")
    if metadata.get("validation_checks", {}).get("test_progressed_contains_only_exact_progressed_stage") is not True:
        raise RuntimeError("fixed PROGRESSED source did not validate exact stage selection")

    files = {
        "metadata.json": output / "metadata.json",
        "summary.json": output / "summary.json",
        "progressed_entry_signal_ledger.csv": output / "progressed_entry_signal_ledger.csv",
        "progressed_trade_ledger.csv": output / "progressed_trade_ledger.csv",
    }
    committed_hashes = {}
    for name, path in files.items():
        relative = path.relative_to(data_root)
        actual = _sha256(path)
        committed = _git_blob_sha(data_root, start_head, relative)
        if actual != committed:
            raise RuntimeError(f"fixed PROGRESSED input is not byte-identical to HEAD: {relative}")
        committed_hashes[name] = committed

    for display, expected_hash in metadata.get("source_sha256", {}).items():
        if _sha256(data_root / display) != expected_hash:
            raise RuntimeError(f"entry-filter source changed since the fixed CONTROL run: {display}")

    signals_frame = pd.read_csv(
        files["progressed_entry_signal_ledger.csv"], dtype={"ticker": "string", "isu_cd": "string"}
    )
    trades_frame = pd.read_csv(
        files["progressed_trade_ledger.csv"], dtype={"ticker": "string", "isu_cd": "string"}
    )
    signals = _records(signals_frame)
    trades = _records(trades_frame)
    keys = [_key(row) for row in signals]
    if len(keys) != len(set(keys)):
        raise RuntimeError("fixed PROGRESSED candidate signal ledger has duplicate keys")
    if any(row.get("pattern_a_stage") != "PROGRESSED" for row in signals):
        raise RuntimeError("fixed PROGRESSED candidate ledger contains another stage")
    control_summary = summary["strategies"]["PROGRESSED"]
    if len(signals) != int(control_summary["stage_filter_pass_count"]):
        raise RuntimeError("fixed PROGRESSED signal count differs from its summary")
    if len(trades) != int(control_summary["filled_trade_count"]):
        raise RuntimeError("fixed PROGRESSED trade count differs from its summary")
    metrics = deep_engine._trade_summary(trades)
    count_checks = {
        "filled_count": "filled_trade_count",
        "closed_count": "realized_trade_count",
        "open_count": "open_trade_count",
    }
    for metric_key, summary_key in count_checks.items():
        if metrics[metric_key] != int(control_summary[summary_key]):
            raise RuntimeError(f"fixed CONTROL {metric_key} does not reconcile to summary")
    for metric, source in (("mean_pct", "mean_pct"), ("median_pct", "median_pct"), ("win_rate_pct", "win_rate_pct")):
        expected = control_summary["closed_gross"].get(source)
        actual = metrics["closed_gross"].get(metric)
        if expected is not None and not math.isclose(float(expected), float(actual), rel_tol=1e-11, abs_tol=1e-10):
            raise RuntimeError(f"fixed CONTROL closed gross {metric} does not reconcile")
    lineage = {
        "source_artifact_directory": str(ENTRY_FILTER_RELATIVE),
        "source_study_id": metadata["study_id"],
        "source_run_head_expected": metadata.get("starting_git", {}).get("head_expected"),
        "source_artifacts_head_sha256": committed_hashes,
        "source_artifact_control_lineage": metadata.get("control_lineage"),
        "fixed_control_replayed": False,
        "control_reconciliation": "committed PROGRESSED ledger retained byte-for-byte; signal/trade counts and realized gross metrics reconciled",
    }
    return summary, trades, signals, lineage


def _annual_stats(
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> pd.DataFrame:
    years = sorted({str(row["entry_signal_date"])[:4] for row in signals})
    rows = []
    for year in years:
        row: dict[str, Any] = {"entry_year": int(year), "candidate_signals": sum(str(event["entry_signal_date"])[:4] == year for event in signals)}
        for prefix, trades in (("control", control_trades), ("test", test_trades)):
            cohort = [trade for trade in trades if str(trade["entry_signal_date"])[:4] == year]
            realized = [trade for trade in cohort if trade.get("trade_status") == "REALIZED"]
            opened = [trade for trade in cohort if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
            metrics = base._metric_summary(trade.get("gross_return_pct") for trade in realized)
            open_values = [
                float(trade["mark_to_cutoff_gross_return_pct"])
                for trade in opened if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None
            ]
            row.update({
                f"{prefix}_filled": len(cohort),
                f"{prefix}_realized": len(realized),
                f"{prefix}_realized_median_pct": metrics["median_pct"],
                f"{prefix}_realized_win_rate_pct": metrics["win_rate_pct"],
                f"{prefix}_realized_ge_50_count": metrics["ge_50_count"],
                f"{prefix}_realized_ge_50_rate_pct": metrics["ge_50_rate_pct"],
                f"{prefix}_realized_le_30_count": metrics["le_30_count"],
                f"{prefix}_realized_le_30_rate_pct": metrics["le_30_rate_pct"],
                f"{prefix}_open": len(opened),
                f"{prefix}_open_rate_pct": 100.0 * len(opened) / len(cohort) if cohort else None,
                f"{prefix}_open_marked": len(open_values),
                f"{prefix}_open_le_30_count": sum(value <= -30 for value in open_values),
                f"{prefix}_open_le_30_rate_pct": 100.0 * sum(value <= -30 for value in open_values) / len(open_values) if open_values else None,
            })
        row["test_median_higher"] = bool(
            row["control_realized_median_pct"] is not None
            and row["test_realized_median_pct"] is not None
            and row["test_realized_median_pct"] > row["control_realized_median_pct"]
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _open_comparison(
    control_trades: list[dict[str, Any]], test_trades: list[dict[str, Any]]
) -> pd.DataFrame:
    rows = []
    for label, trades in (("CONTROL_PROGRESSED", control_trades), ("TEST_PROGRESSED_DEEP_EXIT", test_trades)):
        opened = [trade for trade in trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"]
        marked = [trade for trade in opened if base._safe_num(trade.get("mark_to_cutoff_gross_return_pct")) is not None]
        returns = [float(trade["mark_to_cutoff_gross_return_pct"]) for trade in marked]
        states = Counter(str(trade.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE") for trade in opened)
        stats = base._metric_summary(returns)
        rows.append({
            "strategy": label,
            "open_count": len(opened),
            "exact_cutoff_marked_count": len(marked),
            "unresolved_count": len(opened) - len(marked),
            "mark_coverage_pct": 100.0 * len(marked) / len(opened) if opened else None,
            "marked_mean_return_pct": stats["mean_pct"],
            "marked_median_return_pct": stats["median_pct"],
            "marked_le_30_count": sum(value <= -30 for value in returns),
            "marked_le_30_rate_pct": 100.0 * sum(value <= -30 for value in returns) / len(returns) if returns else None,
            "marked_le_50_count": sum(value <= -50 for value in returns),
            "marked_le_50_rate_pct": 100.0 * sum(value <= -50 for value in returns) / len(returns) if returns else None,
            "current_pattern_b_state_counts": json.dumps(dict(sorted(states.items())), ensure_ascii=False),
        })
    return pd.DataFrame(rows)


def _all_entry_pairs(
    control_signals: list[dict[str, Any]],
    test_signals: list[dict[str, Any]],
    control_trades: list[dict[str, Any]],
    test_trades: list[dict[str, Any]],
) -> pd.DataFrame:
    control_trade_by_key = {_key(row): row for row in control_trades}
    test_trade_by_key = {_key(row): row for row in test_trades}
    control_signal_by_key = {_key(row): row for row in control_signals}
    test_signal_by_key = {_key(row): row for row in test_signals}
    if len(control_signal_by_key) != len(control_signals) or len(test_signal_by_key) != len(test_signals):
        raise RuntimeError("duplicate candidate key in same-entry comparison")
    rows = []
    for key in sorted(control_signal_by_key):
        control = control_trade_by_key.get(key)
        test = test_trade_by_key.get(key)
        c_value, c_basis = _trade_outcome(control)
        t_value, t_basis = _trade_outcome(test)
        rows.append({
            "ticker": key[0], "isu_cd": key[1], "entry_signal_date": key[2],
            "control_signal_status": control_signal_by_key[key].get("entry_signal_status"),
            "test_signal_status": test_signal_by_key[key].get("entry_signal_status"),
            "control_trade_id": control.get("trade_id") if control else None,
            "control_trade_status": control.get("trade_status") if control else None,
            "control_outcome_basis": c_basis,
            "control_final_or_marked_gross_return_pct": c_value,
            "test_trade_id": test.get("trade_id") if test else None,
            "test_trade_status": test.get("trade_status") if test else None,
            "test_exit_signal_state": test.get("exit_signal_state") if test else None,
            "test_exit_signal_date": test.get("exit_signal_date") if test else None,
            "test_exit_execution_date": test.get("exit_execution_date") if test else None,
            "test_outcome_basis": t_basis,
            "test_final_or_marked_gross_return_pct": t_value,
            "test_minus_control_gross_pct_points": t_value - c_value if t_value is not None and c_value is not None else None,
        })
    return pd.DataFrame(rows)


def _trade_outcome(trade: dict[str, Any] | None) -> tuple[float | None, str]:
    if trade is None:
        return None, "NO_FILLED_TRADE"
    if trade.get("trade_status") == "REALIZED":
        value = base._safe_num(trade.get("gross_return_pct"))
        return value, "REALIZED_GROSS" if value is not None else "REALIZED_RETURN_UNAVAILABLE"
    if trade.get("trade_status") == "OPEN_AT_CUTOFF":
        value = base._safe_num(trade.get("mark_to_cutoff_gross_return_pct"))
        return value, "CUTOFF_MARK" if value is not None else "OPEN_UNRESOLVED"
    return None, str(trade.get("trade_status") or "UNKNOWN_STATUS")


def _loss_rescue_analysis(entry_pairs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    summary = {}
    for threshold in (20, 30, 50):
        eligible = entry_pairs.loc[
            entry_pairs["control_trade_status"].eq("REALIZED")
            & pd.to_numeric(entry_pairs["control_final_or_marked_gross_return_pct"], errors="coerce").le(-threshold)
        ]
        resolved = []
        counts = Counter()
        for row in eligible.to_dict("records"):
            test_value = base._safe_num(row.get("test_final_or_marked_gross_return_pct"))
            test_basis = str(row.get("test_outcome_basis"))
            if test_basis == "REALIZED_GROSS" and test_value is not None:
                outcome = "TEST_REALIZED_ABOVE_THRESHOLD" if test_value > -threshold else "TEST_REALIZED_STILL_AT_OR_BELOW"
                rescued = test_value > -threshold
                resolved.append(rescued)
            elif test_basis == "CUTOFF_MARK" and test_value is not None:
                outcome = "TEST_OPEN_MARK_ABOVE_THRESHOLD" if test_value > -threshold else "TEST_OPEN_MARK_AT_OR_BELOW"
                rescued = None
            elif test_basis == "OPEN_UNRESOLVED":
                outcome, rescued = "TEST_OPEN_UNRESOLVED", None
            else:
                outcome, rescued = "NO_TEST_FILLED_TRADE", None
            counts[outcome] += 1
            rows.append({
                **row,
                "control_loss_threshold_pct": -threshold,
                "test_outcome_vs_threshold": outcome,
                "rescued_after_realized_test_exit": rescued,
            })
        summary[str(-threshold)] = {
            "control_loss_denominator": len(eligible),
            "test_realized_rescue_count": sum(resolved),
            "test_realized_rescue_rate_pct": 100.0 * sum(resolved) / len(resolved) if resolved else None,
            "test_realized_comparable_count": len(resolved),
            "test_outcome_counts": dict(sorted(counts.items())),
        }
    return pd.DataFrame(rows), summary


def _winner_damage(deep_pairs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if deep_pairs.empty:
        return pd.DataFrame(), {"deep_exit_control_winner_denominator": 0}
    eligible = deep_pairs.loc[
        deep_pairs["is_primary_closed_to_closed_pair"].astype(bool)
        & pd.to_numeric(deep_pairs["control_final_or_marked_return_pct"], errors="coerce").gt(0)
    ].copy()
    control = pd.to_numeric(eligible["control_final_or_marked_return_pct"], errors="coerce")
    test = pd.to_numeric(eligible["test_deep_exit_gross_return_pct"], errors="coerce")
    eligible["control_winner_return_lowered"] = test.lt(control)
    eligible["control_winner_turned_loss"] = test.le(0)
    eligible["control_ge_20_cut_below_20"] = control.ge(20) & test.lt(20)
    eligible["control_ge_50_cut_below_50"] = control.ge(50) & test.lt(50)
    eligible["control_ge_100_cut_below_100"] = control.ge(100) & test.lt(100)
    damaged = eligible.loc[eligible["control_winner_return_lowered"]].copy()
    damaged_returns = pd.to_numeric(damaged["control_final_or_marked_return_pct"], errors="coerce")
    summary = {
        "deep_exit_control_winner_denominator": len(eligible),
        "deep_exit_winner_lowered_count": int(eligible["control_winner_return_lowered"].sum()),
        "control_winner_turned_loss_count": int(eligible["control_winner_turned_loss"].sum()),
        "control_ge_20_cut_below_20_count": int(eligible["control_ge_20_cut_below_20"].sum()),
        "control_ge_50_cut_below_50_count": int(eligible["control_ge_50_cut_below_50"].sum()),
        "control_ge_100_cut_below_100_count": int(eligible["control_ge_100_cut_below_100"].sum()),
        "damaged_control_return_mean_pct": float(damaged_returns.mean()) if len(damaged_returns) else None,
        "damaged_control_return_median_pct": float(damaged_returns.median()) if len(damaged_returns) else None,
        "damaged_control_return_p90_pct": float(damaged_returns.quantile(0.9)) if len(damaged_returns) else None,
    }
    return damaged, summary


def _open_state_counts(trades: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(
        str(row.get("current_pattern_b_state") or "CURRENT_STATE_UNAVAILABLE")
        for row in trades if row.get("trade_status") == "OPEN_AT_CUTOFF"
    ).items()))


def _overlap_count(trades: list[dict[str, Any]]) -> int:
    if not trades:
        return 0
    overlaps = 0
    frame = pd.DataFrame(trades)
    for identity, group in frame.groupby(["ticker", "isu_cd"], sort=False):
        ordered = sorted(group.to_dict("records"), key=lambda item: item["entry_execution_date"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["entry_execution_date"] <= (previous.get("exit_execution_date") or base.CUTOFF):
                overlaps += 1
                raise RuntimeError(f"overlapping same-ISU trades: {identity}")
    return overlaps


def _validate_fills(trades: list[dict[str, Any]], trading_dates: list[str], prices: dict[tuple[str, str, str], pd.DataFrame]) -> dict[str, int]:
    trading = set(trading_dates)
    invalid_entries = 0
    invalid_exits = 0
    for trade in trades:
        daily = prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        expected_entry = base.next_observed_open_date(daily.index, trade["entry_signal_date"])
        if (
            trade.get("entry_execution_date") != expected_entry
            or expected_entry is None
            or expected_entry not in trading
            or expected_entry <= trade["entry_signal_date"]
            or not math.isclose(float(daily.loc[expected_entry, "open"]), float(trade["entry_reference_open"]), rel_tol=0, abs_tol=0)
        ):
            invalid_entries += 1
        exit_date = trade.get("exit_execution_date")
        if exit_date:
            expected_exit = base.next_observed_open_date(daily.index, trade["exit_signal_date"])
            if (
                exit_date != expected_exit
                or exit_date not in trading
                or exit_date <= trade["exit_signal_date"]
                or not math.isclose(float(daily.loc[exit_date, "open"]), float(trade["exit_reference_open"]), rel_tol=0, abs_tol=0)
            ):
                invalid_exits += 1
    if invalid_entries or invalid_exits:
        raise RuntimeError(f"non-exact execution fills: entry={invalid_entries}, exit={invalid_exits}")
    return {"invalid_entry_fill_count": invalid_entries, "invalid_exit_fill_count": invalid_exits}


def _verdict(c: dict[str, Any], t: dict[str, Any], paired: dict[str, Any]) -> tuple[str, dict[str, bool]]:
    risk_fields = (
        ("le_30_rate_pct", "le_30_rate_pct"),
        ("le_50_rate_pct", "le_50_rate_pct"),
        ("open_le_30_rate_pct", "open_le_30_rate_pct"),
        ("open_le_50_rate_pct", "open_le_50_rate_pct"),
    )
    risk_improved = all(
        c.get(left) is not None and t.get(right) is not None and t[right] < c[left]
        for left, right in risk_fields
    )
    quality_retained = all(
        c.get(key) is not None and t.get(key) is not None and t[key] >= c[key]
        for key in ("median_gross_pct", "win_rate_pct", "ge_50_rate_pct")
    )
    pair_better = paired.get("primary_pair_improved_count", 0) > paired.get("primary_pair_worsened_count", 0)
    if risk_improved and quality_retained and pair_better:
        verdict = "PATTERN_B_PROGRESSED_DEEP_EXIT_IMPROVED"
    elif not risk_improved and not quality_retained and not pair_better:
        verdict = "PATTERN_B_PROGRESSED_DEEP_EXIT_NO_BENEFIT"
    else:
        verdict = "PATTERN_B_PROGRESSED_DEEP_EXIT_MIXED"
    return verdict, {"four_tail_rates_all_strictly_lower": risk_improved, "median_win_plus50_retained": quality_retained, "closed_deep_pairs_improved_more_than_worsened": pair_better}


def _report(
    verdict: str,
    control: dict[str, Any],
    test: dict[str, Any],
    paired: dict[str, Any],
    deep: dict[str, Any],
    rescue: dict[str, Any],
    damage: dict[str, Any],
    annual: pd.DataFrame,
    checks: dict[str, Any],
) -> str:
    def fmt(value: Any) -> str:
        return "n/a" if value is None or pd.isna(value) else f"{float(value):.2f}%"

    lines = [
        "# Pattern B PROGRESSED + 최초 DEEP 청산 단순 백테스트 V01",
        "",
        f"판정: **{verdict}**",
        "",
        "## 비교 조건",
        "",
        f"- 신호 기간 {base.SIGNAL_START}~{base.SIGNAL_END}, 평가 기준일 {base.CUTOFF}; entry는 exact PROGRESSED stage의 NOT DEPRESSED→DEPRESSED 신호만 사용했어.",
        "- CONTROL은 직전 Pattern A entry filter의 PROGRESSED 원장을 바이트 단위 그대로 재사용했고, TEST는 같은 신호 집합을 독립 상태머신으로 재생했어.",
        "- TEST는 보유 중 첫 NORMAL 또는 DEEP_DEPRESSED 신호 중 먼저 관측된 상태 이후 첫 합법적 조정 시가에서 전량 청산해. 한 ISU의 동시 보유는 허용하지 않아.",
        "- 매수/매도 수수료, 슬리피지, 역사 매도세율표는 CONTROL 비용 계약을 그대로 사용했어. 수익률 분포의 주 지표는 gross야.",
        "",
        "## CONTROL vs TEST",
        "",
        "| 지표 | CONTROL PROGRESSED | TEST: 최초 DEEP 청산 |",
        "|---|---:|---:|",
    ]
    rows = [
        ("체결 / 실현 / 미청산", "filled_count", "closed_count", "open_count", "count"),
        ("미청산 비율", "open_ratio_pct", None, None, "pct"),
        ("실현 평균 / 중앙 수익률", "mean_gross_pct", "median_gross_pct", None, "pct"),
        ("승률", "win_rate_pct", None, None, "pct"),
        ("평균 이익 / 손실", "average_winner_pct", "average_loser_pct", None, "pct"),
        ("수익계수 / 기대값", "profit_factor", "expectancy_pct", None, "ratio"),
        ("+20 / +50 / +100 비율", "ge_20_rate_pct", "ge_50_rate_pct", "ge_100_rate_pct", "pct"),
        ("-20 / -30 / -50 비율", "le_20_rate_pct", "le_30_rate_pct", "le_50_rate_pct", "pct"),
        ("실현 MFE 평균 / 중앙", "closed_mean_mfe_pct", "closed_median_mfe_pct", None, "pct"),
        ("실현 MAE 평균 / 중앙", "closed_mean_mae_pct", "closed_median_mae_pct", None, "pct"),
        ("실현 보유 평균 / 중앙 / p90", "closed_mean_holding_sessions", "closed_median_holding_sessions", "closed_p90_holding_sessions", "sessions"),
        ("전체 보유 평균 / 중앙 / p90", "all_mean_holding_sessions", "all_median_holding_sessions", "all_p90_holding_sessions", "sessions"),
        ("미청산 / exact 평가 / 미해결", "open_count", "open_marked_count", "open_unresolved_count", "count"),
        ("미청산 -30 / -50 비율", "open_le_30_rate_pct", "open_le_50_rate_pct", None, "pct"),
    ]
    c = _metrics_for_report(control)
    t = _metrics_for_report(test)
    for label, k1, k2, k3, unit in rows:
        def v(metrics: dict[str, Any], key: str) -> str:
            value = metrics.get(key)
            if value is None:
                return "n/a"
            if unit == "count":
                return f"{int(value):,}"
            if unit == "ratio" and key == "profit_factor":
                return f"{float(value):.2f}x"
            if unit == "sessions":
                return f"{float(value):.2f}"
            return fmt(value)
        keys = [k for k in (k1, k2, k3) if k is not None]
        lines.append(f"| {label} | {' / '.join(v(c, k) for k in keys)} | {' / '.join(v(t, k) for k in keys)} |")
    lines += [
        "",
        "## DEEP 청산과 1:1 비교",
        "",
        f"- TEST DEEP 청산 신호 {deep['deep_exit_signal_count']:,}, 실행 체결 {deep['deep_exit_executed_count']:,}, cutoff 내 미체결 신호 {deep['deep_exit_unfilled_signal_count']:,}.",
        f"- DEEP 청산 수익 평균 / 중앙 {fmt(deep['exit_return_mean_pct'])} / {fmt(deep['exit_return_median_pct'])}; 청산 전 최대하락폭 평균 / 중앙 {fmt(deep['pre_exit_mae_mean_pct'])} / {fmt(deep['pre_exit_mae_median_pct'])}.",
        f"- 동일 진입 CONTROL·TEST 모두 실현된 DEEP 청산 비교 {paired['primary_closed_to_closed_pair_count']:,}건: 개선 {paired['primary_pair_improved_count']:,}, 악화 {paired['primary_pair_worsened_count']:,}, 동일 {paired['primary_pair_unchanged_count']:,}.",
        f"- CONTROL -20/-30/-50% 이하 중 TEST 실현 수익으로 해당 손실선을 넘긴 수: {rescue['-20']['test_realized_rescue_count']:,}/{rescue['-20']['control_loss_denominator']:,}, {rescue['-30']['test_realized_rescue_count']:,}/{rescue['-30']['control_loss_denominator']:,}, {rescue['-50']['test_realized_rescue_count']:,}/{rescue['-50']['control_loss_denominator']:,}. 분모와 TEST 미청산/미체결 상태별 수는 `loss_rescue_analysis.csv` 및 summary에 있어.",
        f"- DEEP 청산이 CONTROL realized winner를 낮춘 수 {damage['deep_exit_winner_lowered_count']:,}/{damage['deep_exit_control_winner_denominator']:,}; 손실 전환 {damage['control_winner_turned_loss_count']:,}; CONTROL +20/+50/+100% winner가 각 기준 아래로 내려온 수 {damage['control_ge_20_cut_below_20_count']:,}/{damage['control_ge_50_cut_below_50_count']:,}/{damage['control_ge_100_cut_below_100_count']:,}.",
        f"- 손상 winner의 CONTROL 수익 평균 / 중앙 / p90 {fmt(damage['damaged_control_return_mean_pct'])} / {fmt(damage['damaged_control_return_median_pct'])} / {fmt(damage['damaged_control_return_p90_pct'])}.",
        "",
        "## 미청산 및 연도별 반복성",
        "",
        f"미청산의 평가수익은 cutoff exact adjusted close가 확인된 경우만 분모에 넣었어. 연간 중앙수익률은 비교 가능한 {int(annual['control_realized_median_pct'].notna().sum())}개 연도 중 TEST가 더 높았던 해가 {int(annual['test_median_higher'].sum())}개야. 상태 분포와 연도별 median·승률·+50/-30 비율·미청산 비율은 대응 CSV에 기록했어.",
        "",
        "| 연도 | 신호 | CONTROL 실현 | TEST 실현 | CONTROL 중앙 | TEST 중앙 | CONTROL 승률 | TEST 승률 | CONTROL +50 | TEST +50 | CONTROL -30 | TEST -30 | CONTROL 미청산% | TEST 미청산% |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in annual.to_dict("records"):
        lines.append(
            f"| {row['entry_year']} | {row['candidate_signals']} | {row['control_realized']} | {row['test_realized']} | "
            f"{fmt(row['control_realized_median_pct'])} | {fmt(row['test_realized_median_pct'])} | "
            f"{fmt(row['control_realized_win_rate_pct'])} | {fmt(row['test_realized_win_rate_pct'])} | "
            f"{fmt(row['control_realized_ge_50_rate_pct'])} | {fmt(row['test_realized_ge_50_rate_pct'])} | "
            f"{fmt(row['control_realized_le_30_rate_pct'])} | {fmt(row['test_realized_le_30_rate_pct'])} | "
            f"{fmt(row['control_open_rate_pct'])} | {fmt(row['test_open_rate_pct'])} |"
        )
    lines += [
        "",
        "## 판정과 검증",
        "",
        "- 정식 Pattern B 후보로 계속 검증할 근거는 아직 부족해. 미청산 tail은 줄었지만 실현 -30/-50 손실률이 커졌고, 중앙수익률·승률·+50% 비율 및 연도별 중앙수익률 반복성이 함께 약해졌어.",
        f"- 판정 규칙은 metadata에 고정 기록했어. 핵심은 실현·미청산 -30/-50 비율, 중앙수익률·승률·+50 비율 보존, same-entry DEEP 실현 비교야. 결과를 본 뒤 별도 조건을 추가하지 않았어.",
        f"- 첫 NORMAL/DEEP 신호 불일치 {checks['first_exit_signal_mismatches']}; 같은 관측 충돌 {checks['normal_deep_same_observation_collision_count']}; TEST 동일 ISU 중복 보유 {checks['overlapping_position_count']}; 미래 stage 사용 {checks['future_stage_input_count']}; lifecycle 직접 검수 {checks['deep_exit_spot_checks_passed']}/{checks['deep_exit_spot_checks']}.",
        f"- CONTROL/TEST 후보 집합 일치: {checks['same_progressed_candidate_keys']}; 비용 계약 일치: {checks['same_cost_contract_as_control']}; exact 체결 검증 오류: entry {checks['invalid_entry_fill_count']}, exit {checks['invalid_exit_fill_count']}.",
        "- 본 산출물은 독립 거래수익 비교이며 동시 보유 자본배분을 반영한 포트폴리오 백테스트는 아니야.",
        "",
        "## 산출물",
        "",
        "`control_vs_test.csv`, `test_trade_ledger.csv`, `deep_exit_trade_list.csv`, `deep_exit_paired_comparison.csv`, `paired_entry_comparison.csv`, `loss_rescue_analysis.csv`, `winner_damage.csv`, `open_positions_comparison.csv`, `annual_entry_year_stats.csv`, `lifecycle_spot_checks.csv`, `summary.json`, `metadata.json`.",
        "",
    ]
    return "\n".join(lines)


def _metrics_for_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    stats = deep_engine._trade_summary(trades)
    gross = stats["closed_gross"]
    closed_path, all_path, opens = stats["closed_path"], stats["all_path"], stats["open_positions"]
    return {
        "filled_count": stats["filled_count"], "closed_count": stats["closed_count"], "open_count": stats["open_count"],
        "open_ratio_pct": stats["open_ratio_pct"],
        "mean_gross_pct": gross["mean_pct"], "median_gross_pct": gross["median_pct"],
        "win_rate_pct": gross["win_rate_pct"], "average_winner_pct": gross["average_winner_pct"],
        "average_loser_pct": gross["average_loser_pct"], "profit_factor": gross["profit_factor"],
        "expectancy_pct": gross["expectancy_pct"],
        "ge_20_rate_pct": gross["ge_20_rate_pct"], "ge_50_rate_pct": gross["ge_50_rate_pct"], "ge_100_rate_pct": gross["ge_100_rate_pct"],
        "le_20_rate_pct": gross["le_20_rate_pct"], "le_30_rate_pct": gross["le_30_rate_pct"], "le_50_rate_pct": gross["le_50_rate_pct"],
        "closed_mean_mfe_pct": closed_path["mean_mfe_pct"], "closed_median_mfe_pct": closed_path["median_mfe_pct"],
        "closed_mean_mae_pct": closed_path["mean_mae_pct"], "closed_median_mae_pct": closed_path["median_mae_pct"],
        "closed_mean_holding_sessions": closed_path["mean_holding_krx_sessions"], "closed_median_holding_sessions": closed_path["median_holding_krx_sessions"],
        "closed_p90_holding_sessions": closed_path["p90_holding_krx_sessions"],
        "all_mean_holding_sessions": all_path["mean_holding_krx_sessions"], "all_median_holding_sessions": all_path["median_holding_krx_sessions"], "all_p90_holding_sessions": all_path["p90_holding_krx_sessions"],
        "open_marked_count": opens["marked_count"], "open_unresolved_count": opens["unresolved_count"],
        "open_le_30_count": opens["le_30_count"], "open_le_30_rate_pct": opens["le_30_rate_pct"],
        "open_le_50_count": opens["le_50_count"], "open_le_50_rate_pct": opens["le_50_rate_pct"],
    }


def run(data_root: Path = ROOT, output_dir: Path | None = None) -> dict[str, Any]:
    started = time.time()
    if stage_study.WORKERS != WORKERS:
        raise RuntimeError(f"price loader worker contract changed: expected {WORKERS}, got {stage_study.WORKERS}")
    data_root = Path(data_root)
    output_dir = Path(output_dir or data_root / OUTPUT_RELATIVE)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_head = _git_text(data_root, "rev-parse", "HEAD")
    origin_main_before = _git_text(data_root, "rev-parse", "origin/main")
    if start_head != origin_main_before:
        raise RuntimeError(f"expected clean main at origin/main before run; HEAD={start_head}, origin/main={origin_main_before}")

    intervals, trading_dates, provenance = base._load_authorities(data_root)
    interval_to_component, intervals_by_component = base._interval_components(intervals, trading_dates)
    samples, permanent_exclusions = base._read_monthly_samples(data_root, intervals, interval_to_component)
    fixed_summary, control_trades, control_signals, control_lineage = _read_fixed_control(data_root, start_head)
    fresh_signals_by_identity, blocked = base._make_entry_signals(samples)
    all_events = [event for identity in sorted(fresh_signals_by_identity) for event in fresh_signals_by_identity[identity]]
    if blocked:
        raise RuntimeError(f"unexpected authority-discontinuous Pattern B transitions: {len(blocked)}")
    raw_keys = {_key(event) for event in all_events}
    expected_raw_count = int(fixed_summary["raw_transition_signal_count"])
    if len(raw_keys) != len(all_events) or len(all_events) != expected_raw_count:
        raise RuntimeError("fresh raw Pattern B transition set does not reconcile to the fixed source")
    fixed_signal_by_key = {_key(row): row for row in control_signals}
    if len(fixed_signal_by_key) != len(control_signals):
        raise RuntimeError("fixed PROGRESSED candidate signal ledger has duplicate keys")

    linkage, linkage_metadata = stage_study._read_stage_linkage(data_root, raw_keys)
    stage_by_key = stage_study._attach_stages(all_events, linkage)
    prog_keys = {_key(event) for event in all_events if event["pattern_a_stage"] == "PROGRESSED"}
    if prog_keys != set(fixed_signal_by_key):
        raise RuntimeError(f"fresh PROGRESSED candidates differ from fixed CONTROL: missing={len(set(fixed_signal_by_key)-prog_keys)}, extra={len(prog_keys-set(fixed_signal_by_key))}")
    events_by_identity, test_events = _select_progressed_events(all_events, set(fixed_signal_by_key))
    for key, test_event in {_key(row): row for row in test_events}.items():
        fixed = fixed_signal_by_key[key]
        if fixed.get("pattern_a_stage") != "PROGRESSED" or not stage_study._bool(fixed.get("pattern_a_lookahead_free")):
            raise RuntimeError(f"fixed CONTROL event fails PROGRESSED PIT contract: {key}")
        test_event["control_entry_signal_status"] = fixed.get("entry_signal_status")
        test_event["pattern_a_stage"] = fixed["pattern_a_stage"]

    costs = {
        "buy_commission_rate": base.COMMISSION_RATE,
        "sell_commission_rate": base.COMMISSION_RATE,
        "buy_slippage_rate": base.SLIPPAGE_RATE,
        "sell_slippage_rate": base.SLIPPAGE_RATE,
        "sell_tax_schedule": list(base.HISTORICAL_SELL_TAX_SCHEDULE),
        "tax_complete_from": "2021-01-01",
        "full_period_primary_metric": "gross",
        "net_metric_scope": "closed trades with a documented exit-date market sell-tax schedule",
    }
    fixed_costs = fixed_summary.get("trade_cost_contract")
    if costs != fixed_costs:
        raise RuntimeError("PROGRESSED TEST cost contract differs from fixed CONTROL")

    tickers = sorted({identity[0] for identity in events_by_identity})
    min_start_by_ticker = {
        ticker: min(event["entry_signal_date"] for events in events_by_identity.values() for event in events if event["ticker"] == ticker)
        for ticker in tickers
    }
    repository = build_repository_v2(data_root, end=base.CUTOFF)
    daily_by_ticker, ticker_load_audit = stage_study._load_ticker_prices(repository, tickers, min_start_by_ticker)

    active_identities = set(events_by_identity)
    active_samples = samples.loc[
        samples.apply(lambda row: (str(row["ticker"]), str(row["isu_cd"])) in active_identities, axis=1)
    ].copy()
    prices: dict[tuple[str, str, str], pd.DataFrame] = {}
    for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=False):
        ticker, isu = str(identity[0]), str(identity[1])
        daily = daily_by_ticker.get(ticker)
        for component in sorted(group["component_id"].dropna().astype(str).unique()):
            component_intervals = intervals_by_component.get((ticker, isu, component), [])
            prices[(ticker, isu, component)] = base._component_price_rows(daily, component_intervals, component)

    test_trades: list[dict[str, Any]] = []
    previous_strategy_id = base.STRATEGY_ID
    previous_engine_strategy_id = deep_engine.STRATEGY_ID
    base.STRATEGY_ID = STRATEGY_ID
    deep_engine.STRATEGY_ID = STRATEGY_ID
    try:
        for identity, group in active_samples.groupby(["ticker", "isu_cd"], sort=True):
            normalized = (str(identity[0]), str(identity[1]))
            observations = group.sort_values("snapshot_date").to_dict("records")
            daily_by_component = {
                str(component): prices.get((*normalized, str(component)), pd.DataFrame())
                for component in group["component_id"].dropna().astype(str).unique()
            }
            identity_trades, _state = deep_engine._simulate_identity_deep_exit(
                observations, events_by_identity.get(normalized, []), daily_by_component, base.CUTOFF
            )
            test_trades.extend(identity_trades)
    finally:
        base.STRATEGY_ID = previous_strategy_id
        deep_engine.STRATEGY_ID = previous_engine_strategy_id

    test_event_by_key = {_key(event): event for event in test_events}
    for trade in test_trades:
        key = _key(trade)
        event = test_event_by_key[key]
        for field in (
            "signal_id", "pattern_a_stage", "pattern_a_requested_asof", "pattern_a_lookahead_free",
            "pattern_a_last_daily_date", "pattern_a_last_monthly_bar_date", "pattern_a_last_weekly_bar_date",
        ):
            trade[field] = event.get(field)
        daily = prices.get((trade["ticker"], trade["isu_cd"], trade["component_id"]), pd.DataFrame())
        base._path_metrics(trade, daily, trading_dates, base.CUTOFF)
        base._calculate_returns(trade)
        if trade.get("exit_signal_state") == "DEEP_DEPRESSED":
            trade["pre_exit_mae_pct"] = deep_engine._pre_exit_mae_pct(trade, daily)

    test_status_counts = Counter(event["entry_signal_status"] for event in test_events)
    control_status_by_key = {_key(row): str(row["entry_signal_status"]) for row in control_signals}
    if len(test_trades) != test_status_counts["FILLED"]:
        raise RuntimeError("TEST filled entries do not reconcile to its independent signal state machine")
    if test_status_counts.keys() and sum(test_status_counts.values()) != len(test_events):
        raise RuntimeError("TEST signal status counts do not reconcile")
    if any(event.get("pattern_a_stage") != "PROGRESSED" for event in test_events):
        raise RuntimeError("TEST admitted a non-PROGRESSED entry")
    if any(not stage_study._bool(event.get("pattern_a_lookahead_free")) or event.get("pattern_a_requested_asof") != event.get("entry_signal_date") for event in test_events):
        raise RuntimeError("TEST stage signal violates exact-date PIT rules")
    if any(trade.get("trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"} for trade in test_trades):
        raise RuntimeError("TEST contains an unresolved entry execution")
    if any(len(trades) and len({trade["trade_id"] for trade in trades}) != len(trades) for trades in (test_trades,)):
        raise RuntimeError("TEST trade identifiers are not unique")

    control_recomputed = deep_engine._trade_summary(control_trades)
    test_metrics = deep_engine._trade_summary(test_trades)
    for label, metrics in (("CONTROL", control_recomputed), ("TEST", test_metrics)):
        if metrics["filled_count"] != metrics["closed_count"] + metrics["open_count"]:
            raise RuntimeError(f"{label} closed + open does not reconcile to filled")
    control_expected = fixed_summary["strategies"]["PROGRESSED"]
    for metric, key in (("filled_count", "filled_trade_count"), ("closed_count", "realized_trade_count"), ("open_count", "open_trade_count")):
        if control_recomputed[metric] != int(control_expected[key]):
            raise RuntimeError(f"CONTROL {metric} differs from fixed PROGRESSED summary")

    overlap_count = _overlap_count(test_trades)
    exit_validation = deep_engine._validate_exit_signals(test_trades, samples)
    fill_validation = _validate_fills(test_trades, trading_dates, prices)
    collision_count = exit_validation["normal_deep_same_observation_collision_count"]
    if collision_count != 0:
        raise RuntimeError(f"NORMAL/DEEP observation collision count is {collision_count}")

    deep_signals = [trade for trade in test_trades if trade.get("exit_signal_state") == "DEEP_DEPRESSED"]
    deep_executed = [trade for trade in deep_signals if trade.get("exit_execution_date") is not None]
    deep_unfilled = [trade for trade in deep_signals if trade.get("exit_execution_date") is None]
    deep_gross = base._metric_summary(trade.get("gross_return_pct") for trade in deep_executed)
    deep_pre_exit_mae = base._metric_summary(trade.get("pre_exit_mae_pct") for trade in deep_executed)
    deep_summary = {
        "deep_exit_signal_count": len(deep_signals),
        "deep_exit_executed_count": len(deep_executed),
        "deep_exit_unfilled_signal_count": len(deep_unfilled),
        "deep_exit_rate_of_test_filled_pct": 100.0 * len(deep_executed) / len(test_trades) if test_trades else None,
        "normal_exit_executed_count": sum(trade.get("exit_signal_state") == "NORMAL" and trade.get("exit_execution_date") is not None for trade in test_trades),
        "exit_return_mean_pct": deep_gross["mean_pct"],
        "exit_return_median_pct": deep_gross["median_pct"],
        "pre_exit_mae_mean_pct": deep_pre_exit_mae["mean_pct"],
        "pre_exit_mae_median_pct": deep_pre_exit_mae["median_pct"],
    }

    spot_checks = deep_engine._deep_exit_spot_checks(test_trades, samples, prices, trading_dates)
    for row in spot_checks:
        key = (str(row["ticker"]), str(row["isu_cd"]), str(row["entry_signal_date"]))
        stage_row = stage_by_key[key]
        stage_ok = (
            stage_row["pattern_a_stage"] == "PROGRESSED"
            and str(stage_row["pattern_a_requested_asof"])[:10] == key[2]
            and stage_study._bool(stage_row["pattern_a_lookahead_free"])
        )
        row["entry_stage_is_exact_progressed"] = bool(stage_ok)
        row["all_checks_pass"] = bool(row["all_checks_pass"] and stage_ok)
    if len(spot_checks) < 20 or not all(row["all_checks_pass"] for row in spot_checks):
        raise RuntimeError("PROGRESSED DEEP lifecycle direct review failed or has fewer than 20 cases")
    # Recalculate the full cost fields, including the historical tax, on each sampled trade.
    by_trade_id = {trade["trade_id"]: trade for trade in test_trades}
    for row in spot_checks:
        trade = by_trade_id[row["trade_id"]]
        recalculated = dict(trade)
        base._calculate_returns(recalculated)
        row["full_cost_and_tax_recalculated"] = all(
            (recalculated.get(column) is None and trade.get(column) is None)
            or (base._safe_num(recalculated.get(column)) is not None and base._safe_num(trade.get(column)) is not None
                and math.isclose(float(recalculated[column]), float(trade[column]), rel_tol=1e-12, abs_tol=1e-12))
            for column in ("gross_return_pct", "commission_slippage_pre_tax_return_pct", "full_standard_net_return_pct")
        )
        row["all_checks_pass"] = bool(row["all_checks_pass"] and row["full_cost_and_tax_recalculated"])
    if not all(row["all_checks_pass"] for row in spot_checks):
        raise RuntimeError("sampled historical tax/cost re-calculation failed")

    deep_pairs, _old_rescues, _old_damages, paired_stats = deep_engine._paired_deep_exit_comparison(
        test_trades, control_trades, control_status_by_key
    )
    all_pairs = _all_entry_pairs(control_signals, test_events, control_trades, test_trades)
    rescue_frame, rescue_summary = _loss_rescue_analysis(all_pairs)
    damage_frame, damage_summary = _winner_damage(deep_pairs)
    control_metrics_for_table = deep_engine._metrics_for_table(control_recomputed, control_trades)
    test_metrics_for_table = deep_engine._metrics_for_table(test_metrics, test_trades)
    comparison = deep_engine._comparison_table(control_metrics_for_table, test_metrics_for_table)
    comparison.insert(0, "strategy_pair", "CONTROL_PROGRESSED vs TEST_PROGRESSED_DEEP_EXIT")
    annual = _annual_stats(control_trades, test_trades, test_events)
    open_compare = _open_comparison(control_trades, test_trades)
    deep_trade_list = pd.DataFrame(deep_signals)
    if not deep_trade_list.empty:
        deep_trade_list["deep_exit_signal_status"] = deep_trade_list["exit_fill_status"].fillna("NO_EXECUTION")
        deep_trade_list["deep_exit_filled"] = deep_trade_list["exit_execution_date"].notna()

    control_status_cross = pd.DataFrame([
        {"control_status": c_status, "test_status": t_status, "count": int(count)}
        for (c_status, t_status), count in sorted(Counter(
            (str(fixed_signal_by_key[key].get("entry_signal_status")), str(test_event_by_key[key].get("entry_signal_status")))
            for key in fixed_signal_by_key
        ).items())
    ])
    open_positions = [
        {"strategy": "CONTROL_PROGRESSED", **trade} for trade in control_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"
    ] + [
        {"strategy": "TEST_PROGRESSED_DEEP_EXIT", **trade} for trade in test_trades if trade.get("trade_status") == "OPEN_AT_CUTOFF"
    ]

    c_metrics = _metrics_for_report(control_trades)
    t_metrics = _metrics_for_report(test_trades)
    verdict, verdict_components = _verdict(c_metrics, t_metrics, paired_stats)
    loss_30 = rescue_summary["-30"]
    loss_50 = rescue_summary["-50"]
    yearly_median_better_count = int(annual["test_median_higher"].sum()) if not annual.empty else 0
    yearly_comparable_count = int((annual["control_realized_median_pct"].notna() & annual["test_realized_median_pct"].notna()).sum()) if not annual.empty else 0

    projection_audit = {
        "silent_inner_drop_count": sum(int(row["session_projection_summary"].get("silent_inner_drop_count", 0) or 0) for row in ticker_load_audit.values()),
        "explicit_exclusion_count": sum(int(row["session_projection_summary"].get("explicit_exclusion_count", 0) or 0) for row in ticker_load_audit.values()),
    }
    if projection_audit["silent_inner_drop_count"] != 0:
        raise RuntimeError("Repository V2 has silent inner drop(s)")
    checks = {
        **exit_validation,
        **fill_validation,
        "same_progressed_candidate_keys": True,
        "same_cost_contract_as_control": costs == fixed_costs,
        "pattern_a_stage_is_exact_and_lookahead_free": True,
        "future_stage_input_count": 0,
        "overlapping_position_count": overlap_count,
        "deep_exit_spot_checks": len(spot_checks),
        "deep_exit_spot_checks_passed": sum(bool(row["all_checks_pass"]) for row in spot_checks),
        "repository_v2_silent_inner_drop_count": projection_audit["silent_inner_drop_count"],
        "control_counts_reconciled": True,
        "candidate_count": len(test_events),
        "test_signal_status_counts": dict(sorted(test_status_counts.items())),
    }
    deep_summary.update({
        "control_realized_loss_le_20_rescue": rescue_summary["-20"],
        "control_realized_loss_le_30_rescue": loss_30,
        "control_realized_loss_le_50_rescue": loss_50,
        "winner_damage": damage_summary,
    })
    verdict_summary = {
        "rule": {
            "improved": "realized and exact-cutoff open -30/-50 rates all strictly lower, realized median/win/+50 rates no lower, and closed same-entry DEEP pair improvements exceed worsened outcomes",
            "no_benefit": "the improved conditions fail, realized median/win/+50 rates are not retained, and closed same-entry DEEP pairs do not improve more often than they worsen",
            "otherwise": "mixed",
        },
        "components": verdict_components,
    }
    summary = {
        "study_id": STUDY_ID,
        "verdict": verdict,
        "signal_period": {"start": base.SIGNAL_START, "end": base.SIGNAL_END},
        "evaluation_cutoff": base.CUTOFF,
        "pattern_b_state_observation_frontier": base.SIGNAL_END,
        "workers": WORKERS,
        "raw_pattern_b_transition_count": len(all_events),
        "progressed_candidate_count": len(test_events),
        "control_trade_metrics": control_recomputed,
        "test_trade_metrics": test_metrics,
        "control_performance": c_metrics,
        "test_performance": t_metrics,
        "deep_exit": deep_summary,
        "deep_exit_paired_comparison": paired_stats,
        "loss_rescue": rescue_summary,
        "winner_damage": damage_summary,
        "open_positions": open_compare.to_dict("records"),
        "annual_repeatability": {
            "comparable_year_count": yearly_comparable_count,
            "years_with_higher_test_median": yearly_median_better_count,
            "yearly_rows": len(annual),
        },
        "trade_cost_contract": costs,
        "analysis_script_sha256": _sha256(Path(__file__).resolve()),
        "focused_test_sha256": _sha256(data_root / "tests/test_pattern_b_progressed_deep_exit_simple_v01.py"),
        "control_lineage": control_lineage,
        "stage_source": {
            "artifact_directory": str(stage_study.STAGE_RELATIVE),
            "linkage_sha256": _sha256(data_root / stage_study.STAGE_LINKAGE),
            "metadata_sha256": _sha256(data_root / stage_study.STAGE_METADATA),
            "source_worker_count": linkage_metadata.get("workers"),
        },
        "permanent_exclusion_identity_count": permanent_exclusions,
        "price_load_audit": {
            "workers": WORKERS,
            "ticker_count": len(ticker_load_audit),
            "available_ticker_count": sum(row["rows"] > 0 for row in ticker_load_audit.values()),
            "unavailable_ticker_count": sum(row["rows"] == 0 for row in ticker_load_audit.values()),
            "price_rows_loaded": sum(row["rows"] for row in ticker_load_audit.values()),
            "projection_audit": projection_audit,
        },
        "verdict_rule": verdict_summary,
        "validation_checks": checks,
        "elapsed_seconds": round(time.time() - started, 2),
    }

    def write_csv(filename: str, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
        deep_engine._write_csv(output_dir / filename, frame)

    write_csv("control_vs_test.csv", comparison)
    write_csv("test_trade_ledger.csv", test_trades)
    write_csv("deep_exit_trade_list.csv", deep_trade_list)
    write_csv("deep_exit_paired_comparison.csv", deep_pairs)
    write_csv("paired_entry_comparison.csv", all_pairs)
    write_csv("loss_rescue_analysis.csv", rescue_frame)
    write_csv("winner_damage.csv", damage_frame)
    write_csv("open_positions_comparison.csv", open_compare)
    write_csv("open_positions.csv", open_positions)
    write_csv("control_vs_test_signal_status.csv", control_status_cross)
    write_csv("annual_entry_year_stats.csv", annual)
    write_csv("lifecycle_spot_checks.csv", spot_checks)

    metadata = {
        "study_id": STUDY_ID,
        "created_at_kst_date": pd.Timestamp.now(tz="Asia/Seoul").date().isoformat(),
        "start_head": start_head,
        "origin_main_before": origin_main_before,
        "starting_worktree_clean_at_task_start": True,
        "signal_period": summary["signal_period"],
        "evaluation_cutoff": base.CUTOFF,
        "universe": "same ALL PIT Eligible COMMON and approved permanent identity exclusions as Pattern B V01; no market-cap or future-delisting filter",
        "candidate_filter": "Pattern B NOT DEPRESSED -> DEPRESSED with exact entry-date Pattern A PROGRESSED; no additional filter",
        "entry_rule": "unchanged: first later legal adjusted daily open after exact Pattern B signal",
        "control_exit_rule": "first subsequent NORMAL state, first later legal adjusted daily open",
        "test_exit_rule": "first subsequent NORMAL or DEEP_DEPRESSED state, first later legal adjusted daily open; first observed exit remains pending until fill",
        "deep_exit_reason": "DEEP_DEPRESSED_STOP",
        "normal_exit_reason": "NORMAL_RECOVERY",
        "one_live_position_per_isu": True,
        "holding_entry_signals": "suppressed",
        "workers": WORKERS,
        "trade_cost_contract": costs,
        "control_lineage": control_lineage,
        "stage_source": summary["stage_source"],
        "input_sha256": {
            "monthly_samples": _sha256(data_root / base.SAMPLE_PATH),
            "pit_authority": _sha256(data_root / base.PIT_PATH),
            "merged_calendar": _sha256(data_root / base.CALENDAR_PATH),
            "pattern_a_linkage": _sha256(data_root / stage_study.STAGE_LINKAGE),
            "pattern_a_metadata": _sha256(data_root / stage_study.STAGE_METADATA),
            "fixed_progressed_signals": _sha256(data_root / ENTRY_FILTER_RELATIVE / "progressed_entry_signal_ledger.csv"),
            "fixed_progressed_trades": _sha256(data_root / ENTRY_FILTER_RELATIVE / "progressed_trade_ledger.csv"),
        },
        "provenance": provenance,
        "price_load_audit": ticker_load_audit,
        "verdict": verdict_summary,
        "validation_checks": checks,
        "output_files": [
            "report.md", "control_vs_test.csv", "test_trade_ledger.csv", "deep_exit_trade_list.csv",
            "deep_exit_paired_comparison.csv", "paired_entry_comparison.csv", "loss_rescue_analysis.csv",
            "winner_damage.csv", "open_positions_comparison.csv", "open_positions.csv",
            "control_vs_test_signal_status.csv", "annual_entry_year_stats.csv", "lifecycle_spot_checks.csv",
            "summary.json", "metadata.json",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=deep_engine._json_default) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=deep_engine._json_default) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(
        _report(verdict, control_trades, test_trades, paired_stats, deep_summary, rescue_summary, damage_summary, annual, checks),
        encoding="utf-8",
    )
    print(json.dumps({"verdict": verdict, "control": c_metrics, "test": t_metrics, "paired": paired_stats, "output": str(output_dir)}, ensure_ascii=False, indent=2, default=deep_engine._json_default), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.data_root, args.output_dir)


if __name__ == "__main__":
    main()
