"""Export the fixed ETF price-ranking projection for the static web."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_pattern_a_universe_scanner import resolve_reference_market_date
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_instrument_contract import repository_v2_contract_for_metadata
from trend_scanner.data.repository_v2_loader import build_repository_v2
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver


DEFAULT_OUTPUT_PATH = ROOT / "web" / "data" / "etf-ranking.json"
HORIZONS = {"2w": 10, "1m": 21, "3m": 63, "6m": 126, "12m": 252}
READ_START = "2023-01-01"

# This is the web feature's fixed official 36-product universe. Product names are
# always read from the formal PIT metadata authority, never from this list.
ETF_UNIVERSE = (
    ("069500", "MARKET", "한국 대형시장"),
    ("229200", "MARKET", "코스닥150"),
    ("133690", "MARKET", "미국 나스닥100"),
    ("360750", "MARKET", "미국 S&P500"),
    ("241180", "MARKET", "일본 니케이225"),
    ("283580", "MARKET", "중국 CSI300"),
    ("453810", "MARKET", "인도 Nifty50"),
    ("245710", "MARKET", "베트남 VN30"),
    ("256440", "MARKET", "인도네시아 MSCI"),
    ("195980", "MARKET", "신흥국 MSCI"),
    ("379790", "MARKET", "유로스탁스50"),
    ("251350", "MARKET", "선진국 MSCI"),
    ("091160", "SECTOR", "반도체"),
    ("091180", "SECTOR", "자동차"),
    ("091170", "SECTOR", "은행"),
    ("102970", "SECTOR", "증권"),
    ("140700", "SECTOR", "보험"),
    ("117700", "SECTOR", "건설"),
    ("117680", "SECTOR", "철강"),
    ("117460", "SECTOR", "에너지화학"),
    ("139230", "SECTOR", "중공업"),
    ("157490", "SECTOR", "소프트웨어"),
    ("143860", "SECTOR", "헬스케어"),
    ("266410", "SECTOR", "필수소비재"),
    ("228790", "SECTOR", "화장품"),
    ("228810", "SECTOR", "미디어콘텐츠"),
    ("228800", "SECTOR", "여행레저"),
    ("300950", "SECTOR", "게임산업"),
    ("305720", "SECTOR", "2차전지산업"),
    ("449450", "SECTOR", "K방산"),
    ("367760", "SECTOR", "네트워크인프라"),
    ("411060", "COMMODITY", "금"),
    ("144600", "COMMODITY", "은"),
    ("160580", "COMMODITY", "구리"),
    ("261220", "COMMODITY", "원유"),
    ("271060", "COMMODITY", "농산물"),
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_universe() -> None:
    tickers = [ticker for ticker, _group, _category in ETF_UNIVERSE]
    if len(tickers) != 36 or len(set(tickers)) != 36:
        raise ValueError("ETF universe must contain exactly 36 unique tickers")
    expected_group_counts = {"MARKET": 12, "SECTOR": 19, "COMMODITY": 5}
    group_counts = pd.Series([group for _ticker, group, _category in ETF_UNIVERSE]).value_counts().to_dict()
    if group_counts != expected_group_counts:
        raise ValueError("ETF universe group counts do not match the official 36-product contract")


def _resolve_reference_market_date(target_as_of: str, repo_root: Path) -> str:
    calendar = load_rolling_production_market_calendar(repo_root)
    return resolve_reference_market_date(target_as_of, calendar)


def _load_metadata(repo_root: Path, *, reference_market_date: str) -> dict[str, Any]:
    metadata_by_ticker: dict[str, Any] = {}
    for ticker, _group, _category in ETF_UNIVERSE:
        metadata = InstrumentMetadataResolver.resolve(ticker, as_of=reference_market_date, repo_root=repo_root)
        if metadata.ticker != ticker or not metadata.is_identified:
            raise ValueError(f"ETF metadata identity is unavailable: {ticker}")
        if not metadata.is_trusted_for_production or metadata.asset_type != "ETF":
            raise ValueError(f"ETF metadata classification is not trusted: {ticker}")
        repository_v2_contract_for_metadata(metadata)
        metadata_by_ticker[ticker] = metadata
    if set(metadata_by_ticker) != {ticker for ticker, _group, _category in ETF_UNIVERSE}:
        raise ValueError("ETF metadata set does not match the fixed universe")
    return metadata_by_ticker


def _calculate_horizon_metrics(frame: pd.DataFrame, session_count: int, *, ticker: str) -> dict[str, float]:
    """Calculate all metrics from one exact anchor-plus-window slice."""

    if session_count <= 0 or len(frame) < session_count + 1:
        raise ValueError(f"ETF ranking window is incomplete: {ticker} {session_count}")
    anchor = frame.iloc[-(session_count + 1)]
    window = frame.iloc[-session_count:]
    if len(window) != session_count:
        raise ValueError(f"ETF ranking measurement window is incomplete: {ticker} {session_count}")

    anchor_close = float(anchor["close"])
    close = pd.to_numeric(pd.concat([pd.Series([anchor_close]), window["close"]], ignore_index=True), errors="coerce")
    high = pd.to_numeric(window["high"], errors="coerce")
    volume = pd.to_numeric(window["volume"], errors="coerce")
    trading_value = pd.to_numeric(window["trading_value"], errors="coerce")
    series_by_name = {
        "close": close,
        "high": high,
        "volume": volume,
        "trading_value": trading_value,
    }
    if not math.isfinite(anchor_close) or anchor_close <= 0:
        raise ValueError(f"ETF ranking anchor close is invalid: {ticker} {session_count}")
    for name, series in series_by_name.items():
        if series.isna().any() or not series.map(math.isfinite).all():
            raise ValueError(f"ETF ranking {name} is non-finite: {ticker} {session_count}")
    if (volume < 0).any() or (trading_value < 0).any():
        raise ValueError(f"ETF ranking raw flow is negative: {ticker} {session_count}")

    running_peak = close.cummax()
    drawdown = close / running_peak - 1.0
    metrics = {
        "return": float(close.iloc[-1] / anchor_close - 1.0),
        "mfe": float(high.max() / anchor_close - 1.0),
        "mdd": float(drawdown.min()),
        "avg_volume": float(volume.mean()),
        "avg_trading_value": float(trading_value.mean()),
    }
    if not all(math.isfinite(value) for value in metrics.values()) or metrics["mdd"] > 0:
        raise ValueError(f"ETF ranking derived metrics are invalid: {ticker} {session_count}")
    return metrics


def _project_item(
    repo: Any,
    ticker: str,
    group: str,
    category: str,
    metadata: Any,
    *,
    reference_market_date: str,
) -> dict[str, Any]:
    frame = repo.get_daily(ticker, READ_START, reference_market_date)
    if frame is None or frame.empty:
        raise ValueError(f"ETF ranking data is unavailable: {ticker}")
    frame = frame.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise ValueError(f"ETF ranking dates are invalid: {ticker}")
    if frame.index.max().strftime("%Y-%m-%d") != reference_market_date:
        raise ValueError(f"ETF ranking latest close is not as-of {reference_market_date}: {ticker}")

    close = pd.to_numeric(frame["close"], errors="coerce")
    if len(close) < max(HORIZONS.values()) + 1 or close.isna().any() or not close.map(math.isfinite).all() or (close <= 0).any():
        raise ValueError(f"ETF ranking close history is incomplete: {ticker}")

    latest_close = float(close.iloc[-1])
    horizon_metrics: dict[str, dict[str, float]] = {}
    for horizon, session_count in HORIZONS.items():
        horizon_metrics[horizon] = _calculate_horizon_metrics(frame, session_count, ticker=ticker)

    item = {
        "ticker": ticker,
        "name": metadata.name,
        "group": group,
        "category": category,
        "latest_close": latest_close,
        "latest_close_as_of": reference_market_date,
        "external_links": {
            "naver_finance": f"https://finance.naver.com/item/main.naver?code={ticker}",
            "naver_chart": f"https://stock.naver.com/fchart/domestic/stock/{ticker}",
        },
    }
    for horizon, metrics in horizon_metrics.items():
        for metric_name, value in metrics.items():
            item[f"{metric_name}_{horizon}"] = value
    return item


def build_etf_ranking(target_as_of: str, repo_root: Path | str = ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    reference_market_date = _resolve_reference_market_date(target_as_of, root)
    _validate_universe()
    metadata_by_ticker = _load_metadata(root, reference_market_date=reference_market_date)
    repo = build_repository_v2(root, end=reference_market_date)
    items = [
        _project_item(
            repo, ticker, group, category, metadata_by_ticker[ticker],
            reference_market_date=reference_market_date,
        )
        for ticker, group, category in ETF_UNIVERSE
    ]
    if len(items) != 36 or {item["ticker"] for item in items} != {ticker for ticker, _group, _category in ETF_UNIVERSE}:
        raise ValueError("ETF ranking item set is incomplete")
    items.sort(key=lambda item: (-float(item["return_1m"]), str(item["name"]), str(item["ticker"])))
    return {
        "schema_version": 1,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "as_of": reference_market_date,
        "scope": {"type": "FIXED_ETF_UNIVERSE", "count": 36},
        "horizons": HORIZONS.copy(),
        "items": items,
    }


def export_etf_ranking(target_as_of: str, output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    payload = build_etf_ranking(target_as_of)
    _write_json(output_path, payload)
    return {
        "output": str(output_path.relative_to(ROOT)),
        "as_of": payload["as_of"],
        "count": payload["scope"]["count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="Required target as-of date (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(export_etf_ranking(args.target_as_of, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
