# OpenCode

OpenCode is an optional third tool. Claude Code and Codex remain the main tools. OpenCode can run as an interactive worker started by the launcher. Workstation preflight does not require it, a machine without OpenCode stays healthy.

## Setup

Slopmeister never installs OpenCode, never owns its configuration and never reads a provider key. The provider configuration in `~/.config/opencode/opencode.json` (or `$OPENCODE_CONFIG`) stays the operator's. Slopmeister reads only the variable names that configuration references as `{env:NAME}`.

Export each referenced variable in `~/.zshenv`, not only in `~/.zshrc`. Agents and the launcher's tab run non-interactive or login shells that never read `~/.zshrc`. Keep `~/.zshenv` at mode 600 when it holds a key. A missing variable stops the launch before anything starts, with `provider variable <NAME> unset`.

## What a session receives

OpenCode reads the Codex delivery, `AGENTS.md` and `.agents/skills`. The launcher sets `OPENCODE_DISABLE_CLAUDE_CODE=1` and passes the rendered permission map through `OPENCODE_CONFIG_CONTENT`. The map comes from `src/permissions.toml`, `src/github-permissions.toml` and `src/native-permissions.toml`. The worker may use its granted directories without asking and keeps the operator's OpenCode plugins. It never uses `--auto`.

The shared spine requires an independent plan review and diff check. Those routes support Claude and Codex directions only. An OpenCode worker cannot complete that automatic spine path. The former separate OpenCode tester is removed.


## Worker

```text
task plot-session -- [<repo>] <plot> <name> [--directory] --tool opencode [--model <provider/model>] < kickoff.md
```

The tab runs `opencode <workspace> --prompt "$(cat <kickoff file>)"`. Without `--model` OpenCode uses its configured default. Extra tool arguments after `--` are refused, because `--auto`, `--session` or `--prompt` would replace Slopmeister-owned configuration.

A repository plot must declare both commit and shipping permission as `allow`. Otherwise the launcher refuses before preparation and names the denied permission. This also applies when that plot is launched with `--directory`. Use Claude or Codex for a denied plot. An admitted OpenCode worker still lacks native approval for direct `git push`, unlike Claude and Codex. Admission does not establish full Git permission parity.

Delivery is proven from OpenCode's own store. The launcher finds the one session whose directory is exactly the workspace, created after the launch and whose first prompt is the kickoff with only the fixed inbox-failure notice permitted, through `opencode session list --format json` and `opencode export <id>`. It writes a reduced receipt, never the conversation, to `<state>/<name>.opencode.jsonl`, and the claim check reads that receipt. The report prints `resume: cd <workspace> && opencode -s <id>`.

The occupant census counts an `opencode` process whose working directory is inside the workspace. `opencode serve`, `web` and `acp` servers and OpenCode sessions in other directories are not occupants.

## Not supported yet

`--redispatch` and `--abandon` for OpenCode workers, and OpenCode as the cross-tool reviewer. The launcher and review command refuse these with a message naming this document.

## Recovery and rollback

A launch that stops after the tab opened leaves the worker running. Inspect it with `cd <workspace> && opencode session list` and close the tab yourself. Never relaunch over it. Retained evidence from the retired tester stays where it was saved and is not automatically deleted.


Rollback is removing `--tool opencode` from use, no Claude or Codex path depends on OpenCode. Worker sessions stay in OpenCode's store, delete one with `opencode session delete <id>`.
