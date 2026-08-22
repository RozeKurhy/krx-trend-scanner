"""Strategy-invariant Pattern A / FAST snapshot caches (BACKTEST_PERFORMANCE_ENGINEERING_V01, Priority 3/4).

``evaluate_pattern_a_fast(ticker, name, daily, w, score_contract, stage_contract)``
and the monthly ``build_historical_snapshot(...) -> evaluate_pattern_a(...)``
pair are pure functions of ``(ticker, reference_date)`` given a fixed daily
OHLCV frame and fixed frozen contracts. Neither depends on
``enable_loss_guard`` or ``sensitivity_mode``. ``simulate_ticker_strategy_2022``
is invoked up to 4 times per ticker per backtest run (Baseline/Julia x
Primary/Sensitivity) and today recomputes both independently every time.

These caches memoize by ``(ticker, reference_date)`` so the expensive
evaluation runs once and is reused across all passes, while preserving the
exact per-call success/failure outcome of the original inline
``try/except Exception`` blocks it replaces:

- ``FastSnapshotCache`` mirrors the search-loop's ``except Exception: continue``
  by storing a ``_FAILED`` sentinel on exception; callers must treat a
  sentinel hit exactly like the original ``continue``.
- ``MonthlySnapshotCache`` mirrors the monthly-snapshot loop's
  ``except Exception: {"stage": "UNAVAILABLE", "score": None}`` fallback by
  storing that exact fallback value on exception.

No feature formula, contract interpretation, or stage/score semantic is
reimplemented here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

_FAILED = object()
_FAILED_MARKER = "__FAST_SNAPSHOT_EVALUATION_FAILED__"


class FastSnapshotCache:
    """Memoizes ``evaluate_pattern_a_fast`` results by ``(ticker, week)``."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, pd.Timestamp], dict | object] = {}
        self.evaluation_count = 0
        self.cache_hit_count = 0

    def __len__(self) -> int:
        return len(self._store)

    def get(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        w: pd.Timestamp,
        score_contract: dict,
        stage_contract: dict,
    ) -> dict | None:
        """Returns the evaluate_pattern_a_fast result dict, or None on the
        same failure condition the original inline try/except would have
        hit (caller must ``continue`` exactly as before on None)."""
        key = (ticker, w)
        cached = self._store.get(key)
        if cached is not None:
            self.cache_hit_count += 1
            return None if cached is _FAILED else cached

        self.evaluation_count += 1
        try:
            res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
        except Exception:
            self._store[key] = _FAILED
            return None
        self._store[key] = res
        return res

    def export_store(self) -> dict[tuple[str, pd.Timestamp], dict | str]:
        """Picklable snapshot of the cache contents for persistent-cache
        storage (``_FAILED`` is not stably picklable as a cross-process
        identity, so it is exported as ``_FAILED_MARKER`` and restored back
        to the in-process ``_FAILED`` sentinel on import)."""
        return {key: (_FAILED_MARKER if v is _FAILED else v) for key, v in self._store.items()}

    def import_store(self, data: dict[tuple[str, pd.Timestamp], dict | str]) -> None:
        """Bulk-loads entries from a previously exported store (e.g. a disk-
        persisted cache from an earlier process). Existing entries with the
        same key are overwritten; this never changes what ``get()`` would
        have computed for a given key, only whether it needs to."""
        for key, v in data.items():
            self._store[key] = _FAILED if v == _FAILED_MARKER else v


class MonthlySnapshotCache:
    """Memoizes the monthly Pattern A (stage, score) snapshot by ``(ticker, month)``."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, pd.Timestamp], dict[str, Any]] = {}
        self.evaluation_count = 0
        self.cache_hit_count = 0

    def __len__(self) -> int:
        return len(self._store)

    def get(self, ticker: str, name: str, daily: pd.DataFrame, m: pd.Timestamp) -> dict[str, Any]:
        key = (ticker, m)
        cached = self._store.get(key)
        if cached is not None:
            self.cache_hit_count += 1
            return cached

        self.evaluation_count += 1
        try:
            snap = build_historical_snapshot(ticker, name, daily[daily.index <= m], m, include_incomplete_periods=False)
            eval_res = evaluate_pattern_a(snap)
            st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
            sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
            result = {"date": m, "stage": st, "score": sc}
        except Exception:
            result = {"date": m, "stage": "UNAVAILABLE", "score": None}
        self._store[key] = result
        return result

    def export_store(self) -> dict[tuple[str, pd.Timestamp], dict[str, Any]]:
        """Picklable snapshot of the cache contents for persistent-cache storage."""
        return dict(self._store)

    def import_store(self, data: dict[tuple[str, pd.Timestamp], dict[str, Any]]) -> None:
        """Bulk-loads entries from a previously exported store."""
        self._store.update(data)
