# rule-based-verifier

Human-led workflow for AI-assisted coding: **policy first**, **small steps**, **verification** (tests, lint, search) via MCP—not bigger prompts.

- **`AGENTS.md`** — full operating rules (pair-programming model, plan/rollback, circuit breaker, MCP phases).
- **`CONTRIBUTING.md`** — PR norms, Docker image on GHCR, Cursor `mcp.json` and duplicate-server pitfalls.

## What’s here

| Area | Purpose |
|------|---------|
| **`mcp/`** | Python MCP server **`rule-based-verifier`**: health, read/search under workspace root, run tests & linters (bounded by `RULE_BASED_WORKSPACE_ROOT`). |
| **`.cursor/rules/`** | Cursor project rules (`alwaysApply` summaries of the same policy). |
| **`.cursor/mcp.json`** | Optional: run the verifier via **`mcp/scripts/run-docker-mcp.sh`** (`args` use **`${workspaceFolder}/...`** so **Cursor CLI** finds the script; the launcher still fixes fragile `docker -v` mounts—see **`CONTRIBUTING.md`**). |
| **`Dockerfile`** | Published to **`ghcr.io/kroq86/rule-based-verifier`** (multi-arch **amd64** / **arm64**). |
| **`emacs/`** | Optional Doom Emacs snippets (see **`CONTRIBUTING.md`**). |

## Solution Semantic Trace Preview

Open in browser: `solution_semantic_trace.html` (or use a local `file://` URL for your own clone path).

![Solution semantic trace preview](Screenshot_2026-03-25_at_5.59.59_PM-c557dab2-7f8c-48b7-8788-c70519e58b50.png)

## Run the MCP server (Docker)

Mount the repo you want to verify at `/workspace` and set the env (see **`CONTRIBUTING.md`** for full notes and Cursor or CLI wiring):

```bash
docker pull ghcr.io/kroq86/rule-based-verifier:latest
docker run -i --rm \
  -v "$PWD:/workspace" \
  -e RULE_BASED_WORKSPACE_ROOT=/workspace \
  ghcr.io/kroq86/rule-based-verifier:latest
```

## Local dev (optional)

From **`mcp/`**:

- install deps: **`uv sync`**
- run stdio MCP safely: **`.venv/bin/python -u run_server.py`** (avoid `uv run` for stdio transport)
- run tests: **`.venv/bin/python -m pytest`**
- lint setup: **`run_lint`** uses `RULE_BASED_LINT_CMD` first, then auto-detects `ruff`/`npm run lint`; if none found, configure one explicitly

Treat **`AGENTS.md`** as the source of truth for how assistants should behave in this project.
