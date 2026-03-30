"""
Gradient checks for ``examples/micrograd_value.py`` against finite-difference (numerical) derivatives.

Loads the example module by path so it does not need to be installed as a package.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "micrograd_value.py"
assert _EXAMPLES.is_file(), f"missing {_EXAMPLES}"

_spec = importlib.util.spec_from_file_location("micrograd_value", _EXAMPLES)
assert _spec and _spec.loader
mg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mg)

Value = mg.Value


def _central_partial(
    forward,
    xs: tuple[float, ...],
    i: int,
    eps: float = 1e-5,
) -> float:
    """∂/∂x_i of scalar forward(*xs) via symmetric difference."""
    x = list(xs)
    x[i] += eps
    f_plus = forward(*x)
    x[i] -= 2.0 * eps
    f_minus = forward(*x)
    return (f_plus - f_minus) / (2.0 * eps)


def _assert_close(a: float, b: float, *, rtol: float = 1e-4, atol: float = 1e-6) -> None:
    assert math.isclose(a, b, rel_tol=rtol, abs_tol=atol), f"{a!r} vs {b!r}"


def test_tanh_mul_add_matches_numerical() -> None:
    def forward(a: float, b: float, c: float) -> float:
        va = Value(a)
        vb = Value(b)
        vc = Value(c)
        return (va * vb + vc).tanh().data

    a, b, c = 2.0, -3.0, 10.0
    out = forward(a, b, c)
    assert math.isclose(out, math.tanh(a * b + c))

    va = Value(a)
    vb = Value(b)
    vc = Value(c)
    y = (va * vb + vc).tanh()
    y.backward()

    for i, v in enumerate((a, b, c)):
        num = _central_partial(forward, (a, b, c), i)
        ana = (va.grad, vb.grad, vc.grad)[i]
        _assert_close(ana, num)


def test_pow_and_div_matches_numerical() -> None:
    def forward(x: float, y: float) -> float:
        vx = Value(x)
        vy = Value(y)
        return (vx**2 + vy**3 / Value(1.0)).data

    x, y = 1.5, -0.7
    vx = Value(x)
    vy = Value(y)
    z = vx**2 + vy**3 / Value(1.0)
    z.backward()

    for i, v in enumerate((x, y)):
        num = _central_partial(forward, (x, y), i)
        ana = (vx.grad, vy.grad)[i]
        _assert_close(ana, num)


def test_same_leaf_used_twice_mul() -> None:
    """d/da (a*a) = 2a — graph uses one leaf twice; backward must accumulate."""
    a = Value(3.0)
    out = a * a
    out.backward()
    _assert_close(a.grad, 6.0)


def test_same_leaf_used_twice_add() -> None:
    """d/da (a + a) = 2 when a is the same Value twice."""
    a = Value(4.0)
    s = a + a
    s.backward()
    _assert_close(a.grad, 2.0)


def test_backward_repeatable_after_reset_grads() -> None:
    """Calling backward() twice without zeroing intermediates is wrong: ``out.grad`` accumulates.

    Real micrograd usage: zero all ``Value.grad`` in the graph before a second backward.
    """
    a = Value(2.0)
    y = (a * 3.0).tanh()
    y.backward()
    g1 = a.grad

    mg.zero_grad(y)
    y.backward()
    g2 = a.grad
    assert g2 == pytest.approx(g1)


def test_division_chain() -> None:
    def forward(x: float) -> float:
        v = Value(x)
        return (v / (v + Value(1.0))).data

    x = 0.7
    vx = Value(x)
    out = vx / (vx + Value(1.0))
    out.backward()
    num = _central_partial(forward, (x,), 0)
    _assert_close(vx.grad, num)


def test_trace_includes_all_nodes() -> None:
    a = Value(1.0)
    b = Value(2.0)
    y = a * b + a
    nodes, edges = mg.trace(y)
    assert len(nodes) >= 4


def test_dot_source_is_valid_when_dot_available() -> None:
    import shutil

    if not shutil.which("dot"):
        pytest.skip("Graphviz dot not on PATH")

    a = Value(1.0)
    b = Value(2.0)
    y = (a * b).tanh()
    y.backward()
    src = mg.dot_source(y)
    assert "digraph" in src
    assert str(id(a)) in src or str(id(b)) in src
