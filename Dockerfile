# rule-based-verifier MCP (stdio). Mount the target repo at /workspace and set RULE_BASED_WORKSPACE_ROOT=/workspace.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# `dot` for `trace` tool SVG output (same as host: brew install graphviz)
RUN apt-get update && apt-get install -y --no-install-recommends graphviz git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/mcp

COPY mcp/pyproject.toml mcp/uv.lock ./
COPY mcp/rule_based_verifier ./rule_based_verifier
COPY mcp/run_server.py ./

# Include dev deps (pytest) for a consistent test toolchain inside the image.
# Stdio safety: server still runs ``.venv/bin/python`` directly — no ``uv run`` on stdout.
RUN uv sync --frozen

ENV RULE_BASED_WORKSPACE_ROOT=/workspace

# stdio MCP: **do not** use `uv run` here — it can print downloads/progress to stdout and break
# JSON-RPC on stdio (MCP error -32000 / "Connection closed"). Use the image venv Python only.
ENV PYTHONUNBUFFERED=1
CMD [".venv/bin/python", "-u", "run_server.py"]
