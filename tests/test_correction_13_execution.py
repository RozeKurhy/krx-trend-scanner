"""CORRECTION_13 production-path, persisted-evidence, and renderer tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import sys
import types

import pandas as pd
import pytest

from trend_scanner.data import corporate_action_authority as ca


def _summary(head: str = "MOCK_FIX", tree: str = "MOCK_TREE", **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "full_pytest_summary_v01_fix03_correction_13", "full_suite_completion": True,
        "code_head_under_test": head, "code_tree_sha_under_test": tree,
        "passed": 100, "failed": 0, "skipped": 0, "deselected": 0, "warnings": 0,
        "known_baseline_failures": [], "unexpected_failures": [], "new_regression_count": 0,
    }
    value.update(updates)
    return value


def _install_production_mocks(monkeypatch: pytest.MonkeyPatch, *, ohlc_delta: bool = False) -> None:
    targets = ca.get_official_discovery_search_targets()
    by_corp: dict[str, tuple[dict[str, object], str]] = {}
    by_record: dict[str, dict[str, object]] = {}
    for index, target in enumerate(targets, start=1):
        record_id = f"9{index:013d}"
        by_corp[str(target["corp_code"])] = (target, record_id)
        by_record[record_id] = target

    class Response:
        def __init__(self, payload: bytes | dict[str, object], status_code: int = 200):
            self.status_code = status_code
            self.content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

        def json(self) -> dict[str, object]:
            return json.loads(self.content.decode())

    def mocked_get(self: object, url: str, *args: object, **kwargs: object) -> Response:
        params = kwargs.get("params", {})
        if url.endswith("/api/list.json"):
            target, record_id = by_corp[str(params["corp_code"])]
            labels = {"STOCK_SPLIT": "주식분할결정", "MERGER": "합병결정", "RIGHTS_OFFERING": "유상증자결정", "BONUS_ISSUE": "무상증자결정"}
            return Response({"status": "000", "total_count": 1, "total_page": 1, "page_count": 100, "list": [{"rcept_no": record_id, "report_nm": labels[str(target["target_event_family"])], "rcept_dt": target["discovery_start"], "corp_code": target["corp_code"], "stock_code": target["ticker"], "corp_name": target["issuer_name"]}]})
        if url.endswith("/api/document.xml"):
            target = by_record[str(params["rcept_no"])]
            event_labels = {"STOCK_SPLIT": "주식분할", "MERGER": "회사합병", "RIGHTS_OFFERING": "유상증자", "BONUS_ISSUE": "무상증자"}
            timing_labels = {"STOCK_SPLIT": "신주상장예정일", "MERGER": "합병기일", "RIGHTS_OFFERING": "신주상장일", "BONUS_ISSUE": "신주배정기준일"}
            raw = (f"<DOCUMENT><DOCUMENT-HEADER><DOCUMENT-NAME>{event_labels[str(target['target_event_family'])]}결정</DOCUMENT-NAME>"
                   f"<COMPANY-NAME>{target['issuer_name']}</COMPANY-NAME></DOCUMENT-HEADER><BODY><SECTION-1>"
                   f"<TITLE>{event_labels[str(target['target_event_family'])]}</TITLE><P>{timing_labels[str(target['target_event_family'])]} : {target['claimed_anchor_date']}</P>"
                   "</SECTION-1></BODY></DOCUMENT>").encode()
            return Response(raw)
        raise AssertionError(f"unexpected mocked URL: {url}")

    monkeypatch.setattr(ca.requests.Session, "get", mocked_get)
    monkeypatch.setattr(ca, "run_opendart_preflight", lambda *a, **k: {"verdict": "READY"})
    monkeypatch.setattr(ca, "run_document_endpoint_readiness_probe", lambda *a, **k: {"verdict": "READY"})
    monkeypatch.setattr(ca, "get_opendart_api_key", lambda: "mock-only")
    monkeypatch.setattr(ca.NaverDateRangeAdjustedClient, "fetch_raw", lambda self, ticker, start, end: _naver_xml(targets, ticker))

    fake_pkg = types.ModuleType("pykrx")
    fake_pkg.__path__ = []
    fake_stock = types.ModuleType("pykrx.stock")

    def mock_pykrx(start: str, end: str, ticker: str, adjusted: bool = True) -> pd.DataFrame:
        assert adjusted is True
        anchor = next(str(t["claimed_anchor_date"]) for t in targets if str(t["ticker"]) == ticker)
        anchor_dt = datetime.strptime(anchor, "%Y-%m-%d")
        close = 150 if ohlc_delta and ticker == "005930" else 100
        dates = [anchor_dt + timedelta(days=offset) for offset in range(-5, 6)]
        return pd.DataFrame({"시가": [100] * 11, "고가": [101] * 11, "저가": [99] * 11, "종가": [close] * 11, "거래량": [1000] * 11}, index=pd.to_datetime(dates))

    fake_stock.get_market_ohlcv_by_date = mock_pykrx
    fake_pkg.stock = fake_stock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pkg)
    monkeypatch.setitem(sys.modules, "pykrx.stock", fake_stock)


def _naver_xml(targets: list[dict[str, object]], ticker: str) -> tuple[int, str, float]:
    anchor = next(str(t["claimed_anchor_date"]) for t in targets if str(t["ticker"]) == ticker)
    anchor_dt = datetime.strptime(anchor, "%Y-%m-%d")
    items = "".join(f'<item data="{(anchor_dt + timedelta(days=offset)).strftime("%Y%m%d")}|100|101|99|100|1000"/>' for offset in range(-5, 6))
    return 200, f"<protocol><chartdata>{items}</chartdata></protocol>", 0.01


def _write_c13_evidence(tmp_path: Path, summary: dict[str, object]) -> None:
    path = tmp_path / ca.FULL_PYTEST_EVIDENCE_RELATIVE_PATH_CORRECTION_13
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary), encoding="utf-8")


def _clean_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ca, "observe_git_code_snapshot", lambda *a, **k: ca.GitCodeSnapshot("MOCK_FIX", "MOCK_TREE", False))


def test_correction13_mocked_full_production_uses_live_capable_path(tmp_path, monkeypatch):
    _clean_snapshot(monkeypatch)
    _install_production_mocks(monkeypatch)
    _write_c13_evidence(tmp_path, _summary())
    result = ca.run_correction13_from_canonical_evidence(repo_root=tmp_path, output_dir=tmp_path / "c13", allow_network=True, parent_dir=Path.cwd() / ca.PARENT_FIX03_CORRECTION_DIR)
    assert result["gate_06_result"] is True
    assert result["gate_15_result"] is True
    assert result["all_gates_passed"] is True
    assert result["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert result["production_integration_authorized"] is True
    assert result["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
    assert len(pd.read_csv(tmp_path / "c13" / ca.CORRECTION_13_PRICE_FILE)) == 176


def test_correction13_ohlc_contradiction_rejects_actual_path(tmp_path, monkeypatch):
    _clean_snapshot(monkeypatch)
    _install_production_mocks(monkeypatch, ohlc_delta=True)
    _write_c13_evidence(tmp_path, _summary())
    result = ca.run_correction13_from_canonical_evidence(repo_root=tmp_path, output_dir=tmp_path / "reject", allow_network=True, parent_dir=Path.cwd() / ca.PARENT_FIX03_CORRECTION_DIR)
    assert result["review_decision"] == "REJECTED_AS_PRODUCTION_AUTHORITY"
    assert result["gate_06_result"] is False
    assert result["production_integration_authorized"] is False
    assert result["recommended_next_state"] == "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"


@pytest.mark.parametrize("summary", [None, _summary(schema="wrong"), _summary(head="OTHER"), _summary(tree="OTHER"), _summary(full_suite_completion=False), _summary(new_regression_count=1)])
def test_correction13_invalid_pytest_evidence_stops_before_external_calls(tmp_path, monkeypatch, summary):
    calls = {"preflight": 0, "naver": 0}
    monkeypatch.setenv("OPENDART_API_KEY", "must-not-be-used")
    monkeypatch.setattr(ca, "observe_git_code_snapshot", lambda *a, **k: ca.GitCodeSnapshot("MOCK_FIX", "MOCK_TREE", False))
    monkeypatch.setattr(ca, "run_opendart_preflight", lambda *a, **k: calls.__setitem__("preflight", calls["preflight"] + 1) or {"verdict": "READY"})
    monkeypatch.setattr(ca.NaverDateRangeAdjustedClient, "fetch_raw", lambda *a, **k: calls.__setitem__("naver", calls["naver"] + 1))
    _write_c13_evidence(tmp_path, summary or {})
    ca.run_correction13_from_canonical_evidence(repo_root=tmp_path, output_dir=tmp_path / "invalid", parent_dir=Path.cwd() / ca.PARENT_FIX03_CORRECTION_DIR)
    assert calls == {"preflight": 0, "naver": 0}


def test_correction13_dirty_scope_stops_before_external_calls(tmp_path, monkeypatch):
    calls = {"preflight": 0}
    monkeypatch.setattr(ca, "observe_git_code_snapshot", lambda *a, **k: ca.GitCodeSnapshot("MOCK_FIX", "MOCK_TREE", True))
    monkeypatch.setattr(ca, "run_opendart_preflight", lambda *a, **k: calls.__setitem__("preflight", calls["preflight"] + 1) or {"verdict": "READY"})
    _write_c13_evidence(tmp_path, _summary())
    ca.run_correction13_from_canonical_evidence(repo_root=tmp_path, output_dir=tmp_path / "dirty", parent_dir=Path.cwd() / ca.PARENT_FIX03_CORRECTION_DIR)
    assert calls["preflight"] == 0


def _valid_persisted_bundle() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, str]], list[dict[str, object]]]:
    controls = [{"control_id": "C1", "ticker": "005930", "corp_code": "CC", "authority_record_id": "R1", "price_window_start": "2020-01-01", "price_window_end": "2020-01-31", "official_anchor_date": "2020-01-16"}]
    dates = pd.date_range("2020-01-10", periods=11).strftime("%Y-%m-%d")
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    logs: list[dict[str, object]] = []
    for source, req in (("NAVER_DIRECT", "N1"), ("RAW_PYKRX_COMPARATOR", "P1")):
        frame = ca._c13_normalize_price_frame(pd.DataFrame({"date": dates, "open": [100] * 11, "high": [101] * 11, "low": [99] * 11, "close": [100] * 11, "volume": [1000] * 11}), control=controls[0], source=source, request_id=req)
        frames[("C1", source)] = frame
        logs.append({"control_id": "C1", "source": source, "request_id": req, "outcome": "SUCCESS", "physical_attempt": 1, "price_window_start": "2020-01-01", "price_window_end": "2020-01-31"})
    parity, recon = ca._c13_price_parity_rows(controls, frames, {key: ("N1" if key[1] == "NAVER_DIRECT" else "P1") for key in frames}, "RUN")
    return pd.concat(list(frames.values()), ignore_index=True), pd.DataFrame(parity), pd.DataFrame(recon), controls, logs


def test_correction13_raw_ohlc_contradiction_beats_fake_match():
    price, parity, recon, controls, logs = _valid_persisted_bundle()
    price.loc[price["source"] == "RAW_PYKRX_COMPARATOR", "close"] = 150
    parity.loc[0, "close_mismatch_count"] = 0
    parity.loc[0, "parity_status"] = "MATCH"
    result = ca.validate_persisted_price_parity_evidence(price, parity, recon, controls, request_logs=logs)
    assert result.evaluation_status == "INVALID"
    assert "PARITY_SUMMARY_RECOMPUTATION_MISMATCH" in result.blockers
    assert result.ohlc_mismatch_control_count == 1


def test_correction13_raw_date_contradiction_fails_closed():
    price, parity, recon, controls, logs = _valid_persisted_bundle()
    price = price[~((price["source"] == "RAW_PYKRX_COMPARATOR") & (price["date"] == "2020-01-10"))]
    parity.loc[0, "candidate_only_date_count"] = 0
    recon.loc[0, "candidate_only_date_count"] = 0
    result = ca.validate_persisted_price_parity_evidence(price, parity, recon, controls, request_logs=logs)
    assert result.evaluation_status == "INVALID"
    assert "PARITY_SUMMARY_RECOMPUTATION_MISMATCH" in result.blockers
    assert "RECONCILIATION_RECOMPUTATION_MISMATCH" in result.blockers


def test_correction13_raw_insufficient_window_cannot_claim_match():
    price, parity, recon, controls, logs = _valid_persisted_bundle()
    price = price[price["date"] <= "2020-01-12"]
    result = ca.validate_persisted_price_parity_evidence(price, parity, recon, controls, request_logs=logs)
    assert result.evaluation_status == "INVALID"
    assert result.insufficient_window_control_count == 1
    assert "PARITY_SUMMARY_RECOMPUTATION_MISMATCH" in result.blockers


def test_correction13_header_only_duplicate_and_request_mismatch_fail_closed():
    _, _, _, controls, _ = _valid_persisted_bundle()
    empty = pd.DataFrame(columns=sorted(ca.PRICE_ROW_REQUIRED_COLUMNS))
    result = ca.validate_persisted_price_parity_evidence(empty, pd.DataFrame(columns=sorted(ca.PARITY_REQUIRED_COLUMNS)), pd.DataFrame(columns=sorted(ca.RECONCILIATION_REQUIRED_COLUMNS)), controls)
    assert result.evaluation_status == "INCOMPLETE"
    assert {"PRICE_EVIDENCE_EMPTY", "PARITY_EVIDENCE_EMPTY", "RECONCILIATION_EVIDENCE_EMPTY"} <= set(result.blockers)
    price, parity, recon, controls, logs = _valid_persisted_bundle()
    parity = pd.concat([parity, parity], ignore_index=True)
    logs[0]["request_id"] = "wrong"
    result = ca.validate_persisted_price_parity_evidence(price, parity, recon, controls, request_logs=logs)
    assert "PARITY_CONTROL_DUPLICATE" in result.blockers
    assert "PRICE_REQUEST_LINKAGE_MISSING" in result.blockers


def test_correction13_candidate_resolution_population_preserves_rank2_unresolved():
    result = ca.evaluate_candidate_resolution_population([
        {"candidate_rank": 1, "event_match_score": 80, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": False},
        {"candidate_rank": 2, "event_match_score": 70, "official_evidence_obtained": False, "official_content_usable": False, "semantic_valid": False, "fallback_available": False},
        {"candidate_rank": 3, "event_match_score": 60, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": True},
    ])
    assert [row["status"] for row in result["candidate_statuses"]] == ["DEFINITIVELY_REJECTED", "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE", "SELECTED"]
    assert result["unresolved_higher_priority_candidate_count"] == 1


def test_correction13_full_pytest_schema_accepts_c13_and_rejects_unknown():
    valid = ca.validate_full_regression_evidence(_summary(), expected_fix_head="MOCK_FIX", expected_fix_tree_sha="MOCK_TREE")
    invalid = ca.validate_full_regression_evidence({**_summary(), "schema": "unknown"}, expected_fix_head="MOCK_FIX", expected_fix_tree_sha="MOCK_TREE")
    assert valid.certification_valid is True
    assert invalid.certification_valid is False
    assert "PYTEST_SCHEMA_MISMATCH" in invalid.blockers


@pytest.mark.parametrize(
    "decision_name,authorized,all_gates,gate06,gate15,next_state",
    [
        ("APPROVED_FOR_PRODUCTION_INTEGRATION", True, True, True, True, "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"),
        ("CONDITIONAL_REVIEW_REQUIRED", False, False, False, False, ca.DIRECTIVE_ID_CORRECTION_13),
        ("REJECTED_AS_PRODUCTION_AUTHORITY", False, False, False, False, "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"),
    ],
)
def test_correction13_renderer_terminal_decision_matrix(tmp_path, monkeypatch, decision_name, authorized, all_gates, gate06, gate15, next_state):
    import scripts.render_corporate_action_authority_report as report

    price, parity, recon, controls, logs = _valid_persisted_bundle()
    files = {
        "corporate_action_review_cohort_v01_fix03_correction_13.csv": controls,
        ca.CORRECTION_13_PRICE_FILE: price.to_dict("records"),
        ca.CORRECTION_13_PARITY_FILE: parity.to_dict("records"),
        ca.CORRECTION_13_RECONCILIATION_FILE: recon.to_dict("records"),
    }
    gate = {"gate_06_pass": gate06}
    audit = {"verdict": "COMPLETE", "all_metrics_audited": True, "rows_loaded": {"parity": 1, "reconciliation": 1}}
    decision = {"schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13", "all_gates_passed": all_gates, "gate_06_result": gate06, "gate_15_result": gate15, "production_integration_authorized": authorized, "review_decision": decision_name, "recommended_next_state": next_state, "full_suite_completion": True, "new_regression_count": 0, "actual_candidate_price_row_count": 11, "actual_pykrx_price_row_count": 11, "exact_date_match_controls": 1, "date_mismatch_controls": 0, "insufficient_window_controls": 0, "ohlc_mismatch_controls": 0, "network_accounting": {"request_logs": logs}}
    monkeypatch.setattr(report, "_git_exists", lambda *a, **k: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *a, **k: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *a, **k: (True, []))
    monkeypatch.setattr(report, "read_git_csv", lambda _root, _head, path: files.get(Path(path).name, []))
    monkeypatch.setattr(report, "read_git_json", lambda _root, _head, path: gate if "gate06_corporate_action" in path else (audit if "gate06_metric" in path else {}))
    binding = {"schema": "code_test_binding_evidence_v01_fix03_correction_13", "fix_head": "FIX", "fix_tree_sha": "TREE", "tested_code_head": "FIX", "tested_code_tree_sha": "TREE", "code_scope": ["src", "scripts", "tests"]}
    truth = report.evaluate_report_truth_sync(tmp_path, "END", {"schema": "manifest"}, decision, binding, _summary(head="FIX", tree="TREE"))
    assert truth["report_truth_sync"] == "PASS"


def test_correction13_renderer_rejects_persisted_price_contradiction(tmp_path, monkeypatch):
    import scripts.render_corporate_action_authority_report as report

    price, parity, recon, controls, logs = _valid_persisted_bundle()
    price.loc[price["source"] == "RAW_PYKRX_COMPARATOR", "close"] = 150
    parity.loc[0, "close_mismatch_count"] = 0
    parity.loc[0, "parity_status"] = "MATCH"
    files = {"corporate_action_review_cohort_v01_fix03_correction_13.csv": controls, ca.CORRECTION_13_PRICE_FILE: price.to_dict("records"), ca.CORRECTION_13_PARITY_FILE: parity.to_dict("records"), ca.CORRECTION_13_RECONCILIATION_FILE: recon.to_dict("records")}
    monkeypatch.setattr(report, "_git_exists", lambda *a, **k: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *a, **k: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *a, **k: (True, []))
    monkeypatch.setattr(report, "read_git_csv", lambda _root, _head, path: files.get(Path(path).name, []))
    monkeypatch.setattr(report, "read_git_json", lambda _root, _head, path: {"gate_06_pass": True} if "gate06_corporate_action" in path else ({"verdict": "COMPLETE", "all_metrics_audited": True, "rows_loaded": {"parity": 1, "reconciliation": 1}} if "gate06_metric" in path else {}))
    decision = {"schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13", "all_gates_passed": False, "gate_06_result": False, "gate_15_result": False, "production_integration_authorized": False, "review_decision": "CONDITIONAL_REVIEW_REQUIRED", "recommended_next_state": ca.DIRECTIVE_ID_CORRECTION_13, "full_suite_completion": True, "new_regression_count": 0, "network_accounting": {"request_logs": logs}}
    binding = {"schema": "code_test_binding_evidence_v01_fix03_correction_13", "fix_head": "FIX", "fix_tree_sha": "TREE", "tested_code_head": "FIX", "tested_code_tree_sha": "TREE", "code_scope": ["src", "scripts", "tests"]}
    truth = report.evaluate_report_truth_sync(tmp_path, "END", {"schema": "manifest"}, decision, binding, _summary(head="FIX", tree="TREE"))
    assert truth["report_truth_sync"] == "FAIL"
    assert "PARITY_SUMMARY_RECOMPUTATION_MISMATCH" in truth["blockers"]


def test_correction13_renderer_rejects_malformed_terminal_shape(tmp_path, monkeypatch):
    import scripts.render_corporate_action_authority_report as report

    monkeypatch.setattr(report, "_git_exists", lambda *a, **k: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *a, **k: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *a, **k: (True, []))
    monkeypatch.setattr(report, "read_git_csv", lambda *a, **k: [])
    monkeypatch.setattr(report, "read_git_json", lambda *a, **k: {"gate_06_pass": True} if "gate06_corporate_action" in k.get("path", "") else {"verdict": "COMPLETE", "all_metrics_audited": True, "rows_loaded": {"parity": 0, "reconciliation": 0}} if "gate06_metric" in k.get("path", "") else {})
    decision = {"schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13", "all_gates_passed": True, "gate_06_result": True, "gate_15_result": True, "production_integration_authorized": True, "review_decision": "NOT_A_TERMINAL_STATE", "recommended_next_state": "NOWHERE", "full_suite_completion": True, "new_regression_count": 0}
    binding = {"schema": "code_test_binding_evidence_v01_fix03_correction_13", "fix_head": "FIX", "fix_tree_sha": "TREE", "tested_code_head": "FIX", "tested_code_tree_sha": "TREE", "code_scope": ["src", "scripts", "tests"]}
    truth = report.evaluate_report_truth_sync(tmp_path, "END", {"schema": "manifest"}, decision, binding, _summary(head="FIX", tree="TREE"))
    assert truth["report_truth_sync"] == "FAIL"
    assert "DECISION_INTERNAL_INCONSISTENCY" in truth["blockers"]
