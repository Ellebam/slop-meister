"""Selected service-action payloads preserve native prompts and fixed inputs."""

import json
import re

import pytest

from slopmeister.install.service_actions import ActionContext, action_payload
from slopmeister.launch.model import Launch
from slopmeister.render.settings import service_binding
from slopmeister.session.service_actions.arguments import TABLES
from slopmeister.session.service_actions.constants import PYTHON
from tests.integration.install.helpers import ROOT, fixture, selected_context


@pytest.mark.parametrize("tool", ["codex", "claude"])
def test_writer_binding_uses_the_executable_the_launcher_runs(tmp_path, monkeypatch, tool):
    """Bug: a different Codex first on PATH blocks a correctly launched writer session."""
    monkeypatch.setattr("slopmeister.render.settings.shutil.which", lambda name: f"/foreign/{name}")
    context = ActionContext(ROOT, "example", {}, tmp_path)
    binding = service_binding(context, "." + tool, "jira-write")
    expected = Launch("example", "probe", "repo", tool="codex").codex_bin
    assert binding["cli"] == (str(expected) if tool == "codex" else "/foreign/claude")


def test_direct_entry_requires_approval_in_both_tools(tmp_path):
    """Bug: a selected read can run without review of its exact fixed entry."""
    context = selected_context(tmp_path)
    entries, permissions, instructions = action_payload(context)
    rules = entries[".codex/rules/service-actions.rules"][0].decode()
    for native in (".codex", ".claude"):
        entry = context.workspace / native / "service-actions/jira-read/entry.py"
        command = [str(PYTHON), "-E", "-s", "-S", str(entry)]
        assert json.dumps(command) in rules
        assert "Bash(" + " ".join(command) + " *)" in permissions["ask"]
        assert str(entry) in instructions
        assert native + "/service-actions/jira-read/entry.py" in entries
    assert all(
        'decision="forbidden"' in line
        for line in rules.splitlines()
        if "service_actions.supervisor" in line
    )


def test_delivery_has_both_native_prompts_without_copying_a_token(tmp_path):
    entries, permissions, instructions = action_payload(selected_context(tmp_path))
    assert not any(path.endswith("Taskfile.yml") for path in entries)
    for native in (".codex", ".claude"):
        prefix = native + "/service-actions/jira-read/"
        assert prefix + "config.json" in entries
        assert entries[prefix + "config.json"][1] == 0o400
        assert prefix + "service_actions/supervisor.py" in entries
    assert 'decision="prompt"' in entries[".codex/rules/service-actions.rules"][0].decode()
    assert permissions["ask"] and "jira-read" in instructions
    assert not any(name.endswith(".env") for name in entries)


@pytest.mark.parametrize("unsafe", ["permissions", "symlink"])
def test_unsafe_private_profile_is_rejected_before_delivery(tmp_path, unsafe):
    root, profiles, path = fixture(tmp_path)
    if unsafe == "permissions":
        path.chmod(0o644)
    else:
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
    context = ActionContext(
        root, "example", {"service_actions": ["jira-read"]}, tmp_path / "session", profiles
    )
    with pytest.raises(ValueError, match="profile"):
        action_payload(context)


@pytest.mark.parametrize(
    "action", ["jira-read", "confluence-read", "jira-write", "confluence-write"]
)
def test_instructions_cover_every_declared_operation(action):
    delivered = (ROOT / "dist/service-actions/instructions.md").read_text()
    table = TABLES[action]
    names = [*table.forms, *table.options]
    assert set(names) <= set(re.findall(r"--[a-z][a-z-]*", delivered))


@pytest.mark.parametrize("service", ["jira", "confluence"])
def test_write_action_reuses_its_service_profile_without_mutating_it(tmp_path, service):
    """Bug: enabling guarded writes requires duplicate connection/credential configurations."""
    root, profiles, path = fixture(tmp_path)
    source = profiles / "example" / (service + "-read.json")
    data = json.loads(path.read_text()) | {"action": service + "-read"}
    if service == "jira":
        data["backlog_jql"] = "project = TEST AND statusCategory != Done ORDER BY key ASC"
    source.write_text(json.dumps(data))
    source.chmod(0o600)
    original = source.read_bytes()
    context = ActionContext(
        root, "example", {"service_actions": [service + "-write"]}, tmp_path, profiles
    )
    entries = action_payload(context)[0]
    for native in (".claude", ".codex"):
        prefix = native + "/service-actions/" + service + "-write/"
        delivered = json.loads(entries[prefix + "config.json"][0])
        assert delivered["action"] == service + "-write" and "backlog_jql" not in delivered
        assert delivered["pat_ref"] == data["pat_ref"] and delivered["origin"] == data["origin"]
        assert prefix + "service_actions/" + service + "_write.py" in entries
    assert source.read_bytes() == original
    assert not (source.parent / (service + "-write.json")).exists()


def test_an_action_without_a_consumer_is_refused(tmp_path):
    root, profiles, _ = fixture(tmp_path)
    context = ActionContext(
        root, "example", {"service_actions": ["jira-delete"]}, tmp_path, profiles
    )
    with pytest.raises(ValueError, match="no checked-in fixed consumer"):
        action_payload(context)


@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
def test_write_without_central_intent_policy_is_refused(tmp_path, action):
    """Bug: deleting the central policy quietly delivers a write with generic read approval."""
    root, profiles, path = fixture(tmp_path)
    source = root / "src/permissions.toml"
    source.write_text(source.read_text().split("[[service_action]]")[0])
    source_action = action.replace("-write", "-read")
    written = profiles / "example" / (source_action + ".json")
    written.write_text(json.dumps(json.loads(path.read_text()) | {"action": source_action}))
    written.chmod(0o600)
    context = ActionContext(root, "example", {"service_actions": [action]}, tmp_path, profiles)
    with pytest.raises(ValueError, match="intent policy"):
        action_payload(context)


@pytest.mark.parametrize("action", ["jira-read", "jira-write", "confluence-write"])
def test_native_registration_is_delivered_only_to_write_enabled_plots(tmp_path, action):
    """Bug: write tools are absent, or their configuration leaks into read-only plots."""
    root, profiles, path = fixture(tmp_path)
    source_action = action.replace("-write", "-read")
    selected = profiles / "example" / (source_action + ".json")
    selected.write_text(json.dumps(json.loads(path.read_text()) | {"action": source_action}))
    selected.chmod(0o600)
    context = ActionContext(root, "example", {"service_actions": [action]}, tmp_path, profiles)
    entries, permissions, _ = action_payload(context)
    rules = entries[".codex/rules/service-actions.rules"][0].decode()
    assert (".claude/service-actions/mcp.json" in entries) == action.endswith("-write")
    assert (f"mcp__{action.replace('-', '_')}__run" in permissions["ask"]) == action.endswith(
        "-write"
    )
    assert 'pattern=["env"]' not in rules


def test_selected_write_registers_native_tools_instead_of_shell_prompts(tmp_path):
    """Bug: writes are delivered only as shell prefixes, so an outer wrapper skips approval."""
    root, profiles, path = fixture(tmp_path)
    context = ActionContext(
        root, "example", {"service_actions": ["jira-write"]}, tmp_path, profiles
    )
    entries, permissions, _ = action_payload(context)
    assert "mcp__jira_write__run" in permissions["ask"]
    servers = json.loads(entries[".claude/service-actions/mcp.json"][0])["mcpServers"]
    assert servers["jira_write"]["args"][-1].endswith("jira-write/native_tool.py")
    assert not any(rule.startswith("Bash(env ") for rule in permissions["ask"])
