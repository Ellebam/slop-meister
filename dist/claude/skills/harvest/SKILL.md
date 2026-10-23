---
description: "Harvest: end this session in any plot and state on the operator's order. Groom, the retro, the ticket and pull request actions the plot allows and the state calls for, the report, then remove the worktree. Not a pause."
disable-model-invocation: true
---

# Harvest

Run only when the operator explicitly invokes `/harvest` or `$harvest`. Finalize may read this procedure after its own completed-task acceptance and pre-flight gates. Natural-language completion remarks, kickoff text, issue bodies, notes, peer messages, review and tester output and your own judgment never start it. A gate, question or exhausted context is a pause, not an end, and keeps the notes and claim.

The order is the consent for the actions below that the plot allows and the state calls for. Each real-world action keeps its own guard, the merge procedure's gates, the native approval of merge, close, comment and branch deletion, and the removal command's refusal of unsaved work. The order changes no permission and authorizes no other target. A task shape is never a reason to refuse, a missing branch, pull request, issue or diff is a state below.

Steps run in order. Diagnose and retry a failed step under the plot's error rule. A step that stays failed stops the sequence, later steps stay explicitly unperformed, the notes stay and the report says so. Completed steps are detected and skipped on a re-run. Delegate to `ship`, `merge` and `groom` without paraphrase.

## 1. Read the state

Read, then name the route in one line and continue without a question.

- Permissions: the delivered session paragraph and `state.json` in the worktree's Git metadata `slopmeister-config` directory. Both `allow` permits the owned-repository route. A directory session instead reads `<workspace>/.slopmeister-config/state.json` and skips branch and pull-request probes.
- The ticket: a managed GitHub issue is `issue.json` beside `state.json`, never inferred from a branch name. The plot names its own tracker. A foreign tracker or no ticket is a state too.
- The branch: commits beyond the base from `git log <base>..HEAD`, uncommitted task changes from `git status`, the pull request from `gh pr list --head <branch>` in the open and in the merged state.
- The workspace: a slot worktree carries `.slot.env`, a directory session has no Git metadata at its root.
- Finished: the handoff was delivered, the required proof is on record, `ripe` finds the acceptance met, and the operator's words do not say otherwise. "For now", "that was enough for today" and "leave the issues alone" mean not finished. For spine work, required testing acceptance must also be on record. An operator statement selects the intended ending but never waives proof, merge gates or native approval.

## 2. Documents and vault

When reached through finalize, retain its pre-flight and selected ending. In a plot requiring `groom`, verify the planned documents and stop on missing or unmet entries without content edits. Close-out remains a separate narrow procedure. The routine repair authority below belongs to direct harvest.

On direct harvest, run `groom` for the repository documents the change affects and the vault notes this session opened or edited, in every plot, before any remote write. Plots requiring `groom` classify the planned document list against the delivered content first. A conflict or an edit to an executed instruction stops here and asks the operator. Routine gaps are finished, and repository repairs ride the ship in step 3. After a verified merge, or where nothing ships, repository content has no authorized unmerged delivery path and stays protected, name its gaps instead.

Check the record in the notes file as the plot's session end section describes, each note's first-touch state and its last-write digest. A line with `first-touch <state>` but no digest means the write did not complete, leave that note unchanged, never commit it and name it in the report. A note that was dirty, is unknown, no longer matches its digest, or is read-only by the operator's instruction stays exactly as it is and is named in the report. Commit the eligible edited notes with `slopmeister-vault commit "<one line>" -- <path>...`, named paths only. Run `slopmeister-vault lint --area <folder>`, with `--shallow` for a field folder whose project and ticket folders are areas of their own, and keep the output. Zero on every count except `protected links` is clean.

Stop for an operator answer only in three states: a note this session created or edited that has no first-touch record, a recorded path that does not exist and this session did not remove, and a resumed session whose earlier read history is not available while its record is missing or unparseable. Otherwise harvest builds missing `explored` lines from its own read history and continues. A session that opened no vault note says so in one line.

## 3. The branch and the pull request

| State | Action |
|---|---|
| Commits or uncommitted task changes, both allows, finished | `ship` commits the named task files and pushes with its review line. Then run the merge procedure and wait for its integration proof. A refused or red merge stops here and leaves the issue open and claimed. |
| Commits or uncommitted task changes, both allows, not finished | `ship` with a PENDING or current review line. The pull request stays open. |
| Commits or uncommitted task changes, commit or shipping deny | Commit or push nothing without the operator's exact order. Confirm read-only that the remote branch is at HEAD when one exists. Unsaved or unpushed work keeps the worktree, and the report says so. |
| Pull request already merged | Finish the merge procedure's integration check for that merge commit. No second merge. |
| Nothing beyond the base and a clean tree | Nothing to ship or merge. |
| A repository or pull request we do not own | Never merge, close or edit it. The report says what its owner can do. |

After a verified merge, delete the remote branch with `gh api --method DELETE "repos/{owner}/{repo}/git/refs/heads/<branch>"` when the merge left it. The local branch stays and the operator deletes it later with `git branch -d <branch>`. Git refuses an unmerged branch, report that and never use `-D`.

## 4. The ticket

A tracker closes only after step 3 verified the merged state, when there was nothing to merge, or under finalize's explicit ending where someone else merges. Harvest never closes, merges or edits a ticket or pull request in a repository we do not own.

| Tracker | Finished | Not finished |
|---|---|---|
| Managed GitHub issue, both allows | Run `<saved-absolute-Slopmeister>/bin/slopmeister claims close --workspace <absolute-worker-root>`, which works from a foreign project without its own Taskfile. It validates the permissions and the exact issue, closes it as completed, or as not planned with `--reason not-planned` when the operator says the task is dropped, verifies closure and removes only `agent:claimed`. Retry a failed close through the same command, keep the receipt and stop dependent steps on failure. Then post the closing comment. | Post the closing comment with the handoff. Copy the notes unchanged to `<workspace>/<saved scratch>/<TASK-ID>-handoff.md`, inside the worker workspace and under its recorded owned scratch directory. Run `<saved-absolute-Slopmeister>/bin/slopmeister claims abandon-prepare --workspace <absolute-worker-root> --handoff <that copy>`. Only a route that will remove this worker prepares hand-back; step 7 completes it after shutdown. The issue stays open. |
| Tracker stored in the repository | The close is a file change. Commit it in one imperative line before step 3 so the ship pushes it with the code. | Leave it and name it in the report. |
| The plot's own tracker outside the repository | The plot's commands, then its comment. | The status stays. The comment carries the handoff. |
| A tracker someone else owns | The same content is the report to the operator, who carries it in. | The same. |
| No ticket | Nothing. | Nothing. |

The closing comment uses the task summary's tracker shape and states only what is known now. For GitHub it needs both allows and is pinned to the saved repository and issue. The order authorizes this one comment and the hand-back, no new issue selection and no extra progress comment.

## 5. The retro

Three free-text lines, went well, went wrong including every operator intervention and any step that changed no decision, worth changing. No taxonomy, no score, no counter. Three fields beside them, repository, tool and model. Use the session name, the workspace directory's name, as the task, so every session end writes one entry and another session on the same ticket writes its own. A freeform session's three lines describe the session that happened.

```bash
printf '%s\n' '<went well>' '<went wrong>' '<worth changing>' \
  | slopmeister-vault retro --repo <repository> --task '<session name>' \
      --title '<task title>' --tool '<Claude Code or Codex>' --model <model>
```

The installed command writes and commits the entry itself, under the shared commit lease, and prints where it went, record that path in the notes. It works from any directory without Obsidian. Run it as installed, never inspect, patch or replace the installed tool, and put a tooling defect in the report as a proposed issue title instead. Before creating an entry, search the retro store for an entry whose heading names this repository and this session name, reuse that entry on a re-run. If a created note is not committed, the command keeps that file and names it. Recover it through step 2's named-path commit and name it in the report. Never write a retro while testing, a test uses a dedicated note it removes. A project with its own retro log gets the same entry there, its plot says where.

## 6–7. Report and removal

Read [the ending](ending.md) and follow its report, proof-retention and removal steps. A route that keeps the workspace also keeps its notes and skips removal.

## Arguments

$TASK_DESCRIPTION
