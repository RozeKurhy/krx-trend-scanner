"""CORRECTION_13 persisted price/parity evidence and candidate semantics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trend_scanner.data import corporate_action_authority as ca


def _controls() -> list[dict[str, str]]:
    families = ["STOCK_SPLIT", "STOCK_SPLIT", "MERGER", "RIGHTS_OFFERING", "BONUS_ISSUE", "MERGER", "RIGHTS_OFFERING", "STOCK_SPLIT"]
    controls = []
    for index, family in enumerate(families, start=1):
        controls.append({
            "control_id": f"CTRL_{index:02d}", "ticker": f"00{index:04d}", "corp_code": f"CORP{index:02d}",
            "authority_record_id": f"RCP{index:02d}", "normalized_event_type": family,
            "price_window_start": "2020-01-01", "price_window_end": "2020-01-31", "official_anchor_date": "2020-01-16",
        })
    return controls


def _prices() -> pd.DataFrame:
    dates = pd.date_range("2020-01-10", periods=11, freq="D")
    return pd.DataFrame({"date": dates, "open": [100] * 11, "high": [101] * 11, "low": [99] * 11, "close": [100] * 11, "volume": [1000] * 11})


def _source_map(controls: list[dict[str, str]]) -> dict[tuple[str, str], pd.DataFrame]:
    return {(control["control_id"], source): _prices() for control in controls for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR")}


def _request_logs(controls: list[dict[str, str]]) -> list[dict[str, object]]:
    logs = []
    for control in controls:
        for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"):
            logs.append({
                "control_id": control["control_id"], "source": source, "request_id": f"MOCK_{source}_{control['ticker']}_{control['control_id']}",
                "outcome": "SUCCESS", "physical_attempt": 1, "price_window_start": control["price_window_start"], "price_window_end": control["price_window_end"],
            })
    return logs


def test_correction13_mocked_full_production_persists_evidence(tmp_path):
    controls = _controls()
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_13(
        output_dir=tmp_path / "v01_fix03_correction_13", repo_root=tmp_path,
        frozen_controls=controls, price_sources=_source_map(controls), request_logs=_request_logs(controls),
    )
    assert result["gate_06_result"] is True
    assert result["persisted_price_evidence_status"] == "EVALUATED"
    assert result["actual_candidate_price_row_count"] == 88
    assert result["actual_pykrx_price_row_count"] == 88
    assert result["exact_date_match_controls"] == 8
    assert result["production_integration_authorized"] is False
    out = tmp_path / "v01_fix03_correction_13"
    assert len(pd.read_csv(out / ca.CORRECTION_13_PARITY_FILE)) == 8
    assert len(pd.read_csv(out / ca.CORRECTION_13_RECONCILIATION_FILE)) == 8
    price = pd.read_csv(out / ca.CORRECTION_13_PRICE_FILE)
    assert set(price.loc[price.source == "NAVER_DIRECT", "control_id"]) == {c["control_id"] for c in controls}
    assert set(price.loc[price.source == "RAW_PYKRX_COMPARATOR", "control_id"]) == {c["control_id"] for c in controls}
    assert json.loads((out / "artifact_manifest.json").read_text()) ["schema"] == "corporate_action_evidence_manifest_v01_fix03_correction_13"


def test_correction13_header_only_evidence_fails_closed():
    controls = _controls()
    result = ca.validate_persisted_price_parity_evidence(
        pd.DataFrame(columns=sorted(ca.PRICE_ROW_REQUIRED_COLUMNS)),
        pd.DataFrame(columns=sorted(ca.PARITY_REQUIRED_COLUMNS)),
        pd.DataFrame(columns=sorted(ca.RECONCILIATION_REQUIRED_COLUMNS)),
        controls,
    )
    assert result.evaluation_status == "INCOMPLETE"
    assert {"PRICE_EVIDENCE_EMPTY", "PARITY_EVIDENCE_EMPTY", "RECONCILIATION_EVIDENCE_EMPTY"} <= set(result.blockers)


def test_correction13_partial_source_coverage_fails_closed(tmp_path):
    controls = _controls()
    sources = _source_map(controls)
    sources.pop((controls[-1]["control_id"], "RAW_PYKRX_COMPARATOR"))
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_13(
        output_dir=tmp_path / "partial", repo_root=tmp_path, frozen_controls=controls, price_sources=sources,
    )
    assert result["gate_06_result"] is False
    assert "PRICE_SOURCE_CONTROL_COVERAGE_MISMATCH:PYKRX" in result["blocking_conditions"]


def test_correction13_counter_drift_and_fake_match_fail_closed():
    controls = _controls()[:1]
    prices = _source_map(controls)
    # Build a valid rowset, then make the persisted parity claim impossible.
    frames = {(cid, source): ca._c13_normalize_price_frame(value, control=controls[0], source=source, request_id=f"MOCK_{source}") for (cid, source), value in prices.items()}
    parity, recon = ca._c13_price_parity_rows(controls, frames, {key: f"MOCK_{key[1]}" for key in frames}, "RUN")
    parity[0]["parity_status"] = "MATCH"
    parity[0]["common_date_count"] = 0
    result = ca.validate_persisted_price_parity_evidence(
        pd.concat(list(frames.values())), parity, recon, controls,
        request_logs=[{"control_id": "CTRL_01", "source": source, "request_id": f"MOCK_{source}", "outcome": "SUCCESS", "physical_attempt": 1, "price_window_start": "2020-01-01", "price_window_end": "2020-01-31"} for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR")],
    )
    assert result.evaluation_status == "INVALID"
    assert "FAKE_MATCH_OR_INCOMPLETE_PARITY" in result.blockers


def test_correction13_duplicate_control_and_decision_drift_fail_closed():
    controls = _controls()[:1]
    sources = _source_map(controls)
    out = Path("/tmp/c13-negative")
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_13(output_dir=out, repo_root=Path.cwd(), frozen_controls=controls, price_sources=sources)
    parity = pd.read_csv(out / ca.CORRECTION_13_PARITY_FILE)
    parity = pd.concat([parity, parity], ignore_index=True)
    validation = ca.validate_persisted_price_parity_evidence(out / ca.CORRECTION_13_PRICE_FILE, parity, out / ca.CORRECTION_13_RECONCILIATION_FILE, controls, request_logs=result["network_accounting"]["request_logs"])
    assert "PARITY_CONTROL_DUPLICATE" in validation.blockers


def test_correction13_decision_and_gate06_counter_drift_fail_closed(tmp_path):
    controls = _controls()
    out = tmp_path / "drift"
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_13(
        output_dir=out, repo_root=tmp_path, frozen_controls=controls, price_sources=_source_map(controls), request_logs=_request_logs(controls),
    )
    price = out / ca.CORRECTION_13_PRICE_FILE
    parity = out / ca.CORRECTION_13_PARITY_FILE
    recon = out / ca.CORRECTION_13_RECONCILIATION_FILE
    gate = {"date_set_mismatch_count": 0, "insufficient_window_count": 0, "ohlc_mismatch_count": 1}
    decision = {"exact_date_match_controls": 7, "date_mismatch_controls": 0, "insufficient_window_controls": 0, "ohlc_mismatch_controls": 0, "actual_candidate_price_row_count": 88, "actual_pykrx_price_row_count": 88}
    validation = ca.validate_persisted_price_parity_evidence(price, parity, recon, controls, request_logs=result["network_accounting"]["request_logs"], gate06_payload=gate, decision_payload=decision)
    assert "GATE06_PERSISTED_PARITY_MISMATCH" in validation.blockers
    assert "DECISION_PERSISTED_PARITY_MISMATCH" in validation.blockers


def test_correction13_candidate_semantics_keep_unresolved_rank2_explicit():
    result = ca.evaluate_candidate_resolution_population([
        {"candidate_rank": 1, "event_match_score": 80, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": False},
        {"candidate_rank": 2, "event_match_score": 70, "official_evidence_obtained": False, "official_content_usable": False, "semantic_valid": False, "fallback_available": False},
        {"candidate_rank": 3, "event_match_score": 60, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": True},
    ])
    statuses = [item["status"] for item in result["candidate_statuses"]]
    assert statuses == ["DEFINITIVELY_REJECTED", "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE", "SELECTED"]
    assert result["unresolved_higher_priority_candidate_count"] == 1


def test_correction13_allow_network_is_explicitly_blocked():
    try:
        ca.run_corporate_action_evidence_acquisition_fix03_correction_13(allow_network=True)
    except RuntimeError as exc:
        assert "post-review" in str(exc)
    else:
        raise AssertionError("C13 must not execute live during review-candidate development")


def test_correction13_renderer_recomputes_persisted_evidence(tmp_path, monkeypatch):
    controls = _controls()
    out = tmp_path / "renderer"
    decision = ca.run_corporate_action_evidence_acquisition_fix03_correction_13(
        output_dir=out, repo_root=tmp_path, frozen_controls=controls, price_sources=_source_map(controls), request_logs=_request_logs(controls),
    )
    import scripts.render_corporate_action_authority_report as report

    monkeypatch.setattr(report, "_git_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *args, **kwargs: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *args, **kwargs: (True, []))
    binding = {"schema": "code_test_binding_evidence_v01_fix03_correction_13", "fix_head": "FIX", "fix_tree_sha": "TREE", "tested_code_head": "FIX", "tested_code_tree_sha": "TREE", "code_scope": ["src", "scripts", "tests"]}

    def read_csv(_root, _head, path):
        return __import__("csv").DictReader((out / Path(path).name).read_text(encoding="utf-8").splitlines()) and list(__import__("csv").DictReader((out / Path(path).name).read_text(encoding="utf-8").splitlines()))

    gate = json.loads((out / "gate06_corporate_action_reassessment_v01_fix03_correction_13.json").read_text(encoding="utf-8"))
    audit = json.loads((out / "gate06_metric_provenance_audit_v01_fix03_correction_13.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(report, "read_git_csv", read_csv)
    monkeypatch.setattr(report, "read_git_json", lambda _root, _head, path: gate if "gate06_corporate_action_reassessment" in path else (audit if "gate06_metric_provenance_audit" in path else {}))
    truth = report.evaluate_report_truth_sync(tmp_path, "END", {"schema": "manifest"}, decision, binding, None)
    assert truth["report_truth_sync"] == "PASS"

    parity_path = out / ca.CORRECTION_13_PARITY_FILE
    parity = pd.read_csv(parity_path)
    parity.loc[0, "candidate_row_count"] = 0
    parity.to_csv(parity_path, index=False)
    truth = report.evaluate_report_truth_sync(tmp_path, "END", {"schema": "manifest"}, decision, binding, None)
    assert truth["report_truth_sync"] == "FAIL"
    assert "PERSISTED_PRICE_ROW_COUNT_MISMATCH" in truth["blockers"]
