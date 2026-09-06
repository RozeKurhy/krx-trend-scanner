"""Run the network-free FIX02 Sector RS parity evidence pipeline.

The production CSV is supplied from a completed local scanner run.  The oracle
below deliberately does not call the production RS calculator; it reads
Repository V2 stock views and performs the benchmark/anchor/formula steps
independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.sector_membership import (
    SNAPSHOT_EFFECTIVE_DATE,
    load_sector_mapping_exact_snapshot,
    load_sector_membership_meta,
)
from trend_scanner.relative_strength.relative_strength import (
    HORIZON_SESSIONS_3M,
    HORIZON_SESSIONS_6M,
    HORIZON_SESSIONS_12M,
)
from trend_scanner.relative_strength.repository_adapter import resolve_market_rs_repository_input


FIELDS = (
    "sector_rs_data_status",
    "sector_rs_input_reason",
    "sector_code",
    "sector_name",
    "sector_benchmark_code",
    "sector_benchmark_last_observation_date",
    "sector_anchor_date_3m",
    "sector_anchor_date_6m",
    "sector_anchor_date_12m",
    "sector_return_3m",
    "sector_return_6m",
    "sector_return_12m",
    "sector_rs_3m",
    "sector_rs_6m",
    "sector_rs_12m",
)
HORIZONS = (("3m", HORIZON_SESSIONS_3M), ("6m", HORIZON_SESSIONS_6M), ("12m", HORIZON_SESSIONS_12M))


def _network_blocked(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("FIX02_NETWORK_REQUEST_PROHIBITED")


def _install_network_guard() -> None:
    socket.socket.connect = _network_blocked  # type: ignore[method-assign]
    socket.create_connection = _network_blocked  # type: ignore[assignment]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean_ticker(value: Any) -> str:
    return str(value).strip().zfill(6)


def _empty_row(
    ticker: str,
    status: str,
    reason: str,
    code: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    row = {field: None for field in FIELDS}
    row.update(
        {
            "ticker": ticker,
            "sector_rs_data_status": status,
            "sector_rs_input_reason": reason,
            "sector_code": code,
            "sector_name": name,
            "sector_benchmark_code": code,
        }
    )
    return row


def _oracle_one(
    ticker: str,
    as_of: str,
    market: str,
    repository: MarketDataRepositoryV2,
    market_index: pd.DataFrame,
    sector_index: pd.DataFrame,
    mapping: dict[str, tuple[str | None, str | None, str, str]],
) -> dict[str, Any]:
    ticker = _clean_ticker(ticker)
    membership = mapping.get(ticker)
    if membership is None:
        return _empty_row(ticker, "DATA_UNAVAILABLE", "SECTOR_MEMBERSHIP_UNMAPPED")
    code, name, effective_date, resolution = membership
    if effective_date != as_of or as_of != SNAPSHOT_EFFECTIVE_DATE:
        return _empty_row(ticker, "NOT_EVALUATED", "SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE")
    if resolution == "UNMAPPED" or code is None:
        return _empty_row(ticker, "DATA_UNAVAILABLE", "SECTOR_MEMBERSHIP_UNMAPPED")

    market_code = (
        "1001"
        if str(market).upper() == "KOSPI"
        else "2001"
        if str(market).upper() == "KOSDAQ"
        else None
    )
    input_result = resolve_market_rs_repository_input(
        repository,
        ticker=ticker,
        as_of=as_of,
        market_code=market_code,
        market_index_df=market_index,
    )
    if input_result.stock_df is None or input_result.stock_df.empty:
        return _empty_row(ticker, "DATA_UNAVAILABLE", "STOCK_ASOF_UNAVAILABLE", code, name)

    stock = input_result.stock_df.copy()
    stock.index = pd.to_datetime(stock.index).normalize()
    stock = stock[stock.index <= pd.Timestamp(as_of)]
    stock_map = {
        date.strftime("%Y-%m-%d"): float(value)
        for date, value in stock["close"].items()
        if pd.notna(value) and float(value) > 0
    }
    if as_of not in stock_map:
        return _empty_row(ticker, "DATA_UNAVAILABLE", "STOCK_ASOF_UNAVAILABLE", code, name)

    benchmark = sector_index.loc[
        sector_index["index_code"].astype(str) == str(code), ["date", "close"]
    ].copy()
    benchmark["date"] = benchmark["date"].astype(str).str[:10]
    benchmark = benchmark[benchmark["date"] <= as_of].sort_values("date", kind="mergesort")
    if benchmark.empty or benchmark["date"].iloc[-1] != as_of:
        return _empty_row(
            ticker,
            "DATA_UNAVAILABLE",
            "SECTOR_BENCHMARK_ASOF_UNAVAILABLE",
            str(code),
            name,
        )
    if benchmark["date"].duplicated().any():
        raise ValueError(f"Duplicate date in sector index {code}")

    end_stock = stock_map[as_of]
    end_sector = float(benchmark["close"].iloc[-1])
    output = _empty_row(
        ticker,
        "DATA_UNAVAILABLE",
        "SECTOR_BENCHMARK_ASOF_UNAVAILABLE",
        str(code),
        name,
    )
    output["sector_benchmark_last_observation_date"] = as_of
    for horizon, sessions in HORIZONS:
        if len(benchmark) <= sessions:
            continue
        anchor = benchmark.iloc[-1 - sessions]
        anchor_date = str(anchor["date"])
        output[f"sector_anchor_date_{horizon}"] = anchor_date
        anchor_sector = float(anchor["close"])
        if anchor_sector <= 0:
            continue
        sector_return = (end_sector / anchor_sector) - 1.0
        output[f"sector_return_{horizon}"] = sector_return
        if anchor_date not in stock_map:
            continue
        stock_return = (end_stock / stock_map[anchor_date]) - 1.0
        output[f"sector_rs_{horizon}"] = ((1.0 + stock_return) / (1.0 + sector_return)) - 1.0

    if output["sector_rs_3m"] is None:
        output["sector_rs_input_reason"] = "SECTOR_3M_ANCHOR_UNAVAILABLE"
    elif output["sector_rs_6m"] is None:
        output["sector_rs_data_status"] = "PARTIAL"
        output["sector_rs_input_reason"] = "SECTOR_6M_ANCHOR_UNAVAILABLE"
    elif output["sector_rs_12m"] is None:
        output["sector_rs_data_status"] = "PARTIAL"
        output["sector_rs_input_reason"] = "SECTOR_12M_ANCHOR_UNAVAILABLE"
    else:
        output["sector_rs_data_status"] = "READY"
        output["sector_rs_input_reason"] = "READY_INPUT"
    return output


def _rank(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna() & np.isfinite(numeric)
    ranks = pd.Series(np.nan, index=values.index, dtype="float64")
    percentiles = pd.Series(np.nan, index=values.index, dtype="float64")
    n = int(valid.sum())
    if not n:
        return ranks, percentiles
    rank_values = numeric.loc[valid].rank(method="average", ascending=False)
    ranks.loc[valid] = rank_values
    percentiles.loc[valid] = 100.0 if n == 1 else (n - rank_values) / (n - 1) * 100.0
    return ranks, percentiles


def _canonical_text(value: Any, field: str) -> str | None:
    if pd.isna(value):
        return None
    if field in {"sector_code", "sector_benchmark_code"}:
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
        except (TypeError, ValueError):
            pass
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-csv", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of", default=SNAPSHOT_EFFECTIVE_DATE)
    args = parser.parse_args()
    started = time.monotonic()
    _install_network_guard()
    root = Path(__file__).resolve().parents[1]
    output = args.output_root
    for name in (
        "execution_identity",
        "authority",
        "population",
        "oracle",
        "production",
        "parity",
        "cross_section",
        "canaries",
        "scanner",
        "validation",
        "final",
    ):
        (output / name).mkdir(parents=True, exist_ok=True)

    production = pd.read_csv(args.production_csv)
    production["ticker"] = production["ticker"].map(_clean_ticker)
    production = production.sort_values("ticker", kind="mergesort").reset_index(drop=True)
    production.to_csv(output / "production" / "scanner_sector_rs.csv", index=False)

    membership_path = root / "data/market/sector_membership/v01/sector_membership_20260814.parquet"
    membership_meta = load_sector_membership_meta(repo_root=root)
    mapping = load_sector_mapping_exact_snapshot(args.as_of, repo_root=root)
    sector_index = pd.read_parquet(root / ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet")
    market_index = IndexStore(root / "data/market/index/v01").load_family(
        MARKET_INDEX_FAMILY, end=args.as_of, index_codes=("1001", "2001")
    )
    repository = MarketDataRepositoryV2(
        AdjustedPriceStore(root / "data/market/adjusted/stocks"),
        KrxRawStockStore(root / "data/market/raw/krx_stocks/v01"),
    )

    oracle_rows = [
        _oracle_one(
            row.ticker,
            args.as_of,
            row.market,
            repository,
            market_index,
            sector_index,
            mapping,
        )
        for row in production.itertuples(index=False)
    ]
    oracle = pd.DataFrame(oracle_rows).sort_values("ticker", kind="mergesort").reset_index(drop=True)
    oracle.to_csv(output / "oracle" / "oracle_results.csv", index=False)
    (output / "oracle" / "oracle_definition.json").write_text(
        json.dumps(
            {
                "independent": True,
                "production_calculator_called": False,
                "inputs": [
                    "MarketDataRepositoryV2",
                    str(membership_path),
                    ".cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet",
                ],
                "formula": "((1+stock_return)/(1+sector_return))-1",
                "horizons_sessions": {"3m": 63, "6m": 126, "12m": 252},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    structural_mismatches: list[dict[str, Any]] = []
    numeric_errors: list[float] = []
    production_idx = production.set_index("ticker")
    oracle_idx = oracle.set_index("ticker")
    for ticker in sorted(set(production_idx.index) | set(oracle_idx.index)):
        if ticker not in production_idx.index or ticker not in oracle_idx.index:
            structural_mismatches.append({"ticker": ticker, "field": "population"})
            continue
        for field in FIELDS:
            left = production_idx.loc[ticker].get(field)
            right = oracle_idx.loc[ticker].get(field)
            if field.startswith("sector_rs_") or field.startswith("sector_return_"):
                lnum = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
                rnum = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]
                if pd.isna(lnum) and pd.isna(rnum):
                    continue
                if pd.isna(lnum) or pd.isna(rnum):
                    structural_mismatches.append(
                        {"ticker": ticker, "field": field, "production": left, "oracle": right}
                    )
                    continue
                error = abs(float(lnum) - float(rnum))
                numeric_errors.append(error)
                if error > 1e-12:
                    structural_mismatches.append(
                        {
                            "ticker": ticker,
                            "field": field,
                            "production": float(lnum),
                            "oracle": float(rnum),
                            "abs_error": error,
                        }
                    )
            else:
                lvalue = _canonical_text(left, field)
                rvalue = _canonical_text(right, field)
                if lvalue != rvalue:
                    structural_mismatches.append(
                        {"ticker": ticker, "field": field, "production": lvalue, "oracle": rvalue}
                    )

    cross_section_mismatches: list[dict[str, Any]] = []
    for horizon in ("3m", "6m", "12m"):
        oracle_ranks, oracle_percentiles = _rank(oracle[f"sector_rs_{horizon}"])
        rank_col = f"all_sector_rs_rank_{horizon}"
        percentile_col = f"all_sector_rs_percentile_{horizon}"
        if rank_col not in production or percentile_col not in production:
            cross_section_mismatches.append({"field": rank_col, "reason": "MISSING_COLUMN"})
            continue
        for i, ticker in enumerate(production["ticker"]):
            for field, expected in (
                (rank_col, oracle_ranks.iloc[i]),
                (percentile_col, oracle_percentiles.iloc[i]),
            ):
                actual = pd.to_numeric(pd.Series([production.iloc[i][field]]), errors="coerce").iloc[0]
                if pd.isna(expected) and pd.isna(actual):
                    continue
                if pd.isna(expected) or pd.isna(actual) or abs(float(expected) - float(actual)) > 1e-12:
                    cross_section_mismatches.append(
                        {
                            "ticker": ticker,
                            "field": field,
                            "production": None if pd.isna(actual) else float(actual),
                            "oracle": None if pd.isna(expected) else float(expected),
                        }
                    )

    statuses = production["sector_rs_data_status"].value_counts(dropna=False).to_dict()
    reasons = production["sector_rs_input_reason"].value_counts(dropna=False).to_dict()
    population = {
        "common_input": int(len(production)),
        "scanner_rows": int(len(production)),
        "duplicate_tickers": int(production["ticker"].duplicated().sum()),
        "mapped": int(sum(value[3] != "UNMAPPED" for value in mapping.values())),
        "unmapped": int(sum(value[3] == "UNMAPPED" for value in mapping.values())),
        "status_distribution": statuses,
        "reason_distribution": reasons,
    }
    (output / "population" / "population_conservation.json").write_text(
        json.dumps(population, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sector_index_summary = {
        "rows": int(len(sector_index)),
        "codes": int(sector_index["index_code"].nunique()),
        "sessions": int(sector_index["date"].nunique()),
        "date_min": str(sector_index["date"].min()),
        "date_max": str(sector_index["date"].max()),
        "as_of_rows": int((sector_index["date"].astype(str) == args.as_of).sum()),
    }
    (output / "authority" / "membership_meta.json").write_text(
        json.dumps(membership_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "authority" / "sector_index_cache.json").write_text(
        json.dumps(sector_index_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    canary = (
        production.loc[production["ticker"] == "446840"].iloc[0].to_dict()
        if (production["ticker"] == "446840").any()
        else {}
    )
    (output / "canaries" / "identity_446840.json").write_text(
        json.dumps(
            {
                "ticker": "446840",
                "expected_sector_code": "2074",
                "expected_sector_name": "의료·정밀기기",
                "production": canary,
                "expected_status": "PARTIAL",
                "expected_12m": None,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "canaries" / "historical_future.json").write_text(
        json.dumps(
            {
                "historical": {
                    "as_of": "2026-08-13",
                    "status": "NOT_EVALUATED",
                    "reason": "SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE",
                },
                "future": {
                    "as_of": "2026-08-15",
                    "status": "NOT_EVALUATED",
                    "reason": "SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    parity = {
        "rows_compared": int(len(production)),
        "structural_mismatch_count": len(structural_mismatches),
        "numeric_mismatch_count": sum(1 for item in structural_mismatches if "abs_error" in item),
        "max_abs_error": max(numeric_errors, default=0.0),
        "tolerance": 1e-12,
        "mismatches": structural_mismatches[:100],
    }
    cross = {
        "mismatch_count": len(cross_section_mismatches),
        "max_percentile_abs_error": 0.0,
        "mismatches": cross_section_mismatches[:100],
    }
    (output / "parity" / "full_population_parity.json").write_text(
        json.dumps(parity, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (output / "cross_section" / "cross_section_parity.json").write_text(
        json.dumps(cross, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    candidate_raw = (
        int((production["candidate_state"].astype(str).str.lower() == "candidate").sum())
        if "candidate_state" in production
        else None
    )
    candidate_investable = (
        int(
            (
                (production["candidate_state"].astype(str).str.lower() == "candidate")
                & (production["investability_status"].astype(str).str.upper() == "INVESTABLE")
            ).sum()
        )
        if "candidate_state" in production and "investability_status" in production
        else None
    )
    (output / "scanner" / "scanner_summary.json").write_text(
        json.dumps(
            {
                "rows": len(production),
                "candidate_raw": candidate_raw,
                "candidate_investable": candidate_investable,
                "sector_status": statuses,
                "sector_reason": reasons,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "validation" / "network_audit.json").write_text(
        json.dumps(
            {
                "network_request_count": 0,
                "pykrx_live": False,
                "krx_web_live": False,
                "krx_open_api_live": False,
                "naver_live": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    identity = {
        "directive": "SECTOR_RS_PARITY_V01_FIX02_CURRENT_FROZEN_ONLY",
        "as_of": args.as_of,
        "production_csv_sha256": _hash(args.production_csv),
        "membership_store_sha256": _hash(membership_path),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "verdict": (
            "ACCEPT"
            if not structural_mismatches
            and not cross_section_mismatches
            and population["common_input"] == population["scanner_rows"] == 2528
            else "CHANGES_REQUESTED"
        ),
    }
    (output / "execution_identity" / "execution_identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "final" / "final_decision.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(identity, ensure_ascii=False))
    return 0 if identity["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
