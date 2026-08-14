"""Pattern A & Trend Patterns Package."""

from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    PatternAEvaluationResult,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_score import (
    PatternAResult,
    score_pattern_a,
)
from trend_scanner.patterns.pattern_a_score_momentum import (
    PatternAMonthlyScoreDelta,
    PatternAScoreMomentumHorizon,
    PatternAScoreMomentumResult,
    PatternAScoreObservation,
    compute_pattern_a_score_momentum,
)
from trend_scanner.patterns.pattern_a_stage import (
    StageClassificationResult,
    classify_pattern_a_stage,
)

__all__ = [
    "PatternACandidateState",
    "PatternAEvaluationResult",
    "PatternAMonthlyScoreDelta",
    "PatternAResult",
    "PatternAScoreMomentumHorizon",
    "PatternAScoreMomentumResult",
    "PatternAScoreObservation",
    "StageClassificationResult",
    "classify_pattern_a_stage",
    "compute_pattern_a_score_momentum",
    "evaluate_pattern_a",
    "score_pattern_a",
]
