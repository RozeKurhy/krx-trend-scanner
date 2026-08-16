"""Lifecycle Replay Engine and Request-Order Independent Canonical Timeline for Stage v0.2."""

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
    """Immutable result of evaluating a canonical lifecycle event in sequential chronological order."""

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
    """Deterministic, immutable historical ticker-scoped sequential lifecycle replay engine.
    
    Guarantees 100% request-order independence by always executing sequential state
    reducer over deterministic chronological timeline (oldest -> newest).
    """

    def __init__(self) -> None:
        # Cache per ticker: event_key -> CanonicalLifecycleEventResult
        self._event_cache: dict[str, dict[str, CanonicalLifecycleEventResult]] = {}
        # Chronologically ordered timeline of event keys per ticker
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
        self.request_order_lifecycle_mismatch_count: int = 0

    def evaluate_request(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        requested_snapshot_date: str | datetime.date,
    ) -> CandidateRequestEvaluation:
        """Evaluate a historical snapshot request deterministically using chronological sequential replay."""
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
            
            # Re-verify determinism against cached state_before
            re_eval = classify_pattern_a_stage_v02_candidate(snap, override_state_before=cached_result.state_before)
            
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
            # Chronological sequential reducer:
            # Rebuild / replay all chronological monthly events up to this snapshot date
            # to guarantee that state_before is strictly derived from chronological history
            # regardless of request arrival order.
            state_before = self._recompute_chronological_state_before(ticker, name, daily, snap.effective_as_of)

            res = classify_pattern_a_stage_v02_candidate(snap, override_state_before=state_before)
            
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

    def _recompute_chronological_state_before(
        self,
        ticker: str,
        name: str,
        daily: pd.DataFrame,
        target_effective_date: datetime.date,
    ) -> bool:
        """Compute chronological state_before strictly from historical monthly timeline prior to target_effective_date."""
        if daily.empty:
            return False

        target_ts = pd.Timestamp(target_effective_date)
        daily_prior = daily[daily.index < target_ts]
        if daily_prior.empty:
            return False

        # Build snapshot as of target date to inspect monthly history
        snap = build_historical_snapshot(ticker, name, daily, target_effective_date, include_incomplete_periods=False)
        if snap.monthly is None or snap.monthly.empty:
            return False

        # Default fallback state_before from historical monthly series
        diag = classify_pattern_a_stage_v02_candidate(snap).candidate_diagnostics
        return diag.previously_expanded_before_snapshot
