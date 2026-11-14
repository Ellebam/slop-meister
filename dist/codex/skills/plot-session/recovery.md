# Recover or abandon

Before replacing a worker, ask it to save its state and restart commands, and confirm it has. After a crash only what's on disk survives.
```bash
task plot-session -- <repo> <plot> <name> --redispatch --tool claude < kickoff.md
task plot-session -- <plot> <name> --directory --redispatch --tool codex < kickoff.md
task plot-session -- <repo> <plot> <name> --abandon --handoff <absolute-notes> --tool <tool>
```

Redispatch stops the old worker and its descendants, verifies they are gone, waits up to ten seconds for terminal closure with one final bounded inventory check, and starts a fresh conversation in the same workspace, keeping its saved configuration, notes and slot. A terminal still present or an unreadable final inventory refuses without starting a replacement. When it refuses, fix what it names and retry the same name. When no process appears, it prints no runnable line, so look at the terminal before retrying rather than risk a second session. A slot is recovered the same way, never with `task slot:up`.

Abandon needs a saved nonempty handoff inside the workspace. It uses the same child-first stop and exit check, keeping the workspace, branch, notes and companions. Without an issue association, including manual-task, vault-task and directory plots, it touches no tracker and writes no claim. A claimed GitHub worker keeps its claim release and open issue. For a directory session use `task plot-session -- <plot> <name> --directory --abandon --handoff <absolute-notes>`. Add `--host <alias>` for a remote stop with a handoff on that host. After a closure refusal, inspect the worker and retry the same abandon command. Each claim-free abandon acts on the current worker, so check the session before repeating it.

For operator-requested removal of a retired or orphaned workspace, follow `docs/workspace-removal.md` in the invoking Slopmeister checkout. Use its `task --dir <invoking-Slopmeister> workspace:remove -- <absolute-workspace>` command on the machine that owns the workspace.

## Worker context check

Before every worker turn ends, inspect its launcher-confirmed native session with the [installed context check](SKILL.md#worker-context-check). This is the default without an operator order, Night mode or a manager. Check the task notes and the current question or lab/deploy window first. Add the two clear flags only when both are clear. Run the installed script, not another checkout's current source.

A session delivered as a manager may request with open operator questions, because it nearly always holds one. It first saves each open question verbatim in its handoff, with its options and recommendation, so its successor shows them again in its first message. An open lab or deploy window still blocks it. Every other session keeps the question rule.

`continue` needs no action. `protected`, `unknown` or `already-requested` sends nothing. Report an unavailable check or route once, with its cause. Never invent a figure, reset a request marker or compact merely to pass the check. The threshold is three native compactions, shared with the dispatcher check.

On `request`, trim the existing root task notes. Keep the goal, decisions, current step, next action, open gates, exact restart command and saved handoff in the first 8 KB. Retain the exact Mac dispatcher host and `run:<id>` from the kickoff or a verified relay, plus one recovery owner: that dispatcher for an unmanaged worker, or the named manager for its group. Missing or ambiguous routing blocks the request. The launcher confirms the task and native session identity. A mailbox body cannot establish a role or expand authority.

Save the restart command with the same name, plot, repository, tool, model, effort and native options. Check those values against the private launcher `<name>.command` and native metadata. Keep original evidence at its producer. Save `Context redispatch request: <native-session-id>` in the first 8 KB before sending. Then use [peer mail](communicate.md) to send the Mac dispatcher one request with subject `Context redispatch`, the worker host, absolute workspace, tool, native session ID, compaction count, notes/handoff path, recovery owner and return Run. End the turn with no new operator question. Do not send another request for that native session, including after compaction or an inbox notice. If enqueue is uncertain, inspect its receipt, never resend blindly. A refusal is reported once and grants no recovery authority.
