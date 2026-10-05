from types import SimpleNamespace

from scripts.replay_b_select_daily_normal_exit_permanent_exclusion_v01 import _executed_event_counts
from trend_scanner.universe.permanent_identity_exclusions import (
    PERMANENT_IDENTITY_EXCLUSIONS,
    apply_permanent_identity_exclusions,
)


NEW_IDENTITIES = {
    ("007720", "KR7007720006"),
    ("011080", "KR7011080009"),
    ("019490", "KR7019490002"),
    ("019570", "KR7019570001"),
    ("066790", "KR7066790007"),
    ("073570", "KR7073570004"),
    ("083660", "KR7083660001"),
}


def test_global_exclusion_registry_has_exact_181_identities_and_new_pairs():
    assert len(PERMANENT_IDENTITY_EXCLUSIONS) == 181
    assert NEW_IDENTITIES <= set(PERMANENT_IDENTITY_EXCLUSIONS)
    for identity in NEW_IDENTITIES:
        policy = PERMANENT_IDENTITY_EXCLUSIONS[identity]
        assert policy["approval_scope"] == "GLOBAL permanent identity exclusion"
        assert policy["approved_date"] == "2026-10-05"
        assert "data-quality basis, not performance" in policy["reason"]


def test_new_exclusions_match_both_ticker_and_exact_isu_code():
    segments = [
        SimpleNamespace(ticker=ticker, isu_cd=isu_cd, market="KOSDAQ")
        for ticker, isu_cd in sorted(NEW_IDENTITIES)
    ]
    segments.append(SimpleNamespace(ticker="007720", isu_cd="KR7007720007", market="KOSDAQ"))

    kept, excluded = apply_permanent_identity_exclusions(segments)

    assert {(row["ticker"], row["isu_cd"]) for row in excluded} == NEW_IDENTITIES
    assert [(row.ticker, row.isu_cd) for row in kept] == [("007720", "KR7007720007")]


def test_executed_trade_counts_come_from_filled_event_ledger():
    events = [
        {"event_type": "ENTRY", "event_status": "EXECUTED"},
        {"event_type": "ENTRY", "event_status": "SKIPPED"},
        {"event_type": "EXIT", "event_status": "EXECUTED"},
        {"event_type": "EXIT", "event_status": "UNRESOLVED"},
    ]

    assert _executed_event_counts(events) == {"executed_entry_count": 1, "executed_exit_count": 1}
