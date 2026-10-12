#!/usr/bin/env python3
"""Check P3-1 portfolio exposure around Koentec's documented cash exchange."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
EFFECTIVE = pd.Timestamp("2025-05-30")
CUTOFF = pd.Timestamp("2025-05-30")
SUPPORT = pd.Timestamp("2025-06-02")
TARGET = ("029960", "KR7029960002")
EVIDENCE = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(name: str) -> pd.DataFrame:
    path = OUT / name
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def pair_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    isu_column = next((col for col in ("isu_cd", "standard_isu_cd") if col in frame.columns), None)
    if isu_column is None:
        return pd.DataFrame()
    tickers = frame["ticker"].astype(str).str.strip().str.zfill(6)
    isu = frame[isu_column].astype(str).str.strip().str.upper()
    return frame.loc[(tickers == TARGET[0]) & (isu == TARGET[1])].copy()


def day(row: dict, field: str) -> pd.Timestamp | None:
    value = row.get(field)
    if value is None or str(value).strip() in {"", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(value).normalize()
    except (TypeError, ValueError):
        return None


def group_audit(group: str) -> tuple[dict, list[dict]]:
    all_trades = read_csv(f"{group}_trades.csv")
    all_events = read_csv(f"{group}_portfolio_events.csv")
    def identity_scanable(frame: pd.DataFrame) -> bool:
        if frame.empty:
            return True
        return "ticker" in frame.columns and any(col in frame.columns for col in ("isu_cd", "standard_isu_cd"))
    exact_pair_columns_scanned = identity_scanable(all_trades) and identity_scanable(all_events)
    trades = pair_rows(all_trades)
    events = pair_rows(all_events)
    rows = events.to_dict("records")
    executed_entries = [row for row in rows if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"]
    executed_exits = [row for row in rows if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"]
    exits_by_id: dict[str, list[dict]] = {}
    for row in executed_exits:
        exits_by_id.setdefault(str(row.get("candidate_id", "")), []).append(row)

    open_at_cutoff: list[dict] = []
    exposed_on_action_date: list[dict] = []
    for entry in executed_entries:
        candidate_id = str(entry.get("candidate_id", ""))
        entry_date = day(entry, "execution_date")
        if entry_date is None:
            continue
        exits = exits_by_id.get(candidate_id, [])
        exits_on_or_before_cutoff = [exit_row for exit_row in exits if (day(exit_row, "execution_date") or pd.Timestamp.max) <= CUTOFF]
        if entry_date <= CUTOFF and not exits_on_or_before_cutoff:
            open_at_cutoff.append(entry)
        if entry_date <= EFFECTIVE:
            exited_before_effective = any((day(exit_row, "execution_date") or pd.Timestamp.max) < EFFECTIVE for exit_row in exits)
            if not exited_before_effective:
                exposed_on_action_date.append(entry)

    support_exits = [
        row for row in executed_exits
        if day(row, "execution_date") == SUPPORT and str(row.get("post_cutoff", "")).strip().lower() in {"true", "1"}
    ]
    cash_skips = [row for row in rows if row.get("event_type") == "ENTRY" and row.get("event_status") == "SKIPPED_CASH_UNAVAILABLE"]
    summary = {
        "group": group.upper(),
        "exact_identity_trade_rows": int(len(trades)),
        "exact_identity_portfolio_events": int(len(events)),
        "exact_pair_columns_scanned": exact_pair_columns_scanned,
        "executed_entry_count": int(len(executed_entries)),
        "cash_unavailable_entry_skip_count": int(len(cash_skips)),
        "held_at_cutoff_after_cutoff_day_events": int(len(open_at_cutoff)),
        "held_at_or_through_cash_exchange_effective_date": int(len(exposed_on_action_date)),
        "held_at_cutoff_share_count": int(sum(float(row.get("shares") or 0) for row in open_at_cutoff)),
        "held_at_or_through_effective_date_share_count": int(sum(float(row.get("shares") or 0) for row in exposed_on_action_date)),
        "support_day_exit_count": int(len(support_exits)),
        "open_at_cutoff_candidate_ids": sorted({str(row.get("candidate_id", "")) for row in open_at_cutoff}),
        "support_exit_candidate_ids": sorted({str(row.get("candidate_id", "")) for row in support_exits}),
    }
    audit_rows = []
    for row in rows:
        audit_rows.append({
            "group": group.upper(),
            **{key: row.get(key) for key in (
                "ticker", "isu_cd", "candidate_id", "event_type", "event_status", "execution_date",
                "signal_date", "shares", "reference_price", "fill_price", "notional_krw", "reason", "post_cutoff",
            )},
            "is_cash_exchange_effective_date": day(row, "execution_date") == EFFECTIVE,
            "is_support_session": day(row, "execution_date") == SUPPORT,
        })
    return summary, audit_rows


def main() -> int:
    groups = {}
    audit_rows: list[dict] = []
    inputs_present = True
    for group in ("control", "candidate"):
        for suffix in ("trades.csv", "portfolio_events.csv"):
            inputs_present &= (OUT / f"{group}_{suffix}").is_file()
        groups[group] = group_audit(group)
        audit_rows.extend(groups[group][1])

    control, candidate = groups["control"][0], groups["candidate"][0]
    exposure = any(
        summary["held_at_or_through_cash_exchange_effective_date"]
        or summary["held_at_cutoff_after_cutoff_day_events"]
        or summary["support_day_exit_count"]
        for summary in (control, candidate)
    )
    scan_complete = inputs_present and all(summary["exact_pair_columns_scanned"] for summary in (control, candidate))
    status = "CHECK_REQUIRED" if exposure or not scan_complete else "NO_P3_1_EXPOSURE"
    result = {
        "schema": "fast_core_v2_alignment_500b_p3_1_corporate_action_audit_v01",
        "target_identity": {"ticker": TARGET[0], "isu_cd": TARGET[1], "name": "Koentec"},
        "official_evidence": {
            "path": str(EVIDENCE.relative_to(ROOT)),
            "sha256": sha(EVIDENCE) if EVIDENCE.is_file() else None,
            "cash_exchange_effective_date": "2025-05-30",
            "documented_consideration_krw_per_share": 9000,
            "delisting_date": "2025-06-16",
            "payment_date_status": "2025-06-20 was scheduled; actual account receipt was not evidenced",
            "cash_tax_fee_and_receivable_contract": "UNDEFINED_BY_P3_1_PORTFOLIO_CONTRACT",
        },
        "portfolio_exposure_method": "Match exact ticker+ISU in the executed portfolio event ledger; identify positions entered by the effective date without an exit before that date, positions remaining at cutoff, and cutoff exits executed on support day.",
        "input_event_scan_complete": scan_complete,
        "control": control,
        "candidate": candidate,
        "control_open_at_cutoff_count": control["held_at_cutoff_after_cutoff_day_events"],
        "candidate_open_at_cutoff_count": candidate["held_at_cutoff_after_cutoff_day_events"],
        "support_day_exit_count": control["support_day_exit_count"] + candidate["support_day_exit_count"],
        "status": status,
        "settlement_invented": False,
        "cash_receivable_or_special_tax_added": False,
        "p3_1_nav_or_trades_modified": False,
        "reason": (
            "Exact identity exposure intersects the cash-exchange date/cutoff/support period; actual entitlement and receipt are unresolved, so no settlement is fabricated."
            if status == "CHECK_REQUIRED" else
            "No exact-identity P3-1 portfolio exposure intersects the cash-exchange date, cutoff, or support-day exit window."
            if status == "NO_P3_1_EXPOSURE" else
            "Required exact-identity event ledgers could not be fully scanned."
        ),
    }
    pd.DataFrame(audit_rows).to_csv(OUT / "corporate_action_position_event_audit.csv", index=False)
    (OUT / "corporate_action_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "input_event_scan_complete": scan_complete, "control": control, "candidate": candidate}, ensure_ascii=False, indent=2))
    return 0 if scan_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
