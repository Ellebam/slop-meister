---
description: "Ship: commit, push, and open or update the PR. Idempotent. Standing authority comes from the plot; denied delivery needs explicit operator instruction. Not the merge."
---

# Ship

The branch-shipping part of the spine. Commit, push, open or update the pull request. Idempotent, running it twice never creates a duplicate PR or a duplicate commit.

Read the fixed session permissions. Commit and shipping allow grant standing authority for ordinary commit, push and PR create/update through the fixed helper on the saved owned repository and current non-default task branch after proof. The helper refuses the default branch. Deny grants no standing authority, but an explicit operator instruction for the named task may authorize the exact native-prompted commit and fixed ship command once. Approval changes no saved permission. Directory sessions cannot ship. Merge remains an operator gate.

Commands here are the GitHub instantiation through `gh`. On another forge the helper only pushes, see step 3, and the project supplies its change request equivalents through its plot, the principles, one open change request per branch, an honest review line, reported mergeability, do not change.

The input is optionally a commit-message hint or PR context, otherwise infer from the changes.

## Process

### 1. Assess

List the primary and companions with the invoking Slopmeister's `repository status --workspace <primary>`. Apply this procedure to each changed repository under its own saved permission and remote. Use the primary's fixed ship helper for every member, passing that member as `--cwd`. Companions have no separate shipping entry, so the existing native approval route stays the same. The helper refuses foreign sessions and mismatched permissions.

Run a companion's direct Git history writes and any push outside the fixed helper as `cd <companion> && git <command>`, never through `git -C <companion>`. This preserves the session's existing bare-command approval rules. The fixed ship helper still takes `--cwd` and keeps its separate native approval route.

Run in parallel, `git status`, `git diff --stat`, `git log --oneline -5` to match the existing message style, `git branch --show-current`, `gh pr list --repo <saved owner/repository> --head <branch> --json number,url,state,body,baseRefName`, and a lookup of the task notes file if any.

Guard rails. On the default branch, stop and warn, never commit or push there. Nothing to commit, nothing unpushed, and no PR line to sync, report "There is nothing to ship."

### 2. Independent-review line

Keep exactly one plain review line per delivery in the task notes and handoff, in one of these forms.

```
Independent review: PASS - <tool, model, date>, verdict <exact verdict>, fix result <none needed | fixed by <proving check> | accepted by the operator>
Independent review: N/A - <why this diff executes nothing>
Independent review: N/A - operator exception: "<verbatim order>"
Independent review: PENDING - <what it is waiting on>, verdict <exact verdict or none yet>, fix result still open
```

Decide the value here once. PASS when the diff check verdict passed, or when every failing finding and scenario is fixed with its proving check or accepted by the operator. A security must-fix finding cannot be accepted and stays a stop. N/A when the working agreement's exemption applies, a judgment already made at step 3, or when the operator excepts this named delivery. Record that order verbatim in the notes. When this task has no saved diff result yet, pass it to the diff check as `--exempt-reason "operator exception: <order>"`, so the saved result matches the line. Otherwise leave the saved result unchanged. The line quotes the order on one line, with its line breaks as spaces. PENDING while review or a fix is still owed. A pending line blocks at the merge.

A verdict covers this delivery only when HEAD is its gate's `Tested:` commit or adds only the recorded scoped fix pass with its proof, or when the runner bound it to this delivery's final candidate. A tested commit that is an ancestor of an earlier merged pull request head of this task belongs to that delivery. A completed task-and-mode result replays permanently unless the operator explicitly authorizes exact replacement, so a replayed result of an earlier delivery covers nothing. Then ask the operator for that replacement or an exception.

Push nothing for a delivery that changes something a program or a session executes until its line carries a covering verdict or the operator's exception. Without either, push only on the operator's order to push this named delivery first, for example when its pull request CI run is the tracer, and keep the line PENDING.

For every forge, include that line in a pull request or merge request body only where the plot fully owns the project. Where it does not, the line stays in the notes and handoff and never reaches the body, including writes without the GitHub helper. This ownership rule also applies to the review-line principle for other forges above. Add `--review-in-notes` to step 3's helper command for this case. The helper then refuses a review line in the body. Its default still requires exactly one line.

The line does not grant approval. Use the value verbatim wherever it belongs, whether the request is new or existing. Never re-derive it or strip an operator's quoted words out of the internal record.

### 3. Commit and push

1. Read the diff, `git diff` and `git diff --cached`.
2. When commit or shipping permission is denied, verify the conversation contains explicit operator instruction for the named commit, push and PR create/update. Present the exact title and body before invoking the fixed helper. Without that instruction, prepare the handoff and stop.
3. If the changes span logically distinct concerns, make separate commits, one concern, one commit.
4. Answer two questions. What must be committed so the change works? Go through every `git status` entry, untracked files included, and mark it needed or not. Is the commit safe? Check the plot's rules, `rinse` on the commit message, and on everything the push publishes where the plot requires its trace check, that only needed files are staged, and that the diff holds no secret. A secret stops the commit.
5. Resolve every remaining untracked task file before shipping. Stage the needed files by name, `git add <specific files>`, never `git add -A` or `git add .`.
6. Commit messages follow the global layer, one imperative line, no body, no attribution trailer, unless the project's log shows another convention, then match the log. A denied commit uses the native exact-command approval boundary.
7. Prepare the title and exact body under step 4 and check them with `rinse`, then run `python3 <this skill>/scripts/ship.py --cwd <absolute worktree> --title <title> --body-file <absolute body file>`. Fresh denied sessions route this fixed command through native approval, allowed sessions use standing authority. The fixed helper checks the declaration, the saved repository, remote and branch, and PR identity. It pushes without force or tags only when the remote branch differs from HEAD, creates or edits the PR only when its title or body differ, and reads each write back. It then reads mergeability up to five times two seconds apart and reports the answer without failing on it. It accepts no stronger action or arbitrary Git flags. Success prints one JSON line with `pr`, `sha`, `pushed`, `pr_action` (`created`, `updated` or `unchanged`) and `mergeable`. Failure prints `SPINE BLOCKED: shipping:` with the failed check or command and exits 1.
   When origin is not GitHub, run `python3 <this skill>/scripts/ship.py --push-only --cwd <absolute worktree>` as its own command, with nothing chained before or after it. Pass a companion as `--cwd` the same way. It pushes HEAD without force to the remote branch recorded at launch, which may differ from the local branch name, refuses the default branch and prints one JSON line with `sha`, `branch` and `pushed`. It never creates a remote branch. When it reports that origin has no such branch, create that branch once with `git push origin HEAD:refs/heads/<branch>` through native approval, then use the helper again. Add `--tag <name>` to also push a new pre-release version tag such as `0.2.1-dev1` that points at HEAD. It never moves or deletes a tag and refuses a release tag. With both allows this command runs on standing authority. Every other push, including a release tag, keeps native approval. The plot's own route opens the merge request.
8. Confirm that the pushed commit works: its CI where the repository has one, otherwise one clean checkout of that commit running the plan's focused check. A refused push or a failed check means not finished. Record the PR URL, or the pushed branch where the helper writes no PR, and the shipped SHA in the notes. Git is the shipping state, the remote branch at HEAD with its open PR, or with no PR after `--push-only`, is shipped, anything else is not. After a failure or interruption, fix the named cause and rerun the same authorized command with the same inputs, a confirmed push or PR write is never repeated. Never bypass the helper or infer success from a launch line.

### 4. The pull request

For a session spanning repositories, record each confirmed PR URL in the task notes. After creating the eligible PRs, add links to the other session PRs in each exact body, run `rinse`, and update through the same fixed helper. Read back every link. Preserve already confirmed writes on a retry and report any member still unshipped. No repository's permission authorizes another repository's write.

Pin every GitHub read and write to the saved owner/repository. The helper validates PR base and head identity against that repository. If an open PR already exists, do not create another. After earlier PRs are merged, include exactly one `Follows #<number>` line naming the latest merged PR in the new body. Keep that line on updates and retries. The helper refuses closed unmerged or ambiguous history and requires new commits on the merged PR head before creating a follow-up. Where step 2 puts the review line in the body, replace its single existing value. Otherwise remove any existing review line from the body and retain the value internally. Preserve the rest of the body byte for byte. Re-read the body afterwards and confirm the line's presence or absence matches step 2. Report the URL and whether the line changed.

If no PR exists, base it on the default branch unless told otherwise. Read the commits for this request so the body covers the whole change, not just the last commit. For a follow-up, start after the previous merged PR head. Title under 70 characters. The body carries a summary and a test plan. Include the independent-review line verbatim only where step 2 permits it. Never add attribution lines.

### 5. Report

Use the [task summary](../execute-plan/task-summary.md), carrying branch, commits, files, PR URL and whether it is new or updated, mergeability and the independent-review line into the handoff. A non-clean mergeability answer leads the outcome and is never omitted. An `UNKNOWN` or `UNAVAILABLE` answer says only that, never that CI is blocked. During a continuing workflow, retain these results for its eventual handoff.

## Rules

- Never force-push, never amend, never bypass hooks.
- No secrets in the diff, including env files, credentials and tokens.
