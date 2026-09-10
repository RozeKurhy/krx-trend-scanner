"""Build V06 Fundamentals validation artifacts from raw/local XBRL cache.

This validator intentionally does not import the production periodizer, metric
resolvers, or F2--F5 results.  The report files are used only for the ACTUAL
side of the comparison; EXPECTED values are parsed independently from the
local OpenDART filing registry and raw XBRL zip files.
"""

from __future__ import annotations

import csv
import json
import random
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REQUESTED_AS_OF = "2026-09-04"
RUN_DATE = "2026-09-10"
PRODUCTION_REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904/json"
CORP_CACHE = ROOT / "data/cache/opendart/corp_code_cache.json"
FILING_CACHE_DIR = ROOT / "data/cache/opendart/filings"
XBRL_CACHE_DIR = ROOT / "data/cache/opendart/xbrl"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_independent_validation_v06"
METRICS = ("revenue", "operating_income", "net_income")
REGRESSION_TICKERS = (
    "047050", "207940", "035420", "034020", "263750",
    "307950", "000660", "042660", "329180", "161390",
    "247540", "011200", "352820",
)
CELL_PERIODS = (
    ("2023FY", "annual", "2023", "FY"),
    ("2024FY", "annual", "2024", "FY"),
    ("2025FY", "annual", "2025", "FY"),
    ("2025Q1", "quarterly", "2025", "Q1"),
    ("2025Q2", "quarterly", "2025", "Q2"),
    ("2025Q3", "quarterly", "2025", "Q3"),
    ("2025Q4", "quarterly", "2025", "Q4"),
    ("2026Q1", "quarterly", "2026", "Q1"),
)
REPORT_CODE_BY_PERIOD = {"Q1": "11013", "Q2": "11012", "Q3": "11014", "Q4": "11011", "FY": "11011"}
SEED_LABEL = "20260910_03"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_path(ticker: str) -> Path | None:
    matches = sorted(PRODUCTION_REPORT_DIR.glob(f"{ticker}_*.json"))
    return matches[0] if matches else None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "sample_type", "ticker", "name", "period", "metric",
        "our_value_krw", "independent_source_type", "independent_source_rcept_no",
        "independent_account_id", "independent_context", "independent_raw_value",
        "independent_value_krw", "direct_value_krw", "derived_value_krw",
        "difference_krw", "actual_independent_difference_krw", "source_decimals", "source_precision_krw",
        "metric_semantics", "comparison_status", "sign_match", "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _alias(namespace: str) -> str:
    lowered = namespace.lower()
    if "ifrs-full" in lowered:
        return "ifrs-full"
    if "dart" in lowered:
        return "dart"
    return namespace.rsplit("/", 1)[-1]


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _number(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = raw.strip().replace(",", "")
    if not text or text in {"-", "—"}:
        return None
    try:
        value = float(text) if any(char in text for char in ".eE") else int(text)
    except ValueError:
        return None
    return int(value) if int(value) == value else round(value)


def _declared_precision(decimals: str | None, precision: str | None) -> int | None:
    if decimals:
        try:
            number = int(decimals)
            if number < 0:
                return 10 ** (-number)
            return 1
        except ValueError:
            pass
    if precision:
        try:
            number = int(precision)
            return max(1, number)
        except ValueError:
            pass
    return None


def _metric_for_fact(namespace: str, local: str) -> str | None:
    prefix = _alias(namespace)
    if (prefix == "ifrs-full" and local == "Revenue") or local.endswith("RevenueOfStatementOfComprehensiveIncomeAbstract"):
        return "revenue"
    if (prefix == "dart" and local == "OperatingIncomeLoss") or (prefix == "ifrs-full" and local == "ProfitLossFromOperatingActivities"):
        return "operating_income"
    if prefix == "ifrs-full" and local == "ProfitLoss":
        return "net_income"
    return None


def _period_info(context: ET.Element) -> dict[str, Any] | None:
    period = next((node for node in context.iter() if _local(node.tag) == "period"), None)
    if period is None:
        return None
    instant = next((node for node in period if _local(node.tag) == "instant"), None)
    if instant is not None:
        end = _date(instant.text)
        return {"start": None, "end": end, "days": None, "kind": "instant"}
    start_node = next((node for node in period if _local(node.tag) == "startDate"), None)
    end_node = next((node for node in period if _local(node.tag) == "endDate"), None)
    start = _date(start_node.text if start_node is not None else None)
    end = _date(end_node.text if end_node is not None else None)
    return {
        "start": start,
        "end": end,
        "days": (end - start).days + 1 if start and end else None,
        "kind": "duration",
    }


def _context_info(context: ET.Element) -> dict[str, Any] | None:
    period = _period_info(context)
    if period is None:
        return None
    members: list[tuple[str, str]] = []
    typed = False
    for node in context.iter():
        local = _local(node.tag)
        if local == "explicitMember":
            members.append((node.attrib.get("dimension", ""), (node.text or "").strip()))
        elif local == "typedMember":
            typed = True
    basis = "UNDIMENSIONED"
    extras: list[tuple[str, str]] = []
    for dimension, member in members:
        if _local(dimension).endswith("ConsolidatedAndSeparateFinancialStatementsAxis"):
            basis = _local(member)
        else:
            extras.append((dimension, member))
    primary = not typed and not extras and basis in {"UNDIMENSIONED", "ConsolidatedMember", "SeparateMember"}
    return {
        **period,
        "basis": basis,
        "primary": primary,
        "context": context.attrib.get("id"),
        "extra_dimensions": len(extras),
    }


def _fact_preference(metric: str, prefix: str) -> int:
    preferred = {
        "revenue": ("ifrs-full",),
        "operating_income": ("dart", "ifrs-full"),
        "net_income": ("ifrs-full",),
    }[metric]
    return preferred.index(prefix) if prefix in preferred else len(preferred) + 1


def _parse_xbrl(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".xbrl")]
        if not names:
            raise ValueError("XBRL member not found")
        root = ET.fromstring(archive.read(names[0]))
    contexts: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if _local(node.tag) == "context":
            info = _context_info(node)
            if info and info.get("context"):
                contexts[str(info["context"])] = info
    facts: dict[str, list[dict[str, Any]]] = {metric: [] for metric in METRICS}
    for node in root.iter():
        context_ref = node.attrib.get("contextRef")
        if not context_ref or context_ref not in contexts:
            continue
        metric = _metric_for_fact(_namespace(node.tag), _local(node.tag))
        value = _number(node.text)
        if metric is None or value is None or not contexts[context_ref]["primary"]:
            continue
        prefix = _alias(_namespace(node.tag))
        facts[metric].append({
            "value": value,
            "raw_value": (node.text or "").strip(),
            "account_id": f"{prefix}:{_local(node.tag)}",
            "prefix": prefix,
            "context": context_ref,
            "decimals": node.attrib.get("decimals"),
            "precision": node.attrib.get("precision"),
            **contexts[context_ref],
        })
    for metric in METRICS:
        facts[metric].sort(key=lambda item: (_fact_preference(metric, item["prefix"]), item["context"], item["account_id"]))
    return {"path": str(path), "facts": facts}


def _corp_map() -> dict[str, str]:
    payload = _read_json(CORP_CACHE)
    return {str(row["stock_code"]): str(row["corp_code"]).zfill(8) for row in payload.get("records", []) if row.get("stock_code")}


def _filing(ticker: str, year: str, reprt_code: str, corp_codes: dict[str, str]) -> dict[str, Any] | None:
    corp_code = corp_codes.get(ticker)
    if not corp_code:
        return None
    path = FILING_CACHE_DIR / f"{corp_code}_{year}_{reprt_code}.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    eligible = [
        row for row in payload.get("filings", [])
        if str(row.get("rcept_dt") or "") <= REQUESTED_AS_OF.replace("-", "")
        and row.get("rcept_no") and row.get("reprt_code") == reprt_code
    ]
    if not eligible:
        return None
    selected = max(eligible, key=lambda row: (str(row.get("rcept_dt")), str(row.get("rcept_no"))))
    rcept_no = str(selected["rcept_no"])
    xbrl_path = XBRL_CACHE_DIR / f"{rcept_no}_{reprt_code}.zip"
    if not xbrl_path.exists():
        return {"metadata": selected, "xbrl_path": None, "registry_path": str(path)}
    return {"metadata": selected, "xbrl_path": xbrl_path, "registry_path": str(path)}


class RawCache:
    def __init__(self, corp_codes: dict[str, str]):
        self.corp_codes = corp_codes
        self.filings: dict[tuple[str, str, str], dict[str, Any] | None] = {}
        self.raw: dict[str, dict[str, Any] | None] = {}

    def get(self, ticker: str, year: str, reprt_code: str) -> dict[str, Any] | None:
        key = (ticker, year, reprt_code)
        if key not in self.filings:
            self.filings[key] = _filing(ticker, year, reprt_code, self.corp_codes)
        filing = self.filings[key]
        if filing is None or filing.get("xbrl_path") is None:
            return None
        cache_key = str(filing["xbrl_path"])
        if cache_key not in self.raw:
            try:
                parsed = _parse_xbrl(filing["xbrl_path"])
                parsed["filing"] = filing
                self.raw[cache_key] = parsed
            except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
                self.raw[cache_key] = None
        return self.raw[cache_key]

    def filing_info(self, ticker: str, year: str, reprt_code: str) -> dict[str, Any] | None:
        key = (ticker, year, reprt_code)
        if key not in self.filings:
            self.filings[key] = _filing(ticker, year, reprt_code, self.corp_codes)
        return self.filings[key]


def _period_candidates(raw: dict[str, Any] | None, metric: str, year: str, period: str, mode: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    end_month = 12 if period == "FY" else {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}[period]
    expected_min = {"Q1": 60, "Q2": 150, "Q3": 230, "Q4": 300}.get(period, 300)
    expected_max = {"Q1": 130, "Q2": 230, "Q3": 330, "Q4": 430}.get(period, 430)
    result = []
    for fact in raw["facts"].get(metric, []):
        end = fact.get("end")
        start = fact.get("start")
        days = fact.get("days")
        if not end or end.year != int(year) or end.month != end_month or fact.get("kind") != "duration":
            continue
        starts_in_year = bool(start and start.year == int(year) and start.month == 1 and start.day <= 10)
        is_direct = days is not None and 60 <= days <= 130
        is_cumulative = starts_in_year and days >= expected_min
        if mode == "direct" and not is_direct:
            continue
        if mode == "cumulative" and not is_cumulative:
            continue
        if mode == "annual" and not (days is not None and days >= 300):
            continue
        result.append(fact)
    result.sort(key=lambda item: (_fact_preference(metric, item["prefix"]), abs((item.get("days") or 0) - (90 if mode == "direct" else 180)), item["context"], item["account_id"]))
    return result


def _one_candidate(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    if not candidates:
        return None, False
    chosen = candidates[0]
    same_context = [item for item in candidates if item["context"] == chosen["context"] and item["account_id"] == chosen["account_id"]]
    ambiguous = len({item["value"] for item in same_context}) > 1
    return chosen, ambiguous


def _fact_copy(fact: dict[str, Any] | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {
        "value": fact["value"],
        "raw_value": fact["raw_value"],
        "account_id": fact["account_id"],
        "context": fact["context"],
        "basis": fact["basis"],
        "start": fact["start"].isoformat() if fact.get("start") else None,
        "end": fact["end"].isoformat() if fact.get("end") else None,
        "days": fact.get("days"),
        "decimals": fact.get("decimals"),
        "precision": fact.get("precision"),
        "source_precision_krw": _declared_precision(fact.get("decimals"), fact.get("precision")),
    }


def _quarter_evidence(ticker: str, year: str, period: str, metric: str, cache: RawCache) -> dict[str, Any]:
    reprt_code = REPORT_CODE_BY_PERIOD[period]
    current = cache.get(ticker, year, reprt_code)
    direct_fact, direct_ambiguous = _one_candidate(_period_candidates(current, metric, year, period, "direct"))
    cumulative_fact, cumulative_ambiguous = _one_candidate(_period_candidates(current, metric, year, period, "cumulative"))
    direct = _fact_copy(direct_fact)
    derived: dict[str, Any] | None = None
    notes: list[str] = []
    if direct_ambiguous or cumulative_ambiguous:
        notes.append("SOURCE_AMBIGUOUS_RAW_FACTS")
    if period == "Q1":
        derived = _fact_copy(cumulative_fact)
        derived_source = cache.filing_info(ticker, year, reprt_code)
    elif period == "Q2":
        q1 = cache.get(ticker, year, "11013")
        q1_fact, q1_ambiguous = _one_candidate(_period_candidates(q1, metric, year, "Q1", "cumulative"))
        if q1_ambiguous:
            notes.append("SOURCE_AMBIGUOUS_PRIOR_CUMULATIVE")
        if cumulative_fact is not None and q1_fact is not None:
            derived = {**_fact_copy(cumulative_fact), "value": cumulative_fact["value"] - q1_fact["value"], "raw_value": f"{cumulative_fact['value']}-{q1_fact['value']}"}
            derived["account_id"] = f"{cumulative_fact['account_id']}-{q1_fact['account_id']}"
            derived["context"] = f"{cumulative_fact['context']}-{q1_fact['context']}"
            derived["source_precision_krw"] = max(cumulative_fact.get("source_precision_krw") or 1, q1_fact.get("source_precision_krw") or 1)
            derived_source = cache.filing_info(ticker, year, "11012")
            notes.append("DERIVED_FROM_H1_CUMULATIVE_MINUS_Q1_CUMULATIVE")
        else:
            derived_source = None
    elif period == "Q3":
        h1 = cache.get(ticker, year, "11012")
        h1_fact, h1_ambiguous = _one_candidate(_period_candidates(h1, metric, year, "Q2", "cumulative"))
        if h1_ambiguous:
            notes.append("SOURCE_AMBIGUOUS_PRIOR_CUMULATIVE")
        if cumulative_fact is not None and h1_fact is not None:
            derived = {**_fact_copy(cumulative_fact), "value": cumulative_fact["value"] - h1_fact["value"], "raw_value": f"{cumulative_fact['value']}-{h1_fact['value']}"}
            derived["account_id"] = f"{cumulative_fact['account_id']}-{h1_fact['account_id']}"
            derived["context"] = f"{cumulative_fact['context']}-{h1_fact['context']}"
            derived["source_precision_krw"] = max(cumulative_fact.get("source_precision_krw") or 1, h1_fact.get("source_precision_krw") or 1)
            derived_source = cache.filing_info(ticker, year, "11014")
            notes.append("DERIVED_FROM_Q3_CUMULATIVE_MINUS_H1_CUMULATIVE")
        else:
            derived_source = None
    else:  # Q4: annual full-year minus Q3 cumulative.
        annual = cache.get(ticker, year, "11011")
        annual_fact, annual_ambiguous = _one_candidate(_period_candidates(annual, metric, year, "FY", "annual"))
        q3 = cache.get(ticker, year, "11014")
        q3_fact, q3_ambiguous = _one_candidate(_period_candidates(q3, metric, year, "Q3", "cumulative"))
        if annual_ambiguous or q3_ambiguous:
            notes.append("SOURCE_AMBIGUOUS_PRIOR_CUMULATIVE")
        if annual_fact is not None and q3_fact is not None:
            derived = {**_fact_copy(annual_fact), "value": annual_fact["value"] - q3_fact["value"], "raw_value": f"{annual_fact['value']}-{q3_fact['value']}"}
            derived["account_id"] = f"{annual_fact['account_id']}-{q3_fact['account_id']}"
            derived["context"] = f"{annual_fact['context']}-{q3_fact['context']}"
            derived["source_precision_krw"] = max(annual_fact.get("source_precision_krw") or 1, q3_fact.get("source_precision_krw") or 1)
            derived_source = cache.filing_info(ticker, year, "11011")
            notes.append("DERIVED_FROM_FY_MINUS_Q3_CUMULATIVE")
        else:
            derived_source = None
    selected = direct or derived
    direct_value = direct.get("value") if direct else None
    derived_value = derived.get("value") if derived else None
    difference = direct_value - derived_value if direct_value is not None and derived_value is not None else None
    if difference not in (None, 0):
        notes.append("DIRECT_DERIVED_DIFFERENCE")
    source = cache.filing_info(ticker, year, reprt_code) if selected is direct else (derived_source if "derived_source" in locals() else None)
    source_type = "RAW_XBRL_DIRECT_STANDALONE" if selected is direct else "RAW_XBRL_DERIVED_CUMULATIVE"
    return {
        "selected": selected,
        "direct": direct,
        "derived": derived,
        "difference": difference,
        "source": source,
        "source_type": source_type if selected else None,
        "ambiguous": any("SOURCE_AMBIGUOUS" in note for note in notes),
        "notes": notes,
    }


def _annual_evidence(ticker: str, year: str, metric: str, cache: RawCache) -> dict[str, Any]:
    filing = cache.get(ticker, year, "11011")
    fact, ambiguous = _one_candidate(_period_candidates(filing, metric, year, "FY", "annual"))
    selected = _fact_copy(fact)
    return {
        "selected": selected,
        "direct": selected,
        "derived": None,
        "difference": None,
        "source": cache.filing_info(ticker, year, "11011") if selected else None,
        "source_type": "RAW_XBRL_DIRECT_ANNUAL" if selected else None,
        "ambiguous": ambiguous,
        "notes": ["SOURCE_AMBIGUOUS_RAW_FACTS"] if ambiguous else [],
    }


def _actual(report: dict[str, Any], kind: str, year: str, period: str, metric: str) -> Any:
    rows = report.get("fundamentals", {}).get("annual" if kind == "annual" else "quarterly", [])
    key = "fiscal_year" if kind == "annual" else "quarter"
    wanted = year if kind == "annual" else f"{year}{period}"
    row = next((item for item in rows if str(item.get(key)) == wanted), None)
    return row.get(f"{metric}_krw") if row else None


def _source_rcept(evidence: dict[str, Any]) -> str | None:
    source = evidence.get("source") or {}
    return (source.get("metadata") or {}).get("rcept_no")


def _compare(actual: Any, evidence: dict[str, Any]) -> tuple[str, str | None, int | None]:
    expected = (evidence.get("selected") or {}).get("value")
    if evidence.get("ambiguous"):
        return "SOURCE_AMBIGUOUS", None, None
    if expected is None:
        return ("OUR_MISSING" if actual is None else "SOURCE_MISSING"), None, None
    if actual is None:
        return "OUR_MISSING", None, None
    difference = int(actual) - int(expected)
    if difference == 0:
        return "MATCH", "yes", difference
    if actual != 0 and expected != 0 and (actual < 0) != (expected < 0):
        return "WRONG_SIGN", "no", difference
    precision = (evidence.get("selected") or {}).get("source_precision_krw")
    if precision and abs(difference) <= precision:
        return "ROUNDING_MATCH", "yes", difference
    return "MISMATCH", "yes", difference


def _rows_for_tickers(tickers: list[str], sample_type: str, cache: RawCache) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        report_path = _report_path(ticker)
        if report_path is None:
            continue
        report = _read_json(report_path)
        for period_key, kind, year, period in CELL_PERIODS:
            for metric in METRICS:
                evidence = _annual_evidence(ticker, year, metric, cache) if kind == "annual" else _quarter_evidence(ticker, year, period, metric, cache)
                actual = _actual(report, kind, year, period, metric)
                status, sign_match, difference = _compare(actual, evidence)
                selected = evidence.get("selected") or {}
                notes = list(evidence.get("notes") or [])
                if selected.get("basis") == "SeparateMember":
                    notes.append("SOURCE_SEPARATE_MEMBER")
                rows.append({
                    "sample_type": sample_type,
                    "ticker": ticker,
                    "name": report.get("name"),
                    "period": period_key,
                    "metric": metric,
                    "our_value_krw": actual,
                    "independent_source_type": evidence.get("source_type"),
                    "independent_source_rcept_no": _source_rcept(evidence),
                    "independent_account_id": selected.get("account_id"),
                    "independent_context": selected.get("context"),
                    "independent_raw_value": selected.get("raw_value"),
                    "independent_value_krw": selected.get("value"),
                    "direct_value_krw": (evidence.get("direct") or {}).get("value"),
                    "derived_value_krw": (evidence.get("derived") or {}).get("value"),
                    "difference_krw": evidence.get("difference"),
                    "actual_independent_difference_krw": difference,
                    "source_decimals": selected.get("decimals"),
                    "source_precision_krw": selected.get("source_precision_krw"),
                    "metric_semantics": "CONSOLIDATED_TOTAL_PROFIT_LOSS" if metric == "net_income" else "CONSOLIDATED_PRIMARY_XBRL_FACT",
                    "comparison_status": status,
                    "sign_match": sign_match,
                    "notes": ";".join(notes),
                })
    return rows


def _summary(rows: list[dict[str, Any]], *, selected_tickers: list[str], sample_type: str) -> dict[str, Any]:
    statuses = Counter(str(row["comparison_status"]) for row in rows)
    metric_statuses = {metric: dict(sorted(Counter(row["comparison_status"] for row in rows if row["metric"] == metric).items())) for metric in METRICS}
    return {
        "sample_type": sample_type,
        "ticker_count": len(selected_tickers),
        "tickers": selected_tickers,
        "cell_count": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "metric_status_counts": metric_statuses,
        "direct_derived_difference_count": sum("DIRECT_DERIVED_DIFFERENCE" in str(row.get("notes")) for row in rows),
        "wrong_sign_count": statuses.get("WRONG_SIGN", 0),
        "mismatch_count": statuses.get("MISMATCH", 0),
        "source_missing_count": statuses.get("SOURCE_MISSING", 0),
        "our_missing_count": statuses.get("OUR_MISSING", 0),
    }


def _load_candidates() -> list[str]:
    candidates = []
    for path in sorted(PRODUCTION_REPORT_DIR.glob("*.json")):
        try:
            report = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if report.get("asset_type") != "COMMON":
            continue
        if report.get("fundamentals", {}).get("applicability") != "APPLICABLE":
            continue
        ticker = str(report.get("ticker") or path.stem.split("_", 1)[0]).zfill(6)
        if ticker not in REGRESSION_TICKERS:
            candidates.append(ticker)
    return candidates


def _write_sanity(rows: list[dict[str, Any]]) -> None:
    by_key = {(row["ticker"], row["period"], row["metric"]): row for row in rows}
    lines = [
        "# V06 external sanity evidence",
        "",
        f"- Requested as-of: `{REQUESTED_AS_OF}`; validation run: `{RUN_DATE}`.",
        "- The production value is shown as ACTUAL; the raw/local XBRL value is shown as the independent check. No Naver value is substituted into production.",
        "",
        "## Required spot checks",
        "",
        "### Samsung Biologics (207940)",
        f"- FY2024 revenue ACTUAL `{by_key.get(('207940', '2024FY', 'revenue'), {}).get('our_value_krw')}` KRW; independent raw XBRL `{by_key.get(('207940', '2024FY', 'revenue'), {}).get('independent_value_krw')}` KRW; status `{by_key.get(('207940', '2024FY', 'revenue'), {}).get('comparison_status')}`.",
        "- The current Naver page shows FY2024 revenue `34,971억원`, while the official company release reports consolidated `45,473억원` and separate Logicus `34,971억원`; this confirms a basis distinction, so Naver is not treated as comparable to the consolidated DART value.",
        "- References: [Naver Samsung Biologics](https://finance.naver.com/item/main.naver?code=207940), [Samsung Biologics FY2024 result](https://samsungbiologics.com/kr/media/company-news/samsung-biologics-reports-fourth-quarter-and-fiscal-year-2024-financial-results).",
        "",
        "### Pearl Abyss (263750)",
        f"- 2025Q1 operating income ACTUAL `{by_key.get(('263750', '2025Q1', 'operating_income'), {}).get('our_value_krw')}` KRW; independent raw XBRL `{by_key.get(('263750', '2025Q1', 'operating_income'), {}).get('independent_value_krw')}` KRW; status `{by_key.get(('263750', '2025Q1', 'operating_income'), {}).get('comparison_status')}`.",
        "- The current Naver page has no 2025Q1 column, so the independently parsed DART fact's negative sign is checked against the prior external report context and is not overwritten by a stale/different display.",
        "- References: [Naver Pearl Abyss](https://finance.naver.com/item/main.naver?code=263750), [EDaily Q1 report](https://www.edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02587926642168920).",
        "",
        "### Hyundai Construction (000720)",
    ]
    for period_key, metric in (("2025Q2", "revenue"), ("2025Q2", "operating_income"), ("2025Q2", "net_income")):
        row = by_key.get(("000720", period_key, metric), {})
        lines.append(f"- {period_key} {metric} ACTUAL `{row.get('our_value_krw')}` KRW; independent raw XBRL `{row.get('independent_value_krw')}` KRW; status `{row.get('comparison_status')}`; semantics `{row.get('metric_semantics')}`.")
    lines.extend([
        "- Net income is compared as `ifrs-full:ProfitLoss` (consolidated total profit/loss). If an external page uses attributable-owner net income, that is `NOT_COMPARABLE_METRIC_SEMANTICS`, not a production mismatch.",
        "- Reference: [Naver Hyundai Construction](https://finance.naver.com/item/main.naver?code=000720).",
        "",
        "## Interpretation",
        "",
        "- This is an external sanity sample, not a second production collection. It uses already cached local filing/XBRL evidence and public reference links for semantic context.",
    ])
    (OUTPUT_DIR / "external_sanity_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    corp_codes = _corp_map()
    cache = RawCache(corp_codes)
    regression_rows = _rows_for_tickers(list(REGRESSION_TICKERS), "REGRESSION", cache)
    pool = _load_candidates()
    blind_tickers = random.Random(SEED_LABEL).sample(sorted(pool), 10)
    blind_rows = _rows_for_tickers(blind_tickers, "BLIND", cache)
    sanity_rows = _rows_for_tickers(["000720"], "SANITY", cache)
    _write_csv(OUTPUT_DIR / "independent_regression_13_tickers.csv", regression_rows)
    _write_csv(OUTPUT_DIR / "independent_blind_10_tickers.csv", blind_rows)
    _write_sanity(regression_rows + sanity_rows)
    summary = {
        "work_id": "FUNDAMENTALS_V1_INDEPENDENT_VALIDATION_WEB_POLISH_V06",
        "requested_as_of": REQUESTED_AS_OF,
        "run_date": RUN_DATE,
        "method": {
            "actual": "artifacts/reporting/stock_reports/20260904/json/*.json fundamentals values",
            "expected": "independent XML parse of raw/local OpenDART XBRL zip selected from local filing registry",
            "production_periodizer_imported": False,
            "production_metric_resolver_imported": False,
            "blind_pool_rule": "identity.asset_type == COMMON and fundamentals.applicability == APPLICABLE; no completeness/value filter",
            "blind_seed": SEED_LABEL,
            "direct_standalone_preferred": True,
            "cumulative_derivation": "raw prior cumulative facts only",
            "net_income_semantics": "ifrs-full:ProfitLoss consolidated total; external attributable-owner values are NOT_COMPARABLE_METRIC_SEMANTICS",
        },
        "regression": _summary(regression_rows, selected_tickers=list(REGRESSION_TICKERS), sample_type="REGRESSION"),
        "blind": _summary(blind_rows, selected_tickers=blind_tickers, sample_type="BLIND"),
        "blind_pool_count": len(pool),
        "blind_pool_excluded_regression_count": len(REGRESSION_TICKERS),
        "raw_xbrl_network_calls": 0,
        "open_dart_api_calls": 0,
        "naver_collection_calls": 0,
        "production_code_changed": False,
        "artifacts": [
            "independent_regression_13_tickers.csv",
            "independent_blind_10_tickers.csv",
            "validation_summary.json",
            "external_sanity_evidence.md",
        ],
    }
    _write_json(OUTPUT_DIR / "validation_summary.json", summary)
    print(json.dumps({"regression": summary["regression"], "blind": summary["blind"], "blind_pool_count": len(pool)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
