from pathlib import Path

from trend_scanner.research.fear_index_v01 import run_research


if __name__ == "__main__":
    summary = run_research(
        Path("artifacts/fear_index/research_v01/source/official_exports"),
        Path("data/market/index/v01/market_index.parquet"),
        Path("artifacts/fear_index/research_v01"),
    )
    print(summary)
