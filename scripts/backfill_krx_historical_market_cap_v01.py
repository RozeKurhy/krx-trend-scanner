#!/usr/bin/env python
"""Phase 13J-0: ingest official KRX Data Marketplace CSV exports as PIT sources.

The script never fetches market data.  KRX authentication and the official
``전종목 시세`` UI export are deliberately performed outside this script.  That
keeps credentials out of the repository and lets this script make the raw
download byte-for-byte immutable before producing normalized derived files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


BASE_SHA = "cb2aba5d680c2f5e770ef9441e2e781d82a8cb2e"
SCREEN_ID = "MDC0201020101"
SOURCE_PRODUCT = "ALL_STOCK_MARKET_DATA"
NORMALIZATION_VERSION = "KRX_ALL_STOCK_UI_EXPORT_NORMALIZED_V01"
REFERENCE_CANDIDATES = [
    "20200327", "20200626", "20200925", "20201225",
    "20210326", "20210625", "20210924", "20211231",
    "20220325", "20220624", "20220930", "20221230",
    "20230331", "20230630", "20230922", "20231229",
    "20240329", "20240628", "20240927", "20241227",
    "20250328", "20250627",
]
KOREAN_COLUMNS = {
    "종목코드": "ticker", "종목명": "name", "시장구분": "raw_market",
    "종가": "close", "거래량": "volume", "거래대금": "trading_value",
    "시가총액": "market_cap", "상장주식수": "shares_outstanding",
}


@dataclass(frozen=True)
class SnapshotInfo:
    candidate_date: str
    effective_date: str
    resolution_status: str
    downloaded_file: Path
    downloaded_sha256: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def reference_quarter(value: str) -> str:
    return f"{value[:4]} Q{(int(value[4:6]) - 1) // 3 + 1}"


def normalized_market(value: object) -> str:
    raw = str(value or "").strip()
    if raw.startswith("KOSPI"):
        return "KOSPI"
    if raw.startswith("KOSDAQ"):
        return "KOSDAQ"
    if raw.startswith("KONEX"):
        return "KONEX"
    return "OTHER"


def numeric(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.replace(",", "", regex=False).str.strip()
    values = values.replace({"": pd.NA, "-": pd.NA, "nan": pd.NA})
    return pd.to_numeric(values, errors="coerce").astype("Int64")


def load_ui_export(path: Path, effective_date: str) -> pd.DataFrame:
    """Read KRX UI CSV without modifying its on-disk raw bytes."""
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
    return out[[
        "ticker", "name", "raw_market", "market", "close", "volume", "trading_value",
        "market_cap", "shares_outstanding", "effective_date",
    ]]


def validate_snapshot(frame: pd.DataFrame, info: SnapshotInfo) -> tuple[dict[str, Any], pd.DataFrame]:
    duplicate_count = int(frame.ticker.duplicated().sum())
    if duplicate_count:
        raise ValueError(f"duplicate tickers in KRX snapshot {info.effective_date}: {duplicate_count}")
    if not frame.market_cap.notna().all() or not (frame.market_cap.dropna() > 0).all():
        raise ValueError(f"missing/non-positive KRX canonical market_cap: {info.effective_date}")
    if not (frame.close.dropna() >= 0).all():
        raise ValueError(f"negative close in KRX snapshot: {info.effective_date}")
    if not (frame.shares_outstanding.dropna() > 0).all():
        raise ValueError(f"non-positive shares outstanding in KRX snapshot: {info.effective_date}")

    ordinary = frame.dropna(subset=["close", "shares_outstanding", "market_cap"]).copy()
    ordinary["calculated_market_cap"] = ordinary.close.astype("int64") * ordinary.shares_outstanding.astype("int64")
    ordinary["relative_error"] = (ordinary.market_cap.astype(float) - ordinary.calculated_market_cap.astype(float)).abs() / ordinary.market_cap.astype(float)
    # Descriptive-only anomaly list; this is not an investability or production gate.
    anomalies = ordinary.loc[ordinary.relative_error > 0.01, [
        "ticker", "name", "market", "effective_date", "market_cap", "calculated_market_cap", "relative_error",
    ]].copy()
    counts = frame.market.value_counts().to_dict()
    summary = {
        "effective_date": iso_date(info.effective_date), "total_rows": len(frame),
        "kospi_rows": int(counts.get("KOSPI", 0)), "kosdaq_rows": int(counts.get("KOSDAQ", 0)),
        "konex_rows": int(counts.get("KONEX", 0)), "other_rows": int(counts.get("OTHER", 0)),
        "market_cap_non_null_count": int(frame.market_cap.notna().sum()),
        "shares_outstanding_non_null_count": int(frame.shares_outstanding.notna().sum()),
        "ticker_unique_count": int(frame.ticker.nunique()),
        "market_cap_crosscheck_anomaly_count": len(anomalies),
    }
    return summary, anomalies


def source_info(record: dict[str, Any]) -> SnapshotInfo:
    candidate, effective = record["candidate_date"], record["effective_date"]
    if candidate not in REFERENCE_CANDIDATES or not effective:
        raise ValueError(f"invalid reference record: {record}")
    source = Path("/Users/june/Downloads") / record["download_file"]
    if not source.is_file():
        raise FileNotFoundError(source)
    observed_sha = sha256(source)
    if observed_sha != record["sha256"]:
        raise ValueError(f"download hash drift: {source}")
    return SnapshotInfo(candidate, effective, record["date_resolution_status"], source, observed_sha)


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
    existing = pd.read_csv(root / "artifacts/investability/source/krx_market_cap_20250131.csv", dtype={"ticker": str})
    existing.ticker = existing.ticker.astype("string").str.zfill(6)
    merged = fresh.merge(existing[["ticker", "close", "market_cap", "shares_outstanding"]], on="ticker", how="inner", suffixes=("_krx", "_existing"))
    results = {"ticker_overlap_count": len(merged), "fresh_row_count": len(fresh), "existing_row_count": len(existing)}
    for column in ("close", "market_cap", "shares_outstanding"):
        results[f"{column}_equal_count"] = int((merged[f"{column}_krx"].astype("Int64") == pd.to_numeric(merged[f"{column}_existing"], errors="coerce").astype("Int64")).sum())
    results["comparison_status"] = "PASS" if all(results[f"{field}_equal_count"] == len(merged) for field in ("close", "market_cap", "shares_outstanding")) else "DESCRIPTIVE_DIFFERENCE"
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-manifest", required=True, type=Path)
    parser.add_argument("--network-request-count", required=True, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    history = root / "artifacts/investability/history"
    raw_dir, normalized_dir = history / "source", history / "normalized"
    manifest = json.loads(args.download_manifest.read_text(encoding="utf-8"))
    infos = [source_info(item) for item in manifest["references"]]
    if len(infos) != 22 or {item.candidate_date for item in infos} != set(REFERENCE_CANDIDATES):
        raise ValueError("exactly 22 unique reference candidates are required")

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    reference_rows, provenance_rows, audit_sources, all_anomalies = [], [], [], []
    for info in sorted(infos, key=lambda item: item.candidate_date):
        raw_file = raw_dir / f"krx_market_cap_{info.effective_date}.csv"
        normalized_file = normalized_dir / raw_file.name
        copy_immutable(info.downloaded_file, raw_file, info.downloaded_sha256)
        frame = load_ui_export(raw_file, info.effective_date)
        summary, anomalies = validate_snapshot(frame, info)
        normalized_file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(normalized_file, index=False)
        normalized_sha = sha256(normalized_file)
        if not anomalies.empty:
            all_anomalies.append(anomalies)
        relative_raw = raw_file.relative_to(root).as_posix()
        reference_rows.append({
            "reference_quarter": reference_quarter(info.candidate_date),
            "calendar_candidate_date": iso_date(info.candidate_date),
            "requested_date": iso_date(info.candidate_date), "effective_date": iso_date(info.effective_date),
            "date_resolution_status": info.resolution_status, "source_provider": "KRX",
            "source_product": SOURCE_PRODUCT, "row_count": summary["total_rows"],
            "source_file": relative_raw, "sha256": info.downloaded_sha256,
        })
        provenance_rows.append({
            "source_provider": "KRX", "source_product": SOURCE_PRODUCT, "source_screen_id": SCREEN_ID,
            "requested_date": iso_date(info.candidate_date), "effective_date": iso_date(info.effective_date),
            "retrieved_at": retrieved_at, "source_file": relative_raw, "sha256": info.downloaded_sha256,
            "row_count": summary["total_rows"],
            "raw_schema": "|".join(KOREAN_COLUMNS), "normalization_version": NORMALIZATION_VERSION,
            "normalized_file": normalized_file.relative_to(root).as_posix(), "normalized_sha256": normalized_sha,
            "retrieval_status": "SUCCESS",
        })
        audit_sources.append({"effective_date": iso_date(info.effective_date), "file": relative_raw, "sha256": info.downloaded_sha256, "row_count": summary["total_rows"], **summary})

    reference_file = history / "krx_market_cap_reference_grid_v01.csv"
    provenance_file = history / "krx_historical_market_cap_provenance_v01.csv"
    anomaly_file = history / "krx_historical_market_cap_crosscheck_anomalies_v01.csv"
    pd.DataFrame(reference_rows).to_csv(reference_file, index=False)
    pd.DataFrame(provenance_rows).to_csv(provenance_file, index=False)
    anomaly_columns = ["ticker", "name", "market", "effective_date", "market_cap", "calculated_market_cap", "relative_error"]
    anomalies = pd.concat(all_anomalies, ignore_index=True) if all_anomalies else pd.DataFrame(columns=anomaly_columns)
    anomalies.to_csv(anomaly_file, index=False)

    crosscheck_record = manifest.get("existing_20250131_crosscheck")
    crosscheck = existing_crosscheck(Path("/Users/june/Downloads") / crosscheck_record["download_file"], root) if crosscheck_record else {"comparison_status": "NOT_PERFORMED"}
    audit = {
        "version": "KRX_HISTORICAL_MARKET_CAP_BACKFILL_V01", "base_sha": BASE_SHA,
        "provider": "KRX", "source_product": SOURCE_PRODUCT, "source_screen_id": SCREEN_ID,
        "reference_candidate_count": 22, "resolved_reference_count": len(reference_rows),
        "unique_effective_date_count": len({item["effective_date"] for item in reference_rows}),
        "successful_snapshot_count": len(audit_sources), "failed_snapshot_count": 0, "review_required_count": 0,
        "reference_grid_file": reference_file.relative_to(root).as_posix(), "reference_grid_sha256": sha256(reference_file),
        "provenance_file": provenance_file.relative_to(root).as_posix(), "provenance_sha256": sha256(provenance_file),
        "crosscheck_anomaly_file": anomaly_file.relative_to(root).as_posix(), "crosscheck_anomaly_sha256": sha256(anomaly_file),
        "source_files": audit_sources, "existing_20250131_crosscheck": crosscheck,
        "all_reference_dates_covered": True, "market_cap_field_source": "KRX_CANONICAL",
        "shares_outstanding_field_source": "KRX", "historical_market_identity_source": "KRX",
        "current_market_cap_substitution_used": False, "future_shares_substitution_used": False,
        "market_cap_interpolation_used": False, "third_party_market_data_used": False,
        "sample_generated_count": 0, "oos_evaluation_executed": False,
        "network_provider": "KRX_ONLY", "network_request_count": args.network_request_count,
        "status": "HISTORICAL_MARKET_CAP_PIT_READY",
    }
    audit_file = history / "krx_historical_market_cap_backfill_audit_v01.json"
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{audit['status']}: {audit_file.relative_to(root)}")


if __name__ == "__main__":
    main()
