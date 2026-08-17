"""Phase 13C Pattern A Fast Human Ground Truth Dataset — preparation helpers.

Research/validation-only. Reuses the frozen Pattern A production evaluator
(``evaluate_pattern_a``, ``build_historical_snapshot``) strictly as read-only
Benchmark / Context (see docs/specs/pattern_a_fast_definition.md §2). This
module never computes or fills ``weekly_stage_at_reference`` (Pattern A Fast
Weekly Lifecycle Stage, docs/specs/pattern_a_fast_lifecycle_contract.md) or
``human_label`` — those are Human Annotation fields (Phase 13C-2) and are
left ``UNLABELED`` by every function here.

Data access is cache-only (``ParquetCache``), never through
``MarketDataRepository``/``PyKrxDataProvider`` (whose job includes
incremental network fetch) — a missing ticker is reported as
``DATA_UNAVAILABLE``/``CACHE_MISSING``, never fetched.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

UNLABELED = "UNLABELED"
NOT_OBSERVED = "NOT_OBSERVED"
NOT_EVALUATED = "NOT_EVALUATED"
NOT_APPLICABLE = "NOT_APPLICABLE"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
CACHE_MISSING = "CACHE_MISSING"


def load_raw_daily(ticker: str, cache: ParquetCache | None = None) -> pd.DataFrame | None:
    """캐시 전용 daily OHLCV 로드. 캐시에 없으면 네트워크로 채우지 않고 None을 반환한다."""
    cache = cache or ParquetCache()
    return cache.load(ticker)


@dataclass(frozen=True)
class ReferenceSnapshot:
    """reference_date 시점 Pattern A Benchmark Context (Fast Ground Truth 아님)."""

    ticker: str
    reference_date: pd.Timestamp | None
    data_status: str
    pattern_a_stage: str | None
    pattern_a_candidate_state: str | None
    pattern_a_score: float | None


def resolve_completed_weekly_reference(
    ticker: str, name: str, daily: pd.DataFrame, target_date: str | pd.Timestamp
) -> pd.Timestamp | None:
    """target_date 이하에서 완료된(W-FRI) 주봉 기준일을 반환한다. 없으면 None.

    §35 Exact Reference Date: 가장 가까운 전일/다음날로 silent substitution하지
    않는다 — ``build_historical_snapshot``의 completed-weekly 판정을 그대로
    재사용해, 반환값은 항상 실제 완료 주봉 라벨이거나 None이다.
    """
    snapshot = build_historical_snapshot(
        ticker, name, daily, target_date, include_incomplete_periods=False
    )
    return snapshot.weekly_as_of


def compute_reference_snapshot(
    ticker: str, name: str, daily: pd.DataFrame, reference_date: pd.Timestamp
) -> ReferenceSnapshot:
    """reference_date가 실제 완료 주봉 라벨일 때만 Pattern A Benchmark Context를 계산한다.

    reference_date가 완료 주봉 라벨이 아니면(=미완성 주봉이거나 데이터 범위 밖)
    DATA_UNAVAILABLE로 fail-closed 처리하고 추정/보정하지 않는다.
    """
    snapshot = build_historical_snapshot(
        ticker, name, daily, reference_date, include_incomplete_periods=False
    )
    if snapshot.weekly_as_of is None or snapshot.weekly_as_of != pd.Timestamp(reference_date):
        return ReferenceSnapshot(ticker, None, DATA_UNAVAILABLE, None, None, None)

    result = evaluate_pattern_a(snapshot)
    stage = result.stage
    return ReferenceSnapshot(
        ticker=ticker,
        reference_date=snapshot.weekly_as_of,
        data_status="OK",
        pattern_a_stage=stage.value if stage else None,
        pattern_a_candidate_state=(
            result.candidate_state.value if result.candidate_state else None
        ),
        pattern_a_score=result.score,
    )


def first_stage_dates_after(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    reference_date: pd.Timestamp,
    horizon_weeks: int = 104,
) -> tuple[str | pd.Timestamp, str | pd.Timestamp]:
    """reference_date 이후 horizon_weeks 이내에서 Pattern A가 처음 TRANSITION /
    EARLY_TREND에 도달한 완료 주봉 날짜(Benchmark Context, 사후 조회).

    이 함수의 결과는 Pattern A 자체의 사후 벤치마크일 뿐이며,
    weekly_stage_at_reference나 human_label 계산에는 절대 쓰지 않는다
    (미래 데이터는 reference 시점 PIT 판단에 섞이지 않는다).
    둘 다 못 찾으면 각각 NOT_APPLICABLE.
    """
    weekly_index = to_weekly(daily).index
    horizon_end = reference_date + pd.Timedelta(weeks=horizon_weeks)
    data_end = daily.index.max()
    candidates = [d for d in weekly_index if reference_date < d <= horizon_end and d <= data_end]

    transition_first: str | pd.Timestamp = NOT_APPLICABLE
    early_trend_first: str | pd.Timestamp = NOT_APPLICABLE
    for d in candidates:
        snap = build_historical_snapshot(ticker, name, daily, d, include_incomplete_periods=False)
        if snap.weekly_as_of != d:
            continue
        stage = evaluate_pattern_a(snap).stage
        if transition_first == NOT_APPLICABLE and stage in (
            PatternAStage.TRANSITION,
            PatternAStage.EARLY_TREND,
        ):
            transition_first = d
        if early_trend_first == NOT_APPLICABLE and stage == PatternAStage.EARLY_TREND:
            early_trend_first = d
        if transition_first != NOT_APPLICABLE and early_trend_first != NOT_APPLICABLE:
            break
    return transition_first, early_trend_first


def find_base_reference_before_entry(
    ticker: str,
    name: str,
    daily: pd.DataFrame,
    cutoff: str | pd.Timestamp,
    min_lead_weeks: int = 12,
    max_lookback_weeks: int = 104,
    gap_tolerance_weeks: int = 4,
    confirm_pre_episode_weeks: int = 4,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, str | None]:
    """Cohort A 선정용: cutoff 시점 현재 episode(TRANSITION/EARLY_TREND)의
    진입 경계(entry_boundary)를 찾고, 그보다 최소 min_lead_weeks 이전에
    실제로 BASE였던 완료 주봉을 reference_date로 반환한다.

    단순히 "cutoff에서 가장 가까운 BASE"를 쓰면 entry_boundary 바로 직전
    주가 되어 관측 가능한 lead time이 구조적으로 min_lead_weeks 미만으로
    눌린다(13A §26이 말하는 "Fast가 Pattern A보다 몇 주 먼저 보이는가"를
    이 cohort가 보여줄 수 없게 됨) — 그래서 entry_boundary - min_lead_weeks
    지점부터 backward로 BASE를 찾는다.

    **gap-tolerant entry_boundary**: cutoff부터 backward로 걸을 때 단
    1주짜리 BASE/WEAK 되돌림만으로 episode가 끝났다고 보면, "실제 episode
    시작"보다 훨씬 최근을 entry_boundary로 잘못 잡는다(회귀 발견 사례:
    000050/000850/001260/001800/002460 등 다수가 이 버그로 lead time이
    구조적으로 1주에 눌려 있었음 — Phase 13C-1 correction 2차). 그래서
    TRANSITION/EARLY_TREND가 아닌 주가 `gap_tolerance_weeks`회 연속으로
    나타나야만 episode가 끝났다고 보고, 그 전의 산발적 1~3주 dip은
    무시하며 계속 backward로 entry_boundary를 확장한다.

    **forward-confirmed reference**: 찾은 BASE 후보가 진짜로 episode
    "이전"인지, 아니면 그 자체가 TRANSITION 사이의 짧은 dip인지 구분하기
    위해, 후보 다음 `confirm_pre_episode_weeks`주 연속이 TRANSITION/
    EARLY_TREND가 아님을 확인한 뒤에만 채택한다.

    못 찾으면 reference_date는 None(entry_boundary/entry_stage는 찾았으면
    채워서 반환 — 로그/skip 사유 확인용).

    반환: (reference_date | None, entry_boundary | None, entry_stage | None)
    entry_stage는 entry_boundary 시점의 Pattern A stage("transition" 또는
    "early_trend") — 호출부가 PATTERN_A_PRE_TRANSITION vs
    PATTERN_A_PRE_EARLY source_reason을 고르는 데 쓴다.
    """
    cutoff = pd.Timestamp(cutoff)
    all_weekly_asc = sorted(d for d in to_weekly(daily).index if d <= cutoff and d <= daily.index.max())
    stage_cache: dict[pd.Timestamp, str | None] = {}

    def stage_at(d: pd.Timestamp) -> str | None:
        if d not in stage_cache:
            snap = compute_reference_snapshot(ticker, name, daily, d)
            stage_cache[d] = snap.pattern_a_stage if snap.data_status == "OK" else None
        return stage_cache[d]

    # 1) entry_boundary: cutoff부터 backward, gap_tolerance_weeks 연속
    #    비-TRANSITION/EARLY_TREND가 나올 때까지는 계속 확장.
    entry_boundary: pd.Timestamp | None = None
    entry_stage: str | None = None
    gap = 0
    for d in reversed(all_weekly_asc):
        stage = stage_at(d)
        if stage in ("transition", "early_trend"):
            entry_boundary = d
            entry_stage = stage
            gap = 0
        else:
            gap += 1
            if gap >= gap_tolerance_weeks:
                break

    if entry_boundary is None:
        return None, None, None

    # 2) entry_boundary - min_lead_weeks 부터 backward로 최대
    #    max_lookback_weeks까지, forward-confirmed BASE를 찾는다.
    search_start = entry_boundary - pd.Timedelta(weeks=min_lead_weeks)
    search_floor = entry_boundary - pd.Timedelta(weeks=max_lookback_weeks)
    search_candidates = sorted((d for d in all_weekly_asc if search_floor <= d <= search_start), reverse=True)

    for d in search_candidates:
        if stage_at(d) != "base":
            continue
        forward_dates = [x for x in all_weekly_asc if x > d][:confirm_pre_episode_weeks]
        if len(forward_dates) < confirm_pre_episode_weeks:
            continue
        if any(stage_at(x) in ("transition", "early_trend") for x in forward_dates):
            continue
        return d, entry_boundary, entry_stage

    return None, entry_boundary, entry_stage


def weekly_return_screen(
    daily: pd.DataFrame,
    reference_date: pd.Timestamp,
    lookback_weeks: int = 12,
    lookahead_weeks: int = 12,
) -> dict | None:
    """단순 가격 기반 sampling 지표 — cohort 선정용 설명 지표일 뿐, Fast Trigger
    판정/human_label 산출에는 쓰지 않는다(§19, §40 Optional Descriptive Metrics).

    reference_date 이후 가격을 사용하는 유일한 목적은 "다양한 구조의 sample을
    고르기 위한 sampling"이며, 이 함수의 반환값은 어떤 sample row의
    weekly_stage_at_reference/human_label에도 대입되지 않는다.
    """
    weekly = to_weekly(daily)["close"]
    if reference_date not in weekly.index:
        return None
    pos = weekly.index.get_loc(reference_date)
    if pos - lookback_weeks < 0 or pos + lookahead_weeks >= len(weekly):
        return None

    ref_price = weekly.iloc[pos]
    trailing_price = weekly.iloc[pos - lookback_weeks]
    forward_window = weekly.iloc[pos + 1 : pos + 1 + lookahead_weeks]
    if ref_price <= 0 or trailing_price <= 0 or forward_window.empty:
        return None

    trailing_52w_return = None
    if pos - 52 >= 0:
        base52 = weekly.iloc[pos - 52]
        if base52 > 0:
            trailing_52w_return = float(ref_price / base52 - 1.0)

    return {
        "trailing_return": float(ref_price / trailing_price - 1.0),
        "forward_return": float(forward_window.iloc[-1] / ref_price - 1.0),
        "forward_max_drawdown": float(forward_window.min() / ref_price - 1.0),
        "forward_max_runup": float(forward_window.max() / ref_price - 1.0),
        "trailing_52w_return": trailing_52w_return,
    }


def classify_source_reason(metrics: dict) -> str:
    """weekly_return_screen 결과를 사전 문서화된 규칙으로 sampling bucket에
    매핑한다. 결과는 source_reason(왜 dataset에 들어왔는지)일 뿐 human_label이
    아니다(§18 Source Reason은 Human Label이 아니다).

    규칙(고정, 이 함수가 유일한 정의처):
    * FAILED_BREAKOUT: trailing 12주 수익률 >= +15% 이고 forward 12주 최대낙폭
      <= -8% 이고 forward 12주 수익률 <= +3%
    * LONG_DOWNTREND_BOUNCE: trailing 52주 수익률 <= -30% 이고 trailing 12주
      수익률이 0%~+10% 사이
    * STRONG_UPTREND_ALREADY_EXTENDED: trailing 52주 수익률 >= +60%
    * NEGATIVE_CONTROL: trailing 52주 수익률 <= -20% 이고 trailing 12주 수익률
      <= -3% 이고 forward 12주 최대상승 < +8%
    * RANGE_BOUND: trailing/forward 12주 수익률·낙폭·상승폭이 전부 5~10%p 이내
    * 위 어디에도 안 맞으면 AMBIGUOUS_STRUCTURE
    """
    tr = metrics["trailing_return"]
    fr = metrics["forward_return"]
    fmdd = metrics["forward_max_drawdown"]
    fmru = metrics["forward_max_runup"]
    t52 = metrics["trailing_52w_return"]

    if tr >= 0.15 and fmdd <= -0.08 and fr <= 0.03:
        return "FAILED_BREAKOUT"
    if t52 is not None and t52 <= -0.30 and 0.0 <= tr <= 0.10:
        return "LONG_DOWNTREND_BOUNCE"
    if t52 is not None and t52 >= 0.60:
        return "STRONG_UPTREND_ALREADY_EXTENDED"
    if t52 is not None and t52 <= -0.20 and tr <= -0.03 and fmru < 0.08:
        return "NEGATIVE_CONTROL"
    if abs(tr) <= 0.05 and abs(fmru) <= 0.10 and abs(fmdd) <= 0.10:
        return "RANGE_BOUND"
    return "AMBIGUOUS_STRUCTURE"


def make_sample_id(ticker: str, reference_date: pd.Timestamp) -> str:
    """결정론적 sample_id: {ticker}_{YYYYMMDD}."""
    return f"{ticker}_{pd.Timestamp(reference_date).strftime('%Y%m%d')}"


@dataclass(frozen=True)
class ChartSlices:
    """PIT chart 3종(Monthly/Weekly/Daily)과 Outcome chart(Weekly)용 slice.

    PIT slice는 reference_date 이하만, Outcome slice는 outcome_review_end
    이하만 포함한다. 두 영역을 렌더링 단계에서 실수로 섞지 않도록 처음부터
    분리된 DataFrame으로 반환한다(Gate 5/6).
    """

    monthly_pit: pd.DataFrame
    weekly_pit: pd.DataFrame
    daily_pit: pd.DataFrame
    weekly_outcome: pd.DataFrame


def build_chart_slices(
    daily: pd.DataFrame,
    reference_date: pd.Timestamp,
    outcome_review_end: pd.Timestamp,
    daily_pit_window_days: int = 180,
) -> ChartSlices:
    """PIT/Outcome chart용 slice를 생성하고, PIT 영역에 미래 데이터가 없음을
    machine-check로 보장한다(assert). §26 PIT Chart: reference_date 이후 price/
    volume을 절대 포함하지 않는다.
    """
    reference_date = pd.Timestamp(reference_date)
    outcome_review_end = pd.Timestamp(outcome_review_end)

    pit_daily_full = daily[daily.index <= reference_date]
    # resample 라벨은 period 끝(월말/주말 금요일) 기준이라, 마지막 미완성
    # 기간의 라벨이 reference_date보다 늦게 찍힐 수 있다(내용은 이미
    # reference_date 이하 데이터로만 만들어졌어도). 라벨 자체가 미래로
    # 보이는 걸 막기 위해 label <= reference_date인 완료 기간만 남긴다
    # (historical_snapshot.py의 completed-period 트리밍과 동일한 취지).
    monthly_pit = to_monthly(pit_daily_full)
    monthly_pit = monthly_pit[monthly_pit.index <= reference_date]
    weekly_pit = to_weekly(pit_daily_full)
    weekly_pit = weekly_pit[weekly_pit.index <= reference_date]
    daily_pit_start = reference_date - pd.Timedelta(days=daily_pit_window_days)
    daily_pit = pit_daily_full[pit_daily_full.index >= daily_pit_start]

    outcome_daily = daily[daily.index <= outcome_review_end]
    weekly_outcome = to_weekly(outcome_daily)

    assert monthly_pit.empty or monthly_pit.index.max() <= reference_date, "PIT leakage: monthly"
    assert weekly_pit.empty or weekly_pit.index.max() <= reference_date, "PIT leakage: weekly"
    assert daily_pit.empty or daily_pit.index.max() <= reference_date, "PIT leakage: daily"

    return ChartSlices(
        monthly_pit=monthly_pit,
        weekly_pit=weekly_pit,
        daily_pit=daily_pit,
        weekly_outcome=weekly_outcome,
    )
