"""The retro target guard runs before any direct note access."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMMAND = [str(ROOT / "bin/slopmeister"), "vault", "retro"]


def guard_call(tmp_path: Path, extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    note = "_system/retro-log.md"
    subject = tmp_path / "vault" / note
    subject.parent.mkdir(parents=True, exist_ok=True)
    subject.write_text("foreign bytes\n")
    values = {
        "repo": "fixture",
        "task": extra,
        "title": "fixture",
        "tool": "pytest",
        "model": "fixture",
        "note": note,
    }
    command = [*COMMAND, *(item for key, value in values.items() for item in (f"--{key}", value))]
    result = subprocess.run(
        command,
        input="one\ntwo\nthree\n",
        env={
            **os.environ,
            "SLOPMEISTER_VAULT": str(tmp_path / "vault"),
            "RETRO_FORBID_NOTE": note,
            "RETRO_SPILL_DIR": str(tmp_path / "spill"),
        },
        capture_output=True,
        text=True,
    )
    return result, subject


@pytest.mark.parametrize(
    "extra",
    [
        "path=foreign.md",
        "path=_system/test-fixtures/slopmeister-retro-fixture.md",
        "file=foreign",
        "vault=other",
        "overwrite",
        "permanent=true",
    ],
)
def test_native_guard_refuses_alternate_targets_before_any_write(tmp_path: Path, extra: str):
    """The forbidden canonical note cannot reach the writer under caller-shaped input."""
    result, subject = guard_call(tmp_path, extra)
    assert result.returncode == 2 and "forbidden" in result.stderr
    assert subject.read_text() == "foreign bytes\n" and not (tmp_path / "spill").exists()


def test_native_guard_preserves_preexisting_and_modified_notes(tmp_path: Path):
    """The guard refuses before it can overwrite a protected note."""
    _, note = guard_call(tmp_path, "foreign")
    assert note.read_bytes() == b"foreign bytes\n"
