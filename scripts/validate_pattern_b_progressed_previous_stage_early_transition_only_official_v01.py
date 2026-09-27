#!/usr/bin/env python3
"""Read-only contract recertification for saved Pattern B E/T candidate artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01 as prior  # noqa: E402

OUTPUT = Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01")
FREEZE_DOC = Path("docs/patterns/pattern_b/strategy/PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md")
STRATEGY_ID = "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01"
DISPLAY_NAME = "Pattern B E/T PROGRESSED Candidate V1"
ALLOWED = {"EARLY_TREND", "TRANSITION"}
TAILS = (("ge_30", 30.0), ("ge_50", 50.0), ("ge_100", 100.0),
         ("le_30", -30.0), ("le_40", -40.0), ("le_50", -50.0), ("le_60", -60.0))
TOLERANCE_PP = 0.1


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def js(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def yes(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def key(row: dict[str, Any]) -> tuple[str, str, str]:
    return prior._key(row)


def stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "mean_pct": None, "median_pct": None, "positive_rate_pct": None}
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    out: dict[str, Any] = {
        "n": n, "mean_pct": sum(ordered) / n, "median_pct": median,
        "positive_rate_pct": sum(v > 0 for v in ordered) * 100 / n,
    }
    for label, threshold in TAILS:
        count = sum(v >= threshold for v in ordered) if threshold > 0 else sum(v <= threshold for v in ordered)
        out[f"{label}_count"] = count
        out[f"{label}_rate_pct"] = count * 100 / n
    return out


def trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [r for r in trades if r.get("trade_status") == "REALIZED"]
    opened = [r for r in trades if r.get("trade_status") == "OPEN_AT_CUTOFF"]
    result = stats([float(r["gross_return_pct"]) for r in realized])
    holds = [float(r["holding_krx_sessions"]) for r in trades if num(r.get("holding_krx_sessions")) is not None]
    result.update({
        "filled_count": len(trades), "realized_count": len(realized), "open_count": len(opened),
        "mean_holding_sessions": sum(holds) / len(holds) if holds else None,
        "median_holding_sessions": stats(holds)["median_pct"] if holds else None,
    })
    for name, field in (("mfe", "mfe_pct"), ("mae", "mae_pct")):
        values = [float(r[field]) for r in trades if num(r.get(field)) is not None]
        result[f"mean_{name}_pct"] = stats(values)["mean_pct"]
        result[f"median_{name}_pct"] = stats(values)["median_pct"]
    return result


def terminal_metrics(trades: list[dict[str, Any]], end: str) -> dict[str, Any]:
    realized = [r for r in trades if r.get("trade_status") == "REALIZED"]
    opened = [r for r in trades if r.get("trade_status") == "OPEN_AT_CUTOFF"]
    values = [float(r["gross_return_pct"]) for r in realized]
    exact = []
    unresolved = 0
    for r in opened:
        status = r.get("valuation_status")
        if status == "MARKED_EXACT_CUTOFF_CLOSE":
            if r.get("cutoff_valuation_date") != end:
                raise ValueError("cutoff mark date differs from effective_end")
            exact.append(float(r["mark_to_cutoff_gross_return_pct"]))
        elif status == "UNRESOLVED":
            unresolved += 1
        else:
            raise ValueError(f"unexpected open valuation status: {status}")
    if len(exact) + unresolved != len(opened):
        raise ValueError("open rows do not reconcile to exact/unresolved marks")
    result = stats(values + exact)
    result.update({"realized_count": len(realized), "exact_open_mark_count": len(exact),
                   "unresolved_open_count": unresolved})
    return result


def add(checks: list[dict[str, Any]], name: str, observed: Any, expected: Any,
        ok: bool, window: str = "", detail: str = "") -> None:
    checks.append({"window": window, "check": name,
                   "observed": json.dumps(observed, ensure_ascii=False, sort_keys=True, default=str),
                   "expected": json.dumps(expected, ensure_ascii=False, sort_keys=True, default=str),
                   "status": "PASS" if ok else "FAIL", "detail": detail})


def check_realized_aggregate(checks: list[dict[str, Any]], wid: str, scenario: str,
                             calc: dict[str, Any], saved: dict[str, str], prefix: str) -> None:
    exact_fields = {
        "n": "realized_count", "filled_count": "filled_count", "realized_count": "realized_count",
        "open_count": "open_count", **{f"{x}_count": f"{x}_count" for x, _ in TAILS},
    }
    for field, metric in exact_fields.items():
        observed, expected = num(saved.get(f"{prefix}_{field}")), num(calc.get(metric))
        add(checks, f"{scenario}.{field}_exact", observed, expected,
            observed is not None and expected is not None and observed == expected, wid)
    float_fields = {
        "mean_pct": "mean_pct", "median_pct": "median_pct", "positive_rate_pct": "positive_rate_pct",
        **{f"{x}_rate_pct": f"{x}_rate_pct" for x, _ in TAILS},
        "mean_mfe_pct": "mean_mfe_pct", "median_mfe_pct": "median_mfe_pct",
        "mean_mae_pct": "mean_mae_pct", "median_mae_pct": "median_mae_pct",
    }
    for field, metric in float_fields.items():
        observed, expected = num(saved.get(f"{prefix}_{field}")), num(calc.get(metric))
        add(checks, f"{scenario}.{field}_aggregate", observed, expected,
            observed is not None and expected is not None and abs(observed - expected) <= TOLERANCE_PP,
            wid, f"tolerance={TOLERANCE_PP}pp")
    for field in ("mean_holding_sessions", "median_holding_sessions"):
        observed, expected = num(saved.get(f"{prefix}_{field}")), num(calc.get(field))
        add(checks, f"{scenario}.{field}_all_filled", observed, expected,
            observed is not None and expected is not None and abs(observed - expected) <= 1e-8,
            wid, "all filled rows in scenario ledger")


def check_terminal_aggregate(checks: list[dict[str, Any]], wid: str, scenario: str,
                             calc: dict[str, Any], saved: dict[str, str]) -> None:
    fields = {"n": "n", "exact_open_mark_count": "exact_open_mark_count",
              "unresolved_open_count": "unresolved_open_count",
              **{f"{x}_count": f"{x}_count" for x, _ in TAILS}}
    for field, metric in fields.items():
        observed, expected = num(saved.get(f"{scenario}_{field}")), num(calc.get(metric))
        add(checks, f"{scenario}.terminal_{field}_exact", observed, expected,
            observed is not None and expected is not None and observed == expected, wid)
    fields = {"mean_pct": "mean_pct", "median_pct": "median_pct", "positive_rate_pct": "positive_rate_pct",
              **{f"{x}_rate_pct": f"{x}_rate_pct" for x, _ in TAILS}}
    for field, metric in fields.items():
        observed, expected = num(saved.get(f"{scenario}_{field}")), num(calc.get(metric))
        add(checks, f"{scenario}.terminal_{field}_aggregate", observed, expected,
            observed is not None and expected is not None and abs(observed - expected) <= TOLERANCE_PP,
            wid, f"tolerance={TOLERANCE_PP}pp")


def run() -> dict[str, Any]:
    root = ROOT / prior.OUTPUT_ROOT
    out = ROOT / OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    agg = {r["window"]: r for r in rows(root / "five_window_synthesis.csv")}
    agg_terminal = {r["window"]: r for r in rows(root / "resolved_terminal_synthesis.csv")}
    root_meta = js(root / "metadata.json")
    source_paths = set(root_meta.get("source_sha256", {}))

    try:
        prior._verify_frozen(ROOT)
        add(checks, "frozen_reference_hashes", "all frozen outputs verified", "all frozen outputs verified", True)
    except Exception as exc:
        add(checks, "frozen_reference_hashes", str(exc), "all frozen outputs verified", False)
    try:
        fast = prior._load_fast_refs(ROOT)
        add(checks, "FAST_V2_saved_reference_contract", len(fast), 5, len(fast) == 5,
            detail="saved COMPLETE summaries, exact windows, official strategy ID")
    except Exception as exc:
        fast = {}
        add(checks, "FAST_V2_saved_reference_contract", str(exc), "5 valid saved summaries", False)

    try:
        _, sessions, authority = prior.runner.base._load_authorities(ROOT)
        add(checks, "local_PIT_and_calendar_authority_read", bool(sessions), True, bool(sessions))
    except Exception as exc:
        sessions, authority = [], {}
        add(checks, "local_PIT_and_calendar_authority_read", str(exc), "readable local authority files", False)

    stage_root = ROOT / "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01"
    history_path = stage_root / "candidate_signal_stage_history.csv"
    history = rows(history_path)
    history_map = {key(r): r for r in history}
    add(checks, "previous_stage_history_unique_keys", len(history_map), len(history), len(history_map) == len(history))
    stage_meta = js(stage_root / "metadata.json")
    linkage_path = ROOT / stage_meta["source_studies"]["stage_linkage"]
    linkage_sha = sha(linkage_path)
    history_sha = sha(history_path)
    add(checks, "stage_history_and_linkage_SHA", {
        "history": history_sha, "linkage": linkage_sha,
    }, {"history": "recorded stage history SHA", "linkage": stage_meta["source_studies"]["stage_linkage_sha256"]},
       history_sha == sha(history_path) and linkage_sha == stage_meta["source_studies"]["stage_linkage_sha256"])

    exclusions_path = ROOT / "artifacts/patterns/pattern_b/state_forward_return_v01/permanent_identity_exclusions.csv"
    exclusions = rows(exclusions_path)
    exclusion_ids = {(prior.runner.base.norm_ticker(r["ticker"]), prior.runner.base.norm_isu(r["isu_cd"])) for r in exclusions}
    code_exclusions = {(prior.runner.base.norm_ticker(t), prior.runner.base.norm_isu(i))
                       for t, i in prior.runner.base.PERMANENT_IDENTITY_EXCLUSIONS}
    add(checks, "permanent_exact_exclusion_identity_set", len(exclusion_ids), 43,
        len(exclusion_ids) == 43 and exclusion_ids == code_exclusions,
        detail=f"CSV SHA-256={sha(exclusions_path)}")

    result_by_window: dict[str, Any] = {}
    terminal_by_window: dict[str, Any] = {}
    for wid in prior.WINDOW_IDS:
        wkey = wid.lower().replace("-", "_")
        d = root / wkey
        meta, summary = js(d / "metadata.json"), js(d / "summary.json")
        start, end, support = prior.runner.STANDARD_WINDOW_EXPECTATIONS[wid][2:]
        resolved = prior.runner._resolve_window(ROOT, wid)[1]
        window_tuple = (resolved["effective_start"], resolved["effective_end"], resolved["execution_support"])
        add(checks, "standard_window_dates", window_tuple, (start, end, support), window_tuple == (start, end, support), wid)
        saved_tuple = (summary["window"].get("effective_start"), summary["window"].get("effective_end"),
                       summary["window"].get("execution_support"))
        add(checks, "saved_window_dates", saved_tuple, (start, end, support), saved_tuple == (start, end, support), wid)
        output_hash_ok = all((d / n).is_file() and sha(d / n) == detail.get("sha256")
                             for n, detail in meta.get("generated_files", {}).items())
        add(checks, "per_window_output_hashes", output_hash_ok, True, output_hash_ok, wid)

        market = summary["source_provenance"]["market_authority"]
        market_ok = all(market.get(k) == authority.get(k) for k in (
            "pit_frontier", "pit_content_digest", "calendar_frontier", "calendar_content_digest",
            "interval_count", "common_interval_count", "pit_sha256", "calendar_sha256"))
        add(checks, "saved_PIT_calendar_authority_identity", market_ok, True, market_ok, wid)

        provenance = summary["source_provenance"]
        prov_ok = (
            provenance["previous_stage_history_sha256"] == history_sha
            and provenance["pattern_a_linkage_source_sha256"] == linkage_sha
            and provenance["pattern_a_linkage_source_study_id"] == "PATTERN_B_DEPRESSED_ENTRY_PATTERN_A_STATE_V01"
            and provenance["permanent_exclusion_identity_count"] == 43
        )
        add(checks, "stage_linkage_PIT_and_exclusion_provenance", prov_ok, True, prov_ok, wid)

        zero_fields = (
            "new_test_previous_stage_forbidden_fill_count", "entry_after_window_end_count",
            "execution_support_new_entry_count", "future_pattern_a_input_count",
            "duplicate_trade_identity_count", "duplicate_trade_id_count",
            "lifecycle_settlement_contract_violation_count", "raw_candidate_key_mismatch_count",
            "same_isu_overlap_count", "repository_v2_silent_inner_drop_count",
            "pattern_b_authority_discontinuity_count", "carry_in_position_count",
        )
        for field in zero_fields:
            observed = summary["validations"].get(field)
            add(checks, f"saved_{field}", observed, 0, observed == 0, wid)

        ledger = rows(d / "test_trade_ledger.csv")
        opened = rows(d / "test_open_positions.csv")
        audit = rows(d / "previous_stage_audit.csv")
        spot = rows(d / "lifecycle_spot_checks.csv")
        old_dir = ROOT / prior.FROZEN_DIRS[wid]
        control = rows(old_dir / "control_trade_ledger.csv")
        frozen_test = rows(old_dir / "test_trade_ledger.csv")
        posthoc = [r for r in frozen_test if r.get("previous_pattern_a_stage") in ALLOWED]
        scenarios = {"CONTROL": control, "FROZEN_TEST": frozen_test,
                     "POSTHOC_EARLY_TRANSITION": posthoc, "NEW_TEST": ledger}
        result_by_window[wid] = {name: trade_metrics(x) for name, x in scenarios.items()}

        spot_ok = len(spot) == 30 and len({r["review_id"] for r in spot}) == 30 and all(yes(r["all_checks_pass"]) for r in spot)
        add(checks, "existing_lifecycle_spotchecks", {"rows": len(spot), "passing": sum(yes(r["all_checks_pass"]) for r in spot)},
            {"rows": 30, "passing": 30}, spot_ok, wid)

        gate_ok = len({key(r) for r in audit}) == len(audit)
        filled_ids = set()
        for r in audit:
            k = key(r)
            h = history_map.get(k)
            prev = r.get("previous_pattern_a_stage", "")
            expected_gate = "PASS_EARLY_TREND_OR_TRANSITION" if prev in ALLOWED else f"REJECT_PREVIOUS_STAGE_{prev}"
            gate_ok &= h is not None
            gate_ok &= r.get("pattern_a_stage") == "PROGRESSED"
            gate_ok &= r.get("pattern_b_entry_state") == "DEPRESSED"
            gate_ok &= r.get("new_test_gate_decision") == expected_gate
            gate_ok &= r.get("pattern_a_requested_asof") == r.get("entry_signal_date")
            gate_ok &= yes(r.get("pattern_a_lookahead_free"))
            if h:
                gate_ok &= h.get("pattern_a_stage") == r.get("pattern_a_stage")
                gate_ok &= h.get("previous_pattern_a_stage") == prev
                gate_ok &= h.get("entry_pattern_a_requested_asof") == r.get("pattern_a_requested_asof")
                gate_ok &= yes(h.get("entry_pattern_a_lookahead_free"))
            if r.get("trade_id"):
                filled_ids.add(r["trade_id"])
            if (prior.runner.base.norm_ticker(r["ticker"]), prior.runner.base.norm_isu(r["isu_cd"])) in exclusion_ids:
                gate_ok = False
        allowed_count = sum(r.get("new_test_gate_decision") == "PASS_EARLY_TREND_OR_TRANSITION" for r in audit)
        allowed_valid = allowed_count == summary["candidate_counts"]["new_test_allowed_entry_signals"]
        fill_ids = {r["trade_id"] for r in ledger}
        add(checks, "entry_gate_and_previous_stage_authority", {
            "stage_candidates": len(audit), "allowed": allowed_count, "filled_identity_count": len(filled_ids),
        }, {"stage_candidates": summary["candidate_counts"]["pattern_a_progressed_count"],
            "allowed": summary["candidate_counts"]["new_test_allowed_entry_signals"], "filled_identity_count": len(ledger)},
            gate_ok and allowed_valid and filled_ids == fill_ids, wid)

        identity = [key(r) for r in ledger]
        ids = [r["trade_id"] for r in ledger]
        excl = sum((prior.runner.base.norm_ticker(r["ticker"]), prior.runner.base.norm_isu(r["isu_cd"])) in exclusion_ids for r in ledger)
        unique_ok = len(identity) == len(set(identity)) and len(ids) == len(set(ids)) and excl == 0
        add(checks, "trade_identity_and_permanent_exclusion", {
            "rows": len(ledger), "duplicate_identity": len(identity) - len(set(identity)),
            "duplicate_trade_id": len(ids) - len(set(ids)), "excluded": excl,
        }, {"duplicate_identity": 0, "duplicate_trade_id": 0, "excluded": 0}, unique_ok, wid)

        lifecycle_ok = bool(sessions)
        by_trade = {r["trade_id"]: r for r in ledger}
        open_by_id = {r["trade_id"]: r for r in opened}
        open_match = set(open_by_id) == {r["trade_id"] for r in ledger if r["trade_status"] == "OPEN_AT_CUTOFF"}
        if open_match:
            for trade_id, op in open_by_id.items():
                for field in set(op) & set(by_trade[trade_id]):
                    open_match &= op[field] == by_trade[trade_id][field]
        overlaps = 0
        by_isu: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        support_exits = 0
        for r in ledger:
            signal, entry = r.get("entry_signal_date", ""), r.get("entry_execution_date", "")
            lifecycle_ok &= start <= signal <= end and signal < entry and entry in set(sessions) and entry <= end
            lifecycle_ok &= r.get("pattern_a_requested_asof") == signal and yes(r.get("pattern_a_lookahead_free"))
            lifecycle_ok &= r.get("entry_signal_state") == "DEPRESSED" and r.get("pattern_a_stage") == "PROGRESSED"
            lifecycle_ok &= r.get("previous_pattern_a_stage") in ALLOWED
            lifecycle_ok &= (prior.runner.base.norm_ticker(r["ticker"]), prior.runner.base.norm_isu(r["isu_cd"])) not in exclusion_ids
            expected_prefix = [prior.runner.base.norm_ticker(r["ticker"]), prior.runner.base.norm_isu(r["isu_cd"])]
            lifecycle_ok &= r.get("component_id", "").split(":")[:2] == expected_prefix
            by_isu[(expected_prefix[0], expected_prefix[1])].append(r)
            if r.get("trade_status") == "REALIZED":
                xs, xe = r.get("exit_signal_date", ""), r.get("exit_execution_date", "")
                lifecycle_ok &= bool(xs and xe and xs <= end and xs < xe and xe in set(sessions) and xe <= support and r.get("exit_signal_state") == "NORMAL")
                calculated = (float(r["exit_reference_open"]) / float(r["entry_reference_open"]) - 1) * 100
                lifecycle_ok &= math.isclose(calculated, float(r["gross_return_pct"]), rel_tol=1e-10, abs_tol=1e-8)
                is_support = xe == support and xe > end
                lifecycle_ok &= yes(r.get("window_execution_support_exit_fill")) == is_support
                support_exits += int(is_support)
            elif r.get("trade_status") == "OPEN_AT_CUTOFF":
                lifecycle_ok &= not r.get("exit_execution_date") and r.get("cutoff_date") == end
                if r.get("valuation_status") == "MARKED_EXACT_CUTOFF_CLOSE":
                    lifecycle_ok &= r.get("cutoff_valuation_date") == end and num(r.get("cutoff_close")) is not None
                    calculated = (float(r["cutoff_close"]) / float(r["entry_reference_open"]) - 1) * 100
                    lifecycle_ok &= math.isclose(calculated, float(r["mark_to_cutoff_gross_return_pct"]), rel_tol=1e-10, abs_tol=1e-8)
                else:
                    lifecycle_ok &= r.get("valuation_status") == "UNRESOLVED"
            else:
                lifecycle_ok = False
        for group in by_isu.values():
            group.sort(key=lambda r: r["entry_execution_date"])
            for a, b in zip(group, group[1:]):
                overlaps += int((a.get("exit_execution_date") or end) >= b["entry_execution_date"])
        add(checks, "execution_support_terminal_and_lifecycle_contract", {
            "rows_valid": lifecycle_ok, "open_subset_exact": open_match, "same_ISU_overlap": overlaps,
            "support_exit_count": support_exits,
        }, {"rows_valid": True, "open_subset_exact": True, "same_ISU_overlap": 0,
            "support_exit_count": summary["validations"]["execution_support_exit_fill_count"]},
            lifecycle_ok and open_match and overlaps == 0 and support_exits == summary["validations"]["execution_support_exit_fill_count"], wid)

        pkeys, nkeys = {key(r) for r in posthoc}, {key(r) for r in ledger}
        add(checks, "posthoc_new_identity_exact", {
            "posthoc": len(pkeys), "new": len(nkeys), "shared": len(pkeys & nkeys),
            "posthoc_only": len(pkeys - nkeys), "new_only": len(nkeys - pkeys),
        }, {"posthoc": len(posthoc), "new": len(ledger), "shared": len(ledger), "posthoc_only": 0, "new_only": 0},
            pkeys == nkeys, wid)

        for scenario, trades in scenarios.items():
            calc = result_by_window[wid][scenario]
            check_realized_aggregate(checks, wid, scenario, calc, agg[wid], scenario.lower())
            for field in ("mean_holding_sessions", "median_holding_sessions"):
                saved = num(summary["scenario_metrics"][scenario].get(field))
                add(checks, f"window_summary_{scenario}_{field}", saved, calc[field],
                    saved is not None and abs(saved - calc[field]) <= 1e-8, wid)

        terminal_by_window[wid] = {}
        for scenario, trades in scenarios.items():
            value = terminal_metrics(trades, end)
            terminal_by_window[wid][scenario] = value
            check_terminal_aggregate(checks, wid, scenario, value, agg_terminal[wid])

    bad_sources = []
    for rel, expected in root_meta.get("source_sha256", {}).items():
        path = ROOT / rel
        if not path.is_file() or sha(path) != expected:
            bad_sources.append(rel)
    add(checks, "root_source_SHA_references", bad_sources, [], not bad_sources,
        detail="frozen ledgers/summaries and saved FAST V2 source summaries")

    fast_rows = []
    for wid in prior.WINDOW_IDS:
        ref = fast.get(wid, {})
        new = terminal_by_window.get(wid, {}).get("NEW_TEST", {})
        fast_rows.append({
            "window": wid, "strategy_id": ref.get("strategy_id"), "display_name": "A FAST Core V2",
            "source_summary": ref.get("source_summary"), "source_sha256": ref.get("source_sha256"),
            "fast_trade_count": ref.get("trade_count"), "fast_performance_n": ref.get("performance_n"),
            "fast_mean_pct": ref.get("mean_pct"), "fast_positive_rate_pct": ref.get("positive_rate_pct"),
            "fast_median_pct": ref.get("median_pct"), "candidate_mean_pct": new.get("mean_pct"),
            "candidate_positive_rate_pct": new.get("positive_rate_pct"), "candidate_median_pct": new.get("median_pct"),
            "comparison": "UNPAIRED_REFERENCE_DIFFERENT_UNIVERSE_LIFECYCLE_TERMINAL",
        })
    fast_ok = len(fast_rows) == 5 and all(r["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02" for r in fast_rows)
    add(checks, "FAST_V2_official_strategy_identity", [r["strategy_id"] for r in fast_rows],
        ["PATTERN_A_FAST_FINAL_STRATEGY_V02"] * 5, fast_ok, detail="saved summaries only, no rerun; unpaired")

    # Required official tables.
    validation_rows = []
    terminal_rows = []
    for wid in prior.WINDOW_IDS:
        d = root / wid.lower().replace("-", "_")
        s = js(d / "summary.json")
        n = terminal_by_window[wid]["NEW_TEST"]
        m = result_by_window[wid]["NEW_TEST"]
        validation_rows.append({
            "window": wid, "effective_start": s["window"]["effective_start"], "effective_end": s["window"]["effective_end"],
            "execution_support": s["window"]["execution_support"],
            "allowed_signals": s["validations"]["new_test_candidate_count"],
            "filled": s["validations"]["new_test_filled_count"], "realized": s["validations"]["new_test_realized_count"],
            "open": s["validations"]["new_test_open_count"], "exact_open": n["exact_open_mark_count"],
            "unresolved_open": n["unresolved_open_count"], "mean_pct": n["mean_pct"],
            "positive_rate_pct": n["positive_rate_pct"], "median_pct": n["median_pct"],
            **{f"{x}_count": n[f"{x}_count"] for x, _ in TAILS},
            **{f"{x}_rate_pct": n[f"{x}_rate_pct"] for x, _ in TAILS},
            "mean_holding_sessions": m["mean_holding_sessions"], "median_holding_sessions": m["median_holding_sessions"],
            "deep_arrival_count": s["scenario_metrics"]["NEW_TEST"]["deep_arrival_count"],
            "lifecycle_spotcheck": "30/30",
            "verdict": "PASS" if not any(c["status"] == "FAIL" and c["window"] == wid for c in checks) else "CHECK_REQUIRED",
        })
        for scenario, value in terminal_by_window[wid].items():
            terminal_rows.append({"window": wid, "scenario": scenario, **value})

    output_tables = {
        "five_window_validation.csv": validation_rows,
        "terminal_comparison.csv": terminal_rows,
        "fast_core_v2_reference.csv": fast_rows,
        "integrity_audit.csv": checks,
    }
    for filename, data in output_tables.items():
        with (out / filename).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)

    failures = [c for c in checks if c["status"] != "PASS"]
    verdict = "CERTIFIED_PASS" if not failures else "CHECK_REQUIRED"
    lines = [
        "# Pattern B E/T PROGRESSED Candidate V1: 공식 검증",
        "",
        f"판정: {verdict}. 검증일: 2026-09-28.",
        f"후보 ID: {STRATEGY_ID}. 표시 이름: {DISPLAY_NAME}.",
        "검증은 저장된 원장과 metadata를 read-only로 재대조했어. lifecycle replay와 FAST V2 재실행은 하지 않았어.",
        f"무결성 확인 {len(checks)}건, 실패 {len(failures)}건. 실현/terminal aggregate 허용 오차는 ±{TOLERANCE_PP}pp이며 count와 identity는 exact 비교야.",
        "이 판정은 contract/integrity 검증이야. 성과 판정이나 production 승격을 뜻하지 않아.",
        "",
        "## NEW_TEST resolved-terminal",
        "",
        "| Window | Filled | Realized | Exact open | Unresolved | Mean | Positive | Median | -30 | -40 | -50 | -60 | Mean / median holding |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in validation_rows:
        lines.append(
            f"| {r['window']} | {r['filled']} | {r['realized']} | {r['exact_open']} | {r['unresolved_open']} | "
            f"{r['mean_pct']:.2f}% | {r['positive_rate_pct']:.2f}% | {r['median_pct']:.2f}% | "
            f"{r['le_30_count']} ({r['le_30_rate_pct']:.2f}%) | {r['le_40_count']} ({r['le_40_rate_pct']:.2f}%) | "
            f"{r['le_50_count']} ({r['le_50_rate_pct']:.2f}%) | {r['le_60_count']} ({r['le_60_rate_pct']:.2f}%) | "
            f"{r['mean_holding_sessions']:.2f} / {r['median_holding_sessions']:.1f} |"
        )
    lines += [
        "", "## FAST Core V2 saved official reference", "",
        "전략 ID PATTERN_A_FAST_FINAL_STRATEGY_V02 / A FAST Core V2. 표본·lifecycle·terminal 계약이 달라 unpaired 참고이며 우열 비교가 아니야. 재실행하지 않았어.",
        "", "| Window | FAST mean / positive / median | Candidate mean / positive / median |", "|---|---:|---:|",
    ]
    for r in fast_rows:
        lines.append(f"| {r['window']} | {r['fast_mean_pct']:.2f}% / {r['fast_positive_rate_pct']:.2f}% / {r['fast_median_pct']:.2f}% | {r['candidate_mean_pct']:.2f}% / {r['candidate_positive_rate_pct']:.2f}% / {r['candidate_median_pct']:.2f}% |")
    lines += [
        "", "## 검증 범위", "",
        "- Gate: Pattern B DEPRESSED + current Pattern A PROGRESSED + previous authoritative stage EARLY_TREND 또는 TRANSITION.",
        "- Entry/exit는 기존 lifecycle 그대로야. 저장된 체결일은 신호 이후 exact KRX session이고 Repository V2 open 행을 사용해. 기존 30건/window spotcheck가 다음 exact 종목 세션을 확인해. cutoff 이후 신규 진입은 0이고 support session은 cutoff 이전 확정 exit만 settle해.",
        "- Permanent exclusion, Pattern A stage-history authority, PIT/calendar identity, Repository V2 silent-drop summary, 30 lifecycle spotchecks/window, duplicate/overlap, exact cutoff marks와 unresolved open을 확인했어.",
        "- 세부 결과와 source SHA 연결은 integrity_audit.csv 및 metadata.json에 있어.",
        f"- 연구 산출물: {prior.OUTPUT_ROOT.as_posix()}",
        f"- Freeze 문서: {FREEZE_DOC.as_posix()}",
        "",
    ]
    if failures:
        lines += ["## CHECK_REQUIRED", ""]
        lines += [f"- {c['window'] or 'GLOBAL'} / {c['check']}: {c['detail'] or c['observed']}" for c in failures]
        lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")

    source_set = set(source_paths)
    source_set.update({
        prior.OUTPUT_ROOT.as_posix() + "/metadata.json",
        prior.OUTPUT_ROOT.as_posix() + "/five_window_synthesis.csv",
        prior.OUTPUT_ROOT.as_posix() + "/resolved_terminal_synthesis.csv",
        prior.OUTPUT_ROOT.as_posix() + "/fast_core_v2_terminal_reference.csv",
        FREEZE_DOC.as_posix(),
        history_path.relative_to(ROOT).as_posix(),
        stage_meta_path.relative_to(ROOT).as_posix() if 'stage_meta_path' in locals() else (stage_root / "metadata.json").relative_to(ROOT).as_posix(),
        linkage_path.relative_to(ROOT).as_posix(),
        exclusions_path.relative_to(ROOT).as_posix(),
        prior.runner.base.PIT_PATH.as_posix(),
        prior.runner.base.CALENDAR_PATH.as_posix(),
    })
    for wid in prior.WINDOW_IDS:
        window_key = wid.lower().replace("-", "_")
        window_prefix = (prior.OUTPUT_ROOT / window_key).as_posix()
        source_set.update(
            f"{window_prefix}/{name}"
            for name in (
                "metadata.json", "summary.json", "test_trade_ledger.csv",
                "test_open_positions.csv", "previous_stage_audit.csv",
                "lifecycle_spot_checks.csv", "posthoc_trade_set_comparison.csv",
            )
        )
    source_sha = {p: sha(ROOT / p) for p in sorted(source_set) if (ROOT / p).is_file()}
    summary = {
        "study_id": STRATEGY_ID, "display_name": DISPLAY_NAME, "certification_verdict": verdict,
        "validation_date": "2026-09-28", "certification_scope": "existing saved artifact contract/integrity",
        "read_only_existing_artifacts": True, "lifecycle_replay_performed": False, "fast_core_v2_rerun": False,
        "window_order": list(prior.WINDOW_IDS), "check_count": len(checks), "failed_check_count": len(failures),
        "failed_checks": [{"window": c["window"], "check": c["check"], "detail": c["detail"]} for c in failures],
        "aggregate_tolerance_pp": TOLERANCE_PP, "resolved_terminal_new_test": validation_rows,
        "fast_core_v2_reference_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "fast_core_v2_reference_is_unpaired": True, "source_sha256": source_sha,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    output_names = ["report.md", "summary.json", *output_tables.keys()]
    metadata = {
        "study_id": STRATEGY_ID, "certification_verdict": verdict, "validation_date": "2026-09-28",
        "read_only_existing_artifacts": True, "lifecycle_replay_performed": False,
        "validation_code_sha256": {Path(__file__).resolve().relative_to(ROOT).as_posix(): sha(Path(__file__).resolve())},
        "source_sha256": source_sha,
        "generated_files": {n: {"sha256": sha(out / n), "bytes": (out / n).stat().st_size} for n in output_names},
    }
    (out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"certification_verdict": verdict, "check_count": len(checks),
                      "failed_check_count": len(failures), "output": OUTPUT.as_posix(),
                      "failed_checks": [{"window": c["window"], "check": c["check"], "detail": c["detail"]} for c in failures]},
                     ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    # Keep the final official artifacts complete when invoking this validator
    # directly: integrity recertification is followed by the saved-artifact
    # standards and strategy-quality review (no lifecycle replay).
    from scripts.review_pattern_b_progressed_previous_et_candidate_v01 import run_review

    run_review()
