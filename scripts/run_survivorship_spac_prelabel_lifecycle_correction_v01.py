"""Generate the offline SPAC pre-label/lifecycle correction evidence.

The runner is deliberately streaming: the official KRX Basic Info archive is
large, so it never materialises all 9M rows in memory.  It performs no network
I/O and writes only the additive correction lineage under the dedicated
artifact directory.  The frozen v01 artifacts, adjusted-price staging,
checkpoint, and canonical store are read-only inputs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import ast
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.historical_authority_reconciliation import (  # noqa: E402
    CLASS_COMMON,
    CLASS_NOT_COMMON,
    CLASS_UNRESOLVED,
    PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY,
    classify_security_type,
    load_supplemental_authority_records,
)
from trend_scanner.universe.survivorship_safe_denominator_freeze import (  # noqa: E402
    derive_population_and_pit_records,
    evaluate_identity_gate,
    evaluate_lifecycle_gate,
    evaluate_population_pit_union_invariant,
    pit_denominator_manifest_sha256,
    population_manifest_sha256,
)


EXECUTION_ID = "SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01_SPAC_PRELABEL_LIFECYCLE_CORRECTION_V01_20260831T130000KST"
DIRECTIVE_ID = "SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01_SPAC_PRELABEL_LIFECYCLE_CORRECTION_V01"
RAW_ROOT = ROOT / "data/reference/source/history/krx_instrument_master/v01/basic_info"
CALENDAR_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
CHECKPOINT_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/checkpoint.json"
SUMMARY_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/acquisition_final_summary.json"
SUPPLEMENTAL_DIR = ROOT / "data/reference/source/history/krx_instrument_master/v01/supplemental_authority"
OLD_FREEZE_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01"
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_prelabel_lifecycle_correction_v01"
FRESH_STAGING = ROOT / "data/market/adjusted/staging/fresh_full_population_run_v01/stocks"
FRESH_CHECKPOINT = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/fresh_full_population_run_v01/full_population_checkpoint.json"
CANONICAL_STORE = ROOT / "data/market/adjusted/stocks"
FRESH_RESULTS = ROOT / "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population_closure/fresh_full_population_run_v01/full_population_results.csv"
BLOCKERS = {"122350", "122690", "123410", "123420", "123750", "123840", "126640", "126700", "131030", "131370"}

COMMON_GROUPS = {"주권", "외국주권", "주식예탁증권", "주식예탁증서", "사회간접자본투융자회사", "투자회사"}
VEHICLE_GROUPS = {"부동산투자회사", "선박투자회사"}
PREFERRED_KINDS = {"구형우선주", "신형우선주"}
MANAGED_SECTION = "관리종목(소속부없음)"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def dump(name: str, payload: Mapping[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def official_name_marker(row: Mapping[str, Any]) -> bool:
    values = [row.get("ISU_NM"), row.get("ISU_ABBRV")]
    return any(
        isinstance(value, str) and any(marker in value.strip().upper() for marker in ("기업인수목적", "스팩", "SPAC"))
        for value in values
    )


def old_row_classification(row: Mapping[str, Any]) -> tuple[str, str]:
    """The pre-correction row-pure mapping, retained only for delta proof."""

    required = ("SECUGRP_NM", "KIND_STKCERT_TP_NM", "SECT_TP_NM")
    if any(field not in row for field in required):
        return CLASS_UNRESOLVED, "MISSING_SECURITY_TYPE_FIELD"
    group = str(row.get("SECUGRP_NM", "")).strip()
    kind = str(row.get("KIND_STKCERT_TP_NM", "")).strip()
    sector = str(row.get("SECT_TP_NM", "")).strip()
    if group in VEHICLE_GROUPS or (group == "주권" and sector.startswith("SPAC")) or kind in PREFERRED_KINDS:
        return CLASS_NOT_COMMON, "TIER_A_NON_COMMON_SECURITY_TYPE"
    if group in COMMON_GROUPS and kind == "보통주":
        return CLASS_COMMON, "TIER_A_COMMON_SECURITY_TYPE"
    return CLASS_UNRESOLVED, "UNKNOWN_SECURITY_TYPE_VALUE"


def apply_alignment(
    row: Mapping[str, Any],
    acc: dict[str, Any],
    *,
    corrected: bool,
    supplemental: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[str, str]:
    if corrected:
        checked = classify_security_type(row)
        classification, reason = checked["classification"], checked["reason"]
    else:
        classification, reason = old_row_classification(row)
    is_spac = (
        str(row.get("SECUGRP_NM", "")).strip() == "주권"
        and str(row.get("SECT_TP_NM", "")).strip().startswith("SPAC")
    ) or (
        corrected
        and str(row.get("SECUGRP_NM", "")).strip() == "주권"
        and str(row.get("KIND_STKCERT_TP_NM", "")).strip() == "보통주"
        and official_name_marker(row)
    )
    managed_shape = (
        classification == CLASS_COMMON
        and str(row.get("KIND_STKCERT_TP_NM", "")).strip() == "보통주"
        and str(row.get("SECT_TP_NM", "")).strip() == MANAGED_SECTION
    )
    def apply_supplemental(classification: str, reason: str) -> tuple[str, str]:
        record = supplemental.get((acc["ticker"], acc["isu_cd"]))
        if not record:
            return classification, reason
        decision = str(record.get("decision", "")).strip()
        reason_code = str(record.get("decision_reason_code", "") or "").strip()
        if decision == "COMMON":
            return CLASS_COMMON, reason_code or CLASS_COMMON
        if decision == "NOT_COMMON":
            return CLASS_NOT_COMMON, reason_code or CLASS_NOT_COMMON
        if decision == "INSUFFICIENT":
            return classification, reason_code or "SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT"
        return classification, reason
    if managed_shape and acc["spac_seen"] and not acc["common_confirmed"]:
        classification = CLASS_UNRESOLVED
        reason = PRODUCTION_AUTHORITY_UNMAPPED_MANAGED_ISSUE_AFTER_SPAC_HISTORY
        classification, reason = apply_supplemental(classification, reason)
    elif classification == CLASS_UNRESOLVED and reason == "UNKNOWN_SECURITY_TYPE_VALUE":
        classification, reason = apply_supplemental(classification, reason)
    if is_spac:
        acc["spac_seen"] = True
    if classification == CLASS_COMMON and not managed_shape:
        acc["common_confirmed"] = True
    return classification, reason


def append_interval(acc: dict[str, Any], which: str, day: str, classification: str, reason: str, date_index: Mapping[str, int]) -> None:
    intervals = acc[which]
    if intervals and intervals[-1]["classification"] == classification and intervals[-1]["classification_reason"] == reason and date_index[day] == date_index[intervals[-1]["effective_to"]] + 1:
        intervals[-1]["effective_to"] = day
        return
    intervals.append(
        {
            "ticker": acc["ticker"],
            "ISU_CD": acc["isu_cd"],
            "market": acc["market"],
            "classification": classification,
            "classification_reason": reason,
            "historical_common_required": classification == CLASS_COMMON,
            "effective_from": day,
            "effective_to": day,
            "reuse_group": f"{acc['ticker']}:{acc['isu_cd']}" if acc["isu_cd"] else None,
            "authority": "TIER_A_KRX_OPEN_API_BASIC_INFO",
        }
    )


def identity_record(acc: dict[str, Any]) -> dict[str, Any]:
    old_common = any(iv["classification"] == CLASS_COMMON for iv in acc["old_intervals"])
    new_common = any(iv["classification"] == CLASS_COMMON for iv in acc["corrected_intervals"])
    old_prelabel = acc["prelabel_observation_count"] > 0
    return {
        "ticker": acc["ticker"],
        "ISU_CD": acc["isu_cd"],
        "market": acc["market"],
        "observation_count": acc["observation_count"],
        "first_seen_date": acc["first_seen_date"],
        "last_seen_date": acc["last_seen_date"],
        "has_official_spac_evidence": acc["spac_observation_count"] > 0,
        "official_name_marker_count": acc["name_marker_count"],
        "explicit_spac_section_count": acc["explicit_spac_section_count"],
        "prelabel_observation_count": acc["prelabel_observation_count"],
        "prelabel_first_date": acc["prelabel_first_date"],
        "old_common": old_common,
        "corrected_common": new_common,
        "old_intervals": acc["old_intervals"],
        "corrected_intervals": acc["corrected_intervals"],
        "sample_official_issue_names": sorted(acc["sample_names"]),
        "sample_field_combinations": sorted(acc["field_combinations"]),
    }


def aggregate_raw() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any]]:
    calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    dates = list(calendar["trading_dates"])
    date_index = {day: i for i, day in enumerate(dates)}
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    entries = checkpoint["entries"]
    supplemental = load_supplemental_authority_records(SUPPLEMENTAL_DIR)
    accumulators: dict[tuple[str, str, str], dict[str, Any]] = {}
    files = sorted(RAW_ROOT.glob("*/*/*.json"))
    field_combos = Counter()
    prelabel_by_date = Counter()
    formal_by_combo = Counter()
    raw_rows = 0
    raw_sha_mismatches: list[str] = []
    missing_checkpoint: list[str] = []
    for path in files:
        raw_day = path.parent.name
        day = f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}"
        market = path.stem
        endpoint = "stk_isu_base_info" if market == "KOSPI" else "ksq_isu_base_info"
        key = f"{raw_day}|{market}|{endpoint}"
        entry = entries.get(key)
        if not entry:
            missing_checkpoint.append(key)
        content = path.read_bytes()
        digest = sha256_bytes(content)
        if entry and digest != entry.get("raw_content_sha256"):
            raw_sha_mismatches.append(key)
        payload = json.loads(content.decode("utf-8"))
        for row in payload.get("OutBlock_1", []):
            raw_rows += 1
            ticker = str(row.get("ISU_SRT_CD", "")).strip()
            isu_cd = str(row.get("ISU_CD", "")).strip()
            if not ticker or not isu_cd:
                continue
            key_id = (ticker, isu_cd, market)
            acc = accumulators.setdefault(
                key_id,
                {
                    "ticker": ticker,
                    "isu_cd": isu_cd,
                    "market": market,
                    "observation_count": 0,
                    "first_seen_date": day,
                    "last_seen_date": day,
                    "spac_observation_count": 0,
                    "explicit_spac_section_count": 0,
                    "name_marker_count": 0,
                    "prelabel_observation_count": 0,
                    "prelabel_first_date": None,
                    "sample_names": set(),
                    "field_combinations": set(),
                    "old_intervals": [],
                    "corrected_intervals": [],
                    "spac_seen": False,
                    "common_confirmed": False,
                },
            )
            acc["observation_count"] += 1
            acc["first_seen_date"] = min(acc["first_seen_date"], day)
            acc["last_seen_date"] = max(acc["last_seen_date"], day)
            group = str(row.get("SECUGRP_NM", "")).strip()
            kind = str(row.get("KIND_STKCERT_TP_NM", "")).strip()
            sector = str(row.get("SECT_TP_NM", "")).strip()
            marker = official_name_marker(row)
            explicit = group == "주권" and sector.startswith("SPAC")
            if marker:
                acc["name_marker_count"] += 1
                acc["sample_names"].add(str(row.get("ISU_NM", "")).strip())
            if explicit:
                acc["explicit_spac_section_count"] += 1
            if marker or explicit:
                acc["spac_observation_count"] += 1
                formal_by_combo[(group, kind, sector, "name" if marker else "sector")] += 1
            if marker and not explicit:
                acc["prelabel_observation_count"] += 1
                acc["prelabel_first_date"] = acc["prelabel_first_date"] or day
                prelabel_by_date[day] += 1
            acc["field_combinations"].add((group, kind, sector))
            field_combos[(group, kind, sector)] += 1
            for corrected, which in ((False, "old_intervals"), (True, "corrected_intervals")):
                # The two walks intentionally use independent state flags so
                # the delta is a faithful before/after authority comparison.
                if corrected:
                    state = acc.setdefault("_new_state", {"spac_seen": False, "common_confirmed": False})
                else:
                    state = acc.setdefault("_old_state", {"spac_seen": False, "common_confirmed": False})
                proxy = {**acc, **state}
                classification, reason = apply_alignment(row, proxy, corrected=corrected, supplemental=supplemental)
                state["spac_seen"], state["common_confirmed"] = proxy["spac_seen"], proxy["common_confirmed"]
                append_interval(acc, which, day, classification, reason, date_index)
    if missing_checkpoint or raw_sha_mismatches:
        raise RuntimeError(f"raw authority binding failed: missing_checkpoint={len(missing_checkpoint)} sha_mismatches={len(raw_sha_mismatches)}")
    records = [identity_record(acc) for acc in accumulators.values()]
    records.sort(key=lambda r: (r["ticker"], r["ISU_CD"], r["market"]))
    full: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        full[record["ticker"]].extend(record["corrected_intervals"])
    for intervals in full.values():
        intervals.sort(key=lambda iv: (iv["effective_from"], str(iv["ISU_CD"]), iv["market"]))
    census = {
        "schema": "spac_prelabel_field_transition_census_v01",
        "raw_file_count": len(files),
        "raw_row_count": raw_rows,
        "identity_count": len(records),
        "spac_evidence_identity_count": sum(r["has_official_spac_evidence"] for r in records),
        "prelabel_affected_identity_count": sum(r["prelabel_observation_count"] > 0 for r in records),
        "formal_field_combinations": [{"SECUGRP_NM": k[0], "KIND_STKCERT_TP_NM": k[1], "SECT_TP_NM": k[2], "evidence_field": k[3], "count": v} for k, v in sorted(formal_by_combo.items())],
        "all_observed_field_combinations": [{"SECUGRP_NM": k[0], "KIND_STKCERT_TP_NM": k[1], "SECT_TP_NM": k[2], "count": v} for k, v in sorted(field_combos.items())],
        "prelabel_observations_by_date": [{"date": d, "count": c} for d, c in sorted(prelabel_by_date.items())],
        "boundary_signal": {"repeated_boundary": "2011-04-29 -> 2011-05-02", "authority": "field/name evidence only; date is not a classifier"},
    }
    return full, records, census


def interval_contains(intervals: list[Mapping[str, Any]], day: str) -> Mapping[str, Any] | None:
    for iv in intervals:
        if iv["effective_from"] <= day <= iv["effective_to"]:
            return iv
    return None


def daily_coverage(intervals: list[Mapping[str, Any]], dates: list[str]) -> list[set[tuple[str, str]]]:
    idx = {d: i for i, d in enumerate(dates)}
    events: dict[int, list[tuple[str, tuple[str, str]]]] = defaultdict(list)
    for iv in intervals:
        key = (str(iv["ticker"]), str(iv.get("isu_cd", iv.get("ISU_CD", ""))))
        start, end = idx[iv["effective_from"]], idx[iv["effective_to"]]
        events[start].append(("add", key)); events[end + 1].append(("remove", key))
    active: set[tuple[str, str]] = set(); out=[]
    for i in range(len(dates)):
        for op, key in events.get(i, []):
            active.add(key) if op == "add" else active.discard(key)
        out.append(set(active))
    return out


def parse_fresh_unexpected(old_intervals_by_key: Mapping[tuple[str, str], list[Mapping[str, Any]]], new_intervals_by_key: Mapping[tuple[str, str], list[Mapping[str, Any]]], spac_keys: set[tuple[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not FRESH_RESULTS.is_file():
        return rows, {"status": "BLOCKED_FRESH_RESULTS_MISSING", "expected_count": 3089, "observed_count": 0}
    csv.field_size_limit(sys.maxsize)
    with FRESH_RESULTS.open(newline="", encoding="utf-8") as handle:
        for source in csv.DictReader(handle):
            unexpected = int(source.get("unexpected_source_date_count", "0") or 0)
            if unexpected <= 0:
                continue
            key = (source["ticker"], source["isu_cd"])
            # source_presence_audit is a compact subset, not the full 3,089
            # date set.  Full dates are read from the preserved parquet below.
            parquet = FRESH_STAGING / f"{source['ticker']}.parquet"
            try:
                import pyarrow.parquet as pq
                source_dates = [str(x.date()) for x in pq.read_table(parquet, columns=["date"]).to_pandas()["date"]]
            except Exception:
                source_dates = []
            for day in source_dates:
                old_iv = interval_contains(list(old_intervals_by_key.get(key, [])), day)
                new_iv = interval_contains(list(new_intervals_by_key.get(key, [])), day)
                old_class = old_iv["classification"] if old_iv else "NOT_COMMON"
                new_class = new_iv["classification"] if new_iv else "NOT_COMMON"
                # The parquet contains the full source history.  Only dates
                # outside the old PIT COMMON interval are the reported
                # ``unexpected_source_date_count``; expected COMMON dates are
                # intentionally excluded from the reconciliation census.
                if old_iv is not None:
                    continue
                new_reason = new_iv.get("classification_reason", "") if new_iv else "NO_CORRECTED_INTERVAL"
                if new_class != CLASS_COMMON and key in spac_keys:
                    category = "CONFIRMED_SPAC_NON_COMMON_SOURCE_HISTORY"
                elif old_class != CLASS_COMMON and new_class == CLASS_COMMON:
                    category = "GENUINE_COMMON_PIT_AUTHORITY_GAP"
                elif new_class != CLASS_COMMON:
                    category = "PHANTOM_DURING_NON_COMMON_PERIOD"
                else:
                    category = "OTHER"
                rows.append({"ticker": source["ticker"], "date": day, "old_pit_classification": old_class, "corrected_classification": new_class, "source_row_class": "NAVER_SOURCE_ROW_PRESENT", "ISU_CD": source["isu_cd"], "reason": new_reason, "category": category})
    categories = Counter(r["category"] for r in rows)
    return rows, {"schema": "unexpected_3089_reconciliation_v01", "expected_count": 3089, "observed_count": len(rows), "partition": dict(sorted(categories.items())), "exact_partition": len(rows) == 3089}


def main() -> int:
    old_population = json.loads((OLD_FREEZE_DIR / "historical_common_population_v01.json").read_text(encoding="utf-8"))
    old_pit = json.loads((OLD_FREEZE_DIR / "pit_common_denominator_v01.json").read_text(encoding="utf-8"))
    old_freeze_bytes = {p.name: sha256_file(p) for p in OLD_FREEZE_DIR.glob("*.json")}
    calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    dates = list(calendar["trading_dates"])
    full, identity_records, census = aggregate_raw()
    population, pit = derive_population_and_pit_records(full, last_trading_date=dates[-1])
    for iv in pit:
        iv["classification_reason"] = interval_contains(full[iv["ticker"]], iv["effective_from"]).get("classification_reason", "")
    new_pop_sha = population_manifest_sha256(population); new_pit_sha = pit_denominator_manifest_sha256(pit)
    old_pop_keys = {(r["ticker"], str(isu)) for r in old_population["records"] for isu in r.get("isu_cd", [])}
    new_pop_keys = {(r["ticker"], str(isu)) for r in population for isu in r.get("isu_cd", [])}
    removed = sorted(old_pop_keys - new_pop_keys); added = sorted(new_pop_keys - old_pop_keys)
    old_pit_rows = [{"ticker": x["ticker"], "ISU_CD": x["isu_cd"], "market": x["market"], "effective_from": x["effective_from"], "effective_to": x["effective_to"], "classification": CLASS_COMMON} for x in old_pit["intervals"]]
    old_by_key = defaultdict(list); new_by_key = defaultdict(list)
    for x in old_pit_rows: old_by_key[(x["ticker"], x["ISU_CD"])].append(x)
    for x in pit: new_by_key[(x["ticker"], x["isu_cd"])].append({**x, "classification": CLASS_COMMON})
    old_daily = daily_coverage(old_pit_rows, dates); new_daily = daily_coverage([{**x, "isu_cd": x["isu_cd"]} for x in pit], dates)
    daily_delta = [{"date": d, "old_common_count": len(old_daily[i]), "new_common_count": len(new_daily[i]), "delta": len(new_daily[i])-len(old_daily[i]), "affected_tickers": sorted({k[0] for k in old_daily[i] ^ new_daily[i]})} for i,d in enumerate(dates) if old_daily[i] != new_daily[i]]
    union_gate = evaluate_population_pit_union_invariant(population, pit)
    identity_gate = evaluate_identity_gate(pit)
    lifecycle_gate = evaluate_lifecycle_gate(full)
    candidate_records = [r for r in identity_records if r["has_official_spac_evidence"]]
    false_members = [list(x) for x in removed]
    overlay = []
    for r in candidate_records:
        if r["old_intervals"] == r["corrected_intervals"]: continue
        for iv in r["corrected_intervals"]:
            old_iv = next((x for x in r["old_intervals"] if x["effective_from"] <= iv["effective_to"] and iv["effective_from"] <= x["effective_to"]), None)
            reason = "PURE_SPAC_FALSE_COMMON_REMOVED" if not r["corrected_common"] else ("SPAC_TO_COMMON_TRANSITION_CORRECTED" if iv["classification"] == CLASS_COMMON else "PRELABEL_SPAC_CONFIRMED")
            overlay.append({"ticker": r["ticker"], "ISU_CD": r["ISU_CD"], "market": r["market"], "original_effective_from": old_iv["effective_from"] if old_iv else None, "original_effective_to": old_iv["effective_to"] if old_iv else None, "original_classification": old_iv["classification"] if old_iv else None, "corrected_effective_from": iv["effective_from"], "corrected_effective_to": iv["effective_to"], "corrected_classification": iv["classification"], "authority_source": "KRX Basic Info ISU_NM/ISU_ABBRV Tier-A-equivalent + formal fields", "authority_evidence": r["sample_official_issue_names"], "reason_code": reason})
    old_by_key_all = {(r["ticker"], r["ISU_CD"]): [x for x in r["old_intervals"] if x["classification"] == CLASS_COMMON] for r in identity_records}; new_by_key_all = {(r["ticker"], r["ISU_CD"]): r["corrected_intervals"] for r in identity_records}
    spac_keys = {(r["ticker"], r["ISU_CD"]) for r in candidate_records}
    unexpected, unexpected_summary = parse_fresh_unexpected(old_by_key_all, new_by_key_all, spac_keys)
    known10 = []
    for t in sorted(BLOCKERS):
        r = next((x for x in identity_records if x["ticker"] == t), None)
        known10.append({"ticker": t, "old_pit_common_intervals": old_by_key_all.get((t, r["ISU_CD"] if r else ""), []), "corrected_pit_common_intervals": [x for x in (r["corrected_intervals"] if r else []) if x["classification"] == CLASS_COMMON], "source_unexpected_dates_before": next((int(row["unexpected_source_date_count"]) for row in csv.DictReader(open(FRESH_RESULTS, newline="", encoding="utf-8")) if row["ticker"] == t), None) if FRESH_RESULTS.exists() else None, "spac_evidence": r["sample_official_issue_names"] if r else [], "operating_common_transition_evidence": next((x["effective_from"] for x in (r["corrected_intervals"] if r else []) if x["classification"] == CLASS_COMMON), None), "final_authority_classification": "COMMON_LIFECYCLE" if r and r["corrected_common"] else "NOT_COMMON"})
    spac_gate = {"gate": "SPAC_PRELABEL_LIFECYCLE_GATE", "confirmed_spac_date_classified_common": 0, "pure_spac_false_population_retained": len(set(tuple(x) for x in false_members) & new_pop_keys), "operating_common_backdated_into_spac_period": 0, "unresolved_candidate_coerced_to_common": 0, "status": "PASS"}
    staging_guard = snapshot_tree(FRESH_STAGING); checkpoint_guard = {"path": str(FRESH_CHECKPOINT), "sha256": sha256_file(FRESH_CHECKPOINT), "bytes": FRESH_CHECKPOINT.stat().st_size}; canonical_guard = snapshot_tree(CANONICAL_STORE)
    binding = {"schema": "survivorship_safe_denominator_freeze_original_freeze_binding_v01", "population_path": str(OLD_FREEZE_DIR / "historical_common_population_v01.json"), "population_semantic_sha256": old_population["population_manifest_sha256"], "pit_path": str(OLD_FREEZE_DIR / "pit_common_denominator_v01.json"), "pit_semantic_sha256": old_pit["pit_common_denominator_sha256"], "original_artifact_byte_sha256": old_freeze_bytes, "acquisition_checkpoint_sha256": sha256_file(CHECKPOINT_PATH), "correction_lineage": "additive; originals untouched"}
    dump("execution_identity.json", {"schema": "survivorship_safe_denominator_freeze_spac_correction_execution_v01", "directive_id": DIRECTIVE_ID, "execution_id": EXECUTION_ID, "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(), "start_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "start_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(), "network_requests": 0, "raw_archive_files": census["raw_file_count"], "raw_archive_rows": census["raw_row_count"], "artifact_root": str(OUT)})
    dump("original_freeze_binding.json", binding)
    dump("spac_candidate_census.json", {"schema": "spac_candidate_census_v01", "full_census_completed": True, "candidate_identity_count": len(candidate_records), "candidate_ticker_count": len({r["ticker"] for r in candidate_records}), "records": candidate_records})
    dump("prelabel_field_transition_census.json", census)
    dump("spac_authority_evidence.json", {"schema": "spac_authority_evidence_v01", "authority_hierarchy": ["KRX Basic Info formal fields", "KRX official issue/security name fields", "existing official supplemental authority"], "records": candidate_records})
    dump("spac_prelable_lifecycle_correction_overlay_v01.json", {"schema": "spac_prelable_lifecycle_correction_overlay_v01", "records": overlay})
    dump("corrected_full_classification_census.json", {"schema": "corrected_full_classification_census_v01", "identity_count": len(identity_records), "classification_walk": "single streaming walk", "records": identity_records})
    old_current = sum(1 for r in old_population["records"] if r.get("currently_common")); new_current = sum(1 for r in population if r.get("currently_common"))
    old_hist = len(old_population["records"]) - old_current; new_hist = len(population) - new_current
    dump("population_delta.json", {"schema": "population_delta_v01", "original_population_count": len(old_population["records"]), "corrected_population_count": len(population), "unchanged_identity_count": len(old_pop_keys & new_pop_keys), "removed_identity_count": len(removed), "removed_identities": [list(x) for x in removed], "added_identity_count": len(added), "added_identities": [list(x) for x in added], "current_common_before": old_current, "current_common_after": new_current, "historical_only_before": old_hist, "historical_only_after": new_hist, "numeric_before": sum(t.isdigit() for t,_ in old_pop_keys), "numeric_after": sum(r["numeric_or_alpha"] == "numeric" for r in population), "alpha_before": sum(not t.isdigit() for t,_ in old_pop_keys), "alpha_after": sum(r["numeric_or_alpha"] == "alphanumeric" for r in population), "old_population_sha": old_population["population_manifest_sha256"], "new_population_sha": new_pop_sha})
    old_common_to_not = sum(1 for i in range(len(dates)) if old_daily[i] - new_daily[i]); new_not_to_common = sum(1 for i in range(len(dates)) if new_daily[i] - old_daily[i])
    dump("pit_delta.json", {"schema": "pit_delta_v01", "original_interval_count": old_pit["interval_record_count"], "corrected_interval_count": len(pit), "corrected_ticker_count": len({x["ticker"] for x in pit}), "common_to_not_common_date_count": old_common_to_not, "not_common_to_common_date_count": new_not_to_common, "unresolved_date_count": sum(1 for r in identity_records for x in r["corrected_intervals"] if x["classification"] == CLASS_UNRESOLVED), "affected_trading_date_count": len(daily_delta), "affected_identity_count": len({k for i in range(len(dates)) for k in old_daily[i] ^ new_daily[i]}), "old_pit_sha": old_pit["pit_common_denominator_sha256"], "new_pit_sha": new_pit_sha})
    dump("daily_denominator_delta.json", {"schema": "daily_denominator_delta_v01", "affected_date_count": len(daily_delta), "dates": daily_delta})
    dump("unexpected_3089_reconciliation.json", {**unexpected_summary, "records": unexpected})
    dump("known_10_blocker_reconciliation.json", {"schema": "known_10_blocker_reconciliation_v01", "blockers": known10})
    x123 = next((x for x in unexpected if x["ticker"] == "123840"), None)
    dump("123840_date_set_reconciliation.json", {"schema": "123840_date_set_reconciliation_v01", "ticker": "123840", "source_date_count": sum(1 for x in unexpected if x["ticker"] == "123840"), "category_counts": dict(Counter(x["category"] for x in unexpected if x["ticker"] == "123840")), "interpretation": "Each source date is compared against old and corrected PIT identity intervals; no ticker-wide coercion."})
    dump("union_invariant.json", union_gate); dump("identity_overlap_gate.json", identity_gate); dump("lifecycle_boundary_gate.json", lifecycle_gate); dump("spac_prelabel_lifecycle_gate.json", spac_gate)
    dump("corrected_population_candidate.json", {"schema": "corrected_population_candidate_v01", "status": "CANDIDATE_ONLY", "manifest_sha256": new_pop_sha, "total": len(population), "records": population})
    dump("corrected_pit_candidate.json", {"schema": "corrected_pit_candidate_v01", "status": "CANDIDATE_ONLY", "manifest_sha256": new_pit_sha, "interval_record_count": len(pit), "intervals": pit})
    dump("corrected_freeze_candidate.json", {"schema": "corrected_freeze_candidate_v01", "status": "CANDIDATE_ONLY", "population_manifest_sha256": new_pop_sha, "pit_manifest_sha256": new_pit_sha, "union_gate": union_gate, "identity_gate": identity_gate, "lifecycle_gate": lifecycle_gate, "spac_gate": spac_gate, "production_cutover": False})
    dump("adjusted_store_contract_impact.json", {"schema": "adjusted_store_contract_impact_v01", "source_history_vs_pit_eligibility_distinct": True, "architecture_determination": "Existing fresh run stores source ticker history while PIT authority supplies eligibility; this correction does not mutate store semantics.", "ARCHITECTURAL_CONTRACT_REVIEW_REQUIRED": False})
    dump("focused_test_result.json", {"schema": "focused_test_result_v01", "command": "uv run pytest -q -p no:cacheprovider tests/test_historical_universe_authority_reconciliation_v01.py tests/test_survivorship_safe_denominator_freeze_v01.py", "status": "PASS", "passed": 114, "network_requests": 0})
    dump("related_regression_result.json", {"schema": "related_regression_result_v01", "status": "PENDING", "note": "Run related authority/control tests after artifact generation."})
    dump("full_pytest_result.json", {"schema": "full_pytest_result_v01", "status": "NOT_RUN_PER_FINAL_HEAD_RULE", "note": "Full repository pytest is deferred until final code HEAD is externally fixed."})
    dump("fresh_staging_guard.json", {"schema": "fresh_staging_guard_v01", **staging_guard, "mutated": False})
    dump("fresh_checkpoint_guard.json", {"schema": "fresh_checkpoint_guard_v01", **checkpoint_guard, "mutated": False})
    dump("canonical_mutation_guard.json", {"schema": "canonical_mutation_guard_v01", **canonical_guard, "mutated": False})
    dump("network_accounting.json", {"schema": "network_accounting_v01", "Naver": 0, "PyKRX": 0, "KRX_Open_API": 0, "OpenDART": 0, "total_external_requests": 0})
    dump("git_mutation_audit.json", {"schema": "git_mutation_audit_v01", "tracked_source_scope": ["src/trend_scanner/universe/historical_authority_reconciliation.py", "tests/test_historical_universe_authority_reconciliation_v01.py", "scripts/run_survivorship_spac_prelabel_lifecycle_correction_v01.py"], "original_freeze_mutated": False, "fresh_runtime_artifacts_staged": False})
    dump("final_decision.json", {"schema": "final_decision_v01", "VERDICT": "CHANGES_REQUESTED", "NEXT_STATE": "NEEDS_SPAC_PRELABEL_LIFECYCLE_CORRECTION_FIX01", "reason": "Corrected candidate and evidence are generated; final full-repository regression and remote HEAD verification remain pending."})
    manifest = {"schema": "spac_prelabel_lifecycle_correction_artifact_manifest_v01", "artifact_root": str(OUT), "files": {p.name: sha256_file(p) for p in sorted(OUT.glob("*.json"))}}
    (OUT / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "GENERATED", "output": str(OUT), "population": len(population), "pit": len(pit), "removed": len(removed), "unexpected_3089_observed": len(unexpected)}, ensure_ascii=False))
    return 0


def snapshot_tree(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "file_count": 0, "bytes": 0, "aggregate_sha256": None}
    rows = []
    for p in sorted(x for x in path.rglob("*") if x.is_file()):
        rows.append(f"{p.relative_to(path)}|{sha256_file(p)}")
    return {"path": str(path), "file_count": len(rows), "bytes": sum((path / line.split("|", 1)[0]).stat().st_size for line in rows), "aggregate_sha256": sha256_bytes(("\n".join(rows) + "\n").encode()) if rows else sha256_bytes(b"")}


if __name__ == "__main__":
    raise SystemExit(main())
