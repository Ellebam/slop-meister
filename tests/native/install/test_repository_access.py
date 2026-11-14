"""Already-running clients use a newly attached worktree inside their existing workspace."""

from dataclasses import replace
import json
from pathlib import Path
import shlex
import subprocess

import pytest

from tests.integration.launch.helpers import CLI, declare, launch, machine, target
from tests.native.install.test_permissions import client_command, shell_call
from tests.support.repos import git
from tests.support.standin import StandIn, capture_server, run, tool_results


class AddingRepository(StandIn):
    def request_path(self):
        if len(self.server.requests) == 2:
            self.server.attach()
        return super().request_path()


def workspace(tmp_path, tool):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    primary_repo, companion_repo = [target(tmp_path / name) for name in ("entry", "storage")]
    for repo in (primary_repo, companion_repo):
        (repo / "value.txt").write_text("original\n")
        git(repo, "add", "value.txt")
        git(repo, "commit", "-qm", "Seed input")
    launch(world, str(primary_repo), "example-app", "example-app-native", "--tool", tool)
    primary = primary_repo / ".worktrees/example-app-native"
    companion = primary / ".slopmeister-repos/storage"
    return world, primary, companion_repo, companion


def prepared_client(tool, native, server, primary, companion):
    client = client_command(tool, native, server.server_port)
    argv = [str(primary) if arg == str(client.cwd) else arg for arg in client.argv]
    if tool == "claude":
        argv = ["auto" if arg == "bypassPermissions" else arg for arg in argv]
        argv[argv.index("--tools") + 1] = "Read,Edit"
        argv[-2:-2] = ["--settings", str(primary / ".claude/access-settings.json")]
        server.script = [
            ("Read", {"file_path": str(primary / "value.txt")}),
            (
                "Edit",
                {
                    "file_path": str(companion / "value.txt"),
                    "old_string": "original",
                    "new_string": "changed",
                },
            ),
            ("Read", {"file_path": str(companion / "value.txt")}),
        ]
    else:
        home = Path(client.env["CODEX_HOME"])
        (home / "config.toml").write_text(
            f"[projects.{json.dumps(str(primary))}]\ntrust_level = 'trusted'\n"
        )
        argv[-1:-1] = ["--sandbox", "workspace-write"]
        source = "from pathlib import Path; import sys; p=Path(sys.argv[1]); "
        scripts = [
            (source + "print(p.read_text())", primary / "value.txt"),
            (source + "p.write_text('changed\\n'); print(p.read_text())", companion / "value.txt"),
        ]
        server.script = [
            shell_call(tool, shlex.join(["python3", "-c", code, str(path)]))
            for code, path in scripts
        ]
    return replace(client, argv=argv, cwd=primary, timeout=90)


@pytest.mark.xdist_group("native-standin")
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_running_client_reads_and_writes_a_later_repository(tmp_path, tool):
    world, primary, companion_repo, companion = workspace(tmp_path, tool)
    added = []

    def attach():
        assert not companion.exists()
        result = subprocess.run(
            [
                str(CLI),
                "repository",
                "add",
                "--workspace",
                str(primary),
                "--repo",
                str(companion_repo),
            ],
            env=world.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        added.append(result.stdout)

    native = tmp_path / "native"
    native.mkdir()
    server = capture_server(native / "requests", tool, [])
    server.RequestHandlerClass = AddingRepository
    server.attach = attach
    client = prepared_client(tool, native, server, primary, companion)
    try:
        run(client)
    finally:
        server.shutdown()
        server.server_close()
    assert len(added) == 1
    assert (companion / "value.txt").read_text() == "changed\n"
    assert (companion_repo / "value.txt").read_text() == "original\n"
    assert "changed" in json.dumps(tool_results(server.requests[-1]))
