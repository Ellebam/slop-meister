"""The hands-off spine keeps its one message, its halts and its bounds in both tools."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

REMOVED_STOPS = (
    "dummy shape",
    "one question per message",
    "operator disposition",
    "findings disposition",
    "halt, not a go",
    "whether to test the frozen candidate",
    "direction discussion",
)
HALTS = (
    "1. A finding is in a security must-fix class.",
    "2. A finding says the approach is wrong.",
    "3. The plan or the diff has drifted from the ticket.",
    "4. A fix needs a file outside `## Scope` or changes an acceptance criterion.",
    "5. A second tester run fails, or the fix for the first failure would change the approach.",
    "6. Diagnosis of an error is exhausted.",
)
OPENING = ("**Goal**", "**Plan**", "**Your call**", "**Risk**", "**Details**")
CLOSING = ("**Result**", "**Proven**", "**Weak**", "**Your move**", "**Details**", "- Checks:")
SUMMARY_RULES = (
    "at most 150 words",
    "at most 350 words",
    "no file path, line number, command, command output, commit hash",
    "says in one line where",
    "keep their exact wording",
)


def _spine_plots(tool: str) -> list[Path]:
    plots = sorted((ROOT / "dist" / tool / "plots").glob("*.md"))
    return [plot for plot in plots if "## The spine" in plot.read_text()]


def test_no_rendered_instruction_keeps_a_removed_stop():
    """One leftover stop line makes a worker wait for an answer nobody owes."""
    for tool in ("claude", "codex"):
        for path in sorted((ROOT / "dist" / tool).rglob("*.md")):
            text = path.read_text().lower()
            assert [phrase for phrase in REMOVED_STOPS if phrase in text] == [], str(path)
        assert not (ROOT / "dist" / tool / "skills/frame").exists()
        assert not (ROOT / "dist" / tool / "skills/plan").exists()


def test_every_spine_plot_states_the_six_halts_once_for_both_tools():
    """A tool that loses a halt applies a security or approach finding silently."""
    assert _spine_plots("claude")
    for tool in ("claude", "codex"):
        for plot in _spine_plots(tool):
            text = plot.read_text()
            assert text.count("\n".join(HALTS)) == 1, str(plot)
            assert "opens with the smallest change that satisfies the ticket" in text, str(plot)


def test_both_messages_open_with_the_plain_summary_for_both_tools():
    """One tool keeping a buried decision or an uncapped report is caught only by paid sessions."""
    for tool in ("claude", "codex"):
        base = ROOT / "dist" / tool / "skills"
        sow = (base / "sow/SKILL.md").read_text()
        summary = (base / "execute-plan/task-summary.md").read_text()
        for text, parts in ((sow, OPENING), (summary, CLOSING)):
            shape = text[text.index(parts[0]) :]
            positions = [shape.index(part) for part in parts]
            assert positions == sorted(positions), tool
        assert "execute-plan/task-summary.md" in sow, tool
        assert "without a second question" in sow, tool
        assert [rule for rule in SUMMARY_RULES if rule not in summary] == [], tool


def test_freeform_sessions_get_the_same_summary_rules_for_both_tools():
    """A vault session keeps sending openings and handbacks the operator cannot read."""
    for tool in ("claude", "codex"):
        plots = sorted((ROOT / "dist" / tool / "plots").glob("*.md"))
        freeform = [plot for plot in plots if "Always work in freeform mode" in plot.read_text()]
        assert freeform, tool
        for plot in [*freeform, *_spine_plots(tool)]:
            assert "opening plan" in plot.read_text(), str(plot)
            assert "execute-plan/task-summary.md" in plot.read_text(), str(plot)


def test_hands_off_path_keeps_its_bounds():
    """The frozen-candidate question returns, tester runs loop, or a review request edits code."""
    for tool in ("claude", "codex"):
        base = ROOT / "dist" / tool / "skills"
        execute = (base / "execute-plan/SKILL.md").read_text()
        review = (base / "cross-tool-review/SKILL.md").read_text()
        assert "and test that candidate" in execute, tool
        assert "Ask the operator once" not in execute, tool
        assert (
            "commit it or freeze the candidate again" in execute
            and "A failed second run halts" in execute
        ), tool
        assert "An ad-hoc review presents its findings and stops" in review, tool
        assert "apply the surviving findings" in review, tool
        prune = (base / "prune/SKILL.md").read_text()
        assert "the default verdict is drop" in prune and "its default is drop" in review, tool


def test_complete_gate_runs_once_and_candidates_never_fail_a_run():
    """Escaping bug: workers reran the whole suite and relaunched the tester for invented cases."""
    for tool in ("claude", "codex"):
        skills = ROOT / "dist" / tool / "skills"
        implement = (skills / "implement/SKILL.md").read_text()
        assert "The complete suite and the local gates run once, in step 5" in implement, tool
        assert "run the whole suite" not in implement, tool
        proof = (skills / "local-qa/SKILL.md").read_text()
        assert "Run a gate again only when it failed" in proof, tool
        execute = (skills / "execute-plan/SKILL.md").read_text()
        assert "a candidate never fails a run" in execute, tool
        assert "none of this launches another tester run" in execute, tool
