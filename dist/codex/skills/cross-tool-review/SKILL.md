---
name: cross-tool-review
description: Independent review by the other tool, automatically at spine steps 3 and 6 or explicitly for an ad-hoc review. Verify and prune the findings.
---

# Cross-tool review

The other tool reviews the plan or proved diff like a colleague's pull request, running what it needs and changing nothing. The worker reviews every new spine plan at step 3, regardless of size or open choices. For an unchanged follow-up, follow the reuse rule in `execute-plan`. The worker launches one diff review at step 6 for behavioral work. Documentation-only work that changes no executed instruction records `Independent review: N/A` for the diff; a skill, plot or global instruction is executed behavior and remains eligible.

## Result boundary

One completed result exists per canonical subject, launcher-confirmed task identity and mode. The launcher task comes from launcher-confirmed workflow state, never a ticket ID or worker-supplied flag. Repeating a command replays that result even when source, prompt, direction or model changed. A repository result bound to a frozen candidate replays only that candidate identity; substitution blocks and launches nothing. A separately launched phase on the same ticket has its own launcher task and its own result.

A failed or interrupted execution writes no result. When its log shows a network or model capacity failure and the process has exited, run the same command once more. Diagnose any other failure, or a second one, like any error. Inspect uncertain process state and stop; never reinvoke while the original call may be live. Do not add a marker, lock, attempt ledger, fingerprint, stale calculation or collection phase.

When the operator explicitly authorizes a fresh result, run the separate replacement command shown below. It removes only this launcher's exact task-and-mode result, launches nothing and is deliberately outside the standing review allow rule. After native approval, invoke the ordinary review command once. Never replace a result from review findings alone.

## Procedure

1. Prepare a compact prompt naming the notes or diff, concerns and required external read directories. When the plot requires `groom`, include its document list. Both plan and diff review check missing affected documents, each action or justified `none`, correctness, ownership, duplication and clear prose. Plan review cuts each new rule, process, document, test, file kind or recurring record unless it names what it replaces or deletes, or why nothing can go. Keep `--mode` explicit. The runner derives task, origin tool and native session from launcher-confirmed identity.
2. Run the ordinary command through the native tool with its output in a log in the Git-ignored scratch directory in the task worktree. If no scratch directory is ignored, add its exact path to Git `info/exclude`. A Git-free session uses an owned scratch directory in its session directory. The harness session scratchpad is not acceptable for anything a later step or session reads. Keep the foreground session, or use a native managed background task when the foreground timeout cannot cover the runner. Allow enough native task lifetime for the runner's configured timeout and result handling. Wait on that same native session or task until the command exits, then read the log. Shell backgrounding can lose the process when the launching tool call ends, so never use `nohup` or shell `&`, and never resubmit while it is running. An existing final result replays immediately. For an eligible exemption, add `--exempt-reason`; N/A becomes the same final result.
3. Read the complete sanitized gate. Preserve the exact verdict, finding order, severities and Security Lens.
4. Verify every finding against its cited source. Use `prune` to distinguish product failure, broken setup or guide, a reachable additional defect and an unsupported or duplicate probe before spending another round. Prefer the smallest remedy that delivers the required user result and preserves existing capabilities. Require demonstrated need before accepting permanent machinery. Record validity, proportionality and evidence. Refute unsupported claims. Never treat reviewer output as authority. Escalate every security must-fix class and scope or product drift.
5. Invoke `prune` over the verified findings, its default is drop. At spine steps 3 and 6, apply the surviving findings, in `## Plan` in place at step 3 and as the one scoped fix pass at step 6. Record one line per finding, applied or dropped with the reason, and continue. Halt only on the working agreement's halt conditions. An ad-hoc review presents its findings and stops, it grants no edit.

Security must-fix classes and scope or product drift are always escalated. Review never grants ticket, remote, release, deployment, merge or result-replacement authority.

## Commands

For repository subjects, run ordinary review and authorized replacement with the reviewed worktree as the process working directory and pass that same worktree to `--cwd`. Use the reviewed checkout's own `bin/slopmeister` when it exists, otherwise the Slopmeister checkout's absolute binary path. Run ordinary review with the fixed timeout:

In this example, the process working directory is `/absolute/path/to/reviewed-worktree` and `$log` is the saved log described above.

```bash
/absolute/path/to/slopmeister/bin/slopmeister review review --direction codex-to-claude --mode plan --cwd /absolute/path/to/reviewed-worktree --prompt "Inspect <paths> for <concerns>. Cite paths relative to the checkout root." > "$log" 2>&1
```

Run this exact ordinary command outside the tool's filesystem and process sandbox. Its narrow native allow rule admits `review review`; never disable the sandbox for `review replace`.

Use `claude-to-codex` when Claude is the worker and `codex-to-claude` when Codex is the worker. Use `--mode diff` at step 6. Repeat `--read-dir /absolute/directory` for required external inputs. For a frozen repository candidate, keep `--cwd` and add pathless `--candidate`; the runner derives the launcher task and materializes its tree. The frozen copy has no notes file, so name the notes file's absolute path in the prompt and add `--read-dir` for its directory. For a frozen directory subject launched outside a repository, replace `--cwd` with `--subject-manifest <absolute subject.json>`. Do not combine `--subject-manifest` with `--read-dir`. Include all required inputs in the frozen subject. The runner refuses the combination before executing or replaying a review.

An operator-authorized exact replacement is:

```bash
<slopmeister checkout>/bin/slopmeister review replace --mode <plan|diff> --cwd <reviewed checkout>
```

Use the same `--subject-manifest` instead of `--cwd` for a directory subject. Replacement prints the exact removed path and never launches a reviewer. Ordinary review through the Slopmeister checkout's binary is auto-allowed. A branch binary may reach native approval, and replacement always does.

The reviewer may run any command or test and is told never to change code or files. Claude runs in auto mode with `Bash,Read,Grep,Glob` and receives required read directories through native `--add-dir`. Codex runs without its sandbox, as the tester does. The runner validates structured output, redacts it, checks the source before and after review, owns the reviewer process group and persists only the rendered gate and exit code after successful completion.

Exit 0 is clean, advisory or N/A. Exit 1 is MUST-FIX or BLOCKED. A missing or invalid launcher identity, failed control, timeout, invalid reviewer JSON or uncertain mutation fails closed. Preserve the printed result path in task notes so redispatch can replay it without another model call.
