"""The session snapshot, the session subpackage copied into the state directory under a manifest."""

import hashlib
import json
from pathlib import Path
import shutil

from slopmeister.errors import SlopmeisterError
from slopmeister.install.entries import entry_text

DIRECTORY = "snapshot"
MANIFEST = "manifest.json"
PACKAGE_INIT = "slopmeister/__init__.py"
SESSION = "slopmeister/session"
FILE_MODE = 0o644
DIRECTORY_MODE = 0o755
# Skill to (script name, program): the entry sits at <skill>/scripts/<script>.py in either tool.
SKILL_PROGRAMS = {
    "browser-login": ("browser", "slopmeister.session.browser_login"),
    "bloom": ("bloom", "slopmeister.session.bloom"),
    "ship": ("ship", "slopmeister.session.ship"),
    "update-prs": ("update", "slopmeister.session.update_pr"),
    "vault-todos": ("vault_todos", "slopmeister.session.vault_todos"),
}
STATE_ENTRIES = {
    "config-install.py": "slopmeister.session.verify",
}
SKILL_ROOTS = (".claude/skills/", ".agents/skills/")


def sources(root: Path) -> list[Path]:
    """List the package marker, session modules and the service-action OpenSSL configuration."""
    session = root / SESSION
    modules = [p for p in sorted(session.rglob("*.py")) if "__pycache__" not in p.parts]
    return [root / PACKAGE_INIT, *modules, *session.glob("service_actions/openssl.cnf")]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(root: Path, state_dir: Path) -> Path:
    """Copy the session subpackage into the state directory and record every file's digest."""
    snapshot = state_dir / DIRECTORY
    manifest: dict[str, str] = {}
    for source in sources(root):
        relative = source.relative_to(root)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(FILE_MODE)
        manifest[str(relative)] = digest(target)
    for directory in [snapshot, *(p for p in snapshot.rglob("*") if p.is_dir())]:
        directory.chmod(DIRECTORY_MODE)
    (snapshot / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (snapshot / MANIFEST).chmod(FILE_MODE)
    return snapshot


def present(snapshot: Path) -> dict[str, str]:
    """Every regular file under the snapshot with its digest, refusing symlinks anywhere."""
    found: dict[str, str] = {}
    for path in sorted(snapshot.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise SlopmeisterError(f"session snapshot contains a symlink: {path}")
        if path.is_file() and path.name != MANIFEST:
            found[str(path.relative_to(snapshot))] = digest(path)
    return found


def verify(state_dir: Path, recorded: str | None = None) -> Path:
    """The snapshot matches its manifest, and the manifest matches the digest saved outside it.

    The manifest lives inside the writable snapshot it describes, so a module rewritten together
    with its manifest still agrees with itself. Only a digest recorded elsewhere catches that.
    """
    snapshot = state_dir / DIRECTORY
    manifest_path = snapshot / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SlopmeisterError("session snapshot manifest is missing")
    if recorded is not None and digest(manifest_path) != recorded:
        raise SlopmeisterError("session snapshot manifest differs from the saved record")
    manifest = json.loads(manifest_path.read_text())
    if present(snapshot) != manifest:
        raise SlopmeisterError("session snapshot changed since preparation")
    return snapshot


def program(delivered: str) -> str | None:
    """The session program behind a delivered path, or None for a file that is not an entry."""
    for prefix in SKILL_ROOTS:
        if delivered.startswith(prefix):
            skill, _, tail = delivered.removeprefix(prefix).partition("/")
            script, module = SKILL_PROGRAMS.get(skill, ("", ""))
            return module if module and tail == f"scripts/{script}.py" else None
    return None


def bake(files: dict[str, tuple[bytes, int]], snapshot: Path) -> None:
    """Replace every delivered entry in the payload with its thin entry bound to the snapshot."""
    for delivered, (_, mode) in list(files.items()):
        module = program(delivered)
        if module:
            files[delivered] = (entry_text(module, snapshot).encode(), mode)


def state_entries(state_dir: Path, snapshot: Path) -> dict[str, str]:
    """Write the state directory's own entries and return each one's digest by name."""
    digests = {}
    for name, module in STATE_ENTRIES.items():
        path = state_dir / name
        path.write_text(entry_text(module, snapshot))
        path.chmod(0o700)
        digests[name] = digest(path)
    return digests
