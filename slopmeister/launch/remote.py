"""SSH transport to an existing host-owned Slopmeister checkout and Orca runtime."""

from collections.abc import Sequence
from pathlib import Path
import subprocess
import sys

from slopmeister.errors import SlopmeisterError, UsageError
from slopmeister.launch.model import shq
from slopmeister.session import remote_ssh

PREFLIGHT_TIMEOUT = 45
# The remote shell supplies its own tool paths and desktop runtime, never the Mac's environment.
CHECKOUT = 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"; cd "$HOME/dev/slop-meister"'
CHECK = (
    CHECKOUT + ' || { echo "remote checkout is unavailable" >&2; exit 78; }; '
    'test -x bin/slopmeister || { echo "remote launcher is unavailable" >&2; exit 78; }; '
    "python3 -c "
    + shq(
        "from slopmeister.launch import terminal; import sys; "
        "sys.exit(0 if terminal._usable() else 69)"
    )
)


def selected(argv: Sequence[str]) -> tuple[str, list[str]]:
    args = list(argv)
    end = args.index("--") if "--" in args else len(args)
    indices = [i for i in range(end) if args[i].split("=", 1)[0] == "--host"]
    if not indices:
        return "", args
    index = indices[0]
    inline = args[index].startswith("--host=")
    host = args[index].partition("=")[2] if inline else ""
    if not inline and index + 1 < end:
        host = args[index + 1]
    if len(indices) != 1 or not remote_ssh.ALIAS.fullmatch(host):
        raise UsageError("--host requires one dedicated SSH alias, matching [a-z0-9][a-z0-9-]*")
    del args[index : index + (1 if inline else 2)]
    return host, args


def ssh(host: str, command: str) -> list[str]:
    try:
        return remote_ssh.argv(Path.home(), host, command)
    except ValueError as error:
        raise UsageError(str(error)) from None


def preflight(host: str) -> None:
    try:
        result = subprocess.run(
            ssh(host, CHECK),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(
            f"{host}: SSH preflight unavailable ({type(error).__name__}); nothing launched"
        ) from error
    if result.returncode:
        cause = {69: "Orca is unreachable", 78: "Slopmeister checkout is unavailable"}.get(
            result.returncode, "SSH or remote preflight failed"
        )
        detail = result.stderr.strip()[-1000:]
        raise SlopmeisterError(f"{host}: {cause}; nothing launched. {detail}")


def launch(argv: Sequence[str], entry: Sequence[str]) -> int | None:
    host, args = selected(argv)
    if not host:
        return None
    preflight(host)
    print(f"remote host: {host}", flush=True)
    command = (
        CHECKOUT
        + " && exec "
        + " ".join(shq(value) for value in ["bin/slopmeister", *entry, *args])
    )
    try:
        result = subprocess.run(ssh(host, command), stdin=sys.stdin)
        code = result.returncode
    except OSError, KeyboardInterrupt:
        code = 1
    if code:
        print(
            f"{host}: remote launch did not confirm success; a worker may be live. "
            f"Inspect its Orca and claim on {host} before retrying or releasing resources. "
            f"Every retry must keep --host {host}; remote paths must not run locally.",
            file=sys.stderr,
        )
    return code
