#!/usr/bin/env python3
"""Fetch only the selected XBRL cache misses approved by the V02 audit."""

from __future__ import annotations

import json
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hydrate_fundamentals_v1_production import (  # noqa: E402
    QuotaBoundOpenDartClient,
    _load_opendart_key,
    _write_json_checked,
)
from trend_scanner.fundamentals.models import RegisteredFiling  # noqa: E402
from trend_scanner.fundamentals.opendart_client import OpenDartError  # noqa: E402
from trend_scanner.fundamentals.opendart_contract import REPORT_TYPE_BY_CODE  # noqa: E402
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository  # noqa: E402

AUDIT_DIR = ROOT / "artifacts/fundamentals/validation/fundamentals_v1_full_authority_audit_v02"
NEEDS_PATH = AUDIT_DIR / "needs_live_fetch.json"
MANIFEST_PATH = AUDIT_DIR / "source_fetch_manifest.json"
OFFICIAL_USAGE_BEFORE = 18_458
SAFETY_DAILY_CAP = 39_000
MAX_ADDITIONAL = SAFETY_DAILY_CAP - OFFICIAL_USAGE_BEFORE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cached(item: dict[str, Any]) -> bool:
    stem = f"{item['rcept_no']}_{item['reprt_code']}"
    cache_dir = ROOT / "data/cache/opendart/xbrl"
    return (cache_dir / f"{stem}.zip").is_file() and (cache_dir / f"{stem}.json").is_file()


def _filing(item: dict[str, Any]) -> RegisteredFiling:
    code = str(item["reprt_code"])
    return RegisteredFiling(
        ticker=str(item["ticker"]), corp_code=str(item["corp_code"]), corp_name="",
        bsns_year=str(item["year"]), reprt_code=code,
        report_type=REPORT_TYPE_BY_CODE[code], report_nm=str(item["report_nm"]),
        rcept_no=str(item["rcept_no"]), rcept_dt=str(item["rcept_dt"]),
        filing_chain_key=str(item.get("filing_chain_key") or ""),
        correction_flag=bool(item.get("correction_flag", False)),
        source_retrieved_at=_now(), fs_div=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prior-additional-requests", type=int, default=0,
        help="Already-counted attempts from earlier invocations in today's quota ledger",
    )
    args = parser.parse_args()
    payload = json.loads(NEEDS_PATH.read_text(encoding="utf-8"))
    needs = list(payload.get("needs", []))
    expected = len(needs)
    if expected > MAX_ADDITIONAL:
        raise RuntimeError("TARGETED_FETCH_EXCEEDS_DAILY_SAFETY_CAP")
    secret = _load_opendart_key(Path("/Users/june/Documents/projects/env.md"))
    client = QuotaBoundOpenDartClient(
        api_key=secret,
        prior_additional_requests=args.prior_additional_requests,
        max_additional_requests=MAX_ADDITIONAL,
        official_usage_before=OFFICIAL_USAGE_BEFORE,
        safety_daily_cap=SAFETY_DAILY_CAP,
    )
    repository = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
    started = time.monotonic()
    fetched = 0
    already_present = 0
    failures: list[dict[str, Any]] = []
    stop_reason = "TARGET_SET_EXHAUSTED"
    for item in needs:
        if _cached(item):
            already_present += 1
            continue
        try:
            repository.fetch(_filing(item), force_refresh=False)
            fetched += 1
        except OpenDartError as exc:
            failures.append({
                "ticker": item.get("ticker"), "rcept_no": item.get("rcept_no"),
                "reprt_code": item.get("reprt_code"), "status": exc.status,
                "classification": exc.classification, "error_type": type(exc).__name__,
            })
            if exc.status in {"020", "021"} or exc.classification == "RATE_LIMIT":
                stop_reason = "OPENDART_RATE_LIMIT"
                break
            # A per-filing request/data error is recorded and the next exact
            # selected miss is attempted.  No alternate endpoint or filing is
            # substituted.
            continue
        except Exception as exc:  # pragma: no cover - defensive source boundary
            failures.append({
                "ticker": item.get("ticker"), "rcept_no": item.get("rcept_no"),
                "reprt_code": item.get("reprt_code"), "error_type": type(exc).__name__,
            })
            continue
        if (fetched + already_present) % 250 == 0:
            print(json.dumps({
                "completed": fetched + already_present, "expected": expected,
                "actual_requests": len(client.audit),
                "estimated_daily_total": client.estimated_daily_total,
            }, ensure_ascii=False), flush=True)
    remaining = sum(not _cached(item) for item in needs)
    if not failures and remaining == 0:
        stop_reason = "TARGET_SET_EXHAUSTED"
    manifest = {
        "work_id": "FUNDAMENTALS_V1_TARGETED_SELECTED_XBRL_FETCH_V02",
        "requested_as_of": payload.get("requested_as_of"),
        "scope": "exact_selected_filing_cache_misses_only",
        "expected_targeted_requests": expected,
        "actual_http_requests": len(client.audit),
        "fetched": fetched,
        "already_present_at_start": already_present,
        "remaining_cache_misses": remaining,
        "failures": failures,
        "stop_reason": stop_reason,
        "quota": {
            "official_usage_before": OFFICIAL_USAGE_BEFORE,
            "max_additional_requests": MAX_ADDITIONAL,
            "safety_daily_cap": SAFETY_DAILY_CAP,
            "estimated_daily_total": client.estimated_daily_total,
            "counter_consistent": client.http_request_count == len(client.audit),
        },
        "network": {"OpenDART_live": "USED", "scope_verified": True},
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "completed_at": _now(),
    }
    _write_json_checked(MANIFEST_PATH, manifest)
    print(json.dumps({
        "status": "PASS" if not failures and remaining == 0 else "CHANGES_REQUESTED",
        "expected": expected, "actual_requests": len(client.audit),
        "remaining": remaining, "estimated_daily_total": client.estimated_daily_total,
    }, ensure_ascii=False))
    return 0 if not failures and remaining == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
