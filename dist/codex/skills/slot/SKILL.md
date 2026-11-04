---
name: slot
description: "Allocate an isolated worktree with its declared ports and resources, then launch. Follow the dispatcher worker-command rule for fresh workers and use a slot when a task needs the project stack."
---

# Slot

A slot owns one worktree, its deterministic port set and any declared Compose project and data directory. Its resources are named `<plot>-slot<N>`. The declaration is `plots/<plot>/plot.toml`. The worker receives its allocation in `.slot.env`. `docs/slots.md` in the invoking Slopmeister checkout owns the schema and recovery contract. Slots live under `<repo>/.worktrees/`, never in the main checkout. One task per slot, one slot per session.

## Select the route

Follow [Choose the worker command](../plot-session/dispatcher.md#choose-the-worker-command). A directly launched freeform task needs a slot when it uses the project stack. A freeform task that runs nothing may use the plain launcher. A declaration with `none = true` uses the plain launcher.

Use the [launcher naming rule](../plot-session/SKILL.md) and the full `<plot>-` prefix for new sessions. Recover and release existing slots by their saved names.

For remote allocation, add `--host <alias>` to `slot:up`, quote paths and run status and release on the owning host. Follow `docs/remote-dispatch.md` under the invoking checkout.

## The ritual

1. From the Slopmeister root, run `task slot:up -- <repo> <plot> <name> [--slot <n>] [launcher args]` with the kickoff on stdin. Require the launcher's confirmed delivery. Allocation selects the lowest free number, checks actual listeners, and reports any collision. Fixed configuration, the allocation, declared commit permission, ready Compose services and successful declared repository setup must precede worker opening. Setup output remains ordinary untracked or ignored work. Inspect it before any explicit removal.
2. Read back and report the returned allocation with the launcher's report, including the slot, worktree and ports. Do not infer resources from another slot.
3. Run `task slot:status -- <repo>` only when asked. It reports live resources, listeners, stray ports and workers. Without a repository it lists expanded definitions and permitted cross-plot overlap. Never poll it on a loop.
4. Release only under the operator's order or through harvest. From the main checkout, use `task slot:down -- <repo> <plot> <saved-name>`. A worker removes its own slot only with `--self`. Other live workers and active issue claims refuse release. Stop or harvest/abandon them through their owning route first. Uncommitted and unknown ignored work require `--force` with accepted loss. If its worktree was removed by hand, use the explicit `--slot <n>` recovery from the contract. Teardown targets only resources with the allocation's exact project label, data and worktree. The branch, trust entry and kickoff stay.

Before terminal opening, failed preparation reverses allocation. It deletes an allocated branch only after delivery and while still at the starting commit. After opening is attempted, preserve resources and inspect the possibly live worker before cleanup. Never substitute a cleanup retry for that inspection.

A definition is written once per plot, by a person, and reviewed at commit like a plot fragment. Before writing a definition, read the project's Compose files and environment examples. Reuse its variable names. Every declared port must move with the slot number. The shared validator requires a slots table for every repository and checks intra-plot collisions. Allocation checks live listeners. Cross-plot overlap alone is not an error.

A successor's handoff keeps every unanswered operator question verbatim.
