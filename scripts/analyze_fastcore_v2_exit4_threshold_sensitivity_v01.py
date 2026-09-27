"""A FAST Core V2 — Exit4 score drawdown threshold sensitivity V01 (T10 / T15 / T20 / T25).

Exit4의 존재는 유지하고 `HWM - score >= threshold`의 threshold만 10 / 15(CONTROL) / 20 / 25pt로 바꾼 거래 단위
반사실을 계산한다. 나머지 V2 규칙(Loss Guard, Exit3, coverage 감시 종료, 다음 거래일 시가 체결, cutoff 평가)은
인증 러너가 호출하는 `pattern_a_fast_core_v02_reentry.simulate_ticker_core_v02_reentry`와 같다.

- threshold는 E2(Exit3 / Exit4 / coverage)에만 영향을 준다. Loss Guard로 끝난 거래와 PROGRESSED에 닿지 않은
  거래는 네 시나리오에서 같다.
- T15는 원장과 청산 유형·신호·체결가·terminal·MFE·MAE가 같아야 한다(parity 게이트, 불일치 행은 제외).
- 다른 threshold는 정의상 실제 청산 이후의 가격·stage를 쓸 수 있지만 윈도우 cutoff(실행 지원일)를 넘지 않는다.
- 포트폴리오 재생·자본 재배치는 계산하지 않는다. 최적값을 고르지 않으며 판정 규칙은 코드에 고정했다.

사용법:
    python scripts/analyze_fastcore_v2_exit4_threshold_sensitivity_v01.py
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

import scripts.analyze_fastcore_v2_exit4_effectiveness_v01 as e4  # noqa: E402
import scripts.analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01 as lc  # noqa: E402
import scripts.analyze_fastcore_v2_winner_loser_profile_v01 as wl  # noqa: E402

OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/exit4_threshold_sensitivity_v01"
THRESHOLDS = [10.0, 15.0, 20.0, 25.0]
CONTROL_T = 15.0
ALTERNATIVES = [10.0, 20.0, 25.0]
EXIT4 = e4.EXIT4
PARITY_TOLERANCE = 0.011
# 판정 규칙(결과 확인 전에 고정)
VERDICT_RULES = {
    "core_metrics": ["median_return (higher)", "mean_excl_top5 (higher)", "ge_50 count (higher)", "ge_100 count (higher)", "le_neg_30 count (lower)"],
    "panel_better": ">= 4 of 5 core metrics strictly better than T15 AND median_return >= T15 + 2.0pp",
    "ALTERNATIVE_THRESHOLD_PROMISING": "exactly one alternative is panel_better in the pooled panel, in >= 4 of 5 simple windows and in >= 2 of 3 realistic eligible panels",
    "T15_ROBUST": "no alternative is panel_better in the pooled panel and each alternative is panel_better in <= 1 simple window",
    "MIXED_NO_CLEAR_WINNER": "otherwise",
    "INSUFFICIENT_EVIDENCE": "pooled affected trades < 20",
    "median_margin_pp": 2.0,
}


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------

def replicate_exit_path(entry_stage: str, post: list[tuple[pd.Timestamp, str, float | None]], threshold: float) -> dict[str, Any]:
    """`e4.replicate_exit_path`와 같은 E2 규칙에서 Exit4 threshold만 바꾼다."""
    lifecycle, first_progressed = lc.replicate_ledger_lifecycle(entry_stage, [(m, s) for m, s, _ in post])
    handoff, prev = None, entry_stage
    for m, s, _ in post:
        if s in lc.VALID_SKIP:
            continue
        if s == "PROGRESSED" and prev == "EARLY_TREND":
            handoff = m
            break
        prev = s
    out = {"lifecycle": lifecycle, "exit_type": None, "signal_label": None, "hwm_at_signal": None, "score_at_signal": None,
           "arm_label": handoff if lifecycle == "NORMAL_EARLY_TREND_HANDOFF" else first_progressed}
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
                    if hwm - sc >= threshold:
                        out.update(exit_type=EXIT4, signal_label=m, hwm_at_signal=hwm, score_at_signal=sc)
                        return out
            elif s in e4.EXIT3_TARGETS:
                out.update(exit_type=f"EXIT3_PROGRESSED_TO_{s}", signal_label=m, hwm_at_signal=hwm, score_at_signal=sc)
                return out
        out["exit_type"] = "NO_EXIT_BEFORE_CUTOFF"
        return out
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
                    if hwm - sc >= threshold:
                        out.update(exit_type=EXIT4, signal_label=m, hwm_at_signal=hwm, score_at_signal=sc)
                        return out
            else:
                break
        out["exit_type"] = "NO_EXIT_BEFORE_CUTOFF"
        return out
    out["exit_type"] = "NO_PROGRESSED_BEFORE_CUTOFF"
    return out


def outcome(daily: pd.DataFrame, entry_date: pd.Timestamp, entry_open: float, signal_label: pd.Timestamp | None,
            valuation_end: pd.Timestamp, support: pd.Timestamp) -> dict[str, Any]:
    """러너 `_calc_trade_outcome` + `_refresh_outcome_metrics`와 같은 방식의 terminal / MFE / MAE / 보유일."""
    exit_date = exit_open = None
    if signal_label is not None:
        later = daily[(daily.index > signal_label) & (daily.index <= support)]
        if not later.empty:
            exit_date, exit_open = pd.Timestamp(later.index[0]), float(later.iloc[0]["open"])
    if exit_date is not None:
        held = daily[(daily.index >= entry_date) & (daily.index < exit_date)]
        highs, lows = held["high"].tolist() + [exit_open], held["low"].tolist() + [exit_open]
        terminal = exit_open
        holding_days = int(len(daily[(daily.index >= entry_date) & (daily.index <= exit_date)]))
    else:
        held = daily[(daily.index >= entry_date) & (daily.index <= valuation_end)]
        highs = held["high"].tolist() or [entry_open]
        lows = held["low"].tolist() or [entry_open]
        terminal = float(held.iloc[-1]["close"]) if len(held) else entry_open
        holding_days = int(len(held))
    ret = round((terminal - entry_open) / entry_open * 100.0, 2)
    mfe = round((max(highs) / entry_open - 1.0) * 100.0, 2)
    return {"exit_date": exit_date, "exit_open": exit_open, "terminal_return": ret, "mfe": mfe,
            "mae": round((min(lows) / entry_open - 1.0) * 100.0, 2), "giveback": round(mfe - ret, 2), "holding_days": holding_days}


def stats(frame: pd.DataFrame, col: str = "terminal_return") -> dict[str, Any]:
    v = pd.to_numeric(frame[col], errors="coerce").dropna()
    if v.empty:
        return {"n": 0}
    ordered = v.sort_values(ascending=False)
    return {"n": int(len(v)), "mean": wl._round(v.mean()), "median": wl._round(v.median()),
            "mean_excl_top1": wl._round(ordered.iloc[1:].mean()) if len(v) > 1 else None,
            "mean_excl_top5": wl._round(ordered.iloc[5:].mean()) if len(v) > 5 else None,
            "ge_50": int((v >= 50).sum()), "ge_100": int((v >= 100).sum()),
            **{f"le_neg_{t}": int((v <= -t).sum()) for t in (15, 30, 50, 60)}}


def panel_better(alt: dict[str, Any], control: dict[str, Any]) -> tuple[bool, int, int]:
    wins = losses = 0
    for metric, higher in (("median", True), ("mean_excl_top5", True), ("ge_50", True), ("ge_100", True), ("le_neg_30", False)):
        a, c = alt.get(metric), control.get(metric)
        if a is None or c is None:
            continue
        if (a > c) if higher else (a < c):
            wins += 1
        elif (a < c) if higher else (a > c):
            losses += 1
    better = wins >= 4 and alt.get("median") is not None and alt["median"] >= control["median"] + VERDICT_RULES["median_margin_pp"]
    return bool(better), wins, losses


def verdict(panel_flags: dict[float, dict[str, bool]], pooled_n: int) -> tuple[str, dict[str, Any]]:
    if pooled_n < 20:
        return "INSUFFICIENT_EVIDENCE", {}
    detail = {}
    promising = []
    for t, flags in panel_flags.items():
        simple = sum(v for k, v in flags.items() if k.startswith("SIMPLE_P") and k != "SIMPLE_POOLED_DEDUP")
        realistic = sum(v for k, v in flags.items() if k.startswith("REALISTIC") and k.endswith("ELIGIBLE"))
        pooled = flags.get("SIMPLE_POOLED_DEDUP", False)
        detail[f"T{int(t)}"] = {"pooled_better": pooled, "simple_windows_better": simple, "realistic_eligible_better": realistic}
        if pooled and simple >= 4 and realistic >= 2:
            promising.append(t)
    if len(promising) == 1:
        return "ALTERNATIVE_THRESHOLD_PROMISING", {**detail, "candidate": f"T{int(promising[0])}"}
    if all(not d["pooled_better"] and d["simple_windows_better"] <= 1 for d in detail.values()):
        return "T15_ROBUST", detail
    return "MIXED_NO_CLEAR_WINNER", detail


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def build(repo: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    stages = lc.load_stage_cache()
    panels_all, count_gates = lc.build_panels(stages)
    gate_table, panels = lc.replication_gate(panels_all)
    daily_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    rows, parity_rows = [], []
    for panel, frame in panels.items():
        counts = {"panel": panel, "panel_trades": int(len(frame)), "affected": 0, "t15_parity_ok": 0, "t15_parity_fail": 0}
        for index, row in frame.iterrows():
            if str(row["exit_type"]) == e4.LOSS_GUARD or row["trade_status"] == "LIFECYCLE_SETTLED":
                continue
            cutoff = e4.cutoff_of(panel, row)
            key = (row["ticker"], row["isu_cd"], row["identity_effective_from"])
            cache = stages[key]
            signal = pd.Timestamp(row["entry_signal_date"])
            post_frame = cache[(cache["label"] >= signal) & (cache["label"] <= cutoff)]
            post = [(m, s, (None if pd.isna(sc) else float(sc))) for m, s, sc in zip(post_frame["label"], post_frame["stage"], post_frame["score"])]
            base = replicate_exit_path(str(row["entry_pattern_a_stage"]).upper(), post, CONTROL_T)
            if base["lifecycle"] == "NEVER_PROGRESSED":
                continue
            counts["affected"] += 1
            if key not in daily_cache:
                daily_cache[key] = repo.get_daily(key[0], key[2], lc.DATA_SUPPORT_END).sort_index()
            daily = daily_cache[key]
            support = pd.Timestamp(e4.SUPPORT_BY_CUTOFF[cutoff.strftime("%Y-%m-%d")])
            entry_date, entry_open = pd.Timestamp(row["entry_execution_date"]), float(row["entry_open"])
            record: dict[str, Any] = {"panel": panel, "row_index": index, "ticker": row["ticker"], "trade_id": row["trade_id"],
                                      "entry_signal_date": row["entry_signal_date"], "market": row["market"],
                                      "exit_path": "NORMAL" if base["lifecycle"] == "NORMAL_EARLY_TREND_HANDOFF" else "COVERAGE",
                                      "ledger_exit_type": row["exit_type"], "ledger_terminal_return": float(row["terminal_return"]),
                                      "filled": row.get("filled")}
            ok = True
            for t in THRESHOLDS:
                path = base if t == CONTROL_T else replicate_exit_path(str(row["entry_pattern_a_stage"]).upper(), post, t)
                result = outcome(daily, entry_date, entry_open, path["signal_label"], cutoff, support)
                tag = f"t{int(t)}"
                record.update({
                    f"{tag}_exit_type": path["exit_type"],
                    f"{tag}_signal_label": path["signal_label"].strftime("%Y-%m-%d") if path["signal_label"] is not None else None,
                    f"{tag}_score_drop_at_signal": wl._round(path["hwm_at_signal"] - path["score_at_signal"])
                    if path["exit_type"] == EXIT4 else None,
                    f"{tag}_exit_date": result["exit_date"].strftime("%Y-%m-%d") if result["exit_date"] is not None else None,
                    f"{tag}_exit_price": result["exit_open"], f"{tag}_terminal_return": result["terminal_return"],
                    f"{tag}_mfe": result["mfe"], f"{tag}_mae": result["mae"], f"{tag}_giveback": result["giveback"],
                    f"{tag}_holding_days": result["holding_days"],
                    f"{tag}_days_entry_to_signal": int(((daily.index >= entry_date) & (daily.index <= path["signal_label"])).sum())
                    if path["signal_label"] is not None else None,
                })
                if t == CONTROL_T:
                    ledger_exit = row.get("exit_execution_date")
                    ok = (path["exit_type"] == row["exit_type"]
                          and abs(result["terminal_return"] - float(row["terminal_return"])) <= PARITY_TOLERANCE
                          and abs(result["mfe"] - float(row["mfe"])) <= PARITY_TOLERANCE
                          and abs(result["mae"] - float(row["mae"])) <= PARITY_TOLERANCE
                          and ((result["exit_date"] is None and not isinstance(ledger_exit, str))
                               or (result["exit_date"] is not None and isinstance(ledger_exit, str) and result["exit_date"] == pd.Timestamp(ledger_exit)
                                   and abs(result["exit_open"] - float(row["exit_price"])) <= PARITY_TOLERANCE)))
            counts["t15_parity_ok" if ok else "t15_parity_fail"] += 1
            if ok:
                rows.append(record)
        parity_rows.append(counts)
    parity = pd.DataFrame(parity_rows)
    parity["t15_parity_pct"] = (parity["t15_parity_ok"] / parity["affected"] * 100.0).round(3)
    return pd.DataFrame(rows), parity, panels, {"count_gates": count_gates, "replication_gate": gate_table.drop(columns=["mismatch_examples"]).to_dict("records")}


def summarize(trades: pd.DataFrame, panels: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    threshold_rows, window_rows, change_rows, extreme_rows = [], [], [], []
    for panel, part in trades.groupby("panel", sort=False):
        control_stats = None
        for t in THRESHOLDS:
            tag = f"t{int(t)}"
            frame = part.rename(columns={f"{tag}_terminal_return": "ret"})
            s = stats(frame, "ret")
            drop = pd.to_numeric(part[f"{tag}_score_drop_at_signal"], errors="coerce").dropna()
            row = {
                "panel": panel, "threshold": f"T{int(t)}", **s,
                "exit4_n": int((part[f"{tag}_exit_type"] == EXIT4).sum()),
                "exit3_n": int(part[f"{tag}_exit_type"].astype(str).str.startswith("EXIT3").sum()),
                "no_exit_n": int((part[f"{tag}_exit_type"] == "NO_EXIT_BEFORE_CUTOFF").sum()),
                "mfe_median": wl._round(part[f"{tag}_mfe"].median()), "mae_median": wl._round(part[f"{tag}_mae"].median()),
                "giveback_median": wl._round(part[f"{tag}_giveback"].median()), "giveback_mean": wl._round(part[f"{tag}_giveback"].mean()),
                "holding_days_median": wl._round(part[f"{tag}_holding_days"].median()), "holding_days_mean": wl._round(part[f"{tag}_holding_days"].mean()),
                "days_entry_to_exit4_signal_median": wl._round(part.loc[part[f"{tag}_exit_type"] == EXIT4, f"{tag}_days_entry_to_signal"].median()),
                "score_drop_median": wl._round(drop.median()) if len(drop) else None,
                "score_drop_q25": wl._round(drop.quantile(0.25)) if len(drop) else None,
                "score_drop_q75": wl._round(drop.quantile(0.75)) if len(drop) else None,
            }
            if t == CONTROL_T:
                control_stats = s
            threshold_rows.append(row)
        for t in ALTERNATIVES:
            tag = f"t{int(t)}"
            alt_s = stats(part.rename(columns={f"{tag}_terminal_return": "ret"}), "ret")
            better, wins, losses = panel_better(alt_s, control_stats)
            diff = part[f"{tag}_terminal_return"] - part["t15_terminal_return"]
            c, a = part["t15_terminal_return"], part[f"{tag}_terminal_return"]
            earlier = (part[f"{tag}_holding_days"] < part["t15_holding_days"]).sum()
            later = (part[f"{tag}_holding_days"] > part["t15_holding_days"]).sum()
            ordered = diff.sort_values()
            change_rows.append({
                "panel": panel, "alternative": f"T{int(t)}", "affected_n": int(len(part)),
                "exited_earlier": int(earlier), "exited_later": int(later), "same_exit": int(len(part) - earlier - later),
                "return_improved": int((diff > 0).sum()), "return_worsened": int((diff < 0).sum()),
                "win50_gained": int(((a >= 50) & (c < 50)).sum()), "win50_lost": int(((c >= 50) & (a < 50)).sum()),
                "win100_gained": int(((a >= 100) & (c < 100)).sum()), "win100_lost": int(((c >= 100) & (a < 100)).sum()),
                "loss30_added": int(((a <= -30) & (c > -30)).sum()), "loss30_removed": int(((c <= -30) & (a > -30)).sum()),
                "loss50_added": int(((a <= -50) & (c > -50)).sum()), "loss50_removed": int(((c <= -50) & (a > -50)).sum()),
                "median_diff_pp": wl._round(diff.median()), "mean_diff_pp": wl._round(diff.mean()),
                "median_return_alt_minus_t15_pp": wl._round(a.median() - c.median()),
                "giveback_median_alt_minus_t15": wl._round(part[f"{tag}_giveback"].median() - part["t15_giveback"].median()),
                "holding_days_mean_alt_minus_t15": wl._round(part[f"{tag}_holding_days"].mean() - part["t15_holding_days"].mean()),
                "worst_trade_diff_pp": wl._round(ordered.iloc[0]), "best_trade_diff_pp": wl._round(ordered.iloc[-1]),
                "core_metric_wins": wins, "core_metric_losses": losses, "panel_better": better,
                "tier": "EVALUABLE" if len(part) >= 20 else ("DESCRIPTIVE" if len(part) >= 10 else "INSUFFICIENT_EVIDENCE"),
            })
        for t in THRESHOLDS:
            s = stats(part.rename(columns={f"t{int(t)}_terminal_return": "ret"}), "ret")
            extreme_rows.append({"panel": panel, "threshold": f"T{int(t)}", "mean_all": s.get("mean"),
                                 "mean_excl_top1": s.get("mean_excl_top1"), "mean_excl_top5": s.get("mean_excl_top5"), "median": s.get("median")})
        # 패널 전체(영향 없는 거래 포함) 기준 평균·중앙
        full = panels[panel]
        base_returns = full["terminal_return"].astype(float)
        for t in THRESHOLDS:
            replaced = base_returns.copy()
            replaced.loc[part["row_index"].values] = part[f"t{int(t)}_terminal_return"].values
            window_rows.append({"panel": panel, "threshold": f"T{int(t)}", "panel_trades": int(len(full)), "affected_n": int(len(part)),
                                "panel_mean": wl._round(replaced.mean()), "panel_median": wl._round(replaced.median()),
                                "panel_ge_50": int((replaced >= 50).sum()), "panel_ge_100": int((replaced >= 100).sum()),
                                "panel_le_neg_30": int((replaced <= -30).sum()), "panel_le_neg_50": int((replaced <= -50).sum()),
                                "affected_median": wl._round(part[f"t{int(t)}_terminal_return"].median()),
                                "affected_giveback_median": wl._round(part[f"t{int(t)}_giveback"].median())})
    return {"threshold": pd.DataFrame(threshold_rows), "window": pd.DataFrame(window_rows),
            "change": pd.DataFrame(change_rows), "extreme": pd.DataFrame(extreme_rows)}


def run() -> None:
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    repo = build_production_repository_v2(ROOT, end=lc.REPOSITORY_END)
    trades, parity, panels, gates = build(repo)
    low = parity[parity["t15_parity_pct"] < 99.0]
    if len(low):
        print(parity.to_string(index=False))
        raise RuntimeError("T15_PARITY_GATE_FAILED")
    if trades.duplicated(["panel", "ticker", "trade_id", "entry_signal_date"]).any():
        raise RuntimeError("TRADE_IDENTITY_DUPLICATE")
    exit4_ref = pd.read_csv(ROOT / "artifacts/patterns/pattern_a_fast/research/exit4_effectiveness_v01/exit4_trade_profile.csv", dtype={"ticker": str})
    exit4_ref["ticker"] = exit4_ref["ticker"].str.zfill(6)
    mine = trades[trades["t15_exit_type"] == EXIT4][["panel", "ticker", "trade_id", "entry_signal_date", "t15_signal_label", "t15_exit_date"]]
    joined = mine.merge(exit4_ref[["panel", "ticker", "trade_id", "entry_signal_date", "exit4_signal_label", "exit4_execution_date"]],
                        on=["panel", "ticker", "trade_id", "entry_signal_date"], how="outer", indicator=True)
    exit4_cross = {"t15_exit4_trades": int(len(mine)), "exit4_analysis_trades": int(len(exit4_ref)),
                   "both": int((joined["_merge"] == "both").sum()),
                   "signal_and_execution_equal": int(((joined["t15_signal_label"] == joined["exit4_signal_label"])
                                                      & (joined["t15_exit_date"] == joined["exit4_execution_date"])).sum())}
    trades.drop(columns=["row_index"]).to_csv(OUTPUT_DIR / "trade_level_comparison.csv", index=False)
    tables = summarize(trades, panels)
    tables["threshold"].to_csv(OUTPUT_DIR / "threshold_summary.csv", index=False)
    tables["window"].to_csv(OUTPUT_DIR / "window_summary.csv", index=False)
    tables["change"].to_csv(OUTPUT_DIR / "winner_tail_impact.csv", index=False)
    tables["extreme"].to_csv(OUTPUT_DIR / "extreme_winner_sensitivity.csv", index=False)
    parity.to_csv(OUTPUT_DIR / "t15_parity.csv", index=False)
    flags = {t: dict(zip(g["panel"], g["panel_better"])) for t, g in
             ((float(a[1:]), grp) for a, grp in tables["change"].groupby("alternative"))}
    pooled_n = int(len(trades[trades["panel"] == "SIMPLE_POOLED_DEDUP"]))
    label, detail = verdict(flags, pooled_n)
    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_EXIT4_THRESHOLD_SENSITIVITY_V01",
        "strategy_id": lc.STRATEGY_ID,
        "scope": "CONTROL only; archived certified ledgers; trade-level counterfactual only (no portfolio replay, no capital redeployment); thresholds fixed to 10/15/20/25pt",
        "thresholds_pt": THRESHOLDS, "control_threshold_pt": CONTROL_T,
        "rules_kept": "Loss Guard (pre-first-PROGRESSED), Exit3 on NORMAL path, coverage monitoring end on any non-PROGRESSED label, next-session-open execution, window-cutoff close valuation",
        "affected_universe": "trades not closed by the Loss Guard and whose window path reaches PROGRESSED; all other trades are identical across thresholds",
        "data_boundary": "alternative thresholds may hold beyond the actual exit by construction; no data beyond the window cutoff / execution support day is used",
        "gates": {**gates, "t15_parity": parity.to_dict("records"), "t15_vs_exit4_effectiveness": exit4_cross},
        "verdict_rules": VERDICT_RULES,
        "verdict": label, "verdict_detail": detail,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(parity.to_string(index=False))
    print(json.dumps({"verdict": label, "detail": detail, "exit4_cross": exit4_cross}, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    audit = {"count": 0}
    with wl.network_guard(audit):
        run()
    if audit["count"]:
        raise RuntimeError(f"NETWORK_REQUESTS_ATTEMPTED:{audit['count']}")


if __name__ == "__main__":
    main()
