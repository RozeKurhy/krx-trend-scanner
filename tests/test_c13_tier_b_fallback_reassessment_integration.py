"""Hermetic end-to-end test for the C13 Tier-B offline reassessment path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from trend_scanner.data import corporate_action_authority as ca


SYNTHETIC_ISSUER_HTML = b"""<html><body>
Samsung Electronics Co., Ltd. KS005930
Decision on Stock Split (Update) Mar 16, 2018
Scheduled Listing Date of New Share Certificates May 4, 2018
(originally May 16, 2018) updated details originally announced
</body></html>
"""


def _controls() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(8):
        ticker = "005930" if index == 0 else f"{100000 + index:06d}"
        rows.append({
            "canonical_run_id": "RUN_PARENT",
            "control_id": f"CORP_{ticker}_STOCK_SPLIT",
            "ticker": ticker,
            "issuer_name": "삼성전자" if index == 0 else f"Issuer {index}",
            "corp_code": f"C{index:07d}",
            "source_event_type": "STOCK_SPLIT",
            "normalized_event_type": "STOCK_SPLIT",
            "official_anchor_type": "NEW_SHARE_LISTING_DATE",
            "official_anchor_date": "2018-05-16" if index == 0 else "2018-05-04",
            "price_window_start": "2018-04-25",
            "price_window_end": "2018-05-10",
            "authority_source_tier": "TIER_A1_OPENDART",
            "authority_source_name": "OPENDART_OFFICIAL_API",
            "authority_record_id": "20180223000294" if index == 0 else f"R{index}",
            "producing_request_id": f"REQ_DOC_{ticker}",
            "raw_evidence_path": f"raw/{ticker}.xml",
            "raw_evidence_sha256": f"sha-{index}",
        })
    return rows


def _price_rows(controls: list[dict[str, str]]) -> pd.DataFrame:
    dates = pd.date_range("2018-04-25", "2018-05-10", freq="D").strftime("%Y-%m-%d")
    frames: list[pd.DataFrame] = []
    for control in controls:
        for source, request_id in (("NAVER_DIRECT", f"REQ_NAVER_{control['ticker']}"), ("RAW_PYKRX_COMPARATOR", f"REQ_PYKRX_{control['ticker']}")):
            raw = pd.DataFrame({
                "date": dates,
                "open": [100.0] * len(dates),
                "high": [101.0] * len(dates),
                "low": [99.0] * len(dates),
                "close": [100.0] * len(dates),
                "volume": [1000.0] * len(dates),
            })
            frames.append(ca._c13_normalize_price_frame(raw, control=control, source=source, request_id=request_id))
    return pd.concat(frames, ignore_index=True)


def _write_parent_bundle(root: Path) -> tuple[Path, dict[str, bytes]]:
    parent = root / "c13_live_artifacts"
    parent.mkdir(parents=True)
    controls = _controls()
    control_frame = pd.DataFrame(controls)
    price = _price_rows(controls)
    source_frames = {(c["control_id"], source): price[(price["control_id"] == c["control_id"]) & (price["source"] == source)] for c in controls for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR")}
    request_ids = {(c["control_id"], source): f"REQ_{'NAVER' if source == 'NAVER_DIRECT' else 'PYKRX'}_{c['ticker']}" for c in controls for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR")}
    parity_rows, reconciliation_rows = ca._c13_price_parity_rows(controls, source_frames, request_ids, "RUN_PARENT")
    files: dict[str, bytes] = {}

    def put(name: str, data: bytes) -> None:
        (parent / name).write_bytes(data)
        files[name] = data

    control_path = parent / "corporate_action_review_cohort_v01_fix03_correction_13.csv"
    control_frame.to_csv(control_path, index=False)
    files[control_path.name] = control_path.read_bytes()
    price_path = parent / ca.CORRECTION_13_PRICE_FILE
    price.to_csv(price_path, index=False)
    files[price_path.name] = price_path.read_bytes()
    parity_path = parent / ca.CORRECTION_13_PARITY_FILE
    pd.DataFrame(parity_rows).to_csv(parity_path, index=False)
    files[parity_path.name] = parity_path.read_bytes()
    recon_path = parent / ca.CORRECTION_13_RECONCILIATION_FILE
    pd.DataFrame(reconciliation_rows).to_csv(recon_path, index=False)
    files[recon_path.name] = recon_path.read_bytes()

    probe_rows = [
        {"ticker": "005930", "candidate_rank": 1, "rcept_no": "20180131800068", "report_nm": "주식분할결정", "source": "DART_OFFICIAL_DISCLOSURE", "http_status": 200, "transport_response_sha256": "rank1", "authority_valid": False, "validation_reason": "EVENT_SEMANTIC_BINDING_FAILED"},
        {"ticker": "005930", "candidate_rank": 2, "rcept_no": "20180316800856", "report_nm": "[기재정정]주식분할결정", "source": "", "http_status": 200, "transport_response_sha256": "rank2", "authority_valid": False, "validation_reason": "EMPTY_OR_UNUSABLE_DOCUMENT"},
        {"ticker": "005930", "candidate_rank": 3, "rcept_no": "20180223000294", "report_nm": "주식분할결정", "source": "DART_OFFICIAL_DISCLOSURE", "http_status": 200, "transport_response_sha256": "rank3", "authority_valid": True, "validation_reason": ""},
    ]
    candidate_rows = [
        {"ticker": "005930", "candidate_rank": rank, "rcept_no": rcept, "report_nm": name, "rcept_dt": dt, "corp_code": "C0000000", "event_match_score": 80}
        for rank, rcept, name, dt in ((1, "20180131800068", "주식분할결정", "20180131"), (2, "20180316800856", "[기재정정]주식분할결정", "20180316"), (3, "20180223000294", "주식분할결정", "20180223"))
    ]
    for name, frame in (("corporate_action_document_probe_audit_v01_fix03_correction_13.csv", pd.DataFrame(probe_rows)), ("corporate_action_discovery_candidate_audit_v01_fix03_correction_13.csv", pd.DataFrame(candidate_rows))):
        path = parent / name
        frame.to_csv(path, index=False)
        files[name] = path.read_bytes()

    zero_metrics = {
        "preflight_verdict": "READY", "document_readiness_verdict": "READY", "authority_valid_controls_count": 8, "diversity_pass": True,
        "pagination_incomplete_control_count": 0, "pagination_metadata_inconsistency_count": 0, "pagination_page_count_inconsistency_count": 0,
        "discovery_total_count_mismatch_count": 0, "conflicting_duplicate_rcept_no_count": 0, "candidate_audit_incomplete_count": 0,
        "ranking_order_invariance_failure_count": 0, "selected_record_invariance_failure_count": 0, "historical_raw_reuse_count": 0,
        "physical_request_mutation_failure_count": 0, "live_lineage_failure_count": 0, "claim_event_selection_influence_count": 0,
        "claim_context_selection_influence_count": 0, "claim_anchor_type_selection_influence_count": 0, "claim_anchor_date_selection_influence_count": 0,
        "event_type_ambiguity_count": 0, "event_context_ambiguity_count": 0, "event_timing_ambiguity_count": 0, "semantic_binding_failure_count": 0,
        "global_semantic_block_authority_count": 0, "archive_provenance_failure_count": 0, "archive_member_ambiguity_count": 0,
        "archive_transport_inconsistency_count": 0, "archive_member_inconsistency_count": 0, "producing_request_failure_count": 0,
        "cross_run_request_linkage_failure_count": 0, "invalid_retrieval_mode_count": 0, "record_identity_failure_count": 0,
        "issuer_identity_failure_count": 0, "candidate_linkage_failure_count": 0, "pykrx_linkage_failure_count": 0, "raw_orphan_file_count": 0,
        "network_accounting_failure_count": 0, "total_provenance_failure_count": 0, "linkage_evaluation_status": "EVALUATED", "all_linkage_valid": True,
        "canonical_run_identity_valid": True, "canonical_run_identity_failure_count": 0, "canonical_pytest_summary_immutability_failure_count": 0,
        "canonical_pytest_summary_physically_unchanged": True,
    }
    gate = {"schema": "gate06_corporate_action_reassessment_v01_fix03_correction_13", "canonical_run_id": "RUN_PARENT", **zero_metrics}
    decision = {"canonical_run_id": "RUN_PARENT", "inherited_gate_results": {f"gate_{i:02d}": True for i in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14)}}
    network_logs = [{"control_id": c["control_id"], "source": source, "request_id": request_ids[(c["control_id"], source)], "outcome": "SUCCESS", "physical_attempt": 1, "price_window_start": c["price_window_start"], "price_window_end": c["price_window_end"]} for c in controls for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR")]
    network = {"request_logs": network_logs}
    for name, payload in (("gate06_corporate_action_reassessment_v01_fix03_correction_13.json", gate), ("adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13.json", decision), ("corporate_action_evidence_network_accounting_v01_fix03_correction_13.json", network)):
        put(name, json.dumps(payload).encode())

    manifest = {"artifacts": {name: {"path": name, "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}}
    (parent / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    raw_dir = root / "unresolved_higher_priority_candidate_resolution_v01_fix01" / "issuer_official_raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "samsung_public_disclosure_71206.html").write_bytes(SYNTHETIC_ISSUER_HTML)
    supplemental = raw_dir.parent
    (supplemental / "supplemental_request_log.json").write_text(json.dumps({"requests": [
        {"authority_tier": ca.TIER_B_ISSUER_OFFICIAL, "outcome": "SUCCESS", "url": ca.C13_SAMSUNG_ISSUER_URL, "request_id": "REQ_ISSUER", "completed_at": "2026-08-30T00:00:00Z"},
        {"authority_tier": ca.AuthoritySourceTier.TIER_A2_KRX_KIND.value, "purpose": "CANDIDATE_DISCLOSURE_VIEWER_RETRIEVAL", "outcome": "FAILED", "target_rcept_no": "20180316800856"},
    ]}), encoding="utf-8")
    contract_dir = root / "authority_source_tier_contract_review_v01"
    contract_dir.mkdir(parents=True)
    (contract_dir / "authority_source_tier_contract_review_v01.json").write_text(json.dumps({"contract": "candidate-bound"}), encoding="utf-8")
    return root, files


def test_c13_reassessment_is_hermetic_and_binds_may04_gate_provenance(tmp_path, monkeypatch):
    evidence_root, parent_files = _write_parent_bundle(tmp_path / "evidence")
    raw_path = evidence_root / "unresolved_higher_priority_candidate_resolution_v01_fix01" / "issuer_official_raw" / "samsung_public_disclosure_71206.html"
    contract_path = evidence_root / "authority_source_tier_contract_review_v01" / "authority_source_tier_contract_review_v01.json"
    monkeypatch.setattr(ca, "C13_SAMSUNG_ISSUER_RAW_SHA256", hashlib.sha256(SYNTHETIC_ISSUER_HTML).hexdigest())
    monkeypatch.setattr(ca, "C13_TIER_B_CONTRACT_EVIDENCE_SHA256", hashlib.sha256(contract_path.read_bytes()).hexdigest())
    monkeypatch.setattr(ca.requests.Session, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")))
    regression = {"certification_valid": True, "full_suite_completion": True, "unexpected_failures": [], "unexpected_errors": [], "new_regression_count": 0}
    result = ca.reassess_c13_tier_b_fallback_offline(evidence_root=evidence_root, output_dir=tmp_path / "output", implementation_fix_head="FIX01", implementation_fix_tree="TREE01", regression_certification=regression)
    assert result["selected_rcept_no"] == "20180316800856"
    assert result["active_anchor_date"] == "2018-05-04"
    assert result["unresolved_higher_priority_candidate_count"] == 0
    assert result["samsung_price_parity"]["pre_common_date_count"] >= 5
    assert result["samsung_price_parity"]["post_common_date_count"] >= 5
    assert result["gate06_pass"] is True
    assert result["gate14_pass"] is True
    assert result["gate15_pass"] is True
    assert result["all_gates"]["gate_14_provenance_complete"] is True
    assert result["recommended_next_state"] == "IMPLEMENTATION_FIX02_ACCEPTED_READY_FOR_CLOSURE_REASSESSMENT_V02"
    assert (tmp_path / "output" / "reassessed_corporate_action_controls.csv").is_file()
    assert (tmp_path / "output" / "reassessed_provenance_audit.json").is_file()
    gate14 = json.loads((tmp_path / "output" / "gate14_reassessment.json").read_text())
    assert gate14["gate_14_pass"] is True
    assert gate14["stale_rank3_reference_count"] == 0
    assert gate14["stale_active_may16_reference_count"] == 0
    controls = pd.read_csv(tmp_path / "output" / "reassessed_corporate_action_controls.csv", dtype=str, keep_default_na=False)
    samsung = controls.loc[controls["ticker"].astype(str) == "005930"].iloc[0].to_dict()
    assert samsung["authority_record_id"] == "20180316800856"
    assert samsung["content_authority_tier"] == ca.TIER_B_ISSUER_OFFICIAL
    assert samsung["content_producing_request_id"] == "REQ_ISSUER"
    assert samsung["official_anchor_date"] == "2018-05-04"
    assert samsung["official_anchor_source_value"] == "2018-05-04"
    assert samsung["superseded_anchor_date"] == "2018-05-16"
    assert samsung["selected_source_event_context_id"] == ""
    assert samsung["event_node_path"] == ""
    assert samsung["timing_node_path"] == ""
    assert "20180223000294" not in " ".join(str(value) for key, value in samsung.items() if key in {
        "authority_record_id", "authority_source_name", "producing_request_id", "raw_evidence_path",
        "identity_record_id", "content_source_url", "content_retrieval_request_id",
        "content_producing_request_id", "selected_source_event_context_id", "event_node_path",
        "timing_node_path", "binding_relationship", "lowest_common_ancestor_path",
    })
    gate = json.loads((tmp_path / "output" / "gate06_reassessment.json").read_text())
    assert gate["reassessed_parity_artifact_sha256"] == hashlib.sha256((tmp_path / "output" / "reassessed_event_sensitive_parity.csv").read_bytes()).hexdigest()
    assert gate["metrics"]["gate06_price_provenance"] == "REASSESSED_MAY-04_PARITY"
    assert gate["metrics"]["old_may16_samsung_canonical_price_metric_used"] is False
    for name, before in parent_files.items():
        assert (evidence_root / "c13_live_artifacts" / name).read_bytes() == before
    raw_path.write_bytes(SYNTHETIC_ISSUER_HTML + b"tampered")
    try:
        ca.reassess_c13_tier_b_fallback_offline(evidence_root=evidence_root, output_dir=tmp_path / "tampered-output", implementation_fix_head="FIX01", implementation_fix_tree="TREE01", regression_certification=regression)
    except ValueError as exc:
        assert "FROZEN_EVIDENCE_INTEGRITY_FAILURE" in str(exc)
    else:
        raise AssertionError("tampered frozen evidence must fail closed")
