"""The Task targets and the check catalogue reach the package, with arguments intact."""

import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPACED = "/tmp/vault with spaces"


def dry(*args: str) -> subprocess.CompletedProcess[str]:
    # CI makes Task colour its output, the comparisons are over plain text.
    env = {**os.environ, "NO_COLOR": "1"}
    return subprocess.run(
        ["task", "--dry", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, env=env
    )


def test_check_target_delegates_to_the_runner():
    result = dry("check", "--", SPACED)
    assert result.returncode == 0
    assert f"bin/slopmeister check '{SPACED}'" in result.stderr + result.stdout


def test_tools_target_is_exactly_the_locked_sync():
    assert (dry("tools").stderr + dry("tools").stdout).strip() == "task: [tools] uv sync --locked"


def test_home_install_installs_everything_unless_entries_are_named():
    """Escaping bug, the prompt's removal leaves a bare task home:install that writes nothing."""
    assert "workstation install --all" in dry("home:install").stderr
    named = dry("home:install", "--", ".claude/CLAUDE.md").stderr
    assert "workstation install .claude/CLAUDE.md" in named and "--all" not in named


def test_catalogue_routes_the_vault_argument_to_product_drift():
    listing = subprocess.run(
        [str(ROOT / "bin/slopmeister"), "check", "--list", SPACED],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"bin/slopmeister workstation drift '{SPACED}'" in listing


def test_vault_targets_reach_the_package_and_preserve_the_separator():
    commit = dry("vault:commit", "--", "One line", "--", "fields/demo/note.md")
    assert commit.returncode == 0
    assert "bin/slopmeister vault commit 'One line' -- fields/demo/note.md" in (
        commit.stderr + commit.stdout
    )
    lint = dry("vault:lint", "--", "--area", "fields/demo")
    assert lint.returncode == 0
    assert "bin/slopmeister vault lint --area fields/demo" in lint.stderr + lint.stdout


@pytest.mark.parametrize("layout", ("source", "symlink", "copy"))
def test_onboarding_links_resolve_from_every_supported_skill_location(tmp_path, layout):
    source = ROOT / "src/skills/workstation/SKILL.md"
    skill = source
    if layout != "source":
        payload = tmp_path / "dist/codex/skills/workstation/SKILL.md"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(source.read_bytes())
        skill = tmp_path / ".agents/skills/workstation/SKILL.md"
        if layout == "symlink":
            skill.parents[2].mkdir()
            skill.parents[1].symlink_to("../dist/codex/skills", target_is_directory=True)
        else:
            skill.parent.mkdir(parents=True)
            skill.write_bytes(source.read_bytes())
    links = re.findall(r"\[[^]\n]*\]\(([^)\n]+)\)", skill.read_text())
    assert links
    for link in links:
        url = urlsplit(link)
        if not url.scheme and url.path:
            assert (skill.parent / unquote(url.path)).exists(), (layout, link)
    local = re.findall(r"`((?:docs|host|examples|slopmeister)/[^`<> ]+)`", skill.read_text())
    assert local and all((ROOT / path).exists() for path in local)


def test_optional_browser_install_is_explicit_pinned_and_uses_the_runtime_prefix():
    result = dry("browser:install")
    assert result.returncode == 0
    command = (result.stderr + result.stdout).split("\n", 1)[1]
    assert "from slopmeister.session.browser_state import data_home" in command
    assert 'npm ci --ignore-scripts --no-audit --no-fund --prefix "$prefix"' in command
    checked = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
