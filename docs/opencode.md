# OpenCode

OpenCode is an optional third tool. Claude Code and Codex remain the main tools. OpenCode serves two uses, an interactive worker started by the launcher and an autonomous tester an agent starts for local QA. Workstation preflight does not require it, a machine without OpenCode stays healthy.

## Setup

Slopmeister never installs OpenCode, never owns its configuration and never reads a provider key. The provider configuration in `~/.config/opencode/opencode.json` (or `$OPENCODE_CONFIG`) stays the operator's. Slopmeister reads only the variable names that configuration references as `{env:NAME}`.

Export each referenced variable in `~/.zshenv`, not only in `~/.zshrc`. Agents, the tester supervisor and the launcher's tab run non-interactive or login shells that never read `~/.zshrc`. Keep `~/.zshenv` at mode 600 when it holds a key. A missing variable stops the launch or the tester before anything starts, with `provider variable <NAME> unset`.

## What a session receives

OpenCode reads the Codex delivery every launched workspace already has, `AGENTS.md` and `.agents/skills`. Both commands set `OPENCODE_DISABLE_CLAUDE_CODE=1`, so the Claude copy and the operator's personal Claude skills stay out, and pass the Slopmeister permission rules through `OPENCODE_CONFIG_CONTENT`. The rules are rendered from `src/permissions.toml` and `src/native-permissions.toml` into `dist/opencode/permission.json`, where a `needs_intent` decision becomes `ask`, which a headless run refuses. The worker may use its granted directories, the vault and for Slopmeister its checkout, without asking. The tester also denies the edit tools and allows outside-directory access only to its own run directory, which holds the guide, notes and evidence. Neither ever uses `--auto`. The tester's shell commands inherit the provider variable, as any shell of the operator's user can already read it from `~/.zshenv`, so a tester has the same credential reach as the Claude and Codex testers have to their own. The worker keeps the operator's OpenCode plugins, the tester does not disable them either because it already runs the subject's own commands.

The skills are the Codex rendering, so a procedure that names a tool speaks of Codex. The supported spine path for an OpenCode worker is sow, implement, local QA and independent testing. Cross-tool review still supports only Claude and Codex worker directions, so the automatic path stops before that review boundary.

## Worker

```text
task plot-session -- [<repo>] <plot> <name> [--directory] --tool opencode [--model <provider/model>] < kickoff.md
```

The tab runs `opencode <workspace> --prompt "$(cat <kickoff file>)"`. Without `--model` OpenCode uses its configured default. Extra tool arguments after `--` are refused, because `--auto`, `--session` or `--prompt` would replace Slopmeister-owned configuration.

A repository plot must declare both commit and shipping permission as `allow`. Otherwise the launcher refuses before preparation and names the denied permission. This also applies when that plot is launched with `--directory`. Use Claude or Codex for a denied plot. An admitted OpenCode worker still lacks native approval for direct `git push`, unlike Claude and Codex. Admission does not establish full Git permission parity.

Delivery is proven from OpenCode's own store. The launcher finds the one session whose directory is exactly the workspace, created after the launch and whose first prompt is exactly the kickoff, through `opencode session list --format json` and `opencode export <id>`. It writes a reduced receipt, never the conversation, to `<state>/<name>.opencode.jsonl`, and the claim check reads that receipt. The report prints `resume: cd <workspace> && opencode -s <id>`.

The occupant census counts an `opencode` process whose working directory is inside the workspace. `opencode serve`, `web` and `acp` servers and OpenCode sessions in other directories are not occupants.

## Tester

```text
bin/slopmeister tester launch --worker-tool <claude|codex> --tester-tool opencode [--tester-model <provider/model>] --task <task> --cwd <checkout> --commit <commit> --guide <guide> --validation <notes> [--slot-target <plot>]
bin/slopmeister tester collect --run <run path> --wait-seconds 30
```

Without `--tester-tool` the tester stays the opposite of the worker tool. The worker and tester tools must differ, and a named tester never falls back to another tool. The binary and provider variables are checked before the tester starts. Every invocation creates a fresh isolated run directory.

The run executes `opencode run --format json --dir <checkout> --print-logs --log-level INFO` with the prompt on stdin, which OpenCode stores verbatim. The run directory keeps `events.jsonl`, `stderr.log` with OpenCode's own log, `native.json` with the checked session fields, and `result.json` with `blocked_reason` when blocked. Exact provider values are scrubbed from every run file outside the checkout after the process exits, the subject itself is never rewritten. The session is deleted from the store once the receipt is saved, `session_deleted` records whether that worked.

The saved validated draft is the sole verdict source after native completion and identity are proven; a draft cannot repair a missing completion event or change a failed scenario into a pass. Optional tester slots have separate ports and Compose projects, and cleanup completes before result publication. The guide still owns repository setup.

A blocked report names one reason, its cause, the fix and the exact evidence path and line.

| Reason | Meaning |
|---|---|
| `opencode not found` | No executable on PATH, nothing started |
| `provider variable <NAME> unset` | The configuration references a variable this environment lacks, nothing started |
| `provider error` | The event stream carries an `error` event, such as an authentication failure or a blocked request. The subject was not tested |
| `permission refused` | OpenCode asked a permission question a headless run cannot answer, such as access outside the checkout and run directory |
| `interrupted` | The run ended without a final step whose reason is `stop` |
| `no native evidence` | No session, a session in another directory, a different first prompt, or a model other than the requested one |

A missing, malformed or invalid saved draft produces a blocked report with its validation error. `fail` is reserved for scenarios the tester graded as failing.

## Not supported yet

`--redispatch` and `--abandon` for OpenCode workers, and OpenCode as the cross-tool reviewer. The launcher and review command refuse these with a message naming this document.

## Recovery and rollback

A launch that stops after the tab opened leaves the worker running. Inspect it with `cd <workspace> && opencode session list` and close the tab yourself, never relaunch over it. Collect and report a blocked tester run by its exact path. A later intentional test is a separate invocation. A run that timed out or lost its process group may leave its session in the store, remove it with `opencode session delete <id>` using the session id in `events.jsonl`.

Rollback is removing `--tool opencode` from use, no Claude or Codex path depends on OpenCode. Worker sessions stay in OpenCode's store, delete one with `opencode session delete <id>`.
