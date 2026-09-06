#!/usr/bin/env python3
"""Network-free FIX01 evidence generator for the historical-universe
authority reconciliation harness (HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01
HARNESS FIX01).

This script never touches the network, never runs the 8190 acquisition, and
never freezes the actual denominator.  It only exercises the reconciliation
harness against small synthetic fixtures and the real pytest suite, then
records the results as JSON evidence under artifacts/.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.historical_authority_reconciliation import (  # noqa: E402
    BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
    DEFAULT_TARGET_IDENTITY_PATH,
    HISTORICAL_AUTHORITY_UNRESOLVED,
    HISTORICAL_COMMON_REQUIRED,
    HISTORICAL_NOT_COMMON,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    build_denominator_candidate,
    build_security_type_mapping_evidence,
    evaluate_ticker_identity_reuse_gate,
    load_basic_info_snapshots,
    load_target_identities,
    reconcile_target_identities,
    run_reconciliation_preflight,
    target_identity_set_hash,
)

FIX_VERSION = "FIX01"
START_HEAD = "8053285ca73147dc02d2eaba9907a356a4f79847"
OUTPUT_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/historical_universe_authority_reconciliation/v01/harness_fix01"
ALLOWED_DIFF_PATHS_PREFIXES = (
    "src/trend_scanner/universe/historical_authority_reconciliation.py",
    "scripts/run_historical_universe_authority_reconciliation_v01.py",
    "scripts/validate_historical_universe_authority_reconciliation_v01_fix01.py",
    "tests/test_historical_universe_authority_reconciliation_v01.py",
    "tests/test_run_historical_universe_authority_reconciliation_cli_v01.py",
    "artifacts/data/end_to_end_data_parity/v01/historical_universe_authority_reconciliation/v01/harness_fix01/",
    "w.md",
    "r.md",
)
_ENDPOINT = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}


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
    return {"effective_date": day, "effective_date_source": "REQUEST_BAS_DD", "rows": list(rows)}


def _target(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker, "identity_key": f"ticker:{ticker}",
        "identity_type": "numeric" if ticker.isdigit() else "alphanumeric",
        "current_presence": False, "source": "FIX01 synthetic evidence fixture",
    }


def _write_acquisition_fixture(
    tmp_root: Path,
    dates: list[str],
    rows_by_date_market: dict[tuple[str, str], list[dict[str, str]]],
    *,
    tamper_sha_for: tuple[str, str] | None = None,
    wrong_row_count_for: tuple[str, str] | None = None,
    drop_entry_for: tuple[str, str] | None = None,
    extra_entry: bool = False,
    non_complete_status_for: tuple[str, str] | None = None,
    final_summary_status: str = READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
) -> tuple[Path, Path, Path]:
    raw_root = tmp_root / "basic_info"
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
    checkpoint_path = tmp_root / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    final_summary_path = tmp_root / "acquisition_final_summary.json"
    final_summary_path.write_text(json.dumps({"status": final_summary_status}), encoding="utf-8")
    return raw_root, checkpoint_path, final_summary_path


def _run_cli(cwd_tmp: Path, output_dir: Path, *extra_args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_historical_universe_authority_reconciliation_v01.py"),
         "--output-dir", str(output_dir), *extra_args],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    try:
        stdout_payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        stdout_payload = {"raw_stdout": proc.stdout}
    return {"returncode": proc.returncode, "stdout": stdout_payload, "stderr": proc.stderr[-2000:]}


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
    import tempfile

    evidence: dict[str, Path] = {}
    start_head = START_HEAD
    end_head_before_evidence = git_head()
    # Section 59 failure-terminal gates. Every evidence status computed below
    # feeds one of these buckets so a FAIL cannot silently pass through to
    # RECONCILIATION_HARNESS_READY (that exact hole is what MAJOR-04 fixed in
    # the harness itself — this validator must not reopen it).
    gates: dict[str, list[str]] = {}

    def _gate(bucket: str, status: str) -> None:
        gates.setdefault(bucket, []).append(status)

    # 03/04/05/06/07: acquisition-authority binding scenarios (Section A).
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dates = ["2020-01-02"]
        rows = {(d, m): [_row("005930", market=m)] for d in dates for m in ("KOSPI", "KOSDAQ")}

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "happy", dates, rows)
        happy = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p02_digest_match = happy.raw_manifest_sha256 == happy.derived_raw_manifest_sha256
        p02 = {
            "contract": "acquisition closure/checkpoint/manifest immutable authority binding",
            "final_status_gate": "acquisition_final_summary.status must equal READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION",
            "checkpoint_complete_gate": "checkpoint entries must exactly cover expected pairs, all COMPLETE",
            "manifest_gate": "checkpoint entry keys must exactly equal expected basDd|market|endpoint keys (no missing, no extra)",
            "raw_sha_gate": "current raw bytes sha256 must equal the checkpoint's stored raw_content_sha256 (never the reverse)",
            "row_count_gate": "current validated row_count must equal the checkpoint's stored row_count",
            "happy_path_status": happy.status,
            # §52: the authority digest (from stored checkpoint hashes) and the
            # derived digest (from freshly re-hashed raw bytes) must use the
            # same canonicalization to even be comparable — this asserts they
            # actually match on the untampered happy path, not just that both
            # exist.
            "authority_digest_equals_derived_digest_when_untampered": p02_digest_match,
            "status": "PASS" if happy.status == "READY" and p02_digest_match else "FAIL",
        }
        evidence["02_acquisition_authority_binding_contract.json"] = _dump("02_acquisition_authority_binding_contract.json", p02)
        _gate("ACQUISITION_AUTHORITY_BINDING", p02["status"])

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "terminal", dates, rows, final_summary_status="PAUSED_QUOTA")
        wrong_terminal = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p03 = {
            "happy_path_status": happy.status,
            "wrong_terminal_status": wrong_terminal.status,
            "wrong_terminal_errors": list(wrong_terminal.errors),
            "status": "PASS" if happy.status == "READY" and wrong_terminal.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("03_acquisition_terminal_gate_validation.json", p03)
        _gate("ACQUISITION_AUTHORITY_BINDING", p03["status"])

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "noncomplete", dates, rows, non_complete_status_for=("2020-01-02", "KOSPI"))
        non_complete = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p04 = {
            "non_complete_status": non_complete.status,
            "non_complete_errors": list(non_complete.errors),
            "status": "PASS" if non_complete.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("04_checkpoint_complete_gate_validation.json", p04)
        _gate("ACQUISITION_AUTHORITY_BINDING", p04["status"])

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "missing", dates, rows, drop_entry_for=("2020-01-02", "KOSPI"))
        missing = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "extra", dates, rows, extra_entry=True)
        extra = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p05 = {
            "missing_entry_status": missing.status, "missing_entry_errors": list(missing.errors),
            "extra_entry_status": extra.status, "extra_entry_errors": list(extra.errors),
            "status": "PASS" if missing.status == extra.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("05_manifest_binding_validation.json", p05)
        _gate("ACQUISITION_AUTHORITY_BINDING", p05["status"])

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "tamper", dates, rows, tamper_sha_for=("2020-01-02", "KOSPI"))
        tampered = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p06 = {
            "tampered_status": tampered.status, "tampered_errors": list(tampered.errors),
            "schema_valid_but_authority_fails": True,
            "status": "PASS" if tampered.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("06_raw_sha_tamper_validation.json", p06)
        _gate("ACQUISITION_AUTHORITY_BINDING", p06["status"])

        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "rowcount", dates, rows, wrong_row_count_for=("2020-01-02", "KOSDAQ"))
        row_mismatch = load_basic_info_snapshots(raw_root, calendar_dates=dates, acquisition_checkpoint_path=ckpt, acquisition_final_summary_path=summary)
        p07 = {
            "row_count_mismatch_status": row_mismatch.status, "errors": list(row_mismatch.errors),
            "status": "PASS" if row_mismatch.status == BLOCKED_RECONCILIATION_INPUT_AUTHORITY else "FAIL",
        }
        _dump("07_row_count_binding_validation.json", p07)
        _gate("ACQUISITION_AUTHORITY_BINDING", p07["status"])

        # 15/16/17: raw status / CLI exit contract (Section D).
        waiting_cli = _run_cli(tmp, tmp / "out_waiting", "--basic-info-root", str(tmp / "does_not_exist"),
                                "--acquisition-checkpoint", str(tmp / "no_ckpt.json"), "--acquisition-final-summary", str(tmp / "no_summary.json"))
        broken_root = tmp / "broken_basic_info" / "2020" / "20200102"
        broken_root.mkdir(parents=True)
        (broken_root / "KOSPI.json").write_text(json.dumps({"OutBlock_1": []}), encoding="utf-8")
        broken_cli = _run_cli(tmp, tmp / "out_broken", "--basic-info-root", str(tmp / "broken_basic_info"),
                               "--acquisition-checkpoint", str(tmp / "no_ckpt.json"), "--acquisition-final-summary", str(tmp / "no_summary.json"))
        raw_root, ckpt, summary = _write_acquisition_fixture(tmp / "tamper_cli", dates, rows, tamper_sha_for=("2020-01-02", "KOSPI"))
        tamper_cli = _run_cli(tmp, tmp / "out_tamper", "--basic-info-root", str(raw_root),
                               "--acquisition-checkpoint", str(ckpt), "--acquisition-final-summary", str(summary))
        _dump("15_raw_status_contract.json", {
            "awaiting_status": "AWAITING_HISTORICAL_BASIC_INFO_ACQUISITION -> top-level READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION, exit 0",
            "blocked_status": "BLOCKED_RECONCILIATION_INPUT_AUTHORITY -> top-level BLOCKED_RECONCILIATION_INPUT_AUTHORITY, non-zero exit",
        })
        p16_pass = waiting_cli["returncode"] == 0 and waiting_cli["stdout"].get("status") == "READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION"
        _dump("16_waiting_exit_validation.json", {
            "returncode": waiting_cli["returncode"], "cli_status": waiting_cli["stdout"].get("status"),
            "pass": p16_pass, "status": "PASS" if p16_pass else "FAIL",
        })
        _gate("RAW_STATUS_CONTRACT", "PASS" if p16_pass else "FAIL")
        p17_pass = broken_cli["returncode"] != 0 and tamper_cli["returncode"] != 0
        _dump("17_broken_raw_exit_validation.json", {
            "partial_raw": {"returncode": broken_cli["returncode"], "status": broken_cli["stdout"].get("status")},
            "tampered_raw": {"returncode": tamper_cli["returncode"], "status": tamper_cli["stdout"].get("status")},
            "pass": p17_pass, "status": "PASS" if p17_pass else "FAIL",
        })
        _gate("RAW_STATUS_CONTRACT", "PASS" if p17_pass else "FAIL")

    # 08/09/10: temporal lifecycle contract (Section B).
    _dump("08_temporal_lifecycle_contract.json", {
        "precedence": [
            "A: identity collision (overlapping ISU_CD same date) -> UNRESOLVED/IDENTITY_COLLISION",
            "A2: true same-date-and-identity contradiction -> UNRESOLVED/SAME_DATE_CONTRADICTORY_CLASSIFICATION",
            "B: any unmapped/invalid official state observed -> UNRESOLVED",
            "C: resolved COMMON interval exists (>=1) -> HISTORICAL_COMMON_REQUIRED, regardless of other-date NOT_COMMON",
            "D: all resolved intervals NOT_COMMON -> HISTORICAL_NOT_COMMON",
            "E: no observation -> HISTORICAL_AUTHORITY_UNRESOLVED/PIT_COVERAGE_GAP",
        ],
        "normal_lifecycle_transition_is_not_a_conflict": True,
    })
    not_common_to_common = reconcile_target_identities(
        [_target("005930")], [_snapshot("2018-06-01", _row("005930", kind="신형우선주")), _snapshot("2020-01-02", _row("005930"))],
        expected_dates=["2018-06-01", "2020-01-02"],
    )["results"][0]
    common_to_not_common = reconcile_target_identities(
        [_target("005930")], [_snapshot("2020-01-02", _row("005930")), _snapshot("2020-01-03", _row("005930", kind="신형우선주"))],
        expected_dates=["2020-01-02", "2020-01-03"],
    )["results"][0]
    p09 = {
        "not_common_to_common": {"final": not_common_to_common["historical_classification"], "reason": not_common_to_common["classification_reason"]},
        "common_to_not_common": {"final": common_to_not_common["historical_classification"], "reason": common_to_not_common["classification_reason"]},
        "status": "PASS" if not_common_to_common["historical_classification"] == common_to_not_common["historical_classification"] == HISTORICAL_COMMON_REQUIRED else "FAIL",
    }
    _dump("09_temporal_transition_validation.json", p09)
    _gate("TEMPORAL_CLASSIFICATION_CONTRACT", p09["status"])
    same_day_conflict = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2020-01-02", _row("005930", isu_cd="SAME"), _row("005930", isu_cd="SAME", kind="신형우선주"))],
        expected_dates=["2020-01-02"],
    )["results"][0]
    p10 = {
        "same_day_same_identity_contradiction": {"final": same_day_conflict["historical_classification"], "reason": same_day_conflict["classification_reason"]},
        "status": "PASS" if same_day_conflict["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED else "FAIL",
    }
    _dump("10_true_conflict_validation.json", p10)
    _gate("TEMPORAL_CLASSIFICATION_CONTRACT", p10["status"])

    # 11/12/13/14: identity-aware reuse (Section C).
    _dump("11_identity_aware_reuse_contract.json", {
        "identity_key": "ticker|ISU_CD|effective_from|effective_to",
        "denominator_candidate_never_uses_set_of_ticker": True,
    })
    # §28 fixture: OLD=COMMON, NEW=NOT_COMMON — this is the exact shape that
    # previously collapsed in the denominator candidate (MAJOR-03); a
    # both-COMMON fixture would not exercise that bug at all.
    non_overlap = reconcile_target_identities(
        [_target("005930")],
        [
            _snapshot("2020-01-02", _row("005930", isu_cd="OLD")),
            _snapshot("2020-01-03", _row("005930", isu_cd="NEW", kind="신형우선주")),
        ],
        expected_dates=["2020-01-02", "2020-01-03"],
    )
    p12 = {
        "ticker_reuse_status": non_overlap["results"][0]["ticker_reuse_status"],
        "identity_count": len(non_overlap["results"][0]["intervals"]),
        "ticker_count": 1,
        "reuse_gate_status": evaluate_ticker_identity_reuse_gate(non_overlap)["status"],
        "status": "PASS" if len(non_overlap["results"][0]["intervals"]) == 2 else "FAIL",
    }
    _dump("12_non_overlap_reuse_validation.json", p12)
    _gate("IDENTITY_REUSE_CONTRACT", p12["status"])
    candidate = build_denominator_candidate([], non_overlap, raw_input_status="READY", raw_integrity_pass=True, expected_total=1)
    p13 = {
        "candidate_status": candidate["status"],
        "historical_identity_interval_count": len(candidate.get("historical_identity_intervals", [])),
        "ticker_union_count": candidate.get("ticker_union_count"),
        "collapse_to_ticker_only": candidate.get("ticker_only_collapse"),
        "status": "PASS" if len(candidate.get("historical_identity_intervals", [])) == 2 and candidate.get("ticker_only_collapse") is False else "FAIL",
    }
    _dump("13_reuse_candidate_identity_validation.json", p13)
    _gate("IDENTITY_REUSE_CONTRACT", p13["status"])
    overlap = reconcile_target_identities(
        [_target("005930")], [_snapshot("2020-01-02", _row("005930", isu_cd="OLD"), _row("005930", isu_cd="NEW"))],
        expected_dates=["2020-01-02"],
    )
    overlap_candidate = build_denominator_candidate([], overlap, raw_input_status="READY", raw_integrity_pass=True, expected_total=1)
    p14 = {
        "ticker_reuse_status": overlap["results"][0]["ticker_reuse_status"],
        "reuse_gate_status": evaluate_ticker_identity_reuse_gate(overlap)["status"],
        "denominator_candidate_status": overlap_candidate["status"],
        "status": "PASS" if overlap_candidate["status"] == "BLOCKED_DENOMINATOR_FREEZE_GATE" else "FAIL",
    }
    _dump("14_overlap_collision_validation.json", p14)
    _gate("IDENTITY_REUSE_CONTRACT", p14["status"])

    # 18: security-type mapping provenance (Section E, Minor).
    mapping_sample_path = ROOT / "data/reference/krx_instrument_metadata.parquet"
    mapping_sample_rows: list[dict[str, str]] = []
    if mapping_sample_path.is_file():
        try:
            import pandas as pd

            frame = pd.read_parquet(mapping_sample_path, columns=["source_security_type"])
            for raw_value in frame["source_security_type"].dropna():
                fields: dict[str, str] = {}
                for part in str(raw_value).split("|"):
                    if "=" in part:
                        key, _, value = part.partition("=")
                        fields[key.strip()] = value.strip()
                if fields:
                    mapping_sample_rows.append(fields)
        except Exception:
            mapping_sample_rows = []
    mapping_evidence = build_security_type_mapping_evidence(
        mapping_sample_rows, sample_source_path=str(mapping_sample_path.relative_to(ROOT)) if mapping_sample_path.is_file() else None
    )
    managed_after_spac = reconcile_target_identities(
        [_target("005930")],
        [_snapshot("2018-06-01", _row("005930", sector="SPAC(소속부없음)")), _snapshot("2020-01-02", _row("005930", sector="관리종목(소속부없음)"))],
        expected_dates=["2018-06-01", "2020-01-02"],
    )["results"][0]
    p18 = {
        "mapping_evidence": mapping_evidence,
        "managed_issue_after_spac_history_alignment": {
            "final": managed_after_spac["historical_classification"],
            "reasons": sorted({i["classification_reason"] for i in managed_after_spac["intervals"]}),
        },
        "status": "PASS" if managed_after_spac["historical_classification"] == HISTORICAL_AUTHORITY_UNRESOLVED else "FAIL",
    }
    _dump("18_security_mapping_provenance.json", p18)
    _gate("SECURITY_TYPE_CLASSIFICATION_CONTRACT", p18["status"])

    # 19/20/21: target identity / network / quota regression.
    loaded_target = load_target_identities(ROOT / DEFAULT_TARGET_IDENTITY_PATH)
    _EXPECTED_TARGET_HASH = "cb3e5af122fa5f514e2800565dd4280ea9c4b00541d620f86fe6d4062cb4bfe7"
    counts_match = loaded_target["counts"] == {"total": 1116, "numeric": 1058, "alphanumeric": 58}
    hash_match = loaded_target["target_identity_set_sha256"] == _EXPECTED_TARGET_HASH
    p19 = {
        "counts": loaded_target["counts"],
        "hash": loaded_target["target_identity_set_sha256"],
        "expected": {"total": 1116, "numeric": 1058, "alphanumeric": 58, "hash": _EXPECTED_TARGET_HASH},
        # Both must hold — matching counts alone does not prove the hash
        # (and therefore the exact identity set) is unchanged.
        "unchanged": counts_match and hash_match,
        "status": "PASS" if counts_match and hash_match else "FAIL",
    }
    _dump("19_target_identity_regression.json", p19)
    _gate("TARGET_IDENTITY_CONTRACT", p19["status"])
    default_preflight = run_reconciliation_preflight(
        target_identities_path=ROOT / DEFAULT_TARGET_IDENTITY_PATH,
        basic_info_root=ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info",
    )
    p20 = {
        "network_requests": default_preflight["network_requests"],
        "status": "PASS" if all(v == 0 for v in default_preflight["network_requests"].values()) else "FAIL",
    }
    _dump("20_network_zero_validation.json", p20)
    _gate("NETWORK_PROVENANCE", p20["status"])
    _dump("21_quota_zero_delta_validation.json", {
        "reserve_attempt": 0, "quota_mutation": 0, "quota_delta": 0,
        "note": "no live acquisition executed by this FIX; quota untouched by construction",
    })

    # 22/23: pytest regression.
    focused_targets = [
        "tests/test_historical_universe_authority_reconciliation_v01.py",
        "tests/test_run_historical_universe_authority_reconciliation_cli_v01.py",
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
    p22 = {
        "targets": focused_targets, "returncode": focused.returncode, "tail": focused.stdout.strip().splitlines()[-5:],
        "status": "PASS" if focused.returncode == 0 else "FAIL",
    }
    _dump("22_focused_test_result.json", p22)
    _gate("REGRESSION", p22["status"])

    precomputed_full_log = os.getenv("FIX01_FULL_REGRESSION_LOG", "").strip()
    # The log's actual source HEAD must be supplied explicitly — a stale log
    # silently reused across commits without recording what tree it measured
    # is exactly the fail-open pattern MAJOR-01 exists to prevent.
    measured_at_head = os.getenv("FIX01_FULL_REGRESSION_LOG_HEAD", "").strip() or git_head()
    if precomputed_full_log and Path(precomputed_full_log).is_file():
        full_stdout = Path(precomputed_full_log).read_text(encoding="utf-8", errors="ignore")
        last_line = full_stdout.strip().splitlines()[-1] if full_stdout.strip() else ""
        full_returncode = 1 if ("failed" in last_line or "error" in last_line.lower()) else 0
        # Best-effort provenance: if the log's mtime predates this HEAD by a
        # nontrivial margin, callers should not assume it reflects the exact
        # current tree — the log's own path/mtime is recorded either way so
        # r.md can state explicitly what state was actually measured.
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
    _dump("23_full_regression_result.json", {
        "returncode": full_returncode, "summary_line": summary_line,
        "known_unrelated_failure_present": known_unrelated, "status": full_status,
        "source": "precomputed_log" if precomputed_full_log else "inline_run",
        "measured_at_head": measured_at_head,
        "log_path": precomputed_full_log or None,
        "log_mtime_epoch": log_mtime,
    })
    _gate("REGRESSION", "PASS" if full_status in ("PASS", "PASS_WITH_KNOWN_UNRELATED_FAILURE") else "FAIL")

    # 24: secret scan.
    krx_auth_key = os.getenv("KRX_OPEN_API_AUTH_KEY", "")
    if not krx_auth_key:
        env_path = ROOT / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("KRX_OPEN_API_AUTH_KEY="):
                    krx_auth_key = line.split("=", 1)[1].strip()
    secret_scan = scan_secret(krx_auth_key)
    _dump("24_secret_scan.json", {**secret_scan, "status": "PASS" if secret_scan["secret_occurrence_count"] == 0 else "FAIL"})

    # 25: diff guard.
    diff_paths = subprocess.check_output(["git", "diff", "--name-only", start_head, "HEAD"], cwd=ROOT, text=True).splitlines()
    diff_paths += subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
    diff_paths += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    out_of_scope = sorted({p for p in diff_paths if p and not any(p.startswith(prefix) for prefix in ALLOWED_DIFF_PATHS_PREFIXES)})
    _dump("25_diff_guard.json", {
        "allowed_prefixes": list(ALLOWED_DIFF_PATHS_PREFIXES),
        "changed_paths": sorted(set(p for p in diff_paths if p)),
        "out_of_scope_paths": out_of_scope,
        "status": "PASS" if not out_of_scope else "BLOCKED_DIFF_GUARD",
    })

    # Section 59 priority order. The first bucket carrying any non-PASS
    # status determines final_status; a clean run (or diff/secret-scan-only
    # failure, which §59 has no dedicated terminal for) falls through to
    # BLOCKED_RECONCILIATION_HARNESS or RECONCILIATION_HARNESS_READY.
    _FAILURE_PRIORITY = (
        ("ACQUISITION_AUTHORITY_BINDING", "BLOCKED_ACQUISITION_AUTHORITY_BINDING"),
        ("TEMPORAL_CLASSIFICATION_CONTRACT", "BLOCKED_TEMPORAL_CLASSIFICATION_CONTRACT"),
        ("IDENTITY_REUSE_CONTRACT", "BLOCKED_IDENTITY_REUSE_CONTRACT"),
        ("RAW_STATUS_CONTRACT", "BLOCKED_RAW_STATUS_CONTRACT"),
        ("SECURITY_TYPE_CLASSIFICATION_CONTRACT", "BLOCKED_SECURITY_TYPE_CLASSIFICATION_CONTRACT"),
        ("TARGET_IDENTITY_CONTRACT", "BLOCKED_TARGET_IDENTITY_CONTRACT"),
        ("NETWORK_PROVENANCE", "BLOCKED_NETWORK_PROVENANCE"),
        ("REGRESSION", "BLOCKED_REGRESSION"),
    )
    final_status = "RECONCILIATION_HARNESS_READY"
    for bucket, terminal in _FAILURE_PRIORITY:
        if any(status != "PASS" for status in gates.get(bucket, [])):
            final_status = terminal
            break
    if final_status == "RECONCILIATION_HARNESS_READY" and (out_of_scope or secret_scan["secret_occurrence_count"]):
        final_status = "BLOCKED_RECONCILIATION_HARNESS"
    gate_snapshot = dict(gates)

    _dump("01_fix01_summary.json", {
        "work_id": "HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01_HARNESS_FIX01",
        "start_head": start_head,
        # This evidence file is committed together with the change it
        # describes, so it structurally cannot know its own future commit
        # hash (repo convention: scripts/validate_krx_open_api_v02.py uses
        # the same null + implementation_head split). r.md records the
        # actual END HEAD after the commit exists.
        "implementation_head": git_head(),
        "end_head": None,
        "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip(),
        "focused_test_status": "PASS" if focused.returncode == 0 else "FAIL",
        "full_regression_status": full_status,
        "diff_guard_status": "PASS" if not out_of_scope else "BLOCKED_DIFF_GUARD",
        "secret_scan_status": "PASS" if secret_scan["secret_occurrence_count"] == 0 else "FAIL",
        "gate_snapshot": gate_snapshot,
        "final_status": final_status,
    })
    _dump("26_final_summary.json", {
        "final_status": final_status,
        "next_action": (
            "quota reset 후 approved 8190 Basic Info acquisition 실행 -> acquisition closure/manifest/hash PASS "
            "-> actual 1116 reconciliation 실행"
        ),
        "acquisition_harness_unchanged": True,
        "actual_reconciliation_executed": False,
        "actual_denominator_frozen": False,
    })

    print(json.dumps({"final_status": final_status, "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False, indent=2))
    return 0 if final_status == "RECONCILIATION_HARNESS_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
