---
description: "Retry initially failed CI jobs once for the session's task branch or exact own merge, then report their result."
---

# CI rerun

Use the fixed command for a suspected transient CI failure. It supports GitHub Actions, GitLab CI and Azure DevOps Pipelines. It finds the provider from the saved repository remote and uses its existing authenticated client, `gh`, `glab` or `az` with the azure-devops extension. Missing clients or access stop the command. Do not install tools or change authentication without the operator's order.

```bash
python3 <workspace>/.claude/skills/ci-rerun/scripts/ci_rerun.py --run <run-id>
```

The numeric run ID identifies an existing pipeline run. The command verifies its fixed configuration and saved task identity before provider access. It refuses another repository or task branch. It never starts a pipeline, cancels a run or changes settings. It permits one retry of initial failures and reports another failure as real. Do not repeat a refused or uncertain write.

The command prints the run link, requested jobs, final restarted jobs and their results. If CI exceeds the 90-second deadline, use the printed read-only status command to obtain the final result. Do not invoke the retry command again to read status.

## Scope and provider behavior

The task branch and its current commit must match the saved repository. A default-branch run is allowed only for this task's exact merge commit and its push trigger. The command checks the merged pull request or merge request, its source repository, task branch and head commit. Scheduled and manual default-branch runs are refused. Use `--cwd <member-workspace>` only for another recorded repository in the same session.

GitHub uses the failed-job rerun endpoint. It also restarts dependent jobs. GitLab retries individual failed build jobs, which can release skipped later jobs. It does not retry cancelled jobs or bridge jobs that start another pipeline. Azure retries failed stages with `forceRetryAllJobs=false`. Azure also restarts dependent jobs. The output reports all observed restarted or released jobs. These are the providers' native retry semantics.

The command has no pipeline dispatch, cancellation, setting, payload, endpoint or retry-limit options. Its CI-only authority applies to ordinary repository sessions independently of push and pull-request shipping permission. Directory and proof sessions cannot rerun CI. A manager should ask the owning task session for a routine CI retry before any refusal. A refused action must go to the operator with its one `!` command. Never move it between sessions.
