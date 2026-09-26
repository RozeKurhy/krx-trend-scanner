"""A FAST Core V2 — A(FIRST_PROGRESSED_NORMAL) vs C1 divergence analysis V01.

보유 lifecycle 기준 A와 C1(보유 중 PROGRESSED 도달, 직접 EARLY_TREND → PROGRESSED handoff 없음)을
보유 중 첫 PROGRESSED 시점(anchor)을 기준으로 비교한다.

- 입력: Git에 보관된 인증 CONTROL 원장 8개(단순 5, 현실적 3)와
  `lifecycle_refinement_strict_handoff_v01`의 월간 stage 캐시·재현 게이트.
- 보유 구간 밖의 stage와 가격은 쓰지 않는다. 원장 `lifecycle_class`(윈도우 lifecycle)는 그룹 정의에 쓰지 않는다.
- 가격 경로는 현재 Repository V2 일봉으로 만들고, 거래마다 원장의 MFE / MAE / terminal_return을
  러너와 같은 방식으로 재현하는지 확인한다(가격 parity 게이트).

새 백테스트, 전략·청산 규칙 구현, threshold sweep, 네트워크 호출은 하지 않는다.

사용법:
    python scripts/analyze_fastcore_v2_a_vs_c1_divergence_v01.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import scripts.analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01 as lc  # noqa: E402
import scripts.analyze_fastcore_v2_winner_loser_profile_v01 as wl  # noqa: E402

OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/a_vs_c1_divergence_v01"
GROUP_A = lc.HOLDING_A
GROUP_C1 = lc.HOLDING_C1
THRESHOLDS = [15, 20, 30, 40, 50, 60]
RETREAT_STAGES = ["EARLY_TREND", "TRANSITION", "BASE", "WEAK"]
PRICE_PARITY_TOLERANCE = 0.011
PANEL_EXCLUSION_MISMATCH_PCT = 1.0
TIERS = {"evaluable_min_n": 20, "descriptive_min_n": 10}


# ---------------------------------------------------------------------------
# 거래별 경로 복원 (순수 함수)
# ---------------------------------------------------------------------------

def held_labels(cache: pd.DataFrame, signal: pd.Timestamp, cutoff: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """보유 구간 월 라벨: signal <= 라벨 <= cutoff 이고 관측일 <= 보유 종료."""
    post = cache[(cache["label"] >= signal) & (cache["label"] <= cutoff)]
    return post[post["effective"] <= end].reset_index(drop=True)


def stage_events(entry_stage: str, held: pd.DataFrame) -> dict[str, Any]:
    """anchor(보유 중 첫 PROGRESSED)와 그 전후의 stage 사건을 뽑는다."""
    stages = [(None, None, entry_stage, None)] + list(zip(held["label"], held["effective"], held["stage"], held["score"]))
    valid = [(i, s) for i, s in enumerate(stages) if s[2] not in lc.VALID_SKIP]
    anchor = next((i for i, s in valid if s[2] == "PROGRESSED"), None)
    out: dict[str, Any] = {"anchor_index": anchor}
    if anchor is None:
        return out
    prev_valid = next((s[2] for i, s in reversed(valid) if i < anchor), None)
    pre_valid = [s[2] for i, s in valid if i < anchor]
    transitions = sum(1 for a, b in zip(pre_valid, pre_valid[1:]) if a != b)
    after = [(i, s) for i, s in valid if i > anchor]
    departure = next(((i, s) for i, s in after if s[2] != "PROGRESSED"), None)
    run_length = 1 + sum(1 for _ in _takewhile_progressed(after))
    returned = departure is not None and any(s[2] == "PROGRESSED" for i, s in after if i > departure[0])
    first_stage = {st: next((s for i, s in after if s[2] == st), None) for st in RETREAT_STAGES}
    hwm, max_dd = None, 0.0
    for i, s in [(anchor, stages[anchor])] + after:
        if s[2] != "PROGRESSED" or s[3] is None or (isinstance(s[3], float) and math.isnan(s[3])):
            continue
        hwm = s[3] if hwm is None else max(hwm, s[3])
        max_dd = max(max_dd, hwm - s[3])
    out.update({
        "anchor_label": stages[anchor][0], "anchor_effective": stages[anchor][1], "anchor_score": stages[anchor][3],
        "stage_before_anchor": prev_valid,
        "pre_anchor_label_count": anchor, "pre_anchor_stage_transitions": transitions,
        "progressed_run_labels": run_length,
        "first_departure_stage": departure[1][2] if departure else None,
        "first_departure_label": departure[1][0] if departure else None,
        "first_departure_effective": departure[1][1] if departure else None,
        "returned_to_progressed_after_departure": bool(returned),
        "post_anchor_score_drawdown_max": round(max_dd, 2),
        "post_anchor_path": lc.compress_path([(None, s[2]) for _, s in [(anchor, stages[anchor])] + after]),
        **{f"first_{st.lower()}_effective": (first_stage[st][1] if first_stage[st] else None) for st in RETREAT_STAGES},
        **{f"ever_{st.lower()}_after_anchor": first_stage[st] is not None for st in RETREAT_STAGES},
    })
    return out


def _takewhile_progressed(after: list[tuple[int, tuple]]):
    for _, s in after:
        if s[2] != "PROGRESSED":
            return
        yield s


def holding_prices(daily: pd.DataFrame, row: pd.Series, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, float | None, pd.Timestamp | None]:
    """러너 `_refresh_outcome_metrics`와 같은 보유 일봉. 청산 거래는 [진입, 청산 체결일), 미청산은 cutoff까지."""
    entry = pd.Timestamp(row["entry_execution_date"])
    exit_exec = row.get("exit_execution_date")
    if isinstance(exit_exec, str) and exit_exec and row.get("exit_price") is not None and not pd.isna(row.get("exit_price")):
        exit_date = pd.Timestamp(exit_exec)
        return daily[(daily.index >= entry) & (daily.index < exit_date)], float(row["exit_price"]), exit_date
    return daily[(daily.index >= entry) & (daily.index <= cutoff)], None, None


def price_parity(daily: pd.DataFrame, row: pd.Series, cutoff: pd.Timestamp) -> dict[str, Any]:
    held, exit_open, _ = holding_prices(daily, row, cutoff)
    entry_open = float(row["entry_open"])
    if held.empty:
        return {"price_parity": False, "parity_reason": "EMPTY_HOLDING_DAILY"}
    highs = held["high"].tolist() + ([exit_open] if exit_open is not None else [])
    lows = held["low"].tolist() + ([exit_open] if exit_open is not None else [])
    terminal = (exit_open if exit_open is not None else float(held.iloc[-1]["close"]))
    rec = {
        "recomputed_mfe": round((max(highs) / entry_open - 1.0) * 100.0, 2),
        "recomputed_mae": round((min(lows) / entry_open - 1.0) * 100.0, 2),
        "recomputed_terminal": round((terminal - entry_open) / entry_open * 100.0, 2),
    }
    ok = all(abs(rec[f"recomputed_{k}"] - float(row[k if k != "terminal" else "terminal_return"])) <= PRICE_PARITY_TOLERANCE
             for k in ("mfe", "mae", "terminal"))
    return {**rec, "price_parity": bool(ok), "parity_reason": None if ok else "MFE_MAE_OR_TERMINAL_MISMATCH"}


def path_metrics(daily: pd.DataFrame, row: pd.Series, cutoff: pd.Timestamp, events: dict[str, Any], held_stages: pd.DataFrame) -> dict[str, Any]:
    held, exit_open, _ = holding_prices(daily, row, cutoff)
    entry_open = float(row["entry_open"])
    anchor = pd.Timestamp(events["anchor_effective"])
    pct = lambda v: round((float(v) / entry_open - 1.0) * 100.0, 2)  # noqa: E731
    pre = held[held.index <= anchor]
    post = held[held.index > anchor]
    closes = held["close"]
    out: dict[str, Any] = {
        "entry_to_anchor_trading_days": int(len(pre)),
        "return_at_anchor": pct(pre.iloc[-1]["close"]) if len(pre) else None,
        "pre_anchor_mfe": pct(pre["high"].max()) if len(pre) else None,
        "pre_anchor_mae": pct(pre["low"].min()) if len(pre) else None,
        "pre_anchor_max_close_drawdown": round(float((pre["close"] / pre["close"].cummax() - 1.0).min() * 100.0), 2) if len(pre) else None,
        "post_anchor_trading_days": int(len(post)),
        "post_anchor_mfe": pct(max(post["high"].max(), exit_open or -np.inf)) if len(post) else None,
        "post_anchor_mae": pct(min(post["low"].min(), exit_open or np.inf)) if len(post) else None,
    }
    final = float(row["terminal_return"])
    out["post_anchor_giveback"] = round(out["post_anchor_mfe"] - final, 2) if out["post_anchor_mfe"] is not None else None
    dep = events.get("first_departure_effective")
    if dep is not None and not pd.isna(dep):
        dep = pd.Timestamp(dep)
        at = closes[closes.index <= dep]
        out["return_at_first_departure"] = pct(at.iloc[-1]) if len(at) else None
        out["anchor_to_departure_trading_days"] = int(((held.index > anchor) & (held.index <= dep)).sum())
        out["departure_to_end_trading_days"] = int((held.index > dep).sum())
    else:
        out.update({"return_at_first_departure": None, "anchor_to_departure_trading_days": None, "departure_to_end_trading_days": None})
    stage_by_date = [(pd.Timestamp(e), s) for e, s in zip(held_stages["effective"], held_stages["stage"]) if s not in lc.VALID_SKIP]
    for threshold in THRESHOLDS:
        hit = closes[closes / entry_open - 1.0 <= -threshold / 100.0]
        key = f"touch_{threshold}"
        if hit.empty:
            out[f"{key}_date"] = None
            continue
        day = hit.index[0]
        seen = [str(row["entry_pattern_a_stage"]).upper()] + [s for e, s in stage_by_date if e <= day]
        distinct = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
        stage_now = distinct[-1]
        prev_stage = distinct[-2] if len(distinct) >= 2 else None
        later = closes[closes.index > day]
        out.update({
            f"{key}_date": day.strftime("%Y-%m-%d"),
            f"{key}_days_from_anchor": int(((held.index > anchor) & (held.index <= day)).sum()) if day > anchor else -int(((held.index > day) & (held.index <= anchor)).sum()),
            f"{key}_after_anchor": bool(day > anchor),
            f"{key}_stage": stage_now,
            f"{key}_prev_stage": prev_stage,
            f"{key}_after_departure": bool(dep is not None and not pd.isna(dep) and day > pd.Timestamp(dep)),
            f"{key}_later_max_return": pct(later.max()) if len(later) else None,
            f"{key}_recovered_to_breakeven": bool(len(later) and later.max() >= entry_open),
        })
    return out


def _num(value: Any, fmt: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    return "?" if math.isnan(number) else format(number, fmt)


def event_sequence(row: pd.Series) -> str:
    """보고서 비교용 요약 이벤트 시퀀스."""
    parts = [f"ENTRY[{row['entry_pattern_a_stage']}]",
             f"PROG@+{_num(row['entry_to_anchor_trading_days'], '.0f')}d({_num(row['return_at_anchor'], '+.0f')}%)"]
    if isinstance(row.get("first_departure_stage"), str):
        parts.append(f"DEPART:{row['first_departure_stage']}@+{_num(row['anchor_to_departure_trading_days'], '.0f')}d"
                     f"({_num(row['return_at_first_departure'], '+.0f')}%)")
        if row.get("returned_to_progressed_after_departure") is True:
            parts.append("RE-PROG")
    for threshold in (30, 50):
        if isinstance(row.get(f"touch_{threshold}_date"), str):
            parts.append(f"TOUCH-{threshold}[{row[f'touch_{threshold}_stage']}]@{_num(row[f'touch_{threshold}_days_from_anchor'], '+.0f')}d")
    end = "OPEN" if row["trade_status"] == "OPEN_AT_CUTOFF" else str(row["exit_type"])
    parts.append(f"{end}({_num(row['terminal_return'], '+.0f')}%)")
    return " > ".join(parts)


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

NUMERIC_PRE = ["entry_to_anchor_trading_days", "return_at_anchor", "pre_anchor_mfe", "pre_anchor_mae",
               "pre_anchor_max_close_drawdown", "pre_anchor_label_count", "pre_anchor_stage_transitions",
               "fast_score", "pre_entry_month_pattern_a_score", "anchor_score", "anchor_score_change", "anchor_market_cap_eok"]
NUMERIC_POST = ["post_anchor_mfe", "post_anchor_mae", "post_anchor_giveback", "terminal_return", "holding_days",
                "post_anchor_trading_days", "progressed_run_labels", "anchor_to_departure_trading_days",
                "return_at_first_departure", "departure_to_end_trading_days", "post_anchor_score_drawdown_max"]
CATEGORICAL = {
    "market": ["KOSDAQ"], "entry_pattern_a_stage": ["EARLY_TREND"], "stage_before_anchor": ["TRANSITION", "EARLY_TREND", "BASE", "WEAK"],
    "first_departure_stage": ["EARLY_TREND", "TRANSITION", "BASE", "WEAK"],
    "departed_progressed": ["True"], "returned_to_progressed_after_departure": ["True"],
    **{f"ever_{s.lower()}_after_anchor": ["True"] for s in RETREAT_STAGES},
    "trade_status": ["OPEN_AT_CUTOFF"],
}


def tier(a: int, b: int) -> str:
    n = min(a, b)
    return "EVALUABLE" if n >= TIERS["evaluable_min_n"] else ("DESCRIPTIVE" if n >= TIERS["descriptive_min_n"] else "INSUFFICIENT_EVIDENCE")


def compare(first: pd.DataFrame, second: pd.DataFrame, panel: str, comparison: str) -> list[dict[str, Any]]:
    rows = []
    t = tier(len(first), len(second))
    for feature in NUMERIC_PRE + NUMERIC_POST:
        a = pd.to_numeric(first.get(feature), errors="coerce").dropna()
        b = pd.to_numeric(second.get(feature), errors="coerce").dropna()
        auc = wl.rank_auc(a, b)
        rows.append({"panel": panel, "comparison": comparison, "tier": t, "feature": feature,
                     "phase": "PRE_OR_AT_ANCHOR" if feature in NUMERIC_PRE else "POST_ANCHOR",
                     "first_n": int(len(a)), "second_n": int(len(b)),
                     "first_median": wl._round(a.median()) if len(a) else None, "second_median": wl._round(b.median()) if len(b) else None,
                     "first_mean": wl._round(a.mean()) if len(a) else None, "second_mean": wl._round(b.mean()) if len(b) else None,
                     "auc": wl._round(auc), "effect": wl._round(auc - 0.5) if auc is not None else None})
    for feature, levels in CATEGORICAL.items():
        for level in levels:
            a = first[feature].astype(str) if feature in first else pd.Series(dtype=str)
            b = second[feature].astype(str) if feature in second else pd.Series(dtype=str)
            sa = (a == level).mean() * 100.0 if len(a) else None
            sb = (b == level).mean() * 100.0 if len(b) else None
            rows.append({"panel": panel, "comparison": comparison, "tier": t, "feature": f"{feature}={level}",
                         "phase": "PRE_OR_AT_ANCHOR" if feature in {"market", "entry_pattern_a_stage", "stage_before_anchor"} else "POST_ANCHOR",
                         "first_n": int(len(a)), "second_n": int(len(b)),
                         "first_share_pct": wl._round(sa), "second_share_pct": wl._round(sb),
                         "effect": wl._round(sa - sb) if sa is not None and sb is not None else None})
    return rows


def group_summary(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["terminal_return"].astype(float)
    row: dict[str, Any] = {"n": int(len(frame))}
    if not len(frame):
        return row
    row.update({"mean_return": wl._round(returns.mean()), "median_return": wl._round(returns.median()),
                "ge_50_count": int((returns >= 50).sum()), "ge_100_count": int((returns >= 100).sum()),
                **{f"le_neg_{t}_count": int((returns <= -t).sum()) for t in (30, 40, 50, 60)},
                "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()),
                "departed_progressed_pct": wl._round(frame["departed_progressed"].mean() * 100.0),
                "exit_type_mix": "; ".join(f"{k}={v}" for k, v in frame["exit_type"].value_counts().items())})
    return row


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def build_trade_table(repo: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stages = lc.load_stage_cache()
    panels_all, count_gates = lc.build_panels(stages)
    gate_table, panels = lc.replication_gate(panels_all)
    ancillary_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    daily_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    rows, parity_rows = [], []
    for panel, frame in panels.items():
        cutoff_of = (lambda r: pd.Timestamp(r["window_cutoff"])) if panel == "SIMPLE_POOLED_DEDUP" else None
        if panel == "SIMPLE_POOLED_DEDUP":
            cutoff_value = None
        elif panel.startswith("SIMPLE_"):
            cutoff_value = pd.Timestamp(lc.SIMPLE_CUTOFF[panel.split("_", 1)[1]])
        else:
            cutoff_value = pd.Timestamp(lc.REALISTIC_RUNS[panel.split("_")[1]]["cutoff"])
        selected = frame[frame["holding_subgroup"].isin([GROUP_A, GROUP_C1])]
        mismatch = 0
        for index, row in selected.iterrows():
            cutoff = cutoff_of(row) if cutoff_of else cutoff_value
            key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
            if key not in daily_cache:
                daily_cache[key] = repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
                ancillary_cache[key] = repo.get_daily_ancillary(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
            daily = daily_cache[key]
            parity = price_parity(daily, row, cutoff)
            if not parity["price_parity"]:
                mismatch += 1
                continue
            cache = stages[key]
            end = lc.holding_end(row, cutoff)
            held = held_labels(cache, pd.Timestamp(row["entry_signal_date"]), cutoff, end)
            if lc.holding_lifecycle_class(str(row["entry_pattern_a_stage"]).upper(), list(zip(held["label"], held["stage"]))) != row["holding_subgroup"]:
                raise RuntimeError(f"HOLDING_CLASS_REBUILD_MISMATCH:{panel}:{row['trade_id']}")
            if len(held) and held["effective"].max() > end:
                raise RuntimeError("STAGE_AFTER_HOLDING_END_USED")
            events = stage_events(str(row["entry_pattern_a_stage"]).upper(), held)
            record = {"panel": panel, "row_index": index, "group": "A" if row["holding_subgroup"] == GROUP_A else "C1", **events}
            record.update(path_metrics(daily, row, cutoff, events, held))
            pre = cache[cache["label"] < pd.Timestamp(row["entry_signal_date"])]
            pre_scores = pre.loc[pre["stage"] != "UNAVAILABLE", "score"].dropna()
            record["pre_entry_month_pattern_a_score"] = float(pre_scores.iloc[-1]) if len(pre_scores) else None
            record["anchor_score_change"] = (round(float(events["anchor_score"]) - record["pre_entry_month_pattern_a_score"], 2)
                                             if record["pre_entry_month_pattern_a_score"] is not None and events["anchor_score"] is not None else None)
            anc = ancillary_cache[key]
            anchor_day = pd.Timestamp(events["anchor_effective"])
            record["anchor_market_cap_eok"] = (round(float(anc.loc[anchor_day, "market_cap"]) / 1e8, 2)
                                               if anchor_day in anc.index and pd.notna(anc.loc[anchor_day, "market_cap"]) else None)
            record["departed_progressed"] = bool(isinstance(events.get("first_departure_stage"), str))
            first_prog_ledger = row.get("first_progressed_date")
            record["anchor_equals_ledger_first_progressed"] = bool(isinstance(first_prog_ledger, str)
                                                                    and pd.Timestamp(first_prog_ledger) == pd.Timestamp(events["anchor_label"]))
            record["entry_before_anchor"] = bool(pd.Timestamp(row["entry_execution_date"]) <= anchor_day)
            rows.append(record)
        parity_rows.append({"panel": panel, "a_c1_trades": int(len(selected)), "price_parity_mismatch": mismatch,
                            "mismatch_pct": wl._round(mismatch / len(selected) * 100.0) if len(selected) else None})
    detail = pd.DataFrame(rows)
    base_columns = ["ticker", "isu_cd", "name", "market", "trade_id", "pair_id", "entry_signal_date", "entry_execution_date",
                    "entry_pattern_a_stage", "fast_score", "exit_type", "exit_signal_date", "exit_execution_date", "trade_status",
                    "terminal_return", "mfe", "mae", "holding_days", "holding_subgroup", "lifecycle_class", "filled"]
    base = []
    for panel, frame in panels.items():
        part = frame.reindex(columns=base_columns).copy()
        part["panel"] = panel
        part["row_index"] = frame.index
        base.append(part)
    merged = detail.merge(pd.concat(base), on=["panel", "row_index"], how="left", validate="one_to_one")
    parity = pd.DataFrame(parity_rows)
    audit = {"count_gates": count_gates, "replication_gate": gate_table.drop(columns=["mismatch_examples"]).to_dict("records")}
    return merged, parity, audit


def run() -> None:
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    repo = build_production_repository_v2(ROOT, end=lc.REPOSITORY_END)
    trades, parity, audit = build_trade_table(repo)
    excluded = parity[parity["mismatch_pct"] > PANEL_EXCLUSION_MISMATCH_PCT]["panel"].tolist()
    trades = trades[~trades["panel"].isin(excluded)].copy()
    if trades.duplicated(["panel", "ticker", "isu_cd", "entry_signal_date", "entry_execution_date"]).any():
        raise RuntimeError("TRADE_IDENTITY_DUPLICATE")
    if not trades["entry_before_anchor"].all():
        raise RuntimeError("ANCHOR_BEFORE_ENTRY")
    trades["event_sequence"] = trades.apply(event_sequence, axis=1)
    trades = trades.sort_values(["panel", "group", "ticker", "entry_signal_date"]).reset_index(drop=True)
    trades.drop(columns=["row_index"]).to_csv(OUTPUT_DIR / "a_vs_c1_trade_level.csv", index=False)
    anchor_cols = ["panel", "group", "ticker", "trade_id", "entry_signal_date", "entry_execution_date", "anchor_label", "anchor_effective",
                   "stage_before_anchor", "entry_to_anchor_trading_days", "return_at_anchor", "pre_anchor_mfe", "pre_anchor_mae",
                   "pre_anchor_max_close_drawdown", "pre_anchor_label_count", "pre_anchor_stage_transitions", "pre_entry_month_pattern_a_score",
                   "anchor_score", "anchor_score_change", "fast_score", "market", "anchor_market_cap_eok", "anchor_equals_ledger_first_progressed"]
    trades[anchor_cols].to_csv(OUTPUT_DIR / "first_progressed_anchor_metrics.csv", index=False)

    comparison_rows, summary_rows, winner_loser_rows = [], [], []
    for panel, frame in trades.groupby("panel", sort=False):
        a, c1 = frame[frame["group"] == "A"], frame[frame["group"] == "C1"]
        comparison_rows += compare(a, c1, panel, "A_vs_C1")
        for name, subset in (("A", a), ("C1", c1)):
            summary_rows.append({"panel": panel, "group": name, **group_summary(subset)})
        c1r = c1["terminal_return"].astype(float)
        for label, win, lose in (("C1_WIN50_vs_C1_LOSS30", c1r >= 50, c1r <= -30), ("C1_WIN100_vs_C1_LOSS50", c1r >= 100, c1r <= -50)):
            winner_loser_rows += compare(c1[win], c1[lose], panel, label)
    pd.DataFrame(comparison_rows).to_csv(OUTPUT_DIR / "a_vs_c1_comparison.csv", index=False)
    pd.DataFrame(winner_loser_rows).to_csv(OUTPUT_DIR / "c1_winner_vs_loser_comparison.csv", index=False)
    summary_table = pd.DataFrame(summary_rows)
    summary_table.to_csv(OUTPUT_DIR / "window_level_summary.csv", index=False)

    extreme_cols = ["panel", "ticker", "name", "trade_id", "market", "terminal_return", "trade_status", "exit_type", "event_sequence",
                    "stage_before_anchor", "return_at_anchor", "post_anchor_path", "first_departure_stage", "return_at_first_departure",
                    "anchor_to_departure_trading_days", "departure_to_end_trading_days", "returned_to_progressed_after_departure",
                    "post_anchor_score_drawdown_max"] + [f"touch_{t}_{s}" for t in THRESHOLDS for s in ("date", "days_from_anchor", "stage", "prev_stage", "after_departure", "later_max_return", "recovered_to_breakeven")]
    c1_all = trades[trades["group"] == "C1"]
    extreme = c1_all[c1_all["terminal_return"].astype(float) <= -30].reindex(columns=extreme_cols)
    extreme.to_csv(OUTPUT_DIR / "c1_extreme_loss_event_sequences.csv", index=False)

    # 전체 deep loss 중 C1 비중(보유 기준): lifecycle 패널 전체 거래 기준
    concentration = {}
    stages = lc.load_stage_cache()
    panels_all, _ = lc.build_panels(stages)
    _, panels = lc.replication_gate(panels_all)
    for panel, frame in panels.items():
        r = frame["terminal_return"].astype(float)
        concentration[panel] = {f"le_neg_{t}": {"total": int((r <= -t).sum()), "c1": int(((r <= -t) & (frame["holding_subgroup"] == GROUP_C1)).sum()),
                                                "a": int(((r <= -t) & (frame["holding_subgroup"] == GROUP_A)).sum())} for t in (30, 40, 50, 60)}

    threshold_rows = []
    for panel, frame in trades.groupby("panel", sort=False):
        for group, subset in frame.groupby("group"):
            for t in THRESHOLDS:
                touched = subset[subset[f"touch_{t}_date"].notna()]
                threshold_rows.append({
                    "panel": panel, "group": group, "threshold": -t, "n_group": int(len(subset)), "touched": int(len(touched)),
                    "touched_after_anchor": int(touched[f"touch_{t}_after_anchor"].sum()),
                    "touched_after_departure": int(touched[f"touch_{t}_after_departure"].sum()),
                    "median_days_from_anchor": wl._round(touched[f"touch_{t}_days_from_anchor"].median()) if len(touched) else None,
                    "stage_at_touch": "; ".join(f"{k}={v}" for k, v in touched[f"touch_{t}_stage"].value_counts().items()),
                    "prev_stage_at_touch": "; ".join(f"{k}={v}" for k, v in touched[f"touch_{t}_prev_stage"].value_counts().items()),
                    "recovered_to_breakeven": int(touched[f"touch_{t}_recovered_to_breakeven"].sum()),
                    "final_le_neg_30": int((touched["terminal_return"].astype(float) <= -30).sum()),
                    "open_at_cutoff": int((touched["trade_status"] == "OPEN_AT_CUTOFF").sum()),
                })
    pd.DataFrame(threshold_rows).to_csv(OUTPUT_DIR / "loss_threshold_touch_summary.csv", index=False)

    departure_rows = []
    for panel, frame in trades.groupby("panel", sort=False):
        for group, subset in frame.groupby("group"):
            for stage in ["NONE"] + RETREAT_STAGES:
                part = subset[subset["first_departure_stage"].fillna("NONE") == stage]
                r = part["terminal_return"].astype(float)
                departure_rows.append({
                    "panel": panel, "group": group, "first_departure_stage": stage, "n": int(len(part)),
                    "mean_return": wl._round(r.mean()) if len(part) else None, "median_return": wl._round(r.median()) if len(part) else None,
                    "median_return_at_departure": wl._round(part["return_at_first_departure"].median()) if len(part) else None,
                    "ge_50": int((r >= 50).sum()), "le_neg_30": int((r <= -30).sum()), "le_neg_50": int((r <= -50).sum()),
                    "open_at_cutoff": int((part["trade_status"] == "OPEN_AT_CUTOFF").sum()),
                    "returned_to_progressed": int(part["returned_to_progressed_after_departure"].sum()),
                    "exit_type_mix": "; ".join(f"{k}={v}" for k, v in part["exit_type"].value_counts().items()),
                })
    pd.DataFrame(departure_rows).to_csv(OUTPUT_DIR / "first_departure_outcomes.csv", index=False)

    audit_sample = trades.sample(n=min(12, len(trades)), random_state=20260927)[
        ["panel", "group", "ticker", "trade_id", "entry_signal_date", "exit_signal_date", "trade_status", "exit_type", "terminal_return",
         "anchor_label", "anchor_equals_ledger_first_progressed", "first_departure_stage", "first_departure_label", "post_anchor_path", "event_sequence"]]
    audit_sample.to_csv(OUTPUT_DIR / "manual_audit_sample.csv", index=False)

    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_A_VS_C1_DIVERGENCE_V01",
        "strategy_id": lc.STRATEGY_ID,
        "scope": "CONTROL only; archived certified ledgers; holding lifecycle only (stages and prices after the holding end are never used); no backtest, exit rule, threshold sweep, or network",
        "groups": {"A": GROUP_A, "C1": GROUP_C1, "definition_source": "classify_holding in scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py"},
        "anchor": "first PROGRESSED month label while held; observed at its effective (last trading) close",
        "price_contract": "Repository V2 adjusted daily; holding window as the runner's _refresh_outcome_metrics; thresholds use completed daily closes vs entry_open (same basis as the -15% Loss Guard)",
        "gates": {**audit, "price_parity": parity.to_dict("records"), "excluded_panels": excluded,
                  "price_parity_tolerance_pct_points": PRICE_PARITY_TOLERANCE, "panel_exclusion_mismatch_pct": PANEL_EXCLUSION_MISMATCH_PCT,
                  "anchor_equals_ledger_first_progressed_pct": {p: wl._round(f["anchor_equals_ledger_first_progressed"].mean() * 100.0) for p, f in trades.groupby("panel")},
                  "trade_identity_duplicates": 0, "stage_after_holding_end_used": 0},
        "tiers": TIERS,
        "deep_loss_concentration_holding_basis": concentration,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(parity.to_string(index=False))
    print("excluded:", excluded)


def main() -> None:
    audit = {"count": 0}
    with wl.network_guard(audit):
        run()
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
