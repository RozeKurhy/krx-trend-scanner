#!/usr/bin/env python3
"""Final deterministic adjusted-OHLC spot validation against direct Naver data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    NaverDirectAdjustedPriceDataProvider,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError


ROOT = Path(__file__).resolve().parents[1]
TARGET_AS_OF = "2026-09-11"
FIXED_SEED = 20260914
TICKER_SAMPLE_COUNT = 30
DATES_PER_TICKER = 20
OHLC_FIELDS = tuple(ADJUSTED_OHLC_COLUMNS)
DEFAULT_PIT_PATH = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
DEFAULT_ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
DEFAULT_ARTIFACT_DIR = ROOT / "artifacts/data/final_market_price_validation/v01"
PRODUCTION_FINGERPRINT_ROOTS = {
    "adjusted": ROOT / "data/market/adjusted/stocks",
    "raw": ROOT / "data/market/raw/krx_stocks/v01",
    "index": ROOT / "data/market/index/v01",
}


class FinalMarketPriceValidationError(MarketDataError):
    """Fail-closed validation error with a stable diagnostic code."""

    def __init__(self, error_code: str, message: str = "") -> None:
        self.error_code = str(error_code)
        suffix = f": {message}" if message else ""
        super().__init__(f"{self.error_code}{suffix}")


@dataclass(frozen=True)
class EligibilityResult:
    eligible_tickers: tuple[str, ...]
    fewer_than_20: tuple[dict[str, Any], ...]
    store_errors: tuple[dict[str, str], ...]


def _date_text(value: str | date | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _date_index(frame: pd.DataFrame, target_as_of: str) -> list[str]:
    if not isinstance(frame, pd.DataFrame):
        raise FinalMarketPriceValidationError("BLOCKED_PRODUCTION_FRAME")
    dates = pd.to_datetime(frame.index, errors="coerce")
    if dates.isna().any():
        raise FinalMarketPriceValidationError("BLOCKED_PRODUCTION_DATE_INDEX")
    return sorted({_date_text(value) for value in dates if _date_text(value) <= target_as_of})


def derive_eligible_tickers(
    active_common_tickers: Sequence[str],
    store: Any,
    *,
    target_as_of: str = TARGET_AS_OF,
    minimum_dates: int = DATES_PER_TICKER,
) -> EligibilityResult:
    """Use the existing production store metadata to derive sampling eligibility."""

    eligible: list[str] = []
    fewer_than_20: list[dict[str, Any]] = []
    store_errors: list[dict[str, str]] = []
    for ticker in sorted({str(value).zfill(6) for value in active_common_tickers}):
        try:
            metadata = store.load_metadata(ticker)
            row_count = int(metadata.get("row_count", -1))
            actual_date_max = str(metadata.get("actual_date_max", ""))
            # The current production boundary is 2026-09-11.  When a future row
            # exists, use the actual filtered date index instead of trusting the
            # full-store row count for this target.
            if actual_date_max > target_as_of:
                row_count = len(_date_index(store.load_daily_source(ticker, end=target_as_of), target_as_of))
            if row_count >= minimum_dates:
                eligible.append(ticker)
            else:
                fewer_than_20.append({"ticker": ticker, "date_count": max(row_count, 0)})
        except Exception as exc:  # metadata/store defects are not silently eligible
            store_errors.append({"ticker": ticker, "error_type": type(exc).__name__})
    return EligibilityResult(tuple(eligible), tuple(fewer_than_20), tuple(store_errors))


def build_sample_manifest(
    eligible_tickers: Sequence[str],
    date_loader: Callable[[str], Sequence[str]],
    *,
    seed: int = FIXED_SEED,
    ticker_count: int = TICKER_SAMPLE_COUNT,
    dates_per_ticker: int = DATES_PER_TICKER,
) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    """Sample tickers and dates with one reproducible RNG stream.

    ``date_loader`` is lazy so the production run only loads actual OHLC/date
    indexes for selected tickers.  A selected ticker that unexpectedly cannot
    provide 20 dates is deterministically replaced from the remaining sorted
    eligible population.
    """

    eligible = sorted({str(value).zfill(6) for value in eligible_tickers})
    if len(eligible) < ticker_count:
        raise FinalMarketPriceValidationError("BLOCKED_INSUFFICIENT_ELIGIBLE_TICKERS")
    rng = random.Random(seed)
    initial = rng.sample(eligible, ticker_count)
    used = set(initial)
    selected_manifest: dict[str, list[str]] = {}
    replacements: list[dict[str, str]] = []
    for original_ticker in initial:
        ticker = original_ticker
        while True:
            try:
                dates = sorted({_date_text(value) for value in date_loader(ticker)})
            except Exception:
                dates = []
            if len(dates) >= dates_per_ticker:
                selected_manifest[ticker] = sorted(rng.sample(dates, dates_per_ticker))
                break
            remaining = [candidate for candidate in eligible if candidate not in used]
            if not remaining:
                raise FinalMarketPriceValidationError("BLOCKED_SAMPLE_REPLACEMENT_EXHAUSTED")
            replacement = remaining[rng.randrange(len(remaining))]
            used.add(replacement)
            replacements.append({"from": ticker, "to": replacement})
            ticker = replacement
    if len(selected_manifest) != ticker_count or any(len(days) != dates_per_ticker for days in selected_manifest.values()):
        raise FinalMarketPriceValidationError("BLOCKED_SAMPLE_MANIFEST_SHAPE")
    return selected_manifest, replacements


def _numeric(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def compare_observation(
    ticker: str,
    day: str,
    production_row: Mapping[str, Any],
    naver_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare one exact ticker/date observation without tolerance."""

    result: dict[str, Any] = {"ticker": ticker, "date": day}
    for field in OHLC_FIELDS:
        result[f"production_{field}"] = None if production_row.get(field) is None else float(production_row[field])
        result[f"naver_{field}"] = None if naver_row is None or naver_row.get(field) is None else float(naver_row[field])
    if naver_row is None:
        result["field_mismatch_count"] = len(OHLC_FIELDS)
        result["status"] = "NAVER_DATE_MISSING"
        return result
    mismatches = 0
    for field in OHLC_FIELDS:
        if _numeric(production_row.get(field)) != _numeric(naver_row.get(field)):
            mismatches += 1
    result["field_mismatch_count"] = mismatches
    result["status"] = "MATCH" if mismatches == 0 else "MISMATCH"
    return result


def fingerprint_tree(root: Path) -> dict[str, Any]:
    """Create a lightweight no-write fingerprint from file paths, sizes and mtimes."""

    root = Path(root)
    entries: list[str] = []
    total_bytes = 0
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            stat = path.stat()
            total_bytes += stat.st_size
            entries.append(f"{path.relative_to(root)}|{stat.st_size}|{stat.st_mtime_ns}")
    digest = hashlib.sha256(("\n".join(entries) + "\n").encode("utf-8")).hexdigest()
    return {
        "path": str(root.resolve()),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "fingerprint_sha256": digest,
    }


def _frame_by_date(frame: pd.DataFrame, target_as_of: str) -> dict[str, Mapping[str, Any]]:
    if tuple(frame.columns) != OHLC_FIELDS:
        raise FinalMarketPriceValidationError("BLOCKED_PRODUCTION_OHLC_SCHEMA")
    result: dict[str, Mapping[str, Any]] = {}
    for day in _date_index(frame, target_as_of):
        row = frame.loc[pd.Timestamp(day)]
        if isinstance(row, pd.DataFrame):
            raise FinalMarketPriceValidationError("BLOCKED_PRODUCTION_DUPLICATE_DATE")
        result[day] = row.to_dict()
    return result


def _naver_by_date(frame: pd.DataFrame) -> dict[str, Mapping[str, Any]]:
    if tuple(frame.columns) != OHLC_FIELDS:
        raise FinalMarketPriceValidationError("BLOCKED_NAVER_OHLC_SCHEMA")
    result: dict[str, Mapping[str, Any]] = {}
    for value, row in frame.iterrows():
        result[_date_text(value)] = row.to_dict()
    return result


def _relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_validation(
    *,
    active_common_tickers: Sequence[str],
    store: Any,
    provider: Any,
    adjusted_root: Path,
    artifact_dir: Path,
    target_as_of: str = TARGET_AS_OF,
    seed: int = FIXED_SEED,
    fingerprint_roots: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Run the bounded validation; this function never calls a store write API."""

    roots = dict(fingerprint_roots or {"adjusted": adjusted_root, "raw": ROOT / "data/market/raw/krx_stocks/v01", "index": ROOT / "data/market/index/v01"})
    before = {name: fingerprint_tree(path) for name, path in roots.items()}
    eligibility = derive_eligible_tickers(active_common_tickers, store, target_as_of=target_as_of)
    production_frames: dict[str, pd.DataFrame] = {}

    def load_dates(ticker: str) -> Sequence[str]:
        frame = store.load_daily_source(ticker, end=target_as_of)
        production_frames[ticker] = frame
        return _date_index(frame, target_as_of)

    sample_manifest, replacements = build_sample_manifest(eligibility.eligible_tickers, load_dates, seed=seed)
    sample_manifest_payload = {
        "seed": seed,
        "target_as_of": target_as_of,
        "active_common_count": len(active_common_tickers),
        "eligible_ticker_count": len(eligibility.eligible_tickers),
        "excluded_fewer_than_20": list(eligibility.fewer_than_20),
        "store_error_count": len(eligibility.store_errors),
        "sampling_replacements": replacements,
        "selected": [{"ticker": ticker, "dates": dates} for ticker, dates in sample_manifest.items()],
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    sample_path = artifact_dir / "sample_manifest.json"
    _write_json(sample_path, sample_manifest_payload)

    comparison_rows: list[dict[str, Any]] = []
    for ticker, dates in sample_manifest.items():
        production_by_date = _frame_by_date(production_frames[ticker], target_as_of)
        try:
            naver_frame = provider.load_daily(ticker, min(dates), max(dates))
            naver_by_date = _naver_by_date(naver_frame)
        except Exception:
            naver_by_date = None
        for day in dates:
            production_row = production_by_date[day]
            if naver_by_date is None:
                row = {"ticker": ticker, "date": day}
                for field in OHLC_FIELDS:
                    row[f"production_{field}"] = float(production_row[field])
                    row[f"naver_{field}"] = None
                row["field_mismatch_count"] = 0
                row["status"] = "SOURCE_FETCH_FAILURE"
            else:
                row = compare_observation(ticker, day, production_row, naver_by_date.get(day))
            row["confirmation_status"] = "NOT_REQUIRED"
            comparison_rows.append(row)

    # Only affected observations receive the one bounded confirmation fetch.
    for row in comparison_rows:
        if row["status"] not in {"MISMATCH", "NAVER_DATE_MISSING"}:
            continue
        ticker, day = row["ticker"], row["date"]
        production_row = _frame_by_date(production_frames[ticker], target_as_of)[day]
        try:
            confirmation = provider.load_daily(ticker, day, day)
            confirmation_map = _naver_by_date(confirmation)
            confirmed = compare_observation(ticker, day, production_row, confirmation_map.get(day))
        except Exception:
            row["confirmation_status"] = "SOURCE_FETCH_FAILURE"
            continue
        row["confirmation_status"] = "REFETCH_MATCH" if confirmed["status"] == "MATCH" else confirmed["status"]
        if confirmed["status"] == "MATCH":
            for field in OHLC_FIELDS:
                row[f"naver_{field}"] = confirmed[f"naver_{field}"]
            row["field_mismatch_count"] = 0
            row["status"] = "MATCH"

    comparison_columns = [
        "ticker", "date",
        *[f"production_{field}" for field in OHLC_FIELDS],
        *[f"naver_{field}" for field in OHLC_FIELDS],
        "field_mismatch_count", "status", "confirmation_status",
    ]
    comparison_path = artifact_dir / "row_level_comparison.csv"
    pd.DataFrame(comparison_rows, columns=comparison_columns).to_csv(comparison_path, index=False)

    after = {name: fingerprint_tree(path) for name, path in roots.items()}
    production_unchanged = {name: before[name] == after[name] for name in roots}
    matched_observations = sum(row["status"] == "MATCH" for row in comparison_rows)
    mismatch_rows = [row for row in comparison_rows if row["status"] == "MISMATCH"]
    missing_rows = [row for row in comparison_rows if row["status"] == "NAVER_DATE_MISSING"]
    failure_rows = [row for row in comparison_rows if row["status"] == "SOURCE_FETCH_FAILURE"]
    mismatch_list: list[dict[str, Any]] = []
    for row in mismatch_rows:
        for field in OHLC_FIELDS:
            if _numeric(row[f"production_{field}"]) != _numeric(row[f"naver_{field}"]):
                mismatch_list.append({
                    "ticker": row["ticker"],
                    "date": row["date"],
                    "field": field,
                    "production_value": row[f"production_{field}"],
                    "naver_value": row[f"naver_{field}"],
                    "mismatch_type": "EXACT_NUMERIC_VALUE_DIFFERENCE",
                })
    audit = provider.call_audit() if callable(getattr(provider, "call_audit", None)) else {}
    scalar_count = sum(len(OHLC_FIELDS) for row in comparison_rows if row["status"] != "SOURCE_FETCH_FAILURE")
    mismatched_scalar_fields = sum(int(row["field_mismatch_count"]) for row in comparison_rows if row["status"] != "SOURCE_FETCH_FAILURE")
    if eligibility.store_errors:
        verdict = "BLOCKED"
    elif failure_rows:
        verdict = "BLOCKED"
    elif mismatch_rows or missing_rows:
        verdict = "FAIL"
    elif not all(production_unchanged.values()):
        verdict = "BLOCKED"
    elif len(sample_manifest) != TICKER_SAMPLE_COUNT or len(comparison_rows) != TICKER_SAMPLE_COUNT * DATES_PER_TICKER:
        verdict = "BLOCKED"
    else:
        verdict = "PASS"
    summary = {
        "seed": seed,
        "target_as_of": target_as_of,
        "active_common_count": len(active_common_tickers),
        "eligible_ticker_count": len(eligibility.eligible_tickers),
        "excluded_fewer_than_20": list(eligibility.fewer_than_20),
        "selected_ticker_count": len(sample_manifest),
        "selected_ticker_list": list(sample_manifest),
        "sampled_observation_count": len(comparison_rows),
        "scalar_ohlc_comparison_count": scalar_count,
        "direct_naver_fetch_count": int(audit.get("logical_fetch_count", 0)),
        "naver_http_request_count": int(audit.get("naver_http_call_count", 0)),
        "naver_request_summary": dict(audit),
        "exact_matched_observations": matched_observations,
        "mismatched_observations": len(mismatch_rows),
        "mismatched_scalar_fields": mismatched_scalar_fields,
        "missing_naver_dates": len(missing_rows),
        "source_fetch_failures": len(failure_rows),
        "source_fetch_failure_tickers": sorted({row["ticker"] for row in failure_rows}),
        "mismatch_list": mismatch_list,
        "production_adjusted_store_unchanged": production_unchanged.get("adjusted", False),
        "production_raw_store_unchanged": production_unchanged.get("raw", False),
        "production_index_store_unchanged": production_unchanged.get("index", False),
        "production_fingerprints_before": before,
        "production_fingerprints_after": after,
        "artifact_paths": {
            "sample_manifest": _relpath(sample_path),
            "row_level_comparison": _relpath(comparison_path),
            "final_summary": _relpath(artifact_dir / "final_summary.json"),
        },
        "final_verdict": verdict,
    }
    _write_json(artifact_dir / "final_summary.json", summary)
    return summary


def _load_active_common(target_as_of: str, pit_path: Path) -> list[str]:
    # This is the exact helper used by the rolling refresh population wiring.
    try:
        from scripts.refresh_market_data_v01 import load_common_adjusted_tickers_from_pit
    except ModuleNotFoundError as exc:
        if exc.name != "scripts":
            raise
        # Direct execution places ``scripts/`` on sys.path, while pytest imports
        # it as the repository namespace package.  Both paths use the same helper.
        from refresh_market_data_v01 import load_common_adjusted_tickers_from_pit

    return load_common_adjusted_tickers_from_pit(pit_path, identity_as_of=target_as_of)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Final 30x20 adjusted OHLC spot validation against Naver")
    parser.add_argument("--target-as-of", default=TARGET_AS_OF)
    parser.add_argument("--pit-path", type=Path, default=DEFAULT_PIT_PATH)
    parser.add_argument("--adjusted-root", type=Path, default=DEFAULT_ADJUSTED_ROOT)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--execute-live", action="store_true", help="perform fresh direct Naver requests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute_live:
        print(json.dumps({"status": "LIVE_VALIDATION_REQUIRES_EXECUTE_LIVE"}, ensure_ascii=False))
        return 2
    try:
        active = _load_active_common(args.target_as_of, args.pit_path)
        store = AdjustedPriceStore(args.adjusted_root)
        provider = NaverDirectAdjustedPriceDataProvider()
        summary = run_validation(
            active_common_tickers=active,
            store=store,
            provider=provider,
            adjusted_root=args.adjusted_root,
            artifact_dir=args.artifact_dir,
            target_as_of=args.target_as_of,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, default=str))
        return 0 if summary["final_verdict"] == "PASS" else 1
    except Exception as exc:  # do not expose secrets or raw network payloads
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
