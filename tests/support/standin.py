"""Process helpers and a stand-in model that native tests point the real clients at."""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import threading

DONE = "STAND_IN_DONE"


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def put(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@dataclass(frozen=True)
class Command:
    """One subprocess invocation and its evidence destination."""

    argv: list
    cwd: Path
    env: dict
    evidence: Path
    timeout: int = 45
    stdin: str | None = None


def run(command: Command):
    put(command.evidence.with_suffix(".command.json"), json.dumps(list(map(str, command.argv))))
    child = subprocess.Popen(
        command.argv,
        cwd=command.cwd,
        env=command.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    out, err = communicate(child, command)
    put(command.evidence.with_suffix(".stdout"), out)
    put(command.evidence.with_suffix(".stderr"), err)
    require(
        child.returncode == 0,
        f"command exited {child.returncode}, evidence: {command.evidence}",
    )
    return out


def communicate(child, command):
    try:
        return child.communicate(input=command.stdin, timeout=command.timeout)
    except subprocess.TimeoutExpired as error:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            out, err = child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            out, err = child.communicate()
        put(command.evidence.with_suffix(".stderr"), err)
        raise RuntimeError("command timed out, evidence: " + str(command.evidence)) from error


class StandIn(BaseHTTPRequestHandler):
    """A scripted model for both clients, one scripted tool call per turn, then a final text.

    The turn is the number of tool results the client sent back, so a reply never depends on
    server-side state and a client that retries a request gets the same answer.
    """

    def log_message(self, format_string, *values):
        return None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        route = self.path.split("?")[0]
        if not route.endswith(("/messages", "/responses")):
            self.reply_tokens()
            return
        self.server.requests.append(body)
        put(self.request_path(), json.dumps(body, indent=2))
        turn = len(tool_results(body))
        call = self.server.script[turn] if turn < len(self.server.script) else None
        if route.endswith("/responses"):
            self.reply_stream(responses_events(call, turn))
        else:
            self.reply_stream(messages_events(call, body, turn))

    def request_path(self):
        name = f"{self.server.case}-{len(self.server.requests)}.json"
        return self.server.evidence / name

    def reply_tokens(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"input_tokens":100}')

    def reply_stream(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in events:
            payload = "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
            self.wfile.write(payload.encode())
        self.wfile.flush()


def tool_results(body):
    """Claude's tool_result parts and Codex's function_call_output items in one request."""
    claude = [
        part
        for message in body.get("messages", [])
        for part in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(part, dict) and part.get("type") == "tool_result"
    ]
    codex = [
        item
        for item in (body.get("input") if isinstance(body.get("input"), list) else [])
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    return claude + codex


def messages_events(call, body, turn):
    message = dict(
        id="msg_standin",
        type="message",
        role="assistant",
        content=[],
        model=body.get("model", "stand-in"),
        stop_reason=None,
        stop_sequence=None,
        usage=dict(input_tokens=100, output_tokens=1),
    )
    block, delta, stop = messages_block(call, turn)
    return [
        dict(type="message_start", message=message),
        dict(type="content_block_start", index=0, content_block=block),
        dict(type="content_block_delta", index=0, delta=delta),
        dict(type="content_block_stop", index=0),
        dict(
            type="message_delta",
            delta=dict(stop_reason=stop, stop_sequence=None),
            usage=dict(output_tokens=4),
        ),
        dict(type="message_stop"),
    ]


def messages_block(call, turn):
    if call is None:
        return dict(type="text", text=""), dict(type="text_delta", text=DONE), "end_turn"
    name, arguments = call
    block = dict(type="tool_use", id=f"standin_{turn}", name=name, input={})
    return block, dict(type="input_json_delta", partial_json=json.dumps(arguments)), "tool_use"


def responses_events(call, turn):
    if call is None:
        text = dict(type="output_text", text=DONE, annotations=[])
        item = dict(type="message", id="msg_standin", role="assistant", content=[text])
    else:
        name, arguments = call
        item = dict(type="function_call", call_id=f"call_{turn}", name=name)
        item.update(id=f"fc_{turn}", arguments=json.dumps(arguments))
    item["status"] = "completed"
    usage = dict(input_tokens=100, output_tokens=1, total_tokens=101)
    response = dict(id="resp_standin", object="response", status="completed", output=[item])
    return [
        dict(type="response.created", response=dict(id="resp_standin")),
        dict(type="response.output_item.done", output_index=0, item=item),
        dict(type="response.completed", response=dict(response, usage=usage)),
    ]


def capture_server(evidence, case, script):
    """Serve `script`, a list of (tool name, arguments) pairs, on a loopback port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    server.evidence, server.case, server.requests = evidence, case, []
    server.script = script
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
