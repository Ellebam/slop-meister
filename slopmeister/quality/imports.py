"""Import direction, cycles, the self-contained session subpackage and runtime edges."""

import ast
from dataclasses import dataclass, field
from importlib.util import resolve_name
from pathlib import Path
import re

from slopmeister.errors import SlopmeisterError
from slopmeister.quality.budgets import Violation
from slopmeister.quality.inventory import Source

PACKAGE = "slopmeister"
SESSION = "slopmeister.session"
VAULT_RUNTIME = "slopmeister.vault.runtime"
FORBIDDEN_TARGETS = {"tests", "scripts"}
RUNTIME_EDGE = re.compile(r"scripts/[\w./-]+\.py|runpy\.run_path|sys\.path\.insert")
# The gate runner's catalogue launches every check as a command, that is its job, not reuse.
EDGE_EXEMPT = ("slopmeister/check/catalogue.py",)


def module_name(relative: str) -> str:
    parts = Path(relative).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_names(tree: ast.Module, module: str, is_package: bool) -> list[tuple[str, str | None]]:
    """Every import as (module, imported name), the name being None for a plain import."""
    names: list[tuple[str, str | None]] = []
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((alias.name, None) for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        target = "." * node.level + (node.module or "")
        try:
            target = resolve_name(target, package)
        except ImportError as error:
            raise SlopmeisterError(f"{module}:{node.lineno}: {error}") from None
        names.extend((target, alias.name) for alias in node.names)
    return names


def _resolve(name: str, known: set[str]) -> str | None:
    """The longest known module prefix of an imported name, or None for stdlib and third party."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def _parsed(path: Path) -> ast.Module | None:
    """The module tree, or None for a file the budgets already report as unparsable."""
    try:
        return ast.parse(path.read_text())
    except SyntaxError:
        return None


def graph(sources: list[Source], root: Path) -> dict[str, list[str]]:
    """Module to the repository modules it imports, resolved against the parsed set."""
    parsed = {
        module_name(str(s.path.relative_to(root))): (tree, s.path.name == "__init__.py")
        for s in sources
        if s.language == "python" and s.path.suffix == ".py" and (tree := _parsed(s.path))
    }
    known = set(parsed)
    edges: dict[str, list[str]] = {}
    for module, (tree, is_package) in parsed.items():
        targets = set()
        for module_part, name in imported_names(tree, module, is_package):
            full = f"{module_part}.{name}" if name else module_part
            targets.add(_resolve(full, known) or module_part)
        edges[module] = sorted(
            t for t in targets if t.split(".")[0] in (PACKAGE, "tests", "scripts")
        )
    return edges


@dataclass
class Walk:
    edges: dict[str, list[str]]
    stack: list[str] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)


def _cycle_from(node: str, walk: Walk) -> list[str] | None:
    if node in walk.stack:
        return walk.stack[walk.stack.index(node) :] + [node]
    if node in walk.seen:
        return None
    walk.seen.add(node)
    walk.stack.append(node)
    for target in walk.edges.get(node, ()):
        if target in walk.edges and (found := _cycle_from(target, walk)):
            return found
    walk.stack.pop()
    return None


def cycles(edges: dict[str, list[str]]) -> list[list[str]]:
    walk = Walk(edges)
    found = []
    for node in sorted(edges):
        cycle = _cycle_from(node, walk)
        if cycle:
            found.append(cycle)
    return found


def _direction_violation(module: str, target: str) -> Violation | None:
    top = target.split(".")[0]
    if module.startswith(PACKAGE) and top in FORBIDDEN_TARGETS:
        return Violation(module, 0, "import_direction", target, 1, 0)
    if (
        (module == SESSION or module.startswith(SESSION + "."))
        and top == PACKAGE
        and target != SESSION
        and not target.startswith(SESSION + ".")
    ):
        return Violation(module, 0, "session_self_contained", target, 1, 0)
    if (
        (module == VAULT_RUNTIME or module.startswith(VAULT_RUNTIME + "."))
        and top == PACKAGE
        and target != VAULT_RUNTIME
        and not target.startswith(VAULT_RUNTIME + ".")
    ):
        return Violation(module, 0, "vault_runtime_self_contained", target, 1, 0)
    return None


def direction_violations(edges: dict[str, list[str]]) -> list[Violation]:
    found = []
    for module, targets in sorted(edges.items()):
        found.extend(v for t in targets if (v := _direction_violation(module, t)))
    return found


def runtime_edges(sources: list[Source], root: Path) -> list[Violation]:
    """A package module that launches another script by path instead of importing it."""
    found = []
    for source in sources:
        relative = str(source.path.relative_to(root))
        if not relative.startswith(PACKAGE + "/") or relative in EDGE_EXEMPT:
            continue
        for number, line in enumerate(source.path.read_text().splitlines(), 1):
            if RUNTIME_EDGE.search(line):
                found.append(Violation(relative, number, "runtime_edge", line.strip()[:60], 1, 0))
    return found


def import_violations(sources: list[Source], root: Path) -> list[Violation]:
    edges = graph(sources, root)
    found = direction_violations(edges) + runtime_edges(sources, root)
    for cycle in cycles(edges):
        found.append(Violation(cycle[0], 0, "import_cycle", " -> ".join(cycle), len(cycle), 0))
    return found
