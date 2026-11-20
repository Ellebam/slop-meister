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
- [Recovery](launcher-recovery.md)
- [Repositories](#repositories)
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

[Native worker startup](launcher-native.md) owns the client arguments, delivery evidence, protected selectors and write-tool preflight. Existing model, effort and disable-only options remain available. A Claude launch and redispatch reads the [Claude account](claude-accounts.md) selected in Orca again.

## File access and trust

Every launch grants file access to the vault selected by `SLOPMEISTER_VAULT`, defaulting to `~/.slopmeister/vault`. A Slopmeister worker also gets the Slopmeister checkout it was launched for, and the dispatcher gets the invoking checkout. Claude receives the grants in the protected `.claude/access-settings.json` as `permissions.additionalDirectories`, Codex as `writable_roots` in the workspace `.codex/config.toml`. A grant is file access, never permission to load vault configuration as instructions.

See [session repositories](#repositories) for initial and later additions. Companions use the existing workspace access and plot rules.

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

## Manager role and peer inboxes

Declare `--manager` only on the first dispatch. Redispatch keeps the saved role. The role grants group monitoring and only the exact operator-ordered worker approval relay described in [Manage sessions](../src/skills/plot-session/manage.md). It also performs [verified automatic context recovery](../src/skills/plot-session/dispatcher.md#automatic-context-redispatch) only for its own group. Context recovery needs no operator order or Night mode and grants no terminal-input or other write authority. The role grants no broader permission. Capacity resumes remain bounded to the documented exact stop. The launcher prepares each task's own inbox before the model starts. Informational peer mail needs no separate participant approval and never supplies operator authority.

## Repositories

Repeat `--repository <main-checkout>` to add source repositories in the session's plot. Each gets the task branch in `<primary>/.slopmeister-repos/<basename>`. Duplicate repositories or names refuse before preparation. A companion with an origin starts from its freshly fetched advertised default branch. The source checkout stays on its current branch and commit. A local-only companion without origin starts from its local HEAD. A repository with no commit, including a clone of an empty origin, gets an orphan task branch without a bootstrap commit. Any other origin without an advertised default refuses, including an empty origin when the source already has commits. The primary remains the launcher, issue and notes identity. Companions are ignored by the primary Git repository and remain separate Git worktrees, not submodules.

After the operator approves an additional repository, run `bin/slopmeister repository add --workspace <primary> --repo <main-checkout>` from the unchanged invoking Slopmeister checkout. Native approval covers that exact addition. It creates no worker and uses the client's existing workspace access. `repository status --workspace <primary>` verifies and lists the members. Every member retains its own Git identity, remote and saved permissions. Changed plot permissions require a scope decision rather than a live policy rewrite. If delivery differs, run the quoted retry from a trusted checkout that matches the launch source and permissions. If none is available, keep the worktree and use a fresh session name with all approved repositories. Use the primary's fixed shipping helper for every member. It validates membership and the target's permissions before any write.

The saved state records pending creation before allocating a companion and marks it ready after installation verifies. An installation failure rolls back only the worktree and branch created by that call, provided no new commit, product-file change or live worker appeared. Unknown ownership or a crash keeps the pending record for inspection. A successful rollback restores the previous member set so the same addition can be retried. Old sessions without the add capability keep their original behavior. OpenCode multi-repository sessions are refused.

An unborn companion can be frozen and copied for review before its first product commit. The candidate keeps its empty baseline commit in the private candidate store, never in the target repository. After committing, `candidate verify-commit --cwd <member> --commit <commit>` verifies that member's selected commit and every other recorded member at HEAD. A refusal names the member that blocks verification.

An empty GitHub origin has no default branch and cannot receive a pull request. Initial default-branch publication needs the operator's explicit order and is not part of repository add. The shipping helper gives a generic error for that case.

## The permission contract

[Permission contract](permissions.md) owns central decisions, native translations, global restriction delivery and their limits.

## Declared shipping

Preparation binds shipping to the plot's repository, its original origin URL and the task branch. Directory sessions cannot ship. With both commit and shipping `allow`, the [ship helper](../src/skills/ship/scripts/ship.py) pushes the task branch and creates or updates its pull request without asking. Otherwise the helper itself needs your explicit instruction through native approval.

The GitHub pull request helper pushes the task branch and refuses a changed destination or the default branch. It pushes only when the remote branch differs from HEAD and writes the pull request only when its title or body differ, reading each write back, so a rerun never repeats a confirmed write. For a different forge, pass `--push-branch <main-checkout> <branch>` at launch when the remote branch differs from the local task name. The branch must already exist before the [push-only helper](../src/skills/ship/SKILL.md) can push to it. The helper prints the confirmed commit and branch. Use the forge’s own merge request flow. The optional `--tag 0.2.1-dev1` also pushes that local pre-release tag if it points to the tested commit. Release tags, force-pushes, merges, releases and deployments require their own orders. [Issue ownership](issue-claims.md) covers ticket changes.

## Proof ownership and inbox setup

An operator-ordered disposable proof session uses `--proof-for <owner-name>`. The owner must have a saved launch record and a live terminal. The proof session keeps native approval, claims no issue and cannot ship. Redispatch preserves that restriction. The [proof-session procedure](../src/skills/plot-session/SKILL.md#proof-sessions) owns permitted input and cleanup.

Inbox setup requests full routing data from supported Orca versions, with a fallback only when the flag is unsupported. A setup failure adds a fixed notice to the first prompt. Delivery accepts exactly the original kickoff or that kickoff with the fixed notice. The worker must diagnose its own inbox, not borrow another session's identity.

## Model and effort

Fresh Claude and Codex workers use the model and high effort set in [the review defaults](../slopmeister/review/defaults.toml). The same file sets independent review defaults. Set `--model <name>` for an individual launch. Supply effort after the launcher’s `--` separator using your tool’s native option. A redispatch keeps the saved selection unless you override it. Higher effort can take longer and consume more model usage.

For recurring runs, see [weekly dependency updates and recaps](weekly-sessions.md).
