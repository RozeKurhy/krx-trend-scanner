from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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

    tickers = refresh.load_common_adjusted_tickers_from_pit(pit_path)

    assert "999999" in tickers
    assert "005930" in tickers
    assert "069500" not in tickers


def test_population_audit_binds_supplied_live_pit_and_calendar(tmp_path, monkeypatch) -> None:
    adjusted_dir = tmp_path / "adjusted"
    pit_path = tmp_path / "merged_pit.json"
    calendar_path = tmp_path / "merged_calendar.json"
    seen: dict[str, object] = {}

    class _Audit:
        unexplained_gap_count = 0

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

    assert audit() == {"candidate_boundary": "2026-09-11", "unexplained_gap_count": 0}
    assert seen["adjusted_store_dir"] == adjusted_dir
    assert seen["candidate_boundary"] == "2026-09-11"
    assert seen["pit_path"] == pit_path
    assert seen["historical_calendar_path"] == calendar_path
