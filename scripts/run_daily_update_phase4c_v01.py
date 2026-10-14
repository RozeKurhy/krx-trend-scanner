#!/usr/bin/env python3
"""Phase 4C production runner: exact-target 필수 분석 표시 결과 검증.

4A Scanner exact-target summary와 4B exact-target Stock Report corpus만 입력으로
받아, 기존 web export builder(``build_web_payload``/``build_market_ranking``/
``build_strategy_monitor``/``build_sector_rs_web_payload``/
``build_foreign_net_buy_ranking``/``build_health``)를 그대로 재사용해 6개 필수
payload를 생성·검증한다. 새 계산기를 만들지 않으며, ``web/data/``는 이 runner
실행 전후로 절대 쓰지 않는다(read-only). 검증 결과는 stdout summary로만 반환하고,
중간 payload는 ``TemporaryDirectory``에만 존재하다가 실행 종료와 함께 삭제된다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import export_foreign_net_buy_ranking_web as foreign_net_buy_web
from scripts import export_market_ranking_web as market_ranking_web
from scripts import export_sector_rs_ranking_web as sector_rs_web
from scripts import export_stock_report_web as stock_report_web
from scripts import export_strategy_monitor_web as strategy_monitor_web
from scripts import export_web_data as health_web
from scripts import build_b_select_core_v2_status as b_select_status_web
from scripts import build_b_select_core_v1_status as historical_b_select_status_web
from trend_scanner.data.sector_membership import (
    SectorMembershipSnapshotUnavailable,
    resolve_sector_membership_snapshot_for_target,
)
from trend_scanner.universe.historical_authority_reconciliation import (
    DEFAULT_RAW_ROOT as DEFAULT_BASIC_INFO_RAW_ROOT,
)

FAST_STRATEGY_IDS = {
    "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B",
}
PROMOTED_FAST_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
FULL_HISTORY_ALIGNMENT_WEB = "FULL_HISTORY_ALIGNMENT_WEB"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_daily_update_phase4c_v01")


class Phase4CError(RuntimeError):
    """Phase 4C fail-closed error (input validation, cross-payload validation)."""


def _b_select_status_builder(reference_market_date: str):
    """Select the historical V1 builder or current V2 builder explicitly."""
    reference = str(reference_market_date)[:10]
    if reference < "2026-10-02":
        return historical_b_select_status_web
    return b_select_status_web


def resolve_sector_membership_for_target(target_as_of: str, *, root: Path) -> tuple[str, Path]:
    """Return the approved periodic membership snapshot for ``target_as_of``."""

    try:
        _snapshot, effective_date, path, _meta = resolve_sector_membership_snapshot_for_target(
            target_as_of,
            repo_root=root,
        )
    except SectorMembershipSnapshotUnavailable as exc:
        raise Phase4CError(f"PHASE4C_FOREIGN_NET_BUY_AUTHORITY_MISSING: {exc}") from exc
    return effective_date, Path(path)


def require_payload_date(payload: dict[str, Any], field: str, expected: str, error_code: str) -> None:
    actual = payload.get(field)
    if actual != expected:
        raise Phase4CError(f"{error_code}: {actual!r}")


def _validate_fast_strategy_monitor(
    strategy_monitor: dict[str, Any],
    report_json_count: int,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Validate the single FAST row, default ID, promotion state/date, and scope."""
    strategy_rows = strategy_monitor.get("strategies")
    if not isinstance(strategy_rows, list):
        raise Phase4CError("PHASE4C_FAST_STRATEGY_ID_INVALID")
    strategy_by_id = {
        row["id"]: row for row in strategy_rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    fast_rows = [row for row in strategy_rows if isinstance(row, dict) and row.get("id") in FAST_STRATEGY_IDS]
    if len(fast_rows) != 1 or strategy_monitor.get("default_strategy_id") != fast_rows[0]["id"]:
        raise Phase4CError("PHASE4C_FAST_STRATEGY_ID_INVALID")
    fast_strategy_id = fast_rows[0]["id"]
    fast_gate_status = fast_rows[0].get("promotion_gate_status")
    fast_effective_signal_date = fast_rows[0].get("effective_signal_date")
    historical_replay = strategy_monitor.get("strategy_replay_mode") == FULL_HISTORY_ALIGNMENT_WEB
    if historical_replay:
        digest = strategy_monitor.get("strategy_replay_digest")
        scope = strategy_monitor.get("strategy_replay_scope")
        if (
            fast_strategy_id != PROMOTED_FAST_STRATEGY_ID
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(scope, dict)
            or fast_rows[0].get("strategy_replay_mode") != FULL_HISTORY_ALIGNMENT_WEB
            or fast_rows[0].get("strategy_replay_digest") != digest
            or fast_rows[0].get("strategy_replay_scope") != scope
            or scope.get("report_count") != report_json_count
            or scope.get("output_strategy_id") != PROMOTED_FAST_STRATEGY_ID
            or fast_gate_status is not None
            or fast_effective_signal_date is not None
            or fast_rows[0].get("activation_intervals") is not None
        ):
            raise Phase4CError("PHASE4C_FAST_FULL_HISTORY_REPLAY_PROVENANCE_INVALID")
    else:
        if fast_gate_status is None and fast_strategy_id == PROMOTED_FAST_STRATEGY_ID:
            raise Phase4CError("PHASE4C_FAST_PROMOTION_GATE_STATUS_MISSING")
        if fast_strategy_id == PROMOTED_FAST_STRATEGY_ID and fast_gate_status != "ACTIVE":
            raise Phase4CError("PHASE4C_FAST_PROMOTED_ID_NOT_ACTIVE")
    if fast_gate_status is not None and fast_gate_status not in {"INACTIVE_PENDING_USER_APPROVAL", "SCHEDULED_INACTIVE", "ACTIVE"}:
        raise Phase4CError("PHASE4C_FAST_PROMOTION_GATE_STATUS_INVALID")
    if fast_gate_status == "ACTIVE":
        try:
            valid_effective_date = date.fromisoformat(str(fast_effective_signal_date)).isoformat() == fast_effective_signal_date
        except ValueError:
            valid_effective_date = False
        if fast_strategy_id != "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B" or not valid_effective_date:
            raise Phase4CError("PHASE4C_FAST_ACTIVE_GATE_DATE_INVALID")
    if fast_gate_status == "INACTIVE_PENDING_USER_APPROVAL" and fast_effective_signal_date != "PENDING_USER_APPROVAL":
        raise Phase4CError("PHASE4C_FAST_PENDING_GATE_DATE_MISMATCH")
    if fast_gate_status == "SCHEDULED_INACTIVE":
        try:
            valid_scheduled_date = date.fromisoformat(str(fast_effective_signal_date)).isoformat() == fast_effective_signal_date
        except ValueError:
            valid_scheduled_date = False
        if fast_strategy_id != "PATTERN_A_FAST_FINAL_STRATEGY_V02" or not valid_scheduled_date:
            raise Phase4CError("PHASE4C_FAST_SCHEDULED_GATE_DATE_INVALID")
    fast_row = strategy_by_id[fast_strategy_id]
    if not isinstance(fast_row.get("items"), list) or not isinstance(fast_row.get("scope"), dict):
        raise Phase4CError("PHASE4C_FAST_STRATEGY_SCOPE_INVALID")
    if fast_row["scope"].get("report_count") != report_json_count:
        raise Phase4CError(
            f"PHASE4C_STRATEGY_MONITOR_REPORT_COUNT_MISMATCH: "
            f"{fast_row['scope'].get('report_count')} != {report_json_count}"
        )
    return fast_strategy_id, strategy_by_id


def validate_fast_full_history_projection(
    reports: dict[str, dict[str, Any]],
    strategy_monitor: dict[str, Any],
    fast_strategy_id: str,
) -> dict[str, int]:
    """Compare every source trade and OPEN position with the monitor projection."""
    if strategy_monitor.get("strategy_replay_mode") != FULL_HISTORY_ALIGNMENT_WEB:
        return {"source_trade_count": 0, "monitor_trade_count": 0, "trade_mismatch_count": 0, "open_mismatch_count": 0}
    row = next(
        item for item in strategy_monitor.get("strategies", [])
        if isinstance(item, dict) and item.get("id") == fast_strategy_id
    )
    source_trades: dict[tuple[Any, ...], dict[str, Any]] = {}
    source_open: dict[str, dict[str, Any]] = {}
    for ticker, report in reports.items():
        if (report.get("identity") or {}).get("asset_type") != "COMMON":
            continue
        strategy = report.get("strategy") or {}
        if (
            strategy.get("strategy_replay_mode") != FULL_HISTORY_ALIGNMENT_WEB
            or strategy.get("strategy_id") != fast_strategy_id
            or strategy.get("strategy_replay_digest") != strategy_monitor.get("strategy_replay_digest")
            or strategy.get("strategy_replay_scope") != strategy_monitor.get("strategy_replay_scope")
        ):
            raise Phase4CError(f"PHASE4C_FAST_SOURCE_MONITOR_PROVENANCE_MISMATCH: {ticker}")
        for trade in strategy.get("history") or []:
            key = (
                str(ticker).zfill(6), int(trade.get("trade_sequence")),
                str(trade.get("entry_signal_date") or ""), str(trade.get("entry_execution_date") or ""),
            )
            if key in source_trades:
                raise Phase4CError("PHASE4C_FAST_SOURCE_DUPLICATE_TRADE_KEY")
            source_trades[key] = {
                "trade_id": trade.get("trade_id"),
                "strategy_id": trade.get("strategy_id"),
                "entry_strategy_id": trade.get("entry_strategy_id"),
                "exit_strategy_id": trade.get("exit_strategy_id"),
                "entry_price": trade.get("entry_open"),
                "exit_reason": trade.get("exit_type"),
                "exit_signal_date": trade.get("exit_signal_date"),
                "exit_execution_date": trade.get("exit_execution_date"),
                "exit_price": trade.get("exit_price"),
                "return_pct": trade.get("return_pct"),
                "trade_status": trade.get("trade_status"),
            }
            if trade.get("trade_status") == "OPEN_AT_CUTOFF":
                source_open[str(ticker).zfill(6)] = trade

    monitor_trades: dict[tuple[Any, ...], dict[str, Any]] = {}
    for trade in row.get("trade_history") or []:
        key = (
            str(trade.get("ticker") or "").zfill(6), int(trade.get("trade_sequence")),
            str(trade.get("entry_signal_date") or ""), str(trade.get("entry_execution_date") or ""),
        )
        if key in monitor_trades:
            raise Phase4CError("PHASE4C_FAST_MONITOR_DUPLICATE_TRADE_KEY")
        monitor_trades[key] = {
            field: trade.get(field)
            for field in (
                "trade_id", "strategy_id", "entry_strategy_id", "exit_strategy_id",
                "entry_price", "exit_reason", "exit_signal_date", "exit_execution_date",
                "exit_price", "return_pct", "trade_status",
            )
        }
    trade_mismatches = sum(source_trades.get(key) != monitor_trades.get(key) for key in source_trades.keys() | monitor_trades.keys())
    monitor_items = {str(item.get("ticker") or "").zfill(6): item for item in row.get("items") or []}
    open_mismatches = 0
    for ticker in set(source_open) | {
        key for key, item in monitor_items.items() if item.get("canonical_position") == "OPEN"
    }:
        trade = source_open.get(ticker)
        item = monitor_items.get(ticker) or {}
        current = item.get("current_trade")
        if trade is None or not isinstance(current, dict) or any(
            current.get(field) != expected
            for field, expected in (
                ("trade_sequence", trade.get("trade_sequence")),
                ("entry_execution_date", trade.get("entry_execution_date")),
                ("entry_open", trade.get("entry_open")),
                ("trade_status", trade.get("trade_status")),
                ("strategy_id", fast_strategy_id),
                ("entry_strategy_id", fast_strategy_id),
                ("exit_strategy_id", fast_strategy_id),
            )
        ):
            open_mismatches += 1
    if trade_mismatches or open_mismatches:
        raise Phase4CError(
            "PHASE4C_FAST_SOURCE_MONITOR_PARITY_MISMATCH: "
            f"trades={trade_mismatches}, open={open_mismatches}"
        )
    return {
        "source_trade_count": len(source_trades),
        "monitor_trade_count": len(monitor_trades),
        "trade_mismatch_count": trade_mismatches,
        "source_open_position_count": len(source_open),
        "open_mismatch_count": open_mismatches,
    }


def require_web_data_unchanged(
    before: dict[str, tuple[float, int]],
    after: dict[str, tuple[float, int]],
) -> int:
    changed_paths = set(before) ^ set(after)
    changed_paths |= {key for key in before.keys() & after.keys() if before[key] != after[key]}
    if changed_paths:
        raise Phase4CError(
            f"PHASE4C_WEB_DATA_WRITE_DETECTED: {len(changed_paths)} path(s) changed under web/data/: "
            f"{sorted(changed_paths)[:5]}"
        )
    return 0


# --------------------------------------------------------------------------
# 1. 4A scanner summary exact target 로드
# --------------------------------------------------------------------------


def load_scanner_summary(root: Path, target_as_of: str) -> dict[str, Any]:
    dt_clean = target_as_of.replace("-", "")
    summary_path = (
        root / "artifacts/patterns/pattern_a/production/scanner"
        / f"pattern_a_universe_scan_{dt_clean}_summary.json"
    )
    if not summary_path.exists():
        raise Phase4CError(f"PHASE4C_SCANNER_SUMMARY_MISSING: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("requested_as_of") != target_as_of:
        raise Phase4CError(
            f"PHASE4C_SCANNER_REQUESTED_AS_OF_MISMATCH: expected {target_as_of}, "
            f"got {summary.get('requested_as_of')!r}"
        )
    reference_market_date = summary.get("reference_market_date")
    if not reference_market_date:
        raise Phase4CError("PHASE4C_SCANNER_REFERENCE_MARKET_DATE_MISSING")
    if str(reference_market_date) > target_as_of:
        raise Phase4CError(
            f"PHASE4C_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET: {reference_market_date} > {target_as_of}"
        )
    return summary


# --------------------------------------------------------------------------
# Basic Info name-authority directory 선택 (Sector RS 이름 결합용, 표시 전용)
# --------------------------------------------------------------------------


def resolve_basic_info_dir(root: Path, target_as_of: str) -> Path:
    """target_as_of 이하(과거 또는 동일) 가장 최신 basic_info snapshot을 선택한다.
    이름 표시 전용이며 종목 멤버십/state 판정에는 쓰이지 않는다.

    PHASE4C_FINAL_FIX_V01: target_as_of 이전/동일 snapshot이 하나도 없으면
    미래 snapshot으로 대체(fallback)하지 않고 fail-closed한다 -- 표시용이라도
    미래 정보를 과거 기준일에 역적용하지 않는다는 Strict PIT 원칙은 그대로
    지킨다."""
    basic_info_root = root / DEFAULT_BASIC_INFO_RAW_ROOT
    target_clean = target_as_of.replace("-", "")
    all_dirs = sorted((p for p in basic_info_root.glob("*/*") if p.is_dir()), key=lambda p: p.name)
    if not all_dirs:
        raise Phase4CError(f"PHASE4C_BASIC_INFO_DIR_NOT_FOUND: no snapshot under {basic_info_root}")
    past_dirs = [p for p in all_dirs if p.name <= target_clean]
    if not past_dirs:
        raise Phase4CError(
            f"PHASE4C_BASIC_INFO_NO_SNAPSHOT_ON_OR_BEFORE_TARGET: target={target_as_of}, "
            f"earliest available={all_dirs[0].name}"
        )
    return past_dirs[-1]


# --------------------------------------------------------------------------
# 4B exact-target report corpus 최소 검증 (build_web_payload가 상세 검증하므로
# 여기서는 존재 여부와 개수만 선제 확인)
# --------------------------------------------------------------------------


def validate_report_corpus_directory(root: Path, target_as_of: str) -> tuple[Path, int]:
    dt_clean = target_as_of.replace("-", "")
    report_dir = root / "artifacts/reporting/stock_reports" / dt_clean
    json_dir = report_dir / "json"
    if not report_dir.is_dir() or not json_dir.is_dir():
        raise Phase4CError(f"PHASE4C_REPORT_CORPUS_MISSING: {report_dir}")
    count = len(list(json_dir.glob("*.json")))
    if count == 0:
        raise Phase4CError(f"PHASE4C_REPORT_CORPUS_EMPTY: {report_dir}")
    return report_dir, count


# --------------------------------------------------------------------------
# 임시 stock-index/stocks payload 기록 (web/data가 아닌 TemporaryDirectory에만)
# --------------------------------------------------------------------------


def write_temp_stock_report_payload(
    staging_dir: Path, index: dict[str, Any], reports: dict[str, dict[str, Any]],
) -> tuple[Path, Path]:
    index_path = staging_dir / "stock-index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    stocks_dir = staging_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    for ticker, report in reports.items():
        (stocks_dir / f"{ticker}.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return index_path, stocks_dir


# --------------------------------------------------------------------------
# web/data 무변경 확인
# --------------------------------------------------------------------------


def snapshot_web_data(root: Path) -> dict[str, tuple[float, int]]:
    web_data_dir = root / "web/data"
    if not web_data_dir.exists():
        return {}
    return {
        str(p.relative_to(web_data_dir)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in web_data_dir.rglob("*") if p.is_file()
    }


# --------------------------------------------------------------------------
# 메인 오케스트레이션
# --------------------------------------------------------------------------


def run_phase4c(
    target_as_of: str,
    root: Path = ROOT,
    *,
    b_select_status_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    web_data_before = snapshot_web_data(root)

    # 1~2. exact target/reference 확정
    scanner_summary = load_scanner_summary(root, target_as_of)
    reference_market_date = str(scanner_summary["reference_market_date"])

    # 3. 4B exact-target report corpus 존재 확인 (상세 검증은 build_web_payload가 수행)
    report_dir, report_json_count = validate_report_corpus_directory(root, target_as_of)

    with tempfile.TemporaryDirectory(prefix=".phase4c-payload-") as tmp_name:
        staging_dir = Path(tmp_name)

        # 4. Stock Report web payload
        index, reports, stock_report_stats = stock_report_web.build_web_payload(
            root,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
            include_etf=True,
        )
        stock_report_tickers = {
            ticker for ticker, report in reports.items()
            if (report.get("identity") or {}).get("asset_type") == "COMMON"
        }
        etf_report_tickers = set(reports) - stock_report_tickers
        temp_index_path, temp_stocks_dir = write_temp_stock_report_payload(staging_dir, index, reports)

        stock_index_available = {
            str(item["ticker"]) for item in index["items"]
            if item.get("report_available") is True and item.get("asset_type") == "COMMON"
        }

        # 5. Market RS
        market_ranking = market_ranking_web.build_market_ranking(
            index_path=temp_index_path, stocks_dir=temp_stocks_dir,
        )
        market_ranking_tickers = {str(item["ticker"]) for item in market_ranking["items"]}
        if market_ranking.get("requested_as_of") != target_as_of:
            raise Phase4CError(
                f"PHASE4C_MARKET_RS_REQUESTED_AS_OF_MISMATCH: {market_ranking.get('requested_as_of')!r}"
            )
        if market_ranking.get("reference_market_date") != reference_market_date:
            raise Phase4CError(
                f"PHASE4C_MARKET_RS_REFERENCE_MARKET_DATE_MISMATCH: {market_ranking.get('reference_market_date')!r}"
            )

        # 6. Strategy monitor
        if b_select_status_override is not None:
            b_select_status = b_select_status_override
            expected_strategy_id = _b_select_status_builder(reference_market_date).STRATEGY_ID
            if (
                b_select_status.get("strategy_id") != expected_strategy_id
                or b_select_status.get("requested_as_of") != target_as_of
                or b_select_status.get("reference_market_date") != reference_market_date
            ):
                raise Phase4CError(
                    f"PHASE4C_B_SELECT_OVERRIDE_DATE_OR_STRATEGY_MISMATCH: expected {expected_strategy_id}"
                )
        else:
            b_select_builder = _b_select_status_builder(reference_market_date)
            b_select_status = b_select_builder.build_b_select_status(
                repo_root=root,
                index_path=temp_index_path,
                stocks_path=temp_stocks_dir,
                target_as_of=target_as_of,
                reference_market_date=reference_market_date,
            )
        strategy_monitor = strategy_monitor_web.build_strategy_monitor(
            repo_root=root,
            index_path=temp_index_path,
            stocks_path=temp_stocks_dir,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
            b_select_status=b_select_status,
        )
        strategy_rows = strategy_monitor["strategies"]
        fast_strategy_id, strategy_by_id = _validate_fast_strategy_monitor(strategy_monitor, report_json_count)
        fast_replay_projection = validate_fast_full_history_projection(
            reports,
            strategy_monitor,
            fast_strategy_id,
        )
        strategy_monitor_tickers = {
            str(item["ticker"])
            for item in strategy_by_id[fast_strategy_id]["items"]
        }
        expected_b_select_id = str(b_select_status.get("strategy_id") or "")
        if expected_b_select_id not in {"PATTERN_B_SELECT_CORE_V01", "PATTERN_B_SELECT_CORE_V02"}:
            raise Phase4CError("PHASE4C_B_SELECT_STRATEGY_ID_INVALID")
        if [row["id"] for row in strategy_rows] != [
            fast_strategy_id,
            expected_b_select_id,
            "JULIA_ETF_STRATEGY_V01",
        ]:
            raise Phase4CError("PHASE4C_STRATEGY_MONITOR_STRATEGY_ID_MISMATCH")

        # 7. Sector RS ranking (exact-target Phase 3 authority)
        dt_clean = target_as_of.replace("-", "")
        sector_ranking_path = (
            root / "data/analytics/sector_rs_ranking/v01" / f"sector_rs_ranking_{dt_clean}.parquet"
        )
        sector_meta_path = (
            root / "data/analytics/sector_rs_ranking/v01" / f"sector_rs_ranking_{dt_clean}_meta.json"
        )
        if not sector_ranking_path.exists() or not sector_meta_path.exists():
            raise Phase4CError(f"PHASE4C_SECTOR_RS_AUTHORITY_MISSING: {sector_ranking_path}")
        basic_info_dir = resolve_basic_info_dir(root, target_as_of)
        sector_rs_payload = sector_rs_web.build_sector_rs_web_payload(
            ranking_path=sector_ranking_path,
            meta_path=sector_meta_path,
            basic_info_dir=basic_info_dir,
            stocks_dir=temp_stocks_dir,
            expected_as_of=reference_market_date,
            requested_as_of=target_as_of,
            reference_market_date=reference_market_date,
        )
        if sector_rs_payload.get("requested_as_of") != target_as_of:
            raise Phase4CError(
                f"PHASE4C_SECTOR_RS_REQUESTED_AS_OF_MISMATCH: {sector_rs_payload.get('requested_as_of')!r}"
            )
        if sector_rs_payload.get("reference_market_date") != reference_market_date:
            raise Phase4CError(
                f"PHASE4C_SECTOR_RS_REFERENCE_MARKET_DATE_MISMATCH: {sector_rs_payload.get('reference_market_date')!r}"
            )
        if sector_rs_payload["as_of"] != reference_market_date:
            raise Phase4CError(f"PHASE4C_SECTOR_RS_AS_OF_MISMATCH: {sector_rs_payload['as_of']!r}")
        sector_rs_mismatches = sum(
            1 for item in sector_rs_payload["items"]
            if bool(item["report_available"]) != (str(item["ticker"]) in stock_report_tickers)
        )
        if sector_rs_mismatches:
            raise Phase4CError(f"PHASE4C_SECTOR_RS_REPORT_AVAILABILITY_MISMATCH: {sector_rs_mismatches}")

        # 8. Foreign net buy ranking (exact-target Phase 3 authority)
        flow_path = (
            root / "artifacts/patterns/pattern_a/production/flow/source" / f"foreign_flow_daily_{dt_clean}.parquet"
        )
        sector_membership_effective_date, sector_membership_path = resolve_sector_membership_for_target(
            target_as_of,
            root=root,
        )
        common_authority_path = (
            root / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01"
            / f"market_rs_universe_{dt_clean}.csv"
        )
        for p in (flow_path, sector_membership_path, common_authority_path):
            if not p.exists():
                raise Phase4CError(f"PHASE4C_FOREIGN_NET_BUY_AUTHORITY_MISSING: {p}")
        foreign_net_buy = foreign_net_buy_web.build_foreign_net_buy_ranking(
            index_path=temp_index_path,
            flow_path=flow_path,
            sector_path=sector_membership_path,
            common_authority_path=common_authority_path,
            as_of=reference_market_date,
            requested_as_of=target_as_of,
            reference_market_date=reference_market_date,
            identity_as_of=target_as_of,
            repo_root=root,
        )
        if foreign_net_buy.get("requested_as_of") != target_as_of:
            raise Phase4CError(
                f"PHASE4C_FOREIGN_NET_BUY_REQUESTED_AS_OF_MISMATCH: {foreign_net_buy.get('requested_as_of')!r}"
            )
        if foreign_net_buy.get("reference_market_date") != reference_market_date:
            raise Phase4CError(
                f"PHASE4C_FOREIGN_NET_BUY_REFERENCE_MARKET_DATE_MISMATCH: "
                f"{foreign_net_buy.get('reference_market_date')!r}"
            )
        if foreign_net_buy["as_of"] != reference_market_date:
            raise Phase4CError(f"PHASE4C_FOREIGN_NET_BUY_AS_OF_MISMATCH: {foreign_net_buy['as_of']!r}")
        # stock-index는 foreign ranking의 모집단 authority가 아니라 report_available
        # 표시용일 뿐임을 명시적으로 확인한다: 모집단(items)은 common_authority_path
        # 기준이므로, 그 개수가 stock-index 크기와 다를 수 있다(정상).
        foreign_net_buy_mismatches = sum(
            1 for item in foreign_net_buy["items"]
            if bool(item["report_available"]) != (str(item["ticker"]) in stock_report_tickers)
        )
        if foreign_net_buy_mismatches:
            raise Phase4CError(f"PHASE4C_FOREIGN_NET_BUY_REPORT_AVAILABILITY_MISMATCH: {foreign_net_buy_mismatches}")

        # 9. Health/status
        health = health_web.build_health(root, target_as_of=target_as_of)
        if health["requested_as_of"] != target_as_of or health["reference_market_date"] != reference_market_date:
            raise Phase4CError("PHASE4C_HEALTH_DATE_MISMATCH")

        # 10. cross-payload 검증 (§17)
        if stock_report_tickers != stock_index_available:
            raise Phase4CError(
                f"PHASE4C_CROSS_PAYLOAD_MISMATCH[stock_index]: "
                f"missing={sorted(stock_report_tickers - stock_index_available)[:5]} "
                f"extra={sorted(stock_index_available - stock_report_tickers)[:5]}"
            )
        if stock_report_tickers != market_ranking_tickers:
            raise Phase4CError(
                f"PHASE4C_CROSS_PAYLOAD_MISMATCH[market_ranking]: "
                f"missing={sorted(stock_report_tickers - market_ranking_tickers)[:5]} "
                f"extra={sorted(market_ranking_tickers - stock_report_tickers)[:5]}"
            )
        if stock_report_tickers != strategy_monitor_tickers:
            raise Phase4CError(
                f"PHASE4C_CROSS_PAYLOAD_MISMATCH[strategy_monitor]: "
                f"missing={sorted(stock_report_tickers - strategy_monitor_tickers)[:5]} "
                f"extra={sorted(strategy_monitor_tickers - stock_report_tickers)[:5]}"
            )

    # staging_dir는 with 블록 종료와 함께 삭제됨 (검증 후 삭제)
    web_data_after = snapshot_web_data(root)
    # MINOR 1 (PHASE4C_FINAL_FIX_V01): web/data가 하나라도 바뀌면 PASS를 허용하지
    # 않는다 -- 4C는 read-only여야 하고, 실제 투영은 Phase 4D 책임이다.
    web_data_writes = require_web_data_unchanged(web_data_before, web_data_after)

    result = {
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "b_select_status_source": "CANONICAL_OVERRIDE" if b_select_status_override is not None else "PRODUCTION_BUILDER",
        "scanner_common_count": scanner_summary.get("official_common_total"),
        "stock_report": {
            "source_report_directory": stock_report_stats["source_report_directory"],
            "json_count": report_json_count,
            "universe_count": stock_report_stats["universe_count"],
            "available_report_count": len(stock_report_tickers),
        },
        "market_ranking": {
            "report_count": market_ranking["scope"]["report_count"],
        },
        "strategy_monitor": {
            "strategy_count": len(strategy_rows),
            "common_report_count": strategy_by_id[fast_strategy_id]["scope"]["report_count"],
            "fast_replay_projection": fast_replay_projection,
            "strategies": [
                {
                    "id": strategy["id"],
                    "scope_count": strategy["scope"]["report_count"],
                    "counts": strategy["counts"],
                }
                for strategy in strategy_rows
            ],
        },
        "b_select_status": {
            "status": b_select_status["status"],
            "count": b_select_status["count"],
            "counts": b_select_status["counts"],
            "evaluation_error_count": b_select_status["evaluation_error_count"],
            "date_mismatch_count": b_select_status["date_mismatch_count"],
            "network_requests": b_select_status["network_requests"],
        },
        "sector_rs_ranking": {
            "requested_as_of": sector_rs_payload.get("requested_as_of"),
            "reference_market_date": sector_rs_payload.get("reference_market_date"),
            "as_of": sector_rs_payload["as_of"],
            "population_count": sector_rs_payload["scope"]["population_count"],
            "report_available_count": sum(1 for item in sector_rs_payload["items"] if item["report_available"]),
        },
        "foreign_net_buy_ranking": {
            "requested_as_of": foreign_net_buy.get("requested_as_of"),
            "reference_market_date": foreign_net_buy.get("reference_market_date"),
            "as_of": foreign_net_buy["as_of"],
            "target_common_universe_count": foreign_net_buy["coverage"]["target_common_universe_count"],
            "flow_covered_count": foreign_net_buy["coverage"]["flow_covered_count"],
        },
        "sector_membership": {
            "effective_date": sector_membership_effective_date,
            "path": str(sector_membership_path),
        },
        "health": {
            "overall_status": health["overall_status"],
        },
        "cross_payload_validation": {
            "stock_report_ticker_count": len(stock_report_tickers),
            "etf_report_ticker_count": len(etf_report_tickers),
            "stock_index_available_count": len(stock_index_available),
            "market_ranking_ticker_count": len(market_ranking_tickers),
            "strategy_monitor_ticker_count": len(strategy_monitor_tickers),
            "sets_equal": True,
        },
        "network_calls": 0,
        "web_data_writes": web_data_writes,
        "status": "PASS",
        "_b_select_status_for_phase4d": b_select_status,
        "_strategy_monitor_for_phase4d": strategy_monitor,
        "_foreign_net_buy_for_phase4d": foreign_net_buy,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_phase4c(args.target_as_of)
    except Phase4CError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    result.pop("_b_select_status_for_phase4d", None)
    result.pop("_strategy_monitor_for_phase4d", None)
    result.pop("_foreign_net_buy_for_phase4d", None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
