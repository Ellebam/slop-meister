"""The quality inventory reports the enforced ceiling and visible exceptions."""

import json
from pathlib import Path
import subprocess

import pytest

from tests.support.repos import scratch_repo

ROOT = Path(__file__).resolve().parents[3]


def run_quality_inventory(root: Path) -> subprocess.CompletedProcess[str]:
    command = [str(ROOT / "bin/slopmeister"), "quality", "--root", str(root), "--inventory"]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def parse_inventory_report(output: str) -> dict:
    value, _ = json.JSONDecoder().raw_decode(output)
    return value


def allow_401_line_skill(root: Path) -> None:
    exception = {
        "path": "plots/example-app/skills/example/SKILL.md",
        "metric": "file_lines",
        "symbol": "__file__",
        "ceiling": 401,
        "target": 400,
        "owner": "issue-999",
        "rationale": "operator-approved high-water mark",
    }
    (root / "quality-allowlist.json").write_text(
        json.dumps({"version": 1, "exceptions": [exception]})
    )


def test_inventory_reports_400_boundary_and_keeps_approved_exception_visible(
    tmp_path: Path,
) -> None:
    root = scratch_repo(tmp_path / "slopmeister")
    skill = root / "plots/example-app/skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("line\n" * 400)
    result = run_quality_inventory(root)
    assert result.returncode == 0
    assert parse_inventory_report(result.stdout)["oversized_400"] == 0

    skill.write_text("line\n" * 401)
    result = run_quality_inventory(root)
    assert result.returncode != 0
    assert parse_inventory_report(result.stdout)["oversized_400"] == 1

    allow_401_line_skill(root)
    result = run_quality_inventory(root)
    assert result.returncode == 0
    inventory_report = parse_inventory_report(result.stdout)
    assert inventory_report["oversized_400"] == 1
    assert inventory_report["allowlist"][0]["ceiling"] == 401


@pytest.mark.parametrize(
    "path",
    (
        "README.md",
        "host/README.md",
        "docs/guide.md",
        "src/skills/x/SKILL.md",
        "plots/example-app/skills/x/SKILL.md",
    ),
)
def test_cli_includes_each_document_family_before_commit(tmp_path: Path, path: str):
    root = scratch_repo(tmp_path / "subject")
    document = root / path
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("word " * 2000)
    result = run_quality_inventory(root)
    assert result.returncode == 0, result.stdout
    document.write_text("word " * 2001)
    result = run_quality_inventory(root)
    assert result.returncode == 1, result.stdout
    assert f"{path}:1: document_words __file__ 2001 > 2000" in result.stdout
