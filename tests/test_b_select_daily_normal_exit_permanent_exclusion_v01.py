from types import SimpleNamespace

import pandas as pd

from scripts.replay_b_select_daily_normal_exit_permanent_exclusion_v01 import (
    _executed_event_counts,
    _make_raw_store_reader,
)
from scripts.run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 import compute_mdd
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


def test_raw_partition_cache_is_order_independent_for_marks_equity_coverage_and_mdd():
    dates = ("2026-09-28", "2026-09-29", "2026-09-30")
    tickers = ("000001", "000002", "000003")
    isu_by_ticker = {
        "000001": "KR7000010004",
        "000002": "KR7000020008",
        "000003": "KR7000030002",
    }
    closes = {
        "2026-09-28": {"000001": 100.0, "000002": 100.0, "000003": 100.0},
        "2026-09-29": {"000001": 80.0, "000003": 90.0},
        "2026-09-30": {"000001": 95.0, "000002": 90.0, "000003": 80.0},
    }

    class FakeRawStore:
        def get_manifest(self, market, day):
            if day not in closes:
                return None
            return {"status": "COMPLETE", "file_sha256": f"{market}-{day}"}

        def load_snapshot(self, market, day):
            return pd.DataFrame([
                {
                    "ticker": ticker, "date": day,
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": 100, "trading_value": price * 100,
                    "listed_shares": 1_000_000,
                }
                for ticker, price in closes[day].items()
            ])

    def value_in_order(order):
        cache = {}
        manifests = {}
        intervals = {
            (ticker, isu_by_ticker[ticker]): [{
                "state": "COMMON", "market": "KOSDAQ",
                "effective_from": dates[0], "effective_to": dates[-1],
            }]
            for ticker in tickers
        }
        read = _make_raw_store_reader(FakeRawStore(), cache, manifests, intervals)
        mark_rows = []
        equity_rows = []
        for day in dates:
            marks = {}
            for ticker in order:
                row, manifest = read("KOSDAQ", day, ticker, isu_by_ticker[ticker])
                assert manifest["status"] == "COMPLETE"
                marks[ticker] = None if row is None else float(row["close"])
            mark_rows.append({"date": day, **marks})
            equity = None if any(marks[ticker] is None for ticker in tickers) else 1_000_000.0 + sum(marks.values())
            equity_rows.append({"date": day, "equity": equity})
        coverage = sum(row["equity"] is not None for row in equity_rows) / len(equity_rows) * 100.0
        return mark_rows, equity_rows, coverage, compute_mdd(equity_rows, 1_000_000.0)

    ascending = value_in_order(sorted(tickers))
    descending = value_in_order(sorted(tickers, reverse=True))
    shuffled = value_in_order(["000002", "000003", "000001"])

    assert ascending == descending == shuffled
    cache = {}
    manifests = {}
    intervals = {
        ("000001", isu_by_ticker["000001"]): [{
            "state": "COMMON", "market": "KOSDAQ",
            "effective_from": dates[0], "effective_to": dates[-1],
        }]
    }
    exact_reader = _make_raw_store_reader(FakeRawStore(), cache, manifests, intervals)
    assert exact_reader("KOSDAQ", dates[0], "000001", "KR7999999999")[0] is None
    assert sum(value is None for row in ascending[0] for key, value in row.items() if key != "date") == 1
    assert abs(ascending[2] - 200.0 / 3.0) < 1e-12
    assert ascending[3]["mdd_pct"] == compute_mdd(ascending[1], 1_000_000.0)["mdd_pct"]
