#!/usr/bin/env python3
"""Project published Stock Report strategy authority into a static monitor JSON.

This exporter only consumes the existing compact web Stock Report payloads. It
does not run a strategy, calculate indicators, perform a backtest, or call any
external provider.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "web/data/stock-index.json"
STOCKS_PATH = ROOT / "web/data/stocks"
OUTPUT_PATH = ROOT / "web/data/strategy-monitor.json"
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
STRATEGY_LABEL = "A FAST Core"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _trade_projection(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_sequence": trade.get("trade_sequence"),
        "entry_execution_date": trade.get("entry_execution_date"),
        "entry_open": trade.get("entry_open"),
        "return_pct": trade.get("return_pct"),
        "trade_status": trade.get("trade_status"),
    }


def _item_bucket(item: dict[str, Any]) -> str:
    if item["data_status"] != "READY" or item["canonical_position"] == "NOT_APPLICABLE":
        return "unavailable"
    action = item["action"]
    if action in {"ENTRY", "ENTER_NEXT_OPEN"}:
        return "entry"
    if action == "HOLD":
        return "hold"
    if action == "EXIT":
        return "exit"
    if action in {"WATCH", "WAIT"}:
        return "watch"
    return "unavailable"


def _project_item(index_item: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    identity = report.get("identity") or {}
    decision = report.get("decision") or {}
    strategy = report.get("strategy") or {}
    technical = report.get("technical_details") or {}
    pattern = report.get("pattern") or {}
    price = report.get("price_trend") or {}
    availability = report.get("availability") or {}

    ticker = str(index_item.get("ticker") or "").upper()
    if identity.get("ticker") != ticker:
        raise ValueError(f"strategy monitor ticker mismatch: {ticker}")
    for index_key, report_key in (("name", "name"), ("market", "market"), ("asset_type", "asset_type")):
        if index_item.get(index_key) != identity.get(report_key):
            raise ValueError(f"strategy monitor identity mismatch: {ticker} {index_key}")

    action = decision.get("action")
    strategy_action = strategy.get("action")
    if action != strategy_action:
        raise ValueError(f"strategy action mismatch: {ticker}")
    strategy_state = decision.get("strategy_state")
    if strategy_state != strategy.get("state"):
        raise ValueError(f"strategy state mismatch: {ticker}")
    canonical_position = decision.get("canonical_position")
    if canonical_position != strategy.get("position"):
        raise ValueError(f"canonical position mismatch: {ticker}")

    data_status = "READY"
    current_trade: dict[str, Any] | None = None
    history = strategy.get("history") or []
    open_trades = [
        trade for trade in history
        if isinstance(trade, dict) and trade.get("trade_status") == "OPEN_AT_CUTOFF"
    ]
    if canonical_position == "OPEN":
        if len(open_trades) != 1:
            data_status = "CHECK_REQUIRED"
        else:
            current_trade = _trade_projection(open_trades[0])
    elif open_trades:
        data_status = "CHECK_REQUIRED"
    elif canonical_position == "NOT_APPLICABLE":
        data_status = "NOT_APPLICABLE"
    elif canonical_position not in {"FLAT", "OPEN"}:
        data_status = "CHECK_REQUIRED"
    if not action or not strategy_state or not canonical_position:
        data_status = "CHECK_REQUIRED"

    item = {
        "ticker": ticker,
        "name": identity.get("name"),
        "market": identity.get("market"),
        "asset_type": identity.get("asset_type"),
        "sector_name": technical.get("sector_name"),
        "action": action,
        "strategy_state": strategy_state,
        "canonical_position": canonical_position,
        "pattern_stage": pattern.get("official_stage"),
        "pattern_score": pattern.get("score"),
        "latest_close": price.get("latest_close"),
        "latest_close_as_of": price.get("latest_close_as_of"),
        "report_status": availability.get("report_status") or technical.get("report_status"),
        "data_status": data_status,
        "current_trade": current_trade,
    }
    item["bucket"] = _item_bucket(item)
    return item


def build_strategy_monitor(repo_root: Path = ROOT) -> dict[str, Any]:
    index_path = repo_root / "web/data/stock-index.json"
    stocks_path = repo_root / "web/data/stocks"
    index = _read_json(index_path)
    index_items = index.get("items") or []
    available = [item for item in index_items if item.get("report_available") is True]
    available.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("ticker") or "")))
    if index.get("available_report_count") != len(available):
        raise ValueError("stock index available report count mismatch")

    expected_tickers = {str(item.get("ticker") or "").upper() for item in available}
    report_paths = {path.stem for path in stocks_path.glob("*.json")}
    if report_paths != expected_tickers:
        raise ValueError("published stock report files do not match stock index")

    items: list[dict[str, Any]] = []
    as_of_values: set[str] = set()
    for index_item in available:
        ticker = str(index_item.get("ticker") or "").upper()
        report = _read_json(stocks_path / f"{ticker}.json")
        technical = report.get("technical_details") or {}
        as_of = str(technical.get("requested_as_of") or "")[:10]
        if as_of:
            as_of_values.add(as_of)
        items.append(_project_item(index_item, report))

    counts = {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0}
    for item in items:
        counts[item["bucket"]] += 1

    return {
        "schema_version": 1,
        "strategy": {
            "id": STRATEGY_ID,
            "label": STRATEGY_LABEL,
        },
        "source": {
            "type": "PUBLISHED_STOCK_REPORTS",
            "path": "web/data/stocks/*.json",
        },
        "scope": {
            "type": "PUBLISHED_REPORTS",
            "label": "현재 공개 리포트 기준",
            "report_count": len(items),
        },
        "as_of": next(iter(as_of_values)) if len(as_of_values) == 1 else "MIXED",
        "counts": counts,
        "items": items,
    }


def export_strategy_monitor(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    payload = build_strategy_monitor()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    payload = export_strategy_monitor(args.output)
    print(json.dumps({"as_of": payload["as_of"], "counts": payload["counts"], "item_count": len(payload["items"])}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
