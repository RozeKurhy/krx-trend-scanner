from trend_scanner.models.score import score_momentum


def test_score_momentum_positive_when_improving():
    assert score_momentum(current_score=85, past_score=62) == 23


def test_score_momentum_negative_when_declining():
    assert score_momentum(current_score=50, past_score=70) == -20
