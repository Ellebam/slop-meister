"""Harness Git variables never reach a Git or GitHub child, repository redirects still stop."""

import hashlib

import pytest

from slopmeister.claims import github
from slopmeister.install import preflight
from slopmeister.session import git_environment, ship, verify
from tests.support import repos

HARNESS = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "credential.helper",
    "GIT_CONFIG_VALUE_0": "x",
    "GIT_CONFIG_PARAMETERS": "'credential.helper=y'",
    "GIT_ASKPASS": "/bin/true",
    "SSH_ASKPASS": "/bin/true",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name, value in {**repos.GIT_ENV, **HARNESS}.items():
        monkeypatch.setenv(name, value)
    return repos.scratch_repo(tmp_path / "repo")


def test_child_environment_drops_only_the_injected_variables(repo):
    """Bug: a harness setting changed a child, or a wanted variable was dropped with it."""
    child = git_environment.child()
    assert not set(HARNESS) & set(child)
    assert child["GIT_CONFIG_GLOBAL"] == "/dev/null"


def test_claims_git_child_does_not_see_injected_configuration(repo):
    """Bug: claims refused the harness variables, so finalize needed a manual unset."""
    with pytest.raises(ValueError, match=r"git operation failed \(1\)"):
        github.git(repo, "config", "--get", "credential.helper")


def test_installer_git_child_does_not_see_injected_configuration(repo):
    """Bug: an injected setting reached the installer's Git reads."""
    preflight.reject_git_context()
    assert preflight.setting(repo, "credential.helper") == ""


def test_ship_child_does_not_see_injected_configuration(repo):
    """Bug: shipping refused the harness variables, or pushed under injected configuration."""
    names = {row.split("=")[0] for row in ship.command(repo, "env").splitlines()}
    assert not set(HARNESS) & names
    with pytest.raises(ValueError, match=r"failed \(1\)"):
        ship.command(repo, "git", "config", "--get", "credential.helper")


def test_copied_verifier_git_child_does_not_see_injected_configuration(repo, monkeypatch):
    """Bug: an injected core.excludesFile made the launch-time verifier refuse a sound worktree."""
    exclude = repo / "state/exclude"
    exclude.parent.mkdir()
    exclude.write_text("")
    repos.git(repo, "config", "core.excludesFile", "state/exclude")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "injected")
    monkeypatch.setattr(verify, "entry", lambda: repo / "state/config-install.py")
    state = {"baseline": "0" * 40, "exclude_sha256": hashlib.sha256(b"").hexdigest()}
    verify._check_delivery_isolation(repo, state)


@pytest.mark.parametrize("name", git_environment.REDIRECTS)
def test_repository_redirects_still_refuse_everywhere(repo, monkeypatch, name):
    """Bug: accepting the harness variables also accepted a variable that moves the repository."""
    monkeypatch.setenv(name, str(repo / "elsewhere"))
    with pytest.raises(ValueError, match="not allowed for issue management"):
        github.git(repo, "status")
    with pytest.raises(ValueError, match="refuses Git context override " + name):
        preflight.reject_git_context()
    with pytest.raises(ValueError, match="refuses Git context override " + name):
        verify._check_delivery_isolation(repo, {"baseline": "0" * 40})
    with pytest.raises(ValueError, match="refuses Git context overrides: .*" + name):
        ship.authorized_state(repo)
