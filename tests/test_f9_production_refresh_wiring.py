from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from trend_scanner.data.rolling_market_data_refresh import resolve_current_identity


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/refresh_market_data_v01.py"
SPEC = importlib.util.spec_from_file_location("refresh_market_data_v01", SCRIPT_PATH)
assert SPEC and SPEC.loader
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


def test_common_population_builder_includes_new_pit_common_without_store(tmp_path) -> None:
    pit_path = tmp_path / "merged_pit_intervals.json"
    pit_path.write_text(
        json.dumps(
            {
                "intervals": [
                    {"ticker": "005930", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-09-11"},
                    {"ticker": "999999", "state": "COMMON", "effective_from": "2026-09-08", "effective_to": "2026-09-11"},
                    {"ticker": "069500", "state": "COMMON", "effective_from": "2010-01-04", "effective_to": "2026-09-11"},
                ]
            }
        ),
        encoding="utf-8",
    )

    removed_path = tmp_path / "removed_identities.json"
    removed_path.write_text(json.dumps({"removed_identities": ["121910"]}), encoding="utf-8")
    zero_path = tmp_path / "zero_store_contract.json"
    zero_path.write_text(json.dumps({"tickers": ["000610"]}), encoding="utf-8")

    tickers = refresh.load_effective_common_adjusted_population(
        pit_path,
        etf_acceptance_tickers=("069500",),
        removed_identity_audit_path=removed_path,
        zero_store_contract_path=zero_path,
        effective_population_path=None,
    )

    assert "999999" in tickers
    assert "005930" in tickers
    assert "121910" not in tickers
    assert "000610" not in tickers
    assert "069500" not in tickers


def test_production_population_reuses_f8_removed_and_zero_authorities() -> None:
    tickers = refresh.load_common_adjusted_tickers_from_pit(
        ROOT / "data/market/rolling_authority/merged_pit_intervals.json",
    )

    assert {
        "121910", "121950", "122290", "122750", "123160", "123290", "123300",
        "123550", "123910", "124050", "126680", "128910", "380440",
    }.isdisjoint(tickers)
    assert {"000610", "015940", "037510", "045820"}.isdisjoint(tickers)
    assert "386380" in tickers


def test_frozen_removed_identity_is_excluded(tmp_path) -> None:
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "ticker": "121910",
                        "isu_cd": "KR7121910004",
                        "market": "KOSPI",
                        "state": "COMMON",
                        "effective_from": "2010-03-03",
                        "effective_to": "2012-10-12",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    removed_path = tmp_path / "removed.json"
    removed_path.write_text(
        json.dumps(
            {
                "removed_identities": [
                    {
                        "ticker": "121910",
                        "isu_cd": "KR7121910004",
                        "market": "KOSPI",
                        "effective_from": "2010-03-03",
                        "effective_to": "2012-10-12",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    tickers = refresh.load_effective_common_adjusted_population(
        pit_path,
        etf_acceptance_tickers=(),
        removed_identity_audit_path=removed_path,
        zero_store_contract_path=None,
        effective_population_path=None,
        identity_as_of="2026-09-11",
    )

    assert "121910" not in tickers


def test_same_ticker_new_identity_remains_eligible(tmp_path) -> None:
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "ticker": "121910",
                        "isu_cd": "KR7121910004",
                        "market": "KOSPI",
                        "state": "COMMON",
                        "effective_from": "2010-03-03",
                        "effective_to": "2012-10-12",
                    },
                    {
                        "ticker": "121910",
                        "isu_cd": "KR7999990001",
                        "market": "KOSDAQ",
                        "state": "COMMON",
                        "effective_from": "2026-09-08",
                        "effective_to": "2026-09-11",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    removed_path = tmp_path / "removed.json"
    removed_path.write_text(
        json.dumps(
            {
                "removed_identities": [
                    {
                        "ticker": "121910",
                        "isu_cd": "KR7121910004",
                        "market": "KOSPI",
                        "effective_from": "2010-03-03",
                        "effective_to": "2012-10-12",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    tickers = refresh.load_effective_common_adjusted_population(
        pit_path,
        etf_acceptance_tickers=(),
        removed_identity_audit_path=removed_path,
        zero_store_contract_path=None,
        effective_population_path=None,
        identity_as_of="2026-09-11",
    )

    assert "121910" in tickers


def test_historical_single_identity_is_excluded_from_rolling_refresh_population(tmp_path) -> None:
    pit_path = tmp_path / "pit.json"
    pit_path.write_text(
        json.dumps(
            {
                "intervals": [
                    {"ticker": "000001", "isu_cd": "KR7000000001", "market": "KOSPI", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-09-10"},
                    {"ticker": "000002", "isu_cd": "KR7000000002", "market": "KOSPI", "state": "COMMON", "effective_from": "2020-01-01", "effective_to": "2026-09-11"},
                    {"ticker": "000003", "isu_cd": "KR7000000003", "market": "KOSPI", "state": "COMMON", "effective_from": "2026-09-12", "effective_to": "2026-09-20"},
                ]
            }
        ),
        encoding="utf-8",
    )
    intervals = {
        ticker: [interval]
        for interval in json.loads(pit_path.read_text(encoding="utf-8"))["intervals"]
        for ticker in [interval["ticker"]]
    }

    historical_resolution = resolve_current_identity("000001", "2026-09-11", intervals)
    assert historical_resolution.status == "RESOLVED"
    assert refresh.load_effective_common_adjusted_population(
        pit_path,
        etf_acceptance_tickers=(),
        removed_identity_audit_path=None,
        zero_store_contract_path=None,
        effective_population_path=None,
        identity_as_of="2026-09-11",
    ) == ["000002"]


def test_population_audit_binds_supplied_live_pit_and_calendar(tmp_path, monkeypatch) -> None:
    adjusted_dir = tmp_path / "adjusted"
    pit_path = tmp_path / "merged_pit.json"
    calendar_path = tmp_path / "merged_calendar.json"
    seen: dict[str, object] = {}

    class _Audit:
        unexplained_gap_count = 0
        total_in_scope = 0
        ok_count = 0
        explained_gap_count = 0
        records = ()

    def fake_audit(**kwargs):
        seen.update(kwargs)
        return _Audit()

    monkeypatch.setattr(refresh, "audit_full_population_bootstrap", fake_audit)
    audit = refresh.build_population_gap_audit(
        adjusted_store_dir=adjusted_dir,
        candidate_boundary="2026-09-11",
        pit_path=pit_path,
        historical_calendar_path=calendar_path,
    )

    assert audit() == {
        "candidate_boundary": "2026-09-11",
        "total_in_scope": 0,
        "common_scope_count": 0,
        "etf_scope_count": len(refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS),
        "ok_count": 0,
        "explained_gap_count": 0,
        "unexplained_gap_count": 0,
        "reason_breakdown": {},
        "unexplained_reason_breakdown": {},
    }
    assert seen["adjusted_store_dir"] == adjusted_dir
    assert seen["candidate_boundary"] == "2026-09-11"
    assert seen["pit_path"] == pit_path
    assert seen["historical_calendar_path"] == calendar_path


def test_production_refresh_and_rolling_audit_population_parity() -> None:
    pit_path = ROOT / "data/market/rolling_authority/merged_pit_intervals.json"
    refresh_scope = refresh.load_common_adjusted_tickers_from_pit(
        pit_path,
        identity_as_of="2026-09-11",
    )
    audit = refresh.audit_full_population_bootstrap(
        adjusted_store_dir=ROOT / "data/market/adjusted/stocks",
        candidate_boundary="2026-09-11",
        etf_acceptance_tickers=refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS,
        pit_path=pit_path,
        historical_calendar_path=ROOT / "data/market/rolling_authority/merged_trading_calendar.json",
    )
    etf_tickers = {str(ticker).zfill(6) for ticker in refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS}
    audit_common_scope = [record for record in audit.records if record.ticker not in etf_tickers]

    assert len(refresh_scope) == len(audit_common_scope)
    assert audit.total_in_scope == len(refresh_scope) + len(etf_tickers)
