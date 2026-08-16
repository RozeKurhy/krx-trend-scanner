"""2026-08-14 기준 65거래일 외국인 수급 원천 데이터를 일괄 수집하여 캐싱한다."""

import json
from pathlib import Path
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.foreign_flow_provider import (
    ForeignFlowDataProvider,
    compute_file_sha256,
)

def main():
    repo_root = Path(__file__).resolve().parent.parent
    cache_dir = repo_root / "data/raw/stocks"
    parquet_cache = ParquetCache(base_dir=cache_dir)

    # 005930(삼성전자) 일봉에서 2026-08-14 이전 65거래일 날짜 추출
    df_samsung = parquet_cache.load("005930")
    if df_samsung is None:
        raise ValueError("005930 cache not found")

    df_asof = df_samsung[df_samsung.index <= "2026-08-14"]
    trading_dates = df_asof.index[-65:].strftime("%Y%m%d").tolist()

    print(f"Trading dates count: {len(trading_dates)} ({trading_dates[0]} ~ {trading_dates[-1]})")

    out_dir = repo_root / "artifacts/flow/source"
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_out = out_dir / "foreign_flow_daily_20260814.parquet"
    csv_out = out_dir / "foreign_flow_daily_20260814.csv"
    meta_out = out_dir / "foreign_flow_daily_20260814_meta.json"

    provider = ForeignFlowDataProvider()
    df_flow = provider.build_historical_cache(trading_dates, parquet_out)

    # CSV도 함께 저장 (Inspection 및 human review용)
    df_flow.to_csv(csv_out, index=False)

    sha256_parquet = compute_file_sha256(parquet_out)
    sha256_csv = compute_file_sha256(csv_out)

    meta = {
        "source_name": "KRX_PYKRX_FOREIGN_FLOW",
        "requested_as_of": "2026-08-14",
        "date_min": str(df_flow["date"].min()),
        "date_max": str(df_flow["date"].max()),
        "trading_dates_count": len(trading_dates),
        "row_count": len(df_flow),
        "ticker_count": int(df_flow["ticker"].nunique()),
        "parquet_file": str(parquet_out.relative_to(repo_root)),
        "parquet_sha256": sha256_parquet,
        "csv_file": str(csv_out.relative_to(repo_root)),
        "csv_sha256": sha256_csv,
    }

    meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Metadata saved to {meta_out}:")
    print(json.dumps(meta, indent=2))

if __name__ == "__main__":
    main()
