#!/usr/bin/env python3
"""Reaggregate the immutable V06 ledger by terminal status and ETF category."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v06"
OUTPUT_DIR = ROOT / "artifacts/research/etf_v06_afast_vs_julia_post_analysis_v01"
LEDGER_PATH = SOURCE_DIR / "trade_ledger.csv"
SUMMARY_PATH = SOURCE_DIR / "full_summary.json"
UNIVERSE_PATH = SOURCE_DIR / "included_plain_long_universe_2026-09-29.csv"
CATEGORY_ORDER = ("MARKET_INDEX", "SECTOR_INDUSTRY", "COMMODITY_RESOURCE")
STRATEGIES = (
    "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    "JULIA_STRATEGY_V00",
)
STATUS_MAP = {"REALIZED": "CLOSED", "OPEN_AT_CUTOFF": "TERMINAL"}
TAIL_THRESHOLDS = {
    "ge_20": ("ge", 20.0),
    "ge_50": ("ge", 50.0),
    "ge_100": ("ge", 100.0),
    "le_15": ("le", -15.0),
    "le_30": ("le", -30.0),
    "le_40": ("le", -40.0),
    "le_50": ("le", -50.0),
}
RETURN_TOLERANCE_PP = 0.1


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _number(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _stats(frame: pd.DataFrame) -> dict[str, Any]:
    gross = _number(frame["gross_return_pct"]) if not frame.empty else np.array([])
    net = (
        _number(frame["commission_slippage_pre_tax_return_pct"])
        if not frame.empty else np.array([])
    )
    holding = (
        _number(frame["holding_krx_sessions_inclusive"])
        if not frame.empty else np.array([])
    )

    def mean_or_none(values: np.ndarray) -> float | None:
        return float(values.mean()) if len(values) else None

    def median_or_none(values: np.ndarray) -> float | None:
        return float(np.median(values)) if len(values) else None

    result: dict[str, Any] = {
        "trade_count": int(len(frame)),
        "positive_rate_pct": float((gross > 0).mean() * 100) if len(gross) else None,
        "positive_rate_cost_adjusted_pct": float((net > 0).mean() * 100) if len(net) else None,
        "mean_gross_return_pct": mean_or_none(gross),
        "median_gross_return_pct": median_or_none(gross),
        "mean_cost_adjusted_return_pct": mean_or_none(net),
        "median_cost_adjusted_return_pct": median_or_none(net),
        "mean_holding_sessions": mean_or_none(holding),
        "median_holding_sessions": median_or_none(holding),
    }
    for quantile in (10, 25, 50, 75, 90):
        result[f"gross_p{quantile}_pct"] = (
            float(np.percentile(gross, quantile)) if len(gross) else None
        )
    for label, (direction, threshold) in TAIL_THRESHOLDS.items():
        result[f"{label}_count"] = int(
            np.count_nonzero(gross >= threshold if direction == "ge" else gross <= threshold)
        )
    return result


def _near(actual: Any, expected: Any, tolerance: float = RETURN_TOLERANCE_PP) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(float(actual) - float(expected)) <= tolerance


def _aggregate_validation(
    frame: pd.DataFrame,
    stored_summary: Mapping[str, Any],
    stored_category_rows: list[Mapping[str, Any]],
    universe: pd.DataFrame,
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    overall_checks = []
    category_lookup = {
        (row["category"], row["strategy_id"]): row for row in stored_category_rows
    }
    category_universe_counts = universe["category"].value_counts().to_dict()
    for strategy in STRATEGIES:
        current = frame.loc[frame["strategy_id"].eq(strategy)]
        actual = _stats(current)
        stored = stored_summary["strategies"][strategy]
        checks = {
            "trade_count": int(stored["trade_count"]) == actual["trade_count"],
            "unique_etf_count": int(stored["unique_etf_count"]) == int(current["ticker"].nunique()),
        }
        for stored_group, current_prefix in (
            ("trade_weighted_all_positions_gross", "gross"),
            ("trade_weighted_all_positions_after_cost", "cost"),
        ):
            group = stored[stored_group]
            if current_prefix == "gross":
                pairs = {
                    "positive_rate_pct": actual["positive_rate_pct"],
                    "mean_pct": actual["mean_gross_return_pct"],
                    "median_pct": actual["median_gross_return_pct"],
                    "p10_pct": actual["gross_p10_pct"],
                    "p25_pct": actual["gross_p25_pct"],
                    "p50_pct": actual["gross_p50_pct"],
                    "p75_pct": actual["gross_p75_pct"],
                    "p90_pct": actual["gross_p90_pct"],
                }
            else:
                pairs = {
                    "positive_rate_pct": actual["positive_rate_cost_adjusted_pct"],
                    "mean_pct": actual["mean_cost_adjusted_return_pct"],
                    "median_pct": actual["median_cost_adjusted_return_pct"],
                }
            for key, value in pairs.items():
                checks[f"{current_prefix}.{key}"] = _near(value, group.get(key))
                if not checks[f"{current_prefix}.{key}"]:
                    mismatches.append({
                        "scope": "overall",
                        "strategy_id": strategy,
                        "metric": f"{current_prefix}.{key}",
                        "ledger_value": value,
                        "v06_value": group.get(key),
                        "absolute_difference": (
                            None if value is None or group.get(key) is None
                            else abs(float(value) - float(group[key]))
                        ),
                    })
        etf_means = current.groupby("ticker")["gross_return_pct"].mean()
        etf_positive = current.assign(
            _positive=current["gross_return_pct"].gt(0)
        ).groupby("ticker")["_positive"].mean() * 100
        etf_weighted = stored["etf_weighted"]
        checks["etf_weighted.median_etf_mean_trade_return_pct"] = _near(
            float(etf_means.median()) if len(etf_means) else None,
            etf_weighted.get("median_etf_mean_trade_return_pct"),
        )
        checks["etf_weighted.median_etf_positive_rate_pct"] = _near(
            float(etf_positive.median()) if len(etf_positive) else None,
            etf_weighted.get("median_etf_positive_rate_pct"),
        )
        checks["etf_weighted.etf_count_with_trades"] = (
            int(etf_means.size) == int(etf_weighted.get("etf_count_with_trades", -1))
        )
        overall_checks.append({"strategy_id": strategy, "checks": checks, "passed": all(checks.values())})
        for category in CATEGORY_ORDER:
            subset = current.loc[current["category"].eq(category)]
            category_stats = _stats(subset)
            stored_category = category_lookup.get((category, strategy))
            if stored_category is None:
                mismatches.append({
                    "scope": "category", "strategy_id": strategy,
                    "category": category, "metric": "missing_v06_category_row",
                })
                continue
            category_checks = {
                "trade_count": int(stored_category["trade_count"]) == category_stats["trade_count"],
                "etf_count": int(stored_category["etf_count"]) == int(category_universe_counts.get(category, 0)),
            }
            for key, value in (
                ("positive_return_rate_pct_gross", category_stats["positive_rate_pct"]),
                ("mean_gross_return_pct", category_stats["mean_gross_return_pct"]),
                ("median_gross_return_pct", category_stats["median_gross_return_pct"]),
                ("mean_cost_adjusted_return_pct", category_stats["mean_cost_adjusted_return_pct"]),
                ("median_cost_adjusted_return_pct", category_stats["median_cost_adjusted_return_pct"]),
            ):
                category_checks[key] = _near(value, stored_category.get(key))
                if not category_checks[key]:
                    mismatches.append({
                        "scope": "category",
                        "strategy_id": strategy,
                        "category": category,
                        "metric": key,
                        "ledger_value": value,
                        "v06_value": stored_category.get(key),
                        "absolute_difference": (
                            None if value is None or stored_category.get(key) is None
                            else abs(float(value) - float(stored_category[key]))
                        ),
                    })
            if not category_checks["trade_count"]:
                mismatches.append({
                    "scope": "category", "strategy_id": strategy,
                    "category": category, "metric": "trade_count",
                    "ledger_value": category_stats["trade_count"],
                    "v06_value": stored_category["trade_count"],
                })
            if not category_checks["etf_count"]:
                mismatches.append({
                    "scope": "category", "strategy_id": strategy,
                    "category": category, "metric": "etf_count",
                    "v06_value": stored_category["etf_count"],
                })

    return {
        "return_aggregate_tolerance_absolute_pp": RETURN_TOLERANCE_PP,
        "overall_strategy_checks": overall_checks,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _status_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy in STRATEGIES:
        all_rows = frame.loc[frame["strategy_id"].eq(strategy)]
        closed = all_rows.loc[all_rows["analysis_status"].eq("CLOSED")]
        terminal = all_rows.loc[all_rows["analysis_status"].eq("TERMINAL")]
        total_count = len(all_rows)
        for status in ("CLOSED", "TERMINAL"):
            subset = all_rows.loc[all_rows["analysis_status"].eq(status)]
            row = {
                "strategy_id": strategy,
                "analysis_status": status,
                "ledger_trade_status": "REALIZED" if status == "CLOSED" else "OPEN_AT_CUTOFF",
                "total_trade_count": total_count,
                "closed_count": len(closed),
                "closed_rate_pct": 100 * len(closed) / total_count if total_count else None,
                "terminal_count": len(terminal),
                "terminal_rate_pct": 100 * len(terminal) / total_count if total_count else None,
                "unique_etf_count": int(all_rows["ticker"].nunique()),
                "closed_unique_etf_count": int(closed["ticker"].nunique()),
                "terminal_unique_etf_count": int(terminal["ticker"].nunique()),
                "status_trade_count": len(subset),
                "status_unique_etf_count": int(subset["ticker"].nunique()),
            }
            row.update(_stats(subset))
            rows.append(row)
    return pd.DataFrame(rows)


def _category_summaries(
    frame: pd.DataFrame,
    universe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    category_counts = universe["category"].value_counts().to_dict()
    category_rows = []
    closed_rows = []
    etf_weighted_rows = []
    for category in CATEGORY_ORDER:
        category_all = frame.loc[frame["category"].eq(category)]
        for strategy in STRATEGIES:
            subset = category_all.loc[category_all["strategy_id"].eq(strategy)]
            stats = _stats(subset)
            category_rows.append({
                "category": category,
                "strategy_id": strategy,
                "etf_count": int(category_counts.get(category, 0)),
                "traded_etf_count": int(subset["ticker"].nunique()),
                **stats,
            })
            closed = subset.loc[subset["analysis_status"].eq("CLOSED")]
            closed_stats = _stats(closed)
            closed_rows.append({
                "category": category,
                "strategy_id": strategy,
                "trade_count": int(len(closed)),
                "positive_rate_pct": closed_stats["positive_rate_pct"],
                "mean_gross_return_pct": closed_stats["mean_gross_return_pct"],
                "median_gross_return_pct": closed_stats["median_gross_return_pct"],
                "ge_50_count": closed_stats["ge_50_count"],
                "le_15_count": closed_stats["le_15_count"],
            })

    for category_name in ("ALL", *CATEGORY_ORDER):
        for strategy in STRATEGIES:
            subset = frame.loc[frame["strategy_id"].eq(strategy)]
            if category_name != "ALL":
                subset = subset.loc[subset["category"].eq(category_name)]
            by_etf = subset.groupby("ticker")["gross_return_pct"].agg(
                mean_trade_return_pct="mean",
                positive_rate=lambda values: float((values > 0).mean() * 100),
            )
            etf_weighted_rows.append({
                "category": category_name,
                "strategy_id": strategy,
                "etf_count_with_trades": int(len(by_etf)),
                "median_etf_mean_trade_return_pct": (
                    float(by_etf["mean_trade_return_pct"].median()) if len(by_etf) else None
                ),
                "median_etf_positive_rate_pct": (
                    float(by_etf["positive_rate"].median()) if len(by_etf) else None
                ),
            })
    return (
        pd.DataFrame(category_rows),
        pd.DataFrame(closed_rows),
        pd.DataFrame(etf_weighted_rows),
    )


def _top_bottom(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    columns = [
        "ticker", "name", "category", "signal_date", "entry_execution_date",
        "exit_or_terminal_date", "gross_return_pct",
        "commission_slippage_pre_tax_return_pct",
        "holding_krx_sessions_inclusive", "trade_status", "analysis_status",
    ]
    for strategy in STRATEGIES:
        for status in ("CLOSED", "TERMINAL"):
            group = frame.loc[
                frame["strategy_id"].eq(strategy)
                & frame["analysis_status"].eq(status)
            ].sort_values(
                ["gross_return_pct", "ticker", "entry_execution_date"],
                kind="mergesort",
            )
            bottom = group.head(5)
            top = group.tail(5).sort_values(
                ["gross_return_pct", "ticker", "entry_execution_date"],
                ascending=[False, True, True],
                kind="mergesort",
            )
            for label, selected in (("BOTTOM_5", bottom), ("TOP_5", top)):
                for rank, (_, trade) in enumerate(selected.iterrows(), start=1):
                    rows.append({
                        "strategy_id": strategy,
                        "analysis_status": status,
                        "ranking": label,
                        "rank": rank,
                        **{column: trade[column] for column in columns},
                    })
    return pd.DataFrame(rows)


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _write_summary(
    output_path: Path,
    validation: Mapping[str, Any],
    status_table: pd.DataFrame,
    category_table: pd.DataFrame,
    closed_category_table: pd.DataFrame,
    etf_weighted_table: pd.DataFrame,
) -> None:
    status_lines = [
        "| 전략 | 구분 | 거래 | 거래 ETF | 양수율 | Gross 평균 / 중앙값 | 비용 반영 평균 / 중앙값 | Gross P10/P25/P50/P75/P90 | 보유 평균 / 중앙값 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in status_table.to_dict("records"):
        status_lines.append(
            f"| {row['strategy_id']} | {row['analysis_status']} | {row['status_trade_count']} | "
            f"{row['status_unique_etf_count']} | {_fmt(row['positive_rate_pct'])}% | "
            f"{_fmt(row['mean_gross_return_pct'])}% / {_fmt(row['median_gross_return_pct'])}% | "
            f"{_fmt(row['mean_cost_adjusted_return_pct'])}% / {_fmt(row['median_cost_adjusted_return_pct'])}% | "
            f"{_fmt(row['gross_p10_pct'])}/{_fmt(row['gross_p25_pct'])}/{_fmt(row['gross_p50_pct'])}/"
            f"{_fmt(row['gross_p75_pct'])}/{_fmt(row['gross_p90_pct'])}% | "
            f"{_fmt(row['mean_holding_sessions'])} / {_fmt(row['median_holding_sessions'])} |"
        )
    category_lines = [
        "| Category | 전략 | Universe ETF | 거래 ETF | 거래 | 양수율 | Gross 평균 / 중앙값 | 비용 반영 평균 / 중앙값 | Gross P25/P50/P75 | +20/+50/+100 | -15/-30/-40/-50 | 보유 중앙값 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in category_table.to_dict("records"):
        tails_up = "/".join(str(row[f"ge_{n}_count"]) for n in (20, 50, 100))
        tails_down = "/".join(str(row[f"le_{n}_count"]) for n in (15, 30, 40, 50))
        category_lines.append(
            f"| {row['category']} | {row['strategy_id']} | {row['etf_count']} | "
            f"{row['traded_etf_count']} | {row['trade_count']} | {_fmt(row['positive_rate_pct'])}% | "
            f"{_fmt(row['mean_gross_return_pct'])}% / {_fmt(row['median_gross_return_pct'])}% | "
            f"{_fmt(row['mean_cost_adjusted_return_pct'])}% / {_fmt(row['median_cost_adjusted_return_pct'])}% | "
            f"{_fmt(row['gross_p25_pct'])}/{_fmt(row['gross_p50_pct'])}/{_fmt(row['gross_p75_pct'])}% | "
            f"{tails_up} | {tails_down} | {_fmt(row['median_holding_sessions'])} |"
        )
    closed_lines = [
        "| Category | 전략 | CLOSED 거래 | 양수율 | Gross 평균 / 중앙값 | +50 | -15 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in closed_category_table.to_dict("records"):
        closed_lines.append(
            f"| {row['category']} | {row['strategy_id']} | {row['trade_count']} | "
            f"{_fmt(row['positive_rate_pct'])}% | {_fmt(row['mean_gross_return_pct'])}% / "
            f"{_fmt(row['median_gross_return_pct'])}% | {row['ge_50_count']} | {row['le_15_count']} |"
        )
    weighted_lines = [
        "| 범위 | 전략 | 거래 ETF | ETF별 평균수익률 중앙값 | ETF별 양수율 중앙값 |",
        "|---|---|---:|---:|---:|",
    ]
    for row in etf_weighted_table.to_dict("records"):
        weighted_lines.append(
            f"| {row['category']} | {row['strategy_id']} | {row['etf_count_with_trades']} | "
            f"{_fmt(row['median_etf_mean_trade_return_pct'])}% | "
            f"{_fmt(row['median_etf_positive_rate_pct'])}% |"
        )

    julia = status_table.loc[status_table["strategy_id"].eq(STRATEGIES[1])].set_index("analysis_status")
    afast = status_table.loc[status_table["strategy_id"].eq(STRATEGIES[0])].set_index("analysis_status")
    overall_summary = validation["v06_overall_reaggregation"]
    status_question = (
        f"Julia 전체 ledger에서 양수율 {_fmt(overall_summary[STRATEGIES[1]]['positive_rate_pct'])}% / "
        f"중앙값 {_fmt(overall_summary[STRATEGIES[1]]['median_gross_return_pct'])}%였어. "
        f"CLOSED만 보면 양수율 {_fmt(julia.loc['CLOSED', 'positive_rate_pct'])}% / "
        f"중앙값 {_fmt(julia.loc['CLOSED', 'median_gross_return_pct'])}%, TERMINAL만 보면 "
        f"{_fmt(julia.loc['TERMINAL', 'positive_rate_pct'])}% / "
        f"{_fmt(julia.loc['TERMINAL', 'median_gross_return_pct'])}%야. "
        f"CLOSED 양수율은 전체보다 {float(julia.loc['CLOSED', 'positive_rate_pct']) - float(overall_summary[STRATEGIES[1]]['positive_rate_pct']):+.2f}pp, "
        f"CLOSED 중앙값은 {float(julia.loc['CLOSED', 'median_gross_return_pct']) - float(overall_summary[STRATEGIES[1]]['median_gross_return_pct']):+.2f}pp 높아. "
        "따라서 Julia의 높은 전체 양수율과 중앙값은 TERMINAL 평가에만 의존하지 않고 CLOSED 거래에서도 유지돼. "
        "TERMINAL은 cutoff 종가 평가이며 실현 수익으로 해석하면 안 돼."
    )
    medians = category_table.pivot(
        index="category", columns="strategy_id", values="median_gross_return_pct"
    )
    positives = category_table.pivot(
        index="category", columns="strategy_id", values="positive_rate_pct"
    )
    median_gap = (medians[STRATEGIES[1]] - medians[STRATEGIES[0]]).dropna()
    positive_gap = (positives[STRATEGIES[1]] - positives[STRATEGIES[0]]).dropna()
    median_category = median_gap.abs().idxmax()
    positive_category = positive_gap.abs().idxmax()
    closed_medians = closed_category_table.pivot(
        index="category", columns="strategy_id", values="median_gross_return_pct"
    )
    closed_median_gap = closed_medians[STRATEGIES[1]] - closed_medians[STRATEGIES[0]]

    lines = [
        "# V06 A FAST / Julia CLOSED vs TERMINAL 및 Category 재집계",
        "",
        f"- 판정: {validation['verdict']}",
        "- 범위: V06 ledger의 재집계만 수행. 새 백테스트·전략 replay·signal generation은 하지 않았어.",
        "- 원본 V06 artifact는 읽기만 했고 수정하지 않았어.",
        "- CLOSED는 ledger trade_status=REALIZED, TERMINAL은 ledger trade_status=OPEN_AT_CUTOFF로 그대로 분류했어.",
        f"- 수익률 aggregate 교차검증 허용오차: absolute {RETURN_TOLERANCE_PP:.1f} percentage point.",
        "",
        "## CLOSED / TERMINAL",
        "",
        *status_lines,
        "",
        "### Julia 지표의 TERMINAL 의존 여부",
        "",
        status_question,
        "",
        "### CLOSED / TERMINAL count와 ETF coverage",
        "",
        "| 전략 | 전체 거래 / ETF | CLOSED 거래 / ETF | CLOSED 비율 | TERMINAL 거래 / ETF | TERMINAL 비율 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for strategy in STRATEGIES:
        rows = status_table.loc[status_table["strategy_id"].eq(strategy)].set_index("analysis_status")
        closed_row, terminal_row = rows.loc["CLOSED"], rows.loc["TERMINAL"]
        lines.append(
            f"| {strategy} | {int(closed_row['total_trade_count'])} / {int(closed_row['unique_etf_count'])} | "
            f"{int(closed_row['closed_count'])} / {int(closed_row['closed_unique_etf_count'])} | "
            f"{_fmt(closed_row['closed_rate_pct'])}% | "
            f"{int(terminal_row['terminal_count'])} / {int(terminal_row['terminal_unique_etf_count'])} | "
            f"{_fmt(terminal_row['terminal_rate_pct'])}% |"
        )
    lines.extend([
        "",
        "## Category × Strategy",
        "",
        *category_lines,
        "",
        f"Gross median의 절대 격차가 가장 큰 category는 {median_category} "
        f"(Julia − A FAST = {median_gap.loc[median_category]:+.2f}pp)야. "
        f"양수율 격차가 가장 큰 category는 {positive_category} "
        f"(Julia − A FAST = {positive_gap.loc[positive_category]:+.2f}pp)야.",
        f"CLOSED-only에서도 {closed_median_gap.abs().idxmax()}의 median gross 차이가 "
        f"{closed_median_gap.loc[closed_median_gap.abs().idxmax()]:+.2f}pp로 가장 커. "
        "category별 median 격차는 TERMINAL 평가만으로 설명되지 않아.",
        f"A FAST는 CLOSED 양수율/중앙값 {_fmt(afast.loc['CLOSED', 'positive_rate_pct'])}% / "
        f"{_fmt(afast.loc['CLOSED', 'median_gross_return_pct'])}%이고 TERMINAL은 "
        f"{_fmt(afast.loc['TERMINAL', 'positive_rate_pct'])}% / "
        f"{_fmt(afast.loc['TERMINAL', 'median_gross_return_pct'])}%야.",
        "",
        "## CLOSED-only Category 보조표",
        "",
        *closed_lines,
        "",
        "CLOSED-only gross median의 Julia − A FAST 차이:",
        "",
    ])
    for category, value in closed_median_gap.items():
        lines.append(f"- {category}: {value:+.2f}pp")
    lines.extend([
        "",
        "## ETF-weighted (V06 계약)",
        "",
        *weighted_lines,
        "",
        "ETF별 mean trade return의 중앙값과 ETF별 positive rate의 중앙값을 사용했어. 새 composite score는 만들지 않았어.",
        "",
        "## 재집계 검증",
        "",
        f"- 검증 통과: {validation['passed']}",
        f"- overall/category aggregate mismatch: {validation['aggregate_validation']['mismatch_count']}",
        f"- 중복 trade ID: {validation['duplicate_trade_id_count']}",
        f"- unknown category: {validation['unknown_category_count']}",
        f"- CLOSED + TERMINAL count mismatch: {validation['closed_terminal_count_mismatch_count']}",
        f"- category count sum mismatch: {validation['category_trade_count_mismatch_count']}",
        "- 상세 검증은 validation.json에 저장했어.",
        "",
        "## 산출물",
        "",
        "- closed_terminal_summary.csv",
        "- category_summary.csv",
        "- closed_only_category_summary.csv",
        "- etf_weighted_summary.csv",
        "- top_bottom_by_status.csv",
        "- validation.json",
        "",
        "이 표는 V06 거래를 상태와 기존 category별로 기술적으로 비교한 재집계야. 새로운 전략 winner 판정은 하지 않았어.",
        "",
    ])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not all(path.is_file() for path in (LEDGER_PATH, SUMMARY_PATH, UNIVERSE_PATH)):
        raise FileNotFoundError("V06_LEDGER_SUMMARY_OR_UNIVERSE_MISSING")
    v06_summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    ledger = pd.read_csv(LEDGER_PATH, dtype={"ticker": "string"})
    universe = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": "string"})
    if v06_summary.get("verdict") != "ETF_PLAIN_LONG_THREE_STRATEGY_SIMPLE_BACKTEST_V06_COMPLETE":
        raise RuntimeError(f"V06_SOURCE_VERDICT_MISMATCH:{v06_summary.get('verdict')}")
    ledger["ticker"] = ledger["ticker"].astype(str).str.zfill(6)
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)
    selected = ledger.loc[ledger["strategy_id"].isin(STRATEGIES)].copy()
    category_by_ticker = universe.set_index("ticker")["category"]
    selected["category"] = selected["ticker"].map(category_by_ticker)
    selected["analysis_status"] = selected["trade_status"].map(STATUS_MAP)

    trade_id_values = []
    for row in selected.itertuples(index=False):
        details = json.loads(row.source_signal_details or "{}")
        canonical_id = details.get("canonical_trade_id")
        trade_id_values.append(
            f"{row.strategy_id}|{row.ticker}|{canonical_id}" if canonical_id else None
        )
    selected["analysis_trade_id"] = trade_id_values
    selected_counts = selected["strategy_id"].value_counts().to_dict()
    expected_counts = {
        STRATEGIES[0]: 350,
        STRATEGIES[1]: 246,
    }
    count_mismatches = {
        strategy: {"expected": count, "actual": int(selected_counts.get(strategy, 0))}
        for strategy, count in expected_counts.items()
        if int(selected_counts.get(strategy, 0)) != count
    }
    unknown_category_count = int(selected["category"].isna().sum())
    unknown_status_count = int(selected["analysis_status"].isna().sum())
    invalid_trade_id_count = int(selected["analysis_trade_id"].isna().sum())
    duplicate_trade_id_count = int(
        selected.loc[selected["analysis_trade_id"].notna(), "analysis_trade_id"].duplicated().sum()
    )

    status_table = _status_summary(selected)
    category_table, closed_category_table, etf_weighted_table = _category_summaries(
        selected, universe
    )
    top_bottom = _top_bottom(selected)
    aggregate_validation = _aggregate_validation(
        selected, v06_summary, v06_summary.get("category_results", []), universe
    )

    closed_terminal_mismatches = []
    category_sum_mismatches = []
    for strategy in STRATEGIES:
        all_count = int(selected["strategy_id"].eq(strategy).sum())
        statuses = status_table.loc[status_table["strategy_id"].eq(strategy)].set_index("analysis_status")
        closed_count = int(statuses.loc["CLOSED", "status_trade_count"])
        terminal_count = int(statuses.loc["TERMINAL", "status_trade_count"])
        if closed_count + terminal_count != all_count:
            closed_terminal_mismatches.append({
                "strategy_id": strategy,
                "closed": closed_count,
                "terminal": terminal_count,
                "total": all_count,
            })
        category_sum = int(category_table.loc[
            category_table["strategy_id"].eq(strategy), "trade_count"
        ].sum())
        if category_sum != all_count:
            category_sum_mismatches.append({
                "strategy_id": strategy, "category_sum": category_sum, "total": all_count,
            })

    checks = {
        "v06_source_verdict_exact": v06_summary["verdict"] == "ETF_PLAIN_LONG_THREE_STRATEGY_SIMPLE_BACKTEST_V06_COMPLETE",
        "strategy_trade_counts_exact": not count_mismatches,
        "closed_plus_terminal_equals_total": not closed_terminal_mismatches,
        "category_count_sum_equals_total": not category_sum_mismatches,
        "duplicate_trade_ids_zero": duplicate_trade_id_count == 0,
        "canonical_trade_ids_present": invalid_trade_id_count == 0,
        "unknown_category_zero": unknown_category_count == 0,
        "unknown_status_zero": unknown_status_count == 0,
        "overall_and_category_aggregates_within_0_1pp": aggregate_validation["mismatch_count"] == 0,
    }
    validation = {
        "verdict": (
            "ETF_V06_AFAST_VS_JULIA_POST_ANALYSIS_COMPLETE"
            if all(checks.values()) else "CHECK_REQUIRED"
        ),
        "analysis_only": True,
        "new_backtest_or_replay": False,
        "v06_input_directory": str(SOURCE_DIR.relative_to(ROOT)),
        "v06_source_verdict": v06_summary["verdict"],
        "strategies": list(STRATEGIES),
        "expected_trade_counts": expected_counts,
        "actual_trade_counts": {k: int(v) for k, v in selected_counts.items()},
        "trade_status_counts": {
            str(k): int(v)
            for k, v in selected.groupby(["strategy_id", "analysis_status"]).size().items()
        },
        "category_counts_in_universe": {
            str(k): int(v) for k, v in universe["category"].value_counts().items()
        },
        "duplicate_trade_id_count": duplicate_trade_id_count,
        "canonical_trade_id_missing_count": invalid_trade_id_count,
        "unknown_category_count": unknown_category_count,
        "unknown_status_count": unknown_status_count,
        "closed_terminal_count_mismatch_count": len(closed_terminal_mismatches),
        "category_trade_count_mismatch_count": len(category_sum_mismatches),
        "closed_terminal_count_mismatches": closed_terminal_mismatches,
        "category_trade_count_mismatches": category_sum_mismatches,
        "strategy_trade_count_mismatches": count_mismatches,
        "aggregate_validation": aggregate_validation,
        "v06_overall_reaggregation": {
            strategy: _stats(selected.loc[selected["strategy_id"].eq(strategy)])
            for strategy in STRATEGIES
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    status_table.to_csv(OUTPUT_DIR / "closed_terminal_summary.csv", index=False)
    category_table.to_csv(OUTPUT_DIR / "category_summary.csv", index=False)
    closed_category_table.to_csv(OUTPUT_DIR / "closed_only_category_summary.csv", index=False)
    etf_weighted_table.to_csv(OUTPUT_DIR / "etf_weighted_summary.csv", index=False)
    top_bottom.to_csv(OUTPUT_DIR / "top_bottom_by_status.csv", index=False)
    _write_json(OUTPUT_DIR / "validation.json", validation)
    _write_summary(
        OUTPUT_DIR / "summary.md", validation, status_table,
        category_table, closed_category_table, etf_weighted_table,
    )
    print(json.dumps({
        "verdict": validation["verdict"],
        "trade_counts": validation["actual_trade_counts"],
        "status_counts": validation["trade_status_counts"],
        "duplicate_trade_id_count": duplicate_trade_id_count,
        "aggregate_mismatch_count": aggregate_validation["mismatch_count"],
    }, ensure_ascii=False))
    return 0 if validation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
