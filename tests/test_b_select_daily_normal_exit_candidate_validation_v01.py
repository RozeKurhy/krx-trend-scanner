import unittest

from scripts.analyze_b_select_daily_normal_exit_candidate_validation_v01 import (
    build_early_pairs,
    mdd_gate,
    trade_distribution,
)


class CandidateValidationTests(unittest.TestCase):
    def test_trade_distribution_includes_each_tail_boundary(self):
        result = trade_distribution([-30.0, -15.0, 0.0, 30.0, 50.0, 100.0])

        self.assertEqual(result["realized_count"], 6)
        self.assertEqual(result["win_rate_pct"], 50.0)
        self.assertEqual(result["le_neg_15_count"], 2)
        self.assertAlmostEqual(result["le_neg_15_rate_pct"], 100 / 3)
        self.assertEqual(result["le_neg_30_count"], 1)
        self.assertEqual(result["ge_pos_30_count"], 3)
        self.assertEqual(result["ge_pos_50_count"], 2)
        self.assertEqual(result["ge_pos_100_count"], 1)

    def test_mdd_coverage_is_checked_before_the_numeric_thresholds(self):
        self.assertEqual(mdd_gate(89.99, -80.0, -55.0, 6.0), "CHECK_REQUIRED")
        self.assertEqual(mdd_gate(90.0, -55.01, -55.0, 0.0), "FAIL")
        self.assertEqual(mdd_gate(100.0, -20.0, -40.0, 5.0), "FAIL")
        self.assertEqual(mdd_gate(90.0, -20.0, -40.0, 4.99), "PASS")

    def test_early_pairing_requires_two_realized_exits_and_uses_exact_sessions(self):
        sessions = [f"2026-01-{day:02d}" for day in range(1, 8)]
        rows = [
        {
            "window_id": "P2-1",
            "ticker": "000001",
            "isu_cd": "KR7000000001",
            "entry_signal_date": sessions[0],
            "entry_execution_date": sessions[1],
            "control_exit_signal_date": sessions[5],
            "control_exit_execution_date": sessions[6],
            "test_exit_signal_date": sessions[3],
            "test_exit_execution_date": sessions[4],
            "control_trade_status": "REALIZED",
            "test_trade_status": "REALIZED",
            "control_costed_pre_tax_return_pct": "10",
            "test_costed_pre_tax_return_pct": "15",
            "control_holding_krx_sessions": "6",
            "test_holding_krx_sessions": "4",
        },
        {
            "window_id": "P2-1",
            "ticker": "000002",
            "isu_cd": "KR7000000002",
            "entry_signal_date": sessions[0],
            "control_exit_signal_date": sessions[4],
            "control_exit_execution_date": sessions[5],
            "test_exit_signal_date": sessions[4],
            "test_exit_execution_date": sessions[5],
            "control_trade_status": "REALIZED",
            "test_trade_status": "REALIZED",
            "control_costed_pre_tax_return_pct": "5",
            "test_costed_pre_tax_return_pct": "5",
        },
        {
            "window_id": "P2-1",
            "ticker": "000003",
            "isu_cd": "KR7000000003",
            "entry_signal_date": sessions[0],
            "control_exit_signal_date": "",
            "control_exit_execution_date": "",
            "test_exit_signal_date": sessions[3],
            "test_exit_execution_date": sessions[4],
            "control_trade_status": "OPEN_AT_CUTOFF",
            "test_trade_status": "REALIZED",
            "control_costed_pre_tax_return_pct": "",
            "test_costed_pre_tax_return_pct": "12",
        },
        ]

        pairs, summary = build_early_pairs(rows, sessions, set(), {"000001|KR7000000001|2026-01-01"})

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["signal_sessions_advanced"], 2)
        self.assertEqual(pairs[0]["execution_sessions_advanced"], 2)
        self.assertEqual(pairs[0]["return_delta_pp"], 5)
        self.assertEqual(summary["daily_earlier_signal_count"], 2)
        self.assertEqual(summary["paired_realized_earlier_exit_count"], 1)
        self.assertEqual(summary["earlier_test_exit_without_control_exit_count"], 1)
        self.assertEqual(summary["improved_count"], 1)
        self.assertEqual(summary["degraded_count"], 0)


if __name__ == "__main__":
    unittest.main()
