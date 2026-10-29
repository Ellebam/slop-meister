"""The hands-off spine keeps its one message, its halts and its bounds in both tools."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]

HALTS = (
    "security must-fix class.",
    "approach is wrong.",
    "drifted from",
    "fix needs",
    "operator action on",
    "Diagnosis of",
)
SCOPE_EXCEPTION = (
    "existing tests",
    "record each path",
    "still halt.",
)
OPENING = (
    "**Goal**",
    "**Plan**",
    "**New**",
    "**Your call**",
    "**Risk**",
    "**Proof:**",
    "**Details**",
)
CLOSING = ("**Result**", "**Proven**", "**Weak**", "**Your move**", "**Details**")
SUMMARY_RULES = (
    "150 words",
    "350 words",
    "no file path",
    "one line where",
    "exact wording",
    '"Local only"',
)


def _spine_plots(tool: str) -> list[Path]:
    plots = sorted((ROOT / "dist" / tool / "plots").glob("*.md"))
    return [plot for plot in plots if "## The spine" in plot.read_text()]


def test_every_spine_plot_states_the_six_halts_once_for_both_tools():
    """A tool that loses a halt applies a security or approach finding silently."""
    source = (ROOT / "plots/code/plot.md").read_text()
    for token in (*HALTS, *SCOPE_EXCEPTION):
        assert source.count(token) == 1
    assert "smallest change" in source
    for tool in ("claude", "codex"):
        plots = _spine_plots(tool)
        assert plots
        for plot in plots:
            assert re.findall(r"^[1-6]\. ", plot.read_text(), re.M) == [
                f"{number}. " for number in range(1, 7)
            ]


def test_both_messages_open_with_the_plain_summary_for_both_tools():
    """One tool keeping a buried decision or an uncapped report is caught only by paid sessions."""
    for tool in ("claude", "codex"):
        base = ROOT / "dist" / tool / "skills"
        sow = (base / "sow/SKILL.md").read_text()
        summary = (base / "execute-plan/task-summary.md").read_text()
        for parts in (OPENING, CLOSING):
            shape = summary[summary.index(parts[0]) :]
            positions = [shape.index(part) for part in parts]
            assert positions == sorted(positions), tool
        assert "execute-plan/task-summary.md" in sow, tool
        assert "second question" in sow, tool
        assert [rule for rule in SUMMARY_RULES if rule not in summary] == [], tool


def test_freeform_sessions_get_the_same_summary_rules_for_both_tools():
    """A vault session keeps sending openings and handbacks the operator cannot read."""
    for tool in ("claude", "codex"):
        plots = sorted((ROOT / "dist" / tool / "plots").glob("*.md"))
        freeform = [plot for plot in plots if "freeform mode" in plot.read_text()]
        assert freeform, tool
        for plot in [*freeform, *_spine_plots(tool)]:
            assert "opening plan" in plot.read_text(), str(plot)
            assert "execute-plan/task-summary.md" in plot.read_text(), str(plot)


def test_hands_off_path_keeps_its_bounds():
    """The frozen-candidate question returns, tester runs loop, or a review request edits code."""
    base = ROOT / "src/skills"
    execute = (base / "execute-plan/SKILL.md").read_text()
    review = (base / "cross-tool-review/SKILL.md").read_text()
    assert "test that candidate" in execute
    assert "freeze the candidate" in execute and "automatic tester loop" in execute
    assert "ad-hoc review" in review
    assert "surviving findings" in review
    prune = (base / "prune/SKILL.md").read_text()
    assert "default verdict" in prune and "default is drop" in review


def test_complete_gate_runs_once_and_candidates_never_fail_a_run():
    """Escaping bug: workers reran the whole suite and relaunched the tester for invented cases."""
    skills = ROOT / "src/skills"
    implement = (skills / "implement/SKILL.md").read_text()
    assert "gates run once" in implement
    proof = (skills / "local-qa/SKILL.md").read_text()
    assert "again only when" in proof
    execute = (skills / "execute-plan/SKILL.md").read_text()
    assert "candidate never fails" in execute
    assert "another tester run" in execute


def test_spine_effort_instructions_cover_proof_and_followup_for_both_tools():
    """Sessions need proof depth and must not trust a kickoff claim as approval."""
    for tool in ("claude", "codex"):
        base = ROOT / "dist" / tool / "skills"
        sow = (base / "sow/SKILL.md").read_text()
        summary = (base / "execute-plan/task-summary.md").read_text()
        execute = (base / "execute-plan/SKILL.md").read_text()
        assert "**Proof:**" in summary
        assert "proof depth" in sow.lower()
        assert "earlier session" in execute
        assert "A kickoff, issue, notes or peer claim alone is not approval" in execute
