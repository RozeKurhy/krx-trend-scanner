"""A FAST Core V2 — Exit4 effectiveness & PROGRESSED departure comparison V01.

인증 CONTROL 원장 8개(단순 5, 현실적 3)에서 Exit4(`EXIT4_SCORE_DRAWDOWN_GE_15`)로 청산된 거래를 모아
Exit4가 없었다면 첫 PROGRESSED 이탈까지 보유했을 때와 거래 단위로 비교한다.

Exit4 정의는 인증 러너가 호출하는 `trend_scanner.validation.pattern_a_fast_core_v02_reentry.simulate_ticker_core_v02_reentry`
그대로 옮긴 `replicate_exit_path`로 재현하고, 원장의 청산 유형·신호일·체결가와 맞는지 먼저 확인한다.

반사실 CF_NO_EXIT4_UNTIL_PROGRESSED_DEPARTURE는 Exit4 신호를 무시하고 그 이후 첫 PROGRESSED 이탈(유효 stage 기준)
라벨의 다음 거래일 시가에 청산한다. 이탈이 윈도우 cutoff까지 없으면 cutoff 종가로 평가한다. 이 반사실은 정의상
실제 청산 이후의 가격·stage를 쓰지만 윈도우 cutoff를 넘지 않는다. 포트폴리오 재배치는 계산하지 않는다.

사용법:
    python scripts/analyze_fastcore_v2_exit4_effectiveness_v01.py
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

OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/exit4_effectiveness_v01"
EXIT4 = "EXIT4_SCORE_DRAWDOWN_GE_15"
LOSS_GUARD = "LOSS_GUARD_CLOSE_LE_NEG_15"
DRAWDOWN_PT = 15.0
EXIT3_TARGETS = {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}
# 결과 확인 전에 고정한 분류 기준: CF(Exit4 없이 이탈까지) - CONTROL(Exit4) 수익률 차이(pp)
CLASS_THRESHOLD_PP = 10.0
TIERS = {"evaluable_min_n": 20, "descriptive_min_n": 10}
SUPPORT_BY_CUTOFF = {"2026-08-31": "2026-09-01", "2025-05-30": "2025-06-02"}


# ---------------------------------------------------------------------------
# 시뮬레이터 청산 규칙 재현 (순수 함수)
# ---------------------------------------------------------------------------

def replicate_exit_path(entry_stage: str, post: list[tuple[pd.Timestamp, str, float | None]]) -> dict[str, Any]:
    """reentry 시뮬레이터의 E2(Exit3 + Exit4 + coverage) 판정. post는 (라벨, stage, score)."""
    lifecycle, first_progressed = lc.replicate_ledger_lifecycle(entry_stage, [(m, s) for m, s, _ in post])
    handoff = None
    prev = entry_stage
    for m, s, _ in post:
        if s in lc.VALID_SKIP:
            continue
        if s == "PROGRESSED" and prev == "EARLY_TREND":
            handoff = m
            break
        prev = s
    result = {"lifecycle": lifecycle, "first_progressed": first_progressed, "handoff": handoff,
              "exit_type": None, "signal_label": None, "hwm_at_signal": None, "score_at_signal": None}
    if lifecycle == "NORMAL_EARLY_TREND_HANDOFF":
        in_p, hwm = False, None
        for m, s, sc in post:
            if m < handoff:
                continue
            if m == handoff:
                in_p, hwm = True, (sc if sc is not None else 0.0)
                continue
            if not in_p:
                continue
            if s == "PROGRESSED":
                if sc is not None and hwm is not None:
                    hwm = max(hwm, sc)
                    if hwm - sc >= DRAWDOWN_PT:
                        result.update(exit_type=EXIT4, signal_label=m, hwm_at_signal=hwm, score_at_signal=sc)
                        return result
            elif s in EXIT3_TARGETS:
                result.update(exit_type=f"EXIT3_PROGRESSED_TO_{s}", signal_label=m, score_at_signal=sc, hwm_at_signal=hwm)
                return result
        result["exit_type"] = "NO_EXIT_BEFORE_CUTOFF"
        return result
    if lifecycle in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
        hwm = None
        for m, s, sc in post:
            if m < first_progressed:
                continue
            if m == first_progressed:
                hwm = sc if sc is not None else 0.0
                continue
            if s == "PROGRESSED":
                if sc is not None:
                    hwm = max(hwm, sc)
                    if hwm - sc >= DRAWDOWN_PT:
                        result.update(exit_type=EXIT4, signal_label=m, hwm_at_signal=hwm, score_at_signal=sc)
                        return result
            else:
                break
        result["exit_type"] = "NO_EXIT_BEFORE_CUTOFF"
        return result
    result["exit_type"] = "NO_PROGRESSED_BEFORE_CUTOFF"
    return result


def first_departure_after(post: list[tuple[pd.Timestamp, str, float | None]], after: pd.Timestamp) -> tuple[pd.Timestamp | None, str | None]:
    """after 라벨 이후 첫 유효(UNAVAILABLE 제외) non-PROGRESSED 라벨."""
    for m, s, _ in post:
        if m <= after or s in lc.VALID_SKIP:
            continue
        if s != "PROGRESSED":
            return m, s
    return None, None


def next_session_open(daily: pd.DataFrame, label: pd.Timestamp, support: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    """시뮬레이터 `_calc_trade_outcome`: 신호 라벨보다 뒤의 첫 거래일(실행 지원일까지) 시가."""
    later = daily[(daily.index > label) & (daily.index <= support)]
    if later.empty:
        return None, None
    return pd.Timestamp(later.index[0]), float(later.iloc[0]["open"])


def classify(diff_pp: float | None) -> str:
    if diff_pp is None or (isinstance(diff_pp, float) and math.isnan(diff_pp)):
        return "INSUFFICIENT_EVIDENCE"
    if diff_pp <= -CLASS_THRESHOLD_PP:
        return "EXIT4_CLEARLY_HELPFUL"
    if diff_pp >= CLASS_THRESHOLD_PP:
        return "EXIT4_POTENTIALLY_HARMFUL"
    return "EXIT4_ROUGHLY_REDUNDANT"


def tier(n: int) -> str:
    return "EVALUABLE" if n >= TIERS["evaluable_min_n"] else ("DESCRIPTIVE" if n >= TIERS["descriptive_min_n"] else "INSUFFICIENT_EVIDENCE")


def pct(price: float, entry_open: float) -> float:
    return round((float(price) - float(entry_open)) / float(entry_open) * 100.0, 2)


def return_stats(values: pd.Series, prefix: str = "") -> dict[str, Any]:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if v.empty:
        return {f"{prefix}n": 0}
    return {f"{prefix}n": int(len(v)), f"{prefix}mean": wl._round(v.mean()), f"{prefix}median": wl._round(v.median()),
            f"{prefix}ge_50": int((v >= 50).sum()), f"{prefix}ge_100": int((v >= 100).sum()),
            **{f"{prefix}le_neg_{t}": int((v <= -t).sum()) for t in (15, 30, 40, 50, 60)}}


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def cutoff_of(panel: str, row: pd.Series) -> pd.Timestamp:
    if panel == "SIMPLE_POOLED_DEDUP":
        return pd.Timestamp(row["window_cutoff"])
    if panel.startswith("SIMPLE_"):
        return pd.Timestamp(lc.SIMPLE_CUTOFF[panel.split("_", 1)[1]])
    return pd.Timestamp(lc.REALISTIC_RUNS[panel.split("_")[1]]["cutoff"])


def build(repo: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stages = lc.load_stage_cache()
    panels_all, count_gates = lc.build_panels(stages)
    gate_table, panels = lc.replication_gate(panels_all)
    enrichment = pd.read_csv(wl.ENRICHMENT_PATH, dtype={"ticker": str, "isu_cd": str})
    enrichment["ticker"] = enrichment["ticker"].str.zfill(6)
    mcap = enrichment.set_index(["ticker", "isu_cd", "entry_signal_date"])["market_cap_eok"].to_dict()
    daily_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    parity_rows, trade_rows = [], []
    for panel, frame in panels.items():
        counts = {"panel": panel, "rows": 0, "e2_rows_checked": 0, "e2_type_match": 0, "e2_signal_match": 0,
                  "exit4_ledger": 0, "exit4_replicated_match": 0, "exit4_price_match": 0}
        for _, row in frame.iterrows():
            counts["rows"] += 1
            cutoff = cutoff_of(panel, row)
            key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
            cache = stages[key]
            signal = pd.Timestamp(row["entry_signal_date"])
            post_frame = cache[(cache["label"] >= signal) & (cache["label"] <= cutoff)]
            post = [(m, s, (None if pd.isna(sc) else float(sc))) for m, s, sc in zip(post_frame["label"], post_frame["stage"], post_frame["score"])]
            replicated = replicate_exit_path(str(row["entry_pattern_a_stage"]).upper(), post)
            ledger_type = str(row["exit_type"])
            if ledger_type != LOSS_GUARD and row["trade_status"] != "LIFECYCLE_SETTLED":
                counts["e2_rows_checked"] += 1
                type_ok = replicated["exit_type"] == ledger_type
                counts["e2_type_match"] += int(type_ok)
                ledger_signal = row.get("exit_signal_date")
                signal_ok = (replicated["signal_label"] is None and not isinstance(ledger_signal, str)) or (
                    replicated["signal_label"] is not None and isinstance(ledger_signal, str)
                    and pd.Timestamp(ledger_signal) == replicated["signal_label"])
                counts["e2_signal_match"] += int(type_ok and signal_ok)
            if ledger_type != EXIT4:
                continue
            counts["exit4_ledger"] += 1
            if not (replicated["exit_type"] == EXIT4 and pd.Timestamp(row["exit_signal_date"]) == replicated["signal_label"]):
                continue
            counts["exit4_replicated_match"] += 1
            if key not in daily_cache:
                daily_cache[key] = repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
            daily = daily_cache[key]
            support = pd.Timestamp(SUPPORT_BY_CUTOFF[cutoff.strftime("%Y-%m-%d")])
            exec_date, exec_open = next_session_open(daily, replicated["signal_label"], support)
            price_ok = (exec_date is not None and exec_date == pd.Timestamp(row["exit_execution_date"])
                        and abs(exec_open - float(row["exit_price"])) <= 0.011)
            counts["exit4_price_match"] += int(price_ok)
            if not price_ok:
                continue
            entry_open = float(row["entry_open"])
            departure_label, departure_stage = first_departure_after(post, replicated["signal_label"])
            if departure_label is not None:
                cf_date, cf_open = next_session_open(daily, departure_label, support)
            else:
                cf_date, cf_open = None, None
            window_close = daily[daily.index <= cutoff]
            if cf_date is None:
                cf_price, cf_exit_kind, cf_end = float(window_close.iloc[-1]["close"]), "MARK_AT_WINDOW_CUTOFF", pd.Timestamp(window_close.index[-1])
            else:
                cf_price, cf_exit_kind, cf_end = cf_open, "EXIT_AT_PROGRESSED_DEPARTURE", cf_date
            # Exit4 체결일 ~ 반사실 청산 직전(청산일은 시가만)
            between = daily[(daily.index >= exec_date) & (daily.index < cf_end)] if cf_exit_kind.startswith("EXIT") else daily[(daily.index >= exec_date) & (daily.index <= cf_end)]
            highs = between["high"].tolist() + ([cf_price] if cf_exit_kind.startswith("EXIT") else [])
            lows = between["low"].tolist() + ([cf_price] if cf_exit_kind.startswith("EXIT") else [])
            closes = between["close"]
            peak_day = closes.idxmax() if len(closes) else None
            post_labels = [(m, s) for m, s, _ in post if replicated["signal_label"] < m <= (departure_label or cutoff)]
            control = float(row["terminal_return"])
            cf_return = pct(cf_price, entry_open)
            trade_rows.append({
                "panel": panel, "ticker": row["ticker"], "name": row.get("name"), "market": row["market"], "trade_id": row["trade_id"],
                "entry_signal_date": row["entry_signal_date"], "entry_execution_date": row["entry_execution_date"],
                "entry_pattern_a_stage": row["entry_pattern_a_stage"], "window_lifecycle_class": row["lifecycle_class"],
                "holding_subgroup": row["holding_subgroup"], "exit4_path": "NORMAL" if replicated["lifecycle"] == "NORMAL_EARLY_TREND_HANDOFF" else "COVERAGE",
                "exit4_signal_label": replicated["signal_label"].strftime("%Y-%m-%d"), "exit4_execution_date": exec_date.strftime("%Y-%m-%d"),
                "exit4_return": control, "mfe": float(row["mfe"]), "mae": float(row["mae"]), "giveback": round(float(row["mfe"]) - control, 2),
                "holding_days": row["holding_days"], "score_at_exit4": replicated["score_at_signal"], "hwm_at_exit4": replicated["hwm_at_signal"],
                "score_drawdown_at_exit4": round(replicated["hwm_at_signal"] - replicated["score_at_signal"], 2),
                "entry_market_cap_eok": mcap.get((row["ticker"], row["isu_cd"], row["entry_signal_date"]))
                if not pd.notna(row.get("entry_market_cap")) else round(float(row["entry_market_cap"]) / 1e8, 2),
                "post_exit4_departure_label": departure_label.strftime("%Y-%m-%d") if departure_label is not None else None,
                "post_exit4_departure_stage": departure_stage,
                "departure_group": "A_DEPARTED_AFTER_EXIT4" if departure_label is not None else "B_NO_DEPARTURE_BEFORE_CUTOFF",
                "cf_exit_kind": cf_exit_kind, "cf_exit_date": cf_end.strftime("%Y-%m-%d"), "cf_return": cf_return,
                "cf_minus_control_pp": round(cf_return - control, 2), "classification": classify(round(cf_return - control, 2)),
                "exit4_to_cf_trading_days": int(((daily.index >= exec_date) & (daily.index < cf_end)).sum()),
                "post_exit4_max_return": pct(max(highs), entry_open) if highs else None,
                "post_exit4_min_return": pct(min(lows), entry_open) if lows else None,
                "post_exit4_max_close_return": pct(closes.max(), entry_open) if len(closes) else None,
                "exit4_to_peak_trading_days": int(((daily.index >= exec_date) & (daily.index <= peak_day)).sum()) if peak_day is not None else None,
                "post_exit4_path": lc.compress_path([(None, s) for _, s in post_labels]),
                **{f"post_exit4_ever_{s.lower()}": any(st == s for _, st in post_labels) for s in ("WEAK", "BASE", "TRANSITION", "EARLY_TREND")},
                "filled": row.get("filled"),
            })
        parity_rows.append(counts)
    parity = pd.DataFrame(parity_rows)
    for c in ("e2_type_match", "e2_signal_match"):
        parity[f"{c}_pct"] = (parity[c] / parity["e2_rows_checked"] * 100.0).round(3)
    parity["exit4_price_match_pct"] = (parity["exit4_price_match"] / parity["exit4_ledger"] * 100.0).round(3)
    return pd.DataFrame(trade_rows), parity, {"count_gates": count_gates, "replication_gate": gate_table.drop(columns=["mismatch_examples"]).to_dict("records")}


def summarize(trades: pd.DataFrame, panels_n: dict[str, int]) -> dict[str, pd.DataFrame]:
    profile_rows, cf_rows, class_rows, damage_rows, protect_rows = [], [], [], [], []
    for panel, part in trades.groupby("panel", sort=False):
        for label, sub in [("ALL", part), ("NORMAL_PATH", part[part["exit4_path"] == "NORMAL"]), ("COVERAGE_PATH", part[part["exit4_path"] == "COVERAGE"])]:
            if sub.empty:
                continue
            profile_rows.append({
                "panel": panel, "subset": label, "tier": tier(len(sub)), **return_stats(sub["exit4_return"]),
                "mfe_median": wl._round(sub["mfe"].median()), "mae_median": wl._round(sub["mae"].median()),
                "giveback_median": wl._round(sub["giveback"].median()), "holding_days_median": wl._round(sub["holding_days"].median()),
                "score_at_exit4_median": wl._round(sub["score_at_exit4"].median()), "hwm_at_exit4_median": wl._round(sub["hwm_at_exit4"].median()),
                "score_drawdown_median": wl._round(sub["score_drawdown_at_exit4"].median()),
                "kosdaq_pct": wl._round((sub["market"] == "KOSDAQ").mean() * 100.0),
                "entry_market_cap_eok_median": wl._round(pd.to_numeric(sub["entry_market_cap_eok"], errors="coerce").median()),
                "holding_group_mix": "; ".join(f"{k}={v}" for k, v in sub["holding_subgroup"].value_counts().items()),
            })
        for group, sub in [("ALL", part), ("A_DEPARTED_AFTER_EXIT4", part[part["departure_group"] == "A_DEPARTED_AFTER_EXIT4"]),
                           ("B_NO_DEPARTURE_BEFORE_CUTOFF", part[part["departure_group"] == "B_NO_DEPARTURE_BEFORE_CUTOFF"])]:
            if sub.empty:
                continue
            diff = sub["cf_minus_control_pp"]
            ordered = sub.sort_values("cf_minus_control_pp", ascending=False)
            for scenario, col in (("CONTROL_EXIT4", "exit4_return"), ("CF_NO_EXIT4_UNTIL_PROGRESSED_DEPARTURE", "cf_return")):
                cf_rows.append({
                    "panel": panel, "group": group, "scenario": scenario, "tier": tier(len(sub)), **return_stats(sub[col]),
                    "mean_diff_cf_minus_control_pp": wl._round(diff.mean()), "median_diff_pp": wl._round(diff.median()),
                    "mean_diff_excl_top1_pp": wl._round(ordered["cf_minus_control_pp"].iloc[1:].mean()) if len(sub) > 1 else None,
                    "mean_diff_excl_top5_pp": wl._round(ordered["cf_minus_control_pp"].iloc[5:].mean()) if len(sub) > 5 else None,
                    "cf_better_n": int((diff > 0).sum()), "cf_worse_n": int((diff < 0).sum()),
                    "exit4_to_cf_trading_days_median": wl._round(sub["exit4_to_cf_trading_days"].median()),
                    "post_exit4_max_return_median": wl._round(sub["post_exit4_max_return"].median()),
                    "post_exit4_min_return_median": wl._round(sub["post_exit4_min_return"].median()),
                    "cf_marked_at_cutoff_n": int((sub["cf_exit_kind"] == "MARK_AT_WINDOW_CUTOFF").sum()),
                    "panel_all_trades_n": panels_n.get(panel),
                    "panel_mean_shift_pp": wl._round(diff.sum() / panels_n[panel]) if panels_n.get(panel) else None,
                })
        for group, sub in [("ALL", part), ("A_DEPARTED_AFTER_EXIT4", part[part["departure_group"] == "A_DEPARTED_AFTER_EXIT4"]),
                           ("B_NO_DEPARTURE_BEFORE_CUTOFF", part[part["departure_group"] == "B_NO_DEPARTURE_BEFORE_CUTOFF"])]:
            counts = sub["classification"].value_counts()
            class_rows.append({"panel": panel, "group": group, "n": int(len(sub)), "tier": tier(len(sub)),
                               **{c: int(counts.get(c, 0)) for c in ("EXIT4_CLEARLY_HELPFUL", "EXIT4_ROUGHLY_REDUNDANT", "EXIT4_POTENTIALLY_HARMFUL", "INSUFFICIENT_EVIDENCE")},
                               "helpful_sum_pp": wl._round(sub.loc[sub["classification"] == "EXIT4_CLEARLY_HELPFUL", "cf_minus_control_pp"].sum()),
                               "harmful_sum_pp": wl._round(sub.loc[sub["classification"] == "EXIT4_POTENTIALLY_HARMFUL", "cf_minus_control_pp"].sum())})
        c, cf = part["exit4_return"], part["cf_return"]
        damage_rows.append({
            "panel": panel, "n": int(len(part)),
            "cf_ge50_where_exit4_lt50": int(((cf >= 50) & (c < 50)).sum()), "cf_ge100_where_exit4_lt100": int(((cf >= 100) & (c < 100)).sum()),
            "exit4_ge50_but_cf_lt50": int(((c >= 50) & (cf < 50)).sum()),
            "post_exit4_max_ge50_where_exit4_lt50": int(((part["post_exit4_max_return"] >= 50) & (c < 50)).sum()),
            "post_exit4_max_ge100_where_exit4_lt100": int(((part["post_exit4_max_return"] >= 100) & (c < 100)).sum()),
            "post_exit4_max_exceeds_prior_mfe": int((part["post_exit4_max_return"] > part["mfe"]).sum()),
            "missed_upside_to_post_max_median_pp": wl._round((part["post_exit4_max_return"] - c).median()),
            "exit4_to_peak_days_median": wl._round(part["exit4_to_peak_trading_days"].median()),
            "stayed_progressed_to_cutoff_n": int((part["departure_group"] == "B_NO_DEPARTURE_BEFORE_CUTOFF").sum()),
        })
        protect_rows.append({
            "panel": panel, "n": int(len(part)),
            **{f"cf_le_neg{t}_where_exit4_gt_neg{t}": int(((cf <= -t) & (c > -t)).sum()) for t in (15, 30, 50)},
            **{f"post_exit4_min_le_neg{t}": int((part["post_exit4_min_return"] <= -t).sum()) for t in (15, 30, 50)},
            "cf_worse_by_ge_20pp": int((part["cf_minus_control_pp"] <= -20).sum()),
            "post_exit4_giveback_to_cf_median_pp": wl._round((part["post_exit4_max_return"] - cf).median()),
            **{f"post_exit4_ever_{s}": int(part[f"post_exit4_ever_{s}"].sum()) for s in ("weak", "base", "transition", "early_trend")},
            "departure_stage_mix": "; ".join(f"{k}={v}" for k, v in part["post_exit4_departure_stage"].fillna("NONE").value_counts().items()),
        })
    return {"profile": pd.DataFrame(profile_rows), "cf": pd.DataFrame(cf_rows), "classes": pd.DataFrame(class_rows),
            "damage": pd.DataFrame(damage_rows), "protection": pd.DataFrame(protect_rows)}


def run() -> None:
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    repo = build_production_repository_v2(ROOT, end=lc.REPOSITORY_END)
    trades, parity, gates = build(repo)
    for column in ("e2_type_match_pct", "e2_signal_match_pct", "exit4_price_match_pct"):
        low = parity[parity[column] < 99.0]
        if len(low):
            print(parity.to_string(index=False))
            raise RuntimeError(f"EXIT_PARITY_GATE_FAILED:{column}")
    if trades.duplicated(["panel", "ticker", "trade_id", "entry_signal_date"]).any():
        raise RuntimeError("TRADE_IDENTITY_DUPLICATE")
    trades = trades.sort_values(["panel", "ticker", "entry_signal_date"]).reset_index(drop=True)
    trades.to_csv(OUTPUT_DIR / "exit4_trade_profile.csv", index=False)
    comparison_cols = ["panel", "ticker", "trade_id", "exit4_path", "departure_group", "exit4_signal_label", "exit4_return",
                       "post_exit4_departure_label", "post_exit4_departure_stage", "cf_exit_kind", "cf_exit_date", "cf_return",
                       "cf_minus_control_pp", "classification", "exit4_to_cf_trading_days", "post_exit4_max_return",
                       "post_exit4_min_return", "exit4_to_peak_trading_days", "post_exit4_path"]
    trades[comparison_cols].to_csv(OUTPUT_DIR / "exit4_vs_progressed_departure_comparison.csv", index=False)
    stages = lc.load_stage_cache()
    panels_all, _ = lc.build_panels(stages)
    _, panels = lc.replication_gate(panels_all)
    tables = summarize(trades, {p: len(f) for p, f in panels.items()})
    tables["profile"].to_csv(OUTPUT_DIR / "exit4_profile_summary.csv", index=False)
    tables["cf"].to_csv(OUTPUT_DIR / "no_exit4_counterfactual.csv", index=False)
    tables["classes"].to_csv(OUTPUT_DIR / "exit4_role_classification.csv", index=False)
    tables["damage"].to_csv(OUTPUT_DIR / "exit4_winner_damage.csv", index=False)
    tables["protection"].to_csv(OUTPUT_DIR / "exit4_loss_protection.csv", index=False)
    parity.to_csv(OUTPUT_DIR / "exit_rule_parity.csv", index=False)
    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_EXIT4_EFFECTIVENESS_V01",
        "strategy_id": lc.STRATEGY_ID,
        "scope": "CONTROL only; archived certified ledgers; trade-level counterfactual only; no backtest, strategy or exit-rule change, threshold sweep, or network",
        "exit4_definition_source": "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py simulate_ticker_core_v02_reentry (called by the certified runners)",
        "exit4_definition": {
            "normal_path": "active from the first direct EARLY_TREND->PROGRESSED handoff label; HWM initialised to the handoff label score; on each later PROGRESSED label HWM = max(HWM, score) and EXIT4 when HWM - score >= 15.0; a later WEAK/BASE/TRANSITION/EARLY_TREND label is EXIT3; UNAVAILABLE labels are ignored",
            "coverage_path": "SKIPPED / WITHOUT_DIRECT: active from the first PROGRESSED label; HWM initialised to its score; EXIT4 on PROGRESSED labels only; any non-PROGRESSED label (including UNAVAILABLE) ends monitoring without an exit (OPEN_AT_CUTOFF)",
            "priority": "the -15% Loss Guard is only active before the first PROGRESSED effective date and takes precedence when triggered; within one monthly label EXIT3 and EXIT4 are mutually exclusive (EXIT4 needs a PROGRESSED label)",
            "execution": "next trading session open after the signal label (execution support day allowed)",
            "stage_at_exit4": "always PROGRESSED by construction",
        },
        "counterfactual": "CF_NO_EXIT4_UNTIL_PROGRESSED_DEPARTURE: ignore EXIT4, exit at the next session open after the first valid non-PROGRESSED label after the EXIT4 label; if none before the window cutoff, mark at the window-cutoff close. Loss Guard is already inactive after the first PROGRESSED, so no other forced exit applies. Uses prices and stages after the actual exit by construction, bounded by the window cutoff.",
        "classification_rule": {"threshold_pp": CLASS_THRESHOLD_PP, "EXIT4_CLEARLY_HELPFUL": "CF - CONTROL <= -10pp", "EXIT4_ROUGHLY_REDUNDANT": "|CF - CONTROL| < 10pp",
                                "EXIT4_POTENTIALLY_HARMFUL": "CF - CONTROL >= +10pp", "INSUFFICIENT_EVIDENCE": "counterfactual not computable"},
        "gates": {**gates, "exit_rule_parity": parity.to_dict("records")},
        "tiers": TIERS,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(parity.to_string(index=False))


def main() -> None:
    audit = {"count": 0}
    with wl.network_guard(audit):
        run()
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
