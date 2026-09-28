#!/usr/bin/env python3
"""Portfolio-only V2 MDD re-evaluation after approved RAW_DATA_GAP exclusions."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_v2_official_adoption_revalidation_v02 as base

CURRENT_MASTER_PATH = ROOT / "data/reference/source/krx_instrument_metadata_source_snapshot_2026-09-04.json"
CURRENT_MARKET_CAP_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260922.csv"
BASELINE_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02"
CLOSURE_V01_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v01"
SCANNER_PATH = ROOT / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260922.csv"
POLICY_MODULE_PATH = ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"

# Latest locally observed exchange/feed evidence, paired with the explicit KRX
# notices below. Do not infer a formal suspension from an old cache or zero volume alone.
EXPLICIT_CURRENT_STATUS: dict[tuple[str, str], dict[str, Any]] = {
    ("005110", "KR7005110002"): {
        "current_status": "CURRENTLY_SUSPENDED",
        "cause": "CURRENTLY_SUSPENDED",
        "as_of": "2026-09-22",
        "evidence": "KRX 2026-05-06 notice says the delisting proceedings remain subject to the pending injunction; local KRX market-cap feed on 2026-09-22 has zero volume and the current scanner cache is very stale.",
        "official_source_url": "https://kind.krx.co.kr/external/2026/05/06/001170/20260506000717/91813.htm",
    },
    ("068240", "KR7068240001"): {
        "current_status": "CURRENTLY_DELISTED",
        "cause": "CURRENTLY_DELISTED",
        "as_of": "2026-09-15",
        "evidence": "KRX market actions list delisting and the start of liquidation trading following suspension release on 2026-09-15.",
        "official_source_url": "https://kind.krx.co.kr/disclosure/detailsExt.do?method=searchDetailsMktactMainExt",
    },
}

_ORIGINAL_SOURCE_CHECK = base.source_check
_ORIGINAL_GATE_BUILDER = base.build_gate_results
_ORIGINAL_CORE_SOURCE_HASHES = base.core_source_hashes
_ORIGINAL_EXECUTION_CONTRACT = base.execution_contract
_ORIGINAL_VERDICT = base.final_verdict

FALLBACK_EXCLUSIONS: dict[tuple[str, str], dict[str, Any]] = {}
BASELINE_UNRESOLVED_ROWS: list[dict[str, Any]] = []
BASELINE_UNRESOLVED_SUMMARY: list[dict[str, Any]] = []
ROOT_CAUSE_COUNTS: dict[str, int] = {}
ROOT_CAUSE_MARK_COUNTS: dict[str, int] = {}
PREPARED = False
PREPARED_INFO: dict[str, Any] = {}
POLICY_SCOPE = "V2 official adoption MDD closure 2026-09-28"
MDD_RAW_DATA_GAP_IDENTITIES = {
    pair
    for pair, metadata in base.PERMANENT_IDENTITY_EXCLUSIONS.items()
    if metadata.get("approval_scope") == POLICY_SCOPE
}
UNRESOLVED_REMAINING: list[dict[str, Any]] = []
NEW_RAW_DATA_GAP_IDENTITIES: set[tuple[str, str]] = set()

OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02"


def normalize_pair(ticker: Any, isu_cd: Any) -> tuple[str, str]:
    return str(ticker or "").strip().zfill(6), str(isu_cd or "").strip().upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def current_master_pairs(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for section in ("equity", "equity_kospi", "equity_kosdaq", "equity_konex"):
        for row in payload.get(section, []) or []:
            if not isinstance(row, Mapping):
                continue
            pair = normalize_pair(row.get("ISU_SRT_CD"), row.get("ISU_CD"))
            if pair[0].strip("0") and pair[1]:
                pairs.add(pair)
    return pairs


def read_market_cap_evidence() -> dict[str, dict[str, str]]:
    return {str(row.get("ticker", "")).zfill(6): row for row in read_csv(CURRENT_MARKET_CAP_PATH)}


def read_scanner_evidence() -> dict[str, dict[str, str]]:
    if not SCANNER_PATH.is_file():
        return {}
    return {str(row.get("ticker", "")).zfill(6): row for row in read_csv(SCANNER_PATH)}


def classify_cause(pair: tuple[str, str], reasons: Sequence[str]) -> str:
    joined = ";".join(reasons)
    if pair == ("023890", "KR7023890007") or "CORPORATE_SUCCESSOR" in joined or "SUCCESSOR" in joined:
        return "MERGER_OR_SUCCESSOR"
    status = FALLBACK_EXCLUSIONS.get(pair, {}).get("current_status")
    if status == "CURRENTLY_SUSPENDED":
        return "CURRENTLY_SUSPENDED"
    if status in {"CURRENTLY_DELISTED", "CURRENT_ROSTER_ABSENT"}:
        return "CURRENTLY_DELISTED"
    if any("RAW_ROW_NOT_PLACEHOLDER" in reason or "UNRESOLVED_DAILY_MARK" in reason for reason in reasons):
        return "RAW_DATA_GAP"
    return "OTHER"


def build_baseline_unresolved_summary() -> None:
    global BASELINE_UNRESOLVED_ROWS, BASELINE_UNRESOLVED_SUMMARY
    global ROOT_CAUSE_COUNTS, ROOT_CAUSE_MARK_COUNTS

    by_window_pair: dict[tuple[str, tuple[str, str]], list[dict[str, str]]] = defaultdict(list)
    for window_id in base.WINDOWS:
        filename = f"missing_marks_{window_id.lower().replace('-', '_')}.csv"
        for row in read_csv(BASELINE_DIR / filename):
            pair = normalize_pair(row.get("ticker"), row.get("isu_cd"))
            row = dict(row)
            row["window_id"] = window_id
            by_window_pair[(window_id, pair)].append(row)

    try:
        scanner_rows = read_scanner_evidence()
    except Exception:
        scanner_rows = {}

    summary: list[dict[str, Any]] = []
    causes_by_pair: dict[tuple[str, str], str] = {}
    reason_rows_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (window_id, pair), rows in sorted(by_window_pair.items()):
        dates = sorted(str(row.get("date", "")) for row in rows if row.get("date"))
        reasons = sorted({str(row.get("reason", "")) for row in rows if row.get("reason")})
        evidence_states = sorted({str(row.get("evidence_state", "")) for row in rows if row.get("evidence_state")})
        status_record = FALLBACK_EXCLUSIONS.get(pair)
        cause = classify_cause(pair, reasons)
        causes_by_pair.setdefault(pair, cause)
        reason_rows_by_pair[pair].extend(reasons)
        explicit_status = status_record.get("current_status") if status_record else "CURRENTLY_LISTED_OR_STATUS_UNCONFIRMED"
        in_current_master = explicit_status not in {"CURRENT_ROSTER_ABSENT", "CURRENTLY_DELISTED"}
        scan = scanner_rows.get(pair[0], {})
        summary.append({
            "window": window_id,
            "ticker": pair[0],
            "ISU_CD": pair[1],
            "unresolved_day_count": len(rows),
            "first_unresolved_date": dates[0] if dates else "",
            "last_unresolved_date": dates[-1] if dates else "",
            "current_listing_status": explicit_status,
            "currently_suspended": explicit_status == "CURRENTLY_SUSPENDED",
            "currently_delisted_or_identity_retired": explicit_status in {"CURRENTLY_DELISTED", "CURRENT_ROSTER_ABSENT"},
            "possible_cause": cause,
            "baseline_reasons": ";".join(reasons),
            "raw_evidence_states": ";".join(evidence_states),
            "in_current_krx_equity_master": in_current_master,
            "fallback_excluded": status_record is not None,
            "scanner_effective_as_of": scan.get("effective_as_of", ""),
            "scanner_freshness": scan.get("freshness_status", ""),
        })

    for pair in list(causes_by_pair):
        causes_by_pair[pair] = classify_cause(pair, reason_rows_by_pair[pair])
    BASELINE_UNRESOLVED_ROWS = [row for rows in by_window_pair.values() for row in rows]
    BASELINE_UNRESOLVED_SUMMARY = summary
    ROOT_CAUSE_COUNTS = dict(sorted(Counter(causes_by_pair.values()).items()))
    mark_counter: Counter[str] = Counter()
    for (window_id, pair), rows in by_window_pair.items():
        del window_id
        mark_counter[classify_cause(pair, reason_rows_by_pair[pair])] += len(rows)
    ROOT_CAUSE_MARK_COUNTS = dict(sorted(mark_counter.items()))


def write_permanent_exclusion_delta() -> list[dict[str, Any]]:
    baseline_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in BASELINE_UNRESOLVED_SUMMARY:
        pair = normalize_pair(row.get("ticker"), row.get("ISU_CD"))
        if pair in MDD_RAW_DATA_GAP_IDENTITIES:
            baseline_by_pair[pair].append(row)

    delta: list[dict[str, Any]] = []
    for pair in sorted(MDD_RAW_DATA_GAP_IDENTITIES):
        metadata = base.PERMANENT_IDENTITY_EXCLUSIONS[pair]
        prior_rows = baseline_by_pair.get(pair, [])
        delta.append({
            "ticker": pair[0],
            "ISU_CD": pair[1],
            **metadata,
            "action": "ADDED_TO_COMMON_PERMANENT_EXCLUSION_POLICY",
            "baseline_v01_windows": ";".join(sorted({str(row["window"]) for row in prior_rows})),
            "baseline_v01_unresolved_mark_count": sum(int(row.get("unresolved_day_count") or 0) for row in prior_rows),
            "baseline_v01_unresolved_window_count": len(prior_rows),
        })
    base.save_csv(OUT_DIR / "permanent_exclusion_delta.csv", delta)
    return delta


def collect_unresolved_remaining(
    outputs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}

    def record(pair: tuple[str, str]) -> dict[str, Any]:
        if pair not in by_pair:
            by_pair[pair] = {
                "ticker": pair[0],
                "ISU_CD": pair[1],
                "windows": set(),
                "mark_counts": Counter(),
                "event_counts": Counter(),
                "dates": set(),
                "reasons": set(),
                "evidence_states": set(),
                "raw_data_gap": False,
            }
        return by_pair[pair]

    for window_id, output in outputs.items():
        for mark in output.get("missing_marks", []):
            pair = normalize_pair(mark.get("ticker"), mark.get("isu_cd"))
            if not pair[0].strip("0") or not pair[1]:
                continue
            current = record(pair)
            current["windows"].add(str(window_id))
            current["mark_counts"][str(window_id)] += 1
            date_value = str(mark.get("date") or mark.get("valuation_date") or "")[:10]
            if date_value:
                current["dates"].add(date_value)
            reason = str(mark.get("reason") or "")
            if reason:
                current["reasons"].add(reason)
            state = str(mark.get("evidence_state") or "")
            if state:
                current["evidence_states"].add(state)
            current["raw_data_gap"] |= (
                "RAW_ROW_NOT_PLACEHOLDER" in reason
                or "UNRESOLVED_DAILY_MARK" in reason
            )

        for event in output.get("unresolved_trade_events", []):
            pair = normalize_pair(event.get("ticker"), event.get("isu_cd"))
            if not pair[0].strip("0") or not pair[1]:
                continue
            current = record(pair)
            current["windows"].add(str(window_id))
            current["event_counts"][str(window_id)] += 1
            date_value = str(event.get("execution_date") or event.get("date") or "")[:10]
            if date_value:
                current["dates"].add(date_value)
            reason = str(event.get("reason") or "")
            if reason:
                current["reasons"].add(reason)

    rows: list[dict[str, Any]] = []
    for pair, item in sorted(by_pair.items()):
        marks = item["mark_counts"]
        events = item["event_counts"]
        is_raw_gap = bool(item["raw_data_gap"])
        if is_raw_gap:
            NEW_RAW_DATA_GAP_IDENTITIES.add(pair)
        rows.append({
            "ticker": pair[0],
            "ISU_CD": pair[1],
            "classification": "RAW_DATA_GAP" if is_raw_gap else "OTHER_UNRESOLVED",
            "unresolved_daily_mark_count": sum(marks.values()),
            "unresolved_trade_event_count": sum(events.values()),
            "windows": ";".join(sorted(item["windows"])),
            "mark_counts_by_window": ";".join(f"{key}:{marks[key]}" for key in sorted(marks)),
            "event_counts_by_window": ";".join(f"{key}:{events[key]}" for key in sorted(events)),
            "first_unresolved_date": min(item["dates"]) if item["dates"] else "",
            "last_unresolved_date": max(item["dates"]) if item["dates"] else "",
            "reasons": ";".join(sorted(item["reasons"])),
            "raw_evidence_states": ";".join(sorted(item["evidence_states"])),
            "in_new_permanent_policy": pair in MDD_RAW_DATA_GAP_IDENTITIES,
        })
    return rows


def prepare() -> dict[str, Any]:
    global FALLBACK_EXCLUSIONS, PREPARED, PREPARED_INFO
    if PREPARED:
        return PREPARED_INFO

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = base.read_json(CURRENT_MASTER_PATH)
    listed_pairs = current_master_pairs(payload)
    market_cap = read_market_cap_evidence()
    scanner = read_scanner_evidence()

    ledger_rows: dict[str, list[dict[str, Any]]] = {}
    for window_id in base.WINDOWS:
        rows, _ = _ORIGINAL_SOURCE_CHECK(window_id)
        ledger_rows[window_id] = rows
    all_pairs = {
        normalize_pair(row.get("ticker"), row.get("isu_cd"))
        for rows in ledger_rows.values()
        for row in rows
    }

    exclusions: dict[tuple[str, str], dict[str, Any]] = {}
    for pair in sorted(all_pairs - listed_pairs):
        exclusions[pair] = {
            "ticker": pair[0],
            "isu_cd": pair[1],
            "current_status": "CURRENT_ROSTER_ABSENT",
            "cause": "CURRENTLY_DELISTED",
            "as_of": payload.get("source_observation_date", "2026-09-04"),
            "evidence": "Exact (ticker, ISU_CD) is absent from the KRX current listed-equity identity master; no successor was inferred.",
            "evidence_source_path": str(CURRENT_MASTER_PATH.relative_to(ROOT)),
            "official_source_url": "",
        }

    for pair, details in EXPLICIT_CURRENT_STATUS.items():
        if pair in all_pairs:
            evidence = dict(details)
            evidence["ticker"], evidence["isu_cd"] = pair
            evidence["evidence_source_path"] = str(CURRENT_MARKET_CAP_PATH.relative_to(ROOT)) if pair[0] == "005110" else "KRX KIND market action notice"
            exclusions[pair] = evidence

    FALLBACK_EXCLUSIONS = exclusions
    build_baseline_unresolved_summary()
    permanent_delta = write_permanent_exclusion_delta()
    base.save_csv(OUT_DIR / "unresolved_remaining.csv", [])

    name_by_ticker = {str(row.get("ticker", "")).zfill(6): row.get("name", "") for row in scanner.values()}
    exclusion_rows: list[dict[str, Any]] = []
    per_window_counts: dict[str, dict[str, int]] = {}
    for pair, item in sorted(FALLBACK_EXCLUSIONS.items()):
        windows = []
        row_counts: dict[str, int] = {}
        for window_id, rows in ledger_rows.items():
            count = sum(1 for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) == pair)
            if count:
                windows.append(window_id)
                row_counts[window_id] = count
        per_window_counts["|".join(pair)] = row_counts
        exclusion_rows.append({
            "ticker": pair[0],
            "ISU_CD": pair[1],
            "name_if_cached": name_by_ticker.get(pair[0], ""),
            "current_status": item["current_status"],
            "cause": item["cause"],
            "as_of": item.get("as_of", ""),
            "source_windows": ";".join(windows),
            "ledger_rows_removed": sum(row_counts.values()),
            "ledger_rows_by_window": ";".join(f"{wid}:{count}" for wid, count in row_counts.items()),
            "evidence": item.get("evidence", ""),
            "evidence_source_path": item.get("evidence_source_path", ""),
            "official_source_url": item.get("official_source_url", ""),
            "current_market_cap_feed_volume": market_cap.get(pair[0], {}).get("volume", ""),
            "scanner_effective_as_of": scanner.get(pair[0], {}).get("effective_as_of", ""),
            "scanner_freshness": scanner.get(pair[0], {}).get("freshness_status", ""),
        })

    base.save_csv(OUT_DIR / "fallback_exclusions.csv", exclusion_rows)
    base.save_csv(OUT_DIR / "unresolved_identity_summary.csv", BASELINE_UNRESOLVED_SUMMARY)
    PREPARED_INFO = {
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_roster_absent_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENT_ROSTER_ABSENT"),
        "fallback_suspended_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENTLY_SUSPENDED"),
        "fallback_official_delisted_count": sum(1 for item in FALLBACK_EXCLUSIONS.values() if item["current_status"] == "CURRENTLY_DELISTED"),
        "baseline_unresolved_mark_rows": len(BASELINE_UNRESOLVED_ROWS),
        "baseline_unresolved_window_identity_count": len(BASELINE_UNRESOLVED_SUMMARY),
        "baseline_unresolved_identity_count": len({(row["ticker"], row["ISU_CD"]) for row in BASELINE_UNRESOLVED_SUMMARY}),
        "baseline_root_causes_by_identity": ROOT_CAUSE_COUNTS,
        "baseline_root_causes_by_mark": ROOT_CAUSE_MARK_COUNTS,
        "new_permanent_exclusion_count": len(permanent_delta),
        "permanent_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "filtered_ledger_rows_by_window": per_window_counts,
    }
    PREPARED = True
    return PREPARED_INFO


def filtered_source_check(window_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, details = _ORIGINAL_SOURCE_CHECK(window_id)
    removed = [row for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) in FALLBACK_EXCLUSIONS]
    kept = [row for row in rows if normalize_pair(row.get("ticker"), row.get("isu_cd")) not in FALLBACK_EXCLUSIONS]
    details["current_status_fallback_filter"] = "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK"
    details["current_status_fallback_identity_count"] = len({normalize_pair(row.get("ticker"), row.get("isu_cd")) for row in removed})
    details["current_status_fallback_rows_removed"] = len(removed)
    details["rows_after_current_status_fallback"] = len(kept)
    return kept, details


def closure_gate_results(
    window_id: str,
    metrics: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    unresolved_events: Sequence[Mapping[str, Any]],
    missing_marks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    previous = _ORIGINAL_GATE_BUILDER(window_id, metrics, issues, unresolved_events, missing_marks)
    result = [dict(item) for item in previous if item["gate"] in {"A", "B", "C", "D"}]
    validity = next(dict(item) for item in previous if item["gate"] == "F")
    validity["gate"] = "E"
    validity["detail"] = f"portfolio_result_validity: {validity['detail']}"
    result.append(validity)
    return result


def closure_source_hashes(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    value = _ORIGINAL_CORE_SOURCE_HASHES(results)
    source_paths = [
        CURRENT_MASTER_PATH,
        CURRENT_MARKET_CAP_PATH,
        SCANNER_PATH,
        CLOSURE_V01_DIR / "unresolved_identity_summary.csv",
        *(BASELINE_DIR / f"missing_marks_{window.lower().replace('-', '_')}.csv" for window in base.WINDOWS),
        *(BASELINE_DIR / f"unresolved_events_{window.lower().replace('-', '_')}.csv" for window in base.WINDOWS),
    ]
    value["mdd_closure_v02"] = {
        "script": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": base.sha256_file(Path(__file__).resolve())},
        "permanent_exclusion_policy_path": str(POLICY_MODULE_PATH.relative_to(ROOT)),
        "permanent_exclusion_policy_sha256": base.sha256_file(POLICY_MODULE_PATH),
        "permanent_exclusion_policy_version": "permanent_identity_exclusions_v01",
        "permanent_exclusion_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "permanent_exclusion_delta_count": len(MDD_RAW_DATA_GAP_IDENTITIES),
        "permanent_exclusion_delta_path": str((OUT_DIR / "permanent_exclusion_delta.csv").relative_to(ROOT)),
        "permanent_exclusion_delta_sha256": base.sha256_file(OUT_DIR / "permanent_exclusion_delta.csv"),
        "unresolved_remaining_path": str((OUT_DIR / "unresolved_remaining.csv").relative_to(ROOT)),
        "unresolved_remaining_sha256": base.sha256_file(OUT_DIR / "unresolved_remaining.csv"),
        "execution_contract_path": str((OUT_DIR / "execution_contract.json").relative_to(ROOT)),
        "execution_contract_sha256": base.sha256_file(OUT_DIR / "execution_contract.json"),
        "fallback_exclusion_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_exclusions_path": str((OUT_DIR / "fallback_exclusions.csv").relative_to(ROOT)),
        "fallback_exclusions_sha256": base.sha256_file(OUT_DIR / "fallback_exclusions.csv"),
        "unresolved_identity_summary_path": str((OUT_DIR / "unresolved_identity_summary.csv").relative_to(ROOT)),
        "unresolved_identity_summary_sha256": base.sha256_file(OUT_DIR / "unresolved_identity_summary.csv"),
        "status_evidence_sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": base.sha256_file(path)}
            for path in source_paths
        ],
        "portfolio_output_artifacts": [
            {"path": str(path.relative_to(ROOT)), "sha256": base.sha256_file(path)}
            for path in sorted(OUT_DIR.iterdir())
            if path.is_file() and path.name != "source_hashes.json"
        ],
        "portfolio_frame_hashes_reconstructed_from_saved_outputs": False,
        "official_status_notice_urls": {"005110|KR7005110002": EXPLICIT_CURRENT_STATUS[("005110", "KR7005110002")]["official_source_url"], "068240|KR7068240001": EXPLICIT_CURRENT_STATUS[("068240", "KR7068240001")]["official_source_url"]},
        "survivorship_bias_fallback_used": True,
        "signal_regeneration": False,
        "strategy_evaluation_rerun": False,
    }
    return value


def closure_execution_contract() -> dict[str, Any]:
    value = _ORIGINAL_EXECUTION_CONTRACT()
    value.update({
        "schema": "pattern_a_fast_v2_official_adoption_mdd_closure_execution_contract_v02",
        "mode": "EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY",
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
        "portfolio_universe_filter": [
            "COMMON_PERMANENT_EXACT_IDENTITY_EXCLUSIONS",
            "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        ],
        "permanent_exclusion_policy_modified": True,
        "permanent_exclusion_policy_version": "permanent_identity_exclusions_v01",
        "permanent_exclusion_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "permanent_exclusion_delta_count": len(MDD_RAW_DATA_GAP_IDENTITIES),
        "permanent_exclusion_delta_scope": POLICY_SCOPE,
        "permanent_exclusion_delta_path": str((OUT_DIR / "permanent_exclusion_delta.csv").relative_to(ROOT)),
        "current_status_fallback_is_separate_from_permanent_policy": True,
        "current_status_fallback_promotion_approved": False,
        "fallback_filter_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_filter_exact_identity_key": ["ticker", "ISU_CD"],
        "fallback_filter_evidence": "Current KRX listed-equity identity master absence, plus the two listed explicit KRX current-status notices in fallback_exclusions.csv. Zero volume or stale cache alone is not sufficient evidence.",
        "survivorship_bias_fallback_used": True,
        "survivorship_bias_acknowledged": "This filter excludes identities based on current status, so historical results are survivorship biased and are not represented as an unbiased historical simulation.",
    })
    return value


def closure_verdict(gates: Sequence[Mapping[str, Any]]) -> str:
    return _ORIGINAL_VERDICT(gates)


def closure_render_report(
    verdict: str,
    metrics: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
    source_hashes: Mapping[str, Any],
    plan_commit: str,
    result_commit: str | None = None,
    head: str | None = None,
    origin_main: str | None = None,
    worktree_clean: bool | None = None,
) -> str:
    del references, source_hashes
    gate_by_window: dict[str, dict[str, str]] = defaultdict(dict)
    for item in gates:
        gate_by_window[str(item["window_id"])][str(item["gate"])] = str(item["status"])

    lines = [
        "# V2 RAW_DATA_GAP 영구 제외 후 MDD 재평가",
        "",
        f"- 최종 판정: **{verdict}**",
        f"- 기준 계획 commit: `{plan_commit}`",
        f"- 결과 commit: `{result_commit or 'SHA는 r.md 참고'}`",
        f"- 종료 HEAD / origin/main: `{head or 'push 후 r.md에 확인 기록'}` / `{origin_main or 'push 후 r.md에 확인 기록'}`; clean: `{worktree_clean if worktree_clean is not None else 'push 후 확인 기록'}`",
        f"- 승인 정책 commit: `d3a7aced`",
        f"- 기존 V02 baseline은 보존: `{BASELINE_DIR.relative_to(ROOT)}`",
        "- 실행 모드: `EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY`; entry signal regeneration=false; strategy evaluation rerun=false; price-frame workers=10.",
        "- 현재 상태 fallback은 permanent 정책으로 승격하지 않았고, 이번 재평가에 별도로 적용했어. 따라서 결과는 생존편향이 있어.",
        "",
        "## 진단 및 fallback 범위",
        "",
        f"- V02 unresolved mark: {len(BASELINE_UNRESOLVED_ROWS)} window-day rows, {len(BASELINE_UNRESOLVED_SUMMARY)} window-identity groups, {len({(row['ticker'], row['ISU_CD']) for row in BASELINE_UNRESOLVED_SUMMARY})} 고유 identity.",
        f"- 원인별 고유 identity: `{ROOT_CAUSE_COUNTS}`.",
        f"- 원인별 unresolved mark 수: `{ROOT_CAUSE_MARK_COUNTS}`.",
        f"- 공통 permanent 정책은 기존 43개와 승인된 RAW_DATA_GAP 66개, 총 {len(base.PERMANENT_IDENTITY_EXCLUSIONS)} exact identities야.",
        f"- delta 66개는 `permanent_exclusion_delta.csv`에 기록했어. CURRENT_ROSTER_ABSENT 136개와 현재 거래정지/상폐 fallback은 permanent 목록에 넣지 않았어.",
        f"- fallback 제외: {len(FALLBACK_EXCLUSIONS)} exact identities — KRX current master 부재 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENT_ROSTER_ABSENT')}, 명시적 현재 거래정지 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENTLY_SUSPENDED')}, 명시적 현재 상폐 {sum(1 for x in FALLBACK_EXCLUSIONS.values() if x['current_status'] == 'CURRENTLY_DELISTED')}.",
        "- current-status fallback은 영구 정책과 분리했어. 기존 placeholder carry·비용·현금 규칙 및 인증 원장은 유지했고 신호/전략은 재생성하지 않았어.",
        "- 거래량 0 또는 오래된 scanner cache만으로 거래정지 판정을 추가하지 않았어.",
        "",
        "## 5개 표준 기간 재평가",
        "",
        "| 기간 | 총수익률 | CAGR | MDD | peak | trough | recovery | unresolved marks | 현금 부족률(참고) | A | B | C | D | E |",
        "|---|---:|---:|---:|---|---|---|---:|---:|---|---|---|---|---|",
    ]

    def fmt(value: Any) -> str:
        return "미산출" if value is None else f"{float(value):.2f}%"

    for row in metrics:
        wid = str(row["window_id"])
        gate = gate_by_window.get(wid, {})
        lines.append("| " + " | ".join([
            wid,
            fmt(row.get("total_return_pct")),
            fmt(row.get("cagr_pct")),
            fmt(row.get("mdd_pct")),
            str(row.get("mdd_peak_date") or "N/A"),
            str(row.get("mdd_trough_date") or "N/A"),
            str(row.get("mdd_recovery_date") or "미회복"),
            str(row.get("valuation_unresolved_count", row.get("unresolved_count", ""))),
            fmt(row.get("cash_shortage_skip_rate_pct")),
            *(gate.get(key, "CHECK_REQUIRED") for key in "ABCDE"),
        ]) + " |")

    lines.extend([
        "",
        "현금 부족률은 참고 진단으로만 표시했고 A~E 판정에는 넣지 않았어. MDD 통과 기준은 -35% 이상이야.",
        "",
        "## 재평가 후 남은 미해결",
        "",
        f"- 미해결 identity: {len(UNRESOLVED_REMAINING)}개; 새 RAW_DATA_GAP exact identity: {len(NEW_RAW_DATA_GAP_IDENTITIES)}개.",
        "- identity별 기간·일수·날짜·근거는 `unresolved_remaining.csv`에 있어. 새 identity는 자동 영구 제외하거나 반복 실행하지 않았어.",
    ])
    if NEW_RAW_DATA_GAP_IDENTITIES:
        lines.extend(["", "| ticker | ISU_CD | window | unresolved mark days | first date | last date |", "|---|---|---|---:|---|---|"])
        for row in UNRESOLVED_REMAINING:
            if row["classification"] == "RAW_DATA_GAP":
                lines.append(f"| {row['ticker']} | {row['ISU_CD']} | {row['windows']} | {row['unresolved_daily_mark_count']} | {row['first_unresolved_date']} | {row['last_unresolved_date']} |")
    lines.extend([
        "",
        "## A~E 상세 판정",
        "",
    ])
    for item in gates:
        lines.append(f"- {item['window_id']} {item['gate']}: **{item['status']}** — {item['detail']}")
    lines.extend([
        "",
        "## 현재 상태 근거와 해석",
        "",
        f"- KRX 현재 상장 종목 원천: `{CURRENT_MASTER_PATH.relative_to(ROOT)}` (관측일 2026-09-04); KRX 시가총액 일별 원천: `{CURRENT_MARKET_CAP_PATH.relative_to(ROOT)}` (2026-09-22).",
        "- 005110 한창: KRX 2026-05-06 안내에는 상장폐지 결정 효력정지 가처분 결과에 따라 후속 절차가 진행된다고 되어 있고, 2026-09-22 로컬 KRX 시세 snapshot은 거래량 0이어서 현재 거래정지 fallback으로 분류했어.",
        "- 068240 다원시스: KRX 시장조치 목록에 2026-09-15 상장폐지 및 정리매매 개시 관련 조치가 기록되어 있어 현재 상폐 fallback으로 분류했어.",
        "- 그 외 KRX 현재 상장 equity master에 없는 identity는 `CURRENT_ROSTER_ABSENT`로 기록했어. 이는 현재 exact identity가 목록에 없다는 근거이며 successor 연결을 새로 추정하지 않았어.",
        "",
        "## 재현 정보",
        "",
        f"- 실행 계약: `{(OUT_DIR / 'execution_contract.json').relative_to(ROOT)}`.",
        f"- 원천 해시: `{(OUT_DIR / 'source_hashes.json').relative_to(ROOT)}`.",
        f"- delta 및 unresolved 목록: `{(OUT_DIR / 'permanent_exclusion_delta.csv').relative_to(ROOT)}`; `{(OUT_DIR / 'unresolved_remaining.csv').relative_to(ROOT)}`.",
        f"- 기간별 일별 equity, 거래, 현금, carry, missing mark 및 unresolved event CSV는 `{OUT_DIR.relative_to(ROOT)}`에 있어.",
        "",
    ])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    global UNRESOLVED_REMAINING
    prepared = prepare()
    base.OUT_DIR = OUT_DIR
    base.source_check = filtered_source_check
    base.build_gate_results = closure_gate_results
    base.core_source_hashes = closure_source_hashes
    base.execution_contract = closure_execution_contract
    base.final_verdict = closure_verdict
    base.render_report = closure_render_report
    result = base.run_full()

    UNRESOLVED_REMAINING = collect_unresolved_remaining(result["outputs"])
    base.save_csv(OUT_DIR / "unresolved_remaining.csv", UNRESOLVED_REMAINING)
    unresolved_mark_count = sum(int(row["unresolved_daily_mark_count"]) for row in UNRESOLVED_REMAINING)
    unresolved_event_count = sum(int(row["unresolved_trade_event_count"]) for row in UNRESOLVED_REMAINING)
    raw_gap_mark_count = sum(
        int(row["unresolved_daily_mark_count"])
        for row in UNRESOLVED_REMAINING
        if row["classification"] == "RAW_DATA_GAP"
    )
    contract = base.read_json(OUT_DIR / "execution_contract.json")
    contract.update({
        "unresolved_remaining_path": str((OUT_DIR / "unresolved_remaining.csv").relative_to(ROOT)),
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_daily_mark_count": unresolved_mark_count,
        "unresolved_trade_event_count": unresolved_event_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": [
            {"ticker": ticker, "ISU_CD": isu_cd}
            for ticker, isu_cd in sorted(NEW_RAW_DATA_GAP_IDENTITIES)
        ],
        "automatic_follow_up_exclusion_or_rerun": False,
    })
    base.save_json(OUT_DIR / "execution_contract.json", contract)
    source_hashes = closure_source_hashes(result["outputs"])
    base.save_json(OUT_DIR / "source_hashes.json", source_hashes)

    result_summary = dict(result["summary"])
    result_summary.update({
        "schema": "pattern_a_fast_v2_official_adoption_mdd_closure_summary_v02",
        "survivorship_bias_fallback_used": True,
        "verdict_with_flag": f"{result['verdict']}_WITH_SURVIVORSHIP_BIAS_FALLBACK_USED",
        "fallback_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_identity_status_counts": dict(sorted(Counter(str(item["current_status"]) for item in FALLBACK_EXCLUSIONS.values()).items())),
        "permanent_exclusion_policy_modified": True,
        "permanent_exclusion_policy_version": "permanent_identity_exclusions_v01",
        "permanent_exclusion_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "permanent_exclusion_delta_count": len(MDD_RAW_DATA_GAP_IDENTITIES),
        "permanent_exclusion_delta_scope": POLICY_SCOPE,
        "permanent_exclusion_delta_path": str((OUT_DIR / "permanent_exclusion_delta.csv").relative_to(ROOT)),
        "baseline_unresolved_mark_rows": prepared["baseline_unresolved_mark_rows"],
        "baseline_unresolved_window_identity_count": prepared["baseline_unresolved_window_identity_count"],
        "baseline_unresolved_identity_count": prepared["baseline_unresolved_identity_count"],
        "baseline_unresolved_cause_counts_by_identity": ROOT_CAUSE_COUNTS,
        "baseline_unresolved_cause_counts_by_mark": ROOT_CAUSE_MARK_COUNTS,
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_remaining_mark_count": unresolved_mark_count,
        "unresolved_remaining_trade_event_count": unresolved_event_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": [
            {"ticker": ticker, "ISU_CD": isu_cd}
            for ticker, isu_cd in sorted(NEW_RAW_DATA_GAP_IDENTITIES)
        ],
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
        "source_hashes_path": str((OUT_DIR / "source_hashes.json").relative_to(ROOT)),
        "execution_contract_path": str((OUT_DIR / "execution_contract.json").relative_to(ROOT)),
    })
    base.save_json(OUT_DIR / "summary.json", result_summary)
    (OUT_DIR / "report.md").write_text(
        closure_render_report(result["verdict"], result["metrics"], result["gates"], result["references"], source_hashes, base.PLAN_COMMIT),
        encoding="utf-8",
    )
    result["summary"] = result_summary
    result["source_hashes"] = source_hashes
    print(base.json.dumps({
        "verdict": result["verdict"],
        "survivorship_bias_fallback_used": True,
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_status_counts": result_summary["fallback_identity_status_counts"],
        "permanent_exclusion_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "permanent_exclusion_delta_count": len(MDD_RAW_DATA_GAP_IDENTITIES),
        "baseline_unresolved_identity_count": prepared["baseline_unresolved_identity_count"],
        "baseline_unresolved_cause_counts_by_identity": ROOT_CAUSE_COUNTS,
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_remaining_mark_count": unresolved_mark_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": sorted(NEW_RAW_DATA_GAP_IDENTITIES),
        "window_metrics": [
            {
                key: row.get(key)
                for key in (
                    "window_id",
                    "total_return_pct",
                    "cagr_pct",
                    "mdd_pct",
                    "mdd_peak_date",
                    "mdd_trough_date",
                    "mdd_recovery_date",
                    "valuation_unresolved_count",
                    "cash_shortage_skip_rate_pct",
                )
            }
            for row in result["metrics"]
        ],
        "gate_results": result["gates"],
        "total_wall_seconds": result_summary["total_wall_seconds"],
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return result


def cast_saved_metric_row(row: Mapping[str, str]) -> dict[str, Any]:
    date_fields = {
        "effective_start",
        "effective_end",
        "execution_support",
        "mdd_peak_date",
        "mdd_trough_date",
        "mdd_recovery_date",
    }
    string_fields = {"window_id", "open_at_cutoff_candidate_ids"}
    result: dict[str, Any] = {}
    for key, value in row.items():
        if value == "" or value.lower() in {"nan", "none"}:
            result[key] = None
        elif key in date_fields or key in string_fields:
            result[key] = value
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                result[key] = value
            else:
                result[key] = int(number) if number.is_integer() else number
    return result


def finalize_existing() -> dict[str, Any]:
    """Build reports and hashes from completed on-disk outputs without replaying a portfolio."""
    global UNRESOLVED_REMAINING
    required = [OUT_DIR / "window_metrics.csv", OUT_DIR / "gate_results.csv"]
    for window_id in base.WINDOWS:
        suffix = window_id.lower().replace("-", "_")
        required.extend([
            OUT_DIR / f"daily_equity_{suffix}.csv",
            OUT_DIR / f"valuation_carry_audit_{suffix}.csv",
            OUT_DIR / f"missing_marks_{suffix}.csv",
            OUT_DIR / f"unresolved_events_{suffix}.csv",
        ])
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"COMPLETED_PORTFOLIO_OUTPUTS_MISSING:{missing}")

    prepared = prepare()
    metrics = [cast_saved_metric_row(row) for row in read_csv(OUT_DIR / "window_metrics.csv")]
    gates = read_csv(OUT_DIR / "gate_results.csv")
    outputs: dict[str, dict[str, Any]] = {}
    source_certification: dict[str, dict[str, Any]] = {}
    for window_id in base.WINDOWS:
        suffix = window_id.lower().replace("-", "_")
        _rows, source_details = filtered_source_check(window_id)
        source_certification[window_id] = source_details
        outputs[window_id] = {
            "source_details": source_details,
            "frame_hashes": {},
            "valuation_carry_audit": read_csv(OUT_DIR / f"valuation_carry_audit_{suffix}.csv"),
            "missing_marks": read_csv(OUT_DIR / f"missing_marks_{suffix}.csv"),
            "unresolved_trade_events": read_csv(OUT_DIR / f"unresolved_events_{suffix}.csv"),
        }

    UNRESOLVED_REMAINING = collect_unresolved_remaining(outputs)
    base.save_csv(OUT_DIR / "unresolved_remaining.csv", UNRESOLVED_REMAINING)
    unresolved_mark_count = sum(int(row["unresolved_daily_mark_count"]) for row in UNRESOLVED_REMAINING)
    unresolved_event_count = sum(int(row["unresolved_trade_event_count"]) for row in UNRESOLVED_REMAINING)
    raw_gap_mark_count = sum(
        int(row["unresolved_daily_mark_count"])
        for row in UNRESOLVED_REMAINING
        if row["classification"] == "RAW_DATA_GAP"
    )

    contract = base.read_json(OUT_DIR / "execution_contract.json")
    contract.update({
        "unresolved_remaining_path": str((OUT_DIR / "unresolved_remaining.csv").relative_to(ROOT)),
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_daily_mark_count": unresolved_mark_count,
        "unresolved_trade_event_count": unresolved_event_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": [
            {"ticker": ticker, "ISU_CD": isu_cd}
            for ticker, isu_cd in sorted(NEW_RAW_DATA_GAP_IDENTITIES)
        ],
        "automatic_follow_up_exclusion_or_rerun": False,
        "post_run_finalization_mode": "SAVED_PORTFOLIO_OUTPUTS_NO_REPLAY",
    })
    base.save_json(OUT_DIR / "execution_contract.json", contract)

    references = {
        period: base.reference_metrics(ROOT / path)
        for period, path in base.REFERENCE_SUMMARIES.items()
    }
    verdict = closure_verdict(gates)
    summary = {
        "schema": "pattern_a_fast_v2_official_adoption_mdd_closure_summary_v02",
        "strategy_id": base.STRATEGY_ID,
        "verdict": verdict,
        "plan_commit": base.PLAN_COMMIT,
        "plan_sha256": base.PLAN_SHA256,
        "price_frame_workers": base.WORKERS,
        "portfolio_event_workers": 1,
        "metrics_by_window": {row["window_id"]: row for row in metrics},
        "gate_results": gates,
        "source_certification": source_certification,
        "reference_only_market_cap_1t_results": references,
        "valuation_carry_audit": {
            window_id: {
                "rows": len(outputs[window_id]["valuation_carry_audit"]),
                "applied": metrics_by_window_value(metrics, window_id, "valuation_carry_count"),
                "unresolved_daily_marks": metrics_by_window_value(metrics, window_id, "valuation_unresolved_count"),
            }
            for window_id in base.WINDOWS
        },
        "source_hashes_path": str((OUT_DIR / "source_hashes.json").relative_to(ROOT)),
        "execution_contract_path": str((OUT_DIR / "execution_contract.json").relative_to(ROOT)),
        "total_wall_seconds": None,
        "total_wall_seconds_note": "The completed runner did not persist total wall time before report finalization failed.",
        "post_run_finalization_mode": "SAVED_PORTFOLIO_OUTPUTS_NO_REPLAY",
        "survivorship_bias_fallback_used": True,
        "verdict_with_flag": f"{verdict}_WITH_SURVIVORSHIP_BIAS_FALLBACK_USED",
        "fallback_filter": "CURRENT_STATUS_SUSPENDED_DELISTED_FALLBACK",
        "fallback_identity_count": len(FALLBACK_EXCLUSIONS),
        "fallback_identity_status_counts": dict(sorted(Counter(str(item["current_status"]) for item in FALLBACK_EXCLUSIONS.values()).items())),
        "permanent_exclusion_policy_modified": True,
        "permanent_exclusion_policy_version": "permanent_identity_exclusions_v01",
        "permanent_exclusion_policy_total_count": len(base.PERMANENT_IDENTITY_EXCLUSIONS),
        "permanent_exclusion_delta_count": len(MDD_RAW_DATA_GAP_IDENTITIES),
        "permanent_exclusion_delta_scope": POLICY_SCOPE,
        "permanent_exclusion_delta_path": str((OUT_DIR / "permanent_exclusion_delta.csv").relative_to(ROOT)),
        "baseline_unresolved_mark_rows": prepared["baseline_unresolved_mark_rows"],
        "baseline_unresolved_window_identity_count": prepared["baseline_unresolved_window_identity_count"],
        "baseline_unresolved_identity_count": prepared["baseline_unresolved_identity_count"],
        "baseline_unresolved_cause_counts_by_identity": ROOT_CAUSE_COUNTS,
        "baseline_unresolved_cause_counts_by_mark": ROOT_CAUSE_MARK_COUNTS,
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_remaining_mark_count": unresolved_mark_count,
        "unresolved_remaining_trade_event_count": unresolved_event_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": [
            {"ticker": ticker, "ISU_CD": isu_cd}
            for ticker, isu_cd in sorted(NEW_RAW_DATA_GAP_IDENTITIES)
        ],
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
    }

    base.save_json(OUT_DIR / "summary.json", summary)
    (OUT_DIR / "report.md").write_text(
        closure_render_report(verdict, metrics, gates, references, {}, base.PLAN_COMMIT),
        encoding="utf-8",
    )
    source_hashes = closure_source_hashes(outputs)
    source_hashes["mdd_closure_v02"]["post_run_finalization_mode"] = "SAVED_PORTFOLIO_OUTPUTS_NO_REPLAY"
    source_hashes["mdd_closure_v02"]["daily_frame_hashes_available_from_saved_runner"] = False
    base.save_json(OUT_DIR / "source_hashes.json", source_hashes)
    print(base.json.dumps({
        "verdict": verdict,
        "post_run_finalization_mode": "SAVED_PORTFOLIO_OUTPUTS_NO_REPLAY",
        "unresolved_remaining_identity_count": len(UNRESOLVED_REMAINING),
        "unresolved_remaining_mark_count": unresolved_mark_count,
        "new_raw_data_gap_identity_count": len(NEW_RAW_DATA_GAP_IDENTITIES),
        "new_raw_data_gap_mark_count": raw_gap_mark_count,
        "new_raw_data_gap_identities": sorted(NEW_RAW_DATA_GAP_IDENTITIES),
        "window_metrics": [
            {
                key: row.get(key)
                for key in (
                    "window_id",
                    "total_return_pct",
                    "cagr_pct",
                    "mdd_pct",
                    "mdd_peak_date",
                    "mdd_trough_date",
                    "mdd_recovery_date",
                    "valuation_unresolved_count",
                    "cash_shortage_skip_rate_pct",
                )
            }
            for row in metrics
        ],
        "gate_statuses": {
            window_id: {
                str(row["gate"]): str(row["status"])
                for row in gates
                if row["window_id"] == window_id
            }
            for window_id in base.WINDOWS
        },
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return {
        "verdict": verdict,
        "summary": summary,
        "metrics": metrics,
        "gates": gates,
        "outputs": outputs,
        "references": references,
        "source_hashes": source_hashes,
    }


def metrics_by_window_value(
    metrics: Sequence[Mapping[str, Any]],
    window_id: str,
    key: str,
) -> Any:
    return next((row.get(key) for row in metrics if row.get("window_id") == window_id), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Prepare and report the exact status filter and compressed baseline gaps only.")
    group.add_argument("--run", action="store_true", help="Run five portfolio-only V2 re-evaluations using the status fallback.")
    group.add_argument("--finalize-existing", action="store_true", help="Build summaries from completed window CSVs without replaying portfolios.")
    args = parser.parse_args()
    if not base.PLAN_PATH.is_file() or base.sha256_file(base.PLAN_PATH) != base.PLAN_SHA256:
        raise RuntimeError("SEALED_PLAN_MISSING_OR_HASH_MISMATCH")
    if args.preflight:
        info = prepare()
        print(base.json.dumps(info, ensure_ascii=False, indent=2, default=str), flush=True)
    elif args.finalize_existing:
        finalize_existing()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
