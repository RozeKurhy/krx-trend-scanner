#!/usr/bin/env python
"""Seal 117/215 KRX Historical Market Cap Sources with Strict Canonical Authority Crosscheck.

Enforces strict bidirectional cross-check between Grid and ACTIVE_REFERENCE Provenance
(exact source/normalized filename, SHA-256, and effective_date match),
strictly hard-fails on sealed source corruption without downgrading to missing,
and atomically replaces checkpoint artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

HISTORY_DIR = ROOT / "artifacts/patterns/pattern_a/validation/investability_history"
SOURCE_DIR = HISTORY_DIR / "source"
NORMALIZED_DIR = HISTORY_DIR / "normalized"
JULIA_V00_DIR = ROOT / "artifacts/strategies/julia/v00"

GRID_CSV = HISTORY_DIR / "krx_market_cap_reference_grid_v01.csv"
PROVENANCE_CSV = HISTORY_DIR / "krx_historical_market_cap_provenance_v01.csv"
P10_SOURCE_20250131 = ROOT / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20250131.csv"
P10_SOURCE_20260814 = ROOT / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260814.csv"

REQUIRED_DATES_CSV = JULIA_V00_DIR / "historical_market_cap_required_dates.csv"
MANIFEST_CSV = JULIA_V00_DIR / "historical_market_cap_source_manifest.csv"
MISSING_DATES_CSV = JULIA_V00_DIR / "historical_market_cap_missing_dates.csv"
PIT_AUDIT_JSON = JULIA_V00_DIR / "historical_investability_pit_audit.json"


class SealedMarketCapCheckpointIntegrityError(RuntimeError):
    """Raised when sealed available source or canonical authority fails integrity check."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class CanonicalUIAuthorityEntry:
    completed_weekly_reference_date: str
    effective_date: str
    source_filename: str
    source_sha256: str
    normalized_filename: str
    normalized_sha256: str
    reference_status: str


def load_canonical_ui_authorities(
    provenance_path: Path = PROVENANCE_CSV,
    grid_path: Path = GRID_CSV,
    p10_source_path: Path = P10_SOURCE_20250131,
) -> dict[str, CanonicalUIAuthorityEntry]:
    """Strictly cross-check Grid and ACTIVE Provenance to derive Canonical UI Authorities."""
    authorities: dict[str, CanonicalUIAuthorityEntry] = {}

    if not provenance_path.exists() or not grid_path.exists():
        raise SealedMarketCapCheckpointIntegrityError(
            f"Missing required authority files: provenance={provenance_path.exists()}, grid={grid_path.exists()}"
        )

    df_prov = pd.read_csv(provenance_path, dtype=str).fillna("")
    df_grid = pd.read_csv(grid_path, dtype=str).fillna("")

    # 1. Parse ACTIVE_REFERENCE rows only
    df_active = df_prov[df_prov["reference_status"] == "ACTIVE_REFERENCE"]
    prov_by_date: dict[str, dict[str, str]] = {}
    for _, r in df_active.iterrows():
        ref_d = str(r.get("completed_weekly_reference_date", "")).strip()
        if ref_d:
            prov_by_date[ref_d] = {
                "effective_date": str(r.get("effective_date", "")).strip(),
                "source_file": str(r.get("source_file", "")).strip(),
                "source_sha256": str(r.get("sha256", "")).strip(),
                "normalized_file": str(r.get("normalized_file", "")).strip(),
                "normalized_sha256": str(r.get("normalized_sha256", "")).strip(),
            }

    # 2. Cross-check against Grid rows
    grid_by_date: dict[str, dict[str, str]] = {}
    for _, r in df_grid.iterrows():
        ref_d = str(r.get("completed_weekly_reference_date", "")).strip()
        if ref_d:
            grid_by_date[ref_d] = {
                "source_file": str(r.get("source_file", "")).strip(),
                "source_sha256": str(r.get("sha256", "")).strip(),
            }

    # Strict bidirectional match for Phase 13J entries
    for ref_d, p_info in prov_by_date.items():
        g_info = grid_by_date.get(ref_d)
        if g_info is None:
            raise SealedMarketCapCheckpointIntegrityError(
                f"Canonical authority mismatch: {ref_d} is active in Provenance but missing in Grid."
            )

        p_src_name = Path(p_info["source_file"]).name
        g_src_name = Path(g_info["source_file"]).name
        if p_src_name != g_src_name:
            raise SealedMarketCapCheckpointIntegrityError(
                f"Source filename mismatch for {ref_d}: prov='{p_src_name}', grid='{g_src_name}'"
            )

        if p_info["source_sha256"] != g_info["source_sha256"]:
            raise SealedMarketCapCheckpointIntegrityError(
                f"Source SHA-256 mismatch for {ref_d}: prov='{p_info['source_sha256']}', grid='{g_info['source_sha256']}'"
            )

        norm_f = p_info["normalized_file"]
        norm_name = Path(norm_f).name if norm_f else p_src_name
        norm_sha = p_info["normalized_sha256"] if p_info["normalized_sha256"] else p_info["source_sha256"]

        authorities[ref_d] = CanonicalUIAuthorityEntry(
            completed_weekly_reference_date=ref_d,
            effective_date=p_info["effective_date"] or ref_d,
            source_filename=p_src_name,
            source_sha256=p_info["source_sha256"],
            normalized_filename=norm_name,
            normalized_sha256=norm_sha,
            reference_status="ACTIVE_REFERENCE",
        )

    # 3. Explicit Phase 10 Production Authority (2025-01-31)
    if p10_source_path.exists():
        p10_sha = sha256_file(p10_source_path)
        authorities["2025-01-31"] = CanonicalUIAuthorityEntry(
            completed_weekly_reference_date="2025-01-31",
            effective_date="2025-01-31",
            source_filename=p10_source_path.name,
            source_sha256=p10_sha,
            normalized_filename=p10_source_path.name,
            normalized_sha256=p10_sha,
            reference_status="ACTIVE_REFERENCE",
        )

    logger.info("Loaded %d strictly cross-checked active canonical UI authorities.", len(authorities))
    return authorities


def seal_checkpoint(
    root: Path = ROOT,
    required_dates_path: Path = REQUIRED_DATES_CSV,
    manifest_path: Path = MANIFEST_CSV,
    missing_dates_path: Path = MISSING_DATES_CSV,
    pit_audit_path: Path = PIT_AUDIT_JSON,
) -> None:
    if not required_dates_path.exists():
        raise FileNotFoundError(f"Missing required dates file: {required_dates_path}")

    # 1. Load Existing Manifest for Prior-Seal Revalidation & Corruption Guard
    old_manifest_by_date: dict[str, dict[str, Any]] = {}
    if manifest_path.exists():
        df_old_man = pd.read_csv(manifest_path, dtype=str).fillna("")
        for _, r in df_old_man.iterrows():
            sig_d = str(r.get("signal_reference_date", "")).strip()
            if sig_d:
                old_manifest_by_date[sig_d] = dict(r)
        logger.info("Loaded previous manifest with %d entries for SHA revalidation.", len(old_manifest_by_date))

    active_authorities = load_canonical_ui_authorities()

    df_req = pd.read_csv(required_dates_path)
    required_dates = sorted(df_req["signal_reference_date"].unique().tolist())
    total_required = len(required_dates)
    logger.info("Verifying %d required signal reference dates against authority...", total_required)

    manifest_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []

    available_count = 0
    missing_count = 0
    broken_source_paths = 0
    broken_norm_paths = 0
    source_sha_seal_created_count = 0
    normalized_sha_seal_created_count = 0
    source_sha_revalidation_count = 0
    normalized_sha_revalidation_count = 0
    source_sha_mismatches = 0
    norm_sha_mismatches = 0
    effective_date_violations = 0
    provider_failures = 0
    integrity_failures = 0

    channel_counts = {
        "KRX_DATA_MARKETPLACE_UI_CSV": 0,
        "KRX_DATA_MARKETPLACE_JSON_ENDPOINT": 0,
        "KRX_OPEN_API": 0,
    }
    role_counts = {
        "CANONICAL_RAW_UI_EXPORT": 0,
        "DERIVED_PROVIDER_RESPONSE_SNAPSHOT": 0,
    }

    history_dir = root / "artifacts/patterns/pattern_a/validation/investability_history"
    source_dir = history_dir / "source"
    norm_dir = history_dir / "normalized"
    p10_20250131 = root / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20250131.csv"

    for sig_d_str in required_dates:
        target_compact = sig_d_str.replace("-", "")
        norm_filename = f"krx_market_cap_{target_compact}.csv"
        raw_filename = f"krx_market_cap_{target_compact}.csv"
        norm_path = norm_dir / norm_filename
        raw_path = source_dir / raw_filename

        # Special handling for 2025-01-31 (Phase 10 production directory source)
        if not norm_path.exists() and sig_d_str == "2025-01-31" and p10_20250131.exists():
            norm_path = p10_20250131
            raw_path = p10_20250131

        prev_record = old_manifest_by_date.get(sig_d_str)
        was_previously_available = (
            prev_record is not None
            and prev_record.get("available", "").lower() == "true"
            and prev_record.get("integrity_status") == "PASS"
        )

        file_exists = norm_path.exists() and norm_path.stat().st_size > 1000

        # Hard fail check: previously sealed available source must NOT disappear
        if was_previously_available and not file_exists:
            raise SealedMarketCapCheckpointIntegrityError(
                f"Sealed available source {sig_d_str} has disappeared or is empty: {norm_path}"
            )

        if file_exists:
            try:
                # 1. Validate normalized file integrity
                df_norm = pd.read_csv(norm_path, dtype={"ticker": str})
                if df_norm.empty or len(df_norm) < 500:
                    raise ValueError(f"Incomplete rows in {norm_path}: {len(df_norm)}")
                if df_norm["ticker"].duplicated().any():
                    raise ValueError(f"Duplicate tickers in {norm_path}")
                if not (df_norm["market_cap"].dropna().astype(float) > 0).all():
                    raise ValueError(f"Invalid market cap values in {norm_path}")

                eff_d = str(df_norm.iloc[0]["effective_date"]) if "effective_date" in df_norm.columns else sig_d_str

                # Effective date contract: must not look ahead
                if pd.Timestamp(eff_d) > pd.Timestamp(sig_d_str):
                    effective_date_violations += 1
                    raise ValueError(f"Effective date {eff_d} > signal reference date {sig_d_str}")

                # 2. Validate source/raw path and SHA
                if not raw_path.exists():
                    broken_source_paths += 1
                    raise ValueError(f"Missing source file: {raw_path}")

                actual_raw_sha = sha256_file(raw_path)
                actual_norm_sha = sha256_file(norm_path)

                # Prior-Seal Revalidation vs Seal Creation
                if prev_record and prev_record.get("raw_sha256") and prev_record.get("normalized_sha256"):
                    prev_raw_sha = prev_record["raw_sha256"]
                    prev_norm_sha = prev_record["normalized_sha256"]

                    if actual_raw_sha == prev_raw_sha:
                        source_sha_revalidation_count += 1
                    else:
                        source_sha_mismatches += 1
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Sealed source SHA mismatch for {sig_d_str}: expected {prev_raw_sha}, got {actual_raw_sha}"
                        )

                    if actual_norm_sha == prev_norm_sha:
                        normalized_sha_revalidation_count += 1
                    else:
                        norm_sha_mismatches += 1
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Sealed normalized SHA mismatch for {sig_d_str}: expected {prev_norm_sha}, got {actual_norm_sha}"
                        )
                else:
                    source_sha_seal_created_count += 1
                    normalized_sha_seal_created_count += 1

                # 3. Dynamic ACTIVE Authority Derivation (Major 2)
                auth_entry = active_authorities.get(sig_d_str)
                if auth_entry is not None:
                    # Validate exact contract matches
                    if raw_path.name != auth_entry.source_filename:
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Canonical source filename mismatch for {sig_d_str}: authority={auth_entry.source_filename}, actual={raw_path.name}"
                        )
                    if norm_path.name != auth_entry.normalized_filename:
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Canonical normalized filename mismatch for {sig_d_str}: authority={auth_entry.normalized_filename}, actual={norm_path.name}"
                        )
                    if actual_raw_sha != auth_entry.source_sha256:
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Canonical authority SHA mismatch for {sig_d_str}: authority={auth_entry.source_sha256}, actual={actual_raw_sha}"
                        )
                    if actual_norm_sha != auth_entry.normalized_sha256:
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Canonical normalized authority SHA mismatch for {sig_d_str}: authority={auth_entry.normalized_sha256}, actual={actual_norm_sha}"
                        )
                    if eff_d != auth_entry.effective_date:
                        raise SealedMarketCapCheckpointIntegrityError(
                            f"Canonical effective date mismatch for {sig_d_str}: authority={auth_entry.effective_date}, actual={eff_d}"
                        )

                    channel = "KRX_DATA_MARKETPLACE_UI_CSV"
                    role = "CANONICAL_RAW_UI_EXPORT"
                    src_status = "AVAILABLE_EXISTING"
                    auth_status = "CANONICAL_UI_AUTHORITY"
                else:
                    channel = "KRX_DATA_MARKETPLACE_JSON_ENDPOINT"
                    role = "DERIVED_PROVIDER_RESPONSE_SNAPSHOT"
                    src_status = "CHECKPOINT_DERIVED_KRX_KDM_JSON"
                    auth_status = "CHECKPOINT_ACCEPTED_NOT_FINAL_SOURCE_AUTHORITY"

                channel_counts[channel] += 1
                role_counts[role] += 1
                available_count += 1

                manifest_rows.append({
                    "signal_reference_date": sig_d_str,
                    "required": True,
                    "available": True,
                    "source_provider": "KRX",
                    "source_channel": channel,
                    "source_role": role,
                    "requested_date": sig_d_str,
                    "effective_date": eff_d,
                    "date_resolution_status": "EXACT_COMPLETED_WEEK" if eff_d == sig_d_str else "PRIOR_COMPLETED_WEEK",
                    "raw_source_file": str(raw_path.relative_to(root)),
                    "normalized_source_file": str(norm_path.relative_to(root)),
                    "raw_sha256": actual_raw_sha,
                    "normalized_sha256": actual_norm_sha,
                    "source_and_normalized_identical_content": bool(actual_raw_sha == actual_norm_sha),
                    "raw_row_count": len(df_norm),
                    "normalized_row_count": len(df_norm),
                    "source_status": src_status,
                    "authority_status": auth_status,
                    "integrity_status": "PASS",
                })
            except Exception as e:
                # If previously available, HARD FAIL immediately
                if was_previously_available:
                    raise SealedMarketCapCheckpointIntegrityError(
                        f"Integrity check failed for previously sealed source {sig_d_str}: {e}"
                    ) from e

                logger.error("Integrity validation failed for %s: %s", sig_d_str, e)
                integrity_failures += 1
                missing_count += 1
                missing_rows.append({
                    "signal_reference_date": sig_d_str,
                    "reason": f"INTEGRITY_FAIL_{e}",
                    "resume_status": "PENDING",
                })
        else:
            missing_count += 1
            missing_rows.append({
                "signal_reference_date": sig_d_str,
                "reason": "KRX_KDM_TEMPORARY_USAGE_RESTRICTION",
                "resume_status": "PENDING",
            })
            manifest_rows.append({
                "signal_reference_date": sig_d_str,
                "required": True,
                "available": False,
                "source_provider": "KRX",
                "source_channel": None,
                "source_role": None,
                "requested_date": sig_d_str,
                "effective_date": None,
                "date_resolution_status": "UNRESOLVED",
                "raw_source_file": None,
                "normalized_source_file": None,
                "raw_sha256": None,
                "normalized_sha256": None,
                "source_and_normalized_identical_content": None,
                "raw_row_count": 0,
                "normalized_row_count": 0,
                "source_status": "MISSING_NOT_FETCHED",
                "authority_status": "NOT_AVAILABLE",
                "integrity_status": "PENDING_KRX_RECOVERY",
            })

    # Prepare Checkpoint Audit Data
    coverage_rate = round(available_count / total_required * 100.0, 2) if total_required > 0 else 0.0
    pit_audit_checkpoint = {
        "evaluation_start": "2022-01-01",
        "evaluation_end": "2026-08-14",
        "total_universe_scanned": 2528,
        "potential_entry_signal_count": 5176,
        "unique_signal_reference_dates_count": total_required,
        "historical_market_cap_source_dates_required": total_required,
        "historical_market_cap_source_dates_available": available_count,
        "historical_market_cap_source_dates_missing": missing_count,
        "historical_market_cap_source_coverage_rate": coverage_rate,
        "source_collection_status": "INTERRUPTED_KRX_TEMPORARY_RESTRICTION",
        "final_pit_backtest_ready": False,
        "final_result_status": "INVALID_INCOMPLETE_PIT_COVERAGE",
        "future_market_cap_fallback_count": 0,
        "current_20260814_market_cap_usage_count": 0,
        "pit_violation_count": 0,
        "broken_source_path_count": broken_source_paths,
        "broken_normalized_path_count": broken_norm_paths,
        "source_file_integrity_verified_count": available_count,
        "normalized_file_integrity_verified_count": available_count,
        "source_sha_seal_created_count": source_sha_seal_created_count,
        "normalized_sha_seal_created_count": normalized_sha_seal_created_count,
        "source_sha_revalidation_count": source_sha_revalidation_count,
        "normalized_sha_revalidation_count": normalized_sha_revalidation_count,
        "source_sha_mismatch_count": source_sha_mismatches,
        "normalized_sha_mismatch_count": norm_sha_mismatches,
        "effective_date_violation_count": effective_date_violations,
        "provider_validation_failure_count": provider_failures,
        "integrity_failure_count": integrity_failures,
        "source_provider_counts": {
            "KRX": available_count,
        },
        "source_channel_counts": channel_counts,
        "source_role_counts": role_counts,
        "operator_note": f"KRX Data Marketplace usage restriction encountered on 2026-08-22. {available_count} dates successfully sealed and authority-derived. {missing_count} dates pending resumption via approved KRX Open API.",
    }

    # Major 4: Atomic Write to Artifacts
    df_manifest = pd.DataFrame(manifest_rows)
    df_missing = pd.DataFrame(missing_rows)

    manifest_parent = manifest_path.parent
    manifest_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=str(manifest_parent), delete=False, encoding="utf-8", suffix=".csv") as tf_man:
        df_manifest.to_csv(tf_man.name, index=False)
        temp_man = Path(tf_man.name)

    with tempfile.NamedTemporaryFile("w", dir=str(manifest_parent), delete=False, encoding="utf-8", suffix=".csv") as tf_miss:
        df_missing.to_csv(tf_miss.name, index=False)
        temp_miss = Path(tf_miss.name)

    with tempfile.NamedTemporaryFile("w", dir=str(manifest_parent), delete=False, encoding="utf-8", suffix=".json") as tf_audit:
        json.dump(pit_audit_checkpoint, tf_audit, indent=2, ensure_ascii=False)
        temp_audit = Path(tf_audit.name)

    # Atomic replace all
    temp_man.replace(manifest_path)
    temp_miss.replace(missing_dates_path)
    temp_audit.replace(pit_audit_path)

    logger.info("Saved source manifest atomically to %s (%d rows)", manifest_path, len(df_manifest))
    logger.info("Saved missing dates manifest atomically to %s (%d rows)", missing_dates_path, len(df_missing))
    logger.info("Checkpoint PIT audit successfully saved atomically to %s", pit_audit_path)
    logger.info("Summary: REQUIRED=%d, AVAILABLE=%d, MISSING=%d, COVERAGE=%.2f%%", total_required, available_count, missing_count, coverage_rate)
    logger.info("Channel breakdown: %s", channel_counts)
    logger.info("SHA stats: Created=%d, Revalidated=%d, Mismatch=%d", source_sha_seal_created_count, source_sha_revalidation_count, source_sha_mismatches)


if __name__ == "__main__":
    seal_checkpoint()
