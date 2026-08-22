#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- Standalone Parity Re-Verification.

Re-runs the golden-vs-optimized parity comparison purely from artifacts
already persisted by scripts/run_backtest_engine_v01_optimized.py:

  artifacts/strategies/julia/proxy_market_cap_v01/  (golden, read-only)
  artifacts/performance/backtest_engine_v01/full_run/  (optimized evidence)

This does NOT re-run the 2,506-ticker simulation. It exists specifically so
that a bug found in the comparison logic itself (see
trend_scanner.backtest.parity) can be fixed and re-verified without paying
the full ~80 minute simulation cost again.

Requires a prior full (non --limit) run of
scripts/run_backtest_engine_v01_optimized.py to have populated
artifacts/performance/backtest_engine_v01/full_run/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.backtest.parity import compare_trade_csvs, diff_summary_dicts

GOLDEN_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"
FULL_RUN_DIR = PERF_DIR / "full_run"


def main() -> None:
    required = [
        FULL_RUN_DIR / "optimized_baseline_trades.csv",
        FULL_RUN_DIR / "optimized_julia_trades.csv",
        FULL_RUN_DIR / "optimized_b_metrics.json",
        FULL_RUN_DIR / "optimized_j_metrics.json",
        FULL_RUN_DIR / "optimized_lg_summary.json",
        FULL_RUN_DIR / "optimized_val_summary.json",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit(
            "Missing persisted optimized-run artifacts, cannot re-verify without a full run:\n"
            + "\n".join(missing)
        )

    baseline_cmp = compare_trade_csvs(GOLDEN_DIR / "baseline_v2_proxy_trades.csv", FULL_RUN_DIR / "optimized_baseline_trades.csv")
    julia_cmp = compare_trade_csvs(GOLDEN_DIR / "julia_v00_proxy_trades.csv", FULL_RUN_DIR / "optimized_julia_trades.csv")

    golden_summary = json.loads((GOLDEN_DIR / "strategy_comparison_summary.json").read_text(encoding="utf-8"))
    golden_lg = json.loads((GOLDEN_DIR / "loss_guard_recovery_summary.json").read_text(encoding="utf-8"))
    golden_val = json.loads((GOLDEN_DIR / "proxy_market_cap_validation_summary.json").read_text(encoding="utf-8"))
    opt_b_metrics = json.loads((FULL_RUN_DIR / "optimized_b_metrics.json").read_text(encoding="utf-8"))
    opt_j_metrics = json.loads((FULL_RUN_DIR / "optimized_j_metrics.json").read_text(encoding="utf-8"))
    opt_lg = json.loads((FULL_RUN_DIR / "optimized_lg_summary.json").read_text(encoding="utf-8"))
    opt_val = json.loads((FULL_RUN_DIR / "optimized_val_summary.json").read_text(encoding="utf-8"))

    baseline_metrics_diff = diff_summary_dicts(golden_summary["baseline_v2_proxy"], opt_b_metrics)
    julia_metrics_diff = diff_summary_dicts(golden_summary["julia_v00_proxy"], opt_j_metrics)
    loss_guard_cohort_diff = diff_summary_dicts(golden_lg, opt_lg)
    proxy_validation_diff = diff_summary_dicts(golden_val, opt_val)

    exact_identity = (
        baseline_cmp["exact_trade_identity"] and julia_cmp["exact_trade_identity"]
        and not baseline_metrics_diff and not julia_metrics_diff
        and not loss_guard_cohort_diff and not proxy_validation_diff
    )

    full_parity_summary = {
        "limited_smoke_test": False,
        "reverification_only": True,
        "baseline": {**{k: v for k, v in baseline_cmp.items() if k != "mismatch_examples"}, "metrics_diff": baseline_metrics_diff},
        "julia": {**{k: v for k, v in julia_cmp.items() if k != "mismatch_examples"}, "metrics_diff": julia_metrics_diff},
        "loss_guard_cohort_diff": loss_guard_cohort_diff,
        "proxy_validation_diff": proxy_validation_diff,
        "mismatch_examples": {"baseline": baseline_cmp["mismatch_examples"], "julia": julia_cmp["mismatch_examples"]},
        "overall_exact_parity": exact_identity,
    }

    (PERF_DIR / "full_parity_summary.json").write_text(json.dumps(full_parity_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(full_parity_summary, indent=2, ensure_ascii=False))

    if not exact_identity:
        raise SystemExit("PERFORMANCE_OPTIMIZATION_REJECTED: golden parity mismatch detected. See full_parity_summary.json.")


if __name__ == "__main__":
    main()
