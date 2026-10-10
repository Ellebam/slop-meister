"""Supervisor redaction keeps real citations valid while masking what it saves and shows."""

import json
from pathlib import Path

import pytest

from slopmeister.review.redact import redact
from slopmeister.spine.tester import runs
from slopmeister.spine.tester.collect import collect
from slopmeister.spine.tester.supervise import supervise
from slopmeister.spine.tester.validate import validate_verdict


def _snapshot(root: Path) -> dict:
    return {p: p.read_bytes() for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize(
    "quote",
    [
        "SECRET_OPERATION_FAILED_CHECK_1PASSWORD_AND_TARGET_ACCESS",
        "secret_" + "a" * 20,
        "ghp_" + "a" * 36,
        "Bearer\n" + "a" * 20,
    ],
)
@pytest.mark.parametrize("status", ["pass", "fail", "blocked"])
def test_supervisor_redaction_preserves_valid_evidence_and_outcome(
    supervised_run, verdict, capsys, quote, status
):
    """A real quote must not become an absent citation when the report masks it."""
    root, _, _ = supervised_run
    original = (quote + "\n").encode()
    (root / "evidence/output.txt").write_bytes(original)
    verdict["scenarios"][0].update(
        verdict=status, evidence=[{"path": "evidence/output.txt", "quote": quote}]
    )
    expected = 0 if status == "pass" else 1
    assert supervise(root) == expected
    saved = json.loads((root / "verdict.json").read_text())
    assert validate_verdict(saved, ["basic"], root) == status
    item = saved["scenarios"][0]["evidence"][0]
    excerpt = root / item["path"]
    assert excerpt.parent == root / "evidence" and excerpt.name.startswith("report-evidence-")
    assert excerpt.read_text() == 'Source: "evidence/output.txt"\n\n' + redact(quote) + "\n"
    assert item["quote"] == redact(quote)
    assert (root / "evidence/output.txt").read_bytes() == original
    report = (root / "report.md").read_text()
    assert item["path"] in report and item["quote"] in report
    for path in (root / "verdict.json", root / "report.md", excerpt):
        assert quote not in path.read_text()
    before = _snapshot(root)
    assert collect(root, 0) == collect(root, 0) == expected
    assert capsys.readouterr().out == report * 2
    with pytest.raises(FileExistsError):
        supervise(root)
    assert _snapshot(root) == before


def test_supervisor_redaction_keeps_mixed_citations_distinct_and_masks_source(
    supervised_run, verdict
):
    """Changing only a path must not leak its sentinel or overwrite another excerpt."""
    root, _, _ = supervised_run
    secret = "secret_" + "a" * 20
    path = "evidence/" + secret + '\n".txt'
    (root / path).write_text("ordinary output")
    (root / "evidence/second.txt").write_text(secret)
    original = [
        {"path": "evidence/output.txt", "quote": "actual command output"},
        {"path": path, "quote": "ordinary output"},
        {"path": "evidence/second.txt", "quote": secret},
    ]
    verdict["scenarios"][0]["evidence"] = original
    assert supervise(root) == 0
    saved = json.loads((root / "verdict.json").read_text())
    assert validate_verdict(saved, ["basic"], root) == "pass"
    items = saved["scenarios"][0]["evidence"]
    assert items[0] == original[0]
    assert len({item["path"] for item in items}) == 3
    assert len(list(root.glob("evidence/report-evidence-*"))) == 2
    for item, source in zip(items[1:], original[1:], strict=True):
        text = (root / item["path"]).read_text()
        masked = json.dumps(redact(source["path"]))
        assert text == "Source: " + masked + "\n\n" + redact(source["quote"]) + "\n"
        assert secret not in text
    assert (root / path).read_text() == "ordinary output"
    assert (root / "evidence/second.txt").read_text() == secret
    assert secret not in (root / "verdict.json").read_text() + (root / "report.md").read_text()


def test_supervisor_refuses_masking_collision_before_creating_evidence_then_recovers(
    supervised_run, verdict
):
    """Different secrets that redact identically must not manufacture valid evidence."""
    root, _, _ = supervised_run
    actual, invented = "secret_" + "a" * 20, "secret_" + "b" * 20
    assert redact(actual) == redact(invented)
    (root / "evidence/output.txt").write_text(actual)
    verdict["scenarios"][0]["evidence"][0]["quote"] = invented
    assert supervise(root) == 1
    assert not list(root.glob("**/report-evidence-*"))
    assert not (root / "verdict.json").exists()
    assert "evidence quote is absent" in (root / "report.md").read_text()
    refused = _snapshot(root)
    recovery = root.parent / "recovery"
    (recovery / "checkout").mkdir(parents=True)
    (recovery / "evidence").mkdir()
    run = json.loads((root / "run.json").read_text())
    run["checkout"] = str(recovery / "checkout")
    runs.save(recovery / "run.json", run)
    for name in ("guide.md", "validation.md", "evidence/output.txt"):
        (recovery / name).write_bytes((root / name).read_bytes())
    verdict["scenarios"][0]["evidence"][0]["quote"] = actual
    assert supervise(recovery) == 0
    saved = json.loads((recovery / "verdict.json").read_text())
    assert validate_verdict(saved, ["basic"], recovery) == "pass"
    assert _snapshot(root) == refused
