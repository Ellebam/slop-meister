"""Drive Claude positive controls and exclusive prepared discovery."""

import json

from tests.native.install.discovery_fixture import CLAUDE, git
from tests.support.standin import (
    Command,
    capture_server,
    put,
    require,
    run,
    tool_results,
)

FOREIGN = (
    "FOREIGN_CLAUDE_ROOT",
    "FOREIGN_CLAUDE_LOCAL",
    "FOREIGN_IMPORT",
    "FOREIGN_CLAUDE_NESTED",
    "FOREIGN_CLAUDE_HOOK",
    "FOREIGN_MAIN_LOCAL_HOOK",
    "FOREIGN_RULE",
    "FOREIGN_NESTED_RULE",
    "FOREIGN_LINK_AGREEMENT",
    "FOREIGN_CLAUDE_SKILL",
    "FOREIGN_CLAUDE_AGENT",
    "FOREIGN_LEGACY_COMMAND",
    "FOREIGN_EXTRA_SKILL",
    "FOREIGN_EXTRA_AGENT",
    "FOREIGN_EXTRA_MEMORY",
)
EXPECTED = (
    "GLOBAL_CLAUDE_MARKER",
    "GLOBAL_AGENT_MARKER",
    "GLOBAL_HOOK_MARKER",
    "SLOPMEISTER_AGREEMENT_MARKER",
    "SLOPMEISTER_SKILL_MARKER",
)

PRINT_FLAGS = (
    "-p",
    "--verbose",
    "--output-format",
    "stream-json",
    "--strict-mcp-config",
    "--no-chrome",
)

__all__ = ["verify_claude"]


def verify_claude(fixture, prepare_codex):
    server = capture_server(fixture.root / "requests", "baseline", [])
    fixture.env.update(
        ANTHROPIC_API_KEY="fixture-only",
        ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_port}",
    )
    try:
        baseline = claude_case(fixture, server, baseline_case(fixture))
        for marker in (*FOREIGN, *EXPECTED[:3]):
            require(marker in baseline, "missing Claude positive control: " + marker)
        prepare_codex(fixture)
        verify_prepared(fixture, server)
        verify_generic(fixture, server)
        verify_late(fixture, server)
    finally:
        server.shutdown()
        server.server_close()


def baseline_case(fixture):
    return (
        "claude-baseline",
        fixture.workspace / "nested/app.txt",
        ["--setting-sources", "user,project,local", "--add-dir", str(fixture.extra)],
        fixture.workspace,
    )


def claude_case(fixture, server, case):
    name, read_path, options, cwd = case
    server.case, server.requests = name, []
    server.script = [("Read", {"file_path": str(read_path)})]
    tools = ["--tools", "Read,Skill,Agent", "--allowedTools", "Read"]
    argv = [CLAUDE, *PRINT_FLAGS, *tools, *options, "--", "Return DISCOVERY_DONE."]
    run(Command(argv, cwd, fixture.env, fixture.root / name))
    require(len(server.requests) >= 2, name + ": no attributable second request after Read")
    results = [part for request in server.requests for part in tool_results(request)]
    require(
        any(
            not part.get("is_error") and read_path.read_text().strip() in json.dumps(part)
            for part in results
        ),
        name + ": ordinary Read did not succeed",
    )
    return json.dumps(server.requests)


def prepared_flags(workspace):
    return [
        "--setting-sources",
        "user,project",
        "--append-system-prompt-file",
        str(workspace / "CLAUDE.md"),
        "--settings",
        str(workspace / ".claude/access-settings.json"),
    ]


def verify_prepared(fixture, server):
    flags = prepared_flags(fixture.workspace)
    for name, path in (
        ("claude-replaced", fixture.workspace / "nested/app.txt"),
        ("claude-extra-read", fixture.extra / "app.txt"),
    ):
        captured = claude_case(fixture, server, (name, path, flags, fixture.workspace))
        verify_markers(name, captured)
        print(
            f"PASS {name}: positive controls excluded, global and Slopmeister retained, "
            "ordinary Read confirmed",
            flush=True,
        )


def verify_markers(name, captured):
    for marker in FOREIGN:
        require(marker not in captured, name + ": competing configuration loaded: " + marker)
    for marker in EXPECTED:
        require(marker in captured, name + ": expected configuration missing: " + marker)


def verify_generic(fixture, server):
    generic = fixture.repo / ".worktrees/generic"
    git(fixture, ["worktree", "add", "-qb", "generic", str(generic)])
    argv = [str(fixture.product / "bin/slopmeister"), "install", "--prepare", "probe", str(generic)]
    run(Command(argv, fixture.root, fixture.env, fixture.root / "prepare-generic"))
    case = ("claude-no-grants", generic / "nested/app.txt", prepared_flags(generic), generic)
    captured = claude_case(fixture, server, case)
    verify_markers("ordinary plot", captured)
    print(
        "PASS claude-no-grants: upstream fallback excluded without a Slopmeister-root grant",
        flush=True,
    )


def verify_late(fixture, server):
    late = fixture.workspace / "late-product"
    put(late / ".claude/rules/nested.md", "FOREIGN_NESTED_RULE\n")
    case = (
        "claude-late-config",
        late / "app.txt",
        prepared_flags(fixture.workspace),
        fixture.workspace,
    )
    captured = claude_case(fixture, server, case)
    require(
        "FOREIGN_NESTED_RULE" not in captured, "Claude loaded a rule introduced after preparation"
    )
    for marker in (
        "GLOBAL_CLAUDE_MARKER",
        "SLOPMEISTER_AGREEMENT_MARKER",
        "SLOPMEISTER_SKILL_MARKER",
    ):
        require(marker in captured, "late Claude case lost expected configuration: " + marker)
    print(
        "PASS late native configuration: root launches exclude new nested rules/settings, "
        "Claude Read confirmed",
        flush=True,
    )
