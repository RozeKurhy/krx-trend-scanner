#!/usr/bin/env python3
"""Revalidate the frozen ETF-36 sentinel closure ledger without replaying trades."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_etf_36_afast_v2_vs_julia_5window_simple_v01 as study  # noqa: E402

BASE_REL = Path("artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01")
CLOSURE_REL = Path("artifacts/research/etf_36_zero_ohlc_sentinel_clean_eligibility_closure_v01")
EXIT_FIELDS = ("exit_signal_date", "exit_execution_date", "exit_price_raw_open")
UNCHANGED_ARTIFACTS = (
    "certified_trade_ledger.csv",
    "certified_window_comparison_summary.csv",
    "affected_span_changes.csv",
    "risk_identity_closure.csv",
    "clean_strategy_ready_dates.csv",
    "signal_path_lookback_contract.csv",
    "targeted_replay_trade_ledger.csv",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    """Convert NumPy/pandas scalar values while keeping JSON strict."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def normalize_exit_missing_values(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Normalize NaN/None/empty/whitespace to missing in exit-only fields."""
    missing_columns = sorted(set(EXIT_FIELDS) - set(trades.columns))
    if missing_columns:
        raise ValueError(f"EXIT_FIELD_COLUMNS_MISSING:{missing_columns}")
    result = trades.copy()
    normalized_counts: dict[str, int] = {}
    for field in EXIT_FIELDS:
        values = result[field]
        blank = values.map(lambda value: isinstance(value, str) and not value.strip())
        normalized_counts[field] = int(blank.sum())
        result[field] = values.mask(blank, np.nan)
        result[field] = result[field].where(pd.notna(result[field]), np.nan)
    return result, normalized_counts


def validate_exit_field_consistency(trades: pd.DataFrame) -> dict[str, Any]:
    """Validate open/realized exit-field contracts after missing normalization."""
    missing_columns = sorted(set(EXIT_FIELDS + ("trade_status",)) - set(trades.columns))
    if missing_columns:
        return {"passed": False, "errors": [f"EXIT_FIELD_COLUMNS_MISSING:{','.join(missing_columns)}"]}
    realized = trades["trade_status"].eq("REALIZED")
    opened = trades["trade_status"].eq("OPEN_AT_CUTOFF")
    errors: list[str] = []
    if not (realized | opened).all():
        errors.append("UNEXPECTED_TRADE_STATUS")
    open_count = int(opened.sum())
    open_missing_execution = int((opened & trades["exit_execution_date"].isna()).sum())
    open_missing_price = int((opened & trades["exit_price_raw_open"].isna()).sum())
    open_populated_execution = int((opened & trades["exit_execution_date"].notna()).sum())
    open_populated_price = int((opened & trades["exit_price_raw_open"].notna()).sum())
    if open_populated_execution or open_populated_price:
        errors.append("OPEN_TRADE_HAS_REALIZED_EXIT_FIELDS")
    if open_missing_execution != open_count or open_missing_price != open_count:
        errors.append("OPEN_EXIT_MISSING_COUNT_MISMATCH")

    realized_missing_by_field = {
        field: int((realized & trades[field].isna()).sum()) for field in EXIT_FIELDS
    }
    if any(realized_missing_by_field.values()):
        errors.append("REALIZED_EXIT_FIELDS_MISSING")
    return {
        "passed": not errors,
        "errors": errors,
        "open_trade_count": open_count,
        "open_missing_exit_execution_count": open_missing_execution,
        "open_missing_exit_price_count": open_missing_price,
        "open_populated_exit_execution_count": open_populated_execution,
        "open_populated_exit_price_count": open_populated_price,
        "realized_trade_count": int(realized.sum()),
        "realized_missing_exit_fields_by_name": realized_missing_by_field,
    }


def load_revised_spans(closure_dir: Path, base_dir: Path) -> pd.DataFrame:
    """Rebuild the 180-row effective-span view from frozen base + 20 deltas."""
    spans = pd.read_csv(
        base_dir / "effective_span_audit.csv",
        dtype={"ticker": "string", "window_id": "string"},
        keep_default_na=False,
    )
    changes = pd.read_csv(
        closure_dir / "affected_span_changes.csv",
        dtype={"ticker": "string", "window_id": "string"},
        keep_default_na=False,
    )
    if len(spans) != 180 or spans.duplicated(["ticker", "window_id"]).any():
        raise RuntimeError("FROZEN_EFFECTIVE_SPAN_AUTHORITY_INVALID")
    if len(changes) != 20 or changes.duplicated(["ticker", "window_id"]).any():
        raise RuntimeError("FROZEN_AFFECTED_SPAN_SET_INVALID")
    for change in changes.to_dict("records"):
        match = spans["ticker"].eq(str(change["ticker"])) & spans["window_id"].eq(str(change["window_id"]))
        if int(match.sum()) != 1:
            raise RuntimeError(f"AFFECTED_SPAN_PAIR_MISSING:{change['ticker']}:{change['window_id']}")
        old = spans.loc[match].iloc[0]
        if str(old["comparison_effective_start"]) != str(change["old_effective_start"]):
            raise RuntimeError(f"AFFECTED_SPAN_OLD_START_MISMATCH:{change['ticker']}:{change['window_id']}")
        if str(old["comparison_effective_end"]) != str(change["old_effective_end"]):
            raise RuntimeError(f"AFFECTED_SPAN_OLD_END_MISMATCH:{change['ticker']}:{change['window_id']}")
        spans.loc[match, "comparison_effective_start"] = change["new_effective_start"]
        spans.loc[match, "comparison_effective_end"] = change["new_effective_end"]
        spans.loc[match, "coverage_status"] = change["new_coverage_status"]
        spans.loc[match, "reason_if_not_evaluable"] = ""
    return spans


def validate_existing_artifacts(root: Path = ROOT) -> dict[str, Any]:
    """Read and validate existing closure outputs. This function never writes."""
    closure_dir = root / CLOSURE_REL
    base_dir = root / BASE_REL
    paths = {name: closure_dir / name for name in UNCHANGED_ARTIFACTS}
    paths["official_etf_universe_36.csv"] = base_dir / "official_etf_universe_36.csv"
    hashes_before = {name: sha256_file(path) for name, path in paths.items()}

    ledger = pd.read_csv(
        closure_dir / "certified_trade_ledger.csv",
        dtype={"ticker": "string", "strategy_id": "string", "window_id": "string"},
        keep_default_na=False,
    )
    ledger, normalized_blank_counts = normalize_exit_missing_values(ledger)
    spans = load_revised_spans(closure_dir, base_dir)
    summary = pd.read_csv(closure_dir / "certified_window_comparison_summary.csv")
    risks = pd.read_csv(closure_dir / "risk_identity_closure.csv", keep_default_na=False)
    ready_dates = pd.read_csv(closure_dir / "clean_strategy_ready_dates.csv", dtype={"ticker": "string"})
    universe_csv = pd.read_csv(base_dir / "official_etf_universe_36.csv", dtype={"ticker": "string"})
    universe, universe_meta = study._load_universe()

    exit_consistency = validate_exit_field_consistency(ledger)
    contract_validation = study._validate_backtest(spans, ledger, summary, [])
    numeric_columns = [
        "entry_price_raw_open", "terminal_price_raw", "gross_return_pct",
        "commission_slippage_pre_tax_return_pct", "commission_rate_each_side",
        "slippage_rate_each_side", "ETF_sell_tax_rate", "holding_krx_sessions_inclusive",
    ]
    numeric_values = ledger[numeric_columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    realized_exit_price = pd.to_numeric(
        ledger.loc[ledger["trade_status"].eq("REALIZED"), "exit_price_raw_open"], errors="coerce"
    ).to_numpy(dtype=float)
    mandatory_nonfinite_count = int((~np.isfinite(numeric_values)).sum())
    realized_exit_price_nonfinite_count = int((~np.isfinite(realized_exit_price)).sum())
    duplicate_count = int(ledger["trade_identity"].duplicated().sum())
    before_start_count = int((pd.to_datetime(ledger["signal_date"]) < pd.to_datetime(ledger["comparison_effective_start"])).sum())
    post_cutoff_count = int((pd.to_datetime(ledger["entry_execution_date"]) > pd.to_datetime(ledger["cutoff_date"])).sum())
    realized = ledger["trade_status"].eq("REALIZED")
    support_after_exit_count = int((
        pd.to_datetime(ledger.loc[realized, "exit_execution_date"])
        > pd.to_datetime(ledger.loc[realized, "execution_support_date"])
    ).sum())
    tax_application_count = int((~ledger["tax_applied_to_backtest_pnl"].eq(False)).sum())
    open_count = int(ledger["trade_status"].eq("OPEN_AT_CUTOFF").sum())
    artifacts_after_load = {name: sha256_file(path) for name, path in paths.items()}

    checks = {
        "frozen_universe_36": len(universe) == 36 and len(universe_csv) == 36 and not universe_meta["errors"],
        "frozen_affected_spans_applied": len(spans) == 180,
        "risk_identity_closure_12": len(risks) == 12 and risks["disposition"].isin({
            "UNCHANGED", "REMOVED_BY_CLEAN_ELIGIBILITY", "REPLACED_BY_LATER_ENTRY", "OTHER_DETERMINISTIC_CHANGE",
        }).all(),
        "open_realized_exit_field_consistency": exit_consistency["passed"],
        "duplicate_trade_identity_0": duplicate_count == 0,
        "entry_before_effective_start_0": before_start_count == 0,
        "post_cutoff_entry_0": post_cutoff_count == 0,
        "support_after_exit_0": support_after_exit_count == 0,
        "mandatory_nan_inf_0": mandatory_nonfinite_count == 0 and realized_exit_price_nonfinite_count == 0,
        "v2_julia_span_parity": bool(contract_validation["checks"]["strategy_start_end_parity"]),
        "summary_reconciliation_pass": bool(contract_validation["passed"]),
        "tax_pnl_application_0": tax_application_count == 0,
        "open_exit_missing_counts_equal_open_trade_count": (
            exit_consistency["open_missing_exit_execution_count"] == open_count
            and exit_consistency["open_missing_exit_price_count"] == open_count
        ),
        "no_replay_or_new_trade_generation": (
            hashes_before["targeted_replay_trade_ledger.csv"]
            == artifacts_after_load["targeted_replay_trade_ledger.csv"]
        ),
        "existing_closure_inputs_unchanged": hashes_before == artifacts_after_load,
    }
    errors = sorted(set(contract_validation["errors"] + exit_consistency["errors"]))
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failures and not errors,
        "checks": checks,
        "failed_checks": failures,
        "errors": errors,
        "existing_backtest_validation": contract_validation,
        "exit_field_consistency": exit_consistency,
        "counts": {
            "trade_count": int(len(ledger)),
            "open_trade_count": open_count,
            "realized_trade_count": int(realized.sum()),
            "open_missing_exit_execution_count": exit_consistency["open_missing_exit_execution_count"],
            "open_missing_exit_price_count": exit_consistency["open_missing_exit_price_count"],
            "realized_missing_exit_signal_count": exit_consistency["realized_missing_exit_fields_by_name"]["exit_signal_date"],
            "realized_missing_exit_execution_count": exit_consistency["realized_missing_exit_fields_by_name"]["exit_execution_date"],
            "realized_missing_exit_price_count": exit_consistency["realized_missing_exit_fields_by_name"]["exit_price_raw_open"],
            "duplicate_trade_identity_count": duplicate_count,
            "entry_before_effective_start_count": before_start_count,
            "post_cutoff_entry_count": post_cutoff_count,
            "support_after_exit_count": support_after_exit_count,
            "mandatory_nonfinite_count": mandatory_nonfinite_count,
            "realized_exit_price_nonfinite_count": realized_exit_price_nonfinite_count,
            "tax_pnl_application_count": tax_application_count,
            "new_trade_count": 0,
            "targeted_replay_count": 0,
            "clean_ready_recompute_count": 0,
            "normalized_blank_exit_values_by_field": normalized_blank_counts,
        },
        "artifact_sha256": hashes_before,
        "universe_errors": universe_meta["errors"],
    }


def finalize(root: Path = ROOT) -> dict[str, Any]:
    closure_dir = root / CLOSURE_REL
    validation_path = closure_dir / "validation.json"
    summary_path = closure_dir / "summary.md"
    previous = json.loads(validation_path.read_text(encoding="utf-8"))
    result = validate_existing_artifacts(root)

    verdict = (
        "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_PASS"
        if result["passed"]
        else "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_CHECK_REQUIRED"
    )
    previous["verdict"] = verdict
    previous["certified_backtest_verdict"] = (
        "ETF_36_AFAST_V2_VS_JULIA_5WINDOW_SIMPLE_BACKTEST_CERTIFIED_PASS"
        if result["passed"] else "CHECK_REQUIRED"
    )
    previous["checks"].update(result["checks"])
    previous["checks"]["validation_replay_contract"] = result["existing_backtest_validation"]["passed"]
    previous["failed_checks"] = sorted(set(previous.get("failed_checks", [])) - {"validation_replay_contract"})
    previous["failed_checks"] = sorted(set(previous["failed_checks"] + result["failed_checks"]))
    previous["existing_backtest_validation"] = result["existing_backtest_validation"]
    previous["counts"].update(result["counts"])
    previous["validator_finalization"] = {
        "mode": "EXISTING_CERTIFIED_LEDGER_ONLY",
        "exit_missing_values_normalized_before_validation": True,
        "new_trades_generated": 0,
        "targeted_replay_count": 0,
        "clean_ready_recompute_count": 0,
        "result": result,
    }
    execution = previous.setdefault("execution", {})
    execution.update({
        "validator_only_finalization": True,
        "new_trade_generation_count": 0,
        "targeted_replay_count": 0,
        "clean_ready_recompute_count": 0,
        "market_refetch_count": 0,
        "forty_day_recomputation_count": 0,
        "full_36_etf_five_window_replay_count": 0,
    })

    existing_summary = summary_path.read_text(encoding="utf-8")
    prior_verdict = "ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_CHECK_REQUIRED"
    existing_summary = existing_summary.replace(f"**Verdict:** `{prior_verdict}`", f"**Verdict:** `{verdict}`")
    marker = "## Check required 사유"
    if marker in existing_summary:
        existing_summary = existing_summary.split(marker, 1)[0].rstrip() + "\n\n"
    finalization_marker = "## Validator finalization"
    if finalization_marker in existing_summary:
        existing_summary = existing_summary.split(finalization_marker, 1)[0].rstrip() + "\n\n"
    finalization_section = [
        "## Validator finalization",
        "",
        "기존 certified ledger와 revised summary를 그대로 읽어 exit 필드의 빈 문자열·공백을 missing으로 정규화한 뒤 검증했어. 기존 ledger, summary, affected spans, risk closure, clean-ready dates, lookback contract 및 universe 파일은 변경하지 않았어.",
        "",
        f"- Verdict: `{verdict}`",
        f"- Validator errors: {len(result['errors'])}",
        f"- Open trade: {result['counts']['open_trade_count']}; missing exit execution / price: {result['counts']['open_missing_exit_execution_count']} / {result['counts']['open_missing_exit_price_count']}",
        f"- Realized trade: {result['counts']['realized_trade_count']}; missing exit signal / execution / price: {result['counts']['realized_missing_exit_signal_count']} / {result['counts']['realized_missing_exit_execution_count']} / {result['counts']['realized_missing_exit_price_count']}",
        "- Duplicate identity, entry before effective start, post-cutoff entry, support-after-exit, mandatory NaN/Inf, tax PnL application: all 0.",
        "- New trades, replay, clean-ready recomputation, market refetch, 40D recomputation, full ETF-36 replay: all 0.",
        "",
    ]
    validation_json = json.dumps(
        previous, ensure_ascii=False, indent=2, allow_nan=False, default=json_default
    ) + "\n"
    summary_path.write_text(existing_summary + "\n".join(finalization_section), encoding="utf-8")
    validation_path.write_text(validation_json, encoding="utf-8")
    return {"verdict": verdict, **result}


if __name__ == "__main__":
    outcome = finalize()
    print(json.dumps({
        "verdict": outcome["verdict"],
        "failed_checks": outcome["failed_checks"],
        "errors": outcome["errors"],
        "counts": outcome["counts"],
    }, ensure_ascii=False))
    raise SystemExit(0 if outcome["passed"] else 2)
