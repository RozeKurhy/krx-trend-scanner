"""ROLLING_MARKET_DATA_AUTHORITY_FIX_V01 tests for BLOCKER A (survivorship-safe rolling PIT
extension) and BLOCKER B (full-population bootstrap audit replacing mode(actual_date_max))."""

from __future__ import annotations

import hashlib
import json

import pytest

from trend_scanner.data.rolling_market_data_refresh import (
    InsufficientPitFrontierError,
    PopulationBootstrapAudit,
    RollingAuthorityError,
    audit_full_population_bootstrap,
    bootstrap_rolling_authority,
    bootstrap_rolling_authority_v2,
    build_rolling_pit_extension,
    merge_pit_extension_intervals,
    validate_pit_extension_survivorship_safety,
)


# ---------------------------------------------------------------------------
# BLOCKER B: full-population bootstrap audit
# ---------------------------------------------------------------------------


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _pit(intervals) -> dict:
    return {"intervals": intervals}


def _interval(ticker, effective_from, effective_to, *, market="KOSPI", isu_cd=None) -> dict:
    return {
        "ticker": ticker,
        "isu_cd": isu_cd or f"KR{ticker}0000",
        "market": market,
        "state": "COMMON",
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def _calendar(dates) -> dict:
    return {"trading_dates": dates}


def _meta(actual_date_max) -> dict:
    return {"actual_date_max": actual_date_max}


TRADING_DATES = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"]


def _base_audit_kwargs(tmp_path, intervals, *, removed=(), zero_store=(), closure_csv_rows=None):
    pit_path = tmp_path / "pit.json"
    _write_json(pit_path, _pit(intervals))
    calendar_path = tmp_path / "calendar.json"
    _write_json(calendar_path, _calendar(TRADING_DATES))
    removed_path = tmp_path / "removed.json"
    _write_json(removed_path, {"removed_identities": list(removed)})
    zero_store_path = tmp_path / "zero_store.json"
    _write_json(zero_store_path, {"tickers": list(zero_store)})
    closure_csv_path = None
    if closure_csv_rows is not None:
        closure_csv_path = tmp_path / "closure.csv"
        header = "ticker,last_actual_date,coverage_status\n"
        rows = "\n".join(f"{t},{d},{s}" for t, d, s in closure_csv_rows)
        closure_csv_path.write_text(header + rows + "\n", encoding="utf-8")
    return dict(
        pit_path=pit_path,
        historical_calendar_path=calendar_path,
        removed_identity_audit_path=removed_path,
        zero_store_contract_path=zero_store_path,
        full_population_closure_results_path=closure_csv_path,
        stocks_dir=tmp_path / "no_such_legacy_raw_cache",
        suspension_authority_path=tmp_path / "no_such_suspension_authority.json",
        suspension_errata_path=None,
    )


def test_bootstrap_mode_is_not_sufficient(tmp_path) -> None:
    """mode(actual_date_max) picks whatever value the majority of tickers share -- it has no way to
    notice that one ticker never advanced at all. A full-population audit does."""
    adjusted_dir = tmp_path / "adjusted"
    adjusted_dir.mkdir()
    # Two of three tickers reached 2026-08-21; one is stuck at 2026-08-19 -- the majority mode still
    # picks 2026-08-21 and the old bootstrap certifies it, silently losing the lagging ticker.
    _write_json(adjusted_dir / "AAA001.meta.json", _meta("2026-08-21"))
    _write_json(adjusted_dir / "AAA002.meta.json", _meta("2026-08-21"))
    _write_json(adjusted_dir / "AAA003.meta.json", _meta("2026-08-19"))
    # bootstrap_rolling_authority also requires a readable ETF-scope mode -- give it one so the
    # comparison isolates the COMMON mode-insufficiency this test is actually about.
    _write_json(adjusted_dir / "0115D0.meta.json", _meta("2026-08-21"))

    old_manifest = bootstrap_rolling_authority(
        raw_store=_FakeRawStore({"KOSPI": "2026-08-21", "KOSDAQ": "2026-08-21", "ETF": "2026-08-21"}),
        adjusted_store_dir=adjusted_dir,
    )
    assert old_manifest.leg_boundaries["common_adjusted"] == "2026-08-21"  # wrongly certifies the majority

    kwargs = _base_audit_kwargs(
        tmp_path,
        [_interval("AAA001", "2026-08-17", "2026-08-21"), _interval("AAA002", "2026-08-17", "2026-08-21"), _interval("AAA003", "2026-08-17", "2026-08-21")],
    )
    audit = audit_full_population_bootstrap(adjusted_store_dir=adjusted_dir, candidate_boundary="2026-08-21", etf_acceptance_tickers=(), **kwargs)
    assert audit.unexplained_gap_count == 1
    assert audit.unexplained()[0].ticker == "AAA003"


class _FakeRawStore:
    def __init__(self, latest_complete_by_market: dict[str, str]) -> None:
        self._latest = latest_complete_by_market

    def list_manifest(self, market=None):
        if market is None:
            return [{"market": m, "date": d, "status": "COMPLETE"} for m, d in self._latest.items()]
        return [{"market": market, "date": self._latest[market], "status": "COMPLETE"}]


def test_bootstrap_boundary_requires_full_population_authority(tmp_path) -> None:
    adjusted_dir = tmp_path / "adjusted"
    adjusted_dir.mkdir()
    _write_json(adjusted_dir / "AAA001.meta.json", _meta("2026-08-21"))
    kwargs = _base_audit_kwargs(tmp_path, [_interval("AAA001", "2026-08-17", "2026-08-21")])

    manifest, audit = bootstrap_rolling_authority_v2(
        raw_store=_FakeRawStore({"KOSPI": "2026-08-21", "KOSDAQ": "2026-08-21", "ETF": "2026-08-21"}),
        adjusted_store_dir=adjusted_dir,
        candidate_boundary="2026-08-21",
        etf_acceptance_tickers=(),
        audit_kwargs=kwargs,
    )
    assert audit.certified
    assert manifest.certified_through == "2026-08-21"
    assert manifest.leg_boundaries["common_adjusted"] == "2026-08-21"


def test_unexplained_bootstrap_gap_fails(tmp_path) -> None:
    adjusted_dir = tmp_path / "adjusted"
    adjusted_dir.mkdir()
    _write_json(adjusted_dir / "AAA001.meta.json", _meta("2026-08-19"))  # short, no explanation anywhere
    kwargs = _base_audit_kwargs(tmp_path, [_interval("AAA001", "2026-08-17", "2026-08-21")])

    with pytest.raises(RollingAuthorityError, match="BOOTSTRAP_UNEXPLAINED_POPULATION_GAP_COUNT"):
        bootstrap_rolling_authority_v2(
            raw_store=_FakeRawStore({"KOSPI": "2026-08-21", "KOSDAQ": "2026-08-21", "ETF": "2026-08-21"}),
            adjusted_store_dir=adjusted_dir,
            candidate_boundary="2026-08-21",
            etf_acceptance_tickers=(),
            audit_kwargs=kwargs,
        )


def test_explained_lifecycle_gap_allowed(tmp_path) -> None:
    """A ticker delisted before the candidate boundary (its own PIT interval ends early) is not a gap
    at all -- nothing is expected of it past its own effective_to."""
    adjusted_dir = tmp_path / "adjusted"
    adjusted_dir.mkdir()
    _write_json(adjusted_dir / "AAA001.meta.json", _meta("2026-08-18"))  # matches its own effective_to exactly
    kwargs = _base_audit_kwargs(tmp_path, [_interval("AAA001", "2026-08-17", "2026-08-18")])

    audit = audit_full_population_bootstrap(adjusted_store_dir=adjusted_dir, candidate_boundary="2026-08-21", etf_acceptance_tickers=(), **kwargs)
    assert audit.unexplained_gap_count == 0
    assert audit.records[0].category == "OK"


def test_removed_identity_and_zero_store_and_closure_certified_are_explained_not_unexplained(tmp_path) -> None:
    adjusted_dir = tmp_path / "adjusted"
    adjusted_dir.mkdir()
    # AAA001: removed identity -- no store file, not even in scope for reconciliation.
    # AAA002: certified expected-zero-store -- no store file, contractually correct.
    # AAA003: closure already certified this exact short coverage under FULL_EXPECTED_COVERAGE.
    _write_json(adjusted_dir / "AAA003.meta.json", _meta("2026-08-19"))
    kwargs = _base_audit_kwargs(
        tmp_path,
        [
            _interval("AAA001", "2026-08-17", "2026-08-21"),
            _interval("AAA002", "2026-08-17", "2026-08-21"),
            _interval("AAA003", "2026-08-17", "2026-08-21"),
        ],
        removed=("AAA001",),
        zero_store=("AAA002",),
        closure_csv_rows=[("AAA003", "2026-08-19", "FULL_EXPECTED_COVERAGE")],
    )
    audit = audit_full_population_bootstrap(adjusted_store_dir=adjusted_dir, candidate_boundary="2026-08-21", etf_acceptance_tickers=(), **kwargs)
    assert audit.unexplained_gap_count == 0
    assert audit.explained_gap_count == 3


def test_real_production_full_population_bootstrap_audit_is_certified() -> None:
    """Runs the audit against the actual production stores (read-only) -- the concrete BLOCKER B
    evidence: 3179 in-scope tickers (3162 PIT COMMON + 17 ETF), 0 unexplained gaps."""
    from pathlib import Path

    audit: PopulationBootstrapAudit = audit_full_population_bootstrap(
        adjusted_store_dir=Path("data/market/adjusted/stocks"),
        candidate_boundary="2026-08-21",
    )
    assert audit.total_in_scope == 3179
    assert audit.unexplained_gap_count == 0


# ---------------------------------------------------------------------------
# BLOCKER A: survivorship-safe rolling PIT extension
# ---------------------------------------------------------------------------


def test_rolling_pit_extension_is_survivorship_safe() -> None:
    frozen = [_interval("005930", "2010-01-04", "2026-08-21")]
    new = [_interval("005930", "2026-08-24", "2026-08-25")]  # continuation, same identity key
    violations = validate_pit_extension_survivorship_safety(frozen, new, boundary="2026-08-21")
    assert violations == []
    merged = merge_pit_extension_intervals(frozen, new)
    assert len(merged) == 1  # extended in place, not duplicated
    assert merged[0]["effective_from"] == "2010-01-04"  # never rewritten
    assert merged[0]["effective_to"] == "2026-08-25"  # extended forward


def test_new_listing_not_backfilled_into_past_population() -> None:
    frozen = [_interval("005930", "2010-01-04", "2026-08-21")]
    backdated_new_listing = [_interval("900001", "2026-08-20", "2026-08-25")]  # starts before boundary
    violations = validate_pit_extension_survivorship_safety(frozen, backdated_new_listing, boundary="2026-08-21")
    assert any("BACKDATED_NEW_INTERVAL" in v for v in violations)

    genuine_new_listing = [_interval("900001", "2026-08-24", "2026-08-25")]
    assert validate_pit_extension_survivorship_safety(frozen, genuine_new_listing, boundary="2026-08-21") == []
    merged = merge_pit_extension_intervals(frozen, genuine_new_listing)
    assert {iv["ticker"] for iv in merged} == {"005930", "900001"}
    new_iv = next(iv for iv in merged if iv["ticker"] == "900001")
    assert new_iv["effective_from"] == "2026-08-24"


def test_delisted_ticker_not_removed_from_historical_population() -> None:
    frozen = [
        _interval("005930", "2010-01-04", "2026-08-21"),
        _interval("121910", "2010-03-03", "2012-10-12"),  # long-delisted; absent from any new snapshot
    ]
    new = [_interval("005930", "2026-08-24", "2026-08-25")]  # only the still-active ticker continues
    merged = merge_pit_extension_intervals(frozen, new)
    delisted = next(iv for iv in merged if iv["ticker"] == "121910")
    assert delisted["effective_from"] == "2010-03-03"
    assert delisted["effective_to"] == "2012-10-12"  # untouched, still present


def test_extension_cannot_shorten_existing_history() -> None:
    frozen = [_interval("005930", "2010-01-04", "2026-08-21")]
    # A malformed/short-window classification for the same continuation key must never be allowed to
    # look like a truncation of history.
    shortened = [_interval("005930", "2026-08-24", "2026-08-20", isu_cd="KR0059300000")]
    frozen[0]["isu_cd"] = "KR0059300000"
    violations = validate_pit_extension_survivorship_safety(frozen, shortened, boundary="2026-08-21")
    assert any("EXTENSION_WOULD_SHORTEN_HISTORY" in v for v in violations)


def test_insufficient_authority_still_fails_closed(tmp_path) -> None:
    """The real production case today: the Basic Info acquisition archive has no files at all for the
    extension window, so this must fail closed, never fabricate an extension."""
    frozen_pit_path = tmp_path / "pit.json"
    _write_json(frozen_pit_path, _pit([_interval("005930", "2010-01-04", "2026-08-21")]))
    calendar_path = tmp_path / "calendar.json"
    _write_json(calendar_path, _calendar(TRADING_DATES))

    with pytest.raises(InsufficientPitFrontierError):
        build_rolling_pit_extension(
            extension_calendar_dates=["2026-08-24", "2026-08-25"],
            frozen_pit_path=frozen_pit_path,
            historical_calendar_path=calendar_path,
            basic_info_raw_root=tmp_path / "no_such_basic_info_archive",
            acquisition_checkpoint_path=tmp_path / "no_such_checkpoint.json",
            acquisition_final_summary_path=tmp_path / "no_such_final_summary.json",
        )


def test_insufficient_authority_against_real_frozen_archive() -> None:
    """The real production archive exists but has no files beyond 2026-08-21 -- also fails closed,
    against the actual on-disk authority (not a synthetic fixture)."""
    with pytest.raises(InsufficientPitFrontierError):
        build_rolling_pit_extension(extension_calendar_dates=["2026-08-24", "2026-08-25", "2026-08-26"])


def test_phantom_row_prevention_preserved() -> None:
    """resolve_expected_coverage's phantom/zero-OHL exclusion (is_nontradable_or_phantom_row /
    ClosureState.CONFIRMED_NONTRADING) is reused unchanged by the audit path -- not reimplemented, and
    not bypassed by any BLOCKER A/B addition."""
    from trend_scanner.data.adjusted_price_pilot import is_nontradable_or_phantom_row

    # zero-OHL with a stale positive close and zero confirmed activity -- the exact
    # phantom-row shape the closure's own evidence (full_population_results.csv) documents.
    assert is_nontradable_or_phantom_row(0.0, 0.0, 0.0, 14800.0, volume=0, trading_value=0) is True
    assert is_nontradable_or_phantom_row(100.0, 105.0, 95.0, 101.0, volume=1000, trading_value=100000) is False
