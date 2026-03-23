# rule-based-verifier MCP (stdio). Mount the target repo at /workspace and set RULE_BASED_WORKSPACE_ROOT=/workspace.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app/mcp

COPY mcp/pyproject.toml mcp/uv.lock ./
COPY mcp/rule_based_verifier ./rule_based_verifier
COPY mcp/run_server.py ./

RUN uv sync --frozen --no-dev

ENV RULE_BASED_WORKSPACE_ROOT=/workspace

# stdio MCP: keep a single foreground process
CMD ["uv", "run", "python", "run_server.py"]
