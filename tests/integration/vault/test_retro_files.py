"""Default retros own separate notes; legacy logs remain an explicit route."""

from pathlib import Path
import subprocess

from tests.integration.vault.test_repository import repository as repository
from tests.integration.vault.test_repository import run, vaultgit
from tests.integration.vault.test_retro import ARGS, COMMAND


def test_default_retro_creates_one_utf8_note_and_preserves_foreign_index(repository):
    env, vault = repository
    (vault / "foreign.md").write_text("foreign")
    vaultgit(env, "add", "--", "foreign.md")
    result = subprocess.run(
        [*COMMAND, *ARGS],
        input="Worked: café\nFailed: none\nChange: prüfen\n",
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    notes = list((vault / "_system/retros").glob("*.md"))
    assert len(notes) == 1
    note = notes[0]
    assert "café" in note.read_text(encoding="utf-8") and note.stat().st_mode & 0o777 == 0o600
    relative = str(note.relative_to(vault))
    assert vaultgit(env, "show", "--name-only", "--format=", "HEAD").stdout.strip() == relative
    assert vaultgit(env, "diff", "--cached", "--name-only").stdout.strip() == "foreign.md"


def test_concurrent_default_entries_commit_separately(repository):
    env, vault = repository
    env = {key: value for key, value in env.items() if key != "SLOPMEISTER_VAULT_LOCKED"}
    env["VAULT_LOCK"] = str(Path(__file__).resolve().parents[3] / "plots/vault/bin/vault-lock.py")
    children = [
        subprocess.Popen(
            [*COMMAND, *ARGS, "--task", f"writer-{index}"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(4)
    ]
    for child in children:
        child.stdin.write("one\ntwo\nthree\n")
        child.stdin.close()
        child.stdin = None
    for child in children:
        output, error = child.communicate(timeout=15)
        assert child.returncode == 0, output + error
    notes = list((vault / "_system/retros").glob("*.md"))
    assert len(notes) == 4
    for note in notes:
        assert vaultgit(env, "show", f"HEAD:{note.relative_to(vault)}").stdout == note.read_text()


def test_new_route_keeps_pending_legacy_spills_and_reports_them(repository, tmp_path):
    env, vault = repository
    spill = tmp_path / "spill"
    spill.mkdir()
    owed = spill / "owed.md"
    owed.write_text("legacy pending entry\n")
    result = subprocess.run(
        [*COMMAND, *ARGS],
        input="one\ntwo\nthree\n",
        env=env | {"RETRO_SPILL_DIR": str(spill)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and "remain pending" in result.stderr
    assert owed.read_text() == "legacy pending entry\n"
    assert "legacy pending" not in next((vault / "_system/retros").glob("*.md")).read_text()


def test_failed_default_commit_keeps_note_for_named_recovery(repository):
    env, vault = repository
    hook = Path(env["VAULT_GIT_DIR"]) / "hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o700)
    result = subprocess.run(
        [*COMMAND, *ARGS], input="one\ntwo\nthree\n", env=env, capture_output=True, text=True
    )
    notes = list((vault / "_system/retros").glob("*.md"))
    assert result.returncode == 1 and "not committed" in result.stderr and len(notes) == 1
    before = notes[0].read_bytes()
    hook.write_text("#!/bin/sh\nexit 0\n")
    recovered = run("commit", "Recover retro", "--", str(notes[0].relative_to(vault)), env=env)
    assert recovered.returncode == 0, recovered.stderr
    assert notes[0].read_bytes() == before
