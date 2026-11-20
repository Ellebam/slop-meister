"""A scratch Orca profile and a stand-in for Orca's runtime socket, never the live Orca."""

import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import threading

from slopmeister.workstation import orca

TOKEN = "stand-in-orca-token"
RUNTIME_ID = "stand-in-runtime"


def profile(home: Path, settings: dict | None) -> Path:
    """Write Orca's profile database with one settings document, or none when `settings` is None."""
    store = home / orca.NAME
    store.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store) as database:
        database.execute(
            "create table if not exists profile_state_documents"
            "(domain text primary key, payload text)"
        )
        database.execute("delete from profile_state_documents where domain = 'settings'")
        if settings is not None:
            database.execute(
                "insert into profile_state_documents values('settings', ?)", (json.dumps(settings),)
            )
    database.close()
    return store


class Runtime:
    """Answers one request per connection like Orca, after one keepalive frame.

    `settings` is the live state the stand-in serves and changes. `replies` maps a method to a
    function that returns the raw frames to send instead. `requests` keeps each parsed request.
    """

    def __init__(self, home: Path, settings: dict):
        self.settings = settings
        self.requests: list[dict] = []
        self.replies: dict = {}
        # macOS caps a socket path at 104 bytes, so the socket lives in a short private folder.
        self.root = Path(tempfile.mkdtemp(prefix="orca", dir="/tmp")).resolve()
        folder = self.root / "r"
        folder.mkdir(mode=0o700)
        self.endpoint = folder / "o.sock"
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.endpoint))
        self.server.listen()
        self.metadata = home / orca.RUNTIME
        self.metadata.parent.mkdir(parents=True, exist_ok=True)
        self.write_metadata()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def write_metadata(self, **changes: object) -> None:
        meta = {
            "authToken": TOKEN,
            "runtimeId": RUNTIME_ID,
            "pid": os.getpid(),
            "transport": None,
            "transports": [{"kind": "unix", "endpoint": str(self.endpoint)}],
            **changes,
        }
        self.metadata.unlink(missing_ok=True)
        descriptor = os.open(self.metadata, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(meta, stream)

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *_: object) -> None:
        self.server.close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.root, ignore_errors=True)

    def methods(self) -> list[str]:
        return [request["method"] for request in self.requests]

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            with connection, connection.makefile("rb") as stream:
                request = json.loads(stream.readline())
                self.requests.append(request)
                custom = self.replies.get(request["method"])
                for frame in custom(request) if custom else self._frames(request):
                    connection.sendall(frame)

    def _frames(self, request: dict) -> list[bytes]:
        if request.get("authToken") != TOKEN:
            reply = {"id": request["id"], "ok": False, "error": {"code": "unauthorized"}}
        else:
            reply = {
                "id": request["id"],
                "ok": True,
                "result": self._answer(request["method"], request.get("params")),
                "_meta": {"runtimeId": RUNTIME_ID},
            }
        return [b'{"_keepalive":true}\n', json.dumps(reply).encode() + b"\n"]

    def _answer(self, method: str, params: dict | None) -> dict:
        commands = self.settings.setdefault("terminalQuickCommands", [])
        if method == "settings.updateTerminalQuickCommands":
            command = params["mutation"]["command"]
            found = [i for i, item in enumerate(commands) if item["id"] == command["id"]]
            if found:
                commands[found[0]] = command
            else:
                commands.append(command)
        if method == "settings.update":
            self.settings.update(params)
        if method.endswith("TerminalQuickCommands"):
            return {"terminalQuickCommands": commands}
        keys = ("agentStatusHooksEnabled", "agentDefaultArgs")
        return {"settings": {key: self.settings[key] for key in keys if key in self.settings}}
