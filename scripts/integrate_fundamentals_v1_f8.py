#!/usr/bin/env python3
"""Integrate frozen F7 Fundamentals into the 2026-09-04 Stock Report set.

The integration is deliberately local-only.  It consumes the existing v0.4
Stock Report JSON/Markdown and the serialized F7 ``f5_ready`` section, builds
the complete v0.5 corpus in a staging directory, validates it, and promotes
the corpus only after every validation passes.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from jsonschema import Draft7Validator

from trend_scanner.reporting.fundamentals_report import fundamentals_executive_bullet
from trend_scanner.reporting.models import (
    FundamentalsAnnualRow,
    FundamentalsQuarterRow,
    FundamentalsSection,
    FundamentalsSummary,
)
from trend_scanner.reporting.stock_report import _render_fundamentals_section


ROOT = Path(__file__).resolve().parents[1]
REQUESTED_AS_OF = "2026-09-04"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904"
FUNDAMENTALS_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
SCHEMA_PATH = ROOT / "docs/reporting/stock_report/schema_v05.json"
EXPECTED_REPORT_COUNT = 553
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
VALID_TERMINAL_STATUSES = {
    "PASS",
    "FILTERED_ANNUAL_REVENUE",
    "FILTERED_QUARTERLY_REVENUE",
    "FILTERED_OPERATING_LOSS",
    "FILTERED_NET_LOSS",
    "DATA_UNAVAILABLE",
    "NOT_APPLICABLE",
}
VALID_DATA_STATUSES = {"READY", "PARTIAL", "DATA_UNAVAILABLE", "NOT_APPLICABLE"}
F5_REQUIRED_FIELDS = {
    "applicability",
    "data_status",
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
    "diagnostics",
}
V05_VALIDATOR = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


class F8IntegrationError(RuntimeError):
    """Raised when an integration or preservation invariant fails."""


@dataclass(frozen=True)
class IntegrationRecord:
    ticker: str
    stem: str
    baseline_json: dict[str, Any]
    baseline_markdown: str
    f7_json: dict[str, Any]
    fundamentals: FundamentalsSection


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise F8IntegrationError(f"JSON authority must be an object: {path}")
    return value


def _first_difference(expected: Any, actual: Any, path: str = "$") -> tuple[str, Any, Any] | None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return f"{path}.{key}", expected.get(key), actual.get(key)
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return path, expected, actual
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = _first_difference(expected_item, actual_item, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if expected != actual or type(expected) is not type(actual):
        return path, expected, actual
    return None


def _section_from_f5(value: Mapping[str, Any]) -> FundamentalsSection:
    missing = sorted(F5_REQUIRED_FIELDS - set(value))
    if missing:
        raise F8IntegrationError(f"f5_ready missing fields: {missing}")
    if value["data_status"] not in VALID_DATA_STATUSES:
        raise F8IntegrationError(f"invalid f5_ready data_status: {value['data_status']!r}")
    if value["currency"] != "KRW":
        raise F8IntegrationError(f"invalid f5_ready currency: {value['currency']!r}")
    summary = value["summary"]
    if not isinstance(summary, Mapping):
        raise F8IntegrationError("f5_ready summary must be an object")
    try:
        summary_model = FundamentalsSummary(**dict(summary))
        quarterly = [FundamentalsQuarterRow(**dict(row)) for row in value["quarterly"]]
        annual = [FundamentalsAnnualRow(**dict(row)) for row in value["annual"]]
    except (TypeError, ValueError) as exc:
        raise F8IntegrationError(f"invalid f5_ready nested structure: {exc}") from exc
    if not isinstance(value["filter_reasons"], list) or not isinstance(value["diagnostics"], list):
        raise F8IntegrationError("f5_ready filter_reasons/diagnostics must be arrays")
    if not isinstance(value["quarterly"], list) or not isinstance(value["annual"], list):
        raise F8IntegrationError("f5_ready quarterly/annual must be arrays")
    return FundamentalsSection(
        applicability=str(value["applicability"]),
        data_status=str(value["data_status"]),
        reason=value["reason"],
        requested_as_of=value["requested_as_of"],
        company_family=value["company_family"],
        currency=str(value["currency"]),
        filter_status=str(value["filter_status"]),
        filter_passed=bool(value["filter_passed"]),
        filter_reasons=list(value["filter_reasons"]),
        summary=summary_model,
        quarterly=quarterly,
        annual=annual,
        diagnostics=list(value["diagnostics"]),
    )


def load_integration_records(
    report_dir: Path = REPORT_DIR,
    fundamentals_dir: Path = FUNDAMENTALS_DIR,
    *,
    expected_count: int = EXPECTED_REPORT_COUNT,
) -> list[IntegrationRecord]:
    json_dir = report_dir / "json"
    json_paths = sorted(json_dir.glob("*.json"))
    md_paths = sorted(report_dir.glob("*.md"))
    if len(json_paths) != expected_count or len(md_paths) != expected_count:
        raise F8IntegrationError(
            f"Stock Report target must be {expected_count}/{expected_count}, "
            f"got {len(json_paths)}/{len(md_paths)}"
        )
    json_stems = {path.stem for path in json_paths}
    md_stems = {path.stem for path in md_paths}
    if json_stems != md_stems:
        raise F8IntegrationError("Stock Report JSON/Markdown filename stems differ")

    records: list[IntegrationRecord] = []
    seen: set[str] = set()
    for json_path in json_paths:
        baseline = _read_json(json_path)
        ticker = str(baseline.get("ticker") or "").strip().upper()
        if not TICKER_RE.fullmatch(ticker) or json_path.stem.split("_", 1)[0] != ticker:
            raise F8IntegrationError(f"invalid Stock Report ticker/filename identity: {json_path.name}")
        if ticker in seen:
            raise F8IntegrationError(f"duplicate Stock Report ticker: {ticker}")
        seen.add(ticker)
        if baseline.get("report_version") != "0.4":
            raise F8IntegrationError(f"F8 baseline must be v0.4: {json_path.name}")
        if baseline.get("requested_as_of") != REQUESTED_AS_OF:
            raise F8IntegrationError(f"Stock Report requested_as_of mismatch: {json_path.name}")
        if baseline.get("reference_market_date") != REQUESTED_AS_OF:
            raise F8IntegrationError(f"Stock Report reference_market_date mismatch: {json_path.name}")

        md_path = report_dir / f"{json_path.stem}.md"
        if not md_path.exists():
            raise F8IntegrationError(f"Markdown counterpart missing: {md_path.name}")

        f7_path = fundamentals_dir / f"{ticker}.json"
        if not f7_path.exists():
            raise F8IntegrationError(f"missing F7 output for Stock Report ticker: {ticker}")
        f7 = _read_json(f7_path)
        if f7.get("ticker") != ticker:
            raise F8IntegrationError(f"F7 ticker identity mismatch: {ticker}")
        if f7.get("requested_as_of") != REQUESTED_AS_OF:
            raise F8IntegrationError(f"F7 requested_as_of mismatch: {ticker}")
        if f7.get("terminal_status") not in VALID_TERMINAL_STATUSES:
            raise F8IntegrationError(f"invalid F7 terminal status: {ticker}")
        if baseline.get("asset_type") != f7.get("asset_type"):
            raise F8IntegrationError(
                f"asset_type identity mismatch: {ticker} "
                f"report={baseline.get('asset_type')!r} f7={f7.get('asset_type')!r}"
            )
        f5 = f7.get("f5_ready")
        if not isinstance(f5, Mapping):
            raise F8IntegrationError(f"invalid or missing f5_ready: {ticker}")
        if f5.get("requested_as_of") != REQUESTED_AS_OF:
            raise F8IntegrationError(f"f5_ready requested_as_of mismatch: {ticker}")
        fundamentals = _section_from_f5(f5)
        records.append(IntegrationRecord(
            ticker=ticker,
            stem=json_path.stem,
            baseline_json=baseline,
            baseline_markdown=md_path.read_text(encoding="utf-8"),
            f7_json=f7,
            fundamentals=fundamentals,
        ))
    if len(records) != expected_count:
        raise F8IntegrationError(f"F8 target ticker count mismatch: {len(records)}")
    return records


def _integrated_json(record: IntegrationRecord) -> dict[str, Any]:
    value = copy.deepcopy(record.baseline_json)
    value["report_version"] = "0.5"
    technical_details = value.get("technical_details")
    if isinstance(technical_details, dict):
        technical_details["report_version"] = "0.5"
        value["technical_details"] = technical_details
    value["fundamentals"] = copy.deepcopy(record.f7_json["f5_ready"])

    summary = value.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("bullet_points"), list):
        raise F8IntegrationError(f"summary bullet_points missing: {record.ticker}")
    bullet = fundamentals_executive_bullet(record.fundamentals)
    if not bullet or bullet in summary["bullet_points"]:
        raise F8IntegrationError(f"invalid duplicate Fundamentals bullet: {record.ticker}")
    bullets = summary["bullet_points"]
    summary["bullet_points"] = bullets[:1] + [bullet] + bullets[1:]
    value["summary"] = summary
    return value


def _integrated_markdown(record: IntegrationRecord) -> str:
    lines = record.baseline_markdown.splitlines()
    if not lines or not re.search(r" 종목 리포트 v0\.4$", lines[0]):
        raise F8IntegrationError(f"v0.4 Markdown title missing: {record.ticker}")
    lines[0] = re.sub(r" v0\.4$", " v0.5", lines[0], count=1)

    bullet = fundamentals_executive_bullet(record.fundamentals)
    narrative = record.baseline_json["summary"]["combined_narrative"]
    try:
        summary_start = next(index for index, line in enumerate(lines) if line.startswith("## 0."))
        narrative_index = lines.index(narrative, summary_start)
    except (StopIteration, ValueError) as exc:
        raise F8IntegrationError(f"Markdown summary structure missing: {record.ticker}") from exc
    bullet_indices = [
        index for index in range(summary_start, narrative_index)
        if lines[index].startswith("> - ")
    ]
    if not bullet_indices:
        raise F8IntegrationError(f"Markdown executive bullets missing: {record.ticker}")
    lines.insert(bullet_indices[-1] + 1, f"> - {bullet}")

    try:
        section_two_index = next(index for index, line in enumerate(lines) if line.startswith("## 2."))
    except StopIteration as exc:
        raise F8IntegrationError(f"Markdown Section 2 missing: {record.ticker}") from exc
    lines[section_two_index:section_two_index] = _render_fundamentals_section(record.fundamentals)
    return "\n".join(lines) + "\n"


def _report_without_allowed_changes(value: Mapping[str, Any], bullet: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.pop("fundamentals", None)
    result["report_version"] = "0.4"
    details = result.get("technical_details")
    if isinstance(details, dict):
        details["report_version"] = "0.4"
    summary = result.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("bullet_points"), list):
        bullets = list(summary["bullet_points"])
        if bullet in bullets:
            bullets.remove(bullet)
            summary["bullet_points"] = bullets
    return result


def _markdown_without_allowed_changes(value: str, bullet: str) -> str:
    lines = value.splitlines()
    if not lines:
        raise F8IntegrationError("integrated Markdown is empty")
    lines[0] = re.sub(r" v0\.5$", " v0.4", lines[0], count=1)
    try:
        lines.remove(f"> - {bullet}")
    except ValueError as exc:
        raise F8IntegrationError("integrated Fundamentals bullet missing") from exc
    start = next(index for index, line in enumerate(lines) if line == "## 1.5. 펀더멘털 (Fundamentals)")
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("## 2."))
    del lines[start:end]
    return "\n".join(lines) + "\n"


def validate_integrated_record(record: IntegrationRecord, value: Mapping[str, Any], markdown: str) -> None:
    errors = sorted(V05_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path) or "$"
        raise F8IntegrationError(f"v0.5 schema error {record.ticker} at {location}: {first.message}")
    if value.get("report_version") != "0.5":
        raise F8IntegrationError(f"v0.5 report_version missing: {record.ticker}")
    if value.get("requested_as_of") != REQUESTED_AS_OF:
        raise F8IntegrationError(f"v0.5 requested_as_of mismatch: {record.ticker}")
    if value.get("reference_market_date") != REQUESTED_AS_OF:
        raise F8IntegrationError(f"v0.5 reference_market_date mismatch: {record.ticker}")
    if value.get("fundamentals") != record.f7_json.get("f5_ready"):
        raise F8IntegrationError(f"F7 f5_ready parity mismatch: {record.ticker}")
    bullet = fundamentals_executive_bullet(record.fundamentals)
    summary = value.get("summary")
    if not isinstance(summary, dict) or bullet not in summary.get("bullet_points", []):
        raise F8IntegrationError(f"Fundamentals bullet missing: {record.ticker}")
    baseline_view = _report_without_allowed_changes(record.baseline_json, bullet)
    actual_view = _report_without_allowed_changes(value, bullet)
    difference = _first_difference(baseline_view, actual_view)
    if difference is not None:
        path, baseline, actual = difference
        raise F8IntegrationError(
            f"NON_FUNDAMENTALS_REPORT_DRIFT ticker={record.ticker} field={path} "
            f"baseline={baseline!r} new={actual!r}"
        )
    normalized_baseline = record.baseline_markdown.rstrip("\n") + "\n"
    normalized_actual = _markdown_without_allowed_changes(markdown, bullet)
    if normalized_baseline != normalized_actual:
        difference = _first_difference(normalized_baseline.splitlines(), normalized_actual.splitlines())
        path, baseline, actual = difference or ("$", normalized_baseline, normalized_actual)
        raise F8IntegrationError(
            f"NON_FUNDAMENTALS_MARKDOWN_DRIFT ticker={record.ticker} field={path} "
            f"baseline={baseline!r} new={actual!r}"
        )


def _write_record(staging_dir: Path, record: IntegrationRecord) -> tuple[dict[str, Any], str]:
    value = _integrated_json(record)
    markdown = _integrated_markdown(record)
    json_path = staging_dir / "json" / f"{record.stem}.json"
    md_path = staging_dir / f"{record.stem}.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return value, markdown


def _select_representatives(records: list[IntegrationRecord]) -> list[IntegrationRecord]:
    by_ticker = {record.ticker: record for record in records}
    selected: list[IntegrationRecord] = []
    seen: set[str] = set()
    for ticker in ("005930", "000080", "000250", "0220W0"):
        record = by_ticker.get(ticker)
        if record is not None and ticker not in seen:
            selected.append(record)
            seen.add(ticker)
    for status in ("READY", "PARTIAL", "DATA_UNAVAILABLE", "NOT_APPLICABLE"):
        record = next((item for item in records if item.fundamentals.data_status == status and item.ticker not in seen), None)
        if record is not None:
            selected.append(record)
            seen.add(record.ticker)
    filtered = next(
        (item for item in records if item.fundamentals.filter_status.startswith("FILTERED_") and item.ticker not in seen),
        None,
    )
    if filtered is not None:
        selected.append(filtered)
    return selected


def _validate_staging(records: list[IntegrationRecord], staging_dir: Path) -> dict[str, Any]:
    json_paths = sorted((staging_dir / "json").glob("*.json"))
    md_paths = sorted(staging_dir.glob("*.md"))
    if len(json_paths) != EXPECTED_REPORT_COUNT or len(md_paths) != EXPECTED_REPORT_COUNT:
        raise F8IntegrationError(f"staging count mismatch: JSON={len(json_paths)} MD={len(md_paths)}")
    by_stem = {record.stem: record for record in records}
    data_status_counts: Counter[str] = Counter()
    filter_status_counts: Counter[str] = Counter()
    for json_path in json_paths:
        record = by_stem.get(json_path.stem)
        if record is None:
            raise F8IntegrationError(f"unexpected staging JSON: {json_path.name}")
        value = _read_json(json_path)
        md_path = staging_dir / f"{json_path.stem}.md"
        if not md_path.exists():
            raise F8IntegrationError(f"staging Markdown missing: {md_path.name}")
        validate_integrated_record(record, value, md_path.read_text(encoding="utf-8"))
        fundamentals = value["fundamentals"]
        data_status_counts[str(fundamentals["data_status"])] += 1
        filter_status_counts[str(fundamentals["filter_status"])] += 1
    return {
        "report_target_count": len(records),
        "f7_matched_count": len(records),
        "missing_f7_count": 0,
        "identity_mismatch_count": 0,
        "invalid_f5_ready_count": 0,
        "json_count": len(json_paths),
        "markdown_count": len(md_paths),
        "v05_count": len(json_paths),
        "schema_errors": 0,
        "fundamentals_present_count": len(json_paths),
        "fundamentals_parity_pass": len(json_paths),
        "fundamentals_parity_fail": 0,
        "non_fundamentals_report_drift": 0,
        "fundamentals_data_status_counts": dict(sorted(data_status_counts.items())),
        "fundamentals_filter_status_counts": dict(sorted(filter_status_counts.items())),
    }


def _promote_staging(staging_dir: Path, canonical_dir: Path) -> None:
    parent = canonical_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    new_dir = Path(tempfile.mkdtemp(prefix=".f8-new-", dir=str(parent)))
    shutil.rmtree(new_dir)
    shutil.copytree(staging_dir, new_dir)
    old_dir = parent / f".f8-old-{uuid4().hex}"
    canonical_dir.rename(old_dir)
    try:
        new_dir.rename(canonical_dir)
    except Exception:
        old_dir.rename(canonical_dir)
        raise
    shutil.rmtree(old_dir)


def integrate(
    report_dir: Path = REPORT_DIR,
    fundamentals_dir: Path = FUNDAMENTALS_DIR,
    *,
    promote: bool = True,
) -> dict[str, Any]:
    records = load_integration_records(report_dir, fundamentals_dir)
    staging_parent = report_dir.parent
    with tempfile.TemporaryDirectory(prefix=".f8-staging-", dir=str(staging_parent)) as temp_name:
        staging_dir = Path(temp_name) / report_dir.name
        staging_dir.mkdir(parents=True, exist_ok=True)
        representatives = _select_representatives(records)
        for record in representatives:
            value, markdown = _write_record(staging_dir, record)
            validate_integrated_record(record, value, markdown)
        for record in records:
            if record.ticker not in {item.ticker for item in representatives}:
                _write_record(staging_dir, record)
        stats = _validate_staging(records, staging_dir)
        stats["representative_tickers"] = [record.ticker for record in representatives]
        stats["staging_validated"] = True
        if promote:
            _promote_staging(staging_dir, report_dir)
            stats["canonical_promoted"] = True
        else:
            stats["canonical_promoted"] = False
        return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-promote", action="store_true", help="validate staging without replacing canonical reports")
    args = parser.parse_args()
    stats = integrate(promote=not args.no_promote)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
