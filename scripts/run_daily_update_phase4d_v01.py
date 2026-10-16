#!/usr/bin/env python3
"""Publish Phase 4D exact-target analysis payloads to static ``web/data``.

The runner only projects already-validated Phase 4B/4C authorities.  It has
no network path and never treats the prior web payload as an input authority.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import uuid
from typing import Any, Callable


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
from scripts import export_b_select_core_v2_identity_reports_web as identity_reports_web
from scripts import run_daily_update_phase4b_v01 as phase4b
from scripts import run_daily_update_phase4c_v01 as phase4c
from scripts import run_pattern_a_universe_scanner as phase4a
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


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
PROMOTED_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
FAST_STRATEGY_IDS = {STRATEGY_ID, PROMOTED_STRATEGY_ID}
B_SELECT_ID = "PATTERN_B_SELECT_CORE_V02"
JULIA_ID = "JULIA_ETF_STRATEGY_V01"
B_SELECT_STATUS_STAGING_NAME = "b-select-status.json"
PHASE4D_PUBLISH_JOURNAL = ".phase4d-publish-transaction.json"
DAILY_ALIGNMENT_TARGET_AS_OF = "2026-10-15"
DAILY_ALIGNMENT_REFERENCE_MARKET_DATE = "2026-10-15"
DAILY_ALIGNMENT_REPLAY_DIGEST = "eb9137d752331b71b2570bd742dd1cc2d3c66dedd8dc6303fa5ecb346d423b81"
_DAILY_ALIGNMENT_PROMOTION_AUTHORITY = object()


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
    expected_exclusion_count = None
    if target_as_of == "2026-10-11":
        monitor = _read_json(web_data / "strategy-monitor.json")
        if monitor.get("strategy_replay_digest") == V13_ALIGNMENT_CANDIDATE_DIGEST:
            expected_exclusion_count = V13_ALIGNMENT_PERMANENT_EXCLUSION_COUNT
    try:
        validation = validate_staging(
            web_data,
            target_as_of,
            reference_market_date,
            require_etf36=require_etf_source,
            b_select_status_path=status_path,
            expected_permanent_identity_exclusion_count=expected_exclusion_count,
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


def _canonical_full_history_alignment_provenance(
    root: Path,
    target_as_of: str,
    reference_market_date: str,
) -> dict[str, Any] | None:
    """Validate the exact-date canonical when it declares a full-history replay.

    A valid legacy V2 corpus returns ``None`` so the existing daily NOOP contract
    remains unchanged. Once any COMMON report declares the promoted replay, the
    complete canonical corpus must validate or Phase 4D fails closed.
    """
    report_dir = root / "artifacts/reporting/stock_reports" / target_as_of.replace("-", "")
    json_dir = report_dir / "json"
    report_paths = sorted(json_dir.glob("*.json")) if json_dir.is_dir() else []
    if not report_paths:
        if report_dir.exists() and any(report_dir.rglob("*.md")):
            raise Phase4DError("PHASE4D_CANONICAL_STOCK_REPORT_CORPUS_INCOMPLETE")
        return None

    common_tickers: set[str] = set()
    declares_alignment = False
    parse_errors: list[str] = []
    for path in report_paths:
        try:
            report = _read_json(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            parse_errors.append(path.name)
            continue
        if report.get("asset_type") != "COMMON":
            continue
        ticker = str(report.get("ticker") or "").strip().upper().zfill(6)
        if ticker:
            common_tickers.add(ticker)
        core = report.get("a_fast_core")
        if isinstance(core, dict) and (
            core.get("strategy_replay_mode") == phase4b.FULL_HISTORY_ALIGNMENT_WEB
            or core.get("strategy_id") == PROMOTED_STRATEGY_ID
        ):
            declares_alignment = True

    if not declares_alignment:
        return None
    if parse_errors:
        raise Phase4DError("PHASE4D_CANONICAL_FULL_HISTORY_ALIGNMENT_INVALID: REPORT_JSON_INVALID")
    try:
        validation = phase4b.validate_full_history_alignment_corpus(
            report_dir,
            target_as_of,
            reference_market_date,
            common_tickers,
        )
    except (OSError, UnicodeError, ValueError, phase4b.Phase4BError) as exc:
        raise Phase4DError(f"PHASE4D_CANONICAL_FULL_HISTORY_ALIGNMENT_INVALID: {exc}") from exc
    scope = validation.get("strategy_replay_scope")
    if (
        validation.get("valid") is not True
        or validation.get("strategy_id") != PROMOTED_STRATEGY_ID
        or validation.get("strategy_replay_mode") != phase4b.FULL_HISTORY_ALIGNMENT_WEB
        or not isinstance(validation.get("strategy_replay_digest"), str)
        or not isinstance(scope, dict)
        or scope.get("requested_as_of") != target_as_of
        or scope.get("reference_market_date") != reference_market_date
        or scope.get("report_count") != validation.get("common_report_count")
        or scope.get("output_strategy_id") != PROMOTED_STRATEGY_ID
    ):
        reasons = validation.get("reason_codes") or ["CANONICAL_PROVENANCE_INVALID"]
        raise Phase4DError(
            "PHASE4D_CANONICAL_FULL_HISTORY_ALIGNMENT_INVALID: " + ",".join(map(str, reasons))
        )
    return validation


def _published_monitor_matches_canonical_full_history_alignment(
    root: Path,
    target_as_of: str,
    reference_market_date: str,
    canonical: dict[str, Any],
) -> bool:
    """Return whether the published FAST row reflects the validated canonical."""
    try:
        monitor = _read_json(root / "web/data/strategy-monitor.json")
    except (OSError, UnicodeError, ValueError, Phase4DError):
        return False
    fast_rows = [
        row for row in monitor.get("strategies", [])
        if isinstance(row, dict) and row.get("id") in FAST_STRATEGY_IDS
    ]
    if len(fast_rows) != 1:
        return False
    fast_row = fast_rows[0]
    digest = canonical.get("strategy_replay_digest")
    scope = canonical.get("strategy_replay_scope")
    return bool(
        fast_row.get("id") == PROMOTED_STRATEGY_ID
        and monitor.get("strategy_replay_mode") == phase4b.FULL_HISTORY_ALIGNMENT_WEB
        and monitor.get("strategy_replay_digest") == digest
        and monitor.get("strategy_replay_scope") == scope
        and fast_row.get("strategy_replay_mode") == phase4b.FULL_HISTORY_ALIGNMENT_WEB
        and fast_row.get("strategy_replay_digest") == digest
        and fast_row.get("strategy_replay_scope") == scope
        and monitor.get("requested_as_of") == target_as_of
        and monitor.get("reference_market_date") == reference_market_date
    )


def _run_phase4c_for_phase4d(target_as_of: str) -> dict[str, Any]:
    """Reuse an exact-date canonical B Select status instead of recalculating it."""
    status_path = _b_select_status_path(ROOT, target_as_of)
    if not status_path.is_file():
        return phase4c.run_phase4c(target_as_of, root=ROOT)
    status = _read_json(status_path)
    if (
        status.get("status") != "PASS"
        or status.get("strategy_id") != B_SELECT_ID
        or status.get("requested_as_of") != target_as_of
        or status.get("network_requests") != 0
    ):
        raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_STATUS_INVALID")
    return phase4c.run_phase4c(
        target_as_of,
        root=ROOT,
        b_select_status_override=status,
    )


def _foreign_net_buy_payload(phase4c_result: dict[str, Any], **build_args: Any) -> dict[str, Any]:
    """Reuse the exact payload already computed and validated by Phase 4C."""
    payload = phase4c_result.get("_foreign_net_buy_for_phase4d")
    if isinstance(payload, dict):
        return payload
    return foreign_web.build_foreign_net_buy_ranking(**build_args)


def _stage_payloads(
    target_as_of: str,
    stage_data: Path,
    *,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if phase4c_result is None:
        phase4c_result = _run_phase4c_for_phase4d(target_as_of)
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

    identity_route_validation = None
    if isinstance(b_status.get("canonical_trade_history"), list):
        identity_routes, supplemental_reports = identity_reports_web.build_identity_routes(
            status_data=b_status,
            index_data=index,
            pit_data=identity_reports_web._read(identity_reports_web.PIT_PATH),
            monitor_data=strategy,
            stocks_dir=stocks_dir,
            output_dir=stage_data / "identity-reports",
            expected_requested_as_of=target_as_of,
            expected_reference_market_date=reference_market_date,
        )
        _write_json(stage_data / "identity-report-routes.json", identity_routes)
        identity_route_validation = identity_reports_web.validate_identity_routes(stage_data, b_status)
    elif target_as_of >= "2026-10-15":
        raise Phase4DError("PHASE4D_CANONICAL_B_SELECT_HISTORY_REQUIRED_FOR_IDENTITY_ROUTES")

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
    foreign = _foreign_net_buy_payload(
        phase4c_result,
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
        "identity_routes": (
            {
                **identity_route_validation,
                "supplemental_report_paths": [
                    path.relative_to(stage_data).as_posix() for path in supplemental_reports
                ],
            }
            if identity_route_validation is not None
            else {"status": "NOT_APPLICABLE", "route_count": 0, "supplemental_report_paths": []}
        ),
    }


def validate_staging(
    stage_data: Path,
    target_as_of: str,
    reference_market_date: str,
    *,
    require_etf36: bool = False,
    b_select_status_path: Path | None = None,
    expected_permanent_identity_exclusion_count: int | None = None,
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
    if expected_permanent_identity_exclusion_count is None:
        expected_permanent_identity_exclusion_count = len(PERMANENT_IDENTITY_EXCLUSIONS)
    stock_paths = sorted((stage_data / "stocks").glob("*.json"))
    stocks = {path.stem: _read_json(path) for path in stock_paths}
    for name, document in documents.items():
        _assert_finite(document, name)
    _assert_finite(b_status, "b-select-status.json")
    for ticker, document in stocks.items():
        _assert_finite(document, f"stocks/{ticker}.json")

    identity_route_path = stage_data / "identity-report-routes.json"
    if target_as_of >= "2026-10-15" and not identity_route_path.is_file():
        raise Phase4DError("PHASE4D_IDENTITY_ROUTE_TABLE_REQUIRED")
    identity_route_validation = None
    if identity_route_path.is_file():
        route_metadata = _read_json(identity_route_path)
        route_dates_match = (
            route_metadata.get("requested_as_of") == target_as_of
            and route_metadata.get("reference_market_date") == reference_market_date
        )
        if route_dates_match:
            try:
                identity_route_validation = identity_reports_web.validate_identity_routes(stage_data, b_status)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise Phase4DError(f"PHASE4D_IDENTITY_ROUTE_INTEGRITY_FAILED: {exc}") from exc
        elif target_as_of >= "2026-10-15":
            raise Phase4DError("PHASE4D_IDENTITY_ROUTE_DATE_MISMATCH")

    index = documents["stock-index.json"]
    report_tickers = _report_tickers(index)
    if not report_tickers or report_tickers != set(stocks) or index.get("available_report_count") != len(report_tickers):
        raise Phase4DError("PHASE4D_STOCK_REPORT_SET_MISMATCH")
    report_fast_strategy_ids: set[str] = set()
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
        elif strategy_section.get("id") is not None and strategy_section.get("id") not in FAST_STRATEGY_IDS:
            raise Phase4DError(f"PHASE4D_STOCK_STRATEGY_MISMATCH: {ticker}")
        elif asset_type == "COMMON":
            report_fast_strategy_ids.add(str(strategy_section.get("id") or STRATEGY_ID))

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
    strategy_rows = strategy.get("strategies")
    if not isinstance(strategy_rows, list):
        raise Phase4DError("PHASE4D_STRATEGY_SET_INVALID")
    fast_rows = [row for row in strategy_rows if isinstance(row, dict) and row.get("id") in FAST_STRATEGY_IDS]
    if strategy.get("schema_version") != 2 or len(fast_rows) != 1:
        raise Phase4DError("PHASE4D_STRATEGY_MONITOR_SCHEMA_INVALID")
    fast_strategy_id = fast_rows[0]["id"]
    if strategy.get("default_strategy_id") != fast_strategy_id:
        raise Phase4DError("PHASE4D_FAST_STRATEGY_DEFAULT_MISMATCH")
    if report_fast_strategy_ids and report_fast_strategy_ids != {fast_strategy_id}:
        raise Phase4DError("PHASE4D_FAST_REPORT_MONITOR_STRATEGY_MISMATCH")
    fast_row = fast_rows[0]
    historical_alignment_replay = strategy.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
    gate_status = fast_row.get("promotion_gate_status")
    effective_signal_date = fast_row.get("effective_signal_date")
    if gate_status is not None and gate_status not in {
        "INACTIVE_PENDING_USER_APPROVAL", "SCHEDULED_INACTIVE", "ACTIVE"
    }:
        raise Phase4DError("PHASE4D_FAST_PROMOTION_GATE_STATUS_INVALID")
    if historical_alignment_replay:
        replay_digest = strategy.get("strategy_replay_digest")
        replay_scope = strategy.get("strategy_replay_scope")
        if (
            fast_strategy_id != PROMOTED_STRATEGY_ID
            or not isinstance(replay_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", replay_digest)
            or not isinstance(replay_scope, dict)
            or fast_row.get("strategy_replay_mode") != "FULL_HISTORY_ALIGNMENT_WEB"
            or fast_row.get("strategy_replay_digest") != replay_digest
            or fast_row.get("strategy_replay_scope") != replay_scope
            or replay_scope.get("report_count") != len(common_tickers)
            or replay_scope.get("requested_as_of") != target_as_of
            or replay_scope.get("reference_market_date") != reference_market_date
            or replay_scope.get("output_strategy_id") != PROMOTED_STRATEGY_ID
            or gate_status is not None
            or effective_signal_date is not None
            or fast_row.get("activation_intervals") is not None
        ):
            raise Phase4DError("PHASE4D_FAST_FULL_HISTORY_REPLAY_PROVENANCE_INVALID")
    elif fast_strategy_id == PROMOTED_STRATEGY_ID and gate_status != "ACTIVE":
        raise Phase4DError("PHASE4D_FAST_PROMOTED_ID_NOT_ACTIVE")
    if gate_status == "ACTIVE" and (
        fast_strategy_id != PROMOTED_STRATEGY_ID
        or not isinstance(effective_signal_date, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_signal_date)
    ):
        raise Phase4DError("PHASE4D_FAST_ACTIVE_GATE_DATE_INVALID")
    if gate_status == "ACTIVE":
        try:
            active_date_valid = date.fromisoformat(effective_signal_date).isoformat() == effective_signal_date
        except ValueError:
            active_date_valid = False
        if not active_date_valid:
            raise Phase4DError("PHASE4D_FAST_ACTIVE_GATE_DATE_INVALID")
    if gate_status == "INACTIVE_PENDING_USER_APPROVAL" and effective_signal_date not in {
        None, "PENDING_USER_APPROVAL"
    }:
        raise Phase4DError("PHASE4D_FAST_PENDING_GATE_DATE_MISMATCH")
    if gate_status == "SCHEDULED_INACTIVE":
        try:
            scheduled_date_valid = re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(effective_signal_date)) is not None
            if scheduled_date_valid:
                scheduled_date_valid = date.fromisoformat(str(effective_signal_date)).isoformat() == effective_signal_date
        except ValueError:
            scheduled_date_valid = False
        if fast_strategy_id != STRATEGY_ID or not scheduled_date_valid:
            raise Phase4DError("PHASE4D_FAST_SCHEDULED_GATE_DATE_INVALID")
    if strategy.get("requested_as_of") != target_as_of or strategy.get("reference_market_date") != reference_market_date:
        raise Phase4DError("PHASE4D_STRATEGY_MONITOR_DATE_MISMATCH")
    if not isinstance(strategy_rows, list) or [row.get("id") for row in strategy_rows] != [fast_strategy_id, B_SELECT_ID, JULIA_ID]:
        raise Phase4DError("PHASE4D_STRATEGY_SET_INVALID")
    strategy_by_id = {row["id"]: row for row in strategy_rows}
    fast_replay_projection: dict[str, int] | None = None
    if historical_alignment_replay:
        try:
            from scripts.run_daily_update_phase4c_v01 import validate_fast_full_history_projection

            fast_replay_projection = validate_fast_full_history_projection(stocks, strategy, fast_strategy_id)
        except Exception as exc:  # noqa: BLE001 -- staging must fail closed on parity errors
            raise Phase4DError(f"PHASE4D_FAST_FULL_HISTORY_SOURCE_MONITOR_PARITY_INVALID: {exc}") from exc
    expected_strategy_scopes = {
        fast_strategy_id: ("COMMON", common_tickers),
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
        or b_status.get("permanent_identity_exclusion_count") != expected_permanent_identity_exclusion_count
        or (b_status.get("source_authorities") or {}).get("signal_cadence") != "MONTH_END_ENTRY_DAILY_NORMAL_EXIT"
        or b_status.get("scope", {}).get("type") != "PUBLISHED_COMMON_REPORTS"
        or b_status.get("count") != len(common_tickers)
        or len(b_status.get("items", [])) != len(common_tickers)
        or {str(item.get("ticker", "")).zfill(6) for item in b_status.get("items", [])} != common_tickers
        or not _b_select_monitor_items_match_status(b_items, b_status.get("items"))
        or strategy_by_id[B_SELECT_ID].get("counts") != b_status.get("counts")
    ):
        raise Phase4DError("PHASE4D_B_SELECT_STATUS_INVALID")
    if strategy_by_id[B_SELECT_ID].get("label") != "B Select Core V2":
        raise Phase4DError("PHASE4D_B_SELECT_LABEL_INVALID")
    calendar = load_rolling_production_market_calendar(ROOT)
    trading_dates = {day.strftime("%Y-%m-%d") for day in calendar.trading_dates}
    from trend_scanner.strategies.b_select_core_v2 import exact_month_end_sessions, next_exact_session

    month_end_dates = set(exact_month_end_sessions(sorted(trading_dates)))
    item_history_rows: list[dict[str, Any]] = []
    v1_source_rows = 0
    excluded_entry_rows = 0
    exact_session_violations = 0
    non_normal_exits = 0
    month_internal_entries = 0
    for item in b_status.get("items", []):
        history = item.get("trade_history")
        if not isinstance(history, list):
            raise Phase4DError(f"PHASE4D_B_SELECT_HISTORY_INVALID:{item.get('ticker')}")
        for trade in history:
            if not isinstance(trade, dict):
                raise Phase4DError(f"PHASE4D_B_SELECT_HISTORY_ROW_INVALID:{item.get('ticker')}")
            if trade.get("strategy_id") != B_SELECT_ID:
                raise Phase4DError(f"PHASE4D_B_SELECT_NON_V2_HISTORY:{item.get('ticker')}")
            item_history_rows.append({
                **trade,
                "ticker": str(item.get("ticker", "")).zfill(6),
                "isu_cd": str(item.get("isu_cd", "")).upper(),
            })
        if item.get("permanent_identity_excluded") is True and history:
            excluded_entry_rows += 0
    canonical_history_available = isinstance(b_status.get("canonical_trade_history"), list)
    history_rows = b_status.get("canonical_trade_history")
    if not canonical_history_available:
        history_rows = item_history_rows
    if not isinstance(history_rows, list):
        raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_HISTORY_INVALID")
    canonical_trade_keys: set[tuple[str, str, int, str, str]] = set()
    canonical_trade_by_key: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
    for trade in history_rows:
        if not isinstance(trade, dict):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_HISTORY_ROW_INVALID")
        try:
            canonical_key = (
                str(trade.get("ticker", "")).zfill(6),
                str(trade.get("isu_cd", "")).upper(),
                int(trade.get("trade_sequence")),
                str(trade.get("entry_signal_date") or "")[:10],
                str(trade.get("entry_execution_date") or "")[:10],
            )
        except (TypeError, ValueError) as exc:
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_HISTORY_KEY_INVALID") from exc
        if (
            not canonical_key[0].isdigit() or len(canonical_key[0]) != 6
            or not canonical_key[1] or canonical_key[2] < 1
            or not canonical_key[3] or not canonical_key[4]
            or canonical_key in canonical_trade_keys
        ):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_HISTORY_KEY_INVALID")
        canonical_trade_keys.add(canonical_key)
        canonical_trade_by_key[canonical_key] = trade
        if trade.get("strategy_id") != B_SELECT_ID or trade.get("exit_strategy_id") not in {None, B_SELECT_ID}:
            if trade.get("strategy_id") == "PATTERN_B_SELECT_CORE_V01":
                v1_source_rows += 1
            raise Phase4DError("PHASE4D_B_SELECT_NON_V2_HISTORY")
        identity_pair = (str(trade.get("ticker", "")).zfill(6), str(trade.get("isu_cd", "")).upper())
        if identity_pair in PERMANENT_IDENTITY_EXCLUSIONS:
            excluded_entry_rows += 1
        signal_date = str(trade.get("entry_signal_date") or "")[:10]
        execution_date = str(trade.get("entry_execution_date") or "")[:10]
        if signal_date not in month_end_dates:
            month_internal_entries += 1
        if signal_date not in trading_dates or execution_date not in trading_dates:
            exact_session_violations += 1
        exit_signal = str(trade.get("exit_signal_date") or "")[:10]
        exit_execution = str(trade.get("exit_execution_date") or "")[:10]
        if trade.get("trade_status") == "REALIZED":
            if trade.get("exit_reason") != "PATTERN_B_NORMAL_NEXT_OPEN" or trade.get("exit_strategy_id") != B_SELECT_ID:
                non_normal_exits += 1
            if exit_signal not in trading_dates or exit_execution not in trading_dates:
                exact_session_violations += 1
    monitor_history = strategy_by_id[B_SELECT_ID].get("trade_history")
    def _history_signature(row: dict[str, Any], *, monitor_row: bool) -> tuple[Any, ...]:
        price_key = "entry_price" if monitor_row else "entry_open"
        return (
            str(row.get("ticker", "")).zfill(6),
            str(row.get("isu_cd", "")).upper(),
            int(row.get("trade_sequence") or 0),
            str(row.get("entry_signal_date") or "")[:10],
            str(row.get("entry_execution_date") or "")[:10],
            round(float(row.get(price_key) or 0), 10),
            str(row.get("exit_signal_date") or "")[:10],
            str(row.get("exit_execution_date") or "")[:10],
            round(float(row.get("exit_price") or 0), 10),
            str(row.get("trade_status") or ""),
            str(row.get("strategy_id") or ""),
            str(row.get("exit_strategy_id") or ""),
            str(row.get("exit_reason") or ""),
        )
    if target_as_of == "2026-10-03" and not canonical_history_available:
        raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_HISTORY_MISSING")
    if target_as_of == "2026-10-03":
        canonical_open_rows = b_status.get("canonical_current_open_positions")
        monitor_open_rows = strategy_by_id[B_SELECT_ID].get("canonical_current_open_positions")
        expected_open_rows = [
            trade for trade in history_rows
            if isinstance(trade, dict) and trade.get("trade_status") == "OPEN_AT_REFERENCE"
        ]
        if (
            not isinstance(canonical_open_rows, list)
            or not isinstance(monitor_open_rows, list)
            or b_status.get("canonical_current_open_position_count") != len(expected_open_rows)
            or strategy_by_id[B_SELECT_ID].get("canonical_current_open_position_count") != len(expected_open_rows)
            or sorted(_history_signature(row, monitor_row=False) for row in canonical_open_rows)
            != sorted(_history_signature(row, monitor_row=False) for row in expected_open_rows)
            or sorted(_history_signature(row, monitor_row=True) for row in monitor_open_rows)
            != sorted(_history_signature(row, monitor_row=False) for row in expected_open_rows)
        ):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_OPEN_POSITION_MISMATCH")
    elif canonical_history_available:
        canonical_open_rows = b_status.get("canonical_current_open_positions")
        monitor_open_rows = strategy_by_id[B_SELECT_ID].get("canonical_current_open_positions")
        expected_open_rows = [
            trade for trade in history_rows
            if isinstance(trade, dict) and trade.get("trade_status") == "OPEN_AT_REFERENCE"
        ]
        if (
            not isinstance(canonical_open_rows, list)
            or not isinstance(monitor_open_rows, list)
            or b_status.get("canonical_current_open_position_count") != len(expected_open_rows)
            or strategy_by_id[B_SELECT_ID].get("canonical_current_open_position_count") != len(expected_open_rows)
            or sorted(_history_signature(row, monitor_row=False) for row in canonical_open_rows)
            != sorted(_history_signature(row, monitor_row=False) for row in expected_open_rows)
            or sorted(_history_signature(row, monitor_row=True) for row in monitor_open_rows)
            != sorted(_history_signature(row, monitor_row=False) for row in expected_open_rows)
        ):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_OPEN_POSITION_MISMATCH")
    if canonical_history_available and (
        not isinstance(monitor_history, list)
        or sorted(_history_signature(row, monitor_row=False) for row in history_rows)
        != sorted(_history_signature(row, monitor_row=True) for row in monitor_history)
        or b_status.get("canonical_trade_history_row_count", len(history_rows)) != len(history_rows)
    ):
        raise Phase4DError("PHASE4D_B_SELECT_MONITOR_CANONICAL_HISTORY_MISMATCH")
    if canonical_history_available:
        public_identity_pairs = {
            (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
            for item in b_status.get("items", [])
        }
        historical_identity_pairs = {
            (key[0], key[1]) for key in canonical_trade_keys
            if (key[0], key[1]) not in public_identity_pairs
        }
        if b_status.get("historical_only_identity_count") != len(historical_identity_pairs):
            raise Phase4DError("PHASE4D_B_SELECT_HISTORICAL_ONLY_IDENTITY_COUNT_MISMATCH")

        canonical_audit = b_status.get("canonical_history") or {}
        if canonical_audit.get("status") == "INCREMENTAL_CONTINUITY":
            catchup_audit = b_status.get("catchup_audit") or {}
            prior_artifact = str(catchup_audit.get("prior_artifact_path") or "")
            prior_path = (ROOT / prior_artifact).resolve()
            if not prior_artifact or ROOT.resolve() not in prior_path.parents or not prior_path.is_file():
                raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_ARTIFACT_INVALID")
            prior_status = _read_json(prior_path)
            prior_rows = prior_status.get("canonical_trade_history")
            if (
                not isinstance(prior_rows, list)
                or prior_status.get("canonical_trade_history_row_count") != len(prior_rows)
                or str(prior_status.get("reference_market_date") or "")[:10]
                != str(catchup_audit.get("prior_reference_market_date") or "")[:10]
            ):
                raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_HISTORY_INVALID")
            prior_by_key: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
            for prior_trade in prior_rows:
                if not isinstance(prior_trade, dict):
                    raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_HISTORY_INVALID")
                try:
                    prior_key = (
                        str(prior_trade.get("ticker", "")).zfill(6),
                        str(prior_trade.get("isu_cd", "")).upper(),
                        int(prior_trade.get("trade_sequence")),
                        str(prior_trade.get("entry_signal_date") or "")[:10],
                        str(prior_trade.get("entry_execution_date") or "")[:10],
                    )
                except (TypeError, ValueError) as exc:
                    raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_HISTORY_KEY_INVALID") from exc
                if prior_key in prior_by_key:
                    raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_HISTORY_DUPLICATE")
                prior_by_key[prior_key] = prior_trade
            if not set(prior_by_key).issubset(canonical_trade_keys):
                raise Phase4DError("PHASE4D_B_SELECT_PRIOR_CANONICAL_TRADE_KEY_LOST")
            for prior_key, prior_trade in prior_by_key.items():
                current_trade = canonical_trade_by_key[prior_key]
                if prior_trade.get("trade_status") == "REALIZED":
                    if current_trade != prior_trade:
                        raise Phase4DError("PHASE4D_B_SELECT_PRIOR_REALIZED_TRADE_CHANGED")
                    continue
                if prior_trade.get("trade_status") != "OPEN_AT_REFERENCE":
                    raise Phase4DError("PHASE4D_B_SELECT_PRIOR_TRADE_STATUS_INVALID")
                if current_trade.get("trade_status") not in {"OPEN_AT_REFERENCE", "REALIZED"}:
                    raise Phase4DError("PHASE4D_B_SELECT_PRIOR_OPEN_TRADE_DROPPED")
                for field in ("ticker", "isu_cd", "trade_sequence", "entry_signal_date", "entry_execution_date", "entry_open", "strategy_id"):
                    if current_trade.get(field) != prior_trade.get(field):
                        raise Phase4DError("PHASE4D_B_SELECT_PRIOR_OPEN_ENTRY_CHANGED")
                if current_trade.get("trade_status") == "REALIZED":
                    signal_day = str(current_trade.get("exit_signal_date") or "")[:10]
                    execution_day = str(current_trade.get("exit_execution_date") or "")[:10]
                    if (
                        current_trade.get("exit_reason") != "PATTERN_B_NORMAL_NEXT_OPEN"
                        or current_trade.get("exit_strategy_id") != B_SELECT_ID
                        or signal_day not in trading_dates
                        or execution_day not in trading_dates
                        or execution_day != next_exact_session(signal_day, sorted(trading_dates))
                        or execution_day > reference_market_date
                    ):
                        raise Phase4DError("PHASE4D_B_SELECT_PRIOR_OPEN_ILLEGAL_EXIT")

            catchup_dates = catchup_audit.get("catchup_session_dates")
            hidden_replays = canonical_audit.get("historical_only_open_replay")
            if not isinstance(catchup_dates, list) or not isinstance(hidden_replays, list):
                raise Phase4DError("PHASE4D_B_SELECT_HIDDEN_OPEN_REPLAY_AUDIT_INVALID")
            expected_hidden_open_keys = {
                (key[0], key[1], key[2])
                for key, trade in prior_by_key.items()
                if trade.get("trade_status") == "OPEN_AT_REFERENCE"
                and (key[0], key[1]) not in public_identity_pairs
            }
            actual_hidden_open_keys = {
                (
                    str(row.get("ticker", "")).zfill(6),
                    str(row.get("isu_cd", "")).upper(),
                    int(row.get("trade_sequence") or 0),
                )
                for row in hidden_replays
                if isinstance(row, dict)
            }
            if (
                len(hidden_replays) != len(actual_hidden_open_keys)
                or actual_hidden_open_keys != expected_hidden_open_keys
                or canonical_audit.get("lost_prior_trade_key_count") != 0
            ):
                raise Phase4DError("PHASE4D_B_SELECT_HIDDEN_OPEN_REPLAY_AUDIT_INVALID")
            for replay in hidden_replays:
                observations = replay.get("observations")
                if (
                    not isinstance(observations, list)
                    or [str(row.get("date") or "")[:10] for row in observations]
                    != [str(day)[:10] for day in catchup_dates]
                    or any(not row.get("pattern_b_state") for row in observations)
                ):
                    raise Phase4DError("PHASE4D_B_SELECT_HIDDEN_OPEN_OBSERVATIONS_INVALID")
                state_by_date = {
                    str(row.get("date") or "")[:10]: row.get("pattern_b_state")
                    for row in observations
                }
                signal_dates = replay.get("exit_signal_dates")
                if not isinstance(signal_dates, list) or any(
                    state_by_date.get(str(day)[:10]) != "NORMAL" for day in signal_dates
                ):
                    raise Phase4DError("PHASE4D_B_SELECT_HIDDEN_OPEN_EXIT_SIGNAL_INVALID")
                matching = [
                    row for row in history_rows
                    if str(row.get("ticker", "")).zfill(6) == str(replay.get("ticker", "")).zfill(6)
                    and str(row.get("isu_cd", "")).upper() == str(replay.get("isu_cd", "")).upper()
                    and int(row.get("trade_sequence") or 0) == int(replay.get("trade_sequence") or 0)
                ]
                if len(matching) != 1 or matching[0].get("trade_status") != replay.get("result_trade_status"):
                    raise Phase4DError("PHASE4D_B_SELECT_HIDDEN_OPEN_RESULT_MISMATCH")

        pending_rows = b_status.get("canonical_pending_events")
        monitor_pending_rows = strategy_by_id[B_SELECT_ID].get("canonical_pending_events")
        if (
            not isinstance(pending_rows, list)
            or not isinstance(monitor_pending_rows, list)
            or b_status.get("canonical_pending_event_count", len(pending_rows)) != len(pending_rows)
            or strategy_by_id[B_SELECT_ID].get("canonical_pending_event_count", len(monitor_pending_rows))
            != len(monitor_pending_rows)
        ):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_PENDING_EVENTS_INVALID")

        def _pending_signature(row: dict[str, Any]) -> tuple[Any, ...]:
            return (
                str(row.get("ticker", "")).zfill(6),
                str(row.get("isu_cd", "")).upper(),
                int(row.get("trade_sequence") or 0),
                str(row.get("kind") or ""),
                str(row.get("signal_date") or "")[:10],
                str(row.get("execution_date") or "")[:10],
                str(row.get("strategy_id") or ""),
            )

        try:
            pending_signatures = [_pending_signature(row) for row in pending_rows]
            monitor_pending_signatures = [_pending_signature(row) for row in monitor_pending_rows]
        except (AttributeError, TypeError, ValueError) as exc:
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_PENDING_EVENTS_INVALID") from exc
        if (
            len(pending_signatures) != len(set(pending_signatures))
            or sorted(pending_signatures) != sorted(monitor_pending_signatures)
        ):
            raise Phase4DError("PHASE4D_B_SELECT_MONITOR_CANONICAL_PENDING_EVENTS_MISMATCH")
        item_pending_signatures = []
        for item in b_status.get("items", []):
            event = item.get("pending_event")
            if not isinstance(event, dict):
                continue
            current_trade = item.get("current_trade")
            item_pending_signatures.append((
                str(item.get("ticker", "")).zfill(6),
                str(item.get("isu_cd", "")).upper(),
                int((current_trade or {}).get("trade_sequence") or 0)
                if isinstance(current_trade, dict) else 0,
                str(event.get("kind") or ""),
                str(event.get("signal_date") or "")[:10],
                str(event.get("execution_date") or "")[:10],
                str(event.get("strategy_id") or B_SELECT_ID),
            ))
        if not set(item_pending_signatures).issubset(set(pending_signatures)):
            raise Phase4DError("PHASE4D_B_SELECT_ITEM_PENDING_EVENT_NOT_CANONICAL")
    if (
        v1_source_rows != 0
        or b_status.get("current_v1_source_row_count") != 0
        or excluded_entry_rows != 0
        or exact_session_violations != 0
        or non_normal_exits != 0
        or month_internal_entries != 0
    ):
        raise Phase4DError(
            "PHASE4D_B_SELECT_CANONICAL_LEDGER_INVALID:"
            f"v1={v1_source_rows},excluded={excluded_entry_rows},exact={exact_session_violations},"
            f"non_normal={non_normal_exits},midmonth_entry={month_internal_entries}"
        )
    if target_as_of == "2026-10-03":
        canonical = b_status.get("canonical_history") or {}
        if (
            reference_market_date != "2026-10-02"
            or canonical.get("status") != "FRESH_REPLAY"
            or canonical.get("end_date") != reference_market_date
            or canonical.get("current_v1_source_row_count") != 0
            or b_status.get("catchup_audit", {}).get("replay_mode") != "V2_CANONICAL_FULL_HISTORY_REPLAY"
            or canonical.get("trade_history_row_count") != len(history_rows)
        ):
            raise Phase4DError("PHASE4D_B_SELECT_CANONICAL_REPLAY_AUDIT_INVALID")
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
        fast = strategy_by_id[fast_strategy_id]
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
        "b_select_canonical_trade_history_row_count": b_status.get("canonical_trade_history_row_count"),
        "fast_replay_projection": fast_replay_projection,
        "b_select_canonical_current_open_position_count": b_status.get("canonical_current_open_position_count"),
        "b_select_published_item_open_position_count": sum(
            item.get("canonical_position") == "OPEN" for item in b_status.get("items", [])
        ),
        "b_select_historical_only_open_position_count": sum(
            (str(trade.get("ticker", "")).zfill(6), str(trade.get("isu_cd", "")).upper())
            not in {
                (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
                for item in b_status.get("items", [])
            }
            for trade in b_status.get("canonical_current_open_positions", [])
            if isinstance(trade, dict)
        ),
        "b_select_evaluation_error_count": b_status.get("evaluation_error_count"),
        "b_select_date_mismatch_count": b_status.get("date_mismatch_count"),
        "b_select_future_reference_count": b_status.get("future_reference_count"),
        "b_select_duplicate_item_count": b_status.get("duplicate_item_count"),
        "b_select_cross_strategy_contamination_count": b_status.get("cross_strategy_contamination_count"),
        "b_select_network_requests": b_status.get("network_requests"),
        "identity_route_integrity": identity_route_validation,
    }


def _phase4d_checkpoint(_name: str) -> None:
    """Fault-injection seam; production execution intentionally does nothing."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_dir():
        raise Phase4DError(f"PHASE4D_PUBLISH_PATH_NOT_DIRECTORY: {path}")
    directories = sorted(
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_dir()
    )
    files = {
        item.relative_to(path).as_posix(): _sha256_file(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }
    return {"directories": directories, "files": files}


def _build_promotion_snapshot(stage_data: Path, web_data: Path, new_snapshot: Path) -> None:
    """Apply the same complete-directory and stocks-only replacement used by promote()."""
    if web_data.exists():
        shutil.copytree(web_data, new_snapshot)
    else:
        new_snapshot.mkdir(parents=True)
    staged_stocks = stage_data / "stocks"
    new_stocks = new_snapshot / "stocks"
    _remove_path(new_stocks)
    shutil.copytree(staged_stocks, new_stocks)
    for name in REQUIRED_FILES:
        temporary = new_snapshot / f".{name}.{uuid.uuid4().hex}.tmp"
        _phase4d_checkpoint(f"before_json_replace:{name}")
        shutil.copy2(stage_data / name, temporary)
        os.replace(temporary, new_snapshot / name)
        _phase4d_checkpoint(f"after_json_replace:{name}")

    staged_routes_path = stage_data / "identity-report-routes.json"
    if staged_routes_path.is_file():
        routes = _read_json(staged_routes_path)
        for item in routes.get("items", []):
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_ITEM_INVALID")
            url = item["url"]
            if not url.startswith("./data/identity-reports/"):
                continue
            relative = PurePosixPath(url[len("./data/"):])
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_URL_INVALID")
            source = stage_data.joinpath(*relative.parts)
            if source.is_file():
                target = new_snapshot.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
        temporary = new_snapshot / f".identity-report-routes.json.{uuid.uuid4().hex}.tmp"
        shutil.copy2(staged_routes_path, temporary)
        os.replace(temporary, new_snapshot / "identity-report-routes.json")


def _validate_promoted_snapshot(
    web_data: Path,
    new_snapshot: Path,
    *,
    stage_data: Path | None = None,
) -> dict[str, Any]:
    """Verify exact preservation of non-stock sidecars and every identity route."""
    route_publish_allowlist: set[str] = set()
    if stage_data is not None:
        staged_routes_path = stage_data / "identity-report-routes.json"
        if staged_routes_path.is_file():
            route_publish_allowlist.add("identity-report-routes.json")
            staged_routes = _read_json(staged_routes_path)
            for item in staged_routes.get("items", []):
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_ITEM_INVALID")
                url = item["url"]
                if not url.startswith("./data/identity-reports/"):
                    continue
                relative = PurePosixPath(url[len("./data/"):])
                if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                    raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_URL_INVALID")
                if stage_data.joinpath(*relative.parts).is_file():
                    route_publish_allowlist.add(relative.as_posix())
    protected_before = {
        path.relative_to(web_data).as_posix(): _sha256_file(path)
        for path in sorted(web_data.rglob("*"))
        if path.is_file()
        and path.relative_to(web_data).parts[0] != "stocks"
        and path.relative_to(web_data).as_posix() not in REQUIRED_FILES
        and path.relative_to(web_data).as_posix() not in route_publish_allowlist
    } if web_data.is_dir() else {}
    protected_after = {
        path.relative_to(new_snapshot).as_posix(): _sha256_file(path)
        for path in sorted(new_snapshot.rglob("*"))
        if path.is_file()
        and path.relative_to(new_snapshot).parts[0] != "stocks"
        and path.relative_to(new_snapshot).as_posix() not in REQUIRED_FILES
        and path.relative_to(new_snapshot).as_posix() not in route_publish_allowlist
    }
    if protected_before != protected_after:
        missing = sorted(set(protected_before) - set(protected_after))
        added = sorted(set(protected_after) - set(protected_before))
        changed = sorted(
            path for path in set(protected_before) & set(protected_after)
            if protected_before[path] != protected_after[path]
        )
        raise Phase4DError(
            "PHASE4D_PROMOTION_PROTECTED_WEB_FILES_MISMATCH: "
            f"missing={len(missing)} added={len(added)} changed={len(changed)}"
        )

    route_path = new_snapshot / "identity-report-routes.json"
    route_result: dict[str, Any] = {
        "status": "NOT_PRESENT",
        "route_count": 0,
        "referenced_file_count": 0,
        "missing_route_count": 0,
        "routes": [],
    }
    if route_path.is_file():
        routes = _read_json(route_path)
        items = routes.get("items")
        if not isinstance(items, list):
            raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTES_INVALID")
        resolved_routes: list[dict[str, str]] = []
        missing: list[str] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_ITEM_INVALID")
            url = item["url"]
            prefix = "./data/"
            if not url.startswith(prefix):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_URL_INVALID")
            relative = PurePosixPath(url[len(prefix):])
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_URL_INVALID")
            target = new_snapshot.joinpath(*relative.parts)
            if not _path_is_within(target, new_snapshot):
                raise Phase4DError("PHASE4D_PROMOTION_IDENTITY_ROUTE_URL_INVALID")
            if not target.is_file():
                missing.append(url)
            resolved_routes.append({"url": url, "path": relative.as_posix()})
        if missing:
            raise Phase4DError(
                f"PHASE4D_PROMOTION_IDENTITY_ROUTE_TARGET_MISSING: count={len(missing)}"
            )
        route_result = {
            "status": "PASS",
            "route_count": len(items),
            "referenced_file_count": len({item["path"] for item in resolved_routes}),
            "missing_route_count": 0,
            "routes": resolved_routes,
        }
        if stage_data is not None and (stage_data / "identity-report-routes.json").is_file():
            status_path = stage_data / B_SELECT_STATUS_STAGING_NAME
            if status_path.is_file():
                expected_status = _read_json(status_path)
                if isinstance(expected_status.get("canonical_trade_history"), list):
                    try:
                        full_integrity = identity_reports_web.validate_identity_routes(new_snapshot, expected_status)
                    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                        raise Phase4DError(f"PHASE4D_PROMOTION_IDENTITY_ROUTE_INTEGRITY_FAILED: {exc}") from exc
                    route_result.update(full_integrity)
                    route_result["referenced_file_count"] = len({item["path"] for item in resolved_routes})
                    route_result["routes"] = resolved_routes
    return {
        "status": "PASS",
        "protected_file_count": len(protected_before),
        "protected_files": protected_before,
        "missing_protected_file_count": 0,
        "changed_protected_file_count": 0,
        "route_integrity": route_result,
    }


def _inspect_final_promotion_snapshot(stage_data: Path, web_data: Path) -> dict[str, Any]:
    """Preflight the exact final tree without touching the published web/data."""
    preflight_root = web_data.parent / f".phase4d-preflight-{uuid.uuid4().hex}"
    preflight_root.mkdir()
    try:
        snapshot = preflight_root / "new-web-data"
        _build_promotion_snapshot(stage_data, web_data, snapshot)
        return _validate_promoted_snapshot(web_data, snapshot, stage_data=stage_data)
    finally:
        shutil.rmtree(preflight_root, ignore_errors=True)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _relative_to_root(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Phase4DError(f"PHASE4D_TRANSACTION_PATH_OUTSIDE_ROOT: {path}") from exc


def _transaction_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise Phase4DError(f"PHASE4D_TRANSACTION_PATH_INVALID:{field}")
    path = (root / value).resolve()
    if not _path_is_within(path, root):
        raise Phase4DError(f"PHASE4D_TRANSACTION_PATH_OUTSIDE_ROOT:{field}")
    return path


def _write_transaction_journal(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _read_transaction_journal(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase4DError(f"PHASE4D_TRANSACTION_JOURNAL_INVALID:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "phase4d_publish_transaction_v02":
        raise Phase4DError(f"PHASE4D_TRANSACTION_JOURNAL_SCHEMA_INVALID:{path}")
    return payload


def _status_digest(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _restore_web_data(
    web_data: Path,
    backup_web_data: Path,
    expected_manifest: dict[str, Any] | None,
    restore_temporary: Path,
) -> None:
    current_manifest = _tree_manifest(web_data)
    if current_manifest == expected_manifest:
        return
    if expected_manifest is None:
        _remove_path(web_data)
        return
    if _tree_manifest(backup_web_data) != expected_manifest:
        raise Phase4DError(f"PHASE4D_RECOVERY_WEB_DATA_BACKUP_MISSING_OR_CORRUPT: {backup_web_data}")
    _remove_path(restore_temporary)
    shutil.copytree(backup_web_data, restore_temporary)
    if _tree_manifest(restore_temporary) != expected_manifest:
        raise Phase4DError(f"PHASE4D_RECOVERY_WEB_DATA_COPY_MISMATCH: {restore_temporary}")
    _remove_path(web_data)
    os.replace(restore_temporary, web_data)
    if _tree_manifest(web_data) != expected_manifest:
        raise Phase4DError(f"PHASE4D_RECOVERY_WEB_DATA_READBACK_MISMATCH: {web_data}")


def _restore_status(
    status_destination: Path,
    backup_status: Path,
    expected_digest: str | None,
    temporary: Path,
) -> None:
    if _status_digest(status_destination) == expected_digest:
        return
    if expected_digest is None:
        status_destination.unlink(missing_ok=True)
        return
    if _status_digest(backup_status) != expected_digest:
        raise Phase4DError(f"PHASE4D_RECOVERY_STATUS_BACKUP_MISSING_OR_CORRUPT: {backup_status}")
    status_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_status, temporary)
    if _status_digest(temporary) != expected_digest:
        raise Phase4DError(f"PHASE4D_RECOVERY_STATUS_COPY_MISMATCH: {temporary}")
    os.replace(temporary, status_destination)
    if _status_digest(status_destination) != expected_digest:
        raise Phase4DError(f"PHASE4D_RECOVERY_STATUS_READBACK_MISMATCH: {status_destination}")


def _recover_pending_promotion(web_data: Path) -> dict[str, Any]:
    root = web_data.parent.parent.resolve()
    journal_path = web_data.parent / PHASE4D_PUBLISH_JOURNAL
    if not journal_path.is_file():
        orphan_transactions = sorted(web_data.parent.glob(".phase4d-publish-txn-*"))
        if orphan_transactions:
            exposed_backups = [
                path for path in orphan_transactions
                if (path / "previous-web-data").exists()
                or (path / "previous-b-select-status.json").exists()
            ]
            if exposed_backups:
                raise Phase4DError(
                    "PHASE4D_ORPHAN_TRANSACTION_BACKUP_REQUIRES_REVIEW: "
                    + ", ".join(str(path) for path in exposed_backups)
                )
            for path in orphan_transactions:
                shutil.rmtree(path, ignore_errors=False)
            return {"status": "UNPUBLISHED_STAGING_CLEANED"}
        return {"status": "NO_PENDING_TRANSACTION"}

    journal = _read_transaction_journal(journal_path)
    tx_dir = _transaction_path(root, journal.get("transaction_dir"), "transaction_dir")
    backup_web_data = _transaction_path(root, journal.get("backup_web_data"), "backup_web_data")
    restore_web_data = _transaction_path(root, journal.get("restore_web_data"), "restore_web_data")
    backup_status = _transaction_path(root, journal.get("backup_status"), "backup_status")
    status_destination = _transaction_path(root, journal.get("status_destination"), "status_destination")
    restore_status = _transaction_path(root, journal.get("restore_status"), "restore_status")
    status_temporary = _transaction_path(root, journal.get("status_temporary"), "status_temporary")
    old_manifest = journal.get("old_web_data_manifest")
    old_status_digest = journal.get("old_status_sha256")

    if journal.get("phase") == "COMMITTED":
        if (
            _tree_manifest(web_data) != journal.get("new_web_data_manifest")
            or _status_digest(status_destination) != journal.get("new_status_sha256")
        ):
            raise Phase4DError(
                f"PHASE4D_COMMITTED_SNAPSHOT_MISMATCH_BACKUPS_PRESERVED: {tx_dir}"
            )
        if tx_dir.exists():
            shutil.rmtree(tx_dir, ignore_errors=True)
        if tx_dir.exists():
            raise Phase4DError(f"PHASE4D_COMMITTED_BACKUP_CLEANUP_CHECK_REQUIRED: {tx_dir}")
        journal_path.unlink(missing_ok=True)
        return {"status": "COMMITTED_TRANSACTION_FINALIZED", "transaction_id": journal.get("transaction_id")}

    try:
        _restore_web_data(web_data, backup_web_data, old_manifest, restore_web_data)
        _restore_status(status_destination, backup_status, old_status_digest, restore_status)
        if (
            _tree_manifest(web_data) != old_manifest
            or _status_digest(status_destination) != old_status_digest
        ):
            raise Phase4DError("PHASE4D_RECOVERY_OLD_SNAPSHOT_READBACK_MISMATCH")
        status_temporary.unlink(missing_ok=True)
    except Exception as exc:
        raise Phase4DError(
            f"PHASE4D_RECOVERY_FAILED_BACKUPS_PRESERVED:{tx_dir}: {exc}"
        ) from exc
    if tx_dir.exists():
        shutil.rmtree(tx_dir, ignore_errors=True)
    if tx_dir.exists():
        raise Phase4DError(f"PHASE4D_RECOVERY_BACKUP_CLEANUP_FAILED_BACKUPS_PRESERVED: {tx_dir}")
    journal_path.unlink(missing_ok=True)
    return {
        "status": "OLD_SNAPSHOT_RESTORED",
        "transaction_id": journal.get("transaction_id"),
        "restored_web_data_sha256": hashlib.sha256(
            json.dumps(old_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest() if old_manifest is not None else None,
    }


V13_ALIGNMENT_CANDIDATE_DIGEST = "3993cc22f55f52b169736159637662e93ebac3c0f4edac4fe0946f2fd933733c"
V13_ALIGNMENT_PERMANENT_EXCLUSION_COUNT = 181
V13_ALIGNMENT_STAGE_RELATIVE_PATH = Path(
    "artifacts/strategies/a_fast_core_v2/research/"
    "a_fast_alignment_500b_v09_strict_baseline_approval_and_phase4d_preflight/"
    "run_20261015/phase4d_stage/web"
)


def _alignment_candidate_binding(
    stage_data: Path,
    root: Path,
    *,
    alignment_candidate_digest: str | None = None,
) -> dict[str, str] | None:
    """Recognize candidate intent independently of mutable monitor markers.

    The designated stage path is only a reason to require the gate; it is never
    evidence that the files are trusted. The V13 gate still binds every staged
    file to its pinned manifest and V05/V12 evidence before publication.
    """
    from trend_scanner.validation.a_fast_alignment_publication_gate_v13 import V05_STAGE_REL

    designated_stage_data = {
        (root / V13_ALIGNMENT_STAGE_RELATIVE_PATH).resolve(),
        (root / V05_STAGE_REL / "web").resolve(),
    }
    is_designated_stage = stage_data.resolve() in designated_stage_data
    if alignment_candidate_digest is not None and alignment_candidate_digest != V13_ALIGNMENT_CANDIDATE_DIGEST:
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_DIGEST_NOT_BOUND_TO_V13")

    monitor_path = stage_data / "strategy-monitor.json"
    monitor: dict[str, Any] = {}
    if monitor_path.is_file():
        monitor = _read_json(monitor_path)
    strategy_rows = monitor.get("strategies")
    strategy_rows = strategy_rows if isinstance(strategy_rows, list) else []
    promoted_row_present = any(
        isinstance(row, dict) and row.get("id") == PROMOTED_STRATEGY_ID
        for row in strategy_rows
    )
    marker_candidate = (
        monitor.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
        or promoted_row_present
        or monitor.get("strategy_replay_digest") == V13_ALIGNMENT_CANDIDATE_DIGEST
    )
    if not (alignment_candidate_digest is not None or is_designated_stage or marker_candidate):
        return None
    if not is_designated_stage:
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_STAGE_NOT_DESIGNATED")
    monitor_digest = monitor.get("strategy_replay_digest")
    if monitor_digest is not None and monitor_digest != V13_ALIGNMENT_CANDIDATE_DIGEST:
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_DIGEST_NOT_BOUND_TO_V13")
    return {
        "candidate_digest": V13_ALIGNMENT_CANDIDATE_DIGEST,
        "requested_as_of": "2026-10-11",
        "reference_market_date": "2026-10-08",
    }


def _validate_v13_alignment_stage(
    stage_data: Path,
    target_as_of: str,
    root: Path,
    *,
    expected_candidate_digest: str | None = None,
) -> dict[str, Any]:
    """Run both the independent evidence gate and Phase4D's ordinary validator."""
    from trend_scanner.validation.a_fast_alignment_publication_gate_v13 import (
        EXPECTED as V13_EXPECTED,
        V09_STAGE_REL,
        validate_alignment_candidate_evidence,
    )

    if root.resolve() != ROOT.resolve():
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_REPOSITORY_ROOT_MISMATCH")
    stage_root = stage_data.parent
    try:
        evidence = validate_alignment_candidate_evidence(root, stage_root)
        validation = validate_staging(
            stage_data,
            V13_EXPECTED["requested_as_of"],
            V13_EXPECTED["reference_market_date"],
            require_etf36=True,
            b_select_status_path=stage_root / B_SELECT_STATUS_STAGING_NAME,
            expected_permanent_identity_exclusion_count=V13_ALIGNMENT_PERMANENT_EXCLUSION_COUNT,
        )
    except Exception as exc:
        if isinstance(exc, Phase4DError):
            raise
        raise Phase4DError(f"PHASE4D_ALIGNMENT_ELIGIBILITY_GATE_FAILED:{exc}") from exc
    if target_as_of != V13_EXPECTED["requested_as_of"]:
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_TARGET_DATE_MISMATCH")
    candidate_digest = evidence["candidate_binding"]["candidate_digest"]
    if expected_candidate_digest is not None and candidate_digest != expected_candidate_digest:
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_DIGEST_NOT_BOUND_TO_V13")
    if stage_data.resolve() != (root / V09_STAGE_REL / "web").resolve():
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_STAGE_NOT_DESIGNATED")
    return {
        "status": "PASS",
        "candidate_digest": candidate_digest,
        "stage_fingerprint_sha256": evidence["stage_fingerprint_sha256"],
        "b_select_status_sha256": evidence["b_select_status_sha256"],
        "phase4d_staging_validation": validation,
    }


def _published_alignment_candidate_matches(
    root: Path,
    target_as_of: str,
    candidate_digest: str,
    published: dict[str, Any] | None,
) -> bool:
    """Allow candidate NOOP only after payload and exact date/scope validation."""
    if candidate_digest != V13_ALIGNMENT_CANDIDATE_DIGEST or target_as_of != "2026-10-11":
        raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_REQUEST_BINDING_INVALID")
    if not isinstance(published, dict):
        return False
    reference_market_date = published.get("reference_market_date")
    if reference_market_date != "2026-10-08":
        return False
    try:
        monitor = _read_json(root / "web/data/strategy-monitor.json")
    except (OSError, UnicodeError, ValueError, Phase4DError):
        return False
    scope = monitor.get("strategy_replay_scope")
    rows = monitor.get("strategies")
    fast_rows = [
        row for row in rows if isinstance(row, dict) and row.get("id") == PROMOTED_STRATEGY_ID
    ] if isinstance(rows, list) else []
    fast_row = fast_rows[0] if len(fast_rows) == 1 else {}
    return bool(
        monitor.get("requested_as_of") == target_as_of
        and monitor.get("reference_market_date") == reference_market_date
        and monitor.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
        and monitor.get("strategy_replay_digest") == candidate_digest
        and isinstance(scope, dict)
        and scope.get("requested_as_of") == target_as_of
        and scope.get("reference_market_date") == reference_market_date
        and scope.get("report_count") == 1459
        and scope.get("output_strategy_id") == PROMOTED_STRATEGY_ID
        and fast_row.get("strategy_replay_mode") == "FULL_HISTORY_ALIGNMENT_WEB"
        and fast_row.get("strategy_replay_digest") == candidate_digest
        and fast_row.get("strategy_replay_scope") == scope
    )


def _assert_alignment_snapshot_matches_stage(stage_data: Path, new_snapshot: Path) -> None:
    """Ensure the exact Alignment payload copied to the promotion snapshot was gated."""
    for name in REQUIRED_FILES:
        if _sha256_file(stage_data / name) != _sha256_file(new_snapshot / name):
            raise Phase4DError(f"PHASE4D_ALIGNMENT_SNAPSHOT_PAYLOAD_MISMATCH:{name}")
    if _tree_manifest(stage_data / "stocks") != _tree_manifest(new_snapshot / "stocks"):
        raise Phase4DError("PHASE4D_ALIGNMENT_SNAPSHOT_STOCKS_MISMATCH")


def _daily_alignment_stage_proof(
    stage_data: Path,
    target_as_of: str,
    reference_market_date: str,
    root: Path,
    *,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the one approved daily Alignment projection to its canonical inputs."""
    stage_data = Path(stage_data)
    root = Path(root)
    if root.resolve() != ROOT.resolve():
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_REPOSITORY_ROOT_MISMATCH")
    if (
        target_as_of != DAILY_ALIGNMENT_TARGET_AS_OF
        or reference_market_date != DAILY_ALIGNMENT_REFERENCE_MARKET_DATE
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_DATE_NOT_DESIGNATED")
    if (
        stage_data.name != "data"
        or not stage_data.parent.name.startswith(".phase4d-stage-")
        or stage_data.parent.parent.resolve() != (root / "web").resolve()
        or not _path_is_within(stage_data, root)
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_STAGE_NOT_OFFICIAL_TEMP_STAGE")

    monitor = _read_json(stage_data / "strategy-monitor.json")
    b_status_path = stage_data / B_SELECT_STATUS_STAGING_NAME
    b_status = _read_json(b_status_path)
    canonical = _canonical_full_history_alignment_provenance(
        root, target_as_of, reference_market_date,
    )
    if (
        canonical is None
        or canonical.get("valid") is not True
        or canonical.get("strategy_id") != PROMOTED_STRATEGY_ID
        or canonical.get("strategy_replay_mode") != "FULL_HISTORY_ALIGNMENT_WEB"
        or canonical.get("strategy_replay_digest") != DAILY_ALIGNMENT_REPLAY_DIGEST
        or canonical.get("computed_strategy_replay_digest") != DAILY_ALIGNMENT_REPLAY_DIGEST
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_CANONICAL_PROVENANCE_MISMATCH")
    canonical_scope = canonical.get("strategy_replay_scope")
    if (
        not isinstance(canonical_scope, dict)
        or canonical_scope.get("requested_as_of") != target_as_of
        or canonical_scope.get("reference_market_date") != reference_market_date
        or canonical_scope.get("report_count") != canonical.get("common_report_count")
        or canonical_scope.get("output_strategy_id") != PROMOTED_STRATEGY_ID
        or monitor.get("requested_as_of") != target_as_of
        or monitor.get("reference_market_date") != reference_market_date
        or monitor.get("default_strategy_id") != PROMOTED_STRATEGY_ID
        or monitor.get("strategy_replay_mode") != "FULL_HISTORY_ALIGNMENT_WEB"
        or monitor.get("strategy_replay_digest") != DAILY_ALIGNMENT_REPLAY_DIGEST
        or monitor.get("strategy_replay_scope") != canonical_scope
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_MONITOR_CANONICAL_MISMATCH")

    if phase4c_result is not None:
        phase4c_monitor = phase4c_result.get("_strategy_monitor_for_phase4d")
        phase4c_b_status = phase4c_result.get("_b_select_status_for_phase4d")
        if (
            phase4c_result.get("status") != "PASS"
            or phase4c_result.get("target_as_of") != target_as_of
            or phase4c_result.get("requested_as_of") != target_as_of
            or phase4c_result.get("reference_market_date") != reference_market_date
            or phase4c_result.get("network_calls") != 0
            or phase4c_result.get("web_data_writes") != 0
            or phase4c_monitor != monitor
            or phase4c_b_status != b_status
            or (phase4c_result.get("strategy_monitor") or {}).get("common_report_count")
            != canonical.get("common_report_count")
            or (phase4c_result.get("stock_report") or {}).get("available_report_count")
            != canonical.get("common_report_count")
        ):
            raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_PHASE4C_CANONICAL_MISMATCH")
        b_summary = phase4c_result.get("b_select_status") or {}
        if any(
            b_summary.get(key) != b_status.get(source_key)
            for key, source_key in (
                ("status", "status"),
                ("count", "count"),
                ("counts", "counts"),
                ("evaluation_error_count", "evaluation_error_count"),
                ("date_mismatch_count", "date_mismatch_count"),
                ("network_requests", "network_requests"),
            )
        ):
            raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_PHASE4C_B_STATUS_MISMATCH")

    validation = validate_staging(
        stage_data,
        target_as_of,
        reference_market_date,
        require_etf36=True,
        b_select_status_path=b_status_path,
    )
    manifest = _tree_manifest(stage_data)
    if manifest is None:
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_STAGE_MISSING")
    stage_fingerprint = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "PASS",
        "candidate_digest": DAILY_ALIGNMENT_REPLAY_DIGEST,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "strategy_replay_scope": canonical_scope,
        "stage_fingerprint_sha256": stage_fingerprint,
        "b_select_status_sha256": _sha256_file(b_status_path),
        "canonical_trade_count": b_status.get("canonical_trade_history_row_count"),
        "canonical_identity_count": len({
            (str(row.get("ticker") or "").zfill(6), str(row.get("isu_cd") or "").upper())
            for row in b_status.get("canonical_trade_history", [])
            if isinstance(row, dict)
        }),
        "route_integrity": validation.get("identity_route_integrity"),
        "validation": validation,
    }


def _create_daily_alignment_promotion_context(
    stage_data: Path,
    target_as_of: str,
    reference_market_date: str,
    root: Path,
    phase4c_result: dict[str, Any],
) -> dict[str, Any] | None:
    monitor_path = Path(stage_data) / "strategy-monitor.json"
    if not monitor_path.is_file():
        return None
    if _read_json(monitor_path).get("strategy_replay_mode") != "FULL_HISTORY_ALIGNMENT_WEB":
        return None
    proof = _daily_alignment_stage_proof(
        stage_data,
        target_as_of,
        reference_market_date,
        root,
        phase4c_result=phase4c_result,
    )
    return {
        "_authority": _DAILY_ALIGNMENT_PROMOTION_AUTHORITY,
        "stage_data": str(Path(stage_data).resolve()),
        "target_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "candidate_digest": proof["candidate_digest"],
        "stage_fingerprint_sha256": proof["stage_fingerprint_sha256"],
        "b_select_status_sha256": proof["b_select_status_sha256"],
        "proof": proof,
    }


def _validate_daily_alignment_promotion_context(
    context: dict[str, Any] | None,
    stage_data: Path,
    target_as_of: str,
    root: Path,
) -> dict[str, Any]:
    if (
        not isinstance(context, dict)
        or context.get("_authority") is not _DAILY_ALIGNMENT_PROMOTION_AUTHORITY
        or context.get("stage_data") != str(Path(stage_data).resolve())
        or context.get("target_as_of") != target_as_of
        or context.get("reference_market_date") != DAILY_ALIGNMENT_REFERENCE_MARKET_DATE
        or context.get("candidate_digest") != DAILY_ALIGNMENT_REPLAY_DIGEST
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_PROMOTION_CONTEXT_INVALID")
    proof = _daily_alignment_stage_proof(
        stage_data,
        target_as_of,
        DAILY_ALIGNMENT_REFERENCE_MARKET_DATE,
        root,
    )
    if (
        proof.get("stage_fingerprint_sha256") != context.get("stage_fingerprint_sha256")
        or proof.get("b_select_status_sha256") != context.get("b_select_status_sha256")
    ):
        raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_STAGE_CHANGED_AFTER_VALIDATION")
    return proof


def promote(
    stage_data: Path,
    web_data: Path,
    *,
    target_as_of: str,
    post_publish_validate: Callable[[Path], Any] | None = None,
    alignment_candidate_digest: str | None = None,
    _daily_alignment_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish one complete web/data directory plus B Select status with recoverable rollback.

    The web/data directory rename is atomic on its filesystem. B Select status
    lives elsewhere and is replaced in a separate operation, so the cross-path
    transaction is recoverable but not globally atomic; readers can briefly see
    a missing web/data path or mismatched status while publication is in flight.
    """
    stage_data = Path(stage_data)
    web_data = Path(web_data)
    root = web_data.parent.parent.resolve()
    if _daily_alignment_context is not None:
        if alignment_candidate_digest is not None:
            raise Phase4DError("PHASE4D_DAILY_ALIGNMENT_CANDIDATE_MODE_CONFLICT")
        alignment_binding = {
            "binding_type": "DAILY_ALIGNMENT",
            **_validate_daily_alignment_promotion_context(
                _daily_alignment_context, stage_data, target_as_of, root,
            ),
        }
    else:
        try:
            alignment_binding = _alignment_candidate_binding(
                stage_data,
                root,
                alignment_candidate_digest=alignment_candidate_digest,
            )
        except Phase4DError as binding_error:
            # A content-identified Alignment stage outside the pinned locations is
            # still a candidate attempt. Run the independent evidence gate before
            # rejecting it so direct promote() cannot bypass eligibility checks by
            # copying the payload to an unrecognized directory.
            if str(binding_error) != "PHASE4D_ALIGNMENT_CANDIDATE_STAGE_NOT_DESIGNATED":
                raise
            try:
                _validate_v13_alignment_stage(
                    stage_data,
                    target_as_of,
                    root,
                    expected_candidate_digest=V13_ALIGNMENT_CANDIDATE_DIGEST,
                )
            except Phase4DError as gate_error:
                raise gate_error from binding_error
            raise binding_error
    status_source = stage_data / B_SELECT_STATUS_STAGING_NAME
    if alignment_binding is not None and not status_source.is_file():
        status_source = stage_data.parent / B_SELECT_STATUS_STAGING_NAME
    status_destination = _b_select_status_path(root, target_as_of)
    journal_path = web_data.parent / PHASE4D_PUBLISH_JOURNAL
    lock_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]
    lock_path = Path(tempfile.gettempdir()) / f"phase4d-publish-{lock_key}.lock"

    if not (stage_data / "stocks").is_dir() or any(not (stage_data / name).is_file() for name in REQUIRED_FILES):
        raise Phase4DError("PHASE4D_PROMOTION_STAGE_INCOMPLETE")
    if not status_source.is_file():
        raise Phase4DError("PHASE4D_PROMOTION_B_SELECT_STATUS_MISSING")
    if not _path_is_within(stage_data, root) or not _path_is_within(status_destination, root):
        raise Phase4DError("PHASE4D_PROMOTION_PATH_OUTSIDE_ROOT")

    with lock_path.open("a+b") as lock_stream:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Phase4DError("PHASE4D_PUBLICATION_ALREADY_IN_PROGRESS") from exc
        try:
            alignment_preflight = None
            if alignment_binding is not None:
                if alignment_binding.get("binding_type") == "DAILY_ALIGNMENT":
                    alignment_preflight = _validate_daily_alignment_promotion_context(
                        _daily_alignment_context, stage_data, target_as_of, root,
                    )
                else:
                    alignment_preflight = _validate_v13_alignment_stage(
                        stage_data,
                        target_as_of,
                        root,
                        expected_candidate_digest=alignment_binding["candidate_digest"],
                    )
            recovery = _recover_pending_promotion(web_data)
            tx_id = uuid.uuid4().hex
            tx_dir = web_data.parent / f".phase4d-publish-txn-{tx_id}"
            tx_dir.mkdir()
            new_snapshot = tx_dir / "new-web-data"
            backup_web_data = tx_dir / "previous-web-data"
            restore_web_data = tx_dir / "restore-web-data"
            backup_status = tx_dir / "previous-b-select-status.json"
            restore_status = tx_dir / "restore-b-select-status.json"
            status_temporary = status_destination.with_name(f".{status_destination.name}.{tx_id}.tmp")
            status_destination.parent.mkdir(parents=True, exist_ok=True)

            old_manifest = _tree_manifest(web_data)
            _build_promotion_snapshot(stage_data, web_data, new_snapshot)
            _phase4d_checkpoint("after_stocks_stage_copy")
            snapshot_validation = _validate_promoted_snapshot(
                web_data, new_snapshot, stage_data=stage_data,
            )
            alignment_final = None
            if alignment_binding is not None:
                if alignment_binding.get("binding_type") == "DAILY_ALIGNMENT":
                    alignment_final = _validate_daily_alignment_promotion_context(
                        _daily_alignment_context, stage_data, target_as_of, root,
                    )
                else:
                    alignment_final = _validate_v13_alignment_stage(
                        stage_data,
                        target_as_of,
                        root,
                        expected_candidate_digest=alignment_binding["candidate_digest"],
                    )
                if alignment_preflight is None or alignment_final["stage_fingerprint_sha256"] != alignment_preflight["stage_fingerprint_sha256"]:
                    raise Phase4DError("PHASE4D_ALIGNMENT_FINAL_STAGE_FINGERPRINT_MISMATCH")
                if not isinstance(alignment_final.get("b_select_status_sha256"), str):
                    raise Phase4DError("PHASE4D_ALIGNMENT_FINAL_STATUS_HASH_MISSING")
                _assert_alignment_snapshot_matches_stage(stage_data, new_snapshot)
                _phase4d_checkpoint("after_alignment_final_gate")
            new_manifest = _tree_manifest(new_snapshot)
            new_status_digest = (
                alignment_final["b_select_status_sha256"]
                if alignment_final is not None
                else _sha256_file(status_source)
            )
            old_status_digest = _status_digest(status_destination)
            journal = {
                "schema": "phase4d_publish_transaction_v02",
                "transaction_id": tx_id,
                "target_as_of": target_as_of,
                "phase": "PREPARED",
                "transaction_dir": _relative_to_root(tx_dir, root),
                "backup_web_data": _relative_to_root(backup_web_data, root),
                "restore_web_data": _relative_to_root(restore_web_data, root),
                "status_destination": _relative_to_root(status_destination, root),
                "backup_status": _relative_to_root(backup_status, root),
                "restore_status": _relative_to_root(restore_status, root),
                "status_temporary": _relative_to_root(status_temporary, root),
                "old_web_data_manifest": old_manifest,
                "new_web_data_manifest": new_manifest,
                "old_status_sha256": old_status_digest,
                "new_status_sha256": new_status_digest,
            }
            _write_transaction_journal(journal_path, journal)

            try:
                if old_status_digest is not None:
                    _phase4d_checkpoint("before_status_backup")
                    shutil.copy2(status_destination, backup_status)
                    if _status_digest(backup_status) != old_status_digest:
                        raise Phase4DError("PHASE4D_STATUS_BACKUP_HASH_MISMATCH")
                    _phase4d_checkpoint("after_status_backup")
                shutil.copy2(status_source, status_temporary)
                if _status_digest(status_temporary) != new_status_digest:
                    raise Phase4DError("PHASE4D_STATUS_STAGE_COPY_HASH_MISMATCH")

                _phase4d_checkpoint("before_stocks_backup")
                if web_data.exists():
                    os.replace(web_data, backup_web_data)
                _phase4d_checkpoint("after_stocks_backup")
                journal["phase"] = "WEB_DATA_BACKED_UP"
                _write_transaction_journal(journal_path, journal)

                _phase4d_checkpoint("before_stocks_promote")
                os.replace(new_snapshot, web_data)
                _phase4d_checkpoint("after_stocks_promote")
                journal["phase"] = "WEB_DATA_PROMOTED"
                _write_transaction_journal(journal_path, journal)

                _phase4d_checkpoint("before_status_promote")
                os.replace(status_temporary, status_destination)
                _phase4d_checkpoint("after_status_promote")
                journal["phase"] = "STATUS_PROMOTED"
                _write_transaction_journal(journal_path, journal)

                if _tree_manifest(web_data) != new_manifest or _status_digest(status_destination) != new_status_digest:
                    raise Phase4DError("PHASE4D_PROMOTED_SNAPSHOT_HASH_MISMATCH")
                _phase4d_checkpoint("before_post_readback")
                readback = post_publish_validate(status_destination) if post_publish_validate is not None else None
                _phase4d_checkpoint("after_post_readback")
                journal["phase"] = "COMMITTED"
                _write_transaction_journal(journal_path, journal)
            except Exception as exc:
                try:
                    rollback = _recover_pending_promotion(web_data)
                except Exception as recovery_exc:
                    raise Phase4DError(
                        f"PHASE4D_PROMOTION_FAILED_RECOVERY_CHECK_REQUIRED:{tx_dir}: "
                        f"cause={exc}; recovery={recovery_exc}"
                    ) from recovery_exc
                if isinstance(exc, Phase4DError):
                    raise Phase4DError(
                        f"{exc}; rollback={rollback.get('status')}; transaction={tx_id}"
                    ) from exc
                raise Phase4DError(
                    f"PHASE4D_PROMOTION_FAILED_ROLLED_BACK:{exc}; rollback={rollback.get('status')}; "
                    f"transaction={tx_id}"
                ) from exc

            shutil.rmtree(tx_dir, ignore_errors=True)
            if tx_dir.exists():
                raise Phase4DError(f"PHASE4D_COMMITTED_BACKUP_CLEANUP_CHECK_REQUIRED: {tx_dir}")
            journal_path.unlink(missing_ok=True)
            return {
                "status_path": status_destination,
                "post_publish_readback": readback,
                "promoted_snapshot_validation": snapshot_validation,
                "publication": {
                    "transaction_id": tx_id,
                    "status": "COMMITTED_AND_READ_BACK",
                    "consistency_boundary": "COMPLETE_WEB_DATA_DIRECTORY_PLUS_SEPARATE_B_SELECT_STATUS_REPLACE",
                    "cross_path_atomicity": False,
                    "temporary_exposure": "web/data may be briefly absent during directory rename; B Select status is replaced separately",
                    "failure_recovery": "FULL_OLD_SNAPSHOT_RESTORED_BEFORE_BACKUP_CLEANUP",
                    "prior_transaction_recovery": recovery.get("status"),
                },
            }
        finally:
            if "status_temporary" in locals():
                status_temporary.unlink(missing_ok=True)
            if "tx_dir" in locals() and tx_dir.exists() and not journal_path.exists():
                shutil.rmtree(tx_dir, ignore_errors=True)
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def run_phase4d(
    target_as_of: str,
    *,
    execute_live: bool,
    root: Path = ROOT,
    phase4c_result: dict[str, Any] | None = None,
    alignment_candidate_digest: str | None = None,
) -> dict[str, Any]:
    if root != ROOT:
        raise Phase4DError("PHASE4D_REPOSITORY_ROOT_MISMATCH")
    web_data = root / "web/data"
    journal_path = web_data.parent / PHASE4D_PUBLISH_JOURNAL
    if journal_path.exists():
        if not execute_live:
            raise Phase4DError("PHASE4D_PENDING_PUBLISH_RECOVERY_REQUIRES_EXECUTE_LIVE")
        _recover_pending_promotion(web_data)
    if alignment_candidate_digest is not None:
        _alignment_candidate_binding(
            root / V13_ALIGNMENT_STAGE_RELATIVE_PATH,
            root,
            alignment_candidate_digest=alignment_candidate_digest,
        )
        if target_as_of != "2026-10-11":
            raise Phase4DError("PHASE4D_ALIGNMENT_CANDIDATE_TARGET_DATE_MISMATCH")
        published = inspect_published_payload(root, target_as_of, require_etf_source=True)
        if _published_alignment_candidate_matches(
            root,
            target_as_of,
            alignment_candidate_digest,
            published,
        ):
            return {
                "status": "NOOP_ALREADY_COMPLETE",
                "target_as_of": target_as_of,
                "requested_as_of": target_as_of,
                "reference_market_date": "2026-10-08",
                "execute_live": execute_live,
                "network_calls": 0,
                "web_data_writes": 0,
                "b_select_status_writes": 0,
                "promotion_called": False,
                "published": published["validation"],
                "candidate_digest": alignment_candidate_digest,
                "reason": "VALID_PUBLISHED_ALIGNMENT_CANDIDATE",
            }

        stage_data = root / V13_ALIGNMENT_STAGE_RELATIVE_PATH
        eligibility = _validate_v13_alignment_stage(
            stage_data,
            target_as_of,
            root,
            expected_candidate_digest=alignment_candidate_digest,
        )
        snapshot_validation = _inspect_final_promotion_snapshot(stage_data, web_data)
        promotion = None
        readback = None
        if execute_live:
            promotion = promote(
                stage_data,
                web_data,
                target_as_of=target_as_of,
                alignment_candidate_digest=alignment_candidate_digest,
                post_publish_validate=lambda status_path: validate_staging(
                    web_data,
                    target_as_of,
                    "2026-10-08",
                    require_etf36=True,
                    b_select_status_path=status_path,
                    expected_permanent_identity_exclusion_count=V13_ALIGNMENT_PERMANENT_EXCLUSION_COUNT,
                ),
            )
            readback = promotion["post_publish_readback"]
        return {
            "status": "PASS",
            "target_as_of": target_as_of,
            "requested_as_of": target_as_of,
            "reference_market_date": "2026-10-08",
            "execute_live": execute_live,
            "network_calls": 0,
            "web_data_writes": 0 if not execute_live else None,
            "b_select_status_writes": 0 if not execute_live else None,
            "promotion_called": execute_live,
            "candidate_digest": alignment_candidate_digest,
            "candidate_eligibility": eligibility,
            "promote_snapshot_validation": snapshot_validation,
            "post_promote_readback": readback,
            "publication": promotion["publication"] if promotion is not None else None,
        }
    published = (
        inspect_published_payload(root, target_as_of, require_etf_source=True)
        if phase4c_result is None
        else None
    )
    if published is not None and phase4c_result is None:
        canonical_alignment = _canonical_full_history_alignment_provenance(
            root,
            target_as_of,
            str(published["reference_market_date"]),
        )
        if canonical_alignment is not None and not _published_monitor_matches_canonical_full_history_alignment(
            root,
            target_as_of,
            str(published["reference_market_date"]),
            canonical_alignment,
        ):
            published = None
    if published is not None and phase4c_result is None:
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
    stage_root = Path(tempfile.mkdtemp(prefix=".phase4d-stage-", dir=web_data.parent))
    try:
        stage_data = stage_root / "data"
        stage_data.mkdir()
        stage_context = _stage_payloads(target_as_of, stage_data, phase4c_result=phase4c_result)
        validation = validate_staging(
            stage_data, target_as_of, stage_context["reference_market_date"], require_etf36=True,
        )
        snapshot_validation = _inspect_final_promotion_snapshot(stage_data, web_data)
        phase4c_for_stage = stage_context.get("phase4c", phase4c_result)
        daily_alignment_context = (
            _create_daily_alignment_promotion_context(
                stage_data,
                target_as_of,
                stage_context["reference_market_date"],
                root,
                phase4c_for_stage,
            )
            if isinstance(phase4c_for_stage, dict)
            else None
        )
        if execute_live:
            promotion = promote(
                stage_data,
                web_data,
                target_as_of=target_as_of,
                post_publish_validate=lambda status_path: validate_staging(
                    web_data,
                    target_as_of,
                    stage_context["reference_market_date"],
                    require_etf36=True,
                    b_select_status_path=status_path,
                ),
                _daily_alignment_context=daily_alignment_context,
            )
            readback = promotion["post_publish_readback"]
        else:
            readback = None
        return {
            "status": "PASS",
            "target_as_of": target_as_of,
            "requested_as_of": target_as_of,
            "reference_market_date": stage_context["reference_market_date"],
            "execute_live": execute_live,
            "network_calls": 0,
            "sector_membership": stage_context["sector_membership"],
            "staging": validation,
            "promote_snapshot_validation": snapshot_validation,
            "daily_alignment_eligibility": (
                daily_alignment_context["proof"] if daily_alignment_context is not None else None
            ),
            "post_promote_readback": readback,
            "publication": promotion["publication"] if execute_live else None,
        }
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    parser.add_argument(
        "--alignment-candidate-digest",
        help="explicitly validate the pinned saved Alignment candidate digest",
    )
    parser.add_argument("--execute-live", action="store_true", help="promote validated staging payloads to web/data")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run_phase4d(
            args.target_as_of,
            execute_live=args.execute_live,
            alignment_candidate_digest=args.alignment_candidate_digest,
        ), ensure_ascii=False, indent=2))
        return 0
    except (Phase4DError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
