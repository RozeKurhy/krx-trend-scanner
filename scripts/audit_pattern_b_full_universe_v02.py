#!/usr/bin/env python3
"""Pattern B full-universe operational audit V02 (operational policy V02; audit only).

Record: docs/patterns/pattern_b/validation/full_universe_operational_audit_v02.md

Same population, identity resolution, repository, and evaluator as audit V01
(``audit_pattern_b_full_universe_v01``, reused unchanged), plus operational contract V02:

- Policy A: contiguous KOSPI <-> KOSDAQ market-transfer history is stitched per segment
  (``pattern_b_operational.history_chain`` / ``load_history``).
- Policy B: ``freshness_status`` CURRENT / STALE from the last completed weekly bar.

Data is read from ``--data-root`` (read-only); artifacts are written under this repo.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import audit_pattern_b_full_universe_v01 as v1  # noqa: E402
from trend_scanner.data.repository_v2_loader import build_production_repository_v2  # noqa: E402
from trend_scanner.data.rolling_market_data_refresh import (  # noqa: E402
    DEFAULT_ROLLING_AUTHORITY_DIR,
    RollingAuthorityError,
)
from trend_scanner.patterns import pattern_b_operational as op  # noqa: E402
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b  # noqa: E402
from trend_scanner.universe.instrument_metadata import (  # noqa: E402
    load_target_basic_info_universe,
    load_target_pit_common_tickers,
)

DEFAULT_OUT_DIR = ROOT / "artifacts/patterns/pattern_b/operational_audit_v02"
V01_DIR = ROOT / "artifacts/patterns/pattern_b/operational_audit_v01"
CODE_FILES = v1.CODE_FILES + ("src/trend_scanner/patterns/pattern_b_operational.py",)
RESULT_FIELDS = v1.RESULT_FIELDS[:6] + (
    "history_effective_from", "history_segment_count", "market_transfer_stitched",
    "history_segments", "history_stop_reason",
) + v1.RESULT_FIELDS[6:22] + (
    "freshness_status", "expected_weekly_bar",
    "active_only_evaluation_status", "active_only_pattern_b_state", "error",
)
REPLAY_FIELDS = v1.REPLAY_FIELDS + (
    "history_segments", "history_effective_from", "market_transfer_stitched", "freshness_status",
)
STITCH_ERROR_KINDS = {
    "rows outside segment": "stitched_segment_boundary_violation",
    "duplicate dates": "stitched_duplicate_date",
    "not in date order": "stitched_order_violation",
    "not from MarketDataRepositoryV2": "wrong_repository_authority_segment",
}


def _chain_text(chain: op.HistoryChain) -> str:
    return "|".join(f"{s.market}:{s.isu_cd}:{s.effective_from}~{s.effective_to}" for s in chain.segments)


def verify_chain(chain: op.HistoryChain, trading_dates: list[str]) -> bool:
    """Independent re-check that every link satisfies policy A."""
    for prev, head in zip(chain.segments, chain.segments[1:]):
        if not (prev.isu_cd == head.isu_cd and prev.state == head.state == "COMMON"
                and {prev.market, head.market} <= op.TRANSFER_MARKETS and prev.market != head.market
                and op.next_trading_date(trading_dates, prev.effective_to) == head.effective_from):
            return False
    return True


def evaluate_one(repository, identity: dict, active: dict, own_intervals: list[dict],
                 trading_dates: list[str], target: str) -> dict:
    row: dict[str, Any] = {**identity, "history_effective_from": "", "history_segment_count": 0,
                           "market_transfer_stitched": False, "history_segments": "", "history_stop_reason": "",
                           "repository_status": "", "repository_reason": "", "row_count": 0,
                           "first_daily_date": "", "last_daily_date": "", "evaluation_status": "",
                           "pattern_b_state": None, "reason_codes": "", "reason_details": "",
                           "range_36m": None, "monthly_ma24_distance": None, "range_52w": None,
                           "monthly_last_bar": "", "weekly_last_bar": "", "feature_contract_version": "",
                           "state_rule_version": "", "freshness_status": "",
                           "expected_weekly_bar": op.expected_weekly_bar(target),
                           "active_only_evaluation_status": "", "active_only_pattern_b_state": None, "error": ""}
    ticker = identity["ticker"]
    try:
        chain = op.history_chain(ticker, active, own_intervals, trading_dates)
    except op.PatternBHistoryError as exc:
        row.update(repository_status=v1.ERROR, error=f"PatternBHistoryError: {exc}", _chain_ambiguous=True)
        return row
    row.update(history_effective_from=chain.history_effective_from, history_segment_count=len(chain.segments),
               market_transfer_stitched=chain.market_transfer_stitched, history_segments=_chain_text(chain),
               history_stop_reason=chain.stop_reason, _chain_valid=verify_chain(chain, trading_dates))
    try:
        frame = op.load_history(repository, ticker, chain, target)
    except RollingAuthorityError as exc:
        if str(exc).startswith("IDENTITY_"):
            row.update(repository_status=v1.ERROR, error=f"RollingAuthorityError: {exc}")
            return row
        raise
    except op.PatternBHistoryError as exc:
        kind = next((k for m, k in STITCH_ERROR_KINDS.items() if m in str(exc)), "stitch_error")
        row.update(repository_status=v1.ERROR, error=f"PatternBHistoryError: {exc}", **{f"_{kind}": True})
        return row
    except Exception as exc:  # noqa: BLE001 - recorded as a hard error, never hidden
        row.update(repository_status=v1.ERROR, error=f"{type(exc).__name__}: {exc}")
        return row
    if frame is None:
        audit = repository.query_audit.get(ticker.zfill(6), {})
        row.update(repository_status=v1.DATA_UNAVAILABLE, repository_reason=str(audit.get("reason") or ""))
        return row
    first, last = frame.index.min(), frame.index.max()
    row.update(repository_status=v1.LOADED, row_count=len(frame),
               first_daily_date=first.date().isoformat(), last_daily_date=last.date().isoformat())
    row["_wrong_authority"] = frame.attrs.get("data_authority") != "MarketDataRepositoryV2"
    row["_boundary_violation"] = first < pd.Timestamp(chain.history_effective_from)
    row["_post_as_of"] = last > pd.Timestamp(target)
    try:
        result = evaluate_pattern_b(ticker, frame, target, name=identity["name"])
        active_only = (evaluate_pattern_b(ticker, frame.loc[identity["identity_effective_from"]:], target,
                                          name=identity["name"]) if chain.market_transfer_stitched else result)
    except Exception as exc:  # noqa: BLE001
        row.update(error=f"{type(exc).__name__}: {exc}")
        return row
    row.update(
        evaluation_status=result.evaluation_status.value, pattern_b_state=result.pattern_b_state,
        reason_codes="|".join(result.reason_codes), reason_details="|".join(result.reason_details),
        range_36m=result.range_36m, monthly_ma24_distance=result.monthly_ma24_distance,
        range_52w=result.range_52w, monthly_last_bar=result.monthly_last_bar or "",
        weekly_last_bar=result.weekly_last_bar or "",
        feature_contract_version=result.feature_contract_version,
        state_rule_version=result.state_rule_version,
        freshness_status=op.freshness_status(result.weekly_last_bar, target),
        active_only_evaluation_status=active_only.evaluation_status.value,
        active_only_pattern_b_state=active_only.pattern_b_state,
    )
    return row


def check_invariants_v02(rows: list[dict], universe: set[str]) -> dict[str, Any]:
    base = v1.check_invariants(rows, universe)
    loaded = [r for r in rows if r["repository_status"] == v1.LOADED and not r["error"]]
    extra = {
        "market_transfer_chain_ambiguity": sum(bool(r.get("_chain_ambiguous")) for r in rows),
        "stitched_segment_boundary_violation": sum(bool(r.get("_stitched_segment_boundary_violation")) for r in rows),
        "stitched_duplicate_date": sum(bool(r.get("_stitched_duplicate_date")) for r in rows),
        "stitched_order_violation": sum(bool(r.get("_stitched_order_violation")) for r in rows),
        "non_eligible_segment_stitch": sum(r.get("_chain_valid") is False for r in rows),
        "unknown_freshness_status": sum(r["freshness_status"] not in op.FRESHNESS_STATUSES for r in loaded),
        "current_with_other_weekly_bar": sum(
            r["freshness_status"] == op.CURRENT and r["weekly_last_bar"] != r["expected_weekly_bar"] for r in loaded),
        "stale_with_expected_weekly_bar": sum(
            r["freshness_status"] == op.STALE and r["weekly_last_bar"] == r["expected_weekly_bar"] for r in loaded),
    }
    zero = {**base["zero_checks"], **extra}
    return {"zero_checks": zero, "equalities": base["equalities"],
            "pass": all(v == 0 for v in zero.values()) and all(base["equalities"].values())}


def _load_v01(target: str) -> tuple[dict[str, dict], dict]:
    path = V01_DIR / target / v1.RESULTS_NAME
    if not path.exists():
        return {}, {}
    with path.open(encoding="utf-8") as fh:
        rows = {r["ticker"]: r for r in csv.DictReader(fh)}
    summary = json.loads((V01_DIR / target / v1.SUMMARY_NAME).read_text(encoding="utf-8"))
    return rows, summary


def compare_with_v01(rows: list[dict], v01_rows: dict[str, dict]) -> dict[str, Any]:
    fields = ("evaluation_status", "pattern_b_state", "range_36m", "monthly_ma24_distance", "range_52w",
              "monthly_last_bar", "weekly_last_bar")
    changed_stitched, changed_other = [], []
    for r in rows:
        old = v01_rows.get(r["ticker"])
        if old is None:
            continue
        diff = [f for f in fields if v1._fmt(r.get(f)) != old.get(f, "")]
        if diff:
            (changed_stitched if r["market_transfer_stitched"] else changed_other).append(
                {"ticker": r["ticker"], "fields": diff,
                 "v01": {f: old.get(f, "") for f in ("evaluation_status", "pattern_b_state")},
                 "v02": {f: v1._fmt(r.get(f)) for f in ("evaluation_status", "pattern_b_state")}})
    return {"compared": sum(r["ticker"] in v01_rows for r in rows),
            "changed_stitched": changed_stitched, "changed_not_stitched": changed_other}


def run(data_root: Path, target: str, out_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    before = v1.authority_fingerprint(data_root)
    v1.validate_target(data_root, target, before)
    trading_dates = sorted(v1._calendar_dates(data_root))
    universe = load_target_pit_common_tickers(data_root, target)
    basic_rows, snapshot_date = load_target_basic_info_universe(data_root, target)
    pit = json.loads((data_root / DEFAULT_ROLLING_AUTHORITY_DIR / "merged_pit_intervals.json")
                     .read_text(encoding="utf-8"))
    intervals = pit["intervals"]
    by_ticker: dict[str, list[dict]] = {}
    for iv in intervals:
        by_ticker.setdefault(str(iv["ticker"]).strip().upper(), []).append(iv)
    resolved, problems = v1.resolve_identities(universe, basic_rows, intervals, target)
    active = {t: ivs[0] for t, ivs in v1.active_intervals(intervals, target).items() if len(ivs) == 1}

    targets = sorted(resolved)
    if limit is not None:
        targets = targets[:limit]
        universe = set(targets) | {t for t in universe if t not in resolved}
    repository = build_production_repository_v2(data_root, end=target)
    rows = []
    for i, ticker in enumerate(targets, 1):
        rows.append(evaluate_one(repository, resolved[ticker], active[ticker], by_ticker[ticker],
                                 trading_dates, target))
        if i % 200 == 0:
            print(f"[{i}/{len(targets)}] {time.time() - started:.0f}s", flush=True)

    invariants = check_invariants_v02(rows, universe)
    identity_ok = not any(problems.values())

    ok_rows = [r for r in rows if r["repository_status"] == v1.LOADED and not r["error"]]
    sample = v1.replay_sample([r["ticker"] for r in ok_rows])
    replay_repo = build_production_repository_v2(data_root, end=target)
    by_row = {r["ticker"]: r for r in rows}
    mismatches = []
    for ticker in sample:
        again = evaluate_one(replay_repo, resolved[ticker], active[ticker], by_ticker[ticker], trading_dates, target)
        diff = [f for f in REPLAY_FIELDS if again[f] != by_row[ticker][f]]
        if diff:
            mismatches.append({"ticker": ticker, "fields": diff})

    after = v1.authority_fingerprint(data_root)
    v01_rows, v01_summary = _load_v01(target)
    stitched = [r for r in rows if r["market_transfer_stitched"]]
    stitched_ok = [r for r in stitched if r in ok_rows]
    with_predecessor = [r for r in rows if r["history_stop_reason"]]
    fresh = Counter((r["evaluation_status"], r["freshness_status"]) for r in ok_rows)
    summary = {
        "schema": "pattern_b_full_universe_operational_audit_v02",
        "target_as_of": target,
        "basic_info_snapshot_date": snapshot_date,
        "population_authority": "load_target_pit_common_tickers",
        "universe_count": len(universe),
        "universe_by_market": dict(Counter(r["market"] for r in resolved.values())),
        "identity": {"resolved": len(resolved), **{k: len(v) for k, v in problems.items()},
                     "problem_tickers": problems},
        "market_transfer": {
            "stitched_chain": len(stitched),
            "stitched_loaded_multi_segment": len(stitched_ok),
            "segment_count_distribution": dict(Counter(str(r["history_segment_count"]) for r in rows)),
            "stop_reasons": dict(Counter(r["history_stop_reason"] for r in with_predecessor)),
            "stitched_tickers": [
                {"ticker": r["ticker"], "segments": r["history_segments"],
                 "active_only": [r["active_only_evaluation_status"], r["active_only_pattern_b_state"]],
                 "stitched": [r["evaluation_status"], r["pattern_b_state"]]} for r in stitched_ok],
            "rejected_tickers": [
                {"ticker": r["ticker"], "stop_reason": r["history_stop_reason"],
                 "evaluation_status": r["evaluation_status"]} for r in with_predecessor],
            "ready_transitions": dict(Counter(
                f"{r['active_only_evaluation_status']}->{r['evaluation_status']}" for r in stitched_ok)),
            "state_changes": sum(r["active_only_pattern_b_state"] != r["pattern_b_state"] for r in stitched_ok),
        },
        "freshness": {
            "expected_weekly_bar": op.expected_weekly_bar(target),
            "current": sum(r["freshness_status"] == op.CURRENT for r in ok_rows),
            "stale": sum(r["freshness_status"] == op.STALE for r in ok_rows),
            "by_evaluation_status": {f"{s}+{f}": fresh[(s, f)] for s in v1.STATUSES for f in op.FRESHNESS_STATUSES},
            "stale_without_weekly_bar": sum(r["freshness_status"] == op.STALE and not r["weekly_last_bar"]
                                            for r in ok_rows),
            "stale_with_older_weekly_bar": sum(r["freshness_status"] == op.STALE and bool(r["weekly_last_bar"])
                                               for r in ok_rows),
        },
        "repository": {
            "loaded": sum(r["repository_status"] == v1.LOADED for r in rows),
            "data_unavailable": sum(r["repository_status"] == v1.DATA_UNAVAILABLE for r in rows),
            "data_unavailable_reasons": dict(Counter(
                r["repository_reason"] for r in rows if r["repository_status"] == v1.DATA_UNAVAILABLE)),
            "error": sum(r["repository_status"] == v1.ERROR for r in rows),
        },
        "hard_errors": [{"ticker": r["ticker"], "error": r["error"]} for r in rows if r["error"]],
        "distribution": v1.distribution(ok_rows),
        "distribution_by_market": {m: v1.distribution([r for r in ok_rows if r["market"] == m]) for m in v1.MARKETS},
        "invariants": invariants,
        "replay": {"sample": sample, "count": len(sample), "mismatches": mismatches},
        "v01_comparison": {**compare_with_v01(rows, v01_rows),
                           "v01_authority_after_equals_v02_before":
                               v01_summary.get("authority_after") == before if v01_summary else None},
        "authority_before": before,
        "authority_after": after,
        "authority_stable": before == after,
        "code_sha256": {p: v1._sha(ROOT / p) for p in CODE_FILES},
        "elapsed_seconds": round(time.time() - started, 1),
        "limit": limit,
    }
    summary["verdict"] = "PASS" if (
        identity_ok and invariants["pass"] and not mismatches and summary["authority_stable"]
        and len(sample) == v1.REPLAY_SIZE and limit is None
    ) else "CHECK_REQUIRED"

    target_dir = out_dir / target
    target_dir.mkdir(parents=True, exist_ok=True)
    with (target_dir / v1.RESULTS_NAME).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULT_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: v1._fmt(r.get(k)) for k in RESULT_FIELDS})
    (target_dir / v1.SUMMARY_NAME).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-as-of", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repository root that holds data/ (read-only)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="smoke test only; verdict is never PASS")
    args = parser.parse_args()
    target = pd.Timestamp(args.target_as_of).date().isoformat()
    try:
        summary = run(args.data_root.resolve(), target, args.out_dir, limit=args.limit)
    except v1.AuditCheckRequired as exc:
        raise SystemExit(f"CHECK_REQUIRED: {exc}")
    print(json.dumps({k: summary[k] for k in ("target_as_of", "universe_count", "repository", "market_transfer",
                                              "freshness", "verdict")}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
