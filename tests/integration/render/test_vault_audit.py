"""The rendered vault-optimize audit scans only the selected scope and refuses unusable ones."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("tool", ("claude", "codex"))
def test_rendered_vault_commands_use_the_bounded_obsidian_boundary(tool: str) -> None:
    skill = (ROOT / "dist" / tool / "skills/vault-optimize/SKILL.md").read_text()
    assert skill.count("slopmeister-vault obsidian -- vault=obsidian") == 4
    assert "2 refuses a non-read-only operation" in skill and "</dev/null>" not in skill


@pytest.fixture(params=("claude", "codex"))
def audit_command(request):
    skill = (ROOT / "dist" / request.param / "skills/vault-optimize/SKILL.md").read_text()
    return skill.split("```bash\n")[-1].split("\n```", 1)[0]


def refusing_environment(tmp_path):
    """No scope variable, and a grep that fails loudly if an empty operand scans the root."""
    env = {key: value for key, value in os.environ.items() if key != "VAULT_SCOPE"}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    grep = bin_dir / "grep"
    grep.write_text("#!/bin/sh\nprintf 'unexpected scan\\n'\nexit 1\n")
    grep.chmod(0o755)
    env["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    return env


def test_vault_alias_audit_reads_selected_scope_instead_of_session_directory(
    tmp_path, audit_command
):
    """A workspace scan must not hide bad vault links or report unrelated matches."""
    workspace = tmp_path / "session"
    scope = tmp_path / "vault with spaces" / "selected area"
    workspace.mkdir()
    scope.mkdir(parents=True)
    bad_row = "| [[note|label]] | bad alias |\n"
    (workspace / "decoy.md").write_text(bad_row)
    (scope.parent / "outside.md").write_text(bad_row)
    bad = scope / "bad.md"
    bad.write_text(bad_row)
    (scope / "good.md").write_text("| [[note\\|label]] | escaped alias |\n")
    command = audit_command
    env = {**os.environ, "VAULT_SCOPE": str(scope)}
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    result = subprocess.run(
        ["bash", "-c", command], cwd=workspace, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(bad)]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    bad.write_text("| [[note\\|label]] | repaired alias |\n")
    clean = subprocess.run(
        ["bash", "-c", command], cwd=workspace, env=env, capture_output=True, text=True
    )
    assert clean.returncode == 1 and not clean.stdout and not clean.stderr


@pytest.mark.parametrize(
    "kind", ("unset", "empty", "missing", "relative", "file", "broken_symlink")
)
def test_vault_alias_audit_refuses_unusable_scope_then_accepts_valid_retry(
    tmp_path, audit_command, kind
):
    """An unscanned folder must produce an error instead of the clean-audit exit status."""
    scope = tmp_path / "selected"
    scope.mkdir()
    bad = scope / "bad.md"
    bad.write_text("| [[note|label]] | bad alias |\n")
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "missing")
    values = {
        "empty": "",
        "missing": str(tmp_path / "missing"),
        "relative": "selected",
        "file": str(bad),
        "broken_symlink": str(broken),
    }
    env = refusing_environment(tmp_path)
    if kind != "unset":
        env["VAULT_SCOPE"] = values[kind]
    before = bad.read_bytes()
    refused = subprocess.run(
        ["bash", "-c", audit_command], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert refused.returncode == 2, (kind, refused.stdout, refused.stderr)
    assert not refused.stdout and "existing absolute vault folder" in refused.stderr
    assert bad.read_bytes() == before
    assert_valid_retry(audit_command, env, (scope, bad, before))


def assert_valid_retry(audit_command, env, case):
    """The same command with a usable scope finds the bad row and changes nothing."""
    scope, bad, before = case
    env["PATH"] = os.environ["PATH"]
    env["VAULT_SCOPE"] = str(scope)
    retry = subprocess.run(
        ["bash", "-c", audit_command],
        cwd=bad.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert retry.returncode == 0 and retry.stdout.splitlines() == [str(bad)]
    assert not retry.stderr and bad.read_bytes() == before


@pytest.mark.parametrize("trailing_slash", (False, True))
def test_vault_alias_audit_follows_selected_symlink_root(tmp_path, audit_command, trailing_slash):
    """BSD grep must not silently skip a selected scope that is a directory symlink."""
    target = tmp_path / "real scope"
    target.mkdir()
    bad = target / "bad.md"
    bad.write_text("| [[note|label]] | bad alias |\n")
    link = tmp_path / "linked scope"
    link.symlink_to(target, target_is_directory=True)
    env = {**os.environ, "VAULT_SCOPE": str(link) + ("/" if trailing_slash else "")}
    result = subprocess.run(
        ["bash", "-c", audit_command], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0 and result.stdout.splitlines() == [str(link / "bad.md")]
    assert not result.stderr and link.is_symlink()
    bad.write_text("| [[note\\|label]] | repaired alias |\n")
    clean = subprocess.run(
        ["bash", "-c", audit_command], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert clean.returncode == 1 and not clean.stdout and not clean.stderr
