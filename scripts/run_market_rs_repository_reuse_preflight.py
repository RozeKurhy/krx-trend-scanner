"""Same-process heavy-resource preflight for the Market RS consumer."""

from __future__ import annotations

import json
from pathlib import Path

from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.relative_strength.repository_adapter import resolve_market_rs_repository_input
from trend_scanner.scanner.full_universe_scanner import _default_market_rs_repository


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_rs_parity/v01_fix01/repository_reuse_preflight.json"


def main() -> int:
    benchmark = IndexStore(ROOT / "data/market/index/v01").load_family(
        MARKET_INDEX_FAMILY,
        end="2026-08-14",
        index_codes=("1001", "2001"),
    )
    repository_one = _default_market_rs_repository(ROOT)
    first = resolve_market_rs_repository_input(
        repository_one,
        ticker="000250",
        as_of="2026-08-14",
        market_code="2001",
        market_index_df=benchmark,
    )
    repository_two = _default_market_rs_repository(ROOT)
    second = resolve_market_rs_repository_input(
        repository_two,
        ticker="000440",
        as_of="2026-08-14",
        market_code="2001",
        market_index_df=benchmark,
    )
    stats_after_first = repository_one.raw_reader_stats
    stats_after_second = repository_two.raw_reader_stats
    result = {
        "status": "PASS" if repository_one is repository_two and stats_after_second.get("full_store_scans", 0) == stats_after_first.get("full_store_scans", 0) == 1 else "FAIL",
        "repository_instance_count": 1 if repository_one is repository_two else 2,
        "same_instance": repository_one is repository_two,
        "first_call_present": first.stock_df is not None and not first.stock_df.empty,
        "second_call_present": second.stock_df is not None and not second.stock_df.empty,
        "full_store_build_count": stats_after_first.get("full_store_scans", 0),
        "second_call_additional_full_store_builds": stats_after_second.get("full_store_scans", 0) - stats_after_first.get("full_store_scans", 0),
        "memory_after_first_build_bytes": stats_after_first.get("index_memory_bytes", 0),
        "memory_after_second_call_bytes": stats_after_second.get("index_memory_bytes", 0),
        "raw_reader_stats": stats_after_second,
        "network_requests": 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
