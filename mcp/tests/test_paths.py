import os
from pathlib import Path

import pytest

from rule_based_verifier.paths import resolve_under_root, workspace_root


def test_workspace_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULE_BASED_WORKSPACE_ROOT", str(tmp_path))
    assert workspace_root() == tmp_path.resolve()


def test_resolve_under_root_ok(tmp_path: Path) -> None:
    f = tmp_path / "a" / "b.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x", encoding="utf-8")
    got = resolve_under_root("a/b.txt", root=tmp_path)
    assert got == f.resolve()


def test_resolve_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_under_root("../outside", root=tmp_path)


def test_resolve_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_under_root(str(tmp_path / "x"), root=tmp_path)
