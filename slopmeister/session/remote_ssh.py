"""The dedicated SSH route to the Linux agent host, see docs/remote-dispatch.md.

The configuration file declares each permitted alias on its own Host line. A wildcard block only
carries defaults, so it is never an alias.
"""

from pathlib import Path
import re

ALIAS = re.compile(r"[a-z0-9][a-z0-9-]*")
CONFIG = ".ssh/slopmeister-remote.conf"
# No agent, forwarding, shared connection, password or terminal: the key alone authenticates.
OPTIONS = (
    "BatchMode=yes",
    "IdentityAgent=none",
    "IdentitiesOnly=yes",
    "StrictHostKeyChecking=yes",
    "ForwardAgent=no",
    "ForwardX11=no",
    "ClearAllForwardings=yes",
    "ControlMaster=no",
    "ControlPath=none",
    "PasswordAuthentication=no",
    "KbdInteractiveAuthentication=no",
    "PreferredAuthentications=publickey",
    "RequestTTY=no",
    "ConnectTimeout=8",
    "ServerAliveInterval=5",
    "ServerAliveCountMax=2",
)


def shq(value: str) -> str:
    """Single-quote a value for the remote login shell, the idiom the launch receipts pin."""
    return "'" + value.replace("'", "'\\''") + "'"


def config_path(home: Path) -> Path:
    return home / CONFIG


def aliases(home: Path) -> list[str]:
    """Every alias with its own Host line, in file order, without wildcard blocks."""
    rows = [line.partition("#")[0].split() for line in config_path(home).read_text().splitlines()]
    return [
        row[1]
        for row in rows
        if len(row) == 2 and row[0].lower() == "host" and ALIAS.fullmatch(row[1])
    ]


def argv(home: Path, alias: str, command: str) -> list[str]:
    """The ssh command that runs one zsh login command on a declared alias."""
    if alias not in aliases(home):
        raise ValueError(
            f"SSH alias {alias} is not declared by its own Host line in {config_path(home)}"
        )
    options = [part for option in OPTIONS for part in ("-o", option)]
    remote = " ".join(shq(value) for value in ["/bin/zsh", "-lc", command])
    return ["ssh", "-F", str(config_path(home)), *options, "--", alias, remote]
