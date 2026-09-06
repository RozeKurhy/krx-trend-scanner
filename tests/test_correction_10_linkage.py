"""FIX03_CORRECTION_10 linkage truth-source and mocked orchestration tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import types
from datetime import datetime

import pandas as pd
import pytest

import trend_scanner.data.corporate_action_authority as ca
from scripts.render_corporate_action_authority_report import (
    derive_authority_closed,
    evaluate_report_truth_sync,
)


def _bundle(tmp_path: Path) -> dict:
    run_id = "RUN_FIX10_001"
    ticker = "005930"
    control_id = "CTRL_005930"
    authority_id = "RCP_001"
    raw = "<DOCUMENT><DOCUMENT-HEADER><DOCUMENT-NAME>주식분할결정</DOCUMENT-NAME><COMPANY-NAME>삼성전자</COMPANY-NAME></DOCUMENT-HEADER><BODY><SECTION-1><TITLE>주식분할</TITLE><P>신주상장예정일 : 2020-05-16</P></SECTION-1></BODY></DOCUMENT>".encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "doc.xml").write_bytes(raw)
    discovery = [{
        "canonical_run_id": run_id,
        "control_id": control_id,
        "ticker": ticker,
        "issuer_name": "삼성전자",
        "corp_code": "00126380",
        "selected_record_id": authority_id,
    }]
    documents = [{
        "canonical_run_id": run_id,
        "control_id": control_id,
        "ticker": ticker,
        "issuer": "삼성전자",
        "corp_code": "00126380",
        "path": "raw/doc.xml",
        "sha256": sha,
        "source": "OPENDART_OFFICIAL_API",
        "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH",
        "official_record_id": authority_id,
        "producing_request_id": "DOC_001",
    }]
    authorities = [{
        "canonical_run_id": run_id,
        "control_id": control_id,
        "ticker": ticker,
        "issuer_name": "삼성전자",
        "corp_code": "00126380",
        "authority_record_id": authority_id,
        "raw_evidence_path": "raw/doc.xml",
        "raw_evidence_sha256": sha,
        "producing_request_id": "DOC_001",
        "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH",
        "price_window_start": "2020-04-11",
        "price_window_end": "2020-06-20",
        "authority_valid": True,
    }]
    requests = [{
        "canonical_run_id": run_id,
        "request_id": "DOC_001",
        "source": "OPENDART_OFFICIAL_API",
        "ticker": ticker,
        "corp_code": "00126380",
        "official_record_id": authority_id,
        "physical_attempt": 1,
        "outcome": "SUCCESS",
        "http_status": 200,
        "transport_response_size": len(raw),
        "transport_response_sha256": sha,
        "raw_http_response_size": len(raw),
        "raw_http_response_sha256": sha,
        "canonical_raw_sha256": sha,
    }]
    prices = [
        {
            "canonical_run_id": run_id,
            "request_id": "NAVER_001",
            "source": "NAVER_DIRECT",
            "control_id": control_id,
            "ticker": ticker,
            "authority_record_id": authority_id,
            "price_window_start": "2020-04-11",
            "price_window_end": "2020-06-20",
            "physical_attempt": 1,
            "outcome": "SUCCESS",
        },
        {
            "canonical_run_id": run_id,
            "request_id": "PYKRX_001",
            "source": "RAW_PYKRX_COMPARATOR",
            "control_id": control_id,
            "ticker": ticker,
            "authority_record_id": authority_id,
            "price_window_start": "2020-04-11",
            "price_window_end": "2020-06-20",
            "adjusted": True,
            "sanitized_endpoint": "pykrx.stock.get_market_ohlcv_by_date(..., adjusted=True)",
            "physical_attempt": 1,
            "outcome": "SUCCESS",
        },
    ]
    return {
        "run_id": run_id,
        "discovery": discovery,
        "documents": documents,
        "raw": documents,
        "authorities": authorities,
        "requests": requests + prices,
        "prices": prices,
        "raw_dir": raw_dir,
    }


def _validate(bundle: dict):
    return ca.validate_live_evidence_linkage(
        canonical_run_id=bundle["run_id"],
        discovery_records=bundle["discovery"],
        document_records=bundle["documents"],
        raw_manifest_entries=bundle["raw"],
        authority_rows=bundle["authorities"],
        request_logs=bundle["requests"],
        price_request_logs=bundle["prices"],
        artifact_paths={"raw": bundle["raw_dir"]},
        current_output_dir=bundle["raw_dir"].parent,
        accounting_cross_invariant_pass=True,
    )


def _gate(result):
    metrics = {
        "preflight_verdict": "READY",
        "document_readiness_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "cohort_frozen_before_price_fetch": True,
        "network_accounting_failure_count": 0,
    }
    metrics.update(result.to_metrics())
    return ca.evaluate_gate06(metrics)


def test_full_success_mocked_orchestration_uses_linkage_truth_source(tmp_path):
    """Mocked preflight→documents→cohort→prices→Gate06 path certifies only real zero counts."""
    bundle = _bundle(tmp_path)
    result = _validate(bundle)
    passed, blockers = _gate(result)
    assert passed is True, blockers
    assert result.all_linkage_valid is True
    assert result.total_linkage_failures == 0
    assert all(v == 0 for k, v in result.to_metrics().items() if k.endswith("_count"))


@pytest.mark.parametrize(
    ("name", "mutate", "counter"),
    [
        ("wrong producing request", lambda b: b["documents"][0].update(producing_request_id="NOPE"), "producing_request_failure_count"),
        ("prior-run request", lambda b: b["requests"][0].update(canonical_run_id="RUN_OLD"), "cross_run_request_linkage_failure_count"),
        ("forbidden raw reuse", lambda b: b["documents"][0].update(retrieval_mode="CACHED_OFFICIAL_RAW"), "historical_raw_reuse_count"),
        ("invalid retrieval mode", lambda b: b["documents"][0].update(retrieval_mode="UNKNOWN"), "invalid_retrieval_mode_count"),
        ("duplicate request", lambda b: b["requests"].append(deepcopy(b["requests"][0])), "physical_request_mutation_failure_count"),
        ("record identity mismatch", lambda b: b["authorities"][0].update(authority_record_id="RCP_WRONG"), "record_identity_failure_count"),
        ("issuer identity mismatch", lambda b: b["authorities"][0].update(issuer_name="다른회사"), "issuer_identity_failure_count"),
        ("candidate wrong window", lambda b: b["prices"][0].update(price_window_start="1900-01-01"), "candidate_linkage_failure_count"),
        ("pykrx wrong ticker", lambda b: b["prices"][1].update(ticker="000660"), "pykrx_linkage_failure_count"),
        ("raw orphan", lambda b: (b["raw_dir"] / "orphan.xml").write_bytes(b"orphan"), "raw_orphan_file_count"),
    ],
)
def test_linkage_negative_cases_fail_gate06(tmp_path, name, mutate, counter):
    bundle = _bundle(tmp_path)
    mutate(bundle)
    result = _validate(bundle)
    passed, blockers = _gate(result)
    assert passed is False, name
    assert result.to_metrics()[counter] > 0, (name, result.to_dict())
    assert blockers


def test_physical_request_conflict_is_immutable_failure(tmp_path):
    bundle = _bundle(tmp_path)
    conflicting = deepcopy(bundle["requests"][0])
    conflicting["outcome"] = "ERROR"
    bundle["requests"].append(conflicting)
    result = _validate(bundle)
    assert result.to_metrics()["physical_request_mutation_failure_count"] >= 2
    assert result.all_linkage_valid is False


def test_mocked_production_price_logs_bind_exact_frozen_identity(tmp_path):
    bundle = _bundle(tmp_path)
    result = _validate(bundle)
    assert result.to_metrics()["candidate_linkage_failure_count"] == 0
    assert result.to_metrics()["pykrx_linkage_failure_count"] == 0
    assert bundle["prices"][0]["authority_record_id"] == bundle["authorities"][0]["authority_record_id"]
    assert bundle["prices"][1]["adjusted"] is True


def test_renderer_closure_is_decision_derived():
    approved = {
        "all_gates_passed": True,
        "gate_06_result": True,
        "gate_15_result": True,
        "production_integration_authorized": True,
        "review_decision": "APPROVED_FOR_PRODUCTION_INTEGRATION",
    }
    assert derive_authority_closed(approved, {"report_truth_sync": "PASS"}) is True
    assert derive_authority_closed({**approved, "production_integration_authorized": False}, {"report_truth_sync": "PASS"}) is False
    assert derive_authority_closed({**approved, "gate_15_result": False}, {"report_truth_sync": "PASS"}) is False
    assert derive_authority_closed(approved, {"report_truth_sync": "FAIL"}) is False


def test_renderer_truth_sync_fails_closed_when_code_equivalence_false(monkeypatch):
    import scripts.render_corporate_action_authority_report as report

    monkeypatch.setattr(report, "_git_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(report, "_git_tree_sha", lambda *args, **kwargs: "TREE")
    monkeypatch.setattr(report, "verify_code_equivalence_between_commits", lambda *args, **kwargs: (True, []))
    binding = {
        "fix_head": "FIX",
        "end_head": "END",
        "fix_tree_sha": "TREE",
        "end_tree_sha": "TREE",
        "code_scope": ["src", "scripts", "tests"],
        "code_diff_paths": [],
        "production_code_equivalent": False,
    }
    truth = evaluate_report_truth_sync(Path("."), "END", {"schema": "manifest"}, {"all_gates_passed": True}, binding)
    assert truth["report_truth_sync"] == "FAIL"
    assert truth["production_certification_valid"] is False
    assert "CODE_TEST_BINDING_FAILURE" in truth["blockers"]


def test_mocked_real_orchestration_reaches_gate06_and_gate15(tmp_path, monkeypatch):
    """Run the production orchestration with mocked HTTP/data providers, never live endpoints."""
    monkeypatch.delenv("CORRECTION_10_OFFLINE_ONLY", raising=False)
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

    result = ca.run_corporate_action_evidence_acquisition_fix03_correction_9(
        output_dir=tmp_path / "mocked_canonical", allow_network=True
    )
    assert result["authority_valid_control_count"] == 8
    assert result["gate_06_result"] is True
    assert result["gate_15_result"] is True
    assert result["network_accounting"]["accounting_cross_invariant_pass"] is True
    assert result["provenance_failures"] == 0
