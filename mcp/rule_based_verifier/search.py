"""Code search: prefer ripgrep, fall back to Python scan."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .paths import workspace_root
from .runner import ProcResult, run_command, which_rg


def search_with_rg(
    pattern: str,
    *,
    glob_pat: str,
    max_results: int,
    root: Path,
) -> ProcResult:
    rg = which_rg()
    if not rg:
        raise RuntimeError("ripgrep not found")
    timeout = float(os.environ.get("RULE_BASED_SEARCH_TIMEOUT_SEC", "60"))
    cmd = [
        rg,
        "--glob",
        glob_pat,
        "-n",
        "--max-count",
        str(max(1, max_results)),
        "--max-columns",
        "500",
        pattern,
        str(root),
    ]
    return run_command(cmd, cwd=root, timeout_sec=timeout)


def search_python_fallback(
    pattern: str,
    *,
    glob_pat: str,
    max_results: int,
    root: Path,
) -> ProcResult:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return ProcResult(
            command=["python-fallback"],
            cwd=str(root),
            exit_code=2,
            stdout="",
            stderr=f"invalid regex: {e}",
        )
    lines_out: list[str] = []
    count = 0
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"}

    for path in root.rglob("*"):
        if count >= max_results:
            break
        if path.is_dir():
            continue
        parts = path.relative_to(root).parts
        if any(p in skip_dirs for p in parts):
            continue
        rel = str(path.relative_to(root))
        if glob_pat not in ("**/*", "*"):
            if not fnmatch.fnmatch(rel, glob_pat):
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if count >= max_results:
                break
            if regex.search(line):
                lines_out.append(f"{rel}:{i}:{line}")
                count += 1

    body = "\n".join(lines_out)
    if not body:
        body = "(no matches)"
    return ProcResult(
        command=["python-fallback", "regex-scan"],
        cwd=str(root),
        exit_code=0 if lines_out else 1,
        stdout=body,
        stderr="",
    )


def search_codebase(
    pattern: str,
    *,
    glob_pat: str = "**/*",
    max_results: int = 50,
) -> ProcResult:
    root = workspace_root()
    if which_rg():
        return search_with_rg(pattern, glob_pat=glob_pat, max_results=max_results, root=root)
    return search_python_fallback(pattern, glob_pat=glob_pat, max_results=max_results, root=root)
