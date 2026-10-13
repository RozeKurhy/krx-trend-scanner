from __future__ import annotations

import csv
import json
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.reporting import a_fast_core_report
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    ACTIVATION_HISTORY_SCHEMA,
    DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH,
    ActivationInterval,
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
    load_activation_history,
    monthly_alignment_decision,
    verify_permanent_exclusion_registry,
)


SIGNAL_DATE = pd.Timestamp("2025-01-15")
EFFECTIVE_DATE = "2025-01-01"


def _activation_history(
    effective_signal_date: str = EFFECTIVE_DATE,
    rollback_effective_signal_date: str | None = None,
) -> tuple[ActivationInterval, ...]:
    return (ActivationInterval(
        "fixture-activation-001",
        effective_signal_date,
        rollback_effective_signal_date,
        "FIXTURE_APPROVAL",
    ),)


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
        activation_intervals=_activation_history(),
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


def test_approved_activation_history_is_immutable_and_rollback_end_is_exclusive(tmp_path):
    production_root = Path(__file__).resolve().parents[1]
    config = load_promotion_config(production_root)
    assert config.enabled is False
    assert config.effective_signal_date == PENDING_USER_APPROVAL
    assert load_activation_history(production_root, config) == ()

    history_path = tmp_path / DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH
    history_path.parent.mkdir(parents=True)
    history_path.write_text(json.dumps({
        "schema": ACTIVATION_HISTORY_SCHEMA,
        "strategy_id": PROMOTED_STRATEGY_ID,
        "interval_policy": "APPEND_ONLY_SIGNAL_DATE_INTERVALS_ROLLBACK_END_EXCLUSIVE",
        "intervals": [{
            "activation_id": "fixture-activation-001",
            "approval_status": "APPROVED",
            "approval_reference": "FIXTURE_APPROVAL",
            "effective_signal_date": "2025-01-14",
            "rollback_effective_signal_date": "2025-01-16",
        }],
    }), encoding="utf-8")
    history = load_activation_history(tmp_path, PromotionConfig())
    gate = AlignmentMcap500BGate(
        tmp_path,
        PromotionConfig(),
        identity_resolver=lambda _ticker, market, _day: ("KR7999997003", market),
        market_cap_resolver=lambda *_args: MARKET_CAP_THRESHOLD_KRW,
        activation_intervals=history,
    )

    assert gate.strategy_id_for_signal("2025-01-13") == V2_STRATEGY_ID
    assert gate.strategy_id_for_signal("2025-01-14") == PROMOTED_STRATEGY_ID
    assert gate.strategy_id_for_signal("2025-01-15") == PROMOTED_STRATEGY_ID
    assert gate.strategy_id_for_signal("2025-01-16") == V2_STRATEGY_ID
    assert gate.strategy_id_for_as_of("2025-01-20") == V2_STRATEGY_ID
    assert gate.evaluate("999997", "KOSPI", _daily_prices(), "2025-01-15").allowed
    assert gate.evaluate("999997", "KOSPI", _daily_prices(), "2025-01-16").reason_code.startswith("PASS_V2")


def test_active_production_config_requires_matching_open_approved_interval(tmp_path):
    production_root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json"
    config_path.parent.mkdir(parents=True)
    config_payload = json.loads((production_root / "artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json").read_text())
    config_payload.update({
        "enabled": True,
        "effective_signal_date": EFFECTIVE_DATE,
        "operational_activation_approved": True,
    })
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    config = load_promotion_config(tmp_path)
    with pytest.raises(AlignmentGateIntegrityError, match="PROMOTION_ACTIVATION_HISTORY_REQUIRED"):
        AlignmentMcap500BGate(tmp_path, config)
    with pytest.raises(AlignmentGateIntegrityError, match="ACTIVATION_HISTORY_MISSING"):
        load_activation_history(tmp_path, config)

    history_path = tmp_path / DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps({
        "schema": ACTIVATION_HISTORY_SCHEMA,
        "strategy_id": PROMOTED_STRATEGY_ID,
        "intervals": [{
            "activation_id": "fixture-open-001",
            "approval_status": "APPROVED",
            "approval_reference": "FIXTURE_APPROVAL",
            "effective_signal_date": EFFECTIVE_DATE,
            "rollback_effective_signal_date": None,
        }],
    }), encoding="utf-8")
    history = load_activation_history(tmp_path, config)
    gate = AlignmentMcap500BGate(
        tmp_path,
        config,
        identity_resolver=lambda _ticker, market, _day: ("KR7999997003", market),
        activation_intervals=history,
    )
    assert gate.strategy_id_for_signal("2025-01-01") == PROMOTED_STRATEGY_ID
    assert gate.strategy_id_for_signal("2024-12-31") == V2_STRATEGY_ID


def test_activation_history_overlap_fails_closed(tmp_path):
    history_path = tmp_path / DEFAULT_ACTIVATION_HISTORY_RELATIVE_PATH
    history_path.parent.mkdir(parents=True)
    intervals = [
        {"activation_id": "one", "approval_status": "APPROVED", "approval_reference": "A",
         "effective_signal_date": "2025-01-01", "rollback_effective_signal_date": "2025-02-01"},
        {"activation_id": "two", "approval_status": "APPROVED", "approval_reference": "B",
         "effective_signal_date": "2025-01-31", "rollback_effective_signal_date": "2025-03-01"},
    ]
    history_path.write_text(json.dumps({
        "schema": ACTIVATION_HISTORY_SCHEMA,
        "strategy_id": PROMOTED_STRATEGY_ID,
        "intervals": intervals,
    }), encoding="utf-8")
    with pytest.raises(AlignmentGateIntegrityError, match="OVERLAP"):
        load_activation_history(tmp_path, PromotionConfig())


def test_candidate_open_then_rollback_replays_mixed_history_without_reclassifying_trades(
    monkeypatch: pytest.MonkeyPatch,
):
    candidate_open_interval = ActivationInterval(
        "fixture-activation-001", "2025-01-14", None, "FIXTURE_APPROVAL",
    )
    rolled_back_interval = ActivationInterval(
        "fixture-activation-001", "2025-01-14", "2025-01-16", "FIXTURE_APPROVAL",
    )
    identity_resolver = lambda _ticker, market, _day: ("KR7999997003", market)
    cap_resolver = lambda *_args: MARKET_CAP_THRESHOLD_KRW
    active_gate = AlignmentMcap500BGate(
        Path("."),
        PromotionConfig(enabled=True, effective_signal_date="2025-01-14", operational_activation_approved=True),
        identity_resolver=identity_resolver,
        market_cap_resolver=cap_resolver,
        activation_intervals=(candidate_open_interval,),
    )
    rollback_gate = AlignmentMcap500BGate(
        Path("."), PromotionConfig(),
        identity_resolver=identity_resolver,
        market_cap_resolver=cap_resolver,
        activation_intervals=(rolled_back_interval,),
    )
    daily = _daily_prices()
    extra_dates = pd.to_datetime([
        "2025-01-13", "2025-01-14", "2025-01-16", "2025-01-19", "2025-01-20",
    ])
    extra = pd.DataFrame({"close": [101.0, 102.0, 103.0, 104.0, 105.0]}, index=extra_dates)
    daily = pd.concat([daily.loc[~daily.index.isin(extra.index)], extra]).sort_index()

    def make_trade(
        *, trade_id: str, sequence: int, signal: str, execution: str,
        status: str, return_pct: float, exit_signal: str | None = None,
        exit_execution: str | None = None, exit_price: float | None = None,
    ):
        return SimpleNamespace(
            trade_id=trade_id,
            trade_sequence=sequence,
            entry_signal_date=pd.Timestamp(signal),
            entry_execution_date=pd.Timestamp(execution),
            entry_open=100.0,
            entry_pattern_a_stage="EARLY_TREND",
            exit_type="TEST_EXIT" if exit_signal else None,
            exit_signal_date=pd.Timestamp(exit_signal) if exit_signal else None,
            exit_execution_date=pd.Timestamp(exit_execution) if exit_execution else None,
            exit_price=exit_price,
            trade_status=status,
            terminal_return=return_pct,
            previous_exit_type=None,
            previous_exit_execution_date=None,
            lifecycle_class="NORMAL_EARLY_TREND_HANDOFF",
            first_progressed_date=None,
            first_progressed_effective_trading_date=None,
            loss_guard_triggered=False,
        )

    entry_filter_calls: list[tuple[str, bool]] = []

    def fake_simulator(*, entry_signal_filter, cutoff_date, **_kwargs):
        cutoff = pd.Timestamp(cutoff_date).normalize()
        selected = []
        candidates = [
            ("2025-01-13", make_trade(
                trade_id="TICKER_01", sequence=1, signal="2025-01-13", execution="2025-01-14",
                status="REALIZED", return_pct=2.0, exit_signal="2025-01-14",
                exit_execution="2025-01-15", exit_price=102.0,
            )),
            ("2025-01-14", make_trade(
                trade_id="TICKER_02", sequence=2, signal="2025-01-14", execution="2025-01-15",
                status=("OPEN_AT_CUTOFF" if cutoff <= pd.Timestamp("2025-01-15") else "REALIZED"),
                return_pct=(0.0 if cutoff <= pd.Timestamp("2025-01-15") else 5.0),
                exit_signal=(None if cutoff <= pd.Timestamp("2025-01-15") else "2025-01-15"),
                exit_execution=(None if cutoff <= pd.Timestamp("2025-01-15") else "2025-01-16"),
                exit_price=(None if cutoff <= pd.Timestamp("2025-01-15") else 105.0),
            )),
            ("2025-01-19", make_trade(
                trade_id="TICKER_03", sequence=3, signal="2025-01-19", execution="2025-01-20",
                status="OPEN_AT_CUTOFF", return_pct=0.0,
            )),
        ]
        for signal, trade in candidates:
            signal_date = pd.Timestamp(signal)
            if signal_date > cutoff:
                continue
            allowed = entry_signal_filter(signal_date, {}) if entry_signal_filter else True
            entry_filter_calls.append((signal, allowed))
            if allowed:
                selected.append(trade)
        return selected

    monkeypatch.setattr(a_fast_core_report, "simulate_ticker_core_v02_reentry", fake_simulator)
    monkeypatch.setattr(a_fast_core_report, "build_historical_snapshot", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(a_fast_core_report, "evaluate_pattern_a", lambda *_args, **_kwargs: SimpleNamespace(score=10.0))

    def build(as_of: str, gate: AlignmentMcap500BGate):
        return a_fast_core_report.build_a_fast_core_section(
            ticker="999997",
            name="synthetic",
            market="KOSPI",
            daily=daily,
            requested_as_of=pd.Timestamp(as_of),
            score_contract={"frozen": True},
            stage_contract={"frozen": True},
            metadata_provenance_mode="CURRENT_VERIFIED",
            promotion_gate=gate,
        )

    before_rollback = build("2025-01-15", active_gate)
    after_rollback = build("2025-01-20", rollback_gate)
    repeated_after_rollback = build("2025-01-20", rollback_gate)
    assert before_rollback.strategy_id == PROMOTED_STRATEGY_ID
    assert after_rollback.strategy_id == V2_STRATEGY_ID
    assert len(after_rollback.trade_history) == 3
    assert [item.strategy_id for item in after_rollback.trade_history] == [
        V2_STRATEGY_ID, PROMOTED_STRATEGY_ID, V2_STRATEGY_ID,
    ]
    candidate_open = before_rollback.trade_history[1]
    candidate_exited = after_rollback.trade_history[1]
    assert candidate_open.trade_status == "OPEN_AT_CUTOFF"
    assert candidate_exited.trade_status == "REALIZED"
    assert candidate_open.trade_id == candidate_exited.trade_id == "TICKER_02"
    assert candidate_open.trade_sequence == candidate_exited.trade_sequence == 2
    assert candidate_open.entry_signal_date == candidate_exited.entry_signal_date
    assert candidate_open.entry_execution_date == candidate_exited.entry_execution_date
    assert candidate_exited.exit_type == "TEST_EXIT"
    assert candidate_exited.exit_signal_date == pd.Timestamp("2025-01-15")
    assert candidate_exited.exit_execution_date == pd.Timestamp("2025-01-16")
    assert candidate_exited.exit_strategy_id == PROMOTED_STRATEGY_ID
    assert candidate_exited.return_pct == 5.0
    assert [item.__dict__ for item in after_rollback.trade_history] == [
        item.__dict__ for item in repeated_after_rollback.trade_history
    ]
    assert [(row[0], row[1]) for row in entry_filter_calls if row[0] in {"2025-01-14", "2025-01-19"}][-4:] == [
        ("2025-01-14", True), ("2025-01-19", True),
        ("2025-01-14", True), ("2025-01-19", True),
    ]


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
        activation_intervals=_activation_history(),
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
        activation_intervals=_activation_history(),
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
        activation_intervals=_activation_history(),
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
        activation_intervals=_activation_history(),
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
        activation_intervals=_activation_history(),
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
