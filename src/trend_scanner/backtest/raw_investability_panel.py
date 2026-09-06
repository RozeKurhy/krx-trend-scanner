"""PIT raw investability panel (market cap / 20D avg trading value / close).

Builds per-ticker daily time series of the three raw KRX fields the
FastCore vs Julia STEP 1 backtest entry-only filter needs
(``MKTCAP``, ``ACC_TRDVAL`` 20-trading-day rolling mean, ``TDD_CLSPRC``)
directly from :class:`KrxRawStockStore`'s official local historical
snapshots -- never from live PyKRX/KRX API/Naver/OpenDART, and never from
the single as-of production investability snapshot (which only reflects
one date, not the full PIT history a backtest needs).

Built once per backtest run (one pass over every raw daily snapshot,
not once per ticker) because :meth:`KrxRawStockStore.load_ticker` scans
every date's manifest row per ticker -- O(dates x tickers) if called in a
loop. Loading every whole-market snapshot once and pivoting to per-ticker
series is O(dates) instead.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore

RAW_MARKETS = ("KOSPI", "KOSDAQ")
AVG_TRADING_VALUE_WINDOW = 20


def build_raw_investability_panel(
    tickers: set[str],
    *,
    end: str | pd.Timestamp,
    raw_root: Path | str = DEFAULT_RAW_STOCK_ROOT,
) -> dict[str, pd.DataFrame]:
    """Return ``{ticker: DataFrame(index=date, columns=[close, market_cap,
    trading_value, avg_trading_value_20d])}`` built from raw KRX snapshots.

    Only dates ``<= end`` are read. ``avg_trading_value_20d`` at date ``t``
    uses only that ticker's own trading-day history up to and including
    ``t`` (a trailing rolling mean over its own observed dates), so it is
    PIT-safe by construction -- it never needs a day that has not
    happened yet, and a ticker's halted/missing days do not silently
    borrow future days to fill the window.
    """
    store = KrxRawStockStore(raw_root)
    end_day = pd.Timestamp(end).strftime("%Y-%m-%d")

    frames: list[pd.DataFrame] = []
    for market in RAW_MARKETS:
        for day in store.list_dates(market):
            if day > end_day:
                continue
            snap = store.load_snapshot(market, day)
            if snap.empty:
                continue
            snap = snap[snap["ticker"].isin(tickers)]
            if snap.empty:
                continue
            frames.append(
                snap.loc[:, ["date", "ticker", "close", "market_cap", "trading_value"]]
            )

    if not frames:
        return {}

    long_df = pd.concat(frames, ignore_index=True)
    long_df["date"] = pd.to_datetime(long_df["date"])
    long_df = long_df.sort_values(["ticker", "date"])
    # Preserve same-day cross-market collisions instead of silently selecting
    # one row.  The identity-scoped runner detects the duplicate index and
    # fails that (ticker, ISU_CD, market) task closed.
    if not long_df.duplicated(subset=["ticker", "date"], keep=False).any():
        long_df = long_df.drop_duplicates(subset=["ticker", "date"], keep="first")

    panels: dict[str, pd.DataFrame] = {}
    for ticker, group in long_df.groupby("ticker", sort=False):
        g = group.set_index("date").sort_index()
        g["avg_trading_value_20d"] = (
            g["trading_value"].rolling(window=AVG_TRADING_VALUE_WINDOW, min_periods=AVG_TRADING_VALUE_WINDOW).mean()
        )
        panels[str(ticker)] = g.loc[:, ["close", "market_cap", "trading_value", "avg_trading_value_20d"]]

    return panels


def evaluate_entry_filter(
    panel: pd.DataFrame | None,
    signal_date: pd.Timestamp,
    *,
    market_cap_threshold: float,
    avg_trading_value_threshold: float,
    close_threshold: float,
) -> dict[str, object]:
    """Entry-only investability filter evaluated strictly as of ``signal_date``.

    Never an exit condition -- callers must only call this at entry/re-entry
    decision points, never to force a close on an open position.
    """
    result = {
        "entry_market_cap": None,
        "entry_avg_trading_value_20d": None,
        "entry_signal_close": None,
        "entry_filter_raw_date": None,
        "entry_market_cap_pass": False,
        "entry_trading_value_pass": False,
        "entry_close_pass": False,
        "entry_filter_pass": False,
    }
    if panel is None or panel.empty:
        return result
    row = panel[panel.index <= signal_date]
    if row.empty:
        return result
    # Most recent PIT-valid raw observation at or before the signal date --
    # if the signal date itself has no raw snapshot (e.g. a weekly-bar
    # label that isn't itself a KRX raw trading day), this falls back to
    # the latest one before it, never one after it.
    last = row.iloc[-1]
    raw_date = row.index[-1]
    mkt_cap = last["market_cap"]
    avg_tv = last["avg_trading_value_20d"]
    close = last["close"]

    mkt_cap_pass = bool(pd.notna(mkt_cap) and mkt_cap >= market_cap_threshold)
    tv_pass = bool(pd.notna(avg_tv) and avg_tv >= avg_trading_value_threshold)
    close_pass = bool(pd.notna(close) and close >= close_threshold)

    result.update(
        entry_market_cap=None if pd.isna(mkt_cap) else float(mkt_cap),
        entry_avg_trading_value_20d=None if pd.isna(avg_tv) else float(avg_tv),
        entry_signal_close=None if pd.isna(close) else float(close),
        entry_filter_raw_date=pd.Timestamp(raw_date).strftime("%Y-%m-%d"),
        entry_market_cap_pass=mkt_cap_pass,
        entry_trading_value_pass=tv_pass,
        entry_close_pass=close_pass,
        entry_filter_pass=bool(mkt_cap_pass and tv_pass and close_pass),
    )
    return result
