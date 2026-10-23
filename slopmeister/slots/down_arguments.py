"""Parse the exact allocation and explicit release options."""

from collections.abc import Sequence
from dataclasses import dataclass

from slopmeister.errors import UsageError

USAGE = "usage: slopmeister slots down <repo> <target> <name> [--force] [--slot <n>] [--self]"


@dataclass(frozen=True)
class Request:
    repo: str
    target: str
    name: str
    force: bool
    wanted: str
    own: bool = False


def parse(argv: Sequence[str]) -> Request:
    args = list(argv)
    if len(args) < 3:
        raise UsageError(USAGE)
    repo, target, name, *tail = args
    flags, wanted = set(), ""
    while tail:
        if tail[0] in ("--force", "--self"):
            flags.add(tail.pop(0))
        elif tail[0] == "--slot" and len(tail) >= 2:
            wanted, tail = tail[1], tail[2:]
        else:
            raise UsageError(USAGE)
    return Request(repo, target, name, "--force" in flags, wanted, "--self" in flags)
