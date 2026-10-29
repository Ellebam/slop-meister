"""The launch being prepared, and the two ways a launch stops before delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess

from slopmeister.paths import codex_home, main_checkout

RED = "\033[0;31m"
REPORT = "; stop and report this to the operator"
NC = "\033[0m"
ROOT = Path(__file__).resolve().parent.parent.parent
CLI = ROOT / "bin/slopmeister"


class Stop(Exception):
    """End the launch with an exit code; the text, when any, goes to stderr."""

    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(text)
        self.code = code
        self.text = text


def die(message: str) -> Stop:
    return Stop(1, f"{RED}Error: {message}{NC}")


def plain(message: str) -> Stop:
    return Stop(1, message)


def pause(seconds: float) -> None:
    """The external sleep, as the shell launcher used, so process doubles can drive polling."""
    subprocess.run(["sleep", str(seconds)], check=True)


# The home-installed op reads this mark and then picks the tier of an op run and refuses
# value-printing commands, see docs/1password-access.md. Without it, the operator's own
# terminals keep the real op.
BROKER_MARK = "SLOPMEISTER_SECRET_BROKER=1"


def shq(value: str) -> str:
    """Single-quote a value for the shell line the tab runs, the idiom the receipts pin."""
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class Delivery:
    pid: int
    evidence: str = ""
    session: str = ""


@dataclass
class Launch:
    plot: str
    name: str
    repo_arg: str
    tool: str = "claude"
    issue: str = ""
    issue_id: str = ""
    note: str = ""
    handoff: str = ""
    model: str = ""
    redispatch: bool = False
    abandon: bool = False
    manager: bool = False
    directory_requested: bool = False
    model_set: bool = False
    extra: list[str] = field(default_factory=list)
    service_actions: bool = False
    git_prompts: bool = False
    approval_required: bool = False
    delivery: str = ""
    tasks: str = ""
    repo: Path | None = None
    claim_managed: bool = False
    claim_target: str = ""
    claim_model: str = ""
    lock_fd: int | None = None
    wt_file: str = ""
    wt_file_name: str = ""
    claude_bin: str = ""
    opencode_bin: str = ""
    codex_baseline: set[int] = field(default_factory=set)
    claude_root: Path | None = None
    kickoff: str = ""
    wt: Path = Path()
    claude_wt: Path = Path()
    grants: list[str] = field(default_factory=list)
    session_id: str = ""
    line: str = ""
    open_attempted: bool = False
    native_pending: bool = False
    native_server_pins: bool = True
    scratch: Path | None = None

    @property
    def directory(self) -> bool:
        return self.directory_requested or not self.repo_arg

    @property
    def codex_home(self) -> Path:
        return codex_home()

    @property
    def codex_bin(self) -> Path:
        return Path.home() / ".local/bin/codex"

    @property
    def state_dir(self) -> Path:
        return Path(
            os.environ.get("PLOT_SESSION_STATE_DIR") or main_checkout() / "tmp/plot-session"
        )

    @property
    def kickoff_file(self) -> Path:
        return self.state_dir / f"{self.name}.md"

    @property
    def command_file(self) -> Path:
        return self.state_dir / f"{self.name}.command"

    @property
    def orca_file(self) -> Path:
        return self.state_dir / f"{self.name}.orca"

    @property
    def orca_workspace(self) -> Path:
        """A directory session has no repository, its tab opens in the Slopmeister checkout."""
        return ROOT if self.directory else self.wt

    @property
    def terminal_line(self) -> str:
        """A one-key shell startup question consumes the space before Orca types the command."""
        return f" /bin/zsh -l {shq(str(self.command_file))}"

    @property
    def claude_config(self) -> Path:
        return (
            self.claude_root / ".claude.json" if self.claude_root else Path.home() / ".claude.json"
        )

    @property
    def claude_projects(self) -> Path:
        return (
            self.claude_root / "projects" if self.claude_root else Path.home() / ".claude/projects"
        )
