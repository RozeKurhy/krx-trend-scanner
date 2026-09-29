from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from trend_scanner.data.krx_credentials import (
    load_open_api_auth_key,
    load_operator_credentials,
    load_phase3_krx_credentials,
)


def test_phase3_loader_reuses_env_md_source_without_emitting_credentials(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo_root = tmp_path / "project"
    repo_root.mkdir()
    (tmp_path / "env.md").write_text(
        "KRX_ID=test-user\nKRX_PW=test-password\nKRX_OPEN_API_AUTH_KEY=test-auth-key\n",
        encoding="utf-8",
    )
    for name in ("KRX_ID", "KRX_PW", "KRX_OPEN_API_AUTH_KEY"):
        monkeypatch.delenv(name, raising=False)

    load_phase3_krx_credentials(repo_root)

    assert os.environ["KRX_ID"] == "test-user"
    assert os.environ["KRX_PW"] == "test-password"
    assert os.environ["KRX_OPEN_API_AUTH_KEY"] == "test-auth-key"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_phase1_helpers_share_env_precedence_and_preserve_process_values(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "project"
    repo_root.mkdir()
    (repo_root / ".env").write_text(
        "KRX_ID=file-user\nKRX_PW=file-password\nKRX_OPEN_API_AUTH_KEY=file-key\n",
        encoding="utf-8",
    )
    (tmp_path / "env.md").write_text(
        "KRX_ID=parent-user\nKRX_PW=parent-password\nKRX_OPEN_API_AUTH_KEY=parent-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KRX_ID", "process-user")
    monkeypatch.delenv("KRX_PW", raising=False)
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "process-key")

    load_operator_credentials(repo_root)

    assert os.environ["KRX_ID"] == "process-user"
    assert os.environ["KRX_PW"] == "file-password"
    assert load_open_api_auth_key(repo_root) == "process-key"


def test_phase3_cli_suppresses_provider_console_output(capsys, monkeypatch) -> None:
    runner_path = Path(__file__).resolve().parents[1] / "scripts/run_daily_update_phase3_v01.py"
    spec = importlib.util.spec_from_file_location("phase3_cli_secret_test", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    class NoisyCoordinator:
        def execute(self, target: str):
            print("dummy-login-value")
            print("dummy-auth-value", file=sys.stderr)
            return SimpleNamespace(
                overall_status="PASS",
                to_dict=lambda: {"overall_status": "PASS", "target_as_of": target},
            )

    monkeypatch.setattr(runner, "load_phase3_krx_credentials", lambda _root: None)
    monkeypatch.setattr(runner, "build_official_phase3_coordinator", lambda **_kwargs: NoisyCoordinator())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(runner_path),
            "--target-as-of",
            "2026-09-25",
            "--fundamentals-run-date",
            "2026-09-29",
            "--execute-live",
        ],
    )

    assert runner.main() == 0
    captured = capsys.readouterr()
    assert "dummy-login-value" not in captured.out + captured.err
    assert "dummy-auth-value" not in captured.out + captured.err
    assert '"overall_status": "PASS"' in captured.out
