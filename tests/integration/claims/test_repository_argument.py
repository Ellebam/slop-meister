"""Repository actions diagnose an omitted repository instead of passing None to Git."""

import os
from pathlib import Path
import subprocess

from tests.support import fakes, repos

SLOPMEISTER = Path(__file__).resolve().parents[3]


def run_target(cwd: Path, *arguments: str, **environment: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **repos.GIT_ENV, **environment}
    return subprocess.run(
        [str(SLOPMEISTER / "bin/slopmeister"), "claims", "target", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_repository_action_defaults_to_current_checkout(tmp_path):
    repo = repos.scratch_repo(tmp_path / "repo")
    repos.git(repo, "remote", "add", "origin", "git@github.com:owner/project.git")
    nested = repo / "nested"
    nested.mkdir()

    result = run_target(nested)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owner/project\n"
    assert result.stderr == ""


def test_missing_repo_outside_checkout_names_the_flag(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    result = run_target(outside, GIT_CEILING_DIRECTORIES=str(tmp_path))

    assert result.returncode == 1
    assert "git operation failed (128): fatal: " in result.stderr
    assert "--repo" in result.stderr
    assert "None" not in result.stderr


def test_explicit_repo_error_has_no_omitted_flag_hint(tmp_path):
    result = run_target(tmp_path, "--repo", str(tmp_path / "missing"))

    assert result.returncode == 1
    assert "git operation failed (128): fatal: " in result.stderr
    assert "pass --repo" not in result.stderr


def test_backlog_names_the_error_gh_printed_without_its_credentials(tmp_path):
    """Bug: a failed GitHub read showed only an exit code, or leaked a token from a URL."""
    repo = repos.scratch_repo(tmp_path / "repo")
    repos.git(repo, "remote", "add", "origin", "git@github.com:owner/project.git")
    plot = tmp_path / "plots/scratch/plot.toml"
    plot.parent.mkdir(parents=True)
    plot.write_text(
        '[plot]\nbase="code"\n[target]\ntasks="github"\n'
        '[target.repository]\ncommit="allow"\nshipping="allow"\n[slots]\nnone=true\n'
    )
    failure = "gh: authentication required for https://user:token@github.com/owner/project"
    fakes.fake_binary(tmp_path / "bin", "gh", f"echo '{failure}' >&2\necho 'second' >&2\nexit 1")
    env = {
        **os.environ,
        **repos.GIT_ENV,
        "PATH": fakes.path_with(tmp_path / "bin"),
        "PLOT_DECLARATIONS": str(tmp_path / "plots"),
    }
    result = subprocess.run(
        [str(SLOPMEISTER / "bin/slopmeister"), "claims", "backlog", "--repo", str(repo)]
        + ["--plot", "scratch"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 1
    assert "authentication required for https://github.com/owner/project" in result.stderr
    assert "token" not in result.stderr and "second" not in result.stderr
