"""The rendered execute-plan path and its guide and review procedures."""

from pathlib import Path
import re

import pytest

from tests.integration.spine import adapters

ROOT = Path(__file__).resolve().parents[3]
SUMMARY = ROOT / "src/skills/execute-plan/task-summary.md"
SUMMARY_CALLERS = ("ship", "test-guide", "execute-plan", "finalize", "close-out")
STAGES = [
    "1. Run `implement`",
    "2. Run `local-qa`",
    "3. Run `test-guide`",
    "4. Promote",
    "5. Run `ship`",
    "6. Run the existing",
]


def _frontmatter(path: Path) -> str:
    return path.read_text().split("---", 2)[1]


def _assert_operator_gates(skills: Path, tool: str) -> None:
    for name in ("merge", "finalize", "close-out"):
        gate = skills / name / ("SKILL.md" if tool == "claude" else "agents/openai.yaml")
        expected = (
            "disable-model-invocation: true"
            if tool == "claude"
            else "allow_implicit_invocation: false"
        )
        assert expected in gate.read_text()


def _rendered_chain(tool: str) -> None:
    skills = ROOT / "dist" / tool / "skills"
    procedure = (skills / "execute-plan/SKILL.md").read_text()
    if tool == "claude":
        assert "disable-model-invocation: true" not in procedure.split("---", 2)[1]
    else:
        assert not (skills / "execute-plan/agents/openai.yaml").exists()
    review = _frontmatter(skills / "cross-tool-review/SKILL.md")
    assert "disable-model-invocation: true" not in review
    _assert_operator_gates(skills, tool)
    positions = [procedure.index(stage) for stage in STAGES]
    assert positions == sorted(positions)


def test_rendered_chain_preserves_decision_gates_and_selected_order():
    for tool in ("claude", "codex"):
        _rendered_chain(tool)


def _assert_payload(payload: dict, tool: str, directory: str) -> None:
    prefix = f"{directory}/skills/execute-plan/"
    text = payload[prefix + "SKILL.md"][0].decode()
    if tool == "claude":
        assert "disable-model-invocation: true" not in text.split("---", 2)[1]
    else:
        assert "name: execute-plan" in text.split("---", 2)[1]
        assert prefix + "agents/openai.yaml" not in payload
    assert payload[prefix + "task-summary.md"][0] == SUMMARY.read_bytes()


@pytest.mark.parametrize("target", ("slopmeister", "example-app"))
def test_execute_plan_reaches_launcher_payload_and_summary(target):
    """A source-only rename can silently drop discovery through either delivery manifest."""
    payload = adapters.installer_payload(target)
    for tool, directory in (("claude", ".claude"), ("codex", ".agents")):
        _assert_payload(payload, tool, directory)


def test_summary_reaches_every_handoff_without_tool_drift():
    """A missing caller reference or one-tool change silently revives competing handoffs."""
    expected = SUMMARY.read_bytes()
    for tool in ("claude", "codex"):
        base = ROOT / "dist" / tool / "skills"
        summary = base / "execute-plan/task-summary.md"
        assert summary.read_bytes() == expected
        for name in SUMMARY_CALLERS:
            caller = base / name / "SKILL.md"
            _assert_caller_links(caller, summary)
            # A target renders only what it varies, so its tree is an overlay rather than a
            # delivery layout and the relative link resolves only once the installer puts every
            # skill side by side. Compare the link text instead of following it.
            varied = ROOT / "dist" / tool / "targets/example-app/skills" / name / "SKILL.md"
            if varied.exists():
                assert _summary_links(varied) == _summary_links(caller), str(varied)
        for plot in (ROOT / "dist" / tool / "plots").glob("*.md"):
            text = plot.read_text()
            if "## The spine" in text:
                assert "execute-plan/task-summary.md" in text, str(plot)


def test_close_out_preserves_an_interrupted_first_touch_record_without_committing_it():
    """Bug: a pre-write ownership record becomes unparseable or authorizes a commit."""
    text = (ROOT / "src/skills/close-out/SKILL.md").read_text()
    assert "first-touch <state>" in text
    assert "never commit it" in text


def test_review_replays_final_result_and_has_explicit_operator_replacement():
    """Bug: a changed prompt silently buys another completed review."""
    review = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert "launcher-confirmed task identity" in review
    assert "review replace --mode <plan|diff>" in review
    assert "outside the standing review allow rule" in review


def _summary_links(caller: Path) -> list[str]:
    return re.findall(r"\[[^]]+\]\(([^)]+task-summary\.md)\)", caller.read_text())


def _assert_caller_links(caller: Path, summary: Path) -> None:
    links = _summary_links(caller)
    assert len(links) == (2 if caller.parent.name == "close-out" else 1), str(caller)
    assert all((caller.parent / link).resolve() == summary.resolve() for link in links)


def test_command_guide_has_runnable_scenarios():
    """Bug: a command change gets a guide that the tester cannot run or parse."""
    source = (ROOT / "src/skills/test-guide/SKILL.md").read_text()
    assert "### Scenario <id>: <title>" in source
    assert "commands with expected output" in source


def test_interrupted_review_instructions_stop_without_reinvocation():
    """Bug: an uncertain live reviewer is reinvoked and spends the review twice."""
    source = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert "never reinvoke while the original call may be live" in source


def test_commit_and_shipping_permissions_select_continuations_without_blocking_review():
    """Bug: commit-deny testing changes authority or review consumes an untested candidate."""
    execute = (ROOT / "src/skills/execute-plan/SKILL.md").read_text()
    review = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert '`commit = "allow"`' in execute and '`commit = "deny"`' in execute
    assert "--candidate" in execute and "--candidate" in review
    assert "Shipping: N/A, denied by plot" in execute
    assert "freeze the final candidate and test it" in execute
    assert "reviewer and final tester consume the same tree" in execute


def test_guide_cleanup_preserves_changed_files_for_any_subject():
    """Bug: guide cleanup deletes a file modified by the subject or an unrecorded file."""
    source = (ROOT / "src/skills/test-guide/SKILL.md").read_text()
    assert "bytes still match what the test wrote" in source
    assert "preserve changed or unrecorded files" in source


def test_branch_binary_rule_precedes_the_copyable_tester_command():
    """Bug: copying the main checkout's command tests old code."""
    source = (ROOT / "src/skills/execute-plan/SKILL.md").read_text()
    assert source.index("contains `bin/slopmeister`, use that binary") < source.index(
        "tester launch"
    )


def test_promotion_prunes_candidates_before_adding_tests():
    """Bug: a speculative tester candidate becomes a permanent regression test."""
    source = (ROOT / "src/skills/execute-plan/SKILL.md").read_text()
    step = source[source.index("4. Promote") : source.index("5. Run `ship`")]
    assert "Invoke `prune` on the candidates first" in step


def test_close_out_continues_a_read_only_session_and_keeps_the_write_stops():
    """Bug: an unrecorded vault write passes, or a read-only session cannot recover its ledger."""
    source = (ROOT / "src/skills/close-out/SKILL.md").read_text()
    assert "builds those lines from its own read history" in source
    assert "created or edited that has no first-touch record" in source
    assert "earlier read history is not available" in source
