#!/usr/bin/env python3
"""Archive v0.2 and regenerate the canonical 2026-08-14 Stock Report v0.3 set."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from trend_scanner.reporting.stock_report import generate_stock_report


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260814"
AS_OF = "2026-08-14"
CANONICAL = ROOT / "artifacts/reporting/stock_reports" / DATE
ARCHIVE = ROOT / "artifacts/reporting/stock_reports/archive/v0.2" / DATE


def _json_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def _md_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.md"))


def _ticker_set(directory: Path) -> set[str]:
    return {path.stem for path in _json_files(directory)}


def _verify_v02_source() -> list[str]:
    source_dir = CANONICAL
    archived_files = _json_files(ARCHIVE)
    if len(archived_files) == 54 and all(
        json.loads(path.read_text(encoding="utf-8")).get("report_version") == "0.2"
        for path in archived_files
    ):
        source_dir = ARCHIVE
    files = _json_files(source_dir)
    md_files = _md_files(source_dir)
    if len(files) != 54 or len(md_files) != 54:
        raise RuntimeError(f"expected 54 v0.2 JSON/Markdown artifacts in {source_dir}, got {len(files)}/{len(md_files)}")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("report_version") != "0.2":
            raise RuntimeError(f"source is not v0.2: {path.name}")
    return sorted(path.stem for path in files)


def _archive_v02(tickers: list[str]) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    if _json_files(ARCHIVE) or _md_files(ARCHIVE):
        existing = sorted(path.stem for path in _json_files(ARCHIVE))
        if existing != tickers or len(_md_files(ARCHIVE)) != 54:
            raise RuntimeError("existing archive/v0.2 is not the expected immutable 54-report set")
        for path in _json_files(ARCHIVE):
            if json.loads(path.read_text(encoding="utf-8")).get("report_version") != "0.2":
                raise RuntimeError(f"existing archive contains non-v0.2 artifact: {path.name}")
        return
    for path in _json_files(CANONICAL) + _md_files(CANONICAL):
        shutil.copy2(path, ARCHIVE / path.name)


def _validate_temp(temp_dir: Path, tickers: list[str]) -> None:
    json_files = _json_files(temp_dir)
    md_files = _md_files(temp_dir)
    if sorted(path.stem for path in json_files) != tickers or len(md_files) != 54:
        raise RuntimeError("generated v0.3 ticker set or artifact count mismatch")
    for path in json_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("report_version") != "0.3":
            raise RuntimeError(f"generated artifact is not v0.3: {path.name}")
        if "relative_strength" not in data:
            raise RuntimeError(f"generated artifact missing relative_strength: {path.name}")


def main() -> None:
    tickers = _verify_v02_source()
    _archive_v02(tickers)
    with tempfile.TemporaryDirectory(prefix="stock-report-v03-") as temp_name:
        temp_dir = Path(temp_name)
        for index, stem in enumerate(tickers, start=1):
            ticker = stem[:6]
            generate_stock_report(
                ticker=ticker,
                as_of=AS_OF,
                repo_root=ROOT,
                save_artifacts=True,
                output_dir=temp_dir,
            )
            print(f"[{index:02d}/54] {ticker}", flush=True)
        _validate_temp(temp_dir, tickers)
        for path in _json_files(temp_dir) + _md_files(temp_dir):
            shutil.copy2(path, CANONICAL / path.name)
    print(f"regenerated {len(tickers)} Stock Report v0.3 artifacts in {CANONICAL}")


if __name__ == "__main__":
    main()
