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
        plot.stem for plot in (root / "plots").glob("*.md") if "Use `groom`" in plot.read_text()
    }
    assert required == {"slopmeister", "example-app"}
    for name in required:
        assert "routine gaps" in (root / f"plots/{name}.md").read_text()


def test_groom_body_has_tool_parity():
    """Bug: one tool receives different document maintenance instructions."""
    bodies = [
        (ROOT / "dist" / tool / "skills/groom/SKILL.md").read_text().split("---\n", 2)[2]
        for tool in ("claude", "codex")
    ]
    assert bodies[0] == bodies[1]


def test_owned_document_classification_precedes_remote_writes_and_conflicts_stop():
    """Routine repair must not bypass the existing review gates or any remote write."""
    harvest = (ROOT / "src/skills/harvest/SKILL.md").read_text()
    documents = harvest.split("## 2. Documents and vault", 1)[1].split("## 3.", 1)[0]
    assert harvest.index("## 2. Documents and vault") < harvest.index("## 3. The branch")
    assert "planned document list" in documents
    assert "remote write" in documents
    assert "executed instruction" in documents
    assert "Routine gaps" in documents


def test_groom_keeps_conflicts_review_and_write_authority_separate():
    """A routine gap cannot erase a decision or authorize a protected write."""
    groom = (ROOT / "src/skills/groom/SKILL.md").read_text()
    for boundary in (
        "decision",
        "safety gate",
        "binding document",
        "two owners",
        "protected, dirty",
        "foreign note",
        "executed instruction",
        "remote write",
        "external-write authority",
    ):
        assert boundary in groom
    conflict, instruction = groom.split("A groom edit", 1)
    assert "conflicting edit" in conflict
    assert "existing review rules" in instruction


def test_harvest_grooms_every_plot_without_creating_unshipped_changes():
    """Harvest must finish routine vault work in every plot and keep repository delivery gates."""
    harvest = (ROOT / "src/skills/harvest/SKILL.md").read_text()
    assert "Run `groom`" in harvest
    assert "every plot" in harvest
    assert "stays protected" in harvest
    audit = (ROOT / "src/skills/vault-optimize/SKILL.md").read_text()
    invocation = audit.split("## Invocation", 1)[1].split("## Safety rules", 1)[0]
    assert "Harvest verifies groom maintenance in every plot" in invocation


def test_harvest_routes_vault_repairs_before_any_branch_route():
    """A no-diff or already-merged run must not skip eligible vault repairs."""
    harvest = (ROOT / "src/skills/harvest/SKILL.md").read_text()
    documents = harvest.split("## 2. Documents and vault", 1)[1].split("## 3.", 1)[0]
    assert "slopmeister-vault commit" in documents
    assert "Completed steps" in harvest
    assert "nothing ships" in documents


def test_owned_document_work_cannot_skip_planning_maintenance_or_review():
    """Bug: planned documents are omitted from scope, implementation or external review."""
    plan = (ROOT / "src/skills/sow/SKILL.md").read_text()
    assert "`## Scope`" in plan
    assert "one action" in plan
    implement = (ROOT / "src/skills/implement/SKILL.md").read_text()
    assert implement.index("planned document list") < implement.index("### 3. Verify")
    review = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert "missing affected documents" in review


def test_bug_reproduction_keeps_the_operator_intent_limit():
    """Bug: a session probes a live environment unasked while reproducing a ticket's failure."""
    sow = (ROOT / "src/skills/sow/SKILL.md").read_text()
    start = sow.find("reported failure")
    assert start >= 0, "sow has no bug-reproduction rule"
    rule = sow[start:].split("\n", 1)[0]
    assert "operator intent" in rule
