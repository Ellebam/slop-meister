# Run sessions beside each other

A slot gives a worktree its own ports and, when declared, a compose project and data directory. Dispatch fresh workers using [Choose the worker command](../src/skills/plot-session/dispatcher.md#choose-the-worker-command). Direct freeform sessions may use the plain launcher when they need no stack resources.

[Overview](../README.md) · [All documentation](README.md) · [Slot procedure](../src/skills/slot/SKILL.md)

## Commands

```text
task slot:up -- <repo> <plot> <name> [--slot <n>] [launcher args]
task slot:status -- [<repo>]
task slot:down -- <repo> <plot> <name> [--force] [--slot <n>] [--self]
```

Use `<plot>-<ticket>-<one or two words>` for new session names, keeping them near twenty characters. `slot:up` checks the full plot prefix before claiming resources. `slot:down` keeps accepting existing names. Recover a saved slot through [launcher redispatch](../src/skills/plot-session/SKILL.md) with its exact name.

> [!IMPORTANT]
> Every slot hands off to the same launcher preparation, with the kickoff and launcher arguments. The declaration independently selects agent commit permission.

`slot:up` accepts `--host <alias>` before native tool arguments. Allocation and all recovery run on the owning host. See [remote dispatch](remote-dispatch.md).

## The definition

Each repository plot declares its resources in `[slots]` inside plot.toml. A plot without a repository has no slots table. A repository without resources declares only `none = true`.

```toml
[slots]
max = 3
compose = "docker/compose.yml"
testers = 1
setup = ["task", "setup"]
setup_files = [".env.local"]

[slots.ports]
PG_PORT = 45432
```

Slot N adds N to each `ports` value. `max` is an integer from 1 to 99 and defaults to 6. A resource table needs at least one port variable. `none = true` cannot accompany any other key or table.

Read the project's compose files and environment examples before writing a definition. The repository owns that manifest and its stack conventions; Slopmeister owns allocation, readiness, attribution and teardown. Use the variable names the stack already reads and do not reproduce its manifest in Slopmeister.

| Field | Validation |
|---|---|
| Variable names | Matching `^[A-Z][A-Z0-9_]*$`. |
| Reserved names | `SLOT`, `SLOT_TARGET`, `SLOT_NAME`, `SLOT_PROJECT`, `SLOT_DATA`, `SLOT_COMPOSE`. |
| Ports | Integers from 1024 to 65535, never booleans or quoted numbers. Every expanded slot must stay in range, and the port sets of all slot numbers must be disjoint, before any app starts listening. |
| `testers` | Optional tester-only slots after the worker range, default 0. Worker max plus testers cannot exceed 99. Port validation includes both ranges. |
| `setup` | Optional nonempty argument array, executed directly after worker stack readiness with the slot environment. No shell parsing. |
| `setup_files` | Unique relative paths created by setup. Existing, tracked, linked, parent, Git-metadata and allocation paths are refused. Unchanged recorded outputs may be removed; changed outputs require confirmation. |
| Disposable directories | Optional `disposable` lists exact relative build directories. Require documented recreation and no secret or proof. Setup-output path checks apply. Only ignored, readable regular files qualify. Tracked files and symlinks remain protected. |
| Compose path | A nonempty relative path with no `..` segment or control character. Spaces are literal. It must name a readable file at allocation time. Its resolved path must remain inside the checkout, including through symlinks. |

Cross-plot port overlap is reported by `task slot:status`. It is allowed in definitions because those plots may never run together. Allocation checks live listeners before using the ports.

Run `bin/slopmeister plots --list` to validate and list every plot declaration. `task check` covers the command through the [layered slot tests](../tests/integration/slots/). The [shared validator](../slopmeister/plots/declaration.py) supplies normalised rows through `task plot -- --slots <name>`. Resources are never rendered into session instructions.

## Allocate a slot

1. Pick the lowest number unused by the repository's worktrees and Slopmeister's `tmp/slots/` data directories, or use `--slot <n>`.
2. Expand the ports and check live listeners. A collision names the port and process.
3. Claim `tmp/slots/<plot>-slot<N>` with atomic directory creation. Concurrent allocation or leftover state fails with the matching teardown command.
4. Write sorted `KEY=value` lines to `.slot.env`.
5. Prepare the normal worktree, deliver fixed Slopmeister configuration and `.slot.env`, exclude the allocation from Git status and protect it from commits.
6. Resolve the repository-owned compose manifest inside that prepared worktree and wait for every declared service. Running services must be healthy when they declare a health check, and completed one-shot services must exit zero. A missing, unhealthy or nonzero-exit service reverses allocation.
7. Run declared setup, record generated output digests and open the worker only after setup succeeds. Setup has a 900-second limit and its owned children are stopped before rollback. Failure retains a private `setup.log`.

The environment file contains the reserved keys and allocated port variables. Compose and the stack can read it. The slot command never sources it.

Repository deliveries use the launcher's staged-file contract, and the launcher refuses a tracked destination basename. Preparation or compose failure before terminal opening reverses the allocation. Once the allocation was delivered into the worktree, the reversal also deletes the branch while it still points at its starting commit, so the same name can be retried. An earlier preparation failure keeps the branch. Once terminal opening is attempted, resources stay up because a worker may already exist. Inspect the worker before cleanup.


## Release a slot

Run `task slot:down` from outside the worktree being removed. It checks that the plot and session name match the allocation, refuses while a worker still occupies the worktree, and refuses a dirty worktree unless `--force` is supplied. `--force` confirms discarding uncommitted work and nothing else. It refuses a worktree whose saved issue association is in any phase other than `released` or `closed`, and names the abandon command, because removing the worktree deletes the record that releases the claim. The refusal also holds when the worktree directory lost its Git link or is gone, because the association lives in the repository's Git metadata until teardown prunes it. Harvest or abandon the task first. A live worker blocks release, except when that worker releases its own slot with `--self`.

A worker occupies the worktree when a `claude`, `codex` or `opencode` client process has its working directory at the worktree or beneath it. `bin/slopmeister occupants` is the one definition, shared with the launcher's redispatch, and the refusal names every occupant. Use launcher redispatch or abandonment to close a known worker before `slot:down`; that path records its descendants before signalling, stops them child-first and verifies every recorded process has gone. Manually closing a terminal must stop that worker's descendants too, because resource teardown cannot reconstruct ownership after the client disappears. When a slotted launch fails, the launcher's message stands and no cleanup command is printed, because the launcher can fail after its worker has started.

A worker releases its own slot with `--self`, run from the main checkout and outside the tool's sandbox, on the operator's cleanup request or in harvest. Inside a sandbox the worker inventory cannot run and the command refuses. The command applies the same checks while the worker still runs. It also requires that the calling worker is the only occupant, so the nearest worker process above the command must be the one in the worktree. A reviewer, a tester or another session is refused. The command then starts one process that outlives the worker and returns. That process stops the worker and its descendants through the redispatch shutdown, which also closes the worker's terminal, completes any intact recorded claim hand-back, then runs strict ordinary teardown and exits. Its output goes to `tmp/slots/<name>.down.log`, which ends with the release line or with the refusal that stopped it.

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

Ignored work and hidden tracked changes are checked too. Only unchanged delivered files, unchanged recorded setup output, declared disposable directories and recognized caches are disposable. Session scratch is disposable only when the saved delivery records ownership. Before self-removal, harvest preserves named proof. Root `tmp/` proof must have an external private copy with matching bytes; changed, missing or linked copies refuse cleanup.

## Independent testers

Add `--slot-target <plot>` to `tester launch` when its guide needs services. The tester receives its own checkout, ports and Compose project. With `testers` set, it uses only the reserved range. Otherwise it competes for ordinary free slots. Directory subjects cannot take a slot.

The allocation lease prevents simultaneous use and remains held through the tester process. Compose readiness runs before admission. The guide still owns dependency installation and repository setup; worker setup is not replayed automatically. Collect releases tester resources before publishing the final result. Cleanup failure retains its ownership record and reports the blocked state.

For interrupted tester cleanup, inspect `slot:status`, then use `slot:down` with the saved plot, tester name and slot number. Tester recovery accepts neither `--self` nor `--force`. A live lease, wrong checkout identity, edited allocation, occupant or live listener refuses recovery. Keep the record until recovery succeeds.

## Inspect live work

| Command | Shows |
|---|---|
| `task slot:status` | Definitions expanded for every slot and ports shared by plots. |
| `task slot:status -- <repo>` | Live slots, ports, labelled Compose resources, listeners and occupying workers attributed to worktree directories. |

Status makes two `lsof` passes, for listeners and working directories. A listener inside a slot's worktree but outside its port set is marked `stray`. Status runs on demand, never in a loop.

## Check the mechanism

The [unit](../tests/unit/slots/), [integration](../tests/integration/slots/) and [native](../tests/native/slots/) suites use scratch repositories, [fixture definitions](../tests/data/slots/), suppressed launches and disposable listeners. Their overrides are `PLOT_DECLARATIONS`, `SLOT_STATE_DIR`, the non-Compose launcher double `SLOT_LAUNCHER`, and a test-owned `CODEX_HOME`.

The suite does not touch Docker. Real container, volume and network behaviour needs the separate local QA run described by the [procedure](../src/skills/slot/SKILL.md).
