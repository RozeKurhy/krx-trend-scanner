"""외국인 수급(Foreign Investor Flow) 데이터 Provider 및 캐시 관리.

Point In Time(PIT) 원칙을 준수하며 일자별 전체 시장(Universe) Batch Fetch를 통해
외국인 순매수(signed KRW), 매수대금, 매도대금을 수집하고 로컬 Parquet/CSV로 캐싱한다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from pykrx import stock  # noqa: E402

from trend_scanner.data.errors import MarketDataError

_STANDARD_FLOW_COLUMNS = (
    "date",
    "ticker",
    "foreign_net_buy_value",
    "foreign_buy_value",
    "foreign_sell_value",
)


class ForeignFlowDataProvider:
    """KRX 원천 기반 외국인 수급 데이터 수집기."""

    def __init__(self, cache_file: Path | str | None = None):
        self.cache_file = Path(cache_file) if cache_file else None
        self._cached_df: pd.DataFrame | None = None

    def fetch_date_batch(self, date_str: str) -> pd.DataFrame:
        """단일 거래일 전체 종목 외국인 수급 데이터를 Batch Fetch한다.

        Args:
            date_str: 'YYYYMMDD' 또는 'YYYY-MM-DD' 형식의 날짜 문자열.

        Returns:
            DataFrame with columns: ['date', 'ticker', 'foreign_net_buy_value', 'foreign_buy_value', 'foreign_sell_value']
        """
        clean_date = date_str.replace("-", "")
        formatted_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
        try:
            raw_df = stock.get_market_net_purchases_of_equities_by_ticker(
                clean_date, clean_date, "ALL", "외국인"
            )
        except Exception as exc:
            raise MarketDataError(
                f"외국인 수급 Batch Fetch 실패 (date={clean_date}): {exc}"
            ) from exc

        if raw_df.empty:
            return pd.DataFrame(columns=list(_STANDARD_FLOW_COLUMNS))

        rows = []
        for ticker, row in raw_df.iterrows():
            ticker_str = str(ticker).zfill(6)
            buy_val = float(row.get("매수거래대금", 0.0))
            sell_val = float(row.get("매도거래대금", 0.0))
            net_buy_val = float(row.get("순매수거래대금", buy_val - sell_val))

            rows.append({
                "date": formatted_date,
                "ticker": ticker_str,
                "foreign_net_buy_value": net_buy_val,
                "foreign_buy_value": buy_val,
                "foreign_sell_value": sell_val,
            })

        df = pd.DataFrame(rows)
        # Verify duplicate prevention contract
        if df.duplicated(subset=["date", "ticker"]).any():
            raise MarketDataError(f"Duplicate ticker/date detected on {formatted_date}")
        return df

    def build_historical_cache(
        self,
        trading_dates: list[str],
        output_path: Path,
    ) -> pd.DataFrame:
        """지정된 거래일 리스트 전체에 대해 외국인 수급 데이터를 수집하고 Parquet로 저장한다."""
        all_dfs = []
        print(f"Fetching foreign flow for {len(trading_dates)} trading dates...")
        for i, dt in enumerate(trading_dates, 1):
            df_date = self.fetch_date_batch(dt)
            if not df_date.empty:
                all_dfs.append(df_date)
            if i % 10 == 0 or i == len(trading_dates):
                print(f"  [{i}/{len(trading_dates)}] Fetched {dt} ({len(df_date)} rows)")

        if not all_dfs:
            combined = pd.DataFrame(columns=list(_STANDARD_FLOW_COLUMNS))
        else:
            combined = pd.concat(all_dfs, ignore_index=True)

        combined["date"] = combined["date"].astype(str)
        combined["ticker"] = combined["ticker"].astype(str).str.zfill(6)
        combined["foreign_net_buy_value"] = combined["foreign_net_buy_value"].astype("float64")
        combined["foreign_buy_value"] = combined["foreign_buy_value"].astype("float64")
        combined["foreign_sell_value"] = combined["foreign_sell_value"].astype("float64")

        combined = combined.sort_values(by=["date", "ticker"]).reset_index(drop=True)

        # Ensure no duplicates
        if combined.duplicated(subset=["date", "ticker"]).any():
            raise MarketDataError("Duplicate (date, ticker) found in combined foreign flow data")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(output_path, index=False)
        print(f"Saved {len(combined)} rows of foreign flow to {output_path}")
        return combined

    def load_flow_history(self, as_of: str | None = None) -> pd.DataFrame:
        """캐시된 외국인 수급 데이터를 로드하고 as_of 이하만 필터링한다."""
        if self._cached_df is None:
            if self.cache_file is None or not self.cache_file.exists():
                return pd.DataFrame(columns=list(_STANDARD_FLOW_COLUMNS))
            self._cached_df = pd.read_parquet(self.cache_file)

        df = self._cached_df
        if as_of:
            clean_asof = as_of.replace("-", "")
            formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"
            df = df[df["date"] <= formatted_asof].copy()
        return df


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
