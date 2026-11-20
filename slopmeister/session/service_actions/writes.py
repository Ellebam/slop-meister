"""The shared write path: required options, one guard per target and the sequential write loop."""

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import re

from .constants import INCOMPLETE, KNOWN_FAILURES
from .operations import Rejected
from .wire import bounded


@dataclass(frozen=True)
class Write:
    """One fixed request against one named target, and how to record its new version."""

    target: str
    method: str
    path: str
    payload: dict
    version: Callable[[object, object, dict], None]


def requires(*names: str, guard: str | None = None, targets: str | None = None):
    """A form check refusing missing options and a guard list that does not match the targets."""

    def check(operation: dict) -> None:
        for name in names:
            if name not in operation:
                raise Rejected(f"--{operation['mode']} requires --{name}")
        if guard and len(operation.get(guard, [])) != len(operation[targets]):
            raise Rejected(f"--{guard} expects one value per target of --{operation['mode']}")

    return check


def items(value: str) -> list[dict]:
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else [parsed]


def _error_code(error: Exception, fallback: str) -> str:
    if isinstance(error, ValueError):
        code = str(error).partition(":")[0]
        if code in KNOWN_FAILURES or re.fullmatch(r"HTTP_[0-9]{3}", code):
            return code
    return fallback


def apply(client, result: dict, planned: list[Write]) -> dict:
    """Send each write once, in order. A later failure keeps the lines of writes already made."""
    written = []
    for write in planned:
        body = json.dumps(write.payload, separators=(",", ":")).encode()
        try:
            response = client.send(write.method, write.path, body)
        except Exception as error:
            if not written:
                raise
            failure = {"target": write.target, "error": _error_code(error, "ACTION_FAILED")}
            return bounded(dict(result, result=INCOMPLETE, written=written, failed=failure))
        line = {"target": write.target}
        try:
            write.version(response, client, line)
        except Exception as error:
            # The write happened, only its new version is unknown, so its line must stay.
            line["version_unconfirmed"] = _error_code(error, "RESPONSE_INVALID")
        written.append(line | {"payload_sha256": hashlib.sha256(body).hexdigest()})
    return bounded(dict(result, written=written))
