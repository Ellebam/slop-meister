"""Command-line entry point for allocating, inspecting and releasing slots."""

from collections.abc import Sequence

from slopmeister.errors import UsageError
from slopmeister.slots import down, status, up

USAGE = (
    "usage: slopmeister slots up <repo> <target> <name> [--slot <n>] [launcher args]\n"
    "       slopmeister slots down <repo> <target> <name> [--force] [--slot <n>] [--self]\n"
    "       slopmeister slots status [<repo>]"
)


def main(argv: Sequence[str]) -> int:
    args = list(argv)
    if not args:
        raise UsageError(USAGE)
    command = args.pop(0)
    if command == "up":
        return up.main(args)
    if command == "down":
        return down.main(args)
    if command == "status" and len(args) <= 1:
        return status.live(args[0]) if args else status.static()
    raise UsageError(USAGE)
