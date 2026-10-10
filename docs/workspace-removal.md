# Remove a retired workspace

Use one command from outside the selected workspace:

```sh
bin/slopmeister workspace-remove /absolute/repo/.worktrees/session
```

The Task interface is `task workspace:remove -- <path> [--force] [--self]`. In another repository, use the absolute Slopmeister entry. This removes one directory and keeps all branches. Delete a merged local branch separately with `git branch -d <branch>`.

## Allowed paths and checks

The path must be one direct child of a main repository's `.worktrees/` or of `PLOT_SESSION_ROOT`. The session root defaults to `~/.slopmeister/sessions`. Directory sessions must have no Git metadata. Repository roots, either container root, nested paths and symlinks in the managed path are refused. An ancestor alias above the managed root is resolved before Git registration is checked. Symlinks inside the removed tree are unlinked without following their targets.

A slot workspace is refused with its named `slot:down` command. The local allocation file or the selected workspace's saved allocation flag identifies it. A missing file still needs its slot number. Unrelated global slot records do not identify this workspace. An occupying worker or failed process inspection also refuses removal. An active or unreadable surviving Git-metadata issue association refuses removal. A worker-written local receipt cannot release that claim. Finalize or abandon that task first. `--force` overrides none of these checks or a Git worktree lock.

Git checks a registered worktree for uncommitted tracked and untracked work, even when Git's status configuration hides untracked files. Use `--force` only to confirm losing that work. A detached HEAD also needs confirmation because removal can make its commits unreachable. A registered worktree with a missing or inconsistent Git link refuses because its status cannot be checked safely. For a missing link, run the printed `git -C <repo> worktree repair` command and retry. This repairs links from the owning repository's records and keeps claim and lock metadata. Do not prune that metadata to bypass a refusal. A live foreign Git link is not a forgotten local worktree. Nested linked worktrees must be removed separately so their records and claims are not stranded.

The command asks Git to remove the worktree. It then deletes any files Git could not remove. Only directories inside the selected tree gain owner write permission. The [delivered service-action lock](service-actions.md) stays unchanged. If Git refuses and still registers the workspace, recursive deletion does not start.

## Recover a forgotten worktree

Inspect its content before deleting it. Git cannot check unshipped work after forgetting the workspace. Run the command without `--force`. It refuses and prints one exact, quoted retry command. Run that line only after accepting the loss. A stale `.git` file does not prevent this recovery. Any surviving issue association still blocks deletion.

There is no sweep or background cleanup. Orca trash containers and entries are refused because their placement is not established by this command. An operator can inspect a retired entry and move it to an unused direct child of its repository's `.worktrees/` before removing it with the printed retry. Do not move a live workspace.

## Remove a retired dispatcher directory

After stopping the dispatcher, run:

```sh
bin/slopmeister workspace-remove /absolute/session-root/retired-dispatcher
```

The same locked-tree removal applies. This command does not stop a dispatcher.

## A worker removes its own worktree

Finalize reports before its last cleanup action. It uses the same command with `--self` from the main checkout and outside the tool's sandbox. Only the sole calling worker in a registered worktree can use this option. Session directories, forgotten leftovers, external callers and nested reviewer or tester workers are refused. Claim, path and unsaved-work checks run before shutdown.

The command returns a pending line with a private result log under Slopmeister's `tmp/plot-session/`. The cleanup process leaves the worker's process tree, stops the worker and its recorded descendants through the launcher, then runs the ordinary checks again before deletion. The local branch stays. Read the exact printed log to confirm completion or diagnose a refusal. A pending line is not completed removal.
