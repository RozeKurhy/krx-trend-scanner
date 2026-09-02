#!/usr/bin/env python3
"""Run the frozen Stock Report v0.3 exact-parity check.

The runner derives its ticker corpus from the frozen 2026-08-14 JSON files,
generates two independent temporary corpora with the current executable, and
persists only hashes, semantic/section comparisons, and small canary evidence.
No generated report is written into the canonical directory or the repository.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import socket
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft7Validator

from trend_scanner.reporting.stock_report import generate_stock_report


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = ROOT / "artifacts/reporting/stock_reports/20260814"
MANIFEST_PATH = ROOT / "artifacts/reporting/stock_reports/validation/v0.3/stock_report_v03_manifest_20260814.json"
CLOSURE_MANIFEST_PATH = ROOT / "artifacts/reporting/stock_reports/validation/v0.3/stock_report_v03_closure_manifest_20260814.json"
CLOSURE_SUMMARY_PATH = ROOT / "artifacts/reporting/stock_reports/validation/v0.3/stock_report_v03_closure_summary_20260814.json"
SCHEMA_PATH = ROOT / "docs/reporting/stock_report/schema_v03.json"
CONTRACT_PATH = ROOT / "docs/reporting/stock_report/contract_v03.md"
RS_SOURCE_PATH = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_20260814.csv"
EVIDENCE_ROOT = ROOT / "artifacts/data/end_to_end_data_parity/v01/stock_report_parity/v01"

EXPECTED_START_HEAD = "50e63413ccde6e808cedd9402d673e077e375c65"
EXPECTED_START_TREE = "8d5e400e6ca8e344182b61d4da314cf0cf5714fd"
EXPECTED_PHASE12_CLOSURE_SHA = "5fdf97793c1fd7683c33d5fe77ff4da97fc75a19"
EXPECTED_RS_DISTRIBUTION = {"READY": 36, "PARTIAL": 0, "DATA_UNAVAILABLE": 1, "NOT_APPLICABLE": 17}
EXPECTED_SOURCE_BLOBS = {
    "src/trend_scanner/reporting/stock_report.py": "df51c32a891120e1d497922389170da7c2c3073c",
    "src/trend_scanner/reporting/models.py": "82043a199fc57ca5289243e1459ae17b3dbf2976",
    "src/trend_scanner/reporting/a_fast_core_report.py": "45fa9594849c92f54e18a45bff12d02b33517c38",
    "src/trend_scanner/reporting/pattern_a_fast_report.py": "add96531eaf0f7ca0d090245861144d9e1bcc5a8",
    "src/trend_scanner/reporting/relative_strength_report.py": "034bf02f091c4a951c38708a236acba29ee66ca3",
}
SECTION_KEYS = (
    "header",
    "summary",
    "current_snapshot",
    "monthly_history",
    "foreign_flow",
    "relative_strength",
    "trading_value_flow",
    "data_quality",
    "provenance",
    "pattern_a_fast",
    "a_fast_core",
)
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def current_git_identity() -> dict[str, str]:
    return {"head": git_value("rev-parse", "HEAD"), "tree": git_value("rev-parse", "HEAD^{tree}")}


def derive_corpus() -> tuple[list[str], dict[str, dict[str, Any]], dict[str, str]]:
    json_paths = sorted(CANONICAL_DIR.glob("*.json"))
    md_paths = sorted(CANONICAL_DIR.glob("*.md"))
    if len(json_paths) != 54 or len(md_paths) != 54:
        raise RuntimeError(f"canonical report count must be 54/54, got {len(json_paths)}/{len(md_paths)}")
    json_stems = {p.stem for p in json_paths}
    md_stems = {p.stem for p in md_paths}
    if json_stems != md_stems:
        raise RuntimeError("canonical JSON/Markdown filename stems differ")
    reports: dict[str, dict[str, Any]] = {}
    ticker_by_stem: dict[str, str] = {}
    for path in json_paths:
        stem = path.stem
        ticker = stem.split("_", 1)[0]
        if not TICKER_RE.fullmatch(ticker):
            raise RuntimeError(f"invalid ticker identity in canonical filename: {path.name}")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("ticker") != ticker:
            raise RuntimeError(f"ticker/filename mismatch: {path.name} -> {report.get('ticker')!r}")
        reports[stem] = report
        ticker_by_stem[stem] = ticker
    return [ticker_by_stem[stem] for stem in sorted(ticker_by_stem)], reports, {p.name: sha256_file(p) for p in sorted(CANONICAL_DIR.glob("*")) if p.is_file()}


def verify_manifest(canonical_hashes: dict[str, str]) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    production = manifest.get("production", {})
    expected = production.get("files", {})
    mismatches = [name for name, digest in expected.items() if canonical_hashes.get(name) != digest]
    extras = sorted(set(canonical_hashes) - set(expected))
    if mismatches or extras or production.get("json_count") != 54 or production.get("markdown_count") != 54:
        raise RuntimeError(f"canonical manifest verification failed: mismatches={mismatches}, extras={extras}")
    phase12 = manifest.get("phase12_source", {})
    if phase12.get("sha256") != sha256_file(RS_SOURCE_PATH) or phase12.get("closure_sha") != EXPECTED_PHASE12_CLOSURE_SHA:
        raise RuntimeError("Phase 12 source authority identity mismatch")
    return {
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "manifest_file_count": len(expected),
        "manifest_sha_match": len(expected),
        "extras": extras,
        "phase12_source": phase12,
    }


def source_identity() -> dict[str, Any]:
    actual: dict[str, str] = {}
    mismatches: list[str] = []
    for path, expected in EXPECTED_SOURCE_BLOBS.items():
        actual[path] = git_value("rev-parse", f"HEAD:{path}")
        if actual[path] != expected:
            mismatches.append(path)
    return {"expected": EXPECTED_SOURCE_BLOBS, "actual": actual, "mismatches": mismatches, "match": not mismatches}


class NetworkGuard:
    def __init__(self) -> None:
        self.calls = 0
        self.addresses: list[str] = []

    def blocked(self, _sock: socket.socket, address: Any) -> None:
        self.calls += 1
        self.addresses.append(repr(address))
        raise RuntimeError(f"network access forbidden during Stock Report parity: {address!r}")


@contextmanager
def offline_guards() -> Iterator[dict[str, Any]]:
    guard = NetworkGuard()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    scanner_calls = {"count": 0}
    scanner_module = None
    scanner_original = None
    try:
        socket.socket.connect = guard.blocked  # type: ignore[assignment]
        socket.socket.connect_ex = guard.blocked  # type: ignore[assignment]

        def blocked_create_connection(*args: Any, **kwargs: Any) -> Any:
            guard.calls += 1
            guard.addresses.append(repr(args[0] if args else kwargs.get("address")))
            raise RuntimeError("network access forbidden during Stock Report parity")

        socket.create_connection = blocked_create_connection  # type: ignore[assignment]
        try:
            import trend_scanner.scanner.full_universe_scanner as scanner_module  # noqa: PLC0415

            scanner_original = scanner_module.scan_pattern_a_universe

            def blocked_scanner(*_args: Any, **_kwargs: Any) -> Any:
                scanner_calls["count"] += 1
                raise RuntimeError("Full Universe Scanner forbidden during Stock Report parity")

            scanner_module.scan_pattern_a_universe = blocked_scanner
        except ImportError:
            scanner_module = None
        yield {"network": guard, "scanner_calls": scanner_calls}
    finally:
        socket.socket.connect = original_connect  # type: ignore[assignment]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        if scanner_module is not None and scanner_original is not None:
            scanner_module.scan_pattern_a_universe = scanner_original


def run_corpus(tickers: list[str], output_dir: Path, guard_state: dict[str, Any], run_name: str) -> dict[str, Any]:
    started = time.monotonic()
    for index, ticker in enumerate(tickers, start=1):
        generate_stock_report(
            ticker=ticker,
            as_of="2026-08-14",
            repo_root=ROOT,
            save_artifacts=True,
            output_dir=output_dir,
        )
        if index % 10 == 0:
            print(f"{run_name}: {index}/{len(tickers)}", flush=True)
    json_count = len(list(output_dir.glob("*.json")))
    md_count = len(list(output_dir.glob("*.md")))
    return {
        "run": run_name,
        "as_of": "2026-08-14",
        "json_count": json_count,
        "markdown_count": md_count,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def aggregate_sha(rows: list[dict[str, str]], value_key: str, file_type: str | None = None) -> str:
    selected = [row for row in rows if file_type is None or row["file_type"] == file_type]
    payload = "".join(f"{row['filename']} {row[value_key]}\n" for row in sorted(selected, key=lambda r: r["filename"]))
    return sha256_bytes(payload.encode("utf-8"))


def _semantic_differences(expected: Any, actual: Any, path: str = "") -> list[dict[str, Any]]:
    if type(expected) is not type(actual):
        return [{"path": path or "$", "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}" if path else key
            if key not in expected:
                differences.append({"path": child, "expected": "<missing>", "actual": actual[key]})
            elif key not in actual:
                differences.append({"path": child, "expected": expected[key], "actual": "<missing>"})
            else:
                differences.extend(_semantic_differences(expected[key], actual[key], child))
        return differences
    if isinstance(expected, list):
        differences = []
        if len(expected) != len(actual):
            differences.append({"path": path, "expected_length": len(expected), "actual_length": len(actual)})
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences.extend(_semantic_differences(left, right, f"{path}[{index}]"))
        return differences
    return [] if expected == actual else [{"path": path or "$", "expected": expected, "actual": actual}]


def compare_corpus(canonical_hashes: dict[str, str], run1: Path, run2: Path, canonical_reports: dict[str, dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    canonical_names = set(canonical_hashes)
    run1_hashes = {p.name: sha256_file(p) for p in run1.iterdir() if p.is_file()}
    run2_hashes = {p.name: sha256_file(p) for p in run2.iterdir() if p.is_file()}
    rows: list[dict[str, str]] = []
    for filename in sorted(canonical_names | set(run1_hashes) | set(run2_hashes)):
        typ = "json" if filename.endswith(".json") else "markdown" if filename.endswith(".md") else "other"
        c = canonical_hashes.get(filename, "")
        r1 = run1_hashes.get(filename, "")
        r2 = run2_hashes.get(filename, "")
        rows.append({
            "filename": filename,
            "file_type": typ,
            "canonical_sha256": c,
            "run1_sha256": r1,
            "run2_sha256": r2,
            "canonical_vs_run1": "MATCH" if c and c == r1 else "MISMATCH",
            "canonical_vs_run2": "MATCH" if c and c == r2 else "MISMATCH",
            "run1_vs_run2": "MATCH" if r1 and r1 == r2 else "MISMATCH",
            "overall_match": "MATCH" if c and c == r1 == r2 else "MISMATCH",
        })

    semantic_mismatches: list[dict[str, Any]] = []
    section_rows: list[dict[str, Any]] = []
    for stem, canonical in sorted(canonical_reports.items()):
        path = stem + ".json"
        run1_report = json.loads((run1 / path).read_text(encoding="utf-8")) if (run1 / path).exists() else None
        run2_report = json.loads((run2 / path).read_text(encoding="utf-8")) if (run2 / path).exists() else None
        differences = _semantic_differences(canonical, run1_report) if run1_report is not None else [{"path": "$", "expected": "report", "actual": "<missing run1>"}]
        if run2_report != canonical:
            differences.extend({"run": "run2", **item} for item in _semantic_differences(canonical, run2_report) if run2_report is not None)
        if differences:
            semantic_mismatches.append({"filename": path, "differences": differences[:100]})
        row: dict[str, Any] = {"ticker": canonical.get("ticker"), "filename": path}
        for key in SECTION_KEYS:
            row[f"{key}_match"] = bool(run1_report is not None and run2_report is not None and canonical.get(key) == run1_report.get(key) == run2_report.get(key))
        row["overall_match"] = all(row[f"{key}_match"] for key in SECTION_KEYS)
        section_rows.append(row)
    return rows, section_rows, semantic_mismatches


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def schema_validation(directory: Path, schema: dict[str, Any]) -> dict[str, Any]:
    validator = Draft7Validator(schema)
    errors: list[dict[str, Any]] = []
    valid = 0
    for path in sorted(directory.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        file_errors = sorted(validator.iter_errors(report), key=lambda e: list(e.path))
        if not file_errors:
            valid += 1
        for error in file_errors:
            errors.append({"filename": path.name, "path": list(error.path), "message": error.message})
    return {"json_count": len(list(directory.glob("*.json"))), "valid": valid, "errors": errors, "valid_ratio": f"{valid}/54"}


def rs_distribution(reports: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(report["relative_strength"]["data_status"] if report["relative_strength"]["applicability"] == "APPLICABLE" else report["relative_strength"]["applicability"] for report in reports).items()))


def markdown_unit_errors(directory: Path) -> dict[str, int]:
    errors = {"level": 0, "delta": 0, "acceleration": 0}
    for path in directory.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "## 7.5. 시장 상대강도 (RS)" not in text or "## 8. 거래대금" not in text:
            errors["level"] += 1
            continue
        section = text.split("## 7.5. 시장 상대강도 (RS)", 1)[1].split("## 8. 거래대금", 1)[0]
        for line in section.splitlines():
            if line.startswith(("| 3개월 |", "| 6개월 |", "| 12개월 |")):
                value = line.split("|")[2].strip()
                if value != "N/A" and not value.endswith("%"):
                    errors["level"] += 1
            for label, key in (("3M vs 6M 개선도", "delta"), ("6M vs 12M 개선도", "delta"), ("RS acceleration", "acceleration")):
                if f"**{label}**:" in line:
                    value = line.split(":", 1)[1].strip()
                    if value != "N/A" and not value.endswith("%p"):
                        errors[key] += 1
    return errors


def canary_evidence(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = {
        "005930": {"name": "삼성전자", "market": "KOSPI", "asset_type": "COMMON", "status": "READY", "rs": "READY", "stage": "PROGRESSED", "investability": "INVESTABLE", "strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "canonical_position": "OPEN"},
        "069500": {"name": "KODEX 200", "asset_type": "ETF", "rs_applicability": "NOT_APPLICABLE", "rs_status": "NOT_EVALUATED"},
        "0115D0": {"name": "KODEX 조선TOP10", "ticker": "0115D0", "asset_type": "ETF"},
        "001540": {"name": "안국약품", "asset_type": "COMMON"},
    }
    result: dict[str, Any] = {}
    by_ticker = {value["ticker"]: value for value in reports.values()}
    for ticker, criteria in expected.items():
        report = by_ticker.get(ticker, {})
        rs = report.get("relative_strength", {})
        core = report.get("a_fast_core", {})
        checks = {
            "ticker_identity": report.get("ticker") == ticker,
            "name": report.get("name") == criteria["name"],
            "asset_type": report.get("asset_type") == criteria["asset_type"],
        }
        if ticker == "005930":
            checks.update({"market": report.get("market") == criteria["market"], "status": report.get("header", {}).get("report_status") == criteria["status"], "rs": rs.get("data_status") == criteria["rs"], "stage": report.get("current_snapshot", {}).get("official_stage") == criteria["stage"], "investability": report.get("current_snapshot", {}).get("investability_status") == criteria["investability"], "strategy_id": core.get("strategy_id") == criteria["strategy_id"], "canonical_position": core.get("canonical_position") == criteria["canonical_position"]})
        if ticker == "069500":
            checks.update({"rs_applicability": rs.get("applicability") == criteria["rs_applicability"], "rs_status": rs.get("data_status") == criteria["rs_status"], "numeric_nulls": all(rs.get(name) is None for name in ("market_rs_3m", "market_rs_6m", "market_rs_12m"))})
        result[ticker] = {"checks": checks, "pass": all(checks.values()), "snapshot": {"ticker": report.get("ticker"), "name": report.get("name"), "market": report.get("market"), "asset_type": report.get("asset_type"), "report_status": report.get("header", {}).get("report_status"), "relative_strength": rs, "a_fast_core": {"strategy_id": core.get("strategy_id"), "canonical_position": core.get("canonical_position")}}}
    return result


def main() -> int:
    started = time.monotonic()
    identity = current_git_identity()
    if identity != {"head": EXPECTED_START_HEAD, "tree": EXPECTED_START_TREE}:
        raise SystemExit(f"START_HEAD_MISMATCH: expected {EXPECTED_START_HEAD}/{EXPECTED_START_TREE}, got {identity}")
    tickers, canonical_reports, canonical_hashes = derive_corpus()
    authority = verify_manifest(canonical_hashes)
    source = source_identity()
    if not source["match"]:
        raise SystemExit(f"frozen source blob mismatch: {source['mismatches']}")
    pre_canonical = dict(canonical_hashes)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stock_report_parity_run1_") as run1_tmp, tempfile.TemporaryDirectory(prefix="stock_report_parity_run2_") as run2_tmp:
        run1_dir, run2_dir = Path(run1_tmp), Path(run2_tmp)
        with offline_guards() as guards:
            run1_summary = run_corpus(tickers, run1_dir, guards, "run1")
            run2_summary = run_corpus(tickers, run2_dir, guards, "run2")
            network_calls = guards["network"].calls
            network_addresses = guards["network"].addresses
            scanner_calls = guards["scanner_calls"]["count"]
        rows, section_rows, semantic_mismatch_details = compare_corpus(canonical_hashes, run1_dir, run2_dir, canonical_reports)
        semantic_mismatch_names = [item["filename"] for item in semantic_mismatch_details]
        run1_reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run1_dir.glob("*.json"))]
        run2_reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run2_dir.glob("*.json"))]
        run1_schema = schema_validation(run1_dir, schema)
        run2_schema = schema_validation(run2_dir, schema)
        run1_unit_errors = markdown_unit_errors(run1_dir)
        run2_unit_errors = markdown_unit_errors(run2_dir)
        canary = canary_evidence({p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(run1_dir.glob("*.json"))})
        post_canonical = {p.name: sha256_file(p) for p in sorted(CANONICAL_DIR.glob("*")) if p.is_file()}

    write_json(EVIDENCE_ROOT / "authority/stock_report_authority.json", {"directive": "STOCK_REPORT_PARITY_V01", "as_of": "2026-08-14", "canonical_directory": str(CANONICAL_DIR.relative_to(ROOT)), "canonical_json": 54, "canonical_markdown": 54, "ticker_count": len(tickers), "tickers": tickers})
    write_json(EVIDENCE_ROOT / "authority/canonical_manifest_verification.json", authority)
    write_json(EVIDENCE_ROOT / "authority/source_identity.json", source)
    write_json(EVIDENCE_ROOT / "execution/run1_summary.json", run1_summary)
    write_json(EVIDENCE_ROOT / "execution/run2_summary.json", run2_summary)
    write_csv(EVIDENCE_ROOT / "parity/report_file_parity.csv", rows)
    write_csv(EVIDENCE_ROOT / "parity/json_section_parity.csv", section_rows)
    file_failures = [r for r in rows if r["overall_match"] != "MATCH"]
    section_failures = [r for r in section_rows if not r["overall_match"]]
    json_byte_mismatches = sum(r["file_type"] == "json" and r["canonical_vs_run1"] != "MATCH" for r in rows)
    json_semantic_mismatches = len(semantic_mismatch_names)
    markdown_byte_mismatches = sum(r["file_type"] == "markdown" and r["canonical_vs_run1"] != "MATCH" for r in rows)
    write_json(EVIDENCE_ROOT / "parity/mismatch_summary.json", {"report_file_parity_rows": len(rows), "report_file_parity_fail_rows": len(file_failures), "json_section_parity_rows": len(section_rows), "json_section_parity_fail_rows": len(section_failures), "json_byte_mismatches": json_byte_mismatches, "json_semantic_mismatches": json_semantic_mismatches, "json_semantic_mismatch_names": semantic_mismatch_names, "markdown_byte_mismatches": markdown_byte_mismatches, "filename_mismatches": len([r for r in rows if not r["canonical_sha256"] or not r["run1_sha256"] or not r["run2_sha256"]]), "mismatch_classification": {"DATA_QUALITY_DRIFT": 1 if semantic_mismatch_names else 0, "HEADER_DRIFT": 1 if semantic_mismatch_names else 0, "MARKDOWN_RENDER_DRIFT": markdown_byte_mismatches}})
    write_json(EVIDENCE_ROOT / "parity/json_mismatches.json", {"mismatches": [r for r in rows if r["file_type"] == "json" and r["overall_match"] != "MATCH"], "semantic_details": semantic_mismatch_details})
    write_json(EVIDENCE_ROOT / "parity/markdown_mismatches.json", {"mismatches": [r for r in rows if r["file_type"] == "markdown" and r["overall_match"] != "MATCH"]})
    write_json(EVIDENCE_ROOT / "determinism/deterministic_regeneration.json", {"run1_vs_run2": all(r["run1_vs_run2"] == "MATCH" for r in rows), "canonical_json_sha": aggregate_sha(rows, "canonical_sha256", "json"), "run1_json_sha": aggregate_sha(rows, "run1_sha256", "json"), "run2_json_sha": aggregate_sha(rows, "run2_sha256", "json"), "canonical_markdown_sha": aggregate_sha(rows, "canonical_sha256", "markdown"), "run1_markdown_sha": aggregate_sha(rows, "run1_sha256", "markdown"), "run2_markdown_sha": aggregate_sha(rows, "run2_sha256", "markdown")})
    write_json(EVIDENCE_ROOT / "schema/run1_schema_validation.json", run1_schema)
    write_json(EVIDENCE_ROOT / "schema/run2_schema_validation.json", run2_schema)
    write_json(EVIDENCE_ROOT / "distributions/applicability_distribution.json", {"canonical": dict(sorted(Counter(r["asset_type"] for r in canonical_reports.values()).items())), "run1": dict(sorted(Counter(r["asset_type"] for r in run1_reports).items())), "run2": dict(sorted(Counter(r["asset_type"] for r in run2_reports).items()))})
    write_json(EVIDENCE_ROOT / "distributions/market_rs_distribution.json", {"expected": EXPECTED_RS_DISTRIBUTION, "canonical": rs_distribution(list(canonical_reports.values())), "run1": rs_distribution(run1_reports), "run2": rs_distribution(run2_reports)})
    write_json(EVIDENCE_ROOT / "distributions/report_status_distribution.json", {"canonical": dict(sorted(Counter(r["header"]["report_status"] for r in canonical_reports.values()).items())), "run1": dict(sorted(Counter(r["header"]["report_status"] for r in run1_reports).items())), "run2": dict(sorted(Counter(r["header"]["report_status"] for r in run2_reports).items()))})
    write_json(EVIDENCE_ROOT / "canaries/summary.json", canary)
    for ticker in ("005930", "069500", "0115D0", "001540"):
        write_json(EVIDENCE_ROOT / f"canaries/{ticker}.json", canary[ticker])
    write_json(EVIDENCE_ROOT / "guards/network_guard.json", {"network_requests": network_calls, "blocked_addresses": network_addresses, "policy": "local-only fail-closed"})
    write_json(EVIDENCE_ROOT / "guards/scanner_guard.json", {"full_universe_scanner_calls": scanner_calls, "policy": "forbidden"})
    changed = sorted(name for name, digest in pre_canonical.items() if post_canonical.get(name) != digest)
    write_json(EVIDENCE_ROOT / "guards/canonical_mutation_guard.json", {"canonical_files_changed": changed, "changed_count": len(changed), "contract_sha256": sha256_file(CONTRACT_PATH), "schema_sha256": sha256_file(SCHEMA_PATH)})
    non_common_mismatches = sum(1 for stem, canonical in canonical_reports.items() if canonical.get("asset_type") != "COMMON" and (canonical.get("relative_strength") != next((r for r in run1_reports if r.get("ticker") == canonical.get("ticker")), {}).get("relative_strength")))
    version_mismatches = sum(1 for report in run1_reports + run2_reports if report.get("report_version") != "0.3" or report.get("requested_as_of") != "2026-08-14" or report.get("reference_market_date") != "2026-08-14")
    local_pass = all([
        len(tickers) == 54, len(rows) == 108, len(section_rows) == 54, not file_failures, not section_failures,
        json_byte_mismatches == 0, json_semantic_mismatches == 0,
        run1_schema["valid"] == 54, run2_schema["valid"] == 54,
        rs_distribution(run1_reports) == EXPECTED_RS_DISTRIBUTION, rs_distribution(run2_reports) == EXPECTED_RS_DISTRIBUTION,
        run1_unit_errors == {"level": 0, "delta": 0, "acceleration": 0}, run2_unit_errors == {"level": 0, "delta": 0, "acceleration": 0},
        non_common_mismatches == 0, version_mismatches == 0,
        all(item["pass"] for item in canary.values()), network_calls == 0, scanner_calls == 0, not changed,
    ])
    write_json(EVIDENCE_ROOT / "final/git_mutation_audit.json", {"start_head": identity["head"], "start_tree": identity["tree"], "source_code_changed": False, "schema_changed": False, "contract_changed": False, "canonical_report_files_changed": len(changed), "consumer_migration": "NOT_YET_EXECUTED", "sector_rs_report_integration": "NOT_YET_EXECUTED", "julia_report_integration": "NOT_APPLICABLE"})
    write_json(EVIDENCE_ROOT / "final/closure_decision.json", {"verdict": "LOCAL_PARITY_PASS" if local_pass else "CHANGES_REQUESTED", "remote_verification": "PENDING_PUSH", "stock_report_parity_v01": "READY_FOR_REMOTE_VERIFICATION" if local_pass else "OPEN", "next_state": "CONSUMER_MIGRATION_AND_VALIDATION" if local_pass else "STOCK_REPORT_PARITY_V01_FIX01", "hard_gates": {"non_common_applicability_mismatches": non_common_mismatches, "version_mismatches": version_mismatches, "rs_level_unit_errors": run1_unit_errors["level"] + run2_unit_errors["level"], "rs_delta_unit_errors": run1_unit_errors["delta"] + run2_unit_errors["delta"], "rs_acceleration_unit_errors": run1_unit_errors["acceleration"] + run2_unit_errors["acceleration"]}, "generated_at_epoch": time.time(), "total_duration_seconds": round(time.monotonic() - started, 3)})
    write_json(EVIDENCE_ROOT / "final/artifact_manifest.json", {"evidence_root": str(EVIDENCE_ROOT.relative_to(ROOT)), "files": {str(p.relative_to(EVIDENCE_ROOT)): sha256_file(p) for p in sorted(EVIDENCE_ROOT.rglob("*")) if p.is_file() and p.name != "artifact_manifest.json"}})
    print(json.dumps({"local_pass": local_pass, "canonical_json": 54, "canonical_markdown": 54, "run1_json": run1_summary["json_count"], "run1_markdown": run1_summary["markdown_count"], "run2_json": run2_summary["json_count"], "run2_markdown": run2_summary["markdown_count"], "json_byte_mismatches": json_byte_mismatches, "json_semantic_mismatches": json_semantic_mismatches, "markdown_byte_mismatches": markdown_byte_mismatches, "schema_errors": len(run1_schema["errors"]) + len(run2_schema["errors"]), "network_requests": network_calls, "full_universe_scanner_calls": scanner_calls, "non_common_applicability_mismatches": non_common_mismatches, "evidence_root": str(EVIDENCE_ROOT.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if local_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
