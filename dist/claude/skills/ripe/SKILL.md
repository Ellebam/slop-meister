---
description: "Check whether we delivered the intended outcome and need more work. Use before questions, handoffs, completion claims or extra work, and whenever asked for status. Read-only except the stuck handoff."
---

# Ripe

Read the task and look at the work as it stands.

Did we fix what we meant to fix or build what we meant to build? Check each acceptance point against what the user can actually do. Did you actually run the fix or feature the way people will use it after it ships? Say what works, what is missing, and what you have not checked. If your change may have broken something else, say whether you checked.

Are we overdoing it? After plan approval with nothing shipped, an operator status request or statement that the session is the problem means "stuck". Write a handoff in the task notes, recommend redispatch or a split and stop. Otherwise, stop if the next step does not help finish the task or clear a required gate.

Are the task notes still light? When they exceed 64 KB, the next action is to trim them before other work, outside a lab or deploy window. Keep decisions, scope, plan, proof, open gates, the next action and restart commands, and leave evidence with its producers. Keep the goal, operator decisions, current step, next action, open gates and restart commands current in the first 8 KB, because after a compaction the session gets back only that part of its notes, not the conversation.

Keep this check internal unless a report is due. Then state the result, evidence and next action once. Say done only when the outcome works and required gates are complete. Never skip a gate or operator decision.

Before every worker turn ends, run the [context check](../plot-session/recovery.md#worker-context-check). This is routine session care, including outside Night mode and without a manager. An open lab or deploy window blocks its request. A pending operator question blocks it too, except for a manager whose saved handoff states that question verbatim. Unknown observations remain unknown.

Read-only except for trimming task notes, saving a handoff and the context request. Do not edit product files, repeat a test or review, or create another report or checklist. Simple read-only checks are allowed.
