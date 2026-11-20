---
description: "Does it work? Run the acceptance commands, drive the change as its user, break your own work, and run the gates only this machine can run. Spine step 5, after implement and before the diff review, proves a change actually works. Not for writing code and not for reviewing a diff."
---

# Does it work?

Step 5 of the spine. Green tests are necessary and not sufficient. This step runs the assembled result, drives it the way its user does, and tries to break it.

Before you start, read `How a change is driven here` and `Local gates here` in this repository's working agreement. Where a section has nothing under its lead sentence, the generic rule below stands alone.

## Process

### 1. Run the acceptance commands

For a multi-repository session, compare the saved members with `## Scope` and run the user path across them together. Per-repository passing suites do not prove the connection between them. Reuse the actual first-step acceptance evidence when its inputs and code remain unchanged.

Run every acceptance command and every test `## Plan` names, and keep the actual output. Reuse valid current-revision evidence when the subject and inputs are unchanged. Another execution must add a distinct claim, changed input or resolution of a failure. Independent testing still executes its required scenarios itself. A planned test is cited by file and line, or reported missing. An acceptance command that is not runnable as written is a setup or guide finding, diagnose and write the command that works within scope.

A probe that always passes is not a probe. Require an observed subject signal before accepting an absence claim. Empty capture without subject activity is missing proof. When setup, capture or fallback could pass without exercising the subject, use a positive control that the check must detect. Require the intended stage and its relevant diagnostic or state for a negative case. A fallback status code needs an assertion on the actual result.

Do not claim portability from local success alone. Show minimal-environment execution or fixture ownership of every relevant external dependency. Keep real host requirements native and report the host and unproven platforms.

Run probe, backup and restore loops from a bash script file, never inline in the session shell.

### 2. Drive the change as its user

Unconditional. The interface is how the user reaches the change, not which directory the diff touched. Reach a screen through that screen, a script by running it, an endpoint by calling it and a configuration by loading it the way its consumer does. If a change has no user-reachable surface, say which and why. Follow `How a change is driven here`. If the thing you drive is built, bundled or rendered, confirm it contains your edit.

1. Seed the state that makes the change observable, the cohort the change is for, not the happy path that predates it.
2. Test a partial choice, accept one thing and decline another, not only all-on and all-off.
3. Continue past the expected outcome until the user is somewhere normal. An error they cannot act on or a retry that repeats the failure is the finding.

For a requested look or layout, or any change covered by a design reference, compare each changed section with the reference the approved plan follows. Keep one screenshot per changed section next to its matching reference crop. Cover every expanded, collapsed and empty state the change touches with a screenshot and matching crop. Check layout, component composition, hierarchy, sequence, copy, navigation, typography, clipping, surfaces, colors and controls. Name each remaining difference beside the comparison. The plot names where its design references live.

For a set of factual claims, compare every delivered claim with its authoritative source. Correct or remove claims the source contradicts or does not support. A sampled check does not prove the remaining claims. A missing reference or inaccessible source blocks proof of that result. Ask the operator for the reference or access before completion. A test pass, frame rate or successful render alone proves neither appearance nor factual accuracy.

Keep actual output, or a screenshot for a visual interface, in the Git-ignored scratch directory in the task worktree. If no scratch directory is ignored, add its exact path to Git `info/exclude`. A Git-free session uses an owned scratch directory in its session directory. The harness session scratchpad is not acceptable for anything a later step or session reads.

### 3. The break-it pass

Three arms.

1. Behavior proof. For each distinct changed behavior or trust boundary without a valid failing reproducer, use a meaningful subject mutation or control and confirm the relevant check fails. Equivalent parameter cases may share a control when it proves their common obligation. Distinct branches and interactions need distinct proof. A wording deletion alone proves no reachable failure. Apply [Test purpose](../implement/SKILL.md#test-purpose) before retaining a test. For Python source mutations, give every interpreter that imports the changed modules, including child processes, a fresh disposable cache for each mutation run and restored-source verification. Set `PYTHONPYCACHEPREFIX`, or `-X pycache_prefix=<fresh-directory>` when environment variables are ignored. Disabling bytecode writes alone still permits stale cache reads. Restore temporary changes from copies and compare checksums of every touched file, including untracked ones. Keep controls temporary unless they reveal uncovered regression risk.
2. Adversarial falsification. For every "verified clean" claim, construct one concrete counterexample, preferring the way real usage would break it. If one holds, fix it now.
3. Security Lens. One line over the diff per the working agreement's security section, a finding with file, line and severity, or a verified-clean declaration naming the checks that ran. A must-fix class is fixed now.

### 4. The local gates

Read the repository's CI configuration, including triggers, changed-path filters, job rules and includes. List the jobs the changed paths select and the commands they run. Run each job that can run locally, including checks absent from `Local gates here`. Reuse a local gate's evidence for the same commands and inputs. A job that the plot explicitly reserves for CI stays there. Under Weak, name every unrun job, its reason and any job whose selection you could not determine. A green local gate does not prove those jobs passed.

Run each gate `Local gates here` names once, by default after the break-it pass. Before that, run only the checks your change affects. Run a gate again only when it failed, or when a later fix has an impact you cannot bound. Every other fix runs the checks it affects. A local gate is a regression suite, never coverage of your change. A failure that also happens on a clean checkout of the merge base is recorded with a follow-up, never fixed on this branch. Tear down only what you started.

### 5. Prove and record

Before you report this step done, run `ripe` against the task and its acceptance. Say what works for its user and what remains. Missing proof is not done.

Write `## Validation` in the notes file, free-form, with the date and PASS or FAIL, the acceptance output, what you drove and saw, the three break-it arms with the `**Security Lens:**` line, and each local gate result. Then continue as `execute-plan` directs.

## Rules

- No remote mutation here. Shipping belongs to `execute-plan`.
- Source edits here fix only concrete findings from this step, a falsified claim, ineffective proof, uncovered required behavior or a security defect. Apply `prune` to unsupported extras. If a fix would change the plan's approach rather than its code, stop and tell the operator.
