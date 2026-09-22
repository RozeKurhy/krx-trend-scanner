from __future__ import annotations

import csv
from contextlib import contextmanager
from collections import Counter, defaultdict
from pathlib import Path
import json
import math
import socket
import warnings
from typing import Any, Iterable

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast


ROOT = Path(__file__).resolve().parents[1]
TARGET_DATE = "2026-09-21"
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
OUTPUT_DIR = ROOT / "artifacts/research/fastcore_v2_entry_pattern_score_bucket_v02"

TRADE_FIELDS = [
    "ticker", "name", "market", "trade_id", "trade_sequence",
    "entry_signal_date", "entry_execution_date", "entry_open",
    "entry_pattern_a_stage_report", "entry_pattern_a_stage_reconstructed",
    "entry_pattern_a_score", "score_status", "score_bucket", "trade_status",
    "exit_type", "exit_execution_date", "return_pct", "return_source",
    "latest_target_as_of", "score_error",
]

BUCKET_FIELDS = [
    "score_bucket", "trade_count", "realized_count", "open_count",
    "avg_return_pct_all", "median_return_pct_all", "win_count", "win_rate_pct",
    "avg_realized_return_pct", "avg_open_return_pct", "min_return_pct", "max_return_pct",
    "loss_le_neg20_count", "loss_le_neg30_count", "loss_le_neg50_count",
    "loss_le_neg20_rate", "loss_le_neg30_rate", "loss_le_neg50_rate",
    "open_le_neg30_count", "open_le_neg50_count", "open_le_neg30_rate", "open_le_neg50_rate",
]


class NetworkRequestBlocked(RuntimeError):
    pass


@contextmanager
def network_guard(audit: dict[str, int]):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit["count"] += 1
        raise NetworkRequestBlocked(repr(address))

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit["count"] += 1
        raise NetworkRequestBlocked(repr(address))

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def score_bucket(score: float) -> str:
    """Return the frozen 5-point bucket, including 100 in the final bucket."""
    value = float(score)
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        raise ValueError(f"PATTERN_A_SCORE_OUT_OF_RANGE:{score}")
    if value >= 95.0:
        return "[95, 100]"
    lower = int(value // 5.0) * 5
    return f"[{lower}, {lower + 5})"


def _clean_date(value: Any) -> str:
    return pd.Timestamp(value).normalize().strftime("%Y-%m-%d")


def _round(value: Any, digits: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), digits)


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return _round(sum(values) / len(values)) if values else None


def _median(values: Iterable[float]) -> float | None:
    values = sorted(values)
    return _round(float(np.median(values))) if values else None


def _rate(numerator: int, denominator: int) -> float | None:
    return _round(100.0 * numerator / denominator) if denominator else None


def _parse_numeric(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_current_corpus() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    monitor = json.loads((ROOT / "web/data/strategy-monitor.json").read_text(encoding="utf-8"))
    if monitor.get("strategy", {}).get("id") != STRATEGY_ID:
        raise RuntimeError("STRATEGY_MONITOR_ID_MISMATCH")
    target = str(monitor.get("requested_as_of", ""))[:10]
    if target != TARGET_DATE or str(monitor.get("reference_market_date", ""))[:10] != TARGET_DATE:
        raise RuntimeError("STRATEGY_MONITOR_EXACT_TARGET_MISMATCH")
    monitor_items = {str(item["ticker"]): item for item in monitor.get("items", [])}

    reports = sorted((ROOT / "web/data/stocks").glob("*.json"))
    trades: list[dict[str, Any]] = []
    corpus_as_of: set[str] = set()
    source_paths: set[str] = set()
    for path in reports:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ticker = str(payload.get("identity", {}).get("ticker", path.stem)).zfill(6)
        identity = payload.get("identity", {})
        technical = payload.get("technical_details", {})
        as_of = str(technical.get("requested_as_of", ""))[:10]
        reference = str(technical.get("reference_market_date", ""))[:10]
        if as_of != target or reference != target:
            raise RuntimeError(f"REPORT_EXACT_TARGET_MISMATCH:{ticker}:{as_of}:{reference}")
        source_report = str(technical.get("source_report", ""))
        if source_report and target.replace("-", "") not in source_report:
            raise RuntimeError(f"REPORT_SOURCE_TARGET_MISMATCH:{ticker}:{source_report}")
        corpus_as_of.add(as_of)
        if source_report:
            source_paths.add(source_report)
        for history in payload.get("strategy", {}).get("history", []) or []:
            row = dict(history)
            row["ticker"] = ticker
            row["name"] = str(identity.get("name", ""))
            row["market"] = str(identity.get("market", ""))
            trades.append(row)

    keys = [(row["ticker"], str(row.get("trade_id", ""))) for row in trades]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError(f"CURRENT_TRADE_DUPLICATE:{duplicate_count}")
    status_counts = Counter(str(row.get("trade_status", "")) for row in trades)
    unsupported = {key: value for key, value in status_counts.items() if key not in {"REALIZED", "OPEN_AT_CUTOFF"}}
    if unsupported:
        raise RuntimeError(f"UNSUPPORTED_TRADE_STATUS:{unsupported}")
    corpus = {
        "strategy_id": STRATEGY_ID,
        "target_as_of": target,
        "report_count": len(reports),
        "source_report_count": len(source_paths),
        "history_trade_count": len(trades),
        "status_counts": dict(status_counts),
        "duplicate_count": duplicate_count,
        "corpus_as_of": sorted(corpus_as_of),
        "monitor_hold_count": int(monitor.get("counts", {}).get("hold", -1)),
        "monitor_counts": monitor.get("counts", {}),
    }
    if corpus["monitor_hold_count"] != status_counts.get("OPEN_AT_CUTOFF", 0):
        raise RuntimeError("OPEN_COUNT_MONITOR_MISMATCH")
    if len(trades) != sum(status_counts.values()):
        raise RuntimeError("TRADE_STATUS_TOTAL_MISMATCH")
    return trades, corpus, monitor_items


def _base_result(row: dict[str, Any], target: str) -> dict[str, Any]:
    return {
        "ticker": row["ticker"],
        "name": row["name"],
        "market": row["market"],
        "trade_id": str(row.get("trade_id", "")),
        "trade_sequence": row.get("trade_sequence"),
        "entry_signal_date": str(row.get("entry_signal_date", ""))[:10],
        "entry_execution_date": str(row.get("entry_execution_date", ""))[:10],
        "entry_open": _parse_numeric(row.get("entry_open")),
        "entry_pattern_a_stage_report": row.get("entry_pattern_a_stage"),
        "entry_pattern_a_stage_reconstructed": None,
        "entry_pattern_a_score": None,
        "score_status": "UNAVAILABLE",
        "score_bucket": None,
        "trade_status": row.get("trade_status"),
        "exit_type": row.get("exit_type"),
        "exit_execution_date": row.get("exit_execution_date"),
        "return_pct": _parse_numeric(row.get("return_pct")),
        "return_source": "REALIZED_REPORT_HISTORY" if row.get("trade_status") == "REALIZED" else "OPEN_LATEST_REPORT_HISTORY",
        "latest_target_as_of": target,
        "score_error": None,
    }


def _process_ticker(
    ticker: str,
    rows: list[dict[str, Any]],
    target: str,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    market_calendar: Any,
    repo: Any,
) -> tuple[list[dict[str, Any]], Counter[str], list[dict[str, str]]]:
    local_errors: Counter[str] = Counter()
    local_examples: list[dict[str, str]] = []
    name = rows[0]["name"]
    daily = None
    context = None
    try:
        earliest_signal = min(pd.Timestamp(row["entry_signal_date"]).normalize() for row in rows)
        history_start = (earliest_signal - pd.Timedelta("1800D")).strftime("%Y-%m-%d")
        daily = repo.get_daily(ticker, history_start, target).sort_index()
        if daily.empty:
            raise MarketDataError("REPOSITORY_V2_EMPTY")
        context = build_precomputed_ticker_context(ticker, name, daily)
    except Exception as exc:
        local_errors[type(exc).__name__] += len(rows)
        local_examples.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
    output: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item.get("entry_signal_date", ""), str(item.get("trade_id", "")))):
        result = _base_result(row, target)
        if context is None or daily is None:
            result["score_error"] = local_examples[-1]["error"] if local_examples else "DATA_UNAVAILABLE"
            output.append(result)
            continue
        signal_date = pd.Timestamp(row["entry_signal_date"]).normalize()
        try:
            evaluated = evaluate_pattern_a_fast(
                ticker,
                name,
                daily,
                signal_date,
                score_contract,
                stage_contract,
                context=context,
                market_calendar=market_calendar,
            )
            reconstructed_stage = evaluated.get("pattern_a_stage")
            normalized_reconstructed_stage = str(reconstructed_stage).upper() if reconstructed_stage is not None else None
            reconstructed_score = _parse_numeric(evaluated.get("pattern_a_score"))
            result["entry_pattern_a_stage_reconstructed"] = normalized_reconstructed_stage
            result["entry_pattern_a_score"] = reconstructed_score
            if evaluated.get("pattern_a_evaluation_status") != "READY" or reconstructed_score is None:
                result["score_status"] = "UNAVAILABLE"
                result["score_error"] = "PATTERN_A_SCORE_UNAVAILABLE"
                local_errors["PATTERN_A_SCORE_UNAVAILABLE"] += 1
            elif reconstructed_score < 0.0 or reconstructed_score > 100.0:
                result["score_status"] = "UNAVAILABLE"
                result["score_error"] = "PATTERN_A_SCORE_OUT_OF_RANGE"
                local_errors["PATTERN_A_SCORE_OUT_OF_RANGE"] += 1
            elif normalized_reconstructed_stage != str(row.get("entry_pattern_a_stage", "")).upper():
                result["score_status"] = "CHECK_REQUIRED"
                result["score_error"] = "PATTERN_A_STAGE_MISMATCH"
                local_errors["PATTERN_A_STAGE_MISMATCH"] += 1
            else:
                result["score_status"] = "READY"
                result["score_bucket"] = score_bucket(reconstructed_score)
        except Exception as exc:
            local_errors[type(exc).__name__] += 1
            result["score_error"] = f"{type(exc).__name__}: {exc}"
            if len(local_examples) < 20:
                local_examples.append({"ticker": ticker, "trade_id": result["trade_id"], "error": result["score_error"]})
        output.append(result)
    return output, local_errors, local_examples


def reconstruct_scores(
    trades: list[dict[str, Any]],
    target: str,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    market_calendar: Any,
    network_audit: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        by_ticker[row["ticker"]].append(row)
    repo = build_production_repository_v2(ROOT, end=target)
    tickers = sorted(by_ticker)
    first = tickers[0]
    first_rows, first_errors, first_examples = _process_ticker(
        first, by_ticker[first], target, score_contract, stage_contract, market_calendar, repo
    )
    result_by_ticker: dict[str, list[dict[str, Any]]] = {first: first_rows}
    error_counter: Counter[str] = Counter(first_errors)
    error_examples = list(first_examples)
    processed = 1
    print(f"processed_tickers={processed}/{len(tickers)} trades={len(first_rows)}", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = min(8, max(1, len(tickers) - 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_ticker,
                ticker,
                by_ticker[ticker],
                target,
                score_contract,
                stage_contract,
                market_calendar,
                repo,
            ): ticker
            for ticker in tickers[1:]
        }
        for future in as_completed(futures):
            ticker = futures[future]
            ticker_rows, ticker_errors, ticker_examples = future.result()
            result_by_ticker[ticker] = ticker_rows
            error_counter.update(ticker_errors)
            for example in ticker_examples:
                if len(error_examples) < 20:
                    error_examples.append(example)
            processed += 1
            if processed % 50 == 0 or processed == len(tickers):
                print(f"processed_tickers={processed}/{len(tickers)} trades={sum(len(value) for value in result_by_ticker.values())}", flush=True)
    output = [row for ticker in tickers for row in result_by_ticker[ticker]]
    diagnostics = {
        "ticker_count": len(by_ticker),
        "processed_ticker_count": processed,
        "error_counts": dict(error_counter),
        "error_examples": error_examples,
        "network_requests": network_audit["count"],
        "max_workers": max_workers,
    }
    return output, diagnostics


def _bucket_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [f"[{lower}, {lower + 5})" for lower in range(0, 95, 5)] + ["[95, 100]"]
    result: list[dict[str, Any]] = []
    for bucket in buckets:
        selected = [row for row in rows if row["score_status"] == "READY" and row["score_bucket"] == bucket]
        returns = [float(row["return_pct"]) for row in selected if row["return_pct"] is not None]
        realized = [float(row["return_pct"]) for row in selected if row["trade_status"] == "REALIZED" and row["return_pct"] is not None]
        open_rows = [row for row in selected if row["trade_status"] == "OPEN_AT_CUTOFF"]
        open_returns = [float(row["return_pct"]) for row in open_rows if row["return_pct"] is not None]
        le20 = sum(value <= -20.0 for value in returns)
        le30 = sum(value <= -30.0 for value in returns)
        le50 = sum(value <= -50.0 for value in returns)
        open_le30 = sum(value <= -30.0 for value in open_returns)
        open_le50 = sum(value <= -50.0 for value in open_returns)
        result.append({
            "score_bucket": bucket,
            "trade_count": len(selected),
            "realized_count": len(realized),
            "open_count": len(open_rows),
            "avg_return_pct_all": _mean(returns),
            "median_return_pct_all": _median(returns),
            "win_count": sum(value > 0 for value in returns),
            "win_rate_pct": _rate(sum(value > 0 for value in returns), len(returns)),
            "avg_realized_return_pct": _mean(realized),
            "avg_open_return_pct": _mean(open_returns),
            "min_return_pct": _round(min(returns)) if returns else None,
            "max_return_pct": _round(max(returns)) if returns else None,
            "loss_le_neg20_count": le20,
            "loss_le_neg30_count": le30,
            "loss_le_neg50_count": le50,
            "loss_le_neg20_rate": _rate(le20, len(returns)),
            "loss_le_neg30_rate": _rate(le30, len(returns)),
            "loss_le_neg50_rate": _rate(le50, len(returns)),
            "open_le_neg30_count": open_le30,
            "open_le_neg50_count": open_le50,
            "open_le_neg30_rate": _rate(open_le30, len(open_returns)),
            "open_le_neg50_rate": _rate(open_le50, len(open_returns)),
        })
    return result


def _cohort_stats(rows: list[dict[str, Any]], predicate) -> dict[str, Any]:
    selected = [row for row in rows if predicate(float(row["return_pct"]))]
    by_bucket = Counter(row["score_bucket"] for row in selected if row["score_status"] == "READY")
    return {"count": len(selected), "bucket_counts": dict(sorted(by_bucket.items()))}


def _score_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [row for row in rows if row["score_status"] == "READY" and row["entry_pattern_a_score"] is not None]
    groups = {
        "all": ready,
        "realized": [row for row in ready if row["trade_status"] == "REALIZED"],
        "open": [row for row in ready if row["trade_status"] == "OPEN_AT_CUTOFF"],
        "wins": [row for row in ready if row["return_pct"] is not None and row["return_pct"] > 0],
        "losses": [row for row in ready if row["return_pct"] is not None and row["return_pct"] < 0],
        "return_le_neg30": [row for row in ready if row["return_pct"] is not None and row["return_pct"] <= -30],
        "return_le_neg50": [row for row in ready if row["return_pct"] is not None and row["return_pct"] <= -50],
        "return_ge_pos50": [row for row in ready if row["return_pct"] is not None and row["return_pct"] >= 50],
    }
    return {key: {"count": len(value), "avg_entry_score": _mean(row["entry_pattern_a_score"] for row in value), "median_entry_score": _median(row["entry_pattern_a_score"] for row in value)} for key, value in groups.items()}


def validate_open_returns(rows: list[dict[str, Any]], monitor_items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    open_rows = [row for row in rows if row["trade_status"] == "OPEN_AT_CUTOFF"]
    checked = 0
    mismatches: list[dict[str, Any]] = []
    for row in open_rows[:20]:
        item = monitor_items.get(row["ticker"], {})
        latest_close = _parse_numeric(item.get("latest_close"))
        entry_open = _parse_numeric(row.get("entry_open"))
        reported = _parse_numeric(row.get("return_pct"))
        if latest_close is None or entry_open in (None, 0.0) or reported is None:
            continue
        calculated = round((latest_close / entry_open - 1.0) * 100.0, 2)
        checked += 1
        if abs(calculated - reported) > 0.02:
            mismatches.append({"ticker": row["ticker"], "trade_id": row["trade_id"], "calculated": calculated, "reported": reported})
    return {"sample_size": checked, "mismatch_count": len(mismatches), "mismatches": mismatches}


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def write_outputs(rows: list[dict[str, Any]], corpus: dict[str, Any], diagnostics: dict[str, Any], buckets: list[dict[str, Any]], open_validation: dict[str, Any], score_stats: dict[str, Any], target: str) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        writer.writerows({field: _fmt(row.get(field)) for field in TRADE_FIELDS} for row in rows)
    with (OUTPUT_DIR / "score_buckets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BUCKET_FIELDS)
        writer.writeheader()
        writer.writerows({field: _fmt(row.get(field)) for field in BUCKET_FIELDS} for row in buckets)

    status_counts = Counter(row["score_status"] for row in rows)
    non_ready = sum(count for key, count in status_counts.items() if key != "READY")
    bucket_total = sum(int(row["trade_count"]) for row in buckets)
    return_counts = Counter(row["trade_status"] for row in rows)
    open_rows = [row for row in rows if row["trade_status"] == "OPEN_AT_CUTOFF" and row["return_pct"] is not None]
    all_rows_with_return = [row for row in rows if row["return_pct"] is not None]
    open_cohorts = {
        "<= -20%": _cohort_stats(open_rows, lambda value: value <= -20),
        "<= -30%": _cohort_stats(open_rows, lambda value: value <= -30),
        "<= -40%": _cohort_stats(open_rows, lambda value: value <= -40),
        "<= -50%": _cohort_stats(open_rows, lambda value: value <= -50),
    }
    all_cohorts = {
        "<= -30%": _cohort_stats(all_rows_with_return, lambda value: value <= -30),
        "<= -50%": _cohort_stats(all_rows_with_return, lambda value: value <= -50),
        ">= +50%": _cohort_stats(all_rows_with_return, lambda value: value >= 50),
    }
    summary = {
        "status": "PASS" if status_counts.get("CHECK_REQUIRED", 0) == 0 and diagnostics["network_requests"] == 0 and open_validation["mismatch_count"] == 0 else "CHECK_REQUIRED",
        "strategy_id": STRATEGY_ID,
        "target_as_of": target,
        "corpus": corpus,
        "trade_count": len(rows),
        "realized_count": return_counts.get("REALIZED", 0),
        "open_count": return_counts.get("OPEN_AT_CUTOFF", 0),
        "score_status_counts": dict(status_counts),
        "bucket_trade_count": bucket_total,
        "non_ready_score_count": non_ready,
        "diagnostics": diagnostics,
        "open_return_validation": open_validation,
        "score_stats": score_stats,
        "open_cohorts": open_cohorts,
        "all_return_avg_pct": _mean(float(row["return_pct"]) for row in all_rows_with_return),
        "all_return_median_pct": _median(float(row["return_pct"]) for row in all_rows_with_return),
    }
    (OUTPUT_DIR / "analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    nonempty = [row for row in buckets if row["trade_count"]]
    best_avg = max(nonempty, key=lambda row: row["avg_return_pct_all"]) if nonempty else None
    best_median = max(nonempty, key=lambda row: row["median_return_pct_all"]) if nonempty else None
    open_ready = [row for row in rows if row["trade_status"] == "OPEN_AT_CUTOFF" and row["score_status"] == "READY"]
    lines = [
        "# A FAST Core V2 진입 Pattern A 점수대별 수익률 분석",
        "",
        f"## 상태: `{summary['status']}`",
        "",
        "현재 production lineage의 최신 Stock Report `strategy.history`만 사용했다. frozen 783건 baseline은 primary input에서 제외했다.",
        "",
        "## 1. 기준 및 원장",
        "",
        f"- 전략: `{STRATEGY_ID}`",
        f"- 기준일: `{target}`",
        f"- source corpus: `web/data/stocks/*.json` ({corpus['report_count']} reports, history {corpus['history_trade_count']} trades)",
        f"- REALIZED: **{summary['realized_count']}건**",
        f"- OPEN_AT_CUTOFF: **{summary['open_count']}건**",
        f"- strategy monitor HOLD: **{corpus['monitor_hold_count']}건**",
        f"- duplicate `(ticker, trade_id)`: `{corpus['duplicate_count']}`",
        f"- 네트워크 호출: `{diagnostics['network_requests']}`",
        "",
        "## 2. Pattern A score 복원",
        "",
        "모든 score는 `entry_signal_date` 시점에서 MarketDataRepositoryV2와 공식 `evaluate_pattern_a_fast(...)` 경로로 PIT 복원했다. 매도일 score, 현재 `pattern.score`, `fast_score`는 사용하지 않았다.",
        "",
        f"- READY: **{status_counts.get('READY', 0)}건**",
        f"- CHECK_REQUIRED (stage mismatch): **{status_counts.get('CHECK_REQUIRED', 0)}건**",
        f"- UNAVAILABLE: **{status_counts.get('UNAVAILABLE', 0)}건**",
        f"- UNAVAILABLE trade: `{', '.join(row['ticker'] + '/' + row['trade_id'] for row in rows if row['score_status'] == 'UNAVAILABLE') or '없음'}`",
        f"- bucket 합계 + non-ready: `{bucket_total} + {non_ready} = {len(rows)}`",
        f"- OPEN return 표본 검증: `{open_validation['sample_size']}`건, mismatch `{open_validation['mismatch_count']}`건",
        "",
        "## 3. 20개 score bucket 전체 표",
        "",
        "`avg_return_pct_all`은 각 trade 동일 가중치의 단순 산술평균이며 복리 포트폴리오 수익률이 아니다.",
        "",
        "| bucket | trades | realized | open | avg all | median all | win rate | avg realized | avg open | <=-20 | <=-30 | <=-50 | open <=-30 | open <=-50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for bucket in buckets:
        lines.append("| {score_bucket} | {trade_count} | {realized_count} | {open_count} | {avg_return_pct_all} | {median_return_pct_all} | {win_rate_pct}% | {avg_realized_return_pct} | {avg_open_return_pct} | {loss_le_neg20_count} | {loss_le_neg30_count} | {loss_le_neg50_count} | {open_le_neg30_count} | {open_le_neg50_count} |".format(**bucket))
    lines += ["", "## 4. 현재 OPEN_AT_CUTOFF 손실 분석", "", f"- 전체 OPEN: **{len(open_rows)}건**, 평균 `{_mean(float(row['return_pct']) for row in open_rows)}%`, 중앙값 `{_median(float(row['return_pct']) for row in open_rows)}%`", "", "| cohort | count | READY score bucket별 건수 |", "|---|---:|---|"]
    for label, cohort in open_cohorts.items():
        bucket_text = ", ".join(f"{key}: {value}" for key, value in cohort["bucket_counts"].items()) or "없음/비복원"
        lines.append(f"| {label} | {cohort['count']} | {bucket_text} |")
    def top_bucket_text(cohort: dict[str, Any]) -> str:
        counts = cohort["bucket_counts"]
        if not counts:
            return "없음"
        peak = max(counts.values())
        return ", ".join(f"{key} ({value}건)" for key, value in counts.items() if value == peak)
    lines += ["", "### OPEN 손실 집중 해석", "", f"- `OPEN_AT_CUTOFF <= -30%` 최다 bucket: {top_bucket_text(open_cohorts['<= -30%'])}", f"- `OPEN_AT_CUTOFF <= -50%` 최다 bucket: {top_bucket_text(open_cohorts['<= -50%'])}", "- score가 READY가 아닌 OPEN 거래는 bucket에 억지로 배정하지 않고 별도 non-ready로 남겼다.", ""]
    lines += ["### 전체 수익률 cohort 집중", "", f"- 전체 `return <= -30%` 최다 bucket: {top_bucket_text(all_cohorts['<= -30%'])}", f"- 전체 `return <= -50%` 최다 bucket: {top_bucket_text(all_cohorts['<= -50%'])}", f"- 전체 `return >= +50%` 최다 bucket: {top_bucket_text(all_cohorts['>= +50%'])}", ""]
    lines += ["## 5. 보조 score 통계", "", "| group | count | avg entry score | median entry score |", "|---|---:|---:|---:|"]
    for key in ("all", "realized", "open", "wins", "losses", "return_le_neg30", "return_le_neg50", "return_ge_pos50"):
        item = score_stats[key]
        lines.append(f"| {key} | {item['count']} | {item['avg_entry_score']} | {item['median_entry_score']} |")
    lines += ["", "## 6. 핵심 구간", ""]
    if best_avg:
        lines.append(f"- 평균 수익률 최고 구간: `{best_avg['score_bucket']}` / `{best_avg['avg_return_pct_all']}%` (n={best_avg['trade_count']})")
    if best_median:
        lines.append(f"- 중앙값 수익률 최고 구간: `{best_median['score_bucket']}` / `{best_median['median_return_pct_all']}%` (n={best_median['trade_count']})")
    lines += ["- `<= -30%`, `<= -50%`, `OPEN <= -50%`, `>= +50%` 집중 구간은 전체 bucket 표와 cohort 표에서 확인한다.", "", "## 7. 데이터 한계 및 결론", "", "- 현재 production report history만 사용했으며 frozen baseline과 병합하지 않았다.", "- score 복원 stage mismatch와 unavailable은 조용히 제외하지 않고 상태로 기록했다.", "- 본 결과는 현상 파악용이며 진입 cutoff나 전략 규칙 변경을 제안하지 않는다.", ""]
    (OUTPUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    audit = {"count": 0}
    with network_guard(audit):
        trades, corpus, monitor_items = load_current_corpus()
        calendar = load_rolling_production_market_calendar(ROOT)
        if calendar is None or pd.Timestamp(calendar.trading_dates.max()).normalize() < pd.Timestamp(TARGET_DATE):
            raise RuntimeError("ROLLING_CALENDAR_BELOW_TARGET")
        score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
        stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
        rows, diagnostics = reconstruct_scores(trades, TARGET_DATE, score_contract, stage_contract, calendar, audit)
        buckets = _bucket_rows(rows)
        open_validation = validate_open_returns(rows, monitor_items)
        score_stats = _score_stats(rows)
        write_outputs(rows, corpus, diagnostics, buckets, open_validation, score_stats, TARGET_DATE)


if __name__ == "__main__":
    main()
