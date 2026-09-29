#!/usr/bin/env python3
"""Refine the committed V02 ETF representatives without refreshing market data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_V02 = ROOT / "artifacts/research/etf_official_universe_refinement_v02"
DEFAULT_OUTPUT = ROOT / "artifacts/research/etf_official_universe_refinement_v03"
NEAR_TURNOVER_RELATIVE_TOLERANCE = 0.01
EXPECTED_REFERENCE_DATE = "2026-09-23"
EXPECTED_40D_START = "2026-07-29"
EXPECTED_40D_END = "2026-09-23"
EXPECTED_40D_SESSIONS = 40

V02_FILES = (
    "all_current_etf_snapshot.csv",
    "classified_universe.csv",
    "comparison_vs_existing_ranking_24.csv",
    "eligible_candidates.csv",
    "excluded_audit.csv",
    "official_representative_etf_universe.csv",
    "summary.md",
    "validation.json",
)
UNIVERSE_FIELDS = (
    "major_category",
    "representative_group",
    "ticker",
    "ETF_name",
    "listing_date",
    "close",
    "avg_volume_40d",
    "avg_trading_value_40d",
    "product_management_type",
    "selection_reason",
    "change_from_v02",
    "AUM_if_available",
    "tracking_quality_if_available",
)
CHANGE_FIELDS = (
    "change_type",
    "major_category",
    "representative_group",
    "before_ticker",
    "before_ETF_name",
    "after_ticker",
    "after_ETF_name",
    "reason",
)
ACTIVE_AUDIT_FIELDS = (
    "major_category",
    "representative_group",
    "removed_ticker",
    "removed_ETF_name",
    "product_management_type",
    "replacement_ticker",
    "replacement_ETF_name",
    "selection_reason",
)
OVERLAP_AUDIT_FIELDS = (
    "major_category",
    "parent_group",
    "parent_ticker",
    "parent_ETF_name",
    "child_groups",
    "child_tickers",
    "action",
    "reason",
)

# These are the unambiguous broad-sector/industry overlaps explicitly named by
# the work instruction. Children are retained; only the broad representative
# is removed.
PARENT_CHILD_GROUPS = {
    "FINANCIALS": ("BANK", "SECURITIES", "INSURANCE"),
    "INFORMATION_TECHNOLOGY": ("SEMICONDUCTOR", "SOFTWARE"),
}
PARENT_REMOVAL_REASONS = {
    "FINANCIALS": "Removed the broad financial-sector representative because BANK, SECURITIES, and INSURANCE are retained as separate child groups.",
    "INFORMATION_TECHNOLOGY": "Removed the broad IT representative because SEMICONDUCTOR and SOFTWARE are retained as separate child groups.",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def product_management_type(metadata: dict[str, Any]) -> str:
    """Map the official KRX replication-method label to ACTIVE or PASSIVE."""
    label = str(metadata.get("ETF_REPLICA_METHD_TP_CD", "") or "").strip()
    upper = label.upper()
    if "액티브" in label or "ACTIVE" in upper:
        return "ACTIVE"
    if "패시브" in label or "PASSIVE" in upper:
        return "PASSIVE"
    return "UNKNOWN"


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hard_filter_pass(metadata: dict[str, Any]) -> bool:
    failed = str(metadata.get("failed_filter", "") or "").strip()
    passed = str(metadata.get("hard_filter_pass", "")).strip().lower()
    return not failed and passed in {"true", "1", "yes"}


def select_passive_candidate(
    candidates: list[dict[str, str]],
    classified_by_ticker: dict[str, dict[str, str]],
) -> tuple[dict[str, str], str] | None:
    """Select from existing V02 eligible rows with the V02 ranking rules."""
    passive: list[tuple[dict[str, str], dict[str, str]]] = []
    for candidate in candidates:
        ticker = str(candidate["ticker"])
        metadata = classified_by_ticker.get(ticker)
        if metadata is None:
            raise ValueError(f"CLASSIFICATION_MISSING:{ticker}")
        if (
            str(metadata.get("major_category", "")) != str(candidate.get("major_category", ""))
            or str(metadata.get("representative_group", "")) != str(candidate.get("representative_group", ""))
        ):
            raise ValueError(f"CANDIDATE_CLASSIFICATION_MISMATCH:{ticker}")
        product_type = product_management_type(metadata)
        if product_type == "UNKNOWN":
            raise ValueError(f"PRODUCT_MANAGEMENT_TYPE_UNKNOWN:{ticker}")
        if not _hard_filter_pass(metadata):
            raise ValueError(f"ELIGIBLE_CANDIDATE_HARD_FILTER_FAILURE:{ticker}")
        if product_type == "PASSIVE":
            passive.append((candidate, metadata))

    if not passive:
        return None

    category = str(passive[0][0].get("major_category", ""))
    pool = passive
    if category == "COMMODITY_RESOURCE":
        spot = [item for item in passive if item[1].get("product_structure") == "PLAIN_LONG_SPOT"]
        if spot:
            pool = spot

    def turnover(item: tuple[dict[str, str], dict[str, str]]) -> float:
        value = _float_or_none(item[0].get("avg_trading_value_40d"))
        return value if value is not None else float("-inf")

    top_turnover = max(turnover(item) for item in pool)
    near_tie = [
        item for item in pool
        if turnover(item) >= top_turnover * (1.0 - NEAR_TURNOVER_RELATIVE_TOLERANCE)
    ]
    used_aum_tie_break = len(near_tie) > 1

    def rank_key(item: tuple[dict[str, str], dict[str, str]]) -> tuple[float, str, float, str]:
        candidate, _metadata = item
        aum = _float_or_none(candidate.get("AUM_if_available"))
        listing_date = str(candidate.get("listing_date", "9999-12-31")) or "9999-12-31"
        # Higher AUM wins; then older listing date; remaining ties use turnover
        # and ticker, matching the deterministic V02 tie behavior.
        return (
            -(aum if aum is not None else float("-inf")),
            listing_date,
            -turnover(item),
            str(candidate.get("ticker", "")),
        )

    winner, metadata = sorted(near_tie, key=rank_key)[0]
    reasons: list[str] = []
    if category == "COMMODITY_RESOURCE" and metadata.get("product_structure") == "PLAIN_LONG_SPOT":
        reasons.append("Eligible spot product preferred over futures under V02 rules.")
    if used_aum_tie_break:
        reasons.append("Among passive candidates within 1% of top 40D average trading value, the largest available AUM proxy wins; listing age breaks ties.")
    else:
        reasons.append("Highest 40D average trading value among existing V02 eligible passive candidates; AUM and listing age break ties.")
    return winner, " ".join(reasons)


def _universe_row(
    *,
    major_category: str,
    group: str,
    ticker: str,
    name: str,
    listing_date: str,
    close: str,
    avg_volume: str,
    avg_trading_value: str,
    product_type: str,
    selection_reason: str,
    change: str,
    aum: str = "",
    tracking_quality: str = "",
) -> dict[str, str]:
    return {
        "major_category": major_category,
        "representative_group": group,
        "ticker": ticker,
        "ETF_name": name,
        "listing_date": listing_date,
        "close": close,
        "avg_volume_40d": avg_volume,
        "avg_trading_value_40d": avg_trading_value,
        "product_management_type": product_type,
        "selection_reason": selection_reason,
        "change_from_v02": change,
        "AUM_if_available": aum,
        "tracking_quality_if_available": tracking_quality,
    }


def _hash_v02_files(v02_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for filename in V02_FILES:
        path = v02_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"V02_AUTHORITY_FILE_MISSING:{filename}")
        hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def build_v03(v02_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Build V03 from committed V02 snapshots; never fetch or recompute metrics."""
    source_hashes_before = _hash_v02_files(v02_dir)
    selected_v02 = read_csv(v02_dir / "official_representative_etf_universe.csv")
    eligible = read_csv(v02_dir / "eligible_candidates.csv")
    classified_rows = read_csv(v02_dir / "classified_universe.csv")
    with (v02_dir / "validation.json").open("r", encoding="utf-8") as handle:
        v02_validation = json.load(handle)

    classified_by_ticker = {row["ticker"]: row for row in classified_rows}
    selected_by_group = {
        (row["major_category"], row["representative_group"]): row for row in selected_v02
    }
    if len(selected_by_group) != len(selected_v02):
        raise ValueError("V02_SELECTED_DUPLICATE_GROUP")
    if len({row["ticker"] for row in selected_v02}) != len(selected_v02):
        raise ValueError("V02_SELECTED_DUPLICATE_TICKER")

    authority_matches = (
        str(v02_validation.get("reference_date")) == EXPECTED_REFERENCE_DATE
        and str(v02_validation.get("40D_start_date")) == EXPECTED_40D_START
        and str(v02_validation.get("40D_end_date")) == EXPECTED_40D_END
        and int(v02_validation.get("40D_session_count", -1)) == EXPECTED_40D_SESSIONS
    )
    if not authority_matches:
        raise ValueError("V02_AUTHORITY_WINDOW_MISMATCH")

    removal_reasons: dict[str, str] = {}
    sector_selected = {
        group: row for (category, group), row in selected_by_group.items() if category == "SECTOR_INDEX"
    }
    for parent, children in PARENT_CHILD_GROUPS.items():
        if parent in sector_selected:
            missing_children = [child for child in children if child not in sector_selected]
            if missing_children:
                raise ValueError(f"EXPECTED_CHILD_GROUP_MISSING:{parent}:{'|'.join(missing_children)}")
            removal_reasons[parent] = PARENT_REMOVAL_REASONS[parent]

    groups_to_active_candidates: dict[tuple[str, str], list[dict[str, str]]] = {}
    for candidate in eligible:
        key = (candidate["major_category"], candidate["representative_group"])
        groups_to_active_candidates.setdefault(key, []).append(candidate)

    output_rows: list[dict[str, str]] = []
    change_rows: list[dict[str, str]] = []
    active_audit: list[dict[str, str]] = []
    replacement_by_group: dict[tuple[str, str], tuple[dict[str, str], str]] = {}

    for original in selected_v02:
        category = original["major_category"]
        group = original["representative_group"]
        ticker = original["ticker"]
        metadata = classified_by_ticker.get(ticker)
        if metadata is None:
            raise ValueError(f"SELECTED_CLASSIFICATION_MISSING:{ticker}")
        if metadata.get("major_category") != category or metadata.get("representative_group") != group:
            raise ValueError(f"SELECTED_CLASSIFICATION_MISMATCH:{ticker}")
        product_type = product_management_type(metadata)
        if product_type == "UNKNOWN":
            raise ValueError(f"SELECTED_PRODUCT_MANAGEMENT_TYPE_UNKNOWN:{ticker}")
        if not _hard_filter_pass(metadata):
            raise ValueError(f"V02_SELECTED_HARD_FILTER_FAILURE:{ticker}")

        if group in removal_reasons and category == "SECTOR_INDEX":
            reason = removal_reasons[group]
            change_rows.append({
                "change_type": "PARENT_GROUP_REMOVED",
                "major_category": category,
                "representative_group": group,
                "before_ticker": ticker,
                "before_ETF_name": original["ETF_name"],
                "after_ticker": "",
                "after_ETF_name": "",
                "reason": reason,
            })
            continue

        if product_type == "ACTIVE":
            candidates = groups_to_active_candidates.get((category, group), [])
            selected = select_passive_candidate(candidates, classified_by_ticker)
            if selected is None:
                raise ValueError(f"PASSIVE_REPLACEMENT_NOT_FOUND:{category}:{group}")
            replacement, reason = selected
            new_ticker = replacement["ticker"]
            replacement_metadata = classified_by_ticker[new_ticker]
            replacement_by_group[(category, group)] = (replacement, reason)
            new_row = _universe_row(
                major_category=category,
                group=group,
                ticker=new_ticker,
                name=replacement["ISU_ABBRV"],
                listing_date=replacement["listing_date"],
                close=replacement["reference_close"],
                avg_volume=replacement["avg_volume_40d"],
                avg_trading_value=replacement["avg_trading_value_40d"],
                product_type=product_management_type(replacement_metadata),
                selection_reason=reason,
                change="ACTIVE_REPLACED",
                aum=replacement.get("AUM_if_available", ""),
                tracking_quality="",
            )
            output_rows.append(new_row)
            change_rows.append({
                "change_type": "ACTIVE_REPLACED",
                "major_category": category,
                "representative_group": group,
                "before_ticker": ticker,
                "before_ETF_name": original["ETF_name"],
                "after_ticker": new_ticker,
                "after_ETF_name": replacement["ISU_ABBRV"],
                "reason": f"Excluded the ACTIVE representative and reselected from existing V02 eligible PASSIVE candidates. {reason}",
            })
            active_audit.append({
                "major_category": category,
                "representative_group": group,
                "removed_ticker": ticker,
                "removed_ETF_name": original["ETF_name"],
                "product_management_type": product_type,
                "replacement_ticker": new_ticker,
                "replacement_ETF_name": replacement["ISU_ABBRV"],
                "selection_reason": reason,
            })
            continue

        output_rows.append(_universe_row(
            major_category=category,
            group=group,
            ticker=ticker,
            name=original["ETF_name"],
            listing_date=original["listing_date"],
            close=original["close"],
            avg_volume=original["avg_volume_40d"],
            avg_trading_value=original["avg_trading_value_40d"],
            product_type=product_type,
            selection_reason=original.get("selection_reason", ""),
            change="UNCHANGED",
            aum=original.get("AUM_if_available", ""),
            tracking_quality=original.get("tracking_quality_if_available", ""),
        ))
        change_rows.append({
            "change_type": "UNCHANGED",
            "major_category": category,
            "representative_group": group,
            "before_ticker": ticker,
            "before_ETF_name": original["ETF_name"],
            "after_ticker": ticker,
            "after_ETF_name": original["ETF_name"],
            "reason": "Retained the V02 representative; no V03 rule requires a change.",
        })

    final_groups = [(row["major_category"], row["representative_group"]) for row in output_rows]
    duplicate_group_count = len(final_groups) - len(set(final_groups))
    final_tickers = [row["ticker"] for row in output_rows]
    duplicate_ticker_count = len(final_tickers) - len(set(final_tickers))
    selected_active = [row["ticker"] for row in output_rows if row["product_management_type"] != "PASSIVE"]

    selected_v02_by_ticker = {row["ticker"]: row for row in selected_v02}
    eligible_by_ticker = {row["ticker"]: row for row in eligible}
    market_metric_source_mismatch_count = 0
    for row in output_rows:
        if row["change_from_v02"] == "ACTIVE_REPLACED":
            source = eligible_by_ticker.get(row["ticker"])
            expected_metrics = (
                source.get("listing_date", "") if source else "",
                source.get("reference_close", "") if source else "",
                source.get("avg_volume_40d", "") if source else "",
                source.get("avg_trading_value_40d", "") if source else "",
            )
        else:
            source = selected_v02_by_ticker.get(row["ticker"])
            expected_metrics = (
                source.get("listing_date", "") if source else "",
                source.get("close", "") if source else "",
                source.get("avg_volume_40d", "") if source else "",
                source.get("avg_trading_value_40d", "") if source else "",
            )
        actual_metrics = (
            row["listing_date"], row["close"], row["avg_volume_40d"], row["avg_trading_value_40d"]
        )
        if source is None or actual_metrics != expected_metrics:
            market_metric_source_mismatch_count += 1

    hard_filter_violations = 0
    unknown_selected_classification_count = 0
    for row in output_rows:
        metadata = classified_by_ticker.get(row["ticker"])
        if metadata is None:
            unknown_selected_classification_count += 1
            hard_filter_violations += 1
            continue
        if product_management_type(metadata) == "UNKNOWN":
            unknown_selected_classification_count += 1
        if not _hard_filter_pass(metadata):
            hard_filter_violations += 1
        if metadata.get("major_category") != row["major_category"] or metadata.get("representative_group") != row["representative_group"]:
            unknown_selected_classification_count += 1

    final_sector_groups = {
        row["representative_group"] for row in output_rows if row["major_category"] == "SECTOR_INDEX"
    }
    parent_child_overlap_violations = sum(
        1 for parent, children in PARENT_CHILD_GROUPS.items()
        if parent in final_sector_groups and any(child in final_sector_groups for child in children)
    )

    # Audit other plausible adjacencies explicitly without inventing overlap:
    # the instruction requires ambiguous relationships to remain unchanged.
    def chosen(group: str) -> dict[str, str]:
        return sector_selected.get(group, {})

    overlap_rows: list[dict[str, str]] = []
    for parent, children in PARENT_CHILD_GROUPS.items():
        p = chosen(parent)
        overlap_rows.append({
            "major_category": "SECTOR_INDEX",
            "parent_group": parent,
            "parent_ticker": p.get("ticker", ""),
            "parent_ETF_name": p.get("ETF_name", ""),
            "child_groups": "|".join(children),
            "child_tickers": "|".join(chosen(child).get("ticker", "") for child in children),
            "action": "REMOVE_PARENT",
            "reason": removal_reasons[parent],
        })
    energy = chosen("ENERGY")
    energy_chemicals = chosen("ENERGY_CHEMICALS")
    overlap_rows.append({
        "major_category": "SECTOR_INDEX",
        "parent_group": "ENERGY",
        "parent_ticker": energy.get("ticker", ""),
        "parent_ETF_name": energy.get("ETF_name", ""),
        "child_groups": "ENERGY_CHEMICALS",
        "child_tickers": energy_chemicals.get("ticker", ""),
        "action": "KEEP_SEPARATE_AS_DIRECTED",
        "reason": "The work instruction explicitly says not to automatically deduplicate ENERGY and ENERGY_CHEMICALS; the selected products also represent distinct regional/industry structures.",
    })
    consumer_parent = chosen("CONSUMER_DISCRETIONARY")
    overlap_rows.append({
        "major_category": "SECTOR_INDEX",
        "parent_group": "CONSUMER_DISCRETIONARY",
        "parent_ticker": consumer_parent.get("ticker", ""),
        "parent_ETF_name": consumer_parent.get("ETF_name", ""),
        "child_groups": "AUTO|COSMETICS|TRAVEL_LEISURE",
        "child_tickers": "|".join(chosen(child).get("ticker", "") for child in ("AUTO", "COSMETICS", "TRAVEL_LEISURE")),
        "action": "NO_SELECTED_PARENT_REPRESENTATIVE",
        "reason": "V02 has no eligible broad consumer-discretionary representative, so there is no parent representative to remove.",
    })
    overlap_rows.append({
        "major_category": "SECTOR_INDEX",
        "parent_group": "MEDIA_ENTERTAINMENT",
        "parent_ticker": chosen("MEDIA_ENTERTAINMENT").get("ticker", ""),
        "parent_ETF_name": chosen("MEDIA_ENTERTAINMENT").get("ETF_name", ""),
        "child_groups": "GAMING",
        "child_tickers": chosen("GAMING").get("ticker", ""),
        "action": "KEEP_AMBIGUOUS_SEPARATE",
        "reason": "The V02 product/index mandates do not establish a clear parent-child exposure relationship; preserve both and record the ambiguity.",
    })

    source_hashes_after = _hash_v02_files(v02_dir)
    v02_sources_unchanged = source_hashes_before == source_hashes_after
    selected_count_expected = len(selected_v02) - len(removal_reasons)
    reference_unchanged = str(v02_validation.get("reference_date")) == EXPECTED_REFERENCE_DATE
    window_unchanged = (
        str(v02_validation.get("40D_start_date")) == EXPECTED_40D_START
        and str(v02_validation.get("40D_end_date")) == EXPECTED_40D_END
    )
    sessions_unchanged = int(v02_validation.get("40D_session_count", -1)) == EXPECTED_40D_SESSIONS
    remaining_children = [child for children in PARENT_CHILD_GROUPS.values() for child in children]
    checks = {
        "reference_date_unchanged": reference_unchanged,
        "40D_window_unchanged": window_unchanged,
        "40D_session_count_unchanged": sessions_unchanged,
        "market_data_refetch_count_zero": True,
        "40D_metric_recomputation_count_zero": True,
        "selected_active_etf_count_zero": len(selected_active) == 0,
        "selected_hard_filter_violation_count_zero": hard_filter_violations == 0,
        "duplicate_representative_group_count_zero": duplicate_group_count == 0,
        "parent_child_overlap_violation_count_zero": parent_child_overlap_violations == 0,
        "unknown_selected_classification_count_zero": unknown_selected_classification_count == 0,
        "v02_source_raw_figures_unchanged": v02_sources_unchanged,
        "v02_market_metrics_copied_exactly": market_metric_source_mismatch_count == 0,
        "v03_count_matches_expected_scope": len(output_rows) == selected_count_expected,
        "selected_ticker_count_unique": duplicate_ticker_count == 0,
    }
    passed = all(checks.values())
    validation: dict[str, Any] = {
        "verdict": "ETF_OFFICIAL_UNIVERSE_REFINEMENT_V03_COMPLETE" if passed else "CHECK_REQUIRED",
        "passed": passed,
        "market_reference_date": str(v02_validation["reference_date"]),
        "40D_start_date": str(v02_validation["40D_start_date"]),
        "40D_end_date": str(v02_validation["40D_end_date"]),
        "40D_session_count": int(v02_validation["40D_session_count"]),
        "market_data_refetch_count": 0,
        "40D_market_metric_recomputation_count": 0,
        "v02_selected_count": len(selected_v02),
        "v03_selected_count": len(output_rows),
        "active_representatives_removed_count": len(active_audit),
        "active_representatives_replaced_count": len(active_audit),
        "active_representatives_removed": [
            {"ticker": row["removed_ticker"], "ETF_name": row["removed_ETF_name"], "group": row["representative_group"]}
            for row in active_audit
        ],
        "active_representatives_replaced": [
            {"old_ticker": row["removed_ticker"], "new_ticker": row["replacement_ticker"], "new_ETF_name": row["replacement_ETF_name"]}
            for row in active_audit
        ],
        "parent_sector_groups_removed": sorted(removal_reasons),
        "parent_sector_groups_removed_count": len(removal_reasons),
        "remaining_child_groups": remaining_children,
        "selected_active_etf_count": len(selected_active),
        "selected_active_tickers": selected_active,
        "selected_hard_filter_violation_count": hard_filter_violations,
        "duplicate_representative_group_count": duplicate_group_count,
        "duplicate_selected_ticker_count": duplicate_ticker_count,
        "parent_child_overlap_violation_count": parent_child_overlap_violations,
        "unknown_selected_classification_count": unknown_selected_classification_count,
        "v02_market_metric_source_mismatch_count": market_metric_source_mismatch_count,
        "v02_source_artifact_hashes_before": source_hashes_before,
        "v02_source_artifact_hashes_after": source_hashes_after,
        "checks": checks,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "official_representative_etf_universe_v03.csv", output_rows, UNIVERSE_FIELDS)
    write_csv(output_dir / "changes_from_v02.csv", change_rows, CHANGE_FIELDS)
    write_csv(output_dir / "sector_overlap_audit.csv", overlap_rows, OVERLAP_AUDIT_FIELDS)
    write_csv(output_dir / "active_exclusion_audit.csv", active_audit, ACTIVE_AUDIT_FIELDS)
    with (output_dir / "validation.json").open("w", encoding="utf-8") as handle:
        json.dump(validation, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    replaced_text = "; ".join(
        f"{row['removed_ticker']} {row['removed_ETF_name']} → {row['replacement_ticker']} {row['replacement_ETF_name']}"
        for row in active_audit
    ) or "없음"
    removed_text = "; ".join(
        f"{parent} ({sector_selected[parent]['ticker']} {sector_selected[parent]['ETF_name']})"
        for parent in sorted(removal_reasons)
    ) or "없음"
    lines = [
        "# KRX ETF current representative universe refinement V03",
        "",
        f"- Verdict: **{validation['verdict']}**",
        f"- V02 representatives: {len(selected_v02)}; V03 representatives: {len(output_rows)}",
        f"- Authority unchanged: market reference {validation['market_reference_date']}; 40D {validation['40D_start_date']} through {validation['40D_end_date']} ({validation['40D_session_count']} sessions)",
        "- Market data refetches: 0; 40D metric recomputations: 0. All market figures were copied from the committed V02 selected/candidate rows.",
        f"- ACTIVE representatives excluded and replaced: {replaced_text}",
        f"- Parent groups removed: {removed_text}",
        f"- Retained child groups: `{', '.join(remaining_children)}`",
        "- V02 input artifact SHA-256 hashes match before and after generation: `" + str(v02_sources_unchanged) + "`",
        "",
        "## Validation",
        "",
    ]
    lines.extend(f"- `{name}`: `{value}`" for name, value in checks.items())
    lines += [
        "",
        "## Audit files",
        "",
        "- `changes_from_v02.csv`: one row per V02 selected representative, including unchanged, replaced, and removed rows.",
        "- `active_exclusion_audit.csv`: ACTIVE removals and passive replacements.",
        "- `sector_overlap_audit.csv`: explicit finance/IT parent removals and other reviewed adjacent groups.",
        "",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v02-dir", type=Path, default=DEFAULT_V02)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_v03(args.v02_dir, args.output_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "v02_selected_count": result["v02_selected_count"],
        "v03_selected_count": result["v03_selected_count"],
        "active_representatives_replaced_count": result["active_representatives_replaced_count"],
        "parent_sector_groups_removed": result["parent_sector_groups_removed"],
        "passed": result["passed"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
