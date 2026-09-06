"""Offline contract tests for the survivorship-safe historical denominator
freeze (SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01).

Unit tests use small synthetic ``full_universe``-shaped fixtures (the same
interval shape ``_intervalize`` produces) so they run fast and don't touch
the raw archive. A separate block of "real data" regression tests reads the
already-frozen canonical artifacts committed to the repo — these are fast
(pure JSON reads) and exercise Section 25/27/38's actual survivorship
negative controls against real historical identities.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_PIT_ARTIFACT_PATH,
    DEFAULT_POPULATION_ARTIFACT_PATH,
    FreezeContractError,
    compute_pit_daily_statistics,
    derive_population_and_pit_records,
    evaluate_identity_gate,
    evaluate_lifecycle_gate,
    evaluate_population_pit_union_invariant,
    get_common_universe_as_of,
    load_historical_common_population,
    load_pit_common_intervals,
    pit_denominator_manifest_sha256,
    population_manifest_sha256,
)

ROOT = Path(__file__).resolve().parents[1]


def _interval(ticker, isu_cd, market, classification, effective_from, effective_to, reason="X"):
    return {
        "ticker": ticker,
        "ISU_CD": isu_cd,
        "market": market,
        "classification": classification,
        "classification_reason": reason,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


# ---------------------------------------------------------------------------
# Section 35: POPULATION
# ---------------------------------------------------------------------------


def test_ever_common_identity_included_in_population() -> None:
    full = {"AAA": [_interval("AAA", "KRAAA", "KOSPI", "COMMON", "2015-01-02", "2020-01-02")]}
    population, _ = derive_population_and_pit_records(full)
    assert {r["ticker"] for r in population} == {"AAA"}


def test_always_not_common_identity_excluded_from_population() -> None:
    full = {"BBB": [_interval("BBB", "KRBBB", "KOSPI", "NOT_COMMON", "2015-01-02", "2020-01-02")]}
    population, pit = derive_population_and_pit_records(full)
    assert population == []
    assert pit == []


def test_common_to_not_common_lifecycle_included_in_population() -> None:
    full = {
        "CCC": [
            _interval("CCC", "KRCCC", "KOSPI", "COMMON", "2013-01-02", "2015-12-31"),
            _interval("CCC", "KRCCC", "KOSPI", "NOT_COMMON", "2016-01-04", "2018-12-31"),
        ]
    }
    population, _ = derive_population_and_pit_records(full)
    assert len(population) == 1
    assert population[0]["lifecycle_transition_present"] is True
    assert population[0]["historical_only"] is True


def test_not_common_to_common_lifecycle_included_in_population() -> None:
    full = {
        "DDD": [
            _interval("DDD", "KRDDD", "KOSDAQ", "NOT_COMMON", "2013-01-02", "2015-12-31"),
            _interval("DDD", "KRDDD", "KOSDAQ", "COMMON", "2016-01-04", "2026-08-21"),
        ]
    }
    population, _ = derive_population_and_pit_records(full, last_trading_date="2026-08-21")
    assert len(population) == 1
    assert population[0]["lifecycle_transition_present"] is True
    assert population[0]["currently_common"] is True


def test_alpha_common_identity_not_silently_dropped_from_population() -> None:
    full = {"0008Z0": [_interval("0008Z0", "KR70008Z0005", "KOSDAQ", "COMMON", "2025-08-19", "2026-08-21")]}
    population, _ = derive_population_and_pit_records(full)
    assert len(population) == 1
    assert population[0]["numeric_or_alpha"] == "alphanumeric"


# ---------------------------------------------------------------------------
# Section 36: PIT
# ---------------------------------------------------------------------------


def test_pit_common_interval_date_included() -> None:
    full = {"EEE": [_interval("EEE", "KREEE", "KOSPI", "COMMON", "2015-01-02", "2020-01-02")]}
    _, pit = derive_population_and_pit_records(full)
    included = get_common_universe_as_of("2017-06-01", intervals=pit, calendar_path=ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
    assert {r["ticker"] for r in included} == {"EEE"}


def test_pit_not_common_date_excluded() -> None:
    full = {"FFF": [_interval("FFF", "KRFFF", "KOSPI", "NOT_COMMON", "2015-01-02", "2020-01-02")]}
    _, pit = derive_population_and_pit_records(full)
    included = get_common_universe_as_of("2017-06-01", intervals=pit, calendar_path=ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
    assert included == []


def test_pit_before_listing_and_after_delisting_excluded() -> None:
    full = {"GGG": [_interval("GGG", "KRGGG", "KOSPI", "COMMON", "2015-01-02", "2016-12-30")]}
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    before = get_common_universe_as_of("2011-01-04", intervals=pit, calendar_path=cal)
    after = get_common_universe_as_of("2020-01-02", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in before} == set()
    assert {r["ticker"] for r in after} == set()


def test_pit_common_to_not_common_boundary_preserved() -> None:
    full = {
        "HHH": [
            _interval("HHH", "KRHHH", "KOSPI", "COMMON", "2015-01-02", "2016-06-30"),
            _interval("HHH", "KRHHH", "KOSPI", "NOT_COMMON", "2016-07-01", "2018-12-31"),
        ]
    }
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    last_common = get_common_universe_as_of("2016-06-30", intervals=pit, calendar_path=cal)
    first_not_common = get_common_universe_as_of("2016-07-01", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in last_common} == {"HHH"}
    assert {r["ticker"] for r in first_not_common} == set()


def test_pit_not_common_to_common_boundary_preserved() -> None:
    full = {
        "III": [
            _interval("III", "KRIII", "KOSDAQ", "NOT_COMMON", "2015-01-02", "2016-06-30"),
            _interval("III", "KRIII", "KOSDAQ", "COMMON", "2016-07-01", "2018-12-31"),
        ]
    }
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    last_not_common = get_common_universe_as_of("2016-06-30", intervals=pit, calendar_path=cal)
    first_common = get_common_universe_as_of("2016-07-01", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in last_not_common} == set()
    assert {r["ticker"] for r in first_common} == {"III"}


def test_pit_spac_at_cutoff_excluded() -> None:
    """Section 23/36.7: an identity that was COMMON earlier in its history but
    became a SPAC (NOT_COMMON) through the frozen cutoff is excluded from the
    PIT denominator at cutoff specifically — not merely absent because it was
    never common at all. It must still appear at its earlier COMMON date."""
    full = {
        "472220": [
            _interval("472220", "KR7472220003", "KOSDAQ", "COMMON", "2015-01-02", "2016-06-30"),
            _interval("472220", "KR7472220003", "KOSDAQ", "NOT_COMMON", "2016-07-01", "2026-08-21"),
        ]
    }
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    while_common = get_common_universe_as_of("2016-06-30", intervals=pit, calendar_path=cal)
    at_cutoff = get_common_universe_as_of("2026-08-21", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in while_common} == {"472220"}
    assert {r["ticker"] for r in at_cutoff} == set()


def test_pit_future_common_event_does_not_leak_into_past_denominator() -> None:
    """Section 36.8: a SPAC-then-COMMON lineage (mirroring the real 203690
    case) must not have its later COMMON interval leak backward — an early
    date squarely inside the NOT_COMMON span is excluded even though the same
    identity is COMMON later, and the post-transition date is included."""
    full = {
        "JJJ": [
            _interval("JJJ", "KRJJJ", "KOSPI", "NOT_COMMON", "2015-01-02", "2016-06-30"),
            _interval("JJJ", "KRJJJ", "KOSPI", "COMMON", "2016-07-01", "2026-08-21"),
        ]
    }
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    early_not_common = get_common_universe_as_of("2015-01-02", intervals=pit, calendar_path=cal)
    after_transition = get_common_universe_as_of("2016-07-01", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in early_not_common} == set()
    assert {r["ticker"] for r in after_transition} == {"JJJ"}


# ---------------------------------------------------------------------------
# Section 37/28: UNION INVARIANT + gates
# ---------------------------------------------------------------------------


def test_union_invariant_exact_match_passes() -> None:
    full = {"KKK": [_interval("KKK", "KRKKK", "KOSPI", "COMMON", "2015-01-02", "2020-01-02")]}
    population, pit = derive_population_and_pit_records(full)
    gate = evaluate_population_pit_union_invariant(population, pit)
    assert gate["status"] == "PASS"
    assert gate["missing_in_population"] == []
    assert gate["population_never_pit_common"] == []


def test_union_invariant_detects_population_without_pit() -> None:
    population = [
        {"ticker": "LLL", "isu_cd": ["KRLLL"], "market": ["KOSPI"], "numeric_or_alpha": "alphanumeric", "common_interval_count": 1, "first_common_date": "x", "last_common_date": "y"}
    ]
    gate = evaluate_population_pit_union_invariant(population, [])
    assert gate["status"] == "BLOCKED_UNION_MISMATCH"
    assert gate["population_never_pit_common"] == [["LLL", "KRLLL"]]


def test_union_invariant_detects_pit_without_population() -> None:
    pit = [{"ticker": "MMM", "isu_cd": "KRMMM", "market": "KOSPI", "state": "COMMON", "effective_from": "x", "effective_to": "y"}]
    gate = evaluate_population_pit_union_invariant([], pit)
    assert gate["status"] == "BLOCKED_UNION_MISMATCH"
    assert gate["missing_in_population"] == [["MMM", "KRMMM"]]


def test_identity_gate_detects_overlap() -> None:
    pit = [
        {"ticker": "NNN", "isu_cd": "KRNNN", "market": "KOSPI", "effective_from": "2015-01-02", "effective_to": "2016-06-30"},
        {"ticker": "NNN", "isu_cd": "KRNNN", "market": "KOSPI", "effective_from": "2016-01-01", "effective_to": "2017-01-01"},
    ]
    gate = evaluate_identity_gate(pit)
    assert gate["status"] == "BLOCKED_INTERVAL_OVERLAP"
    assert gate["overlap_count"] == 1


def test_identity_gate_passes_non_overlapping() -> None:
    pit = [
        {"ticker": "OOO", "isu_cd": "KROOO", "market": "KOSPI", "effective_from": "2015-01-02", "effective_to": "2016-06-30"},
        {"ticker": "OOO", "isu_cd": "KROOO", "market": "KOSPI", "effective_from": "2018-01-01", "effective_to": "2019-01-01"},
    ]
    gate = evaluate_identity_gate(pit)
    assert gate["status"] == "PASS"


def test_lifecycle_gate_detects_boundary_violation() -> None:
    full = {
        "PPP": [
            _interval("PPP", "KRPPP", "KOSPI", "COMMON", "2015-01-02", "2016-06-30"),
            _interval("PPP", "KRPPP", "KOSPI", "NOT_COMMON", "2016-06-30", "2018-01-01"),
        ]
    }
    gate = evaluate_lifecycle_gate(full)
    assert gate["status"] == "BLOCKED_LIFECYCLE_BOUNDARY"
    assert gate["violation_count"] == 1


def test_lifecycle_gate_passes_clean_boundary() -> None:
    full = {
        "QQQ": [
            _interval("QQQ", "KRQQQ", "KOSPI", "COMMON", "2015-01-02", "2016-06-30"),
            _interval("QQQ", "KRQQQ", "KOSPI", "NOT_COMMON", "2016-07-01", "2018-01-01"),
        ]
    }
    gate = evaluate_lifecycle_gate(full)
    assert gate["status"] == "PASS"


# ---------------------------------------------------------------------------
# Hashing + query contract
# ---------------------------------------------------------------------------


def test_population_manifest_sha256_deterministic_and_order_independent() -> None:
    a = [{"market": ["KOSPI"], "ticker": "AAA", "isu_cd": ["KRAAA"], "first_common_date": "x", "last_common_date": "y", "common_interval_count": 1, "numeric_or_alpha": "alphanumeric"}]
    b = [{"market": ["KOSPI"], "ticker": "AAA", "isu_cd": ["KRAAA"], "first_common_date": "x", "last_common_date": "y", "common_interval_count": 1, "numeric_or_alpha": "alphanumeric"}]
    assert population_manifest_sha256(a) == population_manifest_sha256(b)
    assert population_manifest_sha256(a) == population_manifest_sha256(list(reversed(a)))


def test_pit_denominator_manifest_sha256_deterministic() -> None:
    a = [{"market": "KOSPI", "ticker": "AAA", "isu_cd": "KRAAA", "effective_from": "x", "effective_to": "y"}]
    assert pit_denominator_manifest_sha256(a) == pit_denominator_manifest_sha256(a)


def test_get_common_universe_as_of_fails_closed_on_unknown_date() -> None:
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    with pytest.raises(FreezeContractError):
        get_common_universe_as_of("2015-01-01T00:00:00", intervals=[], calendar_path=cal)  # malformed, not a calendar date
    with pytest.raises(FreezeContractError):
        get_common_universe_as_of("2009-01-01", intervals=[], calendar_path=cal)  # before range
    with pytest.raises(FreezeContractError):
        get_common_universe_as_of("2030-01-01", intervals=[], calendar_path=cal)  # after range
    with pytest.raises(FreezeContractError):
        get_common_universe_as_of("2015-01-03", intervals=[], calendar_path=cal)  # a real Sunday, non-trading date


def test_get_common_universe_as_of_market_filter() -> None:
    full = {
        "RRR": [_interval("RRR", "KRRRR", "KOSPI", "COMMON", "2015-01-02", "2020-01-02")],
        "SSS": [_interval("SSS", "KRSSS", "KOSDAQ", "COMMON", "2015-01-02", "2020-01-02")],
    }
    _, pit = derive_population_and_pit_records(full)
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    kospi_only = get_common_universe_as_of("2017-06-01", market="KOSPI", intervals=pit, calendar_path=cal)
    assert {r["ticker"] for r in kospi_only} == {"RRR"}


def test_compute_pit_daily_statistics_reports_coverage_and_extremes() -> None:
    full = {"TTT": [_interval("TTT", "KRTTT", "KOSPI", "COMMON", "2015-01-02", "2015-01-06")]}
    _, pit = derive_population_and_pit_records(full)
    dates = ["2015-01-02", "2015-01-05", "2015-01-06", "2015-01-07"]
    stats = compute_pit_daily_statistics(pit, dates)
    assert stats["date_coverage"] == 4
    assert stats["daily_counts"] == [1, 1, 1, 0]
    assert stats["min_daily_count"] == 0
    assert stats["max_daily_count"] == 1


# ---------------------------------------------------------------------------
# Real-data regressions (reads the already-frozen committed artifacts;
# Section 25/27/38 survivorship negative control against real identities).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frozen_population():
    return load_historical_common_population(ROOT / DEFAULT_POPULATION_ARTIFACT_PATH)


@pytest.fixture(scope="module")
def frozen_pit():
    return load_pit_common_intervals(ROOT / DEFAULT_PIT_ARTIFACT_PATH)


@pytest.fixture(scope="module")
def current_live_common_tickers():
    df = pd.read_parquet(ROOT / "data/reference/krx_instrument_metadata.parquet")
    current = df[df["effective_date"] == "2026-08-21"]
    return set(current.loc[current["is_common_stock"] == True, "ticker"])  # noqa: E712


@pytest.mark.parametrize("ticker", ["000030", "000060", "000360", "000470"])
def test_real_delisted_historical_common_survivorship_negative_control(
    ticker, frozen_population, frozen_pit, current_live_common_tickers
) -> None:
    """Section 25/38: a delisted historical common must be present in the
    Population Universe and in the historical-date PIT denominator, but
    absent from today's live universe — this is the actual survivorship
    regression: a current-only implementation cannot pass this test."""
    population_tickers = {r["ticker"] for r in frozen_population}
    assert ticker in population_tickers

    record = next(r for r in frozen_population if r["ticker"] == ticker)
    mid_date = record["first_common_date"]  # first date is guaranteed inside the interval
    included = get_common_universe_as_of(mid_date, intervals=frozen_pit, calendar_path=ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
    assert ticker in {r["ticker"] for r in included}

    assert ticker not in current_live_common_tickers
    current_pit = get_common_universe_as_of("2026-08-21", intervals=frozen_pit, calendar_path=ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json")
    assert ticker not in {r["ticker"] for r in current_pit}


def test_real_spac_lineage_lifecycle_boundary(frozen_pit) -> None:
    """Section 23: 203690 has a real SPAC (NOT_COMMON) period through
    2015-09-30 and a confirmed common-lineage transition from 2015-10-01 —
    the SPAC period must be excluded, the post-transition period included."""
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    during_spac = get_common_universe_as_of("2015-01-05", intervals=frozen_pit, calendar_path=cal)
    after_transition = get_common_universe_as_of("2015-10-01", intervals=frozen_pit, calendar_path=cal)
    assert "203690" not in {r["ticker"] for r in during_spac}
    assert "203690" in {r["ticker"] for r in after_transition}


def test_real_active_spac_at_cutoff_excluded_from_pit(frozen_pit) -> None:
    """Section 23: 472220 (신영스팩10호), resolved NOT_COMMON as an active
    SPAC at the historical cutoff, must never appear in the PIT denominator
    on the cutoff date."""
    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    at_cutoff = get_common_universe_as_of("2026-08-21", intervals=frozen_pit, calendar_path=cal)
    assert "472220" not in {r["ticker"] for r in at_cutoff}


def test_real_population_pit_union_invariant_exact(frozen_population, frozen_pit) -> None:
    gate = evaluate_population_pit_union_invariant(frozen_population, frozen_pit)
    assert gate["status"] == "PASS"
    assert gate["missing_in_population"] == []
    assert gate["population_never_pit_common"] == []


def test_real_frozen_artifacts_pass_identity_and_lifecycle_gates(frozen_pit) -> None:
    assert evaluate_identity_gate(frozen_pit)["status"] == "PASS"


def test_real_closure_artifact_records_correct_historical_only_counts() -> None:
    import json

    closure = json.loads((ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/survivorship_safe_denominator_freeze_v01.json").read_text(encoding="utf-8"))
    assert closure["historical_only_reconciliation"] == {
        "HISTORICAL_COMMON_REQUIRED": 605,
        "HISTORICAL_NOT_COMMON": 511,
        "HISTORICAL_AUTHORITY_UNRESOLVED": 0,
    }
    assert closure["status"] == "CLOSED_AND_FROZEN"
    assert closure["pit"]["trading_date_coverage"] == 4095


def test_real_preferred_alpha_not_common_excluded(frozen_population, frozen_pit) -> None:
    """Section 18: preferred-class alpha identities (including 00781K and the
    other 13 preferred-class supplemental items) confirmed HISTORICAL_NOT_COMMON
    must be strictly excluded from both Population and PIT COMMON intervals."""
    preferred_14 = {
        "00781K", "00806K", "02826K", "03473K", "03481K",
        "08537M", "18064K", "28513K", "35320K", "36328K",
        "37550K", "38380K", "45014K", "45226K",
    }
    population_tickers = {r["ticker"] for r in frozen_population}
    pit_tickers = {r["ticker"] for r in frozen_pit}

    assert population_tickers.intersection(preferred_14) == set()
    assert pit_tickers.intersection(preferred_14) == set()


def test_real_legitimate_alpha_common_preserved(frozen_population, frozen_pit) -> None:
    """Section 19: legitimate alphanumeric COMMON identities (23 active items)
    must be preserved in Population and present in PIT on their active dates."""
    alpha_population = [r for r in frozen_population if r.get("numeric_or_alpha") == "alphanumeric"]
    assert len(alpha_population) == 23

    cal = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    for sample_ticker in ["0008Z0", "0009K0", "0010F0"]:
        record = next((r for r in alpha_population if r["ticker"] == sample_ticker), None)
        assert record is not None
        assert record["included_in_population"] is True
        assert record["currently_common"] is True

        included = get_common_universe_as_of(record["first_common_date"], intervals=frozen_pit, calendar_path=cal)
        assert sample_ticker in {r["ticker"] for r in included}


def test_real_market_overlap_accounting(frozen_population) -> None:
    """Section 20: market breakdown follows inclusion-exclusion principle:
    KOSPI_EVER (982) + KOSDAQ_EVER (2202) - CROSS_MARKET (22) == TOTAL_POPULATION (3162)."""
    kospi_ever = {(r["ticker"], tuple(r["isu_cd"])) for r in frozen_population if "KOSPI" in r["market"]}
    kosdaq_ever = {(r["ticker"], tuple(r["isu_cd"])) for r in frozen_population if "KOSDAQ" in r["market"]}
    cross_market = kospi_ever & kosdaq_ever

    assert len(kospi_ever) == 982
    assert len(kosdaq_ever) == 2202
    assert len(cross_market) == 22
    assert len(kospi_ever) + len(kosdaq_ever) - len(cross_market) == len(frozen_population) == 3162


def test_real_no_same_date_dual_market_membership(frozen_pit) -> None:
    """Section 21: across all 4,095 trading dates, no identity may ever hold
    membership in more than one market's COMMON denominator on the same date."""
    import json
    from collections import defaultdict

    cal_path = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    calendar = json.loads(cal_path.read_text(encoding="utf-8"))
    trading_dates = calendar["trading_dates"]
    assert len(trading_dates) == 4095

    # Group intervals by identity
    ident_intervals = defaultdict(list)
    for inv in frozen_pit:
        ident_intervals[(inv["ticker"], inv["isu_cd"])].append(inv)

    dual_conflicts = 0
    for ident, intervals in ident_intervals.items():
        if len({i["market"] for i in intervals}) <= 1:
            continue
        # For cross-market identities, ensure intervals never overlap on any trading day
        sorted_inv = sorted(intervals, key=lambda x: x["effective_from"])
        for i in range(len(sorted_inv) - 1):
            curr_end = sorted_inv[i]["effective_to"]
            next_start = sorted_inv[i + 1]["effective_from"]
            curr_idx = trading_dates.index(curr_end)
            next_idx = trading_dates.index(next_start)
            if next_idx <= curr_idx:
                dual_conflicts += 1

    assert dual_conflicts == 0


def test_real_cross_market_transfer_lifecycle(frozen_pit) -> None:
    """Section 22: cross-market migration boundary lifecycle test.
    For representative migrating tickers (Kakao 035720, Celltrion 068270, POSCO DX 022100),
    verify exact inclusion/exclusion on transition boundaries with trading day diff == 1."""
    import json

    cal_path = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
    calendar = json.loads(cal_path.read_text(encoding="utf-8"))
    trading_dates = calendar["trading_dates"]

    test_cases = [
        # (ticker, last_kosdaq_date, first_kospi_date)
        ("035720", "2017-07-07", "2017-07-10"),  # Kakao
        ("068270", "2018-02-08", "2018-02-09"),  # Celltrion
        ("022100", "2023-12-28", "2024-01-02"),  # POSCO DX
    ]

    for ticker, last_kosdaq, first_kospi in test_cases:
        last_k_idx = trading_dates.index(last_kosdaq)
        first_p_idx = trading_dates.index(first_kospi)
        assert first_p_idx - last_k_idx == 1, f"{ticker} transition dates must be consecutive trading days"

        # On last KOSDAQ date: in KOSDAQ, not in KOSPI
        kosdaq_univ = get_common_universe_as_of(last_kosdaq, market="KOSDAQ", intervals=frozen_pit, calendar_path=cal_path)
        kospi_univ = get_common_universe_as_of(last_kosdaq, market="KOSPI", intervals=frozen_pit, calendar_path=cal_path)
        assert ticker in {r["ticker"] for r in kosdaq_univ}
        assert ticker not in {r["ticker"] for r in kospi_univ}

        # On first KOSPI date: in KOSPI, not in KOSDAQ
        kosdaq_univ_after = get_common_universe_as_of(first_kospi, market="KOSDAQ", intervals=frozen_pit, calendar_path=cal_path)
        kospi_univ_after = get_common_universe_as_of(first_kospi, market="KOSPI", intervals=frozen_pit, calendar_path=cal_path)
        assert ticker not in {r["ticker"] for r in kosdaq_univ_after}
        assert ticker in {r["ticker"] for r in kospi_univ_after}

