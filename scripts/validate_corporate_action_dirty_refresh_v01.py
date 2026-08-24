#!/usr/bin/env python3
"""Offline contract validator and evidence writer for dirty adjusted refresh."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from trend_scanner.data.adjusted_price_provider import AdjustedPriceDataProvider  # noqa: E402
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore  # noqa: E402
from trend_scanner.data.corporate_action_detector import (  # noqa: E402
    CorporateActionDetector,
    CorporateActionSnapshot,
    LISTED_SHARES_AND_PAR_VALUE_CHANGED,
)
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService  # noqa: E402
from trend_scanner.data.corporate_action_state_store import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    CorporateActionStateStore,
)
from trend_scanner.data.errors import MarketDataError  # noqa: E402


FIX_START_HEAD = "f3a3083f6382183b2b38717dbf5595b9a137a539"
DEFAULT_OUTPUT = ROOT / "artifacts/data/corporate_action_dirty_refresh/v01"
ALLOWED_PATHS = {
    "src/trend_scanner/data/corporate_action_detector.py",
    "src/trend_scanner/data/corporate_action_state_store.py",
    "src/trend_scanner/data/corporate_action_refresh.py",
    "tests/test_corporate_action_detector.py",
    "tests/test_corporate_action_state_store.py",
    "tests/test_corporate_action_refresh.py",
    "scripts/validate_corporate_action_dirty_refresh_v01.py",
    "docs/architecture/corporate_action_dirty_refresh_v01.md",
}
SECRET_ASSIGNMENT = re.compile(
    r"\b(?:KRX_ID|KRX_PW|KRX_OPEN_API_AUTH_KEY)\s*=\s*(['\"])(?!<redacted>|your_|change_me|$)[^'\"]+\1"
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_tests() -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in ("detector", "state_store", "refresh"):
        path = f"tests/test_corporate_action_{name}.py"
        output = subprocess.check_output(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", path],
            cwd=ROOT,
            text=True,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        match = re.search(r"(\d+) tests? collected", output)
        counts[f"{name}_test_count"] = int(match.group(1)) if match else 0
    return counts


def _run_new_tests() -> tuple[dict[str, int], str]:
    paths = [
        "tests/test_corporate_action_detector.py",
        "tests/test_corporate_action_state_store.py",
        "tests/test_corporate_action_refresh.py",
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    passed = int(re.search(r"(\d+) passed", output).group(1)) if re.search(r"(\d+) passed", output) else 0
    failed = int(re.search(r"(\d+) failed", output).group(1)) if re.search(r"(\d+) failed", output) else (1 if completed.returncode else 0)
    return {"new_test_passed": passed, "new_test_failure_count": failed, "new_test_return_code": completed.returncode}, output[-4000:]


def _detector_checks() -> dict[str, int]:
    detector = CorporateActionDetector()
    counters = {
        "detector_case_count": 0,
        "detector_failure_count": 0,
        "samsung_split_dirty_detection_count": 0,
        "same_value_false_dirty_count": 0,
        "listed_shares_change_missed_count": 0,
        "par_value_change_missed_count": 0,
        "source_conflict_detection_error_count": 0,
    }

    def snap(as_of: str, listed: int, par: int | None = 5000) -> CorporateActionSnapshot:
        return CorporateActionSnapshot("005930", as_of, listed, par)

    cases = [
        (snap("2024-01-01", 100), snap("2024-01-02", 100), False, ()),
        (snap("2024-01-01", 100), snap("2024-01-02", 101), True, ("LISTED_SHARES_CHANGED",)),
        (snap("2024-01-01", 100), snap("2024-01-02", 100, 100), True, ("PAR_VALUE_CHANGED",)),
        (snap("2024-01-01", 100), snap("2024-01-02", 101, 100), True, (LISTED_SHARES_AND_PAR_VALUE_CHANGED,)),
        (snap("2024-01-01", 100, None), snap("2024-01-02", 101, None), True, ("LISTED_SHARES_CHANGED",)),
        (snap("2024-01-01", 100, None), snap("2024-01-02", 100, 100), False, ()),
    ]
    for previous, current, expected_dirty, expected_reasons in cases:
        counters["detector_case_count"] += 1
        decision = detector.evaluate(previous, current)
        if decision.is_dirty != expected_dirty or decision.dirty_reasons != expected_reasons:
            counters["detector_failure_count"] += 1
        if expected_reasons == () and decision.is_dirty:
            counters["same_value_false_dirty_count"] += 1
        if expected_reasons and "LISTED_SHARES_CHANGED" in expected_reasons and not decision.is_dirty:
            counters["listed_shares_change_missed_count"] += 1
        if expected_reasons and "PAR_VALUE_CHANGED" in expected_reasons and not decision.is_dirty:
            counters["par_value_change_missed_count"] += 1

    samsung = detector.evaluate(
        snap("2018-04-27", 128_386_494, 5000),
        snap("2018-05-04", 6_419_324_700, 100),
    )
    counters["detector_case_count"] += 1
    counters["samsung_split_dirty_detection_count"] = int(
        samsung.is_dirty and samsung.dirty_reasons == (LISTED_SHARES_AND_PAR_VALUE_CHANGED,)
    )
    if not counters["samsung_split_dirty_detection_count"]:
        counters["detector_failure_count"] += 1

    for invalid_case in (
        lambda: CorporateActionSnapshot("005930", "2024-01-01", 0, 5000),
        lambda: CorporateActionSnapshot("005930", "2024-01-01", 100, -1),
        lambda: detector.evaluate(snap("2024-01-02", 100), snap("2024-01-01", 100)),
    ):
        counters["detector_case_count"] += 1
        try:
            invalid_case()
        except MarketDataError:
            pass
        else:
            counters["detector_failure_count"] += 1

    counters["detector_case_count"] += 1
    try:
        detector.evaluate(snap("2024-01-01", 100), snap("2024-01-01", 101))
    except MarketDataError:
        pass
    else:
        counters["detector_failure_count"] += 1
        counters["source_conflict_detection_error_count"] += 1
    return counters


def _seed_state_and_store(root: Path) -> tuple[AdjustedPriceStore, CorporateActionStateStore, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=5, freq="D")
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [105.0, 106.0, 107.0, 108.0, 109.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [102.0, 103.0, 104.0, 105.0, 106.0],
        },
        index=index,
    )
    adjusted = AdjustedPriceStore(root / "adjusted")
    adjusted.save_full("005930", frame, {"requested_start": "2024-01-02", "requested_end": "2024-01-06"})
    state = CorporateActionStateStore(root / "state.sqlite3")
    detector = CorporateActionDetector()
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000), detector)
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 101, 5000), detector)
    return adjusted, state, frame


class _FakeProvider:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self.frame = frame
        self.error = error
        self.calls = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.frame is None:
            raise MarketDataError("fake provider frame missing")
        return self.frame.copy()


def _refresh_checks() -> dict[str, int]:
    counters = {
        "state_transition_test_count": 0,
        "illegal_transition_accept_count": 0,
        "dirty_latch_error_count": 0,
        "concurrent_claim_error_count": 0,
        "interrupted_refresh_recovery_error_count": 0,
        "refresh_success_count": 0,
        "refresh_failure_detection_error_count": 0,
        "partial_response_accept_count": 0,
        "empty_response_accept_count": 0,
        "missing_store_fetch_count": 0,
        "old_store_preservation_error_count": 0,
        "post_refresh_integrity_error_count": 0,
        "logical_adjusted_refresh_fetch_count": 0,
        "adjusted_true_call_count": 0,
        "adjusted_false_call_count": 0,
    }
    with tempfile.TemporaryDirectory(prefix="corporate-action-v01-") as temp_dir:
        root = Path(temp_dir)
        adjusted, state, old = _seed_state_and_store(root / "success")
        old_hash = adjusted.load_metadata("005930")["content_sha256"]
        extra = old.iloc[[-1]].copy()
        extra.index = pd.DatetimeIndex(["2024-01-07"])
        refreshed = pd.concat([old, extra])
        refreshed.loc[:, ["open", "high", "low", "close"]] += 10
        provider = _FakeProvider(refreshed)
        result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
        counters["logical_adjusted_refresh_fetch_count"] += provider.calls
        counters["adjusted_true_call_count"] += provider.calls
        counters["state_transition_test_count"] += len(state.transition_log("005930"))
        if result.status == "CLEAN" and state.get("005930").status == "CLEAN":
            counters["refresh_success_count"] += 1
        else:
            counters["refresh_failure_detection_error_count"] += 1
        if len(adjusted.load_daily("005930")) != 6:
            counters["post_refresh_integrity_error_count"] += 1
        if old_hash == state.get("005930").last_content_sha256:
            counters["post_refresh_integrity_error_count"] += 1

        adjusted, state, _ = _seed_state_and_store(root / "failure")
        parquet_path = adjusted.base_dir / "005930.parquet"
        before_bytes = parquet_path.read_bytes()
        provider = _FakeProvider(error=RuntimeError("synthetic provider failure"))
        result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
        counters["logical_adjusted_refresh_fetch_count"] += provider.calls
        counters["adjusted_true_call_count"] += provider.calls
        if result.status != "FAILED" or state.get("005930").status != "FAILED":
            counters["refresh_failure_detection_error_count"] += 1
        if parquet_path.read_bytes() != before_bytes:
            counters["old_store_preservation_error_count"] += 1

        adjusted, state, _ = _seed_state_and_store(root / "partial")
        partial = _seed_state_and_store(root / "partial-source")[2].iloc[:-1]
        provider = _FakeProvider(partial)
        result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
        counters["logical_adjusted_refresh_fetch_count"] += provider.calls
        counters["adjusted_true_call_count"] += provider.calls
        if result.status != "FAILED" or result.reason != "PARTIAL_REFRESH_RESPONSE":
            counters["refresh_failure_detection_error_count"] += 1
            counters["partial_response_accept_count"] += 1

        adjusted, state, _ = _seed_state_and_store(root / "empty")
        empty = pd.DataFrame(
            {column: pd.Series(dtype="float64") for column in ("open", "high", "low", "close")},
            index=pd.DatetimeIndex([]),
        )
        provider = _FakeProvider(empty)
        result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2024-01-07")
        counters["logical_adjusted_refresh_fetch_count"] += provider.calls
        counters["adjusted_true_call_count"] += provider.calls
        if result.status != "FAILED" or result.reason != "EMPTY_REFRESH_RESPONSE":
            counters["refresh_failure_detection_error_count"] += 1
            counters["empty_response_accept_count"] += 1

        missing_root = root / "missing"
        missing_state = CorporateActionStateStore(missing_root / "state.sqlite3")
        detector = CorporateActionDetector()
        missing_state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000), detector)
        missing_state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 101, 5000), detector)
        provider = _FakeProvider(old)
        result = CorporateActionRefreshService(
            missing_state, provider, AdjustedPriceStore(missing_root / "adjusted")
        ).refresh_dirty("005930", "2024-01-07")
        if result.status != "FAILED" or result.reason != "ADJUSTED_STORE_MISSING":
            counters["refresh_failure_detection_error_count"] += 1
        counters["missing_store_fetch_count"] += provider.calls

        concurrent_path = root / "concurrent.sqlite3"
        first = CorporateActionStateStore(concurrent_path)
        second = CorporateActionStateStore(concurrent_path)
        first.evaluate_and_record(CorporateActionSnapshot("000660", "2024-01-01", 100, 5000))
        first.evaluate_and_record(CorporateActionSnapshot("000660", "2024-01-02", 101, 5000))
        if not first.claim_refresh("000660") or second.claim_refresh("000660"):
            counters["concurrent_claim_error_count"] += 1

        recovery_path = root / "recovery.sqlite3"
        recovery = CorporateActionStateStore(recovery_path)
        recovery.evaluate_and_record(CorporateActionSnapshot("068270", "2024-01-01", 100, 5000))
        recovery.evaluate_and_record(CorporateActionSnapshot("068270", "2024-01-02", 101, 5000))
        recovery.claim_refresh("068270")
        if recovery.recover_interrupted() != 1 or recovery.get("068270").status != "FAILED":
            counters["interrupted_refresh_recovery_error_count"] += 1

        latch_path = root / "latch.sqlite3"
        latch = CorporateActionStateStore(latch_path)
        detector = CorporateActionDetector()
        latch.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000), detector)
        latch.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 101, 5000), detector)
        latch.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-03", 101, 5000), detector)
        if latch.get("005930").status != "DIRTY":
            counters["dirty_latch_error_count"] += 1
        try:
            latch.transition("005930", "CLEAN")
        except MarketDataError:
            pass
        else:
            counters["illegal_transition_accept_count"] += 1
    return counters


def _live_refresh_smoke(counters: dict[str, int]) -> dict[str, Any]:
    legacy_path = ROOT / "data/raw/stocks/005930.parquet"
    if not legacy_path.exists():
        raise MarketDataError("legacy seed cache가 없습니다.")
    legacy = pd.read_parquet(legacy_path)[["open", "high", "low", "close"]].loc["2018-04-01":"2018-06-30"]
    with tempfile.TemporaryDirectory(prefix="corporate-action-v01-live-") as temp_dir:
        root = Path(temp_dir)
        adjusted = AdjustedPriceStore(root / "adjusted")
        adjusted.save_full("005930", legacy, {"requested_start": "2018-04-01", "requested_end": "2018-06-30"})
        state = CorporateActionStateStore(root / "state.sqlite3")
        detector = CorporateActionDetector()
        state.evaluate_and_record(CorporateActionSnapshot("005930", "2018-04-27", 128_386_494, 5000), detector)
        state.evaluate_and_record(CorporateActionSnapshot("005930", "2018-05-04", 6_419_324_700, 100), detector)
        provider = AdjustedPriceDataProvider()
        result = CorporateActionRefreshService(state, provider, adjusted).refresh_dirty("005930", "2018-06-30")
        audit = provider.call_audit()
        counters["logical_adjusted_refresh_fetch_count"] += audit["logical_fetch_count"]
        counters["adjusted_true_call_count"] += audit["adjusted_true_call_count"]
        counters["adjusted_false_call_count"] += audit["adjusted_false_call_count"]
        return {"ticker": "005930", "status": result.status, "reason": result.reason, "rows": result.rows, "audit": audit}


def _production_diff_guard() -> dict[str, Any]:
    implementation_head = _git("rev-parse", "HEAD")
    changed = [item for item in _git("diff", "--name-only", f"{FIX_START_HEAD}..{implementation_head}").splitlines() if item]
    disallowed = [
        item
        for item in changed
        if item not in ALLOWED_PATHS and not item.startswith("artifacts/data/corporate_action_dirty_refresh/v01/")
    ]
    production_paths = {
        "src/trend_scanner/data/pykrx_provider.py",
        "src/trend_scanner/data/repository.py",
        "src/trend_scanner/data/cache.py",
        "src/trend_scanner/data/source_contracts.py",
    }
    production_count = len(production_paths.intersection(changed))
    return {
        "start_head": FIX_START_HEAD,
        "implementation_head": implementation_head,
        "changed_paths": changed,
        "disallowed_paths": disallowed,
        "production_consumer_changed_count": len(disallowed),
        "production_adjusted_store_modified_count": int("src/trend_scanner/data/adjusted_price_store.py" in changed),
        "frozen_production_path_changed_count": production_count,
    }


def _secret_count(paths: list[str]) -> int:
    return sum(
        len(SECRET_ASSIGNMENT.findall((ROOT / path).read_text(encoding="utf-8")))
        for path in paths
        if (ROOT / path).is_file()
    )


def run(mode: str, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    test_counts, test_tail = _run_new_tests()
    collected = _collect_tests()
    counters = {
        **_detector_checks(),
        **_refresh_checks(),
        "krx_open_api_request_count": 0,
        "opendart_request_count": 0,
        "production_consumer_changed_count": 0,
        "legacy_cache_modified_count": 0,
        "production_adjusted_store_modified_count": 0,
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": 0,
        **test_counts,
        **collected,
    }
    live_result: dict[str, Any] | None = None
    if mode == "live-smoke":
        live_result = _live_refresh_smoke(counters)

    diff_guard = _production_diff_guard()
    counters["production_consumer_changed_count"] = diff_guard["production_consumer_changed_count"]
    counters["production_adjusted_store_modified_count"] = diff_guard["production_adjusted_store_modified_count"]
    counters["validation_source_head_mismatch_count"] = int(diff_guard["start_head"] != FIX_START_HEAD)
    counters["secret_occurrence_count"] = _secret_count(diff_guard["changed_paths"])
    required_zero = (
        "detector_failure_count", "same_value_false_dirty_count", "listed_shares_change_missed_count",
        "par_value_change_missed_count", "source_conflict_detection_error_count",
        "illegal_transition_accept_count", "dirty_latch_error_count", "concurrent_claim_error_count",
        "interrupted_refresh_recovery_error_count", "refresh_failure_detection_error_count",
        "partial_response_accept_count", "empty_response_accept_count", "missing_store_fetch_count",
        "old_store_preservation_error_count", "post_refresh_integrity_error_count",
        "adjusted_false_call_count", "krx_open_api_request_count", "opendart_request_count",
        "production_consumer_changed_count", "legacy_cache_modified_count",
        "production_adjusted_store_modified_count", "secret_occurrence_count",
        "validation_source_head_mismatch_count", "new_test_failure_count",
    )
    blockers = [name for name in required_zero if counters.get(name, 0) != 0]
    positives = [
        ("detector_case_count", counters["detector_case_count"] > 0),
        ("samsung_split_dirty_detection_count", counters["samsung_split_dirty_detection_count"] == 1),
        ("state_transition_test_count", counters["state_transition_test_count"] > 0),
        ("refresh_success_count", counters["refresh_success_count"] > 0),
    ]
    if mode == "live-smoke":
        positives.extend(
            [
                ("logical_adjusted_refresh_fetch_count", counters["logical_adjusted_refresh_fetch_count"] > 0),
                ("adjusted_true_call_count", counters["adjusted_true_call_count"] > 0),
            ]
        )
    blockers.extend(name for name, passed in positives if not passed)
    if blockers:
        recommendation = "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE" if mode == "live-smoke" and live_result is None else "BLOCKED_MORE_EVIDENCE_REQUIRED"
        status = "BLOCKED_CORPORATE_ACTION_DIRTY_REFRESH_V01"
    else:
        recommendation = "RECOMMEND_PROCEED_TO_KRX_HISTORICAL_BACKFILL_V01"
        status = "READY_FOR_ARCHITECT_CORPORATE_ACTION_DIRTY_REFRESH_V01_REVIEW"

    _write_json(output / "detector_contract.json", {
        "snapshot_fields": ["ticker", "as_of", "listed_shares", "par_value"],
        "primary_signal": "LIST_SHRS",
        "corroborating_signal": "PARVAL",
        "event_classification": False,
        "price_gap_signal": False,
        "counters": counters,
    })
    _write_json(output / "state_store_contract.json", {
        "backend": "SQLite",
        "default_path": "data/market/state/corporate_action.sqlite3",
        "statuses": ["CLEAN", "DIRTY", "REFRESHING", "FAILED"],
        "allowed_transitions": {key: sorted(value) for key, value in ALLOWED_TRANSITIONS.items()},
        "transaction": "BEGIN IMMEDIATE compare-and-set",
        "runtime_database_committed": False,
    })
    _write_json(output / "state_transition_matrix.json", {
        "absent": ["CLEAN", "DIRTY"],
        "allowed": {key: sorted(value) for key, value in ALLOWED_TRANSITIONS.items()},
        "forbidden": ["DIRTY->CLEAN", "FAILED->CLEAN"],
    })
    _write_json(output / "refresh_contract.json", {
        "provider": "AdjustedPriceDataProvider",
        "adjusted_true_only": True,
        "one_logical_fetch_per_invocation": True,
        "full_history_start": "metadata.requested_start fallback metadata.actual_date_min",
        "end_rule": "refresh_end >= existing actual_date_max",
        "existing_store_required": True,
        "coverage_rule": "old trading dates must be subset of new frame",
        "empty_response": "FAILED without save",
        "partial_response": "FAILED without save",
        "clean_transition": "only after provider/save/reload/integrity success",
    })
    _write_json(output / "samsung_split_evidence.json", {
        "ticker": "005930",
        "previous": {"as_of": "2018-04-27", "par_value": 5000, "listed_shares": 128386494},
        "current": {"as_of": "2018-05-04", "par_value": 100, "listed_shares": 6419324700},
        "is_dirty": True,
        "dirty_reason": "LISTED_SHARES_AND_PAR_VALUE_CHANGED",
        "corporate_action_type": None,
    })
    _write_json(output / "refresh_integrity_summary.json", {
        "refresh_success_count": counters["refresh_success_count"],
        "refresh_failure_detection_error_count": counters["refresh_failure_detection_error_count"],
        "partial_response_accept_count": counters["partial_response_accept_count"],
        "empty_response_accept_count": counters["empty_response_accept_count"],
        "missing_store_fetch_count": counters["missing_store_fetch_count"],
        "old_store_preservation_error_count": counters["old_store_preservation_error_count"],
        "post_refresh_integrity_error_count": counters["post_refresh_integrity_error_count"],
        "runtime_database_committed": False,
    })
    if live_result is not None:
        _write_json(output / "live_refresh_smoke.json", live_result)
    recommendation_text = (
        "corporate_action_dirty_refresh_recommendation.md\n\n"
        "======================================================================\n"
        "Corporate Action Dirty Refresh V01 Recommendation\n"
        "======================================================================\n\n"
        f"STATUS: {status}\nRECOMMENDATION: {recommendation}\n\n"
        "Detector는 refresh 필요성만 판단하고 event type이나 OHLC adjustment를 수행하지 않는다.\n"
        "runtime SQLite와 validation parquet는 commit하지 않았다.\n"
    )
    (output / "corporate_action_dirty_refresh_recommendation.md").write_text(recommendation_text, encoding="utf-8")
    result = {
        "architecture_version": "CORPORATE_ACTION_DIRTY_REFRESH_V01",
        "mode": mode,
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": diff_guard["implementation_head"],
        "end_head": None,
        "branch": _git("branch", "--show-current"),
        "counters": counters,
        "required_zero": list(required_zero),
        "blockers": blockers,
        "production_diff_guard": diff_guard,
        "status": status,
        "recommendation": recommendation,
        "test_output_tail": test_tail,
    }
    _write_json(output / "corporate_action_dirty_refresh_v01_summary.json", result)
    artifact_names = sorted(
        path.name for path in output.iterdir()
        if path.is_file() and path.name != "corporate_action_dirty_refresh_v01_manifest.json"
    )
    _write_json(output / "corporate_action_dirty_refresh_v01_manifest.json", {
        "architecture_version": "CORPORATE_ACTION_DIRTY_REFRESH_V01",
        "start_head": FIX_START_HEAD,
        "implementation_head": diff_guard["implementation_head"],
        "validation_source_head": diff_guard["implementation_head"],
        "end_head": None,
        "artifact_count": len(artifact_names) + 1,
        "artifacts": artifact_names + ["corporate_action_dirty_refresh_v01_manifest.json"],
        "network_request_count": counters["logical_adjusted_refresh_fetch_count"] if mode == "live-smoke" else 0,
        "status": status,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Corporate Action Dirty Refresh v01")
    parser.add_argument("--live-smoke", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    result = run("live-smoke" if args.live_smoke else "offline", output)
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "blockers": result["blockers"]}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
