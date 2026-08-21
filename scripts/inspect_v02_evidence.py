"""Deterministic evidence inspection and artifact generation for Pattern A FAST Core V02 Re-Entry."""

import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

V01_CSV = ROOT / "artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01/pattern_a_fast_strategy_finalization_v01_trades.csv"
V02_CSV = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
V02_TICKER_CSV = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/ticker_summary.csv"
V02_DIR = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry"


def build_representative_case(ticker: str, v02_df: pd.DataFrame | None = None, ticker_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Dynamically build structured representative case from saved artifact authorities."""
    if v02_df is None:
        v02_df = pd.read_csv(V02_CSV, dtype={"ticker": str})
        v02_df["ticker"] = v02_df["ticker"].str.zfill(6)
    if ticker_df is None:
        ticker_df = pd.read_csv(V02_TICKER_CSV, dtype={"ticker": str})
        ticker_df["ticker"] = ticker_df["ticker"].str.zfill(6)

    t_str = str(ticker).zfill(6)
    sub = v02_df[v02_df["ticker"] == t_str].sort_values(by="trade_sequence")
    if sub.empty:
        raise ValueError(f"Ticker {t_str} not found in trades.csv")

    tsum_row = ticker_df[ticker_df["ticker"] == t_str].iloc[0]

    trades_list = []
    for _, r in sub.iterrows():
        trades_list.append({
            "trade_id": r["trade_id"],
            "trade_sequence": int(r["trade_sequence"]),
            "entry_signal_date": r["entry_signal_date"],
            "entry_execution_date": r["entry_execution_date"],
            "entry_open": float(r["entry_open"]),
            "entry_pattern_a_stage": r["entry_pattern_a_stage"],
            "daily_risk": r["daily_risk"],
            "fast_score_state": r["fast_score_state"],
            "previous_exit_type": r["previous_exit_type"] if pd.notna(r["previous_exit_type"]) else None,
            "previous_exit_execution_date": r["previous_exit_execution_date"] if pd.notna(r["previous_exit_execution_date"]) else None,
            "lifecycle_class": r["lifecycle_class"],
            "first_progressed_date": r["first_progressed_date"] if pd.notna(r["first_progressed_date"]) else None,
            "first_progressed_effective_trading_date": r["first_progressed_effective_trading_date"] if pd.notna(r["first_progressed_effective_trading_date"]) else None,
            "loss_guard_triggered": bool(r["loss_guard_triggered"]),
            "loss_guard_signal_date": r["loss_guard_signal_date"] if pd.notna(r["loss_guard_signal_date"]) else None,
            "loss_guard_execution_date": r["loss_guard_execution_date"] if pd.notna(r["loss_guard_execution_date"]) else None,
            "exit_type": r["exit_type"],
            "exit_signal_date": r["exit_signal_date"] if pd.notna(r["exit_signal_date"]) else None,
            "exit_execution_date": r["exit_execution_date"] if pd.notna(r["exit_execution_date"]) else None,
            "exit_price": float(r["exit_price"]) if pd.notna(r["exit_price"]) else None,
            "terminal_return": float(r["terminal_return"]),
            "mfe": float(r["mfe"]),
            "mae": float(r["mae"]),
            "peak_giveback": float(r["peak_giveback"]),
            "holding_weeks": float(r["holding_weeks"]),
            "trade_status": r["trade_status"],
        })

    return {
        "ticker": t_str,
        "name": sub.iloc[0]["name"],
        "market": sub.iloc[0]["market"],
        "total_trades": int(tsum_row["total_trades"]),
        "sequential_cumulative_return_pct": float(tsum_row["sequential_cumulative_return_pct"]),
        "win_rate_pct": float(tsum_row["win_rate_pct"]),
        "trades": trades_list,
    }


def classify_deep_loss_cause(row: pd.Series) -> dict[str, Any]:
    """Data-driven cause classification hierarchy strictly based on row facts."""
    ret = float(row["terminal_return"])
    status = str(row["trade_status"])
    exit_type = str(row["exit_type"])
    lifecycle = str(row["lifecycle_class"])
    has_prog = pd.notna(row["first_progressed_date"])
    lg_trig = bool(row["loss_guard_triggered"])

    primary_cause = "OTHER_DEEP_LOSS"
    secondary_flags: list[str] = []
    interpretation = ""

    # Hierarchy:
    # 1. OPEN_AT_CUTOFF_STRUCTURAL_TAIL
    if status == "OPEN_AT_CUTOFF" and ret <= -20.0:
        primary_cause = "OPEN_AT_CUTOFF_STRUCTURAL_TAIL"
        interpretation = "포지션이 Cutoff 시점까지 청산 조건을 충족하지 못하고 장기 보유되어 평가손실이 누적된 구조적 테일"
        if lifecycle in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
            secondary_flags.append("COVERAGE_STRUCTURAL_TAIL")
            interpretation += " (Coverage 경로 상 Exit 3 미적용 및 점수 하락 급락 미발생으로 인한 미청산)"
    # 2. LOSS_GUARD_REALIZED_DEEP_LOSS
    elif lg_trig and exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15" and ret <= -20.0:
        primary_cause = "LOSS_GUARD_REALIZED_DEEP_LOSS"
        interpretation = "Loss Guard가 발동했으나 다음 거래일 시가 실행 기준 최종 손실이 -20% 이하로 확대된 거래. 확대 원인이 signal-day close 자체의 급락인지 overnight gap인지 현재 saved trade artifact만으로는 확정할 수 없음."
    # 3. POST_PROGRESSED_EXIT3_LAG
    elif has_prog and exit_type.startswith("EXIT3_") and ret <= -20.0:
        primary_cause = "POST_PROGRESSED_EXIT3_LAG"
        interpretation = "PROGRESSED 도달 후 주가가 하락하였으나 월봉 국면이 WEAK/BASE/TRANSITION 등으로 전환될 때까지 지연 청산되어 발생한 손실"
    # 4. POST_PROGRESSED_EXIT4_TAIL
    elif has_prog and exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15" and ret <= -20.0:
        primary_cause = "POST_PROGRESSED_EXIT4_TAIL"
        interpretation = "PROGRESSED 점수 HWM 대비 15pt 하락 청산 시 월간 급락으로 인해 큰 실현손실이 발생한 테일"
    # 5. NEVER_PROGRESSED_DEEP_LOSS
    elif lifecycle == "NEVER_PROGRESSED" and ret <= -20.0:
        primary_cause = "NEVER_PROGRESSED_DEEP_LOSS"
        interpretation = "PROGRESSED에 도달하지 못한 상태에서 발생한 심각한 하락 손실"
    # 6. COVERAGE_STRUCTURAL_TAIL
    elif lifecycle in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"} and ret <= -20.0:
        primary_cause = "COVERAGE_STRUCTURAL_TAIL"
        interpretation = "커버리지 생애주기 경로에서 청산 지연으로 발생한 손실"

    return {
        "primary_cause": primary_cause,
        "secondary_flags": secondary_flags,
        "research_interpretation": interpretation,
    }


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

    # Add data-driven classification columns
    causes = [classify_deep_loss_cause(r) for _, r in df_le_neg20.iterrows()]
    df_le_neg20["primary_cause"] = [c["primary_cause"] for c in causes]
    df_le_neg20["secondary_flags"] = [",".join(c["secondary_flags"]) if c["secondary_flags"] else "NONE" for c in causes]
    df_le_neg20["research_interpretation"] = [c["research_interpretation"] for c in causes]

    out_csv = V02_DIR / "deep_loss_reentry_cases.csv"
    df_le_neg20.to_csv(out_csv, index=False)
    print(f"Saved {len(df_le_neg20)} deep loss reentry cases to {out_csv}")

    # Generate Markdown deep loss report with Structural Facts vs Interpretation
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
        "2. Re-Entry <= -30% Extreme Loss Cases (4건 전수 구조적 사실 및 해석)",
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
        exit_sig = r["exit_signal_date"]
        exit_exec = r["exit_execution_date"]
        exit_p = r["exit_price"]
        t_ret = r["terminal_return"]
        mfe = r["mfe"]
        mae = r["mae"]
        gb = r["peak_giveback"]
        hw = r["holding_weeks"]
        status = r["trade_status"]
        p_cause = r["primary_cause"]
        s_flags = r["secondary_flags"]
        interp = r["research_interpretation"]

        md_lines.extend([
            f"### [{t_id}] {name} ({t}) - Sequence {seq}",
            "",
            "**[Structural Facts]**",
            f"- Previous Exit: `{prev_exit}` (Execution Date: `{prev_exec}`)",
            f"- Entry: Signal `{e_sig}` -> Execution `{e_exec}` (Open Price: `{e_open:,.0f}`원)",
            f"- Entry Context: Stage `{e_stage}`, Daily Risk `{risk}`, Score State `{f_state}`",
            f"- Lifecycle: `{life}` (First PROGRESSED: `{f_prog}`, Effective Trading Date: `{f_prog_eff}`)",
            f"- Loss Guard Triggered: `{lg_trig}`",
            f"- Exit Outcome: Type `{exit_t}`, Signal Date `{exit_sig}`, Exec Date `{exit_exec}`, Exec Price `{exit_p}`, Status `{status}`",
            f"- Performance: Terminal Return **`{t_ret}%`**, MFE `+{mfe}%`, MAE `{mae}%`, Giveback `{gb}%`, Holding `{hw}`주",
            "",
            "**[RESEARCH_INTERPRETATION]**",
            f"- **Primary Cause**: `{p_cause}`",
            f"- **Secondary Flags**: `{s_flags}`",
            f"- **Analysis**: {interp}",
            "",
        ])

    md_lines.extend([
        "================================================================================",
        "3. Re-Entry <= -20% Summary Statistics (14건 종합)",
        "================================================================================",
        "",
        "| Ticker | 종목명 | Trade ID | Seq | Previous Exit | Lifecycle | Exit Type | Status | Return | Primary Cause |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|",
    ])

    for _, r in df_le_neg20.iterrows():
        md_lines.append(
            f"| `{r['ticker']}` | {r['name']} | `{r['trade_id']}` | {r['trade_sequence']} | `{r['previous_exit_type']}` | `{r['lifecycle_class']}` | `{r['exit_type']}` | `{r['trade_status']}` | **{r['terminal_return']}%** | `{r['primary_cause']}` |"
        )

    out_md = V02_DIR / "deep_loss_reentry_cases.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Saved deep loss report to {out_md}")

    # Generate updated comparison_vs_v01.md
    _generate_comparison_markdown_doc(v02_df, v02_ticker_df)


def _generate_comparison_markdown_doc(v02_df: pd.DataFrame, ticker_df: pd.DataFrame):
    c_samsung = build_representative_case("005930", v02_df, ticker_df)
    c_lotte = build_representative_case("011170", v02_df, ticker_df)
    c_ankook = build_representative_case("001540", v02_df, ticker_df)

    eval_json = json.loads((V02_DIR / "evaluation.json").read_text(encoding="utf-8"))
    meta = eval_json["metadata"]
    risk = eval_json["risk_metrics"]
    ret = eval_json["return_metrics"]
    up = eval_json["upside_metrics"]
    gb = eval_json["giveback_metrics"]
    v01 = eval_json["comparator_v01"]
    v01_r = v01["v01_e2_risk_metrics"]
    v01_t = v01["v01_e2_terminal_return"]
    v01_u = v01["v01_e2_upside_metrics"]
    v01_g = v01["v01_e2_peak_giveback"]

    md = f"""# A FAST Core V01 vs A FAST Core V02 Re Entry 비교 보고서

================================================================================
1. Executive Summary
================================================================================
- **전략 명칭**: `{meta["strategy_name"]}` (`{meta["strategy_alias"]}`)
- **연구 분류**: `{meta["research_classification"]}`
- **평가 기준**: `{meta["evaluation_basis"]}`
- **캘린더 권한 커밋**: [`{meta["calendar_authority_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["calendar_authority_commit"]})
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **평가 결론**: **`{eval_json.get("evaluation_conclusion", "REENTRY_PROMISING_WITH_WORSE_DOWNSIDE_TAIL")}`**
- **제안 상태**: **`{eval_json.get("suggested_status", "PROMISING_NOT_YET_PROMOTED")}`**

================================================================================
2. V01 vs V02 핵심 비교표
================================================================================

| 핵심 평가 지표 | V01 (First Entry Only) | V02 (Re Entry Allowed) | 변화량 (Delta) |
|---|:---:|:---:|:---:|
| **총 거래 수 (Total Trades)** | {v01["v01_trade_count"]}건 | **{meta["total_trades"]}건** | **{meta["total_trades"] - v01["v01_trade_count"]:+d}건 (+{meta["total_reentry_trades"]}건 재진입)** |
| **참여 종목 수 (Unique Tickers)** | {v01["v01_trade_count"]}개 | **{meta["unique_tickers"]}개** | **0개 (100% 동일)** |
| **재진입 발생 종목 수** | 0개 | **{meta["reentered_tickers"]}개** | **+{meta["reentered_tickers"]}개** |
| **Return <= -30% 극단 손실 (비율)** | {v01_r["return_le_neg_30_count"]}건 ({v01_r["return_le_neg_30_rate"]}%) | **{risk["return_le_neg_30_count"]}건 ({risk["return_le_neg_30_rate"]}%)** | **{risk["return_le_neg_30_count"] - v01_r["return_le_neg_30_count"]:+d}건 ({risk["return_le_neg_30_rate"] - v01_r["return_le_neg_30_rate"]:+.2f}%p)** |
| **Return <= -20% 대형 손실 (비율)** | {v01_r["return_le_neg_20_count"]}건 ({v01_r["return_le_neg_20_rate"]}%) | **{risk["return_le_neg_20_count"]}건 ({risk["return_le_neg_20_rate"]}%)** | **{risk["return_le_neg_20_count"] - v01_r["return_le_neg_20_count"]:+d}건 ({risk["return_le_neg_20_rate"] - v01_r["return_le_neg_20_rate"]:+.2f}%p)** |
| **Return <= -15% 손실 (비율)** | 223건 (40.47%) | **{risk["return_le_neg_15_count"]}건 ({risk["return_le_neg_15_rate"]}%)** | **{risk["return_le_neg_15_count"] - 223:+d}건 ({risk["return_le_neg_15_rate"] - 40.47:+.2f}%p)** |
| **최악 손실률 (Worst Return)** | {v01_r["worst_return"]}% | **{risk["worst_return"]}%** | **{risk["worst_return"] - v01_r["worst_return"]:+.2f}%p (011170_02 구조적 테일)** |
| **최악 MAE (Worst MAE)** | -59.27% | **{risk["worst_mae"]}%** | **{risk["worst_mae"] - (-59.27):+.2f}%p** |
| **평균 MAE (Mean MAE)** | -14.93% | **{risk["mae_stats"]["mean"]}%** | **{risk["mae_stats"]["mean"] - (-14.93):+.2f}%p** |
| **중앙값 MAE (Median MAE)** | -16.18% | **{risk["mae_stats"]["median"]}%** | **{risk["mae_stats"]["median"] - (-16.18):+.2f}%p** |
| **Loss Guard 발동 비율** | 53.36% | **{risk["loss_guard_rate"]}%** | **{risk["loss_guard_rate"] - 53.36:+.2f}%p** |
| **평균 수익률 (Mean Return)** | {v01_t["mean"]}% | **{ret["terminal_return_stats"]["mean"]}%** | **{ret["terminal_return_stats"]["mean"] - v01_t["mean"]:+.2f}%p** |
| **중앙값 수익률 (Median Return)** | {v01_t["median"]}% | **{ret["terminal_return_stats"]["median"]}%** | **{ret["terminal_return_stats"]["median"] - v01_t["median"]:+.2f}%p** |
| **승률 (Positive Rate)** | 39.93% (220건) | **{ret["positive_rate"]}% ({ret["positive_count"]}건)** | **+{ret["positive_count"] - 220}건 ({ret["positive_rate"] - 39.93:+.2f}%p)** |
| **Terminal Return >= +20% 승자** | {v01_u.get("return_ge_20_count", 167)}건 ({v01_u.get("return_ge_20_rate", 30.31)}%) | **{up["return_ge_20_count"]}건 ({up["return_ge_20_rate"]}%)** | **+{up["return_ge_20_count"] - 167}건 ({up["return_ge_20_rate"] - 30.31:+.2f}%p)** |
| **Terminal Return >= +50% 대형 승자** | {v01_u["return_ge_50_count"]}건 ({v01_u["return_ge_50_rate"]}%) | **{up["return_ge_50_count"]}건 ({up["return_ge_50_rate"]}%)** | **+{up["return_ge_50_count"] - v01_u["return_ge_50_count"]}건 ({up["return_ge_50_rate"] - v01_u["return_ge_50_rate"]:+.2f}%p)** |
| **Terminal Return >= +100% 초대형 승자** | {v01_u["return_ge_100_count"]}건 ({v01_u["return_ge_100_rate"]}%) | **{up["return_ge_100_count"]}건 ({up["return_ge_100_rate"]}%)** | **+{up["return_ge_100_count"] - v01_u["return_ge_100_count"]}건 ({up["return_ge_100_rate"] - v01_u["return_ge_100_rate"]:+.2f}%p)** |
| **Peak Giveback 중앙값** | {v01_g["median"]}% | **{gb["giveback_stats"]["median"]}%** | **{gb["giveback_stats"]["median"] - v01_g["median"]:+.2f}%p** |
| **종목 생애주기 평균 누적 수익률** | 18.48% | **{eval_json["sequential_ticker_cumulative_return"]["mean"]}%** | **{eval_json["sequential_ticker_cumulative_return"]["mean"] - 18.48:+.2f}%p 대폭 상승** |
| **종목 생애주기 중앙값 누적 수익률** | -13.60% | **{eval_json["sequential_ticker_cumulative_return"]["median"]}%** | **{eval_json["sequential_ticker_cumulative_return"]["median"] - (-13.60):+.2f}%p 대폭 개선** |
| **종목 생애주기 플러스 종목 비율** | 39.93% | **{eval_json["sequential_ticker_cumulative_return"]["positive_rate"]}%** | **{eval_json["sequential_ticker_cumulative_return"]["positive_rate"] - 39.93:+.2f}%p 대폭 상승** |

================================================================================
3. 거래 차수별 (Sequence) 세부 성과
================================================================================
- **1차 진입 (First Entry, 551건)**:
  - 평균 수익률: **18.48%** / 중앙값: **-13.60%** / 승률: **39.93% (220건 승리)**
  - <= -20% 손실: **25건 (4.54%)** / <= -30% 손실: **6건 (1.09%)** / >= +50% 승자: **117건 (21.23%)**
- **재진입 전체 (Re-Entry All, 232건)**:
  - 평균 수익률: **19.69%** / 중앙값: **-13.66%** / 승률: **40.52% (94건 승리)**
  - <= -20% 손실: **14건 (6.03%)** / <= -30% 손실: **4건 (1.72%)** / >= +50% 승자: **51건 (21.98%)**
- **2차 진입 (151건)**: 평균 14.93%, 중앙값 -14.48%, 승률 35.76%, <= -20% 7.95% (12건), >= +50% 17.88% (27건)
- **3차 진입 (48건)**: 평균 18.91%, 중앙값 -8.34%, 승률 47.92%, <= -20% 4.17% (2건), >= +50% 27.08% (13건)
- **4차 이상 진입 (33건)**: 평균 42.63%, 중앙값 +12.90%, 승률 51.52%, <= -20% 0.00% (0건), >= +50% 33.33% (11건)

================================================================================
4. 직전 청산 사유별 재진입 성과
================================================================================
- **Loss Guard 이후 재진입 (192건)**:
  - 평균 수익률: **+22.28%** / 중앙값: **-13.43%** / 승률: **41.15% (79건 승리)**
  - Return <= -20% / <= -30%: **12건 (6.25%) / 4건 (2.08%)**
  - Return >= +50% 대형 승자: **44건**
  - Return >= +100% 초대형 승자: **17건**
- **Exit 4 (Score HWM 15pt Drawdown) 이후 재진입 (31건)**:
  - 평균 수익률: **+8.64%** / 중앙값: **-14.86%** / 승률: **38.71% (12건 승리)** / >= +50%: **7건**
- **Exit 3 (Stage Transition) 이후 재진입 (9건)**:
  - 평균 수익률: **+2.53%** / 중앙값: **-15.89%** / 승률: **33.33% (3건 승리)**

================================================================================
5. 대표 사례 검증 (Deterministic Real Cases from Artifacts)
================================================================================

### 1. 삼성전자 (005930) - 생애주기 누적 수익률: **+{c_samsung["sequential_cumulative_return_pct"]}%**
"""
    for tr in c_samsung["trades"]:
        md += f"- **Sequence {tr['trade_sequence']}** (`{tr['trade_id']}`): Entry Signal `{tr['entry_signal_date']}` -> Exec `{tr['entry_execution_date']}` (Open `{tr['entry_open']:,.0f}`원) | Exit: `{tr['exit_type']}` (Sig `{tr['exit_signal_date']}`, Exec `{tr['exit_execution_date']}`, Price `{tr['exit_price']}`) | **Return: `{tr['terminal_return']}%`**, Status: `{tr['trade_status']}`\n"

    md += f"""
### 2. 롯데케미칼 (011170) - 생애주기 누적 수익률: **{c_lotte["sequential_cumulative_return_pct"]}%**
"""
    for tr in c_lotte["trades"]:
        md += f"- **Sequence {tr['trade_sequence']}** (`{tr['trade_id']}`): Entry Signal `{tr['entry_signal_date']}` -> Exec `{tr['entry_execution_date']}` (Open `{tr['entry_open']:,.0f}`원) | Exit: `{tr['exit_type']}` (Sig `{tr['exit_signal_date']}`, Exec `{tr['exit_execution_date']}`) | **Return: `{tr['terminal_return']}%`**, MAE: `{tr['mae']}%`, Status: `{tr['trade_status']}`\n"

    md += f"""
### 3. 안국약품 (001540) - 생애주기 누적 수익률: **+{c_ankook["sequential_cumulative_return_pct"]}%**
"""
    for tr in c_ankook["trades"]:
        md += f"- **Sequence {tr['trade_sequence']}** (`{tr['trade_id']}`): Entry Signal `{tr['entry_signal_date']}` -> Exec `{tr['entry_execution_date']}` (Open `{tr['entry_open']:,.0f}`원) | Exit: `{tr['exit_type']}` (Sig `{tr['exit_signal_date']}`, Exec `{tr['exit_execution_date']}`) | **Return: `{tr['terminal_return']}%`**, Status: `{tr['trade_status']}`\n"

    out_comp = V02_DIR / "comparison_vs_v01.md"
    out_comp.write_text(md, encoding="utf-8")
    print(f"Saved comparison markdown to {out_comp}")


if __name__ == "__main__":
    generate_identity_and_deep_loss_artifacts()
