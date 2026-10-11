---
description: "Implement: execute the plan, write code and tests, run the gates. Spine step 4, after the plan check passes, builds a planned task, or runs once as a scoped fix pass on a step 6 findings list. Not planning and not proving it works."
---

# Implement

Step 4 of the spine. Read the plan, build it step by step, run the gates. Proving it actually works, the acceptance commands and the break-it pass, is step 5, and that is where the value is, do not declare victory here.

Both modes use the approved `## Plan` and the working agreement's approval and resume rule.

## Two modes

- Build, the default. Execute the plan's numbered steps, in order.
- Scoped fix pass, run once, only for the surviving findings of a step 6 diff review. That list bounds the edits, one action per item, each with a file, a line and a one-sentence change. Do not extend it, do not touch neighbouring code, do not redo the build. If an item is ambiguous, drop it with that reason. If a fix pass is already recorded there is no second one, stop and tell the operator.

## Test purpose

Admit a permanent test when it protects required behavior or a reachable harmful failure that existing coverage misses. Name the caller or input, observable consequence and coverage gap. Reuse or extend existing coverage first. A bug name or a mutation-sensitive wording pin alone does not justify a test. Keep exploratory controls temporary unless they expose uncovered regression risk.

Negative tests must establish that the intended stage was reached and assert its diagnostic or preserved state. A generic nonzero exit can hide a missing executable or broken setup. Keep distinct security, data-loss, authority and recovery obligations, render structure, delivery, parity and actual tool-specific behavior. Check a shared instruction's safety obligation once in source. Remove duplicate wording pins and retired-name checks with no consumer.

## Process

### 1. Read

1. The notes file, `## Scope`, `## Plan`, and any findings handed to you.
2. The context documents this plot names for the area.
3. Confirm you are on the expected feature branch and the working tree is what you expect. Unexpected uncommitted work means ask before proceeding.
4. Read every file you are about to change. For new files, read the pattern reference the plan names.

### 2. Build

Follow the plan's steps in order. For each of them.

- Deliver the approved user result with the smallest runnable path first. Add permanent machinery only when that result requires it. Before retiring shared machinery, drive each affected existing capability through its replacement, including its approval boundary.
- Test-first. Apply Test purpose above before writing the test `## Plan` named. Run it before the production change. Record red first only when its assertion observes the intended missing behavior. Diagnose and correct setup or import errors before counting them as proof. A prior pass can reflect existing coverage, check that gap before adding more tests. Do not manufacture a red receipt. Use the [behavior proof](../local-qa/SKILL.md#3-the-break-it-pass) for changed obligations without a valid failing reproducer.
- Match the local idiom, not its defects. Follow the surrounding code's conventions, naming, file layout, import style, so a new file reads as part of the codebase. Where that code violates this plot's standard, the standard wins for the lines you write, do not replicate bad structure to blend in.
- Minimal diff. Do exactly what the step says. Every changed line traces to `## Scope`. When you notice adjacent work worth doing, name it in one line and do not do it.
- If a named test is clearly deferrable, say which and why.

When the plot requires `groom`, invoke it for the planned document list before Verify. Include documents affected by an approved fix, keep edits within the accepted scope and finish them before proof and review.

Before Verify, simplify the result against the global lean-design standard. Delete superseded paths and dead code, inline unjustified one-use abstractions, remove redundant intermediate output and collapse pass-through scripts. If the same accepted behavior and required safety use fewer concepts or less code, simplify now. This completes Build, it is not another workflow phase.

### 3. Verify

Two parts, both before handoff.

Checks first. Run the checks your change affects and every targeted check the plan names, typically the tests of the changed code, the type checker and the linter. The complete suite and the local gates run once, in step 5, so do not run them here. Run independent checks in parallel, the targeted one first for fast feedback. When a check fails, read the error, diagnose the root cause, fix it if it is straightforward. If the fix would deviate materially from the plan, stop and report, the plan may be wrong. Never edit a passing test to make a failure go away.

Then run the smallest path against one of the plan's acceptance criteria and show the actual user result. Green gates alone do not show that result. Keep valid nominal evidence for step 5. Repeat execution only for a distinct claim, changed input or unresolved failure. The adversarial pass remains step 5. If the intended result fails, fix it now.

### 4. Record

Append under `## Implementation`, the files changed with one line each, the tests added and what they cover, the gate results, the acceptance criterion you exercised with its observed output, and anything deferred with its one-line trade-off.

Then report the branch, files changed and gate results, with step 5 next because green tests are not proof. In the automatic post-plan path, retain this evidence in the task notes and continue directly to `local-qa` and `ripe`.

In scoped fix-pass mode, prove the edited lines with every affected suite and acceptance claim. Use the full suite when impact cannot be bounded. Apply the [behavior proof](../local-qa/SKILL.md#3-the-break-it-pass) to each distinct changed behavior or trust boundary, restore controls exactly and run `ripe`. Continue as `execute-plan` directs to final shipping and the operator handoff at step 8 only when everything passes and is proven, otherwise halt and report to the operator. The guide and independent tester run before the diff review.

## Rules

- Don't be sloppy. Read the whole error, check the whole diff, run every check the change affects, and put real output behind every claim you record.
- The plan is the spec. If you disagree with it, raise it, do not silently diverge.
- Read before you write. No exceptions.
- Tests are part of the work. If the plan forgot a test the change obviously needs, write it and say so.
- Fail loudly. If a gate fails and the fix is not obvious, report it rather than making speculative changes.
- No gold plating. No extra error handling, logging, comments, or annotations beyond what the plan and the surrounding code do.
- Do not commit. That is the ship step.

## Arguments

$TASK_DESCRIPTION
