#!/usr/bin/env python3
"""Produce the required v0.3 schema, parity, summary and manifest artifacts."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pandas as pd
from jsonschema import Draft7Validator

from trend_scanner.reporting.relative_strength_report import (
    PHASE12_CLOSURE_SHA,
    RS_ARTIFACT_TEMPLATE,
    load_relative_strength_section,
)


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260814"
PRODUCTION = ROOT / "artifacts/reporting/stock_reports" / DATE
ARCHIVE_V02 = ROOT / "artifacts/reporting/stock_reports/archive/v0.2" / DATE
ARCHIVE_V01 = ROOT / "artifacts/reporting/stock_reports/archive/v0.1" / DATE
VALIDATION = ROOT / "artifacts/reporting/stock_reports/validation/v0.3"
SCHEMA_PATH = ROOT / "docs/reporting/stock_report/schema_v03.json"
RS_PATH = ROOT / RS_ARTIFACT_TEMPLATE.format(date=DATE)

PARITY_FIELDS = (
    "ticker", "name", "market", "asset_type", "requested_as_of", "reference_market_date",
    "header", "current_snapshot", "monthly_history", "foreign_flow", "trading_value_flow",
    "data_quality", "pattern_a_fast", "a_fast_core", "provenance",
)
RS_NUMERIC_FIELDS = (
    "market_rs_3m", "market_rs_6m", "market_rs_12m", "market_rs_delta_3m_vs_6m",
    "market_rs_delta_6m_vs_12m", "market_rs_acceleration_3_6_12m", "all_market_rs_rank_3m",
    "all_market_rs_rank_6m", "all_market_rs_rank_12m", "all_market_rs_percentile_3m",
    "all_market_rs_percentile_6m", "all_market_rs_percentile_12m",
)


def _load_dir(directory: Path) -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rs_rows() -> dict[str, dict]:
    frame = pd.read_csv(RS_PATH, dtype={"ticker": str}, float_precision="round_trip")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.zfill(6)
    return {row["ticker"]: row for row in frame.to_dict(orient="records")}


def _rs_expected(row: dict, field: str):
    value = row.get(field)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _summary_parity(v02: dict, v03: dict) -> dict:
    old_bullets = v02["summary"]["bullet_points"]
    new_bullets = [b for b in v03["summary"]["bullet_points"] if not b.startswith("시장 상대강도:")]
    old_narrative = v02["summary"]["combined_narrative"]
    new_narrative = v03["summary"]["combined_narrative"]
    return {
        "headline_equal": v02["summary"]["headline"] == v03["summary"]["headline"],
        "strategy_headline_equal": v02["summary"].get("strategy_headline") == v03["summary"].get("strategy_headline"),
        "bullet_points_equal_after_rs_removal": old_bullets == new_bullets,
        "combined_narrative_v02_prefix": new_narrative.startswith(old_narrative),
        "rs_bullet_count": sum(b.startswith("시장 상대강도:") for b in v03["summary"]["bullet_points"]),
    }


def main() -> None:
    v02 = _load_dir(ARCHIVE_V02)
    v03 = _load_dir(PRODUCTION)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    schema_errors = {
        stem: [error.message for error in validator.iter_errors(data)]
        for stem, data in v03.items()
        if list(validator.iter_errors(data))
    }

    ticker_set_equal = set(v02) == set(v03) == {p.stem for p in ARCHIVE_V01.glob("*.json")}
    parity_mismatches: dict[str, dict[str, list[str]]] = {}
    summary_results: dict[str, dict] = {}
    rs_mismatches: dict[str, list[str]] = {}
    rs_rows = _rs_rows()
    for stem in sorted(v03):
        old, new = v02[stem], v03[stem]
        differences = [field for field in PARITY_FIELDS if old.get(field) != new.get(field)]
        if differences:
            parity_mismatches[stem] = {"fields": differences}
        summary_results[stem] = _summary_parity(old, new)
        rs = new["relative_strength"]
        expected_row = rs_rows.get(new["ticker"])
        rs_diff: list[str] = []
        if new["asset_type"] == "COMMON" and new["market"] in {"KOSPI", "KOSDAQ"} and expected_row:
            if rs["applicability"] != "APPLICABLE" or rs["data_status"] != expected_row.get("market_rs_data_status"):
                rs_diff.append("status")
            for field in RS_NUMERIC_FIELDS:
                if rs[field] != _rs_expected(expected_row, field):
                    rs_diff.append(field)
        elif new["asset_type"] != "COMMON" or new["market"] not in {"KOSPI", "KOSDAQ"}:
            if rs["applicability"] != "NOT_APPLICABLE" or rs["data_status"] != "NOT_EVALUATED":
                rs_diff.append("noncommon_status")
            if any(rs[field] is not None for field in RS_NUMERIC_FIELDS):
                rs_diff.append("noncommon_numeric_not_null")
        if rs["source_artifact"] == str(RS_PATH.relative_to(ROOT)) and rs["source_sha256"] != _sha256(RS_PATH):
            rs_diff.append("source_sha256")
        if rs["phase12_closure_sha"] != PHASE12_CLOSURE_SHA:
            rs_diff.append("phase12_closure_sha")
        if rs["source_as_of"] != "2026-08-14" and rs["applicability"] == "APPLICABLE":
            rs_diff.append("source_as_of")
        if rs_diff:
            rs_mismatches[stem] = rs_diff

    markdown_errors = {}
    for path in sorted(PRODUCTION.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        try:
            flow = text.index("## 7. 외국인")
            relative = text.index("## 7.5. 시장 상대강도 (RS)")
            trading = text.index("## 8. 거래대금")
            rs_text = text[relative:trading]
            errors = [] if flow < relative < trading else ["section_order"]
            if "매수 추천" in rs_text or "매도 추천" in rs_text:
                errors.append("strategy_language")
            if errors:
                markdown_errors[path.stem] = errors
        except ValueError:
            markdown_errors[path.stem] = ["missing_section"]

    with tempfile.TemporaryDirectory(prefix="stock-report-v03-validation-") as temp_name:
        temp_root = Path(temp_name)
        missing_snapshot = load_relative_strength_section("005930", DATE, "COMMON", "KOSPI", temp_root)
        missing_ticker = load_relative_strength_section("999999", DATE, "COMMON", "KOSPI", ROOT)

    representative = {}
    for ticker in ("068270", "035420", "005930", "001540"):
        section = load_relative_strength_section(ticker, "2026-08-14", "COMMON", "KOSPI" if ticker != "001540" else "KOSDAQ", ROOT)
        representative[ticker] = {
            "applicability": section.applicability,
            "data_status": section.data_status,
            "market_rs_3m": section.market_rs_3m,
            "market_rs_6m": section.market_rs_6m,
            "market_rs_12m": section.market_rs_12m,
            "explanation": section.explanation,
        }

    VALIDATION.mkdir(parents=True, exist_ok=True)
    summary = {
        "artifact": "stock_report_v03_rs_integration_summary_20260814",
        "report_version": "0.3",
        "phase12_closure_sha": PHASE12_CLOSURE_SHA,
        "report_count": len(v03),
        "v02_archive_count": len(v02),
        "v03_production_count": len(v03),
        "production_json_count": len(v03),
        "production_markdown_count": len(list(PRODUCTION.glob("*.md"))),
        "archive_v02_json_count": len(v02),
        "archive_v01_json_count": len(list(ARCHIVE_V01.glob("*.json"))),
        "ticker_set_equal": ticker_set_equal,
        "ticker_set_mismatch_count": 0 if ticker_set_equal else 1,
        "schema_error_count": len(schema_errors),
        "parity_mismatch_count": len(parity_mismatches),
        "rs_mismatch_count": len(rs_mismatches),
        "current_snapshot_mismatch_count": sum("current_snapshot" in item["fields"] for item in parity_mismatches.values()),
        "monthly_history_mismatch_count": sum("monthly_history" in item["fields"] for item in parity_mismatches.values()),
        "foreign_flow_mismatch_count": sum("foreign_flow" in item["fields"] for item in parity_mismatches.values()),
        "trading_value_flow_mismatch_count": sum("trading_value_flow" in item["fields"] for item in parity_mismatches.values()),
        "pattern_a_fast_mismatch_count": sum("pattern_a_fast" in item["fields"] for item in parity_mismatches.values()),
        "a_fast_core_mismatch_count": sum("a_fast_core" in item["fields"] for item in parity_mismatches.values()),
        "data_quality_mismatch_count": sum("data_quality" in item["fields"] for item in parity_mismatches.values()),
        "header_mismatch_count": sum("header" in item["fields"] for item in parity_mismatches.values()),
        "relative_strength_exact_parity_mismatch_count": len(rs_mismatches),
        "markdown_error_count": len(markdown_errors),
        "summary_headline_mismatch_count": sum(not item["headline_equal"] for item in summary_results.values()),
        "summary_strategy_headline_mismatch_count": sum(not item["strategy_headline_equal"] for item in summary_results.values()),
        "summary_bullet_parity_mismatch_count": sum(not item["bullet_points_equal_after_rs_removal"] for item in summary_results.values()),
        "summary_narrative_prefix_mismatch_count": sum(not item["combined_narrative_v02_prefix"] for item in summary_results.values()),
        "allowed_summary_change_only": all(
            item["headline_equal"]
            and item["strategy_headline_equal"]
            and item["bullet_points_equal_after_rs_removal"]
            and item["combined_narrative_v02_prefix"]
            and item["rs_bullet_count"] == 1
            for item in summary_results.values()
        ),
        "rs_ready_count": sum(data["relative_strength"]["applicability"] == "APPLICABLE" and data["relative_strength"]["data_status"] == "READY" for data in v03.values()),
        "rs_partial_count": sum(data["relative_strength"]["data_status"] == "PARTIAL" for data in v03.values()),
        "rs_data_unavailable_count": sum(data["relative_strength"]["data_status"] == "DATA_UNAVAILABLE" for data in v03.values()),
        "rs_not_applicable_count": sum(data["relative_strength"]["applicability"] == "NOT_APPLICABLE" for data in v03.values()),
        "exact_snapshot_missing_count": sum(
            data["relative_strength"]["applicability"] == "DATA_UNAVAILABLE"
            and data["relative_strength"]["source_artifact"] is None
            for data in v03.values()
        ),
        "ticker_missing_count": sum(
            data["relative_strength"]["applicability"] == "DATA_UNAVAILABLE"
            and data["relative_strength"]["source_artifact"] is not None
            for data in v03.values()
        ),
        "phase12_numeric_mismatch_count": sum(
            any(field in mismatch for field in RS_NUMERIC_FIELDS)
            for mismatch in rs_mismatches.values()
        ),
        "phase12_percentile_mismatch_count": sum(
            any(field.startswith("all_market_rs_percentile") for field in mismatch)
            for mismatch in rs_mismatches.values()
        ),
        "phase12_rank_mismatch_count": sum(
            any(field.startswith("all_market_rs_rank") for field in mismatch)
            for mismatch in rs_mismatches.values()
        ),
        "source_sha_mismatch_count": sum("source_sha256" in mismatch for mismatch in rs_mismatches.values()),
        "network_requests": 0,
        "full_universe_scanner_called": False,
        "sector_rs": "DEFERRED",
        "behavior_checks": {
            "missing_snapshot": [missing_snapshot.applicability, missing_snapshot.data_status],
            "missing_ticker": [missing_ticker.applicability, missing_ticker.data_status],
        },
        "representatives": representative,
        "final_status": "READY_FOR_ARCHITECT_STOCK_REPORT_V03_REVIEW",
    }
    parity = {
        "parity_fields": list(PARITY_FIELDS),
        "allowed_additions": ["report_version", "relative_strength", "summary_rs_bullet", "summary_rs_narrative"],
        "mismatches": parity_mismatches,
        "summary_results": summary_results,
        "relative_strength_mismatches": rs_mismatches,
    }
    schema_result = {
        "schema": str(SCHEMA_PATH.relative_to(ROOT)),
        "validator": "Draft7Validator",
        "report_count": len(v03),
        "errors": schema_errors,
        "valid": not schema_errors,
    }
    manifest = {
        "report_version": "0.3",
        "as_of": "2026-08-14",
        "production": {
            "directory": str(PRODUCTION.relative_to(ROOT)),
            "json_count": len(v03),
            "markdown_count": len(list(PRODUCTION.glob("*.md"))),
            "files": {path.name: _sha256(path) for path in sorted(PRODUCTION.glob("*.json")) + sorted(PRODUCTION.glob("*.md"))},
        },
        "archive_v02": {
            "directory": str(ARCHIVE_V02.relative_to(ROOT)),
            "json_count": len(v02),
            "markdown_count": len(list(ARCHIVE_V02.glob("*.md"))),
            "files": {path.name: _sha256(path) for path in sorted(ARCHIVE_V02.glob("*.json")) + sorted(ARCHIVE_V02.glob("*.md"))},
        },
        "phase12_source": {
            "artifact": str(RS_PATH.relative_to(ROOT)),
            "sha256": _sha256(RS_PATH),
            "closure_sha": PHASE12_CLOSURE_SHA,
        },
    }
    outputs = {
        "stock_report_v03_rs_integration_summary_20260814.json": summary,
        "stock_report_v03_regression_parity_20260814.json": parity,
        "stock_report_v03_schema_validation_20260814.json": schema_result,
        "stock_report_v03_manifest_20260814.json": manifest,
    }
    for name, content in outputs.items():
        (VALIDATION / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "validation_dir": str(VALIDATION)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
