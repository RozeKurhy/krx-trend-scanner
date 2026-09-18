"""Focused regression for the Daily Update live-entrypoint scope guard FIX08."""

from __future__ import annotations

import json
from pathlib import Path


def _args(module, tmp_path: Path, *, execute_live: bool):
    authority_dir = tmp_path / "authority"
    authority_dir.mkdir(parents=True)
    (authority_dir / "merged_pit_intervals.json").write_text(
        json.dumps({"intervals": []}), encoding="utf-8"
    )
    argv = [
        "--target-as-of",
        "2026-09-16",
        "--authority-dir",
        str(authority_dir),
        "--raw-root",
        str(tmp_path / "raw"),
        "--adjusted-root",
        str(tmp_path / "adjusted"),
        "--index-root",
        str(tmp_path / "index"),
        "--quota-db",
        str(tmp_path / "quota.sqlite3"),
    ]
    if execute_live:
        argv.append("--execute-live")
    return module.build_parser().parse_args(argv)


def test_build_foundation_live_and_dry_run_use_adjusted_updater_without_network(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    import run_daily_update_v01 as module

    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

    class FakeQuota:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class FakeClient:
        instances = []

        def __init__(self, *args, **kwargs):
            self.calls = []
            self.args = args
            self.kwargs = kwargs
            self.quota = kwargs.get("quota")
            self.instances.append(self)

        def fetch(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("object graph construction must not call the KRX API")

    monkeypatch.setattr(module, "load_auth_key", lambda: "test-key")
    monkeypatch.setattr(module, "LocalKrxOpenApiQuota", FakeQuota)
    monkeypatch.setattr(module, "KrxOpenApiClient", FakeClient)

    live = module.build_foundation(_args(module, tmp_path / "live", execute_live=True), execute_live=True)
    dry_run = module.build_foundation(_args(module, tmp_path / "dry", execute_live=False), execute_live=False)

    assert isinstance(live.common_adjusted_updater, RollingAdjustedPriceUpdater)
    assert isinstance(dry_run.common_adjusted_updater, RollingAdjustedPriceUpdater)
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].calls == []
