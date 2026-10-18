"""Browser sandbox helpers are not conversations, and prompt text is not a subcommand."""

import subprocess

import pytest

from slopmeister.threads import occupants


@pytest.mark.parametrize(
    ("arguments", "is_worker"),
    [
        ("/Applications/ChatGPT.app/bin/codex sandbox -c policy node kernel.js", False),
        ("/Applications/ChatGPT.app/bin/codex sandbox node trusted-worker.js", False),
        ("/opt/bin/codex app-server", False),
        ("/opt/agent tools/bin/codex app-server", False),
        ("/opt/agent tools/bin/codex remote-control", False),
        ("/opt/agent tools/bin/codex sandbox node kernel.js", False),
        ("codex --no-daemon Explain /opt/bin/codex sandbox", True),
        ("/opt/agent tools/bin/codex --no-daemon Explain /opt/bin/codex sandbox", True),
        ("/opt/bin/codex --no-daemon Explain /opt/bin/codex sandbox", True),
        ("/opt/bin/codex --no-daemon Explain /opt/bin/codex app-server", True),
        ("/opt/bin/codex --no-daemon kickoff", True),
    ],
)
def test_browser_helpers_do_not_occupy_a_workspace(monkeypatch, arguments, is_worker):
    def run(args):
        if args[:2] == ["ps", "-axo"]:
            output = "101 ttys001 /opt/bin/codex\n"
        elif args[0] == "lsof":
            output = "p101\nfcwd\nn/work\n"
        else:
            output = arguments if args[-1] == "args=" else "Mon Jan 1 /opt/bin/codex"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(occupants, "run", run)
    assert bool(occupants.processes("/work", None)) is is_worker
