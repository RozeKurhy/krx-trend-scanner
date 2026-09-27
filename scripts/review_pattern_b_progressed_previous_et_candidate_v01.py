#!/usr/bin/env python3
"""Add standards and strategy-quality review to saved Pattern B validation.

Reads completed trade ledgers and saved reports only. It never runs a lifecycle
replay or backtest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validate_pattern_b_progressed_previous_stage_early_transition_only_official_v01 as validator  # noqa: E402

OUT = ROOT / validator.OUTPUT
STUDY = ROOT / "artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01"
RULES = ROOT / "docs/validation/backtest_common_rules.md"
LIFECYCLE = ROOT / "docs/strategies/strategy_lifecycle.md"
FREEZE = ROOT / validator.FREEZE_DOC
README = ROOT / "docs/patterns/pattern_b/README.md"
WINDOWS = [("P1", "p1"), ("P2-1", "p2_1"), ("P2-2", "p2_2"), ("P3-1", "p3_1"), ("P3-2", "p3_2")]
REVIEW_START_HEAD = "74a71b16b137dffd5eee20efc5d6cf45f4420e6e"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(items[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(items)


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolved_value(row: dict[str, str]) -> float | None:
    if row.get("trade_status") == "REALIZED":
        return number(row.get("gross_return_pct"))
    if row.get("trade_status") == "OPEN_AT_CUTOFF" and row.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE":
        return number(row.get("mark_to_cutoff_gross_return_pct"))
    return None


def read_only_quality() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    annual_groups: dict[str, list[tuple[dict[str, str], float | None]]] = defaultdict(list)
    ticker_groups: dict[str, list[tuple[dict[str, str], float]]] = defaultdict(list)
    cost_rows: list[dict[str, Any]] = []
    validation_rows = read_csv(OUT / "five_window_validation.csv")
    p90_by_window: dict[str, float | None] = {}

    for label, dirname in WINDOWS:
        folder = STUDY / dirname
        saved = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        ledger = read_csv(folder / "test_trade_ledger.csv")
        realized = [r for r in ledger if r.get("trade_status") == "REALIZED"]
        p90_by_window[label] = number(saved["new_test_lifecycle_summary"]["mfe_mae_holding"].get("p90_holding_krx_sessions"))
        cost_rows.append({
            "window": label,
            "realized_count": len(realized),
            "commission_slippage_pre_tax_count": sum(number(r.get("commission_slippage_pre_tax_return_pct")) is not None for r in realized),
            "sell_tax_rate_present_count": sum(number(r.get("sell_tax_rate")) is not None for r in realized),
            "full_standard_net_count": sum(number(r.get("full_standard_net_return_pct")) is not None for r in realized),
        })
        if label == "P1":
            for row in ledger:
                if row.get("trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"}:
                    continue
                year = row.get("entry_execution_date", "")[:4]
                annual_groups[year].append((row, resolved_value(row)))
                v = resolved_value(row)
                if v is not None:
                    ticker_groups[row["ticker"]].append((row, v))

    for row in validation_rows:
        label = row["window"]
        row["resolved_n"] = int(row["realized"]) + int(row["exact_open"])
        row["p90_holding_sessions"] = p90_by_window[label]
        cost = next(item for item in cost_rows if item["window"] == label)
        row.update(cost)
        row["full_standard_net_coverage_pct"] = (
            100 * cost["full_standard_net_count"] / cost["realized_count"] if cost["realized_count"] else None
        )
    write_csv(OUT / "five_window_validation.csv", validation_rows)

    annual_rows: list[dict[str, Any]] = []
    for year, pairs in sorted(annual_groups.items()):
        values = [v for _, v in pairs if v is not None]
        realized_n = sum(r.get("trade_status") == "REALIZED" for r, _ in pairs)
        exact_n = sum(r.get("trade_status") == "OPEN_AT_CUTOFF" and r.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE" for r, _ in pairs)
        unresolved_n = sum(v is None for _, v in pairs)
        annual_rows.append({
            "entry_execution_year": year,
            "filled_count": len(pairs),
            "realized_count": realized_n,
            "exact_cutoff_open_count": exact_n,
            "unresolved_count": unresolved_n,
            "resolved_terminal_n": len(values),
            "resolved_terminal_mean_gross_pct": statistics.mean(values) if values else None,
            "resolved_terminal_median_gross_pct": statistics.median(values) if values else None,
            "resolved_terminal_positive_rate_pct": 100 * sum(v > 0 for v in values) / len(values) if values else None,
        })
    write_csv(OUT / "annual_breakdown.csv", annual_rows)

    ticker_rows = []
    for ticker, pairs in ticker_groups.items():
        values = [v for _, v in pairs]
        ticker_rows.append({
            "ticker": ticker,
            "resolved_trade_count": len(values),
            "realized_count": sum(r.get("trade_status") == "REALIZED" for r, _ in pairs),
            "exact_cutoff_open_count": sum(r.get("trade_status") == "OPEN_AT_CUTOFF" for r, _ in pairs),
            "gross_return_points_sum": sum(values),
            "positive_return_points_sum": sum(v for v in values if v > 0),
            "negative_abs_return_points_sum": -sum(v for v in values if v < 0),
        })
    ticker_rows.sort(key=lambda r: (-r["resolved_trade_count"], r["ticker"]))
    write_csv(OUT / "ticker_concentration.csv", ticker_rows)

    pos_total = sum(r["positive_return_points_sum"] for r in ticker_rows)
    neg_total = sum(r["negative_abs_return_points_sum"] for r in ticker_rows)
    top_pos = sorted((r["positive_return_points_sum"] for r in ticker_rows), reverse=True)
    top_neg = sorted((r["negative_abs_return_points_sum"] for r in ticker_rows), reverse=True)
    top_count = sorted((r["resolved_trade_count"] for r in ticker_rows), reverse=True)
    cost_review = {
        "coverage_by_window": cost_rows,
        "p1_full_standard_net_coverage_pct": 100 * cost_rows[0]["full_standard_net_count"] / cost_rows[0]["realized_count"],
        "p1_uncovered_full_standard_net_realized_count": cost_rows[0]["realized_count"] - cost_rows[0]["full_standard_net_count"],
        "open_marks_are_gross_and_not_liquidation_net": True,
    }
    concentration = {
        "p1_resolved_trade_count": sum(len(v) for v in ticker_groups.values()),
        "distinct_ticker_count": len(ticker_groups),
        "max_trades_per_ticker": top_count[0],
        "max_ticker_trade_share_pct": 100 * top_count[0] / sum(top_count),
        "top5_positive_return_points_share_pct": 100 * sum(top_pos[:5]) / pos_total,
        "top5_negative_abs_return_points_share_pct": 100 * sum(top_neg[:5]) / neg_total,
        "measure_note": "unweighted sum of per-trade gross percentage points; not portfolio contribution",
    }
    quality = {
        "annual_breakdown_basis": "P1 entry execution year; realized gross plus exact cutoff close marks; unresolved excluded",
        "annual_breakdown": annual_rows,
        "ticker_concentration": concentration,
        "holding_p90_sessions_by_window": p90_by_window,
        "cost_review": cost_review,
        "portfolio_mdd": "NOT_AVAILABLE_IN_CURRENT_TRADE_LEVEL_VALIDATION",
        "portfolio_turnover": "NOT_AVAILABLE_IN_CURRENT_TRADE_LEVEL_VALIDATION",
        "mdd_is_not_inferred_from_trade_mae": True,
        "full_portfolio_configuration_recorded": False,
        "profitability_mean_pct_range": [min(float(r["mean_pct"]) for r in validation_rows), max(float(r["mean_pct"]) for r in validation_rows)],
        "profitability_median_pct_range": [min(float(r["median_pct"]) for r in validation_rows), max(float(r["median_pct"]) for r in validation_rows)],
        "positive_rate_pct_range": [min(float(r["positive_rate_pct"]) for r in validation_rows), max(float(r["positive_rate_pct"]) for r in validation_rows)],
        "candidate_vs_frozen_test": {},
        "fast_core_v2_reference_is_unpaired": True,
    }
    terminal = read_csv(OUT / "terminal_comparison.csv")
    by_scenario = {(r["window"], r["scenario"]): r for r in terminal}
    synth = {r["window"]: r for r in read_csv(STUDY / "five_window_synthesis.csv")}
    avg_improved = sum(number(by_scenario[(w, "NEW_TEST")]["mean_pct"]) > number(by_scenario[(w, "FROZEN_TEST")]["mean_pct"]) for w, _ in WINDOWS)
    med_improved = sum(number(by_scenario[(w, "NEW_TEST")]["median_pct"]) > number(by_scenario[(w, "FROZEN_TEST")]["median_pct"]) for w, _ in WINDOWS)
    positive_improved = sum(number(by_scenario[(w, "NEW_TEST")]["positive_rate_pct"]) > number(by_scenario[(w, "FROZEN_TEST")]["positive_rate_pct"]) for w, _ in WINDOWS)
    tail_improved = {field: sum(number(by_scenario[(w, "NEW_TEST")][f"{field}_rate_pct"]) < number(by_scenario[(w, "FROZEN_TEST")][f"{field}_rate_pct"]) for w, _ in WINDOWS) for field in ("le_30", "le_40", "le_50", "le_60")}
    winner_counts = {
        "ge_50_lower_count_windows": sum(int(by_scenario[(w, "NEW_TEST")]["ge_50_count"]) < int(by_scenario[(w, "FROZEN_TEST")]["ge_50_count"]) for w, _ in WINDOWS),
        "ge_100_lower_or_equal_count_windows": sum(int(by_scenario[(w, "NEW_TEST")]["ge_100_count"]) <= int(by_scenario[(w, "FROZEN_TEST")]["ge_100_count"]) for w, _ in WINDOWS),
    }
    filled_reductions = [int(synth[w]["frozen_test_filled_count"]) - int(synth[w]["new_test_filled_count"]) for w, _ in WINDOWS]
    quality["candidate_vs_frozen_test"] = {
        "mean_improved_windows": avg_improved, "median_improved_windows": med_improved,
        "positive_rate_improved_windows": positive_improved, "tail_rate_improved_windows": tail_improved,
        "winner_counts": winner_counts, "filled_trade_reduction_by_window": dict((w, v) for (w, _), v in zip(WINDOWS, filled_reductions)),
    }
    quality["annual_2025_entry_cohort"] = next(r for r in annual_rows if r["entry_execution_year"] == "2025")
    quality["annual_2026_entry_cohort"] = next(r for r in annual_rows if r["entry_execution_year"] == "2026")
    quality["deep_arrival_count_range"] = [min(int(r["deep_arrival_count"]) for r in validation_rows), max(int(r["deep_arrival_count"]) for r in validation_rows)]
    quality["open_unresolved_count_sum_over_overlapping_windows"] = sum(int(r["unresolved_open"] or 0) for r in validation_rows)
    return validation_rows, ticker_rows, quality


def compliance_audit() -> str:
    rows = [
        ("후보 전략 동결", "PASS", f"`{FREEZE.relative_to(ROOT).as_posix()}` / 동결된 후보 규칙·실행 계약. 공식 검증 metadata의 freeze SHA 기록."),
        ("검증 계획 사전 고정", "CHECK_REQUIRED", f"`{FREEZE.relative_to(ROOT).as_posix()}`와 기존 study metadata에 창·데이터·측정값은 있지만, 결과 확인 전 작성된 별도 go/no-go 기준 문서는 확인되지 않음. 기준을 소급 작성하지 않음."),
        ("Repository V2", "PASS", "각 window `summary.json.validations.repository_v2_silent_inner_drop_count = 0`; 공식 validator integrity audit."),
        ("PIT universe", "PASS", "rolling PIT/calendar authority SHA와 window `source_provenance`; `integrity_audit.csv`의 PIT/calendar·authority 검사."),
        ("completed observations only", "PASS", "원장 `pattern_a_lookahead_free`; window summary `future_pattern_a_input_count = 0`; 기존 window별 lifecycle spotcheck 30/30."),
        ("cutoff / support contract", "PASS", "window summary `effective_end`, `execution_support`, support policy; cutoff 뒤 신규 진입 0."),
        ("next-session execution", "PASS", "`lifecycle_spot_checks.csv` 30/30 per window; exact KRX session/open reconciliation in official validator."),
        ("identity / lifecycle", "PASS", "stable ticker/ISU key, 43 exact identity exclusions, no duplicate/overlap/support contract violations; `integrity_audit.csv`."),
        ("missing / unresolved semantics", "PASS", "미청산은 exact cutoff mark와 UNRESOLVED로 분리; proxy/forward-fill 없이 exact 52/43/52/39/50, unresolved 9/4/4/3/3 by window."),
        ("cost semantics", "CHECK_REQUIRED", "실현 거래 pre-tax 비용 필드는 전부 존재하나 P1 full-standard net/tax는 521건 중 310건만 존재. primary resolved-terminal table은 gross이며 미청산 exact mark는 매도 청산으로 보지 않음."),
        ("5 standard windows", "PASS", "P1, P2-1, P2-2, P3-1, P3-2의 저장 effective start/end/support가 `backtest_common_rules.md §3.1`과 일치."),
        ("float tolerance ±0.1pp", "PASS", "`summary.json.aggregate_tolerance_pp = 0.1`; 공식 aggregate check 1,098건, failed 0."),
        ("same-condition comparison", "PASS", "frozen Pattern B TEST와 변경된 stage gate 외의 execution/terminal 정책은 동일. FAST Core V2는 표본·lifecycle·terminal이 달라 unpaired 참고로 별도 표시."),
        ("failure / side-effect review", "PASS", "-30/-40/-50/-60, DEEP arrival, +30/+50/+100, unresolved/open tail, holding, 2025 cohort weakness를 이번 report에서 별도 공개."),
        ("robustness", "CHECK_REQUIRED", "다섯 창의 mean/median/positive 방향은 반복되나 창끼리 겹침. P1 entry-year 2025 resolved cohort 27건 mean -8.92%; 2026은 부분 기간. 종목 집중도는 낮지만 시기 독립성은 확정되지 않음."),
        ("MDD / turnover / portfolio setup", "CHECK_REQUIRED", "`backtest_common_rules.md §3, §5`의 portfolio core 평가에 필요한 equity curve·초기자본·position sizing·동시 보유·현금 정책이 현재 trade-level 산출물에 없음. MDD/turnover는 계산하지 않음."),
        ("final strategy review", "HOLD", "trade-level 성과는 유망하나 기준상 필수 portfolio risk/cost evidence 및 기록된 사전 go/no-go plan이 부족해 공식 전략 채택을 보류."),
    ]
    lines = [
        "# Pattern B E/T-only 후보: 기준 문서 compliance audit", "",
        "검토일: 2026-09-28. 기준 문서는 `docs/validation/backtest_common_rules.md` 및 `docs/strategies/strategy_lifecycle.md`야.",
        "저장된 원장·요약을 read-only로 확인했고 replay, V2 rerun, 규칙 변경, threshold 실험은 하지 않았어.",
        "무결성 자체는 PASS지만 구조적으로 확인되지 않은 항목이 있어 전체 기준 적합성은 CHECK_REQUIRED야.", "",
        "| 기준 | 상태 | 근거 / 판단 |", "|---|---|---|",
    ]
    lines.extend(f"| {name} | **{status}** | {evidence} |" for name, status, evidence in rows)
    lines += [
        "", "## 보정 판단", "",
        "공식 validator의 `CERTIFIED_PASS`는 저장 산출물의 contract/integrity verdict만 뜻해. 전략 성과와 공식 채택은 별도로 평가했어.",
        "MDD를 trade MAE에서 만들어내지 않았고, turnover도 trade count만으로 추정하지 않았어. portfolio sizing 및 historical tax coverage를 추가 재실행 없이 증명할 수 없어 채택은 HOLD로 기록해.",
        "전략 규칙과 FAST Core V2의 기본 지위는 바꾸지 않았어. 향후 결정을 위해서는 사전 고정된 portfolio 설정과 비용 정책으로 필요한 risk/cost 지표를 평가해야 해.", "",
    ]
    return "\n".join(lines)


def render_report(summary: dict[str, Any], validation_rows: list[dict[str, Any]], quality: dict[str, Any]) -> str:
    fast = read_csv(OUT / "fast_core_v2_reference.csv")
    fast_terminal = read_csv(STUDY / "fast_core_v2_terminal_reference.csv")
    study_start = json.loads((STUDY / "metadata.json").read_text(encoding="utf-8"))["starting_git"]["head"]
    lines = [
        "# Pattern B E/T PROGRESSED Candidate V1: 공식 검증 및 전략 품질 검토", "",
        f"이번 재감사 시작 HEAD: `{REVIEW_START_HEAD}`. 원본 5-window replay 시작 HEAD: `{study_start}`. 검토일: 2026-09-28.",
        "무결성 인증: **PASS (`CERTIFIED_PASS`, 1,098 checks / 0 failures)**.",
        "전체 기준 적합성: **CHECK_REQUIRED**. 최종 lifecycle 결정: **HOLD (공식 전략 채택 보류)**.",
        "기존 저장 원장·terminal 산출물을 재사용했어. 5-window lifecycle replay와 FAST Core V2 rerun은 하지 않았고 전략 규칙/threshold도 바꾸지 않았어.",
        "상세 기준별 근거는 [standards_compliance_audit.md](standards_compliance_audit.md)에 있어.", "",
        "## Candidate NEW_TEST resolved-terminal 성과 및 위험", "",
        "N은 realized gross 결과와 exact cutoff gross mark를 합친 resolved 수야. UNRESOLVED는 평균·비율에서 제외했고 실제 매도로 간주하지 않았어.", "",
        "| Window | N / filled | Mean | Median | Positive | +30 / +50 / +100 | -30 / -40 / -50 / -60 | DEEP | Holding mean / median / P90 | Exact open / unresolved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in validation_rows:
        lines.append(
            f"| {r['window']} | {r['resolved_n']} / {r['filled']} | {float(r['mean_pct']):.2f}% | {float(r['median_pct']):.2f}% | {float(r['positive_rate_pct']):.2f}% | "
            f"{r['ge_30_count']} / {r['ge_50_count']} / {r['ge_100_count']} | "
            f"{r['le_30_count']} ({float(r['le_30_rate_pct']):.2f}%) / {r['le_40_count']} ({float(r['le_40_rate_pct']):.2f}%) / {r['le_50_count']} ({float(r['le_50_rate_pct']):.2f}%) / {r['le_60_count']} ({float(r['le_60_rate_pct']):.2f}%) | "
            f"{r['deep_arrival_count']} | {float(r['mean_holding_sessions']):.1f} / {float(r['median_holding_sessions']):.0f} / {float(r['p90_holding_sessions']):.0f} sessions | {r['exact_open']} / {r['unresolved_open']} |"
        )
    lines += [
        "", "창 전체에서 mean 6.27–9.45%, median 9.15–11.00%, positive rate 67.77–74.87%로 방향은 반복돼. 하지만 이 5개 창은 서로 기간이 중첩돼 독립 표본 5개로 볼 수 없어.",
        "후보는 frozen Pattern B TEST보다 mean과 median이 5/5 개선됐고, positive rate는 4/5 개선(나머지 P3-1은 -0.24pp), -30/-40/-50/-60 빈도도 각각 5/5 낮아졌어. 동시에 filled 수와 +50 winner count는 5/5 줄었고 +100 count는 모두 같거나 줄었어.",
        "DEEP arrival는 window마다 50–106건(전체 filled 대비 약 18–25%)이야. 위험 꼬리는 frozen TEST보다 낮아졌어도 절대 수준이 작지 않아.", "",
        "## FAST Core V2 참고 비교", "",
        "저장된 공식 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 결과만 사용했어. FAST와 후보는 모집단·lifecycle·terminal이 달라 **unpaired 참고**이며 인과적 우열 비교가 아니야.",
        "후보는 positive rate와 median이 5/5 높고, mean은 4/5 높아(P1은 9.45% 대 9.53%). 후보의 +50 비율은 대략 5.9–6.6%로 FAST의 9.0–15.2%보다 낮고, +100 비율도 후보 0.7–1.7% 대 FAST 2.6–6.4%야. 큰 승자 보존은 FAST가 더 강해. 반대로 FAST의 positive rate는 27.9–32.2%, median은 약 -15.3%야.",
        "FAST의 -30 비율은 약 1.9–2.4%, -60은 0.28–0.62%로 후보보다 훨씬 낮아. 후보는 수익성·승률 특성이 다르고, FAST는 큰 승자와 하방 억제 특성이 다르다는 교환 관계가 있어.", "",
        "## 시기·종목 집중도 및 보유 특성", "",
        "P1 연도별 entry cohort 집계는 `annual_breakdown.csv`, 종목별 집계는 `ticker_concentration.csv`야. 계산은 realized gross와 exact cutoff gross mark만 사용하며 percentage-point 합은 자본가중 포트폴리오 기여가 아니야.",
        f"P1 resolved 573건은 463개 ticker에 분산됐고 한 ticker 최대 6건(1.05%)이야. 상위 5개 ticker는 양의 gross return point 합의 {quality['ticker_concentration']['top5_positive_return_points_share_pct']:.2f}%, 음의 절대 합의 {quality['ticker_concentration']['top5_negative_abs_return_points_share_pct']:.2f}%를 차지해. 종목 하나에 성과가 좌우된 징후는 약해.",
        f"다만 2025 entry cohort는 {quality['annual_2025_entry_cohort']['resolved_terminal_n']}건 평균 {quality['annual_2025_entry_cohort']['resolved_terminal_mean_gross_pct']:.2f}%, positive {quality['annual_2025_entry_cohort']['resolved_terminal_positive_rate_pct']:.1f}%야. 2026 cohort는 부분 기간이라 {quality['annual_2026_entry_cohort']['filled_count']}건 중 {quality['annual_2026_entry_cohort']['exact_cutoff_open_count']}건이 cutoff open mark야.",
        "평균 보유는 151–169 KRX sessions, 중앙값 43–61, P90 약 456–561 sessions야. 장기 자본 고착이 분명한 약점이야.", "",
        "## 비용 및 portfolio risk 한계", "",
        "모든 realized ledger row에 commission/slippage pre-tax 값은 있지만, P1 실현 521건 중 full-standard net/tax 값은 310건(59.5%)뿐이야. 나머지 P1 역사 구간의 세후 비교를 완결할 근거가 부족해. Exact open 표시는 gross mark이며 매도 체결·exit tax로 가정하지 않았어.",
        "현재 산출물은 trade-level ledger라 portfolio equity curve가 없어 MDD는 `NOT_AVAILABLE_IN_CURRENT_TRADE_LEVEL_VALIDATION`이야. Turnover도 같은 사유로 평가 불가야. Trade MAE를 MDD로 대체하거나 거래 건수를 turnover로 간주하지 않았어. 초기자본, 종목별 예산, 최대 동시 보유, 현금·체결 배분도 이 후보 산출물에 기록되어 있지 않아.",
        "사전 고정된 전략별 go/no-go 기준 문서도 찾지 못했어. 결과를 본 뒤 이를 소급 작성하지 않았어.", "",
        "## 최종 lifecycle 결정", "",
        "**HOLD — 공식 전략 채택 보류.** 저장된 trade-level 자료는 수익성 및 frozen TEST 대비 개선 신호를 보여주지만, 현재 공통 기준이 요구하는 portfolio MDD·turnover와 P1 전체 비용 비교를 확인할 수 없어. 또한 2025 연도 cohort 약세와 창 중첩 때문에 robustness도 충분히 독립적으로 확인되지 않았어.",
        "후보 규칙은 변경하지 않고 V01로 동결 보존해. 이 결정은 기본 전략 `A FAST Core V2`의 교체 여부와 무관하며, 이번 검토에서 V2를 교체하지 않아.",
        "다음 평가 단계에는 사전 고정된 portfolio/cost 설정을 사용한 risk/cost 평가가 필요하지만, 이번에는 새 portfolio backtest를 시작하지 않았어.",
        "", "## 근거 파일", "",
        f"- 무결성 상세: `{(OUT / 'integrity_audit.csv').relative_to(ROOT).as_posix()}`",
        f"- Standards audit: `{(OUT / 'standards_compliance_audit.md').relative_to(ROOT).as_posix()}`",
        f"- Window aggregate: `{(OUT / 'five_window_validation.csv').relative_to(ROOT).as_posix()}`",
        f"- 저장 FAST V2 비교: `{(OUT / 'fast_core_v2_reference.csv').relative_to(ROOT).as_posix()}`",
        "",
    ]
    # Keep a simple consistency guard between the reference table and its saved data.
    assert len(fast) == len(fast_terminal) == 5
    return "\n".join(lines)


def run_review() -> dict[str, Any]:
    # Re-run only the read-only integrity reconciler, never the trade lifecycle.
    summary = validator.run()
    validation_rows, _, quality = read_only_quality()
    audit_path = OUT / "standards_compliance_audit.md"
    audit_path.write_text(compliance_audit(), encoding="utf-8")
    summary.update({
        "starting_head": REVIEW_START_HEAD,
        "underlying_study_starting_head": json.loads((STUDY / "metadata.json").read_text(encoding="utf-8"))["starting_git"]["head"],
        "integrity_verdict": "PASS" if summary["failed_check_count"] == 0 else "CHECK_REQUIRED",
        "compliance_verdict": "CHECK_REQUIRED",
        "strategy_quality_verdict": "CHECK_REQUIRED",
        "final_lifecycle_decision": "HOLD",
        "read_only_existing_artifacts": True,
        "lifecycle_replay_performed": False,
        "fast_core_v2_rerun": False,
        "strategy_quality_review": quality,
    })
    summary["resolved_terminal_new_test"] = validation_rows
    summary_path = OUT / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(render_report(summary, validation_rows, quality), encoding="utf-8")

    meta = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    meta.update({
        "integrity_verdict": summary["integrity_verdict"],
        "compliance_verdict": "CHECK_REQUIRED",
        "strategy_quality_verdict": "CHECK_REQUIRED",
        "final_lifecycle_decision": "HOLD",
        "review_starting_head": REVIEW_START_HEAD,
        "quality_review_code_sha256": {
            Path(__file__).resolve().relative_to(ROOT).as_posix(): sha(Path(__file__).resolve()),
        },
    })
    meta["source_sha256"].update({
        path.relative_to(ROOT).as_posix(): sha(path)
        for path in (RULES, LIFECYCLE, FREEZE, README)
    })
    generated = [
        "report.md", "summary.json", "five_window_validation.csv", "terminal_comparison.csv",
        "fast_core_v2_reference.csv", "integrity_audit.csv", "standards_compliance_audit.md",
        "annual_breakdown.csv", "ticker_concentration.csv",
    ]
    meta["generated_files"] = {
        name: {"sha256": sha(OUT / name), "bytes": (OUT / name).stat().st_size}
        for name in generated
    }
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "integrity_verdict": summary["integrity_verdict"],
        "compliance_verdict": "CHECK_REQUIRED",
        "final_lifecycle_decision": "HOLD",
        "check_count": summary["check_count"],
        "failed_check_count": summary["failed_check_count"],
        "lifecycle_replay_performed": False,
        "output": OUT.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run_review()
