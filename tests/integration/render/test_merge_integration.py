"""Execute exact merged-tree proof against disposable Git history and a synthetic forge."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support.repos import GIT_ENV, git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]
FAKE_GH = r"""
import json, sys
from pathlib import Path
args = sys.argv[1:]
data = json.loads(Path("github.json").read_text())
log = Path("calls.json")
calls = json.loads(log.read_text()) if log.exists() else []
log.write_text(json.dumps([*calls, args]))
if args[:2] == ["pr", "view"]:
    print(data.get("state", "MERGED") + " " + data["commit"])
elif args[:2] == ["run", "list"]:
    assert args[args.index("--commit") + 1] == data["expected"], args
    assert args[args.index("--workflow") + 1] == "check", args
    if data["expected"] == data["head"]:
        assert args[args.index("--event") + 1] == "pull_request", args
    else:
        assert args[args.index("--branch") + 1] == "main", args
    print("" if data.get("missing") else "73 " + data.get("run_sha", data["expected"]))
elif args[:2] == ["run", "watch"]:
    assert args[2] == "73" and "--exit-status" in args, args
    sys.exit(1 if data.get("watch_failed") else 0)
elif args[:2] == ["run", "view"]:
    print(data["expected"] + " " + data.get("result", "completed success"))
else:
    sys.exit("unexpected write or command: " + repr(args))
"""


def history(root: Path, kind: str):
    repo = scratch_repo(root)
    git(repo, "checkout", "-qb", "head")
    (repo / "head.txt").write_text("head change")
    git(repo, "add", "head.txt")
    git(repo, "commit", "-qm", "Change the head")
    head = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "main")
    if kind == "diverged":
        (repo / "base.txt").write_text("base change")
        git(repo, "add", "base.txt")
    if kind != "aligned":
        git(repo, "commit", "--allow-empty", "-qm", "Advance the base")
    git(repo, "merge", "--no-ff", "--no-edit", "head")
    commit = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "remote", "add", "origin", repo.as_uri())
    return repo, head, commit


@pytest.fixture(params=["aligned", "diverged", "same-tree-diverged"])
def integration(tmp_path, request):
    repo, head, commit = history(tmp_path / "repo", request.param)
    binary = tmp_path / "bin"
    binary.mkdir()
    for name, text in (("gh", f"#!{sys.executable}\n" + FAKE_GH), ("sleep", "#!/bin/sh\nexit 0\n")):
        path = binary / name
        path.write_text(text)
        path.chmod(0o700)
    env = {**os.environ, **GIT_ENV, "PATH": f"{binary}:/usr/bin:/bin", "GIT_ALLOW_PROTOCOL": "file"}
    env.update(
        merge_repository="owner/subject",
        merge_number="7",
        merge_base="main",
        merge_head=head,
        merge_proof="ci",
        merge_workflow="check",
    )
    text = (ROOT / "dist/codex/skills/merge/integration.md").read_text()
    command = text.split("```bash\n", 1)[1].split("\n```", 1)[0]
    return {
        "root": repo,
        "env": env,
        "command": command,
        "kind": request.param,
        "commit": commit,
        "head": head,
        "expected": head if request.param == "aligned" else commit,
    }


def run_proof(context, **changes):
    root = context["root"]
    data = {key: context[key] for key in ("commit", "head", "expected")}
    (root / "github.json").write_text(json.dumps({**data, **changes}))
    result = subprocess.run(
        ["bash", "-c", context["command"]],
        cwd=root,
        env=context["env"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, json.loads((root / "calls.json").read_text())


def test_exact_tree_and_ancestry_choose_the_only_acceptable_run(integration):
    result, calls = run_proof(integration)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"run 73 on {integration['expected']}" in result.stdout
    assert [call[:2] for call in calls] == [
        ["pr", "view"],
        ["run", "list"],
        ["run", "watch"],
        ["run", "view"],
    ]
    # Replaying an already-merged task performs the same reads and no second merge.
    repeated, calls = run_proof(integration)
    assert repeated.returncode == 0, repeated.stderr
    assert not any(call[:2] == ["pr", "merge"] for call in calls)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"missing": True}, "no exact-commit integration run"),
        ({"run_sha": "f" * 40}, "another commit or invalid identity"),
        ({"watch_failed": True}, "integration gate did not succeed"),
        ({"result": "in_progress "}, "not successful on the exact commit"),
        ({"result": "completed failure"}, "not successful on the exact commit"),
        ({"result": "completed skipped"}, "not successful on the exact commit"),
        ({"state": "OPEN"}, "PR is not merged"),
    ],
)
def test_missing_or_wrong_integration_proof_stops_without_dispatch(integration, change, reason):
    result, calls = run_proof(integration, **change)
    assert result.returncode != 0 and reason in result.stderr
    assert not any(call[0] == "workflow" or call[:2] == ["pr", "merge"] for call in calls)
    if change.get("missing"):
        assert sum(call[:2] == ["run", "list"] for call in calls) == 2


def test_bootstrap_reuse_requires_the_unchanged_proved_tree(integration):
    integration["env"]["merge_proof"] = "bootstrap"
    result, calls = run_proof(integration)
    assert (result.returncode == 0) == (integration["kind"] == "aligned")
    assert [call[:2] for call in calls] == [["pr", "view"]]
    if integration["kind"] != "aligned":
        assert "bootstrap merged tree differs" in result.stderr
