"""Document maintenance reaches both tools without changing other plots' duties."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("tool", ("claude", "codex"))
def test_groom_is_discoverable_and_required_only_by_owned_plots(tool):
    root = ROOT / "dist" / tool
    skill = root / "skills/groom/SKILL.md"
    assert skill.is_file(), "groom is missing from delivery"
    text = skill.read_text()
    assert "disable-model-invocation: true" not in text
    if tool == "codex":
        policy = skill.parent / "agents/openai.yaml"
        if policy.exists():
            assert "allow_implicit_invocation: false" not in policy.read_text()
    required = {
        plot.stem
        for plot in (root / "plots").glob("*.md")
        if "Use `groom` for affected repository documentation and vault knowledge."
        in plot.read_text()
    }
    assert required == {"slopmeister", "example-app"}


def test_groom_body_has_tool_parity():
    """Bug: one tool receives different document maintenance instructions."""
    bodies = [
        (ROOT / "dist" / tool / "skills/groom/SKILL.md").read_text().split("---\n", 2)[2]
        for tool in ("claude", "codex")
    ]
    assert bodies[0] == bodies[1]


def test_owned_document_refusal_precedes_remote_checks_and_never_repairs():
    """Bug: finalize writes remotely or repairs documentation after review."""
    finalize = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    assert finalize.index("check the planned document list") < finalize.index("Read the PR body's")
    assert "Stop without document edits" in finalize
    close = (ROOT / "src/skills/close-out/SKILL.md").read_text()
    assert "verify the affected document list" in close
    assert "Only plots that do not require `groom`" in close


def test_owned_document_work_cannot_skip_planning_maintenance_or_review():
    """Bug: planned documents are omitted from scope, implementation or external review."""
    plan = (ROOT / "src/skills/sow/SKILL.md").read_text()
    assert "Include their paths in `## Scope`" in plan
    assert "list each document with one action" in plan
    implement = (ROOT / "src/skills/implement/SKILL.md").read_text()
    assert implement.index("invoke it for the planned document list") < implement.index(
        "### 3. Verify"
    )
    review = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert "Both plan and diff review check missing affected documents" in review
