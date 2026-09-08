"""Build the read-only market-strength ranking projection for the static web."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_PATH = ROOT / "web" / "data" / "stock-index.json"
DEFAULT_STOCKS_DIR = ROOT / "web" / "data" / "stocks"
DEFAULT_OUTPUT_PATH = ROOT / "web" / "data" / "market-ranking.json"
HORIZONS = ("3m", "6m", "12m")
PERCENTILE_FIELDS = {horizon: f"percentile_{horizon}" for horizon in HORIZONS}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_valid_percentile(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def _is_eligible(item: dict[str, Any], horizon: str) -> bool:
    return (
        item["asset_type"] == "COMMON"
        and item["market_strength_applicability"] == "APPLICABLE"
        and item["market_strength_status"] == "READY"
        and _is_valid_percentile(item[PERCENTILE_FIELDS[horizon]])
    )


def _project_item(index_item: dict[str, Any], report: dict[str, Any], path: Path) -> dict[str, Any]:
    identity = report.get("identity")
    market_strength = report.get("market_strength")
    pattern = report.get("pattern")
    flow = report.get("flow")
    decision = report.get("decision")
    price_trend = report.get("price_trend")
    technical_details = report.get("technical_details")
    if not all(isinstance(value, dict) for value in (identity, market_strength, pattern, flow, decision, price_trend, technical_details)):
        raise ValueError(f"compact report sections are incomplete: {path}")

    expected_identity = {
        "ticker": index_item.get("ticker"),
        "name": index_item.get("name"),
        "market": index_item.get("market"),
        "asset_type": index_item.get("asset_type"),
    }
    actual_identity = {key: identity.get(key) for key in expected_identity}
    if actual_identity != expected_identity:
        raise ValueError(f"index/report identity mismatch: {path}")
    requested_as_of = technical_details.get("requested_as_of")
    if not isinstance(requested_as_of, str) or len(requested_as_of) < 10:
        raise ValueError(f"missing requested_as_of: {path}")

    return {
        "ticker": identity["ticker"],
        "name": identity["name"],
        "market": identity["market"],
        "asset_type": identity["asset_type"],
        "sector_name": technical_details.get("sector_name"),
        "latest_close": price_trend.get("latest_close"),
        "latest_close_as_of": price_trend.get("latest_close_as_of"),
        "percentile_3m": market_strength.get("percentile_3m"),
        "percentile_6m": market_strength.get("percentile_6m"),
        "percentile_12m": market_strength.get("percentile_12m"),
        "market_strength_applicability": market_strength.get("applicability"),
        "market_strength_status": market_strength.get("data_status"),
        "pattern_stage": pattern.get("official_stage"),
        "pattern_score": pattern.get("score"),
        "flow_state": flow.get("state"),
        "flow_data_status": flow.get("data_status"),
        "strategy_action": decision.get("action"),
    }


def build_market_ranking(
    index_path: Path = DEFAULT_INDEX_PATH,
    stocks_dir: Path = DEFAULT_STOCKS_DIR,
) -> dict[str, Any]:
    index = _read_json(index_path)
    if index.get("schema_version") != 1 or not isinstance(index.get("items"), list):
        raise ValueError("stock-index schema is incomplete")

    published_index_items = [item for item in index["items"] if isinstance(item, dict) and item.get("report_available") is True]
    published_by_ticker = {item.get("ticker"): item for item in published_index_items}
    if len(published_by_ticker) != len(published_index_items) or any(not ticker for ticker in published_by_ticker):
        raise ValueError("stock-index has invalid or duplicate published tickers")
    if index.get("available_report_count") != len(published_index_items):
        raise ValueError("stock-index available_report_count does not match published items")

    paths = sorted(stocks_dir.glob("*.json"))
    if {path.stem for path in paths} != set(published_by_ticker):
        raise ValueError("published report file set does not match stock-index")

    reports: dict[str, dict[str, Any]] = {}
    for path in paths:
        report = _read_json(path)
        identity = report.get("identity")
        ticker = identity.get("ticker") if isinstance(identity, dict) else None
        if ticker != path.stem or ticker not in published_by_ticker:
            raise ValueError(f"invalid published report ticker: {path}")
        if report.get("schema_version") != 1 or report.get("availability", {}).get("report_available") is not True:
            raise ValueError(f"published report is not available: {path}")
        reports[ticker] = report

    items = [
        _project_item(published_by_ticker[ticker], reports[ticker], stocks_dir / f"{ticker}.json")
        for ticker in sorted(reports, key=lambda value: (str(published_by_ticker[value].get("name") or ""), value))
    ]
    as_of_values = {str(item["technical_details"].get("requested_as_of"))[:10] for item in reports.values()}
    if len(as_of_values) != 1:
        raise ValueError(f"published report requested_as_of is mixed: {sorted(as_of_values)}")
    as_of = next(iter(as_of_values))
    if as_of != str(index.get("requested_as_of") or "")[:10]:
        raise ValueError("stock-index and published report requested_as_of differ")

    eligible_counts = {
        horizon: sum(1 for item in items if _is_eligible(item, horizon))
        for horizon in HORIZONS
    }
    return {
        "schema_version": 1,
        "scope": {
            "type": "PUBLISHED_REPORTS",
            "label": "현재 공개 리포트 기준",
            "report_count": len(items),
        },
        "metric_scope": {
            "label": "시장 강도는 전체 보통주 기준",
        },
        "as_of": as_of,
        "eligible_counts": eligible_counts,
        "items": items,
    }


def export_market_ranking(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    payload = build_market_ranking()
    _write_json(output_path, payload)
    return {
        "output": str(output_path.relative_to(ROOT)),
        "as_of": payload["as_of"],
        "report_count": payload["scope"]["report_count"],
        "eligible_counts": payload["eligible_counts"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(export_market_ranking(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
