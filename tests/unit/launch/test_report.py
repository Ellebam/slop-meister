"""The reported resume command must recover the same standalone Codex session."""

from pathlib import Path
import shlex
import tomllib

import pytest

from slopmeister.launch import report
from slopmeister.launch.model import Delivery, Launch


@pytest.mark.parametrize("service_actions", [False, True])
def test_resume_pins_home_and_auto_review(monkeypatch, tmp_path, capsys, service_actions):
    """Bug: resume loses the launcher's reviewer or selected native writer approvals."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(report.kickoff, "receipt", lambda _: "receipt")
    monkeypatch.setattr(report, "_thread_name", lambda *_: "recorded")
    launch = Launch("example-client", "example-client-worker", "repo", tool="codex")
    launch.wt = tmp_path / "worker"
    if service_actions:
        config = launch.wt / ".codex/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[mcp_servers.jira_write.tools.run]\napproval_mode="prompt"\n'
            '[mcp_servers.confluence_write.tools.run]\napproval_mode="prompt"\n'
        )
    thread = "11111111-1111-4111-8111-111111111111"
    report.delivered(launch, Delivery(42, session=thread))
    resume = next(line for line in capsys.readouterr().out.splitlines() if "  resume: " in line)
    assert f"cd '{launch.wt}' && env CODEX_HOME='{tmp_path / 'codex'}'" in resume
    assert f"'{Path.home() / '.local/bin/codex'}' resume '{thread}' --no-daemon" in resume
    assert 'approval_policy="on-request"' in resume
    assert 'approvals_reviewer="auto_review"' in resume
    assert 'approvals_reviewer="user"' not in resume
    assert "project_root_markers=" in resume
    assert "--remote" not in resume
    pins = [word for word in shlex.split(resume) if word.startswith("mcp_servers.")]
    assert len(pins) == (2 if service_actions else 0)
    for pin in pins:
        server = next(iter(tomllib.loads(pin)["mcp_servers"].values()))
        assert server["tools"]["run"]["approval_mode"] == "prompt"


def test_manual_reviewer_resume_keeps_manual_choice(monkeypatch, tmp_path, capsys):
    """Bug: resuming a human-review worker silently restores automatic approval."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(report.kickoff, "receipt", lambda _: "receipt")
    monkeypatch.setattr(report, "_thread_name", lambda *_: "recorded")
    launch = Launch("example-client", "example-client-worker", "repo", tool="codex")
    launch.wt = tmp_path / "worker"
    launch.extra = ["-c", 'approvals_reviewer="user"']

    report.delivered(launch, Delivery(42, session="11111111-1111-4111-8111-111111111111"))

    resume = next(line for line in capsys.readouterr().out.splitlines() if "  resume: " in line)
    assert resume.index('approvals_reviewer="auto_review"') < resume.index(
        'approvals_reviewer="user"'
    )
