"""The update entry has fixed delivery and no direct-push exemption."""

import json

import pytest

from slopmeister.install import snapshot
from slopmeister.install.entries import entry_text
from tests.integration.install.installer_helpers import prepared, state


def test_allowed_repository_gets_only_the_fixed_update_entry(tmp_path):
    """Bug: a scheduled task could push directly or run an unbound update script."""
    installed = prepared(tmp_path)
    workspace = installed.workspace
    state_path, _ = state(workspace)
    bound = snapshot.verify(state_path.parent)
    assert snapshot.program(".agents/skills/update-prs/scripts/update.py") == (
        "slopmeister.session.update_pr"
    )
    for native in (".agents", ".claude"):
        entry = workspace / native / "skills/update-prs/scripts/update.py"
        assert entry.read_text() == entry_text("slopmeister.session.update_pr", bound)
    skill = (workspace / ".agents/skills/update-prs/SKILL.md").read_text()
    assert "absolute path" in skill and "JSON list of objects" in skill
    assert all(f'"{key}"' in skill for key in ("number", "head", "ci", "smoke", "fix"))
    codex = workspace / ".agents/skills/update-prs/scripts/update.py"
    rule = (workspace / ".codex/rules/update-pr.rules").read_text()
    assert f'pattern=["python3", "{codex}"]' in rule
    assert 'decision="allow"' in rule
    direct = (workspace / ".codex/rules/git-permission.rules").read_text()
    assert 'pattern=["git", "push"]' in direct
    assert 'decision="prompt"' in direct
    claude = json.loads((workspace / ".claude/access-settings.json").read_text())
    helper = workspace / ".claude/skills/update-prs/scripts/update.py"
    assert f"Bash(python3 {helper} *)" in claude["permissions"]["allow"]


@pytest.mark.parametrize("commit,shipping", [("deny", "allow"), ("allow", "deny")])
def test_denied_repository_cannot_run_update_entry_unattended(tmp_path, commit, shipping):
    """Bug: one missing repository permission granted autonomous PR writes."""
    workspace = prepared(tmp_path, commit, shipping).workspace
    assert not (workspace / ".codex/rules/update-pr.rules").exists()
    claude = json.loads((workspace / ".claude/access-settings.json").read_text())
    allowed = claude["permissions"].get("allow", [])
    assert not any("skills/update-prs/scripts/update.py" in rule for rule in allowed)
