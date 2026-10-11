"""Draft citations refused through the tester entry, then accepted without rerunning the subject."""

import json
from pathlib import Path

import pytest

from tests.integration.spine.test_tester_cli import validate

CITATIONS = {"quote", "empty", "escaped", "missing", "parent", "absolute", "symlink"}
DEFECTS = [
    "quote", "empty", "escaped", "missing", "parent", "absolute", "symlink", "scenario",
    "retired-lens", "shape", "list-verdict", "object-verdict", "json", "metadata", "external-draft",
    "symlinked-draft",
]  # fmt: skip


def _citation(root: Path, verdict: dict, defect: str) -> None:
    bad = verdict["scenarios"][0]["evidence"][1]
    outside = root.parent / "evidence/output.txt"
    if defect in QUOTES:
        bad["quote"] = QUOTES[defect]
        return
    (root / "evidence/link.txt").symlink_to(outside)
    paths = {
        "missing": "evidence/absent.txt",
        "parent": "../evidence.txt",
        "absolute": str(outside),
    }
    bad["path"] = paths.get(defect, "evidence/link.txt")


QUOTES = {"quote": "invented output", "empty": " ", "escaped": r"actual command output\n"}
DAMAGE = {
    "scenario": lambda root, v: v["scenarios"][0].update(id="other"),
    "retired-lens": lambda root, v: v.update(security_lens={"checks": ["x"], "evidence": "y"}),
    "shape": lambda root, v: v["scenarios"][0].pop("evidence"),
    "list-verdict": lambda root, v: v["scenarios"][0].update(verdict=[]),
    "object-verdict": lambda root, v: v["scenarios"][0].update(verdict={}),
    "metadata": lambda root, v: (root / "run.json").write_text('{"required": null}'),
}


def _break(root: Path, verdict: dict, defect: str) -> None:
    """Add a second citation and damage the draft or run as `defect` names."""
    item = verdict["scenarios"][0]["evidence"][0]
    verdict["scenarios"][0]["evidence"].append(dict(item))
    if defect in CITATIONS:
        _citation(root, verdict, defect)
    elif defect in DAMAGE:
        DAMAGE[defect](root, verdict)


def _files(root: Path) -> dict:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _draft(root: Path, verdict: dict, defect: str) -> Path:
    draft = (root.parent if defect == "external-draft" else root) / "draft.json"
    draft.write_text("{" if defect == "json" else json.dumps(verdict))
    if defect == "symlinked-draft":
        outside = root.parent / "external.json"
        draft.rename(outside)
        draft.symlink_to(outside)
    return draft


@pytest.mark.parametrize("defect", DEFECTS)
def test_draft_command_rejects_bad_input_then_recovers_without_subject_rerun(
    tmp_path, verdict, defect
):
    """Bad citations and malformed drafts must be actionable errors, not tracebacks or regrades."""
    root = tmp_path / "run"
    (root / "evidence").mkdir(parents=True)
    (root / "evidence/output.txt").write_bytes((tmp_path / "evidence/output.txt").read_bytes())
    (root / "run.json").write_text(json.dumps({"required": ["basic"]}))
    good = json.dumps(verdict)
    _break(root, verdict, defect)
    draft = _draft(root, verdict, defect)
    before = _files(root)
    result = validate(root, draft)
    assert result.returncode == 1 and result.stderr.startswith("INVALID DRAFT:")
    assert "Traceback" not in result.stderr and not result.stdout
    if defect in CITATIONS:
        assert "scenario 1, evidence 2:" in result.stderr
    assert "invented output" not in result.stderr
    assert before == _files(root)
    (root / "run.json").write_text(json.dumps({"required": ["basic"]}))
    draft = root / "draft.json"
    if draft.is_symlink():
        draft.unlink()
    draft.write_text(good)
    result = validate(root, draft)
    assert result.returncode == 0 and "outcome: pass" in result.stdout
    assert (root / "evidence/output.txt").read_bytes() == (
        tmp_path / "evidence/output.txt"
    ).read_bytes()
