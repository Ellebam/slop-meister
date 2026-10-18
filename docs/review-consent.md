# Consent for Slopmeister and vault reviews

The operator decides which review inputs may be sent to which providers. The policy below is an example for recording that decision. It grants no consent until the operator adopts it. For an authorized review, carry the actual inputs, destination and existing consent into its execution justification.

[Overview](../README.md) · [Review procedure](../src/skills/cross-tool-review/SKILL.md)

## Configure the deciding layer

Codex's automatic approval reviewer can stop a command before Slopmeister's review launcher runs. A launch allow rule and instructions in the review skill do not establish what that reviewer received. Codex supports local instructions through top-level `[auto_review].policy`; managed `guardian_policy_config` takes precedence. This setting changes approval guidance, not the execution sandbox. See [Codex approval configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#approval-policies-and-sandbox-modes).

For the operator's policy to take effect, the effective `approvals_reviewer` must be `auto_review`. The operator sets this in `~/.codex/config.toml`. A launch override can select `user` instead, so check the caller's effective setting.

The example policy records approval for requested Slopmeister and vault reviews through OpenAI Codex and Anthropic Claude Code. It preserves every other approval requirement and reviewer safeguard. It grants no permission for autonomous testers, implementation, unrelated sends or additional destinations.

This is a Codex approval setting. Claude's existing launch permissions remain in its [settings template](../plots/home/claude/settings.json.tmpl). A Codex rejection does not establish the same defect in Claude's approval system.

## Apply the policy once

`task home:install` manages only the template's top-level `model_context_window` in `~/.codex/config.toml`. It preserves every other setting. The reviewer and policy remain operator-owned and follow the manual procedure below. `task home:diff` reports the context key and declared approval rules by status only, main-checkout `task check` fails when the context key drifts, and neither prints a live configuration or rule file.

After the operator approves this exact scope, the operator-owned settings are:

```toml
approvals_reviewer = "auto_review"

[auto_review]
policy = """
The operator has approved sending required Slopmeister and vault review inputs, including private project documentation, to OpenAI Codex and Anthropic Claude Code. For operator-requested reviews, do not ask for that consent again.

This consent covers only those reviews and destinations. Keep the no-change instruction, secret filtering, output redaction, mutation checks, verdict persistence and all other approval requirements.
"""
```

1. Back up the existing user configuration privately and prepare a candidate with the reviewer and policy values above. Change only those keys as needed. Reconcile an existing policy before replacing it.
2. Inspect that exact change. Check that the live file still matches the saved preimage immediately before applying it.
3. Confirm that only `approvals_reviewer` and `auto_review.policy` changed in the parsed configuration. Keep the backup private because the complete configuration can contain sensitive values.
4. Compare the resulting reviewer and policy with the exact TOML example above, including both policy paragraphs.

Check the actual caller runtime's effective configuration before testing a review. The app-server exposes `config/read` with `cwd` and `includeLayers`, and `configRequirements/read`. Record the effective `approvals_reviewer`, whether `auto_review.policy` matches the example, and their provenance, never a complete configuration dump. A missing policy, stale runtime or unknown managed override leaves this check unresolved. Do not restart shared sessions to refresh it without coordinated authorization. Successful readback alone does not prove the approval reviewer used the policy.

## Give the reviewer its inputs

Set `--cwd` to the worktree being reviewed. A disposable calling session can review the worker's existing worktree directly, including its untracked plan. The reviewer needs no separate worktree or plan copy.

For required documents outside that worktree, `review --read-dir /absolute/directory` names additional read directories. Repeat it for each required directory. Paths must identify existing directories, with no relative paths, control characters or filesystem-root grants. The runner resolves them before execution. Quote paths containing spaces. A directory includes its descendants, so nested documents need no separate grant.

Claude receives these directories through native `--add-dir` while retaining `--restricted`, auto mode and only `Bash,Read,Grep,Glob`. Additional directories use the same permission rules as the original directory. See [Claude working directories](https://code.claude.com/docs/en/permissions#working-directories).

Codex runs without its sandbox, as the tester does, and receives no `--add-dir`. Both directions may run commands and tests, are told never to change the reviewed files, and gain no edit tools. The runner compares the tree of every file Git sees before and after the review and refuses a verdict when it differs. Ignored files are not compared.

If a review fails, the runner prints the blocked gate and writes no final result. Invalid reviewer JSON also produces redacted diagnostic output on stderr, capped at 16,384 characters. Nested JSON credentials and terminal control characters are removed before display. A decoding-limit failure omits the output. These diagnostics are not a review result and do not change the review gate. Inspect uncertain process and mutation state and stop; never reinvoke while the original call may still be live.

## Prove the result

Policy consumption and prompt-free completion are established only when a fresh caller runs the authorized review under normal automatic approval and retains all of the following:

| Evidence | What it establishes |
|---|---|
| Native caller identity, actual runtime and effective configuration | The tested session received the intended configuration. |
| Actual command, required input paths and execution decision | The responsible approval layer evaluated the intended review. |
| Caller transcript and approval messages | No repeated data-sharing consent was requested. |
| Completed persisted verdict and replay from the same ordinary command | The reviewer finished and its final result survived the launching tool call. |
| A nested synthetic marker read from a granted directory | The reviewer could read descendants, with the expected marker absent from its prompt. |

A launched tab, passing unit tests, a parsed policy or an accepted retry with a stronger justification cannot establish all of these. Review findings still require their normal verification.

## Handle a rejection

Preserve the exact decision privately and report which action was rejected and why. Continue authorized unaffected work. Do not disguise the command, switch launch paths to get past the rejection, loosen the sandbox or count the review as complete. A new approval requirement remains separate from the consent already granted.

If the supported configuration cannot produce the required behavior, keep acceptance unproven and prepare a sanitized upstream reproducer with the actual runtime versions, effective policy and managed-policy visibility, command shape, expected behavior, observed rejection and evidence references. Keep private document contents, field facts and exact sensitive paths out of that report. Distinguish an ignored setting, a managed override and unavailable evidence. A single failed run does not establish that no supported setting exists.

## Replacement boundary

The generated per-session Claude and Codex rules allow only the ordinary `review review` command. Claude runs without a Bash sandbox, so the command reaches the reviewer and protected result store directly and still passes through the narrow allow rule. Claude carries a separate ask rule for `review replace`, and Codex has no standing allow for it. When the operator explicitly requests a fresh task-and-mode result, the agent runs that separate command through native approval; it removes one exact result and launches nothing. Direct state writes remain outside routine workspace permissions.

Live proof must exercise ordinary prompt-free review, replay, unauthorized replacement refusal and operator-authorized exact replacement in fresh Claude and Codex sessions. Approval-policy consumption and the replacement boundary may be claimed only for the tools and implementations whose probe evidence is retained.
