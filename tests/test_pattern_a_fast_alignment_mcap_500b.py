from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.reporting import a_fast_core_report
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    AlignmentGateIntegrityError,
    AlignmentMcap500BGate,
    EXPECTED_EXCLUSION_COUNT,
    EXPECTED_EXCLUSION_SHA256,
    MARKET_CAP_THRESHOLD_KRW,
    PROMOTED_STRATEGY_ID,
    PENDING_USER_APPROVAL,
    PromotionConfig,
    V2_STRATEGY_ID,
    canonical_exclusion_sha256,
    load_promotion_config,
    monthly_alignment_decision,
    verify_permanent_exclusion_registry,
)


SIGNAL_DATE = pd.Timestamp("2025-01-15")
EFFECTIVE_DATE = "2025-01-01"


def _daily_prices(month_count: int = 60, *, monthly_values: list[float] | None = None, signal_close: float = 100.0) -> pd.DataFrame:
    periods = pd.period_range(end=SIGNAL_DATE.to_period("M") - 1, periods=month_count, freq="M")
    values = monthly_values if monthly_values is not None else [float(value) for value in range(1, month_count + 1)]
    assert len(values) == len(periods)
    rows = [(period.end_time.normalize(), value) for period, value in zip(periods, values)]
    # A very high earlier observation in the signal month must not enter either MA.
    rows.extend([
        (SIGNAL_DATE.replace(day=2), 1_000_000.0),
        (SIGNAL_DATE, signal_close),
    ])
    frame = pd.DataFrame({"close": [value for _, value in rows]}, index=pd.DatetimeIndex([day for day, _ in rows]))
    return frame.sort_index()


def _active_gate(
    *,
    ticker: str = "999997",
    isu_cd: str = "KR7999997003",
    market: str = "KOSPI",
    market_cap: int | None = MARKET_CAP_THRESHOLD_KRW,
    repo_root: Path | None = None,
) -> AlignmentMcap500BGate:
    return AlignmentMcap500BGate(
        repo_root or Path("."),
        PromotionConfig(
            enabled=True,
            effective_signal_date=EFFECTIVE_DATE,
            operational_activation_approved=True,
        ),
        identity_resolver=lambda _ticker, _market, _date: (isu_cd, market),
        market_cap_resolver=lambda _ticker, _market, _date: market_cap,
    )


def _raw_snapshot(day: str, ticker: str = "999997", market_cap: int = MARKET_CAP_THRESHOLD_KRW) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": day,
        "ticker": ticker,
        "open": 100,
        "high": 100,
        "low": 100,
        "close": 100,
        "volume": 1,
        "trading_value": 100,
        "market_cap": market_cap,
        "listed_shares": 5_000_000_000,
    }], columns=list(RAW_COLUMNS))


def test_operational_config_stays_disabled_pending_approval(tmp_path):
    absent = load_promotion_config(tmp_path)
    assert absent.enabled is False
    assert absent.active is False
    assert absent.effective_signal_date == PENDING_USER_APPROVAL

    repo_root = Path(__file__).resolve().parents[1]
    configured = load_promotion_config(repo_root)
    assert configured.enabled is False
    assert configured.active is False
    assert configured.effective_signal_date == PENDING_USER_APPROVAL
    assert configured.operational_activation_approved is False

    config_path = tmp_path / "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json"
    payload = json.loads((repo_root / "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json").read_text())
    payload["enabled"] = True
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AlignmentGateIntegrityError, match="ACTIVATION_NOT_APPROVED_OR_DATE_PENDING"):
        load_promotion_config(tmp_path)

    unapproved = PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=False)
    assert unapproved.active is False


def test_monthly_alignment_uses_only_60_prior_completed_month_ends():
    decision = monthly_alignment_decision(_daily_prices(), SIGNAL_DATE)
    assert decision.allowed is True
    assert decision.reason_code == "PASS_ALIGNMENT"
    assert decision.details["ma20_prior_completed_months"] == pytest.approx(50.5)
    assert decision.details["ma60_prior_completed_months"] == pytest.approx(30.5)
    assert decision.details["last_completed_month"] == "2024-12"


def test_repository_v2_monthly_alignment_matches_sealed_research_golden():
    repo_root = Path(__file__).resolve().parents[1]
    evidence_path = repo_root / (
        "artifacts/strategies/a_fast_core_v2/research/"
        "fast_core_v2_alignment_500b_p3_2_official_realistic_v01/"
        "sample_candidate_signal_filter_audit.csv"
    )
    with evidence_path.open(encoding="utf-8", newline="") as stream:
        golden = next(
            row for row in csv.DictReader(stream)
            if row["ticker"] == "000660" and row["signal_date"] == "2022-03-04"
        )
    daily = AdjustedPriceStore(repo_root / "data/market/adjusted/stocks").load_daily(
        golden["ticker"], start="2017-03-01", end=golden["signal_date"]
    )
    decision = monthly_alignment_decision(daily, golden["signal_date"])
    assert decision.allowed is True
    assert decision.details["signal_close_adjusted"] == pytest.approx(float(golden["signal_day_adjusted_close"]))
    assert decision.details["ma20_prior_completed_months"] == pytest.approx(float(golden["ma20"]))
    assert decision.details["ma60_prior_completed_months"] == pytest.approx(float(golden["ma60"]))


@pytest.mark.parametrize(
    ("values", "signal_close"),
    [
        ([float(value) for value in range(1, 61)], 50.5),  # close == MA20
        ([10.0] * 60, 20.0),  # MA20 == MA60
    ],
)
def test_monthly_alignment_uses_strict_inequalities(values, signal_close):
    decision = monthly_alignment_decision(
        _daily_prices(monthly_values=values, signal_close=signal_close),
        SIGNAL_DATE,
    )
    assert decision.allowed is False
    assert decision.reason_code == "REJECT_MA_ALIGNMENT"


@pytest.mark.parametrize("month_count", [59, 60])
def test_monthly_alignment_rejects_insufficient_or_gapped_history(month_count):
    daily = _daily_prices(month_count)
    if month_count == 60:
        daily = daily.drop(pd.Period("2022-06", freq="M").end_time.normalize())
    decision = monthly_alignment_decision(daily, SIGNAL_DATE)
    assert decision.allowed is False
    assert decision.reason_code == "REJECT_MA_UNAVAILABLE"
    assert decision.details["cause"] == "PRIOR_COMPLETED_MONTHS_INSUFFICIENT_OR_GAPPED"


def test_market_cap_threshold_and_exact_pit_keys():
    calls = []
    gate = AlignmentMcap500BGate(
        Path("."),
        PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=True),
        identity_resolver=lambda ticker, market, day: ("KR7999997003", market),
        market_cap_resolver=lambda ticker, market, day: calls.append((ticker, market, day)) or MARKET_CAP_THRESHOLD_KRW,
    )
    passed = gate.evaluate("999997", "KOSPI", _daily_prices(), SIGNAL_DATE)
    assert passed.allowed is True
    assert passed.reason_code == "PASS_ALIGNMENT_MCAP_500B"
    assert passed.details["market_cap_partition"] == {"market": "KOSPI", "date": "2025-01-15"}
    assert calls == [("999997", "KOSPI", "2025-01-15")]

    below = _active_gate(market_cap=MARKET_CAP_THRESHOLD_KRW - 1).evaluate(
        "999997", "KOSPI", _daily_prices(), SIGNAL_DATE
    )
    assert below.allowed is False
    assert below.reason_code == "REJECT_MCAP_BELOW_500B"


def test_exact_exclusion_pair_hash_and_signal_date_lineage():
    registry = verify_permanent_exclusion_registry()
    assert registry == {
        "pair_count": EXPECTED_EXCLUSION_COUNT,
        "canonical_sha256": EXPECTED_EXCLUSION_SHA256,
    }
    assert canonical_exclusion_sha256(PERMANENT_IDENTITY_EXCLUSIONS) == EXPECTED_EXCLUSION_SHA256

    ticker, excluded_isu = sorted(PERMANENT_IDENTITY_EXCLUSIONS)[0]
    excluded_gate = _active_gate(ticker=ticker, isu_cd=excluded_isu)
    excluded = excluded_gate.evaluate(ticker, "KOSPI", _daily_prices(), SIGNAL_DATE)
    assert excluded.allowed is False
    assert excluded.reason_code == "REJECT_PERMANENT_EXCLUSION"

    different_isu = excluded_isu[:-1] + ("0" if excluded_isu[-1] != "0" else "1")
    changed_pair_gate = _active_gate(ticker=ticker, isu_cd=different_isu)
    changed_pair = changed_pair_gate.evaluate(ticker, "KOSPI", _daily_prices(), SIGNAL_DATE)
    assert changed_pair.reason_code == "PASS_ALIGNMENT_MCAP_500B"

    prior_trade = {"entry_signal_date": "2024-12-31", "entry_execution_date": "2025-01-02"}
    assert changed_pair_gate.strategy_id_for_signal(prior_trade["entry_signal_date"]) == V2_STRATEGY_ID
    assert changed_pair_gate.strategy_id_for_signal("2025-01-01") == PROMOTED_STRATEGY_ID
    # A post-cutover execution date does not change the pre-cutover signal lineage.


def test_repository_rolling_pit_resolves_exact_ticker_market_signal_date():
    repo_root = Path(__file__).resolve().parents[1]
    gate = AlignmentMcap500BGate(
        repo_root,
        PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=True),
        market_cap_resolver=lambda *_args: MARKET_CAP_THRESHOLD_KRW,
    )
    assert gate._resolve_pit_identity("000660", "KOSPI", "2022-03-04") == ("KR7000660001", "KOSPI")
    assert gate._resolve_pit_identity("000660", "KOSDAQ", "2022-03-04") is None
    assert gate._resolve_pit_identity("000660", "KOSPI", "2030-01-01") is None


def test_raw_partition_is_exact_and_manifest_hash_is_verified(tmp_path):
    raw_root = tmp_path / DEFAULT_RAW_STOCK_ROOT
    store = KrxRawStockStore(raw_root)
    store.save_snapshot("KOSPI", SIGNAL_DATE, _raw_snapshot("2025-01-15"), "synthetic-test")
    exact_gate = AlignmentMcap500BGate(
        tmp_path,
        PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=True),
        identity_resolver=lambda _ticker, market, _day: ("KR7999997003", market),
    )
    exact = exact_gate.evaluate("999997", "KOSPI", _daily_prices(), SIGNAL_DATE)
    assert exact.reason_code == "PASS_ALIGNMENT_MCAP_500B"

    row = store.get_manifest("KOSPI", SIGNAL_DATE)
    partition_path = raw_root / row["file_path"]
    partition_path.write_bytes(b"tampered partition")
    tampered_gate = AlignmentMcap500BGate(
        tmp_path,
        PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=True),
        identity_resolver=lambda _ticker, market, _day: ("KR7999997003", market),
    )
    with pytest.raises(AlignmentGateIntegrityError, match="RAW_KRX_PARTITION_INTEGRITY_ERROR"):
        tampered_gate.evaluate("999997", "KOSPI", _daily_prices(), SIGNAL_DATE)


@pytest.mark.parametrize(
    ("partition_market", "partition_date"),
    [("KOSDAQ", "2025-01-15"), ("KOSPI", "2025-01-14")],
)
def test_raw_market_cap_never_falls_back_to_other_market_or_date(tmp_path, partition_market, partition_date):
    store = KrxRawStockStore(tmp_path / DEFAULT_RAW_STOCK_ROOT)
    store.save_snapshot(partition_market, partition_date, _raw_snapshot(partition_date), "synthetic-test")
    gate = AlignmentMcap500BGate(
        tmp_path,
        PromotionConfig(enabled=True, effective_signal_date=EFFECTIVE_DATE, operational_activation_approved=True),
        identity_resolver=lambda _ticker, market, _day: ("KR7999997003", market),
    )
    decision = gate.evaluate("999997", "KOSPI", _daily_prices(), SIGNAL_DATE)
    assert decision.allowed is False
    assert decision.reason_code == "REJECT_MCAP_UNRESOLVED"
    assert decision.details["partition_lookup"] == "EXACT_DATE_AND_MARKET_ONLY"


def test_rejected_gate_keeps_current_report_action_from_entering(monkeypatch):
    gate = _active_gate(market_cap=MARKET_CAP_THRESHOLD_KRW - 1)
    monkeypatch.setattr(
        a_fast_core_report,
        "to_weekly",
        lambda _daily: pd.DataFrame(index=pd.DatetimeIndex([SIGNAL_DATE])),
    )
    monkeypatch.setattr(
        a_fast_core_report,
        "evaluate_pattern_a_fast",
        lambda *_args, **_kwargs: {
            "pattern_a_stage": "TRANSITION",
            "fast_machine_stage": "TRIGGER",
            "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME",
            "fast_daily_risk_state": "NORMAL",
            "fast_score_status": "READY",
        },
    )

    def fake_simulator(*, entry_signal_filter, **_kwargs):
        assert entry_signal_filter(SIGNAL_DATE, {}) is False
        return []

    monkeypatch.setattr(a_fast_core_report, "simulate_ticker_core_v02_reentry", fake_simulator)
    section = a_fast_core_report.build_a_fast_core_section(
        ticker="999997",
        name="synthetic",
        market="KOSPI",
        daily=_daily_prices(),
        requested_as_of=SIGNAL_DATE,
        score_contract={"frozen": True},
        stage_contract={"frozen": True},
        metadata_provenance_mode="CURRENT_VERIFIED",
        promotion_gate=gate,
    )
    assert section.strategy_id == PROMOTED_STRATEGY_ID
    assert section.action == "WAIT"
    assert section.entry_conditions.all_conditions_met is False
    assert section.entry_conditions.alignment_mcap_500b_status == "REJECT_MCAP_BELOW_500B"
    assert section.promotion_gate_audit[0]["reason_code"] == "REJECT_MCAP_BELOW_500B"
