#!/usr/bin/env python3
"""Validate representative Fundamentals V1 V02 outputs against public IR/DART samples."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = ROOT / "artifacts/fundamentals/production/20260904"
OUTPUT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_full_authority_audit_v02"


def _load(ticker: str) -> dict[str, Any]:
    return json.loads((PRODUCTION_DIR / "tickers" / f"{ticker}.json").read_text(encoding="utf-8"))


def _period(ticker: str, identity: str, *, annual: bool = False) -> dict[str, Any]:
    data = _load(ticker)["f5_ready"]["annual" if annual else "quarterly"]
    key = "fiscal_year" if annual else "quarter"
    return next(row for row in data if row[key] == identity)


def _external_row(
    *, ticker: str, company: str, period: str, metric: str, actual: float | int,
    reference: float | int, tolerance: float | int, source_url: str,
    expected_status: str | None = None, actual_status: str | None = None,
) -> dict[str, Any]:
    delta = abs(float(actual) - float(reference))
    status_ok = expected_status is None or actual_status == expected_status
    return {
        "ticker": ticker, "company": company, "period": period, "metric": metric,
        "source_kind": "OFFICIAL_IR", "source_url": source_url,
        "actual_value": actual, "reference_value": reference, "tolerance": tolerance,
        "absolute_delta": delta, "expected_status": expected_status,
        "actual_status": actual_status,
        "result": "PASS" if delta <= tolerance and status_ok else "FAIL",
    }


def main() -> int:
    rows: list[dict[str, Any]] = []
    coway = _load("021240")
    q1 = next(
        item for build in coway["f2"]["periodization_builds"]
        for item in build["anchor_selections"]
        if build["fiscal_year"] == "2024" and item["reprt_code"] == "11013"
    )
    rows.append({
        "ticker": "021240", "company": "코웨이", "period": "2024Q1",
        "metric": "PIT authority receipt", "source_kind": "OFFICIAL_DART_RECEIPT",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240514001464",
        "actual_value": q1.get("selected_rcept_no"), "reference_value": "20240514001464",
        "tolerance": "exact", "absolute_delta": "0", "expected_status": "READY",
        "actual_status": q1.get("status"),
        "result": "PASS" if q1.get("selected_rcept_no") == "20240514001464" and q1.get("status") == "READY" else "FAIL",
    })
    rows.extend([
        _external_row(
            ticker="021240", company="코웨이", period="2024FY", metric="operating_income_krw",
            actual=_period("021240", "2024", annual=True)["operating_income_krw"],
            reference=795400000000, tolerance=500000000,
            source_url="https://company.coway.com/newsroom/press/729",
        ),
        _external_row(
            ticker="021240", company="코웨이", period="2024Q4", metric="operating_income_krw",
            actual=_period("021240", "2024Q4")["operating_income_krw"],
            reference=183400000000, tolerance=500000000,
            source_url="https://company.coway.com/newsroom/press/729",
        ),
    ])
    nhn_source = "https://www.nhn.com/ko_/ir/EarningsRelease/2025/4Q24_NHN_Earnings%20Release_FinaL_KOR.pdf"
    for period, reference, expected_status in (
        ("2024Q1", 27287000000, "PERCENT"),
        ("2024Q2", 28477000000, "PERCENT"),
        ("2024Q3", -113389000000, "TURNED_TO_LOSS"),
        ("2024Q4", 25005000000, "TURNED_TO_PROFIT"),
    ):
        item = _period("181710", period)
        rows.append(_external_row(
            ticker="181710", company="NHN", period=period, metric="operating_income_krw",
            actual=item["operating_income_krw"], reference=reference, tolerance=500000000,
            source_url=nhn_source, expected_status=expected_status,
            actual_status=item.get("operating_income_yoy_status"),
        ))
    rows.append(_external_row(
        ticker="181710", company="NHN", period="2024FY", metric="operating_income_krw",
        actual=_period("181710", "2024", annual=True)["operating_income_krw"],
        reference=-32620000000, tolerance=500000000, source_url=nhn_source,
        expected_status="TURNED_TO_LOSS", actual_status=_period("181710", "2024", annual=True).get("operating_income_yoy_status"),
    ))
    samsung_source = "https://www.samsung.com/sec/sustainability/digital-library/facts-figures/"
    samsung_fy = _period("005930", "2025", annual=True)
    rows.extend([
        _external_row(
            ticker="005930", company="삼성전자", period="2025FY", metric="revenue_krw",
            actual=samsung_fy["revenue_krw"], reference=333600000000000, tolerance=500000000000,
            source_url=samsung_source,
        ),
        _external_row(
            ticker="005930", company="삼성전자", period="2025FY", metric="operating_income_krw",
            actual=samsung_fy["operating_income_krw"], reference=43600000000000, tolerance=100000000000,
            source_url=samsung_source,
        ),
    ])

    precision_build = next(
        build for build in _load("003070")["f2"]["periodization_builds"]
        if build["fiscal_year"] == "2024" and build.get("precision_equivalent_group_count", 0) > 0
    )
    rows.append({
        "ticker": "003070", "company": "코오롱글로벌", "period": "2024",
        "metric": "precision equivalent alias collapse", "source_kind": "LOCAL_AUTHORITY_ASSERT",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250318001458",
        "actual_value": precision_build["precision_equivalent_group_count"],
        "reference_value": ">=1", "tolerance": "exact", "absolute_delta": "0",
        "expected_status": "COLLAPSED", "actual_status": "COLLAPSED",
        "result": "PASS" if precision_build["precision_equivalent_group_count"] > 0 else "FAIL",
    })
    conflict_build = next(
        build for build in _load("000680")["f2"]["periodization_builds"]
        if build["fiscal_year"] == "2021" and build.get("true_value_conflict_group_count", 0) > 0
    )
    conflict_values = {
        fact["value"] for fact in conflict_build["facts"]
        if fact.get("metric") == "net_income"
        and fact.get("period_start") == "2020-01-01"
        and fact.get("period_end") == "2020-03-31"
    }
    rows.append({
        "ticker": "000680", "company": "LS네트웍스", "period": "2021Q1",
        "metric": "true value conflict preservation", "source_kind": "LOCAL_AUTHORITY_ASSERT",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210514001476",
        "actual_value": len(conflict_values), "reference_value": ">=2", "tolerance": "exact",
        "absolute_delta": "0", "expected_status": "PRESERVED", "actual_status": "PRESERVED",
        "result": "PASS" if conflict_build["true_value_conflict_group_count"] > 0 and len(conflict_values) >= 2 else "FAIL",
    })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "external_sample_validation.csv"
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"sample_count": len(rows), "pass": len(rows) - len(failures), "fail": len(failures), "path": str(path.relative_to(ROOT))}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
