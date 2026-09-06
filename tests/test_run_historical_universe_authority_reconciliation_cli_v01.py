"""CLI exit-code contract for the historical-universe reconciliation preflight.

Section 32/33: BLOCKED states must never return CLI exit 0; normal preflight
waiting (raw archive absent) must return exit 0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_ENDPOINT = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}


def _run_cli(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    output_dir = tmp_path / "harness_output"
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_historical_universe_authority_reconciliation_v01.py"),
            "--output-dir", str(output_dir),
            *extra_args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_fixture(tmp_path: Path, *, tamper: bool) -> tuple[Path, Path, Path]:
    dates = ["2020-01-02"]
    raw_root = tmp_path / "basic_info"
    entries: dict[str, object] = {}
    for market in ("KOSPI", "KOSDAQ"):
        rows = [{
            "ISU_CD": "KR005930", "ISU_SRT_CD": "005930", "MKT_TP_NM": market, "LIST_DD": "20100104",
            "SECUGRP_NM": "주권", "KIND_STKCERT_TP_NM": "보통주", "SECT_TP_NM": "",
        }]
        content = json.dumps({"OutBlock_1": rows}, ensure_ascii=False).encode("utf-8")
        path = raw_root / "2020" / "20200102" / f"{market}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        entries[f"20200102|{market}|{_ENDPOINT[market]}"] = {
            "basDd": "20200102", "market": market, "endpoint": _ENDPOINT[market],
            "status": "COMPLETE", "raw_path": str(path),
            "raw_content_sha256": "0" * 64 if tamper and market == "KOSPI" else digest,
            "row_count": 1, "schema_validation": "PASS", "identity_validation": "PASS",
        }
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    final_summary_path = tmp_path / "acquisition_final_summary.json"
    final_summary_path.write_text(
        json.dumps({"status": "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"}), encoding="utf-8"
    )
    return raw_root, checkpoint_path, final_summary_path


def test_raw_root_absent_exits_zero_as_normal_waiting(tmp_path: Path) -> None:
    result = _run_cli(
        tmp_path,
        "--basic-info-root", str(tmp_path / "missing_basic_info"),
        "--acquisition-checkpoint", str(tmp_path / "missing_checkpoint.json"),
        "--acquisition-final-summary", str(tmp_path / "missing_summary.json"),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "READY_FOR_RECONCILIATION_AFTER_AUTHORITY_ACQUISITION"


def test_partial_raw_archive_exits_non_zero(tmp_path: Path) -> None:
    raw_root = tmp_path / "basic_info" / "2020" / "20200102"
    raw_root.mkdir(parents=True)
    (raw_root / "KOSPI.json").write_text(json.dumps({"OutBlock_1": []}), encoding="utf-8")
    result = _run_cli(
        tmp_path,
        "--basic-info-root", str(tmp_path / "basic_info"),
        "--acquisition-checkpoint", str(tmp_path / "missing_checkpoint.json"),
        "--acquisition-final-summary", str(tmp_path / "missing_summary.json"),
    )
    assert result.returncode != 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED_RECONCILIATION_INPUT_AUTHORITY"


def test_tampered_raw_sha_exits_non_zero(tmp_path: Path) -> None:
    raw_root, checkpoint_path, final_summary_path = _write_fixture(tmp_path, tamper=True)
    result = _run_cli(
        tmp_path,
        "--basic-info-root", str(raw_root),
        "--acquisition-checkpoint", str(checkpoint_path),
        "--acquisition-final-summary", str(final_summary_path),
    )
    assert result.returncode != 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED_RECONCILIATION_INPUT_AUTHORITY"


def test_wrong_acquisition_terminal_exits_non_zero(tmp_path: Path) -> None:
    raw_root, checkpoint_path, final_summary_path = _write_fixture(tmp_path, tamper=False)
    final_summary_path.write_text(json.dumps({"status": "PAUSED_QUOTA"}), encoding="utf-8")
    result = _run_cli(
        tmp_path,
        "--basic-info-root", str(raw_root),
        "--acquisition-checkpoint", str(checkpoint_path),
        "--acquisition-final-summary", str(final_summary_path),
    )
    assert result.returncode != 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED_RECONCILIATION_INPUT_AUTHORITY"
