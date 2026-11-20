---
name: test-guide
description: "Write runnable test scenarios for an observable change, including scripts and rendered instructions. Produce commands with expected results or product interactions for the operator or the step 6 diff check."
---

# Test guide

Write a runnable guide for the changed behavior, using commands with expected output or exact product interactions. The reader is the step 6 diff check by the other tool, or the operator.

Only a change with no observable behavior, such as a prose typo, comment or rename with identical renders, receives a one-sentence N/A explaining why. A script, launcher or executed instruction has observable behavior. Missing tools, access or a running environment means blocked testing, not N/A. A change the diff check covers needs at least one scenario, because the check refuses a guide without one.

Read the task notes, its acceptance criteria and `## Validation`, the changed files and the project's `How the independent check reaches the change` instructions.

## What the check gets

For a multi-repository session the primary is the check's root, and companions retain `.slopmeister-repos/<name>` beneath it. Name each repository in the guide and include a consumer that needs their combined changes. Use these relative paths, never the worker's live checkouts. The primary's slot serves the session's combined path.

The check starts in a fresh copy of the subject, at the snapshot commit or frozen candidate for a repository. It has no `.venv`, installed project packages, notes file, local state or worker scratch files. It runs the repository's documented setup. A guide that starts a local service must state its port allocation requirement. Use the diff check's `--slot-target <plot>` to borrow the worker's existing allocation exclusively. The owner delivers the same `.slot.env` to the clean checkout after validating ownership. The declared setup route stops owned applications and resets disposable data before admission and on return, then returns a stopped slot after failure or running worker applications after a passing check. These resets discard the slot's data. The worker cannot use the slot during the check. The guide starts its application from the clean checkout and never allocates another slot, stack or simulator. Cleanup preserves the worker stack. Without the option the copy has no allocation. Never copy an allocation manually or bypass setup with a fake CI flag. It can run shell commands and read files. It has no skills, cannot start agents and cannot reach a phone or a screen. Write every step for that copy, with paths relative to its root, and create any other state a scenario needs inside the guide.

A check only the operator can run, such as a phone, a screen, a live login or an approval prompt, is not a scenario. List it under `## Operator checks` for the handoff.

## Write

1. Give a short user-result summary and prerequisites, starting from the clean copy's root with exact setup, boot or render commands, each with its own success check. Own required dependencies in the scenario or declare its real host requirement. A worker's installed tools or scratch files are not setup for the check.
2. Give each scenario a unique heading, `### Scenario <id>: <title>`, with an ID of lowercase letters, digits, underscores or hyphens. Cover the happy path, important edge cases and only falsification cases from `## Validation` that run without changing the checkout. Keep subject mutations in the worker's break-it pass. Create disposable fixtures outside the checkout when they would invalidate a checkout assertion. Give ordered actions, expected results and concrete signs of product failure. A setup, environment or guide fault is not a product failure, the check reports it as could not run. Commands must be copyable as written.
3. Derive every expected result from the actual file, saved tool output or behavior contract. Never require exact model text, token counts, timings or total test counts. Apply [behavior proof](../local-qa/SKILL.md#3-the-break-it-pass) and its subject-signal rule. When success means no output, verify command success and subject activity before printing a nonempty marker. Include a positive control when setup or capture could hide execution. An unconditional `echo ok` proves nothing.
4. Record exact test-created paths and their bytes before the test and clean up only those. Before removing one, confirm its bytes still match what the test wrote, and preserve changed or unrecorded files.
5. Save `<TASK-ID>-TEST-GUIDE.md` in the Git-ignored scratch directory in the task worktree, unless the task includes a committed guide, and record its absolute path in the notes. If no scratch directory is ignored, add its exact path to Git `info/exclude`. A Git-free session uses an owned scratch directory in its session directory. The harness session scratchpad is not acceptable for anything a later step or session reads. Preserve scenario IDs when revising it.

The diff check runs the guide as `execute-plan` directs. Keep its exact scenario statuses and guide findings. Use the [task summary](../execute-plan/task-summary.md) for the handoff. A guide remains owed even when testing cannot yet run. Testing acceptance and the harvest order require the operator's order or a valid Night mode grant under its completion limits.

Never rebase or rewrite the branch to produce the guide unless `How the independent check reaches the change` requires it, and then follow its consent and conflict rules exactly.
