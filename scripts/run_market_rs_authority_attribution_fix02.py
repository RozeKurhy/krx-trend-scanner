"""Bounded offline authority adjudication for MARKET_RS_AUTHORITY_ATTRIBUTION_FIX02.

This script consumes the FIX01 unresolved census only.  It never calls a live
provider and does not rewrite canonical data.  Its purpose is to produce an
auditable pair-level decision before the expensive full parity run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import (
    KNOWN_ADJUSTED_SOURCE_GAP_DATES,
    KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES,
    MarketDataRepositoryV2,
    _project_analytic_sessions,
    _session_projection_evidence,
)
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR
from trend_scanner.data.repository_v2_session_authority import (
    ADJUSTED_ANALYTICALLY_NONUSABLE_DATES,
    SOURCE_CLOSURE_CHECKPOINT_SHA256,
)
from trend_scanner.relative_strength.repository_adapter import benchmark_anchor_start


ROOT = Path(__file__).resolve().parents[1]
FIX01 = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_rs_parity/v01_fix01"
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_rs_parity/v01_fix02"
UNRESOLVED = FIX01 / "legacy_vs_repository_input_census_20260814.json"
AS_OF = "2026-08-14"
CURRENT_AS_OF = "2026-08-21"


def write_json(name: str, payload: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _row(frame: pd.DataFrame | None, date: str, columns: tuple[str, ...]) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    if "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        selected = frame.loc[dates == date]
    else:
        dates = pd.DatetimeIndex(frame.index).strftime("%Y-%m-%d")
        selected = frame.loc[dates == date]
    if selected.empty:
        return None
    item = selected.iloc[-1]
    return {column: item.get(column) for column in columns if column in item.index}


def _placeholder_fields(raw: dict[str, Any] | None) -> dict[str, bool] | None:
    if raw is None:
        return None
    return {
        "open_zero": raw.get("open") == 0,
        "high_zero": raw.get("high") == 0,
        "low_zero": raw.get("low") == 0,
        "close_positive": raw.get("close", 0) > 0,
        "volume_zero": raw.get("volume") == 0,
        "trading_value_zero": raw.get("trading_value") == 0,
    }


def _is_placeholder(raw: dict[str, Any] | None) -> bool:
    fields = _placeholder_fields(raw)
    return bool(fields and all(fields.values()))


def _ratio(legacy: Any, repository: Any) -> tuple[float | None, float | None]:
    try:
        if legacy is None or repository is None or float(legacy) == 0.0 or float(repository) == 0.0:
            return None, None
        left = float(legacy) / float(repository)
        right = float(repository) / float(legacy)
        return left, right
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None


def _canonical_adjusted(ticker: str, date: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    path = ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet"
    if not path.exists():
        return None, None
    frame = pd.read_parquet(path)
    adjusted = _row(frame, date, ("date", "ticker", "open", "high", "low", "close"))
    meta_path = path.with_suffix(".meta.json")
    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else None
    return adjusted, metadata


def _load_raw_maps(pairs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    maps: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for market in sorted({str(pair["market"]) for pair in pairs}):
        for date in sorted({str(pair["date"]) for pair in pairs}):
            path = ROOT / "data/market/raw/krx_stocks/v01" / f"market={market}" / f"year={date[:4]}" / f"{date}.parquet"
            if not path.exists():
                continue
            frame = pd.read_parquet(path)
            frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
            maps[(market, date)] = {
                str(row["ticker"]): row.to_dict() for _, row in frame.iterrows()
            }
    return maps


def _authority_for_pair(pair: dict[str, Any], adjusted: dict[str, Any] | None, metadata: dict[str, Any] | None, raw: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    ticker, date = str(pair["ticker"]), str(pair["date"])
    base = {
        "ticker": ticker,
        "date": date,
        "legacy_value": pair.get("legacy_value"),
        "authoritative_value": pair.get("repository_value"),
        "source_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256,
    }
    if _is_placeholder(raw) and adjusted is not None:
        return "APPROVED_NONTRADING_EXCLUSION", {
            **base,
            "authority_source": "Repository V2 NON_TRADING_PLACEHOLDER_V01",
            "authority_artifact_path": "src/trend_scanner/data/repository_v2.py",
            "authority_record_identifier": f"NON_TRADING_PLACEHOLDER_V01[{ticker!r}, {date!r}]",
            "authority_reason": "exact raw OHLC/volume/trading_value placeholder predicate is true; the date is excluded from the analytic view without substitution",
            "raw_placeholder_predicate_fields": _placeholder_fields(raw),
        }
    if (ticker, date) in KNOWN_ADJUSTED_SOURCE_GAP_DATES and adjusted is None and raw is not None:
        return "APPROVED_ANALYTIC_SESSION_EXCLUSION", {
            **base,
            "authority_source": "Repository V2 known adjusted-source gap authority",
            "authority_artifact_path": "src/trend_scanner/data/repository_v2.py",
            "authority_record_identifier": f"KNOWN_ADJUSTED_SOURCE_GAP_DATES[{ticker!r}, {date!r}]",
            "authority_reason": KNOWN_ADJUSTED_SOURCE_GAP_DATES[(ticker, date)],
            "raw_placeholder_predicate_fields": _placeholder_fields(raw),
        }
    if adjusted is not None and metadata is not None and metadata.get("source_authority_id") == CURRENT_SOURCE_DESCRIPTOR.source_authority_id:
        return "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA", {
            **base,
            "authority_source": "canonical adjusted source descriptor",
            "authority_artifact_path": f"data/market/adjusted/stocks/{ticker}.meta.json",
            "authority_record_identifier": f"content_sha256={metadata.get('content_sha256')};date={date}",
            "authority_reason": "canonical adjusted row is present and bound to the current Closure V02 source descriptor; legacy row is the PyKRX composite cache and is retained only as baseline",
            "source_authority_id": metadata.get("source_authority_id"),
            "canonical_content_sha256": metadata.get("content_sha256"),
            "legacy_authority": "src/trend_scanner/data/source_contracts.py::LEGACY_CACHE_CLASSIFICATION",
            "ratio_diagnostic_only": True,
        }
    return "UNRESOLVED", {
        **base,
        "authority_source": "",
        "authority_artifact_path": "",
        "authority_record_identifier": "",
        "authority_reason": "no exact offline authority evidence",
        "raw_placeholder_predicate_fields": _placeholder_fields(raw),
    }


def _probe(repository: MarketDataRepositoryV2, adjusted_store: AdjustedPriceStore, end: str, canonical: pd.DataFrame) -> dict[str, Any]:
    start = benchmark_anchor_start(canonical, market_code="2001", as_of=end)
    adjusted = adjusted_store.load_daily_source("446840", start, end) if start else pd.DataFrame()
    raw = repository._load_raw("446840", pd.Timestamp(start), pd.Timestamp(end)) if start else pd.DataFrame()
    evidence = _session_projection_evidence(adjusted, raw)
    try:
        composed = repository.get_daily("446840", start, end) if start else None
        repository_error = None
    except Exception as exc:  # diagnostic artifact must preserve the exact error
        composed = None
        repository_error = {"error_type": type(exc).__name__, "error": str(exc)}
    adjusted_map = {str(index.date()): row.to_dict() for index, row in adjusted.iterrows()}
    raw_map = {str(index.date()): row.to_dict() for index, row in raw.iterrows()}
    offending = []
    for date in sorted(set(evidence["adjusted_only_dates"]) | set(evidence["rejected_raw_only_dates"]) | set(evidence["known_adjusted_gap_dates"])):
        adjusted_row = adjusted_map.get(date)
        raw_row = raw_map.get(date)
        offending.append({
            "date": date,
            "adjusted_source_OHLC": {key: adjusted_row.get(key) for key in ("open", "high", "low", "close")} if adjusted_row else None,
            "raw_OHLC": {key: raw_row.get(key) for key in ("open", "high", "low", "close")} if raw_row else None,
            "raw_volume": raw_row.get("volume") if raw_row else None,
            "raw_trading_value": raw_row.get("trading_value") if raw_row else None,
            "raw_market_cap": raw_row.get("market_cap") if raw_row else None,
            "raw_listed_shares": raw_row.get("listed_shares") if raw_row else None,
            "placeholder_predicate_fields": _placeholder_fields(raw_row),
            "pit_lifecycle_state": "OUTSIDE_IDENTITY_LIFECYCLE" if ("446840", date) in KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES else "IN_SCOPE_OR_NOT_PROVEN",
            "existing_session_authority": "KNOWN_ADJUSTED_SOURCE_GAP" if ("446840", date) in KNOWN_ADJUSTED_SOURCE_GAP_DATES else ("ADJUSTED_ANALYTICALLY_NONUSABLE" if ("446840", date) in ADJUSTED_ANALYTICALLY_NONUSABLE_DATES else None),
        })
    return {
        "ticker": "446840",
        "requested_start": start,
        "requested_end": end,
        "adjusted_physical_dates": evidence["adjusted_dates"],
        "raw_physical_dates": evidence["raw_dates"],
        "adjusted_only_dates": evidence["adjusted_only_dates"],
        "raw_only_dates": evidence["raw_only_dates"],
        "shared_dates": evidence["shared_dates"],
        "shared_placeholder_dates": evidence["confirmed_nontrading_shared_dates"],
        "raw_only_placeholder_dates": evidence["accepted_placeholder_dates"],
        "adjusted_analytic_invalid_dates": evidence["adjusted_analytic_invalid_dates"],
        "adjusted_source_nonusable_dates": evidence["adjusted_source_nonusable_dates"],
        "outside_identity_lifecycle_dates": evidence["outside_identity_lifecycle_dates"],
        "known_adjusted_gap_dates": evidence["known_adjusted_gap_dates"],
        "unexplained_adjusted_only_dates": evidence["unexplained_adjusted_only_dates"],
        "rejected_raw_only_dates": evidence["rejected_raw_only_dates"],
        "projected_adjusted_dates": sorted(pd.Timestamp(value).strftime("%Y-%m-%d") for value in evidence["projected_adjusted"].index),
        "projected_raw_dates": sorted(pd.Timestamp(value).strftime("%Y-%m-%d") for value in evidence["projected_raw"].index),
        "projected_date_set_exact_match": evidence["projected_date_set_exact_match"],
        "repository_composed_row_count": 0 if composed is None else len(composed),
        "repository_error": repository_error,
        "offending_rows": offending,
        "root_cause": "ADJUSTED_SOURCE_GAP" if evidence["rejected_raw_only_dates"] and set(evidence["rejected_raw_only_dates"]) <= set(KNOWN_ADJUSTED_SOURCE_GAP_DATES) else "UNRESOLVED",
    }


def main() -> int:
    census = json.loads(UNRESOLVED.read_text())
    pairs = [
        {**difference, "market": row["market"], "benchmark_code": row["benchmark_code"]}
        for row in census["rows"] if row["input_classification"] == "UNRESOLVED"
        for difference in row["material_differences"]
    ]
    raw_maps = _load_raw_maps(pairs)
    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    adjudicated = []
    for pair in pairs:
        adjusted, metadata = _canonical_adjusted(str(pair["ticker"]), str(pair["date"]))
        raw = raw_maps.get((str(pair["market"]), str(pair["date"])), {}).get(str(pair["ticker"]))
        classification, authority = _authority_for_pair(pair, adjusted, metadata, raw)
        ratio_left, ratio_right = _ratio(pair.get("legacy_value"), pair.get("repository_value"))
        adjudicated.append({
            **pair,
            "legacy_present": bool(pair.get("legacy_present")),
            "repository_present": bool(pair.get("repository_present")),
            "adjusted_source_present": adjusted is not None,
            "adjusted_source_OHLC": adjusted,
            "adjusted_canonical_present": adjusted is not None,
            "adjusted_canonical_OHLC": adjusted,
            "adjusted_metadata": metadata,
            "raw_present": raw is not None,
            "raw_OHLC": {key: raw.get(key) for key in ("open", "high", "low", "close")} if raw else None,
            "raw_volume": raw.get("volume") if raw else None,
            "raw_trading_value": raw.get("trading_value") if raw else None,
            "pit_in_lifecycle": None,
            "repository_session_classification": "NON_TRADING_PLACEHOLDER" if _is_placeholder(raw) else ("KNOWN_ADJUSTED_SOURCE_GAP" if (str(pair["ticker"]), str(pair["date"])) in KNOWN_ADJUSTED_SOURCE_GAP_DATES else "SHARED_ANALYTIC_SESSION" if adjusted is not None and raw is not None else "RAW_ONLY" if raw is not None else "MISSING_BOTH"),
            "ratio_legacy_over_repository": ratio_left,
            "ratio_repository_over_legacy": ratio_right,
            "final_classification": classification,
            "authority_evidence": authority,
        })
    write_json("unresolved_material_pairs_input.json", {"source": str(UNRESOLVED.relative_to(ROOT)), "pair_count": len(pairs), "pairs": pairs})
    write_json("material_authority_adjudication.json", {"pair_count": len(adjudicated), "pairs": adjudicated})
    counts = pd.Series([row["final_classification"] for row in adjudicated], dtype="string").value_counts().to_dict()
    write_json("material_authority_adjudication_summary.json", {"pair_count": len(adjudicated), "classification_counts": counts, "unadjudicated_material_pairs": int(counts.get("UNRESOLVED", 0)), "offline_only": True})
    write_json("legacy_adjusted_ratio_diagnostics.json", {"pair_count": len(adjudicated), "diagnostics": [{key: row.get(key) for key in ("ticker", "date", "horizon", "legacy_value", "repository_value", "ratio_legacy_over_repository", "ratio_repository_over_legacy", "final_classification", "authority_evidence")} for row in adjudicated]})

    canonical = IndexStore(ROOT / "data/market/index/v01").load_family(MARKET_INDEX_FAMILY, end=CURRENT_AS_OF, index_codes=("1001", "2001"))
    repository = MarketDataRepositoryV2(adjusted_store, KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01"))
    historical_probe = _probe(repository, adjusted_store, AS_OF, canonical)
    current_probe = _probe(repository, adjusted_store, CURRENT_AS_OF, canonical)
    write_json("ticker_446840_session_probe_historical.json", historical_probe)
    write_json("ticker_446840_session_probe_current.json", current_probe)
    root_cause = "ADJUSTED_SOURCE_GAP" if historical_probe["root_cause"] == current_probe["root_cause"] == "ADJUSTED_SOURCE_GAP" and historical_probe["projected_date_set_exact_match"] and current_probe["projected_date_set_exact_match"] else "UNRESOLVED"
    write_json("ticker_446840_root_cause.json", {"ticker": "446840", "historical_root_cause": historical_probe["root_cause"], "current_root_cause": current_probe["root_cause"], "root_cause": root_cause, "classification": "LEGITIMATE_MISSING_SESSION_AUTHORITY" if root_cause == "ADJUSTED_SOURCE_GAP" else "UNRESOLVED", "authority_pairs": sorted(KNOWN_ADJUSTED_SOURCE_GAP_DATES), "offline_only": True})
    write_json("authority_changes.json", {"authority_changes": [{"changed_file": "src/trend_scanner/data/repository_v2.py", "exact_ticker_date_pair": [ticker, date], "previous_classification": "UNCLASSIFIED_RAW_ONLY", "new_classification": "KNOWN_ADJUSTED_SOURCE_GAP", "reason": reason, "supporting_evidence": [f"data/market/adjusted/stocks/446840.meta.json", f"data/market/raw/krx_stocks/v01/market=KOSDAQ/year={date[:4]}/{date}.parquet"], "scope": "exact pair only"} for (ticker, date), reason in sorted(KNOWN_ADJUSTED_SOURCE_GAP_DATES.items())]})
    print(json.dumps({"pair_count": len(adjudicated), "classification_counts": counts, "446840_root_cause": root_cause, "historical_repository_error": historical_probe["repository_error"], "current_repository_error": current_probe["repository_error"]}, ensure_ascii=False, indent=2))
    return 0 if not counts.get("UNRESOLVED") and root_cause != "UNRESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
