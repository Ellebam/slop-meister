"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from slopmeister.review.command import (
    build_review_command,
    cleanup_schema_file,
)
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.schema import (
    ReviewDirection,
    review_json_schema,
)
from tests.support.review_helpers import (
    CONFIG,
)


def _assert_finding_schema(schema):
    required = ["severity", "file", "line", "title", "rationale", "suggested_action", "confidence"]
    item = schema["properties"]["findings"]["items"]
    assert schema == json.loads(review_json_schema())
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["findings", "security_lens"]
    assert item["additionalProperties"] is False
    assert item["required"] == required
    assert set(item["properties"]) == set(required)
    assert item["properties"]["severity"] == {
        "enum": ["MUST-FIX", "NITPICK", "SHOULD-FIX"],
        "type": "string",
    }
    assert item["properties"]["confidence"] == {"enum": ["high", "low", "medium"], "type": "string"}
    assert item["properties"]["line"] == {"minimum": 1, "type": "integer"}


def test_claude_reviewer_can_run_commands_but_has_no_edit_tools():
    """Escaping bug: a read-only reviewer could not run `git diff` or the tests it judged."""
    argv = build_review_command(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt="Review this diff."),
    )
    tools = set(argv[argv.index("--tools") + 1].split(","))
    forbidden = {"Agent", "Edit", "MCP", "NotebookEdit", "WebFetch", "WebSearch", "Write", "all"}

    assert tools == {"Bash", "Read", "Grep", "Glob"}
    assert tools.isdisjoint(forbidden)
    assert argv[argv.index("--permission-mode") + 1] == "auto"


def test_codex_output_schema_uses_file_path_not_inline_json():
    target = ReviewTarget(prompt="Review this diff.")
    codex_argv = build_review_command(
        ReviewDirection.CLAUDE_TO_CODEX,
        target,
    )
    schema_arg = codex_argv[codex_argv.index("--output-schema") + 1]
    assert not schema_arg.lstrip().startswith("{")
    schema_path = Path(schema_arg)
    try:
        assert schema_path.is_file()
        assert stat.S_IMODE(schema_path.stat().st_mode) == 0o600
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    finally:
        schema_path.unlink(missing_ok=True)
    _assert_finding_schema(schema)


def test_codex_output_schema_file_is_unique():
    target = ReviewTarget(prompt="Review this diff.")
    first = build_review_command(
        ReviewDirection.CLAUDE_TO_CODEX,
        target,
    )
    second = build_review_command(
        ReviewDirection.CLAUDE_TO_CODEX,
        target,
    )
    first_path = Path(first[first.index("--output-schema") + 1])
    second_path = Path(second[second.index("--output-schema") + 1])
    try:
        assert first_path != second_path
        assert first_path.is_file()
        assert second_path.is_file()
        assert stat.S_IMODE(first_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(second_path.stat().st_mode) == 0o600
    finally:
        first_path.unlink(missing_ok=True)
        second_path.unlink(missing_ok=True)


def test_codex_reviewer_runs_without_plugins_or_notify():
    """Escaping bug: a plugin refresh and the notify program outlived the reviewer."""
    argv = build_review_command(
        ReviewDirection.CLAUDE_TO_CODEX, ReviewTarget(prompt="x"), config=CONFIG
    )
    Path(argv[argv.index("--output-schema") + 1]).unlink(missing_ok=True)
    assert argv[argv.index("--disable") + 1] == "plugins"
    assert "notify=[]" in argv


def test_codex_reviewer_disables_the_workspace_mcp_servers(tmp_path):
    """Escaping bug: a required write server refused the reviewer parent and ended the session."""
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text(
        '[mcp_servers.jira_write]\ncommand="adapter"\nrequired=true\n'
        '[mcp_servers."docs.prod"]\nurl="https://user:hunter2@example.invalid"\nrequired=true\n'
    )
    argv = build_review_command(
        ReviewDirection.CLAUDE_TO_CODEX, ReviewTarget("x", str(tmp_path)), config=CONFIG
    )
    Path(argv[argv.index("--output-schema") + 1]).unlink(missing_ok=True)
    override = argv.index(
        # A dotted name needs a quoted key, which Codex accepts only inside the value. Without a
        # transport Codex refuses a server it has not loaded from an untrusted workspace.
        'mcp_servers={"jira_write"={enabled=false,command="disabled"},'
        '"docs.prod"={enabled=false,url="disabled"}}'
    )
    assert argv[override - 1] == "--config"
    assert override < len(argv) - 1
    # Escaping bug: a transport copied into argv showed its credentials in the process list.
    assert "hunter2" not in " ".join(argv)


def test_build_command_uses_allowlisted_argv_and_tester_capabilities():
    target = ReviewTarget(prompt="Review this diff.")
    codex_argv = build_review_command(ReviewDirection.CLAUDE_TO_CODEX, target, config=CONFIG)
    claude_argv = build_review_command(ReviewDirection.CODEX_TO_CLAUDE, target, config=CONFIG)
    Path(codex_argv[codex_argv.index("--output-schema") + 1]).unlink(missing_ok=True)

    assert codex_argv[:3] == ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"]
    assert "--sandbox" not in codex_argv
    assert "-a" not in codex_argv
    assert "-m" not in codex_argv
    assert "-c" not in codex_argv
    assert "--ephemeral" in codex_argv
    assert codex_argv[codex_argv.index("--model") + 1] == "codex-model-x"
    assert codex_argv[codex_argv.index("--config") + 1] == "model_reasoning_effort='medium'"
    assert claude_argv[:2] == ["claude", "-p"]
    assert claude_argv[claude_argv.index("--permission-mode") + 1] == "auto"
    assert claude_argv[claude_argv.index("--model") + 1] == "claude-model-x"
    assert claude_argv[claude_argv.index("--effort") + 1] == "low"
    assert "Review this diff." not in claude_argv
    assert claude_argv[claude_argv.index("--tools") + 1] == "Bash,Read,Grep,Glob"
    # Escaping bug: the reviewed checkout's own hooks and settings run under the reviewer,
    # and both reviewers keep a transcript of field content under HOME.
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in claude_argv
    assert json.loads(claude_argv[claude_argv.index("--json-schema") + 1]) == json.loads(
        review_json_schema()
    )
    assert all(isinstance(part, str) for part in codex_argv + claude_argv)
    assert "shell" not in codex_argv + claude_argv


@pytest.mark.parametrize("direction", list(ReviewDirection))
def test_read_dirs_reach_only_claude_as_literal_arguments(tmp_path, direction):
    """Extra input paths must not become shell fragments or writable Codex roots."""
    directories = [tmp_path / "with spaces", tmp_path / "$(touch injected);*--tools=Bash"]
    for directory in directories:
        directory.mkdir()
    target = ReviewTarget(
        "Read named files.", str(tmp_path), read_dirs=tuple(str(p) for p in directories)
    )
    argv = build_review_command(direction, target, config=CONFIG)
    try:
        if direction == ReviewDirection.CODEX_TO_CLAUDE:
            assert argv.count("--add-dir") == 1
            values = argv[argv.index("--add-dir") + 1 :]
            assert values == [str(p.resolve()) for p in directories]
            assert argv[argv.index("--tools") + 1] == "Bash,Read,Grep,Glob"
            assert argv[argv.index("--permission-mode") + 1] == "auto"
            assert all(
                flag in argv
                for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence")
            )
        else:
            assert "--add-dir" not in argv
            assert "--dangerously-bypass-approvals-and-sandbox" in argv
    finally:
        cleanup_schema_file(argv)
