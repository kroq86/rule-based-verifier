"""
MCP server: verification layer (read, search, tests, lint) bounded to RULE_BASED_WORKSPACE_ROOT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__
from .detect import get_test_command_with_cwd, lint_command
from .paths import resolve_under_root, workspace_root
from .runner import format_trace_json, format_trace_tool_result, trace_payload
from .search import search_codebase
from .solution_trace import (
    run_solution_semantic_trace_git,
    run_solution_trace_git,
    run_solution_trace_payload,
)

MAX_READ_BYTES = int(os.environ.get("RULE_BASED_MAX_READ_BYTES", str(2 * 1024 * 1024)))

mcp = FastMCP(
    "rule-based-verifier",
    instructions=(
        "Verification tools for this repo: read files under the workspace root, search code, "
        "run tests and linters, and solution_trace (mode=git|payload|semantic: git diff hunks + imports, "
        "explicit JSON chunks/edges, or AST symbol/call graph for changed Python). "
        "High-risk actions (deploy, DB writes, issue mutations) are not exposed. "
        "Set RULE_BASED_WORKSPACE_ROOT to the repository root when the server cwd is not the repo."
    ),
)


def _json_response(payload: dict) -> str:
    return format_trace_json(payload)


@mcp.tool()
def verifier_health() -> str:
    """Report server version, resolved workspace root, and detected test/lint commands."""
    root = workspace_root()
    test_cmd, test_src, test_cwd = get_test_command_with_cwd(root)
    lint_cmd, lint_src = lint_command(root)
    payload = trace_payload(
        "verifier_health",
        str(root),
        extra={
            "version": __version__,
            "test_command": test_cmd,
            "test_command_source": test_src,
            "test_command_cwd": str(test_cwd),
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
    cmd, src, cwd = get_test_command_with_cwd(root)
    if not cmd:
        payload = trace_payload(
            "run_tests",
            "(none)",
            extra={"error": "no test command; set RULE_BASED_TEST_CMD or add pytest/package.json", "source": src},
        )
        return _json_response(payload)
    if extra_args.strip():
        cmd = [*cmd, *shlex.split(extra_args)]
    proc = run_command(cmd, cwd=cwd)
    payload = trace_payload(
        "run_tests",
        src,
        command=cmd,
        result=proc,
    )
    return _json_response(payload)


@mcp.tool(name="solution_trace")
def solution_trace(
    mode: str = "git",
    ref: str = "HEAD",
    staged: bool = False,
    payload_json: str = "",
    write_svg_relative: str = "",
    write_html_relative: str = "",
    serve_localhost: bool = False,
) -> str:
    """
    One entry point for solution graphs. **mode** (case-insensitive):

    - ``git`` (default): git diff → hunk nodes + Python import edges. Args: ``ref``, ``staged``,
      ``write_svg_relative``. Needs ``.git`` (mount full repo in Docker).
    - ``payload``: explicit JSON object with ``chunks`` and optional ``edges``. Arg: ``payload_json``.
    - ``semantic``: AST symbol add/remove/modify + call/import edges for changed ``.py`` files.
      Args: ``ref``, ``staged``, ``write_svg_relative``, ``write_html_relative`` (optional interactive HTML).

    All modes: Markdown + JSON; optional localhost SVG preview when ``serve_localhost`` is true.
    """
    import json

    m = (mode or "git").strip().lower()
    rel = write_svg_relative.strip() or None
    html_rel = write_html_relative.strip() or None
    if html_rel is None:
        html_rel = "solution_semantic_trace.html" if m == "semantic" else "solution_trace.html"

    if m == "payload":
        if not (payload_json or "").strip():
            payload = {
                "tool": "solution_trace",
                "summary_lines": ["mode=payload requires non-empty payload_json"],
                "error": "payload_json required",
            }
            return format_trace_tool_result(payload)
        try:
            data = json.loads(payload_json)
        except json.JSONDecodeError as e:
            payload = {
                "tool": "solution_trace",
                "summary_lines": [f"Invalid JSON: {e}"],
                "error": str(e),
            }
            return format_trace_tool_result(payload)
        if not isinstance(data, dict):
            payload = {
                "tool": "solution_trace",
                "summary_lines": ["payload must be a JSON object"],
                "error": "payload must be a JSON object",
            }
            return format_trace_tool_result(payload)
        out = run_solution_trace_payload(
            data,
            write_svg_relative=rel,
            write_html_relative=html_rel,
            serve_localhost=serve_localhost,
        )
        return format_trace_tool_result(out)

    if m == "semantic":
        payload = run_solution_semantic_trace_git(
            ref=ref,
            staged=staged,
            write_svg_relative=rel,
            write_html_relative=html_rel,
            serve_localhost=serve_localhost,
        )
        return format_trace_tool_result(payload)

    if m != "git":
        payload = {
            "tool": "solution_trace",
            "summary_lines": [f"unknown mode {mode!r}; use git, payload, or semantic"],
            "error": f"unknown mode: {mode}",
        }
        return format_trace_tool_result(payload)

    payload = run_solution_trace_git(
        ref=ref,
        staged=staged,
        write_svg_relative=rel,
        write_html_relative=html_rel,
        serve_localhost=serve_localhost,
    )
    return format_trace_tool_result(payload)


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
