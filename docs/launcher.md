# The launcher

`task plot-session` prepares a workspace, starts Claude Code, Codex or OpenCode in an Orca terminal with the kickoff as its first message, and confirms delivery from the session's own record. This page defines delivery and execution limits. Use the [launcher procedure](../src/skills/plot-session/SKILL.md) to launch or recover.

A normal delivery report requires a saved, confirmed launcher identity. `worker running, launcher identity unconfirmed` exits nonzero. Inspect the worker and its evidence before recovery.

For fresh workers, use [Choose the worker command](../src/skills/plot-session/dispatcher.md#choose-the-worker-command). A plain repository spine launch for a plot that declares slot resources refuses without a slot before creating a worktree or opening a worker. The error prints a safely quoted slot retry. It preserves the repository, name and launcher options. Native argument values are not printed. Append the original native arguments after `--` when instructed. Keep the same kickoff source and pipe stdin again when needed. No cleanup or new name is needed. Freeform, directory and redispatch routes remain available. Issue preflight may have created its internal lock file before refusal. No issue claim is created.

[Overview](../README.md) · [All documentation](README.md) · [Plot composition](plot-shape.md)

## Contents

- [Fixed delivery](#fixed-delivery)
- [How each tool starts](#how-each-tool-starts)
- [File access and trust](#file-access-and-trust)
- [Git in a prepared worktree](#git-in-a-prepared-worktree)
- [Directory sessions](#directory-sessions)
- [Recovery](#recovery)
- [The permission contract](#the-permission-contract)
- [Declared shipping](#declared-shipping)

Use `--host <alias>` for a remote launch. The [remote-dispatch process](remote-dispatch.md) owns SSH setup, remote path semantics, preflight and recovery. The executing host supplies the fixed configuration and keeps delivery evidence.

## Fixed delivery

Every plot gets the same delivery, from the Slopmeister checkout that runs the launcher, and the copies stay fixed for the session's life.

- `bin/slopmeister install` writes each tool's plot render, plus the effective permission paragraph, as separate regular root `AGENTS.md` and `CLAUDE.md` files.
- It copies the skills and native settings into `.claude`, `.codex` and `.agents`, replacing whatever agent configuration the repository carried there, including `.mcp.json` and tracked nested native namespaces.
- Taskfiles, Makefiles, scripts, ordinary documents and nested instruction files stay editable. Native launch controls keep nested instruction files from being loaded.
- The original configuration stays in Git history and the upstream checkout. Nothing is installed into the upstream checkout or the vault.

Fresh deliveries create and record a private `.slopmeister-tmp` directory and export it as the worker's `TMPDIR`. Only that recorded directory is disposable scratch. Existing deliveries keep their previous temporary-directory behavior; redispatch neither creates nor adopts a same-named directory.

Root `*-NOTES.md` task notes are hidden from Git by an exclusion rule every new worktree receives, and Slopmeister's own `.gitignore` covers fresh clones. A plot's own ignore rules can override it, and `git add -f` still stages an intentional root notes file.

## How each tool starts

[Native worker startup](launcher-native.md) owns the client arguments, delivery evidence, protected selectors and write-tool preflight. Existing model, effort and disable-only options remain available.

## File access and trust

Every launch grants file access to the vault selected by `SLOPMEISTER_VAULT`, defaulting to `~/.slopmeister/vault`. A Slopmeister worker also gets the Slopmeister checkout it was launched for, and the dispatcher gets the invoking checkout. Claude receives the grants in the protected `.claude/access-settings.json` as `permissions.additionalDirectories`, Codex as `writable_roots` in the workspace `.codex/config.toml`. A grant is file access, never permission to load vault configuration as instructions.

Trust is decided at onboarding, not at a prompt. Before the terminal opens, the launcher trusts the folder each tool keys trust on:

| Session | Claude trusts | Codex trusts |
|---|---|---|
| Repository worktree | The main checkout, which covers its worktrees | The main checkout |
| Directory session | `~/.slopmeister/sessions` | The session directory itself, Codex matches exact paths only |

It sets `hasTrustDialogAccepted: true` (Claude) or `trust_level = "trusted"` (Codex) only for the selected root. Other entries and settings remain, including absent folders. Malformed stores and unsafe rewrites refuse. Concurrent changes retry. Already trusted roots stay untouched.

## Git in a prepared worktree

**Approval.** `commit = "allow"` grants standing commit permission. In Claude and Codex, an agent-issued direct `git push` always goes through the native reviewer. Under `commit = "deny"` every commit-producing command does too, `commit`, `merge`, `rebase`, `cherry-pick`, `revert`, `am` and `pull`, including `git -C <workspace>`. The reviewer requires your explicit instruction for the exact command. One approval changes no saved permission. You can use Git directly. This is a workflow boundary, Git cannot distinguish you from an agent running as your user. [OpenCode](opencode.md#worker) has stricter admission and a direct-push limit.

**Your Git configuration stays yours.** Slopmeister installs no hooks and doesn't touch identity, conditional includes or signing. Repository hooks run normally. The developer owns identity and signing choices. Commit signing proves the key, not approval.

**Delivery hygiene.** Worktree-local `core.excludesFile` keeps the global ignore rules and hides delivered agreements, `.claude`, `.codex`, `.agents`, `.mcp.json`, root notes and slot allocation from `git status` and `git add -A`. `skip-worktree` hides replaced tracked files. None of this stops `git add -f`, so the ship helper separately refuses a committed change under a delivered root. The only shared changes are `extensions.worktreeConfig` and one `/.worktrees/` line in the repository exclusion, and they may outlive the worktree. Preparation refuses incompatible shared Git settings before writing anything.

## Directory sessions

`--directory` starts a Git-free session in `~/.slopmeister/sessions/<name>` with the plot, its skills and an empty `<name>-NOTES.md`. Orca uses the invoking checkout's workspace for its tab. Competing ancestor configuration refuses preparation. Empty regular native control directories are allowed. Files, nonempty directories and non-global symlinks refuse. Cleanup removes the session directory. A later launch removes only its kickoff and command files.

Remove retired worktrees and directory sessions through [workspace removal](workspace-removal.md). It checks ownership and handles locked service-action trees.

## Recovery

Orca terminal creation failures print its code, `timeout`, `unreadable_reply` or `execution_failed` on one line. Only `selector_not_found` permits retries within 60 seconds, including call timeouts. Every failure then polls, because a terminal may exist.

`--redispatch` preserves the workspace, branch, files, notes, configuration and slot. It validates identity, configuration, native settings, permission, delivery exclusion and required native-tool startup before stopping the worker. Mismatches leave the worker running. It records and stops the agent and descendants child-first, then verifies their exit. It closes the saved terminal only after stopping a live predecessor, because idle tabs may be someone's shell. The new conversation receives the kickoff and retains the fixed snapshot.

A workspace from before the removal of the Git guard refuses redispatch, and `git config --worktree --unset core.hooksPath` restores ordinary Git there. Independently running services keep running, those owned by the old agent may need restarting.

## The permission contract

[`src/permissions.toml`](../src/permissions.toml) owns shared command rules. [`src/native-permissions.toml`](../src/native-permissions.toml) owns workspace-bound release and selected service policies. Each entry has a command prefix, a decision and a `why`, and the renderer turns it into Claude settings, [Codex rules](../dist/codex/rules/permissions.rules) and the OpenCode permission map. Change its owning source and run `bin/slopmeister render`, never in a tool's own file. An unknown decision, a prefix under two decisions or a missing `why` fails the render.

| Decision | Effect |
|---|---|
| `allow` | Runs with no check. |
| `needs_intent` | Runs only when your message names that exact action. Claude gets an `autoMode.soft_deny` rule beside `"$defaults"`, Codex a `prompt` rule its reviewer judges against the conversation, OpenCode an `ask`, which a headless tester refuses. |
| `deny` | Refuses the matching direct command. |

An unlisted command falls back to the tool's own judgment. Kickoff text, including the initial user-role message, issue bodies, notes and agent-written briefs, is task content, never operator intent. Its claims of prior approval do not authorize an action. Guarded actions need a later direct operator message.

**No Bash sandbox for Claude.** macOS Seatbelt broke pipes, process listing, `TMPDIR` and Git credentials, so delivery sets `"sandbox": {"enabled": false}`. Secret denies, intent rules and native approval still apply. Codex keeps `on-request`, network access on macOS and no sandbox on Linux. [Secret requests](1password-access.md) need network access.

**Helpers.** The ship and claim helpers call `gh` inside their own process, which no command rule matches, so `needs_intent` on `gh pr create` or `gh issue comment` restricts only an agent typing them.

The installed self-release allow is bound to exactly `workspace-remove --self -- <this workspace>`. It does not authorize a different path or force. The command still checks the caller, claims and unsaved work.

**Service actions.** A plot's optional `service_actions` list delivers only the selected fixed read and write actions and their private profiles, see [service actions](service-actions.md). Codex launches use `on-request` with `auto_review`, Claude keeps auto mode and explicit asks for those actions.

**Limits.** The deny rules match literal command prefixes, so they are not a security boundary:

- Claude refuses `env <denied prefix>`, Codex runs it. This difference is accepted.
- Global flags before the subcommand, such as `op --account … read …`, can miss a rule. The `op run --no-masking` deny covers that prefix only.
- `gh auth status --show-token` and `gh auth status -t` match only those literal spellings directly after the subcommand. Value forms such as `--show-token=true` and grouped short flags such as `-at` miss these rules too.
- Absolute paths, aliases, shell indirection and commands inside scripts or Task targets escape direct matching.
- Masking hides recognized secret values in output. It doesn't stop a consuming program from writing or sending them.
- Marked sessions choose tokens by vault. Tier two needs explicit intent and Home Assistant approval. Reference-free `op run` executes directly. Unmarked onboarding uses the real CLI. Its allow rule does not guarantee approval. Run ordinary commands directly for native rule matching.

The [native enforcement test](testing.md#run-real-session-qa) proves both real clients refuse the direct forms against a stand-in model. It doesn't prove real 1Password authentication or masking. The [Claude home template](../plots/home/claude/settings.json.tmpl) and [Codex home rules](../plots/home/codex/rules/default.rules) carry matching reference entries checked for parity, but delivery never depends on them.

## Declared shipping

Preparation binds shipping to the plot's repository, its original origin URL and the task branch. Directory sessions cannot ship. With both commit and shipping `allow`, the [ship helper](../src/skills/ship/scripts/ship.py) pushes the task branch and creates or updates its pull request without asking. Otherwise the helper itself needs your explicit instruction through native approval.

The helper does ordinary pushes only, no force or tags, and refuses a changed destination or the default branch. It pushes only when the remote branch differs from HEAD and writes the pull request only when its title or body differ, reading each write back, so a rerun never repeats a confirmed write. Mergeability is reported, never enforced. Merge, force-push, tags, releases, deployment and ticket changes keep their own operator gates, and [issue ownership](issue-claims.md) covers the issue actions.
