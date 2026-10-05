import json
from pathlib import Path


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
