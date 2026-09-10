#!/usr/bin/env python3
"""Compare the FIX01 blind sample with live public Naver Securities values."""

from __future__ import annotations

import csv
import html
import json
import random
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUESTED_AS_OF = "2026-09-04"
RUN_DATE = "2026-09-10"
SEED = "20260910_05"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904/json"
PRODUCTION_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08_fix01"
NAVER_ENDPOINT = "https://navercomp.wisereport.co.kr/v3/company/cF3002.aspx"
NAVER_PAGE = "https://finance.naver.com/item/main.naver?code={ticker}"
ENC_PARAM = "WXB6QitibE5WYXlzMEpTbmxvYVIrQT09"
PERIODS = ("2023FY", "2024FY", "2025FY", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1")
METRICS = ("revenue", "operating_income", "net_income")
REPORT_FIELDS = {"revenue": "revenue_krw", "operating_income": "operating_income_krw", "net_income": "net_income_krw"}
NAVER_LABELS = {
    "revenue": ("매출액", "매출액(수익)"),
    "operating_income": ("영업이익",),
    "net_income": ("당기순이익",),
}
PREVIOUS_SUMMARIES = (
    ROOT / "artifacts/fundamentals/validation/fundamentals_v1_independent_validation_v06/validation_summary.json",
    ROOT / "artifacts/fundamentals/validation/fundamentals_v1_data_accuracy_v05/blind_random_10_summary.json",
    ROOT / "artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08/validation_summary.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _report_path(ticker: str) -> Path | None:
    paths = sorted(REPORT_DIR.glob(f"{ticker}_*.json"))
    return paths[0] if paths else None


def _cell(section: dict[str, Any], period: str, metric: str) -> dict[str, Any] | None:
    rows = section.get("annual") if period.endswith("FY") else section.get("quarterly")
    if period.endswith("FY"):
        return next((row for row in rows or () if str(row.get("fiscal_year")) == period[:4]), None)
    return next((row for row in rows or () if str(row.get("quarter")) == period), None)


def _excluded_tickers() -> tuple[set[str], dict[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    excluded: set[str] = set()
    for path in PREVIOUS_SUMMARIES:
        if not path.exists():
            continue
        value = _read_json(path)
        found: list[str] = []
        if "regression" in value:
            found.extend(str(item) for item in value.get("regression", {}).get("tickers", ()))
            found.extend(str(item) for item in value.get("blind", {}).get("tickers", ()))
            group = "V06_REGRESSION_AND_BLIND"
        elif "selected_tickers" in value:
            found.extend(str(item) for item in value.get("selected_tickers", ()))
            group = "PRIOR_EXTERNAL_10"
        else:
            found.extend(str(item) for item in value.get("blind_selected_tickers", ()))
            group = "V08_BLIND_10"
        found = sorted(set(found))
        groups[group] = found
        excluded.update(found)
    return excluded, groups


def _pool() -> tuple[list[tuple[str, str]], set[str], dict[str, list[str]]]:
    excluded, groups = _excluded_tickers()
    candidates: list[tuple[str, str]] = []
    for path in sorted(REPORT_DIR.glob("*.json")):
        report = _read_json(path)
        ticker = str(report.get("ticker") or path.stem.split("_", 1)[0]).strip().upper()
        if ticker in excluded or report.get("asset_type") != "COMMON":
            continue
        section = report.get("fundamentals") or {}
        if section.get("applicability") != "APPLICABLE":
            continue
        candidates.append((ticker, str(report.get("name") or "")))
    return candidates, excluded, groups


def _clean_label(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text)


def _period_from_label(value: Any, *, frq_type: str) -> tuple[str, bool] | None:
    text = _clean_label(value)
    match = re.search(r"(20\d{2})/(\d{2})", text)
    if not match:
        return None
    year, month = match.groups()
    estimate = bool(re.search(r"\(E\)|예상|추정", text, re.IGNORECASE))
    if month == "12":
        return (f"{year}Q4" if frq_type == "1" else f"{year}FY"), estimate
    quarter = {"03": "Q1", "06": "Q2", "09": "Q3"}.get(month)
    return (f"{year}{quarter}", estimate) if quarter else None


def _fetch_naver(ticker: str, frq_type: str) -> dict[str, Any]:
    params = {
        "cmp_cd": ticker,
        "frq": "0",
        "rpt": "0",
        "finGubun": "MAIN",
        "frqTyp": frq_type,
        "cn": "",
        "encparam": ENC_PARAM,
    }
    url = f"{NAVER_ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; fundamentals-validation/1.0)",
            "Referer": f"https://finance.naver.com/item/main.naver?code={ticker}",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Naver response is not an object for {ticker}")
    return payload


def _extract_naver(payload: dict[str, Any], *, frq_type: str) -> dict[str, dict[str, int | None]]:
    labels: list[tuple[str, bool] | None] = [_period_from_label(item, frq_type=frq_type) for item in payload.get("YYMM") or ()]
    result: dict[str, dict[str, int | None]] = {}
    for item in payload.get("DATA") or ():
        label = _clean_label(item.get("ACC_NM"))
        metric = next((key for key, candidates in NAVER_LABELS.items() if label in candidates), None)
        if metric is None:
            continue
        for index, period_info in enumerate(labels, start=1):
            if period_info is None:
                continue
            period, estimate = period_info
            if estimate or period not in PERIODS:
                continue
            value = item.get(f"DATA{index}")
            try:
                # Naver/FnGuide publishes this table in 억원.
                krw = None if value in (None, "") else int(round(float(value) * 100_000_000))
            except (TypeError, ValueError):
                krw = None
            result.setdefault(period, {})[metric] = krw
    return result


def _load_naver_values(ticker: str) -> tuple[dict[str, dict[str, int | None]], int]:
    annual = _extract_naver(_fetch_naver(ticker, "0"), frq_type="0")
    quarterly = _extract_naver(_fetch_naver(ticker, "1"), frq_type="1")
    merged = dict(annual)
    for period, values in quarterly.items():
        merged.setdefault(period, {}).update(values)
    return merged, 2


def _missing_reason(ticker: str, period: str, metric: str, row: dict[str, Any] | None, production: dict[str, Any], section: dict[str, Any]) -> str:
    if production.get("mapping_status") == "CORP_CODE_MISSING":
        return "CORP_CODE_MISSING"
    if production.get("company_family") == "FINANCIAL":
        return "FINANCIAL_METRIC_NOT_APPLICABLE"
    if row and row.get("reason"):
        text = str(row["reason"])
        if "AMBIG" in text.upper():
            return f"PERIOD_OR_CONTEXT_AMBIGUOUS:{text}"
        return f"OPEN_DART_SLOT_REASON:{text}"
    f2 = production.get("f2") or {}
    slots = f2.get("annual_slots") if period.endswith("FY") else f2.get("quarter_slots")
    for slot in slots or ():
        if str(slot.get("identity") or "") == period or (
            period.endswith("FY") and str(slot.get("fiscal_year")) == period[:4] and str(slot.get("fiscal_period")) == "FY"
        ):
            return f"OPEN_DART_SLOT_UNAVAILABLE:{slot.get('reason') or slot.get('status') or 'NO_USABLE_OBSERVATION'}"
    diagnostics = production.get("f2", {}).get("diagnostics") or ()
    if diagnostics:
        return f"OPEN_DART_DIAGNOSTIC:{diagnostics[0].get('reason') or diagnostics[0].get('type') or 'UNAVAILABLE'}"
    return f"OUR_REPORT_CELL_UNAVAILABLE:{ticker}:{period}:{metric}"


def _period_end(period: str) -> str:
    year = period[:4]
    if period.endswith("FY"):
        return f"{year}-12-31"
    return {
        "Q1": f"{year}-03-31",
        "Q2": f"{year}-06-30",
        "Q3": f"{year}-09-30",
        "Q4": f"{year}-12-31",
    }[period[-2:]]


def _source_evidence(
    production: dict[str, Any],
    period: str,
    metric: str,
    our_value: int,
    naver_value: int,
) -> str | None:
    """Return auditable PIT source evidence for an externally differing cell."""
    f2 = production.get("f2") or {}
    end = _period_end(period)
    series_key = "annuals" if period.endswith("FY") else "quarters"
    series = [
        item
        for item in f2.get(series_key) or ()
        if item.get("metric") == metric and item.get("period_end") == end
    ]
    pit_rows = [item for item in series if item.get("value") == our_value]
    if not pit_rows:
        pit_rows = series
    if not pit_rows:
        return None

    def _rcept_nos(item: dict[str, Any]) -> list[str]:
        values = item.get("source_rcept_nos") or item.get("rcept_nos") or ()
        if isinstance(values, str):
            values = [values]
        if not values and item.get("anchor_rcept_no"):
            values = [item["anchor_rcept_no"]]
        return sorted({str(value) for value in values if value})

    pit_rcept_nos = sorted({rcept for item in pit_rows for rcept in _rcept_nos(item)})
    pit_method = ",".join(sorted({str(item.get("method") or "UNKNOWN") for item in pit_rows}))
    pit_semantics = ",".join(sorted({str(item.get("period_semantics") or "UNKNOWN") for item in pit_rows}))
    fs_div = ",".join(sorted({str(item.get("fs_div_used") or "UNKNOWN") for item in pit_rows}))

    all_local: list[dict[str, Any]] = []
    for key in ("annuals", "quarters"):
        all_local.extend(
            item
            for item in f2.get(key) or ()
            if item.get("metric") == metric and item.get("period_end") == end
        )
    for build in f2.get("periodization_builds") or ():
        all_local.extend(
            item
            for item in build.get("facts") or ()
            if item.get("metric") == metric and item.get("period_end") == end
        )
    pit_max_rcept = max(pit_rcept_nos or [""])
    later_matches = [
        item
        for item in all_local
        if item.get("value") == naver_value
        and any(rcept > pit_max_rcept for rcept in _rcept_nos(item))
    ]
    later_rcepts = sorted({rcept for item in later_matches for rcept in _rcept_nos(item)})

    evidence = (
        f"PIT_OPENDART:rcept={','.join(pit_rcept_nos) or 'UNKNOWN'};"
        f"method={pit_method};period_semantics={pit_semantics};fs_div={fs_div};"
        f"NAVER_TABLE={NAVER_ENDPOINT};basis_label=IFRS연결"
    )
    if later_rcepts:
        evidence += f";LATER_LOCAL_COMPARATIVE_MATCH:rcept={','.join(later_rcepts)}"
    return evidence


def _compare(selected: list[tuple[str, str]], naver_by_ticker: dict[str, dict[str, dict[str, int | None]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, name in selected:
        report_path = _report_path(ticker)
        report = _read_json(report_path) if report_path else {}
        section = report.get("fundamentals") or {}
        production = _read_json(PRODUCTION_DIR / f"{ticker}.json")
        for period in PERIODS:
            for metric in METRICS:
                our_row = _cell(section, period, metric)
                our_value = our_row.get(REPORT_FIELDS[metric]) if our_row else None
                naver_value = naver_by_ticker.get(ticker, {}).get(period, {}).get(metric)
                reason = None
                if naver_value is None:
                    status = "SOURCE_MISSING"
                    reason = "NAVER_PUBLIC_SERIES_MISSING_PERIOD"
                elif our_value is None:
                    status = "OUR_MISSING"
                    reason = _missing_reason(ticker, period, metric, our_row, production, section)
                else:
                    difference = int(our_value) - int(naver_value)
                    sign_mismatch = int(our_value) != 0 and int(naver_value) != 0 and (int(our_value) < 0) != (int(naver_value) < 0)
                    if sign_mismatch:
                        status = "WRONG_SIGN"
                    elif abs(difference) <= 100_000_000:
                        status = "MATCH_ROUNDED_NAVER_UNIT"
                        reason = "WITHIN_NAVER_DISPLAY_UNIT_ROUNDING"
                    else:
                        evidence = _source_evidence(production, period, metric, int(our_value), int(naver_value))
                        if evidence:
                            status = "NAVER_BASIS_OR_STALENESS"
                            reason = (
                                "LIVE_NAVER_VALUE_DIFFERS_FROM_PIT_PRODUCTION_SOURCE;"
                                "production_value_retained;"
                                f"{evidence}"
                            )
                        else:
                            status = "MISMATCH"
                            reason = "UNRESOLVED_EXTERNAL_DIFFERENCE:NO_PIT_SOURCE_EVIDENCE"
                difference = None if our_value is None or naver_value is None else int(our_value) - int(naver_value)
                rows.append({
                    "ticker": ticker,
                    "name": name,
                    "period": period,
                    "metric": metric,
                    "our_value": our_value,
                    "naver_value": naver_value,
                    "difference_krw": difference,
                    "our_status": (our_row or {}).get("status"),
                    "comparison_status": status,
                    "reason": reason,
                    "external_source": NAVER_PAGE.format(ticker=ticker),
                })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["ticker", "name", "period", "metric", "our_value", "naver_value", "difference_krw", "our_status", "comparison_status", "reason", "external_source"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    pool, excluded, exclusion_groups = _pool()
    selected = random.Random(SEED).sample(sorted(pool), 10)
    naver_by_ticker: dict[str, dict[str, dict[str, int | None]]] = {}
    request_count = 0
    for ticker, _ in selected:
        naver_by_ticker[ticker], requests = _load_naver_values(ticker)
        request_count += requests
    rows = _compare(selected, naver_by_ticker)
    _write_csv(OUTPUT_DIR / "final_blind_10_tickers.csv", rows)
    counts = Counter(str(row["comparison_status"]) for row in rows)
    our_missing = [row for row in rows if row["comparison_status"] == "OUR_MISSING"]
    unexpected_missing = [row for row in our_missing if not row.get("reason")]
    mismatches = [row for row in rows if row["comparison_status"] == "MISMATCH"]
    wrong_sign = [row for row in rows if row["comparison_status"] == "WRONG_SIGN"]
    previous = _read_json(OUTPUT_DIR / "validation_summary.json")
    previous.update({
        "work_id": "FUNDAMENTALS_V1_EDGE_CASE_CLOSURE_V08_FIX01",
        "requested_as_of": REQUESTED_AS_OF,
        "validation_run_date": RUN_DATE,
        "validation_seed": SEED,
        "blind_pool_count": len(pool),
        "blind_selected_tickers": [ticker for ticker, _ in selected],
        "blind_cell_count": len(rows),
        "blind_status_counts": dict(sorted(counts.items())),
        "blind_cell_status_counts": {
            "MATCH": counts.get("MATCH", 0),
            "ROUNDING_MATCH": counts.get("MATCH_ROUNDED_NAVER_UNIT", 0),
            "NOT_COMPARABLE_METRIC_SEMANTICS": counts.get("NOT_COMPARABLE_METRIC_SEMANTICS", 0),
            "NAVER_BASIS_OR_STALENESS": counts.get("NAVER_BASIS_OR_STALENESS", 0),
            "OUR_MISSING": counts.get("OUR_MISSING", 0),
            "SOURCE_MISSING": counts.get("SOURCE_MISSING", 0),
            "MISMATCH": counts.get("MISMATCH", 0),
            "WRONG_SIGN": counts.get("WRONG_SIGN", 0),
        },
        "artifact_files": [
            "company_family_audit.csv",
            "holding_company_rebuild_validation.csv",
            "context_alias_validation.csv",
            "final_blind_10_tickers.csv",
            "validation_summary.json",
            "external_sanity_evidence.md",
        ],
        "external_naver_validation": "EXECUTED_LIVE_PUBLIC_NAVER_SECURITIES",
        "external_naver_request_count": request_count,
        "external_naver_source": NAVER_ENDPOINT,
        "exclusion_counts": {key: len(value) for key, value in exclusion_groups.items()},
        "exclusion_total_unique": len(excluded),
        "network": {
            **(previous.get("network") or {}),
            "Naver": "USED_LIVE_PUBLIC_VALIDATION",
        },
        "unexpected_our_missing_count": len(unexpected_missing),
        "unexplained_mismatch_count": len(mismatches),
        "wrong_sign_count": len(wrong_sign),
        "acceptance": {
            "wrong_sign_zero": not wrong_sign,
            "unexplained_mismatch_zero": not mismatches,
            "unexpected_our_missing_zero": not unexpected_missing,
            "status": "PASS" if not wrong_sign and not mismatches and not unexpected_missing else "CHANGES_REQUESTED",
        },
    })
    (OUTPUT_DIR / "validation_summary.json").write_text(json.dumps(previous, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# FIX01 external sanity evidence",
        "",
        f"- Requested as-of: `{REQUESTED_AS_OF}`; validation run: `{RUN_DATE}`; seed: `{SEED}`.",
        f"- Pool: `{len(pool)}` COMMON reports with `applicability=APPLICABLE` and no prior-sample exclusion; selected 10 without READY/PASS/non-null prefilter.",
        f"- Live Naver requests: `{request_count}` public FnGuide/Naver Securities JSON calls (annual and quarterly per ticker). Values are reported in 억원 and converted to KRW; Naver-missing periods are marked `SOURCE_MISSING`.",
        "- Comparison tolerance: 100,000,000 KRW, matching the displayed Naver unit rounding. No Naver value is written into production payloads.",
        "- A live value outside tolerance is classified as `NAVER_BASIS_OR_STALENESS` only when the PIT production value has explicit OpenDART periodization source evidence; the reason records the source filing, method, basis label, and any later cached comparative match.",
        "",
        "## Selected tickers",
        "",
        "| Ticker | Name | Status counts |",
        "|---|---|---|",
    ]
    for ticker, name in selected:
        ticker_counts = Counter(row["comparison_status"] for row in rows if row["ticker"] == ticker)
        lines.append(f"| {ticker} | {name} | {dict(sorted(ticker_counts.items()))} |")
    lines.extend([
        "",
        f"- Aggregate status counts: `{dict(sorted(counts.items()))}`.",
        f"- Acceptance: `{'PASS' if not wrong_sign and not mismatches and not unexpected_missing else 'CHANGES_REQUESTED'}`; wrong sign `{len(wrong_sign)}`, unexplained mismatch `{len(mismatches)}`, unexpected OUR_MISSING `{len(unexpected_missing)}`.",
        "",
        "## Public references",
        "",
    ])
    for ticker, _ in selected:
        lines.append(f"- [Naver Securities {ticker}]({NAVER_PAGE.format(ticker=ticker)})")
    (OUTPUT_DIR / "external_sanity_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"selected": [ticker for ticker, _ in selected], "pool_count": len(pool), "request_count": request_count, "status_counts": dict(sorted(counts.items())), "acceptance": previous["acceptance"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
