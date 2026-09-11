#!/usr/bin/env python3
"""Run the bounded FastCore Fundamentals ABC V01 backtest.

The runner is cache-only by design. It consumes the frozen raw candidate and
CONTROL artifacts, the local Repository V2 market data, and local OpenDART
filing/XBRL caches through the canonical PIT periodization provider. It never
refreshes data or opens a market-data connection.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import gc
from pathlib import Path
import socket
import time
from typing import Any, Iterator, Mapping, Sequence

import pandas as pd

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    ABCEntryEvaluation,
    ABCQuarterEvent,
    event_versions,
    evaluate_entry,
)
from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    StrategyTradeRecord,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import FilingRegistry
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository

try:
    from scripts.run_fastcore_control import (
        COMMON_START_DATE, EFFECTIVE_AUTHORITY_DIR, EXECUTION_SUPPORT_END_DATE,
        EXPECTED_RAW_ROWS, EXPECTED_RAW_SHA256, RAW_CANDIDATE_PATH,
        SCORE_CONTRACT_PATH, SIGNAL_END_DATE, STAGE_CONTRACT_PATH,
        _authority_intervals, _overlap_count, _tasks_by_ticker, _validate_records,
        frozen_candidate_id, sha256_file, validate_frozen_inputs,
    )
except ModuleNotFoundError:
    from run_fastcore_control import (
        COMMON_START_DATE, EFFECTIVE_AUTHORITY_DIR, EXECUTION_SUPPORT_END_DATE,
        EXPECTED_RAW_ROWS, EXPECTED_RAW_SHA256, RAW_CANDIDATE_PATH,
        SCORE_CONTRACT_PATH, SIGNAL_END_DATE, STAGE_CONTRACT_PATH,
        _authority_intervals, _overlap_count, _tasks_by_ticker, _validate_records,
        frozen_candidate_id, sha256_file, validate_frozen_inputs,
    )


ROOT = Path(__file__).resolve().parents[1]
ABC_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc"
ABC_ENTRY_PATH = ABC_DIR / "fundamentals_abc_entry_evaluations.csv"
ABC_EXIT_PATH = ABC_DIR / "fundamentals_abc_exit_events.csv"
ABC_TRADES_PATH = ABC_DIR / "fundamentals_abc_trades.csv"
ABC_SUMMARY_PATH = ABC_DIR / "fundamentals_abc_summary.json"
COMPARISON_PATH = ABC_DIR / "control_vs_fundamentals_abc.json"
CONTROL_TRADES_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv"
CONTROL_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json"

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_FUNDAMENTALS_ABC_V01"
WORK_ID = "FASTCORE_SIMPLE_BACKTEST_WITH_FUNDAMENTALS_ABC_V01"


class NetworkRequestBlocked(RuntimeError):
    pass


class CacheEvaluationUnavailable(RuntimeError):
    pass


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"ABC cache-only guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"ABC cache-only guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _q_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year}Q{((timestamp.month - 1) // 3) + 1}"


def _company_payload(ticker: str) -> dict[str, Any] | None:
    path = ROOT / "data/cache/opendart/company" / f"{str(ticker)}.json"
    if not path.exists():
        return None
    try:
        payload = _json_read(path)
    except (OSError, ValueError, TypeError):
        return None
    if str(payload.get("status") or "") != "000":
        return None
    return payload


def _family(payload: Mapping[str, Any] | None) -> str:
    if payload is None:
        return CompanyFamily.UNKNOWN.value
    result = classify_company_family(payload, ())
    return str(result.get("company_family") or CompanyFamily.UNKNOWN.value)


class ObservationCatalog:
    """One ticker's canonical observations and cache-only load diagnostics."""

    def __init__(self, ticker: str, family: str) -> None:
        self.ticker = str(ticker)
        self.family = str(family)
        self.observations: list[Any] = []
        self.build_failures: list[dict[str, str]] = []
        self.events: list[ABCQuarterEvent] = []

    def add_build(self, build: Any) -> None:
        self.observations.extend(build.result.observations)

    def finalize(self) -> None:
        self.observations.sort(key=lambda item: (
            str(item.fiscal_year), str(item.fiscal_period), str(item.metric),
            str(item.pit_available_from or item.anchor_rcept_dt), str(item.anchor_rcept_no),
        ))
        if self.family == CompanyFamily.NON_FINANCIAL.value and self.observations:
            self.events = event_versions(self.observations, cutoff=EXECUTION_SUPPORT_END_DATE.date())


def _years_for_candidates(group: pd.DataFrame) -> range:
    years = pd.to_datetime(group["candidate_signal_information_date"], errors="raise").dt.year
    start = max(2015, int(years.min()) - 2)
    stop = min(2026, int(years.max()))
    return range(start, stop + 1)


def _load_catalog(
    ticker: str,
    group: pd.DataFrame,
    provider: PeriodizationProvider,
    *,
    diagnostics: dict[str, int],
) -> ObservationCatalog:
    payload = _company_payload(ticker)
    family = _family(payload)
    catalog = ObservationCatalog(ticker, family)
    if payload is None:
        diagnostics["company_cache_missing"] += 1
        return catalog
    if family != CompanyFamily.NON_FINANCIAL.value:
        diagnostics["non_nonfinancial_tickers"] += 1
        return catalog
    for year in _years_for_candidates(group):
        try:
            build = provider.build(
                ticker, str(year), EXECUTION_SUPPORT_END_DATE.date(),
                company_metadata=payload,
            )
            catalog.add_build(build)
            diagnostics["periodization_builds"] += 1
        except Exception as exc:
            # A missing local registry/XBRL cache is a bounded data gap. The
            # caller records it as unavailable; provider/parser exceptions
            # remain visible as evaluation errors in the summary.
            text = str(exc)
            classification = type(exc).__name__
            catalog.build_failures.append({"year": str(year), "error": classification, "message": text[:240]})
            diagnostics["cache_build_unavailable"] += 1
    catalog.finalize()
    return catalog


def _candidate_rows(candidates: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in candidates.to_dict(orient="records"):
        info_date = pd.Timestamp(record["candidate_signal_information_date"])
        if info_date < COMMON_START_DATE or info_date > SIGNAL_END_DATE:
            continue
        rows.append(record)
    return rows


def _evaluate_group(
    group: pd.DataFrame,
    catalog: ObservationCatalog,
    *,
    eval_rows: list[dict[str, Any]],
    evaluations: dict[tuple[str, str], ABCEntryEvaluation],
    diagnostics: dict[str, int],
) -> None:
    for candidate in _candidate_rows(group):
        candidate_id = str(candidate["candidate_id"])
        try:
            evaluation = evaluate_entry(
                str(candidate["ticker"]), catalog.family, catalog.observations,
                as_of=str(candidate["entry_signal_information_date"]),
            )
        except Exception:
            diagnostics["evaluation_errors"] += 1
            raise
        eval_rows.append(evaluation.to_row(candidate=candidate))
        evaluations[(candidate_id, str(candidate["entry_signal_information_date"]))] = evaluation
        diagnostics["entry_evaluations"] += 1


def _event_dict(event: ABCQuarterEvent, *, trade_id: str, execution_date: pd.Timestamp) -> dict[str, Any]:
    row = event.to_row(trade_id=trade_id)
    row.update({"proposed_execution_date": execution_date.strftime("%Y-%m-%d")})
    return row


def _events_for_entry(
    events: Sequence[ABCQuarterEvent],
    *,
    entry_signal_date: Any,
    entry_execution_date: Any,
    daily: pd.DataFrame,
    backtest_end: pd.Timestamp,
) -> list[dict[str, Any]]:
    signal = pd.Timestamp(entry_signal_date).normalize()
    entry = pd.Timestamp(entry_execution_date).normalize()
    result: list[dict[str, Any]] = []
    for event in events:
        info = pd.Timestamp(event.fundamental_information_date).normalize()
        if info <= signal or info < entry or info > backtest_end:
            continue
        future = daily[(daily.index > info) & (daily.index <= backtest_end)]
        if future.empty:
            continue
        execution = future.index[0]
        if execution <= entry:
            continue
        result.append(_event_dict(event, trade_id="", execution_date=execution))
    return sorted(result, key=lambda row: (str(row["proposed_execution_date"]), str(row["quarter"])))


def _base_trade_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, int]:
    return (
        str(row.get("ticker") or ""), str(row.get("isu_cd") or ""), str(row.get("market") or ""),
        str(row.get("entry_signal_date") or ""), int(row.get("trade_sequence") or 0),
    )


def _trade_frame(
    records: Sequence[StrategyTradeRecord],
    eval_by_key: Mapping[tuple[str, str, str, str], ABCEntryEvaluation],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        row = record.to_dict()
        eval_key = (str(record.ticker), str(record.isu_cd or ""), str(record.market), str(record.entry_signal_date))
        entry = eval_by_key.get(eval_key)
        meta = getattr(record, "_fundamental_exit_meta", None)
        row.update({
            "entry_fundamentals_gate_pass": bool(entry and entry.abc_entry_gate_pass),
            "entry_latest_fy": entry.latest_fy if entry else None,
            "entry_annual_revenue": entry.annual_revenue if entry else None,
            "entry_annual_operating_income": entry.annual_operating_income if entry else None,
            "entry_latest_quarter": entry.latest_quarter if entry else None,
            "entry_quarter_revenue": entry.quarter_revenue if entry else None,
            "entry_quarter_operating_income": entry.quarter_operating_income if entry else None,
            "entry_revenue_yoy_pct": entry.revenue_yoy_pct if entry else None,
            "entry_operating_income_yoy_pct": entry.operating_income_yoy_pct if entry else None,
            "entry_operating_income_growth_mode": entry.operating_income_growth_mode if entry else None,
            "fundamental_exit_triggered": bool(meta),
            "fundamental_exit_primary_type": meta.get("fundamental_primary_trigger") if meta else None,
            "fundamental_exit_all_flags": "|".join(meta.get("all_flags", "").split("|") if meta else []),
            "fundamental_exit_signal_information_date": meta.get("fundamental_information_date") if meta else None,
            "fundamental_exit_execution_date": meta.get("proposed_execution_date") if meta else None,
            "fundamental_exit_accelerated": bool(meta and meta.get("fundamental_exit_accelerated")),
        })
        rows.append(row)
    columns = list(rows[0].keys()) if rows else []
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["ticker", "entry_signal_information_date", "trade_sequence", "trade_id"], kind="mergesort").reset_index(drop=True)
    return frame


def _entry_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if not frame.empty:
        frame = frame.sort_values(["candidate_signal_date", "candidate_id"], kind="mergesort").reset_index(drop=True)
    return frame


def _exit_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if not frame.empty:
        frame = frame.sort_values(["ticker", "trade_id", "fundamental_information_date", "quarter"], kind="mergesort").reset_index(drop=True)
    return frame


def _numeric_stats(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    if frame.empty or column not in frame:
        return None, None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    total = len(frame)
    terminal = pd.to_numeric(frame.get("terminal_return", pd.Series(dtype=float)), errors="coerce")
    positive = int((terminal > 0).sum())
    mean_return, median_return = _numeric_stats(frame, "terminal_return")
    mean_mfe, median_mfe = _numeric_stats(frame, "mfe")
    mean_mae, median_mae = _numeric_stats(frame, "mae")
    mean_holding, median_holding = _numeric_stats(frame, "holding_trading_days")
    seq = pd.to_numeric(frame.get("trade_sequence", pd.Series(dtype=float)), errors="coerce")
    return {
        "total_trades": total,
        "unique_tickers": int(frame["ticker"].nunique()) if total else 0,
        "first_entry_count": int((seq == 1).sum()) if total else 0,
        "reentry_count": int((seq > 1).sum()) if total else 0,
        "closed_trade_count": int((frame["trade_status"] == "REALIZED").sum()) if total else 0,
        "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()) if total else 0,
        "positive_trade_count": positive,
        "positive_trade_rate": round(positive / total * 100, 6) if total else None,
        "mean_terminal_return": mean_return,
        "median_terminal_return": median_return,
        "mean_mfe": mean_mfe,
        "median_mfe": median_mfe,
        "mean_mae": mean_mae,
        "median_mae": median_mae,
        "mean_holding_trading_days": mean_holding,
        "median_holding_trading_days": median_holding,
        "loss_guard_trade_count": int(frame["loss_guard_triggered"].fillna(False).astype(bool).sum()) if total else 0,
        "loss_guard_rate": round(int(frame["loss_guard_triggered"].fillna(False).astype(bool).sum()) / total * 100, 6) if total else None,
        "exit_type_counts": {str(key): int(value) for key, value in frame["exit_type"].value_counts().sort_index().items()} if total else {},
        "tail_counts": {
            "terminal_return_le_neg_15_pct_points": int((terminal <= -15).sum()),
            "terminal_return_le_neg_20_pct_points": int((terminal <= -20).sum()),
            "terminal_return_le_neg_30_pct_points": int((terminal <= -30).sum()),
            "terminal_return_le_neg_40_pct_points": int((terminal <= -40).sum()),
        },
        "winner_counts": {
            "terminal_return_ge_pos_30_pct_points": int((terminal >= 30).sum()),
            "terminal_return_ge_pos_50_pct_points": int((terminal >= 50).sum()),
            "terminal_return_ge_pos_100_pct_points": int((terminal >= 100).sum()),
        },
    }


def _comparison(control: pd.DataFrame, abc: pd.DataFrame) -> dict[str, Any]:
    def keys(frame: pd.DataFrame) -> set[tuple[str, str, str, str, int]]:
        return {_base_trade_key(row) for row in frame.to_dict(orient="records")}

    control_keys = keys(control)
    abc_keys = keys(abc)
    c_terminal = pd.to_numeric(control.get("terminal_return", pd.Series(dtype=float)), errors="coerce")
    a_terminal = pd.to_numeric(abc.get("terminal_return", pd.Series(dtype=float)), errors="coerce")
    c50 = {_base_trade_key(row) for row in control[control["terminal_return"] >= 50].to_dict(orient="records")} if not control.empty else set()
    return {
        "control": _trade_metrics(control),
        "fundamentals_abc": _trade_metrics(abc),
        "delta": {
            "total_trades": len(abc) - len(control),
            "positive_trade_rate_pp": round(float((a_terminal > 0).mean() * 100 - (c_terminal > 0).mean() * 100), 6) if len(control) and len(abc) else None,
            "mean_terminal_return_pp": round(float(a_terminal.mean() - c_terminal.mean()), 6) if len(control) and len(abc) else None,
            "median_terminal_return_pp": round(float(a_terminal.median() - c_terminal.median()), 6) if len(control) and len(abc) else None,
            "loss_guard_trade_count": _trade_metrics(abc)["loss_guard_trade_count"] - _trade_metrics(control)["loss_guard_trade_count"],
        },
        "exact_entry_candidate_match": {
            "control_trade_key_count": len(control_keys),
            "abc_trade_key_count": len(abc_keys),
            "control_keys_retained": len(control_keys & abc_keys),
            "control_keys_missing": len(control_keys - abc_keys),
            "abc_only_new_entries": len(abc_keys - control_keys),
        },
        "control_winners_retained": {
            "terminal_return_ge_50_count": len(c50),
            "terminal_return_ge_50_retained": len(c50 & abc_keys),
            "all_retained": c50.issubset(abc_keys),
        },
        "raw_control_artifacts_read_only": True,
    }


def _preflight(candidates: pd.DataFrame, entry_frame: pd.DataFrame) -> dict[str, Any]:
    required = ["2021Q2", "2021Q3", "2021Q4", "2022Q1"]
    rows = candidates.copy()
    rows["preflight_quarter"] = pd.to_datetime(rows["candidate_signal_information_date"]).map(_q_label)
    rows = rows[(rows["candidate_signal_information_date"] >= COMMON_START_DATE.strftime("%Y-%m-%d"))]
    if not entry_frame.empty:
        family_map = entry_frame[["candidate_id", "company_family"]].drop_duplicates("candidate_id")
        rows = rows.merge(family_map, on="candidate_id", how="left")
        rows = rows[rows["company_family"] == CompanyFamily.NON_FINANCIAL.value]
    else:
        rows = rows.iloc[0:0]
    details: dict[str, Any] = {}
    for quarter in required:
        base = rows[rows["preflight_quarter"] == quarter]
        evaluated = entry_frame[entry_frame["candidate_id"].isin(set(base["candidate_id"].astype(str)))] if not entry_frame.empty else entry_frame
        evaluable = int(evaluated["abc_entry_evaluable"].fillna(False).astype(bool).sum()) if not evaluated.empty else 0
        errors = int(evaluated["status"].astype(str).eq("EVALUATION_ERROR").sum()) if not evaluated.empty else 0
        details[quarter] = {
            "non_financial_candidate_count": int(len(base)),
            "evaluated_count": int(len(evaluated)),
            "evaluable_count": evaluable,
            "evaluable_rate_pct": round(evaluable / len(base) * 100, 6) if len(base) else None,
            "evaluation_error_count": errors,
            "pass": bool(len(base) and evaluable / len(base) >= 0.90 and errors == 0),
        }
    return {
        "required_rate_pct": 90.0,
        "quarters": details,
        "pass": all(bool(item["pass"]) for item in details.values()),
    }


def _summary(
    *,
    candidates: pd.DataFrame,
    entry_frame: pd.DataFrame,
    exit_frame: pd.DataFrame,
    trade_frame: pd.DataFrame,
    preflight: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    validation: Mapping[str, Any],
    network_requests: int,
    loader_count: int,
    authority_sha256: str,
    authority_interval_count: int,
    status: str,
) -> dict[str, Any]:
    pass_count = int(entry_frame["abc_entry_gate_pass"].fillna(False).astype(bool).sum()) if not entry_frame.empty else 0
    evaluable_count = int(entry_frame["abc_entry_evaluable"].fillna(False).astype(bool).sum()) if not entry_frame.empty else 0
    family_counts = entry_frame["company_family"].value_counts().to_dict() if not entry_frame.empty else {}
    reject_counts: dict[str, int] = {}
    if not entry_frame.empty:
        for value in entry_frame["reject_reasons"].fillna("").astype(str):
            for reason in filter(None, value.split("|")):
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
    event_flags = {flag: int(exit_frame["all_flags"].fillna("").astype(str).str.contains(flag, regex=False).sum()) for flag in (
        "FUNDAMENTAL_A_OPERATING_LOSS", "FUNDAMENTAL_B_SHARP_DECLINE", "FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES",
    )} if not exit_frame.empty else {}
    return {
        "work_id": WORK_ID,
        "status": status,
        "common_start_date": COMMON_START_DATE.strftime("%Y-%m-%d"),
        "signal_end_date": SIGNAL_END_DATE.strftime("%Y-%m-%d"),
        "execution_support_end_date": EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d"),
        "raw_candidate_count": EXPECTED_RAW_ROWS,
        "raw_candidate_sha256": sha256_file(RAW_CANDIDATE_PATH),
        "strategy_id": STRATEGY_ID,
        "fundamentals_gate": "ABC_V01",
        "experimental_investability_conditions": {
            "market_cap_min_krw": 300_000_000_000,
            "avg_trading_value_20d_min_krw": 300_000_000,
            "close_min_krw": 5_000,
        },
        "execution_semantics": "next local trading day open",
        "reentry_semantics": "V2 re-entry after realized exit; no overlap or pyramiding",
        "return_unit": "percentage_points",
        "abc_entry_coverage_preflight": dict(preflight),
        "entry_coverage": {
            "window_candidate_count": int(len(entry_frame)),
            "company_family_counts": {str(k): int(v) for k, v in family_counts.items()},
            "evaluable_count": evaluable_count,
            "gate_pass_count": pass_count,
            "reject_reason_counts": reject_counts,
        },
        "trade_metrics": _trade_metrics(trade_frame),
        "fundamental_exit_metrics": {
            "event_row_count": int(len(exit_frame)),
            "flag_counts": event_flags,
            "primary_trigger_counts": {str(k): int(v) for k, v in exit_frame["fundamental_primary_trigger"].value_counts(dropna=True).items()} if not exit_frame.empty else {},
            "accelerated_count": int(exit_frame["fundamental_exit_accelerated"].fillna(False).astype(bool).sum()) if not exit_frame.empty else 0,
            "same_execution_tie_count": int(validation.get("fundamental_same_open_ties", 0)),
            "evaluable_event_count": int(exit_frame[["exit_a_evaluable", "exit_b_evaluable", "exit_c_evaluable"]].any(axis=1).sum()) if not exit_frame.empty else 0,
        },
        "network_call_counts": {
            "krx_open_api": 0, "opendart": 0, "pykrx": 0, "naver": 0, "krx_html": 0,
            "socket_attempts": network_requests, "repository_v2_local_loads": loader_count,
        },
        "authority": {"effective_pit_sha256": authority_sha256, "effective_pit_interval_count": authority_interval_count},
        "diagnostics": dict(diagnostics),
        "validation": dict(validation),
        "determinism": {"status": "PENDING"},
        "artifacts": {
            "fundamentals_abc_entry_evaluations_csv": str(ABC_ENTRY_PATH.relative_to(ROOT)),
            "fundamentals_abc_exit_events_csv": str(ABC_EXIT_PATH.relative_to(ROOT)),
            "fundamentals_abc_trades_csv": str(ABC_TRADES_PATH.relative_to(ROOT)),
            "fundamentals_abc_summary_json": str(ABC_SUMMARY_PATH.relative_to(ROOT)),
            "control_vs_fundamentals_abc_json": str(COMPARISON_PATH.relative_to(ROOT)),
        },
    }


def run_pipeline(*, require_preflight: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    candidates = validate_frozen_inputs()
    raw_control_trades = CONTROL_TRADES_PATH.read_bytes()
    raw_control_summary = CONTROL_SUMMARY_PATH.read_bytes()
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority)
    tasks_by_ticker = _tasks_by_ticker(candidates)
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    provider = PeriodizationProvider(
        corp,
        FilingRegistry(None, cache_dir=ROOT / "data/cache/opendart/filings"),
        XbrlRepository(None, cache_dir=ROOT / "data/cache/opendart/xbrl"),
    )
    entry_rows: list[dict[str, Any]] = []
    evaluations: dict[tuple[str, str], ABCEntryEvaluation] = {}
    catalogs: dict[str, ObservationCatalog] = {}
    diagnostics: dict[str, Any] = {
        "periodization_builds": 0, "cache_build_unavailable": 0, "company_cache_missing": 0,
        "non_nonfinancial_tickers": 0, "entry_evaluations": 0, "evaluation_errors": 0,
        "catalog_tickers": 0,
    }
    all_candidates = candidates[candidates["candidate_signal_information_date"] >= COMMON_START_DATE.strftime("%Y-%m-%d")].copy()
    for ticker, group in all_candidates.groupby("ticker", sort=True):
        catalog = _load_catalog(str(ticker), group, provider, diagnostics=diagnostics)
        catalogs[str(ticker)] = catalog
        _evaluate_group(group, catalog, eval_rows=entry_rows, evaluations=evaluations, diagnostics=diagnostics)
        diagnostics["catalog_tickers"] += 1
        if diagnostics["catalog_tickers"] % 50 == 0:
            print(f"ABC fundamentals progress: {diagnostics['catalog_tickers']}/{len(tasks_by_ticker)} tickers, entries={len(entry_rows)}", flush=True)

    entry_frame = _entry_frame(entry_rows)
    # Entry evaluation is complete. The simulation only needs the immutable
    # quarter-event lists; retaining every canonical observation across all
    # 691 tickers causes Repository V2 daily loads to compete for memory.
    for catalog in catalogs.values():
        catalog.observations.clear()
    gc.collect()
    preflight = _preflight(all_candidates, entry_frame)
    if require_preflight and not preflight["pass"]:
        validation = {
            "raw_candidate_hash_unchanged": sha256_file(RAW_CANDIDATE_PATH) == EXPECTED_RAW_SHA256,
            "control_artifacts_unchanged": CONTROL_TRADES_PATH.read_bytes() == raw_control_trades and CONTROL_SUMMARY_PATH.read_bytes() == raw_control_summary,
            "network_calls": 0,
        }
        summary = _summary(
            candidates=all_candidates, entry_frame=entry_frame, exit_frame=pd.DataFrame(), trade_frame=pd.DataFrame(),
            preflight=preflight, diagnostics=diagnostics, validation=validation, network_requests=0,
            loader_count=0, authority_sha256=authority.pit_sha256, authority_interval_count=authority.pit_count,
            status="BLOCKED_PREFLIGHT",
        )
        return entry_frame, pd.DataFrame(), pd.DataFrame(), summary, {"control_trades": raw_control_trades, "control_summary": raw_control_summary}

    repository = build_repository_v2(ROOT, end=EXECUTION_SUPPORT_END_DATE)
    loader = RepositoryV2DailyLoader(repository, end=EXECUTION_SUPPORT_END_DATE)
    records: list[StrategyTradeRecord] = []
    exit_rows: list[dict[str, Any]] = []
    eval_by_trade_key: dict[tuple[str, str, str, str], ABCEntryEvaluation] = {}
    validation: dict[str, Any] = {
        "raw_candidate_hash_unchanged": sha256_file(RAW_CANDIDATE_PATH) == EXPECTED_RAW_SHA256,
        "control_artifacts_unchanged": CONTROL_TRADES_PATH.read_bytes() == raw_control_trades and CONTROL_SUMMARY_PATH.read_bytes() == raw_control_summary,
        "pre_start_entry_violations": 0, "post_end_signal_violations": 0, "identity_violations": 0,
        "execution_next_day_violations": 0, "overlapping_positions": 0, "pit_future_membership_fallback": 0,
        "entry_gate_future_source_violations": 0, "entry_nonfinancial_violations": 0,
        "fundamental_exit_data_unavailable_violations": 0, "fundamental_b_and_logic_violations": 0,
        "fundamental_c_logic_violations": 0, "fundamental_same_open_ties": 0,
        "evaluation_errors": int(diagnostics["evaluation_errors"]), "network_calls": 0,
    }
    for processed_ticker, ticker in enumerate(sorted(tasks_by_ticker), 1):
        daily = loader.load(str(ticker))
        if daily is None or daily.empty:
            raise RuntimeError(f"missing Repository V2 daily data for raw candidate ticker {ticker}")
        catalog = catalogs.get(str(ticker), ObservationCatalog(str(ticker), CompanyFamily.UNKNOWN.value))
        tasks = tasks_by_ticker[str(ticker)]
        for task in tasks:
            lifecycle = IdentityLifecycle(
                ticker=str(task["ticker"]), isu_cd=str(task["isu_cd"]), market=str(task["market"]),
                effective_from=pd.Timestamp(task["effective_from"]), effective_to=pd.Timestamp(task["effective_to"]),
            )
            raw_panel = task["raw_panel"]
            allowed_ids = task["allowed_candidate_ids"]

            def gate(_as_of: pd.Timestamp, context: dict[str, Any], *, lifecycle=lifecycle, allowed_ids=allowed_ids) -> dict[str, Any]:
                signal = pd.Timestamp(context["signal_date"]).normalize()
                cid = frozen_candidate_id(lifecycle.ticker, lifecycle.isu_cd, lifecycle.market, signal)
                base_pass = cid in allowed_ids and COMMON_START_DATE <= signal <= SIGNAL_END_DATE
                information_key = pd.Timestamp(context.get("signal_information_date")).strftime("%Y-%m-%d")
                evaluation = evaluations.get((cid, information_key))
                abc_pass = bool(evaluation and evaluation.abc_entry_gate_pass)
                if evaluation is not None:
                    source_dates = [value for value in evaluation.selected_source_receipt_dates.split("|") if value]
                    if any(value > str(context.get("signal_information_date"))[:10] for value in source_dates):
                        validation["entry_gate_future_source_violations"] += 1
                    if evaluation.company_family != CompanyFamily.NON_FINANCIAL.value:
                        validation["entry_nonfinancial_violations"] += 1
                return {"gate_pass": base_pass and abc_pass, "gate_id": "FROZEN_RAW_AND_FUNDAMENTALS_ABC_V01"}

            def fundamental_callback(signal: pd.Timestamp, entry_exec: pd.Timestamp, identity_daily: pd.DataFrame, *, catalog=catalog) -> Sequence[Mapping[str, Any]]:
                return _events_for_entry(catalog.events, entry_signal_date=signal, entry_execution_date=entry_exec,
                                         daily=identity_daily, backtest_end=EXECUTION_SUPPORT_END_DATE)

            task_records = simulate_ticker_strategy_fundamentals_v01(
                strategy_id=STRATEGY_ID, ticker=lifecycle.ticker, isu_cd=lifecycle.isu_cd,
                name=str(task["name"]), market=lifecycle.market, daily=daily, raw_panel=raw_panel,
                score_contract=score_contract, stage_contract=stage_contract, loss_guard_enabled=True,
                backtest_end=EXECUTION_SUPPORT_END_DATE, entry_eligible_from=COMMON_START_DATE,
                allowed_signal_dates=task["allowed_signal_dates"], identity_lifecycle=lifecycle,
                pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                    intervals, ticker_value, isu_value, market_value, value,
                ), entry_gate=gate, fundamental_exit_callback=fundamental_callback,
            )
            task_validation = _validate_records(task_records, daily=daily, lifecycle=lifecycle, intervals=intervals)
            for key in ("pre_start_entry_violations", "post_end_signal_violations", "identity_violations", "execution_next_day_violations"):
                validation[key] += task_validation[key]
            validation["pit_future_membership_fallback"] += task_validation["pit_membership_violations"]
            for record in task_records:
                eval_key = (str(record.ticker), str(record.isu_cd or ""), str(record.market), str(record.entry_signal_date))
                if eval_key in eval_by_trade_key:
                    raise RuntimeError(f"duplicate ABC entry evaluation key: {eval_key}")
                evaluation = evaluations.get((frozen_candidate_id(record.ticker, record.isu_cd or "", record.market, record.entry_signal_date), str(record.entry_signal_information_date)))
                if evaluation is None:
                    validation["entry_nonfinancial_violations"] += 1
                else:
                    eval_by_trade_key[eval_key] = evaluation
                considered = _events_for_entry(catalog.events, entry_signal_date=record.entry_signal_date,
                                               entry_execution_date=record.entry_execution_date, daily=daily,
                                               backtest_end=EXECUTION_SUPPORT_END_DATE)
                selected_meta = getattr(record, "_fundamental_exit_meta", None)
                for event_row in considered:
                    event_row = dict(event_row)
                    event_row.update({"trade_id": record.trade_id, "isu_cd": record.isu_cd, "market": record.market})
                    selected_info = selected_meta.get("fundamental_information_date") if selected_meta else None
                    event_row["fundamental_exit_accelerated"] = bool(selected_meta and selected_info == event_row["fundamental_information_date"])
                    if not all((not event_row["exit_b_triggered"]) or (event_row["revenue_yoy_pct"] is not None and event_row["operating_income_yoy_pct"] is not None and event_row["revenue_yoy_pct"] <= -10 and event_row["operating_income_yoy_pct"] <= -20) for _ in [0]):
                        validation["fundamental_b_and_logic_violations"] += 1
                    if event_row["exit_c_triggered"] and not (event_row["previous_quarter_revenue_declined_yoy"] and event_row["previous_quarter_operating_income_declined_yoy"]):
                        validation["fundamental_c_logic_violations"] += 1
                    exit_rows.append(event_row)
            records.extend(task_records)
            del raw_panel
        del daily
        # Catalog observations are only needed while this ticker's tasks are
        # simulated. Releasing them here prevents the bounded ABC run from
        # retaining hundreds of ticker histories and exhausting memory before
        # the Repository V2 loader reaches the end of the universe.
        catalogs.pop(str(ticker), None)
        if processed_ticker % 25 == 0:
            gc.collect()

    validation["overlapping_positions"] = _overlap_count(records)
    trade_frame = _trade_frame(records, eval_by_trade_key)
    exit_frame = _exit_frame(exit_rows)
    comparison = _comparison(pd.read_csv(CONTROL_TRADES_PATH), trade_frame)
    validation["fundamental_exit_data_unavailable_violations"] = int(exit_frame["all_flags"].fillna("").astype(str).str.contains("DATA_UNAVAILABLE", regex=False).sum()) if not exit_frame.empty else 0
    boolean_checks = {"raw_candidate_hash_unchanged", "control_artifacts_unchanged"}
    invalid = any(
        (not bool(value)) if key in boolean_checks else (int(value) != 0)
        for key, value in validation.items() if key != "network_calls"
    )
    status = "COMPLETE" if not invalid else "BLOCKED_VALIDATION"
    summary = _summary(
        candidates=all_candidates, entry_frame=entry_frame, exit_frame=exit_frame, trade_frame=trade_frame,
        preflight=preflight, diagnostics=diagnostics, validation=validation, network_requests=0,
        loader_count=loader.load_count, authority_sha256=authority.pit_sha256, authority_interval_count=authority.pit_count,
        status=status,
    )
    return entry_frame, exit_frame, trade_frame, summary, comparison


def write_outputs(entry_frame: pd.DataFrame, exit_frame: pd.DataFrame, trade_frame: pd.DataFrame,
                  summary: Mapping[str, Any], comparison: Mapping[str, Any]) -> None:
    ABC_DIR.mkdir(parents=True, exist_ok=True)
    entry_frame.to_csv(ABC_ENTRY_PATH, index=False, lineterminator="\n")
    exit_frame.to_csv(ABC_EXIT_PATH, index=False, lineterminator="\n")
    trade_frame.to_csv(ABC_TRADES_PATH, index=False, lineterminator="\n")
    _json_write(ABC_SUMMARY_PATH, summary)
    _json_write(COMPARISON_PATH, comparison)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--verify-determinism", action="store_true")
    args = parser.parse_args()
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            result = run_pipeline(require_preflight=True)
            entry_frame, exit_frame, trade_frame, summary, comparison = result
            summary = dict(summary)
            summary["network_call_counts"]["socket_attempts"] = audit.request_count
            summary["validation"]["network_calls"] = audit.request_count
            if args.preflight_only or summary.get("status") == "BLOCKED_PREFLIGHT":
                write_outputs(entry_frame, exit_frame, trade_frame, summary, comparison)
                print(json.dumps(summary["abc_entry_coverage_preflight"], ensure_ascii=False), flush=True)
                return 0 if summary.get("status") == "COMPLETE" else 2
            write_outputs(entry_frame, exit_frame, trade_frame, summary, comparison)
            if args.verify_determinism:
                replay = run_pipeline(require_preflight=True)
                replay_frames = replay[:3]
                replay_summary = replay[3]
                same = all(
                    left.to_csv(index=False, lineterminator="\n") == right.to_csv(index=False, lineterminator="\n")
                    for left, right in zip((entry_frame, exit_frame, trade_frame), replay_frames)
                )
                core_keys = [key for key in summary if key != "determinism"]
                core_same = all(summary.get(key) == replay_summary.get(key) for key in core_keys)
                summary["determinism"] = {"status": "PASS" if same and core_same else "FAIL", "artifact_content_same": same, "summary_core_same": core_same}
                _json_write(ABC_SUMMARY_PATH, summary)
                if not same or not core_same:
                    return 1
            print(f"ABC complete: trades={len(trade_frame)}, entries={len(entry_frame)}, exits={len(exit_frame)}", flush=True)
            return 0 if summary.get("status") == "COMPLETE" and audit.request_count == 0 else 1
    except Exception as exc:
        print(f"ABC BLOCKED: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
