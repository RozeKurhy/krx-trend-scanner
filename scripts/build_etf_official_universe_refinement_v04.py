#!/usr/bin/env python3
"""Apply the two scoped V04 edits to the existing V03 ETF universe."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V02_DIR = ROOT / "artifacts/research/etf_official_universe_refinement_v02"
V03_DIR = ROOT / "artifacts/research/etf_official_universe_refinement_v03"
DEFAULT_OUTPUT = ROOT / "artifacts/research/etf_official_universe_refinement_v04"
REFERENCE_DATE = "2026-09-23"
WINDOW_START = "2026-07-29"
WINDOW_END = "2026-09-23"
SESSION_COUNT = 40
NEAR_TURNOVER_RELATIVE_TOLERANCE = 0.01

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
V03_FILES = ("official_representative_etf_universe_v03.csv", "validation.json")

# A direct broad-healthcare mandate is established from these existing V02
# product names and official index/objective labels. No new product search is
# performed. The active KRX Healthcare product is audited but cannot be chosen.
BROAD_HEALTHCARE_PRODUCTS = {
    "143860": ("TIGER 헬스케어", "KRX 헬스케어"),
    "266420": ("KODEX 헬스케어", "KRX 헬스케어"),
    "227540": ("TIGER 200 헬스케어", "코스피 200 헬스케어"),
    "453640": ("KODEX 미국S&P500헬스케어", "S&P Health Care Select Sector Index(Price Return)"),
    "463050": ("TIME K바이오액티브", "KRX 헬스케어"),
}
BIOTECH_ONLY_TICKERS = {"244580", "261070", "203780", "371470"}
PARENT_CHILD_GROUPS = {
    "FINANCIALS": ("BANK", "SECURITIES", "INSURANCE"),
    "INFORMATION_TECHNOLOGY": ("SEMICONDUCTOR", "SOFTWARE"),
}

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
    "change_from_v03",
    "source_v02_basis",
    "AUM_if_available",
    "tracking_quality_if_available",
)
CANDIDATE_FIELDS = (
    "ticker",
    "ETF_name",
    "broad_healthcare_eligible",
    "passive",
    "avg_volume_40d",
    "avg_trading_value_40d",
    "AUM_if_available",
    "selected",
    "reason",
)
CHANGE_FIELDS = (
    "change_type",
    "major_category",
    "representative_group_before",
    "representative_group_after",
    "before_ticker",
    "before_ETF_name",
    "after_ticker",
    "after_ETF_name",
    "reason",
)


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
    label = str(metadata.get("ETF_REPLICA_METHD_TP_CD", "") or "").strip()
    upper = label.upper()
    if "액티브" in label or "ACTIVE" in upper:
        return "ACTIVE"
    if "패시브" in label or "PASSIVE" in upper:
        return "PASSIVE"
    return "UNKNOWN"


def is_broad_healthcare_candidate(candidate: dict[str, Any], metadata: dict[str, Any]) -> bool:
    ticker = str(candidate.get("ticker", ""))
    expected = BROAD_HEALTHCARE_PRODUCTS.get(ticker)
    if expected is None:
        return False
    return (
        str(candidate.get("ISU_ABBRV", "")).strip() == expected[0]
        and str(metadata.get("ETF_OBJ_IDX_NM", "")).strip() == expected[1]
    )


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hard_filter_pass(metadata: dict[str, Any]) -> bool:
    return (
        str(metadata.get("hard_filter_pass", "")).strip().lower() in {"true", "1", "yes"}
        and not str(metadata.get("failed_filter", "") or "").strip()
    )


def choose_healthcare_representative(
    candidates: list[dict[str, str]], classified_by_ticker: dict[str, dict[str, str]]
) -> tuple[dict[str, str], str]:
    broad_passive: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        metadata = classified_by_ticker.get(ticker)
        if metadata is None:
            raise ValueError(f"HEALTHCARE_CLASSIFICATION_MISSING:{ticker}")
        if metadata.get("major_category") != "SECTOR_INDEX" or metadata.get("representative_group") != "HEALTHCARE":
            raise ValueError(f"HEALTHCARE_CLASSIFICATION_MISMATCH:{ticker}")
        if ticker in BROAD_HEALTHCARE_PRODUCTS and not is_broad_healthcare_candidate(candidate, metadata):
            raise ValueError(f"BROAD_HEALTHCARE_PRODUCT_METADATA_MISMATCH:{ticker}")
        if not _hard_filter_pass(metadata):
            raise ValueError(f"V02_ELIGIBLE_HEALTHCARE_HARD_FILTER_FAILURE:{ticker}")
        if is_broad_healthcare_candidate(candidate, metadata) and product_management_type(metadata) == "PASSIVE":
            broad_passive.append(candidate)

    if not broad_passive:
        raise ValueError("BROAD_PASSIVE_HEALTHCARE_CANDIDATE_NOT_FOUND")

    values = {row["ticker"]: _number(row.get("avg_trading_value_40d")) for row in broad_passive}
    if any(value is None for value in values.values()):
        raise ValueError("BROAD_PASSIVE_HEALTHCARE_TURNOVER_MISSING")
    top_turnover = max(value for value in values.values() if value is not None)
    near = [row for row in broad_passive if values[row["ticker"]] >= top_turnover * (1.0 - NEAR_TURNOVER_RELATIVE_TOLERANCE)]

    def rank_key(row: dict[str, str]) -> tuple[float, str, float, str]:
        aum = _number(row.get("AUM_if_available"))
        # Missing AUM ranks last, then older listing date wins a tie.
        return (
            -(aum if aum is not None else float("-inf")),
            str(row.get("listing_date", "9999-12-31")) or "9999-12-31",
            -float(values[row["ticker"]] or 0),
            row["ticker"],
        )

    winner = sorted(near, key=rank_key)[0]
    if len(near) > 1:
        reason = "Broad healthcare PASSIVE candidates were within 1% turnover; highest available V02 AUM proxy selected, then listing age."
    else:
        reason = "Highest V02 40D average trading value among broad healthcare PASSIVE candidates; AUM and listing age break ties."
    return winner, reason


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_hashes(v02_dir: Path, v03_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "v02": {name: _sha256(v02_dir / name) for name in V02_FILES},
        "v03": {name: _sha256(v03_dir / name) for name in V03_FILES},
    }


def _metric_tuple(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("listing_date", "")),
        str(row.get("close", "")),
        str(row.get("avg_volume_40d", "")),
        str(row.get("avg_trading_value_40d", "")),
    )


def build_v04(v02_dir: Path = V02_DIR, v03_dir: Path = V03_DIR, output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    input_hashes_before = _input_hashes(v02_dir, v03_dir)
    v02_candidates = read_csv(v02_dir / "eligible_candidates.csv")
    v02_classified = read_csv(v02_dir / "classified_universe.csv")
    v03_rows = read_csv(v03_dir / "official_representative_etf_universe_v03.csv")
    with (v02_dir / "validation.json").open(encoding="utf-8") as handle:
        v02_validation = json.load(handle)
    with (v03_dir / "validation.json").open(encoding="utf-8") as handle:
        v03_validation = json.load(handle)

    expected_dates = (REFERENCE_DATE, WINDOW_START, WINDOW_END, SESSION_COUNT)
    for label, validation in (("V02", v02_validation), ("V03", v03_validation)):
        actual = (
            str(validation.get("reference_date" if label == "V02" else "market_reference_date")),
            str(validation.get("40D_start_date")),
            str(validation.get("40D_end_date")),
            int(validation.get("40D_session_count", -1)),
        )
        if actual != expected_dates:
            raise ValueError(f"{label}_AUTHORITY_WINDOW_MISMATCH:{actual}")
    if v02_validation.get("passed") is not True or v03_validation.get("passed") is not True:
        raise ValueError("UPSTREAM_AUTHORITY_NOT_PASSED")
    if len(v03_rows) != 37:
        raise ValueError(f"V03_SELECTED_COUNT_NOT_37:{len(v03_rows)}")

    classified_by_ticker = {row["ticker"]: row for row in v02_classified}
    healthcare_v03 = [row for row in v03_rows if row["representative_group"] == "HEALTHCARE"]
    if len(healthcare_v03) != 1 or healthcare_v03[0]["ticker"] != "244580":
        raise ValueError("V03_HEALTHCARE_AUTHORITY_MISMATCH")
    healthcare_candidates = [
        row for row in v02_candidates
        if row["major_category"] == "SECTOR_INDEX" and row["representative_group"] == "HEALTHCARE"
    ]
    if not healthcare_candidates:
        raise ValueError("V02_HEALTHCARE_ELIGIBLE_CANDIDATES_MISSING")

    selected_candidate, selection_rule = choose_healthcare_representative(healthcare_candidates, classified_by_ticker)
    chosen_ticker = selected_candidate["ticker"]
    chosen_metadata = classified_by_ticker[chosen_ticker]

    audit_rows: list[dict[str, str]] = []
    candidate_by_ticker = {row["ticker"]: row for row in healthcare_candidates}
    for candidate in healthcare_candidates:
        ticker = candidate["ticker"]
        metadata = classified_by_ticker[ticker]
        broad = is_broad_healthcare_candidate(candidate, metadata)
        passive = product_management_type(metadata) == "PASSIVE"
        selected = ticker == chosen_ticker
        if selected:
            reason = f"Broad healthcare sector mandate; PASSIVE; selected under V02 liquidity priority. {selection_rule}"
        elif broad and not passive:
            reason = "Tracks a broad healthcare sector, but official KRX metadata marks it ACTIVE; V04 requires PASSIVE."
        elif broad and passive:
            reason = f"Broad healthcare PASSIVE candidate retained in audit but not selected because its V02 ranking loses to {chosen_ticker}."
        elif ticker in BIOTECH_ONLY_TICKERS:
            reason = "Biotechnology or biotech-subindustry exposure; excluded from broad healthcare representation per V04 scope."
        elif product_management_type(metadata) == "ACTIVE":
            reason = "ACTIVE product; V04 representative candidates must be PASSIVE."
        else:
            reason = f"Does not match the V04 broad healthcare product/index allowlist (official index: {metadata.get('ETF_OBJ_IDX_NM', '')})."
        audit_rows.append({
            "ticker": ticker,
            "ETF_name": candidate["ISU_ABBRV"],
            "broad_healthcare_eligible": str(broad).lower(),
            "passive": str(passive).lower(),
            "avg_volume_40d": candidate["avg_volume_40d"],
            "avg_trading_value_40d": candidate["avg_trading_value_40d"],
            "AUM_if_available": candidate.get("AUM_if_available", ""),
            "selected": str(selected).lower(),
            "reason": reason,
        })

    output_rows: list[dict[str, str]] = []
    changes: list[dict[str, str]] = []
    v03_non_healthcare = [row for row in v03_rows if row["representative_group"] != "HEALTHCARE"]
    healthcare_reason = f"Replaced V03's biotech-specific representative with the highest-ranked broad healthcare PASSIVE candidate from the existing V02 eligible set. {selection_rule}"
    for row in v03_rows:
        if row["representative_group"] == "HEALTHCARE":
            output_rows.append({
                "major_category": row["major_category"],
                "representative_group": "HEALTHCARE",
                "ticker": chosen_ticker,
                "ETF_name": selected_candidate["ISU_ABBRV"],
                "listing_date": selected_candidate["listing_date"],
                "close": selected_candidate["reference_close"],
                "avg_volume_40d": selected_candidate["avg_volume_40d"],
                "avg_trading_value_40d": selected_candidate["avg_trading_value_40d"],
                "product_management_type": product_management_type(chosen_metadata),
                "selection_reason": healthcare_reason,
                "change_from_v03": "HEALTHCARE_RESELECTED",
                "source_v02_basis": "V02_ELIGIBLE_CANDIDATE",
                "AUM_if_available": selected_candidate.get("AUM_if_available", ""),
                "tracking_quality_if_available": "",
            })
            changes.append({
                "change_type": "HEALTHCARE_RESELECTED",
                "major_category": "SECTOR_INDEX",
                "representative_group_before": "HEALTHCARE",
                "representative_group_after": "HEALTHCARE",
                "before_ticker": row["ticker"],
                "before_ETF_name": row["ETF_name"],
                "after_ticker": chosen_ticker,
                "after_ETF_name": selected_candidate["ISU_ABBRV"],
                "reason": healthcare_reason,
            })
            continue

        renamed = row["representative_group"] == "GLOBAL_BROAD"
        after_group = "DEVELOPED_MARKETS" if renamed else row["representative_group"]
        output_rows.append({
            "major_category": row["major_category"],
            "representative_group": after_group,
            "ticker": row["ticker"],
            "ETF_name": row["ETF_name"],
            "listing_date": row["listing_date"],
            "close": row["close"],
            "avg_volume_40d": row["avg_volume_40d"],
            "avg_trading_value_40d": row["avg_trading_value_40d"],
            "product_management_type": row["product_management_type"],
            "selection_reason": row["selection_reason"],
            "change_from_v03": "GROUP_RENAMED" if renamed else "UNCHANGED",
            "source_v02_basis": "V03_REPRESENTATIVE",
            "AUM_if_available": row.get("AUM_if_available", ""),
            "tracking_quality_if_available": row.get("tracking_quality_if_available", ""),
        })
        if renamed:
            changes.append({
                "change_type": "GROUP_RENAMED",
                "major_category": row["major_category"],
                "representative_group_before": "GLOBAL_BROAD",
                "representative_group_after": "DEVELOPED_MARKETS",
                "before_ticker": row["ticker"],
                "before_ETF_name": row["ETF_name"],
                "after_ticker": row["ticker"],
                "after_ETF_name": row["ETF_name"],
                "reason": "Corrected the group label to reflect the MSCI Developed Markets exposure; ticker and market figures are unchanged.",
            })

    output_by_ticker = {row["ticker"]: row for row in output_rows}
    selected_tickers = [row["ticker"] for row in output_rows]
    groups = [(row["major_category"], row["representative_group"]) for row in output_rows]
    duplicate_group_count = len(groups) - len(set(groups))
    duplicate_ticker_count = len(selected_tickers) - len(set(selected_tickers))

    v03_by_ticker = {row["ticker"]: row for row in v03_rows}
    non_health_ticker_unchanged = (
        {row["ticker"] for row in output_rows if row["ticker"] != chosen_ticker}
        == {row["ticker"] for row in v03_non_healthcare}
    )
    metric_source_mismatch_count = 0
    for row in output_rows:
        if row["ticker"] == chosen_ticker:
            source_metrics = (
                selected_candidate["listing_date"], selected_candidate["reference_close"],
                selected_candidate["avg_volume_40d"], selected_candidate["avg_trading_value_40d"],
            )
        else:
            source = v03_by_ticker.get(row["ticker"])
            source_metrics = _metric_tuple(source or {})
        if _metric_tuple(row) != source_metrics:
            metric_source_mismatch_count += 1

    selected_active_tickers: list[str] = []
    hard_filter_violation_count = 0
    unknown_selected_classification_count = 0
    for row in output_rows:
        metadata = classified_by_ticker.get(row["ticker"])
        if metadata is None:
            unknown_selected_classification_count += 1
            hard_filter_violation_count += 1
            continue
        if product_management_type(metadata) != "PASSIVE":
            selected_active_tickers.append(row["ticker"])
        expected_source_group = "GLOBAL_BROAD" if row["representative_group"] == "DEVELOPED_MARKETS" else row["representative_group"]
        if metadata.get("major_category") != row["major_category"] or metadata.get("representative_group") != expected_source_group:
            unknown_selected_classification_count += 1
        if not _hard_filter_pass(metadata):
            hard_filter_violation_count += 1

    sector_groups = {row["representative_group"] for row in output_rows if row["major_category"] == "SECTOR_INDEX"}
    parent_child_overlap_count = sum(
        1 for parent, children in PARENT_CHILD_GROUPS.items()
        if parent in sector_groups and any(child in sector_groups for child in children)
    )
    healthcare_row = next((row for row in output_rows if row["representative_group"] == "HEALTHCARE"), {})
    chosen_candidate_audit = next(row for row in audit_rows if row["ticker"] == chosen_ticker)
    healthcare_is_broad_passive = (
        chosen_candidate_audit["broad_healthcare_eligible"] == "true"
        and chosen_candidate_audit["passive"] == "true"
        and chosen_candidate_audit["selected"] == "true"
    )
    biotech_only_selected_count = sum(1 for row in output_rows if row["ticker"] in BIOTECH_ONLY_TICKERS)
    global_broad_count = sum(1 for row in output_rows if row["representative_group"] == "GLOBAL_BROAD")
    developed_rows = [row for row in output_rows if row["representative_group"] == "DEVELOPED_MARKETS"]

    input_hashes_after = _input_hashes(v02_dir, v03_dir)
    upstream_hashes_unchanged = input_hashes_before == input_hashes_after
    checks = {
        "v03_selected_count_37": len(v03_rows) == 37,
        "v04_selected_count_37": len(output_rows) == 37,
        "healthcare_representative_is_broad_passive": healthcare_is_broad_passive,
        "selected_active_etf_count_zero": len(selected_active_tickers) == 0,
        "healthcare_biotech_only_representative_count_zero": biotech_only_selected_count == 0,
        "global_broad_group_count_zero": global_broad_count == 0,
        "developed_markets_group_count_one": len(developed_rows) == 1,
        "developed_markets_ticker_251350": len(developed_rows) == 1 and developed_rows[0]["ticker"] == "251350",
        "all_non_healthcare_tickers_unchanged": non_health_ticker_unchanged,
        "market_reference_date_unchanged": expected_dates[0] == REFERENCE_DATE,
        "40D_window_unchanged": expected_dates[1:3] == (WINDOW_START, WINDOW_END),
        "40D_session_count_unchanged": expected_dates[3] == SESSION_COUNT,
        "market_refetch_count_zero": True,
        "40D_metric_recomputation_count_zero": True,
        "market_metric_source_mismatch_count_zero": metric_source_mismatch_count == 0,
        "hard_filter_violation_count_zero": hard_filter_violation_count == 0,
        "duplicate_representative_group_count_zero": duplicate_group_count == 0,
        "parent_child_overlap_violation_count_zero": parent_child_overlap_count == 0,
        "unknown_selected_classification_count_zero": unknown_selected_classification_count == 0,
        "v02_v03_input_artifacts_unchanged": upstream_hashes_unchanged,
    }
    passed = all(checks.values())
    validation: dict[str, Any] = {
        "verdict": "ETF_OFFICIAL_UNIVERSE_REFINEMENT_V04_COMPLETE" if passed else "CHECK_REQUIRED",
        "passed": passed,
        "market_reference_date": REFERENCE_DATE,
        "40D_start_date": WINDOW_START,
        "40D_end_date": WINDOW_END,
        "40D_session_count": SESSION_COUNT,
        "market_refetch_count": 0,
        "40D_metric_recomputation_count": 0,
        "v03_selected_count": len(v03_rows),
        "v04_selected_count": len(output_rows),
        "healthcare_candidate_count": len(healthcare_candidates),
        "broad_healthcare_passive_candidate_count": sum(
            row["broad_healthcare_eligible"] == "true" and row["passive"] == "true" for row in audit_rows
        ),
        "healthcare_representative": {
            "ticker": chosen_ticker,
            "ETF_name": selected_candidate["ISU_ABBRV"],
            "selection_rule": selection_rule,
        },
        "global_broad_group_count": global_broad_count,
        "developed_markets_group_count": len(developed_rows),
        "developed_markets_ticker": developed_rows[0]["ticker"] if len(developed_rows) == 1 else "",
        "non_healthcare_tickers_unchanged": non_health_ticker_unchanged,
        "selected_active_tickers": selected_active_tickers,
        "healthcare_biotech_only_representative_count": biotech_only_selected_count,
        "market_metric_source_mismatch_count": metric_source_mismatch_count,
        "hard_filter_violation_count": hard_filter_violation_count,
        "duplicate_representative_group_count": duplicate_group_count,
        "duplicate_ticker_count": duplicate_ticker_count,
        "parent_child_overlap_violation_count": parent_child_overlap_count,
        "unknown_selected_classification_count": unknown_selected_classification_count,
        "v02_v03_input_hashes_before": input_hashes_before,
        "v02_v03_input_hashes_after": input_hashes_after,
        "checks": checks,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "official_representative_etf_universe_v04.csv", output_rows, UNIVERSE_FIELDS)
    write_csv(output_dir / "healthcare_candidate_audit.csv", audit_rows, CANDIDATE_FIELDS)
    write_csv(output_dir / "changes_from_v03.csv", changes, CHANGE_FIELDS)
    with (output_dir / "validation.json").open("w", encoding="utf-8") as handle:
        json.dump(validation, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    lines = [
        "# KRX ETF official representative universe refinement V04",
        "",
        f"- Verdict: **{validation['verdict']}**",
        "- V03 selected: 37; V04 selected: 37.",
        f"- Healthcare: {healthcare_v03[0]['ticker']} {healthcare_v03[0]['ETF_name']} → {chosen_ticker} {selected_candidate['ISU_ABBRV']}.",
        f"- Broad healthcare PASSIVE candidates reviewed: {validation['broad_healthcare_passive_candidate_count']}; selection: {selection_rule}",
        "- Group correction: `GLOBAL_BROAD` → `DEVELOPED_MARKETS`; ticker remains `251350`.",
        "- All other non-HEALTHCARE tickers and stored market figures match V03 exactly.",
        f"- Authority unchanged: {REFERENCE_DATE}; 40D {WINDOW_START} through {WINDOW_END} ({SESSION_COUNT} sessions). Refetches: 0; metric recomputations: 0.",
        f"- V02/V03 input files unchanged by generation: `{upstream_hashes_unchanged}`.",
        "",
        "## Validation",
        "",
    ]
    lines.extend(f"- `{key}`: `{value}`" for key, value in checks.items())
    lines += ["", "## Artifacts", "", "- `official_representative_etf_universe_v04.csv`", "- `healthcare_candidate_audit.csv`", "- `changes_from_v03.csv`", "- `validation.json`", ""]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v02-dir", type=Path, default=V02_DIR)
    parser.add_argument("--v03-dir", type=Path, default=V03_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_v04(args.v02_dir, args.v03_dir, args.output_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "v03_selected_count": result["v03_selected_count"],
        "v04_selected_count": result["v04_selected_count"],
        "healthcare_representative": result["healthcare_representative"],
        "developed_markets_ticker": result["developed_markets_ticker"],
        "passed": result["passed"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
