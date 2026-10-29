"""Small source trees for the quality checker, written without git so they measure files only."""

from pathlib import Path


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def nested(levels: int) -> str:
    lines = ["def deep():"]
    for level in range(levels):
        lines.append("    " * (level + 1) + f"if {level} < 9:")
    lines.append("    " * (levels + 1) + "return 1")
    return "\n".join(lines) + "\n"
