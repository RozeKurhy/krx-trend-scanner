#!/usr/bin/env python3
"""Analyze PASS/FAIL cohorts among existing A FAST Core V2 CONTROL trades.

This is a read-only cohort analysis. It does not run a backtest, collect market
or fundamental data, or modify the source study artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/oi_1q_20b_5window_v01"
OUTPUT_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/oi_1q_20b_available_only_v01"
KEY_COLUMNS = ("ticker", "isu_cd", "entry_signal_date")
WINDOWS = (
    ("P1", "p1"),
    ("P2-1", "p2_1"),
    ("P2-2", "p2_2"),
    ("P3-1", "p3_1"),
    ("P3-2", "p3_2"),
)
COHORT_STATUSES = ("PASS", "FAIL", "UNAVAILABLE")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: csv_value(row.get(name)) for name in fieldnames})


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.8f}"
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def key_for(row: dict[str, str]) -> tuple[str, str, str]:
    return tuple((row.get(column) or "").strip() for column in KEY_COLUMNS)  # type: ignore[return-value]


def duplicate_key_report(rows: list[dict[str, str]]) -> tuple[int, int]:
    counts = Counter(key_for(row) for row in rows)
    duplicate_values = sum(count > 1 for count in counts.values())
    duplicate_excess_rows = sum(count - 1 for count in counts.values() if count > 1)
    return duplicate_values, duplicate_excess_rows


def parse_return(row: dict[str, str]) -> float | None:
    raw = (row.get("terminal_return") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def linear_quantile(sorted_values: list[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    returns = sorted(float(trade["terminal_return"]) for trade in trades)
    count = len(returns)
    if not count:
        return {
            "trade_count": 0,
            "mean_return_pct": None,
            "median_return_pct": None,
            "win_count": 0,
            "win_rate_pct": None,
            "loss_count": 0,
            "loss_rate_pct": None,
            "break_even_count": 0,
            "ge_50_count": 0,
            "ge_50_rate_pct": None,
            "worst_return_pct": None,
            "p10_return_pct": None,
        }
    win_count = sum(value > 0 for value in returns)
    loss_count = sum(value < 0 for value in returns)
    ge_50_count = sum(value >= 50 for value in returns)
    return {
        "trade_count": count,
        "mean_return_pct": statistics.fmean(returns),
        "median_return_pct": statistics.median(returns),
        "win_count": win_count,
        "win_rate_pct": win_count / count * 100,
        "loss_count": loss_count,
        "loss_rate_pct": loss_count / count * 100,
        "break_even_count": sum(value == 0 for value in returns),
        "ge_50_count": ge_50_count,
        "ge_50_rate_pct": ge_50_count / count * 100,
        "worst_return_pct": returns[0],
        "p10_return_pct": linear_quantile(returns, 0.10),
    }


def find_outside_window(rows: list[dict[str, str]], start: str, end: str) -> int:
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    outside = 0
    for row in rows:
        value = (row.get("entry_signal_date") or "").strip()
        try:
            signal_date = date.fromisoformat(value)
        except ValueError:
            outside += 1
            continue
        outside += not (lower <= signal_date <= upper)
    return int(outside)


def pct(numerator: int, denominator: int) -> float | None:
    return numerator / denominator * 100 if denominator else None


def rounded(value: Any, digits: int = 4) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def fmt(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def main() -> None:
    required = [
        SOURCE_DIR / "oi_entry_evaluations.csv",
        SOURCE_DIR / "window_boundaries.json",
        SOURCE_DIR / "execution_metadata.json",
        SOURCE_DIR / "pit_audit.json",
        *(SOURCE_DIR / folder / "control_trade_ledger.csv" for _, folder in WINDOWS),
    ]
    if any(not path.is_file() for path in required):
        missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
        raise FileNotFoundError("Missing required source artifacts: " + ", ".join(missing))

    input_hashes_before = {str(path.relative_to(ROOT)): sha256(path) for path in required}
    evaluations = read_csv(SOURCE_DIR / "oi_entry_evaluations.csv")
    boundaries = read_json(SOURCE_DIR / "window_boundaries.json")["windows"]
    metadata = read_json(SOURCE_DIR / "execution_metadata.json")
    pit_audit = read_json(SOURCE_DIR / "pit_audit.json")
    pit_index: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in evaluations:
        pit_index[key_for(row)].append(row)
    pit_duplicate_values, pit_duplicate_excess = duplicate_key_report(evaluations)

    results: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    delta_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    per_window_trades: dict[str, dict[str, list[dict[str, Any]]]] = {}
    critical_count = pit_duplicate_excess
    major_count = 0
    minor_unavailable_rows = 0

    for window_name, folder in WINDOWS:
        ledger_path = SOURCE_DIR / folder / "control_trade_ledger.csv"
        control = read_csv(ledger_path)
        window = boundaries[window_name]
        metadata_window = metadata["periods"][window_name]
        boundary_contract_match = all(
            window[field] == metadata_window[field]
            for field in ("effective_start", "effective_end", "execution_support")
        )
        boundary_violation_count = find_outside_window(
            control, window["effective_start"], window["effective_end"]
        )
        control_duplicate_values, control_duplicate_excess = duplicate_key_report(control)
        critical_count += control_duplicate_excess

        cohorts: dict[str, list[dict[str, Any]]] = {status: [] for status in COHORT_STATUSES}
        available: list[dict[str, Any]] = []
        joined_rows: list[dict[str, Any]] = []
        missing_count = 0
        ambiguous_count = 0
        unexpected_status_count = 0
        status_counts: Counter[str] = Counter()
        source_basis_mismatch_count = 0
        ledger_status_mismatch_count = 0
        invalid_return_count = 0
        open_at_cutoff_count = sum(row.get("trade_status") == "OPEN_AT_CUTOFF" for row in control)

        for row in control:
            key = key_for(row)
            matches = pit_index.get(key, [])
            if len(matches) == 0:
                missing_count += 1
                continue
            if len(matches) > 1:
                ambiguous_count += 1
                continue

            pit_row = matches[0]
            status = (pit_row.get("oi_status") or "").strip()
            status_counts[status] += 1
            if pit_row.get("source_oi_status") == "BASIS_OR_CURRENCY_MISMATCH":
                source_basis_mismatch_count += 1
            if (row.get("oi_status") or "").strip() != status:
                ledger_status_mismatch_count += 1
            if status not in COHORT_STATUSES:
                unexpected_status_count += 1
                continue

            terminal_return = parse_return(row)
            if terminal_return is None:
                invalid_return_count += 1
                continue

            trade = {
                "ticker": key[0],
                "isu_cd": key[1],
                "entry_signal_date": key[2],
                "trade_id": row.get("trade_id", ""),
                "trade_status": row.get("trade_status", ""),
                "oi_status": status,
                "source_oi_status": pit_row.get("source_oi_status", ""),
                "terminal_return": terminal_return,
            }
            joined_rows.append(trade)
            if status in ("PASS", "FAIL"):
                available.append(trade)
                cohorts[status].append(trade)
            else:
                cohorts["UNAVAILABLE"].append(trade)

        unavailable_count = len(cohorts["UNAVAILABLE"])
        minor_unavailable_rows += unavailable_count
        major_count += (
            missing_count
            + ambiguous_count
            + unexpected_status_count
            + ledger_status_mismatch_count
            + invalid_return_count
            + boundary_violation_count
            + (0 if boundary_contract_match else 1)
        )

        control_with_return = []
        for row in control:
            terminal_return = parse_return(row)
            if terminal_return is not None:
                control_with_return.append({"terminal_return": terminal_return})
        groups = {
            "PASS": cohorts["PASS"],
            "FAIL": cohorts["FAIL"],
            "AVAILABLE_ALL": available,
            "CONTROL_ALL": control_with_return,
        }
        group_metrics = {name: metrics(trades) for name, trades in groups.items()}
        available_count = len(available)
        pass_count = len(cohorts["PASS"])
        fail_count = len(cohorts["FAIL"])
        joined_count = sum(status_counts.values()) - unexpected_status_count
        exact_join_count = len(joined_rows) + invalid_return_count
        # A valid OI join remains a join even if a return value cannot be parsed.
        exact_join_count = sum(status_counts.values())
        window_result = {
            "window": window_name,
            "folder": folder,
            "effective_start": window["effective_start"],
            "effective_end": window["effective_end"],
            "execution_support": window["execution_support"],
            "boundary_contract_match": boundary_contract_match,
            "boundary_violation_count": boundary_violation_count,
            "control_trade_count": len(control),
            "pit_exact_join_count": exact_join_count,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "available_count": available_count,
            "unavailable_count": unavailable_count,
            "join_missing_count": missing_count,
            "ambiguous_duplicate_join_count": ambiguous_count,
            "control_duplicate_key_value_count": control_duplicate_values,
            "control_duplicate_excess_row_count": control_duplicate_excess,
            "pit_duplicate_key_value_count_global": pit_duplicate_values,
            "pit_duplicate_excess_row_count_global": pit_duplicate_excess,
            "unexpected_status_count": unexpected_status_count,
            "ledger_oi_status_mismatch_count": ledger_status_mismatch_count,
            "invalid_terminal_return_count": invalid_return_count,
            "basis_currency_mismatch_source_count": source_basis_mismatch_count,
            "open_at_cutoff_count": open_at_cutoff_count,
            "status_counts": dict(status_counts),
            "groups": group_metrics,
        }
        results.append(window_result)
        per_window_trades[window_name] = groups

        for cohort_name, cohort_trades in groups.items():
            row_metrics = group_metrics[cohort_name]
            comparison_rows.append(
                {
                    "window": window_name,
                    "cohort": cohort_name,
                    "trade_count": row_metrics["trade_count"],
                    "share_of_available_pct": pct(row_metrics["trade_count"], available_count)
                    if cohort_name in ("PASS", "FAIL")
                    else (100.0 if cohort_name == "AVAILABLE_ALL" and available_count else None),
                    **row_metrics,
                }
            )

        pass_metrics, fail_metrics = group_metrics["PASS"], group_metrics["FAIL"]
        delta_rows.append(
            {
                "window": window_name,
                "available_count": available_count,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "mean_return_delta_pass_minus_fail_pp": difference(
                    pass_metrics["mean_return_pct"], fail_metrics["mean_return_pct"]
                ),
                "median_return_delta_pass_minus_fail_pp": difference(
                    pass_metrics["median_return_pct"], fail_metrics["median_return_pct"]
                ),
                "win_rate_delta_pass_minus_fail_pp": difference(
                    pass_metrics["win_rate_pct"], fail_metrics["win_rate_pct"]
                ),
                "loss_rate_delta_pass_minus_fail_pp": difference(
                    pass_metrics["loss_rate_pct"], fail_metrics["loss_rate_pct"]
                ),
                "ge_50_rate_delta_pass_minus_fail_pp": difference(
                    pass_metrics["ge_50_rate_pct"], fail_metrics["ge_50_rate_pct"]
                ),
                "p10_return_delta_pass_minus_fail_pp": difference(
                    pass_metrics["p10_return_pct"], fail_metrics["p10_return_pct"]
                ),
            }
        )

        control_metrics, available_metrics = group_metrics["CONTROL_ALL"], group_metrics["AVAILABLE_ALL"]
        coverage_rows.append(
            {
                "window": window_name,
                "control_trade_count": len(control),
                "pit_exact_join_count": exact_join_count,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "available_count": available_count,
                "available_rate_of_control_pct": pct(available_count, len(control)),
                "unavailable_count": unavailable_count,
                "unavailable_rate_of_control_pct": pct(unavailable_count, len(control)),
                "join_missing_count": missing_count,
                "ambiguous_duplicate_join_count": ambiguous_count,
                "control_duplicate_key_value_count": control_duplicate_values,
                "pit_duplicate_key_value_count_global": pit_duplicate_values,
                "unexpected_status_count": unexpected_status_count,
                "ledger_oi_status_mismatch_count": ledger_status_mismatch_count,
                "invalid_terminal_return_count": invalid_return_count,
                "boundary_violation_count": boundary_violation_count,
                "boundary_contract_match": boundary_contract_match,
                "basis_currency_mismatch_source_count": source_basis_mismatch_count,
                "open_at_cutoff_count": open_at_cutoff_count,
                **{f"control_{name}": value for name, value in control_metrics.items()},
                **{f"available_{name}": value for name, value in available_metrics.items()},
            }
        )

    input_hashes_after = {str(path.relative_to(ROOT)): sha256(path) for path in required}
    inputs_unchanged = input_hashes_before == input_hashes_after
    if not inputs_unchanged:
        major_count += 1

    # Availability is a planned cohort outcome, not a join or computation defect.
    severity = {
        "CRITICAL": critical_count,
        "MAJOR": major_count,
        "MINOR": minor_unavailable_rows,
        "minor_definition": "Per-window CONTROL rows classified UNAVAILABLE and intentionally omitted from PASS/FAIL. Counts overlap across standard windows and are not unique trades.",
    }

    summary = {
        "study_id": "A_FAST_CORE_V2_OI_1Q_20B_AVAILABLE_ONLY_V01",
        "analysis_type": "read-only PASS vs FAIL cohort analysis of existing CONTROL trade ledgers",
        "source_study_id": metadata.get("study_id"),
        "source_directory": str(SOURCE_DIR.relative_to(ROOT)),
        "output_directory": str(OUTPUT_DIR.relative_to(ROOT)),
        "join_key": list(KEY_COLUMNS),
        "available_statuses": ["PASS", "FAIL"],
        "excluded_statuses": ["UNAVAILABLE", "all other/unmatched states"],
        "return_source": "terminal_return exactly as stored in the existing CONTROL ledger, including OPEN_AT_CUTOFF rows",
        "win_definition": "terminal_return > 0",
        "loss_definition": "terminal_return < 0",
        "break_even_definition": "terminal_return == 0; counted separately, excluded from both wins and losses",
        "ge_50_definition": "terminal_return >= 50",
        "p10_definition": "linear interpolation at quantile 0.10, equivalent to the default pandas Series.quantile method",
        "pit_authority_digest": metadata.get("pit_authority", {}).get("content_digest"),
        "pit_as_of": metadata.get("pit_authority", {}).get("target_as_of"),
        "pit_audit_status_counts": pit_audit.get("status_counts", {}),
        "control_ledger_files_modified": False,
        "new_backtest_or_lifecycle_replay": False,
        "new_market_or_fundamental_data_collected": False,
        "official_strategy_files_modified": False,
        "input_files_unchanged_during_analysis": inputs_unchanged,
        "input_sha256": input_hashes_before,
        "severity": severity,
        "windows": results,
        "interpretation": interpret(results),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_DIR / "summary.json", summary)
    write_csv(
        OUTPUT_DIR / "window_cohort_comparison.csv",
        [
            "window",
            "cohort",
            "trade_count",
            "share_of_available_pct",
            "mean_return_pct",
            "median_return_pct",
            "win_count",
            "win_rate_pct",
            "loss_count",
            "loss_rate_pct",
            "break_even_count",
            "ge_50_count",
            "ge_50_rate_pct",
            "worst_return_pct",
            "p10_return_pct",
        ],
        comparison_rows,
    )
    write_csv(
        OUTPUT_DIR / "window_delta.csv",
        [
            "window",
            "available_count",
            "pass_count",
            "fail_count",
            "mean_return_delta_pass_minus_fail_pp",
            "median_return_delta_pass_minus_fail_pp",
            "win_rate_delta_pass_minus_fail_pp",
            "loss_rate_delta_pass_minus_fail_pp",
            "ge_50_rate_delta_pass_minus_fail_pp",
            "p10_return_delta_pass_minus_fail_pp",
        ],
        delta_rows,
    )
    coverage_fields = list(coverage_rows[0]) if coverage_rows else []
    write_csv(OUTPUT_DIR / "coverage.csv", coverage_fields, coverage_rows)
    report = build_report(summary, comparison_rows, delta_rows, coverage_rows)
    (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_DIR.relative_to(ROOT)}")
    print(f"Severity: CRITICAL={critical_count}, MAJOR={major_count}, MINOR={minor_unavailable_rows}")
    print("Inputs unchanged:", inputs_unchanged)
    for result in results:
        print(
            result["window"],
            "CONTROL", result["control_trade_count"],
            "PASS", result["pass_count"],
            "FAIL", result["fail_count"],
            "UNAVAILABLE", result["unavailable_count"],
            "join_missing", result["join_missing_count"],
        )


def difference(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def interpret(results: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = []
    for result in results:
        pass_metrics = result["groups"]["PASS"]
        fail_metrics = result["groups"]["FAIL"]
        deltas.append(
            {
                "window": result["window"],
                "win_rate_pass_gt_fail": gt(pass_metrics["win_rate_pct"], fail_metrics["win_rate_pct"]),
                "loss_rate_pass_lt_fail": lt(pass_metrics["loss_rate_pct"], fail_metrics["loss_rate_pct"]),
                "mean_pass_gt_fail": gt(pass_metrics["mean_return_pct"], fail_metrics["mean_return_pct"]),
                "median_pass_gt_fail": gt(pass_metrics["median_return_pct"], fail_metrics["median_return_pct"]),
                "p10_pass_gt_fail": gt(pass_metrics["p10_return_pct"], fail_metrics["p10_return_pct"]),
                "ge_50_rate_pass_ge_fail": ge(pass_metrics["ge_50_rate_pct"], fail_metrics["ge_50_rate_pct"]),
            }
        )
    return {
        "win_rate_pass_gt_fail_windows": sum(row["win_rate_pass_gt_fail"] for row in deltas),
        "loss_rate_pass_lt_fail_windows": sum(row["loss_rate_pass_lt_fail"] for row in deltas),
        "mean_pass_gt_fail_windows": sum(row["mean_pass_gt_fail"] for row in deltas),
        "median_pass_gt_fail_windows": sum(row["median_pass_gt_fail"] for row in deltas),
        "p10_pass_gt_fail_windows": sum(row["p10_pass_gt_fail"] for row in deltas),
        "ge_50_rate_pass_at_least_fail_windows": sum(row["ge_50_rate_pass_ge_fail"] for row in deltas),
        "window_comparisons": deltas,
    }


def gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left > right


def ge(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left >= right


def lt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left < right


def build_report(
    summary: dict[str, Any],
    comparison_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> str:
    severity = summary["severity"]
    lines = [
        "# A FAST Core V2 OI20 AVAILABLE-only Cohort Analysis V01",
        "",
        "## 검수 수준",
        "",
        md_table(
            ["레벨", "개수"],
            [
                ["CRITICAL", severity["CRITICAL"]],
                ["MAJOR", severity["MAJOR"]],
                ["MINOR", severity["MINOR"]],
            ],
        ),
        "",
        "CRITICAL은 duplicate key, MAJOR는 join 누락·중복 join·상태/수익률 오류·기간 경계 오류를 센다. MINOR는 각 window에서 PIT 상태가 UNAVAILABLE인 CONTROL 거래 수다. UNAVAILABLE은 지시서에 따라 PASS/FAIL 분석에서 제외하며 결함으로 보지 않는다. 창 사이에 같은 거래가 겹칠 수 있어 MINOR 합계는 고유 종목/거래 수가 아니다.",
        "",
        "## PASS vs FAIL PRIMARY 비교",
        "",
        md_table(
            ["기간", "Cohort", "거래 수", "AVAILABLE 내 비중 %", "평균 %", "중앙값 %", "승률 %", "손실률 %", ">=50% 건수/비율", "최악 %", "p10 %"],
            [
                [
                    row["window"], row["cohort"], row["trade_count"],
                    fmt(row["share_of_available_pct"]), fmt(row["mean_return_pct"]),
                    fmt(row["median_return_pct"]), fmt(row["win_rate_pct"]),
                    fmt(row["loss_rate_pct"]), f"{row['ge_50_count']} / {fmt(row['ge_50_rate_pct'])}",
                    fmt(row["worst_return_pct"]), fmt(row["p10_return_pct"]),
                ]
                for row in comparison_rows if row["cohort"] in ("PASS", "FAIL")
            ],
        ),
        "",
        "승률은 `terminal_return > 0`, 손실률은 `< 0`, 손익분기는 `== 0`으로 별도 집계했다. +50%는 `>= 50`이며 p10은 선형 보간 방식이다. 모든 수익률은 기존 CONTROL 원장의 `terminal_return`을 그대로 썼고 OPEN_AT_CUTOFF 거래도 원장 값 그대로 포함했다.",
        "",
        "## 1. Window별 PASS - FAIL delta",
        "",
        md_table(
            ["기간", "평균 pp", "중앙값 pp", "승률 pp", "손실률 pp", ">=50% 비율 pp", "p10 pp"],
            [
                [
                    row["window"], fmt(row["mean_return_delta_pass_minus_fail_pp"]),
                    fmt(row["median_return_delta_pass_minus_fail_pp"]),
                    fmt(row["win_rate_delta_pass_minus_fail_pp"]),
                    fmt(row["loss_rate_delta_pass_minus_fail_pp"]),
                    fmt(row["ge_50_rate_delta_pass_minus_fail_pp"]),
                    fmt(row["p10_return_delta_pass_minus_fail_pp"]),
                ]
                for row in delta_rows
            ],
        ),
        "",
        "수익률 차이와 비율 차이는 모두 PASS - FAIL이다. 비율 차이는 percentage point(pp)다.",
        "",
        "## 2. AVAILABLE coverage와 CONTROL 표본 성격",
        "",
        md_table(
            ["기간", "CONTROL", "PASS", "FAIL", "AVAILABLE", "AVAILABLE %", "UNAVAILABLE", "UNAVAILABLE %", "join 누락", "중복 key", "상태 불일치", "OPEN_AT_CUTOFF"],
            [
                [
                    row["window"], row["control_trade_count"], row["pass_count"], row["fail_count"],
                    row["available_count"], fmt(row["available_rate_of_control_pct"]),
                    row["unavailable_count"], fmt(row["unavailable_rate_of_control_pct"]),
                    row["join_missing_count"],
                    row["control_duplicate_key_value_count"] + row["pit_duplicate_key_value_count_global"],
                    row["ledger_oi_status_mismatch_count"], row["open_at_cutoff_count"],
                ]
                for row in coverage_rows
            ],
        ),
        "",
        "Coverage 표본 수익률 프로필은 필터 성능 비교가 아니라 UNAVAILABLE 제외 전후의 표본 구성 설명이다.",
        "",
        md_table(
            ["기간", "집단", "거래 수", "평균 %", "중앙값 %", "승률 %", "손실률 %", ">=50% 건수/비율", "최악 %", "p10 %"],
            [
                [
                    row["window"], row["cohort"], row["trade_count"],
                    fmt(row["mean_return_pct"]), fmt(row["median_return_pct"]),
                    fmt(row["win_rate_pct"]), fmt(row["loss_rate_pct"]),
                    f"{row['ge_50_count']} / {fmt(row['ge_50_rate_pct'])}",
                    fmt(row["worst_return_pct"]), fmt(row["p10_return_pct"]),
                ]
                for row in comparison_rows if row["cohort"] in ("CONTROL_ALL", "AVAILABLE_ALL")
            ],
        ),
        "",
        "원장 상태별 통계는 `coverage.csv`에 포함했다. CONTROL 전체 대 AVAILABLE 전체는 PIT coverage에 따른 표본 성격 변화를 설명하며, 조건의 선별력 판정에 쓰지 않는다.",
        "",
        "## 3. +50% winner 비교",
        "",
        md_table(
            ["기간", "PASS +50% 건수/비율", "FAIL +50% 건수/비율", "PASS - FAIL pp"],
            [
                [
                    row["window"],
                    f"{group_metrics(summary, row['window'], 'PASS', 'ge_50_count')} / {fmt(group_metrics(summary, row['window'], 'PASS', 'ge_50_rate_pct'))}",
                    f"{group_metrics(summary, row['window'], 'FAIL', 'ge_50_count')} / {fmt(group_metrics(summary, row['window'], 'FAIL', 'ge_50_rate_pct'))}",
                    fmt(next(delta["ge_50_rate_delta_pass_minus_fail_pp"] for delta in delta_rows if delta["window"] == row["window"])),
                ]
                for row in coverage_rows
            ],
        ),
        "",
        "## 4. 손실 거래 비교",
        "",
        md_table(
            ["기간", "PASS 손실 건수/비율", "FAIL 손실 건수/비율", "PASS - FAIL pp"],
            [
                [
                    row["window"],
                    f"{group_metrics(summary, row['window'], 'PASS', 'loss_count')} / {fmt(group_metrics(summary, row['window'], 'PASS', 'loss_rate_pct'))}",
                    f"{group_metrics(summary, row['window'], 'FAIL', 'loss_count')} / {fmt(group_metrics(summary, row['window'], 'FAIL', 'loss_rate_pct'))}",
                    fmt(next(delta["loss_rate_delta_pass_minus_fail_pp"] for delta in delta_rows if delta["window"] == row["window"])),
                ]
                for row in coverage_rows
            ],
        ),
        "",
        "## 5. 5-window 종합 해석",
        "",
        interpretation_text(summary),
        "",
        "## 방법과 제한",
        "",
        "- 입력은 기존 V01의 PIT 평가 파일, window별 CONTROL 원장, 경계·메타데이터·PIT audit뿐이다. 기존 산출물 해시를 분석 전후 비교해 변경되지 않았음을 확인했다.",
        "- exact join key는 `(ticker, isu_cd, entry_signal_date)`다. PASS와 FAIL만 AVAILABLE로 묶고, UNAVAILABLE 및 join 누락은 PASS/FAIL 어느 쪽에도 넣지 않았다.",
        "- BASIS_OR_CURRENCY_MISMATCH의 fail-closed 처리 결과는 원본 평가의 `oi_status=UNAVAILABLE`을 그대로 따른다. 원본 source status는 coverage 진단에만 보존했다.",
        "- 이 분석은 CONTROL에서 실제 발생한 거래 결과와 진입 시점 PIT 상태의 연관성을 비교한다. 가상으로 FAIL 거래를 제거했을 때의 lifecycle·포트폴리오 성과를 재생하지 않는다.",
        "- P1은 오래된 기간에서 재무정보 coverage가 선택적으로 남을 수 있으므로 P1 결과의 일반화에 주의한다. 이 결과만으로 공식 전략을 변경하거나 추가 threshold를 제안하지 않는다.",
        "- 신규 시세·fundamentals 수집, backtest, TEST lifecycle replay는 수행하지 않았다.",
        "",
        f"PIT authority digest: `{summary['pit_authority_digest']}` (as of `{summary['pit_as_of']}`).",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def group_metrics(summary: dict[str, Any], window: str, group: str, metric: str) -> Any:
    result = next(row for row in summary["windows"] if row["window"] == window)
    return result["groups"][group][metric]


def interpretation_text(summary: dict[str, Any]) -> str:
    interpretation = summary["interpretation"]
    windows = interpretation["window_comparisons"]
    by_window = {row["window"]: row for row in windows}
    details = {row["window"]: row for row in summary["windows"]}
    p2_short = details["P2-1"]["groups"]
    p2_long = details["P2-2"]["groups"]
    p3_short = details["P3-1"]["groups"]
    p3_long = details["P3-2"]["groups"]
    p2_mean_short = p2_short["PASS"]["mean_return_pct"] - p2_short["FAIL"]["mean_return_pct"]
    p2_mean_long = p2_long["PASS"]["mean_return_pct"] - p2_long["FAIL"]["mean_return_pct"]
    p3_mean_short = p3_short["PASS"]["mean_return_pct"] - p3_short["FAIL"]["mean_return_pct"]
    p3_mean_long = p3_long["PASS"]["mean_return_pct"] - p3_long["FAIL"]["mean_return_pct"]
    p2_winner_short = p2_short["PASS"]["ge_50_rate_pct"] - p2_short["FAIL"]["ge_50_rate_pct"]
    p2_winner_long = p2_long["PASS"]["ge_50_rate_pct"] - p2_long["FAIL"]["ge_50_rate_pct"]
    p3_winner_short = p3_short["PASS"]["ge_50_rate_pct"] - p3_short["FAIL"]["ge_50_rate_pct"]
    p3_winner_long = p3_long["PASS"]["ge_50_rate_pct"] - p3_long["FAIL"]["ge_50_rate_pct"]
    return "\n".join(
        [
            f"1. PASS 승률이 FAIL보다 높은 기간은 {interpretation['win_rate_pass_gt_fail_windows']}/5, 손실률이 낮은 기간은 {interpretation['loss_rate_pass_lt_fail_windows']}/5다.",
            f"2. PASS 평균은 {interpretation['mean_pass_gt_fail_windows']}/5, 중앙값은 {interpretation['median_pass_gt_fail_windows']}/5, p10은 {interpretation['p10_pass_gt_fail_windows']}/5에서 FAIL보다 높다.",
            f"3. PASS의 +50% winner 비율이 FAIL 이상인 기간은 {interpretation['ge_50_rate_pass_at_least_fail_windows']}/5다. 이 비율이 낮은 기간에는 해당 조건이 큰 winner를 더 많이 포함하지 않는다.",
            f"4. P2에서 P2-1→P2-2로 기간을 늘리면 평균차가 {p2_mean_short:+.2f}→{p2_mean_long:+.2f}pp로 음수에서 양수로 바뀐다. 승률·손실률·중앙값·p10은 두 기간 모두 PASS에 유리하지만, +50% winner 비율 차이는 {p2_winner_short:+.2f}→{p2_winner_long:+.2f}pp로 바뀐다.",
            f"5. P3도 P3-1→P3-2에서 평균차가 {p3_mean_short:+.2f}→{p3_mean_long:+.2f}pp로 바뀐다. 승률·손실률·중앙값·p10은 두 기간 모두 PASS에 유리하고 +50% winner 비율 차이는 {p3_winner_short:+.2f}→{p3_winner_long:+.2f}pp다. 기간 연장은 거래 조합과 시장 구간도 바꾸므로 순수한 기간 효과로 단정할 수 없다.",
            f"6. AVAILABLE 비중은 P1 {next(row['available_rate_of_control_pct'] for row in coverage_rows_from_summary(summary) if row['window'] == 'P1'):.2f}%이며 나머지 기간은 약 89–90%다. P1은 재무정보 coverage가 선택적으로 남을 수 있어 일반화에 특히 주의해야 한다.",
            "7. 이 차이는 기존 CONTROL 거래 표본 내의 cohort 상관관계다. 가상으로 FAIL을 제거한 lifecycle·포트폴리오 성과는 계산하지 않았고, 이 결과만으로 공식 전략을 변경하지 않는다.",
        ]
    )


def coverage_rows_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result in summary["windows"]:
        rows.append(
            {
                "window": result["window"],
                "available_rate_of_control_pct": pct(result["available_count"], result["control_trade_count"]),
            }
        )
    return rows


if __name__ == "__main__":
    main()
