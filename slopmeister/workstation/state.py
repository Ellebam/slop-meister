"""One comparison of the home install against this machine, read by install, diff and drift."""

from dataclasses import dataclass
from pathlib import Path

from slopmeister.workstation import codex_config, manifest, orca
from slopmeister.workstation.manifest import APPLET, CODEX_CONFIG, VAULT_REPOSITORY, Entry

UNCHANGED = "unchanged"
MISSING = "missing"
DIFFERS = "differs"
UNSAFE = "unsafe symlink"
# The exclude file lives inside the vault repository, which vault:init creates and fills.
BLOCKED = "waiting for the vault repository"
PENDING = (MISSING, DIFFERS, UNSAFE)


@dataclass(frozen=True)
class Item:
    name: str
    status: str
    entry: Entry | None = None

    @property
    def pending(self) -> bool:
        return self.status in PENDING


def link_in(home: Path, name: str | Path) -> Path | None:
    """Check only managed components below the selected home, not its own ancestors."""
    path = home
    for part in Path(name).parts:
        path /= part
        if path.is_symlink():
            return path
    return None


def _status(entry: Entry, home: Path) -> str:
    if link_in(home, entry.destination):
        return UNSAFE
    if entry.needs_vault_repository and not (home / VAULT_REPOSITORY).is_dir():
        return BLOCKED
    destination = home / entry.destination
    if not destination.exists():
        return MISSING
    matches = destination.is_file() and destination.read_bytes() == entry.expected(home)
    return UNCHANGED if matches else DIFFERS


def items(home: Path) -> list[Item]:
    found = [Item(entry.destination, _status(entry, home), entry) for entry in manifest.entries()]
    found.append(
        Item(CODEX_CONFIG, UNSAFE if link_in(home, CODEX_CONFIG) else codex_config.status(home))
    )
    if manifest.mac_only():
        found.append(Item(orca.NAME, UNSAFE if link_in(home, orca.NAME) else orca.status(home)))
        if link_in(home, APPLET):
            applet = UNSAFE
        else:
            applet = UNCHANGED if (home / APPLET).exists() else MISSING
        found.append(Item(APPLET, applet))
    return found


def skipped(item: Item) -> str | None:
    """Report entries that cannot be installed or are already unchanged."""
    if item.status == BLOCKED:
        return f"  no vault repository yet, run task vault:init first, skipping: {item.name}"
    if item.status == UNSAFE:
        return f"  {UNSAFE}: {item.name}, resolve the link before installing"
    return None if item.pending else f"  unchanged: {item.name}"


def pending(home: Path) -> list[Item]:
    return [item for item in items(home) if item.pending]
