"""Lifecycle Replay Engine and Canonical Sequential Reducer for Stage v0.2 Candidate."""

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
    """Immutable result of evaluating a canonical lifecycle event in sequential order."""

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
    """Deterministic, immutable historical ticker-scoped sequential lifecycle replay engine."""

    def __init__(self) -> None:
        # Cache per ticker: event_key -> CanonicalLifecycleEventResult
        self._event_cache: dict[str, dict[str, CanonicalLifecycleEventResult]] = {}
        # Sequential timeline per ticker: ordered list of event results
        self._timeline_by_ticker: dict[str, list[CanonicalLifecycleEventResult]] = {}
        
        # Real observed metrics counters
        self.same_event_key_state_before_mismatches: int = 0
        self.same_event_key_termination_mismatches: int = 0
        self.same_event_key_state_after_mismatches: int = 0
        self.same_event_key_candidate_stage_mismatches: int = 0
        self.same_event_key_reason_code_mismatches: int = 0
        self.request_temporal_provenance_mismatches: int = 0
        self.cross_ticker_event_reuses: int = 0
        self.lifecycle_off_by_one_errors: int = 0

    def evaluate_request(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        requested_snapshot_date: str | datetime.date,
    ) -> CandidateRequestEvaluation:
        """Evaluate a historical snapshot request deterministically using sequential state replay."""
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

        if ticker not in self._event_cache:
            self._event_cache[ticker] = {}
            self._timeline_by_ticker[ticker] = []

        # Check cross-ticker pollution
        for other_ticker, cache_dict in self._event_cache.items():
            if other_ticker != ticker and event_key in cache_dict:
                self.cross_ticker_event_reuses += 1

        # Check if already evaluated in cache
        if event_key in self._event_cache[ticker]:
            cached_result = self._event_cache[ticker][event_key]
            
            # Re-evaluate with current context to verify immutable replay determinism
            current_state_before = cached_result.state_before
            re_eval = classify_pattern_a_stage_v02_candidate(snap, override_state_before=current_state_before)
            
            if re_eval.candidate_diagnostics.previously_expanded_before_snapshot != cached_result.state_before:
                self.same_event_key_state_before_mismatches += 1
            if re_eval.candidate_diagnostics.current_episode_terminated != cached_result.current_episode_terminated:
                self.same_event_key_termination_mismatches += 1
            if re_eval.candidate_diagnostics.previously_expanded_after_snapshot != cached_result.state_after:
                self.same_event_key_state_after_mismatches += 1
            if re_eval.candidate_stage != cached_result.candidate_stage:
                self.same_event_key_candidate_stage_mismatches += 1
            if re_eval.candidate_reason_codes != cached_result.candidate_reason_codes:
                self.same_event_key_reason_code_mismatches += 1

            event_result = cached_result
        else:
            # Sequential state computation from preceding timeline
            timeline = self._timeline_by_ticker[ticker]
            state_before = timeline[-1].state_after if timeline else snap.monthly.empty is False and classify_pattern_a_stage_v02_candidate(snap).candidate_diagnostics.previously_expanded_before_snapshot

            res = classify_pattern_a_stage_v02_candidate(snap, override_state_before=state_before)
            
            # Verify off-by-one boundary
            if res.candidate_diagnostics.previously_expanded_before_snapshot != state_before:
                self.lifecycle_off_by_one_errors += 1

            event_result = CanonicalLifecycleEventResult(
                ticker=ticker,
                lifecycle_event_key=event_key,
                candidate_relevant_feature_signature=feat_sig,
                monthly_as_of=monthly_as_of,
                weekly_as_of=weekly_as_of,
                state_before=res.candidate_diagnostics.previously_expanded_before_snapshot,
                current_strict_expansion=res.candidate_diagnostics.current_strict_expansion,
                current_episode_terminated=res.candidate_diagnostics.current_episode_terminated,
                state_after=res.candidate_diagnostics.previously_expanded_after_snapshot,
                candidate_stage=res.candidate_stage,
                candidate_reason_codes=res.candidate_reason_codes,
                diagnostics=res.candidate_diagnostics,
            )
            self._event_cache[ticker][event_key] = event_result
            self._timeline_by_ticker[ticker].append(event_result)

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
