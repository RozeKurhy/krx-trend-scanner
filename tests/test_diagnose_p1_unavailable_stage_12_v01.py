from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from scripts.diagnose_p1_unavailable_stage_12_v01 import _missing_bucket_evidence


def _snapshot_with_one_empty_week(label: str) -> SimpleNamespace:
    labels = pd.date_range(end=pd.Timestamp(label), periods=17, freq="W-FRI")
    close = np.full(17, 100.0)
    close[-1] = np.nan
    weekly = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": np.zeros(17),
            "trading_value": np.full(17, np.nan),
        },
        index=labels,
    )
    return SimpleNamespace(
        features=SimpleNamespace(weekly_rows=17, monthly_rows=0),
        weekly=weekly,
        monthly=pd.DataFrame(columns=["close"]),
    )


def test_zero_session_empty_week_is_resampler_artifact():
    snapshot = _snapshot_with_one_empty_week("2017-10-06")
    evidence = _missing_bucket_evidence(
        "weekly_ma12_slope",
        snapshot,
        pd.DataFrame(index=pd.DatetimeIndex([])),
        pd.DatetimeIndex([]),
    )
    assert evidence == [
        {
            "frequency": "weekly",
            "bucket_label": "2017-10-06",
            "bucket_start": "2017-09-30",
            "expected_krx_sessions": 0,
            "repository_v2_daily_rows": 0,
            "kind": "EMPTY_CALENDAR_BUCKET_RESAMPLER_ARTIFACT",
        }
    ]


def test_expected_exchange_sessions_without_repository_rows_are_source_gap():
    snapshot = _snapshot_with_one_empty_week("2023-05-05")
    evidence = _missing_bucket_evidence(
        "weekly_ma12_slope",
        snapshot,
        pd.DataFrame(index=pd.DatetimeIndex([])),
        pd.DatetimeIndex(pd.to_datetime(["2023-05-02", "2023-05-03", "2023-05-04"])),
    )
    assert evidence[-1]["expected_krx_sessions"] == 3
    assert evidence[-1]["repository_v2_daily_rows"] == 0
    assert evidence[-1]["kind"] == "EXPECTED_SESSION_SOURCE_OR_AUTHORITY_GAP"
