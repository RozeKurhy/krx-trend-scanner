from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.foreign_flow_rolling import (
    BLOCKED,
    NOOP_ALREADY_COMPLETE,
    PASS,
    update_foreign_flow_snapshot,
)


FLOW_DIR = Path("artifacts/patterns/pattern_a/production/flow/source")


class FakeCalendar:
    def __init__(self, dates: list[str], *, authority_frontier: str | None = None):
        self.trading_dates = pd.DatetimeIndex(dates)
        self.authority_frontier = authority_frontier or max(dates)


class FakeProvider:
    def __init__(self, responses: dict[str, pd.DataFrame]):
        self.responses = responses
        self.calls: list[str] = []

    def fetch_date_batch(self, date: str) -> pd.DataFrame:
        self.calls.append(date)
        return self.responses[date].copy()


def _flow(dates: list[str], *, ticker: str = "005930", base: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "ticker": [ticker] * len(dates),
            "foreign_net_buy_value": [base + i for i in range(len(dates))],
            "foreign_buy_value": [base + 100 + i for i in range(len(dates))],
            "foreign_sell_value": [base + 50 + i for i in range(len(dates))],
        }
    )


def _write_snapshot(repo_root: Path, as_of: str, frame: pd.DataFrame) -> Path:
    output = repo_root / FLOW_DIR / f"foreign_flow_daily_{as_of.replace('-', '')}.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    output.with_name(f"foreign_flow_daily_{as_of.replace('-', '')}_meta.json").write_text(
        json.dumps({"requested_as_of": as_of}, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def test_exact_target_noop_has_zero_fetch_and_zero_write(tmp_path: Path):
    target = "2026-09-05"
    output = _write_snapshot(tmp_path, target, _flow(["2026-09-04"]))
    before_bytes = output.read_bytes()
    before_meta = output.with_name("foreign_flow_daily_20260905_meta.json").read_bytes()
    before_mtime = output.stat().st_mtime_ns
    provider = FakeProvider({})

    result = update_foreign_flow_snapshot(
        target,
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-04"]),
    )

    assert result.status == NOOP_ALREADY_COMPLETE
    assert provider.calls == []
    assert output.read_bytes() == before_bytes
    assert output.with_name("foreign_flow_daily_20260905_meta.json").read_bytes() == before_meta
    assert output.stat().st_mtime_ns == before_mtime


def test_exact_target_middle_gap_is_repaired_then_noops(tmp_path: Path):
    target = "2026-09-17"
    _write_snapshot(
        tmp_path,
        target,
        _flow(["2026-09-14", "2026-09-16", "2026-09-17"]),
    )
    provider = FakeProvider({"2026-09-15": _flow(["2026-09-15"])})
    calendar = FakeCalendar(["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"])

    first = update_foreign_flow_snapshot(
        target,
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )
    first_calls = list(provider.calls)
    second = update_foreign_flow_snapshot(
        target,
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )

    assert first.status == PASS
    assert first_calls == ["2026-09-15"]
    assert second.status == NOOP_ALREADY_COMPLETE
    assert provider.calls == first_calls
    final = pd.read_parquet(tmp_path / FLOW_DIR / "foreign_flow_daily_20260917.parquet")
    assert final["date"].tolist() == [
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
    ]


def test_tail_incremental_fetches_only_new_dates_and_publishes_exact_target(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-04", _flow(["2026-09-03", "2026-09-04"]))
    provider = FakeProvider(
        {
            "2026-09-07": _flow(["2026-09-07"]),
            "2026-09-08": _flow(["2026-09-08"]),
        }
    )

    result = update_foreign_flow_snapshot(
        "2026-09-08",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"]),
    )

    assert result.status == PASS
    assert provider.calls == ["2026-09-07", "2026-09-08"]
    assert result.missing_trading_dates == provider.calls
    assert result.fetched_trading_dates == provider.calls
    output = tmp_path / FLOW_DIR / "foreign_flow_daily_20260908.parquet"
    final = pd.read_parquet(output)
    assert final["date"].tolist() == ["2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08"]
    assert not final.duplicated(["date", "ticker"]).any()
    assert json.loads(output.with_name("foreign_flow_daily_20260908_meta.json").read_text())[
        "pykrx_data_calls"
    ] == 2


def test_middle_gap_and_tail_gap_are_both_fetched(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-03", _flow(["2026-09-01", "2026-09-03"]))
    provider = FakeProvider(
        {
            "2026-09-02": _flow(["2026-09-02"]),
            "2026-09-04": _flow(["2026-09-04"]),
        }
    )

    result = update_foreign_flow_snapshot(
        "2026-09-04",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    )

    assert result.status == PASS
    assert provider.calls == ["2026-09-02", "2026-09-04"]
    final = pd.read_parquet(tmp_path / FLOW_DIR / "foreign_flow_daily_20260904.parquet")
    assert final["date"].tolist() == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
    ]


def test_non_trading_target_publishes_exact_snapshot_then_noops(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-11", _flow(["2026-09-10", "2026-09-11"]))
    provider = FakeProvider({})
    calendar = FakeCalendar(["2026-09-10", "2026-09-11"])

    first = update_foreign_flow_snapshot(
        "2026-09-12",
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )
    second = update_foreign_flow_snapshot(
        "2026-09-12",
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )

    assert first.status == PASS
    assert first.missing_trading_dates == []
    assert first.date_max == "2026-09-11"
    assert second.status == NOOP_ALREADY_COMPLETE
    assert provider.calls == []


def test_sunday_weekend_bridge_publishes_then_noops(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-11", _flow(["2026-09-10", "2026-09-11"]))
    provider = FakeProvider({})
    calendar = FakeCalendar(["2026-09-10", "2026-09-11"])

    first = update_foreign_flow_snapshot(
        "2026-09-13",
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )
    second = update_foreign_flow_snapshot(
        "2026-09-13",
        repo_root=tmp_path,
        provider=provider,
        calendar=calendar,
    )

    assert first.status == PASS
    assert first.missing_trading_dates == []
    assert first.date_max == "2026-09-11"
    assert second.status == NOOP_ALREADY_COMPLETE
    assert provider.calls == []


def test_empty_required_date_blocks_without_publishing_target(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-04", _flow(["2026-09-04"]))
    provider = FakeProvider(
        {"2026-09-07": pd.DataFrame(columns=_flow(["2026-09-07"]).columns)}
    )

    result = update_foreign_flow_snapshot(
        "2026-09-08",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-04", "2026-09-07", "2026-09-08"]),
    )

    assert result.status == BLOCKED
    assert provider.calls == ["2026-09-07"]
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260908.parquet").exists()
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260908_meta.json").exists()


def test_invalid_seed_duplicate_blocks_without_network_or_repair(tmp_path: Path):
    duplicate = _flow(["2026-09-03", "2026-09-03"])
    _write_snapshot(tmp_path, "2026-09-04", duplicate)
    provider = FakeProvider({"2026-09-08": _flow(["2026-09-08"])})

    result = update_foreign_flow_snapshot(
        "2026-09-08",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-03", "2026-09-08"]),
    )

    assert result.status == BLOCKED
    assert provider.calls == []
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260908.parquet").exists()


def test_no_usable_seed_blocks_without_historical_rebuild(tmp_path: Path):
    provider = FakeProvider({"2026-09-08": _flow(["2026-09-08"])})

    result = update_foreign_flow_snapshot(
        "2026-09-08",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-08"]),
    )

    assert result.status == BLOCKED
    assert result.reason == "NO_USABLE_SEED_SNAPSHOT"
    assert provider.calls == []


def test_authority_frontier_insufficient_blocks_before_fetch_or_target_write(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-17", _flow(["2026-09-17"]))
    provider = FakeProvider({"2026-09-18": _flow(["2026-09-18"])})

    result = update_foreign_flow_snapshot(
        "2026-09-18",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(
            ["2026-09-17"],
            authority_frontier="2026-09-17",
        ),
    )

    assert result.status == BLOCKED
    assert result.reason == (
        "ROLLING_AUTHORITY_FRONTIER_INSUFFICIENT:"
        "frontier=2026-09-17:target=2026-09-18"
    )
    assert provider.calls == []
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260918.parquet").exists()
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260918_meta.json").exists()


def test_exact_target_beyond_authority_frontier_is_not_noop_or_rewritten(tmp_path: Path):
    output = _write_snapshot(
        tmp_path,
        "2026-09-18",
        _flow(["2026-09-17", "2026-09-18"]),
    )
    meta_path = output.with_name("foreign_flow_daily_20260918_meta.json")
    before_bytes = output.read_bytes()
    before_meta = meta_path.read_bytes()
    before_mtime = output.stat().st_mtime_ns
    provider = FakeProvider({"2026-09-18": _flow(["2026-09-18"], base=999.0)})

    result = update_foreign_flow_snapshot(
        "2026-09-18",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(
            ["2026-09-17"],
            authority_frontier="2026-09-17",
        ),
    )

    assert result.status == BLOCKED
    assert provider.calls == []
    assert output.read_bytes() == before_bytes
    assert meta_path.read_bytes() == before_meta
    assert output.stat().st_mtime_ns == before_mtime


def test_weekday_between_frontier_and_weekend_target_blocks_without_fetch_or_write(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-10", _flow(["2026-09-10"]))
    provider = FakeProvider({"2026-09-11": _flow(["2026-09-11"])})

    result = update_foreign_flow_snapshot(
        "2026-09-12",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-10"]),
    )

    assert result.status == BLOCKED
    assert provider.calls == []
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260912.parquet").exists()
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260912_meta.json").exists()


def test_weekday_target_after_weekend_blocks_without_fetch_or_write(tmp_path: Path):
    _write_snapshot(tmp_path, "2026-09-11", _flow(["2026-09-11"]))
    provider = FakeProvider({"2026-09-14": _flow(["2026-09-14"])})

    result = update_foreign_flow_snapshot(
        "2026-09-14",
        repo_root=tmp_path,
        provider=provider,
        calendar=FakeCalendar(["2026-09-11"]),
    )

    assert result.status == BLOCKED
    assert provider.calls == []
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260914.parquet").exists()
    assert not (tmp_path / FLOW_DIR / "foreign_flow_daily_20260914_meta.json").exists()
