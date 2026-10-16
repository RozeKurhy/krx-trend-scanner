import json
from pathlib import Path

import pytest

from scripts import export_b_select_core_v2_identity_reports_web as identity_web


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_canonical_v2_exact_identities_have_identity_bound_report_routes():
    status = _json(ROOT / "artifacts/strategies/b_select_core_v2/production/20261003/status.json")
    routes = _json(ROOT / "web/data/identity-report-routes.json")
    expected = {
        (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper())
        for row in status["canonical_trade_history"]
    }
    entries = routes["items"]
    actual = {(row["ticker"], row["isu_cd"]) for row in entries}

    assert len(status["canonical_trade_history"]) == 488
    assert len(expected) == routes["unique_exact_identity_count"] == 399
    assert actual == expected
    assert len(entries) == routes["route_count"] == 399
    assert routes["supplemental_report_count"] == 148

    for row in entries:
        path = ROOT / "web" / row["url"].removeprefix("./")
        report = _json(path)
        assert report["identity"]["ticker"] == row["ticker"]
        assert report["identity"]["isu_cd"] == row["isu_cd"]


def test_open_history_identities_and_historical_routes_are_explicit():
    status = _json(ROOT / "artifacts/strategies/b_select_core_v2/production/20261003/status.json")
    routes = _json(ROOT / "web/data/identity-report-routes.json")
    by_pair = {(row["ticker"], row["isu_cd"]): row for row in routes["items"]}
    opens = [row for row in status["canonical_trade_history"] if row["trade_status"] == "OPEN_AT_REFERENCE"]
    historical = [row for row in routes["items"] if row["report_type"] == "HISTORICAL_ARCHIVE"]
    current_partial = [row for row in routes["items"] if row["report_type"] == "IDENTITY_ONLY_CURRENT"]

    assert len(opens) == status["canonical_current_open_position_count"] == 37
    assert all((row["ticker"], row["isu_cd"]) in by_pair for row in opens)
    assert len(historical) == 16
    assert len(current_partial) == 132
    for route in historical:
        report = _json(ROOT / "web" / route["url"].removeprefix("./"))
        assert report["availability"]["identity_status"] == "HISTORICAL / NOT_CURRENT_COMMON"
        assert report["price_trend"]["latest_close"] is None


def _seven_missing_identity_fixture(tmp_path: Path):
    identities = [
        ("001500", "KR7001500008"),
        ("002460", "KR7002460004"),
        ("034940", "KR7034940007"),
        ("093240", "KR7093240000"),
        ("115180", "KR7115180002"),
        ("134060", "KR7134060003"),
        ("140410", "KR7140410002"),
    ]
    history = []
    for ticker, isu_cd in identities:
        history.append({
            "ticker": ticker,
            "isu_cd": isu_cd,
            "name": f"테스트 {ticker}",
            "market": "KOSPI",
            "trade_sequence": 1,
            "entry_signal_date": "2026-09-30",
            "entry_execution_date": "2026-10-01",
            "entry_open": 1000.0,
            "exit_signal_date": "2026-10-02",
            "exit_execution_date": "2026-10-05",
            "exit_price": 1100.0,
            "trade_status": "REALIZED",
            "return_pct": 10.0,
            "exit_reason": "PATTERN_B_NORMAL_NEXT_OPEN",
        })
    status = {
        "requested_as_of": "2026-10-15",
        "reference_market_date": "2026-10-15",
        "canonical_trade_history_row_count": len(history),
        "canonical_trade_history": history,
        "items": [
            {"ticker": ticker, "isu_cd": isu_cd, "action": "WAIT", "canonical_position": "FLAT"}
            for ticker, isu_cd in identities
        ],
    }
    monitor = {
        "requested_as_of": "2026-10-15",
        "reference_market_date": "2026-10-15",
        "strategies": [{
            "id": "PATTERN_B_SELECT_CORE_V02",
            "items": status["items"],
            "trade_history": history,
        }],
    }
    index = {"items": [
        {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "name": f"테스트 {ticker}",
            "market": "KOSPI",
            "asset_type": "COMMON",
            "report_available": False,
        }
        for ticker, isu_cd in identities
    ]}
    pit = {"intervals": [
        {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "state": "COMMON",
            "effective_from": "2010-01-01",
            "effective_to": "2026-10-15",
        }
        for ticker, isu_cd in identities
    ]}
    stage = tmp_path / "data"
    (stage / "stocks").mkdir(parents=True)
    payload, report_paths = identity_web.build_identity_routes(
        status_data=status,
        index_data=index,
        pit_data=pit,
        monitor_data=monitor,
        stocks_dir=stage / "stocks",
        output_dir=stage / "identity-reports",
        expected_requested_as_of="2026-10-15",
        expected_reference_market_date="2026-10-15",
    )
    (stage / "identity-report-routes.json").write_text(json.dumps(payload), encoding="utf-8")
    return stage, status, payload, report_paths, monitor


def test_phase4d_builds_exact_routes_for_the_seven_missing_20261015_identities(tmp_path: Path):
    stage, status, payload, report_paths, monitor = _seven_missing_identity_fixture(tmp_path)

    result = identity_web.validate_identity_routes(stage, status)

    assert len(payload["items"]) == payload["route_count"] == 7
    assert payload["canonical_trade_count"] == 7
    assert payload["unique_exact_identity_count"] == 7
    assert payload["supplemental_report_count"] == len(report_paths) == 7
    assert {route["report_type"] for route in payload["items"]} == {"IDENTITY_ONLY_CURRENT"}
    assert result["status"] == "PASS"
    assert result["missing_route_count"] == result["identity_mismatch_count"] == 0
    assert monitor["strategies"][0]["items"] == status["items"]
    for route in payload["items"]:
        report = _json(stage / route["url"].removeprefix("./data/"))
        assert report["identity"]["ticker"] == route["ticker"]
        assert report["identity"]["isu_cd"] == route["isu_cd"]
        assert report["decision"]["action"] == "NONE"
        assert report["strategy"]["state"] == "NOT_APPLICABLE"
        assert len(report["strategy"]["history"]) == route["trade_count"]


def test_identity_route_validation_rejects_wrong_exact_identity_and_dangling_target(tmp_path: Path):
    stage, status, payload, _report_paths, _monitor = _seven_missing_identity_fixture(tmp_path)
    first = payload["items"][0]
    report_path = stage / first["url"].removeprefix("./data/")
    report = _json(report_path)
    report["identity"]["isu_cd"] = "KR7999999999"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="target identity mismatch"):
        identity_web.validate_identity_routes(stage, status)

    report["identity"]["isu_cd"] = first["isu_cd"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    report_path.unlink()
    with pytest.raises(ValueError, match="target is missing"):
        identity_web.validate_identity_routes(stage, status)


def test_identity_only_route_fails_closed_for_a_current_b_select_hold(tmp_path: Path):
    stage, status, _payload, _report_paths, monitor = _seven_missing_identity_fixture(tmp_path)
    monitor["strategies"][0]["items"][0]["action"] = "HOLD"

    with pytest.raises(ValueError, match="current B Select HOLD cannot use identity-only report"):
        identity_web.build_identity_routes(
            status_data=status,
            index_data={"items": []},
            pit_data={"intervals": []},
            monitor_data=monitor,
            stocks_dir=stage / "stocks",
            output_dir=stage / "identity-reports-next",
            expected_requested_as_of="2026-10-15",
            expected_reference_market_date="2026-10-15",
        )
