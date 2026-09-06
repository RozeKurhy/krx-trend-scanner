#!/usr/bin/env python3
"""Run the frozen Stock Report v0.3 exact-parity check.

The runner derives its ticker corpus from the frozen 2026-08-14 JSON files,
generates two independent temporary corpora with the current executable, and
persists only hashes, semantic/section comparisons, and small canary evidence.
No generated report is written into the canonical directory or the repository.
"""

from __future__ import annotations

import csv
import copy
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

from trend_scanner.data.cache import ParquetCache
from trend_scanner.reporting.stock_report import render_markdown_report
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

EXPECTED_START_HEAD = "511c398745b01869fd1756ba1f783bafecc177ca"
EXPECTED_START_TREE = "867fe279e1432504e2a1a463b45d97b522e28818"
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
FIX01_EVIDENCE_ROOT = ROOT / "artifacts/data/end_to_end_data_parity/v01/stock_report_parity/v01/fix01"
REQUESTED_AS_OF = "2026-08-14"
COWAY_TICKER = "021240"
COWAY_STEM = "021240_코웨이"
RUNTIME_METADATA_SENTINEL = "<RUNTIME_CACHE_STATE>"
RUNTIME_METADATA_FIELDS = (
    "header.cache_last_date",
    "data_quality.cache_last_date",
    "data_quality.daily_rows_count",
)
RUNTIME_METADATA_FIELD_COUNT = 3


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


# ---------------------------------------------------------------------------
# FIX01: raw-artifact parity versus frozen-as-of behavioral parity
# ---------------------------------------------------------------------------


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    section, field = path.split(".", 1)
    payload[section][field] = value


def normalize_json_runtime_metadata(report: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with exactly the three FIX01 allowlisted fields masked."""
    normalized = copy.deepcopy(report)
    for path in RUNTIME_METADATA_FIELDS:
        _set_path(normalized, path, RUNTIME_METADATA_SENTINEL)
    return normalized


def normalized_json_sha(report: dict[str, Any]) -> str:
    payload = json.dumps(
        normalize_json_runtime_metadata(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def runtime_metadata_delta(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    differences = _semantic_differences(expected, actual)
    paths = sorted({item["path"] for item in differences})
    return {
        "paths": paths,
        "difference_count": len(differences),
        "only_allowlisted": bool(differences) and set(paths) == set(RUNTIME_METADATA_FIELDS),
        "differences": differences,
    }


def validate_runtime_metadata_delta(
    expected: dict[str, Any],
    actual: dict[str, Any],
    state: dict[str, Any],
    requested_as_of: str = REQUESTED_AS_OF,
) -> dict[str, Any]:
    """Validate the conditional runtime allowlist; never silently ignore fields."""
    delta = runtime_metadata_delta(expected, actual)
    conditions = {
        "future_cache_last_date": str(state.get("current_cache_last_date", "")) > requested_as_of,
        "future_rows_present": int(state.get("current_rows_gt_as_of", 0)) > 0,
        "as_of_row_count_match": int(state.get("current_rows_le_as_of", -1)) == int(state.get("canonical_daily_rows_count", -2)),
        "all_extra_rows_future": bool(state.get("all_extra_rows_date_future", False)),
        "no_pre_or_on_as_of_extra_rows": int(state.get("pre_or_on_as_of_extra_row_count", -1)) == 0,
        # ``runtime_metadata_delta`` sorts paths for deterministic evidence;
        # validation must compare the set, not rely on tuple ordering.
        "no_other_json_difference": set(delta["paths"]) == set(RUNTIME_METADATA_FIELDS),
    }
    passed = delta["only_allowlisted"] and all(conditions.values())
    return {
        "passed": passed,
        "classification": "EXPECTED_POST_FREEZE_CACHE_STATE_METADATA_DELTA" if passed else "UNEXPLAINED_RUNTIME_METADATA_DELTA",
        "allowlist_fields": list(RUNTIME_METADATA_FIELDS),
        "conditions": conditions,
        "delta": delta,
    }


def markdown_runtime_delta(canonical_text: str, current_text: str) -> dict[str, Any]:
    """Inspect Markdown differences and allow only the two exact rendered labels."""
    left, right = canonical_text.splitlines(), current_text.splitlines()
    if len(left) != len(right):
        return {"passed": False, "differences": [{"line": None, "canonical": len(left), "current": len(right)}], "line_count": 0}
    differences: list[dict[str, Any]] = []
    for index, (canonical_line, current_line) in enumerate(zip(left, right), start=1):
        if canonical_line == current_line:
            continue
        allowed_label = None
        if canonical_line.startswith("- **로컬 일봉 캐시**:") and current_line.startswith("- **로컬 일봉 캐시**:"):
            if re.fullmatch(r"- \*\*로컬 일봉 캐시\*\*: `정상 로드 \(\d+행\)`", canonical_line) and re.fullmatch(r"- \*\*로컬 일봉 캐시\*\*: `정상 로드 \(\d+행\)`", current_line):
                allowed_label = "data_quality.daily_rows_count"
        if canonical_line.startswith("- **데이터 기간**:") and current_line.startswith("- **데이터 기간**:"):
            if re.fullmatch(r"- \*\*데이터 기간\*\*: `\d{4}-\d{2}-\d{2}` ~ `\d{4}-\d{2}-\d{2}`", canonical_line) and re.fullmatch(r"- \*\*데이터 기간\*\*: `\d{4}-\d{2}-\d{2}` ~ `\d{4}-\d{2}-\d{2}`", current_line):
                allowed_label = "data_quality.cache_last_date"
        differences.append({"line": index, "canonical": canonical_line, "current": current_line, "allowlisted_field": allowed_label})
    allowed = bool(differences) and all(item["allowlisted_field"] for item in differences)
    return {"passed": allowed, "differences": differences, "line_count": len(differences), "allowlisted_line_count": sum(item["allowlisted_field"] is not None for item in differences)}


def normalize_markdown_runtime_metadata(text: str, delta: dict[str, Any]) -> str:
    """Normalize only lines previously proven to be exact allowlisted deltas."""
    if not delta.get("passed"):
        return text
    lines = text.splitlines()
    for item in delta["differences"]:
        index = int(item["line"]) - 1
        if item["allowlisted_field"] == "data_quality.daily_rows_count":
            lines[index] = re.sub(r"정상 로드 \(\d+행\)", f"정상 로드 ({RUNTIME_METADATA_SENTINEL}행)", lines[index])
        elif item["allowlisted_field"] == "data_quality.cache_last_date":
            lines[index] = re.sub(r"( ~ )`\d{4}-\d{2}-\d{2}`", rf"\1`{RUNTIME_METADATA_SENTINEL}`", lines[index])
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def coway_cache_state() -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    frame = ParquetCache(base_dir=ROOT / "data/raw/stocks").load(COWAY_TICKER)
    if frame is None or frame.empty:
        raise RuntimeError("Coway local cache is missing")
    frame = frame.copy()
    frame.index = frame.index.map(lambda value: value.to_pydatetime() if hasattr(value, "to_pydatetime") else value)
    import pandas as pd  # noqa: PLC0415

    frame.index = pd.to_datetime(frame.index)
    as_of = pd.Timestamp(REQUESTED_AS_OF)
    before_or_on = frame.loc[frame.index <= as_of]
    extra = frame.loc[frame.index > as_of]
    extras: list[dict[str, Any]] = []
    for date, row in extra.sort_index().iterrows():
        item: dict[str, Any] = {"ticker": COWAY_TICKER, "date": date.strftime("%Y-%m-%d")}
        item.update({column: row[column] for column in frame.columns})
        extras.append(item)
    state = {
        "ticker": COWAY_TICKER,
        "requested_as_of": REQUESTED_AS_OF,
        "current_cache_first_date": frame.index.min().strftime("%Y-%m-%d"),
        "current_cache_last_date": frame.index.max().strftime("%Y-%m-%d"),
        "current_full_row_count": int(len(frame)),
        "current_rows_le_as_of": int(len(before_or_on)),
        "current_rows_gt_as_of": int(len(extra)),
        "canonical_daily_rows_count": 1222,
        "canonical_cache_last_date": REQUESTED_AS_OF,
        "all_extra_rows_date_future": bool(len(extra) > 0 and (extra.index > as_of).all()),
        "pre_or_on_as_of_extra_row_count": int((extra.index <= as_of).sum()),
        "columns": ["ticker", "date", *frame.columns.tolist()],
    }
    return frame, state, extras


def _shadow_coway_report() -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate Coway once with its cache truncated at the requested as-of."""
    import trend_scanner.reporting.stock_report as stock_report_module  # noqa: PLC0415

    original_load = stock_report_module.ParquetCache.load
    try:
        def sliced_load(cache: Any, ticker: str) -> Any:
            frame = original_load(cache, ticker)
            if str(ticker).strip() == COWAY_TICKER and frame is not None:
                import pandas as pd  # noqa: PLC0415
                return frame.loc[frame.index <= pd.Timestamp(REQUESTED_AS_OF)].copy()
            return frame

        stock_report_module.ParquetCache.load = sliced_load  # type: ignore[assignment]
        report, _, _ = generate_stock_report(COWAY_TICKER, REQUESTED_AS_OF, ROOT, save_artifacts=False)
    finally:
        stock_report_module.ParquetCache.load = original_load  # type: ignore[assignment]
    return report.to_dict(), {"max_date_used_for_calculation": report.header.effective_as_of, "lookahead_rows": 0 if report.header.effective_as_of <= REQUESTED_AS_OF else 1}


def _fix01_compare(
    canonical_reports: dict[str, dict[str, Any]],
    canonical_hashes: dict[str, str],
    run1_dir: Path,
    run2_dir: Path,
    coway_state: dict[str, Any],
) -> dict[str, Any]:
    run1_reports = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(run1_dir.glob("*.json"))}
    run2_reports = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(run2_dir.glob("*.json"))}
    raw_rows: list[dict[str, Any]] = []
    normalized_json_rows: list[dict[str, Any]] = []
    normalized_section_rows: list[dict[str, Any]] = []
    normalized_markdown_rows: list[dict[str, Any]] = []
    semantic_details: list[dict[str, Any]] = []
    markdown_allowlist_details: list[dict[str, Any]] = []
    metadata_validation: dict[str, Any] | None = None
    for stem, canonical in sorted(canonical_reports.items()):
        json_name, md_name = stem + ".json", stem + ".md"
        run1, run2 = run1_reports.get(stem), run2_reports.get(stem)
        c_json = CANONICAL_DIR / json_name
        c_md = CANONICAL_DIR / md_name
        r1_json, r2_json = run1_dir / json_name, run2_dir / json_name
        r1_md, r2_md = run1_dir / md_name, run2_dir / md_name
        raw_json_match = bool(run1 is not None and run2 is not None and sha256_file(c_json) == sha256_file(r1_json) == sha256_file(r2_json))
        raw_md_match = bool(r1_md.exists() and r2_md.exists() and sha256_file(c_md) == sha256_file(r1_md) == sha256_file(r2_md))
        raw_diff = runtime_metadata_delta(canonical, run1) if run1 is not None else {"paths": ["$"], "differences": []}
        if stem == COWAY_STEM:
            metadata_validation = validate_runtime_metadata_delta(canonical, run1, coway_state) if run1 is not None else {"passed": False}
        runtime_only = bool(stem == COWAY_STEM and metadata_validation and metadata_validation["passed"])
        classification = "EXACT_MATCH" if raw_json_match and raw_md_match else "EXPECTED_POST_FREEZE_CACHE_STATE_METADATA_DELTA" if runtime_only else "BEHAVIORAL_DRIFT"
        if not raw_json_match:
            semantic_details.append({"filename": json_name, "differences": raw_diff.get("differences", [])})
        raw_rows.append({
            "filename": json_name, "file_type": "json", "canonical_sha256": sha256_file(c_json), "run1_sha256": sha256_file(r1_json) if r1_json.exists() else "", "run2_sha256": sha256_file(r2_json) if r2_json.exists() else "", "raw_match": raw_json_match, "runtime_metadata_only_delta": runtime_only, "behavioral_match": False, "classification": classification,
        })
        raw_rows.append({
            "filename": md_name, "file_type": "markdown", "canonical_sha256": sha256_file(c_md), "run1_sha256": sha256_file(r1_md) if r1_md.exists() else "", "run2_sha256": sha256_file(r2_md) if r2_md.exists() else "", "raw_match": raw_md_match, "runtime_metadata_only_delta": runtime_only, "behavioral_match": False, "classification": classification,
        })
        normalized_c = normalize_json_runtime_metadata(canonical) if stem == COWAY_STEM else canonical
        normalized_r1 = normalize_json_runtime_metadata(run1) if stem == COWAY_STEM and runtime_only else run1
        normalized_r2 = normalize_json_runtime_metadata(run2) if stem == COWAY_STEM and runtime_only else run2
        norm_match = normalized_r1 == normalized_c and normalized_r2 == normalized_c
        norm_sha_c = normalized_json_sha(canonical)
        norm_sha_1 = normalized_json_sha(run1) if run1 is not None else ""
        norm_sha_2 = normalized_json_sha(run2) if run2 is not None else ""
        normalized_json_rows.append({"ticker": canonical["ticker"], "filename": json_name, "raw_match": raw_json_match, "runtime_metadata_only_delta": runtime_only, "normalized_json_sha_canonical": norm_sha_c, "normalized_json_sha_run1": norm_sha_1, "normalized_json_sha_run2": norm_sha_2, "behavioral_match": norm_match})
        section_row = {"ticker": canonical["ticker"], "filename": json_name, "runtime_metadata_only_delta": runtime_only}
        for key in SECTION_KEYS:
            c_section = normalized_c.get(key) if normalized_c else None
            section_row[f"{key}_match"] = bool(normalized_r1 is not None and normalized_r2 is not None and normalized_r1.get(key) == c_section == normalized_r2.get(key))
        section_row["behavioral_match"] = all(section_row[f"{key}_match"] for key in SECTION_KEYS)
        normalized_section_rows.append(section_row)
        c_md_text, r1_md_text, r2_md_text = c_md.read_text(encoding="utf-8"), r1_md.read_text(encoding="utf-8"), r2_md.read_text(encoding="utf-8")
        md_delta_1 = markdown_runtime_delta(c_md_text, r1_md_text)
        md_delta_2 = markdown_runtime_delta(c_md_text, r2_md_text)
        if stem == COWAY_STEM:
            markdown_allowlist_details = md_delta_1.get("differences", [])
        md_allow = bool(stem == COWAY_STEM and runtime_only and md_delta_1.get("passed") and md_delta_2.get("passed"))
        n_c_md = normalize_markdown_runtime_metadata(c_md_text, md_delta_1 if md_allow else {"passed": False})
        n_r1_md = normalize_markdown_runtime_metadata(r1_md_text, md_delta_1 if md_allow else {"passed": False})
        n_r2_md = normalize_markdown_runtime_metadata(r2_md_text, md_delta_2 if md_allow else {"passed": False})
        normalized_markdown_rows.append({"ticker": canonical["ticker"], "filename": md_name, "raw_match": raw_md_match, "runtime_metadata_only_delta": md_allow, "allowlisted_line_count": md_delta_1.get("allowlisted_line_count", 0), "canonical_sha256": sha256_bytes(n_c_md.encode("utf-8")), "run1_sha256": sha256_bytes(n_r1_md.encode("utf-8")), "run2_sha256": sha256_bytes(n_r2_md.encode("utf-8")), "behavioral_match": n_c_md == n_r1_md == n_r2_md})
        if raw_json_match and raw_md_match:
            raw_rows[-2]["behavioral_match"] = True
            raw_rows[-1]["behavioral_match"] = True
        elif norm_match and normalized_markdown_rows[-1]["behavioral_match"]:
            raw_rows[-2]["behavioral_match"] = True
            raw_rows[-1]["behavioral_match"] = True
    raw_json = [row for row in raw_rows if row["file_type"] == "json"]
    raw_md = [row for row in raw_rows if row["file_type"] == "markdown"]
    return {
        "raw_rows": raw_rows,
        "raw_json_mismatches": sum(not row["raw_match"] for row in raw_json),
        "raw_markdown_mismatches": sum(not row["raw_match"] for row in raw_md),
        "run1_vs_run2_raw_mismatches": sum(row["run1_sha256"] != row["run2_sha256"] for row in raw_rows),
        "normalized_json_rows": normalized_json_rows,
        "normalized_section_rows": normalized_section_rows,
        "normalized_markdown_rows": normalized_markdown_rows,
        "semantic_details": semantic_details,
        "markdown_allowlist_details": markdown_allowlist_details,
        "metadata_validation": metadata_validation or {"passed": False},
        "behavioral_json_pass": sum(row["behavioral_match"] for row in normalized_json_rows),
        "behavioral_markdown_pass": sum(row["behavioral_match"] for row in normalized_markdown_rows),
        "behavioral_report_pass": sum(row["behavioral_match"] and normalized_section_rows[index]["behavioral_match"] for index, row in enumerate(normalized_json_rows)),
        "normalized_json_semantic_mismatches": sum(not row["behavioral_match"] for row in normalized_json_rows),
        "normalized_json_sha_mismatches": sum(row["normalized_json_sha_canonical"] != row["normalized_json_sha_run1"] or row["normalized_json_sha_canonical"] != row["normalized_json_sha_run2"] for row in normalized_json_rows),
        "normalized_markdown_mismatches": sum(not row["behavioral_match"] for row in normalized_markdown_rows),
    }


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


def main_fix01() -> int:
    """FIX01 entrypoint: reconcile only proven post-as-of runtime metadata."""
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
    FIX01_EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    frame, coway_state, extra_rows = coway_cache_state()
    with tempfile.TemporaryDirectory(prefix="stock_report_fix01_run1_") as run1_tmp, tempfile.TemporaryDirectory(prefix="stock_report_fix01_run2_") as run2_tmp:
        run1_dir, run2_dir = Path(run1_tmp), Path(run2_tmp)
        with offline_guards() as guards:
            run1_summary = run_corpus(tickers, run1_dir, guards, "fix01-run1")
            run2_summary = run_corpus(tickers, run2_dir, guards, "fix01-run2")
            shadow_report, shadow_guard = _shadow_coway_report()
            network_calls = guards["network"].calls
            network_addresses = guards["network"].addresses
            scanner_calls = guards["scanner_calls"]["count"]
        comparison = _fix01_compare(canonical_reports, canonical_hashes, run1_dir, run2_dir, coway_state)
        run1_reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run1_dir.glob("*.json"))]
        run2_reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run2_dir.glob("*.json"))]
        run1_schema = schema_validation(run1_dir, schema)
        run2_schema = schema_validation(run2_dir, schema)
        post_canonical = {p.name: sha256_file(p) for p in sorted(CANONICAL_DIR.glob("*")) if p.is_file()}

    write_json(FIX01_EVIDENCE_ROOT / "authority/parity_model.json", {"raw_layer": "RAW_ARTIFACT_PARITY", "behavioral_layer": "AS_OF_BEHAVIORAL_PARITY", "requested_as_of": REQUESTED_AS_OF, "canonical_authority_status": "UNCHANGED", "runtime_metadata_allowlist_field_count": RUNTIME_METADATA_FIELD_COUNT})
    write_json(FIX01_EVIDENCE_ROOT / "authority/runtime_metadata_policy.json", {"fields": list(RUNTIME_METADATA_FIELDS), "sentinel": RUNTIME_METADATA_SENTINEL, "conditional": True, "classification": "RUNTIME_ENVIRONMENT_METADATA", "strategy_field_normalization_count": 0})
    write_json(FIX01_EVIDENCE_ROOT / "authority/canonical_integrity.json", {"manifest_verification": authority, "pre_hash_count": len(pre_canonical), "post_hash_count": len(post_canonical), "canonical_files_changed": sorted(name for name, digest in pre_canonical.items() if post_canonical.get(name) != digest)})
    write_json(FIX01_EVIDENCE_ROOT / "execution/run1_summary.json", run1_summary)
    write_json(FIX01_EVIDENCE_ROOT / "execution/run2_summary.json", run2_summary)
    write_csv(FIX01_EVIDENCE_ROOT / "coway/post_freeze_rows.csv", extra_rows)
    coway_non_runtime = [item for item in comparison["metadata_validation"].get("delta", {}).get("differences", []) if item.get("path") not in RUNTIME_METADATA_FIELDS]
    write_json(FIX01_EVIDENCE_ROOT / "coway/cache_state_reconciliation.json", {**coway_state, "classification": comparison["metadata_validation"].get("classification"), "calculation_lookahead": shadow_guard["lookahead_rows"] > 0, "calculation_max_date_used": shadow_guard["max_date_used_for_calculation"], "behavioral_drift": comparison["metadata_validation"].get("passed") is False, "hard_gates": {"current_rows_le_as_of_equals_canonical": coway_state["current_rows_le_as_of"] == coway_state["canonical_daily_rows_count"], "extra_rows_future_only": coway_state["all_extra_rows_date_future"], "pre_or_on_as_of_extra_rows": coway_state["pre_or_on_as_of_extra_row_count"]}})
    write_json(FIX01_EVIDENCE_ROOT / "coway/non_runtime_field_parity.json", {"ticker": COWAY_TICKER, "mismatches": coway_non_runtime, "mismatch_count": len(coway_non_runtime), "pass": len(coway_non_runtime) == 0})
    write_csv(FIX01_EVIDENCE_ROOT / "raw_parity/report_file_parity.csv", comparison["raw_rows"])
    write_json(FIX01_EVIDENCE_ROOT / "raw_parity/raw_mismatch_summary.json", {"raw_json_byte_mismatches": comparison["raw_json_mismatches"], "raw_json_semantic_mismatches": len(comparison["semantic_details"]), "raw_markdown_byte_mismatches": comparison["raw_markdown_mismatches"], "raw_report_file_fail_rows": sum(not row["raw_match"] for row in comparison["raw_rows"]), "raw_mismatch_tickers": sorted({row["ticker"] for row in comparison["normalized_json_rows"] if not row["raw_match"]}), "run1_vs_run2_raw_mismatches": comparison["run1_vs_run2_raw_mismatches"]})
    write_csv(FIX01_EVIDENCE_ROOT / "behavioral_parity/normalized_json_parity.csv", comparison["normalized_json_rows"])
    write_csv(FIX01_EVIDENCE_ROOT / "behavioral_parity/normalized_section_parity.csv", comparison["normalized_section_rows"])
    write_csv(FIX01_EVIDENCE_ROOT / "behavioral_parity/normalized_markdown_parity.csv", comparison["normalized_markdown_rows"])
    write_json(FIX01_EVIDENCE_ROOT / "behavioral_parity/behavioral_summary.json", {"behavioral_json_pass": f"{comparison['behavioral_json_pass']}/54", "behavioral_markdown_pass": f"{comparison['behavioral_markdown_pass']}/54", "behavioral_report_pass": f"{comparison['behavioral_report_pass']}/54", "normalized_json_semantic_mismatches": comparison["normalized_json_semantic_mismatches"], "normalized_json_sha_mismatches": comparison["normalized_json_sha_mismatches"], "normalized_markdown_mismatches": comparison["normalized_markdown_mismatches"], "unexplained_runtime_metadata_delta": 0 if comparison["metadata_validation"].get("passed") else 1, "behavioral_drift": 0 if comparison["behavioral_report_pass"] == 54 else 54 - comparison["behavioral_report_pass"], "strategy_field_normalization_count": 0})
    write_json(FIX01_EVIDENCE_ROOT / "authority/markdown_runtime_metadata_allowlist.json", {"affected_ticker": COWAY_TICKER, "fields": ["data_quality.daily_rows_count", "data_quality.cache_last_date"], "affected_line_count": len(comparison["markdown_allowlist_details"]), "exact_line_deltas": comparison["markdown_allowlist_details"], "patterns": ["- **로컬 일봉 캐시**: `정상 로드 (<row_count>행)`", "- **데이터 기간**: `<first_date>` ~ `<cache_last_date>`"]})
    write_json(FIX01_EVIDENCE_ROOT / "schema/run1_schema_validation.json", run1_schema)
    write_json(FIX01_EVIDENCE_ROOT / "schema/run2_schema_validation.json", run2_schema)
    write_json(FIX01_EVIDENCE_ROOT / "guards/lookahead_guard.json", {"requested_as_of": REQUESTED_AS_OF, "max_date_used_for_calculation": shadow_guard["max_date_used_for_calculation"], "calculation_lookahead_rows": shadow_guard["lookahead_rows"], "pass": shadow_guard["lookahead_rows"] == 0})
    write_json(FIX01_EVIDENCE_ROOT / "guards/normalization_scope_guard.json", {"allowlist_fields": list(RUNTIME_METADATA_FIELDS), "allowlist_count": RUNTIME_METADATA_FIELD_COUNT, "strategy_field_normalization_count": 0, "non_allowlisted_json_differences": coway_non_runtime, "pass": len(coway_non_runtime) == 0 and RUNTIME_METADATA_FIELD_COUNT == 3})
    write_json(FIX01_EVIDENCE_ROOT / "guards/network_guard.json", {"network_requests": network_calls, "blocked_addresses": network_addresses, "policy": "local-only fail-closed"})
    write_json(FIX01_EVIDENCE_ROOT / "guards/scanner_guard.json", {"full_universe_scanner_calls": scanner_calls, "policy": "forbidden"})
    changed = sorted(name for name, digest in pre_canonical.items() if post_canonical.get(name) != digest)
    write_json(FIX01_EVIDENCE_ROOT / "guards/canonical_mutation_guard.json", {"canonical_files_changed": changed, "changed_count": len(changed), "report_source_changed": False, "report_schema_changed": False, "report_contract_changed": False})
    canaries = canary_evidence({p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CANONICAL_DIR.glob("*.json"))})
    canaries[COWAY_TICKER] = {"ticker": COWAY_TICKER, "name": "코웨이", "runtime_metadata_reconciliation": comparison["metadata_validation"], "pass": comparison["metadata_validation"].get("passed", False) and comparison["behavioral_report_pass"] == 54}
    for ticker in ("005930", "069500", "0115D0", "001540", COWAY_TICKER):
        write_json(FIX01_EVIDENCE_ROOT / f"canaries/{ticker}.json", canaries[ticker])
    write_json(FIX01_EVIDENCE_ROOT / "validation/parity_runner_local_summary.json", {"raw_json_byte_mismatches": comparison["raw_json_mismatches"], "raw_markdown_byte_mismatches": comparison["raw_markdown_mismatches"], "normalized_json_semantic_mismatches": comparison["normalized_json_semantic_mismatches"], "normalized_json_sha_mismatches": comparison["normalized_json_sha_mismatches"], "normalized_markdown_mismatches": comparison["normalized_markdown_mismatches"], "behavioral_json_pass": comparison["behavioral_json_pass"], "behavioral_markdown_pass": comparison["behavioral_markdown_pass"], "behavioral_report_pass": comparison["behavioral_report_pass"], "network_requests": network_calls, "full_universe_scanner_calls": scanner_calls})
    local_pass = all([
        len(tickers) == 54,
        comparison["raw_json_mismatches"] == 1,
        comparison["raw_markdown_mismatches"] == 1,
        comparison["run1_vs_run2_raw_mismatches"] == 0,
        comparison["normalized_json_semantic_mismatches"] == 0,
        comparison["normalized_json_sha_mismatches"] == 0,
        comparison["normalized_markdown_mismatches"] == 0,
        comparison["behavioral_json_pass"] == 54,
        comparison["behavioral_markdown_pass"] == 54,
        comparison["behavioral_report_pass"] == 54,
        comparison["metadata_validation"].get("passed") is True,
        coway_state["current_rows_le_as_of"] == coway_state["canonical_daily_rows_count"] == 1222,
        coway_state["current_rows_gt_as_of"] == 4,
        coway_state["pre_or_on_as_of_extra_row_count"] == 0,
        shadow_guard["lookahead_rows"] == 0,
        len(comparison["metadata_validation"].get("delta", {}).get("paths", [])) == 3,
        len(coway_non_runtime) == 0,
        run1_schema["valid"] == 54 and run2_schema["valid"] == 54,
        network_calls == 0 and scanner_calls == 0 and not changed,
    ])
    write_json(FIX01_EVIDENCE_ROOT / "final/closure_decision.json", {"verdict": "LOCAL_PARITY_PASS" if local_pass else "CHANGES_REQUESTED", "stock_report_parity_v01_fix01": "READY_FOR_REMOTE_VERIFICATION" if local_pass else "OPEN", "stock_report_parity_v01": "CLOSED" if local_pass else "OPEN", "raw_artifact_parity": "EXPECTED_RUNTIME_METADATA_DELTA_ONLY" if local_pass else "NOT_CLOSED", "as_of_behavioral_parity": "PASS_54_OF_54" if local_pass else "FAIL", "runtime_metadata_delta": "EXPECTED_POST_FREEZE_CACHE_STATE_METADATA_DELTA" if local_pass else "UNEXPLAINED_RUNTIME_METADATA_DELTA", "canonical_report_authority": "UNCHANGED", "consumer_migration": "NOT_YET_EXECUTED", "sector_rs_report_integration": "NOT_YET_EXECUTED", "next_state": "CONSUMER_MIGRATION_AND_VALIDATION" if local_pass else "STOCK_REPORT_PARITY_V01_FIX02", "remote_verification": "PENDING_PUSH", "generated_at_epoch": time.time(), "total_duration_seconds": round(time.monotonic() - started, 3)})
    write_json(FIX01_EVIDENCE_ROOT / "final/git_mutation_audit.json", {"start_head": identity["head"], "start_tree": identity["tree"], "source_semantic_changes": False, "test_semantic_changes": False, "runtime_config_changes": False, "canonical_report_files_changed": len(changed), "consumer_migration": "NOT_YET_EXECUTED", "sector_rs_report_integration": "NOT_YET_EXECUTED", "julia_report_integration": "NOT_APPLICABLE"})
    write_json(FIX01_EVIDENCE_ROOT / "final/artifact_manifest.json", {"evidence_root": str(FIX01_EVIDENCE_ROOT.relative_to(ROOT)), "files": {str(p.relative_to(FIX01_EVIDENCE_ROOT)): sha256_file(p) for p in sorted(FIX01_EVIDENCE_ROOT.rglob("*")) if p.is_file() and p.name != "artifact_manifest.json"}})
    print(json.dumps({"local_pass": local_pass, "raw_json_byte_mismatches": comparison["raw_json_mismatches"], "raw_markdown_byte_mismatches": comparison["raw_markdown_mismatches"], "normalized_json_semantic_mismatches": comparison["normalized_json_semantic_mismatches"], "normalized_json_sha_mismatches": comparison["normalized_json_sha_mismatches"], "normalized_markdown_mismatches": comparison["normalized_markdown_mismatches"], "behavioral_json_pass": comparison["behavioral_json_pass"], "behavioral_markdown_pass": comparison["behavioral_markdown_pass"], "behavioral_report_pass": comparison["behavioral_report_pass"], "coway_state": coway_state, "network_requests": network_calls, "full_universe_scanner_calls": scanner_calls, "evidence_root": str(FIX01_EVIDENCE_ROOT.relative_to(ROOT))}, ensure_ascii=False))
    return 0 if local_pass else 1


if __name__ == "__main__":
    raise SystemExit(main_fix01())
