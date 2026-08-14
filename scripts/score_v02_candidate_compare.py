"""Pattern A Score Design v0.2 Candidate 비교 스크립트.

목적: v0.1 OOS Case Validation에서 실제로 재현된 두 실패 메커니즘
(SKC형 Core/Supporting, LG/한국타이어형 alignment bonus)과 Pattern A/B
경계 문제(넷마블)를 구조적으로 해결하는 v0.2 후보를 development set에서
비교한다. 최종 후보를 자동으로 고르지 않는다 — 표만 만들고 선택은
문서(docs/patterns/pattern_a.md의 Score Design v0.2 절)에 사람이 기록한다.

**Pattern A 점수 코드(pattern_a_score.py) 자체는 이 스크립트에서 건드리지
않는다** — Candidate A는 score_pattern_a()를 그대로 호출한 결과다(재구현이
아니라 진짜 v0.1 baseline). Candidate B/C는 이 스크립트 안에서만 존재하는
로컬 함수다 — freeze가 결정되기 전까지 프로덕션 코드에는 아무것도 넣지
않는다(git status로 확인 가능).

Transition Candidate:
    A. v0.1 그대로: 0.60*ma24_core + 0.20*weekly + 0.20*acceleration (가중합)
    B. Core gating: core_score(ma24_slope)가 낮으면 support_score(weekly/
       acceleration 평균)의 기여를 support_multiplier로 깎는다.
    C. Core + confirmation: Supporting은 독립 점수가 아니라 core_score가
       이미 일정 수준 이상일 때만 추가되는 confirmation bonus다.

Alignment Candidate(Transition 구조와 별개로 4개 비교, item 8):
    A. 현재 +8 유지  B. 축소(+4)  C. Core-strength 조건부  D. 완전 제거(0)

새 downtrend 구조 신호 후보 2개(item 9, analysis-only — FeatureRow/
PATTERN_A_FEATURE_SCOPE/Score 어디에도 아직 연결하지 않는다):
    long_term_high_slope_36m, prior_leg_drift_36m
    (trend_scanner.features.downtrend_structure, look-ahead 방지는
    HistoricalSnapshot.monthly가 이미 보장한다)

새 KRX fetch 없음 — 기존 historical_snapshot 캐시(exploration/holdout/
negative_control/OOS v0.1 29건)만 재사용한다. OOS2는 선정도 계산도 하지
않는다.

**버전 고정 안내(중요)**: 이 스크립트는 pattern_a_score.py가 아직 v0.1인
시점(freeze 이전 commit)에 실행해서 결과를 기록했다 — 그때는 Candidate
A(`score_pattern_a()` 직접 호출)가 진짜 v0.1 baseline이었다. freeze 이후
(v0.2가 pattern_a_score.py에 반영된 뒤) 이 스크립트를 다시 실행하면
Candidate A도 v0.2를 반환하므로 "A=v0.1, B/C=신규 후보"라는 비교 전제가
깨진다 — 재실행 결과를 v0.1 대비 비교로 쓰지 말 것. 이 스크립트는 그
당시 실행 결과(CSV/print 출력, docs/patterns/pattern_a.md에 옮겨 적음)를
남기기 위한 기록용 스크립트다.

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/score_v02_candidate_compare.py

CSV: data/processed/score_v02_candidate_compare.csv (로컬 전용, data/
전체가 gitignore).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.features.downtrend_structure import (
    long_term_high_slope_36m,
    prior_leg_drift_36m,
)
from trend_scanner.patterns.pattern_a_score import (
    ALIGNMENT_BONUS,
    MA24_SLOPE_ACCELERATION_POINTS,
    MA24_SLOPE_POINTS,
    WEEKLY_MA12_SLOPE_POINTS,
    _harmonic_mean,
    _is_missing,
    _piecewise_linear,
    _transition_alignment,
    score_pattern_a,
)
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
)
from trend_scanner.validation.oos_v01_manifest import (
    OOS_V01_DIAGNOSTIC_SNAPSHOTS,
    OOS_V01_STAGE_AUDIT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "score_v02_candidate_compare.csv"

# scripts/score_design_validate.py / base_expansion_validate.py와 동일한
# 종목/날짜(재정의가 아니라 그대로 옮긴 것 — 이 스크립트 하나로 재현
# 가능하도록 중복을 감수하는 이 repo의 기존 관례를 그대로 따른다).
EXPLORATION_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "068270", "name": "셀트리온", "date": "2019-12-31", "label": "pre_breakout"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-12-31", "label": "trend_progressed"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "035420", "name": "NAVER", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "005930", "name": "삼성전자", "date": "2019-09-30", "label": "pre_breakout"},
    {"ticker": "005930", "name": "삼성전자", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "005930", "name": "삼성전자", "date": "2021-03-31", "label": "trend_progressed"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-03-31", "label": "pre_breakout"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-12-31", "label": "early_trend"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2024-06-30", "label": "trend_progressed"},
]

HOLDOUT_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "005380", "name": "현대차", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "005380", "name": "현대차", "date": "2020-08-31", "label": "early_trend"},
    {"ticker": "005380", "name": "현대차", "date": "2021-02-28", "label": "trend_progressed"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "051910", "name": "LG화학", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "000270", "name": "기아", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "000270", "name": "기아", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "000270", "name": "기아", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "012330", "name": "현대모비스", "date": "2024-11-30", "label": "pre_breakout"},
    {"ticker": "012330", "name": "현대모비스", "date": "2025-06-30", "label": "early_trend"},
    {"ticker": "012330", "name": "현대모비스", "date": "2026-02-28", "label": "trend_progressed"},
]

NEGATIVE_CONTROL_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "003550", "name": "LG", "date": "2020-12-31", "label": "failed_breakout"},
    {"ticker": "010130", "name": "고려아연", "date": "2022-06-30", "label": "failed_breakout"},
    {"ticker": "011170", "name": "롯데케미칼", "date": "2023-01-31", "label": "failed_higher_low"},
    {"ticker": "009150", "name": "삼성전기", "date": "2022-12-31", "label": "failed_momentum"},
    {"ticker": "018260", "name": "삼성에스디에스", "date": "2023-07-31", "label": "failed_breakout"},
    {"ticker": "032830", "name": "삼성생명", "date": "2021-02-28", "label": "failed_ma24_turn"},
    {"ticker": "034730", "name": "SK", "date": "2020-12-31", "label": "failed_weekly_turn"},
    {"ticker": "011200", "name": "HMM", "date": "2024-10-31", "label": "failed_breakout"},
]

NEGATIVE_SUBGROUP: dict[str, str] = {
    "003550": "confirmed_negative",
    "010130": "confirmed_negative",
    "011170": "confirmed_negative",
    "032830": "confirmed_negative",
    "034730": "confirmed_negative",
    "009150": "ambiguous_negative",
    "018260": "ambiguous_negative",
    "011200": "ambiguous_negative",
}

# 특히 주목해서 별도 표로 뽑아볼 known false positive / 진단 케이스.
# (source, ticker, snapshot_date, 별칭)
KNOWN_FP_CASES: list[tuple[str, str, str, str]] = [
    ("negative_control", "003550", "2020-12-31", "LG(alignment FP)"),
    ("oos", "161390", "2024-04-30", "한국타이어(alignment FP)"),
    ("oos", "011790", "2024-06-30", "SKC(Core/Supporting FP)"),
    ("oos", "251270", "2020-08-31", "넷마블 boundary(A/B 경계)"),
]
CLEAN_EARLY_CASE = ("oos", "005490", "2023-03-31")  # 가장 깨끗한 audited EARLY_TREND
FAST_MOVER_CASES = [
    ("oos", "042660", "2024-10-31", "positive_pre_breakout"),
    ("oos", "042660", "2025-01-31", "positive_early_trend(EARLY/PROGRESSED 경계)"),
    ("oos", "042660", "2025-07-31", "positive_trend_progressed"),
]

FEATURE_ATTRS = (
    "range_36m",
    "avg_price_change_12m",
    "ma_spread",
    "ma24_slope",
    "weekly_ma12_slope",
    "ma24_slope_acceleration",
    "range_position",
)


def _feature_values(features: Any) -> dict[str, float]:
    return {name: getattr(features, name) for name in FEATURE_ATTRS}


# --- Candidate B: Core gating ---
CORE_WEIGHT = 0.60
SUPPORT_WEIGHT = 0.40
# core_score가 낮을 때 support 기여를 얼마나 깎을지(설명 가능한 3구간
# piecewise). raw ma24_slope가 아니라 이미 0~100으로 변환된 core_score를
# gate 기준으로 쓴다(item 5 권장안 — threshold를 새로 하나 더 만들지
# 않기 위해 MA24_SLOPE_POINTS가 만든 스케일을 그대로 재사용).
CORE_GATE_POINTS: tuple[tuple[float, float], ...] = ((0.0, 0.0), (30.0, 0.25), (60.0, 1.0), (100.0, 1.0))

# --- Candidate C: Core + confirmation ---
CONFIRMATION_MAX = 20.0
# core_score가 50 미만이면 confirmation 기여가 0(= Supporting이 Core
# 없이 점수를 만들 수 없다), 80 이상이면 최대 확인 보너스를 전부 인정.
CONFIRMATION_GATE_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (50.0, 0.0),
    (80.0, 1.0),
    (100.0, 1.0),
)

# --- Alignment candidates ---
ALIGN_REDUCED_BONUS = 4.0
ALIGN_CORE_STRONG_THRESHOLD = 60.0  # Candidate B의 CORE_GATE_POINTS "full contribution" 지점과 동일값 재사용
ALIGN_CORE_STRONG_BONUS = 8.0
ALIGN_CORE_WEAK_BONUS = 3.0


def _core_score(ma24_slope: float) -> float | None:
    if _is_missing(ma24_slope):
        return None
    return _piecewise_linear(ma24_slope, MA24_SLOPE_POINTS)


def _support_score(weekly: float, accel: float) -> float | None:
    parts = []
    if not _is_missing(weekly):
        parts.append(_piecewise_linear(weekly, WEEKLY_MA12_SLOPE_POINTS))
    if not _is_missing(accel):
        parts.append(_piecewise_linear(accel, MA24_SLOPE_ACCELERATION_POINTS))
    if not parts:
        return None
    return sum(parts) / len(parts)


def candidate_b_transition(fv: dict[str, float]) -> dict[str, float | None]:
    core = _core_score(fv.get("ma24_slope"))
    if core is None:
        return {"transition_b": None, "core_score": None, "support_score": None, "support_multiplier": None}
    support = _support_score(fv.get("weekly_ma12_slope"), fv.get("ma24_slope_acceleration"))
    if support is None:
        return {"transition_b": core, "core_score": core, "support_score": None, "support_multiplier": None}
    multiplier = _piecewise_linear(core, CORE_GATE_POINTS)
    transition = CORE_WEIGHT * core + SUPPORT_WEIGHT * support * multiplier
    return {
        "transition_b": transition,
        "core_score": core,
        "support_score": support,
        "support_multiplier": multiplier,
    }


def candidate_c_transition(fv: dict[str, float]) -> dict[str, float | None]:
    core = _core_score(fv.get("ma24_slope"))
    if core is None:
        return {
            "transition_c": None,
            "core_score": None,
            "support_score": None,
            "confirmation_gate": None,
            "confirmation_bonus": None,
        }
    support = _support_score(fv.get("weekly_ma12_slope"), fv.get("ma24_slope_acceleration"))
    if support is None:
        return {
            "transition_c": core,
            "core_score": core,
            "support_score": None,
            "confirmation_gate": None,
            "confirmation_bonus": 0.0,
        }
    gate = _piecewise_linear(core, CONFIRMATION_GATE_POINTS)
    confirmation_bonus = CONFIRMATION_MAX * (support / 100.0) * gate
    transition = min(100.0, core + confirmation_bonus)
    return {
        "transition_c": transition,
        "core_score": core,
        "support_score": support,
        "confirmation_gate": gate,
        "confirmation_bonus": confirmation_bonus,
    }


def align_variants(fv: dict[str, float], core_score: float | None) -> dict[str, float]:
    aligned = _transition_alignment(fv)
    a_keep = ALIGNMENT_BONUS if aligned else 0.0
    b_reduced = ALIGN_REDUCED_BONUS if aligned else 0.0
    if not aligned or core_score is None:
        c_conditional = 0.0
    elif core_score >= ALIGN_CORE_STRONG_THRESHOLD:
        c_conditional = ALIGN_CORE_STRONG_BONUS
    else:
        c_conditional = ALIGN_CORE_WEAK_BONUS
    return {
        "align_a_keep8": a_keep,
        "align_b_reduced4": b_reduced,
        "align_c_core_conditional": c_conditional,
        "align_d_removed": 0.0,
    }


def _final_score(
    base_score: float | None, transition_score: float | None, align_bonus: float, penalty: float
) -> float | None:
    if base_score is None or transition_score is None:
        return None
    balanced = _harmonic_mean(base_score, transition_score)
    if balanced is None:
        return None
    return max(0.0, min(100.0, balanced + align_bonus - penalty))


def _load_daily(cache: ParquetCache, tickers: dict[str, str]) -> dict[str, pd.DataFrame]:
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(f"{ticker} 캐시가 없습니다. 새로 fetch하지 않습니다 — 먼저 캐시를 채워주세요.")
        daily_by_ticker[ticker] = daily
    return daily_by_ticker


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    exploration_tickers = {s["ticker"]: s["name"] for s in EXPLORATION_SNAPSHOTS}
    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}
    negative_tickers = {s["ticker"]: s["name"] for s in NEGATIVE_CONTROL_SNAPSHOTS}
    oos_tickers = {s.ticker: s.name for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS}

    exploration_daily = _load_daily(cache, exploration_tickers)
    holdout_daily = _load_daily(cache, holdout_tickers)
    negative_daily = _load_daily(cache, negative_tickers)
    oos_daily = _load_daily(cache, oos_tickers)

    records: list[dict] = []

    def _add_record(
        source: str, group: str, ticker: str, name: str, date: str, label: str, audited_label: str | None,
        snap: HistoricalSnapshot,
    ) -> None:
        result = score_pattern_a(snap.features)
        row: dict[str, Any] = {
            "source": source,
            "group": group,
            "ticker": ticker,
            "name": name,
            "date": date,
            "label": label,
            "audited_label": audited_label,
            "insufficient_data": result.flags.get("insufficient_data", False),
            "base_score": result.base_score,
            "final_a": result.pattern_a_score,
            "transition_a": result.transition_score,
            "align_v01_bonus": result.alignment_bonus,
            "progressed_penalty": result.progressed_penalty,
            "progressed_evidence_count": result.progressed_evidence_count,
            "long_term_high_slope_36m": long_term_high_slope_36m(snap.monthly),
            "prior_leg_drift_36m": prior_leg_drift_36m(snap.monthly),
        }
        for name_ in FEATURE_ATTRS:
            row[name_] = getattr(snap.features, name_)

        if result.flags.get("insufficient_data", False):
            row.update(
                {
                    "transition_b": None,
                    "transition_c": None,
                    "core_score": None,
                    "support_score": None,
                    "final_b_align01": None,
                    "final_c_align01": None,
                }
            )
            for k in ("align_a_keep8", "align_b_reduced4", "align_c_core_conditional", "align_d_removed"):
                row[k] = None
            for cand in ("a", "b", "c"):
                for align_name in ("keep8", "reduced4", "core_conditional", "removed"):
                    row[f"final_{cand}_align_{align_name}"] = None
            records.append(row)
            return

        fv = _feature_values(snap.features)
        b = candidate_b_transition(fv)
        c = candidate_c_transition(fv)
        row["transition_b"] = b["transition_b"]
        row["transition_c"] = c["transition_c"]
        row["core_score"] = b["core_score"]
        row["support_score"] = b["support_score"]
        row["support_multiplier"] = b.get("support_multiplier")
        row["confirmation_gate"] = c.get("confirmation_gate")
        row["confirmation_bonus"] = c.get("confirmation_bonus")

        # stage 1: transition만 비교 (alignment는 v0.1 그대로 고정)
        row["final_a"] = result.pattern_a_score
        row["final_b_align01"] = _final_score(
            result.base_score, b["transition_b"], result.alignment_bonus, result.progressed_penalty
        )
        row["final_c_align01"] = _final_score(
            result.base_score, c["transition_c"], result.alignment_bonus, result.progressed_penalty
        )

        # stage 2: 각 transition candidate x alignment candidate 전체 grid
        aligns = align_variants(fv, b["core_score"])
        row.update(aligns)
        transitions = {"a": result.transition_score, "b": b["transition_b"], "c": c["transition_c"]}
        align_map = {
            "keep8": aligns["align_a_keep8"],
            "reduced4": aligns["align_b_reduced4"],
            "core_conditional": aligns["align_c_core_conditional"],
            "removed": aligns["align_d_removed"],
        }
        for cand_name, cand_transition in transitions.items():
            for align_name, align_bonus in align_map.items():
                row[f"final_{cand_name}_align_{align_name}"] = _final_score(
                    result.base_score, cand_transition, align_bonus, result.progressed_penalty
                )

        records.append(row)

    for s in EXPLORATION_SNAPSHOTS:
        daily = exploration_daily[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("exploration", f"exploration_{s['label']}", s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in HOLDOUT_SNAPSHOTS:
        daily = holdout_daily[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("holdout", f"holdout_{s['label']}", s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in NEGATIVE_CONTROL_SNAPSHOTS:
        daily = negative_daily[s["ticker"]]
        subgroup = NEGATIVE_SUBGROUP[s["ticker"]]
        snap = build_historical_snapshot(s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False)
        _add_record("negative_control", subgroup, s["ticker"], s["name"], s["date"], s["label"], None, snap)

    for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        daily = oos_daily[s.ticker]
        audited = OOS_V01_STAGE_AUDIT.get((s.ticker, s.snapshot_date))
        audited_label = audited.audited_stage_label if audited is not None else None
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        _add_record("oos", s.original_group, s.ticker, s.name, s.snapshot_date, s.original_group, audited_label, snap)

    df = pd.DataFrame(records)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    # --- Stage 1: Transition Candidate A/B/C (alignment은 v0.1 고정) ---
    print("=" * 100)
    print("[Stage 1] Transition Candidate A/B/C 그룹별 final score (alignment=v0.1 고정) min/median/max")
    print("=" * 100)
    for group in dict.fromkeys(df["group"]):
        sub = df[df["group"] == group]
        row = {"group": group, "n": len(sub)}
        for col, label in [("final_a", "A"), ("final_b_align01", "B"), ("final_c_align01", "C")]:
            values = sub[col].dropna()
            if values.empty:
                row[f"{label}_median"] = float("nan")
                row[f"{label}_min"] = float("nan")
                row[f"{label}_max"] = float("nan")
            else:
                row[f"{label}_median"] = values.median()
                row[f"{label}_min"] = values.min()
                row[f"{label}_max"] = values.max()
        print(
            f"{group:<32} n={row['n']:>2}  "
            f"A(min/med/max)={row['A_min']:.1f}/{row['A_median']:.1f}/{row['A_max']:.1f}  "
            f"B={row['B_min']:.1f}/{row['B_median']:.1f}/{row['B_max']:.1f}  "
            f"C={row['C_min']:.1f}/{row['C_median']:.1f}/{row['C_max']:.1f}"
        )
    print()

    # --- Known FP 4건 ---
    print("=" * 100)
    print("[Known FP] LG / 한국타이어 / SKC / 넷마블 boundary — transition/align/final 비교")
    print("=" * 100)
    for source, ticker, date, alias in KNOWN_FP_CASES:
        sub = df[(df["source"] == source) & (df["ticker"] == ticker) & (df["date"] == date)]
        if sub.empty:
            print(f"{alias}: 레코드 없음")
            continue
        r = sub.iloc[0]
        print(
            f"{alias:<26} core={r['core_score']:.1f} support={r['support_score']} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"align_v01={r['align_v01_bonus']:.1f}  final A/B/C(align v0.1)={r['final_a']:.1f}/"
            f"{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- Clean early case ---
    print("=" * 100)
    print("[Clean early case] 005490 2023-03-31 (가장 깨끗한 audited EARLY_TREND)")
    print("=" * 100)
    sub = df[(df["ticker"] == CLEAN_EARLY_CASE[1]) & (df["date"] == CLEAN_EARLY_CASE[2])]
    if not sub.empty:
        r = sub.iloc[0]
        print(
            f"core={r['core_score']:.1f} support={r['support_score']:.1f} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"final A/B/C(align v0.1)={r['final_a']:.1f}/{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- 042660 fast mover ---
    print("=" * 100)
    print("[042660 한화오션 fast mover] base/transition/penalty/final A/B/C 비교")
    print("=" * 100)
    for source, ticker, date, label in FAST_MOVER_CASES:
        sub = df[(df["ticker"] == ticker) & (df["date"] == date)]
        if sub.empty:
            continue
        r = sub.iloc[0]
        print(
            f"{date} ({label:<45}) base={r['base_score']:.1f} "
            f"transition A/B/C={r['transition_a']:.1f}/{r['transition_b']:.1f}/{r['transition_c']:.1f}  "
            f"penalty={r['progressed_penalty']:.1f} evidence={r['progressed_evidence_count']}  "
            f"final A/B/C(align v0.1)={r['final_a']:.1f}/{r['final_b_align01']:.1f}/{r['final_c_align01']:.1f}"
        )
    print()

    # --- 새 downtrend Feature 그룹별 raw value ---
    print("=" * 100)
    print("[새 Feature] long_term_high_slope_36m / prior_leg_drift_36m 그룹별 min/median/max")
    print("=" * 100)
    for group in dict.fromkeys(df["group"]):
        sub = df[df["group"] == group]
        for col in ("long_term_high_slope_36m", "prior_leg_drift_36m"):
            values = sub[col].dropna()
            if values.empty:
                continue
            print(f"{group:<32} {col:<26} n={len(values):>2} min={values.min():+.4f} median={values.median():+.4f} max={values.max():+.4f}")
    print()

    print("=" * 100)
    print("[새 Feature] downtrend_reversal_boundary vs positive_pre_breakout 종목별 raw value")
    print("=" * 100)
    for group in ("downtrend_reversal_boundary", "positive_pre_breakout"):
        sub = df[df["group"] == group]
        for _, r in sub.iterrows():
            print(
                f"{group:<28} {r['ticker']} {r['name']:<12} {r['date']}  "
                f"avg_price_change_12m={r['avg_price_change_12m']!s:>10}  "
                f"long_term_high_slope_36m={r['long_term_high_slope_36m']!s:>10}  "
                f"prior_leg_drift_36m={r['prior_leg_drift_36m']!s:>10}"
            )
    print()


if __name__ == "__main__":
    main()
