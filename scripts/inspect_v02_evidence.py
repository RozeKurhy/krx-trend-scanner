"""Deterministic evidence inspection and artifact generation for Pattern A FAST Core V02 Re-Entry."""

import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

V01_CSV = ROOT / "artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/pattern_a_fast_strategy_finalization_v01_trades.csv"
V02_CSV = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
V02_TICKER_CSV = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/ticker_summary.csv"
V02_DIR = ROOT / "artifacts/pattern_a_fast/core_v02_reentry"


def generate_identity_and_deep_loss_artifacts():
    v01_df = pd.read_csv(V01_CSV, dtype={"ticker": str})
    v02_df = pd.read_csv(V02_CSV, dtype={"ticker": str})
    v02_ticker_df = pd.read_csv(V02_TICKER_CSV, dtype={"ticker": str})

    v01_df["ticker"] = v01_df["ticker"].str.zfill(6)
    v02_df["ticker"] = v02_df["ticker"].str.zfill(6)
    v02_ticker_df["ticker"] = v02_ticker_df["ticker"].str.zfill(6)

    # 1. Identity Check
    v02_seq1 = v02_df[v02_df["trade_sequence"] == 1].sort_values(by="ticker").reset_index(drop=True)
    v01_sorted = v01_df.sort_values(by="ticker").reset_index(drop=True)

    fields_to_compare = [
        ("entry_signal_date", "entry_signal_date"),
        ("entry_execution_date", "entry_execution_date"),
        ("entry_open", "entry_open"),
        ("entry_pattern_a_stage", "entry_pattern_a_stage"),
        ("fast_monthly_regime_at_entry", "monthly_regime"),
        ("daily_risk_at_entry", "daily_risk"),
        ("fast_score_availability", "fast_score_state"),
        ("loss_guard_triggered", "loss_guard_triggered"),
        ("loss_guard_signal_date", "loss_guard_signal_date"),
        ("loss_guard_exec_date", "loss_guard_execution_date"),
        ("lifecycle_class", "lifecycle_class"),
        ("first_progressed_date", "first_progressed_date"),
        ("first_progressed_effective_trading_date", "first_progressed_effective_trading_date"),
        ("hold_b_e2_exit_type", "exit_type"),
        ("hold_b_e2_terminal_return", "terminal_return"),
        ("hold_b_e2_mfe", "mfe"),
        ("hold_b_e2_mae", "mae"),
        ("hold_b_e2_peak_giveback", "peak_giveback"),
        ("hold_b_e2_holding_weeks", "holding_weeks"),
    ]

    mismatches = []
    for i in range(len(v01_sorted)):
        r1 = v01_sorted.iloc[i]
        r2 = v02_seq1.iloc[i]
        t1 = r1["ticker"]
        t2 = r2["ticker"]
        if t1 != t2:
            mismatches.append({"ticker": t1, "field": "ticker", "v01": t1, "v02": t2})
            continue
        for f1, f2 in fields_to_compare:
            v1 = r1[f1]
            v2 = r2[f2]
            if pd.isna(v1) and pd.isna(v2):
                continue
            if isinstance(v1, (int, float, np.number)) and isinstance(v2, (int, float, np.number)):
                if not np.isclose(float(v1), float(v2), atol=1e-2):
                    mismatches.append({"ticker": t1, "field": f"{f1}!={f2}", "v01": float(v1), "v02": float(v2)})
            else:
                if str(v1) != str(v2):
                    mismatches.append({"ticker": t1, "field": f"{f1}!={f2}", "v01": str(v1), "v02": str(v2)})

    identity_check_data = {
        "v01_trade_count": len(v01_df),
        "v02_sequence1_count": len(v02_seq1),
        "matched_count": len(v01_sorted) - len(mismatches),
        "mismatch_count": len(mismatches),
        "mismatch_details": mismatches,
        "identity_verified": len(mismatches) == 0,
    }

    out_ident = V02_DIR / "artifact_identity_check.json"
    out_ident.write_text(json.dumps(identity_check_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved identity check to {out_ident} (Mismatch Count: {len(mismatches)})")

    # 2. Deep Loss Re-entry Cases (<= -20%)
    df_reentry = v02_df[v02_df["trade_sequence"] >= 2]
    df_le_neg20 = df_reentry[df_reentry["terminal_return"] <= -20.0].sort_values(by="terminal_return").copy()

    out_csv = V02_DIR / "deep_loss_reentry_cases.csv"
    df_le_neg20.to_csv(out_csv, index=False)
    print(f"Saved {len(df_le_neg20)} deep loss reentry cases to {out_csv}")

    # Generate Markdown deep loss report
    df_le_neg30 = df_le_neg20[df_le_neg20["terminal_return"] <= -30.0].copy()

    md_lines = [
        "# Pattern A FAST Core V02 Re-Entry Deep Loss Tail Analysis",
        "",
        "================================================================================",
        "1. Executive Overview",
        "================================================================================",
        f"- Total Re-Entry Trades: **{len(df_reentry)}건**",
        f"- Return <= -20% Trades: **{len(df_le_neg20)}건 ({len(df_le_neg20)/len(df_reentry)*100:.2f}%)**",
        f"- Return <= -30% Trades: **{len(df_le_neg30)}건 ({len(df_le_neg30)/len(df_reentry)*100:.2f}%)**",
        "",
        "================================================================================",
        "2. Re-Entry <= -30% Extreme Loss Cases (4건 전수 상세)",
        "================================================================================",
        "",
    ]

    for _, r in df_le_neg30.iterrows():
        t = r["ticker"]
        name = r["name"]
        t_id = r["trade_id"]
        seq = r["trade_sequence"]
        prev_exit = r["previous_exit_type"]
        prev_exec = r["previous_exit_execution_date"]
        e_sig = r["entry_signal_date"]
        e_exec = r["entry_execution_date"]
        e_open = r["entry_open"]
        e_stage = r["entry_pattern_a_stage"]
        risk = r["daily_risk"]
        f_state = r["fast_score_state"]
        life = r["lifecycle_class"]
        f_prog = r["first_progressed_date"]
        f_prog_eff = r["first_progressed_effective_trading_date"]
        lg_trig = r["loss_guard_triggered"]
        exit_t = r["exit_type"]
        exit_exec = r["exit_execution_date"]
        t_ret = r["terminal_return"]
        mfe = r["mfe"]
        mae = r["mae"]
        gb = r["peak_giveback"]
        hw = r["holding_weeks"]
        status = r["trade_status"]

        if t == "011170":
            cause = "F. OPEN_AT_CUTOFF structural tail & D. PROGRESSED coverage hole"
            desc = "SKIPPED_EARLY_TREND_HANDOFF에서 PROGRESSED 도달 후 Exit4 15pt 하락 조건이 미충족되어 cutoff까지 미청산 보유된 구조적 테일 케이스 (Gap Loss 아님)"
        elif t == "000670":
            cause = "C. Post-PROGRESSED monthly lag decline / Exit3 lag"
            desc = "2026-02-27 PROGRESSED 도달로 Loss Guard 비활성화된 후 월봉 국면이 WEAK로 전환될 때까지 지연되어 -45.64% 손실 기록"
        elif t == "200670":
            cause = "E. Exit3 lag after MFE surge"
            desc = "MFE +42.70% 급등 후 되돌림 과정에서 월봉 WEAK 전환 지연으로 -36.51% 손실 기록"
        elif t == "298380":
            cause = "A. Gap Execution Tail / Sharp Monthly Drawdown"
            desc = "급격한 월간 가격 하락으로 Score HWM 15pt drawdown 청산 시 -31.34% 기록"
        else:
            cause = "G. Other"
            desc = "-"

        md_lines.extend([
            f"### [{t_id}] {name} ({t}) - Sequence {seq}",
            f"- **Previous Exit**: `{prev_exit}` (Exec Date: `{prev_exec}`)",
            f"- **Entry**: Signal `{e_sig}` -> Execution `{e_exec}` (Open: `{e_open:,.0f}`원)",
            f"- **Entry Context**: Stage `{e_stage}`, Daily Risk `{risk}`, Score State `{f_state}`",
            f"- **Lifecycle**: `{life}` (First PROGRESSED: `{f_prog}`, Effective: `{f_prog_eff}`)",
            f"- **Loss Guard Triggered**: `{lg_trig}`",
            f"- **Exit Outcome**: Type `{exit_t}`, Exec Date `{exit_exec}`, Status `{status}`",
            f"- **Performance**: **Terminal `{t_ret}%`**, MFE `+{mfe}%`, MAE `{mae}%`, Giveback `{gb}%`, Holding `{hw}`주",
            f"- **원인 분류 (`Cause Classification`)**: **`{cause}`**",
            f"- **상세 원인 분석**: {desc}",
            "",
        ])

    md_lines.extend([
        "================================================================================",
        "3. Re-Entry <= -20% Summary Statistics (14건 종합)",
        "================================================================================",
        "",
        "| Ticker | 종목명 | Trade ID | Seq | Previous Exit | Lifecycle | Exit Type | Status | Return | MAE | MFE |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])

    for _, r in df_le_neg20.iterrows():
        md_lines.append(
            f"| `{r['ticker']}` | {r['name']} | `{r['trade_id']}` | {r['trade_sequence']} | `{r['previous_exit_type']}` | `{r['lifecycle_class']}` | `{r['exit_type']}` | `{r['trade_status']}` | **{r['terminal_return']}%** | {r['mae']}% | +{r['mfe']}% |"
        )

    out_md = V02_DIR / "deep_loss_reentry_cases.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Saved deep loss report to {out_md}")


if __name__ == "__main__":
    generate_identity_and_deep_loss_artifacts()
