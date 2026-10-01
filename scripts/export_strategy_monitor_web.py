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
STRATEGY_LABEL = "A FAST Core V2"
B_SELECT_ID = "PATTERN_B_SELECT_CORE_V01"
B_SELECT_LABEL = "B Select Core V1"
JULIA_ID = "JULIA_ETF_STRATEGY_V01"
JULIA_LABEL = "Julia V1"
DEFAULT_STRATEGY_ID = STRATEGY_ID


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
    if action in {"EXIT", "EXIT_NEXT_OPEN"}:
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


def build_strategy_monitor(
    repo_root: Path = ROOT,
    *,
    index_path: Path | None = None,
    stocks_path: Path | None = None,
    target_as_of: str | None = None,
    reference_market_date: str | None = None,
    b_select_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``index_path``/``stocks_path``(선택, PHASE4C_MANDATORY_ANALYSIS_DISPLAY_V01)를
    명시하면 ``web/data/`` 대신 그 exact-target 소스를 읽는다. 생략하면 기존과
    완전히 동일하게 ``repo_root/web/data/``를 읽는다(하위 호환). ``target_as_of``/
    ``reference_market_date``를 명시하면 published report의 requested_as_of/
    reference_market_date가 그 값과 정확히 일치하는지 fail-closed로 검증한다
    (생략 시 기존처럼 mixed일 경우 "MIXED"로만 표시하고 raise하지 않는다).
    """
    index_path = index_path if index_path is not None else repo_root / "web/data/stock-index.json"
    stocks_path = stocks_path if stocks_path is not None else repo_root / "web/data/stocks"
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

    common_items: list[dict[str, Any]] = []
    etf_items: list[dict[str, Any]] = []
    as_of_values: set[str] = set()
    reference_market_date_values: set[str] = set()
    for index_item in available:
        ticker = str(index_item.get("ticker") or "").upper()
        report = _read_json(stocks_path / f"{ticker}.json")
        technical = report.get("technical_details") or {}
        as_of = str(technical.get("requested_as_of") or "")[:10]
        ref = str(technical.get("reference_market_date") or "")[:10]
        if as_of:
            as_of_values.add(as_of)
        if ref:
            reference_market_date_values.add(ref)
        if index_item.get("asset_type") == "COMMON":
            common_items.append(_project_item(index_item, report))
        elif index_item.get("asset_type") == "ETF":
            strategy = report.get("strategy") or {}
            if (
                strategy.get("source") != "official_strategy"
                or strategy.get("strategy_id") != JULIA_ID
                or strategy.get("strategy_name") != JULIA_LABEL
            ):
                raise ValueError(f"Julia source strategy mismatch: {ticker}")
            etf_items.append(_project_item(index_item, report))

    if target_as_of is not None and as_of_values != {target_as_of}:
        raise ValueError(
            f"strategy monitor requested_as_of mismatch: expected {target_as_of!r}, got {sorted(as_of_values)}"
        )
    if reference_market_date is not None and reference_market_date_values != {reference_market_date}:
        raise ValueError(
            f"strategy monitor reference_market_date mismatch: expected {reference_market_date!r}, "
            f"got {sorted(reference_market_date_values)}"
        )

    resolved_as_of = (
        target_as_of if target_as_of is not None
        else (next(iter(as_of_values)) if len(as_of_values) == 1 else "MIXED")
    )
    resolved_reference = (
        reference_market_date if reference_market_date is not None
        else (next(iter(reference_market_date_values)) if len(reference_market_date_values) == 1 else "MIXED")
    )

    if b_select_status is None:
        b_select_path = repo_root / "artifacts/strategies/b_select_core_v1/production" / resolved_as_of.replace("-", "") / "status.json"
        if not b_select_path.is_file():
            raise ValueError("B Select current status artifact is missing")
        b_select_status = _read_json(b_select_path)
    if (
        b_select_status.get("status") != "PASS"
        or b_select_status.get("strategy_id") != B_SELECT_ID
        or b_select_status.get("requested_as_of") != resolved_as_of
        or b_select_status.get("reference_market_date") != resolved_reference
        or (b_select_status.get("scope") or {}).get("type") != "PUBLISHED_COMMON_REPORTS"
    ):
        raise ValueError("B Select current status is invalid or date-mismatched")
    b_items = b_select_status.get("items")
    if not isinstance(b_items, list):
        raise ValueError("B Select current status items are invalid")
    common_tickers = {item["ticker"] for item in common_items}
    if {str(item.get("ticker", "")).zfill(6) for item in b_items} != common_tickers:
        raise ValueError("B Select current status COMMON scope does not match published reports")
    b_counts = b_select_status.get("counts") or {}
    expected_bucket_counts = {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0}
    for item in b_items:
        if item.get("asset_type") != "COMMON" or item.get("bucket") not in expected_bucket_counts:
            raise ValueError("B Select current status item contract is invalid")
        expected_bucket_counts[item["bucket"]] += 1
    if (
        b_select_status.get("count") != len(b_items)
        or (b_select_status.get("scope") or {}).get("report_count") != len(b_items)
        or b_counts != expected_bucket_counts
        or any(
            b_select_status.get(key) != 0
            for key in (
                "network_requests",
                "evaluation_error_count",
                "date_mismatch_count",
                "future_reference_count",
                "duplicate_item_count",
                "cross_strategy_contamination_count",
            )
        )
    ):
        raise ValueError("B Select current status diagnostics or counts are invalid")
    if len(etf_items) != 36:
        raise ValueError(f"Official ETF 36 report count mismatch: {len(etf_items)}")

    def counts_for(items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0}
        for item in items:
            bucket = item.get("bucket")
            if bucket not in counts:
                raise ValueError(f"unknown strategy item bucket: {bucket!r}")
            counts[bucket] += 1
        return counts

    strategies = [
        {
            "id": STRATEGY_ID,
            "label": STRATEGY_LABEL,
            "asset_scope": "COMMON",
            "scope": {
                "type": "PUBLISHED_COMMON_REPORTS",
                "label": "현재 공개 COMMON 리포트 기준",
                "report_count": len(common_items),
            },
            "counts": counts_for(common_items),
            "items": common_items,
        },
        {
            "id": B_SELECT_ID,
            "label": B_SELECT_LABEL,
            "asset_scope": "COMMON",
            "scope": {
                "type": "PUBLISHED_COMMON_REPORTS",
                "label": "현재 공개 COMMON 리포트 기준",
                "report_count": len(b_items),
            },
            "counts": dict(b_select_status.get("counts") or {}),
            "items": b_items,
        },
        {
            "id": JULIA_ID,
            "label": JULIA_LABEL,
            "asset_scope": "OFFICIAL_ETF_36",
            "scope": {
                "type": "OFFICIAL_ETF_36",
                "label": "Official ETF 36 기준",
                "report_count": len(etf_items),
            },
            "counts": counts_for(etf_items),
            "items": etf_items,
        },
    ]
    for strategy in strategies:
        if len(strategy["items"]) != strategy["scope"]["report_count"]:
            raise ValueError(f"strategy monitor scope count mismatch: {strategy['id']}")

    return {
        "schema_version": 2,
        "source": {
            "type": "PUBLISHED_STOCK_REPORTS",
            "path": "web/data/stocks/*.json",
        },
        "default_strategy_id": DEFAULT_STRATEGY_ID,
        "requested_as_of": resolved_as_of,
        "reference_market_date": resolved_reference,
        "as_of": resolved_as_of,
        "strategies": strategies,
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
    print(json.dumps({
        "as_of": payload["as_of"],
        "strategies": [
            {"id": strategy["id"], "scope_count": strategy["scope"]["report_count"], "counts": strategy["counts"]}
            for strategy in payload["strategies"]
        ],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
