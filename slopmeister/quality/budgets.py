"""File length, document words and nesting depth. Ruff owns function complexity."""

import ast
from dataclasses import dataclass
from pathlib import Path

from slopmeister.quality.inventory import Source

HARD_MAX_LINES = 400
DOCUMENT_WORDS = 2000
NESTING_DEPTH = 3
NESTING_NODES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.Match)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    metric: str
    symbol: str
    value: int
    limit: int

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.metric} {self.symbol} {self.value} > {self.limit}"


def depth_of(node: ast.AST, current: int = 0) -> int:
    deepest = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        step = 1 if isinstance(child, NESTING_NODES) else 0
        deepest = max(deepest, depth_of(child, current + step))
    return deepest


def python_violations(source: Source, relative: str) -> list[Violation]:
    try:
        tree = ast.parse(source.path.read_text())
    except SyntaxError as error:
        return [Violation(relative, error.lineno or 1, "syntax", error.msg, 1, 0)]
    found = []
    lines = len(source.path.read_text().splitlines())
    if lines > HARD_MAX_LINES:
        found.append(Violation(relative, 1, "file_lines", "__file__", lines, HARD_MAX_LINES))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            depth = depth_of(node)
            if depth > NESTING_DEPTH:
                found.append(
                    Violation(
                        relative, node.lineno, "nesting_depth", node.name, depth, NESTING_DEPTH
                    )
                )
    return found


def measure(source: Source, root: Path) -> list[Violation]:
    relative = str(source.path.relative_to(root))
    if source.language == "python":
        return python_violations(source, relative)
    text = source.path.read_text()
    lines = len(text.splitlines())
    found = []
    if source.language != "document" and lines > HARD_MAX_LINES:
        found.append(Violation(relative, 1, "file_lines", "__file__", lines, HARD_MAX_LINES))
    parts = Path(relative).parts
    skill = parts[-1] == "SKILL.md" and (
        len(parts) == 4
        and parts[:2] == ("src", "skills")
        or len(parts) == 5
        and parts[0] == "plots"
        and parts[2] == "skills"
    )
    if source.language == "document" or skill:
        words = len(text.split())
        if words > DOCUMENT_WORDS:
            found.append(
                Violation(relative, 1, "document_words", "__file__", words, DOCUMENT_WORDS)
            )
    return found
