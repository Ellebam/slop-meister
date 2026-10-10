"""The `op` a launched session runs: `op run` goes through the approval broker.

Installed as ~/.local/bin/op, which the dotfiles put first on every shell's PATH. In a session
the launcher marked, `op run` reads its env files and the environment the way the real command
does, asks the broker for the references, runs the command here as the agent once the operator
approved, and masks the values in its output. Commands that disclose values are refused. Everything
else, and everything outside a marked session, passes to the real `op` next on PATH.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

from slopmeister.session import secret_transport as transport
from slopmeister.session.secret_env import environment  # noqa: F401, the shim's reader

MASK = b"<concealed by 1Password>"
MARK = "SLOPMEISTER_SECRET_BROKER"
LAUNCHER = "SLOPMEISTER_OP_LAUNCHER"
# Disclosure commands, matched on the words of the line so flags cannot hide them.
REFUSED_WORDS = {"read", "inject"}
REFUSED_PAIRS = (("item", "get"), ("item", "share"), ("document", "get"))
ENV_FILE = "--env-file"
REFUSAL = "is refused for agents; use op run, the Home Assistant approval resolves its references"


def _flag(args: list[str], index: int, files: list[str]) -> int:
    """Consume one `op run` flag at index into files, returning the next index."""
    arg = args[index]
    if arg == ENV_FILE and index + 1 < len(args):
        files.append(args[index + 1])
        return index + 2
    if arg.startswith(ENV_FILE + "="):
        files.append(arg.partition("=")[2])
        return index + 1
    if arg == "--no-masking":
        raise ValueError("--no-masking is refused, values stay masked")
    raise ValueError(f"{arg} is not supported through the approval broker")


def parse(args: list[str]) -> tuple[list[str], list[str]]:
    """The env files and the command of an `op run` line."""
    files: list[str] = []
    index = 0
    while index < len(args) and args[index] != "--":
        index = _flag(args, index, files)
    command = args[index + 1 :]
    if not command:
        raise ValueError("op run needs -- followed by the command")
    return files, command


def session_name(cwd: Path) -> str:
    """The containing repository's directory name, which is the session's workspace name."""
    return next((p.name for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd.name)


def request(references: dict[str, str], command: list[str]) -> dict:
    return {
        "env": references,
        "argv": command,
        "cwd": os.getcwd(),
        "reason": os.environ.get("SECRET_ASK_REASON", ""),
        "session": session_name(Path.cwd()),
        "host": socket.gethostname().partition(".")[0],
    }


def _pump(source, sink, patterns: list[bytes]) -> None:
    for line in iter(source.readline, b""):
        for pattern in patterns:
            line = line.replace(pattern, MASK)
        sink.write(line)
        sink.flush()


def run(command: list[str], extra: dict[str, str], values: list[str]) -> int:
    """Run the command as this user with the values in its environment, masked in its output."""
    parts = {part.encode() for value in values for part in value.splitlines() if part}
    patterns = sorted(parts, key=len, reverse=True)
    try:
        child = subprocess.Popen(
            command, env={**os.environ, **extra}, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except (OSError, ValueError) as error:
        print(f"op run: {command[0]}: {getattr(error, 'strerror', None) or error}", file=sys.stderr)
        return 127
    pumps = [
        threading.Thread(target=_pump, args=(child.stdout, sys.stdout.buffer, patterns)),
        threading.Thread(target=_pump, args=(child.stderr, sys.stderr.buffer, patterns)),
    ]
    for pump in pumps:
        pump.start()
    for pump in pumps:
        pump.join()
    status = child.wait()
    # A signal-terminated child exits as the shell reports it, 128 plus the signal number.
    return status if status >= 0 else 128 - status


def _report(receipt: dict) -> None:
    if receipt.get("state") in transport.ACTIVE:
        print(
            f"secret-ask: request {receipt.get('id')} waits for Home Assistant approval",
            file=sys.stderr,
            flush=True,
        )


def _resolved(references: dict[str, str], command: list[str]) -> dict | None:
    try:
        return transport.reach(request(references, command), _report)
    except transport.Unreachable as error:
        print(
            f"op run: the approval broker is unreachable, {error}. "
            "Only the operator can order the desktop route.",
            file=sys.stderr,
        )
    except transport.Refused as error:
        print(f"op run: the approval broker refused the request, {error}", file=sys.stderr)
    return None


def _values(references: dict[str, str], command: list[str]) -> dict | None:
    final = _resolved(references, command)
    if final is None:
        return None
    values = final.get("values")
    if final.get("state") != "delivered" or not isinstance(values, dict):
        print(f"secret-ask: request {final.get('id')} {final.get('state')}", file=sys.stderr)
        return None
    return values


def run_through_broker(args: list[str]) -> int:
    try:
        files, command = parse(args)
        literals, references = environment(files)
    except ValueError as error:
        print(f"op run: {error}", file=sys.stderr)
        return 2
    if not references:
        print("op run: no secret references; run the command directly", file=sys.stderr)
        return 2
    values = _values(references, command)
    if values is None:
        return 1
    return run(command, {**literals, **values}, [str(value) for value in values.values()])


def real_op(own: Path) -> Path | None:
    """The real `op` next on PATH, never this program's own launcher."""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry or ".") / "op"
        if candidate.resolve() != own and os.access(candidate, os.X_OK) and candidate.is_file():
            return candidate
    return None


def refused(argv: list[str]) -> str:
    """The refused command named by the line's words, whatever flags surround them, or empty."""
    words = [arg for arg in argv if not arg.startswith("-")]
    hit = next((word for word in words if word in REFUSED_WORDS), "")
    if not hit:
        hit = next((" ".join(pair) for pair in REFUSED_PAIRS if set(pair) <= set(words)), "")
    if not hit and argv[:1] != ["run"] and "run" in words:
        hit = "run with global flags"
    return hit


def pass_through(argv: list[str]) -> int:
    hit = refused(argv)
    if hit:
        print(f"op {hit} {REFUSAL}", file=sys.stderr)
        return 1
    own = Path(os.environ.get(LAUNCHER) or sys.argv[0]).resolve()
    binary = real_op(own)
    if binary is None:
        print("op: the 1Password CLI is not installed on this machine", file=sys.stderr)
        return 127
    os.execv(binary, [str(binary), *argv])


def main(argv: list[str]) -> int:
    if os.environ.get(MARK) != "1":
        own = Path(os.environ.get(LAUNCHER) or sys.argv[0]).resolve()
        binary = real_op(own)
        if binary is None:
            print("op: the 1Password CLI is not installed on this machine", file=sys.stderr)
            return 127
        os.execv(binary, [str(binary), *argv])
    if argv[:1] == ["run"]:
        return run_through_broker(argv[1:])
    return pass_through(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
