# Dependency update pull requests

The shared [update-prs skill](../src/skills/update-prs/SKILL.md) owns the daily check and bounded fix attempt, the quiet weekly issue, and the handoff to an operator-dispatched worker. Each scheduled task must name its repository and plot. Merge, posted approval and deployment require operator action.

## Activation

The operator enables the dependency bot and schedules for each selected project. Use a dedicated prepared worktree and a credential-free smoke stack separate from live services. The schedule, model choice and active state belong to that project's own configuration.

In the [Scheduled task](https://learn.chatgpt.com/docs/automations?surface=app), select that worktree as a local project and trust its `.codex` layer. Before activation, verify effective `approval_policy=never`: direct push and merge refuse unattended while the fixed helper runs. [OpenAI Docs](https://learn.chatgpt.com/docs/agent-configuration/rules) explains why project rules require trust. Missing CI, isolated smoke or effective rules stops activation.

## Proof

`.venv/bin/python -m pytest -q tests/integration/update_prs tests/integration/install/test_update_pr_delivery.py` exercises a passing and breaking PR against a local bare origin, the exact bot-branch push, one dispatch issue and no default-branch change. `task check` is the repository gate. Each host's Scheduled run and project smoke need separate acceptance before activation.
