"""Best-effort command detection for tests and lint."""

from __future__ import annotations

import json
import os
import shutil
import shlex
import sys
from pathlib import Path


def _cmd_from_env(var: str) -> list[str] | None:
    raw = os.environ.get(var, "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed
        except json.JSONDecodeError:
            pass
    return shlex.split(raw)


def test_command(root: Path) -> tuple[list[str] | None, str]:
    override = _cmd_from_env("RULE_BASED_TEST_CMD")
    if override:
        return override, "env RULE_BASED_TEST_CMD"
    exe = sys.executable or "python3"
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").is_dir():
        return [exe, "-m", "pytest"], "detected pytest"
    if (root / "package.json").exists() and shutil.which("npm"):
        return ["npm", "test"], "detected npm test"
    return None, "no test command detected"


def lint_command(root: Path) -> tuple[list[str] | None, str]:
    override = _cmd_from_env("RULE_BASED_LINT_CMD")
    if override:
        return override, "env RULE_BASED_LINT_CMD"
    if shutil.which("ruff"):
        return ["ruff", "check", "."], "detected ruff"
    if (root / "package.json").exists() and shutil.which("npm"):
        return ["npm", "run", "lint"], "detected npm run lint"
    return None, "no lint command detected"
