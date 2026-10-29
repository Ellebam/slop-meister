# Issue ownership

GitHub records whether work is owned. A worker waiting for an operator decision still owns its issue.

| GitHub state | Meaning |
|---|---|
| Open, no claim or blocker | Available |
| `agent:claimed` | A delivered worker owns the issue |
| `blocked` or an open native blocked-by dependency | External progress is unavailable |
| Closed | Done |

Ownership and blocking can coexist. Reports show both. Use native GitHub blocked-by relationships for exact issue dependencies and `blocked` for other external impediments. A closed dependency is resolved, including one closed as not planned. Existing `priority:high` orders available recommendations; type labels describe the work. No workflow-step labels are needed.

For a remote worker, inspect and reconcile claims in its owning host's repository. The [remote-dispatch process](remote-dispatch.md#recover-on-the-owning-machine) gives the route.

## Non-GitHub backlog reports

For a vault/manual plot declaring `jira-read`, a fresh dispatcher uses that plot's approved reader and fixed machine-local profile query. Report available, blocked and unknown tickets with summary/status and named blocking tickets. An open blocked-by relationship blocks a ticket, an outward blocks relationship does not block that ticket, and a done blocker is resolved. Missing or ambiguous relationship/status evidence is unknown. Dependencies outside the query still count, and an unreadable profile or failed provider read never becomes an empty or available backlog. Report incomplete windows and account visibility limits.

Vault notes supply context, not a fallback live backlog. The reader also handles a named Jira ticket and its links through the same approved path. This adds no Jira claim, status transition or other tracker write. GitHub ownership below keeps its existing route and permissions. See [service actions](service-actions.md#dispatcher-jira-reads) for delivery, profile provisioning and native approval.

## Operator flow

Run these templates from the invoking Slopmeister checkout, replacing the paths, plot, number and name. In another project, use `task --dir <absolute-slopmeister-root>` before the task name.

1. Ask for the backlog: `task issue:claims -- backlog --repo <project-root> --plot <plot> --json`. This reads only. Report available, claimed, blocked and unknown issues, including drift. Recommend only the returned available issue numbers.
2. Dispatch the issue using [Choose the worker command](../src/skills/plot-session/dispatcher.md#choose-the-worker-command). Keep `--issue-id <number> --tool claude --model <model>` on the selected command. Pipe the kickoff on stdin. Use `--tool codex` for Codex. The brief starts with its `Mode:` line. Alternatively, `--issue <number>` fetches and associates that issue. A custom brief without `--issue-id` never selects a ticket from its text or name.
3. Pause for a frame, plan, review or testing decision. Leave the claim in place. Save the handoff before planned replacement, then use `task plot-session -- <project-root> <plot> <name> --redispatch --tool <tool> < kickoff.md`. The saved association and claim remain, with no duplicate label transition.
4. To abandon explicitly, first save a nonempty handoff with recovery commands inside the worker workspace. Run `task plot-session -- <project-root> <plot> <name> --abandon --handoff <absolute-task-notes> --tool <tool>`. Exact worker inspection precedes closure. The issue stays open, its claim is released, and the workspace and handoff remain. Retry interrupted abandonment with the same unchanged handoff. An already released claim makes abandonment a no-op, even if a later session occupies that workspace.
5. After accepted testing, order `harvest`. After the merge is verified, its owned-tracker path closes the saved issue, verifies closure and removes the claim. A refused merge leaves the issue open and claimed. It uses `<saved-absolute-slopmeister-root>/bin/slopmeister claims close --workspace <worker-root>`, so the project needs no Slopmeister Taskfile. The close reason is `completed`, and `--reason not-planned` records a dropped task. A failed close preserves recovery evidence and can be retried. The verified finishing worker does not block unrelated dispatch while session closure completes.

To harvest unfinished work, preserve a nonempty handoff inside the workspace's recorded scratch directory. Harvest records `abandon-prepare`; self-cleanup stops the sole worker before `abandon-complete` releases its claim. A changed, outside, linked or nonregular handoff refuses release. A retained workspace keeps its notes and active claim. No new issue is selected.

## Permission and authorization

GitHub repository plots use their existing commit and shipping `allow` declarations for project eligibility. There is no new permission knob. Task retrieval, repository access or commit permission alone never authorizes issue mutation. Saved workspace permissions remain fixed on redispatch.

The explicit operator request or invoked workflow authorizes its prescribed action. Dispatch authorizes claiming its delivered issue. Harvest authorizes its prescribed closure or hand-back and comment. No second consent question is needed for those actions. Permission alone authorizes none of them. Denied plots and non-GitHub task sources perform no tracker writes.

Autonomous issue selection needs a separate operator kickoff naming the exact repository, eligible issue set or filters, concurrency bound and stopping condition. Paused claimed workers count against the bound. A backlog question grants no dispatch authority. See the [kickoff contract](contracts.md#authorize-bounded-selection).

## Inspect and recover

An automatic launch observes any requested model before it claims, and a missing model stops it before any tracker write. Requested aliases may resolve to a different reported model name, which the launcher reports for the dispatcher to judge. The claim itself proves only that the exact native worker received the saved kickoff, whatever order its record logs model and kickoff rows in. Failure or uncertain delivery creates no new claim. If GitHub fails after delivery, the launcher reports `worker delivered, claim unconfirmed`, preserves the worker and saves unresolved ownership. The local backlog reports unknown and recommends no replacement.

Inspect with `task issue:claims -- inspect --workspace <worker-root>`. After inspecting the exact repository, issue, workspace and native identity, explicitly complete a known failed claim with `task issue:claims -- reconcile --workspace <worker-root>`. Reconciliation verifies saved delivery and refuses a conflicting owner. A changed kickoff or missing attributable evidence needs recovery, not an invented success receipt. A failed redispatch without bound delivery reports unknown, retains the GitHub claim and needs an explicitly verified redispatch.

Legacy workers without a saved association remain unmapped. After inspecting the existing worker, associate it without restarting it: `task issue:claims -- reconcile --workspace <worker-root> --issue-id <number> --kickoff <saved-kickoff-file> --tool <tool> --pid <worker-pid> --session <native-session-id> --evidence <native-transcript>`. Use the original launcher output and saved native records for these values. Recovery checks the saved configuration, current worker identity and exact delivered kickoff before claiming. It judges no model, because reconciling is the dispatcher's recovery decision. Recover multiple legacy workers one at a time with their respective explicit issues. An unresolved worker is named in a warning and blocks no issue. An intentionally unassociated worker is never silently assigned a ticket or disregarded: finish it and preserve its handoff outside the active workspace before retiring that workspace explicitly. An existing GitHub claim with no verifiable local owner stays claimed until the operator inspects the owning workspace and explicitly recovers or releases it. A missing process alone never releases a claim. When the owning worktree is gone and you have confirmed that no worker owns the issue, release the orphaned label with `gh issue edit <number> --repo <owner>/<repo> --remove-label agent:claimed`.

Worktrees and processes never make an issue unknown. Only GitHub and the issue's own saved association decide its category. The backlog reports every other local finding in `warnings`, and each warning ends with `does not block dispatch`. That covers a live worker or task notes in a worktree without an active association, a bare leftover worktree, a finishing worker, a worktree that cannot be inspected and a registered worktree whose directory is missing. A worktree whose directory is missing, replaced or no longer linked to Git keeps its saved association until Git discards the registration, through `git worktree prune` or a forced `git worktree add`. An unconfirmed claim there still keeps its own issue unknown. A claimed worktree is read from its saved association and the GitHub claim, whichever process runs in it, including a session resumed by hand. Claim, reconcile and abandon still require the exact delivered process. A saved association that cannot be read or validated is the one local finding that stops the backlog and every dispatch in that repository, because it may hide an owner.

Only `agent:claimed` is created or added, without rewriting existing label definitions, issue bodies or progress comments. Its one local association lives beside the launcher's existing worktree configuration. There is no second task database or background service.

A per-issue lock serializes dispatch and lifecycle actions across linked worktrees in one repository. GitHub labels provide shared visibility across computers. Independent clones can still race before either claim becomes visible, and another computer cannot see a failed write recorded only locally. This mechanism does not promise atomic distributed reservation.
