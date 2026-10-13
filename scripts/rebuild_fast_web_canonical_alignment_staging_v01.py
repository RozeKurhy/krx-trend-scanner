#!/usr/bin/env python3
"""Build an isolated FAST Core V2 Alignment 500B full-history web candidate.

This runner reads the exact current Stock Report corpus and rolling market-data
authority. It writes only below a new staging directory; it never edits
operational configuration, activation history, canonical Stock Reports, or
``web/data``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any

import pandas as pd

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_loader import (
    RepositoryV2DailyLoader,
    build_repository_v2,
)
from trend_scanner.filters.investability import evaluate_investability
from trend_scanner.reporting.a_fast_core_report import (
    HISTORICAL_ALIGNMENT_REPLAY_MODE,
    build_a_fast_core_section,
)
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    AlignmentGateIntegrityError,
    PROMOTED_STRATEGY_ID,
    PROMOTED_STRATEGY_NAME,
    get_historical_alignment_replay_gate,
    load_activation_history,
    load_promotion_config,
)


ROOT = Path(__file__).resolve().parents[1]
SCANNER_ROOT = ROOT / "artifacts/patterns/pattern_a/production/scanner"
STOCK_INDEX_PATH = ROOT / "web/data/stock-index.json"
STOCK_REPORTS_ROOT = ROOT / "artifacts/reporting/stock_reports"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
CONFIG_REL = Path("artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_operational_config.json")
HISTORY_REL = Path("artifacts/patterns/pattern_a_fast/production/alignment_mcap_500b_activation_history.json")
STAGING_PARENT = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_web_canonical_full_history_rebuild_v01"
FULL_HISTORY_WEB_MODE = "FULL_HISTORY_ALIGNMENT_WEB"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        import csv

        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_export_modules() -> tuple[Any, Any]:
    """Load sibling exporters by file path; ``scripts`` is not a Python package."""
    loaded = []
    for name, path in (
        ("krx_stock_report_web_exporter", ROOT / "scripts/export_stock_report_web.py"),
        ("krx_strategy_monitor_web_exporter", ROOT / "scripts/export_strategy_monitor_web.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load web exporter module: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded[0], loaded[1]


def _scanner_dates(target_as_of: str | None) -> tuple[str, str, dict[str, Any]]:
    index = read_json(STOCK_INDEX_PATH)
    requested = target_as_of or str(index.get("requested_as_of") or "")[:10]
    if not DATE_RE.fullmatch(requested):
        raise ValueError("stock index has no exact requested_as_of")
    summary_path = SCANNER_ROOT / f"pattern_a_universe_scan_{requested.replace('-', '')}_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"exact-target scanner summary missing: {summary_path}")
    summary = read_json(summary_path)
    reference = str(summary.get("reference_market_date") or "")[:10]
    if summary.get("requested_as_of") != requested or not DATE_RE.fullmatch(reference) or reference > requested:
        raise ValueError("scanner summary date contract is invalid")
    if (
        index.get("requested_as_of") != requested
        or index.get("reference_market_date") != reference
    ):
        raise ValueError("stock index dates do not match the exact scanner summary")
    if int(summary.get("scanner_error_count", -1)) != 0:
        raise ValueError("exact-target scanner summary has errors")
    return requested, reference, summary


def _report_sources(target_as_of: str) -> tuple[Path, list[Path], set[str]]:
    report_dir = STOCK_REPORTS_ROOT / target_as_of.replace("-", "")
    json_dir = report_dir / "json"
    if not json_dir.is_dir():
        raise FileNotFoundError(f"exact-target Stock Report directory missing: {json_dir}")
    index = read_json(STOCK_INDEX_PATH)
    common_tickers = {
        str(item.get("ticker") or "").zfill(6)
        for item in index.get("items", [])
        if item.get("report_available") is True and item.get("asset_type") == "COMMON"
    }
    paths = sorted(json_dir.glob("*.json"))
    file_tickers = [str(read_json(path).get("ticker") or "").zfill(6) for path in paths]
    if len(file_tickers) != len(set(file_tickers)) or set(file_tickers) != common_tickers:
        raise ValueError(
            f"exact COMMON report scope mismatch: files={len(file_tickers)} index={len(common_tickers)}"
        )
    return report_dir, paths, common_tickers


def _summary_bullet(core: dict[str, Any]) -> str:
    state = str(core.get("strategy_state") or "DATA_UNAVAILABLE")
    trade = core.get("current_trade") or {}
    sequence = trade.get("trade_sequence")
    if state == "HOLD_PROGRESSED":
        detail = f"HOLD_PROGRESSED · 현재 {sequence}번째 포지션 보유"
    elif state == "HOLD_PRE_PROGRESSED":
        detail = f"HOLD_PRE_PROGRESSED · 현재 {sequence}번째 포지션 보유 (Loss Guard 활성)"
    elif state == "ENTRY":
        detail = "신규 진입 조건 충족 · 다음 거래일 시가 진입 신호"
    elif state == "EXIT":
        detail = f"청산 신호 발생({core.get('action_reason')}) · 다음 거래일 시가 청산"
    elif state == "WAIT":
        detail = "관망 · 현재 신규 진입 조건 미충족"
    elif state == "NOT_APPLICABLE":
        detail = "전략 적용 대상 아님"
    else:
        detail = "데이터 부족으로 현재 상태 판정 불가"
    return f"{PROMOTED_STRATEGY_NAME}: {detail}"


def _validate_trade_rows(ticker: str, history: list[dict[str, Any]]) -> None:
    sequences = []
    for row in history:
        if any(row.get(field) != PROMOTED_STRATEGY_ID for field in (
            "strategy_id", "entry_strategy_id", "exit_strategy_id",
        )):
            raise ValueError(f"non-Alignment lineage in staged history: {ticker}")
        if not DATE_RE.fullmatch(str(row.get("entry_signal_date") or "")):
            raise ValueError(f"invalid entry_signal_date in staged history: {ticker}")
        if not DATE_RE.fullmatch(str(row.get("entry_execution_date") or "")):
            raise ValueError(f"invalid entry_execution_date in staged history: {ticker}")
        if row["entry_signal_date"] >= row["entry_execution_date"]:
            raise ValueError(f"entry execution must follow its signal: {ticker}")
        if row.get("trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"}:
            raise ValueError(f"unexpected lifecycle status in staged history: {ticker}")
        sequences.append(int(row.get("trade_sequence", 0)))
        expected_trade_id = f"{ticker}_{int(row.get('trade_sequence', 0)):02d}"
        if row.get("trade_id") != expected_trade_id:
            raise ValueError(f"trade ID does not match ticker/sequence: {ticker}")
    if sequences != list(range(1, len(sequences) + 1)):
        raise ValueError(f"trade sequence is not contiguous from one: {ticker}")


def _normalize_trade_key(ticker: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        ticker,
        int(row["trade_sequence"]),
        str(row["entry_signal_date"]),
        str(row["entry_execution_date"]),
    )


def _project_signature(ticker: str, row: dict[str, Any], source: str) -> tuple[Any, ...]:
    if source == "report":
        return (
            _normalize_trade_key(ticker, row),
            row.get("trade_id"),
            row.get("strategy_id"), row.get("entry_strategy_id"), row.get("exit_strategy_id"),
            row.get("entry_open"), row.get("exit_type") if row.get("exit_execution_date") else None,
            row.get("exit_signal_date"),
            row.get("exit_execution_date"), row.get("exit_price"), row.get("return_pct"),
            row.get("trade_status"),
        )
    if source == "monitor":
        return (
            _normalize_trade_key(str(row["ticker"]).zfill(6), row),
            row.get("trade_id"),
            row.get("strategy_id"), row.get("entry_strategy_id"), row.get("exit_strategy_id"),
            row.get("entry_price"), row.get("exit_reason"), row.get("exit_signal_date"),
            row.get("exit_execution_date"), row.get("exit_price"), row.get("return_pct"),
            row.get("trade_status"),
        )
    raise ValueError(source)


def _validate_open_trade_status_pair(current_trade: dict[str, Any], open_history: dict[str, Any]) -> None:
    """The current-position projection uses OPEN; history uses OPEN_AT_CUTOFF."""
    if current_trade.get("trade_status") != "OPEN" or open_history.get("trade_status") != "OPEN_AT_CUTOFF":
        raise ValueError("Stock Report current position and OPEN history statuses are inconsistent")


def _verify_three_way_parity(stage_root: Path, target_as_of: str, reference_market_date: str,
                             index: dict[str, Any], monitor: dict[str, Any],
                             old_monitor: dict[str, Any]) -> dict[str, Any]:
    stocks_dir = stage_root / "web/stocks"
    source_dir = stage_root / "reports" / target_as_of.replace("-", "") / "json"
    fast_rows = [row for row in monitor["strategies"] if row.get("id") in {
        "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        PROMOTED_STRATEGY_ID,
    }]
    if len(fast_rows) != 1 or fast_rows[0].get("id") != PROMOTED_STRATEGY_ID:
        raise ValueError("Strategy Monitor does not contain exactly one Alignment FAST row")
    fast = fast_rows[0]
    if (
        monitor.get("strategy_replay_mode") != FULL_HISTORY_WEB_MODE
        or monitor.get("strategy_replay_digest") != fast.get("strategy_replay_digest")
        or monitor.get("strategy_replay_scope") != fast.get("strategy_replay_scope")
    ):
        raise ValueError("Strategy Monitor root replay provenance differs from its FAST row")
    source_by_key: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    web_by_key: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    source_history_count = 0
    web_history_count = 0
    open_source: dict[tuple[Any, ...], dict[str, Any]] = {}
    open_monitor: dict[tuple[Any, ...], dict[str, Any]] = {}
    ticker_map = {
        str(item["ticker"]).zfill(6): item
        for item in index.get("items", [])
        if item.get("report_available") is True and item.get("asset_type") == "COMMON"
    }
    monitor_items = {
        str(item.get("ticker") or "").zfill(6): item
        for item in fast.get("items", [])
    }
    if set(monitor_items) != set(ticker_map):
        raise ValueError("Strategy Monitor item scope differs from published COMMON reports")
    report_current_states: Counter[str] = Counter()
    for ticker in sorted(ticker_map):
        source_path = next(source_dir.glob(f"{ticker}_*.json"), None)
        if source_path is None:
            raise ValueError(f"staged source report missing: {ticker}")
        source_report = read_json(source_path)
        source_core = source_report.get("a_fast_core") or {}
        web_report = read_json(stocks_dir / f"{ticker}.json")
        web_strategy = web_report.get("strategy") or {}
        if (
            source_core.get("strategy_id") != PROMOTED_STRATEGY_ID
            or source_core.get("strategy_replay_mode") != FULL_HISTORY_WEB_MODE
            or web_strategy.get("strategy_id") != PROMOTED_STRATEGY_ID
            or web_strategy.get("strategy_replay_mode") != FULL_HISTORY_WEB_MODE
            or source_core.get("strategy_replay_digest") != fast.get("strategy_replay_digest")
            or web_strategy.get("strategy_replay_digest") != fast.get("strategy_replay_digest")
            or source_core.get("strategy_replay_scope") != fast.get("strategy_replay_scope")
            or web_strategy.get("strategy_replay_scope") != fast.get("strategy_replay_scope")
        ):
            raise ValueError(f"staged source/web report FAST authority mismatch: {ticker}")
        monitor_item = monitor_items[ticker]
        if (
            source_core.get("action") != web_strategy.get("action")
            or source_core.get("strategy_state") != web_strategy.get("state")
            or source_core.get("canonical_position") != web_strategy.get("position")
            or web_strategy.get("action") != monitor_item.get("action")
            or web_strategy.get("state") != monitor_item.get("strategy_state")
            or web_strategy.get("position") != monitor_item.get("canonical_position")
        ):
            raise ValueError(f"report action/state/position differs from Strategy Monitor item: {ticker}")
        report_current_states[str(source_core.get("strategy_state") or "UNKNOWN")] += 1
        for trade in source_core.get("trade_history") or []:
            key = _normalize_trade_key(ticker, trade)
            if key in source_by_key:
                raise ValueError(f"duplicate report trade key: {key}")
            source_by_key[key] = _project_signature(ticker, trade, "report")
            source_history_count += 1
            if trade.get("trade_status") == "OPEN_AT_CUTOFF":
                open_source[key] = trade
        for trade in web_strategy.get("history") or []:
            key = _normalize_trade_key(ticker, trade)
            if key in web_by_key:
                raise ValueError(f"duplicate web report trade key: {key}")
            web_by_key[key] = _project_signature(ticker, trade, "report")
            web_history_count += 1
        source_open = [
            trade for trade in (source_core.get("trade_history") or [])
            if trade.get("trade_status") == "OPEN_AT_CUTOFF"
        ]
        core_current = source_core.get("current_trade")
        monitor_current = monitor_item.get("current_trade")
        if source_core.get("canonical_position") == "OPEN":
            if len(source_open) != 1 or not isinstance(core_current, dict) or not isinstance(monitor_current, dict):
                raise ValueError(f"report/monitor OPEN current trade projection is incomplete: {ticker}")
            open_history = source_open[0]
            core_key = _normalize_trade_key(ticker, core_current)
            if core_key != _normalize_trade_key(ticker, open_history):
                raise ValueError(f"Stock Report current_trade differs from replay OPEN history: {ticker}")
            for field in (
                "trade_id", "trade_sequence", "entry_signal_date", "entry_execution_date",
                "entry_open", "entry_pattern_a_stage", "lifecycle_class",
                "strategy_id", "entry_strategy_id", "exit_strategy_id",
            ):
                if core_current.get(field) != open_history.get(field):
                    raise ValueError(f"Stock Report current_trade differs from its OPEN history ({field}): {ticker}")
            _validate_open_trade_status_pair(core_current, open_history)
            if not math.isclose(
                float(core_current.get("current_return_pct")),
                float(open_history.get("return_pct")),
                rel_tol=0.0,
                abs_tol=0.011,
            ):
                raise ValueError(f"Stock Report current/open-history return differs: {ticker}")
            if (
                int(monitor_current.get("trade_sequence", 0)) != int(core_current["trade_sequence"])
                or monitor_current.get("entry_execution_date") != core_current.get("entry_execution_date")
            ):
                raise ValueError(f"Strategy Monitor current OPEN key differs from Stock Report: {ticker}")
            for field in (
                "entry_open", "trade_status", "strategy_id", "entry_strategy_id", "exit_strategy_id",
            ):
                if open_history.get(field) != monitor_current.get(field):
                    raise ValueError(f"Strategy Monitor current OPEN value differs ({field}): {ticker}")
            if not math.isclose(
                float(open_history.get("return_pct")),
                float(monitor_current.get("return_pct")),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError(f"Strategy Monitor current OPEN return differs: {ticker}")
            if not math.isclose(
                float(core_current.get("current_close")),
                float(monitor_item.get("latest_close")),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError(f"Stock Report current close differs from Strategy Monitor: {ticker}")
        elif source_open or core_current is not None or monitor_current is not None:
            raise ValueError(f"flat report contains an OPEN current trade: {ticker}")

    monitor_by_key: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    monitor_trade_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for trade in fast.get("trade_history") or []:
        key = _normalize_trade_key(str(trade["ticker"]).zfill(6), trade)
        if key in monitor_by_key:
            raise ValueError(f"duplicate monitor trade key: {key}")
        monitor_by_key[key] = _project_signature(str(trade["ticker"]).zfill(6), trade, "monitor")
        monitor_trade_by_key[key] = trade
        if trade.get("trade_status") == "OPEN_AT_CUTOFF":
            open_monitor[key] = trade
    if source_by_key != web_by_key or source_by_key != monitor_by_key:
        raise ValueError(
            "source report/web report/Strategy Monitor trade key or field parity failed: "
            f"source={len(source_by_key)} web={len(web_by_key)} monitor={len(monitor_by_key)}"
        )

    monitor_items = {str(item["ticker"]).zfill(6): item for item in fast.get("items", [])}
    for ticker, item in monitor_items.items():
        if item.get("canonical_position") == "OPEN":
            current_projection = item.get("current_trade")
            if not isinstance(current_projection, dict):
                raise ValueError(f"monitor OPEN item has no current trade: {ticker}")
            matches = [
                (key, trade) for key, trade in monitor_trade_by_key.items()
                if key[0] == ticker
                and trade.get("trade_status") == "OPEN_AT_CUTOFF"
                and int(trade.get("trade_sequence", 0)) == int(current_projection.get("trade_sequence", 0))
                and trade.get("entry_execution_date") == current_projection.get("entry_execution_date")
            ]
            if len(matches) != 1:
                raise ValueError(f"monitor current OPEN item does not identify exactly one history trade: {ticker}")
            _, history_trade = matches[0]
            for item_field, history_field in (
                ("entry_open", "entry_price"),
                ("trade_status", "trade_status"),
                ("strategy_id", "strategy_id"),
                ("entry_strategy_id", "entry_strategy_id"),
                ("exit_strategy_id", "exit_strategy_id"),
            ):
                if current_projection.get(item_field) != history_trade.get(history_field):
                    raise ValueError(f"monitor OPEN item/history projection differs ({item_field}): {ticker}")
            if not math.isclose(
                float(current_projection.get("return_pct")),
                float(history_trade.get("return_pct")),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError(f"monitor OPEN item/history return differs: {ticker}")
    if set(open_source) != set(open_monitor):
        raise ValueError(
            "stock report current OPEN and Strategy Monitor OPEN keys differ: "
            f"source={len(open_source)} monitor={len(open_monitor)}"
        )
    for key in open_source:
        left, right = open_source[key], open_monitor[key]
        if (
            left.get("entry_open") != right.get("entry_price")
            or left.get("entry_signal_date") != right.get("entry_signal_date")
            or left.get("exit_signal_date") != right.get("exit_signal_date")
            or left.get("exit_execution_date") != right.get("exit_execution_date")
            or left.get("exit_price") != right.get("exit_price")
            or left.get("return_pct") != right.get("return_pct")
            or (left.get("exit_type") if left.get("exit_execution_date") else None) != right.get("exit_reason")
            or left.get("strategy_id") != right.get("strategy_id")
            or left.get("entry_strategy_id") != right.get("entry_strategy_id")
            or left.get("exit_strategy_id") != right.get("exit_strategy_id")
        ):
            raise ValueError(f"stock report current OPEN projection fields differ: {key}")

    expected_buckets: Counter[str] = Counter({
        "entry": 0, "hold": 0, "exit": 0, "watch": 0, "unavailable": 0,
    })
    for item in fast.get("items", []):
        bucket = str(item.get("bucket") or "UNKNOWN")
        if bucket not in expected_buckets:
            raise ValueError(f"unknown Strategy Monitor current state bucket: {bucket}")
        expected_buckets[bucket] += 1
    if dict(sorted(expected_buckets.items())) != dict(sorted((fast.get("counts") or {}).items())):
        raise ValueError("Strategy Monitor current state counts do not match its items")
    if len(fast.get("trade_history") or []) != source_history_count:
        raise ValueError("Strategy Monitor trade statistics/history count differs from Stock Reports")

    old_by_id = {row["id"]: row for row in old_monitor.get("strategies", [])}
    new_by_id = {row["id"]: row for row in monitor.get("strategies", [])}
    for strategy_id in ("PATTERN_B_SELECT_CORE_V02", "JULIA_ETF_STRATEGY_V01"):
        if old_by_id.get(strategy_id) != new_by_id.get(strategy_id):
            raise ValueError(f"unrelated strategy output changed in staging: {strategy_id}")
    if monitor.get("requested_as_of") != target_as_of or monitor.get("reference_market_date") != reference_market_date:
        raise ValueError("Strategy Monitor target dates differ from the scanner authority")
    return {
        "source_report_trade_rows": source_history_count,
        "web_report_trade_rows": web_history_count,
        "strategy_monitor_trade_rows": len(monitor_by_key),
        "trade_key_and_values_mismatches": 0,
        "report_open_positions": len(open_source),
        "monitor_open_positions": len(open_monitor),
        "open_key_and_values_mismatches": 0,
        "b_select_unchanged": True,
        "julia_unchanged": True,
        "fast_strategy_row_count": len(fast_rows),
        "common_report_scope_count": len(ticker_map),
        "report_current_state_counts": dict(sorted(report_current_states.items())),
        "strategy_monitor_current_state_counts": dict(sorted(expected_buckets.items())),
        "strategy_replay_digest_match": True,
    }


def run(target_as_of: str | None = None, staging_parent: Path = STAGING_PARENT) -> dict[str, Any]:
    started = time.monotonic()
    requested_as_of, reference_market_date, scanner_summary = _scanner_dates(target_as_of)
    report_dir, report_paths, common_tickers = _report_sources(requested_as_of)
    staging_parent = Path(staging_parent)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage_root = staging_parent / f"staging_{run_id}"
    if stage_root.exists():
        raise FileExistsError(f"refusing to overwrite existing staging output: {stage_root}")
    stage_root.mkdir(parents=True)
    (stage_root / "replay_core").mkdir()
    (stage_root / "reports" / requested_as_of.replace("-", "") / "json").mkdir(parents=True)
    (stage_root / "audit").mkdir()

    config_before = sha256_file(ROOT / CONFIG_REL)
    history_before = sha256_file(ROOT / HISTORY_REL)
    config = load_promotion_config(ROOT)
    activation_history = load_activation_history(ROOT, config)
    if config.active:
        raise AlignmentGateIntegrityError("operational FAST activation is active; historical web replay refused")

    score_contract = read_json(SCORE_CONTRACT_PATH)
    stage_contract = read_json(STAGE_CONTRACT_PATH)
    # This is a fixed historical replay over a certified cutoff. Keep the
    # full PIT history available for pre-transfer signals; production-mode
    # current-identity clamping would truncate a migrated ticker's old market.
    repository = build_repository_v2(ROOT, end=reference_market_date)
    daily_loader = RepositoryV2DailyLoader(repository, end=requested_as_of)
    market_calendar = load_rolling_production_market_calendar(ROOT)
    if market_calendar is None:
        raise AlignmentGateIntegrityError("rolling production market calendar is unavailable")
    gate = get_historical_alignment_replay_gate(str(ROOT.resolve()))

    counts: Counter[str] = Counter()
    gate_reasons: Counter[str] = Counter()
    ticker_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    replay_material_path = stage_root / "audit" / "replay_core_canonical.jsonl"
    source_hashes: dict[str, str] = {}
    first_candidate_dates: list[str] = []
    last_candidate_dates: list[str] = []
    first_alignment_pass_dates: list[str] = []
    unresolved_gate_count = 0
    monthly_gap_count = 0
    daily_missing_count = 0
    current_target_gap_count = 0
    loader_silent_drop_count = 0
    adjusted_series_too_short_count = 0
    metadata_unavailable_count = 0
    replay_state_unavailable_count = 0
    engine_error_count = 0
    current_investability_by_ticker: dict[str, dict[str, Any]] = {}

    with replay_material_path.open("w", encoding="utf-8") as replay_material:
        for position, path in enumerate(report_paths, start=1):
            report = read_json(path)
            ticker = str(report.get("ticker") or "").zfill(6)
            if ticker not in common_tickers or report.get("asset_type") != "COMMON":
                raise ValueError(f"unexpected target report ticker or asset type: {path.name}")
            if report.get("requested_as_of") != requested_as_of or report.get("reference_market_date") != reference_market_date:
                raise ValueError(f"target report date mismatch: {path.name}")
            source_hashes[ticker] = sha256_file(path)
            source_core = report.get("a_fast_core") or {}
            metadata_mode = str(source_core.get("metadata_provenance_mode") or "DATA_UNAVAILABLE")
            if metadata_mode == "DATA_UNAVAILABLE":
                metadata_unavailable_count += 1
            snapshot = report.get("current_snapshot") or {}
            daily = daily_loader.load(ticker)
            if daily is None or daily.empty:
                daily_missing_count += 1
                first_date = last_date = None
                row_count = 0
                projection = {}
            else:
                daily = daily.sort_index()
                first_date = daily.index.min().strftime("%Y-%m-%d")
                last_date = daily.index.max().strftime("%Y-%m-%d")
                row_count = int(len(daily))
                if row_count < 60:
                    adjusted_series_too_short_count += 1
                projection = dict(daily.attrs.get("session_projection_summary") or {})
                loader_silent_drop_count += int(projection.get("silent_inner_drop_count", 0) or 0)
                if last_date != reference_market_date:
                    current_target_gap_count += 1

            # The Stock Reports are requested for a Sunday (10/11) while the
            # certified market reference is Thursday (10/08). Evaluate current
            # investability on that exact reference session and its exact KRX
            # market-cap partition; the source report's requested-date snapshot
            # can otherwise fail closed for every flat ticker on the Sunday.
            current_market_cap = gate._resolve_market_cap(ticker, str(report.get("market") or "UNKNOWN"), reference_market_date)
            current_investability = evaluate_investability(
                ticker=ticker,
                as_of=reference_market_date,
                daily=daily,
                market_cap=current_market_cap,
                market_cap_effective_date=reference_market_date if current_market_cap is not None else None,
            )
            investability_status = current_investability.status.value
            investability_reason = current_investability.reason
            current_investability_by_ticker[ticker] = {
                "source_status": str(snapshot.get("investability_status") or "DATA_UNAVAILABLE"),
                "source_reason": str(snapshot.get("investability_reason") or ""),
                "market_cap_eok": current_investability.market_cap_eok,
                "avg_trading_value_20d_eok": current_investability.avg_trading_value_20d_eok,
                "investability_status": investability_status,
                "investability_reason": investability_reason,
                "market_cap_effective_date": current_investability.market_cap_effective_date,
                "close_effective_date": current_investability.close_effective_date,
                "tv20_last_observation_date": current_investability.tv20_last_observation_date,
                "close_ready": current_investability.close_ready,
                "market_cap_ready": current_investability.market_cap_ready,
                "trading_value_20d_ready": current_investability.trading_value_20d_ready,
            }

            section = build_a_fast_core_section(
                ticker=ticker,
                name=str(report.get("name") or ticker),
                market=str(report.get("market") or "UNKNOWN"),
                daily=daily,
                requested_as_of=pd.Timestamp(requested_as_of),
                score_contract=score_contract,
                stage_contract=stage_contract,
                asset_type="COMMON",
                investability_status=investability_status,
                investability_reason=investability_reason,
                is_common_stock=True,
                metadata_provenance_mode=metadata_mode,
                market_calendar=market_calendar,
                repo_root=ROOT,
                promotion_gate=gate,
                replay_mode=HISTORICAL_ALIGNMENT_REPLAY_MODE,
            )
            core = asdict(section)
            if core.get("strategy_id") != PROMOTED_STRATEGY_ID or core.get("strategy_replay_mode") != HISTORICAL_ALIGNMENT_REPLAY_MODE:
                raise ValueError(f"historical full-replay mode was not applied: {ticker}")
            history = core.get("trade_history") or []
            _validate_trade_rows(ticker, history)
            candidate_audit = core.get("promotion_gate_audit") or []
            decisions_for_ticker = Counter(str(row.get("reason_code") or "UNKNOWN") for row in candidate_audit)
            gate_reasons.update(decisions_for_ticker)
            counts["gate_signal_count"] += len(candidate_audit)
            for row in candidate_audit:
                signal_date = str(row.get("signal_date") or "")[:10]
                if signal_date:
                    first_candidate_dates.append(signal_date)
                    last_candidate_dates.append(signal_date)
                if row.get("allowed") is True and signal_date:
                    first_alignment_pass_dates.append(signal_date)
                details = row.get("details") or {}
                reason = str(row.get("reason_code") or "")
                if reason in {"REJECT_MCAP_UNRESOLVED", "REJECT_IDENTITY_UNRESOLVED"}:
                    unresolved_gate_count += 1
                if reason == "REJECT_MA_UNAVAILABLE":
                    cause = details.get("cause")
                    if cause == "PRIOR_COMPLETED_MONTHS_INSUFFICIENT_OR_GAPPED":
                        available_months = int(details.get("available_months") or 0)
                        daily_first = pd.Timestamp(first_date) if first_date else None
                        required_first_month = pd.Period(signal_date, freq="M") - 60
                        if daily_first is not None and pd.Period(daily_first, freq="M") <= required_first_month and available_months < 60:
                            monthly_gap_count += 1
                    elif cause != "ADJUSTED_CLOSE_MISSING":
                        monthly_gap_count += 1
                gate_rows.append({
                    "ticker": ticker,
                    "signal_date": signal_date,
                    "allowed": bool(row.get("allowed")),
                    "reason_code": reason,
                    "details_json": canonical_json(details),
                })
            state_reason = str(core.get("action_reason") or "")
            if core.get("strategy_state") == "DATA_UNAVAILABLE":
                replay_state_unavailable_count += 1
            if state_reason in {"EVALUATOR_EXECUTION_FAILED", "FAST_EVALUATOR_UNAVAILABLE", "NO_COMPLETED_WEEKS"}:
                engine_error_count += 1
            counts["reports_processed"] += 1
            counts[f"state:{core.get('strategy_state') or 'UNKNOWN'}"] += 1
            counts["trades_total"] += len(history)
            counts["trades_realized"] += sum(row.get("trade_status") == "REALIZED" for row in history)
            counts["trades_open"] += sum(row.get("trade_status") == "OPEN_AT_CUTOFF" for row in history)
            for row in history:
                trade_rows.append({
                    "ticker": ticker,
                    "name": str(report.get("name") or ticker),
                    **row,
                })
            replay_core_path = stage_root / "replay_core" / f"{ticker}.json"
            write_json(replay_core_path, core)
            replay_material.write(canonical_json({"ticker": ticker, "a_fast_core": core}) + "\n")
            ticker_rows.append({
                "ticker": ticker,
                "name": str(report.get("name") or ticker),
                "market": str(report.get("market") or "UNKNOWN"),
                "report_source_sha256": source_hashes[ticker],
                "metadata_provenance_mode": metadata_mode,
            "source_report_investability_status": str(snapshot.get("investability_status") or "DATA_UNAVAILABLE"),
            "source_report_investability_reason": str(snapshot.get("investability_reason") or ""),
                "investability_status": investability_status,
                "adjusted_first_date": first_date,
                "adjusted_last_date": last_date,
                "adjusted_row_count": row_count,
                "session_projection_summary": canonical_json(projection),
                "signal_evaluation_count": len(candidate_audit),
                "first_v2_candidate_signal_date": min((str(x.get("signal_date"))[:10] for x in candidate_audit), default=None),
                "last_v2_candidate_signal_date": max((str(x.get("signal_date"))[:10] for x in candidate_audit), default=None),
                "first_alignment_gate_pass_signal_date": min((str(x.get("signal_date"))[:10] for x in candidate_audit if x.get("allowed") is True), default=None),
                "gate_reason_counts": canonical_json(dict(sorted(decisions_for_ticker.items()))),
                "replay_strategy_state": core.get("strategy_state"),
                "replay_canonical_position": core.get("canonical_position"),
                "replay_action_reason": core.get("action_reason"),
                "trade_count": len(history),
                "realized_count": sum(row.get("trade_status") == "REALIZED" for row in history),
                "open_count": sum(row.get("trade_status") == "OPEN_AT_CUTOFF" for row in history),
            })
            if position % 50 == 0 or position == len(report_paths):
                print(f"replayed {position}/{len(report_paths)} COMMON reports", flush=True)

    digest = sha256_file(replay_material_path)
    all_trade_ids = [str(row.get("trade_id") or "") for row in trade_rows]
    if len(all_trade_ids) != len(set(all_trade_ids)):
        raise ValueError("historical Alignment replay contains duplicate trade IDs across reports")
    gate_start = min(first_candidate_dates) if first_candidate_dates else None
    gate_end = max(last_candidate_dates) if last_candidate_dates else None
    scope = {
        "type": "PUBLISHED_COMMON_REPORTS",
        "report_count": len(report_paths),
        "requested_as_of": requested_as_of,
        "reference_market_date": reference_market_date,
        "first_v2_candidate_signal_date": gate_start,
        "last_v2_candidate_signal_date": gate_end,
        "first_alignment_gate_pass_signal_date": min(first_alignment_pass_dates) if first_alignment_pass_dates else None,
        "base_candidate_signal_count": counts["gate_signal_count"],
        "alignment_gate_pass_count": gate_reasons.get("PASS_ALIGNMENT_MCAP_500B", 0),
        "output_strategy_id": PROMOTED_STRATEGY_ID,
    }

    staged_report_dir = stage_root / "reports" / requested_as_of.replace("-", "")
    staged_json_dir = staged_report_dir / "json"
    for position, path in enumerate(report_paths, start=1):
        report = read_json(path)
        ticker = str(report.get("ticker") or "").zfill(6)
        core_path = stage_root / "replay_core" / f"{ticker}.json"
        core = read_json(core_path)
        core["strategy_replay_mode"] = FULL_HISTORY_WEB_MODE
        core["strategy_replay_scope"] = scope
        core["strategy_replay_digest"] = digest
        report["a_fast_core"] = core
        current_snapshot = report.get("current_snapshot") or {}
        current_metrics = current_investability_by_ticker[ticker]
        for field in (
            "market_cap_eok", "avg_trading_value_20d_eok", "investability_status",
            "investability_reason", "market_cap_effective_date",
        ):
            current_snapshot[field] = current_metrics[field]
        current_snapshot["is_investable"] = current_metrics["investability_status"] == "INVESTABLE"
        current_snapshot["market_cap_source"] = (
            "KRX_RAW_STOCK_SNAPSHOT" if current_metrics["market_cap_ready"] else None
        )
        report["current_snapshot"] = current_snapshot
        summary = report.get("summary") or {}
        summary["strategy_headline"] = core.get("interpretation") or ""
        bullets = list(summary.get("bullet_points") or [])
        bullet = _summary_bullet(core)
        if bullets:
            bullets[0] = bullet
        else:
            bullets.insert(0, bullet)
        summary["bullet_points"] = bullets
        report["summary"] = summary
        write_json(staged_json_dir / path.name, report)

    _write_csv(
        stage_root / "audit" / "ticker_coverage.csv",
        [
            "ticker", "name", "market", "report_source_sha256", "metadata_provenance_mode",
            "source_report_investability_status", "source_report_investability_reason",
            "investability_status", "adjusted_first_date", "adjusted_last_date", "adjusted_row_count",
            "session_projection_summary", "signal_evaluation_count", "first_v2_candidate_signal_date",
            "last_v2_candidate_signal_date", "first_alignment_gate_pass_signal_date", "gate_reason_counts",
            "replay_strategy_state", "replay_canonical_position", "replay_action_reason", "trade_count",
            "realized_count", "open_count",
        ],
        ticker_rows,
    )
    _write_csv(
        stage_root / "audit" / "gate_signal_audit.csv",
        ["ticker", "signal_date", "allowed", "reason_code", "details_json"],
        gate_rows,
    )
    trade_fields = [
        "ticker", "name", "trade_id", "trade_sequence", "strategy_id", "entry_strategy_id",
        "exit_strategy_id", "entry_signal_date", "entry_execution_date", "entry_open",
        "entry_pattern_a_stage", "exit_type", "exit_signal_date", "exit_execution_date", "exit_price",
        "trade_status", "return_pct", "previous_exit_type", "lifecycle_class",
    ]
    _write_csv(stage_root / "audit" / "alignment_trade_ledger.csv", trade_fields, trade_rows)

    if config_before != sha256_file(ROOT / CONFIG_REL) or history_before != sha256_file(ROOT / HISTORY_REL):
        raise AlignmentGateIntegrityError("operational config or activation history changed during read-only replay")

    stock_web, strategy_web = _load_export_modules()

    web_output = stage_root / "web"
    export_stats = stock_web.export_stock_reports(
        web_output,
        target_as_of=requested_as_of,
        reference_market_date=reference_market_date,
        include_etf=True,
        source_report_directory=staged_report_dir,
    )
    b_status_path = ROOT / "artifacts/strategies/b_select_core_v2/production" / requested_as_of.replace("-", "") / "status.json"
    b_select_status = read_json(b_status_path)
    monitor = strategy_web.build_strategy_monitor(
        repo_root=ROOT,
        index_path=web_output / "stock-index.json",
        stocks_path=web_output / "stocks",
        target_as_of=requested_as_of,
        reference_market_date=reference_market_date,
        b_select_status=b_select_status,
        source_report_path=(web_output / "stocks" / "*.json").relative_to(ROOT).as_posix(),
    )
    write_json(web_output / "strategy-monitor.json", monitor)
    old_monitor = read_json(ROOT / "web/data/strategy-monitor.json")
    parity = _verify_three_way_parity(
        stage_root, requested_as_of, reference_market_date,
        read_json(web_output / "stock-index.json"), monitor, old_monitor,
    )

    prior_fast = next(
        (strategy for strategy in old_monitor.get("strategies", []) if strategy.get("id") in {
            "PATTERN_A_FAST_FINAL_STRATEGY_V02", PROMOTED_STRATEGY_ID,
        }),
        {},
    )
    prior_status_counts = Counter(str(row.get("trade_status") or "UNKNOWN") for row in prior_fast.get("trade_history", []))
    current_status_counts = Counter(str(row.get("trade_status") or "UNKNOWN") for row in (
        next(row for row in monitor["strategies"] if row["id"] == PROMOTED_STRATEGY_ID).get("trade_history") or []
    ))

    blockers: list[dict[str, Any]] = []
    if daily_missing_count:
        blockers.append({"code": "ADJUSTED_PRICE_SERIES_MISSING", "count": daily_missing_count})
    if adjusted_series_too_short_count:
        blockers.append({"code": "ADJUSTED_PRICE_HISTORY_TOO_SHORT", "count": adjusted_series_too_short_count})
    if metadata_unavailable_count:
        blockers.append({"code": "STOCK_METADATA_UNAVAILABLE", "count": metadata_unavailable_count})
    if replay_state_unavailable_count:
        blockers.append({"code": "REPLAY_STATE_UNAVAILABLE", "count": replay_state_unavailable_count})
    if current_target_gap_count:
        blockers.append({"code": "REFERENCE_MARKET_DATE_PRICE_GAP", "count": current_target_gap_count})
    if loader_silent_drop_count:
        blockers.append({"code": "UNEXPLAINED_REPOSITORY_SESSION_DROP", "count": loader_silent_drop_count})
    if unresolved_gate_count:
        blockers.append({"code": "PIT_OR_EXACT_RAW_MARKET_CAP_UNRESOLVED", "count": unresolved_gate_count})
    if monthly_gap_count:
        blockers.append({"code": "COMPLETED_MONTH_MA_HISTORY_GAP", "count": monthly_gap_count})
    if engine_error_count:
        blockers.append({"code": "STRATEGY_EVALUATOR_ERROR", "count": engine_error_count})
    status = "PASS" if not blockers else "CHECK_REQUIRED"

    output_hashes = {}
    for path in sorted(stage_root.rglob("*")):
        if path.is_file() and path.name != "manifest.json" and path.name != "report.md":
            output_hashes[path.relative_to(stage_root).as_posix()] = sha256_file(path)
    manifest = {
        "schema": "a_fast_alignment_500b_web_canonical_full_history_rebuild_v01",
        "status": status,
        "completion_token": (
            "A_FAST_CORE_V2_ALIGNMENT_500B_WEB_CANONICAL_FULL_HISTORY_REBUILD_V01_PASS"
            if status == "PASS" else "A_FAST_CORE_V2_ALIGNMENT_500B_WEB_CANONICAL_FULL_HISTORY_REBUILD_V01_CHECK_REQUIRED"
        ),
        "git_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "origin_main": __import__("subprocess").check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
        "requested_as_of": requested_as_of,
        "reference_market_date": reference_market_date,
        "scanner_summary_path": str((SCANNER_ROOT / f"pattern_a_universe_scan_{requested_as_of.replace('-', '')}_summary.json").relative_to(ROOT)),
        "scanner_scope": scanner_summary,
        "source_report_directory": str(report_dir.relative_to(ROOT)),
        "source_report_count": len(report_paths),
        "published_common_monitor_scope": len(common_tickers),
        "universe_scanner_official_common_total": scanner_summary.get("official_common_total"),
        "strategy_id": PROMOTED_STRATEGY_ID,
        "strategy_name": PROMOTED_STRATEGY_NAME,
        "strategy_replay_mode": FULL_HISTORY_WEB_MODE,
        "strategy_replay_scope": scope,
        "strategy_replay_digest": digest,
        "trade_counts": {
            "realized": current_status_counts.get("REALIZED", 0),
            "open": current_status_counts.get("OPEN_AT_CUTOFF", 0),
            "total": sum(current_status_counts.values()),
            "old_v2_reference_realized": prior_status_counts.get("REALIZED", 0),
            "old_v2_reference_open": prior_status_counts.get("OPEN_AT_CUTOFF", 0),
            "old_v2_reference_total": sum(prior_status_counts.values()),
            "realized_delta_vs_old_reference": current_status_counts.get("REALIZED", 0) - prior_status_counts.get("REALIZED", 0),
            "open_delta_vs_old_reference": current_status_counts.get("OPEN_AT_CUTOFF", 0) - prior_status_counts.get("OPEN_AT_CUTOFF", 0),
            "total_delta_vs_old_reference": sum(current_status_counts.values()) - sum(prior_status_counts.values()),
        },
        "gate_decision_counts": dict(sorted(gate_reasons.items())),
        "coverage": {
            "reports_processed": counts["reports_processed"],
            "expected_common_reports": len(common_tickers),
            "v2_candidate_signals_evaluated": counts["gate_signal_count"],
            "first_candidate_signal_date": gate_start,
            "last_candidate_signal_date": gate_end,
            "first_alignment_gate_pass_signal_date": scope["first_alignment_gate_pass_signal_date"],
            "daily_series_missing_tickers": daily_missing_count,
            "adjusted_series_too_short_tickers": adjusted_series_too_short_count,
            "metadata_unavailable_tickers": metadata_unavailable_count,
            "replay_state_unavailable_tickers": replay_state_unavailable_count,
            "reference_date_gaps": current_target_gap_count,
            "unexplained_repository_session_drops": loader_silent_drop_count,
            "pit_or_raw_market_cap_unresolved_signals": unresolved_gate_count,
            "completed_month_ma_history_gaps": monthly_gap_count,
            "strategy_evaluator_errors": engine_error_count,
            "explicit_repository_projection_exclusions": sum(
                int(row.get("session_projection_summary") and json.loads(row["session_projection_summary"]).get("explicit_exclusion_count", 0) or 0)
                for row in ticker_rows
            ),
        },
        "staging_output_only": True,
        "operational_config_enabled": config.enabled,
        "operational_config_active": config.active,
        "operational_effective_signal_date": config.effective_signal_date,
        "operational_activation_interval_count": len(activation_history),
        "b_select_status_sha256": sha256_file(b_status_path),
        "config_sha256_before_and_after": config_before,
        "activation_history_sha256_before_and_after": history_before,
        "three_way_validation": parity,
        "stock_report_export_stats": export_stats,
        "blockers": blockers,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source_report_sha256_by_ticker": source_hashes,
        "staging_file_sha256": output_hashes,
    }
    manifest_path = stage_root / "manifest.json"
    write_json(manifest_path, manifest)
    report_lines = [
        f"# FAST Core V2 Alignment 500B 웹 정본 전 기간 재생 staging — {status}",
        "",
        "| 등급 | 건수 | 판정 |",
        "|---|---:|---|",
        f"| CRITICAL | {1 if status == 'CHECK_REQUIRED' and any('INTEGRITY' in row['code'] for row in blockers) else 0} | 구조/hash 무결성 오류 여부는 blockers 참조 |",
        f"| MAJOR | {len(blockers)} | {'; '.join(row['code'] + '=' + str(row['count']) for row in blockers) if blockers else '필수 데이터·정합성 blocker 없음'} |",
        "| MINOR | 1 | 기존 공개 scope 1,459 COMMON으로 제한; scanner 전체 common 수 2,547로 확대하지 않음 |",
        "",
        f"- 기준: HEAD `{manifest['git_head']}`, origin/main `{manifest['origin_main']}`.",
        f"- 기준일: requested_as_of `{requested_as_of}`, reference_market_date `{reference_market_date}`.",
        f"- 결과: `{status}`; PASS token: `{manifest['completion_token']}`.",
        f"- staging: `{stage_root.relative_to(ROOT)}`. 운영 config/history, canonical reports, `web/data`는 읽기 전용.",
        f"- 재생 범위: COMMON reports {len(common_tickers)}; source reports {len(report_paths)}; scanner official_common_total {scanner_summary.get('official_common_total')}.",
        f"- 거래: REALIZED {manifest['trade_counts']['realized']}, OPEN {manifest['trade_counts']['open']}, TOTAL {manifest['trade_counts']['total']}.",
        f"- V2 비교 참고: REALIZED {manifest['trade_counts']['old_v2_reference_realized']}, OPEN {manifest['trade_counts']['old_v2_reference_open']}, TOTAL {manifest['trade_counts']['old_v2_reference_total']}.",
        f"- V2 유효 후보 신호 평가: {counts['gate_signal_count']}; first/last {gate_start}/{gate_end}; first Alignment pass {scope['first_alignment_gate_pass_signal_date']}.",
        f"- 단일 Alignment ID, report/web/monitor 거래 및 OPEN 1:1: {parity['trade_key_and_values_mismatches']} / {parity['open_key_and_values_mismatches']} mismatches; B Select/Julia unchanged={parity['b_select_unchanged']}/{parity['julia_unchanged']}.",
        f"- 운영 config enabled={config.enabled}, active={config.active}, date={config.effective_signal_date}; activation intervals={len(activation_history)}.",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        report_lines.extend(f"- `{row['code']}`: {row['count']}" for row in blockers)
    else:
        report_lines.append("- 없음")
    report_lines.extend([
        "",
        "## 검증 범위와 한계",
        "",
        "- 보고서 JSON, Compact Stock Report, Strategy Monitor는 동일한 replay-core digest를 사용한다.",
        "- 웹 정본은 별도 FULL_HISTORY_ALIGNMENT_WEB mode로만 생성했으며 operational activation history를 사용하거나 수정하지 않는다.",
        "- 공식 V2 lifecycle 엔진에서 각 유효 진입 후보를 발생 순서로 평가하고 Alignment exact-date gate를 적용했다. 통과 진입 뒤 EXIT/재진입/OPEN과 sequence를 처음부터 다시 계산했다.",
        "- staged output 외 canonical publish, Daily Update, 운영 활성화, 주문, 공식 5기간 백테스트, commit/push는 수행하지 않았다.",
        "",
    ])
    report_path = stage_root / "report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    manifest["staging_file_sha256"]["report.md"] = sha256_file(report_path)
    write_json(manifest_path, manifest)
    print(json.dumps({
        "status": status,
        "stage_root": str(stage_root.relative_to(ROOT)),
        "strategy_replay_digest": digest,
        "trade_counts": manifest["trade_counts"],
        "coverage": manifest["coverage"],
        "blockers": blockers,
    }, ensure_ascii=False, sort_keys=True))
    return manifest


def resume_completed_stage(stage_root: Path, *, replay_elapsed_seconds: float | None = None) -> dict[str, Any]:
    """Finalize a stage whose full replay and per-ticker audits already completed."""
    started = time.monotonic()
    stage_root = Path(stage_root).resolve()
    allowed_parent = STAGING_PARENT.resolve()
    if not stage_root.is_relative_to(allowed_parent) or not stage_root.is_dir():
        raise ValueError(f"resume stage must be an existing task staging directory: {stage_root}")
    if (stage_root / "manifest.json").exists() or (stage_root / "report.md").exists():
        raise FileExistsError(f"refusing to replace finalized staging output: {stage_root}")

    requested_as_of, reference_market_date, scanner_summary = _scanner_dates(None)
    report_dir, report_paths, common_tickers = _report_sources(requested_as_of)
    staged_report_dir = stage_root / "reports" / requested_as_of.replace("-", "")
    staged_json_dir = staged_report_dir / "json"
    replay_material_path = stage_root / "audit" / "replay_core_canonical.jsonl"
    coverage_path = stage_root / "audit" / "ticker_coverage.csv"
    gate_path = stage_root / "audit" / "gate_signal_audit.csv"
    trade_path = stage_root / "audit" / "alignment_trade_ledger.csv"
    for required in (replay_material_path, coverage_path, gate_path, trade_path):
        if not required.is_file():
            raise FileNotFoundError(f"completed replay audit is missing: {required}")

    def read_csv(path: Path) -> list[dict[str, str]]:
        import csv

        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    ticker_rows = read_csv(coverage_path)
    gate_rows = read_csv(gate_path)
    trade_rows = read_csv(trade_path)
    expected_tickers = set(common_tickers)
    coverage_tickers = {str(row.get("ticker") or "").zfill(6) for row in ticker_rows}
    if coverage_tickers != expected_tickers or len(ticker_rows) != len(expected_tickers):
        raise ValueError("completed ticker coverage does not match published COMMON report scope")
    if len(report_paths) != len(expected_tickers):
        raise ValueError("published COMMON source report count changed since the replay")
    source_hashes = {
        str(row["ticker"]).zfill(6): str(row.get("report_source_sha256") or "")
        for row in ticker_rows
    }
    for path in report_paths:
        source_report = read_json(path)
        ticker = str(source_report.get("ticker") or "").zfill(6)
        if source_hashes.get(ticker) != sha256_file(path):
            raise ValueError(f"source Stock Report changed after the completed replay: {ticker}")
        staged_path = staged_json_dir / path.name
        core_path = stage_root / "replay_core" / f"{ticker}.json"
        if not staged_path.is_file() or not core_path.is_file():
            raise FileNotFoundError(f"completed staged replay report/core is missing: {ticker}")

    replay_tickers: list[str] = []
    with replay_material_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            ticker = str(row.get("ticker") or "").zfill(6)
            if ticker not in expected_tickers or not isinstance(row.get("a_fast_core"), dict):
                raise ValueError("completed replay material contains an invalid ticker/core row")
            replay_tickers.append(ticker)
    if len(replay_tickers) != len(expected_tickers) or set(replay_tickers) != expected_tickers:
        raise ValueError("completed replay material ticker set/count does not match report scope")
    digest = sha256_file(replay_material_path)

    candidate_dates = [
        str(row.get(field) or "")
        for row in ticker_rows
        for field in ("first_v2_candidate_signal_date", "last_v2_candidate_signal_date")
        if row.get(field)
    ]
    alignment_pass_dates = [
        str(row.get("first_alignment_gate_pass_signal_date") or "")
        for row in ticker_rows if row.get("first_alignment_gate_pass_signal_date")
    ]
    gate_reasons: Counter[str] = Counter(str(row.get("reason_code") or "UNKNOWN") for row in gate_rows)
    scope = {
        "type": "PUBLISHED_COMMON_REPORTS",
        "report_count": len(report_paths),
        "requested_as_of": requested_as_of,
        "reference_market_date": reference_market_date,
        "first_v2_candidate_signal_date": min(candidate_dates) if candidate_dates else None,
        "last_v2_candidate_signal_date": max(candidate_dates) if candidate_dates else None,
        "first_alignment_gate_pass_signal_date": min(alignment_pass_dates) if alignment_pass_dates else None,
        "base_candidate_signal_count": len(gate_rows),
        "alignment_gate_pass_count": gate_reasons.get("PASS_ALIGNMENT_MCAP_500B", 0),
        "output_strategy_id": PROMOTED_STRATEGY_ID,
    }
    for path in report_paths:
        ticker = str(read_json(path).get("ticker") or "").zfill(6)
        staged_report = read_json(staged_json_dir / path.name)
        core = staged_report.get("a_fast_core") or {}
        if (
            core.get("strategy_id") != PROMOTED_STRATEGY_ID
            or core.get("strategy_replay_mode") != FULL_HISTORY_WEB_MODE
            or core.get("strategy_replay_digest") != digest
            or core.get("strategy_replay_scope") != scope
        ):
            raise ValueError(f"completed staged report replay provenance mismatch: {ticker}")

    coverage_by_ticker = {str(row["ticker"]).zfill(6): row for row in ticker_rows}
    daily_missing_count = sum(not row.get("adjusted_first_date") or not row.get("adjusted_last_date") for row in ticker_rows)
    adjusted_series_too_short_count = sum(int(row.get("adjusted_row_count") or 0) < 60 for row in ticker_rows)
    metadata_unavailable_count = sum(row.get("metadata_provenance_mode") == "DATA_UNAVAILABLE" for row in ticker_rows)
    replay_state_unavailable_count = sum(row.get("replay_strategy_state") == "DATA_UNAVAILABLE" for row in ticker_rows)
    current_target_gap_count = sum(
        bool(row.get("adjusted_last_date")) and row.get("adjusted_last_date") != reference_market_date
        for row in ticker_rows
    )
    loader_silent_drop_count = 0
    for row in ticker_rows:
        projection = json.loads(row.get("session_projection_summary") or "{}")
        loader_silent_drop_count += int(projection.get("silent_inner_drop_count", 0) or 0)
    unresolved_gate_count = sum(row.get("reason_code") in {"REJECT_MCAP_UNRESOLVED", "REJECT_IDENTITY_UNRESOLVED"} for row in gate_rows)
    monthly_gap_count = 0
    for row in gate_rows:
        if row.get("reason_code") != "REJECT_MA_UNAVAILABLE":
            continue
        details = json.loads(row.get("details_json") or "{}")
        cause = details.get("cause")
        if cause == "PRIOR_COMPLETED_MONTHS_INSUFFICIENT_OR_GAPPED":
            available_months = int(details.get("available_months") or 0)
            daily_first = coverage_by_ticker[str(row["ticker"]).zfill(6)].get("adjusted_first_date")
            required_first_month = pd.Period(str(row["signal_date"]), freq="M") - 60
            if daily_first and pd.Period(daily_first, freq="M") <= required_first_month and available_months < 60:
                monthly_gap_count += 1
        elif cause != "ADJUSTED_CLOSE_MISSING":
            monthly_gap_count += 1
    engine_error_count = sum(
        row.get("replay_action_reason") in {"EVALUATOR_EXECUTION_FAILED", "FAST_EVALUATOR_UNAVAILABLE", "NO_COMPLETED_WEEKS"}
        for row in ticker_rows
    )

    config_before = sha256_file(ROOT / CONFIG_REL)
    history_before = sha256_file(ROOT / HISTORY_REL)
    config = load_promotion_config(ROOT)
    activation_history = load_activation_history(ROOT, config)
    if config.active:
        raise AlignmentGateIntegrityError("operational FAST activation is active; historical web replay refused")

    web_output = stage_root / "web"
    index_path = web_output / "stock-index.json"
    monitor_path = web_output / "strategy-monitor.json"
    stock_web = strategy_web = None
    if not index_path.is_file():
        stock_web, strategy_web = _load_export_modules()
        export_stats = stock_web.export_stock_reports(
            web_output,
            target_as_of=requested_as_of,
            reference_market_date=reference_market_date,
            include_etf=True,
            source_report_directory=staged_report_dir,
        )
    else:
        index_for_stats = read_json(index_path)
        available_common = sum(
            item.get("report_available") is True and item.get("asset_type") == "COMMON"
            for item in index_for_stats.get("items", [])
        )
        available_etf = sum(
            item.get("report_available") is True and item.get("asset_type") == "ETF"
            for item in index_for_stats.get("items", [])
        )
        export_stats = {
            "requested_as_of": requested_as_of,
            "reference_market_date": reference_market_date,
            "universe_snapshot_date": index_for_stats.get("universe_snapshot_date"),
            "universe_count": int(index_for_stats.get("count", 0)),
            "available_report_count": int(index_for_stats.get("available_report_count", 0)),
            "unavailable_report_count": int(index_for_stats.get("count", 0)) - int(index_for_stats.get("available_report_count", 0)),
            "common_report_count": available_common,
            "etf_report_count": available_etf,
            "source_report_directory": index_for_stats.get("source_report_directory"),
        }
    b_status_path = ROOT / "artifacts/strategies/b_select_core_v2/production" / requested_as_of.replace("-", "") / "status.json"
    if not monitor_path.is_file():
        if strategy_web is None:
            _, strategy_web = _load_export_modules()
        b_select_status = read_json(b_status_path)
        monitor = strategy_web.build_strategy_monitor(
            repo_root=ROOT,
            index_path=index_path,
            stocks_path=web_output / "stocks",
            target_as_of=requested_as_of,
            reference_market_date=reference_market_date,
            b_select_status=b_select_status,
            source_report_path=(web_output / "stocks" / "*.json").relative_to(ROOT).as_posix(),
        )
        write_json(monitor_path, monitor)
    else:
        monitor = read_json(monitor_path)
    old_monitor = read_json(ROOT / "web/data/strategy-monitor.json")
    parity = _verify_three_way_parity(
        stage_root, requested_as_of, reference_market_date,
        read_json(index_path), monitor, old_monitor,
    )
    prior_fast = next(
        (row for row in old_monitor.get("strategies", []) if row.get("id") in {
            "PATTERN_A_FAST_FINAL_STRATEGY_V02", PROMOTED_STRATEGY_ID,
        }),
        {},
    )
    prior_status_counts = Counter(str(row.get("trade_status") or "UNKNOWN") for row in prior_fast.get("trade_history", []))
    current_fast = next(row for row in monitor["strategies"] if row.get("id") == PROMOTED_STRATEGY_ID)
    current_status_counts = Counter(str(row.get("trade_status") or "UNKNOWN") for row in current_fast.get("trade_history") or [])

    blockers: list[dict[str, Any]] = []
    for code, count in (
        ("ADJUSTED_PRICE_SERIES_MISSING", daily_missing_count),
        ("ADJUSTED_PRICE_HISTORY_TOO_SHORT", adjusted_series_too_short_count),
        ("STOCK_METADATA_UNAVAILABLE", metadata_unavailable_count),
        ("REPLAY_STATE_UNAVAILABLE", replay_state_unavailable_count),
        ("REFERENCE_MARKET_DATE_PRICE_GAP", current_target_gap_count),
        ("UNEXPLAINED_REPOSITORY_SESSION_DROP", loader_silent_drop_count),
        ("PIT_OR_EXACT_RAW_MARKET_CAP_UNRESOLVED", unresolved_gate_count),
        ("COMPLETED_MONTH_MA_HISTORY_GAP", monthly_gap_count),
        ("STRATEGY_EVALUATOR_ERROR", engine_error_count),
    ):
        if count:
            blockers.append({"code": code, "count": count})
    status = "PASS" if not blockers else "CHECK_REQUIRED"
    output_hashes = {
        path.relative_to(stage_root).as_posix(): sha256_file(path)
        for path in sorted(stage_root.rglob("*"))
        if path.is_file() and path.name not in {"manifest.json", "report.md"}
    }
    replay_start_utc = datetime.strptime(stage_root.name.removeprefix("staging_"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    elapsed_from_stage_start = (datetime.now(timezone.utc) - replay_start_utc).total_seconds()
    original_elapsed = replay_elapsed_seconds if replay_elapsed_seconds is not None else elapsed_from_stage_start
    total_elapsed = max(original_elapsed + (time.monotonic() - started), elapsed_from_stage_start)
    manifest = {
        "schema": "a_fast_alignment_500b_web_canonical_full_history_rebuild_v01",
        "status": status,
        "completion_token": (
            "A_FAST_CORE_V2_ALIGNMENT_500B_WEB_CANONICAL_FULL_HISTORY_REBUILD_V01_PASS"
            if status == "PASS" else "A_FAST_CORE_V2_ALIGNMENT_500B_WEB_CANONICAL_FULL_HISTORY_REBUILD_V01_CHECK_REQUIRED"
        ),
        "git_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "origin_main": __import__("subprocess").check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
        "requested_as_of": requested_as_of,
        "reference_market_date": reference_market_date,
        "scanner_summary_path": str((SCANNER_ROOT / f"pattern_a_universe_scan_{requested_as_of.replace('-', '')}_summary.json").relative_to(ROOT)),
        "scanner_scope": scanner_summary,
        "source_report_directory": str(report_dir.relative_to(ROOT)),
        "source_report_count": len(report_paths),
        "published_common_monitor_scope": len(common_tickers),
        "universe_scanner_official_common_total": scanner_summary.get("official_common_total"),
        "strategy_id": PROMOTED_STRATEGY_ID,
        "strategy_name": PROMOTED_STRATEGY_NAME,
        "strategy_replay_mode": FULL_HISTORY_WEB_MODE,
        "strategy_replay_scope": scope,
        "strategy_replay_digest": digest,
        "trade_counts": {
            "realized": current_status_counts.get("REALIZED", 0),
            "open": current_status_counts.get("OPEN_AT_CUTOFF", 0),
            "total": sum(current_status_counts.values()),
            "old_v2_reference_realized": prior_status_counts.get("REALIZED", 0),
            "old_v2_reference_open": prior_status_counts.get("OPEN_AT_CUTOFF", 0),
            "old_v2_reference_total": sum(prior_status_counts.values()),
            "realized_delta_vs_old_reference": current_status_counts.get("REALIZED", 0) - prior_status_counts.get("REALIZED", 0),
            "open_delta_vs_old_reference": current_status_counts.get("OPEN_AT_CUTOFF", 0) - prior_status_counts.get("OPEN_AT_CUTOFF", 0),
            "total_delta_vs_old_reference": sum(current_status_counts.values()) - sum(prior_status_counts.values()),
        },
        "gate_decision_counts": dict(sorted(gate_reasons.items())),
        "coverage": {
            "reports_processed": len(ticker_rows),
            "expected_common_reports": len(common_tickers),
            "v2_candidate_signals_evaluated": len(gate_rows),
            "first_candidate_signal_date": scope["first_v2_candidate_signal_date"],
            "last_candidate_signal_date": scope["last_v2_candidate_signal_date"],
            "first_alignment_gate_pass_signal_date": scope["first_alignment_gate_pass_signal_date"],
            "daily_series_missing_tickers": daily_missing_count,
            "adjusted_series_too_short_tickers": adjusted_series_too_short_count,
            "metadata_unavailable_tickers": metadata_unavailable_count,
            "replay_state_unavailable_tickers": replay_state_unavailable_count,
            "reference_date_gaps": current_target_gap_count,
            "unexplained_repository_session_drops": loader_silent_drop_count,
            "pit_or_raw_market_cap_unresolved_signals": unresolved_gate_count,
            "completed_month_ma_history_gaps": monthly_gap_count,
            "strategy_evaluator_errors": engine_error_count,
            "explicit_repository_projection_exclusions": sum(
                int(json.loads(row.get("session_projection_summary") or "{}").get("explicit_exclusion_count", 0) or 0)
                for row in ticker_rows
            ),
        },
        "staging_output_only": True,
        "operational_config_enabled": config.enabled,
        "operational_config_active": config.active,
        "operational_effective_signal_date": config.effective_signal_date,
        "operational_activation_interval_count": len(activation_history),
        "b_select_status_sha256": sha256_file(b_status_path),
        "config_sha256_before_and_after": config_before,
        "activation_history_sha256_before_and_after": history_before,
        "three_way_validation": parity,
        "stock_report_export_stats": export_stats,
        "blockers": blockers,
        "elapsed_seconds": round(total_elapsed, 3),
        "replay_elapsed_seconds": round(original_elapsed, 3),
        "resume_finalization_elapsed_seconds": round(total_elapsed - original_elapsed, 3),
        "replay_finalization_reused_completed_stage": True,
        "source_report_sha256_by_ticker": source_hashes,
        "staging_file_sha256": output_hashes,
    }
    manifest_path = stage_root / "manifest.json"
    write_json(manifest_path, manifest)
    report_lines = [
        f"# FAST Core V2 Alignment 500B 웹 정본 전 기간 재생 staging — {status}",
        "",
        "| 등급 | 건수 | 판정 |",
        "|---|---:|---|",
        f"| CRITICAL | {1 if status == 'CHECK_REQUIRED' and any('INTEGRITY' in row['code'] for row in blockers) else 0} | 구조/hash 무결성 오류 여부는 blockers 참조 |",
        f"| MAJOR | {len(blockers)} | {'; '.join(row['code'] + '=' + str(row['count']) for row in blockers) if blockers else '필수 데이터·정합성 blocker 없음'} |",
        "| MINOR | 1 | 기존 공개 scope 1,459 COMMON으로 제한; scanner 전체 common 수 2,547로 확대하지 않음 |",
        "",
        f"- 기준: HEAD `{manifest['git_head']}`, origin/main `{manifest['origin_main']}`.",
        f"- 기준일: requested_as_of `{requested_as_of}`, reference_market_date `{reference_market_date}`.",
        f"- 결과: `{status}`; completion token: `{manifest['completion_token']}`.",
        f"- staging: `{stage_root.relative_to(ROOT)}`. 운영 config/history, canonical reports, `web/data`는 읽기 전용.",
        f"- 재생 범위: COMMON reports {len(common_tickers)}; source reports {len(report_paths)}; scanner official_common_total {scanner_summary.get('official_common_total')}.",
        f"- 거래: REALIZED {manifest['trade_counts']['realized']}, OPEN {manifest['trade_counts']['open']}, TOTAL {manifest['trade_counts']['total']}.",
        f"- V2 비교 참고: REALIZED {manifest['trade_counts']['old_v2_reference_realized']}, OPEN {manifest['trade_counts']['old_v2_reference_open']}, TOTAL {manifest['trade_counts']['old_v2_reference_total']}.",
        f"- V2 유효 후보 신호 평가: {len(gate_rows)}; first/last {scope['first_v2_candidate_signal_date']}/{scope['last_v2_candidate_signal_date']}; first Alignment pass {scope['first_alignment_gate_pass_signal_date']}.",
        f"- 단일 Alignment ID, report/web/monitor 거래 및 OPEN 1:1: {parity['trade_key_and_values_mismatches']} / {parity['open_key_and_values_mismatches']} mismatches; B Select/Julia unchanged={parity['b_select_unchanged']}/{parity['julia_unchanged']}.",
        f"- 운영 config enabled={config.enabled}, active={config.active}, date={config.effective_signal_date}; activation intervals={len(activation_history)}.",
        f"- 전체 staging 소요 {round(total_elapsed, 2)}초; 본 재생 소요 {round(original_elapsed, 2)}초.",
        "",
        "## Blockers",
        "",
    ]
    report_lines.extend(
        [f"- `{row['code']}`: {row['count']}" for row in blockers]
        if blockers else ["- 없음"]
    )
    report_lines.extend([
        "",
        "## 검증 범위와 한계",
        "",
        "- 보고서 JSON, Compact Stock Report, Strategy Monitor는 동일한 replay-core digest를 사용한다.",
        "- 웹 정본은 FULL_HISTORY_ALIGNMENT_WEB mode로만 생성했으며 operational activation history를 사용하거나 수정하지 않는다.",
        "- 원래 staging 실행에서 전 종목 replay 및 audit CSV/JSONL 기록이 완료된 뒤, exporter import 오류를 복구해 여기서 후처리했다.",
        "- 공식 V2 lifecycle 엔진에서 각 유효 진입 후보를 발생 순서로 평가하고 Alignment exact-date gate를 적용했다.",
        "- canonical publish, Daily Update, 운영 활성화, 주문, 공식 5기간 백테스트, commit/push는 수행하지 않았다.",
        "",
    ])
    report_path = stage_root / "report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    manifest["staging_file_sha256"]["report.md"] = sha256_file(report_path)
    write_json(manifest_path, manifest)
    print(json.dumps({
        "status": status,
        "stage_root": str(stage_root.relative_to(ROOT)),
        "strategy_replay_digest": digest,
        "trade_counts": manifest["trade_counts"],
        "coverage": manifest["coverage"],
        "blockers": blockers,
        "three_way_validation": parity,
    }, ensure_ascii=False, sort_keys=True))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", help="exact target; defaults to the stock-index scanner target")
    parser.add_argument("--staging-parent", type=Path, default=STAGING_PARENT)
    parser.add_argument("--resume-stage", type=Path, help="finalize an existing stage after its replay completed")
    parser.add_argument("--replay-elapsed-seconds", type=float, help="observed elapsed time for the already completed replay")
    args = parser.parse_args()
    result = (
        resume_completed_stage(args.resume_stage, replay_elapsed_seconds=args.replay_elapsed_seconds)
        if args.resume_stage is not None
        else run(args.target_as_of, args.staging_parent)
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
