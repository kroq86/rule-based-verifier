# Agent operating instructions (this repo)

**Core rule:** AI is a junior pair, not the driver. Humans own architecture, boundaries, contracts, and stop decisions.

This file is the source of truth for how assistants (Cursor, Codex, and similar) should behave in this project. Cursor rules summarize and enforce; this document explains why.

---

## Paste-ready operating mode (default)

Use this loop for every session:

1. **Human defines boundary** (what changes, what must not change).
2. **AI proposes one tiny change** (one function, file, test, refactor, migration step, or localized diff).
3. **If MCP (or other tools) are available:** use them to **inspect or verify** inside that boundary—not to expand scope (see “Phase MCP-3”).
4. **Human reviews logic** before caring about the diff (see “Explanation before code”).
5. **Tests and checks run** (via MCP, scripts, or manual verification).
6. **Circuit breaker:** after **two failed AI-driven fix attempts** on the **same issue**, stop using AI for that issue and debug manually.

**Minimal rollout (smallest usable version):**

1. AI only does small, scoped changes.
2. Explanation before code is mandatory for nontrivial work.
3. Two failed retries on the same issue means stop.
4. Human owns architecture.
5. Every nontrivial change records why, invariants, and what test proves it.

---

## Standard explanation format (any technical topic)

Use this structure everywhere: architecture notes, reviews, onboarding, interviews, and agent turns.

1. **Idea** — What we are solving.
2. **Language/API** — Surface syntax and public contracts.
3. **Planner/runtime** — Control flow, execution model, when things run.
4. **Storage/data-structure** — Where state lives and how it is shaped.
5. **OS/hardware** — Environment, I/O, machines (when relevant).
6. **Complexity/perf** — Cost and scaling characteristics.
7. **One-liner** — Summary in one sentence.

---

## Shrink AI task size

**Do not** ask the model to: build the whole feature, redesign the system, or fix everything in one go.

**Do** ask for exactly one of: one function, one file, one test, one refactor, one schema or migration step, or one localized change set.

Goal: every AI contribution stays reviewable and bounded (reduces loss of understanding and unknown debt).

---

## Explanation before code (mandatory for nontrivial generation)

Before producing nontrivial code, output this template (human reviews **this** before the diff):

| Section | Content |
|--------|---------|
| **Plan** | Steps and intent in plain language |
| **Touched files** | Paths you expect to change or add |
| **Assumptions** | What you are assuming about the codebase or environment |
| **Risks** | What could break or surprise reviewers |
| **Rollback** | How to revert or what to undo if this is wrong |

This is workflow, not optional etiquette.

---

## Circuit breaker

**After 2 failed AI fixes on the same issue, stop and debug manually.**

“Failed” means the fix did not resolve the bug, broke tests, or required another blind retry without understanding. Do not enter an infinite retry loop.

---

## Human-owned vs AI-owned

**Human-owned (assistant does not choose alone unless the human explicitly approved a path):**

- Module boundaries
- Data flow
- State model
- API contracts
- Error strategy
- Auth
- Concurrency
- Caching
- Data model design
- Scaling choices

The assistant may analyze options or draft text, but **does not silently decide** these.

**Approved AI usage**

| Good fit | Not primary driver |
|----------|-------------------|
| Boilerplate | Architecture |
| Tests | Auth |
| Repetitive refactors | Concurrency |
| Local transformations | Caching |
| Summarizing unfamiliar code | Data model |
| | Scaling |

**Git and remotes (human-owned):** `git commit`, `git push` (including `--force`), tags, and any change to remotes or default branch protection. The assistant does **not** run these unless the user **explicitly** asks in this conversation (e.g. “commit and push that”).

---

## Git, commits, and remotes

**Never commit or push without explicit user permission.**

- Do **not** run `git commit`, `git push`, `git push --force`, `git tag`, or alter remotes/branches on the server unless the user **clearly** asked you to in the current thread.
- You may prepare diffs, suggest commit messages, and show exact shell commands; the user runs them unless they have explicitly delegated commit/push to you.
- Applies to **any** automation or tool that would write to git history or update a remote.

---

## Change trail (nontrivial work)

For each meaningful change, record (in PR description, commit body, or a short change note):

- **Why** this exists
- **Alternatives rejected** (briefly)
- **Invariants** that must stay true
- **What test** (or check) proves it

This reduces mystery diffs and future debt.

---

## Rules vs MCP (mental model)

**Rules = behavior.** `AGENTS.md`, Cursor rules, and contribution norms define how the model should act: small steps, explain-first, human ownership, stop conditions.

**MCP = capabilities.** MCP exposes tools the model can **call**: run tests, linters, search the repo, tickets, DB reads, custom APIs—**verification and real actions**, not “making the model smarter.”

MCP fits **after** workflow rules exist. Without rules, more tools mostly give the model more ways to do the wrong thing faster.

---

## Phase MCP-1 — What MCP is for

Use MCP for **verification and bounded actions**, not as a substitute for governance.

- **Rules / AGENTS.md / Cursor rules** → how the assistant should behave.
- **MCP** → what it can invoke to check or act: tests, linters, safe file reads, codebase search, issue trackers, read-only DB inspection, project APIs.

---

## Phase MCP-2 — Smallest useful MCP server set

Avoid a large tool zoo. Start with tools that **reduce blind guessing**:

1. Run tests  
2. Run linter / formatter (and type-checker when applicable)  
3. Read repo files safely  
4. Search the codebase  
5. Optionally: issue tracker / tickets  
6. Optionally: database **read-only** inspection  

Add more only when a clear verification gap appears.

**This repository:** a stdio MCP server lives in `mcp/` (`rule-based-verifier`). It exposes `verifier_health`, `read_repo_file`, `search_codebase`, `run_tests`, and `run_lint`. Cursor wiring: **`~/.cursor/mcp.json`** (global) and/or optional **`.cursor/mcp.json`** calling **`mcp/scripts/run-docker-mcp.sh`** (see `CONTRIBUTING.md`); local dev can still use `uv run` from `mcp/` without Docker. The same server is also published as a **Docker image** to GHCR (see `Dockerfile` and `CONTRIBUTING.md`) for reuse in other repos without a local Python toolchain. No issue-tracker or DB tools are bundled here by design (high-risk surfaces stay human-gated).

---

## Phase MCP-3 — MCP only inside the bounded workflow

When MCP is enabled, the runtime should follow:

1. Human defines boundary  
2. AI proposes a **small** change  
3. AI uses MCP to **inspect or verify** within that boundary  
4. Human reviews logic (and diff)  
5. Tests/checks run (MCP or otherwise)  
6. If **two** failed retries on the **same issue**, stop and debug manually  

MCP extends **verification**; it does not replace the planner/runtime loop or human review.

---

## Phase MCP-4 — Restrict MCP authority

MCP must not become “the model gets production powers.” Prefer early:

- Read-only or narrow repo access  
- Test execution  
- Lint / type-check  
- Local, safe utilities  

Treat as **high-risk** and **later / human-gated** unless policy explicitly allows:

- Writes to production databases  
- Deploy or infra mutation  
- Auto-merge PRs  
- Delete or update remote resources without human approval  

This matches **bounded, verifiable steps with human ownership**—MCP should strengthen that, not bypass it.

---

## Phase MCP-5 — MCP and traceability

Tie MCP use to the **explicit trail**:

- **What** tool ran (name/id)  
- **What** target (path, suite, query, ticket id, …)  
- **What** came back (pass/fail, excerpt, error)  
- **What test or check** proves the code change (still required for nontrivial edits)  

The assistant should make this easy to see in the session (or in PR notes when relevant).

---

## Practical MCP rollout (for this project)

1. **Rules first** — Ship `AGENTS.md` and Cursor rules before expanding MCP; tools do not replace rules.  
2. **Add only 2–3 MCP tools initially** — e.g. repo search, test runner, linter/type-checker.  
3. **Plan before tool use** — Before calling MCP, state **what** you want to check, **why**, and **what result would confirm or reject** the hypothesis.  
4. **Writes human-approved** — Keep destructive or production-side actions off the default path; require explicit human approval at least initially.  
5. **Review impact** — If MCP only made the assistant faster at producing noise, **remove or narrow** tools.

---

## Common traps (name them early)

- Confident wrongness
- Lost codebase understanding
- Short-horizon success
- Unknown debt
- Fix-it loop
- Fluency bias
- Completion bias
- Local success bias
- Tool bias
- Prompt bias

---

## Optional framing: Naive Bayes as teaching model

You can think of a healthy session as becoming more probable when you combine:

- Small units
- Explain-first workflow
- Circuit breaker
- Human-owned boundaries
- Explicit change trail

This is a mental model for why structure beats “better prompting,” not a literal production system.

---

## One-line summary

**Reduce AI authority, force explicit reasoning, bound change size, stop infinite retries, and keep architecture under human control.**

**MCP:** MCP is the **verification and action layer**: useful **after** rules, small-step workflow, human ownership, and stop conditions are defined—it does not replace them.

---

## Phase map (reference)

| Phase | Topic |
|-------|--------|
| 0 | Core rule: junior pair, human owns architecture and stops |
| 1 | Seven-point explanation format |
| 2 | Small task size only |
| 3 | Plan / files / assumptions / risks / rollback before code |
| 4 | Two failures → manual debug |
| 5 | Human-owned decisions listed explicitly |
| 6 | Change trail: why, alternatives, invariants, test |
| 7 | Where AI is a good fit vs not |
| 8 | Default operating loop (boundary → tiny change → MCP verify when enabled → human review → tests → circuit breaker) |
| 9 | Rules files (this repo: `AGENTS.md`, `.cursor/rules`, `CONTRIBUTING.md`) |
| 10 | Rules vs MCP (behavior vs capabilities) |
| 11 | Named failure modes |
| 12 | Optional Naive Bayes framing |
| MCP-1 | MCP for verification/actions, not “smarter model” |
| MCP-2 | Minimal MCP tool set (tests, lint, read/search, optional tickets/DB read) |
| MCP-3 | MCP only inside bounded loop (propose → verify → human review → checks → circuit breaker) |
| MCP-4 | Restrict authority (prefer read-only/safe; gate high-risk writes) |
| MCP-5 | Traceability for each MCP action + link to change trail |
| 13 | No `git commit` / `git push` / force-push / remote changes without explicit user permission |
