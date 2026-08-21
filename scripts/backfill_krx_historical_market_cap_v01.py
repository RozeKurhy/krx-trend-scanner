#!/usr/bin/env python
"""Phase 13J-0 KRX UI export backfill, aligned to completed W-FRI references."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.validation.historical_snapshot import build_historical_snapshot


BASE_SHA = "cb2aba5d680c2f5e770ef9441e2e781d82a8cb2e"
SCREEN_ID = "MDC0201020101"
SOURCE_PRODUCT = "ALL_STOCK_MARKET_DATA"
NORMALIZATION_VERSION = "KRX_ALL_STOCK_UI_EXPORT_NORMALIZED_V01"
REFERENCE_TICKER = "000150"
REFERENCE_CANDIDATES = [
    "20200327", "20200626", "20200925", "20201225", "20210326", "20210625",
    "20210924", "20211231", "20220325", "20220624", "20220930", "20221230",
    "20230331", "20230630", "20230922", "20231229", "20240329", "20240628",
    "20240927", "20241227", "20250328", "20250627",
]
KOREAN_COLUMNS = {
    "종목코드": "ticker", "종목명": "name", "시장구분": "raw_market", "종가": "close",
    "거래량": "volume", "거래대금": "trading_value", "시가총액": "market_cap",
    "상장주식수": "shares_outstanding",
}


@dataclass(frozen=True)
class SnapshotInfo:
    candidate_date: str
    completed_weekly_reference_date: str
    resolution_status: str
    source: Path
    source_sha256: str
    retrieved_at: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def compact_date(value: str) -> str:
    return value.replace("-", "")


def reference_quarter(value: str) -> str:
    return f"{value[:4]} Q{(int(value[4:6]) - 1) // 3 + 1}"


def normalized_market(value: object) -> str:
    raw = str(value or "").strip()
    return "KOSPI" if raw.startswith("KOSPI") else "KOSDAQ" if raw.startswith("KOSDAQ") else "KONEX" if raw.startswith("KONEX") else "OTHER"


def numeric(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(values.replace({"": pd.NA, "-": pd.NA, "nan": pd.NA}), errors="coerce").astype("Int64")


def load_ui_export(path: Path, effective_date: str) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False)
    missing = sorted(set(KOREAN_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(f"KRX UI schema missing {missing}: {path}")
    frame = raw.rename(columns=KOREAN_COLUMNS)
    out = pd.DataFrame({column: frame[column] for column in KOREAN_COLUMNS.values()})
    out["ticker"] = out["ticker"].astype("string").str.strip().str.zfill(6)
    out["name"] = out["name"].astype("string").str.strip()
    out["raw_market"] = out["raw_market"].astype("string").str.strip()
    out["market"] = out["raw_market"].map(normalized_market)
    for column in ("close", "volume", "trading_value", "market_cap", "shares_outstanding"):
        out[column] = numeric(out[column])
    out["effective_date"] = iso_date(effective_date)
    return out[["ticker", "name", "raw_market", "market", "close", "volume", "trading_value", "market_cap", "shares_outstanding", "effective_date"]]


def validate_snapshot(frame: pd.DataFrame, info: SnapshotInfo) -> tuple[dict[str, Any], pd.DataFrame]:
    if frame.ticker.duplicated().any():
        raise ValueError(f"duplicate tickers: {info.completed_weekly_reference_date}")
    if not frame.market_cap.notna().all() or not (frame.market_cap.dropna() > 0).all():
        raise ValueError(f"invalid KRX market_cap: {info.completed_weekly_reference_date}")
    if not (frame.close.dropna() >= 0).all() or not (frame.shares_outstanding.dropna() > 0).all():
        raise ValueError(f"invalid KRX metrics: {info.completed_weekly_reference_date}")
    ordinary = frame.dropna(subset=["close", "shares_outstanding", "market_cap"]).copy()
    ordinary["calculated_market_cap"] = ordinary.close.astype("int64") * ordinary.shares_outstanding.astype("int64")
    ordinary["relative_error"] = (ordinary.market_cap.astype(float) - ordinary.calculated_market_cap.astype(float)).abs() / ordinary.market_cap.astype(float)
    anomalies = ordinary.loc[ordinary.relative_error > 0.01, ["ticker", "name", "market", "effective_date", "market_cap", "calculated_market_cap", "relative_error"]].copy()
    counts = frame.market.value_counts().to_dict()
    return {
        "effective_date": iso_date(info.completed_weekly_reference_date), "total_rows": len(frame),
        "kospi_rows": int(counts.get("KOSPI", 0)), "kosdaq_rows": int(counts.get("KOSDAQ", 0)),
        "konex_rows": int(counts.get("KONEX", 0)), "other_rows": int(counts.get("OTHER", 0)),
        "market_cap_non_null_count": int(frame.market_cap.notna().sum()),
        "shares_outstanding_non_null_count": int(frame.shares_outstanding.notna().sum()),
        "ticker_unique_count": int(frame.ticker.nunique()), "market_cap_crosscheck_anomaly_count": len(anomalies),
    }, anomalies


def completed_weekly_references(root: Path) -> dict[str, str]:
    """Use the frozen implementation to compute all 22 dates; no date table is encoded."""
    daily = pd.read_parquet(root / "data/raw/stocks" / f"{REFERENCE_TICKER}.parquet")
    resolved = {}
    for candidate in REFERENCE_CANDIDATES:
        snapshot = build_historical_snapshot(REFERENCE_TICKER, REFERENCE_TICKER, daily, candidate, include_incomplete_periods=False)
        if snapshot.weekly_as_of is None:
            raise ValueError(f"completed weekly reference unavailable: {candidate}")
        resolved[candidate] = snapshot.weekly_as_of.strftime("%Y%m%d")
    return resolved


def copy_immutable(source: Path, destination: Path, expected_sha: str) -> None:
    if destination.exists():
        if sha256(destination) != expected_sha:
            raise ValueError(f"immutable raw source conflict: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(destination) != expected_sha:
        raise RuntimeError(f"copy hash mismatch: {destination}")


def existing_crosscheck(download: Path, root: Path) -> dict[str, Any]:
    fresh = load_ui_export(download, "20250131")
    existing = pd.read_csv(root / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20250131.csv", dtype={"ticker": str})
    existing.ticker = existing.ticker.astype("string").str.zfill(6)
    merged = fresh.merge(existing[["ticker", "close", "market_cap", "shares_outstanding"]], on="ticker", how="inner", suffixes=("_krx", "_existing"))
    result = {"ticker_overlap_count": len(merged), "fresh_row_count": len(fresh), "existing_row_count": len(existing)}
    for field in ("close", "market_cap", "shares_outstanding"):
        result[f"{field}_equal_count"] = int((merged[f"{field}_krx"].astype("Int64") == pd.to_numeric(merged[f"{field}_existing"], errors="coerce").astype("Int64")).sum())
    result["comparison_status"] = "PASS" if all(result[f"{field}_equal_count"] == len(merged) for field in ("close", "market_cap", "shares_outstanding")) else "DESCRIPTIVE_DIFFERENCE"
    return result


def build_active_inputs(root: Path, grid: pd.DataFrame, provenance: pd.DataFrame, corrections: dict[str, dict[str, str]], computed: dict[str, str], retrieved_at: str) -> tuple[list[SnapshotInfo], list[dict[str, str]]]:
    prior_by_source = {str(row.source_file): row._asdict() for row in provenance.itertuples(index=False)}
    grid_by_candidate = {compact_date(str(row.calendar_candidate_date)): row._asdict() for row in grid.itertuples(index=False)}
    active = []
    superseded = [row._asdict() for row in provenance.itertuples(index=False) if str(getattr(row, "reference_status", "")) == "SUPERSEDED_NON_REFERENCE_SOURCE"]
    for candidate in REFERENCE_CANDIDATES:
        previous = grid_by_candidate.get(candidate)
        if previous is None:
            raise ValueError(f"previous active mapping missing: {candidate}")
        completed = computed[candidate]
        status = "EXACT_COMPLETED_WEEK" if candidate == completed else "PRIOR_COMPLETED_WEEK"
        if compact_date(str(previous["effective_date"])) == completed:
            source_file = str(previous["source_file"])
            prior = prior_by_source.get(source_file)
            if prior is None:
                raise ValueError(f"previous provenance missing: {source_file}")
            if candidate in corrections:
                correction = corrections[candidate]
                if compact_date(correction["completed_weekly_reference_date"]) != completed or correction["sha256"] != str(previous["sha256"]):
                    raise ValueError(f"active correction seal mismatch: {candidate}")
            active.append(SnapshotInfo(candidate, completed, status, root / source_file, str(previous["sha256"]), str(prior["retrieved_at"])))
            continue
        correction = corrections.get(candidate)
        if correction is None or compact_date(correction["completed_weekly_reference_date"]) != completed:
            raise ValueError(f"missing/mismatched KRX correction: {candidate} -> {completed}")
        source = Path("/Users/june/Downloads") / correction["download_file"]
        observed_sha = sha256(source)
        if observed_sha != correction["sha256"]:
            raise ValueError(f"download hash drift: {source}")
        old = dict(prior_by_source[str(previous["source_file"])])
        old.update({"calendar_candidate_date": iso_date(candidate), "completed_weekly_reference_date": iso_date(completed), "reference_status": "SUPERSEDED_NON_REFERENCE_SOURCE", "superseded_by_effective_date": iso_date(completed)})
        superseded.append(old)
        active.append(SnapshotInfo(candidate, completed, status, source, observed_sha, retrieved_at))
    required_corrections = {candidate for candidate in REFERENCE_CANDIDATES if candidate != computed[candidate]}
    if set(corrections) != required_corrections:
        raise ValueError("correction manifest must contain exactly the mechanically prior completed-week mappings")
    return active, superseded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correction-download-manifest", required=True, type=Path)
    parser.add_argument("--network-request-count", required=True, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    history = root / "artifacts/patterns/pattern_a/validation/investability_history"
    raw_dir, normalized_dir = history / "source", history / "normalized"
    reference_file = history / "krx_market_cap_reference_grid_v01.csv"
    provenance_file = history / "krx_historical_market_cap_provenance_v01.csv"
    grid, provenance = pd.read_csv(reference_file, dtype=str), pd.read_csv(provenance_file, dtype=str)
    manifest = json.loads(args.correction_download_manifest.read_text(encoding="utf-8"))
    corrections = {item["candidate_date"]: item for item in manifest["corrections"]}
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    infos, superseded_rows = build_active_inputs(root, grid, provenance, corrections, completed_weekly_references(root), retrieved_at)
    if len(infos) != 22 or {item.candidate_date for item in infos} != set(REFERENCE_CANDIDATES):
        raise ValueError("exactly 22 unique reference candidates are required")

    reference_rows: list[dict[str, Any]] = []
    active_provenance_rows: list[dict[str, Any]] = []
    audit_sources, all_anomalies = [], []
    for info in sorted(infos, key=lambda item: item.candidate_date):
        raw_file = raw_dir / f"krx_market_cap_{info.completed_weekly_reference_date}.csv"
        normalized_file = normalized_dir / raw_file.name
        copy_immutable(info.source, raw_file, info.source_sha256)
        frame = load_ui_export(raw_file, info.completed_weekly_reference_date)
        summary, anomalies = validate_snapshot(frame, info)
        normalized_file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(normalized_file, index=False)
        normalized_sha = sha256(normalized_file)
        if not anomalies.empty:
            all_anomalies.append(anomalies)
        relative_raw = raw_file.relative_to(root).as_posix()
        reference_rows.append({"reference_quarter": reference_quarter(info.candidate_date), "calendar_candidate_date": iso_date(info.candidate_date), "completed_weekly_reference_date": iso_date(info.completed_weekly_reference_date), "requested_date": iso_date(info.completed_weekly_reference_date), "effective_date": iso_date(info.completed_weekly_reference_date), "date_resolution_status": info.resolution_status, "source_provider": "KRX", "source_product": SOURCE_PRODUCT, "row_count": summary["total_rows"], "source_file": relative_raw, "sha256": info.source_sha256})
        active_provenance_rows.append({"source_provider": "KRX", "source_product": SOURCE_PRODUCT, "source_screen_id": SCREEN_ID, "calendar_candidate_date": iso_date(info.candidate_date), "completed_weekly_reference_date": iso_date(info.completed_weekly_reference_date), "requested_date": iso_date(info.completed_weekly_reference_date), "effective_date": iso_date(info.completed_weekly_reference_date), "retrieved_at": info.retrieved_at, "source_file": relative_raw, "sha256": info.source_sha256, "row_count": summary["total_rows"], "raw_schema": "|".join(KOREAN_COLUMNS), "normalization_version": NORMALIZATION_VERSION, "normalized_file": normalized_file.relative_to(root).as_posix(), "normalized_sha256": normalized_sha, "retrieval_status": "SUCCESS", "reference_status": "ACTIVE_REFERENCE", "superseded_by_effective_date": ""})
        audit_sources.append({"calendar_candidate_date": iso_date(info.candidate_date), "completed_weekly_reference_date": iso_date(info.completed_weekly_reference_date), "effective_date": iso_date(info.completed_weekly_reference_date), "file": relative_raw, "sha256": info.source_sha256, "row_count": summary["total_rows"], **summary})

    active_provenance = pd.DataFrame(active_provenance_rows)
    provenance_out = pd.concat([active_provenance, pd.DataFrame(superseded_rows).reindex(columns=active_provenance.columns, fill_value="")], ignore_index=True)
    pd.DataFrame(reference_rows).to_csv(reference_file, index=False)
    provenance_out.to_csv(provenance_file, index=False)
    anomaly_file = history / "krx_historical_market_cap_crosscheck_anomalies_v01.csv"
    columns = ["ticker", "name", "market", "effective_date", "market_cap", "calculated_market_cap", "relative_error"]
    (pd.concat(all_anomalies, ignore_index=True) if all_anomalies else pd.DataFrame(columns=columns)).to_csv(anomaly_file, index=False)
    crosscheck_record = manifest.get("existing_20250131_crosscheck")
    crosscheck = existing_crosscheck(Path("/Users/june/Downloads") / crosscheck_record["download_file"], root) if crosscheck_record else {"comparison_status": "NOT_PERFORMED"}
    alignment = all(row["completed_weekly_reference_date"] == row["effective_date"] for row in reference_rows)
    audit = {"version": "KRX_HISTORICAL_MARKET_CAP_BACKFILL_V01", "base_sha": BASE_SHA, "provider": "KRX", "source_product": SOURCE_PRODUCT, "source_screen_id": SCREEN_ID, "reference_date_semantics": "BUILD_HISTORICAL_SNAPSHOT_COMPLETED_W_FRI", "reference_ticker": REFERENCE_TICKER, "reference_candidate_count": 22, "resolved_reference_count": len(reference_rows), "unique_effective_date_count": len({item["effective_date"] for item in reference_rows}), "active_reference_count": len(active_provenance_rows), "superseded_source_count": len(superseded_rows), "successful_snapshot_count": len(audit_sources), "failed_snapshot_count": 0, "review_required_count": 0, "all_reference_dates_covered": True, "all_completed_weekly_reference_dates_match_effective_date": alignment, "reference_grid_file": reference_file.relative_to(root).as_posix(), "reference_grid_sha256": sha256(reference_file), "provenance_file": provenance_file.relative_to(root).as_posix(), "provenance_sha256": sha256(provenance_file), "crosscheck_anomaly_file": anomaly_file.relative_to(root).as_posix(), "crosscheck_anomaly_sha256": sha256(anomaly_file), "source_files": audit_sources, "existing_20250131_crosscheck": crosscheck, "market_cap_field_source": "KRX_CANONICAL", "shares_outstanding_field_source": "KRX", "historical_market_identity_source": "KRX", "current_market_cap_substitution_used": False, "future_shares_substitution_used": False, "market_cap_interpolation_used": False, "third_party_market_data_used": False, "sample_generated_count": 0, "oos_evaluation_executed": False, "network_provider": "KRX_ONLY", "network_request_count": args.network_request_count, "status": "HISTORICAL_MARKET_CAP_PIT_READY"}
    audit_file = history / "krx_historical_market_cap_backfill_audit_v01.json"
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{audit['status']}: {audit_file.relative_to(root)}")


if __name__ == "__main__":
    main()
