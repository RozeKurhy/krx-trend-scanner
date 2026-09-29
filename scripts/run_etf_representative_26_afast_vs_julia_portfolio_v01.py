#!/usr/bin/env python3
"""Run a fixed 26-ETF A FAST vs Julia realistic portfolio robustness study."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as v03  # noqa: E402
from scripts import run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03 as battle  # noqa: E402

OUTPUT_DIR = ROOT / "artifacts/research/etf_representative_26_afast_vs_julia_portfolio_v01"
FULL_ATTEMPT_MARKER = OUTPUT_DIR / "full_run_attempted.json"
CURRENT_UNIVERSE_PATH = ROOT / "artifacts/research/etf_current_survivors_raw_price_three_strategy_simple_backtest_v03/current_etf_universe_2026-09-29.csv"
BASELINE_DIR = ROOT / "artifacts/research/etf_v06_afast_vs_julia_realistic_portfolio_battle_v03"
BASELINE_METRICS_PATH = BASELINE_DIR / "portfolio_metrics.csv"
BASELINE_SUMMARY_PATH = BASELINE_DIR / "summary.md"
BASELINE_VALIDATION_PATH = BASELINE_DIR / "validation.json"

UNIVERSE_GROUPS: dict[str, tuple[str, ...]] = {
    "MARKET_DOMESTIC": ("069500", "229200"),
    "SECTOR_DOMESTIC": (
        "091160", "487240", "305720", "0080G0", "117700", "091170", "102970", "140700",
        "091180", "139230", "117460", "157490", "117680", "143860", "266410", "140710",
    ),
    "FOREIGN_MARKET": ("360750", "133690", "241180", "192090"),
    "COMMODITY_RESOURCE": ("0072R0", "144600", "261220", "160580"),
}
EXPECTED_NAMES: dict[str, str] = {
    "069500": "KODEX 200", "229200": "KODEX 코스닥150",
    "091160": "KODEX 반도체", "487240": "KODEX AI전력핵심설비",
    "305720": "KODEX 2차전지산업", "0080G0": "KODEX 방산TOP10",
    "117700": "KODEX 건설", "091170": "KODEX 은행", "102970": "KODEX 증권",
    "140700": "KODEX 보험", "091180": "KODEX 자동차", "139230": "TIGER 200 중공업",
    "117460": "KODEX 에너지화학", "157490": "TIGER 소프트웨어", "117680": "KODEX 철강",
    "143860": "TIGER 헬스케어", "266410": "KODEX 필수소비재", "140710": "KODEX 운송",
    "360750": "TIGER 미국S&P500", "133690": "TIGER 미국나스닥100",
    "241180": "TIGER 일본니케이225", "192090": "TIGER 차이나CSI300",
    "0072R0": "TIGER KRX금현물", "144600": "KODEX 은선물(H)",
    "261220": "KODEX WTI원유선물(H)", "160580": "TIGER 구리실물",
}
GROUP_ORDER = tuple(UNIVERSE_GROUPS)
ALL_TICKERS = tuple(ticker for group in UNIVERSE_GROUPS.values() for ticker in group)
STRATEGIES = battle.STRATEGIES
WORKERS = 10
SAMPLE_TICKERS = ("069500", "091160", "133690", "0072R0", "261220")
VERDICT_COMPLETE = "ETF_REPRESENTATIVE_26_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_COMPLETE"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fixed_ticker_set() -> set[str]:
    return set(ALL_TICKERS)


def _theoretical_initial_deployment_ceiling(
    universe_count: int = 26,
    position_cap_krw: float = battle.POSITION_CAP,
    initial_capital_krw: float = battle.INITIAL_CAPITAL,
) -> dict[str, float]:
    notional = float(universe_count) * float(position_cap_krw)
    return {
        "notional_krw": notional,
        "pct": notional / float(initial_capital_krw) * 100.0,
    }


def _expected_category(ticker: str) -> str:
    for category, tickers in UNIVERSE_GROUPS.items():
        if ticker in tickers:
            return category
    raise KeyError(f"UNKNOWN_FIXED_TICKER:{ticker}")


def _load_universe() -> list[dict[str, str]]:
    if len(ALL_TICKERS) != 26 or len(set(ALL_TICKERS)) != 26:
        raise RuntimeError("FIXED_UNIVERSE_CONSTANTS_INVALID")
    if {name: len(tickers) for name, tickers in UNIVERSE_GROUPS.items()} != {
        "MARKET_DOMESTIC": 2, "SECTOR_DOMESTIC": 16,
        "FOREIGN_MARKET": 4, "COMMODITY_RESOURCE": 4,
    }:
        raise RuntimeError("FIXED_UNIVERSE_GROUP_COUNTS_INVALID")
    if "140710" not in _fixed_ticker_set() or "경기소비재" in " ".join(EXPECTED_NAMES.values()):
        raise RuntimeError("FIXED_UNIVERSE_AUTHORITY_MISMATCH")
    if not CURRENT_UNIVERSE_PATH.is_file():
        raise RuntimeError(f"CURRENT_ETF_IDENTITY_SOURCE_MISSING:{CURRENT_UNIVERSE_PATH}")
    source = pd.read_csv(CURRENT_UNIVERSE_PATH, dtype="string")
    source["ticker"] = source["ticker"].map(v03._norm_ticker)
    if source["ticker"].duplicated().any():
        raise RuntimeError("CURRENT_ETF_IDENTITY_SOURCE_DUPLICATE_TICKER")
    by_ticker = {str(row["ticker"]): row for row in source.to_dict(orient="records")}
    unknown = sorted(_fixed_ticker_set() - set(by_ticker))
    if unknown:
        raise RuntimeError(f"FIXED_UNIVERSE_IDENTITY_MISSING:{unknown}")
    result: list[dict[str, str]] = []
    for ticker in ALL_TICKERS:
        source_row = by_ticker[ticker]
        name = str(source_row["name"])
        isu_cd = str(source_row["isu_cd"])
        listing_date = pd.Timestamp(source_row["listing_date"]).strftime("%Y-%m-%d")
        if name != EXPECTED_NAMES[ticker] or not isu_cd or listing_date == "NaT":
            raise RuntimeError(f"FIXED_UNIVERSE_SOURCE_IDENTITY_MISMATCH:{ticker}")
        result.append({
            "ticker": ticker,
            "ISU_CD": isu_cd,
            "name": name,
            "listing_date": listing_date,
            "category": _expected_category(ticker),
            "selection_authority": "USER_FIXED_REPRESENTATIVE_26_2026-09-23",
        })
    return result


def _fixed_universe_frame(universe: Sequence[Mapping[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(universe, columns=[
        "ticker", "ISU_CD", "name", "listing_date", "category", "selection_authority",
    ])


def _common_start_from_result(result: Mapping[str, Any]) -> str | None:
    values = [
        result.get("listing_anniversary_ready_date"), result.get("a_fast_ready_date"),
        result.get("julia_ready_date"), result.get("volume_20d_ready_date"),
    ]
    cleaned = [battle._clean_date(value) for value in values]
    if any(value is None for value in cleaned):
        return None
    return max(value for value in cleaned if value is not None)


def _normal_non_evaluable(result: Mapping[str, Any]) -> bool:
    if result.get("status") != "NOT_EVALUABLE" or result.get("errors"):
        return False
    reasons = set(str(result.get("reason") or "").split(";"))
    return bool(reasons) and reasons.issubset({
        "LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF", "COMMON_START_AFTER_CUTOFF",
        "A_FAST_JULIA_NOT_READY_BY_CUTOFF",
    })


def _run_workers(
    instruments: Sequence[dict[str, str]], data_info: Mapping[str, Any], db_path: Path,
    *, worker_count: int, label: str,
) -> list[dict[str, Any]]:
    score, stage = v03._read_contracts()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=v03._init_worker,
        initargs=(str(db_path), score, stage, data_info["calendar_dates_internal"], data_info["month_ends_internal"]),
    ) as pool:
        futures = {pool.submit(battle._worker_process_instrument, item): item for item in instruments}
        for finished, future in enumerate(as_completed(futures), 1):
            instrument = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    **instrument, "status": "ERROR", "reason": "WORKER_EXCEPTION",
                    "common_evaluable_start": None,
                    "trades": {strategy: [] for strategy in STRATEGIES},
                    "errors": [f"{type(exc).__name__}:{str(exc)[:500]}"],
                    "missing_session_count": 0,
                })
            if finished % 5 == 0 or finished == len(instruments):
                print(f"{label} {finished}/{len(instruments)} ETFs", flush=True)
    return sorted(results, key=lambda row: str(row.get("ticker", "")))


def _cost_contract_sample() -> dict[str, Any]:
    expected = {
        "buy_fee_rate": 0.00015,
        "sell_fee_rate": 0.00015,
        "buy_slippage_rate": 0.001,
        "sell_slippage_rate": 0.001,
        "ETF_sell_tax_rate": 0.0,
    }
    actual = {
        "buy_fee_rate": battle.BUY_FEE_RATE,
        "sell_fee_rate": battle.SELL_FEE_RATE,
        "buy_slippage_rate": battle.BUY_SLIPPAGE_RATE,
        "sell_slippage_rate": battle.SELL_SLIPPAGE_RATE,
        "ETF_sell_tax_rate": battle.ETF_SELL_TAX_RATE,
    }
    constants_match = actual == expected
    buy = battle._buy_sizing(10_000.0, 10_000_000.0)
    sell = battle._sell_proceeds(10_000.0, 100)
    formulas_match = (
        math.isclose(float(buy["fill_price"]), 10_010.0, rel_tol=0, abs_tol=1e-9)
        and float(buy["notional"]) <= battle.POSITION_CAP
        and math.isclose(float(buy["fee"]), float(buy["notional"]) * expected["buy_fee_rate"], rel_tol=0, abs_tol=1e-9)
        and math.isclose(float(sell["fill_price"]), 9_990.0, rel_tol=0, abs_tol=1e-9)
        and math.isclose(float(sell["fee"]), float(sell["notional"]) * expected["sell_fee_rate"], rel_tol=0, abs_tol=1e-9)
        and sell["tax"] == 0.0
    )
    return {"expected": expected, "actual": actual, "constants_match": constants_match,
            "formula_sample": {"buy": buy, "sell": sell}, "formulas_match": formulas_match,
            "passed": constants_match and formulas_match}


def _run_sample(
    universe: Sequence[dict[str, str]], data_info: Mapping[str, Any], db_path: Path,
) -> dict[str, Any]:
    by_ticker = {row["ticker"]: dict(row) for row in universe}
    sample = [by_ticker[ticker] for ticker in SAMPLE_TICKERS]
    outcomes = _run_workers(sample, data_info, db_path, worker_count=len(sample), label="Representative-26 sample")
    outcome_by_ticker = {str(row["ticker"]): row for row in outcomes}
    daily_frames = battle._load_daily_frames(db_path, SAMPLE_TICKERS)
    raw_no_trade_counts: dict[str, int] = {}
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        for ticker in SAMPLE_TICKERS:
            raw = pd.read_sql_query(
                "SELECT date,open,high,low,close,volume FROM bars WHERE ticker=? ORDER BY date",
                connection, params=(ticker,),
            )
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.set_index("date").sort_index()
            raw = raw.loc[raw.index >= pd.Timestamp(by_ticker[ticker]["listing_date"])]
            raw_no_trade_counts[ticker] = int(battle.strict_no_trade_mask(raw).sum())
    checks: list[dict[str, Any]] = []
    for ticker in SAMPLE_TICKERS:
        result = outcome_by_ticker[ticker]
        expected_start = _common_start_from_result(result)
        daily = daily_frames[ticker]
        raw_no_trade_count = raw_no_trade_counts[ticker]
        no_trade_count_matches = raw_no_trade_count == int(result.get("strict_no_trade_rows_excluded", -1))
        formula_matches = expected_start == battle._clean_date(result.get("common_evaluable_start"))
        normal_status = result.get("status") == "EVALUABLE" or _normal_non_evaluable(result)
        trade_rows = [trade for strategy in STRATEGIES for trade in result.get("trades", {}).get(strategy, [])]
        price_source_ok = all(trade.get("price_source") == v03.DATA_SOURCE for trade in trade_rows)
        execution_contract_ok = not any(
            str(error).startswith(("EXECUTION_TIMING_MISMATCH", "EXECUTION_PRICE_MISMATCH", "TERMINAL_CUTOFF_PRICE_MISMATCH"))
            for error in result.get("errors", [])
        )
        no_trade_contract_ok = int(result.get("no_trade_rows_in_technical_input", -1)) == 0 and no_trade_count_matches
        passes = bool(
            result.get("errors") == [] and normal_status and formula_matches and price_source_ok
            and execution_contract_ok and no_trade_contract_ok
            and result.get("has_exact_cutoff_close") is True
            and result.get("has_exact_support_open") is True
            and int(result.get("missing_session_count", -1)) == 0
        )
        checks.append({
            "ticker": ticker, "name": result.get("name"), "category": result.get("category"),
            "status": result.get("status"), "reason": result.get("reason"),
            "listing_date": result.get("listing_date"),
            "common_evaluable_start": result.get("common_evaluable_start"),
            "listing_anniversary_ready_date": result.get("listing_anniversary_ready_date"),
            "a_fast_ready_date": result.get("a_fast_ready_date"),
            "julia_ready_date": result.get("julia_ready_date"),
            "volume_20d_ready_date": result.get("volume_20d_ready_date"),
            "eligible_signal_date_count": result.get("eligible_signal_date_count"),
            "trade_counts": {strategy: len(result.get("trades", {}).get(strategy, [])) for strategy in STRATEGIES},
            "strict_no_trade_rows_excluded": result.get("strict_no_trade_rows_excluded"),
            "raw_no_trade_rows_seen": raw_no_trade_count,
            "technical_input_no_trade_rows": result.get("no_trade_rows_in_technical_input"),
            "exact_cutoff_close": result.get("has_exact_cutoff_close"),
            "exact_support_open": result.get("has_exact_support_open"),
            "raw_session_gaps": result.get("missing_session_count"),
            "errors": result.get("errors", []),
            "checks": {
                "common_start_formula": formula_matches,
                "normal_evaluable_status": normal_status,
                "raw_prices_and_execution": execution_contract_ok and price_source_ok,
                "no_trade_session_policy": no_trade_contract_ok,
            },
            "pass": passes,
        })
    cost_sample = _cost_contract_sample()
    passed = len(checks) == len(SAMPLE_TICKERS) and all(row["pass"] for row in checks) and cost_sample["passed"]
    return {
        "verdict": "SAMPLE_PASS" if passed else "CHECK_REQUIRED",
        "sample_count": len(checks), "worker_count": len(sample),
        "sample_tickers": checks, "cost_slippage_contract": cost_sample,
        "validation_passed": passed,
    }


def _candidate_ledger_frame(results: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    category_by_ticker = {str(row["ticker"]): str(row["category"]) for row in results}
    for result in results:
        ticker = str(result["ticker"])
        for strategy in STRATEGIES:
            for trade in result.get("trades", {}).get(strategy, []):
                row = dict(trade)
                row["category"] = category_by_ticker[ticker]
                row["fixed_universe_group"] = category_by_ticker[ticker]
                row["common_start_group"] = "REPRESENTATIVE_26"
                details = row.get("source_signal_details")
                row["source_signal_details"] = json.dumps(details, ensure_ascii=False, sort_keys=True) if isinstance(details, Mapping) else details
                rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame.sort_values(["strategy_id", "signal_date", "ticker", "ISU_CD", "entry_execution_date"], kind="mergesort", inplace=True)
    else:
        frame = pd.DataFrame(columns=[
            "strategy_id", "ticker", "name", "ISU_CD", "signal_date", "entry_execution_date",
            "trade_status", "category", "fixed_universe_group", "common_start_group",
        ])
    return frame.reset_index(drop=True)


def _save_candidate_lifecycle(results: Sequence[Mapping[str, Any]], universe: Sequence[Mapping[str, str]], sample: Mapping[str, Any], lifecycle_seconds: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    ledger = _candidate_ledger_frame(results)
    ledger_path = OUTPUT_DIR / "candidate_trade_ledger.csv"
    ledger.to_csv(ledger_path, index=False, lineterminator="\n")
    status_counts = Counter(str(row.get("status")) for row in results)
    worker_errors = [
        {"ticker": row.get("ticker"), "status": row.get("status"), "reason": row.get("reason"), "errors": row.get("errors", [])}
        for row in results if row.get("status") == "ERROR" or row.get("errors")
    ]
    trades_by_strategy = {strategy: int(ledger["strategy_id"].eq(strategy).sum()) if not ledger.empty else 0 for strategy in STRATEGIES}
    candidate_tickers = battle._portfolio_price_universe(ledger.to_dict(orient="records"))
    per_etf = [{
        key: result.get(key) for key in (
            "ticker", "name", "category", "listing_date", "status", "reason", "common_evaluable_start",
            "listing_anniversary_ready_date", "a_fast_ready_date", "julia_ready_date", "volume_20d_ready_date",
            "eligible_signal_date_count", "strict_no_trade_rows_excluded", "no_trade_rows_in_technical_input",
            "has_exact_cutoff_close", "has_exact_support_open", "missing_session_count",
        )
    } | {"trade_counts": {strategy: len(result.get("trades", {}).get(strategy, [])) for strategy in STRATEGIES}}
        for result in results]
    summary = {
        "verdict": "CANDIDATE_LIFECYCLE_SAVED", "sealed": True,
        "sealed_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "candidate_trade_ledger_sha256": battle._sha256(ledger_path),
        "authority_universe_ticker_count": len(universe), "lifecycle_result_count": len(results),
        "lifecycle_status_counts": dict(sorted(status_counts.items())),
        "candidate_worker_error_count": len(worker_errors), "candidate_worker_errors": worker_errors,
        "candidate_trade_count": int(len(ledger)), "candidate_trade_count_by_strategy": trades_by_strategy,
        "candidate_ticker_count": len(candidate_tickers), "candidate_tickers": candidate_tickers,
        "candidate_status_counts": dict(sorted(Counter(ledger.get("trade_status", pd.Series(dtype=str)).astype(str)).items())),
        "fixed_universe_group_counts": {category: len(tickers) for category, tickers in UNIVERSE_GROUPS.items()},
        "sample_verdict": sample.get("verdict"), "worker_count": WORKERS,
        "candidate_lifecycle_attempt_count": 1, "lifecycle_wall_seconds": round(lifecycle_seconds, 3),
        "per_etf_readiness_and_status": per_etf,
    }
    _write_json(OUTPUT_DIR / "candidate_summary.json", summary)
    marker = _read_json(FULL_ATTEMPT_MARKER)
    marker.update({
        "candidate_ledger_sealed": True, "candidate_ledger_sealed_at": summary["sealed_at"],
        "candidate_trade_ledger_sha256": summary["candidate_trade_ledger_sha256"],
        "candidate_trade_count": summary["candidate_trade_count"],
        "candidate_ticker_count": summary["candidate_ticker_count"],
    })
    _write_json(FULL_ATTEMPT_MARKER, marker)
    return ledger, summary


def _group_contribution(strategy: str, ledger: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in GROUP_ORDER:
        group = ledger.loc[ledger["category"].eq(category)] if not ledger.empty else ledger
        filled = group.loc[group["entry_status"].eq("FILLED")] if not group.empty else group
        realized = filled.loc[filled["exit_status"].eq("FILLED")] if not filled.empty else filled
        returns = pd.to_numeric(realized.get("realized_net_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        rows.append({
            "strategy_id": strategy, "category": category,
            "candidate_trades": int(len(group)), "filled_trades": int(len(filled)),
            "realized_trades": int(len(realized)),
            "realized_positive_rate_pct": float((returns > 0).mean() * 100) if len(returns) else None,
            "median_net_return_pct": float(returns.median()) if len(returns) else None,
            "realized_pnl_contribution_krw": float(pd.to_numeric(realized.get("realized_pnl_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        })
    return rows


def _comparison_vs_v03(metrics_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    for path in (BASELINE_METRICS_PATH, BASELINE_SUMMARY_PATH, BASELINE_VALIDATION_PATH):
        if not path.is_file():
            raise RuntimeError(f"V03_427_BASELINE_MISSING:{path}")
    baseline_validation = _read_json(BASELINE_VALIDATION_PATH)
    if baseline_validation.get("passed") is not True:
        raise RuntimeError("V03_427_BASELINE_VALIDATION_NOT_PASSED")
    baseline = pd.read_csv(BASELINE_METRICS_PATH)
    baseline_by_strategy = {str(row["strategy_id"]): row for row in baseline.to_dict(orient="records")}
    current_by_strategy = {str(row["strategy_id"]): row for row in metrics_rows}
    if set(baseline_by_strategy) != set(STRATEGIES) or set(current_by_strategy) != set(STRATEGIES):
        raise RuntimeError("V03_427_BASELINE_STRATEGY_SET_MISMATCH")
    pairs = (
        ("final_equity_krw", "final_equity_krw"), ("CAGR_pct", "CAGR_pct"),
        ("mdd_pct", "mdd_pct"), ("average_invested_ratio_pct", "average_invested_ratio_pct"),
        ("average_cash_ratio_pct", "average_cash_ratio_pct"),
        ("realized_positive_rate_pct", "realized_positive_rate_pct"),
        ("realized_median_return_pct", "realized_median_return_pct"),
        ("median_holding_sessions", "median_holding_sessions"),
    )
    result: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        old, new = baseline_by_strategy[strategy], current_by_strategy[strategy]
        row: dict[str, Any] = {"strategy_id": strategy, "v03_427_run_status": old.get("run_status"), "v01_26_run_status": new.get("run_status")}
        for field, source_field in pairs:
            old_value, new_value = old.get(source_field), new.get(source_field)
            row[f"v03_427_{field}"] = old_value
            row[f"v01_26_{field}"] = new_value
            if old_value is not None and new_value is not None and not pd.isna(old_value) and not pd.isna(new_value):
                row[f"delta_26_minus_427_{field}"] = float(new_value) - float(old_value)
            else:
                row[f"delta_26_minus_427_{field}"] = None
        row["interpretation_note"] = "26-ETF theoretical initial deployment ceiling is 65%; 427 has no same structural cap. Equity/CAGR differences include universe capacity."
        result.append(row)
    return result


def _write_check_required_outputs(
    universe: Sequence[Mapping[str, str]], reason: str, sample: Mapping[str, Any] | None = None,
    candidate_summary: Mapping[str, Any] | None = None, validation: Mapping[str, Any] | None = None,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _fixed_universe_frame(universe).to_csv(OUTPUT_DIR / "fixed_universe.csv", index=False, lineterminator="\n")
    if not (OUTPUT_DIR / "candidate_trade_ledger.csv").exists():
        pd.DataFrame(columns=["strategy_id", "ticker", "ISU_CD", "signal_date", "entry_execution_date", "trade_status", "category"]).to_csv(
            OUTPUT_DIR / "candidate_trade_ledger.csv", index=False, lineterminator="\n")
    if candidate_summary is None and not (OUTPUT_DIR / "candidate_summary.json").exists():
        _write_json(OUTPUT_DIR / "candidate_summary.json", {"verdict": "CANDIDATE_LIFECYCLE_NOT_RUN", "sealed": False, "reason": reason})
    elif candidate_summary is not None:
        _write_json(OUTPUT_DIR / "candidate_summary.json", dict(candidate_summary))
    empty_portfolio_columns = [
        "strategy_id", "ticker", "category", "entry_status", "exit_status", "buy_notional_krw",
        "sell_notional_krw", "realized_pnl_krw", "realized_net_return_pct",
    ]
    pd.DataFrame(columns=empty_portfolio_columns).to_csv(OUTPUT_DIR / "portfolio_trade_ledger.csv", index=False, lineterminator="\n")
    pd.DataFrame(columns=["date", "strategy_id", "cash", "invested_market_value", "total_equity", "open_positions"]).to_csv(OUTPUT_DIR / "equity_curve.csv", index=False, lineterminator="\n")
    pd.DataFrame([{"strategy_id": strategy, "run_status": "NOT_COMPLETED", "reason": reason} for strategy in STRATEGIES]).to_csv(OUTPUT_DIR / "portfolio_metrics.csv", index=False, lineterminator="\n")
    pd.DataFrame([{"strategy_id": strategy, "run_status": "NOT_COMPLETED", "reason": reason} for strategy in STRATEGIES]).to_csv(OUTPUT_DIR / "execution_summary.csv", index=False, lineterminator="\n")
    pd.DataFrame(columns=["strategy_id", "year", "year_label", "return_pct"]).to_csv(OUTPUT_DIR / "annual_returns.csv", index=False, lineterminator="\n")
    pd.DataFrame(columns=["strategy_id", "category", "candidate_trades", "filled_trades", "realized_trades"]).to_csv(OUTPUT_DIR / "group_contribution.csv", index=False, lineterminator="\n")
    pd.DataFrame(columns=["strategy_id", "v03_427_final_equity_krw", "v01_26_final_equity_krw"]).to_csv(OUTPUT_DIR / "comparison_vs_v03_427.csv", index=False, lineterminator="\n")
    if validation is None:
        validation = {"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": reason}
    _write_json(OUTPUT_DIR / "validation.json", {**dict(validation), "verdict": "CHECK_REQUIRED", "passed": False})
    if sample is not None:
        _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
    (OUTPUT_DIR / "summary.md").write_text(
        "# ETF 대표 26 A FAST vs Julia 현실 포트폴리오 V01 — CHECK_REQUIRED\n\n"
        f"- 차단 사유: `{reason}`\n- 표본 결과: `{(sample or {}).get('verdict', 'NOT_RUN')}`\n"
        "- 전체 포트폴리오 지표는 완료되지 않았어. 세부 정보는 validation.json과 preflight_sample.json을 확인해.\n",
        encoding="utf-8",
    )


def _raw_authorities(data_info: Mapping[str, Any], raw_audit: Mapping[str, Any]) -> dict[str, Any]:
    score_path = ROOT / v03.SCORE_CONTRACT_REL
    stage_path = ROOT / v03.STAGE_CONTRACT_REL
    return {
        "fixed_selection_authority": "User-provided fixed 26-ETF list in w.md (2026-09-23 snapshot); not dynamically reselected.",
        "identity_and_listing_source": str(CURRENT_UNIVERSE_PATH.relative_to(ROOT)),
        "price_source": v03.DATA_SOURCE, "raw_price_limitation": True, "survivorship_bias": True,
        "raw_store_relative_path": str(v03.RAW_STORE_REL),
        "raw_store_manifest_sha256": data_info.get("source_store_manifest_sha256"),
        "krx_calendar_sha256": data_info.get("krx_calendar_sha256"),
        "score_contract_sha256": v03._sha256(score_path), "stage_contract_sha256": v03._sha256(stage_path),
        "strategy_ids": list(STRATEGIES), "existing_v03_427_baseline_replayed": False,
        "v03_427_summary_path": str(BASELINE_SUMMARY_PATH.relative_to(ROOT)),
        "v03_427_metrics_sha256": battle._sha256(BASELINE_METRICS_PATH),
        "raw_data_audit": dict(raw_audit),
    }


def _write_completed_outputs(
    universe: Sequence[Mapping[str, str]], sample: Mapping[str, Any], validation: Mapping[str, Any],
    portfolios: Mapping[str, Mapping[str, Any]], raw_authorities: Mapping[str, Any],
    runtime: Mapping[str, Any], comparison_rows: Sequence[Mapping[str, Any]],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _fixed_universe_frame(universe).to_csv(OUTPUT_DIR / "fixed_universe.csv", index=False, lineterminator="\n")
    portfolio_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []
    metrics_rows: list[dict[str, Any]] = []
    execution_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        portfolio = portfolios[strategy]
        ledger = portfolio["ledger"].copy()
        if "source_signal_details" in ledger.columns:
            ledger["source_signal_details"] = ledger["source_signal_details"].map(
                lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, Mapping) else value
            )
        portfolio_frames.append(ledger)
        curve_frames.append(portfolio["curve"])
        metrics = dict(portfolio["summary"])
        metrics_rows.append(metrics)
        execution_rows.append({
            "strategy_id": strategy, "run_status": metrics["run_status"],
            "candidate_entries": metrics["candidate_entry_signals"], "filled_entries": metrics["filled_entries"],
            "CASH_SKIP": metrics["CASH_SKIP"], "open_position_skip": metrics["open_position_skip"],
            "total_exits": metrics["total_exits"], "terminal_positions": metrics["terminal_positions"],
            "fill_rate_pct": metrics["fill_rate_pct"],
        })
        group_rows.extend(_group_contribution(strategy, ledger))
        annual_rows.extend({"strategy_id": strategy, **row} for row in battle._annual_returns(portfolio["curve"]))
    pd.concat(portfolio_frames, ignore_index=True).to_csv(OUTPUT_DIR / "portfolio_trade_ledger.csv", index=False, lineterminator="\n")
    pd.concat(curve_frames, ignore_index=True).to_csv(OUTPUT_DIR / "equity_curve.csv", index=False, lineterminator="\n")
    pd.DataFrame(metrics_rows).to_csv(OUTPUT_DIR / "portfolio_metrics.csv", index=False, lineterminator="\n")
    pd.DataFrame(execution_rows).to_csv(OUTPUT_DIR / "execution_summary.csv", index=False, lineterminator="\n")
    pd.DataFrame(annual_rows).to_csv(OUTPUT_DIR / "annual_returns.csv", index=False, lineterminator="\n")
    pd.DataFrame(group_rows).to_csv(OUTPUT_DIR / "group_contribution.csv", index=False, lineterminator="\n")
    pd.DataFrame(comparison_rows).to_csv(OUTPUT_DIR / "comparison_vs_v03_427.csv", index=False, lineterminator="\n")
    _write_json(OUTPUT_DIR / "validation.json", validation)
    _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
    _write_json(OUTPUT_DIR / "source_authorities.json", {**dict(raw_authorities), "runtime": dict(runtime), "verdict": validation["verdict"]})
    comparison_by_strategy = {str(row["strategy_id"]): row for row in comparison_rows}
    lines = [
        "# ETF 대표 26 A FAST vs Julia 현실 포트폴리오 V01", "",
        f"- Verdict: `{validation['verdict']}`", "- Universe: 사용자 고정 대표 ETF 26개; 현재 대표 ETF 고정 목록이라 survivorship bias가 있어.",
        "- 데이터: KRX raw OHLCV; RAW_PRICE_LIMITATION=TRUE; adjusted price 사용 안 함.",
        f"- 기간: {battle.GLOBAL_START.date()} ~ {battle.CUTOFF.date()} (체결 지원 {battle.EXECUTION_SUPPORT.date()}).",
        f"- 표본: {sample['verdict']} ({sample['sample_count']}개); 전체 candidate worker {WORKERS}개.",
        "- 포트폴리오: 초기 2억원, 종목당 최대 500만원, 정수 수량, 무레버리지, 현금 부족 시 CASH_SKIP, 동시 보유 제한 없음.",
        "- 비용: 매수·매도 수수료 각 0.015%; 매수 슬리피지 +0.1%, 매도 -0.1%; ETF 매도세 0%.",
        "- 고정 universe 최초 notional 상한: 26 × 500만원 = 1억3천만원, 초기자본의 65%. 계좌자산이 커지면 실질 상한 비율은 더 낮아질 수 있어.",
        "- 427개 V03의 최초 투자비중에는 이와 같은 65% 구조 상한이 없어. 최종자산/CAGR 차이는 universe와 자본 활용 차이도 포함해.",
        "- 427개 V03은 기존 committed 산출물만 읽었고 재실행하지 않았어.", "",
        "## 포트폴리오 결과", "",
        "| 전략 | 최종자산 | 총수익률 | CAGR | MDD | 평균 투자비중 | 평균 현금비중 | 실현 승률 | 실현 중앙값 | 중앙 보유 세션 | CASH_SKIP | 체결률 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics_rows:
        lines.append(
            f"| {row['strategy_id']} | {row['final_equity_krw']:,.0f}원 | {row['total_return_pct']:.2f}% | {row['CAGR_pct']:.2f}% | {row['mdd_pct']:.2f}% | "
            f"{row['average_invested_ratio_pct']:.2f}% | {row['average_cash_ratio_pct']:.2f}% | {row['realized_positive_rate_pct'] if row['realized_positive_rate_pct'] is not None else float('nan'):.2f}% | "
            f"{row['realized_median_return_pct'] if row['realized_median_return_pct'] is not None else float('nan'):.2f}% | {row['median_holding_sessions']} | {row['CASH_SKIP']} | {row['fill_rate_pct']:.2f}% |"
        )
    lines += ["", "## 기존 V03 427과 비교", "", "| 전략 | 지표 | V03 427 | 대표 26 | 26−427 |", "|---|---|---:|---:|---:|"]
    compare_fields = (
        ("final_equity_krw", "최종자산", "원"), ("CAGR_pct", "CAGR", "%"), ("mdd_pct", "MDD", "%"),
        ("average_invested_ratio_pct", "평균 투자비중", "%"), ("average_cash_ratio_pct", "평균 현금비중", "%"),
        ("realized_positive_rate_pct", "실현 승률", "%"), ("realized_median_return_pct", "실현 중앙값", "%"),
        ("median_holding_sessions", "중앙 보유 세션", "세션"),
    )
    for strategy in STRATEGIES:
        comp = comparison_by_strategy[strategy]
        for field, label, unit in compare_fields:
            old, new, delta = (comp.get(f"v03_427_{field}"), comp.get(f"v01_26_{field}"), comp.get(f"delta_26_minus_427_{field}"))
            if unit == "원":
                fmt = lambda value: "n/a" if value is None or pd.isna(value) else f"{float(value):,.0f}"
            else:
                fmt = lambda value: "n/a" if value is None or pd.isna(value) else f"{float(value):.2f}"
            lines.append(f"| {strategy} | {label} | {fmt(old)} {unit} | {fmt(new)} {unit} | {fmt(delta)} {unit} |")
    lines += ["", "## 그룹별 실현 기여", "", "| 전략 | 그룹 | candidate | 체결 | 실현 | 승률 | 실현 중앙값 | 실현 손익 기여 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in group_rows:
        win = "n/a" if row["realized_positive_rate_pct"] is None else f"{row['realized_positive_rate_pct']:.2f}%"
        median = "n/a" if row["median_net_return_pct"] is None else f"{row['median_net_return_pct']:.2f}%"
        lines.append(f"| {row['strategy_id']} | {row['category']} | {row['candidate_trades']} | {row['filled_trades']} | {row['realized_trades']} | {win} | {median} | {row['realized_pnl_contribution_krw']:,.0f}원 |")
    lines += ["", "## 비평가 종목", ""]
    non_evaluable = [row for row in validation.get("non_evaluable_etfs", [])]
    lines.extend([f"- `{row['ticker']} {row['name']}`: {row['reason'] or 'unknown reason'}" for row in non_evaluable] or ["- 없음"])
    lines += [
        "", "## Validation", "", f"- 고정 목록: {validation['fixed_universe_count']}종목; 미확인/무단 ETF: {validation['unknown_etf_count']}/{validation['unauthorized_etf_count']}.",
        f"- 비평가: {validation['not_evaluable_count']}종목 (정상 분리). 원시 OHLCV 결측/세션 간격 문제는 별도 차단 조건이야.",
        f"- candidate 필요 가격 누락: {validation['candidate_required_price_missing_count']}; 음수 현금 / 레버리지 / 500만원 초과: {validation['negative_cash_count']} / {validation['leverage_usage_krw']} / {validation['position_notional_over_5m_count']}.",
        f"- cutoff 이후 진입 / 미래 날짜 fallback / nearest-date fallback: {validation['post_cutoff_new_entry_count']} / {validation['future_fallback_count']} / {validation['nearest_date_fallback_count']}.",
        f"- eligibility / 실행일 / 가격 / no-trade / same-day ordering mismatch: {validation['eligibility_mismatch_count']} / {validation['execution_timing_mismatch_count']} / {validation['execution_price_mismatch_count']} / {validation['no_trade_session_mismatch_count']} / {validation['same_day_ordering_mismatch_count']}.",
        f"- 전체 candidate replay: {validation['candidate_lifecycle_attempt_count']}회; portfolio battle: {validation['portfolio_battle_attempt_count']}회 (전략별 replay 2회).", "",
        "## 산출물", "",
    ]
    lines.extend(f"- `{name}`" for name in (
        "fixed_universe.csv", "candidate_trade_ledger.csv", "candidate_summary.json", "portfolio_trade_ledger.csv",
        "portfolio_metrics.csv", "execution_summary.csv", "equity_curve.csv", "annual_returns.csv",
        "group_contribution.csv", "comparison_vs_v03_427.csv", "validation.json", "preflight_sample.json",
    ))
    (OUTPUT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _count_errors(results: Sequence[Mapping[str, Any]], prefixes: tuple[str, ...]) -> int:
    return sum(
        1 for result in results for error in result.get("errors", [])
        if str(error).startswith(prefixes)
    )


def _build_validation(
    universe: Sequence[Mapping[str, str]], results: Sequence[Mapping[str, Any]], sample: Mapping[str, Any],
    raw_audit: Mapping[str, Any], coverage: Mapping[str, Any], portfolios: Mapping[str, Mapping[str, Any]],
    candidate_summary: Mapping[str, Any], candidate_attempts: int, portfolio_attempts: int,
) -> dict[str, Any]:
    result_tickers = [str(row.get("ticker", "")) for row in results]
    all_trades = [trade for result in results for strategy in STRATEGIES for trade in result.get("trades", {}).get(strategy, [])]
    requested = _fixed_ticker_set()
    result_set = set(result_tickers)
    unauthorized = sorted({str(row.get("ticker", "")).zfill(6) for row in all_trades} - requested)
    formula_mismatches = sum(
        1 for row in results
        if battle._clean_date(row.get("common_evaluable_start")) != _common_start_from_result(row)
    )
    non_evaluable = [
        {"ticker": row.get("ticker"), "name": row.get("name"), "reason": row.get("reason"), "common_evaluable_start": row.get("common_evaluable_start")}
        for row in results if row.get("status") == "NOT_EVALUABLE"
    ]
    portfolio_summaries = [portfolios[strategy]["summary"] for strategy in STRATEGIES]
    errors = [row for row in results if row.get("status") == "ERROR" or row.get("errors")]
    negative_cash = sum(int(row.get("negative_cash_count", 0)) for row in portfolio_summaries)
    leverage = sum(float(row.get("leverage_usage_krw", 0.0)) for row in portfolio_summaries)
    oversized = sum(int(row.get("position_notional_over_5m_count", 0)) for row in portfolio_summaries)
    ordering = sum(int(row.get("same_day_ordering_mismatch_count", 0)) for row in portfolio_summaries)
    post_cutoff = max(
        sum(1 for trade in all_trades if (battle._clean_date(trade.get("entry_execution_date")) or "") > battle.CUTOFF.strftime("%Y-%m-%d")),
        sum(int(row.get("post_cutoff_new_entry_count", 0)) for row in portfolio_summaries),
    )
    non_evaluable_invalid = [row for row in results if row.get("status") == "NOT_EVALUABLE" and not _normal_non_evaluable(row)]
    identity_unknown_count = max(0, 26 - len(universe))
    deployment_ceiling = _theoretical_initial_deployment_ceiling(len(universe))
    passed = bool(
        len(universe) == 26 and len(result_tickers) == 26 and len(set(result_tickers)) == 26 and result_set == requested
        and not errors and not unauthorized and formula_mismatches == 0 and not non_evaluable_invalid
        and sample.get("validation_passed") is True and raw_audit.get("other_invalid_ohlc_rows") == 0
        and raw_audit.get("technical_input_no_trade_row_count") == 0
        and int(coverage.get("candidate_required_price_coverage_missing_count", -1)) == 0
        and int(coverage.get("candidate_required_raw_session_gap_count", -1)) == 0
        and int(coverage.get("price_requested_for_zero_candidate_etf_count", -1)) == 0
        and negative_cash == 0 and leverage <= 1e-7 and oversized == 0 and ordering == 0 and post_cutoff == 0
        and all(int(row.get("cash_conservation_error_count", 1)) == 0 and row.get("run_status") == "COMPLETED" for row in portfolio_summaries)
        and all(row.get("sealed") is True for row in [candidate_summary])
    )
    return {
        "verdict": VERDICT_COMPLETE if passed else "CHECK_REQUIRED", "passed": passed,
        "fixed_universe_count": len(universe), "fixed_universe_identity_count": len(result_set & requested),
        "fixed_universe_identities_exact": result_set == requested,
        "fixed_universe_group_counts": {category: len(tickers) for category, tickers in UNIVERSE_GROUPS.items()},
        "unknown_etf_count": identity_unknown_count, "unauthorized_etf_count": len(unauthorized),
        "unauthorized_etfs": unauthorized, "full_candidate_result_count": len(results),
        "duplicate_result_ticker_count": len(result_tickers) - len(set(result_tickers)),
        "missing_result_tickers": sorted(requested - result_set),
        "candidate_trade_count": len(all_trades), "candidate_trade_count_by_strategy": dict(candidate_summary.get("candidate_trade_count_by_strategy", {})),
        "candidate_lifecycle_attempt_count": candidate_attempts,
        "candidate_ledger_sealed": bool(candidate_summary.get("sealed")),
        "candidate_trade_ledger_sha256": candidate_summary.get("candidate_trade_ledger_sha256"),
        "portfolio_battle_attempt_count": portfolio_attempts,
        "portfolio_strategy_replay_count": sum(1 for row in portfolio_summaries if row.get("run_status") == "COMPLETED"),
        "sample_verdict": sample.get("verdict"), "sample_ticker_count": sample.get("sample_count"),
        "not_evaluable_count": len(non_evaluable), "non_evaluable_etfs": non_evaluable,
        "invalid_not_evaluable_count": len(non_evaluable_invalid),
        "common_start_formula_mismatch_count": formula_mismatches,
        "eligibility_mismatch_count": _count_errors(results, ("ELIGIBILITY_MISMATCH", "TRADE_CONTRACT_MISMATCH")),
        "execution_timing_mismatch_count": _count_errors(results, ("EXECUTION_TIMING_MISMATCH",)),
        "execution_price_mismatch_count": _count_errors(results, ("EXECUTION_PRICE_MISMATCH", "TERMINAL_CUTOFF_PRICE_MISMATCH", "EXACT_ENTRY_OPEN_MISMATCH", "EXACT_EXIT_OPEN_MISMATCH")),
        "terminal_contract_mismatch_count": _count_errors(results, ("OPEN_TERMINAL_HAS_EXIT_EXECUTION", "TERMINAL_CUTOFF_DATE_MISMATCH")),
        "no_trade_session_mismatch_count": max(int(raw_audit.get("technical_input_no_trade_row_count", 0)), sum(int(row.get("no_trade_rows_in_technical_input", 0)) for row in results)),
        "no_trade_session_rows_kept_in_volume_eligibility": int(raw_audit.get("strict_no_trade_session_rows", 0)),
        "raw_invalid_ohlc_count": int(raw_audit.get("other_invalid_ohlc_rows", -1)),
        "raw_rewrite_count": int(raw_audit.get("raw_rewrite_count", -1)),
        "synthetic_or_forward_filled_rows": int(raw_audit.get("synthetic_or_forward_filled_rows", -1)),
        "raw_session_gap_count": sum(int(row.get("missing_session_count", 0)) for row in results),
        "candidate_required_price_missing_count": int(coverage.get("candidate_required_price_coverage_missing_count", -1)),
        "candidate_required_price_missing": list(coverage.get("candidate_required_price_coverage_missing", [])),
        "candidate_required_raw_session_gap_count": int(coverage.get("candidate_required_raw_session_gap_count", -1)),
        "negative_cash_count": negative_cash, "leverage_usage_krw": leverage,
        "position_notional_over_5m_count": oversized, "cash_conservation_error_count": sum(int(row.get("cash_conservation_error_count", 0)) for row in portfolio_summaries),
        "same_day_ordering_mismatch_count": ordering, "post_cutoff_new_entry_count": post_cutoff,
        "future_fallback_count": 0, "nearest_date_fallback_count": 0,
        "theoretical_initial_capital_deployment_ceiling_krw": deployment_ceiling["notional_krw"],
        "theoretical_initial_capital_deployment_ceiling_pct": deployment_ceiling["pct"],
        "process_error_count": len(errors),
        "process_errors": [{"ticker": row.get("ticker"), "status": row.get("status"), "reason": row.get("reason"), "errors": row.get("errors")} for row in errors[:50]],
        "portfolio_price_coverage": dict(coverage),
        "raw_data_audit": dict(raw_audit),
    }


def _run(output: Path | None = None) -> dict[str, Any]:
    global OUTPUT_DIR, FULL_ATTEMPT_MARKER
    if output is not None:
        OUTPUT_DIR = output
        FULL_ATTEMPT_MARKER = OUTPUT_DIR / "full_run_attempted.json"
    if FULL_ATTEMPT_MARKER.exists():
        raise RuntimeError("FULL_RUN_ALREADY_ATTEMPTED_NO_AUTOMATIC_RERUN")
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise RuntimeError("OUTPUT_DIR_NOT_EMPTY_NO_OVERWRITE")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    universe = _load_universe()
    _fixed_universe_frame(universe).to_csv(OUTPUT_DIR / "fixed_universe.csv", index=False, lineterminator="\n")
    with tempfile.TemporaryDirectory(prefix="etf_rep26_raw_") as temp_dir:
        db_path = Path(temp_dir) / "raw_etf_prices.sqlite3"
        data_info = v03._build_price_database(db_path, ROOT / v03.RAW_STORE_REL, universe)
        raw_audit = battle._audit_raw_data(db_path, universe)
        if raw_audit.get("other_invalid_ohlc_rows") != 0 or raw_audit.get("technical_input_no_trade_row_count") != 0:
            validation = {"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "RAW_DATA_AUDIT", "raw_data_audit": raw_audit}
            _write_check_required_outputs(universe, "RAW_DATA_AUDIT", validation=validation)
            return {"validation": validation}
        sample = _run_sample(universe, data_info, db_path)
        _write_json(OUTPUT_DIR / "preflight_sample.json", sample)
        if not sample["validation_passed"]:
            validation = {"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "SAMPLE", "sample_verdict": sample["verdict"], "sample_ticker_count": sample["sample_count"]}
            _write_check_required_outputs(universe, "SAMPLE", sample, validation=validation)
            return {"validation": validation, "sample": sample}

        marker = {
            "attempt_started_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
            "worker_count": WORKERS, "full_run_attempt_count": 1,
            "candidate_lifecycle_attempt_count": 1, "portfolio_battle_attempt_count": 0,
            "portfolio_strategy_replay_count": 0, "sample_verdict": sample["verdict"],
            "universe_count": len(universe), "candidate_ledger_sealed": False,
        }
        _write_json(FULL_ATTEMPT_MARKER, marker)
        lifecycle_started = time.perf_counter()
        results = _run_workers(universe, data_info, db_path, worker_count=WORKERS, label="Representative-26 full lifecycle")
        lifecycle_seconds = time.perf_counter() - lifecycle_started
        candidate_ledger, candidate_summary = _save_candidate_lifecycle(results, universe, sample, lifecycle_seconds)
        all_trades = candidate_ledger.to_dict(orient="records")

        if any(row.get("status") == "ERROR" or row.get("errors") for row in results):
            coverage = {"checked": False, "candidate_trade_ticker_count": len(battle._portfolio_price_universe(all_trades)), "portfolio_price_requested_ticker_count": 0, "candidate_required_price_coverage_missing_count": 0, "candidate_required_price_coverage_missing": [], "candidate_required_raw_session_gap_count": sum(int(row.get("missing_session_count", 0)) for row in results), "price_requested_for_zero_candidate_etf_count": 0}
            portfolios = {strategy: {"ledger": pd.DataFrame(), "curve": pd.DataFrame(), "summary": {"strategy_id": strategy, "run_status": "NOT_RUN", "negative_cash_count": 0, "leverage_usage_krw": 0.0, "position_notional_over_5m_count": 0, "cash_conservation_error_count": 0, "same_day_ordering_mismatch_count": 0, "post_cutoff_new_entry_count": 0}} for strategy in STRATEGIES}
            validation = _build_validation(universe, results, sample, raw_audit, coverage, portfolios, candidate_summary, 1, 0)
            validation.update({"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "CANDIDATE_LIFECYCLE"})
            _write_check_required_outputs(universe, "CANDIDATE_LIFECYCLE", sample, candidate_summary, validation)
            return {"validation": validation, "sample": sample}

        coverage = battle._audit_candidate_price_coverage(db_path, all_trades, results, authority_universe_count=len(universe))
        if coverage["candidate_required_price_coverage_missing_count"] or coverage["candidate_required_raw_session_gap_count"]:
            portfolios = {strategy: {"ledger": pd.DataFrame(), "curve": pd.DataFrame(), "summary": {"strategy_id": strategy, "run_status": "NOT_RUN", "negative_cash_count": 0, "leverage_usage_krw": 0.0, "position_notional_over_5m_count": 0, "cash_conservation_error_count": 0, "same_day_ordering_mismatch_count": 0, "post_cutoff_new_entry_count": 0}} for strategy in STRATEGIES}
            validation = _build_validation(universe, results, sample, raw_audit, coverage, portfolios, candidate_summary, 1, 0)
            validation.update({"verdict": "CHECK_REQUIRED", "passed": False, "blocked_stage": "CANDIDATE_PRICE_COVERAGE"})
            _write_check_required_outputs(universe, "CANDIDATE_PRICE_COVERAGE", sample, candidate_summary, validation)
            return {"validation": validation, "sample": sample}

        price_tickers = battle._portfolio_price_universe(all_trades)
        daily_frames = battle._load_daily_frames(db_path, price_tickers)
        category_by_ticker = {row["ticker"]: row["category"] for row in universe}
        marker = _read_json(FULL_ATTEMPT_MARKER)
        marker["portfolio_battle_attempt_count"] = 1
        marker["portfolio_strategy_replay_count"] = len(STRATEGIES)
        marker["portfolio_started_at"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat()
        _write_json(FULL_ATTEMPT_MARKER, marker)
        portfolio_started = time.perf_counter()
        portfolios: dict[str, Any] = {}
        for strategy in STRATEGIES:
            strategy_rows = [row for row in all_trades if row.get("strategy_id") == strategy]
            portfolios[strategy] = battle._portfolio_replay(strategy_rows, daily_frames, data_info["calendar_dates_internal"], strategy, category_by_ticker)
        portfolio_seconds = time.perf_counter() - portfolio_started

        metrics_rows = [portfolios[strategy]["summary"] for strategy in STRATEGIES]
        comparison_rows = _comparison_vs_v03(metrics_rows)
        validation = _build_validation(universe, results, sample, raw_audit, coverage, portfolios, candidate_summary, 1, 1)
        runtime = {
            "raw_database_build_seconds": data_info.get("database_build_seconds"),
            "lifecycle_wall_seconds": round(lifecycle_seconds, 3),
            "portfolio_wall_seconds": round(portfolio_seconds, 3),
            "total_wall_seconds": round(time.perf_counter() - lifecycle_started, 3),
            "worker_count": WORKERS,
        }
        if not validation["passed"]:
            validation["blocked_stage"] = "FINAL_VALIDATION"
        raw_authorities = _raw_authorities(data_info, raw_audit)
        _write_completed_outputs(universe, sample, validation, portfolios, raw_authorities, runtime, comparison_rows)
        return {"validation": validation, "sample": sample, "runtime": runtime, "comparison": comparison_rows}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run sample gate and one full candidate + portfolio replay.")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    try:
        outcome = _run()
    except Exception as exc:
        marker_attempted = FULL_ATTEMPT_MARKER.exists()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        validation = {
            "verdict": "CHECK_REQUIRED", "passed": False,
            "blocked_stage": "FULL_RUN" if marker_attempted else "PREFLIGHT",
            "full_run_attempted": marker_attempted,
            "error": f"{type(exc).__name__}:{str(exc)[:500]}",
            "candidate_lifecycle_attempt_count": 1 if marker_attempted else 0,
            "portfolio_battle_attempt_count": 0,
        }
        try:
            universe = _load_universe()
        except Exception:
            universe = [
                {"ticker": ticker, "ISU_CD": "", "name": EXPECTED_NAMES[ticker], "listing_date": "", "category": _expected_category(ticker), "selection_authority": "USER_FIXED_REPRESENTATIVE_26_2026-09-23"}
                for ticker in ALL_TICKERS
            ]
        sample_path = OUTPUT_DIR / "preflight_sample.json"
        sample = _read_json(sample_path) if sample_path.is_file() else None
        candidate_summary_path = OUTPUT_DIR / "candidate_summary.json"
        candidate_summary = _read_json(candidate_summary_path) if candidate_summary_path.is_file() else None
        _write_check_required_outputs(
            universe, validation["error"], sample=sample,
            candidate_summary=candidate_summary, validation=validation,
        )
        print(json.dumps({"verdict": "CHECK_REQUIRED", "error": f"{type(exc).__name__}:{str(exc)[:300]}", "full_run_attempted": marker_attempted}, ensure_ascii=False))
        return 2
    validation = outcome["validation"]
    print(json.dumps({
        "verdict": validation["verdict"], "validation_passed": validation["passed"],
        "candidate_lifecycle_attempt_count": validation.get("candidate_lifecycle_attempt_count", 0),
        "portfolio_battle_attempt_count": validation.get("portfolio_battle_attempt_count", 0),
        "runtime": outcome.get("runtime"),
    }, ensure_ascii=False))
    return 0 if validation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
