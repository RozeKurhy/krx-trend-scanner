from __future__ import annotations

import pytest

from trend_scanner.data.corporate_action_detector import (
    CorporateActionDetector,
    CorporateActionSnapshot,
    LISTED_SHARES_AND_PAR_VALUE_CHANGED,
    LISTED_SHARES_CHANGED,
    PAR_VALUE_CHANGED,
)
from trend_scanner.data.errors import MarketDataError


def _snapshot(
    as_of: str,
    listed_shares: int = 100,
    par_value: int | None = 5000,
) -> CorporateActionSnapshot:
    return CorporateActionSnapshot("005930", as_of, listed_shares, par_value)


def test_same_values_are_clean():
    decision = CorporateActionDetector().evaluate(_snapshot("2024-01-01"), _snapshot("2024-01-02"))
    assert decision.is_dirty is False
    assert decision.dirty_reasons == ()


def test_listed_shares_change_is_dirty():
    decision = CorporateActionDetector().evaluate(_snapshot("2024-01-01"), _snapshot("2024-01-02", 101))
    assert decision.is_dirty is True
    assert decision.dirty_reasons == (LISTED_SHARES_CHANGED,)
    assert decision.listed_shares_ratio == pytest.approx(1.01)


def test_par_value_change_is_dirty():
    decision = CorporateActionDetector().evaluate(_snapshot("2024-01-01"), _snapshot("2024-01-02", 100, 100))
    assert decision.is_dirty is True
    assert decision.dirty_reasons == (PAR_VALUE_CHANGED,)
    assert decision.par_value_ratio == pytest.approx(0.02)


def test_both_authority_values_change_is_dirty_without_event_classification():
    decision = CorporateActionDetector().evaluate(
        _snapshot("2018-04-27", 128_386_494, 5000),
        _snapshot("2018-05-04", 6_419_324_700, 100),
    )
    assert decision.is_dirty is True
    assert decision.dirty_reasons == (LISTED_SHARES_AND_PAR_VALUE_CHANGED,)
    assert not hasattr(decision, "corporate_action_type")


def test_missing_par_value_does_not_create_false_dirty():
    detector = CorporateActionDetector()
    assert detector.evaluate(_snapshot("2024-01-01", 100, None), _snapshot("2024-01-02", 100, 5000)).is_dirty is False
    decision = detector.evaluate(_snapshot("2024-01-01", 100, None), _snapshot("2024-01-02", 101, None))
    assert decision.is_dirty is True
    assert decision.dirty_reasons == (LISTED_SHARES_CHANGED,)


def test_initial_snapshot_is_clean_baseline():
    decision = CorporateActionDetector().evaluate(None, _snapshot("2024-01-01"))
    assert decision.is_dirty is False
    assert decision.previous_as_of is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"listed_shares": 0},
        {"listed_shares": -1},
        {"listed_shares": "not-a-number"},
        {"par_value": -1},
        {"par_value": "not-a-number"},
        {"as_of": "not-a-date"},
    ],
)
def test_invalid_snapshot_fails_closed(kwargs):
    values = {"as_of": "2024-01-01", "listed_shares": 100, "par_value": 5000}
    values.update(kwargs)
    with pytest.raises(MarketDataError):
        CorporateActionSnapshot("005930", **values)


def test_reverse_dates_fail_closed():
    with pytest.raises(MarketDataError, match="OUT_OF_ORDER"):
        CorporateActionDetector().evaluate(_snapshot("2024-01-02"), _snapshot("2024-01-01"))


def test_same_date_conflicting_values_fail_closed():
    with pytest.raises(MarketDataError, match="SOURCE_CONFLICT"):
        CorporateActionDetector().evaluate(_snapshot("2024-01-01"), _snapshot("2024-01-01", 101))


def test_different_tickers_fail_closed():
    with pytest.raises(MarketDataError):
        CorporateActionDetector().evaluate(
            _snapshot("2024-01-01"),
            CorporateActionSnapshot("000660", "2024-01-02", 100, 5000),
        )
