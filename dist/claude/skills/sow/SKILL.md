---
description: "Sow: read the ticket and the code, set the scope, draft the plan and send the operator one message. Spine steps 1 and 2, before any source change."
effort: high
---

# Sow

Steps 1 and 2 of the spine. For a follow-up, check the reuse rule in `execute-plan` before asking for another plan answer. Writes only to `<TASK-ID>-NOTES.md` and creates the branch if none exists, except Bloom artifacts under the operator's explicit or standing request. No source changes.

## Read

1. The ticket with its linked issues and pull requests, from the project's tracker or the operator's prose. The live ticket is read-only. Before starting new implementation, search all branches and their history, pull request titles and bodies in every state, and worktree lists and contents for this ticket. A branch-name check is not enough. Prior or competing work stops new implementation until ownership and continuation are resolved through the existing decision route. The current already-ordered workspace alone is not competing work. Keep an existing operator decision to resume it.
2. The code the change lands on, what calls it and its history. Search semantic consumers as well as imports, including bare directory names in copy lists, fixtures and commands. For a shared replacement, name the existing capabilities and consumers it must preserve, and include their affected files in scope before approval. For a bug, find where actual diverges from expected. Also reproduce the reported failure with a read-only command against the real state it failed on, not only a scratch copy, and plan that same command as an acceptance check of the fix. If that needs a live-environment probe or another action reserved for operator intent, do not run it, request it in the one message and write `not reproduced live` in the plan. For a feature or operational task, trace the existing path to the requested result before proposing a new integration, credential or service. Find the extension point and the pattern next to it. When the change touches CI, build, packaging, release or test-harness behavior, check the files and actions that wire it in, including CI workflows, ignore files, shared fixtures, release scripts and slot-service actions. List affected files in `## Scope` up front and needed slot-service actions in `## Plan`, or name each as out of scope with the reason. Do not audit the repository, anything outside the change gets one line.
3. The context documents this plot names for the area, and any binding design artifacts for a surface you change. If none covers the surface, say the work is a gap-fill.

When the plot requires `groom`, use its read-only discovery to name affected repository documents and vault notes. Include their paths in `## Scope`. Under `## Plan`, list each document with one action, update, cut, merge or move. If none is affected, write `none` with a one-line reason.

## Design

For every spine, including a single repository, trace the user result from its entry point through each layer and repository to the visible outcome. Mark what already works and what is missing. Make step 1 a tracer bullet that carries the smallest deliverable through its real path, with its own acceptance command and visible expected result. Run the deliverable itself. A working test harness is setup, not the tracer. When the user result exists only in continuous integration (CI), the pull request CI run is the tracer. Name the authority and access that run needs. Do not substitute a local harness or dry run. Later steps widen the working path. Do not invent layers or plan speculative edge cases before that first feedback.

Separate the ticket's required outcome from any mechanism it names, its proposed fixes are suggestions. A fork is real only when its options lead to different behaviour, visible output or scope and the ticket does not decide it. A background process, a new module, a new trust boundary or secret custody, a schema change or a material size increase the ticket did not ask for is always a fork. State every behaviour choice the ticket leaves open as a fork with its options, never as a remark inside another part. Security work is threat-mapped, name the concrete threat, the reachable path and the smallest sufficient change.

Choose proof depth from what the change touches and state it in the opening. Every change the step 6 diff check covers is also tested by it against the test guide, so the opening names no tester choice. Use existing tests for a covered code path, one real session per tool for instruction text when needed, a deploy window for a live system, and the must-fix gates for security. The operator can correct the proof with the plan answer. Extra probe or rerun rounds beyond that proof need the operator's order. Keep mandatory security, authority and recovery gates.

## Write the notes

```markdown
# <Task Title>

**Goal:** <one sentence> **Branch:** `<name>`

## Scope
<each repository and the file globs the implementation may touch there>

## Plan
<the end-to-end user path with existing and missing parts, step 1's runnable tracer bullet and acceptance command, later steps that widen it, affected files, regression tests, document actions and concrete risks>
```

`## Scope` and `## Plan` are frozen headings. Tests under a listed area are in scope. Every code claim carries a file and line. A project gate that needs registration, a lint budget, a baseline file, an allowlist, gets its own step.

Select permanent tests by the shared [test-purpose rule](../implement/SKILL.md#test-purpose). Name the caller or input, observable consequence and existing coverage gap in the plan. No extra form or table is required. Name each paid live check, its exact command and cost in sessions, plus access or operator-only install prerequisites before work starts.

Read the session's repository list through `repository status` in the invoking Slopmeister. Name every touched repository in `## Scope`. A missing repository follows the same operator question as a file outside scope. After the operator agrees, use the plot-session add command and read the member's agreement before editing. Keep the session's plot and approval rules. A different plot or policy is a scope halt, not a reason to design a permission system for ordinary work.

## Send the one message

Run `prune` on your draft plan. Follow [task summary](../execute-plan/task-summary.md), check the exact opening reply and send that checked text unchanged. In Details, give the first acceptance command, its expected result and the notes path.

When three or more operator decisions are open, use one [Bloom decision page](../bloom/SKILL.md#decision-pages) by standing request. Link it in Details with one line per decision. This is still the one plan question, and source edits still wait for the answer. One or two decisions stay in chat with a recommendation and pros and cons per option.

Under a valid grant of [Night mode](../plot-session/SKILL.md#night-mode), you or your own wave's manager may decide the routine plan answer. Record the choice, its actual decision maker and the exact grant in task notes, then continue to plan review. Do not label it as the operator's answer. Otherwise stop until the operator answers. This is the spine's one plan question.

## After the answer

Fold the operator's feedback into `## Plan` in place, without a second question. Run `cross-tool-review` in plan mode for every new plan, then continue with `execute-plan`. For a follow-up, first check the reuse rule in `execute-plan`.
