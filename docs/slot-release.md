# Release a slot

[Slots](slots.md) · [All documentation](README.md)

Applications record their owned process groups under the slot state directory's applications folder. Release runs the declared stop phase before deleting their records, stack or worktree. A failed stop or nonempty registry keeps the slot intact.

A diff check holds an exclusive lease on its worker slot. Ordinary release refuses while that check runs. Recovery of a retained check lease restores the worker without releasing its stack or allocation. Follow [Independent checks](slots.md#independent-checks) before ordinary teardown.

Run `task slot:down` from outside the worktree being removed. It checks that the plot and session name match the allocation, refuses while a worker still occupies the worktree, and refuses a dirty worktree unless `--force` is supplied. `--force` confirms discarding uncommitted work and nothing else. It refuses a worktree whose saved issue association is in any phase other than `released` or `closed`, and names the abandon command, because removing the worktree deletes the record that releases the claim. The refusal also holds when the worktree directory lost its Git link or is gone, because the association lives in the repository's Git metadata until teardown prunes it. Harvest or abandon the task first.

A worker occupies the worktree when a `claude`, `codex` or `opencode` client process has its working directory at the worktree or beneath it. `bin/slopmeister occupants` is the one definition, shared with the launcher's redispatch, and the refusal names every occupant. Use launcher redispatch or abandonment to close a known worker before `slot:down`; that path records its descendants before signalling, stops them child-first and verifies every recorded process has gone. Manually closing a terminal must stop that worker's descendants too, because resource teardown cannot reconstruct ownership after the client disappears. When a slotted launch fails, the launcher's message stands and no cleanup command is printed, because the launcher can fail after its worker has started.

A worker ends through [harvest](../src/skills/harvest/SKILL.md). Its single `workspace-remove --self -- <primary-worktree>` entry verifies the slot before shutdown, then releases it after the worker stops. Finished and unfinished harvests share the [report and shutdown contract](workspace-removal.md#a-worker-removes-its-own-worktree) and unique result logs.

| Removed | Kept |
|---|---|
| Exact-label Compose containers, volumes and networks | Git branch |
| Slot data directory | Launcher kickoff files and trust entries, until the next launch removes them |
| Worktree | |

> [!WARNING]
> Teardown deletes slot data and Docker resources selected by the exact `com.docker.compose.project` label. Neither the editable environment file nor the worker-editable manifest selects deletion targets.

Teardown removes the worktree before the slot data directory. Git removes what it can, and teardown then deletes what Git left behind, including files and directories without write permission. It changes permissions only inside that worktree and follows no symlink inside it. It refuses a symlink at the worktree path. When Git refuses the removal, teardown stops with Git's reason and keeps the worktree. When the deletion fails, the message names the cause and the command that finishes the release. In both cases the slot data directory stays and the slot stays claimed, while Compose resources are already removed.

A leftover is a directory at the worktree path that has neither `.git` nor `.slot.env`, so Git no longer tracks it. Release it with `--slot <n> --force`. Git cannot check a leftover for unsaved work, so teardown refuses without `--force` and prints the exact command. It also refuses while a worker occupies the directory.

Repeating teardown with `--slot <n>` reports nothing live and exits 0. Without the number, it refuses because neither a removed worktree nor a leftover can identify the slot.

Ignored work and hidden tracked changes are checked too. Unchanged delivered files and recognized caches are disposable. Session scratch is disposable only when the saved delivery records ownership. Setup output is ordinary untracked or ignored work. The retired `setup_files` and `disposable` declarations are rejected. Preserve required proof outside the worktree before removal. Unknown or changed work requires explicit accepted loss and `--force`.
