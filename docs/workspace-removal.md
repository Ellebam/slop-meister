# Remove a retired workspace

Use one command from outside the selected workspace:

```sh
bin/slopmeister workspace-remove /absolute/repo/.worktrees/session
```

The Task interface is `task workspace:remove -- <path> [--force] [--self] [--stop-only]`. In another repository, use the absolute Slopmeister entry. This removes one directory and keeps all branches. Delete a merged local branch separately with `git branch -d <branch>`.

## Session endings

Claude Code and Codex use these same paths on macOS and Linux. A slot adds resource release. Companions are removed before the primary. A directory session uses both `--self` entries with its own directory as the path.

| Entry and state | Result |
|---|---|
| Finished harvest: `workspace-remove --self -- <primary>` | Persist report, detach, stop caller and descendants, verify terminal closure, recheck ownership, remove the saved set and slot. |
| Unfinished harvest: `workspace-remove --self --stop-only -- <primary>` | Persist report and stop caller. Keep work, notes, registration, slot and claim. |
| Directory session that does not act on its inbox | Stop through `--directory --abandon --handoff <notes>`. Remove separately with `task workspace:remove -- <directory>` when ordered. |
| Pause at a question, gate or context limit | Keep worker and recovery notes available. |
| `task plot-session -- ... --redispatch` | Validate the saved set, close the predecessor, start one replacement. Keep configuration and work. |
| `task plot-session -- ... --abandon --handoff <notes>` | Stop the worker. Keep its workspace. Release a managed GitHub claim, retaining the open issue. Without an association, touch no tracker or claim. |
| Client exit, terminal closure or crash | Retain workspace, allocation and claim. Recover through redispatch or the owning harvest/abandon route. Never adopt orphaned processes for signalling. |
| Retired plain workspace: `task workspace:remove -- <path>` | Apply the checks below. Keep branches. |
| Retired slot: `task slot:down -- <repo> <plot> <name>` | Check allocation, occupancy and claims, then release its resources and saved set. Missing-worktree recovery needs `--slot`. |
| Failed `task slot:up` before worker opening | Roll back only that verified allocation. Retain uncertain live-worker state for inspection. |

Late terminal closure and redispatch use one monotonic ten-second budget for the close request and inventory polls, followed by a final half-second check. A still-listed terminal or unreadable final inventory refuses without deletion or a second conversation.

[Test cleanup](testing.md#test-files-and-cleanup) removes test-owned linked worktrees, including after an assertion fails. Unknown nested worktrees remain protected. A timeout can terminate pytest before finalizers run. The existing gate owns and removes that run's scratch after stopping its processes. A direct pytest process killed outside the gate can leave scratch that needs inspection. There is no new sweep or permission to discard foreign work.

## Allowed paths and checks

For a multi-repository session, name its primary worktree. The command checks every recorded companion with the existing registration, claim, lock, tracked-change and occupancy guards before removing any member. It then unregisters companions from their owning repositories, removes them, updates the saved set, and removes the primary last. A companion's location is accepted only through its primary's saved membership. Unrecorded nested worktrees remain refused. Slot teardown uses the same checks and ordering. Branches remain in each repository.

The path must be one direct child of a main repository's `.worktrees/` or of `PLOT_SESSION_ROOT`. The session root defaults to `~/.slopmeister/sessions`. Directory sessions must have no Git metadata. Repository roots, either container root, nested paths and symlinks in the managed path are refused. An ancestor alias above the managed root is resolved before Git registration is checked. Symlinks inside the removed tree are unlinked without following their targets.

External removal of a slot workspace is refused with its named `slot:down` command. A calling worker uses the shared `--self` entry, which checks its allocation and any check lease before stopping it. The local allocation file or the selected workspace's saved allocation flag identifies it. A missing file still needs its slot number. Unrelated global slot records do not identify this workspace. An occupying worker or failed process inspection also refuses removal. An active or unreadable surviving Git-metadata issue association refuses removal. A worker-written local receipt cannot release that claim. Harvest or abandon that task first. `--force` overrides none of these checks or a Git worktree lock.

Git checks a registered worktree for uncommitted tracked and untracked work, even when Git's status configuration hides untracked files. Use `--force` only to confirm losing that work. A detached HEAD also needs confirmation because removal can make its commits unreachable. A registered worktree with a missing or inconsistent Git link refuses because its status cannot be checked safely. For a missing link, run the printed `git -C <repo> worktree repair` command and retry. This repairs links from the owning repository's records and keeps claim and lock metadata. Do not prune that metadata to bypass a refusal. A live foreign Git link is not a forgotten local worktree. Nested linked worktrees and nested repositories that register an outside checkout must be removed separately so their records and claims are not stranded. Unreadable registrations, linked Git pointer files and pipes refuse removal.

Ignored content and hidden tracked changes are checked before removal. Unknown files, edited delivery and nonempty notes are retained unless the operator explicitly confirms their loss. An old same-named scratch directory is not ownership evidence. Only newly recorded session scratch is disposable. Directory sessions receive the same unknown-content guard.

The command asks Git to remove the worktree. It then deletes any files Git could not remove. Only directories inside the selected tree gain owner write permission. The [delivered service-action lock](service-actions.md) stays unchanged. If Git refuses and still registers the workspace, recursive deletion does not start.

## Recover a forgotten worktree

Inspect its content before deleting it. Git cannot check unshipped work after forgetting the workspace. Run the command without `--force`. It refuses and prints one exact, quoted retry command. Run that line only after accepting the loss. A stale `.git` file does not prevent this recovery. Any surviving issue association still blocks deletion.

There is no sweep or background cleanup. Orca trash containers and entries are refused because their placement is not established by this command. An operator can inspect a retired entry and move it to an unused direct child of its repository's `.worktrees/` before removing it with the printed retry. Do not move a live workspace.

## A worker removes its own worktree

Harvest supplies its report on standard input to its last cleanup call. It runs `cd <main-checkout> && <saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self -- <absolute-worktree>` outside the tool's sandbox, with paths quoted for the shell. The delivered permission binds the absolute Slopmeister executable and the session's own workspace. This spelling needs no new consent round. The final `--` prevents a trailing argument from enabling force. The ordinary removal and `workspace-remove <path> --self --force` forms keep their existing approval decisions. Only the sole calling worker in a registered worktree or in its own session directory can use self-cleanup. Forgotten leftovers, external callers and nested reviewer or tester workers are refused. A directory session starts the command with `cd <saved-absolute-Slopmeister>`, reads its plot from its own `.slopmeister-config/state.json` and passes the same unknown-content guard before deletion. Claim, path and unsaved-work checks run before shutdown.

Finished and unfinished harvests require a nonempty UTF-8 report on standard input. Use a quoted here-document, as below, with a delimiter absent from the report. The parent writes the report to the private 0600 result log and flushes it to standard output before forking. The report counts as delivered in that log. The client may close before showing the output. A manager, dispatcher or proof owner that sent harvest reads the complete report from the exact result log on the worker host and passes it on. Confirm shutdown separately from report delivery. Input must close within five seconds and fit in 65,536 bytes. Terminal control characters other than newline and tab are refused. Missing, blank, unreadable or oversized input and failed report delivery refuse shutdown. Ordinary removal without `--self` reads no report. No removal command reads a session transcript.

The command returns a pending line with that private result log under Slopmeister's `tmp/plot-session/`. If that line never appears, read the newest `<main-checkout>/tmp/plot-session/<worktree-name>.remove.*.log` on the worker host. An empty log does not deliver a report. The cleanup process leaves the worker's process tree, stops the worker and its recorded descendants through the launcher, waits for terminal closure, then runs the ordinary checks again before deletion. A slotted worktree uses the same command and unique result log, with its allocation and check lease checked before shutdown and its resources released afterwards. An active claim always keeps the workspace. Shutdown failure also keeps it. The local branch stays. Read the exact log for completion or refusal. A late refusal names the kept workspace and cleanup command.

## Stop an unfinished session

After an operator-ordered harvest concludes that a worktree is unfinished, save its recovery notes and include the full report in the shutdown call:

```sh
<saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self --stop-only -- <absolute-worktree> <<'HARVEST_REPORT'
<full report naming the unfinished state, retained work and next action>
HARVEST_REPORT
```

Run outside the tool's sandbox. The delivered permission binds the saved executable and the session's own workspace. Claude matches the exact spelling. Codex matches it as a prefix, so the command itself rejects trailing arguments after `--`. Other spellings retain their native approval rules. Stop-only requires `--self` and refuses `--force`.

The sole calling worker is identified before detachment and checked again by process ID and birth identity before shutdown. A different caller, a nested reviewer, another occupant, a replacement worker or failed inspection refuses the stop. The existing shutdown closes that worker and its recorded descendants. Finished worktree and slot self-cleanup use the same identity check.

Stop-only preserves the worktree, registration, branch, tracked and untracked work, locks, slot and claim. It skips deletion guards and resource release. The unique result log must contain `session stopped; workspace kept:`. A pending line proves neither shutdown nor removal. A refusal preserves the workspace. Resume through redispatch. A pending harvest question remains a pause.
