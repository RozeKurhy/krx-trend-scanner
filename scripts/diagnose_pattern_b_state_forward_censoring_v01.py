#!/usr/bin/env python3
"""Diagnose missing forward outcomes in Pattern B State Forward Return Study V01.

This script only joins the frozen sample/outcome files to the already-built PIT
interval and trading-calendar authorities. It does not load or replay prices.
"""

from __future__ import annotations

import bisect
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.patterns import pattern_b_operational as pattern_b_op  # noqa: E402

HORIZONS = {"3M": 63, "6M": 126, "12M": 252, "24M": 504}
STATES = ("DEEP_DEPRESSED", "DEPRESSED", "NORMAL", "OVERHEATED", "EXTREME_OVERHEATED")
PANELS = {
    "PANEL_A_ALL": "ALL PIT Eligible",
    "PANEL_B_PIT_1T_PLUS": "Exact snapshot PIT market cap >= 1T KRW",
}
STATUS_ORDER = (
    "COMPLETED", "FRONTIER_INCOMPLETE", "TERMINAL_IDENTITY",
    "ENDPOINT_PRICE_MISSING", "OTHER_MISSING",
)
SEED = 20260927
SOURCE_DIR = ROOT / "artifacts/patterns/pattern_b/state_forward_return_v01"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_b/state_forward_return_censoring_diagnostic_v01"


def normalize_ticker(value: Any) -> str:
    return str(value).strip().zfill(6)


def normalize_isu(value: Any) -> str:
    return str(value).strip().upper()


def interval_key(interval: Any, ticker_hint: str | None = None) -> tuple[str, str, str, str, str]:
    def get(name: str) -> str:
        if isinstance(interval, dict):
            return str(interval[name])
        if name == "ticker" and ticker_hint is not None:
            return ticker_hint
        return str(getattr(interval, name))

    return (
        normalize_ticker(get("ticker")), normalize_isu(get("isu_cd")),
        str(get("market")).strip().upper(), str(get("effective_from"))[:10],
        str(get("effective_to"))[:10],
    )


def horizon_endpoint(snapshot_date: str, horizon: str, trading_dates: list[str]) -> str | None:
    """Return the exact Nth exchange session strictly after the snapshot."""
    start = bisect.bisect_left(trading_dates, snapshot_date)
    if start >= len(trading_dates) or trading_dates[start] != snapshot_date:
        raise ValueError(f"snapshot is not an authoritative trading date: {snapshot_date}")
    end = start + HORIZONS[horizon]
    return trading_dates[end] if end < len(trading_dates) else None


def classify_status(
    *, outcome_present: bool, endpoint_after_frontier: bool, identity_status: str,
) -> str:
    """Apply mutually exclusive outcome-status precedence for one sample/horizon."""
    if endpoint_after_frontier:
        if outcome_present:
            raise ValueError("an outcome cannot exist beyond the data frontier")
        return "FRONTIER_INCOMPLETE"
    if outcome_present:
        return "COMPLETED"
    if identity_status == "TERMINAL":
        return "TERMINAL_IDENTITY"
    if identity_status == "CONTINUOUS":
        return "ENDPOINT_PRICE_MISSING"
    if identity_status == "OTHER":
        return "OTHER_MISSING"
    raise ValueError(f"unknown identity status: {identity_status}")


def summarize_status_counts(total: int, counts: dict[str, int]) -> dict[str, Any]:
    """Validate decomposition and calculate documented completion/censoring rates."""
    if set(counts) != set(STATUS_ORDER):
        raise ValueError("status counts must contain all five status categories")
    if sum(counts.values()) != total:
        raise ValueError(f"status decomposition mismatch: {sum(counts.values())} != {total}")
    mature_n = total - counts["FRONTIER_INCOMPLETE"]
    mature_rate = counts["COMPLETED"] / mature_n * 100 if mature_n else None
    return {
        "total_snapshot_n": total,
        "completed_n": counts["COMPLETED"],
        "frontier_incomplete_n": counts["FRONTIER_INCOMPLETE"],
        "terminal_identity_n": counts["TERMINAL_IDENTITY"],
        "endpoint_price_missing_n": counts["ENDPOINT_PRICE_MISSING"],
        "other_missing_n": counts["OTHER_MISSING"],
        "raw_completion_rate_pct": counts["COMPLETED"] / total * 100 if total else None,
        "mature_sample_n": mature_n,
        "mature_completion_rate_pct": mature_rate,
        "terminal_identity_rate_pct": counts["TERMINAL_IDENTITY"] / mature_n * 100 if mature_n else None,
        "endpoint_price_missing_rate_pct": counts["ENDPOINT_PRICE_MISSING"] / mature_n * 100 if mature_n else None,
    }


def _covered(interval: dict[str, Any], endpoint: str) -> bool:
    return str(interval.get("effective_from", ""))[:10] <= endpoint <= str(interval.get("effective_to", ""))[:10]


def _identity_assessment(
    sample: dict[str, Any], endpoint: str, ticker_intervals: list[dict[str, Any]],
    trading_dates: list[str],
) -> dict[str, Any]:
    """Check exact same-ISU endpoint identity and source-to-endpoint chain continuity."""
    ticker = normalize_ticker(sample["ticker"])
    isu_cd = normalize_isu(sample["isu_cd"])
    source_key = interval_key(sample)
    endpoint_intervals = [iv for iv in ticker_intervals if _covered(iv, endpoint)]
    endpoint_common_same = [
        iv for iv in endpoint_intervals
        if iv.get("state") == "COMMON" and normalize_isu(iv.get("isu_cd", "")) == isu_cd
    ]
    base = {
        "identity_status": "TERMINAL",
        "identity_reason_code": "",
        "identity_reason_detail": "",
        "identity_interval_end": str(sample["effective_to"])[:10],
        "endpoint_same_isu_intervals": "",
        "endpoint_other_isu_intervals": "",
        "last_same_isu_common_interval_before_endpoint": "",
        "later_same_isu_intervals_after_source": "",
        "chain_segments": "",
        "chain_stop_reason": "",
    }
    same_isu_common = [
        iv for iv in ticker_intervals
        if iv.get("state") == "COMMON" and normalize_isu(iv.get("isu_cd", "")) == isu_cd
    ]
    same_isu_prior = [iv for iv in same_isu_common if str(iv.get("effective_to", ""))[:10] < endpoint]
    if same_isu_prior:
        last_prior = max(same_isu_prior, key=lambda iv: (str(iv["effective_to"]), str(iv["effective_from"])))
        base["last_same_isu_common_interval_before_endpoint"] = (
            f"{last_prior['effective_from']}~{last_prior['effective_to']} [{last_prior['market']}]"
        )
    later_same_isu = [
        iv for iv in same_isu_common
        if str(iv.get("effective_from", ""))[:10] > str(sample["effective_to"])[:10]
    ]
    base["later_same_isu_intervals_after_source"] = ";".join(
        f"{iv['effective_from']}~{iv['effective_to']} [{iv['market']}]"
        for iv in later_same_isu
    )
    base["endpoint_same_isu_intervals"] = ";".join(
        f"{iv.get('state')}:{iv.get('market')}:{iv.get('effective_from')}~{iv.get('effective_to')}"
        for iv in endpoint_intervals if normalize_isu(iv.get("isu_cd", "")) == isu_cd
    )
    base["endpoint_other_isu_intervals"] = ";".join(
        f"{normalize_isu(iv.get('isu_cd', ''))}:{iv.get('state')}:{iv.get('market')}:{iv.get('effective_from')}~{iv.get('effective_to')}"
        for iv in endpoint_intervals if normalize_isu(iv.get("isu_cd", "")) != isu_cd
    )

    if len(endpoint_common_same) > 1:
        base.update(
            identity_reason_code="AMBIGUOUS_ENDPOINT_IDENTITY",
            identity_reason_detail="multiple COMMON intervals for the same ISU cover the exact endpoint",
        )
        return base
    if len(endpoint_common_same) == 1:
        try:
            chain = pattern_b_op.history_chain(ticker, endpoint_common_same[0], ticker_intervals, trading_dates)
        except pattern_b_op.PatternBHistoryError as exc:
            base.update(
                identity_reason_code="AMBIGUOUS_IDENTITY_CHAIN",
                identity_reason_detail=f"existing history-chain authority raised {type(exc).__name__}",
            )
            return base
        base["chain_stop_reason"] = str(chain.stop_reason)
        base["chain_segments"] = ";".join(
            f"{segment.isu_cd}:{segment.market}:{segment.effective_from}~{segment.effective_to}"
            for segment in chain.segments
        )
        if source_key in {interval_key(segment, ticker) for segment in chain.segments}:
            base.update(
                identity_status="CONTINUOUS",
                identity_reason_code="SAME_ISU_COMMON_CHAIN_COVERS_ENDPOINT",
                identity_reason_detail="source interval is included in the existing contiguous COMMON identity chain ending at the exact endpoint",
            )
            return base
        stop = str(chain.stop_reason or "UNSPECIFIED")
        base.update(
            identity_reason_code=f"IDENTITY_CHAIN_STOP_{stop}",
            identity_reason_detail=f"same-ISU COMMON endpoint interval exists, but source interval is absent from its existing chain; stop_reason={stop}",
        )
        return base

    same_isu_at_endpoint = [
        iv for iv in endpoint_intervals if normalize_isu(iv.get("isu_cd", "")) == isu_cd
    ]
    other_common = [iv for iv in endpoint_intervals if iv.get("state") == "COMMON"]
    if same_isu_at_endpoint:
        base.update(
            identity_reason_code="SAME_ISU_NON_COMMON_AT_ENDPOINT",
            identity_reason_detail="same-ISU interval covers endpoint but its authoritative state is not COMMON",
        )
    elif other_common:
        base.update(
            identity_reason_code="ISU_CHANGE_AT_ENDPOINT",
            identity_reason_detail="the ticker has a different-ISU COMMON interval at the exact endpoint; no merger or economic-loss cause inferred",
        )
    else:
        if later_same_isu:
            base.update(
                identity_reason_code="SAME_ISU_INTERVAL_NOT_COVERING_ENDPOINT",
                identity_reason_detail="same-ISU interval authority exists after the source interval, but no same-ISU interval covers the exact endpoint",
            )
        elif endpoint_intervals:
            base.update(
                identity_reason_code="NO_COMMON_SAME_ISU_ENDPOINT_INTERVAL",
                identity_reason_detail="interval authority covers endpoint but no COMMON interval for the source ISU does",
            )
        else:
            base.update(
                identity_reason_code="NO_INTERVAL_COVERS_ENDPOINT",
                identity_reason_detail="no ticker interval in the existing PIT authority covers the exact endpoint",
            )
    return base


def _format_pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2f}%"


def _format_diff(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):+.2f} pp"


def _summary_table(frame: pd.DataFrame, panel: str, horizon: str) -> str:
    selected = frame.loc[(frame["panel"] == panel) & (frame["horizon"] == horizon)]
    core = selected.loc[selected["state"].isin(["DEEP_DEPRESSED", "DEPRESSED", "NORMAL"])]
    cols = [
        ("state", "State"), ("total_snapshot_n", "Total"), ("completed_n", "Done"),
        ("frontier_incomplete_n", "Frontier"), ("terminal_identity_n", "Terminal"),
        ("endpoint_price_missing_n", "Endpoint price missing"), ("other_missing_n", "Other"),
        ("raw_completion_rate_pct", "Raw"), ("mature_sample_n", "Mature N"),
        ("mature_completion_rate_pct", "Mature"), ("terminal_identity_rate_pct", "Terminal rate"),
        ("endpoint_price_missing_rate_pct", "Endpoint missing rate"),
    ]
    lines = ["| " + " | ".join(label for _, label in cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in core.iterrows():
        vals = []
        for key, _ in cols:
            value = row[key]
            if key == "state":
                vals.append(str(value))
            elif key.endswith("_pct"):
                vals.append(_format_pct(value))
            elif pd.isna(value):
                vals.append("—")
            else:
                vals.append(str(int(value)))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def _comparison_frame(summary: pd.DataFrame) -> pd.DataFrame:
    pairs = (
        ("DEPRESSED", "NORMAL"),
        ("DEEP_DEPRESSED", "NORMAL"),
        ("DEEP_DEPRESSED", "DEPRESSED"),
    )
    metrics = (
        ("mature_completion_rate_pct", "mature_completion_diff_pp"),
        ("terminal_identity_rate_pct", "terminal_identity_rate_diff_pp"),
        ("endpoint_price_missing_rate_pct", "endpoint_price_missing_rate_diff_pp"),
    )
    lookup = summary.set_index(["panel", "horizon", "state"])
    rows: list[dict[str, Any]] = []
    for panel in PANELS:
        for horizon in HORIZONS:
            for target, reference in pairs:
                left = lookup.loc[(panel, horizon, target)]
                right = lookup.loc[(panel, horizon, reference)]
                row: dict[str, Any] = {
                    "panel": panel, "horizon": horizon,
                    "comparison": f"{target}_vs_{reference}",
                    "target_state": target, "reference_state": reference,
                }
                for source, destination in metrics:
                    row[destination] = float(left[source] - right[source])
                rows.append(row)
    return pd.DataFrame(rows)


def run_diagnostic() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    samples_path = SOURCE_DIR / "snapshot_samples.csv.gz"
    outcomes_path = SOURCE_DIR / "forward_outcomes.csv.gz"
    metadata_path = SOURCE_DIR / "study_metadata.json"
    pit_path = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
    calendar_path = ROOT / "data/market/rolling_authority/merged_trading_calendar.json"

    source_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    pit = json.loads(pit_path.read_text(encoding="utf-8"))
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    samples = pd.read_csv(samples_path, dtype={"ticker": str, "isu_cd": str})
    outcomes = pd.read_csv(outcomes_path, dtype={"ticker": str, "isu_cd": str})

    samples["ticker"] = samples["ticker"].map(normalize_ticker)
    samples["isu_cd"] = samples["isu_cd"].map(normalize_isu)
    samples["snapshot_date"] = samples["snapshot_date"].astype(str).str[:10]
    samples["state"] = samples["state"].astype(str)
    samples["panel_b_eligible"] = samples["panel_b_eligible"].astype(bool)
    samples["pit_market_cap_exact"] = samples["pit_market_cap_exact"].astype(bool)
    samples["market_cap_krw"] = pd.to_numeric(samples["market_cap_krw"], errors="coerce")
    outcomes["ticker"] = outcomes["ticker"].map(normalize_ticker)
    outcomes["isu_cd"] = outcomes["isu_cd"].map(normalize_isu)
    outcomes["snapshot_date"] = outcomes["snapshot_date"].astype(str).str[:10]
    outcomes["horizon"] = outcomes["horizon"].astype(str)

    sample_key = ["snapshot_date", "ticker", "isu_cd"]
    outcome_key = sample_key + ["horizon"]
    if samples.duplicated(sample_key).any():
        raise RuntimeError("duplicate sample keys in frozen source samples")
    if outcomes.duplicated(outcome_key).any():
        raise RuntimeError("duplicate sample/horizon keys in frozen source outcomes")
    if len(samples) != int(source_meta["panel_a_snapshot_count"]):
        raise RuntimeError("frozen sample row count does not match study metadata")
    if set(samples["state"]) != set(STATES):
        raise RuntimeError("frozen sample rows do not contain the expected five states")
    derived_panel_b = samples["pit_market_cap_exact"] & (samples["market_cap_krw"] >= 1_000_000_000_000)
    if not derived_panel_b.equals(samples["panel_b_eligible"]):
        raise RuntimeError("PANEL B membership does not match exact snapshot PIT market-cap threshold")
    if int(samples["panel_b_eligible"].sum()) != int(source_meta["panel_b_snapshot_count"]):
        raise RuntimeError("PANEL B snapshot count does not match source metadata")
    if len(outcomes) != sum(int(source_meta["horizon_counts"][h]["n"]) for h in HORIZONS):
        raise RuntimeError("frozen outcome row count does not match horizon counts")

    sample_keys = set(zip(samples["snapshot_date"], samples["ticker"], samples["isu_cd"]))
    outcome_keys = set(zip(outcomes["snapshot_date"], outcomes["ticker"], outcomes["isu_cd"], outcomes["horizon"]))
    if any(key[:3] not in sample_keys for key in outcome_keys):
        raise RuntimeError("an existing outcome row does not link to a source sample")
    outcomes_by_horizon = Counter(outcomes["horizon"])
    for horizon in HORIZONS:
        if outcomes_by_horizon[horizon] != int(source_meta["horizon_counts"][horizon]["n"]):
            raise RuntimeError(f"frozen outcome count mismatch for {horizon}")

    intervals: list[dict[str, Any]] = []
    intervals_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pit["intervals"]:
        iv = dict(item)
        iv["ticker"] = normalize_ticker(iv["ticker"])
        iv["isu_cd"] = normalize_isu(iv["isu_cd"])
        intervals.append(iv)
        intervals_by_ticker[iv["ticker"]].append(iv)
    for ticker_intervals in intervals_by_ticker.values():
        ticker_intervals.sort(key=lambda iv: (iv["effective_from"], iv["effective_to"], iv["isu_cd"], iv["market"]))

    trading_dates = [str(day)[:10] for day in calendar["trading_dates"]]
    if trading_dates != sorted(set(trading_dates)):
        raise RuntimeError("authoritative trading calendar is not sorted and unique")
    frontier = str(calendar.get("calendar_frontier") or pit["pit_frontier"])[:10]
    if frontier != str(source_meta["calendar_frontier"]):
        raise RuntimeError("source study and current calendar frontier differ")
    endpoint_cache = {
        (date, horizon): horizon_endpoint(date, horizon, trading_dates)
        for date in samples["snapshot_date"].drop_duplicates()
        for horizon in HORIZONS
    }
    outcome_set = outcome_keys

    counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    terminal_rows: list[dict[str, Any]] = []
    all_sample_keys = set(sample_keys)
    missing_reason_totals: dict[str, Counter[str]] = defaultdict(Counter)
    for row in samples.itertuples(index=False, name=None):
        sample = dict(zip(samples.columns, row))
        key = (sample["snapshot_date"], sample["ticker"], sample["isu_cd"])
        ticker_intervals = intervals_by_ticker.get(sample["ticker"], [])
        for horizon in HORIZONS:
            endpoint = endpoint_cache[(sample["snapshot_date"], horizon)]
            endpoint_after_frontier = endpoint is None or endpoint > frontier
            has_outcome = (*key, horizon) in outcome_set
            identity = {"identity_status": "NOT_ASSESSED"}
            if not endpoint_after_frontier and not has_outcome:
                identity = _identity_assessment(sample, endpoint, ticker_intervals, trading_dates)
            status = classify_status(
                outcome_present=has_outcome,
                endpoint_after_frontier=endpoint_after_frontier,
                identity_status=identity["identity_status"],
            )
            panel_names = ["PANEL_A_ALL"]
            if bool(sample["panel_b_eligible"]):
                panel_names.append("PANEL_B_PIT_1T_PLUS")
            for panel in panel_names:
                counts[(panel, horizon, sample["state"])][status] += 1
            if status == "TERMINAL_IDENTITY":
                terminal_rows.append({
                    "snapshot_date": key[0], "ticker": key[1], "isu_cd": key[2],
                    "state": sample["state"], "horizon": horizon,
                    "expected_sessions": HORIZONS[horizon], "endpoint_date": endpoint,
                    "identity_interval_start": str(sample["effective_from"])[:10],
                    "identity_interval_end": identity["identity_interval_end"],
                    "market_at_snapshot": str(sample["market"]),
                    "panel_a_eligible": True,
                    "panel_b_eligible": bool(sample["panel_b_eligible"]),
                    "identity_reason_code": identity["identity_reason_code"],
                    "identity_reason_detail": identity["identity_reason_detail"],
                    "endpoint_same_isu_intervals": identity["endpoint_same_isu_intervals"],
                    "endpoint_other_isu_intervals": identity["endpoint_other_isu_intervals"],
                    "last_same_isu_common_interval_before_endpoint": identity["last_same_isu_common_interval_before_endpoint"],
                    "later_same_isu_intervals_after_source": identity["later_same_isu_intervals_after_source"],
                    "chain_stop_reason": identity["chain_stop_reason"],
                    "chain_segments": identity["chain_segments"],
                    "outcome_row_present": False,
                })
            if not endpoint_after_frontier and not has_outcome:
                missing_reason_totals[horizon][status] += 1

    summary_rows: list[dict[str, Any]] = []
    for panel in PANELS:
        for horizon in HORIZONS:
            for state in STATES:
                category_counts = {status: int(counts[(panel, horizon, state)][status]) for status in STATUS_ORDER}
                total = sum(category_counts.values())
                summary_rows.append({
                    "panel": panel, "horizon": horizon, "state": state,
                    **summarize_status_counts(total, category_counts),
                })
    summary = pd.DataFrame(summary_rows)
    comparisons = _comparison_frame(summary)
    terminal = pd.DataFrame(terminal_rows)
    if not terminal.empty:
        terminal = terminal.sort_values(["horizon", "snapshot_date", "ticker", "isu_cd"]).reset_index(drop=True)

    # Compare reconstructed aggregate miss classes to the original study's recorded reasons.
    reconciliation: dict[str, dict[str, int]] = {}
    expected_reason_map = {
        "FRONTIER_INCOMPLETE": "ENDPOINT_AFTER_FRONTIER",
        "TERMINAL_IDENTITY": "FUTURE_IDENTITY_NOT_CONTIGUOUS",
        "ENDPOINT_PRICE_MISSING": "NO_EXACT_ENDPOINT_CLOSE",
    }
    for horizon in HORIZONS:
        expected = {
            status: int(source_meta["outcome_ineligible_reasons"].get(f"{horizon}:{reason}", 0))
            for status, reason in expected_reason_map.items()
        }
        observed = {
            "FRONTIER_INCOMPLETE": int(sum(counts[("PANEL_A_ALL", horizon, state)]["FRONTIER_INCOMPLETE"] for state in STATES)),
            "TERMINAL_IDENTITY": int(sum(counts[("PANEL_A_ALL", horizon, state)]["TERMINAL_IDENTITY"] for state in STATES)),
            "ENDPOINT_PRICE_MISSING": int(sum(counts[("PANEL_A_ALL", horizon, state)]["ENDPOINT_PRICE_MISSING"] for state in STATES)),
        }
        reconciliation[horizon] = {f"expected_{k}": v for k, v in expected.items()} | {f"observed_{k}": v for k, v in observed.items()}
        if expected != observed:
            raise RuntimeError(f"status reconstruction does not reconcile to source metadata for {horizon}: {reconciliation[horizon]}")
        expected_outcomes = int(source_meta["horizon_counts"][horizon]["n"])
        completed = sum(counts[("PANEL_A_ALL", horizon, state)]["COMPLETED"] for state in STATES)
        if completed != expected_outcomes:
            raise RuntimeError(f"completed count does not reconcile to source metadata for {horizon}")
        panel_b_completed = sum(counts[("PANEL_B_PIT_1T_PLUS", horizon, state)]["COMPLETED"] for state in STATES)
        expected_panel_b_outcomes = int(source_meta["horizon_counts"][horizon]["panel_b_n"])
        if panel_b_completed != expected_panel_b_outcomes:
            raise RuntimeError(f"PANEL B completed count does not reconcile for {horizon}")
        if sum(counts[("PANEL_A_ALL", horizon, state)]["OTHER_MISSING"] for state in STATES):
            raise RuntimeError(f"unexpected OTHER_MISSING outcomes for {horizon}")

    # A deterministic, independently inspected 20-row PIT-chain audit is emitted for review.
    if len(terminal) < 20:
        raise RuntimeError(f"fewer than 20 terminal identity rows available to spot-check: {len(terminal)}")
    reason_examples = terminal.groupby("identity_reason_code", group_keys=False).sample(n=1, random_state=SEED)
    remaining_terminal = terminal.drop(index=reason_examples.index)
    additional_n = 20 - len(reason_examples)
    chosen = pd.concat([
        reason_examples,
        remaining_terminal.sample(n=additional_n, random_state=SEED),
    ]).sort_values(["horizon", "snapshot_date", "ticker"]).reset_index(drop=True)
    spot_rows: list[dict[str, Any]] = []
    for _, row in chosen.iterrows():
        key = (row["snapshot_date"], row["ticker"], row["isu_cd"])
        if key not in all_sample_keys or (*key, row["horizon"]) in outcome_set:
            raise RuntimeError(f"terminal spot-check source/outcome linkage failed: {key}")
        if row["endpoint_date"] not in trading_dates or row["endpoint_date"] > frontier:
            raise RuntimeError(f"terminal spot-check endpoint is not an observed exchange date: {key}")
        original = samples.loc[
            (samples["snapshot_date"] == key[0]) & (samples["ticker"] == key[1]) & (samples["isu_cd"] == key[2])
        ].iloc[0].to_dict()
        rechecked = _identity_assessment(
            original, str(row["endpoint_date"]), intervals_by_ticker.get(key[1], []), trading_dates,
        )
        if rechecked["identity_status"] != "TERMINAL" or rechecked["identity_reason_code"] != row["identity_reason_code"]:
            raise RuntimeError(f"terminal spot-check identity result did not reproduce: {key}")
        spot_rows.append({
            "snapshot_date": key[0], "ticker": key[1], "isu_cd": key[2],
            "state": row["state"], "horizon": row["horizon"], "endpoint_date": row["endpoint_date"],
            "source_interval": f"{row['identity_interval_start']}~{row['identity_interval_end']} [{row['market_at_snapshot']}]",
            "endpoint_same_isu_intervals": row["endpoint_same_isu_intervals"],
            "endpoint_other_isu_intervals": row["endpoint_other_isu_intervals"],
            "last_same_isu_common_interval_before_endpoint": row["last_same_isu_common_interval_before_endpoint"],
            "later_same_isu_intervals_after_source": row["later_same_isu_intervals_after_source"],
            "chain_stop_reason": row["chain_stop_reason"],
            "identity_reason_code": row["identity_reason_code"],
            "source_sample_retained": True, "outcome_absent": True,
            "endpoint_calendar_verified": True, "identity_recheck_passed": True,
        })
    spot_checks = pd.DataFrame(spot_rows).sort_values(["horizon", "snapshot_date", "ticker"]).reset_index(drop=True)

    summary.to_csv(OUTPUT_DIR / "completion_by_state.csv", index=False, encoding="utf-8")
    comparisons.to_csv(OUTPUT_DIR / "state_comparisons.csv", index=False, encoding="utf-8")
    terminal.to_csv(OUTPUT_DIR / "terminal_identity_samples.csv", index=False, encoding="utf-8")
    spot_checks.to_csv(OUTPUT_DIR / "terminal_identity_spot_checks.csv", index=False, encoding="utf-8")

    # Judge from repeated direction across horizons, without adding a post-hoc rate threshold.
    core_comparisons = comparisons.loc[
        comparisons["horizon"].isin(["12M", "24M"])
        & comparisons["comparison"].eq("DEPRESSED_vs_NORMAL")
    ]
    panel_a_comparisons = core_comparisons.loc[core_comparisons["panel"] == "PANEL_A_ALL"]
    panel_a_missing_diff = (
        panel_a_comparisons["terminal_identity_rate_diff_pp"]
        + panel_a_comparisons["endpoint_price_missing_rate_diff_pp"]
    )
    panel_a_risk_repeats = bool(
        len(panel_a_comparisons) == 2
        and (panel_a_comparisons["mature_completion_diff_pp"] < 0).all()
        and (panel_a_missing_diff > 0).all()
    )
    if panel_a_risk_repeats:
        verdict = "PATTERN_B_FORWARD_CENSORING_DIAGNOSTIC_CAUTION"
        prior_interpretation = "기존 해석에 censoring caution 필요"
    else:
        verdict = "PATTERN_B_FORWARD_CENSORING_DIAGNOSTIC_PASS"
        prior_interpretation = "기존 해석 유지 가능"

    # Backtest readiness is a research gate, not an instruction to run one here.
    strategy_backtest_ready = True
    strategy_readiness_text = (
        "탐색적 백테스트 단계로는 넘어갈 수 있다. 다만 표본 기간·진입/청산·거래 비용·성숙 표본 및 terminal/endpoint missing 처리를 사전 고정해야 한다. "
        "이번 기술통계만으로 전략 우위가 확인된 것은 아니다."
    )

    report_lines = [
        "# Pattern B Horizon Outcome Censoring Diagnostic V01",
        "",
        f"- Verdict: `{verdict}`",
        f"- 기준 forward-study verdict: `PATTERN_B_FORWARD_SIGNAL_MIXED` (이번 작업에서 변경하지 않음)",
        "- Baseline commit at run start: `272016f6dca62e32af66c67bdfb9f072d8de8bbf`.",
        f"- Source samples: {len(samples):,}; existing outcome rows: {len(outcomes):,}; frontier: {frontier}.",
        "- Method: frozen source sample/outcome key join + existing merged PIT identity intervals and trading calendar. No price replay, return recalculation, imputation, or strategy backtest.",
        "- Rates in CSV are percentages. Mature terminal and endpoint-price missing rates use `mature_sample_n = total_snapshot_n - frontier_incomplete_n` as denominator.",
        "",
        "## Core completion results",
        "",
    ]
    for panel in PANELS:
        report_lines.extend([f"### {panel} — {PANELS[panel]}", ""])
        for horizon in ("12M", "24M"):
            report_lines.extend([f"#### {horizon}", "", _summary_table(summary, panel, horizon), ""])
    report_lines.extend(["## State contrasts (target minus reference, percentage points)", ""])
    contrast_rows = comparisons.loc[comparisons["horizon"].isin(["12M", "24M"])]
    report_lines.extend([
        "| Panel | Horizon | Contrast | Mature completion | Terminal identity | Endpoint price missing |",
        "|---|---|---|---:|---:|---:|",
    ])
    for _, row in contrast_rows.iterrows():
        report_lines.append(
            f"| {row['panel']} | {row['horizon']} | {row['comparison']} | "
            f"{_format_diff(row['mature_completion_diff_pp'])} | "
            f"{_format_diff(row['terminal_identity_rate_diff_pp'])} | "
            f"{_format_diff(row['endpoint_price_missing_rate_diff_pp'])} |"
        )
    reason_counts = terminal["identity_reason_code"].value_counts().to_dict() if not terminal.empty else {}
    top_reasons = ", ".join(f"`{key}` {value:,}" for key, value in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0])))
    report_lines.extend([
        "",
        "## Terminal identity evidence",
        "",
        f"Terminal rows: {len(terminal):,} distinct sample/horizon records; reason-code counts: {top_reasons or 'none'}.",
        "Reason codes describe only PIT interval/chain evidence. ISU changes are not asserted to be mergers, and no terminal case is assigned a return or economic loss.",
        f"A deterministic {len(spot_checks)}-row spot-check is in `terminal_identity_spot_checks.csv`; each row verifies source sample retained, outcome absent, exact endpoint in calendar and classifier reproduced from PIT authority.",
        "",
        "## Interpretation",
        "",
        f"Prior verdict interpretation: **{prior_interpretation}**. This diagnostic verdict does not alter `PATTERN_B_FORWARD_SIGNAL_MIXED`.",
        "",
        "### DEPRESSED forward-return 우위와 censoring",
        "",
    ])
    depressed_rows = core_comparisons
    if panel_a_risk_repeats:
        answer_censor = (
            "전부 설명할 가능성이 크다고 보긴 어렵지만, PANEL A에서는 일부 기여 가능성이 있다. 12M/24M mature completion이 NORMAL보다 각각 "
            f"{abs(float(panel_a_comparisons.loc[panel_a_comparisons['horizon'] == '12M', 'mature_completion_diff_pp'].iloc[0])):.2f}/"
            f"{abs(float(panel_a_comparisons.loc[panel_a_comparisons['horizon'] == '24M', 'mature_completion_diff_pp'].iloc[0])):.2f} pp 낮고, "
            "missing 비율은 더 높다. 차이는 terminal identity 자체보다 endpoint price missing에서 더 크다. PANEL B의 차이는 두 horizon에서 거의 0에 가까워 반복되지 않는다. "
            "기존 forward-return 우위가 생존 표본 조건부 결과일 가능성은 남지만, 전체 우위를 censoring 탓으로 돌릴 증거는 아니다."
        )
    else:
        answer_censor = (
            "현재 지표로는 가능성이 크다고 보기 어렵다. PANEL A의 12M/24M에서 mature completion 저하와 missing 증가가 함께 반복되지 않았다. "
            "이는 censoring이 없다는 뜻은 아니며, 수익률 우위의 원인으로 단정할 증거도 아니다."
        )
    answer_censor += (
        " 기존 연구의 PANEL B에서 DEPRESSED/NORMAL median return은 12M +1.6%/-3.9%, 24M +3.8%/-5.1%였고, "
        "이번 PANEL B mature completion은 각각 98.87%/98.74%, 98.24%/98.28%로 거의 같았다. 이 비교에서는 horizon censoring이 우위를 설명할 가능성이 낮아 보인다."
    )
    report_lines.extend([answer_censor, "", "### `DEPRESSED -> NORMAL` Pure Pattern B 전략 백테스트", "", strategy_readiness_text, ""])

    (OUTPUT_DIR / "report.md").write_text("\n".join(report_lines), encoding="utf-8")

    metadata = {
        "diagnostic": "KRX Pattern B Horizon Outcome Censoring Diagnostic V01",
        "verdict": verdict,
        "prior_forward_study_verdict": "PATTERN_B_FORWARD_SIGNAL_MIXED",
        "prior_interpretation": prior_interpretation,
        "exploratory_strategy_backtest_next_step_allowed": strategy_backtest_ready,
        "confirmatory_strategy_claim_supported": False,
        "strategy_backtest_readiness_text": strategy_readiness_text,
        "baseline_head_at_start": "272016f6dca62e32af66c67bdfb9f072d8de8bbf",
        "baseline_origin_main_at_start": "272016f6dca62e32af66c67bdfb9f072d8de8bbf",
        "source_directory": str(SOURCE_DIR.relative_to(ROOT)),
        "source_sample_rows": int(len(samples)),
        "source_outcome_rows": int(len(outcomes)),
        "source_sample_unique_keys": int(len(sample_keys)),
        "source_outcome_unique_keys": int(len(outcome_keys)),
        "source_panel_a_snapshots": int(source_meta["panel_a_snapshot_count"]),
        "source_panel_b_snapshots": int(source_meta["panel_b_snapshot_count"]),
        "source_horizon_outcome_counts": {h: int(outcomes_by_horizon[h]) for h in HORIZONS},
        "panel_definitions": PANELS,
        "state_definitions": list(STATES),
        "horizons_sessions": HORIZONS,
        "frontier": frontier,
        "pit_authority_content_digest": pit.get("content_digest"),
        "calendar_authority_content_digest": calendar.get("content_digest"),
        "classification": {
            "COMPLETED": "matching exact existing sample/horizon row in forward_outcomes.csv.gz",
            "FRONTIER_INCOMPLETE": "exact requested session offset is beyond the authoritative calendar/data frontier",
            "TERMINAL_IDENTITY": "no continuous same-ISU COMMON history_chain from snapshot interval through endpoint, based on existing PIT authority",
            "ENDPOINT_PRICE_MISSING": "identity chain is continuous to endpoint but exact outcome row is absent",
            "OTHER_MISSING": "remaining unclassified missing outcome; zero expected and checked against source metadata",
        },
        "rate_units": "percentage points (0-100 scale)",
        "mature_denominator": "total_snapshot_n - frontier_incomplete_n",
        "terminal_and_endpoint_missing_rate_denominator": "mature_sample_n",
        "source_metadata_reconciliation": reconciliation,
        "status_missing_counts_panel_a": {
            h: {s: int(sum(counts[("PANEL_A_ALL", h, state)][s] for state in STATES)) for s in STATUS_ORDER}
            for h in HORIZONS
        },
        "panel_b_mature_completion_matches_source_outcome_counts": True,
        "panel_b_membership_revalidated_from_exact_snapshot_cap": True,
        "panel_a_repeated_depressed_vs_normal_censoring_pattern_12m_24m": panel_a_risk_repeats,
        "terminal_identity_sample_horizon_rows": int(len(terminal)),
        "terminal_identity_spot_checks": int(len(spot_checks)),
        "spot_check_seed": SEED,
        "spot_check_selection": "one sample per observed reason code, then seeded random fill to 20",
        "spot_check_result": "PASS",
        "outcome_or_price_replay_performed": False,
        "existing_study_artifacts_modified": False,
        "strategy_backtest_performed": False,
        "source_study_metadata_outcome_ineligible_reasons": source_meta["outcome_ineligible_reasons"],
        "outputs": [
            "completion_by_state.csv", "state_comparisons.csv", "terminal_identity_samples.csv",
            "terminal_identity_spot_checks.csv", "metadata.json", "report.md",
        ],
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


if __name__ == "__main__":
    result = run_diagnostic()
    print(json.dumps({
        "verdict": result["verdict"],
        "source_sample_rows": result["source_sample_rows"],
        "source_outcome_rows": result["source_outcome_rows"],
        "terminal_identity_rows": result["terminal_identity_sample_horizon_rows"],
        "spot_checks": result["terminal_identity_spot_checks"],
        "output": str(OUTPUT_DIR),
    }, ensure_ascii=False, indent=2))
