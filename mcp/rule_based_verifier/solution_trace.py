"""Solution trace: git diff hunks + optional payload chunks, import edges between changed Python files, DOT/SVG."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .paths import resolve_under_root, workspace_root

# Unified diff hunk header: @@ -old_start[,old_len] +new_start[,new_len] @@
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _render_svg_bytes(dot_text: str) -> tuple[bytes | None, str | None]:
    """Render Graphviz DOT to SVG bytes (``dot -Tsvg`` stdout, or Python graphviz fallback)."""
    dot_bin = shutil.which("dot")
    if dot_bin:
        try:
            p = subprocess.run(
                [dot_bin, "-Tsvg"],
                input=dot_text,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if p.returncode == 0 and (p.stdout or "").strip():
                return p.stdout.encode("utf-8"), None
            err = (p.stderr or "").strip() or f"dot exit {p.returncode}"
            return None, err
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, str(e)
    try:
        from graphviz import Source

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            stem = Path(td) / "g"
            Source(dot_text).render(str(stem), format="svg", cleanup=True)
            produced = Path(str(stem) + ".svg")
            if produced.exists():
                return produced.read_bytes(), None
    except ImportError:
        pass
    except OSError as e:
        return None, str(e)
    return None, "no `dot` on PATH and no Python graphviz package"


# --- Localhost HTML preview for generated SVG (single shared server; replaces former trace_preview) ---

_preview_lock = threading.Lock()
_preview_server: ThreadingHTTPServer | None = None


def _preview_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _preview_bind_host() -> str:
    return "0.0.0.0" if _preview_in_docker() else "127.0.0.1"


def _preview_bind_port() -> int:
    raw = os.environ.get("RULE_BASED_TRACE_PREVIEW_PORT", "").strip()
    if raw:
        return int(raw)
    return 8765


def _preview_pick_port(preferred: int) -> int:
    if preferred == 0:
        return 0
    host = _preview_bind_host()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, preferred))
    except OSError:
        return 0
    return preferred


def _svg_preview_html_page(svg_utf8: str) -> str:
    safe = re.sub(r"</script>", r"<\\/script>", svg_utf8, flags=re.IGNORECASE)
    return (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trace preview</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    margin: 0;
    padding: 24px;
    background: #f0f3f6;
    color: #1a1a1a;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #0d1117; color: #e6edf3; }
    .card { background: #161b22; border-color: #30363d; box-shadow: none; }
  }
  .card {
    max-width: 1280px;
    margin: 0 auto;
    background: #fff;
    border: 1px solid #d8dee4;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,.06);
    padding: 20px 24px 28px;
  }
  h1 {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0 0 16px;
    letter-spacing: -0.02em;
  }
  .svg-wrap {
    overflow: auto;
    width: 100%;
    -webkit-overflow-scrolling: touch;
  }
  .svg-wrap svg {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
  }
</style>
</head>
<body>
  <div class="card">
    <h1>Trace preview</h1>
    <div class="svg-wrap">
"""
        + safe
        + """
    </div>
  </div>
</body>
</html>
"""
    )


def _start_trace_preview_server(svg_bytes: bytes) -> tuple[str | None, str | None]:
    global _preview_server
    try:
        svg_text = svg_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        return None, f"SVG is not valid UTF-8: {e}"

    def _normalize_path(raw: str) -> str:
        p = raw.split("?", 1)[0].strip()
        if p.startswith("http://") or p.startswith("https://"):
            p = urlparse(p).path or "/"
        while "//" in p:
            p = p.replace("//", "/")
        return p or "/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = _normalize_path(self.path)
            if path in ("/", ""):
                body = _svg_preview_html_page(svg_text).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                msg = b"Not found. Open / (GET / or http://127.0.0.1:<port>/) for the trace preview.\n"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

    host = _preview_bind_host()
    want = _preview_bind_port()
    port = _preview_pick_port(want) if want != 0 else 0
    try:
        server = ThreadingHTTPServer((host, port), Handler)
        server.allow_reuse_address = True
    except OSError as e:
        return None, f"cannot bind preview server ({host}:{port}): {e}"

    _, actual_port = server.server_address[:2]

    def _run() -> None:
        server.serve_forever(poll_interval=0.5)

    t = threading.Thread(target=_run, name="trace-preview-http", daemon=True)
    with _preview_lock:
        if _preview_server is not None:
            try:
                _preview_server.shutdown()
            except Exception:
                pass
        _preview_server = server
    t.start()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", actual_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    url = f"http://127.0.0.1:{actual_port}/"

    return url, None


def _preview_enabled() -> bool:
    v = os.environ.get("RULE_BASED_TRACE_PREVIEW", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _host_file_uri(local_path: str, workspace_root_path: Path) -> str | None:
    """Best-effort map /workspace path to host file:// URI when running in Docker."""
    host_root = os.environ.get("RULE_BASED_HOST_WORKSPACE_ROOT", "").strip()
    if not host_root:
        return None
    try:
        local_abs = Path(local_path).expanduser().resolve()
        root_abs = workspace_root_path.resolve()
        rel = local_abs.relative_to(root_abs)
        host_abs = Path(host_root).expanduser().resolve() / rel
        return host_abs.as_uri()
    except Exception:
        return None


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_bytes(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1024, int(raw))
    except ValueError:
        return default


@dataclass
class Hunk:
    path: str
    new_start: int
    new_len: int
    excerpt: str


@dataclass
class ChunkNode:
    id: str
    path: str
    start_line: int
    end_line: int
    label: str
    kind: str = "hunk"  # or "payload"


@dataclass
class SymbolChange:
    id: str
    path: str
    qualname: str
    kind: str
    status: str  # added | removed | modified
    calls: list[str]
    old_code: str
    new_code: str


def parse_unified_diff(diff_text: str, *, max_hunks: int | None = None) -> list[Hunk]:
    """Parse unified diff into hunks (new-file line ranges + short excerpt)."""
    hunks: list[Hunk] = []
    current_path: str | None = None
    lines = diff_text.splitlines()
    i = 0
    mh = max_hunks or 10_000

    while i < len(lines) and len(hunks) < mh:
        line = lines[i]
        if line.startswith("+++ "):
            # +++ b/path or +++ /dev/null
            rest = line[4:].strip()
            if rest.startswith("b/"):
                current_path = rest[2:]
            elif rest == "/dev/null":
                current_path = None
            else:
                current_path = rest.lstrip("a/").lstrip("b/")
            i += 1
            continue

        m = _HUNK_RE.match(line)
        if m and current_path:
            new_start = int(m.group(3))
            new_len = int(m.group(4) or "1")
            i += 1
            body: list[str] = []
            while i < len(lines):
                ln = lines[i]
                if ln.startswith("diff --git") or (ln.startswith("--- ") and i > 0):
                    break
                if _HUNK_RE.match(ln):
                    break
                if ln.startswith("@@"):
                    break
                if ln.startswith("\\"):
                    i += 1
                    continue
                if ln.startswith("+") and not ln.startswith("+++"):
                    body.append(ln[1:][:120])
                elif ln.startswith(" ") and not ln.startswith("---"):
                    body.append(ln[1:][:120])
                i += 1
            excerpt = " ".join(body[:3])[:200]
            if new_len == 0:
                # empty hunk at end of file — still record
                excerpt = excerpt or "(empty hunk)"
            end_line = new_start + max(0, new_len) - 1 if new_len else new_start
            hunks.append(
                Hunk(
                    path=current_path,
                    new_start=new_start,
                    new_len=max(1, new_len) if new_len == 0 else new_len,
                    excerpt=excerpt.strip() or "…",
                )
            )
            continue
        i += 1

    return hunks


def _hunk_id(path: str, new_start: int, new_len: int) -> str:
    end = new_start + new_len - 1
    return f"{path}:{new_start}-{end}"


def _chunks_from_hunks(hunks: list[Hunk]) -> list[ChunkNode]:
    out: list[ChunkNode] = []
    for h in hunks:
        end_line = h.new_start + h.new_len - 1
        hid = _hunk_id(h.path, h.new_start, h.new_len)
        label = f"{Path(h.path).name}\\n{h.excerpt[:80]}"
        out.append(
            ChunkNode(
                id=hid,
                path=h.path,
                start_line=h.new_start,
                end_line=end_line,
                label=label.replace('"', "'"),
                kind="hunk",
            )
        )
    return out


def _try_resolve_module(root: Path, parts: tuple[str, ...]) -> Path | None:
    """Map dotted module to a file under *root* (package layout)."""
    if not parts:
        return None
    *parents, last = parts
    base = root.joinpath(*parents) if parents else root
    cand = base / f"{last}.py"
    if cand.is_file():
        return cand.resolve()
    init_py = base / last / "__init__.py"
    if init_py.is_file():
        return init_py.resolve()
    nested = base / f"{last}/__init__.py"
    if nested.is_file():
        return nested.resolve()
    return None


def _resolve_import_to_path(
    root: Path,
    module: str | None,
    level: int,
    current_file: Path,
) -> Path | None:
    """Resolve import target to absolute path under *root*."""
    if module is None:
        return None
    parts = tuple(module.split(".")) if module else ()
    if level and level > 0:
        # relative: walk up from current_file's package
        cur = current_file.parent
        for _ in range(level - 1):
            cur = cur.parent
        rel = cur.relative_to(root) if cur.is_relative_to(root) else None
        if rel is None:
            return None
        rel_parts = tuple(rel.parts) + parts if parts else tuple(rel.parts)
        return _try_resolve_module(root, rel_parts)
    return _try_resolve_module(root, parts)


def _python_import_targets(root: Path, rel_path: str) -> set[Path]:
    """Absolute paths of workspace files imported from this Python file (module-level only)."""
    targets: set[Path] = set()
    try:
        path = resolve_under_root(rel_path, root=root)
    except ValueError:
        return targets
    if path.suffix != ".py" or not path.is_file():
        return targets
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return targets
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return targets

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                p = _try_resolve_module(root, tuple(alias.name.split(".")))
                if p and _is_under_root(p, root):
                    targets.add(p)
        elif isinstance(node, ast.ImportFrom):
            if (node.level or 0) > 0:
                continue  # v1: skip relative imports (resolution is package-layout dependent)
            mod = node.module
            tgt = _resolve_import_to_path(root, mod, 0, path)
            if tgt and _is_under_root(tgt, root):
                targets.add(tgt)
            if mod:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    sub = tuple(mod.split(".")) + (alias.name,)
                    p = _try_resolve_module(root, sub)
                    if p and _is_under_root(p, root):
                        targets.add(p)
    return targets


def _is_under_root(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _rel_str(root: Path, abs_path: Path) -> str:
    return str(abs_path.resolve().relative_to(root.resolve())).replace("\\", "/")


def build_import_edges(
    root: Path,
    changed_py_relpaths: set[str],
) -> list[tuple[str, str]]:
    """
    Directed edges (importer_id, imported_id) at **file** level for v1:
    we connect files that both appear in *changed_py_relpaths* and have an import relationship.
    IDs are ``path`` (file path relative to workspace) for edge endpoints; the graph will
    link file nodes — for hunks we duplicate edges from each hunk in importer to each hunk in imported
    or simplify: v1 plan says edge between changed files — I'll add edge from **first hunk** of importer
    to **first hunk** of imported file, or a synthetic file-level node.

    Plan: "Add directed edge importer → imported when both files have at least one hunk"

    Simplest graph: nodes are **hunks**. Import edge from file A to B: add edge from **each** hunk in A
    to **each** hunk in B (can be noisy). Better: one edge from **min line hunk in A** to **min line hunk in B**.

    I'll add one edge per (importer_file, imported_file) pair: connect the first hunk node of each file
    (by order in hunks list).
    """
    changed_abs: dict[str, Path] = {}
    for rp in changed_py_relpaths:
        if not rp.endswith(".py"):
            continue
        try:
            changed_abs[rp] = resolve_under_root(rp, root=root)
        except ValueError:
            continue

    edges: list[tuple[str, str]] = []
    for rel, abspath in changed_abs.items():
        targets = _python_import_targets(root, rel)
        for t in targets:
            tr = _rel_str(root, t)
            if tr in changed_py_relpaths and tr != rel:
                edges.append((rel, tr))
    # dedupe
    return list(dict.fromkeys(edges))


def _map_file_edges_to_hunk_edges(
    file_edges: list[tuple[str, str]],
    chunks: list[ChunkNode],
) -> list[tuple[str, str]]:
    """Map file-level (a.py, b.py) to first hunk id per file."""
    first_hunk: dict[str, str] = {}
    for c in chunks:
        if c.path not in first_hunk:
            first_hunk[c.path] = c.id
    out: list[tuple[str, str]] = []
    for a, b in file_edges:
        ha = first_hunk.get(a)
        hb = first_hunk.get(b)
        if ha and hb and ha != hb:
            out.append((ha, hb))
    return list(dict.fromkeys(out))


def dot_from_chunks_and_edges(
    chunks: list[ChunkNode],
    edges: list[tuple[str, str]],
) -> str:
    """Emit Graphviz DOT (left-to-right, micrograd-style: rounded value boxes, op ellipses on edges)."""
    lines: list[str] = [
        "digraph G {",
        "  rankdir=LR;",
        "  nodesep=0.35;",
        "  ranksep=0.55;",
        "  splines=polyline;",
    ]
    id_map = {c.id: c for c in chunks}

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    for c in chunks:
        # Three-line label: kind, location, excerpt (like ``data`` + lines in notebook)
        pshort = esc(c.path)
        loc = f"L{c.start_line}-{c.end_line}"
        ex = esc(c.label.replace("\\n", " ")[:100])
        lbl = f"{esc(c.kind)}\\n{pshort}\\n{loc}\\n{ex}"
        fill = "#E3F2FD" if c.kind == "payload" else "#E8F4FC"
        lines.append(
            f'  "{c.id}" [label="{lbl}", shape=box, style="rounded,filled", '
            f'fillcolor="{fill}", color="#1565C0", fontsize=9];'
        )

    for i, (a, b) in enumerate(edges):
        if a not in id_map or b not in id_map:
            continue
        op_id = "op_" + hashlib.sha256(f"{a}|{b}|{i}".encode()).hexdigest()[:12]
        lines.append(
            f'  "{op_id}" [label="imports", shape=ellipse, style=filled, fillcolor="#FFFACD", '
            f'color="#B8860B", fontsize=10];'
        )
        lines.append(f'  "{a}" -> "{op_id}";')
        lines.append(f'  "{op_id}" -> "{b}";')

    lines.append("}")
    return "\n".join(lines)


def _git_diff(root: Path, *, ref: str, staged: bool) -> tuple[str | None, str | None]:
    if not (root / ".git").exists():
        return None, "not a git repository (.git missing — mount the full repo including .git for Docker)"
    exe = shutil.which("git")
    if not exe:
        return None, "git executable not found on PATH"
    cmd = [exe, "-C", str(root), "diff", "--no-color"]
    if staged:
        cmd.append("--cached")
    else:
        cmd.append(ref)
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip() or f"git exit {p.returncode}"
        return None, err
    return p.stdout or "", None


def _git_show_text(root: Path, spec: str, rel_path: str) -> str | None:
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        p = subprocess.run(
            [exe, "-C", str(root), "show", f"{spec}:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _symbols_from_source(src: str, rel_path: str) -> dict[str, tuple[str, str, list[str], str]]:
    """
    Map qualname -> (kind, ast_hash, call_names, code_snippet) for top-level classes/functions and methods.
    """
    out: dict[str, tuple[str, str, list[str], str]] = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out

    def node_hash(n: ast.AST) -> str:
        return hashlib.sha256(ast.dump(n, include_attributes=False).encode()).hexdigest()[:12]

    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qn = top.name
            calls = sorted(
                {
                    c
                    for c in (_call_name(x.func) for x in ast.walk(top) if isinstance(x, ast.Call))
                    if c
                }
            )
            snippet = (ast.get_source_segment(src, top) or "").strip()
            out[qn] = ("function", node_hash(top), calls, snippet[:1200])
        elif isinstance(top, ast.ClassDef):
            qn = top.name
            snippet = (ast.get_source_segment(src, top) or "").strip()
            out[qn] = ("class", node_hash(top), [], snippet[:1200])
            for item in top.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mqn = f"{top.name}.{item.name}"
                    calls = sorted(
                        {
                            c
                            for c in (_call_name(x.func) for x in ast.walk(item) if isinstance(x, ast.Call))
                            if c
                        }
                    )
                    msnippet = (ast.get_source_segment(src, item) or "").strip()
                    out[mqn] = ("method", node_hash(item), calls, msnippet[:1200])
    return out


def _semantic_dot(nodes: list[SymbolChange], edges: list[tuple[str, str, str]]) -> str:
    lines = [
        "digraph G {",
        "  rankdir=LR;",
        "  nodesep=0.35;",
        "  ranksep=0.55;",
    ]
    by_id = {n.id: n for n in nodes}

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    status_fill = {"added": "#E8F5E9", "removed": "#FFEBEE", "modified": "#FFF8E1"}
    status_pen = {"added": "#2E7D32", "removed": "#C62828", "modified": "#EF6C00"}

    for n in nodes:
        fill = status_fill.get(n.status, "#F4F4F4")
        pen = status_pen.get(n.status, "#616161")
        lbl = f"{esc(n.status)}\\n{esc(n.path)}\\n{esc(n.qualname)}\\n{esc(n.kind)}"
        lines.append(
            f'  "{n.id}" [label="{lbl}", shape=box, style="rounded,filled", fillcolor="{fill}", color="{pen}", fontsize=9];'
        )

    for i, (a, b, lbl) in enumerate(edges):
        if a not in by_id or b not in by_id:
            continue
        op_id = "edge_" + hashlib.sha256(f"{i}|{a}|{b}|{lbl}".encode()).hexdigest()[:12]
        lines.append(
            f'  "{op_id}" [label="{esc(lbl)}", shape=ellipse, style=filled, fillcolor="#FFFACD", color="#B8860B", fontsize=9];'
        )
        lines.append(f'  "{a}" -> "{op_id}";')
        lines.append(f'  "{op_id}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines)


def _semantic_html(nodes: list[SymbolChange], edges: list[tuple[str, str, str]], title: str) -> str:
    """Self-contained interactive HTML (Cytoscape via CDN) for semantic trace."""
    graph_nodes = [
        {
            "data": {
                "id": n.id,
                "label": n.qualname,
                "path": n.path,
                "status": n.status,
                "kind": n.kind,
                "calls": ", ".join(n.calls[:30]),
                "old_code": n.old_code,
                "new_code": n.new_code,
            }
        }
        for n in nodes
    ]
    graph_edges = [
        {
            "data": {
                "id": f"e{i}",
                "source": a,
                "target": b,
                "etype": t,
                "label": t,
            }
        }
        for i, (a, b, t) in enumerate(edges)
    ]
    payload = {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "title": title,
    }
    import json

    # Prevent breaking out of the inline <script> when code snippets contain "</script>"
    # in any casing (HTML parser treats end tags case-insensitively).
    data_json = re.sub(r"</script>", r"<\\/script>", json.dumps(payload), flags=re.IGNORECASE)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <script src="https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
  <style>
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }}
    #top {{ padding: 10px 12px; border-bottom: 1px solid #ddd; display: flex; gap: 8px; align-items: center; }}
    #layout {{ display: flex; flex-direction: row; align-items: stretch; height: calc(100vh - 52px); }}
    #cy-panel {{ flex: 0 0 45%; min-width: 180px; max-width: 85%; display: flex; flex-direction: column; min-height: 0; }}
    #cy {{ flex: 1; width: 100%; min-height: 0; }}
    #splitter {{ flex: 0 0 6px; width: 6px; cursor: col-resize; background: #e0e0e0; border-left: 1px solid #ccc; border-right: 1px solid #ccc; }}
    #splitter:hover {{ background: #c8c8c8; }}
    #right {{ flex: 1 1 auto; min-width: 200px; overflow: auto; padding: 10px; background: #fafafa; }}
    #details {{ margin-bottom: 10px; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 8px; font-size: 12px; }}
    .pill {{ padding: 4px 8px; border-radius: 999px; border: 1px solid #ccc; cursor: pointer; background:#fff; }}
    .symbol {{ background:#fff; border:1px solid #ddd; border-radius:8px; padding:8px; margin-bottom:8px; }}
    .hdr {{ font-weight:600; margin-bottom:6px; }}
    .meta {{ color:#555; font-size:12px; margin-bottom:6px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    pre {{ margin:0; white-space:pre-wrap; word-break:break-word; background:#f5f5f5; border:1px solid #e5e5e5; border-radius:6px; padding:8px; max-height:220px; overflow:auto; font-size:12px; }}
    .chg {{ background: #fff3cd; display:block; border-radius:3px; }}
    .tag {{ display:inline-block; padding:2px 6px; border-radius:999px; font-size:11px; margin-right:6px; border:1px solid #ccc; }}
  </style>
</head>
<body>
  <div id="top">
    <strong>{title}</strong>
    <input id="search" placeholder="Search symbol or file..." style="flex:1; padding:6px 8px;" />
    <button class="pill" data-filter="all">all</button>
    <button class="pill" data-filter="added">added</button>
    <button class="pill" data-filter="modified">modified</button>
    <button class="pill" data-filter="removed">removed</button>
  </div>
  <div id="layout">
    <div id="cy-panel">
      <div id="cy"></div>
    </div>
    <div id="splitter" role="separator" aria-orientation="vertical" title="Drag to resize panes"></div>
    <div id="right">
      <pre id="details">Click a node to focus graph. All changed code snippets are listed below.</pre>
      <div id="symbols"></div>
    </div>
  </div>
  <script>
    const data = {data_json};
    let activeFilter = 'all';
    let activeSearch = '';
    const symbolsWrap = document.getElementById('symbols');
    const details = document.getElementById('details');

    function esc(s) {{
      return (s || '')
        .replaceAll('&','&amp;')
        .replaceAll('<','&lt;')
        .replaceAll('>','&gt;')
        .replaceAll('"','&quot;')
        .replaceAll("'",'&#39;');
    }}

    function statusBadge(st) {{
      const color = st === 'added' ? '#2E7D32' : (st === 'modified' ? '#EF6C00' : '#C62828');
      return `<span class="tag" style="color:${{color}}; border-color:${{color}}">${{esc(st)}}</span>`;
    }}

    function matchNode(n) {{
      const d = n.data || n;
      if (activeFilter !== 'all' && d.status !== activeFilter) return false;
      if (!activeSearch) return true;
      const t = (`${{d.label}} ${{d.path}} ${{d.kind}} ${{d.calls || ''}}`).toLowerCase();
      return t.includes(activeSearch);
    }}

    function renderCodePair(oldCode, newCode) {{
      const oldLines = (oldCode || '').split('\\n');
      const newLines = (newCode || '').split('\\n');
      const n = Math.max(oldLines.length, newLines.length);
      let oldHtml = '';
      let newHtml = '';
      for (let i = 0; i < n; i++) {{
        const ol = oldLines[i] ?? '';
        const nl = newLines[i] ?? '';
        const changed = ol !== nl;
        oldHtml += changed ? `<span class="chg">${{esc(ol || ' ')}}</span>` : `${{esc(ol || ' ')}}`;
        newHtml += changed ? `<span class="chg">${{esc(nl || ' ')}}</span>` : `${{esc(nl || ' ')}}`;
        if (i !== n - 1) {{
          oldHtml += '\\n';
          newHtml += '\\n';
        }}
      }}
      return {{ oldHtml, newHtml }};
    }}

    function renderSymbolList() {{
      const rows = data.nodes.map(x => x.data).filter(matchNode);
      if (!rows.length) {{
        symbolsWrap.innerHTML = '<div class="symbol">No symbols match current filter.</div>';
        return;
      }}
      symbolsWrap.innerHTML = rows.map(d => {{
        const pair = renderCodePair(d.old_code || '', d.new_code || '');
        return `
        <div class="symbol" data-id="${{esc(d.id)}}">
          <div class="hdr">${{statusBadge(d.status)}} ${{esc(d.label)}}</div>
          <div class="meta">${{esc(d.path)}} · ${{esc(d.kind)}} · calls: ${{esc(d.calls || '-')}}</div>
          <div class="grid">
            <div>
              <div class="meta">old_code</div>
              <pre>${{pair.oldHtml}}</pre>
            </div>
            <div>
              <div class="meta">new_code</div>
              <pre>${{pair.newHtml}}</pre>
            </div>
          </div>
        </div>
      `; }}).join('');
    }}

    const cy = cytoscape({{
      container: document.getElementById('cy'),
      elements: [...data.nodes, ...data.edges],
      style: [
        {{ selector: 'node', style: {{
          'label': 'data(label)', 'font-size': 10, 'text-valign':'center', 'text-halign':'center',
          'shape':'round-rectangle', 'padding':'8px', 'border-width':1.5, 'background-color':'#E8F4FC', 'border-color':'#1565C0'
        }}}},
        {{ selector: 'node[status = "added"]', style: {{ 'background-color':'#E8F5E9', 'border-color':'#2E7D32' }} }},
        {{ selector: 'node[status = "modified"]', style: {{ 'background-color':'#FFF8E1', 'border-color':'#EF6C00' }} }},
        {{ selector: 'node[status = "removed"]', style: {{ 'background-color':'#FFEBEE', 'border-color':'#C62828' }} }},
        {{ selector: 'edge', style: {{
          'curve-style':'bezier', 'width':1.5, 'target-arrow-shape':'triangle', 'arrow-scale':0.8,
          'line-color':'#8D6E63', 'target-arrow-color':'#8D6E63', 'label':'data(label)', 'font-size':8
        }}}},
        {{ selector: '.dim', style: {{ 'opacity':0.12 }} }},
        {{ selector: '.hi', style: {{ 'opacity':1.0 }} }}
      ],
      layout: {{ name:'breadthfirst', directed:true, spacingFactor:1.05 }}
    }});

    function rotateGraph90() {{
      const nodes = cy.nodes();
      if (!nodes.length) return;
      let sx = 0, sy = 0;
      nodes.forEach(n => {{
        const p = n.position();
        sx += p.x;
        sy += p.y;
      }});
      const cx = sx / nodes.length;
      const cy0 = sy / nodes.length;
      nodes.forEach(n => {{
        const p = n.position();
        const dx = p.x - cx;
        const dy = p.y - cy0;
        // 90-degree rotation around centroid: (x, y) -> (-y, x)
        n.position({{ x: cx - dy, y: cy0 + dx }});
      }});
      cy.fit(undefined, 20);
    }}
    rotateGraph90();

    (function initSplitter() {{
      const layoutEl = document.getElementById('layout');
      const cyPanel = document.getElementById('cy-panel');
      const split = document.getElementById('splitter');
      let dragging = false;
      split.addEventListener('mousedown', (e) => {{
        dragging = true;
        e.preventDefault();
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      }});
      document.addEventListener('mousemove', (e) => {{
        if (!dragging) return;
        const rect = layoutEl.getBoundingClientRect();
        const x = e.clientX - rect.left;
        let pct = (x / rect.width) * 100;
        pct = Math.max(15, Math.min(85, pct));
        cyPanel.style.flex = '0 0 ' + pct + '%';
        cy.resize();
      }});
      document.addEventListener('mouseup', () => {{
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        cy.resize();
      }});
    }})();

    function applyGraphFilters() {{
      cy.elements().removeClass('dim').removeClass('hi');
      cy.nodes().forEach(n => {{
        const d = n.data();
        const ok = (activeFilter === 'all' || d.status === activeFilter) &&
                   (!activeSearch || (`${{d.label}} ${{d.path}} ${{d.kind}} ${{d.calls || ''}}`).toLowerCase().includes(activeSearch));
        if (!ok) n.addClass('dim');
      }});
      cy.edges().forEach(ed => {{
        if (ed.source().hasClass('dim') && ed.target().hasClass('dim')) ed.addClass('dim');
      }});
    }}

    cy.on('tap', 'node', (evt) => {{
      const d = evt.target.data();
      details.textContent = JSON.stringify(d, null, 2);
      cy.elements().addClass('dim').removeClass('hi');
      evt.target.removeClass('dim').addClass('hi');
      evt.target.connectedEdges().removeClass('dim').addClass('hi');
      evt.target.neighborhood().removeClass('dim').addClass('hi');
      const el = document.querySelector(`[data-id="${{CSS.escape(d.id)}}"]`);
      if (el) el.scrollIntoView({{ behavior:'smooth', block:'center' }});
    }});
    cy.on('tap', (evt) => {{
      if (evt.target === cy) {{
        applyGraphFilters();
      }}
    }});

    document.getElementById('search').addEventListener('input', (e) => {{
      activeSearch = e.target.value.toLowerCase().trim();
      applyGraphFilters();
      renderSymbolList();
    }});
    document.querySelectorAll('[data-filter]').forEach(btn => btn.addEventListener('click', () => {{
      activeFilter = btn.getAttribute('data-filter');
      applyGraphFilters();
      renderSymbolList();
    }}));

    renderSymbolList();
  </script>
</body>
</html>
"""


def run_solution_trace_git(
    *,
    ref: str = "HEAD",
    staged: bool = False,
    write_svg_relative: str | None = None,
    write_html_relative: str | None = None,
    write_svg_absolute: str | Path | None = None,
    serve_localhost: bool = False,
) -> dict[str, Any]:
    root = workspace_root()
    max_bytes = _env_bytes("RULE_BASED_SOLUTION_TRACE_MAX_BYTES", 2_000_000)
    max_hunks = _env_int("RULE_BASED_SOLUTION_TRACE_MAX_HUNKS", 500)

    diff_text, err = _git_diff(root, ref=ref, staged=staged)
    if err:
        return _error_payload(root, err)

    if diff_text is None:
        return _error_payload(root, "no diff output")

    truncated = False
    if len(diff_text) > max_bytes:
        diff_text = diff_text[:max_bytes]
        truncated = True

    hunks = parse_unified_diff(diff_text, max_hunks=max_hunks)
    if truncated:
        pass  # summary note below

    if not hunks:
        return {
            "tool": "solution_trace",
            "mode": "git",
            "workspace_root": str(root),
            "summary_lines": [
                "Solution trace (git): no hunks in diff (empty diff or parse miss).",
                f"  ref={'--cached' if staged else ref}",
            ],
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "dot_source": "digraph G { rankdir=LR; \"empty\" [label=\"no hunks\", shape=note]; }",
            "truncated": truncated,
        }

    chunks = _chunks_from_hunks(hunks)
    changed_py = {h.path for h in hunks if h.path.endswith(".py")}
    file_edges = build_import_edges(root, changed_py)
    hunk_edges = _map_file_edges_to_hunk_edges(file_edges, chunks)

    dot = dot_from_chunks_and_edges(chunks, hunk_edges)
    summary_lines = [
        f"Solution trace (git): {len(chunks)} hunks, {len(hunk_edges)} import edge(s)",
        f"  diff: {'staged vs HEAD' if staged else f'working tree vs {ref}'}",
    ]
    if truncated:
        summary_lines.append(f"  (diff truncated to {max_bytes} bytes)")
    for c in chunks[:20]:
        summary_lines.append(f"  [{c.kind}] {c.id}")
    if len(chunks) > 20:
        summary_lines.append(f"  … and {len(chunks) - 20} more hunks")

    out = _finalize_payload(
        root,
        chunks,
        hunk_edges,
        dot,
        summary_lines,
        write_svg_relative,
        write_html_relative,
        write_svg_absolute,
        serve_localhost,
        extra={"mode": "git", "ref": ref, "staged": staged, "truncated": truncated},
    )
    return out


def run_solution_semantic_trace_git(
    *,
    ref: str = "HEAD",
    staged: bool = False,
    write_svg_relative: str | None = None,
    write_html_relative: str | None = None,
    write_svg_absolute: str | Path | None = None,
    serve_localhost: bool = False,
) -> dict[str, Any]:
    """
    Python semantic trace from git changes:
    - nodes: added/removed/modified symbols (functions/classes/methods)
    - edges: best-effort static calls + import links between changed files
    """
    root = workspace_root()
    max_bytes = _env_bytes("RULE_BASED_SOLUTION_TRACE_MAX_BYTES", 2_000_000)
    max_hunks = _env_int("RULE_BASED_SOLUTION_TRACE_MAX_HUNKS", 500)

    diff_text, err = _git_diff(root, ref=ref, staged=staged)
    if err:
        return _error_payload(root, err)
    if diff_text is None:
        return _error_payload(root, "no diff output")
    if len(diff_text) > max_bytes:
        diff_text = diff_text[:max_bytes]

    hunks = parse_unified_diff(diff_text, max_hunks=max_hunks)
    changed_py = sorted({h.path for h in hunks if h.path.endswith(".py")})
    if not changed_py:
        return {
            "tool": "solution_semantic_trace",
            "mode": "git",
            "workspace_root": str(root),
            "summary_lines": ["Solution semantic trace: no changed Python files in diff."],
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "dot_source": 'digraph G { rankdir=LR; "empty" [label="no changed .py files", shape=note]; }',
        }

    nodes: list[SymbolChange] = []
    nodes_by_path: dict[str, list[SymbolChange]] = defaultdict(list)
    new_calls_by_id: dict[str, list[str]] = {}

    for rel in changed_py:
        old_spec = "HEAD" if staged else ref
        old_src = _git_show_text(root, old_spec, rel) or ""
        try:
            new_src = resolve_under_root(rel, root=root).read_text(encoding="utf-8", errors="replace")
        except OSError:
            new_src = ""

        old_syms = _symbols_from_source(old_src, rel)
        new_syms = _symbols_from_source(new_src, rel)
        quals = sorted(set(old_syms) | set(new_syms))
        for qn in quals:
            o = old_syms.get(qn)
            n = new_syms.get(qn)
            if o and not n:
                status = "removed"
                kind = o[0]
                calls = []
                old_code = o[3]
                new_code = ""
            elif n and not o:
                status = "added"
                kind = n[0]
                calls = n[2]
                old_code = ""
                new_code = n[3]
            else:
                assert o and n
                if o[1] == n[1]:
                    continue
                status = "modified"
                kind = n[0]
                calls = n[2]
                old_code = o[3]
                new_code = n[3]

            sid = f"sym:{rel}:{qn}"
            sc = SymbolChange(
                id=sid,
                path=rel,
                qualname=qn,
                kind=kind,
                status=status,
                calls=calls,
                old_code=old_code,
                new_code=new_code,
            )
            nodes.append(sc)
            nodes_by_path[rel].append(sc)
            new_calls_by_id[sid] = calls

    if not nodes:
        return {
            "tool": "solution_semantic_trace",
            "mode": "git",
            "workspace_root": str(root),
            "summary_lines": ["Solution semantic trace: no symbol-level AST changes detected."],
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "dot_source": 'digraph G { rankdir=LR; "empty" [label="no symbol changes", shape=note]; }',
        }

    # Symbol lookup for call edges (by bare function/method name).
    by_short: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        by_short[n.qualname.split(".")[-1]].append(n.id)

    edges: list[tuple[str, str, str]] = []
    for src_id, calls in new_calls_by_id.items():
        for cname in calls:
            for dst_id in by_short.get(cname, []):
                if src_id != dst_id:
                    edges.append((src_id, dst_id, "calls"))

    # Add import edges between changed files, mapped to first changed symbol per file.
    file_edges = build_import_edges(root, set(changed_py))
    for a_path, b_path in file_edges:
        a_nodes = nodes_by_path.get(a_path) or []
        b_nodes = nodes_by_path.get(b_path) or []
        if a_nodes and b_nodes:
            edges.append((a_nodes[0].id, b_nodes[0].id, "imports"))

    # Dedupe triples
    edges = list(dict.fromkeys(edges))
    dot = _semantic_dot(nodes, edges)
    summary_lines = [
        f"Solution semantic trace (git): {len(nodes)} changed symbol(s), {len(edges)} semantic edge(s)",
        f"  diff: {'staged vs HEAD' if staged else f'working tree vs {ref}'}",
    ]
    for n in nodes[:30]:
        summary_lines.append(f"  [{n.status}] {n.path} :: {n.qualname}")
    if len(nodes) > 30:
        summary_lines.append(f"  … and {len(nodes) - 30} more symbols")

    chunks = [
        ChunkNode(
            id=n.id,
            path=n.path,
            start_line=0,
            end_line=0,
            label=f"{n.status} {n.qualname}",
            kind="semantic",
        )
        for n in nodes
    ]
    out = _finalize_payload(
        root,
        chunks,
        [(a, b) for a, b, _lbl in edges],
        dot,
        summary_lines,
        write_svg_relative,
        None,
        write_svg_absolute,
        serve_localhost,
        extra={
            "tool": "solution_semantic_trace",
            "mode": "git",
            "ref": ref,
            "staged": staged,
            "semantic_nodes": [
                {
                    "id": n.id,
                    "path": n.path,
                    "qualname": n.qualname,
                    "kind": n.kind,
                    "status": n.status,
                    "calls": n.calls,
                    "old_code": n.old_code,
                    "new_code": n.new_code,
                }
                for n in nodes
            ],
            "semantic_edges": [{"from": a, "to": b, "type": t} for a, b, t in edges],
        },
    )
    if write_html_relative:
        try:
            html_path = resolve_under_root(write_html_relative, root)
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                _semantic_html(nodes, edges, "Solution Semantic Trace"),
                encoding="utf-8",
            )
            out["html_path"] = str(html_path)
        except (OSError, ValueError) as e:
            out["html_error"] = str(e)
    return out


def _error_payload(root: Path, msg: str) -> dict[str, Any]:
    return {
        "tool": "solution_trace",
        "workspace_root": str(root),
        "summary_lines": [f"Solution trace error: {msg}"],
        "node_count": 0,
        "edge_count": 0,
        "nodes": [],
        "edges": [],
        "dot_source": f'digraph G {{ rankdir=LR; "err" [label="{msg[:200]}", shape=note, color=red]; }}',
        "error": msg,
    }


def run_solution_trace_payload(
    payload: dict[str, Any],
    *,
    write_svg_relative: str | None = None,
    write_html_relative: str | None = None,
    write_svg_absolute: str | Path | None = None,
    serve_localhost: bool = False,
) -> dict[str, Any]:
    root = workspace_root()
    raw_chunks = payload.get("chunks")
    raw_edges = payload.get("edges")
    if not isinstance(raw_chunks, list):
        return _error_payload(root, "payload.chunks must be a list")
    chunks: list[ChunkNode] = []
    seen: set[str] = set()
    for i, ch in enumerate(raw_chunks):
        if not isinstance(ch, dict):
            return _error_payload(root, f"chunks[{i}] must be an object")
        cid = str(ch.get("id", "")).strip()
        path = str(ch.get("path", "")).strip()
        if not cid or not path:
            return _error_payload(root, f"chunks[{i}] needs id and path")
        try:
            sl = int(ch["start_line"])
            el = int(ch["end_line"])
        except (KeyError, TypeError, ValueError):
            return _error_payload(root, f"chunks[{i}] needs integer start_line and end_line")
        label = str(ch.get("label", path)).strip() or path
        if cid in seen:
            return _error_payload(root, f"duplicate chunk id: {cid}")
        seen.add(cid)
        try:
            resolve_under_root(path, root=root)
        except ValueError as e:
            return _error_payload(root, f"chunks[{i}] path: {e}")
        chunks.append(
            ChunkNode(
                id=cid,
                path=path,
                start_line=sl,
                end_line=el,
                label=label.replace('"', "'")[:500],
                kind="payload",
            )
        )

    edges: list[tuple[str, str]] = []
    if raw_edges is not None:
        if not isinstance(raw_edges, list):
            return _error_payload(root, "payload.edges must be a list or omitted")
        for j, ed in enumerate(raw_edges):
            if not isinstance(ed, dict):
                return _error_payload(root, f"edges[{j}] must be an object")
            a = str(ed.get("from_id", "")).strip()
            b = str(ed.get("to_id", "")).strip()
            if not a or not b:
                return _error_payload(root, f"edges[{j}] needs from_id and to_id")
            if a not in seen or b not in seen:
                return _error_payload(root, f"edges[{j}] unknown from_id or to_id")
            edges.append((a, b))
    edges = list(dict.fromkeys(edges))

    dot = dot_from_chunks_and_edges(chunks, edges)
    summary_lines = [
        f"Solution trace (payload): {len(chunks)} chunk(s), {len(edges)} edge(s)",
    ]
    for c in chunks[:30]:
        summary_lines.append(f"  [payload] {c.id}")
    if len(chunks) > 30:
        summary_lines.append(f"  … and {len(chunks) - 30} more")

    return _finalize_payload(
        root,
        chunks,
        edges,
        dot,
        summary_lines,
        write_svg_relative,
        write_html_relative,
        write_svg_absolute,
        serve_localhost,
        extra={"mode": "payload"},
    )


def _finalize_payload(
    root: Path,
    chunks: list[ChunkNode],
    edges: list[tuple[str, str]],
    dot: str,
    summary_lines: list[str],
    write_svg_relative: str | None,
    write_html_relative: str | None,
    write_svg_absolute: str | Path | None,
    serve_localhost: bool,
    extra: dict[str, Any],
) -> dict[str, Any]:
    svg_path: str | None = None
    svg_error: str | None = None
    html_path: str | None = None
    html_error: str | None = None

    out_path: Path | None = None
    html_out_path: Path | None = None
    if write_svg_absolute is not None:
        out_path = Path(write_svg_absolute).expanduser().resolve()
    elif write_svg_relative:
        try:
            out_path = resolve_under_root(write_svg_relative, root)
        except ValueError as e:
            svg_error = str(e)
            out_path = None
    if write_html_relative:
        try:
            html_out_path = resolve_under_root(write_html_relative, root)
        except ValueError as e:
            html_error = str(e)
            html_out_path = None

    need_svg = (out_path is not None) or (html_out_path is not None)
    svg_bytes: bytes | None = None
    svg_render_err: str | None = None
    if need_svg:
        svg_bytes, svg_render_err = _render_svg_bytes(dot)
        if svg_render_err and svg_bytes is None and not svg_error:
            svg_error = svg_render_err

    if out_path is not None:
        if svg_bytes is not None:
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(svg_bytes)
                svg_path = str(out_path)
            except OSError as e:
                svg_error = str(e)
        elif not svg_error:
            svg_error = svg_render_err or "failed to render SVG"

    if html_out_path is not None:
        if svg_bytes is not None:
            try:
                html_out_path.parent.mkdir(parents=True, exist_ok=True)
                svg_text = svg_bytes.decode("utf-8", errors="replace")
                html_out_path.write_text(_svg_preview_html_page(svg_text), encoding="utf-8")
                html_path = str(html_out_path)
            except OSError as e:
                html_error = str(e)
        elif not html_error:
            html_error = svg_render_err or svg_error or "failed to render HTML (SVG unavailable)"

    nodes = [
        {
            "id": c.id,
            "path": c.path,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "kind": c.kind,
        }
        for c in chunks
    ]
    edge_objs = [{"from": a, "to": b} for a, b in edges]

    out: dict[str, Any] = {
        "tool": "solution_trace",
        "workspace_root": str(root),
        "node_count": len(chunks),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edge_objs,
        "dot_source": dot,
        "summary_lines": summary_lines,
        **extra,
    }
    if svg_path:
        out["svg_path"] = svg_path
        svg_uri = _host_file_uri(svg_path, root)
        if svg_uri:
            out["svg_uri"] = svg_uri
    if svg_error:
        out["svg_error"] = svg_error
    if html_path:
        out["html_path"] = html_path
        html_uri = _host_file_uri(html_path, root)
        if html_uri:
            out["html_uri"] = html_uri
    if html_error:
        out["html_error"] = html_error
    return out
