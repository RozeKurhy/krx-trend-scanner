"""상대강도(Relative Strength) 확증 피처 계산 엔진.

Point In Time(PIT) 원칙과 벤치마크 거래일 기준 Window(3M=63D, 6M=126D, 12M=252D)를 준수하여
대표 시장 지수(KOSPI 1001, KOSDAQ 2001) 및 업종 지수 대비 상대강도(Relative Price Ratio - 1) 피처를 계산한다.

[핵심 정의]:
1. Relative Strength는 RSI(Relative Strength Index)가 아니며,
   Stock Price Performance vs Benchmark Price Performance의 상대 가격 성과이다.
2. Canonical Formula:
   - stock_return_H = (stock_close_end / stock_close_anchor) - 1.0
   - benchmark_return_H = (benchmark_close_end / benchmark_close_anchor) - 1.0
   - relative_price_ratio_H = (1.0 + stock_return_H) / (1.0 + benchmark_return_H)
   - rs_H = relative_price_ratio_H - 1.0
3. Fail-Closed 원칙:
   - Stock exact as_of 관측값 누락 시 DATA_UNAVAILABLE.
   - Benchmark exact as_of 관측값 누락 시 DATA_UNAVAILABLE.
   - Anchor 시점 누락 시 해당 Horizon은 None (침묵의 forward/backward fill 금지).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.models import MarketType


class RelativeStrengthDataStatus(str, Enum):
    """상대강도 데이터 준비 상태."""

    READY = "READY"                      # 3M, 6M, 12M 전체 horizon 정상 산출
    PARTIAL = "PARTIAL"                  # 3M은 산출 가능하나 6M 또는 12M observation 부족
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"  # 기준일 가격 부재, 벤치마크 누락 등으로 3M 산출 불가
    NOT_EVALUATED = "NOT_EVALUATED"        # 스캐너에서 미평가된 비후보군 종목 상태


HORIZON_SESSIONS_3M = 63
HORIZON_SESSIONS_6M = 126
HORIZON_SESSIONS_12M = 252


@dataclass(frozen=True)
class RelativeStrengthFeatureResult:
    """단일 종목의 상대강도(Relative Strength) 피처 계산 결과."""

    ticker: str
    as_of: str

    # 1. Market Relative Strength (Primary Axis)
    market_rs_data_status: RelativeStrengthDataStatus
    market_benchmark_name: str | None
    market_benchmark_code: str | None
    market_benchmark_last_observation_date: str | None

    # Stock Absolute Returns
    stock_return_3m: float | None
    stock_return_6m: float | None
    stock_return_12m: float | None

    # Market Benchmark Returns
    market_return_3m: float | None
    market_return_6m: float | None
    market_return_12m: float | None

    # Market Relative Strength (Relative Price Ratio - 1)
    market_rs_3m: float | None
    market_rs_6m: float | None
    market_rs_12m: float | None

    # Anchor Dates
    market_anchor_date_3m: str | None
    market_anchor_date_6m: str | None
    market_anchor_date_12m: str | None

    # 2. Sector Relative Strength (Secondary Axis)
    sector_rs_data_status: RelativeStrengthDataStatus
    sector_name: str | None
    sector_code: str | None
    sector_benchmark_code: str | None
    sector_benchmark_last_observation_date: str | None

    # Sector Benchmark Returns
    sector_return_3m: float | None
    sector_return_6m: float | None
    sector_return_12m: float | None

    # Sector Relative Strength
    sector_rs_3m: float | None
    sector_rs_6m: float | None
    sector_rs_12m: float | None

    # Sector Anchor Dates
    sector_anchor_date_3m: str | None
    sector_anchor_date_6m: str | None
    sector_anchor_date_12m: str | None

    def to_dict(self) -> dict[str, Any]:
        """Dictionary 변환 (JSON / DataFrame 직렬화용)."""
        return {
            "ticker": self.ticker,
            "as_of": self.as_of,
            "market_rs_data_status": self.market_rs_data_status.value,
            "market_benchmark_name": self.market_benchmark_name,
            "market_benchmark_code": self.market_benchmark_code,
            "market_benchmark_last_observation_date": self.market_benchmark_last_observation_date,
            "stock_return_3m": self.stock_return_3m,
            "stock_return_6m": self.stock_return_6m,
            "stock_return_12m": self.stock_return_12m,
            "market_return_3m": self.market_return_3m,
            "market_return_6m": self.market_return_6m,
            "market_return_12m": self.market_return_12m,
            "market_rs_3m": self.market_rs_3m,
            "market_rs_6m": self.market_rs_6m,
            "market_rs_12m": self.market_rs_12m,
            "market_anchor_date_3m": self.market_anchor_date_3m,
            "market_anchor_date_6m": self.market_anchor_date_6m,
            "market_anchor_date_12m": self.market_anchor_date_12m,
            "sector_rs_data_status": self.sector_rs_data_status.value,
            "sector_name": self.sector_name,
            "sector_code": self.sector_code,
            "sector_benchmark_code": self.sector_benchmark_code,
            "sector_benchmark_last_observation_date": self.sector_benchmark_last_observation_date,
            "sector_return_3m": self.sector_return_3m,
            "sector_return_6m": self.sector_return_6m,
            "sector_return_12m": self.sector_return_12m,
            "sector_rs_3m": self.sector_rs_3m,
            "sector_rs_6m": self.sector_rs_6m,
            "sector_rs_12m": self.sector_rs_12m,
            "sector_anchor_date_3m": self.sector_anchor_date_3m,
            "sector_anchor_date_6m": self.sector_anchor_date_6m,
            "sector_anchor_date_12m": self.sector_anchor_date_12m,
        }


def _unavailable_rs_result(
    ticker: str,
    as_of: str,
    market_benchmark_name: str | None = None,
    market_benchmark_code: str | None = None,
    sector_name: str | None = None,
    sector_code: str | None = None,
) -> RelativeStrengthFeatureResult:
    """데이터 부재 시 반환하는 기본 불능 결과."""
    return RelativeStrengthFeatureResult(
        ticker=ticker,
        as_of=as_of,
        market_rs_data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE,
        market_benchmark_name=market_benchmark_name,
        market_benchmark_code=market_benchmark_code,
        market_benchmark_last_observation_date=None,
        stock_return_3m=None,
        stock_return_6m=None,
        stock_return_12m=None,
        market_return_3m=None,
        market_return_6m=None,
        market_return_12m=None,
        market_rs_3m=None,
        market_rs_6m=None,
        market_rs_12m=None,
        market_anchor_date_3m=None,
        market_anchor_date_6m=None,
        market_anchor_date_12m=None,
        sector_rs_data_status=RelativeStrengthDataStatus.DATA_UNAVAILABLE,
        sector_name=sector_name,
        sector_code=sector_code,
        sector_benchmark_code=sector_code,
        sector_benchmark_last_observation_date=None,
        sector_return_3m=None,
        sector_return_6m=None,
        sector_return_12m=None,
        sector_rs_3m=None,
        sector_rs_6m=None,
        sector_rs_12m=None,
        sector_anchor_date_3m=None,
        sector_anchor_date_6m=None,
        sector_anchor_date_12m=None,
    )


def compute_relative_strength_features(
    ticker: str,
    as_of: str,
    stock_df: pd.DataFrame | None,
    market_index_df: pd.DataFrame | None,
    market: MarketType | str = MarketType.KOSPI,
    sector_index_df: pd.DataFrame | None = None,
    sector_mapping: dict[str, tuple[str, str]] | None = None,
) -> RelativeStrengthFeatureResult:
    """단일 종목에 대해 PIT 원칙에 따라 시장 및 업종 상대강도(RS) 피처를 계산한다.

    Args:
        ticker: 6자리 종목 코드.
        as_of: 기준일 ('YYYY-MM-DD' 또는 'YYYYMMDD').
        stock_df: 일봉 OHLCV DataFrame (index: DatetimeIndex, column: 'close').
        market_index_df: 시장 대표 지수 DataFrame (columns: ['date', 'index_code', 'close']).
        market: 종목의 시장 (KOSPI 또는 KOSDAQ).
        sector_index_df: 업종 지수 DataFrame (columns: ['date', 'index_code', 'close']).
        sector_mapping: Ticker -> (sector_code, sector_name) 딕셔너리.

    Returns:
        RelativeStrengthFeatureResult 객체.
    """
    clean_asof = as_of.replace("-", "")
    formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"
    ticker_z = str(ticker).zfill(6)

    # 1. Resolve Market Benchmark Code & Name
    market_str = market.value if isinstance(market, MarketType) else str(market).upper()
    if market_str == "KOSPI":
        target_mkt_code = "1001"
        target_mkt_name = "코스피"
    elif market_str == "KOSDAQ":
        target_mkt_code = "2001"
        target_mkt_name = "코스닥"
    else:
        target_mkt_code = None
        target_mkt_name = None

    # Resolve Sector Mapping Info if available (Strict PIT provenance: requires effective_date)
    s_code = None
    s_name = None
    if sector_mapping and ticker_z in sector_mapping:
        val = sector_mapping[ticker_z]
        if isinstance(val, (tuple, list)) and len(val) >= 3:
            sc, sn, eff_dt = val[0], val[1], str(val[2]).strip()
            # Strict PIT check: reject if mapping effective date is in the future relative to as_of
            if eff_dt <= formatted_asof:
                s_code, s_name = str(sc), str(sn)
        # Provenance-less 2-tuples are strictly rejected (s_code and s_name remain None -> DATA_UNAVAILABLE)

    if stock_df is None or stock_df.empty or market_index_df is None or market_index_df.empty:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    if target_mkt_code is None:
        return _unavailable_rs_result(ticker_z, formatted_asof)

    # 2. Extract and Filter Market Benchmark Series
    df_mkt = market_index_df[market_index_df["index_code"] == target_mkt_code].copy()
    if df_mkt.empty:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    df_mkt["date"] = df_mkt["date"].astype(str)
    # PIT Filter: date <= formatted_asof
    df_mkt = df_mkt[df_mkt["date"] <= formatted_asof].copy()
    if df_mkt.empty:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    if df_mkt.duplicated(subset=["date"]).any():
        raise MarketDataError(f"Duplicate date detected in market index {target_mkt_code}")

    df_mkt = df_mkt.sort_values(by="date").reset_index(drop=True)
    mkt_last_obs_date = df_mkt["date"].iloc[-1]

    # Exact Freshness Contract on Market Benchmark
    if mkt_last_obs_date != formatted_asof:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    # 3. Extract and Filter Stock Price Series
    s_df = stock_df.copy()
    if not isinstance(s_df.index, pd.DatetimeIndex):
        s_df.index = pd.to_datetime(s_df.index)
    s_df = s_df[s_df.index <= pd.Timestamp(formatted_asof)].copy()
    if s_df.empty or "close" not in s_df.columns:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    s_df["date_str"] = s_df.index.strftime("%Y-%m-%d")
    if s_df.duplicated(subset=["date_str"]).any():
        raise MarketDataError(f"Duplicate date detected in stock series for ticker {ticker_z}")

    s_map = dict(zip(s_df["date_str"], s_df["close"]))

    # Stock exact as_of observation must exist
    if formatted_asof not in s_map or pd.isna(s_map[formatted_asof]) or s_map[formatted_asof] <= 0:
        return _unavailable_rs_result(
            ticker_z,
            formatted_asof,
            market_benchmark_name=target_mkt_name,
            market_benchmark_code=target_mkt_code,
            sector_name=s_name,
            sector_code=s_code,
        )

    stock_end_close = float(s_map[formatted_asof])
    mkt_end_close = float(df_mkt["close"].iloc[-1])

    # 4. Compute Market RS for 3M, 6M, 12M Horizons
    mkt_obs_count = len(df_mkt)

    def _eval_horizon(
        sessions_back: int,
        df_bench: pd.DataFrame,
        bench_end_close: float,
    ) -> tuple[float | None, float | None, float | None, str | None]:
        """주어진 거래일 세션 수 이전의 anchor를 찾아 stock_return, bench_return, rs, anchor_date를 계산한다."""
        if len(df_bench) <= sessions_back:
            return None, None, None, None

        anchor_row = df_bench.iloc[-1 - sessions_back]
        anchor_date = str(anchor_row["date"])
        bench_anchor_close = float(anchor_row["close"])

        if bench_anchor_close <= 0:
            return None, None, None, anchor_date

        bench_ret = (bench_end_close / bench_anchor_close) - 1.0

        if anchor_date not in s_map or pd.isna(s_map[anchor_date]) or s_map[anchor_date] <= 0:
            return None, bench_ret, None, anchor_date

        stock_anchor_close = float(s_map[anchor_date])
        stock_ret = (stock_end_close / stock_anchor_close) - 1.0

        rel_ratio = (1.0 + stock_ret) / (1.0 + bench_ret)
        rs_val = rel_ratio - 1.0
        return stock_ret, bench_ret, rs_val, anchor_date

    # Market RS Horizons
    s_ret_3m, m_ret_3m, m_rs_3m, m_anc_3m = _eval_horizon(HORIZON_SESSIONS_3M, df_mkt, mkt_end_close)
    s_ret_6m, m_ret_6m, m_rs_6m, m_anc_6m = _eval_horizon(HORIZON_SESSIONS_6M, df_mkt, mkt_end_close)
    s_ret_12m, m_ret_12m, m_rs_12m, m_anc_12m = _eval_horizon(HORIZON_SESSIONS_12M, df_mkt, mkt_end_close)

    # Determine Market RS Data Status
    if m_rs_3m is None:
        market_rs_status = RelativeStrengthDataStatus.DATA_UNAVAILABLE
    elif m_rs_6m is not None and m_rs_12m is not None:
        market_rs_status = RelativeStrengthDataStatus.READY
    else:
        market_rs_status = RelativeStrengthDataStatus.PARTIAL

    # 5. Compute Sector Relative Strength (Independent Secondary Axis)
    sec_status = RelativeStrengthDataStatus.DATA_UNAVAILABLE
    sec_name = None
    sec_code = None
    sec_bench_code = None
    sec_last_obs_date = None
    sec_ret_3m = None
    sec_ret_6m = None
    sec_ret_12m = None
    sec_rs_3m = None
    sec_rs_6m = None
    sec_rs_12m = None
    sec_anc_3m = None
    sec_anc_6m = None
    sec_anc_12m = None

    if (
        sector_mapping is not None
        and ticker_z in sector_mapping
        and sector_index_df is not None
        and not sector_index_df.empty
    ):
        mapped_code, mapped_name = sector_mapping[ticker_z]
        sec_code = mapped_code
        sec_name = mapped_name
        sec_bench_code = mapped_code

        df_sec = sector_index_df[sector_index_df["index_code"] == str(mapped_code)].copy()
        if not df_sec.empty:
            df_sec["date"] = df_sec["date"].astype(str)
            df_sec = df_sec[df_sec["date"] <= formatted_asof].copy()
            if not df_sec.empty:
                if df_sec.duplicated(subset=["date"]).any():
                    raise MarketDataError(f"Duplicate date in sector index {mapped_code}")
                df_sec = df_sec.sort_values(by="date").reset_index(drop=True)
                sec_last_obs_date = df_sec["date"].iloc[-1]

                if sec_last_obs_date == formatted_asof:
                    sec_end_close = float(df_sec["close"].iloc[-1])

                    # Compute Sector RS Horizons
                    _, sec_ret_3m, sec_rs_3m, sec_anc_3m = _eval_horizon(HORIZON_SESSIONS_3M, df_sec, sec_end_close)
                    _, sec_ret_6m, sec_rs_6m, sec_anc_6m = _eval_horizon(HORIZON_SESSIONS_6M, df_sec, sec_end_close)
                    _, sec_ret_12m, sec_rs_12m, sec_anc_12m = _eval_horizon(HORIZON_SESSIONS_12M, df_sec, sec_end_close)

                    if sec_rs_3m is None:
                        sec_status = RelativeStrengthDataStatus.DATA_UNAVAILABLE
                    elif sec_rs_6m is not None and sec_rs_12m is not None:
                        sec_status = RelativeStrengthDataStatus.READY
                    else:
                        sec_status = RelativeStrengthDataStatus.PARTIAL

    return RelativeStrengthFeatureResult(
        ticker=ticker_z,
        as_of=formatted_asof,
        market_rs_data_status=market_rs_status,
        market_benchmark_name=target_mkt_name,
        market_benchmark_code=target_mkt_code,
        market_benchmark_last_observation_date=mkt_last_obs_date,
        stock_return_3m=s_ret_3m,
        stock_return_6m=s_ret_6m,
        stock_return_12m=s_ret_12m,
        market_return_3m=m_ret_3m,
        market_return_6m=m_ret_6m,
        market_return_12m=m_ret_12m,
        market_rs_3m=m_rs_3m,
        market_rs_6m=m_rs_6m,
        market_rs_12m=m_rs_12m,
        market_anchor_date_3m=m_anc_3m,
        market_anchor_date_6m=m_anc_6m,
        market_anchor_date_12m=m_anc_12m,
        sector_rs_data_status=sec_status,
        sector_name=sec_name,
        sector_code=sec_code,
        sector_benchmark_code=sec_bench_code,
        sector_benchmark_last_observation_date=sec_last_obs_date,
        sector_return_3m=sec_ret_3m,
        sector_return_6m=sec_ret_6m,
        sector_return_12m=sec_ret_12m,
        sector_rs_3m=sec_rs_3m,
        sector_rs_6m=sec_rs_6m,
        sector_rs_12m=sec_rs_12m,
        sector_anchor_date_3m=sec_anc_3m,
        sector_anchor_date_6m=sec_anc_6m,
        sector_anchor_date_12m=sec_anc_12m,
    )
