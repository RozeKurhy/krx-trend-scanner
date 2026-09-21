from pathlib import Path
import argparse

from trend_scanner.research.fear_index_v01 import run_research


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Fear Index research projection.")
    parser.add_argument("--target-as-of", required=True, help="Required target as-of date (YYYY-MM-DD)")
    args = parser.parse_args()
    summary = run_research(
        Path("artifacts/fear_index/research_v01/source/official_exports"),
        Path("data/market/index/v01/market_index.parquet"),
        Path("artifacts/fear_index/research_v01"),
        target_as_of=args.target_as_of,
    )
    print(summary)
