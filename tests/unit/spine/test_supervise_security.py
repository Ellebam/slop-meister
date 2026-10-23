"""Supervisor redaction, identity refusal and draft command delivery."""

import json
from pathlib import Path
import shlex
import sys

import pytest

from slopmeister.spine.tester import process, runs
from slopmeister.spine.tester.collect import collect
from slopmeister.spine.tester.supervise import supervise
from slopmeister.spine.tester.validate import validate_verdict


def _snapshot(root: Path) -> dict:
    return {p: p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_supervisor_masks_sensitive_text_without_damaging_json(supervised_run, verdict):
    """Masking serialized JSON consumed closing quotes in sensitive assignments."""
    root, _, _ = supervised_run
    verdict["regressions"] = [
        {"name": "guard", "bug": "escaping bug", "evidence": "OPENAI_API_KEY=private-fixture-value"}
    ]
    assert supervise(root) == 0
    saved = json.loads((root / "verdict.json").read_text())
    assert saved["regressions"][0]["evidence"] == "OPENAI_API_KEY=[REDACTED]"
    assert validate_verdict(saved, ["basic"], root) == "pass"
    assert "private-fixture-value" not in (root / "report.md").read_text()


def test_report_keeps_markdown_quotes_inside_the_evidence_block(supervised_run, verdict, capsys):
    """Ordinary Markdown quoted as evidence must not create report headings."""
    root, _, _ = supervised_run
    quote = "Output\n```\n# Example heading\n````\n**Regression candidate** quoted example"
    (root / "evidence/output.txt").write_text(quote)
    verdict["scenarios"][0]["evidence"][0]["quote"] = quote
    verdict["regressions"] = [
        {
            "name": "guard",
            "bug": "escaping bug",
            "evidence": "Checked output.\n# Not a report heading",
        }
    ]
    assert supervise(root) == 0
    saved = json.loads((root / "verdict.json").read_text())
    assert saved["scenarios"][0]["evidence"][0]["quote"] == quote
    assert validate_verdict(saved, ["basic"], root) == "pass"
    report = (root / "report.md").read_text()
    assert "  `````text\n" + quote + "\n  `````" in report
    assert "\n# Not a report heading" not in report
    assert collect(root, 0) == 0
    assert capsys.readouterr().out == report


def test_supervisor_masks_labelled_credentials_in_saved_assessment(supervised_run, verdict):
    """The real tester's labelled credentials escaped both saved and displayed output."""
    root, _, _ = supervised_run
    verdict["regressions"] = [
        {
            "name": "guard",
            "bug": "escaping bug",
            "evidence": "GITHUB_TOKEN=token-fixture password: password-fixture",
        }
    ]
    assert supervise(root) == 0
    for name in ("verdict.json", "report.md"):
        text = (root / name).read_text()
        assert "token-fixture" not in text
        assert "password-fixture" not in text
    saved = json.loads((root / "verdict.json").read_text())
    assert validate_verdict(saved, ["basic"], root) == "pass"


def _break_identity(native: Path, defect: str) -> None:
    identity = json.loads(native.read_text())
    if identity.get("type") == "turn_context":
        identity["payload"][defect] = "other" if defect == "model" else "low"
    elif defect == "model":
        identity["message"]["model"] = "other"
    else:
        identity["effort"] = "low"
    native.write_text(json.dumps(identity) + "\n")


@pytest.mark.parametrize("defect", ["model", "effort", "subject", "crash", "live-group"])
def test_supervisor_blocks_unverified_identity_subject_or_process(
    supervised_run, monkeypatch, defect
):
    root, world, native = supervised_run
    if defect in {"model", "effort"}:
        _break_identity(native, defect)
    elif defect == "subject":
        monkeypatch.setattr(runs, "git", lambda *args: "changed")
    elif defect == "crash":
        world.returncode = 2
    else:
        world.group_alive = True
        monkeypatch.setattr(process, "group_members", lambda _: ["4242 leftover-helper"])
        monkeypatch.setattr(process.jobs, "stop_group", lambda _: None)
    assert supervise(root) == 1
    assert json.loads((root / "result.json").read_text())["status"] == "blocked"
    assert "Tester BLOCKED" in (root / "report.md").read_text()


def test_supervisor_delivers_exact_draft_command_and_still_rejects_changed_final(
    supervised_run, verdict
):
    """A successful precheck must not bypass final validation or invoke an older checkout script."""
    root, world, _ = supervised_run
    assert validate_verdict(verdict, ["basic"], root) == "pass"
    verdict["scenarios"][0]["evidence"][0]["quote"] = "changed after precheck"
    assert supervise(root) == 1
    command = world.prompt.split("Draft check command: ", 1)[1].split("\n", 1)[0]
    draft = str(root / "evidence/draft.json")
    expected = [sys.executable, str(runs.ENTRY), "tester", "validate", "--run", str(root)]
    assert shlex.split(command) == [*expected, "--draft", draft]
    assert "evidence quote is absent" in (root / "report.md").read_text()
