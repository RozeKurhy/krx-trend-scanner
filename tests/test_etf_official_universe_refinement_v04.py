from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_etf_official_universe_refinement_v04.py"
SPEC = importlib.util.spec_from_file_location("etf_universe_v04", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v04 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v04)


class ETFOfficialUniverseRefinementV04Tests(unittest.TestCase):
    def test_broad_healthcare_uses_existing_product_and_index_authority(self):
        self.assertTrue(v04.is_broad_healthcare_candidate(
            {"ticker": "143860", "ISU_ABBRV": "TIGER 헬스케어"},
            {"ETF_OBJ_IDX_NM": "KRX 헬스케어"},
        ))
        self.assertFalse(v04.is_broad_healthcare_candidate(
            {"ticker": "244580", "ISU_ABBRV": "KODEX 바이오"},
            {"ETF_OBJ_IDX_NM": "FnGuide 바이오 지수"},
        ))

    def test_end_to_end_v04_changes_only_healthcare_and_group_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "v04"
            result = v04.build_v04(output_dir=output)
            self.assertTrue(result["passed"])
            self.assertEqual(result["verdict"], "ETF_OFFICIAL_UNIVERSE_REFINEMENT_V04_COMPLETE")
            self.assertEqual(result["v03_selected_count"], 37)
            self.assertEqual(result["v04_selected_count"], 37)
            self.assertEqual(result["healthcare_representative"]["ticker"], "143860")
            self.assertEqual(result["developed_markets_ticker"], "251350")
            self.assertTrue(result["non_healthcare_tickers_unchanged"])
            self.assertEqual(result["market_refetch_count"], 0)
            self.assertEqual(result["40D_metric_recomputation_count"], 0)
            self.assertEqual(result["market_metric_source_mismatch_count"], 0)

            with (output / "official_representative_etf_universe_v04.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            by_group = {(row["major_category"], row["representative_group"]): row for row in rows}
            self.assertEqual(by_group[("SECTOR_INDEX", "HEALTHCARE")]["ticker"], "143860")
            self.assertEqual(by_group[("MARKET_INDEX", "DEVELOPED_MARKETS")]["ticker"], "251350")
            self.assertNotIn(("MARKET_INDEX", "GLOBAL_BROAD"), by_group)
            self.assertTrue(all(row["product_management_type"] == "PASSIVE" for row in rows))

            v03_path = ROOT / "artifacts/research/etf_official_universe_refinement_v03/official_representative_etf_universe_v03.csv"
            with v03_path.open(encoding="utf-8-sig", newline="") as handle:
                old_rows = list(csv.DictReader(handle))
            old_nonhealth = {row["ticker"]: row for row in old_rows if row["representative_group"] != "HEALTHCARE"}
            new_by_ticker = {row["ticker"]: row for row in rows}
            for ticker, old in old_nonhealth.items():
                new = new_by_ticker[ticker]
                self.assertEqual(new["representative_group"], "DEVELOPED_MARKETS" if ticker == "251350" else old["representative_group"])
                for field in ("ETF_name", "listing_date", "close", "avg_volume_40d", "avg_trading_value_40d"):
                    self.assertEqual(new[field], old[field], (ticker, field))

            with (output / "healthcare_candidate_audit.csv").open(encoding="utf-8-sig", newline="") as handle:
                audit = list(csv.DictReader(handle))
            self.assertEqual(len(audit), 10)
            chosen = [row for row in audit if row["selected"] == "true"]
            self.assertEqual([row["ticker"] for row in chosen], ["143860"])
            active = next(row for row in audit if row["ticker"] == "463050")
            self.assertEqual(active["broad_healthcare_eligible"], "true")
            self.assertEqual(active["passive"], "false")

            with (output / "validation.json").open(encoding="utf-8") as handle:
                validation = json.load(handle)
            self.assertTrue(all(validation["checks"].values()))
            with (output / "changes_from_v03.csv").open(encoding="utf-8-sig", newline="") as handle:
                changes = list(csv.DictReader(handle))
            self.assertEqual({row["change_type"] for row in changes}, {"HEALTHCARE_RESELECTED", "GROUP_RENAMED"})
            for filename in (
                "official_representative_etf_universe_v04.csv",
                "healthcare_candidate_audit.csv",
                "changes_from_v03.csv",
                "validation.json",
                "summary.md",
            ):
                self.assertTrue((output / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
