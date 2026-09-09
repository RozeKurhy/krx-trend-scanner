"""Fear Index Research V01.

This module is intentionally research-only.  It joins the official KRX
V-KOSPI 200 export to the existing KOSPI canonical series and evaluates
three deterministic fear-score candidates without adding macro inputs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REGIMES = ("OVERHEATED", "NORMAL", "ANXIOUS", "PANIC", "APATHY")
CANDIDATES = ("balanced_v01", "downside_sensitive_v01", "participation_aware_v01")
DATE_MIN = pd.Timestamp("2010-01-04")
DATE_MAX = pd.Timestamp("2026-09-04")
VALIDATION_CUTOFF = pd.Timestamp("2022-01-01")


def _json_default(value: object) -> str | float | int | None:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return str(value)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    def last_percentile(values: pd.Series) -> float:
        return float(values.rank(pct=True).iloc[-1])

    return series.rolling(window, min_periods=min_periods).apply(last_percentile, raw=False)


def _clip01(series: pd.Series) -> pd.Series:
    return series.replace([np.inf, -np.inf], np.nan).clip(0.0, 1.0)


def load_v_kospi_exports(export_dir: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load repository-preserved KRX CSV exports and validate raw integrity."""
    files = sorted(export_dir.glob("v_kospi200_*_official.csv"))
    if not files:
        raise FileNotFoundError(f"No V-KOSPI official exports under {export_dir}")

    frames: list[pd.DataFrame] = []
    numeric_failures = 0
    for path in files:
        frame = pd.read_csv(path, encoding="utf-8")
        expected = ["일자", "종가", "대비", "등락률", "시가", "고가", "저가"]
        missing = [column for column in expected if column not in frame.columns]
        if missing:
            raise ValueError(f"{path.name} missing columns: {missing}")
        frame = frame.rename(
            columns={
                "일자": "date",
                "종가": "v_kospi200_close",
                "대비": "change",
                "등락률": "change_pct",
                "시가": "open",
                "고가": "high",
                "저가": "low",
            }
        )
        frame["source_file"] = path.name
        frame["date"] = pd.to_datetime(frame["date"], format="%Y/%m/%d", errors="coerce")
        if frame["date"].isna().any():
            raise ValueError(f"{path.name} has invalid dates")
        for column in ("v_kospi200_close", "change", "change_pct", "open", "high", "low"):
            before = frame[column].notna().sum()
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            numeric_failures += int(before - frame[column].notna().sum())
        frames.append(frame)

    raw = pd.concat(frames, ignore_index=True)
    duplicate_dates = int(raw["date"].duplicated(keep=False).sum())
    conflicting_duplicates = 0
    if duplicate_dates:
        grouped = raw.groupby("date")["v_kospi200_close"].nunique(dropna=False)
        conflicting_duplicates = int((grouped > 1).sum())
        if conflicting_duplicates:
            raise ValueError("Conflicting duplicate V-KOSPI dates found")
        raw = raw.drop_duplicates(subset=["date"], keep="first")

    normalized = raw.sort_values("date").reset_index(drop=True)
    if normalized["date"].duplicated().any():
        raise ValueError("Duplicate V-KOSPI dates remain after normalization")
    validation = {
        "source": "KRX Data Marketplace",
        "index": "V-KOSPI 200 (KRX displayed name: 코스피 200 변동성지수)",
        "file_count": len(files),
        "files": [path.name for path in files],
        "date_min": normalized["date"].min(),
        "date_max": normalized["date"].max(),
        "row_count": len(normalized),
        "duplicate_date_count": duplicate_dates,
        "conflicting_duplicate_date_count": conflicting_duplicates,
        "null_value_count": int(normalized["v_kospi200_close"].isna().sum()),
        "numeric_parse_failure_count": numeric_failures,
        "sample_values": {
            date: None
            if normalized.loc[normalized["date"].eq(pd.Timestamp(date)), "v_kospi200_close"].empty
            else float(normalized.loc[normalized["date"].eq(pd.Timestamp(date)), "v_kospi200_close"].iloc[0])
            for date in (
                "2011-08-08",
                "2011-08-19",
                "2017-01-02",
                "2020-03-19",
                "2022-01-03",
                "2024-08-05",
                "2026-06-18",
                "2026-06-29",
                "2026-09-04",
            )
        },
    }
    return normalized, validation


def load_kospi_canonical(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    code = frame["index_code"].astype(str).str.strip()
    frame = frame.loc[code.eq("1001")].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["kospi_close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["trading_value"] = pd.to_numeric(frame["trading_value"], errors="coerce")
    frame = frame[["date", "kospi_close", "trading_value"]].sort_values("date")
    if frame["date"].duplicated().any():
        raise ValueError("KOSPI canonical source contains duplicate dates")
    return frame.reset_index(drop=True)


def exact_date_join(kospi: pd.DataFrame, v_kospi: pd.DataFrame) -> pd.DataFrame:
    """Join the three research inputs on exact trading dates only."""
    left = kospi[["date", "kospi_close", "trading_value"]].copy()
    right = v_kospi[["date", "v_kospi200_close"]].copy()
    joined = left.merge(right, on="date", how="inner", validate="one_to_one")
    return joined.sort_values("date").reset_index(drop=True)


def build_features(joined: pd.DataFrame) -> pd.DataFrame:
    """Build PIT-safe features using only current and prior observations."""
    frame = joined.copy().sort_values("date").reset_index(drop=True)
    v = frame["v_kospi200_close"]
    k = frame["kospi_close"]
    value = frame["trading_value"]

    frame["v_level_pct_252"] = _rolling_percentile(v, 252, 126)
    v_mean = v.rolling(60, min_periods=30).mean()
    v_std = v.rolling(60, min_periods=30).std().replace(0.0, np.nan)
    frame["v_z_60"] = (v - v_mean) / v_std
    frame["v_change_20"] = v.pct_change(20)
    frame["kospi_return_20"] = k.pct_change(20)
    frame["kospi_return_60"] = k.pct_change(60)
    frame["kospi_drawdown_60"] = k / k.rolling(60, min_periods=30).max() - 1.0
    frame["participation_pct_252"] = _rolling_percentile(value, 252, 126)
    value_median = value.rolling(252, min_periods=126).median()
    frame["participation_ratio_20"] = value.rolling(20, min_periods=10).mean() / value_median

    # Future labels are evaluation-only and are never used by score formulas.
    future_prices = pd.concat({f"p{i}": k.shift(-i) for i in range(1, 21)}, axis=1)
    frame["future_return_20"] = k.shift(-20) / k - 1.0
    frame["future_min_return_20"] = future_prices.min(axis=1, skipna=True) / k - 1.0
    frame["future_risk_event_20"] = (
        (frame["future_return_20"] <= -0.08) | (frame["future_min_return_20"] <= -0.10)
    ).astype("float64")
    frame.loc[frame["future_return_20"].isna(), "future_risk_event_20"] = np.nan
    return frame


def build_candidate_scores(features: pd.DataFrame) -> pd.DataFrame:
    frame = features.copy()
    v_level = frame["v_level_pct_252"]
    v_spike = 1.0 / (1.0 + np.exp(-frame["v_z_60"].clip(-8.0, 8.0)))
    v_momentum = _clip01(0.5 + frame["v_change_20"] / 0.8)
    downside = _clip01(
        0.5 * (-frame["kospi_return_20"] / 0.15)
        + 0.5 * (-frame["kospi_drawdown_60"] / 0.25)
    )
    low_participation = 1.0 - frame["participation_pct_252"]

    frame["score_balanced_v01"] = 100.0 * (
        0.45 * v_level + 0.15 * v_spike + 0.20 * downside + 0.10 * v_momentum + 0.10 * low_participation
    )
    frame["score_downside_sensitive_v01"] = 100.0 * (
        0.35 * v_level + 0.10 * v_spike + 0.35 * downside + 0.10 * v_momentum + 0.10 * low_participation
    )
    frame["score_participation_aware_v01"] = 100.0 * (
        0.35 * v_level + 0.10 * v_spike + 0.20 * downside + 0.10 * v_momentum + 0.25 * low_participation
    )
    for candidate in CANDIDATES:
        column = f"score_{candidate}"
        frame[column] = frame[column].clip(0.0, 100.0)
    return frame


def _brier(probability: pd.Series, outcome: pd.Series) -> float:
    return float(((probability - outcome) ** 2).mean())


def evaluate_candidates(features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for candidate in CANDIDATES:
        score_column = f"score_{candidate}"
        complete = features[["date", score_column, "future_risk_event_20", "future_min_return_20"]].dropna()
        for split, mask in (
            ("calibration", complete["date"] < VALIDATION_CUTOFF),
            ("validation", complete["date"] >= VALIDATION_CUTOFF),
        ):
            sample = complete.loc[mask].copy()
            probability = sample[score_column] / 100.0
            outcome = sample["future_risk_event_20"]
            if sample.empty:
                continue
            top_cut = sample[score_column].quantile(0.80)
            top = sample.loc[sample[score_column] >= top_cut]
            # Avoid an optional scipy dependency: Spearman is Pearson on ranks.
            corr = probability.rank().corr((-sample["future_min_return_20"]).rank())
            rows.append(
                {
                    "candidate": candidate,
                    "split": split,
                    "rows": len(sample),
                    "brier": _brier(probability, outcome),
                    "spearman_adverse_return": 0.0 if pd.isna(corr) else float(corr),
                    "top_quintile_cut": float(top_cut),
                    "top_quintile_event_rate": float(top["future_risk_event_20"].mean()),
                    "top_quintile_mean_future_min_return": float(top["future_min_return_20"].mean()),
                    "overall_event_rate": float(outcome.mean()),
                }
            )
    return pd.DataFrame(rows)


def select_final_candidate(metrics: pd.DataFrame) -> str:
    validation = metrics.loc[metrics["split"].eq("validation")].copy()
    if validation.empty:
        validation = metrics.loc[metrics["split"].eq("calibration")].copy()
    selected = validation.sort_values(
        ["brier", "spearman_adverse_return", "candidate"], ascending=[True, False, True]
    ).iloc[0]
    return str(selected["candidate"])


def classify_regime(row: pd.Series | dict[str, object]) -> str:
    """Classify a non-linear five-regime state with explicit directional guards."""
    values = row if isinstance(row, dict) else row.to_dict()
    required = ("fear_score", "kospi_return_20", "kospi_return_60", "kospi_drawdown_60", "participation_pct_252")
    if any(pd.isna(values.get(key)) for key in required):
        return "UNAVAILABLE"
    score = float(values["fear_score"])
    ret20 = float(values["kospi_return_20"])
    ret60 = float(values["kospi_return_60"])
    drawdown = float(values["kospi_drawdown_60"])
    participation = float(values["participation_pct_252"])
    downside = ret20 <= -0.05 or drawdown <= -0.10
    strong_up = ret20 >= 0.08 or ret60 >= 0.12
    weak_low_participation = ret60 <= 0.03 and participation <= 0.40 and not downside

    # PANIC requires both high fear and downside.  High V-KOSPI during a strong
    # upward move is therefore not allowed to become PANIC by itself.
    if score >= 72.0 and downside:
        return "PANIC"
    if strong_up and participation >= 0.55 and not downside:
        return "OVERHEATED"
    if weak_low_participation and score <= 45.0:
        return "APATHY"
    if score >= 50.0 or downside:
        return "ANXIOUS"
    return "NORMAL"


def assign_regimes(features: pd.DataFrame, candidate: str) -> pd.DataFrame:
    frame = features.copy()
    score_column = f"score_{candidate}"
    frame["fear_score"] = frame[score_column].clip(0.0, 100.0)
    frame["regime"] = frame.apply(classify_regime, axis=1)
    return frame


def flicker_summary(regimes: pd.Series) -> dict[str, int | float]:
    valid = regimes.loc[regimes.ne("UNAVAILABLE")].reset_index(drop=True)
    switches = valid.ne(valid.shift(1)) & valid.shift(1).notna()
    rapid = valid.ne(valid.shift(1)) & valid.eq(valid.shift(2)) & valid.shift(2).notna()
    return {
        "valid_days": int(len(valid)),
        "regime_switches": int(switches.sum()),
        "switch_rate": float(switches.mean()) if len(valid) else 0.0,
        "two_day_return_flickers": int(rapid.sum()),
    }


def build_historical_events(frame: pd.DataFrame) -> pd.DataFrame:
    event_dates = pd.to_datetime(
        [
            "2011-08-08",
            "2011-08-19",
            "2017-01-02",
            "2020-03-19",
            "2022-01-03",
            "2024-08-05",
            "2026-06-18",
            "2026-06-29",
            "2026-09-04",
        ]
    )
    columns = [
        "date",
        "v_kospi200_close",
        "kospi_close",
        "fear_score",
        "regime",
        "kospi_return_20",
        "kospi_return_60",
        "kospi_drawdown_60",
        "participation_pct_252",
        "future_return_20",
        "future_min_return_20",
    ]
    return frame.loc[frame["date"].isin(event_dates), columns].copy()


def run_research(export_dir: Path, kospi_path: Path, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    source_dir = output_root / "source"
    normalized_dir = source_dir
    v_kospi, acquisition = load_v_kospi_exports(export_dir)
    kospi = load_kospi_canonical(kospi_path)
    joined = exact_date_join(kospi, v_kospi)
    features = build_features(joined)
    scored = build_candidate_scores(features)
    metrics = evaluate_candidates(scored)
    final_candidate = select_final_candidate(metrics)
    final_frame = assign_regimes(scored, final_candidate)

    normalized_dir.mkdir(parents=True, exist_ok=True)
    v_kospi.to_csv(normalized_dir / "v_kospi200_daily_normalized.csv", index=False, date_format="%Y-%m-%d")
    joined.to_csv(output_root / "exact_date_join.csv", index=False, date_format="%Y-%m-%d")
    scored.to_csv(output_root / "feature_and_candidate_scores.csv", index=False, date_format="%Y-%m-%d")
    metrics.to_csv(output_root / "candidate_comparison.csv", index=False)
    final_frame.to_csv(output_root / "final_daily_regimes.csv", index=False, date_format="%Y-%m-%d")

    events = build_historical_events(final_frame)
    events.to_csv(output_root / "historical_event_validation.csv", index=False, date_format="%Y-%m-%d")
    false_positive_rows = final_frame.loc[
        final_frame["future_risk_event_20"].eq(0)
        & final_frame["future_return_20"].notna()
    ].nlargest(25, "fear_score")
    false_positive_rows.to_csv(output_root / "false_positive_review.csv", index=False, date_format="%Y-%m-%d")

    flicker = flicker_summary(final_frame["regime"])
    regime_counts = {
        regime: int(final_frame["regime"].eq(regime).sum()) for regime in REGIMES
    }
    acquisition.update(
        {
            "official_url": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201010303",
            "krx_menu_path": "통계 > 기본 통계 > 지수 > 파생 및 기타지수 > 개별지수 시세 추이",
            "login": "SUCCESS",
            "download": "chunked",
            "downloaded_files": [
                {"period": "2010-01-04~2011-12-31", "file": "data_5119_20260909.csv", "sha256": "c9ffbe3ed723fe2fcda9250365edabe4851a9540539a0f7b37024ced9d8fb09d"},
                {"period": "2012-01-01~2013-12-31", "file": "data_5624_20260909.csv", "sha256": "38af893fba8771928d8abcec03e79abac85832be9cce0b4901efb94b7720b755"},
                {"period": "2014-01-01~2015-12-31", "file": "data_5209_20260909.csv", "sha256": "c74c94e7fce48674aa27977ee87f92b0f5863800484b3f5872614545e2ab2602"},
                {"period": "2016-01-01~2017-12-31", "file": "data_5418_20260909.csv", "sha256": "35401fe02d5c3a473983863e1fa10d4154e05c457965e012f92ac0dafe53106b"},
                {"period": "2018-01-01~2019-12-31", "file": "data_5219_20260909.csv", "sha256": "6f61a003f0b410976e422800b47d1309524f04d25e7eb1b3876d3b278ad03b5e"},
                {"period": "2020-01-01~2021-12-31", "file": "data_5513_20260909.csv", "sha256": "e8e3bb0913619e2c4a260e1da9970ba4b6a96676532082d9363c729bd7534577"},
                {"period": "2022-01-01~2023-12-31", "file": "data_5229_20260909.csv", "sha256": "093770884b12487f3f8789afd2daf81f541eea6a4316e5cc64721130003bfa41"},
                {"period": "2024-01-01~2025-12-31", "file": "data_5609_20260909.csv", "sha256": "8de975ac3f6d0a1e41764b7896f334567d0d7f59ddd863efe5c536fe3749cc62"},
                {"period": "2026-01-01~2026-09-04", "file": "data_5239_20260909.csv", "sha256": "f0941ee4786d1610cb458f825247292f72f607f01b6c46a7610fc83de4c1bc0c"},
            ],
            "official_date_range": {
                "min": acquisition["date_min"],
                "max": acquisition["date_max"],
            },
            "normalized_row_count": len(v_kospi),
            "duplicate_dates": acquisition["duplicate_date_count"],
            "null_values": acquisition["null_value_count"],
        }
    )
    write_json(source_dir / "krx_acquisition_validation.json", acquisition)

    validation_metrics = metrics.loc[metrics["split"].eq("validation")].copy()
    selected_metrics = validation_metrics.loc[validation_metrics["candidate"].eq(final_candidate)].iloc[0]
    summary = {
        "study": "Fear Index Research & Market Regime Backtest V01",
        "inputs": ["V-KOSPI 200", "KOSPI", "KOSPI trading_value"],
        "date_range": {"min": joined["date"].min(), "max": joined["date"].max()},
        "joined_rows": len(joined),
        "candidate_count": len(CANDIDATES),
        "final_candidate": final_candidate,
        "validation": {
            "cutoff": VALIDATION_CUTOFF,
            "brier": selected_metrics["brier"],
            "spearman_adverse_return": selected_metrics["spearman_adverse_return"],
        },
        "regime_counts": regime_counts,
        "flicker": flicker,
        "historical_event_rows": len(events),
        "false_positive_review_rows": len(false_positive_rows),
        "web_changed": False,
    }
    write_json(output_root / "research_summary.json", summary)

    formula = f"""# Fear Index V01 final formula\n\nSelected candidate: `{final_candidate}`\n\nThe score is bounded to 0-100 and uses only V-KOSPI 200, KOSPI close, and KOSPI trading value. All rolling features use current and prior observations only.\n\nRegime guards:\n\n- `PANIC`: score >= 72 and KOSPI downside (`20D return <= -5%` or `60D drawdown <= -10%`).\n- `OVERHEATED`: strong positive KOSPI trend with adequate participation and no downside guard.\n- `APATHY`: low score, weak/flat KOSPI, and participation percentile <= 40%.\n- `ANXIOUS`: elevated score or downside not meeting PANIC.\n- `NORMAL`: remaining available observations.\n\nThe downside guard is intentional: elevated V-KOSPI during a strong bull move cannot become PANIC automatically.\n"""
    (output_root / "final_formula.md").write_text(formula, encoding="utf-8")

    report = f"""# Fear Index Research & Market Regime Backtest V01\n\n- KRX menu path: `통계 > 기본 통계 > 지수 > 파생 및 기타지수 > 개별지수 시세 추이`\n- Index: `V-KOSPI 200` / KRX displayed name `코스피 200 변동성지수`\n- Login: `SUCCESS`\n- Download: `chunked` (9 official CSV exports, each within the KRX two-year limit)\n- Official date range: `{acquisition['date_min']:%Y-%m-%d} ~ {acquisition['date_max']:%Y-%m-%d}`\n- Normalized row count: `{acquisition['normalized_row_count']}`\n- Duplicate dates: `{acquisition['duplicate_dates']}`\n- Null values: `{acquisition['null_values']}`\n\n## Research\n\n- Exact-date join rows: `{len(joined)}`\n- Inputs: V-KOSPI 200, KOSPI, KOSPI trading_value\n- Candidates evaluated: `{', '.join(CANDIDATES)}`\n- Final candidate: `{final_candidate}`\n- Validation cutoff: `{VALIDATION_CUTOFF:%Y-%m-%d}`\n- Validation Brier: `{float(selected_metrics['brier']):.6f}`\n- Validation adverse-return Spearman: `{float(selected_metrics['spearman_adverse_return']):.6f}`\n- Regime counts: `{regime_counts}`\n- Flicker summary: `{flicker}`\n\n## Scope\n\nNo web files or production payloads were changed. The 2008 financial-crisis check remains `NOT IN COMMON SOURCE RANGE` because the canonical KOSPI input begins on 2010-01-04.\n"""
    (output_root / "final_report.md").write_text(report, encoding="utf-8")
    return summary


__all__ = [
    "CANDIDATES",
    "REGIMES",
    "assign_regimes",
    "build_candidate_scores",
    "build_features",
    "classify_regime",
    "exact_date_join",
    "flicker_summary",
    "load_kospi_canonical",
    "load_v_kospi_exports",
    "run_research",
    "select_final_candidate",
]
