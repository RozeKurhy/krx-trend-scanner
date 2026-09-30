#!/usr/bin/env python3
"""Export local Stock Report authority into compact public web JSON.

This exporter is deliberately a read-only consumer of existing repository
artifacts. It does not generate reports, recalculate indicators, hydrate
fundamentals, or contact any external provider.
"""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import date
import json
from pathlib import Path
import re
import tempfile
from functools import lru_cache
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_STOCK_REPORT_VERSIONS = {"0.5", "0.6", "0.7"}
METADATA_PATH = ROOT / "data/reference/krx_instrument_metadata.csv"
STOCK_REPORTS_ROOT = ROOT / "artifacts/reporting/stock_reports"
ETF_STOCK_REPORTS_ROOT = ROOT / "artifacts/reporting/etf_stock_reports"
ADJUSTED_STOCK_ROOT = ROOT / "data/market/adjusted/stocks"
DEFAULT_OUTPUT_DIR = ROOT / "web/data"
DATE_DIR_PATTERN = re.compile(r"^(\d{8})$")
FUNDAMENTALS_PUBLIC_FIELDS = (
    "applicability",
    "reason",
    "requested_as_of",
    "company_family",
    "currency",
    "filter_status",
    "filter_passed",
    "filter_reasons",
    "summary",
    "quarterly",
    "annual",
)
VALID_FUNDAMENTALS_STATUSES = {"READY", "PARTIAL", "DATA_UNAVAILABLE", "NOT_APPLICABLE"}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON authority must be an object: {path}")
    return value


def _validate_report_contract(report: dict[str, Any], source_path: Path) -> None:
    version = report.get("report_version")
    if version == "0.6":
        if (
            report.get("asset_type") != "ETF"
            or "a_fast_core" in report
            or not isinstance(report.get("official_strategy"), dict)
            or report["official_strategy"].get("strategy_id") != "JULIA_ETF_STRATEGY_V01"
            or report["official_strategy"].get("strategy_name") != "Julia V1"
        ):
            raise ValueError(f"Stock Report v0.6 ETF Julia contract missing: {source_path}")
        return
    if not isinstance(version, str) or version not in SUPPORTED_STOCK_REPORT_VERSIONS:
        raise ValueError(f"Unsupported Stock Report version {version!r}: {source_path}")
    if version == "0.7" and (
        report.get("asset_type") != "COMMON"
        or not isinstance(report.get("pattern_b"), dict)
    ):
        raise ValueError(f"Stock Report v0.7 COMMON Pattern B contract missing: {source_path}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temp:
        temp_path = Path(temp.name)
        temp.write(encoded)
        temp.flush()
    temp_path.replace(path)


def _iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _resolve_report_directory() -> tuple[Path, str]:
    candidates: list[tuple[date, Path]] = []
    for path in STOCK_REPORTS_ROOT.iterdir():
        if not path.is_dir() or DATE_DIR_PATTERN.fullmatch(path.name) is None:
            continue
        json_dir = path / "json"
        if not json_dir.is_dir() or not any(json_dir.glob("*.json")):
            continue
        candidates.append((_iso_date(f"{path.name[:4]}-{path.name[4:6]}-{path.name[6:]}"), path))
    if not candidates:
        raise FileNotFoundError("no dated Stock Report JSON authority found")
    _, directory = max(candidates, key=lambda item: (item[0], item[1].name))
    return directory, f"{directory.name[:4]}-{directory.name[4:6]}-{directory.name[6:]}"


def _resolve_exact_report_directory(target_as_of: str) -> tuple[Path, str]:
    """PHASE4C_MANDATORY_ANALYSIS_DISPLAY_V01: production 4C는 최신 디렉터리를
    자동 선택하지 않고 target_as_of 디렉터리 하나만 exact하게 사용한다."""
    dt_clean = target_as_of.replace("-", "")
    directory = STOCK_REPORTS_ROOT / dt_clean
    json_dir = directory / "json"
    if not directory.is_dir() or not json_dir.is_dir() or not any(json_dir.glob("*.json")):
        raise FileNotFoundError(f"exact-target Stock Report directory not found or empty: {directory}")
    return directory, target_as_of


def _load_universe(requested_as_of: str) -> tuple[list[dict[str, str]], str]:
    from trend_scanner.universe.instrument_metadata import load_target_production_universe

    rows, snapshot_date = load_target_production_universe(ROOT, requested_as_of)
    current = [
        {
            "ticker": str(row["ticker"]),
            "name": str(row.get("name") or row["ticker"]).strip(),
            "market": str(row.get("market") or "UNKNOWN").strip().upper(),
            "asset_type": str(row.get("asset_type") or "UNKNOWN").strip().upper(),
            "effective_date": str(row.get("effective_date") or snapshot_date)[:10],
        }
        for row in rows
    ]
    tickers = [row["ticker"] for row in current]
    if len(tickers) != len(set(tickers)):
        raise ValueError("target production universe contains duplicate tickers")
    return current, snapshot_date


@lru_cache(maxsize=None)
def _load_exact_daily_close(ticker: str, as_of: str) -> dict[str, Any] | None:
    """Read one exact-date close from the local adjusted market authority."""
    if not ticker or not as_of:
        return None
    path = ADJUSTED_STOCK_ROOT / f"{ticker}.parquet"
    if not path.exists():
        return None
    try:
        import pandas as pd

        daily = pd.read_parquet(path, columns=["date", "close"])
        if "date" not in daily or "close" not in daily:
            return None
        dates = pd.to_datetime(daily["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        matches = daily.loc[dates == as_of, "close"].dropna()
    except (ImportError, OSError, ValueError, KeyError):
        return None
    if len(matches) != 1:
        return None
    return {
        "value": float(matches.iloc[0]),
        "as_of": as_of,
        "source": _relative(path),
    }


def _compact_monthly_history(monthly: dict[str, Any]) -> list[dict[str, Any]]:
    history = monthly.get("recent_12m_history") or []
    if not isinstance(history, list):
        return []
    return [
        {
            "as_of": observation.get("as_of"),
            "close": observation.get("close"),
            "score": observation.get("score"),
            "stage": observation.get("stage"),
            "candidate_state": observation.get("candidate_state"),
            "data_available": observation.get("data_available"),
        }
        for observation in history
        if isinstance(observation, dict)
    ]


def _compact_trade_history(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    history = strategy.get("trade_history") or []
    if not isinstance(history, list):
        return []
    fields = (
        "trade_id",
        "trade_sequence",
        "entry_signal_date",
        "entry_execution_date",
        "entry_open",
        "entry_pattern_a_stage",
        "exit_type",
        "exit_signal_date",
        "exit_execution_date",
        "exit_price",
        "trade_status",
        "return_pct",
        "lifecycle_class",
    )
    return [
        {field: trade.get(field) for field in fields}
        for trade in history
        if isinstance(trade, dict)
    ]


def validate_exact_etf_report_corpus(
    target_as_of: str,
    reference_market_date: str,
) -> tuple[Path, dict[str, dict[str, Any]], dict[str, Path]]:
    """Validate the exact frozen ETF36 v0.6 source corpus without projection."""
    from trend_scanner.reporting.julia_v1_report import load_official_etf36, validate_v06_report_payload

    etf_dir = ETF_STOCK_REPORTS_ROOT / target_as_of.replace("-", "")
    etf_json_dir = etf_dir / "json"
    if not etf_json_dir.is_dir():
        raise FileNotFoundError(f"exact-target ETF Stock Report directory not found: {etf_json_dir}")
    official_identities, _universe_sha = load_official_etf36(ROOT)
    frozen_tickers = {identity.ticker for identity in official_identities}
    etf_reports: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    for path in sorted(etf_json_dir.glob("*.json")):
        report = _read_json(path)
        ticker = str(report.get("ticker") or "").strip().upper()
        if not ticker or ticker in etf_reports:
            raise ValueError(f"invalid or duplicate ETF Stock Report ticker: {path}")
        if ticker not in frozen_tickers:
            raise ValueError(f"ETF Stock Report outside frozen Official ETF36: {path}")
        if str(report.get("requested_as_of") or "")[:10] != target_as_of:
            raise ValueError(f"ETF Stock Report date mismatch: {path}")
        if str(report.get("reference_market_date") or "")[:10] != reference_market_date:
            raise ValueError(f"ETF Stock Report reference_market_date mismatch: {path}")
        _validate_report_contract(report, path)
        markdown_path = etf_dir / f"{path.stem}.md"
        if not markdown_path.is_file():
            raise FileNotFoundError(f"ETF Stock Report Markdown authority missing: {markdown_path}")
        validate_v06_report_payload(ROOT, report, markdown_path.read_text(encoding="utf-8"))
        fundamentals = report.get("fundamentals")
        if not isinstance(fundamentals, dict) or fundamentals.get("requested_as_of") != target_as_of:
            raise ValueError(f"ETF Stock Report fundamentals date mismatch: {path}")
        etf_reports[ticker] = report
        source_paths[ticker] = path
    if set(etf_reports) != frozen_tickers:
        missing = sorted(frozen_tickers - set(etf_reports))
        extra = sorted(set(etf_reports) - frozen_tickers)
        raise ValueError(
            "ETF Stock Report frozen ticker set mismatch: "
            f"missing={missing[:5]} extra={extra[:5]} count={len(etf_reports)}"
        )
    return etf_dir, etf_reports, source_paths


def _compact_fundamentals(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError("Stock Report fundamentals authority is missing")
    data_status = source.get("data_status")
    if data_status not in VALID_FUNDAMENTALS_STATUSES:
        raise ValueError(f"invalid Stock Report fundamentals data_status: {data_status!r}")
    missing = [field for field in FUNDAMENTALS_PUBLIC_FIELDS if field not in source]
    if missing:
        raise ValueError(f"Stock Report fundamentals fields missing: {missing}")
    if not isinstance(source["filter_reasons"], list):
        raise ValueError("Stock Report fundamentals filter_reasons must be an array")
    if not isinstance(source["summary"], dict):
        raise ValueError("Stock Report fundamentals summary must be an object")
    if not isinstance(source["quarterly"], list) or not isinstance(source["annual"], list):
        raise ValueError("Stock Report fundamentals periods must be arrays")
    return {
        "status": data_status,
        **{field: copy.deepcopy(source[field]) for field in FUNDAMENTALS_PUBLIC_FIELDS},
    }


def _compact_report(report: dict[str, Any], source_path: Path) -> dict[str, Any]:
    header = report.get("header") or {}
    snapshot = report.get("current_snapshot") or {}
    monthly = report.get("monthly_history") or {}
    relative_strength = report.get("relative_strength") or {}
    sector_strength = report.get("sector_relative_strength") or {}
    flow = report.get("foreign_flow") or {}
    trading_value = report.get("trading_value_flow") or {}
    is_etf_v06 = report.get("report_version") == "0.6"
    strategy = (report.get("official_strategy") if is_etf_v06 else report.get("a_fast_core")) or {}
    pattern_b = report.get("pattern_b")
    ticker = str(report.get("ticker") or header.get("ticker") or "").upper()
    asset_type = str(report.get("asset_type") or header.get("asset_type") or "UNKNOWN").upper()
    reference_market_date = str(report.get("reference_market_date") or "")[:10]
    daily_close = _load_exact_daily_close(ticker, reference_market_date)
    fundamentals = _compact_fundamentals(report.get("fundamentals"))
    if is_etf_v06:
        strategy_history = []
        for trade in strategy.get("trade_history") or []:
            if not isinstance(trade, dict):
                continue
            strategy_history.append({
                "trade_id": trade.get("trade_id"),
                "trade_sequence": trade.get("trade_sequence"),
                "entry_signal_date": trade.get("entry_signal_date"),
                "entry_execution_date": trade.get("entry_execution_date"),
                "entry_open": trade.get("entry_open_krw"),
                "entry_pattern_a_stage": trade.get("entry_pattern_a_stage"),
                "exit_type": trade.get("exit_type"),
                "exit_signal_date": trade.get("exit_signal_date"),
                "exit_execution_date": trade.get("exit_execution_date"),
                "exit_price": trade.get("exit_price_krw"),
                "trade_status": trade.get("trade_status"),
                "return_pct": trade.get("terminal_return_pct"),
                "lifecycle_class": trade.get("lifecycle_class"),
            })
        strategy_public = {
            "source": "official_strategy",
            "id": strategy.get("strategy_id"),
            "strategy_id": strategy.get("strategy_id"),
            "strategy_name": strategy.get("strategy_name"),
            "action": strategy.get("action"),
            "state": strategy.get("strategy_state"),
            "position": strategy.get("canonical_position"),
            "reason": strategy.get("action_reason"),
            "action_reason": strategy.get("action_reason"),
            "interpretation": strategy.get("interpretation"),
            "history": strategy_history,
            "eligibility": copy.deepcopy((report.get("current_snapshot") or {}).get("etf_eligibility") or {}),
        }
    else:
        strategy_public = {
            "action": strategy.get("action"),
            "state": strategy.get("strategy_state"),
            "position": strategy.get("canonical_position"),
            "reason": strategy.get("action_reason"),
            "interpretation": strategy.get("interpretation"),
            "history": _compact_trade_history(strategy),
        }

    return {
        "schema_version": 1,
        "identity": {
            "ticker": ticker,
            "name": str(report.get("name") or header.get("name") or ""),
            "market": str(report.get("market") or header.get("market") or "").upper(),
            "asset_type": asset_type,
        },
        "availability": {
            "report_available": True,
            "report_status": header.get("report_status"),
        },
        "decision": {
            "action": strategy.get("action"),
            "strategy_state": strategy.get("strategy_state"),
            "canonical_position": strategy.get("canonical_position"),
            "action_reason": strategy.get("action_reason"),
            "is_investable": snapshot.get("is_investable"),
        },
        "summary": {
            "trend_stage": snapshot.get("official_stage"),
            "flow_state": flow.get("flow_state"),
        },
        "price_trend": {
            "latest_close": daily_close["value"] if daily_close else None,
            "latest_close_as_of": daily_close["as_of"] if daily_close else None,
            "price_status": "AVAILABLE" if daily_close else "UNAVAILABLE",
            "price_source": daily_close["source"] if daily_close else None,
            "score_trend": monthly.get("score_trend") or {},
            "trading_value_state": trading_value.get("trading_value_state"),
            "trading_value_explanation": trading_value.get("explanation"),
            "avg_trading_value_1d_eok": trading_value.get("avg_trading_value_1d_eok"),
            "avg_trading_value_5d_eok": trading_value.get("avg_trading_value_5d_eok"),
            "avg_trading_value_10d_eok": trading_value.get("avg_trading_value_10d_eok"),
            "avg_trading_value_20d_eok": trading_value.get("avg_trading_value_20d_eok"),
            "avg_trading_value_60d_eok": trading_value.get("avg_trading_value_60d_eok"),
        },
        "pattern": {
            "official_stage": snapshot.get("official_stage"),
            "candidate_state": snapshot.get("candidate_state"),
            "score": snapshot.get("pattern_a_score"),
            "history_12m": _compact_monthly_history(monthly),
        },
        # Pattern B is a report-owned informational analysis. This compact
        # export intentionally copies it without recalculation or hydration.
        "pattern_b": copy.deepcopy(pattern_b) if asset_type == "COMMON" and isinstance(pattern_b, dict) else None,
        "market_strength": {
            "applicability": relative_strength.get("applicability"),
            "data_status": relative_strength.get("data_status"),
            "benchmark_name": relative_strength.get("benchmark_name"),
            "benchmark_last_observation_date": relative_strength.get("benchmark_last_observation_date"),
            "stock_return_2w": relative_strength.get("stock_return_2w"),
            "stock_return_1m": relative_strength.get("stock_return_1m"),
            "stock_return_3m": relative_strength.get("stock_return_3m"),
            "stock_return_6m": relative_strength.get("stock_return_6m"),
            "stock_return_12m": relative_strength.get("stock_return_12m"),
            "market_rs_2w": relative_strength.get("market_rs_2w"),
            "market_rs_1m": relative_strength.get("market_rs_1m"),
            "market_rs_3m": relative_strength.get("market_rs_3m"),
            "market_rs_6m": relative_strength.get("market_rs_6m"),
            "market_rs_12m": relative_strength.get("market_rs_12m"),
            "percentile_2w": relative_strength.get("all_market_rs_percentile_2w"),
            "percentile_1m": relative_strength.get("all_market_rs_percentile_1m"),
            "percentile_3m": relative_strength.get("all_market_rs_percentile_3m"),
            "percentile_6m": relative_strength.get("all_market_rs_percentile_6m"),
            "percentile_12m": relative_strength.get("all_market_rs_percentile_12m"),
            "explanation": relative_strength.get("explanation"),
        },
        "flow": {
            "data_status": flow.get("data_status"),
            "state": flow.get("flow_state"),
            "net_buy_value_1d_krw": flow.get("foreign_net_buy_value_1d_krw"),
            "net_buy_value_5d_krw": flow.get("foreign_net_buy_value_5d_krw"),
            "net_buy_value_10d_krw": flow.get("foreign_net_buy_value_10d_krw"),
            "net_buy_value_20d_krw": flow.get("foreign_net_buy_value_20d_krw"),
            "net_buy_value_60d_krw": flow.get("foreign_net_buy_value_60d_krw"),
            "intensity_1d": flow.get("foreign_flow_intensity_1d"),
            "intensity_5d": flow.get("foreign_flow_intensity_5d"),
            "intensity_10d": flow.get("foreign_flow_intensity_10d"),
            "intensity_20d": flow.get("foreign_flow_intensity_20d"),
            "intensity_60d": flow.get("foreign_flow_intensity_60d"),
            "positive_days_1d": flow.get("foreign_positive_days_1d"),
            "positive_days_5d": flow.get("foreign_positive_days_5d"),
            "positive_days_10d": flow.get("foreign_positive_days_10d"),
            "positive_days_20d": flow.get("foreign_positive_days_20d"),
            "positive_days_60d": flow.get("foreign_positive_days_60d"),
            "explanation": flow.get("explanation"),
        },
        "fundamentals": fundamentals,
        "strategy": strategy_public,
        "technical_details": {
            "requested_as_of": report.get("requested_as_of"),
            "reference_market_date": reference_market_date,
            "report_version": report.get("report_version"),
            "report_status": header.get("report_status"),
            "asset_type": report.get("asset_type"),
            "investability_status": snapshot.get("investability_status"),
            "investability_reason": snapshot.get("investability_reason"),
            "pattern_stage": snapshot.get("official_stage"),
            "pattern_score": snapshot.get("pattern_a_score"),
            "candidate_state": snapshot.get("candidate_state"),
            "flow_state": flow.get("flow_state"),
            "market_strength_applicability": relative_strength.get("applicability"),
            "market_strength_status": relative_strength.get("data_status"),
            "relative_strength_status": relative_strength.get("data_status"),
            "trading_value_state": trading_value.get("trading_value_state"),
            "price_as_of": daily_close["as_of"] if daily_close else None,
            "price_status": "AVAILABLE" if daily_close else "UNAVAILABLE",
            "price_source": daily_close["source"] if daily_close else None,
            "sector_name": sector_strength.get("sector_name"),
            "data_quality": report.get("data_quality") or {},
            "source_report": _relative(source_path),
        },
        "external_links": {
            "naver_finance": f"https://finance.naver.com/item/main.naver?code={ticker}",
            "naver_chart": f"https://stock.naver.com/fchart/domestic/stock/{ticker}",
        },
    }


def build_web_payload(
    repo_root: Path = ROOT,
    *,
    target_as_of: str | None = None,
    reference_market_date: str | None = None,
    include_etf: bool = False,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    """``target_as_of``(선택, PHASE4C_MANDATORY_ANALYSIS_DISPLAY_V01)를 명시하면
    최신 디렉터리 자동 선택 대신 그 날짜의 exact 디렉터리만 사용하고,
    ``reference_market_date``(생략 시 target_as_of와 동일)와의 불일치도 fail-closed로
    검증한다. 둘 다 생략하면 기존과 완전히 동일한 latest-directory 자동 선택
    경로를 그대로 쓴다(하위 호환)."""
    if repo_root != ROOT:
        raise ValueError("stock report web exporter is bound to the repository root")
    if target_as_of is not None:
        report_dir, requested_as_of = _resolve_exact_report_directory(target_as_of)
    else:
        report_dir, requested_as_of = _resolve_report_directory()
    effective_reference_market_date = (
        reference_market_date if reference_market_date is not None else requested_as_of
    )
    universe, snapshot_date = _load_universe(requested_as_of)
    source_json_dir = report_dir / "json"
    source_json_paths = sorted(source_json_dir.glob("*.json"))
    if not source_json_paths:
        raise ValueError(
            "Stock Report source must contain at least one JSON file, "
            f"got {len(source_json_paths)}"
        )
    if target_as_of is None and reference_market_date is None:
        # A dated report bundle can be requested on a non-trading/certification
        # date while all reports share an earlier actual market-data frontier.
        # Preserve the source report's reference date and validate every file
        # against it below instead of assuming it equals the request date.
        first_report = _read_json(source_json_paths[0])
        effective_reference_market_date = str(first_report.get("reference_market_date") or "")[:10]
    if not effective_reference_market_date or effective_reference_market_date > requested_as_of:
        raise ValueError("Stock Report reference_market_date is missing or after requested_as_of")
    reports: dict[str, dict[str, Any]] = {}
    fundamentals_status_counts: dict[str, int] = {}
    for path in source_json_paths:
        report = _read_json(path)
        ticker = str(report.get("ticker") or "").strip().upper()
        if not ticker or ticker in reports:
            raise ValueError(f"invalid or duplicate Stock Report ticker: {path}")
        if str(report.get("requested_as_of") or "")[:10] != requested_as_of:
            raise ValueError(f"Stock Report date mismatch: {path}")
        if str(report.get("reference_market_date") or "")[:10] != effective_reference_market_date:
            raise ValueError(f"Stock Report reference_market_date mismatch: {path}")
        _validate_report_contract(report, path)
        fundamentals_source = report.get("fundamentals")
        if not isinstance(fundamentals_source, dict) or fundamentals_source.get("requested_as_of") != requested_as_of:
            raise ValueError(f"Stock Report fundamentals date mismatch: {path}")
        reports[ticker] = _compact_report(report, path)
        status = reports[ticker]["fundamentals"]["status"]
        fundamentals_status_counts[status] = fundamentals_status_counts.get(status, 0) + 1

    source_directories = [_relative(report_dir)]
    etf_report_tickers: set[str] = set()
    if include_etf:
        if target_as_of is None:
            raise ValueError("ETF v0.6 Web projection requires exact target_as_of")
        etf_dir, etf_source_reports, etf_source_paths = validate_exact_etf_report_corpus(
            requested_as_of, effective_reference_market_date,
        )
        for ticker, etf_report in etf_source_reports.items():
            if ticker in reports:
                raise ValueError(f"COMMON/ETF Stock Report ticker conflict: {ticker}")
            path = etf_source_paths[ticker]
            reports[ticker] = _compact_report(etf_report, path)
            etf_report_tickers.add(ticker)
            status = reports[ticker]["fundamentals"]["status"]
            fundamentals_status_counts[status] = fundamentals_status_counts.get(status, 0) + 1
        if len(reports) != len(source_json_paths) + len(etf_source_reports):
            raise ValueError("COMMON/ETF Stock Report merged count mismatch")
        source_directories.append(_relative(etf_dir))

    report_tickers = set(reports)
    items = [
        {
            "ticker": row["ticker"],
            "name": row["name"],
            "market": row["market"],
            "asset_type": row["asset_type"],
            "report_available": row["ticker"] in report_tickers,
        }
        for row in universe
    ]
    unknown_reports = sorted(report_tickers - {item["ticker"] for item in items})
    if unknown_reports:
        raise ValueError(f"Stock Reports outside the PIT universe: {unknown_reports[:5]}")

    index = {
        "schema_version": 1,
        "requested_as_of": requested_as_of,
        "reference_market_date": effective_reference_market_date,
        "universe_snapshot_date": snapshot_date,
        "source_report_directory": _relative(report_dir),
        **({"source_report_directories": source_directories} if include_etf else {}),
        "count": len(items),
        "available_report_count": len(reports),
        "items": items,
    }
    stats = {
        "requested_as_of": requested_as_of,
        "reference_market_date": effective_reference_market_date,
        "universe_snapshot_date": snapshot_date,
        "universe_count": len(items),
        "available_report_count": len(reports),
        "unavailable_report_count": len(items) - len(reports),
        "source_report_directory": _relative(report_dir),
        "source_json_directory": _relative(source_json_dir),
        "source_report_directories": source_directories,
        "common_report_count": len(source_json_paths),
        "etf_report_count": len(etf_report_tickers),
        "fundamentals_integrated_count": len(reports),
        "fundamentals_status_counts": dict(sorted(fundamentals_status_counts.items())),
    }
    return index, reports, stats


def export_stock_reports(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    target_as_of: str | None = None,
    reference_market_date: str | None = None,
    include_etf: bool = False,
) -> dict[str, Any]:
    index, reports, stats = build_web_payload(
        target_as_of=target_as_of,
        reference_market_date=reference_market_date,
        include_etf=include_etf,
    )
    _write_json(output_dir / "stock-index.json", index)
    stock_dir = output_dir / "stocks"
    stock_dir.mkdir(parents=True, exist_ok=True)
    for ticker, report in sorted(reports.items()):
        _write_json(stock_dir / f"{ticker}.json", report)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-as-of", help="exact YYYY-MM-DD Stock Report target")
    parser.add_argument("--reference-market-date", help="exact YYYY-MM-DD market-data date")
    parser.add_argument("--include-etf", action="store_true", help="include exact frozen ETF36 v0.6 corpus")
    args = parser.parse_args()
    stats = export_stock_reports(
        args.output,
        target_as_of=args.target_as_of,
        reference_market_date=args.reference_market_date,
        include_etf=args.include_etf,
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
