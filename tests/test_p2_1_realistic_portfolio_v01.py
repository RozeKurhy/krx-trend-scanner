import pandas as pd

from scripts.run_p2_1_realistic_portfolio_v01 import _frame_for_record


def test_frame_lookup_matches_identity_segment_pipe_key():
    record = {
        "ticker": "005930",
        "isu_cd": "KR7005930003",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2026-09-21",
    }
    frame = pd.DataFrame({"open": [100.0]})
    frames = {"005930|KR7005930003|KOSPI|2010-01-04|2026-09-21": frame}

    assert _frame_for_record(record, frames) is frame
