---
name: prune
description: "Prune: critically reassess whatever is on the table, a review's findings, a proposal, a plan, a diff, your own draft or gaps you are about to raise, for validity, overengineering and added complexity. Invoke after a review returns, before handing findings or gaps to the operator, to check your own or another agent's output, or whenever the operator asks. Read-only and safe to repeat."
---

# Prune

Reassess what is on the table in this discussion right now. It needs no prior review, step or notes file, writes nothing, and is safe to repeat. Answer every question for each item, and say which ones fail and why.

- Really valid or overengineering?
- Does this remove redundant machinery?
- Does it remove unneeded paperwork, or at least add none?
- Is bookkeeping minimized?
- Did we apply KISS and YAGNI, is it DRY?
- Is the solution the most elegant it could be?
- Are the suggestions workable for engineers, readable and maintainable?
- Did we reduce the complexity of the whole system?

Classify findings before spending another round. Distinguish a required product failure, broken setup or guide, a valid additional defect and a speculative or duplicate probe. Verify the caller or input and observable consequence. Diagnose setup before blaming the product. Keep exact saved verdicts, this triage never regrades them. Additional tester defects use the existing candidate path, not new required scenarios.

Agents overbuild and reviews reward it, so the default verdict is drop. An item survives when it is a security, data-loss, authority or recovery matter, when required behavior fails without it, or when evidence shows a reachable harmful failure of the change. Fix real defects of the change inside scope and escalate under the existing security and scope rules. Drop unsupported or duplicate extras with a reason the operator can reopen. Apply [Test purpose](../implement/SKILL.md#test-purpose) before retaining regression coverage. Where an item fails, name the smaller or simpler remedy.

When checking your own draft that nobody has seen yet, revise it and continue. Inside a spine run, apply what survives and record what you dropped and why. When the operator asked for the assessment, present it and stop for their decision.
