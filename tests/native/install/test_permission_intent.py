"""Native prefix selection gates broad cleanup while leaving owned-PID cleanup unlisted."""

from dataclasses import replace
import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from tests.native.install.discovery_fixture import CODEX
from tests.native.install.intent_fixture import (
    IntentModel,
    claude_host,
    is_review,
    main_results,
)
from tests.native.install.test_permissions import client_command, shell_call
from tests.support.fakes import fake_binary
from tests.support.standin import capture_server, run

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "command",
    [
        ["pkill", "-f", "x"],
        ["killall", "x"],
        ["docker", "volume", "prune"],
        ["docker", "system", "prune"],
        ["docker", "image", "prune"],
        ["docker", "container", "prune"],
    ],
)
def test_broad_cleanup_prompts_despite_an_inherited_allow(tmp_path, command):
    """Bug: an inherited executable-wide allow bypasses the cleanup intent rule."""
    saved = tmp_path / "saved.rules"
    saved.write_text(f'prefix_rule(pattern={json.dumps(command[:1])}, decision="allow")\n')
    result = subprocess.run(
        [
            str(CODEX),
            "execpolicy",
            "check",
            "--rules",
            str(saved),
            "--rules",
            str(ROOT / "dist/codex/rules/permissions.rules"),
            "--",
            *command,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["decision"] == "prompt"


def test_direct_recorded_pid_kill_has_no_permission_prefix_rule():
    """Bug: guarding broad cleanup also adds a rule that blocks individual PID cleanup."""
    result = subprocess.run(
        [
            str(CODEX),
            "execpolicy",
            "check",
            "--rules",
            str(ROOT / "dist/codex/rules/permissions.rules"),
            "--",
            "kill",
            "12345",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["matchedRules"] == []


def _cleanup_call(stub, installed, stop_only, invalid, report):
    path = str(installed.workspace) + ("-other" if invalid == "path" else "")
    flags = ["--self", "--stop-only"] if stop_only else ["--self"]
    args = [str(stub), "workspace-remove", *flags, "--", path]
    if invalid == "extra":
        args.append("--force")
    call = shlex.join(args)
    return f"cd {shlex.quote(str(installed.repo))} && {call} < {shlex.quote(str(report))}"


def _cleanup_world(root, tool, stop_only=False, invalid=""):
    from tests.integration.install.installer_helpers import prepared

    (root / "install").mkdir()
    installed = prepared(root / "install")
    body = (
        f'exec {shlex.quote(str(ROOT / "bin/slopmeister"))} "$@"'
        if invalid
        else 'echo SELF_RELEASE_RAN "$@"\ncat'
    )
    fake_binary(root / "stubs", "slopmeister", body)
    stub = root / "stubs/slopmeister"
    original = str(ROOT / "bin/slopmeister")
    access = installed.workspace / ".claude/access-settings.json"
    access = access.read_text().replace(original, str(stub))
    # A prepared report exercises stdin without a shell temporary-file dependency.
    report = root / "harvest-report.txt"
    report.write_text("Harvest report from standard input. Keep $(false) literal.\n")
    call = _cleanup_call(stub, installed, stop_only, invalid, report)
    server = capture_server(root / "requests", tool, [shell_call(tool, call)])
    server.RequestHandlerClass = IntentModel
    (root / "native").mkdir()
    client = client_command(tool, root / "native", server.server_port)
    argv = ["auto" if part == "bypassPermissions" else part for part in client.argv]
    if tool == "claude":
        settings = client.cwd / ".claude/access-settings.json"
        settings.parent.mkdir()
        settings.write_text(access)
    else:
        source = installed.workspace / ".codex/rules/self-release.rules"
        rule = Path(client.env["CODEX_HOME"]) / "rules/self-release.rules"
        rule.write_text(source.read_text().replace(original, str(stub)))
    return SimpleNamespace(client=replace(client, argv=argv), server=server, command=call)


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("stop_only", [False, True])
def test_protected_cleanup_compound_runs_without_a_prompt(tmp_path, tool, stop_only):
    """An exact cleanup allow must also work after the real caller's directory change."""
    world = _cleanup_world(tmp_path, tool, stop_only)
    try:
        if tool == "claude":
            assert claude_host(world, approved=False) == []
        else:
            run(world.client)
        flags = "--self --stop-only --" if stop_only else "--self --"
        result = main_results(world)
        assert f"SELF_RELEASE_RAN workspace-remove {flags}" in result, result
        assert "Keep $(false) literal." in result
        assert "Harvest report from standard input. Keep $(false) literal." in result, result
        assert not any(is_review(r) for r in world.server.requests)
    finally:
        world.server.shutdown()
        world.server.server_close()


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("invalid", ["path", "extra"])
def test_stop_only_wrong_path_or_extra_arguments_are_refused(tmp_path, tool, invalid):
    """Exact permission or command validation must reject an altered stop request."""
    world = _cleanup_world(tmp_path, tool, True, invalid)
    try:
        requests = claude_host(world, approved=False) if tool == "claude" else []
        if tool == "codex":
            run(world.client)
        output = main_results(world)
        expected = (
            "workspace directory not found"
            if invalid == "path"
            else "unrecognized arguments: --force"
        )
        if requests:
            assert requests[0]["input"]["command"] == world.command
            assert "STANDIN_HOST_DENIED" in output
        else:
            assert expected in output, output
        assert "session stop pending" not in output
    finally:
        world.server.shutdown()
        world.server.server_close()


def test_native_cleanup_prefix_does_not_match_other_targets_or_force(tmp_path):
    from tests.integration.install.installer_helpers import prepared

    installed = prepared(tmp_path)
    entry = str(ROOT / "bin/slopmeister")
    path = str(installed.workspace)
    base = [str(CODEX), "execpolicy", "check", "--rules"]
    base += [str(installed.workspace / ".codex/rules/self-release.rules"), "--"]
    for args, matched in (
        ([entry, "workspace-remove", "--self", "--", path], True),
        ([entry, "workspace-remove", "--self", "--stop-only", "--", path], True),
        ([entry, "workspace-remove", "--self", "--stop-only", "--", path + "-other"], False),
        ([entry, "workspace-remove", "--self", "--stop-only", "--force", "--", path], False),
        ([entry, "workspace-remove", path, "--self", "--force"], False),
        ([entry, "workspace-remove", "--self", "--force", "--", path], False),
        ([entry, "workspace-remove", path], False),
        ([entry, "workspace-remove", "--self", "--", path + "-other"], False),
        ([entry + "-other", "workspace-remove", "--self", "--", path], False),
    ):
        result = subprocess.run(
            [*base, *args], capture_output=True, text=True, check=True, timeout=10
        )
        decision = json.loads(result.stdout)
        assert bool(decision["matchedRules"]) is matched, args
        if matched:
            assert decision["decision"] == "allow"


@pytest.mark.parametrize("client", ["gh", "glab"])
@pytest.mark.parametrize(
    "args",
    [
        ["repos/owner/repository/contents"],
        ["--method", "POST", "repos/owner/repository/issues"],
        ["--method", "GET", "repos/owner/repository/issues", "--input", "body.json"],
        ["graphql", "-f", "query=mutation { operation }"],
        ["repos/owner/repository/actions/variables"],
        ["user/keys"],
        ["--hostname", "unknown.invalid", "repos/owner/repository"],
        ["--method", "GET", "repos/owner/repository", "--method", "DELETE"],
        ["--method", "GET", "repos/owner/repository/issues"],
        ["-X", "GET", "repos/owner/repository/issues"],
    ],
)
def test_api_commands_keep_native_review_for_reads_and_mutations(client, args):
    """Codex prompts for every API command. Claude allows only the explicit GET prefixes."""
    result = subprocess.run(
        [
            str(CODEX),
            "execpolicy",
            "check",
            "--rules",
            str(ROOT / "dist/codex/rules/permissions.rules"),
            "--",
            client,
            "api",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["decision"] == "prompt"
    settings = json.loads((ROOT / "dist/claude/settings.json").read_text())
    allowed = [
        rule for rule in settings["permissions"]["allow"] if rule.startswith(f"Bash({client} api")
    ]
    assert allowed == [
        f"Bash({client} api {method} GET{rest})"
        for method in ("--method", "-X")
        for rest in ("", " *")
    ]


def test_review_allow_selects_only_the_launch_source_ordinary_command(tmp_path):
    """The worker binary, replacement and raw client must not inherit the ordinary allow."""
    from tests.integration.install.installer_helpers import prepared

    installed = prepared(tmp_path)
    source = str(ROOT / "bin/slopmeister")
    worker = str(installed.workspace / "bin/slopmeister")
    access = json.loads((installed.workspace / ".claude/access-settings.json").read_text())
    assert f"Bash({source} review review *)" in access["permissions"]["allow"]
    assert f"Bash({source} review replace *)" in access["permissions"]["ask"]
    assert not any(worker in rule for rule in access["permissions"]["allow"])
    rule = str(installed.workspace / ".codex/rules/review.rules")
    for args, allowed in (
        ([source, "review", "review", "--mode", "plan"], True),
        ([source, "review", "review", "--mode", "diff", "--candidate"], True),
        ([worker, "review", "review", "--mode", "plan"], False),
        ([source, "review", "replace", "--mode", "plan"], False),
        ([str(CODEX), "exec", "--dangerously-bypass-approvals-and-sandbox"], False),
    ):
        result = subprocess.run(
            [str(CODEX), "execpolicy", "check", "--rules", rule, "--", *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        decision = json.loads(result.stdout)
        assert bool(decision["matchedRules"]) is allowed, args
        if allowed:
            assert decision["decision"] == "allow"
