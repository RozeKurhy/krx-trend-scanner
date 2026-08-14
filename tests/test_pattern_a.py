import pandas as pd
import pytest

from trend_scanner.patterns.pattern_a import evaluate_pattern_a


def test_evaluate_pattern_a_not_implemented_yet():
    daily = pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([]),
    )
    with pytest.raises(NotImplementedError):
        evaluate_pattern_a(daily)
