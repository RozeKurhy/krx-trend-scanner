"""Build the static KOSPI/KOSDAQ common-stock foreign net-buy ranking."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository_v2_loader import EXPECTED_DATA_UNAVAILABLE, build_repository_v2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX_PATH = ROOT / "web" / "data" / "stock-index.json"
DEFAULT_FLOW_PATH = ROOT / "artifacts" / "patterns" / "pattern_a" / "production" / "flow" / "source" / "foreign_flow_daily_20260904.parquet"
DEFAULT_SECTOR_PATH = ROOT / "data" / "market" / "sector_membership" / "v01" / "sector_membership_20260904.parquet"
DEFAULT_COMMON_AUTHORITY_PATH = ROOT / "artifacts" / "patterns" / "pattern_a" / "validation" / "relative_strength" / "market_completion_v01" / "market_rs_universe_20260904.csv"
DEFAULT_OUTPUT_PATH = ROOT / "web" / "data" / "foreign-net-buy-ranking.json"
AS_OF = "2026-09-04"
HORIZONS = (1, 5, 10, 20, 60)
FLOW_COLUMN = "foreign_net_buy_value"
REQUIRED_FLOW_COLUMNS = {"date", "ticker", FLOW_COLUMN}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_common_universe(
    index_path: Path = DEFAULT_INDEX_PATH,
    sector_path: Path = DEFAULT_SECTOR_PATH,
    common_authority_path: Path = DEFAULT_COMMON_AUTHORITY_PATH,
    as_of: str = AS_OF,
) -> tuple[list[dict[str, Any]], str | None]:
    """Resolve the exact production common-stock authority and sector labels."""

    index = _read_json(index_path)
    if index.get("schema_version") != 1 or not isinstance(index.get("items"), list):
        raise ValueError("stock-index schema is incomplete")
    report_by_ticker: dict[str, bool] = {}
    for item in index["items"]:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        ticker = str(item["ticker"])
        if ticker in report_by_ticker:
            raise ValueError("stock-index contains duplicate tickers")
        report_by_ticker[ticker] = bool(item.get("report_available", False))

    authority = pd.read_csv(common_authority_path, dtype=str)
    required_authority = {"ticker", "name", "market"}
    if not required_authority.issubset(authority.columns):
        raise ValueError(
            f"common authority schema is incomplete: {sorted(required_authority - set(authority.columns))}"
        )
    authority = authority.loc[authority["market"].isin({"KOSPI", "KOSDAQ"}), ["ticker", "name", "market"]].copy()
    if authority.empty or authority[["ticker", "name", "market"]].isna().any().any():
        raise ValueError("common authority is empty or has incomplete identity")
    authority["ticker"] = authority["ticker"].astype(str).str.strip()
    authority["name"] = authority["name"].astype(str).str.strip()
    authority["market"] = authority["market"].astype(str).str.strip()
    if authority["ticker"].eq("").any() or authority["name"].eq("").any():
        raise ValueError("common authority has incomplete identity")
    if authority["ticker"].duplicated().any():
        raise ValueError("common authority contains duplicate tickers")

    membership = pd.read_parquet(sector_path)
    required = {"ticker", "sector_name"}
    if not required.issubset(membership.columns):
        raise ValueError(f"sector membership schema is incomplete: {sorted(required - set(membership.columns))}")
    if membership["ticker"].duplicated().any():
        raise ValueError("sector membership contains duplicate tickers")
    membership = membership.copy()
    membership["ticker"] = membership["ticker"].astype(str)
    sectors = membership.set_index("ticker")["sector_name"].to_dict()
    projected = []
    for item in authority.sort_values("ticker").to_dict("records"):
        ticker = str(item["ticker"])
        sector_name = sectors.get(ticker)
        projected.append(
            {
                "ticker": ticker,
                "name": str(item["name"]),
                "market": str(item["market"]),
                "asset_type": "COMMON",
                "sector_name": None if pd.isna(sector_name) else str(sector_name),
                "report_available": report_by_ticker.get(ticker, False),
            }
        )
    return projected, as_of


def load_flow_source(path: Path = DEFAULT_FLOW_PATH) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_parquet(path)
    if not REQUIRED_FLOW_COLUMNS.issubset(frame.columns):
        raise ValueError(f"foreign flow source schema is incomplete: {sorted(REQUIRED_FLOW_COLUMNS - set(frame.columns))}")
    frame = frame.loc[:, ["date", "ticker", FLOW_COLUMN]].copy()
    frame["date"] = frame["date"].astype(str).str[:10]
    frame["ticker"] = frame["ticker"].astype(str)
    frame[FLOW_COLUMN] = pd.to_numeric(frame[FLOW_COLUMN], errors="coerce")
    if frame[["date", "ticker", FLOW_COLUMN]].isna().any().any() or not frame[FLOW_COLUMN].map(math.isfinite).all():
        raise ValueError("foreign flow source has invalid values")
    if frame.duplicated(["date", "ticker"]).any():
        raise ValueError("foreign flow source has duplicate date/ticker rows")
    meta_path = path.with_name(f"{path.stem}_meta.json")
    meta = _read_json(meta_path) if meta_path.exists() else {}
    return frame, meta


def _flow_values_by_horizon(
    flow: pd.DataFrame,
    target_tickers: set[str],
    as_of: str,
) -> tuple[dict[int, dict[str, float | None]], list[str], dict[int, int]]:
    if as_of not in set(flow["date"]):
        raise ValueError(f"foreign flow source has no exact as-of row: {as_of}")
    dates = sorted(date for date in flow["date"].unique() if date <= as_of)
    if len(dates) < max(HORIZONS):
        raise ValueError(f"foreign flow source has only {len(dates)} sessions through {as_of}")
    values: dict[int, dict[str, float | None]] = {}
    eligible_counts: dict[int, int] = {}
    for horizon in HORIZONS:
        window_dates = dates[-horizon:]
        window = flow[flow["date"].isin(window_dates)]
        sums = window.groupby("ticker", sort=False)[FLOW_COLUMN].sum()
        observations = window.groupby("ticker", sort=False)["date"].nunique()
        by_ticker: dict[str, float | None] = {}
        for ticker in target_tickers:
            if int(observations.get(ticker, 0)) == horizon:
                by_ticker[ticker] = float(sums[ticker])
            else:
                by_ticker[ticker] = None
        values[horizon] = by_ticker
        eligible_counts[horizon] = sum(value is not None for value in by_ticker.values())
    return values, dates, eligible_counts


def _close_value(frame: pd.DataFrame, date: str) -> float | None:
    if date not in frame.index:
        return None
    value = frame.loc[date, "close"]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price_fields(
    repository: Any,
    ticker: str,
    session_dates: list[str],
    as_of: str,
) -> tuple[float | None, str | None, dict[int, float | None]]:
    try:
        frame = repository.get_daily(ticker, session_dates[0], as_of)
    except MarketDataError as exc:
        if str(exc) not in EXPECTED_DATA_UNAVAILABLE:
            raise
        return None, None, {horizon: None for horizon in HORIZONS}
    if frame is None or frame.empty:
        return None, None, {horizon: None for horizon in HORIZONS}
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index).normalize().strftime("%Y-%m-%d")
    frame = frame[~frame.index.duplicated(keep="last")]
    latest_close = _close_value(frame, as_of)
    returns: dict[int, float | None] = {}
    for horizon in HORIZONS:
        anchor_date = session_dates[-(horizon + 1)]
        anchor = _close_value(frame, anchor_date)
        if latest_close is None or anchor in (None, 0):
            returns[horizon] = None
        else:
            returns[horizon] = latest_close / anchor - 1.0
    return latest_close, as_of if latest_close is not None else None, returns


def build_foreign_net_buy_ranking(
    *,
    index_path: Path = DEFAULT_INDEX_PATH,
    flow_path: Path = DEFAULT_FLOW_PATH,
    sector_path: Path = DEFAULT_SECTOR_PATH,
    common_authority_path: Path = DEFAULT_COMMON_AUTHORITY_PATH,
    repository: Any | None = None,
    as_of: str = AS_OF,
) -> dict[str, Any]:
    universe, universe_snapshot_date = load_common_universe(index_path, sector_path, common_authority_path, as_of)
    flow, flow_meta = load_flow_source(flow_path)
    target_tickers = {item["ticker"] for item in universe}
    flow_values, source_dates, eligible_counts = _flow_values_by_horizon(flow, target_tickers, as_of)
    source_tickers = set(flow["ticker"])
    flow_covered_tickers = target_tickers & source_tickers

    if repository is None:
        repository = build_repository_v2(ROOT, end=as_of)

    items: list[dict[str, Any]] = []
    price_exact_resolved_count = 0
    return_resolved_counts = {horizon: 0 for horizon in HORIZONS}
    for identity in universe:
        ticker = identity["ticker"]
        latest_close, latest_close_as_of, returns = _price_fields(repository, ticker, source_dates, as_of)
        if latest_close is not None:
            price_exact_resolved_count += 1
        for horizon, value in returns.items():
            if value is not None:
                return_resolved_counts[horizon] += 1
        item = {
            **identity,
            "latest_close": latest_close,
            "latest_close_as_of": latest_close_as_of,
        }
        for horizon in HORIZONS:
            item[f"foreign_net_buy_{horizon}d"] = flow_values[horizon][ticker]
            item[f"stock_return_{horizon}d"] = returns[horizon]
        items.append(item)

    source_min = min(source_dates)
    source_max = max(source_dates)
    return {
        "schema_version": 1,
        "as_of": as_of,
        "scope": {
            "type": "KRX_COMMON_STOCKS",
            "markets": ["KOSPI", "KOSDAQ"],
            "asset_type": "COMMON",
            "label": "KOSPI·KOSDAQ 보통주",
            "universe_snapshot_date": universe_snapshot_date,
            "universe_authority_path": _display_path(common_authority_path),
        },
        "horizons": [f"{horizon}d" for horizon in HORIZONS],
        "source": {
            "path": _display_path(flow_path),
            "as_of": flow_meta.get("requested_as_of", source_max),
            "date_min": flow_meta.get("date_min", source_min),
            "date_max": flow_meta.get("date_max", source_max),
            "trading_session_count": len(source_dates),
            "ticker_count": len(source_tickers),
            "field": FLOW_COLUMN,
        },
        "coverage": {
            "target_common_universe_count": len(target_tickers),
            "flow_covered_count": len(flow_covered_tickers),
            "missing_flow_count": len(target_tickers - source_tickers),
            "source_extra_non_target_count": len(source_tickers - target_tickers),
            "target_market_counts": {
                market: sum(item["market"] == market for item in universe)
                for market in ("KOSPI", "KOSDAQ")
            },
            "eligible_counts": {f"{horizon}d": eligible_counts[horizon] for horizon in HORIZONS},
            "price_exact_resolved_count": price_exact_resolved_count,
            "price_exact_unresolved_count": len(items) - price_exact_resolved_count,
            "return_resolved_counts": {f"{horizon}d": return_resolved_counts[horizon] for horizon in HORIZONS},
            "return_unresolved_counts": {
                f"{horizon}d": len(items) - return_resolved_counts[horizon] for horizon in HORIZONS
            },
        },
        "items": items,
    }


def export_foreign_net_buy_ranking(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    payload = build_foreign_net_buy_ranking()
    _write_json(output_path, payload)
    return {
        "output": _display_path(output_path),
        "as_of": payload["as_of"],
        "item_count": len(payload["items"]),
        "eligible_counts": payload["coverage"]["eligible_counts"],
        "flow_covered_count": payload["coverage"]["flow_covered_count"],
        "missing_flow_count": payload["coverage"]["missing_flow_count"],
        "price_exact_resolved_count": payload["coverage"]["price_exact_resolved_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(export_foreign_net_buy_ranking(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
