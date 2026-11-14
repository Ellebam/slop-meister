# Claude accounts

[Orca](orca.md) · [Launcher](launcher.md) · [Phone access](phone-access.md)

Orca's account switcher chooses the Claude account of every new session. `task plot-session`, `task dispatch` and the dispatcher Quick Commands read the selection at each start, so a launch or a `--redispatch` after a switch runs on the selected account. A running session keeps its account. **System default** is this machine's own Claude login. A `CLAUDE_CONFIG_DIR` that the operator set still wins. A launch outside an Orca terminal behaves as before, except a [remote launch](remote-dispatch.md), which follows the remote host's selection. A selection that names no existing folder stops the launch with a message. Select the account or System default again in Orca, then start again.

Slopmeister reads only the path of the selected account folder. It reads, copies and moves no credential. Do not use a `claude setup-token` token, because it cannot serve Remote Control.

Account commands run on the machine that owns the account, with `/Applications/Orca.app/Contents/Resources/bin/orca` on the Mac or `/usr/bin/orca-ide` on Linux. [Update Orca](remote-dispatch.md#update-orca-without-stopping-workers) first on a machine whose `account select --help` names no `claude` agent, because that version cannot select a Claude account.

1. Add an account once per machine. In an Orca terminal on that machine, opened at the desk or in Orca Mobile, run `account add`. It prints a sign-in link. Open the link in a private browser window on the phone, sign in to the second account and paste the code back. The command needs no desktop session. Orca's Settings, Accounts page does the same at the desk.
2. Switch with the account switcher in Orca's status bar, the Accounts screen in Orca Mobile, or `account select --agent claude --account <email>`. Use `system` for System default. `account list --agent claude` marks the active account. A switch applies to every later Claude launch on that machine, including other tasks.
3. Move running work in this order. Restart the dispatcher first, then run `--redispatch` for each worker that must move. Each worker continues from its notes. `/status` in a session shows its account. A worker that is not redispatched stays on its account.
4. Sign an expired account in again from the phone. Select that account, then run the **Claude sign-in** Quick Command in Orca Mobile. It types `claude auth login --claudeai` into a new Orca terminal, which shows the link and waits for the code. On Linux, add a Quick Command with that command by hand. Redispatch the sessions that stopped for the missing login.
5. After `task home:install`, select the account again in Orca. Orca then copies the changed settings into the account folder. Instructions, skills and hooks need no step, because the account folder links them from `~/.claude`.

The standing [remote-control job](phone-access.md) always uses the system login. The Claude app shows only the sessions of the account it is signed in to, so sign the app in to the account whose sessions you need.
