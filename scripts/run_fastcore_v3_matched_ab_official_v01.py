#!/usr/bin/env python3
"""Run the official local-only FastCore V2/V3 matched-entry A/B replay."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_fastcore_v3_exit_ab_v00 as diagnostic
from scripts import run_fastcore_v3_simple_v00 as v3


CONTROL_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"
PLAN_PATH = ROOT / "docs/patterns/pattern_a_fast/validation_plan/version_03_matched_ab_validation.md"
V3_README_PATH = ROOT / "docs/patterns/pattern_a_fast/strategy/version_03/README.md"

OUT_DIR = ROOT / "artifacts/backtests/fastcore_v3_matched_ab_official_v01"
MATCHED_PATH = OUT_DIR / "matched_trades.csv"
SUMMARY_PATH = OUT_DIR / "summary.json"
ROBUSTNESS_PATH = OUT_DIR / "robustness.csv"
EXIT_REASON_PATH = OUT_DIR / "exit_reason_diagnostics.csv"
REPRESENTATIVE_PATH = OUT_DIR / "representative_cases.csv"
REPORT_PATH = OUT_DIR / "report.md"

EXPECTED_TRADES = 973
EXPECTED_UNIQUE_TICKERS = 542
EXPECTED_PERIOD = ("2021-04-01", "2026-08-14", "2026-08-21")
EXPECTED_FINAL_VALUATION = "2026-08-21 CLOSE"


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _normalise_control(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str, "trade_id": str})
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    frame["isu_cd"] = frame["isu_cd"].astype(str).str.strip()
    frame["trade_id"] = frame["trade_id"].astype(str).str.strip()
    return frame


def validate_control_input(control: pd.DataFrame, control_summary: Mapping[str, Any]) -> None:
    if len(control) != EXPECTED_TRADES:
        raise AssertionError(f"expected {EXPECTED_TRADES} CONTROL rows, got {len(control)}")
    if int(control["ticker"].nunique()) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError(f"expected {EXPECTED_UNIQUE_TICKERS} CONTROL tickers, got {control['ticker'].nunique()}")
    if int(control_summary.get("total_trades", -1)) != EXPECTED_TRADES:
        raise AssertionError("CONTROL summary total_trades does not match frozen value")
    if int(control_summary.get("unique_tickers", -1)) != EXPECTED_UNIQUE_TICKERS:
        raise AssertionError("CONTROL summary unique_tickers does not match frozen value")
    period = (
        str(control_summary.get("common_start_date")),
        str(control_summary.get("signal_end_date")),
        str(control_summary.get("execution_support_end_date")),
    )
    if period != EXPECTED_PERIOD:
        raise AssertionError(f"CONTROL period does not match frozen value: {period}")
    signal_dates = pd.to_datetime(control["entry_signal_date"], errors="raise")
    execution_dates = pd.to_datetime(control["entry_execution_date"], errors="raise")
    if bool((signal_dates < pd.Timestamp(EXPECTED_PERIOD[0])).any()) or bool((signal_dates > pd.Timestamp(EXPECTED_PERIOD[1])).any()):
        raise AssertionError("CONTROL signal dates fall outside the frozen period")
    if bool((execution_dates < pd.Timestamp(EXPECTED_PERIOD[0])).any()) or bool((execution_dates > pd.Timestamp(EXPECTED_PERIOD[2])).any()):
        raise AssertionError("CONTROL execution dates fall outside the frozen support period")
    if int(control["trade_id"].duplicated().sum()) != 0:
        raise AssertionError("duplicated CONTROL trade identity")


def _full_path_raw_mfe(row: Mapping[str, Any], daily_full: pd.DataFrame) -> float:
    lifecycle = diagnostic._lifecycle(row)
    daily = diagnostic.clip_to_identity_lifecycle(daily_full, lifecycle)
    if daily is None or daily.empty:
        raise RuntimeError(f"missing identity-scoped daily data for {row['trade_id']}")
    entry_date = pd.Timestamp(row["entry_execution_date"]).normalize()
    path = daily.loc[daily.index >= entry_date]
    if path.empty:
        raise RuntimeError(f"missing post-entry daily data for {row['trade_id']}")
    highs = pd.to_numeric(path["high"], errors="coerce").dropna()
    if highs.empty:
        raise RuntimeError(f"missing post-entry HIGH data for {row['trade_id']}")
    entry_open = float(row["entry_open"])
    return (float(highs.max()) / entry_open - 1.0) * 100.0


def classify_full_path_mfe(value: float) -> str:
    return "PRE_WINNER_LT_20" if float(value) < 20.0 else "WINNER_CAPABLE_GE_20"


def _v2_exit_category(row: Mapping[str, Any]) -> str:
    if str(row.get("trade_status", "")) == "OPEN_AT_CUTOFF":
        return "OPEN_AT_CUTOFF"
    exit_type = str(row.get("exit_type", ""))
    if exit_type.startswith("LOSS_GUARD"):
        return "LOSS_GUARD"
    if exit_type.startswith("EXIT3"):
        return "EXIT3"
    if exit_type.startswith("EXIT4"):
        return "EXIT4"
    if exit_type.startswith("NO_"):
        return "OPEN_AT_CUTOFF"
    return exit_type


def replay_one(row: Mapping[str, Any], daily_by_ticker: Mapping[str, pd.DataFrame], states: Mapping[str, list[tuple[pd.Timestamp, str]]]) -> dict[str, Any]:
    ticker = str(row["ticker"]).zfill(6)
    daily_full = daily_by_ticker[ticker]
    replay = diagnostic.replay_v0_entry(row, daily_full, states.get(diagnostic._identity_key(row), []))
    full_path_mfe = _full_path_raw_mfe(row, daily_full)
    v3_terminal_return = float(replay["v0_terminal_return"])
    v3_mfe = float(replay["v0_mfe"])
    v3_mae = float(replay["v0_mae"])
    v2_terminal_return = float(row["terminal_return"])
    v2_mfe = float(row["mfe"])
    v2_mae = float(row["mae"])
    return {
        "ticker": ticker,
        "name": str(row["name"]),
        "market": str(row["market"]),
        "isu_cd": str(row["isu_cd"]),
        "control_trade_id": str(row["trade_id"]),
        "control_trade_sequence": int(row["trade_sequence"]),
        "entry_signal_date": str(row["entry_signal_date"]),
        "entry_signal_information_date": str(row["entry_signal_information_date"]),
        "entry_execution_date": str(row["entry_execution_date"]),
        "entry_open": float(row["entry_open"]),
        "identity_effective_from": str(row["identity_effective_from"]),
        "identity_effective_to": str(row["identity_effective_to"]),
        "v2_exit_reason": str(row["exit_type"]),
        "v2_exit_category": _v2_exit_category(row),
        "v2_exit_signal_date": row["exit_signal_date"] if pd.notna(row["exit_signal_date"]) else None,
        "v2_exit_execution_date": row["exit_execution_date"] if pd.notna(row["exit_execution_date"]) else None,
        "v2_exit_price": float(row["exit_price"]) if pd.notna(row["exit_price"]) else None,
        "v2_terminal_return": v2_terminal_return,
        "v2_mfe": v2_mfe,
        "v2_mae": v2_mae,
        "v2_holding_days": int(row["holding_trading_days"]),
        "v2_trade_status": str(row["trade_status"]),
        "v2_loss_guard_triggered": bool(row["loss_guard_triggered"]),
        "v2_giveback": round(v2_mfe - v2_terminal_return, 6),
        "v3_entry_signal_date": str(row["entry_signal_date"]),
        "v3_entry_execution_date": replay["v0_entry_execution_date"],
        "v3_entry_open": float(replay["v0_entry_open"]),
        "v3_exit_reason": replay["v0_exit_reason"],
        "v3_exit_signal_date": replay["v0_exit_signal_date"],
        "v3_exit_execution_date": replay["v0_exit_execution_date"],
        "v3_exit_price": replay["v0_exit_price"],
        "v3_terminal_return": v3_terminal_return,
        "v3_strategy_path_mfe": v3_mfe,
        "v3_strategy_path_mae": v3_mae,
        "v3_holding_days": int(replay["v0_holding_days"]),
        "v3_trade_status": replay["v0_trade_status"],
        "v3_fast_state_at_exit": replay["v0_fast_state_at_exit"],
        "v3_soft_threshold": replay["v0_soft_threshold"],
        "v3_hard_threshold": replay["v0_hard_threshold"],
        "v3_exit_mfe_tier": replay["v0_mfe_tier"],
        "v3_giveback": round(v3_mfe - v3_terminal_return, 6),
        "full_path_raw_mfe": round(full_path_mfe, 6),
        "full_path_mfe_cohort": classify_full_path_mfe(full_path_mfe),
        "entry_signal_date_match": str(row["entry_signal_date"]) == str(row["entry_signal_date"]),
        "entry_execution_date_match": replay["v0_entry_execution_date"] == str(row["entry_execution_date"]),
        "entry_open_match": abs(float(replay["v0_entry_open"]) - float(row["entry_open"])) <= 1e-8,
        "return_delta_v3_minus_v2": round(v3_terminal_return - v2_terminal_return, 6),
        "improved_worsened_same": "improved" if v3_terminal_return > v2_terminal_return else "worsened" if v3_terminal_return < v2_terminal_return else "same",
    }


def validate_matched_integrity(matched: pd.DataFrame) -> dict[str, Any]:
    if len(matched) != EXPECTED_TRADES:
        raise AssertionError(f"matched rows != {EXPECTED_TRADES}: {len(matched)}")
    if int(matched["control_trade_id"].duplicated().sum()) != 0:
        raise AssertionError("duplicated matched CONTROL trade identity")
    date_matches = int(matched["entry_execution_date_match"].sum())
    open_matches = int(matched["entry_open_match"].sum())
    signal_matches = int(matched["entry_signal_date_match"].sum())
    if date_matches != EXPECTED_TRADES or open_matches != EXPECTED_TRADES or signal_matches != EXPECTED_TRADES:
        raise AssertionError("matched entry date or entry open mismatch")
    return {
        "matched_rows": len(matched),
        "unique_tickers": int(matched["ticker"].nunique()),
        "entry_signal_date_match_count": signal_matches,
        "entry_execution_date_match_count": date_matches,
        "entry_open_match_count": open_matches,
        "missing_entries": 0,
        "duplicated_control_trade_identity": int(matched["control_trade_id"].duplicated().sum()),
        "arbitrary_excluded_entries": EXPECTED_TRADES - len(matched),
        "pass": True,
    }


def _mean_median(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _side_stats(frame: pd.DataFrame, side: str) -> dict[str, Any]:
    return_col = f"{side}_terminal_return"
    mfe_col = "v2_mfe" if side == "v2" else "v3_strategy_path_mfe"
    mae_col = "v2_mae" if side == "v2" else "v3_strategy_path_mae"
    holding_col = f"{side}_holding_days"
    status_col = f"{side}_trade_status"
    giveback_col = f"{side}_giveback"
    returns = pd.to_numeric(frame[return_col], errors="coerce")
    mean_return, median_return = _mean_median(frame, return_col)
    mean_mfe, median_mfe = _mean_median(frame, mfe_col)
    mean_mae, median_mae = _mean_median(frame, mae_col)
    mean_holding, median_holding = _mean_median(frame, holding_col)
    mean_giveback, median_giveback = _mean_median(frame, giveback_col)
    total = len(frame)
    open_count = int((frame[status_col] == "OPEN_AT_CUTOFF").sum())
    output: dict[str, Any] = {
        "trades": total,
        "positive_count": int((returns > 0).sum()),
        "positive_rate_pct": round(float((returns > 0).mean() * 100.0), 6) if total else None,
        "mean_terminal_return_pct": mean_return,
        "median_terminal_return_pct": median_return,
        "mean_mfe_pct": mean_mfe,
        "median_mfe_pct": median_mfe,
        "mean_mae_pct": mean_mae,
        "median_mae_pct": median_mae,
        "mean_holding_days": mean_holding,
        "median_holding_days": median_holding,
        "p90_holding_days": round(float(pd.to_numeric(frame[holding_col], errors="coerce").quantile(0.9)), 6) if total else None,
        "open_at_cutoff_count": open_count,
        "open_at_cutoff_rate_pct": round(open_count / total * 100.0, 6) if total else None,
        "mean_giveback": mean_giveback,
        "median_giveback": median_giveback,
    }
    for threshold in (15, 20, 30, 40, 50, 60):
        count = int((returns <= -threshold).sum())
        output[f"tail_le_{threshold}_count"] = count
        output[f"tail_le_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else None
    for threshold in (20, 30, 50, 100, 200, 400):
        count = int((returns >= threshold).sum())
        output[f"winner_ge_{threshold}_count"] = count
        output[f"winner_ge_{threshold}_rate_pct"] = round(count / total * 100.0, 6) if total else None
    return output


def build_robustness(matched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(dimension: str, group: str, frame: pd.DataFrame) -> None:
        mean_delta, median_delta = _mean_median(frame, "return_delta_v3_minus_v2")
        rows.append({
            "dimension": dimension,
            "group": group,
            "trade_count": len(frame),
            "mean_paired_return_delta": mean_delta,
            "median_paired_return_delta": median_delta,
        })

    for group in ("KOSPI", "KOSDAQ"):
        add("market", group, matched[matched["market"] == group])
    add("entry_type", "FIRST_ENTRY", matched[matched["control_trade_sequence"] == 1])
    add("entry_type", "REENTRY", matched[matched["control_trade_sequence"] > 1])
    years = pd.to_datetime(matched["entry_execution_date"], errors="raise").dt.year
    for year in sorted(years.unique()):
        add("entry_year", str(int(year)), matched[years == year])
    return pd.DataFrame(rows)


def _robustness_mean(robustness: pd.DataFrame, dimension: str, group: str) -> float | None:
    rows = robustness[(robustness["dimension"] == dimension) & (robustness["group"] == group)]
    if rows.empty or pd.isna(rows.iloc[0]["mean_paired_return_delta"]):
        return None
    return float(rows.iloc[0]["mean_paired_return_delta"])


def evaluate_preregistered_criteria(
    v2: Mapping[str, Any],
    v3_stats: Mapping[str, Any],
    paired: Mapping[str, Any],
    robustness: pd.DataFrame,
    integrity_pass: bool,
) -> dict[str, Any]:
    path_a = bool(paired["mean_delta"] > 0 and paired["median_delta"] >= 0)
    path_b = bool(v3_stats["winner_ge_50_count"] > v2["winner_ge_50_count"] and v3_stats["winner_ge_100_count"] >= v2["winner_ge_100_count"])
    path_c = bool(v3_stats["median_giveback"] < v2["median_giveback"] and v3_stats["mean_giveback"] <= v2["mean_giveback"])
    performance_pass = bool(path_a or path_b or path_c)
    large_loss_worsened = bool(v3_stats["tail_le_30_rate_pct"] > v2["tail_le_30_rate_pct"] and v3_stats["tail_le_40_rate_pct"] > v2["tail_le_40_rate_pct"])
    capital_lock_worsened = bool(v3_stats["median_holding_days"] > v2["median_holding_days"] and v3_stats["open_at_cutoff_rate_pct"] > v2["open_at_cutoff_rate_pct"])
    official_risk_block = bool(large_loss_worsened and capital_lock_worsened)
    market_pass = bool(
        _robustness_mean(robustness, "market", "KOSPI") is not None
        and _robustness_mean(robustness, "market", "KOSPI") >= 0
        and _robustness_mean(robustness, "market", "KOSDAQ") is not None
        and _robustness_mean(robustness, "market", "KOSDAQ") >= 0
    )
    entry_type_pass = bool(
        _robustness_mean(robustness, "entry_type", "FIRST_ENTRY") is not None
        and _robustness_mean(robustness, "entry_type", "FIRST_ENTRY") >= 0
        and _robustness_mean(robustness, "entry_type", "REENTRY") is not None
        and _robustness_mean(robustness, "entry_type", "REENTRY") >= 0
    )
    year_rows = robustness[robustness["dimension"] == "entry_year"]
    year_means = pd.to_numeric(year_rows["mean_paired_return_delta"], errors="coerce").dropna()
    year_pass = bool(not year_means.empty and int((year_means >= 0).sum()) >= len(year_means) / 2)
    default_criteria = {
        "criterion_1_mean_return_ge_v2": bool(v3_stats["mean_terminal_return_pct"] >= v2["mean_terminal_return_pct"]),
        "criterion_2_median_return_ge_v2": bool(v3_stats["median_terminal_return_pct"] >= v2["median_terminal_return_pct"]),
        "criterion_3_tail_le_30_rate_le_v2": bool(v3_stats["tail_le_30_rate_pct"] <= v2["tail_le_30_rate_pct"]),
        "criterion_4_tail_le_40_rate_le_v2": bool(v3_stats["tail_le_40_rate_pct"] <= v2["tail_le_40_rate_pct"]),
        "criterion_5_winner_or_giveback_improved": bool(path_b or path_c),
        "criterion_6_median_holding_le_v2": bool(v3_stats["median_holding_days"] <= v2["median_holding_days"]),
        "criterion_7_open_at_cutoff_rate_le_v2": bool(v3_stats["open_at_cutoff_rate_pct"] <= v2["open_at_cutoff_rate_pct"]),
        "criterion_8_robustness": bool(market_pass and entry_type_pass and year_pass),
    }
    return {
        "path_a_return_improvement": {"pass": path_a, "mean_delta_gt_zero": bool(paired["mean_delta"] > 0), "median_delta_ge_zero": bool(paired["median_delta"] >= 0)},
        "path_b_winner_preservation": {"pass": path_b, "v3_ge_50_gt_v2": bool(v3_stats["winner_ge_50_count"] > v2["winner_ge_50_count"]), "v3_ge_100_ge_v2": bool(v3_stats["winner_ge_100_count"] >= v2["winner_ge_100_count"])},
        "path_c_giveback_improvement": {"pass": path_c, "v3_median_giveback_lt_v2": bool(v3_stats["median_giveback"] < v2["median_giveback"]), "v3_mean_giveback_le_v2": bool(v3_stats["mean_giveback"] <= v2["mean_giveback"])},
        "performance_improvement_pass": performance_pass,
        "large_loss_area_worsened": large_loss_worsened,
        "capital_lock_area_worsened": capital_lock_worsened,
        "official_strategy_risk_block": official_risk_block,
        "official_adoption_eligible_by_preregistered_criteria": bool(performance_pass and not official_risk_block),
        "default_promotion_robustness": {"market": market_pass, "entry_type": entry_type_pass, "entry_year": year_pass},
        "default_promotion_criteria": default_criteria,
        "default_promotion_eligible_by_preregistered_criteria": bool(integrity_pass and all(default_criteria.values())),
    }


def _representative_row(case_type: str, rank: int, row: Mapping[str, Any]) -> dict[str, Any]:
    fields = [
        "ticker", "name", "market", "isu_cd", "control_trade_id", "control_trade_sequence",
        "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date", "entry_open",
        "v2_exit_category", "v2_terminal_return", "v2_mfe", "v2_mae", "v2_holding_days", "v2_giveback",
        "v3_exit_reason", "v3_terminal_return", "v3_strategy_path_mfe", "v3_strategy_path_mae", "v3_holding_days", "v3_giveback",
        "full_path_raw_mfe", "full_path_mfe_cohort", "return_delta_v3_minus_v2",
    ]
    return {"case_type": case_type, "rank": rank, **{field: row.get(field) for field in fields}}


def build_representative_cases(matched: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    cases: list[dict[str, Any]] = []

    def add(case_type: str, frame: pd.DataFrame, sort_columns: list[str], ascending: list[bool]) -> None:
        ordered = frame.sort_values(sort_columns + ["ticker", "entry_execution_date", "control_trade_id"], ascending=ascending + [True, True, True], kind="mergesort").head(limit)
        cases.extend(_representative_row(case_type, rank, row) for rank, row in enumerate(ordered.to_dict("records"), start=1))

    add("PRE_WINNER_WORST_TERMINAL_RETURN", matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"], ["v3_terminal_return"], [True])
    add("V3_OPEN_AT_CUTOFF_LONGEST_HOLDING", matched[matched["v3_exit_reason"] == "OPEN_AT_CUTOFF"], ["v3_holding_days"], [False])
    add("PAIRED_DELTA_LOWEST", matched, ["return_delta_v3_minus_v2"], [True])
    add("WINNER_PRESERVATION_LARGEST_DELTA", matched[matched["v3_terminal_return"] >= 50], ["return_delta_v3_minus_v2"], [False])
    add("WINNER_ACTIVATION_LARGEST_GIVEBACK", matched[matched["v3_strategy_path_mfe"] >= 20], ["v3_giveback"], [False])
    add("V3_SOFT_EXIT", matched[matched["v3_exit_reason"] == "SOFT_EXIT"], ["v3_terminal_return"], [True])
    add("V3_HARD_EXIT", matched[matched["v3_exit_reason"] == "HARD_EXIT"], ["v3_terminal_return"], [True])
    return pd.DataFrame(cases)


def build_exit_reason_diagnostics(matched: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    definitions = [
        ("V2", "LOSS_GUARD", "v2_exit_category"),
        ("V2", "EXIT3", "v2_exit_category"),
        ("V2", "EXIT4", "v2_exit_category"),
        ("V2", "OPEN_AT_CUTOFF", "v2_exit_category"),
        ("V3", "SOFT_EXIT", "v3_exit_reason"),
        ("V3", "HARD_EXIT", "v3_exit_reason"),
        ("V3", "OPEN_AT_CUTOFF", "v3_exit_reason"),
    ]
    for strategy, reason, column in definitions:
        frame = matched[matched[column] == reason]
        stats = _side_stats(frame, strategy.lower())
        rows.append({
            "strategy": strategy,
            "exit_reason": reason,
            "count": stats["trades"],
            "rate_pct": round(stats["trades"] / len(matched) * 100.0, 6),
            "mean_terminal_return": stats["mean_terminal_return_pct"],
            "median_terminal_return": stats["median_terminal_return_pct"],
            "mean_mfe": stats["mean_mfe_pct"],
            "median_mfe": stats["median_mfe_pct"],
            "mean_mae": stats["mean_mae_pct"],
            "median_mae": stats["median_mae_pct"],
            "mean_holding_days": stats["mean_holding_days"],
            "median_holding_days": stats["median_holding_days"],
            "mean_giveback": stats["mean_giveback"],
            "median_giveback": stats["median_giveback"],
        })
    return pd.DataFrame(rows)


def _build_report(summary: Mapping[str, Any]) -> str:
    integrity = summary["integrity"]
    v2 = summary["strategies"]["v2"]
    v3_stats = summary["strategies"]["v3"]
    paired = summary["paired"]
    decisions = summary["preregistered_decision"]
    return "\n".join([
        "# FastCore V3 공식 동일 진입 matched A/B 결과",
        "",
        "## 실행 상태",
        "",
        f"- 상태: `{summary['status']}`",
        f"- 기간: `{summary['evaluation_start']}` ~ `{summary['execution_support_end']}` 지원, signal cutoff `{summary['signal_cutoff']}`, 최종 평가 `{summary['final_valuation']}`",
        f"- matched 거래: `{integrity['matched_rows']}` / 고유 종목: `{integrity['unique_tickers']}`",
        f"- entry execution date 일치: `{integrity['entry_execution_date_match_count']}/{EXPECTED_TRADES}`",
        f"- entry open 일치: `{integrity['entry_open_match_count']}/{EXPECTED_TRADES}`",
        f"- 네트워크 요청: `{summary['network_requests']}`",
        "",
        "## V2 / V3 핵심 지표",
        "",
        f"| 지표 | V2 | V3 |",
        f"|---|---:|---:|",
        f"| mean terminal return | {v2['mean_terminal_return_pct']} | {v3_stats['mean_terminal_return_pct']} |",
        f"| median terminal return | {v2['median_terminal_return_pct']} | {v3_stats['median_terminal_return_pct']} |",
        f"| win rate | {v2['positive_rate_pct']}% | {v3_stats['positive_rate_pct']}% |",
        f"| mean MAE | {v2['mean_mae_pct']} | {v3_stats['mean_mae_pct']} |",
        f"| median MAE | {v2['median_mae_pct']} | {v3_stats['median_mae_pct']} |",
        f"| mean holding days | {v2['mean_holding_days']} | {v3_stats['mean_holding_days']} |",
        f"| median holding days | {v2['median_holding_days']} | {v3_stats['median_holding_days']} |",
        f"| OPEN_AT_CUTOFF | {v2['open_at_cutoff_count']} ({v2['open_at_cutoff_rate_pct']}%) | {v3_stats['open_at_cutoff_count']} ({v3_stats['open_at_cutoff_rate_pct']}%) |",
        f"| <= -30% | {v2['tail_le_30_count']} ({v2['tail_le_30_rate_pct']}%) | {v3_stats['tail_le_30_count']} ({v3_stats['tail_le_30_rate_pct']}%) |",
        f"| <= -40% | {v2['tail_le_40_count']} ({v2['tail_le_40_rate_pct']}%) | {v3_stats['tail_le_40_count']} ({v3_stats['tail_le_40_rate_pct']}%) |",
        f"| >= +50% | {v2['winner_ge_50_count']} | {v3_stats['winner_ge_50_count']} |",
        f"| >= +100% | {v2['winner_ge_100_count']} | {v3_stats['winner_ge_100_count']} |",
        f"| mean giveback | {v2['mean_giveback']} | {v3_stats['mean_giveback']} |",
        f"| median giveback | {v2['median_giveback']} | {v3_stats['median_giveback']} |",
        "",
        "## Cohort diagnostics",
        "",
        "| cohort | side | trades | mean return | median return | mean MAE | median MAE | median holding | OPEN_AT_CUTOFF | <= -20% | <= -30% | <= -40% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[
            f"| {cohort_name} | {side.upper()} | {cohort[side]['trades']} | {cohort[side]['mean_terminal_return_pct']} | {cohort[side]['median_terminal_return_pct']} | {cohort[side]['mean_mae_pct']} | {cohort[side]['median_mae_pct']} | {cohort[side]['median_holding_days']} | {cohort[side]['open_at_cutoff_count']} ({cohort[side]['open_at_cutoff_rate_pct']}%) | {cohort[side]['tail_le_20_count']} | {cohort[side]['tail_le_30_count']} | {cohort[side]['tail_le_40_count']} |"
            for cohort_name, cohort in (("PRE_WINNER_LT_20", summary["pre_winner"]), ("WINNER_CAPABLE_GE_20", summary["winner_capable"]))
            for side in ("v2", "v3")
        ],
        "",
        "## Paired 결과",
        "",
        f"- mean delta: `{paired['mean_delta']}`",
        f"- median delta: `{paired['median_delta']}`",
        f"- improved / worsened / same: `{paired['improved_count']} / {paired['worsened_count']} / {paired['same_count']}`",
        "",
        "## 사전등록 판정",
        "",
        f"- Path A: `{decisions['path_a_return_improvement']['pass']}`",
        f"- Path B: `{decisions['path_b_winner_preservation']['pass']}`",
        f"- Path C: `{decisions['path_c_giveback_improvement']['pass']}`",
        f"- performance improvement: `{decisions['performance_improvement_pass']}`",
        f"- large loss area worsened: `{decisions['large_loss_area_worsened']}`",
        f"- capital lock area worsened: `{decisions['capital_lock_area_worsened']}`",
        f"- official risk block: `{decisions['official_strategy_risk_block']}`",
        f"- official adoption eligible: `{decisions['official_adoption_eligible_by_preregistered_criteria']}`",
        f"- default promotion eligible: `{decisions['default_promotion_eligible_by_preregistered_criteria']}`",
        "",
        "## MDD",
        "",
        f"- 상태: `{summary['mdd']['status']}`",
        f"- 사유: {summary['mdd']['reason']}",
        "",
        "이 결과는 고정 CONTROL 진입에 대한 청산 규칙 matched A/B 결과이며, 자동 전략 채택·승격 또는 V3 규칙 수정으로 이어지지 않는다.",
        "",
    ])


def run_official() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    control = _normalise_control(CONTROL_TRADES_PATH)
    control_summary = _json_read(CONTROL_SUMMARY_PATH)
    validate_control_input(control, control_summary)
    if not PLAN_PATH.exists() or not V3_README_PATH.exists():
        raise AssertionError("required frozen plan or V3 README is missing")

    repository = v3.build_repository_v2(ROOT, end=v3.SUPPORT_END)
    loader = v3.RepositoryV2DailyLoader(repository, end=v3.SUPPORT_END)
    states, daily_by_ticker, state_errors = diagnostic._state_index(control, loader)
    rows = [
        replay_one(row, daily_by_ticker, states)
        for row in control.sort_values(["ticker", "entry_signal_date", "trade_sequence", "trade_id"], kind="mergesort").to_dict("records")
    ]
    matched = pd.DataFrame(rows)
    integrity = validate_matched_integrity(matched)
    v2_stats = _side_stats(matched, "v2")
    v3_stats = _side_stats(matched, "v3")
    delta_mean, delta_median = _mean_median(matched, "return_delta_v3_minus_v2")
    paired = {
        "mean_delta": delta_mean,
        "median_delta": delta_median,
        "improved_count": int((matched["improved_worsened_same"] == "improved").sum()),
        "worsened_count": int((matched["improved_worsened_same"] == "worsened").sum()),
        "same_count": int((matched["improved_worsened_same"] == "same").sum()),
    }
    paired["improved_rate_pct"] = round(paired["improved_count"] / EXPECTED_TRADES * 100.0, 6)
    paired["worsened_rate_pct"] = round(paired["worsened_count"] / EXPECTED_TRADES * 100.0, 6)
    paired["same_rate_pct"] = round(paired["same_count"] / EXPECTED_TRADES * 100.0, 6)
    robustness = build_robustness(matched)
    decisions = evaluate_preregistered_criteria(
        {
            "mean_terminal_return_pct": v2_stats["mean_terminal_return_pct"],
            "median_terminal_return_pct": v2_stats["median_terminal_return_pct"],
            "tail_le_30_rate_pct": v2_stats["tail_le_30_rate_pct"],
            "tail_le_40_rate_pct": v2_stats["tail_le_40_rate_pct"],
            "winner_ge_50_count": v2_stats["winner_ge_50_count"],
            "winner_ge_100_count": v2_stats["winner_ge_100_count"],
            "median_holding_days": v2_stats["median_holding_days"],
            "open_at_cutoff_rate_pct": v2_stats["open_at_cutoff_rate_pct"],
            "mean_giveback": v2_stats["mean_giveback"],
            "median_giveback": v2_stats["median_giveback"],
        },
        {
            "mean_terminal_return_pct": v3_stats["mean_terminal_return_pct"],
            "median_terminal_return_pct": v3_stats["median_terminal_return_pct"],
            "tail_le_30_rate_pct": v3_stats["tail_le_30_rate_pct"],
            "tail_le_40_rate_pct": v3_stats["tail_le_40_rate_pct"],
            "winner_ge_50_count": v3_stats["winner_ge_50_count"],
            "winner_ge_100_count": v3_stats["winner_ge_100_count"],
            "median_holding_days": v3_stats["median_holding_days"],
            "open_at_cutoff_rate_pct": v3_stats["open_at_cutoff_rate_pct"],
            "mean_giveback": v3_stats["mean_giveback"],
            "median_giveback": v3_stats["median_giveback"],
        },
        paired,
        robustness,
        integrity["pass"],
    )
    exit_reason = build_exit_reason_diagnostics(matched)
    representative = build_representative_cases(matched)
    summary: dict[str, Any] = {
        "work_id": "FASTCORE_V3_MATCHED_AB_OFFICIAL_V01",
        "status": "COMPLETE",
        "evaluation_start": EXPECTED_PERIOD[0],
        "signal_cutoff": EXPECTED_PERIOD[1],
        "execution_support_end": EXPECTED_PERIOD[2],
        "final_valuation": EXPECTED_FINAL_VALUATION,
        "control_trade_count": EXPECTED_TRADES,
        "control_unique_tickers": EXPECTED_UNIQUE_TICKERS,
        "integrity": integrity,
        "state_weekly_evaluation_error_count": state_errors,
        "strategies": {"v2": v2_stats, "v3": v3_stats},
        "paired": paired,
        "preregistered_decision": decisions,
        "pre_winner": {
            "definition": "full_path_raw_mfe < +20%",
            "trade_count": int((matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20").sum()),
            "trade_rate_pct": round(float((matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20").mean() * 100.0), 6),
            "v2": _side_stats(matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"], "v2"),
            "v3": _side_stats(matched[matched["full_path_mfe_cohort"] == "PRE_WINNER_LT_20"], "v3"),
        },
        "winner_capable": {
            "definition": "full_path_raw_mfe >= +20%",
            "trade_count": int((matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20").sum()),
            "trade_rate_pct": round(float((matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20").mean() * 100.0), 6),
            "v2": _side_stats(matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"], "v2"),
            "v3": _side_stats(matched[matched["full_path_mfe_cohort"] == "WINNER_CAPABLE_GE_20"], "v3"),
        },
        "mdd": {
            "status": "NOT_EVALUATED",
            "reason": "fixed-entry trade-level A/B has no pre-confirmed common portfolio equity curve; new portfolio model is prohibited",
        },
        "network_requests": None,
        "production_strategy_modified": False,
        "existing_v3_artifact_modified": False,
        "source_artifacts": {
            "validation_plan": str(PLAN_PATH.relative_to(ROOT)),
            "control_trades": str(CONTROL_TRADES_PATH.relative_to(ROOT)),
            "control_summary": str(CONTROL_SUMMARY_PATH.relative_to(ROOT)),
            "v3_readme": str(V3_README_PATH.relative_to(ROOT)),
            "v3_frozen_implementation": "scripts/run_fastcore_v3_simple_v00.py",
            "matched_replay_reference": "scripts/analyze_fastcore_v3_exit_ab_v00.py",
        },
        "representative_case_rule": {
            "limit_per_case_type": 10,
            "tie_breaker": ["ticker", "entry_execution_date", "control_trade_id"],
        },
    }
    return summary, matched, robustness, exit_reason, representative


def refresh_existing_cohort_summary() -> None:
    """Complete cohort-side summaries from the already-generated official match."""
    summary = _json_read(SUMMARY_PATH)
    matched = pd.read_csv(MATCHED_PATH)
    if len(matched) != EXPECTED_TRADES:
        raise AssertionError(f"existing matched artifact rows != {EXPECTED_TRADES}: {len(matched)}")
    for key, cohort in (
        ("pre_winner", "PRE_WINNER_LT_20"),
        ("winner_capable", "WINNER_CAPABLE_GE_20"),
    ):
        frame = matched[matched["full_path_mfe_cohort"] == cohort]
        summary[key]["v2"] = _side_stats(frame, "v2")
        summary[key]["v3"] = _side_stats(frame, "v3")
    _json_write(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(_build_report(summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()
    if args.run == args.refresh_existing:
        parser.error("choose exactly one of --run or --refresh-existing")
    if args.refresh_existing:
        try:
            refresh_existing_cohort_summary()
            print(json.dumps({"status": "REFRESHED_EXISTING_OFFICIAL_ARTIFACT"}, ensure_ascii=False), flush=True)
            return 0
        except Exception as exc:
            print(f"FASTCORE V3 OFFICIAL ARTIFACT REFRESH BLOCKED: {type(exc).__name__}: {exc}", flush=True)
            return 1
    audit = diagnostic.NetworkAudit()
    try:
        with diagnostic.network_guard(audit):
            summary, matched, robustness, exit_reason, representative = run_official()
        summary["network_requests"] = audit.request_count
        if audit.request_count != 0:
            summary["status"] = "FAIL"
            raise AssertionError(f"network_requests must be 0, got {audit.request_count}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        matched.to_csv(MATCHED_PATH, index=False, lineterminator="\n")
        robustness.to_csv(ROBUSTNESS_PATH, index=False, lineterminator="\n")
        exit_reason.to_csv(EXIT_REASON_PATH, index=False, lineterminator="\n")
        representative.to_csv(REPRESENTATIVE_PATH, index=False, lineterminator="\n")
        _json_write(SUMMARY_PATH, summary)
        REPORT_PATH.write_text(_build_report(summary), encoding="utf-8")
        print(json.dumps({
            "status": summary["status"],
            "matched_trades": summary["integrity"]["matched_rows"],
            "unique_tickers": summary["integrity"]["unique_tickers"],
            "network_requests": summary["network_requests"],
            "official_adoption_eligible": summary["preregistered_decision"]["official_adoption_eligible_by_preregistered_criteria"],
            "default_promotion_eligible": summary["preregistered_decision"]["default_promotion_eligible_by_preregistered_criteria"],
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f"FASTCORE V3 OFFICIAL MATCHED A/B BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
