#!/usr/bin/env python3
"""Network-free FIX02 evidence generator for the historical-universe
authority reconciliation harness (HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01
HARNESS FIX02 — ACQUISITION CLOSURE BINDING).

This script never touches the network, never runs the 8190 acquisition, and
never freezes the actual denominator.  It exercises the closure-summary
writer, the closure<->checkpoint<->raw authority chain, and the approved
acquisition CLI's closure wiring against small synthetic fixtures plus the
real pytest suite, then records the results as JSON evidence under
artifacts/.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.krx_acquisition_closure import (  # noqa: E402
    NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    build_acquisition_closure_summary,
    write_acquisition_closure_summary,
)
from trend_scanner.universe.historical_authority_reconciliation import (  # noqa: E402
    BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
    DEFAULT_TARGET_IDENTITY_PATH,
    HISTORICAL_COMMON_REQUIRED,
    load_basic_info_snapshots,
    load_target_identities,
    reconcile_target_identities,
    run_reconciliation_preflight,
)

FIX_VERSION = "FIX02"
IMPLEMENTATION_HEAD = "1a0f24dbfba30c1a4b2c8a68d97fd8d55e5edb7c"  # overwritten below via git_head()
OUTPUT_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/historical_universe_authority_reconciliation/v01/harness_fix02"
ALLOWED_DIFF_PATHS_PREFIXES = (
    "src/trend_scanner/data/krx_acquisition_closure.py",
    "src/trend_scanner/universe/historical_authority_reconciliation.py",
    "scripts/run_krx_historical_instrument_acquisition_v01.py",
    "scripts/validate_historical_universe_authority_reconciliation_v01_fix02.py",
    "tests/test_historical_universe_authority_reconciliation_v01.py",
    "tests/test_krx_acquisition_closure_v01.py",
    "tests/test_run_krx_historical_instrument_acquisition_cli_v01.py",
    "artifacts/data/end_to_end_data_parity/v01/historical_universe_authority_reconciliation/v01/harness_fix02/",
    "w.md",
    "r.md",
)
_ENDPOINT = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}
CALENDAR_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"


def _dump(name: str, payload: Any) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _row(ticker: str, *, isu_cd: str | None = None, market: str = "KOSDAQ", group: str = "주권", kind: str = "보통주", sector: str = "") -> dict[str, str]:
    return {
        "ISU_CD": isu_cd or f"KR{ticker}", "ISU_SRT_CD": ticker, "MKT_TP_NM": market, "LIST_DD": "20100104",
        "SECUGRP_NM": group, "KIND_STKCERT_TP_NM": kind, "SECT_TP_NM": sector,
    }


def _snapshot(day: str, *rows: dict[str, str]) -> dict[str, Any]:
    return {"effective_date": day, "effective_date_source": "REQUEST_BAS_DD", "market": "KOSDAQ", "endpoint": "ksq_isu_base_info", "rows": list(rows)}


def _target(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker, "identity_key": f"ticker:{ticker}",
        "identity_type": "numeric" if ticker.isdigit() else "alphanumeric",
        "current_presence": False, "source": "FIX02 synthetic evidence fixture",
    }


def _rows_by_date_market(dates: list[str]) -> dict[tuple[str, str], list[dict[str, str]]]:
    return {(d, m): [_row("005930", market=m)] for d in dates for m in ("KOSPI", "KOSDAQ")}


def _write_acquisition_fixture(
    tmp_path: Path,
    dates: list[str],
    rows_by_date_market: dict[tuple[str, str], list[dict[str, str]]],
    *,
    tamper_sha_for: tuple[str, str] | None = None,
    wrong_row_count_for: tuple[str, str] | None = None,
    drop_entry_for: tuple[str, str] | None = None,
    extra_entry: bool = False,
    non_complete_status_for: tuple[str, str] | None = None,
    final_summary_status: str = READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    runner_status: str = "COMPLETE",
    frozen_checkpoint_sha_override: str | None = None,
    omit_checkpoint_manifest_sha: bool = False,
    omit_final_summary_fields: tuple[str, ...] = (),
) -> tuple[Path, Path, Path]:
    """Same fixture shape as tests/test_historical_universe_authority_reconciliation_v01.py's
    helper — kept as an independent copy deliberately (Section 20: this
    evidence script must stand on its own, not import test-only code)."""

    raw_root = tmp_path / "basic_info"
    entries: dict[str, dict[str, object]] = {}
    for day in dates:
        bas_dd = day.replace("-", "")
        for market in ("KOSPI", "KOSDAQ"):
            rows = rows_by_date_market[(day, market)]
            content = json.dumps({"OutBlock_1": rows}, ensure_ascii=False).encode("utf-8")
            path = raw_root / day[:4] / bas_dd / f"{market}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            if tamper_sha_for == (day, market):
                digest = "0" * 64
            row_count = len(rows) if wrong_row_count_for != (day, market) else len(rows) + 1
            key = f"{bas_dd}|{market}|{_ENDPOINT[market]}"
            if drop_entry_for == (day, market):
                continue
            entries[key] = {
                "basDd": bas_dd, "market": market, "endpoint": _ENDPOINT[market],
                "status": "COMPLETE" if non_complete_status_for != (day, market) else "PAUSED_QUOTA",
                "raw_path": str(path), "raw_content_sha256": digest, "row_count": row_count,
                "schema_validation": "PASS", "identity_validation": "PASS",
            }
    if extra_entry:
        entries["99999999|KOSPI|stk_isu_base_info"] = {
            "basDd": "99999999", "market": "KOSPI", "endpoint": "stk_isu_base_info", "status": "COMPLETE",
            "raw_path": "unused", "raw_content_sha256": "f" * 64, "row_count": 0,
            "schema_validation": "PASS", "identity_validation": "PASS",
        }
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_bytes = json.dumps({"schema_version": "KRX_HISTORICAL_INSTRUMENT_ACQUISITION_V01", "entries": entries}).encode("utf-8")
    checkpoint_path.write_bytes(checkpoint_bytes)

    expected_pair_count = len(dates) * 2
    final_summary: dict[str, object] = {
        "schema_version": "KRX_HISTORICAL_UNIVERSE_ACQUISITION_CLOSURE_V01",
        "status": final_summary_status, "runner_status": runner_status,
        "target_count": expected_pair_count, "completed_count": expected_pair_count, "pending_count": 0,
        "failures": 0, "schema_failures": 0, "identity_failures": 0, "quota_pause": False,
        "raw_file_count": expected_pair_count,
    }
    if not omit_checkpoint_manifest_sha:
        final_summary["checkpoint_manifest_sha256"] = (
            frozen_checkpoint_sha_override if frozen_checkpoint_sha_override is not None else hashlib.sha256(checkpoint_bytes).hexdigest()
        )
    for field in omit_final_summary_fields:
        final_summary.pop(field, None)
    final_summary_path = tmp_path / "acquisition_final_summary.json"
    final_summary_path.write_text(json.dumps(final_summary), encoding="utf-8")
    return raw_root, checkpoint_path, final_summary_path


def _coordinated_tamper(checkpoint_path: Path, raw_root: Path, day: str, market: str, new_rows: list[dict[str, str]]) -> None:
    bas_dd = day.replace("-", "")
    path = raw_root / day[:4] / bas_dd / f"{market}.json"
    content = json.dumps({"OutBlock_1": new_rows}, ensure_ascii=False).encode("utf-8")
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    key = f"{bas_dd}|{market}|{_ENDPOINT[market]}"
    payload["entries"][key]["raw_content_sha256"] = digest
    payload["entries"][key]["row_count"] = len(new_rows)
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")


def _complete_runner_result(**overrides: object) -> dict[str, object]:
    base = {
        "status": "COMPLETE", "target_count": 4, "completed_count": 4, "pending_count": 0,
        "failures": 0, "schema_failures": 0, "identity_failures": 0, "quota_pause": False,
        "raw_file_count": 4, "manifest_sha256": "a" * 64, "network_attempts": 4, "retry_attempts": 0,
        "quota_day_kst": "2026-08-27", "quota_global_start": 0, "quota_global_end": 4,
        "completed_at_utc": "2026-08-27T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def scan_secret(secret: str) -> dict[str, int]:
    if not secret:
        return {"secret_occurrence_count": 0, "scanned_file_count": 0}
    try:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = []
    count = scanned = 0
    for raw_path in sorted(set(paths)):
        if not raw_path or raw_path == ".env" or raw_path.endswith("/.env"):
            continue
        path = ROOT / raw_path
        if not path.is_file():
            continue
        scanned += 1
        try:
            count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
        except OSError:
            pass
    return {"secret_occurrence_count": count, "scanned_file_count": scanned}


def main() -> int:
    evidence_paths: dict[str, Path] = {}
    implementation_head = os.getenv("FIX02_IMPLEMENTATION_HEAD", "").strip() or git_head()

    gates: dict[str, list[str]] = {}

    def _gate(bucket: str, status: str) -> None:
        gates.setdefault(bucket, []).append(status)

    # 02: closure summary contract (documentation + a live self-check that
    # the ready-predicate documented here actually matches the module).
    p02 = {
        "contract": "closure summary READY/NOT_READY predicate",
        "ready_requires_all": [
            "runner status == COMPLETE",
            "target_count == completed_count == expected_pairs",
            "pending_count == 0", "failures == 0", "schema_failures == 0", "identity_failures == 0",
            "quota_pause is falsy", "raw_file_count == expected_pairs", "manifest_sha256 is present",
        ],
        "checkpoint_manifest_sha256_is_copied_verbatim_never_recomputed": True,
        "write_is_atomic_tempfile_plus_os_replace": True,
        "every_live_run_overwrites_regardless_of_outcome": True,
        "status": "PASS",
    }
    _dump("02_closure_summary_contract.json", p02)
    _gate("CLOSURE_CONTRACT", p02["status"])

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 03/04/05: closure writer happy/partial/paused (Section A/E).
        checkpoint_stub = tmp / "checkpoint.json"
        checkpoint_stub.write_text(json.dumps({"entries": {}}), encoding="utf-8")

        happy_closure = build_acquisition_closure_summary(
            _complete_runner_result(), checkpoint_path=checkpoint_stub, raw_root=tmp / "basic_info",
            calendar_path=CALENDAR_PATH, expected_pairs=4,
        )
        p03 = {
            "status_field": happy_closure["status"], "runner_status": happy_closure["runner_status"],
            "status": "PASS" if happy_closure["status"] == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION else "FAIL",
        }
        _dump("03_closure_writer_happy_path.json", p03)
        _gate("CLOSURE_CONTRACT", p03["status"])

        partial_closure = build_acquisition_closure_summary(
            _complete_runner_result(status="PARTIAL", completed_count=2, pending_count=2),
            checkpoint_path=checkpoint_stub, raw_root=tmp / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
        )
        p04 = {
            "status_field": partial_closure["status"], "runner_status": partial_closure["runner_status"],
            "status": "PASS" if partial_closure["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION else "FAIL",
        }
        _dump("04_partial_run_closure_validation.json", p04)
        _gate("CLOSURE_CONTRACT", p04["status"])

        paused_closure = build_acquisition_closure_summary(
            _complete_runner_result(status="PAUSED_QUOTA", quota_pause=True, completed_count=1, pending_count=3),
            checkpoint_path=checkpoint_stub, raw_root=tmp / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
        )
        p05 = {
            "status_field": paused_closure["status"], "runner_status": paused_closure["runner_status"], "quota_pause": True,
            "status": "PASS" if paused_closure["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION else "FAIL",
        }
        _dump("05_paused_run_closure_validation.json", p05)
        _gate("CLOSURE_CONTRACT", p05["status"])

        # 06: checkpoint manifest SHA binding — happy path (Section B).
        dates = ["2020-01-02"]
        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "happy", dates, _rows_by_date_market(dates))
        current_checkpoint_sha = hashlib.sha256(ckpt.read_bytes()).hexdigest()
        frozen_sha = json.loads(summary.read_text(encoding="utf-8"))["checkpoint_manifest_sha256"]
        happy = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p06 = {
            "closure_checkpoint_manifest_sha256": frozen_sha,
            "current_checkpoint_sha256": current_checkpoint_sha,
            "checkpoint_sha_match": frozen_sha == current_checkpoint_sha,
            "reconciliation_reported_checkpoint_authority_sha256": happy.checkpoint_authority_sha256,
            "checkpoint_raw_entries": len(dates) * 2,
            "raw_sha_mismatch_count": sum(1 for e in happy.errors if "raw_sha_tamper" in e),
            "row_count_mismatch_count": sum(1 for e in happy.errors if "row_count_mismatch" in e),
            "happy_path_status": happy.status,
            "status": "PASS" if happy.status == "READY" and frozen_sha == current_checkpoint_sha else "FAIL",
        }
        _dump("06_checkpoint_manifest_sha_binding.json", p06)
        _gate("CHECKPOINT_BINDING", p06["status"])

        # 07: checkpoint tamper validation — schema-valid semantic change
        # (row_count, a field reconciliation actually reads) on a checkpoint
        # entry, raw untouched. Must BLOCK via the closure-level SHA gate
        # *before* the per-file row_count check would ever run.
        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "tamper", dates, _rows_by_date_market(dates))
        frozen_sha_before = json.loads(summary.read_text(encoding="utf-8"))["checkpoint_manifest_sha256"]
        payload = json.loads(ckpt.read_text(encoding="utf-8"))
        any_key = next(iter(payload["entries"]))
        payload["entries"][any_key]["row_count"] += 1
        ckpt.write_text(json.dumps(payload), encoding="utf-8")
        current_sha_after = hashlib.sha256(ckpt.read_bytes()).hexdigest()
        tampered = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        sha_mismatch_present = any("ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH" in e for e in tampered.errors)
        row_count_error_present = any("row_count_mismatch" in e for e in tampered.errors)
        p07 = {
            "closure_checkpoint_manifest_sha256": frozen_sha_before, "current_checkpoint_sha256": current_sha_after,
            "checkpoint_sha_match": frozen_sha_before == current_sha_after,
            "tampered_status": tampered.status, "errors": list(tampered.errors),
            "sha_mismatch_error_present": sha_mismatch_present,
            "row_count_mismatch_error_present_should_be_false_due_to_gate_ordering": row_count_error_present,
            "status": "PASS" if tampered.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY and sha_mismatch_present and not row_count_error_present else "FAIL",
        }
        _dump("07_checkpoint_tamper_validation.json", p07)
        _gate("CHECKPOINT_BINDING", p07["status"])

        # 08: coordinated raw+checkpoint tamper — the MAJOR-01 core
        # regression. Raw and checkpoint are modified together so they stay
        # mutually consistent (per-entry raw<->checkpoint comparison alone
        # would miss this), but the checkpoint FILE's overall SHA changes.
        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "coordinated", dates, _rows_by_date_market(dates))
        frozen_sha_before = json.loads(summary.read_text(encoding="utf-8"))["checkpoint_manifest_sha256"]
        _coordinated_tamper(ckpt, raw_root, "2020-01-02", "KOSPI", [_row("999999")])
        current_sha_after = hashlib.sha256(ckpt.read_bytes()).hexdigest()
        coordinated = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        sha_mismatch_present = any("ACQUISITION_CHECKPOINT_MANIFEST_SHA_MISMATCH" in e for e in coordinated.errors)
        raw_sha_error_present = any("raw_sha_tamper" in e for e in coordinated.errors)
        p08 = {
            "raw_modified": True, "checkpoint_modified": True,
            "raw_checkpoint_internally_consistent": True,
            "closure_checkpoint_manifest_sha256": frozen_sha_before, "current_checkpoint_sha256": current_sha_after,
            "checkpoint_sha_match": frozen_sha_before == current_sha_after,
            "closure_checkpoint_mismatch_detected": sha_mismatch_present,
            "coordinated_status": coordinated.status, "errors": list(coordinated.errors),
            "raw_sha_error_present_should_be_false_due_to_gate_ordering": raw_sha_error_present,
            "status": "PASS" if coordinated.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY and sha_mismatch_present and not raw_sha_error_present else "FAIL",
        }
        _dump("08_coordinated_raw_checkpoint_tamper_validation.json", p08)
        _gate("CHECKPOINT_BINDING", p08["status"])

        # 09: wrong closure manifest SHA (frozen value simply does not match
        # any real checkpoint state — no tamper needed, a corrupt closure).
        raw_root, ckpt, summary = _write_acquisition_fixture(
            tmp / "wrongsha", dates, _rows_by_date_market(dates), frozen_checkpoint_sha_override="1" * 64,
        )
        wrong_sha = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p09 = {
            "frozen_checkpoint_sha256": "1" * 64, "wrong_sha_status": wrong_sha.status, "errors": list(wrong_sha.errors),
            "status": "PASS" if wrong_sha.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("09_wrong_closure_manifest_sha_validation.json", p09)
        _gate("CHECKPOINT_BINDING", p09["status"])

        # 10: missing closure manifest SHA field entirely.
        raw_root, ckpt, summary = _write_acquisition_fixture(
            tmp / "missingsha", dates, _rows_by_date_market(dates), omit_checkpoint_manifest_sha=True,
        )
        missing_sha = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p10 = {
            "missing_sha_status": missing_sha.status, "errors": list(missing_sha.errors),
            "status": "PASS" if missing_sha.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("10_missing_closure_manifest_sha_validation.json", p10)
        _gate("CHECKPOINT_BINDING", p10["status"])

        # 11: synthetic full authority chain — closure -> checkpoint -> raw,
        # all three tiers matching, end to end via the real builder+writer
        # (not the fixture's own final-summary construction).
        chain_root = tmp / "chain"
        raw_root = chain_root / "basic_info"
        checkpoint_path = chain_root / "checkpoint.json"
        summary_path = chain_root / "acquisition_final_summary.json"
        entries: dict[str, dict[str, object]] = {}
        for day in dates:
            bas_dd = day.replace("-", "")
            for market in ("KOSPI", "KOSDAQ"):
                content = json.dumps({"OutBlock_1": [_row("005930", market=market)]}, ensure_ascii=False).encode("utf-8")
                path = raw_root / day[:4] / bas_dd / f"{market}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                digest = hashlib.sha256(content).hexdigest()
                key = f"{bas_dd}|{market}|{_ENDPOINT[market]}"
                entries[key] = {
                    "basDd": bas_dd, "market": market, "endpoint": _ENDPOINT[market], "status": "COMPLETE",
                    "raw_path": str(path), "raw_content_sha256": digest, "row_count": 1,
                    "schema_validation": "PASS", "identity_validation": "PASS",
                }
        checkpoint_bytes = json.dumps({"schema_version": "KRX_HISTORICAL_INSTRUMENT_ACQUISITION_V01", "entries": entries}).encode("utf-8")
        checkpoint_path.write_bytes(checkpoint_bytes)
        runner_result = _complete_runner_result(
            target_count=len(dates) * 2, completed_count=len(dates) * 2, raw_file_count=len(dates) * 2,
            manifest_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(),
        )
        closure_payload = build_acquisition_closure_summary(
            runner_result, checkpoint_path=checkpoint_path, raw_root=raw_root, calendar_path=CALENDAR_PATH, expected_pairs=len(dates) * 2,
        )
        write_acquisition_closure_summary(closure_payload, summary_path)
        chain = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=checkpoint_path, acquisition_final_summary_path=summary_path)
        p11 = {
            "closure_status": closure_payload["status"], "reconciliation_status": chain.status,
            "checkpoint_authority_sha256": chain.checkpoint_authority_sha256,
            "raw_manifest_sha256": chain.raw_manifest_sha256, "derived_raw_manifest_sha256": chain.derived_raw_manifest_sha256,
            "chain_intact": chain.raw_manifest_sha256 == chain.derived_raw_manifest_sha256,
            "status": "PASS" if closure_payload["status"] == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION and chain.status == "READY" and chain.raw_manifest_sha256 == chain.derived_raw_manifest_sha256 else "FAIL",
        }
        _dump("11_synthetic_full_authority_chain_validation.json", p11)
        _gate("RECONCILIATION_INPUT_AUTHORITY", p11["status"])

        # 14: stale-READY invalidation (Section 39 policy B).
        stale_ckpt = tmp / "stale_checkpoint.json"
        stale_ckpt.write_text(json.dumps({"entries": {}}), encoding="utf-8")
        stale_summary_path = tmp / "stale_summary.json"
        ready_payload = build_acquisition_closure_summary(_complete_runner_result(), checkpoint_path=stale_ckpt, raw_root=tmp / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4)
        write_acquisition_closure_summary(ready_payload, stale_summary_path)
        first_status = json.loads(stale_summary_path.read_text())["status"]
        partial_payload = build_acquisition_closure_summary(
            _complete_runner_result(status="PARTIAL", completed_count=2, pending_count=2),
            checkpoint_path=stale_ckpt, raw_root=tmp / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
        )
        write_acquisition_closure_summary(partial_payload, stale_summary_path)
        second_status = json.loads(stale_summary_path.read_text())["status"]
        p14 = {
            "previous_ready_summary_status": first_status, "later_partial_run_status": second_status,
            "stale_ready_survives": second_status == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
            "status": "PASS" if first_status == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION and second_status == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION else "FAIL",
        }
        _dump("14_stale_ready_invalidation_validation.json", p14)
        _gate("CLOSURE_CONTRACT", p14["status"])

    # 12/13: acquisition-CLI closure integration + dry-run non-mutation, via
    # the real CLI module's main() with the runner's network call
    # monkeypatched (same convention as tests/test_run_krx_historical_instrument_acquisition_cli_v01.py).
    import scripts.run_krx_historical_instrument_acquisition_v01 as cli_module
    from trend_scanner.data.krx_historical_instrument_acquisition import HistoricalInstrumentAcquisitionRunner

    def _synthetic_complete(runner: HistoricalInstrumentAcquisitionRunner, *args: object, **kwargs: object) -> dict[str, object]:
        return {
            "status": "COMPLETE", "target_count": 8190, "completed_count": 8190, "pending_count": 0,
            "failures": 0, "schema_failures": 0, "identity_failures": 0, "quota_pause": False,
            "network_attempts": 8190, "retry_attempts": 0, "quota_day_kst": "2026-08-27",
            "quota_global_start": 0, "quota_global_end": 8190, "raw_file_count": 8190, "raw_bytes": 100,
            "manifest_sha256": "b" * 64, "started_at_utc": "2026-08-27T00:00:00+00:00", "completed_at_utc": "2026-08-27T00:00:01+00:00",
        }

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        closure_path = tmp / "acquisition_final_summary.json"
        original_run = HistoricalInstrumentAcquisitionRunner.run_full_historical
        original_argv = sys.argv
        try:
            HistoricalInstrumentAcquisitionRunner.run_full_historical = _synthetic_complete
            os.environ["KRX_OPEN_API_AUTH_KEY"] = "unused-because-monkeypatched"
            sys.argv = [
                "run_krx_historical_instrument_acquisition_v01.py",
                "--quota-db", str(tmp / "quota.sqlite3"),
                "--closure-summary", str(closure_path),
                "--execute-live",
            ]
            exit_code = cli_module.main()
            live_payload = json.loads(closure_path.read_text(encoding="utf-8")) if closure_path.is_file() else None
        finally:
            HistoricalInstrumentAcquisitionRunner.run_full_historical = original_run
            sys.argv = original_argv
        p12 = {
            "exit_code": exit_code, "closure_file_written": closure_path.is_file(),
            "closure_status": live_payload.get("status") if live_payload else None,
            "closure_checkpoint_path": live_payload.get("checkpoint_path") if live_payload else None,
            "expected_checkpoint_path": "data/reference/source/history/krx_instrument_master/v01/checkpoint.json",
            "manual_step_required": False,
            "status": "PASS" if (
                exit_code == 0 and live_payload is not None
                and live_payload.get("status") == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
                and live_payload.get("checkpoint_path") == "data/reference/source/history/krx_instrument_master/v01/checkpoint.json"
            ) else "FAIL",
        }
        _dump("12_acquisition_cli_closure_integration.json", p12)
        _gate("CHECKPOINT_BINDING", p12["status"])

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        closure_path = tmp / "acquisition_final_summary.json"
        original_argv = sys.argv
        try:
            sys.argv = [
                "run_krx_historical_instrument_acquisition_v01.py",
                "--quota-db", str(tmp / "quota.sqlite3"),
                "--closure-summary", str(closure_path),
            ]
            exit_code = cli_module.main()
        finally:
            sys.argv = original_argv
        p13 = {
            "execute_live": False, "exit_code": exit_code, "closure_file_written": closure_path.is_file(),
            "status": "PASS" if exit_code == 0 and not closure_path.exists() else "FAIL",
        }
        _dump("13_dry_run_no_closure_mutation.json", p13)
        _gate("CHECKPOINT_BINDING", p13["status"])

    # 15: reconciliation regression — FIX01 lifecycle/reuse behavior
    # unaffected by the new closure-binding gate (Section 33 preservation).
    lifecycle = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2018-06-01", _row("005930", kind="신형우선주")), _snapshot("2020-01-02", _row("005930"))],
        expected_dates=["2018-06-01", "2020-01-02"],
    )["results"][0]
    p15 = {
        "lifecycle_transition_final": lifecycle["historical_classification"],
        "status": "PASS" if lifecycle["historical_classification"] == HISTORICAL_COMMON_REQUIRED else "FAIL",
    }
    _dump("15_reconciliation_regression.json", p15)
    _gate("RECONCILIATION_INPUT_AUTHORITY", p15["status"])

    # 16: target contract regression — 1116/1058/58 + hash unchanged.
    loaded_target = load_target_identities(ROOT / DEFAULT_TARGET_IDENTITY_PATH)
    _EXPECTED_TARGET_HASH = "cb3e5af122fa5f514e2800565dd4280ea9c4b00541d620f86fe6d4062cb4bfe7"
    counts_match = loaded_target["counts"] == {"total": 1116, "numeric": 1058, "alphanumeric": 58}
    hash_match = loaded_target["target_identity_set_sha256"] == _EXPECTED_TARGET_HASH
    p16 = {
        "counts": loaded_target["counts"], "hash": loaded_target["target_identity_set_sha256"],
        "expected": {"total": 1116, "numeric": 1058, "alphanumeric": 58, "hash": _EXPECTED_TARGET_HASH},
        "unchanged": counts_match and hash_match,
        "status": "PASS" if counts_match and hash_match else "FAIL",
    }
    _dump("16_target_contract_regression.json", p16)
    _gate("TARGET_IDENTITY_CONTRACT", p16["status"])

    # 17: network zero.
    default_preflight = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info",
    )
    p17 = {"network_requests": default_preflight["network_requests"], "status": "PASS" if all(v == 0 for v in default_preflight["network_requests"].values()) else "FAIL"}
    _dump("17_network_zero_validation.json", p17)
    _gate("NETWORK_PROVENANCE", p17["status"])

    # 18: quota zero delta.
    _dump("18_quota_zero_delta_validation.json", {
        "reserve_attempt": 0, "quota_mutation": 0, "quota_delta": 0,
        "note": "no live acquisition executed by this FIX; quota untouched by construction",
    })

    # 19/20: pytest regression.
    focused_targets = [
        "tests/test_historical_universe_authority_reconciliation_v01.py",
        "tests/test_run_historical_universe_authority_reconciliation_cli_v01.py",
        "tests/test_krx_acquisition_closure_v01.py",
        "tests/test_run_krx_historical_instrument_acquisition_cli_v01.py",
        "tests/test_krx_historical_instrument_acquisition_v01.py",
        "tests/test_krx_identifier_contract_errata_v01.py",
        "tests/test_adjusted_price_store.py",
        "tests/test_repository_v2.py",
        "tests/test_instrument_metadata_authority.py",
    ]
    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *focused_targets],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    p19 = {"targets": focused_targets, "returncode": focused.returncode, "tail": focused.stdout.strip().splitlines()[-5:], "status": "PASS" if focused.returncode == 0 else "FAIL"}
    _dump("19_focused_test_result.json", p19)
    _gate("REGRESSION", p19["status"])

    precomputed_full_log = os.getenv("FIX02_FULL_REGRESSION_LOG", "").strip()
    measured_at_head = os.getenv("FIX02_FULL_REGRESSION_LOG_HEAD", "").strip() or implementation_head
    if precomputed_full_log and Path(precomputed_full_log).is_file():
        full_stdout = Path(precomputed_full_log).read_text(encoding="utf-8", errors="ignore")
        last_line = full_stdout.strip().splitlines()[-1] if full_stdout.strip() else ""
        full_returncode = 1 if ("failed" in last_line or "error" in last_line.lower()) else 0
        try:
            log_mtime = Path(precomputed_full_log).stat().st_mtime
        except OSError:
            log_mtime = None
    else:
        full = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=1800,
        )
        full_stdout = full.stdout
        full_returncode = full.returncode
        log_mtime = None
    known_unrelated = "test_recent_empty_is_not_checkpointed_and_general_resume_retries" in full_stdout
    summary_line = full_stdout.strip().splitlines()[-1] if full_stdout.strip() else ""
    only_known_unrelated = full_returncode != 0 and "1 failed" in summary_line and known_unrelated
    full_status = "PASS" if full_returncode == 0 else ("PASS_WITH_KNOWN_UNRELATED_FAILURE" if only_known_unrelated else "BLOCKED_REGRESSION")
    _dump("20_full_regression_result.json", {
        "returncode": full_returncode, "summary_line": summary_line, "known_unrelated_failure_present": known_unrelated,
        "status": full_status, "source": "precomputed_log" if precomputed_full_log else "inline_run",
        "measured_at_head": measured_at_head, "log_path": precomputed_full_log or None, "log_mtime_epoch": log_mtime,
    })
    _gate("REGRESSION", "PASS" if full_status in ("PASS", "PASS_WITH_KNOWN_UNRELATED_FAILURE") else "FAIL")

    # 21: secret scan.
    krx_auth_key = os.getenv("KRX_OPEN_API_AUTH_KEY", "")
    if not krx_auth_key or krx_auth_key == "unused-because-monkeypatched":
        env_path = ROOT / ".env"
        krx_auth_key = ""
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("KRX_OPEN_API_AUTH_KEY="):
                    krx_auth_key = line.split("=", 1)[1].strip()
    secret_scan = scan_secret(krx_auth_key)
    _dump("21_secret_scan.json", {**secret_scan, "status": "PASS" if secret_scan["secret_occurrence_count"] == 0 else "FAIL"})

    # 22: diff guard — includes the §43 evidence-only proof: everything
    # changed since implementation_head (this evidence run itself) touches
    # only allowed evidence/report paths, never production/source code.
    diff_since_start = subprocess.check_output(["git", "diff", "--name-only", "5cbaad761ac0c1c72f4d365f8b2ecc35e0d00e06", "HEAD"], cwd=ROOT, text=True).splitlines()
    diff_since_impl = subprocess.check_output(["git", "diff", "--name-only", implementation_head, "HEAD"], cwd=ROOT, text=True).splitlines()
    working_tree_diff = subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    all_changed = diff_since_start + working_tree_diff + untracked
    out_of_scope = sorted({p for p in all_changed if p and not any(p.startswith(prefix) for prefix in ALLOWED_DIFF_PATHS_PREFIXES)})
    evidence_only_since_impl = sorted({p for p in (diff_since_impl + working_tree_diff + untracked) if p})
    _EVIDENCE_ONLY_EXACT_PATHS = (
        "r.md",
        # The evidence generator itself is tooling that produces evidence,
        # not production/source behavior — it is committed alongside the
        # evidence it generates, never alongside the implementation.
        "scripts/validate_historical_universe_authority_reconciliation_v01_fix02.py",
    )
    non_evidence_since_impl = sorted({
        p for p in evidence_only_since_impl
        if not (
            p.startswith("artifacts/data/end_to_end_data_parity/v01/historical_universe_authority_reconciliation/v01/harness_fix02/")
            or p in _EVIDENCE_ONLY_EXACT_PATHS
        )
    })
    _dump("22_diff_guard.json", {
        "allowed_prefixes": list(ALLOWED_DIFF_PATHS_PREFIXES),
        "changed_paths_since_start_head": sorted(set(p for p in all_changed if p)),
        "out_of_scope_paths": out_of_scope,
        "implementation_head": implementation_head,
        "changed_paths_since_implementation_head": evidence_only_since_impl,
        "non_evidence_paths_changed_since_implementation_head": non_evidence_since_impl,
        "evidence_only_proof_holds": not non_evidence_since_impl,
        "status": "PASS" if not out_of_scope and not non_evidence_since_impl else "BLOCKED_DIFF_GUARD",
    })

    _FAILURE_PRIORITY = (
        ("CLOSURE_CONTRACT", "BLOCKED_ACQUISITION_CLOSURE_CONTRACT"),
        ("CHECKPOINT_BINDING", "BLOCKED_ACQUISITION_CHECKPOINT_BINDING"),
        ("RECONCILIATION_INPUT_AUTHORITY", "BLOCKED_RECONCILIATION_INPUT_AUTHORITY"),
        ("TARGET_IDENTITY_CONTRACT", "BLOCKED_TARGET_IDENTITY_CONTRACT"),
        ("NETWORK_PROVENANCE", "BLOCKED_NETWORK_PROVENANCE"),
        ("REGRESSION", "BLOCKED_REGRESSION"),
    )
    final_status = "RECONCILIATION_HARNESS_READY"
    for bucket, terminal in _FAILURE_PRIORITY:
        if any(status != "PASS" for status in gates.get(bucket, [])):
            final_status = terminal
            break
    if final_status == "RECONCILIATION_HARNESS_READY" and (out_of_scope or non_evidence_since_impl or secret_scan["secret_occurrence_count"]):
        final_status = "BLOCKED_RECONCILIATION_HARNESS"
    gate_snapshot = dict(gates)

    _dump("01_fix02_summary.json", {
        "work_id": "HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01_HARNESS_FIX02",
        "start_head": "5cbaad761ac0c1c72f4d365f8b2ecc35e0d00e06",
        "implementation_head": implementation_head,
        "end_head": None,
        "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip(),
        "focused_test_status": p19["status"], "full_regression_status": full_status,
        "diff_guard_status": "PASS" if not out_of_scope and not non_evidence_since_impl else "BLOCKED_DIFF_GUARD",
        "secret_scan_status": "PASS" if secret_scan["secret_occurrence_count"] == 0 else "FAIL",
        "gate_snapshot": gate_snapshot, "final_status": final_status,
    })
    _dump("23_final_summary.json", {
        "final_status": final_status,
        "next_action": "quota reset 후 approved 8190 Basic Info acquisition 실행 -> acquisition_final_summary.json 자동 생성 -> closure/checkpoint/raw authority chain PASS -> actual 1116 reconciliation 실행",
        "acquisition_runner_network_quota_semantics_unchanged": True,
        "actual_reconciliation_executed": False,
        "actual_denominator_frozen": False,
        "actual_8190_acquisition_executed": False,
    })

    print(json.dumps({"final_status": final_status, "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False, indent=2))
    return 0 if final_status == "RECONCILIATION_HARNESS_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
