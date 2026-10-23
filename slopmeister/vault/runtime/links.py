"""Resolve vault links and heading fragments without evaluating note content."""

from pathlib import Path
import re
from urllib.parse import unquote

WIKI = re.compile(r"\[\[[^]]+\]\]")
MARKDOWN = re.compile(
    r"\[[^]]*\]\((?:[^()]|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\))*\)"
)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PUBLISHED = re.compile(r"^status:[ \t]*(['\"]?)published\1[ \t\r]*$", re.M)
PROTECTED = "protected (published mirror) "


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _fence(line: str, active: tuple[str, int] | None) -> tuple[tuple[str, int] | None, bool]:
    found = re.match(r"(`{3,}|~{3,})(.*)$", line)
    if found is None:
        return active, False
    run, rest = found.groups()
    char = run[0]
    if active is None and not (char == "`" and "`" in rest):
        return (char, len(run)), True
    if active and char == active[0] and len(run) >= active[1] and not rest.strip():
        return None, True
    return active, active is not None


def _strip_code(text: str) -> str:
    kept: list[str] = []
    active: tuple[str, int] | None = None
    for original in text.splitlines():
        indent = len(original) - len(original.lstrip(" "))
        line = original.lstrip(" ") if indent <= 3 else original
        active, omit = _fence(line, active)
        if not omit and active is None:
            kept.append(re.sub(r"`[^`]*`", "", original))
    return "\n".join(kept)


def _slug(value: str) -> str:
    value = re.sub(r"[`*_~]", "", value.lower())
    value = re.sub(r"[^\w _-]", "", value)
    return re.sub(r"-+", "-", re.sub(r"[ _]+", "-", value)).strip("-")


def heading_exists(path: Path, fragment: str) -> bool:
    if path.suffix.lower() not in (".md", ".markdown"):
        return True
    wanted = unquote(fragment)
    if (text := _read(path)) is None or wanted.startswith("^") or "#" in wanted:
        return False
    headings = (
        match.group(1).strip()
        for line in _strip_code(text).splitlines()
        if (match := re.match(r"^\s{0,3}#+\s+(.+?)\s*#*\s*$", line))
    )
    return any(
        heading.casefold() == wanted.casefold() or _slug(heading) == wanted.casefold()
        for heading in headings
    )


class Resolver:
    def __init__(self, vault: Path):
        self.vault = vault.resolve()
        self.by_name: dict[str, Path] = {}
        for path in sorted(self.vault.rglob("*")):
            relative = path.relative_to(self.vault)
            hidden = any(part.startswith(".") for part in relative.parts)
            if path.is_file() and not path.is_symlink() and not hidden:
                self.by_name.setdefault(path.name.casefold(), path)

    def file(self, candidate: str | Path) -> Path | None:
        path = Path(candidate)
        path = path if path.is_absolute() else self.vault / path
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.vault)
        except OSError, ValueError:
            return None
        return resolved if resolved.is_file() else None

    def wiki(self, target: str, directory: Path, current: Path) -> Path | None:
        if not target:
            return current
        candidates = (target, target + ".md", directory / target, directory / (target + ".md"))
        for candidate in candidates:
            if found := self.file(candidate):
                return found
        if "/" not in target and "\\" not in target:
            exact = self.by_name.get(target.casefold())
            return exact or self.by_name.get((target + ".md").casefold())
        return None

    def markdown(self, target: str, directory: Path, current: Path) -> Path | None:
        if not target:
            return current
        for candidate in (directory / target, target, directory / (target + ".md"), target + ".md"):
            if found := self.file(candidate):
                return found
        return None


def _target(raw: str, markdown: bool) -> tuple[str, str]:
    if markdown:
        value = raw.split("](", 1)[1][:-1]
        title = r"\s+(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\))\s*$"
        value = re.sub(title, "", value)
        if value.startswith("<") and value.endswith(">"):
            value = value[1:-1]
    else:
        value = raw[2:-2].split("|", 1)[0].removesuffix("\\").strip()
    target, separator, fragment = value.partition("#")
    return unquote(target), fragment if separator else ""


def _check_link(resolver: Resolver, note: Path, item: tuple[str, bool]) -> tuple[str, str] | None:
    raw, markdown = item
    target, fragment = _target(raw, markdown)
    if markdown and SCHEME.match(target):
        return None
    directory = note.parent.relative_to(resolver.vault)
    resolve = resolver.markdown if markdown else resolver.wiki
    found = resolve(target, directory, note)
    if fragment.startswith("^") or "#" in fragment:
        return raw, "unsupported fragment in "
    if found is None or (fragment and not heading_exists(found, fragment)):
        return raw, ""
    return None


def _note_links(resolver: Resolver, note: Path) -> list[tuple[str, bool]]:
    if (source := _read(note)) is None:
        return []
    text, broken = _strip_code(source), []
    frontmatter = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", source, re.S)
    protected = bool(frontmatter and PUBLISHED.search(frontmatter[1]))
    prefix = f"{note.relative_to(resolver.vault)}: {PROTECTED if protected else ''}"
    for markdown, pattern in ((False, WIKI), (True, MARKDOWN)):
        for match in pattern.finditer(text):
            if problem := _check_link(resolver, note, (match.group(), markdown)):
                raw, label = problem
                broken.append((f"{prefix}{label}{raw}", protected))
    return broken
