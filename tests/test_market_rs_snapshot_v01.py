"""Phase 3C Market RS exact-date snapshot builder 집중 시험 (w.md T1~T13).

실제 네트워크/실제 Repository V2/실제 IndexStore를 쓰지 않는다. `build_market_rs_snapshot_v01`
모듈이 이름으로 참조하는 `load_rolling_authority`/`IndexStore`/`build_production_repository_v2`/
`RepositoryV2DailyLoader`를 fake로 monkeypatch하고, PIT는 tmp_path에 실제 JSON 파일로 둔다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.rolling_market_data_refresh import DEFAULT_MERGED_PIT_PATH, RollingAuthorityError

import scripts.build_market_rs_snapshot_v01 as mrs


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _write_pit(repo_root: Path, intervals: list[dict]) -> None:
    pit_path = repo_root / DEFAULT_MERGED_PIT_PATH
    pit_path.parent.mkdir(parents=True, exist_ok=True)
    pit_path.write_text(json.dumps({"intervals": intervals}, ensure_ascii=False), encoding="utf-8")


def _interval(ticker: str, market: str, effective_from: str, effective_to: str, state: str = "COMMON", isu_cd: str | None = None) -> dict:
    return {
        "ticker": ticker,
        "isu_cd": isu_cd or f"KR7{ticker}0000",
        "market": market,
        "state": state,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def _patch_authority(monkeypatch: pytest.MonkeyPatch, certified_through: str) -> None:
    monkeypatch.setattr(
        mrs, "load_rolling_authority", lambda directory: SimpleNamespace(certified_through=certified_through)
    )


def _bench_frame(end: str, n: int, code: str, start_price: float = 1000.0, step: float = 1.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "index_code": [code] * n,
            "close": [start_price + i * step for i in range(n)],
        }
    )


def _stock_frame(end: str, n: int, start_price: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"close": [start_price + i * step for i in range(n)]}, index=dates)


def _patch_index(monkeypatch: pytest.MonkeyPatch, frames: dict[str, pd.DataFrame]) -> None:
    class _FakeIndexStore:
        def __init__(self, root=None) -> None:
            self._frames = frames

        def load_family(self, family, start=None, end=None, index_codes=None):
            codes = list(index_codes) if index_codes is not None else list(self._frames)
            parts = []
            for code in codes:
                frame = self._frames.get(code)
                if frame is None or frame.empty:
                    continue
                part = frame.copy()
                if end is not None:
                    part = part[part["date"] <= str(end)[:10]]
                if not part.empty:
                    parts.append(part)
            if not parts:
                return pd.DataFrame(columns=["date", "index_code", "close"])
            return pd.concat(parts, ignore_index=True).sort_values(["date", "index_code"]).reset_index(drop=True)

    monkeypatch.setattr(mrs, "IndexStore", _FakeIndexStore)


def _patch_repository(monkeypatch: pytest.MonkeyPatch, stock_data: dict[str, object]) -> list:
    """stock_data: ticker -> DataFrame | None | Exception instance."""

    calls: list[str] = []

    class _FakeLoader:
        def __init__(self, repository, *, start=None, end=None) -> None:
            self.repository = repository
            self.start = start
            self.end = end
            self.load_count = 0

        def load(self, ticker: str):
            self.load_count += 1
            calls.append(ticker)
            behavior = stock_data.get(ticker)
            if isinstance(behavior, BaseException):
                raise behavior
            return behavior

    monkeypatch.setattr(mrs, "build_production_repository_v2", lambda repo_root, end=None: object())
    monkeypatch.setattr(mrs, "RepositoryV2DailyLoader", _FakeLoader)
    return calls


def _read_output(repo_root: Path, target: str) -> pd.DataFrame:
    path = mrs._output_path(repo_root, target)
    return pd.read_csv(path, dtype={"ticker": str})


# ---------------------------------------------------------------------------
# T1 explicit as-of
# ---------------------------------------------------------------------------


def test_t1_as_of_required_no_system_date_fallback():
    with pytest.raises(SystemExit):
        mrs._build_parser().parse_args([])


# ---------------------------------------------------------------------------
# T2 target beyond certified boundary
# ---------------------------------------------------------------------------


def test_t2_target_beyond_certified_boundary_is_blocked(tmp_path, monkeypatch):
    _patch_authority(monkeypatch, "2026-09-17")
    _write_pit(tmp_path, [_interval("005930", "KOSPI", "2010-01-04", "2026-09-18")])

    result = mrs.build_market_rs_snapshot("2026-09-18", repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert result.reason == "TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY"
    assert not mrs._output_path(tmp_path, "2026-09-18").exists()


# ---------------------------------------------------------------------------
# T3 exact PIT COMMON population
# ---------------------------------------------------------------------------


def test_t3_population_includes_only_target_active_common(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000001", "KOSPI", "2010-01-04", "2026-09-17"),  # target active KOSPI COMMON
            _interval("000002", "KOSDAQ", "2010-01-04", "2026-09-17"),  # target active KOSDAQ COMMON
            _interval("000003", "KOSPI", "2010-01-04", "2026-08-01"),  # ended before target
            _interval("000004", "KOSPI", "2026-10-01", "2027-01-01"),  # starts after target
            _interval("000005", "KOSPI", "2010-01-04", "2026-09-17", state="ETF"),  # non-COMMON
        ],
    )
    population = mrs._load_pit_common_population(tmp_path, target)
    tickers = {row["ticker"] for row in population}
    assert tickers == {"000001", "000002"}


def test_t3_ambiguous_identity_blocks(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000009", "KOSPI", "2010-01-04", "2026-09-17", isu_cd="KR1"),
            _interval("000009", "KOSPI", "2015-01-01", "2026-09-17", isu_cd="KR2"),
        ],
    )
    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert result.status == mrs.BLOCKED
    assert result.reason.startswith("PIT_IDENTITY_AMBIGUOUS")
    assert not mrs._output_path(tmp_path, target).exists()


# ---------------------------------------------------------------------------
# T4 denominator is full PIT COMMON (price-missing rows preserved)
# ---------------------------------------------------------------------------


def test_t4_price_missing_common_ticker_row_preserved(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000001", "KOSPI", "2010-01-04", target),
            _interval("000002", "KOSPI", "2010-01-04", target),
            _interval("000003", "KOSPI", "2010-01-04", target),
        ],
    )
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(
        monkeypatch,
        {
            "000001": _stock_frame(target, 20),
            "000002": _stock_frame(target, 20),
            "000003": None,  # explicit DATA_UNAVAILABLE
        },
    )

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.PASS
    frame = _read_output(tmp_path, target)
    assert set(frame["ticker"]) == {"000001", "000002", "000003"}
    row_c = frame[frame["ticker"] == "000003"].iloc[0]
    assert row_c["market_rs_data_status"] == "DATA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# T5 full-population percentile (not a candidate/investable subset)
# ---------------------------------------------------------------------------


def test_t5_percentile_is_over_full_population(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000001", "KOSPI", "2010-01-04", target),
            _interval("000002", "KOSPI", "2010-01-04", target),
            _interval("000003", "KOSPI", "2010-01-04", target),
        ],
    )
    bench = _bench_frame(target, 15, "1001", start_price=1000.0, step=1.0)
    _patch_index(monkeypatch, {"1001": bench, "2001": _bench_frame(target, 15, "2001")})
    # A rises faster than benchmark, B tracks benchmark, C falls vs benchmark => A > B > C on rs_2w.
    _patch_repository(
        monkeypatch,
        {
            "000001": _stock_frame(target, 15, start_price=100.0, step=5.0),
            "000002": _stock_frame(target, 15, start_price=100.0, step=1.0),
            "000003": _stock_frame(target, 15, start_price=100.0, step=0.1),
        },
    )

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert result.status == mrs.PASS
    frame = _read_output(tmp_path, target).set_index("ticker")
    assert frame.loc["000001", "market_rs_2w"] > frame.loc["000002", "market_rs_2w"] > frame.loc["000003", "market_rs_2w"]
    assert frame.loc["000001", "all_market_rs_percentile_2w"] == 100.0
    assert frame.loc["000003", "all_market_rs_percentile_2w"] == pytest.approx(0.0)
    # percentile population size is exactly 3 (full COMMON population), not a 1-ticker candidate subset.
    assert frame["all_market_rs_rank_2w"].notna().sum() == 3


# ---------------------------------------------------------------------------
# T6 market mapping
# ---------------------------------------------------------------------------


def test_t6_market_benchmark_mapping(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000001", "KOSPI", "2010-01-04", target),
            _interval("000002", "KOSDAQ", "2010-01-04", target),
        ],
    )
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20), "000002": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert result.status == mrs.PASS
    frame = _read_output(tmp_path, target).set_index("ticker")
    assert str(int(float(frame.loc["000001", "market_benchmark_code"]))) == "1001"
    assert str(int(float(frame.loc["000002", "market_benchmark_code"]))) == "2001"


# ---------------------------------------------------------------------------
# T7 exact target benchmark missing (both KOSPI and KOSDAQ)
# ---------------------------------------------------------------------------


def test_t7_both_benchmarks_missing_exact_target_is_blocked(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target)])
    # Benchmarks only have history through the previous day -- no exact target row.
    _patch_index(
        monkeypatch,
        {"1001": _bench_frame("2026-09-16", 20, "1001"), "2001": _bench_frame("2026-09-16", 20, "2001")},
    )
    calls = _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert result.reason == "MARKET_INDEX_TARGET_UNAVAILABLE"
    assert not mrs._output_path(tmp_path, target).exists()
    assert calls == []  # Repository V2 must not be touched once the benchmark gate fails.


def test_t7a_kospi_exact_but_kosdaq_missing_is_blocked(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target)])
    _patch_index(
        monkeypatch,
        {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame("2026-09-16", 20, "2001")},
    )
    calls = _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert result.reason == "MARKET_INDEX_TARGET_UNAVAILABLE"
    assert not mrs._output_path(tmp_path, target).exists()
    assert calls == []


def test_t7b_kospi_missing_but_kosdaq_exact_is_blocked(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target)])
    _patch_index(
        monkeypatch,
        {"1001": _bench_frame("2026-09-16", 20, "1001"), "2001": _bench_frame(target, 20, "2001")},
    )
    calls = _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert result.reason == "MARKET_INDEX_TARGET_UNAVAILABLE"
    assert not mrs._output_path(tmp_path, target).exists()
    assert calls == []


# ---------------------------------------------------------------------------
# T8 expected ticker DATA_UNAVAILABLE (covered structurally by T4; kept as an explicit alias)
# ---------------------------------------------------------------------------


def test_t8_explicit_repository_unavailable_does_not_fail_whole_build(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target)])
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(monkeypatch, {"000001": None})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.PASS
    frame = _read_output(tmp_path, target)
    assert len(frame) == 1
    assert frame.iloc[0]["market_rs_data_status"] == "DATA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# T9 unexpected repository/authority error
# ---------------------------------------------------------------------------


def test_t9_unexpected_market_data_error_fails_without_partial_output(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000001", "KOSPI", "2010-01-04", target),
            _interval("000002", "KOSPI", "2010-01-04", target),
        ],
    )
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(
        monkeypatch,
        {"000001": _stock_frame(target, 20), "000002": MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")},
    )

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.FAILED
    assert not mrs._output_path(tmp_path, target).exists()


def test_t9_rolling_authority_error_blocks_without_partial_output(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target)])
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(monkeypatch, {"000001": RollingAuthorityError("IDENTITY_AMBIGUITY_FAIL_CLOSED")})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert not mrs._output_path(tmp_path, target).exists()


# ---------------------------------------------------------------------------
# T10 same-target valid NOOP
# ---------------------------------------------------------------------------


def test_t10_valid_existing_exact_artifact_is_noop(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target), _interval("000002", "KOSPI", "2010-01-04", target)])
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    calls = _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20), "000002": _stock_frame(target, 20)})

    first = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert first.status == mrs.PASS
    output_path = mrs._output_path(tmp_path, target)
    mtime_before = output_path.stat().st_mtime_ns
    size_before = output_path.stat().st_size
    calls.clear()

    second = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert second.status == mrs.NOOP_ALREADY_COMPLETE
    assert calls == []  # Repository V2 ticker calculation = 0
    assert output_path.stat().st_mtime_ns == mtime_before
    assert output_path.stat().st_size == size_before


# ---------------------------------------------------------------------------
# T11 invalid existing artifact
# ---------------------------------------------------------------------------


def test_t11_invalid_existing_artifact_blocks_without_overwrite(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("000001", "KOSPI", "2010-01-04", target), _interval("000002", "KOSPI", "2010-01-04", target)])

    output_path = mrs._output_path(tmp_path, target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Missing ticker 000002 -> ticker-set mismatch against the current PIT population.
    stale = pd.DataFrame([{column: None for column in mrs.OUTPUT_COLUMNS}])
    stale.loc[0, "ticker"] = "000001"
    stale.loc[0, "market"] = "KOSPI"
    stale.loc[0, "as_of"] = target
    stale.to_csv(output_path, index=False)
    original_bytes = output_path.read_bytes()

    calls = _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20), "000002": _stock_frame(target, 20)})
    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)

    assert result.status == mrs.BLOCKED
    assert result.reason.startswith("EXISTING_EXACT_ARTIFACT_INVALID")
    assert output_path.read_bytes() == original_bytes  # not overwritten
    assert calls == []


# ---------------------------------------------------------------------------
# T12 deterministic output
# ---------------------------------------------------------------------------


def test_t12_deterministic_output_ordering_and_values(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(
        tmp_path,
        [
            _interval("000002", "KOSDAQ", "2010-01-04", target),
            _interval("000001", "KOSPI", "2010-01-04", target),
        ],
    )
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(monkeypatch, {"000001": _stock_frame(target, 20), "000002": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert result.status == mrs.PASS
    frame = _read_output(tmp_path, target)
    # compute_market_rs_cross_section sorts by (market, ticker); KOSDAQ < KOSPI alphabetically.
    assert list(frame["market"]) == ["KOSDAQ", "KOSPI"]
    assert list(frame["ticker"]) == ["000002", "000001"]


# ---------------------------------------------------------------------------
# T13 report consumer compatibility
# ---------------------------------------------------------------------------


def test_t13_report_consumer_reads_published_snapshot(tmp_path, monkeypatch):
    target = "2026-09-17"
    _patch_authority(monkeypatch, target)
    _write_pit(tmp_path, [_interval("005930", "KOSPI", "2010-01-04", target)])
    _patch_index(monkeypatch, {"1001": _bench_frame(target, 20, "1001"), "2001": _bench_frame(target, 20, "2001")})
    _patch_repository(monkeypatch, {"005930": _stock_frame(target, 20)})

    result = mrs.build_market_rs_snapshot(target, repo_root=tmp_path)
    assert result.status == mrs.PASS

    from trend_scanner.reporting.relative_strength_report import load_relative_strength_section

    section = load_relative_strength_section("005930", target, "COMMON", "KOSPI", tmp_path)
    assert section.applicability == "APPLICABLE"
    assert section.source_as_of == target
