"""Repository locations and the operator's environment. Nothing here names a field."""

from functools import cache
import os
from pathlib import Path
import subprocess
import sys

from slopmeister.errors import SlopmeisterError
from slopmeister.session import git_environment

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SRC = ROOT / "src"
PLOTS = ROOT / "plots"
SCRIPTS = ROOT / "scripts"
VAULT_VARIABLE = "SLOPMEISTER_VAULT"
# One path on every machine, so no tracked file names where a machine's sync client puts the
# vault. On the Mac it is a link into the synced folder, whose path carries the account.
DEFAULT_VAULT = ".slopmeister/vault"
PLATFORM_VARIABLE = "SLOPMEISTER_PLATFORM"
PLATFORMS = ("darwin", "linux")


@cache
def main_checkout() -> Path:
    """The main checkout of this repository, so state written from a worktree outlives it."""
    argv = ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"]
    # A variable that redirects Git must not decide where this checkout keeps its state.
    env = git_environment.child()
    for name in git_environment.REDIRECTS:
        env.pop(name, None)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
    except OSError, subprocess.TimeoutExpired:
        return ROOT
    common = Path(result.stdout.strip())
    return common.parent if not result.returncode and common.name == ".git" else ROOT


def vault(home: Path | None = None) -> Path:
    """SLOPMEISTER_VAULT when set, otherwise the per-machine link below the home directory."""
    value = os.environ.get(VAULT_VARIABLE)
    return Path(value).expanduser() if value else (home or Path.home()) / DEFAULT_VAULT


def platform() -> str:
    """This machine's system. A test names the other one, so both branches run in both gates."""
    name = os.environ.get(PLATFORM_VARIABLE) or sys.platform
    if name not in PLATFORMS:
        raise SlopmeisterError(f"unsupported system {name}, Slopmeister runs on macOS and Linux")
    return name


def plot_declarations(default: Path = PLOTS) -> Path:
    return Path(os.environ.get("PLOT_DECLARATIONS") or default)


def session_root() -> Path:
    return Path(os.environ.get("PLOT_SESSION_ROOT") or Path.home() / ".slopmeister/sessions")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _orca_selection(pointer: str) -> str:
    """The account home Orca's switcher names now, empty for System default."""
    path = Path(os.path.expanduser(pointer) if pointer.startswith("~/") else pointer)
    fix = "select an account or System default in Orca, then start again"
    try:
        selected = path.read_text().rstrip("\n")
    except FileNotFoundError:
        # Orca removes the file when it manages no account.
        return ""
    except (OSError, ValueError) as error:
        raise SlopmeisterError(
            f"cannot read Orca's Claude account selection {path}; {fix}"
        ) from error
    if not selected.isprintable():
        # A terminal would act on a control sequence in the name, also from an existing folder.
        raise SlopmeisterError(
            f"Orca's selected Claude account folder {ascii(selected)} has a non-printable "
            f"character in its name; {fix}"
        )
    if selected and not (os.path.isabs(selected) and os.path.isdir(selected)):
        raise SlopmeisterError(
            f"Orca's selected Claude account folder {selected} is not an existing directory; {fix}"
        )
    return selected


def claude_store(base: Path, *, switcher: bool = True) -> tuple[Path | None, bool]:
    """The Claude store for a start in `base` now, and whether Orca's account switcher chose it.

    This is the rule of the `claude` function Orca defines in its terminals, which a launch line
    bypasses. A relative CLAUDE_CONFIG_DIR is relative to the directory the session runs in.
    """
    value = os.environ.get("CLAUDE_CONFIG_DIR")
    if value == "":
        raise SlopmeisterError(
            "CLAUDE_CONFIG_DIR is empty, refusing to choose a Claude store; "
            "unset it or name a store"
        )
    pointer = os.environ.get("ORCA_CLAUDE_PROFILE_POINTER")
    user = os.environ.get("ORCA_CLAUDE_USER_CONFIG_DIR", "")
    operator_set = (
        value is not None
        and value != os.environ.get("ORCA_CLAUDE_INJECTED_CONFIG_DIR")
        and (not user or value.removesuffix("/") != user.removesuffix("/"))
    )
    if switcher and pointer and not operator_set:
        selected = _orca_selection(pointer)
        if selected:
            # Unchanged, because the exact text names the login's macOS Keychain entry.
            return Path(selected), True
        value = user if value and user else None
    return (None if value is None else Path(os.path.realpath(os.path.join(base, value)))), False
