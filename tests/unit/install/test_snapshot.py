"""A snapshot drifting from its manifest, or an entry bound to the checkout, ships silently."""

import json
import os
from pathlib import Path

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.install import snapshot
from slopmeister.install.entries import entry_text
from tests.support.trees import write


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    write(root, "slopmeister/__init__.py", "")
    write(root, "slopmeister/session/__init__.py", "")
    write(root, "slopmeister/session/ship.py", "def main(argv):\n    return 0\n")
    write(root, "slopmeister/session/threads/__init__.py", "")
    write(root, "slopmeister/session/threads/cli.py", "def main(argv):\n    return 0\n")
    write(root, "slopmeister/session/__pycache__/ship.cpython-314.pyc", "junk")
    write(root, "slopmeister/render/build.py", "never delivered\n")
    return root


def test_snapshot_holds_the_session_subpackage_and_verifies(checkout: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    written = snapshot.write(checkout, state_dir)
    manifest = json.loads((written / snapshot.MANIFEST).read_text())
    assert sorted(manifest) == [
        "slopmeister/__init__.py",
        "slopmeister/session/__init__.py",
        "slopmeister/session/ship.py",
        "slopmeister/session/threads/__init__.py",
        "slopmeister/session/threads/cli.py",
    ]
    assert snapshot.verify(state_dir) == written
    assert oct(os.stat(written / "slopmeister/session/ship.py").st_mode & 0o777) == "0o644"


def test_one_changed_byte_anywhere_fails_verification(checkout: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    written = snapshot.write(checkout, state_dir)
    for relative in json.loads((written / snapshot.MANIFEST).read_text()):
        path = written / relative
        original = path.read_bytes()
        path.write_bytes(original + b"#")
        with pytest.raises(SlopmeisterError, match="changed since preparation"):
            snapshot.verify(state_dir)
        path.write_bytes(original)
    snapshot.verify(state_dir)


@pytest.mark.parametrize("change", ["added", "removed", "symlink", "manifest"])
def test_added_removed_or_linked_files_fail_verification(
    checkout: Path, tmp_path: Path, change: str
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    written = snapshot.write(checkout, state_dir)
    if change == "added":
        write(written, "slopmeister/session/extra.py", "")
    elif change == "removed":
        (written / "slopmeister/session/ship.py").unlink()
    elif change == "symlink":
        (written / "slopmeister/session/ship.py").unlink()
        (written / "slopmeister/session/ship.py").symlink_to(
            checkout / "slopmeister/session/ship.py"
        )
    else:
        (written / snapshot.MANIFEST).unlink()
    with pytest.raises(SlopmeisterError):
        snapshot.verify(state_dir)


def test_bake_binds_every_delivered_entry_and_leaves_other_files(tmp_path: Path) -> None:
    files = {
        ".claude/skills/ship/scripts/ship.py": (b"legacy", 0o555),
        ".agents/skills/vault-todos/scripts/vault_todos.py": (b"legacy", 0o555),
        ".claude/skills/ship/SKILL.md": (b"prose", 0o444),
        "AGENTS.md": (b"prose", 0o644),
    }
    snapshot.bake(files, tmp_path / "snapshot")
    assert files[".claude/skills/ship/SKILL.md"] == (b"prose", 0o444)
    assert files["AGENTS.md"] == (b"prose", 0o644)
    expected = entry_text("slopmeister.session.ship", tmp_path / "snapshot").encode()
    assert files[".claude/skills/ship/scripts/ship.py"] == (expected, 0o555)
    assert str(tmp_path / "snapshot").encode() in files[".claude/skills/ship/scripts/ship.py"][0]
    assert snapshot.program(".agents/skills/ship/scripts/ship.py") == "slopmeister.session.ship"
    assert snapshot.program(".agents/skills/sow/SKILL.md") is None


def test_state_entries_are_private_and_bound(tmp_path: Path) -> None:
    digests = snapshot.state_entries(tmp_path, tmp_path / "snapshot")
    assert sorted(digests) == ["config-install.py"]
    helper = tmp_path / "config-install.py"
    assert oct(helper.stat().st_mode & 0o777) == "0o700"
    assert helper.read_text() == entry_text("slopmeister.session.verify", tmp_path / "snapshot")


def test_manifest_rewritten_with_a_module_is_refused_by_the_saved_record(
    checkout: Path, tmp_path: Path
) -> None:
    """Escaping bug: a module and its manifest rewritten together agree with each other."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    written = snapshot.write(checkout, state_dir)
    recorded = snapshot.digest(written / snapshot.MANIFEST)
    module = written / "slopmeister/session/ship.py"
    module.write_text("def main(argv):\n    return 1\n")
    manifest = json.loads((written / snapshot.MANIFEST).read_text())
    manifest["slopmeister/session/ship.py"] = snapshot.digest(module)
    (written / snapshot.MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    assert snapshot.verify(state_dir) == written
    with pytest.raises(SlopmeisterError, match="differs from the saved record"):
        snapshot.verify(state_dir, recorded)
