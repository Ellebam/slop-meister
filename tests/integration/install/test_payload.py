"""Installer payloads are fixed snapshots with complete native configuration."""

import hashlib
import json
import tomllib

from slopmeister.install import snapshot
from slopmeister.install.entries import entry_text
from tests.integration.install.installer_helpers import ROOT, install, prepared, state


def test_snapshot_contains_exact_helper_and_complete_skill_payload(installed):
    workspace = installed.workspace
    path, saved = state(workspace)
    helper = path.parent / "config-install.py"
    bound = snapshot.verify(path.parent)
    assert saved["snapshot"] == str(bound)
    assert helper.read_text() == entry_text("slopmeister.session.verify", bound)
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == saved["helper_sha256"]
    for tool, native in (("claude", ".claude"), ("codex", ".agents")):
        source = ROOT / f"dist/{tool}/targets/example-app/skills"
        for file in source.rglob("*"):
            if file.is_file():
                relative = f"{native}/skills/{file.relative_to(source)}"
                delivered = workspace / relative
                program = snapshot.program(relative)
                expected = entry_text(program, bound).encode() if program else file.read_bytes()
                assert delivered.read_bytes() == expected, relative


def test_native_settings_and_remaining_helpers_are_snapshotted(installed):
    workspace = installed.workspace
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    project = json.loads((workspace / ".claude/settings.json").read_text())
    # The contract is rendered into dist, which is what the installer delivers.
    source = json.loads((ROOT / "dist/claude/settings.json").read_text())
    assert not access["hooks"] and "hooks" not in project
    assert access["autoMode"] == source["autoMode"]


def test_tampered_native_rule_is_refused_and_exact_restoration_recovers(installed):
    rule = installed.workspace / ".codex/rules/permissions.rules"
    original = rule.read_bytes()
    rule.write_bytes(original + b"\n# tamper\n")
    result = install(installed.env, "--check", "example-app", str(installed.workspace), ok=False)
    assert "saved session configuration" in result.stderr
    rule.write_bytes(original)
    install(installed.env, "--check", "example-app", str(installed.workspace))


def test_product_source_changes_do_not_change_delivered_snapshot(installed):
    agreement = installed.workspace / "AGENTS.md"
    helper = installed.workspace / ".agents/skills/sow/SKILL.md"
    agreement_before, helper_before = agreement.read_bytes(), helper.read_bytes()
    assert agreement_before.startswith(
        (ROOT / "dist/codex/plots/example-app.md").read_bytes().rstrip()
    )
    assert helper_before == (ROOT / "dist/codex/skills/sow/SKILL.md").read_bytes()
    install(installed.env, "--check", "example-app", str(installed.workspace))
    assert agreement.read_bytes() == agreement_before and helper.read_bytes() == helper_before


def test_deny_uses_native_one_command_git_approval(tmp_path):
    """Bug: deny either blocks the operator in Git hooks or gives the agent standing authority."""
    installed = prepared(tmp_path, "deny")
    workspace = installed.workspace
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    asks = access["permissions"]["ask"]
    rules = (workspace / ".codex/rules/git-permission.rules").read_text()
    for command in ("commit", "merge", "rebase", "cherry-pick", "revert", "am", "pull", "push"):
        assert f"Bash(git {command} *)" in asks
        assert f"Bash(git -C {workspace} {command} *)" in asks
        assert f'pattern=["git", "{command}"]' in rules
        assert f'pattern=["git", "-C", "{workspace}", "{command}"]' in rules
    claude_ship = workspace / ".claude/skills/ship/scripts/ship.py"
    codex_ship = workspace / ".agents/skills/ship/scripts/ship.py"
    assert f"Bash(python3 {claude_ship} *)" in asks
    assert f'pattern=["python3", "{codex_ship}"]' in rules
    assert 'decision="prompt"' in rules
    config = (workspace / ".codex/config.toml").read_text()
    assert "approval_policy" not in config
    assert "approvals_reviewer" not in config
    # Codex ignores and warns about a key under the sandbox table, the launcher owns approvals.
    assert set(tomllib.loads(config)["sandbox_workspace_write"]) == {"writable_roots"}
    for agreement in ("AGENTS.md", "CLAUDE.md"):
        text = (workspace / agreement).read_text()
        assert "no standing authority" in text
        assert "exact command once" in text


def test_allow_prompts_only_raw_push(installed):
    """Bug: shipping allow lets an agent bypass the fixed helper with a raw push."""
    workspace = installed.workspace
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    asks = [rule for rule in access["permissions"]["ask"] if rule.startswith("Bash(git ")]
    rules = (workspace / ".codex/rules/git-permission.rules").read_text()
    assert asks == ["Bash(git push *)", f"Bash(git -C {workspace} push *)"]
    assert 'pattern=["git", "push"]' in rules
    assert 'pattern=["git", "commit"]' not in rules
    assert "skills/ship/scripts/ship.py" not in rules
    config = (workspace / ".codex/config.toml").read_text()
    assert "approval_policy" not in config
    assert "approvals_reviewer" not in config


def test_shipping_deny_prompts_for_raw_push_and_fixed_ship(tmp_path):
    """Deny needs exact operator approval, not permanent refusal or standing authority."""
    installed = prepared(tmp_path, "allow", "deny")
    workspace = installed.workspace
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    asks = [rule for rule in access["permissions"]["ask"] if rule.startswith("Bash(git ")]
    rules = (workspace / ".codex/rules/git-permission.rules").read_text()
    assert asks == ["Bash(git push *)", f"Bash(git -C {workspace} push *)"]
    assert 'pattern=["git", "push"]' in rules
    assert 'pattern=["git", "commit"]' not in rules
    claude = json.loads((workspace / ".claude/access-settings.json").read_text())
    helper = workspace / ".claude/skills/ship/scripts/ship.py"
    assert f"Bash(python3 {helper} *)" in claude["permissions"]["ask"]
    codex_helper = workspace / ".agents/skills/ship/scripts/ship.py"
    assert f'pattern=["python3", "{codex_helper}"]' in rules
    config = (workspace / ".codex/config.toml").read_text()
    assert "approval_policy" not in config
    assert "approvals_reviewer" not in config
