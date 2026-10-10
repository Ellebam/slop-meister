"""Writing rules for the plot sources a session loads, and the length of the global source."""

from fnmatch import fnmatch
from pathlib import Path
import re

GLOBAL = "plots/home/global.md"
GLOBAL_MAX_LINES = 200
# Skill bodies and the home tool trees follow their own formats, see docs/plot-shape.md.
# As with find, a star crosses directories.
EXCLUDED = ("plots/*/skills/*", "plots/home/claude/*", "plots/home/codex/*")
CODE_SPAN = re.compile(r"`[^`]*`")
AT_TOKEN = re.compile(r"(^|\s)@\S")


def _plot_sources(root: Path) -> list[Path]:
    plots = root / "plots"
    return sorted(
        path
        for path in plots.rglob("*.md")
        if not any(fnmatch(str(path.relative_to(root)), pattern) for pattern in EXCLUDED)
    )


def _punctuation(line: str) -> bool:
    return ("—" in line or ";" in line) and "`" not in line


def findings(root: Path) -> list[str]:
    found = []
    source = root / GLOBAL
    if source.exists():
        lines = len(source.read_text().splitlines())
        if lines > GLOBAL_MAX_LINES:
            found.append(f"{GLOBAL} is {lines} lines, keep it under {GLOBAL_MAX_LINES}")
    for path in _plot_sources(root):
        relative = path.relative_to(root)
        text = path.read_text().splitlines()
        if any(_punctuation(line) for line in text):
            found.append(f"{relative} carries an em dash or a mid-sentence semicolon outside code")
        if any(AT_TOKEN.search(CODE_SPAN.sub("", line)) for line in text):
            found.append(
                f"{relative} carries an @token outside backticks, "
                "Claude Code would treat it as an import"
            )
    return found
