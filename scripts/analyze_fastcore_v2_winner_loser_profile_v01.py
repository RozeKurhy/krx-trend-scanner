"""A FAST Core V2 winner vs loser profile analysis V01.

기존에 인증·봉인된 CONTROL(`PATTERN_A_FAST_FINAL_STRATEGY_V02`) 단순 백테스트 원장만 읽어
고수익 거래와 손실 거래의 진입 시점 특성 차이를 비교한다.

- 새 백테스트, 신규 signal 생성, threshold 변경을 하지 않는다.
- 원장에 없는 진입 시점 feature는 기존 공식 경로로만 복원한다.
  - Pattern A score와 FAST 계약 입력값: `evaluate_pattern_a_fast`와 같은 snapshot/feature 함수
  - 시가총액·평균 거래대금: raw daily `market_cap`/`trading_value`와 `evaluate_investability`
- 비교는 그룹별 기술통계, rank AUC(Mann-Whitney), 범주 비율 차이만 사용한다.

사용법:
    python scripts/analyze_fastcore_v2_winner_loser_profile_v01.py enrich   # 진입 feature 복원(수십 분)
    python scripts/analyze_fastcore_v2_winner_loser_profile_v01.py analyze  # 캐시를 읽어 산출물 생성
    python scripts/analyze_fastcore_v2_winner_loser_profile_v01.py lifecycle  # lifecycle 경로별 수익률 follow-up
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import socket
import sys
import time
import warnings
from typing import Any, Iterable

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
BACKTEST_ROOT = ROOT / "artifacts/backtests"
OUTPUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/winner_loser_profile_v01"
ENRICHMENT_PATH = OUTPUT_DIR / "entry_feature_enrichment.csv"
ENRICHMENT_AUDIT_PATH = OUTPUT_DIR / "entry_feature_enrichment_audit.json"
SYNTHESIS_DOC = "docs/patterns/pattern_a_fast/strategy/FAST_CORE_V2_NEG40_WEAK_PROTECT_5_WINDOW_SYNTHESIS_V01.md"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
REPOSITORY_END = "2026-09-21"
DISJOINT_SPLIT_DATE = "2021-01-01"

# 5-window synthesis 문서가 지정한 윈도우별 인증 산출물. priority가 작을수록 dedup 대표값으로 우선한다.
# 같은 cutoff(2026-08-31)인 P1·P3-2·P2-2 중 P1과 P3-2는 현재 lifecycle 계약 재인증본이라 먼저 두고,
# 더 이른 계약으로 실행된 P2-2를 그 다음에 둔다. 이른 cutoff인 P2-1·P3-1은 마지막이다.
WINDOWS: dict[str, dict[str, Any]] = {
    "P1": {
        "run_dir": "p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02",
        "certification_file": "p1_raw_only_certification_v02.json",
        "verdict": "P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS",
        "cutoff": "2026-08-31",
        "priority": 1,
    },
    "P3-2": {
        "run_dir": "p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01",
        "certification_file": "p3_2_summary.json",
        "verdict": "P3_2_REPLAY_PASS; certified with authoritative exclusion",
        "cutoff": "2026-08-31",
        "priority": 2,
    },
    "P2-2": {
        "run_dir": "p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01",
        "certification_file": "p2_2_summary.json",
        "verdict": "COMPLETE / PROMISING; ledger aggregate reconciliation PASS",
        "cutoff": "2026-08-31",
        "priority": 3,
    },
    "P2-1": {
        "run_dir": "p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/raw_only_lifecycle_closure_v01",
        "certification_file": "p2_1_raw_only_certification_v01.json",
        "verdict": "P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS",
        "cutoff": "2025-05-30",
        "priority": 4,
    },
    "P3-1": {
        "run_dir": "p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01",
        "certification_file": "p3_1_summary.json",
        "verdict": "P3_1_REPLAY_PASS; certified with authoritative exclusion",
        "cutoff": "2025-05-30",
        "priority": 5,
    },
}
WINDOW_ORDER = ["P1", "P2-1", "P2-2", "P3-1", "P3-2"]

# synthesis 문서의 CONTROL 값. 입력 원장 필터와 수익률 계약이 같다는 입력 게이트로 쓴다.
SYNTHESIS_CONTROL = {
    "P1": {"n": 4982, "positive_rate": 30.0682, "mean": 9.5307, "median": -15.29, "le": [109, 66, 42, 31], "ge": [1025, 757, 320]},
    "P2-1": {"n": 1800, "positive_rate": 32.1667, "mean": 3.8632, "median": -15.18, "le": [37, 24, 11, 6], "ge": [295, 187, 64]},
    "P2-2": {"n": 2424, "positive_rate": 30.7343, "mean": 7.9321, "median": -15.16, "le": [57, 37, 22, 13], "ge": [462, 336, 134]},
    "P3-1": {"n": 1173, "positive_rate": 29.2413, "mean": 0.7892, "median": -15.29, "le": [22, 14, 7, 4], "ge": [165, 106, 30]},
    "P3-2": {"n": 1792, "positive_rate": 27.9018, "mean": 6.4094, "median": -15.265, "le": [37, 22, 8, 5], "ge": [322, 249, 96]},
}

IDENTITY_KEY = ["ticker", "isu_cd", "entry_signal_date", "entry_execution_date"]
CLOSED_STATUSES = {"REALIZED", "LIFECYCLE_SETTLED"}

# 결과를 보기 전에 고정한 feature 목록. FAST 계약의 직접 입력값과 원장 진입 필드만 쓴다.
ENRICHED_FAST_INPUTS = [
    "range_position_24m",
    "monthly_down_month_ratio_12m",
    "distance_to_prior_26w_high_pct",
    "close_vs_wma200_pct",
    "higher_weekly_low_count_13w",
    "wma52_slope_1w",
    "wma12_vs_wma26_pct",
    "weeks_since_26w_close_breakout",
    "post_breakout_min_low_vs_level_pct_26w",
    "recent_5d_max_gap_abs_pct",
    "atr_14_pct",
]
NUMERIC_ENTRY_FEATURES = [
    "fast_score",
    "pattern_a_score",
    "fast_weekly_core_score",
    *ENRICHED_FAST_INPUTS,
    "market_cap_eok",
    "avg_trading_value_20d_eok",
    "avg_trading_value_60d_eok",
]
# 2수준 범주는 한쪽 수준만 지시변수로 둔다(나머지는 거울상이다).
CATEGORICAL_ENTRY_FEATURES: dict[str, list[str] | None] = {
    "market": ["KOSDAQ"],
    "entry_pattern_a_stage": ["EARLY_TREND"],
    "daily_risk": ["ELEVATED"],
    "fast_score_state": ["PARTIAL"],
    "entry_kind": ["REENTRY"],
    "fast_conditional_status": ["EVENT_OBSERVED"],
    "investability_status": None,
}
CONSTANT_ENTRY_FIELDS = ["fast_stage", "monthly_regime"]
NUMERIC_POST_ENTRY = ["days_to_first_progressed", "holding_days", "mfe", "mae", "peak_giveback", "profit_capture"]
CATEGORICAL_POST_ENTRY: dict[str, list[str] | None] = {
    "lifecycle_class": None,
    "exit_type": None,
    "trade_status": None,
    "loss_guard_triggered": None,
}

GROUP_RULES = {
    "WIN_50": lambda r: r >= 50.0,
    "WIN_100": lambda r: r >= 100.0,
    "LOSS_ANY": lambda r: r <= 0.0,
    "LOSS_30": lambda r: r <= -30.0,
    "LOSS_50": lambda r: r <= -50.0,
    "LOSS_60": lambda r: r <= -60.0,
    "POSITIVE": lambda r: r > 0.0,
}
COMPARISONS = [
    ("WIN_50_vs_REST", "WIN_50", "NOT_WIN_50", False),
    ("WIN_100_vs_REST", "WIN_100", "NOT_WIN_100", False),
    ("LOSS_ANY_vs_POSITIVE", "LOSS_ANY", "POSITIVE", False),
    ("LOSS_30_vs_REST", "LOSS_30", "NOT_LOSS_30", False),
    ("LOSS_50_vs_REST", "LOSS_50", "NOT_LOSS_50", False),
    ("WIN_50_vs_LOSS_30", "WIN_50", "LOSS_30", True),
    ("WIN_100_vs_LOSS_50", "WIN_100", "LOSS_50", True),
]

# 반복성 등급 기준(결과 확인 전에 고정).
GRADE_RULES = {
    "min_group_n": 10,
    "weak_auc_abs": 0.05,
    "weak_share_pp": 5.0,
    "min_qualifying_windows": 3,
    "consistent_window_share": 0.8,
    "disjoint_split_date": DISJOINT_SPLIT_DATE,
    "definition": {
        "INSUFFICIENT_EVIDENCE": "pooled group or reference n < 10, or fewer than 3 windows where both sides have n >= 10",
        "WEAK": "pooled |AUC-0.5| < 0.05 (numeric) or |share difference| < 5pp (categorical)",
        "CONSISTENT": "not WEAK, >= 80% of qualifying windows have the pooled sign, and both disjoint periods (entry < 2021-01-01 / >= 2021-01-01) have the pooled sign when both qualify",
        "MIXED": "not WEAK and not CONSISTENT",
    },
}


class NetworkRequestBlocked(RuntimeError):
    pass


@contextmanager
def network_guard(audit: dict[str, int]):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit["count"] += 1
        raise NetworkRequestBlocked(repr(address))

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit["count"] += 1
        raise NetworkRequestBlocked(repr(address))

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ---------------------------------------------------------------------------
# 원장 로드와 입력 게이트
# ---------------------------------------------------------------------------

def load_window_ledger(window: str) -> pd.DataFrame:
    spec = WINDOWS[window]
    run_dir = BACKTEST_ROOT / spec["run_dir"]
    frame = pd.read_csv(run_dir / "control_trades.csv", dtype={"ticker": str, "isu_cd": str}, low_memory=False)
    if window == "P3-2":
        summary = json.loads((run_dir / "p3_2_summary.json").read_text(encoding="utf-8"))
        excluded = summary["population"]["permanent_identity_exclusion_recertification"]["excluded_pair_ids"]
        frame = frame[~frame["pair_id"].isin(excluded)].copy()
        if (frame.get("lifecycle_certification_class") == "REMEDIABLE_UNRESOLVED").any():
            raise RuntimeError("P3_2_REMEDIABLE_UNRESOLVED_REMAINS_AFTER_EXCLUSION")
    if set(frame["strategy_id"].unique()) != {STRATEGY_ID}:
        raise RuntimeError(f"STRATEGY_ID_MISMATCH:{window}")
    frame["ticker"] = frame["ticker"].str.zfill(6)
    frame["window"] = window
    return frame


def window_control_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["terminal_return"].dropna().astype(float)
    return {
        "n": int(len(returns)),
        "positive_rate": round(float((returns > 0).mean() * 100.0), 4),
        "mean": round(float(returns.mean()), 4),
        "median": round(float(returns.median()), 4),
        "le": [int((returns <= -x).sum()) for x in (30, 40, 50, 60)],
        "ge": [int((returns >= x).sum()) for x in (30, 50, 100)],
    }


def input_gate(ledgers: dict[str, pd.DataFrame]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for window in WINDOW_ORDER:
        observed = window_control_metrics(ledgers[window])
        expected = SYNTHESIS_CONTROL[window]
        match = (
            observed["n"] == expected["n"]
            and observed["le"] == expected["le"]
            and observed["ge"] == expected["ge"]
            and abs(observed["positive_rate"] - expected["positive_rate"]) < 1e-3
            and abs(observed["mean"] - expected["mean"]) < 1e-3
            and abs(observed["median"] - expected["median"]) < 1e-3
        )
        result[window] = {"observed": observed, "expected": expected, "match": bool(match)}
        if not match:
            raise RuntimeError(f"INPUT_GATE_SYNTHESIS_MISMATCH:{window}:{observed}")
    return result


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def _inventory_status(window: str, run_rel: str) -> str:
    selected = BACKTEST_ROOT / WINDOWS[window]["run_dir"]
    if (BACKTEST_ROOT / run_rel) == selected:
        return "SELECTED"
    if "realistic" in run_rel:
        return "OUT_OF_SCOPE_REALISTIC_PORTFOLIO"
    if selected.is_relative_to(BACKTEST_ROOT / run_rel):
        return "SOURCE_RAW_OF_SELECTED_CERTIFICATION"
    return "SUPERSEDED_OR_NOT_AUTHORITATIVE"


def build_inventory() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    window_dirs = {
        "P1": "p1_neg40_weak_protect_v01",
        "P2-1": "p2_1_neg40_weak_protect_v01",
        "P2-2": "p2_2_neg40_weak_protect_v01",
        "P3-1": "p3_1_neg40_weak_protect_v01",
        "P3-2": "p3_2_neg40_weak_protect_v01",
    }
    for window in WINDOW_ORDER:
        window_root = BACKTEST_ROOT / window_dirs[window]
        paths = sorted([*window_root.rglob("control_trades.csv"), *window_root.rglob("control_strategy_trades.csv")])
        for path in paths:
            run_rel = str(path.parent.relative_to(BACKTEST_ROOT))
            status = _inventory_status(window, run_rel)
            header = pd.read_csv(path, nrows=0).columns.tolist()
            frame = pd.read_csv(path, dtype=str, low_memory=False)
            if "strategy_id" not in frame:
                frame["strategy_id"] = ""
            entry_features = [c for c in header if c in {
                "market", "entry_pattern_a_stage", "fast_stage", "monthly_regime", "daily_risk",
                "fast_score", "fast_score_state", "previous_exit_type", "entry_open",
            }]
            rows.append({
                "window": window,
                "path": _rel(path),
                "status": status,
                "certification_verdict": WINDOWS[window]["verdict"] if status == "SELECTED" else "",
                "certification_file": (
                    _rel(BACKTEST_ROOT / WINDOWS[window]["run_dir"] / WINDOWS[window]["certification_file"])
                    if status == "SELECTED" else ""
                ),
                "strategy_id": ";".join(sorted(frame["strategy_id"].astype(str).unique())),
                "row_count": int(len(frame)),
                "trade_identity_columns": "ticker|isu_cd|entry_signal_date|entry_execution_date (pair_id, trade_id restart per window)",
                "entry_signal_date_column": "entry_signal_date" if "entry_signal_date" in header else "",
                "entry_execution_date_column": "entry_execution_date" if "entry_execution_date" in header else "",
                "return_column": "terminal_return" if "terminal_return" in header else "",
                "entry_feature_columns": "|".join(entry_features),
                "sha256": sha256_file(path),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Exclusion union과 dedup
# ---------------------------------------------------------------------------

def certification_exclusion_identities() -> pd.DataFrame:
    """선택된 인증본들이 제외한 (ticker, isu_cd) identity의 합집합."""
    rows: list[dict[str, str]] = []
    p1 = json.loads((BACKTEST_ROOT / WINDOWS["P1"]["run_dir"] / WINDOWS["P1"]["certification_file"]).read_text(encoding="utf-8"))
    for item in p1["p1_population"]["population_preflight"]["permanent_identity_exclusions"]:
        rows.append({"ticker": str(item["ticker"]).zfill(6), "isu_cd": str(item["isu_cd"]), "source": "P1_PERMANENT_EXCLUSION"})
    p21 = json.loads((BACKTEST_ROOT / WINDOWS["P2-1"]["run_dir"] / WINDOWS["P2-1"]["certification_file"]).read_text(encoding="utf-8"))
    for key, source in (("registry_identities", "P2_1_REGISTRY_EXCLUSION"), ("closure_identities", "P2_1_LIFECYCLE_CLOSURE_EXCLUSION")):
        for item in p21["exclusions"][key]:
            rows.append({"ticker": str(item["ticker"]).zfill(6), "isu_cd": str(item["isu_cd"]), "source": source})
    p32 = json.loads((BACKTEST_ROOT / WINDOWS["P3-2"]["run_dir"] / WINDOWS["P3-2"]["certification_file"]).read_text(encoding="utf-8"))
    for item in p32["population"]["permanent_identity_exclusion_recertification"]["excluded_identities"]:
        rows.append({"ticker": str(item["ticker"]).zfill(6), "isu_cd": str(item["isu_cd"]), "source": "P3_2_PERMANENT_EXCLUSION"})
    frame = pd.DataFrame(rows)
    return frame.groupby(["ticker", "isu_cd"], as_index=False)["source"].agg(lambda s: "|".join(sorted(set(s))))


def deduplicate(ledgers: dict[str, pd.DataFrame], exclusions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    stacked = pd.concat([ledgers[w] for w in WINDOW_ORDER], ignore_index=True)
    stacked["window_priority"] = stacked["window"].map(lambda w: WINDOWS[w]["priority"])
    stacked["window_cutoff"] = stacked["window"].map(lambda w: WINDOWS[w]["cutoff"])
    total_rows = len(stacked)

    excluded_keys = set(zip(exclusions["ticker"], exclusions["isu_cd"]))
    is_excluded = pd.Series([(t, i) in excluded_keys for t, i in zip(stacked["ticker"], stacked["isu_cd"])], index=stacked.index)
    excluded_rows = stacked[is_excluded]
    stacked = stacked[~is_excluded]
    null_return = stacked["terminal_return"].isna()
    null_rows = stacked[null_return]
    stacked = stacked[~null_return].copy()

    grouped = stacked.groupby(IDENTITY_KEY, sort=False)
    observed_windows = grouped["window"].agg(lambda s: "|".join(w for w in WINDOW_ORDER if w in set(s))).rename("observed_windows")
    # 같은 cutoff에서 수익률이 다른 identity(데이터 authority·lifecycle 계약 차이)를 기록한다.
    same_cutoff_spread = (
        stacked.groupby(IDENTITY_KEY + ["window_cutoff"], sort=False)["terminal_return"]
        .agg(lambda s: float(s.max() - s.min()))
        .groupby(level=list(range(len(IDENTITY_KEY))))
        .max()
        .rename("same_cutoff_return_spread")
    )
    representative = stacked.sort_values(IDENTITY_KEY + ["window_priority"]).drop_duplicates(IDENTITY_KEY, keep="first")
    representative = representative.merge(observed_windows.reset_index(), on=IDENTITY_KEY).merge(
        same_cutoff_spread.reset_index(), on=IDENTITY_KEY
    )
    representative["n_windows_observed"] = representative["observed_windows"].str.count(r"\|") + 1
    representative = representative.rename(columns={"window": "representative_window"})
    representative = representative.sort_values(["entry_signal_date", "ticker", "isu_cd"]).reset_index(drop=True)
    disagreement = representative[representative["same_cutoff_return_spread"] > 0.005]
    audit = {
        "identity_key": IDENTITY_KEY,
        "representative_priority": [w for w, _ in sorted(WINDOWS.items(), key=lambda kv: kv[1]["priority"])],
        "priority_rule": "latest cutoff first; among the 2026-08-31 cutoff windows P1 and P3-2 (current lifecycle-contract recertifications) precede P2-2 (earlier run)",
        "stacked_window_rows": int(total_rows),
        "excluded_by_certification_identity_union_rows": int(len(excluded_rows)),
        "excluded_by_certification_identity_union_by_window": {k: int(v) for k, v in excluded_rows["window"].value_counts().items()},
        "exclusion_identity_count": int(len(exclusions)),
        "null_terminal_return_rows": int(len(null_rows)),
        "null_terminal_return_trade_ids": sorted(f"{w}:{t}" for w, t in zip(null_rows["window"], null_rows["trade_id"])),
        "rows_after_filters": int(len(stacked)),
        "dedup_trade_count": int(len(representative)),
        "duplicate_rows_removed": int(len(stacked) - len(representative)),
        "identities_by_n_windows": {int(k): int(v) for k, v in representative["n_windows_observed"].value_counts().sort_index().items()},
        "representative_window_counts": {k: int(v) for k, v in representative["representative_window"].value_counts().items()},
        "same_cutoff_return_disagreement_count": int(len(disagreement)),
        "same_cutoff_return_disagreement_examples": disagreement[IDENTITY_KEY + ["observed_windows", "representative_window", "terminal_return", "same_cutoff_return_spread"]].head(20).to_dict("records"),
    }
    return representative, audit


def nesting_audit(ledgers: dict[str, pd.DataFrame]) -> dict[str, Any]:
    keys = {w: set(map(tuple, ledgers[w][IDENTITY_KEY].values)) for w in WINDOW_ORDER}
    result = {}
    for inner, outer in (("P2-1", "P2-2"), ("P3-1", "P3-2"), ("P2-2", "P1"), ("P3-2", "P1")):
        missing = sorted(keys[inner] - keys[outer])
        result[f"{inner}_not_in_{outer}"] = {"count": len(missing), "examples": [list(m) for m in missing[:20]]}
    result["note"] = (
        "Windows share start dates (P2-1/P2-2 2021-01, P3-1/P3-2 2022-01) but trades are path-dependent per ticker; "
        "a different cutoff, data authority, lifecycle contract, or earlier P1 history changes later entries. "
        "Window agreement is therefore not independent confirmation."
    )
    return result


# ---------------------------------------------------------------------------
# 진입 feature 복원 (enrich)
# ---------------------------------------------------------------------------

def enrichment_keys(ledgers: dict[str, pd.DataFrame]) -> pd.DataFrame:
    stacked = pd.concat([ledgers[w] for w in WINDOW_ORDER], ignore_index=True)
    columns = ["ticker", "isu_cd", "identity_effective_from", "entry_signal_date", "entry_pattern_a_stage", "fast_score", "fast_score_state"]
    keys = stacked[columns].drop_duplicates(["ticker", "isu_cd", "identity_effective_from", "entry_signal_date"])
    return keys.sort_values(["ticker", "identity_effective_from", "entry_signal_date"]).reset_index(drop=True)


def _features_at(context: Any, signal_date: pd.Timestamp, market_calendar: Any) -> dict[str, float]:
    """`evaluate_pattern_a_fast`가 내부에서 만드는 feature dict를 같은 함수로 다시 만든다."""
    from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context
    from trend_scanner.research.pattern_a_fast_daily_features import compute_daily_timing_features
    from trend_scanner.research.pattern_a_fast_monthly_features import compute_monthly_regime_features
    from trend_scanner.research.pattern_a_fast_weekly_features import compute_weekly_trigger_features

    snapshot = build_historical_snapshot_from_context(
        context, signal_date, include_incomplete_periods=False, market_calendar=market_calendar
    )
    features: dict[str, float] = {}
    features.update(compute_monthly_regime_features(snapshot.monthly))
    features.update(compute_weekly_trigger_features(snapshot.weekly))
    features.update(compute_daily_timing_features(context.slice_daily_up_to(signal_date)))
    return features


def _enrich_identity(
    group: pd.DataFrame,
    repo: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    market_calendar: Any,
) -> list[dict[str, Any]]:
    from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
    from trend_scanner.filters.investability import evaluate_investability
    from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

    first = group.iloc[0]
    ticker, isu_cd, start = first["ticker"], first["isu_cd"], first["identity_effective_from"]
    last_signal = max(group["entry_signal_date"])
    output: list[dict[str, Any]] = []
    try:
        daily = repo.get_daily(ticker, start, last_signal).sort_index()
        ancillary = repo.get_daily_ancillary(ticker, start, last_signal).sort_index()
        context = build_precomputed_ticker_context(ticker, ticker, daily)
        load_error = None
    except Exception as exc:  # 데이터 결측은 행 단위 UNAVAILABLE로 남긴다.
        daily = ancillary = context = None
        load_error = f"{type(exc).__name__}: {exc}"
    for _, row in group.iterrows():
        signal_date = pd.Timestamp(row["entry_signal_date"]).normalize()
        record: dict[str, Any] = {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "identity_effective_from": start,
            "entry_signal_date": row["entry_signal_date"],
            "ledger_entry_pattern_a_stage": row["entry_pattern_a_stage"],
            "ledger_fast_score": row["fast_score"],
            "enrichment_status": "UNAVAILABLE",
            "enrichment_error": load_error,
        }
        if context is None:
            output.append(record)
            continue
        try:
            evaluated = evaluate_pattern_a_fast(
                ticker, ticker, daily, signal_date, score_contract, stage_contract,
                context=context, market_calendar=market_calendar,
            )
            features = _features_at(context, signal_date, market_calendar)
            record["reconstructed_pattern_a_stage"] = (str(evaluated.get("pattern_a_stage")).upper() if evaluated.get("pattern_a_stage") else None)
            record["pattern_a_score"] = _round(evaluated.get("pattern_a_score"), 4)
            record["pattern_a_evaluation_status"] = evaluated.get("pattern_a_evaluation_status")
            record["reconstructed_fast_score"] = _round(evaluated.get("fast_score"), 4)
            record["fast_weekly_core_score"] = _round(evaluated.get("fast_weekly_core_score"), 4)
            record["fast_conditional_status"] = evaluated.get("fast_conditional_status")
            record["reconstructed_fast_machine_stage"] = evaluated.get("fast_machine_stage")
            for name in ENRICHED_FAST_INPUTS:
                record[name] = _round(features.get(name), 6)
            mcap = None
            mcap_date = None
            if ancillary is not None and signal_date in ancillary.index:
                value = ancillary.loc[signal_date, "market_cap"]
                mcap = float(value) if pd.notna(value) else None
                mcap_date = signal_date.strftime("%Y-%m-%d")
            investability = evaluate_investability(
                ticker, signal_date, daily.loc[daily.index <= signal_date], market_cap=mcap,
                market_cap_effective_date=mcap_date,
            )
            inv = investability.to_dict()
            record["market_cap_eok"] = inv["market_cap_eok"]
            record["avg_trading_value_20d_eok"] = inv["avg_trading_value_20d_eok"]
            record["avg_trading_value_60d_eok"] = inv["avg_trading_value_60d_eok"]
            record["investability_status"] = inv["investability_status"]
            stage_match = record["reconstructed_pattern_a_stage"] == str(row["entry_pattern_a_stage"]).upper()
            fast_match = (
                record["reconstructed_fast_score"] is not None
                and pd.notna(row["fast_score"])
                and abs(float(record["reconstructed_fast_score"]) - float(row["fast_score"])) <= 0.011
            )
            record["stage_match"] = bool(stage_match)
            record["fast_score_match"] = bool(fast_match)
            if record["pattern_a_evaluation_status"] != "READY" or record["pattern_a_score"] is None:
                record["enrichment_status"] = "PATTERN_A_UNAVAILABLE"
            elif not stage_match:
                record["enrichment_status"] = "CHECK_REQUIRED_STAGE_MISMATCH"
            else:
                record["enrichment_status"] = "READY"
            record["enrichment_error"] = None
        except Exception as exc:
            record["enrichment_error"] = f"{type(exc).__name__}: {exc}"
        output.append(record)
    return output


def leakage_check(
    sample: pd.DataFrame,
    enriched: pd.DataFrame,
    repo: Any,
    score_contract: dict[str, Any],
    stage_contract: dict[str, Any],
    market_calendar: Any,
) -> dict[str, Any]:
    """진입 신호일까지만 자른 일봉으로 다시 계산해 context 경로와 같은지 확인한다."""
    from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
    from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast

    index = enriched.set_index(["ticker", "isu_cd", "identity_effective_from", "entry_signal_date"])
    checked, mismatches = 0, []
    for _, row in sample.iterrows():
        key = (row["ticker"], row["isu_cd"], row["identity_effective_from"], row["entry_signal_date"])
        base = index.loc[key]
        if base["enrichment_status"] != "READY":
            continue
        signal_date = pd.Timestamp(row["entry_signal_date"]).normalize()
        daily = repo.get_daily(row["ticker"], row["identity_effective_from"], row["entry_signal_date"]).sort_index()
        daily = daily.loc[daily.index <= signal_date]
        context = build_precomputed_ticker_context(row["ticker"], row["ticker"], daily)
        evaluated = evaluate_pattern_a_fast(
            row["ticker"], row["ticker"], daily, signal_date, score_contract, stage_contract,
            context=context, market_calendar=market_calendar,
        )
        features = _features_at(context, signal_date, market_calendar)
        checked += 1
        diffs = {}
        if _round(evaluated.get("pattern_a_score"), 4) != base["pattern_a_score"]:
            diffs["pattern_a_score"] = [_round(evaluated.get("pattern_a_score"), 4), base["pattern_a_score"]]
        for name in ENRICHED_FAST_INPUTS:
            a, b = _round(features.get(name), 6), base[name]
            if not ((a is None and pd.isna(b)) or (a is not None and pd.notna(b) and abs(a - float(b)) < 1e-6)):
                diffs[name] = [a, None if pd.isna(b) else float(b)]
        if diffs:
            mismatches.append({"key": list(key), "diffs": diffs})
    return {"sample_size": int(len(sample)), "checked": checked, "mismatch_count": len(mismatches), "mismatches": mismatches[:20]}


def run_enrich(workers: int) -> None:
    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
    from trend_scanner.data.repository_v2_loader import build_production_repository_v2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit_net = {"count": 0}
    started = time.time()
    with network_guard(audit_net):
        ledgers = {w: load_window_ledger(w) for w in WINDOW_ORDER}
        input_gate(ledgers)
        keys = enrichment_keys(ledgers)
        calendar = load_rolling_production_market_calendar(ROOT)
        score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
        stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
        repo = build_production_repository_v2(ROOT, end=REPOSITORY_END)
        groups = [g for _, g in keys.groupby(["ticker", "isu_cd", "identity_effective_from"], sort=True)]
        print(f"enrich keys={len(keys)} identities={len(groups)}", flush=True)
        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_enrich_identity, g, repo, score_contract, stage_contract, calendar) for g in groups]
            for done, future in enumerate(as_completed(futures), start=1):
                records.extend(future.result())
                if done % 200 == 0 or done == len(groups):
                    print(f"identities={done}/{len(groups)} rows={len(records)} elapsed={time.time() - started:.0f}s", flush=True)
        enriched = pd.DataFrame(records).sort_values(["ticker", "identity_effective_from", "entry_signal_date"]).reset_index(drop=True)
        sample = keys.sample(n=min(20, len(keys)), random_state=20260926)
        leakage = leakage_check(sample, enriched, repo, score_contract, stage_contract, calendar)
    enriched.to_csv(ENRICHMENT_PATH, index=False)
    status_counts = enriched["enrichment_status"].value_counts().to_dict()
    audit = {
        "key_count": int(len(keys)),
        "identity_count": int(len(groups)),
        "status_counts": {k: int(v) for k, v in status_counts.items()},
        "stage_mismatch_count": int((enriched.get("stage_match") == False).sum()),  # noqa: E712
        "fast_score_match_count": int((enriched.get("fast_score_match") == True).sum()),  # noqa: E712
        "fast_score_mismatch_count": int((enriched.get("fast_score_match") == False).sum()),  # noqa: E712
        "error_examples": enriched.loc[enriched["enrichment_error"].notna(), ["ticker", "entry_signal_date", "enrichment_error"]].head(20).to_dict("records"),
        "leakage_check": leakage,
        "network_requests": audit_net["count"],
        "repository_end": REPOSITORY_END,
        "workers": workers,
        "elapsed_seconds": round(time.time() - started, 1),
        "enrichment_sha256": sha256_file(ENRICHMENT_PATH),
    }
    ENRICHMENT_AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in audit.items() if k != "error_examples"}, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 비교 통계
# ---------------------------------------------------------------------------

def rank_auc(group: Iterable[float], reference: Iterable[float]) -> float | None:
    """P(group > reference) + 0.5 * P(tie). 값이 없으면 None."""
    a = np.asarray([x for x in group if x is not None and math.isfinite(x)], dtype=float)
    b = np.asarray([x for x in reference if x is not None and math.isfinite(x)], dtype=float)
    if len(a) == 0 or len(b) == 0:
        return None
    ranks = pd.Series(np.concatenate([a, b])).rank(method="average").to_numpy()
    rank_sum = ranks[: len(a)].sum()
    u = rank_sum - len(a) * (len(a) + 1) / 2.0
    return float(u / (len(a) * len(b)))


def assign_groups(returns: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame(index=returns.index)
    for name, rule in GROUP_RULES.items():
        frame[name] = returns.map(lambda r, rule=rule: bool(rule(float(r))))
    for name in ("WIN_50", "WIN_100", "LOSS_30", "LOSS_50"):
        frame[f"NOT_{name}"] = ~frame[name]
    return frame


def _numeric_stats(values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"n": 0, "mean": None, "median": None, "q25": None, "q75": None}
    return {
        "n": int(len(values)),
        "mean": _round(values.mean()),
        "median": _round(values.median()),
        "q25": _round(values.quantile(0.25)),
        "q75": _round(values.quantile(0.75)),
    }


def feature_items(frame: pd.DataFrame, numeric: list[str], categorical: dict[str, list[str] | None]) -> list[tuple[str, str, str | None]]:
    items: list[tuple[str, str, str | None]] = [(name, "numeric", None) for name in numeric if name in frame]
    for name, levels in categorical.items():
        if name not in frame:
            continue
        chosen = levels if levels is not None else sorted(frame[name].dropna().astype(str).unique())
        items.extend((name, "categorical", level) for level in chosen)
    return items


def compare_feature(frame: pd.DataFrame, groups: pd.DataFrame, group: str, reference: str, feature: str, kind: str, level: str | None) -> dict[str, Any]:
    g = frame.loc[groups[group], feature]
    r = frame.loc[groups[reference], feature]
    row: dict[str, Any] = {"n_group_rows": int(groups[group].sum()), "n_reference_rows": int(groups[reference].sum())}
    if kind == "numeric":
        gs, rs = _numeric_stats(g), _numeric_stats(r)
        auc = rank_auc(pd.to_numeric(g, errors="coerce").dropna(), pd.to_numeric(r, errors="coerce").dropna())
        row.update({f"group_{k}": v for k, v in gs.items()})
        row.update({f"reference_{k}": v for k, v in rs.items()})
        row["median_difference"] = _round(gs["median"] - rs["median"]) if gs["median"] is not None and rs["median"] is not None else None
        row["mean_difference"] = _round(gs["mean"] - rs["mean"]) if gs["mean"] is not None and rs["mean"] is not None else None
        row["auc"] = _round(auc)
        row["effect"] = _round(auc - 0.5) if auc is not None else None
        row["effect_unit"] = "AUC-0.5"
    else:
        g_valid, r_valid = g.dropna().astype(str), r.dropna().astype(str)
        g_share = float((g_valid == level).mean() * 100.0) if len(g_valid) else None
        r_share = float((r_valid == level).mean() * 100.0) if len(r_valid) else None
        row.update({
            "group_n": int(len(g_valid)), "reference_n": int(len(r_valid)),
            "group_share_pct": _round(g_share), "reference_share_pct": _round(r_share),
            "group_level_count": int((g_valid == level).sum()), "reference_level_count": int((r_valid == level).sum()),
        })
        row["effect"] = _round(g_share - r_share) if g_share is not None and r_share is not None else None
        row["effect_unit"] = "share_pp"
    return row


def _sign(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def grade(pooled: dict[str, Any], windows: list[dict[str, Any]], disjoint: list[dict[str, Any]], kind: str) -> tuple[str, dict[str, Any]]:
    n_min = GRADE_RULES["min_group_n"]
    pooled_n = min(pooled.get("group_n", 0) or 0, pooled.get("reference_n", 0) or 0)
    qualifying = [w for w in windows if min(w.get("group_n", 0) or 0, w.get("reference_n", 0) or 0) >= n_min and w.get("effect") is not None]
    disjoint_q = [d for d in disjoint if min(d.get("group_n", 0) or 0, d.get("reference_n", 0) or 0) >= n_min and d.get("effect") is not None]
    effect = pooled.get("effect")
    sign = _sign(effect)
    same = sum(_sign(w["effect"]) == sign for w in qualifying)
    detail = {
        "qualifying_windows": len(qualifying),
        "windows_same_sign": same,
        "disjoint_evaluable": len(disjoint_q) == 2,
        "disjoint_same_sign": sum(_sign(d["effect"]) == sign for d in disjoint_q),
    }
    if pooled_n < n_min or len(qualifying) < GRADE_RULES["min_qualifying_windows"] or effect is None:
        return "INSUFFICIENT_EVIDENCE", detail
    threshold = GRADE_RULES["weak_auc_abs"] if kind == "numeric" else GRADE_RULES["weak_share_pp"]
    if abs(effect) < threshold:
        return "WEAK", detail
    windows_ok = same / len(qualifying) >= GRADE_RULES["consistent_window_share"]
    disjoint_ok = (not detail["disjoint_evaluable"]) or detail["disjoint_same_sign"] == 2
    if windows_ok and disjoint_ok:
        return "CONSISTENT", detail
    return "MIXED", detail


def build_group_counts(pooled: pd.DataFrame, ledgers: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    scopes = [("POOLED_DEDUP", pooled)]
    scopes += [(f"WINDOW_{w}", ledgers[w][ledgers[w]["terminal_return"].notna()]) for w in WINDOW_ORDER]
    early = pooled["entry_signal_date"] < DISJOINT_SPLIT_DATE
    scopes += [("POOLED_ENTRY_BEFORE_2021", pooled[early]), ("POOLED_ENTRY_FROM_2021", pooled[~early])]
    scopes += [("POOLED_DEDUP_CLOSED_ONLY", pooled[pooled["trade_status"].isin(CLOSED_STATUSES)])]
    for scope, frame in scopes:
        groups = assign_groups(frame["terminal_return"].astype(float))
        row = {"scope": scope, "trades": int(len(frame)), "open_at_cutoff": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum())}
        for name in ("WIN_50", "WIN_100", "POSITIVE", "LOSS_ANY", "LOSS_30", "LOSS_50", "LOSS_60"):
            row[name] = int(groups[name].sum())
            row[f"{name}_open_at_cutoff"] = int((groups[name] & (frame["trade_status"] == "OPEN_AT_CUTOFF")).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def prepare_frame(frame: pd.DataFrame, enrichment: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["entry_kind"] = np.where(frame["previous_exit_type"].notna(), "REENTRY", "FIRST_IN_WINDOW")
    first_prog = pd.to_datetime(frame["first_progressed_effective_trading_date"], errors="coerce")
    frame["days_to_first_progressed"] = (first_prog - pd.to_datetime(frame["entry_execution_date"])).dt.days
    frame["loss_guard_triggered"] = frame["loss_guard_triggered"].astype(str)
    columns = ["ticker", "isu_cd", "identity_effective_from", "entry_signal_date", "enrichment_status",
               "pattern_a_score", "fast_weekly_core_score", "fast_conditional_status", *ENRICHED_FAST_INPUTS,
               "market_cap_eok", "avg_trading_value_20d_eok", "avg_trading_value_60d_eok", "investability_status"]
    merged = frame.merge(enrichment[columns], on=["ticker", "isu_cd", "identity_effective_from", "entry_signal_date"], how="left", validate="many_to_one")
    not_ready = merged["enrichment_status"] != "READY"
    enriched_cols = [c for c in columns if c not in {"ticker", "isu_cd", "identity_effective_from", "entry_signal_date", "enrichment_status"}]
    merged.loc[not_ready, enriched_cols] = np.nan
    return merged


def profile_tables(
    pooled: pd.DataFrame,
    ledgers: dict[str, pd.DataFrame],
    numeric: list[str],
    categorical: dict[str, list[str] | None],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(pooled profile, window/disjoint consistency) 두 표를 만든다."""
    early_mask = pooled["entry_signal_date"] < DISJOINT_SPLIT_DATE
    scopes: dict[str, pd.DataFrame] = {f"WINDOW_{w}": ledgers[w] for w in WINDOW_ORDER}
    scopes["ENTRY_BEFORE_2021"] = pooled[early_mask]
    scopes["ENTRY_FROM_2021"] = pooled[~early_mask]
    scope_groups = {name: assign_groups(frame["terminal_return"].astype(float)) for name, frame in scopes.items()}
    pooled_groups = assign_groups(pooled["terminal_return"].astype(float))
    items = feature_items(pooled, numeric, categorical)
    profile_rows, consistency_rows = [], []
    for comparison, group, reference, extreme in COMPARISONS:
        for feature, kind, level in items:
            base = {"comparison": comparison, "group": group, "reference": reference, "extreme_contrast": extreme,
                    "feature": feature, "feature_kind": kind, "level": level}
            pooled_row = compare_feature(pooled, pooled_groups, group, reference, feature, kind, level)
            window_rows, disjoint_rows = [], []
            for scope, frame in scopes.items():
                row = compare_feature(frame, scope_groups[scope], group, reference, feature, kind, level)
                consistency_rows.append({**base, "scope": scope, **{k: row.get(k) for k in (
                    "group_n", "reference_n", "group_median", "reference_median", "group_share_pct", "reference_share_pct", "auc", "effect", "effect_unit")}})
                (window_rows if scope.startswith("WINDOW_") else disjoint_rows).append(row)
            verdict, detail = grade(pooled_row, window_rows, disjoint_rows, kind)
            direction = {1: "HIGHER_IN_GROUP", -1: "LOWER_IN_GROUP", 0: "NONE"}[_sign(pooled_row.get("effect"))]
            window_signs = "".join({1: "+", -1: "-", 0: "0"}[_sign(r.get("effect"))] if min(r.get("group_n", 0) or 0, r.get("reference_n", 0) or 0) >= GRADE_RULES["min_group_n"] else "." for r in window_rows)
            disjoint_signs = "".join({1: "+", -1: "-", 0: "0"}[_sign(r.get("effect"))] if min(r.get("group_n", 0) or 0, r.get("reference_n", 0) or 0) >= GRADE_RULES["min_group_n"] else "." for r in disjoint_rows)
            profile_rows.append({**base, **pooled_row, "direction": direction, "grade": verdict,
                                 "window_signs_P1_P21_P22_P31_P32": window_signs, "disjoint_signs_pre2021_from2021": disjoint_signs, **detail})
    return pd.DataFrame(profile_rows), pd.DataFrame(consistency_rows)


def constant_field_report(pooled: pd.DataFrame) -> dict[str, Any]:
    return {name: {k: int(v) for k, v in pooled[name].value_counts(dropna=False).items()} for name in CONSTANT_ENTRY_FIELDS}


def loser_mechanics(pooled: pd.DataFrame) -> pd.DataFrame:
    groups = assign_groups(pooled["terminal_return"].astype(float))
    rows = []
    for group in ("WIN_50", "WIN_100", "LOSS_ANY", "LOSS_30", "LOSS_50", "LOSS_60"):
        subset = pooled[groups[group]]
        for field in ("lifecycle_class", "exit_type", "trade_status"):
            for level, count in subset[field].value_counts().items():
                rows.append({"group": group, "field": field, "level": level, "count": int(count), "share_pct": _round(count / len(subset) * 100.0)})
    return pd.DataFrame(rows)


def closed_only_sensitivity(pooled: pd.DataFrame, profile: pd.DataFrame, numeric: list[str], categorical: dict[str, list[str] | None]) -> list[dict[str, Any]]:
    closed = pooled[pooled["trade_status"].isin(CLOSED_STATUSES)]
    groups = assign_groups(closed["terminal_return"].astype(float))
    rows = []
    for _, prow in profile[profile["grade"].isin(["CONSISTENT", "MIXED"])].iterrows():
        result = compare_feature(closed, groups, prow["group"], prow["reference"], prow["feature"], prow["feature_kind"], prow["level"] if prow["feature_kind"] == "categorical" else None)
        rows.append({
            "comparison": prow["comparison"], "feature": prow["feature"], "level": prow["level"], "grade": prow["grade"],
            "all_effect": prow["effect"], "closed_only_effect": result.get("effect"),
            "closed_only_group_n": result.get("group_n"), "same_sign": _sign(prow["effect"]) == _sign(result.get("effect")),
        })
    return rows


def market_split(pooled: pd.DataFrame, profile: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for _, prow in profile[profile["grade"] == "CONSISTENT"].iterrows():
        if prow["feature"] == "market":
            continue
        entry = {"comparison": prow["comparison"], "feature": prow["feature"], "level": prow["level"], "pooled_effect": prow["effect"]}
        for market in ("KOSPI", "KOSDAQ"):
            subset = pooled[pooled["market"] == market]
            groups = assign_groups(subset["terminal_return"].astype(float))
            result = compare_feature(subset, groups, prow["group"], prow["reference"], prow["feature"], prow["feature_kind"], prow["level"] if prow["feature_kind"] == "categorical" else None)
            entry[f"{market}_effect"] = result.get("effect")
            entry[f"{market}_group_n"] = result.get("group_n")
        rows.append(entry)
    return rows


def quartile_descriptive(pooled: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    """극단 대비에서 CONSISTENT인 수치 feature의 pooled 사분위별 결과 비율(서술용, cutoff 제안 아님)."""
    extreme = profile[profile["extreme_contrast"] & (profile["grade"] == "CONSISTENT") & (profile["feature_kind"] == "numeric")]
    rows = []
    groups = assign_groups(pooled["terminal_return"].astype(float))
    for feature in sorted(extreme["feature"].unique()):
        values = pd.to_numeric(pooled[feature], errors="coerce")
        valid = values.notna()
        quartile = pd.qcut(values[valid].rank(method="first"), 4, labels=["Q1_LOW", "Q2", "Q3", "Q4_HIGH"])
        for label in ["Q1_LOW", "Q2", "Q3", "Q4_HIGH"]:
            mask = pd.Series(False, index=pooled.index)
            mask.loc[quartile.index[quartile == label]] = True
            n = int(mask.sum())
            row = {"feature": feature, "quartile": label, "trades": n,
                   "value_min": _round(values[mask].min(), 6), "value_max": _round(values[mask].max(), 6),
                   "mean_terminal_return": _round(pooled.loc[mask, "terminal_return"].mean())}
            for name in ("WIN_50", "WIN_100", "LOSS_30", "LOSS_50"):
                count = int((groups[name] & mask).sum())
                row[f"{name}_count"] = count
                row[f"{name}_rate_pct"] = _round(count / n * 100.0) if n else None
            rows.append(row)
    return pd.DataFrame(rows)


def run_analyze(network_audit: dict[str, int] | None = None) -> None:
    if not ENRICHMENT_PATH.exists():
        raise RuntimeError("ENRICHMENT_MISSING: run the enrich step first")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ledgers_raw = {w: load_window_ledger(w) for w in WINDOW_ORDER}
    gate = input_gate(ledgers_raw)
    inventory = build_inventory()
    inventory.to_csv(OUTPUT_DIR / "ledger_inventory.csv", index=False)

    exclusions = certification_exclusion_identities()
    pooled_raw, dedup_audit = deduplicate(ledgers_raw, exclusions)
    nesting = nesting_audit(ledgers_raw)
    enrichment = pd.read_csv(ENRICHMENT_PATH, dtype={"ticker": str, "isu_cd": str})
    enrichment["ticker"] = enrichment["ticker"].str.zfill(6)
    enrichment_audit = json.loads(ENRICHMENT_AUDIT_PATH.read_text(encoding="utf-8"))
    if enrichment_audit["enrichment_sha256"] != sha256_file(ENRICHMENT_PATH):
        raise RuntimeError("ENRICHMENT_SHA_MISMATCH")

    pooled = prepare_frame(pooled_raw, enrichment)
    ledgers = {w: prepare_frame(f[f["terminal_return"].notna()], enrichment) for w, f in ledgers_raw.items()}

    index_columns = [*IDENTITY_KEY, "name", "market", "representative_window", "observed_windows", "n_windows_observed",
                     "same_cutoff_return_spread", "trade_id", "pair_id", "trade_status", "exit_type", "terminal_return", "enrichment_status"]
    pooled[index_columns].to_csv(OUTPUT_DIR / "dedup_trade_index.csv", index=False)
    build_group_counts(pooled, ledgers).to_csv(OUTPUT_DIR / "group_counts.csv", index=False)

    profile, consistency = profile_tables(pooled, ledgers, NUMERIC_ENTRY_FEATURES, CATEGORICAL_ENTRY_FEATURES)
    profile.to_csv(OUTPUT_DIR / "entry_feature_profile.csv", index=False)
    consistency.to_csv(OUTPUT_DIR / "window_consistency.csv", index=False)
    profile[profile["extreme_contrast"]].to_csv(OUTPUT_DIR / "extreme_contrast.csv", index=False)

    post_profile, post_consistency = profile_tables(pooled, ledgers, NUMERIC_POST_ENTRY, CATEGORICAL_POST_ENTRY)
    post_profile.insert(0, "interpretation", "DESCRIPTIVE_ONLY_POST_ENTRY_OUTCOME_CONTAMINATED")
    post_profile.to_csv(OUTPUT_DIR / "post_entry_descriptive_profile.csv", index=False)
    mechanics = loser_mechanics(pooled)
    mechanics.to_csv(OUTPUT_DIR / "group_lifecycle_mechanics.csv", index=False)

    quartile_descriptive(pooled, profile).to_csv(OUTPUT_DIR / "entry_feature_quartile_descriptive.csv", index=False)
    sensitivity = closed_only_sensitivity(pooled, profile, NUMERIC_ENTRY_FEATURES, CATEGORICAL_ENTRY_FEATURES)
    markets = market_split(pooled, profile)
    grade_counts = profile.groupby(["comparison", "grade"]).size().unstack(fill_value=0).to_dict("index")
    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_WINNER_LOSER_PROFILE_V01",
        "strategy_id": STRATEGY_ID,
        "scope": "CONTROL only; existing certified simple-backtest ledgers; no backtest, signal generation, threshold change, or network",
        "source_selection_authority": SYNTHESIS_DOC,
        "windows": {w: {"ledger": _rel(BACKTEST_ROOT / WINDOWS[w]["run_dir"] / "control_trades.csv"), "verdict": WINDOWS[w]["verdict"], "cutoff": WINDOWS[w]["cutoff"]} for w in WINDOW_ORDER},
        "input_gate_synthesis_reproduction": gate,
        "return_contract": "terminal_return as recorded (OPEN_AT_CUTOFF marked to window cutoff, as in the synthesis); closed-only (REALIZED + LIFECYCLE_SETTLED) is a sensitivity check",
        "pooled_population_rule": "union of certification exclusion identities applied to every window before pooling; null terminal_return (authoritative-final unresolved) removed",
        "dedup": dedup_audit,
        "nesting": nesting,
        "enrichment_audit": {k: v for k, v in enrichment_audit.items() if k != "error_examples"},
        "features": {
            "numeric_entry": NUMERIC_ENTRY_FEATURES,
            "categorical_entry": CATEGORICAL_ENTRY_FEATURES,
            "constant_entry_fields_no_variance": constant_field_report(pooled),
            "window_dependent_fields": {"entry_kind": "derived from previous_exit_type; REENTRY vs FIRST_IN_WINDOW depends on window start"},
            "post_entry_descriptive_only": {"numeric": NUMERIC_POST_ENTRY, "categorical": list(CATEGORICAL_POST_ENTRY)},
            "unavailable_not_rebuilt": ["fixed 20/40/60 trading-day MAE/MFE", "first -15/-30/-40 touch date", "entry-time Pattern A score components beyond the FAST contract inputs"],
        },
        "grade_rules": GRADE_RULES,
        "group_counts_path": "group_counts.csv",
        "grade_counts_by_comparison": grade_counts,
        "closed_only_sensitivity": sensitivity,
        "market_split_for_consistent_features": markets,
        "network_requests": (network_audit or {"count": 0})["count"],
    }
    (OUTPUT_DIR / "winner_loser_profile_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"dedup_trade_count": dedup_audit["dedup_trade_count"], "grade_counts": grade_counts}, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Follow-up: lifecycle handoff 경로별 수익률 분포 (lifecycle)
# ---------------------------------------------------------------------------

LIFECYCLE_OUTPUT_DIR = OUTPUT_DIR / "lifecycle_return_profile_v01"
NORMAL = "NORMAL_EARLY_TREND_HANDOFF"
SKIPPED = "SKIPPED_EARLY_TREND_HANDOFF"
WITHOUT_DIRECT = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
COVERAGE = "COVERAGE_PATH_COMBINED"
NEVER = "NEVER_PROGRESSED"
LIFECYCLE_GROUPS: dict[str, set[str]] = {
    NORMAL: {NORMAL},
    SKIPPED: {SKIPPED},
    WITHOUT_DIRECT: {WITHOUT_DIRECT},
    COVERAGE: {SKIPPED, WITHOUT_DIRECT},
    NEVER: {NEVER},  # primary 비교에서 제외, 참고용
}
LIFECYCLE_COMPARISONS = [
    ("NORMAL_vs_COVERAGE_COMBINED", NORMAL, COVERAGE),
    ("NORMAL_vs_SKIPPED", NORMAL, SKIPPED),
    ("NORMAL_vs_WITHOUT_DIRECT", NORMAL, WITHOUT_DIRECT),
    ("SKIPPED_vs_WITHOUT_DIRECT", SKIPPED, WITHOUT_DIRECT),
]
# 방향 점검 지표 7개: (지표, 첫 그룹이 유리한 방향). +1은 클수록, -1은 작을수록 유리.
LIFECYCLE_KEY_METRICS = [
    ("mean_return", 1), ("median_return", 1), ("ge_50_rate_pct", 1), ("ge_100_rate_pct", 1),
    ("le_neg_30_rate_pct", -1), ("le_neg_50_rate_pct", -1), ("le_neg_60_rate_pct", -1),
]
# 판정 기준(결과 확인 전에 고정). 대상 비교는 NORMAL_vs_COVERAGE_COMBINED.
LIFECYCLE_VERDICT_RULES = {
    "primary_comparison": "NORMAL_vs_COVERAGE_COMBINED",
    "min_scope_group_n": 10,
    "min_pooled_group_n": 30,
    "min_evaluable_windows": 3,
    "strong_min_auc_effect": 0.10,
    "definition": {
        "INSUFFICIENT_EVIDENCE": "pooled NORMAL or COVERAGE n < 30, or fewer than 3 windows where both groups have n >= 10",
        "STRONG": "pooled ALL and CLOSED_ONLY: 0 unfavorable of 7 key metrics and >= 6 favorable; every evaluable ALL scope (5 windows + 2 disjoint periods) has <= 1 unfavorable; >= 80% of evaluable CLOSED_ONLY scopes have favorable > unfavorable; pooled ALL |AUC-0.5| >= 0.10",
        "MODERATE": "pooled ALL and CLOSED_ONLY have favorable > unfavorable, and >= 80% of evaluable ALL scopes have favorable > unfavorable",
        "MIXED": "otherwise",
        "favorable_rule": "strict difference in the favorable direction; a tie (including both rates 0) counts as neither",
    },
}


def lifecycle_group_frame(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    return frame[frame["lifecycle_class"].isin(LIFECYCLE_GROUPS[group])]


def lifecycle_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["terminal_return"].astype(float)
    n = int(len(returns))
    row: dict[str, Any] = {"trades": n}
    if n == 0:
        return row

    def rate(mask: pd.Series) -> float | None:
        return _round(mask.sum() / n * 100.0)

    row.update({
        "mean_return": _round(returns.mean()),
        "median_return": _round(returns.median()),
        "q25_return": _round(returns.quantile(0.25)),
        "q75_return": _round(returns.quantile(0.75)),
        "positive_rate_pct": rate(returns > 0),
    })
    for threshold in (30, 50, 100):
        row[f"ge_{threshold}_count"] = int((returns >= threshold).sum())
        row[f"ge_{threshold}_rate_pct"] = rate(returns >= threshold)
    for threshold in (15, 30, 40, 50, 60):
        row[f"le_neg_{threshold}_count"] = int((returns <= -threshold).sum())
        row[f"le_neg_{threshold}_rate_pct"] = rate(returns <= -threshold)
    status = frame["trade_status"]
    row["open_at_cutoff_rate_pct"] = rate(status == "OPEN_AT_CUTOFF")
    row["closed_rate_pct"] = rate(status.isin(CLOSED_STATUSES))
    for column in ("holding_days", "mfe", "mae", "peak_giveback"):
        values = pd.to_numeric(frame[column], errors="coerce")
        row[f"{column}_mean"] = _round(values.mean())
        row[f"{column}_median"] = _round(values.median())
    return row


def lifecycle_compare(first: pd.DataFrame, second: pd.DataFrame) -> dict[str, Any]:
    a, b = lifecycle_metrics(first), lifecycle_metrics(second)
    row: dict[str, Any] = {"first_n": a["trades"], "second_n": b["trades"]}
    if not a["trades"] or not b["trades"]:
        row.update({"favorable": None, "unfavorable": None})
        return row
    favorable = unfavorable = 0
    for metric, direction in LIFECYCLE_KEY_METRICS:
        diff = a[metric] - b[metric]
        row[f"{metric}_first"] = a[metric]
        row[f"{metric}_second"] = b[metric]
        row[f"{metric}_diff"] = _round(diff)
        signed = _sign(diff) * direction
        row[f"{metric}_favorable"] = {1: "FAVORABLE", -1: "UNFAVORABLE", 0: "TIE"}[signed]
        favorable += signed == 1
        unfavorable += signed == -1
    for metric in ("positive_rate_pct", "ge_30_rate_pct", "le_neg_15_rate_pct", "le_neg_40_rate_pct"):
        row[f"{metric}_diff"] = _round(a[metric] - b[metric])
    auc = rank_auc(first["terminal_return"].astype(float), second["terminal_return"].astype(float))
    row["return_auc"] = _round(auc)
    row["return_auc_effect"] = _round(auc - 0.5) if auc is not None else None
    row["favorable"] = int(favorable)
    row["unfavorable"] = int(unfavorable)
    return row


def lifecycle_scopes(pooled: pd.DataFrame, ledgers: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    early = pooled["entry_signal_date"] < DISJOINT_SPLIT_DATE
    scopes = {"POOLED_DEDUP": pooled}
    scopes.update({f"WINDOW_{w}": ledgers[w] for w in WINDOW_ORDER})
    scopes["ENTRY_BEFORE_2021"] = pooled[early]
    scopes["ENTRY_FROM_2021"] = pooled[~early]
    return scopes


def lifecycle_verdict(consistency: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    rules = LIFECYCLE_VERDICT_RULES
    rows = consistency[consistency["comparison"] == rules["primary_comparison"]]
    n_min = rules["min_scope_group_n"]

    def pick(scope: str, version: str) -> pd.Series:
        return rows[(rows["scope"] == scope) & (rows["version"] == version)].iloc[0]

    pooled_all, pooled_closed = pick("POOLED_DEDUP", "ALL"), pick("POOLED_DEDUP", "CLOSED_ONLY")
    sub = rows[rows["scope"] != "POOLED_DEDUP"]
    evaluable = sub[(sub["first_n"] >= n_min) & (sub["second_n"] >= n_min)]
    ev_all = evaluable[evaluable["version"] == "ALL"]
    ev_closed = evaluable[evaluable["version"] == "CLOSED_ONLY"]
    evaluable_windows = int(ev_all["scope"].str.startswith("WINDOW_").sum())
    majority_all = float((ev_all["favorable"] > ev_all["unfavorable"]).mean()) if len(ev_all) else 0.0
    majority_closed = float((ev_closed["favorable"] > ev_closed["unfavorable"]).mean()) if len(ev_closed) else 0.0
    detail = {
        "pooled_all_favorable_unfavorable": [int(pooled_all["favorable"]), int(pooled_all["unfavorable"])],
        "pooled_closed_favorable_unfavorable": [int(pooled_closed["favorable"]), int(pooled_closed["unfavorable"])],
        "pooled_all_return_auc": pooled_all["return_auc"],
        "evaluable_windows_all": evaluable_windows,
        "evaluable_scopes_all": int(len(ev_all)),
        "evaluable_scopes_closed_only": int(len(ev_closed)),
        "all_scopes_majority_favorable_share": round(majority_all, 4),
        "closed_scopes_majority_favorable_share": round(majority_closed, 4),
        "all_scopes_max_unfavorable": int(ev_all["unfavorable"].max()) if len(ev_all) else None,
    }
    if min(pooled_all["first_n"], pooled_all["second_n"]) < rules["min_pooled_group_n"] or evaluable_windows < rules["min_evaluable_windows"]:
        return "INSUFFICIENT_EVIDENCE", detail
    strong = (
        pooled_all["unfavorable"] == 0 and pooled_all["favorable"] >= 6
        and pooled_closed["unfavorable"] == 0 and pooled_closed["favorable"] >= 6
        and detail["all_scopes_max_unfavorable"] is not None and detail["all_scopes_max_unfavorable"] <= 1
        and majority_closed >= 0.8
        and abs(float(pooled_all["return_auc_effect"])) >= rules["strong_min_auc_effect"]
    )
    if strong:
        return "NORMAL_HANDOFF_STRONGLY_ASSOCIATED_WITH_BETTER_RETURN_DISTRIBUTION", detail
    moderate = (
        pooled_all["favorable"] > pooled_all["unfavorable"]
        and pooled_closed["favorable"] > pooled_closed["unfavorable"]
        and majority_all >= 0.8
    )
    if moderate:
        return "NORMAL_HANDOFF_MODERATELY_ASSOCIATED_WITH_BETTER_RETURN_DISTRIBUTION", detail
    return "LIFECYCLE_RETURN_DIFFERENCE_MIXED", detail


def lifecycle_tail_concentration(pooled: pd.DataFrame, version: str) -> list[dict[str, Any]]:
    returns = pooled["terminal_return"].astype(float)
    tails = {
        "ge_50": returns >= 50, "ge_100": returns >= 100,
        "le_neg_30": returns <= -30, "le_neg_40": returns <= -40, "le_neg_50": returns <= -50, "le_neg_60": returns <= -60,
    }
    rows = []
    total = len(pooled)
    for group in (NORMAL, SKIPPED, WITHOUT_DIRECT, COVERAGE, NEVER):
        mask = pooled["lifecycle_class"].isin(LIFECYCLE_GROUPS[group])
        trade_share = mask.sum() / total * 100.0
        for tail, tail_mask in tails.items():
            tail_total = int(tail_mask.sum())
            count = int((mask & tail_mask).sum())
            share = count / tail_total * 100.0 if tail_total else None
            rows.append({
                "version": version, "lifecycle_group": group, "tail": tail,
                "group_trades": int(mask.sum()), "group_trade_share_pct": _round(trade_share),
                "tail_count_in_group": count, "tail_total": tail_total,
                "tail_share_in_group_pct": _round(share),
                "concentration_ratio": _round(share / trade_share) if share is not None and trade_share else None,
                "tail_open_at_cutoff_count": int((mask & tail_mask & (pooled["trade_status"] == "OPEN_AT_CUTOFF")).sum()),
            })
    return rows


def run_lifecycle(network_audit: dict[str, int]) -> None:
    LIFECYCLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ledgers_raw = {w: load_window_ledger(w) for w in WINDOW_ORDER}
    gate = input_gate(ledgers_raw)
    pooled, dedup_audit = deduplicate(ledgers_raw, certification_exclusion_identities())
    index = pd.read_csv(OUTPUT_DIR / "dedup_trade_index.csv", dtype={"ticker": str, "isu_cd": str})
    index["ticker"] = index["ticker"].str.zfill(6)
    check = pooled[IDENTITY_KEY + ["terminal_return"]].merge(index[IDENTITY_KEY + ["terminal_return"]], on=IDENTITY_KEY, how="outer", indicator=True)
    if len(pooled) != len(index) or (check["_merge"] != "both").any() or (check["terminal_return_x"] - check["terminal_return_y"]).abs().max() > 1e-9:
        raise RuntimeError("LIFECYCLE_POOLED_DOES_NOT_MATCH_DEDUP_TRADE_INDEX")
    ledgers = {w: f[f["terminal_return"].notna()] for w, f in ledgers_raw.items()}

    profile_rows, closed_rows, consistency_rows = [], [], []
    for scope, frame in lifecycle_scopes(pooled, ledgers).items():
        for version in ("ALL", "CLOSED_ONLY"):
            data = frame if version == "ALL" else frame[frame["trade_status"].isin(CLOSED_STATUSES)]
            if scope == "POOLED_DEDUP":
                for group in LIFECYCLE_GROUPS:
                    row = {"scope": scope, "version": version, "lifecycle_group": group,
                           "role": "REFERENCE_ONLY" if group == NEVER else "PRIMARY",
                           **lifecycle_metrics(lifecycle_group_frame(data, group))}
                    (profile_rows if version == "ALL" else closed_rows).append(row)
            for comparison, first, second in LIFECYCLE_COMPARISONS:
                consistency_rows.append({
                    "scope": scope, "version": version, "comparison": comparison, "first": first, "second": second,
                    **lifecycle_compare(lifecycle_group_frame(data, first), lifecycle_group_frame(data, second)),
                })
    profile = pd.DataFrame(profile_rows)
    closed = pd.DataFrame(closed_rows)
    consistency = pd.DataFrame(consistency_rows)
    tails = pd.DataFrame(
        lifecycle_tail_concentration(pooled, "ALL")
        + lifecycle_tail_concentration(pooled[pooled["trade_status"].isin(CLOSED_STATUSES)], "CLOSED_ONLY")
    )
    profile.to_csv(LIFECYCLE_OUTPUT_DIR / "lifecycle_return_profile.csv", index=False)
    closed.to_csv(LIFECYCLE_OUTPUT_DIR / "lifecycle_return_profile_closed_only.csv", index=False)
    consistency.to_csv(LIFECYCLE_OUTPUT_DIR / "lifecycle_window_consistency.csv", index=False)
    tails.to_csv(LIFECYCLE_OUTPUT_DIR / "lifecycle_extreme_tail_comparison.csv", index=False)

    verdict, detail = lifecycle_verdict(consistency)
    signs = {}
    for comparison, _, _ in LIFECYCLE_COMPARISONS:
        for version in ("ALL", "CLOSED_ONLY"):
            sub = consistency[(consistency["comparison"] == comparison) & (consistency["version"] == version)]
            signs[f"{comparison}|{version}"] = {
                r["scope"]: (f"{r['favorable']}F/{r['unfavorable']}U n={r['first_n']}/{r['second_n']}" if r["favorable"] is not None else "NA")
                for _, r in sub.iterrows()
            }
    summary = {
        "work_id": "PATTERN_A_FAST_CORE_V2_LIFECYCLE_HANDOFF_RETURN_PROFILE_V01",
        "parent_work": "PATTERN_A_FAST_CORE_V2_WINNER_LOSER_PROFILE_V01",
        "strategy_id": STRATEGY_ID,
        "scope": "CONTROL only; same certified ledgers, pooled dedup and exclusion rules as the parent; lifecycle_class is a post-entry state, not an entry feature; no backtest, enrich, threshold change, or network",
        "input_gate_synthesis_reproduction_match": {w: v["match"] for w, v in gate.items()},
        "pooled_matches_parent_dedup_trade_index": True,
        "dedup_trade_count": dedup_audit["dedup_trade_count"],
        "return_contract": "terminal_return as recorded (OPEN_AT_CUTOFF marked to window cutoff); CLOSED_ONLY = REALIZED + LIFECYCLE_SETTLED",
        "window_scope_population": "each window's own certified population (no pooled exclusion union), as in the parent window_consistency",
        "lifecycle_groups": {k: sorted(v) for k, v in LIFECYCLE_GROUPS.items()},
        "key_metrics_favorable_direction": dict(LIFECYCLE_KEY_METRICS),
        "verdict_rules": LIFECYCLE_VERDICT_RULES,
        "verdict": verdict,
        "verdict_detail": detail,
        "favorable_unfavorable_by_scope": signs,
        "network_requests": network_audit["count"],
    }
    (LIFECYCLE_OUTPUT_DIR / "lifecycle_return_profile_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": verdict, **detail}, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["enrich", "analyze", "lifecycle"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.step == "enrich":
        run_enrich(args.workers)
    else:
        audit = {"count": 0}
        with network_guard(audit):
            if args.step == "analyze":
                run_analyze(audit)
            else:
                run_lifecycle(audit)


if __name__ == "__main__":
    main()
