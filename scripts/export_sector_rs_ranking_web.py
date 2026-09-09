"""Export the closed Sector RS ranking authority as a static web payload."""

from __future__ import annotations

import argparse
import json
import math
import socket
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RANKING_PATH = ROOT / "data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904.parquet"
DEFAULT_META_PATH = ROOT / "data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904_meta.json"
DEFAULT_BASIC_INFO_DIR = ROOT / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info/2026/20260904"
DEFAULT_STOCKS_DIR = ROOT / "web/data/stocks"
DEFAULT_OUTPUT_PATH = ROOT / "web/data/sector-rs-ranking.json"
HORIZONS = ("2w", "1m", "3m", "6m", "12m")
RANK_COLUMNS = tuple(f"within_sector_rs_rank_{horizon}" for horizon in HORIZONS)
PERCENTILE_COLUMNS = tuple(f"within_sector_rs_percentile_{horizon}" for horizon in HORIZONS)
ELIGIBLE_COUNT_COLUMNS = tuple(f"sector_eligible_count_{horizon}" for horizon in HORIZONS)
SECTOR_ANCHOR_COLUMNS = tuple(f"sector_anchor_date_{horizon}" for horizon in HORIZONS)
SECTOR_STOCK_RETURN_COLUMNS = tuple(f"sector_stock_return_{horizon}" for horizon in HORIZONS)
DISPLAY_COLUMNS = ("latest_close", "latest_close_as_of", *SECTOR_ANCHOR_COLUMNS, *SECTOR_STOCK_RETURN_COLUMNS)
MEMBERSHIP_STATUSES = ("MAPPED", "AGGREGATE_ONLY", "UNMAPPED")
EXPECTED_MARKETS = ("KOSPI", "KOSDAQ")


def _network_blocked(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("SECTOR_RS_WEB_EXPORT_NETWORK_REQUEST_PROHIBITED")


def _install_network_guard() -> None:
    socket.socket.connect = _network_blocked  # type: ignore[method-assign]
    socket.create_connection = _network_blocked  # type: ignore[assignment]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy scalars and non-finite values to strict JSON values."""

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (float,)):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _text(value: Any) -> str | None:
    value = _json_value(value)
    if value is None:
        return None
    return str(value).strip()


def _ticker(value: Any) -> str:
    value = (_text(value) or "").upper()
    if value.isdigit():
        value = value.zfill(6)
    if len(value) != 6 or not value.isalnum():
        raise ValueError(f"invalid ticker: {value!r}")
    return value


def _normalise_date(value: Any) -> str | None:
    value = _json_value(value)
    if value is None:
        return None
    return str(value)[:10]


def _load_core(ranking_path: Path, meta_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    meta = _read_json(meta_path)
    if meta.get("schema_version") != "SECTOR_RS_RANKING_V01":
        raise ValueError("unexpected Sector RS ranking schema")
    ranking = pd.read_parquet(ranking_path)
    required = {
        "as_of",
        "ticker",
        "market",
        "membership_status",
        "sector_code",
        "sector_name",
        "sector_rs_data_status",
        "sector_rs_input_reason",
        "sector_benchmark_last_observation_date",
        *(f"sector_rs_{horizon}" for horizon in HORIZONS),
        *RANK_COLUMNS,
        *PERCENTILE_COLUMNS,
        "sector_member_count",
        *ELIGIBLE_COUNT_COLUMNS,
        *DISPLAY_COLUMNS,
    }
    missing = sorted(required.difference(ranking.columns))
    if missing:
        raise ValueError(f"ranking authority is missing columns: {','.join(missing)}")
    if not isinstance(meta.get("as_of"), str):
        raise ValueError("ranking authority meta is missing as_of")
    return ranking.reset_index(drop=True), meta


def _validate_core(ranking: pd.DataFrame, meta: dict[str, Any]) -> dict[str, int]:
    as_of = str(meta["as_of"])
    if as_of != "2026-09-04":
        raise ValueError(f"unexpected ranking as_of: {as_of}")
    membership_meta = meta.get("membership")
    validation_meta = meta.get("validation")
    if not isinstance(membership_meta, dict) or not isinstance(validation_meta, dict):
        raise ValueError("ranking authority meta is incomplete")

    ranking["ticker"] = ranking["ticker"].map(_ticker)
    ranking["market"] = ranking["market"].map(lambda value: (_text(value) or "").upper())
    ranking["membership_status"] = ranking["membership_status"].map(
        lambda value: (_text(value) or "").upper()
    )
    ranking["sector_code"] = ranking["sector_code"].map(_text)
    ranking["sector_name"] = ranking["sector_name"].map(_text)

    if len(ranking) != int(membership_meta.get("population_total", -1)):
        raise ValueError("ranking authority population does not match meta")
    if ranking["ticker"].duplicated().any():
        raise ValueError("ranking authority has duplicate tickers")
    if ranking["as_of"].astype(str).str[:10].ne(as_of).any():
        raise ValueError("ranking authority has mixed as_of values")
    if not set(ranking["membership_status"]).issubset(set(MEMBERSHIP_STATUSES)):
        raise ValueError("ranking authority has an unknown membership status")

    status_counts = ranking["membership_status"].value_counts().to_dict()
    for status, key in (("MAPPED", "mapped"), ("AGGREGATE_ONLY", "aggregate_only"), ("UNMAPPED", "unmapped")):
        expected = int(membership_meta.get(key, -1))
        if int(status_counts.get(status, 0)) != expected:
            raise ValueError(f"ranking authority {status} count does not match meta")

    rankable = ranking["membership_status"].isin(("MAPPED", "AGGREGATE_ONLY"))
    if ranking.loc[rankable, "sector_code"].isna().any() or ranking.loc[rankable, "sector_name"].isna().any():
        raise ValueError("rankable authority row has incomplete sector identity")
    if ranking.loc[~rankable, "membership_status"].eq("UNMAPPED").any():
        if ranking.loc[~rankable, "sector_code"].notna().any() or ranking.loc[~rankable, "sector_name"].notna().any():
            raise ValueError("UNMAPPED authority row has sector identity")

    for horizon, rank_column, percentile_column in zip(HORIZONS, RANK_COLUMNS, PERCENTILE_COLUMNS):
        ranks = pd.to_numeric(ranking[rank_column], errors="coerce")
        percentiles = pd.to_numeric(ranking[percentile_column], errors="coerce")
        if ranks.notna().any() and not ranks.dropna().map(math.isfinite).all():
            raise ValueError(f"ranking authority has non-finite {rank_column}")
        if percentiles.notna().any() and not percentiles.dropna().map(math.isfinite).all():
            raise ValueError(f"ranking authority has non-finite {percentile_column}")
        if ((ranks.notna()) & ((ranks < 1) | (ranks > pd.to_numeric(ranking[f"{rank_column.replace('within_sector_rs_rank', 'sector_eligible_count')}"])))) .any():
            raise ValueError(f"ranking authority has invalid {rank_column}")
        if ((percentiles.notna()) & ((percentiles < 0) | (percentiles > 100))).any():
            raise ValueError(f"ranking authority has invalid {percentile_column}")
        expected_eligible = int(validation_meta.get(f"eligible_total_{horizon}", -1))
        if int(ranks.notna().sum()) != expected_eligible:
            raise ValueError(f"ranking authority {horizon} eligible count does not match meta")

    group_count = int(
        ranking.loc[rankable, ["market", "sector_code"]].drop_duplicates().shape[0]
    )
    if group_count != int(validation_meta.get("sector_group_count", -1)):
        raise ValueError("ranking authority sector group count does not match meta")

    return {
        "population_count": int(len(ranking)),
        "mapped_count": int(status_counts.get("MAPPED", 0)),
        "aggregate_only_count": int(status_counts.get("AGGREGATE_ONLY", 0)),
        "unmapped_count": int(status_counts.get("UNMAPPED", 0)),
        "sector_group_count": group_count,
        **{f"eligible_count_{horizon}": int(pd.to_numeric(ranking[f"within_sector_rs_rank_{horizon}"], errors="coerce").notna().sum()) for horizon in HORIZONS},
    }


def _load_name_authority(basic_info_dir: Path) -> dict[str, dict[str, str]]:
    by_ticker: dict[str, dict[str, str]] = {}
    for market in EXPECTED_MARKETS:
        path = basic_info_dir / f"{market}.json"
        block = _read_json(path).get("OutBlock_1")
        if not isinstance(block, list):
            raise ValueError(f"basic info source has no OutBlock_1 list: {path}")
        for row in block:
            if not isinstance(row, dict):
                raise ValueError(f"basic info source has invalid row: {path}")
            ticker = _ticker(row.get("ISU_SRT_CD"))
            name = _text(row.get("ISU_ABBRV"))
            row_market = (_text(row.get("MKT_TP_NM")) or "").upper()
            if not name or row_market != market:
                raise ValueError(f"basic info identity is invalid: {path} {ticker}")
            if ticker in by_ticker:
                raise ValueError(f"basic info has duplicate ticker: {ticker}")
            by_ticker[ticker] = {"name": name, "market": row_market}
    return by_ticker


def _load_report_file_set(stocks_dir: Path) -> set[str]:
    report_tickers: set[str] = set()
    for path in sorted(stocks_dir.glob("*.json")):
        ticker = _ticker(path.stem)
        report = _read_json(path)
        identity = report.get("identity")
        if not isinstance(identity, dict) or _ticker(identity.get("ticker")) != ticker:
            raise ValueError(f"stock report internal identity mismatch: {path}")
        if ticker in report_tickers:
            raise ValueError(f"duplicate stock report ticker: {ticker}")
        report_tickers.add(ticker)
    return report_tickers


def _sector_key(market: str | None, sector_code: str | None) -> str | None:
    if not market or not sector_code:
        return None
    return f"{market}:{sector_code}"


def _build_sectors(ranking: pd.DataFrame) -> list[dict[str, Any]]:
    rankable = ranking[ranking["membership_status"].isin(("MAPPED", "AGGREGATE_ONLY"))].copy()
    sectors: list[dict[str, Any]] = []
    for (market, sector_code), group in rankable.groupby(["market", "sector_code"], sort=True, dropna=False):
        names = {name for name in group["sector_name"].dropna().map(_text) if name}
        if len(names) != 1:
            raise ValueError(f"sector group has mixed names: {market}:{sector_code}")
        member_count = len(group)
        if not group["sector_member_count"].map(_json_value).eq(member_count).all():
            raise ValueError(f"sector member count is not canonical: {market}:{sector_code}")
        item: dict[str, Any] = {
            "sector_key": _sector_key(str(market), str(sector_code)),
            "market": str(market),
            "sector_code": str(sector_code),
            "sector_name": next(iter(names)),
            "member_count": member_count,
        }
        for horizon in HORIZONS:
            rank_column = f"within_sector_rs_rank_{horizon}"
            eligible_count = int(pd.to_numeric(group[rank_column], errors="coerce").notna().sum())
            authority_counts = pd.to_numeric(group[f"sector_eligible_count_{horizon}"], errors="coerce")
            if authority_counts.nunique(dropna=True) != 1 or int(authority_counts.dropna().iloc[0]) != eligible_count:
                raise ValueError(f"sector eligible count is not canonical: {market}:{sector_code}:{horizon}")
            item[f"eligible_count_{horizon}"] = eligible_count
        sectors.append(item)
    return sectors


def _project_items(
    ranking: pd.DataFrame,
    names: dict[str, dict[str, str]],
    report_tickers: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in ranking.sort_values(["market", "sector_code", "ticker"], kind="mergesort", na_position="last").to_dict(orient="records"):
        ticker = str(row["ticker"])
        name_record = names.get(ticker)
        if name_record is None:
            raise ValueError(f"exact 2026-09-04 Basic Info name unresolved: {ticker}")
        if name_record["market"] != row["market"]:
            raise ValueError(f"exact Basic Info market mismatch: {ticker}")
        sector_code = _text(row.get("sector_code"))
        sector_name = _text(row.get("sector_name"))
        sector_key = _sector_key(row["market"], sector_code)
        item: dict[str, Any] = {
            "ticker": ticker,
            "name": name_record["name"],
            "market": row["market"],
            "membership_status": row["membership_status"],
            "sector_key": sector_key,
            "sector_code": sector_code,
            "sector_name": sector_name,
            "report_available": ticker in report_tickers,
            "sector_rs_data_status": _json_value(row.get("sector_rs_data_status")),
            "sector_rs_input_reason": _json_value(row.get("sector_rs_input_reason")),
            "sector_benchmark_last_observation_date": _normalise_date(row.get("sector_benchmark_last_observation_date")),
            "latest_close": _json_value(row.get("latest_close")),
            "latest_close_as_of": _normalise_date(row.get("latest_close_as_of")),
        }
        for horizon in HORIZONS:
            item[f"sector_rs_{horizon}"] = _json_value(row.get(f"sector_rs_{horizon}"))
            item[f"sector_anchor_date_{horizon}"] = _normalise_date(row.get(f"sector_anchor_date_{horizon}"))
            item[f"sector_stock_return_{horizon}"] = _json_value(row.get(f"sector_stock_return_{horizon}"))
        for column in RANK_COLUMNS + PERCENTILE_COLUMNS + ("sector_member_count",) + ELIGIBLE_COUNT_COLUMNS:
            item[column] = _json_value(row.get(column))
        items.append(item)
    return items


def _validate_payload(
    payload: dict[str, Any],
    ranking: pd.DataFrame,
    meta: dict[str, Any],
    names: dict[str, dict[str, str]],
    report_tickers: set[str],
) -> dict[str, int]:
    items = payload["items"]
    sectors = payload["sectors"]
    expected = _validate_core(ranking.copy(), meta)
    if len(items) != expected["population_count"]:
        raise ValueError("payload item population is not conserved")
    if len(sectors) != expected["sector_group_count"]:
        raise ValueError("payload sector count is not canonical")

    item_by_ticker = {item["ticker"]: item for item in items}
    if len(item_by_ticker) != len(items):
        raise ValueError("payload has duplicate tickers")
    if set(item_by_ticker) != set(ranking["ticker"]):
        raise ValueError("payload ticker set differs from authority")
    authority_by_ticker = ranking.set_index("ticker").to_dict(orient="index")
    parity_fields = (
        *(f"sector_rs_{horizon}" for horizon in HORIZONS),
        *RANK_COLUMNS,
        *PERCENTILE_COLUMNS,
        "sector_member_count",
        *ELIGIBLE_COUNT_COLUMNS,
    )
    rank_parity_mismatches = 0
    percentile_parity_mismatches = 0
    for item in items:
        ticker = item["ticker"]
        source = authority_by_ticker[ticker]
        for field in parity_fields:
            if item[field] != _json_value(source.get(field)):
                if field in RANK_COLUMNS:
                    rank_parity_mismatches += 1
                elif field in PERCENTILE_COLUMNS:
                    percentile_parity_mismatches += 1
                else:
                    raise ValueError(f"payload authority parity mismatch: {ticker}:{field}")
        if item["name"] != names[ticker]["name"] or item["market"] != names[ticker]["market"]:
            raise ValueError(f"payload exact name identity mismatch: {ticker}")
        if item["report_available"] != (ticker in report_tickers):
            raise ValueError(f"payload report availability mismatch: {ticker}")
        if item["membership_status"] == "UNMAPPED":
            if any(item[column] is not None for column in ("sector_key", "sector_code", "sector_name", *RANK_COLUMNS, *PERCENTILE_COLUMNS)):
                raise ValueError(f"UNMAPPED payload row is not null: {ticker}")
        elif item["sector_key"] != _sector_key(item["market"], item["sector_code"]):
            raise ValueError(f"payload sector key mismatch: {ticker}")

    sector_by_key = {sector["sector_key"]: sector for sector in sectors}
    if len(sector_by_key) != len(sectors):
        raise ValueError("payload has duplicate sectors")
    for item in items:
        if item["sector_key"] is None:
            continue
        sector = sector_by_key[item["sector_key"]]
        for field in ("member_count", *[f"eligible_count_{horizon}" for horizon in HORIZONS]):
            item_field = "sector_member_count" if field == "member_count" else f"sector_{field}"
            if item[item_field] != sector[field]:
                raise ValueError(f"payload sector metadata mismatch: {item['ticker']}:{field}")

    report_available_count = sum(bool(item["report_available"]) for item in items)
    report_set_mismatches = len({item["ticker"] for item in items if item["report_available"]} ^ (set(ranking["ticker"]) & report_tickers))
    name_unresolved = sum(1 for ticker in ranking["ticker"] if ticker not in names)
    market_mismatches = sum(1 for ticker, record in names.items() if ticker in item_by_ticker and record["market"] != item_by_ticker[ticker]["market"])
    if rank_parity_mismatches or percentile_parity_mismatches:
        raise ValueError("payload ranking parity does not match authority")
    if name_unresolved or market_mismatches or report_set_mismatches:
        raise ValueError("payload identity or report availability validation failed")
    latest_close_resolved = 0
    latest_close_as_of_mismatches = 0
    sector_stock_return_resolved = {horizon: 0 for horizon in HORIZONS}
    for item in items:
        latest_close = item["latest_close"]
        latest_close_as_of = item["latest_close_as_of"]
        if latest_close is None:
            if latest_close_as_of is not None:
                raise ValueError(f"unresolved latest close has an as-of date: {item['ticker']}")
        else:
            latest_close_resolved += 1
            if not isinstance(latest_close, (int, float)) or not math.isfinite(float(latest_close)) or float(latest_close) <= 0:
                raise ValueError(f"latest close is invalid: {item['ticker']}")
            if latest_close_as_of != meta["as_of"]:
                latest_close_as_of_mismatches += 1
        for horizon in HORIZONS:
            anchor = item[f"sector_anchor_date_{horizon}"]
            stock_return = item[f"sector_stock_return_{horizon}"]
            if stock_return is not None:
                if anchor is None:
                    raise ValueError(f"sector stock return has no anchor: {item['ticker']}:{horizon}")
                if not isinstance(stock_return, (int, float)) or not math.isfinite(float(stock_return)):
                    raise ValueError(f"sector stock return is invalid: {item['ticker']}:{horizon}")
                sector_stock_return_resolved[horizon] += 1
            if anchor is not None and anchor > meta["as_of"]:
                raise ValueError(f"sector anchor is after as_of: {item['ticker']}:{horizon}")
    if latest_close_as_of_mismatches:
        raise ValueError("latest close exact as-of validation failed")
    return {
        **expected,
        "name_resolved": len(ranking) - name_unresolved,
        "name_unresolved": name_unresolved,
        "market_mismatches": market_mismatches,
        "duplicate_ticker_count": len(items) - len(item_by_ticker),
        "report_available_count": report_available_count,
        "report_set_mismatches": report_set_mismatches,
        "rank_parity_mismatches": rank_parity_mismatches,
        "percentile_parity_mismatches": percentile_parity_mismatches,
        "sector_metadata_mismatches": 0,
        "invalid_json_number_count": 0,
        "latest_close_resolved": latest_close_resolved,
        "latest_close_unresolved": len(items) - latest_close_resolved,
        "latest_close_as_of_mismatches": latest_close_as_of_mismatches,
        **{
            f"sector_stock_return_{horizon}_resolved": count
            for horizon, count in sector_stock_return_resolved.items()
        },
    }


def build_sector_rs_web_payload(
    *,
    ranking_path: Path = DEFAULT_RANKING_PATH,
    meta_path: Path = DEFAULT_META_PATH,
    basic_info_dir: Path = DEFAULT_BASIC_INFO_DIR,
    stocks_dir: Path = DEFAULT_STOCKS_DIR,
) -> dict[str, Any]:
    """Project the closed authority without recomputing any Sector RS value."""

    _install_network_guard()
    ranking, meta = _load_core(ranking_path, meta_path)
    source_validation = _validate_core(ranking, meta)
    names = _load_name_authority(basic_info_dir)
    missing_names = set(ranking["ticker"]) - set(names)
    if missing_names:
        raise ValueError(f"exact 2026-09-04 Basic Info name join failed: {sorted(missing_names)}")
    report_tickers = _load_report_file_set(stocks_dir)
    sectors = _build_sectors(ranking)
    items = _project_items(ranking, names, report_tickers)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "as_of": str(meta["as_of"]),
        "scope": {
            "type": "EXACT_SECTOR_MEMBERSHIP_POPULATION",
            "population_count": source_validation["population_count"],
            "mapped_count": source_validation["mapped_count"],
            "aggregate_only_count": source_validation["aggregate_only_count"],
            "unmapped_count": source_validation["unmapped_count"],
            "sector_group_count": source_validation["sector_group_count"],
        },
        "metric_scope": {
            "type": "WITHIN_SECTOR",
            "group_key": ["market", "sector_code"],
            "label": "섹터 RS는 같은 섹터 구성종목끼리 비교",
        },
        "horizons": list(HORIZONS),
        "eligible_counts": {
            horizon: source_validation[f"eligible_count_{horizon}"] for horizon in HORIZONS
        },
        "source": {
            "ranking_schema": meta["schema_version"],
            "ranking_as_of": str(meta["as_of"]),
            "name_source_date": "2026-09-04",
        },
        "sectors": sectors,
        "items": items,
    }
    validation = _validate_payload(payload, ranking, meta, names, report_tickers)
    # Strict serialization is itself a final guard against NaN/Infinity leaking into JSON.
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    payload["_validation"] = validation
    # Validation is a builder result, not public payload data.
    payload.pop("_validation")
    return payload


def export_sector_rs_ranking_web(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_sector_rs_web_payload(**kwargs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    json.loads(serialized)
    ranking, meta = _load_core(kwargs.get("ranking_path", DEFAULT_RANKING_PATH), kwargs.get("meta_path", DEFAULT_META_PATH))
    names = _load_name_authority(kwargs.get("basic_info_dir", DEFAULT_BASIC_INFO_DIR))
    report_tickers = _load_report_file_set(kwargs.get("stocks_dir", DEFAULT_STOCKS_DIR))
    validation = _validate_payload(payload, ranking, meta, names, report_tickers)
    return {
        "output": str(output_path.relative_to(ROOT)) if output_path.is_relative_to(ROOT) else str(output_path),
        "schema_version": payload["schema_version"],
        "as_of": payload["as_of"],
        **validation,
        "network": {
            "krx_open_api": 0,
            "pykrx": 0,
            "marketplace": 0,
            "opendart": 0,
            "naver": 0,
            "direct_http": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ranking", type=Path, default=DEFAULT_RANKING_PATH)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META_PATH)
    parser.add_argument("--basic-info-dir", type=Path, default=DEFAULT_BASIC_INFO_DIR)
    parser.add_argument("--stocks-dir", type=Path, default=DEFAULT_STOCKS_DIR)
    args = parser.parse_args()
    print(
        json.dumps(
            export_sector_rs_ranking_web(
                output_path=args.output,
                ranking_path=args.ranking,
                meta_path=args.meta,
                basic_info_dir=args.basic_info_dir,
                stocks_dir=args.stocks_dir,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
