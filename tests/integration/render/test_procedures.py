"""Rendered procedures retain parity, headings, fill-ins, and spine contracts."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
PROCEDURES = (
    "bloom",
    "close-out",
    "cross-tool-review",
    "dummy",
    "finalize",
    "implement",
    "local-qa",
    "merge",
    "sow",
    "ripe",
    "prune",
    "ship",
    "execute-plan",
    "test-guide",
    "update-prs",
    "leak-check",
)
POINTS = {
    "local-qa": {
        "local-qa-drive": "How a change is driven here",
        "local-qa-gates": "Local gates here",
    },
    "test-guide": {"test-guide-access": "How a tester reaches the change"},
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
    assert "Never skip a required gate" in ripe
    assert "Do not edit, repeat a test or review" in ripe
    assert "invoke `ripe`" in (ROOT / "plots/code/plot.md").read_text()


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


def test_review_replace_is_outside_standing_allow_rules():
    claude = json.loads((ROOT / "plots/home/claude/settings.json.tmpl").read_text())
    allowed = claude["permissions"]["allow"]
    assert any("slopmeister review review *" in rule for rule in allowed)
    assert not any("review replace" in rule for rule in allowed)
    codex = (ROOT / "plots/home/codex/rules/default.rules").read_text()
    assert '"review", "review"], decision="allow"' in codex
    assert '"review", "replace"], decision="allow"' not in codex


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


def test_leak_check_is_required_only_where_we_do_not_own_the_project():
    """Escaping bug: the rule lands in inject and stops own projects, or a covered plot loses it."""
    for tool in ("claude", "codex"):
        required = {
            plot.stem
            for plot in (DIST / tool / "plots").glob("*.md")
            if "Invoke `leak-check` before anything leaves" in plot.read_text()
        }
        assert required == {"example-client"}, tool


def test_prune_preserves_mandatory_safety_and_the_changed_subject_bound():
    """Prune can otherwise drop mandatory safeguards or admit unrelated scoped-file repairs."""
    source = (ROOT / "src/skills/prune/SKILL.md").read_text()
    assert "it is a security, data-loss, authority or recovery matter" in source
    assert "failure of the change" in source
