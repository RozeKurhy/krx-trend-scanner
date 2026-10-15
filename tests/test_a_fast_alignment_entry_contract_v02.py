from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

import trend_scanner.reporting.a_fast_core_report as core_report


@dataclass
class _GateDecision:
    allowed: bool
    reason_code: str
    details: dict[str, object]

    def to_dict(self, signal_date: pd.Timestamp) -> dict[str, object]:
        return {
            "signal_date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "details": self.details,
        }


class _PromotionGate:
    def __init__(self, decision: _GateDecision) -> None:
        self.decision = decision
        self.evaluated = 0

    def evaluate_historical_alignment(self, *_args: object) -> _GateDecision:
        self.evaluated += 1
        return self.decision

    def is_promoted_signal(self, _signal_date: pd.Timestamp) -> bool:
        return False

    def has_promoted_signal_on_or_before(self, _as_of: pd.Timestamp) -> bool:
        return False

    def strategy_id_for_as_of(self, _as_of: pd.Timestamp) -> str:
        return core_report.V2_STRATEGY_ID


def _section(
    monkeypatch,
    *,
    investability_status: str,
    decision: _GateDecision | None = None,
    fast_daily_risk: str = "NORMAL",
    historical_alignment_replay: bool = True,
    stale_current_session: bool = False,
    simulator_exception: Exception | None = None,
):
    dates = pd.bdate_range("2026-07-01", periods=65)
    daily = pd.DataFrame(
        {
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000,
            "trading_value": 100_000.0,
        },
        index=dates,
    )
    requested_as_of = dates[-1] + pd.offsets.BDay(1) if stale_current_session else dates[-1]
    market_calendar = SimpleNamespace(trading_dates=pd.bdate_range(dates[0], requested_as_of))
    gate = _PromotionGate(decision or _GateDecision(True, "PASS_ALIGNMENT_MCAP_500B", {"market_cap_krw": 600_000_000_000}))
    def simulate(**_kwargs):
        if simulator_exception is not None:
            raise simulator_exception
        return []

    monkeypatch.setattr(core_report, "simulate_ticker_core_v02_reentry", simulate)
    monkeypatch.setattr(core_report, "to_weekly", lambda frame: pd.DataFrame(index=[frame.index[-1]]))
    monkeypatch.setattr(
        core_report,
        "evaluate_pattern_a_fast",
        lambda *_args, **_kwargs: {
            "pattern_a_stage": "TRANSITION",
            "fast_machine_stage": "TRIGGER",
            "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME",
            "fast_daily_risk_state": fast_daily_risk,
            "fast_score_status": "READY",
        },
    )
    result = core_report._build_a_fast_core_section_impl(
        ticker="123456",
        name="Test Co",
        market="KOSPI",
        daily=daily,
        requested_as_of=requested_as_of,
        score_contract={"contract": "test"},
        stage_contract={"contract": "test"},
        asset_type="COMMON",
        investability_status=investability_status,
        is_common_stock=True,
        metadata_trusted=True,
        market_calendar=market_calendar,
        promotion_gate=gate,
        historical_alignment_replay=historical_alignment_replay,
    )
    return result, gate


def test_alignment_phase10_liquidity_failure_does_not_block_entry(monkeypatch):
    section, gate = _section(monkeypatch, investability_status="FILTERED_LIQUIDITY")

    assert section.strategy_state == "ENTRY"
    assert section.action == "ENTER_NEXT_OPEN"
    assert section.entry_conditions is not None
    assert section.entry_conditions.investability_required is False
    assert section.entry_conditions.investability_pass is None
    assert section.entry_conditions.investability_reference_status == "FILTERED_LIQUIDITY"
    assert "NOT_INVESTABLE (FILTERED_LIQUIDITY)" not in section.entry_conditions.failed_conditions
    assert gate.evaluated == 1


def test_alignment_phase10_data_unavailable_alone_does_not_block_entry(monkeypatch):
    section, gate = _section(monkeypatch, investability_status="DATA_UNAVAILABLE")

    assert section.strategy_state == "ENTRY"
    assert section.action_reason == "ALL_ENTRY_CONDITIONS_MET"
    assert section.entry_conditions is not None
    assert section.entry_conditions.investability_pass is None
    assert section.entry_conditions.investability_reference_status == "DATA_UNAVAILABLE"
    assert gate.evaluated == 1


def test_alignment_stale_price_series_fails_closed_even_when_phase10_is_unavailable(monkeypatch):
    section, gate = _section(
        monkeypatch,
        investability_status="DATA_UNAVAILABLE",
        stale_current_session=True,
    )

    assert section.strategy_state == "DATA_UNAVAILABLE"
    assert section.canonical_position == "DATA_UNAVAILABLE"
    assert section.action == "NONE"
    assert section.action_reason == "CURRENT_SESSION_PRICE_UNAVAILABLE"
    assert section.entry_conditions is None
    assert gate.evaluated == 0


def test_alignment_keeps_wait_when_another_required_v2_condition_fails(monkeypatch):
    section, gate = _section(
        monkeypatch,
        investability_status="FILTERED_LIQUIDITY",
        fast_daily_risk="EXTREME",
    )

    assert section.strategy_state == "WAIT"
    assert section.action == "WAIT"
    assert section.action_reason == "ENTRY_CONDITIONS_NOT_MET"
    assert section.entry_conditions is not None
    assert section.entry_conditions.all_conditions_met is False
    assert "DAILY_RISK_EXTREME" in section.entry_conditions.failed_conditions
    assert not any("INVESTABILITY" in item for item in section.entry_conditions.failed_conditions)
    assert gate.evaluated == 0


def test_alignment_cap_gate_rejection_still_blocks_entry_when_phase10_fails(monkeypatch):
    section, gate = _section(
        monkeypatch,
        investability_status="FILTERED_MARKET_CAP",
        decision=_GateDecision(
            False,
            "REJECT_MCAP_BELOW_500B",
            {"market_cap_krw": 499_999_999_999, "market_cap_threshold_krw": 500_000_000_000},
        ),
    )

    assert section.strategy_state == "WAIT"
    assert section.action_reason == "REJECT_MCAP_BELOW_500B"
    assert section.entry_conditions is not None
    assert section.entry_conditions.all_conditions_met is False
    assert section.entry_conditions.alignment_mcap_500b_pass is False
    assert gate.evaluated == 1


def test_operational_v2_keeps_phase10_as_required_gate(monkeypatch):
    section, gate = _section(
        monkeypatch,
        investability_status="FILTERED_LIQUIDITY",
        historical_alignment_replay=False,
    )

    assert section.strategy_state == "WAIT"
    assert section.action_reason == "INVESTABILITY_FILTERED_FILTERED_LIQUIDITY"
    assert section.entry_conditions is not None
    assert section.entry_conditions.investability_required is True
    assert section.entry_conditions.investability_pass is False
    assert section.entry_conditions.investability_reference_status is None
    assert gate.evaluated == 0


def test_unverified_next_session_execution_price_is_explicitly_unavailable(monkeypatch):
    section, _gate = _section(
        monkeypatch,
        investability_status="INVESTABLE",
        simulator_exception=core_report.ExecutionPriceUnavailableError(
            pd.Timestamp("2026-07-02"), "EXACT_SESSION_HAS_NO_VERIFIED_ADJUSTED_OPEN"
        ),
    )

    assert section.strategy_state == "DATA_UNAVAILABLE"
    assert section.canonical_position == "DATA_UNAVAILABLE"
    assert section.action == "NONE"
    assert section.action_reason == "EXECUTION_PRICE_UNRESOLVED"
    assert "2026-07-02" in section.interpretation
