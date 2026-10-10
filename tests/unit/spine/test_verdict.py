"""Tester verdict validation, native identity and report rendering without any process."""

import json
import shutil

import pytest

from slopmeister.review.run import project_child_env
from slopmeister.spine.tester.launch import build_command
from slopmeister.spine.tester.supervise import PROMPT
from slopmeister.spine.tester.validate import (
    native_identity,
    render_report,
    scenario_ids,
    validate_verdict,
)


def test_command_guide_cannot_omit_or_duplicate_scenarios():
    assert scenario_ids("### Scenario basic: Run command\nDo it.") == ["basic"]
    for text in ("No runnable scenarios", "### Scenario same: One\n### Scenario same: Two"):
        with pytest.raises(ValueError):
            scenario_ids(text)


@pytest.mark.parametrize("quote", ["actual command output", "secret_" + "a" * 20])
def test_tester_refuses_malformed_verdicts_then_accepts_valid_evidence(tmp_path, verdict, quote):
    """Malformed input must fail equally before and after redaction would change its text."""
    (tmp_path / "evidence/output.txt").write_text(quote)
    verdict["scenarios"][0]["evidence"][0]["quote"] = quote
    scenario = verdict["scenarios"][0]
    for broken in (
        {},
        {**verdict, "scenarios": []},
        {**verdict, "scenarios": verdict["scenarios"] * 2},
        {**verdict, "scenarios": [{**scenario, "verdict": "maybe"}]},
    ):
        with pytest.raises(ValueError):
            validate_verdict(broken, ["basic"], tmp_path)
        assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"


def _bad_citations(tmp_path, quote):
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text(quote)
    (tmp_path / "evidence/linked.txt").symlink_to(outside)
    paths = ("../" + outside.name, str(outside), "evidence/linked.txt", "evidence/missing")
    bad = [{"path": path, "quote": quote} for path in paths]
    quotes = ("", " ", quote.replace("a", "b"), quote.replace("\n", r"\n"))
    bad += [{"path": "evidence/output.txt", "quote": value} for value in quotes]
    return [*bad, {"path": "evidence/output.txt"}]


@pytest.mark.parametrize(
    "quote", ["actual command output\nsecond line", "secret_" + "a" * 20 + "\nsecond line"]
)
def test_tester_refuses_invalid_evidence_then_accepts_valid_quote(tmp_path, verdict, quote):
    """Missing, escaped or invented evidence must never inherit validity from masking."""
    (tmp_path / "evidence/output.txt").write_text(quote)
    item = verdict["scenarios"][0]["evidence"][0]
    valid = {"path": "evidence/output.txt", "quote": quote}
    for broken in _bad_citations(tmp_path, quote):
        item.clear()
        item.update(broken)
        with pytest.raises(ValueError):
            validate_verdict(verdict, ["basic"], tmp_path)
        item.clear()
        item.update(valid)
        assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"


def test_tester_preserves_fail_and_blocked_without_regrading(tmp_path, verdict):
    for status in ("fail", "blocked"):
        verdict["scenarios"][0]["verdict"] = status
        assert validate_verdict(verdict, ["basic"], tmp_path) == status
        assert status in render_report(verdict)


def test_tester_added_failure_does_not_fail_the_run(tmp_path, verdict):
    """Escaping bug: a counterexample the tester invented failed the run and forced a relaunch."""
    invented = dict(verdict["scenarios"][0], id="invented-counterexample", verdict="fail")
    verdict["scenarios"].append(invented)
    assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"
    verdict["scenarios"][0]["verdict"] = "blocked"
    assert validate_verdict(verdict, ["basic"], tmp_path) == "blocked"
    with pytest.raises(ValueError, match="no required scenario"):
        validate_verdict(verdict, [], tmp_path)


def test_report_marks_a_tester_added_row_as_not_counted(verdict):
    """Escaping bug: a passed run showed a bare fail line and the worker relaunched anyway."""
    invented = dict(verdict["scenarios"][0], id="invented", verdict="fail")
    verdict["scenarios"].append(invented)
    report = render_report(verdict, ["basic"])
    assert "- basic: pass\n" in report
    assert "- invented: fail, added by the tester, not counted\n" in report


def test_tester_returns_counterexamples_as_candidates():
    """Escaping bug: the tester failed a guide scenario for a case the guide never named."""
    assert "Add no scenario of your own" in PROMPT
    assert "its written steps and expected results alone" in PROMPT
    assert "as a regression candidate" in PROMPT


@pytest.mark.parametrize("kind", ["relative", "absolute", "symlink"])
def test_report_cannot_cite_checkout_files_that_cleanup_will_delete(tmp_path, verdict, kind):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subject = checkout / "subject.txt"
    subject.write_text("actual command output")
    linked = tmp_path / "evidence/linked.txt"
    linked.symlink_to(subject)
    paths = {
        "relative": "checkout/subject.txt",
        "absolute": str(subject),
        "symlink": "evidence/linked.txt",
    }
    item = verdict["scenarios"][0]["evidence"][0]
    item["path"] = paths[kind]
    with pytest.raises(ValueError, match="copy the quoted file into evidence/"):
        validate_verdict(verdict, ["basic"], tmp_path)
    item["path"] = "evidence/output.txt"
    assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"


def test_checkout_symlink_does_not_reject_retained_report_evidence(tmp_path, verdict):
    """Deletion refuses a replaced root, so its target must not become the citation boundary."""
    evidence = tmp_path / "evidence"
    (evidence / "output.txt").write_text("actual command output")
    (tmp_path / "checkout").symlink_to(evidence, target_is_directory=True)
    verdict["scenarios"][0]["evidence"][0]["path"] = "evidence/output.txt"
    assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"


@pytest.mark.parametrize(
    "name", ["guide.md", "validation.md", "events.jsonl", "run.json", "evidence/draft.json"]
)
def test_pass_cannot_cite_worker_inputs_run_records_or_its_own_draft(tmp_path, verdict, name):
    """A quote of the expected text or of the tester's own claim is not command output."""
    (tmp_path / name).write_text("actual command output")
    item = verdict["scenarios"][0]["evidence"][0]
    item["path"] = name
    with pytest.raises(ValueError, match="under evidence/"):
        validate_verdict(verdict, ["basic"], tmp_path)
    item["path"] = "evidence/output.txt"
    assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"


def test_redirected_evidence_root_is_refused(tmp_path, verdict):
    """A linked evidence folder would admit checkout files that cleanup deletes."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "output.txt").write_text("actual command output")
    shutil.rmtree(tmp_path / "evidence")
    (tmp_path / "evidence").symlink_to(checkout, target_is_directory=True)
    with pytest.raises(ValueError, match="under evidence/"):
        validate_verdict(verdict, ["basic"], tmp_path)


def test_tester_verdict_needs_no_security_lens(tmp_path, verdict):
    """Escaping bug: a correct tester run blocks on a Security Lens the worker and reviewer own."""
    verdict.pop("security_lens", None)
    assert validate_verdict(verdict, ["basic"], tmp_path) == "pass"
    assert "Security Lens" not in render_report(verdict)


def test_tester_sets_up_missing_tools_and_changes_no_code():
    """Escaping bug: testers blocked on a missing `.venv` their clean copy never had."""
    assert "run the development setup its README or CONTRIBUTING names" in PROMPT
    assert "never change the subject's code or files" in PROMPT
    assert "Security Lens" not in PROMPT


def test_tester_rejects_missing_or_mismatched_native_model(tmp_path):
    native = tmp_path / "native.jsonl"
    record = {"type": "turn_context", "payload": {"model": "observed", "effort": "high"}}
    native.write_text(json.dumps(record) + "\n")
    assert native_identity(native, "codex") == ("observed", "high")
    native.write_text('{"type":"turn_context","payload":{"model":"observed"}}\n')
    with pytest.raises(ValueError):
        native_identity(native, "codex")


def test_tester_filters_environment_and_redacts_report_without_regrading(verdict):
    verdict["regressions"] = [
        {
            "name": "guard",
            "bug": "escaping bug",
            "evidence": "sk-secret123456789012345678901234567890",
        }
    ]
    assert "sk-secret" not in render_report(verdict)
    assert "pass" in render_report(verdict)
    assert "OPENAI_API_KEY" not in project_child_env({"PATH": "/bin", "OPENAI_API_KEY": "private"})


def test_tester_runs_other_tool_at_exact_commit(tmp_path):
    run = {"tool": "codex", "model": "selected", "effort": "high", "checkout": str(tmp_path)}
    command = build_command(run, tmp_path)
    assert command[:3] == ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"]
    assert command[command.index("-C") + 1] == str(tmp_path)
    # Escaping bug: a plugin refresh and the notify program outlived the tester, every run blocked.
    assert command[command.index("--disable") + 1] == "plugins"
    assert "notify=[]" in command
    run["tool"] = "claude"
    command = build_command(run, tmp_path)
    assert command[0] == "claude"
    assert "--no-session-persistence" not in command


def test_report_single_line_fields_cannot_inject_new_blocks(verdict):
    """Newlines in labels and assessments must not escape into report structure."""
    text = "label\n# Forged heading\n| row |"
    verdict["scenarios"][0]["id"] = text
    verdict["scenarios"][0]["evidence"][0]["path"] = text
    verdict["regressions"] = [{"name": text, "bug": text, "evidence": text}]
    report = render_report(verdict)
    assert "\n# Forged heading" not in report
    assert "\n| row |" not in report
    assert report.count(r"\| row \|") == 5
