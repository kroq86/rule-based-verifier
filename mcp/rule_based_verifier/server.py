"""
MCP server: verification layer (read, search, tests, lint) bounded to RULE_BASED_WORKSPACE_ROOT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__
from .detect import lint_command, test_command
from .paths import resolve_under_root, workspace_root
from .runner import format_trace_json, trace_payload
from .search import search_codebase

MAX_READ_BYTES = int(os.environ.get("RULE_BASED_MAX_READ_BYTES", str(2 * 1024 * 1024)))

mcp = FastMCP(
    "rule-based-verifier",
    instructions=(
        "Verification tools for this repo: read files under the workspace root, search code, "
        "run tests and linters. High-risk actions (deploy, DB writes, issue mutations) are not exposed. "
        "Set RULE_BASED_WORKSPACE_ROOT to the repository root when the server cwd is not the repo."
    ),
)


def _json_response(payload: dict) -> str:
    return format_trace_json(payload)


@mcp.tool()
def verifier_health() -> str:
    """Report server version, resolved workspace root, and detected test/lint commands."""
    root = workspace_root()
    test_cmd, test_src = test_command(root)
    lint_cmd, lint_src = lint_command(root)
    payload = trace_payload(
        "verifier_health",
        str(root),
        extra={
            "version": __version__,
            "test_command": test_cmd,
            "test_command_source": test_src,
            "lint_command": lint_cmd,
            "lint_command_source": lint_src,
            "python_executable": sys.executable,
        },
    )
    return _json_response(payload)


@mcp.tool()
def read_repo_file(relative_path: str) -> str:
    """
    Read a text file under the workspace root (read-only). Path must be relative; no absolute paths.
    """
    root = workspace_root()
    try:
        path = resolve_under_root(relative_path, root)
    except ValueError as e:
        payload = trace_payload("read_repo_file", relative_path, extra={"error": str(e)})
        return _json_response(payload)
    if not path.is_file():
        payload = trace_payload(
            "read_repo_file",
            relative_path,
            extra={"error": "not a file or does not exist", "resolved": str(path)},
        )
        return _json_response(payload)
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        payload = trace_payload(
            "read_repo_file",
            relative_path,
            extra={
                "error": f"file too large ({size} bytes > {MAX_READ_BYTES})",
                "resolved": str(path),
            },
        )
        return _json_response(payload)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        payload = trace_payload("read_repo_file", relative_path, extra={"error": str(e)})
        return _json_response(payload)
    payload = trace_payload(
        "read_repo_file",
        relative_path,
        extra={"resolved": str(path), "bytes": size, "content": content},
    )
    return _json_response(payload)


@mcp.tool(name="search_codebase")
def search_codebase_tool(
    pattern: str,
    glob_pattern: str = "**/*",
    max_results: int = 50,
) -> str:
    """
    Search the workspace with ripgrep when available, else a Python regex scan.
    Pattern is a ripgrep regex (or Python regex in fallback mode).
    """
    root = workspace_root()
    try:
        res = search_codebase(pattern, glob_pat=glob_pattern, max_results=max(1, min(max_results, 500)))
    except Exception as e:
        payload = trace_payload(
            "search_codebase",
            pattern,
            extra={"error": str(e), "glob_pattern": glob_pattern},
        )
        return _json_response(payload)
    payload = trace_payload(
        "search_codebase",
        pattern,
        command=res.command,
        result=res,
        extra={"glob_pattern": glob_pattern, "max_results": max_results},
    )
    return _json_response(payload)


@mcp.tool()
def run_tests(extra_args: str = "") -> str:
    """
    Run the project test command (override with RULE_BASED_TEST_CMD). Optional extra_args are shell-split.
    """
    import shlex

    from .runner import run_command

    root = workspace_root()
    cmd, src = test_command(root)
    if not cmd:
        payload = trace_payload(
            "run_tests",
            "(none)",
            extra={"error": "no test command; set RULE_BASED_TEST_CMD or add pytest/package.json", "source": src},
        )
        return _json_response(payload)
    if extra_args.strip():
        cmd = [*cmd, *shlex.split(extra_args)]
    proc = run_command(cmd, cwd=root)
    payload = trace_payload(
        "run_tests",
        src,
        command=cmd,
        result=proc,
    )
    return _json_response(payload)


@mcp.tool()
def run_lint(extra_args: str = "") -> str:
    """
    Run the project lint command (override with RULE_BASED_LINT_CMD). Optional extra_args are shell-split.
    """
    import shlex

    from .runner import run_command

    root = workspace_root()
    cmd, src = lint_command(root)
    if not cmd:
        payload = trace_payload(
            "run_lint",
            "(none)",
            extra={
                "error": "no lint command; set RULE_BASED_LINT_CMD or install ruff / npm run lint",
                "source": src,
            },
        )
        return _json_response(payload)
    if extra_args.strip():
        cmd = [*cmd, *shlex.split(extra_args)]
    proc = run_command(cmd, cwd=root)
    payload = trace_payload(
        "run_lint",
        src,
        command=cmd,
        result=proc,
    )
    return _json_response(payload)


def main() -> None:
    # Repository root is `mcp/`'s parent when this package lives under `mcp/rule_based_verifier/`.
    _repo = Path(__file__).resolve().parent.parent.parent
    os.environ.setdefault("RULE_BASED_WORKSPACE_ROOT", str(_repo))
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
