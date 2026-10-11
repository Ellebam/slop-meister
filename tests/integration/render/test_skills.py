"""Skill rendering preserves shared bytes and isolates tool-specific blocks."""

from pathlib import Path

import pytest

from tests.integration.render.helpers import ROOT, run_render, scaffold
from tests.support.trees import write


def test_check_skill_tool_blocks(tmp_path):
    root = scaffold(tmp_path, "skill-fixtures")
    result = run_render(root)
    assert result.returncode == 0, result.stderr
    claude = (root / "dist/claude/skills/blocky/SKILL.md").read_text()
    codex = (root / "dist/codex/skills/blocky/SKILL.md").read_text()
    assert "Claude-only line." in claude and "Claude-only line." not in codex
    assert "Codex-only line." in codex and "Codex-only line." not in claude
    assert "{{" not in claude + codex
    plain = root / "src/skills/plain/SKILL.md"
    assert (root / "dist/claude/skills/plain/SKILL.md").read_bytes() == plain.read_bytes()
    policy = (root / "dist/codex/skills/gated/agents/openai.yaml").read_text()
    assert "allow_implicit_invocation: false" in policy


BLOCK_CASES = (
    ("unclosed", "{{TOOL:claude}}\norphan\n", "never closed"),
    ("nested", "{{TOOL:claude}}\n{{TOOL:codex}}\nline\n{{/TOOL}}\n{{/TOOL}}\n", "do not nest"),
    ("orphan", "{{/TOOL}}\n", "without an open block"),
    ("token", "{{WAT}}\n", "unsanctioned"),
    ("selector", "{{TOOL:gemini}}\nline\n{{/TOOL}}\n", "unsanctioned"),
    ("inline", "around {{TOOL:claude}} marker\n", "unsanctioned"),
)


@pytest.mark.parametrize("label,body,expected", BLOCK_CASES, ids=[case[0] for case in BLOCK_CASES])
def test_check_skill_block_failure_modes(tmp_path, label, body, expected):
    root = scaffold(tmp_path, "skill-fixtures")
    source = "---\nname: plain\ndescription: fixture\n---\n\n" + body
    write(root, "src/skills/plain/SKILL.md", source)
    result = run_render(root)
    assert result.returncode != 0, label
    assert expected in result.stderr and "plain" in result.stderr


def test_skill_frontmatter_marker_is_refused(tmp_path):
    root = scaffold(tmp_path, "skill-fixtures")
    source = "---\nname: plain\ndescription: d\n{{TOOL:claude}}\n---\n\nline\n"
    write(root, "src/skills/plain/SKILL.md", source)
    result = run_render(root)
    assert result.returncode != 0 and "frontmatter" in result.stderr


def _body(path: Path) -> bytes:
    parts = path.read_bytes().split(b"---\n", 2)
    assert len(parts) == 3
    return parts[2].lstrip(b"\n")


def test_finalize_names_safe_non_slot_removal_for_both_tools():
    """Bug: finalize silently returned to plain Git and left locked delivery on disk."""
    for tool in ("claude", "codex"):
        text = (ROOT / f"dist/{tool}/skills/finalize/SKILL.md").read_text()
        assert "workspace-remove <absolute-worktree>" in text
        assert "same `workspace-remove` command with `--self`" in text
        assert "Remove the worktree if this session ran in one" not in text
        assert "cleanup as pending" in text and "local branch as retained" in text


def test_target_tree_holds_exactly_the_folders_the_target_declares():
    """A target renders only what it varies. Without this the tree regrows the duplicate copies
    the manifest used to force, 13 of which were byte-identical to the shared render."""
    declared = {
        path.name for path in (ROOT / "plots/example-app/skills").iterdir() if path.is_dir()
    }
    for tool in ("claude", "codex"):
        root = ROOT / "dist" / tool / "targets/example-app/skills"
        assert {path.name for path in root.iterdir() if path.is_dir()} == declared


@pytest.fixture
def patched_tree(tmp_path):
    root = scaffold(tmp_path, "skill-fixtures")
    write(root, "plots/base/plot.md", "# Fixture\n\nRead details.md when checking the result.\n")
    write(
        root,
        "plots/probe/plot.toml",
        '[plot]\nbase="base"\n[target]\ntasks="manual"\n'
        '[target.repository]\ncommit="deny"\n[slots]\nnone=true\n',
    )
    write(root, "plots/probe/skills/gated/claude.frontmatter.yaml", "allowed-tools: Read\n")
    write(root, "plots/probe/skills/plain/details.md", "Fixture payload.\n")
    result = run_render(root)
    assert result.returncode == 0, result.stderr
    return root


def test_a_folder_without_skill_md_patches_the_shared_skill(patched_tree):
    """A metadata or payload overlay must retain the body of its shared skill."""
    root = patched_tree
    patched = root / "dist/claude/targets/probe/skills/gated/SKILL.md"
    assert _body(patched) == _body(root / "dist/claude/skills/gated/SKILL.md")
    assert "allowed-tools:" in patched.read_text().split("---")[1]
    for tool in ("claude", "codex"):
        payload = root / f"dist/{tool}/targets/probe/skills/plain"
        assert _body(payload / "SKILL.md") == _body(root / f"dist/{tool}/skills/plain/SKILL.md")
        assert (payload / "details.md").read_text() == "Fixture payload.\n"


def test_example_app_uses_the_shared_slot_skill_without_a_target_shadow():
    """Bug: the old target-local allocator shadowed the supported generic slot procedure."""
    for tool in ("claude", "codex"):
        assert not (ROOT / f"dist/{tool}/targets/example-app/skills/slot").exists()
        shared = ROOT / f"dist/{tool}/skills/slot/SKILL.md"
        assert _body(shared) == _body(ROOT / "src/skills/slot/SKILL.md")


def test_a_target_patch_never_reaches_the_shared_render(patched_tree):
    """A plot's extra permission must not reach any other plot or the other tool."""
    for path in (
        "dist/claude/skills/gated/SKILL.md",
        "dist/codex/targets/probe/skills/gated/SKILL.md",
        "src/skills/gated/SKILL.md",
    ):
        assert "allowed-tools:" not in (patched_tree / path).read_text()
    assert not (patched_tree / "dist/claude/skills/plain/details.md").exists()


def test_a_skill_without_a_metadata_file_renders(tmp_path):
    """skill.meta.yaml carries only optional Codex interface keys now. Keeping it mandatory would
    force 23 files whose entire content was a key the renderer no longer reads."""
    root = scaffold(tmp_path, "skill-fixtures")
    assert not (root / "src/skills/plain/skill.meta.yaml").exists()
    result = run_render(root)
    assert result.returncode == 0, result.stderr
    assert (root / "dist/claude/skills/plain/SKILL.md").is_file()
    assert (root / "dist/codex/skills/plain/SKILL.md").read_text().startswith("---\nname: plain\n")
