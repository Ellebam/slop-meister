---
name: finalize
description: "Finalize: the completed-task compatibility entry for harvest. Keep testing acceptance, document pre-flight and merge guards. Operator-typed."
---

# Finalize

Run only on the operator's instruction for a finished task. Retain required testing acceptance and the checks below, then read [harvest](../harvest/SKILL.md) and follow its finished route. This entry does not authorize an unfinished-session ending. Do not run close-out afterward, harvest records the one retro and report.

Use the explicit task identifier or the launcher's saved issue association. Never infer a managed issue from a branch name. Another forge uses the plot's equivalent commands with the same gates. A directory or tracker-only task skips steps that require a repository.

## Endings

The default is a pull request this session merges. Retain these existing alternatives and tell harvest which ending applies.

- A pushed pull request someone else reviews and merges, selected by the operator or a plot whose shipping permission is deny. Verify read-only that the pull request is open and the remote branch is at HEAD. Otherwise stop. Skip ship, merge, the pre-flight checks gate and its independent-review-line gate, which belong to that owner. A managed GitHub issue may close as completed only in an owned repository with both commit and shipping allow. Keep both branches while the pull request is open. Preserve unsaved or unpushed work.
- No diff, no commits beyond the base and a clean tree. No ship, pull request or merge. A managed issue closes as not planned only when the operator drops the task, otherwise as completed, with the existing permissions.

Never close, merge or edit a pull request or ticket in a repository we do not own. Tracker actions everywhere else become the operator report. The selected alternative does not waive any other acceptance, ownership or native approval rule.

## Pre-flight

For a plot requiring `groom`, check the planned document list against the delivered repository content and vault notes before any remote command. A missing list, unjustified `none`, missing document or unmet action refuses and names the document or missing list. Check the content, not only file existence or Git status. Stop without document edits, retain the notes and ask the operator for direction. Documentation gaps are not retryable errors and this procedure never repairs them. Any authorized correction follows the existing proof, review and acceptance rules before finalization resumes.

On a re-run, when `gh pr list --head <branch> --state merged` shows this task's PR, the merge is done. Skip the open-PR gates below and do not ship or merge again. Run merge's read-only integration proof for that exact merge commit before resuming harvest at its ticket step. Missing or failed proof stops the sequence.

Read the PR body's `Independent review:` line before anything writes to the tree. PASS or N/A, proceed. PENDING or missing, stop, except in the ending where someone else merges and in the no-diff ending, which has no PR. Check whether the review ran and only the line is stale, the ship step syncs it. If no review result exists, tell the operator it is owed. Catch this here, before a later step deletes the notes.

Outside the no-diff ending, if no PR exists and CI is absent or uncertain, stop before any write. Ship the PR and obtain its operator authorization before finalizing. With CI configured, the ship step creates a missing PR with the right review line.

For an existing PR, run `gh pr checks <number>` before any document or tracker write. When zero checks are reported, apply merge's checks through the current-base comparison without branch, tracker or GitHub writes. A refusal stops finalize. Do not refresh the branch or merge during pre-flight. After ship, run merge afresh. If that later gate refuses, the issue stays open and claimed, report the blocked merge.

## Continue

Read harvest and follow its finished route with the selected ending above. For plots requiring `groom`, its document step is verification only. Missing lists, missing documents and unmet actions stop without repairs. For other plots, retain the existing duty to make affected project documents true before shipping, under the existing proof and review rules. Never use harvest's routine-gap repair paragraph to bypass this pre-flight.

Report a pre-flight stop using the [task summary](../execute-plan/task-summary.md).

Detect completed actions on a re-run and skip them. A failed step stops dependent actions and retains notes. Harvest owns the retro, report, proof retention and guarded cleanup. A starting cleanup line is not evidence that removal completed.

## Arguments

$TASK_DESCRIPTION
