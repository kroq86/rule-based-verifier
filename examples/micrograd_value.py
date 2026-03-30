"""
Minimal autograd (micrograd-style) with fixed graph visualization.

**PyPI** ``graphviz`` (``pip install graphviz``) is optional: it is only the Python binding, not the
same as ``brew install graphviz`` (which installs the ``dot`` binary). If the PyPI package is
missing, :func:`render_svg` still works by invoking ``dot -Tsvg`` when ``dot`` is on ``PATH``.

Notebook reference: .ipynb_checkpoints/25-checkpoint.ipynb — graph + backward were incomplete.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Set, Tuple, Union

try:
    from graphviz import Digraph
except ImportError:  # pragma: no cover - optional viz
    Digraph = None  # type: ignore[misc, assignment]


def _as_value(x: Any) -> "Value":
    return x if isinstance(x, Value) else Value(x)


class Value:
    """Scalar value with automatic differentiation."""

    __slots__ = ("data", "grad", "_backward", "_prev", "_op")

    def __init__(self, data: float, _children: Tuple["Value", ...] = (), _op: str = "") -> None:
        self.data = float(data)
        self.grad = 0.0
        self._backward: Callable[[], None] = lambda: None
        self._prev: Set[Value] = set(_children)
        self._op = _op

    def __repr__(self) -> str:
        return f"Value(data={self.data})"

    def backward(self) -> None:
        """Backpropagate from this scalar. Accumulates ``grad``; call :func:`zero_grad` before a new step."""
        topo: list[Value] = []
        visited: Set[Value] = set()

        def build_topo(v: Value) -> None:
            if v not in visited:
                visited.add(v)
                for ch in v._prev:
                    build_topo(ch)
                topo.append(v)

        build_topo(self)
        self.grad = 1.0
        for v in reversed(topo):
            v._backward()

    # --- ops ---

    def __add__(self, other: Any) -> "Value":
        other = _as_value(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward() -> None:
            self.grad += out.grad
            other.grad += out.grad

        out._backward = _backward
        return out

    def __mul__(self, other: Any) -> "Value":
        other = _as_value(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward() -> None:
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad

        out._backward = _backward
        return out

    def __neg__(self) -> "Value":
        return self * -1

    def __sub__(self, other: Any) -> "Value":
        return self + (-_as_value(other))

    def __pow__(self, other: Any) -> "Value":
        if not isinstance(other, (int, float)):
            return NotImplemented
        out = Value(self.data ** float(other), (self,), f"**{other}")

        def _backward() -> None:
            self.grad += float(other) * (self.data ** (float(other) - 1.0)) * out.grad

        out._backward = _backward
        return out

    def __truediv__(self, other: Any) -> "Value":
        return self * _as_value(other) ** -1

    def __radd__(self, other: Any) -> "Value":
        return _as_value(other) + self

    def __rmul__(self, other: Any) -> "Value":
        return _as_value(other) * self

    def __rsub__(self, other: Any) -> "Value":
        return _as_value(other) - self

    def __rtruediv__(self, other: Any) -> "Value":
        return _as_value(other) / self

    def tanh(self) -> "Value":
        t = math.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward() -> None:
            self.grad += (1.0 - t * t) * out.grad

        out._backward = _backward
        return out


def trace(root: Value) -> Tuple[Set[Value], Set[Tuple[Value, Value]]]:
    nodes: Set[Value] = set()
    edges: Set[Tuple[Value, Value]] = set()

    def build(v: Value) -> None:
        if v not in nodes:
            nodes.add(v)
            for ch in v._prev:
                edges.add((ch, v))
                build(ch)

    build(root)
    return nodes, edges


def zero_grad(root: Value) -> None:
    """Set ``grad`` to 0 for every :class:`Value` reachable from ``root`` (before another ``backward``)."""
    nodes, _ = trace(root)
    for n in nodes:
        n.grad = 0.0


def _dot_quote(s: str) -> str:
    """Escape for double-quoted DOT strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _value_html_label(n: Value) -> str:
    """HTML-like label so **data** and **grad** always show in SVG (plain ``record`` is easy to miss)."""
    return (
        "<<TABLE BORDER=\"1\" CELLBORDER=\"1\" CELLSPACING=\"0\" CELLPADDING=\"3\" "
        'STYLE="ROUNDED">'
        f"<TR><TD BGCOLOR=\"#eeeeee\">data</TD><TD>{n.data:.4f}</TD></TR>"
        f"<TR><TD BGCOLOR=\"#e8f4e8\">grad</TD><TD>{n.grad:.4f}</TD></TR>"
        "</TABLE>>"
    )


def dot_source(root: Value, *, rankdir: str = "LR") -> str:
    """Same topology as :func:`draw_dot`, as a Graphviz DOT string (no PyPI ``graphviz`` needed)."""
    lines = [f"digraph G {{", f'  graph [rankdir="{_dot_quote(rankdir)}"];']
    nodes, edges = trace(root)

    for n in nodes:
        uid = str(id(n))
        lines.append(f'  "{uid}" [label={_value_html_label(n)}, shape=plain];')
        if n._op:
            op_id = uid + n._op
            lines.append(f'  "{op_id}" [label="{_dot_quote(n._op)}"];')
            lines.append(f'  "{op_id}" -> "{uid}";')

    for n1, n2 in edges:
        lines.append(f'  "{id(n1)}" -> "{id(n2)}{n2._op}";')

    lines.append("}")
    return "\n".join(lines)


def draw_dot(root: Value, *, rankdir: str = "LR") -> "Digraph":
    """Render computation graph. Fixed: op nodes are unique; edges child -> op -> parent."""
    if Digraph is None:  # pragma: no cover
        raise ImportError("graphviz package not installed (pip install graphviz)")

    dot = Digraph(format="svg", graph_attr={"rankdir": rankdir})
    nodes, edges = trace(root)

    for n in nodes:
        uid = str(id(n))
        dot.node(
            name=uid,
            label=_value_html_label(n),
            shape="plain",
        )
        if n._op:
            op_id = uid + n._op
            dot.node(name=op_id, label=n._op)
            dot.edge(op_id, uid)

    for n1, n2 in edges:
        # n1 -> op that produced n2
        dot.edge(str(id(n1)), str(id(n2)) + n2._op)

    return dot


def render_svg(root: Value, path: Union[str, Path], *, rankdir: str = "LR") -> Path:
    """Write the computation graph as an SVG file.

    Uses the PyPI ``graphviz`` package if installed (``dot.pipe``). Otherwise calls the
    system ``dot`` executable (e.g. from Homebrew) with DOT from :func:`dot_source`.
    """
    out = Path(path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if Digraph is not None:
        dot = draw_dot(root, rankdir=rankdir)
        out.write_bytes(dot.pipe(format="svg"))
        return out

    dot_bin = shutil.which("dot")
    if dot_bin is None:
        raise ImportError(
            "Cannot render SVG: install PyPI package `graphviz` (pip install graphviz) "
            "or install Graphviz so `dot` is on PATH (e.g. brew install graphviz)."
        )

    src = dot_source(root, rankdir=rankdir)
    subprocess.run(
        [dot_bin, "-Tsvg", "-o", str(out)],
        input=src,
        text=True,
        check=True,
    )
    return out


def _demo() -> None:
    a = Value(2.0)
    b = Value(-3.0)
    c = Value(10.0)
    d = a * b + c
    e = d.tanh()
    e.backward()

    print("e = tanh(a*b + c)", e.data)
    print("grad a,b,c:", a.grad, b.grad, c.grad)

    svg_path = Path(__file__).resolve().parent / "micrograd_graph.svg"
    try:
        render_svg(e, svg_path)
        print("Wrote", svg_path)  # noqa: T201
    except (ImportError, OSError, subprocess.CalledProcessError) as err:
        print("Could not write SVG:", err)  # noqa: T201


if __name__ == "__main__":
    _demo()
