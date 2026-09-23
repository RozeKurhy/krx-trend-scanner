"""Pattern B Holdout V02 selection and chart contract (synthetic data only)."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/build_pattern_b_holdout_v02_chart_pack.py"
_spec = importlib.util.spec_from_file_location("build_pattern_b_holdout_v02_chart_pack", _SCRIPT)
hold = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hold  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(hold)

CALENDAR = pd.bdate_range("2010-01-04", "2026-08-31")


def _daily(end, start="2010-01-04", seed=0) -> pd.DataFrame:
    dates = CALENDAR[(CALENDAR >= pd.Timestamp(start)) & (CALENDAR <= pd.Timestamp(end))]
    close = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.01, len(dates))))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": 1.0, "trading_value": 1.0},
        index=dates,
    )


class FakeRepository:
    """Serves synthetic history; tickers in ``short`` start too late for 84 monthly bars."""

    def __init__(self, short=()):
        self.short = set(short)

    def get_daily(self, ticker, start, end):
        first = "2024-01-02" if ticker in self.short else start
        return _daily(end, start=max(pd.Timestamp(first), pd.Timestamp("2010-01-04")))


def _intervals(tickers):
    return [{"ticker": t, "state": "COMMON", "effective_from": "2005-01-03", "effective_to": "2026-08-31"}
            for t in tickers]


def test_anchor_is_last_session_on_or_before_june_30():
    assert hold.resolve_anchor(CALENDAR, 2024) == pd.Timestamp("2024-06-28")  # June 30 is a Sunday
    assert hold.resolve_anchor(CALENDAR, 2020) == pd.Timestamp("2020-06-30")


def test_hash_order_is_deterministic():
    anchor = pd.Timestamp("2022-06-30")
    key = hold.hash_key(anchor, "123456")
    assert key == hold.hash_key(anchor, "123456")
    import hashlib
    assert key == hashlib.sha256(b"PATTERN_B_HOLDOUT_V02|2022-06-30|123456").hexdigest()
    assert key != hold.hash_key(pd.Timestamp("2024-06-28"), "123456")


def test_selection_excludes_v01_skips_gaps_and_never_reuses_tickers():
    v01 = sorted(hold.V01_TICKERS)
    assert {"005930", "086520", "003490", "009150"} <= set(v01)
    normal = [f"9{i:05d}" for i in range(45)]
    short = normal[:5]
    anchors = [(y, hold.resolve_anchor(CALENDAR, y)) for y in hold.ANCHOR_YEARS]
    samples, audit = hold.select_samples(
        anchors, _intervals(v01 + normal), FakeRepository(short=short), CALENDAR
    )
    tickers = [s["ticker"] for s in samples]
    assert len(samples) == 36 and len(set(tickers)) == 36
    assert not set(tickers) & hold.V01_TICKERS
    assert not set(tickers) & set(short)
    assert {y: sum(s["anchor_year"] == y for s in samples) for y in hold.ANCHOR_YEARS} == {
        y: 9 for y in hold.ANCHOR_YEARS
    }
    assert all(len(s["monthly"]) == 84 and len(s["weekly"]) == 156 for s in samples)
    assert any(audit[str(y)]["skips"].get("INSUFFICIENT_BARS") for y in hold.ANCHOR_YEARS)


def test_existing_mapping_is_reused_and_mismatch_fails(tmp_path):
    samples = [{"ticker": f"9{i:05d}", "as_of": "2020-06-30"} for i in range(3)]
    manifest = tmp_path / "private_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sample_id", "ticker", "as_of"])
        writer.writeheader()
        for i, s in enumerate(reversed(samples), start=1):
            writer.writerow({"sample_id": f"PBHOLD_{i:03d}", **s})
    hold.assign_sample_ids(samples, manifest)
    assert [s["sample_id"] for s in samples] == ["PBHOLD_003", "PBHOLD_002", "PBHOLD_001"]
    with pytest.raises(SystemExit):
        hold.assign_sample_ids(samples + [{"ticker": "999999", "as_of": "2020-06-30"}], manifest)


def test_inner_halt_gap_is_kept():
    as_of = pd.Timestamp("2022-06-30")
    daily = _daily(as_of)
    weeks = daily.index.to_period("W-FRI")
    daily = daily[weeks != weeks[-60]]
    window = hold.build_window(daily, CALENDAR, as_of)
    assert len(window["weekly"]) == 156 and len(window["monthly"]) == 84
    assert window["halt_slots"]["weekly"] == 1
    positions = hold.v01.period_positions(window["weekly"].index, "weekly")
    assert positions[-1] - positions[0] + 1 == 157  # the halted week keeps its slot


def test_candidate_halted_at_as_of_is_skipped():
    as_of = pd.Timestamp("2022-06-30")  # Thursday: last completed week ends 2022-06-24
    daily = _daily(as_of)
    daily = daily[daily.index <= pd.Timestamp("2022-06-17")]
    with pytest.raises(hold.CandidateSkip, match="HALTED_AT_AS_OF"):
        hold.build_window(daily, CALENDAR, as_of)


def test_invalid_ohlc_and_short_history_are_skips():
    daily = _daily("2022-06-30")
    daily.iloc[10, daily.columns.get_loc("low")] = daily.iloc[10]["high"] * 2
    with pytest.raises(hold.CandidateSkip, match="OHLC_INVALID"):
        hold.build_window(daily, CALENDAR, pd.Timestamp("2022-06-30"))
    with pytest.raises(hold.CandidateSkip, match="INSUFFICIENT_BARS"):
        hold.build_window(_daily("2022-06-30", start="2020-01-02"), CALENDAR, pd.Timestamp("2022-06-30"))


def test_public_seal_has_no_mapping_fields():
    seal_path = _ROOT / "docs/patterns/pattern_b/validation/holdout_v02_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    assert not {"ticker", "stock_name", "as_of", "tickers", "label"} & set(seal)
    assert seal["sample_count"] == 36 and seal["unique_ticker_count"] == 36
    assert seal["anchor_years"] == [2020, 2022, 2024, 2026]
    text = seal_path.read_text(encoding="utf-8")
    assert "-06-" not in text


def test_selection_path_does_not_reference_feature_modules():
    source = _SCRIPT.read_text(encoding="utf-8")
    for token in ("pattern_b_features", "trend_scanner.patterns", "human_ground_truth_labels",
                  "feature_raw_values"):
        assert token not in source
