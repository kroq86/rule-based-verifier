"""Workspace boundary: all file operations stay under RULE_BASED_WORKSPACE_ROOT."""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    raw = os.environ.get("RULE_BASED_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_under_root(relative_path: str, root: Path | None = None) -> Path:
    """
    Resolve a path that must live under the workspace root.
    Rejects absolute paths and any resolved path that escapes the root.
    """
    root = (root or workspace_root()).resolve()
    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("absolute paths are not allowed; use a path relative to the workspace root")
    final = (root / p).resolve()
    try:
        final.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes workspace root") from exc
    return final
