from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_etf_official_universe_refinement_v03.py"
SPEC = importlib.util.spec_from_file_location("etf_universe_v03", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v03 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v03)


class ETFOfficialUniverseRefinementV03Tests(unittest.TestCase):
    def test_product_management_type_uses_official_krx_replica_label(self):
        self.assertEqual(v03.product_management_type({"ETF_REPLICA_METHD_TP_CD": "실물(액티브)"}), "ACTIVE")
        self.assertEqual(v03.product_management_type({"ETF_REPLICA_METHD_TP_CD": "합성(패시브)"}), "PASSIVE")
        self.assertEqual(v03.product_management_type({"ETF_REPLICA_METHD_TP_CD": "unknown"}), "UNKNOWN")

    def test_passive_selector_applies_one_percent_aum_tiebreak(self):
        candidates = [
            {"major_category": "SECTOR_INDEX", "representative_group": "HEALTHCARE", "ticker": "000001", "avg_trading_value_40d": "100000", "AUM_if_available": "200", "listing_date": "2020-01-01"},
            {"major_category": "SECTOR_INDEX", "representative_group": "HEALTHCARE", "ticker": "000002", "avg_trading_value_40d": "99500", "AUM_if_available": "300", "listing_date": "2021-01-01"},
        ]
        classified = {
            row["ticker"]: {
                "major_category": "SECTOR_INDEX",
                "representative_group": "HEALTHCARE",
                "ETF_REPLICA_METHD_TP_CD": "실물(패시브)",
                "product_structure": "PLAIN_LONG",
                "hard_filter_pass": "True",
                "failed_filter": "",
            }
            for row in candidates
        }
        winner, reason = v03.select_passive_candidate(candidates, classified)  # type: ignore[misc]
        self.assertEqual(winner["ticker"], "000002")
        self.assertIn("within 1%", reason)

    def test_commodity_spot_precedes_higher_turnover_future(self):
        candidates = [
            {"major_category": "COMMODITY_RESOURCE", "representative_group": "GOLD", "ticker": "000001", "avg_trading_value_40d": "900000", "AUM_if_available": "500", "listing_date": "2020-01-01"},
            {"major_category": "COMMODITY_RESOURCE", "representative_group": "GOLD", "ticker": "000002", "avg_trading_value_40d": "500000", "AUM_if_available": "100", "listing_date": "2020-01-01"},
        ]
        classified = {
            "000001": {"major_category": "COMMODITY_RESOURCE", "representative_group": "GOLD", "ETF_REPLICA_METHD_TP_CD": "실물(패시브)", "product_structure": "PLAIN_LONG_FUTURES", "hard_filter_pass": "True", "failed_filter": ""},
            "000002": {"major_category": "COMMODITY_RESOURCE", "representative_group": "GOLD", "ETF_REPLICA_METHD_TP_CD": "실물(패시브)", "product_structure": "PLAIN_LONG_SPOT", "hard_filter_pass": "True", "failed_filter": ""},
        }
        winner, reason = v03.select_passive_candidate(candidates, classified)  # type: ignore[misc]
        self.assertEqual(winner["ticker"], "000002")
        self.assertIn("spot product preferred", reason)

    def test_end_to_end_uses_v02_authority_and_builds_37_passive_representatives(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "v03"
            result = v03.build_v03(ROOT / "artifacts/research/etf_official_universe_refinement_v02", output_dir)
            self.assertTrue(result["passed"])
            self.assertEqual(result["verdict"], "ETF_OFFICIAL_UNIVERSE_REFINEMENT_V03_COMPLETE")
            self.assertEqual(result["v02_selected_count"], 39)
            self.assertEqual(result["v03_selected_count"], 37)
            self.assertEqual(result["active_representatives_removed_count"], 1)
            self.assertEqual(result["active_representatives_replaced_count"], 1)
            self.assertEqual(result["parent_sector_groups_removed"], ["FINANCIALS", "INFORMATION_TECHNOLOGY"])
            self.assertEqual(result["market_data_refetch_count"], 0)
            self.assertEqual(result["40D_market_metric_recomputation_count"], 0)
            self.assertEqual(result["v02_market_metric_source_mismatch_count"], 0)
            with (output_dir / "official_representative_etf_universe_v03.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            by_group = {(row["major_category"], row["representative_group"]): row for row in rows}
            healthcare = by_group[("SECTOR_INDEX", "HEALTHCARE")]
            self.assertEqual(healthcare["ticker"], "244580")
            self.assertEqual(healthcare["product_management_type"], "PASSIVE")
            self.assertNotIn(("SECTOR_INDEX", "FINANCIALS"), by_group)
            self.assertNotIn(("SECTOR_INDEX", "INFORMATION_TECHNOLOGY"), by_group)
            self.assertIn(("SECTOR_INDEX", "BANK"), by_group)
            self.assertIn(("SECTOR_INDEX", "SEMICONDUCTOR"), by_group)
            self.assertTrue(all(row["product_management_type"] == "PASSIVE" for row in rows))
            with (output_dir / "validation.json").open(encoding="utf-8") as handle:
                validation = json.load(handle)
            self.assertTrue(all(validation["checks"].values()))
            for filename in (
                "official_representative_etf_universe_v03.csv",
                "changes_from_v02.csv",
                "sector_overlap_audit.csv",
                "active_exclusion_audit.csv",
                "validation.json",
                "summary.md",
            ):
                self.assertTrue((output_dir / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
