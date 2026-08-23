#!/usr/bin/env python3
"""Audit Q1 XBRL context ambiguity without changing periodization semantics.

The audit uses the production filing/PIT/XBRL path, keeps raw XML/ZIP files in
the ignored cache, and writes only context metadata plus source hashes.  It
does not import or call PyKRX/KRX.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/q1_context_ambiguity_audit"
ACCESS_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/access_v01/opendart_api_access_summary.json"
PRIOR_SUMMARY = ROOT / "artifacts/fundamentals/opendart/validation/derived_metrics_fix02_correction/derived_metrics_fix02_correction_summary.json"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_Q1_CONTEXT_AMBIGUITY_ROOT_CAUSE_AUDIT"
START_HEAD = "5dcc4d72090256d82d0d7116da62d9cf8021544f"
CUTOFF = "2026-08-20"
YEARS = ("2024", "2025")
TICKERS = ("005930", "237690", "005380", "000660", "035420", "068270", "012330")
NAMES = {
    "005930": "삼성전자", "237690": "에스티팜", "005380": "현대자동차",
    "000660": "SK하이닉스", "035420": "NAVER", "068270": "셀트리온",
    "012330": "현대모비스",
}
REPORT_CODES = ("11013", "11012", "11014")
REPORT_PERIOD = {"11013": "Q1", "11012": "Q2", "11014": "Q3"}
REPORT_END_MONTH_DAY = {"11013": "03-31", "11012": "06-30", "11014": "09-30"}
TARGET_CONCEPTS = {
    "Revenue": "revenue",
    "OperatingIncomeLoss": "operating_income",
    "ProfitLossFromOperatingActivities": "operating_income",
    "ProfitLoss": "net_income",
    "CashFlowsFromUsedInOperatingActivities": "operating_cash_flow",
}
METRICS = tuple(sorted(set(TARGET_CONCEPTS.values())))
TARGETED_FILES = (
    "tests/test_opendart_fundamentals_contract.py",
    "tests/test_opendart_fundamentals_core.py",
    "tests/test_opendart_fundamentals_core_fix01.py",
    "tests/test_opendart_fundamentals_core_fix02.py",
    "tests/test_opendart_fundamentals_periodization_v01.py",
    "tests/test_opendart_fundamentals_periodization_fix01.py",
    "tests/test_opendart_fundamentals_periodization_fix02.py",
    "tests/test_opendart_fundamentals_periodization_fix03.py",
    "tests/test_opendart_fundamentals_periodization_fix04.py",
    "tests/test_opendart_fundamentals_periodization_fix05.py",
    "tests/test_opendart_fundamentals_derived_metrics.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix01.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02.py",
    "tests/test_opendart_fundamentals_derived_metrics_fix02_correction.py",
    "tests/test_opendart_historical_promotion_detector.py",
    "tests/test_opendart_q1_context_ambiguity_audit.py",
)

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository  # noqa: E402
from trend_scanner.fundamentals.filing_registry import FilingRegistry  # noqa: E402
from trend_scanner.fundamentals.models import RegisteredFiling  # noqa: E402
from trend_scanner.fundamentals.opendart_client import OpenDartClient  # noqa: E402
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE  # noqa: E402
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation, PeriodizationFact, PeriodizationResult  # noqa: E402
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider, PeriodizationBuild  # noqa: E402
from trend_scanner.fundamentals.pit_resolver import PITResolver  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsProvider  # noqa: E402

from validate_opendart_derived_metrics_fix02 import _company_metadata, _date_text, _load_env, _synth  # noqa: E402
from validate_opendart_derived_metrics_fix02_correction import (  # noqa: E402
    _historical_detector,
    _margin_samples,
    _recompute_margin,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _prefix(namespace: str) -> str:
    if "xbrl.ifrs.org/taxonomy" in namespace:
        return "ifrs-full"
    if "dart-gcd" in namespace:
        return "dart-gcd"
    if "dart.fss.or.kr/taxonomy" in namespace:
        return "dart"
    return namespace.rsplit("/", 1)[-1] or "xbrl"


def _text(element: ET.Element, child_name: str) -> str | None:
    for child in element.iter():
        if _local(child.tag) == child_name:
            return (child.text or "").strip() or None
    return None


def _number(value: Any) -> int | float | None:
    if value in (None, "", "-", "—", "–"):
        return None
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def _duration_days(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except ValueError:
        return None


def _period_semantics(start: str | None, end: str | None, instant: str | None, fiscal_year: str) -> str:
    if instant and not start:
        return "INSTANT"
    days = _duration_days(start, end)
    if start == f"{fiscal_year}-01-01":
        return "CUMULATIVE_YTD"
    if days is not None and 60 <= days <= 110:
        return "STANDALONE_QUARTER"
    return "DURATION"


def _normalized_dimensions(context: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    explicit: list[dict[str, Any]] = []
    typed: list[dict[str, Any]] = []
    for item in context.iter():
        if _local(item.tag) == "explicitMember":
            explicit.append({"dimension": item.attrib.get("dimension"), "member": (item.text or "").strip()})
        elif _local(item.tag) == "typedMember":
            typed.append({
                "dimension": item.attrib.get("dimension"),
                "value": ET.tostring(item, encoding="unicode", short_empty_elements=True),
            })
    explicit.sort(key=lambda item: (str(item.get("dimension")), str(item.get("member"))))
    typed.sort(key=lambda item: (str(item.get("dimension")), str(item.get("value"))))
    return explicit, typed


def _context_record(context: ET.Element, fiscal_year: str, expected_end: str) -> dict[str, Any]:
    explicit, typed = _normalized_dimensions(context)
    start = _text(context, "startDate")
    end = _text(context, "endDate") or _text(context, "instant")
    instant = _text(context, "instant")
    entity = next((item for item in context.iter() if _local(item.tag) == "identifier"), None)
    identifier = (entity.text or "").strip() if entity is not None else None
    scheme = entity.attrib.get("scheme") if entity is not None else None
    basis = None
    for item in explicit:
        axis = str(item.get("dimension") or "").rsplit(":", 1)[-1]
        if axis in {"ConsolidatedAndSeparateFinancialStatementsAxis", "StatementInformationAxis"}:
            basis = str(item.get("member") or "").rsplit(":", 1)[-1]
            break
    other_explicit = [item for item in explicit if str(item.get("dimension") or "").rsplit(":", 1)[-1]
                      not in {"ConsolidatedAndSeparateFinancialStatementsAxis", "StatementInformationAxis"}]
    has_dimensions = bool(other_explicit or typed)
    primary = bool(basis in {"ConsolidatedMember", "SeparateMember"} and not has_dimensions and len(explicit) == 1)
    return {
        "context_id": context.attrib.get("id"), "period_start": start, "period_end": end,
        "instant": instant, "duration_days": _duration_days(start, end),
        "context_semantics": "INSTANT" if instant and not start else "DURATION" if start and end else "UNKNOWN",
        "period_semantics": _period_semantics(start, end, instant, fiscal_year),
        "entity_identifier": identifier, "entity_scheme": scheme,
        "dimensions_normalized": explicit + typed, "explicit_members": explicit, "typed_members": typed,
        "has_dimensions": has_dimensions, "segment_present": any(_local(item.tag) == "segment" for item in context),
        "scenario_present": any(_local(item.tag) == "scenario" for item in context),
        "basis": basis, "primary": primary, "current_candidate": end == expected_end,
    }


def semantic_fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "ticker": row.get("ticker"), "fiscal_year": row.get("fiscal_year"), "metric": row.get("metric"),
        "concept": row.get("concept"), "period_start": row.get("period_start"),
        "period_end": row.get("period_end"), "instant": row.get("instant"),
        "fs_div_used": row.get("fs_div_used"), "currency": row.get("currency"),
        "unit": row.get("unit"), "entity_identifier": row.get("entity_identifier"),
        "dimensions_normalized": row.get("dimensions_normalized", []),
        "segment_present": row.get("segment_present"), "scenario_present": row.get("scenario_present"),
        "period_semantics": row.get("period_semantics"), "comparative": row.get("comparative"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_context_group(rows: Iterable[dict[str, Any]]) -> str:
    values = list(rows)
    if not values:
        return "UNRESOLVED"
    by_context_concept_value: Counter[tuple[str, str, Any, str | None]] = Counter(
        (str(item.get("context_id")), str(item.get("concept")), item.get("value"), item.get("unit"))
        for item in values
    )
    if any(count > 1 for count in by_context_concept_value.values()):
        return "PARSER_DUPLICATION"
    by_fp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in values:
        by_fp[str(item.get("semantic_fingerprint"))].append(item)
    if len(by_fp) == 1 and len({item.get("value") for item in values}) == 1 and len({item.get("context_id") for item in values}) > 1:
        return "EXACT_SEMANTIC_DUPLICATE"
    if len({item.get("value") for item in values}) == 1:
        return "PRIMARY_TOTAL_PLUS_DIMENSIONED_DETAIL" if any(item.get("has_dimensions") for item in values) and any(
            not item.get("has_dimensions") for item in values) else "VALUE_EQUAL_BUT_SEMANTICALLY_DIFFERENT"
    return "VALUE_DIFFERENT_SEMANTICALLY_DIFFERENT"


def _raw_context_rows(artifact: Any, *, fiscal_year: str, reprt_code: str, selected_basis: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    zip_path = Path("data/cache/opendart/xbrl") / f"{artifact.rcept_no}_{artifact.reprt_code}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        xbrl_names = [name for name in archive.namelist() if name.lower().endswith(".xbrl")]
        root = ET.fromstring(archive.read(xbrl_names[0]))
    expected_end = f"{fiscal_year}-{REPORT_END_MONTH_DAY[reprt_code]}"
    selected_basis_member = "ConsolidatedMember" if selected_basis == "CFS" else "SeparateMember"
    contexts = {
        item.attrib.get("id"): _context_record(item, fiscal_year, expected_end)
        for item in root if _local(item.tag) == "context" and item.attrib.get("id")
    }
    units: dict[str, str | None] = {}
    for item in root:
        if _local(item.tag) != "unit" or not item.attrib.get("id"):
            continue
        measure = next((child for child in item.iter() if _local(child.tag) == "measure"), None)
        units[item.attrib["id"]] = (measure.text or "").strip() if measure is not None else None
    rows: list[dict[str, Any]] = []
    fact_occurrences: Counter[tuple[str, str, Any, str | None]] = Counter()
    for fact in root:
        local_name = _local(fact.tag)
        metric = TARGET_CONCEPTS.get(local_name)
        context_id = fact.attrib.get("contextRef")
        info = contexts.get(context_id)
        if metric is None or info is None or not info.get("current_candidate"):
            continue
        namespace = fact.tag.split("}", 1)[0].lstrip("{") if "}" in fact.tag else ""
        concept = f"{_prefix(namespace)}_{local_name}"
        unit = fact.attrib.get("unitRef")
        currency = units.get(unit) or unit
        row = {
            "ticker": artifact.ticker, "corp_code": artifact.corp_code, "company_family": None,
            "fiscal_year": fiscal_year, "reprt_code": reprt_code, "rcept_no": artifact.rcept_no,
            "rcept_dt": artifact.rcept_dt, "metric": metric, "account_id": concept, "concept": concept,
            "value": _number(fact.text), "currency": currency, "unit": unit, "fs_div_used": selected_basis,
            "context_id": context_id, "period_start": info.get("period_start"), "period_end": info.get("period_end"),
            "duration_days": info.get("duration_days"), "instant": info.get("instant"),
            "period_semantics": info.get("period_semantics"), "context_semantics": info.get("context_semantics"),
            "comparative": False, "entity_identifier": info.get("entity_identifier"),
            "dimensions_normalized": info.get("dimensions_normalized", []),
            "has_dimensions": info.get("has_dimensions"), "segment_present": info.get("segment_present"),
            "scenario_present": info.get("scenario_present"), "basis": info.get("basis"),
            "primary": info.get("primary"), "source_sha256": artifact.sha256,
            "fact_xml_node_count": None,
        }
        if info.get("basis") not in {"ConsolidatedMember", "SeparateMember"}:
            continue
        if str(info.get("basis")) != selected_basis_member:
            continue
        fact_occurrences[(str(context_id), concept, row["value"], unit)] += 1
        row["semantic_fingerprint"] = semantic_fingerprint(row)
        rows.append(row)
    for row in rows:
        row["fact_xml_node_count"] = fact_occurrences[(str(row["context_id"]), row["concept"], row["value"], row["unit"])]
    context_ids = {str(row.get("context_id")) for row in rows}
    context_xml = {
        context_id: {key: value for key, value in contexts[context_id].items()
                     if key not in {"current_candidate", "primary"}}
        for context_id in context_ids if context_id in contexts
    }
    context_target_counts = Counter(str(row.get("context_id")) for row in rows)
    context_target_concepts: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        context_target_concepts[str(row.get("context_id"))].append(str(row.get("concept")))
    for context_id, context_meta in context_xml.items():
        context_meta["target_fact_node_count"] = int(context_target_counts.get(str(context_id), 0))
        context_meta["target_fact_concepts"] = sorted(set(context_target_concepts.get(str(context_id), [])))
    return rows, {
        "rcept_no": artifact.rcept_no, "rcept_dt": artifact.rcept_dt, "reprt_code": reprt_code,
        "source_sha256": artifact.sha256, "context_count": len(context_xml), "contexts": context_xml,
        "raw_xbrl_fact_node_count": len(rows),
    }


def _selection_for(registry: FilingRegistry, resolver: PITResolver, corp: Any, ticker: str, year: str, code: str) -> tuple[Any, Any]:
    record = corp.get_record(ticker)
    filings = registry.list_regular_filings(ticker=ticker, corp_code=record.corp_code,
                                             bsns_year=year, reprt_code=code, as_of=CUTOFF)
    selection = resolver.resolve(filings, as_of=CUTOFF, bsns_year=year, reprt_code=code)
    return selection, record


def _selected_basis(filing: RegisteredFiling | None) -> str:
    value = str(filing.fs_div or "") if filing else ""
    return "OFS" if value in {"OFS", "SeparateMember"} else "CFS"


def _case_classification(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    primary = [item for item in rows if item.get("primary")]
    cumulative = [item for item in primary if item.get("period_semantics") == "CUMULATIVE_YTD"]
    direct = [item for item in primary if item.get("period_semantics") == "STANDALONE_QUARTER"]
    context_ids = sorted({str(item.get("context_id")) for item in primary})
    trigger_rows = cumulative if len({item.get("context_id") for item in cumulative}) > 1 else direct
    classification = classify_context_group(trigger_rows) if len({item.get("context_id") for item in trigger_rows}) > 1 else "UNRESOLVED"
    return classification, {
        "primary_rows": primary, "cumulative_context_ids": sorted({item.get("context_id") for item in cumulative}),
        "direct_standalone_context_ids": sorted({item.get("context_id") for item in direct}),
        "primary_context_count": len(context_ids), "primary_value_count": len({item.get("value") for item in primary}),
        "ambiguity_triggered": bool(len({item.get("context_id") for item in cumulative}) > 1
                                     or len({item.get("context_id") for item in direct}) > 1),
        "classification": classification,
    }


def _run_targeted_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TARGETED_FILES]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    return {"targeted_test_command": " ".join(command), "targeted_test_count": count,
            "targeted_test_status": "PASS" if completed.returncode == 0 and count else "FAIL",
            "targeted_test_returncode": completed.returncode, "targeted_test_output_tail": output[-1200:]}


def _company_metadata_for(ticker: str, metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if ticker in metadata and metadata[ticker]:
        return metadata[ticker]
    return {"company_family": "FINANCIAL" if ticker == "086790" else "NON_FINANCIAL"}


def _build_production(*, live: bool, env_file: Path) -> tuple[list[Any], OpenDartClient | None, list[dict[str, Any]]]:
    _load_env(env_file)
    client = OpenDartClient(api_key=os.getenv("OPENDART_API_KEY", "").strip()) if live else None
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    if not live:
        corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    registry = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    provider = DerivedMetricsProvider(PeriodizationProvider(corp, registry, xbrl))
    metadata = _company_metadata()
    if live:
        corp.ensure_loaded()
    builds: list[Any] = []
    errors: list[dict[str, Any]] = []
    for ticker in TICKERS:
        try:
            builds.append(provider.build(ticker, YEARS, CUTOFF,
                                         company_metadata=_company_metadata_for(ticker, metadata), force_refresh=False))
        except Exception as exc:
            errors.append({"ticker": ticker, "error_type": type(exc).__name__, "message": str(exc)})
    return builds, client, errors


def _historical_controls() -> dict[str, Any]:
    def fact(no: str, code: str = "11012") -> PeriodizationFact:
        return PeriodizationFact(
            ticker="FIX02-AUDIT", corp_code="FIX02-AUDIT", company_family="NON_FINANCIAL", fiscal_year="2024",
            metric="revenue", value=100, currency="KRW", reprt_code=code,
            report_type=REPORT_TYPE_BY_CODE.get(code, "UNKNOWN"), rcept_no=no, rcept_dt="2024-08-14",
            period_start="2024-01-01", period_end="2024-06-30", fs_div_used="CFS",
            source_sha256="sha", resolution_status="RESOLVED", period_semantics="CUMULATIVE_YTD",
            fiscal_year_start="2024-01-01", pit_available_from="2024-08-14",
        )

    def observation(no: str, code: str, period: str, *, sources: tuple[str, ...] = ()) -> PeriodizedFinancialObservation:
        return replace(_synth("revenue", "2024", period, 100, no=no, receipt="2024-08-14"),
                       ticker="FIX02-AUDIT", corp_code="FIX02-AUDIT",
                       source_rcept_nos=sources or (no,), source_rcept_dts=tuple("2024-08-14" for _ in (sources or (no,))),
                       source_sha256s=tuple("sha" for _ in (sources or (no,))))

    def make(selections: tuple[dict[str, Any], ...], facts: tuple[PeriodizationFact, ...], result: tuple[Any, ...], canonical: tuple[Any, ...]):
        period = PeriodizationBuild(
            ticker="FIX02-AUDIT", fiscal_year="2024", requested_as_of="2024-12-31", company_family="NON_FINANCIAL",
            filings=(), facts=facts, result=PeriodizationResult(result), anchor_selections=selections, skipped_anchors=(),
        )
        return SimpleNamespace(periodization_builds=(period,), canonical_observations=canonical)

    positive = make(
        ({"reprt_code": "11014", "status": "READY", "selected_rcept_no": "Q3-B",
          "prior_pit": {"selected_rcept_no": "H1-A"}},),
        (fact("H1-A"), fact("Q3-B", "11014")),
        (observation("Q3-B", "11014", "Q3", sources=("Q3-B", "H1-A")),),
        (observation("Q3-B", "11014", "Q3", sources=("Q3-B", "H1-A")),),
    )
    negative_ambiguous = make(
        ({"reprt_code": "11012", "status": "AMBIGUOUS", "selected_rcept_no": None},),
        (fact("H1-A"),), (observation("H1-A", "11012", "Q2"),), (observation("H1-A", "11012", "Q2"),),
    )
    negative_non_selected = make(
        ({"reprt_code": "11012", "status": "READY", "selected_rcept_no": "H1-B"},),
        (fact("H1-A"), fact("H1-B")), (observation("H1-A", "11012", "Q2"),), (observation("H1-A", "11012", "Q2"),),
    )
    positive_records, positive_count = _historical_detector((positive,))
    negative_a_records, negative_a_count = _historical_detector((negative_ambiguous,))
    negative_b_records, negative_b_count = _historical_detector((negative_non_selected,))
    return {
        "positive_control_violation_count": positive_count,
        "positive_control_allowed_historical_prior_source_count": sum(
            int(item.get("allowed_historical_prior_source_count", 0)) for item in positive_records
        ),
        "positive_control_records": positive_records,
        "negative_control_detected_count": negative_a_count + negative_b_count,
        "negative_control_ambiguous_current_records": negative_a_records,
        "negative_control_non_selected_current_records": negative_b_records,
        "status": "PASS" if positive_count == 0 and negative_a_count >= 1 and negative_b_count >= 1 else "FAIL",
    }


def _secret_and_raw_counts(key: str) -> tuple[int, bool]:
    secret = key.encode("utf-8") if key else b"__missing_key__"
    secret_count = sum(1 for path in ARTIFACT_DIR.rglob("*") if path.is_file() and secret in path.read_bytes())
    tracked = subprocess.run(["git", "ls-files", "data/cache/opendart"], cwd=ROOT, text=True,
                             capture_output=True, check=False)
    return secret_count, bool(tracked.stdout.strip())


def _safe_correction_implemented() -> bool:
    try:
        from trend_scanner.fundamentals.xbrl_repository import SEMANTIC_DUPLICATE_COLLAPSE_ENABLED
        return bool(SEMANTIC_DUPLICATE_COLLAPSE_ENABLED)
    except ImportError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path("/Users/june/Documents/projects/env.md"))
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _load_env(args.env_file)
    key = os.getenv("OPENDART_API_KEY", "").strip()
    targeted = _run_targeted_tests()
    if args.live and not key:
        summary = {"work_id": WORK_ID, "start_head": START_HEAD, "final_status": "BLOCKED_OPENDART_API_KEY",
                   "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"]}
        _write_json(ARTIFACT_DIR / "q1_context_audit_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    metadata = _company_metadata()
    client = OpenDartClient(api_key=key) if args.live else None
    corp = CorpCodeRepository(client, cache_path=ROOT / "data/cache/opendart/corp_code_cache.json")
    if not args.live:
        corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    registry = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
    resolver = PITResolver()
    xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    corp.ensure_loaded()

    inventory: list[dict[str, Any]] = []
    fingerprints: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    raw_audits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    primary_candidate_keys: set[tuple[str, str, str]] = set()
    example: dict[str, Any] | None = None

    for ticker in TICKERS:
        for year in YEARS:
            for code in REPORT_CODES:
                try:
                    selection, record = _selection_for(registry, resolver, corp, ticker, year, code)
                    selected = selection.selected
                    selections.append({
                        "ticker": ticker, "company": NAMES[ticker], "fiscal_year": year, "reprt_code": code,
                        "selected_rcept_no": selection.selected_rcept_no, "rcept_dt": selection.selected_rcept_dt,
                        "status": selection.status, "reason": selection.reason, "fs_div_used": _selected_basis(selected),
                        "requested_as_of": CUTOFF, "corp_code": record.corp_code,
                    })
                    if selected is None:
                        continue
                    artifact = xbrl.fetch(selected, force_refresh=False)
                    rows, raw_meta = _raw_context_rows(artifact, fiscal_year=year, reprt_code=code,
                                                        selected_basis=_selected_basis(selected))
                    for row in rows:
                        row["company_family"] = _company_metadata_for(ticker, metadata).get("company_family")
                        row["semantic_fingerprint"] = semantic_fingerprint(row)
                        inventory.append(row)
                    if code == "11013":
                        raw_audits.append({"ticker": ticker, "company": NAMES[ticker], "fiscal_year": year,
                                           "selected_filing": selections[-1], **raw_meta})
                        for metric in METRICS:
                            metric_rows = [item for item in rows if item["metric"] == metric]
                            if any(item.get("primary") for item in metric_rows) and any(not item.get("primary") for item in metric_rows):
                                primary_candidate_keys.add((ticker, year, metric))
                            classification, detail = _case_classification(metric_rows)
                            key_tuple = (ticker, year, metric, code)
                            fingerprints[key_tuple] = {"classification": classification, **detail}
                            if detail["ambiguity_triggered"] and example is None and classification == "EXACT_SEMANTIC_DUPLICATE":
                                example = {"ticker": ticker, "company": NAMES[ticker], "fiscal_year": year,
                                           "metric": metric, "classification": classification,
                                           "contexts": detail["primary_rows"]}
                            summaries.append({
                                "ticker": ticker, "company": NAMES[ticker], "company_family": _company_metadata_for(ticker, metadata).get("company_family"),
                                "fiscal_year": year, "reprt_code": code, "rcept_no": artifact.rcept_no,
                                "rcept_dt": artifact.rcept_dt, "fs_div_used": _selected_basis(selected),
                                "metric": metric, "ambiguity_triggered": detail["ambiguity_triggered"],
                                "cumulative_context_count": len(detail["cumulative_context_ids"]),
                                "direct_standalone_context_count": len(detail["direct_standalone_context_ids"]),
                                "primary_context_count": detail["primary_context_count"],
                                "primary_value_count": detail["primary_value_count"], "classification": classification,
                            })
                    for metric in METRICS:
                        metric_rows = [item for item in rows if item["metric"] == metric and item.get("primary")]
                        cumulative = sorted({item["context_id"] for item in metric_rows if item.get("period_semantics") == "CUMULATIVE_YTD"})
                        direct = sorted({item["context_id"] for item in metric_rows if item.get("period_semantics") == "STANDALONE_QUARTER"})
                        comparisons.append({"ticker": ticker, "company": NAMES[ticker], "fiscal_year": year,
                                            "reprt_code": code, "report_period": REPORT_PERIOD[code], "metric": metric,
                                            "selected_rcept_no": artifact.rcept_no, "fs_div_used": _selected_basis(selected),
                                            "current_cumulative_context_count": len(cumulative),
                                            "current_direct_standalone_context_count": len(direct),
                                            "current_context_count": len(set(cumulative + direct)),
                                            "current_cumulative_context_ids": "|".join(cumulative),
                                            "current_direct_standalone_context_ids": "|".join(direct)})
                except Exception as exc:
                    errors.append({"ticker": ticker, "fiscal_year": year, "reprt_code": code,
                                   "error_type": type(exc).__name__, "message": str(exc)})

    # Classification counts are per Q1 ticker/year/metric ambiguity case.
    case_counts = Counter(item["classification"] for item in summaries if item["ambiguity_triggered"])
    audit_controls = _historical_controls()
    builds, build_client, build_errors = _build_production(live=args.live, env_file=args.env_file)
    if client is None:
        client = build_client
    production_records, production_detector_count = _historical_detector(builds)
    results = [item for build in builds for item in build.result]
    margin_samples = [(build, item) for build in builds for item in _margin_samples(build)]
    margin_rechecks = [_recompute_margin(build, item) for build, item in margin_samples]
    margin_after = len(margin_rechecks)
    margin_mismatch = sum(bool(item["recalc_violation"]) for item in margin_rechecks)
    prior_summary = json.loads(PRIOR_SUMMARY.read_text(encoding="utf-8")) if PRIOR_SUMMARY.exists() else {}
    margin_before = int(prior_summary.get("production_ttm_margin_ready_count") or 0)
    safe_implemented = _safe_correction_implemented()
    exact_count = case_counts["EXACT_SEMANTIC_DUPLICATE"]
    value_equal_count = case_counts["VALUE_EQUAL_BUT_SEMANTICALLY_DIFFERENT"]
    true_count = case_counts["VALUE_DIFFERENT_SEMANTICALLY_DIFFERENT"]
    primary_count = len(primary_candidate_keys)
    parser_count = case_counts["PARSER_DUPLICATION"]
    unresolved_count = case_counts["UNRESOLVED"]
    if true_count or value_equal_count or unresolved_count:
        global_root = "MIXED_CONTEXT_SEMANTICS" if exact_count else "UNRESOLVED"
    elif primary_count and not exact_count:
        global_root = "PRIMARY_TOTAL_PATTERN"
    elif parser_count:
        global_root = "PARSER_DUPLICATION_PATTERN"
    else:
        global_root = "ALL_SAFE_EXACT_DUPLICATE"
    periodization_change_required = bool(exact_count and not (true_count or unresolved_count or value_equal_count or parser_count))
    if periodization_change_required and safe_implemented and margin_after >= margin_before:
        final_status = "READY_FOR_ARCHITECT_Q1_CONTEXT_CORRECTION_REVIEW"
    elif (true_count or value_equal_count or unresolved_count) and not safe_implemented:
        final_status = "READY_FOR_ARCHITECT_Q1_CONTEXT_LIMITATION_REVIEW"
    elif audit_controls["status"] != "PASS" or audit_controls["negative_control_detected_count"] < 2:
        final_status = "BLOCKED_HISTORICAL_PROMOTION_DETECTOR"
    else:
        final_status = "BLOCKED_Q1_CONTEXT_ROOT_CAUSE_UNRESOLVED"
    network = len(client.audit) if client is not None else 0
    registry_network = sum(item.get("endpoint") == "list.json" for item in client.audit) if client is not None else 0
    xbrl_network = sum(item.get("endpoint") == "fnlttXbrl.xml" for item in client.audit) if client is not None else 0
    secret_count, raw_source = _secret_and_raw_counts(key)
    summary = {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "implementation_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                               capture_output=True, check=False).stdout.strip(),
        "historical_detector_status": "PASS" if production_detector_count == 0 and audit_controls["status"] == "PASS" else "FAIL",
        "historical_positive_control_violation_count": audit_controls["positive_control_violation_count"],
        "historical_negative_control_detected_count": audit_controls["negative_control_detected_count"],
        "historical_production_violation_count": production_detector_count,
        "audit_ticker_count": len(TICKERS), "audit_fiscal_year_count": len(YEARS),
        "audit_metric_count": len(METRICS), "audit_context_count": len(inventory),
        "q1_ambiguous_case_count": sum(1 for item in summaries if item["ambiguity_triggered"]),
        "exact_semantic_duplicate_case_count": exact_count,
        "value_equal_semantic_diff_case_count": value_equal_count,
        "true_semantic_ambiguity_case_count": true_count,
        "primary_total_candidate_case_count": primary_count,
        "parser_duplication_case_count": parser_count,
        "unresolved_case_count": unresolved_count,
        "global_root_cause": global_root,
        "periodization_change_required": periodization_change_required,
        "periodization_change_reason": "Collapse only identical semantic fingerprint + identical value rows before Periodization; retain ambiguity on any semantic/value conflict.",
        "safe_semantic_deduplication_implemented": safe_implemented,
        "production_ttm_margin_before": margin_before, "production_ttm_margin_after": margin_after,
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch,
        "future_correction_leakage": "NO" if all(not any((_date_text(dt) or "9999-12-31") > CUTOFF for dt in item.source_rcept_dts)
                                                    for item in results) else "YES",
        "pykrx_krx_network_request_count": 0, "opendart_network_request_count": network,
        "opendart_registry_network_request_count": registry_network, "opendart_xbrl_network_request_count": xbrl_network,
        "targeted_test_count": targeted["targeted_test_count"], "targeted_test_status": targeted["targeted_test_status"],
        "targeted_test_returncode": targeted["targeted_test_returncode"], "secret_leak_count": secret_count,
        "raw_source_committed": raw_source, "production_build_error_count": len(build_errors),
        "audit_error_count": len(errors), "example_case": example,
        "final_status": final_status,
    }
    _write_csv(ARTIFACT_DIR / "q1_context_inventory.csv", inventory, [
        "ticker", "corp_code", "company_family", "fiscal_year", "reprt_code", "rcept_no", "rcept_dt", "metric",
        "account_id", "concept", "value", "currency", "unit", "fs_div_used", "context_id", "period_start",
        "period_end", "duration_days", "period_semantics", "context_semantics", "comparative", "entity_identifier",
        "dimensions_normalized", "has_dimensions", "segment_present", "scenario_present", "source_sha256",
        "semantic_fingerprint", "fact_xml_node_count",
    ])
    for row in inventory:
        row["dimensions_normalized"] = json.dumps(row.get("dimensions_normalized", []), ensure_ascii=False, sort_keys=True)
    _write_csv(ARTIFACT_DIR / "q1_context_inventory.csv", inventory, [
        "ticker", "corp_code", "company_family", "fiscal_year", "reprt_code", "rcept_no", "rcept_dt", "metric",
        "account_id", "concept", "value", "currency", "unit", "fs_div_used", "context_id", "period_start",
        "period_end", "duration_days", "period_semantics", "context_semantics", "comparative", "entity_identifier",
        "dimensions_normalized", "has_dimensions", "segment_present", "scenario_present", "source_sha256",
        "semantic_fingerprint", "fact_xml_node_count",
    ])
    fingerprint_rows: list[dict[str, Any]] = []
    for key_tuple, detail in fingerprints.items():
        rows = detail.get("primary_rows", [])
        grouped = defaultdict(list)
        for row in rows:
            grouped[row.get("semantic_fingerprint")].append(row)
        for fp, group in grouped.items():
            fingerprint_rows.append({"ticker": key_tuple[0], "fiscal_year": key_tuple[1], "metric": key_tuple[2],
                                     "reprt_code": key_tuple[3], "semantic_fingerprint": fp,
                                     "context_count": len({item.get("context_id") for item in group}),
                                     "value_count": len({item.get("value") for item in group}),
                                     "values": "|".join(sorted({str(item.get("value")) for item in group})),
                                     "context_ids": "|".join(sorted({str(item.get("context_id")) for item in group})),
                                     "classification": detail.get("classification")})
    _write_csv(ARTIFACT_DIR / "q1_context_fingerprints.csv", fingerprint_rows,
               ["ticker", "fiscal_year", "metric", "reprt_code", "semantic_fingerprint", "context_count", "value_count", "values", "context_ids", "classification"])
    _write_csv(ARTIFACT_DIR / "q1_ticker_year_metric_summary.csv", summaries, list(summaries[0].keys()) if summaries else ["ticker"])
    _write_csv(ARTIFACT_DIR / "q1_vs_q2_q3_context_count.csv", comparisons,
               ["ticker", "company", "fiscal_year", "reprt_code", "report_period", "metric", "selected_rcept_no", "fs_div_used",
                "current_cumulative_context_count", "current_direct_standalone_context_count", "current_context_count",
                "current_cumulative_context_ids", "current_direct_standalone_context_ids"])
    _write_json(ARTIFACT_DIR / "q1_context_classification.json", {
        "case_counts": dict(case_counts), "global_root_cause": global_root, "example_case": example,
        "summaries": summaries,
    })
    _write_json(ARTIFACT_DIR / "raw_xbrl_context_audit.json", {
        "policy": "metadata and SHA-256 only; raw XML/ZIP remains in ignored cache",
        "example_case": example, "selected_filing_contexts": raw_audits,
    })
    _write_json(ARTIFACT_DIR / "parser_duplication_audit.json", {
        "parser_duplication_case_count": parser_count,
        "raw_fact_node_duplicate_count": sum(1 for row in inventory if int(row.get("fact_xml_node_count") or 0) > 1),
        "status": "PASS" if parser_count == 0 else "REVIEW_REQUIRED",
    })
    _write_json(ARTIFACT_DIR / "historical_promotion_detector_validation.json", {
        "production_violation_count": production_detector_count, "records": production_records,
        "positive_control_violation_count": audit_controls["positive_control_violation_count"],
        "negative_control_detected_count": audit_controls["negative_control_detected_count"],
        "allowed_historical_prior_source_count": audit_controls["positive_control_allowed_historical_prior_source_count"],
        "status": summary["historical_detector_status"],
    })
    _write_json(ARTIFACT_DIR / "historical_promotion_negative_control.json", audit_controls)
    _write_json(ARTIFACT_DIR / "production_ttm_margin_recheck.json", {
        "production_ttm_margin_before": margin_before, "production_ttm_margin_after": margin_after,
        "production_ttm_margin_recalc_mismatch_count": margin_mismatch, "samples": margin_rechecks,
        "status": "PASS" if margin_mismatch == 0 and (margin_after > 0 or periodization_change_required) else "BLOCKED_PRODUCTION_INPUT",
    })
    _write_json(ARTIFACT_DIR / "q1_context_audit_summary.json", summary)
    manifest_files = [path for path in sorted(ARTIFACT_DIR.iterdir()) if path.name != "q1_context_audit_manifest.json"]
    _write_json(ARTIFACT_DIR / "q1_context_audit_manifest.json", {
        "work_id": WORK_ID, "start_head": START_HEAD,
        "files": {path.name: _sha(path) for path in manifest_files},
        "request_accounting": {"network": network, "registry": registry_network, "xbrl_network_fetch": xbrl_network},
        "pykrx_krx_network_request_count": 0,
        "raw_source_policy": "Raw OpenDART ZIP/XML remains in ignored data/cache and is not committed.",
        "secret_policy": "OPENDART_API_KEY is environment-only and never written.",
        "final_status": final_status,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if final_status.startswith("READY_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
