"""Pattern B operational policy V02 — market-transfer history and price freshness.

Contract: docs/patterns/pattern_b/spec/production_contract_v02.md

Pattern B only; shared Repository V2 / rolling authority code is not changed.

Policy A (history): starting from the active COMMON segment on ``target_as_of``, earlier
segments are linked only through a contiguous KOSPI <-> KOSDAQ market-transfer chain
(same ticker, same isu_cd, both COMMON, previous ``effective_to`` followed by the current
``effective_from`` on the next KRX trading date). Each linked segment is read with its own
date range through ``RepositoryV2DailyLoader`` and the frames are concatenated.

Policy B (freshness): ``CURRENT`` when the last completed weekly bar equals the latest
completed W-FRI label on or before ``target_as_of``; otherwise ``STALE``. Freshness never
changes the Pattern B state and is not an evaluation status.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import pandas as pd

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader

TRANSFER_MARKETS = frozenset({"KOSPI", "KOSDAQ"})
CURRENT = "CURRENT"
STALE = "STALE"
FRESHNESS_STATUSES = (CURRENT, STALE)

STOP_NONE = ""
STOP_GAP = "GAP"
STOP_ISU_CHANGE = "ISU_CHANGE"
STOP_SAME_MARKET = "SAME_MARKET"
STOP_NON_COMMON = "NON_COMMON"


class PatternBHistoryError(ValueError):
    """History segments are ambiguous or the stitched frame breaks its contract; fail closed."""


@dataclass(frozen=True)
class HistorySegment:
    market: str
    isu_cd: str
    effective_from: str
    effective_to: str
    state: str = "COMMON"


@dataclass(frozen=True)
class HistoryChain:
    segments: tuple[HistorySegment, ...]  # oldest first; the last one is the active segment
    stop_reason: str  # why the walk stopped at the oldest segment ("" when nothing precedes it)

    @property
    def history_effective_from(self) -> str:
        return self.segments[0].effective_from

    @property
    def market_transfer_stitched(self) -> bool:
        return len(self.segments) > 1


def _segment(iv: Mapping) -> HistorySegment:
    return HistorySegment(
        market=str(iv["market"]).upper(), isu_cd=str(iv["isu_cd"]),
        effective_from=str(iv["effective_from"])[:10], effective_to=str(iv["effective_to"])[:10],
        state=str(iv.get("state", "")),
    )


def next_trading_date(trading_dates: Sequence[str], date: str) -> str | None:
    """First trading date strictly after ``date`` (``trading_dates`` sorted ISO strings)."""
    i = bisect.bisect_right(trading_dates, date)
    return trading_dates[i] if i < len(trading_dates) else None


def history_chain(
    ticker: str, active: Mapping, intervals: Iterable[Mapping], trading_dates: Sequence[str],
) -> HistoryChain:
    """Contiguous market-transfer chain ending at ``active``; ambiguity raises."""
    own = [_segment(iv) for iv in intervals if str(iv["ticker"]).strip().upper() == ticker]
    current = _segment(active)
    for seg in own:
        if seg != current and not (seg.effective_to < current.effective_from
                                   or seg.effective_from > current.effective_to):
            raise PatternBHistoryError(f"{ticker}: segment overlaps the active segment")
    chain = [current]
    while True:
        head = chain[0]
        earlier = [s for s in own if s.effective_to < head.effective_from]
        if not earlier:
            return HistoryChain(tuple(chain), STOP_NONE)
        latest_to = max(s.effective_to for s in earlier)
        previous = [s for s in earlier if s.effective_to == latest_to]
        if len(previous) != 1:
            raise PatternBHistoryError(f"{ticker}: {len(previous)} segments end on {latest_to}")
        prev = previous[0]
        if any(s.effective_from <= prev.effective_to and s.effective_to >= prev.effective_from
               for s in own if s != prev and s not in chain):
            raise PatternBHistoryError(f"{ticker}: segment overlaps {prev.effective_from}~{prev.effective_to}")
        if next_trading_date(trading_dates, prev.effective_to) != head.effective_from:
            return HistoryChain(tuple(chain), STOP_GAP)
        if prev.isu_cd != head.isu_cd:
            return HistoryChain(tuple(chain), STOP_ISU_CHANGE)
        if prev.state != "COMMON" or head.state != "COMMON":
            return HistoryChain(tuple(chain), STOP_NON_COMMON)
        if not ({prev.market, head.market} <= TRANSFER_MARKETS and prev.market != head.market):
            return HistoryChain(tuple(chain), STOP_SAME_MARKET)
        chain.insert(0, prev)


def stitch_frames(pieces: Sequence[tuple[HistorySegment, pd.DataFrame]], target_as_of: str) -> pd.DataFrame:
    """Concatenate per-segment frames; every row must lie in its own segment range."""
    target = pd.Timestamp(target_as_of)
    checked = []
    for i, (seg, frame) in enumerate(pieces):
        end = target if i == len(pieces) - 1 else pd.Timestamp(seg.effective_to)
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise PatternBHistoryError("segment frame index is not a DatetimeIndex")
        if len(frame) and (frame.index.min() < pd.Timestamp(seg.effective_from) or frame.index.max() > end):
            raise PatternBHistoryError(f"rows outside segment {seg.effective_from}~{end.date()}")
        if frame.attrs.get("data_authority") != "MarketDataRepositoryV2":
            raise PatternBHistoryError("segment frame is not from MarketDataRepositoryV2")
        checked.append(frame)
    stitched = pd.concat(checked) if len(checked) > 1 else checked[0].copy()
    if not stitched.index.is_unique:
        raise PatternBHistoryError("stitched history has duplicate dates")
    if not stitched.index.is_monotonic_increasing:
        raise PatternBHistoryError("stitched history is not in date order")
    stitched.attrs = {"data_authority": "MarketDataRepositoryV2"}
    return stitched


def load_history(repository, ticker: str, chain: HistoryChain, target_as_of: str) -> pd.DataFrame | None:
    """Per-segment Repository V2 reads, then ``stitch_frames``; ``None`` if any segment is unavailable."""
    pieces = []
    for i, seg in enumerate(chain.segments):
        end = target_as_of if i == len(chain.segments) - 1 else seg.effective_to
        frame = RepositoryV2DailyLoader(repository, start=seg.effective_from, end=end).load(ticker)
        if frame is None:
            return None
        pieces.append((seg, frame))
    return stitch_frames(pieces, target_as_of)


def expected_weekly_bar(target_as_of: str) -> str:
    """Latest completed W-FRI label on or before ``target_as_of`` (Feature Contract V01 rule)."""
    ts = pd.Timestamp(target_as_of).normalize()
    friday = ts if ts.weekday() == 4 else ts - pd.offsets.Week(weekday=4)
    return friday.date().isoformat()


def freshness_status(weekly_last_bar: str | None, target_as_of: str) -> str:
    return CURRENT if weekly_last_bar and weekly_last_bar == expected_weekly_bar(target_as_of) else STALE
