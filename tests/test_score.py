from trend_scanner.models.score import ScanResult, score_momentum
from trend_scanner.patterns.pattern_a import PatternAResult


def test_score_momentum_positive_when_improving():
    assert score_momentum(current_score=85, past_score=62) == 23


def test_score_momentum_negative_when_declining():
    assert score_momentum(current_score=50, past_score=70) == -20


def _sample_pattern_a_result() -> PatternAResult:
    return PatternAResult(
        pattern_a_score=76.0,
        rejected=False,
        rejection_reasons=(),
        base_score=20.0,
        low_score=16.0,
        ma_score=20.0,
        volatility_score=10.0,
        breakout_score=10.0,
        ma6_slope=0.02,
        ma12_slope=0.01,
        ma24_slope=0.0,
        ma24_slope_acceleration=0.01,
        ma_spread=0.08,
        ma_spread_12m_ago=0.20,
        ma_spread_ratio=0.40,
        low_regression_slope=0.001,
        atr_pct=0.03,
        atr_ratio=0.7,
        distance_to_resistance=0.1,
        range_position=0.7,
    )


def test_scan_result_combines_identity_and_pattern_result():
    pattern_a = _sample_pattern_a_result()
    scan_result = ScanResult(ticker="068270", name="셀트리온", pattern_a=pattern_a)

    assert scan_result.ticker == "068270"
    assert scan_result.name == "셀트리온"
    assert scan_result.pattern_a is pattern_a
