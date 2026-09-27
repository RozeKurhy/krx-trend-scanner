#!/usr/bin/env python3
"""Run the frozen Pattern B weak-origin filter over standard P2/P3 windows."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as runner  # noqa: E402

START_COMMIT = "2104d12675b18bea269d02e40a0b3a8864a104b9"
P1_REFERENCE_VERDICT = "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED"
P1_REFERENCE_ROOT = Path("artifacts/patterns/pattern_b/progressed_weak_exclusion_p1_simple_v01")
OUTPUT_ROOT = runner.ROBUSTNESS_OUTPUT_RELATIVE
WINDOW_IDS = ("P2-1", "P2-2", "P3-1", "P3-2")
SCRIPT_RELATIVE = Path("scripts/run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01.py")
TEST_RELATIVE = Path("tests/test_run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01.py")
P1_RUNNER_TEST = Path("tests/test_run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py")
ALLOWED_PATHS = (
    "scripts/run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01.py",
    "tests/test_run_pattern_b_progressed_weak_exclusion_p2_p3_4window_v01.py",
)
P1_REFERENCE_FILES = (
    P1_REFERENCE_ROOT / "metadata.json",
    P1_REFERENCE_ROOT / "summary.json",
    P1_REFERENCE_ROOT / "control_trade_ledger.csv",
    P1_REFERENCE_ROOT / "test_trade_ledger.csv",
    P1_REFERENCE_ROOT / "control_open_positions.csv",
    P1_REFERENCE_ROOT / "test_open_positions.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_p1_reference(data_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_root = data_root / P1_REFERENCE_ROOT
    metadata = _json(artifact_root / "metadata.json")
    summary = _json(artifact_root / "summary.json")
    if summary.get("study_id") != "PATTERN_B_PROGRESSED_WEAK_FILTER_P1_SIMPLE_V01":
        raise RuntimeError("frozen P1 artifact has an unexpected study id")
    if summary.get("verdict") != P1_REFERENCE_VERDICT:
        raise RuntimeError("frozen P1 verdict differs from the four-window instruction")
    if summary.get("window", {}).get("window_id") != "P1":
        raise RuntimeError("frozen reference is not the standard P1 result")
    for relative, detail in metadata.get("generated_files", {}).items():
        path = artifact_root / relative
        if not path.is_file() or _sha256(path) != detail.get("sha256"):
            raise RuntimeError(f"frozen P1 generated artifact hash mismatch: {relative}")
        if runner._git_blob_sha(data_root, START_COMMIT, P1_REFERENCE_ROOT / relative) != _sha256(path):
            raise RuntimeError(f"frozen P1 generated artifact differs from reference commit: {relative}")
    for relative in (P1_REFERENCE_ROOT / "metadata.json",):
        if runner._git_blob_sha(data_root, START_COMMIT, relative) != _sha256(data_root / relative):
            raise RuntimeError(f"frozen P1 metadata differs from reference commit: {relative}")
    for relative, expected in metadata.get("source_sha256", {}).items():
        if _sha256(data_root / relative) != expected:
            raise RuntimeError(f"current source no longer matches frozen P1 provenance: {relative}")
    for relative, expected in metadata.get("code_sha256", {}).items():
        if runner._git_blob_sha(data_root, START_COMMIT, Path(relative)) != expected:
            raise RuntimeError(f"frozen P1 code hash does not match reference commit: {relative}")
    return metadata, summary


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _terminal_stats(data_root: Path, directory: Path) -> dict[str, Any]:
    control_trades = pd.read_csv(data_root / directory / "control_trade_ledger.csv")
    test_trades = pd.read_csv(data_root / directory / "test_trade_ledger.csv")
    control_open = pd.read_csv(data_root / directory / "control_open_positions.csv")
    test_open = pd.read_csv(data_root / directory / "test_open_positions.csv")

    def resolve(trades: pd.DataFrame, opened: pd.DataFrame) -> dict[str, Any]:
        realized_rows = trades.loc[trades["trade_status"].astype(str).eq("REALIZED"), "gross_return_pct"]
        realized_all = pd.to_numeric(realized_rows, errors="coerce")
        if realized_all.isna().any():
            raise RuntimeError("resolved-terminal has a realized trade without an exact gross return")
        realized = realized_all.dropna()
        exact = opened.loc[
            opened.get("valuation_status", pd.Series(index=opened.index, dtype="object"))
            .astype(str).eq("MARKED_EXACT_CUTOFF_CLOSE")
        ]
        exact_all = pd.to_numeric(exact["mark_to_cutoff_gross_return_pct"], errors="coerce")
        if exact_all.isna().any():
            raise RuntimeError("resolved-terminal exact open mark is missing its gross return")
        open_values = exact_all.dropna()
        values = pd.concat([realized, open_values], ignore_index=True)
        valuation_status = opened.get("valuation_status", pd.Series(index=opened.index, dtype="object")).astype(str)
        unresolved = int(valuation_status.eq("UNRESOLVED").sum())
        if len(exact) + unresolved != len(opened):
            raise RuntimeError("resolved-terminal open positions are not partitioned into exact and unresolved marks")
        if values.empty:
            result: dict[str, Any] = {"resolved_terminal_n": 0, "mean_pct": None, "median_pct": None, "positive_rate_pct": None}
        else:
            result = {
                "resolved_terminal_n": int(len(values)),
                "mean_pct": float(values.mean()),
                "median_pct": float(values.median()),
                "positive_rate_pct": float((values > 0).mean() * 100.0),
            }
        for label, predicate in (
            ("ge_30", values.ge(30)), ("ge_50", values.ge(50)), ("ge_100", values.ge(100)),
            ("le_30", values.le(-30)), ("le_40", values.le(-40)),
            ("le_50", values.le(-50)), ("le_60", values.le(-60)),
        ):
            result[f"{label}_count"] = int(predicate.sum())
            result[f"{label}_rate_pct"] = float(predicate.mean() * 100.0) if len(values) else None
        result["exact_open_mark_count"] = int(len(open_values))
        result["unresolved_open_count"] = unresolved
        return result

    return {
        "control": resolve(control_trades, control_open),
        "test": resolve(test_trades, test_open),
    }


def _terminal_row(window_id: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"window": window_id}
    for scenario in ("control", "test"):
        for key, value in stats[scenario].items():
            row[f"{scenario}_{key}"] = value
    return row


def _window_synthesis_row(window_id: str, summary: Mapping[str, Any]) -> dict[str, Any]:
    control = summary["control_summary"]["realized_gross"]
    test = summary["test_summary"]["realized_gross"]
    control_deep = summary["control_summary"]["deep_cohort"]["deep_arrival_rate_of_filled_pct"]
    test_deep = summary["test_summary"]["deep_cohort"]["deep_arrival_rate_of_filled_pct"]
    rubric = summary["rubric"]
    return {
        "window": window_id,
        "test_realized_mean_pct": test["mean_pct"],
        "test_minus_control_mean_pp": test["mean_pct"] - control["mean_pct"],
        "test_win_rate_pct": test["win_rate_pct"],
        "test_minus_control_win_rate_pp": test["win_rate_pct"] - control["win_rate_pct"],
        "test_realized_median_pct": test["median_pct"],
        "test_minus_control_median_pp": test["median_pct"] - control["median_pct"],
        "control_realized_mean_pct": control["mean_pct"],
        "control_win_rate_pct": control["win_rate_pct"],
        "control_realized_median_pct": control["median_pct"],
        "control_minus_test_le_30_pp": control["le_30_rate_pct"] - test["le_30_rate_pct"],
        "control_minus_test_le_50_pp": control["le_50_rate_pct"] - test["le_50_rate_pct"],
        "control_minus_test_deep_arrival_pp": control_deep - test_deep,
        "control_le_30_rate_pct": control["le_30_rate_pct"],
        "test_le_30_rate_pct": test["le_30_rate_pct"],
        "control_le_50_rate_pct": control["le_50_rate_pct"],
        "test_le_50_rate_pct": test["le_50_rate_pct"],
        "control_deep_arrival_rate_pct": control_deep,
        "test_deep_arrival_rate_pct": test_deep,
        "control_filled": summary["control_summary"]["filled_count"],
        "control_realized": summary["control_summary"]["realized_count"],
        "control_open": summary["control_summary"]["open_count"],
        "test_filled": summary["test_summary"]["filled_count"],
        "test_realized": summary["test_summary"]["realized_count"],
        "test_open": summary["test_summary"]["open_count"],
        "verdict": summary["verdict"],
        "quality_all_nonworse": rubric["quality_all_nonworse"],
        "risk_metrics_improved_count": rubric["risk_metrics_improved_count"],
        "risk_improved_entry_years": json.dumps(rubric["risk_improved_entry_years"]),
    }


def _format(value: Any, suffix: str = "", places: int = 2) -> str:
    number = _num(value)
    return "—" if number is None else f"{number:.{places}f}{suffix}"


def _root_report(
    p1_summary: Mapping[str, Any],
    window_summaries: Mapping[str, Mapping[str, Any]],
    synthesis: pd.DataFrame,
    terminal: pd.DataFrame,
) -> str:
    lines = [
        "# Pattern B + PROGRESSED 이전 WEAK 제외 P2/P3 4-Window Robustness V01",
        "",
        "P1은 commit `2104d12675b18bea269d02e40a0b3a8864a104b9`의 frozen 결과를 그대로 읽었고, 재실행하지 않았어. P2-1/P2-2/P3-1/P3-2는 P1의 동일한 CONTROL/TEST 정의와 독립 lifecycle replay를 적용했어.",
        "",
        "## 5-Window 핵심 지표",
        "",
        "평균, 승률, 중앙값 순서야. Δ는 TEST−CONTROL percentage point고, tail/DEEP Δ는 CONTROL−TEST라 양수면 TEST 위험률이 낮아.",
        "",
        "| Window | TEST 평균 | 평균 Δ | TEST 승률 | 승률 Δ | TEST 중앙 | 중앙 Δ | -30 Δ | -50 Δ | DEEP Δ | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in synthesis.to_dict("records"):
        lines.append(
            f"| {row['window']} | {_format(row['test_realized_mean_pct'], '%')} | {_format(row['test_minus_control_mean_pp'], 'pp')} | "
            f"{_format(row['test_win_rate_pct'], '%')} | {_format(row['test_minus_control_win_rate_pp'], 'pp')} | "
            f"{_format(row['test_realized_median_pct'], '%')} | {_format(row['test_minus_control_median_pp'], 'pp')} | "
            f"{_format(row['control_minus_test_le_30_pp'], 'pp')} | {_format(row['control_minus_test_le_50_pp'], 'pp')} | "
            f"{_format(row['control_minus_test_deep_arrival_pp'], 'pp')} | `{row['verdict']}` |"
        )
    lines += [
        "",
        "평균 수익률은 verdict와 별도로 우선 지표로 표시했어. 단일 종합 점수는 만들지 않았어.",
        "",
        "## Resolved-terminal 보조 sensitivity",
        "",
        "실현 gross terminal과 cutoff exact close mark를 합쳤어. unresolved open은 합산에서 제외하고 건수를 분리했어.",
        "",
        "| Window | CONTROL mean / median / positive | TEST mean / median / positive | Resolved N C/T | Exact open C/T | unresolved open C/T |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in terminal.to_dict("records"):
        lines.append(
            f"| {row['window']} | {_format(row['control_mean_pct'], '%')} / {_format(row['control_median_pct'], '%')} / {_format(row['control_positive_rate_pct'], '%')} | "
            f"{_format(row['test_mean_pct'], '%')} / {_format(row['test_median_pct'], '%')} / {_format(row['test_positive_rate_pct'], '%')} | "
            f"{row['control_resolved_terminal_n']} / {row['test_resolved_terminal_n']} | "
            f"{row['control_exact_open_mark_count']} / {row['test_exact_open_mark_count']} | "
            f"{row['control_unresolved_open_count']} / {row['test_unresolved_open_count']} |"
        )
    lines += [
        "",
        "Resolved-terminal tail sensitivity는 exact close mark 가능한 open과 실현 거래를 합친 분모 기준이야. 셀은 CONTROL / TEST 순서로 rate와 count를 함께 표시해.",
        "",
        "| Window | +30 | +50 | +100 | -30 | -40 | -50 | -60 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in terminal.to_dict("records"):
        cells = []
        for threshold in ("ge_30", "ge_50", "ge_100", "le_30", "le_40", "le_50", "le_60"):
            cells.append(
                f"{_format(row[f'control_{threshold}_rate_pct'], '%')} ({row[f'control_{threshold}_count']}) / "
                f"{_format(row[f'test_{threshold}_rate_pct'], '%')} ({row[f'test_{threshold}_count']})"
            )
        lines.append(f"| {row['window']} | " + " | ".join(cells) + " |")
    p1 = synthesis.loc[synthesis["window"] == "P1"].iloc[0]
    all_windows = synthesis
    p2p3 = synthesis.loc[synthesis["window"] != "P1"]
    repeat_mean_better = int((p2p3["test_minus_control_mean_pp"] > 0).sum())
    repeat_win_better = int((p2p3["test_minus_control_win_rate_pp"] > 0).sum())
    repeat_median_better = int((p2p3["test_minus_control_median_pp"] > 0).sum())
    mean_better_5 = int((all_windows["test_minus_control_mean_pp"] > 0).sum())
    win_better_5 = int((all_windows["test_minus_control_win_rate_pp"] > 0).sum())
    median_better_5 = int((all_windows["test_minus_control_median_pp"] > 0).sum())
    le30_better = int((p2p3["control_minus_test_le_30_pp"] >= 0.1 - 1e-9).sum())
    le50_better = int((p2p3["control_minus_test_le_50_pp"] >= 0.1 - 1e-9).sum())
    deep_better = int((p2p3["control_minus_test_deep_arrival_pp"] >= 0.1 - 1e-9).sum())
    lines += [
        "",
        "## 5-Window 질문 답변",
        "",
        f"1. P1의 평균/승률/중앙 개선 방향이 P2/P3에서 반복됐는지: P1 Δ는 평균 `{_format(p1['test_minus_control_mean_pp'], 'pp')}`, 승률 `{_format(p1['test_minus_control_win_rate_pp'], 'pp')}`, 중앙 `{_format(p1['test_minus_control_median_pp'], 'pp')}`야. P2/P3에서는 각각 `{repeat_mean_better}/4`, `{repeat_win_better}/4`, `{repeat_median_better}/4`개 window에서 TEST가 CONTROL보다 높았어.",
        f"2. 전체 5개 window 중 TEST 평균이 개선된 window는 `{mean_better_5}/5`야.",
        f"3. 전체 5개 window 중 승률 개선은 `{win_better_5}/5`야.",
        f"4. 전체 5개 window 중 중앙값 개선은 `{median_better_5}/5`야.",
        f"5. P2/P3 tail 재현성(각 위험률 0.1pp 이상 감소)은 -30 `{le30_better}/4`, -50 `{le50_better}/4`, DEEP `{deep_better}/4` window야. P1에서의 대응 delta는 -30 `{_format(p1['control_minus_test_le_30_pp'], 'pp')}`, -50 `{_format(p1['control_minus_test_le_50_pp'], 'pp')}`, DEEP `{_format(p1['control_minus_test_deep_arrival_pp'], 'pp')}`야.",
        "6. P2-1/P3-1은 2025-05 고정 종료, P2-2/P3-2는 2026-08 full 종료라 각 pair에서 판정과 mean/win/median/tail delta를 나눠서 아래에 적었어.",
        "",
        "| 고정/전체 pair | 고정 verdict | 전체 verdict | mean Δ 고정→전체 | win Δ 고정→전체 | median Δ 고정→전체 | -30 Δ | -50 Δ | DEEP Δ |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    by_window = {row["window"]: row for row in synthesis.to_dict("records")}
    for fixed, full in (("P2-1", "P2-2"), ("P3-1", "P3-2")):
        fixed_row, full_row = by_window[fixed], by_window[full]
        lines.append(
            f"| {fixed} → {full} | `{fixed_row['verdict']}` | `{full_row['verdict']}` | "
            f"{_format(fixed_row['test_minus_control_mean_pp'], 'pp')} → {_format(full_row['test_minus_control_mean_pp'], 'pp')} | "
            f"{_format(fixed_row['test_minus_control_win_rate_pp'], 'pp')} → {_format(full_row['test_minus_control_win_rate_pp'], 'pp')} | "
            f"{_format(fixed_row['test_minus_control_median_pp'], 'pp')} → {_format(full_row['test_minus_control_median_pp'], 'pp')} | "
            f"{_format(fixed_row['control_minus_test_le_30_pp'], 'pp')} → {_format(full_row['control_minus_test_le_30_pp'], 'pp')} | "
            f"{_format(fixed_row['control_minus_test_le_50_pp'], 'pp')} → {_format(full_row['control_minus_test_le_50_pp'], 'pp')} | "
            f"{_format(fixed_row['control_minus_test_deep_arrival_pp'], 'pp')} → {_format(full_row['control_minus_test_deep_arrival_pp'], 'pp')} |"
        )
    improved_names = synthesis.loc[synthesis["verdict"].astype(str).str.endswith("_IMPROVED"), "window"].tolist()
    improved_robustness = int(p2p3["verdict"].astype(str).str.endswith("_IMPROVED").sum())
    mixed_robustness = int(p2p3["verdict"].astype(str).str.endswith("_MIXED").sum())
    no_benefit_robustness = int(p2p3["verdict"].astype(str).str.endswith("_NO_BENEFIT").sum())
    if improved_robustness >= 2:
        next_stage_judgment = "P1 외에도 여러 창에서 사전 규칙상 개선이 반복돼 다음 연구 단계 후보로 유지할 근거가 있어. 다만 이 결과만으로 전략 채택/production 승격을 뜻하지 않아."
    elif improved_robustness == 1:
        next_stage_judgment = "P1 외 개선 판정이 한 창뿐이라 재현 근거는 제한적이야. 다음 연구에서는 탐색적 가설로만 유지하고, 추가 독립 구간 증거 전에는 우선순위를 낮게 두는 게 맞아."
    else:
        next_stage_judgment = "P2/P3에서 개선 판정이 없어 P1 결과의 재현 근거가 부족해. 현 단계에서 다음 연구 우선 후보로 유지할 근거는 충분하지 않아."
    lines += [
        "",
        f"7. 다음 연구 단계 유지 근거: 5개 중 improved `{len(improved_names)}`개 (`{', '.join(improved_names) if improved_names else '없음'}`); P2/P3만 보면 improved/mixed/no-benefit `{improved_robustness}/{mixed_robustness}/{no_benefit_robustness}`야. {next_stage_judgment}",
        "",
        "## Window별 상세 산출물",
        "",
        "각 하위 폴더에 CONTROL/TEST 원장, open positions, filter audit, WEAK 직접효과, DEEP/연도 비교, 30건 lifecycle 검수, metadata/provenance가 있어. P1 frozen summary는 `summary.json`과 `frozen_p1_reference`에 기록했어.",
        "",
    ]
    for window_id in WINDOW_IDS:
        lines.append(f"- `{window_id}`: verdict `{window_summaries[window_id]['verdict']}`; `{window_id.lower().replace('-', '_')}/report.md`.")
    lines += [
        "",
        "P1 frozen verdict: `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED`.",
        "",
    ]
    return "\n".join(lines)


def _verify_window_output(directory: Path) -> dict[str, Any]:
    metadata = _json(directory / "metadata.json")
    summary = _json(directory / "summary.json")
    for filename, detail in metadata.get("generated_files", {}).items():
        path = directory / filename
        if not path.is_file() or _sha256(path) != detail.get("sha256"):
            raise RuntimeError(f"window generated artifact hash mismatch: {path}")
    validations = summary["validations"]
    required_zero = (
        "raw_candidate_key_mismatch_count", "future_pattern_a_input_count",
        "test_weak_origin_pass_count", "entry_after_window_end_count",
        "control_overlap_count", "test_overlap_count", "repository_v2_silent_inner_drop_count",
    )
    nonzero = {key: validations.get(key) for key in required_zero if validations.get(key) != 0}
    if nonzero:
        raise RuntimeError(f"window required-zero validation failed: {nonzero}")
    if validations.get("lifecycle_spot_check_pass_count", 0) < 20:
        raise RuntimeError("window has fewer than 20 passing lifecycle spot checks")
    return summary


def run(data_root: Path = ROOT) -> dict[str, Any]:
    data_root = Path(data_root).resolve()
    starting_git = runner._assert_git_start(
        data_root,
        expected_head=START_COMMIT,
        allowed_paths=ALLOWED_PATHS,
        output_root=OUTPUT_ROOT,
        current_output_dir=data_root / OUTPUT_ROOT,
    )
    p1_metadata, p1_summary = _verify_p1_reference(data_root)
    if (p1_summary.get("verdict") or "") != P1_REFERENCE_VERDICT:
        raise RuntimeError("P1 frozen reference verdict changed after verification")

    resolved_windows = {window_id: runner._resolve_window(data_root, window_id) for window_id in WINDOW_IDS}
    frozen_paths = list(P1_REFERENCE_FILES)
    code_paths = [SCRIPT_RELATIVE, TEST_RELATIVE]
    window_summaries: dict[str, dict[str, Any]] = {}
    window_directories: dict[str, Path] = {}
    for window_id in WINDOW_IDS:
        _, window = resolved_windows[window_id]
        window_directory = OUTPUT_ROOT / window_id.lower().replace("-", "_")
        window_directories[window_id] = window_directory
        summary = runner.run(
            data_root=data_root,
            output_dir=data_root / window_directory,
            window_id=window_id,
            expected_head=START_COMMIT,
            allowed_paths=ALLOWED_PATHS,
            output_root=OUTPUT_ROOT,
            additional_code_paths=code_paths,
            additional_source_paths=frozen_paths,
            print_summary=False,
        )
        verified = _verify_window_output(data_root / window_directory)
        window_summaries[window_id] = verified
        print(json.dumps({
            "window": window_id,
            "range": [window["effective_start"], window["effective_end"]],
            "execution_support": window["execution_support"],
            "verdict": verified["verdict"],
            "control": {key: verified["control_summary"]["realized_gross"].get(key) for key in ("mean_pct", "win_rate_pct", "median_pct")},
            "test": {key: verified["test_summary"]["realized_gross"].get(key) for key in ("mean_pct", "win_rate_pct", "median_pct")},
            "output": str(data_root / window_directory),
        }, ensure_ascii=False, allow_nan=False), flush=True)

    frozen_summary = p1_summary
    all_summaries: dict[str, Mapping[str, Any]] = {"P1": frozen_summary, **window_summaries}
    synthesis_rows = [_window_synthesis_row(window_id, all_summaries[window_id]) for window_id in ("P1", *WINDOW_IDS)]
    synthesis = pd.DataFrame(synthesis_rows)
    terminal_rows = []
    p1_terminal = _terminal_stats(data_root, P1_REFERENCE_ROOT)
    terminal_rows.append(_terminal_row("P1", p1_terminal))
    for window_id in WINDOW_IDS:
        terminal_rows.append(_terminal_row(window_id, _terminal_stats(data_root, window_directories[window_id])))
    terminal = pd.DataFrame(terminal_rows)

    root = data_root / OUTPUT_ROOT
    generated: dict[str, pd.DataFrame] = {
        "five_window_synthesis.csv": synthesis,
        "resolved_terminal_synthesis.csv": terminal,
    }
    for filename, frame in generated.items():
        frame.to_csv(root / filename, index=False, encoding="utf-8")
    report = _root_report(p1_summary, window_summaries, synthesis, terminal)
    (root / "report.md").write_text(report, encoding="utf-8")

    summary = {
        "study_id": "PATTERN_B_PROGRESSED_WEAK_FILTER_P2_P3_4WINDOW_V01",
        "starting_git": starting_git,
        "frozen_p1_reference": {
            "commit": START_COMMIT,
            "artifact_root": str(P1_REFERENCE_ROOT),
            "verdict": p1_summary["verdict"],
            "metadata_sha256": _sha256(data_root / P1_REFERENCE_ROOT / "metadata.json"),
            "summary_sha256": _sha256(data_root / P1_REFERENCE_ROOT / "summary.json"),
            "p1_rerun": False,
        },
        "resolved_windows": {window_id: resolved_windows[window_id][1] for window_id in WINDOW_IDS},
        "window_summaries": {window_id: window_summaries[window_id] for window_id in WINDOW_IDS},
        "five_window_synthesis": synthesis_rows,
        "resolved_terminal_synthesis": terminal_rows,
        "p1_frozen_metadata_study_id": p1_metadata.get("study_id"),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=runner._json_clean) + "\n",
        encoding="utf-8",
    )

    code_files = [
        Path("scripts/run_pattern_b_progressed_weak_exclusion_p1_simple_v01.py"),
        P1_RUNNER_TEST,
        SCRIPT_RELATIVE,
        TEST_RELATIVE,
    ]
    source_files = [*frozen_paths]
    metadata = {
        "study_id": summary["study_id"],
        "starting_git": starting_git,
        "frozen_p1_reference": summary["frozen_p1_reference"],
        "windows": list(WINDOW_IDS),
        "window_resolutions": summary["resolved_windows"],
        "workers": runner.WORKERS,
        "source_sha256": {path.as_posix(): _sha256(data_root / path) for path in source_files},
        "code_sha256": {path.as_posix(): _sha256(data_root / path) for path in code_files},
        "window_metadata_sha256": {
            window_id: _sha256(data_root / window_directories[window_id] / "metadata.json")
            for window_id in WINDOW_IDS
        },
        "generated_files": {
            filename: {"sha256": _sha256(root / filename), "bytes": (root / filename).stat().st_size}
            for filename in [*generated, "summary.json", "report.md"]
        },
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "completed_windows": list(WINDOW_IDS),
        "verdicts": {window_id: window_summaries[window_id]["verdict"] for window_id in WINDOW_IDS},
        "five_window_synthesis": synthesis_rows,
        "resolved_terminal_synthesis": terminal_rows,
        "output": str(root),
    }, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    return summary


if __name__ == "__main__":
    run()
