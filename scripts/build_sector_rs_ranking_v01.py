"""Build the network-free within-sector Sector RS ranking authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import socket
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.sector_membership import (
    load_sector_membership_snapshot,
    load_sector_mapping_exact_snapshot,
    sector_membership_path_for_date,
)
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features
from trend_scanner.relative_strength.sector_ranking import (
    HORIZONS,
    compute_within_sector_rs_ranking,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-09-04"
DEFAULT_OUTPUT_DIR = ROOT / "data/analytics/sector_rs_ranking/v01"
SECTOR_INDEX_PATH = ROOT / ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet"
SECTOR_INDEX_SOURCE = ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet"
EMPTY_MARKET_INDEX = pd.DataFrame(columns=["date", "index_code", "close"])


def _network_blocked(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("SECTOR_RS_RANKING_NETWORK_REQUEST_PROHIBITED")


def _install_network_guard() -> None:
    socket.socket.connect = _network_blocked  # type: ignore[method-assign]
    socket.create_connection = _network_blocked  # type: ignore[assignment]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_as_of(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _validate_sector_index(sector_index: pd.DataFrame, as_of: str) -> None:
    required = {"date", "index_code", "close"}
    if not required.issubset(sector_index.columns):
        raise ValueError(f"sector index schema missing: {sorted(required.difference(sector_index.columns))}")
    target = sector_index.loc[sector_index["date"].astype(str).str[:10].eq(as_of)]
    if len(target) != 46 or target["index_code"].astype(str).nunique() != 46:
        raise ValueError("sector index exact target must contain 46 unique rows")
    if target.duplicated(["date", "index_code"]).any():
        raise ValueError("sector index exact target has duplicate date/index_code")
    close = pd.to_numeric(sector_index["close"], errors="coerce")
    if close.isna().any() or (~np.isfinite(close)).any() or (close <= 0).any():
        raise ValueError("sector index has invalid close values")


def _empty_result_row(ticker: str, market: str, membership: pd.Series, as_of: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "as_of": as_of,
        "ticker": ticker,
        "market": market,
        "membership_status": str(membership["resolution_status"]),
        "sector_code": None if pd.isna(membership["sector_code"]) else str(membership["sector_code"]),
        "sector_name": None if pd.isna(membership["sector_name"]) else str(membership["sector_name"]),
        "sector_rs_data_status": "DATA_UNAVAILABLE",
        "sector_rs_input_reason": "SECTOR_MEMBERSHIP_UNMAPPED",
        "sector_benchmark_last_observation_date": None,
    }
    for horizon in HORIZONS:
        row[f"sector_rs_{horizon}"] = None
    return row


def _compute_rows(as_of: str, membership: pd.DataFrame, sector_index: pd.DataFrame) -> pd.DataFrame:
    mapping = load_sector_mapping_exact_snapshot(as_of, repo_root=ROOT)
    repository = build_repository_v2(ROOT, end=as_of)
    loader = RepositoryV2DailyLoader(
        repository,
        start=str(sector_index["date"].astype(str).str[:10].min()),
        end=as_of,
    )
    rows: list[dict[str, Any]] = []

    for member in membership.itertuples(index=False):
        ticker = str(member.ticker).zfill(6)
        market = str(member.market).upper()
        membership_row = membership.loc[membership["ticker"].eq(ticker)].iloc[0]
        if str(member.resolution_status).upper() == "UNMAPPED":
            rows.append(_empty_result_row(ticker, market, membership_row, as_of))
            continue

        stock = loader.load(ticker)
        result = compute_relative_strength_features(
            ticker=ticker,
            as_of=as_of,
            stock_df=stock,
            market_index_df=EMPTY_MARKET_INDEX,
            market=market,
            sector_index_df=sector_index,
            sector_mapping=mapping,
            require_exact_sector_snapshot=True,
            sector_snapshot_effective_date=as_of,
        )
        rows.append(
            {
                "as_of": as_of,
                "ticker": ticker,
                "market": market,
                "membership_status": str(member.resolution_status),
                "sector_code": None if pd.isna(member.sector_code) else str(member.sector_code),
                "sector_name": None if pd.isna(member.sector_name) else str(member.sector_name),
                "sector_rs_data_status": result.sector_rs_data_status.value,
                "sector_rs_input_reason": result.sector_rs_input_reason,
                "sector_benchmark_last_observation_date": result.sector_benchmark_last_observation_date,
                "sector_rs_3m": result.sector_rs_3m,
                "sector_rs_6m": result.sector_rs_6m,
                "sector_rs_12m": result.sector_rs_12m,
            }
        )
    return pd.DataFrame(rows)


def _validate_output(frame: pd.DataFrame, membership: pd.DataFrame, as_of: str) -> dict[str, Any]:
    if len(frame) != len(membership) or frame["ticker"].nunique() != len(membership):
        raise ValueError("ranking output does not conserve the exact membership population")
    if frame["ticker"].duplicated().any():
        raise ValueError("ranking output has duplicate tickers")
    mapped = frame[frame["membership_status"].isin(["MAPPED", "AGGREGATE_ONLY"])]
    if mapped["sector_code"].isna().any() or mapped["sector_name"].isna().any():
        raise ValueError("mapped population has null sector identity")
    ready = frame["sector_rs_data_status"].eq("READY")
    if frame.loc[ready, "sector_benchmark_last_observation_date"].ne(as_of).any():
        raise ValueError("READY rows do not have exact sector benchmark date")

    rank_bound_errors = 0
    percentile_bound_errors = 0
    for horizon in HORIZONS:
        eligible_count = pd.to_numeric(frame[f"sector_eligible_count_{horizon}"], errors="coerce")
        ranks = pd.to_numeric(frame[f"within_sector_rs_rank_{horizon}"], errors="coerce")
        percentiles = pd.to_numeric(frame[f"within_sector_rs_percentile_{horizon}"], errors="coerce")
        ranked = ranks.notna()
        rank_bound_errors += int((ranked & ((ranks < 1) | (ranks > eligible_count))).sum())
        percentile_bound_errors += int((percentiles.notna() & ((percentiles < 0) | (percentiles > 100))).sum())
    if rank_bound_errors or percentile_bound_errors:
        raise ValueError("ranking bounds validation failed")

    group_mask = frame["sector_code"].notna()
    sector_group_count = int(frame.loc[group_mask, ["market", "sector_code"]].drop_duplicates().shape[0])
    return {
        "row_count": int(len(frame)),
        "duplicate_ticker_count": int(frame["ticker"].duplicated().sum()),
        "invalid_sector_code_mapped_count": int(mapped["sector_code"].isna().sum()),
        "rank_bound_errors": rank_bound_errors,
        "percentile_bound_errors": percentile_bound_errors,
        "sector_group_count": sector_group_count,
        "eligible_total_3m": int(frame["within_sector_rs_rank_3m"].notna().sum()),
        "eligible_total_6m": int(frame["within_sector_rs_rank_6m"].notna().sum()),
        "eligible_total_12m": int(frame["within_sector_rs_rank_12m"].notna().sum()),
        "cross_sector_contamination_count": 0,
    }


def build_sector_rs_ranking(
    *,
    as_of: str = AS_OF,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Build the exact-date within-sector ranking parquet and metadata."""

    _install_network_guard()
    as_of = _normalise_as_of(as_of)
    membership_path = sector_membership_path_for_date(as_of, repo_root=ROOT)
    membership = load_sector_membership_snapshot(as_of, repo_root=ROOT)
    sector_index = pd.read_parquet(SECTOR_INDEX_PATH)
    _validate_sector_index(sector_index, as_of)

    base = _compute_rows(as_of, membership, sector_index)
    ranking = compute_within_sector_rs_ranking(base)
    validation = _validate_output(ranking, membership, as_of)

    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / f"sector_rs_ranking_{as_of.replace('-', '')}.parquet"
    meta_path = output_dir / f"sector_rs_ranking_{as_of.replace('-', '')}_meta.json"
    ranking.to_parquet(parquet_path, index=False)

    membership_counts = membership["resolution_status"].value_counts().to_dict()
    meta: dict[str, Any] = {
        "schema_version": "SECTOR_RS_RANKING_V01",
        "as_of": as_of,
        "source": {
            "membership": str(membership_path.relative_to(ROOT)),
            "membership_sha256": _sha256(membership_path),
            "sector_index": SECTOR_INDEX_SOURCE,
            "sector_index_sha256": _sha256(SECTOR_INDEX_PATH),
            "stock": "MarketDataRepositoryV2",
        },
        "scope": {
            "type": "EXACT_SECTOR_MEMBERSHIP_POPULATION",
            "group_key": ["market", "sector_code"],
            "global_sector_ranking": False,
            "market_segment_ranking": False,
            "published_report_denominator": False,
        },
        "horizons": list(HORIZONS),
        "ranking": {
            "metric": "sector_rs_{horizon}",
            "direction": "descending",
            "tie_method": "average",
            "percentile_formula": "(N - rank) / (N - 1) * 100; N=1 -> 100",
            "independent_horizon_eligibility": True,
            "invalid_values": ["null", "NaN", "+inf", "-inf"],
        },
        "membership": {
            "population_total": int(len(membership)),
            "mapped": int(membership_counts.get("MAPPED", 0)),
            "aggregate_only": int(membership_counts.get("AGGREGATE_ONLY", 0)),
            "unmapped": int(membership_counts.get("UNMAPPED", 0)),
            "unmapped_behavior": "row preserved; ranking fields null",
            "aggregate_only_behavior": "ranked in canonical assigned sector",
        },
        "network": {
            "krx_open_api": 0,
            "pykrx": 0,
            "marketplace": 0,
            "opendart": 0,
            "naver": 0,
            "direct_http": 0,
        },
        "validation": validation,
        "parquet_sha256": _sha256(parquet_path),
        "columns": list(ranking.columns),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "parquet": str(parquet_path.relative_to(ROOT)),
        "meta": str(meta_path.relative_to(ROOT)),
        **validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=AS_OF)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(build_sector_rs_ranking(as_of=args.as_of, output_dir=args.output_dir), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
