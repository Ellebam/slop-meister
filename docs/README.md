# Documentation

New here? Start with the [project overview](../README.md), then follow [one session from dispatch to finish](session-walkthrough.md).

## Contents

- [Get something done](#get-something-done)
- [Understand the pieces](#understand-the-pieces)
- [Find a procedure](#find-a-procedure)

## Get something done

| I need to… | Go here |
|---|---|
| Set up a workstation, diagnose a failed launch or tool, or update the tools | Tell an agent in the checkout, the [workstation skill](../src/skills/workstation/SKILL.md) runs it, see the [Quick start](../README.md#quick-start) |
| Command a configured remote host from the Mac or phone | [Remote dispatch](remote-dispatch.md) |
| Launch or resume a worker | [The dispatcher's first run](session-walkthrough.md#prepare-and-dispatch), then [the launcher procedure](../src/skills/plot-session/SKILL.md) |
| Set up Orca, its phone pairing and what agents may drive in it | [Orca onboarding](orca.md) |
| End or hand back a session | [Harvest](../src/skills/harvest/SKILL.md) |
| Remove a retired workspace or recover failed removal | [Workspace removal](workspace-removal.md) |
| Read or change GitLab issues, epics and merge requests | [GitLab through glab](gitlab.md) |
| Deploy Home Assistant approvals or Grove on Linux | [Host services](../host/README.md) |
| Request a secret from an agent session, on either machine | [Secret requests in two tiers](1password-access.md) |
| Sign a worker into a website | [Browser login](browser-login.md) |
| Find a 1Password item by title without reading values | [Item metadata search](1password-access.md#item-metadata) |
| Add a project | [Onboard a project](context-layer.md#onboard-a-project) |
| Prepare project secrets | [1Password integration](1password.md) |
| Run parallel stacks and service testers | [Slots](slots.md) |
| Try Atlassian service actions against local Jira and Confluence | [Atlassian sandbox](atlassian-sandbox.md) |
| Start a dispatcher from a phone, or recover one after a restart | [Phone access on macOS and Ubuntu](phone-access.md) |
| Set up another agent machine, or learn what every agent machine must do | [Agent machines](agent-hosts.md) |
| Run OpenCode as a worker or tester | [OpenCode](opencode.md) |
| Keep the Go plugin available to Codex from a local marketplace, optional | [Codex plugins](codex-plugins.md) |
| Publish a tested version | [Release maintenance](releases.md) |
| Change configuration and check it | [Contributing](../CONTRIBUTING.md) |
| Choose checks, read failures or measure QA time | [Testing and evidence](testing.md) |
| Configure consent for Slopmeister and vault reviews | [Review consent](review-consent.md) |
| Maintain affected repository docs and vault knowledge | [Groom](../src/skills/groom/SKILL.md), during work, direct harvest or a scoped request |
| Start with a local vault, then save or recover changes | [Vault setup and history](vault-version-control.md) |
| Add optional Google Drive sync | [Document access and sync](drive-access.md) |
| Read and file mirrored documents or use Drive in the browser | [Document access](drive-access.md) |
| Find a command | [Taskfile](../Taskfile.yml), or `task --list-all` |

## Understand the pieces

| Question | Read |
|---|---|
| What are the layers and the vocabulary? | [Project overview](../README.md#how-the-farm-runs) |
| What does each skill do, and who starts it? | [Skills index](skills.md) |
| What happens during a task? | [Session walkthrough](session-walkthrough.md) |
| What rules does a Slopmeister worker load? | [Rendered agreement](../dist/codex/plots/slopmeister.md) |
| What belongs in an issue or kickoff? | [Task briefs](contracts.md) |
| How does a plot find project knowledge? | [Context and ownership](context-layer.md) |
| How do sources become tool-specific files? | [Plot composition](plot-shape.md) |
| What does a launched session receive, and what may it run? | [The launcher](launcher.md) |
| How are ports and resources kept apart? | [Slots](slots.md) |
| Who owns each part of an agent machine? | [Agent machines](agent-hosts.md) |
| How much context does startup use? | [Startup measurement method](startup-context.md) |
| Where are plots and the reviewer and tester defaults declared? | [Plot declarations](plot-shape.md#declaration) and [reviewer and tester settings](../slopmeister/review/defaults.toml) |

## Find a procedure

The [skills index](skills.md) names every procedure, what it does, when it runs and who starts it.

> [!TIP]
> Returning to a task? Read its saved notes, find your step in the [walkthrough](session-walkthrough.md#the-ten-steps), then open that procedure. The notes carry the decisions already made.

[Testing environments](testing-environments.md) owns CI, workstation, real-session and temporary-fixture prerequisites.
