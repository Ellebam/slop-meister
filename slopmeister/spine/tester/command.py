"""Native tester command construction for the existing three clients."""

import json
from pathlib import Path

from slopmeister.opencode import tester as opencode_tester
from slopmeister.spine.tester.validate import VERDICT_SCHEMA


def build_command(run: dict, root: Path) -> list[str]:
    if run["tool"] == "opencode":
        return opencode_tester.command(run)
    if run["tool"] == "codex":
        return [
            # Plugin refresh and the notify program outlive the CLI and trip the group check.
            "codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--disable", "plugins",
            "-C", run["checkout"], "--model", run["model"], "--config", "notify=[]",
            "--config", f'model_reasoning_effort="{run["effort"]}"',
            "--json", "--output-schema", str(root / "schema.json"),
            "--output-last-message", str(root / "verdict.raw.json"), "-",
        ]  # fmt: skip
    return [
        "claude", "-p", "--model", run["model"], "--effort", run["effort"],
        "--permission-mode", "auto", "--tools", "Bash,Read,Glob,Grep", "--strict-mcp-config",
        "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(VERDICT_SCHEMA),
    ]  # fmt: skip
