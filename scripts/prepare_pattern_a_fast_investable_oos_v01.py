#!/usr/bin/env python
"""Phase 13J-1: freeze a strict-PIT Investable OOS-B blind review package.

Inputs are local-only: the frozen 13J-0 active KRX sources and raw daily cache.
This script does not call a market-data client, consume outcome data for sampling,
or modify frozen Fast/Pattern A/Phase10 implementations.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

try:  # direct script execution and test module import are both supported.
    from scripts.research_pattern_a_fast_lead_time_failure import evaluate_fast_contract
except ModuleNotFoundError:  # pragma: no cover - ``python scripts/...`` path
    from research_pattern_a_fast_lead_time_failure import evaluate_fast_contract
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features

warnings.filterwarnings("ignore", category=FutureWarning)
plt.rcParams["font.family"] = ["AppleGothic", "NanumGothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


ROOT = Path(__file__).resolve().parents[1]
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
HISTORY = ROOT / "artifacts/investability/history"
GRID = HISTORY / "krx_market_cap_reference_grid_v01.csv"
PROVENANCE = HISTORY / "krx_historical_market_cap_provenance_v01.csv"
HISTORICAL_AUDIT = HISTORY / "krx_historical_market_cap_backfill_audit_v01.json"
DAILY_DIR = ROOT / "data/raw/stocks"
SCORE_CONTRACT = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT = ROOT / "artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json"
PRIOR_SOURCE = ROOT / "artifacts/pattern_a_fast/ground_truth/pattern_a_fast_ground_truth_source_v01.csv"
ANCHORS = ROOT / "artifacts/pattern_a_fast/human_anchors/pattern_a_fast_human_positive_anchor_v01.csv"

MANIFEST = OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
ASSETS = OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_investable_oos_preregistration_seal_v01.json"
STAGE_DIR = OOS / "charts/stage_blind"
OUTCOME_DIR = OOS / "charts/outcome_blind"

BASE_SHA = "aae2db99beebcbfe518fd614e2ab650dc432e569"
FAST_FROZEN_SHA = "2da3fc36744b27ec13edae3f690df72c796906e5"
PATTERN_A_FROZEN_SHA = "05d03e16501adbca889488294aaaaa0bd84005de"
SELECTION_SEED = "PATTERN_A_FAST_INVESTABLE_OOS_B_V01"
REVIEW_ORDER_SEED = "PATTERN_A_FAST_INVESTABLE_OOS_B_REVIEW_ORDER_V01"
STRATA = {
    "ADVANCED_CANDIDATE": 10,
    "SETUP_CANDIDATE": 10,
    "WATCH_HIGH_SCORE": 8,
    "EXTENDED_CONTROL": 4,
    "WATCH_LOW_SCORE_CONTROL": 4,
}
HARD_MINIMUMS = {
    "ADVANCED_CANDIDATE": 6,
    "SETUP_CANDIDATE": 6,
    "WATCH_HIGH_SCORE": 5,
    "EXTENDED_CONTROL": 3,
    "WATCH_LOW_SCORE_CONTROL": 3,
}
STAGE_ORDER = ["WATCH", "SETUP", "TRIGGER", "TREND", "EXTENDED"]
FROZEN_SELECTION_SHA256 = "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825"
FROZEN_HUMAN_REVIEW_SHA256 = "25d5f524517c7eabe6ab232e5ba97964ff00aae06f59a4362ba49cb5f78c99d1"
FROZEN_EVALUATION_PROTOCOL_SHA256 = "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _iso(value: object) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _number(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def frozen_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict, dict, dict]:
    grid = pd.read_csv(GRID, dtype=str, keep_default_na=False)
    provenance = pd.read_csv(PROVENANCE, dtype=str, keep_default_na=False).fillna("")
    audit = json.loads(HISTORICAL_AUDIT.read_text(encoding="utf-8"))
    score = json.loads(SCORE_CONTRACT.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT.read_text(encoding="utf-8"))
    active = provenance[provenance.reference_status.eq("ACTIVE_REFERENCE")]
    if audit["status"] != "HISTORICAL_MARKET_CAP_PIT_READY" or audit["reference_date_semantics"] != "BUILD_HISTORICAL_SNAPSHOT_COMPLETED_W_FRI":
        raise RuntimeError("HISTORICAL_INVESTABILITY_INPUT_INTEGRITY_FAIL")
    if len(grid) != len(active) != 22 or not (grid.completed_weekly_reference_date == grid.effective_date).all():
        raise RuntimeError("HISTORICAL_INVESTABILITY_INPUT_INTEGRITY_FAIL")
    if set(active.source_file) != set(grid.source_file) or (active.source_provider != "KRX").any():
        raise RuntimeError("HISTORICAL_INVESTABILITY_INPUT_INTEGRITY_FAIL")
    if score["selected_research_prototype"] != "HIERARCHICAL_V01" or stage["stage_semantics"] != STAGE_ORDER:
        raise RuntimeError("Frozen Fast contract mismatch")
    return grid, active, audit, score, stage


def firewalls() -> tuple[set[str], set[str]]:
    prior = pd.read_csv(PRIOR_SOURCE, dtype={"ticker": str}, keep_default_na=False)
    anchors = pd.read_csv(ANCHORS, dtype={"ticker": str}, keep_default_na=False)
    if len(prior) != 60:
        raise RuntimeError("Prior 60 firewall source does not contain 60 historical rows")
    return set(prior.ticker.str.zfill(6)), set(anchors.ticker.str.zfill(6))


def _daily(ticker: str, cache: dict[str, pd.DataFrame | None]) -> pd.DataFrame | None:
    if ticker not in cache:
        path = DAILY_DIR / f"{ticker}.parquet"
        cache[ticker] = pd.read_parquet(path).sort_index() if path.is_file() else None
    return cache[ticker]


def fast_point(ticker: str, name: str, daily: pd.DataFrame, reference_date: str, score: dict, stage: dict) -> dict[str, Any]:
    """Evaluate only frozen Fast inputs at the completed reference, not Pattern A."""
    reference = pd.Timestamp(reference_date)
    sliced = daily[daily.index <= reference]
    if sliced.empty or sliced.index.max().normalize() != reference:
        raise ValueError(f"incomplete reference date: {ticker} {reference_date}")
    weekly = to_weekly(sliced)
    if weekly.empty or weekly.index[-1].normalize() != reference:
        raise ValueError(f"reference is not completed W-FRI: {ticker} {reference_date}")
    monthly = to_monthly(sliced)
    if not monthly.empty and reference < reference + pd.offsets.MonthEnd(0):
        monthly = monthly.iloc[:-1]
    features: dict[str, float] = {}
    features.update(compute_monthly_regime_features(monthly))
    features.update(compute_weekly_trigger_features(weekly))
    features.update(compute_daily_timing_features(sliced))
    fast = evaluate_fast_contract(features, score, stage)
    return {
        **fast,
        "effective_as_of": _iso(sliced.index.max()),
        "monthly_as_of": _iso(monthly.index.max()) if not monthly.empty else "",
        "weekly_as_of": _iso(weekly.index.max()),
    }


def collect_candidates() -> tuple[pd.DataFrame, list[dict[str, Any]], dict]:
    grid, active, audit, score, stage = frozen_inputs()
    prior_tickers, anchor_tickers = firewalls()
    active_by_file = active.set_index("source_file")
    cache: dict[str, pd.DataFrame | None] = {}
    rows: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    for reference in grid.itertuples(index=False):
        source = ROOT / reference.source_file
        meta = active_by_file.loc[reference.source_file]
        if sha256(source) != meta.sha256 or sha256(source) != reference.sha256:
            raise RuntimeError("HISTORICAL_INVESTABILITY_INPUT_INTEGRITY_FAIL")
        snapshot = pd.read_csv(HISTORY / "normalized" / source.name, dtype={"ticker": str})
        snapshot.ticker = snapshot.ticker.str.zfill(6)
        reference_date = _iso(reference.completed_weekly_reference_date)
        universe = snapshot[snapshot.market.isin(["KOSPI", "KOSDAQ"])].copy()
        local = {"reference_date": reference_date, "source_file": reference.source_file, "universe_scope_count": int(len(universe)), "market_cap_pass_count": 0, "reference_data_insufficient_count": 0, "liquidity_fail_count": 0, "prior_or_anchor_excluded_count": 0, "investable_count": 0, "fast_ready_count": 0, "watch_score_population_count": 0}
        for item in universe.itertuples(index=False):
            ticker = str(item.ticker).zfill(6)
            if float(item.market_cap) < MIN_MARKET_CAP_KRW:
                continue
            local["market_cap_pass_count"] += 1
            daily = _daily(ticker, cache)
            invest = evaluate_investability(ticker, reference_date, daily, float(item.market_cap), reference_date)
            if invest.status == InvestabilityStatus.DATA_UNAVAILABLE:
                local["reference_data_insufficient_count"] += 1
                continue
            if invest.status == InvestabilityStatus.FILTERED_LIQUIDITY:
                local["liquidity_fail_count"] += 1
                continue
            if invest.status != InvestabilityStatus.INVESTABLE:
                continue
            local["investable_count"] += 1
            if ticker in prior_tickers or ticker in anchor_tickers:
                local["prior_or_anchor_excluded_count"] += 1
                continue
            try:
                fast = fast_point(ticker, str(item.name), daily, reference_date, score, stage)
            except (ValueError, KeyError):
                continue
            if fast["fast_machine_stage_status"] != "READY":
                continue
            local["fast_ready_count"] += 1
            row = {
                "ticker": ticker, "name": str(item.name), "historical_market": str(item.market),
                "calendar_candidate_date": _iso(reference.calendar_candidate_date),
                "completed_weekly_reference_date": reference_date,
                "market_cap_at_reference": int(item.market_cap),
                "avg_trading_value_20d_at_reference": _number(invest.avg_trading_value_20d),
                "investability_status": invest.status.value,
                "machine_stage": fast["fast_machine_stage"], "machine_stage_status": fast["fast_machine_stage_status"],
                "fast_score": _number(fast["fast_score"]), "fast_score_status": fast["fast_score_status"],
                "watch_score_percentile": None, "reference_quarter": reference.reference_quarter,
                "prior_60_ticker_overlap": False, "human_positive_anchor_overlap": False,
                "reference_source_file": reference.source_file, "reference_source_sha256": reference.sha256,
                "effective_as_of": fast["effective_as_of"], "monthly_as_of": fast["monthly_as_of"], "weekly_as_of": fast["weekly_as_of"],
            }
            rows.append(row)
        counts.append(local)
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        raise RuntimeError("INSUFFICIENT_INVESTABLE_OOS_POOL")
    for date, group in candidates.groupby("completed_weekly_reference_date", sort=True):
        watch = group[(group.machine_stage == "WATCH") & group.fast_score_status.isin(["READY", "PARTIAL"]) & group.fast_score.notna()].copy()
        counts[[i for i, item in enumerate(counts) if item["reference_date"] == date][0]]["watch_score_population_count"] = len(watch)
        # Same-date ordinal percentile: sort score ascending, then ticker ascending to resolve ties.
        watch = watch.sort_values(["fast_score", "ticker"], kind="mergesort").reset_index()
        watch["percentile"] = (watch.index + 1) / len(watch) * 100 if len(watch) else []
        for item in watch.itertuples(index=False):
            candidates.at[item.index, "watch_score_percentile"] = round(float(item.percentile), 6)
    return candidates, counts, {"audit": audit, "prior_tickers": prior_tickers, "anchor_tickers": anchor_tickers}


def assign_strata(candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for record in candidates.to_dict(orient="records"):
        stage, status, percentile = record["machine_stage"], record["fast_score_status"], record["watch_score_percentile"]
        stratum = None
        if stage in {"TRIGGER", "TREND"}:
            stratum = "ADVANCED_CANDIDATE"
        elif stage == "SETUP":
            stratum = "SETUP_CANDIDATE"
        elif stage == "EXTENDED":
            stratum = "EXTENDED_CONTROL"
        elif stage == "WATCH" and status in {"READY", "PARTIAL"} and percentile is not None and percentile >= 75:
            stratum = "WATCH_HIGH_SCORE"
        elif stage == "WATCH" and status in {"READY", "PARTIAL"} and percentile is not None and percentile <= 25:
            stratum = "WATCH_LOW_SCORE_CONTROL"
        if stratum:
            record["sampling_stratum"] = stratum
            record["selection_hash"] = stable_hash(SELECTION_SEED, stratum, record["ticker"], record["completed_weekly_reference_date"])
            rows.append(record)
    pool = pd.DataFrame(rows)
    if pool.empty:
        raise RuntimeError("INSUFFICIENT_INVESTABLE_OOS_POOL")
    # One ticker / one sample: retain the globally smallest predeclared stable hash.
    return pool.sort_values(["ticker", "selection_hash"], kind="mergesort").drop_duplicates("ticker", keep="first").reset_index(drop=True)


def select_samples(pool: pd.DataFrame) -> pd.DataFrame:
    available = {stratum: frame.sort_values("selection_hash", kind="mergesort").to_dict(orient="records") for stratum, frame in pool.groupby("sampling_stratum", sort=False)}
    if any(len(available.get(stratum, [])) < minimum for stratum, minimum in HARD_MINIMUMS.items()):
        raise RuntimeError("INSUFFICIENT_INVESTABLE_OOS_POOL")
    selected: list[dict[str, Any]] = []
    per_date: Counter[str] = Counter()
    per_market: Counter[str] = Counter()
    max_market = int(np.floor(2 * sum(STRATA.values()) / 3))
    for stratum, target in STRATA.items():
        for record in available.get(stratum, []):
            if sum(1 for row in selected if row["sampling_stratum"] == stratum) >= target:
                break
            if per_date[record["completed_weekly_reference_date"]] >= 3 or per_market[record["historical_market"]] >= max_market:
                continue
            selected.append(record)
            per_date[record["completed_weekly_reference_date"]] += 1
            per_market[record["historical_market"]] += 1
    selected_df = pd.DataFrame(selected)
    actual = selected_df.sampling_stratum.value_counts().to_dict() if not selected_df.empty else {}
    if len(selected_df) < 30 or any(int(actual.get(stratum, 0)) < minimum for stratum, minimum in HARD_MINIMUMS.items()):
        raise RuntimeError("INSUFFICIENT_INVESTABLE_OOS_POOL")
    if selected_df.ticker.nunique() != len(selected_df) or selected_df.completed_weekly_reference_date.value_counts().max() > 3:
        raise RuntimeError("Selection uniqueness/diversity failure")
    if selected_df.historical_market.value_counts().max() > int(np.floor(2 * len(selected_df) / 3)) or selected_df.reference_quarter.nunique() < 10:
        raise RuntimeError("INSUFFICIENT_INVESTABLE_OOS_POOL")
    selected_df = selected_df.sort_values("selection_hash", kind="mergesort").reset_index(drop=True)
    selected_df.insert(0, "sample_id", [f"INV_OOS_B_{index:03d}" for index in range(1, len(selected_df) + 1)])
    selected_df["outcome_review_end"] = selected_df.apply(lambda row: outcome_end(row.ticker, row.completed_weekly_reference_date), axis=1)
    selected_df["selection_seed"] = SELECTION_SEED
    selected_df["human_review_exposed"] = False
    return selected_df


def outcome_end(ticker: str, reference_date: str) -> str:
    daily = pd.read_parquet(DAILY_DIR / f"{ticker}.parquet").sort_index()
    completed = [date for date in to_weekly(daily).index if date in daily.index and date >= pd.Timestamp(reference_date)]
    if len(completed) <= 52:
        return _iso(daily.index.max())
    return _iso(completed[52])


def stage_chart_title(review_order: int, row: pd.Series, reference: pd.Timestamp) -> str:
    return f"OOS-B Review {review_order:03d} | {row['ticker']} {row['name']} | as of {reference.date()}"


def outcome_chart_title(review_order: int, row: pd.Series) -> str:
    return f"OOS-B Outcome Review {review_order:03d} | {row['ticker']} {row['name']}"


def plot(frame: pd.DataFrame, path: Path, title: str, reference: pd.Timestamp | None) -> None:
    fig, (price, volume) = plt.subplots(2, 1, figsize=(8, 5), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    price.plot(frame.index, frame.close, color="#2c6fbb", linewidth=1.1)
    volume.bar(frame.index, frame.volume, color="#8a8a8a", width=3.5)
    if reference is not None:
        price.axvline(reference, color="#c0392b", linestyle="--", linewidth=1)
        volume.axvline(reference, color="#c0392b", linestyle="--", linewidth=1)
    price.set_title(title, fontsize=9)
    price.set_ylabel("close")
    volume.set_ylabel("volume")
    fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(path, dpi=110, metadata={"Title": title}); plt.close(fig)


def frozen_package() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load the already sealed samples; a mapping correction must never resample them."""
    expected = {
        MANIFEST: FROZEN_SELECTION_SHA256,
        REVIEW: FROZEN_HUMAN_REVIEW_SHA256,
        PROTOCOL: FROZEN_EVALUATION_PROTOCOL_SHA256,
    }
    for path, expected_hash in expected.items():
        if sha256(path) != expected_hash:
            if path == MANIFEST:
                raise RuntimeError("INVESTABLE_OOS_SAMPLE_FREEZE_INTEGRITY_FAIL")
            raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    samples = pd.read_csv(MANIFEST, dtype={"ticker": str}, keep_default_na=False)
    review = pd.read_csv(REVIEW, dtype={"ticker": str}, keep_default_na=False)
    if len(samples) != 36 or samples.sample_id.nunique() != 36:
        raise RuntimeError("INVESTABLE_OOS_SAMPLE_FREEZE_INTEGRITY_FAIL")
    if len(review) != 36 or review.sample_id.nunique() != 36 or review.review_order.astype(int).tolist() != list(range(1, 37)):
        raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    return samples, review, json.loads(SEAL.read_text(encoding="utf-8"))


def ordered_review_samples(samples: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    """The sealed Human review mapping is the sole numbering source for every asset."""
    review_mapping = review[["review_order", "sample_id"]].copy()
    review_mapping["review_order"] = review_mapping.review_order.astype(int)
    mapped = samples.merge(review_mapping, on="sample_id", how="inner", validate="one_to_one")
    if len(mapped) != len(samples) or mapped.review_order.nunique() != len(samples):
        raise RuntimeError("INVESTABLE_OOS_BLIND_ASSET_MAPPING_FAIL")
    return mapped.sort_values("review_order", kind="mergesort").reset_index(drop=True)


def review_order_sample_mapping_sha256(review: pd.DataFrame) -> str:
    ordered = review[["review_order", "sample_id"]].copy()
    ordered["review_order"] = ordered.review_order.astype(int)
    payload = "\n".join(f"{row.review_order}|{row.sample_id}" for row in ordered.sort_values("review_order").itertuples(index=False))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_assets(samples: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    for directory in (STAGE_DIR, OUTCOME_DIR):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    rows = []
    for _, row in ordered_review_samples(samples, review).iterrows():
        review_order = int(row["review_order"])
        daily = pd.read_parquet(DAILY_DIR / f"{row['ticker']}.parquet").sort_index()
        reference, end = pd.Timestamp(row["completed_weekly_reference_date"]), pd.Timestamp(row["outcome_review_end"])
        stage_frames = {"MONTHLY_STAGE_BLIND": to_monthly(daily[daily.index <= reference]), "WEEKLY_STAGE_BLIND": to_weekly(daily[daily.index <= reference]), "DAILY_STAGE_BLIND": daily[daily.index <= reference]}
        for asset_type, frame in stage_frames.items():
            frame = frame[frame.index <= reference]
            path = STAGE_DIR / f"{review_order:03d}_{row['sample_id']}_{asset_type.split('_')[0].lower()}.png"
            plot(frame, path, stage_chart_title(review_order, row, reference), reference if asset_type == "DAILY_STAGE_BLIND" else None)
            rows.append({"review_order": review_order, "sample_id": row["sample_id"], "asset_type": asset_type, "file_path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "data_start": _iso(frame.index.min()), "data_end": _iso(frame.index.max()), "reference_date": _iso(reference), "human_exposure_phase": "PASS_A"})
        outcome = daily[(daily.index >= reference) & (daily.index <= end)]
        path = OUTCOME_DIR / f"{review_order:03d}_{row['sample_id']}_outcome.png"
        plot(outcome, path, outcome_chart_title(review_order, row), reference)
        rows.append({"review_order": review_order, "sample_id": row["sample_id"], "asset_type": "OUTCOME_BLIND", "file_path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "data_start": _iso(outcome.index.min()), "data_end": _iso(outcome.index.max()), "reference_date": _iso(reference), "human_exposure_phase": "PASS_B_AFTER_STAGE_FREEZE"})
    return pd.DataFrame(rows)


def review_sheet(samples: pd.DataFrame) -> pd.DataFrame:
    ordered = samples.assign(_review_hash=samples.sample_id.map(lambda sample_id: stable_hash(REVIEW_ORDER_SEED, sample_id))).sort_values(["_review_hash", "sample_id"], kind="mergesort").reset_index(drop=True)
    review = ordered[["sample_id", "ticker", "name", "historical_market", "completed_weekly_reference_date", "outcome_review_end"]].copy()
    review.insert(0, "review_order", range(1, len(review) + 1))
    review = review.rename(columns={"completed_weekly_reference_date": "reference_date"})
    review["human_stage"] = "UNLABELED"; review["human_stage_confidence"] = "UNLABELED"; review["human_trigger_event_observed"] = "UNLABELED"; review["human_trigger_event_date"] = ""
    review["stage_review_status"] = "PENDING"; review["human_outcome_label"] = "UNLABELED"; review["human_outcome_confidence"] = "UNLABELED"; review["outcome_review_status"] = "PENDING"
    return review


def protocol() -> dict[str, Any]:
    return {"version": "PATTERN_A_FAST_INVESTABLE_OOS_B_EVALUATION_PROTOCOL_V01", "phase": "13J-4_PREREGISTERED", "claim_boundary": "retrospective historical OOS with preregistered blind human review", "fast_contract": "HIERARCHICAL_V01", "fast_contract_sha": FAST_FROZEN_SHA, "pattern_a_frozen_sha": PATTERN_A_FROZEN_SHA, "human_stage_taxonomy": STAGE_ORDER, "human_stage_confidence": ["LOW", "MEDIUM", "HIGH"], "human_outcome_taxonomy": ["GOOD_TRIGGER", "BORDERLINE_TRIGGER", "FALSE_TRIGGER", "TOO_EARLY", "TOO_LATE", "TOO_EXTENDED", "NO_SETUP"], "primary_score_comparison": {"positive_labels": ["GOOD_TRIGGER", "BORDERLINE_TRIGGER"], "negative_labels": ["TOO_EARLY", "NO_SETUP"], "minimum_n_per_group": 5, "direction_fail_if_positive_median_lte_negative": True, "cliffs_delta_hard_threshold": None}, "secondary_score_comparisons": [["GOOD_TRIGGER", label] for label in ["NO_SETUP", "FALSE_TRIGGER", "TOO_EARLY", "TOO_EXTENDED"]], "stage_order": STAGE_ORDER, "stage_exact_match_hard_threshold": None, "lead_precedence": ["DATA_UNAVAILABLE", "SAME_WEEK", "PATTERN_A_ALREADY_ACTIVE", "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", "FAST_EARLIER_PATTERN_A_LATER", "FAST_EVENT_NO_PATTERN_A_CATCHUP"], "lead_minimum_clean_n": 3, "stage_ready_coverage_minimum": 0.80, "score_unavailable_rate_maximum": 0.20, "no_sample_replacement_after_freeze": True, "network_market_request_count": 0}


def write_correction_outputs(samples: pd.DataFrame, review: pd.DataFrame, assets: pd.DataFrame, prior_seal: dict[str, Any]) -> None:
    """Only regenerated blind assets and their seal may change in this correction."""
    if sha256(MANIFEST) != FROZEN_SELECTION_SHA256:
        raise RuntimeError("INVESTABLE_OOS_SAMPLE_FREEZE_INTEGRITY_FAIL")
    if sha256(REVIEW) != FROZEN_HUMAN_REVIEW_SHA256 or sha256(PROTOCOL) != FROZEN_EVALUATION_PROTOCOL_SHA256:
        raise RuntimeError("INVESTABLE_OOS_REVIEW_ORDER_FREEZE_INTEGRITY_FAIL")
    expected_mapping = review[["review_order", "sample_id"]].copy().sort_values("review_order", kind="mergesort").reset_index(drop=True)
    expected_mapping["review_order"] = expected_mapping.review_order.astype(int)
    asset_mapping = assets[["review_order", "sample_id"]].drop_duplicates().sort_values("review_order", kind="mergesort").reset_index(drop=True)
    asset_mapping["review_order"] = asset_mapping.review_order.astype(int)
    if not expected_mapping.equals(asset_mapping) or not (assets.groupby("review_order").size() == 4).all() or not (assets.groupby("sample_id").size() == 4).all():
        raise RuntimeError("INVESTABLE_OOS_BLIND_ASSET_MAPPING_FAIL")
    assets.to_csv(ASSETS, index=False)
    seal = prior_seal.copy()
    seal.update({
        "selection_manifest_sha256": sha256(MANIFEST),
        "human_review_sha256": sha256(REVIEW),
        "evaluation_protocol_sha256": sha256(PROTOCOL),
        "blind_asset_manifest_sha256": sha256(ASSETS),
        "stage_blind_chart_count": int((assets.human_exposure_phase == "PASS_A").sum()),
        "outcome_blind_chart_count": int((assets.human_exposure_phase == "PASS_B_AFTER_STAGE_FREEZE").sum()),
        "review_asset_mapping_status": "EXACT",
        "review_order_sample_mapping_sha256": review_order_sample_mapping_sha256(review),
        "correction": "13J-1 blind review order to chart asset mapping alignment",
        "status": "READY_FOR_BLIND_HUMAN_INVESTABLE_OOS_LABELING",
    })
    SEAL.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    samples, review, prior_seal = frozen_package()
    assets = generate_assets(samples, review)
    write_correction_outputs(samples, review, assets, prior_seal)
    print(f"READY_FOR_BLIND_HUMAN_INVESTABLE_OOS_LABELING: samples={len(samples)}, review_asset_mapping=EXACT")


if __name__ == "__main__":
    main()
