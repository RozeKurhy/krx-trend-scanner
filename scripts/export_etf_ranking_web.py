"""Export the fixed ETF price-ranking projection for the static web."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.repository_v2_instrument_contract import repository_v2_contract_for_metadata
from trend_scanner.data.repository_v2_loader import build_repository_v2
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "web" / "data" / "etf-ranking.json"
AS_OF = "2026-09-04"
HORIZONS = {"2w": 10, "1m": 21, "3m": 63, "6m": 126, "12m": 252}
READ_START = "2023-01-01"

# This is the web feature's fixed 24-product universe.  Product names are
# always read from the formal PIT metadata authority, never from this list.
ETF_UNIVERSE = (
    ("069500", "MARKET", "한국 대형시장"),
    ("226490", "MARKET", "한국 전체시장"),
    ("229200", "MARKET", "코스닥"),
    ("091160", "SECTOR", "반도체"),
    ("091180", "SECTOR", "자동차"),
    ("091170", "SECTOR", "은행"),
    ("102970", "SECTOR", "증권"),
    ("140700", "SECTOR", "보험"),
    ("117700", "SECTOR", "건설"),
    ("117680", "SECTOR", "철강"),
    ("117460", "SECTOR", "에너지화학"),
    ("139230", "SECTOR", "중공업"),
    ("139260", "SECTOR", "IT"),
    ("157490", "SECTOR", "소프트웨어"),
    ("143860", "SECTOR", "헬스케어"),
    ("102960", "SECTOR", "기계장비"),
    ("140710", "SECTOR", "운송"),
    ("266410", "SECTOR", "필수소비재"),
    ("266390", "SECTOR", "경기소비재"),
    ("266360", "SECTOR", "K-콘텐츠"),
    ("133690", "OVERSEAS", "미국 기술주"),
    ("360750", "OVERSEAS", "미국 대표주"),
    ("241180", "OVERSEAS", "일본"),
    ("192090", "OVERSEAS", "중국"),
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_universe() -> None:
    tickers = [ticker for ticker, _group, _category in ETF_UNIVERSE]
    if len(tickers) != 24 or len(set(tickers)) != 24:
        raise ValueError("ETF universe must contain exactly 24 unique tickers")


def _load_metadata(repo_root: Path) -> dict[str, Any]:
    metadata_by_ticker: dict[str, Any] = {}
    for ticker, _group, _category in ETF_UNIVERSE:
        metadata = InstrumentMetadataResolver.resolve(ticker, as_of=AS_OF, repo_root=repo_root)
        if metadata.ticker != ticker or not metadata.is_identified:
            raise ValueError(f"ETF metadata identity is unavailable: {ticker}")
        if not metadata.is_trusted_for_production or metadata.asset_type != "ETF":
            raise ValueError(f"ETF metadata classification is not trusted: {ticker}")
        repository_v2_contract_for_metadata(metadata)
        metadata_by_ticker[ticker] = metadata
    if set(metadata_by_ticker) != {ticker for ticker, _group, _category in ETF_UNIVERSE}:
        raise ValueError("ETF metadata set does not match the fixed universe")
    return metadata_by_ticker


def _project_item(repo: Any, ticker: str, group: str, category: str, metadata: Any) -> dict[str, Any]:
    frame = repo.get_daily(ticker, READ_START, AS_OF)
    if frame is None or frame.empty:
        raise ValueError(f"ETF ranking data is unavailable: {ticker}")
    frame = frame.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
        raise ValueError(f"ETF ranking dates are invalid: {ticker}")
    if frame.index.max().strftime("%Y-%m-%d") != AS_OF:
        raise ValueError(f"ETF ranking latest close is not as-of {AS_OF}: {ticker}")

    close = pd.to_numeric(frame["close"], errors="coerce")
    if len(close) < max(HORIZONS.values()) + 1 or close.isna().any() or not close.map(math.isfinite).all() or (close <= 0).any():
        raise ValueError(f"ETF ranking close history is incomplete: {ticker}")

    latest_close = float(close.iloc[-1])
    returns: dict[str, float] = {}
    for horizon, session_count in HORIZONS.items():
        anchor_position = -(session_count + 1)
        anchor_close = float(close.iloc[anchor_position])
        value = latest_close / anchor_close - 1.0
        if not math.isfinite(value):
            raise ValueError(f"ETF ranking return is non-finite: {ticker} {horizon}")
        returns[horizon] = value

    return {
        "ticker": ticker,
        "name": metadata.name,
        "group": group,
        "category": category,
        "latest_close": latest_close,
        "latest_close_as_of": AS_OF,
        "return_2w": returns["2w"],
        "return_1m": returns["1m"],
        "return_3m": returns["3m"],
        "return_6m": returns["6m"],
        "return_12m": returns["12m"],
    }


def build_etf_ranking(repo_root: Path | str = ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    _validate_universe()
    metadata_by_ticker = _load_metadata(root)
    repo = build_repository_v2(root, end=AS_OF)
    items = [
        _project_item(repo, ticker, group, category, metadata_by_ticker[ticker])
        for ticker, group, category in ETF_UNIVERSE
    ]
    if len(items) != 24 or {item["ticker"] for item in items} != {ticker for ticker, _group, _category in ETF_UNIVERSE}:
        raise ValueError("ETF ranking item set is incomplete")
    items.sort(key=lambda item: (-float(item["return_1m"]), str(item["name"]), str(item["ticker"])))
    return {
        "schema_version": 1,
        "as_of": AS_OF,
        "scope": {"type": "FIXED_ETF_UNIVERSE", "count": 24},
        "horizons": HORIZONS.copy(),
        "items": items,
    }


def export_etf_ranking(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    payload = build_etf_ranking()
    _write_json(output_path, payload)
    return {
        "output": str(output_path.relative_to(ROOT)),
        "as_of": payload["as_of"],
        "count": payload["scope"]["count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(export_etf_ranking(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
