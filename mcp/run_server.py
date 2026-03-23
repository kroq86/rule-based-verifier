#!/usr/bin/env python3
"""Launch MCP server without requiring `pip install -e` (adds this directory to PYTHONPATH)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Default workspace = repository root (parent of `mcp/`) when Cursor does not inject env.
os.environ.setdefault("RULE_BASED_WORKSPACE_ROOT", str(_ROOT.parent))

from rule_based_verifier.server import main  # noqa: E402

if __name__ == "__main__":
    main()
