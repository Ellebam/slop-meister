"""Directory and repository sessions receive the same bounded capability set."""

import json
from pathlib import Path
import tomllib

import pytest

from tests.integration.install.installer_helpers import ROOT, environment, install


def test_directory_session_has_no_git_and_does_not_write_to_grants(tmp_path):
    env = environment(tmp_path)
    grant = tmp_path / "vault"
    grant.mkdir()
    workspace = tmp_path / "sessions/example-notes"
    install(env, "--directory", "example-notes", str(workspace), "--grant", str(grant))
    install(env, "--check", "example-notes", str(workspace), "--grant", str(grant))
    assert not (workspace / ".git").exists()
    for native in (".agents", ".claude"):
        for skill in ("vault-todos", "vault-optimize"):
            assert (workspace / native / "skills" / skill / "SKILL.md").is_file()
    assert not list(grant.iterdir())


def test_directory_snapshot_allows_claude_runtime_state_but_refuses_payload_drift(tmp_path):
    env = environment(tmp_path)
    workspace = tmp_path / "sessions/example-notes"
    install(env, "--directory", "example-notes", str(workspace))
    (workspace / ".claude/settings.local.json").write_text("{}\n")
    (workspace / ".claude/.cc-writes").mkdir()
    (workspace / ".claude/.cc-writes/record").write_text("{}\n")
    install(env, "--check", "example-notes", str(workspace))
    (workspace / ".claude/.cc-writes-extra").write_text("tampered\n")
    result = install(env, "--check", "example-notes", str(workspace), ok=False)
    assert "report the refusal to the operator" in result.stderr
    (workspace / ".claude/.cc-writes-extra").unlink()
    (workspace / "AGENTS.md").write_text("tampered\n")
    result = install(env, "--check", "example-notes", str(workspace), ok=False)
    assert "report the refusal to the operator" in result.stderr


@pytest.mark.parametrize(
    ("shape", "message"),
    [
        ("file", "Claude Code runtime path is not a directory"),
        ("root symlink", "symlinked configuration path"),
        ("nested symlink", "symlinked configuration path"),
    ],
)
def test_directory_snapshot_refuses_unsafe_claude_runtime_path(tmp_path, shape, message):
    env = environment(tmp_path)
    workspace = tmp_path / "sessions/example-notes"
    install(env, "--directory", "example-notes", str(workspace))
    writes = workspace / ".claude/.cc-writes"
    outside = tmp_path / "outside"
    outside.mkdir()
    if shape == "file":
        writes.write_text("{}\n")
    elif shape == "root symlink":
        writes.symlink_to(outside)
    else:
        writes.mkdir()
        (writes / "record").symlink_to(outside)
    result = install(env, "--check", "example-notes", str(workspace), ok=False)
    assert message in result.stderr


def test_both_tools_receive_only_validated_temporary_write_roots(tmp_path):
    env = environment(tmp_path)
    safe = tmp_path / "safe-tmp"
    safe.mkdir()
    env["TMPDIR"] = str(safe)
    workspace = tmp_path / "sessions/example-notes"
    install(env, "--directory", "example-notes", str(workspace))
    expected = {str(Path("/tmp").resolve()), str(safe.resolve())}
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    codex = tomllib.loads((workspace / ".codex/config.toml").read_text())
    review = f"{ROOT}/bin/slopmeister review review *"
    assert set(access["permissions"]["additionalDirectories"]) == expected
    assert set(codex["sandbox_workspace_write"]["writable_roots"]) == expected

    assert "Edit(~/.local/state/slopmeister/**)" in access["permissions"]["deny"]
    replace = f"Bash({ROOT}/bin/slopmeister review replace *)"
    assert replace in access["permissions"]["ask"]
    edit_rules = {rule for rule in access["permissions"]["allow"] if rule.startswith("Edit(")}
    assert edit_rules == {"Edit(/" + path + "/**)" for path in {str(workspace), *expected}}
    assert "Bash" not in access["permissions"]["allow"]
    assert f"Bash({review})" in access["permissions"]["allow"]
    rules = (workspace / ".codex/rules/review.rules").read_text()
    assert f'"{ROOT}/bin/slopmeister", "review", "review"' in rules
    assert "replace" not in rules
    assert not any("local/state/slopmeister" in path for path in expected)


def test_codex_grant_with_toml_syntax_stays_one_literal_root(tmp_path):
    """Bug: a grant path carrying quote, bracket, newline and table syntax escapes the
    writable_roots array and injects configuration into the Codex workspace config."""
    env = environment(tmp_path)
    grant = tmp_path / 'x"]\n[projects."a"]\ntrust_level = "trusted'
    grant.mkdir()
    workspace = tmp_path / "sessions/example-notes"
    install(env, "--directory", "example-notes", str(workspace), "--grant", str(grant))
    codex = tomllib.loads((workspace / ".codex/config.toml").read_text())
    assert "projects" not in codex
    assert str(grant.resolve()) in codex["sandbox_workspace_write"]["writable_roots"]


@pytest.mark.parametrize("shape", ("directory", "repository"))
def test_claude_runs_unsandboxed_and_only_the_named_path_vault_commit_skips_a_question(
    tmp_path, shape
):
    """A wider rule would run lint, retro or any launcher subcommand without a question."""
    from tests.integration.install.installer_helpers import project, worktree

    env = environment(tmp_path)
    if shape == "directory":
        workspace = tmp_path / "sessions/example-notes"
        install(env, "--directory", "example-notes", str(workspace))
    else:
        workspace = worktree(project(tmp_path / "project"), "session")
        install(env, "--prepare", "example-app", str(workspace))
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    # Bug: an enabled block keeps failing gh pipes, ps and git's credential write, and an
    # omitted block lets a home sandbox setting silently re-enable it in every session.
    assert access["sandbox"] == {"enabled": False}
    # Bug: a second sandbox block in the project settings makes effective precedence unclear.
    assert "sandbox" not in json.loads((workspace / ".claude/settings.json").read_text())
    # Bug: with no sandbox the secret denies are the only guard on these commands.
    assert {"Bash(gh auth token)", "Bash(gh auth login)"} <= set(access["permissions"]["deny"])
    assert "Bash(slopmeister-vault commit *)" in access["permissions"]["allow"]
    vault = (workspace / ".codex/rules/vault-commit.rules").read_text()
    assert '["slopmeister-vault", "commit"]' in vault and 'decision="allow"' in vault
    for wider in ('["slopmeister-vault"]', "lint", "retro", "obsidian"):
        assert wider not in vault


def test_unsafe_tmpdir_is_refused_before_workspace_creation(tmp_path):
    env = environment(tmp_path)
    env["TMPDIR"] = env["HOME"]
    workspace = tmp_path / "sessions/example-notes"
    result = install(env, "--directory", "example-notes", str(workspace), ok=False)
    assert "TMPDIR must be a current-user macOS temporary directory" in result.stderr
    assert not workspace.exists()


@pytest.mark.parametrize("problem", ["existing", "missing-grant", "inside-git"])
def test_directory_destination_and_grants_must_be_safe(tmp_path, problem):
    env = environment(tmp_path)
    workspace = tmp_path / "sessions/worker"
    args = ["--directory", "example-notes", str(workspace)]
    if problem == "existing":
        workspace.mkdir(parents=True)
    elif problem == "missing-grant":
        args += ["--grant", str(tmp_path / "missing")]
    else:
        from tests.support.repos import scratch_repo

        repo = scratch_repo(tmp_path / "repo")
        workspace = repo / "session"
        args = ["--directory", "example-notes", str(workspace)]
    result = install(env, *args, ok=False)
    assert "config-install:" in result.stderr


def test_allocation_is_ignored_and_saved_with_delivery_state(tmp_path):
    from tests.integration.install.installer_helpers import project, worktree
    from tests.support.repos import git

    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    workspace = worktree(repo, "allocated")
    install(env, "--prepare", "example-app", str(workspace), ".slot.env")
    (workspace / ".slot.env").write_text("APP_PORT=4100\n")
    install(env, "--check", "example-app", str(workspace))
    assert git(workspace, "check-ignore", ".slot.env").strip() == ".slot.env"
    gitdir = Path(git(workspace, "rev-parse", "--absolute-git-dir").strip())
    assert (
        json.loads((gitdir / "slopmeister-config/state.json").read_text())["allocation"]
        == ".slot.env"
    )
