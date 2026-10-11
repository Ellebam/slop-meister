"""The real dispatcher Task must deliver Jira readers before any model is launched."""

import json
from pathlib import Path

from tests.integration.dispatch.test_public_command import _reported, _run
from tests.integration.install.helpers import profile, unlock_deliveries
from tests.integration.launch.helpers import machine


def test_dispatcher_task_carries_declared_jira_profile_into_both_tool_trees(tmp_path):
    """Bug: installer tests pass while task dispatch forgets the aggregation option."""
    world = machine(tmp_path)
    declaration = Path(world.env["PLOT_DECLARATIONS"]) / "example-app/plot.toml"
    text = declaration.read_text().replace(
        "[target]\n", '[target]\nservice_actions=["jira-read"]\n'
    )
    declaration.write_text(text)
    data = profile("example-app") | {"backlog_jql": 'project = "TEST" ORDER BY key ASC'}
    path = Path(world.env["HOME"]) / ".config/slopmeister/access/example-app/jira-read.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    try:
        result = _run(world, "codex", "jira-fixture", "--model", "fixture-model")
        assert result.returncode == 0, result.stdout + result.stderr
        workspace = _reported(result.stdout, "prepared directory")
        for native in (".codex", ".claude"):
            reader = workspace / native / "service-actions/example-app/jira-read"
            assert json.loads((reader / "config.json").read_text()) == data
            assert reader.stat().st_mode & 0o777 == 0o555
            assert (reader / "config.json").stat().st_mode & 0o777 == 0o400
        assert "launch skipped" in result.stdout
    finally:
        unlock_deliveries(tmp_path)
