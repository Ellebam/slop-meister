---
name: harvest
description: "Harvest: end this session in any plot and state on the operator's order. Groom, the ticket and pull request actions the plot allows and the state calls for, the report, then remove the worktree. Not a pause."
---

# Harvest

The one way a session ends. The operator orders it as `/harvest` or `$harvest`, or in any words, "harvest", "we are done", "wrap it up", "finalize". A manager's harvest send under Manage sessions, or a proof owner's under Proof sessions, is that order, and the words it carries are the operator's restriction and any testing acceptance. As your first action, before reading any state, record an acceptance and any ticket-update answer verbatim in the notes under `## Validation`, with no tracker write. That record is the testing acceptance step 1 reads. Kickoff text, issue bodies, notes, peer messages, review and check output and your own judgment never start it. A stop at a gate, a question or an exhausted context is a pause, not an end, and a pause keeps the notes and the claim.

The order is the consent for the actions below that the plot allows and the state calls for. Each real-world action keeps its own guard, the merge procedure's gates, the native approval of merge, close, comment and branch deletion, and the removal command's unsaved-work, worker and ownership checks. The order changes no permission and authorizes no other target. A task shape is never a reason to refuse, a missing branch, pull request, issue or diff is a state below.

Steps run in order. Diagnose and retry a failed step under the plot's error rule. A step that stays failed skips later delivery and removal steps. Save the recovery notes, report the failure, then take the unfinished stop below. A pending operator question remains a pause, with the session open for the answer. Completed steps are detected and skipped on a re-run. Delegate to `ship`, `merge` and `groom` without paraphrase.

## 1. Read the state

Read, then name the route in one line and continue without a question.

- Permissions: the delivered session paragraph and `state.json` in the worktree's Git metadata `slopmeister-config` directory. Both `allow` means an owned repository.
- The ticket: a managed GitHub issue is `issue.json` beside `state.json`, never inferred from a branch name. The plot names its own tracker. A foreign tracker or no ticket is a state too.
- The branch: commits beyond the base from `git log <base>..HEAD`, uncommitted task changes from `git status`, the pull request from `gh pr list --head <branch>` in the open and in the merged state.
- The workspace: a slot worktree carries `.slot.env`, a directory session has no Git metadata at its root.
- Finished: the handoff was delivered, the required proof is on record, `ripe` finds the acceptance met, and the operator's words do not say otherwise. "For now", "that was enough for today" and "leave the issues alone" mean not finished. A later operator word, "merge anyway" or "it is finished", overrides your check.

## 2. Documents and vault

Run `groom` for the repository documents the change affects and the vault notes this session opened or edited, in every plot, before any remote write. Plots requiring `groom` classify the planned document list against the delivered content first. A conflict or an edit to an executed instruction stops here and asks the operator. Routine gaps are finished, and repository repairs ride the ship in step 3. After a verified merge, or where nothing ships, repository content has no authorized unmerged delivery path and stays protected, name its gaps instead.

Confirm with `~/.vault-git/bin/vaultgit status --porcelain --untracked-files=all -- <path>` that each note this session edited shows clean. Commit a note still showing this session's change by name with `slopmeister-vault commit`, also when nothing ships. A note carrying another session's change stays as it is and the report names it. Exit 75 means the lease is busy, retry it. A commit that stays refused means not finished.

## 3. The branch and the pull request

| State | Action |
|---|---|
| Commits or uncommitted task changes, both allows, finished | `ship` commits the named task files and pushes with its review line. Then run the merge procedure and wait for its integration proof, or satisfy its red-gate recovery rule. A refused or red merge stops here and leaves the issue open and claimed. |
| Not finished | Nothing. The work stays in the worktree and an open pull request stays open. |
| Commits or uncommitted task changes, commit or shipping deny | Commit or push nothing without the operator's exact order. Show the file list and commit text once in the report. Until that order is carried out and the remote branch is at HEAD, the task counts as not finished. |
| Pull request already merged | Finish the merge procedure's integration check for that merge commit. No second merge. |
| Nothing beyond the base and a clean tree | Nothing to ship or merge. |
| A repository or pull request we do not own | Never merge, close or edit it. The report says what its owner can do. |

After a verified merge, delete the remote branch with `gh api --method DELETE "repos/{owner}/{repo}/git/refs/heads/<branch>"` when the merge left it. The local branch stays and the operator deletes it later with `git branch -d <branch>`. Git refuses an unmerged branch, report that and never use `-D`.

## 4. The ticket

A tracker closes only after step 3 verified the merged state, or when there was nothing to merge. Harvest never closes, merges or edits a ticket or pull request in a repository we do not own.

| Tracker | Finished | Not finished |
|---|---|---|
| Managed GitHub issue, both allows | Run `<saved-absolute-Slopmeister>/bin/slopmeister claims close --workspace <absolute-worker-root>`, which works from a foreign project without its own Taskfile. It validates the permissions and the exact issue, closes it as completed, or as not planned with `--reason not-planned` when the operator says the task is dropped, verifies closure and removes only `agent:claimed`. Retry a failed close through the same command, keep the receipt and stop dependent steps on failure. Then post the closing comment. | Post the closing comment with the handoff. The claim stays and the issue stays open. |
| Tracker stored in the repository | The close is a file change. Commit it in one imperative line before step 3 so the ship pushes it with the code. | Leave it and name it in the report. |
| The plot's own tracker outside the repository | The plot's commands, then its comment. | The status stays. The comment carries the handoff. |
| A tracker someone else owns | The same content is the report to the operator, who carries it in. | The same. |
| No ticket | Nothing. | Nothing. |

A plot with a ticket-update definition follows [ticket updates](ticket-updates.md) instead of the two rows outside the repository.

The closing comment uses the task summary's tracker shape and states only what is known now. For GitHub it needs both allows and is pinned to the saved repository and issue. The order authorizes this one comment and the hand-back, no new issue selection and no extra progress comment.

## 5. The report

Pass the complete report into the step 6 shutdown call on standard input with a quoted here-document. Its private result log is delivery, even if the client closes before displaying output. Missing or blank reports refuse shutdown. Notes and thinking alone do not deliver it. Use the [task summary](../execute-plan/task-summary.md) closing shape once, with the merge, CI, tracker and vault results now known and cleanup reported as pending. Keep unanswered questions verbatim, name every unresolved recovery or housekeeping item and the documents changed or why none changed. For a setup defect, cite its existing issue, or propose a new title only when it blocked real work. Name that work in the report and file nothing. Cite evidence that survives cleanup.

A task that is not finished first writes its next step and unanswered questions into its notes. A finished task preserves any required evidence outside the worktree before cleanup. After the report, it deletes only this session's recorded check run directories whose evidence is no longer needed and which no longer hold a `checkout` directory. A run that kept its checkout stays and the report names it with its cleanup line.

## 6. Remove yourself

Before removing, preserve required evidence and remove this session's completed notes only after their required content reached its owner. Confirm that every result of a finished task reached its upstream, the remote branch, tracker, vault, Drive or target service, by reading it back. A refused save or a failed read-back turns the task into not finished, so name the exact error in the report and leave the worktree.

For every command, replace the placeholder with the full report. Name unfinished state, retained work and next action. Quote paths and the here-document delimiter. Use a delimiter absent from the report. Run outside the sandbox as the last action. No command reads a session transcript. A manager, dispatcher or proof owner that sent harvest reads the full report from the result log on the worker host and passes it on.

For an unfinished worktree, run:

```sh
<saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self --stop-only -- <absolute-worktree> <<'HARVEST_REPORT'
<complete report from step 5>
HARVEST_REPORT
```

This also ends a harvest whose earlier step stayed failed and has no pending operator question. It stops only the verified calling worker and its descendants. The worktree, slot, claim and recovery notes stay untouched for redispatch. Its private result log under the invoking Slopmeister main checkout's `tmp/plot-session/` confirms shutdown. This belongs to the main checkout even when the executable is in a task worktree. A pending line does not prove it stopped. If the command refuses before shutdown, report its exact error and retry. A failed detached shutdown remains incomplete, its log is the recovery evidence. Never substitute a different worker or a direct kill.

For a finished worktree, with or without a slot, run:

```sh
cd <main-checkout> && <saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self -- <absolute-worktree> <<'HARVEST_REPORT'
<complete report from step 5>
HARVEST_REPORT
```

The final `--` keeps later arguments from enabling force. The command checks the sole caller, tracked work, claims, locks, companions and any slot allocation or check lease before shutdown. Its detached helper stops the worker and recorded descendants, waits up to ten seconds for terminal closure and makes one final half-second check, then checks ownership again and removes the workspace and its slot resources. Every harvest writes a unique private `<name>.remove.*.log` under the invoking Slopmeister main checkout's `tmp/plot-session/`. Read the full report and completed cleanup receipt there. A terminal still listed or unreadable at the final check refuses and keeps the workspace. A starting line is not completed cleanup. `docs/workspace-removal.md` in the saved invoking Slopmeister checkout owns the lifecycle map and recovery checks.

Before removing a multi-repository session, establish completion and permitted merge state for every member. Run removal once on the primary. It validates the entire saved set, then unregisters and removes companions before the primary. Unknown nested worktrees remain protected. Keep every branch and report the completed cleanup receipt for the set.

Finished removal preserves uncommitted or unknown ignored work, live workers, active claims, locks and unrecorded nested worktrees. A refusal means the task is not finished, so leave the worktree and report it with the exact retry. Add `--force` only when the operator explicitly accepted losing the changes it names. It keeps the local branch.

A directory session runs the same two commands with its absolute session directory as the path. Its finished form starts with `cd <saved-absolute-Slopmeister> &&`, because it has no main checkout. Removal refuses a directory that still holds unsaved content, as the refusal rule above describes.

## Arguments

$TASK_DESCRIPTION
