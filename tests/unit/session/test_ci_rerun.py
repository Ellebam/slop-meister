"""Saved destinations, complete provider history and incomplete-result recovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from slopmeister.session import ci_rerun
from slopmeister.session.ci_rerun_common import Context, Run, pages, remote


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:example/project.git", ("github", "github.com", "example/project")),
        (
            "https://gitlab.example.invalid/group/project.git",
            ("gitlab", "gitlab.example.invalid", "group/project"),
        ),
        (
            "git@ssh.dev.azure.com:v3/org/project/repo",
            ("azure", "dev.azure.com", "org/project/repo"),
        ),
        (
            "https://org.visualstudio.com/project/_git/repo",
            ("azure", "dev.azure.com", "org/project/repo"),
        ),
    ],
)
def test_remote_infers_provider_without_caller_override(url, expected):
    assert remote(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://token@github.com/example/project",
        "file:///tmp/repo",
        "https://github.com/example/../other",
        "https://github.com/example/%2e%2e",
        "https://github.com/example/a%2fb",
        "https://github.com/example/project?other=true",
    ],
)
def test_remote_rejects_credentials_and_path_injection(url):
    with pytest.raises(ValueError, match="unsupported repository remote"):
        remote(url)


def test_pagination_reads_later_history_before_a_retry_decision():
    calls = []

    def fetch(endpoint):
        calls.append(endpoint)
        return [dict(id=1)] * 100 if endpoint.endswith("&page=1") else [dict(id=2, retried=True)]

    result = pages(fetch, "projects/1/jobs?include_retried=true")
    assert result[-1] == dict(id=2, retried=True)
    assert len(calls) == 2 and "page=2" in calls[-1]


def test_incomplete_rerun_prints_read_only_followup_without_another_write(monkeypatch, capsys):
    initial = Run("https://ci.example.invalid/run/7", "failed", True, 1, (), {})
    writes = []
    service = SimpleNamespace(
        read=lambda *args: initial,
        retry=lambda *args: writes.append(7),
        status=lambda *args: ["gh", "run", "view", "7"],
    )
    monkeypatch.setattr(ci_rerun, "provider", lambda name: service)
    monkeypatch.setattr(ci_rerun.time, "monotonic", lambda: 100)
    ctx = Context(Path("."), "task", "a" * 40, "github", "github.com", "e/p", 101)
    with pytest.raises(ValueError, match="incomplete"):
        ci_rerun.execute(ctx, 7)
    assert writes == [7]
    assert '"status_command": "gh run view 7"' in capsys.readouterr().out
