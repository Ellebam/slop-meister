"""Disposable prepared repositories and recording CI provider clients."""

import json
import os
from pathlib import Path
import sys

from tests.integration.install.installer_helpers import (
    ROOT,
    environment,
    install,
    project,
    worktree,
)
from tests.support.repos import git

FAKE = r"""
import json, os, sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

root = Path(os.environ["CI_FIXTURE"])
state = json.loads((root / "state.json").read_text())
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(args) + "\n")


def mutate():
    state["attempt"] = state.get("attempt", 1) + 1
    (root / "state.json").write_text(json.dumps(state))
    if state.get("uncertain"):
        sys.stderr.write("sensitive-provider-diagnostic")
        sys.exit(1)


attempt = state.get("attempt", 1)
failed = attempt == 1 or state.get("fails_again")
sha = state.get("head_sha", state["sha"])
branch = state.get("branch", "task")
if Path(sys.argv[0]).name == "glab":
    method = args[args.index("--method") + 1]
    path = urlsplit(args[-1]).path
    query = parse_qs(urlsplit(args[-1]).query)

    def job(n, name, status):
        return dict(id=n, name=name, status=status, stage="test", tag=False, pipeline=dict(id=7))

    if method == "POST":
        assert path == "projects/1/jobs/11/retry", args
        mutate()
        result = job(12, "flaky", "pending")
    elif path == "projects/example%2Fproject":
        result = dict(id=1, path_with_namespace="example/project", default_branch="main")
    elif path == "projects/1/pipelines/7":
        result = dict(
            id=7,
            project_id=state.get("repository_id", 1),
            ref=branch,
            sha=sha,
            source=state.get("event", "push"),
            status="failed" if failed else "success",
        )
    elif path.endswith("/merge_requests/9/pipelines"):
        result = [dict(id=7)] if state.get("mr_pipeline_member", True) else []
    elif path.endswith("/merge_requests") and state.get("mr"):
        result = [dict(iid=9, sha=state["sha"], source_branch="task", target_branch="main",
                       source_project_id=state.get("mr_source_project", 1), target_project_id=1)]
    elif path.endswith("/merge_requests"):
        result = (
            [
                dict(
                    state="merged",
                    sha=state["sha"],
                    merge_commit_sha=sha,
                    source_branch="task",
                    target_branch="main",
                    source_project_id=1,
                    target_project_id=1,
                )
            ]
            if state.get("merged")
            else []
        )
    elif path.endswith("/jobs"):
        result = [
            job(10 + attempt, "flaky", "failed" if failed else "success"),
            job(20, "control", "success"),
        ]
        if attempt == 2 and query.get("include_retried") == ["true"]:
            result.append(job(11, "flaky", "failed"))
    else:
        raise AssertionError(args)
    print(json.dumps(result))
    sys.exit(0)
if Path(sys.argv[0]).name == "az":

    def option(name):
        return args[args.index(name) + 1]

    method, resource = option("--http-method"), option("--resource")
    if method == "PATCH":
        assert resource == "stages" and "stageRefName=Test" in args, args
        body = json.loads(Path(option("--in-file")).read_text())
        assert body == dict(state="retry", forceRetryAllJobs=False), body
        mutate()
        result = None
    elif resource == "repositories":
        result = dict(
            id="repo-id",
            name="repository",
            project=dict(name="project"),
            defaultBranch="refs/heads/main",
        )
    elif resource == "builds":
        result = dict(
            id=7,
            repository=dict(id=state.get("repository_id", "repo-id"), type="TfsGit"),
            sourceBranch="refs/heads/" + branch,
            sourceVersion=sha,
            reason=state.get("event", "individualCI"),
            status="completed",
            result="failed" if failed else "succeeded",
        )
    elif resource == "timeline":
        result = dict(
            records=[
                dict(
                    id="stage-id",
                    name="Test",
                    identifier="Test",
                    type="Stage",
                    result="failed" if failed else "succeeded",
                    attempt=attempt,
                ),
                dict(
                    id="job-id",
                    name="flaky",
                    type="Job",
                    attempt=attempt,
                    result="failed" if failed else "succeeded",
                    state="completed",
                ),
                dict(
                    id="control-id",
                    name="control",
                    type="Job",
                    attempt=1,
                    result="succeeded",
                    state="completed",
                ),
            ]
        )
    elif resource == "pullRequests":
        result = dict(
            value=[
                dict(
                    status="completed",
                    sourceRefName="refs/heads/task",
                    targetRefName="refs/heads/main",
                    repository=dict(id="repo-id"),
                    lastMergeSourceCommit=dict(commitId=state["sha"]),
                    lastMergeCommit=dict(commitId=sha),
                )
            ]
            if state.get("merged")
            else []
        )
    else:
        raise AssertionError(args)
    print(json.dumps(result))
    sys.exit(0)

method = args[args.index("--method") + 1]
endpoint = args[-1]
path = urlsplit(endpoint).path
if method == "POST":
    assert path == "repos/example/project/actions/runs/7/rerun-failed-jobs", args
    state["attempt"] = state.get("attempt", 1) + 1
    (root / "state.json").write_text(json.dumps(state))
    if state.get("uncertain"):
        sys.stderr.write("sensitive-provider-diagnostic")
        sys.exit(1)
    sys.exit(0)
if path == "repos/example/project":
    result = dict(id=1, full_name="example/project", default_branch="main")
elif path.endswith("/jobs"):
    attempt = state.get("attempt", 1)
    status = "failure" if attempt == 1 or state.get("fails_again") else "success"
    result = dict(
        jobs=[
            dict(
                id=10 + attempt,
                name="flaky",
                status="completed",
                conclusion=status,
                run_attempt=attempt,
            ),
            dict(id=20 + attempt, name="control", status="completed", conclusion="success",
                 run_attempt=attempt, started_at="2026-01-01T00:00:00Z",
                 completed_at="2026-01-01T00:00:01Z"),
        ]
    )
elif path.endswith("/pulls"):
    result = (
        [
            dict(
                merged_at="2026-01-01",
                merge_commit_sha=sha,
                head=dict(ref="task", sha=state["sha"], repo=dict(full_name="example/project")),
                base=dict(ref="main", repo=dict(full_name="example/project")),
            )
        ]
        if state.get("merged")
        else []
    )
elif path == "repos/example/project/actions/runs/7":
    result = dict(
        id=7,
        repository=dict(id=1),
        head_repository=dict(id=state.get("repository_id", 1)),
        head_branch=state.get("branch", "task"),
        head_sha=state.get("head_sha", state["sha"]),
        status="completed",
        conclusion="failure"
        if state.get("attempt", 1) == 1 or state.get("fails_again")
        else "success",
        run_attempt=state.get("attempt", 1),
        event=state.get("event", "push"),
    )
else:
    raise AssertionError(args)
print(json.dumps(result))
"""


def world(tmp_path: Path, provider: str, shipping: str = "allow"):
    env = environment(tmp_path)
    if shipping == "deny":
        declared = tmp_path / "plots/example-app"
        declared.mkdir(parents=True)
        source = (ROOT / "plots/example-app/plot.toml").read_text()
        (declared / "plot.toml").write_text(
            source.replace('shipping = "allow"', 'shipping = "deny"')
        )
        env["PLOT_DECLARATIONS"] = str(declared.parent)
    repo = project(tmp_path / "project")
    remote = {
        "github": "https://github.com/example/project.git",
        "gitlab": "https://gitlab.example.invalid/example/project.git",
        "azure": "https://dev.azure.com/example/project/_git/repository",
    }[provider]
    git(repo, "remote", "add", "origin", remote)
    workspace = worktree(repo, "task")
    install(env, "--prepare", "example-app", str(workspace))
    sha = git(workspace, "rev-parse", "HEAD").strip()
    state = tmp_path / "state.json"
    state.write_text(json.dumps(dict(sha=sha)))
    stub = tmp_path / "stubs" / {"github": "gh", "gitlab": "glab", "azure": "az"}[provider]
    stub.parent.mkdir()
    stub.write_text(f"#!{sys.executable}\n" + FAKE)
    stub.chmod(0o755)
    env.update(PATH=str(stub.parent) + os.pathsep + os.environ["PATH"], CI_FIXTURE=str(tmp_path))
    return workspace, env, state
