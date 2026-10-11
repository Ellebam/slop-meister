# Measure session startup

Measure the current tool and configuration together. Separate Slopmeister instructions from the harness's own startup cost, and retain the tool version with each result.

[Overview](../README.md) · [All documentation](README.md) · [Task briefs](contracts.md)

## The method

Read the first `assistant` record in `~/.claude/projects/<slug>/<session-id>.jsonl`. The slug is the working directory with slashes replaced by dashes.

```text
bin/slopmeister startup-context ~/.claude/projects/<slug>/<session-id>.jsonl
```

| Evidence | What to count |
|---|---|
| `message.usage` | Sum `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens` for the actual startup total. |
| Earlier `attachment` records | Skill and agent listings, plus deferred tool names and their byte counts. |
| Later `deferred_tools_delta` records | MCP names added after tool calls. Schemas load separately when requested. |
| `/context` in the tool | Category estimates and named memory files or skills. Use them for attribution, not as a substitute for the interactive transcript. |

The command prints the first turn, kickoff bytes, attachments and later MCP deltas, then the servers and tool-name count. Print mode omits interactive-only tools and skills. A fresh session's cache read includes the system prompt and built-in tool definitions shared by sessions on that binary.

## Compare configurations

Use fresh sessions with the same tool version, task and execution path. Record the launch flags and effective configuration. Change one input at a time. Keep full transcripts private and report only the relevant counts and configuration differences.

Measure source and rendered instruction size separately:

```bash
wc -c plots/code/plot.md dist/codex/plots/slopmeister.md
```

Bytes are not tokens. A smaller instruction file also does not prove that a session loaded less context. Use the native first-turn usage for that claim.

## Keep one owner per instruction

The [kickoff contract](contracts.md) keeps shared rules in their owning layer. Run `task kickoff:check -- <kickoff-file>` to detect known repetitions, then inspect the brief for paraphrases the checker cannot catch. Keep only the task's result, scope, decisions and session-specific constraints in its kickoff.

The [launcher](launcher.md#how-each-tool-starts) owns current tool flags, settings sources, memory exclusions and file grants. The [rendered agreement](../dist/codex/plots/slopmeister.md) and delivered skills own the workflow. Measure those actual inputs before proposing another startup optimization.
