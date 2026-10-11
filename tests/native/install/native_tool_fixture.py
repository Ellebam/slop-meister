"""Real native write tools with harmless consumers and actual approval assessments."""

from dataclasses import replace
import io
import json
from pathlib import Path

from tests.native.install.intent_fixture import IntentModel, prepared_action, text


def assessment(body):
    content = "\n".join(text(item.get("content", [])) for item in body["input"])
    planned = json.loads(
        content.split("Planned action JSON:\n")[1].split(">>> APPROVAL REQUEST END")[0]
    )
    command = planned["arguments"]["command"]
    assert planned["server"] in ("jira_write", "confluence_write") and planned["tool_name"] == "run"
    history = content.split(">>> TRANSCRIPT START")[1].split(">>> TRANSCRIPT END")[0]
    users = [line[6:] for line in history.splitlines() if line.startswith("user: ")]
    approved = any(
        a == "I approve this exact command:" and b == command
        for a, b in zip(users, users[1:], strict=False)
    )
    preview = "assistant: Preview command:\n" + command + "\n"
    approved |= (
        users[-1:] == ["I approve that one previewed command."] and history.count(preview) == 1
    )
    return dict(
        risk_level="low",
        user_authorization="high" if approved else "low",
        outcome="allow" if approved else "deny",
        rationale="STANDIN_INTENT_DECISION",
    )


class NativeModel(IntentModel):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw)
        if body.get("model") == "codex-auto-review":
            self.server.requests.append(body)
            self.request_path().parent.mkdir(parents=True, exist_ok=True)
            self.request_path().write_text(json.dumps(body, indent=2))
            self.reply_text(body, json.dumps(assessment(body)))
        else:
            self.rfile = io.BytesIO(raw)
            super().do_POST()

    def reply_stream(self, events):
        for event in events:
            for item in [event.get("item"), *event.get("response", {}).get("output", [])]:
                if (
                    item
                    and item.get("type") == "function_call"
                    and item["name"].startswith("mcp__")
                ):
                    item["namespace"], item["name"] = item["name"].rsplit("__", 1)
        super().reply_stream(events)


def prepared_native(root, tool, action):
    world = prepared_action(root, tool, action)
    world.server.RequestHandlerClass = NativeModel
    alias = action.replace("-", "_")
    if tool == "codex":
        argv = [
            *world.client.argv[:2],
            "--approve-for-me",
            "-c",
            "mcp_optional_startup_grace_ms=0",
            *world.client.argv[2:],
        ]
    else:
        argv = list(world.client.argv)
        argv[argv.index("--tools") + 1] = "Bash,mcp__" + alias + "__run"
        argv[-2:-2] = ["--mcp-config", str(world.client.cwd / ".claude/service-actions/mcp.json")]
        home = Path(world.client.env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings = json.loads(home.read_text())
        settings["permissions"]["allow"].append("mcp__" + alias + "__*")
        home.write_text(json.dumps(settings))
    world.client = replace(world.client, argv=argv)
    return world


def marker_consumer(world):
    path = world.entry.parent / "service_actions/supervisor.py"
    path.chmod(0o644)
    path.write_text(
        "import json\nfrom pathlib import Path\nfrom .native_gate import require_consumer\n"
        "ROOT=Path(__file__).resolve().parent.parent\n"
        "def main(argv,**kwargs):\n"
        " try: require_consumer(ROOT,json.loads((ROOT/'config.json').read_text()).get('native'))\n"
        " except ValueError as error: print(json.dumps({'result':str(error)})); return 1\n"
        " print('STANDIN_WRITE'); return 0\n"
    )
    path.chmod(0o444)
