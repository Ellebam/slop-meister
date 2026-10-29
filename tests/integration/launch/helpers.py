"""A scratch machine and scratch targets for driving slopmeister plot-session."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib

from slopmeister.launch import cli
from tests.support.repos import GIT_ENV, git

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "bin/slopmeister"
KICKOFF = "test kickoff"
CLAUDE_STUB = '#!/bin/sh\n[ "$1" = agents ] && echo "[]"\nexit 0\n'


@dataclass(frozen=True)
class Machine:
    root: Path
    env: dict[str, str]

    @property
    def state(self) -> Path:
        return Path(self.env["PLOT_SESSION_STATE_DIR"])

    @property
    def sessions(self) -> Path:
        return Path(self.env["PLOT_SESSION_ROOT"])

    @property
    def vault(self) -> Path:
        return Path(self.env["SLOPMEISTER_VAULT"])

    @property
    def claude(self) -> Path:
        return Path(self.env["CLAUDE_CONFIG_DIR"])

    @property
    def codex(self) -> Path:
        return Path(self.env["CODEX_HOME"])


def executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def ordinary_plots(path: Path) -> Path:
    """The committed declarations without workstation service actions."""
    for source in (ROOT / "plots").glob("*/plot.toml"):
        lines = source.read_text().splitlines(keepends=True)
        kept = "".join(line for line in lines if not line.startswith("service_actions ="))
        destination = path / source.parent.name / "plot.toml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(kept)
    return path


def machine(tmp_path: Path) -> Machine:
    """Every store and state path a launch writes lives under tmp_path, never the operator's."""
    home = tmp_path / "home"
    executable(home / ".local/bin/codex", "#!/bin/sh\nexit 0\n")
    executable(tmp_path / "bin/claude", CLAUDE_STUB)
    (tmp_path / "vault").mkdir()
    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.pop("PLOT_SESSION_WORKTREE_FILE", None)
    env.pop("ORCA_TERMINAL_HANDLE", None)
    env.update(GIT_ENV)
    env.update(
        HOME=str(home),
        PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"),
        CLAUDE_CONFIG_DIR=str(tmp_path / "claude"),
        CODEX_HOME=str(tmp_path / "codex"),
        XDG_STATE_HOME=str(tmp_path / "xdg"),
        PLOT_SESSION_STATE_DIR=str(tmp_path / "state"),
        PLOT_SESSION_ROOT=str(tmp_path / "sessions"),
        SLOPMEISTER_VAULT=str(tmp_path / "vault"),
        PLOT_SESSION_NO_LAUNCH="1",
        PLOT_DECLARATIONS=str(ordinary_plots(tmp_path / "plots")),
    )
    return Machine(tmp_path, env)


def temporary_roots(world: Machine) -> set[str]:
    roots = {str(Path("/tmp").resolve())}
    if raw := world.env.get("TMPDIR"):
        roots.add(str(Path(raw).resolve()))
    return roots


def codex_writable(workspace: Path) -> set[str]:
    """Codex 0.156 accepts no roots from a remote client, this project config is the grant."""
    config = tomllib.loads((workspace / ".codex/config.toml").read_text())
    return set(config["sandbox_workspace_write"]["writable_roots"])


def target(path: Path) -> Path:
    """A repository with one empty commit, the smallest thing a worktree can branch from."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def declare(root: Path, name: str, delivery: str, **values: str) -> Path:
    """A complete declaration: delivery is inject, seed, committed or - for no repository."""
    base = {"inject": "inject", "-": "freeform"}.get(delivery, "code")
    seed = "seed = true\n" if delivery == "seed" else ""
    text = f'[plot]\nbase = "{base}"\n{seed}\n[target]\ntasks = "{values.get("tasks", "manual")}"\n'
    if delivery != "-":
        permission = values.get("commit", "allow")
        text += f'\n[target.repository]\ncommit = "{permission}"\n\n[slots]\nnone = true\n'
    path = root / name / "plot.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return root


def launch(
    world: Machine, *args: str, kickoff: str = KICKOFF, ok: bool | None = True, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run the command; ok=None accepts either outcome for tests that assert the code."""
    command = [env.pop("cli", str(CLI)), "plot-session", *args]
    result = subprocess.run(
        command,
        input=kickoff or "",
        env={**world.env, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    if ok is not None:
        assert (result.returncode == 0) is ok, result.stdout + result.stderr
    return result


def launch_here(monkeypatch, world: Machine, *args: str, kickoff: str = KICKOFF, **env: str) -> int:
    """Run the launcher in this process, so a test can replace its sleep or its closure."""
    environment = {**world.env, **env}
    for key in set(os.environ) - set(environment):
        monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(kickoff.encode())))
    return cli.main(list(args))


def reported(output: str, label: str) -> str:
    """A value from the launcher's indented report, such as `kickoff file`."""
    prefix = f"  {label}: "
    return next(line[len(prefix) :] for line in output.splitlines() if line.startswith(prefix))


def snapshot(root: Path) -> list[tuple[str, int, str]]:
    """Every path under root with its mode and content digest or link target.

    Git's own lock files come and go under background maintenance, so they are
    neither compared nor allowed to fail the walk when they vanish mid-read.
    """
    rows = (_row(path, root) for path in sorted(root.rglob("*")) if path.suffix != ".lock")
    return [row for row in rows if row is not None]


def _row(path: Path, root: Path) -> tuple[str, int, str] | None:
    try:
        mode = path.lstat().st_mode
        if path.is_symlink():
            value = os.readlink(path)
        elif path.is_file():
            value = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            value = ""
    except FileNotFoundError:
        return None
    return (str(path.relative_to(root)), stat.S_IMODE(mode), value)
