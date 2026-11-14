# Architecture

Slopmeister is one Python package that dispatches and manages agent sessions and proves their work. This document answers four questions for a new maintainer: which command to run, where a new test belongs, how modules may depend on each other, and which checks CI owns versus the workstation. The [testing guide](testing.md) covers the commands in depth.

## The package

The product runs from the checkout through one entry script, `bin/slopmeister <command>`, or `python3 -m slopmeister`. Task targets in `taskfiles/` are the maintainer interface and call that script. Each command is one module with a `main(argv)` function, registered in `slopmeister/cli.py`. A session's `op` is the session program `slopmeister/session/secret_run.py`, installed with the home layer at `~/.local/bin/op` and switched on by the launcher's session mark.

| Location | Owns | Entry |
|---|---|---|
| `host/` | Optional Linux service roles, plain HA configuration and synthetic host checks | `task host:*` through `taskfiles/host.yml` |
| `slopmeister/claims/` | GitHub issue ownership backed by workspace evidence | `claims` |
| `slopmeister/check/` | Check catalogue, bounded runner and run ownership | `check` |
| `slopmeister/dispatch/` | Standing dispatcher launch | `dispatch` |
| `slopmeister/install/` | Fixed session configuration, snapshots, trust and hooks | `install` |
| `slopmeister/launch/` | Worker launch and recovery | `plot-session` |
| `slopmeister/opencode/` | OpenCode worker launch and native evidence | Library used by `plot-session` |
| `slopmeister/plots/` | Plot declaration, validation and queries | `plots` |
| `slopmeister/quality/` | Budgets, import rules, field identifiers and plot style | `quality` |
| `slopmeister/render/` | Rendering sources and plots for both tools | `render` |
| `slopmeister/review/` | Independent review and final-result replay | `review` |
| `slopmeister/session/` | Self-contained delivered session programs | No direct command |
| `slopmeister/session/service_actions/` | Delivered native read and write actions | No direct command |
| `slopmeister/slots/` | Target slot allocation, inspection and release | `slots` |
| `slopmeister/spine/` | Frozen repository candidates, including the complete session set | `candidate` |
| `slopmeister/repositories.py` | Same-plot repository attachment, using saved membership from `session/repositories.py` | `repository` |
| `slopmeister/threads/` | Worker occupancy and startup context | `occupants`, `startup-context` |
| `slopmeister/threads/timing/` | Spine session timing | `spine-timing` |
| `slopmeister/vault/` | Self-contained vault runtime boundary | No direct command |
| `slopmeister/vault/runtime/` | Markdown access, initialization, history, lint and retro | `vault` |
| `slopmeister/workstation/` | Machine doctor, home install, drift and kickoff checks | `workstation`, `kickoff` |
| `slopmeister/workspace_removal.py` | Guarded removal of one retired workspace | `workspace-remove` |

Operator-specific values stay outside Python and the public sources. Plots under `plots/` contain rules and knowledge pointers. Vault facts, service-action profiles and [private identifier patterns](context-layer.md#private-identifier-patterns) remain in their operator-owned stores.

## Global agent configuration

These are the native global inputs. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` can relocate the respective stores. The home installer targets the normal home locations. [Claude settings](https://code.claude.com/docs/en/settings), [Claude memory](https://code.claude.com/docs/en/memory), [Codex configuration](https://developers.openai.com/codex/config-basic), [instructions](https://developers.openai.com/codex/guides/agents-md) and [rules](https://developers.openai.com/codex/rules) own native discovery and precedence.

| Global input | Writer | Check or ownership boundary |
|---|---|---|
| `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` | Home install from rendered global source | Drift compares bytes |
| `~/.claude/settings.json` | Home install owns `autoMemoryEnabled = false`, Bash denials and missing central `autoMode.soft_deny` entries | Drift checks these values. Other settings, non-Bash denials, allows and existing soft-deny entries stay intact |
| `~/.codex/rules/permissions.rules` | Home install from the central contract, excluding allows | Drift compares the complete owned file |
| `~/.codex/rules/default.rules`, other `rules/*.rules` | Codex saves approvals, or operator | Native client loads them. Slopmeister leaves private saved commands unread and unchanged |
| `~/.codex/config.toml` | Home install owns the top-level keys and `[features] memories = false` of `plots/home/codex/config.toml.tmpl` | Drift checks those values. Other keys remain operator-owned |
| `~/.codex/hooks.json` | Orca and the operator. The operator appends the notes-after-compaction group once, as described below | Codex runs only hooks trusted by hash. `/hooks` reviews them |
| `~/.codex/AGENTS.override.md`, `~/.claude/rules/**/*.md` | Operator | Native instruction discovery. No managed source to compare |
| `~/.claude/{skills,commands,agents,plugins}/**`, `~/.agents/skills/**`, `~/.codex/{skills,plugins}/**` | Client, plugin installer or operator | Native discovery. User extensions have no Slopmeister baseline |
| `~/.claude.json`, `~/.claude/.credentials.json`, `~/.codex/auth.json`, native credential stores | Client | Native login checks only. Credentials and account state are not configuration payloads to print or replace |
| `~/.claude/projects/*/memory/`, `~/.codex/{memories,memories_v2}/`, `memories_1.sqlite` and its WAL/SHM files | Forbidden private memory | Doctor flags populated stores using metadata, including active relocated roots. Unreadable stores are unknown. General session databases remain untouched |
| `/etc/claude-code/*`, `/Library/Application Support/ClaudeCode/*`, `/etc/codex/*.toml`, managed device policy | Administrator or native management | Native precedence and diagnostics. Home install has no authority over system policy |

After a compaction, both clients run a `SessionStart` hook with source `compact` and add its output to the model's context. The home install copies `plots/home/claude/notes-after-compaction.sh` to `~/.claude/`. It prints the start of the workspace's root `*-NOTES.md`, marked as the session's own possibly stale notes. Launched Claude sessions receive the registration from `src/claude/settings.json`. Codex runs only hooks the user trusted, so its registration lives in the user layer. Once per machine, append this group to the `hooks.SessionStart` list in `~/.codex/hooks.json`, after Orca's entry, then trust it with `/hooks` in Codex.

```json
{"matcher": "compact", "hooks": [{"type": "command", "command": "~/.claude/notes-after-compaction.sh", "additionalContextLimit": 4000}]}
```

Without `additionalContextLimit`, Codex cuts hook output at about 2,500 tokens and passes a preview.

Existing soft-deny strings are kept, including superseded central strings. Drift checks current strings are present and does not identify older retained versions. Removing retained strings requires a separate operator order.

`src/permissions.toml` remains the command-policy source. Global installation copies restrictions only, preserving session-only allow scope. Repair both policy entries with `task home:install -- .claude/settings.json .codex/rules/permissions.rules` on the operator's order. It keeps private backups and leaves saved approvals intact. Start a new client to load newly installed rules. [Workstation](../src/skills/workstation/SKILL.md#read-both-machines) owns the existing peer route and unknown results.

## Delivered code

A launched session receives fixed copies of what it needs and never follows later source edits. The self-contained subpackage `slopmeister/session/` holds every program a session runs without the checkout: the protected launcher identity, in-session verification, ship helper, bounded CI rerun helper, selected service-action consumer and vault-todos. The installer copies that directory once per session into the session's private state directory and writes thin entries at the skill script paths. An entry resolves the snapshot relative to itself, never through the checkout, adds it to `sys.path` and calls one `main`. Tracebacks name real module files.

The same boundary serves vault access from repository worktrees and temporary directory sessions. The installer copies `slopmeister/vault/runtime/` byte-for-byte to `~/.vault-git/lib/slopmeister_vault/` and installs one small launcher at `~/.vault-git/bin/slopmeister-vault`. Markdown bytes and external Git own correctness. Its optional `obsidian` pass-through allows only read-only index and UI operations and bounds their process group. The launcher selects an absolute Python 3.14 path, Homebrew's on the Mac and the system's on Linux, and never imports a checkout. The scheduled whole-vault sweep remains the separate Bash job used by its existing applet.

Native startup preflight drives each client protocol with the delivered writer configuration before opening a worker. Existing deliveries retain their saved pin format and scratch ownership on redispatch. Slot setup and independent check allocations share the slot owner. Check leases and the public ignored-work guard prevent unsafe cleanup.

The vault runtime separates path/environment selection, initialization, link resolution and retro routes so each module stays within budget. Legacy log callers remain explicit. Permission rendering reads general commands from `src/permissions.toml`, GitHub commands from `src/github-permissions.toml`, and workspace-bound/service policies from `src/native-permissions.toml`, each with one source.

The quality checker enforces both snapshot boundaries: `slopmeister/session/` and `slopmeister/vault/runtime/` may import only the standard library and their own subtree. A delivered module that reaches into the rest of the package fails the gate.

The optional `host` dependency group holds Ansible and its validation tools. Host browser-test dependencies are pinned under `host/`; the optional page-control CLI is pinned under `slopmeister/session/playwright/`. They do not widen the agent runtime or the delivered session library. [Host services](../host/README.md) owns installation and operator bootstrap.

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
| Python, shell and other runtime sources, including instructions and configuration | 400 lines |
| Global instruction source | 200 lines |
| Function parameters | 5, enforced by Ruff |
| Nesting depth | 3 |
| Cyclomatic complexity | 10, enforced by Ruff |
| `README.md`, `docs/*.md`, `src/skills/*/SKILL.md` and `plots/*/skills/*/SKILL.md` | 2,000 words |

Words are whitespace-separated, including tables and code. Repository documents have no line cap. Shared and plot-owned skill entrypoints retain their runtime-source line cap. Ruff also enforces statement and branch limits, import order and formatting. Shellcheck uses the inventory's Bash classification, including extensionless plot launchers.

`quality-allowlist.json` holds operator-approved exceptions with a path, metric, owner, rationale, exact ceiling and lower target. Targets are at most 400 lines or 2,000 words. Growth, missing paths and obsolete entries fail. The remaining service-actions reference has a word exception capped at its delivered size. `bin/slopmeister quality --inventory` shows the exceptions and runtime `oversized_400` count.

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

The host layer uses explicit optional tasks rather than joining the core catalogue. `host:lint` and `host:syntax` check deployment code without applying it. `host:test` runs the role and panel fixtures. `host:ha:check` validates configuration in its own contained, pinned image. Root lint and quality cover host source files. CI runs the four host tasks in a separate job. The [release job](releases.md) waits for all core and host jobs before publishing a new version.
