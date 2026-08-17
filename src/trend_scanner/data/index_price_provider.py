"""KRX Market and Sector Index Data Provider and Source Cache Management.

Point In Time(PIT) 원칙을 준수하며 KOSPI(1001), KOSDAQ(2001) 대표 시장 지수 및
주요 업종별 지수 OHLCV 시계열 데이터를 수집하고 로컬 Parquet/CSV로 캐싱한다.
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

_STANDARD_INDEX_COLUMNS = (
    "date",
    "index_code",
    "index_name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
)

MARKET_INDEX_KOSPI = "1001"
MARKET_INDEX_KOSDAQ = "2001"

KOSPI_SECTOR_CODES = (
    "1005", "1006", "1007", "1008", "1009", "1010", "1011", "1012", "1013", "1014",
    "1015", "1016", "1017", "1018", "1019", "1020", "1021", "1024", "1025", "1026",
    "1027", "1045", "1046", "1047",
)

KOSDAQ_SECTOR_CODES = (
    "2012", "2024", "2026", "2027", "2029", "2031", "2037", "2056", "2058", "2062",
    "2063", "2065", "2066", "2067", "2068", "2070", "2072", "2074", "2075", "2077",
    "2114", "2118",
)


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


class IndexPriceDataProvider:
    """KRX 원천 기반 시장 및 업종 지수 데이터 제공자."""

    def __init__(
        self,
        market_index_cache_file: Path | str | None = None,
        sector_index_cache_file: Path | str | None = None,
        sector_mapping_cache_file: Path | str | None = None,
    ):
        self.market_index_cache_file = Path(market_index_cache_file) if market_index_cache_file else None
        self.sector_index_cache_file = Path(sector_index_cache_file) if sector_index_cache_file else None
        self.sector_mapping_cache_file = Path(sector_mapping_cache_file) if sector_mapping_cache_file else None

        self._cached_market_df: pd.DataFrame | None = None
        self._cached_sector_df: pd.DataFrame | None = None
        self._cached_sector_mapping_raw_df: pd.DataFrame | None = None

    def fetch_index_series(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
        max_retries: int = 3,
        delay_sec: float = 0.3,
    ) -> pd.DataFrame:
        """단일 인덱스의 OHLCV 시계열 데이터를 수집한다 (재시도 및 Rate Limit 지연 포함)."""
        import time

        clean_start = start_date.replace("-", "")
        clean_end = end_date.replace("-", "")
        raw_df = pd.DataFrame()
        name = ""

        for attempt in range(1, max_retries + 1):
            try:
                if delay_sec > 0:
                    time.sleep(delay_sec)
                name = stock.get_index_ticker_name(index_code)
                raw_df = stock.get_index_ohlcv_by_date(clean_start, clean_end, index_code)
                if not raw_df.empty:
                    break
            except Exception as exc:
                if attempt == max_retries:
                    raise MarketDataError(
                        f"지수 시계열 수집 실패 (index_code={index_code}, start={clean_start}, end={clean_end}): {exc}"
                    ) from exc
                time.sleep(1.0 * attempt)

        if raw_df.empty:
            return pd.DataFrame(columns=list(_STANDARD_INDEX_COLUMNS))

        rows = []
        for dt, row in raw_df.iterrows():
            dt_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
            try:
                op = float(row["시가"])
                hi = float(row["고가"])
                lo = float(row["저가"])
                cl = float(row["종가"])
                vol = int(row.get("거래량", 0)) if "거래량" in row and not pd.isna(row["거래량"]) else 0
                tv = float(row.get("거래대금", 0.0)) if "거래대금" in row and not pd.isna(row["거래대금"]) else 0.0
            except (ValueError, TypeError) as exc:
                raise MarketDataError(
                    f"지수 데이터 Numeric Coercion 실패 (index_code={index_code}, date={dt_str}): {exc}"
                ) from exc

            rows.append({
                "date": dt_str,
                "index_code": str(index_code),
                "index_name": name,
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": vol,
                "trading_value": tv,
            })

        df = pd.DataFrame(rows)
        if df.duplicated(subset=["date", "index_code"]).any():
            raise MarketDataError(f"Duplicate date/index_code detected for index {index_code}")
        return df

    def build_market_index_cache(
        self,
        start_date: str,
        end_date: str,
        output_parquet: Path,
        output_meta: Path,
    ) -> pd.DataFrame:
        """KOSPI(1001) 및 KOSDAQ(2001) 시장 대표 지수를 수집하고 Parquet/Meta로 저장한다."""
        dfs = []
        for code in (MARKET_INDEX_KOSPI, MARKET_INDEX_KOSDAQ):
            df_idx = self.fetch_index_series(code, start_date, end_date)
            if not df_idx.empty:
                dfs.append(df_idx)

        if not dfs:
            combined = pd.DataFrame(columns=list(_STANDARD_INDEX_COLUMNS))
        else:
            combined = pd.concat(dfs, ignore_index=True)

        combined["date"] = combined["date"].astype(str)
        combined["index_code"] = combined["index_code"].astype(str)
        combined["index_name"] = combined["index_name"].astype(str)
        for col in ("open", "high", "low", "close", "trading_value"):
            combined[col] = combined[col].astype("float64")
        combined["volume"] = combined["volume"].astype("int64")

        combined = combined.sort_values(by=["index_code", "date"]).reset_index(drop=True)

        if combined.duplicated(subset=["date", "index_code"]).any():
            raise MarketDataError("Duplicate (date, index_code) found in market index dataset")

        output_parquet.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(output_parquet, index=False)

        sha256 = compute_file_sha256(output_parquet)
        meta = {
            "source_name": "KRX_PYKRX_MARKET_INDEX",
            "requested_as_of": end_date,
            "date_min": str(combined["date"].min()) if not combined.empty else "",
            "date_max": str(combined["date"].max()) if not combined.empty else "",
            "index_codes": [MARKET_INDEX_KOSPI, MARKET_INDEX_KOSDAQ],
            "index_names": ["코스피", "코스닥"],
            "row_count": len(combined),
            "parquet_sha256": sha256,
            "fetch_mode": "BATCH_PYKRX",
            "generation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        output_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return combined

    def build_sector_index_cache(
        self,
        sector_codes: list[str],
        start_date: str,
        end_date: str,
        output_parquet: Path,
        output_meta: Path,
    ) -> pd.DataFrame:
        """지정된 업종 지수들의 시계열을 수집하고 Parquet/Meta로 저장한다."""
        dfs = []
        unique_codes = sorted(list(set(sector_codes)))
        for code in unique_codes:
            df_idx = self.fetch_index_series(code, start_date, end_date)
            if not df_idx.empty:
                dfs.append(df_idx)

        if not dfs:
            combined = pd.DataFrame(columns=list(_STANDARD_INDEX_COLUMNS))
        else:
            combined = pd.concat(dfs, ignore_index=True)

        combined["date"] = combined["date"].astype(str)
        combined["index_code"] = combined["index_code"].astype(str)
        combined["index_name"] = combined["index_name"].astype(str)
        for col in ("open", "high", "low", "close", "trading_value"):
            combined[col] = combined[col].astype("float64")
        combined["volume"] = combined["volume"].astype("int64")

        combined = combined.sort_values(by=["index_code", "date"]).reset_index(drop=True)

        if combined.duplicated(subset=["date", "index_code"]).any():
            raise MarketDataError("Duplicate (date, index_code) found in sector index dataset")

        output_parquet.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(output_parquet, index=False)

        sha256 = compute_file_sha256(output_parquet)
        meta = {
            "source_name": "KRX_PYKRX_SECTOR_INDEX",
            "requested_as_of": end_date,
            "date_min": str(combined["date"].min()) if not combined.empty else "",
            "date_max": str(combined["date"].max()) if not combined.empty else "",
            "index_codes": unique_codes,
            "row_count": len(combined),
            "parquet_sha256": sha256,
            "fetch_mode": "BATCH_PYKRX",
            "generation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        output_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return combined

    def build_sector_mapping(
        self,
        as_of: str,
        output_csv: Path,
        output_meta: Path,
        delay_sec: float = 0.3,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """KOSPI 및 KOSDAQ 업종 지수 구성 종목(PDF)을 취합하여 Ticker별 Sector 매핑을 생성한다."""
        import time

        clean_date = as_of.replace("-", "")
        formatted_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
        all_sector_codes = list(KOSPI_SECTOR_CODES) + list(KOSDAQ_SECTOR_CODES)

        rows = []
        seen_tickers: set[str] = set()
        for code in all_sector_codes:
            tickers = []
            name = ""
            for attempt in range(1, max_retries + 1):
                try:
                    if delay_sec > 0:
                        time.sleep(delay_sec)
                    name = stock.get_index_ticker_name(code)
                    tickers = stock.get_index_portfolio_deposit_file(code, clean_date)
                    if len(tickers) > 0:
                        break
                except Exception as exc:
                    if attempt == max_retries:
                        raise MarketDataError(
                            f"업종 구성종목(PDF) 수집 실패 (code={code}, as_of={clean_date}): {exc}"
                        ) from exc
                    time.sleep(1.0 * attempt)

            for t in tickers:
                t_str = str(t).zfill(6)
                if t_str not in seen_tickers:
                    seen_tickers.add(t_str)
                    market = "KOSPI" if code in KOSPI_SECTOR_CODES else "KOSDAQ"
                    rows.append({
                        "ticker": t_str,
                        "market": market,
                        "sector_code": str(code),
                        "sector_name": name,
                        "effective_date": formatted_date,
                    })

        df = pd.DataFrame(rows)
        df = df.sort_values(by=["market", "ticker"]).reset_index(drop=True)

        if df.duplicated(subset=["ticker", "effective_date"]).any():
            raise MarketDataError("Duplicate (ticker, effective_date) detected in sector mapping")

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_csv, index=False, encoding="utf-8")

        sha256 = compute_file_sha256(output_csv)
        meta = {
            "source_name": "KRX_PYKRX_SECTOR_MAPPING",
            "effective_date": formatted_date,
            "ticker_count": len(df),
            "sector_count": df["sector_code"].nunique(),
            "csv_sha256": sha256,
            "generation_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        output_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return df

    def load_market_index_history(self, as_of: str | None = None) -> pd.DataFrame:
        """캐시된 시장 대표 지수를 로드하고 as_of 이하만 필터링한다."""
        if self._cached_market_df is None:
            if self.market_index_cache_file is None or not self.market_index_cache_file.exists():
                return pd.DataFrame(columns=list(_STANDARD_INDEX_COLUMNS))
            self._cached_market_df = pd.read_parquet(self.market_index_cache_file)

        df = self._cached_market_df
        if as_of:
            clean_asof = as_of.replace("-", "")
            formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"
            df = df[df["date"] <= formatted_asof].copy()
        return df

    def load_sector_index_history(self, as_of: str | None = None) -> pd.DataFrame:
        """캐시된 업종 지수를 로드하고 as_of 이하만 필터링한다."""
        if self._cached_sector_df is None:
            if self.sector_index_cache_file is None or not self.sector_index_cache_file.exists():
                return pd.DataFrame(columns=list(_STANDARD_INDEX_COLUMNS))
            self._cached_sector_df = pd.read_parquet(self.sector_index_cache_file)

        df = self._cached_sector_df
        if as_of:
            clean_asof = as_of.replace("-", "")
            formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"
            df = df[df["date"] <= formatted_asof].copy()
        return df

    def load_sector_mapping(self, as_of: str | None = None) -> dict[str, tuple[str, str, str]]:
        """Ticker -> (sector_code, sector_name, effective_date) 딕셔너리를 반환한다.

        Raw DataFrame을 캐시하고 매 호출마다 effective_date <= requested_as_of를 재적용하여
        Cross-as_of 캐시 누출을 원천 방지한다.
        """
        if self._cached_sector_mapping_raw_df is None:
            if self.sector_mapping_cache_file is None or not self.sector_mapping_cache_file.exists():
                return {}
            df = pd.read_csv(self.sector_mapping_cache_file)
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
            self._cached_sector_mapping_raw_df = df

        df = self._cached_sector_mapping_raw_df
        if "effective_date" not in df.columns:
            return {}

        if as_of:
            clean_asof = as_of.replace("-", "")
            formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"
            df = df[df["effective_date"].astype(str) <= formatted_asof]

        return {
            row["ticker"]: (str(row["sector_code"]), str(row["sector_name"]), str(row["effective_date"]))
            for _, row in df.iterrows()
        }
