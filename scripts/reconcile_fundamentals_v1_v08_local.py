#!/usr/bin/env python3
"""Reconcile the four V08 edge-case artifacts from committed local evidence.

This script is intentionally cache-only.  It never creates an OpenDART client,
reads secrets, or contacts a network provider.  It rewrites only the affected
production/report/web payloads after rebuilding them through the production
periodization and reporting boundaries.
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trend_scanner.fundamentals.derived_metrics import DerivedMetricsEngine
from trend_scanner.fundamentals.fundamentals_filter import FundamentalsFilter
from trend_scanner.fundamentals.multi_period import build_multi_period_result
from trend_scanner.fundamentals.models import RegisteredFiling
from trend_scanner.fundamentals.period_models import (
    PeriodizationFact,
    PeriodizationResult,
    PeriodizedFinancialObservation,
)
from trend_scanner.fundamentals.periodization import (
    PeriodizationEngine,
    collapse_canonical_duplicate_periodization_facts,
    normalize_represented_comparative_fact,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild
from trend_scanner.reporting.fundamentals_report import (
    build_fundamentals_section,
    fundamentals_executive_bullet,
)
from trend_scanner.reporting.stock_report import _render_fundamentals_section
from scripts.export_stock_report_web import _compact_report, _write_json
from scripts.integrate_fundamentals_v1_f8 import _section_from_f5


REQUESTED_AS_OF = "2026-09-04"
FUNDAMENTALS_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904"
WEB_STOCK_DIR = ROOT / "web/data/stocks"
HOLDING_MARKERS = ("홀딩", "홀딩스", "지주", "지주회사", "스퀘어")
AMBIGUOUS_HOLDING_TICKERS = {"055550"}  # 신한지주; metadata cache is absent locally.
ACTUAL_FINANCIAL_RESTORE_TICKERS = {
    "071050", "086790", "138040", "138930", "139130", "175330", "316140",
}
MIGRATED_TICKERS = {
    "000070", "000140", "000320", "000590", "000640", "001040", "001230", "001800",
    "003030", "003380", "004150", "004990", "005440", "005740", "005810", "006200",
    "006840", "007700", "009440", "009970", "010060", "0126Z0", "015860", "024720",
    "036530", "060980", "072710", "078070", "084690", "096760", "107590", "192400",
    "363280", "383800", "402340",
}
FINANCIAL_NAME_MARKERS = (
    "금융", "은행", "증권", "보험", "캐피탈", "카드", "신탁", "자산운용",
    "투자", "여신", "보증", "화재", "생명", "손해",
)


class _AsOfOnlyDerivedResult:
    def __init__(self):
        self.requested_as_of = REQUESTED_AS_OF
        self.observations: tuple[Any, ...] = ()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _observation(value: dict[str, Any]) -> PeriodizedFinancialObservation:
    data = dict(value)
    for field in ("source_rcept_nos", "source_rcept_dts", "source_sha256s"):
        data[field] = tuple(data.get(field) or ())
    return PeriodizedFinancialObservation(**data)


def _filing(value: dict[str, Any]) -> RegisteredFiling:
    keys = {field.name for field in RegisteredFiling.__dataclass_fields__.values()}
    return RegisteredFiling(**{key: value.get(key) for key in keys})


def _rebuild_build(raw: dict[str, Any], *, ticker: str, corp_code: str, family: str) -> PeriodizationBuild:
    facts: list[PeriodizationFact] = []
    for value in raw.get("facts", ()):
        fact = normalize_represented_comparative_fact(PeriodizationFact.from_mapping(value))
        facts.append(fact)
    stats: dict[str, int] = {}
    collapsed = collapse_canonical_duplicate_periodization_facts(facts, stats=stats)
    current_states = {
        str(item.get("reprt_code")): {
            "status": item.get("status"),
            "reason": item.get("reason"),
        }
        for item in raw.get("anchor_selections", ())
        if item.get("reprt_code")
    }
    prior_states: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw.get("anchor_selections", ()):
        anchor_no = item.get("selected_rcept_no")
        prior = item.get("prior_pit") or {}
        if anchor_no and prior.get("reprt_code"):
            prior_states[(str(item["reprt_code"]), str(anchor_no))] = {
                "status": prior.get("status"),
                "reason": prior.get("canonical_reason") or prior.get("reason"),
            }
    result = PeriodizationEngine().periodize(
        collapsed,
        as_of=REQUESTED_AS_OF,
        prior_pit_states=prior_states,
        current_pit_states=current_states,
        include_comparative_presentations=True,
    )
    return PeriodizationBuild(
        ticker=ticker,
        fiscal_year=str(raw.get("fiscal_year") or ""),
        requested_as_of=REQUESTED_AS_OF,
        company_family=family,
        filings=tuple(_filing(item) for item in raw.get("filings", ())),
        facts=collapsed,
        result=result,
        anchor_selections=tuple(raw.get("anchor_selections") or ()),
        skipped_anchors=tuple(raw.get("skipped_anchors") or ()),
        canonical_duplicate_group_count=int(raw.get("canonical_duplicate_group_count", 0) or 0) + int(stats.get("group_count", 0) or 0),
        canonical_duplicate_fact_removed_count=int(raw.get("canonical_duplicate_fact_removed_count", 0) or 0) + int(stats.get("removed_fact_count", 0) or 0),
        precision_equivalent_group_count=int(raw.get("precision_equivalent_group_count", 0) or 0) + int(stats.get("precision_equivalent_group_count", 0) or 0),
        precision_equivalent_fact_removed_count=int(raw.get("precision_equivalent_fact_removed_count", 0) or 0) + int(stats.get("precision_equivalent_fact_removed_count", 0) or 0),
        context_equivalent_group_count=int(raw.get("context_equivalent_group_count", 0) or 0) + int(stats.get("context_equivalent_group_count", 0) or 0),
        context_equivalent_fact_removed_count=int(raw.get("context_equivalent_fact_removed_count", 0) or 0) + int(stats.get("context_equivalent_fact_removed_count", 0) or 0),
        true_value_conflict_group_count=int(stats.get("true_value_conflict_group_count", 0) or 0),
    )


def _status(result: Any) -> str:
    quarter = result.quarter_coverage or {}
    annual = result.annual_coverage or {}
    if quarter.get("has_comparison_window") and annual.get("has_comparison_window"):
        return "READY"
    if result.canonical_observations or quarter.get("ready_count") or annual.get("ready_count"):
        return "PARTIAL"
    return "DATA_UNAVAILABLE"


def _rebuild_fundamentals(raw: dict[str, Any], *, family: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    ticker = str(raw["ticker"])
    corp_code = str(raw.get("corp_code") or "")
    builds = tuple(
        _rebuild_build(item, ticker=ticker, corp_code=corp_code, family=family)
        for item in (raw.get("f2") or {}).get("periodization_builds", ())
    )
    observations = tuple(item for build in builds for item in build.result.observations)
    f2 = build_multi_period_result(
        ticker=ticker,
        corp_code=corp_code,
        company_family=family,
        requested_as_of=REQUESTED_AS_OF,
        observations=observations,
        periodization_builds=builds,
    )
    f3 = DerivedMetricsEngine().derive(f2.canonical_observations, requested_as_of=REQUESTED_AS_OF)
    f4_input = f3 if f3.observations else _AsOfOnlyDerivedResult()
    f4 = FundamentalsFilter().evaluate(f2, f4_input, requested_as_of=REQUESTED_AS_OF)
    section = build_fundamentals_section(f2, f3, f4, REQUESTED_AS_OF, raw.get("asset_type", "COMMON"))
    return f2.to_dict(), f3.to_dict(), f4.to_dict(), asdict(section)


def _report_path(ticker: str) -> Path:
    matches = sorted((REPORT_DIR / "json").glob(f"{ticker}_*.json"))
    if len(matches) != 1:
        raise ValueError(f"expected one report for {ticker}, got {matches}")
    return matches[0]


def _replace_report(report: dict[str, Any], section: dict[str, Any]) -> None:
    old_bullet = fundamentals_executive_bullet(_section_from_dict(report.get("fundamentals")))
    new_bullet = fundamentals_executive_bullet(_section_from_dict(section))
    report["fundamentals"] = section
    points = list((report.get("summary") or {}).get("bullet_points") or ())
    if old_bullet in points:
        points[points.index(old_bullet)] = new_bullet
    elif new_bullet not in points:
        points.insert(1, new_bullet)
    report.setdefault("summary", {})["bullet_points"] = points


def _section_from_dict(value: dict[str, Any] | None):
    return _section_from_f5(value) if value else None


def _update_reports(ticker: str, section: dict[str, Any]) -> None:
    matches = sorted((REPORT_DIR / "json").glob(f"{ticker}_*.json"))
    if not matches:
        return
    json_path = _report_path(ticker)
    report = _read_json(json_path)
    original = copy.deepcopy(report)
    _replace_report(report, section)
    if report == original:
        return
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = REPORT_DIR / f"{json_path.stem}.md"
    markdown = md_path.read_text(encoding="utf-8")
    start = markdown.find("## 1.5. 펀더멘털 (Fundamentals)")
    end = markdown.find("## 2. ", start)
    if start < 0 or end < 0:
        raise ValueError(f"fundamentals markdown boundary missing: {md_path}")
    rendered = "\n".join(_render_fundamentals_section(_section_from_dict(section)))
    md_path.write_text(markdown[:start] + rendered + "\n" + markdown[end:], encoding="utf-8")
    _write_json(WEB_STOCK_DIR / f"{ticker}.json", _compact_report(report, json_path))


def _update_ticker_index(tickers: set[str]) -> None:
    path = ROOT / "artifacts/fundamentals/production/20260904/ticker_index.csv"
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        for row in reader:
            ticker = str(row.get("ticker") or "").upper()
            if ticker in tickers:
                raw = _read_json(FUNDAMENTALS_DIR / f"{ticker}.json")
                for field in fields:
                    if field == "f4_reasons":
                        row[field] = json.dumps(raw.get(field) or [], ensure_ascii=False, separators=(",", ":"))
                    elif field == "f4_passed":
                        row[field] = str(bool(raw.get(field)))
                    elif field in raw:
                        row[field] = raw[field]
            rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    family_overrides: dict[str, str] = {}
    for path in sorted(FUNDAMENTALS_DIR.glob("*.json")):
        raw = _read_json(path)
        ticker = str(raw.get("ticker") or path.stem).upper()
        name = str(raw.get("name") or "")
        if ticker in ACTUAL_FINANCIAL_RESTORE_TICKERS:
            family_overrides[ticker] = "FINANCIAL"
        elif ticker in MIGRATED_TICKERS or ticker == "001040" or (
            ticker not in AMBIGUOUS_HOLDING_TICKERS
            and str(raw.get("company_family") or "") == "FINANCIAL"
            and any(marker in name for marker in HOLDING_MARKERS)
            and not any(marker in name for marker in FINANCIAL_NAME_MARKERS)
        ):
            family_overrides[ticker] = "NON_FINANCIAL"
    for ticker in sorted(family_overrides):
        path = FUNDAMENTALS_DIR / f"{ticker}.json"
        raw = _read_json(path)
        family = family_overrides[ticker]
        f2, f3, f4, section = _rebuild_fundamentals(raw, family=family)
        raw["company_family"] = family
        raw["f2"] = f2
        raw["f3"] = f3
        raw["f4"] = f4
        raw["data_status"] = section["data_status"]
        raw["f2_data_status"] = _status(type("F2", (), {"quarter_coverage": f2["quarter_coverage"], "annual_coverage": f2["annual_coverage"], "canonical_observations": tuple(f2["quarters"] + f2["annuals"])})())
        raw["f3_data_status"] = section["data_status"]
        raw["f4_status"] = f4["status"]
        raw["f4_passed"] = bool(f4["passed"])
        raw["terminal_status"] = f4["status"]
        raw["terminal_reason"] = section["reason"]
        raw["f2_latest_quarter"] = f2["latest_quarter"]
        raw["f2_latest_fy"] = f2["latest_fy"]
        raw["f4_reasons"] = list(f4["reasons"])
        raw["f5_ready"] = section
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _update_reports(ticker, section)
        print(json.dumps({"ticker": ticker, "company_family": family, "data_status": section["data_status"], "f4_status": f4["status"]}, ensure_ascii=False))
    _update_ticker_index(set(family_overrides) | {"000120", "000700", "000640"})


if __name__ == "__main__":
    main()
