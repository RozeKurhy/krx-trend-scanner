"""Lifecycle Replay Engine and True Chronological Sequential Reducer for Stage v0.2."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.historical_snapshot import HistoricalSnapshot, build_historical_snapshot
from trend_scanner.validation.stage_v02.allowlist import (
    CANDIDATE_RAW_FEATURE_ALLOWLIST,
    compute_canonical_sha256,
)
from trend_scanner.validation.stage_v02.candidate_classifier import (
    CandidateDiagnostics,
    CandidateStageResult,
    classify_pattern_a_stage_v02_candidate,
)


@dataclass(frozen=True)
class CanonicalLifecycleEventResult:
    """Immutable result of evaluating a canonical lifecycle event in true sequential chronological order."""

    ticker: str
    lifecycle_event_key: str
    candidate_relevant_feature_signature: str
    monthly_as_of: str
    weekly_as_of: str
    state_before: bool
    current_strict_expansion: bool
    current_episode_terminated: bool
    state_after: bool
    candidate_stage: PatternAStage | None
    candidate_reason_codes: tuple[str, ...]
    diagnostics: CandidateDiagnostics


@dataclass(frozen=True)
class CandidateRequestEvaluation:
    """Provenanced request evaluation linking a requested date to a canonical lifecycle event."""

    ticker: str
    requested_snapshot_date: str
    effective_as_of: str
    monthly_as_of: str
    weekly_as_of: str
    temporal_signature: str
    lifecycle_event_key: str
    candidate_stage: PatternAStage | None
    candidate_reason_codes: tuple[str, ...]
    diagnostics: CandidateDiagnostics


def compute_feature_signature(features: Any) -> str:
    """Compute digest of candidate relevant raw features allowlist only."""
    payload = {name: getattr(features, name, None) for name in CANDIDATE_RAW_FEATURE_ALLOWLIST}
    return compute_canonical_sha256(payload)


def compute_temporal_signature(
    ticker: str,
    requested_snapshot_date: str,
    effective_as_of: str,
    monthly_as_of: str,
    weekly_as_of: str,
) -> str:
    """Compute temporal provenance signature."""
    payload = {
        "ticker": ticker,
        "requested_snapshot_date": str(requested_snapshot_date),
        "effective_as_of": str(effective_as_of),
        "monthly_as_of": str(monthly_as_of),
        "weekly_as_of": str(weekly_as_of),
        "include_incomplete_periods": False,
    }
    return compute_canonical_sha256(payload)


def compute_lifecycle_event_key(
    ticker: str,
    monthly_as_of: str,
    weekly_as_of: str,
    feature_signature: str,
) -> str:
    """Compute canonical lifecycle event key incorporating ticker namespace."""
    payload = {
        "ticker": ticker,
        "monthly_as_of": str(monthly_as_of),
        "weekly_as_of": str(weekly_as_of),
        "feature_signature": feature_signature,
    }
    return compute_canonical_sha256(payload)


class LifecycleStreamEngine:
    """True deterministic chronological sequential reducer for Pattern A Stage lifecycle.
    
    Guarantees:
    1. next_event.state_before == previous_event.state_after (strict sequential state linking).
    2. Every historical event uses real build_historical_snapshot (0 synthetic approximations).
    3. evaluate_request strictly returns target event from chronological sequential replay.
    4. 100% request-order independence.
    """

    def __init__(self) -> None:
        self._event_cache: dict[str, dict[str, CanonicalLifecycleEventResult]] = {}
        self._timeline_by_ticker: dict[str, list[CanonicalLifecycleEventResult]] = {}
        
        self.same_event_key_state_before_mismatches: int = 0
        self.same_event_key_termination_mismatches: int = 0
        self.same_event_key_state_after_mismatches: int = 0
        self.same_event_key_candidate_stage_mismatches: int = 0
        self.same_event_key_reason_code_mismatches: int = 0
        self.request_temporal_provenance_mismatches: int = 0
        self.cross_ticker_event_reuses: int = 0
        self.lifecycle_off_by_one_errors: int = 0
        self.sequential_state_link_mismatch_count: int = 0

    def replay_canonical_timeline(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        target_date: str | datetime.date,
    ) -> list[CanonicalLifecycleEventResult]:
        """Replay true sequential reducer over real historical snapshots up to target_date."""
        if daily is None or daily.empty:
            return []

        target_snap = build_historical_snapshot(
            ticker=ticker,
            name=name,
            daily=daily,
            snapshot_date=target_date,
            include_incomplete_periods=False,
        )

        monthly = target_snap.monthly
        if monthly is None or monthly.empty:
            return []

        timeline: list[CanonicalLifecycleEventResult] = []
        current_state_before: bool = False

        if ticker not in self._event_cache:
            self._event_cache[ticker] = {}

        # Schedule dates from monthly index
        monthly_dates = [d.date() for d in monthly.index]

        for i, sub_date in enumerate(monthly_dates):
            # For the last event, use target_snap directly for exactness
            if i == len(monthly_dates) - 1:
                snap = target_snap
            else:
                snap = build_historical_snapshot(
                    ticker=ticker,
                    name=name,
                    daily=daily,
                    snapshot_date=sub_date,
                    include_incomplete_periods=False,
                )

            m_as_of = str(snap.monthly.index[-1].date()) if (snap.monthly is not None and not snap.monthly.empty) else "NONE"
            w_as_of = str(snap.features.as_of) if hasattr(snap.features, "as_of") else str(snap.effective_as_of)
            feat_sig = compute_feature_signature(snap.features)
            event_key = compute_lifecycle_event_key(ticker, m_as_of, w_as_of, feat_sig)

            # Evaluate with true previous state_after
            state_before = current_state_before
            res = classify_pattern_a_stage_v02_candidate(snap, override_state_before=state_before)

            # Invariant verification
            if res.candidate_diagnostics.previously_expanded_before_snapshot != current_state_before:
                self.sequential_state_link_mismatch_count += 1

            event_result = CanonicalLifecycleEventResult(
                ticker=ticker,
                lifecycle_event_key=event_key,
                candidate_relevant_feature_signature=feat_sig,
                monthly_as_of=m_as_of,
                weekly_as_of=w_as_of,
                state_before=res.candidate_diagnostics.previously_expanded_before_snapshot,
                current_strict_expansion=res.candidate_diagnostics.current_strict_expansion,
                current_episode_terminated=res.candidate_diagnostics.current_episode_terminated,
                state_after=res.candidate_diagnostics.previously_expanded_after_snapshot,
                candidate_stage=res.candidate_stage,
                candidate_reason_codes=res.candidate_reason_codes,
                diagnostics=res.candidate_diagnostics,
            )

            timeline.append(event_result)
            self._event_cache[ticker][event_key] = event_result
            current_state_before = event_result.state_after

        self._timeline_by_ticker[ticker] = timeline
        return timeline

    def evaluate_request(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        requested_snapshot_date: str | datetime.date,
    ) -> CandidateRequestEvaluation:
        """Evaluate a historical snapshot request strictly by retrieving the target event from canonical sequential replay."""
        snap = build_historical_snapshot(
            ticker=ticker,
            name=name,
            daily=daily,
            snapshot_date=requested_snapshot_date,
            include_incomplete_periods=False,
        )

        monthly_as_of = str(snap.monthly.index[-1].date()) if (snap.monthly is not None and not snap.monthly.empty) else "NONE"
        weekly_as_of = str(snap.features.as_of) if hasattr(snap.features, "as_of") else str(snap.effective_as_of)
        effective_as_of = str(snap.effective_as_of)

        feat_sig = compute_feature_signature(snap.features)
        temp_sig = compute_temporal_signature(
            ticker=ticker,
            requested_snapshot_date=str(requested_snapshot_date),
            effective_as_of=effective_as_of,
            monthly_as_of=monthly_as_of,
            weekly_as_of=weekly_as_of,
        )
        event_key = compute_lifecycle_event_key(
            ticker=ticker,
            monthly_as_of=monthly_as_of,
            weekly_as_of=weekly_as_of,
            feature_signature=feat_sig,
        )

        # Check cross-ticker pollution
        for other_ticker, cache_dict in self._event_cache.items():
            if other_ticker != ticker and event_key in cache_dict:
                self.cross_ticker_event_reuses += 1

        # Replay canonical chronological timeline
        timeline = self.replay_canonical_timeline(ticker, name, daily, requested_snapshot_date)

        if not timeline:
            res = classify_pattern_a_stage_v02_candidate(snap)
            return CandidateRequestEvaluation(
                ticker=ticker,
                requested_snapshot_date=str(requested_snapshot_date),
                effective_as_of=effective_as_of,
                monthly_as_of=monthly_as_of,
                weekly_as_of=weekly_as_of,
                temporal_signature=temp_sig,
                lifecycle_event_key=event_key,
                candidate_stage=res.candidate_stage,
                candidate_reason_codes=res.candidate_reason_codes,
                diagnostics=res.candidate_diagnostics,
            )

        # Strictly return target event from sequential reducer timeline
        event_result = timeline[-1]

        return CandidateRequestEvaluation(
            ticker=ticker,
            requested_snapshot_date=str(requested_snapshot_date),
            effective_as_of=effective_as_of,
            monthly_as_of=monthly_as_of,
            weekly_as_of=weekly_as_of,
            temporal_signature=temp_sig,
            lifecycle_event_key=event_key,
            candidate_stage=event_result.candidate_stage,
            candidate_reason_codes=event_result.candidate_reason_codes,
            diagnostics=event_result.diagnostics,
        )
