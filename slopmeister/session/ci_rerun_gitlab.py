"""Retry failed GitLab build jobs, excluding pipeline and bridge retry endpoints."""

from collections import Counter
import json
import re

from slopmeister.session.ci_rerun_common import (
    Context,
    Job,
    Run,
    commit,
    encoded,
    number,
    object_value,
    pages,
    task_run,
    text,
)


def api(ctx: Context, endpoint: str, method: str = "GET"):
    value = ctx.command("glab", "api", "--hostname", ctx.host, "--method", method, endpoint)
    return json.loads(value) if value else None


def merge_matches(ctx: Context, mr: dict, project: dict, sha: str, default: str) -> bool:
    result = mr.get("merge_commit_sha") or mr.get("squash_commit_sha") or mr.get("sha")
    return (
        mr.get("state") == "merged"
        and result == sha
        and mr["sha"] == ctx.sha
        and mr["source_branch"] == ctx.branch
        and mr["target_branch"] == default
        and mr["source_project_id"] == project["id"] == mr["target_project_id"]
    )


def ownership(ctx: Context, run: dict, project: dict) -> None:
    default = text(project["default_branch"])
    ref, sha = text(run["ref"]), commit(run["sha"])
    if task_run(ctx, ref, sha, default):
        return
    endpoint = (
        f"projects/{project['id']}/merge_requests?state=merged&source_branch={encoded(ctx.branch)}"
    )
    matches = [
        mr
        for mr in pages(lambda path: api(ctx, path), endpoint)
        if merge_matches(ctx, mr, project, sha, default)
    ]
    if run["source"] != "push" or len(matches) != 1:
        raise ValueError("default-branch run is not this task's exact merge push")


def mr_ownership(ctx: Context, run: dict, project: dict) -> None:
    ref = text(run["ref"])
    match = re.fullmatch(r"refs/merge-requests/([0-9]+)/(?:head|merge)", ref)
    if run["source"] != "merge_request_event" and not match:
        ownership(ctx, run, project)
        return
    endpoint = f"projects/{project['id']}/merge_requests?source_branch={encoded(ctx.branch)}"
    candidates = [
        mr
        for mr in pages(lambda path: api(ctx, path), endpoint)
        if mr["source_branch"] == ctx.branch
        and mr["sha"] == ctx.sha
        and mr["source_project_id"] == project["id"] == mr["target_project_id"]
    ]
    matches = [
        mr
        for mr in candidates
        if any(
            number(p["id"]) == run["id"]
            for p in pages(
                lambda path: api(ctx, path),
                f"projects/{project['id']}/merge_requests/{number(mr['iid'])}/pipelines",
            )
        )
    ]
    if len(matches) != 1:
        raise ValueError("merge-request run does not belong to the saved task branch")
    iid = number(matches[0]["iid"])
    if ref not in (
        ctx.branch,
        f"refs/merge-requests/{iid}/head",
        f"refs/merge-requests/{iid}/merge",
    ):
        raise ValueError("merge-request run does not belong to the saved task branch")


def read(ctx: Context, run_id: int) -> Run:
    project = object_value(api(ctx, f"projects/{encoded(ctx.project)}"))
    if project["path_with_namespace"].lower() != ctx.project.lower():
        raise ValueError("provider repository differs from the saved origin")
    prefix = f"projects/{number(project['id'])}/pipelines/{run_id}"
    run = object_value(api(ctx, prefix))
    if number(run["id"]) != run_id or run["project_id"] != project["id"]:
        raise ValueError("run belongs to another repository")
    current = pages(lambda path: api(ctx, path), prefix + "/jobs?include_retried=false")
    history = pages(lambda path: api(ctx, path), prefix + "/jobs?include_retried=true")
    counts = Counter((text(j["name"]), text(j["stage"])) for j in history)
    run["jobs"] = current
    if any(job.get("tag") is not False for job in current):
        raise ValueError("tag jobs are not task branch jobs")
    mr_ownership(ctx, run, project)
    jobs = tuple(make_job(row, counts, run_id) for row in current)
    result = text(run["status"])
    return Run(
        f"https://{ctx.host}/{ctx.project}/-/pipelines/{run_id}",
        result,
        result in ("success", "failed", "canceled", "skipped", "manual"),
        max((j.attempt for j in jobs), default=1),
        jobs,
        run,
    )


def make_job(row: dict, counts: Counter, run_id: int) -> Job:
    if number(row["pipeline"]["id"]) != run_id:
        raise ValueError("job belongs to another pipeline")
    key = (text(row["name"]), text(row["stage"]))
    return Job(str(number(row["id"])), key[0], text(row["status"]), number(counts[key]), row)


def retry(ctx: Context, run_id: int, run: Run) -> None:
    if run.generation != 1:
        raise ValueError("run already retried; treat the second failure as real")
    failed = [job for job in run.jobs if job.result == "failed"]
    if not run.complete or run.result != "failed" or not failed:
        raise ValueError("run has no completed initial failed jobs")
    for job in failed:
        response = object_value(
            api(ctx, f"projects/{run.native['project_id']}/jobs/{job.id}/retry", "POST")
        )
        if response["pipeline"]["id"] != run_id or number(response["id"]) == int(job.id):
            raise ValueError("retry response does not confirm a new job in this run; do not retry")


def status(ctx: Context, run_id: int) -> list[str]:
    return [
        "glab",
        "api",
        "--hostname",
        ctx.host,
        "--method",
        "GET",
        f"projects/{encoded(ctx.project)}/pipelines/{run_id}",
    ]
