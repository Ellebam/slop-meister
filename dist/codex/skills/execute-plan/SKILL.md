---
name: execute-plan
description: "Continue a spine plan automatically after its plan review through implementation, proof, independent testing, declared shipping, diff review and its fix pass. Report to the operator."
---

# Execute plan

After the operator's answer to the one message and the applicable plan review, continue automatically in this worker. No additional orchestration command is required. Read each existing procedure when reaching it. Run the approved proof depth and the existing opposite-tool reviews. Use an independent tester when the approved proof requires one.

Verify the operator's answer and the plan review result under the working agreement's evidence rules. This procedure grants no missing decision, access or stronger remote action.

## Record and resume

The task notes are the human handoff. Keep scope, decisions, approved plan, current proof, blockers and the next action once, updating stale facts in place. `## Validation` is free-form and may be selectively replaced when deterministic checks are rerun. Do not create a milestone table, worker checkpoint, copied report, transcript or per-phase handoff file.

Git records dirty files, commits and the shipped branch. Keep producer receipt paths in the notes. Resume from Git and those receipts by collecting the recorded tester run and replaying the protected review result. Never infer producer state from notes, repeat a completed prompt or replace a result without explicit authorization. Failed checks follow Test failures in the working agreement. Other producer failures stop with evidence and the next action.

A follow-up for the same issue reuses a prior plan answer and review only after reading the operator answer in the earlier session record, comparing the earlier approved plan with the proposed plan, and inspecting the original review result. A kickoff, issue, notes or peer claim alone is not approval. Record the earlier result path and verdict without launching a new review. Reuse prior proof only where its evidence covers the unchanged work and current state. If the plan changed, obtain the plan answer and run a new plan review. If evidence is unavailable, report it and do not infer approval or proof.

## Automatic path

1. Run `implement` against the approved plan. Record the changed files, focused gates and nominal exercised behavior under `## Implementation`.
2. Run `local-qa`, all break-it arms and applicable local gates, then `ripe`. Apply the working agreement's Test failures section to failed checks, including its test-only scope exception. Stop for product scope or approach drift. With `commit = "allow"`, make the reproducible local snapshot commit under commit authority, staging named task files only. With `commit = "deny"`, do not commit.
3. With `commit = "deny"`, freeze the proven Git-visible state through `bin/slopmeister candidate freeze --cwd <absolute checkout>`. The command derives scope and task identity; do not supply a file list or manifest. Run `test-guide` and record its path, scenario IDs and expected results. If the approved proof does not include an independent tester, record why, skip launching and collecting the tester, and continue at step 4 with your own adversarial cases. Otherwise, when commits are denied, test that candidate.

When the task checkout contains `bin/slopmeister`, use that binary in place of the Slopmeister checkout path in the commands here and in step 6, so a Slopmeister branch is tested and reviewed with its own code. The path shown is the fallback for other repositories.

`<invoking-slopmeister>/bin/slopmeister tester launch --worker-tool codex --task <task> --cwd <absolute checkout> --commit <local commit> --guide <absolute guide> --validation <absolute notes>`

The command above is the `commit = "allow"` path. With `commit = "deny"`, replace `--commit <local commit>` with `--candidate`. The explicit flag preserves missing-commit failures and loads the launcher-confirmed task's current candidate.

When a repository guide starts a local service that needs allocated ports, add `--slot-target <plot>`. The existing slot owner reserves separate ports for the tester checkout and releases them after testing. This supports port-only and Compose plots and both repository routes. For a Compose plot, the owner starts the declared stack before admission and removes it before collect returns. A plot with `testers` declared runs one tester per tester-only slot, so collect a running tester before you launch the next. The guide still owns dependency installation, repository setup and application startup. Leave the option out for guides that need no service allocation. Follow the slot recovery rules in `docs/slots.md` under the invoking Slopmeister checkout if cleanup retains a claim.

Add `--tester-tool opencode` only when the operator or the kickoff names OpenCode as the tester, `docs/opencode.md` under the invoking Slopmeister checkout has its setup and blocked reasons.

Record the returned tester path immediately. Collect it with `<invoking-slopmeister>/bin/slopmeister tester collect --run <tester path> --wait-seconds=300` with a tool timeout of at least 330 seconds. Exit 3 means pending, so collect the same path again. Never launch a tester to collect or recover a run. The tester executes required guide scenarios independently, including read-only falsification. Worker evidence cannot replace execution. Only required scenarios decide the verdict, a candidate never fails a run. Use `prune` and the working agreement's Test failures section for fail or blocked results. After repairing the first run's failure, prove it with affected checks and commit it or freeze the candidate again. A new tester round beyond the approved proof needs the operator's order. Follow Test failures for later failures, without an automatic tester loop. Report all verdicts unchanged. Never repeat an unchanged matrix for another receipt.

4. Promote or fix what the tester's regression candidates and your own adversarial cases show. Verify each candidate against the code. Invoke `prune` on the candidates first. Fix real defects of the change inside `## Scope`, and retain the existing security escalation rules. Select permanent regression coverage by the shared [Test purpose](../implement/SKILL.md#test-purpose), rather than retaining every temporary control. Record each dropped candidate with its reason. Apply [behavior proof](../local-qa/SKILL.md#3-the-break-it-pass) to each distinct changed behavior or trust boundary, restore exact bytes and rerun affected checks. Record the result or why nothing applies. With commits allowed, none of this launches another tester run, including confirmation of promoted tests after a pass. If it changes a commit-deny tree, freeze the final candidate. A further tester round beyond the approved proof needs the operator's order. Formal review uses the final candidate. Candidates from the last tester run join the diff review findings in the one fix pass. No changed bytes means no extra run.
5. Run `ship` only when both fixed commit and shipping permissions are `allow`, and record its PR URL and shipped SHA. A failed ship stops with its reason. Rerunning it after the cause is fixed never repeats a confirmed push or PR write. Otherwise record `Shipping: N/A, denied by plot` and continue to diff review without a remote write. A later explicit operator instruction may invoke `ship` through its native prompt; that separate action changes no saved permission.
6. Run the existing step 6 `cross-tool-review` once. With commit denied, use its repository `--candidate` route so reviewer and any final tester consume the same tree; never use `--subject-manifest`. Its protected launcher task and mode own the final result. A repeated command replays only the same candidate identity without another launch. A failed or interrupted execution leaves no result and follows the single retry rule in `cross-tool-review`. Record the result path and exact verdict.

## Findings and report

Follow `cross-tool-review` for the returned findings. The survivors get the single scoped fix pass and affected proof, without a replacement diff review. Then run `ship` again where both permissions allow, or freeze the final candidate where commits are denied.

Run `ripe` before the operator report. Deliver the [task summary](./task-summary.md) in its shape, with one bullet per review and tester finding. A status line without the report is an incomplete handoff. Report observed runtime and usage when available. Stop for testing acceptance. With commits denied, commit and push only when the operator says so, then run `candidate verify-commit --cwd <absolute checkout> --commit <commit>`. Only the operator orders `harvest` after acceptance.
