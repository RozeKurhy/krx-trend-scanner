#!/usr/bin/env python3
"""CONTROL vs TEST20 PRIMARY return-bucket distribution from frozen V03 FIX01 ledgers.

Read-only aggregation: no replay, no fundamentals evaluation, no data refresh.
Per-trade values are the FIX01 PRIMARY resolved terminal returns (realized
gross, else exact effective_end close gross mark; UNRESOLVED excluded).
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIX01 = Path("artifacts/strategies/b_select_core_v1/research/oi_1q_filter_5window_v03_fix01")
OUTPUT = Path("artifacts/strategies/b_select_core_v1/research/oi_1q_filter_5window_v03_fix01_distribution")
WINDOWS = {"P1": ("p1", "2026-08-31"), "P2-1": ("p2_1", "2025-05-30"), "P2-2": ("p2_2", "2026-08-31"),
           "P3-1": ("p3_1", "2025-05-30"), "P3-2": ("p3_2", "2026-08-31")}
KEY = ["ticker", "isu_cd", "entry_signal_date"]
BUCKETS = (
    (">=+100%", lambda v: v >= 100),
    ("+50%~<+100%", lambda v: 50 <= v < 100),
    ("+30%~<+50%", lambda v: 30 <= v < 50),
    ("+20%~<+30%", lambda v: 20 <= v < 30),
    ("0%~<+20% (0% 제외)", lambda v: 0 < v < 20),
    ("0% EXACT", lambda v: v == 0),
    ("-15%~<0%", lambda v: -15 <= v < 0),
    ("-30%~<-15%", lambda v: -30 <= v < -15),
    ("-50%~<-30%", lambda v: -50 <= v < -30),
    ("<-50%", lambda v: v < -50),
)
THRESHOLDS = (
    (">=+20%", lambda v: v >= 20), (">=+30%", lambda v: v >= 30), (">=+50%", lambda v: v >= 50),
    (">=+100%", lambda v: v >= 100), ("<0%", lambda v: v < 0), ("<=-15%", lambda v: v <= -15),
    ("<=-30%", lambda v: v <= -30), ("<=-50%", lambda v: v <= -50), ("<=-70%", lambda v: v <= -70),
)
BOUNDARIES = (100.0, 50.0, 30.0, 20.0, 0.0, -15.0, -30.0, -50.0, -70.0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _primary(row: dict[str, Any], period_end: str) -> float | None:
    """Recompute the FIX01 PRIMARY value from raw ledger fields."""

    if row["trade_status"] == "REALIZED":
        return float(row["gross_return_pct"])
    if row["trade_status"] != "OPEN_AT_CUTOFF":
        raise RuntimeError(f"unexpected status {row['trade_status']}")
    if row["valuation_status"] == "MARKED_EXACT_CUTOFF_CLOSE":
        if str(row["cutoff_valuation_date"])[:10] != period_end:
            raise RuntimeError("mark is not the exact effective_end close")
        return float(row["mark_to_cutoff_gross_return_pct"])
    if row["valuation_status"] == "UNRESOLVED":
        return None
    raise RuntimeError(f"unknown valuation status {row['valuation_status']}")


def _load(window: str, name: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    relative, end = WINDOWS[window]
    path = ROOT / FIX01 / relative / f"{name}_trade_ledger.csv"
    frame = pd.read_csv(path, dtype={"ticker": "string", "isu_cd": "string", "entry_signal_date": "string"})
    records = frame.replace({np.nan: None}).to_dict("records")
    values = [_primary(row, end) for row in records]
    stored = [None if row.get("primary_resolved_value_pct") is None else float(row["primary_resolved_value_pct"]) for row in records]
    mismatch = sum((a is None) != (b is None) or (a is not None and not math.isclose(a, b, rel_tol=0, abs_tol=1e-9))
                   for a, b in zip(values, stored))
    frame = frame.assign(primary=values)
    info = {"path": (FIX01 / relative / f"{name}_trade_ledger.csv").as_posix(), "sha256": _sha256(path),
            "rows": len(frame), "unresolved": sum(v is None for v in values), "stored_value_mismatch": mismatch}
    if frame.duplicated(KEY).any():
        raise RuntimeError(f"duplicate trade keys in {path}")
    return frame, info


def _summary(values: np.ndarray) -> dict[str, Any]:
    n = len(values)
    out = {"n": n, "mean_pct": float(values.mean()), "median_pct": float(np.median(values)),
           "win_rate_pct": float((values > 0).mean() * 100), "loss_rate_pct": float((values < 0).mean() * 100),
           "worst_pct": float(values.min()), "p10_pct": float(np.percentile(values, 10))}
    for label, test in THRESHOLDS:
        count = int(sum(test(v) for v in values))
        out[f"{label}_count"] = count
        out[f"{label}_rate_pct"] = count / n * 100
    return out


def main() -> int:
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, check=True,
                            stdout=subprocess.PIPE, text=True).stdout.splitlines()
    unexpected = [line for line in status if not line[3:].startswith(OUTPUT.as_posix())]
    if unexpected:
        raise RuntimeError(f"unexpected worktree changes: {unexpected}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    reference = pd.read_csv(ROOT / FIX01 / "group_metrics.csv")
    (ROOT / OUTPUT).mkdir(parents=True, exist_ok=False)
    summary_rows, bucket_rows, retention_rows, checks, sources = [], [], [], [], {}
    for window, (_, end) in WINDOWS.items():
        control, c_info = _load(window, "control")
        test, t_info = _load(window, "test")
        sources[window] = {"CONTROL": c_info, "TEST20": t_info}
        control_keys = set(map(tuple, control[KEY].astype(str).values))
        test_keys = set(map(tuple, test[KEY].astype(str).values))
        if not test_keys <= control_keys:
            raise RuntimeError(f"{window}: TEST20 is not a subset of CONTROL")
        for group, frame in (("CONTROL", control), ("TEST20", test)):
            values = np.asarray([v for v in frame["primary"] if v is not None], dtype=float)
            stats = _summary(values)
            summary_rows.append({"window": window, "group": group, **stats})
            bucket_counts = {label: int(sum(test_fn(v) for v in values)) for label, test_fn in BUCKETS}
            for label, count in bucket_counts.items():
                bucket_rows.append({"window": window, "group": group, "bucket": label, "count": count,
                                    "rate_pct": count / len(values) * 100})
            ref = reference[(reference.window == window) & (reference.basis == "PRIMARY_RESOLVED_TERMINAL")
                            & (reference.group == ("CONTROL" if group == "CONTROL" else "TEST"))].iloc[0]
            diffs = {
                "n": int(ref.n) - stats["n"],
                "mean_pct": float(ref.mean_pct) - stats["mean_pct"],
                "median_pct": float(ref.median_pct) - stats["median_pct"],
                "win_rate_pct": float(ref.win_rate_pct) - stats["win_rate_pct"],
                "loss_rate_pct": float(ref.loss_rate_pct) - stats["loss_rate_pct"],
                "worst_pct": float(ref.worst_pct) - stats["worst_pct"],
                "p10_pct": float(ref.p10_pct) - stats["p10_pct"],
                "ge_20": int(ref.ge_20_count) - stats[">=+20%_count"],
                "ge_50": int(ref.ge_50_count) - stats[">=+50%_count"],
                "ge_100": int(ref.ge_100_count) - stats[">=+100%_count"],
            }
            checks.append({
                "window": window, "group": group, "bucket_sum": sum(bucket_counts.values()), "resolved_n": len(values),
                "bucket_sum_ok": sum(bucket_counts.values()) == len(values),
                "boundary_value_hits": json.dumps({str(b): int(sum(v == b for v in values)) for b in BOUNDARIES if any(v == b for v in values)}),
                "fix01_report_match": all(abs(v) < 1e-9 for v in diffs.values()),
                "fix01_diffs": json.dumps(diffs),
            })
        control_values = {tuple(map(str, k)): v for k, v in zip(control[KEY].values, control["primary"]) if v is not None}
        for label, test_fn in (*THRESHOLDS, *BUCKETS):
            members = [k for k, v in control_values.items() if test_fn(v)]
            kept = sum(k in test_keys for k in members)
            retention_rows.append({"window": window, "category": label, "control_count": len(members),
                                   "test20_kept": kept, "removed": len(members) - kept,
                                   "retention_pct": kept / len(members) * 100 if members else None,
                                   "overall_retention_pct": len(test_keys) / len(control_keys) * 100})
    pd.DataFrame(summary_rows).to_csv(ROOT / OUTPUT / "threshold_summary.csv", index=False)
    pd.DataFrame(bucket_rows).to_csv(ROOT / OUTPUT / "bucket_distribution.csv", index=False)
    pd.DataFrame(retention_rows).to_csv(ROOT / OUTPUT / "control_category_retention.csv", index=False)
    pd.DataFrame(checks).to_csv(ROOT / OUTPUT / "integrity_checks.csv", index=False)
    ok = all(c["bucket_sum_ok"] and c["fix01_report_match"] for c in checks) and \
        all(s[g]["stored_value_mismatch"] == 0 and s[g]["unresolved"] == 0 for s in sources.values() for g in s)
    (ROOT / OUTPUT / "metadata.json").write_text(json.dumps({
        "analysis": "B_SELECT_CORE_OI_1Q_V03_FIX01_CONTROL_VS_TEST20_RETURN_DISTRIBUTION",
        "head": head, "replay_performed": False, "fundamentals_reevaluated": False,
        "metric": "PRIMARY resolved terminal (V03 FIX01 contract)",
        "sources": sources, "all_checks_pass": ok,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
