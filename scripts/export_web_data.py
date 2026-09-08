#!/usr/bin/env python3
"""Export a compact, public-safe Data Health artifact for the static web site.

This exporter is intentionally local-only.  It reads existing repository
authorities and never imports or calls an external data provider.  The browser
consumes only the JSON written under ``web/data``; it never sees the production
artifact directories used here.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import tempfile
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "web/data"
SCAN_SUMMARY_PATH = ROOT / (
    "artifacts/patterns/pattern_a/production/scanner/"
    "pattern_a_universe_scan_20260904_summary.json"
)
MARKET_AUTHORITY_MANIFEST_PATH = ROOT / "data/market/rolling_authority/manifest.json"
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.parquet"
FUNDAMENTALS_ROOT = ROOT / "artifacts/fundamentals/production/20260904"
FUNDAMENTALS_TICKERS_DIR = FUNDAMENTALS_ROOT / "tickers"
FUNDAMENTALS_CHECKPOINT_PATH = FUNDAMENTALS_ROOT / "daily_quota_checkpoint.json"
STOCK_REPORTS_DIR = ROOT / "artifacts/reporting/stock_reports/20260904"

VALID_STATUSES = {
    "NORMAL",
    "UPDATING",
    "WAITING",
    "CHECK_REQUIRED",
    "UNKNOWN",
}
VALID_TERMINAL_STATUSES = {
    "PASS",
    "FILTERED_ANNUAL_REVENUE",
    "FILTERED_QUARTERLY_REVENUE",
    "FILTERED_OPERATING_LOSS",
    "FILTERED_NET_LOSS",
    "DATA_UNAVAILABLE",
    "NOT_APPLICABLE",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON authority must be an object: {path}")
    return value


def _relative(path: Path) -> str:
    """Return a repository-relative logical path, never a machine path."""

    return path.relative_to(ROOT).as_posix()


def _source(path: Path, *, as_of: str | None = None, generated_at: str | None = None) -> dict[str, str]:
    value = {"path": _relative(path)}
    if as_of:
        value["as_of"] = as_of
    if generated_at:
        value["generated_at"] = generated_at
    return value


def _load_as_of() -> tuple[str, str]:
    """Read the exact requested/reference date from the scanner authority."""

    summary = _read_json(SCAN_SUMMARY_PATH)
    requested = str(summary.get("requested_as_of") or "")[:10]
    reference = str(summary.get("reference_market_date") or "")[:10]
    if not requested or requested != reference:
        raise ValueError("scanner authority does not expose one exact as_of date")
    return requested, reference


def _load_universe(requested_as_of: str) -> tuple[set[str], str, Counter[str]]:
    """Load the same Strict PIT universe authority used by F7.

    The metadata resolver is a local reader for the canonical parquet/CSV
    authority.  It has no network path.  The latest row snapshot not after the
    requested date is selected, then duplicate tickers fail closed.
    """

    if not METADATA_PATH.exists():
        raise FileNotFoundError(f"instrument metadata authority missing: {METADATA_PATH}")

    import sys

    src_dir = str(ROOT / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

    frame = InstrumentMetadataResolver.load_master_dataframe(ROOT).copy()
    required = {"ticker", "effective_date"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("instrument metadata authority is empty or incomplete")

    import pandas as pd

    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="coerce")
    eligible = frame[
        frame["effective_date"].notna()
        & (frame["effective_date"] <= pd.Timestamp(requested_as_of))
    ]
    if eligible.empty:
        raise ValueError("instrument metadata has no PIT-eligible rows")
    snapshot_date = str(eligible["effective_date"].max().date())
    current = eligible[eligible["effective_date"] == pd.Timestamp(snapshot_date)].copy()
    current = current.sort_values("ticker")
    if current["ticker"].duplicated().any():
        raise ValueError("instrument metadata authority contains duplicate PIT tickers")

    tickers = set(current["ticker"].tolist())
    asset_counts = Counter(
        str(value or "UNKNOWN").strip().upper()
        for value in current.get("asset_type", pd.Series(index=current.index, dtype="object"))
    )
    return tickers, snapshot_date, asset_counts


def _valid_fundamentals_outputs(
    expected_tickers: Iterable[str],
    requested_as_of: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Recount valid F7 outputs without opening raw filings or cache data."""

    expected = set(expected_tickers)
    valid: dict[str, dict[str, Any]] = {}
    terminal_counts: Counter[str] = Counter()
    data_counts: Counter[str] = Counter()
    invalid_count = 0
    outside_universe_count = 0
    duplicate_payload_count = 0

    if not FUNDAMENTALS_TICKERS_DIR.exists():
        raise FileNotFoundError(f"F7 production output directory missing: {FUNDAMENTALS_TICKERS_DIR}")

    for path in sorted(FUNDAMENTALS_TICKERS_DIR.glob("*.json")):
        try:
            value = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            invalid_count += 1
            continue

        ticker = str(value.get("ticker") or "").strip().upper()
        terminal_status = str(value.get("terminal_status") or "")
        if (
            ticker != path.stem.upper()
            or value.get("requested_as_of") != requested_as_of
            or terminal_status not in VALID_TERMINAL_STATUSES
        ):
            invalid_count += 1
            continue
        if ticker not in expected:
            outside_universe_count += 1
            continue
        if ticker in valid:
            duplicate_payload_count += 1
            continue

        valid[ticker] = value
        terminal_counts[terminal_status] += 1
        data_counts[str(value.get("data_status") or "DATA_UNAVAILABLE")] += 1

    counts = {
        "terminal": dict(sorted(terminal_counts.items())),
        "data": dict(sorted(data_counts.items())),
        "invalid_output_count": invalid_count,
        "outside_universe_count": outside_universe_count,
        "duplicate_payload_count": duplicate_payload_count,
    }
    return valid, counts


def _build_fundamentals(requested_as_of: str, universe_tickers: set[str]) -> dict[str, Any]:
    valid, counts = _valid_fundamentals_outputs(universe_tickers, requested_as_of)
    total = len(universe_tickers)
    completed = len(valid)
    remaining = total - completed
    percentage = round((completed / total) * 100, 1) if total else 0.0

    checkpoint = _read_json(FUNDAMENTALS_CHECKPOINT_PATH)
    run_status = str(checkpoint.get("status") or "UNKNOWN")
    output_integrity_ok = not any(
        counts[key] for key in (
            "invalid_output_count",
            "outside_universe_count",
            "duplicate_payload_count",
        )
    )
    if not output_integrity_ok:
        status = "CHECK_REQUIRED"
    elif completed < total:
        status = "UPDATING"
    else:
        status = "NORMAL"

    return {
        "status": status,
        "run_status": run_status,
        "requested_as_of": requested_as_of,
        "completed": completed,
        "total": total,
        "remaining": remaining,
        "percentage": percentage,
        "terminal_status_counts": counts["terminal"],
        "data_status_counts": counts["data"],
        "output_integrity": {
            "valid_output_count": completed,
            "invalid_output_count": counts["invalid_output_count"],
            "outside_universe_count": counts["outside_universe_count"],
            "duplicate_payload_count": counts["duplicate_payload_count"],
        },
        "source": {
            "production_directory": _relative(FUNDAMENTALS_ROOT),
            "checkpoint": _source(FUNDAMENTALS_CHECKPOINT_PATH, as_of=requested_as_of),
            "outputs": _source(FUNDAMENTALS_TICKERS_DIR, as_of=requested_as_of),
        },
    }


def _build_market_data(requested_as_of: str) -> dict[str, Any]:
    manifest = _read_json(MARKET_AUTHORITY_MANIFEST_PATH)
    latest = str(manifest.get("certified_through") or "")[:10]
    frontier = str(manifest.get("merged_calendar_frontier") or "")[:10]
    if not latest or latest != frontier:
        raise ValueError("rolling market authority has no single certified frontier")
    status = "NORMAL" if latest == requested_as_of else "CHECK_REQUIRED"
    return {
        "status": status,
        "latest_trading_date": latest,
        "certified_through": latest,
        "authority_version": manifest.get("authority_version"),
        "source": _source(
            MARKET_AUTHORITY_MANIFEST_PATH,
            as_of=latest,
            generated_at=str(manifest.get("generated_at") or "") or None,
        ),
    }


def _build_universe(snapshot_date: str, tickers: set[str], asset_counts: Counter[str]) -> dict[str, Any]:
    return {
        "status": "NORMAL",
        "count": len(tickers),
        "snapshot_date": snapshot_date,
        "asset_type_counts": dict(sorted(asset_counts.items())),
        "source": _source(METADATA_PATH, as_of=snapshot_date),
    }


def _count_stock_report_artifacts() -> int:
    if not STOCK_REPORTS_DIR.exists():
        return 0
    return sum(1 for path in STOCK_REPORTS_DIR.glob("*.md") if path.is_file())


def _build_downstream_section(
    name: str,
    fundamentals_status: str,
    *,
    existing_artifact_count: int | None = None,
) -> dict[str, Any]:
    if fundamentals_status in {"UPDATING", "CHECK_REQUIRED"}:
        status = "WAITING" if fundamentals_status == "UPDATING" else "CHECK_REQUIRED"
        reason = "Fundamentals production coverage is not complete."
    elif fundamentals_status == "NORMAL":
        status = "UNKNOWN"
        reason = "No WEB-01 readiness authority confirms downstream completion."
    else:
        status = "UNKNOWN"
        reason = "Fundamentals readiness is unknown."

    value: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "source": _source(FUNDAMENTALS_CHECKPOINT_PATH),
    }
    if existing_artifact_count is not None:
        value["existing_artifact_count"] = existing_artifact_count
        value["artifact_source"] = _source(STOCK_REPORTS_DIR, as_of="2026-09-04")
    return value


def _overall_status(sections: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = {str(section.get("status")) for section in sections.values()}
    if "CHECK_REQUIRED" in statuses:
        return "CHECK_REQUIRED"
    if "UPDATING" in statuses:
        return "UPDATING"
    if "WAITING" in statuses:
        return "WAITING"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "NORMAL"


def _assert_public_payload(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden_fragments = (
        "/Users/",
        "/private/",
        ".env",
        "OPENDART_API_KEY",
        "crtfc_key",
        "api_key",
        "Authorization",
    )
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"public health payload contains forbidden fragment: {fragment}")


def build_health(repo_root: Path = ROOT, *, generated_at: str | None = None) -> dict[str, Any]:
    """Build the public-safe health document from local authorities."""

    if repo_root != ROOT:
        raise ValueError("WEB-01 exporter is bound to the repository root")
    requested_as_of, _ = _load_as_of()
    universe_tickers, snapshot_date, asset_counts = _load_universe(requested_as_of)
    fundamentals = _build_fundamentals(requested_as_of, universe_tickers)
    market_data = _build_market_data(requested_as_of)
    stock_report_count = _count_stock_report_artifacts()
    stock_reports = _build_downstream_section(
        "stock_reports",
        fundamentals["status"],
        existing_artifact_count=stock_report_count,
    )
    analysis = _build_downstream_section("analysis", fundamentals["status"])
    backtest = _build_downstream_section("backtest", fundamentals["status"])
    sections = {
        "market_data": market_data,
        "universe": _build_universe(snapshot_date, universe_tickers, asset_counts),
        "fundamentals": fundamentals,
        "stock_reports": stock_reports,
        "analysis": analysis,
        "backtest": backtest,
    }
    status_sections = {
        key: value for key, value in sections.items() if isinstance(value, Mapping)
    }
    health = {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall_status": _overall_status(status_sections),
        **sections,
    }
    if health["overall_status"] not in VALID_STATUSES:
        raise ValueError("invalid overall status")
    _assert_public_payload(health)
    return health


def _write_checked(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preflight probe: confirm the target directory is writable before the
    # actual artifact replacement.  The probe contains no project data.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".health-write-probe-", delete=False
    ) as probe:
        probe_path = Path(probe.name)
        probe.write("probe")
    probe_path.unlink(missing_ok=True)

    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".health-export-", delete=False
    ) as temp:
        temp_path = Path(temp.name)
        temp.write(encoded)
        temp.flush()
        os.fsync(temp.fileno())
    os.replace(temp_path, path)

    readback = path.read_text(encoding="utf-8")
    if readback != encoded or json.loads(readback) != dict(payload):
        raise ValueError("health artifact readback verification failed")


def export_health(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    health = build_health()
    output_path = output_dir / "health.json"
    _write_checked(output_path, health)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory receiving health.json (default: web/data)",
    )
    args = parser.parse_args()
    output_path = export_health(args.output)
    health = json.loads(output_path.read_text(encoding="utf-8"))
    fundamentals = health["fundamentals"]
    print(
        "exported health.json: "
        f"overall={health['overall_status']} "
        f"fundamentals={fundamentals['completed']}/{fundamentals['total']} "
        f"remaining={fundamentals['remaining']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
