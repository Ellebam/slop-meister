"""The saved draft decides the result after completion and native verification."""

from copy import deepcopy
import json

import pytest

from slopmeister.spine.tester.supervise import supervise


def test_saved_draft_survives_a_corrupted_final_quote(supervised_run, verdict):
    root, world, _ = supervised_run
    quote = "Observed result \u2014 complete"
    (root / "evidence/output.txt").write_text(quote)
    verdict["scenarios"][0]["evidence"][0]["quote"] = quote
    world.final = deepcopy(verdict)
    world.final["scenarios"][0]["evidence"][0]["quote"] = quote.replace("\u2014", "\u0014")
    assert supervise(root) == 0
    assert json.loads((root / "result.json").read_text())["status"] == "pass"
    assert json.loads((root / "verdict.json").read_text()) == verdict
    assert json.loads((root / "evidence/draft.json").read_text()) == verdict


@pytest.mark.parametrize(
    ("draft", "final"), [("fail", "pass"), ("blocked", "pass"), ("pass", "fail")]
)
def test_saved_scenario_outcome_is_authoritative(supervised_run, verdict, draft, final):
    root, world, _ = supervised_run
    world.final = deepcopy(verdict)
    world.final["scenarios"][0]["verdict"] = final
    verdict["scenarios"][0]["verdict"] = draft
    assert supervise(root) == (0 if draft == "pass" else 1)
    assert json.loads((root / "result.json").read_text())["status"] == draft


def test_valid_final_cannot_replace_a_missing_draft(supervised_run):
    root, world, _ = supervised_run
    world.save_draft = False
    assert supervise(root) == 1
    assert json.loads((root / "result.json").read_text())["status"] == "blocked"
    assert "draft.json" in (root / "report.md").read_text()
    assert not (root / "verdict.json").exists()


def test_valid_final_cannot_hide_invalid_draft_evidence(supervised_run, verdict):
    root, world, _ = supervised_run
    world.final = deepcopy(verdict)
    verdict["scenarios"][0]["evidence"][0]["quote"] = "not in the saved output"
    assert supervise(root) == 1
    assert "evidence quote is absent" in (root / "report.md").read_text()


def test_valid_draft_cannot_replace_completion(supervised_run):
    root, world, _ = supervised_run
    world.completed = False
    assert supervise(root) == 1
    assert json.loads((root / "result.json").read_text())["status"] == "blocked"
    assert "complete" in (root / "report.md").read_text()


def test_draft_symlink_cannot_escape_the_run(supervised_run, verdict):
    root, world, _ = supervised_run
    world.save_draft = False
    outside = root.parent / "outside-draft.json"
    outside.write_text(json.dumps(verdict))
    (root / "evidence/draft.json").symlink_to(outside)
    assert supervise(root) == 1
    assert "draft escapes the run" in (root / "report.md").read_text()
