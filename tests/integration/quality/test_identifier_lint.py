"""The identifier and style rules of `slopmeister quality` over a scratch repository."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.quality import identifiers
from tests.support.repos import git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]
PROBE = "synthetic-sensitive-value"


def _fixture(tmp_path: Path) -> Path:
    root = scratch_repo(tmp_path / "slopmeister")
    for relative in ("plots/home/global.md", "plots/example-client/target.md"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    git(root, "add", "plots")
    patterns = tmp_path / "private-patterns"
    patterns.write_text("# Synthetic test patterns\n\n" + re.escape(PROBE) + "\n")
    patterns.chmod(0o600)
    return root


def _quality(root: Path, patterns: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [str(ROOT / "bin/slopmeister"), "quality", "--root", str(root)]
    env = dict(
        os.environ,
        SLOPMEISTER_PRIVATE_PATTERNS=str(patterns or root.parent / "private-patterns"),
    )
    return subprocess.run(command, capture_output=True, text=True, check=False, env=env)


def test_identifier_lint_rejects_a_synthetic_plot_identifier(tmp_path):
    root = _fixture(tmp_path)
    assert _quality(root).returncode == 0
    target = root / "plots/example-client/target.md"
    original = target.read_bytes()
    target.write_text(target.read_text() + f"\nSynthetic lint probe {PROBE}\n")
    result = _quality(root)
    assert result.returncode != 0
    lines = len(target.read_text().splitlines())
    assert f"plots/example-client/target.md:{lines}: field identifier" in result.stdout
    target.write_bytes(original)
    assert _quality(root).returncode == 0


def test_identifier_finding_never_prints_the_matched_text(tmp_path):
    """Escaping bug, the gate echoes the leaked fact into agent output and from there a PR."""
    root = _fixture(tmp_path)
    (root / "notes.txt").write_text(f"host {PROBE}\n")
    result = _quality(root)
    assert result.returncode != 0 and "notes.txt:1:" in result.stdout
    assert PROBE not in result.stdout + result.stderr


@pytest.mark.parametrize("kind", ("style", "budget", "syntax"))
def test_other_quality_findings_cannot_echo_a_private_path_or_symbol(tmp_path, kind):
    root = _fixture(tmp_path)
    target = root / "plots" / PROBE / "notes.md"
    target.parent.mkdir()
    target.write_text("One clause; another clause.\n")
    if kind != "style":
        target = root / "slopmeister" / f"{PROBE}.py"
        target.parent.mkdir()
        target.write_text("pass\n" * 401 if kind == "budget" else f"{PROBE} = !\n")
    result = _quality(root)
    assert result.returncode != 0 and "field identifier" in result.stdout
    assert PROBE not in result.stdout + result.stderr


@pytest.mark.parametrize("encoding", ("utf-16", "utf-16-be"))
def test_identifier_in_bom_marked_utf16_text_is_found(tmp_path, encoding):
    root = _fixture(tmp_path)
    data = f"host {PROBE}\n".encode(encoding)
    (root / "notes.txt").write_bytes(b"\xfe\xff" + data if encoding == "utf-16-be" else data)
    result = _quality(root)
    assert result.returncode != 0 and "notes.txt:1:" in result.stdout
    assert PROBE not in result.stdout + result.stderr


def test_identifier_patterns_are_case_insensitive_and_do_not_exempt_the_checker(tmp_path):
    root = _fixture(tmp_path)
    source = root / "slopmeister/quality/identifiers.py"
    source.parent.mkdir(parents=True)
    source.write_text(f"# {PROBE.upper()}\n")
    result = _quality(root)
    assert result.returncode != 0
    assert "slopmeister/quality/identifiers.py:1: field identifier" in result.stdout
    assert PROBE.upper() not in result.stdout + result.stderr


@pytest.mark.parametrize("kind", ("missing", "inside", "directory"))
def test_explicit_unsafe_pattern_source_fails_without_exposing_its_contents(tmp_path, kind):
    root = _fixture(tmp_path)
    patterns = root.parent / "private-patterns"
    if kind == "missing":
        patterns.unlink()
    elif kind == "inside":
        patterns = patterns.rename(root / "patterns")
    else:
        patterns.unlink()
        patterns.mkdir()
    result = _quality(root, patterns)
    assert result.returncode != 0
    assert PROBE not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "contents,mode",
    [(PROBE.encode() + b"[", 0o600), (PROBE.encode(), 0o644), (b"x", 0o200), (b"\xff", 0o600)],
    ids=("invalid-regex", "public", "unreadable", "invalid-utf8"),
)
def test_invalid_pattern_contents_or_access_fail_closed(tmp_path, contents, mode):
    root = _fixture(tmp_path)
    patterns = root.parent / "private-patterns"
    patterns.write_bytes(contents)
    patterns.chmod(mode)
    result = _quality(root)
    assert result.returncode != 0
    assert PROBE not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_pattern_file_owned_by_another_user_is_refused(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    patterns = root.parent / "private-patterns"
    owner = patterns.stat().st_uid
    monkeypatch.setenv("SLOPMEISTER_PRIVATE_PATTERNS", str(patterns))
    monkeypatch.setattr(identifiers.os, "getuid", lambda: owner + 1)
    with pytest.raises(SlopmeisterError, match="owner-only") as error:
        identifiers.findings(root)
    assert PROBE not in str(error.value)


def test_missing_implicit_pattern_file_leaves_other_quality_checks_active(tmp_path):
    root = _fixture(tmp_path)
    home = tmp_path / "empty-home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if key != "SLOPMEISTER_PRIVATE_PATTERNS"}
    env["HOME"] = str(home)
    command = [str(ROOT / "bin/slopmeister"), "quality", "--root", str(root)]
    assert subprocess.run(command, env=env, capture_output=True).returncode == 0
    (root / "plots/home/global.md").write_text("line\n" * 201)
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "keep it under 200" in result.stdout


def test_identifier_in_a_link_target_is_found(tmp_path):
    """Escaping bug, a symlink carries the identifier in its target and is never read."""
    root = _fixture(tmp_path)
    (root / "pointer").symlink_to(f"/srv/{PROBE}/missing")
    assert "pointer:1: field identifier" in _quality(root).stdout


def test_allowlist_entry_cannot_cover_an_identifier(tmp_path):
    """Escaping bug, the one must-fix class becomes waivable through quality-allowlist.json."""
    root = _fixture(tmp_path)
    (root / "leak.sh").write_text(f"echo {PROBE}\n")
    entry = {
        "path": "leak.sh",
        "metric": "field_identifier",
        "symbol": "__file__",
        "ceiling": 2,
        "target": 1,
        "owner": "F9",
        "rationale": "an attempt to waive a leak",
    }
    (root / "quality-allowlist.json").write_text(json.dumps({"exceptions": [entry]}))
    result = _quality(root)
    assert result.returncode != 0
    assert "leak.sh:1: field identifier" in result.stdout


def test_semicolon_in_a_plot_source_fails(tmp_path):
    """Escaping bug, the writing rules stop being enforced when the Bash lint is deleted."""
    root = _fixture(tmp_path)
    (root / "plots/example-client/target.md").write_text("One clause; another clause.\n")
    (root / "plots/example-client/skills/x").mkdir(parents=True)
    (root / "plots/example-client/skills/x/SKILL.md").write_text(
        "Skills may; they follow their own form.\n"
    )
    result = _quality(root)
    assert (
        "plots/example-client/target.md carries an em dash or a mid-sentence semicolon"
        in result.stdout
    )
    assert "SKILL.md" not in result.stdout


def test_at_token_outside_backticks_fails(tmp_path):
    root = _fixture(tmp_path)
    (root / "plots/example-client/target.md").write_text(
        "Inside `@ok` passes.\nOutside @import fails.\n"
    )
    assert (
        "plots/example-client/target.md carries an @token outside backticks"
        in _quality(root).stdout
    )


def test_long_global_source_fails(tmp_path):
    root = _fixture(tmp_path)
    (root / "plots/home/global.md").write_text("line\n" * 201)
    assert "plots/home/global.md is 201 lines, keep it under 200" in _quality(root).stdout


def test_identifier_in_a_path_is_found_without_naming_the_path(tmp_path):
    """Escaping bug, a file named after a ticket passes the gate, or its finding prints the name."""
    root = _fixture(tmp_path)
    (root / f"notes-{PROBE}.md").write_text("plain\n")
    (root / f"data-{PROBE}.txt").write_text(f"host {PROBE}\n")
    result = _quality(root)
    listed = git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    notes, data = (
        sorted(listed).index(name) + 1 for name in (f"notes-{PROBE}.md", f"data-{PROBE}.txt")
    )
    assert result.returncode != 0
    assert f"committable path #{notes}: field identifier, list with:" in result.stdout
    assert f"committable path #{data}: field identifier, list with:" in result.stdout
    assert f"committable path #{data}:1: field identifier" in result.stdout
    assert PROBE not in result.stdout + result.stderr
