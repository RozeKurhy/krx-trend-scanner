#!/usr/bin/env python3
"""Export local Stock Report authority into compact public web JSON.

This exporter is deliberately a read-only consumer of existing repository
artifacts. It does not generate reports, recalculate indicators, hydrate
fundamentals, or contact any external provider.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.csv"
STOCK_REPORTS_ROOT = ROOT / "artifacts/reporting/stock_reports"
DEFAULT_OUTPUT_DIR = ROOT / "web/data"
DATE_DIR_PATTERN = re.compile(r"^(\d{8})$")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON authority must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temp:
        temp_path = Path(temp.name)
        temp.write(encoded)
        temp.flush()
    temp_path.replace(path)


def _iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _resolve_report_directory() -> tuple[Path, str]:
    candidates: list[tuple[date, Path]] = []
    for path in STOCK_REPORTS_ROOT.iterdir():
        if not path.is_dir() or DATE_DIR_PATTERN.fullmatch(path.name) is None:
            continue
        json_dir = path / "json"
        if not json_dir.is_dir() or not any(json_dir.glob("*.json")):
            continue
        candidates.append((_iso_date(f"{path.name[:4]}-{path.name[4:6]}-{path.name[6:]}"), path))
    if not candidates:
        raise FileNotFoundError("no dated Stock Report JSON authority found")
    _, directory = max(candidates, key=lambda item: (item[0], item[1].name))
    return directory, f"{directory.name[:4]}-{directory.name[4:6]}-{directory.name[6:]}"


def _load_universe(requested_as_of: str) -> tuple[list[dict[str, str]], str]:
    if not METADATA_PATH.exists():
        raise FileNotFoundError(f"instrument metadata authority missing: {METADATA_PATH}")

    rows: list[dict[str, str]] = []
    with METADATA_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker") or "").strip().upper()
            effective = str(row.get("effective_date") or "").strip()[:10]
            if not ticker or not effective or effective > requested_as_of:
                continue
            rows.append({
                "ticker": ticker,
                "name": str(row.get("name") or ticker).strip() or ticker,
                "market": str(row.get("market") or "").strip().upper(),
                "asset_type": str(row.get("asset_type") or "UNKNOWN").strip().upper() or "UNKNOWN",
                "effective_date": effective,
            })

    if not rows:
        raise ValueError("instrument metadata has no PIT-eligible rows")
    snapshot_date = max(row["effective_date"] for row in rows)
    current = [row for row in rows if row["effective_date"] == snapshot_date]
    current.sort(key=lambda row: row["ticker"])
    tickers = [row["ticker"] for row in current]
    if len(tickers) != len(set(tickers)):
        raise ValueError("instrument metadata authority contains duplicate PIT tickers")
    return current, snapshot_date


def _latest_monthly_observation(report: dict[str, Any]) -> dict[str, Any] | None:
    history = report.get("monthly_history") or {}
    observations = history.get("recent_12m_history") or history.get("full_monthly_history") or []
    for observation in reversed(observations):
        if isinstance(observation, dict) and observation.get("close") is not None:
            return observation
    return None


def _market_strength_state(relative_strength: dict[str, Any]) -> str:
    if relative_strength.get("data_status") != "READY":
        return "UNAVAILABLE"
    explanation = str(relative_strength.get("explanation") or "")
    if "회복" in explanation:
        return "RECOVERING"
    if "약화" in explanation or "낮아지" in explanation:
        return "WEAKENING"
    if "개선" in explanation:
        return "IMPROVING"
    return "MIXED"


def _compact_report(report: dict[str, Any], source_path: Path) -> dict[str, Any]:
    header = report.get("header") or {}
    snapshot = report.get("current_snapshot") or {}
    monthly = report.get("monthly_history") or {}
    relative_strength = report.get("relative_strength") or {}
    sector_strength = report.get("sector_relative_strength") or {}
    flow = report.get("foreign_flow") or {}
    trading_value = report.get("trading_value_flow") or {}
    strategy = report.get("a_fast_core") or {}
    latest = _latest_monthly_observation(report)

    return {
        "schema_version": 1,
        "identity": {
            "ticker": str(report.get("ticker") or header.get("ticker") or "").upper(),
            "name": str(report.get("name") or header.get("name") or ""),
            "market": str(report.get("market") or header.get("market") or "").upper(),
            "asset_type": str(report.get("asset_type") or header.get("asset_type") or "UNKNOWN").upper(),
        },
        "availability": {
            "report_available": True,
            "report_status": header.get("report_status"),
        },
        "decision": {
            "action": strategy.get("action"),
            "strategy_state": strategy.get("strategy_state"),
            "canonical_position": strategy.get("canonical_position"),
            "action_reason": strategy.get("action_reason"),
            "is_investable": snapshot.get("is_investable"),
        },
        "summary": {
            "trend_stage": snapshot.get("official_stage"),
            "market_strength_state": _market_strength_state(relative_strength),
            "flow_state": flow.get("flow_state"),
        },
        "price_trend": {
            "latest_close": latest.get("close") if latest else None,
            "latest_close_as_of": latest.get("as_of") if latest else None,
            "score_trend": monthly.get("score_trend") or {},
            "trading_value_state": trading_value.get("trading_value_state"),
            "trading_value_explanation": trading_value.get("explanation"),
        },
        "pattern": {
            "official_stage": snapshot.get("official_stage"),
            "candidate_state": snapshot.get("candidate_state"),
            "score": snapshot.get("pattern_a_score"),
        },
        "market_strength": {
            "data_status": relative_strength.get("data_status"),
            "state": _market_strength_state(relative_strength),
            "benchmark_name": relative_strength.get("benchmark_name"),
            "market_rs_3m": relative_strength.get("market_rs_3m"),
            "market_rs_6m": relative_strength.get("market_rs_6m"),
            "market_rs_12m": relative_strength.get("market_rs_12m"),
            "percentile_3m": relative_strength.get("all_market_rs_percentile_3m"),
            "explanation": relative_strength.get("explanation"),
        },
        "flow": {
            "data_status": flow.get("data_status"),
            "state": flow.get("flow_state"),
            "net_buy_value_5d_krw": flow.get("foreign_net_buy_value_5d_krw"),
            "net_buy_value_20d_krw": flow.get("foreign_net_buy_value_20d_krw"),
            "net_buy_value_60d_krw": flow.get("foreign_net_buy_value_60d_krw"),
            "positive_days_20d": flow.get("foreign_positive_days_20d"),
            "explanation": flow.get("explanation"),
        },
        "fundamentals": {
            "status": "NOT_AVAILABLE",
            "reason": "F8 production fundamentals are not connected in WEB-02A.",
        },
        "strategy": {
            "action": strategy.get("action"),
            "state": strategy.get("strategy_state"),
            "position": strategy.get("canonical_position"),
            "reason": strategy.get("action_reason"),
            "interpretation": strategy.get("interpretation"),
        },
        "technical_details": {
            "requested_as_of": report.get("requested_as_of"),
            "reference_market_date": report.get("reference_market_date"),
            "report_version": report.get("report_version"),
            "report_status": header.get("report_status"),
            "asset_type": report.get("asset_type"),
            "investability_status": snapshot.get("investability_status"),
            "investability_reason": snapshot.get("investability_reason"),
            "pattern_stage": snapshot.get("official_stage"),
            "pattern_score": snapshot.get("pattern_a_score"),
            "candidate_state": snapshot.get("candidate_state"),
            "flow_state": flow.get("flow_state"),
            "relative_strength_status": relative_strength.get("data_status"),
            "trading_value_state": trading_value.get("trading_value_state"),
            "sector_name": sector_strength.get("sector_name"),
            "data_quality": report.get("data_quality") or {},
            "source_report": _relative(source_path),
        },
        "external_links": {
            "naver_finance": f"https://finance.naver.com/item/main.naver?code={report.get('ticker')}"
        },
    }


def build_web_payload(repo_root: Path = ROOT) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    if repo_root != ROOT:
        raise ValueError("stock report web exporter is bound to the repository root")
    report_dir, requested_as_of = _resolve_report_directory()
    universe, snapshot_date = _load_universe(requested_as_of)
    source_json_dir = report_dir / "json"
    reports: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    for path in sorted(source_json_dir.glob("*.json")):
        report = _read_json(path)
        ticker = str(report.get("ticker") or "").strip().upper()
        if not ticker or ticker in reports:
            raise ValueError(f"invalid or duplicate Stock Report ticker: {path}")
        if str(report.get("requested_as_of") or "")[:10] != requested_as_of:
            raise ValueError(f"Stock Report date mismatch: {path}")
        reports[ticker] = _compact_report(report, path)
        source_paths[ticker] = path

    report_tickers = set(reports)
    items = [
        {
            "ticker": row["ticker"],
            "name": row["name"],
            "market": row["market"],
            "asset_type": row["asset_type"],
            "report_available": row["ticker"] in report_tickers,
        }
        for row in universe
    ]
    unknown_reports = sorted(report_tickers - {item["ticker"] for item in items})
    if unknown_reports:
        raise ValueError(f"Stock Reports outside the PIT universe: {unknown_reports[:5]}")

    index = {
        "schema_version": 1,
        "requested_as_of": requested_as_of,
        "universe_snapshot_date": snapshot_date,
        "source_report_directory": _relative(report_dir),
        "count": len(items),
        "available_report_count": len(reports),
        "items": items,
    }
    stats = {
        "requested_as_of": requested_as_of,
        "universe_snapshot_date": snapshot_date,
        "universe_count": len(items),
        "available_report_count": len(reports),
        "unavailable_report_count": len(items) - len(reports),
        "source_report_directory": _relative(report_dir),
        "source_json_directory": _relative(source_json_dir),
    }
    return index, reports, stats


def export_stock_reports(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    index, reports, stats = build_web_payload()
    _write_json(output_dir / "stock-index.json", index)
    stock_dir = output_dir / "stocks"
    stock_dir.mkdir(parents=True, exist_ok=True)
    for ticker, report in sorted(reports.items()):
        _write_json(stock_dir / f"{ticker}.json", report)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    stats = export_stock_reports(args.output)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
