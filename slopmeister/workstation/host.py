"""The doctor's result, its bounded command read, and the reads that differ per system."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from slopmeister import paths
from slopmeister.dispatch import command
from slopmeister.workstation import manifest

TIMEOUT = 20
INSTALL = "ask the operator, then run task home:install"
UNIT = f"{manifest.CLAUDE_UNIT}.service"
# The installer skips an unchanged unit, so a unit that failed to start is repaired by hand.
UNIT_FIX = (
    f"{INSTALL} -- .config/systemd/user/{UNIT}, or when that file is unchanged run "
    f"systemctl --user enable --now {UNIT}, see docs/phone-access.md"
)
LINGER_FIX = "run loginctl enable-linger, see docs/agent-hosts.md"
PHONE_ENTRIES = {
    "darwin": f"Library/LaunchAgents/{manifest.CLAUDE_LABEL}.plist",
    "linux": f".config/systemd/user/{UNIT}",
}
TIMERS = {
    "vault-sync": manifest.VAULT_SYNC,
    "documents-sync": manifest.DOCUMENTS_SYNC,
    "vault-sweep": manifest.VAULT_SWEEP,
}
GUARD_FIX = f"{INSTALL} -- {manifest.SYNC_COMMAND}"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    evidence: str
    fix: str


def run(*argv: str) -> tuple[int | None, str]:
    """The exit code and output, or None and the reason when the probe itself cannot answer."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return None, f"{argv[0]} timed out after {TIMEOUT}s"
    except OSError as error:
        return None, f"{argv[0]} could not run: {error}"
    return done.returncode, (done.stdout + done.stderr).strip()


def _agent(label: str, must_run: bool) -> Result:
    name, fix = f"launchd:{label}", f"{INSTALL} -- Library/LaunchAgents/{label}.plist"
    code, output = run("launchctl", "print", f"gui/{os.getuid()}/{label}")
    if code is None:
        return Result(name, "unknown", output, fix)
    if code != 0:
        return Result(name, "problem", f"not loaded, launchctl print exited {code}", fix)
    if must_run and "state = running" not in output:
        return Result(name, "problem", "loaded but not running", "see docs/phone-access.md")
    return Result(name, "ok", "loaded" + (" and running" if must_run else ""), "none")


def _unit() -> Result:
    """Active alone is not enough, a unit that is not enabled is gone after the next reboot."""
    name, found = f"systemd:{manifest.CLAUDE_UNIT}", []
    for question in ("is-active", "is-enabled"):
        code, output = run("systemctl", "--user", question, UNIT)
        if code is None:
            return Result(name, "unknown", output, UNIT_FIX)
        found.append(output if code == 0 and output else f"{output or question} (exit {code})")
    status = "ok" if found == ["active", "enabled"] else "problem"
    return Result(name, status, ", ".join(found), UNIT_FIX)


def _linger() -> Result:
    """Without lingering the user's units stop at logout and never start at boot."""
    code, output = run("loginctl", "show-user", str(os.getuid()), "-p", "Linger", "--value")
    if code != 0:
        evidence = output or f"loginctl show-user exited {code}"
        return Result("linger", "unknown", evidence, LINGER_FIX)
    return Result("linger", "ok" if output == "yes" else "problem", f"Linger={output}", LINGER_FIX)


def _timer(name: str, unit: str) -> Result:
    """An enabled, active timer whose every run fails or refuses syncs nothing."""
    guide = "vault-version-control.md" if unit == manifest.VAULT_SWEEP else "drive-access.md"
    fix = (
        f"read journalctl --user -u {unit}.service and follow docs/{guide}, "
        f"or {INSTALL} -- .config/systemd/user/{unit}.timer"
    )
    found = []
    for question, kind in (
        ("is-active", "timer"),
        ("is-enabled", "timer"),
        ("is-failed", "service"),
    ):
        code, output = run("systemctl", "--user", question, f"{unit}.{kind}")
        if code is None:
            return Result(name, "unknown", output, fix)
        found.append(output or f"{question} exited {code}")
    status = "ok" if found[:2] == ["active", "enabled"] and found[2] != "failed" else "problem"
    return Result(name, status, ", ".join(found), fix)


def _delete_guard() -> Result:
    """The limit lives in the installed command, so that file is what shows the guard."""
    name, command = "vault-delete-guard", Path.home() / manifest.SYNC_COMMAND
    try:
        guarded = "--max-delete" in command.read_text()
    except OSError:
        return Result(name, "problem", f"no sync command at {command}", GUARD_FIX)
    evidence = f"{command} {'carries' if guarded else 'lacks'} --max-delete"
    return Result(name, "ok" if guarded else "problem", evidence, GUARD_FIX)


def home_setup(home: Path) -> tuple[bool, bool, set[str]]:
    """Installed evidence decides which optional home entries the doctor requires."""
    jobs = (
        {f"Library/LaunchAgents/{manifest.VAULT_LABEL}.plist"}
        if paths.platform() == "darwin"
        else {
            f".config/systemd/user/{manifest.VAULT_SWEEP}.{kind}" for kind in ("service", "timer")
        }
    )
    sync = {
        f".config/systemd/user/{name}.{kind}"
        for name in (manifest.VAULT_SYNC, manifest.DOCUMENTS_SYNC)
        for kind in ("service", "timer")
    } | {manifest.SYNC_COMMAND}
    history = any(os.path.lexists(home / name) for name in {*jobs, manifest.VAULT_REPOSITORY})
    drive = paths.platform() == "linux" and any(os.path.lexists(home / name) for name in sync)
    optional = set() if drive else sync
    if not history:
        optional |= jobs | {
            f"{manifest.VAULT_REPOSITORY}/info/exclude",
            ".vault-git/bin/vault-commit.sh",
            manifest.APPLET,
        }
    phone = PHONE_ENTRIES[paths.platform()]
    if not os.path.lexists(home / phone):
        optional.add(phone)
    return history, drive, optional


def vault_rows(history: bool, drive: bool) -> list[Result]:
    """Configured Linux timers retain their checks even when only part of the setup remains."""
    found = [
        _timer(name, unit)
        for name, unit in TIMERS.items()
        if (history if name == "vault-sweep" else drive)
    ]
    return found + ([_delete_guard()] if drive else [])


def services(home: Path, history: bool, drive: bool) -> list[Result]:
    phone = os.path.lexists(home / PHONE_ENTRIES[paths.platform()])
    if paths.platform() == "linux":
        return ([_unit()] if phone else []) + ([_linger()] if phone or history or drive else [])
    return [
        *([_agent(manifest.VAULT_LABEL, must_run=False)] if history else []),
        *([_agent(manifest.CLAUDE_LABEL, must_run=True)] if phone else []),
    ]


def sleep_guard() -> Result:
    guard = Path(command.sleep_guard()[0])
    if guard.is_file() and os.access(guard, os.X_OK):
        return Result("sleep-guard", "ok", str(guard), "none")
    fix = "restore it, the dispatcher refuses to start without it"
    return Result("sleep-guard", "problem", f"not found at {guard}", fix)
