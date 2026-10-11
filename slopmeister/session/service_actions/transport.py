"""HTTPS transport with secrets and write bodies carried only through private pipes."""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from .constants import CURL, OPENSSL_CONFIG, RESPONSE_LIMIT

MARKER = b"\nSLOPMEISTER_HTTP_STATUS:"


@dataclass(frozen=True)
class CurlRequest:
    url: str
    token: str
    timeout: float
    limit: int = RESPONSE_LIMIT
    pfx: bytes | None = None
    password: str | None = None
    server_ca: Path | None = None
    method: str = "GET"
    body: bytes | None = None


@dataclass(frozen=True)
class CurlResponse:
    status: int
    output: bytes
    errors: bytes


def _quote(value: str) -> str:
    escapes = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}
    if "\x00" in value:
        raise ValueError("CREDENTIAL_INPUT_INVALID")
    return '"' + "".join(escapes.get(char, char) for char in value) + '"'


def _config(request: CurlRequest) -> bytes:
    lines = [
        "header = " + _quote("Authorization: Bearer " + request.token),
        'header = "Accept: application/json"',
    ]
    if request.pfx is not None:
        lines.extend(
            (
                'cert = "/dev/stdin"',
                'cert-type = "P12"',
                "pass = " + _quote(request.password or ""),
            )
        )
    if request.body is not None:
        # curl reads a data value starting with @ as a file name.
        if request.body.startswith(b"@"):
            raise ValueError("REQUEST_INVALID")
        lines.append('header = "Content-Type: application/json"')
        lines.append("data-binary = " + _quote(request.body.decode()))
    return ("\n".join(lines) + "\n").encode()


def _command(request: CurlRequest, config_fd: int) -> list[str]:
    command = [
        str(CURL),
        "--disable",
        "--silent",
        "--show-error",
        "--request",
        request.method,
        "--proto",
        "=https",
        "--noproxy",
        "*",
        "--max-time",
        str(max(1, math.ceil(request.timeout))),
        "--max-filesize",
        str(request.limit),
        "--config",
        f"/dev/fd/{config_fd}",
        "--write-out",
        MARKER.decode() + "%{http_code}",
    ]
    if request.server_ca is not None:
        command.extend(("--cacert", str(request.server_ca)))
        if sys.platform == "linux":
            # OpenSSL adds its default CA directory to --cacert. An empty one leaves only the pin.
            command.extend(("--capath", "/dev/null"))
    return [*command, request.url]


def _environment(request: CurlRequest) -> dict[str, str]:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C"}
    if sys.platform == "linux" and request.pfx is not None:
        env["OPENSSL_CONF"] = str(OPENSSL_CONFIG)
    if sys.platform == "darwin" and request.server_ca is not None and request.pfx is None:
        # Apple's default backend adds the system trust store to --cacert. SecureTransport trusts
        # the pin alone, but cannot read a client certificate from a pipe.
        env["CURL_SSL_BACKEND"] = "secure-transport"
    return env


def _run(request: CurlRequest) -> CurlResponse:
    config_read, config_write = os.pipe()
    try:
        process = subprocess.Popen(
            _command(request, config_read),
            env=_environment(request),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(config_read,),
        )
    finally:
        os.close(config_read)
    with os.fdopen(config_write, "wb") as config:
        config.write(_config(request))
    try:
        output, errors = process.communicate(request.pfx or b"", timeout=request.timeout + 2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise ValueError("REQUEST_TIMEOUT") from None
    return CurlResponse(process.returncode, output, errors)


def _result(response: CurlResponse, request: CurlRequest):
    if response.status == 63 or len(response.output) > request.limit + len(MARKER) + 3:
        raise ValueError("RESPONSE_TOO_LARGE")
    if response.status == 28:
        raise ValueError("REQUEST_TIMEOUT")
    if response.status in (58, 59) and request.pfx is not None:
        raise ValueError("CERTIFICATE_INVALID")
    if response.status or len(response.errors) > 65536:
        raise ValueError("NETWORK_OR_TLS_FAILED")
    try:
        body, code = response.output.rsplit(MARKER, 1)
        http_status = int(code)
    except ValueError, TypeError:
        raise ValueError("RESPONSE_INVALID") from None
    accepted = (200,) if request.method == "GET" else (200, 201, 204)
    if http_status not in accepted:
        raise ValueError(f"HTTP_{http_status:03d}")
    if request.method != "GET" and not body:
        return None
    try:
        return json.loads(body)
    except UnicodeError, json.JSONDecodeError:
        raise ValueError("RESPONSE_INVALID") from None


def send(request: CurlRequest):
    if (
        not request.token
        or any(char.isspace() for char in request.token)
        or request.token.startswith("op://")
    ):
        raise ValueError("CREDENTIAL_INPUT_INVALID")
    paired = request.pfx is not None and request.password is not None
    if (request.pfx is not None or request.password is not None) and not paired:
        raise ValueError("CREDENTIAL_INPUT_INVALID")
    if paired and (not request.pfx or not request.password or request.password.startswith("op://")):
        raise ValueError("CREDENTIAL_INPUT_INVALID")
    return _result(_run(request), request)
