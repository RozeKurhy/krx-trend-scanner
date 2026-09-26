"""A FAST Core V2 realistic P2 winner/loser + lifecycle profile V01.

인증된 현실적 포트폴리오 실행(P2-1, P2-2, survivor-only + PIT 시총 1조 이상)의 CONTROL 산출물만 읽어
두 층을 따로 분석한다.

- ELIGIBLE: 현실적 universe를 통과한 CONTROL 전략 거래 전체(`control_strategy_trades.csv`)
- FILLED: 포트폴리오에서 실제 체결된 거래(`control_portfolio_events.csv`의 ENTRY/EXECUTED)

수익률은 두 가지를 섞지 않는다.

- 기본: 원장 `terminal_return`(broad 연구와 같은 계약, OPEN_AT_CUTOFF는 cutoff 평가값)
- 보조: 체결 후 청산된 거래의 비용 반영 순수익률(인증 headline 재현과 민감도 전용)

새 백테스트, 전략 재평가, feature 재계산, 네트워크 호출은 하지 않는다. 진입 feature는 상위
`winner_loser_profile_v01`의 PIT 복원 캐시를 (ticker, isu_cd, entry_signal_date)로 재사용한다.

사용법:
    python scripts/analyze_realistic_p2_winner_loser_lifecycle_v01.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import scripts.analyze_fastcore_v2_winner_loser_profile_v01 as wl  # noqa: E402

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/realistic_p2_winner_loser_lifecycle_v01"
PARENT_DIR = wl.OUTPUT_DIR
RUNS: dict[str, dict[str, Any]] = {
    "P2-1": {
        "run_dir": ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01",
        "status": "P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
        "universe_audit": "filtered_universe_audit.csv",
    },
    "P2-2": {
        "run_dir": ROOT / "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01",
        "status": "P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
        "universe_audit": "survivor_universe_audit.csv",
    },
}
WINDOWS = ["P2-1", "P2-2"]
LAYERS = ["ELIGIBLE", "FILLED"]
# 요청서에 적힌 인증 체결 수. summary.csv 재현과 별도로 확인한다.
EXPECTED_FILLED = {"P2-1": 199, "P2-2": 242}
MCAP_THRESHOLD_EOK = 10_000.0

ENRICHED_COLUMNS = [
    "pattern_a_score", "avg_trading_value_20d_eok", "wma52_slope_1w", "atr_14_pct", "range_position_24m",
    "wma12_vs_wma26_pct", "close_vs_wma200_pct", "post_breakout_min_low_vs_level_pct_26w",
]
NUMERIC_ENTRY = [
    "pattern_a_score", "fast_score", "market_cap_eok", "avg_trading_value_20d_eok", "wma52_slope_1w", "atr_14_pct",
    "range_position_24m", "wma12_vs_wma26_pct", "close_vs_wma200_pct", "post_breakout_min_low_vs_level_pct_26w",
]
CATEGORICAL_ENTRY: dict[str, list[str] | None] = {
    "market": ["KOSDAQ"],
    "entry_pattern_a_stage": ["EARLY_TREND"],
    "fast_score_state": ["PARTIAL"],
}
# 진입 후 상태(설명력 비교 전용). 0/1 지시변수에 rank AUC를 적용하면 0.5 + 비율차/2가 된다.
POST_ENTRY_INDICATORS = ["is_normal_handoff", "is_coverage_path"]
PROFILE_MIN_N = 10

# broad 대비 분류와 최종 판정 규칙(결과 확인 전에 고정).
BROAD_CLASS_RULES = {
    "baseline": "parent lifecycle_window_consistency WINDOW_P2-1 / WINDOW_P2-2 (same window and cutoff); broad pooled is a secondary column",
    "MAINTAINED": "same sign and |realistic| >= 50% of |broad same-window|",
    "WEAKENED": "same sign and 20% <= ratio < 50%",
    "VANISHED": "ratio < 20% or realistic difference exactly 0",
    "REVERSED": "opposite non-zero sign",
    "NOT_COMPARABLE": "broad same-window difference is 0",
}
FILLED_KEY_METRICS = ["mean_return", "ge_50_rate_pct", "ge_100_rate_pct"]
VERDICT_RULES = {
    "comparison": "NORMAL_vs_COVERAGE_COMBINED on ledger terminal_return, ALL trades",
    "evaluable_panel": "NORMAL n >= 10 and COVERAGE n >= 10",
    "eligible_panel_favorable": "favorable > unfavorable over the 7 key metrics",
    "filled_panel_favorable": "mean difference > 0 and >= 2 of (mean, +50%, +100%) favorable; filled tail rates are descriptive only",
    "INSUFFICIENT_EVIDENCE": "fewer than 2 evaluable ELIGIBLE panels",
    "REALISTIC_P2_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE": "every evaluable panel favorable; every ELIGIBLE panel has 0 REVERSED key metrics, mean and +50% MAINTAINED vs broad same window, and |AUC-0.5| >= 0.05",
    "REALISTIC_P2_LIFECYCLE_EFFECT_WEAK": "ELIGIBLE mean differences all > 0 but every ELIGIBLE mean is VANISHED, or every ELIGIBLE |AUC-0.5| < 0.05",
    "REALISTIC_P2_PARTIALLY_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE": "every evaluable ELIGIBLE panel favorable with mean difference > 0",
    "REALISTIC_P2_LIFECYCLE_EFFECT_MIXED": "otherwise",
    "order": ["INSUFFICIENT_EVIDENCE", "CONFIRMS", "WEAK", "PARTIALLY", "MIXED"],
    "nesting_note": "P2-1 is the early part of P2-2 and FILLED is a subset of ELIGIBLE; agreement across the 4 panels is not four independent confirmations",
}


# ---------------------------------------------------------------------------
# 로드와 인증 headline 재현 게이트
# ---------------------------------------------------------------------------

def load_run(window: str) -> dict[str, Any]:
    run_dir = RUNS[window]["run_dir"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if summary.get("status") != RUNS[window]["status"] or summary.get("window_id") != window:
        raise RuntimeError(f"REALISTIC_RUN_STATUS_MISMATCH:{window}:{summary.get('status')}")
    if summary["strategy_ids"]["control"] != STRATEGY_ID:
        raise RuntimeError(f"CONTROL_STRATEGY_ID_MISMATCH:{window}")
    trades = pd.read_csv(run_dir / "control_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str}, low_memory=False)
    trades["ticker"] = trades["ticker"].str.zfill(6)
    events = pd.read_csv(run_dir / "control_portfolio_events.csv", dtype={"ticker": str, "isu_cd": str}, low_memory=False)
    events["ticker"] = events["ticker"].str.zfill(6)
    metrics = pd.read_csv(run_dir / "summary.csv")
    control_metrics = dict(zip(metrics.loc[metrics["strategy"] == "CONTROL", "metric"], metrics.loc[metrics["strategy"] == "CONTROL", "value"]))
    equity = pd.read_csv(run_dir / "control_daily_equity.csv")
    return {"summary": summary, "trades": trades, "events": events, "control_metrics": control_metrics, "equity": equity}


def net_realized_returns(trades: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """체결 후 청산된 거래의 비용 반영 순수익률(%). 러너의 net_return 정의와 같다."""
    entries = events[(events["event_type"] == "ENTRY") & (events["event_status"] == "EXECUTED")]
    exits = events[(events["event_type"] == "EXIT") & (events["event_status"] == "EXECUTED")]
    if entries["pair_id"].duplicated().any() or exits["pair_id"].duplicated().any():
        raise RuntimeError("EXECUTED_EVENT_PAIR_ID_DUPLICATE")
    buy = entries.assign(buy_cost=entries["notional"] + entries["commission"])[["pair_id", "buy_cost"]]
    sell = exits.assign(proceeds=exits["notional"] - exits["commission"] - exits["sell_tax"])[["pair_id", "proceeds"]]
    merged = sell.merge(buy, on="pair_id", how="left", validate="one_to_one")
    if merged["buy_cost"].isna().any():
        raise RuntimeError("EXIT_WITHOUT_EXECUTED_ENTRY")
    merged["net_realized_return"] = (merged["proceeds"] / merged["buy_cost"] - 1.0) * 100.0
    check = merged.merge(trades[["pair_id", "terminal_return"]], on="pair_id", how="left", validate="one_to_one")
    ratio = (1.0 + check["net_realized_return"] / 100.0) / (1.0 + check["terminal_return"] / 100.0)
    # 체결 슬리피지·수수료·세금은 가격 비율에 곱해지는 비용이라 비율은 1보다 약간 작아야 한다.
    bad = check[(ratio >= 1.0) | (ratio < 0.99)]
    if len(bad):
        raise RuntimeError(f"NET_RETURN_COST_HAIRCUT_OUT_OF_RANGE:{bad['pair_id'].head().tolist()}")
    return merged[["pair_id", "net_realized_return"]]


def headline_gate(window: str, run: dict[str, Any]) -> dict[str, Any]:
    events, metrics, equity = run["events"], run["control_metrics"], run["equity"]
    net = net_realized_returns(run["trades"], events)["net_realized_return"]
    effective_end = run["summary"]["window"]["effective_end"]
    at_end = equity[equity["date"] == effective_end]
    if len(at_end) != 1:
        raise RuntimeError(f"EQUITY_EFFECTIVE_END_ROW_MISSING:{window}")
    observed = {
        "trade_count": int(((events["event_type"] == "ENTRY") & (events["event_status"] == "EXECUTED")).sum()),
        "realized_trade_count": int(((events["event_type"] == "EXIT") & (events["event_status"] == "EXECUTED")).sum()),
        "cash_shortage_skipped_entries": int(((events["event_type"] == "ENTRY") & (events["event_status"] == "SKIPPED_CASH_UNAVAILABLE")).sum()),
        "win_rate_pct": float((net > 0).mean() * 100.0),
        "realized_return_le_neg_30_count": int((net <= -30).sum()),
        "realized_return_le_neg_40_count": int((net <= -40).sum()),
        "realized_return_le_neg_50_count": int((net <= -50).sum()),
        "realized_return_le_neg_60_count": int((net <= -60).sum()),
        "realized_return_ge_pos_50_count": int((net >= 50).sum()),
        "realized_return_ge_pos_100_count": int((net >= 100).sum()),
        "final_equity_at_effective_close": float(at_end["equity"].iloc[0]),
        "mdd_pct": float(equity.loc[equity["date"] <= effective_end, "drawdown"].min() * 100.0),
    }
    result: dict[str, Any] = {}
    for key, value in observed.items():
        certified = float(metrics[key])
        match = math.isclose(value, certified, rel_tol=0, abs_tol=1e-4 if key != "final_equity_at_effective_close" else 1e-3)
        result[key] = {"observed": value, "certified": certified, "match": bool(match)}
        if not match:
            raise RuntimeError(f"HEADLINE_GATE_MISMATCH:{window}:{key}:{value}:{certified}")
    if observed["trade_count"] != EXPECTED_FILLED[window]:
        raise RuntimeError(f"FILLED_COUNT_NOT_REQUESTED_VALUE:{window}")
    eligible = len(run["trades"])
    if eligible != int(run["summary"]["population"]["control_trade_rows"]):
        raise RuntimeError(f"ELIGIBLE_COUNT_MISMATCH:{window}")
    if eligible - observed["trade_count"] != observed["cash_shortage_skipped_entries"]:
        raise RuntimeError(f"ELIGIBLE_MINUS_FILLED_NOT_CASH_SKIPS:{window}")
    if run["trades"]["pair_id"].duplicated().any():
        raise RuntimeError(f"TRADE_PAIR_ID_DUPLICATE:{window}")
    return {"eligible_trades": eligible, "checks": result, "all_match": True}


# ---------------------------------------------------------------------------
# 패널 구성
# ---------------------------------------------------------------------------

def load_enrichment() -> pd.DataFrame:
    enrichment = pd.read_csv(wl.ENRICHMENT_PATH, dtype={"ticker": str, "isu_cd": str})
    enrichment["ticker"] = enrichment["ticker"].str.zfill(6)
    audit = json.loads(wl.ENRICHMENT_AUDIT_PATH.read_text(encoding="utf-8"))
    if audit["enrichment_sha256"] != wl.sha256_file(wl.ENRICHMENT_PATH):
        raise RuntimeError("PARENT_ENRICHMENT_SHA_MISMATCH")
    if enrichment.duplicated(["ticker", "isu_cd", "entry_signal_date"]).any():
        raise RuntimeError("PARENT_ENRICHMENT_KEY_NOT_UNIQUE")
    return enrichment


def build_panel_frame(run: dict[str, Any], enrichment: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    trades = run["trades"].copy()
    events = run["events"]
    filled_ids = set(events.loc[(events["event_type"] == "ENTRY") & (events["event_status"] == "EXECUTED"), "pair_id"])
    trades["filled"] = trades["pair_id"].isin(filled_ids)
    trades = trades.merge(net_realized_returns(run["trades"], events), on="pair_id", how="left", validate="one_to_one")
    trades["market_cap_eok"] = pd.to_numeric(trades["entry_market_cap"], errors="coerce") / 1e8
    trades["entry_year"] = trades["entry_signal_date"].str[:4]
    trades["is_normal_handoff"] = (trades["lifecycle_class"] == wl.NORMAL).astype(float)
    trades["is_coverage_path"] = trades["lifecycle_class"].isin(wl.LIFECYCLE_GROUPS[wl.COVERAGE]).astype(float)
    cache = enrichment[["ticker", "isu_cd", "entry_signal_date", "enrichment_status", "ledger_fast_score", "ledger_entry_pattern_a_stage", *ENRICHED_COLUMNS]]
    merged = trades.merge(cache, on=["ticker", "isu_cd", "entry_signal_date"], how="left", validate="many_to_one", indicator=True)
    merged["feature_cache_joined"] = merged["_merge"] == "both"
    joined = merged[merged["feature_cache_joined"]]
    fast_mismatch = int((joined["fast_score"] - joined["ledger_fast_score"]).abs().gt(0.011).sum())
    stage_mismatch = int((joined["entry_pattern_a_stage"] != joined["ledger_entry_pattern_a_stage"]).sum())
    if fast_mismatch or stage_mismatch or (joined["enrichment_status"] != "READY").any():
        raise RuntimeError(f"FEATURE_CACHE_JOIN_INCONSISTENT:fast={fast_mismatch}:stage={stage_mismatch}")
    if len(merged) != len(trades):
        raise RuntimeError("FEATURE_CACHE_JOIN_DUPLICATED_ROWS")
    merged = merged.drop(columns=["_merge", "ledger_fast_score", "ledger_entry_pattern_a_stage", "enrichment_status"])
    audit = {
        "rows": int(len(merged)),
        "joined": int(merged["feature_cache_joined"].sum()),
        "fast_score_mismatch": fast_mismatch,
        "stage_mismatch": stage_mismatch,
        "unjoined_policy": "left as NA; features are not recomputed",
    }
    return merged, audit


def layer_frame(frame: pd.DataFrame, layer: str) -> pd.DataFrame:
    return frame if layer == "ELIGIBLE" else frame[frame["filled"]]


def join_coverage(frame: pd.DataFrame, window: str) -> list[dict[str, Any]]:
    rows = []
    for layer in LAYERS:
        data = layer_frame(frame, layer)
        groups = wl.assign_groups(data["terminal_return"].astype(float))
        slices = {"ALL": pd.Series(True, index=data.index)}
        slices.update({name: groups[name] for name in ("WIN_50", "WIN_100", "LOSS_ANY", "LOSS_30")})
        slices.update({f"LIFECYCLE_{name}": data["lifecycle_class"].isin(members) for name, members in wl.LIFECYCLE_GROUPS.items()})
        for name, mask in slices.items():
            n = int(mask.sum())
            joined = int((mask & data["feature_cache_joined"]).sum())
            rows.append({"window": window, "layer": layer, "slice": name, "trades": n, "feature_cache_joined": joined,
                         "joined_pct": wl._round(joined / n * 100.0) if n else None})
    return rows


# ---------------------------------------------------------------------------
# Lifecycle 비교와 broad 대비 분류
# ---------------------------------------------------------------------------

def lifecycle_profile_rows(data: pd.DataFrame, window: str, layer: str) -> list[dict[str, Any]]:
    rows = []
    for version in ("ALL", "CLOSED_ONLY"):
        scoped = data if version == "ALL" else data[data["trade_status"].isin(wl.CLOSED_STATUSES)]
        for group in wl.LIFECYCLE_GROUPS:
            group_frame = wl.lifecycle_group_frame(scoped, group)
            row = {"window": window, "layer": layer, "version": version, "lifecycle_group": group,
                   "role": "REFERENCE_ONLY" if group == wl.NEVER else "PRIMARY", **wl.lifecycle_metrics(group_frame)}
            if layer == "FILLED" and len(group_frame):
                net = group_frame["net_realized_return"].dropna()
                row["net_realized_closed_n"] = int(len(net))
                row["net_realized_mean"] = wl._round(net.mean()) if len(net) else None
                row["net_realized_median"] = wl._round(net.median()) if len(net) else None
            rows.append(row)
    return rows


def lifecycle_comparison_rows(data: pd.DataFrame, window: str, layer: str) -> list[dict[str, Any]]:
    rows = []
    for version in ("ALL", "CLOSED_ONLY"):
        scoped = data if version == "ALL" else data[data["trade_status"].isin(wl.CLOSED_STATUSES)]
        for comparison, first, second in wl.LIFECYCLE_COMPARISONS:
            row = wl.lifecycle_compare(wl.lifecycle_group_frame(scoped, first), wl.lifecycle_group_frame(scoped, second))
            row["evaluable"] = bool(min(row["first_n"], row["second_n"]) >= PROFILE_MIN_N)
            if layer == "FILLED" and row.get("favorable") is not None:
                row["filled_key_favorable"] = int(sum(row[f"{m}_favorable"] == "FAVORABLE" for m in FILLED_KEY_METRICS))
                row["filled_key_unfavorable"] = int(sum(row[f"{m}_favorable"] == "UNFAVORABLE" for m in FILLED_KEY_METRICS))
            rows.append({"window": window, "layer": layer, "version": version, "comparison": comparison, "first": first, "second": second, **row})
    return rows


def classify_vs_broad(realistic: float | None, broad: float | None) -> tuple[str, float | None]:
    if realistic is None or broad is None or (isinstance(broad, float) and math.isnan(broad)):
        return "NOT_COMPARABLE", None
    if broad == 0:
        return "NOT_COMPARABLE", None
    if realistic == 0:
        return "VANISHED", 0.0
    if wl._sign(realistic) != wl._sign(broad):
        return "REVERSED", wl._round(realistic / broad)
    ratio = abs(realistic) / abs(broad)
    if ratio >= 0.5:
        return "MAINTAINED", wl._round(ratio)
    if ratio >= 0.2:
        return "WEAKENED", wl._round(ratio)
    return "VANISHED", wl._round(ratio)


def broad_comparison_rows(comparisons: pd.DataFrame, broad: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    metrics = [m for m, _ in wl.LIFECYCLE_KEY_METRICS] + ["return_auc_effect"]
    primary = comparisons[comparisons["comparison"] == "NORMAL_vs_COVERAGE_COMBINED"]
    for _, row in primary.iterrows():
        same_window = broad[(broad["scope"] == f"WINDOW_{row['window']}") & (broad["version"] == row["version"]) & (broad["comparison"] == row["comparison"])].iloc[0]
        pooled = broad[(broad["scope"] == "POOLED_DEDUP") & (broad["version"] == row["version"]) & (broad["comparison"] == row["comparison"])].iloc[0]
        for metric in metrics:
            column = metric if metric == "return_auc_effect" else f"{metric}_diff"
            realistic = row.get(column)
            realistic = None if realistic is None or (isinstance(realistic, float) and math.isnan(realistic)) else float(realistic)
            broad_value = float(same_window[column])
            label, ratio = classify_vs_broad(realistic, broad_value)
            rows.append({
                "window": row["window"], "layer": row["layer"], "version": row["version"], "metric": metric,
                "realistic_diff": realistic, "broad_same_window_diff": broad_value, "broad_pooled_diff": float(pooled[column]),
                "ratio_vs_broad_same_window": ratio, "classification": label,
                "realistic_normal_n": row["first_n"], "realistic_coverage_n": row["second_n"],
                "filled_descriptive_only": bool(row["layer"] == "FILLED" and metric not in FILLED_KEY_METRICS + ["return_auc_effect"]),
            })
    return rows


def verdict(comparisons: pd.DataFrame, broad_rows: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    primary = comparisons[(comparisons["comparison"] == "NORMAL_vs_COVERAGE_COMBINED") & (comparisons["version"] == "ALL")]
    panels: dict[str, Any] = {}
    for _, row in primary.iterrows():
        key = f"{row['window']}|{row['layer']}"
        cls = broad_rows[(broad_rows["window"] == row["window"]) & (broad_rows["layer"] == row["layer"]) & (broad_rows["version"] == "ALL")]
        classes = dict(zip(cls["metric"], cls["classification"]))
        if row["layer"] == "ELIGIBLE":
            favorable = bool(row["favorable"] > row["unfavorable"])
        else:
            favorable = bool(row["mean_return_diff"] > 0 and row["filled_key_favorable"] >= 2)
        panels[key] = {
            "layer": row["layer"], "evaluable": bool(row["evaluable"]), "favorable": favorable,
            "favorable_unfavorable_7": [int(row["favorable"]), int(row["unfavorable"])],
            "mean_diff": row["mean_return_diff"], "auc_effect": row["return_auc_effect"],
            "classifications": classes,
            "reversed_key_metrics": [m for m, c in classes.items() if c == "REVERSED" and m != "return_auc_effect"],
        }
    evaluable = {k: v for k, v in panels.items() if v["evaluable"]}
    eligible = {k: v for k, v in evaluable.items() if v["layer"] == "ELIGIBLE"}
    detail = {"panels": panels, "evaluable_panels": sorted(evaluable), "evaluable_eligible_panels": sorted(eligible)}
    if len(eligible) < 2:
        return "INSUFFICIENT_EVIDENCE", detail
    confirms = all(v["favorable"] for v in evaluable.values()) and all(
        not v["reversed_key_metrics"]
        and v["classifications"].get("mean_return") == "MAINTAINED"
        and v["classifications"].get("ge_50_rate_pct") == "MAINTAINED"
        and abs(v["auc_effect"]) >= 0.05
        for v in eligible.values()
    )
    if confirms:
        return "REALISTIC_P2_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE", detail
    positive_means = all(v["mean_diff"] > 0 for v in eligible.values())
    weak = positive_means and (
        all(v["classifications"].get("mean_return") == "VANISHED" for v in eligible.values())
        or all(abs(v["auc_effect"]) < 0.05 for v in eligible.values())
    )
    if weak:
        return "REALISTIC_P2_LIFECYCLE_EFFECT_WEAK", detail
    if positive_means and all(v["favorable"] for v in eligible.values()):
        return "REALISTIC_P2_PARTIALLY_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE", detail
    return "REALISTIC_P2_LIFECYCLE_EFFECT_MIXED", detail


# ---------------------------------------------------------------------------
# Winner / loser profile
# ---------------------------------------------------------------------------

def winner_loser_rows(data: pd.DataFrame, window: str, layer: str, broad_profile: pd.DataFrame) -> list[dict[str, Any]]:
    groups = wl.assign_groups(data["terminal_return"].astype(float))
    items = wl.feature_items(data, NUMERIC_ENTRY, CATEGORICAL_ENTRY) + [(name, "numeric", None) for name in POST_ENTRY_INDICATORS]
    rows = []
    for comparison, group, reference, extreme in wl.COMPARISONS:
        for feature, kind, level in items:
            result = wl.compare_feature(data, groups, group, reference, feature, kind, level)
            n_group, n_ref = result.get("group_n", 0) or 0, result.get("reference_n", 0) or 0
            broad_match = broad_profile[(broad_profile["comparison"] == comparison) & (broad_profile["feature"] == feature)]
            if level is not None:
                broad_match = broad_match[broad_match["level"] == level]
            broad_effect = float(broad_match["effect"].iloc[0]) if len(broad_match) else None
            broad_grade = str(broad_match["grade"].iloc[0]) if len(broad_match) else None
            allowed = bool(min(n_group, n_ref) >= PROFILE_MIN_N)
            rows.append({
                "window": window, "layer": layer, "comparison": comparison, "extreme_contrast": extreme,
                "feature": feature, "feature_kind": kind, "level": level,
                "feature_role": "POST_ENTRY_LIFECYCLE" if feature in POST_ENTRY_INDICATORS else "ENTRY",
                **{k: result.get(k) for k in ("n_group_rows", "n_reference_rows", "group_n", "reference_n", "group_median", "reference_median",
                                              "group_share_pct", "reference_share_pct", "auc", "effect", "effect_unit")},
                "profile_allowed": allowed,
                "broad_pooled_effect": broad_effect, "broad_pooled_grade": broad_grade,
                "same_sign_as_broad": (wl._sign(result.get("effect")) == wl._sign(broad_effect)) if allowed and broad_effect is not None else None,
            })
    return rows


def group_count_rows(data: pd.DataFrame, window: str, layer: str) -> dict[str, Any]:
    groups = wl.assign_groups(data["terminal_return"].astype(float))
    row: dict[str, Any] = {"window": window, "layer": layer, "trades": int(len(data))}
    for name in ("WIN_50", "WIN_100", "POSITIVE", "LOSS_ANY", "LOSS_30", "LOSS_50", "LOSS_60"):
        row[name] = int(groups[name].sum())
    for name in ("WIN_50", "WIN_100", "LOSS_30"):
        subset = data[groups[name]]
        for group, members in wl.LIFECYCLE_GROUPS.items():
            row[f"{name}_share_{group}"] = wl._round(subset["lifecycle_class"].isin(members).mean() * 100.0) if len(subset) else None
    return row


def explanatory_power(wl_rows: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    numeric = wl_rows[(wl_rows["feature_kind"] == "numeric") & wl_rows["profile_allowed"]]
    for (window, layer, comparison), sub in numeric.groupby(["window", "layer", "comparison"], sort=False):
        entry = sub[sub["feature_role"] == "ENTRY"].dropna(subset=["effect"])
        post = sub[sub["feature"] == "is_normal_handoff"]
        if entry.empty or post.empty:
            continue
        best = entry.loc[entry["effect"].abs().idxmax()]
        normal_effect = float(post["effect"].iloc[0])
        rows.append({
            "window": window, "layer": layer, "comparison": comparison,
            "best_entry_feature": best["feature"], "best_entry_auc_effect_abs": wl._round(abs(best["effect"])),
            "normal_handoff_auc_effect_abs": wl._round(abs(normal_effect)),
            "lifecycle_larger": bool(abs(normal_effect) > abs(best["effect"])),
        })
    return rows


# ---------------------------------------------------------------------------
# Selection effect, filter attribution, path check
# ---------------------------------------------------------------------------

def selection_rows(frame: pd.DataFrame, window: str) -> list[dict[str, Any]]:
    rows = []
    sets = {"ELIGIBLE": frame, "FILLED": frame[frame["filled"]], "SKIPPED": frame[~frame["filled"]]}
    years = sorted(frame["entry_year"].unique())
    for name, data in sets.items():
        groups = wl.assign_groups(data["terminal_return"].astype(float))
        n = len(data)
        row: dict[str, Any] = {"window": window, "set": name, "trades": int(n)}
        for group, members in wl.LIFECYCLE_GROUPS.items():
            row[f"share_{group}_pct"] = wl._round(data["lifecycle_class"].isin(members).mean() * 100.0)
        for group in ("WIN_50", "WIN_100", "LOSS_30", "LOSS_50"):
            row[f"share_{group}_pct"] = wl._round(groups[group].mean() * 100.0)
        returns = data["terminal_return"].astype(float)
        row.update({
            "mean_return": wl._round(returns.mean()), "median_return": wl._round(returns.median()),
            "median_market_cap_eok": wl._round(data["market_cap_eok"].median()),
            "kospi_share_pct": wl._round((data["market"] == "KOSPI").mean() * 100.0),
        })
        for year in years:
            row[f"entry_year_{year}_share_pct"] = wl._round((data["entry_year"] == year).mean() * 100.0)
        rows.append(row)
    return rows


def filter_attribution(window: str, run: dict[str, Any], enrichment: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """broad 같은 윈도우의 deep loser가 survivor·1조 필터 중 어디서 빠지는지 센다(기존 임계값만 사용)."""
    broad = wl.load_window_ledger(window)
    broad = broad[broad["terminal_return"].notna()].copy()
    audit = pd.read_csv(RUNS[window]["run_dir"] / RUNS[window]["universe_audit"], dtype=str)
    survivor = set(zip(audit.loc[audit["status"] == "SURVIVOR_COMMON_IDENTITY", "ticker"].str.zfill(6), audit.loc[audit["status"] == "SURVIVOR_COMMON_IDENTITY", "isu_cd"]))
    policy_excluded = set(zip(audit.loc[audit["status"] == "EXCLUDED_EXISTING_PERMANENT_IDENTITY_POLICY", "ticker"].str.zfill(6), audit.loc[audit["status"] == "EXCLUDED_EXISTING_PERMANENT_IDENTITY_POLICY", "isu_cd"]))
    pit = pd.read_csv(RUNS[window]["run_dir"] / "pit_mcap_audit.csv", dtype={"ticker": str, "identity": str}, usecols=["ticker", "identity", "signal_date", "market_cap"])
    pit["ticker"] = pit["ticker"].str.zfill(6)
    pit = pit.drop_duplicates(["ticker", "identity", "signal_date"]).rename(columns={"identity": "isu_cd", "signal_date": "entry_signal_date", "market_cap": "pit_market_cap"})
    broad = broad.merge(pit, on=["ticker", "isu_cd", "entry_signal_date"], how="left", validate="many_to_one")
    cache = enrichment[["ticker", "isu_cd", "entry_signal_date", "market_cap_eok"]].rename(columns={"market_cap_eok": "cache_market_cap_eok"})
    broad = broad.merge(cache, on=["ticker", "isu_cd", "entry_signal_date"], how="left", validate="many_to_one")
    broad["entry_market_cap_eok"] = (pd.to_numeric(broad["pit_market_cap"], errors="coerce") / 1e8).fillna(broad["cache_market_cap_eok"])
    keys = list(zip(broad["ticker"], broad["isu_cd"]))
    broad["survivor"] = [k in survivor for k in keys]
    broad["policy_excluded"] = [k in policy_excluded for k in keys]
    broad["mcap_ge_1t"] = broad["entry_market_cap_eok"] >= MCAP_THRESHOLD_EOK

    def bucket(row: pd.Series) -> str:
        if row["policy_excluded"]:
            return "EXCLUDED_EXISTING_POLICY"
        if pd.isna(row["entry_market_cap_eok"]):
            return "MCAP_UNKNOWN"
        if not row["survivor"] and not row["mcap_ge_1t"]:
            return "NON_SURVIVOR_AND_MCAP_LT_1T"
        if not row["survivor"]:
            return "NON_SURVIVOR_ONLY"
        if not row["mcap_ge_1t"]:
            return "MCAP_LT_1T_ONLY"
        return "PASSES_BOTH_FILTERS"

    broad["filter_bucket"] = broad.apply(bucket, axis=1)
    returns = broad["terminal_return"].astype(float)
    coverage = broad["lifecycle_class"].isin(wl.LIFECYCLE_GROUPS[wl.COVERAGE])
    slices = {
        "ALL": pd.Series(True, index=broad.index), "WIN_50": returns >= 50, "WIN_100": returns >= 100,
        "LOSS_30": returns <= -30, "LOSS_50": returns <= -50, "LOSS_60": returns <= -60,
        "COVERAGE_LOSS_30": coverage & (returns <= -30), "COVERAGE_ALL": coverage,
    }
    rows = []
    for name, mask in slices.items():
        subset = broad[mask]
        counts = subset["filter_bucket"].value_counts()
        row = {"window": window, "broad_slice": name, "trades": int(len(subset))}
        for label in ("PASSES_BOTH_FILTERS", "MCAP_LT_1T_ONLY", "NON_SURVIVOR_ONLY", "NON_SURVIVOR_AND_MCAP_LT_1T", "EXCLUDED_EXISTING_POLICY", "MCAP_UNKNOWN"):
            row[label] = int(counts.get(label, 0))
        row["passes_both_pct"] = wl._round(row["PASSES_BOTH_FILTERS"] / len(subset) * 100.0) if len(subset) else None
        rows.append(row)

    realistic = run["trades"]
    key = ["ticker", "isu_cd", "entry_signal_date", "entry_execution_date"]
    matched = realistic.merge(broad[key + ["terminal_return", "lifecycle_class"]], on=key, how="left", suffixes=("", "_broad"), validate="one_to_one")
    in_broad = matched["terminal_return_broad"].notna()
    same = in_broad & (matched["terminal_return"] - matched["terminal_return_broad"]).abs().le(0.005) & (matched["lifecycle_class"] == matched["lifecycle_class_broad"])
    path = {
        "realistic_eligible": int(len(matched)),
        "identity_in_broad_same_window": int(in_broad.sum()),
        "identical_return_and_lifecycle": int(same.sum()),
        "identical_pct_of_matched": wl._round(same.sum() / in_broad.sum() * 100.0) if in_broad.sum() else None,
        "note": "realistic trades are not a pure subset: rejected (< 1T) signals do not consume re-entry state, so later entries can differ",
    }
    return rows, path


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def run(network_audit: dict[str, int]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    enrichment = load_enrichment()
    broad_lifecycle = pd.read_csv(PARENT_DIR / "lifecycle_return_profile_v01/lifecycle_window_consistency.csv")
    broad_profile = pd.read_csv(PARENT_DIR / "entry_feature_profile.csv")

    gates, join_audit, coverage_rows, profile_rows, comparison_rows, wl_rows, count_rows = {}, {}, [], [], [], [], []
    selection, attribution, paths, source_hashes = [], [], {}, {}
    frames: dict[str, pd.DataFrame] = {}
    for window in WINDOWS:
        run_data = load_run(window)
        gates[window] = headline_gate(window, run_data)
        frame, join_audit[window] = build_panel_frame(run_data, enrichment)
        frames[window] = frame
        coverage_rows += join_coverage(frame, window)
        for layer in LAYERS:
            data = layer_frame(frame, layer)
            profile_rows.append((window, layer, pd.DataFrame(lifecycle_profile_rows(data, window, layer))))
            comparison_rows += lifecycle_comparison_rows(data, window, layer)
            wl_rows += winner_loser_rows(data, window, layer, broad_profile)
            count_rows.append(group_count_rows(data, window, layer))
        selection += selection_rows(frame, window)
        rows, paths[window] = filter_attribution(window, run_data, enrichment)
        attribution += rows
        run_dir = RUNS[window]["run_dir"]
        source_hashes[window] = {name: wl.sha256_file(run_dir / name) for name in ("control_strategy_trades.csv", "control_portfolio_events.csv", "control_daily_equity.csv", "summary.csv", "summary.json")}

    for window, layer, table in profile_rows:
        table.to_csv(OUTPUT_DIR / f"{window.lower().replace('-', '_')}_{layer.lower()}_profile.csv", index=False)
    comparisons = pd.DataFrame(comparison_rows)
    comparisons.to_csv(OUTPUT_DIR / "lifecycle_comparison.csv", index=False)
    wl_table = pd.DataFrame(wl_rows)
    wl_table.to_csv(OUTPUT_DIR / "winner_loser_comparison.csv", index=False)
    pd.DataFrame(selection).to_csv(OUTPUT_DIR / "eligible_vs_filled_selection_effect.csv", index=False)
    broad_rows = pd.DataFrame(broad_comparison_rows(comparisons, broad_lifecycle))
    broad_rows.to_csv(OUTPUT_DIR / "broad_vs_realistic_comparison.csv", index=False)
    pd.DataFrame(attribution).to_csv(OUTPUT_DIR / "broad_same_window_filter_attribution.csv", index=False)
    pd.DataFrame(count_rows).to_csv(OUTPUT_DIR / "group_counts.csv", index=False)
    pd.DataFrame(coverage_rows).to_csv(OUTPUT_DIR / "feature_cache_join_coverage.csv", index=False)
    explain = explanatory_power(wl_table)
    pd.DataFrame(explain).to_csv(OUTPUT_DIR / "entry_vs_lifecycle_explanatory_power.csv", index=False)

    label, detail = verdict(comparisons, broad_rows)
    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_REALISTIC_P2_WINNER_LOSER_LIFECYCLE_V01",
        "strategy_id": STRATEGY_ID,
        "scope": "CONTROL only; certified realistic P2-1/P2-2 run artifacts; no backtest, strategy re-evaluation, Candidate, threshold/survivor change, feature recomputation, or network",
        "runs": {w: {"run_dir": str(RUNS[w]["run_dir"].relative_to(ROOT)), "status": RUNS[w]["status"], "source_sha256": source_hashes[w]} for w in WINDOWS},
        "headline_gate": gates,
        "layers": {"ELIGIBLE": "control_strategy_trades.csv (survivor-only, exact PIT MKTCAP >= 1T)", "FILLED": "ENTRY/EXECUTED in control_portfolio_events.csv"},
        "return_definitions": {
            "primary": "ledger terminal_return (same contract as the broad study; OPEN_AT_CUTOFF marked to cutoff)",
            "secondary": "net realized return for filled closed trades = (exit notional - commission - tax) / (entry notional + commission) - 1; used for the headline gate and FILLED profile columns only",
        },
        "feature_cache_join": join_audit,
        "future_leakage": "entry features come from the parent PIT enrichment (0 stage/fast_score mismatches, truncated-daily leakage check 0 mismatches); every joined row re-verified against realistic ledger fast_score and Pattern A stage",
        "broad_class_rules": BROAD_CLASS_RULES,
        "verdict_rules": VERDICT_RULES,
        "verdict": label,
        "verdict_detail": detail,
        "path_check": paths,
        "entry_vs_lifecycle_explanatory_power": explain,
        "network_requests": network_audit["count"],
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": label, "panels": {k: {kk: vv for kk, vv in v.items() if kk != "classifications"} for k, v in detail["panels"].items()}}, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    audit = {"count": 0}
    with wl.network_guard(audit):
        run(audit)
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
