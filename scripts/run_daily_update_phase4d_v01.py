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
    try:
        validation = validate_staging(
            web_data, target_as_of, reference_market_date, require_etf36=require_etf_source,
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
    strategy = strategy_web.build_strategy_monitor(
        index_path=stage_data / "stock-index.json",
        stocks_path=stocks_dir,
        target_as_of=target_as_of,
        reference_market_date=reference_market_date,
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
    }


def validate_staging(
    stage_data: Path,
    target_as_of: str,
    reference_market_date: str,
    *,
    require_etf36: bool = False,
) -> dict[str, Any]:
    missing = [name for name in REQUIRED_FILES if not (stage_data / name).is_file()]
    if missing or not (stage_data / "stocks").is_dir():
        raise Phase4DError(f"PHASE4D_STAGE_REQUIRED_OUTPUT_MISSING: {missing}")
    documents = {name: _read_json(stage_data / name) for name in REQUIRED_FILES}
    stock_paths = sorted((stage_data / "stocks").glob("*.json"))
    stocks = {path.stem: _read_json(path) for path in stock_paths}
    for name, document in documents.items():
        _assert_finite(document, name)
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
    if {item.get("ticker") for item in strategy.get("items", [])} != common_tickers:
        raise Phase4DError("PHASE4D_STRATEGY_SET_MISMATCH")
    if market.get("scope", {}).get("report_count") != len(common_tickers) or strategy.get("scope", {}).get("report_count") != len(common_tickers):
        raise Phase4DError("PHASE4D_REPORT_COUNT_MISMATCH")
    if strategy.get("strategy", {}).get("id") != STRATEGY_ID:
        raise Phase4DError("PHASE4D_STRATEGY_ID_MISMATCH")

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
    }


def promote(stage_data: Path, web_data: Path) -> None:
    backup = web_data.parent / f".phase4d-stocks-backup-{os.getpid()}"
    staged_stocks = stage_data / "stocks"
    destination_stocks = web_data / "stocks"
    if backup.exists():
        raise Phase4DError(f"PHASE4D_BACKUP_PATH_EXISTS: {backup}")
    try:
        if destination_stocks.exists():
            destination_stocks.replace(backup)
        staged_stocks.replace(destination_stocks)
        for name in REQUIRED_FILES:
            (stage_data / name).replace(web_data / name)
    except Exception:
        if not destination_stocks.exists() and backup.exists():
            backup.replace(destination_stocks)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)


def run_phase4d(
    target_as_of: str,
    *,
    execute_live: bool,
    root: Path = ROOT,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if root != ROOT:
        raise Phase4DError("PHASE4D_REPOSITORY_ROOT_MISMATCH")
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
        context = _stage_payloads(target_as_of, stage_data, phase4c_result=phase4c_result)
        validation = validate_staging(
            stage_data, target_as_of, context["reference_market_date"], require_etf36=True,
        )
        if execute_live:
            promote(stage_data, web_data)
            readback = validate_staging(
                web_data, target_as_of, context["reference_market_date"], require_etf36=True,
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run_phase4d(args.target_as_of, execute_live=args.execute_live), ensure_ascii=False, indent=2))
        return 0
    except (Phase4DError, ValueError, FileNotFoundError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
