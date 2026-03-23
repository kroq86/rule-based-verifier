# rule-based-verifier

Human-led workflow for AI-assisted coding: **policy first**, **small steps**, **verification** (tests, lint, search) via MCP—not bigger prompts.

- **`AGENTS.md`** — full operating rules (pair-programming model, plan/rollback, circuit breaker, MCP phases).
- **`CONTRIBUTING.md`** — PR norms, Docker image on GHCR, Cursor `mcp.json` and duplicate-server pitfalls.

## What’s here

| Area | Purpose |
|------|---------|
| **`mcp/`** | Python MCP server **`rule-based-verifier`**: health, read/search under workspace root, run tests & linters (bounded by `RULE_BASED_WORKSPACE_ROOT`). |
| **`.cursor/rules/`** | Cursor project rules (`alwaysApply` summaries of the same policy). |
| **`.cursor/mcp.json`** | Optional: run the verifier via **`mcp/scripts/run-docker-mcp.sh`** (fixes unreliable `${workspaceFolder}` in Docker args). |
| **`Dockerfile`** | Published to **`ghcr.io/kroq86/rule-based-verifier`** (multi-arch **amd64** / **arm64**). |
| **`emacs/`** | Optional Doom Emacs snippets (see **`CONTRIBUTING.md`**). |

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

From **`mcp/`**: install with **`uv sync`**, run **`uv run python run_server.py`**, tests with **`uv run pytest`**.

Treat **`AGENTS.md`** as the source of truth for how assistants should behave in this project.
