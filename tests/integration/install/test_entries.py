"""A thin entry that resolves through the checkout or a wrong snapshot runs the wrong code."""

from pathlib import Path
import subprocess
import sys

from slopmeister.install.entries import entry_text
from tests.support.trees import write

ROOT = Path(__file__).resolve().parents[3]


def program(snapshot: Path) -> None:
    write(snapshot, "slopmeister/__init__.py", "")
    write(snapshot, "slopmeister/session/__init__.py", "")
    write(
        snapshot,
        "slopmeister/session/probe.py",
        "import sys\n\n\ndef main(argv):\n    print('probe', sys.argv[0], *argv)\n    return 3\n",
    )


def run(entry: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(entry), *args], capture_output=True, text=True, check=False
    )


def test_baked_snapshot_wins_over_the_entry_location(tmp_path: Path) -> None:
    snapshot = tmp_path / "state" / "snapshot"
    program(snapshot)
    entry = write(
        tmp_path, "workspace/.claude/probe.py", entry_text("slopmeister.session.probe", snapshot)
    )
    result = run(entry, "x")
    assert result.returncode == 3, result.stderr
    assert result.stdout == f"probe {entry} x\n"


def test_unbaked_entry_walks_up_to_the_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    program(checkout)
    entry = write(
        checkout, "src/skills/x/scripts/probe.py", entry_text("slopmeister.session.probe")
    )
    assert run(entry).returncode == 3


def test_unbaked_entry_outside_a_checkout_fails_instead_of_guessing(tmp_path: Path) -> None:
    entry = write(tmp_path, "elsewhere/probe.py", entry_text("slopmeister.session.probe"))
    result = run(entry)
    assert result.returncode == 1
    assert "StopIteration" in result.stderr
