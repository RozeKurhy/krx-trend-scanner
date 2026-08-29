"""CORRECTION_12 runner isolation, identity completeness, and binding tests."""

from __future__ import annotations

from copy import deepcopy
import ast
import json
from pathlib import Path
import hashlib
import sys
import types
from datetime import datetime, timedelta

import pandas as pd

import pytest

import trend_scanner.data.corporate_action_authority as ca
import trend_scanner.data.opendart_preflight as preflight
from scripts.render_corporate_action_authority_report import evaluate_report_truth_sync


def _synthetic_pytest_evidence(
    *, head: str = "MOCK_FIX", tree: str = "MOCK_TREE",
    completion: bool = True, count: int | None = 0,
) -> dict:
    return {
        "schema": "full_pytest_summary_v01_fix03_correction_12",
        "full_suite_completion": completion,
        "code_head_under_test": head,
        "code_tree_sha_under_test": tree,
        "passed": 10,
        "failed": 0,
        "skipped": 0,
        "deselected": 0,
        "warnings": 0,
        "known_baseline_failures": [],
        "unexpected_failures": [],
        "new_regression_count": count,
    }


def _renderer_truth_case(monkeypatch, *, pytest_evidence=None, decision_updates=None):
    import scripts.render_corporate_action_authority_report as report
    monkeypatch.setattr(report, "_git_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *args, **kwargs: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *args, **kwargs: (True, []))
    binding = {
        "schema": "code_test_binding_evidence_v01_fix03_correction_12",
        "fix_head": "FIX", "fix_tree_sha": "TREE", "tested_code_head": "FIX",
        "tested_code_tree_sha": "TREE", "code_scope": ["src", "scripts", "tests"],
    }
    decision = {
        "all_gates_passed": True,
        "gate_06_result": True,
        "gate_15_result": True,
        "production_integration_authorized": True,
        "review_decision": "APPROVED_FOR_PRODUCTION_INTEGRATION",
        "recommended_next_state": "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01",
        "full_suite_completion": True,
        "new_regression_count": 0,
    }
    if decision_updates:
        decision.update(decision_updates)
    return evaluate_report_truth_sync(
        Path("."), "END", {"schema": "manifest"}, decision, binding, pytest_evidence
    )


def _strict_bundle(tmp_path: Path) -> dict:
    run_id = "RUN_FIX12_001"
    ticker = "005930"
    control_id = "CTRL_005930"
    record_id = "RCP_001"
    raw = b"<DOCUMENT><COMPANY-NAME>\xec\x82\xbc\xec\x84\xb1\xec\xa0\x84\xec\x9e\x90</COMPANY-NAME></DOCUMENT>"
    sha = hashlib.sha256(raw).hexdigest()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "doc.xml").write_bytes(raw)
    discovery = [{
        "canonical_run_id": run_id, "control_id": control_id, "ticker": ticker,
        "corp_code": "00126380", "issuer_name": "삼성전자", "selected_record_id": record_id,
    }]
    documents = [{
        "canonical_run_id": run_id, "control_id": control_id, "ticker": ticker,
        "corp_code": "00126380", "issuer_name": "삼성전자", "official_record_id": record_id,
        "producing_request_id": "DOC_001", "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH",
        "raw_evidence_sha256": sha, "raw_sha": sha, "path": "raw/doc.xml",
    }]
    authorities = [{
        "canonical_run_id": run_id, "control_id": control_id, "ticker": ticker,
        "corp_code": "00126380", "issuer_name": "삼성전자", "authority_record_id": record_id,
        "producing_request_id": "DOC_001", "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH",
        "raw_evidence_path": "raw/doc.xml", "raw_evidence_sha256": sha,
        "price_window_start": "2020-04-11", "price_window_end": "2020-06-20",
    }]
    requests = [{
        "canonical_run_id": run_id, "request_id": "DOC_001", "source": "OPENDART_OFFICIAL_API",
        "ticker": ticker, "corp_code": "00126380", "official_record_id": record_id,
        "outcome": "SUCCESS", "http_status": 200, "transport_response_size": len(raw),
        "transport_response_sha256": sha, "raw_http_response_size": len(raw),
        "raw_http_response_sha256": sha, "canonical_raw_sha256": sha,
    }, {
        "canonical_run_id": run_id, "request_id": "NAVER_001", "source": "NAVER_DIRECT",
        "control_id": control_id, "ticker": ticker, "authority_record_id": record_id,
        "price_window_start": "2020-04-11", "price_window_end": "2020-06-20", "outcome": "SUCCESS",
    }, {
        "canonical_run_id": run_id, "request_id": "PYKRX_001", "source": "RAW_PYKRX_COMPARATOR",
        "control_id": control_id, "ticker": ticker, "authority_record_id": record_id,
        "price_window_start": "2020-04-11", "price_window_end": "2020-06-20", "outcome": "SUCCESS",
        "adjusted": True,
    }]
    return {"run_id": run_id, "discovery": discovery, "documents": documents,
            "raw": documents, "authorities": authorities, "requests": requests,
            "prices": requests[1:], "raw_dir": raw_dir}


def _validate(bundle: dict):
    return ca.validate_live_evidence_linkage(
        canonical_run_id=bundle["run_id"], discovery_records=bundle["discovery"],
        document_records=bundle["documents"], raw_manifest_entries=bundle["raw"],
        authority_rows=bundle["authorities"], request_logs=bundle["requests"],
        price_request_logs=bundle["prices"], artifact_paths={"raw": bundle["raw_dir"]},
        current_output_dir=bundle["raw_dir"].parent,
        accounting_cross_invariant_pass=True, schema_suffix="12",
    )


@pytest.mark.parametrize("section,field,expected", [
    ("discovery", "corp_code", "MISSING_DISCOVERY_CORP_CODE"),
    ("discovery", "issuer_name", "MISSING_DISCOVERY_ISSUER"),
    ("documents", "corp_code", "MISSING_DOCUMENT_CORP_CODE"),
    ("documents", "issuer_name", "MISSING_DOCUMENT_ISSUER"),
    ("authorities", "corp_code", "MISSING_AUTHORITY_CORP_CODE"),
    ("authorities", "issuer_name", "MISSING_AUTHORITY_ISSUER"),
    ("authorities", "authority_record_id", "MISSING_AUTHORITY_AUTHORITY_RECORD_ID"),
])
def test_required_identity_missing_fails_closed(tmp_path, section, field, expected):
    bundle = _strict_bundle(tmp_path)
    bundle[section][0].pop(field)
    result = _validate(bundle)
    codes = {item["code"] for item in result.linkage_failures}
    assert expected in codes
    assert result.all_linkage_valid is False
    assert result.to_metrics()["total_provenance_failure_count"] > 0


def test_correction12_offline_guard_isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRECTION_12_OFFLINE_ONLY", "1")
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_12(output_dir=tmp_path / "v01_fix03_correction_12")
    assert result["recommended_next_state"].endswith("CORRECTION_12")
    assert result["production_integration_authorized"] is False
    assert result["full_suite_completion"] is False
    assert result["new_regression_count"] is None
    assert result["network_accounting"]["execution_mode"] == "OFFLINE_IMPLEMENTATION_ONLY"
    assert result["network_accounting"]["grand_total_physical_external_calls"] == 0
    gate06 = json.loads(
        (tmp_path / "v01_fix03_correction_12" / "gate06_corporate_action_reassessment_v01_fix03_correction_12.json")
        .read_text(encoding="utf-8")
    )
    assert "FULL_REPOSITORY_REGRESSION_INCOMPLETE" not in gate06["gate_06_blockers"]
    assert "PYTEST_EVIDENCE_MISSING" in result["blocking_conditions"]
    names = {p.name for p in (tmp_path / "v01_fix03_correction_12").iterdir()}
    assert names
    assert not any(
        any(f"correction_{suffix}" in name for suffix in ("9", "10", "11"))
        for name in names
    )


def test_document_raw_manifest_edge_fails_closed(tmp_path):
    bundle = _strict_bundle(tmp_path)
    bundle["raw"] = [deepcopy(bundle["documents"][0])]
    bundle["raw"][0]["sha256"] = "0" * 64
    result = _validate(bundle)
    assert result.to_metrics()["record_identity_failure_count"] > 0
    assert any(item["code"] == "DOCUMENT_RAW_SHA_MISMATCH" for item in result.linkage_failures)
    assert result.all_linkage_valid is False


def test_correction12_binding_has_no_future_head(monkeypatch):
    truth = _renderer_truth_case(monkeypatch, pytest_evidence=_synthetic_pytest_evidence(head="FIX", tree="TREE"))
    assert truth["report_truth_sync"] == "PASS"

def test_correction12_mocked_full_production_success(tmp_path, monkeypatch):
    """Run the production orchestration with mocked HTTP/data providers, never live endpoints."""
    monkeypatch.delenv("CORRECTION_12_OFFLINE_ONLY", raising=False)
    targets = ca.get_official_discovery_search_targets()
    by_record = {}
    by_corp = {}
    for idx, target in enumerate(targets, start=1):
        record_id = f"9{idx:013d}"
        by_record[record_id] = target
        by_corp[target["corp_code"]] = (target, record_id)

    class Response:
        def __init__(self, payload: bytes | dict):
            self.status_code = 200
            self.content = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

        def json(self):
            return json.loads(self.content.decode("utf-8"))

    def mocked_get(self, url, *args, **kwargs):
        if url.endswith("/api/list.json"):
            target, record_id = by_corp[kwargs["params"]["corp_code"]]
            event_label = {
                "STOCK_SPLIT": "주식분할결정",
                "MERGER": "합병결정",
                "RIGHTS_OFFERING": "유상증자결정",
                "BONUS_ISSUE": "무상증자결정",
            }[target["target_event_family"]]
            return Response({
                "status": "000", "total_count": 1, "total_page": 1, "page_count": 100,
                "list": [{
                    "rcept_no": record_id, "report_nm": event_label,
                    "rcept_dt": target["discovery_start"], "corp_code": target["corp_code"],
                    "stock_code": target["ticker"], "corp_name": target["issuer_name"],
                }],
            })
        if url.endswith("/api/document.xml"):
            record_id = kwargs["params"]["rcept_no"]
            target = by_record[record_id]
            event_label = {
                "STOCK_SPLIT": "주식분할",
                "MERGER": "회사합병",
                "RIGHTS_OFFERING": "유상증자",
                "BONUS_ISSUE": "무상증자",
            }[target["target_event_family"]]
            timing_label = {
                "STOCK_SPLIT": "신주상장예정일",
                "MERGER": "합병기일",
                "RIGHTS_OFFERING": "신주상장일",
                "BONUS_ISSUE": "신주배정기준일",
            }[target["target_event_family"]]
            raw = (
                f"<DOCUMENT><DOCUMENT-HEADER><DOCUMENT-NAME>{event_label}결정</DOCUMENT-NAME>"
                f"<COMPANY-NAME>{target['issuer_name']}</COMPANY-NAME></DOCUMENT-HEADER><BODY>"
                f"<SECTION-1><TITLE>{event_label}</TITLE><P>{timing_label} : {target['claimed_anchor_date']}</P>"
                "</SECTION-1></BODY></DOCUMENT>"
            ).encode("utf-8")
            return Response(raw)
        raise AssertionError(f"unexpected mocked URL: {url}")

    monkeypatch.setattr(ca.requests.Session, "get", mocked_get)
    monkeypatch.setattr(ca, "run_opendart_preflight", lambda *a, **k: {"verdict": "READY"})
    monkeypatch.setattr(ca, "run_document_endpoint_readiness_probe", lambda *a, **k: {"verdict": "READY"})
    monkeypatch.setattr(ca, "get_opendart_api_key", lambda: "mock-only")

    def mock_naver(self, ticker, start, end):
        anchor = next(t["claimed_anchor_date"] for t in targets if t["ticker"] == ticker)
        anchor_dt = datetime.strptime(anchor, "%Y-%m-%d")
        items = [
            f'<item data="{(anchor_dt + timedelta(days=offset)).strftime("%Y%m%d")}|100|101|99|100|1000"/>'
            for offset in range(-5, 6)
        ]
        return 200, "<protocol><chartdata>" + "".join(items) + "</chartdata></protocol>", 1.0

    monkeypatch.setattr(ca.NaverDateRangeAdjustedClient, "fetch_raw", mock_naver)
    fake_pkg = types.ModuleType("pykrx")
    fake_pkg.__path__ = []
    fake_stock = types.ModuleType("pykrx.stock")

    def mock_pykrx(start, end, ticker, adjusted=True):
        assert adjusted is True
        start_dt = datetime.strptime(start, "%Y%m%d")
        dates = [start_dt + timedelta(days=30 + i) for i in range(11)]
        return pd.DataFrame(
            {"시가": [100] * 11, "고가": [101] * 11, "저가": [99] * 11, "종가": [100] * 11, "거래량": [1000] * 11},
            index=pd.to_datetime(dates),
        )

    fake_stock.get_market_ohlcv_by_date = mock_pykrx
    fake_pkg.stock = fake_stock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pkg)
    monkeypatch.setitem(sys.modules, "pykrx.stock", fake_stock)

    captured = {}
    original_validate = ca.validate_live_evidence_linkage

    def capture_validate(**kwargs):
        captured.update(kwargs)
        return original_validate(**kwargs)

    monkeypatch.setattr(ca, "validate_live_evidence_linkage", capture_validate)

    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_12(
        output_dir=tmp_path / "v01_fix03_correction_12", allow_network=True,
        regression_evidence=_synthetic_pytest_evidence(),
        expected_fix_head="MOCK_FIX", expected_fix_tree_sha="MOCK_TREE",
    )
    assert result["authority_valid_control_count"] == 8
    assert result["gate_06_result"] is True
    assert result["gate_15_result"] is True
    assert result["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert result["production_integration_authorized"] is True
    assert result["production_certification_ready"] is True
    assert result["network_accounting"]["accounting_cross_invariant_pass"] is True
    assert result["provenance_failures"] == 0

    files = {p.name for p in (tmp_path / "v01_fix03_correction_12").iterdir()}
    assert files
    assert not any(
        any(f"correction_{suffix}" in name for suffix in ("9", "10", "11"))
        for name in files
    )
    assert result["directive_id"].endswith("CORRECTION_12")
    assert {"canonical_run_id", "control_id", "ticker", "corp_code", "issuer_name", "selected_record_id"} <= set(captured["discovery_records"][0])
    assert {"canonical_run_id", "control_id", "ticker", "corp_code", "issuer_name", "official_record_id", "producing_request_id", "retrieval_mode", "raw_evidence_sha256"} <= set(captured["document_records"][0])
    assert {"canonical_run_id", "control_id", "ticker", "corp_code", "issuer_name", "authority_record_id", "producing_request_id", "raw_evidence_path", "raw_evidence_sha256"} <= set(captured["authority_rows"][0])


def test_default_corporate_action_entrypoint_targets_correction12():
    source = Path(ca.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_nodes = [
        node for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    ]
    assert len(main_nodes) == 1
    calls = [
        node for node in ast.walk(main_nodes[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls
    assert calls[0].func.id == "run_corporate_action_evidence_acquisition_fix03_correction_12"
    assert "CORRECTION_9" not in ast.unparse(main_nodes[0])
    assert "CORRECTION_10" not in ast.unparse(main_nodes[0])
    assert "CORRECTION_11" not in ast.unparse(main_nodes[0])
    assert ca.DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_12.name == "v01_fix03_correction_12"
    assert ca.DIRECTIVE_ID_CORRECTION_12.endswith("CORRECTION_12")


@pytest.mark.parametrize(
    "evidence,expected",
    [
        (_synthetic_pytest_evidence(), True),
        (_synthetic_pytest_evidence(completion=False), False),
        (_synthetic_pytest_evidence(head="OTHER"), False),
        (_synthetic_pytest_evidence(tree="OTHER"), False),
        (_synthetic_pytest_evidence(count=1), False),
        (None, False),
    ],
)
def test_correction12_production_authorization_predicate_is_fail_closed(evidence, expected):
    validated = ca.validate_full_regression_evidence(
        evidence, expected_fix_head="MOCK_FIX", expected_fix_tree_sha="MOCK_TREE"
    )
    assert ca.production_certification_ready(
        all_source_gates_pass=True,
        regression_certification=validated,
    ) is expected


def test_correction12_runner_rejects_unvalidated_caller_assertions(tmp_path):
    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_12(
        output_dir=tmp_path / "v01_fix03_correction_12", allow_network=False,
        full_suite_completion=True, new_regression_count=0,
    )
    assert result["production_integration_authorized"] is False
    assert "UNVALIDATED_CALLER_ASSERTION" in result["blocking_conditions"]


def test_renderer_wrong_pytest_commit_fails(monkeypatch):
    truth = _renderer_truth_case(monkeypatch, pytest_evidence=_synthetic_pytest_evidence(head="OLD"))
    assert truth["report_truth_sync"] == "FAIL"
    assert "PYTEST_FIX_HEAD_MISMATCH" in truth["blockers"]


def test_renderer_wrong_pytest_tree_fails(monkeypatch):
    truth = _renderer_truth_case(monkeypatch, pytest_evidence=_synthetic_pytest_evidence(tree="OLD"))
    assert truth["report_truth_sync"] == "FAIL"
    assert "PYTEST_FIX_TREE_MISMATCH" in truth["blockers"]


def test_renderer_new_regression_fails_but_gate06_claim_is_not_rewritten(monkeypatch):
    truth = _renderer_truth_case(monkeypatch, pytest_evidence=_synthetic_pytest_evidence(count=1))
    assert truth["report_truth_sync"] == "FAIL"
    assert "PYTEST_NEW_REGRESSION_DETECTED" in truth["blockers"]


def test_renderer_decision_pytest_count_mismatch_fails(monkeypatch):
    truth = _renderer_truth_case(
        monkeypatch,
        pytest_evidence=_synthetic_pytest_evidence(count=1),
        decision_updates={"new_regression_count": 0, "gate_15_result": False,
                           "all_gates_passed": False, "production_integration_authorized": False,
                           "review_decision": "CONDITIONAL_REVIEW_REQUIRED"},
    )
    assert truth["report_truth_sync"] == "FAIL"
    assert "DECISION_PYTEST_REGRESSION_COUNT_MISMATCH" in truth["blockers"]


def test_renderer_decision_pytest_completion_mismatch_fails(monkeypatch):
    truth = _renderer_truth_case(
        monkeypatch,
        pytest_evidence=_synthetic_pytest_evidence(completion=False, count=0),
        decision_updates={"full_suite_completion": True, "gate_15_result": False,
                           "all_gates_passed": False, "production_integration_authorized": False,
                           "review_decision": "CONDITIONAL_REVIEW_REQUIRED"},
    )
    assert truth["report_truth_sync"] == "FAIL"
    assert "DECISION_PYTEST_COMPLETION_MISMATCH" in truth["blockers"]


def test_renderer_missing_pytest_evidence_fails(monkeypatch):
    truth = _renderer_truth_case(monkeypatch)
    assert truth["report_truth_sync"] == "FAIL"
    assert "PYTEST_EVIDENCE_MISSING" in truth["blockers"]


def test_renderer_internal_decision_contradiction_fails(monkeypatch):
    truth = _renderer_truth_case(
        monkeypatch,
        pytest_evidence=_synthetic_pytest_evidence(head="FIX", tree="TREE"),
        decision_updates={"production_integration_authorized": False,
                           "review_decision": "CONDITIONAL_REVIEW_REQUIRED"},
    )
    assert truth["report_truth_sync"] == "FAIL"
    assert "DECISION_INTERNAL_INCONSISTENCY" in truth["blockers"]


def test_gate06_source_semantics_are_separate_from_regression_certification():
    gate06_pass, gate06_blockers = ca.evaluate_gate06({
        "preflight_verdict": "READY", "document_readiness_verdict": "READY",
        "authority_valid_controls_count": 8, "diversity_pass": True,
        "linkage_evaluation_status": "EVALUATED", "all_linkage_valid": True,
    })
    assert gate06_pass is True
    assert not any("REGRESSION" in blocker for blocker in gate06_blockers)


def test_correction12_preflight_readiness_identity_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "get_opendart_api_key", lambda: "mock-only")
    run_id = "RUN_FIX12_PREFLIGHT_001"
    preflight_result = preflight.run_opendart_preflight(
        output_dir=tmp_path,
        allow_network=False,
        canonical_run_id=run_id,
        correction_suffix="12",
    )
    readiness_result = preflight.run_document_endpoint_readiness_probe(
        output_dir=tmp_path,
        allow_network=False,
        canonical_run_id=run_id,
        correction_suffix="12",
    )
    assert preflight_result["schema"] == "opendart_preflight_v01_fix03_correction_12"
    assert readiness_result["schema"] == "opendart_document_readiness_v01_fix03_correction_12"
    assert preflight_result["directive_id"].endswith("CORRECTION_12")
    assert readiness_result["directive_id"].endswith("CORRECTION_12")
    assert preflight_result["canonical_run_id"] == run_id
    assert readiness_result["canonical_run_id"] == run_id
