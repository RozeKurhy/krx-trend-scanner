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
from functools import lru_cache
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.csv"
STOCK_REPORTS_ROOT = ROOT / "artifacts/reporting/stock_reports"
ADJUSTED_STOCK_ROOT = ROOT / "data/market/adjusted/stocks"
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


@lru_cache(maxsize=None)
def _load_exact_daily_close(ticker: str, as_of: str) -> dict[str, Any] | None:
    """Read one exact-date close from the local adjusted market authority."""
    if not ticker or not as_of:
        return None
    path = ADJUSTED_STOCK_ROOT / f"{ticker}.parquet"
    if not path.exists():
        return None
    try:
        import pandas as pd

        daily = pd.read_parquet(path, columns=["date", "close"])
        if "date" not in daily or "close" not in daily:
            return None
        dates = pd.to_datetime(daily["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        matches = daily.loc[dates == as_of, "close"].dropna()
    except (ImportError, OSError, ValueError, KeyError):
        return None
    if len(matches) != 1:
        return None
    return {
        "value": float(matches.iloc[0]),
        "as_of": as_of,
        "source": _relative(path),
    }


def _compact_monthly_history(monthly: dict[str, Any]) -> list[dict[str, Any]]:
    history = monthly.get("recent_12m_history") or []
    if not isinstance(history, list):
        return []
    return [
        {
            "as_of": observation.get("as_of"),
            "close": observation.get("close"),
            "score": observation.get("score"),
            "stage": observation.get("stage"),
            "candidate_state": observation.get("candidate_state"),
            "data_available": observation.get("data_available"),
        }
        for observation in history
        if isinstance(observation, dict)
    ]


def _compact_trade_history(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    history = strategy.get("trade_history") or []
    if not isinstance(history, list):
        return []
    fields = (
        "trade_id",
        "trade_sequence",
        "entry_signal_date",
        "entry_execution_date",
        "entry_open",
        "entry_pattern_a_stage",
        "exit_type",
        "exit_signal_date",
        "exit_execution_date",
        "exit_price",
        "trade_status",
        "return_pct",
        "lifecycle_class",
    )
    return [
        {field: trade.get(field) for field in fields}
        for trade in history
        if isinstance(trade, dict)
    ]


def _compact_report(report: dict[str, Any], source_path: Path) -> dict[str, Any]:
    header = report.get("header") or {}
    snapshot = report.get("current_snapshot") or {}
    monthly = report.get("monthly_history") or {}
    relative_strength = report.get("relative_strength") or {}
    sector_strength = report.get("sector_relative_strength") or {}
    flow = report.get("foreign_flow") or {}
    trading_value = report.get("trading_value_flow") or {}
    strategy = report.get("a_fast_core") or {}
    ticker = str(report.get("ticker") or header.get("ticker") or "").upper()
    asset_type = str(report.get("asset_type") or header.get("asset_type") or "UNKNOWN").upper()
    reference_market_date = str(report.get("reference_market_date") or "")[:10]
    daily_close = _load_exact_daily_close(ticker, reference_market_date)
    fundamentals_status = "NOT_AVAILABLE" if asset_type == "COMMON" else "NOT_APPLICABLE"

    return {
        "schema_version": 1,
        "identity": {
            "ticker": ticker,
            "name": str(report.get("name") or header.get("name") or ""),
            "market": str(report.get("market") or header.get("market") or "").upper(),
            "asset_type": asset_type,
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
            "flow_state": flow.get("flow_state"),
        },
        "price_trend": {
            "latest_close": daily_close["value"] if daily_close else None,
            "latest_close_as_of": daily_close["as_of"] if daily_close else None,
            "price_status": "AVAILABLE" if daily_close else "UNAVAILABLE",
            "price_source": daily_close["source"] if daily_close else None,
            "score_trend": monthly.get("score_trend") or {},
            "trading_value_state": trading_value.get("trading_value_state"),
            "trading_value_explanation": trading_value.get("explanation"),
            "avg_trading_value_1d_eok": trading_value.get("avg_trading_value_1d_eok"),
            "avg_trading_value_5d_eok": trading_value.get("avg_trading_value_5d_eok"),
            "avg_trading_value_10d_eok": trading_value.get("avg_trading_value_10d_eok"),
            "avg_trading_value_20d_eok": trading_value.get("avg_trading_value_20d_eok"),
            "avg_trading_value_60d_eok": trading_value.get("avg_trading_value_60d_eok"),
        },
        "pattern": {
            "official_stage": snapshot.get("official_stage"),
            "candidate_state": snapshot.get("candidate_state"),
            "score": snapshot.get("pattern_a_score"),
            "history_12m": _compact_monthly_history(monthly),
        },
        "market_strength": {
            "applicability": relative_strength.get("applicability"),
            "data_status": relative_strength.get("data_status"),
            "benchmark_name": relative_strength.get("benchmark_name"),
            "benchmark_last_observation_date": relative_strength.get("benchmark_last_observation_date"),
            "stock_return_2w": relative_strength.get("stock_return_2w"),
            "stock_return_1m": relative_strength.get("stock_return_1m"),
            "stock_return_3m": relative_strength.get("stock_return_3m"),
            "stock_return_6m": relative_strength.get("stock_return_6m"),
            "stock_return_12m": relative_strength.get("stock_return_12m"),
            "market_rs_2w": relative_strength.get("market_rs_2w"),
            "market_rs_1m": relative_strength.get("market_rs_1m"),
            "market_rs_3m": relative_strength.get("market_rs_3m"),
            "market_rs_6m": relative_strength.get("market_rs_6m"),
            "market_rs_12m": relative_strength.get("market_rs_12m"),
            "percentile_2w": relative_strength.get("all_market_rs_percentile_2w"),
            "percentile_1m": relative_strength.get("all_market_rs_percentile_1m"),
            "percentile_3m": relative_strength.get("all_market_rs_percentile_3m"),
            "percentile_6m": relative_strength.get("all_market_rs_percentile_6m"),
            "percentile_12m": relative_strength.get("all_market_rs_percentile_12m"),
            "explanation": relative_strength.get("explanation"),
        },
        "flow": {
            "data_status": flow.get("data_status"),
            "state": flow.get("flow_state"),
            "net_buy_value_1d_krw": flow.get("foreign_net_buy_value_1d_krw"),
            "net_buy_value_5d_krw": flow.get("foreign_net_buy_value_5d_krw"),
            "net_buy_value_10d_krw": flow.get("foreign_net_buy_value_10d_krw"),
            "net_buy_value_20d_krw": flow.get("foreign_net_buy_value_20d_krw"),
            "net_buy_value_60d_krw": flow.get("foreign_net_buy_value_60d_krw"),
            "intensity_1d": flow.get("foreign_flow_intensity_1d"),
            "intensity_5d": flow.get("foreign_flow_intensity_5d"),
            "intensity_10d": flow.get("foreign_flow_intensity_10d"),
            "intensity_20d": flow.get("foreign_flow_intensity_20d"),
            "intensity_60d": flow.get("foreign_flow_intensity_60d"),
            "positive_days_1d": flow.get("foreign_positive_days_1d"),
            "positive_days_5d": flow.get("foreign_positive_days_5d"),
            "positive_days_10d": flow.get("foreign_positive_days_10d"),
            "positive_days_20d": flow.get("foreign_positive_days_20d"),
            "positive_days_60d": flow.get("foreign_positive_days_60d"),
            "explanation": flow.get("explanation"),
        },
        "fundamentals": {
            "status": fundamentals_status,
        },
        "strategy": {
            "action": strategy.get("action"),
            "state": strategy.get("strategy_state"),
            "position": strategy.get("canonical_position"),
            "reason": strategy.get("action_reason"),
            "interpretation": strategy.get("interpretation"),
            "history": _compact_trade_history(strategy),
        },
        "technical_details": {
            "requested_as_of": report.get("requested_as_of"),
            "reference_market_date": reference_market_date,
            "report_version": report.get("report_version"),
            "report_status": header.get("report_status"),
            "asset_type": report.get("asset_type"),
            "investability_status": snapshot.get("investability_status"),
            "investability_reason": snapshot.get("investability_reason"),
            "pattern_stage": snapshot.get("official_stage"),
            "pattern_score": snapshot.get("pattern_a_score"),
            "candidate_state": snapshot.get("candidate_state"),
            "flow_state": flow.get("flow_state"),
            "market_strength_applicability": relative_strength.get("applicability"),
            "market_strength_status": relative_strength.get("data_status"),
            "relative_strength_status": relative_strength.get("data_status"),
            "trading_value_state": trading_value.get("trading_value_state"),
            "price_as_of": daily_close["as_of"] if daily_close else None,
            "price_status": "AVAILABLE" if daily_close else "UNAVAILABLE",
            "price_source": daily_close["source"] if daily_close else None,
            "sector_name": sector_strength.get("sector_name"),
            "data_quality": report.get("data_quality") or {},
            "source_report": _relative(source_path),
        },
        "external_links": {
            "naver_finance": f"https://finance.naver.com/item/main.naver?code={ticker}",
            "toss_chart": f"https://www.tossinvest.com/stocks/A{ticker}/order",
        },
    }


def build_web_payload(repo_root: Path = ROOT) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    if repo_root != ROOT:
        raise ValueError("stock report web exporter is bound to the repository root")
    report_dir, requested_as_of = _resolve_report_directory()
    universe, snapshot_date = _load_universe(requested_as_of)
    source_json_dir = report_dir / "json"
    reports: dict[str, dict[str, Any]] = {}
    for path in sorted(source_json_dir.glob("*.json")):
        report = _read_json(path)
        ticker = str(report.get("ticker") or "").strip().upper()
        if not ticker or ticker in reports:
            raise ValueError(f"invalid or duplicate Stock Report ticker: {path}")
        if str(report.get("requested_as_of") or "")[:10] != requested_as_of:
            raise ValueError(f"Stock Report date mismatch: {path}")
        reports[ticker] = _compact_report(report, path)

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
