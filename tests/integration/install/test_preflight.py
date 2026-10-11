"""Installer preflight rejects unsafe repositories before mutation."""

from pathlib import Path

import pytest

from slopmeister.install import preflight
from tests.integration.install.installer_helpers import environment, install, project, worktree
from tests.support.repos import git
from tests.support.trees import write


def test_directory_ignores_machine_level_agent_symlink(tmp_path):
    env = environment(tmp_path)
    machine = Path(env["HOME"])
    skills = tmp_path / "machine-skills"
    write(skills, "sentinel", "global skill sentinel\n")
    (machine / ".agents").symlink_to(skills)
    workspace = machine / "sessions/worker"
    install(env, "--directory", "example-notes", str(workspace))
    install(env, "--check", "example-notes", str(workspace))
    assert (skills / "sentinel").read_text() == "global skill sentinel\n"
    assert (machine / ".agents").is_symlink()


@pytest.mark.parametrize("name", [".claude", ".codex", ".agents"])
def test_empty_readonly_ancestor_controls_do_not_block_a_directory_session(tmp_path, name):
    """Bug: another worker's empty sandbox control directory refuses a clean session."""
    env = environment(tmp_path)
    parent = tmp_path / "parent"
    placeholder = parent / name
    placeholder.mkdir(parents=True, mode=0o555)
    placeholder.chmod(0o555)
    workspace = parent / "worker"
    install(env, "--directory", "example-notes", str(workspace))
    assert workspace.is_dir() and not list(placeholder.iterdir())
    assert placeholder.stat().st_mode & 0o777 == 0o555


@pytest.mark.parametrize("kind", ["nonempty", "symlink", "file"])
def test_real_or_symlinked_ancestor_configuration_still_refuses_preparation(tmp_path, kind):
    """Bug: ignoring empty controls also admits actual settings or a redirected namespace."""
    env = environment(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    control = parent / ("AGENTS.md" if kind == "file" else ".codex")
    if kind == "file":
        control.touch()
    elif kind == "symlink":
        target = tmp_path / "outside"
        target.mkdir()
        control.symlink_to(target)
    else:
        control.mkdir()
        (control / "config.toml").write_text("# actual settings\n")
    workspace = parent / "worker"
    result = install(env, "--directory", "example-notes", str(workspace), ok=False)
    assert "ancestor project configuration" in result.stderr and not workspace.exists()


def test_disappearing_empty_control_does_not_fail_ancestor_validation(tmp_path, monkeypatch):
    """Bug: another sandbox command ending removes its empty control during inspection."""
    control = tmp_path / ".codex"
    control.mkdir()
    iterdir = Path.iterdir

    def vanish(path):
        if path == control:
            path.rmdir()
            raise FileNotFoundError(path)
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", vanish)
    preflight._reject_ancestor_configuration(tmp_path, set())
    assert not control.exists()


def test_unreadable_ancestor_control_keeps_the_configuration_refusal(tmp_path):
    """Bug: checking an unreadable control loses the actionable fail-closed refusal."""
    env = environment(tmp_path)
    parent = tmp_path / "parent"
    control = parent / ".codex"
    control.mkdir(parents=True)
    (control / "config.toml").write_text("# actual settings\n")
    control.chmod(0o000)
    workspace = parent / "worker"
    try:
        result = install(env, "--directory", "example-notes", str(workspace), ok=False)
        assert "ancestor project configuration" in result.stderr and not workspace.exists()
    finally:
        control.chmod(0o700)


def test_plot_validation_precedes_repository_inspection(tmp_path):
    env = environment(tmp_path)
    declarations = tmp_path / "plots"
    write(
        declarations,
        "broken/plot.toml",
        '[plot]\nbase = "code"\n[target]\ntasks = "typo"\n',
    )
    env["PLOT_DECLARATIONS"] = str(declarations)
    result = install(env, "--preflight", "example-app", str(tmp_path / "absent"), ok=False)
    assert "broken/plot.toml: target.tasks" in result.stderr


@pytest.mark.parametrize("action", ["--install", "--diff", "--drift", "--prepare"])
def test_main_checkout_and_retired_actions_are_refused_without_mutation(tmp_path, action):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    before = git(repo, "status", "--short", "--untracked-files=all")
    result = install(env, action, "example-app", str(repo), ok=False)
    assert "registered linked worktree" in result.stderr or "is required" in result.stderr
    assert git(repo, "status", "--short", "--untracked-files=all") == before


def test_git_context_override_is_refused(tmp_path):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    env["GIT_DIR"] = str(repo / ".git")
    result = install(env, "--preflight", "example-app", str(repo), ok=False)
    assert "refuses Git context override GIT_DIR" in result.stderr


def test_harness_git_variables_do_not_stop_or_steer_preparation(tmp_path):
    """Bug: the installer refused a launch because the harness had set credential variables."""
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    env.update(
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="core.sparseCheckout",
        GIT_CONFIG_VALUE_0="true",
        GIT_ASKPASS="/bin/true",
    )
    result = install(env, "--preflight", "example-app", str(repo))
    assert "preflight passed" in result.stdout


@pytest.mark.parametrize("key", ["core.worktree", "core.bare"])
def test_shared_repository_modes_are_refused_without_rewrite(tmp_path, key):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    git(repo, "config", key, str(repo) if key == "core.worktree" else "true")
    before = (repo / ".git/config").read_bytes()
    result = install(env, "--preflight", "example-app", str(repo), ok=False)
    assert key in result.stderr
    assert (repo / ".git/config").read_bytes() == before


@pytest.mark.parametrize("value", ["true", "yes", "1"])
def test_git_boolean_spellings_preserve_extension_and_refuse_sparse_checkout(tmp_path, value):
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    git(repo, "config", "extensions.worktreeConfig", value)
    workspace = worktree(repo, "boolean-" + value)
    before = (repo / ".git/config").read_bytes()
    install(env, "--prepare", "example-app", str(workspace))
    assert (repo / ".git/config").read_bytes() == before
    git(repo, "config", "core.sparseCheckout", value)
    result = install(env, "--preflight", "example-app", str(repo), ok=False)
    assert "sparse checkout" in result.stderr


def test_account_level_worktree_config_still_enables_repository_extension(tmp_path):
    """Bug: an account-level extensions.worktreeConfig hides the missing repository setting."""
    env = environment(tmp_path)
    Path(env["GIT_CONFIG_GLOBAL"]).write_text("[extensions]\n\tworktreeConfig = true\n")
    repo = project(tmp_path / "project")
    workspace = worktree(repo, "account-level")
    install(env, "--prepare", "example-app", str(workspace))
    assert (
        git(repo, "config", "--file", ".git/config", "extensions.worktreeConfig").strip() == "true"
    )
    assert git(workspace, "config", "--worktree", "core.excludesFile").strip()
    assert (
        git(repo, "config", "--file", ".git/config", "--get-all", "core.hooksPath").strip()
        == ".hooks"
    )
