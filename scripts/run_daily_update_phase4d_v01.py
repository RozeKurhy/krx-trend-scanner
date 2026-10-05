#!/usr/bin/env python3
"""Publish Phase 4D exact-target analysis payloads to static ``web/data``.

The runner only projects already-validated Phase 4B/4C authorities.  It has
no network path and never treats the prior web payload as an input authority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import export_foreign_net_buy_ranking_web as foreign_web
from scripts import export_market_ranking_web as market_web
from scripts import export_sector_rs_ranking_web as sector_web
from scripts import export_stock_report_web as stock_web
from scripts import export_strategy_monitor_web as strategy_web
from scripts import export_web_data as health_web
from scripts import build_b_select_core_v2_status as b_select_status_web
from scripts import run_daily_update_phase4c_v01 as phase4c
from scripts import run_pattern_a_universe_scanner as phase4a


class Phase4DError(RuntimeError):
    """Fail-closed Phase 4D validation or promotion error."""


REQUIRED_FILES = (
    "stock-index.json",
    "market-ranking.json",
    "strategy-monitor.json",
    "sector-rs-ranking.json",
    "foreign-net-buy-ranking.json",
    "health.json",
)
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
B_SELECT_ID = "PATTERN_B_SELECT_CORE_V02"
JULIA_ID = "JULIA_ETF_STRATEGY_V01"
B_SELECT_STATUS_STAGING_NAME = "b-select-status.json"


def _b_select_status_path(root: Path, target_as_of: str) -> Path:
    return root / "artifacts/strategies/b_select_core_v2/production" / target_as_of.replace("-", "") / "status.json"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise Phase4DError(f"PHASE4D_JSON_OBJECT_REQUIRED: {path}")
    return value


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise Phase4DError(f"PHASE4D_NONFINITE_VALUE: {path}")
    if isinstance(value, dict):
        for key, nested in value.items():
            _assert_finite(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_finite(nested, f"{path}[{index}]")


def _report_tickers(index: dict[str, Any]) -> set[str]:
    items = index.get("items")
    if not isinstance(items, list):
        raise Phase4DError("PHASE4D_STOCK_INDEX_ITEMS_INVALID")
    return {
        str(item.get("ticker") or "")
        for item in items
        if isinstance(item, dict) and item.get("report_available") is True
    }


def _b_select_monitor_items_match_status(
    monitor_items: Any,
    status_items: Any,
) -> bool:
    """Compare the B Select display projection with its status source.

    The monitor deliberately omits per-item trade history and adds the
    display-only fundamental status. All remaining fields must match exactly.
    """
    if not isinstance(monitor_items, list) or not isinstance(status_items, list):
        return False
    monitor_projection = [
        {key: value for key, value in item.items() if key != "fundamental_status"}
        for item in monitor_items
        if isinstance(item, dict)
    ]
    status_projection = [
        {key: value for key, value in item.items() if key != "trade_history"}
        for item in status_items
        if isinstance(item, dict)
    ]
    if len(monitor_projection) != len(monitor_items) or len(status_projection) != len(status_items):
        return False
    return monitor_projection == status_projection


_STALE_PUBLISHED_CODES = frozenset(
    {
        "PHASE4D_STOCK_DATE_MISMATCH",
        "PHASE4D_DATE_MISMATCH",
        "PHASE4D_MARKET_AS_OF_MISMATCH",
    }
)


def inspect_published_payload(
    root: Path,
    target_as_of: str,
    *,
    require_etf_source: bool = False,
) -> dict[str, Any] | None:
    """Validate an already-published exact-target payload without writing.

    ``None`` means the publication is absent or belongs to another target, so the
    caller may proceed with the normal staging path.  A present-but-malformed or
    internally inconsistent exact-target publication raises the existing Phase 4D
    validation error instead of being silently treated as a NOOP.
    """

    web_data = root / "web/data"
    if any(not (web_data / name).is_file() for name in REQUIRED_FILES):
        return None
    if not (web_data / "stocks").is_dir():
        return None
    status_path = _b_select_status_path(root, target_as_of)

    try:
        scanner_summary = phase4c.load_scanner_summary(root, target_as_of)
    except phase4c.Phase4CError as exc:
        code = str(exc).split(":", 1)[0]
        if code == "PHASE4C_SCANNER_SUMMARY_MISSING":
            return None
        raise
    reference_market_date = str(scanner_summary["reference_market_date"])
    expected_reference_market_date = phase4a.resolve_reference_market_date(
        target_as_of,
        phase4a.load_rolling_production_market_calendar(root),
    )
    if reference_market_date != expected_reference_market_date:
        raise Phase4DError(
            "PHASE4D_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH: "
            f"expected {expected_reference_market_date}, got {reference_market_date}"
        )
    if require_etf_source:
        try:
            stock_web.validate_exact_etf_report_corpus(target_as_of, reference_market_date)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise Phase4DError(f"PHASE4D_ETF36_SOURCE_INVALID: {exc}") from exc
    if not status_path.is_file():
        return None
    try:
        validation = validate_staging(
            web_data,
            target_as_of,
            reference_market_date,
            require_etf36=require_etf_source,
            b_select_status_path=status_path,
        )
    except Phase4DError as exc:
        code = str(exc).split(":", 1)[0]
        if code in _STALE_PUBLISHED_CODES or code == "PHASE4D_ETF36_SET_MISMATCH":
            return None
        raise
    return {
        "reference_market_date": reference_market_date,
        "validation": validation,
    }


def _stage_payloads(
    target_as_of: str,
    stage_data: Path,
    *,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if phase4c_result is None:
        phase4c_result = phase4c.run_phase4c(target_as_of, root=ROOT)
    if phase4c_result.get("status") not in {"PASS", "NOOP_ALREADY_COMPLETE"} or phase4c_result.get("network_calls") != 0:
        raise Phase4DError("PHASE4D_PHASE4C_PREREQUISITE_FAILED")
    if phase4c_result.get("web_data_writes") != 0:
        raise Phase4DError("PHASE4D_PHASE4C_WEB_WRITE_DETECTED")
    reference_market_date = str(phase4c_result.get("reference_market_date") or "")
    if not reference_market_date or reference_market_date > target_as_of:
        raise Phase4DError("PHASE4D_REFERENCE_MARKET_DATE_INVALID")

    index, reports, report_stats = stock_web.build_web_payload(
        ROOT, target_as_of=target_as_of, reference_market_date=reference_market_date, include_etf=True,
    )
    _write_json(stage_data / "stock-index.json", index)
    stocks_dir = stage_data / "stocks"
    for ticker, report in sorted(reports.items()):
        _write_json(stocks_dir / f"{ticker}.json", report)

    market = market_web.build_market_ranking(
        index_path=stage_data / "stock-index.json", stocks_dir=stocks_dir,
    )
    _write_json(stage_data / "market-ranking.json", market)
    b_status = (
        phase4c_result.get("_b_select_status_for_phase4d")
        if isinstance(phase4c_result, dict)
        else None
    )
    if not isinstance(b_status, dict):
        b_status = b_select_status_web.build_b_select_status(
            repo_root=ROOT,
            index_path=stage_data / "stock-index.json",
            stocks_path=stocks_dir,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
        )
    _write_json(stage_data / B_SELECT_STATUS_STAGING_NAME, b_status)
    strategy = phase4c_result.get("_strategy_monitor_for_phase4d")
    if not isinstance(strategy, dict):
        strategy = strategy_web.build_strategy_monitor(
            index_path=stage_data / "stock-index.json",
            stocks_path=stocks_dir,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
            b_select_status=b_status,
        )
    _write_json(stage_data / "strategy-monitor.json", strategy)

    dt_clean = target_as_of.replace("-", "")
    sector_membership_effective_date, sector_membership_path = phase4c.resolve_sector_membership_for_target(
        target_as_of,
        root=ROOT,
    )
    sector = sector_web.build_sector_rs_web_payload(
        ranking_path=ROOT / "data/analytics/sector_rs_ranking/v01" / f"sector_rs_ranking_{dt_clean}.parquet",
        meta_path=ROOT / "data/analytics/sector_rs_ranking/v01" / f"sector_rs_ranking_{dt_clean}_meta.json",
        basic_info_dir=phase4c.resolve_basic_info_dir(ROOT, target_as_of),
        stocks_dir=stocks_dir,
        expected_as_of=reference_market_date,
        requested_as_of=target_as_of,
        reference_market_date=reference_market_date,
    )
    _write_json(stage_data / "sector-rs-ranking.json", sector)
    foreign = foreign_web.build_foreign_net_buy_ranking(
        index_path=stage_data / "stock-index.json",
        flow_path=ROOT / "artifacts/patterns/pattern_a/production/flow/source" / f"foreign_flow_daily_{dt_clean}.parquet",
        sector_path=sector_membership_path,
        common_authority_path=ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01" / f"market_rs_universe_{dt_clean}.csv",
        as_of=reference_market_date,
        requested_as_of=target_as_of,
        reference_market_date=reference_market_date,
        identity_as_of=target_as_of,
        repo_root=ROOT,
    )
    _write_json(stage_data / "foreign-net-buy-ranking.json", foreign)
    health = health_web.build_health(ROOT, target_as_of=target_as_of, web_data_root=stage_data)
    _write_json(stage_data / "health.json", health)

    return {
        "phase4c": phase4c_result,
        "reference_market_date": reference_market_date,
        "sector_membership": {
            "effective_date": sector_membership_effective_date,
            "path": str(sector_membership_path),
        },
        "report_stats": report_stats,
        "b_select_status": {
            "status": b_status.get("status"),
            "count": b_status.get("count"),
            "counts": b_status.get("counts"),
            "evaluation_error_count": b_status.get("evaluation_error_count"),
            "network_requests": b_status.get("network_requests"),
        },
    }


def validate_staging(
    stage_data: Path,
    target_as_of: str,
    reference_market_date: str,
    *,
    require_etf36: bool = False,
    b_select_status_path: Path | None = None,
) -> dict[str, Any]:
    missing = [name for name in REQUIRED_FILES if not (stage_data / name).is_file()]
    if missing or not (stage_data / "stocks").is_dir():
        raise Phase4DError(f"PHASE4D_STAGE_REQUIRED_OUTPUT_MISSING: {missing}")
    documents = {name: _read_json(stage_data / name) for name in REQUIRED_FILES}
    if b_select_status_path is None:
        staged_status = stage_data / B_SELECT_STATUS_STAGING_NAME
        if staged_status.is_file():
            b_select_status_path = staged_status
        else:
            b_select_status_path = _b_select_status_path(ROOT, target_as_of)
    if not b_select_status_path.is_file():
        raise Phase4DError("PHASE4D_B_SELECT_STATUS_MISSING")
    b_status = _read_json(b_select_status_path)
    stock_paths = sorted((stage_data / "stocks").glob("*.json"))
    stocks = {path.stem: _read_json(path) for path in stock_paths}
    for name, document in documents.items():
        _assert_finite(document, name)
    _assert_finite(b_status, "b-select-status.json")
    for ticker, document in stocks.items():
        _assert_finite(document, f"stocks/{ticker}.json")

    index = documents["stock-index.json"]
    report_tickers = _report_tickers(index)
    if not report_tickers or report_tickers != set(stocks) or index.get("available_report_count") != len(report_tickers):
        raise Phase4DError("PHASE4D_STOCK_REPORT_SET_MISMATCH")
    common_tickers = {
        str(item.get("ticker") or "")
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("report_available") is True and item.get("asset_type", "COMMON") == "COMMON"
    }
    etf_tickers = {
        str(item.get("ticker") or "")
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("report_available") is True and item.get("asset_type") == "ETF"
    }
    if common_tickers | etf_tickers != report_tickers or common_tickers & etf_tickers:
        raise Phase4DError("PHASE4D_STOCK_ASSET_SET_MISMATCH")
    if require_etf36:
        from trend_scanner.reporting.julia_v1_report import load_official_etf36

        expected_etf_tickers = {identity.ticker for identity in load_official_etf36(ROOT)[0]}
        if etf_tickers != expected_etf_tickers:
            raise Phase4DError(
                "PHASE4D_ETF36_SET_MISMATCH: "
                f"expected={len(expected_etf_tickers)} actual={len(etf_tickers)}"
            )
    for ticker, report in stocks.items():
        technical = report.get("technical_details") or {}
        if technical.get("requested_as_of") != target_as_of or technical.get("reference_market_date") != reference_market_date:
            raise Phase4DError(f"PHASE4D_STOCK_DATE_MISMATCH: {ticker}")
        identity = report.get("identity") or {}
        asset_type = identity.get("asset_type")
        expected_version = "0.6" if asset_type == "ETF" else "0.7"
        if technical.get("report_version") != expected_version:
            raise Phase4DError(f"PHASE4D_STOCK_REPORT_VERSION_MISMATCH: {ticker}")
        strategy_section = report.get("strategy") or {}
        if asset_type == "ETF":
            if (
                strategy_section.get("source") != "official_strategy"
                or strategy_section.get("strategy_id") != "JULIA_ETF_STRATEGY_V01"
                or strategy_section.get("strategy_name") != "Julia V1"
                or report.get("pattern_b") is not None
            ):
                raise Phase4DError(f"PHASE4D_ETF_REPORT_CONTRACT_MISMATCH: {ticker}")
        elif strategy_section.get("id") not in {None, STRATEGY_ID}:
            raise Phase4DError(f"PHASE4D_STOCK_STRATEGY_MISMATCH: {ticker}")

    for name in REQUIRED_FILES:
        document = documents[name]
        if document.get("requested_as_of") != target_as_of or document.get("reference_market_date") != reference_market_date:
            raise Phase4DError(f"PHASE4D_DATE_MISMATCH: {name}")
    if (documents["health.json"].get("stock_reports") or {}).get("report_version") != "0.7":
        raise Phase4DError("PHASE4D_STOCK_REPORT_VERSION_MISMATCH: health.json")
    market = documents["market-ranking.json"]
    strategy = documents["strategy-monitor.json"]
    if {item.get("ticker") for item in market.get("items", [])} != common_tickers:
        raise Phase4DError("PHASE4D_MARKET_SET_MISMATCH")
    if market.get("scope", {}).get("report_count") != len(common_tickers):
        raise Phase4DError("PHASE4D_REPORT_COUNT_MISMATCH")
    if strategy.get("schema_version") != 2 or strategy.get("default_strategy_id") != STRATEGY_ID:
        raise Phase4DError("PHASE4D_STRATEGY_MONITOR_SCHEMA_INVALID")
    if strategy.get("requested_as_of") != target_as_of or strategy.get("reference_market_date") != reference_market_date:
        raise Phase4DError("PHASE4D_STRATEGY_MONITOR_DATE_MISMATCH")
    strategy_rows = strategy.get("strategies")
    if not isinstance(strategy_rows, list) or [row.get("id") for row in strategy_rows] != [STRATEGY_ID, B_SELECT_ID, JULIA_ID]:
        raise Phase4DError("PHASE4D_STRATEGY_SET_INVALID")
    strategy_by_id = {row["id"]: row for row in strategy_rows}
    expected_strategy_scopes = {
        STRATEGY_ID: ("COMMON", common_tickers),
        B_SELECT_ID: ("COMMON", common_tickers),
        JULIA_ID: ("OFFICIAL_ETF_36", etf_tickers),
    }
    for strategy_id, (asset_scope, expected_tickers) in expected_strategy_scopes.items():
        row = strategy_by_id[strategy_id]
        items = row.get("items")
        scope = row.get("scope") or {}
        if (
            row.get("asset_scope") != asset_scope
            or not isinstance(items, list)
            or scope.get("report_count") != len(expected_tickers)
            or len(items) != len(expected_tickers)
            or {str(item.get("ticker", "")).zfill(6) for item in items} != expected_tickers
            or len({str(item.get("ticker", "")).zfill(6) for item in items}) != len(items)
        ):
            raise Phase4DError(f"PHASE4D_STRATEGY_SCOPE_MISMATCH:{strategy_id}")
        expected_asset = "ETF" if asset_scope == "OFFICIAL_ETF_36" else "COMMON"
        if any(item.get("asset_type") != expected_asset for item in items):
            raise Phase4DError(f"PHASE4D_STRATEGY_ASSET_CONTAMINATION:{strategy_id}")
        counts = row.get("counts") or {}
        if sum(int(counts.get(key, 0)) for key in ("entry", "hold", "exit", "watch", "unavailable")) != len(items):
            raise Phase4DError(f"PHASE4D_STRATEGY_COUNTS_MISMATCH:{strategy_id}")

    b_items = strategy_by_id[B_SELECT_ID]["items"]
    if (
        b_status.get("status") != "PASS"
        or b_status.get("strategy_id") != B_SELECT_ID
        or b_status.get("requested_as_of") != target_as_of
        or b_status.get("reference_market_date") != reference_market_date
        or b_status.get("network_requests") != 0
        or b_status.get("evaluation_error_count") != 0
        or b_status.get("date_mismatch_count") != 0
        or b_status.get("future_reference_count") != 0
        or b_status.get("duplicate_item_count") != 0
        or b_status.get("cross_strategy_contamination_count") != 0
        or b_status.get("permanent_identity_exclusion_count") != 181
        or (b_status.get("source_authorities") or {}).get("signal_cadence") != "MONTH_END_ENTRY_DAILY_NORMAL_EXIT"
        or b_status.get("scope", {}).get("type") != "PUBLISHED_COMMON_REPORTS"
        or b_status.get("count") != len(common_tickers)
        or len(b_status.get("items", [])) != len(common_tickers)
        or {str(item.get("ticker", "")).zfill(6) for item in b_status.get("items", [])} != common_tickers
        or not _b_select_monitor_items_match_status(b_items, b_status.get("items"))
        or strategy_by_id[B_SELECT_ID].get("counts") != b_status.get("counts")
    ):
        raise Phase4DError("PHASE4D_B_SELECT_STATUS_INVALID")
    migration = b_status.get("promotion_migration")
    migrated_open = migration.get("migrated_open_positions") if isinstance(migration, dict) else None
    if (
        not isinstance(migration, dict)
        or migration.get("source_strategy_id") != "PATTERN_B_SELECT_CORE_V01"
        or not isinstance(migrated_open, list)
        or migration.get("migrated_open_position_count") != len(migrated_open)
        or b_status.get("migration_open_position_parity_count") != len(migrated_open)
        or len({(row.get("ticker"), row.get("isu_cd")) for row in migrated_open if isinstance(row, dict)}) != len(migrated_open)
        or strategy_by_id[B_SELECT_ID].get("label") != "B Select Core V2"
    ):
        raise Phase4DError("PHASE4D_B_SELECT_MIGRATION_AUDIT_INVALID")
    if target_as_of == phase4c.V2_PROMOTION_SEED_TARGET_AS_OF:
        catchup_audit = b_status.get("catchup_audit") or {}
        migrated_keys = {
            (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())
            for row in migrated_open
            if isinstance(row, dict)
        }
        excluded_open_key = ("011080", "KR7011080009")
        excluded_open_item = next(
            (
                item for item in b_status.get("items", [])
                if (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
                == excluded_open_key
            ),
            None,
        )
        if (
            reference_market_date != phase4c.V2_PROMOTION_BASELINE_REFERENCE_DATE
            or len(migrated_open) != 26
            or len(migrated_keys) != 26
            or excluded_open_key not in migrated_keys
            or b_status.get("reference_run_entry_signal_count") != 0
            or b_status.get("inherited_excluded_open_exception_count") != 1
            or catchup_audit.get("replay_mode") != "V1_SAME_REFERENCE_PROMOTION_SEED_NO_RETROACTIVE_SIGNALS"
            or catchup_audit.get("catchup_session_count") != 0
            or catchup_audit.get("catchup_identity_count") != 0
            or catchup_audit.get("catchup_intermediate_observation_count") != 0
            or not isinstance(excluded_open_item, dict)
            or excluded_open_item.get("canonical_position") != "OPEN"
            or excluded_open_item.get("inherited_excluded_open_exception") is not True
            or excluded_open_item.get("permanent_identity_excluded") is not True
        ):
            raise Phase4DError("PHASE4D_B_SELECT_V2_PROMOTION_SEED_INVALID")
    for item in b_status.get("items", []):
        if item.get("permanent_identity_excluded") is True and any(
            trade.get("strategy_id") == B_SELECT_ID
            for trade in item.get("trade_history", [])
            if isinstance(trade, dict)
        ):
            raise Phase4DError(f"PHASE4D_B_SELECT_EXCLUDED_ENTRY_LEAKAGE:{item.get('ticker')}")
        if item.get("latest_close_as_of") not in {None, reference_market_date}:
            raise Phase4DError(f"PHASE4D_B_SELECT_LATEST_CLOSE_DATE_INVALID:{item.get('ticker')}")
        trade = item.get("current_trade")
        if isinstance(trade, dict) and str(trade.get("entry_execution_date", ""))[:10] > reference_market_date:
            raise Phase4DError(f"PHASE4D_B_SELECT_FUTURE_POSITION_FILL:{item.get('ticker')}")
        pending = item.get("pending_event")
        if isinstance(pending, dict) and pending.get("execution_date") is not None and str(pending["execution_date"])[:10] <= reference_market_date:
            raise Phase4DError(f"PHASE4D_B_SELECT_PENDING_EVENT_NOT_FILLED:{item.get('ticker')}")

    if target_as_of == "2026-09-25" and reference_market_date == "2026-09-23":
        fast = strategy_by_id[STRATEGY_ID]
        if fast.get("scope", {}).get("report_count") != 1451 or fast.get("counts") != {
            "entry": 0, "hold": 241, "exit": 0, "watch": 0, "unavailable": 1210,
        }:
            raise Phase4DError("PHASE4D_A_FAST_BASELINE_REGRESSION")
        if strategy_by_id[JULIA_ID].get("scope", {}).get("report_count") != 36:
            raise Phase4DError("PHASE4D_JULIA_ETF36_COUNT_MISMATCH")

    sector = documents["sector-rs-ranking.json"]
    foreign = documents["foreign-net-buy-ranking.json"]
    if sector.get("as_of") != reference_market_date or foreign.get("as_of") != reference_market_date:
        raise Phase4DError("PHASE4D_MARKET_AS_OF_MISMATCH")
    if sum(bool(item.get("report_available")) for item in sector.get("items", [])) != len(common_tickers):
        raise Phase4DError("PHASE4D_SECTOR_REPORT_COUNT_MISMATCH")
    if sum(bool(item.get("report_available")) for item in foreign.get("items", [])) != len(common_tickers):
        raise Phase4DError("PHASE4D_FOREIGN_REPORT_COUNT_MISMATCH")
    health = documents["health.json"]
    readiness = health.get("stock_reports") or {}
    if health.get("overall_status") != "NORMAL":
        raise Phase4DError("PHASE4D_HEALTH_OVERALL_NOT_NORMAL")
    fundamentals = health.get("fundamentals") or {}
    if fundamentals.get("status") != "NORMAL":
        raise Phase4DError("PHASE4D_HEALTH_FUNDAMENTALS_NOT_NORMAL")
    integrity = fundamentals.get("output_integrity") or {}
    if any(integrity.get(key) != 0 for key in (
        "outside_universe_count",
        "invalid_output_count",
        "duplicate_payload_count",
    )):
        raise Phase4DError("PHASE4D_HEALTH_FUNDAMENTALS_INTEGRITY_FAILED")
    if readiness.get("ready") is not True or readiness.get("source_json_count") != len(common_tickers):
        raise Phase4DError("PHASE4D_HEALTH_STAGING_READINESS_FAILED")
    if readiness.get("web_compact_count") != len(common_tickers) or readiness.get("web_index_available_report_count") != len(common_tickers):
        raise Phase4DError("PHASE4D_HEALTH_STAGE_WEB_COUNT_MISMATCH")
    return {
        "stock_report_count": len(report_tickers),
        "common_stock_report_count": len(common_tickers),
        "etf_stock_report_count": len(etf_tickers),
        "sector_population_count": sector.get("scope", {}).get("population_count"),
        "foreign_population_count": foreign.get("coverage", {}).get("target_common_universe_count"),
        "foreign_flow_covered_count": foreign.get("coverage", {}).get("flow_covered_count"),
        "health_overall_status": health.get("overall_status"),
        "strategy_monitor_strategy_count": len(strategy_rows),
        "b_select_status_count": b_status.get("count"),
        "b_select_evaluation_error_count": b_status.get("evaluation_error_count"),
        "b_select_date_mismatch_count": b_status.get("date_mismatch_count"),
        "b_select_future_reference_count": b_status.get("future_reference_count"),
        "b_select_duplicate_item_count": b_status.get("duplicate_item_count"),
        "b_select_cross_strategy_contamination_count": b_status.get("cross_strategy_contamination_count"),
        "b_select_network_requests": b_status.get("network_requests"),
    }


def promote(stage_data: Path, web_data: Path, *, target_as_of: str) -> Path:
    backup = web_data.parent / f".phase4d-stocks-backup-{os.getpid()}"
    staged_stocks = stage_data / "stocks"
    destination_stocks = web_data / "stocks"
    status_source = stage_data / B_SELECT_STATUS_STAGING_NAME
    status_destination = _b_select_status_path(web_data.parent.parent, target_as_of)
    status_backup = status_destination.with_name(f".status-backup-{os.getpid()}.json")
    status_destination.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise Phase4DError(f"PHASE4D_BACKUP_PATH_EXISTS: {backup}")
    if status_backup.exists():
        raise Phase4DError(f"PHASE4D_BACKUP_PATH_EXISTS: {status_backup}")
    try:
        if destination_stocks.exists():
            destination_stocks.replace(backup)
        staged_stocks.replace(destination_stocks)
        for name in REQUIRED_FILES:
            (stage_data / name).replace(web_data / name)
        if status_destination.exists():
            status_destination.replace(status_backup)
        status_source.replace(status_destination)
    except Exception:
        if not destination_stocks.exists() and backup.exists():
            backup.replace(destination_stocks)
        if not status_destination.exists() and status_backup.exists():
            status_backup.replace(status_destination)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)
        if status_backup.exists():
            status_backup.unlink()
    return status_destination


def run_phase4d(
    target_as_of: str,
    *,
    execute_live: bool,
    root: Path = ROOT,
    phase4c_result: dict[str, Any] | None = None,
    v2_promotion_seed: bool = False,
) -> dict[str, Any]:
    if root != ROOT:
        raise Phase4DError("PHASE4D_REPOSITORY_ROOT_MISMATCH")
    if v2_promotion_seed and target_as_of != phase4c.V2_PROMOTION_SEED_TARGET_AS_OF:
        raise Phase4DError("PHASE4D_V2_PROMOTION_SEED_SCOPE_INVALID")
    published = inspect_published_payload(root, target_as_of, require_etf_source=True)
    if published is not None:
        return {
            "status": "NOOP_ALREADY_COMPLETE",
            "target_as_of": target_as_of,
            "requested_as_of": target_as_of,
            "reference_market_date": published["reference_market_date"],
            "execute_live": execute_live,
            "network_calls": 0,
            "web_data_writes": 0,
            "published": published["validation"],
        }
    web_data = root / "web/data"
    stage_root = Path(tempfile.mkdtemp(prefix=".phase4d-stage-", dir=web_data.parent))
    try:
        stage_data = stage_root / "data"
        stage_data.mkdir()
        if phase4c_result is None and v2_promotion_seed:
            phase4c_result = phase4c.run_phase4c(
                target_as_of,
                root=ROOT,
                v2_promotion_seed=True,
            )
        context = _stage_payloads(target_as_of, stage_data, phase4c_result=phase4c_result)
        validation = validate_staging(
            stage_data, target_as_of, context["reference_market_date"], require_etf36=True,
        )
        if execute_live:
            status_path = promote(stage_data, web_data, target_as_of=target_as_of)
            readback = validate_staging(
                web_data,
                target_as_of,
                context["reference_market_date"],
                require_etf36=True,
                b_select_status_path=status_path,
            )
        else:
            readback = None
        return {
            "status": "PASS",
            "target_as_of": target_as_of,
            "requested_as_of": target_as_of,
            "reference_market_date": context["reference_market_date"],
            "execute_live": execute_live,
            "network_calls": 0,
            "sector_membership": context["sector_membership"],
            "staging": validation,
            "post_promote_readback": readback,
        }
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    parser.add_argument("--execute-live", action="store_true", help="promote validated staging payloads to web/data")
    parser.add_argument(
        "--v2-promotion-seed",
        action="store_true",
        help="authorize only the 2026-10-03 V2 seed from the sealed 2026-10-02 V1 snapshot",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run_phase4d(
            args.target_as_of,
            execute_live=args.execute_live,
            v2_promotion_seed=args.v2_promotion_seed,
        ), ensure_ascii=False, indent=2))
        return 0
    except (Phase4DError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
