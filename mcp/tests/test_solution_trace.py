"""Tests for solution trace (unified diff parse, import edges, payload)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rule_based_verifier.solution_trace import (
    SymbolChange,
    _semantic_html,
    build_import_edges,
    dot_from_chunks_and_edges,
    parse_unified_diff,
    run_solution_semantic_trace_git,
    run_solution_trace_git,
    run_solution_trace_payload,
)
from rule_based_verifier.solution_trace import ChunkNode


SAMPLE_DIFF = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def x():
     pass
+    return 1
"""


def test_parse_unified_diff_one_hunk() -> None:
    hunks = parse_unified_diff(SAMPLE_DIFF)
    assert len(hunks) == 1
    assert hunks[0].path == "foo.py"
    assert hunks[0].new_start == 1
    assert hunks[0].new_len >= 1


def test_parse_unified_diff_two_hunks() -> None:
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,2 @@
 a
+b
@@ -10,1 +11,2 @@
 c
+d
"""
    hunks = parse_unified_diff(diff)
    assert len(hunks) == 2


def test_build_import_edges_python(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("import b\n", encoding="utf-8")
    b.write_text("x = 1\n", encoding="utf-8")
    changed = {"a.py", "b.py"}
    edges = build_import_edges(tmp_path, changed)
    assert ("a.py", "b.py") in edges


def test_dot_from_chunks() -> None:
    chunks = [
        ChunkNode(id="a:1-2", path="a.py", start_line=1, end_line=2, label="a", kind="hunk"),
        ChunkNode(id="b:1-1", path="b.py", start_line=1, end_line=1, label="b", kind="hunk"),
    ]
    dot = dot_from_chunks_and_edges(chunks, [("a:1-2", "b:1-1")])
    assert "digraph G" in dot
    assert "a:1-2" in dot
    assert "->" in dot
    assert "imports" in dot
    assert "ellipse" in dot


def test_run_solution_trace_payload_validates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    f = tmp_path / "x.py"
    f.write_text("# x\n", encoding="utf-8")
    payload = {
        "chunks": [
            {"id": "c1", "path": "x.py", "start_line": 1, "end_line": 1, "label": "x"},
        ],
        "edges": [],
    }
    out = run_solution_trace_payload(payload, serve_localhost=False)
    assert out["node_count"] == 1
    assert out["nodes"][0]["id"] == "c1"


def test_run_solution_trace_git_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "m"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.txt").write_text("a\nb\n", encoding="utf-8")
    out = run_solution_trace_git(ref="HEAD", staged=False, serve_localhost=False)
    assert out.get("node_count", 0) >= 1
    assert "dot_source" in out


def test_run_solution_trace_git_writes_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.py").write_text("x=1\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "m"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.py").write_text("x=2\n", encoding="utf-8")
    out = run_solution_trace_git(
        ref="HEAD",
        staged=False,
        write_html_relative="solution_trace.html",
        serve_localhost=False,
    )
    assert out.get("html_path")
    html_path = Path(out["html_path"])
    assert html_path.exists()
    text = html_path.read_text(encoding="utf-8")
    assert "<svg " in text


def test_run_solution_trace_git_not_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    out = run_solution_trace_git(ref="HEAD", staged=False, serve_localhost=False)
    assert out.get("error") or any("git" in (s or "").lower() for s in out.get("summary_lines", []))


def test_payload_json_invalid_edge_unknown_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    out = run_solution_trace_payload(
        {
            "chunks": [{"id": "c1", "path": "a.py", "start_line": 1, "end_line": 1}],
            "edges": [{"from_id": "c1", "to_id": "missing"}],
        },
        serve_localhost=False,
    )
    assert "error" in out


def test_run_solution_semantic_trace_git_detects_symbol_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    out = run_solution_semantic_trace_git(ref="HEAD", staged=False, serve_localhost=False)
    assert out["tool"] == "solution_semantic_trace"
    assert out["node_count"] >= 1
    assert any(n["status"] in {"modified", "added", "removed"} for n in out["semantic_nodes"])
    sample = out["semantic_nodes"][0]
    assert "old_code" in sample
    assert "new_code" in sample


def test_run_solution_semantic_trace_git_call_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.py").write_text("def g():\n    return 1\n\ndef f():\n    return g()\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.py").write_text(
        "def g():\n    return 2\n\ndef f():\n    x = g()\n    return x\n", encoding="utf-8"
    )
    out = run_solution_semantic_trace_git(ref="HEAD", staged=False, serve_localhost=False)
    assert out["node_count"] >= 1
    # best-effort static calls should include at least one calls edge in this file
    assert any(e.get("type") == "calls" for e in out.get("semantic_edges", []))


def test_run_solution_semantic_trace_git_writes_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "x.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "x.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "x.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    out = run_solution_semantic_trace_git(
        ref="HEAD",
        staged=False,
        write_html_relative="solution_semantic_trace.html",
        serve_localhost=False,
    )
    assert out.get("html_path")
    html_path = Path(out["html_path"])
    assert html_path.exists()
    text = html_path.read_text(encoding="utf-8")
    assert "cytoscape" in text


def test_semantic_html_escapes_script_terminator() -> None:
    nodes = [
        SymbolChange(
            id="sym:x:f",
            path="x.py",
            qualname="f",
            kind="function",
            status="modified",
            calls=[],
            old_code="",
            new_code='s = "</script>"',
        )
    ]
    html = _semantic_html(nodes, [], "t")
    assert "<\\/script>" in html
    assert "</script>" in html  # expected for real script tags


def test_semantic_html_escapes_script_terminator_case_insensitive() -> None:
    nodes = [
        SymbolChange(
            id="sym:x:f",
            path="x.py",
            qualname="f",
            kind="function",
            status="modified",
            calls=[],
            old_code="",
            new_code='s = "</ScRiPt>"',
        )
    ]
    html = _semantic_html(nodes, [], "t")
    assert "</ScRiPt>" not in html
    assert "<\\/script>" in html


def test_semantic_html_esc_includes_quote_escaping() -> None:
    html = _semantic_html([], [], "t")
    assert ".replaceAll('\"','&quot;')" in html
    assert ".replaceAll(\"'\",'&#39;')" in html
