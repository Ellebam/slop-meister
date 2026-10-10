"""Read root-installed routing and private credentials without printing their contents."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import tomllib
from urllib.parse import urlsplit

CONFIG = Path("/etc/slopmeister-secret-ask/config.toml")
ROUTING = {"url", "operator", "agent_uid", "devices"}
FILES = {"state", "socket", "op", "op_token", "ha_token"}
TOKEN_LIMIT = 16384


@dataclass(frozen=True)
class Config:
    url: str
    operator: str
    agent_uid: int
    devices: tuple[str, ...]
    state: Path
    socket: Path
    op: Path
    op_token: Path
    ha_token: Path


def line(value: object, limit: int = 512, empty: bool = False) -> str:
    """One printable line of request text within its limit."""
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError("invalid request text")
    if any(not character.isprintable() for character in value):
        raise ValueError("invalid request text")
    return value


def private_token(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("credential file must be owned and private")
        value = stream.read(TOKEN_LIMIT + 1)
    if not value or len(value) > TOKEN_LIMIT:
        raise ValueError("credential file is empty or too large")
    return line(value.decode().strip(), TOKEN_LIMIT)


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Home Assistant URL must be an origin")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    ):
        raise ValueError("Home Assistant needs HTTPS or local loopback")
    if not parsed.hostname:
        raise ValueError("Home Assistant host is missing")
    return value.rstrip("/")


def _routing(data: dict) -> tuple[str, ...]:
    devices = data["devices"]
    if (
        not isinstance(devices, list)
        or not 1 <= len(devices) <= 16
        or any(
            not isinstance(d, str) or not re.fullmatch(r"mobile_app_[a-z0-9_]+", d) for d in devices
        )
        or len(set(devices)) != len(devices)
    ):
        raise ValueError("configure distinct operator notification services")
    if type(data["agent_uid"]) is not int or data["agent_uid"] < 1:
        raise ValueError("agent UID must name a non-root account")
    return tuple(devices)


def load(path: Path) -> Config:
    data = tomllib.loads(path.read_text())
    if set(data) != ROUTING | FILES:
        raise ValueError("service configuration fields are invalid")
    devices = _routing(data)
    paths = {key: Path(line(data[key], 4096)) for key in FILES}
    if any(not p.is_absolute() or ".." in p.parts for p in paths.values()):
        raise ValueError("service paths must be absolute")
    return Config(
        _url(line(data["url"])), line(data["operator"], 64), data["agent_uid"], devices, **paths
    )
