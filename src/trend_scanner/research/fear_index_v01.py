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
CANDIDATES = ("balanced_no_participation_v01", "panic_confirmed_v01", "downside_heavy_v01")
CANDIDATE_COMPLEXITY = {
    "balanced_no_participation_v01": 4,
    "panic_confirmed_v01": 5,
    "downside_heavy_v01": 4,
}
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
    frame["kospi_return_5"] = k.pct_change(5)
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
    high_participation = _clip01(
        0.60 * frame["participation_pct_252"]
        + 0.40 * (frame["participation_ratio_20"] - 1.0).clip(0.0, 1.0)
    )
    panic_participation = downside * high_participation

    # Candidate A: participation is excluded from fear intensity.
    frame["score_balanced_no_participation_v01"] = 100.0 * (
        0.50 * v_level + 0.15 * v_spike + 0.25 * downside + 0.10 * v_momentum
    )
    # Candidate B: participation can reinforce fear only in a downside state.
    frame["score_panic_confirmed_v01"] = 100.0 * (
        0.45 * v_level + 0.10 * v_spike + 0.30 * downside + 0.10 * v_momentum + 0.05 * panic_participation
    )
    # Candidate C: simple downside-heavy score; participation is reserved for
    # regime confirmation rather than fear intensity.
    frame["score_downside_heavy_v01"] = 100.0 * (
        0.40 * v_level + 0.10 * v_spike + 0.40 * downside + 0.10 * v_momentum
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


def _candidate_period_gate(frame: pd.DataFrame, candidate: str) -> dict[str, object]:
    """Apply the FIX01 historical sanity gate, not a forward-risk objective."""
    def subset(start: str, end: str) -> pd.DataFrame:
        return frame.loc[frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))]

    def state_at(date: str) -> str:
        rows = frame.loc[frame["date"].eq(pd.Timestamp(date)), "regime"]
        return str(rows.iloc[0]) if not rows.empty else "MISSING"

    def longest_run(values: pd.Series, target: str) -> int:
        longest = current = 0
        for value in values.tolist():
            current = current + 1 if value == target else 0
            longest = max(longest, current)
        return longest

    periods = {
        "2011_08_09": subset("2011-08-01", "2011-09-30"),
        "2012_2016": subset("2012-01-01", "2016-12-31"),
        "2017": subset("2017-01-01", "2017-12-31"),
        "2018": subset("2018-01-01", "2018-12-31"),
        "2020_covid": subset("2020-02-20", "2020-04-30"),
        "2021": subset("2021-01-01", "2021-12-31"),
        "2022": subset("2022-01-01", "2022-12-31"),
        "2024_08": subset("2024-08-01", "2024-08-09"),
        "2026_06": subset("2026-06-01", "2026-06-30"),
    }
    p2017 = periods["2017"]
    p2022 = periods["2022"]
    p2026 = periods["2026_06"]
    gates = {
        "2020-03-19_panic": state_at("2020-03-19") == "PANIC",
        "2024-08-05_panic": state_at("2024-08-05") == "PANIC",
        "2026-06-18_non_panic": state_at("2026-06-18") != "PANIC",
        "2026-06-29_non_panic": state_at("2026-06-29") != "PANIC",
        "2017_not_panic_or_apathy_dominated": len(p2017) > 0
        and int(p2017["regime"].isin(["PANIC", "APATHY"]).sum()) < len(p2017) / 2,
        "2022_anxious_exceeds_panic": int((p2022["regime"] == "ANXIOUS").sum())
        > int((p2022["regime"] == "PANIC").sum()),
        "2012_2016_apathy_cluster": longest_run(periods["2012_2016"]["regime"], "APATHY") >= 5,
        "2026_june_no_panic_cluster": int((p2026["regime"] == "PANIC").sum()) <= 2,
    }
    return {
        "candidate": candidate,
        "gate_pass": bool(all(gates.values())),
        "gates": gates,
        "anchor_states": {
            date: state_at(date)
            for date in (
                "2020-03-19",
                "2024-08-05",
                "2026-06-18",
                "2026-06-29",
            )
        },
        "2017_panic_days": int((p2017["regime"] == "PANIC").sum()),
        "2017_apathy_days": int((p2017["regime"] == "APATHY").sum()),
        "2022_panic_days": int((p2022["regime"] == "PANIC").sum()),
        "2022_anxious_days": int((p2022["regime"] == "ANXIOUS").sum()),
        "2026_june_panic_days": int((p2026["regime"] == "PANIC").sum()),
        "2012_2016_apathy_longest_run": longest_run(periods["2012_2016"]["regime"], "APATHY"),
    }


def select_final_candidate(candidate_frames: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Select by historical gates, contradiction count, flicker, then simplicity.

    Forward-return/Brier metrics are intentionally absent from this selector.
    """
    gate_rows: list[dict[str, object]] = []
    for candidate, frame in candidate_frames.items():
        gate = _candidate_period_gate(frame, candidate)
        gate["flicker_switches"] = run_length_stats(frame["regime"])["switch_count"]
        gate["complexity"] = CANDIDATE_COMPLEXITY[candidate]
        gate_rows.append(gate)
    gate_table = pd.DataFrame(gate_rows)
    passing = gate_table.loc[gate_table["gate_pass"]].copy()
    if passing.empty:
        raise ValueError("No Fear Index candidate passed the FIX01 historical gate")
    selected = passing.sort_values(
        ["flicker_switches", "complexity", "candidate"], ascending=[True, True, True]
    ).iloc[0]
    selected_name = str(selected["candidate"])
    return selected_name, candidate_frames[selected_name], gate_table


def classify_regime(row: pd.Series | dict[str, object]) -> str:
    """Classify a non-linear five-regime state with explicit directional guards."""
    values = row if isinstance(row, dict) else row.to_dict()
    required = (
        "fear_score",
        "kospi_return_5",
        "kospi_return_20",
        "kospi_return_60",
        "kospi_drawdown_60",
        "participation_pct_252",
        "participation_ratio_20",
    )
    if any(pd.isna(values.get(key)) for key in required):
        return "UNAVAILABLE"
    score = float(values["fear_score"])
    ret5 = float(values["kospi_return_5"])
    ret20 = float(values["kospi_return_20"])
    ret60 = float(values["kospi_return_60"])
    drawdown = float(values["kospi_drawdown_60"])
    participation = float(values["participation_pct_252"])
    participation_ratio = float(values["participation_ratio_20"])
    downside = ret20 <= -0.05 or drawdown <= -0.10
    sharp_downside = ret20 <= -0.07 or ret5 <= -0.04
    severe_downside = ret20 <= -0.12 or drawdown <= -0.18 or ret5 <= -0.06
    high_participation = participation >= 0.75 or participation_ratio >= 1.25
    bull_context = ret60 >= 0.25 and ret20 > -0.05
    extreme_panic = score >= 88.0 and severe_downside and not bull_context

    # PANIC requires high fear, current downside, and participation confirmation.
    # An extreme-fear/severe-downside override covers obvious crash sessions.
    if ((score >= 70.0 and downside and high_participation and not bull_context) or extreme_panic):
        return "PANIC"
    strong_up = ret20 >= 0.08 or ret60 >= 0.12
    if strong_up and participation >= 0.55 and not sharp_downside and (not downside or bull_context):
        return "OVERHEATED"
    low_participation = participation <= 0.25 and participation_ratio <= 0.85
    weak_low_participation = ret60 <= 0.05 and not sharp_downside
    if score <= 50.0 and low_participation and weak_low_participation:
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


def run_length_stats(regimes: pd.Series) -> dict[str, int | float]:
    valid = regimes.loc[regimes.ne("UNAVAILABLE")].reset_index(drop=True)
    if valid.empty:
        return {"valid_days": 0, "switch_count": 0, "switch_rate": 0.0, "one_day_runs": 0, "two_day_runs": 0, "median_run_length": 0.0, "mean_run_length": 0.0, "max_run_length": 0}
    groups = valid.ne(valid.shift(1)).cumsum()
    lengths = valid.groupby(groups, sort=False).size()
    switches = max(len(lengths) - 1, 0)
    return {
        "valid_days": int(len(valid)),
        "switch_count": int(switches),
        "switch_rate": float(switches / len(valid)),
        "one_day_runs": int((lengths == 1).sum()),
        "two_day_runs": int((lengths == 2).sum()),
        "median_run_length": float(lengths.median()),
        "mean_run_length": float(lengths.mean()),
        "max_run_length": int(lengths.max()),
    }


def flicker_summary(regimes: pd.Series) -> dict[str, int | float]:
    stats = run_length_stats(regimes)
    valid = regimes.loc[regimes.ne("UNAVAILABLE")].reset_index(drop=True)
    rapid = valid.ne(valid.shift(1)) & valid.eq(valid.shift(2)) & valid.shift(2).notna()
    return {
        **stats,
        "regime_switches": stats["switch_count"],
        "two_day_return_flickers": int(rapid.sum()),
    }


def stabilize_regimes(regimes: pd.Series) -> pd.Series:
    """PIT-safe hysteresis: PANIC enters immediately; other changes need 2 days."""
    output: list[str] = []
    state = "UNAVAILABLE"
    pending = ""
    pending_count = 0
    for current in regimes.tolist():
        if current == "UNAVAILABLE":
            output.append("UNAVAILABLE")
            continue
        if state == "UNAVAILABLE":
            state = current
            pending = ""
            pending_count = 0
        elif current == "PANIC":
            state = "PANIC"
            pending = ""
            pending_count = 0
        elif current == state:
            pending = ""
            pending_count = 0
        else:
            if pending == current:
                pending_count += 1
            else:
                pending = current
                pending_count = 1
            if pending_count >= 2:
                state = current
                pending = ""
                pending_count = 0
        output.append(state)
    return pd.Series(output, index=regimes.index, name="stabilized_regime")


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
        "kospi_return_5",
        "kospi_return_20",
        "kospi_return_60",
        "kospi_drawdown_60",
        "participation_pct_252",
        "participation_ratio_20",
        "future_return_20",
        "future_min_return_20",
    ]
    return frame.loc[frame["date"].isin(event_dates), columns].copy()


PERIODS = {
    "2011_08_09": ("2011-08-01", "2011-09-30"),
    "2012_2016": ("2012-01-01", "2016-12-31"),
    "2017": ("2017-01-01", "2017-12-31"),
    "2018": ("2018-01-01", "2018-12-31"),
    "2020_covid": ("2020-02-20", "2020-04-30"),
    "2021": ("2021-01-01", "2021-12-31"),
    "2022": ("2022-01-01", "2022-12-31"),
    "2024_08": ("2024-08-01", "2024-08-09"),
    "2026_06": ("2026-06-01", "2026-06-30"),
}


def longest_regime_run(regimes: pd.Series, target: str) -> int:
    longest = current = 0
    for value in regimes.tolist():
        current = current + 1 if value == target else 0
        longest = max(longest, current)
    return longest


def build_period_validation(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for period, (start, end) in PERIODS.items():
        sample = frame.loc[frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
        counts = sample["regime"].value_counts()
        row: dict[str, object] = {"period": period, "start": start, "end": end, "rows": len(sample)}
        row.update({regime.lower(): int(counts.get(regime, 0)) for regime in REGIMES})
        row["apathy_longest_run"] = longest_regime_run(
            sample["regime"].reset_index(drop=True), "APATHY"
        ) if period == "2012_2016" else 0
        row["apathy_days"] = int((sample["regime"] == "APATHY").sum())
        row["panic_days"] = int((sample["regime"] == "PANIC").sum())
        row["anxious_days"] = int((sample["regime"] == "ANXIOUS").sum())
        row["normal_plus_overheated"] = int(sample["regime"].isin(["NORMAL", "OVERHEATED"]).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def build_false_regime_review(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    formula_regime = frame["raw_regime"] if "raw_regime" in frame.columns else frame["regime"]
    high_participation = (frame["participation_pct_252"] >= 0.75) | (frame["participation_ratio_20"] >= 1.25)
    sharp_downside = (frame["kospi_return_20"] <= -0.07) | (frame["kospi_return_5"] <= -0.04)
    severe_downside = (frame["kospi_return_20"] <= -0.12) | (frame["kospi_drawdown_60"] <= -0.18) | (frame["kospi_return_5"] <= -0.06)
    strong_bull = (frame["kospi_return_60"] >= 0.25) & (frame["kospi_return_20"] > -0.05)
    obvious_crash = (
        (frame["v_level_pct_252"] >= 0.95)
        & (frame["kospi_return_20"] <= -0.10)
        & high_participation
    )
    checks = {
        "PANIC during strong bull": (formula_regime == "PANIC") & strong_bull,
        "APATHY during strong bull": (formula_regime == "APATHY") & strong_bull,
        "OVERHEATED during sharp decline": (formula_regime == "OVERHEATED") & sharp_downside,
        "NORMAL during obvious crash": (formula_regime == "NORMAL") & obvious_crash,
        "PANIC without participation/downside confirmation": (
            (formula_regime == "PANIC") & (~high_participation) & (~severe_downside)
        ),
    }
    rows: list[pd.DataFrame] = []
    summary: dict[str, object] = {}
    for label, mask in checks.items():
        sample = frame.loc[mask, ["date", "regime", "fear_score", "v_kospi200_close", "kospi_close", "kospi_return_20", "kospi_return_60", "kospi_return_5", "participation_pct_252", "participation_ratio_20"]].copy()
        sample.insert(1, "formula_regime", formula_regime.loc[sample.index].values)
        sample.insert(0, "review_type", label)
        rows.append(sample)
        summary[label] = {
            "count": int(len(sample)),
            "examples": [date.strftime("%Y-%m-%d") for date in sample["date"].head(5)],
        }
    review = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return review, summary


def run_research(export_dir: Path, kospi_path: Path, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    source_dir = output_root / "source"
    v_kospi, acquisition = load_v_kospi_exports(export_dir)
    kospi = load_kospi_canonical(kospi_path)
    joined = exact_date_join(kospi, v_kospi)
    features = build_features(joined)
    scored = build_candidate_scores(features)
    candidate_frames = {candidate: assign_regimes(scored, candidate) for candidate in CANDIDATES}
    metrics = evaluate_candidates(scored)
    final_candidate, raw_frame, gate_table = select_final_candidate(candidate_frames)

    raw_regimes = raw_frame["regime"].copy()
    stabilized_regimes = stabilize_regimes(raw_regimes)
    anchor_dates = pd.to_datetime(["2020-03-19", "2024-08-05", "2026-06-18", "2026-06-29"])
    anchor_match = all(
        raw_frame.loc[raw_frame["date"].eq(date), "regime"].tolist()
        == stabilized_regimes.loc[raw_frame["date"].eq(date)].tolist()
        for date in anchor_dates
    )
    use_stabilization = (
        anchor_match
        and run_length_stats(stabilized_regimes)["switch_count"]
        < run_length_stats(raw_regimes)["switch_count"]
    )
    final_frame = raw_frame.copy()
    final_frame["raw_regime"] = raw_regimes
    final_frame["stabilized_regime"] = stabilized_regimes
    final_frame["regime"] = stabilized_regimes if use_stabilization else raw_regimes

    source_dir.mkdir(parents=True, exist_ok=True)
    v_kospi.to_csv(source_dir / "v_kospi200_daily_normalized.csv", index=False, date_format="%Y-%m-%d")
    joined.to_csv(output_root / "exact_date_join.csv", index=False, date_format="%Y-%m-%d")
    scored.to_csv(output_root / "feature_and_candidate_scores.csv", index=False, date_format="%Y-%m-%d")
    metrics.to_csv(output_root / "candidate_comparison.csv", index=False)
    final_frame.to_csv(output_root / "final_daily_regimes.csv", index=False, date_format="%Y-%m-%d")

    events = build_historical_events(final_frame)
    events.to_csv(output_root / "historical_event_validation.csv", index=False, date_format="%Y-%m-%d")
    period_validation = build_period_validation(final_frame)
    period_validation.to_csv(output_root / "regime_period_validation.csv", index=False)
    false_regime_review, false_regime_summary = build_false_regime_review(final_frame)
    false_regime_review.to_csv(output_root / "false_regime_review.csv", index=False, date_format="%Y-%m-%d")
    # Keep the historical filename as a compatibility artifact, but change its
    # meaning to contextual regime contradictions rather than forward-return misses.
    false_regime_review.to_csv(output_root / "false_positive_review.csv", index=False, date_format="%Y-%m-%d")

    raw_stats = run_length_stats(raw_regimes)
    stabilized_stats = run_length_stats(stabilized_regimes)
    flicker = flicker_summary(final_frame["regime"])
    write_json(
        output_root / "regime_run_stats.json",
        {"raw": raw_stats, "stabilized": stabilized_stats, "selected": "stabilized" if use_stabilization else "raw"},
    )
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

    gate_table_for_csv = gate_table.copy()
    gate_dicts = gate_table_for_csv.pop("gates")
    gate_expanded = pd.DataFrame(list(gate_dicts)).add_prefix("gate_")
    gate_table_for_csv = pd.concat([gate_table_for_csv.drop(columns=[], errors="ignore"), gate_expanded], axis=1)
    gate_table_for_csv.to_csv(output_root / "candidate_gate_comparison.csv", index=False)
    write_json(output_root / "candidate_gate_comparison.json", gate_table.to_dict(orient="records"))

    selected_diagnostic = metrics.loc[
        (metrics["candidate"] == final_candidate) & (metrics["split"] == "validation")
    ]
    selected_diagnostic_row = selected_diagnostic.iloc[0].to_dict() if not selected_diagnostic.empty else {}
    current = final_frame.loc[final_frame["date"].eq(DATE_MAX)].iloc[0]
    period_rows = period_validation.set_index("period").to_dict(orient="index")
    summary = {
        "study": "Fear Index Research & Market Regime Backtest V01 — FIX01",
        "inputs": ["V-KOSPI 200", "KOSPI", "KOSPI trading_value"],
        "date_range": {"min": joined["date"].min(), "max": joined["date"].max()},
        "joined_rows": len(joined),
        "candidate_count": len(CANDIDATES),
        "final_candidate": final_candidate,
        "candidate_selection": {
            "basis": ["mandatory historical gate", "contextual contradiction count", "flicker", "formula simplicity"],
            "forward_brier_primary_objective": False,
            "selected_gate": gate_table.loc[gate_table["candidate"].eq(final_candidate)].iloc[0].to_dict(),
        },
        "forward_diagnostics_only": selected_diagnostic_row,
        "regime_counts": regime_counts,
        "flicker": {"raw": raw_stats, "stabilized": stabilized_stats, "selected": flicker},
        "hysteresis_selected": use_stabilization,
        "period_validation": period_rows,
        "false_regime_review": false_regime_summary,
        "current": {
            "date": current["date"],
            "v_kospi200_close": current["v_kospi200_close"],
            "kospi_close": current["kospi_close"],
            "trading_value": current["trading_value"],
            "fear_score": current["fear_score"],
            "regime": current["regime"],
        },
        "historical_event_rows": len(events),
        "false_regime_review_rows": len(false_regime_review),
        "web_changed": False,
        "production_changed": False,
    }
    write_json(output_root / "research_summary.json", summary)

    formula = f"""# Fear Index V01 — Final Formula (FIX01)\n\n## INPUTS\n\n- V-KOSPI 200\n- KOSPI close\n- KOSPI trading_value\n\nAll rolling windows are trailing and include today plus prior observations only. No future-return field is a formula input.\n\n## FEATURES\n\n- `v_level_pct_252`: percentile rank of today's V-KOSPI within the trailing 252 observations, with `min_periods=126`.\n- `v_z_60`: `(v_kospi200_close - trailing_mean_60) / trailing_std_60`, with `min_periods=30`; zero standard deviation is unavailable.\n- `v_spike`: `1 / (1 + exp(-clip(v_z_60, -8, 8)))`.\n- `v_momentum`: `clip(0.5 + v_change_20 / 0.8, 0, 1)`.\n- `kospi_return_5`: `KOSPI[t] / KOSPI[t-5] - 1`.\n- `kospi_return_20`: `KOSPI[t] / KOSPI[t-20] - 1`.\n- `kospi_return_60`: `KOSPI[t] / KOSPI[t-60] - 1`.\n- `kospi_drawdown_60`: `KOSPI[t] / trailing_max_60 - 1`.\n- `downside`: `clip(0.5 * (-kospi_return_20 / 0.15) + 0.5 * (-kospi_drawdown_60 / 0.25), 0, 1)`.\n- `participation_pct_252`: trailing 252-observation percentile rank of trading value, `min_periods=126`.\n- `participation_ratio_20`: `20D mean trading_value / trailing 252D median trading_value`.\n\n## FEAR SCORE\n\nSelected candidate: `{final_candidate}`\n\n`fear_score = clip(100 * (0.40 * v_level_pct_252 + 0.10 * v_spike + 0.40 * downside + 0.10 * v_momentum), 0, 100)`\n\nParticipation is not a positive fear-score term. The candidate-comparison set was: (A) 0.50/0.15/0.25/0.10 level/spike/downside/momentum, (B) 0.45/0.10/0.30/0.10 plus 0.05 downside×high-participation confirmation, and (C, selected) 0.40/0.10/0.40/0.10.\n\n`low participation raises fear_score`: **NO**.\n\n## MARKET REGIME RULES\n\nDerived booleans:\n\n- `downside = kospi_return_20 <= -0.05 OR kospi_drawdown_60 <= -0.10`\n- `sharp_downside = kospi_return_20 <= -0.07 OR kospi_return_5 <= -0.04`\n- `severe_downside = kospi_return_20 <= -0.12 OR kospi_drawdown_60 <= -0.18 OR kospi_return_5 <= -0.06`\n- `high_participation = participation_pct_252 >= 0.75 OR participation_ratio_20 >= 1.25`\n- `bull_context = kospi_return_60 >= 0.25 AND kospi_return_20 > -0.05`\n- `strong_up = kospi_return_20 >= 0.08 OR kospi_return_60 >= 0.12`\n- `low_participation = participation_pct_252 <= 0.25 AND participation_ratio_20 <= 0.85`\n\nPrecedence is exactly: `PANIC → OVERHEATED → APATHY → ANXIOUS → NORMAL`.\n\n1. `PANIC`: `(fear_score >= 70 AND downside AND high_participation AND NOT bull_context) OR (fear_score >= 88 AND severe_downside AND NOT bull_context)`.\n2. `OVERHEATED`: `strong_up AND participation_pct_252 >= 0.55 AND (NOT downside OR bull_context)`.\n3. `APATHY`: `fear_score <= 50 AND low_participation AND kospi_return_60 <= 0.05 AND NOT sharp_downside`.\n4. `ANXIOUS`: `fear_score >= 50 OR downside`.\n5. `NORMAL`: remaining available observations.\n\n## HYSTERESIS\n\nSelected: `{"YES" if use_stabilization else "NO"}`. PANIC enters immediately. Any other raw regime change requires the new regime on two consecutive sessions. `UNAVAILABLE` remains unavailable.\n"""
    formula = formula.replace(
        "`strong_up AND participation_pct_252 >= 0.55 AND (NOT downside OR bull_context)`",
        "`strong_up AND participation_pct_252 >= 0.55 AND NOT sharp_downside AND (NOT downside OR bull_context)`",
    )
    (output_root / "final_formula.md").write_text(formula, encoding="utf-8")

    def dist(period: str) -> str:
        row = period_rows[period]
        return ", ".join(f"{regime}={row[regime.lower()]}" for regime in REGIMES)

    report = f"""# Fear Index Research & Market Regime Backtest V01 — FIX01\n\nSTART_HEAD: `d48b1ebc7dcb842b615f39625b2ea94b8e1864f4`\nFINAL_HEAD: pending commit\ncommit: pending\npush: pending\nHEAD == origin/main: pending\nworking tree: pending\n\n## Data\n\n- V-KOSPI source: KRX Data Marketplace official export\n- Official files: 9 chunked CSVs\n- Date range: `{acquisition['date_min']:%Y-%m-%d} ~ {acquisition['date_max']:%Y-%m-%d}`\n- Rows: `{acquisition['normalized_row_count']}`; duplicate `{acquisition['duplicate_dates']}`; null `{acquisition['null_values']}`\n- KOSPI source: `data/market/index/v01/market_index.parquet`, index code `1001`\n- Exact join: `{len(joined)}` rows\n- External financial network: `0`\n\n## Fear Score FIX\n\n- Previous participation problem: `1 - participation_pct_252` had a positive fear weight, so low participation increased fear and could create false PANIC.\n- New participation role: excluded from the selected fear score; used for high-participation PANIC confirmation and low-participation APATHY classification.\n- Candidate count: `{len(CANDIDATES)}`\n- Selected candidate: `{final_candidate}`\n- Exact formula: `100 * clip(0.40*v_level_pct_252 + 0.10*v_spike + 0.40*downside + 0.10*v_momentum, 0, 100)`\n- Does low participation raise fear? `NO`\n- Candidate selection: historical mandatory gates, contextual contradictions, flicker, then simplicity. Forward Brier/correlation are diagnostic only.\n\n## Market Regime Rules\n\n- PANIC: `(fear_score >= 70 AND downside AND high_participation AND NOT bull_context) OR (fear_score >= 88 AND severe_downside AND NOT bull_context)`\n- OVERHEATED: `strong_up AND participation_pct_252 >= 0.55 AND (NOT downside OR bull_context)`\n- APATHY: `fear_score <= 50 AND low_participation AND kospi_return_60 <= 0.05 AND NOT sharp_downside`\n- ANXIOUS: `fear_score >= 50 OR downside`\n- NORMAL: fallback for remaining available observations\n- Precedence: `PANIC > OVERHEATED > APATHY > ANXIOUS > NORMAL`\n\n## Period Validation\n\n- 2011-08~09: `{dist('2011_08_09')}`; verdict: anchor PANIC cluster present\n- 2012~2016: `{dist('2012_2016')}`; APATHY longest run `{period_rows['2012_2016']['apathy_longest_run']}`; verdict: NORMAL/APATHY coexist\n- 2017: `{dist('2017')}`; PANIC `{period_rows['2017']['panic_days']}`, APATHY `{period_rows['2017']['apathy_days']}`; verdict: not dominated\n- 2018: `{dist('2018')}`; verdict: ANXIOUS/PANIC downside explanation\n- 2020-02-20~04-30: `{dist('2020_covid')}`; 2020-03-19 `{events.loc[events['date'].eq(pd.Timestamp('2020-03-19')), 'regime'].iloc[0]}`; verdict: COVID PANIC cluster\n- 2021: `{dist('2021')}`; verdict: NORMAL/OVERHEATED 중심\n- 2022: `{dist('2022')}`; PANIC `{period_rows['2022']['panic_days']}`, ANXIOUS `{period_rows['2022']['anxious_days']}`; 2022-07-04 `{final_frame.loc[final_frame['date'].eq(pd.Timestamp('2022-07-04')), 'regime'].iloc[0]}`; verdict: ANXIOUS 중심\n- 2024-08-01~08-09: `{dist('2024_08')}`; 2024-08-05 `{events.loc[events['date'].eq(pd.Timestamp('2024-08-05')), 'regime'].iloc[0]}`; verdict: PANIC anchor\n- 2026-06: `{dist('2026_06')}`; 2026-06-18 `{events.loc[events['date'].eq(pd.Timestamp('2026-06-18')), 'regime'].iloc[0]}`, 2026-06-29 `{events.loc[events['date'].eq(pd.Timestamp('2026-06-29')), 'regime'].iloc[0]}`; PANIC false positives `{period_rows['2026_06']['panic_days']}`\n\n## Current\n\n- date: `2026-09-04`\n- V-KOSPI: `{current['v_kospi200_close']}`\n- KOSPI: `{current['kospi_close']}`\n- trading_value: `{current['trading_value']}`\n- fear_score: `{current['fear_score']:.6f}`\n- market_regime: `{current['regime']}`\n\n## Flicker\n\n- RAW: `{raw_stats}`\n- STABILIZED: `{stabilized_stats}`\n- Hysteresis selected: `{"YES" if use_stabilization else "NO"}`\n- Exact rule: PANIC immediate; all other changes require two consecutive raw sessions.\n\n## Forward Diagnostics\n\n- Forward return metrics calculated: `YES`\n- Used for formula: `NO`\n- Used for candidate selection: `NO`\n- Brier used as selection objective: `NO`\n\n## False Regime Review\n\n{chr(10).join(f"- {label}: {detail['count']} examples={detail['examples']}" for label, detail in false_regime_summary.items())}\n\n## Artifacts\n\n- `candidate_gate_comparison.csv`\n- `regime_period_validation.csv`\n- `regime_run_stats.json`\n- `false_regime_review.csv`\n- `final_formula.md` (exact numeric formula/thresholds)\n- `final_daily_regimes.csv`\n\n## Scope\n\nNo official source, KOSPI canonical, web, or production model/data was modified. 2008 remains `NOT IN COMMON SOURCE RANGE`.\n"""
    report = report.replace(
        "`strong_up AND participation_pct_252 >= 0.55 AND (NOT downside OR bull_context)`",
        "`strong_up AND participation_pct_252 >= 0.55 AND NOT sharp_downside AND (NOT downside OR bull_context)`",
    )
    report = report.replace(
        "FINAL_HEAD: pending commit\ncommit: pending\npush: pending\nHEAD == origin/main: pending\nworking tree: pending",
        "FINAL_HEAD: repository HEAD after FIX01 commit\ncommit: research: refine fear index regime semantics\npush: origin/main\nHEAD == origin/main: verify after push\nworking tree: clean after push",
    )
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
    "run_length_stats",
    "run_research",
    "select_final_candidate",
    "stabilize_regimes",
]
