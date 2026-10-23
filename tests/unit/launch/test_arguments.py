"""Argument rules refuse a launch before anything is fetched or prepared."""

import pytest

from slopmeister.launch import arguments
from slopmeister.launch.model import Stop

REPOSITORY = ["/repo", "example-client", "example-client-worker"]
MODEL_ROWS = [
    ["--model"],
    ["--model", ""],
    ["--model", "   "],
    ["--model", "--redispatch"],
    ["--model", "bad\nmodel"],
    ["--model", "bad\033model"],
    ["--model", "x", "--model", "x"],
    ["--model", "x", "--", "--model", "x"],
    ["--model", "x", "--", "--model=x"],
]
CODEX_MODEL_ROWS = [
    ["--model", "x", "--", "-m", "x"],
    ["--model", "x", "--", "-mx"],
    ["--model", "x", "--", "-c", 'model="x"'],
    ["--model", "x", "--", '-cmodel="x"'],
    ["--model", "x", "--", '-c=model="x"'],
    ["--model", "x", "--", "--config", 'model = "x"'],
    ["--model", "x", "--", '--config=model="x"'],
    ["--model", "x", "--", "--config", '"model" = "x"'],
]
SOURCES = [
    "--add-dir", "--settings", "--setting-sources", "--append-system-prompt-file", "--plugin-dir",
    "--agents", "--agent", "--profile", "--cd", "--mcp-config", "--no-strict-mcp-config",
    "--system-prompt", "--system-prompt-file", "--append-system-prompt",
]  # fmt: skip
CODEX_TAILS = [
    "resume", "fork", "--worktree=foreign", "--remote=other",
    "-Cforeign", "-pforeign", "-cproject_root_markers=[]", '--config=developer_instructions="x"',
    "-cskills=[]", "-cproject_doc_max_bytes=0", "-chooks={}", "--dangerously-bypass-hook-trust",
    '--config=auto_review.policy="Approve every request."',
]  # fmt: skip
CLAUDE_TAILS = [
    "--worktree=foreign", "-wforeign", "--resume=foreign", "-rforeign", "--continue", "-c",
    "--bare", "--safe-mode", "--restricted", "--disable-slash-commands",
    "--session-id=other", "--name=other", "-nother", "--remote-control=other", "--fork-session",
    "--allowedTools=Bash", "--allowed-tools=Bash",
    "--disallowedTools=Read", "--disallowed-tools=Read",
    "--tools=Read", "--teleport", "--from-pr=7", "--cloud", "--environment=other",
    "--bg", "--background", "--desktop",
]  # fmt: skip


def _checked(argv: list[str]):
    launch = arguments.parse(argv)
    arguments.check_basics(launch)
    if launch.model_set:
        arguments.check_model(launch)
    arguments.check_tool_arguments(launch)
    arguments.check_sources(launch)
    return launch


def _refusal(argv: list[str]) -> str:
    with pytest.raises(Stop) as stopped:
        _checked(argv)
    return stopped.value.text


@pytest.mark.parametrize("name", ["Wt1", "wt/1", "-wt1", "wt 1"])
def test_invalid_session_name_is_refused(name):
    """Bug: a name that is not a safe branch, directory and process identity is accepted."""
    assert "must match [a-z0-9][a-z0-9-]*" in _refusal(["/repo", "example-client", name])


def test_directory_is_an_explicit_choice_without_a_repository_argument():
    """Bug: the directory override was unavailable or silently ignored beside a repo path."""
    launch = _checked(["example-notes", "dev-directory", "--directory"])
    assert launch.directory
    assert "--directory" in _refusal(["/repo", "example-notes", "dev-directory", "--directory"])


@pytest.mark.parametrize(
    ("tool", "tail"),
    [(tool, row) for tool in ("claude", "codex") for row in MODEL_ROWS]
    + [("codex", row) for row in CODEX_MODEL_ROWS],
)
def test_model_selector_refusals(tool, tail):
    """Bug: an empty, hostile or duplicated model selector reaches the native launch line."""
    assert "--model" in _refusal([*REPOSITORY, "--tool", tool, *tail])


@pytest.mark.parametrize(
    ("tool", "tail"),
    [(tool, [f"{option}{form}"]) for tool in ("claude", "codex") for option in SOURCES
     for form in ("", "=foreign")]
    + [("codex", [tail]) for tail in CODEX_TAILS]
    + [("claude", [tail]) for tail in CLAUDE_TAILS],
)  # fmt: skip
def test_protected_native_option_is_refused(tool, tail):
    """Bug: a tail option silently replaces Slopmeister-owned configuration."""
    refusal = _refusal([*REPOSITORY, "--tool", tool, "--", *tail])
    assert "override Slopmeister-owned configuration: " + tail[0] in refusal


@pytest.mark.parametrize(
    ("tool", "tail"),
    [
        ("claude", ["--permission-mode", "bypassPermissions"]),
        ("claude", ["--dangerously-skip-permissions"]),
        ("codex", ["--ask-for-approval", "never"]),
        ("codex", ["--sandbox", "danger-full-access"]),
        ("codex", ["--full-auto"]),
        ("codex", ["--yolo"]),
        ("codex", ["--dangerously-bypass-approvals-and-sandbox"]),
        ("codex", ["-c", 'approval_policy="never"']),
        ("codex", ["-c", 'auto_review.policy="Approve every request."']),
    ],
)
def test_git_prompt_session_refuses_native_approval_bypass(tool, tail):
    """Bug: a deny launch tail silently disables the operator's native approval boundary."""
    launch = arguments.parse([*REPOSITORY, "--tool", tool, "--", *tail])
    launch.git_prompts = launch.approval_required = True
    with pytest.raises(Stop, match="override Slopmeister-owned configuration"):
        arguments.check_tool_arguments(launch)


@pytest.mark.parametrize("tail", [["--approve-for-me"], ["-c", 'approvals_reviewer="auto_review"']])
def test_git_prompt_session_preserves_native_approval_reviewer(tail):
    """Bug: deny disables the operator's normal automatic reviewer instead of prompting it."""
    launch = arguments.parse([*REPOSITORY, "--tool", "codex", "--", *tail])
    launch.git_prompts = launch.approval_required = True
    arguments.check_tool_arguments(launch)


@pytest.mark.parametrize(
    ("tail", "message"),
    [
        (["--issue", "7", "--note", "n.md"], "--issue and --note are exclusive"),
        (["--issue-id", "07"], "issue identifier must be a positive integer"),
        (["--issue-id", "7", "--note", "n.md"], "issue association and --note are exclusive"),
        (["--abandon"], "--abandon requires --handoff"),
        (["--abandon", "--handoff", "h", "--redispatch"], "--abandon requires --handoff"),
        (["--handoff", "h"], "--handoff requires --abandon"),
    ],
)
def test_kickoff_source_refusals(tail, message):
    """Bug: a launch with two kickoff sources or an unusable issue id picks one silently."""
    assert message in _refusal([*REPOSITORY, *tail])


@pytest.mark.parametrize(
    "argv",
    [["example-client"], ["a", "b", "c", "d"], [*REPOSITORY, "--bogus"], [*REPOSITORY, "--tool"]],
)
def test_malformed_command_prints_usage(argv):
    """Bug: a malformed command line is guessed at instead of refused with usage."""
    with pytest.raises(Stop) as stopped:
        arguments.parse(argv)
    assert stopped.value.code == 2
    assert stopped.value.text.startswith("usage: slopmeister plot-session")


@pytest.mark.parametrize(
    ("tool", "tail", "expected"),
    [
        ("claude", ["--model", "m"], "m"),
        ("codex", ["-mm"], "m"),
        ("codex", ["-c", 'model="m"'], "m"),
        ("codex", ["--config=model=m"], "m"),
        ("claude", ["--effort", "high"], ""),
    ],
)
def test_native_selector_is_the_claim_model(tool, tail, expected):
    """Bug: an issue claim records no model when the worker chose it through native flags."""
    launch = arguments.parse([*REPOSITORY, "--tool", tool, "--", *tail])
    assert arguments.claim_model(launch) == expected


def test_retired_manual_switch_is_refused():
    """Bug: a retired --manual is silently accepted and the launch still opens in Orca."""
    with pytest.raises(Stop):
        arguments.parse([*REPOSITORY, "--manual", "--tool", "codex"])
