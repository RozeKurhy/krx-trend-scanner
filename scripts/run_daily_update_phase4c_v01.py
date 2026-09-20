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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_daily_update_phase4c_v01")


class Phase4CError(RuntimeError):
    """Phase 4C fail-closed error (input validation, cross-payload validation)."""


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
    basic_info_root = root / "data/reference/source/history/krx_instrument_master/v01/rolling/basic_info"
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


def run_phase4c(target_as_of: str, root: Path = ROOT) -> dict[str, Any]:
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
            root, target_as_of=target_as_of, reference_market_date=reference_market_date,
        )
        stock_report_tickers = set(reports)
        temp_index_path, temp_stocks_dir = write_temp_stock_report_payload(staging_dir, index, reports)

        stock_index_available = {
            str(item["ticker"]) for item in index["items"] if item.get("report_available") is True
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
        strategy_monitor = strategy_monitor_web.build_strategy_monitor(
            index_path=temp_index_path,
            stocks_path=temp_stocks_dir,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
        )
        strategy_monitor_tickers = {str(item["ticker"]) for item in strategy_monitor["items"]}
        if strategy_monitor["scope"]["report_count"] != report_json_count:
            raise Phase4CError(
                f"PHASE4C_STRATEGY_MONITOR_REPORT_COUNT_MISMATCH: "
                f"{strategy_monitor['scope']['report_count']} != {report_json_count}"
            )
        if strategy_monitor["strategy"]["id"] != "PATTERN_A_FAST_FINAL_STRATEGY_V02":
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
        sector_membership_path = (
            root / "data/market/sector_membership/v01" / f"sector_membership_{dt_clean}.parquet"
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
    changed_paths = set(web_data_before) ^ set(web_data_after)
    changed_paths |= {k for k in web_data_before.keys() & web_data_after.keys() if web_data_before[k] != web_data_after[k]}
    web_data_writes = len(changed_paths)

    # MINOR 1 (PHASE4C_FINAL_FIX_V01): web/data가 하나라도 바뀌면 PASS를 허용하지
    # 않는다 -- 4C는 read-only여야 하고, 실제 투영은 Phase 4D 책임이다.
    if web_data_writes != 0:
        raise Phase4CError(
            f"PHASE4C_WEB_DATA_WRITE_DETECTED: {web_data_writes} path(s) changed under web/data/: "
            f"{sorted(changed_paths)[:5]}"
        )

    result = {
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "scanner_common_count": scanner_summary.get("official_common_total"),
        "stock_report": {
            "source_report_directory": stock_report_stats["source_report_directory"],
            "json_count": report_json_count,
            "universe_count": stock_report_stats["universe_count"],
            "available_report_count": stock_report_stats["available_report_count"],
        },
        "market_ranking": {
            "report_count": market_ranking["scope"]["report_count"],
        },
        "strategy_monitor": {
            "report_count": strategy_monitor["scope"]["report_count"],
            "strategy_id": strategy_monitor["strategy"]["id"],
            "counts": strategy_monitor["counts"],
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
        "health": {
            "overall_status": health["overall_status"],
        },
        "cross_payload_validation": {
            "stock_report_ticker_count": len(stock_report_tickers),
            "stock_index_available_count": len(stock_index_available),
            "market_ranking_ticker_count": len(market_ranking_tickers),
            "strategy_monitor_ticker_count": len(strategy_monitor_tickers),
            "sets_equal": True,
        },
        "network_calls": 0,
        "web_data_writes": web_data_writes,
        "status": "PASS",
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
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
