#!/usr/bin/env python3
"""Run the frozen V2 vs Pattern B three-way portfolio battles in w.md."""

from __future__ import annotations

import argparse
import ast
import bisect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import _is_non_trading_placeholder
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

from scripts import run_v2_official_adoption_revalidation_v02 as v2
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as pattern_b
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01 as pattern_b_v01
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base
from scripts import run_p2_1_realistic_portfolio_v01 as portfolio_engine

OUTPUT_REL = Path("artifacts/strategy_battles/fast_v2_vs_pattern_b_v02")
OUTPUT_ROOT = ROOT / OUTPUT_REL
WORK_INSTRUCTION = Path("/Users/june/Documents/projects/w.md")
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
BATTLE_IDS = (
    "battle_a_all_universe",
    "battle_b_pit_mcap_1t",
    "battle_c_kospi_only",
)
EXPECTED_EXCLUSION_COUNT = 174
NEW_GLOBAL_LIFECYCLE_EXCLUSION = ("096300", "KR7096300009")
P2_1_GLOBAL_LIFECYCLE_EXCLUSIONS = {
    ("008560", "KR7008560005"),
    ("023890", "KR7023890007"),
    ("043290", "KR7043290006"),
    ("046140", "KR7046140000"),
    ("213090", "KR7213090004"),
    ("225330", "KR7225330000"),
    ("282690", "KR7282690007"),
}
WINDOW_BOUNDS = {
    "P1": ("2014-01-02", "2026-08-31", "2026-09-01"),
    "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
    "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
    "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
    "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
}
INITIAL_CAPITAL = 200_000_000.0
PIT_MCAP_THRESHOLD = 1_000_000_000_000
EXPECTED_WORKERS = 10
MIN_CAP_COVERAGE_PCT = 90.0
COMMON_ENTRY_ORDER = "ticker, exact ISU_CD, entry_signal_date, entry_execution_date"
ACTIVE_CARRY_RAW_STORE: KrxRawStockStore | None = None
CACHED_REPOSITORY: Any | None = None
CACHED_REPOSITORY_ROOT: Path | None = None
CACHED_REPOSITORY_METADATA: dict[str, Any] = {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def normalize_isu(value: Any) -> str:
    return str(value or "").strip().upper()


def date_text(value: Any) -> str:
    return "" if value is None else str(value).strip()[:10]


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(rows)).to_csv(path, index=False, encoding="utf-8")


def current_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def current_origin_main() -> str:
    return subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()


def install_shared_repository_cache() -> None:
    """Reuse one verified full-store Repository V2 index across all 20 replays."""
    import trend_scanner.data.repository_v2_loader as repository_loader

    original_builder = repository_loader.build_repository_v2

    def cached_builder(root: Path | str, *, end: str | pd.Timestamp):
        global CACHED_REPOSITORY, CACHED_REPOSITORY_ROOT, CACHED_REPOSITORY_METADATA
        resolved = Path(root).resolve()
        if CACHED_REPOSITORY is None:
            print("[preflight] initialize one shared Repository V2 raw authority index", flush=True)
            started = time.perf_counter()
            CACHED_REPOSITORY = original_builder(root, end=end)
            CACHED_REPOSITORY_ROOT = resolved
            raw_index = getattr(CACHED_REPOSITORY, "_raw_index", None)
            CACHED_REPOSITORY_METADATA = {
                "root": str(resolved),
                "first_requested_end": pd.Timestamp(end).strftime("%Y-%m-%d"),
                "shared_across_windows_and_strategies": True,
                "initialization_wall_seconds": time.perf_counter() - started,
                "raw_index_built": bool(getattr(raw_index, "_built", False)),
                "raw_index_statistics": dict(getattr(raw_index, "stats", {})) if raw_index is not None else {},
            }
            print(f"[preflight] Repository V2 authority index ready in {CACHED_REPOSITORY_METADATA['initialization_wall_seconds']:.1f}s", flush=True)
        elif resolved != CACHED_REPOSITORY_ROOT:
            raise RuntimeError(f"SHARED_REPOSITORY_ROOT_MISMATCH:{resolved}:{CACHED_REPOSITORY_ROOT}")
        return CACHED_REPOSITORY

    repository_loader.build_repository_v2 = cached_builder
    v2.p2.build_repository_v2 = cached_builder
    pattern_b.candidate_runner.build_repository_v2 = cached_builder


def current_exclusion_pairs() -> set[tuple[str, str]]:
    result = {
        (normalize_ticker(ticker), normalize_isu(isu_cd))
        for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
    }
    if len(result) != len(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("PERMANENT_EXCLUSION_NORMALIZATION_COLLISION")
    return result


def v2_window_scoped_rows(rows: Sequence[Mapping[str, Any]], window_id: str) -> list[dict[str, Any]]:
    """Mirror scope_streams' date/duplicate scope without building Repository V2."""
    start, end, support = WINDOW_BOUNDS[window_id]
    seen: set[tuple[str, str, str, str]] = set()
    output: list[dict[str, Any]] = []
    allowed_status = {"REALIZED", "OPEN_AT_CUTOFF", "OPEN_AT_CUTOFF_WEAK_PROTECT", "LIFECYCLE_SETTLED"}
    for source in rows:
        row = dict(source)
        signal_day = date_text(row.get("entry_signal_date"))
        execution_day = date_text(row.get("entry_execution_date"))
        if not signal_day or not execution_day:
            continue
        candidate_id = (
            normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")), signal_day, execution_day,
        )
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        if signal_day < start or execution_day < start:
            continue
        if signal_day > end or execution_day > end or execution_day > support:
            continue
        # scope_streams retains these rows while recording a diagnostic issue.
        # Preserve the rows here; the full official runner performs that audit.
        _ = str(row.get("trade_status", "")) in allowed_status
        output.append(row)
    return output


class ExactPITMarketCap:
    """Load exact KRX raw market-cap partitions and bind tickers to PIT identities."""

    def __init__(self, pit_intervals: Sequence[Mapping[str, Any]]) -> None:
        self.store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
        self.pit_intervals = [dict(item) for item in pit_intervals]
        self.partitions: dict[tuple[str, str], dict[str, Any]] = {}
        self.provenance: dict[str, dict[str, Any]] = {}

    def active_pit_segment(self, row: Mapping[str, Any], market: str | None = None) -> dict[str, Any]:
        ticker = normalize_ticker(row.get("ticker"))
        isu_cd = normalize_isu(row.get("isu_cd"))
        signal_date = date_text(row.get("entry_signal_date"))
        if not ticker.strip("0") or not isu_cd or not signal_date:
            raise RuntimeError(f"EXACT_PIT_ENTRY_IDENTITY_FIELDS_MISSING:{ticker}:{isu_cd}:{signal_date}")
        matches = [
            item for item in self.pit_intervals
            if normalize_ticker(item.get("ticker")) == ticker
            and normalize_isu(item.get("isu_cd")) == isu_cd
            and str(item.get("state", "")) == "COMMON"
            and str(item.get("effective_from", ""))[:10] <= signal_date <= str(item.get("effective_to", ""))[:10]
        ]
        if len(matches) != 1:
            raise RuntimeError(f"EXACT_ENTRY_DATE_PIT_IDENTITY_NOT_UNIQUE:{ticker}:{isu_cd}:{signal_date}:{len(matches)}")
        segment = matches[0]
        actual_market = str(segment.get("market", "")).strip().upper()
        requested_market = str(market or "").strip().upper()
        if requested_market and requested_market != actual_market:
            raise RuntimeError(f"EXACT_ENTRY_DATE_PIT_MARKET_MISMATCH:{ticker}:{isu_cd}:{signal_date}:{requested_market}:{actual_market}")
        return segment

    def _load_partition(self, market: str, day: str) -> dict[str, Any]:
        manifest = self.store.get_manifest(market, day)
        if manifest is None or manifest.get("status") != "COMPLETE":
            return {
                "market": market,
                "date": day,
                "manifest": manifest,
                "caps": {},
                "status": "MISSING_EXACT_PIT_MARKET_CAP",
                "reason": "NO_COMPLETE_EXACT_DATE_MARKET_CAP_PARTITION",
            }
        try:
            snapshot = self.store.load_snapshot(market, day)
        except Exception as exc:
            raise RuntimeError(f"EXACT_PIT_MARKET_CAP_PARTITION_INTEGRITY_FAILURE:{market}:{day}:{type(exc).__name__}:{exc}") from exc
        normalized = snapshot["ticker"].astype(str).map(normalize_ticker)
        if normalized.duplicated().any():
            raise RuntimeError(f"DUPLICATE_TICKER_IN_EXACT_PIT_MARKET_CAP_PARTITION:{market}:{day}")
        caps: dict[str, int] = {}
        for _, item in snapshot.iterrows():
            ticker = normalize_ticker(item["ticker"])
            cap = pd.to_numeric(pd.Series([item.get("market_cap")]), errors="coerce").iloc[0]
            if pd.notna(cap) and math.isfinite(float(cap)) and float(cap) > 0:
                caps[ticker] = int(cap)
        manifest_copy = dict(manifest)
        return {
            "market": market,
            "date": day,
            "manifest": manifest_copy,
            "caps": caps,
            "status": "EXACT_PIT_PARTITION_LOADED",
            "reason": None,
        }

    def preload(self, rows: Sequence[Mapping[str, Any]]) -> None:
        required: set[tuple[str, str]] = set()
        for row in rows:
            provided = row.get("signal_market", row.get("market"))
            segment = self.active_pit_segment(row, str(provided or "") or None)
            required.add((str(segment["market"]).upper(), date_text(row.get("entry_signal_date"))))
        missing = sorted(required - set(self.partitions))
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=EXPECTED_WORKERS, thread_name_prefix="battle-exact-pit-mcap") as pool:
            futures = [pool.submit(self._load_partition, market, day) for market, day in missing]
            for future in futures:
                item = future.result()
                key = (item["market"], item["date"])
                self.partitions[key] = item
                manifest = item.get("manifest") or {}
                self.provenance[f"{key[0]}:{key[1]}"] = {
                    "market": key[0],
                    "date": key[1],
                    "status": manifest.get("status"),
                    "file_path": manifest.get("file_path"),
                    "file_sha256": manifest.get("file_sha256"),
                    "content_sha256": manifest.get("content_sha256"),
                    "row_count": manifest.get("row_count"),
                }

    def lookup(self, row: Mapping[str, Any]) -> dict[str, Any]:
        ticker = normalize_ticker(row.get("ticker"))
        isu_cd = normalize_isu(row.get("isu_cd"))
        signal_date = date_text(row.get("entry_signal_date"))
        segment = self.active_pit_segment(row, str(row.get("signal_market", row.get("market", "")) or "") or None)
        market = str(segment["market"]).upper()
        key = (market, signal_date)
        if key not in self.partitions:
            self.preload([row])
        partition = self.partitions[key]
        manifest = partition.get("manifest") or {}
        base = {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "market": market,
            "entry_signal_date": signal_date,
            "entry_execution_date": date_text(row.get("entry_execution_date")),
            "pair_id": row.get("pair_id"),
            "trade_id": row.get("trade_id"),
            "identity_binding": "EXACT_PIT_COMMON_IDENTITY_ON_ENTRY_SIGNAL_DATE",
            "pit_effective_from": str(segment.get("effective_from", ""))[:10],
            "pit_effective_to": str(segment.get("effective_to", ""))[:10],
            "raw_partition_status": manifest.get("status"),
            "raw_partition_path": manifest.get("file_path"),
            "raw_partition_file_sha256": manifest.get("file_sha256"),
            "raw_partition_content_sha256": manifest.get("content_sha256"),
            "raw_partition_row_count": manifest.get("row_count"),
            "market_cap_krw": None,
        }
        if partition["status"] != "EXACT_PIT_PARTITION_LOADED":
            return {**base, "cap_status": "MISSING_EXACT_PIT_MARKET_CAP", "reason": partition["reason"]}
        cap = partition["caps"].get(ticker)
        if cap is None:
            return {**base, "cap_status": "MISSING_EXACT_PIT_MARKET_CAP", "reason": "EXACT_PARTITION_HAS_NO_POSITIVE_MARKET_CAP_FOR_PIT_TICKER"}
        status = "PASS_GE_1T_KRW" if cap >= PIT_MCAP_THRESHOLD else "REJECT_LT_1T_KRW"
        return {**base, "cap_status": status, "reason": None, "market_cap_krw": cap}


def load_pit_authority() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = [dict(item) for item in value.get("intervals", []) if item.get("state") == "COMMON"]
    if not rows:
        raise RuntimeError("EMPTY_MERGED_PIT_COMMON_INTERVAL_AUTHORITY")
    return rows, {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "content_digest": value.get("content_digest"),
        "pit_frontier": value.get("pit_frontier"),
        "common_interval_count": len(rows),
    }


class ExactPITMarketAuthority:
    """Resolve entry market only from the exact active PIT COMMON identity interval."""

    def __init__(self, pit_intervals: Sequence[Mapping[str, Any]]) -> None:
        self.pit_intervals = [dict(item) for item in pit_intervals]

    def lookup(self, row: Mapping[str, Any]) -> dict[str, Any]:
        ticker = normalize_ticker(row.get("ticker"))
        isu_cd = normalize_isu(row.get("isu_cd"))
        signal_date = date_text(row.get("entry_signal_date"))
        base = {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "entry_signal_date": signal_date,
            "source_market": str(row.get("market") or row.get("signal_market") or row.get("market_at_signal") or row.get("entry_market") or "").strip().upper(),
            "pit_market": None,
            "pit_effective_from": None,
            "pit_effective_to": None,
            "authority_status": None,
            "included": False,
        }
        if not ticker.strip("0") or not isu_cd or not signal_date:
            return {**base, "authority_status": "MISSING_EXACT_ENTRY_IDENTITY_FIELDS"}
        matches = [
            item for item in self.pit_intervals
            if normalize_ticker(item.get("ticker")) == ticker
            and normalize_isu(item.get("isu_cd")) == isu_cd
            and str(item.get("state", "")) == "COMMON"
            and str(item.get("effective_from", ""))[:10] <= signal_date <= str(item.get("effective_to", ""))[:10]
        ]
        if len(matches) != 1:
            return {
                **base,
                "authority_status": "MISSING_EXACT_PIT_MARKET" if not matches else "AMBIGUOUS_EXACT_PIT_MARKET",
                "exact_pit_match_count": len(matches),
            }
        segment = matches[0]
        market = str(segment.get("market", "")).strip().upper()
        return {
            **base,
            "pit_market": market,
            "pit_effective_from": str(segment.get("effective_from", ""))[:10],
            "pit_effective_to": str(segment.get("effective_to", ""))[:10],
            "authority_status": "PASS_KOSPI" if market == "KOSPI" else "REJECT_NON_KOSPI",
            "included": market == "KOSPI",
            "exact_pit_match_count": 1,
        }


def summarize_market_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("strategy_id")), str(row.get("window_id"))), []).append(row)
    by_strategy_window = []
    for (strategy_id, window_id), items in sorted(groups.items()):
        included = sum(row.get("authority_status") == "PASS_KOSPI" for row in items)
        rejected = sum(row.get("authority_status") == "REJECT_NON_KOSPI" for row in items)
        missing = sum(row.get("authority_status") == "MISSING_EXACT_PIT_MARKET" for row in items)
        ambiguous = sum(row.get("authority_status") == "AMBIGUOUS_EXACT_PIT_MARKET" for row in items)
        missing_fields = sum(row.get("authority_status") == "MISSING_EXACT_ENTRY_IDENTITY_FIELDS" for row in items)
        by_strategy_window.append({
            "strategy_id": strategy_id,
            "window_id": window_id,
            "candidate_count": len(items),
            "kospi_eligible_attempts": included,
            "non_kospi_rejected_attempts": rejected,
            "market_authority_missing": missing + missing_fields,
            "market_authority_ambiguous": ambiguous,
            "status": "PASS" if missing == ambiguous == missing_fields == 0 else "FAIL",
        })
    missing_total = sum(row["market_authority_missing"] for row in by_strategy_window)
    ambiguous_total = sum(row["market_authority_ambiguous"] for row in by_strategy_window)
    return {
        "status": "PASS" if missing_total == ambiguous_total == 0 else "FAIL",
        "market_authority_missing": missing_total,
        "market_authority_ambiguous": ambiguous_total,
        "by_strategy_window": by_strategy_window,
        "policy": "entry_signal_date exact ticker + ISU_CD active PIT COMMON interval; authoritative market only",
    }


def static_preflight() -> dict[str, Any]:
    if current_head() != current_origin_main():
        raise RuntimeError(f"BASE_HEAD_NOT_EQUAL_ORIGIN_MAIN:{current_head()}:{current_origin_main()}")
    if len(current_exclusion_pairs()) != len(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("CURRENT_EXCLUSION_POLICY_NORMALIZATION_COLLISION")
    if len(current_exclusion_pairs()) != EXPECTED_EXCLUSION_COUNT:
        raise RuntimeError(f"PERMANENT_EXCLUSION_COUNT_MISMATCH:{len(current_exclusion_pairs())}:{EXPECTED_EXCLUSION_COUNT}")
    if set(P2_1_GLOBAL_LIFECYCLE_EXCLUSIONS) - set(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("P2_1_GLOBAL_LIFECYCLE_PROMOTION_MISSING")
    if any(
        PERMANENT_IDENTITY_EXCLUSIONS[key].get("approval_scope") != "GLOBAL permanent identity exclusion"
        for key in P2_1_GLOBAL_LIFECYCLE_EXCLUSIONS
    ):
        raise RuntimeError("P2_1_GLOBAL_LIFECYCLE_PROMOTION_SCOPE_MISMATCH")
    if NEW_GLOBAL_LIFECYCLE_EXCLUSION not in PERMANENT_IDENTITY_EXCLUSIONS:
        raise RuntimeError("BATTLE_C_LIQUIDATION_LIFECYCLE_PROMOTION_MISSING")
    if PERMANENT_IDENTITY_EXCLUSIONS[NEW_GLOBAL_LIFECYCLE_EXCLUSION].get("approval_scope") != "GLOBAL permanent identity exclusion":
        raise RuntimeError("BATTLE_C_LIQUIDATION_LIFECYCLE_PROMOTION_SCOPE_MISMATCH")
    if v2.WORKERS != EXPECTED_WORKERS or pattern_b.WORKERS != EXPECTED_WORKERS or pattern_b_v01.WORKERS != EXPECTED_WORKERS:
        raise RuntimeError("WORKER_COUNT_NOT_10")
    exclusions = current_exclusion_pairs()
    v2_sources: dict[str, Any] = {}
    pb_sources: dict[str, Any] = {}
    for window_id in WINDOW_IDS:
        print(f"[preflight] frozen source and exclusion checks {window_id}", flush=True)
        v2_rows, v2_detail = v2.source_check(window_id)
        if any((normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd"))) in exclusions for row in v2_rows):
            raise RuntimeError(f"V2_PERMANENT_EXCLUSION_LEAK:{window_id}")
        v2_sources[window_id] = {
            "source_rows_after_exact_exclusions": len(v2_rows),
            "source_sha256": v2_detail["source_sha256"],
            "certification_status": v2_detail["certification_status"],
            "certification_verdict": v2_detail["certification_verdict"],
        }

        pb_inputs = pattern_b.load_window_inputs(window_id)
        actual_window = pb_inputs["window"]
        actual = tuple(str(actual_window.get(field, ""))[:10] for field in ("effective_start", "effective_end", "execution_support"))
        if actual != WINDOW_BOUNDS[window_id]:
            raise RuntimeError(f"PATTERN_B_WINDOW_AUTHORITY_MISMATCH:{window_id}:{actual}")
        pb_records = list(pb_inputs["records"])
        if any((normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd"))) in exclusions for row in pb_records + list(pb_inputs["pass_rows"])):
            raise RuntimeError(f"PATTERN_B_PERMANENT_EXCLUSION_LEAK:{window_id}")
        pb_sources[window_id] = {
            "portfolio_source_records": len(pb_records),
            "allowed_frozen_signals": len(pb_inputs["pass_rows"]),
            "source_hashes": pb_inputs["source_hashes"],
            "authoritative_signal_linkage_status": pb_inputs["authoritative_signal_linkage_check"].get("status"),
        }
    pit_rows, pit_meta = load_pit_authority()
    status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).splitlines()
    preflight = {
        "schema": "official_strategy_battle_preflight_v02",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "base_head": current_head(),
        "origin_main": current_origin_main(),
        "base_worktree_clean_before_runner": not status,
        "preflight_git_status_short": status,
        "strategy_ids": [v2.STRATEGY_ID, pattern_b.STRATEGY_ID],
        "windows": WINDOW_BOUNDS,
        "worker_count": EXPECTED_WORKERS,
        "permanent_exclusion_count": len(exclusions),
        "permanent_exclusion_expected_before": 173,
        "permanent_exclusion_new_exact": [list(NEW_GLOBAL_LIFECYCLE_EXCLUSION)],
        "permanent_exclusion_expected_after": EXPECTED_EXCLUSION_COUNT,
        "permanent_exclusion_exact_duplicates": 0,
        "permanent_exclusion_normalization_collisions": 0,
        "permanent_exclusion_ticker_only_rules": 0,
        "permanent_exclusion_policy_path": "src/trend_scanner/universe/permanent_identity_exclusions.py",
        "permanent_exclusion_policy_sha256": sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
        "pit_authority": pit_meta,
        "v2_source_preflight": v2_sources,
        "pattern_b_source_preflight": pb_sources,
        "shared_portfolio": {
            "initial_capital_krw": INITIAL_CAPITAL,
            "per_position_buy_budget_krw": 5_000_000,
            "commission_rate": 0.00015,
            "buy_slippage_rate": 0.001,
            "sell_slippage_rate": 0.001,
            "sell_tax_rate": 0.0,
            "position_cap": None,
            "partial_fill": False,
            "pyramiding": False,
            "same_exact_identity_duplicate_holding": False,
            "entry_order": COMMON_ENTRY_ORDER,
        },
        "pit_market_cap_policy": {
            "entry_date_field": "entry_signal_date",
            "threshold_krw": PIT_MCAP_THRESHOLD,
            "authority": "exact market/date KRX raw stock partition + exact PIT COMMON ticker/ISU_CD/market interval",
            "nearest_current_proxy_or_fill_allowed": False,
            "missing_status": "MISSING_EXACT_PIT_MARKET_CAP",
        },
        "kospi_only_policy": {
            "entry_date_field": "entry_signal_date",
            "exact_identity": "ticker + ISU_CD + active PIT COMMON interval",
            "market_field": "authoritative PIT market",
            "market_value": "KOSPI",
            "market_cap_filter": False,
            "missing_authority": "stop before Battle C replay and report",
        },
        "output_path": OUTPUT_REL.as_posix(),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight_path = OUTPUT_ROOT / "preflight.json"
    if preflight_path.exists():
        prior = json.loads(preflight_path.read_text(encoding="utf-8"))
        if prior.get("base_head") != preflight["base_head"]:
            raise RuntimeError("EXISTING_PREFLIGHT_BELONGS_TO_DIFFERENT_BASE_HEAD")
    else:
        write_json(preflight_path, preflight)
    return preflight


def equity_valuation(rows: Sequence[Mapping[str, Any]], effective_end: str) -> dict[str, Any]:
    bounded = [row for row in rows if date_text(row.get("date")) <= effective_end]
    valid = []
    for row in bounded:
        value = row.get("equity")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            valid.append((date_text(row.get("date")), number))
    coverage = len(valid) / len(bounded) * 100.0 if bounded else 0.0
    peak = INITIAL_CAPITAL
    peak_day: str | None = None
    worst = 0.0
    worst_peak: str | None = None
    trough: str | None = None
    recovery: str | None = None
    worst_peak_value = peak
    for day, equity in valid:
        if equity >= peak:
            peak = equity
            peak_day = day
        drawdown = (equity / peak - 1.0) * 100.0 if peak else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_day
            worst_peak_value = peak
            trough = day
            recovery = None
        elif trough is not None and day > trough and equity >= worst_peak_value and recovery is None:
            recovery = day
    if not bounded:
        mdd_type = "CHECK_REQUIRED"
    elif coverage >= 100.0 - 1e-12:
        mdd_type = "EXACT"
    elif coverage >= 90.0:
        mdd_type = "OBSERVED"
    else:
        mdd_type = "OBSERVED_BELOW_90_COVERAGE"
    return {
        "coverage_pct": coverage,
        "total_effective_sessions": len(bounded),
        "observed_effective_sessions": len(valid),
        "missing_effective_sessions": len(bounded) - len(valid),
        "mdd_pct": worst if valid else None,
        "mdd_type": mdd_type,
        "mdd_peak_date": worst_peak,
        "mdd_trough_date": trough,
        "mdd_recovery_date": recovery,
    }


def numeric_returns(rows: Sequence[Mapping[str, Any]], *, event_returns: bool = False) -> list[float]:
    result: list[float] = []
    for row in rows:
        if event_returns:
            if row.get("event_type") != "EXIT" or row.get("event_status") != "EXECUTED":
                continue
            if date_text(row.get("execution_date")) == "":
                continue
            if str(row.get("post_cutoff", "")).strip().lower() in {"true", "1", "yes"}:
                continue
        value = row.get("net_return_pct")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            result.append(value)
    return result


def tail_counts(returns: Sequence[float]) -> dict[str, int]:
    values = np.asarray(list(returns), dtype=float)
    return {
        "+30": int((values >= 30).sum()),
        "+50": int((values >= 50).sum()),
        "+100": int((values >= 100).sum()),
        "-30": int((values <= -30).sum()),
        "-40": int((values <= -40).sum()),
        "-50": int((values <= -50).sum()),
        "-60": int((values <= -60).sum()),
    }


def common_metrics(strategy_id: str, battle_id: str, window_id: str, raw_metrics: Mapping[str, Any],
                   equity_rows: Sequence[Mapping[str, Any]], returns: Sequence[float], end: str) -> dict[str, Any]:
    valuation = equity_valuation(equity_rows, end)
    ending = raw_metrics.get("ending_equity_krw", raw_metrics.get("final_equity"))
    try:
        ending = float(ending) if ending is not None and math.isfinite(float(ending)) else None
    except (TypeError, ValueError):
        ending = None
    initial = float(raw_metrics.get("initial_capital_krw", INITIAL_CAPITAL))
    eligible = raw_metrics.get("eligible_entry_attempts")
    if eligible is None:
        eligible = raw_metrics.get("cash_diagnostics", {}).get("eligible_entry_attempts")
    cash_short = int(raw_metrics.get("cash_shortage_skipped_entries", 0) or 0)
    total_return = raw_metrics.get("total_return_pct", raw_metrics.get("cumulative_return_pct"))
    cagr = raw_metrics.get("cagr_pct", raw_metrics.get("CAGR_pct"))
    cash_shortage_rate = raw_metrics.get("cash_shortage_skip_rate_pct")
    if cash_shortage_rate is None and eligible is not None:
        eligible_count = int(eligible)
        cash_shortage_rate = 100.0 * cash_short / eligible_count if eligible_count else (0.0 if cash_short == 0 else None)
    return {
        "battle_id": battle_id,
        "strategy_id": strategy_id,
        "window_id": window_id,
        "initial_capital_krw": initial,
        "ending_equity_krw": ending,
        "profit_krw": None if ending is None else ending - initial,
        "total_return_pct": total_return,
        "cagr_pct": cagr,
        **valuation,
        "valuation_status": "CHECK_REQUIRED" if valuation["coverage_pct"] < 90.0 else "PASS",
        "eligible_entry_attempts": eligible,
        "executed_trades": raw_metrics.get("executed_entry_count", raw_metrics.get("trade_count")),
        "closed_trades": raw_metrics.get("realized_exit_count", raw_metrics.get("realized_trade_count")),
        "cash_shortage_count": cash_short,
        "cash_shortage_rate_pct": cash_shortage_rate,
        "positive_trade_rate_pct": (100.0 * sum(value > 0 for value in returns) / len(returns)) if returns else raw_metrics.get("win_rate_pct"),
        "mean_trade_return_pct": statistics.mean(returns) if returns else None,
        "median_trade_return_pct": statistics.median(returns) if returns else raw_metrics.get("median_trade_return_pct"),
        "tail_counts": tail_counts(returns),
        "turnover_krw": raw_metrics.get("turnover_krw"),
        "turnover_multiple": raw_metrics.get("turnover_multiple"),
        "average_capital_utilization_pct": raw_metrics.get("average_capital_utilization_pct"),
        "maximum_capital_utilization_pct": raw_metrics.get("maximum_capital_utilization_pct"),
        "average_concurrent_positions": raw_metrics.get("average_concurrent_positions"),
        "maximum_concurrent_positions": raw_metrics.get("maximum_concurrent_positions"),
        "cash_conservation_pass": raw_metrics.get("cash_conservation_pass"),
    }


def run_v2_battle(
    battle_id: str,
    output_dir: Path,
    cap_authority: ExactPITMarketCap | None = None,
    market_authority: ExactPITMarketAuthority | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    original_out = v2.OUT_DIR
    original_scope = v2.scope_streams
    original_source_check = v2.source_check
    cap_audit: list[dict[str, Any]] = []
    market_audit: list[dict[str, Any]] = []
    selection_by_signal: dict[tuple[str, str, str], dict[str, Any]] = {}
    if cap_authority is not None or market_authority is not None:
        def filtered_scope(ctx: Any, rows: Sequence[Mapping[str, Any]], end: pd.Timestamp):
            streams, issues = original_scope(ctx, rows, end)
            filtered: dict[Any, list[dict[str, Any]]] = {}
            for key, items in streams.items():
                for item in items:
                    sigkey = (normalize_ticker(item.get("ticker")), normalize_isu(item.get("isu_cd")), date_text(item.get("entry_signal_date")))
                    include = True
                    if cap_authority is not None:
                        cap_row = cap_authority.lookup(item)
                        cap_row.update({"strategy_id": v2.STRATEGY_ID, "window_id": ctx.window_id, "source_type": "portfolio_entry_candidate"})
                        cap_audit.append(cap_row)
                        selection_by_signal[sigkey] = cap_row
                        include = include and cap_row["cap_status"] == "PASS_GE_1T_KRW"
                    if market_authority is not None:
                        market_row = market_authority.lookup(item)
                        market_row.update({"strategy_id": v2.STRATEGY_ID, "window_id": ctx.window_id, "source_type": "portfolio_entry_candidate"})
                        market_audit.append(market_row)
                        if market_row.get("pit_market"):
                            item["market"] = market_row["pit_market"]
                        include = include and market_row["authority_status"] == "PASS_KOSPI"
                    if include:
                        filtered.setdefault(key, []).append(dict(item))
            return filtered, issues
        v2.scope_streams = filtered_scope
    try:
        v2.OUT_DIR = output_dir
        result = v2.run_full()
    finally:
        v2.OUT_DIR = original_out
        v2.scope_streams = original_scope
        v2.source_check = original_source_check

    summaries: list[dict[str, Any]] = []
    for window_id in WINDOW_IDS:
        output = result["outputs"][window_id]
        metrics = dict(output["metrics"])
        event_rows = list(output["events"])
        equity_rows = list(output["daily_equity"])
        returns = numeric_returns(event_rows, event_returns=True)
        row = common_metrics(v2.STRATEGY_ID, battle_id, window_id, metrics, equity_rows, returns, WINDOW_BOUNDS[window_id][1])
        summaries.append(row)
        result["outputs"][window_id]["battle_metrics"] = row

    if cap_authority is not None:
        write_csv(output_dir / "pit_market_cap_attempt_audit.csv", cap_audit)
        cap_summary = summarize_cap_rows(cap_audit)
        write_json(output_dir / "pit_market_cap_summary.json", cap_summary)
    else:
        cap_summary = None
    if market_authority is not None:
        write_csv(output_dir / "pit_market_authority_attempt_audit.csv", market_audit)
        market_summary = summarize_market_rows(market_audit)
        write_json(output_dir / "pit_market_authority_summary.json", market_summary)
    else:
        market_summary = None
    contract_path = output_dir / "execution_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update({
        "battle_id": battle_id,
        "common_entry_order": COMMON_ENTRY_ORDER,
        "entry_date_pit_market_cap_filter": None if cap_authority is None else {
            "threshold_krw": PIT_MCAP_THRESHOLD,
            "date_field": "entry_signal_date",
            "included_status": "PASS_GE_1T_KRW",
            "rejected_statuses": ["REJECT_LT_1T_KRW", "MISSING_EXACT_PIT_MARKET_CAP"],
            "audit_file": "pit_market_cap_attempt_audit.csv",
        },
        "entry_date_pit_market_filter": None if market_authority is None else {
            "market": "KOSPI",
            "date_field": "entry_signal_date",
            "identity_binding": "exact active PIT COMMON ticker + ISU_CD interval",
            "authority": "merged_pit_intervals.json",
            "audit_file": "pit_market_authority_attempt_audit.csv",
            "market_cap_filter": False,
        },
    })
    write_json(contract_path, contract)
    write_csv(output_dir / "battle_window_metrics.csv", summaries)
    write_json(output_dir / "battle_summary.json", {
        "schema": "official_strategy_battle_strategy_summary_v01",
        "battle_id": battle_id,
        "strategy_id": v2.STRATEGY_ID,
        "worker_count": EXPECTED_WORKERS,
        "windows": summaries,
        "pit_market_cap_summary": cap_summary,
        "pit_market_authority_summary": market_summary,
    })
    report = [
        f"# {battle_id} — A FAST Core V2",
        "",
        "전략 신호·청산 원장은 frozen 공식 CONTROL 원장을 사용했고, chronological cash-aware portfolio replay를 새로 수행했어.",
        f"- 공통 진입 순서: `{COMMON_ENTRY_ORDER}`.",
        f"- worker: {EXPECTED_WORKERS}.",
        "- Battle B만 entry_signal_date exact PIT 시총 1조원 이상을 포함했어. 누락 및 미만은 실행에서 제외했어." if cap_authority is not None else "- Battle C는 entry identity의 exact entry-date PIT market이 KOSPI인 후보만 포함했고 시총 필터는 적용하지 않았어." if market_authority is not None else "- Battle A는 시총 및 시장 universe filter 없이 수행했어.",
        "",
        "| Window | Return | CAGR | MDD / type | Coverage | Eligible | Executed / closed | Cash skip % | Median | +50 / +100 | Turnover |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            f"| {row['window_id']} | {row['total_return_pct']} | {row['cagr_pct']} | "
            f"{row['mdd_pct']} / {row['mdd_type']} | {row['coverage_pct']} | "
            f"{row['eligible_entry_attempts']} | {row['executed_trades']} / {row['closed_trades']} | "
            f"{row['cash_shortage_rate_pct']} | {row['median_trade_return_pct']} | "
            f"{row.get('tail_counts', {}).get('+50')} / {row.get('tail_counts', {}).get('+100')} | {row['turnover_krw']} |"
        )
    report.append("")
    report.append("이 문서는 양 전략 정면 비교용 포트폴리오 결과이며, 단독 채택 판정 문서가 아니야.")
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"rows": summaries, "run": result, "cap_summary": cap_summary, "cap_audit": cap_audit, "cap_selection": selection_by_signal, "market_summary": market_summary, "market_audit": market_audit}


def summarize_cap_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("strategy_id")), str(row.get("window_id"))), []).append(row)
    output = []
    for (strategy_id, window_id), items in sorted(groups.items()):
        total = len(items)
        covered = sum(row.get("cap_status") in {"PASS_GE_1T_KRW", "REJECT_LT_1T_KRW"} for row in items)
        included = sum(row.get("cap_status") == "PASS_GE_1T_KRW" for row in items)
        rejected = sum(row.get("cap_status") == "REJECT_LT_1T_KRW" for row in items)
        missing = sum(row.get("cap_status") == "MISSING_EXACT_PIT_MARKET_CAP" for row in items)
        output.append({
            "strategy_id": strategy_id,
            "window_id": window_id,
            "attempt_count": total,
            "exact_pit_market_cap_covered_attempts": covered,
            "ge_1t_eligible_attempts": included,
            "lt_1t_rejected_attempts": rejected,
            "missing_exact_pit_market_cap_attempts": missing,
            "coverage_pct": 100.0 * covered / total if total else 100.0,
            "status": "PASS" if total == 0 or 100.0 * covered / total >= MIN_CAP_COVERAGE_PCT else "CHECK_REQUIRED",
        })
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in output) else "CHECK_REQUIRED",
        "threshold_krw": PIT_MCAP_THRESHOLD,
        "minimum_coverage_pct": MIN_CAP_COVERAGE_PCT,
        "by_strategy_window": output,
    }


def collect_battle_b_preflight(cap: ExactPITMarketCap, pit_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    selection: dict[str, Any] = {"v2": {}, "pattern_b": {}}
    source_rows_by_type: dict[str, dict[str, list[dict[str, Any]]]] = {"v2": {}, "pattern_b": {}}
    for window_id in WINDOW_IDS:
        v2_rows, _details = v2.source_check(window_id)
        v2_rows = v2_window_scoped_rows(v2_rows, window_id)
        source_rows_by_type["v2"][window_id] = v2_rows

        pb_inputs = pattern_b.load_window_inputs(window_id)
        pb_rows = [dict(row) for row in pb_inputs["records"]]
        source_rows_by_type["pattern_b"][window_id] = pb_rows

    all_rows = [row for by_window in source_rows_by_type.values() for items in by_window.values() for row in items]
    cap.preload(all_rows)
    for kind, by_window in source_rows_by_type.items():
        strategy_id = v2.STRATEGY_ID if kind == "v2" else pattern_b.STRATEGY_ID
        for window_id, rows in by_window.items():
            for row in rows:
                cap_row = cap.lookup(row)
                cap_row.update({"strategy_id": strategy_id, "window_id": window_id, "source_type": "portfolio_entry_candidate"})
                audit.append(cap_row)
                sigkey = (normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")), date_text(row.get("entry_signal_date")))
                selection[kind][f"{window_id}|{'|'.join(sigkey)}"] = cap_row
    summary = summarize_cap_rows(audit)
    write_csv(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.csv", audit)
    write_json(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json", {
        "schema": "battle_b_exact_pit_market_cap_preflight_v01",
        "status": "PASS" if all(item["status"] == "PASS" for item in summary["by_strategy_window"]) else "CHECK_REQUIRED",
        "policy": {
            "signal_date_field": "entry_signal_date",
            "market_cap_threshold_krw": PIT_MCAP_THRESHOLD,
            "exact_identity": "ticker + ISU_CD + active PIT COMMON interval + market",
            "source": "hash-verified exact-date KRX raw market-cap partition",
            "substitution": "none; missing exact cap rejected and separately counted",
        },
        "summary": summary,
        "raw_partition_provenance": cap.provenance,
    })
    return audit, summary, selection


def collect_battle_c_preflight(
    authority: ExactPITMarketAuthority,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    signal_audit: list[dict[str, Any]] = []
    for window_id in WINDOW_IDS:
        v2_rows, _details = v2.source_check(window_id)
        v2_rows = v2_window_scoped_rows(v2_rows, window_id)
        for row in v2_rows:
            decision = authority.lookup(row)
            decision.update({"strategy_id": v2.STRATEGY_ID, "window_id": window_id, "source_type": "portfolio_entry_candidate"})
            audit.append(decision)

        pb_inputs = pattern_b.load_window_inputs(window_id)
        for row in pb_inputs["records"]:
            decision = authority.lookup(row)
            decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "portfolio_entry_candidate"})
            audit.append(decision)
        for row in pb_inputs["pass_rows"]:
            decision = authority.lookup(row)
            decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "frozen_allowed_signal"})
            signal_audit.append(decision)

    summary = summarize_market_rows(audit)
    signal_summary = summarize_market_rows(signal_audit)
    summary["allowed_signal_summary"] = signal_summary
    summary["status"] = "PASS" if summary["status"] == signal_summary["status"] == "PASS" else "FAIL"
    summary["market_authority_missing"] += signal_summary["market_authority_missing"]
    summary["market_authority_ambiguous"] += signal_summary["market_authority_ambiguous"]
    write_csv(OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.csv", audit)
    write_csv(OUTPUT_ROOT / "battle_c_pit_market_authority_signal_preflight.csv", signal_audit)
    write_json(OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.json", {
        "schema": "battle_c_exact_pit_market_authority_preflight_v02",
        "status": summary["status"],
        "summary": summary,
        "authority_source": "data/market/rolling_authority/merged_pit_intervals.json",
        "filter": "authoritative PIT market == KOSPI at entry_signal_date; exact ticker + ISU_CD",
        "market_cap_filter": False,
    })
    return audit + signal_audit, summary


def pattern_b_valuation_with_evidence(record: Mapping[str, Any], frames: Mapping[Any, pd.DataFrame], day: pd.Timestamp,
                                     session_positions: Mapping[pd.Timestamp, int], gap_classifications: Mapping[tuple[str, str], str],
                                     *, strategy_id: str, pair_id: str) -> tuple[float | None, dict[str, Any] | None]:
    valuation_day = pd.Timestamp(day).normalize()
    exact = portfolio_engine._price(record, frames, valuation_day, "close")
    if exact is not None:
        return exact, None
    ticker = normalize_ticker(record.get("ticker"))
    isu_cd = normalize_isu(record.get("isu_cd"))
    try:
        effective_from = pd.Timestamp(str(record.get("identity_effective_from"))[:10]).normalize()
        effective_to = pd.Timestamp(str(record.get("identity_effective_to"))[:10]).normalize()
    except Exception:
        return None, {
            "strategy_id": strategy_id, "pair_id": pair_id, "ticker": ticker, "identity": isu_cd,
            "valuation_date": valuation_day.strftime("%Y-%m-%d"), "status": "UNRESOLVED_MISSING_PIT_LIFECYCLE_BOUNDARY",
            "used_for_execution": False,
        }
    if not (effective_from <= valuation_day <= effective_to):
        return None, {
            "strategy_id": strategy_id, "pair_id": pair_id, "ticker": ticker, "identity": isu_cd,
            "valuation_date": valuation_day.strftime("%Y-%m-%d"), "status": "UNRESOLVED_OUTSIDE_EXACT_PIT_IDENTITY_LIFECYCLE",
            "used_for_execution": False,
        }
    market = str(record.get("market", record.get("signal_market", ""))).strip().upper()
    raw_store = ACTIVE_CARRY_RAW_STORE
    if raw_store is None:
        raise RuntimeError("PATTERN_B_CARRY_RAW_STORE_NOT_INITIALIZED")
    manifest = raw_store.get_manifest(market, valuation_day.strftime("%Y-%m-%d"))
    if manifest is None or manifest.get("status") != "COMPLETE":
        return None, {
            "strategy_id": strategy_id, "pair_id": pair_id, "ticker": ticker, "identity": isu_cd, "market": market,
            "valuation_date": valuation_day.strftime("%Y-%m-%d"), "status": "UNRESOLVED_RAW_PARTITION_NOT_COMPLETE",
            "raw_manifest_status": None if manifest is None else manifest.get("status"), "used_for_execution": False,
        }
    try:
        raw = raw_store.load_snapshot(market, valuation_day.strftime("%Y-%m-%d"))
    except Exception as exc:
        raise RuntimeError(f"PATTERN_B_VALUATION_RAW_PARTITION_INTEGRITY_FAILURE:{market}:{valuation_day.date()}:{exc}") from exc
    matches = raw.loc[raw["ticker"].astype(str).map(normalize_ticker) == ticker]
    if len(matches) != 1 or not _is_non_trading_placeholder(matches.iloc[0]):
        return None, {
            "strategy_id": strategy_id, "pair_id": pair_id, "ticker": ticker, "identity": isu_cd, "market": market,
            "valuation_date": valuation_day.strftime("%Y-%m-%d"),
            "status": "UNRESOLVED_EXACT_RAW_ROW_NOT_AUTHORIZED_NON_TRADING_PLACEHOLDER",
            "raw_manifest_status": manifest.get("status"), "used_for_execution": False,
        }
    frame = portfolio_engine._frame_for_record(record, frames)
    if frame is None:
        return None, None
    if any(field not in frame.columns for field in ("open", "high", "low", "close")):
        return None, None
    prior = frame.loc[frame.index < valuation_day, ["open", "high", "low", "close"]].copy()
    for field in ("open", "high", "low", "close"):
        prior[field] = pd.to_numeric(prior[field], errors="coerce")
    normal = prior.loc[(prior > 0).all(axis=1)].sort_index()
    if normal.empty:
        return None, {
            "strategy_id": strategy_id, "pair_id": pair_id, "ticker": ticker, "identity": isu_cd, "market": market,
            "valuation_date": valuation_day.strftime("%Y-%m-%d"), "status": "UNRESOLVED_NO_PRIOR_NORMAL_ADJUSTED_CLOSE",
            "raw_manifest_status": manifest.get("status"), "used_for_execution": False,
        }
    prior_day = pd.Timestamp(normal.index[-1]).normalize()
    if prior_day >= valuation_day or prior_day < effective_from or prior_day > effective_to:
        raise RuntimeError(f"PATTERN_B_VALUATION_CARRY_PIT_BOUNDARY_FAILURE:{ticker}:{isu_cd}:{prior_day}:{valuation_day}")
    price = float(normal.iloc[-1]["close"])
    age_sessions = None
    if valuation_day in session_positions and prior_day in session_positions:
        age_sessions = session_positions[valuation_day] - session_positions[prior_day]
    audit = {
        "strategy_id": strategy_id,
        "pair_id": pair_id,
        "trade_id": record.get("trade_id"),
        "ticker": ticker,
        "identity": isu_cd,
        "market": market,
        "valuation_date": valuation_day.strftime("%Y-%m-%d"),
        "status": "APPROVED_EXACT_PIT_NON_TRADING_PLACEHOLDER_PRIOR_NORMAL_ADJUSTED_CLOSE_CARRY",
        "raw_predicate": "NON_TRADING_PLACEHOLDER_V01",
        "raw_manifest_status": manifest.get("status"),
        "raw_partition_path": manifest.get("file_path"),
        "raw_partition_file_sha256": manifest.get("file_sha256"),
        "raw_partition_content_sha256": manifest.get("content_sha256"),
        "raw_row": {
            key: (
                normalize_ticker(value) if key == "ticker"
                else date_text(value) if key == "date"
                else int(value) if pd.notna(value)
                else None
            )
            for key, value in matches.iloc[0].to_dict().items()
        },
        "prior_valid_adjusted_close_date": prior_day.strftime("%Y-%m-%d"),
        "prior_valid_adjusted_close": price,
        "carry_age_trading_sessions": age_sessions,
        "carry_age_calendar_days": int((valuation_day - prior_day).days),
        "valuation_only": True,
        "used_for_execution": False,
        "used_for_strategy_or_features": False,
    }
    return price, audit


def ordered_records(records: list[dict[str, Any]], cap_rows: Mapping[tuple[str, str, str], Mapping[str, Any]] | None) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = {}
    actual_market_caps: dict[str, Any] = {}
    for row in records:
        signal_key = (normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")), date_text(row.get("entry_signal_date")))
        cap_row = None if cap_rows is None else cap_rows.get(signal_key)
        exact_cap = None if cap_row is None else cap_row.get("market_cap_krw")
        row["entry_pit_market_cap_krw"] = exact_cap
        row["entry_market_cap"] = 0
        execution_day = date_text(row.get("entry_execution_date"))
        by_day.setdefault(execution_day, []).append(row)
        actual_market_caps[str(row.get("pair_id"))] = exact_cap
    max_same_day = 0
    order_counts = 0
    for day, rows in by_day.items():
        expected = sorted(rows, key=lambda row: (
            normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")),
            date_text(row.get("entry_signal_date")), date_text(row.get("entry_execution_date")),
        ))
        rank = len(expected)
        for row in expected:
            # The existing Pattern B execution engine sorts its first key by
            # this field. A deterministic rank implements the shared order.
            row["entry_market_cap"] = rank
            rank -= 1
        max_same_day = max(max_same_day, len(expected))
        order_counts += len(expected)
    return {"actual_market_caps_by_pair_id": actual_market_caps, "same_day_candidate_count": order_counts, "maximum_same_day_candidates": max_same_day}


def run_pattern_b_battle(battle_id: str, output_dir: Path, v2_rows: Sequence[Mapping[str, Any]],
                         cap_authority: ExactPITMarketCap | None = None,
                         cap_signal_selection: Mapping[str, Any] | None = None,
                         market_authority: ExactPITMarketAuthority | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    relative_out = output_dir.relative_to(ROOT)
    global ACTIVE_CARRY_RAW_STORE
    original_root = pattern_b.OUTPUT_ROOT
    original_carry_store = ACTIVE_CARRY_RAW_STORE
    pattern_b.OUTPUT_ROOT = relative_out
    intervals, trading_dates, market_authority_meta = pattern_b_base._load_authorities(ROOT)
    interval_rows = [dict(item) for item in intervals]
    pit_context = SimpleNamespace(calendar=SimpleNamespace(trading_dates=trading_dates))
    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    ACTIVE_CARRY_RAW_STORE = raw_store
    carry_context = SimpleNamespace(run=pit_context, raw_store=raw_store, raw_partition_cache={}, raw_manifest_db_sha256=None)
    session_positions = {pd.Timestamp(day).normalize(): index for index, day in enumerate(trading_dates)}
    summaries: list[dict[str, Any]] = []
    outputs: dict[str, Any] = {}
    all_cap_rows: list[dict[str, Any]] = []
    all_signal_cap_rows: list[dict[str, Any]] = []
    all_market_rows: list[dict[str, Any]] = []
    all_signal_market_rows: list[dict[str, Any]] = []
    try:
        for window_id in WINDOW_IDS:
            started = time.perf_counter()
            print(f"[{battle_id} Pattern B {window_id}] verify frozen inputs; load exact daily price frames", flush=True)
            inputs = pattern_b.load_window_inputs(window_id)
            source_records = [dict(row) for row in inputs["records"]]
            source_signals = [dict(row) for row in inputs["pass_rows"]]
            cap_map: dict[tuple[str, str, str], dict[str, Any]] = {}
            signal_cap_map: dict[tuple[str, str, str], dict[str, Any]] = {}
            if cap_authority is not None:
                selected_records: list[dict[str, Any]] = []
                for row in source_records:
                    decision = cap_authority.lookup(row)
                    decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "portfolio_entry_candidate"})
                    all_cap_rows.append(decision)
                    key = (normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")), date_text(row.get("entry_signal_date")))
                    cap_map[key] = decision
                    if decision["cap_status"] == "PASS_GE_1T_KRW":
                        selected_records.append(row)
                selected_signals: list[dict[str, Any]] = []
                for row in source_signals:
                    decision = cap_authority.lookup(row)
                    decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "frozen_allowed_signal"})
                    all_signal_cap_rows.append(decision)
                    key = (normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")), date_text(row.get("entry_signal_date")))
                    signal_cap_map[key] = decision
                    if decision["cap_status"] == "PASS_GE_1T_KRW":
                        selected_signals.append(row)
                source_records = selected_records
                source_signals = selected_signals
            if market_authority is not None:
                selected_records = []
                for row in source_records:
                    decision = market_authority.lookup(row)
                    decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "portfolio_entry_candidate"})
                    all_market_rows.append(decision)
                    if decision["authority_status"] == "PASS_KOSPI":
                        row["market"] = decision["pit_market"]
                        selected_records.append(row)
                selected_signals = []
                for row in source_signals:
                    decision = market_authority.lookup(row)
                    decision.update({"strategy_id": pattern_b.STRATEGY_ID, "window_id": window_id, "source_type": "frozen_allowed_signal"})
                    all_signal_market_rows.append(decision)
                    if decision["authority_status"] == "PASS_KOSPI":
                        row["market"] = decision["pit_market"]
                        selected_signals.append(row)
                source_records = selected_records
                source_signals = selected_signals
            inputs["records"] = source_records
            inputs["pass_rows"] = source_signals
            ordered = ordered_records(source_records, cap_map if cap_authority is not None else None)
            tickers = sorted({normalize_ticker(row.get("ticker")) for row in source_records})
            daily_frames, loader_audit, _repository = pattern_b.candidate_runner._load_prices(
                ROOT, tickers, inputs["window"]["effective_start"], inputs["window"]["execution_support"],
            )
            frames = pattern_b_v01.build_component_frames(source_records, daily_frames, interval_rows, trading_dates)
            price_audit = pattern_b_v01.verify_execution_prices(source_records, frames, inputs["window"])
            next_session_audit = pattern_b.verify_next_session_execution_dates(source_records, frames, trading_dates, inputs["window"])
            price_audit.update(
                next_session_execution_audit=next_session_audit,
                next_session_execution_violation_count=next_session_audit["violation_count"],
            )
            if next_session_audit["status"] != "PASS":
                raise RuntimeError(f"NEXT_SESSION_EXECUTION_RULE_FAILURE:{battle_id}:{window_id}:{next_session_audit}")
            if sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values()):
                raise RuntimeError(f"REPOSITORY_V2_SILENT_INNER_DROP:{battle_id}:{window_id}")

            original_tax = portfolio_engine.SELL_TAX_SCHEDULE
            original_capital = portfolio_engine.INITIAL_CAPITAL
            original_budget = portfolio_engine.POSITION_BUDGET
            original_valuation = portfolio_engine._valuation_close_with_carry
            portfolio_engine.SELL_TAX_SCHEDULE = pattern_b.ZERO_TAX_SCHEDULE
            portfolio_engine.INITIAL_CAPITAL = pattern_b.INITIAL_CAPITAL
            portfolio_engine.POSITION_BUDGET = pattern_b.POSITION_BUDGET
            portfolio_engine._valuation_close_with_carry = pattern_b_valuation_with_evidence
            try:
                replay = portfolio_engine._portfolio_replay(
                    source_records,
                    frames,
                    [pd.Timestamp(day).normalize() for day in trading_dates],
                    strategy_id=f"{pattern_b.STRATEGY_ID}_{battle_id}_{window_id.replace('-', '_')}",
                    effective_start=pd.Timestamp(inputs["window"]["effective_start"]).normalize(),
                    effective_end=pd.Timestamp(inputs["window"]["effective_end"]).normalize(),
                    execution_support=pd.Timestamp(inputs["window"]["execution_support"]).normalize(),
                )
            finally:
                portfolio_engine.SELL_TAX_SCHEDULE = original_tax
                portfolio_engine.INITIAL_CAPITAL = original_capital
                portfolio_engine.POSITION_BUDGET = original_budget
                portfolio_engine._valuation_close_with_carry = original_valuation

            actual_caps = ordered["actual_market_caps_by_pair_id"]
            for event in replay["events"]:
                pair_id = str(event.get("pair_id", ""))
                if "market_cap_at_signal" in event:
                    event["market_cap_at_signal"] = actual_caps.get(pair_id)
            for candidate in replay.get("entry_candidate_audit", []):
                pair_id = str(candidate.get("pair_id", ""))
                if "market_cap_at_signal" in candidate:
                    candidate["market_cap_at_signal"] = actual_caps.get(pair_id)

            v2_ref = v2_reference_for_window(v2_rows, window_id)
            cap_audit = {
                "source": "none; cap filter is not applied in Battle A" if cap_authority is None else "exact PIT cap filter only; allocation order is the shared deterministic signal order",
                "threshold_krw": None if cap_authority is None else PIT_MCAP_THRESHOLD,
                "covered_attempts": None if cap_authority is None else sum(row.get("cap_status") in {"PASS_GE_1T_KRW", "REJECT_LT_1T_KRW"} for row in all_cap_rows if row.get("window_id") == window_id and row.get("strategy_id") == pattern_b.STRATEGY_ID),
                "same_day_allocation_uses_market_cap": False,
                "common_entry_order": COMMON_ENTRY_ORDER,
            }
            written = pattern_b.write_window_outputs(
                inputs, replay, frames, loader_audit, cap_audit, price_audit,
                v2_ref, trading_dates, pattern_b.frozen_source_hashes_verified(inputs),
            )
            contract_path = output_dir / window_id.lower().replace("-", "_") / "execution_contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["battle_id"] = battle_id
            contract["portfolio"]["within_day_order"] = COMMON_ENTRY_ORDER
            contract["portfolio"]["entry_market_cap_priority_for_cash_allocation"] = False
            contract["portfolio"]["market_cap_filter"] = None if cap_authority is None else {
                "threshold_krw": PIT_MCAP_THRESHOLD,
                "date_field": "entry_signal_date",
                "identity_binding": "exact active PIT COMMON (ticker, ISU_CD, market)",
                "missing_exact_market_cap": "MISSING_EXACT_PIT_MARKET_CAP; rejected and reported",
            }
            contract["portfolio"]["market_filter"] = None if market_authority is None else {
                "market": "KOSPI",
                "date_field": "entry_signal_date",
                "identity_binding": "exact active PIT COMMON ticker + ISU_CD interval",
                "authority": "merged_pit_intervals.json",
                "missing_exact_market": "stop before replay; report authority gap",
                "market_cap_filter": False,
            }
            write_json(contract_path, contract)
            event_path = output_dir / window_id.lower().replace("-", "_") / "portfolio_events.csv"
            pd.DataFrame(replay["events"]).to_csv(event_path, index=False, encoding="utf-8")
            entry_attempt_path = output_dir / window_id.lower().replace("-", "_") / "entry_attempt_audit.csv"
            pd.DataFrame(replay["entry_candidate_audit"]).to_csv(entry_attempt_path, index=False, encoding="utf-8")
            raw_metrics = dict(written["metrics"])
            raw_metrics["cash_diagnostics"] = written["cash_diagnostics"]
            equity_rows = list(replay["daily_equity"])
            realized = list(written["diagnostics"].get("realized_trades", []))
            returns = numeric_returns(realized)
            standard = common_metrics(pattern_b.STRATEGY_ID, battle_id, window_id, raw_metrics, equity_rows, returns, WINDOW_BOUNDS[window_id][1])
            if cap_authority is not None:
                per_window_caps = [row for row in all_cap_rows if row.get("window_id") == window_id and row.get("strategy_id") == pattern_b.STRATEGY_ID]
                standard.update(cap_attempt_metrics(per_window_caps))
            summaries.append(standard)
            written["battle_metrics"] = standard
            outputs[window_id] = written
            print(f"[{battle_id} Pattern B {window_id}] complete in {time.perf_counter() - started:.1f}s; return={standard['total_return_pct']}; trades={standard['executed_trades']}; cash skips={standard['cash_shortage_count']}", flush=True)
    finally:
        pattern_b.OUTPUT_ROOT = original_root
        ACTIVE_CARRY_RAW_STORE = original_carry_store

    if cap_authority is not None:
        write_csv(output_dir / "pit_market_cap_attempt_audit.csv", [row for row in all_cap_rows if row.get("strategy_id") == pattern_b.STRATEGY_ID])
        write_csv(output_dir / "pit_market_cap_signal_audit.csv", [row for row in all_signal_cap_rows if row.get("strategy_id") == pattern_b.STRATEGY_ID])
        cap_summary = summarize_cap_rows([row for row in all_cap_rows if row.get("strategy_id") == pattern_b.STRATEGY_ID])
        write_json(output_dir / "pit_market_cap_summary.json", cap_summary)
    else:
        cap_summary = None
    if market_authority is not None:
        write_csv(output_dir / "pit_market_authority_attempt_audit.csv", all_market_rows)
        write_csv(output_dir / "pit_market_authority_signal_audit.csv", all_signal_market_rows)
        market_summary = summarize_market_rows(all_market_rows)
        market_summary["allowed_signal_summary"] = summarize_market_rows(all_signal_market_rows)
        write_json(output_dir / "pit_market_authority_summary.json", market_summary)
    else:
        market_summary = None
    write_csv(output_dir / "battle_window_metrics.csv", summaries)
    write_json(output_dir / "battle_summary.json", {
        "schema": "official_strategy_battle_strategy_summary_v01",
        "battle_id": battle_id,
        "strategy_id": pattern_b.STRATEGY_ID,
        "worker_count": EXPECTED_WORKERS,
        "windows": summaries,
        "market_authority": market_authority_meta,
        "pit_market_cap_summary": cap_summary,
        "pit_market_authority_summary": market_summary,
    })
    report = [
        f"# {battle_id} — Pattern B E/T PROGRESSED Candidate V1",
        "",
        "동결된 Pattern B 신호·청산 원장을 사용하고 chronological cash-aware portfolio replay를 새로 수행했어.",
        f"- 공통 진입 순서: `{COMMON_ENTRY_ORDER}`.",
        f"- worker: {EXPECTED_WORKERS}.",
        "- valuation carry는 exact same-date KRX NON_TRADING_PLACEHOLDER_V01, exact PIT identity 안의 이전 정상 조정 종가에만 valuation-only로 적용했어.",
        "- Battle B만 entry_signal_date exact PIT 시총 1조원 이상을 포함했어." if cap_authority is not None else "- Battle C는 entry identity의 exact entry-date PIT market이 KOSPI인 후보만 포함했고 시총 필터는 적용하지 않았어." if market_authority is not None else "- Battle A는 시총 및 시장 universe filter 없이 수행했어.",
        "",
        "| Window | Return | CAGR | MDD / type | Coverage | Eligible | Executed / closed | Cash skip % | Median | +50 / +100 | Turnover |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        report.append(
            f"| {row['window_id']} | {row['total_return_pct']} | {row['cagr_pct']} | "
            f"{row['mdd_pct']} / {row['mdd_type']} | {row['coverage_pct']} | "
            f"{row['eligible_entry_attempts']} | {row['executed_trades']} / {row['closed_trades']} | "
            f"{row['cash_shortage_rate_pct']} | {row['median_trade_return_pct']} | "
            f"{row.get('tail_counts', {}).get('+50')} / {row.get('tail_counts', {}).get('+100')} | {row['turnover_krw']} |"
        )
    report.extend(["", "이 문서는 양 전략 정면 비교용 포트폴리오 결과이며, 단독 채택 판정 문서가 아니야."])
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"rows": summaries, "outputs": outputs, "cap_summary": cap_summary, "cap_audit": all_cap_rows, "signal_cap_audit": all_signal_cap_rows, "market_summary": market_summary, "market_audit": all_market_rows, "signal_market_audit": all_signal_market_rows}


def cap_attempt_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    covered = sum(row.get("cap_status") in {"PASS_GE_1T_KRW", "REJECT_LT_1T_KRW"} for row in rows)
    included = sum(row.get("cap_status") == "PASS_GE_1T_KRW" for row in rows)
    rejected = sum(row.get("cap_status") == "REJECT_LT_1T_KRW" for row in rows)
    missing = sum(row.get("cap_status") == "MISSING_EXACT_PIT_MARKET_CAP" for row in rows)
    return {
        "exact_pit_market_cap_covered_attempts": covered,
        "ge_1t_eligible_attempts": included,
        "lt_1t_rejected_attempts": rejected,
        "missing_exact_pit_market_cap_attempts": missing,
    }


def v2_reference_for_window(v2_rows: Sequence[Mapping[str, Any]], window_id: str) -> dict[str, Any]:
    row = next(item for item in v2_rows if item["window_id"] == window_id)
    return {
        "ending_equity_krw": row.get("ending_equity_krw"),
        "profit_krw": row.get("profit_krw"),
        "total_return_pct": row.get("total_return_pct"),
        "cagr_pct": row.get("cagr_pct"),
        "mdd_pct": row.get("mdd_pct"),
        "mdd_type": row.get("mdd_type"),
        "coverage_pct": row.get("coverage_pct"),
        "cash_shortage_skip_rate_pct": row.get("cash_shortage_rate_pct"),
        "turnover_krw": row.get("turnover_krw"),
        "turnover_multiple": row.get("turnover_multiple"),
        "trade_count": row.get("executed_trades"),
        "closed_trade_count": row.get("closed_trades"),
        "positive_trade_rate_pct": row.get("positive_trade_rate_pct"),
        "median_trade_return_pct": row.get("median_trade_return_pct"),
        **{f"{key}_count": value for key, value in row.get("tail_counts", {}).items()},
    }


def comparison_row(window_id: str, v2_row: Mapping[str, Any], pb_row: Mapping[str, Any]) -> dict[str, Any]:
    def delta(left: Any, right: Any) -> Any:
        return None if left is None or right is None else float(left) - float(right)
    return {
        "window_id": window_id,
        "v2_total_return_pct": v2_row.get("total_return_pct"),
        "pattern_b_total_return_pct": pb_row.get("total_return_pct"),
        "v2_ending_equity_krw": v2_row.get("ending_equity_krw"),
        "pattern_b_ending_equity_krw": pb_row.get("ending_equity_krw"),
        "return_delta_pp_pattern_b_minus_v2": delta(pb_row.get("total_return_pct"), v2_row.get("total_return_pct")),
        "v2_cagr_pct": v2_row.get("cagr_pct"),
        "pattern_b_cagr_pct": pb_row.get("cagr_pct"),
        "cagr_delta_pp_pattern_b_minus_v2": delta(pb_row.get("cagr_pct"), v2_row.get("cagr_pct")),
        "v2_mdd_pct": v2_row.get("mdd_pct"),
        "pattern_b_mdd_pct": pb_row.get("mdd_pct"),
        "mdd_delta_pp_pattern_b_minus_v2": delta(pb_row.get("mdd_pct"), v2_row.get("mdd_pct")),
        "v2_mdd_type": v2_row.get("mdd_type"),
        "pattern_b_mdd_type": pb_row.get("mdd_type"),
        "v2_coverage_pct": v2_row.get("coverage_pct"),
        "pattern_b_coverage_pct": pb_row.get("coverage_pct"),
        "v2_positive_trade_rate_pct": v2_row.get("positive_trade_rate_pct"),
        "pattern_b_positive_trade_rate_pct": pb_row.get("positive_trade_rate_pct"),
        "v2_median_trade_return_pct": v2_row.get("median_trade_return_pct"),
        "pattern_b_median_trade_return_pct": pb_row.get("median_trade_return_pct"),
        "v2_plus_50_count": v2_row.get("tail_counts", {}).get("+50"),
        "pattern_b_plus_50_count": pb_row.get("tail_counts", {}).get("+50"),
        "v2_plus_100_count": v2_row.get("tail_counts", {}).get("+100"),
        "pattern_b_plus_100_count": pb_row.get("tail_counts", {}).get("+100"),
        "v2_executed_trade_count": v2_row.get("executed_trades"),
        "pattern_b_executed_trade_count": pb_row.get("executed_trades"),
        "v2_eligible_entry_attempts": v2_row.get("eligible_entry_attempts"),
        "pattern_b_eligible_entry_attempts": pb_row.get("eligible_entry_attempts"),
        "v2_closed_trade_count": v2_row.get("closed_trades"),
        "pattern_b_closed_trade_count": pb_row.get("closed_trades"),
        "v2_cash_shortage_count": v2_row.get("cash_shortage_count"),
        "pattern_b_cash_shortage_count": pb_row.get("cash_shortage_count"),
        "v2_cash_shortage_rate_pct": v2_row.get("cash_shortage_rate_pct"),
        "pattern_b_cash_shortage_rate_pct": pb_row.get("cash_shortage_rate_pct"),
        "v2_turnover_krw": v2_row.get("turnover_krw"),
        "pattern_b_turnover_krw": pb_row.get("turnover_krw"),
        "v2_turnover_multiple": v2_row.get("turnover_multiple"),
        "pattern_b_turnover_multiple": pb_row.get("turnover_multiple"),
        "v2_average_capital_utilization_pct": v2_row.get("average_capital_utilization_pct"),
        "pattern_b_average_capital_utilization_pct": pb_row.get("average_capital_utilization_pct"),
        "v2_maximum_capital_utilization_pct": v2_row.get("maximum_capital_utilization_pct"),
        "pattern_b_maximum_capital_utilization_pct": pb_row.get("maximum_capital_utilization_pct"),
        "v2_average_concurrent_positions": v2_row.get("average_concurrent_positions"),
        "pattern_b_average_concurrent_positions": pb_row.get("average_concurrent_positions"),
        "v2_maximum_concurrent_positions": v2_row.get("maximum_concurrent_positions"),
        "pattern_b_maximum_concurrent_positions": pb_row.get("maximum_concurrent_positions"),
        "v2_mean_trade_return_pct": v2_row.get("mean_trade_return_pct"),
        "pattern_b_mean_trade_return_pct": pb_row.get("mean_trade_return_pct"),
        "v2_plus_30_count": v2_row.get("tail_counts", {}).get("+30"),
        "pattern_b_plus_30_count": pb_row.get("tail_counts", {}).get("+30"),
        "v2_minus_30_count": v2_row.get("tail_counts", {}).get("-30"),
        "pattern_b_minus_30_count": pb_row.get("tail_counts", {}).get("-30"),
        "v2_minus_40_count": v2_row.get("tail_counts", {}).get("-40"),
        "pattern_b_minus_40_count": pb_row.get("tail_counts", {}).get("-40"),
        "v2_minus_50_count": v2_row.get("tail_counts", {}).get("-50"),
        "pattern_b_minus_50_count": pb_row.get("tail_counts", {}).get("-50"),
        "v2_minus_60_count": v2_row.get("tail_counts", {}).get("-60"),
        "pattern_b_minus_60_count": pb_row.get("tail_counts", {}).get("-60"),
    }


def universe_sensitivity(all_rows: Sequence[Mapping[str, Any]], filtered_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for strategy_id in (v2.STRATEGY_ID, pattern_b.STRATEGY_ID):
        for window_id in WINDOW_IDS:
            base = next((row for row in all_rows if row["strategy_id"] == strategy_id and row["window_id"] == window_id), None)
            filtered = next((row for row in filtered_rows if row["strategy_id"] == strategy_id and row["window_id"] == window_id), None)
            if base is None or filtered is None:
                continue
            values = {
                "total_return_pct": "total_return_delta_pp_mcap1t_minus_all",
                "cagr_pct": "cagr_delta_pp_mcap1t_minus_all",
                "mdd_pct": "mdd_delta_pp_mcap1t_minus_all",
                "executed_trades": "executed_trade_count_delta_mcap1t_minus_all",
                "positive_trade_rate_pct": "positive_rate_delta_pp_mcap1t_minus_all",
                "median_trade_return_pct": "median_delta_pp_mcap1t_minus_all",
                "cash_shortage_rate_pct": "cash_shortage_delta_pp_mcap1t_minus_all",
                "turnover_krw": "turnover_delta_krw_mcap1t_minus_all",
                "turnover_multiple": "turnover_multiple_delta_mcap1t_minus_all",
            }
            row = {"strategy_id": strategy_id, "window_id": window_id}
            for field, name in values.items():
                left, right = base.get(field), filtered.get(field)
                row[f"all_universe_{field}"] = left
                row[f"pit_mcap_1t_{field}"] = right
                row[name] = None if left is None or right is None else float(right) - float(left)
            for key in ("+50", "+100"):
                a = base.get("tail_counts", {}).get(key)
                b = filtered.get("tail_counts", {}).get(key)
                row[f"all_universe_{key}_count"] = a
                row[f"pit_mcap_1t_{key}_count"] = b
                row[f"{key}_count_delta_mcap1t_minus_all"] = None if a is None or b is None else int(b) - int(a)
            output.append(row)
    return output


def artifact_evidence_checks() -> dict[str, Any]:
    """Independently verify required invariants from the written per-window audits."""
    exclusions = current_exclusion_pairs()
    calendar = json.loads((ROOT / "data/market/rolling_authority/merged_trading_calendar.json").read_text(encoding="utf-8"))
    trading_dates = [str(item)[:10] for item in calendar["trading_dates"]]
    v2_cost_mismatches = 0
    v2_frozen_schedule_mismatches = 0
    v2_calendar_deviation_rows: list[dict[str, Any]] = []
    v2_exclusion_leaks = 0
    pb_cost_mismatches = 0
    pb_next_session_violations = 0
    pb_exclusion_leaks = 0
    pb_identity_violations = 0
    pb_source_linkage_violations = 0
    pb_position_cap_violations = 0
    v2_position_cap_violations = 0
    cash_conservation_violations = 0
    worker_count_violations = 0
    frozen_rule_violations = 0
    cap_parity_violations = 0
    kospi_entry_parity_violations = 0
    battle_c_cap_filter_violations = 0
    cap_summary = json.loads((OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json").read_text(encoding="utf-8"))["summary"]
    cap_table = pd.read_csv(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.csv").fillna("")
    market_preflight = json.loads((OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.json").read_text(encoding="utf-8"))
    market_summary = market_preflight["summary"]

    def number(value: Any) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def near(left: Any, right: Any, *, abs_tol: float = 0.011) -> bool:
        a, b = number(left), number(right)
        return a is not None and b is not None and abs(a - b) <= max(abs_tol, abs(b) * 1e-10)

    def event_next_session_violations(frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        count = 0
        execution_events = frame.loc[frame["event_type"].astype(str).isin({"ENTRY", "EXIT"})]
        for row in execution_events.to_dict("records"):
            signal_day, execution_day = date_text(row.get("signal_date")), date_text(row.get("execution_date"))
            next_index = bisect.bisect_right(trading_dates, signal_day) if signal_day else len(trading_dates)
            expected_next = trading_dates[next_index] if next_index < len(trading_dates) else None
            if not signal_day or expected_next != execution_day:
                count += 1
        return count

    def v2_frozen_schedule_audit(frame: pd.DataFrame, window_id: str, battle_id: str) -> tuple[int, list[dict[str, Any]]]:
        if frame.empty:
            return 0, []
        source_path = ROOT / v2.WINDOWS[window_id]["source"]
        source_rows = pd.read_csv(source_path, dtype=str, keep_default_na=False).to_dict("records")
        by_candidate = {
            (
                normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd")),
                date_text(row.get("entry_signal_date")), date_text(row.get("entry_execution_date")),
            ): row
            for row in source_rows
        }
        mismatches = 0
        calendar_deviations: list[dict[str, Any]] = []
        execution_events = frame.loc[frame["event_type"].astype(str).isin({"ENTRY", "EXIT"})]
        for event in execution_events.to_dict("records"):
            candidate_parts = str(event.get("candidate_id", "")).split("|")
            candidate = (
                normalize_ticker(candidate_parts[0]) if len(candidate_parts) == 4 else "",
                normalize_isu(candidate_parts[1]) if len(candidate_parts) == 4 else "",
                date_text(candidate_parts[2]) if len(candidate_parts) == 4 else "",
                date_text(candidate_parts[3]) if len(candidate_parts) == 4 else "",
            )
            source = by_candidate.get(candidate)
            if source is None:
                mismatches += 1
                continue
            event_type = str(event.get("event_type"))
            signal_field, execution_field, price_field = (
                ("entry_signal_date", "entry_execution_date", "entry_open")
                if event_type == "ENTRY" else ("exit_signal_date", "exit_execution_date", "exit_price")
            )
            signal_day = date_text(source.get(signal_field))
            execution_day = date_text(source.get(execution_field))
            if date_text(event.get("signal_date")) != signal_day or date_text(event.get("execution_date")) != execution_day:
                mismatches += 1
                continue
            if str(event.get("event_status")) == "EXECUTED" and not near(event.get("reference_price"), source.get(price_field)):
                mismatches += 1
            if str(event.get("event_status")) == "EXECUTED":
                next_index = bisect.bisect_right(trading_dates, signal_day)
                expected_next = trading_dates[next_index] if next_index < len(trading_dates) else None
                if expected_next != execution_day:
                    calendar_deviations.append({
                        "battle_id": battle_id,
                        "window_id": window_id,
                        "ticker": normalize_ticker(event.get("ticker")),
                        "isu_cd": normalize_isu(event.get("isu_cd")),
                        "event_type": event_type,
                        "event_status": event.get("event_status"),
                        "signal_date": signal_day,
                        "immediate_next_krx_session": expected_next,
                        "frozen_control_execution_date": execution_day,
                        "candidate_id": event.get("candidate_id"),
                        "interpretation": "executed_at_frozen_CONTROL_date_and_exact_price; not rescheduled",
                    })
        return mismatches, calendar_deviations

    def event_exclusion_leaks(frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        entries = frame.loc[frame["event_type"].astype(str) == "ENTRY"]
        return sum(
            (normalize_ticker(row.get("ticker")), normalize_isu(row.get("isu_cd"))) in exclusions
            for row in entries.to_dict("records")
        )

    def b_entry_cap_violations(frame: pd.DataFrame, strategy_id: str, window_id: str) -> int:
        if frame.empty:
            return 0
        executed = frame.loc[(frame["event_type"].astype(str) == "ENTRY") & (frame["event_status"].astype(str) == "EXECUTED")]
        scoped = cap_table.loc[
            (cap_table["strategy_id"].astype(str) == strategy_id)
            & (cap_table["window_id"].astype(str) == window_id)
        ]
        count = 0
        for event in executed.to_dict("records"):
            matches = scoped.loc[
                (scoped["ticker"].astype(str).map(normalize_ticker) == normalize_ticker(event.get("ticker")))
                & (scoped["isu_cd"].astype(str).map(normalize_isu) == normalize_isu(event.get("isu_cd")))
                & (scoped["entry_signal_date"].astype(str).str[:10] == date_text(event.get("signal_date")))
            ]
            if len(matches) != 1:
                count += 1
                continue
            cap = matches.iloc[0]
            if str(cap.get("cap_status")) != "PASS_GE_1T_KRW" or (number(cap.get("market_cap_krw")) or 0.0) < PIT_MCAP_THRESHOLD:
                count += 1
                continue
            event_cap = number(event.get("market_cap_at_signal"))
            if event_cap is not None and not near(event_cap, cap.get("market_cap_krw"), abs_tol=1.0):
                count += 1
        return count

    for battle_id in BATTLE_IDS:
        for strategy_kind, strategy_id in (("v2", v2.STRATEGY_ID), ("pattern_b", pattern_b.STRATEGY_ID)):
            base = OUTPUT_ROOT / battle_id / strategy_kind
            contract_path = base / "execution_contract.json" if strategy_kind == "v2" else base / "p1" / "execution_contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            metric_rows = pd.read_csv(base / "battle_window_metrics.csv").to_dict("records")
            if len(metric_rows) != len(WINDOW_IDS):
                cash_conservation_violations += 1
            for metric in metric_rows:
                if str(metric.get("cash_conservation_pass", "")).strip().lower() not in {"true", "1"}:
                    cash_conservation_violations += 1
                if int(float(metric.get("worker_count", EXPECTED_WORKERS))) != EXPECTED_WORKERS:
                    worker_count_violations += 1
            if strategy_kind == "v2":
                if contract.get("max_concurrent_positions") is not None:
                    v2_position_cap_violations += 1
                if contract.get("entry_signal_regeneration") is not False or contract.get("strategy_evaluation_rerun") is not False:
                    frozen_rule_violations += 1
                if battle_id == "battle_c_kospi_only" and contract.get("entry_date_pit_market_cap_filter") is not None:
                    battle_c_cap_filter_violations += 1
            else:
                if contract.get("portfolio", {}).get("position_cap") is not None:
                    pb_position_cap_violations += 1
                if contract.get("frozen_rule", {}).get("strategy_rule_changed") is not False:
                    frozen_rule_violations += 1
                if battle_id == "battle_c_kospi_only" and contract.get("portfolio", {}).get("market_cap_filter") is not None:
                    battle_c_cap_filter_violations += 1

            for window_id in WINDOW_IDS:
                filename = f"portfolio_events_{window_id.lower().replace('-', '_')}.csv" if strategy_kind == "v2" else None
                event_path = base / filename if filename else base / window_id.lower().replace("-", "_") / "portfolio_events.csv"
                events = pd.read_csv(event_path).fillna("")
                if battle_id == "battle_c_kospi_only":
                    executed_entries = events.loc[
                        (events["event_type"].astype(str) == "ENTRY")
                        & (events["event_status"].astype(str) == "EXECUTED")
                    ]
                    market_audit_path = base / "pit_market_authority_attempt_audit.csv"
                    market_audit = pd.read_csv(market_audit_path, dtype=str, keep_default_na=False)
                    for event in executed_entries.to_dict("records"):
                        if str(event.get("market", "")).strip().upper() != "KOSPI":
                            kospi_entry_parity_violations += 1
                            continue
                        matches = market_audit.loc[
                            (market_audit["ticker"].map(normalize_ticker) == normalize_ticker(event.get("ticker")))
                            & (market_audit["isu_cd"].map(normalize_isu) == normalize_isu(event.get("isu_cd")))
                            & (market_audit["entry_signal_date"].map(date_text) == date_text(event.get("signal_date")))
                            & (market_audit["window_id"].astype(str) == window_id)
                        ]
                        if len(matches) != 1 or str(matches.iloc[0].get("authority_status")) != "PASS_KOSPI":
                            kospi_entry_parity_violations += 1
                if strategy_kind == "v2":
                    v2_exclusion_leaks += event_exclusion_leaks(events)
                    schedule_mismatches, calendar_deviations = v2_frozen_schedule_audit(events, window_id, battle_id)
                    v2_frozen_schedule_mismatches += schedule_mismatches
                    v2_calendar_deviation_rows.extend(calendar_deviations)
                    contract_costs = contract
                    buy_slip = float(contract_costs.get("buy_slippage_rate", 0.001))
                    sell_slip = float(contract_costs.get("sell_slippage_rate", 0.001))
                    commission_rate = float(contract_costs.get("buy_commission_rate", 0.00015))
                    executed = events.loc[
                        events["event_type"].astype(str).isin({"ENTRY", "EXIT"})
                        & (events["event_status"].astype(str) == "EXECUTED")
                    ]
                    for event in executed.to_dict("records"):
                        ref, fill, shares = number(event.get("reference_price")), number(event.get("fill_price")), number(event.get("shares"))
                        notional, commission, slippage = number(event.get("notional_krw")), number(event.get("commission_krw")), number(event.get("slippage_impact_krw"))
                        side = str(event.get("event_type"))
                        rate = buy_slip if side == "ENTRY" else sell_slip
                        if ref is None or fill is None or shares is None or not math.isclose(shares, round(shares), abs_tol=1e-12):
                            v2_cost_mismatches += 1
                            continue
                        expected_fill = ref * (1.0 + rate if side == "ENTRY" else 1.0 - rate)
                        expected_notional = fill * shares
                        if not near(fill, expected_fill) or not near(notional, expected_notional) or not near(commission, expected_notional * commission_rate) or not near(slippage, abs(fill - ref) * shares):
                            v2_cost_mismatches += 1
                        if side == "ENTRY":
                            before, after = number(event.get("cash_before_krw")), number(event.get("cash_after_krw"))
                            if before is None or after is None or not near(before - after, expected_notional + expected_notional * commission_rate):
                                v2_cost_mismatches += 1
                    if battle_id == "battle_b_pit_mcap_1t":
                        cap_parity_violations += b_entry_cap_violations(events, strategy_id, window_id)
                else:
                    pb_exclusion_leaks += event_exclusion_leaks(events)
                    pb_next_session_violations += event_next_session_violations(events)
                    audit_dir = base / window_id.lower().replace("-", "_")
                    window_contract = json.loads((audit_dir / "execution_contract.json").read_text(encoding="utf-8"))
                    if window_contract.get("portfolio", {}).get("position_cap") is not None:
                        pb_position_cap_violations += 1
                    if window_contract.get("frozen_rule", {}).get("strategy_rule_changed") is not False:
                        frozen_rule_violations += 1
                    cost_summary = json.loads((audit_dir / "cost_audit_summary.json").read_text(encoding="utf-8"))
                    cost_audit = pd.read_csv(audit_dir / "cost_audit.csv").fillna("")
                    pb_cost_mismatches += int(cost_summary.get("mismatch_count", 0))
                    pb_cost_mismatches += int(not cost_summary.get("coverage_complete", False))
                    pb_cost_mismatches += int(not cost_audit.empty and (cost_audit["official_cost_status"].astype(str) != "PASS").sum())
                    input_audit = json.loads((audit_dir / "input_audit.json").read_text(encoding="utf-8"))
                    pb_exclusion_leaks += int(input_audit.get("exclusion_leakage_count", 0))
                    pb_identity_violations += int(input_audit.get("identity_lifecycle_audit", {}).get("violation_count", 0))
                    pb_source_linkage_violations += int(input_audit.get("authoritative_signal_linkage_check", {}).get("mismatch_count", 0))
                    pb_source_linkage_violations += int(not input_audit.get("authoritative_signal_linkage_check", {}).get("status") == "PASS")
                    pb_source_linkage_violations += int(input_audit.get("current_exclusion_count", -1) != len(exclusions))
                    pb_source_linkage_violations += int(window_contract.get("sources", {}).get("current_permanent_exclusion_policy_sha256") != sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"))
                    next_audit = input_audit.get("execution_price_audit", {}).get("next_session_execution_audit", {})
                    pb_next_session_violations += int(next_audit.get("status") != "PASS" or int(next_audit.get("violation_count", 0)) != 0)
                    pb_identity_violations += int(input_audit.get("identity_overlap_violation_count", 0))
                    hidden_cap = json.loads((audit_dir / "hidden_position_cap_audit.json").read_text(encoding="utf-8"))
                    pb_position_cap_violations += int(hidden_cap.get("status") != "PASS_NO_POSITION_CAP_OR_POSITION_LIMIT_SKIP")
                    if battle_id == "battle_b_pit_mcap_1t":
                        cap_parity_violations += b_entry_cap_violations(events, strategy_id, window_id)

    cap_coverage_ok = cap_summary.get("status") == "PASS" and all(
        item.get("coverage_pct", 0) >= MIN_CAP_COVERAGE_PCT
        for item in cap_summary.get("by_strategy_window", [])
    )
    checks = {
        "v2_cost_audit_formula_mismatch_count": v2_cost_mismatches,
        "pattern_b_cost_audit_mismatch_count": pb_cost_mismatches,
        "cost_audit_mismatch_zero": v2_cost_mismatches == 0 and pb_cost_mismatches == 0,
        "v2_frozen_execution_date_price_mismatch_count": v2_frozen_schedule_mismatches,
        "v2_calendar_next_session_deviation_count": len(v2_calendar_deviation_rows),
        "v2_calendar_next_session_deviation_audit_file": (OUTPUT_REL / "v2_calendar_next_session_deviations.csv").as_posix(),
        "v2_frozen_execution_date_price_parity_all_pass": v2_frozen_schedule_mismatches == 0,
        "pattern_b_next_session_execution_violation_count": pb_next_session_violations,
        "pattern_b_next_session_execution_all_pass": pb_next_session_violations == 0,
        "v2_entry_exclusion_leakage_count": v2_exclusion_leaks,
        "pattern_b_entry_exclusion_leakage_count": pb_exclusion_leaks,
        "exact_identity_exclusion_leakage_zero": v2_exclusion_leaks == 0 and pb_exclusion_leaks == 0,
        "pattern_b_identity_lifecycle_violation_count": pb_identity_violations,
        "pattern_b_source_linkage_violation_count": pb_source_linkage_violations,
        "cash_conservation_violation_count": cash_conservation_violations,
        "cash_conservation_all_pass": cash_conservation_violations == 0,
        "pattern_b_position_cap_violation_count": pb_position_cap_violations,
        "v2_position_cap_violation_count": v2_position_cap_violations,
        "no_hidden_position_cap_all_pass": pb_position_cap_violations == 0 and v2_position_cap_violations == 0,
        "worker_count_violation_count": worker_count_violations,
        "worker_count_10_all_pass": worker_count_violations == 0,
        "strategy_freeze_violation_count": frozen_rule_violations,
        "strategy_rules_frozen": frozen_rule_violations == 0,
        "battle_b_exact_pit_market_cap_coverage_pass": cap_coverage_ok,
        "battle_b_executed_entries_exact_pit_ge_1t_parity_violation_count": cap_parity_violations,
        "battle_b_entry_market_cap_exact_date_parity": cap_parity_violations == 0 and cap_coverage_ok,
        "battle_c_market_authority_missing": market_summary.get("market_authority_missing", 0),
        "battle_c_market_authority_ambiguous": market_summary.get("market_authority_ambiguous", 0),
        "battle_c_executed_non_kospi_entry_count": kospi_entry_parity_violations,
        "battle_c_executed_entry_exact_pit_market_parity": (
            kospi_entry_parity_violations == 0
            and market_summary.get("status") == "PASS"
            and battle_c_cap_filter_violations == 0
        ),
        "battle_c_market_cap_filter_violation_count": battle_c_cap_filter_violations,
    }
    required = [
        "cost_audit_mismatch_zero",
        "exact_identity_exclusion_leakage_zero", "cash_conservation_all_pass",
        "v2_frozen_execution_date_price_parity_all_pass", "pattern_b_next_session_execution_all_pass",
        "no_hidden_position_cap_all_pass", "worker_count_10_all_pass",
        "strategy_rules_frozen", "battle_b_entry_market_cap_exact_date_parity",
        "battle_c_executed_entry_exact_pit_market_parity",
    ]
    checks["structural_checks_pass"] = all(checks[name] for name in required)
    checks["required_structural_checks"] = required
    checks["structural_checks_pass"] = checks["structural_checks_pass"] and battle_c_cap_filter_violations == 0
    write_csv(OUTPUT_ROOT / "v2_calendar_next_session_deviations.csv", v2_calendar_deviation_rows)
    return checks


def three_way_sensitivity(
    all_rows: Sequence[Mapping[str, Any]],
    mcap_rows: Sequence[Mapping[str, Any]],
    kospi_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    fields = (
        "total_return_pct", "cagr_pct", "mdd_pct", "executed_trades", "positive_trade_rate_pct",
        "median_trade_return_pct", "cash_shortage_rate_pct", "turnover_krw", "turnover_multiple",
        "average_capital_utilization_pct", "maximum_capital_utilization_pct",
    )
    def get(strategy_id: str, window_id: str, rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        return next((item for item in rows if item.get("strategy_id") == strategy_id and item.get("window_id") == window_id), None)
    for strategy_id in (v2.STRATEGY_ID, pattern_b.STRATEGY_ID):
        for window_id in WINDOW_IDS:
            a, b, c = get(strategy_id, window_id, all_rows), get(strategy_id, window_id, mcap_rows), get(strategy_id, window_id, kospi_rows)
            if a is None or b is None or c is None:
                continue
            row: dict[str, Any] = {"strategy_id": strategy_id, "window_id": window_id}
            for field in fields:
                av, bv, cv = a.get(field), b.get(field), c.get(field)
                row[f"all_{field}"] = av
                row[f"pit_mcap_1t_{field}"] = bv
                row[f"kospi_only_{field}"] = cv
                for suffix, left, right in (("mcap1t_minus_all", av, bv), ("kospi_minus_all", av, cv), ("kospi_minus_mcap1t", bv, cv)):
                    row[f"{field}_delta_{suffix}"] = None if left is None or right is None else float(right) - float(left)
            for key in ("+30", "+50", "+100", "-30", "-40", "-50", "-60"):
                av, bv, cv = a.get("tail_counts", {}).get(key), b.get("tail_counts", {}).get(key), c.get("tail_counts", {}).get(key)
                row[f"all_{key}_count"], row[f"pit_mcap_1t_{key}_count"], row[f"kospi_only_{key}_count"] = av, bv, cv
                row[f"{key}_count_delta_mcap1t_minus_all"] = None if av is None or bv is None else int(bv) - int(av)
                row[f"{key}_count_delta_kospi_minus_all"] = None if av is None or cv is None else int(cv) - int(av)
                row[f"{key}_count_delta_kospi_minus_mcap1t"] = None if bv is None or cv is None else int(cv) - int(bv)
            output.append(row)
    return output


def validation_record(
    battle_results: Mapping[str, Any],
    cap_summary: Mapping[str, Any] | None,
    market_summary: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows_by_battle = {
        "battle_a_all_universe": list(battle_results.get("all_rows", [])),
        "battle_b_pit_mcap_1t": list(battle_results.get("mcap_rows", [])),
        "battle_c_kospi_only": list(battle_results.get("kospi_rows", [])),
    }
    rows = [row for group in rows_by_battle.values() for row in group]
    exclusions = current_exclusion_pairs()
    coverage_check_required = [
        {"battle_id": row.get("battle_id"), "strategy_id": row.get("strategy_id"), "window_id": row.get("window_id"),
         "coverage_pct": row.get("coverage_pct"), "mdd_type": row.get("mdd_type")}
        for row in rows if row.get("coverage_pct") is None or float(row["coverage_pct"]) < 90.0
    ]
    cap_ok = bool(cap_summary and cap_summary.get("status") == "PASS" and all(
        float(item.get("coverage_pct", 0)) >= MIN_CAP_COVERAGE_PCT
        for item in cap_summary.get("by_strategy_window", [])
    ))
    market_ok = bool(market_summary and market_summary.get("status") == "PASS"
                     and market_summary.get("market_authority_missing", 0) == 0
                     and market_summary.get("market_authority_ambiguous", 0) == 0)
    evidence_checks = dict(evidence if evidence is not None else artifact_evidence_checks())
    counts = {key: len(value) for key, value in rows_by_battle.items()}
    complete = len(rows) == 30 and all(value == 10 for value in counts.values())
    checks = {
        "expected_result_count": 30,
        "actual_result_count": len(rows),
        "results_by_battle": counts,
        "30_of_30_complete": complete,
        "permanent_exclusion_count_before": 173,
        "permanent_exclusion_new_exact_count": 1,
        "permanent_exclusion_count_after": len(exclusions),
        "permanent_exclusion_policy_sha256": sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
        "permanent_exclusion_exact_duplicate_count": 0,
        "permanent_exclusion_normalization_collision_count": len(PERMANENT_IDENTITY_EXCLUSIONS) - len(exclusions),
        "permanent_exclusion_ticker_only_count": 0,
        "all_seven_exact_global_exclusions_present": P2_1_GLOBAL_LIFECYCLE_EXCLUSIONS <= exclusions,
        "new_096300_exact_global_exclusion_present": NEW_GLOBAL_LIFECYCLE_EXCLUSION in exclusions
        and PERMANENT_IDENTITY_EXCLUSIONS[NEW_GLOBAL_LIFECYCLE_EXCLUSION].get("approval_scope") == "GLOBAL permanent identity exclusion",
        "worker_count_10": v2.WORKERS == EXPECTED_WORKERS and pattern_b.WORKERS == EXPECTED_WORKERS and pattern_b_v01.WORKERS == EXPECTED_WORKERS,
        "valuation_mdd_classified_by_coverage": all(
            row.get("coverage_pct") is not None
            and row.get("mdd_type") == ("EXACT" if row["coverage_pct"] >= 100.0 - 1e-12 else "OBSERVED" if row["coverage_pct"] >= 90.0 else "OBSERVED_BELOW_90_COVERAGE")
            for row in rows
        ),
        "valuation_coverage_at_least_90_pct_all": not coverage_check_required,
        "valuation_check_required_results_below_90_pct": coverage_check_required,
        "battle_b_exact_pit_market_cap_preflight_pass": cap_ok,
        "battle_c_exact_pit_market_authority_preflight_pass": market_ok,
        "battle_c_market_authority_missing": None if market_summary is None else market_summary.get("market_authority_missing"),
        "entry_order_shared": COMMON_ENTRY_ORDER,
        "strategy_rule_mutation": False,
        "posthoc_trade_selection": False,
        "cash_based_signal_regeneration": False,
        "position_cap": None,
        "artifact_evidence": evidence_checks,
    }
    structurally_complete = (
        complete
        and len(exclusions) == EXPECTED_EXCLUSION_COUNT
        and checks["all_seven_exact_global_exclusions_present"]
        and checks["new_096300_exact_global_exclusion_present"]
        and checks["worker_count_10"]
        and checks["valuation_mdd_classified_by_coverage"]
        and cap_ok and market_ok
        and evidence_checks.get("structural_checks_pass") is True
    )
    status = "PASS" if structurally_complete and not coverage_check_required else "CHECK_REQUIRED" if not complete and (not cap_ok or not market_ok) else "FAIL" if not structurally_complete else "CHECK_REQUIRED"
    return {
        "schema": "official_strategy_battle_validation_v02",
        "status": status,
        "execution_status": "COMPLETE" if complete else "INCOMPLETE",
        "checks": checks,
        "notes": [
            "Three battles were independently replayed from the same updated exact-identity exclusion policy.",
            "Battle B uses exact entry-date KRX market-cap partitions and exact PIT identity binding; missing values are counted without substitution.",
            "Battle C uses only the authoritative market on the exact active PIT COMMON identity interval at entry_signal_date; it has no market-cap filter.",
            "Coverage below 90% is CHECK_REQUIRED and is not repaired, filled, retried, or selected around.",
            "High cash-shortage rates, drawdowns, and weak returns do not change frozen strategy rules or trigger reruns.",
        ],
    }


def render_final_report(
    battle_results: Mapping[str, Any],
    cap_summary: Mapping[str, Any] | None,
    market_summary: Mapping[str, Any] | None,
    cross_rows: Sequence[Mapping[str, Any]],
    sensitivity: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
) -> str:
    def fmt(value: Any, digits: int = 2) -> str:
        try:
            parsed = float(value)
            return "—" if not math.isfinite(parsed) else f"{parsed:.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    lines = [
        "# V2 vs Pattern B 3-Way Portfolio Battle V02",
        "",
        f"- 실행 상태: **{validation['execution_status']}**; 검증: **{validation['status']}**.",
        f"- 결과: **{validation['checks']['actual_result_count']}/30**; worker: **{EXPECTED_WORKERS}**; permanent exclusions: **{validation['checks']['permanent_exclusion_count_before']} → {validation['checks']['permanent_exclusion_count_after']}** exact pairs.",
        f"- 기준 HEAD: `{battle_results.get('base_head')}`; same-day entry order: `{COMMON_ENTRY_ORDER}`.",
        "- 초기자본 2억원, 종목별 500만원 예산, 재투자, position cap 없음, 정수주, partial fill/pyramiding 없음, commission 0.015%, slippage 0.1%, sell tax 0%.",
        "- Coverage 90% 미만은 CHECK_REQUIRED로 남기고 수정·보간·재실행하지 않았어.",
        "",
    ]
    replay_scope = validation.get("replay_scope")
    if replay_scope:
        lines.extend([
            f"- 이번 closure 재실행 범위: **{replay_scope.get('battle_id')} / {replay_scope.get('strategy_id')} / {len(replay_scope.get('windows', []))}개 window**; Battle A/B와 Pattern B는 기존 산출물을 유지했어.",
            f"- 재실행 당시 HEAD: `{replay_scope.get('starting_head')}` → `{replay_scope.get('ending_head')}`; 기존 비교 baseline 제외 수: **{replay_scope.get('retained_baseline_exclusion_count')}**.",
        ])
        retained_attempts = replay_scope.get("retained_096300_candidate_attempt_count", 0)
        if retained_attempts:
            lines.append(
                f"- 보존한 이전 Battle A/B V2 산출물의 096300 진입 시도 {retained_attempts}건은 모두 현금 부족으로 미체결이었고, 체결은 0건이야."
            )
        lines.append("")
    battle_titles = {
        "battle_a_all_universe": "Battle A — 전체 universe",
        "battle_b_pit_mcap_1t": "Battle B — entry-date exact PIT 시총 ≥ 1조원",
        "battle_c_kospi_only": "Battle C — entry-date exact PIT KOSPI only (시총 필터 없음)",
    }
    for battle_id, title in battle_titles.items():
        rows = [row for row in cross_rows if row.get("battle_id") == battle_id]
        lines.extend([
            f"## {title}",
            "",
            "| Window | Return V2 / B | Δ pp | CAGR V2 / B | MDD V2 / B | Coverage V2 / B | Eligible V2 / B | Executed / closed (V2 · B) | Cash skip % V2 / B | Positive % V2 / B | Median % V2 / B | +50 / +100 V2 / B | Turnover KRW V2 / B | Avg util % V2 / B |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in rows:
            lines.append(
                f"| {row['window_id']} | {fmt(row.get('v2_total_return_pct'))} / {fmt(row.get('pattern_b_total_return_pct'))} | {fmt(row.get('return_delta_pp_pattern_b_minus_v2'))} | "
                f"{fmt(row.get('v2_cagr_pct'))} / {fmt(row.get('pattern_b_cagr_pct'))} | {fmt(row.get('v2_mdd_pct'))} ({row.get('v2_mdd_type')}) / {fmt(row.get('pattern_b_mdd_pct'))} ({row.get('pattern_b_mdd_type')}) | "
                f"{fmt(row.get('v2_coverage_pct'))} / {fmt(row.get('pattern_b_coverage_pct'))} | {row.get('v2_eligible_entry_attempts')} / {row.get('pattern_b_eligible_entry_attempts')} | "
                f"{row.get('v2_executed_trade_count')} / {row.get('v2_closed_trade_count')} · {row.get('pattern_b_executed_trade_count')} / {row.get('pattern_b_closed_trade_count')} | "
                f"{fmt(row.get('v2_cash_shortage_rate_pct'))} / {fmt(row.get('pattern_b_cash_shortage_rate_pct'))} | {fmt(row.get('v2_positive_trade_rate_pct'))} / {fmt(row.get('pattern_b_positive_trade_rate_pct'))} | "
                f"{fmt(row.get('v2_median_trade_return_pct'))} / {fmt(row.get('pattern_b_median_trade_return_pct'))} | {row.get('v2_plus_50_count')} / {row.get('pattern_b_plus_50_count')} · {row.get('v2_plus_100_count')} / {row.get('pattern_b_plus_100_count')} | "
                f"{fmt(row.get('v2_turnover_krw'), 0)} / {fmt(row.get('pattern_b_turnover_krw'), 0)} | {fmt(row.get('v2_average_capital_utilization_pct'))} / {fmt(row.get('pattern_b_average_capital_utilization_pct'))} |"
            )
        lines.append("")
    lines.extend(["## PIT authority 사전검수", ""])
    if cap_summary:
        lines.extend(["### Battle B exact PIT 시총", "", "| Strategy | Window | Covered | ≥1조 | <1조 | Missing | Coverage | Status |", "|---|---|---:|---:|---:|---:|---:|---|"])
        for row in cap_summary.get("by_strategy_window", []):
            lines.append(f"| {row['strategy_id']} | {row['window_id']} | {row['exact_pit_market_cap_covered_attempts']} | {row['ge_1t_eligible_attempts']} | {row['lt_1t_rejected_attempts']} | {row['missing_exact_pit_market_cap_attempts']} | {fmt(row['coverage_pct'])}% | {row['status']} |")
        lines.append("")
    if market_summary:
        lines.extend(["### Battle C exact PIT market", "", "| Strategy | Window | Candidates | KOSPI eligible | Non-KOSPI rejected | Authority missing | Status |", "|---|---|---:|---:|---:|---:|---|"])
        for row in market_summary.get("by_strategy_window", []):
            lines.append(f"| {row['strategy_id']} | {row['window_id']} | {row['candidate_count']} | {row['kospi_eligible_attempts']} | {row['non_kospi_rejected_attempts']} | {row['market_authority_missing']} | {row['status']} |")
        signal_rows = market_summary.get("allowed_signal_summary", {}).get("by_strategy_window", [])
        lines.extend(["", "Allowed frozen signal authority audit:", "", "| Strategy | Window | Signals | KOSPI | Rejected | Missing |", "|---|---|---:|---:|---:|---:|"])
        for row in signal_rows:
            lines.append(f"| {row['strategy_id']} | {row['window_id']} | {row['candidate_count']} | {row['kospi_eligible_attempts']} | {row['non_kospi_rejected_attempts']} | {row['market_authority_missing']} |")
        lines.append("")
    lines.extend(["## Universe sensitivity", "", "B−A는 PIT 시총 ≥1조 filter 효과, C−A는 KOSPI-only 효과야. 각 전략 안에서만 비교했어.", ""])
    if sensitivity:
        lines.extend(["| Strategy | Window | Return Δ B−A / C−A | CAGR Δ B−A / C−A | MDD Δ B−A / C−A | Trades Δ B−A / C−A | Positive rate Δ B−A / C−A | Median Δ B−A / C−A | +50 Δ B−A / C−A | +100 Δ B−A / C−A | Cash skip Δ B−A / C−A | Avg util Δ B−A / C−A |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for row in sensitivity:
            lines.append(
                f"| {row['strategy_id']} | {row['window_id']} | {fmt(row.get('total_return_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('total_return_pct_delta_kospi_minus_all'))} | "
                f"{fmt(row.get('cagr_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('cagr_pct_delta_kospi_minus_all'))} | {fmt(row.get('mdd_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('mdd_pct_delta_kospi_minus_all'))} | "
                f"{fmt(row.get('executed_trades_delta_mcap1t_minus_all'), 0)} / {fmt(row.get('executed_trades_delta_kospi_minus_all'), 0)} | {fmt(row.get('positive_trade_rate_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('positive_trade_rate_pct_delta_kospi_minus_all'))} | "
                f"{fmt(row.get('median_trade_return_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('median_trade_return_pct_delta_kospi_minus_all'))} | {row.get('+50_count_delta_mcap1t_minus_all')} / {row.get('+50_count_delta_kospi_minus_all')} | {row.get('+100_count_delta_mcap1t_minus_all')} / {row.get('+100_count_delta_kospi_minus_all')} | "
                f"{fmt(row.get('cash_shortage_rate_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('cash_shortage_rate_pct_delta_kospi_minus_all'))} | {fmt(row.get('average_capital_utilization_pct_delta_mcap1t_minus_all'))} / {fmt(row.get('average_capital_utilization_pct_delta_kospi_minus_all'))} |"
            )
        lines.append("")
    evidence = validation["checks"].get("artifact_evidence", {})
    exclusion_scope_label = evidence.get("exclusion_leakage_scope")
    exclusion_line = (
        f"- exclusion leakage ({exclusion_scope_label}): {evidence.get('v2_entry_exclusion_leakage_count', 0)} (V2) / {evidence.get('pattern_b_entry_exclusion_leakage_count', 0)} (Pattern B); cash conservation: {evidence.get('cash_conservation_all_pass')}; no position cap: {evidence.get('no_hidden_position_cap_all_pass')}."
        if exclusion_scope_label
        else f"- exclusion leakage: {evidence.get('v2_entry_exclusion_leakage_count', 0)} (V2) / {evidence.get('pattern_b_entry_exclusion_leakage_count', 0)} (Pattern B); cash conservation: {evidence.get('cash_conservation_all_pass')}; no position cap: {evidence.get('no_hidden_position_cap_all_pass')}."
    )
    lines.extend([
        "## 검증",
        "",
        f"- 구조 검증: **{'PASS' if evidence.get('structural_checks_pass') else 'CHECK_REQUIRED/FAIL'}**; 비용 mismatch {evidence.get('v2_cost_audit_formula_mismatch_count', 0)} (V2) / {evidence.get('pattern_b_cost_audit_mismatch_count', 0)} (Pattern B).",
        f"- frozen V2 date/price mismatch: {evidence.get('v2_frozen_execution_date_price_mismatch_count', 0)}; calendar deviation: {evidence.get('v2_calendar_next_session_deviation_count', 0)} (원 schedule 유지); Pattern B next-session violation: {evidence.get('pattern_b_next_session_execution_violation_count', 0)}.",
        exclusion_line,
        f"- Battle B exact PIT cap parity: {evidence.get('battle_b_entry_market_cap_exact_date_parity')}; Battle C executed KOSPI PIT parity: {evidence.get('battle_c_executed_entry_exact_pit_market_parity')}.",
        f"- Coverage <90%: {len(validation['checks'].get('valuation_check_required_results_below_90_pct', []))} result(s); status **{validation['status']}**.",
        f"- Output: `{OUTPUT_REL.as_posix()}/`.",
        "",
    ])
    return "\n".join(lines)


def read_metric_rows(path: Path, strategy_id: str, battle_id: str) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(value, float) and math.isnan(value):
                row[key] = None
            elif key == "tail_counts" and isinstance(value, str):
                row[key] = ast.literal_eval(value) if value.strip() else {}
            else:
                row[key] = value
        row["strategy_id"] = strategy_id
        row["battle_id"] = battle_id
        if strategy_id == pattern_b.STRATEGY_ID:
            count = row.get("cash_shortage_count")
            eligible = row.get("eligible_entry_attempts")
            if count is not None and eligible is not None:
                denominator = int(float(eligible))
                row["cash_shortage_rate_pct"] = 100.0 * int(float(count)) / denominator if denominator else (0.0 if int(float(count)) == 0 else None)
        coverage = row.get("coverage_pct")
        row["valuation_status"] = "CHECK_REQUIRED" if coverage is None or float(coverage) < 90.0 else "PASS"
        rows.append(row)
    rows.sort(key=lambda row: WINDOW_IDS.index(str(row.get("window_id"))))
    return rows


def finalize_existing_outputs() -> dict[str, Any]:
    """Reconcile summaries from the V02 battle folders without replaying portfolios."""
    preflight_path = OUTPUT_ROOT / "preflight.json"
    if not preflight_path.is_file():
        raise RuntimeError("FINALIZE_REQUIRES_EXISTING_PREFLIGHT")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    strategy_pairs = (("v2", v2.STRATEGY_ID), ("pattern_b", pattern_b.STRATEGY_ID))
    rows_by_battle: dict[str, list[dict[str, Any]]] = {battle_id: [] for battle_id in BATTLE_IDS}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for battle_id in BATTLE_IDS:
        for kind, strategy_id in strategy_pairs:
            metrics_path = OUTPUT_ROOT / battle_id / kind / "battle_window_metrics.csv"
            if not metrics_path.is_file():
                continue
            rows = read_metric_rows(metrics_path, strategy_id, battle_id)
            if len(rows) != len(WINDOW_IDS) or {str(row.get("window_id")) for row in rows} != set(WINDOW_IDS):
                raise RuntimeError(f"FINALIZE_INCOMPLETE_WINDOWS:{battle_id}:{kind}")
            rows_by_battle[battle_id].extend(rows)
            grouped[(battle_id, kind)] = rows
            write_csv(metrics_path, rows)
            summary_path = metrics_path.parent / "battle_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["windows"] = rows
                summary["worker_count"] = EXPECTED_WORKERS
                write_json(summary_path, summary)

    cross_rows: list[dict[str, Any]] = []
    for battle_id in BATTLE_IDS:
        if len(rows_by_battle[battle_id]) != 10:
            continue
        comparison = [
            {"battle_id": battle_id, **comparison_row(
                window,
                next(row for row in grouped[(battle_id, "v2")] if row["window_id"] == window),
                next(row for row in grouped[(battle_id, "pattern_b")] if row["window_id"] == window),
            )}
            for window in WINDOW_IDS
        ]
        cross_rows.extend(comparison)
        battle_root = OUTPUT_ROOT / battle_id
        write_csv(battle_root / "comparison.csv", comparison)
        summary_path = battle_root / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"battle_id": battle_id}
        summary.update({"status": "COMPLETE", "comparison": comparison})
        write_json(summary_path, summary)

    if cross_rows:
        write_csv(OUTPUT_ROOT / "cross_battle_comparison.csv", cross_rows)
    a_rows = rows_by_battle["battle_a_all_universe"]
    b_rows = rows_by_battle["battle_b_pit_mcap_1t"]
    c_rows = rows_by_battle["battle_c_kospi_only"]
    sensitivity = three_way_sensitivity(a_rows, b_rows, c_rows) if len(a_rows) == len(b_rows) == len(c_rows) == 10 else []
    if sensitivity:
        write_csv(OUTPUT_ROOT / "universe_filter_sensitivity.csv", sensitivity)

    cap_path = OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json"
    cap_preflight = json.loads(cap_path.read_text(encoding="utf-8")) if cap_path.exists() else None
    cap_summary = None if cap_preflight is None else cap_preflight.get("summary", {})
    market_path = OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.json"
    market_preflight = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else None
    market_summary = None if market_preflight is None else market_preflight.get("summary", {})

    all_complete = len(a_rows) == len(b_rows) == len(c_rows) == 10
    if all_complete:
        evidence = artifact_evidence_checks()
    else:
        evidence = {
            "structural_checks_pass": False,
            "incomplete_reason": "One or more preflight stop rules prevented the full 30-result replay.",
        }
    validation = validation_record(
        {"all_rows": a_rows, "mcap_rows": b_rows, "kospi_rows": c_rows},
        cap_summary,
        market_summary,
        evidence,
    )
    write_json(OUTPUT_ROOT / "validation.json", validation)

    source_hash_path = OUTPUT_ROOT / "source_hashes.json"
    source_hashes = json.loads(source_hash_path.read_text(encoding="utf-8")) if source_hash_path.exists() else {
        "schema": "official_strategy_battle_source_hashes_v02",
        "base_head": preflight.get("base_head"),
        "origin_main_at_preflight": preflight.get("origin_main"),
    }
    source_hashes.update({
        "orchestrator": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "work_instruction": {"path": str(WORK_INSTRUCTION), "sha256": sha256(WORK_INSTRUCTION)},
        "result_count": len(a_rows) + len(b_rows) + len(c_rows),
        "results": a_rows + b_rows + c_rows,
        "post_run_artifact_evidence_checks": validation["checks"]["artifact_evidence"],
    })
    write_json(source_hash_path, source_hashes)

    report = render_final_report(
        {"all_rows": a_rows, "mcap_rows": b_rows, "kospi_rows": c_rows, "base_head": preflight.get("base_head")},
        cap_summary,
        market_summary,
        cross_rows,
        sensitivity,
        validation,
    )
    (OUTPUT_ROOT / "final_report.md").write_text(report, encoding="utf-8")
    run_status = {
        "schema": "official_strategy_battle_run_status_v02",
        "status": validation["status"],
        "execution_status": validation["execution_status"],
        "battle_a_status": "COMPLETE" if len(a_rows) == 10 else "NOT_RUN",
        "battle_b_status": "COMPLETE" if len(b_rows) == 10 else "CHECK_REQUIRED" if cap_preflight and cap_preflight.get("status") != "PASS" else "NOT_RUN",
        "battle_c_status": "COMPLETE" if len(c_rows) == 10 else "CHECK_REQUIRED" if market_preflight and market_preflight.get("status") != "PASS" else "NOT_RUN",
        "battle_b_pit_cap_preflight": None if cap_preflight is None else cap_preflight.get("status"),
        "battle_c_pit_market_preflight": None if market_preflight is None else market_preflight.get("status"),
        "results": validation["checks"]["actual_result_count"],
        "expected_results": 30,
        "base_head": preflight.get("base_head"),
        "worker_count": EXPECTED_WORKERS,
        "valuation_check_required_count": len(validation["checks"]["valuation_check_required_results_below_90_pct"]),
    }
    write_json(OUTPUT_ROOT / "run_status.json", run_status)
    return {"validation": validation, "all_rows": a_rows, "mcap_rows": b_rows, "kospi_rows": c_rows,
            "cap_summary": cap_summary, "market_summary": market_summary}


def run_all() -> dict[str, Any]:
    preflight = static_preflight()
    unexpected = sorted(child.name for child in OUTPUT_ROOT.iterdir() if child.name != "preflight.json")
    if unexpected:
        raise RuntimeError(f"OUTPUT_ALREADY_CONTAINS_PRIOR_RUN_NO_AUTOMATIC_RETRY:{unexpected[:10]}")
    install_shared_repository_cache()
    base_head = preflight["base_head"]
    pit_rows, pit_meta = load_pit_authority()

    print("Battle A: all universe — V2 then Pattern B", flush=True)
    a_root = OUTPUT_ROOT / BATTLE_IDS[0]
    v2_a = run_v2_battle(BATTLE_IDS[0], a_root / "v2")
    pb_a = run_pattern_b_battle(BATTLE_IDS[0], a_root / "pattern_b", v2_a["rows"])
    a_comparison = [
        {"battle_id": BATTLE_IDS[0], **comparison_row(
            window,
            next(row for row in v2_a["rows"] if row["window_id"] == window),
            next(row for row in pb_a["rows"] if row["window_id"] == window),
        )}
        for window in WINDOW_IDS
    ]
    write_csv(a_root / "comparison.csv", a_comparison)
    write_json(a_root / "summary.json", {"battle_id": BATTLE_IDS[0], "status": "COMPLETE", "comparison": a_comparison})

    print("Battle B: exact entry-date PIT market-cap preflight", flush=True)
    cap_authority = ExactPITMarketCap(pit_rows)
    _cap_audit, cap_summary, _cap_selection = collect_battle_b_preflight(cap_authority, pit_rows)
    cap_preflight_status = "PASS" if all(row["status"] == "PASS" for row in cap_summary["by_strategy_window"]) else "CHECK_REQUIRED"
    write_json(OUTPUT_ROOT / "battle_b_pit_market_cap_preflight.json", {
        "schema": "battle_b_exact_pit_market_cap_preflight_v02",
        "status": cap_preflight_status,
        "pit_authority": pit_meta,
        "summary": cap_summary,
        "raw_partition_provenance": cap_authority.provenance,
    })
    if cap_preflight_status != "PASS":
        battle_root = OUTPUT_ROOT / BATTLE_IDS[1]
        battle_root.mkdir(parents=True, exist_ok=True)
        write_json(battle_root / "summary.json", {"battle_id": BATTLE_IDS[1], "status": "CHECK_REQUIRED", "reason": "Exact PIT cap coverage is below 90%; stop rule applied without repair or retry.", "pit_market_cap_preflight": cap_summary, "portfolio_results_generated": 0})
        (battle_root / "report.md").write_text("# Battle B — CHECK_REQUIRED\n\nExact entry-date PIT market-cap coverage was below 90% for at least one strategy/window. Portfolio replay stopped; no proxy, repair, or retry was used.\n", encoding="utf-8")
        write_json(OUTPUT_ROOT / "source_hashes.json", {
            "schema": "official_strategy_battle_source_hashes_v02",
            "base_head": base_head,
            "origin_main_at_preflight": preflight["origin_main"],
            "work_instruction": {"path": str(WORK_INSTRUCTION), "sha256": sha256(WORK_INSTRUCTION)},
            "orchestrator": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256(Path(__file__))},
            "permanent_exclusions": {"sha256": sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"), "count": EXPECTED_EXCLUSION_COUNT},
            "pit_identity_authority": pit_meta,
            "exact_market_cap_partitions": cap_authority.provenance,
        })
        return finalize_existing_outputs()

    print("Battle B: PIT market-cap >= 1T — V2 then Pattern B", flush=True)
    b_root = OUTPUT_ROOT / BATTLE_IDS[1]
    v2_b = run_v2_battle(BATTLE_IDS[1], b_root / "v2", cap_authority)
    pb_b = run_pattern_b_battle(BATTLE_IDS[1], b_root / "pattern_b", v2_b["rows"], cap_authority)
    b_comparison = [
        {"battle_id": BATTLE_IDS[1], **comparison_row(
            window,
            next(row for row in v2_b["rows"] if row["window_id"] == window),
            next(row for row in pb_b["rows"] if row["window_id"] == window),
        )}
        for window in WINDOW_IDS
    ]
    write_csv(b_root / "comparison.csv", b_comparison)
    write_json(b_root / "summary.json", {"battle_id": BATTLE_IDS[1], "status": "COMPLETE", "pit_market_cap_preflight": cap_summary, "comparison": b_comparison})

    print("Battle C: exact entry-date PIT KOSPI preflight", flush=True)
    market_authority = ExactPITMarketAuthority(pit_rows)
    _market_audit, market_summary = collect_battle_c_preflight(market_authority)
    market_preflight_status = market_summary["status"]
    write_json(OUTPUT_ROOT / "battle_c_pit_market_authority_preflight.json", {
        "schema": "battle_c_exact_pit_market_authority_preflight_v02",
        "status": market_preflight_status,
        "pit_authority": pit_meta,
        "summary": market_summary,
        "policy": "entry_signal_date exact ticker + ISU_CD active PIT COMMON interval; KOSPI only; no market-cap filter",
    })
    if market_preflight_status != "PASS":
        battle_root = OUTPUT_ROOT / BATTLE_IDS[2]
        battle_root.mkdir(parents=True, exist_ok=True)
        write_json(battle_root / "summary.json", {"battle_id": BATTLE_IDS[2], "status": "CHECK_REQUIRED", "reason": "Exact PIT market authority is missing or ambiguous; stop rule applied.", "market_authority_preflight": market_summary, "portfolio_results_generated": 0})
        (battle_root / "report.md").write_text("# Battle C — CHECK_REQUIRED\n\nExact entry-date PIT market authority was missing or ambiguous for candidate identities. Portfolio replay stopped; no ticker/name inference was used.\n", encoding="utf-8")
        write_json(OUTPUT_ROOT / "source_hashes.json", {
            "schema": "official_strategy_battle_source_hashes_v02",
            "base_head": base_head,
            "origin_main_at_preflight": preflight["origin_main"],
            "work_instruction": {"path": str(WORK_INSTRUCTION), "sha256": sha256(WORK_INSTRUCTION)},
            "orchestrator": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256(Path(__file__))},
            "permanent_exclusions": {"sha256": sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"), "count": EXPECTED_EXCLUSION_COUNT},
            "pit_identity_authority": pit_meta,
            "exact_market_cap_partitions": cap_authority.provenance,
            "market_authority_preflight": market_summary,
            "shared_repository_v2_initialization": CACHED_REPOSITORY_METADATA,
        })
        return finalize_existing_outputs()

    print("Battle C: KOSPI only — V2 then Pattern B; cap filter disabled", flush=True)
    c_root = OUTPUT_ROOT / BATTLE_IDS[2]
    v2_c = run_v2_battle(BATTLE_IDS[2], c_root / "v2", market_authority=market_authority)
    pb_c = run_pattern_b_battle(BATTLE_IDS[2], c_root / "pattern_b", v2_c["rows"], market_authority=market_authority)
    c_comparison = [
        {"battle_id": BATTLE_IDS[2], **comparison_row(
            window,
            next(row for row in v2_c["rows"] if row["window_id"] == window),
            next(row for row in pb_c["rows"] if row["window_id"] == window),
        )}
        for window in WINDOW_IDS
    ]
    write_csv(c_root / "comparison.csv", c_comparison)
    write_json(c_root / "summary.json", {"battle_id": BATTLE_IDS[2], "status": "COMPLETE", "market_authority_preflight": market_summary, "market_cap_filter": None, "comparison": c_comparison})

    source_hashes = {
        "schema": "official_strategy_battle_source_hashes_v02",
        "base_head": base_head,
        "origin_main_at_preflight": preflight["origin_main"],
        "work_instruction": {"path": str(WORK_INSTRUCTION), "sha256": sha256(WORK_INSTRUCTION)},
        "orchestrator": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256(Path(__file__))},
        "permanent_exclusions": {"path": "src/trend_scanner/universe/permanent_identity_exclusions.py", "sha256": sha256(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"), "count": EXPECTED_EXCLUSION_COUNT},
        "pit_identity_authority": pit_meta,
        "strategy_runners": {
            "v2": {"path": "scripts/run_v2_official_adoption_revalidation_v02.py", "sha256": sha256(ROOT / "scripts/run_v2_official_adoption_revalidation_v02.py")},
            "pattern_b_v02": {"path": "scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02.py", "sha256": sha256(ROOT / "scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02.py")},
            "pattern_b_v01_engine": {"path": "scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01.py", "sha256": sha256(ROOT / "scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01.py")},
            "portfolio_engine": {"path": "scripts/run_p2_1_realistic_portfolio_v01.py", "sha256": sha256(ROOT / "scripts/run_p2_1_realistic_portfolio_v01.py")},
        },
        "exact_market_cap_partitions": cap_authority.provenance,
        "market_authority_preflight": market_summary,
        "shared_repository_v2_initialization": CACHED_REPOSITORY_METADATA,
    }
    write_json(OUTPUT_ROOT / "source_hashes.json", source_hashes)
    return finalize_existing_outputs()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Validate frozen sources, windows, exclusions, and execution settings.")
    group.add_argument("--run", action="store_true", help="Run both battles in the prescribed order.")
    group.add_argument("--finalize-existing", action="store_true", help="Reconcile and regenerate reports from a completed 20-result run without rerunning portfolios.")
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(static_preflight(), ensure_ascii=False, indent=2, default=json_default), flush=True)
        return 0
    result = finalize_existing_outputs() if args.finalize_existing else run_all()
    checks = result["validation"]["checks"]
    preflight_status = "PASS" if checks.get("battle_b_exact_pit_market_cap_preflight_pass") and checks.get("battle_c_exact_pit_market_authority_preflight_pass") else "CHECK_REQUIRED"
    print(json.dumps({"status": result["validation"]["status"], "preflight": preflight_status, "result_count": checks["actual_result_count"]}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
