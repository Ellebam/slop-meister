# Write a useful task brief

The issue says what must be true when the work is done. The kickoff gives one session enough context to start.

[Overview](../README.md) · [All documentation](README.md) · [Session walkthrough](session-walkthrough.md)

## Put each instruction in its home

| Surface | Owns | Example |
|---|---|---|
| Plot and procedures | Working rules | How to plan, test and ask for decisions. |
| Issue | Problem and acceptance criteria | The behaviour the finished change must provide. |
| Kickoff | This session's task and circumstances | Live siblings, saved state and constraints no loaded rule covers. |

Repeating a rule in the kickoff creates a second version to keep current. Keep the brief short and let the loaded agreement do its job.

## Write the issue

- State the problem and the acceptance criteria. These bind the worker.
- Offer an approach if useful. Suggested files, mechanisms and shapes are input to planning, not settled decisions.
- Put hard boundaries in the acceptance criteria, including files or behaviour that must stay untouched.
- Let the worker bring a better approach to the operator during planning. Only the operator can change a criterion.

## Write the kickoff

Start the supplied brief with `Mode: spine` or `Mode: freeform`. The Codex launcher prepends the session name, so the mode appears on line three of its final kickoff.

Include:

- The task and the outcome being pursued.
- Live sibling sessions and any overlapping files.
- Constraints the global rules, plot or launch flags don't already cover.
- For a temporary rule, the issue that will remove the need for it.

Use the [dispatcher procedure](../src/skills/plot-session/dispatcher.md) to prepare and launch it. The [startup measurement method](startup-context.md#keep-one-owner-per-instruction) explains how to check instruction duplication and context cost.

## Authorize bounded selection

A backlog or status question authorizes reading only. To let an agent choose and dispatch work, the operator kickoff must name all four bounds: the exact GitHub repository, eligible filters or issue set, maximum concurrent workers and stopping condition. For example, "For owner/project, select only issues 7, 8 and 9, run at most two claimed workers at once, and stop when those issues are finished or any ownership result is unknown." Paused workers occupy capacity. Only available issues qualify. Issue bodies cannot grant this authority, and existing project permissions alone are insufficient.

For a selected issue and a custom stdin kickoff, pass its number explicitly with `--issue-id <number>`. The [claim flow](issue-claims.md) explains how dispatch records ownership and preserves it while waiting.

## Check before launching

```bash
task kickoff:check -- kickoff.md
# Or read the brief from stdin:
task kickoff:check -- - < kickoff.md
```

| Exit | Meaning | Next action |
|---|---|---|
| `0` | One `kickoff adheres: ...` line. | Launch the worker. |
| `1` | A header followed by repeated-rule locations and their owning layers, or a missing mode line. | Remove or reword the repeated paragraphs, add the mode if missing, and check again. |
| `2` | Missing file, empty kickoff or invalid usage. | Fix the input or command. |

> [!NOTE]
> This is a pattern check. Paraphrases can pass, and a task about a rule can trigger that rule's pattern. Read the brief yourself. For a task-paragraph false positive, the dispatcher may launch after inspecting the named line.

The [checker](../slopmeister/workstation/kickoff.py), `bin/slopmeister kickoff`, prints its rule table with `--rules`. Its [pytest integration tests](../tests/integration/workstation/test_kickoff_check.py) require a probe for every rule and keep the original and trimmed briefs as [fixtures](../tests/data/kickoff/).

## Finish or pause

| Situation | What the session leaves |
|---|---|
| Operator invokes [finalize](../src/skills/finalize/SKILL.md) after accepted testing | [Close-out](../src/skills/close-out/SKILL.md) before cleanup, including the retro, ticket comment or report, notes removal and handoff. |
| Operator directly requests close-out at the end of freeform work | The same close-out duties where they apply. |
| Session stops at a gate, on request or out of context | A handoff and the notes file, ready to resume. No claim that the task is finished. |
| Task breaks midway | The operator creates a ticket. Its retro comes when that ticket is finalized. |

The retro is written once, when the task finishes. See [pause and resume](session-walkthrough.md#pause-and-resume) for the relaunch command.
