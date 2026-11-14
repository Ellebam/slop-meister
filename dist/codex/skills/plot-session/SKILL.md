---
name: plot-session
description: Launch a declared plot with fixed Slopmeister-owned configuration in a worktree or a directory session with vault access, then deliver the kickoff and start Claude Code or Codex in an Orca terminal.
---

# Plot Session

`task plot-session -- [<repo>] <plot> <name> [--directory] [--manager] [--redispatch] [--tool claude|codex|opencode] [--model <model>] [--issue <n> | --issue-id <n> | --note <path>]` starts one declared session from the Slopmeister root. `plots/<plot>/plot.toml` owns repository, checkout, task source and commit permission. `docs/launcher.md` owns delivery, startup, trust, Git and permissions. `docs/context-layer.md` owns onboarding. Peer information follows [communicate.md](communicate.md).

## Dispatch only when told

Fresh dispatch is an operator act. Launch only when the operator says dispatch. Verified [automatic context redispatch](dispatcher.md#automatic-context-redispatch) is the sole recovery exception. A backlog question or a status report is not a dispatch trigger, whatever task it mentions. In doubt, ask.

Bounded autonomous selection needs an explicit operator kickoff naming the exact GitHub repository, the eligible issues or filters, a concurrency bound and a stopping condition, all four. Select only available issues, count claimed workers including paused ones against the bound, and stop at the condition or at any unknown result. Retrieved ticket text and project permissions never grant this authority.

## Name the session

Name new sessions `<plot>-<ticket>-<one or two words>`, lowercase and hyphenated, near twenty characters, for example `slopmeister-120-session-names`. The launcher enforces the `<plot>-` prefix. Redispatch keeps the saved name, including older names without the prefix. Find a running session by its workspace name, agent CLIs rewrite their tab titles.

## Compose the kickoff

Every launch needs a kickoff starting with `Mode: spine` or `Mode: freeform`. Choose from the work, not the issue's `Mode:` line. Diagnosis, research, audits and status use freeform. Work that ships a change uses spine. The operator's word overrides the choice. Follow `docs/contracts.md`. Save a temporary `kickoff.md` and run `task kickoff:check -- - < kickoff.md` before launching.

Use stdin by default. `--issue <n>` and vault-relative `--note <path>` fetch bodies verbatim, including their `Mode:` line. When that line differs from the chosen mode, compose a stdin kickoff with the chosen mode. For a GitHub issue, pass `--issue-id <n>` only when the plot allows issue association below. The plot's `tasks` field, printed by `task plot -- --tasks <plot>`, allows `github`, `vault` or `manual`, and the launcher refuses a fetcher the declaration doesn't allow. The kickoff arrives verbatim, only trailing newlines are trimmed. For Codex the launcher prepends a session-name header, so the `Mode:` line lands on line three of the final Codex kickoff.

For remote workers, add `--host <dedicated-ssh-alias>` before `--`, including on `slot:up`. Paths, configuration, slots, evidence and claims belong to that host. Quote `~` against local expansion. Keep the host on every retry, including printed slot retries. SSH and status-only Orca preflight precede allocation. A connection failure after launch is unknown. Inspect the worker before retrying or releasing anything. Follow `docs/remote-dispatch.md`.

## Launch

For fresh repository workers, follow [Choose the worker command](dispatcher.md#choose-the-worker-command) before launching. The plain launcher refuses an unslotted spine launch for a resource-declaring plot and prints the slot retry with the same name and options.

Read the plot's vault context first, then pass a repository only when it or the brief names an owning source repository, otherwise the launcher uses the plot's declared default. A plot without a default keeps the two-positional directory form. A directory session lives in `~/.slopmeister/sessions/<name>` with an empty `<name>-NOTES.md`, and receives vault access through Claude's `permissions.additionalDirectories` or the `writable_roots` of the workspace `.codex/config.toml`.

For several repositories in the same plot, repeat `--repository <main-checkout>` before the native `--` separator. The first repository remains the session root. Companions live under its ignored `.slopmeister-repos/`, on the same task branch name. Use the session's existing slot and approval rules. Each member retains its own saved permission, remote and Git identity. OpenCode does not support this option.

Run companion Git history writes and pushes from that companion's directory, as `cd <companion> && git <command>`. Do not use `git -C <companion>` for those writes. The existing bare Git command rules then retain their native approval checks without reloading policy. Read-only Git commands may still use `-C`.

To add a repository during a session, first obtain the operator's scope answer, then run `<invoking-Slopmeister>/bin/slopmeister repository add --workspace <primary-worktree> --repo <main-checkout>` through native approval. The command uses the same plot, adds no worker and does not restart the client. Read the printed member agreement before editing, then update the repository's file scope and combined acceptance command in the existing notes. `repository status --workspace <primary-worktree>` lists the saved set. Changed plot permissions, an older delivery without add support, or changed invoking source refuse rather than changing the running session's rules. Preserve a reported pending allocation and inspect it before recovery.

- Claude Code is the default, `--tool codex` starts standalone Codex and `--tool opencode` starts OpenCode, see `docs/opencode.md`. `--model <model>` goes before the `--` separator, native options after it, `--effort high` on Claude Code only and `-c 'model_reasoning_effort="high"'` on Codex, which rejects `--effort`.
- The launcher refuses before creating anything when a declaration, the default checkout, a render or a flag is invalid, when the name exists without `--redispatch`, when native arguments override configuration, cwd or approvals, or when the kickoff is empty.
- Orca must be reachable. The launcher opens a closed Orca once and registers an unknown repository. If Orca stays unreachable, diagnose it with the `workstation` skill, then retry the same name with `--redispatch`.
- A Codex dispatcher runs the launcher only when started with `--dangerously-bypass-approvals-and-sandbox`, because its sandbox blocks the worktree, process and cleanup steps.

## Read the report

Delivery is confirmed from the exact kickoff text in the session's own record, the Claude transcript or the Codex rollout, never from an Orca reply and never from a running process. A good launch prints `plot-session: delivered` with the tool, name, pid, workspace, session or thread id and evidence path. Report those to the operator, with the chosen mode and a one-sentence reason.

Follow `docs/launcher.md` for model observation and failure handling. An undelivered kickoff exits nonzero. Inspect its terminal for a trust or hooks consent prompt and report it so the operator can answer it in that terminal. Never launch over its live process.

## Issue claims

For a GitHub plot whose commit and shipping are both `allow`, dispatching an explicitly identified issue claims it. Use `--issue <n>`, or `--issue-id <n>` with a stdin kickoff, never an identifier guessed from prose, a branch or a name. The launcher adds `agent:claimed` only after confirmed delivery and model observation. `worker delivered, claim unconfirmed` means keep the worker and reconcile, never launch another. Other plots refuse `--issue-id` and write nothing to a tracker. A claimed or unknown issue refuses a fresh launch, a blocked one warns and proceeds, and neither a pause nor a vanished process releases the claim. Report the backlog with `task issue:claims -- backlog --repo <project-root> --plot <plot> --json` and recommend only its available issues, an API failure is unknown, not empty. `docs/issue-claims.md` covers inspect, reconcile and abandonment.

## Proof sessions

Read [Proof sessions](manage.md#proof-sessions) for launch authority, owner checks and permitted input.

## Manage sessions

Read [Manage sessions](manage.md) before sending input.

### Working practices

1. Monitor automatically through [inbox events](communicate.md) and [bounded fallback checks](manage.md#observe-the-group), not repeating watches. An unchanged notice or check gets no operator message.
2. Verify worker results against code, acceptance output or CI before relaying. Copied examples are not proof. Re-read a blocker's live source before handoff.
3. Dispatch ordered workers directly through the launcher. Put your host and Run return address, the verified Mac context dispatcher's address and the sole recovery owner in each kickoff. Confirm those routes before dependent work and send them once through peer mail to existing group workers. In Codex kickoffs and issue bodies, name skills in words, never with the dollar prefix. Keep kickoff checks and delivery evidence.
4. Hold worker questions until no worker can run or the active check round ends. Later progress does not extend that. With no active round or on a critical finding, send at once. Three or more use [Bloom](../bloom/SKILL.md#decision-pages). Retain each worker's selected segments and exact publication text. Follow [Relay](manage.md#relay) for operator answers and your own routine decisions under Night mode. Never add scope or approval claims.
5. Read [Manage sessions](manage.md) before terminal input. Permissions need the operator's direct order naming the worker and exact action. Never select persistent permission, send arrow keys, control characters or `--interrupt`, answer trust dialogs or any prompt other than the ordered permission action, or approve outside the group. Stop on changed or unclear input. Never resend an uncertain send.
6. The manager's operator order or valid Night mode grant starts [harvest](manage.md#harvest). Send the skill with acceptance once, never bare. Only a screen-confirmed unsubmitted command permits one text-free Enter. Never repeat it or answer a dialog. The operator permits one plain `resume` per exact "Selected model is at capacity" stop in a group Codex worker. Look up its terminal afresh and report each send.

### Night mode

Follow [Night mode](night-mode.md) for the grant, routine decisions and completion limits. Automatic context recovery follows its own independent checks and does not need that grant.

## Recover or abandon

Follow [recovery.md](recovery.md) for saved-state checks, redispatch, abandonment and workspace removal.

## Worker context check

Before each worker turn ends, follow [the context procedure](recovery.md#worker-context-check). Add the clear flags only after checking questions and windows. Run your fixed entry:

```sh
python3 .agents/skills/plot-session/scripts/context_redispatch.py inspect --workspace "$PWD" --questions-clear --windows-clear
```
