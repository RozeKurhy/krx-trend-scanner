"""Negative Control Validation v0.1: exploration/holdout(positive)와
negative_control(false positive 후보) 그룹을 비교하는 순수 분석 함수 모음.

Pattern A 점수는 만들지 않는다. 여기서 계산하는 건 그룹별 min/median/max와
조건(단일 Feature/조합) 발생 비율뿐이다 — 전부 관찰용이며 threshold를
확정하거나 가중치를 매기지 않는다.

이 모듈은 계산만 한다. print/CSV 쓰기는 scripts/negative_control_validate.py가
담당한다(Feature Validation v0.1부터 이어진 계산/출력 분리 원칙).

입력은 FeatureRow를 요구하지 않는다 — 필요한 속성(ma24_slope 등)만
getattr로 읽으므로, 같은 속성을 가진 어떤 객체(FeatureRow, 테스트용
SimpleNamespace 등)로도 동작한다. 그래서 unit test는 실제 KRX 데이터 없이
synthetic 객체로 작성한다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

from trend_scanner.validation.historical_snapshot import HistoricalSnapshot
from trend_scanner.validation.historical_snapshot import to_csv_row as _snapshot_to_csv_row


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _value(row: Any, attr: str) -> float:
    return getattr(row, attr)


def _gt(row: Any, attr: str, threshold: float) -> bool:
    v = _value(row, attr)
    return (not _is_missing(v)) and v > threshold


def _le(row: Any, attr: str, threshold: float) -> bool:
    v = _value(row, attr)
    return (not _is_missing(v)) and v <= threshold


def _lt(row: Any, attr: str, threshold: float) -> bool:
    v = _value(row, attr)
    return (not _is_missing(v)) and v < threshold


# 단일 조건 + 조합 조건. 15번 항목의 Combination A~E를 그대로 옮긴 것.
# 점수/가중치가 아니라 "몇 %에서 나타나는가"만 본다.
CONDITIONS: dict[str, Callable[[Any], bool]] = {
    "weekly_ma12_slope>0": lambda f: _gt(f, "weekly_ma12_slope", 0),
    "ma24_slope>0": lambda f: _gt(f, "ma24_slope", 0),
    "ma24_slope_acceleration>0": lambda f: _gt(f, "ma24_slope_acceleration", 0),
    "A: weekly>0 & ma24<=0": lambda f: _gt(f, "weekly_ma12_slope", 0) and _le(f, "ma24_slope", 0),
    "B: weekly>0 & accel>0": lambda f: _gt(f, "weekly_ma12_slope", 0) and _gt(f, "ma24_slope_acceleration", 0),
    "C: weekly>0 & range_position<0.6": lambda f: _gt(f, "weekly_ma12_slope", 0) and _lt(f, "range_position", 0.6),
    "D: ma24>0 & accel>0": lambda f: _gt(f, "ma24_slope", 0) and _gt(f, "ma24_slope_acceleration", 0),
    "E: weekly>0 & ma24>0 & accel>0": lambda f: (
        _gt(f, "weekly_ma12_slope", 0) and _gt(f, "ma24_slope", 0) and _gt(f, "ma24_slope_acceleration", 0)
    ),
}


def snapshot_csv_rows(
    labeled_snapshots: Iterable[tuple[str, HistoricalSnapshot]], set_name: str
) -> list[dict[str, Any]]:
    """(label, HistoricalSnapshot) 목록을 CSV row로 바꾸고 set 컬럼을 붙인다."""
    rows = []
    for label, snapshot in labeled_snapshots:
        row = _snapshot_to_csv_row(label, snapshot)
        row["set"] = set_name
        rows.append(row)
    return rows


@dataclass
class GroupStats:
    n: int
    min: float
    median: float
    max: float


def group_stats(rows: Sequence[Any], attr: str) -> GroupStats:
    """rows에서 attr 값을 뽑아 NaN을 뺀 min/median/max를 계산한다. 전부 NaN/빈 그룹이면 NaN."""
    values = [v for v in (_value(r, attr) for r in rows) if not _is_missing(v)]
    if not values:
        nan = float("nan")
        return GroupStats(n=0, min=nan, median=nan, max=nan)
    return GroupStats(
        n=len(values),
        min=min(values),
        median=statistics.median(values),
        max=max(values),
    )


def stats_table(groups: dict[str, Sequence[Any]], attrs: Sequence[str]) -> pd.DataFrame:
    """attrs x groups 조합마다 group_stats를 계산해 long-format DataFrame으로 반환한다."""
    records = []
    for attr in attrs:
        for group_name, rows in groups.items():
            stats = group_stats(rows, attr)
            records.append(
                {
                    "feature": attr,
                    "group": group_name,
                    "n": stats.n,
                    "min": stats.min,
                    "median": stats.median,
                    "max": stats.max,
                }
            )
    return pd.DataFrame(records)


def condition_ratio(rows: Sequence[Any], predicate: Callable[[Any], bool]) -> tuple[int, int]:
    """(조건을 만족하는 행 수, 전체 행 수). NaN이 낀 행은 predicate가 False를 내야 한다."""
    total = len(rows)
    matched = sum(1 for r in rows if predicate(r))
    return matched, total


def condition_table(
    groups: dict[str, Sequence[Any]],
    conditions: dict[str, Callable[[Any], bool]] = CONDITIONS,
) -> pd.DataFrame:
    """condition x group 조합마다 k/n과 비율(%)을 계산해 DataFrame으로 반환한다."""
    records = []
    for cond_name, predicate in conditions.items():
        row: dict[str, Any] = {"condition": cond_name}
        for group_name, rows in groups.items():
            matched, total = condition_ratio(rows, predicate)
            pct = (matched / total * 100) if total else float("nan")
            row[f"{group_name}_k/n"] = f"{matched}/{total}"
            row[f"{group_name}_pct"] = pct
        records.append(row)
    return pd.DataFrame(records)
