#!/usr/bin/env python3
"""Publish exact-identity report routes for every B Select Core V2 trade identity.

This exporter does not widen the public Stock Report universe or synthesize
indicators. It reuses full reports where an exact current identity exists and
publishes clearly labeled identity-only records for the remaining historical
trade identities.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "artifacts/strategies/b_select_core_v2/production/20261003/status.json"
INDEX_PATH = ROOT / "web/data/stock-index.json"
STOCKS_DIR = ROOT / "web/data/stocks"
OUTPUT_DIR = ROOT / "web/data/identity-reports"
ROUTES_PATH = ROOT / "web/data/identity-report-routes.json"
PIT_PATH = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
MONITOR_PATH = ROOT / "web/data/strategy-monitor.json"
ADJUSTED_DIR = ROOT / "data/market/adjusted/stocks"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", delete=False,
    ) as stream:
        temp_path = Path(stream.name)
        stream.write(encoded)
        stream.flush()
    temp_path.replace(path)


def _identity_active(intervals: list[dict[str, Any]], ticker: str, isu_cd: str, day: str) -> bool:
    return any(
        str(row.get("ticker", "")).zfill(6) == ticker
        and str(row.get("isu_cd", "")).upper() == isu_cd
        and str(row.get("state", "")).upper() == "COMMON"
        and str(row.get("effective_from", ""))[:10] <= day
        and str(row.get("effective_to", ""))[:10] >= day
        for row in intervals
    )


def _exact_close(ticker: str, reference_date: str) -> tuple[float | None, str | None]:
    path = ADJUSTED_DIR / f"{ticker}.parquet"
    if not path.is_file():
        return None, None
    try:
        import pandas as pd

        frame = pd.read_parquet(path, columns=["date", "close"])
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        rows = frame.loc[dates == reference_date, "close"].dropna()
        if len(rows) != 1:
            return None, None
        value = float(rows.iloc[0])
        if value <= 0:
            return None, None
        return value, path.relative_to(ROOT).as_posix()
    except (ImportError, OSError, ValueError, KeyError):
        return None, None


def _public_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_sequence": row.get("trade_sequence"),
        "entry_signal_date": row.get("entry_signal_date"),
        "entry_execution_date": row.get("entry_execution_date"),
        "entry_open": row.get("entry_open"),
        "exit_signal_date": row.get("exit_signal_date"),
        "exit_execution_date": row.get("exit_execution_date"),
        "exit_price": row.get("exit_price"),
        "trade_status": row.get("trade_status"),
        "return_pct": row.get("return_pct"),
        "exit_reason": row.get("exit_reason"),
        "isu_cd": row.get("isu_cd"),
    }


def _identity_only_report(
    identity: tuple[str, str],
    trade_rows: list[dict[str, Any]],
    *,
    name: str,
    market: str,
    current_common: bool,
    reference_date: str,
) -> dict[str, Any]:
    ticker, isu_cd = identity
    exact_close, close_source = _exact_close(ticker, reference_date) if current_common else (None, None)
    identity_status = (
        "CURRENT_COMMON_OUTSIDE_PUBLISHED_REPORT_SCOPE"
        if current_common else "HISTORICAL / NOT_CURRENT_COMMON"
    )
    history = [_public_trade(row) for row in trade_rows]
    return {
        "schema_version": 1,
        "identity": {
            "ticker": ticker, "isu_cd": isu_cd, "name": name,
            "market": market, "asset_type": "COMMON",
        },
        "availability": {
            "report_available": True,
            "report_status": "PARTIAL_IDENTITY_ONLY",
            "identity_status": identity_status,
            "detail_availability": "FULL_STOCK_ANALYSIS_NOT_PUBLISHED",
        },
        "decision": {
            "action": "NONE", "strategy_state": "NOT_APPLICABLE",
            "canonical_position": "NOT_APPLICABLE",
            "action_reason": "IDENTITY_ROUTE_FOR_CANONICAL_B_SELECT_HISTORY",
            "is_investable": None,
        },
        "summary": {"trend_stage": "UNAVAILABLE", "flow_state": "FLOW_UNAVAILABLE"},
        "price_trend": {
            "latest_close": exact_close,
            "latest_close_as_of": reference_date if exact_close is not None else None,
            "price_status": "AVAILABLE" if exact_close is not None else "UNAVAILABLE",
            "price_source": close_source,
            "score_trend": {}, "trading_value_state": "UNAVAILABLE",
            "trading_value_explanation": None,
        },
        "pattern": {
            "official_stage": "UNAVAILABLE", "candidate_state": None,
            "score": None, "history_12m": [], "history_24m": [],
        },
        "pattern_b": None,
        "market_strength": {
            "applicability": "NOT_APPLICABLE", "data_status": "NOT_AVAILABLE",
            "explanation": "Full Stock Report is not published for this exact identity.",
        },
        "flow": {
            "data_status": "NOT_AVAILABLE", "state": "FLOW_UNAVAILABLE",
            "explanation": "Full Stock Report is not published for this exact identity.",
        },
        "fundamentals": {
            "status": "DATA_UNAVAILABLE", "applicability": "NOT_AVAILABLE",
            "reason": "FULL_STOCK_REPORT_NOT_PUBLISHED_FOR_EXACT_IDENTITY",
            "requested_as_of": reference_date, "summary": {}, "quarterly": [], "annual": [],
        },
        "strategy": {
            "action": "NONE", "state": "NOT_APPLICABLE",
            "position": "NOT_APPLICABLE",
            "reason": "IDENTITY_ROUTE_FOR_CANONICAL_B_SELECT_HISTORY",
            "history": history,
        },
        "technical_details": {
            "requested_as_of": reference_date,
            "reference_market_date": reference_date,
            "report_status": "PARTIAL_IDENTITY_ONLY",
            "identity_status": identity_status,
            "asset_type": "COMMON",
            "price_as_of": reference_date if exact_close is not None else None,
            "price_status": "AVAILABLE" if exact_close is not None else "UNAVAILABLE",
            "price_source": close_source,
            "data_quality": {},
        },
        "external_links": {
            "naver_finance": f"https://finance.naver.com/item/main.naver?code={ticker}",
            "naver_chart": f"https://stock.naver.com/fchart/domestic/stock/{ticker}",
        },
    }


def build_identity_routes() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status = _read(STATUS_PATH)
    index = _read(INDEX_PATH)
    pit = _read(PIT_PATH)
    monitor = _read(MONITOR_PATH)
    reference_date = str(status.get("reference_market_date", ""))[:10]
    if not reference_date or reference_date != "2026-10-02":
        raise ValueError(f"unexpected canonical history reference date: {reference_date}")
    if int(status.get("canonical_trade_history_row_count", -1)) != len(status.get("canonical_trade_history", [])):
        raise ValueError("canonical trade history row count mismatch")

    trades_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in status["canonical_trade_history"]:
        identity = (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper())
        trades_by_identity.setdefault(identity, []).append(row)
    if len(status["canonical_trade_history"]) != 488 or len(trades_by_identity) != 399:
        raise ValueError("unexpected canonical V2 trade or identity count")

    strategy = next(
        (row for row in monitor.get("strategies", []) if row.get("id") == "PATTERN_B_SELECT_CORE_V02"),
        None,
    )
    if strategy is None:
        raise ValueError("canonical V2 Strategy Monitor data is missing")
    monitor_pairs = {
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())
        for row in strategy.get("trade_history", [])
    }
    if monitor_pairs != set(trades_by_identity):
        raise ValueError("Strategy Monitor identity set differs from canonical history")

    active_pairs = {
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())
        for row in pit.get("intervals", [])
        if str(row.get("state", "")).upper() == "COMMON"
        and str(row.get("effective_from", ""))[:10] <= reference_date
        and str(row.get("effective_to", ""))[:10] >= reference_date
    }
    index_items = {str(row.get("ticker", "")).zfill(6): row for row in index.get("items", [])}
    routes: list[dict[str, Any]] = []
    supplemental_paths: set[Path] = set()
    for identity, rows in sorted(trades_by_identity.items()):
        ticker, isu_cd = identity
        is_current_common = identity in active_pairs
        index_item = index_items.get(ticker, {})
        current_report_path = STOCKS_DIR / f"{ticker}.json"
        exact_current_report = False
        if is_current_common and current_report_path.is_file():
            report = _read(current_report_path)
            report_identity = report.get("identity") or {}
            exact_current_report = (
                str(report_identity.get("ticker", "")).zfill(6) == ticker
                and str(report_identity.get("isu_cd", "")).upper() == isu_cd
            )
        if exact_current_report:
            url = f"./data/stocks/{ticker}.json"
            report_type = "CURRENT_STOCK_REPORT"
            identity_status = "CURRENT_COMMON"
        else:
            report_name = f"{ticker}--{isu_cd}.json"
            supplemental_path = OUTPUT_DIR / report_name
            latest_trade = max(
                rows,
                key=lambda row: (str(row.get("entry_signal_date", "")), int(row.get("trade_sequence") or 0)),
            )
            trade_name = str(latest_trade.get("name") or ticker).strip()
            trade_market = str(latest_trade.get("market") or "UNKNOWN").upper()
            name = (
                str(index_item.get("name") or trade_name)
                if is_current_common and str(index_item.get("isu_cd", "")).upper() == isu_cd
                else trade_name
            )
            market = (
                str(index_item.get("market") or trade_market).upper()
                if is_current_common and str(index_item.get("isu_cd", "")).upper() == isu_cd
                else trade_market
            )
            report = _identity_only_report(
                identity, rows, name=name, market=market,
                current_common=is_current_common, reference_date=reference_date,
            )
            _write(supplemental_path, report)
            supplemental_paths.add(supplemental_path)
            url = f"./data/identity-reports/{report_name}"
            report_type = "IDENTITY_ONLY_CURRENT" if is_current_common else "HISTORICAL_ARCHIVE"
            identity_status = report["availability"]["identity_status"]
        routes.append({
            "ticker": ticker, "isu_cd": isu_cd, "url": url,
            "report_type": report_type, "identity_status": identity_status,
            "trade_count": len(rows),
        })

    expected_supplemental = len(trades_by_identity) - sum(
        row["report_type"] == "CURRENT_STOCK_REPORT" for row in routes
    )
    if len(supplemental_paths) != expected_supplemental:
        raise ValueError("supplemental exact-identity report count mismatch")
    payload = {
        "schema_version": 1,
        "strategy_id": "PATTERN_B_SELECT_CORE_V02",
        "requested_as_of": status["requested_as_of"],
        "reference_market_date": reference_date,
        "canonical_trade_count": len(status["canonical_trade_history"]),
        "unique_exact_identity_count": len(trades_by_identity),
        "route_count": len(routes),
        "supplemental_report_count": len(supplemental_paths),
        "items": routes,
    }
    return payload, sorted(supplemental_paths)


def export() -> dict[str, Any]:
    payload, supplemental_paths = build_identity_routes()
    known = {path.name for path in supplemental_paths}
    if OUTPUT_DIR.exists():
        for path in OUTPUT_DIR.glob("*.json"):
            if path.name not in known:
                path.unlink()
    for path in supplemental_paths:
        report = _read(path)
        if report["identity"]["isu_cd"] not in path.name:
            raise ValueError(f"exact identity report path mismatch: {path}")
    _write(ROUTES_PATH, payload)
    return {
        "canonical_trade_count": payload["canonical_trade_count"],
        "unique_exact_identity_count": payload["unique_exact_identity_count"],
        "route_count": payload["route_count"],
        "supplemental_report_count": payload["supplemental_report_count"],
        "current_stock_report_route_count": sum(row["report_type"] == "CURRENT_STOCK_REPORT" for row in payload["items"]),
        "historical_archive_count": sum(row["report_type"] == "HISTORICAL_ARCHIVE" for row in payload["items"]),
        "identity_only_current_count": sum(row["report_type"] == "IDENTITY_ONLY_CURRENT" for row in payload["items"]),
        "route_index": ROUTES_PATH.relative_to(ROOT).as_posix(),
    }


if __name__ == "__main__":
    print(json.dumps(export(), ensure_ascii=False, sort_keys=True))
