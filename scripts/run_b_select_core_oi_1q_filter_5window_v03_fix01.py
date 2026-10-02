#!/usr/bin/env python3
"""B Select Core OI 1Q filter V03 FIX01: PRE_XBRL gate removal and metric contract.

The V03 rule is unchanged.  Two reporting/evaluation defects are corrected:

* MAJOR A — the ``entry_signal_date < 2016-01-01`` PRE_XBRL date gate is removed.
  Every signal is evaluated from the periodic reports actually filed by its
  entry date; fail-closed canonical periodization outcomes are kept.
* MAJOR B — performance uses the certified Select Core contract as PRIMARY:
  resolved terminal = realized gross + exact ``effective_end`` close gross mark,
  UNRESOLVED excluded (official_validation_v01).  Realized-only is SECONDARY.

Stages run separately, like V03: ``--stage evaluate`` then ``--stage backtest``.
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
from trend_scanner.backtest import b_select_core_oi_1q_v03 as rule  # noqa: E402
from trend_scanner.backtest.b_select_core_oi_1q_pit import evaluate_pit_signals  # noqa: E402
from trend_scanner.backtest.b_select_core_oi_1q_v03 import FAIL, PASS, UNAVAILABLE  # noqa: E402

runner = v3.runner
base = v3.base
STUDY_ID = "B_SELECT_CORE_OI_1Q_FILTER_5WINDOW_V03_FIX01"
OUTPUT_ROOT = Path("artifacts/strategies/b_select_core_v1/research/oi_1q_filter_5window_v03_fix01")
V03_ROOT = v3.OUTPUT_ROOT
FIRST_FISCAL_YEAR = 2013
WINDOW_IDS = v3.WINDOW_IDS
COMPARE_COLUMNS = ("oi_status", "oi_reason", "latest_quarter", "latest_quarter_first_rcept_dt",
                   "current_operating_income", "prior_operating_income", "current_source_rcept_dt",
                   "prior_source_rcept_dt", "rule_branch", "fail_reasons")


# ---------------------------------------------------------------- evaluate

def evaluate_fundamentals(candidates: list[dict[str, Any]],
                          min_operating_income_krw: int = rule.OPERATING_INCOME_MIN_KRW) -> pd.DataFrame:
    """FIX01 PIT evaluation; the implementation lives in ``b_select_core_oi_1q_pit``."""

    return evaluate_pit_signals(
        candidates, repo_root=ROOT, min_operating_income_krw=min_operating_income_krw,
        first_fiscal_year=FIRST_FISCAL_YEAR, build_as_of=v3.FUNDAMENTALS_BUILD_AS_OF,
        network_errors=(v3.NetworkBlocked,), progress=True,
    )


def reaudit_class(row: Mapping[str, Any]) -> str:
    status, reason = row["oi_status"], str(row["oi_reason"])
    detail = str(row.get("blocking_detail") or "")
    if status == PASS:
        return "AVAILABLE_PASS"
    if status == FAIL:
        return "AVAILABLE_FAIL"
    if "NON_STANDARD_FISCAL_PERIOD" in detail:
        return "UNAVAILABLE_NONSTANDARD_CONTEXT"
    if reason in {"NO_PERIODIC_REPORT_FILED"} or detail == "NO_OBSERVATION" \
            or reason.startswith("REGISTRY_CACHE_UNAVAILABLE"):
        return "TRULY_UNAVAILABLE"
    return f"AUTHORITY_{reason}"


def _same(a: Any, b: Any) -> bool:
    na, nb = v3._num(a), v3._num(b)
    if na is not None or nb is not None:
        return na is not None and nb is not None and abs(na - nb) <= 1e-6
    return str(a if a is not None and a == a else "") == str(b if b is not None and b == b else "")


def stage_evaluate(output: Path) -> None:
    start = v3._git_start((OUTPUT_ROOT.as_posix(),))
    if (rule.OPERATING_INCOME_MIN_KRW, rule.YOY_MIN_NUMERATOR, rule.YOY_MIN_DENOMINATOR) != (2_000_000_000, 101, 100):
        raise RuntimeError("V03 thresholds changed")
    loader, proof = v3.make_projected_authority_loader()
    base._load_authorities = loader
    resolved, window = runner._resolve_window(ROOT, "P1")
    events, _, blocked, provenance = v3.prepare_inputs(resolved)
    if blocked:
        raise RuntimeError("Pattern B authority discontinuity present")
    candidates = v3.select_core_candidates(events)
    with v3.network_guard():
        frame = evaluate_fundamentals(candidates)
    audit = v3.audit_evaluations(frame)
    old = pd.read_csv(ROOT / V03_ROOT / v3.EVALUATION_FILE, dtype={"ticker": "string", "isu_cd": "string"})
    key = ["ticker", "isu_cd", "entry_signal_date"]
    merged = old.merge(frame, on=key, how="outer", suffixes=("_v03", "_fix01"), indicator=True, validate="one_to_one")
    if not merged["_merge"].eq("both").all():
        raise RuntimeError("FIX01 evaluation keys differ from V03")
    target = merged["oi_reason_v03"].eq("PRE_XBRL_ERA")
    changed_other = []
    for row in merged.loc[~target].to_dict("records"):
        diffs = [c for c in COMPARE_COLUMNS if not _same(row[f"{c}_v03"], row[f"{c}_fix01"])]
        if diffs:
            changed_other.append({**{k: row[k] for k in key}, "changed_columns": "|".join(diffs)})
    reaudit = merged.loc[target, key + ["oi_status_fix01", "oi_reason_fix01", "latest_quarter_fix01",
                                        "latest_quarter_first_rcept_dt_fix01", "current_operating_income_fix01",
                                        "prior_operating_income_fix01", "yoy_pct_fix01", "rule_branch_fix01",
                                        "fail_reasons_fix01", "blocking_detail"]].copy()
    reaudit.columns = [c.replace("_fix01", "") for c in reaudit.columns]
    reaudit["reaudit_class"] = [reaudit_class(row) for row in reaudit.to_dict("records")]
    reaudit["v03_group"] = np.select(
        [reaudit["entry_signal_date"] < "2015-05-15", reaudit["entry_signal_date"] < "2016-01-01"],
        ["V03_TRULY_CANDIDATE_9", "V03_DATE_GATED_13"], "V03_RELABELED_2016_14")
    output.mkdir(parents=True, exist_ok=False)
    frame.to_csv(output / v3.EVALUATION_FILE, index=False)
    reaudit.to_csv(output / "pre_xbrl_reaudit.csv", index=False)
    pd.DataFrame(changed_other, columns=[*key, "changed_columns"]).to_csv(output / "non_target_evaluation_changes.csv", index=False)
    v3._write_json(output / "oi_evaluation_metadata.json", {
        "study_id": STUDY_ID,
        "stage": "evaluate",
        "starting_git": start,
        "window_superset": window,
        "candidate_count": len(candidates),
        "status_counts": frame["oi_status"].value_counts().to_dict(),
        "reason_counts": frame["oi_reason"].value_counts().to_dict(),
        "v03_status_counts": old["oi_status"].value_counts().to_dict(),
        "pre_xbrl_reaudit_counts": reaudit["reaudit_class"].value_counts().to_dict(),
        "non_target_changed_rows": len(changed_other),
        "integrity": audit,
        "authority_projection": proof,
        "first_fiscal_year": FIRST_FISCAL_YEAR,
        "date_gate": "removed",
        "thresholds": {"operating_income_min_krw": rule.OPERATING_INCOME_MIN_KRW,
                       "yoy_min": f"{rule.YOY_MIN_NUMERATOR}/{rule.YOY_MIN_DENOMINATOR}"},
        "network_guard": "socket connect blocked during evaluation",
        "evaluation_sha256": v3._sha256(output / v3.EVALUATION_FILE),
    })
    print(json.dumps({"status": frame["oi_status"].value_counts().to_dict(),
                      "reaudit": reaudit["reaudit_class"].value_counts().to_dict(),
                      "non_target_changed": len(changed_other), "integrity": audit}, ensure_ascii=False))


# ---------------------------------------------------------------- metrics

def resolved_value(row: Mapping[str, Any], period_end: str) -> float | None:
    """PRIMARY per-trade value: realized gross, else exact effective_end close mark, else UNRESOLVED."""

    status = str(row.get("trade_status"))
    if status == "REALIZED":
        value = v3._num(row.get("gross_return_pct"))
        if value is None:
            raise RuntimeError("realized trade lacks gross return")
        return value
    if status != "OPEN_AT_CUTOFF":
        raise RuntimeError(f"unexpected trade status {status}")
    valuation = str(row.get("valuation_status"))
    if valuation == "MARKED_EXACT_CUTOFF_CLOSE":
        if str(row.get("cutoff_valuation_date"))[:10] != period_end:
            raise RuntimeError("open mark is not the exact effective_end close")
        value = v3._num(row.get("mark_to_cutoff_gross_return_pct"))
        if value is None:
            raise RuntimeError("exact mark lacks gross return")
        return value
    if valuation == "UNRESOLVED":
        return None
    raise RuntimeError(f"unknown valuation status {valuation}")


def _distribution(values: list[float]) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    n = len(array)
    result: dict[str, Any] = {
        "n": n,
        "mean_pct": float(array.mean()) if n else None,
        "median_pct": float(np.median(array)) if n else None,
        "win_rate_pct": float((array > 0).mean() * 100) if n else None,
        "loss_rate_pct": float((array < 0).mean() * 100) if n else None,
        "worst_pct": float(array.min()) if n else None,
        "p10_pct": float(np.percentile(array, 10)) if n else None,
    }
    for threshold in (20, 50, 100):
        count = int((array >= threshold).sum()) if n else 0
        result[f"ge_{threshold}_count"] = count
        result[f"ge_{threshold}_rate_pct"] = count / n * 100 if n else None
    return result


def metrics(trades: list[dict[str, Any]], period_end: str) -> dict[str, dict[str, Any]]:
    realized = [row for row in trades if str(row.get("trade_status")) == "REALIZED"]
    opened = [row for row in trades if str(row.get("trade_status")) == "OPEN_AT_CUTOFF"]
    resolved = [resolved_value(row, period_end) for row in trades]
    exact = sum(1 for row, value in zip(trades, resolved)
                if str(row.get("trade_status")) == "OPEN_AT_CUTOFF" and value is not None)
    unresolved = sum(value is None for value in resolved)
    holding = [h for h in (v3._num(row.get("holding_krx_sessions")) for row in trades) if h is not None]
    common = {
        "filled_count": len(trades), "realized_count": len(realized), "open_count": len(opened),
        "exact_open_mark_count": exact, "unresolved_count": unresolved,
        "mean_holding_sessions_filled": float(np.mean(holding)) if holding else None,
        "median_holding_sessions_filled": float(np.median(holding)) if holding else None,
    }
    primary = {"basis": "PRIMARY_RESOLVED_TERMINAL", **common,
               **_distribution([value for value in resolved if value is not None])}
    secondary = {"basis": "SECONDARY_REALIZED_ONLY", **common,
                 **_distribution([float(row["gross_return_pct"]) for row in realized])}
    return {"PRIMARY": primary, "SECONDARY": secondary}


def retention(control: list[dict[str, Any]], test: list[dict[str, Any]], evaluations: Mapping[tuple[str, str, str], Mapping[str, Any]],
              period_end: str) -> dict[str, Any]:
    """Retention on the PRIMARY basis (resolved terminal value per trade)."""

    test_keys = {v3._key(row) for row in test}
    control_keys = {v3._key(row) for row in control}
    values = {v3._key(row): resolved_value(row, period_end) for row in control}

    def reason(key: tuple[str, str, str]) -> str:
        status = evaluations[key]["oi_status"]
        return {FAIL: "FILTER_FAIL", UNAVAILABLE: "UNAVAILABLE"}.get(status, f"OTHER_{status}")

    winners = [key for key, value in values.items() if value is not None and value >= 50]
    losers = [key for key, value in values.items() if value is not None and value < 0]
    shared = control_keys & test_keys
    return {
        "basis": "PRIMARY_RESOLVED_TERMINAL",
        "control_trade_count": len(control_keys), "test_trade_count": len(test_keys),
        "shared_trade_count": len(shared), "test_only_trade_count": len(test_keys - control_keys),
        "retention_rate_pct": len(shared) / len(control_keys) * 100 if control_keys else None,
        "removed_trade_count": len(control_keys - test_keys),
        "removed_by_reason": dict(Counter(reason(key) for key in control_keys - test_keys)),
        "control_unresolved_count": sum(value is None for value in values.values()),
        "control_ge50_count": len(winners),
        "control_ge50_kept": sum(key in test_keys for key in winners),
        "control_ge50_retention_pct": sum(key in test_keys for key in winners) / len(winners) * 100 if winners else None,
        "control_ge50_removed_by_reason": dict(Counter(reason(key) for key in winners if key not in test_keys)),
        "control_loss_count": len(losers),
        "control_loss_kept": sum(key in test_keys for key in losers),
        "control_loss_removed": sum(key not in test_keys for key in losers),
        "control_loss_removal_pct": sum(key not in test_keys for key in losers) / len(losers) * 100 if losers else None,
        "control_loss_removed_by_reason": dict(Counter(reason(key) for key in losers if key not in test_keys)),
        "overall_removal_pct": len(control_keys - test_keys) / len(control_keys) * 100 if control_keys else None,
    }


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 1:
        return []
    frame = pd.read_csv(path, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    return frame.replace({np.nan: None}).to_dict("records")


def _ledger_identical(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    old_by = {v3._key(row): row for row in old}
    new_by = {v3._key(row): row for row in new}
    field_diffs = 0
    for key in set(old_by) & set(new_by):
        for field in ("entry_execution_date", "exit_execution_date", "trade_status", "gross_return_pct",
                      "mark_to_cutoff_gross_return_pct", "valuation_status"):
            if not _same(old_by[key].get(field), new_by[key].get(field)):
                field_diffs += 1
    return {"old_count": len(old_by), "new_count": len(new_by), "old_only": len(set(old_by) - set(new_by)),
            "new_only": len(set(new_by) - set(old_by)), "field_diffs": field_diffs,
            "identical": len(set(old_by) ^ set(new_by)) == 0 and field_diffs == 0}


# ---------------------------------------------------------------- backtest

def stage_backtest(output: Path) -> None:
    started = time.time()
    start = v3._git_start((OUTPUT_ROOT.as_posix(),))
    eval_meta = v3._json(output / "oi_evaluation_metadata.json")
    if v3._sha256(output / v3.EVALUATION_FILE) != eval_meta["evaluation_sha256"]:
        raise RuntimeError("frozen FIX01 evaluation changed after review")
    if (output / "summary.json").exists():
        raise RuntimeError("refusing to rerun: FIX01 summary exists")
    evaluations = pd.read_csv(output / v3.EVALUATION_FILE, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    eval_by_key = {v3._key(row): row for row in evaluations.replace({np.nan: None}).to_dict("records")}
    old_eval = pd.read_csv(ROOT / V03_ROOT / v3.EVALUATION_FILE, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    old_by_key = {v3._key(row): row for row in old_eval.replace({np.nan: None}).to_dict("records")}
    loader, proof = v3.make_projected_authority_loader()
    base._load_authorities = loader
    excluded = v3.current_exclusions()
    if runner.WORKERS != 10:
        raise RuntimeError("worker count is not 10")
    group_rows, retention_rows, window_rows, integrity_rows, before_after_rows = [], [], [], [], []
    for window_id in WINDOW_IDS:
        resolved, window = runner._resolve_window(ROOT, window_id)
        start_day, end_day, support = window["effective_start"], window["effective_end"], window["execution_support"]
        events, samples, blocked, provenance = v3.prepare_inputs(resolved)
        if blocked:
            raise RuntimeError(f"{window_id}: authority discontinuity")
        intervals_by_component = provenance.pop("intervals_by_component")
        control_candidates = v3.select_core_candidates(events)
        if any(v3._key(row) not in eval_by_key for row in control_candidates):
            raise RuntimeError(f"{window_id}: candidate without frozen evaluation")
        test_candidates = [row for row in control_candidates if eval_by_key[v3._key(row)]["oi_status"] == PASS]
        tickers = sorted({row["ticker"] for row in control_candidates})
        daily, ticker_audit, _ = runner._load_prices(ROOT, tickers, start_day, support)
        if sum(int(item.get("silent_inner_drop_count", 0) or 0) for item in ticker_audit.values()):
            raise RuntimeError(f"{window_id}: Repository V2 silent inner drops")
        _, trading_dates, _ = base._load_authorities(ROOT)
        study = f"{STUDY_ID}_{window_id.replace('-', '_')}"
        print(f"{window_id}: CONTROL {len(control_candidates)} signals, TEST {len(test_candidates)} PASS signals", flush=True)
        control, control_events, _ = runner._simulate_scenario(
            "CONTROL", control_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        test, test_events, _ = runner._simulate_scenario(
            "TEST", test_candidates, samples, daily, intervals_by_component,
            trading_dates, start_day, end_day, support, study)
        validation_control = v3.et5._validate_trades(window_id, control, control_events, events, trading_dates, start_day, end_day, support)
        validation_test = v3.et5._validate_trades(window_id, test, test_events, events, trading_dates, start_day, end_day, support)
        parity = v3.control_parity(window_id, control, excluded)
        non_pass = sum(eval_by_key[v3._key(row)]["oi_status"] != PASS for row in test)
        if non_pass:
            raise RuntimeError(f"{window_id}: TEST admitted non-PASS entries")
        if any(v3._identity(row) in excluded for row in control + test):
            raise RuntimeError(f"{window_id}: excluded identity traded")
        relative = window_id.lower().replace("-", "_")
        old_control = _read_ledger(ROOT / V03_ROOT / relative / "control_trade_ledger.csv")
        old_test = _read_ledger(ROOT / V03_ROOT / relative / "test_trade_ledger.csv")
        control_vs_v03 = _ledger_identical(old_control, control)
        test_vs_v03 = _ledger_identical(old_test, test)
        available = [row for row in control if eval_by_key[v3._key(row)]["oi_status"] in {PASS, FAIL}]
        old_available = [row for row in old_control if old_by_key[v3._key(row)]["oi_status"] in {PASS, FAIL}]
        groups = (("CONTROL", control), ("AVAILABLE_CONTROL", available), ("TEST", test),
                  ("V03_AVAILABLE_CONTROL", old_available), ("V03_TEST", old_test))
        for name, trades in groups:
            for basis, values in metrics(trades, end_day).items():
                group_rows.append({"window": window_id, "group": name, **values})
        ret = retention(control, test, eval_by_key, end_day)
        old_ret = retention(old_control, old_test, old_by_key, end_day)
        retention_rows.append({"window": window_id, "version": "FIX01", **ret})
        retention_rows.append({"window": window_id, "version": "V03_RECOMPUTED_PRIMARY", **old_ret})
        status = Counter(eval_by_key[v3._key(row)]["oi_status"] for row in control_candidates)
        old_status = Counter(old_by_key[v3._key(row)]["oi_status"] for row in control_candidates)
        window_rows.append({
            "window": window_id, "effective_start": start_day, "effective_end": end_day, "execution_support": support,
            "control_candidate_signals": len(control_candidates),
            **{f"fix01_{k.lower()}": status.get(k, 0) for k in (PASS, FAIL, UNAVAILABLE, rule.BASIS_OR_CURRENCY_MISMATCH)},
            **{f"v03_{k.lower()}": old_status.get(k, 0) for k in (PASS, FAIL, UNAVAILABLE, rule.BASIS_OR_CURRENCY_MISMATCH)},
            "control_trades": len(control), "test_trades": len(test), "v03_test_trades": len(old_test),
            "control_parity_exact": parity["exact"],
            "control_identical_to_v03": control_vs_v03["identical"],
            "test_identical_to_v03": test_vs_v03["identical"],
        })
        integrity_rows.append({
            "window": window_id,
            **{f"parity_{k}": (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in parity.items()},
            "control_vs_v03": json.dumps(control_vs_v03), "test_vs_v03": json.dumps(test_vs_v03),
            "test_non_pass_entries": non_pass,
            "control_validation": json.dumps(validation_control), "test_validation": json.dumps(validation_test),
        })
        before_after_rows.append({"window": window_id,
                                  "test_added_keys": "|".join(sorted("/".join(k) for k in {v3._key(r) for r in test} - {v3._key(r) for r in old_test})),
                                  "test_removed_keys": "|".join(sorted("/".join(k) for k in {v3._key(r) for r in old_test} - {v3._key(r) for r in test}))})
        out = output / relative
        out.mkdir(parents=True, exist_ok=False)
        cols = ["ticker", "isu_cd", "entry_signal_date", "oi_status", "oi_reason", "latest_quarter",
                "current_operating_income", "prior_operating_income", "yoy_pct", "rule_branch"]
        for name, trades in (("control", control), ("test", test)):
            ledger = pd.DataFrame(trades)
            if len(ledger):
                ledger = ledger.merge(evaluations[cols], on=cols[:3], how="left", validate="one_to_one")
                ledger["primary_resolved_value_pct"] = [resolved_value(row, end_day) for row in ledger.replace({np.nan: None}).to_dict("records")]
            ledger.to_csv(out / f"{name}_trade_ledger.csv", index=False)
        pd.DataFrame(test_events).to_csv(out / "test_entry_signal_ledger.csv", index=False)
        print(json.dumps({"window": window_id, "control": len(control), "test": len(test), "parity": parity["exact"],
                          "control_eq_v03": control_vs_v03["identical"], "test_eq_v03": test_vs_v03["identical"]}), flush=True)
        if not parity["exact"]:
            v3._write_json(output / "parity_failure.json", {"window": window_id, "parity": parity})
            raise RuntimeError(f"{window_id}: CONTROL parity failed")
    pd.DataFrame(group_rows).to_csv(output / "group_metrics.csv", index=False)
    pd.DataFrame(retention_rows).to_csv(output / "retention.csv", index=False)
    pd.DataFrame(window_rows).to_csv(output / "window_signal_summary.csv", index=False)
    pd.DataFrame(integrity_rows).to_csv(output / "integrity_audit.csv", index=False)
    pd.DataFrame(before_after_rows).to_csv(output / "test_set_changes_vs_v03.csv", index=False)
    v3._write_json(output / "summary.json", {
        "study_id": STUDY_ID, "starting_git": start, "workers": runner.WORKERS,
        "metric_contract": {
            "PRIMARY": "resolved terminal: realized gross + exact effective_end close gross mark; UNRESOLVED excluded from numerator and denominator (official_validation_v01 contract)",
            "SECONDARY": "realized-only gross; open positions excluded",
            "holding": "all filled trades including open, KRX sessions",
        },
        "authority_projection": proof, "evaluation_sha256": eval_meta["evaluation_sha256"],
        "windows": window_rows, "elapsed_seconds": round(time.time() - started, 1), "auto_rerun": False,
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
