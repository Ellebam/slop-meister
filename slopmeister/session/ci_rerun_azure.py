"""Azure failed-stage retries with forceRetryAllJobs disabled."""

import json
import re
import tempfile

from slopmeister.session.ci_rerun_common import (
    Context,
    Job,
    Run,
    commit,
    number,
    object_value,
    rows,
    task_run,
    text,
)


def api(ctx: Context, area: str, resource: str, route: dict, **options):
    query, body = options.get("query", ()), options.get("body")
    org, project, _ = ctx.project.split("/")
    args = [
        "az",
        "devops",
        "invoke",
        "--organization",
        f"https://dev.azure.com/{org}",
        "--area",
        area,
        "--resource",
        resource,
        "--route-parameters",
        f"project={project}",
    ]
    args += [f"{key}={value}" for key, value in route.items()]
    args += ["--api-version", "7.1", "--output", "json", "--only-show-errors"]
    if query:
        args += ["--query-parameters", *query]
    if body is None:
        return json.loads(ctx.command(*args, "--http-method", "GET"))
    with tempfile.NamedTemporaryFile(mode="w+", dir=ctx.repo / ".slopmeister-tmp") as payload:
        json.dump(body, payload)
        payload.flush()
        value = ctx.command(*args, "--http-method", "PATCH", "--in-file", payload.name)
    return json.loads(value) if value else None


def own_merge(ctx: Context, run: dict, repo: dict) -> None:
    query = (
        f"searchCriteria.sourceRefName=refs/heads/{ctx.branch}",
        f"searchCriteria.targetRefName={repo['defaultBranch']}",
        "searchCriteria.status=completed",
        "$top=100",
    )
    matches = []
    for offset in range(0, 10000, 100):
        value = api(
            ctx,
            "git",
            "pullRequests",
            dict(repositoryId=repo["id"]),
            query=(*query, f"$skip={offset}"),
        )
        batch = rows(object_value(value)["value"])
        matches.extend(pr for pr in batch if merged(ctx, pr, repo, run["sourceVersion"]))
        if len(batch) < 100:
            break
    else:
        raise ValueError("provider pagination exceeds the limit")
    if run["reason"] not in ("individualCI", "batchedCI") or len(matches) != 1:
        raise ValueError("default-branch run is not this task's exact merge push")


def merged(ctx: Context, pr: dict, repo: dict, sha: str) -> bool:
    return (
        pr["status"] == "completed"
        and pr["sourceRefName"] == f"refs/heads/{ctx.branch}"
        and pr["targetRefName"] == repo["defaultBranch"]
        and pr["repository"]["id"] == repo["id"]
        and pr.get("forkSource") is None
        and pr["lastMergeSourceCommit"]["commitId"] == ctx.sha
        and pr["lastMergeCommit"]["commitId"] == sha
    )


def ownership(ctx: Context, run: dict, repo: dict) -> None:
    ref = text(run["sourceBranch"])
    match = re.fullmatch(r"refs/pull/([0-9]+)/merge", ref)
    if match:
        pr = object_value(
            api(ctx, "git", "pullRequests", dict(repositoryId=repo["id"], pullRequestId=match[1]))
        )
        if (
            pr["sourceRefName"] != f"refs/heads/{ctx.branch}"
            or pr.get("forkSource")
            or pr["repository"]["id"] != repo["id"]
            or run["reason"] != "pullRequest"
            or pr["lastMergeSourceCommit"]["commitId"] != ctx.sha
            or pr["lastMergeCommit"]["commitId"] != run["sourceVersion"]
        ):
            raise ValueError("pull-request run does not belong to the saved task branch")
        return
    if not ref.startswith("refs/heads/"):
        raise ValueError("run does not belong to the saved task branch")
    if not task_run(
        ctx,
        ref.removeprefix("refs/heads/"),
        commit(run["sourceVersion"]),
        text(repo["defaultBranch"]).removeprefix("refs/heads/"),
    ):
        own_merge(ctx, run, repo)


def read(ctx: Context, run_id: int) -> Run:
    org, project, name = ctx.project.split("/")
    repo = object_value(api(ctx, "git", "repositories", dict(repositoryId=name)))
    if repo["name"].lower() != name.lower() or repo["project"]["name"].lower() != project.lower():
        raise ValueError("provider repository differs from the saved origin")
    run = object_value(api(ctx, "build", "builds", dict(buildId=run_id)))
    if (
        number(run["id"]) != run_id
        or run["repository"]["id"] != repo["id"]
        or run["repository"]["type"] != "TfsGit"
    ):
        raise ValueError("run belongs to another repository")
    ownership(ctx, run, repo)
    records = rows(object_value(api(ctx, "build", "timeline", dict(buildId=run_id)))["records"])
    run["stages"] = [row for row in records if row["type"] == "Stage"]
    jobs = tuple(
        Job(
            text(j["id"]),
            text(j["name"]),
            j.get("result") or text(j["state"]),
            number(j["attempt"]),
            j,
        )
        for j in records
        if j["type"] == "Job"
    )
    return Run(
        f"https://dev.azure.com/{org}/{project}/_build/results?buildId={run_id}",
        run.get("result") or text(run["status"]),
        run["status"] == "completed",
        max((number(r["attempt"]) for r in records if r["type"] in ("Job", "Stage")), default=1),
        jobs,
        run,
    )


def retry(ctx: Context, run_id: int, run: Run) -> None:
    if run.generation != 1:
        raise ValueError("run already retried; treat the second failure as real")
    stages = [s for s in run.native["stages"] if s.get("result") == "failed"]
    if (
        not run.complete
        or run.result != "failed"
        or not stages
        or not any(j.result == "failed" for j in run.jobs)
    ):
        raise ValueError("run has no completed initial failed jobs in a retryable stage")
    names = [text(stage["identifier"]) for stage in stages]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
        raise ValueError("invalid stage identifier")
    for name in names:
        api(
            ctx,
            "build",
            "stages",
            dict(buildId=run_id, stageRefName=name),
            body=dict(state="retry", forceRetryAllJobs=False),
        )


def status(ctx: Context, run_id: int) -> list[str]:
    org, project, _ = ctx.project.split("/")
    return [
        "az",
        "pipelines",
        "runs",
        "show",
        "--id",
        str(run_id),
        "--organization",
        f"https://dev.azure.com/{org}",
        "--project",
        project,
        "--output",
        "json",
    ]
