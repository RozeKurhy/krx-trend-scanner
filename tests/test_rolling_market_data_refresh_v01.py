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
    APPROVED_HISTORICAL_RESTATEMENT,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    HISTORICAL_RESTATEMENT_UNCHANGED,
    InsufficientPitFrontierError,
    KindCorporateActionEvidenceProvider,
    REJECTED_HISTORICAL_RESTATEMENT,
    RollingAuthorityError,
    RollingAuthorityManifest,
    RollingEtfAdjustedUpdater,
    RollingAdjustedPriceUpdater,
    RollingRawEtfUpdater,
    RollingRawMarketUpdater,
    RollingRefreshCoordinator,
    bootstrap_rolling_authority,
    classify_adjusted_history_transition,
    count_rows_after,
    history_fingerprint,
    parse_kind_corporate_action_evidence,
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


def _corporate_action_evidence(ticker: str, factors, event_date: str = "2026-08-10") -> list[dict[str, object]]:
    return [
        {
            "ticker": ticker,
            "authority_valid": True,
            "event_type": "STOCK_SPLIT",
            "normalized_event_type": "STOCK_SPLIT",
            "event_date": event_date,
            "official_anchor_date": event_date,
            "ratio": factors,
            "observed_factor": factors,
            "official_source": "KIND_KRX",
            "source_reference": f"https://kind.krx.co.kr/external/test/{ticker}",
        }
    ]


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
    result = updater.refresh("2022-12-31", "2026-08-24")
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

    store = _seed_adjusted_store(
        tmp_path / "adjusted",
        ["005930"],
        start="2010-01-04",
        end="2026-08-21",
    )
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


def _coordinator(
    tmp_path,
    *,
    common_adjusted_fails: bool,
    target_boundary: str = "2026-09-04",
    population_gap_audit=None,
) -> RollingRefreshCoordinator:
    write_rolling_authority(_manifest("2026-08-21"), tmp_path)
    return RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater(target_boundary),
        raw_etf_updater=_FakeEtfRawUpdater(target_boundary),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater(target_boundary),
        common_adjusted_updater=_FakeCommonAdjustedUpdater(fail=common_adjusted_fails),
        common_adjusted_tickers=["005930"],
        authority_dir=tmp_path,
        population_gap_audit=population_gap_audit,
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


def test_coordinator_blocks_independent_unexplained_gap_audit(tmp_path) -> None:
    coordinator = _coordinator(
        tmp_path,
        common_adjusted_fails=False,
        population_gap_audit=lambda: {
            "candidate_boundary": "2026-09-04",
            "unexplained_gap_count": 244,
        },
    )

    before = load_rolling_authority(tmp_path)
    result = coordinator.execute("2026-09-04", dry_run=False)

    assert result["status"] == "FAILED"
    assert result["error"] == "BLOCKED_UNEXPLAINED_GAPS_244"
    assert result["boundary_unchanged"] is True
    assert load_rolling_authority(tmp_path) == before


def test_coordinator_fails_when_adjusted_validation_record_is_missing(tmp_path) -> None:
    authority_dir = tmp_path / "authority"
    write_rolling_authority(_manifest("2026-08-21"), authority_dir)
    coordinator = RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater("2026-09-04"),
        raw_etf_updater=_FakeEtfRawUpdater("2026-09-04"),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater("2026-09-04"),
        common_adjusted_updater=_FakeCommonAdjustedUpdater(),
        common_adjusted_tickers=["005930"],
        authority_dir=authority_dir,
        raw_store=KrxRawStockStore(tmp_path / "raw"),
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
    )

    result = coordinator.execute("2026-09-04", dry_run=False)

    assert result["status"] == "FAILED"
    assert result["error"] == "PREVIOUS_CERTIFIED_HISTORY_MUTATION_DETECTED"
    assert result["error_reason"] == "MISSING_ADJUSTED_RESTATEMENT_VALIDATION"
    assert result["restatement_summary"]["validation_coverage_missing_tickers"] == ["005930"]


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


def test_validated_adjusted_restatement_is_approved() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    historical = candidate.index <= pd.Timestamp("2026-08-21")
    candidate.loc[historical, ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930",
        before,
        candidate,
        "2026-08-21",
        provider_frame_match=True,
        corporate_action_evidence=_corporate_action_evidence("005930", 5.0),
    )

    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert result["changed_rows"] == len(before)
    assert result["factor_regime_count"] == 1


def test_piecewise_adjusted_restatement_is_approved() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    first_regime = candidate.index <= pd.Timestamp("2026-08-10")
    second_regime = (candidate.index > pd.Timestamp("2026-08-10")) & (candidate.index <= pd.Timestamp("2026-08-21"))
    candidate.loc[first_regime, ["open", "high", "low", "close"]] *= 100.0
    candidate.loc[second_regime, ["open", "high", "low", "close"]] *= 10.0

    result = classify_adjusted_history_transition(
        "002780",
        before,
        candidate,
        "2026-08-21",
        provider_frame_match=True,
        corporate_action_evidence=_corporate_action_evidence("002780", [10.0, 100.0]),
    )

    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert result["factor_regime_count"] == 2


def test_coherent_factor_change_without_corporate_action_evidence_is_rejected() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    historical = candidate.index <= pd.Timestamp("2026-08-21")
    candidate.loc[historical, ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["reason"] == "CORPORATE_ACTION_EVIDENCE_MISSING"
    assert result["corporate_action_evidence_matched"] is False


def test_corporate_action_evidence_with_unexplained_ratio_is_rejected() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    historical = candidate.index <= pd.Timestamp("2026-08-21")
    candidate.loc[historical, ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930",
        before,
        candidate,
        "2026-08-21",
        provider_frame_match=True,
        corporate_action_evidence=_corporate_action_evidence("005930", 3.0),
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["corporate_action_evidence_matched"] is True
    assert result["reason"] == "CORPORATE_ACTION_RATIO_DOES_NOT_EXPLAIN_RESTATEMENT"


def test_isolated_adjusted_history_mutation_is_rejected() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = before.copy()
    candidate.iloc[3, candidate.columns.get_loc("close")] += 1.0

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["reason"] == "ISOLATED_CERTIFIED_ROW_CHANGE"


def test_forward_only_adjusted_extension_is_unchanged() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True
    )

    assert result["status"] == HISTORICAL_RESTATEMENT_UNCHANGED
    assert result["reason"] == "NO_CERTIFIED_VALUE_CHANGE"


def test_unchanged_candidate_does_not_lookup_corporate_action_evidence() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    lookup_calls: list[str] = []

    result = classify_adjusted_history_transition(
        "005930",
        before,
        candidate,
        "2026-08-21",
        provider_frame_match=True,
        corporate_action_evidence_lookup=lambda ticker: lookup_calls.append(ticker),
    )

    assert result["status"] == HISTORICAL_RESTATEMENT_UNCHANGED
    assert lookup_calls == []


def test_kind_parser_produces_production_evidence_schema_and_approves_restatement() -> None:
    html = """
    <html><body>
      <h1>주식병합 결정</h1>
      <p>액면가액 100원에서 500원으로 변경</p>
      <p>효력발생일 2026.08.10</p>
      <script>2026.09.01 noise must not become the event date</script>
    </body></html>
    """
    evidence = parse_kind_corporate_action_evidence(
        html,
        "001000",
        "https://kind.krx.co.kr/external/2026/07/23/000479/20260723001108/00591.htm",
    )

    assert len(evidence) == 1
    record = evidence[0]
    assert {
        "ticker", "event_type", "event_date", "ratio", "official_source", "source_reference"
    } <= record.keys()
    assert record["ticker"] == "001000"
    assert record["event_type"] == "STOCK_CONSOLIDATION"
    assert record["event_date"] == "2026-08-10"
    assert record["ratio"] == 5.0

    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0
    result = classify_adjusted_history_transition(
        "001000", before, candidate, "2026-08-21", provider_frame_match=True,
        corporate_action_evidence=evidence,
    )
    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert result["corporate_action_factor_date_matched"] is True


def test_kind_evidence_provider_fetches_only_configured_ticker_and_caches() -> None:
    class _Response:
        status_code = 200
        content = "<body>주식병합 액면가액 100원에서 500원 효력발생일 2026.08.10</body>".encode()

    class _Session:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, url, timeout, params=None):
            self.calls.append(url)
            return _Response()

    session = _Session()
    provider = KindCorporateActionEvidenceProvider(
        {"001000": "https://kind.krx.co.kr/external/001000.htm"},
        session=session,
    )

    first = provider("001000")
    second = provider("001000")
    assert len(first) == len(second) == 1
    assert session.calls == ["https://kind.krx.co.kr/external/001000.htm"]


def test_kind_auto_resolver_finds_candidate_reference_and_reaches_validator() -> None:
    search_url = "https://kind.krx.co.kr/disclosure/details.do"
    document_url = "https://kind.krx.co.kr/external/2026/07/23/000479/20260723001108/00591.htm"

    class _Response:
        def __init__(self, content: str) -> None:
            self.status_code = 200
            self.content = content.encode()

    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict | None]] = []

        def get(self, url, timeout, params=None):
            self.calls.append((url, params))
            if url == search_url:
                return _Response(f'<a href="{document_url}">주식병합 결정</a>')
            return _Response("<body>주식병합 액면가액 100원에서 500원 효력발생일 2026.08.22</body>")

    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0
    session = _Session()
    provider = KindCorporateActionEvidenceProvider(session=session)

    result = classify_adjusted_history_transition(
        "001000",
        before,
        candidate,
        "2026-08-21",
        target_as_of="2026-08-24",
        provider_frame_match=True,
        corporate_action_evidence_lookup=provider,
    )

    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert [url for url, _params in session.calls] == [search_url, document_url]
    assert session.calls[0][1]["repIsuSrtCd"] == "A001000"


def test_kind_auto_resolver_no_result_fails_closed() -> None:
    class _Session:
        def get(self, url, timeout, params=None):
            class _Response:
                status_code = 200
                content = b"<body>no matching disclosure</body>"

            return _Response()

    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0
    provider = KindCorporateActionEvidenceProvider(session=_Session())

    result = classify_adjusted_history_transition(
        "002780", before, candidate, "2026-08-21", target_as_of="2026-08-24",
        provider_frame_match=True, corporate_action_evidence_lookup=provider,
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["reason"] == "CORPORATE_ACTION_EVIDENCE_MISSING"


def test_kind_auto_search_is_bounded_and_filters_non_action_candidates() -> None:
    search_url = "https://kind.krx.co.kr/disclosure/details.do"
    general_url = "https://kind.krx.co.kr/external/general.htm"
    action_url = "https://kind.krx.co.kr/external/action.htm"

    class _Response:
        def __init__(self, content: str) -> None:
            self.status_code = 200
            self.content = content.encode()

    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict | None]] = []

        def get(self, url, timeout, params=None):
            self.calls.append((url, params))
            if url == search_url:
                return _Response(
                    f'<a href="{general_url}">사업보고서</a>'
                    f'<a href="{action_url}">주식병합 결정</a>'
                )
            if url == action_url:
                return _Response("<body>주식병합 액면가액 100원에서 500원 효력발생일 2026.08.22</body>")
            return _Response("<body>must not fetch general disclosure</body>")

    session = _Session()
    provider = KindCorporateActionEvidenceProvider(session=session)
    records = provider.lookup(
        "001000",
        current_boundary="2026-09-11",
        target_as_of="2026-09-18",
        historical_start="2010-01-04",
    )

    assert len(records) == 1
    assert [url for url, _params in session.calls] == [search_url, action_url]
    search_params = session.calls[0][1]
    assert search_params["searchFromDate"] == "2025-09-11"
    assert search_params["searchToDate"] == "2026-09-18"
    assert search_params["searchFromDate"] != "2010-01-04"


def test_compound_adjusted_restatement_uses_at_most_three_official_factors() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 16.77
    evidence = [
        _corporate_action_evidence("001470", 3.0, "2026-08-10")[0],
        _corporate_action_evidence("001470", 5.59, "2026-08-11")[0],
    ]

    result = classify_adjusted_history_transition(
        "001470", before, candidate, "2026-08-21", provider_frame_match=True,
        corporate_action_evidence=evidence,
    )

    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert result["corporate_action_factor_date_matched"] is True
    assert any(
        abs(item["factor"] - 16.77) < 0.02 and len(item["component_factors"]) == 2
        for item in result["corporate_action_factor_combinations"]
    )


def test_piecewise_adjusted_restatement_requires_non_contradictory_event_order() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    first_regime = candidate.index <= pd.Timestamp("2026-08-10")
    second_regime = (candidate.index > pd.Timestamp("2026-08-10")) & (candidate.index <= pd.Timestamp("2026-08-21"))
    candidate.loc[first_regime, ["open", "high", "low", "close"]] *= 100.0
    candidate.loc[second_regime, ["open", "high", "low", "close"]] *= 10.0
    valid_evidence = [
        _corporate_action_evidence("002780", 10.0, "2026-08-10")[0],
        _corporate_action_evidence("002780", 10.0, "2026-08-11")[0],
    ]
    valid = classify_adjusted_history_transition(
        "002780", before, candidate, "2026-08-21", provider_frame_match=True,
        corporate_action_evidence=valid_evidence,
    )
    assert valid["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert valid["factor_regime_sequence"] == [100.0, 10.0]

    contradictory_evidence = [
        _corporate_action_evidence("002780", 100.0, "2026-08-11")[0],
        _corporate_action_evidence("002780", 10.0, "2026-08-10")[0],
    ]
    contradictory = classify_adjusted_history_transition(
        "002780", before, candidate, "2026-08-21", provider_frame_match=True,
        corporate_action_evidence=contradictory_evidence,
    )
    assert contradictory["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert contradictory["reason"] == "CORPORATE_ACTION_FACTOR_ORDER_UNSUPPORTED"


def test_common_updater_passes_refresh_window_to_kind_lookup(tmp_path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"trading_dates": ["2026-08-21", "2026-08-24"]}))
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(json.dumps({"intervals": [{"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-08-24"}]}))
    store = _seed_adjusted_store(tmp_path / "adjusted", ["005930"], start="2026-08-03", end="2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    class _StubProvider:
        def load_daily(self, ticker, start, end):
            return candidate

    class _WindowRecordingProvider(KindCorporateActionEvidenceProvider):
        def __init__(self):
            super().__init__()
            self.windows: list[tuple[str, str, str, str]] = []

        def lookup(self, ticker, *, current_boundary=None, target_as_of=None, historical_start=None):
            self.windows.append((ticker, current_boundary, target_as_of, historical_start))
            return _corporate_action_evidence(ticker, 5.0, "2026-08-22")

    evidence_provider = _WindowRecordingProvider()
    updater = RollingAdjustedPriceUpdater(
        _StubProvider(),
        store,
        pit_path=pit_path,
        historical_calendar_path=calendar_path,
        corporate_action_evidence_lookup=evidence_provider,
    )

    result = updater.refresh(["005930"], "2026-08-21", "2026-08-24")

    assert result["updated"] == ["005930"]
    assert evidence_provider.windows == [("005930", "2026-08-21", "2026-08-24", "2010-01-04")]


def test_production_entrypoint_does_not_use_legacy_frozen_control_csv() -> None:
    source = (ROOT / "scripts/refresh_market_data_v01.py").read_text(encoding="utf-8")
    assert "reassessed_corporate_action_controls.csv" not in source
    assert "KindCorporateActionEvidenceProvider" in source


def test_corporate_action_event_inside_refresh_window_is_approved() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True,
        target_as_of="2026-08-24",
        corporate_action_evidence=_corporate_action_evidence("005930", 5.0, "2026-08-22"),
    )

    assert result["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert result["corporate_action_factor_date_matched"] is True


def test_corporate_action_event_after_target_is_rejected() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True,
        target_as_of="2026-08-24",
        corporate_action_evidence=_corporate_action_evidence("005930", 5.0, "2026-08-25"),
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["reason"] == "CORPORATE_ACTION_EVENT_TIME_UNSUPPORTED"


def test_corporate_action_event_before_history_start_is_rejected() -> None:
    before = _adjusted_frame("2026-08-03", "2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    result = classify_adjusted_history_transition(
        "005930", before, candidate, "2026-08-21", provider_frame_match=True,
        target_as_of="2026-08-24",
        corporate_action_evidence=_corporate_action_evidence("005930", 5.0, "2026-08-01"),
    )

    assert result["status"] == REJECTED_HISTORICAL_RESTATEMENT
    assert result["reason"] == "CORPORATE_ACTION_EVENT_TIME_UNSUPPORTED"


def test_coordinator_allows_validated_adjusted_restatement(tmp_path) -> None:
    write_rolling_authority(_manifest("2026-08-21"), tmp_path)
    raw_store = _seed_raw_store(tmp_path / "raw", dates=["2026-08-21"])
    adjusted_store = _seed_adjusted_store(
        tmp_path / "adjusted",
        ["005930", *ETF_VALIDATED_ACCEPTANCE_TICKERS],
        start="2026-08-03",
        end="2026-08-21",
    )

    class _ApprovedCommonAdjustedUpdater(_FakeCommonAdjustedUpdater):
        def refresh(self, tickers, current_boundary, target_as_of):
            before = adjusted_store.load_daily("005930")
            candidate = _adjusted_frame("2026-08-03", "2026-08-24")
            historical = candidate.index <= pd.Timestamp(current_boundary)
            candidate.loc[historical, ["open", "high", "low", "close"]] *= 5.0
            transition = classify_adjusted_history_transition(
                "005930",
                before,
                candidate,
                current_boundary,
                provider_frame_match=True,
                corporate_action_evidence=_corporate_action_evidence("005930", 5.0),
            )
            adjusted_store.save_full(
                "005930", candidate, {"requested_start": "2026-08-03", "requested_end": "2026-08-24"}
            )
            return {
                "leg": "common_adjusted",
                "updated": list(tickers),
                "skipped": [],
                "failures": [],
                "restatement_validation": [transition],
                "new_boundary": target_as_of,
            }

    coordinator = RollingRefreshCoordinator(
        raw_updater=_FakeRawUpdater("2026-09-04"),
        raw_etf_updater=_FakeEtfRawUpdater("2026-09-04"),
        etf_adjusted_updater=_FakeEtfAdjustedUpdater("2026-09-04"),
        common_adjusted_updater=_ApprovedCommonAdjustedUpdater(),
        common_adjusted_tickers=["005930"],
        authority_dir=tmp_path,
        raw_store=raw_store,
        adjusted_store=adjusted_store,
    )

    result = coordinator.execute("2026-09-04", dry_run=False)

    assert result["status"] == "PROMOTED"
    assert result["restatement_summary"]["changed_adjusted_ticker_count"] == 1
    assert result["restatement_summary"]["approved_restatement_count"] == 1
    assert result["restatement_summary"]["rejected_unexplained_count"] == 0


def test_rejected_candidate_does_not_overwrite_physical_adjusted_store(tmp_path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"trading_dates": ["2026-08-21", "2026-08-24"]}))
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(json.dumps({"intervals": [{"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-08-24"}]}))
    store = _seed_adjusted_store(tmp_path / "adjusted", ["005930"], start="2026-08-03", end="2026-08-21")
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    class _StubProvider:
        def load_daily(self, ticker, start, end):
            return candidate

    parquet_path = tmp_path / "adjusted" / "005930.parquet"
    metadata_path = tmp_path / "adjusted" / "005930.meta.json"
    before_parquet = parquet_path.read_bytes()
    before_metadata = metadata_path.read_bytes()
    updater = RollingAdjustedPriceUpdater(
        _StubProvider(), store, pit_path=pit_path, historical_calendar_path=calendar_path
    )

    result = updater.refresh(["005930"], "2026-08-21", "2026-08-24")

    assert result["updated"] == []
    assert result["restatement_validation"][0]["reason"] == "CORPORATE_ACTION_EVIDENCE_MISSING"
    assert result["failures"][0]["error_type"] == REJECTED_HISTORICAL_RESTATEMENT
    assert parquet_path.read_bytes() == before_parquet
    assert metadata_path.read_bytes() == before_metadata


def test_approved_candidate_reaches_save_full(tmp_path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"trading_dates": ["2026-08-21", "2026-08-24"]}))
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(json.dumps({"intervals": [{"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-08-24"}]}))

    class _CountingStore(AdjustedPriceStore):
        save_calls = 0

        def save_full(self, *args, **kwargs):
            self.save_calls += 1
            return super().save_full(*args, **kwargs)

    store = _CountingStore(tmp_path / "adjusted")
    store.save_full("005930", _adjusted_frame("2026-08-03", "2026-08-21"), {"requested_start": "2026-08-03", "requested_end": "2026-08-21"})
    candidate = _adjusted_frame("2026-08-03", "2026-08-24")
    candidate.loc[candidate.index <= pd.Timestamp("2026-08-21"), ["open", "high", "low", "close"]] *= 5.0

    class _StubProvider:
        def load_daily(self, ticker, start, end):
            return candidate

    updater = RollingAdjustedPriceUpdater(
        _StubProvider(),
        store,
        pit_path=pit_path,
        historical_calendar_path=calendar_path,
        corporate_action_evidence_lookup=lambda ticker: _corporate_action_evidence(ticker, 5.0),
    )

    result = updater.refresh(["005930"], "2026-08-21", "2026-08-24")

    assert result["updated"] == ["005930"]
    assert result["restatement_validation"][0]["status"] == APPROVED_HISTORICAL_RESTATEMENT
    assert store.save_calls == 2
