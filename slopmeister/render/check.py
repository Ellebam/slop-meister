"""Shared validation and byte-comparison helpers for rendering."""

from pathlib import Path
import re

FILL_MARKER = re.compile(r"\{\{FILL:([a-z0-9-]+)\}\}")
TOOL_BLOCK_OPEN = re.compile(r"\{\{TOOL:(claude|codex)\}\}")
TOOL_BLOCK_CLOSE = "{{/TOOL}}"


def parse_meta(path: Path) -> dict[str, str]:
    """Parse the flat key/value and literal-block metadata subset."""
    if not path.is_file():
        return {}
    lines, meta, index = path.read_text().splitlines(), {}, 0
    while index < len(lines):
        line, index = lines[index], index + 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            raise ValueError(f"{path}: unexpected indented line outside a block: {line!r}")
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{path}: not a 'key: value' line: {line!r}")
        key, value = key.strip(), value.strip()
        if key in meta:
            raise ValueError(f"{path}: duplicate key {key!r} — last-one-wins is ambiguous")
        value, index = _literal(lines, index) if value == "|" else (value, index)
        meta[key] = value
    return meta


def _literal(lines: list[str], index: int) -> tuple[str, int]:
    block = []
    while index < len(lines) and (lines[index].startswith("  ") or not lines[index].strip()):
        block.append(lines[index][2:] if lines[index].startswith("  ") else "")
        index += 1
    while block and not block[-1]:
        block.pop()
    return "\n".join(block), index


def split_frontmatter(text: str, origin: Path) -> tuple[str, str]:
    """Return frontmatter body and the remaining document."""
    if "\r" in text:
        raise ValueError(f"{origin}: CRLF/CR line endings are not supported — convert to LF")
    if not text.startswith("---\n"):
        raise ValueError(f"{origin}: missing YAML frontmatter")
    match = re.search(r"\n---[ \t]*(\n|$)", text[3:])
    if match is None:
        raise ValueError(f"{origin}: frontmatter has no closing --- line")
    end = 3 + match.start()
    return text[4:end], text[3 + match.end() :]


def frontmatter_value(frontmatter: str, key: str) -> str | None:
    for line in frontmatter.splitlines():
        if line.startswith(f"{key}:"):
            return line.partition(":")[2].strip()
    return None


def check_meta_keys(meta: dict, allowed: set, origin: Path) -> None:
    unknown = set(meta) - allowed
    if unknown:
        raise ValueError(
            f"{origin}: unknown meta key(s) {sorted(unknown)} — allowed: {sorted(allowed)}"
        )


def single_line(value: str, origin: Path, key: str) -> str:
    if "\n" in value or any(ord(char) < 0x20 and char != "\t" for char in value):
        raise ValueError(f"{origin}: '{key}' must be a single line without control characters")
    return value


def reject_symlinks(root: Path) -> None:
    """Refuse source trees that can read outside the repository."""
    if root.is_symlink() or any(item.is_symlink() for item in sorted(root.rglob("*"))):
        raise ValueError(f"{root}: symlinks are not allowed in skill sources")


def resolve_tool_blocks(body: str, tool: str, source: tuple[Path, int, bool]) -> str:
    """Resolve whole-line tool blocks for one target tool."""
    if "{{" not in body:
        return body
    origin, offset, task_templates = source
    kept, active = [], None
    for number, line in enumerate(body.splitlines(), 1 + offset):
        action, selected = _block_action(line, active, (origin, number, task_templates))
        if action == "open":
            active = selected
        if action == "close":
            active = None
        if action == "text" and (active is None or active == tool):
            kept.append(line)
    if active is not None:
        raise ValueError(f"{origin}: {{{{TOOL:{active}}}}} block is never closed")
    return "\n".join(kept) + "\n"


def _unsanctioned(line: str, task_templates: bool) -> bool:
    checked = re.sub(r"\{\{\.[A-Za-z][A-Za-z0-9]*\}\}", "", line) if task_templates else line
    return "{{" in checked


def _block_action(
    line: str, active: str | None, context: tuple[Path, int, bool]
) -> tuple[str, str | None]:
    origin, number, task_templates = context
    match = TOOL_BLOCK_OPEN.fullmatch(line)
    if match and active is not None:
        raise ValueError(f"{origin}:{number}: tool block inside an open block — blocks do not nest")
    if match:
        return "open", match.group(1)
    if line == TOOL_BLOCK_CLOSE and active is None:
        raise ValueError(f"{origin}:{number}: {{{{/TOOL}}}} without an open block")
    if line == TOOL_BLOCK_CLOSE:
        return "close", None
    if _unsanctioned(line, task_templates):
        raise ValueError(f"{origin}:{number}: unsanctioned '{{{{' token in a skill body")
    return "text", None


def trees_differ(first: Path, second: Path) -> bool:
    """Compare directory trees byte for byte."""
    files_first = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    files_second = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    return files_first != files_second or any(
        (first / relative).read_bytes() != (second / relative).read_bytes()
        for relative in files_first
    )


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_string(value: str) -> str:
    if "\n" in value:
        return f'"""\n{value.replace("\\", "\\\\").replace(chr(34) * 3, '\\"""')}\n"""'
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
