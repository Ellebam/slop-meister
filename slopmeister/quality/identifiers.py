"""Field identifiers in anything git can commit. The one must-fix class, never allowlisted."""

import os
from pathlib import Path
import re
import stat

from slopmeister.errors import SlopmeisterError
from slopmeister.quality import inventory

LISTING = "git ls-files -co --exclude-standard | LC_ALL=C sort"
PATTERN_VARIABLE = "SLOPMEISTER_PRIVATE_PATTERNS"


def _pattern(root: Path) -> re.Pattern[str] | None:
    selected = os.environ.get(PATTERN_VARIABLE)
    default = Path.home() / ".config/slopmeister/private-patterns"
    path = Path(selected).expanduser() if selected else default
    if selected is None and not os.path.lexists(path):
        return None
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or not info.st_mode & stat.S_IRUSR
            or path.resolve().is_relative_to(root.resolve())
        ):
            raise SlopmeisterError(
                "private identifier patterns require an owner-only file outside the repository"
            )
        patterns = [line.strip() for line in path.read_text().splitlines()]
        patterns = [line for line in patterns if line and not line.startswith("#")]
        source = "|".join(f"(?:{line})" for line in patterns)
        return re.compile(source, re.IGNORECASE) if source else None
    except OSError, UnicodeError, re.error:
        raise SlopmeisterError("cannot read or compile private identifier patterns") from None


def _lines(path: Path) -> list[str]:
    if path.is_symlink():
        return [str(path.readlink())]
    data = path.read_bytes()
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    return data.decode(encoding, errors="replace").splitlines()


def findings(root: Path) -> list[str]:
    """`path:line` for every hit, never the matched text, which would itself leak.

    A path that matches is named by its position in the sorted listing instead, so the finding
    for its name or its contents never prints the name.
    """
    pattern = _pattern(root)
    if pattern is None:
        return []
    found = []
    for position, relative in enumerate(inventory.committable(root), 1):
        where = relative
        if pattern.search(relative):
            where = f"committable path #{position}"
            found.append(f"{where}: field identifier, list with: {LISTING} | sed -n {position}p")
        for number, line in enumerate(_lines(root / relative), 1):
            if pattern.search(line):
                found.append(f"{where}:{number}: field identifier")
    return found
