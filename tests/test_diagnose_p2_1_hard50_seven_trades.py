from scripts.diagnose_p2_1_hard50_seven_trades import _verdict


def test_hard50_verdict_is_mixed_when_tail_improvement_clips_positive_recovery():
    summary = {
        "hard_improved_trade_count": 4,
        "hard_worsened_trade_count": 3,
        "hard_vs_candidate_delta_sum": -16.76,
        "deep_tail_improved_trade_count": 4,
        "positive_recovery_clipped_trade_count": 1,
    }

    verdict, reason = _verdict(summary)

    assert verdict == "HARD50_MIXED"
    assert "교환 관계" in reason
