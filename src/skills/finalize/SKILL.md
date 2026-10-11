---
description: "Finalize: ship, merge, close the task and clean up, in that order. The last spine step requires passed review and green CI or a proven CI-less bootstrap exception. Operator-typed."
disable-model-invocation: true
---

# Finalize

The operator-typed final step of the spine. Ship, merge, close the ticket and clean up, in that order. A GitHub issue closes only after its merge is verified, so a refused merge leaves the issue open and claimed. A tracker stored in the repository closes before the ship instead, because its close is a file change that rides the same push as the code. Steps run sequentially, diagnose and retry a failed step under the plot's error rule, and never continue to a dependent step past one that stays failed, stop and report instead.

The input is the explicit task identifier or the launcher's saved issue association. Never infer a managed issue association from the branch name.

Commands referenced here are the GitHub instantiation through `gh`. A project on another forge supplies its equivalents through its plot, the sequence and its gates do not change. Where the task lives in a tracker without a repository we can push to, finishing means the tracker and the vault records as the project's plot says, and the steps that need a branch do not apply.

## Endings

The default ending is a PR that this session merges. Two more exist. Use one when the operator's finalize message names it or when its condition below holds.

- A pushed PR that someone else reviews and merges, as in a plot whose shipping permission is deny. Run steps 1 and 2, then 5 to 8. In place of step 3, confirm read-only that the PR is open and the remote branch is at HEAD, and stop and report when it is not. Skip the merge, skip pre-flight's check gate and do not refuse on the `Independent review:` line, the review and the PR body belong to the PR's owner. Step 5 applies only to a managed GitHub issue in a repository we own and closes it as completed. Step 7 removes only the worktree and keeps both branches while the PR is open.
- A task with no diff, where the branch has no commit beyond its base and the tree is clean. Run steps 1 and 5 to 8, with no PR, ship or merge. Close a managed GitHub issue with `--reason not-planned` when the operator says the task is dropped, otherwise as completed.

Finalize never closes, merges or edits a pull request or a ticket in a repository we do not own. It closes an issue only through step 5, whose two routes both require the project's commit and shipping allow. Everywhere else the tracker action is close-out's report to the operator.

## Steps

### 1. Pre-flight

For a plot requiring `groom`, check the planned document list against the delivered repository content and vault notes before any remote command. A missing list, unjustified `none`, missing document or unmet action refuses and names the document or missing list. Check the content, not only file existence or Git status. Stop without document edits, retain the notes and ask the operator for direction. Documentation gaps are not retryable errors and this procedure never repairs them. Any authorized correction follows the existing proof, review and acceptance rules before finalization resumes.

On a re-run, when `gh pr list --head <branch> --state merged` shows this task's PR, the merge is done. Skip the PR gates below and steps 3 and 4, and resume at step 5.

Read the PR body's `Independent review:` line before anything writes to the tree. PASS or N/A, proceed. PENDING or missing, stop, except in the ending where someone else merges and in the no-diff ending, which has no PR. Check whether the review ran and only the line is stale, the ship step syncs it. If no review result exists, tell the operator it is owed. Catch this here, before a later step has deleted the notes.

Outside the no-diff ending, if no PR exists and CI is absent or uncertain, stop before any write. Ship the PR and obtain its operator authorization before finalizing. With CI configured, the ship step creates a missing PR with the right review line.

For an existing PR, run `gh pr checks <number>` before any document or tracker write. When zero checks are reported, apply merge's checks through the current-base comparison without branch, tracker or GitHub writes. A refusal stops finalize. Do not refresh the branch or merge during pre-flight. After ship, run merge afresh. If that later gate refuses, the issue stays open and claimed, report the blocked merge.

### 2. Project document duties

Plots requiring `groom` completed their document duties before review, so skip this step. For other plots, if the diff changed behaviour a project document describes, update that document to match. Search the project's docs for the touched paths and public symbols, if nothing references them, skip. Just make the documents true, no provenance bookkeeping.

### 3. Ship

Run the ship procedure, any remaining changes, confirm the branch is pushed, create the PR if it does not exist, report the URL.

### 4. Merge

Run the merge procedure. Pending or failed checks refuse, and zero checks use only its narrow bootstrap rule.

### 5. Close the task

A GitHub issue closes here, after step 4 verified the merged state or at an ending above. A close that changes files in the repository, a tracker stored there or a planning document, happens before step 3 instead and is committed explicitly in one imperative line, so the ship pushes it with the code.

1. Identify the ticket in the project's tracker and confirm the identifier, title and branch match. Not found, stop and ask, do not guess.
2. For a managed GitHub issue, read `issue.json` beside `state.json` in the worktree's Git metadata `slopmeister-config` directory and run `<saved-absolute-Slopmeister>/bin/slopmeister claims close --workspace <absolute-worker-root>`, using its saved Slopmeister path. This works from a foreign project without its own Slopmeister Taskfile. The command validates the existing permissions and exact issue, closes it, verifies closure and removes only `agent:claimed`. It closes as completed unless `--reason not-planned` is added. Retry failed completion through the same command; preserve the receipt and stop dependent steps on failure. Invoking finalize already authorizes these issue actions. For tasks without a managed association, use the existing owned-tracker route with the explicit identifier and repository after confirming the project's existing permissions; do not fabricate a claim receipt or guess an issue.
3. For plots requiring `groom`, planning-document changes belong to the reviewed list and this step writes none. For other plots, if the project keeps planning documents that name this task, surface the hits and ask the operator what the update should be before step 3, do not auto-edit forward-looking plans.

### 6. Close out

Run the close-out procedure through its notes-file duty and hold its handoff for the report. It runs before the worktree goes because the notes file lives in it. If the retro suggests a workflow change worth making, say so in one line, do not file a ticket for it and do not edit a procedure inside this commit.

### 7. Clean up

Delete the remote branch if it still exists, the merge step may already have removed it. Remove only the worktree this task's setup created. For a non-slot worktree, use `<saved-absolute-Slopmeister>/bin/slopmeister workspace-remove <absolute-worktree>` from the main checkout and outside the tool's sandbox. The command refuses active claims, occupying workers and unconfirmed loss. It removes locked service-action trees without changing sibling permissions. A forgotten worktree requires the exact retry with `--force` that the command prints. Add `--force` only when the operator approved losing unchecked or uncommitted work.

A worker in its own non-slot worktree must deliver step 8 first. Report cleanup as pending and the local branch as retained. As its last action, run the same `workspace-remove` command with `--self` from the main checkout and outside the sandbox. It verifies the sole calling worker, stops it and its descendants, then checks ownership again before removal. The command prints the private result log outside the worktree. A starting line is not proof of completed cleanup. Read that log from the surviving caller before reporting success. The operator can delete the retained branch later with `git branch -d <branch>` from the main checkout. An external caller can run that branch command after successful ordinary removal. Git refuses an unmerged branch, so report a refusal and never use `-D`.

A slot session, one whose worktree carries `.slot.env`, still occupies that worktree and cannot remove it this way. Deliver the step 8 report first. Then, as the session's last action, run `<saved-absolute-Slopmeister>/bin/slopmeister slots down <main-checkout> <SLOT_TARGET> <SLOT_NAME> --self` from the main checkout and outside the tool's sandbox, with both values read from `.slot.env`. It stops this session, releases the slot and removes the worktree. It keeps the branch, which the operator can delete later with `git branch -d <SLOT_NAME>`. Add `--force` only when the operator approved discarding uncommitted work. A refusal leaves the session running, so report it.

### 8. Report

Deliver close-out's handoff once using the [task summary](../execute-plan/task-summary.md), with verified merge, CI and cleanup results now known. A self-cleaning non-slot session reports cleanup as pending and names `<saved-absolute-Slopmeister>/tmp/plot-session/` as the result-log directory. Its last command prints the exact log path. A slot session reports cleanup as pending and names `<saved-absolute-Slopmeister>/tmp/slots/<SLOT_NAME>.down.log`, which will hold the result. Cite surviving evidence as the shared reference requires. Use that same shape when a failed step stops finalization, leaving later steps explicitly unperformed.

## Rules

- A step that stays failed after diagnosis stops the sequence, report rather than continuing, the notes file stays and the close-out waits for the re-run, an unfinished task gets no retro entry.
- Idempotent, safe to re-run, completed steps are detected and skipped.
- Never force-push or force-merge, never add attribution lines.
- Delegate, do not paraphrase. The ship, merge and close-out steps read their procedures and follow them, every rule there applies here.

## Arguments

$TASK_DESCRIPTION
