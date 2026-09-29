"""Secret-safe loading for the existing KRX credential sources.

Values are read only into the current process environment or returned to an
in-memory caller. This module never prints, logs, or serializes credential data.
"""

from __future__ import annotations

import os
from pathlib import Path


def credential_files(repo_root: Path) -> tuple[Path, Path]:
    """Return the credential sources used by the existing Phase 1 paths."""

    root = Path(repo_root)
    return root / ".env", root.parent / "env.md"


def read_env_value(path: Path, name: str) -> str:
    """Read one KEY=value entry without exposing it to stdout or logs."""

    path = Path(path)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def load_operator_credentials(repo_root: Path) -> None:
    """Load PyKRX login fields into this process, preserving env precedence."""

    paths = credential_files(repo_root)
    for name in ("KRX_ID", "KRX_PW"):
        if os.getenv(name, "").strip():
            continue
        for path in paths:
            value = read_env_value(path, name).strip()
            if value:
                os.environ[name] = value
                break


def load_open_api_auth_key(repo_root: Path) -> str:
    """Resolve the Open API key using the existing Phase 1 source order."""

    value = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
    if value:
        return value
    for path in credential_files(repo_root):
        value = read_env_value(path, "KRX_OPEN_API_AUTH_KEY").strip()
        if value:
            return value
    return ""


def load_phase3_krx_credentials(repo_root: Path) -> None:
    """Load all existing KRX credentials into process memory for Phase 3."""

    load_operator_credentials(repo_root)
    if not os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip():
        value = load_open_api_auth_key(repo_root)
        if value:
            os.environ["KRX_OPEN_API_AUTH_KEY"] = value
