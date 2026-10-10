# Architecture

Slopmeister is one Python package that dispatches and manages agent sessions and proves their work. This document answers four questions for a new maintainer: which command to run, where a new test belongs, how modules may depend on each other, and which checks CI owns versus the workstation. The [testing guide](testing.md) covers the commands in depth.

## The package

The product runs from the checkout through one entry script, `bin/slopmeister <command>`, or `python3 -m slopmeister`. Task targets in `taskfiles/` are the maintainer interface and call that script. Each command is one module with a `main(argv)` function, registered in `slopmeister/cli.py`. The Linux approval broker uses a pinned package revision, reached through an installed symlink. A session's `op` is the session program `slopmeister/session/secret_run.py`, installed with the home layer at `~/.local/bin/op` and switched on by the launcher's session mark.

| Location | Owns | Entry |
|---|---|---|
| `host/` | Optional Linux service roles, plain HA configuration and synthetic host checks | `task host:*` through `taskfiles/host.yml` |
| `slopmeister/claims/` | GitHub issue ownership backed by workspace evidence | `claims` |
| `slopmeister/check/` | Check catalogue, bounded runner and run ownership | `check` |
| `slopmeister/dispatch/` | Standing dispatcher launch | `dispatch` |
| `slopmeister/install/` | Fixed session configuration, snapshots, trust and hooks | `install` |
| `slopmeister/launch/` | Worker launch and recovery | `plot-session` |
| `slopmeister/opencode/` | OpenCode launch and tester integration | Library used by `plot-session` and `tester` |
| `slopmeister/plots/` | Plot declaration, validation and queries | `plots` |
| `slopmeister/quality/` | Budgets, import rules, field identifiers and plot style | `quality` |
| `slopmeister/render/` | Rendering sources and plots for both tools | `render` |
| `slopmeister/review/` | Independent review and final-result replay | `review` |
| `slopmeister/sandbox/` | Opt-in local Jira and Confluence sandbox | `sandbox` |
| `slopmeister/secret_ask/` | Approval broker, relay and once-only secret delivery | `secret-ask` |
| `slopmeister/session/` | Self-contained delivered session programs | No direct command |
| `slopmeister/session/service_actions/` | Delivered native read and write actions | No direct command |
| `slopmeister/slots/` | Target slot allocation, inspection and release | `slots` |
| `slopmeister/spine/` | Frozen repository candidates and tester composition | `candidate` |
| `slopmeister/spine/tester/` | Independent tester launch, validation and collection | `tester` |
| `slopmeister/threads/` | Worker occupancy and startup context | `occupants`, `startup-context` |
| `slopmeister/threads/timing/` | Spine session timing | `spine-timing` |
| `slopmeister/vault/` | Self-contained vault runtime boundary | No direct command |
| `slopmeister/vault/runtime/` | Markdown access, initialization, history, lint and retro | `vault` |
| `slopmeister/workstation/` | Machine doctor, home install, drift and kickoff checks | `workstation`, `kickoff` |
| `slopmeister/workspace_removal.py` | Guarded removal of one retired workspace | `workspace-remove` |

Operator-specific values stay outside Python and the public sources. Plots under `plots/` contain rules and knowledge pointers. Vault facts, service-action profiles and [private identifier patterns](context-layer.md#private-identifier-patterns) remain in their operator-owned stores.

## Delivered code

A launched session receives fixed copies of what it needs and never follows later source edits. The self-contained subpackage `slopmeister/session/` holds every program a session runs without the checkout: the protected launcher identity, in-session verification, ship helper, selected service-action consumer and vault-todos. The installer copies that directory once per session into the session's private state directory and writes thin entries at the skill script paths. An entry resolves the snapshot relative to itself, never through the checkout, adds it to `sys.path` and calls one `main`. Tracebacks name real module files.

The same boundary serves vault access from repository worktrees and temporary directory sessions. The installer copies `slopmeister/vault/runtime/` byte-for-byte to `~/.vault-git/lib/slopmeister_vault/` and installs one small launcher at `~/.vault-git/bin/slopmeister-vault`. Markdown bytes and external Git own correctness. Its optional `obsidian` pass-through allows only read-only index and UI operations and bounds their process group. The launcher selects an absolute Python 3.14 path, Homebrew's on the Mac and the system's on Linux, and never imports a checkout. The scheduled whole-vault sweep remains the separate Bash job used by its existing applet.

The quality checker enforces both snapshot boundaries: `slopmeister/session/` and `slopmeister/vault/runtime/` may import only the standard library and their own subtree. A delivered module that reaches into the rest of the package fails the gate.

The optional `host` dependency group holds Ansible and its validation tools. Browser dependencies are pinned separately under `host/`. They do not widen the agent runtime or the delivered session library. [Host services](../host/README.md) owns installation and operator bootstrap.

## Dependency rules

The quality checker resolves absolute and relative imports and enforces these rules on every run.

- `slopmeister` never imports `tests` or `scripts`.
- `tests` may import `slopmeister` and `tests.support`.
- `slopmeister/session/` imports only itself and the standard library.
- `slopmeister/vault/runtime/` imports only itself and the standard library.
- No import cycles.
- No package module launches another repository script by path, loads a file with `runpy`, or patches `sys.path`. Reuse is an import. The one exemption is the check catalogue, whose job is launching checks.

## Budgets

`slopmeister quality` enforces these size limits.

| What | Limit |
|---|---|
| Python and shell files | 250 lines |
| Constant-only Python modules and other runtime sources, including instructions and configuration | 400 lines |
| Global instruction source | 200 lines |
| Functions | 30 lines |
| Parameters | 3, or 5 for a test function |
| Nesting depth | 3 |
| Cyclomatic complexity | 10, enforced by Ruff |
| `README.md`, `docs/*.md`, `src/skills/*/SKILL.md` and `plots/*/skills/*/SKILL.md` | 2,000 words |

Words are whitespace-separated, including tables and code. Repository documents have no line cap. Shared and plot-owned skill entrypoints retain their runtime-source line cap. Ruff also enforces statement and branch limits, import order and formatting. Shellcheck uses the inventory's Bash classification, including extensionless plot launchers.

`quality-allowlist.json` holds operator-approved exceptions with a path, metric, owner, rationale, exact ceiling and lower target. Targets are at most 400 lines or 2,000 words. Growth, missing paths and obsolete entries fail. Two repository documents have word exceptions, each capped at its delivered size. `bin/slopmeister quality --inventory` shows the exceptions and runtime `oversized_400` count.

## Tests

Tests live under `tests/` by layer first, then subsystem. The directory is the layer, and `tests/conftest.py` stamps the marker from the path.

| Layer | Holds | Runs where |
|---|---|---|
| `tests/unit/` | No subprocess, no filesystem outside `tmp_path` | Every push, CI and workstation |
| `tests/integration/` | Portable tests driving the product through subprocesses with fakes | Every push, CI and workstation |
| `tests/native/` | The real machine, Orca, the real Codex binary, launchd or systemd, installed drift | Workstation only |
| `tests/live/` | Real sessions with model inference, collected only when the command names `tests/live` | Only through `task test:live`, with the operator's consent |

A new test goes into the lowest layer that can observe the bug. Shared builders live in `tests/support/`: scratch repositories, fake binaries on PATH, small source trees. Unit and integration tests run under xdist by default. A test that binds a socket or drives a process tree declares a named group so it never runs beside another test of that group, see [CONTRIBUTING.md](../CONTRIBUTING.md#writing-tests). Every test has a 60-second timeout unless it carries a marked reason. `tests/data/` holds inputs, never executable setup.

## The gate

`slopmeister/check/catalogue.py` declares every core check once with its layer and kind. `task check` runs the whole catalogue with bounded concurrency and fails on any failed, missing, duplicate or interrupted case. GitHub-hosted Ubuntu CI runs three jobs from the same catalogue, `task lint`, `task quality` and `task test:portable`, so a failure is diagnosable by job. Native checks and real-session acceptance are excluded from CI by their layer, not silently skipped, and the [testing guide](testing.md) says what each needs.

The host layer uses explicit optional tasks rather than joining the core catalogue. `host:lint` and `host:syntax` check deployment code without applying it. `host:test` runs the role and panel fixtures. `host:ha:check` validates configuration in its own contained, pinned image. Root lint and quality still cover host source files.
