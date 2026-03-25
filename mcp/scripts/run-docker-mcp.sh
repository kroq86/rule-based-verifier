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

IMAGE="${RULE_BASED_DOCKER_IMAGE:-ghcr.io/kroq86/rule-based-verifier:latest}"

# Base: no host port publish — avoids ``docker run`` failing when 8765 (or another port) is
# already in use on the host, which would prevent the MCP server from loading at all.
DOCKER_RUN=(
  docker run -i --rm
  -v "${ROOT}:/workspace"
  -e RULE_BASED_WORKSPACE_ROOT=/workspace
  -e "RULE_BASED_HOST_WORKSPACE_ROOT=${ROOT}"
)

# Optional: publish the trace preview port to the host (set in ``mcp.json`` ``env``).
# Example: RULE_BASED_TRACE_PREVIEW_PORT=8765 → -p 8765:8765
if [[ -n "${RULE_BASED_TRACE_PREVIEW_PORT:-}" ]]; then
  DOCKER_RUN+=(
    -e "RULE_BASED_TRACE_PREVIEW_PORT=${RULE_BASED_TRACE_PREVIEW_PORT}"
    -p "${RULE_BASED_TRACE_PREVIEW_PORT}:${RULE_BASED_TRACE_PREVIEW_PORT}"
  )
fi

exec "${DOCKER_RUN[@]}" "${IMAGE}"
