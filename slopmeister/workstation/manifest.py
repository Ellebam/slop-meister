"""What the home install places on this machine, and the bytes each entry should hold.

Both tools' global instruction files come from dist/ and are written in the same run, so
Claude Code and Codex are never on different revisions. settings.json, config.toml and the
Codex rules file are deliberately absent, they carry machine state the operator owns.
"""

from dataclasses import dataclass
from pathlib import Path

from slopmeister import paths
from slopmeister.paths import ROOT
from slopmeister.workstation import orca

EXEC = "exec"
# A service is reloaded on install, a launchd job on the Mac and a systemd user unit on Linux.
RELOAD = "reload"
VAULT_REPOSITORY = ".vault-git/obsidian.git"
OP_LIBRARY = ".local/lib/slopmeister-op"
CODEX_CONFIG = ".codex/config.toml"
# The phone's entry point is reloaded on install like the vault job. Its restart ends only the
# server's own phone sessions, never a worker, and the service manager starts it again,
# see docs/phone-access.md.
CLAUDE_LABEL = "local.claude-remote-control"
CLAUDE_UNIT = "claude-remote-control"
VAULT_LABEL = "local.vault-commit"
# On Linux the two Drive sync runs and the scheduled vault commit each have a timer.
VAULT_SYNC, DOCUMENTS_SYNC, VAULT_SWEEP = "drive-sync-vault", "drive-sync-documents", "vault-commit"
TIMERS = (VAULT_SYNC, DOCUMENTS_SYNC, VAULT_SWEEP)
SYNC_COMMAND = ".local/bin/slopmeister-drive-sync"
# Built once and never rebuilt, a rebuild is a new binary and macOS revokes its file-access
# consent, see docs/vault-version-control.md.
APPLET = ".vault-git/VaultCommit.app"
APPLET_SCRIPT = (
    'do shell script "/bin/bash " & quoted form of (POSIX path of (path to home folder)) '
    '& ".vault-git/bin/vault-commit.sh"'
)


@dataclass(frozen=True)
class Entry:
    source: str
    destination: str
    flag: str = ""

    @property
    def template(self) -> bool:
        return self.source.endswith(".tmpl")

    def expected(self, home: Path, root: Path = ROOT) -> bytes:
        """The source bytes, with $HOME substituted in a template the way launchd needs it."""
        data = (root / self.source).read_bytes()
        return data.replace(b"$HOME", str(home).encode()) if self.template else data

    @property
    def needs_vault_repository(self) -> bool:
        return self.destination.startswith(VAULT_REPOSITORY + "/")


def _agent(label: str, flag: str) -> Entry:
    return Entry(
        f"plots/home/launchd/{label}.plist.tmpl", f"Library/LaunchAgents/{label}.plist", flag
    )


def _unit(name: str, flag: str = "") -> Entry:
    return Entry(f"plots/home/systemd/{name}", f".config/systemd/user/{name}", flag)


COMMON = (
    Entry("dist/claude/CLAUDE.md", ".claude/CLAUDE.md"),
    Entry("dist/codex/AGENTS.md", ".codex/AGENTS.md"),
    Entry("plots/home/claude/skill-tracker-hook.sh", ".claude/skill-tracker-hook.sh", EXEC),
    Entry(
        "plots/home/claude/skill-tracker-tool-hook.sh", ".claude/skill-tracker-tool-hook.sh", EXEC
    ),
    Entry("plots/home/claude/statusline-command.sh", ".claude/statusline-command.sh", EXEC),
    Entry("plots/vault/bin/vaultgit", ".vault-git/bin/vaultgit", EXEC),
    Entry("plots/vault/bin/vault-lock.py", ".vault-git/bin/vault-lock.py", EXEC),
    Entry("plots/vault/bin/slopmeister-vault", ".vault-git/bin/slopmeister-vault", EXEC),
    # The same launcher on PATH, because the instructions and the tools' allow rules name the
    # bare command. It resolves the runtime through $HOME, so the copy needs no wrapper.
    Entry("plots/vault/bin/slopmeister-vault", ".local/bin/slopmeister-vault", EXEC),
    Entry("plots/vault/bin/vault-commit.sh", ".vault-git/bin/vault-commit.sh", EXEC),
    # Slopmeister's op, first on PATH because the dotfiles put ~/.local/bin first in every shell.
    # It picks the tier of a marked session's op run, see docs/1password-access.md.
    Entry("plots/home/bin/op", ".local/bin/op", EXEC),
    Entry("slopmeister/__init__.py", f"{OP_LIBRARY}/slopmeister/__init__.py"),
    Entry("slopmeister/session/__init__.py", f"{OP_LIBRARY}/slopmeister/session/__init__.py"),
    Entry("slopmeister/session/secret_run.py", f"{OP_LIBRARY}/slopmeister/session/secret_run.py"),
    Entry(
        "slopmeister/session/secret_metadata.py",
        f"{OP_LIBRARY}/slopmeister/session/secret_metadata.py",
    ),
    Entry("slopmeister/session/secret_env.py", f"{OP_LIBRARY}/slopmeister/session/secret_env.py"),
    Entry("slopmeister/session/secret_tier.py", f"{OP_LIBRARY}/slopmeister/session/secret_tier.py"),
    Entry(
        "slopmeister/session/secret_approval.py",
        f"{OP_LIBRARY}/slopmeister/session/secret_approval.py",
    ),
    Entry("slopmeister/vault/runtime/__init__.py", ".vault-git/lib/slopmeister_vault/__init__.py"),
    Entry("slopmeister/vault/runtime/__main__.py", ".vault-git/lib/slopmeister_vault/__main__.py"),
    Entry(
        "slopmeister/vault/runtime/repository.py",
        ".vault-git/lib/slopmeister_vault/repository.py",
    ),
    Entry(
        "slopmeister/vault/runtime/initialization.py",
        ".vault-git/lib/slopmeister_vault/initialization.py",
    ),
    Entry("slopmeister/vault/runtime/links.py", ".vault-git/lib/slopmeister_vault/links.py"),
    Entry(
        "slopmeister/vault/runtime/environment.py",
        ".vault-git/lib/slopmeister_vault/environment.py",
    ),
    Entry("slopmeister/vault/runtime/lint.py", ".vault-git/lib/slopmeister_vault/lint.py"),
    Entry(
        "slopmeister/vault/runtime/conflicts.py",
        ".vault-git/lib/slopmeister_vault/conflicts.py",
    ),
    Entry("slopmeister/vault/runtime/obsidian.py", ".vault-git/lib/slopmeister_vault/obsidian.py"),
    Entry(
        "slopmeister/vault/runtime/retro_legacy.py",
        ".vault-git/lib/slopmeister_vault/retro_legacy.py",
    ),
    Entry("slopmeister/vault/runtime/exclude", ".vault-git/lib/slopmeister_vault/exclude"),
    Entry("slopmeister/vault/runtime/exclude", f"{VAULT_REPOSITORY}/info/exclude"),
)
# The Mac runs the vault job through launchd and an applet, and Google's client does its sync.
SERVICES = {
    "darwin": (_agent(VAULT_LABEL, RELOAD), _agent(CLAUDE_LABEL, RELOAD)),
    "linux": (
        Entry(
            f"plots/home/systemd/{CLAUDE_UNIT}.service",
            f".config/systemd/user/{CLAUDE_UNIT}.service",
            RELOAD,
        ),
        Entry("plots/home/drive/drive-sync.sh", SYNC_COMMAND, EXEC),
        # A timer starts its service, so only the timer is enabled, after the service exists.
        *(_unit(f"{name}.service") for name in TIMERS),
        *(_unit(f"{name}.timer", RELOAD) for name in TIMERS),
    ),
}


def entries() -> tuple[Entry, ...]:
    return (*COMMON, *SERVICES[paths.platform()])


def mac_only() -> tuple[str, ...]:
    """Orca's settings file and the applet, which have their own installers."""
    return (orca.NAME, APPLET) if paths.platform() == "darwin" else ()


def names() -> tuple[str, ...]:
    return (*(entry.destination for entry in entries()), CODEX_CONFIG, *mac_only())
