"""GitHub's failed-job endpoint, pinned to the saved repository and task commit."""

import json

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
    result = ctx.command("gh", "api", "--hostname", ctx.host, "--method", method, endpoint)
    return json.loads(result) if result else None


def own_merge(ctx: Context, run: dict, default: str) -> None:
    head = encoded(ctx.project.split("/")[0] + ":" + ctx.branch)
    endpoint = f"repos/{ctx.project}/pulls?state=closed&head={head}"
    pulls = pages(lambda path: api(ctx, path), endpoint)
    matches = [
        pr
        for pr in pulls
        if pr.get("merged_at")
        and pr.get("merge_commit_sha") == run["head_sha"]
        and pr["head"]["ref"] == ctx.branch
        and pr["head"]["sha"] == ctx.sha
        and pr["head"]["repo"]["full_name"] == ctx.project
        and pr["base"]["repo"]["full_name"] == ctx.project
        and pr["base"]["ref"] == default
    ]
    if run["event"] != "push" or len(matches) != 1:
        raise ValueError("default-branch run is not this task's exact merge push")


def read(ctx: Context, run_id: int) -> Run:
    repo = object_value(api(ctx, f"repos/{ctx.project}"))
    if repo["full_name"].lower() != ctx.project.lower():
        raise ValueError("provider repository differs from the saved origin")
    run = object_value(api(ctx, f"repos/{ctx.project}/actions/runs/{run_id}"))
    if (
        number(run["id"]) != run_id
        or run["repository"]["id"] != repo["id"]
        or run["head_repository"]["id"] != repo["id"]
    ):
        raise ValueError("run belongs to another repository")
    default = text(repo["default_branch"])
    if not task_run(ctx, text(run["head_branch"]), commit(run["head_sha"]), default):
        own_merge(ctx, run, default)
    values = pages(
        lambda path: api(ctx, path),
        f"repos/{ctx.project}/actions/runs/{run_id}/jobs?filter=latest",
        "jobs",
    )
    jobs = tuple(
        Job(
            str(number(j["id"])),
            text(j["name"]),
            j.get("conclusion") or text(j["status"]),
            number(j["run_attempt"]),
            j,
        )
        for j in values
    )
    return Run(
        f"https://{ctx.host}/{ctx.project}/actions/runs/{run_id}",
        run.get("conclusion") or text(run["status"]),
        run["status"] == "completed",
        number(run["run_attempt"]),
        jobs,
        run,
    )


def retry(ctx: Context, run_id: int, run: Run) -> None:
    if run.generation != 1:
        raise ValueError("run already retried; treat the second failure as real")
    if (
        not run.complete
        or run.result != "failure"
        or not any(j.result in ("failure", "timed_out") for j in run.jobs)
    ):
        raise ValueError("run has no completed initial failed jobs")
    api(ctx, f"repos/{ctx.project}/actions/runs/{run_id}/rerun-failed-jobs", "POST")


def status(ctx: Context, run_id: int) -> list[str]:
    return ["gh", "run", "view", str(run_id), "--repo", f"{ctx.host}/{ctx.project}"]
