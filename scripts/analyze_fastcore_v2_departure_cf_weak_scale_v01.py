"""A FAST Core V2 — PROGRESSED 이탈 반사실 + 이탈 후 WEAK + EARLY_TREND PASS 수익 분해 V01.

입력은 Git에 보관된 인증 CONTROL 원장 8개, 보유 lifecycle 분석(`lifecycle_refinement_strict_handoff_v01`),
A vs C1 분석(`a_vs_c1_divergence_v01`)의 거래별 표, Repository V2 일봉(다음 거래일 시가 조회용)이다.

- 분석 A: C1 중 보유 중 첫 PROGRESSED 이탈이 있는 거래에 대해 거래 단위 반사실 3개를 계산한다.
  CONTROL(실제), CF_FULL_EXIT(이탈 관측일 다음 거래일 시가 전량 청산), CF_HALF_EXIT(절반 청산 + 나머지 실제).
  가격 규칙은 실제 Exit3 체결 규칙과 같다(A의 실제 Exit3 청산으로 검증). 포트폴리오 재배치는 계산하지 않는다.
- 분석 B: C1 이탈 거래를 이탈 후 WEAK 도달 여부와 PROGRESSED 복귀 여부로 나눠 비교한다.
- 분석 C: EARLY_TREND 진입 STRICT PASS 거래의 수익을 첫 PROGRESSED 이전/이후로 나눈다.
- 보조: EARLY_TREND 진입 거래의 진입 시점 Pattern A / FAST 점수를 PASS / FAIL / NO_NEXT로 비교한다.

새 백테스트, 전략 구현, threshold sweep, 네트워크 호출은 하지 않는다. 보유 종료 이후 stage는 쓰지 않는다.

사용법:
    python scripts/analyze_fastcore_v2_departure_cf_weak_scale_v01.py
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

OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/departure_cf_weak_scale_v01"
AVC1_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/a_vs_c1_divergence_v01"
KEY = ["panel", "ticker", "trade_id", "entry_signal_date"]
EXECUTION_SUPPORT = {"SIMPLE_P1": "2026-09-01", "SIMPLE_P2-1": "2025-06-02", "SIMPLE_P2-2": "2026-09-01", "SIMPLE_P3-1": "2025-06-02",
                     "SIMPLE_P3-2": "2026-09-01", "REALISTIC_P2-1": "2025-06-02", "REALISTIC_P2-2": "2026-09-01", "REALISTIC_P3-2": "2026-09-01"}
# 현실적 run 체결 계약(summary.json portfolio_contract). 반사실과 실제를 같은 비용 기준으로 비교할 때만 쓴다.
BUY_SLIPPAGE = SELL_SLIPPAGE = 0.001
COMMISSION = 0.00015
SELL_TAX = {2021: 0.0023, 2022: 0.0023, 2023: 0.002, 2024: 0.0018, 2025: 0.0015, 2026: 0.002}
TIERS = {"evaluable_min_n": 20, "descriptive_min_n": 10}


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------

def next_session_open(daily: pd.DataFrame, observed: pd.Timestamp, support: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    """관측일 다음 거래일(실행 지원일까지)의 시가. Exit3 체결 규칙과 같다."""
    later = daily[(daily.index > observed) & (daily.index <= support)]
    if later.empty:
        return None, None
    return pd.Timestamp(later.index[0]), float(later.iloc[0]["open"])


def pct(price: float, entry_open: float) -> float:
    return round((float(price) - float(entry_open)) / float(entry_open) * 100.0, 2)


def net_return(gross_pct: float, exit_year: int | None, closed: bool) -> float:
    """현실적 계약 비용 반영: 매수 슬리피지·수수료, 청산 시 매도 슬리피지·수수료·세금. 미청산은 종가 평가(매도 비용 없음)."""
    factor = (1.0 + gross_pct / 100.0) / ((1.0 + BUY_SLIPPAGE) * (1.0 + COMMISSION))
    if closed:
        factor *= (1.0 - SELL_SLIPPAGE) * (1.0 - COMMISSION - SELL_TAX.get(exit_year, 0.002))
    return round((factor - 1.0) * 100.0, 4)


def half_exit(control_pct: float, full_pct: float) -> float:
    return round(0.5 * control_pct + 0.5 * full_pct, 4)


def path_tokens(path: str) -> list[str]:
    tokens = []
    for part in str(path).split(">"):
        stage = part.split("(")[0]
        if stage:
            tokens.append(stage)
    return tokens


def weak_return_pattern(post_anchor_path: str) -> dict[str, bool]:
    """post-anchor 압축 경로(보유 구간만)에서 이탈 후 WEAK 도달과 PROGRESSED 복귀를 판정한다."""
    tokens = path_tokens(post_anchor_path)
    departure = next((i for i, s in enumerate(tokens) if s != "PROGRESSED"), None)
    if departure is None:
        return {"departed": False, "weak_after_departure": False, "returned_after_departure": False, "returned_after_weak": False}
    weak = next((i for i in range(departure, len(tokens)) if tokens[i] == "WEAK"), None)
    return {
        "departed": True,
        "weak_after_departure": weak is not None,
        "returned_after_departure": any(tokens[i] == "PROGRESSED" for i in range(departure, len(tokens))),
        "returned_after_weak": weak is not None and any(tokens[i] == "PROGRESSED" for i in range(weak, len(tokens))),
    }


def departure_group(pattern: dict[str, bool]) -> str | None:
    if not pattern["departed"]:
        return None
    if pattern["weak_after_departure"]:
        return "WEAK_THEN_RETURN" if pattern["returned_after_weak"] else "WEAK_NO_RETURN"
    return "NO_WEAK_RETURN" if pattern["returned_after_departure"] else "NO_WEAK_NO_RETURN"


def tier(n: int) -> str:
    return "EVALUABLE" if n >= TIERS["evaluable_min_n"] else ("DESCRIPTIVE" if n >= TIERS["descriptive_min_n"] else "INSUFFICIENT_EVIDENCE")


def return_stats(values: pd.Series, prefix: str = "") -> dict[str, Any]:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if v.empty:
        return {f"{prefix}n": 0}
    return {f"{prefix}n": int(len(v)), f"{prefix}mean": wl._round(v.mean()), f"{prefix}median": wl._round(v.median()),
            f"{prefix}q25": wl._round(v.quantile(0.25)), f"{prefix}q75": wl._round(v.quantile(0.75)),
            f"{prefix}ge_50": int((v >= 50).sum()), f"{prefix}ge_100": int((v >= 100).sum()),
            **{f"{prefix}le_neg_{t}": int((v <= -t).sum()) for t in (30, 40, 50, 60)}}


# ---------------------------------------------------------------------------
# 입력 구성
# ---------------------------------------------------------------------------

def load_inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    stages = lc.load_stage_cache()
    panels_all, count_gates = lc.build_panels(stages)
    gate_table, panels = lc.replication_gate(panels_all)
    avc1 = pd.read_csv(AVC1_DIR / "a_vs_c1_trade_level.csv", dtype={"ticker": str, "isu_cd": str}, low_memory=False)
    avc1["ticker"] = avc1["ticker"].str.zfill(6)
    if avc1.duplicated(KEY).any():
        raise RuntimeError("AVC1_KEY_DUPLICATE")
    ledger_cols = ["ticker", "trade_id", "entry_signal_date", "isu_cd", "identity_effective_from", "entry_open", "exit_price",
                   "exit_execution_date", "exit_signal_date", "strict_class", "entry_origin", "held_path"]
    parts = []
    for panel, frame in panels.items():
        part = frame.reindex(columns=ledger_cols).copy()
        part["panel"] = panel
        parts.append(part)
    ledger = pd.concat(parts, ignore_index=True)
    ledger["ticker"] = ledger["ticker"].astype(str).str.zfill(6)
    trades = avc1.merge(ledger, on=KEY, how="left", validate="one_to_one", suffixes=("", "_ledger"))
    if trades["entry_open"].isna().any():
        raise RuntimeError("AVC1_ROW_WITHOUT_LEDGER_MATCH")
    return trades, panels, {"count_gates": count_gates, "replication_gate": gate_table.drop(columns=["mismatch_examples"]).to_dict("records")}


def window_of(panel: str) -> str:
    return panel if panel.startswith("SIMPLE_P") and panel != "SIMPLE_POOLED_DEDUP" else ("_".join(panel.split("_")[:2]) if panel.startswith("REALISTIC") else panel)


# ---------------------------------------------------------------------------
# 분석
# ---------------------------------------------------------------------------

def counterfactuals(trades: pd.DataFrame, repo: Any, support_for: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily_cache: dict[tuple[str, str, str], pd.DataFrame] = {}

    def daily_for(row: pd.Series) -> pd.DataFrame:
        key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
        if key not in daily_cache:
            daily_cache[key] = repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
        return daily_cache[key]

    # 가격 규칙 검증: A의 실제 Exit3 청산 = 이탈 관측일 다음 거래일 시가
    a_exit3 = trades[(trades["group"] == "A") & trades["exit_type"].astype(str).str.startswith("EXIT3")]
    rule_checks = []
    for _, row in a_exit3.iterrows():
        date, price = next_session_open(daily_for(row), pd.Timestamp(row["first_departure_effective"]), support_for(row))
        rule_checks.append(bool(date is not None and date == pd.Timestamp(row["exit_execution_date"])
                                and abs(price - float(row["exit_price"])) <= 0.011))
    rule_gate = {"a_exit3_trades": len(rule_checks), "rule_match": int(sum(rule_checks)),
                 "match_pct": wl._round(sum(rule_checks) / len(rule_checks) * 100.0) if rule_checks else None}
    if rule_checks and rule_gate["match_pct"] < 99.0:
        raise RuntimeError(f"CF_PRICE_RULE_GATE_FAILED:{rule_gate}")

    rows = []
    departed = trades[(trades["group"] == "C1") & trades["departed_progressed"].astype(bool)]
    for _, row in departed.iterrows():
        observed = pd.Timestamp(row["first_departure_effective"])
        if observed > pd.Timestamp(row["exit_signal_date"] if isinstance(row["exit_signal_date"], str) else "2100-01-01"):
            raise RuntimeError("DEPARTURE_AFTER_EXIT_SIGNAL")
        date, price = next_session_open(daily_for(row), observed, support_for(row))
        control = float(row["terminal_return"])
        actual_exit = pd.Timestamp(row["exit_execution_date"]) if isinstance(row["exit_execution_date"], str) else None
        if date is None or (actual_exit is not None and actual_exit <= date):
            full, cf_date = control, actual_exit
        else:
            full, cf_date = pct(price, float(row["entry_open"])), date
        closed = row["trade_status"] != "OPEN_AT_CUTOFF"
        control_year = actual_exit.year if actual_exit is not None else None
        rows.append({
            **{k: row[k] for k in KEY}, "market": row["market"], "trade_status": row["trade_status"], "exit_type": row["exit_type"],
            "first_departure_stage": row["first_departure_stage"], "first_departure_effective": row["first_departure_effective"],
            "cf_exit_date": cf_date.strftime("%Y-%m-%d") if cf_date is not None else None, "cf_exit_open": price,
            "control_return": control, "cf_full_return": full, "cf_half_return": half_exit(control, full),
            "control_net": net_return(control, control_year, closed),
            "cf_full_net": net_return(full, cf_date.year if cf_date is not None else None, True),
            "filled": row.get("filled"),
        })
    frame = pd.DataFrame(rows)
    frame["cf_half_net"] = [half_exit(c, f) for c, f in zip(frame["control_net"], frame["cf_full_net"])]
    return frame, rule_gate


def cf_summary(cf: pd.DataFrame, panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for panel, part in cf.groupby("panel", sort=False):
        for basis, suffix in (("GROSS_LEDGER_BASIS", "return"), ("NET_REALISTIC_COST_BASIS", "net")):
            if basis.startswith("NET") and not panel.startswith("REALISTIC"):
                continue
            control = part[f"control_{suffix}"]
            for scenario, col in (("CONTROL", f"control_{suffix}"), ("CF_FULL_EXIT", f"cf_full_{suffix}"), ("CF_HALF_EXIT", f"cf_half_{suffix}")):
                values = part[col]
                row = {"panel": panel, "basis": basis, "scenario": scenario, "tier": tier(len(part)), **return_stats(values)}
                row["improved_vs_control"] = int((values > control + 1e-9).sum())
                row["worsened_vs_control"] = int((values < control - 1e-9).sum())
                row["winner50_damaged"] = int(((control >= 50) & (values < 50)).sum())
                row["winner100_damaged"] = int(((control >= 100) & (values < 100)).sum())
                row["sum_return_change_pp"] = wl._round((values - control).sum())
                row["loss_le30_avoided"] = int(((control <= -30) & (values > -30)).sum())
                row["loss_le50_avoided"] = int(((control <= -50) & (values > -50)).sum())
                total = len(panels[panel]) if panel in panels else None
                row["panel_all_trades_n"] = total
                row["panel_mean_return_shift_pp"] = wl._round((values - control).sum() / total) if total else None
                rows.append(row)
    return pd.DataFrame(rows)


def weak_analysis(trades: pd.DataFrame, repo_days: dict[str, pd.DatetimeIndex]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c1 = trades[trades["group"] == "C1"].copy()
    patterns = c1["post_anchor_path"].map(weak_return_pattern)
    c1 = c1.join(pd.DataFrame(list(patterns), index=c1.index))
    if (c1["departed"] != c1["departed_progressed"].astype(bool)).any():
        raise RuntimeError("DEPARTURE_FLAG_MISMATCH_WITH_PATH")
    if (c1["weak_after_departure"] != c1["ever_weak_after_anchor"].astype(bool)).any():
        raise RuntimeError("WEAK_FLAG_MISMATCH_WITH_PATH")
    c1["departure_group"] = [departure_group(p) for p in patterns]

    def trading_days(key: tuple, start: Any, end: Any) -> int | None:
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        index = repo_days.get(key)
        if index is None:
            return None
        return int(((index > pd.Timestamp(start)) & (index <= pd.Timestamp(end))).sum())

    keys = list(zip(c1["ticker"], c1["isu_cd"], c1["identity_effective_from"]))
    c1["departure_to_weak_days"] = [trading_days(k, s, e) for k, s, e in zip(keys, c1["first_departure_effective"], c1["first_weak_effective"])]
    for t in (30, 50):
        after = c1[f"touch_{t}_date"].astype(str) > c1["first_weak_effective"].astype(str)
        c1[f"weak_to_touch_{t}_days"] = [trading_days(k, w, d) if isinstance(w, str) and isinstance(d, str) and d > w else None
                                         for k, w, d in zip(keys, c1["first_weak_effective"], c1[f"touch_{t}_date"])]
        c1[f"touch_{t}_after_weak"] = after & c1[f"touch_{t}_date"].notna() & c1["first_weak_effective"].notna()

    departed_mask = c1["departed"].astype(bool)
    weak_mask = c1["weak_after_departure"].astype(bool)
    views = {
        "ALL_C1": pd.Series(True, index=c1.index),
        "C1_NOT_DEPARTED": ~departed_mask,
        "DEPARTED_ALL": departed_mask,
        "DEPARTED_NO_WEAK": departed_mask & ~weak_mask,
        "DEPARTED_WEAK": weak_mask,
        "DEPARTED_RETURNED_TO_PROGRESSED": c1["returned_after_departure"].astype(bool),
        **{g: c1["departure_group"] == g for g in ("NO_WEAK_NO_RETURN", "NO_WEAK_RETURN", "WEAK_NO_RETURN", "WEAK_THEN_RETURN")},
    }
    rows = []
    for panel, part_all in c1.groupby("panel", sort=False):
        for name, mask in views.items():
            part = part_all[mask.loc[part_all.index]]
            r = part["terminal_return"].astype(float)
            touched15 = part["touch_15_date"].notna()
            rows.append({
                "panel": panel, "group": name, "tier": tier(len(part)), **return_stats(r),
                "mfe_median": wl._round(part["mfe"].median()) if len(part) else None, "mae_median": wl._round(part["mae"].median()) if len(part) else None,
                "departure_to_weak_days_median": wl._round(pd.to_numeric(part["departure_to_weak_days"], errors="coerce").median()) if len(part) else None,
                "weak_to_touch30_days_median": wl._round(pd.to_numeric(part["weak_to_touch_30_days"], errors="coerce").median()) if len(part) else None,
                "weak_to_touch50_days_median": wl._round(pd.to_numeric(part["weak_to_touch_50_days"], errors="coerce").median()) if len(part) else None,
                "return_at_departure_median": wl._round(part["return_at_first_departure"].median()) if len(part) else None,
                "breakeven_recovered_after_touch15_pct": wl._round(part.loc[touched15, "touch_15_recovered_to_breakeven"].astype(bool).mean() * 100.0) if touched15.any() else None,
                "open_at_cutoff": int((part["trade_status"] == "OPEN_AT_CUTOFF").sum()),
                "exit_type_mix": "; ".join(f"{k}={v}" for k, v in part["exit_type"].value_counts().items()),
            })
    groups = pd.DataFrame(rows)

    flag_rows = []
    for panel, part in c1.groupby("panel", sort=False):
        r = part["terminal_return"].astype(float)
        for flag, mask in (("FLAG_DEPARTED", part["departed"]), ("FLAG_DEPARTED_AND_WEAK", part["weak_after_departure"])):
            n = int(mask.sum())
            flag_rows.append({
                "panel": panel, "flag": flag, "c1_n": int(len(part)), "flagged_n": n,
                "deep30_total": int((r <= -30).sum()), "deep30_flagged": int(((r <= -30) & mask).sum()),
                "deep50_total": int((r <= -50).sum()), "deep50_flagged": int(((r <= -50) & mask).sum()),
                "win50_total": int((r >= 50).sum()), "win50_flagged": int(((r >= 50) & mask).sum()),
                "win100_total": int((r >= 100).sum()), "win100_flagged": int(((r >= 100) & mask).sum()),
                "flagged_deep30_rate_pct": wl._round(((r <= -30) & mask).sum() / n * 100.0) if n else None,
                "flagged_win50_rate_pct": wl._round(((r >= 50) & mask).sum() / n * 100.0) if n else None,
                "deep30_capture_pct": wl._round(((r <= -30) & mask).sum() / max((r <= -30).sum(), 1) * 100.0),
                "win50_flagged_pct": wl._round(((r >= 50) & mask).sum() / max((r >= 50).sum(), 1) * 100.0),
            })
    return c1, groups, pd.DataFrame(flag_rows)


def pass_decomposition(trades: pd.DataFrame, repo: Any, cf_support: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    passes = trades[(trades["group"] == "A") & (trades["strict_class"] == lc.STRICT_PASS)].copy()
    if not (passes["entry_pattern_a_stage"].str.upper() == "EARLY_TREND").all():
        raise RuntimeError("PASS_NOT_EARLY_TREND_ENTRY")
    daily_cache: dict = {}
    rows = []
    for _, row in passes.iterrows():
        key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
        if key not in daily_cache:
            daily_cache[key] = repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
        entry_open = float(row["entry_open"])
        final = float(row["terminal_return"])
        anchor = float(row["return_at_anchor"])
        terminal_price = entry_open * (1.0 + final / 100.0)
        anchor_date = pd.Timestamp(row["anchor_effective"])
        add_date, add_open = next_session_open(daily_cache[key], anchor_date, cf_support(row))
        exit_exec = pd.Timestamp(row["exit_execution_date"]) if isinstance(row["exit_execution_date"], str) else None
        add_valid = add_date is not None and (exit_exec is None or add_date < exit_exec)
        rows.append({
            **{k: row[k] for k in KEY}, "market": row["market"], "trade_status": row["trade_status"], "exit_type": row["exit_type"],
            "entry_open": entry_open, "anchor_effective": row["anchor_effective"], "entry_origin": row["entry_origin"],
            "entry_to_anchor_trading_days": row["entry_to_anchor_trading_days"], "post_anchor_trading_days": row["post_anchor_trading_days"],
            "return_at_anchor": anchor, "terminal_return": final,
            "anchor_to_terminal_return": wl._round(((1.0 + final / 100.0) / (1.0 + anchor / 100.0) - 1.0) * 100.0),
            "post_anchor_share_of_gain_pct": wl._round((final - anchor) / final * 100.0) if final > 0 else None,
            "confirmation_next_open_date": add_date.strftime("%Y-%m-%d") if add_valid else None,
            "confirmation_next_open_to_terminal_return": wl._round((terminal_price / add_open - 1.0) * 100.0) if add_valid else None,
            "filled": row.get("filled"),
        })
    detail = pd.DataFrame(rows)
    summary = []
    for panel, part in detail.groupby("panel", sort=False):
        for subset_name, mask in (("ALL_PASS", part.index == part.index), ("PASS_WIN50", part["terminal_return"] >= 50),
                                  ("PASS_WIN100", part["terminal_return"] >= 100), ("PASS_LOSS", part["terminal_return"] <= 0)):
            sub = part[mask]
            summary.append({
                "panel": panel, "subset": subset_name, "tier": tier(len(sub)), "n": int(len(sub)),
                **{f"{c}_{s}": wl._round(getattr(pd.to_numeric(sub[c], errors="coerce"), s)()) if len(sub) else None
                   for c in ("return_at_anchor", "terminal_return", "anchor_to_terminal_return", "confirmation_next_open_to_terminal_return",
                             "entry_to_anchor_trading_days", "post_anchor_trading_days") for s in ("mean", "median")},
                "anchor_to_terminal_q25": wl._round(sub["anchor_to_terminal_return"].quantile(0.25)) if len(sub) else None,
                "anchor_to_terminal_q75": wl._round(sub["anchor_to_terminal_return"].quantile(0.75)) if len(sub) else None,
                "post_anchor_share_of_gain_median_pct": wl._round(sub["post_anchor_share_of_gain_pct"].median()) if len(sub) else None,
                "aggregate_post_anchor_share_pct": wl._round((sub["terminal_return"] - sub["return_at_anchor"]).sum() / sub["terminal_return"].sum() * 100.0)
                if len(sub) and sub["terminal_return"].sum() > 0 else None,
                "confirmation_to_terminal_le_neg15": int((sub["confirmation_next_open_to_terminal_return"] <= -15).sum()) if len(sub) else None,
                "confirmation_to_terminal_positive_pct": wl._round((sub["confirmation_next_open_to_terminal_return"] > 0).mean() * 100.0) if len(sub) else None,
            })
    return detail, pd.DataFrame(summary)


def entry_score_diagnostic(panels: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    enrichment = pd.read_csv(wl.ENRICHMENT_PATH, dtype={"ticker": str, "isu_cd": str})
    enrichment["ticker"] = enrichment["ticker"].str.zfill(6)
    cache = enrichment[["ticker", "isu_cd", "entry_signal_date", "pattern_a_score"]]
    rows, bucket_rows = [], []
    for panel, frame in panels.items():
        early = frame[frame["entry_pattern_a_stage"].astype(str).str.upper() == "EARLY_TREND"].copy()
        early["ticker"] = early["ticker"].astype(str).str.zfill(6)
        early = early.merge(cache, on=["ticker", "isu_cd", "entry_signal_date"], how="left", validate="many_to_one")
        for score in ("pattern_a_score", "fast_score"):
            values = {c: pd.to_numeric(early.loc[early["strict_class"] == c, score], errors="coerce").dropna() for c in (lc.STRICT_PASS, lc.STRICT_FAIL, lc.STRICT_NONE)}
            for cls, v in values.items():
                rows.append({"panel": panel, "score": score, "strict_class": cls, "n": int(len(v)), "joined_pct": wl._round(len(v) / max((early["strict_class"] == cls).sum(), 1) * 100.0),
                             "mean": wl._round(v.mean()) if len(v) else None, "median": wl._round(v.median()) if len(v) else None,
                             "q25": wl._round(v.quantile(0.25)) if len(v) else None, "q75": wl._round(v.quantile(0.75)) if len(v) else None})
            auc_pf = wl.rank_auc(values[lc.STRICT_PASS], values[lc.STRICT_FAIL])
            auc_p_rest = wl.rank_auc(values[lc.STRICT_PASS], pd.concat([values[lc.STRICT_FAIL], values[lc.STRICT_NONE]]))
            rows.append({"panel": panel, "score": score, "strict_class": "AUC_PASS_vs_FAIL", "n": int(min(len(values[lc.STRICT_PASS]), len(values[lc.STRICT_FAIL]))), "mean": wl._round(auc_pf)})
            rows.append({"panel": panel, "score": score, "strict_class": "AUC_PASS_vs_FAIL_OR_NONE", "n": int(len(values[lc.STRICT_PASS])), "mean": wl._round(auc_p_rest)})
        edges = [0, 20, 40, 60, 80, 100.0001]
        labels = ["[0,20)", "[20,40)", "[40,60)", "[60,80)", "[80,100]"]
        early["pa_bucket"] = pd.cut(early["pattern_a_score"], edges, right=False, labels=labels)
        for label in labels:
            sub = early[early["pa_bucket"] == label]
            n = len(sub)
            bucket_rows.append({"panel": panel, "pattern_a_score_bucket": label, "early_trend_entries": int(n),
                                "pass": int((sub["strict_class"] == lc.STRICT_PASS).sum()), "fail": int((sub["strict_class"] == lc.STRICT_FAIL).sum()),
                                "no_next": int((sub["strict_class"] == lc.STRICT_NONE).sum()),
                                "pass_rate_pct": wl._round((sub["strict_class"] == lc.STRICT_PASS).mean() * 100.0) if n else None})
    return pd.DataFrame(rows), pd.DataFrame(bucket_rows)


def run() -> None:
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    trades, panels, gates = load_inputs()
    repo = build_production_repository_v2(ROOT, end=lc.REPOSITORY_END)

    def support_for(row: pd.Series) -> pd.Timestamp:
        if row["panel"] == "SIMPLE_POOLED_DEDUP":
            pooled = panels["SIMPLE_POOLED_DEDUP"]
            cutoff = str(pooled.loc[(pooled["ticker"] == row["ticker"]) & (pooled["trade_id"] == row["trade_id"])
                                    & (pooled["entry_signal_date"] == row["entry_signal_date"]), "window_cutoff"].iloc[0])
            return pd.Timestamp("2026-09-01" if cutoff >= "2026" else "2025-06-02")
        return pd.Timestamp(EXECUTION_SUPPORT[window_of(row["panel"])])

    cf, rule_gate = counterfactuals(trades, repo, support_for)
    cf.to_csv(OUTPUT_DIR / "c1_departure_counterfactual_trades.csv", index=False)
    cf_table = cf_summary(cf, panels)
    cf_table.to_csv(OUTPUT_DIR / "c1_departure_counterfactual_summary.csv", index=False)

    c1_rows = trades[trades["group"] == "C1"]
    days = {key: repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).index
            for key in set(zip(c1_rows["ticker"], c1_rows["isu_cd"], c1_rows["identity_effective_from"]))}
    c1, weak_groups, weak_flags = weak_analysis(trades, days)
    weak_groups.to_csv(OUTPUT_DIR / "departure_weak_group_profile.csv", index=False)
    weak_flags.to_csv(OUTPUT_DIR / "departure_vs_weak_flag_comparison.csv", index=False)
    c1[KEY + ["group", "departure_group", "departed", "weak_after_departure", "returned_after_departure", "returned_after_weak",
              "first_departure_stage", "first_departure_effective", "first_weak_effective", "departure_to_weak_days",
              "weak_to_touch_30_days", "weak_to_touch_50_days", "terminal_return", "mfe", "mae", "trade_status", "exit_type",
              "post_anchor_path"]].to_csv(OUTPUT_DIR / "c1_departure_weak_trades.csv", index=False)

    decomposition, decomposition_summary = pass_decomposition(trades, repo, support_for)
    decomposition.to_csv(OUTPUT_DIR / "strict_pass_return_decomposition_trades.csv", index=False)
    decomposition_summary.to_csv(OUTPUT_DIR / "strict_pass_return_decomposition_summary.csv", index=False)

    scores, buckets = entry_score_diagnostic(panels)
    scores.to_csv(OUTPUT_DIR / "early_trend_entry_score_by_strict_class.csv", index=False)
    buckets.to_csv(OUTPUT_DIR / "early_trend_pattern_a_score_bucket_pass_rate.csv", index=False)

    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_DEPARTURE_CF_WEAK_SCALE_V01",
        "strategy_id": lc.STRATEGY_ID,
        "scope": "CONTROL only; archived certified ledgers; holding lifecycle only; trade-level counterfactuals only (no portfolio replay); no backtest, strategy implementation, threshold sweep, or network",
        "inputs": {"a_vs_c1_trade_level_sha256": wl.sha256_file(AVC1_DIR / "a_vs_c1_trade_level.csv"),
                   "monthly_stage_cache_sha256": wl.sha256_file(lc.STAGE_CACHE_PATH)},
        "gates": {**gates, "cf_price_rule_gate_a_exit3": rule_gate,
                  "departure_flag_matches_path": True, "weak_flag_matches_path": True},
        "counterfactual_contract": {
            "CONTROL": "actual ledger terminal_return",
            "CF_FULL_EXIT": "sell 100% at the next session open after the first PROGRESSED departure label's effective date (same rule as the actual Exit3 execution); if the actual exit came first, the actual result is kept",
            "CF_HALF_EXIT": "0.5 * CF_FULL_EXIT + 0.5 * CONTROL on the entry-cost basis",
            "basis": "GROSS_LEDGER_BASIS for every panel (same price basis as the ledger); REALISTIC panels also NET_REALISTIC_COST_BASIS with the realistic run cost contract (buy/sell slippage 0.1%, commission 0.015%, year sell tax); open positions marked at the cutoff close without sell costs",
            "not_computed": "capital redeployment, portfolio replay, other exit timings",
        },
        "decomposition_contract": "return_at_anchor = close at the first PROGRESSED label's effective date / entry_open - 1; anchor_to_terminal = (1+final)/(1+anchor)-1; confirmation_next_open_to_terminal = terminal price / next session open after the anchor observation - 1 (descriptive only, not a scale-up backtest)",
        "tiers": TIERS,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(rule_gate), flush=True)


def main() -> None:
    audit = {"count": 0}
    with wl.network_guard(audit):
        run()
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
