# Skills

Every session gets the same shared skills, rendered from [src/skills/](../src/skills/). Claude Code invokes one as `/sow`, Codex as `$sow`.

[Overview](../README.md) · [All documentation](README.md) · [One session, start to finish](session-walkthrough.md)

"Agent" means the session invokes the skill on its own when its moment comes. "Agent, on your word" means it runs only when you ask for it. "Operator" means only you type it, both tools refuse to start it on their own.

| Skill | What it does | When | Who |
|---|---|---|---|
| [sow](../src/skills/sow/SKILL.md) | Reads the ticket and the code, sets the scope, drafts the plan and sends you one message. | Spine steps 1 and 2 | Agent |
| [cross-tool-review](../src/skills/cross-tool-review/SKILL.md) | Has the other tool review the plan or the diff once, then verifies, prunes and applies the findings. | Spine steps 3 and 6 | Agent |
| [execute-plan](../src/skills/execute-plan/SKILL.md) | Runs the plan through implement, proof, tester, ship, diff review and its fix pass. | After the plan review | Agent |
| [implement](../src/skills/implement/SKILL.md) | Builds the plan test-first, or applies the fixes you approved. | Spine steps 4 and 7 | Agent |
| [local-qa](../src/skills/local-qa/SKILL.md) | Runs the acceptance, drives the change as its user and tries to break it. | Spine step 5 | Agent |
| [ripe](../src/skills/ripe/SKILL.md) | Checks whether the work does what was meant and whether more is overdoing it. | Before any question, handoff or done | Agent |
| [groom](../src/skills/groom/SKILL.md) | Keeps affected repository docs and vault knowledge correct, short and in one place. | Before review when required, at direct harvest, or a scoped request | Agent or operator |
| [prune](../src/skills/prune/SKILL.md) | Reassesses findings, plans or drafts for validity and needless complexity. | After a review, or whenever asked | Agent or operator |
| [leak-check](../src/skills/leak-check/SKILL.md) | Checks that nothing about to reach a customer, commits, PR text, reviews, Jira, Confluence or message drafts, shows our workflow, agents or machine. | Before anything leaves for a project we do not fully own, or whenever asked | Agent or operator |
| [ship](../src/skills/ship/SKILL.md) | Commits, pushes and opens or updates the pull request. | Before diff review, after its fix pass and during an authorized ending | Agent |
| [test-guide](../src/skills/test-guide/SKILL.md) | Writes the scenarios the independent tester and you run. | After proof, before independent testing and diff review | Agent |
| [harvest](../src/skills/harvest/SKILL.md) | Ends a session with document maintenance, a retro, permitted closure or hand-back, a report and guarded cleanup. | Explicit `/harvest` or `$harvest`, in any state | Operator |
| [finalize](../src/skills/finalize/SKILL.md) | Enters harvest's finished route after its existing pre-flight. | After testing is accepted | Operator |
| [merge](../src/skills/merge/SKILL.md) | Merges the pull request after green checks and updates local main. | Directly or through harvest/finalize | Operator |
| [close-out](../src/skills/close-out/SKILL.md) | Retains the narrow vault check, legacy retro and report route. No merge or task close. | Explicit compatibility invocation | Operator |
| [plot-session](../src/skills/plot-session/SKILL.md) | Launches a worker for a plot with its kickoff and confirms delivery. | When you tell the dispatcher to dispatch | Agent, on your word |
| [update-prs](../src/skills/update-prs/SKILL.md) | Checks and fixes bot PRs, then prepares one issue for dispatch. | Scheduled run for an explicitly named plot | Agent |
| [slot](../src/skills/slot/SKILL.md) | Allocates a worktree with its own ports and resources, then launches into it. | A task that runs its project's stack beside other work | Agent, on your word |
| [dummy](../src/skills/dummy/SKILL.md) | Explains one decision plainly with options and a recommendation. | When a topic is not landing | Agent or operator |
| [bloom](../src/skills/bloom/SKILL.md) | Explains complex work in a browser-checked HTML visualization, with a private [Grove](agent-hosts.md#grove) link for eligible plots and a local path otherwise. | When you ask for a page or a view | Agent or operator |
| [browser-login](../src/skills/browser-login/SKILL.md) | Signs into an authorized HTTPS service through an isolated browser, with optional page control and operator-selected persistent authentication. | When you ask a worker to sign into a website | Agent, on your word |
| [workstation](../src/skills/workstation/SKILL.md) | Onboards macOS or Ubuntu, diagnoses a failed launch or tool and keeps the tools current. | When you say onboard me, or something broke | Agent or operator |
| [vault-optimize](../src/skills/vault-optimize/SKILL.md) | Audits a vault scope for broken links, orphans and drift, and applies approved cleanup. | When you ask | Agent, on your word |
| [vault-todos](../src/skills/vault-todos/SKILL.md) | Rolls, cleans up and adds tasks in the vault's To-Do files. | When you ask | Agent, on your word |

A plot can also own skills, delivered only to its sessions. They live under `plots/<plot>/skills/`, for example [the example application's skill](../plots/example-app/skills/example-check/SKILL.md), and [plot composition](plot-shape.md#plot-procedure-trees) explains how they add to or replace a shared one.
