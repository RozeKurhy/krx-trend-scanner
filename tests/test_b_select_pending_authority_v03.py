"""Prior pending-entry authority continuity and fail-closed regressions."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import build_b_select_core_v2_status as status


@pytest.fixture
def authority_case(tmp_path, monkeypatch):
    ticker, isu = "123456", "KR7123456000"
    component = f"{ticker}:{isu}:000"
    signal, previous, reference = "2024-08-30", "2024-07-31", "2024-09-03"
    days = [previous, "2024-08-29", signal, "2024-09-02", reference]
    interval = {"ticker": ticker, "isu_cd": isu, "market": "KOSDAQ", "state": "COMMON",
                "effective_from": "2024-01-01", "effective_to": reference}
    identity = {"ticker": ticker, "isu_cd": isu, "market": "KOSDAQ", "component_id": component,
                "effective_from": interval["effective_from"], "effective_to": interval["effective_to"]}
    pending = {"kind": "ENTRY", "signal_date": signal, "execution_date": None,
               "trade_sequence": 1, "strategy_id": status.STRATEGY_ID}
    item = {"ticker": ticker, "isu_cd": isu, "component_id": component, "name": "fixture", "market": "KOSDAQ",
            "asset_type": "COMMON", "action": "ENTER_NEXT_OPEN", "canonical_position": "FLAT",
            "strategy_state": "ENTRY_PENDING", "pending_event": pending, "current_trade": None,
            "trade_history": [], "entry_pattern_a_stage": "PROGRESSED", "entry_previous_pattern_a_stage": "TRANSITION",
            "entry_previous_pattern_a_stage_date": previous}
    row = {"ticker": ticker, "isu_cd": isu, "component_id": component, "entry_signal_date": signal,
           "entry_pattern_a_stage_recomputed": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION",
           "previous_pattern_a_stage_date": previous, "source": "REPOSITORY_V2_EXACT_SESSION_EVALUATORS"}
    prior = {"status": "PASS", "strategy_id": status.STRATEGY_ID, "reference_market_date": signal,
             "items": [item], "canonical_trade_history": [], "canonical_trade_history_row_count": 0,
             "canonical_current_open_positions": [], "canonical_current_open_position_count": 0,
             "canonical_pending_events": [{**pending, "ticker": ticker, "isu_cd": isu}],
             "canonical_pending_event_count": 1, "catchup_audit": {"catchup_session_dates": [signal],
             "recovered_month_end_dates": []}, "catchup_entry_pattern_a_authorities": [row]}
    source_dir = tmp_path / "artifacts/reporting/stock_reports/20240903/json"
    source_dir.mkdir(parents=True)
    source_path = source_dir / f"{ticker}_fixture.json"
    source = {"ticker": ticker, "market": "KOSDAQ", "asset_type": "COMMON", "requested_as_of": reference,
              "reference_market_date": reference, "monthly_history": {"full_monthly_history": [
                  {"as_of": previous, "stage": "TRANSITION", "score": 0.0, "data_available": True, "close": 98.0},
                  {"as_of": signal, "stage": "PROGRESSED", "score": 0.0, "data_available": True, "close": 102.0},
              ]}}
    source_path.write_text(json.dumps(source), encoding="utf-8")
    report = {"identity": {"ticker": ticker, "isu_cd": isu, "market": "KOSDAQ", "asset_type": "COMMON"},
              "technical_details": {"source_report": str(source_path.relative_to(tmp_path))},
              "pattern": {"history_12m": source["monthly_history"]["full_monthly_history"]}}

    class Repository:
        def __init__(self):
            self.daily = pd.DataFrame({"open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0],
                                       "volume": [1000], "trading_value": [100000]}, index=pd.to_datetime([signal]))
            self.daily.attrs["session_projection_audit"] = {"projected_date_set_exact_match": True, "silent_inner_drop_count": 0,
                                                            "unexplained_adjusted_only_dates": [], "rejected_raw_only_dates": []}
            self.raw = self.daily.copy()

        def get_daily(self, *_args):
            return self.daily

        def get_raw_daily(self, *_args):
            return self.raw

    context = {"date": signal, "exact_session_observed": True, "observed_close": 102.0,
               "pattern_b_state": "DEPRESSED", "pattern_b_evaluation_status": "READY", "pattern_a_stage": "PROGRESSED",
               "previous_pattern_a_stage": "TRANSITION", "previous_pattern_a_stage_date": previous}
    monkeypatch.setattr(status, "_build_exact_session_contexts", lambda **_kwargs: [dict(context)])
    return {"root": tmp_path, "target_as_of": reference, "reference_market_date": reference, "prior_status": prior,
            "prior_item": item, "identity": identity, "intervals": [interval],
            "interval_components": {status.pattern_b_source.interval_key(interval): component}, "trading_dates": days,
            "month_end_sessions": {previous, signal}, "candidate_rows": [], "report": report, "repository": Repository(),
            "source_path": source_path, "source": source, "context": context}


def resolve(case):
    return status._inherit_prior_pending_entry_context(**{k: v for k, v in case.items()
        if k not in {"source_path", "source", "context"}})


def test_pending_authority_is_inherited_from_the_original_signal(authority_case):
    assert resolve(authority_case) == {"entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "TRANSITION", "entry_previous_pattern_a_stage_date": "2024-07-31"}


def test_consistent_sealed_candidate_is_cross_checked(authority_case):
    row = deepcopy(authority_case["prior_status"]["catchup_entry_pattern_a_authorities"][0])
    authority_case["candidate_rows"].append(row)
    assert resolve(authority_case)["entry_pattern_a_stage"] == "PROGRESSED"


def test_stage_authority_does_not_require_a_numeric_score(authority_case):
    row = authority_case["source"]["monthly_history"]["full_monthly_history"][-1]
    row.update(score=None, data_available=False)
    authority_case["source_path"].write_text(json.dumps(authority_case["source"]), encoding="utf-8")
    assert resolve(authority_case)["entry_pattern_a_stage"] == "PROGRESSED"


def test_verified_pending_survives_missing_session_and_fills_once(authority_case):
    approved = resolve(authority_case)
    signal = authority_case["prior_item"]["pending_event"]["signal_date"]
    pending = {"kind": "ENTRY", "signal_date": signal, "execution_date": None,
               "sequence": 1, "strategy_id": status.STRATEGY_ID}
    first = status._replay_with_unobserved_pending(
        [], [], trading_dates=[signal, "2024-09-02"], exact_opens={}, reference_market_date="2024-09-02",
        initial_pending=pending, execution_by_signal_date={signal: None}, unobserved_sessions={"2024-09-02"},
    )
    assert first["position"] is None and first["pending"]["execution_date"] is None
    second = status._replay_with_unobserved_pending(
        [{"date": "2024-09-03", "state": "DEPRESSED"}], [], trading_dates=[signal, "2024-09-02", "2024-09-03"],
        exact_opens={"2024-09-03": 110.0}, reference_market_date="2024-09-03", initial_pending=first["pending"],
        execution_by_signal_date={signal: "2024-09-03"}, unobserved_sessions={"2024-09-02"},
    )
    assert second["pending"] is None and second["completed_trades"] == []
    assert second["position"]["entry_execution_date"] == "2024-09-03" and second["position"]["entry_open"] == 110.0
    assert approved["entry_pattern_a_stage"] == "PROGRESSED"
    third = status._replay_with_unobserved_pending(
        [{"date": "2024-09-04", "state": "DEPRESSED"}], [],
        trading_dates=[signal, "2024-09-02", "2024-09-03", "2024-09-04"], exact_opens={},
        reference_market_date="2024-09-04", initial_position=second["position"], initial_trade_sequence=1,
    )
    assert third["position"]["trade_sequence"] == 1 and third["pending"] is None and third["completed_trades"] == []


def test_prior_pending_cannot_disappear_when_current_report_is_missing(authority_case, monkeypatch, tmp_path):
    case = authority_case
    prior = case["prior_status"]
    prior["source_authorities"] = {"signal_cadence": "MONTH_END_ENTRY_DAILY_NORMAL_EXIT"}
    index = {"requested_as_of": case["target_as_of"], "reference_market_date": case["reference_market_date"], "items": []}
    index_path = tmp_path / "empty-index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    calendar = SimpleNamespace(trading_dates=pd.to_datetime(case["trading_dates"]),
                               metadata={"certified_through": case["reference_market_date"]})
    sample = pd.DataFrame([{"ticker": case["identity"]["ticker"], "isu_cd": case["identity"]["isu_cd"],
                            "component_id": case["identity"]["component_id"],
                            "snapshot_date": case["trading_dates"][0], "state": "DEPRESSED"}])
    monkeypatch.setattr(status.pattern_b_source, "_load_authorities", lambda _root: (case["intervals"], case["trading_dates"], {}))
    monkeypatch.setattr(status.pattern_b_source, "_interval_components", lambda *_args: (case["interval_components"], {}))
    monkeypatch.setattr(status, "_cached_rolling_production_market_calendar", lambda _root: calendar)
    monkeypatch.setattr(status, "_current_identity_map", lambda *_args: {case["identity"]["ticker"]: case["identity"]})
    monkeypatch.setattr(status, "_load_monthly_states", lambda *_args: (sample, 185))
    monkeypatch.setattr(status, "_load_candidate_signals", lambda _root: [])
    monkeypatch.setattr(status, "_latest_prior_status", lambda *_args: (prior, "fixture-prior"))
    with pytest.raises(status.BSelectStatusError, match="PRIOR_PENDING_ENTRY_CURRENT_SOURCE_MISSING"):
        status.build_b_select_status(repo_root=case["root"], index_path=index_path, stocks_path=tmp_path,
                                     target_as_of=case["target_as_of"], reference_market_date=case["reference_market_date"])


@pytest.mark.parametrize("defect", [
    "missing_authority", "duplicate_authority", "wrong_source", "unapproved_observation_date", "canonical_missing",
    "canonical_duplicate", "canonical_conflict", "wrong_strategy", "wrong_sequence", "duplicate_sequence",
    "item_context_conflict", "candidate_duplicate", "candidate_conflict", "wrong_ticker", "wrong_isu",
    "wrong_component", "ambiguous_pit", "non_month_end", "future_signal", "invalid_previous_stage_date",
    "previous_stage_unqualified", "source_history_missing", "source_history_conflict", "unobserved_signal",
    "pattern_b_not_depressed", "pattern_a_mismatch", "no_v2_signal", "zero_signal_open", "raw_volume_mismatch",
    "v2_projection_gap", "source_file_missing", "no_v2_frame", "no_raw_frame", "item_action_conflict",
    "prior_item_missing", "pending_kind_mismatch", "prior_status_invalid", "duplicate_source_history", "intermediate_pit_gap",
])
def test_pending_authority_fails_closed(authority_case, defect):
    case = authority_case
    prior, item, authority = case["prior_status"], case["prior_item"], case["prior_status"]["catchup_entry_pattern_a_authorities"][0]
    event = prior["canonical_pending_events"][0]
    if defect == "missing_authority": prior["catchup_entry_pattern_a_authorities"] = []
    elif defect == "duplicate_authority": prior["catchup_entry_pattern_a_authorities"].append(deepcopy(authority))
    elif defect == "wrong_source": authority["source"] = "UNVERIFIED"
    elif defect == "unapproved_observation_date": prior["catchup_audit"]["catchup_session_dates"] = []
    elif defect == "canonical_missing": prior["canonical_pending_events"] = []; prior["canonical_pending_event_count"] = 0
    elif defect == "canonical_duplicate": prior["canonical_pending_events"].append(deepcopy(event)); prior["canonical_pending_event_count"] = 2
    elif defect == "canonical_conflict": event["trade_sequence"] = 2
    elif defect == "wrong_strategy": event["strategy_id"] = item["pending_event"]["strategy_id"] = "OTHER"
    elif defect == "wrong_sequence": event["trade_sequence"] = item["pending_event"]["trade_sequence"] = 0
    elif defect == "duplicate_sequence": prior["canonical_trade_history"] = [{"ticker": item["ticker"], "isu_cd": item["isu_cd"], "trade_sequence": 1}]
    elif defect == "item_context_conflict": item["entry_previous_pattern_a_stage"] = "EARLY_TREND"
    elif defect == "candidate_duplicate": case["candidate_rows"].extend([deepcopy(authority), deepcopy(authority)])
    elif defect == "candidate_conflict": case["candidate_rows"].append({**authority, "previous_pattern_a_stage": "EARLY_TREND"})
    elif defect == "wrong_ticker": case["identity"]["ticker"] = "654321"
    elif defect == "wrong_isu": case["identity"]["isu_cd"] = "KR7999999999"
    elif defect == "wrong_component": case["identity"]["component_id"] = "OTHER"
    elif defect == "ambiguous_pit": case["intervals"].append({**case["intervals"][0], "isu_cd": "KR7999999999"})
    elif defect == "intermediate_pit_gap":
        first = {**case["intervals"][0], "effective_to": "2024-08-30"}
        second = {**case["intervals"][0], "effective_from": "2024-09-03"}
        case["intervals"] = [first, second]
        case["interval_components"] = {status.pattern_b_source.interval_key(row): case["identity"]["component_id"]
                                       for row in case["intervals"]}
    elif defect == "non_month_end": case["month_end_sessions"].remove("2024-08-30")
    elif defect == "future_signal": prior["reference_market_date"] = "2024-08-29"
    elif defect == "invalid_previous_stage_date":
        authority["previous_pattern_a_stage_date"] = item["entry_previous_pattern_a_stage_date"] = "2024-07-30"
    elif defect == "previous_stage_unqualified": authority["previous_pattern_a_stage"] = item["entry_previous_pattern_a_stage"] = "WEAK"
    elif defect in {"source_history_missing", "source_history_conflict"}:
        rows = case["source"]["monthly_history"]["full_monthly_history"]
        if defect == "source_history_missing": rows.pop()
        else: rows[-1]["stage"] = "WEAK"
        case["source_path"].write_text(json.dumps(case["source"]), encoding="utf-8")
    elif defect == "unobserved_signal": case["context"]["exact_session_observed"] = False
    elif defect == "pattern_b_not_depressed": case["context"]["pattern_b_state"] = "NORMAL"
    elif defect == "pattern_a_mismatch": case["context"]["pattern_a_stage"] = "TRANSITION"
    elif defect == "no_v2_signal": case["repository"].daily = case["repository"].daily.iloc[0:0]
    elif defect == "zero_signal_open": case["repository"].daily.loc[:, "open"] = 0.0
    elif defect == "raw_volume_mismatch": case["repository"].raw.loc[:, "volume"] = 2
    elif defect == "v2_projection_gap": case["repository"].daily.attrs["session_projection_audit"]["silent_inner_drop_count"] = 1
    elif defect == "source_file_missing": case["source_path"].unlink()
    elif defect == "no_v2_frame": case["repository"].daily = None
    elif defect == "no_raw_frame": case["repository"].raw = None
    elif defect == "item_action_conflict": item["action"] = "WAIT"
    elif defect == "prior_item_missing": prior["items"] = []
    elif defect == "pending_kind_mismatch": item["pending_event"]["kind"] = "EXIT"
    elif defect == "prior_status_invalid": prior["status"] = "CHECK_REQUIRED"
    elif defect == "duplicate_source_history":
        rows = case["source"]["monthly_history"]["full_monthly_history"]
        rows.append(deepcopy(rows[-1]))
        case["source_path"].write_text(json.dumps(case["source"]), encoding="utf-8")
    with pytest.raises(status.BSelectStatusError):
        resolve(case)


def test_real_prior_pending_fills_once_and_keeps_original_stage_authority(monkeypatch, tmp_path):
    """Reproduce V02's real 045390 failure with one current identity only."""
    from scripts import export_stock_report_web
    root = status.ROOT
    if not (root / "artifacts/reporting/stock_reports/20261108/json").is_dir():
        pytest.skip("local 2026-11-08 Phase4B corpus is required for this real-data integration test")
    saved = status._read_json(root / "artifacts/strategies/b_select_core_v2/production/20261101/status.json")
    item = deepcopy(next(row for row in saved["items"] if row["ticker"] == "045390"))
    pending = deepcopy(next(row for row in saved["canonical_pending_events"] if row["ticker"] == "045390"))
    authority = deepcopy(next(row for row in saved["catchup_entry_pattern_a_authorities"] if row["ticker"] == "045390"))
    prior = {**saved, "items": [item], "canonical_trade_history": [], "canonical_trade_history_row_count": 0,
             "canonical_current_open_positions": [], "canonical_current_open_position_count": 0,
             "canonical_pending_events": [pending], "canonical_pending_event_count": 1,
             "catchup_entry_pattern_a_authorities": [authority]}
    monkeypatch.setattr(status, "_latest_prior_status", lambda *_args, **_kwargs: (prior, "fixture-prior-status"))
    index, reports, _ = export_stock_report_web.build_web_payload(
        root, target_as_of="2026-11-08", reference_market_date="2026-11-06", include_etf=False)
    index["items"] = [row for row in index["items"] if row.get("ticker") == "045390" and row.get("report_available")]
    assert len(index["items"]) == 1
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    (stocks / "045390.json").write_text(json.dumps(reports["045390"], ensure_ascii=False), encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    result = status.build_b_select_status(repo_root=root, index_path=index_path, stocks_path=stocks,
        target_as_of="2026-11-08", reference_market_date="2026-11-06")
    trades = [row for row in result["canonical_trade_history"] if row["ticker"] == "045390"]
    assert len(trades) == 1
    assert trades[0]["entry_execution_date"] == "2026-11-02" and trades[0]["entry_open"] == 2530.0
    assert trades[0]["trade_sequence"] == 1 and trades[0]["trade_status"] == "OPEN_AT_REFERENCE"
    assert not result["canonical_pending_events"]
    actual = result["items"][0]
    assert actual["entry_pattern_a_stage"] == "PROGRESSED"
    assert actual["entry_previous_pattern_a_stage"] == "TRANSITION"
    assert actual["entry_previous_pattern_a_stage_date"] == "2026-09-30"
