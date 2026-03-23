# Contributing

This repository follows a **human-led, small-step** workflow for changes, including AI-assisted work. Read **`AGENTS.md`** first; it is the full policy. This file is the contribution-facing summary.

## Principles

- **AI is a junior pair, not the driver.** You own architecture, boundaries, contracts, and when to stop.
- **One bounded change per request** when using assistants: one function, file, test, refactor, migration step, or localized diff—not “the whole feature.”
- **Explain before code** for nontrivial work: plan, touched files, assumptions, risks, rollback (see `AGENTS.md`).
- **Circuit breaker:** after **two** failed fix attempts on the **same** issue with AI assistance, switch to manual debugging for that issue.
- **Assistants must not commit or push** (`git commit`, `git push`, force-push, etc.) **without explicit maintainer permission** in that session—see **`AGENTS.md`** (“Git, commits, and remotes”).
- **Nontrivial changes** should say **why**, what **invariants** hold, **alternatives** considered, and **what test or check** proves correctness (PR description and/or commit body).

## Pull requests

- Prefer small PRs that map to a single clear intent.
- Link or summarize the change trail fields above when the change is not trivial.
- If you used an AI assistant, the PR should still read as if a human understood and owns the result.

## Reviews

- Review **logic and intent** (plan, boundaries, risks) before line-level nitpicks when AI was involved.
- Watch for the traps listed in `AGENTS.md` (e.g., confident wrongness, fix-it loop, completion bias).

## MCP (when enabled in your environment)

MCP is a **verification and action** layer, not a substitute for `AGENTS.md`. Use it to run tests, lint, search the repo, and similar checks—**after** rules and small-step workflow are in place. Prefer a minimal tool set; gate high-risk writes and production actions behind explicit human approval. Before tool calls, the assistant should state what it checks, why, and what would confirm or reject the idea. Details: **`AGENTS.md`** (Phases MCP-1 through MCP-5 and “Practical MCP rollout”).

## Docker image (GHCR)

GitHub Actions (`.github/workflows/docker-publish.yml`) builds the **`Dockerfile`** and pushes to **`ghcr.io/<github-owner>/rule-based-verifier`** on pushes to the default branch and on version tags `v*`. Pull requests build only (no push).

**Run locally (stdio MCP):** mount the project you want to verify at `/workspace` (the image sets `RULE_BASED_WORKSPACE_ROOT=/workspace`).

```bash
docker pull ghcr.io/kroq86/rule-based-verifier:latest
docker run -i --rm \
  -v "$PWD:/workspace" \
  -e RULE_BASED_WORKSPACE_ROOT=/workspace \
  ghcr.io/kroq86/rule-based-verifier:latest
```

Images are built for **linux/amd64** and **linux/arm64** (Apple Silicon pulls the native arm64 variant). If you use an older tag that is amd64-only, run `docker pull --platform linux/amd64 …` or upgrade to a build published after multi-arch was enabled.

**Use in another repo’s Cursor `mcp.json`:** point `command`/`args` at `docker run` with the same volume and env (replace `kroq86` if you fork). Ensure the GitHub Container Registry package is **public** or that you are logged in (`docker login ghcr.io`) with a token that can read it.

## Global Cursor (all workspaces, optional)

To apply the same **MCP** and **rules** in every folder you open:

| Piece | Location |
|--------|-----------|
| **User MCP** | `~/.cursor/mcp.json` — merged with each project’s `.cursor/mcp.json`; **project wins** if the same server name is defined twice. |
| **User rules** | `~/.cursor/rules/*.mdc` — same idea as project rules (`alwaysApply: true`). If your Cursor build does not load these, use **Settings → Cursor → Rules → User Rules** and paste the same policy (body text only, no YAML frontmatter). |

After editing `~/.cursor/mcp.json`, **restart Cursor** or reload MCP. **Docker** must be running for the `rule-based-verifier` container.

**`rule-based-verifier` MCP errors (Agent/CLI):** Cursor does not always expand `${workspaceFolder}` in raw `docker` args, so the container can fail to mount your repo. Use the launcher **`mcp/scripts/run-docker-mcp.sh`**, which resolves the workspace from env (`CURSOR_WORKSPACE_FOLDER`, `VSCODE_WORKSPACE_FOLDER`, `WORKSPACE_FOLDER`), then `git rev-parse`, then `PWD`. Project **`.cursor/mcp.json`** calls that script (see below).

**Duplicate “rule-based-verifier” rows in MCP settings:** The same server id in **both** `~/.cursor/mcp.json` **and** `.cursor/mcp.json` registers twice. Keep **one**: either rely on **global** only (remove the block from the project file) or on **project** only (remove the block from `~/.cursor/mcp.json`).

**Project `mcp.json` (optional):** If you do **not** use a global `rule-based-verifier` entry, add this repo’s **`.cursor/mcp.json`** so the verifier runs via the launcher (Cursor’s cwd should be the repo root):

```json
{
  "mcpServers": {
    "rule-based-verifier": {
      "command": "bash",
      "args": ["mcp/scripts/run-docker-mcp.sh"]
    }
  }
}
```

If you **already** have `rule-based-verifier` in `~/.cursor/mcp.json`, you do **not** need a project file (and should not duplicate the same server id).

This repository ships **`.cursor/rules/`** for project rules. Add **`.cursor/mcp.json`** only when you are not using the global verifier entry.


**Doom Emacs (optional):** **`emacs/doom-extras.el`** holds optional snippets, vterm split to the right on **`SPC p t`**. It is **not** loaded automatically—add e.g. `(load-file "/path/to/this/repo/emacs/doom-extras.el")` to **`~/.doom.d/config.el`** after `doom sync`, or copy only the forms you want.