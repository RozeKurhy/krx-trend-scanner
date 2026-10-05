"""Display-only historical PIT fundamental status for the B Select lineage.

The status is informational and never changes B Select Core V1/V2 signals,
buckets or lifecycle. It is evaluated with the V03 FIX01 PIT path
(``b_select_core_oi_1q_pit``) at a fixed status date per key:

* a trade, an open position or a pending exit: its ``entry_signal_date``;
* a pending entry: the pending event's signal date;
* an item without any Select Core signal: the monitor ``requested_as_of``.

Because the evaluation only reads disclosures available by that date, a
status for ``(ticker, isu_cd, status_asof_date)`` cannot change after later
filings.  The ledger is a speed cache of those results; entries whose
``미상`` came from a local cache gap are marked retryable and re-evaluated.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from trend_scanner.backtest.b_select_core_oi_1q_pit import evaluate_pit_signals
from trend_scanner.backtest.b_select_core_oi_1q_v03 import FAIL, PASS


EXCELLENT = "우수"
GOOD = "양호"
NEUTRAL = "보통"
CAUTION = "주의"
UNKNOWN = "미상"
FUNDAMENTAL_STATUSES = (EXCELLENT, GOOD, NEUTRAL, CAUTION, UNKNOWN)
EXCELLENT_MIN_OPERATING_INCOME_KRW = 2_000_000_000
EVALUATOR = "B_SELECT_OI_1Q_PIT_V03_FIX01"
LEDGER_RELATIVE = Path("artifacts/strategies/b_select_core_v1/fundamental_status/pit_status_ledger.csv")
BASIS_ENTRY_SIGNAL = "ENTRY_SIGNAL_DATE"
BASIS_PENDING_ENTRY = "PENDING_ENTRY_SIGNAL_DATE"
BASIS_REQUESTED_AS_OF = "REQUESTED_AS_OF_NO_SIGNAL"
RETRYABLE_REASON_PREFIXES = (
    "REGISTRY_CACHE_UNAVAILABLE",
    "FISCAL_YEAR_BUILD_FAILED",
    "CORP_CODE_UNAVAILABLE",
    "COMPANY_METADATA_UNAVAILABLE",
)
LEDGER_COLUMNS = (
    "ticker", "isu_cd", "status_asof_date", "fundamental_status", "oi_status", "oi_reason",
    "fundamental_fiscal_quarter", "latest_quarter_first_rcept_dt", "fundamental_source_date",
    "prior_year_same_quarter", "retryable", "evaluator",
)

StatusKey = tuple[str, str, str]


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def classify_evaluation_row(row: Mapping[str, Any]) -> str:
    """Map one PIT latest-quarter evaluation row to the five display states."""

    current = _number(row.get("current_operating_income"))
    if not row.get("latest_quarter") or current is None:
        return UNKNOWN
    if current <= 0:
        return CAUTION
    prior = _number(row.get("prior_operating_income"))
    comparable = row.get("oi_status") in {PASS, FAIL} and prior is not None
    if comparable and current > prior:
        return EXCELLENT if current >= EXCELLENT_MIN_OPERATING_INCOME_KRW else GOOD
    return NEUTRAL


def is_retryable(row: Mapping[str, Any]) -> bool:
    return str(row.get("oi_reason") or "").startswith(RETRYABLE_REASON_PREFIXES)


def status_key(ticker: Any, isu_cd: Any, asof: Any) -> StatusKey:
    return str(ticker).strip().zfill(6), str(isu_cd).strip().upper(), str(asof)[:10]


def item_status_asof(item: Mapping[str, Any], requested_as_of: str) -> tuple[str, str]:
    """Status date and basis for one B Select current-state item."""

    trade = item.get("current_trade")
    if isinstance(trade, Mapping) and trade.get("entry_signal_date"):
        return str(trade["entry_signal_date"])[:10], BASIS_ENTRY_SIGNAL
    pending = item.get("pending_event")
    if isinstance(pending, Mapping) and str(pending.get("kind")).upper() == "ENTRY" and pending.get("signal_date"):
        return str(pending["signal_date"])[:10], BASIS_PENDING_ENTRY
    return str(requested_as_of)[:10], BASIS_REQUESTED_AS_OF


def status_keys(items: Iterable[Mapping[str, Any]], requested_as_of: str) -> dict[StatusKey, str]:
    """Every status key needed by the current items and their trade history."""

    keys: dict[StatusKey, str] = {}
    for item in items:
        asof, basis = item_status_asof(item, requested_as_of)
        keys.setdefault(status_key(item.get("ticker"), item.get("isu_cd"), asof), basis)
        for trade in item.get("trade_history") or []:
            if trade.get("entry_signal_date"):
                keys.setdefault(status_key(item.get("ticker"), item.get("isu_cd"), trade["entry_signal_date"]),
                                BASIS_ENTRY_SIGNAL)
    return keys


def ledger_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "ticker": str(row["ticker"]).zfill(6),
        "isu_cd": str(row["isu_cd"]).upper(),
        "status_asof_date": str(row["entry_signal_date"])[:10],
        "fundamental_status": classify_evaluation_row(row),
        "oi_status": str(row.get("oi_status") or ""),
        "oi_reason": str(row.get("oi_reason") or ""),
        "fundamental_fiscal_quarter": str(row.get("latest_quarter") or ""),
        "latest_quarter_first_rcept_dt": str(row.get("latest_quarter_first_rcept_dt") or ""),
        "fundamental_source_date": str(row.get("current_source_rcept_dt") or ""),
        "prior_year_same_quarter": str(row.get("prior_year_same_quarter") or ""),
        "retryable": "true" if is_retryable(row) else "false",
        "evaluator": EVALUATOR,
    }


def read_ledger(repo_root: Path | str) -> dict[StatusKey, dict[str, str]]:
    path = Path(repo_root) / LEDGER_RELATIVE
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ledger: dict[StatusKey, dict[str, str]] = {}
    for row in rows:
        key = status_key(row["ticker"], row["isu_cd"], row["status_asof_date"])
        if key in ledger:
            raise ValueError(f"duplicate fundamental status ledger key: {key}")
        if row.get("fundamental_status") not in FUNDAMENTAL_STATUSES or row.get("evaluator") != EVALUATOR:
            raise ValueError(f"invalid fundamental status ledger row: {key}")
        ledger[key] = row
    return ledger


def evaluate_keys(keys: Iterable[StatusKey], repo_root: Path | str) -> dict[StatusKey, dict[str, str]]:
    candidates = [{"ticker": t, "isu_cd": i, "entry_signal_date": d} for t, i, d in keys]
    if not candidates:
        return {}
    frame = evaluate_pit_signals(candidates, repo_root=repo_root)
    result = {}
    for record in frame.to_dict("records"):
        row = ledger_row({key: (None if value != value else value) for key, value in record.items()})
        result[status_key(row["ticker"], row["isu_cd"], row["status_asof_date"])] = row
    return result


def resolve_statuses(keys: Iterable[StatusKey], repo_root: Path | str) -> dict[StatusKey, dict[str, str]]:
    """Ledger rows for ``keys``; missing or retryable keys are evaluated in memory."""

    wanted = list(dict.fromkeys(keys))
    ledger = read_ledger(repo_root)
    resolved = {key: ledger[key] for key in wanted if key in ledger and ledger[key]["retryable"] != "true"}
    missing = [key for key in wanted if key not in resolved]
    resolved.update(evaluate_keys(missing, repo_root))
    if set(resolved) != set(wanted):
        raise ValueError("fundamental status evaluation did not return every requested key")
    return resolved


def write_ledger(repo_root: Path | str, rows: Mapping[StatusKey, Mapping[str, str]]) -> Path:
    """Merge ``rows`` into the ledger without changing any fixed (non-retryable) entry."""

    path = Path(repo_root) / LEDGER_RELATIVE
    ledger = read_ledger(repo_root)
    for key, row in rows.items():
        existing = ledger.get(key)
        if existing is not None and existing["retryable"] != "true":
            if existing["fundamental_status"] != row["fundamental_status"]:
                raise ValueError(f"fixed fundamental status would change: {key}")
            continue
        ledger[key] = dict(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()
        for key in sorted(ledger):
            writer.writerow({column: ledger[key].get(column, "") for column in LEDGER_COLUMNS})
    return path
