---
description: "Ship: commit, push, and open or update the PR. Idempotent. Standing authority comes from the plot; denied delivery needs explicit operator instruction. Not the merge."
---

# Ship

The branch-shipping part of the spine. Commit, push, open or update the pull request. Idempotent, running it twice never creates a duplicate PR or a duplicate commit.

Read the fixed session permissions. Commit and shipping allow grant standing authority for ordinary commit, push and PR create/update through the fixed helper on the saved owned repository and current non-default task branch after proof, GitHub enforces branch protection. Deny grants no standing authority, but an explicit operator instruction for the named task may authorize the exact native-prompted commit and fixed ship command once. Approval changes no saved permission. Directory sessions cannot ship. Merge remains an operator gate.

Commands here are the GitHub instantiation through `gh`. A project on another forge supplies its equivalents through its plot, the principles, one change request per branch, an honest review line, reported mergeability, do not change.

The input is optionally a commit-message hint or PR context, otherwise infer from the changes.

## Process

### 1. Assess

Run in parallel, `git status`, `git diff --stat`, `git log --oneline -5` to match the existing message style, `git branch --show-current`, `gh pr list --repo <saved owner/repository> --head <branch> --json number,url,state,body,baseRefName`, and a lookup of the task notes file if any.

Guard rails. On the default branch, stop and warn, never commit or push there. Nothing to commit, nothing unpushed, and no PR line to sync, report "Nothing to ship".

### 2. Independent-review line

Every PR body carries exactly one plain line, one of these three.

```
Independent review: PASS - <tool, model, date, one sentence>
Independent review: N/A - <why this diff did not need one>
Independent review: PENDING - <what it is waiting on>
```

Decide the value here once. PASS after the external diff review and its fix pass are satisfied. N/A when the working agreement's exemption applies, a judgment already made at step 3. PENDING when review is still owed, including the automatic path's push after testing and before diff review. A legitimate pending feature branch blocks at the merge. A completed task-and-mode result replays permanently unless the operator explicitly authorizes exact replacement.

The helper checks the line structure. The line does not grant approval. Use the value verbatim whether the PR is new or existing, never re-derive it, and never strip an operator's quoted words out of it.

### 3. Commit and push

1. Read the diff, `git diff` and `git diff --cached`.
2. When commit or shipping permission is denied, verify the conversation contains explicit operator instruction for the named commit, push and PR create/update. Present the exact title and body before invoking the fixed helper. Without that instruction, prepare the handoff and stop.
3. If the changes span logically distinct concerns, make separate commits, one concern, one commit.
4. Stage explicitly, `git add <specific files>`, never `git add -A` or `git add .`.
5. Commit messages follow the global layer, one imperative line, no body, no attribution trailer, unless the project's log shows another convention, then match the log. A denied commit uses the native exact-command approval boundary.
6. Prepare the title and exact body under step 4, then run `python3 <this skill>/scripts/ship.py --cwd <absolute worktree> --title <title> --body-file <absolute body file>`. Fresh denied sessions route this fixed command through native approval, allowed sessions use standing authority. The fixed helper checks the declaration, the saved repository, remote and branch, and PR identity. It pushes without force or tags only when the remote branch differs from HEAD, creates or edits the PR only when its title or body differ, and reads each write back. It then reads mergeability up to five times two seconds apart and reports the answer without failing on it. It accepts no stronger action or arbitrary Git flags. Success prints one JSON line with `pr`, `sha`, `pushed`, `pr_action` (`created`, `updated` or `unchanged`) and `mergeable`. Failure prints `SPINE BLOCKED: shipping:` with the failed check or command and exits 1.
7. Record the PR URL and shipped SHA in the notes. Git is the shipping state, the remote branch at HEAD with its open PR is shipped, anything else is not. After a failure or interruption, fix the named cause and rerun the same authorized command with the same inputs, a confirmed push or PR write is never repeated. Never bypass the helper or infer success from a launch line.

### 4. The pull request

Pin every GitHub read and write to the saved owner/repository. The helper validates PR base and head identity against that repository. If a PR already exists, do not create another. Replace the single existing `Independent review:` line with the value from step 2, preserving the rest of the body byte for byte, re-read the body afterwards and confirm exactly one such line exists. Report the URL and whether the line changed.

If no PR exists, base it on the default branch unless told otherwise. Read every commit on the branch so the body covers the whole branch, not just the last commit. Title under 70 characters. The body carries a summary, a test plan, and the independent-review line from step 2, verbatim. Never add attribution lines.

### 5. Report

Use the [task summary](../execute-plan/task-summary.md), carrying branch, commits, files, PR URL and whether it is new or updated, mergeability and the independent-review line into the handoff. A non-clean mergeability answer leads the outcome and is never omitted. An `UNKNOWN` or `UNAVAILABLE` answer says only that, never that CI is blocked. During a continuing workflow, retain these results for its eventual handoff.

## Rules

- Never force-push, never amend, never bypass hooks.
- No secrets in the diff. Warn on env files, credentials, tokens.

## Arguments

$TASK_DESCRIPTION
