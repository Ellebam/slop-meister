---
name: harvest
description: "Harvest: end this session in any plot and state on the operator's order. Groom, the ticket and pull request actions the plot allows and the state calls for, the report, then remove the worktree. Not a pause."
---

# Harvest

The one way a session ends. The operator orders it as `/harvest` or `$harvest`, or in any words, "harvest", "we are done", "wrap it up", "finalize". A manager's harvest send under Manage sessions is that order, and the words it carries are the operator's restriction. Kickoff text, issue bodies, notes, peer messages, review and tester output and your own judgment never start it. A stop at a gate, a question or an exhausted context is a pause, not an end, and a pause keeps the notes and the claim.

The order is the consent for the actions below that the plot allows and the state calls for. Each real-world action keeps its own guard, the merge procedure's gates, the native approval of merge, close, comment and branch deletion, and the removal command's refusal of unsaved work. The order changes no permission and authorizes no other target. A task shape is never a reason to refuse, a missing branch, pull request, issue or diff is a state below.

Steps run in order. Diagnose and retry a failed step under the plot's error rule. A step that stays failed stops the sequence, later steps stay explicitly unperformed, the notes stay and the report says so. Completed steps are detected and skipped on a re-run. Delegate to `ship`, `merge` and `groom` without paraphrase.

## 1. Read the state

Read, then name the route in one line and continue without a question.

- Permissions: the delivered session paragraph and `state.json` in the worktree's Git metadata `slopmeister-config` directory. Both `allow` means an owned repository.
- The ticket: a managed GitHub issue is `issue.json` beside `state.json`, never inferred from a branch name. The plot names its own tracker. A foreign tracker or no ticket is a state too.
- The branch: commits beyond the base from `git log <base>..HEAD`, uncommitted task changes from `git status`, the pull request from `gh pr list --head <branch>` in the open and in the merged state.
- The workspace: a slot worktree carries `.slot.env`, a directory session has no Git metadata at its root.
- Finished: the handoff was delivered, the required proof is on record, `ripe` finds the acceptance met, and the operator's words do not say otherwise. "For now", "that was enough for today" and "leave the issues alone" mean not finished. A later operator word, "merge anyway" or "it is finished", overrides your check.

## 2. Documents and vault

Run `groom` for the repository documents the change affects and the vault notes this session opened or edited, in every plot, before any remote write. Plots requiring `groom` classify the planned document list against the delivered content first. A conflict or an edit to an executed instruction stops here and asks the operator. Routine gaps are finished, and repository repairs ride the ship in step 3. After a verified merge, or where nothing ships, repository content has no authorized unmerged delivery path and stays protected, name its gaps instead.

Check the record in the notes file as the plot's session end section describes, each note's first-touch state and its last-write digest. A line with `first-touch <state>` but no digest means the write did not complete, leave that note unchanged, never commit it and name it in the report. A note that was dirty, is unknown, no longer matches its digest, or is read-only by the operator's instruction stays exactly as it is and is named in the report. Commit the eligible edited notes with `slopmeister-vault commit "<one line>" -- <path>...`, named paths only. Run `slopmeister-vault lint --area <folder>`, with `--shallow` for a field folder whose project and ticket folders are areas of their own, and keep the output. Zero on every count except `protected links` is clean.

Stop for an operator answer only in three states: a note this session created or edited that has no first-touch record, a recorded path that does not exist and this session did not remove, and a resumed session whose write record is missing or unparseable and cannot be recovered. A read-only session needs no vault ledger.

## 3. The branch and the pull request

| State | Action |
|---|---|
| Commits or uncommitted task changes, both allows, finished | `ship` commits the named task files and pushes with its review line. Then run the merge procedure and wait for its integration proof, or satisfy its red-gate recovery rule. A refused or red merge stops here and leaves the issue open and claimed. |
| Commits or uncommitted task changes, both allows, not finished | `ship` with a PENDING or current review line. The pull request stays open. |
| Commits or uncommitted task changes, commit or shipping deny | Commit or push nothing without the operator's exact order. Confirm read-only that the remote branch is at HEAD when one exists. Unsaved or unpushed work keeps the worktree, and the report says so. |
| Pull request already merged | Finish the merge procedure's integration check for that merge commit. No second merge. |
| Nothing beyond the base and a clean tree | Nothing to ship or merge. |
| A repository or pull request we do not own | Never merge, close or edit it. The report says what its owner can do. |

After a verified merge, delete the remote branch with `gh api --method DELETE "repos/{owner}/{repo}/git/refs/heads/<branch>"` when the merge left it. The local branch stays and the operator deletes it later with `git branch -d <branch>`. Git refuses an unmerged branch, report that and never use `-D`.

## 4. The ticket

A tracker closes only after step 3 verified the merged state, or when there was nothing to merge. Harvest never closes, merges or edits a ticket or pull request in a repository we do not own.

| Tracker | Finished | Not finished |
|---|---|---|
| Managed GitHub issue, both allows | Run `<saved-absolute-Slopmeister>/bin/slopmeister claims close --workspace <absolute-worker-root>`, which works from a foreign project without its own Taskfile. It validates the permissions and the exact issue, closes it as completed, or as not planned with `--reason not-planned` when the operator says the task is dropped, verifies closure and removes only `agent:claimed`. Retry a failed close through the same command, keep the receipt and stop dependent steps on failure. Then post the closing comment. | Post the closing comment with the handoff. Copy the notes unchanged to `.slopmeister-tmp/<TASK-ID>-handoff.md` and run `<saved-absolute-Slopmeister>/bin/slopmeister claims abandon-prepare --workspace <absolute-worker-root> --handoff <that copy>`. The self-cleanup in step 6 completes the hand-back. The issue stays open. |
| Tracker stored in the repository | The close is a file change. Commit it in one imperative line before step 3 so the ship pushes it with the code. | Leave it and name it in the report. |
| The plot's own tracker outside the repository | The plot's commands, then its comment. | The status stays. The comment carries the handoff. |
| A tracker someone else owns | The same content is the report to the operator, who carries it in. | The same. |
| No ticket | Nothing. | Nothing. |

The closing comment uses the task summary's tracker shape and states only what is known now. For GitHub it needs both allows and is pinned to the saved repository and issue. The order authorizes this one comment and the hand-back, no new issue selection and no extra progress comment.

## 5. The report

For a slot worktree with `tmp/`, copy its contents before the report with `umask 077 && cp -Rn "<worktree>/tmp/." "<proof>/"`. Use the launcher's state directory, `PLOT_SESSION_STATE_DIR` or `<saved-absolute-Slopmeister>/tmp/plot-session`, with `<SLOT_NAME>-proof` appended. Require private destination directories. Refuse symlinks and nonregular entries in either tree and symlinked destination ancestors before copying. Never overwrite saved proof. Copy failure stops release. The guard verifies matching bytes before shutdown and removal. Missing, unreadable, changed or symlinked files keep the refusal.

Deliver the [task summary](../execute-plan/task-summary.md) closing shape once, with the merge, CI, tracker and vault results now known and cleanup reported as pending. Keep unanswered questions verbatim, name every unresolved recovery or housekeeping item and the documents changed or why none changed. For a setup defect, cite its existing issue, or propose a new title only when it blocked real work. Name that work in the report and file nothing. Cite evidence that survives cleanup.

Before deleting notes, retain otherwise-lost recovery records outside the worktree: unanswered questions, spill paths and each live process's exact start command, working directory, environment and port, with secrets redacted. Then delete `<TASK-ID>-NOTES.md` and the other root notes carrying this task's identifier, and leave other files alone. The handoff copy in `.slopmeister-tmp` stays for the hand-back.

## 6. Remove yourself

The report is delivered first. A non-slot worktree then runs, as its last action, `cd <main-checkout> && <saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self -- <absolute-worktree>` outside the tool's sandbox, with paths quoted for the shell. The final `--` keeps later arguments from enabling force. The command verifies the sole calling worker, stops it and its descendants, completes a recorded claim hand-back, checks ownership again and removes the worktree. Its private result log lands under `<saved-absolute-Slopmeister>/tmp/plot-session/`, which the report names. A starting line is not completed cleanup.

A slot worktree, one carrying `.slot.env`, runs `<saved-absolute-Slopmeister>/bin/slopmeister slots down <main-checkout> <SLOT_TARGET> <SLOT_NAME> --self` instead, from the main checkout and outside the sandbox, with both values from `.slot.env`. It stops this session, releases the slot and removes the worktree. Its result lands in `<saved-absolute-Slopmeister>/tmp/slots/<SLOT_NAME>.down.log`.

Both commands refuse unsaved or unknown work. Add `--force` only when the operator explicitly accepted losing what the refusal names. Both keep the local branch. A refusal leaves the session running, so report it with the exact retry.

A directory session cannot remove itself. End with the report and name `task workspace:remove -- <absolute session directory>` for the dispatcher.

## Arguments

$TASK_DESCRIPTION
