"""Validate provider input and dispatch the fixed operation."""

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit

from . import confluence, confluence_write, jira, jira_write, runtime, transport
from .arguments import TABLES
from .constants import INCOMPLETE, LIMIT, ORIGIN, REQUEST_TIMEOUT, RESPONSE_LIMIT, SUCCESS
from .jira_find import backlog_query
from .operations import ID, valid
from .wire import bounded, encode


@dataclass
class Client:
    origin: str
    token: str
    deadline: float
    pfx: bytes | None = None
    password: str | None = None
    server_ca: Path | None = None
    requests: int = 0
    backlog_jql: str | None = None

    def url(self, path: str, query: dict | None = None) -> str:
        base = self.origin.rstrip("/") + "/"
        value = base + path.lstrip("/")
        return value + (("?" + urlencode(query)) if query else "")

    def get_url(self, url: str, write: tuple[str, bytes] | None = None):
        self.requests += 1
        if self.requests > 100:
            raise ValueError("SEARCH_LIMIT")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("ACTION_TIMEOUT")
        request = transport.CurlRequest(
            url,
            self.token,
            min(REQUEST_TIMEOUT, remaining),
            LIMIT,
            self.pfx,
            self.password,
            self.server_ca,
            *(write or ()),
        )
        return transport.send(request)

    def get(self, path: str, query: dict | None = None):
        return self.get_url(self.url(path, query))

    def send(self, method: str, path: str, body: bytes):
        return self.get_url(self.url(path), (method, body))


DISPATCH = {
    "jira-read": jira.read,
    "confluence-read": confluence.read,
    "jira-write": jira_write.write,
    "confluence-write": confluence_write.write,
}


def _origin(value) -> str:
    if not isinstance(value, str):
        raise ValueError("CONFIG_INVALID")
    parsed = urlsplit(value)
    if (
        not re.fullmatch(ORIGIN, value)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CONFIG_INVALID")
    return value


def _operation(data: dict) -> None:
    action, operation = data.get("action"), data.get("operation")
    if action not in TABLES:
        raise ValueError("CONFIG_INVALID")
    if not valid(TABLES[action], operation) or (
        operation["mode"] == "page" and not ID.fullmatch(operation["id"])
    ):
        raise ValueError("REQUEST_INVALID")


def _client(data: dict) -> Client:
    remaining = data.get("remaining_ms", 290000)
    if type(remaining) is not int or not 0 < remaining <= 300000:
        raise ValueError("ACTION_TIMEOUT")
    token = os.environ.pop("JIRA_PAT", "")
    password = os.environ.pop("JIRA_CERT_PASSWORD", None)
    pfx = data.get("pfx")
    try:
        decoded = base64.b64decode(pfx, validate=True) if pfx is not None else None
    except ValueError, TypeError:
        raise ValueError("CREDENTIAL_INPUT_INVALID") from None
    if decoded is not None and len(decoded) > RESPONSE_LIMIT:
        raise ValueError("CREDENTIAL_INPUT_INVALID")
    return Client(
        _origin(data.get("origin")),
        token,
        time.monotonic() + remaining / 1000,
        decoded,
        password,
        Path(data["server_ca"]) if "server_ca" in data else None,
    )


def read(data: dict):
    _operation(data)
    expected = data.get("expected_user")
    if not isinstance(expected, str) or not expected:
        raise ValueError("CONFIG_INVALID")
    query = (
        backlog_query(data.get("backlog_jql")) if data["operation"]["mode"] == "backlog" else None
    )
    client = _client(data)
    client.backlog_jql = query
    return DISPATCH[data["action"]](client, expected, data["operation"])


def main(argv: list[str] | None = None) -> int:
    try:
        runtime.require_interpreter()
        if argv:
            raise ValueError("INPUT_INVALID")
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("INPUT_INVALID")
        data = json.loads(raw)
        result = bounded(read(data))
        if result.get("result") not in (SUCCESS[data["action"]], INCOMPLETE):
            raise ValueError(result.get("result", "ACTION_FAILED"))
        sys.stdout.buffer.write(encode(result))
        return 0
    except Exception as error:
        code = str(error).split(":", 1)[0] if isinstance(error, ValueError) else "ACTION_FAILED"
        if not re.fullmatch(r"[A-Z_]{3,64}|HTTP_[0-9]{3}", code):
            code = "ACTION_FAILED"
        print(json.dumps({"result": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
