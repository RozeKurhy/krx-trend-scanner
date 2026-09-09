#!/usr/bin/env python3
"""Project the approved Fear Index research artifact into public web JSON.

The research artifact is the authority for both ``fear_score`` and the final
stabilized ``regime``.  This script deliberately performs projection only: it
does not recalculate features, scores, thresholds, or hysteresis.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import math
from pathlib import Path
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = ROOT / "artifacts/fear_index/research_v01/final_daily_regimes.csv"
SUMMARY_PATH = ROOT / "artifacts/fear_index/research_v01/research_summary.json"
FORMULA_PATH = ROOT / "artifacts/fear_index/research_v01/final_formula.md"
DEFAULT_OUTPUT_PATH = ROOT / "web/data/fear-index.json"

REGIMES = (
    {"code": "OVERHEATED", "label": "과열·흥분"},
    {"code": "NORMAL", "label": "정상·안정"},
    {"code": "ANXIOUS", "label": "불안"},
    {"code": "PANIC", "label": "공포·패닉"},
    {"code": "APATHY", "label": "침체·무관심"},
)
VALID_REGIMES = frozenset(regime["code"] for regime in REGIMES)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON authority must be an object: {path}")
    return value


def _finite_number(value: Any) -> bool:
    if value is None or value is True or value is False or value == "":
        return False
    if isinstance(value, str) and not value.strip():
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _number(value: Any) -> float:
    if not _finite_number(value):
        raise ValueError(f"expected finite numeric value, got {value!r}")
    return float(value)


def _date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected ISO date, got {value!r}")
    normalized = value[:10]
    date.fromisoformat(normalized)
    return normalized


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(encoded)
        temporary.flush()
    temporary_path.replace(path)


def _project_item(row: dict[str, str]) -> dict[str, Any] | None:
    regime = str(row.get("regime") or "").strip().upper()
    if regime not in VALID_REGIMES:
        return None
    if not all(
        _finite_number(row.get(field))
        for field in ("kospi_close", "v_kospi200_close", "trading_value", "fear_score")
    ):
        return None
    return {
        "date": _date(row.get("date")),
        "kospi_close": _number(row.get("kospi_close")),
        "v_kospi200_close": _number(row.get("v_kospi200_close")),
        "trading_value": _number(row.get("trading_value")),
        "fear_score": _number(row.get("fear_score")),
        "regime": regime,
    }


def build_web_payload() -> dict[str, Any]:
    """Build the public payload from the approved local artifacts."""
    if not SOURCE_CSV.exists():
        raise FileNotFoundError(f"Fear Index CSV authority missing: {SOURCE_CSV}")
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"Fear Index summary missing: {SUMMARY_PATH}")
    if not FORMULA_PATH.exists() or not FORMULA_PATH.read_text(encoding="utf-8").strip():
        raise FileNotFoundError(f"Fear Index formula artifact missing or empty: {FORMULA_PATH}")

    summary = _read_json(SUMMARY_PATH)
    projected: list[dict[str, Any]] = []
    with SOURCE_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            item = _project_item(row)
            if item is not None:
                projected.append(item)

    projected.sort(key=lambda item: item["date"])
    dates = [item["date"] for item in projected]
    if not projected:
        raise ValueError("Fear Index authority has no valid web rows")
    if len(dates) != len(set(dates)):
        raise ValueError("Fear Index authority contains duplicate valid dates")

    current = projected[-1]
    return {
        "schema_version": "FEAR_INDEX_WEB_V01",
        "as_of": current["date"],
        "model": {
            "study": str(summary.get("study") or ""),
            "candidate": str(summary.get("final_candidate") or ""),
            "hysteresis": bool(summary.get("hysteresis_selected")),
        },
        "available_from": projected[0]["date"],
        "current": dict(current),
        "regimes": list(REGIMES),
        "items": projected,
    }


def export_fear_index(output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    payload = build_web_payload()
    _write_json(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    payload = export_fear_index(args.output)
    print(
        f"exported {len(payload['items'])} rows "
        f"({payload['available_from']}..{payload['as_of']}) to {args.output}"
    )


if __name__ == "__main__":
    main()
