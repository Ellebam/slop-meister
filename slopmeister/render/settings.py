"""Render the global layer and native tool settings."""

import json
from pathlib import Path
import shutil

from slopmeister.render.permissions import NATIVE, permission_contract
from slopmeister.render.permissions import render_settings as render_settings
from slopmeister.render.plots import HOME_RENDERINGS
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS


def render_home(plots: Path, out: Path, manifest: list) -> None:
    source = plots / "home" / "global.md"
    if not source.is_file():
        return
    text = source.read_text()
    for tool, filename, label in HOME_RENDERINGS:
        (out / tool).mkdir(parents=True, exist_ok=True)
        (out / tool / filename).write_text(text.replace("{{TOOL}}", label))
        manifest.append(("home", filename, "home", False, False))
    codex = plots / "home" / "codex" / "config.toml.tmpl"
    if codex.is_file():
        shutil.copy2(codex, out / "codex" / "config.toml")
        manifest.append(("home", "config.toml", "home", False, False))


def service_rules(
    patterns: list[list[str]], root: Path, action: str
) -> tuple[list[str], list[str]]:
    rules, asks = [], []
    why = (
        "Native approval review required for the complete selected read action. "
        "Verify operator authorization"
    )
    decision = "prompt"
    if action.endswith("-write"):
        contract = permission_contract(root / "src/permissions.toml")
        policy = next(
            (e for e in contract.get("service_action", []) if e["action"] == action), None
        )
        if policy is None:
            raise ValueError("selected write action has no central intent policy")
        return [], ["mcp__" + action.replace("-", "_") + "__run"]
    for command in patterns:
        rules.append(
            f"prefix_rule(pattern={json.dumps(command)}, decision={json.dumps(decision)}, "
            f"justification={json.dumps(why)})"
        )
        asks.append("Bash(" + " ".join(command) + " *)")
    return rules, asks


def service_binding(context, native: str, action: str) -> dict | bool:
    if not context.native:
        return False
    policies = permission_contract(context.root / "src/permissions.toml").get("service_action", [])
    policy = next((entry for entry in policies if entry["action"] == action), None)
    if policy is None:
        raise ValueError("selected write action has no central intent policy")
    tool = native.removeprefix(".")
    cli = str(Path.home() / ".local/bin/codex") if tool == "codex" else shutil.which(tool) or ""
    return dict(tool=tool, cli=cli, workspace=str(context.workspace), why=policy["why"])


def native_tools(context, writable: list[str]) -> bytes:
    registration = context.files.get(".claude/service-actions/mcp.json")
    result = 'project_root_markers = ["AGENTS.md"]\nproject_doc_fallback_filenames = []\n'
    roots = list(dict.fromkeys((*context.grants, *writable)))
    result += "[sandbox_workspace_write]\nwritable_roots = " + json.dumps(roots) + "\n"
    if registration:
        servers = json.loads(registration[0])["mcpServers"]
        policies = permission_contract(context.root / "src/permissions.toml")["service_action"]
        decisions = {
            entry["action"].replace("-", "_"): NATIVE[entry["decision"]] for entry in policies
        }
        for name, server in servers.items():
            args = [value.replace("/.claude/", "/.codex/") for value in server["args"]]
            result += f"\n[mcp_servers.{name}]\ncommand={json.dumps(server['command'])}\n"
            result += f"args={json.dumps(args)}\nrequired=true\ntool_timeout_sec=360\n"
            result += (
                f"[mcp_servers.{name}.tools.run]\napproval_mode={json.dumps(decisions[name])}\n"
            )
    return result.encode()


def service_registration(context) -> dict:
    actions = context.target.get("service_actions", [])
    servers = {
        action.replace("-", "_"): {
            "command": str(PYTHON),
            "args": [
                *PYTHON_FLAGS,
                str(context.workspace / ".claude/service-actions" / action / "native_tool.py"),
            ],
        }
        for action in actions
        if action.endswith("-write") and context.native
    }
    return (
        {
            ".claude/service-actions/mcp.json": (
                (json.dumps({"mcpServers": servers}) + "\n").encode(),
                0o444,
            )
        }
        if servers
        else {}
    )
