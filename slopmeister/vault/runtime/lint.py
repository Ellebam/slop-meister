from pathlib import Path
import re
import sys

from . import conflicts, repository
from .links import Resolver, _note_links, _read
from .links import heading_exists as heading_exists

PIPE = re.compile(r"^\|.*\[\[[^]]*[^\\]\|[^]]*\]\]", re.MULTILINE)
BARE = re.compile(r"\[\[(README|WORKLOG|_INDEX|CUSTOMER|contacts)(\|[^]]*)?(#[^]|]*)?\]\]")


def _files(root: Path, recursive: bool = True) -> list[Path]:
    return sorted(
        path
        for path in (root.rglob if recursive else root.glob)("*.md")
        if path.is_file()
        and not path.is_symlink()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _patterns(root: Path, recursive: bool = True) -> tuple[int, int]:
    texts = [text for path in _files(root, recursive) if (text := _read(path)) is not None]
    return sum(bool(PIPE.search(text)) for text in texts), sum(
        len(BARE.findall(text)) for text in texts
    )


def _area_syntax(value: str, path: Path) -> str | None:
    problem = None
    if not value:
        problem = "is empty"
    elif any(ord(char) < 32 or ord(char) == 127 for char in value):
        problem = "contains a control character"
    if problem is None and path.is_absolute():
        problem = f"'{value}' is absolute, give a vault-relative folder"
    elif problem is None and value in (".", "./"):
        problem = f"'{value}' is the vault root, name the session's folder"
    elif problem is None and ".." in path.parts:
        problem = f"'{value}' contains a parent segment"
    return problem


def _area(vault: Path, value: str) -> tuple[Path | None, str | None]:
    problem = _area_syntax(value, path := Path(value))
    candidate = vault / path
    resolved = None
    if problem is None and not candidate.is_dir():
        problem = f"'{value}' is not a folder in the vault"
    if problem is None:
        resolved, root = candidate.resolve(), vault.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            problem = f"'{value}' resolves outside the vault"
        if resolved == root:
            problem = f"'{value}' is the vault root, name the session's folder"
    return resolved if problem is None else None, problem


def _global(vault: Path) -> int:
    pipes, bare = _patterns(vault)
    print(f"alias-pipe rows:  {pipes} (must be 0)")
    print(f"bare wikilinks:   {bare} (must be 0)")
    resolver = Resolver(vault)
    unresolved = sum(len(_note_links(resolver, note)) for note in _files(vault))
    print(f"unresolved links: {unresolved} (direct resolver)")
    copies = conflicts.copies(vault, vault)
    print(f"conflict copies:  {len(copies)} (must be 0)")
    if copies:
        print("\n".join(f"  {copy}" for copy in copies) + "\n" + conflicts.STEPS)
    if numbered := conflicts.numbered(vault, vault):
        print("\n".join(numbered))
    return int(bool(pipes or bare or copies or numbered))


def _scoped(vault: Path, area_value: str, shallow: bool) -> int:
    area, problem = _area(vault, area_value)
    if problem:
        print(f"refused: --area {problem}", file=sys.stderr)
        return 2
    assert area is not None
    pipes, bare = _patterns(area, not shallow)
    resolver = Resolver(vault)
    links = [entry for note in _files(area, not shallow) for entry in _note_links(resolver, note)]
    protected = sum(mirror for _, mirror in links)
    broken = len(links) - protected
    copies = conflicts.copies(vault, area, not shallow)
    lines = [line for line, _ in links]
    lines.extend(f"{copy}: conflict copy, see slopmeister-vault lint" for copy in copies)
    numbered = conflicts.numbered(vault, area, not shallow)
    print("\n".join(lines + numbered))
    print(
        f"area {area_value.rstrip('/')}: alias-pipe rows {pipes}, bare wikilinks {bare}, "
        f"unresolved links {broken}"
        + (f", protected links {protected}" if protected else "")
        + (f", conflict copies {len(copies)}" if copies else "")
        + (f", numbered copies {len(numbered)}" if numbered else "")
    )
    return int(bool(pipes or bare or broken or copies or numbered))


def run(area_value: str | None, shallow: bool = False) -> int:
    vault = repository.vault_path().resolve()
    if not vault.is_dir():
        print(f"vault not reachable at {vault}")
        return 1
    return _global(vault) if area_value is None else _scoped(vault, area_value, shallow)
