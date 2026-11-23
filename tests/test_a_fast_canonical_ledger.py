from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import fast_ledger_provenance as provenance
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.reporting import a_fast_canonical_ledger as ledger
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    HISTORICAL_ALIGNMENT_REPLAY_MODE,
    PROMOTED_STRATEGY_ID,
    AlignmentGateIntegrityError,
    GateDecision,
)
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import ExecutionPriceUnavailableError

from tests.test_a_fast_open_evaluation_unavailable import open_authority


class Gate:
    def resolve_common_pit_component(self, ticker, day):
        return {"isu_cd": "KR7000001000", "market": "KOSPI", "effective_from": "2025-01-01"}

    def evaluate_historical_alignment(self, ticker, market, daily, day):
        return GateDecision(True, "PASS_ALIGNMENT_MCAP_500B", {
            "ticker": ticker, "market": market, "isu_cd": "KR7000001000", "signal_date": str(day)[:10],
        })


@pytest.fixture
def strategy_inputs(monkeypatch, open_authority):
    prior, prices, days = open_authority
    for row in [*prior["a_fast_core"]["trade_history"], prior["a_fast_core"]["current_trade"]]:
        row["entry_strategy_id"] = row["exit_strategy_id"] = PROMOTED_STRATEGY_ID
    context = lambda _a, _b, _c: object()
    monkeypatch.setattr(ledger, "build_precomputed_ticker_context", context)
    monkeypatch.setattr(ledger, "build_historical_snapshot_from_context", lambda *_a, **_k: object())
    monkeypatch.setattr(ledger, "evaluate_pattern_a", lambda _: SimpleNamespace(stage=PatternAStage.WEAK, score=0.0))
    monkeypatch.setattr(ledger, "evaluate_pattern_a_fast", lambda *_a, **_k: {
        "fast_machine_stage": "TRIGGER", "fast_machine_stage_status": "READY",
        "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
        "fast_score_status": "READY", "pattern_a_stage": "TRANSITION",
    })
    prior.update(requested_as_of="2025-02-03")
    prices["open"] = prices["close"]
    return prior, prices, days


def run(prior, prices, days, *, gate=None, ends=None):
    return ledger.advance_a_fast_ledger(
        "000001", "Example", "KOSPI", prices, prior_report=prior, prior_reference=pd.Timestamp(prior["reference_market_date"]),
        reference=days[-1], requested=days[-1], calendar=MarketCalendarAuthority(days, ends or [days[2]]),
        score_contract={}, stage_contract={}, promotion_gate=gate or Gate(), execution_open_resolver=None,
    )


def test_unavailable_carries_sealed_open_and_hwm(strategy_inputs, monkeypatch):
    old, prices, days = strategy_inputs
    before = deepcopy(old)
    monkeypatch.setattr(ledger, "evaluate_pattern_a", lambda _: SimpleNamespace(stage=None, score=None))
    result = run(old, prices, days)
    assert old == before
    assert (result.canonical_position, result.strategy_state, result.action) == ("OPEN", "DATA_UNAVAILABLE", "NONE")
    assert result.protection_state.progressed_hwm_score == 85
    assert result.protection_state.current_pattern_a_score is None
    assert result.protection_state.exit4_state == "ARMED"
    assert asdict(result.trade_history[0]) == before["a_fast_core"]["trade_history"][0]


def test_carried_exit_fills_at_next_certified_open_after_holiday(strategy_inputs):
    old, prices, days = strategy_inputs
    core = old["a_fast_core"]
    core["current_trade"].update(pending_exit_signal_date="2025-02-03", pending_exit_type=ledger.LOSS_GUARD_EXIT)
    core["trade_history"][-1].update(exit_signal_date="2025-02-03", exit_type=ledger.LOSS_GUARD_EXIT)
    core["action"] = "EXIT_NEXT_OPEN"
    result = run(old, prices.iloc[-1:], days.delete(-2))
    row = result.trade_history[0]
    assert row.trade_status == "REALIZED" and row.exit_execution_date == "2025-02-05"
    assert row.exit_price == 97.0 and row.exit_signal_date == "2025-02-03"


def test_new_loss_guard_then_new_entry_appends_one_sequence(strategy_inputs):
    old, prices, days = strategy_inputs
    protection = old["a_fast_core"]["protection_state"]
    protection.update(loss_guard_state="ACTIVE", phase="PRE_PROGRESSED", loss_guard_threshold_pct=-15.0)
    prices.loc[days[-2], "close"] = 84.0
    later = pd.to_datetime(["2025-02-07", "2025-02-10"])
    prices = pd.concat([prices, pd.DataFrame({"open": [98.0, 101.0], "close": [98.0, 102.0]}, index=later)])
    result = run(old, prices, days.append(later))
    first, second = result.trade_history
    assert (first.trade_status, first.exit_type, first.exit_execution_date) == ("REALIZED", ledger.LOSS_GUARD_EXIT, "2025-02-05")
    assert (second.trade_id, second.entry_signal_date, second.entry_execution_date) == ("000001_02", "2025-02-07", "2025-02-10")
    assert second.previous_exit_type == ledger.LOSS_GUARD_EXIT
    assert result.current_trade.trade_id == second.trade_id


def test_missing_exact_execution_price_does_not_shift_exit(strategy_inputs):
    old, prices, days = strategy_inputs
    core = old["a_fast_core"]
    core["current_trade"].update(pending_exit_signal_date="2025-02-03", pending_exit_type=ledger.LOSS_GUARD_EXIT)
    core["trade_history"][-1].update(exit_signal_date="2025-02-03", exit_type=ledger.LOSS_GUARD_EXIT)
    with pytest.raises(ExecutionPriceUnavailableError, match="2025-02-04"):
        run(old, prices.iloc[-1:], days)


def test_pit_change_stops_existing_position(strategy_inputs):
    old, prices, days = strategy_inputs

    class Changed(Gate):
        def resolve_common_pit_component(self, ticker, day):
            component = super().resolve_common_pit_component(ticker, day)
            if day == "2025-02-04":
                component["effective_from"] = day
            return component

    with pytest.raises(AlignmentGateIntegrityError, match="PIT_COMPONENT_CHANGED"):
        run(old, prices, days, gate=Changed())


def test_missing_month_close_does_not_produce_exit(strategy_inputs, monkeypatch):
    old, prices, days = strategy_inputs
    extra = pd.Timestamp("2025-02-28")
    monkeypatch.setattr(ledger, "evaluate_pattern_a", lambda _: SimpleNamespace(stage=None, score=None))
    result = run(old, prices, days.append(pd.DatetimeIndex([extra])), ends=[days[2], extra])
    assert result.canonical_position == "OPEN" and result.action == "NONE"
    assert result.protection_state.progressed_hwm_score == 85.0
    assert result.trade_history[0].exit_signal_date is None


def test_sealed_prior_realized_and_mode_digest_fail_closed(tmp_path, strategy_inputs, monkeypatch):
    old, prices, days = strategy_inputs
    archived = old["a_fast_core"]
    archived["trade_history"][0].update(
        exit_signal_date="2025-01-31", exit_execution_date="2025-02-03", exit_price=95.0,
        exit_type="EXIT3_PROGRESSED_TO_WEAK", trade_status="REALIZED", return_pct=-5.0,
    )
    archived.update(canonical_position="FLAT", current_trade=None, protection_state=None, action="WAIT")
    earlier = provenance.PriorCanonicalLedger({
        "requested_as_of":"2025-02-03", "reference_market_date":"2025-02-03",
        "strategy_replay_mode":HISTORICAL_ALIGNMENT_REPLAY_MODE, "strategy_replay_digest":"a"*64,
        "report_files_sha256":"b"*64, "report_count":1,
    }, {"000001":(Path("prior.json"), old)})
    result = run(old, prices, days)
    current = {**old, "requested_as_of":"2025-02-05", "reference_market_date":"2025-02-05", "a_fast_core":asdict(result)}
    folder = tmp_path/"json"
    folder.mkdir()
    p = folder/"000001_Example.json"
    p.write_text(provenance.canonical_json(current))
    monkeypatch.setattr(provenance, "_sealed_prior", lambda *_a: earlier)
    monkeypatch.setattr(provenance, "load_rolling_production_market_calendar", lambda _: MarketCalendarAuthority(days, [days[2]]))
    ok = provenance.finalize_incremental_alignment_reports(tmp_path, "2025-02-05", "2025-02-05", earlier, tmp_path)
    assert ok["valid"] and ok["trade_count"] == 1
    tampered = provenance.read_json(p)
    tampered["a_fast_core"]["trade_history"][0]["return_pct"] = -1
    p.write_text(provenance.canonical_json(tampered))
    invalid = provenance.validate_incremental_alignment_corpus(tmp_path, "2025-02-05", "2025-02-05", root=tmp_path)
    assert not invalid["valid"] and "PRIOR_REALIZED_CHANGED" in invalid["reason_codes"][0]
    valid_row = {**current["a_fast_core"], "strategy_replay_scope":ok["strategy_replay_scope"], "strategy_replay_digest":"f"*64}
    p.write_text(provenance.canonical_json({**current,"a_fast_core":valid_row}))
    invalid = provenance.validate_incremental_alignment_corpus(tmp_path, "2025-02-05", "2025-02-05", root=tmp_path)
    assert not invalid["valid"] and "DIGEST_MISMATCH" in invalid["reason_codes"][0]


def test_stock_report_schema_preserves_both_published_ledger_modes():
    from jsonschema import Draft7Validator

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs/reporting/schema_v07.json").read_text())
    validator = Draft7Validator(schema["definitions"]["aFastCoreSection"])
    common = {
        "type": "PUBLISHED_COMMON_REPORTS", "report_count": 1,
        "requested_as_of": "2025-02-05", "reference_market_date": "2025-02-05",
        "output_strategy_id": PROMOTED_STRATEGY_ID,
    }
    ledger_core = {
        "strategy_id": PROMOTED_STRATEGY_ID, "strategy_replay_digest": "a" * 64, "trade_history": [],
    }
    incremental = {
        **ledger_core, "strategy_replay_mode": ledger.CANONICAL_LEDGER_INCREMENTAL_V01,
        "promotion_gate_status": None, "effective_signal_date": None,
        "strategy_replay_scope": {
            **common, "new_sessions": ["2025-02-05"], "event_count": 0, "events_sha256": "b" * 64,
            "prior_canonical": {
                "requested_as_of": "2025-02-03", "reference_market_date": "2025-02-03", "report_count": 1,
                "strategy_replay_mode": HISTORICAL_ALIGNMENT_REPLAY_MODE,
                "strategy_replay_digest": "c" * 64, "report_files_sha256": "d" * 64,
            },
        },
    }
    full = {
        **ledger_core, "strategy_replay_mode": HISTORICAL_ALIGNMENT_REPLAY_MODE,
        "strategy_replay_scope": {
            **common, "first_v2_candidate_signal_date": None, "last_v2_candidate_signal_date": None,
            "first_alignment_gate_pass_signal_date": None,
            "base_candidate_signal_count": 0, "alignment_gate_pass_count": 0,
        },
    }
    assert validator.is_valid(incremental) and validator.is_valid(full)
    assert not validator.is_valid({**incremental, "strategy_replay_mode": HISTORICAL_ALIGNMENT_REPLAY_MODE})
    assert not validator.is_valid({**incremental, "promotion_gate_status": "ACTIVE"})
    missing_hash = deepcopy(incremental)
    del missing_hash["strategy_replay_scope"]["prior_canonical"]["report_files_sha256"]
    assert not validator.is_valid(missing_hash)
