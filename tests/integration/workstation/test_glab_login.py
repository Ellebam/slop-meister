"""The glab login takes its token from the environment and prints a marker, never the token."""

import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.workstation import glab_login
from tests.integration.workstation.test_install import machine, workstation
from tests.support.fakes import fake_binary

TOKEN = "glpat-" + "synthetic-not-a-secret"
HOST = "gitlab.invalid"
RECORD = 'printf \'%s\\n\' "$*" > "$HOME/argv"; cat > "$HOME/stdin"; env > "$HOME/env"'


def login(tmp_path: Path, script: str, token: str = TOKEN, host: str = HOST):
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "glab", script)
    env = {glab_login.TOKEN: token, glab_login.HOST: host, "CI": "true", "GITLAB_CI": "true"}
    return home, workstation(home, bin_dir, "glab-login", **env)


def test_login_feeds_the_token_on_stdin_and_prints_only_the_marker(tmp_path):
    """Bug: the token reaches the session's output, glab's arguments or glab's environment."""
    home, run = login(tmp_path, f"{RECORD}; echo 'Logged in with {TOKEN}'")
    assert run.returncode == 0
    assert run.stdout == "GLAB_LOGIN_PASS\n" and run.stderr == ""
    assert (home / "stdin").read_text() == TOKEN
    assert (home / "argv").read_text() == f"auth login --hostname {HOST} --stdin\n"
    assert TOKEN not in (home / "env").read_text()
    # Bug: glab stores the token as plaintext in its file when it believes it runs in CI.
    assert "CI=true" not in (home / "env").read_text()


def test_a_failed_login_names_the_exit_code_and_hides_what_glab_printed(tmp_path):
    """Bug: glab echoes the rejected token or the host in its error and the report repeats it."""
    home, run = login(tmp_path, f"echo 'bad token {TOKEN} for {HOST}' >&2; exit 4")
    assert run.returncode == 1
    assert run.stdout == "GLAB_LOGIN_FAIL: glab auth login exited 4\n"
    assert TOKEN not in run.stderr and HOST not in run.stdout + run.stderr


@pytest.mark.parametrize(
    ("token", "host"),
    [
        ("", HOST),
        (glab_login.PLACEHOLDER, HOST),
        ("op://vault/item/credential", HOST),
        (TOKEN, ""),
        (TOKEN, "--token"),
        (TOKEN, "https://gitlab.invalid"),
    ],
)
def test_an_unfilled_item_is_refused_before_glab_runs(tmp_path, token, host):
    """Bug: a placeholder or an unresolved reference is sent to the host as a credential."""
    home, run = login(tmp_path, RECORD, token, host)
    assert run.returncode == 1
    assert run.stdout.startswith("GLAB_LOGIN_FAIL: ")
    assert not (home / "argv").exists()


def test_task_passes_only_the_private_reference_file_to_op(tmp_path):
    home, bin_dir = machine(tmp_path)
    references = home / ".config/slopmeister/glab.env"
    references.parent.mkdir(parents=True)
    references.write_text("# Synthetic reference file\n")
    references.chmod(0o600)
    fake_binary(bin_dir, "op", 'printf "%s\\n" "$@" > "$HOME/op-args"')
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        ["task", "--taskfile", str(root / "taskfiles/workstation.yml"), "glab:login"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert (home / "op-args").read_text().splitlines() == [
        "run",
        f"--env-file={references}",
        "--",
        "bin/slopmeister",
        "workstation",
        "glab-login",
    ]
