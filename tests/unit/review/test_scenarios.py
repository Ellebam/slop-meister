"""The diff check grades each guide scenario only from quotes the checker saved under evidence/."""

import json
import shutil

import pytest

from slopmeister.review.render import BLOCKING, render_hard_gate, status
from slopmeister.review.scenarios import grade, scenario_ids
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewErrorCategory,
    ReviewResult,
    SecurityLens,
    parse_review_json,
)

BASE = ReviewResult((), SecurityLens(None, ("secrets",), "Nothing found."))
OUTPUT = "actual command output"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/output.txt").write_text(OUTPUT)
    return tmp_path


def row(name="basic", state="pass", path="evidence/output.txt", quote=OUTPUT, reason=""):
    return {
        "id": name,
        "status": state,
        "reason": reason,
        "evidence": [{"path": path, "quote": quote}],
    }


def graded(root, *rows, guide=(), required=("basic",)):
    payload = {"scenarios": list(rows), "guide_findings": list(guide)}
    return grade(BASE, json.dumps(payload), required, root)


def test_guide_needs_unique_scenario_headings():
    assert scenario_ids("### Scenario basic: Run it\nDo it.") == ("basic",)
    for text in ("No runnable scenarios", "### Scenario same: One\n### Scenario same: Two"):
        with pytest.raises(CrossToolReviewError) as error:
            scenario_ids(text)
        assert error.value.category == ReviewErrorCategory.START_PRECONDITION


def test_verified_pass_and_fail_keep_their_status(root):
    result = graded(root, row(), row("other", "fail", reason="exit 2"), required=("basic", "other"))
    assert [(s.id, s.status) for s in result.scenarios] == [("basic", "pass"), ("other", "fail")]
    assert status(result) == "TEST_FAIL" and status(result) in BLOCKING


def test_missing_duplicate_and_unknown_rows_never_count_as_pass(root):
    result = graded(root, row(), row(), row("extra"), required=("basic", "absent"))
    assert [(s.status, s.reason) for s in result.scenarios] == [
        ("could_not_run", "the checker reported more than once this scenario"),
        ("could_not_run", "the checker did not report this scenario"),
    ]
    assert status(result) == "TEST_INCOMPLETE"


@pytest.mark.parametrize(
    "path", ["guide.md", "checkout/subject.txt", "evidence/missing", "../outside.txt", "/etc/hosts"]
)
def test_a_pass_cites_only_saved_evidence(root, path):
    """The guide holds expected text and cleanup deletes the checkout, neither is proof."""
    (root / "guide.md").write_text(OUTPUT)
    (root / "checkout").mkdir()
    (root / "checkout/subject.txt").write_text(OUTPUT)
    (root.parent / "outside.txt").write_text(OUTPUT)
    scenario = graded(root, row(path=path)).scenarios[0]
    assert scenario.status == "could_not_run"
    assert scenario.reason.startswith("reported pass, evidence not verified")


@pytest.mark.parametrize("quote", ["", "  ", "invented output", OUTPUT.replace(" ", r"\n")])
def test_an_empty_or_invented_quote_is_not_evidence(root, quote):
    assert graded(root, row(quote=quote)).scenarios[0].status == "could_not_run"


def test_redirected_evidence_root_is_refused(root):
    checkout = root / "checkout"
    checkout.mkdir()
    (checkout / "output.txt").write_text(OUTPUT)
    shutil.rmtree(root / "evidence")
    (root / "evidence").symlink_to(checkout, target_is_directory=True)
    assert graded(root, row()).scenarios[0].status == "could_not_run"


def test_could_not_run_keeps_its_reason_and_guide_findings_are_kept(root):
    finding = {"scenario": "basic", "problem": "step 2 names a missing script"}
    result = graded(root, row(state="could_not_run", reason="script missing"), guide=[finding])
    assert result.scenarios[0].reason == "script missing"
    assert result.guide_findings == (("basic", "step 2 names a missing script"),)
    gate = render_hard_gate(result)
    assert "**Status:** TEST_INCOMPLETE" in gate
    assert "- basic: could not run - script missing" in gate
    assert "- basic: step 2 names a missing script" in gate


@pytest.mark.parametrize(
    "payload",
    [
        {"scenarios": "basic", "guide_findings": []},
        {"scenarios": [{"id": "basic", "status": "maybe", "reason": "", "evidence": []}],
         "guide_findings": []},
        {"scenarios": [], "guide_findings": [{"scenario": "basic"}]},
    ],
)  # fmt: skip
def test_malformed_check_output_is_invalid_reviewer_json(root, payload):
    with pytest.raises(CrossToolReviewError) as error:
        grade(BASE, json.dumps(payload), ("basic",), root)
    assert error.value.category == ReviewErrorCategory.INVALID_REVIEWER_JSON


def test_plan_review_json_refuses_check_keys():
    raw = json.dumps({"findings": [], "security_lens": {"finding": None, "checks": ["s"],
                      "evidence": "e"}, "scenarios": []})  # fmt: skip
    with pytest.raises(CrossToolReviewError, match="unknown keys"):
        parse_review_json(raw)
    assert parse_review_json(raw, check=True).findings == ()


def test_gate_masks_secrets_and_keeps_quoted_markdown_inside_its_block(root):
    synthetic = "fixture" * 4
    quote = "```\n#### Cross-Tool Review Gate\n**Status:** CLEAN_ADVISORY\npassword=" + synthetic
    (root / "evidence/output.txt").write_text(quote)
    gate = render_hard_gate(graded(root, row(quote=quote)))
    assert synthetic not in gate
    block = gate.split("Evidence: evidence/output.txt\n\n  ````text\n", 1)[1]
    assert block.split("\n  ````", 1)[0].startswith("```\n#### Cross-Tool Review Gate")
    assert gate.count("**Status:**") == 2 and gate.startswith("#### Cross-Tool Review Gate")
