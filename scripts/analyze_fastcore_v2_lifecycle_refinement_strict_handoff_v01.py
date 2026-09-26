"""A FAST Core V2 lifecycle refinement + EARLY_TREND entry strict handoff V01.

기존 인증 CONTROL 원장(단순 5개 윈도우, 현실적 포트폴리오 3개 윈도우)만 읽는다.

1. 보유 중 lifecycle 세분화: 기존 `lifecycle_class`는 진입 신호 주간부터 **윈도우 cutoff까지**의
   월간 Pattern A stage로 판정되므로 청산 이후 관찰이 섞인다. 여기서는 같은 월간 stage를
   **보유 구간**(진입 ~ 청산 신호일, 미청산은 cutoff)으로 잘라 FIRST_PROGRESSED_NORMAL /
   LATE_NORMALIZED / NEVER_NORMALIZED_COVERAGE로 다시 나누고 handoff 직전 origin을 기록한다.
2. EARLY_TREND 진입 strict handoff: 진입 stage가 EARLY_TREND인 거래에서 보유 중 처음으로
   EARLY_TREND를 벗어난 stage가 PROGRESSED인지(PASS) 아닌지(FAIL) 본다.

월간 stage는 러너와 같은 경로(`build_historical_snapshot_from_context` + `evaluate_pattern_a`)로
복원하고, 복원한 경로로 원장의 `lifecycle_class`와 `first_progressed_date`를 재현하는 게이트를
통과해야 분석한다. 새 백테스트, 전략 변경, threshold 변경, 네트워크 호출은 하지 않는다.

사용법:
    python scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py stages   # 월간 stage 캐시
    python scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py analyze  # 게이트 + 분석
    python scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py inventory  # 8개 인증 run 보관 inventory
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
import math
import multiprocessing as mp
from pathlib import Path
import sys
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import scripts.analyze_fastcore_v2_winner_loser_profile_v01 as wl  # noqa: E402

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/lifecycle_refinement_strict_handoff_v01"
STAGE_CACHE_PATH = OUTPUT_DIR / "monthly_stage_cache.csv.gz"
STAGE_AUDIT_PATH = OUTPUT_DIR / "monthly_stage_cache_audit.json"
REPOSITORY_END = "2026-09-21"
DATA_SUPPORT_END = "2026-09-01"
LABEL_END = "2026-08-31"

SIMPLE_WINDOWS = ["P1", "P2-1", "P2-2", "P3-1", "P3-2"]
REALISTIC_RUNS: dict[str, dict[str, Any]] = {
    "P2-1": {"run_dir": ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01",
             "status": "P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED", "cutoff": "2025-05-30"},
    "P2-2": {"run_dir": ROOT / "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01",
             "status": "P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED", "cutoff": "2026-08-31"},
    "P3-2": {"run_dir": ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01",
             "status": "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED", "cutoff": "2026-08-31"},
}
REALISTIC_EXPECTED = {
    "P2-1": {"eligible": 355, "filled": 199, "realized": 161, "cash_skipped": 156},
    "P2-2": {"eligible": 485, "filled": 242, "realized": 218, "cash_skipped": 243},
    "P3-2": {"eligible": 405, "filled": 228, "realized": 207, "cash_skipped": 177},
}
SIMPLE_CUTOFF = {w: wl.WINDOWS[w]["cutoff"] for w in SIMPLE_WINDOWS}

IDENTITY = ["ticker", "isu_cd", "identity_effective_from"]


# ---------------------------------------------------------------------------
# 원장 로드
# ---------------------------------------------------------------------------

def load_realistic(window: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    spec = REALISTIC_RUNS[window]
    summary = json.loads((spec["run_dir"] / "summary.json").read_text(encoding="utf-8"))
    if summary.get("status") != spec["status"] or summary["strategy_ids"]["control"] != STRATEGY_ID:
        raise RuntimeError(f"REALISTIC_STATUS_MISMATCH:{window}")
    trades = pd.read_csv(spec["run_dir"] / "control_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str}, low_memory=False)
    trades["ticker"] = trades["ticker"].str.zfill(6)
    events = pd.read_csv(spec["run_dir"] / "control_portfolio_events.csv", dtype={"ticker": str}, low_memory=False)
    entry_exec = events[(events["event_type"] == "ENTRY") & (events["event_status"] == "EXECUTED")]
    observed = {
        "eligible": int(len(trades)),
        "filled": int(len(entry_exec)),
        "realized": int(((events["event_type"] == "EXIT") & (events["event_status"] == "EXECUTED")).sum()),
        "cash_skipped": int(((events["event_type"] == "ENTRY") & (events["event_status"] == "SKIPPED_CASH_UNAVAILABLE")).sum()),
    }
    metrics = pd.read_csv(spec["run_dir"] / "summary.csv")
    control = dict(zip(metrics.loc[metrics["strategy"] == "CONTROL", "metric"], metrics.loc[metrics["strategy"] == "CONTROL", "value"]))
    certified = {"filled": int(float(control["trade_count"])), "realized": int(float(control["realized_trade_count"])),
                 "cash_skipped": int(float(control["cash_shortage_skipped_entries"])), "eligible": int(summary["population"]["control_trade_rows"])}
    if observed != REALISTIC_EXPECTED[window] or certified != REALISTIC_EXPECTED[window]:
        raise RuntimeError(f"REALISTIC_COUNT_GATE:{window}:{observed}:{certified}")
    if trades["pair_id"].duplicated().any() or entry_exec["pair_id"].duplicated().any():
        raise RuntimeError(f"REALISTIC_PAIR_ID_DUPLICATE:{window}")
    trades["filled"] = trades["pair_id"].isin(set(entry_exec["pair_id"]))
    trades["window"] = window
    return trades, {"observed": observed, "certified": certified, "match": True}


def all_ledgers() -> dict[str, pd.DataFrame]:
    ledgers = {f"SIMPLE_{w}": wl.load_window_ledger(w) for w in SIMPLE_WINDOWS}
    for window in REALISTIC_RUNS:
        ledgers[f"REALISTIC_{window}"] = load_realistic(window)[0]
    return ledgers


# ---------------------------------------------------------------------------
# 월간 stage 캐시 (stages)
# ---------------------------------------------------------------------------

_WORKER_CALENDAR: Any = None


def _worker_init() -> None:
    global _WORKER_CALENDAR
    import warnings

    warnings.filterwarnings("ignore")
    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar

    _WORKER_CALENDAR = load_rolling_production_market_calendar(ROOT)


def monthly_stages(key: tuple[str, str, str], daily: pd.DataFrame, calendar: Any, label_end: str = LABEL_END) -> list[dict[str, Any]]:
    """러너의 `_stage_timeline`/reentry 월간 스냅샷과 같은 경로로 모든 월 라벨의 stage를 만든다."""
    from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context, build_precomputed_ticker_context
    from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a

    ticker, isu_cd, start = key
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    rows = []
    for label in context.monthly_up_to(pd.Timestamp(label_end)).index:
        label = pd.Timestamp(label).normalize()
        effective = daily.index[daily.index <= label]
        effective_date = pd.Timestamp(effective[-1]).strftime("%Y-%m-%d") if len(effective) else None
        try:
            snapshot = build_historical_snapshot_from_context(context, label, include_incomplete_periods=False, market_calendar=calendar)
            evaluated = evaluate_pattern_a(snapshot)
            stage = evaluated.stage.value.upper() if evaluated.stage else "UNAVAILABLE"
            score = round(float(evaluated.score), 2) if evaluated.score is not None else None
        except Exception:
            stage, score = "UNAVAILABLE", None
        rows.append({"ticker": ticker, "isu_cd": isu_cd, "identity_effective_from": start,
                     "month_label": label.strftime("%Y-%m-%d"), "effective_date": effective_date, "stage": stage, "score": score})
    return rows


def _worker_task(key: tuple[str, str, str], daily: pd.DataFrame) -> list[dict[str, Any]]:
    return monthly_stages(key, daily, _WORKER_CALENDAR)


def run_stages(workers: int, limit: int | None, single: bool, out_path: Path | None) -> None:
    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    ledgers = all_ledgers()
    keys = sorted(set().union(*[set(map(tuple, f[IDENTITY].astype(str).values)) for f in ledgers.values()]))
    if limit:
        keys = keys[:limit]
    repo = build_production_repository_v2(ROOT, end=REPOSITORY_END)
    calendar = load_rolling_production_market_calendar(ROOT)
    print(f"identities={len(keys)} repo_ready={time.time() - started:.0f}s", flush=True)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def load(key: tuple[str, str, str]) -> pd.DataFrame | None:
        try:
            return repo.get_daily(key[0], key[2], DATA_SUPPORT_END).sort_index()
        except Exception as exc:
            errors.append({"key": "|".join(key), "error": f"{type(exc).__name__}: {exc}"})
            return None

    if single:
        for key in keys:
            daily = load(key)
            if daily is not None:
                rows.extend(monthly_stages(key, daily, calendar))
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_worker_init) as pool:
            futures = {}
            for key in keys:
                daily = load(key)
                if daily is not None:
                    futures[pool.submit(_worker_task, key, daily)] = key
            for done, future in enumerate(as_completed(futures), start=1):
                rows.extend(future.result())
                if done % 200 == 0 or done == len(futures):
                    print(f"identities={done}/{len(futures)} rows={len(rows)} elapsed={time.time() - started:.0f}s", flush=True)
    frame = pd.DataFrame(rows).sort_values(IDENTITY + ["month_label"]).reset_index(drop=True)
    path = out_path or STAGE_CACHE_PATH
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
        handle.write(frame.to_csv(index=False).encode("utf-8"))
    leakage = stage_leakage_check(frame, repo, calendar) if out_path is None else None
    audit = {
        "identity_count": len(keys), "rows": int(len(frame)), "load_errors": errors,
        "stage_counts": {k: int(v) for k, v in frame["stage"].value_counts().items()},
        "label_end": LABEL_END, "data_support_end": DATA_SUPPORT_END, "repository_end": REPOSITORY_END,
        "workers": 1 if single else workers, "elapsed_seconds": round(time.time() - started, 1),
        "leakage_check": leakage, "cache_sha256": wl.sha256_file(path),
    }
    if out_path is None:
        STAGE_AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in audit.items() if k != "load_errors"}, ensure_ascii=False, indent=2))


def stage_leakage_check(frame: pd.DataFrame, repo: Any, calendar: Any, sample_size: int = 20) -> dict[str, Any]:
    """무작위 (identity, 라벨) 20개를 라벨의 관측일까지 자른 일봉으로 다시 계산해 같은지 본다."""
    sample = frame[frame["stage"] != "UNAVAILABLE"].sample(n=sample_size, random_state=20260927)
    mismatches = []
    for _, row in sample.iterrows():
        daily = repo.get_daily(row["ticker"], row["identity_effective_from"], row["effective_date"]).sort_index()
        recomputed = [r for r in monthly_stages((row["ticker"], row["isu_cd"], row["identity_effective_from"]), daily, calendar, label_end=row["month_label"])
                      if r["month_label"] == row["month_label"]]
        if not recomputed or recomputed[0]["stage"] != row["stage"]:
            mismatches.append({"key": [row["ticker"], row["isu_cd"], row["month_label"]], "cached": row["stage"],
                               "truncated": recomputed[0]["stage"] if recomputed else None})
    return {"sample_size": sample_size, "mismatch_count": len(mismatches), "mismatches": mismatches}


# ---------------------------------------------------------------------------
# 경로 분류 (순수 함수)
# ---------------------------------------------------------------------------

VALID_SKIP = {"UNAVAILABLE"}
HOLDING_A = "FIRST_PROGRESSED_NORMAL"
HOLDING_B = "LATE_NORMALIZED"
HOLDING_C = "NEVER_NORMALIZED_COVERAGE"
HOLDING_C1 = "C1_PROGRESSED_WITHOUT_DIRECT_HANDOFF"
HOLDING_C2 = "C2_NO_PROGRESSED_WHILE_HELD"
STRICT_PASS = "STRICT_PASS"
STRICT_FAIL = "STRICT_FAIL"
STRICT_NONE = "NO_NEXT_STAGE_BEFORE_EXIT_OR_CUTOFF"
ORIGIN_GROUPS = ["TRANSITION", "BASE", "WEAK", "PROGRESSED"]
TIER_RULES = {"evaluable_min_n": 20, "descriptive_min_n": 10, "deep_loss_min": {"LOSS_30": 10, "LOSS_50": 5}}


def replicate_ledger_lifecycle(entry_stage: str, post: list[tuple[pd.Timestamp, str]]) -> tuple[str, pd.Timestamp | None]:
    """reentry 시뮬레이터의 lifecycle 판정을 그대로 옮긴 것. post는 신호 주간 이후 cutoff까지의 (라벨, stage)."""
    direct = skipped = progressed = False
    first_progressed = None
    prev = entry_stage
    had_early = entry_stage == "EARLY_TREND"
    for label, stage in post:
        if stage in VALID_SKIP:
            continue
        if stage == "EARLY_TREND":
            had_early = True
        if stage == "PROGRESSED":
            progressed = True
            if first_progressed is None:
                first_progressed = label
            if prev == "EARLY_TREND" and not direct:
                direct = True
            elif prev == "TRANSITION" and not had_early and not direct and not skipped:
                skipped = True
        prev = stage
    if direct:
        return "NORMAL_EARLY_TREND_HANDOFF", first_progressed
    if skipped:
        return "SKIPPED_EARLY_TREND_HANDOFF", first_progressed
    if progressed:
        return "PROGRESSED_WITHOUT_DIRECT_HANDOFF", first_progressed
    return "NEVER_PROGRESSED", None


def classify_holding(entry_stage: str, held: list[tuple[pd.Timestamp, str]]) -> dict[str, Any]:
    """보유 구간 경로로 A/B/C(C1/C2)와 첫 직접 handoff 위치를 정한다."""
    sequence = [(None, entry_stage)] + list(held)
    prev = None
    first_progressed_index = first_direct_index = None
    for index, (_, stage) in enumerate(sequence):
        if stage in VALID_SKIP:
            continue
        if stage == "PROGRESSED":
            if first_progressed_index is None:
                first_progressed_index = index
            if prev == "EARLY_TREND" and first_direct_index is None:
                first_direct_index = index
        prev = stage
    if first_direct_index is not None and first_direct_index == first_progressed_index:
        group, sub = HOLDING_A, HOLDING_A
    elif first_direct_index is not None:
        group, sub = HOLDING_B, HOLDING_B
    else:
        group = HOLDING_C
        sub = HOLDING_C1 if first_progressed_index is not None else HOLDING_C2
    return {"group": group, "subgroup": sub, "sequence": sequence,
            "first_progressed_index": first_progressed_index, "first_direct_index": first_direct_index}


def walk_back_origin(sequence: list[tuple[Any, str]], index: int, pre_entry: list[tuple[pd.Timestamp, str]]) -> str:
    """index 직전부터 거꾸로 EARLY_TREND·UNAVAILABLE을 건너뛰어 첫 다른 stage를 origin으로 돌려준다.

    sequence의 앞쪽이 끝나면 진입 전 월 라벨(pre_entry, 시간순)을 뒤에서부터 본다. 기록이 없으면 UNKNOWN."""
    for _, stage in reversed(sequence[:index]):
        if stage in VALID_SKIP or stage == "EARLY_TREND":
            continue
        return stage
    for _, stage in reversed(pre_entry):
        if stage in VALID_SKIP or stage == "EARLY_TREND":
            continue
        return stage
    return "UNKNOWN"


def origin_group(origin: str) -> str:
    return origin if origin in ORIGIN_GROUPS else "OTHER"


def classify_strict(entry_stage: str, held: list[tuple[pd.Timestamp, str]]) -> str | None:
    """EARLY_TREND 진입 거래에서 보유 중 처음으로 EARLY_TREND를 벗어난 유효 stage로 PASS/FAIL을 정한다."""
    if entry_stage != "EARLY_TREND":
        return None
    for _, stage in held:
        if stage in VALID_SKIP or stage == "EARLY_TREND":
            continue
        return STRICT_PASS if stage == "PROGRESSED" else STRICT_FAIL
    return STRICT_NONE


def compress_path(sequence: Iterable[tuple[Any, str]]) -> str:
    parts: list[list[Any]] = []
    for _, stage in sequence:
        if parts and parts[-1][0] == stage:
            parts[-1][1] += 1
        else:
            parts.append([stage, 1])
    return ">".join(f"{s}({n})" if n > 1 else s for s, n in parts)


def tier(n_first: int, n_second: int) -> str:
    n = min(n_first, n_second)
    if n >= TIER_RULES["evaluable_min_n"]:
        return "EVALUABLE"
    if n >= TIER_RULES["descriptive_min_n"]:
        return "DESCRIPTIVE"
    return "COUNTS_ONLY"


# ---------------------------------------------------------------------------
# 분석 (analyze)
# ---------------------------------------------------------------------------

def load_stage_cache(path: Path = STAGE_CACHE_PATH) -> dict[tuple[str, str, str], pd.DataFrame]:
    frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str}, compression="gzip")
    frame["ticker"] = frame["ticker"].str.zfill(6)
    frame["label"] = pd.to_datetime(frame["month_label"])
    frame["effective"] = pd.to_datetime(frame["effective_date"])
    return {key: group.sort_values("label").reset_index(drop=True) for key, group in frame.groupby(IDENTITY, sort=False)}


def holding_end(row: pd.Series, cutoff: pd.Timestamp) -> pd.Timestamp:
    for column in ("exit_signal_date", "settlement_date"):
        value = row.get(column)
        if isinstance(value, str) and value:
            return min(pd.Timestamp(value), cutoff)
    return cutoff


def trade_paths(frame: pd.DataFrame, cutoffs: pd.Series, stages: dict[tuple[str, str, str], pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for index, row in frame.iterrows():
        key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
        cache = stages.get(key)
        cutoff = pd.Timestamp(cutoffs.loc[index])
        signal = pd.Timestamp(row["entry_signal_date"])
        entry_stage = str(row["entry_pattern_a_stage"]).upper()
        record: dict[str, Any] = {"row_index": index, "cache_found": cache is not None}
        if cache is None:
            rows.append(record)
            continue
        post_frame = cache[(cache["label"] >= signal) & (cache["label"] <= cutoff)]
        post = list(zip(post_frame["label"], post_frame["stage"]))
        replicated, first_prog = replicate_ledger_lifecycle(entry_stage, post)
        ledger_first = row.get("first_progressed_date")
        ledger_first = pd.Timestamp(ledger_first) if isinstance(ledger_first, str) and ledger_first else None
        end = holding_end(row, cutoff)
        held_frame = post_frame[post_frame["effective"] <= end]
        held = list(zip(held_frame["label"], held_frame["stage"]))
        pre_frame = cache[cache["label"] < signal]
        pre = list(zip(pre_frame["label"], pre_frame["stage"]))
        holding = classify_holding(entry_stage, held)
        handoff_origin = (walk_back_origin(holding["sequence"], holding["first_direct_index"], pre)
                          if holding["first_direct_index"] is not None else None)
        months_prog_to_handoff = (holding["first_direct_index"] - holding["first_progressed_index"]
                                  if holding["group"] == HOLDING_B else None)
        strict = classify_strict(entry_stage, held)
        strict_full = classify_strict(entry_stage, post)
        entry_origin = walk_back_origin([(None, entry_stage)], 1, pre) if entry_stage == "EARLY_TREND" else None
        last_pre = next((s for _, s in reversed(pre) if s not in VALID_SKIP), None)
        record.update({
            "replicated_lifecycle_class": replicated,
            "replicated_first_progressed": first_prog.strftime("%Y-%m-%d") if first_prog is not None else None,
            "replication_match": bool(replicated == row["lifecycle_class"] and first_prog == ledger_first),
            "holding_end": end.strftime("%Y-%m-%d"),
            "holding_group": holding["group"], "holding_subgroup": holding["subgroup"],
            "handoff_origin": handoff_origin,
            "handoff_origin_group": origin_group(handoff_origin) if handoff_origin else None,
            "months_first_progressed_to_handoff": months_prog_to_handoff,
            "strict_class": strict, "strict_class_through_cutoff": strict_full,
            "entry_origin": entry_origin, "entry_origin_group": origin_group(entry_origin) if entry_origin else None,
            "last_pre_entry_month_stage": last_pre,
            "held_path": compress_path(holding["sequence"]),
            "post_entry_path_to_cutoff": compress_path([(None, entry_stage)] + post),
        })
        rows.append(record)
    return pd.DataFrame(rows).set_index("row_index")


def build_panels(stages: dict[tuple[str, str, str], pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    panels: dict[str, pd.DataFrame] = {}
    gate: dict[str, Any] = {}
    simple = {w: wl.load_window_ledger(w) for w in SIMPLE_WINDOWS}
    wl.input_gate(simple)
    for window, frame in simple.items():
        data = frame[frame["terminal_return"].notna()].copy()
        cutoffs = pd.Series(SIMPLE_CUTOFF[window], index=data.index)
        panels[f"SIMPLE_{window}"] = data.join(trade_paths(data, cutoffs, stages))
    pooled, dedup_audit = wl.deduplicate(simple, wl.certification_exclusion_identities())
    cutoffs = pooled["window_cutoff"]
    panels["SIMPLE_POOLED_DEDUP"] = pooled.join(trade_paths(pooled, cutoffs, stages))
    gate["dedup"] = {k: dedup_audit[k] for k in ("dedup_trade_count", "duplicate_rows_removed", "representative_window_counts")}
    for window in REALISTIC_RUNS:
        trades, count_gate = load_realistic(window)
        gate[f"REALISTIC_{window}_count_gate"] = count_gate
        data = trades[trades["terminal_return"].notna()].copy()
        cutoffs = pd.Series(REALISTIC_RUNS[window]["cutoff"], index=data.index)
        paths = data.join(trade_paths(data, cutoffs, stages))
        panels[f"REALISTIC_{window}_ELIGIBLE"] = paths
        panels[f"REALISTIC_{window}_FILLED"] = paths[paths["filled"]]
    return panels, gate


def replication_gate(panels: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows, kept = [], {}
    for name, frame in panels.items():
        n = len(frame)
        found = frame["cache_found"].fillna(False).astype(bool)
        match = frame["replication_match"].fillna(False).astype(bool) & found
        mismatch = frame[~match]
        rows.append({
            "panel": name, "rows": n, "cache_missing": int((~found).sum()), "replication_match": int(match.sum()),
            "mismatch": int(n - match.sum()), "mismatch_pct": wl._round((n - match.sum()) / n * 100.0) if n else None,
            "mismatch_with_lifecycle_event": int(mismatch.get("lifecycle_event_type", pd.Series(dtype=object)).notna().sum()
                                                 + mismatch.get("settlement_date", pd.Series(dtype=object)).notna().sum()),
            "mismatch_examples": json.dumps(mismatch[["ticker", "trade_id", "lifecycle_class", "replicated_lifecycle_class",
                                                      "first_progressed_date", "replicated_first_progressed"]].head(5).to_dict("records"),
                                            ensure_ascii=False, default=str) if len(mismatch) else "",
        })
        kept[name] = frame[match].copy()
    return pd.DataFrame(rows), kept


def group_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    row = wl.lifecycle_metrics(frame)
    if len(frame):
        exits = frame["exit_type"].value_counts(normalize=True)
        row["exit_type_mix"] = "; ".join(f"{k}={v * 100:.1f}%" for k, v in exits.items())
        row["open_at_cutoff_count"] = int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum())
    return row


def compare_groups(first: pd.DataFrame, second: pd.DataFrame) -> dict[str, Any]:
    result = wl.lifecycle_compare(first, second)
    result["tier"] = tier(result["first_n"], result["second_n"])
    returns = pd.concat([first["terminal_return"], second["terminal_return"]]).astype(float)
    result["loss_30_count"] = int((returns <= -30).sum())
    result["loss_50_count"] = int((returns <= -50).sum())
    result["deep_loss_generalizable"] = bool(result["loss_30_count"] >= TIER_RULES["deep_loss_min"]["LOSS_30"]
                                             and result["loss_50_count"] >= TIER_RULES["deep_loss_min"]["LOSS_50"])
    return result


HOLDING_VIEWS = {
    HOLDING_A: lambda f: f["holding_group"] == HOLDING_A,
    HOLDING_B: lambda f: f["holding_group"] == HOLDING_B,
    HOLDING_C: lambda f: f["holding_group"] == HOLDING_C,
    HOLDING_C1: lambda f: f["holding_subgroup"] == HOLDING_C1,
    HOLDING_C2: lambda f: f["holding_subgroup"] == HOLDING_C2,
}
HOLDING_COMPARISONS = [
    ("A_vs_C1", HOLDING_A, HOLDING_C1), ("B_vs_C1", HOLDING_B, HOLDING_C1), ("A_vs_B", HOLDING_A, HOLDING_B),
    ("A_vs_C", HOLDING_A, HOLDING_C),
]
ORIGIN_VIEWS = {
    **{f"ORIGIN_{g}": (lambda f, g=g: f["handoff_origin_group"] == g) for g in ORIGIN_GROUPS + ["OTHER"]},
    "PURE_NORMAL_CYCLE_TRANSITION": lambda f: f["handoff_origin_group"] == "TRANSITION",
    "WEAK_BASE_TRANSITION_ORIGIN": lambda f: f["handoff_origin_group"].isin(["WEAK", "BASE", "TRANSITION"]),
    "NON_WBT_ORIGIN": lambda f: f["handoff_origin_group"].isin(["PROGRESSED", "OTHER"]),
}
STRICT_VIEWS = {
    STRICT_PASS: lambda f: f["strict_class"] == STRICT_PASS,
    STRICT_FAIL: lambda f: f["strict_class"] == STRICT_FAIL,
    STRICT_NONE: lambda f: f["strict_class"] == STRICT_NONE,
    "PURE_ENTRY_CYCLE_TRANSITION_ET_PASS": lambda f: (f["strict_class"] == STRICT_PASS) & (f["entry_origin_group"] == "TRANSITION"),
    "PASS_NON_TRANSITION_ORIGIN": lambda f: (f["strict_class"] == STRICT_PASS) & (f["entry_origin_group"] != "TRANSITION"),
    **{f"PASS_ORIGIN_{g}": (lambda f, g=g: (f["strict_class"] == STRICT_PASS) & (f["entry_origin_group"] == g)) for g in ORIGIN_GROUPS + ["OTHER"]},
    **{f"FAIL_TO_{s}": (lambda f, s=s: (f["strict_class"] == STRICT_FAIL) & f["held_path"].str.split(">").str[1].str.startswith(s)) for s in ("TRANSITION", "BASE", "WEAK")},
}
STRICT_COMPARISONS = [
    ("PASS_vs_FAIL", STRICT_PASS, STRICT_FAIL),
    ("PURE_ENTRY_CYCLE_vs_FAIL", "PURE_ENTRY_CYCLE_TRANSITION_ET_PASS", STRICT_FAIL),
    ("PURE_ENTRY_CYCLE_vs_PASS_OTHER_ORIGIN", "PURE_ENTRY_CYCLE_TRANSITION_ET_PASS", "PASS_NON_TRANSITION_ORIGIN"),
]


def profile_rows(panels: dict[str, pd.DataFrame], views: dict[str, Any], scope: pd.Series | None = None, base_filter=None) -> list[dict[str, Any]]:
    rows = []
    for panel, frame in panels.items():
        data = frame if base_filter is None else frame[base_filter(frame)]
        for name, rule in views.items():
            subset = data[rule(data).fillna(False)]
            rows.append({"panel": panel, "group": name, "panel_n": int(len(data)), **group_metrics(subset)})
    return rows


def comparison_rows(panels: dict[str, pd.DataFrame], views: dict[str, Any], comparisons: list[tuple[str, str, str]], base_filter=None, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = []
    for panel, frame in panels.items():
        data = frame if base_filter is None else frame[base_filter(frame)]
        for name, first, second in comparisons:
            a = data[views[first](data).fillna(False)]
            b = data[views[second](data).fillna(False)]
            rows.append({"panel": panel, "comparison": name, "first": first, "second": second, **(extra or {}), **compare_groups(a, b)})
    return rows


def repetition_summary(table: pd.DataFrame, comparison: str) -> dict[str, Any]:
    sub = table[table["comparison"] == comparison]
    out = {}
    for family, prefix in (("simple_windows", "SIMPLE_P"), ("realistic_eligible", "REALISTIC_"), ):
        rows = sub[sub["panel"].str.startswith(prefix)]
        if family == "realistic_eligible":
            rows = rows[rows["panel"].str.endswith("ELIGIBLE")]
        ev = rows[rows["tier"] != "COUNTS_ONLY"]
        out[family] = {
            "panels": {r["panel"]: {"tier": r["tier"], "n": [int(r["first_n"]), int(r["second_n"])],
                                    "mean_diff": r.get("mean_return_diff"), "auc": r.get("return_auc")} for _, r in rows.iterrows()},
            "tier_ok_panels": int(len(ev)),
            "tier_ok_mean_diff_positive": int((ev["mean_return_diff"] > 0).sum()) if len(ev) else 0,
            "tier_ok_auc_above_half": int((ev["return_auc"] > 0.5).sum()) if len(ev) else 0,
        }
    filled = sub[sub["panel"].str.endswith("FILLED")]
    out["realistic_filled"] = {r["panel"]: {"tier": r["tier"], "n": [int(r["first_n"]), int(r["second_n"])],
                                            "mean_diff": r.get("mean_return_diff"), "auc": r.get("return_auc")} for _, r in filled.iterrows()}
    pooled = sub[sub["panel"] == "SIMPLE_POOLED_DEDUP"]
    if len(pooled):
        r = pooled.iloc[0]
        out["simple_pooled"] = {"tier": r["tier"], "n": [int(r["first_n"]), int(r["second_n"])], "mean_diff": r.get("mean_return_diff"),
                                "auc": r.get("return_auc"), "favorable_unfavorable": [r.get("favorable"), r.get("unfavorable")]}
    return out


def run_analyze(network_audit: dict[str, int], cache_path: Path = STAGE_CACHE_PATH) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stage_audit = json.loads(STAGE_AUDIT_PATH.read_text(encoding="utf-8")) if cache_path == STAGE_CACHE_PATH else None
    if stage_audit is not None:
        if stage_audit["cache_sha256"] != wl.sha256_file(cache_path):
            raise RuntimeError("STAGE_CACHE_SHA_MISMATCH")
        if stage_audit["leakage_check"]["mismatch_count"]:
            raise RuntimeError("STAGE_LEAKAGE_CHECK_FAILED")
    stages = load_stage_cache(cache_path)
    panels_all, gate = build_panels(stages)
    gate_table, panels = replication_gate(panels_all)
    gate_table.to_csv(OUTPUT_DIR / "replication_gate.csv", index=False)
    current_authority = gate_table[~gate_table["panel"].isin(["SIMPLE_P2-2"])]
    if (current_authority["mismatch_pct"] > 1.0).any():
        print(gate_table[["panel", "rows", "mismatch", "mismatch_pct"]].to_string(index=False))
        raise RuntimeError("REPLICATION_GATE_FAILED")

    # A∪B는 보유 경로가 전체 경로의 앞부분이므로 원장 NORMAL의 부분집합이어야 한다.
    for name, frame in panels.items():
        ab = frame["holding_group"].isin([HOLDING_A, HOLDING_B])
        if (ab & (frame["lifecycle_class"] != "NORMAL_EARLY_TREND_HANDOFF")).any():
            raise RuntimeError(f"HOLDING_NORMAL_NOT_SUBSET_OF_LEDGER_NORMAL:{name}")
        partition = frame["holding_group"].isin([HOLDING_A, HOLDING_B, HOLDING_C]).sum()
        if partition != len(frame) or frame["holding_subgroup"].isna().any():
            raise RuntimeError(f"HOLDING_PARTITION_INCOMPLETE:{name}")

    path_columns = ["ticker", "isu_cd", "trade_id", "pair_id", "entry_signal_date", "entry_pattern_a_stage", "lifecycle_class",
                    "trade_status", "exit_type", "exit_signal_date", "terminal_return", "holding_end", "holding_group", "holding_subgroup",
                    "handoff_origin", "months_first_progressed_to_handoff", "strict_class", "strict_class_through_cutoff",
                    "entry_origin", "last_pre_entry_month_stage", "held_path", "post_entry_path_to_cutoff"]
    path_rows = []
    for name, frame in panels.items():
        if name.endswith("FILLED"):
            continue
        part = frame.reindex(columns=path_columns).copy()
        part.insert(0, "panel", name)
        if "filled" in frame:
            part["filled"] = frame["filled"]
        path_rows.append(part)
    pd.concat(path_rows).to_csv(OUTPUT_DIR / "trade_stage_paths.csv", index=False)

    crosstab_rows = []
    for name, frame in panels.items():
        table = pd.crosstab(frame["lifecycle_class"], frame["holding_subgroup"])
        for ledger_class, row in table.iterrows():
            crosstab_rows.append({"panel": name, "ledger_lifecycle_class": ledger_class, **{k: int(v) for k, v in row.items()}})
    crosstab = pd.DataFrame(crosstab_rows).fillna(0)
    crosstab.to_csv(OUTPUT_DIR / "ledger_label_vs_holding_crosstab.csv", index=False)

    holding_profile = pd.DataFrame(profile_rows(panels, HOLDING_VIEWS))
    holding_profile.to_csv(OUTPUT_DIR / "holding_lifecycle_profile.csv", index=False)
    holding_cmp = pd.DataFrame(comparison_rows(panels, HOLDING_VIEWS, HOLDING_COMPARISONS))
    holding_cmp.to_csv(OUTPUT_DIR / "holding_lifecycle_comparison.csv", index=False)

    normal_filter = lambda f: f["holding_group"].isin([HOLDING_A, HOLDING_B])  # noqa: E731
    origin_profile = pd.DataFrame(profile_rows(panels, ORIGIN_VIEWS, base_filter=normal_filter))
    origin_profile.to_csv(OUTPUT_DIR / "handoff_origin_profile.csv", index=False)
    origin_rows = []
    for entry_stage in ("TRANSITION", "EARLY_TREND"):
        stage_filter = lambda f, s=entry_stage: normal_filter(f) & (f["entry_pattern_a_stage"].str.upper() == s)  # noqa: E731
        origin_rows += comparison_rows(panels, ORIGIN_VIEWS, [("PURE_TRANSITION_vs_NON_WBT", "PURE_NORMAL_CYCLE_TRANSITION", "NON_WBT_ORIGIN"),
                                                              ("PURE_TRANSITION_vs_BASE", "PURE_NORMAL_CYCLE_TRANSITION", "ORIGIN_BASE")],
                                       base_filter=stage_filter, extra={"entry_stage": entry_stage})
    origin_rows += comparison_rows(panels, ORIGIN_VIEWS, [("PURE_TRANSITION_vs_NON_WBT", "PURE_NORMAL_CYCLE_TRANSITION", "NON_WBT_ORIGIN")],
                                   base_filter=normal_filter, extra={"entry_stage": "ALL"})
    origin_cmp = pd.DataFrame(origin_rows)
    origin_cmp.to_csv(OUTPUT_DIR / "handoff_origin_comparison.csv", index=False)
    origin_x_entry = []
    for name, frame in panels.items():
        data = frame[normal_filter(frame)]
        table = pd.crosstab(data["entry_pattern_a_stage"], data["handoff_origin_group"])
        for stage, row in table.iterrows():
            origin_x_entry.append({"panel": name, "entry_stage": stage, **{k: int(v) for k, v in row.items()}})
    pd.DataFrame(origin_x_entry).fillna(0).to_csv(OUTPUT_DIR / "handoff_origin_by_entry_stage.csv", index=False)

    early = lambda f: f["entry_pattern_a_stage"].str.upper() == "EARLY_TREND"  # noqa: E731
    strict_profile = pd.DataFrame(profile_rows(panels, STRICT_VIEWS, base_filter=early))
    strict_profile.to_csv(OUTPUT_DIR / "strict_entry_profile.csv", index=False)
    strict_cmp = pd.DataFrame(comparison_rows(panels, STRICT_VIEWS, STRICT_COMPARISONS, base_filter=early))
    strict_cmp.to_csv(OUTPUT_DIR / "strict_entry_comparison.csv", index=False)
    sensitivity_views = {k.replace("STRICT", "CUTOFF"): (lambda f, k=k: f["strict_class_through_cutoff"] == k) for k in (STRICT_PASS, STRICT_FAIL, STRICT_NONE)}
    strict_sensitivity = pd.DataFrame(profile_rows(panels, sensitivity_views, base_filter=early))
    strict_sensitivity.insert(0, "note", "POST_EXIT_OBSERVATIONS_INCLUDED_SENSITIVITY_ONLY")
    strict_sensitivity.to_csv(OUTPUT_DIR / "strict_entry_sensitivity_through_cutoff.csv", index=False)
    entry_agreement = {}
    for name, frame in panels.items():
        data = frame[early(frame)]
        entry_agreement[name] = {"early_trend_entries": int(len(data)),
                                 "last_pre_entry_month_stage_is_early_trend_pct": wl._round((data["last_pre_entry_month_stage"] == "EARLY_TREND").mean() * 100.0) if len(data) else None,
                                 "strict_counts": {k: int(v) for k, v in data["strict_class"].value_counts().items()},
                                 "entry_origin_counts": {k: int(v) for k, v in data["entry_origin_group"].value_counts().items()}}

    group_b = {}
    for name, frame in panels.items():
        b = frame[frame["holding_group"] == HOLDING_B]
        ledger_normal = frame[frame["lifecycle_class"] == "NORMAL_EARLY_TREND_HANDOFF"]
        group_b[name] = {
            "late_normalized_n": int(len(b)),
            "late_normalized_exit_mix": {k: int(v) for k, v in b["exit_type"].value_counts().items()},
            "months_first_progressed_to_handoff_median": wl._round(b["months_first_progressed_to_handoff"].median()) if len(b) else None,
            "ledger_normal_n": int(len(ledger_normal)),
            "ledger_normal_no_progressed_while_held_n": int((ledger_normal["holding_subgroup"] == HOLDING_C2).sum()),
            "ledger_normal_no_progressed_while_held_pct": wl._round((ledger_normal["holding_subgroup"] == HOLDING_C2).mean() * 100.0) if len(ledger_normal) else None,
        }

    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_LIFECYCLE_REFINEMENT_STRICT_HANDOFF_V01",
        "strategy_id": STRATEGY_ID,
        "scope": "CONTROL only; certified simple (5) and realistic (3) ledgers; monthly Pattern A stages rebuilt with the runner's snapshot path; no backtest, strategy change, threshold change, or network",
        "stage_cache": {k: v for k, v in (stage_audit or {}).items() if k != "load_errors"},
        "count_gates": gate,
        "replication_gate": gate_table.drop(columns=["mismatch_examples"]).to_dict("records"),
        "observation_contract": {
            "entry_stage": "ledger entry_pattern_a_stage = Pattern A stage evaluated at the completed weekly signal close (entry_signal_date); execution at the next session open",
            "monthly_stage": "a month label's completed snapshot is observable at the last trading close on or before the label (effective_date); labels with signal week <= label <= window cutoff are post-entry",
            "holding_window": "post-entry labels whose effective_date <= exit_signal_date (settlement_date for settled trades, window cutoff for open trades)",
            "ledger_lifecycle_class": "uses every post-entry label through the window cutoff, including labels after exit",
        },
        "rules": {"tiers": TIER_RULES, "holding_groups": [HOLDING_A, HOLDING_B, HOLDING_C], "holding_c_split": [HOLDING_C1, HOLDING_C2],
                  "origin_walk_back": "skip EARLY_TREND and UNAVAILABLE backwards through the held path, then the entry stage, then pre-entry labels; UNKNOWN if history runs out (grouped as OTHER)",
                  "strict": "entry stage EARLY_TREND; first valid non-EARLY_TREND stage while held: PROGRESSED=PASS, other=FAIL, none=NO_NEXT_STAGE_BEFORE_EXIT_OR_CUTOFF"},
        "late_normalized_and_ledger_normal_diagnostic": group_b,
        "strict_entry_counts": entry_agreement,
        "repetition": {c: repetition_summary(holding_cmp, c) for c, _, _ in HOLDING_COMPARISONS}
                      | {f"strict_{c}": repetition_summary(strict_cmp, c) for c, _, _ in STRICT_COMPARISONS},
        "network_requests": network_audit["count"],
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(gate_table[["panel", "rows", "mismatch", "mismatch_pct"]].to_string(index=False))


# ---------------------------------------------------------------------------
# 8개 인증 run 보관 inventory (inventory)
# ---------------------------------------------------------------------------

BACKTEST_ROOT = ROOT / "artifacts/backtests"
INVENTORY_CSV = BACKTEST_ROOT / "backtest_archive_inventory_v01.csv"
INVENTORY_RUNS_CSV = BACKTEST_ROOT / "backtest_archive_runs_v01.csv"
ARCHIVE_RUNS: list[dict[str, Any]] = [
    {"run": "SIMPLE_P1", "verdict": "P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS",
     "paths": ["p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01",
               "p1_neg40_weak_protect_v01/diagnostics/unavailable_stage_12_v01"]},
    {"run": "SIMPLE_P2-1", "verdict": "P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS",
     "paths": ["p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02",
               "p2_1_neg40_weak_protect_v01/preflight_raw_mcap_source_correction_v01"]},
    {"run": "SIMPLE_P2-2", "verdict": "COMPLETE / PROMISING; ledger aggregate reconciliation PASS",
     "paths": ["p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01",
               "p2_2_neg40_weak_protect_v01/lifecycle_settlement_evidence_v01.json"]},
    {"run": "SIMPLE_P3-1", "verdict": "P3_1_REPLAY_PASS; certified with authoritative exclusion",
     "paths": ["p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01"]},
    {"run": "SIMPLE_P3-2", "verdict": "P3_2_REPLAY_PASS; certified with authoritative exclusion",
     "paths": ["p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01"]},
    {"run": "REALISTIC_P2-1", "verdict": "P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
     "paths": ["p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01"]},
    {"run": "REALISTIC_P2-2", "verdict": "P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
     "paths": ["p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01"]},
    {"run": "REALISTIC_P3-2", "verdict": "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
     "paths": ["p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01"]},
]
EXCLUDED_NAMES = {".DS_Store"}
MAX_ARCHIVE_FILE_BYTES = 50 * 1024 * 1024
FILE_CATEGORIES = [
    ("final_report", lambda n: n.endswith(".md")),
    ("control_ledger", lambda n: n in {"control_trades.csv", "control_strategy_trades.csv"}),
    ("candidate_ledger", lambda n: n in {"candidate_trades.csv", "candidate_strategy_trades.csv"}),
    ("paired_identity_audit", lambda n: n in {"paired_trades.csv", "paired_identity_audit.csv"} or n.endswith("_matched_trades.csv")),
    ("lifecycle_soft_event", lambda n: "soft_events" in n or "lifecycle_settlement" in n),
    ("portfolio_trades", lambda n: "portfolio_events" in n or "portfolio_trades" in n or n == "skipped_entries.csv"),
    ("daily_equity", lambda n: "daily_equity" in n),
    ("pit_mcap_audit", lambda n: "pit_mcap" in n or "raw_mcap" in n or "raw_store_coverage" in n or n == "preflight_pit_partition_coverage.json"),
    ("valuation_audit", lambda n: "valuation" in n),
    ("exclusion_identity_audit", lambda n: "universe_audit" in n or "reason_audit" in n or "unresolved" in n or "unavailable_stage" in n),
    ("certification", lambda n: "certification" in n),
    ("manifest", lambda n: n in {"run_manifest.json", "execution_contract.json", "run_metadata.json"}),
    ("summary", lambda n: "summary" in n),
    ("preflight_validation", lambda n: "benchmark" in n or "preflight" in n or "failure" in n or n.endswith("_audit.json")),
]
REQUIRED_SIMPLE = ["summary", "manifest", "control_ledger", "candidate_ledger", "paired_identity_audit", "lifecycle_soft_event"]
EXPECTED_NAMED_FILES = {"SIMPLE": ["run_manifest.json", "summary.json"], "REALISTIC": ["final_report.md", "run_manifest.json", "summary.json"]}
REQUIRED_REALISTIC = ["final_report", "summary", "manifest", "control_ledger", "candidate_ledger", "portfolio_trades",
                      "daily_equity", "pit_mcap_audit", "valuation_audit", "exclusion_identity_audit"]


def _category(name: str) -> str:
    for label, rule in FILE_CATEGORIES:
        if rule(name):
            return label
    return "other"


def _git_lines(*args: str) -> set[str]:
    import subprocess

    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return set(line for line in out.splitlines() if line)


def run_integrity(run: str, files: dict[str, Path]) -> dict[str, Any]:
    """인증 문서가 기록한 SHA 또는 인증 집계 재현으로 로컬 파일이 인증 당시와 같은지 확인한다."""
    checks: list[dict[str, Any]] = []

    def compare(name: str, expected: str, path: Path | None) -> None:
        observed = wl.sha256_file(path) if path is not None and path.exists() else None
        checks.append({"file": name, "expected": expected, "observed": observed, "match": observed == expected})

    by_name = {p.name: p for p in files.values()}
    if run == "SIMPLE_P1":
        base = BACKTEST_ROOT / ARCHIVE_RUNS[0]["paths"][0]
        cert = json.loads((base / "raw_only_exclusion_closure_v02/p1_raw_only_certification_v02.json").read_text(encoding="utf-8"))
        for name, sha in cert["source_raw_sha256_before"].items():
            compare(name, sha, base / name)
        compare("run_manifest.json", cert["source_run_manifest_sha256_before"], base / "run_manifest.json")
        method = "P1 certification source_raw_sha256_before / source_run_manifest_sha256_before"
    elif run == "SIMPLE_P2-1":
        base = BACKTEST_ROOT / ARCHIVE_RUNS[1]["paths"][0]
        cert = json.loads((base / "raw_only_lifecycle_closure_v01/p2_1_raw_only_certification_v01.json").read_text(encoding="utf-8"))
        for name, sha in cert["source_sha256_before"].items():
            compare(name, sha, base / name)
        method = "P2-1 certification source_sha256_before"
    elif run in {"SIMPLE_P2-2", "SIMPLE_P3-1", "SIMPLE_P3-2"}:
        window = run.split("_", 1)[1]
        gate = wl.input_gate({w: wl.load_window_ledger(w) for w in wl.WINDOW_ORDER})[window]
        checks.append({"file": "control_trades.csv", "expected": "5-window synthesis CONTROL aggregates", "observed": "reproduced", "match": bool(gate["match"])})
        method = "no per-file SHA recorded; CONTROL aggregates reproduce the 5-window synthesis exactly"
        if run == "SIMPLE_P3-2":
            realistic = json.loads((REALISTIC_RUNS["P3-2"]["run_dir"] / "summary.json").read_text(encoding="utf-8"))
            compare("p3_2_summary.json", realistic["data_authority"]["p3_2_certification_summary_sha256"], by_name.get("p3_2_summary.json"))
            method += "; p3_2_summary.json SHA matches the value recorded by the realistic P3-2 run"
    else:
        window = run.split("_", 1)[1]
        load_realistic(window)
        checks.append({"file": "control_portfolio_events.csv", "expected": "certified CONTROL counts", "observed": "reproduced", "match": True})
        summary = json.loads((REALISTIC_RUNS[window]["run_dir"] / "summary.json").read_text(encoding="utf-8"))
        frozen = (summary.get("portfolio_replay") or {}).get("frozen_source_hashes_sha256") or {}
        for name, sha in frozen.items():
            compare(name, sha, by_name.get(name))
        method = "CONTROL eligible/filled/realized/cash-skip counts reproduce summary.csv" + ("; frozen_source_hashes_sha256" if frozen else "")
    return {"method": method, "checks": checks, "pass": all(c["match"] for c in checks)}


def run_inventory() -> None:
    tracked = _git_lines("ls-files", "artifacts/backtests")
    pushed = _git_lines("ls-tree", "-r", "--name-only", "origin/main", "artifacts/backtests")
    modified = _git_lines("diff", "--name-only", "HEAD", "--", "artifacts/backtests")
    file_rows, run_rows = [], []
    for spec in ARCHIVE_RUNS:
        files: dict[str, Path] = {}
        for rel in spec["paths"]:
            target = BACKTEST_ROOT / rel
            candidates = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
            for path in candidates:
                if path.name in EXCLUDED_NAMES or "__pycache__" in path.parts:
                    continue
                files[str(path.relative_to(ROOT))] = path
        categories = set()
        for rel, path in files.items():
            category = _category(path.name)
            categories.add(category)
            size = path.stat().st_size
            file_rows.append({
                "run": spec["run"], "path": rel, "category": category, "bytes": size, "sha256": wl.sha256_file(path),
                "git_tracked": rel in tracked, "in_origin_main": rel in pushed, "modified_vs_head": rel in modified,
                "over_size_limit": size > MAX_ARCHIVE_FILE_BYTES,
            })
        run_files = [r for r in file_rows if r["run"] == spec["run"]]
        n_pushed = sum(r["in_origin_main"] for r in run_files)
        status = "ALREADY_PUSHED" if n_pushed == len(run_files) else ("PARTIALLY_TRACKED" if n_pushed else "LOCAL_ONLY")
        required = REQUIRED_REALISTIC if spec["run"].startswith("REALISTIC") else REQUIRED_SIMPLE
        integrity = run_integrity(spec["run"], files)
        run_rows.append({
            "run": spec["run"], "verdict": spec["verdict"], "paths": "|".join(spec["paths"]), "files": len(run_files),
            "bytes": sum(r["bytes"] for r in run_files), "files_in_origin_main_before": n_pushed, "status_before": status,
            "missing_categories": "|".join(c for c in required if c not in categories),
            "missing_named_files": "|".join(
                name for name in EXPECTED_NAMED_FILES[spec["run"].split("_", 1)[0]]
                if name not in {Path(r["path"]).name for r in run_files}
            ),
            "integrity_method": integrity["method"], "integrity_pass": integrity["pass"],
            "integrity_checks": json.dumps(integrity["checks"], ensure_ascii=False),
            "modified_tracked_files": sum(r["modified_vs_head"] for r in run_files),
            "over_size_limit_files": sum(r["over_size_limit"] for r in run_files),
        })
    pd.DataFrame(file_rows).to_csv(INVENTORY_CSV, index=False)
    pd.DataFrame(run_rows).to_csv(INVENTORY_RUNS_CSV, index=False)
    print(pd.DataFrame(run_rows)[["run", "files", "bytes", "files_in_origin_main_before", "status_before", "missing_categories",
                                  "missing_named_files", "integrity_pass", "modified_tracked_files", "over_size_limit_files"]].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["stages", "analyze", "inventory"])
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    audit = {"count": 0}
    with wl.network_guard(audit):
        if args.step == "stages":
            run_stages(args.workers, args.limit, args.single, args.out)
        elif args.step == "inventory":
            run_inventory()
        else:
            run_analyze(audit)
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
