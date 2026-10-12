#!/usr/bin/env python3
"""Classify fail-closed Repository V2 load outcomes without replaying strategy signals."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository_v2 import _session_projection_evidence
from trend_scanner.data.repository_v2_loader import build_repository_v2


def main() -> int:
    outcomes = pd.read_csv(OUT / "ticker_price_source_audit.csv", keep_default_na=False)
    unavailable = sorted(
        outcomes.loc[outcomes["data_status"].ne("AVAILABLE"), "ticker"].astype(str).str.zfill(6).unique()
    )
    bounds = pd.read_csv(OUT / "identity_repository_v2_bounds.csv", keep_default_na=False)
    bounds["ticker"] = bounds["ticker"].astype(str).str.zfill(6)
    p3_1_intervals: dict[str, list[dict]] = {}
    for item in bounds.loc[bounds["ticker"].isin(unavailable)].to_dict("records"):
        p3_1_intervals.setdefault(item["ticker"], []).append(item)
    repository = build_repository_v2(ROOT, end="2025-06-02")
    rows: list[dict] = []
    for index, ticker in enumerate(unavailable, start=1):
        try:
            frame = repository.get_daily(ticker, "1900-01-01", "2025-06-02")
            if frame is None or frame.empty:
                status, reason, row_count = "EMPTY", "REPOSITORY_V2_EMPTY", 0
            else:
                status, reason, row_count = "AVAILABLE_ON_RECHECK", None, int(len(frame))
        except MarketDataError as exc:
            status, reason, row_count = "EXPECTED_DATA_UNAVAILABLE", str(exc), 0
        except Exception as exc:  # keep unexpected source failure visible without retry/fallback
            status, reason, row_count = "UNEXPECTED_RECHECK_ERROR", f"{type(exc).__name__}:{str(exc)[:300]}", 0
        detail: dict = {"effective_start": None, "effective_end": None, "adjusted_rows": None, "raw_rows": None}
        if reason == "REPOSITORY_V2_TRADING_SESSION_MISMATCH":
            try:
                clamped_end = repository._clamp_to_certified_boundary("2025-06-02")
                clamped_start, clamped_end = repository._clamp_to_identity_bounds(ticker, "1900-01-01", clamped_end)
                start_ts, end_ts = pd.Timestamp(clamped_start), pd.Timestamp(clamped_end)
                adjusted = repository._load_adjusted(repository._adjusted_ticker(ticker), start_ts, end_ts)
                raw = repository._load_raw(repository._raw_ticker(ticker), start_ts, end_ts)
                evidence = _session_projection_evidence(adjusted, raw)
                unclassified_raw_details = [
                    item for item in evidence["raw_only_row_details"]
                    if item.get("classification") == "UNCLASSIFIED_RAW_ONLY"
                ]
                predicate_failures = Counter()
                for item in unclassified_raw_details:
                    text = str(item.get("classification_reason", ""))
                    prefix = "predicate fields failed:"
                    if text.startswith(prefix):
                        predicate_failures.update(
                            field.strip() for field in text[len(prefix):].split(",") if field.strip()
                        )
                p3_1_scope_matches = []
                warmup_scope_matches = []
                for date_text in evidence["rejected_raw_only_dates"]:
                    date = pd.Timestamp(date_text)
                    for interval in p3_1_intervals.get(ticker, []):
                        p3_start = pd.Timestamp(interval["p3_1_window_from"])
                        p3_end = pd.Timestamp(interval["p3_1_window_to"])
                        if p3_start <= date <= p3_end:
                            raw_detail = next((item for item in unclassified_raw_details if item.get("date") == date_text), {})
                            p3_1_scope_matches.append({
                                "date": date_text,
                                "isu_cd": interval["isu_cd"],
                                "p3_1_identity_window_from": interval["p3_1_window_from"],
                                "p3_1_identity_window_to": interval["p3_1_window_to"],
                                "classification_reason": raw_detail.get("classification_reason"),
                            })
                        pit_start = max(pd.Timestamp(interval["pit_effective_from"]), pd.Timestamp("2017-01-01"))
                        warmup_end = min(pd.Timestamp(interval["pit_effective_to"]), pd.Timestamp("2021-12-31"))
                        if pit_start <= date <= warmup_end:
                            raw_detail = next((item for item in unclassified_raw_details if item.get("date") == date_text), {})
                            warmup_scope_matches.append({
                                "date": date_text,
                                "isu_cd": interval["isu_cd"],
                                "identity_window_from": interval["pit_effective_from"],
                                "identity_window_to": interval["pit_effective_to"],
                                "classification_reason": raw_detail.get("classification_reason"),
                            })
                        if p3_start <= date <= p3_end or pit_start <= date <= warmup_end:
                            break
                detail = {
                    "effective_start": clamped_start,
                    "effective_end": clamped_end,
                    "adjusted_rows": int(len(adjusted)),
                    "raw_rows": int(len(raw)),
                    "adjusted_date_bounds": [
                        None if adjusted.empty else adjusted.index.min().strftime("%Y-%m-%d"),
                        None if adjusted.empty else adjusted.index.max().strftime("%Y-%m-%d"),
                    ],
                    "raw_date_bounds": [
                        None if raw.empty else raw.index.min().strftime("%Y-%m-%d"),
                        None if raw.empty else raw.index.max().strftime("%Y-%m-%d"),
                    ],
                    "adjusted_only_count": len(evidence["adjusted_only_dates"]),
                    "unexplained_adjusted_only_count": len(evidence["unexplained_adjusted_only_dates"]),
                    "raw_only_count": len(evidence["raw_only_dates"]),
                    "rejected_raw_only_count": len(evidence["rejected_raw_only_dates"]),
                    "unclassified_raw_only_row_count": len(unclassified_raw_details),
                    "unclassified_raw_only_failed_predicate_field_counts": dict(sorted(predicate_failures.items())),
                    "unclassified_raw_only_dates_inside_p3_1_pit": len(p3_1_scope_matches),
                    "unclassified_raw_only_dates_inside_ma60_warmup_pit": len(warmup_scope_matches),
                    "unclassified_raw_only_dates_inside_p3_1_pit_or_ma_warmup": len({
                        item["date"] for item in p3_1_scope_matches + warmup_scope_matches
                    }),
                    "p3_1_scope_mismatch_dates_sample": p3_1_scope_matches[:10],
                    "ma60_warmup_scope_mismatch_dates_sample": warmup_scope_matches[:10],
                    "accepted_nontrading_placeholder_count": len(evidence["accepted_placeholder_dates"]),
                    "known_adjusted_gap_count": len(evidence["known_adjusted_gap_dates"]),
                    "outside_identity_lifecycle_count": len(evidence["outside_identity_lifecycle_dates"]),
                    "adjusted_source_nonusable_count": len(evidence["adjusted_source_nonusable_dates"]),
                    "projected_date_set_exact_match": bool(evidence["projected_date_set_exact_match"]),
                    "unexplained_adjusted_only_dates_sample": evidence["unexplained_adjusted_only_dates"][:10],
                    "rejected_raw_only_dates_sample": evidence["rejected_raw_only_dates"][:10],
                    "unclassified_raw_only_details_sample": [
                        {"date": item.get("date"), "classification_reason": item.get("classification_reason")}
                        for item in unclassified_raw_details[:10]
                    ],
                }
                reason = (
                    "UNEXPLAINED_ADJUSTED_ONLY_SESSION"
                    if detail["unexplained_adjusted_only_count"]
                    else "UNCLASSIFIED_RAW_ONLY_SESSION"
                    if detail["rejected_raw_only_count"]
                    else "PROJECTED_DATE_SET_MISMATCH"
                    if not detail["projected_date_set_exact_match"]
                    else "SESSION_MISMATCH_RECHECK_NOT_REPRODUCED"
                )
            except Exception as exc:
                detail = {"detail_audit_error": f"{type(exc).__name__}:{str(exc)[:300]}"}
        rows.append({"ticker": ticker, "status": status, "reason": reason, "repository_v2_error": repository._query_audit.get(ticker, {}).get("reason"), "daily_rows": row_count, **detail})
        if index % 25 == 0 or index == len(unavailable):
            print(f"classified {index}/{len(unavailable)} RepositoryV2 unavailable tickers", flush=True)

    reason_counts = pd.Series([row["reason"] or "AVAILABLE_ON_RECHECK" for row in rows]).value_counts().sort_index().to_dict()
    failed_predicate_counts = Counter()
    for row in rows:
        failed_predicate_counts.update(row.get("unclassified_raw_only_failed_predicate_field_counts", {}))
    projection_totals = {
        key: int(sum(row.get(key, 0) or 0 for row in rows))
        for key in (
            "adjusted_rows", "raw_rows", "adjusted_only_count", "unexplained_adjusted_only_count",
            "raw_only_count", "rejected_raw_only_count", "unclassified_raw_only_row_count",
        "unclassified_raw_only_dates_inside_p3_1_pit",
        "unclassified_raw_only_dates_inside_ma60_warmup_pit",
        "unclassified_raw_only_dates_inside_p3_1_pit_or_ma_warmup",
            "accepted_nontrading_placeholder_count", "known_adjusted_gap_count",
            "outside_identity_lifecycle_count", "adjusted_source_nonusable_count",
        )
    }
    pd.DataFrame(rows).to_csv(OUT / "repository_v2_unavailable_cause_audit.csv", index=False)
    result = {
        "schema": "fast_core_v2_alignment_500b_p3_1_repository_v2_unavailable_cause_audit_v01",
        "scope": "Read-only local RepositoryV2 diagnosis of ticker outcomes already returned DATA_UNAVAILABLE by the single P3-1 full run; no signal generation, portfolio replay, network, or alternate source.",
        "unavailable_ticker_count_from_full_run": len(unavailable),
        "rechecked_ticker_count": len(rows),
        "reason_counts": reason_counts,
        "failed_raw_placeholder_predicate_field_counts": dict(sorted(failed_predicate_counts.items())),
        "session_projection_totals_across_tickers": projection_totals,
        "unexpected_recheck_error_count": sum(row["status"] == "UNEXPECTED_RECHECK_ERROR" for row in rows),
        "all_unavailable_tickers_classified": len(rows) == len(unavailable) and all(row["status"] != "UNEXPECTED_RECHECK_ERROR" for row in rows),
        "session_projection_detail_audit_complete": all(
            row.get("projected_date_set_exact_match") is False or row["status"] != "EXPECTED_DATA_UNAVAILABLE"
            for row in rows
        ),
        "ticker_audit_csv": "repository_v2_unavailable_cause_audit.csv",
    }
    (OUT / "repository_v2_unavailable_cause_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["all_unavailable_tickers_classified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
