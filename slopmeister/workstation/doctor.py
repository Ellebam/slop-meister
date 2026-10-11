"""Read-only facts about this machine's setup, one result per requirement, for an agent."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shlex
import shutil
import stat

from slopmeister import paths
from slopmeister.session.service_actions import runtime
from slopmeister.workstation import host, manifest, orca, rules, state
from slopmeister.workstation.host import INSTALL, Result

TOOLS = (
    "git",
    "task",
    "uv",
    "gh",
    "glab",
    "claude",
    "codex",
    "rg",
    "op",
    "zsh",
    "lsof",
    "shellcheck",
    "jq",
)
LOGIN_FIX = {
    "gh": "ask the operator to run gh auth login",
    "glab": "ask the operator to run task glab:login, see docs/gitlab.md",
}
GLAB_LOGGED_IN = "Logged in to "
ORCA_FIX = {
    "missing": "install Orca, then follow docs/orca.md",
    "not running": "ask the operator to open Orca",
    "unreachable": "ask the operator to restart Orca, then run the doctor again",
    "off": "turn on Orca's agent status hooks, see docs/orca.md",
}
HOOKS_UNKNOWN = "fix orca:runtime first, or inspect Orca's agent status hooks, see docs/orca.md"
BUNDLE = "Backups/vault-history.bundle"
# The job writes the bundle once a day and only at the end of a run that worked, so one
# missed day plus slack means the job has stopped, whatever stopped it.
BUNDLE_MAX_AGE = timedelta(days=2)
HISTORY_FIX = (
    "read ~/.vault-git/vault-commit.log for the cause, then follow "
    "docs/vault-version-control.md, When the job stops"
)
RULES_FIX = "ask the operator to bring the live rule file in line with the template in plots/home/"
ONLINE_ONLY_FIX = "set the sync client to mirror the vault, see docs/vault-version-control.md"
# On Linux the operator installs a package that needs root, an agent never does.
SYSTEM_TOOLS = ("git", "gh", "glab", "rg", "op", "zsh", "lsof", "rclone", "shellcheck", "jq")
OPERATOR_INSTALLS = (
    "a system package that needs root, ask the operator to install it, see README.md"
)


def _tool(name: str) -> Result:
    if name == "codex":
        fixed = Path.home() / ".local/bin/codex"
        if fixed.is_file() and os.access(fixed, os.X_OK):
            return Result("tool:codex", "ok", str(fixed), "none")
        return Result(
            "tool:codex",
            "problem",
            "not executable: ~/.local/bin/codex",
            "install codex at ~/.local/bin/codex, see README.md",
        )
    path = shutil.which(name)
    if path:
        return Result(f"tool:{name}", "ok", path, "none")
    needs_root = paths.platform() == "linux" and name in SYSTEM_TOOLS
    fix = OPERATOR_INSTALLS if needs_root else f"install {name}, see README.md"
    return Result(f"tool:{name}", "problem", "not on PATH", fix)


def cli_login(tool: str) -> Result:
    """The exit code only, the status output of gh and glab names hosts and accounts."""
    name, fix = f"login:{tool}", LOGIN_FIX[tool]
    code, output = host.run(tool, "auth", "status")
    if code is None:
        return Result(name, "unknown", output, fix)
    evidence = f"{tool} auth status exited {code}"
    # glab always lists gitlab.com and fails it without a token, so one working host is a login.
    if code and tool == "glab" and GLAB_LOGGED_IN in output:
        return Result(name, "ok", f"{evidence}, one host is logged in", fix)
    return Result(name, "ok" if code == 0 else "problem", evidence, fix)


def claude_login() -> Result:
    fix = "ask the operator to run claude auth login"
    code, output = host.run("claude", "auth", "status")
    try:
        logged_in = json.loads(output).get("loggedIn") if code is not None else None
    except ValueError, AttributeError:
        logged_in = None
    if type(logged_in) is not bool:
        evidence = output if code is None else "no loggedIn answer from claude auth status"
        return Result("login:claude", "unknown", evidence, fix)
    evidence = f"claude auth status exited {code}, loggedIn={logged_in}"
    if logged_in and code != 0:
        return Result("login:claude", "unknown", evidence, fix)
    return Result("login:claude", "ok" if logged_in else "problem", evidence, fix)


def codex_login() -> Result:
    """The exit code only, the status output names the account."""
    fix = "ask the operator to run ~/.local/bin/codex login"
    code, output = host.run(str(Path.home() / ".local/bin/codex"), "login", "status")
    if code is None:
        return Result("login:codex", "unknown", output, fix)
    evidence = f"codex login status exited {code}"
    return Result("login:codex", "ok" if code == 0 else "problem", evidence, fix)


def _service_actions() -> Result:
    """The fixed programs a service action runs with, read the way the action itself reads them."""
    missing = runtime.missing()
    if missing:
        evidence = "missing: " + ", ".join(missing)
        return Result("service-actions", "problem", evidence, "see docs/service-actions.md")
    return Result("service-actions", "ok", "every fixed program is present", "none")


def _orca() -> list[Result]:
    health = orca.health()
    runtime, hooks = health["runtime"], health["hooks"]
    status = "ok" if runtime == "running" else "problem"
    fix = ORCA_FIX.get(runtime, "none")
    if runtime == "missing" and paths.platform() == "linux":
        fix = OPERATOR_INSTALLS
    found = Result("orca:runtime", status, runtime, fix)
    if hooks not in ("on", "off"):
        return [found, Result("orca:hooks", "unknown", hooks, HOOKS_UNKNOWN)]
    status = "ok" if hooks == "on" else "problem"
    return [found, Result("orca:hooks", status, hooks, ORCA_FIX.get(hooks, "none"))]


def _home_install(home: Path, optional: set[str]) -> Result:
    items = [item for item in state.items(home) if item.name not in optional]
    pending = [f"{item.status}: {item.name}" for item in items if item.pending]
    if pending:
        fix = f"{INSTALL} -- {shlex.join(item.name for item in items if item.pending)}"
        return Result("home-install", "problem", "; ".join(pending), fix)
    blocked = [item.name for item in items if item.status == state.BLOCKED]
    if blocked:
        evidence = f"{state.BLOCKED}: {', '.join(blocked)}"
        return Result("home-install", "unknown", evidence, "fix vault-repository first")
    return Result("home-install", "ok", "every required home entry matches its source", "none")


def _rules(home: Path) -> Result:
    """Template lines only, the live files hold approvals that must not reach agent output."""
    lines = [line.strip() for line in rules.report(home)]
    stale = [line for line in lines if not line.startswith(rules.PRESENT)]
    if stale:
        return Result("rules", "problem", "; ".join(stale), RULES_FIX)
    return Result("rules", "ok", "every template rule is in the live rule files", "none")


def vault_path(given: str | None, home: Path) -> Path:
    """The command line wins over SLOPMEISTER_VAULT, which wins over the per-machine link."""
    return Path(given).expanduser() if given else paths.vault(home)


def vault_problem(vault: Path) -> str | None:
    for directory in (vault, vault / "_system"):
        if not directory.is_dir():
            return f"Directory not found: {directory}"
    if next(vault.rglob("*.md"), None) is None:
        return f"No Markdown files found in vault: {vault}"
    return None


def _vault_history(vault: Path) -> Result:
    name = "vault-history"
    bundle = vault.resolve().parent / BUNDLE
    if not bundle.is_file():
        return Result(name, "problem", f"no bundle at {bundle}", HISTORY_FIX)
    written = datetime.fromtimestamp(bundle.stat().st_mtime)
    evidence = f"{bundle} last written {written:%F %H:%M}"
    if datetime.now() - written > BUNDLE_MAX_AGE:
        return Result(name, "problem", f"{evidence}, older than two days", HISTORY_FIX)
    return Result(name, "ok", evidence, "none")


def _online_only(path: Path) -> bool:
    flag = getattr(stat, "SF_DATALESS", 0)
    return bool(getattr(path.lstat(), "st_flags", 0) & flag)


def _vault_local(vault: Path) -> list[Result]:
    """Notes must be readable locally, including notes a Mac sync client keeps online only."""
    if not vault.is_dir():
        return [Result("vault-local", "unknown", "no vault folder to read", "fix vault first")]
    if not os.access(vault, os.R_OK | os.X_OK) or any(
        not os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0))
        for path in vault.rglob("*")
    ):
        return [
            Result("vault-local", "problem", "vault content is not readable", "fix file access")
        ]
    online = sorted(path.name for path in vault.rglob("*.md") if _online_only(path))
    if online:
        evidence = f"{len(online)} online-only note(s), first {online[0]}"
        return [Result("vault-local", "problem", evidence, ONLINE_ONLY_FIX)]
    return [Result("vault-local", "ok", "every note is on this disk", "none")]


def _vault(home: Path, given: str | None, history: bool) -> list[Result]:
    vault = vault_path(given, home)
    problem = vault_problem(vault)
    fix = f"link it, ln -s <vault folder> ~/{paths.DEFAULT_VAULT}, or pass --vault <path>"
    found = [Result("vault", "problem" if problem else "ok", problem or str(vault), fix)]
    if not history:
        return found + _vault_local(vault)
    repository = home / manifest.VAULT_REPOSITORY
    if (repository / "HEAD").is_file():
        found.append(Result("vault-repository", "ok", str(repository), "none"))
    else:
        fix = f"ask the operator, then run task vault:init -- {vault}"
        found.append(Result("vault-repository", "problem", f"no repository at {repository}", fix))
    found.append(_vault_history(vault))
    return found + _vault_local(vault)


def doctor(home: Path, vault_arg: str | None = None) -> list[Result]:
    history, drive, optional = host.home_setup(home)
    sync_tools = ("rclone",) if drive else ()
    return [
        *(_tool(name) for name in (*TOOLS, *sync_tools)),
        cli_login("gh"),
        cli_login("glab"),
        claude_login(),
        codex_login(),
        *host.services(home, history, drive),
        host.sleep_guard(),
        _service_actions(),
        *_orca(),
        _home_install(home, optional),
        _rules(home),
        *_vault(home, vault_arg, history),
        *(host.vault_rows(history, drive) if paths.platform() == "linux" else []),
    ]
