"""Ask the operator in Home Assistant about one request and read the decision for it.

The route can send one question and read answers, nothing else. The question carries a random
request ID. Home Assistant records the first press of the operator's own user under that ID, and
only `approved` under this request's ID releases anything.
"""

from http.client import HTTPException
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from slopmeister.session import launch_identity, secret_tier

SETTINGS = "home-assistant.json"
FIELDS = {"ask_url", "answer_url", "token"}
WAIT_SECONDS = 600
POLL_SECONDS = 2
EXCHANGE_TIMEOUT = 5
ANSWER_LIMIT = 1048576
# A mobile push drops a larger body, so the operator would approve text they cannot see.
MESSAGE_LIMIT = 3800
REASON_LIMIT = 160
WORKSPACE = "SLOPMEISTER_SESSION_WORKSPACE"
PHONE = "SLOPMEISTER_PHONE_SESSION"
DECISIONS = ("approved", "denied")
NO_REASON = (
    "a tier-two request needs a reason the operator can read. Put "
    'SECRET_ASK_REASON="<one line>" in front of the command and run it again.'
)
EXPIRED = "timed out"


class Unreachable(Exception):
    """Home Assistant did not take the question, the message names the cause."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Home Assistant redirect refused")


def _address(value: object) -> bool:
    """HTTPS, or plain HTTP to this machine only."""
    parsed = urlsplit(value) if isinstance(value, str) else None
    if parsed is None or not parsed.hostname:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname == "127.0.0.1")


def valid(data: object) -> bool:
    """Whether the data is a route: two safe addresses and a one-line token, nothing else."""
    try:
        return (
            set(data) == FIELDS
            and all(isinstance(v, str) and v.isprintable() for v in data.values())
            and _address(data["ask_url"])
            and _address(data["answer_url"])
        )
    except TypeError, AttributeError:
        return False


def route() -> dict[str, str]:
    """The two addresses and the read credential of the route, from its private file."""
    path = secret_tier.directory() / SETTINGS
    try:
        data = json.loads(secret_tier.private(path))
    except json.JSONDecodeError:
        data = None
    if not valid(data):
        raise ValueError(f"{path} does not hold the route's two HTTPS addresses and its token")
    return data


def origin() -> dict[str, str]:
    """Use launcher state or the phone service marker, never the command's current directory."""
    cwd = os.getcwd()
    if not cwd.isprintable():
        raise ValueError("the current directory must contain only printable characters")
    workspace = os.environ.get(WORKSPACE)
    if workspace is None and os.environ.get(PHONE) == "1":
        session = "Phone session"
    else:
        try:
            if not workspace or not Path(workspace).is_absolute():
                raise ValueError("missing workspace")
            session = launch_identity.read(Path(workspace))["task"]
        except OSError, ValueError, KeyError, TypeError, AttributeError:
            raise ValueError(
                "launcher identity is unavailable or unconfirmed; wait for launcher confirmation "
                "or relaunch the session after installation. For a remote command, resolve in "
                "the launched session and pipe through SSH standard input; see "
                "docs/1password-access.md#remote-commands"
            ) from None
    return {
        "session": session,
        "host": socket.gethostname().partition(".")[0],
        "cwd": cwd,
        "reason": os.environ.get("SECRET_ASK_REASON", ""),
    }


def command_text(argv: list[str]) -> str:
    """Keep ordinary commands familiar and control characters visible without forged lines."""
    if any(arg and not arg.isprintable() for arg in argv):
        return "Command arguments (JSON): " + json.dumps(argv)
    return "Command: " + shlex.join(argv)


def question(request: dict) -> dict:
    """What the operator reads before deciding, the purpose and the origin first."""
    references = ", ".join(f"{name}={value}" for name, value in request["env"].items())
    # One line, so a reason cannot write a line that reads like the command or the host.
    reason = " ".join(request["reason"].split())
    if not reason:
        raise ValueError(NO_REASON)
    if len(reason) > REASON_LIMIT:
        raise ValueError(f"shorten the reason in SECRET_ASK_REASON to {REASON_LIMIT} characters")
    inputs = ""
    if request["files"]:
        inputs += "Env files: " + shlex.join(request["files"]) + "\n"
    if request["literals"]:
        inputs += "Literal names (values hidden): " + ", ".join(request["literals"]) + "\n"
    text = (
        f"Why: {reason}\nSession: {request['session']}\nHost: {request['host']}\n"
        f"{command_text(request['argv'])}\nReferences: {references}\n{inputs}"
        f"Directory: {request['cwd']}"
    )
    body = {
        "id": secrets.token_hex(16),
        "title": "Secret approval: " + request["session"],
        "message": text,
    }
    if len(json.dumps(body).encode()) > MESSAGE_LIMIT:
        raise ValueError("the request text exceeds what one notification can show")
    return body


def _exchange(request: Request) -> bytes:
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=EXCHANGE_TIMEOUT) as response:
        data = response.read(ANSWER_LIMIT + 1)
    if len(data) > ANSWER_LIMIT:
        raise ValueError("Home Assistant's answer exceeds the limit")
    return data


def ask(settings: dict[str, str], body: dict) -> None:
    headers = {"Content-Type": "application/json"}
    try:
        data = json.loads(
            _exchange(
                Request(settings["ask_url"], json.dumps(body).encode(), headers, method="POST")
            )
        )
    except HTTPError as error:
        reason = (
            "refused authentication (HTTP 401)"
            if error.code == 401
            else f"returned HTTP {error.code}"
        )
        raise Unreachable(f"ask route {reason}") from None
    except ValueError, HTTPException, RecursionError:
        raise Unreachable("ask route returned an invalid reply") from None
    except OSError:
        raise Unreachable("ask route is unavailable") from None
    if not isinstance(data, dict) or data.get("accepted") is not True:
        raise Unreachable("ask route returned an invalid reply")


def answer(settings: dict[str, str], identifier: str) -> str:
    """The decision recorded for this request, or empty while there is none."""
    headers = {"Authorization": "Bearer " + settings["token"]}
    try:
        data = json.loads(_exchange(Request(settings["answer_url"], headers=headers)))
    except HTTPError as error:
        if error.code == 401:
            raise Unreachable("answer route refused authentication (HTTP 401)") from None
        return ""
    except ValueError, HTTPException, RecursionError:
        raise Unreachable("answer route returned an invalid reply") from None
    except OSError:
        return ""
    # A Home Assistant state carries the map under its attributes.
    if isinstance(data, dict):
        data = data.get("attributes", data)
    decisions = data.get("decisions") if isinstance(data, dict) else None
    if not isinstance(decisions, dict):
        raise Unreachable("answer route returned an invalid reply")
    found = decisions.get(identifier, "")
    return found if found in DECISIONS else ""


def decision(settings: dict[str, str], identifier: str) -> str:
    """Wait for this request's decision: approved, denied, or timed out after ten minutes."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        found = answer(settings, identifier)
        if found:
            return found
        time.sleep(POLL_SECONDS)
    return EXPIRED
