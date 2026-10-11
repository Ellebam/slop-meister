"""Import rules. Without them the package grows cycles, reaches into tests, or launches scripts."""

from pathlib import Path

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.quality import imports, inventory
from tests.support.trees import write


def violations(root: Path) -> list[tuple[str, str]]:
    found = imports.import_violations(inventory.sources(root), root)
    return sorted((v.metric, v.path) for v in found)


@pytest.mark.parametrize("prefix", ("slopmeister", "."))
def test_cycle_between_two_modules_is_reported(tmp_path: Path, prefix: str) -> None:
    write(tmp_path, "slopmeister/a.py", f"from {prefix} import b\n")
    write(tmp_path, "slopmeister/b.py", f"from {prefix} import a\n")
    assert ("import_cycle", "slopmeister.a") in violations(tmp_path)


def test_package_importing_tests_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "slopmeister/a.py", "from tests.support import trees\n")
    assert violations(tmp_path) == [("import_direction", "slopmeister.a")]


@pytest.mark.parametrize("prefix", ("slopmeister.", ".."))
def test_session_subpackage_may_import_only_itself(tmp_path: Path, prefix: str) -> None:
    write(tmp_path, "slopmeister/session/x.py", "from slopmeister.session import y\nimport json\n")
    write(tmp_path, "slopmeister/session/y.py", f"from {prefix}paths import ROOT\n")
    write(tmp_path, "slopmeister/paths.py", "ROOT = 1\n")
    assert violations(tmp_path) == [("session_self_contained", "slopmeister.session.y")]


@pytest.mark.parametrize("prefix", ("slopmeister.", "..."))
def test_vault_runtime_may_import_only_itself(tmp_path: Path, prefix: str) -> None:
    write(tmp_path, "slopmeister/vault/runtime/x.py", "from slopmeister.vault.runtime import y\n")
    write(tmp_path, "slopmeister/vault/runtime/y.py", f"from {prefix}paths import ROOT\n")
    write(tmp_path, "slopmeister/paths.py", "ROOT = 1\n")
    assert violations(tmp_path) == [("vault_runtime_self_contained", "slopmeister.vault.runtime.y")]


def test_launching_a_script_by_path_is_a_runtime_edge(tmp_path: Path) -> None:
    write(
        tmp_path,
        "slopmeister/a.py",
        'import subprocess\nsubprocess.run(["python3", "scripts/x.py"])\n',
    )
    write(tmp_path, "slopmeister/b.py", "import runpy\nrunpy.run_path('x')\n")
    assert violations(tmp_path) == [
        ("runtime_edge", "slopmeister/a.py"),
        ("runtime_edge", "slopmeister/b.py"),
    ]


def test_tests_may_import_the_package(tmp_path: Path) -> None:
    write(tmp_path, "slopmeister/a.py", "X = 1\n")
    write(tmp_path, "tests/unit/test_a.py", "from slopmeister.a import X\n")
    assert violations(tmp_path) == []


def test_relative_imports_use_the_initializer_package_and_the_module_parent(tmp_path: Path):
    write(tmp_path, "slopmeister/session/__init__.py", "from .entry import run\n")
    write(tmp_path, "slopmeister/session/entry.py", "from . import common\n")
    write(tmp_path, "slopmeister/session/common.py", "run = 1\n")
    edges = imports.graph(inventory.sources(tmp_path), tmp_path)
    assert edges["slopmeister.session"] == ["slopmeister.session.entry"]
    assert edges["slopmeister.session.entry"] == ["slopmeister.session.common"]
    assert violations(tmp_path) == []


def test_over_deep_relative_import_has_a_module_diagnostic(tmp_path: Path):
    write(tmp_path, "slopmeister/session/x.py", "from ... import paths\n")
    with pytest.raises(SlopmeisterError, match="slopmeister.session.x.*beyond top-level"):
        violations(tmp_path)


@pytest.mark.parametrize(
    "subtree, sibling, metric",
    (
        ("session", "session_extra", "session_self_contained"),
        ("vault/runtime", "vault.runtime_extra", "vault_runtime_self_contained"),
    ),
)
def test_snapshot_boundary_does_not_include_a_sibling_prefix(
    tmp_path: Path, subtree: str, sibling: str, metric: str
):
    target = sibling.rsplit(".", 1)[-1]
    write(tmp_path, f"slopmeister/{subtree}/x.py", f"from ..{target} import Z\n")
    write(tmp_path, f"slopmeister/{sibling.replace('.', '/')}.py", "Z = 1\n")
    assert violations(tmp_path) == [(metric, "slopmeister." + subtree.replace("/", ".") + ".x")]
