"""Build disposable repositories for installer integration tests."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess

from tests.support.repos import GIT_ENV, git, scratch_repo
from tests.support.trees import write

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "bin/slopmeister"


@dataclass(frozen=True)
class Installed:
    repo: Path
    workspace: Path
    env: dict[str, str]
    baseline: str


def environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        HOME=str(home),
        XDG_STATE_HOME=str(tmp_path / "state"),
        GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"),
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def install(env: dict[str, str], *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(INSTALL), "install", *map(str, args)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
    return result


def project(path: Path) -> Path:
    repo = scratch_repo(path)
    write(repo, "AGENTS.md", "original agreement\n")
    write(repo, "CLAUDE.md", "original instructions\n")
    write(repo, ".claude/skills/frame/SKILL.md", "original procedure\n")
    write(repo, ".claude/skills/neighbour/SKILL.md", "neighbour\n")
    write(repo, ".claude/settings.local.json", "{}\n")
    write(repo, "app.txt", "application\n")
    write(repo, "product/AGENTS.md", "product document\n")
    write(repo, "product/CLAUDE.md", "product document\n")
    write(repo, "product/.codex/config.toml", 'developer_instructions="foreign"\n')
    pre_commit = write(repo, ".hooks/pre-commit", "#!/bin/sh\necho original-pre-commit\n")
    commit_msg = write(
        repo,
        ".hooks/commit-msg",
        '#!/bin/sh\nif grep -qx bad-message "$1"; then '
        "echo original-message-refusal >&2; exit 1; fi\n",
    )
    pre_commit.chmod(0o700)
    commit_msg.chmod(0o700)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Configure fixture")
    git(repo, "config", "core.hooksPath", ".hooks")
    return repo


def worktree(repo: Path, name: str) -> Path:
    path = repo / ".worktrees" / name
    git(repo, "worktree", "add", "-qb", name, str(path))
    return path


def prepared(tmp_path: Path, permission: str = "allow", shipping: str = "allow") -> Installed:
    env = environment(tmp_path)
    repo = project(tmp_path / "project")
    target = "example-app"
    if permission == "deny" or shipping == "deny":
        plots = tmp_path / "plots"
        source = (ROOT / "plots/example-app/plot.toml").read_text()
        source = source.replace('commit = "allow"', f'commit = "{permission}"')
        source = source.replace('shipping = "allow"', f'shipping = "{shipping}"')
        write(plots, "example-app/plot.toml", source)
        env["PLOT_DECLARATIONS"] = str(plots)
    workspace = worktree(repo, "worker-" + permission + "-" + shipping)
    baseline = git(repo, "rev-parse", "HEAD").strip()
    install(env, "--prepare", target, str(workspace))
    return Installed(repo, workspace, env, baseline)


def state(workspace: Path) -> tuple[Path, dict]:
    gitdir = Path(git(workspace, "rev-parse", "--absolute-git-dir").strip())
    path = gitdir / "slopmeister-config/state.json"
    return path, json.loads(path.read_text())


def git_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=20,
    )


def checkout(path: Path) -> Path:
    path.mkdir()
    for name in ("bin", "slopmeister", "src", "dist", "plots"):
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, path / name)
        else:
            shutil.copy2(source, path / name)
    return path
