# Run sessions beside each other

A slot gives a worktree its own ports and, when declared, a compose project and data directory. Dispatch fresh workers using [Choose the worker command](../src/skills/plot-session/dispatcher.md#choose-the-worker-command). Direct freeform sessions may use the plain launcher when they need no stack resources.

[Overview](../README.md) · [All documentation](README.md) · [Slot procedure](../src/skills/slot/SKILL.md)

## Commands

```text
task slot:up -- <repo> <plot> <name> [--slot <n>] [launcher args]
task slot:status -- [<repo>]
task slot:down -- <repo> <plot> <name> [--force] [--slot <n>]
```

A same-plot session can pass repeated `--repository <checkout>` launcher arguments. The primary holds the one session allocation. Companion source repositories do not each consume a slot. The combined acceptance command uses that allocation, and teardown checks and removes the recorded companions before the primary. A task needing another resource policy follows the existing scope decision.

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
setup = ["task", "setup"]

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
| `setup` | Optional nonempty argument array, executed directly after worker stack readiness with the slot environment. No shell parsing. |
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

Follow [slot release](slot-release.md) for ownership checks, self-shutdown reports, teardown and recovery.

## Independent checks

Add `--slot-target <plot>` to `review review --mode diff --guide <absolute-guide>` when its guide needs services. The check borrows the calling worker's existing allocation for a clean checkout of its committed head or frozen candidate. It requires matching worker and owned-state `.slot.env` files and a declared setup command. It allocates no second slot or Compose project. Different worker slots can be checked concurrently. A second check of the same worker refuses. Directory subjects cannot take a slot.

The check discards all disposable worker-slot data before testing and again on return, including application records, authentication state and uploaded objects. Preserve needed evidence outside disposable slot data before starting. The worker must not use its slot while the check holds it. Repository application entrypoints enforce this exclusion. Arbitrary external clients are not fenced by the advisory lease.

The declared setup command implements three explicit lifecycle phases through `SLOPMEISTER_SLOT_PHASE`. Each successful phase must print exactly `SLOPMEISTER_SLOT_PHASE_OK=<phase>`. An absent command, nonzero exit, timeout or missing acknowledgement blocks the check. A command that ignores the phase never counts as a reset.

1. `stop` runs in the worker checkout before admission. It stops only recorded application processes, verifies their birth identities, and refuses unknown listeners. The worker keeps its stack.
2. `reset` runs in the clean checker checkout. It installs required dependencies and resets the slot through the repository's own setup route. The checker starts applications from its clean checkout as its guide prescribes.
3. After verified reviewer exit, `stop` runs in the checker checkout and `reset` runs in the worker checkout. A failing verdict returns that stopped, reset slot to the worker without restarting the rejected application. A passing check also requires `ready` to leave worker applications running for operator testing. Interrupted executions and explicit recovery use the full restoration route. No unverified stop, failed reset or required readiness failure releases the lease.

The lease is `tester.json` inside the existing worker state directory. A held file lock excludes another check and ordinary teardown. Setup phases receive `SLOPMEISTER_SLOT_CHECK_RUN` naming the private check run. Their unique mode-600 logs live under its `evidence/` directory. The original worker `setup.log` and unrelated state stay intact. Repository applications keep process receipts under `SLOT_DATA/applications`. Ordinary slot release calls the declared stop phase before removing those receipts or the worker stack. Failed stops retain the slot.

Cleanup verifies ownership and both allocation copies, restores the worker, removes only the checker checkout and lease, and retains evidence. It never removes the worker's Compose project, allocation file or state directory. A cleanup failure blocks the review result. Uncertain process exit, changed identity, failed setup or incomplete deletion keeps a visible recovery lease and the checkout. Status reports the held lease beside its worker.

After the review command ends and its cause is resolved, recover the exact worker shown by status:

```text
task slot:down -- <repo> <plot> <worker-name> --slot <n>
```

When a check lease exists, this command restores the worker and releases only that lease. It does not release the worker slot. Recovery refuses a live review lock, changed ownership, remaining checker or failed restoration, including with `--force`. Legacy separate tester records are preserved for explicit repair, never interpreted as worker leases.

## Inspect live work

| Command | Shows |
|---|---|
| `task slot:status` | Definitions expanded for every slot and ports shared by plots. |
| `task slot:status -- <repo>` | Live slots, ports, labelled Compose resources, listeners and occupying workers attributed to worktree directories. |

Status makes two `lsof` passes, for listeners and working directories. A listener inside a slot's worktree but outside its port set is marked `stray`. Status runs on demand, never in a loop.

## Check the mechanism

The [unit](../tests/unit/slots/), [integration](../tests/integration/slots/) and [native](../tests/native/slots/) suites use scratch repositories, [fixture definitions](../tests/data/slots/), suppressed launches and disposable listeners. Their overrides are `PLOT_DECLARATIONS`, `SLOT_STATE_DIR`, the non-Compose launcher double `SLOT_LAUNCHER`, and a test-owned `CODEX_HOME`.

The suite does not touch Docker. Real container, volume and network behaviour needs the separate local QA run described by the [procedure](../src/skills/slot/SKILL.md). A borrowed stack needs one real Compose diff check, proving the same worker resources remain and no checker checkout or lease remains.
