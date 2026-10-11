"""Bounded Obsidian CLI execution for every supplied command."""

import os
from pathlib import Path
import subprocess

from tests.support.fakes import fake_binary

ROOT = Path(__file__).resolve().parents[3]
COMMAND = [str(ROOT / "bin/slopmeister"), "vault", "obsidian", "--"]


def run(tmp_path: Path, *args: str, timeout: str = "2") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [*COMMAND, *args],
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "SLOPMEISTER_OBSIDIAN_TIMEOUT": timeout,
        },
        capture_output=True,
    )


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_obsidian_boundary_preserves_output_and_exit_status(tmp_path: Path) -> None:
    fake_binary(
        tmp_path / "bin",
        "obsidian",
        "printf 'exact output\\n'; printf 'exact error\\n' >&2; exit 7",
    )
    result = run(tmp_path, "vault=obsidian", "search", "query=term")
    assert result.returncode == 7
    assert result.stdout == b"exact output\n" and result.stderr == b"exact error\n"


def test_obsidian_boundary_kills_ignored_parent_and_child_on_timeout(tmp_path: Path) -> None:
    parent, child = tmp_path / "parent.pid", tmp_path / "child.pid"
    fake_binary(
        tmp_path / "bin",
        "obsidian",
        f"""trap '' TERM
echo $$ > {parent!s}
bash -c 'trap "" TERM; echo $$ > {child!s}; while :; do sleep 1; done' &
wait""",
    )
    result = run(tmp_path, "vault=obsidian", "search", "query=term", timeout="5")
    assert result.returncode == 124
    assert parent.is_file() and child.is_file()
    assert not alive(int(parent.read_text())) and not alive(int(child.read_text()))


def test_obsidian_boundary_rejects_invalid_timeout_before_launch(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    fake_binary(tmp_path / "bin", "obsidian", f"touch {marker!s}")
    result = run(tmp_path, "vault=obsidian", "search", "query=term", timeout="0")
    assert result.returncode == 2 and b"positive whole seconds" in result.stderr
    assert not marker.exists()


def test_obsidian_boundary_refuses_write_operations_before_launch(tmp_path: Path) -> None:
    marker = tmp_path / "called"
    fake_binary(tmp_path / "bin", "obsidian", f"touch {marker!s}")
    for operation in ("append", "create", "delete", "rename", "move"):
        result = run(tmp_path, "vault=obsidian", operation, "path=note.md")
        assert result.returncode == 2 and b"not read-only" in result.stderr
    trailing = run(tmp_path, "vault=obsidian", "search", "query=term", "append", "file=x.md")
    assert trailing.returncode == 2 and b"not read-only" in trailing.stderr
    assert not marker.exists()
