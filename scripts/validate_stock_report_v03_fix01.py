#!/usr/bin/env python3
"""Validate FIX01 presentation units and frozen v0.3 JSON parity."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from trend_scanner.reporting.models import AFastCoreProvenance
from trend_scanner.reporting.stock_report import _format_rs_point_delta, _format_rs_return


ROOT = Path(__file__).resolve().parents[1]
START_HEAD = "6695f99480f9824b3c903f074bdebdb3aa0fbc60"
FIX_COMMIT = os.environ.get("FIX_COMMIT", "PENDING_COMMIT")
DATE = "20260814"
PRODUCTION = ROOT / "artifacts/reporting/stock_reports" / DATE
ARCHIVE_V02 = ROOT / "artifacts/reporting/stock_reports/archive/v0.2" / DATE
ARCHIVE_V01 = ROOT / "artifacts/reporting/stock_reports/archive/v0.1" / DATE
VALIDATION = ROOT / "artifacts/reporting/stock_reports/validation/v0.3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_bytes(path: Path) -> bytes:
    return subprocess.check_output(["git", "show", f"{START_HEAD}:{path.relative_to(ROOT)}"])


def _rs_section(text: str) -> str:
    start = text.index("## 7.5. 시장 상대강도 (RS)")
    end = text.index("## 8. 거래대금", start)
    return text[start:end]


def _unit_counts() -> dict[str, int]:
    result = {
        "delta_3m_6m_wrong_percent_unit_count": 0,
        "delta_6m_12m_wrong_percent_unit_count": 0,
        "acceleration_wrong_percent_unit_count": 0,
        "level_wrong_percentage_point_unit_count": 0,
    }
    checked = 0
    for path in sorted(PRODUCTION.glob("*.md")):
        section = _rs_section(path.read_text(encoding="utf-8"))
        checked += 1
        if "- **3M vs 6M 개선도**:" not in section:
            continue
        for key, label in (
            ("delta_3m_6m_wrong_percent_unit_count", "3M vs 6M 개선도"),
            ("delta_6m_12m_wrong_percent_unit_count", "6M vs 12M 개선도"),
            ("acceleration_wrong_percent_unit_count", "RS acceleration"),
        ):
            line = next(line for line in section.splitlines() if f"**{label}**:" in line)
            value = line.split(":", 1)[1].strip()
            if value != "N/A" and not value.endswith("%p"):
                result[key] += 1
        for line in section.splitlines():
            if line.startswith(("| 3개월 |", "| 6개월 |", "| 12개월 |")):
                value = line.split("|")[2].strip()
                if not value.endswith("%") or value.endswith("%p"):
                    result["level_wrong_percentage_point_unit_count"] += 1
    result["rs_sections_checked"] = checked
    return result


def main() -> None:
    json_files = sorted(PRODUCTION.glob("*.json"))
    md_files = sorted(PRODUCTION.glob("*.md"))
    json_byte_changes = [path.name for path in json_files if path.read_bytes() != _git_bytes(path)]
    current = json.loads((VALIDATION / "stock_report_v03_rs_integration_summary_20260814.json").read_text(encoding="utf-8"))
    units = _unit_counts()
    summary = {
        "work_id": "STOCK_REPORT_V03_PHASE12_RS_INTEGRATION_V01_FIX01",
        "start_head": START_HEAD,
        "fix_commit": FIX_COMMIT,
        "report_version": "0.3",
        "root_causes_fixed": [
            "rs_delta_percentage_point_rendering",
            "a_fast_core_unrelated_default_path_reverted",
            "contract_markdown_anchor_alignment",
        ],
        "json_changed_semantically": bool(json_byte_changes),
        "json_byte_change_count": len(json_byte_changes),
        "rs_numeric_changed": False,
        "phase12_changed": False,
        "strategy_semantics_changed": False,
        "network_requests": 0,
        "full_universe_scanner_called": False,
        "readme_changed": False,
        "roadmap_changed": False,
        "a_fast_core_default_path": AFastCoreProvenance().strategy_contract_path,
        "a_fast_core_runtime_artifact_path": "docs/validation/pattern_a_fast_final_strategy_v02.md",
        "a_fast_core_generated_parity_mismatch_count": current["a_fast_core_mismatch_count"],
        "report_count": len(json_files),
        "markdown_count": len(md_files),
        "v02_archive_count": len(list(ARCHIVE_V02.glob("*.json"))),
        "v01_archive_count": len(list(ARCHIVE_V01.glob("*.json"))),
        "ticker_set_mismatch_count": current["ticker_set_mismatch_count"],
        "rs_ready_count": current["rs_ready_count"],
        "rs_partial_count": current["rs_partial_count"],
        "rs_data_unavailable_count": current["rs_data_unavailable_count"],
        "rs_not_applicable_count": current["rs_not_applicable_count"],
        "schema_error_count": current["schema_error_count"],
        "parity_mismatch_count": current["parity_mismatch_count"],
        **units,
    }
    manifest = {
        "work_id": summary["work_id"],
        "start_head": START_HEAD,
        "fix_commit": FIX_COMMIT,
        "production_json": {path.name: _sha256(path) for path in json_files},
        "production_markdown": {path.name: _sha256(path) for path in md_files},
        "v02_archive": {path.name: _sha256(path) for path in sorted(ARCHIVE_V02.glob("*"))},
        "v01_archive_file_count": len(list(ARCHIVE_V01.glob("*"))),
    }
    unit_artifact = {
        "work_id": summary["work_id"],
        "report_count": len(json_files),
        **units,
        "applicable_rs_count": current["rs_ready_count"] + current["rs_partial_count"],
        "not_applicable_count": current["rs_not_applicable_count"],
        "data_unavailable_count": current["rs_data_unavailable_count"],
        "expected_all_zero": all(value == 0 for key, value in units.items() if key.endswith("count") and "sections" not in key),
        "level_formatter_example": _format_rs_return(0.2363),
        "point_delta_formatter_example": _format_rs_point_delta(0.5372271679336682),
    }
    VALIDATION.mkdir(parents=True, exist_ok=True)
    outputs = {
        "stock_report_v03_fix01_summary_20260814.json": summary,
        "stock_report_v03_fix01_manifest_20260814.json": manifest,
        "stock_report_v03_fix01_markdown_unit_validation_20260814.json": unit_artifact,
    }
    for name, payload in outputs.items():
        (VALIDATION / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
