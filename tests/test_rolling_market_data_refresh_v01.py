"""Focused tests for the rolling market-data refresh path (directive ROLLING_MARKET_DATA_REFRESH_PATH_V01).

No live network calls anywhere in this file -- KrxOpenApiClient/NaverDirectAdjustedPriceDataProvider
are always constructed with a fake opener/session, or the higher-level updater classes are exercised
directly against tmp_path stores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    InsufficientPitFrontierError,
    RollingAuthorityError,
    RollingAuthorityManifest,
    RollingEtfAdjustedUpdater,
    RollingRawEtfUpdater,
    RollingRawMarketUpdater,
    RollingRefreshCoordinator,
    bootstrap_rolling_authority,
    count_rows_after,
    history_fingerprint,
    load_rolling_authority,
    write_rolling_authority,
)


ROOT = Path(__file__).resolve().parents[1]
ROLLING_MODULE_PATH = ROOT / "src/trend_scanner/data/rolling_market_data_refresh.py"
ROLLING_SCRIPTS = (
    ROOT / "scripts/refresh_market_data_v01.py",
    ROOT / "scripts/backfill_krx_raw_etf_v01.py",
)


def _raw_frame(ticker: str, day: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [day],
            "ticker": [ticker],
            "open": [100], "high": [110], "low": [90], "close": [105],
            "volume": [1000], "trading_value": [100000],
            "market_cap": [1_000_000], "listed_shares": [10_000],
        }
    )


def _seed_raw_store(root: Path, *, dates: list[str], markets: tuple[str, ...] = ("KOSPI", "KOSDAQ", "ETF")) -> KrxRawStockStore:
    store = KrxRawStockStore(root)
    for day in dates:
        for market in markets:
            ticker = "005930" if market != "ETF" else "069500"
            store.save_snapshot(market, day, _raw_frame(ticker, day), f"/{market}")
    return store


def _adjusted_frame(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {"open": [100.0] * len(index), "high": [105.0] * len(index), "low": [95.0] * len(index), "close": [102.0] * len(index)},
        index=index,
    )


def _seed_adjusted_store(root: Path, tickers: list[str], *, start: str, end: str) -> AdjustedPriceStore:
    store = AdjustedPriceStore(root)
    for ticker in tickers:
        store.save_full(ticker, _adjusted_frame(start, end), {"requested_start": start, "requested_end": end})
    return store


# ---------------------------------------------------------------------------
# PyKRX zero-use guard (directive section 35)
# ---------------------------------------------------------------------------


def test_pykrx_zero_use_guard_in_rolling_source() -> None:
    for path in (ROLLING_MODULE_PATH, *ROLLING_SCRIPTS):
        source = path.read_text(encoding="utf-8").lower()
        assert "pykrx" not in source, f"{path} must not reference pykrx"


# ---------------------------------------------------------------------------
# Authority manifest validation / checkpoint mismatch fail-closed
# ---------------------------------------------------------------------------


def _manifest(certified_through: str = "2026-08-21", **overrides) -> RollingAuthorityManifest:
    leg_boundaries = overrides.pop("leg_boundaries", {leg: certified_through for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")})
    defaults = dict(
        authority_version="ROLLING_MARKET_DATA_V01",
        certified_through=min(leg_boundaries.values()),
        leg_boundaries=leg_boundaries,
        previous_boundary=None,
        raw_store_version="KRX_RAW_STOCK_V01",
        adjusted_store_version="ADJUSTED_PRICE_STORE_V02",
        instrument_contract_version="REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
        bootstrap_source=None,
        generated_at="2026-09-05T00:00:00+00:00",
    )
    defaults.update(overrides)
    return RollingAuthorityManifest(**defaults).with_digest()


def test_manifest_roundtrip(tmp_path) -> None:
    write_rolling_authority(_manifest(), tmp_path)
    loaded = load_rolling_authority(tmp_path)
    assert loaded.certified_through == "2026-08-21"
    assert loaded.leg_boundaries["common_adjusted"] == "2026-08-21"


def test_manifest_checksum_mismatch_fails_closed(tmp_path) -> None:
    write_rolling_authority(_manifest(), tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    payload["certified_through"] = "2099-01-01"  # tamper without recomputing the digest
    path.write_text(json.dumps(payload))
    with pytest.raises(RollingAuthorityError, match="CHECKSUM_MISMATCH"):
        load_rolling_authority(tmp_path)


def test_write_rejects_wrong_authority_version(tmp_path) -> None:
    bad = _manifest()
    object.__setattr__(bad, "authority_version", "SOME_OTHER_VERSION")
    with pytest.raises(RollingAuthorityError, match="AUTHORITY_VERSION_MISMATCH"):
        write_rolling_authority(bad, tmp_path)


def test_load_rejects_wrong_authority_version_written_out_of_band(tmp_path) -> None:
    write_rolling_authority(_manifest(), tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    payload["authority_version"] = "SOME_OTHER_VERSION"
    import hashlib
    canonical = {k: v for k, v in payload.items() if k != "manifest_sha256"}
    payload["manifest_sha256"] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path.write_text(json.dumps(payload))
    with pytest.raises(RollingAuthorityError, match="AUTHORITY_VERSION_MISMATCH"):
        load_rolling_authority(tmp_path)


def test_manifest_incoherent_certified_through_fails_closed(tmp_path) -> None:
    write_rolling_authority(_manifest(), tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    payload["leg_boundaries"]["common_adjusted"] = "2026-08-01"  # now min(legs) != certified_through
    # keep certified_through stale and recompute digest so the checksum itself is internally
    # consistent -- this must still fail on the *coherence* check, independent of the digest guard.
    import hashlib
    canonical = {k: v for k, v in payload.items() if k != "manifest_sha256"}
    payload["manifest_sha256"] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path.write_text(json.dumps(payload))
    with pytest.raises(RollingAuthorityError, match="CERTIFIED_THROUGH_INCOHERENT"):
        load_rolling_authority(tmp_path)


def test_missing_manifest_fails_closed(tmp_path) -> None:
    with pytest.raises(RollingAuthorityError, match="ROLLING_MANIFEST_MISSING"):
        load_rolling_authority(tmp_path / "nowhere")


# ---------------------------------------------------------------------------
# Bootstrap (directive sections 43-44)
# ---------------------------------------------------------------------------


def test_bootstrap_derives_boundary_from_observed_state_not_a_literal(tmp_path) -> None:
    raw_store = _seed_raw_store(tmp_path / "raw", dates=["2026-08-20", "2026-08-21"])
    adjusted_dir = tmp_path / "adjusted"
    _seed_adjusted_store(adjusted_dir, ["005930", *ETF_VALIDATED_ACCEPTANCE_TICKERS], start="2026-08-01", end="2026-08-21")
    evidence_path = tmp_path / "closure_decision.json"
    evidence_path.write_text(json.dumps({"verdict": "ACCEPT", "next_state": "CLOSED"}))

    manifest = bootstrap_rolling_authority(
        raw_store=raw_store,
        adjusted_store_dir=adjusted_dir,
        closure_evidence=[("full_population_closure", evidence_path)],
    )
    assert manifest.certified_through == "2026-08-21"
    assert manifest.leg_boundaries["common_raw"] == "2026-08-21"
    assert manifest.leg_boundaries["etf_raw"] == "2026-08-21"
    assert manifest.bootstrap_source["evidence"][0]["content"]["verdict"] == "ACCEPT"


def test_bootstrap_fails_closed_on_missing_evidence(tmp_path) -> None:
    raw_store = _seed_raw_store(tmp_path / "raw", dates=["2026-08-21"])
    adjusted_dir = tmp_path / "adjusted"
    _seed_adjusted_store(adjusted_dir, ["005930", *ETF_VALIDATED_ACCEPTANCE_TICKERS], start="2026-08-01", end="2026-08-21")
    with pytest.raises(RollingAuthorityError, match="BOOTSTRAP_EVIDENCE_MISSING"):
        bootstrap_rolling_authority(
            raw_store=raw_store,
            adjusted_store_dir=adjusted_dir,
            closure_evidence=[("missing", tmp_path / "does_not_exist.json")],
        )


# ---------------------------------------------------------------------------
# ETF raw/adjusted separation (directive sections 18-20)
# ---------------------------------------------------------------------------


def test_etf_raw_updater_has_no_adjusted_dependency(tmp_path) -> None:
    raw_store = _seed_raw_store(tmp_path / "raw", dates=["2026-08-21"], markets=("KOSPI",))
    updater = RollingRawEtfUpdater(provider=None, raw_store=raw_store)  # provider unused by plan()
    plan = updater.plan("2026-08-21", "2026-08-24")
    assert plan["start"] == "2026-08-22"
    assert "adjusted" not in json.dumps(plan)


def test_etf_adjusted_updater_never_expands_beyond_validated_scope() -> None:
    class _StubProvider:
        def load_daily(self, ticker, start, end):
            return _adjusted_frame(start, end)

    calls: list[str] = []

    class _StubStore:
        def save_full(self, ticker, frame, metadata_context=None):
            calls.append(ticker)

    updater = RollingEtfAdjustedUpdater(_StubProvider(), _StubStore())
    result = updater.refresh("2026-08-21", "2026-08-24")
    assert set(calls) == set(ETF_VALIDATED_ACCEPTANCE_TICKERS)
    assert result["new_boundary"] == "2026-08-24"


def test_etf_acceptance_tickers_match_bundled_script_allowlist() -> None:
    script_source = (ROOT / "scripts/backfill_krx_etf_repository_v2_v01.py").read_text(encoding="utf-8")
    for ticker in ETF_VALIDATED_ACCEPTANCE_TICKERS:
        assert f'"{ticker}"' in script_source, f"{ticker} missing from backfill_krx_etf_repository_v2_v01.py ACCEPTANCE_TICKERS"


# ---------------------------------------------------------------------------
# COMMON adjusted leg: fail-closed on insufficient PIT frontier (the real, current state)
# ---------------------------------------------------------------------------


def test_common_adjusted_updater_fails_closed_when_pit_frontier_insufficient(tmp_path) -> None:
    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"trading_dates": ["2026-08-20", "2026-08-21"]}))
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(json.dumps({"intervals": [{"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-08-21"}]}))

    updater = RollingAdjustedPriceUpdater(provider=None, store=None, pit_path=pit_path, historical_calendar_path=calendar_path)
    with pytest.raises(InsufficientPitFrontierError):
        updater.refresh(["005930"], "2026-08-21", "2026-09-04")


def test_common_adjusted_updater_succeeds_when_frontier_sufficient(tmp_path) -> None:
    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"trading_dates": ["2026-08-20", "2026-08-21", "2026-08-24"]}))
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(json.dumps({"intervals": [{"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-08-24"}]}))
    stocks_dir = tmp_path / "legacy_raw_stocks_dir_that_does_not_exist"  # forces PIT fallback path

    class _StubProvider:
        def load_daily(self, ticker, start, end):
            return _adjusted_frame(start, end)

    store = AdjustedPriceStore(tmp_path / "adjusted")
    updater = RollingAdjustedPriceUpdater(_StubProvider(), store, pit_path=pit_path, historical_calendar_path=calendar_path)
    result = updater.refresh(["005930"], "2026-08-21", "2026-08-24")
    assert result["updated"] == ["005930"]
    assert result["failures"] == []


# ---------------------------------------------------------------------------
# Coordinator: boundary advance / coherence / failure-preserves-boundary / idempotency
# ---------------------------------------------------------------------------


class _FakeRawUpdater:
    def __init__(self, boundary_after: str) -> None:
        self.boundary_after = boundary_after
        self.calls = 0

    def plan(self, current_boundary, target_as_of):
        return {"leg": "common_raw", "start": current_boundary, "end": target_as_of}

    def refresh(self, current_boundary, target_as_of, **kwargs):
        self.calls += 1
        return {"leg": "common_raw", "new_boundary": self.boundary_after}


class _FakeEtfRawUpdater:
    def __init__(self, boundary_after: str) -> None:
        self.boundary_after = boundary_after
        self.calls = 0

    def plan(self, current_boundary, target_as_of):
        return {"leg": "etf_raw", "start": current_boundary, "end": target_as_of}

    def refresh(self, current_boundary, target_as_of, **kwargs):
        self.calls += 1
        return {"leg": "etf_raw", "new_boundary": self.boundary_after}


class _FakeEtfAdjustedUpdater:
    def __init__(self, boundary_after: str) -> None:
        self.boundary_after = boundary_after
        self.calls = 0

    def refresh(self, current_boundary, target_as_of):
        self.calls += 1
        return {"leg": "etf_adjusted", "new_boundary": self.boundary_after, "failures": []}


class _FakeCommonAdjustedUpdater:
    def __init__(self, *, fail: bool = False, boundary_after: str | None = None) -> None:
        self.fail = fail
        self.boundary_after = boundary_after
        self.calls = 0

    def refresh(self, tickers, current_boundary, target_as_of):
        self.calls += 1
        if self.fail:
            raise InsufficientPitFrontierError("no rolling-safe PIT extension exists")
        new_boundary = self.boundary_after if self.boundary_after is not None else target_as_of
        return {"leg": "common_adjusted", "updated": list(tickers), "failures": [], "new_boundary": new_boundary}


def _coordinator(tmp_path, *, common_adjusted_fails: bool, target_boundary: str = "2026-09-04") -> RollingRefreshCoordinator:
    write_rolling_authority(_manifest("2026-08-21"), tmp_path)
    return RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater(target_boundary),
        raw_etf_updater=_FakeEtfRawUpdater(target_boundary),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater(target_boundary),
        common_adjusted_updater=_FakeCommonAdjustedUpdater(fail=common_adjusted_fails),
        common_adjusted_tickers=["005930"],
        authority_dir=tmp_path,
    )


def test_boundary_advances_when_all_legs_succeed(tmp_path) -> None:
    coordinator = _coordinator(tmp_path, common_adjusted_fails=False)
    result = coordinator.execute("2026-09-04", dry_run=False)
    assert result["status"] == "PROMOTED"
    assert result["certified_through"] == "2026-09-04"
    reloaded = load_rolling_authority(tmp_path)
    assert reloaded.certified_through == "2026-09-04"
    assert reloaded.previous_boundary == "2026-08-21"


def test_failed_refresh_preserves_previous_boundary(tmp_path) -> None:
    coordinator = _coordinator(tmp_path, common_adjusted_fails=True)
    before = load_rolling_authority(tmp_path)
    result = coordinator.execute("2026-09-04", dry_run=False)
    assert result["status"] == "FAILED"
    assert result["boundary_unchanged"] is True
    after = load_rolling_authority(tmp_path)
    assert after == before
    assert after.certified_through == "2026-08-21"


def test_raw_adjusted_boundary_coherence_uses_minimum_of_legs(tmp_path) -> None:
    # common_raw/etf_raw/etf_adjusted all reach the target, but common_adjusted only partially
    # progresses (some tickers skipped) and reports a lagging new_boundary -- certified_through must
    # be capped at that lagging leg, not silently promoted to target_as_of.
    write_rolling_authority(_manifest("2026-08-21"), tmp_path)
    coordinator = RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater("2026-09-04"),
        raw_etf_updater=_FakeEtfRawUpdater("2026-09-04"),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater("2026-09-04"),
        common_adjusted_updater=_FakeCommonAdjustedUpdater(fail=False, boundary_after="2026-08-25"),
        common_adjusted_tickers=["005930"],
        authority_dir=tmp_path,
    )
    result = coordinator.execute("2026-09-04", dry_run=False)
    assert result["status"] == "PROMOTED"
    assert result["certified_through"] == "2026-08-25"
    reloaded = load_rolling_authority(tmp_path)
    assert reloaded.certified_through == "2026-08-25"
    assert reloaded.leg_boundaries["common_raw"] == "2026-09-04"
    assert reloaded.leg_boundaries["common_adjusted"] == "2026-08-25"


def test_idempotent_rerun_adds_no_rows_and_does_not_move_boundary_again(tmp_path) -> None:
    coordinator = _coordinator(tmp_path, common_adjusted_fails=False)
    first = coordinator.execute("2026-09-04", dry_run=False)
    assert first["status"] == "PROMOTED"
    second = coordinator.execute("2026-09-04", dry_run=False)
    assert second["status"] == "NOOP_ALREADY_CERTIFIED"
    assert second["certified_through"] == "2026-09-04"


def test_coordinator_aborts_promotion_when_pre_boundary_history_mutates(tmp_path) -> None:
    write_rolling_authority(_manifest("2026-08-21"), tmp_path)
    raw_store = _seed_raw_store(tmp_path / "raw", dates=["2026-08-21"])
    adjusted_store = _seed_adjusted_store(tmp_path / "adjusted", ["005930"], start="2026-08-01", end="2026-08-21")

    class _MutatingCommonAdjustedUpdater(_FakeCommonAdjustedUpdater):
        def refresh(self, tickers, current_boundary, target_as_of):
            # Simulate a bug that corrupts a pre-boundary row while "successfully" extending forward.
            mutated = _adjusted_frame("2026-08-01", "2026-08-21")
            mutated[["open", "high", "low", "close"]] = mutated[["open", "high", "low", "close"]] + 5.0
            adjusted_store.save_full("005930", mutated, {"requested_start": "2026-08-01", "requested_end": "2026-08-21"})
            return super().refresh(tickers, current_boundary, target_as_of)

    coordinator = RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater("2026-09-04"),
        raw_etf_updater=_FakeEtfRawUpdater("2026-09-04"),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater("2026-09-04"),
        common_adjusted_updater=_MutatingCommonAdjustedUpdater(),
        common_adjusted_tickers=["005930"],
        authority_dir=tmp_path,
        raw_store=raw_store,
        adjusted_store=adjusted_store,
    )
    before = load_rolling_authority(tmp_path)
    result = coordinator.execute("2026-09-04", dry_run=False)
    assert result["status"] == "FAILED"
    assert result["error"] == "PREVIOUS_CERTIFIED_HISTORY_MUTATION_DETECTED"
    after = load_rolling_authority(tmp_path)
    assert after == before


def test_dry_run_never_writes(tmp_path) -> None:
    coordinator = _coordinator(tmp_path, common_adjusted_fails=False)
    before = (tmp_path / "manifest.json").read_bytes()
    result = coordinator.execute("2026-09-04", dry_run=True)
    assert result["status"] == "DRY_RUN"
    after = (tmp_path / "manifest.json").read_bytes()
    assert before == after


# ---------------------------------------------------------------------------
# Data-safety guards (directive sections 28-30)
# ---------------------------------------------------------------------------


def test_future_row_guard() -> None:
    assert count_rows_after(["2026-08-14", "2026-09-04"], "2026-09-04") == 0
    assert count_rows_after(["2026-08-14", "2026-09-05"], "2026-09-04") == 1


def test_history_fingerprint_unchanged_when_only_forward_data_added(tmp_path) -> None:
    raw_root = tmp_path / "raw"
    raw_store = _seed_raw_store(raw_root, dates=["2026-08-20", "2026-08-21"])
    adjusted_dir = tmp_path / "adjusted"
    adjusted_store = _seed_adjusted_store(adjusted_dir, ["005930"], start="2026-08-01", end="2026-08-21")
    tickers = ["005930"]

    before = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")

    # Add a new forward date to raw (a distinct partition -- must not touch existing ones).
    raw_store.save_snapshot("KOSPI", "2026-08-24", _raw_frame("005930", "2026-08-24"), "/KOSPI")
    raw_store.save_snapshot("KOSDAQ", "2026-08-24", _raw_frame("005930", "2026-08-24"), "/KOSDAQ")
    raw_store.save_snapshot("ETF", "2026-08-24", _raw_frame("069500", "2026-08-24"), "/ETF")

    after = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")
    assert after == before


def test_history_fingerprint_unchanged_when_an_existing_ticker_is_extended_forward(tmp_path) -> None:
    """The critical case: AdjustedPriceStore.save_full rewrites the ENTIRE file, so the ticker's
    content_sha256 changes on every extension -- the fingerprint must still see the pre-boundary
    slice as identical, since it hashes actual row values for a fixed ticker set, not the whole-file
    digest."""
    raw_root = tmp_path / "raw"
    raw_store = _seed_raw_store(raw_root, dates=["2026-08-21"])
    adjusted_dir = tmp_path / "adjusted"
    adjusted_store = _seed_adjusted_store(adjusted_dir, ["005930"], start="2026-08-01", end="2026-08-21")
    tickers = ["005930"]  # the pre-refresh ticker set, captured once and reused for both snapshots

    before = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")
    before_content_sha256 = adjusted_store.load_metadata("005930")["content_sha256"]

    # Simulate a rolling refresh: extend the same ticker's adjusted history forward to 2026-08-24.
    # This rewrites the whole file, so content_sha256 legitimately changes...
    extended = _adjusted_frame("2026-08-01", "2026-08-24")
    adjusted_store.save_full("005930", extended, {"requested_start": "2026-08-01", "requested_end": "2026-08-24"})
    after_content_sha256 = adjusted_store.load_metadata("005930")["content_sha256"]
    assert after_content_sha256 != before_content_sha256, "test setup must actually exercise a whole-file rewrite"

    # ...but the pre-boundary slice fingerprint must be unchanged.
    after = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")
    assert after == before


def test_history_fingerprint_changes_if_pre_boundary_row_mutates(tmp_path) -> None:
    raw_root = tmp_path / "raw"
    raw_store = _seed_raw_store(raw_root, dates=["2026-08-21"])
    adjusted_dir = tmp_path / "adjusted"
    adjusted_store = _seed_adjusted_store(adjusted_dir, ["005930"], start="2026-08-01", end="2026-08-21")
    tickers = ["005930"]
    before = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")

    # Overwrite the ticker's adjusted history with different (still valid-OHLC) values -- still ends
    # at the same date, but the fingerprint must catch the changed row values.
    mutated = _adjusted_frame("2026-08-01", "2026-08-21")
    mutated[["open", "high", "low", "close"]] = mutated[["open", "high", "low", "close"]] + 1.0
    adjusted_store.save_full("005930", mutated, {"requested_start": "2026-08-01", "requested_end": "2026-08-21"})

    after = history_fingerprint(raw_store, adjusted_store, tickers, "2026-08-21")
    assert after["adjusted_history_sha256"] != before["adjusted_history_sha256"]
