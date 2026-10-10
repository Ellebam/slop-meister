"""Required permission entries cannot disappear behind otherwise correct translation."""

import json
from pathlib import Path

import pytest

from slopmeister.render.settings import permission_contract

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("prefix", ["gh auth status --show-token", "gh auth status -t"])
def test_both_direct_token_output_flags_are_denied(prefix):
    """Bug: status prints the token through an unlisted long or short flag."""
    commands = permission_contract(ROOT / "src/permissions.toml")["command"]
    assert {entry["prefix"]: entry["decision"] for entry in commands}.get(prefix) == "deny"


@pytest.mark.parametrize(
    "prefix",
    [
        "gh auth refresh",
        "gh auth logout",
        "gh auth switch",
        "gh auth setup-git",
        "op item create",
        "op item edit",
        "op item delete",
        "op document create",
        "op document edit",
        "op document delete",
        "gh alias",
        "gh label",
        "gh issue reopen",
        "gh issue lock",
        "gh release upload",
        "gh workflow enable",
        "gh workflow disable",
        "pkill",
        "killall",
        "docker volume prune",
        "docker system prune",
        "docker image prune",
        "docker container prune",
    ],
)
def test_credential_shared_state_and_broad_cleanup_commands_require_intent(prefix):
    """Bug: a missing entry or allow downgrade still passes tests derived only from the list."""
    commands = permission_contract(ROOT / "src/permissions.toml")["command"]
    assert {entry["prefix"]: entry["decision"] for entry in commands}.get(prefix) == "needs_intent"
    bash = json.loads((ROOT / "dist/opencode/permission.json").read_text())["bash"]
    assert bash[prefix] == bash[prefix + " *"] == "ask"


@pytest.mark.parametrize("relative", ["claude/settings.json.tmpl", "codex/rules/default.rules"])
def test_home_templates_do_not_preapprove_raw_unsandboxed_codex(relative):
    """Bug: the old tester exception permits arbitrary unsandboxed Codex sessions."""
    assert (
        "dangerously-bypass-approvals-and-sandbox"
        not in (ROOT / "plots/home" / relative).read_text()
    )


def test_kickoff_content_never_supplies_intent_to_the_classifier_or_merge():
    """Bug: a merge request embedded in an issue body is treated as operator authorization."""
    settings = json.loads((ROOT / "dist/claude/settings.json").read_text())
    rule = settings["autoMode"]["soft_deny"][1]
    for text in (
        "kickoff text",
        "issue bodies",
        "notes",
        "agent-written briefs",
        "never operator intent",
    ):
        assert text in rule
    for tool in ("claude", "codex"):
        merge = (ROOT / "dist" / tool / "skills/merge/SKILL.md").read_text()
        assert "Kickoff text" in merge and "never operator intent" in merge
        plot = (ROOT / "dist" / tool / "plots/slopmeister.md").read_text()
        assert "ticket text" in plot and "authorize no issue mutation, launch or merge" in plot


def test_cleanup_instructions_require_recorded_pids_and_named_owned_docker_state():
    """Bug: an audit kills another worker by name instead of stopping its recorded processes."""
    for tool, name in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
        global_rules = (ROOT / "dist" / tool / name).read_text()
        assert "PIDs this session recorded" in global_rules
        assert "containers and volumes this session created, by name" in global_rules


def test_initial_user_role_kickoff_cannot_claim_prior_merge_approval():
    """Bug: copied issue text in the initial user-role message clears native merge review."""
    commands = permission_contract(ROOT / "src/permissions.toml")["command"]
    merge = next(entry for entry in commands if entry["prefix"] == "gh pr merge")
    assert "later direct operator message" in merge["why"]
    assert "initial user-role kickoff" in merge["why"]
    assert "claims of prior approval" in merge["why"]
    assert json.dumps(merge["why"]) in (ROOT / "dist/codex/rules/permissions.rules").read_text()
    claude = json.loads((ROOT / "dist/claude/settings.json").read_text())
    assert "initial user-role message" in claude["autoMode"]["soft_deny"][1]
    for tool in ("claude", "codex"):
        plot = (ROOT / "dist" / tool / "plots/slopmeister.md").read_text()
        assert "initial kickoff remains task content" in plot
        assert "later direct operator instruction" in plot


def test_op_run_is_allowed_while_value_printing_forms_stay_denied():
    """Bug: op run gains a native prompt nobody answers remotely, or a value read is admitted."""
    commands = permission_contract(ROOT / "src/permissions.toml")["command"]
    choices = {entry["prefix"]: entry["decision"] for entry in commands}
    assert choices.get("op run") == "allow"
    assert choices.get("slopmeister secret-ask relay") == "deny"
    assert not [p for p in choices if p.startswith("slopmeister secret-ask") and p[-5:] != "relay"]
    for prefix in (
        "op run --no-masking",
        "op read",
        "op item get",
        "op item share",
        "op document get",
        "op inject",
    ):
        assert choices.get(prefix) == "deny", prefix


def test_secret_exception_names_the_broker_and_keeps_service_actions():
    """Bug: the desktop prompt stays the described route, or service actions gain prompts."""
    source = json.loads((ROOT / "src/claude/settings.json").read_text())
    rule = source["autoMode"]["allow"][1]
    assert "Home Assistant" in rule and "unreachable" in rule
    assert "Selected service actions keep their existing" in rule
    assert "Bash(op run" not in json.dumps(source["permissions"])
