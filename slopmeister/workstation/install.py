"""Write the named home entries, backing up every file it replaces."""

from collections.abc import Iterable
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess

from slopmeister import paths
from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.workstation import codex_config, manifest, orca, state
from slopmeister.workstation.manifest import APPLET, CODEX_CONFIG, EXEC, RELOAD, Entry

BACKUP_ROOT = ".slopmeister-backup"
STOPPED = {"darwin": "launchd job(s) not running", "linux": "systemd unit(s) not set up"}


def backup_dir(home: Path) -> Path:
    return home / BACKUP_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")


def select(names: Iterable[str]) -> set[str]:
    chosen, known = set(names), set(manifest.names())
    unknown = sorted(chosen - known)
    if unknown:
        raise UsageError(
            f"unknown entries {', '.join(unknown)}, choose from {', '.join(sorted(known))}"
        )
    return chosen


def _systemd(unit: str) -> bool:
    """Lingering starts the unit at boot without a login, see docs/phone-access.md."""
    steps = (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", unit],
        ["systemctl", "--user", "restart", unit],
        ["loginctl", "enable-linger"],
    )
    for step in steps:
        if subprocess.run(step, check=False).returncode != 0:
            print(f"  NOT set up, this step failed: {' '.join(step)}")
            return False
    print("  systemd unit enabled and restarted, lingering on")
    return True


def _reload(destination: Path, label: str) -> bool:
    """A failed bootstrap leaves the job stopped, so it is named, never counted as installed."""
    if paths.platform() == "linux":
        return _systemd(destination.name)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True, check=False)
    if (
        subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=False).returncode
        == 0
    ):
        print("  launchd job reloaded")
        return True
    print(f"  NOT running, load it with: launchctl bootstrap {domain} {destination}")
    return False


def _write(entry: Entry, home: Path, backups: Path) -> str:
    """Returns the label of a launchd job that did not come back, empty when all is well."""
    destination = home / entry.destination
    if destination.is_file():
        saved = backups / entry.destination
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, saved)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(entry.expected(home))
    if entry.flag == EXEC:
        destination.chmod(0o755)
    if entry.flag == RELOAD and not _reload(destination, destination.stem):
        return destination.stem
    return ""


def _applet(home: Path) -> bool:
    if shutil.which("osacompile") is None:
        print(f"  osacompile not found, skipping: {APPLET}")
        return False
    target = home / APPLET
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["osacompile", "-o", str(target), "-e", manifest.APPLET_SCRIPT]
    if subprocess.run(command, check=False).returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        print("  osacompile failed, build it by hand, see docs/vault-version-control.md")
        return False
    print(f"  built: {APPLET}")
    print("  first run blocks on a consent dialog, allow it once")
    return True


def _apply(item: state.Item, home: Path, backups: Path) -> tuple[int, str]:
    line = state.skipped(item)
    if line:
        print(line)
        return 0, ""
    if item.name in (CODEX_CONFIG, orca.NAME):
        if item.name == CODEX_CONFIG:
            codex_config.install(home, backups)
        else:
            orca.install(home, backups)
        print(f"  installed: {item.name}")
        return 1, ""
    if item.entry is None:
        return int(_applet(home)), ""
    stopped = _write(item.entry, home, backups)
    print(f"  installed: {item.name}")
    return 1, stopped


def _preflight(home: Path, items: list[state.Item], backups: Path) -> None:
    for item in items:
        link = state.link_in(home, item.name)
        if not link and item.pending and (home / item.name).is_file():
            link = state.link_in(home, (backups / item.name).relative_to(home))
        if link:
            raise SlopmeisterError(
                f"unsafe symlink: {link}. Resolve the link before retrying. Nothing written."
            )


def install(home: Path, chosen: set[str]) -> int:
    """Install the chosen pending entries. Returns the number written."""
    items = [item for item in state.items(home) if item.name in chosen]
    backups = backup_dir(home)
    _preflight(home, items, backups)
    if orca.NAME in chosen:
        orca.require_closed()
    if any(item.name == orca.NAME and item.pending for item in items):
        orca.validate(home)
    applied = [_apply(item, home, backups) for item in items]
    written = sum(count for count, _ in applied)
    stopped = [label for _, label in applied if label]
    print()
    if written:
        print(f"Installed {written} file(s). Backups in {backups}")
    else:
        print("Everything already up to date.")
    if APPLET in chosen and not (home / APPLET).exists():
        print(
            "The VaultCommit applet is still absent, the launchd job cannot reach the vault "
            "without it, build it by hand per docs/vault-version-control.md."
        )
    if stopped:
        raise SlopmeisterError(f"{STOPPED[paths.platform()]}: {', '.join(stopped)}")
    return written
