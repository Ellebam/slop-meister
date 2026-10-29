"""Each budget has one mutation. Without it, that class of bloat merges silently."""

from pathlib import Path

import pytest

from slopmeister.quality import budgets, inventory
from slopmeister.quality.inventory import Source
from tests.support.trees import nested, write


def measure(root: Path, relative: str, language: str = "python") -> list[str]:
    source = Source(root / relative, language)
    return [v.metric for v in budgets.measure(source, root)]


def test_nesting_over_3_fails(tmp_path: Path) -> None:
    write(tmp_path, "slopmeister/d.py", nested(4))
    write(tmp_path, "slopmeister/e.py", nested(3))
    assert measure(tmp_path, "slopmeister/d.py") == ["nesting_depth"]
    assert measure(tmp_path, "slopmeister/e.py") == []


def test_instruction_file_over_400_lines_fails(tmp_path: Path) -> None:
    write(tmp_path, "plots/example-app/skills/x/fits.md", "line\n" * 400)
    write(tmp_path, "plots/example-app/skills/x/too-big.md", "line\n" * 401)
    assert measure(tmp_path, "plots/example-app/skills/x/fits.md", "source") == []
    assert measure(tmp_path, "plots/example-app/skills/x/too-big.md", "source") == ["file_lines"]


def test_runtime_source_classification_keeps_code_budgets_and_excludes_fixtures() -> None:
    expected = {
        "slopmeister/cli.py": "python",
        "tests/unit/test_cli.py": "python",
        "bin/slopmeister": "python",
        "scripts/check.sh": "bash",
        "host/tests/test_roles.py": "python",
        "host/scripts/check.sh": "bash",
        "host/ansible/roles/example/tasks/main.yml": "source",
        "host/home-assistant/config/www/panel.js": "source",
        "host/package-lock.json": "other",
        "host/node_modules/example/index.js": "ignored",
        "src/skills/x/scripts/tool.py": "python",
        "plots/vault/bin/vault-lock.py": "python",
        "plots/vault/bin/vaultgit": "bash",
        "src/skills/x/SKILL.md": "source",
        "plots/example-app/project.md": "source",
        "scripts/tool": "source",
        "plots/example-app/skills/x/fixtures/blank.jpg": "data",
    }
    assert {path: inventory.classify(path) for path in expected} == expected


def test_unparsable_file_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    """A file with a syntax error would otherwise abort the whole gate with a traceback."""
    write(tmp_path, "slopmeister/broken.py", "def f():\nx = 1\n")
    assert measure(tmp_path, "slopmeister/broken.py") == ["syntax"]


@pytest.mark.parametrize(
    "path",
    ("README.md", "docs/guide.md", "src/skills/x/SKILL.md", "plots/example-app/skills/x/SKILL.md"),
)
def test_document_word_budget_rejects_huge_single_line_prose(tmp_path: Path, path: str) -> None:
    write(tmp_path, path, "word " * 2000)
    language = inventory.classify(path)
    assert measure(tmp_path, path, language) == []
    write(tmp_path, path, "word " * 2001)
    assert measure(tmp_path, path, language) == ["document_words"]


@pytest.mark.parametrize("path", ("README.md", "docs/guide.md"))
def test_repository_document_does_not_inherit_runtime_line_budget(tmp_path: Path, path: str):
    write(tmp_path, path, "word\n" * 401)
    assert measure(tmp_path, path, inventory.classify(path)) == []


@pytest.mark.parametrize("path", ("src/skills/x/SKILL.md", "plots/example-app/skills/x/SKILL.md"))
def test_skill_word_budget_does_not_replace_its_existing_line_budget(tmp_path: Path, path):
    write(tmp_path, path, "word\n" * 401 + "word " * 1600)
    assert measure(tmp_path, path, inventory.classify(path)) == ["file_lines", "document_words"]


@pytest.mark.parametrize("language", ["python", "bash"])
def test_code_has_one_400_line_limit(tmp_path, language):
    body = "x = 1\n" if language == "python" else "true\n"
    suffix = "def f():\n    return x\n" if language == "python" else ""
    name = "slopmeister/code.py" if language == "python" else "scripts/code.sh"
    write(tmp_path, name, body * (400 - len(suffix.splitlines())) + suffix)
    assert measure(tmp_path, name, language) == []
    with (tmp_path / name).open("a") as stream:
        stream.write(body)
    assert measure(tmp_path, name, language) == ["file_lines"]
