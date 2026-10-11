"""The `op` a launched session runs: it picks the tier of an `op run` and holds the tokens.

Installed as ~/.local/bin/op, which the dotfiles put first on every shell's PATH. In a session
the launcher marked, `op run` reads its env files and the environment the way the real command
does and takes the tier from the vaults they name. Tier one runs the real `op run` with the
tier-one service-account token. Tier two needs the operator's word, `op tier-two -- <command>`,
and then their approval in Home Assistant. `op desktop -- <command>` sends every `op run` below
it to the real `op` with the desktop app. Commands that disclose values are refused. Everything
else, and everything outside a marked session, passes to the real `op` next on PATH.
"""

import os
from pathlib import Path
import socket
import sys

from slopmeister.session import secret_approval, secret_tier
from slopmeister.session.secret_env import environment

MARK = "SLOPMEISTER_SECRET_BROKER"
# The operator's word for this process tree, set by `op tier-two --` or `op desktop --`.
ROUTE = "SLOPMEISTER_OP_ROUTE"
TIER_TWO, DESKTOP = "tier-two", "desktop"
# Set for the command of an `op run`, where a route word could ride the allowed `op run` prefix.
INSIDE = "SLOPMEISTER_OP_RUN"
TOKEN = "OP_SERVICE_ACCOUNT_TOKEN"
# The real op obeys these: one prints values, two replace the chosen token's account.
OVERRIDES = ("OP_RUN_NO_MASKING", "OP_CONNECT_HOST", "OP_CONNECT_TOKEN")
# What this program decides. A request cannot bring its own.
RESERVED = (TOKEN, *OVERRIDES, ROUTE, INSIDE)
ENV = "/usr/bin/env"
# Disclosure commands, matched on the words of the line so flags cannot hide them.
REFUSED_WORDS = {"read", "inject"}
REFUSED_PAIRS = (("item", "get"), ("item", "share"), ("document", "get"))
# op also takes both groups in the plural, a refusal must not depend on the spelling.
GROUPS = {"items": "item", "documents": "document"}
ENV_FILE, NO_MASKING = "--env-file", "--no-masking"
REFUSAL = "is refused for agents; use op run, which puts the values into the command only"
ORDER_DESKTOP = "Only the operator can order the desktop route, op desktop -- <command>."
MISSING = "op: the 1Password CLI is not installed on this machine"


class Refusal(Exception):
    """This request releases nothing, the message says why and what the operator can order."""


def _flag(args: list[str], index: int, files: list[str]) -> int:
    """Consume one `op run` flag at index into files, returning the next index."""
    arg = args[index]
    if arg == ENV_FILE and index + 1 < len(args):
        files.append(args[index + 1])
        return index + 2
    if arg.startswith(ENV_FILE + "="):
        files.append(arg.partition("=")[2])
        return index + 1
    if arg == NO_MASKING:
        raise ValueError(f"{NO_MASKING} is refused, values stay masked")
    raise ValueError(f"{arg} is not supported by the session's op")


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


def real_op() -> Path | None:
    """The real `op` next on PATH, never this program's own launcher."""
    own = Path(sys.argv[0]).resolve()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry or ".") / "op"
        if candidate.resolve() != own and os.access(candidate, os.X_OK) and candidate.is_file():
            return candidate
    return None


def execute(argv: list[str], env: dict[str, str] | None = None) -> int:
    """Replace this process with the real `op` and the given line."""
    binary = real_op()
    if binary is None:
        print(MISSING, file=sys.stderr)
        return 127
    try:
        os.execve(binary, [str(binary), *argv], os.environ if env is None else env)
    except ValueError as error:
        print(f"op: {error}", file=sys.stderr)
        return 2


def normalized(token: str = "") -> dict[str, str]:
    """This environment for the real `op`: the given token or none, and no override of it."""
    env = {name: value for name, value in os.environ.items() if name not in (TOKEN, *OVERRIDES)}
    if token:
        env[TOKEN] = token
    return env


def approved(references: dict[str, str], command: list[str]) -> None:
    """Return once the operator approved this request in Home Assistant, else raise Refusal."""
    if os.environ.get(ROUTE) != TIER_TWO:
        raise Refusal(
            "a tier-two secret needs the operator's word. Once the operator ordered this "
            "command, run it as op tier-two -- <command>."
        )
    asked = request(references, command)
    if not asked["reason"].strip():
        raise Refusal(secret_approval.NO_REASON)
    body = secret_approval.question(asked)
    settings = secret_approval.route()
    try:
        secret_approval.ask(settings, body)
    except secret_approval.Unreachable as error:
        raise Refusal(
            f"Home Assistant did not take the question, {error}. {ORDER_DESKTOP}"
        ) from None
    waits = f"op run: request {body['id']} waits for Home Assistant approval"
    print(waits, file=sys.stderr, flush=True)
    state = secret_approval.decision(settings, body["id"])
    if state != "approved":
        raise Refusal(f"request {body['id']} {state}")


def token_for(references: dict[str, str], command: list[str]) -> str:
    """The token of the request's tier, after the approval a tier-two request needs."""
    try:
        tier = secret_tier.tier(references)
        if tier == secret_tier.TIER_TWO:
            approved(references, command)
        return secret_tier.token(tier)
    except ValueError as error:
        raise Refusal(f"{error}. {ORDER_DESKTOP}") from None


def run_desktop(args: list[str]) -> int:
    """The operator ordered the desktop app: the real `op` reads the line itself."""
    flags = args[: args.index("--") if "--" in args else len(args)]
    if any(flag.partition("=")[0] == NO_MASKING for flag in flags):
        print(f"op run: {NO_MASKING} is refused, values stay masked", file=sys.stderr)
        return 2
    return execute(["run", *args], normalized())


def resolved(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """The command and its environment for the real `op`, the tier's token included."""
    try:
        files, command = parse(args)
        literals, references = environment(files)
    except ValueError as error:
        raise Refusal(str(error)) from None
    owned = next((name for name in (*literals, *references) if name in RESERVED), None)
    if owned:
        raise Refusal(f"{owned} is set by the session's op and cannot come from an env file")
    token = token_for(references, command) if references else ""
    return command, {**normalized(token), **literals, **references, INSIDE: "1"}


def run(args: list[str]) -> int:
    """Run the command with the references the tier's token resolves, read once and here."""
    if os.environ.get(ROUTE) == DESKTOP:
        return run_desktop(args)
    try:
        command, env = resolved(args)
    except Refusal as error:
        print(f"op run: {error}", file=sys.stderr)
        return 1
    if TOKEN not in env:
        return direct(command, env)
    return execute(["run", "--", ENV, "-u", TOKEN, *command], env)


def direct(command: list[str], env: dict[str, str]) -> int:
    """A line without references needs no 1Password, the command runs with its literals."""
    try:
        os.execvpe(command[0], command, env)
    except (OSError, ValueError) as error:
        print(f"op: {command[0]}: {getattr(error, 'strerror', None) or error}", file=sys.stderr)
        return 127


def choose(argv: list[str]) -> int:
    """`op tier-two -- <command>` or `op desktop -- <command>`: the operator's word, then run."""
    name, command = argv[0], argv[2:]
    if argv[1:2] != ["--"] or not command:
        print(f"op {name}: put -- and the command after it", file=sys.stderr)
        return 2
    if os.environ.get(INSIDE) or os.environ.get(ROUTE):
        print(f"op {name} must be the outermost command, here it is refused", file=sys.stderr)
        return 1
    return direct(command, {**os.environ, ROUTE: name})


def spoken(argv: list[str]) -> list[str]:
    """The line's words without its flags, each command group in its one spelling."""
    return [GROUPS.get(arg, arg) for arg in argv if not arg.startswith("-")]


def refused(argv: list[str]) -> str:
    """The refused command named by the line's words, whatever flags surround them, or empty."""
    words = spoken(argv)
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
    return execute(argv)


def main(argv: list[str]) -> int:
    if os.environ.get(MARK) != "1":
        return execute(argv)
    if argv[:1] == ["run"]:
        return run(argv[1:])
    if argv[:1] in ([TIER_TWO], [DESKTOP]):
        return choose(argv)
    return pass_through(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
