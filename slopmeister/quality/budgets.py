"""File length, function length, nesting depth and parameter count. Ruff owns complexity."""

import ast
from dataclasses import dataclass
from pathlib import Path

from slopmeister.quality.inventory import Source

FILE_LINES = 250
HARD_MAX_LINES = 400
DOCUMENT_WORDS = 2000
FUNCTION_LINES = 30
NESTING_DEPTH = 3
PARAMETERS = 3
TEST_PARAMETERS = 5
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


def is_test_path(path: Path) -> bool:
    return "tests" in path.parts and path.name.startswith("test_")


def constants_only(tree: ast.Module) -> bool:
    """A module holding only data tables is exempt from file length, nothing runs in it."""
    allowed = (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom, ast.Expr)
    return all(isinstance(node, allowed) for node in tree.body) and not any(
        isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant)
        for node in tree.body
    )


def depth_of(node: ast.AST, current: int = 0) -> int:
    deepest = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        step = 1 if isinstance(child, NESTING_NODES) else 0
        deepest = max(deepest, depth_of(child, current + step))
    return deepest


def parameter_count(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    arguments = function.args
    names = [a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs]
    return len([name for name in names if name not in ("self", "cls")])


def function_violations(
    relative: str, function: ast.FunctionDef | ast.AsyncFunctionDef, test_file: bool
) -> list[Violation]:
    found = []
    length = function.end_lineno - function.lineno + 1
    if length > FUNCTION_LINES:
        found.append(
            Violation(
                relative, function.lineno, "function_lines", function.name, length, FUNCTION_LINES
            )
        )
    depth = depth_of(function)
    if depth > NESTING_DEPTH:
        found.append(
            Violation(
                relative, function.lineno, "nesting_depth", function.name, depth, NESTING_DEPTH
            )
        )
    limit = TEST_PARAMETERS if test_file else PARAMETERS
    parameters = parameter_count(function)
    if parameters > limit:
        found.append(
            Violation(relative, function.lineno, "parameters", function.name, parameters, limit)
        )
    return found


def python_violations(source: Source, relative: str) -> list[Violation]:
    try:
        tree = ast.parse(source.path.read_text())
    except SyntaxError as error:
        return [Violation(relative, error.lineno or 1, "syntax", error.msg, 1, 0)]
    found = []
    lines = len(source.path.read_text().splitlines())
    constant_table = constants_only(tree)
    if lines > FILE_LINES and not constant_table:
        found.append(Violation(relative, 1, "file_lines", "__file__", lines, FILE_LINES))
    elif lines > HARD_MAX_LINES:
        found.append(Violation(relative, 1, "file_lines", "__file__", lines, HARD_MAX_LINES))
    test_file = is_test_path(source.path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.extend(function_violations(relative, node, test_file))
    return found


def measure(source: Source, root: Path) -> list[Violation]:
    relative = str(source.path.relative_to(root))
    if source.language == "python":
        return python_violations(source, relative)
    text = source.path.read_text()
    lines = len(text.splitlines())
    limit = FILE_LINES if source.language == "bash" else HARD_MAX_LINES
    found = []
    if source.language != "document" and lines > limit:
        found.append(Violation(relative, 1, "file_lines", "__file__", lines, limit))
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
