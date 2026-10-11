"""The machine files of the session's op, and the tier a request belongs to.

The setup step writes one service-account token per tier and the vault names each token lists.
A request is tier one when every vault it names is in the first list, tier two when every vault
is in either list, and has no tier otherwise.
"""

import json
import os
from pathlib import Path
import stat

DIRECTORY = ".config/slopmeister/op"
TIER_ONE, TIER_TWO = "tier-one", "tier-two"
TIERS = (TIER_ONE, TIER_TWO)
LISTS = "tiers.json"
FILE_LIMIT = 1048576


def directory() -> Path:
    return Path.home() / DIRECTORY


def private(path: Path) -> str:
    """The text of a regular file only its owner can read, or a ValueError naming the file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        raise ValueError(f"{path}: {error.strerror}") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        owned = stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
        if not owned or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError(f"{path} must be a regular file of this user with mode 600")
        data = stream.read(FILE_LIMIT + 1)
    if not data.strip() or len(data) > FILE_LIMIT:
        raise ValueError(f"{path} is empty or too large")
    return data.decode()


def token(tier: str) -> str:
    return private(directory() / f"{tier}.token").strip()


def lists() -> dict[str, set[str]]:
    """Each tier's vault names and IDs, case-folded as 1Password compares them."""
    try:
        data = json.loads(private(directory() / LISTS))
        return {
            tier: {str(value).casefold() for vault in data[tier] for value in vault.values()}
            for tier in TIERS
        }
    except KeyError, TypeError, AttributeError, json.JSONDecodeError:
        raise ValueError(f"{directory() / LISTS} does not hold both tier lists") from None


def vault(reference: str) -> str:
    return reference.removeprefix("op://").split("/", 1)[0]


def tier(references: dict[str, str]) -> str:
    """The tier of the named vaults together, or a ValueError naming the vault in no tier."""
    known = lists()
    named = {vault(reference) for reference in references.values()}
    outside = sorted(name for name in named if name.casefold() not in known[TIER_ONE])
    if not outside:
        return TIER_ONE
    stranger = next((name for name in outside if name.casefold() not in known[TIER_TWO]), None)
    if stranger is not None:
        raise ValueError(f"the vault {stranger} is in no tier on this machine")
    return TIER_TWO
