# Native worker startup

[Launcher contract](launcher.md) · [Native write actions](service-actions-native.md)

## How each tool starts

| Tool | Start | Delivery proof |
|---|---|---|
| Claude Code, the default | `--remote-control=<name>` so the phone can reach it, `-n <name>` for the prompt box and `/resume` picker, a pinned `--session-id`, `--strict-mcp-config` with the selected native writers, the plot through `--append-system-prompt-file`, `--setting-sources user,project` to skip local settings, and protected settings through `--settings`. | The kickoff as a user message in the transcript under the selected Claude store's `projects/`, `~/.claude/projects/` unless `CLAUDE_CONFIG_DIR` is set. |
| Codex, `--tool codex` | A standalone `--no-daemon` process with the launcher's pinned `CODEX_HOME`, at the prepared root with `project_root_markers=["AGENTS.md"]` and no fallback instruction files. Codex has no name flag, so the session name is the kickoff's first line. | The kickoff in the rollout under `$CODEX_HOME/sessions/`. The report prints a matching resume command. |
| OpenCode, `--tool opencode` | The kickoff as `--prompt`, Claude-compatibility files off, permission rules passed inline. No extra tool arguments, no trust store, no `--redispatch` or `--abandon`. | `opencode export` of the one session carrying the kickoff. See [OpenCode](opencode.md). |

Claude also excludes memory discovery under the workspace and granted roots through `claudeMdExcludes`. Codex has no strict MCP switch, so turn off unused user-scope servers in `~/.codex/config.toml` with `enabled = false`, and on the Claude side remove them with `claude mcp remove <name> -s user`. The launcher refuses native tail arguments that would override these controls, the working directory, session identity, tool selection, hosting or configuration sources. Repository paths must name the actual root. A symlink to that root is accepted, but a nested directory is refused before allocation. The [startup measurement method](startup-context.md) shows how to count what a session actually loads.

Every Claude session runs in auto permission mode without the Bash sandbox, see [the permission contract](launcher.md#the-permission-contract). The dispatcher keeps its full MCP surface. Its delivered `autoMode.allow` exception permits only a `task plot-session`, `task slot:up` or `task dispatch` launch you requested in the conversation.

## Native write startup

Immediately before opening the worker terminal, the launcher starts enabled required writers through the selected client's native protocol. This makes no model request and invokes no service action. Optional servers alone do not trigger it. Explicit disable-only settings remain effective, and OpenCode keeps its existing route.

Codex receives each complete delivered server definition before the accepted configuration tail. The preflight uses the same definitions, approval settings and selected client home. Its ephemeral thread request supplies no trust-mutating cwd. Claude uses the delivered settings and strict server file. Preflight strips Orca identity variables so it cannot appear as the worker.

Protocol reads have a shared sixty-second deadline and bounded frames. Cleanup retains the unreaped process-group leader until its children are stopped. A failed startup opens no worker. If cleanup cannot be verified, the launcher retains the workspace and slot resources. Diagnose the named client/tool failure before retrying the saved session with `--redispatch`.

Fresh deliveries pin the complete server definitions. Existing fixed deliveries retain their compatible approval-key format; redispatch does not rewrite them. Preflight runs before closing the predecessor. Resume commands preserve accepted configuration overrides after the selected pins.
