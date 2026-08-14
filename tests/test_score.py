from trend_scanner.models.score import ScanResult, score_momentum
from trend_scanner.patterns.pattern_a_score import PatternAResult


def test_score_momentum_positive_when_improving():
    assert score_momentum(current_score=85, past_score=62) == 23


def test_score_momentum_negative_when_declining():
    assert score_momentum(current_score=50, past_score=70) == -20


def _sample_pattern_a_result() -> PatternAResult:
    return PatternAResult(
        base_score=76.0,
        base_valid_features=("range_36m", "avg_price_change_12m", "ma_spread"),
        base_missing_features=(),
        transition_score=82.0,
        transition_valid_features=("ma24_slope", "weekly_ma12_slope", "ma24_slope_acceleration"),
        transition_missing_features=(),
        core_score=80.0,
        support_score=85.0,
        confirmation_bonus=2.0,
        balanced_core_score=78.9,
        alignment_bonus=8.0,
        progressed_penalty=0.0,
        progressed_evidence_count=0,
        pattern_a_score=86.9,
        stage=None,
        flags={"transition_alignment": True, "already_progressed": False, "insufficient_data": False},
    )


def test_scan_result_combines_identity_and_pattern_result():
    pattern_a = _sample_pattern_a_result()
    scan_result = ScanResult(ticker="068270", name="셀트리온", pattern_a=pattern_a)

    assert scan_result.ticker == "068270"
    assert scan_result.name == "셀트리온"
    assert scan_result.pattern_a is pattern_a
