from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import build_b_select_core_v1_status as status_builder
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_source
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def test_status_builder_rejects_report_date_mismatch(tmp_path: Path):
    index_path = tmp_path / "stock-index.json"
    index_path.write_text(
        json.dumps({"requested_as_of": "2026-09-24", "reference_market_date": "2026-09-23", "items": []}),
        encoding="utf-8",
    )
    with pytest.raises(status_builder.BSelectStatusError, match="B_SELECT_STOCK_INDEX_DATE_MISMATCH"):
        status_builder.build_b_select_status(
            repo_root=tmp_path,
            index_path=index_path,
            stocks_path=tmp_path / "stocks",
            target_as_of="2026-09-25",
            reference_market_date="2026-09-23",
        )


def test_previous_stage_uses_exact_current_snapshot_after_monthly_history():
    current_stage, previous_stage, context = status_builder._report_previous_stage(
        {
            "pattern": {
                "official_stage": "PROGRESSED",
                "history_12m": [{"as_of": "2026-08-31", "stage": "WEAK"}],
            }
        },
        reference_market_date="2026-09-23",
        trading_dates=["2026-08-31", "2026-09-23"],
        root=Path("."),
        identity={"ticker": "041510", "effective_from": "2020-01-01"},
        resolve_full_history=False,
    )

    assert current_stage == "PROGRESSED"
    assert previous_stage == "WEAK"
    assert context is not None
    assert context["previous_pattern_a_stage_date"] == "2026-08-31"


def test_monthly_state_authority_applies_exact_permanent_identity_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    excluded_ticker, excluded_isu = sorted(PERMANENT_IDENTITY_EXCLUSIONS)[0]
    retained_isu = "KR7999999999"
    snapshot_date = "2026-09-23"
    interval_end = "2026-09-23"
    intervals = [
        {
            "ticker": excluded_ticker,
            "isu_cd": isu,
            "market": "KOSPI",
            "state": "COMMON",
            "effective_from": "2020-01-01",
            "effective_to": interval_end,
        }
        for isu in (excluded_isu, retained_isu)
    ]
    components = {
        pattern_b_source.interval_key(row): f"component-{index}"
        for index, row in enumerate(intervals)
    }
    sample_path = tmp_path / "monthly.csv.gz"
    pd.DataFrame(
        [
            {
                "ticker": excluded_ticker,
                "isu_cd": isu,
                "market": "KOSPI",
                "effective_from": "2020-01-01",
                "effective_to": interval_end,
                "snapshot_date": snapshot_date,
                "monthly_last_bar": "2026-08-31",
                "weekly_last_bar": "2026-09-18",
                "state": "DEPRESSED",
            }
            for isu in (excluded_isu, retained_isu)
        ]
    ).to_csv(sample_path, index=False, compression="gzip")
    monkeypatch.setattr(status_builder, "MONTHLY_SAMPLE_REL", sample_path.relative_to(tmp_path))

    states, policy_exclusion_count = status_builder._load_monthly_states(
        tmp_path,
        intervals,
        components,
        [snapshot_date],
    )

    assert policy_exclusion_count == len(PERMANENT_IDENTITY_EXCLUSIONS)
    assert states[["ticker", "isu_cd"]].to_records(index=False).tolist() == [(excluded_ticker, retained_isu)]
