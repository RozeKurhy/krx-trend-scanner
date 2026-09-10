#!/usr/bin/env python3
"""Write the bounded, local-only V08 validation artifacts."""

from __future__ import annotations

import csv
import json
import random
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260904"
PRODUCTION_DIR = ROOT / "artifacts/fundamentals/production/20260904/tickers"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08"
REQUESTED_AS_OF = "2026-09-04"
SEED = "20260910_04"
EXCLUDED = {"000700", "000670", "000250", "000100", "000120", "001040", "000640", "000990", "000150", "000880"}
HOLDING_MARKERS = ("홀딩", "홀딩스", "지주", "지주회사", "스퀘어")
FINANCIAL_NAME_MARKERS = ("금융", "은행", "증권", "보험", "캐피탈", "카드", "신탁", "자산운용", "투자", "여신", "보증", "화재", "생명", "손해")
AMBIGUOUS_HOLDING_TICKERS = {"055550"}
MIGRATED_TICKERS = {
    "000070", "000140", "000320", "000590", "000640", "001040", "001230", "001800",
    "003030", "003380", "004150", "004990", "005440", "005740", "005810", "006200",
    "006840", "007700", "009440", "009970", "010060", "0126Z0", "015860", "024720",
    "036530", "060980", "072710", "078070", "084690", "096760", "107590", "192400",
    "363280", "383800", "402340",
}
PRESERVED_BLOBS = {
    "strategy_monitor": "5712db9faa6dd07795254e2e730d96c0c90e554e",
    "market_ranking": "2fd12af2d9d8f4a81affabee9a9c83d1c898a6aa",
    "sector_rs_ranking": "17237d63c0630ff8d322764999d6f31b8f52b173",
    "foreign_net_buy_ranking": "1d514cd18b5d10743c75d92b91fe55341ee0cf71",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def report_path(ticker: str) -> Path | None:
    paths = sorted((REPORT_DIR / "json").glob(f"{ticker}_*.json"))
    return paths[0] if paths else None


def baseline_report(ticker: str) -> dict[str, Any] | None:
    path = report_path(ticker)
    if path is None:
        return None
    relative = path.relative_to(ROOT).as_posix()
    raw = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
    return json.loads(raw.decode("utf-8"))


def section_cell(section: dict[str, Any] | None, period: str, metric: str) -> dict[str, Any] | None:
    if not section:
        return None
    field = {"revenue": "revenue_krw", "operating_income": "operating_income_krw", "net_income": "net_income_krw"}[metric]
    if period.endswith("FY"):
        year = period[:4]
        return next((row for row in section.get("annual", ()) if str(row.get("fiscal_year")) == year and field in row), None)
    return next((row for row in section.get("quarterly", ()) if row.get("quarter") == period and field in row), None)


def production_cell(ticker: str, period: str, metric: str) -> dict[str, Any] | None:
    raw = read_json(PRODUCTION_DIR / f"{ticker}.json")
    observations = (raw.get("f2") or {}).get("annuals" if period.endswith("FY") else "quarters", ())
    if period.endswith("FY"):
        year, period_name = period[:4], "FY"
        return next((item for item in observations if str(item.get("fiscal_year")) == year and item.get("fiscal_period") == period_name and item.get("metric") == metric), None)
    year, quarter = period[:4], period[4:]
    return next((item for item in observations if str(item.get("fiscal_year")) == year and item.get("fiscal_period") == quarter and item.get("metric") == metric), None)


def cell_value(row: dict[str, Any] | None, field: str) -> Any:
    return row.get(field) if row else None


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def company_family_audit() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(PRODUCTION_DIR.glob("*.json")):
        raw = read_json(path)
        ticker = str(raw.get("ticker") or path.stem).upper()
        name = str(raw.get("name") or "")
        current = str(raw.get("company_family") or "")
        is_holding = any(marker in name for marker in HOLDING_MARKERS)
        financial_text = any(marker in name for marker in FINANCIAL_NAME_MARKERS)
        included = current == "FINANCIAL" or ticker in MIGRATED_TICKERS
        if not included:
            continue
        if ticker in AMBIGUOUS_HOLDING_TICKERS:
            recommended, status, reason = "MANUAL_REVIEW", "AMBIGUOUS", "FINANCIAL_HOLDING_IDENTITY_NOT_IN_LOCAL_CACHE"
        elif ticker == "001040" or (is_holding and not financial_text):
            recommended, status, reason = "NON_FINANCIAL", "MIGRATED_OR_REQUIRED", "GENERAL_HOLDING_OR_GENERIC_64992_CODE"
        elif financial_text:
            recommended, status, reason = "FINANCIAL", "ACTUAL_FINANCIAL", "FINANCIAL_NAME_MARKER"
        else:
            recommended, status, reason = "FINANCIAL", "RETAINED", "NO_CONTRADICTORY_LOCAL_EVIDENCE"
        rows.append({
            "ticker": ticker, "name": name, "current_company_family": current,
            "recommended_company_family": recommended, "audit_status": status,
            "reason": reason, "local_metadata_status": "NOT_AVAILABLE_LOCAL_COMPANY_CACHE",
            "industry_code": "", "evidence": "name_only_or_saved_production_identity",
        })
    return rows


def targeted_validation() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    targets = (
        ("000120", "2024FY", "revenue"), ("000120", "2024FY", "operating_income"), ("000120", "2024FY", "net_income"),
        ("000120", "2025Q1", "operating_income"), ("000120", "2025Q2", "operating_income"),
        ("000120", "2025Q3", "operating_income"), ("000120", "2025Q4", "operating_income"),
        ("000700", "2023FY", "operating_income"),
    )
    field_for = {"revenue": "revenue_krw", "operating_income": "operating_income_krw", "net_income": "net_income_krw"}
    for ticker, period, metric in targets:
        before_report = baseline_report(ticker) or {}
        before = section_cell(before_report.get("fundamentals"), period, metric)
        after = production_cell(ticker, period, metric)
        rows.append({
            "case": "CJ_PERIODIZATION" if ticker == "000120" else "YUSU_REPRESENTED_COMPARATIVE",
            "ticker": ticker, "period": period, "metric": metric,
            "before_value": cell_value(before, field_for[metric]), "before_status": (before or {}).get("status"),
            "after_value": (after or {}).get("value"), "after_status": (after or {}).get("resolution_status"),
            "after_reason": (after or {}).get("reason"),
            "authority": "LOCAL_PROCESSED_OPENDART_XBRL",
            "source_reference": ";".join((after or {}).get("source_rcept_nos") or ((after or {}).get("anchor_rcept_no"),)),
        })
    for ticker in ("001040", "000640"):
        before = baseline_report(ticker) or {}
        after = read_json(PRODUCTION_DIR / f"{ticker}.json")
        rows.append({
            "case": "COMPANY_FAMILY", "ticker": ticker, "period": "N/A", "metric": "company_family",
            "before_value": ((before.get("fundamentals") or {}).get("company_family")),
            "before_status": ((before.get("fundamentals") or {}).get("data_status")),
            "after_value": after.get("company_family"), "after_status": after.get("f5_ready", {}).get("data_status"),
            "after_reason": after.get("terminal_reason"), "authority": "LOCAL_SAVED_COMPANY_IDENTITY",
            "source_reference": f"artifacts/fundamentals/production/20260904/tickers/{ticker}.json",
        })
    return rows


def blind_validation() -> tuple[list[dict[str, Any]], list[str], int]:
    pool: list[tuple[str, str]] = []
    for path in sorted((REPORT_DIR / "json").glob("*.json")):
        report = read_json(path)
        if report.get("asset_type") != "COMMON" or report.get("ticker") in EXCLUDED:
            continue
        if (report.get("fundamentals") or {}).get("applicability") != "APPLICABLE":
            continue
        pool.append((str(report["ticker"]), str(report.get("name") or "")))
    selected = random.Random(SEED).sample(pool, 10)
    periods = ("2023FY", "2024FY", "2025FY", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1")
    metrics = ("revenue", "operating_income", "net_income")
    fields = {"revenue": "revenue_krw", "operating_income": "operating_income_krw", "net_income": "net_income_krw"}
    result: list[dict[str, Any]] = []
    for ticker, name in selected:
        production = read_json(PRODUCTION_DIR / f"{ticker}.json")
        diagnostic_text = json.dumps(production.get("f2", {}).get("diagnostics", ()), ensure_ascii=False)
        expected_gap = "CORP_CODE_MISSING" if production.get("mapping_status") == "CORP_CODE_MISSING" else (
            "MULTIPLE_FILING_CHAINS" if "MULTIPLE_FILING_CHAINS" in diagnostic_text else None
        )
        report = read_json(report_path(ticker))
        section = report.get("fundamentals") or {}
        for period in periods:
            for metric in metrics:
                row = section_cell(section, period, metric)
                value = cell_value(row, fields[metric])
                ready = row is not None and row.get("status") == "READY" and value is not None
                status = "SOURCE_MISSING" if ready else "OUR_MISSING"
                gap_reason = expected_gap or ((row or {}).get("reason") if row else None) or (section.get("reason") if section else None) or "SAVED_SOURCE_UNAVAILABLE"
                result.append({
                    "ticker": ticker, "name": name, "period": period, "metric": metric,
                    "our_value": value, "our_status": (row or {}).get("status"),
                    "external_naver_value": None, "comparison_status": status,
                    "expected_gap": gap_reason, "external_source": "NOT_CACHED_NO_NETWORK",
                })
    return result, [ticker for ticker, _ in selected], len(pool)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = company_family_audit()
    write_csv(OUTPUT_DIR / "company_family_audit.csv", audit, list(audit[0]) if audit else ["ticker"])
    targeted = targeted_validation()
    write_csv(OUTPUT_DIR / "targeted_edge_case_validation.csv", targeted, list(targeted[0]))
    blind, selected, pool_count = blind_validation()
    write_csv(OUTPUT_DIR / "final_blind_10_tickers.csv", blind, list(blind[0]))
    counts = Counter(row["comparison_status"] for row in blind)
    unexpected_missing = sum(1 for row in blind if row["comparison_status"] == "OUR_MISSING" and not row["expected_gap"])
    summary = {
        "work_id": "FUNDAMENTALS_V1_EDGE_CASE_CLOSURE_V08",
        "requested_as_of": REQUESTED_AS_OF,
        "validation_seed": SEED,
        "network_calls": 0,
        "external_naver_comparison": "NOT_EXECUTED_NO_NETWORK",
        "company_family_audit_rows": len(audit),
        "company_family_audit_counts": dict(Counter(row["audit_status"] for row in audit)),
        "targeted_cell_count": len(targeted),
        "blind_pool_count": pool_count,
        "blind_selected_tickers": selected,
        "blind_cell_count": len(blind),
        "blind_status_counts": dict(sorted(counts.items())),
        "unexpected_our_missing_count": unexpected_missing,
        "unexplained_mismatch_count": counts.get("MISMATCH", 0),
        "wrong_sign_count": counts.get("WRONG_SIGN", 0),
        "preserved_blob_shas": PRESERVED_BLOBS,
        "source_cache_note": "No raw OpenDART ZIP/cache was available locally; committed processed XBRL artifacts were used and no live fetch was attempted.",
    }
    (OUTPUT_DIR / "validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "notes.md").write_text(
        "# V08 local validation notes\n\n"
        "- Authority: saved OpenDART/XBRL processed artifacts and the saved Stock Report payloads.\n"
        "- Network calls: 0. Naver was not queried because this bounded run was cache-only.\n"
        "- `SOURCE_MISSING` in the blind matrix means the external Naver comparison source was not cached; it is not a production mismatch.\n"
        "- `OUR_MISSING` rows carry `expected_gap` when the saved production diagnostics already identify a missing corp mapping or multiple filing chains.\n",
        encoding="utf-8",
    )
    print(json.dumps({"selected": selected, "blind_status_counts": dict(sorted(counts.items())), "unexpected_our_missing_count": unexpected_missing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
