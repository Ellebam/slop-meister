"""Native command construction and same-terminal dispatcher execution."""

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import sys

from slopmeister import paths
from slopmeister.errors import SlopmeisterError
from slopmeister.launch.command import CODEX_APPROVAL
from slopmeister.launch.model import BROKER_MARK, shq

# Wraps the tool so the machine does not sleep while it is idle, see docs/agent-hosts.md.
# Idle only on Linux: a block on sleep itself needs an administrator outside a local login
# session, and a terminal that Orca opens runs outside one.
SLEEP_GUARD = {
    "darwin": ("/usr/bin/caffeinate", "-i"),
    "linux": (
        "/usr/bin/systemd-inhibit",
        "--what=idle",
        "--who=slopmeister",
        "--why=dispatcher at work",
        "--mode=block",
    ),
}


def sleep_guard() -> tuple[str, ...]:
    return SLEEP_GUARD[paths.platform()]


@dataclass(frozen=True)
class Settings:
    tool: str
    name: str
    model: str


def _claude(settings: Settings, workspace: Path) -> list[str]:
    executable = shutil.which("claude")
    if not executable:
        raise SlopmeisterError("claude not found on PATH")
    args = [
        "/usr/bin/env",
        BROKER_MARK,
        *sleep_guard(),
        executable,
        "--append-system-prompt-file",
        str(workspace / "CLAUDE.md"),
        "--setting-sources",
        "user,project",
        "--settings",
        str(workspace / ".claude/access-settings.json"),
        "--permission-mode",
        "auto",
    ]
    if settings.name:
        args.append("--remote-control=" + settings.name)
    return args


def _codex(workspace: Path) -> list[str]:
    executable = Path.home() / ".local/bin/codex"
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
    if not os.access(executable, os.X_OK):
        raise SlopmeisterError(f"codex not found at {executable}")
    return [
        "/usr/bin/env",
        f"CODEX_HOME={codex_home}",
        BROKER_MARK,
        *sleep_guard(),
        str(executable),
        "--no-daemon",
        *shlex.split(CODEX_APPROVAL),
        "-c",
        'project_root_markers=["AGENTS.md"]',
        "-c",
        "project_doc_fallback_filenames=[]",
        "-C",
        str(workspace),
    ]


def prefix(settings: Settings, workspace: Path) -> list[str]:
    args = _claude(settings, workspace) if settings.tool == "claude" else _codex(workspace)
    if settings.model:
        args.extend(("--model", settings.model))
    return args


def line(workspace: Path, argv: list[str], kickoff: Path) -> str:
    quoted = " ".join(shq(value) for value in argv)
    return f'cd {shq(str(workspace))} && exec {quoted} -- "$(cat {shq(str(kickoff))})"'


def execute(workspace: Path, argv: list[str], kickoff: str) -> None:
    sys.stdout.flush()
    os.chdir(workspace)
    os.execvpe(argv[0], [*argv, "--", kickoff], os.environ)
