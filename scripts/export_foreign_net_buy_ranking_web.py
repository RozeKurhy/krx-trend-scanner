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


def _load_pit_identity_names(repo_root: Path, as_of: str) -> dict[str, str]:
    """공식 PIT identity authority(InstrumentMetadataResolver)에서 as_of 이하 최신
    snapshot의 ticker -> name만 읽는다.

    PHASE4C_FINAL_FIX_V01: ``stock-index.json``은 4B 발행 여부(report_available)
    확인에만 쓴다는 Phase 4 계약이 있어, 종목명 authority로 쓰지 않는다. 시장
    (market)은 기존 ``common_authority_path``가 이미 제공하므로 여기서는 이름만
    조인한다 -- 새 identity source를 만들지 않고 기존 공식 resolver를 재사용한다.
    """
    import sys

    src_dir = str(repo_root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    frame = InstrumentMetadataResolver.load_master_dataframe(repo_root).copy()
    required = {"ticker", "name", "effective_date"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("PIT identity authority is empty or incomplete")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="coerce")
    eligible = frame[frame["effective_date"].notna() & (frame["effective_date"] <= pd.Timestamp(as_of))]
    if eligible.empty:
        raise ValueError("PIT identity authority has no PIT-eligible rows")
    snapshot_date = eligible["effective_date"].max()
    current = eligible[eligible["effective_date"] == snapshot_date].copy()
    if current["ticker"].duplicated().any():
        raise ValueError("PIT identity authority contains duplicate PIT tickers")
    return {
        str(row["ticker"]): str(row["name"]).strip()
        for row in current.to_dict("records")
        if str(row.get("name") or "").strip()
    }


def load_common_universe(
    index_path: Path = DEFAULT_INDEX_PATH,
    sector_path: Path = DEFAULT_SECTOR_PATH,
    common_authority_path: Path = DEFAULT_COMMON_AUTHORITY_PATH,
    as_of: str = AS_OF,
    *,
    identity_as_of: str | None = None,
    repo_root: Path = ROOT,
) -> tuple[list[dict[str, Any]], str | None]:
    """Resolve the exact production common-stock authority and sector labels.

    ``identity_as_of``(선택, PHASE4C_NON_TRADING_PIT_DATE_FINAL_FIX): PIT identity/
    name 조회 기준일. 생략하면 ``as_of``를 그대로 쓴다(하위 호환, 기존 동작 유지).
    명시하면(Phase 4 날짜 계약: identity_as_of=requested_as_of) 시장/수급 계산은
    여전히 ``as_of``(reference_market_date)를 쓰고, PIT identity/name만 이 값
    기준으로 조회한다 -- 비거래일 target_as_of에서도 identity 기준일이 어긋나지
    않도록 한다.
    """
    effective_identity_as_of = identity_as_of or as_of

    index = _read_json(index_path)
    if index.get("schema_version") != 1 or not isinstance(index.get("items"), list):
        raise ValueError("stock-index schema is incomplete")
    # stock-index는 report_available 확인에만 쓴다 (Phase 4 계약) -- 종목명/시장
    # authority로 쓰지 않는다.
    report_by_ticker: dict[str, bool] = {}
    for item in index["items"]:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        ticker = str(item["ticker"])
        if ticker in report_by_ticker:
            raise ValueError("stock-index contains duplicate tickers")
        report_by_ticker[ticker] = bool(item.get("report_available", False))

    authority = pd.read_csv(common_authority_path, dtype=str)
    required_authority = {"ticker", "market"}
    if not required_authority.issubset(authority.columns):
        raise ValueError(
            f"common authority schema is incomplete: {sorted(required_authority - set(authority.columns))}"
        )
    # PHASE4C_FINAL_FIX_V01: exact-target(2026-09-17) market RS universe authority
    # 스키마에는 name 컬럼이 없다(0904 스키마와 다름). 종목명은 공식 PIT identity
    # authority(InstrumentMetadataResolver)에서 조인한다 -- market_rs_universe는
    # ticker/market 모집단 authority 역할을 그대로 유지한다.
    if "name" not in authority.columns:
        name_by_ticker = _load_pit_identity_names(repo_root, effective_identity_as_of)
        authority = authority[["ticker", "market"]].copy()
        authority["name"] = authority["ticker"].astype(str).str.strip().str.upper().map(name_by_ticker)
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
    requested_as_of: str | None = None,
    reference_market_date: str | None = None,
    identity_as_of: str | None = None,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """``requested_as_of``/``reference_market_date``(선택, PHASE4C_FINAL_FIX_V01):
    명시하면 Phase 4 날짜 계약(requested_as_of=target_as_of, reference_market_date=
    실제 시장 거래일, as_of=reference_market_date)에 맞춰 payload 최상위에 세 필드를
    모두 노출한다. 생략하면 기존과 완전히 동일하게 ``as_of``만 노출한다(하위 호환).
    ``as_of``(실제 조회 기준일)는 항상 그대로 유지한다 -- reference_market_date와
    다른 값을 의도적으로 넘기는 호출자(과거 검증 스크립트 등)를 깨지 않기 위함이다.

    ``identity_as_of``(선택, PHASE4C_NON_TRADING_PIT_DATE_FINAL_FIX): PIT identity/
    name 조회 기준일을 ``as_of``와 분리한다. Production 호출에서는
    ``identity_as_of=requested_as_of``를 넘겨 비거래일 target_as_of에서도 PIT
    identity가 requested_as_of 기준으로 조회되도록 한다. 생략하면
    ``load_common_universe``가 ``as_of``로 폴백한다(하위 호환).
    """
    universe, universe_snapshot_date = load_common_universe(
        index_path, sector_path, common_authority_path, as_of,
        identity_as_of=identity_as_of, repo_root=repo_root,
    )
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
        **({"requested_as_of": requested_as_of} if requested_as_of is not None else {}),
        **({"reference_market_date": reference_market_date} if reference_market_date is not None else {}),
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
