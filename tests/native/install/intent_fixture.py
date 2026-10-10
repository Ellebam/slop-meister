"""Real-client fixtures with valid approval assessments and native host responses."""

from dataclasses import replace
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tomllib
from types import SimpleNamespace

from slopmeister.session.service_actions.constants import PYTHON
from tests.integration.install.helpers import unlock_deliveries
from tests.integration.install.test_install_service_actions import _command, _fixture
from tests.native.install.test_permissions import client_command
from tests.support.standin import (
    StandIn,
    capture_server,
    messages_events,
    responses_events,
    tool_results,
)


def text(parts):
    if isinstance(parts, str):
        return parts
    return "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))


def assessment(body):
    content = "\n".join(text(item.get("content", [])) for item in body["input"])
    planned = json.loads(
        content.split("Planned action JSON:\n")[1].split(">>> APPROVAL REQUEST END")[0]
    )
    command = planned["command"][-1]
    history = content.split(">>> TRANSCRIPT START")[1].split(">>> TRANSCRIPT END")[0]
    users = [line[6:] for line in history.splitlines() if line.startswith("user: ")]
    retry = content.split(">>> APPROVAL REQUEST START")[1].split("Planned action JSON:")[0]
    guarded = "explicit operator approval" in retry.lower() and (
        "For commands that do not invoke a selected fixed write entry" not in retry
        or any(
            f"/service-actions/{a}/entry.py" in command for a in ("jira-write", "confluence-write")
        )
    )
    approved = any(
        first == "I approve this exact command:" and second == command
        for first, second in zip(users, users[1:], strict=False)
    )
    preview = "assistant: Preview command:\n" + command + "\n"
    approved |= (
        users[-1:] == ["I approve that one previewed command."] and history.count(preview) == 1
    )
    return {
        "risk_level": "low",
        "user_authorization": "high" if approved else "low",
        "outcome": "allow" if approved or not guarded else "deny",
        "rationale": "STANDIN_INTENT_DECISION",
    }


class IntentModel(StandIn):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if not self.path.split("?")[0].endswith(("/messages", "/responses")):
            self.reply_tokens()
            return
        self.server.requests.append(body)
        self.request_path().parent.mkdir(parents=True, exist_ok=True)
        self.request_path().write_text(json.dumps(body, indent=2))
        if body.get("model") == "codex-auto-review":
            self.reply_text(body, json.dumps(assessment(body)))
        elif "security monitor" in text(body.get("system", [])).lower():
            self.reply_text(body, "<severity>10</severity>")
        elif getattr(self.server, "preview", None):
            self.reply_text(body, "Preview command:\n" + self.server.preview)
        else:
            turn = len(tool_results(body))
            call = self.server.script[turn] if turn < len(self.server.script) else None
            events = (
                responses_events(call, turn)
                if self.path.split("?")[0].endswith("/responses")
                else messages_events(call, body, turn)
            )
            self.reply_stream(events)

    def reply_text(self, body, answer):
        if self.path.split("?")[0].endswith("/messages"):
            payload = messages_events(None, body, 0)[0]["message"]
            payload.update(content=[{"type": "text", "text": answer}], stop_reason="end_turn")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
            return
        events = responses_events(None, 0)
        for event in events:
            for item in [event.get("item"), *event.get("response", {}).get("output", [])]:
                if item:
                    item["content"][0]["text"] = answer
        self.reply_stream(events)


def prepared_action(root, tool, action):
    workspace, mode, env = _fixture(root / "install", "directory", action)
    action = action if isinstance(action, str) else action[0]
    profile = Path(env["HOME"]) / ".config/slopmeister/access/example-app"
    profile /= action.replace("-write", "-read") + ".json"
    data = json.loads(profile.read_text()) | {"token_file": str(root / "missing-token.env")}
    profile.write_text(json.dumps(data))
    _command(env, mode, "example-app", str(workspace))
    (root / "native").mkdir()
    server = capture_server(root / "requests", tool, [])
    server.RequestHandlerClass = IntentModel
    client = client_command(tool, root / "native", server.server_port)
    argv = [str(workspace) if arg == str(client.cwd) else arg for arg in client.argv]
    client = replace(client, cwd=workspace, argv=argv)
    entry = workspace / ("." + tool) / "service-actions" / action / "entry.py"
    output = workspace / "results/result.json"
    output.parent.mkdir(mode=0o700)
    output.write_bytes(b"")
    output.chmod(0o600)
    command = f"{PYTHON} -E -s -S {entry} --output {output} "
    command += (
        "--comment TEST-7 --body approved-text --if-updated 2026-09-01T10:00:00.000+0000"
        if action.startswith("jira")
        else "--comment-page 7 --body approved-text --if-version 1"
    )
    client = _settings(client, tool)
    return SimpleNamespace(
        client=client, server=server, entry=entry, output=output, command=command, root=root
    )


def _settings(client, tool):
    if tool == "codex":
        rules = client.cwd / ".codex/rules/service-actions.rules"
        destination = Path(client.env["CODEX_HOME"]) / "rules/service-actions.rules"
        destination.write_bytes(rules.read_bytes())
        config = (client.cwd / ".codex/config.toml").read_text()
        config += "\n[projects." + json.dumps(str(client.cwd)) + ']\ntrust_level="trusted"\n'
        (Path(client.env["CODEX_HOME"]) / "config.toml").write_text(config)
        servers = tomllib.loads(config).get("mcp_servers", {})
        pins = [
            value
            for alias in servers
            for value in ("-c", f'mcp_servers.{alias}.tools.run.approval_mode="prompt"')
        ]
        return replace(client, argv=[*client.argv[:-1], *pins, client.argv[-1]])
    home = Path(client.env["CLAUDE_CONFIG_DIR"]) / "settings.json"
    settings = json.loads(home.read_text())
    settings["permissions"].setdefault("allow", []).append(f"Bash({PYTHON} *)")
    home.write_text(json.dumps(settings))
    return client


def marker_entry(world):
    world.entry.chmod(0o644)
    world.entry.write_text(
        "from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_text('STANDIN_WRITE')\n"
    )
    world.entry.chmod(0o444)


def main_results(world):
    requests = [body for body in world.server.requests if body.get("model") != "codex-auto-review"]
    result = json.dumps(tool_results(requests[-1]))
    assert "review failure" not in result and "not valid JSON" not in result
    return result


def close(world):
    world.server.shutdown()
    world.server.server_close()
    unlock_deliveries(world.root)


def claude_host(world, approved):
    client = world.client
    argv = ["auto" if arg == "bypassPermissions" else arg for arg in client.argv[:-2]]
    argv.extend(("--settings", str(client.cwd / ".claude/access-settings.json")))
    argv.extend(("--input-format", "stream-json", "--permission-prompt-tool", "stdio"))
    with client.evidence.with_suffix(".stderr").open("w") as stderr:
        process = subprocess.Popen(
            argv,
            cwd=client.cwd,
            env=client.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            prompt = "I approve this exact command:\n" + world.command if approved else "Go."
            _send(process, {"type": "user", "message": {"role": "user", "content": prompt}})
            return _host_events(process, world, world.command if approved else None)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)


def _send(process, message):
    process.stdin.write((json.dumps(message) + "\n").encode())
    process.stdin.flush()


def _host_events(process, world, approved):
    pending, requests = b"", []
    with (
        selectors.DefaultSelector() as poll,
        world.client.evidence.with_suffix(".stdout").open("wb") as log,
    ):
        poll.register(process.stdout, selectors.EVENT_READ)
        for _ in range(40):
            if not poll.select(1):
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            assert chunk, "Claude exited without its final result"
            log.write(chunk)
            log.flush()
            *lines, pending = (pending + chunk).split(b"\n")
            frames = [json.loads(line) for line in lines]
            requests.extend(
                _answer(process, item, approved)
                for item in frames
                if item.get("type") == "control_request"
            )
            results = [item for item in frames if item.get("type") == "result"]
            if results:
                assert not results[0].get("is_error"), results[0]
                return requests
    raise AssertionError("Claude never completed its native approval response")


def _answer(process, item, approved):
    request = item["request"]
    allowed = request["input"].get("command") == approved
    response = (
        {"behavior": "allow", "updatedInput": request["input"]}
        if allowed
        else {"behavior": "deny", "message": "STANDIN_HOST_DENIED"}
    )
    response = dict(subtype="success", request_id=item["request_id"], response=response)
    _send(process, {"type": "control_response", "response": response})
    return request
