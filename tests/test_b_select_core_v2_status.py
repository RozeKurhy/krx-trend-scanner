from __future__ import annotations

import json
from pathlib import Path

from scripts import build_b_select_core_v2_status as status_v2


APPROVED_SEVEN = {
    ("007720", "KR7007720006"),
    ("011080", "KR7011080009"),
    ("019490", "KR7019490002"),
    ("019570", "KR7019570001"),
    ("066790", "KR7066790007"),
    ("073570", "KR7073570004"),
    ("083660", "KR7083660001"),
}


def _open_item(ticker: str, isu_cd: str, *, quantity=None):
    trade = {
        "trade_sequence": 1,
        "entry_signal_date": "2026-06-30",
        "entry_execution_date": "2026-07-01",
        "entry_open": 1234.0,
        "trade_status": "OPEN_AT_REFERENCE",
    }
    if quantity is not None:
        trade["quantity"] = quantity
    return {
        "ticker": ticker,
        "isu_cd": isu_cd,
        "name": f"stock-{ticker}",
        "canonical_position": "OPEN",
        "current_trade": trade,
        "trade_history": [dict(trade)],
    }


def test_v2_migration_payload_preserves_exact_v1_open_inventory_and_optional_quantity():
    items = [_open_item(f"{ticker:06d}", f"KR7{ticker:06d}0000") for ticker in range(1, 27)]
    items[0]["current_trade"]["quantity"] = 5
    prior = {
        "strategy_id": "PATTERN_B_SELECT_CORE_V01",
        "reference_market_date": "2026-10-02",
        "requested_as_of": "2026-10-03",
        "items": items,
    }

    payload = status_v2._promotion_migration_payload(prior, "legacy/status.json")

    assert payload["source_strategy_id"] == "PATTERN_B_SELECT_CORE_V01"
    assert payload["baseline_reference_market_date"] == "2026-10-02"
    assert payload["source_artifact_path"] == "legacy/status.json"
    assert payload["migrated_open_position_count"] == 26
    assert payload["migrated_open_positions"][0]["quantity"] == 5
    assert payload["migrated_open_positions"][1]["quantity"] is None


def test_latest_sealed_v1_status_inventory_has_26_open_positions_including_excluded_011080():
    root = Path(__file__).resolve().parents[1]
    source_path = root / "artifacts/strategies/b_select_core_v1/production/20261003/status.json"
    prior = json.loads(source_path.read_text(encoding="utf-8"))
    payload = status_v2._promotion_migration_payload(
        prior,
        str(source_path.relative_to(root)),
    )

    assert prior["status"] == "PASS"
    assert prior["reference_market_date"] == "2026-10-02"
    assert payload["migrated_open_position_count"] == 26
    migrated_keys = {
        (item["ticker"], item["isu_cd"])
        for item in payload["migrated_open_positions"]
    }
    assert ("011080", "KR7011080009") in migrated_keys
    assert all(item["quantity"] is None for item in payload["migrated_open_positions"])


def test_seven_approved_exclusions_block_new_entries_but_only_baseline_open_identity_migrates():
    migration_open = {("011080", "KR7011080009")}
    assert len(APPROVED_SEVEN) == 7
    assert len(status_v2.PERMANENT_IDENTITY_EXCLUSIONS) == 181
    assert all(not status_v2._is_new_entry_allowed(*pair) for pair in APPROVED_SEVEN)

    inherited_item = _open_item("011080", "KR7011080009")
    assert status_v2._is_inherited_excluded_open(
        ("011080", "KR7011080009"), inherited_item, migration_open
    )
    for pair in APPROVED_SEVEN - migration_open:
        assert not status_v2._is_inherited_excluded_open(
            pair,
            _open_item(*pair),
            migration_open,
        )
    assert not status_v2._is_inherited_excluded_open(
        ("011080", "KR7011080009"),
        {"canonical_position": "FLAT", "current_trade": None},
        migration_open,
    )


def test_trade_source_tagging_keeps_v1_entry_lineage():
    row = status_v2._tag_trade_source(
        {"trade_sequence": 2, "exit_strategy_id": "PATTERN_B_SELECT_CORE_V02"},
        "PATTERN_B_SELECT_CORE_V01",
    )
    assert row["strategy_id"] == "PATTERN_B_SELECT_CORE_V01"
    assert row["exit_strategy_id"] == "PATTERN_B_SELECT_CORE_V02"


def test_migration_open_position_parity_requires_exact_identity_and_entry_values():
    migration = {
        "migrated_open_position_count": 1,
        "migrated_open_positions": [{
            "ticker": "011080",
            "isu_cd": "KR7011080009",
            "trade_sequence": 2,
            "entry_signal_date": "2025-06-30",
            "entry_execution_date": "2025-07-01",
            "entry_open": 10447.0,
        }],
    }
    status_item = {
        "ticker": "011080",
        "isu_cd": "KR7011080009",
        "canonical_position": "OPEN",
        "current_trade": {
            "trade_sequence": 2,
            "entry_execution_date": "2025-07-01",
            "entry_open": 10447.0,
        },
        "trade_history": [{
            **migration["migrated_open_positions"][0],
            "trade_status": "OPEN_AT_REFERENCE",
            "strategy_id": "PATTERN_B_SELECT_CORE_V01",
        }],
    }
    assert status_v2._validate_migration_open_position_parity([status_item], migration) == 1

    status_item["trade_history"][0]["entry_open"] = 1.0
    try:
        status_v2._validate_migration_open_position_parity([status_item], migration)
    except status_v2.BSelectStatusError as exc:
        assert "PARITY_MISMATCH" in str(exc)
    else:
        raise AssertionError("migration entry price mismatch was not rejected")
