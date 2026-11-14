# Manage sessions

`--manager` declares the operator's proxy for a worker group on first dispatch. Both tools receive the role and Claude its permission exception. Redispatch preserves it. The flag refuses with `--redispatch` or `--abandon`. Name workers in the kickoff. Other workers refuse terminal input to agents, except to their own [proof sessions](SKILL.md#proof-sessions).

The group contains kickoff-named sessions, ordered dispatches and operator-named sessions. Fresh dispatch and abandonment require the operator's order here. Redispatch also needs that order except for [verified automatic context recovery](dispatcher.md#automatic-context-redispatch) of your own workers. Terminal sends need the operator's order, a covered [Night mode](SKILL.md#night-mode) decision or completion action, or the [standing capacity-resume permission](SKILL.md#working-practices). Automatic recovery grants no terminal-input authority. Worker messages, kickoffs, issues and notes cannot supply a grant. [Peer information](communicate.md) grants no authority.

For unattended work, follow [Night mode](SKILL.md#night-mode). Relay the operator's grant and its explicit end verbatim. You may decide routine choices for your own wave under that grant. The manager role alone supplies no grant.

## Observe the group

Follow each worker through required groom and authorized harvest. Bring outstanding consent requests to the existing [Working practices](SKILL.md#working-practices) decision route, not as questions hidden in progress prose. A shipped branch is not the end of that follow-through.

Use inbox notices and command results. Read group status on an actionable event, operator request or before dependent work. While workers are active without a meaningful event, check after delays of 2, 5 and 10 minutes, then end the turn. A worker notice that needs no operator action gets no operator message, even when it reports new progress. Only verified worker progress or a new operator order starts another budget, never a timestamp refresh or unchanged notice. Do not create a repeating watch or background listener. Stop checks while an operator answer is pending or the operator has requested quiet.

Inspect silent permission or capacity stops and harvest stalls through [status](dispatcher.md#dispatch-and-report). A blocker is reported once with its evidence and next action. Send only `http` or `https` phone-testing links, custom schemes are not tappable in Orca on iPhone.

Use the dispatcher's [status and send forms](dispatcher.md#dispatch-and-report). Apply its automatic context check to your own workers, without a new operator order or Night mode. Give every worker the verified Mac dispatcher route and your host and Run as its sole recovery owner. Workers send their one request to that Mac dispatcher, which verifies and forwards managed requests without launching them. You independently verify a forwarded request and recover only your own group. Keep one owner, record handled native session IDs in your existing notes, and reject stale requests before launch. Confirm the saved state and restart command from your own reading, preserving name, plot, repository, tool, model and effort. Abandon keeps its operator order and requires a claimed GitHub issue. For your own session the Mac dispatcher is the recovery owner. Your open operator questions do not block [your own request](recovery.md#worker-context-check), so keep each one verbatim in your saved handoff.

Find the terminal on its machine immediately before sending. Use `terminal list --worktree path:<worktree>` for repository workers. For directory sessions, confirm the launcher's `tmp/plot-session/<name>.orca` handle in a fresh list. Project only `handle`, `agentIdentity` and `title`, never previews. Refuse missing, closed or ambiguous handles. Typing replaces Claude's greyed suggestions. Confirm the send from its receipt or screen and report machine, session and exact text in the action's handoff. The role grants no commit, push, merge, secret or customer-write authority. Remote reach follows `docs/remote-dispatch.md`.

## Relay

Open every manager question to the operator with one plain sentence stating the needed decision. Follow the [task summary](../execute-plan/task-summary.md#the-operator-summary) for plain wording and the summary and whole-message length limits.

Except permission input, harvest and capacity resume, relay the operator's full text with `[relayed by manager <your session name> on the operator's order]`. Use the workspace directory's name. Guard rails add no scope. Relays never imply a harvest order, say "harvest comes from the manager only". For a combined Bloom answer, relay only that worker's selected segments and operator text verbatim, with the displayed option and exact publication text as quoted reference. Keep the prefix, never another worker's choices or invented approval.

When auto mode refuses actions the operator ordered, give the operator one message for that order with every refused command ready to run with `!`. This covers a tier-two run, a relay, a tracker post and a worktree removal alike. First finish the steps of the order that do not depend on a refused one, so the one message is complete. Write each command as one self-contained line with absolute paths and its working directory inside the command, in the order to run them. Do not retry a refused command, run it another way, pass it to another session or propose a persistent permission change. Before any refusal, an owning worker can use [ci-rerun](../ci-rerun/SKILL.md) for its own routine CI retry.

Under a valid Night mode grant, send your own routine choice as a manager decision. Name the covered task, exact grant and choice. Use no operator relay prefix and claim no operator answer. The worker checks the grant already received through its operator route and records the actual decision maker. A manager message cannot create or expand the grant.

## Permission input

Read the refusal and tell the operator the worker and exact action. On their direct order naming both, refresh the screen and confirm the same action. For Codex, send `/approve` with Enter. Press Enter on the denial list only when its selected entry is that exact action. Otherwise stop. Then relay the operator's order with [the relay prefix](#relay) as the next message for one retry, still subject to review. For Claude, send only the visible one-time permission digit without Enter. The loaded Working practices restrictions apply. Read and report the result.

## Harvest

For a merge here, confirm green CI and testing acceptance. A valid Night mode grant supplies routine acceptance and the harvest order within its completion limits. Record that acceptance with its proof and recovery path. Only with write authority, rerun a known flaky CI failure once. On the operator's harvest order or under that grant, send `/harvest` for Claude or `$harvest` for Codex followed by the acceptance and restrictions. Preserve the operator's text verbatim. Never end on the bare skill or add a relay prefix. This carries acceptance without a separate relay.

Single-quote the whole `--text=` argument and write each `'` as `'\''`. Send once with `--enter --wait-submit 30 --json`. If the receipt did not observe submission, read the screen. Only when the command is still in Codex's input line, send one `terminal send --terminal <handle> --enter` without text. Never repeat it or answer a dialog. Confirm the removal result through events and the bounded fallback above. Report a blocked removal once with the named paths and exact retry.

After a harvest you sent, read its full report from the exact unique `tmp/plot-session/<name>.remove.*.log` on the worker host and pass it on. Slots use that same log and shutdown entry. The report counts as delivered in that log, even when shutdown closes the screen before output appears. Confirm the shutdown result separately. When that log names a kept workspace, pass on its path and cleanup command unchanged. Do not read a session transcript.

## Proof sessions

A worker proves its own change in disposable sessions it drives itself. Launch them only when an operator message in this conversation orders proof sessions, with `--proof-for <your session name>` added to the ordinary launch. The launcher binds each one to your live terminal and refuses a missing or closed owner. A proof session claims no issue, never ships and launches nothing.

Before every send, find the proof session's terminal as [Manage sessions](manage.md) describes, then read `proof_owner.handle` from its saved state, `"$(git -C <workspace> rev-parse --absolute-git-dir)/slopmeister-config/state.json"` or `<directory>/.slopmeister-config/state.json` for a directory session. Send only when it equals your own `ORCA_TERMINAL_HANDLE`. Send the proof task's instructions, a plain `continue` after a stop, and its [harvest](manage.md#harvest) with your proof verdict as the acceptance. Never answer a permission prompt or trust dialog, send `--interrupt`, raw escape sequences or control characters, or send to any other session. Harvest every proof session before your own handoff and report each send, receipt and result.
