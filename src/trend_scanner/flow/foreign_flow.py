"""외국인 수급(Foreign Investor Flow) 확증 피처 계산 엔진.

Point In Time(PIT) 원칙과 거래일 기준 Window(1D, 5D, 20D, 60D)를 준수하여
외국인 순매수 금액(KRW), 거래대금 대비 Flow Intensity, Positive Flow Day 피처를 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.errors import MarketDataError


class FlowDataStatus(str, Enum):
    """외국인 수급 데이터 준비 상태."""

    READY = "READY"                      # 20D window 정상 산출 및 provenance 유효
    PARTIAL = "PARTIAL"                  # 5D는 산출 가능하나 20D observation 부족
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"  # 수급 데이터 부재 또는 신뢰 불가 (계약: DATA_UNAVAILABLE row의 flow 숫자는 production confirmation / ranking에 절대 사용 금지)
    NOT_EVALUATED = "NOT_EVALUATED"        # 스캐너에서 미평가된 종목 상태


@dataclass(frozen=True)
class ForeignFlowFeatureResult:
    """단일 종목의 외국인 수급 피처 계산 결과."""

    ticker: str
    as_of: str
    data_status: FlowDataStatus

    # Provenance
    foreign_flow_last_observation_date: str | None
    foreign_flow_first_observation_date: str | None
    foreign_flow_observation_count: int

    # 1. Raw Window Net Buy Values (Signed KRW)
    foreign_net_buy_value_1d: float | None
    foreign_net_buy_value_5d: float | None
    foreign_net_buy_value_20d: float | None
    foreign_net_buy_value_60d: float | None

    # 2. Normalized Flow Intensity (Net Buy / Trading Value)
    foreign_flow_intensity_5d: float | None
    foreign_flow_intensity_20d: float | None
    foreign_flow_intensity_60d: float | None

    # 3. Positive Flow Days & Ratios
    foreign_positive_days_5d: int | None
    foreign_positive_days_20d: int | None
    foreign_positive_days_60d: int | None
    foreign_positive_day_ratio_5d: float | None
    foreign_positive_day_ratio_20d: float | None
    foreign_positive_day_ratio_60d: float | None

    # 4. Optional Diagnostics
    foreign_net_buy_avg_5d: float | None = None
    foreign_net_buy_avg_20d: float | None = None
    foreign_net_buy_avg_60d: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Dictionary 변환 (JSON / DataFrame 직렬화용)."""
        return {
            "ticker": self.ticker,
            "as_of": self.as_of,
            "foreign_flow_data_status": self.data_status.value,
            "foreign_flow_last_observation_date": self.foreign_flow_last_observation_date,
            "foreign_flow_first_observation_date": self.foreign_flow_first_observation_date,
            "foreign_flow_observation_count": self.foreign_flow_observation_count,
            "foreign_net_buy_value_1d": self.foreign_net_buy_value_1d,
            "foreign_net_buy_value_5d": self.foreign_net_buy_value_5d,
            "foreign_net_buy_value_20d": self.foreign_net_buy_value_20d,
            "foreign_net_buy_value_60d": self.foreign_net_buy_value_60d,
            "foreign_flow_intensity_5d": self.foreign_flow_intensity_5d,
            "foreign_flow_intensity_20d": self.foreign_flow_intensity_20d,
            "foreign_flow_intensity_60d": self.foreign_flow_intensity_60d,
            "foreign_positive_days_5d": self.foreign_positive_days_5d,
            "foreign_positive_days_20d": self.foreign_positive_days_20d,
            "foreign_positive_days_60d": self.foreign_positive_days_60d,
            "foreign_positive_day_ratio_5d": self.foreign_positive_day_ratio_5d,
            "foreign_positive_day_ratio_20d": self.foreign_positive_day_ratio_20d,
            "foreign_positive_day_ratio_60d": self.foreign_positive_day_ratio_60d,
            "foreign_net_buy_avg_5d": self.foreign_net_buy_avg_5d,
            "foreign_net_buy_avg_20d": self.foreign_net_buy_avg_20d,
            "foreign_net_buy_avg_60d": self.foreign_net_buy_avg_60d,
        }


def _unavailable_result(ticker: str, as_of: str) -> ForeignFlowFeatureResult:
    """데이터 부재 시 반환하는 기본 불능 결과."""
    return ForeignFlowFeatureResult(
        ticker=ticker,
        as_of=as_of,
        data_status=FlowDataStatus.DATA_UNAVAILABLE,
        foreign_flow_last_observation_date=None,
        foreign_flow_first_observation_date=None,
        foreign_flow_observation_count=0,
        foreign_net_buy_value_1d=None,
        foreign_net_buy_value_5d=None,
        foreign_net_buy_value_20d=None,
        foreign_net_buy_value_60d=None,
        foreign_flow_intensity_5d=None,
        foreign_flow_intensity_20d=None,
        foreign_flow_intensity_60d=None,
        foreign_positive_days_5d=None,
        foreign_positive_days_20d=None,
        foreign_positive_days_60d=None,
        foreign_positive_day_ratio_5d=None,
        foreign_positive_day_ratio_20d=None,
        foreign_positive_day_ratio_60d=None,
        foreign_net_buy_avg_5d=None,
        foreign_net_buy_avg_20d=None,
        foreign_net_buy_avg_60d=None,
    )


def compute_foreign_flow_features(
    ticker: str,
    as_of: str,
    flow_df: pd.DataFrame | None,
    price_df: pd.DataFrame | None = None,
) -> ForeignFlowFeatureResult:
    """단일 종목에 대해 PIT 외국인 수급 피처를 계산한다.

    Args:
        ticker: 6자리 종목 코드.
        as_of: 기준일 ('YYYY-MM-DD' 또는 'YYYYMMDD').
        flow_df: 외국인 수급 DataFrame (columns: ['date', 'ticker', 'foreign_net_buy_value', ...]).
        price_df: 일봉 OHLCV DataFrame (index: DatetimeIndex, column: 'trading_value').

    Returns:
        ForeignFlowFeatureResult 객체.
    """
    clean_asof = as_of.replace("-", "")
    formatted_asof = f"{clean_asof[:4]}-{clean_asof[4:6]}-{clean_asof[6:8]}"

    if flow_df is None or flow_df.empty:
        return _unavailable_result(ticker, formatted_asof)

    # 1. Filter by ticker if multiple tickers present
    if "ticker" in flow_df.columns:
        df_t = flow_df[flow_df["ticker"] == str(ticker).zfill(6)].copy()
    else:
        df_t = flow_df.copy()

    if df_t.empty:
        return _unavailable_result(ticker, formatted_asof)

    # 2. PIT Filter: date <= formatted_asof (Strict No Future Lookahead)
    df_t["date"] = df_t["date"].astype(str)
    df_t = df_t[df_t["date"] <= formatted_asof].copy()
    if df_t.empty:
        return _unavailable_result(ticker, formatted_asof)

    # 3. Check for Duplicate Rows
    if df_t.duplicated(subset=["date"]).any():
        raise MarketDataError(f"Duplicate date detected in foreign flow for ticker {ticker}")

    # 4. Sort strictly ascending by date
    df_t = df_t.sort_values(by="date").reset_index(drop=True)

    obs_count = len(df_t)
    first_obs_date = df_t["date"].iloc[0]
    last_obs_date = df_t["date"].iloc[-1]

    # Stale observation check: if last observation is not recent or empty
    # In canonical dataset, last observation is expected <= formatted_asof
    if last_obs_date > formatted_asof:
        raise MarketDataError(f"PIT violation: last_obs_date {last_obs_date} > as_of {formatted_asof}")

    # 5. Join with Price/Trading Value for Intensity Normalization
    tv_series = None
    if price_df is not None and not price_df.empty:
        p_df = price_df.copy()
        if not isinstance(p_df.index, pd.DatetimeIndex):
            p_df.index = pd.to_datetime(p_df.index)
        p_df = p_df[p_df.index <= pd.Timestamp(formatted_asof)]
        p_df["date_str"] = p_df.index.strftime("%Y-%m-%d")
        if "trading_value" in p_df.columns:
            tv_map = dict(zip(p_df["date_str"], p_df["trading_value"]))
            df_t["trading_value"] = df_t["date"].map(tv_map)
        else:
            df_t["trading_value"] = np.nan
    else:
        df_t["trading_value"] = np.nan

    # 6. Data Readiness Determination (Stale Flow Fail Closed)
    # Exact as_of freshness is mandatory for production flow readiness.
    if last_obs_date != formatted_asof:
        data_status = FlowDataStatus.DATA_UNAVAILABLE
    elif obs_count < 5:
        data_status = FlowDataStatus.DATA_UNAVAILABLE
    elif obs_count < 20:
        data_status = FlowDataStatus.PARTIAL
    else:
        data_status = FlowDataStatus.READY

    # 7. Window Computations (1D, 5D, 20D, 60D)
    net_buys = df_t["foreign_net_buy_value"].to_numpy(dtype=float)
    trading_vals = df_t["trading_value"].to_numpy(dtype=float)

    # 1D
    net_buy_1d = float(net_buys[-1]) if obs_count >= 1 else None

    # 5D
    if obs_count >= 5:
        w5_net = net_buys[-5:]
        w5_tv = trading_vals[-5:]
        net_buy_5d = float(np.sum(w5_net))
        net_buy_avg_5d = float(np.mean(w5_net))
        pos_days_5d = int(np.sum(w5_net > 0))
        pos_ratio_5d = round(pos_days_5d / 5.0, 4)

        if np.isnan(w5_tv).any() or np.sum(w5_tv) <= 0:
            intensity_5d = None
        else:
            intensity_5d = float(np.sum(w5_net) / np.sum(w5_tv))
    else:
        net_buy_5d = None
        net_buy_avg_5d = None
        pos_days_5d = None
        pos_ratio_5d = None
        intensity_5d = None

    # 20D
    if obs_count >= 20:
        w20_net = net_buys[-20:]
        w20_tv = trading_vals[-20:]
        net_buy_20d = float(np.sum(w20_net))
        net_buy_avg_20d = float(np.mean(w20_net))
        pos_days_20d = int(np.sum(w20_net > 0))
        pos_ratio_20d = round(pos_days_20d / 20.0, 4)

        if np.isnan(w20_tv).any() or np.sum(w20_tv) <= 0:
            intensity_20d = None
        else:
            intensity_20d = float(np.sum(w20_net) / np.sum(w20_tv))
    else:
        net_buy_20d = None
        net_buy_avg_20d = None
        pos_days_20d = None
        pos_ratio_20d = None
        intensity_20d = None

    # 60D
    if obs_count >= 60:
        w60_net = net_buys[-60:]
        w60_tv = trading_vals[-60:]
        net_buy_60d = float(np.sum(w60_net))
        net_buy_avg_60d = float(np.mean(w60_net))
        pos_days_60d = int(np.sum(w60_net > 0))
        pos_ratio_60d = round(pos_days_60d / 60.0, 4)

        if np.isnan(w60_tv).any() or np.sum(w60_tv) <= 0:
            intensity_60d = None
        else:
            intensity_60d = float(np.sum(w60_net) / np.sum(w60_tv))
    else:
        net_buy_60d = None
        net_buy_avg_60d = None
        pos_days_60d = None
        pos_ratio_60d = None
        intensity_60d = None

    return ForeignFlowFeatureResult(
        ticker=ticker,
        as_of=formatted_asof,
        data_status=data_status,
        foreign_flow_last_observation_date=last_obs_date,
        foreign_flow_first_observation_date=first_obs_date,
        foreign_flow_observation_count=obs_count,
        foreign_net_buy_value_1d=net_buy_1d,
        foreign_net_buy_value_5d=net_buy_5d,
        foreign_net_buy_value_20d=net_buy_20d,
        foreign_net_buy_value_60d=net_buy_60d,
        foreign_flow_intensity_5d=intensity_5d,
        foreign_flow_intensity_20d=intensity_20d,
        foreign_flow_intensity_60d=intensity_60d,
        foreign_positive_days_5d=pos_days_5d,
        foreign_positive_days_20d=pos_days_20d,
        foreign_positive_days_60d=pos_days_60d,
        foreign_positive_day_ratio_5d=pos_ratio_5d,
        foreign_positive_day_ratio_20d=pos_ratio_20d,
        foreign_positive_day_ratio_60d=pos_ratio_60d,
        foreign_net_buy_avg_5d=net_buy_avg_5d,
        foreign_net_buy_avg_20d=net_buy_avg_20d,
        foreign_net_buy_avg_60d=net_buy_avg_60d,
    )
