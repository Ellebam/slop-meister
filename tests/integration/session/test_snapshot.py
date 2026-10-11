"A delivered entry resolving through the checkout instead of its snapshot breaks the session."

import json
from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.install import snapshot
from tests.integration.install.installer_helpers import (
    ROOT,
    environment,
    install,
    prepared,
    state,
)

SKILL_ENTRIES = [
    f"{root}{skill}/scripts/{script}.py"
    for root in snapshot.SKILL_ROOTS
    for skill, (script, _) in snapshot.SKILL_PROGRAMS.items()
]
ENTRIES = SKILL_ENTRIES + sorted(snapshot.STATE_ENTRIES)
# Arguments and exit code per entry name; the default is --help and a clean exit.
USAGE = {
    "config-install.py": ([], 1, "invalid delivered configuration helper operation"),
}


@pytest.fixture(params=("worktree", "directory"))
def session(request, tmp_path):
    """A prepared workspace of either shape: (workspace, state directory, environment)."""
    if request.param == "worktree":
        installed = prepared(tmp_path)
        return installed.workspace, state(installed.workspace)[0].parent, installed.env
    env = environment(tmp_path)
    workspace = tmp_path / "sessions/example-app"
    install(env, "--directory", "example-app", str(workspace))
    return workspace, workspace / ".slopmeister-config", env


def delivered(session, entry: str) -> Path | None:
    """The entry's installed path, or None when this shape does not deliver its skill."""
    workspace, state_dir, _ = session
    if entry in snapshot.STATE_ENTRIES:
        return state_dir / entry
    path = workspace / entry
    skill = Path(entry).parts[2] if entry.startswith(snapshot.SKILL_ROOTS) else None
    if skill and not (workspace / Path(*Path(entry).parts[:3])).is_dir():
        return None
    assert path.is_file(), entry
    return path


def run_entry(path: Path, env: dict, elsewhere: Path) -> subprocess.CompletedProcess:
    "Run the entry from an unrelated directory with import tracing, the checkout off the path."
    clean = {k: v for k, v in env.items() if not k.startswith("PYTHON")}
    args = USAGE.get(path.name, (["--help"], 0, ""))[0]
    return subprocess.run(
        [sys.executable, "-v", str(path), *args],
        cwd=elsewhere,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("entry", ENTRIES)
def test_every_entry_runs_from_its_snapshot_with_the_checkout_hidden(session, entry, tmp_path):
    path = delivered(session, entry)
    if path is None:
        pytest.skip(f"{entry} is not delivered to this workspace shape")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    result = run_entry(path, session[2], elsewhere)
    _, code, message = USAGE.get(path.name, ([], 0, ""))
    problems = [line for line in result.stderr.splitlines() if not line.startswith("#")]
    assert result.returncode == code and "Traceback" not in result.stderr, (
        result.returncode,
        "\n".join(problems[-25:]),
    )
    assert message in result.stderr
    origins = [line for line in result.stderr.splitlines() if "slopmeister/session" in line]
    assert origins, "the entry never imported the session subpackage"
    bound = str(session[1] / snapshot.DIRECTORY)
    assert all(bound in line for line in origins), origins[:5]
    assert not any(str(ROOT / "slopmeister") in line for line in origins), origins[:5]


def test_one_changed_snapshot_byte_is_refused_by_check(session):
    workspace, state_dir, env = session
    target = state_dir / snapshot.DIRECTORY / "slopmeister/session/verify.py"
    target.write_bytes(target.read_bytes() + b"#")
    directory = not (workspace / ".git").exists()
    result = install(env, "--check", "example-app", str(workspace), ok=False)
    assert "changed since preparation" in result.stderr, (directory, result.stderr)


def test_module_rewritten_with_its_manifest_is_refused_by_check(session):
    """Escaping bug: coordinated drift passes a manifest that lives inside the snapshot."""
    workspace, state_dir, env = session
    root = state_dir / snapshot.DIRECTORY
    target = root / "slopmeister/session/verify.py"
    target.write_bytes(target.read_bytes() + b"#")
    manifest = json.loads((root / snapshot.MANIFEST).read_text())
    manifest["slopmeister/session/verify.py"] = snapshot.digest(target)
    (root / snapshot.MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result = install(env, "--check", "example-app", str(workspace), ok=False)
    assert "differs from the saved record" in result.stderr, result.stderr
