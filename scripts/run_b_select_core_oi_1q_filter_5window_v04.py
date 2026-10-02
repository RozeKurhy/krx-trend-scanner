#!/usr/bin/env python3
"""B Select Core OI 1Q filter V04: 1B threshold TEST10 and CONTROL/TEST20/TEST10 3-way.

Only the absolute operating-income floor changes (2B -> 1B KRW).  PIT,
periodization, fail-closed policy, exclusions, lifecycle and the PRIMARY
resolved-terminal metric contract are the V03 FIX01 ones.  TEST10 is replayed
independently from raw signals; TEST20 is the frozen V03 FIX01 baseline.

``--stage evaluate`` writes the TEST10 PIT evaluation (cache-only), and
``--stage backtest`` replays CONTROL and TEST10 once.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts import run_b_select_core_oi_1q_filter_5window_v03 as v3  # noqa: E402
from scripts import run_b_select_core_oi_1q_filter_5window_v03_fix01 as f1  # noqa: E402
from trend_scanner.backtest import b_select_core_oi_1q_v03 as rule  # noqa: E402
from trend_scanner.backtest.b_select_core_oi_1q_v03 import FAIL, PASS, UNAVAILABLE  # noqa: E402

runner = v3.runner
base = v3.base
STUDY_ID = "B_SELECT_CORE_OI_1Q_FILTER_5WINDOW_V04"
OUTPUT_ROOT = Path("artifacts/strategies/b_select_core_v1/research/oi_1q_filter_5window_v04")
TEST20_ROOT = f1.OUTPUT_ROOT
TEST10_MIN_KRW = 1_000_000_000
TEST20_MIN_KRW = 2_000_000_000
WINDOW_IDS = v3.WINDOW_IDS
KEY = ["ticker", "isu_cd", "entry_signal_date"]
PIT_COLUMNS = ("latest_quarter", "latest_quarter_first_rcept_dt", "prior_year_same_quarter",
               "current_operating_income", "prior_operating_income", "current_source_rcept_dt",
               "prior_source_rcept_dt", "current_fs_div", "prior_fs_div", "rule_branch", "yoy_pct",
               "company_family", "blocking_detail")


def _rule_pass(current: int, prior: int, minimum: int) -> bool:
    return current >= minimum and (prior <= 0 or 100 * current >= 101 * prior)


def audit_evaluations(frame: pd.DataFrame, minimum: int) -> dict[str, Any]:
    """V03 integrity checks with the threshold under test."""

    audit = v3.audit_evaluations(frame.assign(oi_status=frame["oi_status"].where(~frame["oi_status"].isin([PASS, FAIL]), PASS)))
    audit.pop("rule_recompute_mismatch_count", None)
    mismatch = 0
    for row in frame.to_dict("records"):
        if row["oi_status"] in {PASS, FAIL}:
            expected = _rule_pass(int(row["current_operating_income"]), int(row["prior_operating_income"]), minimum)
            mismatch += expected != (row["oi_status"] == PASS)
    audit["rule_recompute_mismatch_count"] = mismatch
    return audit


def stage_evaluate(output: Path) -> None:
    start = v3._git_start((OUTPUT_ROOT.as_posix(),))
    if (rule.OPERATING_INCOME_MIN_KRW, rule.YOY_MIN_NUMERATOR, rule.YOY_MIN_DENOMINATOR) != (TEST20_MIN_KRW, 101, 100):
        raise RuntimeError("TEST20 default thresholds changed")
    loader, proof = v3.make_projected_authority_loader()
    base._load_authorities = loader
    resolved, window = runner._resolve_window(ROOT, "P1")
    events, _, blocked, provenance = v3.prepare_inputs(resolved)
    if blocked:
        raise RuntimeError("Pattern B authority discontinuity present")
    candidates = v3.select_core_candidates(events)
    with v3.network_guard():
        frame = f1.evaluate_fundamentals(candidates, min_operating_income_krw=TEST10_MIN_KRW)
    audit = audit_evaluations(frame, TEST10_MIN_KRW)
    test20 = pd.read_csv(ROOT / TEST20_ROOT / v3.EVALUATION_FILE, dtype={"ticker": "string", "isu_cd": "string"})
    audit20 = audit_evaluations(test20, TEST20_MIN_KRW)
    merged = test20.merge(frame, on=KEY, how="outer", suffixes=("_20", "_10"), indicator=True, validate="one_to_one")
    if not merged["_merge"].eq("both").all():
        raise RuntimeError("TEST10 evaluation keys differ from TEST20")
    pit_diffs = []
    transitions: Counter[str] = Counter()
    illegal = []
    for row in merged.to_dict("records"):
        diffs = [c for c in PIT_COLUMNS if not f1._same(row[f"{c}_20"], row[f"{c}_10"])]
        if diffs:
            pit_diffs.append({**{k: row[k] for k in KEY}, "columns": "|".join(diffs)})
        s20, s10 = row["oi_status_20"], row["oi_status_10"]
        transitions[f"{s20}->{s10}"] += 1
        if s20 != s10:
            current = v3._num(row["current_operating_income_10"])
            if not (s20 == FAIL and s10 == PASS and current is not None and TEST10_MIN_KRW <= current < TEST20_MIN_KRW):
                illegal.append({k: row[k] for k in KEY})
    if pit_diffs or illegal:
        raise RuntimeError(f"TEST10 evaluation drifted beyond the threshold: pit={len(pit_diffs)} illegal={len(illegal)}")
    output.mkdir(parents=True, exist_ok=False)
    frame.to_csv(output / v3.EVALUATION_FILE, index=False)
    band = merged.loc[merged["oi_status_20"].eq(FAIL) & merged["oi_status_10"].eq(PASS), KEY + ["current_operating_income_10", "prior_operating_income_10", "yoy_pct_10", "rule_branch_10"]]
    band.to_csv(output / "new_10_to_20_signals.csv", index=False)
    v3._write_json(output / "oi_evaluation_metadata.json", {
        "study_id": STUDY_ID, "stage": "evaluate", "starting_git": start, "window_superset": window,
        "candidate_count": len(candidates),
        "test10_status_counts": frame["oi_status"].value_counts().to_dict(),
        "test20_status_counts": test20["oi_status"].value_counts().to_dict(),
        "status_transitions_20_to_10": dict(transitions),
        "new_10_to_20_signal_count": len(band),
        "pit_column_diffs": 0, "illegal_transitions": 0,
        "integrity_test10": audit, "integrity_test20_recheck": audit20,
        "thresholds": {"TEST20": TEST20_MIN_KRW, "TEST10": TEST10_MIN_KRW, "yoy_min": "101/100"},
        "authority_projection": proof,
        "exclusions": {k: v for k, v in provenance.items() if k not in {"intervals_by_component", "market_authority"}},
        "network_guard": "socket connect blocked during evaluation",
        "evaluation_sha256": v3._sha256(output / v3.EVALUATION_FILE),
        "test20_evaluation_sha256": v3._sha256(ROOT / TEST20_ROOT / v3.EVALUATION_FILE),
    })
    print(json.dumps({"test10": frame["oi_status"].value_counts().to_dict(), "transitions": dict(transitions),
                      "new_band": len(band), "integrity": audit}, ensure_ascii=False))


def stage_backtest(output: Path) -> None:
    started = time.time()
    start = v3._git_start((OUTPUT_ROOT.as_posix(),))
    meta = v3._json(output / "oi_evaluation_metadata.json")
    if v3._sha256(output / v3.EVALUATION_FILE) != meta["evaluation_sha256"]:
        raise RuntimeError("frozen TEST10 evaluation changed")
    if v3._sha256(ROOT / TEST20_ROOT / v3.EVALUATION_FILE) != meta["test20_evaluation_sha256"]:
        raise RuntimeError("TEST20 baseline evaluation changed")
    if (output / "summary.json").exists():
        raise RuntimeError("refusing to rerun: V04 summary exists")
    read = lambda path: pd.read_csv(path, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})  # noqa: E731
    eval10 = read(output / v3.EVALUATION_FILE)
    eval20 = read(ROOT / TEST20_ROOT / v3.EVALUATION_FILE)
    e10 = {v3._key(r): r for r in eval10.replace({np.nan: None}).to_dict("records")}
    e20 = {v3._key(r): r for r in eval20.replace({np.nan: None}).to_dict("records")}
    loader, proof = v3.make_projected_authority_loader()
    base._load_authorities = loader
    excluded = v3.current_exclusions()
    if runner.WORKERS != 10:
        raise RuntimeError("worker count is not 10")
    group_rows, retention_rows, window_rows, integrity_rows, cohort_rows, split_rows = [], [], [], [], [], []
    for window_id in WINDOW_IDS:
        resolved, window = runner._resolve_window(ROOT, window_id)
        start_day, end_day, support = window["effective_start"], window["effective_end"], window["execution_support"]
        events, samples, blocked, provenance = v3.prepare_inputs(resolved)
        if blocked:
            raise RuntimeError(f"{window_id}: authority discontinuity")
        intervals_by_component = provenance.pop("intervals_by_component")
        control_candidates = v3.select_core_candidates(events)
        if any(v3._key(r) not in e10 or v3._key(r) not in e20 for r in control_candidates):
            raise RuntimeError(f"{window_id}: candidate without frozen evaluation")
        test10_candidates = [r for r in control_candidates if e10[v3._key(r)]["oi_status"] == PASS]
        tickers = sorted({r["ticker"] for r in control_candidates})
        daily, ticker_audit, _ = runner._load_prices(ROOT, tickers, start_day, support)
        if sum(int(item.get("silent_inner_drop_count", 0) or 0) for item in ticker_audit.values()):
            raise RuntimeError(f"{window_id}: Repository V2 silent inner drops")
        _, trading_dates, _ = base._load_authorities(ROOT)
        study = f"{STUDY_ID}_{window_id.replace('-', '_')}"
        print(f"{window_id}: CONTROL {len(control_candidates)} signals, TEST10 {len(test10_candidates)} PASS signals", flush=True)
        control, control_events, _ = runner._simulate_scenario(
            "CONTROL", control_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        test10, test10_events, _ = runner._simulate_scenario(
            "TEST10", test10_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        val_c = v3.et5._validate_trades(window_id, control, control_events, events, trading_dates, start_day, end_day, support)
        val_t = v3.et5._validate_trades(window_id, test10, test10_events, events, trading_dates, start_day, end_day, support)
        parity = v3.control_parity(window_id, control, excluded)
        non_pass = sum(e10[v3._key(r)]["oi_status"] != PASS for r in test10)
        if non_pass:
            raise RuntimeError(f"{window_id}: TEST10 admitted non-PASS entries")
        if any(v3._identity(r) in excluded for r in control + test10):
            raise RuntimeError(f"{window_id}: excluded identity traded")
        relative = window_id.lower().replace("-", "_")
        control_fix01 = f1._read_ledger(ROOT / TEST20_ROOT / relative / "control_trade_ledger.csv")
        test20 = f1._read_ledger(ROOT / TEST20_ROOT / relative / "test_trade_ledger.csv")
        control_vs_fix01 = f1._ledger_identical(control_fix01, control)
        available = [r for r in control if e10[v3._key(r)]["oi_status"] in {PASS, FAIL}]
        if {v3._key(r) for r in available} != {v3._key(r) for r in control if e20[v3._key(r)]["oi_status"] in {PASS, FAIL}}:
            raise RuntimeError(f"{window_id}: AVAILABLE_CONTROL differs between thresholds")
        k20 = {v3._key(r) for r in test20}
        k10 = {v3._key(r) for r in test10}
        new_cohort = [r for r in test10 if e20[v3._key(r)]["oi_status"] != PASS]
        displaced = [r for r in test10 if e20[v3._key(r)]["oi_status"] == PASS and v3._key(r) not in k20]
        missing20 = [r for r in test20 if v3._key(r) not in k10]
        for name, trades in (("CONTROL", control), ("AVAILABLE_CONTROL", available), ("TEST20", test20),
                             ("TEST10", test10), ("NEW_10_TO_20", new_cohort)):
            for basis, values in f1.metrics(trades, end_day).items():
                group_rows.append({"window": window_id, "group": name, **values})
            for label, mask in (("ENTRY_BEFORE_2025_06", lambda r: str(r["entry_signal_date"]) < "2025-06-01"),
                                ("ENTRY_FROM_2025_06", lambda r: str(r["entry_signal_date"]) >= "2025-06-01")):
                subset = [r for r in trades if mask(r)]
                split_rows.append({"window": window_id, "group": name, "entry_period": label,
                                   **f1.metrics(subset, end_day)["PRIMARY"]})
        for name, trades, emap in (("TEST20", test20, e20), ("TEST10", test10, e10)):
            retention_rows.append({"window": window_id, "group": name, **f1.retention(control, trades, emap, end_day)})
        cohort_rows.append({"window": window_id, "new_10_to_20_trades": len(new_cohort),
                            "test10_pass20_trades_not_in_test20": len(displaced),
                            "test20_trades_not_in_test10": len(missing20),
                            "test20_subset_of_test10": not missing20})
        window_rows.append({
            "window": window_id, "effective_start": start_day, "effective_end": end_day, "execution_support": support,
            "control_candidate_signals": len(control_candidates),
            **{f"test10_{k.lower()}": Counter(e10[v3._key(r)]["oi_status"] for r in control_candidates).get(k, 0) for k in (PASS, FAIL, UNAVAILABLE)},
            **{f"test20_{k.lower()}": Counter(e20[v3._key(r)]["oi_status"] for r in control_candidates).get(k, 0) for k in (PASS, FAIL, UNAVAILABLE)},
            "control_trades": len(control), "test20_trades": len(test20), "test10_trades": len(test10),
            "control_parity_exact": parity["exact"], "control_identical_to_fix01": control_vs_fix01["identical"],
        })
        integrity_rows.append({
            "window": window_id,
            **{f"parity_{k}": (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in parity.items()},
            "control_vs_fix01": json.dumps(control_vs_fix01), "test10_non_pass_entries": non_pass,
            "control_validation": json.dumps(val_c), "test10_validation": json.dumps(val_t),
        })
        out = output / relative
        out.mkdir(parents=True, exist_ok=False)
        cols = KEY + ["oi_status", "oi_reason", "latest_quarter", "current_operating_income",
                      "prior_operating_income", "yoy_pct", "rule_branch"]
        for name, trades in (("control", control), ("test10", test10)):
            ledger = pd.DataFrame(trades)
            if len(ledger):
                ledger = ledger.merge(eval10[cols], on=KEY, how="left", validate="one_to_one")
                ledger["test20_oi_status"] = [e20[v3._key(r)]["oi_status"] for r in ledger.to_dict("records")]
                ledger["primary_resolved_value_pct"] = [f1.resolved_value(r, end_day) for r in ledger.replace({np.nan: None}).to_dict("records")]
            ledger.to_csv(out / f"{name}_trade_ledger.csv", index=False)
        pd.DataFrame(test10_events).to_csv(out / "test10_entry_signal_ledger.csv", index=False)
        print(json.dumps({"window": window_id, "control": len(control), "test20": len(test20), "test10": len(test10),
                          "parity": parity["exact"], "control_eq_fix01": control_vs_fix01["identical"],
                          "new_cohort": len(new_cohort), "test20_missing_in_test10": len(missing20)}), flush=True)
        if not parity["exact"]:
            v3._write_json(output / "parity_failure.json", {"window": window_id, "parity": parity})
            raise RuntimeError(f"{window_id}: CONTROL parity failed")
    for name, rows in (("group_metrics", group_rows), ("retention", retention_rows), ("window_signal_summary", window_rows),
                       ("integrity_audit", integrity_rows), ("cohort_reconciliation", cohort_rows),
                       ("entry_period_split_primary", split_rows)):
        pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False)
    v3._write_json(output / "summary.json", {
        "study_id": STUDY_ID, "starting_git": start, "workers": runner.WORKERS,
        "thresholds": {"TEST20": TEST20_MIN_KRW, "TEST10": TEST10_MIN_KRW},
        "test20_baseline": TEST20_ROOT.as_posix(),
        "metric_contract": {"PRIMARY": "resolved terminal (V03 FIX01)", "SECONDARY": "realized only"},
        "authority_projection": proof, "evaluation_sha256": meta["evaluation_sha256"],
        "windows": window_rows, "cohorts": cohort_rows,
        "elapsed_seconds": round(time.time() - started, 1), "auto_rerun": False,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("evaluate", "backtest"), required=True)
    args = parser.parse_args()
    output = ROOT / OUTPUT_ROOT
    stage_evaluate(output) if args.stage == "evaluate" else stage_backtest(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
