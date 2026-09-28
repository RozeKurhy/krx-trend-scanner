#!/usr/bin/env python3
"""Revalidate official A FAST Core V2 adoption gates on the five standard windows."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_fastcore_neg40_weak_protect_p2_1 as p2
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
    _is_non_trading_placeholder,
)
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
PLAN_PATH = ROOT / "docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md"
PLAN_SHA256 = "84f7c7ab2dfd3f3af049dc876925f103d1e8d04e391248a780cd9d0537c1501c"
PLAN_COMMIT = "930bf77d6d780c42d75254f75bb26f0e1003b283"
OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02"

INITIAL_CAPITAL = 200_000_000.0
BUY_CASH_BUDGET = 5_000_000.0
COMMISSION_RATE = 0.00015
BUY_SLIPPAGE_RATE = 0.001
SELL_SLIPPAGE_RATE = 0.001
WORKERS = 10
WINDOWS: dict[str, dict[str, str]] = {
    "P1": {
        "source": "artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/control_trades.csv",
        "ledger_sha256": "0edcb9b87ccdc1e290c3431fb6e7e395bda910cf6dd69fa2d94426b7011eaeb0",
        "cert": "artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/p1_raw_only_certification_v02.json",
        "cert_sha256": "bf4319a0f1d9b9f443f2563b07779a3ea7dd4a8d5b2cd5daf2c808547e6d248c",
        "manifest": "artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/run_manifest.json",
        "manifest_sha256": "6658bed4dee907f4cf0d82a28688f21dfa7c14b759cb9aaa91e907842ff78098",
        "summary": "artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/p1_summary.json",
        "summary_sha256": "99b6af6db16ed52c197343e4858bbc316021f42e281033e4363952ccd7d68f08",
    },
    "P2-1": {
        "source": "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01/control_trades.csv",
        "ledger_sha256": "47d49cfba42bb7d3f278f81227671f68ab7dc96a34b42a3976f591c2c5a8c790",
        "cert": "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01/p2_1_raw_only_certification_v01.json",
        "cert_sha256": "2396c78b6f7c612d4fbbe6827c71cd0eb9f9ce543d542a7176ad02139af6481b",
        "manifest": "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/run_manifest.json",
        "manifest_sha256": "d8490fa9bf1628042519d2b8abde016f699f4f1874580b64a2691c96ea0b7a86",
        "summary": "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01/p2_1_raw_only_certification_v01.json",
        "summary_sha256": "2396c78b6f7c612d4fbbe6827c71cd0eb9f9ce543d542a7176ad02139af6481b",
    },
    "P2-2": {
        "source": "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/control_trades.csv",
        "ledger_sha256": "b58b27d326b79625bbdce775ab155d52486a11b1bcccfe2acf203d55a1b675f1",
        "cert": "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/p2_2_summary.json",
        "cert_sha256": "cc04b7f1608d5e7a27e8f3739916f5d83aa9374100684d40f54a7ca1ab773409",
        "manifest": "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/run_manifest.json",
        "manifest_sha256": "e025e852ba92605d3e68e6e9c5831f42daaa9f53975dddc02e5b650c19742a35",
        "summary": "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/p2_2_summary.json",
        "summary_sha256": "cc04b7f1608d5e7a27e8f3739916f5d83aa9374100684d40f54a7ca1ab773409",
    },
    "P3-1": {
        "source": "artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/control_trades.csv",
        "ledger_sha256": "333caeae854f69981d6ab3dd2d235eb798c25c7e1086ba7d4ea7d3da109c5b1e",
        "cert": "artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/p3_1_summary.json",
        "cert_sha256": "6d2757f521130f2455b1489361bab3c40f224b8025458be2d45d040dd990b156",
        "manifest": "artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/run_manifest.json",
        "manifest_sha256": "9ab02c8d4914acc67e992fc7b0d7fa9869711d5cebe11f3850909fdb3d894c4a",
        "summary": "artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/p3_1_summary.json",
        "summary_sha256": "6d2757f521130f2455b1489361bab3c40f224b8025458be2d45d040dd990b156",
    },
    "P3-2": {
        "source": "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/control_trades.csv",
        "ledger_sha256": "b905b601f36195e8a1666454f90f442e65c653857cda5e4fdc79a362b2776e16",
        "cert": "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/p3_2_summary.json",
        "cert_sha256": "d500be2806e0a6555389797f9d5035076dd4176774b49db25f70110949e325bf",
        "manifest": "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/run_manifest.json",
        "manifest_sha256": "dc39a7e0500ad9fbe121e586ee846a2b87e913250cb8640219727bd4d8e5b2ae",
        "summary": "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/p3_2_summary.json",
        "summary_sha256": "d500be2806e0a6555389797f9d5035076dd4176774b49db25f70110949e325bf",
    },
}

EXPECTED_DATES = {
    "P1": ("2014-01-02", "2026-08-31", "2026-09-01"),
    "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
    "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
    "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
    "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
}

REFERENCE_SUMMARIES = {
    "P2-1": "artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json",
    "P2-2": "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json",
    "P3-2": "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/summary.json",
}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_frame_hash(frame: pd.DataFrame) -> str:
    h = hashlib.sha256()
    view = frame.loc[:, ["open", "high", "low", "close"]].sort_index()
    for idx, row in view.iterrows():
        h.update(pd.Timestamp(idx).strftime("%Y-%m-%d").encode())
        for column in ("open", "high", "low", "close"):
            value = pd.to_numeric(row[column], errors="coerce")
            h.update(("|" + ("NA" if pd.isna(value) else format(float(value), ".12g"))).encode())
        h.update(b"\n")
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_hash(path: Path, expected: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"SOURCE_SHA256_MISMATCH:{path.relative_to(ROOT)}:{actual}:{expected}")
    return actual


def source_check(window_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = WINDOWS[window_id]
    paths = {key: ROOT / config[key] for key in ("source", "cert", "manifest", "summary")}
    hashes = {key: assert_hash(paths[key], config[f"{key}_sha256" if key != "source" else "ledger_sha256"]) for key in paths}
    cert = read_json(paths["cert"])
    summary = read_json(paths["summary"])
    manifest = read_json(paths["manifest"])
    if window_id in {"P1", "P2-1"}:
        if cert.get("status") != "PASS" or "CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS" not in str(cert.get("verdict")):
            raise RuntimeError(f"SOURCE_CERTIFICATION_NOT_PASS:{window_id}:{cert.get('verdict')}")
    elif window_id == "P3-1":
        if summary.get("certification_verdict") != "RECERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSION":
            raise RuntimeError(f"SOURCE_CERTIFICATION_NOT_PASS:{window_id}:{summary.get('certification_verdict')}")
    elif window_id == "P3-2":
        if summary.get("certification_verdict") != "RECERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSION":
            raise RuntimeError(f"SOURCE_CERTIFICATION_NOT_PASS:{window_id}:{summary.get('certification_verdict')}")
    elif window_id == "P2-2":
        validation = summary.get("validation", {})
        if summary.get("status") != "COMPLETE" or validation.get("control_overlap_count") != 0:
            raise RuntimeError(f"SOURCE_CONTROL_RECONCILIATION_NOT_PASS:{window_id}")

    raw = pd.read_csv(paths["source"], dtype=str, keep_default_na=False).to_dict("records")
    if len(raw) != len(set(str(row.get("pair_id", "")) for row in raw)):
        raise RuntimeError(f"DUPLICATE_SOURCE_PAIR_ID:{window_id}")
    exclusions = set(PERMANENT_IDENTITY_EXCLUSIONS)
    kept: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for row in raw:
        ticker = str(row.get("ticker", "")).strip().zfill(6)
        isu_cd = str(row.get("isu_cd", "")).strip().upper()
        if (ticker, isu_cd) in exclusions:
            excluded_rows.append({"window_id": window_id, "ticker": ticker, "isu_cd": isu_cd, "pair_id": row.get("pair_id"), "reason": PERMANENT_IDENTITY_EXCLUSIONS[(ticker, isu_cd)]["reason"]})
            continue
        if row.get("strategy_id") and row["strategy_id"] != STRATEGY_ID:
            raise RuntimeError(f"NON_V2_CONTROL_RECORD:{window_id}:{row.get('strategy_id')}")
        row["ticker"] = ticker
        row["isu_cd"] = isu_cd
        kept.append(row)
    expected_id = {"P1": "P1", "P2-1": "P2-1", "P2-2": "P2-2", "P3-1": "P3-1", "P3-2": "P3-2"}[window_id]
    if summary.get("window_id") not in (None, expected_id):
        raise RuntimeError(f"SOURCE_WINDOW_ID_MISMATCH:{window_id}:{summary.get('window_id')}")
    details = {
        "window_id": window_id,
        "source_path": str(paths["source"].relative_to(ROOT)),
        "source_sha256": hashes["source"],
        "source_rows": len(raw),
        "rows_after_permanent_exclusions": len(kept),
        "excluded_rows": excluded_rows,
        "certification_status": cert.get("status", summary.get("status")),
        "certification_verdict": cert.get("verdict", summary.get("certification_verdict", summary.get("verdict"))),
        "source_manifest_sha256": hashes["manifest"],
        "source_summary_sha256": hashes["summary"],
        "parent_run_manifest_status": manifest.get("certification_status", manifest.get("status")),
    }
    return kept, details


def identity_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).strip().upper(),
        str(row.get("market", "")).strip().upper(),
        str(row.get("identity_effective_from", ""))[:10],
        str(row.get("identity_effective_to", ""))[:10],
    )


def signal_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", "")).strip().upper(),
        str(row.get("entry_signal_date", ""))[:10],
        str(row.get("entry_execution_date", ""))[:10],
    )


def parse_date(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "" or str(value).strip().lower() == "nan":
        return None
    return pd.Timestamp(value).normalize()


def numeric(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


@dataclass
class WindowContext:
    window_id: str
    run: Any
    source_rows: list[dict[str, Any]]
    source_details: dict[str, Any]
    data_frames: dict[tuple[str, str, str, str, str], pd.DataFrame]
    frame_hashes: dict[str, str]
    segment_by_key: dict[tuple[str, str, str, str, str], Any]
    typed_lifecycle_by_id: dict[str, dict[str, Any]]
    legacy_lifecycle: tuple[dict[str, Any], ...]
    raw_store: KrxRawStockStore
    raw_partition_cache: dict[tuple[str, str], tuple[dict[str, Any] | None, pd.DataFrame | None]]
    raw_manifest_db_sha256: str | None = None


def find_segment(run: Any, key: tuple[str, str, str, str, str]) -> Any | None:
    ticker, isu_cd, market, start, end = key
    for segment in run.segments_by_ticker.get(ticker, ()):
        if (
            segment.isu_cd.strip().upper() == isu_cd
            and segment.market.strip().upper() == market
            and segment.effective_from.strftime("%Y-%m-%d") == start
            and segment.effective_to.strftime("%Y-%m-%d") == end
        ):
            return segment
    return None


def build_window_context(window_id: str) -> WindowContext:
    source_rows, source_details = source_check(window_id)
    run = p2._load_context(window_id)
    actual = tuple(value.strftime("%Y-%m-%d") for value in (run.window.effective_start, run.window.effective_end, run.window.execution_support))
    if actual != EXPECTED_DATES[window_id]:
        raise RuntimeError(f"RESOLVED_WINDOW_MISMATCH:{window_id}:{actual}")
    segment_by_key: dict[tuple[str, str, str, str, str], Any] = {}
    source_identity_issues: list[str] = []
    for row in source_rows:
        key = identity_key(row)
        segment = find_segment(run, key)
        if segment is None:
            source_identity_issues.append("|".join(key))
        else:
            segment_by_key[key] = segment
    if source_identity_issues:
        raise RuntimeError(f"CONTROL_IDENTITY_NOT_IN_CURRENT_PIT:{window_id}:{source_identity_issues[:10]}")
    pit_identities = sorted(
        (
            str(segment.ticker).zfill(6),
            str(segment.isu_cd).strip().upper(),
            str(segment.market).strip().upper(),
            segment.effective_from.strftime("%Y-%m-%d"),
            segment.effective_to.strftime("%Y-%m-%d"),
        )
        for segments in run.segments_by_ticker.values()
        for segment in segments
    )
    resolved_calendar = sorted(pd.Timestamp(day).normalize().strftime("%Y-%m-%d") for day in run.calendar.trading_dates)
    source_details["resolved_pit_identity_count"] = len(pit_identities)
    source_details["resolved_pit_identity_set_sha256"] = hashlib.sha256(
        json.dumps(pit_identities, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_details["resolved_calendar_session_count"] = len(resolved_calendar)
    source_details["resolved_calendar_sha256"] = hashlib.sha256("\n".join(resolved_calendar).encode("utf-8")).hexdigest()
    typed_lifecycle = tuple(getattr(run, "lifecycle_settlements", ()))
    legacy = p2._load_lifecycle_settlement_evidence(p2.LIFECYCLE_SETTLEMENT_EVIDENCE_PATH)
    return WindowContext(
        window_id=window_id,
        run=run,
        source_rows=source_rows,
        source_details=source_details,
        data_frames={},
        frame_hashes={},
        segment_by_key=segment_by_key,
        typed_lifecycle_by_id={str(item.get("evidence_id")): dict(item) for item in typed_lifecycle if item.get("evidence_id")},
        legacy_lifecycle=tuple(legacy),
        raw_store=KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01"),
        raw_partition_cache={},
    )


def load_identity_frame(ctx: WindowContext, key: tuple[str, str, str, str, str]) -> pd.DataFrame:
    frame = ctx.data_frames.get(key)
    if frame is not None:
        return frame
    frame, digest = _load_identity_frame_uncached(ctx, key)
    ctx.data_frames[key] = frame
    ctx.frame_hashes["|".join(key)] = digest
    return frame


def _load_identity_frame_uncached(ctx: WindowContext, key: tuple[str, str, str, str, str]) -> tuple[pd.DataFrame, str]:
    segment = ctx.segment_by_key.get(key) or find_segment(ctx.run, key)
    if segment is None:
        raise RuntimeError(f"IDENTITY_FRAME_WITHOUT_PIT_SEGMENT:{key}")
    loader = RepositoryV2DailyLoader(ctx.run.loader.repository, start=segment.effective_from, end=ctx.run.window.execution_support)
    daily = loader.load(segment.ticker)
    if daily is None or daily.empty:
        raise RuntimeError(f"REPOSITORY_V2_DAILY_UNAVAILABLE:{key}")
    daily = daily.sort_index()
    if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
        raise RuntimeError(f"REPOSITORY_V2_DAILY_INDEX_INVALID:{key}")
    for column in ("open", "high", "low", "close"):
        if column not in daily.columns:
            raise RuntimeError(f"REPOSITORY_V2_OHLC_COLUMN_MISSING:{key}:{column}")
    daily = daily.loc[:, ["open", "high", "low", "close"]].copy()
    return daily, canonical_frame_hash(daily)


def preload_identity_frames(
    ctx: WindowContext,
    streams: Mapping[tuple[str, str, str, str, str], Sequence[Mapping[str, Any]]],
) -> None:
    """Load independent Repository V2 price frames in parallel; portfolio events remain sequential."""

    keys = sorted(streams)
    if not keys:
        return
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="v2-price-frame") as pool:
        loaded = list(pool.map(lambda key: (key, *_load_identity_frame_uncached(ctx, key)), keys))
    for key, frame, digest in loaded:
        ctx.data_frames[key] = frame
        ctx.frame_hashes["|".join(key)] = digest


def exact_price(frame: pd.DataFrame, day: pd.Timestamp, column: str) -> float | None:
    day = pd.Timestamp(day).normalize()
    if day not in frame.index:
        return None
    value = numeric(frame.at[day, column])
    return value if value is not None and value > 0 else None


def _raw_partition(ctx: WindowContext, market: str, day: pd.Timestamp) -> tuple[dict[str, Any] | None, pd.DataFrame | None]:
    market = str(market).strip().upper()
    date_text = pd.Timestamp(day).strftime("%Y-%m-%d")
    key = (market, date_text)
    if key in ctx.raw_partition_cache:
        return ctx.raw_partition_cache[key]
    manifest = ctx.raw_store.get_manifest(market, date_text)
    if manifest is None or manifest.get("status") != "COMPLETE":
        result = (manifest, None)
        ctx.raw_partition_cache[key] = result
        return result
    try:
        frame = ctx.raw_store.load_snapshot(market, date_text)
    except Exception as exc:
        invalid = dict(manifest)
        invalid["verification_error"] = f"{type(exc).__name__}:{exc}"
        result = (invalid, None)
        ctx.raw_partition_cache[key] = result
        return result
    result = (manifest, frame)
    ctx.raw_partition_cache[key] = result
    return result


def mark_price_with_official_carry(
    ctx: WindowContext,
    position: Mapping[str, Any],
    day: pd.Timestamp,
) -> tuple[float | None, dict[str, Any] | None]:
    """Return an exact close or the narrowly authorized valuation-only carry."""

    frame = position["frame"]
    mark = exact_price(frame, day, "close")
    if mark is not None:
        return mark, None

    ticker = str(position.get("ticker", "")).zfill(6)
    isu_cd = str(position.get("current_isu_cd", position.get("identity_key", ("", ""))[1])).strip().upper()
    market = str(position.get("record", {}).get("market", "")).strip().upper()
    manifest, raw_frame = _raw_partition(ctx, market, day)
    raw_row: dict[str, Any] | None = None
    evidence_state = "RAW_PARTITION_MISSING"
    reason = "RAW_PARTITION_MISSING"
    if manifest is not None:
        status = str(manifest.get("status", "UNKNOWN"))
        evidence_state = f"RAW_PARTITION_{status}"
        reason = f"RAW_PARTITION_{status}"
        if manifest.get("verification_error"):
            evidence_state = "RAW_PARTITION_INVALID"
            reason = "RAW_PARTITION_INTEGRITY_FAILURE"
        elif status == "COMPLETE" and raw_frame is not None:
            matches = raw_frame.loc[raw_frame["ticker"].astype(str).str.zfill(6) == ticker]
            if len(matches) == 1:
                row = matches.iloc[0]
                raw_row = {name: (pd.Timestamp(value).strftime("%Y-%m-%d") if name == "date" else int(value) if name != "ticker" else str(value).zfill(6)) for name, value in row.to_dict().items()}
                if _is_non_trading_placeholder(row):
                    evidence_state = "OFFICIAL_NON_TRADING_PLACEHOLDER_CONFIRMED"
                    reason = "OFFICIAL_NON_TRADING_PLACEHOLDER"
                else:
                    evidence_state = "RAW_ROW_NOT_PLACEHOLDER"
                    reason = "RAW_ROW_NOT_NON_TRADING_PLACEHOLDER"
            else:
                evidence_state = "EXACT_TICKER_ROW_MISSING" if matches.empty else "DUPLICATE_EXACT_TICKER_ROWS"
                reason = evidence_state

    prior_rows = frame.loc[frame.index < pd.Timestamp(day).normalize(), "close"]
    valid_prior = pd.to_numeric(prior_rows, errors="coerce")
    valid_prior = valid_prior[valid_prior.map(lambda value: math.isfinite(float(value)) and float(value) > 0)]
    prior_date: pd.Timestamp | None = None
    prior_close: float | None = None
    if not valid_prior.empty:
        prior_date = pd.Timestamp(valid_prior.index[-1]).normalize()
        prior_close = float(valid_prior.iloc[-1])

    partition_path_value = manifest.get("file_path") if manifest else None
    partition_path = Path(str(partition_path_value)) if partition_path_value else None
    if partition_path is not None and not partition_path.is_absolute():
        partition_path = ctx.raw_store.root / partition_path
    manifest_db = ctx.raw_store.manifest_path
    carry_eligible = evidence_state == "OFFICIAL_NON_TRADING_PLACEHOLDER_CONFIRMED" and prior_close is not None
    if evidence_state == "OFFICIAL_NON_TRADING_PLACEHOLDER_CONFIRMED" and prior_close is None:
        evidence_state = "PLACEHOLDER_WITHOUT_PRIOR_VALID_ADJUSTED_CLOSE"
        reason = "NO_PRIOR_VALID_ADJUSTED_CLOSE"
        carry_eligible = False
    calendar_dates = [pd.Timestamp(value).normalize() for value in ctx.run.calendar.trading_dates]
    age_sessions = None if prior_date is None else sum(prior_date < value <= pd.Timestamp(day).normalize() for value in calendar_dates)
    audit = {
        "window_id": ctx.window_id,
        "ticker": ticker,
        "isu_cd": isu_cd,
        "market": market,
        "valuation_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
        "reason": reason,
        "evidence_state": evidence_state,
        "predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
        "raw_manifest_status": None if manifest is None else manifest.get("status"),
        "raw_manifest_path": str(manifest_db.relative_to(ROOT)) if manifest_db.is_relative_to(ROOT) else str(manifest_db),
        "raw_manifest_db_sha256": None,
        "raw_partition_path": None if partition_path is None else str(partition_path.relative_to(ROOT)) if partition_path.is_relative_to(ROOT) else str(partition_path),
        "raw_partition_file_sha256": None if manifest is None else manifest.get("file_sha256"),
        "raw_partition_content_sha256": None if manifest is None else manifest.get("content_sha256"),
        "raw_partition_schema_version": None if manifest is None else manifest.get("schema_version"),
        "raw_partition_row_count": None if manifest is None else manifest.get("row_count"),
        "raw_row": raw_row,
        "prior_valid_adjusted_close_date": None if prior_date is None else prior_date.strftime("%Y-%m-%d"),
        "prior_valid_adjusted_close": prior_close,
        "carry_age_calendar_days": None if prior_date is None else int((pd.Timestamp(day).normalize() - prior_date).days),
        "carry_age_trading_sessions": age_sessions,
        "carry_applied": carry_eligible,
        "valuation_only": True,
        "used_for_signal_or_strategy_state": False,
        "used_for_entry_exit_fill": False,
        "used_for_cutoff_execution": False,
    }
    if manifest is not None and manifest_db.exists():
        if ctx.raw_manifest_db_sha256 is None:
            ctx.raw_manifest_db_sha256 = sha256_file(manifest_db)
        audit["raw_manifest_db_sha256"] = ctx.raw_manifest_db_sha256
    return (prior_close if carry_eligible else None), audit


def next_session_on_or_after(calendar_dates: Sequence[pd.Timestamp], day: pd.Timestamp) -> pd.Timestamp | None:
    target = pd.Timestamp(day).normalize()
    for session in calendar_dates:
        if session >= target:
            return session
    return None


def make_lifecycle_action(ctx: WindowContext, row: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(row.get("trade_status", ""))
    lifecycle_state = str(row.get("lifecycle_state", ""))
    if status == "LIFECYCLE_SETTLED":
        settlement_date = parse_date(row.get("settlement_date"))
        amount = numeric(row.get("settlement_price"))
        if settlement_date is None or amount is None or amount <= 0:
            return {"kind": "UNRESOLVED", "date": None, "reason": "LEGACY_SETTLEMENT_TERMS_MISSING"}
        return {"kind": "CASH_SETTLEMENT", "date": settlement_date, "payment_date": settlement_date, "cash_per_share": amount, "source": row.get("settlement_source"), "evidence_id": row.get("lifecycle_evidence_id")}

    evidence_id = str(row.get("lifecycle_evidence_id", ""))
    event = ctx.typed_lifecycle_by_id.get(evidence_id) if evidence_id else None
    if event is None:
        return None
    effective_date = p2._event_effective_date(event)
    if effective_date is None:
        return {"kind": "UNRESOLVED", "date": None, "reason": "LIFECYCLE_EFFECTIVE_DATE_MISSING", "evidence_id": evidence_id}
    kind = str(event.get("event_type", ""))
    if kind == "MANDATORY_CASH" and lifecycle_state in {"SETTLED", "SETTLEMENT_PENDING"}:
        cash_per_share = numeric(row.get("settlement_price"))
        payment_date = parse_date(row.get("settlement_date"))
        if cash_per_share is None or cash_per_share <= 0:
            return {"kind": "UNRESOLVED", "date": effective_date, "reason": "MANDATORY_CASH_VALUE_MISSING", "evidence_id": evidence_id}
        return {"kind": "CASH_RECEIVABLE", "date": effective_date, "payment_date": payment_date, "cash_per_share": cash_per_share, "source": row.get("settlement_source"), "evidence_id": evidence_id}
    if kind == "MANDATORY_SHARE_EXCHANGE" and lifecycle_state == "SUCCESSOR_POSITION":
        quantity = numeric(row.get("successor_quantity"))
        availability = parse_date(event.get("successor_available_date"))
        successor_ticker = str(row.get("successor_ticker", "")).zfill(6)
        successor_isu = str(row.get("successor_isu_cd", "")).strip().upper()
        successor_market = str(event.get("successor_market", "")).strip().upper()
        if quantity is None or quantity <= 0 or not successor_ticker.strip("0") or not successor_isu or availability is None:
            return {"kind": "UNRESOLVED", "date": effective_date, "reason": "SUCCESSOR_TERMS_MISSING", "evidence_id": evidence_id}
        return {"kind": "SUCCESSOR", "date": effective_date, "available_date": availability, "ticker": successor_ticker, "isu_cd": successor_isu, "market": successor_market, "shares_per_source_share": quantity, "evidence_id": evidence_id}
    if lifecycle_state in {"UNRESOLVED_SETTLEMENT", "UNRESOLVED_SUCCESSOR", "UNRESOLVED_POST_DELIST_VALUE", "SUCCESSOR_PENDING"}:
        return {"kind": "UNRESOLVED", "date": effective_date, "reason": row.get("lifecycle_unresolved_reason") or lifecycle_state, "evidence_id": evidence_id}
    return None


def successor_daily(ctx: WindowContext, ticker: str, isu_cd: str, start: pd.Timestamp) -> pd.DataFrame:
    ticker = str(ticker).zfill(6)
    loader = RepositoryV2DailyLoader(ctx.run.loader.repository, start=start, end=ctx.run.window.effective_end)
    daily = loader.load(ticker)
    if daily is None or daily.empty:
        raise RuntimeError(f"SUCCESSOR_REPOSITORY_V2_DAILY_UNAVAILABLE:{ticker}:{isu_cd}")
    return daily.sort_index().loc[:, ["open", "high", "low", "close"]].copy()


def scope_streams(
    ctx: WindowContext,
    rows: Sequence[Mapping[str, Any]],
    end: pd.Timestamp,
) -> tuple[dict[tuple[str, str, str, str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    start = pd.Timestamp(ctx.run.window.effective_start).normalize()
    end = pd.Timestamp(end).normalize()
    streams: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    issues: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, str, str, str]] = set()
    for source in rows:
        row = dict(source)
        candidate_id = signal_key(row)
        if candidate_id in seen_candidates:
            issues.append({"kind": "DUPLICATE_SIGNAL_ID", "window_id": ctx.window_id, "candidate_id": "|".join(candidate_id)})
            continue
        seen_candidates.add(candidate_id)
        signal_date = parse_date(row.get("entry_signal_date"))
        entry_date = parse_date(row.get("entry_execution_date"))
        if signal_date is None or entry_date is None:
            issues.append({"kind": "ENTRY_DATE_MISSING", "window_id": ctx.window_id, "pair_id": row.get("pair_id")})
            continue
        if signal_date < start or entry_date < start:
            issues.append({"kind": "ENTRY_BEFORE_EFFECTIVE_START", "window_id": ctx.window_id, "pair_id": row.get("pair_id"), "date": str(entry_date.date())})
            continue
        if signal_date > end or entry_date > end:
            continue
        if entry_date > ctx.run.window.execution_support:
            issues.append({"kind": "ENTRY_AFTER_EXECUTION_SUPPORT", "window_id": ctx.window_id, "pair_id": row.get("pair_id"), "date": str(entry_date.date())})
            continue
        status = str(row.get("trade_status", ""))
        if status not in {"REALIZED", "OPEN_AT_CUTOFF", "OPEN_AT_CUTOFF_WEAK_PROTECT", "LIFECYCLE_SETTLED"}:
            issues.append({"kind": "UNRESOLVED_SOURCE_TRADE_STATUS", "window_id": ctx.window_id, "pair_id": row.get("pair_id"), "trade_status": status})
        key = identity_key(row)
        streams.setdefault(key, []).append(row)
    for key in streams:
        streams[key].sort(key=signal_key)
        if len({signal_key(row) for row in streams[key]}) != len(streams[key]):
            issues.append({"kind": "DUPLICATE_IDENTITY_SIGNAL", "window_id": ctx.window_id, "identity": "|".join(key)})
    return streams, issues


def _record_entry_fill(ctx: WindowContext, row: Mapping[str, Any], day: pd.Timestamp) -> tuple[pd.DataFrame | None, float | None, str | None]:
    key = identity_key(row)
    try:
        frame = load_identity_frame(ctx, key)
    except Exception as exc:
        return None, None, f"REPOSITORY_V2_LOAD_ERROR:{type(exc).__name__}:{exc}"
    reference = exact_price(frame, day, "open")
    expected = numeric(row.get("entry_open"))
    if reference is None:
        return frame, None, "MISSING_EXACT_ENTRY_OPEN"
    if expected is None or not math.isclose(reference, expected, rel_tol=0, abs_tol=0.011):
        return frame, reference, "SOURCE_ENTRY_OPEN_MISMATCH"
    return frame, reference, None


def _row_action_day(action: Mapping[str, Any] | None, calendar_dates: Sequence[pd.Timestamp]) -> pd.Timestamp | None:
    if not action or action.get("date") is None:
        return None
    return next_session_on_or_after(calendar_dates, pd.Timestamp(action["date"]))


def mdd_details(curve: Sequence[Mapping[str, Any]], effective_start: pd.Timestamp) -> dict[str, Any]:
    valid = [row for row in curve if row.get("equity") is not None and not pd.isna(row.get("equity"))]
    if not valid or len(valid) != len(curve):
        return {"mdd_pct": None, "mdd_peak_date": None, "mdd_trough_date": None, "mdd_recovery_date": None, "mdd_underwater_sessions": None, "mdd_recovered": False}
    peak = INITIAL_CAPITAL
    peak_date = pd.Timestamp(effective_start).normalize()
    worst = 0.0
    worst_peak = peak_date
    worst_peak_value = peak
    trough = peak_date
    recovery: pd.Timestamp | None = None
    all_days = [pd.Timestamp(item["date"]).normalize() for item in valid]
    for row, day in zip(valid, all_days):
        equity = float(row["equity"])
        if equity >= peak:
            peak = equity
            peak_date = day
        drawdown = equity / peak - 1.0 if peak else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_peak_value = peak
            trough = day
            recovery = None
        elif worst < 0 and recovery is None and day > trough and equity >= worst_peak_value:
            recovery = day
    if worst == 0.0:
        return {"mdd_pct": 0.0, "mdd_peak_date": peak_date.strftime("%Y-%m-%d"), "mdd_trough_date": peak_date.strftime("%Y-%m-%d"), "mdd_recovery_date": peak_date.strftime("%Y-%m-%d"), "mdd_underwater_sessions": 0, "mdd_recovered": True}
    trough_idx = all_days.index(trough)
    peak_idx = max([-1] + [i for i, day in enumerate(all_days) if day <= worst_peak])
    end_idx = all_days.index(recovery) if recovery in all_days else len(all_days) - 1
    return {
        "mdd_pct": worst * 100.0,
        "mdd_peak_date": worst_peak.strftime("%Y-%m-%d"),
        "mdd_trough_date": trough.strftime("%Y-%m-%d"),
        "mdd_recovery_date": recovery.strftime("%Y-%m-%d") if recovery is not None else None,
        "mdd_underwater_sessions": max(0, end_idx - peak_idx),
        "mdd_recovered": recovery is not None,
    }


def portfolio_replay(
    ctx: WindowContext,
    source_streams: dict[tuple[str, str, str, str, str], list[dict[str, Any]]],
    initial_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run = ctx.run
    effective_start = pd.Timestamp(run.window.effective_start).normalize()
    effective_end = pd.Timestamp(run.window.effective_end).normalize()
    execution_support = pd.Timestamp(run.window.execution_support).normalize()
    all_calendar = pd.DatetimeIndex(pd.to_datetime(run.calendar.trading_dates)).normalize()
    calendar_dates = [pd.Timestamp(d).normalize() for d in all_calendar if effective_start <= pd.Timestamp(d).normalize() <= execution_support]
    if effective_end not in calendar_dates or execution_support not in calendar_dates:
        raise RuntimeError(f"WINDOW_CALENDAR_MISSING_CUTOFF_OR_SUPPORT:{ctx.window_id}")
    next_session = {day: calendar_dates[i + 1] for i, day in enumerate(calendar_dates[:-1])}
    issue_rows = list(initial_issues or [])
    streams = {key: [dict(row) for row in value] for key, value in source_streams.items()}
    decision_status: dict[tuple[str, str, str, str], str] = {}
    events: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    valuation_carry_audit: list[dict[str, Any]] = []
    daily_equity: list[dict[str, Any]] = []
    executed_closed_returns: list[float] = []
    holding_sessions: list[int] = []
    pending_sales: dict[pd.Timestamp, float] = {}
    cash = INITIAL_CAPITAL
    total_buy_notional = 0.0
    total_sell_notional = 0.0
    total_commission = 0.0
    total_slippage = 0.0
    eligible_attempts = 0
    cash_skips = 0
    executed_entries = 0
    realized_exits = 0
    lifecycle_closures = 0
    missing_marks: list[dict[str, Any]] = []
    unresolved_trade_events: list[dict[str, Any]] = []
    life_event_diagnostics: list[dict[str, Any]] = []
    cash_receivables: dict[str, dict[str, Any]] = {}
    positions: dict[str, dict[str, Any]] = {}
    exited_tickers_by_day: dict[pd.Timestamp, set[str]] = {}
    snapshot_at_cutoff: dict[str, Any] | None = None
    cash_conservation_pass = True

    def event_base(row: Mapping[str, Any], day: pd.Timestamp, event_type: str) -> dict[str, Any]:
        return {
            "window_id": ctx.window_id,
            "candidate_id": "|".join(signal_key(row)),
            "pair_id": row.get("pair_id"),
            "trade_id": row.get("trade_id"),
            "ticker": str(row.get("ticker", "")).zfill(6),
            "isu_cd": row.get("isu_cd"),
            "market": row.get("market"),
            "signal_date": row.get("entry_signal_date") if event_type == "ENTRY" else row.get("exit_signal_date"),
            "execution_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
            "event_type": event_type,
            "event_status": None,
            "reason": None,
            "reference_price": None,
            "fill_price": None,
            "shares": None,
            "notional_krw": 0.0,
            "commission_krw": 0.0,
            "slippage_impact_krw": 0.0,
            "cash_before_krw": cash,
            "cash_after_krw": cash,
            "pending_sale_proceeds_krw": sum(pending_sales.values()),
        }

    def remember(row: dict[str, Any]) -> None:
        events.append(row)
        if row.get("event_type") in {"ENTRY", "EXIT", "CASH_SETTLEMENT", "CASH_RECEIVABLE", "SUCCESSOR_CONVERSION"}:
            cash_events.append(row)

    def active_candidate_rows(day: pd.Timestamp) -> list[tuple[tuple[str, str, str, str, str], dict[str, Any]]]:
        out = []
        for key, items in streams.items():
            for item in items:
                cid = signal_key(item)
                if cid in decision_status:
                    continue
                entry = parse_date(item.get("entry_execution_date"))
                if entry == day:
                    out.append((key, item))
        out.sort(key=lambda pair: (str(pair[1].get("ticker", "")).zfill(6), signal_key(pair[1])))
        return out

    for session_no, day in enumerate(calendar_dates, start=1):
        if session_no == 1 or session_no % 40 == 0 or session_no == len(calendar_dates):
            print(f"[{ctx.window_id}] portfolio session {session_no}/{len(calendar_dates)}; entries={executed_entries}; cash_skips={cash_skips}; active={len(positions)}", flush=True)
        # T+1 proceeds from earlier sales become spendable at the next normal session.
        cash += pending_sales.pop(day, 0.0)
        for receivable_id, item in list(cash_receivables.items()):
            if item.get("release_date") == day:
                cash += float(item["amount"])
                del cash_receivables[receivable_id]
                e = {"window_id": ctx.window_id, "candidate_id": item.get("candidate_id"), "ticker": item.get("ticker"), "isu_cd": item.get("isu_cd"), "execution_date": day.strftime("%Y-%m-%d"), "event_type": "CASH_RECEIVABLE_RELEASE", "event_status": "RELEASED", "reason": item.get("source"), "notional_krw": float(item["amount"]), "cash_before_krw": cash - float(item["amount"]), "cash_after_krw": cash}
                remember(e)
        exited_tickers = exited_tickers_by_day.setdefault(day, set())

        # Execute scheduled exits first. A support-day exit is recorded after cutoff, never in metrics.
        due_exits = [
            (ticker, pos) for ticker, pos in positions.items()
            if pos.get("asset_kind") == "stock"
            and parse_date(pos["record"].get("exit_execution_date")) == day
            and str(pos["record"].get("trade_status", "")) == "REALIZED"
        ]
        due_exits.sort(key=lambda item: (item[0], signal_key(item[1]["record"])))
        for ticker, pos in due_exits:
            row = pos["record"]
            event = event_base(row, day, "EXIT")
            frame = pos["frame"]
            reference = exact_price(frame, day, "open")
            expected = numeric(row.get("exit_price"))
            if reference is None or expected is None or not math.isclose(reference, expected, rel_tol=0, abs_tol=0.011):
                event.update(event_status="UNRESOLVED", reason="MISSING_OR_MISMATCHED_EXACT_EXIT_OPEN", reference_price=reference, shares=pos["shares"])
                unresolved_trade_events.append(event)
                issue_rows.append({"kind": "EXIT_PRICE_UNRESOLVED", "window_id": ctx.window_id, "candidate_id": event["candidate_id"], "date": event["execution_date"]})
                remember(event)
                continue
            shares = float(pos["shares"])
            fill = reference * (1.0 - SELL_SLIPPAGE_RATE)
            notional = fill * shares
            commission = notional * COMMISSION_RATE
            proceeds = notional - commission
            release_date = next_session.get(day)
            if release_date is not None:
                pending_sales[release_date] = pending_sales.get(release_date, 0.0) + proceeds
            else:
                # Last support session has no further eligible entry; this remains a pending receivable.
                pass
            cash_before = cash
            del positions[ticker]
            exited_tickers.add(ticker)
            total_sell_notional += notional if day <= effective_end else 0.0
            total_commission += commission if day <= effective_end else 0.0
            impact = abs(reference - fill) * shares
            total_slippage += impact if day <= effective_end else 0.0
            net_return = (proceeds - float(pos["buy_cost"])) / float(pos["buy_cost"])
            if day <= effective_end:
                realized_exits += 1
                executed_closed_returns.append(net_return)
                holding_sessions.append(sum(pos["entry_date"] <= session <= day for session in calendar_dates if session <= effective_end))
            event.update(event_status="EXECUTED", reason="STRATEGY_EXIT", reference_price=reference, fill_price=fill, shares=shares, notional_krw=notional, commission_krw=commission, slippage_impact_krw=impact, cash_before_krw=cash_before, cash_after_krw=cash, pending_sale_proceeds_krw=sum(pending_sales.values()), net_return_pct=net_return * 100.0, post_cutoff=day > effective_end)
            remember(event)

        # Apply explicit authoritative corporate lifecycle actions to positions.
        actions_due: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for ticker, pos in list(positions.items()):
            action = pos.get("lifecycle_action")
            action_day = pos.get("lifecycle_action_day")
            if action and not pos.get("lifecycle_applied") and action_day == day:
                actions_due.append((ticker, pos, action))
        actions_due.sort(key=lambda item: (item[0], signal_key(item[1]["record"])))
        for ticker, pos, action in actions_due:
            row = pos["record"]
            action_kind = action.get("kind")
            action_event = {"window_id": ctx.window_id, "candidate_id": "|".join(signal_key(row)), "pair_id": row.get("pair_id"), "ticker": ticker, "isu_cd": row.get("isu_cd"), "execution_date": day.strftime("%Y-%m-%d"), "event_type": action_kind, "event_status": None, "reason": action.get("reason") or action.get("evidence_id"), "cash_before_krw": cash, "cash_after_krw": cash, "shares": pos["shares"], "notional_krw": 0.0, "evidence_id": action.get("evidence_id")}
            if action_kind in {"CASH_SETTLEMENT", "CASH_RECEIVABLE"}:
                amount = float(pos["shares"]) * float(action["cash_per_share"])
                payment_date = action.get("payment_date")
                release_date = next_session_on_or_after(calendar_dates, pd.Timestamp(payment_date)) if payment_date is not None else None
                if release_date is not None and release_date <= effective_end:
                    if release_date <= day:
                        cash += amount
                    else:
                        rid = action_event["candidate_id"] + "|" + str(action.get("evidence_id") or action_kind)
                        cash_receivables[rid] = {"amount": amount, "release_date": release_date, "ticker": ticker, "isu_cd": row.get("isu_cd"), "candidate_id": action_event["candidate_id"], "source": action.get("source")}
                else:
                    rid = action_event["candidate_id"] + "|" + str(action.get("evidence_id") or action_kind)
                    cash_receivables[rid] = {"amount": amount, "release_date": None, "ticker": ticker, "isu_cd": row.get("isu_cd"), "candidate_id": action_event["candidate_id"], "source": action.get("source")}
                del positions[ticker]
                exited_tickers.add(ticker)
                action_event.update(event_type=action_kind, event_status="RECEIVABLE_CREATED", reason=action.get("source"), notional_krw=amount, cash_after_krw=cash, payment_date=str(payment_date.date()) if payment_date is not None else None)
                if action_kind == "CASH_SETTLEMENT" and day <= effective_end:
                    lifecycle_closures += 1
                    if release_date is not None and release_date <= day:
                        executed_closed_returns.append((amount - float(pos["buy_cost"])) / float(pos["buy_cost"]))
                        holding_sessions.append(sum(pos["entry_date"] <= session <= day for session in calendar_dates if session <= effective_end))
                elif action_kind == "CASH_RECEIVABLE":
                    lifecycle_closures += 1
            elif action_kind == "SUCCESSOR":
                successor_ticker = str(action["ticker"]).zfill(6)
                successor_isu = str(action["isu_cd"]).strip().upper()
                available = next_session_on_or_after(calendar_dates, pd.Timestamp(action["available_date"]))
                if available is None:
                    action_event.update(event_status="UNRESOLVED", reason="SUCCESSOR_OUTSIDE_SUPPORTED_WINDOW")
                    unresolved_trade_events.append(action_event)
                    pos["asset_kind"] = "transition_unresolved"
                    pos["lifecycle_applied"] = True
                    issue_rows.append({"kind": "SUCCESSOR_UNRESOLVED", "window_id": ctx.window_id, "candidate_id": action_event["candidate_id"], "date": action_event["execution_date"]})
                elif available <= day:
                    if successor_ticker in positions and successor_ticker != ticker:
                        action_event.update(event_status="UNRESOLVED", reason="SUCCESSOR_TICKER_ALREADY_ACTIVE")
                        unresolved_trade_events.append(action_event)
                        pos["asset_kind"] = "transition_unresolved"
                        pos["lifecycle_applied"] = True
                        issue_rows.append({"kind": "SUCCESSOR_TICKER_COLLISION", "window_id": ctx.window_id, "candidate_id": action_event["candidate_id"]})
                    else:
                        frame = successor_daily(ctx, successor_ticker, successor_isu, available)
                        ctx.frame_hashes[f"successor|{successor_ticker}|{successor_isu}"] = canonical_frame_hash(frame)
                        pos.update(asset_kind="stock", ticker=successor_ticker, current_isu_cd=successor_isu, shares=float(pos["shares"]) * float(action["shares_per_source_share"]), frame=frame, lifecycle_applied=True)
                        if successor_ticker != ticker:
                            del positions[ticker]
                            positions[successor_ticker] = pos
                            exited_tickers.add(ticker)
                        action_event.update(event_status="CONVERTED", reason="AUTHORITATIVE_SUCCESSOR_POSITION", shares=pos["shares"], successor_ticker=successor_ticker)
                else:
                    action_event.update(event_status="UNRESOLVED", reason="SUCCESSOR_NOT_AVAILABLE_ON_EFFECTIVE_SESSION")
                    unresolved_trade_events.append(action_event)
                    pos["asset_kind"] = "transition_unresolved"
                    pos["lifecycle_applied"] = True
                    issue_rows.append({"kind": "SUCCESSOR_AVAILABILITY_GAP", "window_id": ctx.window_id, "candidate_id": action_event["candidate_id"], "date": action_event["execution_date"], "available_date": available.strftime("%Y-%m-%d")})
                action_event["cash_after_krw"] = cash
            else:
                action_event.update(event_status="UNRESOLVED", reason=action.get("reason") or "LIFECYCLE_TERMINAL_VALUE_UNRESOLVED")
                unresolved_trade_events.append(action_event)
                pos["asset_kind"] = "stock"
                pos["lifecycle_applied"] = True
                life_event_diagnostics.append(action_event)
            remember(action_event)

        # Use each pre-fixed CONTROL row once. Cash skips never regenerate a signal or replay strategy state.
        for key, row in active_candidate_rows(day):
            ticker = str(row.get("ticker", "")).zfill(6)
            candidate = signal_key(row)
            candidate_id = "|".join(candidate)
            event = event_base(row, day, "ENTRY")
            frame, reference, price_problem = _record_entry_fill(ctx, row, day)
            if price_problem:
                event.update(event_status="UNRESOLVED", reason=price_problem, reference_price=reference)
                unresolved_trade_events.append(event)
                issue_rows.append({"kind": "ENTRY_PRICE_UNRESOLVED", "window_id": ctx.window_id, "candidate_id": candidate_id, "date": event["execution_date"], "reason": price_problem})
                decision_status[candidate] = "UNRESOLVED"
                remember(event)
                continue
            if ticker in exited_tickers:
                event.update(event_status="SKIPPED_SAME_OPEN_EXIT_REENTRY", reason="SAME_OPEN_REENTRY_FORBIDDEN", reference_price=reference)
                decision_status[candidate] = "NONCASH_SKIP"
                remember(event)
                continue
            if ticker in positions:
                event.update(event_status="SKIPPED_DUPLICATE_ACTIVE_TICKER", reason="SAME_TICKER_POSITION_ALREADY_ACTIVE", reference_price=reference)
                issue_rows.append({"kind": "DUPLICATE_ACTIVE_TICKER_SIGNAL", "window_id": ctx.window_id, "candidate_id": candidate_id, "date": event["execution_date"]})
                decision_status[candidate] = "NONCASH_SKIP"
                remember(event)
                continue
            shares = int(math.floor((BUY_CASH_BUDGET + 1e-9) / (reference * (1.0 + BUY_SLIPPAGE_RATE) * (1.0 + COMMISSION_RATE))))
            if shares <= 0:
                event.update(event_status="SKIPPED_ZERO_SHARES", reason="NO_WHOLE_SHARE_WITHIN_BUY_BUDGET", reference_price=reference, shares=0)
                issue_rows.append({"kind": "ZERO_SHARE_SIGNAL_LIFECYCLE_UNRESOLVED", "window_id": ctx.window_id, "candidate_id": candidate_id, "date": event["execution_date"]})
                decision_status[candidate] = "NONCASH_SKIP"
                remember(event)
                continue
            eligible_attempts += 1
            buy_fill = reference * (1.0 + BUY_SLIPPAGE_RATE)
            buy_notional = buy_fill * shares
            buy_fee = buy_notional * COMMISSION_RATE
            total_cost = buy_notional + buy_fee
            if total_cost > cash + 1e-6:
                cash_skips += 1
                event.update(event_status="SKIPPED_CASH_UNAVAILABLE", reason="INSUFFICIENT_AVAILABLE_CASH", reference_price=reference, fill_price=buy_fill, shares=shares, notional_krw=buy_notional, commission_krw=buy_fee, required_total_buy_cost_krw=total_cost, cash_before_krw=cash, cash_after_krw=cash)
                decision_status[candidate] = "CASH_SKIP"
                remember(event)
                continue

            cash_before = cash
            cash -= total_cost
            life_action = make_lifecycle_action(ctx, row)
            lifecycle_action_day = _row_action_day(life_action, calendar_dates)
            position = {
                "record": dict(row), "candidate_id": candidate_id, "identity_key": key,
                "ticker": ticker, "current_isu_cd": key[1], "asset_kind": "stock",
                "shares": float(shares), "entry_date": day, "buy_cost": total_cost,
                "frame": frame, "lifecycle_action": life_action,
                "lifecycle_action_day": lifecycle_action_day, "lifecycle_applied": False,
            }
            positions[ticker] = position
            total_buy_notional += buy_notional
            total_commission += buy_fee
            buy_impact = abs(buy_fill - reference) * shares
            total_slippage += buy_impact
            executed_entries += 1
            event.update(event_status="EXECUTED", reason="V2_CONTROL_SIGNAL", reference_price=reference, fill_price=buy_fill, shares=shares, notional_krw=buy_notional, commission_krw=buy_fee, slippage_impact_krw=buy_impact, cash_before_krw=cash_before, cash_after_krw=cash, required_total_buy_cost_krw=total_cost)
            decision_status[candidate] = "EXECUTED"
            remember(event)
        # Daily valuation permits only the evidence-backed KRX placeholder carry in the sealed plan.
        if day <= effective_end:
            pending_total = sum(pending_sales.values())
            receivable_total = sum(float(item["amount"]) for item in cash_receivables.values())
            invested_value = 0.0
            day_missing: list[dict[str, Any]] = []
            day_carry_count = 0
            for ticker, pos in sorted(positions.items()):
                if pos.get("asset_kind") == "transition_unresolved":
                    day_missing.append({"window_id": ctx.window_id, "candidate_id": pos["candidate_id"], "ticker": ticker, "isu_cd": pos.get("current_isu_cd"), "date": day.strftime("%Y-%m-%d"), "reason": "UNRESOLVED_CORPORATE_SUCCESSOR_VALUE"})
                    continue
                mark, carry_audit = mark_price_with_official_carry(ctx, pos, day)
                if carry_audit is not None:
                    valuation_carry_audit.append(carry_audit)
                    day_carry_count += int(bool(carry_audit.get("carry_applied")))
                if mark is None:
                    day_missing.append({"window_id": ctx.window_id, "candidate_id": pos["candidate_id"], "ticker": ticker, "isu_cd": pos.get("current_isu_cd"), "date": day.strftime("%Y-%m-%d"), "reason": "UNRESOLVED_DAILY_MARK", "evidence_state": None if carry_audit is None else carry_audit.get("evidence_state")})
                else:
                    invested_value += float(pos["shares"]) * mark
            missing_marks.extend(day_missing)
            equity = None if day_missing else cash + pending_total + receivable_total + invested_value
            if equity is not None:
                cash_conservation_pass = cash_conservation_pass and abs(equity - cash - pending_total - receivable_total - invested_value) <= 1e-6
            cash_total_equivalent = cash + pending_total + receivable_total
            daily_equity.append({
                "date": day.strftime("%Y-%m-%d"),
                "window_id": ctx.window_id,
                "cash": cash,
                "pending_sale_proceeds": pending_total,
                "cash_receivables": receivable_total,
                "invested_market_value": None if day_missing else invested_value,
                "equity": equity,
                "capital_utilization": None if equity is None or not equity else invested_value / equity,
                "cash_ratio": None if equity is None or not equity else cash_total_equivalent / equity,
                "open_stock_positions": sum(1 for pos in positions.values() if pos.get("asset_kind") in {"stock", "transition_unresolved"}),
                "valuation_missing_count": len(day_missing),
                "valuation_missing_ids": [item["candidate_id"] for item in day_missing],
                "valuation_carry_count": day_carry_count,
            })
            if day == effective_end:
                snapshot_at_cutoff = {
                    "equity": equity,
                    "open_stock_positions": sum(1 for pos in positions.values() if pos.get("asset_kind") in {"stock", "transition_unresolved"}),
                    "open_candidate_ids": sorted(pos["candidate_id"] for pos in positions.values()),
                    "receivables": receivable_total,
                    "invested_value": None if day_missing else invested_value,
                }

        if day == execution_support and day > effective_end:
            # There are no new exposure events after cutoff; only support-day exits were processed above.
            continue

    if snapshot_at_cutoff is None or not daily_equity:
        raise RuntimeError(f"PORTFOLIO_CUTOFF_SNAPSHOT_MISSING:{ctx.window_id}")
    if not cash_conservation_pass:
        issue_rows.append({"kind": "CASH_CONSERVATION_FAILURE", "window_id": ctx.window_id})

    # Ensure each in-window pre-fixed CONTROL entry row was decided exactly once.
    remaining = [
        signal_key(row) for stream in streams.values() for row in stream
        if parse_date(row.get("entry_execution_date")) <= effective_end
        and signal_key(row) not in decision_status
    ]
    if remaining:
        raise RuntimeError(f"UNPROCESSED_IN_WINDOW_ENTRY_SIGNALS:{ctx.window_id}:{remaining[:5]}")

    daily_valuation_complete = not missing_marks
    final_equity = snapshot_at_cutoff["equity"]
    total_return = final_equity / INITIAL_CAPITAL - 1.0 if final_equity is not None else None
    days = max(1, int((effective_end - effective_start).days))
    cagr = ((final_equity / INITIAL_CAPITAL) ** (365.25 / days) - 1.0) if final_equity is not None and final_equity > 0 else None
    mdd = mdd_details(daily_equity, effective_start)
    utilizations = [float(item["capital_utilization"]) for item in daily_equity if item.get("capital_utilization") is not None]
    cash_ratios = [float(item["cash_ratio"]) for item in daily_equity if item.get("cash_ratio") is not None]
    return_tails = {
        "ge_pos_50_count": sum(value >= 0.5 for value in executed_closed_returns),
        "ge_pos_100_count": sum(value >= 1.0 for value in executed_closed_returns),
        "le_neg_30_count": sum(value <= -0.3 for value in executed_closed_returns),
        "le_neg_40_count": sum(value <= -0.4 for value in executed_closed_returns),
        "le_neg_50_count": sum(value <= -0.5 for value in executed_closed_returns),
        "le_neg_60_count": sum(value <= -0.6 for value in executed_closed_returns),
    }
    unresolved_count = len(missing_marks) + len(unresolved_trade_events) + len([item for item in issue_rows if "UNRESOLVED" in str(item.get("kind", "")) or "MISMATCH" in str(item.get("kind", ""))])
    metrics = {
        "window_id": ctx.window_id,
        "effective_start": effective_start.strftime("%Y-%m-%d"),
        "effective_end": effective_end.strftime("%Y-%m-%d"),
        "execution_support": execution_support.strftime("%Y-%m-%d"),
        "initial_capital_krw": INITIAL_CAPITAL,
        "ending_equity_krw": final_equity,
        "total_return_pct": None if total_return is None else total_return * 100.0,
        "cagr_pct": None if cagr is None else cagr * 100.0,
        **mdd,
        "eligible_entry_attempts": eligible_attempts,
        "cash_shortage_skipped_entries": cash_skips,
        "cash_shortage_skip_rate_pct": None if eligible_attempts == 0 else cash_skips / eligible_attempts * 100.0,
        "average_capital_utilization_pct": None if not utilizations else float(np.mean(utilizations)) * 100.0,
        "maximum_capital_utilization_pct": None if not utilizations else max(utilizations) * 100.0,
        "average_cash_ratio_pct": None if not cash_ratios else float(np.mean(cash_ratios)) * 100.0,
        "average_concurrent_positions": float(np.mean([item["open_stock_positions"] for item in daily_equity])) if daily_equity else None,
        "maximum_concurrent_positions": max((int(item["open_stock_positions"]) for item in daily_equity), default=0),
        "executed_entry_count": executed_entries,
        "same_open_exit_reentry_skipped_count": sum(item.get("event_status") == "SKIPPED_SAME_OPEN_EXIT_REENTRY" for item in events),
        "realized_exit_count": realized_exits,
        "lifecycle_closure_count": lifecycle_closures,
        "open_at_cutoff_count": snapshot_at_cutoff["open_stock_positions"],
        "open_at_cutoff_candidate_ids": snapshot_at_cutoff["open_candidate_ids"],
        "win_rate_pct": None if not executed_closed_returns else 100.0 * sum(value > 0 for value in executed_closed_returns) / len(executed_closed_returns),
        "average_holding_trading_sessions": None if not holding_sessions else float(np.mean(holding_sessions)),
        "median_holding_trading_sessions": None if not holding_sessions else float(np.median(holding_sessions)),
        "turnover_krw": total_buy_notional + total_sell_notional,
        "turnover_multiple": (total_buy_notional + total_sell_notional) / INITIAL_CAPITAL,
        "total_buy_notional_krw": total_buy_notional,
        "total_sell_notional_krw": total_sell_notional,
        "total_commissions_krw": total_commission,
        "total_slippage_impact_krw": total_slippage,
        "unresolved_count": unresolved_count,
        "exact_daily_marks_complete": not valuation_carry_audit and daily_valuation_complete,
        "daily_valuation_complete": daily_valuation_complete,
        "valuation_carry_count": sum(1 for item in valuation_carry_audit if item.get("carry_applied")),
        "valuation_unresolved_count": len(missing_marks),
        "cash_conservation_pass": cash_conservation_pass,
        "source_or_execution_issue_count": len(issue_rows),
        **return_tails,
    }
    gates = build_gate_results(ctx.window_id, metrics, issue_rows, unresolved_trade_events, missing_marks)
    return {
        "metrics": metrics,
        "gates": gates,
        "daily_equity": daily_equity,
        "events": events,
        "cash_events": cash_events,
        "valuation_carry_audit": valuation_carry_audit,
        "issues": issue_rows,
        "missing_marks": missing_marks,
        "unresolved_trade_events": unresolved_trade_events,
        "lifecycle_diagnostics": life_event_diagnostics,
        "closed_returns": executed_closed_returns,
        "holding_sessions": holding_sessions,
        "source_details": ctx.source_details,
        "frame_hashes": ctx.frame_hashes,
    }


def build_gate_results(
    window_id: str,
    metrics: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    unresolved_events: Sequence[Mapping[str, Any]],
    missing_marks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    structural = [item for item in issues if item.get("kind") in {"DUPLICATE_SIGNAL_ID", "DUPLICATE_IDENTITY_SIGNAL", "ENTRY_BEFORE_EFFECTIVE_START", "ENTRY_AFTER_EXECUTION_SUPPORT", "CASH_CONSERVATION_FAILURE", "DUPLICATE_ACTIVE_TICKER_SIGNAL", "PROCESSED_CONTROL_PREFIX_PARITY_FAILED", "SOURCE_CONTROL_PREFIX_PARITY_FAILED"}]
    check_issues = [item for item in issues if item not in structural]
    results.append({"window_id": window_id, "gate": "A", "status": "FAIL" if structural else ("CHECK_REQUIRED" if check_issues else "PASS"), "detail": f"structural={len(structural)}; unresolved={len(check_issues)}"})
    results.append({"window_id": window_id, "gate": "B", "status": "PASS", "detail": "All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract."})
    if metrics.get("total_return_pct") is None or metrics.get("cagr_pct") is None:
        c_status = "CHECK_REQUIRED"
    else:
        c_status = "PASS" if metrics["total_return_pct"] > 0 and metrics["cagr_pct"] > 0 else "FAIL"
    results.append({"window_id": window_id, "gate": "C", "status": c_status, "detail": f"total_return_pct={metrics.get('total_return_pct')}; cagr_pct={metrics.get('cagr_pct')}"})
    if metrics.get("mdd_pct") is None or missing_marks:
        d_status = "CHECK_REQUIRED"
    else:
        d_status = "PASS" if metrics["mdd_pct"] >= -35.0 else "FAIL"
    results.append({"window_id": window_id, "gate": "D", "status": d_status, "detail": f"mdd_pct={metrics.get('mdd_pct')}; unresolved_mark_gaps={len(missing_marks)}; approved_valuation_carries={metrics.get('valuation_carry_count')}"})
    rate = metrics.get("cash_shortage_skip_rate_pct")
    if rate is None:
        e_status = "CHECK_REQUIRED"
    else:
        e_status = "PASS" if rate < 55.0 else "FAIL"
    results.append({"window_id": window_id, "gate": "E", "status": e_status, "detail": f"cash_skipped={metrics.get('cash_shortage_skipped_entries')}; eligible_attempts={metrics.get('eligible_entry_attempts')}; rate_pct={rate}"})
    f_status = "CHECK_REQUIRED" if missing_marks or unresolved_events or check_issues else "PASS"
    results.append({"window_id": window_id, "gate": "F", "status": f_status, "detail": f"unresolved_daily_marks={len(missing_marks)}; approved_placeholder_carries={metrics.get('valuation_carry_count')}; unresolved_trade_events={len(unresolved_events)}; other_issues={len(check_issues)}"})
    return results


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def save_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        frame = pd.DataFrame(columns=["empty"])
    frame.to_csv(path, index=False, encoding="utf-8")


def core_source_hashes(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    fixed_paths = [
        "docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md",
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/validation/backtest_common_rules.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "src/trend_scanner/patterns/pattern_a_fast_evaluator.py",
        "src/trend_scanner/patterns/pattern_a_evaluator.py",
        "src/trend_scanner/universe/permanent_identity_exclusions.py",
        "src/trend_scanner/data/repository_v2_loader.py",
        "src/trend_scanner/data/repository_v2.py",
        "src/trend_scanner/data/krx_raw_stock_store.py",
        "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        "scripts/run_v2_official_adoption_revalidation_v02.py",
        "data/market/rolling_authority/manifest.json",
        "data/market/rolling_authority/merged_pit_intervals.json",
        "data/market/rolling_authority/merged_trading_calendar.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
    ]
    files = {rel: sha256_file(ROOT / rel) for rel in fixed_paths}
    if files[fixed_paths[0]] != PLAN_SHA256:
        raise RuntimeError("SEALED_PLAN_HASH_CHANGED")
    windows: dict[str, Any] = {}
    for window_id, result in results.items():
        detail = dict(result["source_details"])
        config = WINDOWS[window_id]
        detail["cert_path"] = config["cert"]
        detail["cert_sha256"] = config["cert_sha256"]
        detail["manifest_path"] = config["manifest"]
        detail["summary_path"] = config["summary"]
        detail["daily_frame_hashes"] = result.get("frame_hashes", {})
        detail["valuation_carry_audit_rows"] = result.get("valuation_carry_audit", [])
        unique_partitions: dict[tuple[Any, ...], dict[str, Any]] = {}
        for audit in result.get("valuation_carry_audit", []):
            key = (audit.get("market"), audit.get("valuation_date"), audit.get("raw_partition_file_sha256"), audit.get("raw_partition_content_sha256"))
            unique_partitions[key] = {
                "market": audit.get("market"),
                "date": audit.get("valuation_date"),
                "manifest_path": audit.get("raw_manifest_path"),
                "manifest_db_sha256": audit.get("raw_manifest_db_sha256"),
                "partition_path": audit.get("raw_partition_path"),
                "partition_file_sha256": audit.get("raw_partition_file_sha256"),
                "partition_content_sha256": audit.get("raw_partition_content_sha256"),
                "manifest_status": audit.get("raw_manifest_status"),
            }
        detail["raw_partitions_consulted"] = list(unique_partitions.values())
        windows[window_id] = detail
    references = {key: {"path": rel, "sha256": sha256_file(ROOT / rel)} for key, rel in REFERENCE_SUMMARIES.items()}
    return {
        "schema": "pattern_a_fast_v2_official_adoption_source_hashes_v02",
        "sealed_plan": {"path": str(PLAN_PATH.relative_to(ROOT)), "sha256": PLAN_SHA256, "commit": PLAN_COMMIT},
        "execution_script": {"path": "scripts/run_v2_official_adoption_revalidation_v02.py", "sha256": sha256_file(ROOT / "scripts/run_v2_official_adoption_revalidation_v02.py")},
        "fixed_sources": files,
        "window_sources": windows,
        "market_cap_1t_reference_only": references,
    }


def execution_contract() -> dict[str, Any]:
    return {
        "schema": "pattern_a_fast_v2_official_adoption_execution_contract_v02",
        "strategy_id": STRATEGY_ID,
        "mode": "EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY",
        "entry_signal_regeneration": False,
        "strategy_evaluation_rerun": False,
        "initial_capital_krw": INITIAL_CAPITAL,
        "per_trade_total_buy_cash_budget_krw": BUY_CASH_BUDGET,
        "buy_commission_rate": COMMISSION_RATE,
        "sell_commission_rate": COMMISSION_RATE,
        "buy_slippage_rate": BUY_SLIPPAGE_RATE,
        "sell_slippage_rate": SELL_SLIPPAGE_RATE,
        "sell_tax_rate": 0.0,
        "max_concurrent_positions": None,
        "partial_fill": False,
        "cash_shortage_policy": "SKIPPED_CASH_UNAVAILABLE_FULL_ORDER; decide this frozen CONTROL row once; do not regenerate signals or replay strategy state",
        "one_open_position_per_ticker": True,
        "pyramiding": False,
        "same_open_exit_reentry": False,
        "same_session_order": ["release prior-session settled sale proceeds", "normal exits sorted ticker then stable signal id", "corporate lifecycle event", "entries sorted ticker then (ISU_CD, signal date, execution date, trade id)"],
        "sale_proceeds_release": "next normal trading session after sell execution; remains a pending asset until release",
        "buy_share_formula": "floor(5000000 / (reference_open * 1.001 * 1.00015))",
        "buy_fill_formula": "reference_open * 1.001",
        "sell_fill_formula": "reference_open * 0.999",
        "costs": "All executed buy/sell commission and slippage reflected; tax excluded at 0%.",
        "valuation": "Repository V2 exact session close; missing close may carry the prior valid adjusted close only when a same-date/same-market COMPLETE KRX raw partition has the exact ticker row satisfying NON_TRADING_PLACEHOLDER_V01. Carry is daily valuation/MDD only and is fully audited.",
        "cutoff": "End-date close for all official metrics; next session is execution support for pre-cutoff exits only and is excluded from metrics and new entries.",
        "cash_shortage_denominator": "Pre-fixed CONTROL rows with valid in-window execution date, matching exact open, at least one affordable whole share, and no non-cash execution blocker; each row is counted at most once.",
        "cash_shortage_numerator": "Only full orders skipped for insufficient available cash.",
        "signal_population": "Only the certified frozen CONTROL ledger after current permanent-identity exclusions; no post-skip rows are synthesized or added.",
        "price_frame_workers": WORKERS,
        "portfolio_event_order": "Deterministic sequential application of daily cash and trade events.",
        "valuation_carry_audit": "valuation_carry_audit_<window>.csv records raw manifest/partition/file/content hashes, exact row values, placeholder predicate, prior adjusted close and age, and valuation-only usage flags.",
        "mdd": "Daily cutoff equity against the running prior/high-water peak; initial capital is the starting peak.",
        "cagr": "((ending equity / initial capital) ** (365.25 / elapsed calendar days) - 1) * 100.",
    }


def reference_metrics(path: Path) -> dict[str, Any]:
    summary = read_json(path)
    control = summary.get("portfolio", {}).get("control", {})
    return {
        "status": summary.get("status"),
        "total_return_pct": control.get("cumulative_return_pct"),
        "cagr_pct": control.get("CAGR_pct"),
        "mdd_pct": control.get("mdd_pct"),
        "cash_shortage_skipped_entries": control.get("cash_shortage_skipped_entries"),
        "cash_shortage_skip_rate_pct": None,
        "unresolved_count": control.get("unresolved_count"),
        "universe": "market-cap >= 1T KRW; reference-only, not official",
    }


def final_verdict(gates: Sequence[Mapping[str, Any]]) -> str:
    statuses = [str(item["status"]) for item in gates]
    if "CHECK_REQUIRED" in statuses:
        return "HOLD"
    if "FAIL" in statuses:
        return "NOT_ADOPTED"
    return "OFFICIAL_STRATEGY_ADOPTED"


def render_report(
    verdict: str,
    metrics: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
    source_hashes: Mapping[str, Any],
    plan_commit: str,
    result_commit: str | None = None,
    head: str | None = None,
    origin_main: str | None = None,
    worktree_clean: bool | None = None,
) -> str:
    lines = [
        "# A FAST Core V2 공식 전략 공통 채택 기준 재심사 결과",
        "",
        f"- 최종 판정: **{verdict}**",
        f"- 계획 commit: `{plan_commit}` (계획 SHA-256 `{PLAN_SHA256}`)",
        f"- 결과 commit: `{result_commit or 'pending'}`",
        f"- 종료 HEAD / origin/main: `{head or 'pending'}` / `{origin_main or 'pending'}`; clean: `{worktree_clean}`",
        "",
        "## 다섯 표준 기간 결과",
        "",
        "| 기간 | 총수익률 | CAGR | MDD | 현금 부족률 | A | B | C | D | E | F |",
        "|---|---:|---:|---:|---:|---|---|---|---|---|---|",
    ]
    gate_by_window: dict[str, dict[str, str]] = {}
    for gate in gates:
        gate_by_window.setdefault(str(gate["window_id"]), {})[str(gate["gate"])] = str(gate["status"])
    for row in metrics:
        wid = str(row["window_id"])
        def pct(value: Any) -> str:
            return "CHECK_REQUIRED" if value is None else f"{float(value):.2f}%"
        g = gate_by_window.get(wid, {})
        lines.append("| " + " | ".join([
            wid,
            pct(row.get("total_return_pct")),
            pct(row.get("cagr_pct")),
            pct(row.get("mdd_pct")),
            pct(row.get("cash_shortage_skip_rate_pct")),
            *(g.get(key, "CHECK_REQUIRED") for key in "ABCDEF"),
        ]) + " |")
    lines.extend(["", "## 기간별 진단", "", "| 기간 | 종료 자산 | MDD 최고점/저점/회복 | 적격 시도 | 현금 누락 | 활용도 평균/최대 | 보유 평균/최대 | 진입/청산/미청산 | 수수료 | 슬리피지 | 평가 carry | 미해결 |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in metrics:
        mdd_period = f"{row.get('mdd_peak_date')} / {row.get('mdd_trough_date')} / {row.get('mdd_recovery_date') or '미회복'}"
        utilization = f"{row.get('average_capital_utilization_pct'):.2f}% / {row.get('maximum_capital_utilization_pct'):.2f}%" if row.get('average_capital_utilization_pct') is not None and row.get('maximum_capital_utilization_pct') is not None else "CHECK_REQUIRED"
        positions = f"{row.get('average_concurrent_positions'):.2f} / {row.get('maximum_concurrent_positions')}" if row.get('average_concurrent_positions') is not None else "CHECK_REQUIRED"
        lines.append(f"| {row['window_id']} | {row.get('ending_equity_krw')} | {mdd_period} | {row.get('eligible_entry_attempts')} | {row.get('cash_shortage_skipped_entries')} / {row.get('eligible_entry_attempts')} | {utilization} | {positions} | {row.get('executed_entry_count')} / {row.get('realized_exit_count')} / {row.get('open_at_cutoff_count')} | {row.get('total_commissions_krw')} | {row.get('total_slippage_impact_krw')} | {row.get('valuation_carry_count')} | {row.get('unresolved_count')} |")
    lines.extend(["", "## 기준 판정 근거", ""])
    for gate in gates:
        lines.append(f"- {gate['window_id']} {gate['gate']}: **{gate['status']}** — {gate['detail']}")
    lines.extend(["", "## 사전 확정 원장 기준 E 및 평가 carry 감사", "", "각 인증 CONTROL 원장 행은 최대 한 번만 포트폴리오에 전달했고, 현금 부족 뒤 신호나 종목 상태를 재생성하지 않았어. E는 정확한 체결 시가와 1주 이상 주문 가능성이 확인된 비차단 행만 분모로 삼았어. 일별 종가 carry는 같은 날짜·시장 KRX `COMPLETE` partition의 정확한 종목 행이 공식 `NON_TRADING_PLACEHOLDER_V01` 조건을 만족한 경우에만 적용했어. 모든 적용·미적용 확인은 `valuation_carry_audit_<window>.csv`에 원천 해시와 직전 조정 종가를 남겼어.", "", "## 시가총액 1조 이상 기존 결과(참고 전용)", "", "유니버스가 다른 참고 자료라 공식 A~F 판정이나 성과 우열 근거로 사용하지 않았어.", "", "| 기간 | 상태 | 총수익률 | CAGR | MDD | 현금 누락 수 | 현금 누락률 | 미해결 | 유니버스 |", "|---|---|---:|---:|---:|---:|---:|---:|---|"])
    for period in ("P2-1", "P2-2", "P3-2"):
        ref = references[period]
        def refpct(value: Any) -> str:
            return "N/A" if value is None else f"{float(value):.2f}%"
        lines.append(f"| {period} | {ref.get('status')} | {refpct(ref.get('total_return_pct'))} | {refpct(ref.get('cagr_pct'))} | {refpct(ref.get('mdd_pct'))} | {ref.get('cash_shortage_skipped_entries')} | N/A (기존 원천에 동일 분모가 없음) | {ref.get('unresolved_count')} | 시총 >= 1조원 |")
    lines.extend(["", "## 원천·재현 정보", "", f"- 계획 문서: [`{PLAN_PATH.relative_to(ROOT)}`](../../../../../docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md), commit `{plan_commit}`, SHA-256 `{PLAN_SHA256}`.", f"- source hash manifest: `source_hashes.json`; 인증 원장·실제 로드한 일봉 canonical hash·조회한 KRX 원자료 partition 해시를 포함했어.", f"- execution contract: `execution_contract.json`; 상세 이벤트·현금·평가 carry는 기간별 CSV에 있어.", f"- 공식 산출물 경로: `{OUT_DIR.relative_to(ROOT)}`.", ""])
    return "\n".join(lines)


def write_sample(ctx: WindowContext, out: Mapping[str, Any], seconds: float, sample_end: pd.Timestamp, sample_entries: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sample = {
        "schema": "pattern_a_fast_v2_official_adoption_sample_v02",
        "sample_only": True,
        "not_an_official_window_result": True,
        "window_id": ctx.window_id,
        "sample_end": sample_end.strftime("%Y-%m-%d"),
        "source_entries_in_sample": sample_entries,
        "sample_wall_seconds": seconds,
        "rough_linear_full_window_seconds": None if sample_entries == 0 else seconds * (ctx.source_details["rows_after_permanent_exclusions"] / sample_entries),
        "price_frame_workers": WORKERS,
        "portfolio_event_workers": 1,
        "metrics": out["metrics"],
        "gates": out["gates"],
        "source_details": ctx.source_details,
        "frame_hashes": out["frame_hashes"],
        "valuation_carry_rows": len(out["valuation_carry_audit"]),
        "cash_event_rows": len(out["cash_events"]),
        "missing_mark_count": len(out["missing_marks"]),
    }
    save_json(OUT_DIR / "sample_benchmark.json", sample)
    save_csv(OUT_DIR / "sample_daily_equity.csv", out["daily_equity"])
    save_csv(OUT_DIR / "sample_cash_events.csv", out["cash_events"])
    save_csv(OUT_DIR / "sample_valuation_carry_audit.csv", out["valuation_carry_audit"])
    save_csv(OUT_DIR / "sample_missing_marks.csv", out["missing_marks"])


def run_sample() -> dict[str, Any]:
    ctx = build_window_context("P2-1")
    sessions = [pd.Timestamp(d).normalize() for d in ctx.run.calendar.trading_dates if pd.Timestamp(ctx.run.window.effective_start).normalize() <= pd.Timestamp(d).normalize() <= pd.Timestamp(ctx.run.window.effective_end).normalize()]
    if len(sessions) < 62:
        raise RuntimeError("SAMPLE_CALENDAR_TOO_SHORT")
    sample_end = sessions[59]
    sample_support = sessions[60]
    ctx.run = replace(ctx.run, window=replace(ctx.run.window, effective_end=sample_end, execution_support=sample_support))
    streams, issues = scope_streams(ctx, ctx.source_rows, sample_end)
    started = time.perf_counter()
    preload_identity_frames(ctx, streams)
    output = portfolio_replay(ctx, streams, issues)
    elapsed = time.perf_counter() - started
    sample_entry_count = sum(len(rows) for rows in streams.values())
    write_sample(ctx, output, elapsed, sample_end, sample_entry_count)
    print(json.dumps({
        "sample_end": sample_end.strftime("%Y-%m-%d"),
        "sample_entries": sample_entry_count,
        "cash_skips": output["metrics"]["cash_shortage_skipped_entries"],
        "approved_valuation_carries": output["metrics"]["valuation_carry_count"],
        "unresolved_valuation_marks": output["metrics"]["valuation_unresolved_count"],
        "price_frame_workers": WORKERS,
        "portfolio_event_workers": 1,
        "sample_wall_seconds": round(elapsed, 3),
        "rough_linear_full_period_seconds": None if sample_entry_count == 0 else round(elapsed * ctx.source_details["rows_after_permanent_exclusions"] / sample_entry_count, 1),
        "exact_mark_gaps": len(output["missing_marks"]),
        "source_rows_after_exclusions": ctx.source_details["rows_after_permanent_exclusions"],
    }, ensure_ascii=False, indent=2), flush=True)
    return output


def run_full() -> dict[str, Any]:
    started_all = time.perf_counter()
    outputs: dict[str, dict[str, Any]] = {}
    metrics: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for window_id in ("P1", "P2-1", "P2-2", "P3-1", "P3-2"):
        window_started = time.perf_counter()
        print(f"[{window_id}] load certified CONTROL and Repository V2 authority", flush=True)
        ctx = build_window_context(window_id)
        streams, issues = scope_streams(ctx, ctx.source_rows, ctx.run.window.effective_end)
        print(f"[{window_id}] source rows={ctx.source_details['rows_after_permanent_exclusions']}; identities={len(streams)}; frame workers={WORKERS}; portfolio event workers=1", flush=True)
        preload_identity_frames(ctx, streams)
        output = portfolio_replay(ctx, streams, issues)
        output["wall_seconds"] = time.perf_counter() - window_started
        outputs[window_id] = output
        metrics.append(output["metrics"])
        gates.extend(output["gates"])
        save_csv(OUT_DIR / f"daily_equity_{window_id.lower().replace('-', '_')}.csv", output["daily_equity"])
        save_csv(OUT_DIR / f"portfolio_events_{window_id.lower().replace('-', '_')}.csv", output["events"])
        save_csv(OUT_DIR / f"cash_events_{window_id.lower().replace('-', '_')}.csv", output["cash_events"])
        save_csv(OUT_DIR / f"valuation_carry_audit_{window_id.lower().replace('-', '_')}.csv", output["valuation_carry_audit"])
        save_csv(OUT_DIR / f"missing_marks_{window_id.lower().replace('-', '_')}.csv", output["missing_marks"])
        save_csv(OUT_DIR / f"unresolved_events_{window_id.lower().replace('-', '_')}.csv", output["unresolved_trade_events"])
        print(f"[{window_id}] done {output['wall_seconds']:.1f}s; cash skips={output['metrics']['cash_shortage_skipped_entries']}; unresolved={output['metrics']['unresolved_count']}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    save_csv(OUT_DIR / "window_metrics.csv", metrics)
    save_csv(OUT_DIR / "gate_results.csv", gates)
    all_cash = [event for result in outputs.values() for event in result["cash_events"]]
    all_carries = [item for result in outputs.values() for item in result["valuation_carry_audit"]]
    all_issues = [item for result in outputs.values() for item in result["issues"]]
    save_csv(OUT_DIR / "cash_events.csv", all_cash)
    save_csv(OUT_DIR / "valuation_carry_audit.csv", all_carries)
    save_csv(OUT_DIR / "integrity_issues.csv", all_issues)
    save_json(OUT_DIR / "execution_contract.json", execution_contract())
    references = {period: reference_metrics(ROOT / path) for period, path in REFERENCE_SUMMARIES.items()}
    verdict = final_verdict(gates)
    source_hashes = core_source_hashes(outputs)
    save_json(OUT_DIR / "source_hashes.json", source_hashes)
    summary = {
        "schema": "pattern_a_fast_v2_official_adoption_revalidation_summary_v02",
        "strategy_id": STRATEGY_ID,
        "verdict": verdict,
        "plan_commit": PLAN_COMMIT,
        "plan_sha256": PLAN_SHA256,
        "price_frame_workers": WORKERS,
        "portfolio_event_workers": 1,
        "metrics_by_window": {row["window_id"]: row for row in metrics},
        "gate_results": gates,
        "source_certification": {window_id: output["source_details"] for window_id, output in outputs.items()},
        "reference_only_market_cap_1t_results": references,
        "valuation_carry_audit": {window_id: {"rows": len(output["valuation_carry_audit"]), "applied": output["metrics"]["valuation_carry_count"], "unresolved_daily_marks": output["metrics"]["valuation_unresolved_count"]} for window_id, output in outputs.items()},
        "source_hashes_path": str((OUT_DIR / "source_hashes.json").relative_to(ROOT)),
        "execution_contract_path": str((OUT_DIR / "execution_contract.json").relative_to(ROOT)),
        "total_wall_seconds": time.perf_counter() - started_all,
    }
    save_json(OUT_DIR / "summary.json", summary)
    report = render_report(verdict, metrics, gates, references, source_hashes, PLAN_COMMIT)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    return {"verdict": verdict, "summary": summary, "metrics": metrics, "gates": gates, "outputs": outputs, "references": references}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", action="store_true", help="Run the short P2-1 sample benchmark only.")
    group.add_argument("--run", action="store_true", help="Run all five official revalidation windows.")
    args = parser.parse_args()
    if not PLAN_PATH.is_file() or sha256_file(PLAN_PATH) != PLAN_SHA256:
        raise RuntimeError("SEALED_PLAN_MISSING_OR_HASH_MISMATCH")
    if args.sample:
        run_sample()
    else:
        run_full()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
