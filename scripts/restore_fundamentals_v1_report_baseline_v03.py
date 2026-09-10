#!/usr/bin/env python3
"""Restore the accepted Stock Report/Web baseline and re-inject V02 Fundamentals.

This is a local-only preservation operation.  It reads the previous accepted
commit through ``git show`` and the already-accepted local F7 report subtree;
it never recalculates market data or contacts an external provider.
"""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "cb56749f9f2e98dd67330e323c063451a1a6e694"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904"
WEB_STOCK_DIR = ROOT / "web/data/stocks"
F7_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
EXPECTED_COUNT = 553
FUNDAMENTALS_PUBLIC_FIELDS = (
    "applicability",
    "reason",
    "requested_as_of",
    "company_family",
    "currency",
    "filter_status",
    "filter_passed",
    "filter_reasons",
    "summary",
    "quarterly",
    "annual",
)


def _git_show(relative_path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASELINE_COMMIT}:{relative_path}"],
        cwd=ROOT,
        text=True,
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object expected: {path}")
    return value


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(value)
        handle.flush()
    temp_path.replace(path)


def _compact_fundamentals(source: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in FUNDAMENTALS_PUBLIC_FIELDS if field not in source]
    if missing:
        raise RuntimeError(f"F7 Fundamentals fields missing: {missing}")
    return {
        "status": source["data_status"],
        **{field: copy.deepcopy(source[field]) for field in FUNDAMENTALS_PUBLIC_FIELDS},
    }


def _replace_fundamentals_markdown(baseline: str, current: str) -> str:
    heading = "## 1.5. 펀더멘털 (Fundamentals)"
    next_heading = "\n## 2. "
    current_start = current.index(heading)
    current_end = current.index(next_heading, current_start)
    baseline_start = baseline.index(heading)
    baseline_end = baseline.index(next_heading, baseline_start)
    current_section = current[current_start:current_end]
    merged = baseline[:baseline_start] + current_section + baseline[baseline_end:]

    current_bullet = next(
        line for line in current.splitlines()
        if line.lstrip().startswith("> - 펀더멘털:")
    )
    lines = merged.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("> - 펀더멘털:"):
            lines[index] = current_bullet
            break
    else:
        raise RuntimeError("baseline executive Fundamentals bullet missing")
    return "\n".join(lines) + "\n"


def _without_fundamentals(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("fundamentals", None)
    summary = result.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("bullet_points"), list):
        summary["bullet_points"] = [
            item for item in summary["bullet_points"]
            if not str(item).startswith("펀더멘털:")
        ]
    return result


def _assert_baseline_cases(reports: dict[str, dict[str, Any]], web: dict[str, dict[str, Any]]) -> None:
    nhn = reports["181710"]
    assert nhn["header"]["effective_as_of"] == "2026-09-04"
    assert nhn["header"]["report_status"] == "READY"
    assert nhn["current_snapshot"]["avg_trading_value_20d_eok"] == 230.08
    assert nhn["current_snapshot"]["is_investable"] is True
    assert nhn["a_fast_core"]["action"] == "WAIT"
    assert nhn["a_fast_core"]["strategy_state"] == "WAIT"
    assert nhn["a_fast_core"]["canonical_position"] == "FLAT"
    assert nhn["monthly_history"]["observation_count"] == 157
    assert any(str(item.get("as_of", "")).startswith("2026-08") for item in nhn["monthly_history"]["full_monthly_history"])
    assert nhn["foreign_flow"]["foreign_flow_intensity_5d"] is not None

    coway = reports["021240"]
    assert coway["header"]["effective_as_of"] == "2026-09-04"
    assert coway["header"]["report_status"] == "READY"
    assert coway["current_snapshot"]["is_investable"] is True
    assert coway["current_snapshot"]["avg_trading_value_20d_eok"] == 156.62
    assert coway["current_snapshot"]["pattern_a_score"] == 96.33

    assert web["181710"]["availability"]["report_status"] == "READY"
    assert web["181710"]["decision"]["action"] == "WAIT"
    assert web["181710"]["decision"]["strategy_state"] == "WAIT"
    assert web["181710"]["decision"]["canonical_position"] == "FLAT"
    assert web["181710"]["decision"]["is_investable"] is True
    assert web["181710"]["price_trend"]["avg_trading_value_20d_eok"] == 230.08
    assert any(item["as_of"].startswith("2026-08") for item in web["181710"]["pattern"]["history_12m"])
    assert web["181710"]["flow"]["intensity_5d"] is not None

    assert web["021240"]["availability"]["report_status"] == "READY"
    assert web["021240"]["price_trend"]["avg_trading_value_20d_eok"] == 156.62
    assert web["021240"]["pattern"]["score"] == 96.33


def main() -> int:
    report_paths = sorted((REPORT_DIR / "json").glob("*.json"))
    markdown_paths = sorted(REPORT_DIR.glob("*.md"))
    web_paths = sorted(WEB_STOCK_DIR.glob("*.json"))
    if len(report_paths) != EXPECTED_COUNT or len(markdown_paths) != EXPECTED_COUNT or len(web_paths) != EXPECTED_COUNT:
        raise RuntimeError(f"expected 553/553/553, got {len(report_paths)}/{len(markdown_paths)}/{len(web_paths)}")

    final_reports: dict[str, dict[str, Any]] = {}
    final_markdown: dict[Path, str] = {}
    source_paths: dict[str, Path] = {}
    for current_path in report_paths:
        relative = current_path.relative_to(ROOT).as_posix()
        current = _read_json(current_path)
        ticker = str(current.get("ticker") or "").upper()
        if len(ticker) != 6:
            raise RuntimeError(f"invalid ticker: {current_path}")
        f7_path = F7_DIR / f"{ticker}.json"
        f7 = _read_json(f7_path)
        if f7.get("f5_ready") != current.get("fundamentals"):
            raise RuntimeError(f"current report/F7 Fundamentals mismatch: {ticker}")
        baseline = json.loads(_git_show(relative))
        merged = copy.deepcopy(baseline)
        merged["fundamentals"] = copy.deepcopy(current["fundamentals"])
        baseline_summary = merged.get("summary")
        current_summary = current.get("summary")
        if not isinstance(baseline_summary, dict) or not isinstance(current_summary, dict):
            raise RuntimeError(f"summary missing: {ticker}")
        current_bullets = current_summary.get("bullet_points", [])
        current_fundamentals_bullet = next(
            item for item in current_bullets if str(item).startswith("펀더멘털:")
        )
        baseline_summary["bullet_points"] = [
            item for item in baseline_summary.get("bullet_points", [])
            if not str(item).startswith("펀더멘털:")
        ]
        baseline_summary["bullet_points"].insert(1, current_fundamentals_bullet)
        if _without_fundamentals(merged) != _without_fundamentals(baseline):
            raise RuntimeError(f"unexpected report preservation drift: {ticker}")
        final_reports[ticker] = merged
        source_paths[ticker] = current_path

        current_md_path = REPORT_DIR / f"{current_path.stem}.md"
        baseline_md = _git_show(current_md_path.relative_to(ROOT).as_posix())
        final_markdown[current_md_path] = _replace_fundamentals_markdown(
            baseline_md, current_md_path.read_text(encoding="utf-8")
        )

    final_web: dict[str, dict[str, Any]] = {}
    for web_path in web_paths:
        ticker = web_path.stem.upper()
        relative = web_path.relative_to(ROOT).as_posix()
        baseline = json.loads(_git_show(relative))
        merged = copy.deepcopy(baseline)
        merged["fundamentals"] = _compact_fundamentals(final_reports[ticker]["fundamentals"])
        if _without_fundamentals(merged) != _without_fundamentals(baseline):
            raise RuntimeError(f"unexpected web preservation drift: {ticker}")
        final_web[ticker] = merged

    _assert_baseline_cases(final_reports, final_web)

    # Promote only after all reports and Web payloads pass preservation checks.
    for ticker, payload in final_reports.items():
        _atomic_write(source_paths[ticker], json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    for path, content in final_markdown.items():
        _atomic_write(path, content)
    for web_path in web_paths:
        _atomic_write(web_path, json.dumps(final_web[web_path.stem.upper()], ensure_ascii=False, separators=(",", ":")) + "\n")

    print(json.dumps({
        "baseline_commit": BASELINE_COMMIT,
        "reports_restored": len(final_reports),
        "web_restored": len(final_web),
        "non_fundamentals_source_drift": 0,
        "non_fundamentals_web_drift": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
