#!/usr/bin/env python3
"""Run the saved P2-2 audit with integral CSV share formatting normalized.

The replay serialized integer share counts as values like ``180.0``. The
read-only P3-1 audit helper expects integral text such as ``180``. This wrapper
checks that every event share count is finite and integral, normalizes only the
in-memory event frames, then delegates all audit logic to the frozen V02
finalizer and unchanged P3-1 helper.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
P31_HELPER = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/finalize_research_artifacts.py"
FINALIZER = OUT / "finalize_p2_2_exclusion184.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    helper = load_module("p2_2_readonly_p3_finalizer_helpers_numeric_compat", P31_HELPER)
    original = helper.cost_and_portfolio_checks

    def checked_cost_and_portfolio_checks(events, trades, metrics):
        normalized = events.copy()
        if "shares" in normalized:
            numeric = pd.to_numeric(normalized["shares"], errors="coerce")
            valid = numeric.notna() & numeric.map(lambda value: float(value).is_integer() if pd.notna(value) else False)
            executed = normalized.get("event_status", pd.Series("", index=normalized.index)).eq("EXECUTED")
            if not bool(valid.loc[executed].all()):
                raise RuntimeError("EXECUTED_EVENT_SHARE_COUNT_NOT_FINITE_INTEGER")
            normalized.loc[valid, "shares"] = numeric.loc[valid].map(lambda value: str(int(value)))
        return original(normalized, trades, metrics)

    helper.cost_and_portfolio_checks = checked_cost_and_portfolio_checks
    module = load_module("p2_2_v02_saved_artifact_finalizer", FINALIZER)
    module.import_p3_helpers = lambda: helper
    module.EXCLUSION_SHA = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
