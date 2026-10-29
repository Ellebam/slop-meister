---
description: "Slot: allocate an isolated parallel session of a plot, a worktree with its own port set and resources that no other live slot collides with, then hand over to the launcher. Use the dispatcher worker-command rule for fresh workers, and when a task needs the project's declared resources."
---

# Slot

A slot is a worktree plus a deterministic port set and, when the plot declares one, a compose project and a data directory, all named `<plot>-slot<N>`. Slot N of a plot always yields the same set, so tearing one down and re-creating it changes nothing, and no two live slots on this machine share a port. What one session of a plot consumes is declared once in `plots/<plot>/plot.toml`, contract in `docs/slots.md`, and nothing about it renders into a session's context, a session learns its own set from the `.slot.env` file in its worktree.

## When a slot, when not

Dispatch fresh workers through [Choose the worker command](../plot-session/dispatcher.md#choose-the-worker-command). A directly launched freeform task that needs the project's stack also uses a slot, while a freeform task that runs nothing may use the plain launcher. A plot whose slots table is `none = true` is refused by the slot with a pointer to the plain launcher.

New session names follow the [launcher naming rule](../plot-session/SKILL.md) and must begin with the full `<plot>-` prefix. Slot cleanup accepts the saved name, including older names without the prefix.

For remote allocation, use `--host <alias>` on `slot:up` and quote remote paths. Run slot status and release on the allocation's owning host, never against a same-named Mac checkout. Follow `docs/remote-dispatch.md` under the invoking Slopmeister checkout.

## The ritual

1. `task slot:up -- <repo> <plot> <name> [--slot <n>] [launcher args]`, from the slopmeister root, with the kickoff on stdin exactly as the launcher takes it for every repository plot. The slot picks the lowest free number, checks every port of the set against what is bound on the machine right now and refuses a collision naming the port and its holder, then claims the number. The launcher creates the worktree, delivers fixed Slopmeister configuration and the staged environment file, and enforces the declared commit permission. A declared repository-owned compose manifest starts from that prepared worktree and reaches readiness before any declared setup command runs and before the worker opens. Setup receives the slot environment and records unchanged generated files for guarded cleanup. Failed setup retains its private diagnostic log.
2. Read the allocation back. The last lines of the output are the allocation file's lines sorted by key with `=` replaced by a space, `SLOT`, `SLOT_COMPOSE` when declared, `SLOT_DATA`, `SLOT_NAME`, `SLOT_PROJECT`, `SLOT_TARGET`, and one line per port variable. Present them to the operator with the launcher's own report, slot, worktree, ports, so the dispatch is auditable at a glance.
3. `task slot:status -- <repo>` when asked what is live. One line per slot with its ports and compose state, then the exact labelled containers, volumes and networks, every listener rooted in the slot's worktree, flagged `stray` when it holds a port outside that slot's set and every occupying worker. Without a repository it prints every definition expanded per slot and the ports two plots share, which is a listing, never an error, because two plots are rarely live together. Run it on demand only, it is never a loop and never something a session runs on its own.
4. `task slot:down -- <repo> <plot> <name>` when the work is shipped or abandoned, from the main checkout, never from inside the worktree being removed. It deletes only Docker resources carrying the exact compose project label, deletes the data directory, removes the worktree, and says what it keeps, the branch and, for a launcher session, the trust entry and kickoff files. A worktree a Claude Code or Codex worker still occupies is refused, stop the worker first. A worktree whose issue claim is still active is refused too, harvest or abandon the task first. A session told to remove its own slot adds `--self` instead, which stops that session and then releases the slot as `docs/slots.md` describes. A dirty worktree is refused without `--force`, uncommitted field work is the whole handoff in a repository we do not own. A worktree removed by hand leaves the slot's number claimed until `--slot <n>` releases it.

Independent testers use `tester launch --slot-target <plot>` and their own reserved allocation. Never lend them a worker's ports, project or writable checkout. The guide owns dependency and repository setup. Collect completes cleanup before publishing the result; a retained allocation follows the documented recovery route.

## Writing a definition

A definition is written once per plot, by a person, and reviewed at commit like a plot fragment. Before writing one for a field's repository, read its compose files and env examples. Every declared port moves with the slot number, so a stack that binds a port it cannot move cannot run in two slots at once. Variable names are the ones the project's stack already reads, so a compose file that interpolates `${PG_PORT}` works unchanged. `task check` fails when a definition is malformed, when a plot's own slots collide, or when a repository declaration lacks its slots table. The lookup validates all declarations through one shared validator before allocating resources.

## Rules

- The main checkout is never a slot. Slots live under `<repo>/.worktrees/`, one task per slot, one slot per session.
- Never tear down a slot whose session may be live without the operator saying so, and never from inside its worktree. A session releases its own slot only with `--self`, in harvest or on the operator's explicit cleanup request.
- A failure before the worker can open reverses allocation, including the branch, once the allocation was delivered and while it still points at its starting commit. Once terminal opening is attempted, a failure leaves the resources up and says to inspect the possibly live worker, never printing a cleanup command, so a live session never loses the stack under it.
- Ports are checked against the machine, not against a ledger. The definitions decide the numbers, the live check decides whether they can be taken now, and cross-plot overlap is a listing, not a fault.
- When a slot session hands off to a successor, its notes carry every question put to the operator and never answered, verbatim, so the swap is not where a pending question dies.
