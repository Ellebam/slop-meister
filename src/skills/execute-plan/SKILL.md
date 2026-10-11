---
description: "Continue a spine plan automatically after its plan review through implementation, proof, independent testing, declared shipping, diff review and its fix pass. Report to the operator."
---

# Execute plan

After the operator's answer to the one message and the applicable plan review, continue automatically in this worker. No additional orchestration command is required. Read each existing procedure when reaching it. The only child sessions are one bounded opposite-tool tester and the existing opposite-tool reviews. Editorial review exemptions retain their ordinary spine path.

Verify the operator's answer and the plan review result under the working agreement's evidence rules. This procedure grants no missing decision, access or stronger remote action.

## Record and resume

The task notes are the human handoff. Keep scope, decisions, approved plan, current proof, blockers and the next action once, updating stale facts in place. `## Validation` is free-form and may be selectively replaced when deterministic checks are rerun. Do not create a milestone table, worker checkpoint, copied report, transcript or per-phase handoff file.

Git is the task state. Uncommitted work shows as dirty files, a commit shows in the log, and shipped work is the remote branch at HEAD with its open PR. The tester and reviewer own their detailed state and receipts, record each returned path in the notes. Re-entry reads Git and the notes, then collects the recorded tester path and replays the review command's final result. It never infers producer state from prose, repeats a completed prompt or replaces a review result without explicit operator authorization. Missing access or a substantive producer failure stops with its evidence path and next action in the notes.

## Automatic path

1. Run `implement` against the approved plan. Record the changed files, focused gates and nominal exercised behavior under `## Implementation`.
2. Run `local-qa`, all break-it arms and applicable local gates, then `ripe`. Correct ordinary defects inside approved scope from concrete observations. Stop for scope or approach drift. With `commit = "allow"`, make the reproducible local snapshot commit under commit authority, staging named task files only. With `commit = "deny"`, do not commit.
3. Run `test-guide` and record its path, scenario IDs and expected results. With `commit = "deny"`, freeze the proven Git-visible state through `bin/slopmeister candidate freeze --cwd <absolute checkout>` and test that candidate. The command derives scope and task identity; do not supply a file list or manifest.

When the task checkout contains `bin/slopmeister`, use that binary in place of the Slopmeister checkout path in the commands here and in step 6, so a Slopmeister branch is tested and reviewed with its own code. The path shown is the fallback for other repositories.

{{TOOL:claude}}
`~/dev/slop-meister/bin/slopmeister tester launch --worker-tool claude --task <task> --cwd <absolute checkout> --commit <local commit> --guide <absolute guide> --validation <absolute notes>`
{{/TOOL}}
{{TOOL:codex}}
`~/dev/slop-meister/bin/slopmeister tester launch --worker-tool codex --task <task> --cwd <absolute checkout> --commit <local commit> --guide <absolute guide> --validation <absolute notes>`
{{/TOOL}}

The command above is the `commit = "allow"` path. With `commit = "deny"`, replace `--commit <local commit>` with `--candidate`. The explicit flag preserves missing-commit failures and loads the launcher-confirmed task's current candidate.

Add `--tester-tool opencode` only when the operator or the kickoff names OpenCode as the tester, `docs/opencode.md` under the invoking Slopmeister checkout has its setup and blocked reasons.

Record the returned tester path immediately. Collect it with `~/dev/slop-meister/bin/slopmeister tester collect --run <tester path> --wait-seconds 30`. Exit 3 is pending, so collect that same path again. Never launch another tester to collect or recover a run. The tester independently executes its required scenarios and falsification cases, worker evidence cannot replace that execution. Only those required cases decide the run. Every other counterexample is a regression candidate, and a candidate never fails a run. Apply `prune` before another round to distinguish required product failure, broken setup or guide, a valid additional defect and unsupported extras. When the first tester run fails or blocks and the fix is inside `## Scope`, your own guide included, fix it, prove it with the checks the fix affects, commit it or freeze the candidate again, and launch one new run against that. Keep both verdicts. A failed second run halts. Preserve and report an exact fail or blocked verdict without regrading it. Never repeat an unchanged matrix for another receipt.

4. Promote or fix what the tester's regression candidates and your own adversarial cases show. Verify each candidate against the code. Invoke `prune` on the candidates first. Fix real defects of the change inside `## Scope`, and retain the existing security escalation rules. Select permanent regression coverage by the shared [Test purpose](../implement/SKILL.md#test-purpose), rather than retaining every temporary control. Record each dropped candidate with its reason. Apply [behavior proof](../local-qa/SKILL.md#3-the-break-it-pass) to each distinct changed behavior or trust boundary, restore exact bytes and rerun affected checks. Record the result or why nothing applies. With commits allowed, none of this launches another tester run, including confirmation of promoted tests after a pass. If it changes a commit-deny tree, freeze the final candidate and test it once more. Record and collect its new run path; formal review uses this final tested candidate. Candidates from that final run join the diff review findings in the one fix pass. No changed bytes means no extra run.
5. Run `ship` only when both fixed commit and shipping permissions are `allow`, and record its PR URL and shipped SHA. A failed ship stops with its reason. Rerunning it after the cause is fixed never repeats a confirmed push or PR write. Otherwise record `Shipping: N/A, denied by plot` and continue to diff review without a remote write. A later explicit operator instruction may invoke `ship` through its native prompt; that separate action changes no saved permission.
6. Run the existing step 6 `cross-tool-review` once. With commit denied, use its repository `--candidate` route so reviewer and final tester consume the same tree; never use `--subject-manifest`. Its protected launcher task and mode own the final result. A repeated command replays only the same candidate identity without another launch. A failed or interrupted execution leaves no result and follows the single retry rule in `cross-tool-review`. Record the result path and exact verdict.

## Findings and report

Follow `cross-tool-review` for the returned findings. The survivors get the single scoped fix pass and affected proof, without a replacement diff review. Then run `ship` again where both permissions allow, or freeze the final candidate where commits are denied.

Run `ripe` before the operator report. Deliver the [task summary](./task-summary.md) in its shape, with one Findings line per review and tester finding. A status line without the report is an incomplete handoff. Report observed runtime and usage when available. Stop for testing acceptance. With commits denied, commit and push only when the operator says so, then run `candidate verify-commit --cwd <absolute checkout> --commit <commit>`. Only the operator types `finalize` after acceptance.
