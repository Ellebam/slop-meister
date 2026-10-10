"""Prepare and start one standing dispatcher in the invoking terminal."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re
import subprocess
import uuid

from slopmeister import paths
from slopmeister.dispatch import command
from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.launch import terminal
from slopmeister.launch.model import shq
from slopmeister.paths import ROOT

USAGE = "usage: task dispatch -- [--open] [claude|codex] [remote-name] [--model <model>]"
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def parse(argv: Sequence[str]) -> command.Settings:
    args = list(argv)
    if len(args) > 4:
        raise UsageError(USAGE)
    tool = args.pop(0) if args else "claude"
    if tool not in ("claude", "codex"):
        raise UsageError(USAGE)
    name = args.pop(0) if args and args[0] != "--model" else ""
    if name.startswith("--") or name and not NAME.fullmatch(name):
        reason = f"remote name '{name}' must match [a-z0-9][a-z0-9-]*" if name else USAGE
        raise UsageError(reason)
    model = ""
    if args:
        if len(args) != 2 or args[0] != "--model":
            raise UsageError(USAGE)
        model = args[1]
        if not model:
            raise SlopmeisterError("model must not be empty")
        if model.startswith("-"):
            raise SlopmeisterError(f"model '{model}' must not begin with '-'")
    return command.Settings(tool, name, model)


def _run(argv: list[str], *, capture: bool = False) -> str:
    try:
        result = subprocess.run(argv, capture_output=capture, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(f"could not run {Path(argv[0]).name}") from error
    if result.returncode:
        raise SlopmeisterError(f"{Path(argv[0]).name} failed")
    return result.stdout.rstrip("\n") if capture else ""


def _process_exists(pattern: str) -> bool:
    try:
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        message = "could not inspect live processes for dispatcher collisions"
        raise SlopmeisterError(message) from error
    if result.returncode not in (0, 1):
        raise SlopmeisterError("could not inspect live processes for dispatcher collisions")
    return result.returncode == 0


def _install(tool: str, trust: Path, roots: tuple[Path, Path]) -> None:
    workspace, vault = roots
    cli = str(ROOT / "bin/slopmeister")
    _run([cli, "install", "--trust", "check", tool, str(trust), str(workspace)])
    _run(
        [
            cli,
            "install",
            "--directory",
            "slopmeister",
            str(workspace),
            "--dispatcher-jira",
            "--grant",
            str(ROOT),
            "--grant",
            str(vault),
        ]
    )
    _run([cli, "install", "--trust", "write", tool, str(trust), str(workspace)])


def _kickoff(path: Path, tool: str, name: str) -> str:
    source = ROOT / "src/skills/plot-session/dispatcher.md"
    if not source.is_file():
        raise SlopmeisterError(f"dispatcher kickoff missing at {source}")
    prefix = f"slopmeister-dispatcher={name} role=standing\n\n" if tool == "codex" and name else ""
    suffix = (
        f"\nThe invoking Slopmeister checkout is `{ROOT}`. Run Slopmeister commands with "
        f"`task --dir {ROOT}`, and resolve Slopmeister documentation paths against that "
        "checkout.\n"
    )
    text = prefix + source.read_text() + suffix
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)
    path.chmod(0o600)
    return text


def _trust(tool: str, workspace: Path) -> tuple[Path, dict[str, str]]:
    env = dict(os.environ)
    if tool == "codex":
        home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
        return home / "config.toml", env
    value = env.get("CLAUDE_CONFIG_DIR")
    if value == "":
        raise SlopmeisterError("CLAUDE_CONFIG_DIR is empty, refusing to choose a Claude store")
    if value is None:
        return Path.home() / ".claude.json", env
    root = Path(os.path.realpath(workspace / value))
    env["CLAUDE_CONFIG_DIR"] = str(root)
    os.environ["CLAUDE_CONFIG_DIR"] = str(root)
    return root / ".claude.json", env


def _report(line: str, paths: tuple[Path, Path], skipped: bool = False) -> None:
    kickoff, workspace = paths
    if skipped:
        print("dispatch: launch skipped (DISPATCH_NO_LAUNCH), launch line:")
    else:
        print("dispatch: launch line:")
    print("  " + line)
    print(f"  kickoff file: {kickoff}")
    print(f"  prepared directory: {workspace}")


def _prepare(settings: command.Settings) -> tuple[Path, Path, str, list[str], dict]:
    root = Path(os.environ.get("PLOT_SESSION_ROOT") or Path.home() / ".slopmeister/sessions")
    workspace = root / f"dispatcher-{settings.name or 'unnamed'}-{settings.tool}-{uuid.uuid4()}"
    trust, env = _trust(settings.tool, workspace)
    vault = paths.vault()
    if not vault.is_dir():
        raise SlopmeisterError(f"vault not found at {vault}, set SLOPMEISTER_VAULT")
    _install(settings.tool, trust, (workspace, vault))
    state = Path(os.environ.get("DISPATCH_STATE_DIR") or ROOT / "tmp/dispatch")
    kickoff_file = state / f"{settings.name or 'unnamed'}-{settings.tool}.md"
    kickoff = _kickoff(kickoff_file, settings.tool, settings.name)
    return workspace, kickoff_file, kickoff, command.prefix(settings, workspace), env


def _open(settings: command.Settings) -> int:
    if not settings.name:
        raise UsageError("--open requires a dispatcher name")
    args = ["task", "dispatch", "--", settings.tool, settings.name]
    if settings.model:
        args.extend(("--model", settings.model))
    if settings.tool == "codex":
        args = ["env", f"CODEX_HOME={Path.home() / '.codex'}", *args]
    line = f"cd {shq(str(ROOT))} && " + " ".join(shq(arg) for arg in args)
    if not terminal.ready():
        raise SlopmeisterError(
            "Orca is unreachable, nothing opened; have the workstation skill diagnose Orca"
        )
    terminal.register(ROOT)
    wrapped = f"/bin/zsh -lc {shq(line)}"
    try:
        handle = terminal.create(ROOT, f"{settings.name} dispatcher", wrapped)
    except SlopmeisterError:
        handle = None
    if not handle:
        raise SlopmeisterError(
            "Orca terminal creation is unconfirmed, inspect Orca before retrying"
        )
    print(f"dispatch: Orca terminal {handle} opened")
    return 0


def main(argv: Sequence[str]) -> int:
    open_mode = bool(argv and argv[0] == "--open")
    settings = parse(argv[1:] if open_mode else argv)
    no_launch = os.environ.get("DISPATCH_NO_LAUNCH") == "1"
    guard = Path(command.sleep_guard()[0])
    if not no_launch and (not guard.is_file() or not os.access(guard, os.X_OK)):
        raise SlopmeisterError(f"sleep guard not found at {guard}")
    if settings.name and (
        _process_exists(rf"remote-control={re.escape(settings.name)}($| )")
        or _process_exists(rf"slopmeister-dispatcher={re.escape(settings.name)} role=standing")
    ):
        raise SlopmeisterError(f"a live process already carries dispatcher name {settings.name}")
    if open_mode:
        return _open(settings)
    workspace, kickoff_file, kickoff, prefix, env = _prepare(settings)
    line = command.line(workspace, prefix, kickoff_file)
    if no_launch:
        _report(line, (kickoff_file, workspace), skipped=True)
        return 0
    _report(line, (kickoff_file, workspace))
    os.environ.update(env)
    command.execute(workspace, prefix, kickoff)
    return 0
