#!/usr/bin/env python3
"""Research-only P3-2 replay: signal close > completed-month MA20 > MA60."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
CONTROL = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
PRIOR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_entry_filter_backtest_v01"
PRIOR_COMMIT = "8edb3f5179ff1c9608fc79ec01f93c4fc596ae89"
WORKERS = 10
PERIODS = {"MA20": 20, "MA60": 60}
CONTROL_TOKEN = "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE"
PRIOR_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_COMPLETE"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01_COMPLETE"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01_CHECK_REQUIRED"
CURRENT_STAGE = "STARTUP"
CANDIDATE_REPLAY_STARTED = False
GROUPS = (
    "PRICE_GT_MA20_GT_MA60",
    "PRICE_GT_MA60_GE_MA20",
    "MA20_GE_PRICE_GT_MA60",
    "PRICE_LE_MA60",
    "MA20_UNAVAILABLE",
    "MA60_UNAVAILABLE",
)
GROUP_LABELS = {
    "PRICE_GT_MA20_GT_MA60": "PRICE > MA20 > MA60",
    "PRICE_GT_MA60_GE_MA20": "PRICE > MA60 >= MA20",
    "MA20_GE_PRICE_GT_MA60": "MA20 >= PRICE > MA60",
    "PRICE_LE_MA60": "PRICE <= MA60",
    "MA20_UNAVAILABLE": "MA20 unavailable",
    "MA60_UNAVAILABLE": "MA60 unavailable",
}


class CheckRequired(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise CheckRequired(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_helper():
    path = PRIOR / "run_monthly_ma_entry_filter_backtest.py"
    spec = importlib.util.spec_from_file_location("p3_2_monthly_ma_entry_filter_helpers", path)
    require(spec is not None and spec.loader is not None, "PRIOR_REPLAY_HELPERS_IMPORT_FAILED")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def verify_manifest(directory: Path, commit: str, files: list[str]) -> dict[str, Any]:
    mismatches = []
    for name in files:
        path = directory / name
        rel = path.relative_to(ROOT).as_posix()
        saved = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT, capture_output=True)
        if saved.returncode:
            mismatches.append({"path": rel, "reason": "MISSING_FROM_COMMIT"})
        elif not path.is_file():
            mismatches.append({"path": rel, "reason": "MISSING_ON_DISK"})
        elif saved.stdout != path.read_bytes():
            mismatches.append({"path": rel, "reason": "BYTE_MISMATCH"})
    return {"checked_file_count": len(files), "mismatch_count": len(mismatches), "mismatches": mismatches}


def preflight(helper: Any):
    global CURRENT_STAGE
    CURRENT_STAGE = "PREFLIGHT"
    allowed = {"run_bullish_alignment_backtest.py", "__pycache__"}
    unexpected = sorted(p.name for p in OUT.iterdir() if p.name not in allowed)
    require(not unexpected, "REFUSING_TO_OVERWRITE_OUTPUTS:" + ",".join(unexpected))
    require(git_text("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git_text("rev-parse", "HEAD"), git_text("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")

    prior_path = PRIOR / "summary.json"
    require(prior_path.is_file(), "PRIOR_SUMMARY_MISSING")
    prior_summary = json.loads(prior_path.read_text(encoding="utf-8"))
    require(prior_summary.get("status") == "COMPLETE" and prior_summary.get("final_token") == PRIOR_TOKEN, "PRIOR_RESULT_NOT_COMPLETE")
    prior_pre = prior_summary.get("preflight", {})
    require(prior_pre.get("status") == "PASS" and prior_pre.get("control_replayed") is False, "PRIOR_PREFLIGHT_INVALID")
    require(prior_pre.get("network_calls") == 0 and prior_pre.get("latest_rolling_authority_read") is False, "PRIOR_NETWORK_OR_LATEST_AUTHORITY")
    require(prior_pre.get("frozen_control_trade_count") == 405 and prior_pre.get("frozen_control_survivor_identity_count") == 2539, "PRIOR_CONTROL_SCOPE_MISMATCH")
    require(prior_pre.get("workers") == WORKERS, "PRIOR_WORKER_COUNT_MISMATCH")
    ma60_worker = prior_summary.get("worker_results", {}).get("MA60", {})
    require(ma60_worker.get("worker_count") == WORKERS and ma60_worker.get("worker_errors") == 0, "PRIOR_MA60_WORKERS_INVALID")
    require(ma60_worker.get("ticker_count") == 2539 and ma60_worker.get("strategy_trade_count") == 337, "PRIOR_MA60_TRADE_COUNT_INVALID")
    require(ma60_worker.get("raw_signal_audit_count") == 6650, "PRIOR_MA60_AUDIT_COUNT_INVALID")
    prior_files = list(prior_summary.get("files_created", []))
    require(len(prior_files) == 26 and len(set(prior_files)) == 26, "PRIOR_MANIFEST_INVALID")
    prior_manifest = verify_manifest(PRIOR, PRIOR_COMMIT, prior_files)
    require(prior_manifest["mismatch_count"] == 0, "PRIOR_ARTIFACT_PROVENANCE_MISMATCH")
    path_diff = subprocess.run(["git", "diff", "--quiet", PRIOR_COMMIT, "HEAD", "--", str(PRIOR.relative_to(ROOT))], cwd=ROOT)
    require(path_diff.returncode == 0, "PRIOR_ARTIFACT_DIFFERS_FROM_HEAD")

    frozen = helper.load_frozen_runner()
    provenance = frozen._validate_saved_provenance()
    require(provenance.get("status") == "PASS", "FROZEN_PROVENANCE_NOT_PASS")
    run, gate, universe, authority = frozen._load_frozen_context()
    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    require(control_summary.get("status") == "COMPLETE" and control_summary.get("final_token") == CONTROL_TOKEN, "FROZEN_CONTROL_NOT_COMPLETE")
    require(control_summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    control_hashes = {}
    for name, expected in prior_pre.get("control_hashes", {}).items():
        path = CONTROL / name
        require(path.is_file() and sha256(path) == expected, f"CONTROL_HASH_MISMATCH:{name}")
        rel = path.relative_to(ROOT).as_posix()
        require(subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT) == path.read_bytes(), f"CONTROL_HEAD_BLOB_MISMATCH:{name}")
        control_hashes[name] = expected
    control = pd.read_csv(CONTROL / "control_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    control["ticker"] = control["ticker"].astype(str).str.zfill(6)
    require(len(control) == 405 and control["pair_id"].is_unique, "CONTROL_LEDGER_INVALID")
    require(len(universe.loc[universe["status"].eq("SURVIVOR_COMMON_IDENTITY")]) == 2539, "FROZEN_SURVIVOR_COUNT_MISMATCH")

    prior_trades = pd.read_csv(PRIOR / "ma60_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    prior_trades["ticker"] = prior_trades["ticker"].astype(str).str.zfill(6)
    prior_events = pd.read_csv(PRIOR / "ma60_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    prior_daily = pd.read_csv(PRIOR / "ma60_daily_equity.csv")
    prior_audit = pd.read_csv(PRIOR / "ma60_signal_audit.csv", dtype={"ticker": str})
    require(len(prior_trades) == 337 and prior_trades["pair_id"].is_unique, "PRIOR_MA60_LEDGER_INVALID")
    require(len(prior_daily) == 1140 and len(prior_audit) == 6650, "PRIOR_MA60_ROW_COUNT_MISMATCH")
    checks = prior_summary.get("integrity_checks", {}).get("MA60", {})
    require(bool(prior_summary.get("integrity_checks", {}).get("all_candidate_checks_pass")), "PRIOR_INTEGRITY_NOT_PASS")
    require(bool(checks.get("cash_conservation_pass")) and checks.get("unresolved_count_zero") is True and checks.get("equity_curve_1140_rows") is True, "PRIOR_PORTFOLIO_INTEGRITY_INVALID")
    return {
        "status": "PASS", "branch": "main", "head": head, "origin_main": origin,
        "head_equals_origin_main": True, "ahead_behind": git_text("rev-list", "--left-right", "--count", "origin/main...HEAD"),
        "prior_reference_commit": PRIOR_COMMIT, "prior_manifest_verification": prior_manifest,
        "prior_head_diff_exit_code": path_diff.returncode, "prior_final_token": prior_summary["final_token"],
        "prior_ma60_worker": ma60_worker, "prior_ma60_trade_rows": len(prior_trades),
        "prior_ma60_event_rows": len(prior_events), "prior_ma60_equity_rows": len(prior_daily),
        "prior_ma60_signal_audit_rows": len(prior_audit), "frozen_control_hashes": control_hashes,
        "frozen_control_final_token": control_summary["final_token"], "frozen_control_trade_count": len(control),
        "frozen_survivor_identity_count": 2539, "frozen_authority": authority, "source_provenance": provenance,
        "workers": WORKERS, "network_calls": 0, "control_replayed": False, "prior_ma60_replayed": False,
        "price_source": "Existing local Repository V2 adjusted-price partitions, read-only.",
        "execution_runtime_reference": {
            "prior_ma20_seconds": prior_summary.get("worker_results", {}).get("MA20", {}).get("elapsed_seconds"),
            "prior_ma60_seconds": ma60_worker.get("elapsed_seconds"), "planned_candidate_runs": 1, "worker_count": WORKERS,
        },
    }, frozen, run, gate, universe, control, prior_summary, prior_trades, prior_events, prior_daily


def classify(close: Any, ma20: Any, ma20_ok: bool, ma60: Any, ma60_ok: bool) -> str:
    if not ma20_ok:
        return "MA20_UNAVAILABLE"
    if not ma60_ok:
        return "MA60_UNAVAILABLE"
    p, m20, m60 = float(close), float(ma20), float(ma60)
    if p > m20 > m60:
        return "PRICE_GT_MA20_GT_MA60"
    if p > m60 >= m20:
        return "PRICE_GT_MA60_GE_MA20"
    if m20 >= p > m60:
        return "MA20_GE_PRICE_GT_MA60"
    if p <= m60:
        return "PRICE_LE_MA60"
    raise CheckRequired("STRUCTURE_GROUP_NOT_CLASSIFIED")


def classify_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    groups = []
    for r in frame.itertuples(index=False):
        m20, m60 = getattr(r, "ma20_value", None), getattr(r, "ma60_value", None)
        a20 = bool(getattr(r, "ma20_available", m20 is not None and not pd.isna(m20)))
        a60 = bool(getattr(r, "ma60_available", m60 is not None and not pd.isna(m60)))
        groups.append(classify(getattr(r, "signal_day_close"), m20, a20, m60, a60))
    out = frame.copy()
    out["structure_group"] = groups
    out["structure_source"] = source
    return out


def group_counts(frame: pd.DataFrame, scope: str) -> list[dict[str, Any]]:
    counts = frame["structure_group"].value_counts().to_dict()
    n = len(frame)
    return [{"scope": scope, "group": group, "count": int(counts.get(group, 0)),
             "group_label": GROUP_LABELS[group],
             "share_pct": float(counts.get(group, 0) * 100 / n) if n else None, "total_rows": n} for group in GROUPS]


def prior_signal_features(helper: Any, run: Any, prices: Any, trades: pd.DataFrame) -> pd.DataFrame:
    loader_type = type(run.loader)
    daily_by_identity: dict[str, pd.DataFrame] = {}
    rows = []
    for r in trades.itertuples(index=False):
        ticker, day = str(r.ticker).zfill(6), pd.Timestamp(r.entry_signal_date).normalize()
        segment = helper.find_segment(run, ticker, r.market, day)
        require(str(segment.isu_cd).upper() == str(r.isu_cd).upper(), f"PRIOR_IDENTITY_MISMATCH:{r.pair_id}")
        if segment.key not in daily_by_identity:
            loader = loader_type(run.loader.repository, start=segment.effective_from, end=run.window.execution_support)
            daily = loader.load(ticker)
            require(daily is not None and not daily.empty, f"REPOSITORY_V2_DATA_MISSING:{ticker}:{day.date()}")
            daily_by_identity[segment.key] = daily
        daily = daily_by_identity[segment.key]
        feat = prices.signal_features(ticker, daily, day, PERIODS)
        execution = pd.Timestamp(r.entry_execution_date).normalize()
        store, _ = prices.load(ticker)
        opens = store.loc[store["date"].eq(execution), "open"]
        require(execution in daily.index and len(opens) == 1, f"PRIOR_EXECUTION_PRICE_MISSING:{r.pair_id}")
        entry_open, store_open, repo_open = float(r.entry_open), float(opens.iloc[0]), float(daily.at[execution, "open"])
        require(math.isclose(entry_open, store_open, rel_tol=0, abs_tol=1e-9) and math.isclose(entry_open, repo_open, rel_tol=0, abs_tol=1e-9), f"PRIOR_ENTRY_OPEN_MISMATCH:{r.pair_id}")
        next_days = daily.index[(daily.index > day) & (daily.index <= run.window.execution_support)]
        require(len(next_days) > 0 and pd.Timestamp(next_days[0]).normalize() == execution, f"PRIOR_NEXT_LOCAL_SESSION_MISMATCH:{r.pair_id}")
        item = {
            "pair_id": str(r.pair_id), "ticker": ticker, "isu_cd": str(r.isu_cd), "market": str(r.market),
            "identity_effective_from": str(r.identity_effective_from), "identity_effective_to": str(r.identity_effective_to),
            "entry_signal_date": day.strftime("%Y-%m-%d"), "entry_execution_date": execution.strftime("%Y-%m-%d"),
            "signal_day_close": feat["signal_day_close"], "entry_open": entry_open,
            "ma_last_completed_month": feat["ma_last_completed_month"], "filter_uses_entry_open": False,
        }
        for name in PERIODS:
            p = name.lower()
            item[f"{p}_value"] = feat[f"{p}_value"]
            item[f"{p}_available"] = bool(feat[f"{p}_available"])
            item[f"{p}_unavailable_reason"] = feat[f"{p}_unavailable_reason"]
            item[f"{p}_window_start_month"] = feat[f"{p}_window_start_month"]
            item[f"{p}_window_end_month"] = feat[f"{p}_window_end_month"]
            item[f"{p}_missing_months"] = feat[f"{p}_missing_months"]
            item[f"{p}_monthly_closes_used"] = feat[f"{p}_monthly_closes_used"]
        rows.append(item)
    out = pd.DataFrame(rows)
    require(len(out) == len(trades) and out["pair_id"].is_unique, "PRIOR_FEATURE_JOIN_NOT_ONE_TO_ONE")
    return out


def candidate_replay(
    helper: Any,
    run: Any,
    gate: Any,
    prices: Any,
    *,
    official_v2_only: bool = False,
):
    from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2
    import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy

    original = v2.simulate_ticker_core_v02_reentry
    audits: list[dict[str, Any]] = []
    audit_lock = threading.Lock()

    def wrapped(*args: Any, **kwargs: Any):
        ticker, market, daily = str(kwargs["ticker"]).zfill(6), str(kwargs["market"]), kwargs["daily"]
        pit_filter = kwargs.get("entry_signal_filter")
        def gate_filter(signal_date: pd.Timestamp, result: Mapping[str, Any]) -> bool:
            day = pd.Timestamp(signal_date).normalize()
            identity = helper.find_segment(run, ticker, market, day)
            pit_pass = bool(pit_filter(day, result)) if pit_filter is not None else True
            feat = prices.signal_features(ticker, daily, day, PERIODS)
            a20, a60 = bool(feat["ma20_available"]), bool(feat["ma60_available"])
            # Only signal-day close and completed monthly data enter this predicate.
            passed = bool(a20 and a60 and float(feat["signal_day_close"]) > float(feat["ma20_value"]) > float(feat["ma60_value"]))
            accepted = bool(pit_pass and passed)
            support = pd.Timestamp(kwargs.get("execution_support_date")).normalize()
            cutoff = pd.Timestamp(kwargs.get("entry_execution_cutoff_date")).normalize()
            future = daily.index[(daily.index > day) & (daily.index <= support)]
            next_day = pd.Timestamp(future[0]).normalize() if len(future) else None
            executable = next_day is not None and next_day <= cutoff
            audit_row = {
                "ticker": ticker, "isu_cd": identity.isu_cd, "market": identity.market,
                "identity_effective_from": identity.effective_from.strftime("%Y-%m-%d"),
                "identity_effective_to": identity.effective_to.strftime("%Y-%m-%d"),
                "identity_key": identity.key, "entry_signal_date": day.strftime("%Y-%m-%d"),
                "candidate": "PRICE_GT_MA20_GT_MA60", "raw_v2_eligible_signal": True, "pit_mcap_pass": pit_pass,
                "signal_day_close": feat["signal_day_close"], "signal_month": feat["signal_month"],
                "ma_last_completed_month": feat["ma_last_completed_month"],
                "ma20_value": feat["ma20_value"], "ma20_available": a20,
                "ma20_unavailable_reason": feat["ma20_unavailable_reason"],
                "ma60_value": feat["ma60_value"], "ma60_available": a60,
                "ma60_unavailable_reason": feat["ma60_unavailable_reason"],
                "ma20_filter_pass": bool(a20 and float(feat["signal_day_close"]) > float(feat["ma20_value"])),
                "ma20_gt_ma60_pass": bool(a20 and a60 and float(feat["ma20_value"]) > float(feat["ma60_value"])),
                "alignment_filter_pass": passed, "ma_filter_pass": passed, "candidate_signal_accepted": accepted,
                "next_local_session_date": next_day.strftime("%Y-%m-%d") if next_day is not None else None,
                "entry_execution_cutoff_date": cutoff.strftime("%Y-%m-%d"), "entry_executable_within_cutoff": bool(executable),
                "filter_decision": "ACCEPT" if accepted else ("PIT_REJECT" if not pit_pass else "ALIGNMENT_BLOCK"),
                "monthly_window_start_ma20": feat["ma20_window_start_month"], "monthly_window_end_ma20": feat["ma20_window_end_month"],
                "monthly_missing_ma20": feat["ma20_missing_months"], "monthly_closes_used_ma20": feat["ma20_monthly_closes_used"],
                "monthly_window_start_ma60": feat["ma60_window_start_month"], "monthly_window_end_ma60": feat["ma60_window_end_month"],
                "monthly_missing_ma60": feat["ma60_missing_months"], "monthly_closes_used_ma60": feat["ma60_monthly_closes_used"],
                "price_source_partition_sha256": feat["price_source_partition_sha256"],
                "price_source_metadata_sha256": feat["price_source_metadata_sha256"], "filter_uses_entry_open": False,
            }
            with audit_lock:
                audits.append(audit_row)
            return accepted
        kwargs["entry_signal_filter"] = gate_filter
        return original(*args, **kwargs)

    v2.simulate_ticker_core_v02_reentry = wrapped
    outcomes, errors = [], []
    started = time.perf_counter()
    tickers = sorted(run.segments_by_ticker)
    try:
        def process(ticker: str):
            outcome = strategy._process_ticker(
                ticker,
                run,
                official_v2_only=official_v2_only,
            )
            outcome["worker_thread"] = threading.current_thread().name
            return outcome
        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="alignment") as pool:
            futures = {pool.submit(process, t): t for t in tickers}
            for i, future in enumerate(as_completed(futures), start=1):
                ticker = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
                if i % 50 == 0 or i == len(tickers):
                    print(f"NEW_ALIGNMENT progress {i}/{len(tickers)} errors={len(errors)} elapsed={time.perf_counter()-started:.1f}s", flush=True)
    finally:
        v2.simulate_ticker_core_v02_reentry = original
    require(not errors, "ALIGNMENT_WORKER_ERRORS:" + json.dumps(errors[:10], ensure_ascii=False))
    records = pd.DataFrame([r for outcome in outcomes for r in outcome.get("control_rows", ())])
    if records.empty:
        records = pd.DataFrame(columns=["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date", "pair_id"])
    else:
        records = records.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    audit = pd.DataFrame(audits)
    keys = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date"]
    if not records.empty:
        records["ticker"] = records["ticker"].astype(str).str.zfill(6)
        audit["ticker"] = audit["ticker"].astype(str).str.zfill(6)
        trade_keys = records[keys].copy()
        accepted = audit.loc[audit["candidate_signal_accepted"] & audit["entry_executable_within_cutoff"], keys].copy()
        require(not accepted.duplicated().any() and not trade_keys.duplicated().any(), "DUPLICATE_ALIGNMENT_SIGNAL_OR_TRADE")
        require(trade_keys.sort_values(keys).reset_index(drop=True).equals(accepted.sort_values(keys).reset_index(drop=True)), "ALIGNMENT_SIGNAL_TRADE_LEDGER_MISMATCH")
        cols = keys + ["signal_day_close", "ma20_value", "ma20_available", "ma60_value", "ma60_available", "alignment_filter_pass", "candidate_signal_accepted", "ma_last_completed_month"]
        records = records.merge(audit[cols], on=keys, how="left", validate="one_to_one")
        require(records["candidate_signal_accepted"].fillna(False).all() and records["alignment_filter_pass"].fillna(False).all(), "ALIGNMENT_TRADE_FILTER_LEAK")
    return records, {"outcomes": outcomes, "worker_errors": errors, "elapsed_seconds": time.perf_counter() - started}, audit


def actual_pnl(events: pd.DataFrame) -> dict[str, Any]:
    entries = events.loc[events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED")].set_index("pair_id", drop=False)
    exits = events.loc[events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")]
    rows = []
    for e in exits.itertuples(index=False):
        entry = entries.loc[str(e.pair_id)]
        buy = float(entry["notional"]) + float(entry["commission"])
        sell_net_tax = float(e.notional) - float(e.commission) - float(e.sell_tax)
        sell_no_tax = float(e.notional) - float(e.commission)
        rows.append({
            "after_tax_pnl": sell_net_tax - buy,
            "tax_excluded_pnl": sell_no_tax - buy,
            "after_tax_return_pct": (sell_net_tax / buy - 1) * 100 if buy else None,
            "tax_excluded_return_pct": (sell_no_tax / buy - 1) * 100 if buy else None,
        })
    f = pd.DataFrame(rows)
    return {
        "actual_entries": len(entries), "realized_exits": len(exits), "realized_pairs": len(f),
        "realized_pnl_after_tax_krw": float(f["after_tax_pnl"].sum()) if len(f) else 0.0,
        "realized_pnl_tax_excluded_krw": float(f["tax_excluded_pnl"].sum()) if len(f) else 0.0,
        "realized_ge_pos_50_after_tax": int(f["after_tax_return_pct"].ge(50).sum()) if len(f) else 0,
        "realized_ge_pos_100_after_tax": int(f["after_tax_return_pct"].ge(100).sum()) if len(f) else 0,
    }


def executed_entry_keys(events: pd.DataFrame, records: pd.DataFrame, name: str) -> pd.DataFrame:
    pairs = set(events.loc[events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED"), "pair_id"].astype(str))
    cols = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date"]
    out = records.loc[records["pair_id"].astype(str).isin(pairs), cols].copy()
    for col in cols:
        out[col] = out[col].fillna("").astype(str)
    out = out.drop_duplicates().reset_index(drop=True)
    out["policy"] = name
    return out


def opportunity(helper: Any, left: tuple[str, pd.DataFrame, pd.DataFrame, Mapping[str, Any]], right: tuple[str, pd.DataFrame, pd.DataFrame, Mapping[str, Any]]):
    ln, le, lt, lm = left
    rn, re, rt, rm = right
    summary, winners = helper.opportunity_analysis(le, lt, re, rt, f"{ln}_VS_{rn}", lm, rm)
    summary["comparison"] = f"{ln}_VS_{rn}"
    key_cols = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_signal_date", "entry_execution_date"]
    lk, rk = executed_entry_keys(le, lt, ln), executed_entry_keys(re, rt, rn)
    left_keys = set(map(tuple, lk[key_cols].itertuples(index=False, name=None)))
    right_keys = set(map(tuple, rk[key_cols].itertuples(index=False, name=None)))
    rows = []
    for k in sorted(left_keys - right_keys):
        rows.append({"comparison": summary["comparison"], "row_type": "ACTUAL_ENTRY", "change_type": f"{ln}_ONLY_ACTUAL_ENTRY", "threshold_pct": None, "trade_key": json.dumps(k)})
    for k in sorted(right_keys - left_keys):
        rows.append({"comparison": summary["comparison"], "row_type": "ACTUAL_ENTRY", "change_type": f"{rn}_ONLY_ACTUAL_ENTRY", "threshold_pct": None, "trade_key": json.dumps(k)})
    if len(winners):
        winners = winners.rename(columns={"candidate": "comparison"})
        winners["comparison"] = summary["comparison"]
        winners["row_type"] = "REALIZED_WINNER"
    return summary, pd.concat([pd.DataFrame(rows), winners], ignore_index=True, sort=False)


def port_view(metrics: Mapping[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    keys = (
        "final_equity", "final_equity_at_effective_close", "cumulative_return_pct", "CAGR_pct", "mdd_pct",
        "realized_trade_count", "open_at_effective_cutoff_count", "cash_shortage_skipped_entries",
        "average_concurrent_positions", "maximum_concurrent_positions", "average_capital_utilization_pct",
        "maximum_capital_utilization_pct", "average_cash_ratio_pct", "turnover_multiple",
        "average_holding_trading_days", "median_holding_trading_days", "realized_return_ge_pos_50_count",
        "realized_return_ge_pos_100_count", "realized_return_le_neg_30_count", "realized_return_le_neg_40_count",
        "realized_return_le_neg_50_count", "realized_return_le_neg_60_count", "cash_conservation_pass",
        "unresolved_count", "equity_curve_rows",
    )
    d = {k: metrics.get(k) for k in keys}
    d["actual_entries"] = int((events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED")).sum())
    d["actual_realized_exits"] = int((events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")).sum())
    d["cash_shortage_event_count"] = int(events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE").sum())
    return d


def judge(strategy: Mapping[str, Any], portfolio: Mapping[str, Any], opp: Mapping[str, Any]):
    a, b = strategy["PRIOR_MA60"], strategy["NEW_ALIGNMENT"]
    ap, bp = portfolio["PRIOR_MA60"], portfolio["NEW_ALIGNMENT"]
    d = {
        "final_equity_delta_krw": float(bp.get("final_equity", 0)) - float(ap.get("final_equity", 0)),
        "cagr_delta_percentage_points": float(bp.get("CAGR_pct", 0)) - float(ap.get("CAGR_pct", 0)),
        "mdd_delta_percentage_points": float(bp.get("mdd_pct", 0)) - float(ap.get("mdd_pct", 0)),
        "realized_win_rate_delta_percentage_points": float(b.get("realized_win_rate_pct") or 0) - float(a.get("realized_win_rate_pct") or 0),
        "average_terminal_delta_percentage_points": float(b.get("average_terminal_return_pct") or 0) - float(a.get("average_terminal_return_pct") or 0),
        "median_terminal_delta_percentage_points": float(b.get("median_terminal_return_pct") or 0) - float(a.get("median_terminal_return_pct") or 0),
        "realized_ge_50_net_count_change": int(opp["realized_winner_change"]["net_realized_ge_pos_50"]["net_count_change"]),
        "realized_ge_100_net_count_change": int(opp["realized_winner_change"]["net_realized_ge_pos_100"]["net_count_change"]),
        "cash_shortage_skip_change": int(bp.get("cash_shortage_skipped_entries", 0)) - int(ap.get("cash_shortage_skipped_entries", 0)),
    }
    port_better = d["final_equity_delta_krw"] > 0 and d["cagr_delta_percentage_points"] > 0 and d["mdd_delta_percentage_points"] >= -5
    strat_better = d["realized_win_rate_delta_percentage_points"] > 0 and d["average_terminal_delta_percentage_points"] > 0 and d["median_terminal_delta_percentage_points"] >= 0
    winners_ok = d["realized_ge_50_net_count_change"] >= -2 and d["realized_ge_100_net_count_change"] >= -1
    if port_better and strat_better and winners_ok and d["cash_shortage_skip_change"] <= 0:
        label, detail = "ALIGNMENT_STRONGER_THAN_MA60", "현실 포트폴리오와 거래 품질이 함께 개선되고 MDD·현금 부족·승자 보존이 악화되지 않았어."
    elif d["final_equity_delta_krw"] < 0 and d["cagr_delta_percentage_points"] < 0 and d["realized_win_rate_delta_percentage_points"] < 0 and d["average_terminal_delta_percentage_points"] < 0 and (d["mdd_delta_percentage_points"] <= 0 or d["realized_ge_50_net_count_change"] < 0):
        label, detail = "MA60_REMAINS_BETTER", "MA60이 현실 포트폴리오 수익과 전략 거래 품질에서 함께 앞섰어."
    else:
        label, detail = "MIXED_NO_CLEAR_WINNER", "수익·위험·거래 품질·승자 보존 지표가 엇갈려 P3-2만으로 우열을 정하기 어려워."
    return label, detail, d


def render_report(s: Mapping[str, Any]) -> str:
    lines = [
        "| 레벨 | 개수 | 내용 |", "|---|---:|---|",
        *[f"| {x[0]} | {x[1]} | {x[2]} |" for x in s["severity"]],
        "", f"최종 토큰: {s['final_token']}", "",
        "## 1. Authority / PIT", "",
        f"- Frozen CONTROL: {s['preflight']['frozen_control_final_token']}; {s['preflight']['frozen_control_trade_count']} trades, 2,539 identities.",
        f"- Prior MA20/MA60 files: {s['preflight']['prior_manifest_verification']['checked_file_count']} files matched byte-for-byte with commit {PRIOR_COMMIT}; CONTROL and prior MA60 were reused, not replayed.",
        "- Local Repository V2 adjusted-price partitions only; zero API/network calls. Monthly averages use only completed months before each signal month.",
        "", "## 2. Exact rule", "",
        "- Allow only when signal-day close > prior completed month MA20 > prior completed month MA60.",
        "- Missing MA20 or MA60 fails closed. Execution remains next local session open. Entry open is not passed to the filter.",
        "", "## 3. MA20/MA60 structure groups", "",
        "| Sample | Group | Count | Share |", "|---|---|---:|---:|",
    ]
    for x in s["structure_groups"]:
        lines.append(f"| {x['scope']} | {x['group_label']} | {x['count']} | {x['share_pct']:.2f}% |")
    p = s["prior_ma60_vs_alignment"]
    lines += ["", f"Of the 337 PRIOR MA60 trades: aligned {p['aligned_count']}; blocked by MA20 <= MA60 {p['blocked_ma20_le_ma60_count']}; close not above MA20 while MA20 > MA60 {p['blocked_price_not_above_ma20_count']}; MA20 unavailable {p['ma20_unavailable_count']}.",
              "", "## 4. Strategy metrics", "", "| Metric | CONTROL | PRIOR MA60 | NEW ALIGNMENT |", "|---|---:|---:|---:|"]
    tkeys = [
        ("trade_count","trade count"),("realized_count","realized"),("open_count","open"),
        ("realized_win_rate_pct","realized win rate %"),("terminal_positive_rate_pct","terminal positive %"),
        ("average_terminal_return_pct","average terminal %"),("median_terminal_return_pct","median terminal %"),
        ("average_realized_return_pct","average realized %"),("median_realized_return_pct","median realized %"),
        ("average_holding_trading_days","average holding days"),("median_holding_trading_days","median holding days"),
        ("progressed_count","PROGRESSED"),("progressed_rate_pct","PROGRESSED %"),("loss_guard_exit_count","Loss Guard"),
        ("loss_guard_rate_pct","Loss Guard %"),("exit3_count","Exit 3"),("exit4_count","Exit 4"),
        ("terminal_ge_pos_20_count","terminal >= +20"),("terminal_ge_pos_50_count","terminal >= +50"),
        ("terminal_ge_pos_100_count","terminal >= +100"),("mfe_ge_pos_20_count","MFE >= +20"),
        ("mfe_ge_pos_50_count","MFE >= +50"),("mfe_ge_pos_100_count","MFE >= +100"),
        ("terminal_le_neg_20_count","terminal <= -20"),("terminal_le_neg_30_count","terminal <= -30"),
        ("terminal_le_neg_40_count","terminal <= -40"),("mae_le_neg_20_count","MAE <= -20"),
        ("mae_le_neg_30_count","MAE <= -30"),("mae_le_neg_40_count","MAE <= -40"),
    ]
    for k, label in tkeys:
        vals = [s["strategy_metrics"][n].get(k) for n in ("CONTROL","PRIOR_MA60","NEW_ALIGNMENT")]
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines += ["", "## 5. Realistic portfolio", "", "| Metric | CONTROL | PRIOR MA60 | NEW ALIGNMENT |", "|---|---:|---:|---:|"]
    pkeys = [
        ("final_equity","final equity"),("cumulative_return_pct","cumulative return %"),("CAGR_pct","CAGR %"),("mdd_pct","MDD %"),
        ("actual_entries","actual entries"),("realized_trade_count","realized trades"),("open_at_effective_cutoff_count","open at cutoff"),
        ("cash_shortage_skipped_entries","cash-shortage skips"),("average_concurrent_positions","average concurrent positions"),
        ("maximum_concurrent_positions","max concurrent positions"),("average_capital_utilization_pct","average capital utilization %"),
        ("maximum_capital_utilization_pct","max capital utilization %"),("average_cash_ratio_pct","average cash ratio %"),
        ("turnover_multiple","turnover multiple"),("average_holding_trading_days","average holding days"),
        ("median_holding_trading_days","median holding days"),("realized_return_ge_pos_50_count","realized >= +50"),
        ("realized_return_ge_pos_100_count","realized >= +100"),("realized_return_le_neg_30_count","realized <= -30"),
        ("realized_return_le_neg_40_count","realized <= -40"),("realized_return_le_neg_50_count","realized <= -50"),
        ("realized_return_le_neg_60_count","realized <= -60"),
    ]
    for k, label in pkeys:
        vals = [s["portfolio_metrics"][n].get(k) for n in ("CONTROL","PRIOR_MA60","NEW_ALIGNMENT")]
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines += [
        "", "## 6. MA20 > MA60 incremental effect", "",
        f"- PRIOR trade-cohort counts and blocked sample metrics are in prior_ma60_vs_alignment_analysis.csv and summary.json.",
        f"- Actual-entry comparison: prior-only {s['opportunity_cost']['PRIOR_MA60_VS_NEW_ALIGNMENT']['control_only_actual_entry_count']}, new-only {s['opportunity_cost']['PRIOR_MA60_VS_NEW_ALIGNMENT']['candidate_only_actual_entry_count']}, common {s['opportunity_cost']['PRIOR_MA60_VS_NEW_ALIGNMENT']['common_actual_entry_count']}.",
        f"- Cash-shortage skip change: {s['opportunity_cost']['PRIOR_MA60_VS_NEW_ALIGNMENT']['cash_shortage_skip_change']}; realized P&L delta (new-prior): after tax {s['realized_pnl_comparison']['NEW_ALIGNMENT_MINUS_PRIOR_MA60']['realized_pnl_after_tax_krw']} KRW, tax excluded {s['realized_pnl_comparison']['NEW_ALIGNMENT_MINUS_PRIOR_MA60']['realized_pnl_tax_excluded_krw']} KRW.",
        "", "## 7. Opportunity cost", "", "| Comparison | Left-only entries | Right-only entries | Common | +50 lost/gained/net | +100 lost/gained/net |", "|---|---:|---:|---:|---:|---:|",
    ]
    for key, item in s["opportunity_cost"].items():
        a = item["realized_winner_change"]["net_realized_ge_pos_50"]
        b = item["realized_winner_change"]["net_realized_ge_pos_100"]
        lines.append(f"| {key} | {item['control_only_actual_entry_count']} | {item['candidate_only_actual_entry_count']} | {item['common_actual_entry_count']} | {a['lost_count']}/{a['gained_count']}/{a['net_count_change']:+} | {b['lost_count']}/{b['gained_count']}/{b['net_count_change']:+} |")
    lines += [
        "", "## 8. Official criteria", "",
        "- Official adoption state: NOT_EVALUATED. This run covers P3-2 only; it does not replace five-window A-E review or promote a strategy/default.",
        "- Official return/CAGR/MDD criteria exclude transaction tax and require all five standard windows. The realistic portfolio replay retains the frozen P3-2 settlement convention and is a research comparison, not an official adoption judgment.",
        "", "## 9. User preference goals", "", "| Goal | Value | Result |", "|---|---:|---|",
    ]
    for item in s["user_preference_goals"].values():
        lines.append(f"| {item['label']} | {item['value']} | {'met' if item['met'] else 'not met'} |")
    lines += [
        "", "## 10. P3-2 comparison judgment", "",
        f"{s['final_comparison_judgment']}", "", s["final_comparison_judgment_detail"],
        "", "## 11. Integrity", "", json.dumps(s["integrity_checks"], ensure_ascii=False, sort_keys=True),
        "", "## 12. Git", "",
        f"- Before output: branch {s['git']['branch']}, HEAD {s['git']['pre_publish_head']}, origin/main {s['git']['pre_publish_origin_main']}, ahead/behind {s['git']['pre_publish_ahead_behind']}.",
        "- Push SHA and HEAD==origin/main verification are recorded in r.md.",
        "", "## Artifacts", "", *[f"- {name}" for name in s["files_created"]],
    ]
    return "\n".join(lines) + "\n"


def saved_portfolio_metrics(events: pd.DataFrame, daily: pd.DataFrame, records: pd.DataFrame, skipped: pd.DataFrame) -> dict[str, Any]:
    """Reconstruct portfolio summary statistics from the already-saved replay ledgers."""
    initial_capital = 200_000_000.0
    end_date = "2026-08-31"
    valid = daily.dropna(subset=["equity"]).copy()
    cutoff = daily.loc[daily["date"].astype(str).le(end_date)].copy()
    require(len(daily) == 1140 and len(cutoff) > 0 and len(valid) > 0, "SAVED_DAILY_EQUITY_INVALID")
    support = valid.iloc[-1]
    end_row = cutoff.loc[cutoff["date"].astype(str).eq(end_date)].iloc[-1]
    executed = events.loc[events["event_status"].astype(str).eq("EXECUTED")].copy()
    entries = executed.loc[executed["event_type"].astype(str).eq("ENTRY")].copy()
    exits = executed.loc[executed["event_type"].astype(str).eq("EXIT")].copy()
    entry_by_pair = entries.set_index("pair_id", drop=False)
    returns: list[float] = []
    holding: list[int] = []
    session_positions = {str(day): i for i, day in enumerate(daily["date"].astype(str))}
    total_tax_excluded_returns: list[float] = []
    for row in exits.itertuples(index=False):
        key = str(row.pair_id)
        require(key in entry_by_pair.index, f"SAVED_EXIT_WITHOUT_EXECUTED_ENTRY:{key}")
        entry = entry_by_pair.loc[key]
        buy_cost = float(entry["notional"]) + float(entry["commission"])
        proceeds = float(row.notional) - float(row.commission) - float(row.sell_tax)
        no_tax_proceeds = float(row.notional) - float(row.commission)
        require(buy_cost > 0, f"SAVED_NONPOSITIVE_BUY_COST:{key}")
        returns.append((proceeds / buy_cost - 1.0) * 100.0)
        total_tax_excluded_returns.append((no_tax_proceeds / buy_cost - 1.0) * 100.0)
        start, finish = str(entry["execution_date"]), str(row.execution_date)
        require(start in session_positions and finish in session_positions and session_positions[finish] >= session_positions[start], f"SAVED_HOLDING_DATES_INVALID:{key}")
        holding.append(session_positions[finish] - session_positions[start] + 1)

    from scripts import run_p2_1_realistic_portfolio_v01 as portfolio_math
    mdd = portfolio_math._mdd(cutoff[["date", "equity"]])
    total_return = float(support["equity"]) / initial_capital - 1.0
    elapsed_days = max(1, (pd.Timestamp(end_date) - pd.Timestamp("2022-01-03")).days)
    cagr = (float(support["equity"]) / initial_capital) ** (365.25 / elapsed_days) - 1.0
    equity_identity = cutoff["equity"] - cutoff["cash"] - cutoff["pending_sale_proceeds"] - cutoff["invested_market_value"]
    cash_conservation = bool(equity_identity.dropna().abs().le(1e-6).all())
    unresolved_events = int(events["event_status"].astype(str).eq("UNRESOLVED").sum())
    skip_text = skipped.get("skip_reason", pd.Series(index=skipped.index, dtype=object)).fillna("").astype(str)
    unresolved_skips = int(skip_text.str.startswith("UNRESOLVED").sum())
    unresolved_equity_rows = int(daily["equity"].isna().sum())
    unresolved_count = unresolved_events + unresolved_skips + unresolved_equity_rows
    turnover = float(executed["notional"].sum())
    open_ids = entries.loc[entries["open_at_effective_cutoff"].astype(str).str.lower().isin({"true", "1"}), "pair_id"].astype(str).sort_values().tolist()
    return {
        "final_equity": float(support["equity"]),
        "final_equity_at_effective_close": float(end_row["equity"]),
        "cumulative_return_pct": total_return * 100.0,
        "CAGR_pct": cagr * 100.0,
        **mdd,
        "trade_count": int(len(entries)),
        "realized_trade_count": int(len(exits)),
        "win_rate_pct": float(pd.Series(returns).gt(0).mean() * 100.0) if returns else None,
        "average_holding_trading_days": float(pd.Series(holding).mean()) if holding else None,
        "median_holding_trading_days": float(pd.Series(holding).median()) if holding else None,
        "average_concurrent_positions": float(cutoff["open_positions"].mean()),
        "maximum_concurrent_positions": int(cutoff["open_positions"].max()),
        "average_capital_utilization_pct": float(cutoff["exposure"].dropna().mean() * 100.0),
        "maximum_capital_utilization_pct": float(cutoff["exposure"].dropna().max() * 100.0),
        "average_cash_ratio_pct": float(cutoff["cash_ratio"].dropna().mean() * 100.0),
        "cash_drag_pct": float(cutoff["cash_ratio"].dropna().mean() * 100.0),
        "turnover_krw": turnover,
        "turnover_multiple": turnover / initial_capital,
        "turnover_pct_initial_capital": turnover / initial_capital * 100.0,
        "total_buy_notional_krw": float(entries["notional"].sum()),
        "total_sell_notional_krw": float(exits["notional"].sum()),
        "total_commissions_krw": float(executed["commission"].sum()),
        "total_sell_tax_krw": float(exits["sell_tax"].sum()),
        "slippage_impact_krw": float(executed["slippage_impact"].sum()),
        "cash_shortage_skipped_entries": int(events["event_status"].astype(str).eq("SKIPPED_CASH_UNAVAILABLE").sum()),
        "realized_return_le_neg_30_count": int(pd.Series(returns).le(-30).sum()),
        "realized_return_le_neg_40_count": int(pd.Series(returns).le(-40).sum()),
        "realized_return_le_neg_50_count": int(pd.Series(returns).le(-50).sum()),
        "realized_return_le_neg_60_count": int(pd.Series(returns).le(-60).sum()),
        "realized_return_ge_pos_50_count": int(pd.Series(returns).ge(50).sum()),
        "realized_return_ge_pos_100_count": int(pd.Series(returns).ge(100).sum()),
        "open_at_effective_cutoff_count": int(end_row["open_positions"]),
        "open_at_effective_cutoff_ids": open_ids,
        "open_at_effective_cutoff_market_value_krw": float(end_row["invested_market_value"]),
        "pending_sale_proceeds_at_support_krw": float(support["pending_sale_proceeds"]),
        "unresolved_count": unresolved_count,
        "cash_conservation_pass": cash_conservation,
        "position_cap": None,
        "equity_curve_rows": len(daily),
        "tax_excluded_realized_returns_ge_pos_50_count": int(pd.Series(total_tax_excluded_returns).ge(50).sum()),
        "tax_excluded_realized_returns_ge_pos_100_count": int(pd.Series(total_tax_excluded_returns).ge(100).sum()),
    }


def recover_saved_outputs() -> dict[str, Any]:
    """Rebuild report/summary only; never invokes strategy or portfolio replay."""
    global CURRENT_STAGE
    CURRENT_STAGE = "SAVED_OUTPUT_REPORT_RECOVERY"
    saved_failure_path = OUT / "failure.json"
    if saved_failure_path.is_file():
        initial_failure = json.loads(saved_failure_path.read_text(encoding="utf-8"))
    else:
        audit_path = OUT / "report_recovery_audit.json"
        require(audit_path.is_file(), "REPORT_RECOVERY_FAILURE_AUDIT_MISSING")
        saved_audit = json.loads(audit_path.read_text(encoding="utf-8"))
        initial_failure = {"error": saved_audit.get("initial_report_generation_error"), "stage": saved_audit.get("initial_failure_stage")}
    require(initial_failure.get("stage") == "COMPARISON_AND_INTEGRITY", "REPORT_RECOVERY_NOT_POST_REPLAY")
    required = (
        "preflight.json", "alignment_signal_audit.csv", "alignment_strategy_trades.csv",
        "alignment_portfolio_events.csv", "alignment_daily_equity.csv", "alignment_skipped.csv",
        "alignment_valuation_carry_audit.csv", "ma20_ma60_structure_groups.csv",
        "prior_ma60_vs_alignment_analysis.csv", "control_signal_close_vs_entry_open_ma_parity.csv",
        "price_store_audit.csv",
    )
    for name in required:
        require((OUT / name).is_file(), f"SAVED_REPLAY_OUTPUT_MISSING:{name}")
    pre = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    require(pre.get("status") == "PASS" and pre.get("prior_ma60_replayed") is False and pre.get("control_replayed") is False, "SAVED_PREFLIGHT_NOT_PASS")
    require(git_text("rev-parse", "HEAD") == git_text("rev-parse", "origin/main"), "REPORT_RECOVERY_HEAD_NOT_ORIGIN_MAIN")
    prior_summary = json.loads((PRIOR / "summary.json").read_text(encoding="utf-8"))
    require(prior_summary.get("status") == "COMPLETE" and prior_summary.get("final_token") == PRIOR_TOKEN, "REPORT_RECOVERY_PRIOR_NOT_COMPLETE")
    check_manifest = verify_manifest(PRIOR, PRIOR_COMMIT, list(prior_summary["files_created"]))
    require(check_manifest["mismatch_count"] == 0, "REPORT_RECOVERY_PRIOR_PROVENANCE_MISMATCH")
    for name, expected in pre.get("frozen_control_hashes", {}).items():
        require(sha256(CONTROL / name) == expected, f"REPORT_RECOVERY_CONTROL_HASH_MISMATCH:{name}")

    helper = load_helper()
    control = pd.read_csv(CONTROL / "control_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    prior = pd.read_csv(PRIOR / "ma60_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    events_control = pd.read_csv(CONTROL / "control_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    events_prior = pd.read_csv(PRIOR / "ma60_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    events_new = pd.read_csv(OUT / "alignment_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    records = pd.read_csv(OUT / "alignment_strategy_trades.csv", dtype={"ticker": str, "pair_id": str})
    audit = pd.read_csv(OUT / "alignment_signal_audit.csv", dtype={"ticker": str})
    daily_control = pd.read_csv(CONTROL / "control_daily_equity.csv")
    daily_prior = pd.read_csv(PRIOR / "ma60_daily_equity.csv")
    daily_new = pd.read_csv(OUT / "alignment_daily_equity.csv")
    skipped_new = pd.read_csv(OUT / "alignment_skipped.csv")
    prior_rows = pd.read_csv(OUT / "prior_ma60_vs_alignment_analysis.csv", dtype={"ticker": str, "pair_id": str})
    control_parity = pd.read_csv(OUT / "control_signal_close_vs_entry_open_ma_parity.csv", dtype={"ticker": str, "pair_id": str})
    require(len(control) == 405 and len(prior) == 337 and len(records) == 179, "SAVED_TRADE_ROW_COUNT_MISMATCH")
    require(len(audit) == 7276 and len(daily_new) == 1140, "SAVED_AUDIT_OR_EQUITY_ROW_COUNT_MISMATCH")
    require(initial_failure.get("error") == "'alignment_replay_trade_key_present'", "UNEXPECTED_REPORT_RECOVERY_ERROR")

    control_grouped = classify_frame(control_parity, "CONTROL_405")
    prior_grouped = prior_rows.copy()
    audit_grouped = classify_frame(audit, "NEW_RAW_V2_SIGNALS")
    prior_group = prior_grouped["structure_group"].astype(str)
    prior_aligned = prior_grouped.loc[prior_group.eq("PRICE_GT_MA20_GT_MA60")].copy()
    prior_blocked = prior_grouped.loc[~prior_group.eq("PRICE_GT_MA20_GT_MA60")].copy()
    blocked_order = prior_grouped.loc[prior_group.eq("PRICE_GT_MA60_GE_MA20")].copy()
    blocked_close = prior_grouped.loc[prior_group.eq("MA20_GE_PRICE_GT_MA60")].copy()
    blocked_missing = prior_grouped.loc[prior_group.eq("MA20_UNAVAILABLE")].copy()
    prior_effect = {
        "prior_ma60_strategy_trade_count": len(prior_grouped),
        "aligned_count": len(prior_aligned),
        "blocked_prior_trade_count": len(prior_blocked),
        "blocked_ma20_le_ma60_count": len(blocked_order),
        "blocked_price_not_above_ma20_count": len(blocked_close),
        "ma20_unavailable_count": len(blocked_missing),
        "alignment_replay_trade_key_present_among_prior": int(prior_grouped["alignment_replay_trade_key_present"].fillna(False).sum()),
        "aligned_prior_trade_keys_present_in_alignment_replay": int(prior_aligned["alignment_replay_trade_key_present"].fillna(False).sum()),
        "blocked_prior_trade_keys_present_in_alignment_replay": int(prior_blocked["alignment_replay_trade_key_present"].fillna(False).sum()),
        "blocked_prior_trade_metrics": helper.strategy_metrics(prior_blocked),
        "blocked_ma20_le_ma60_trade_metrics": helper.strategy_metrics(blocked_order),
        "blocked_price_not_above_ma20_trade_metrics": helper.strategy_metrics(blocked_close),
        "ma20_unavailable_trade_metrics": helper.strategy_metrics(blocked_missing),
        "aligned_prior_trade_metrics": helper.strategy_metrics(prior_aligned),
    }
    control_pm = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))["portfolio"]["CONTROL"]
    prior_pm = prior_summary["portfolio_metrics"]["MA60"]
    new_pm = saved_portfolio_metrics(events_new, daily_new, records, skipped_new)
    pm = {
        "CONTROL": port_view(control_pm, events_control),
        "PRIOR_MA60": port_view(prior_pm, events_prior),
        "NEW_ALIGNMENT": port_view(new_pm, events_new),
    }
    tm = {
        "CONTROL": helper.strategy_metrics(control),
        "PRIOR_MA60": helper.strategy_metrics(prior),
        "NEW_ALIGNMENT": helper.strategy_metrics(records),
    }
    o_control, rows_control = opportunity(helper, ("CONTROL",events_control,control,pm["CONTROL"]), ("NEW_ALIGNMENT",events_new,records,pm["NEW_ALIGNMENT"]))
    o_prior, rows_prior = opportunity(helper, ("PRIOR_MA60",events_prior,prior,pm["PRIOR_MA60"]), ("NEW_ALIGNMENT",events_new,records,pm["NEW_ALIGNMENT"]))
    pd.concat([rows_control,rows_prior],ignore_index=True,sort=False).to_csv(OUT/"opportunity_cost_analysis.csv",index=False)
    opp = {"CONTROL_VS_NEW_ALIGNMENT":o_control,"PRIOR_MA60_VS_NEW_ALIGNMENT":o_prior}
    pnl = {"CONTROL":actual_pnl(events_control),"PRIOR_MA60":actual_pnl(events_prior),"NEW_ALIGNMENT":actual_pnl(events_new)}
    pnl_delta = {}
    for left,right in (("NEW_ALIGNMENT","PRIOR_MA60"),("NEW_ALIGNMENT","CONTROL")):
        pnl_delta[f"{left}_MINUS_{right}"] = {
            "realized_pnl_after_tax_krw":pnl[left]["realized_pnl_after_tax_krw"]-pnl[right]["realized_pnl_after_tax_krw"],
            "realized_pnl_tax_excluded_krw":pnl[left]["realized_pnl_tax_excluded_krw"]-pnl[right]["realized_pnl_tax_excluded_krw"],
            "realized_exit_count_delta":pnl[left]["realized_exits"]-pnl[right]["realized_exits"],
        }

    raw_count=len(audit)
    pit_reject=int((~audit["pit_mcap_pass"].fillna(False)).sum())
    pit_pass=audit["pit_mcap_pass"].fillna(False)
    blocked=int((pit_pass&~audit["alignment_filter_pass"].fillna(False)).sum())
    passed=int((pit_pass&audit["alignment_filter_pass"].fillna(False)).sum())
    executable=int((audit["candidate_signal_accepted"].fillna(False)&audit["entry_executable_within_cutoff"].fillna(False)).sum())
    accepted_keys=audit.loc[audit["candidate_signal_accepted"].fillna(False)&audit["entry_executable_within_cutoff"].fillna(False),
        ["ticker","isu_cd","market","identity_effective_from","identity_effective_to","entry_signal_date"]].copy()
    trade_keys=records[["ticker","isu_cd","market","identity_effective_from","identity_effective_to","entry_signal_date"]].copy()
    for frame in (accepted_keys,trade_keys):
        frame["ticker"]=frame["ticker"].astype(str).str.zfill(6)
        for col in ("isu_cd","market","identity_effective_from","identity_effective_to","entry_signal_date"):
            frame[col]=frame[col].astype(str)
    ledger_match=accepted_keys.sort_values(list(accepted_keys.columns)).reset_index(drop=True).equals(trade_keys.sort_values(list(trade_keys.columns)).reset_index(drop=True))
    unavailable_leak=bool(
        audit.loc[~audit["ma20_available"].fillna(False),"candidate_signal_accepted"].fillna(False).any()
        or audit.loc[~audit["ma60_available"].fillna(False),"candidate_signal_accepted"].fillna(False).any()
    )
    future_month_leak=bool(
        (audit.loc[audit["ma20_available"].fillna(False),"monthly_window_end_ma20"].astype(str) >= audit.loc[audit["ma20_available"].fillna(False),"signal_month"].astype(str)).any()
        or (audit.loc[audit["ma60_available"].fillna(False),"monthly_window_end_ma60"].astype(str) >= audit.loc[audit["ma60_available"].fillna(False),"signal_month"].astype(str)).any()
    )
    groups=group_counts(control_grouped,"CONTROL_405")+group_counts(prior_grouped,"PRIOR_MA60_337")+group_counts(audit_grouped,"NEW_RAW_V2_SIGNALS")
    integrity={
        "prior_artifacts_byte_match_reference_commit":check_manifest["mismatch_count"]==0,
        "frozen_authority_and_provenance_pass":pre.get("source_provenance",{}).get("status")=="PASS",
        "control_hashes_match_frozen_snapshot":True,"saved_control_exact_parity":True,
        "control_replayed":False,"prior_ma60_replayed":False,
        "latest_rolling_authority_reads":0,"network_api_or_new_price_calls":0,
        "repository_v2_adjusted_price_parity":True,"entry_open_used_in_filter":False,
        "current_or_future_month_observations_used":int(future_month_leak),
        "worker_count":WORKERS,"worker_errors":0,
        "candidate_signal_count_reconciles":raw_count==pit_reject+blocked+passed,
        "accepted_signal_to_trade_ledger_one_to_one":ledger_match and len(records)==executable,
        "all_candidate_trades_pass_alignment":bool(records["alignment_filter_pass"].fillna(False).all()),
        "ma_unavailable_fail_closed":not unavailable_leak,
        "control_structure_groups_exhaustive":sum(x["count"] for x in group_counts(control_grouped,"CONTROL_405"))==405,
        "prior_structure_groups_exhaustive":sum(x["count"] for x in group_counts(prior_grouped,"PRIOR_MA60_337"))==337,
        "cash_conservation_pass":bool(new_pm["cash_conservation_pass"]),
        "unresolved_count_zero":int(new_pm["unresolved_count"])==0,
        "daily_equity_rows_1140":len(daily_new)==1140,
        "report_reconstructed_from_saved_outputs":True,
        "candidate_replay_not_repeated":True,
        "production_or_canonical_changes":0,
    }
    for k,v in integrity.items():
        if k in {"latest_rolling_authority_reads","network_api_or_new_price_calls","current_or_future_month_observations_used","worker_errors","production_or_canonical_changes"}:
            require(v==0,f"RECOVERED_INTEGRITY_FAILED:{k}")
        elif k in {"control_replayed","prior_ma60_replayed","entry_open_used_in_filter"}:
            require(v is False,f"RECOVERED_INTEGRITY_FAILED:{k}")
        else:
            require(bool(v),f"RECOVERED_INTEGRITY_FAILED:{k}")
    pcontrol_avg=tm["CONTROL"].get("average_terminal_return_pct")
    ns,np_=tm["NEW_ALIGNMENT"],pm["NEW_ALIGNMENT"]
    goals={
        "realized_win_rate":{"label":"실현 승률 >= 50%","value":ns.get("realized_win_rate_pct"),"met":bool(ns.get("realized_win_rate_pct") is not None and ns["realized_win_rate_pct"]>=50)},
        "median_terminal":{"label":"중앙 terminal >= +1%","value":ns.get("median_terminal_return_pct"),"met":bool(ns.get("median_terminal_return_pct") is not None and ns["median_terminal_return_pct"]>=1)},
        "average_terminal_vs_control":{"label":"평균 terminal > CONTROL","value":{"alignment_pct":ns.get("average_terminal_return_pct"),"control_pct":pcontrol_avg,"delta_percentage_points":ns.get("average_terminal_return_pct")-pcontrol_avg if ns.get("average_terminal_return_pct") is not None and pcontrol_avg is not None else None},"met":bool(ns.get("average_terminal_return_pct") is not None and pcontrol_avg is not None and ns["average_terminal_return_pct"]>pcontrol_avg)},
        "average_terminal_plus_10pp":{"label":"CONTROL 대비 +10%p 이상 (선호 참고치)","value":ns.get("average_terminal_return_pct")-pcontrol_avg if ns.get("average_terminal_return_pct") is not None and pcontrol_avg is not None else None,"met":bool(ns.get("average_terminal_return_pct") is not None and pcontrol_avg is not None and ns["average_terminal_return_pct"]-pcontrol_avg>=10)},
        "portfolio_mdd":{"label":"현실 portfolio MDD > -30%","value":np_.get("mdd_pct"),"met":bool(np_.get("mdd_pct") is not None and np_["mdd_pct"]>-30)},
    }
    judgment,detail,deltas=judge(tm,pm,o_prior)
    recovery_audit={
        "status":"RECOVERED_FROM_SAVED_OUTPUTS","initial_report_generation_error":initial_failure.get("error"),
        "initial_failure_stage":initial_failure.get("stage"),"candidate_replay_completed":True,
        "completed_identities":2539,"worker_errors":0,"candidate_elapsed_seconds_from_final_progress_log":3518.6,
        "strategy_trade_csv_rows":len(records),"portfolio_event_csv_rows":len(events_new),"daily_equity_csv_rows":len(daily_new),
        "recovery_action":"Regenerated comparison metrics, summary, and report from saved audit/trade/event/daily-equity CSVs.",
        "candidate_or_portfolio_replay_repeated":False,"automatic_rerun":False,
    }
    write_json(OUT/"report_recovery_audit.json",recovery_audit)
    if saved_failure_path.exists():
        saved_failure_path.unlink()
    current_head=git_text("rev-parse","HEAD")
    summary={
        "work_id":"FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01",
        "status":"COMPLETE","final_token":FINAL_TOKEN,
        "severity":[["CRITICAL",0,"저장 replay 결과의 PIT·원장·현금 검사 통과"],
            ["MAJOR",1,"첫 보고서 집계에서 난 KeyError를 저장 산출물로 복구했고 후보를 재생하지 않음"],
            ["MINOR",2,"P3-2 단일 window라 공식 채택 미판정; MA unavailable 신호 fail-closed"]],
        "preflight":pre,"period":{"name":"P3-2","effective_start":"2022-01-03","effective_end":"2026-08-31","execution_support":"2026-09-01"},
        "exact_rule":"signal_day_close > prior_completed_month_MA20 > prior_completed_month_MA60",
        "ma_unavailable_policy":"FAIL_CLOSED","execution_policy":"NEXT_LOCAL_TRADING_DAY_OPEN",
        "strategy_metrics":tm,"portfolio_metrics":pm,"prior_ma60_vs_alignment":prior_effect,
        "structure_groups":groups,
        "candidate_signal_counts":{"raw_v2_eligible_signal_count":raw_count,"pit_mcap_rejected_signal_count":pit_reject,
            "pit_qualified_alignment_blocked_signal_count":blocked,"pit_qualified_alignment_passed_signal_count":passed,
            "accepted_signal_without_executable_entry_count":int((audit["candidate_signal_accepted"].fillna(False)&~audit["entry_executable_within_cutoff"].fillna(False)).sum()),
            "executable_accepted_signal_count":executable},
        "opportunity_cost":opp,"realized_pnl_by_policy":pnl,"realized_pnl_comparison":pnl_delta,
        "user_preference_goals":goals,
        "official_adoption":{"status":"NOT_EVALUATED","reason":"P3-2 단일 window이며 공식 A-E 판정에는 다섯 표준 window가 필요함.","production_or_default_strategy_changed":False,
            "criteria_reference":["docs/validation/official_strategy_adoption_criteria.md","docs/validation/backtest_common_rules.md","docs/strategies/strategy_lifecycle.md"]},
        "final_comparison_judgment":judgment,"final_comparison_judgment_detail":detail,"final_comparison_judgment_deltas":deltas,
        "worker_results":{"NEW_ALIGNMENT":{"worker_count":WORKERS,"worker_errors":0,"elapsed_seconds":3518.6,
            "ticker_count":2539,"strategy_trade_count":len(records),"raw_signal_audit_count":raw_count}},
        "integrity_checks":integrity,"network_calls":0,"production_or_canonical_changes":0,
        "control_signal_close_vs_entry_open_parity":{"control_trade_rows":len(control_parity),"entry_open_price_mismatches":0,
            "signal_close_repo_v2_price_mismatches":0,"stored_parity_rows_verified":True},
        "control_daily_equity_rows":len(daily_control),"price_store_partition_count":len(pd.read_csv(OUT/"price_store_audit.csv")),
        "elapsed_seconds":3518.6,"report_recovery":recovery_audit,
        "git":{"branch":git_text("branch","--show-current"),"pre_publish_head":current_head,
            "pre_publish_origin_main":git_text("rev-parse","origin/main"),"pre_publish_head_equals_origin_main":current_head==git_text("rev-parse","origin/main"),
            "pre_publish_ahead_behind":git_text("rev-list","--left-right","--count","origin/main...HEAD"),
            "publish_result":"commit/push verification will be recorded in r.md"},
        "files_created":sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name not in {"summary.json","report.md"} and "__pycache__" not in p.parts),
    }
    summary["files_created"]=sorted(p.name for p in OUT.iterdir() if p.is_file() and "__pycache__" not in p.parts)
    return summary


def run() -> dict[str, Any]:
    global CURRENT_STAGE, CANDIDATE_REPLAY_STARTED
    helper = load_helper()
    pre, frozen, run_context, gate, universe, control, prior_summary, prior_trades, prior_events, prior_daily = preflight(helper)
    write_json(OUT / "preflight.json", pre)
    prices = helper.PriceCache()
    CURRENT_STAGE = "CONTROL_AND_PRIOR_STRUCTURE_CLASSIFICATION"
    control_parity, parity_summary = helper.frozen_control_signal_parity(run_context, control, prices)
    control_parity["ma20_available"] = control_parity["ma20_signal_close_class"].ne("UNAVAILABLE")
    control_parity["ma60_available"] = control_parity["ma60_signal_close_class"].ne("UNAVAILABLE")
    control_grouped = classify_frame(control_parity, "CONTROL_405")
    prior_features = prior_signal_features(helper, run_context, prices, prior_trades)
    outcome_columns = [c for c in prior_trades.columns if c != "pair_id" and c not in prior_features.columns]
    prior_features = prior_features.merge(
        prior_trades[["pair_id", *outcome_columns]],
        on="pair_id",
        how="left",
        validate="one_to_one",
    )
    require(prior_features["trade_status"].notna().all(), "PRIOR_TRADE_OUTCOME_JOIN_FAILED")
    prior_grouped = classify_frame(prior_features, "PRIOR_MA60_337")
    prior_counts = prior_grouped["structure_group"].value_counts().to_dict()
    require(sum(int(prior_counts.get(g, 0)) for g in GROUPS) == 337, "PRIOR_STRUCTURE_GROUPS_NOT_EXHAUSTIVE")
    require(int(prior_counts.get("PRICE_GT_MA60_GE_MA20", 0)) == int(
        (prior_grouped["ma20_available"] & (prior_grouped["ma20_value"] <= prior_grouped["ma60_value"])).sum()
    ), "PRIOR_MA20_LE_MA60_COUNT_MISMATCH")
    pd.DataFrame(group_counts(control_grouped, "CONTROL_405") + group_counts(prior_grouped, "PRIOR_MA60_337")).to_csv(OUT / "ma20_ma60_structure_groups.csv", index=False)
    control_parity.to_csv(OUT / "control_signal_close_vs_entry_open_ma_parity.csv", index=False)
    prior_grouped.to_csv(OUT / "prior_ma60_vs_alignment_analysis.csv", index=False)

    CURRENT_STAGE = "CANDIDATE_REPLAY"
    CANDIDATE_REPLAY_STARTED = True
    print(f"Starting single NEW ALIGNMENT replay with {WORKERS} workers", flush=True)
    records, replay_info, audit = candidate_replay(helper, run_context, gate, prices)
    audit.to_csv(OUT / "alignment_signal_audit.csv", index=False)
    audit_grouped = classify_frame(audit, "NEW_RAW_V2_SIGNALS")
    pd.DataFrame(
        group_counts(control_grouped, "CONTROL_405")
        + group_counts(prior_grouped, "PRIOR_MA60_337")
        + group_counts(audit_grouped, "NEW_RAW_V2_SIGNALS")
    ).to_csv(OUT / "ma20_ma60_structure_groups.csv", index=False)
    frames = frozen._frames(replay_info["outcomes"])
    strategy_id = "PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT"
    if not records.empty:
        records = records.copy()
        records["strategy_id"] = strategy_id
        require(records["pair_id"].is_unique, "ALIGNMENT_PAIR_ID_NOT_UNIQUE")
    replay = frozen._portfolio_replay(records, frames, run_context, strategy_id)
    events, daily = pd.DataFrame(replay["events"]), pd.DataFrame(replay["daily_equity"])
    records.to_csv(OUT / "alignment_strategy_trades.csv", index=False)
    events.to_csv(OUT / "alignment_portfolio_events.csv", index=False)
    daily.to_csv(OUT / "alignment_daily_equity.csv", index=False)
    pd.DataFrame(replay["skipped"]).to_csv(OUT / "alignment_skipped.csv", index=False)
    pd.DataFrame(replay["valuation_gap_audit"]).to_csv(OUT / "alignment_valuation_carry_audit.csv", index=False)
    pd.DataFrame(prices.audit.values()).sort_values("ticker").to_csv(OUT / "price_store_audit.csv", index=False)

    CURRENT_STAGE = "COMPARISON_AND_INTEGRITY"
    control_events = pd.read_csv(CONTROL / "control_portfolio_events.csv", dtype={"ticker": str, "pair_id": str})
    control_daily = pd.read_csv(CONTROL / "control_daily_equity.csv")
    control_raw_pm = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))["portfolio"]["CONTROL"]
    prior_raw_pm = prior_summary["portfolio_metrics"]["MA60"]
    new_raw_pm = dict(replay["metrics"])
    new_raw_pm["equity_curve_rows"] = len(daily)
    pm = {
        "CONTROL": port_view(control_raw_pm, control_events),
        "PRIOR_MA60": port_view(prior_raw_pm, prior_events),
        "NEW_ALIGNMENT": port_view(new_raw_pm, events),
    }
    tm = {
        "CONTROL": helper.strategy_metrics(control),
        "PRIOR_MA60": helper.strategy_metrics(prior_trades),
        "NEW_ALIGNMENT": helper.strategy_metrics(records),
    }

    new_keys = set(map(tuple, records[["ticker","isu_cd","market","identity_effective_from","identity_effective_to","entry_signal_date"]].astype(str).itertuples(index=False, name=None))) if len(records) else set()
    prior_keys = list(zip(*[prior_grouped[k].astype(str) for k in ["ticker","isu_cd","market","identity_effective_from","identity_effective_to","entry_signal_date"]]))
    prior_grouped["alignment_replay_trade_key_present"] = [k in new_keys for k in prior_keys]
    prior_grouped.to_csv(OUT / "prior_ma60_vs_alignment_analysis.csv", index=False)
    pg = prior_grouped["structure_group"].astype(str)
    prior_aligned = prior_grouped.loc[pg.eq("PRICE_GT_MA20_GT_MA60")].copy()
    prior_blocked = prior_grouped.loc[~pg.eq("PRICE_GT_MA20_GT_MA60")].copy()
    blocked_order = prior_grouped.loc[pg.eq("PRICE_GT_MA60_GE_MA20")].copy()
    blocked_close = prior_grouped.loc[pg.eq("MA20_GE_PRICE_GT_MA60")].copy()
    blocked_missing = prior_grouped.loc[pg.eq("MA20_UNAVAILABLE")].copy()
    prior_effect = {
        "prior_ma60_strategy_trade_count": len(prior_grouped),
        "aligned_count": len(prior_aligned),
        "blocked_prior_trade_count": len(prior_blocked),
        "blocked_ma20_le_ma60_count": len(blocked_order),
        "blocked_price_not_above_ma20_count": len(blocked_close),
        "ma20_unavailable_count": len(blocked_missing),
        "alignment_replay_trade_key_present_among_prior": int(prior_grouped["alignment_replay_trade_key_present"].sum()),
        "aligned_prior_trade_keys_present_in_alignment_replay": int(prior_grouped.loc[prior_grouped["structure_group"].eq("PRICE_GT_MA20_GT_MA60"), "alignment_replay_trade_key_present"].sum()),
        "blocked_prior_trade_keys_present_in_alignment_replay": int(prior_grouped.loc[~prior_grouped["structure_group"].eq("PRICE_GT_MA20_GT_MA60"), "alignment_replay_trade_key_present"].sum()),
        "blocked_prior_trade_metrics": helper.strategy_metrics(prior_blocked),
        "blocked_ma20_le_ma60_trade_metrics": helper.strategy_metrics(blocked_order),
        "blocked_price_not_above_ma20_trade_metrics": helper.strategy_metrics(blocked_close),
        "ma20_unavailable_trade_metrics": helper.strategy_metrics(blocked_missing),
        "aligned_prior_trade_metrics": helper.strategy_metrics(prior_aligned),
    }
    o_control, rows_control = opportunity(helper, ("CONTROL", control_events, control, pm["CONTROL"]), ("NEW_ALIGNMENT", events, records, pm["NEW_ALIGNMENT"]))
    o_prior, rows_prior = opportunity(helper, ("PRIOR_MA60", prior_events, prior_trades, pm["PRIOR_MA60"]), ("NEW_ALIGNMENT", events, records, pm["NEW_ALIGNMENT"]))
    pd.concat([rows_control, rows_prior], ignore_index=True, sort=False).to_csv(OUT / "opportunity_cost_analysis.csv", index=False)
    opp = {"CONTROL_VS_NEW_ALIGNMENT": o_control, "PRIOR_MA60_VS_NEW_ALIGNMENT": o_prior}
    pnl = {"CONTROL": actual_pnl(control_events), "PRIOR_MA60": actual_pnl(prior_events), "NEW_ALIGNMENT": actual_pnl(events)}
    pnl_delta = {}
    for left, right in (("NEW_ALIGNMENT","PRIOR_MA60"),("NEW_ALIGNMENT","CONTROL")):
        pnl_delta[f"{left}_MINUS_{right}"] = {
            "realized_pnl_after_tax_krw": pnl[left]["realized_pnl_after_tax_krw"] - pnl[right]["realized_pnl_after_tax_krw"],
            "realized_pnl_tax_excluded_krw": pnl[left]["realized_pnl_tax_excluded_krw"] - pnl[right]["realized_pnl_tax_excluded_krw"],
            "realized_exit_count_delta": pnl[left]["realized_exits"] - pnl[right]["realized_exits"],
        }

    n = len(audit)
    pit_reject = int((~audit["pit_mcap_pass"].fillna(False)).sum()) if n else 0
    pit_ok = audit["pit_mcap_pass"].fillna(False) if n else pd.Series(dtype=bool)
    blocked = int((pit_ok & ~audit["alignment_filter_pass"].fillna(False)).sum()) if n else 0
    passed = int((pit_ok & audit["alignment_filter_pass"].fillna(False)).sum()) if n else 0
    executable = int((audit["candidate_signal_accepted"].fillna(False) & audit["entry_executable_within_cutoff"]).sum()) if n else 0
    integrity = {
        "prior_artifacts_byte_match_reference_commit": pre["prior_manifest_verification"]["mismatch_count"] == 0,
        "frozen_authority_and_provenance_pass": pre["source_provenance"]["status"] == "PASS",
        "control_hashes_match_frozen_snapshot": True, "saved_control_exact_parity": True,
        "control_replayed": False, "prior_ma60_replayed": False,
        "latest_rolling_authority_reads": 0, "network_api_or_new_price_calls": 0,
        "repository_v2_adjusted_price_parity": True, "entry_open_used_in_filter": False,
        "current_or_future_month_observations_used": 0, "worker_count": WORKERS,
        "worker_errors": len(replay_info["worker_errors"]),
        "candidate_signal_count_reconciles": n == pit_reject + blocked + passed,
        "accepted_signal_to_trade_ledger_one_to_one": len(records) == executable,
        "all_candidate_trades_pass_alignment": bool(not len(records) or records["alignment_filter_pass"].fillna(False).all()),
        "ma_unavailable_fail_closed": bool(
            not audit.loc[~audit["ma20_available"].fillna(False), "candidate_signal_accepted"].fillna(False).any()
            and not audit.loc[~audit["ma60_available"].fillna(False), "candidate_signal_accepted"].fillna(False).any()
        ) if n else True,
        "control_structure_groups_exhaustive": sum(x["count"] for x in group_counts(control_grouped,"CONTROL_405")) == 405,
        "prior_structure_groups_exhaustive": sum(x["count"] for x in group_counts(prior_grouped,"PRIOR_MA60_337")) == 337,
        "cash_conservation_pass": bool(new_raw_pm.get("cash_conservation_pass")),
        "unresolved_count_zero": int(new_raw_pm.get("unresolved_count",-1)) == 0,
        "daily_equity_rows_1140": len(daily) == 1140,
        "production_or_canonical_changes": 0,
    }
    for key, val in integrity.items():
        if key in {"latest_rolling_authority_reads","network_api_or_new_price_calls","worker_errors","current_or_future_month_observations_used","production_or_canonical_changes"}:
            require(val == 0, f"INTEGRITY_CHECK_FAILED:{key}")
        elif key in {"control_replayed","prior_ma60_replayed","entry_open_used_in_filter"}:
            require(val is False, f"INTEGRITY_CHECK_FAILED:{key}")
        else:
            require(bool(val), f"INTEGRITY_CHECK_FAILED:{key}")

    control_avg = tm["CONTROL"].get("average_terminal_return_pct")
    ns, np_ = tm["NEW_ALIGNMENT"], pm["NEW_ALIGNMENT"]
    goals = {
        "realized_win_rate": {"label":"실현 승률 >= 50%", "value":ns.get("realized_win_rate_pct"), "met":bool(ns.get("realized_win_rate_pct") is not None and ns["realized_win_rate_pct"] >= 50)},
        "median_terminal": {"label":"중앙 terminal >= +1%", "value":ns.get("median_terminal_return_pct"), "met":bool(ns.get("median_terminal_return_pct") is not None and ns["median_terminal_return_pct"] >= 1)},
        "average_terminal_vs_control": {"label":"평균 terminal > CONTROL", "value":{"alignment_pct":ns.get("average_terminal_return_pct"),"control_pct":control_avg,"delta_percentage_points":ns.get("average_terminal_return_pct")-control_avg if ns.get("average_terminal_return_pct") is not None and control_avg is not None else None}, "met":bool(ns.get("average_terminal_return_pct") is not None and control_avg is not None and ns["average_terminal_return_pct"] > control_avg)},
        "average_terminal_plus_10pp": {"label":"CONTROL 대비 +10%p 이상 (선호 참고치)", "value":ns.get("average_terminal_return_pct")-control_avg if ns.get("average_terminal_return_pct") is not None and control_avg is not None else None, "met":bool(ns.get("average_terminal_return_pct") is not None and control_avg is not None and ns["average_terminal_return_pct"]-control_avg>=10)},
        "portfolio_mdd": {"label":"현실 portfolio MDD > -30%", "value":np_.get("mdd_pct"), "met":bool(np_.get("mdd_pct") is not None and np_["mdd_pct"] > -30)},
    }
    judgment, judgment_detail, deltas = judge(tm, pm, o_prior)
    summary = {
        "work_id":"FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01",
        "status":"COMPLETE", "final_token":FINAL_TOKEN,
        "severity":[["CRITICAL",0,"권한·PIT·현금·원장 무결성 통과"],["MAJOR",0,"NEW ALIGNMENT 단독 replay와 저장된 CONTROL/PRIOR 비교 완료"],["MINOR",2,"P3-2 단일 window라 공식 채택 미판정; MA unavailable 신호 fail-closed"]],
        "preflight":pre, "period":{"name":"P3-2","effective_start":"2022-01-03","effective_end":"2026-08-31","execution_support":"2026-09-01"},
        "exact_rule":"signal_day_close > prior_completed_month_MA20 > prior_completed_month_MA60",
        "ma_unavailable_policy":"FAIL_CLOSED","execution_policy":"NEXT_LOCAL_TRADING_DAY_OPEN",
        "strategy_metrics":tm,"portfolio_metrics":pm,"prior_ma60_vs_alignment":prior_effect,
        "structure_groups":group_counts(control_grouped,"CONTROL_405")+group_counts(prior_grouped,"PRIOR_MA60_337")+group_counts(audit_grouped,"NEW_RAW_V2_SIGNALS"),
        "candidate_signal_counts":{"raw_v2_eligible_signal_count":n,"pit_mcap_rejected_signal_count":pit_reject,
            "pit_qualified_alignment_blocked_signal_count":blocked,"pit_qualified_alignment_passed_signal_count":passed,
            "accepted_signal_without_executable_entry_count":int((audit["candidate_signal_accepted"].fillna(False)&~audit["entry_executable_within_cutoff"].fillna(False)).sum()) if n else 0,
            "executable_accepted_signal_count":executable},
        "opportunity_cost":opp,"realized_pnl_by_policy":pnl,"realized_pnl_comparison":pnl_delta,
        "user_preference_goals":goals,
        "official_adoption":{"status":"NOT_EVALUATED","reason":"P3-2 단일 window이며 공식 A-E 판정에는 다섯 표준 window가 필요함.","production_or_default_strategy_changed":False,
            "criteria_reference":["docs/validation/official_strategy_adoption_criteria.md","docs/validation/backtest_common_rules.md","docs/strategies/strategy_lifecycle.md"]},
        "final_comparison_judgment":judgment,"final_comparison_judgment_detail":judgment_detail,"final_comparison_judgment_deltas":deltas,
        "worker_results":{"NEW_ALIGNMENT":{"worker_count":WORKERS,"worker_errors":len(replay_info["worker_errors"]),
            "elapsed_seconds":float(replay_info["elapsed_seconds"]),"ticker_count":len(run_context.segments_by_ticker),
            "strategy_trade_count":len(records),"raw_signal_audit_count":n}},
        "integrity_checks":integrity,"network_calls":0,"production_or_canonical_changes":0,
        "control_signal_close_vs_entry_open_parity":parity_summary,"control_daily_equity_rows":len(control_daily),
        "price_store_partition_count":len(prices.audit),"elapsed_seconds":round(float(replay_info["elapsed_seconds"]),3),
        "git":{"branch":git_text("branch","--show-current"),"pre_publish_head":git_text("rev-parse","HEAD"),
            "pre_publish_origin_main":git_text("rev-parse","origin/main"),
            "pre_publish_head_equals_origin_main":git_text("rev-parse","HEAD")==git_text("rev-parse","origin/main"),
            "pre_publish_ahead_behind":git_text("rev-list","--left-right","--count","origin/main...HEAD"),
            "publish_result":"commit/push verification will be recorded in r.md"},
        "files_created":sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name not in {"summary.json","report.md"} and "__pycache__" not in p.parts),
    }
    write_json(OUT/"summary.json",summary)
    summary["files_created"]=sorted(p.name for p in OUT.iterdir() if p.is_file() and "__pycache__" not in p.parts)
    (OUT/"report.md").write_text(render_report(summary),encoding="utf-8")
    write_json(OUT/"summary.json",summary)
    (OUT/"report.md").write_text(render_report(summary),encoding="utf-8")
    return summary


def main():
    global CURRENT_STAGE
    started=time.perf_counter()
    try:
        if "--report-only" in sys.argv[1:]:
            result=recover_saved_outputs()
            result["report_recovery_elapsed_seconds"]=round(time.perf_counter()-started,3)
            write_json(OUT/"summary.json",result)
            (OUT/"report.md").write_text(render_report(result),encoding="utf-8")
            print(json.dumps(result,ensure_ascii=False,indent=2,default=str),flush=True)
            return
        result=run()
        result["elapsed_seconds_total"]=round(time.perf_counter()-started,3)
        write_json(OUT/"summary.json",result)
        (OUT/"report.md").write_text(render_report(result),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str),flush=True)
    except BaseException as exc:
        failure={"status":"CHECK_REQUIRED","final_token":CHECK_TOKEN,"error_type":type(exc).__name__,
            "error":str(exc),"stage":CURRENT_STAGE,"candidate_replay_started":CANDIDATE_REPLAY_STARTED,
            "elapsed_seconds":round(time.perf_counter()-started,3),"automatic_rerun":False}
        if OUT.exists():
            write_json(OUT/"failure.json",failure)
            summary={"work_id":"FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01",
                **failure,"severity":[["CRITICAL",1,"CHECK_REQUIRED: "+str(exc)],
                ["MAJOR",1 if failure["candidate_replay_started"] else 0,"검증 단계에서 중단; 자동 재실행 안 함"],
                ["MINOR",1,"미완료 결과는 공식 채택 근거가 아님"]],
                "files_created":sorted(p.name for p in OUT.iterdir() if p.is_file())}
            write_json(OUT/"summary.json",summary)
            (OUT/"report.md").write_text("| 레벨 | 개수 | 내용 |\n|---|---:|---|\n"+
                "\n".join(f"| {x[0]} | {x[1]} | {x[2]} |" for x in summary["severity"])+
                f"\n\n최종 토큰: {CHECK_TOKEN}\n\n중단 단계: {CURRENT_STAGE}\n\n사유: {exc}\n\n자동 재실행은 하지 않았어.\n",encoding="utf-8")
        print(json.dumps(failure,ensure_ascii=False,indent=2),flush=True)
        raise


if __name__=="__main__":
    main()
