#!/usr/bin/env bash
# Cursor MCP: mount the real workspace into the verifier container.
# ${workspaceFolder} in JSON is not always expanded (e.g. Agent/CLI), so we resolve ROOT here.
set -euo pipefail

ROOT="${CURSOR_WORKSPACE_FOLDER:-}"
if [[ -z "$ROOT" ]]; then ROOT="${VSCODE_WORKSPACE_FOLDER:-}"; fi
if [[ -z "$ROOT" ]]; then ROOT="${WORKSPACE_FOLDER:-}"; fi
if [[ -z "$ROOT" ]] && git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT="$(git rev-parse --show-toplevel)"
fi
if [[ -z "$ROOT" ]]; then ROOT="$PWD"; fi

exec docker run -i --rm \
  -v "${ROOT}:/workspace" \
  -e RULE_BASED_WORKSPACE_ROOT=/workspace \
  ghcr.io/kroq86/rule-based-verifier:latest
