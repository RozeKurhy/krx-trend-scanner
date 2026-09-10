from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_data_accuracy_v05"


def _csv(name: str) -> list[dict[str, str]]:
    with (OUTPUT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v05_regression_and_blind_artifacts_have_complete_240_cell_contract():
    regression = _csv("regression_10_tickers.csv")
    blind = _csv("blind_random_10_tickers.csv")
    assert len(regression) == 240
    assert len(blind) == 240
    assert Counter(row["comparison_status"] for row in regression) == Counter({"CONFIRMED_MATCH": 240})
    assert all(row["our_final"] and row["official_dart_value"] for row in regression)
    assert all(row["result"] == "MATCH" for row in regression)

    summary = json.loads((OUTPUT / "blind_random_10_summary.json").read_text(encoding="utf-8"))
    assert summary["seed_label"] == "20260910_02"
    assert len(summary["selected_tickers"]) == 10
    assert summary["cell_count"] == summary["expected_cell_count"] == 240
    assert summary["missing_value_count"] == summary["wrong_sign_count"] == summary["material_mismatch_count"] == 0


def test_v05_13_ticker_recheck_records_recovered_seed_cells_and_local_impact_scan():
    baseline = _csv("baseline_13_ticker_recheck.csv")
    assert len(baseline) == 312
    recovered = [
        row for row in baseline
        if row["change_status"] == "RECOVERED"
    ]
    assert len(recovered) == 11
    assert all(row["result"] == "MATCH" for row in recovered)
    pearl_abyss = next(row for row in baseline if (
        row["ticker"], row["period"], row["metric"]
    ) == ("263750", "2023FY", "revenue"))
    assert pearl_abyss["our_final"] == "333484523009"
    assert pearl_abyss["official_method"] == "DIRECT_FULL_YEAR"

    impact = _csv("full_local_impact_scan.csv")
    assert impact
    assert all(row["production_value_policy"] == "DIRECT_STANDALONE_AUTHORITY" for row in impact)
    summary = json.loads((OUTPUT / "root_cause_summary.json").read_text(encoding="utf-8"))
    assert summary["full_local_impact_scan"]["total_parity_mismatch_rows"] == len(impact)
    assert summary["representative_regression"]["material_mismatch_count"] == 0
    assert summary["representative_regression"]["wrong_sign_count"] == 0
    assert summary["missing_seed_recovery"]["network_calls"] == 0


def test_v05_official_evidence_is_network_free_and_reports_required_sources():
    evidence = (OUTPUT / "official_evidence.md").read_text(encoding="utf-8")
    assert "OpenDART/XBRL local cache" in evidence
    assert "Samsung Biologics" in evidence
    assert "Pearl Abyss" in evidence
    assert "20260910_02" in evidence
