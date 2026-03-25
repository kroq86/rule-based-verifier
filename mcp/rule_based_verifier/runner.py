"""Subprocess helpers with timeouts and size limits."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n... [truncated] ...\n"


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_sec: float | None = None,
    max_out_chars: int = 120_000,
) -> ProcResult:
    timeout = timeout_sec
    if timeout is None:
        timeout = float(os.environ.get("RULE_BASED_CMD_TIMEOUT_SEC", "300"))

    try:
        p = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return ProcResult(
            command=command,
            cwd=str(cwd),
            exit_code=p.returncode,
            stdout=_truncate(p.stdout or "", max_out_chars),
            stderr=_truncate(p.stderr or "", max_out_chars),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        return ProcResult(
            command=command,
            cwd=str(cwd),
            exit_code=-1,
            stdout=_truncate(out, max_out_chars),
            stderr=_truncate(err + "\n[timeout]", max_out_chars),
            timed_out=True,
        )


def which_rg() -> str | None:
    return shutil.which("rg")


def trace_payload(
    tool: str,
    target: str,
    *,
    command: list[str] | None = None,
    result: ProcResult | None = None,
    extra: dict | None = None,
) -> dict:
    from .paths import workspace_root

    payload: dict = {
        "tool": tool,
        "target": target,
        "workspace_root": str(workspace_root()),
    }
    if command is not None:
        payload["command"] = command
    if result is not None:
        payload["cwd"] = result.cwd
        payload["exit_code"] = result.exit_code
        payload["stdout"] = result.stdout
        payload["stderr"] = result.stderr
        payload["timed_out"] = result.timed_out
    if extra:
        payload.update(extra)
    return payload


def format_trace_json(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def format_trace_tool_result(payload: dict) -> str:
    """Markdown summary (when present) plus full JSON for MCP tool responses."""
    tool = payload.get("tool", "trace")
    parts: list[str] = [f"## {tool}"]
    for line in payload.get("summary_lines") or []:
        parts.append(str(line))
    if payload.get("preview_url"):
        parts.append(f"**Preview:** {payload['preview_url']}")
    if payload.get("preview_error"):
        parts.append(f"**Preview error:** {payload['preview_error']}")
    if payload.get("svg_path"):
        parts.append(f"**SVG:** `{payload['svg_path']}`")
    if payload.get("html_path"):
        parts.append(f"**HTML:** `{payload['html_path']}`")
    if payload.get("html_uri"):
        parts.append(f"**HTML URI:** {payload['html_uri']}")
    if payload.get("error"):
        parts.append(f"**Error:** {payload['error']}")
    parts.extend(["", "```json", json.dumps(payload, indent=2), "```"])
    return "\n".join(parts)
