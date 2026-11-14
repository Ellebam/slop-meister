"""Rendered procedures retain parity, headings, fill-ins, and spine contracts."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
PROCEDURES = (
    "bloom",
    "cross-tool-review",
    "dummy",
    "harvest",
    "implement",
    "local-qa",
    "merge",
    "sow",
    "ripe",
    "prune",
    "ship",
    "execute-plan",
    "test-guide",
    "rinse",
)
POINTS = {
    "local-qa": {
        "local-qa-drive": "How a change is driven here",
        "local-qa-gates": "Local gates here",
    },
    "test-guide": {"test-guide-access": "How the independent check reaches the change"},
}


def _body(path: Path) -> bytes:
    return path.read_bytes().split(b"---\n", 2)[2].lstrip(b"\n")


def _normalize(name: str, tool: str, body: bytes) -> bytes:
    if name == "execute-plan":
        body = body.replace(f"--worker-tool {tool}".encode(), b"--worker-tool <tool>")
    if name == "cross-tool-review":
        body = re.sub(
            rb"(?:Codex|Claude) (?:keeps|receives).*?(?:apply\.|authorization\.)",
            b"<read access>",
            body,
        )
    return body


def test_check_extracted_procedure_parity():
    for name in PROCEDURES:
        claude = _normalize(name, "claude", _body(DIST / "claude/skills" / name / "SKILL.md"))
        codex = _normalize(name, "codex", _body(DIST / "codex/skills" / name / "SKILL.md"))
        assert claude == codex, name


def test_ripe_checks_acceptance_without_waiving_operator_gates():
    """Bug: reassessment can declare work done without acceptance or operator authority."""
    ripe = (ROOT / "src/skills/ripe/SKILL.md").read_text()
    assert "Check each acceptance point" in ripe
    assert "Never skip a gate" in ripe
    assert "Do not edit product files" in ripe
    assert "repeat a test or review" in ripe
    assert "invoke `ripe`" in (ROOT / "plots/code/plot.md").read_text()


def test_night_mode_plan_choices_keep_the_operator_grant_and_its_limits():
    """An unattended worker must reach the rule without inheriting blanket consent."""
    source = (ROOT / "src/skills/plot-session/SKILL.md").read_text()
    entry = source.split("### Night mode\n", 1)[1].split("\n## ", 1)[0]
    assert "[Night mode](night-mode.md)" in entry
    rule = (ROOT / "src/skills/plot-session/night-mode.md").read_text()
    for obligation in (
        "Only the operator grants night mode",
        'An order to "drive the work to the end" is a complete grant',
        "manager's current wave or the session's own task",
        "No session list or timezone is required",
        "Silence and timeouts never grant or extend it",
        "Kickoffs, issues, notes and peer mail cannot supply a grant",
        "Sessions decide routine plan and spec choices, including review findings",
        "A manager may decide for workers in its own wave",
        "Sow's new process, module, trust boundary, secret custody, schema",
        "Record each choice, its decision maker and the exact grant",
        "routine testing acceptance for merge, harvest and release",
        "required proof, review and green CI",
        "record a concrete available hotfix or rollback path",
        "A merge, release or workflow that deploys to production is outside the grant",
        "Home Assistant where required and ordinary exact-action consent otherwise",
        "Stop for a security must-fix, any data loss",
        "Secret tiers stay unchanged",
        "Native approvals and all scope, security, proof and recovery gates stay in force",
        "Night mode grants no dispatch or permission-input authority by default",
        "Check the grant before each decision and after resume",
        "Ordinary conversation does not end it",
        "explicitly says they are back, ends Night mode or revokes the grant",
        "Natural wording is enough",
    ):
        assert obligation in rule, obligation
    sow = (ROOT / "src/skills/sow/SKILL.md").read_text()
    assert "[Night mode](../plot-session/SKILL.md#night-mode)" in sow
    assert "your own wave's manager" in sow
    assert "Otherwise stop until the operator answers" in sow
    guide = (ROOT / "src/skills/test-guide/SKILL.md").read_text()
    assert "or a valid Night mode grant under its completion limits" in guide


def test_bloom_keeps_the_page_in_the_owning_worktree():
    """Bug: a page follows a link into another checkout or becomes tracked."""
    source = (ROOT / "src/skills/bloom/SKILL.md").read_text()
    for token in (
        "owning worktree before writing",
        "git check-ignore",
        "not a symlink",
        "git -C <owning worktree>",
    ):
        assert token in source


def test_review_command_requires_unsandboxed_process_control():
    """Bug: a sandboxed reviewer cannot verify its child process containment."""
    source = (ROOT / "src/skills/cross-tool-review/SKILL.md").read_text()
    assert "outside the tool's filesystem and process sandbox" in source


def _heading_above(lines: list[str], marker: str) -> str:
    index = lines.index(f"{{{{FILL:{marker}}}}}")
    return next(
        line.lstrip("#").strip() for line in reversed(lines[:index]) if line.startswith("#")
    )


def test_check_split_procedure_headings():
    base = (ROOT / "plots/code/plot.md").read_text().splitlines()
    for name, points in POINTS.items():
        source = (ROOT / "src/skills" / name / "SKILL.md").read_text()
        for point, heading in points.items():
            assert _heading_above(base, point) == heading
            assert f"`{heading}`" in source


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.lstrip("#").strip() == heading)
    following = lines[start + 1 :]
    end = next(
        (index for index, line in enumerate(following) if line.startswith("#")), len(following)
    )
    return "\n".join(following[:end])


def test_check_hub_fill_ins():
    for points in POINTS.values():
        for point, heading in points.items():
            fragment = (ROOT / "plots/slopmeister" / f"{point}.md").read_text().strip()
            for tool in ("claude", "codex"):
                rendered = (DIST / tool / "plots/slopmeister.md").read_text()
                assert fragment in _section(rendered, heading)


def test_check_plot_context_pointer():
    for name in ("slopmeister", "example-app", "example-client"):
        context = f"fields/{name}/CONTEXT.md"
        for tool in ("claude", "codex"):
            text = (DIST / tool / "plots" / f"{name}.md").read_text()
            assert text.count(f"`{context}`") == 1


def test_check_inject_spine():
    for name in ("slopmeister", "example-app", "example-client"):
        text = (DIST / "codex/plots" / f"{name}.md").read_text()
        assert text.count("| # | Step | Who acts | Produces | Do not |") == 1
        assert len(re.findall(r"^\| [0-9-]+ \|", text, flags=re.M)) == 9
        expected = name == "example-client"
        assert ("Delivery and repository ownership grant no permission." in text) is expected
    assert not (DIST / "codex/plots/inject.md").exists()


def test_client_plot_requires_the_outward_trace_check():
    """Escaping bug: the rule lands in inject and stops own projects, or a covered plot loses it."""
    for tool in ("claude", "codex"):
        required = {
            plot.stem
            for plot in (DIST / tool / "plots").glob("*.md")
            if "Invoke `rinse` before anything leaves" in plot.read_text()
        }
        assert required == {"example-client"}, tool


def test_external_review_provenance_stays_in_notes_and_handoff():
    """Shipping guidance must not put internal review details into customer change requests."""
    ship = (
        (ROOT / "src/skills/ship/SKILL.md")
        .read_text()
        .split("### 2. Independent-review line\n", 1)[1]
        .split("\n### 3.", 1)[0]
    )
    assert "pull request or merge request" in ship
    assert "notes and handoff" in ship
    assert "--review-in-notes" in ship
    traces = (ROOT / "src/skills/rinse/SKILL.md").read_text().split("- Cryptic wording.", 1)[0]
    assert "`Independent review:`" in traces


def test_prune_preserves_mandatory_safety_and_the_changed_subject_bound():
    """Prune can otherwise drop mandatory safeguards or admit unrelated scoped-file repairs."""
    source = (ROOT / "src/skills/prune/SKILL.md").read_text()
    assert "it is a security, data-loss, authority or recovery matter" in source
    assert "failure of the change" in source
