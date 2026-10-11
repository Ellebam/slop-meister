# Task summary

Every large message a worker sends at the start or the end of work uses this guidance. That covers the one message of `sow`, the opening plan and closing report of a freeform session, the testing handoff, a halt, a blocked exit, the finalize report and the tracker close-out comment.

## The operator summary

The operator is the first reader. They read on a phone, between many sessions, and must decide in under a minute. Open every such message with a summary that stands alone, and put nothing before it.

- Write in plain words. Say what the user of the change gets, not how the code does it.
- The summary has no file path, line number, command, command output, commit hash, procedure or step name, and no internal term the operator did not use first. Explain a technical term you cannot avoid in the same sentence.
- The summary is at most 150 words. The whole message is at most 350 words. Count the words before you send, and cut until both limits hold.
- What does not fit moves to the pull request, the notes file or a linked receipt, and the message says in one line where it is. Chat is not the archive. Move evidence, never drop it.
- A blocker, a failed proof or a non-clean merge state is the first line of the summary.
- Review and tester verdicts keep their exact wording.

Reviewer detail follows the summary under **Details**. The operator can stop reading before it.

## The opening message

```markdown
**Goal** <what the task achieves for its user>
**Plan** <what you will do, the smallest change that satisfies the task>
**Your call** <each open decision with its options and one recommendation, or "nothing, reply go">
**Risk** <the main thing that could go wrong>

**Details**
<short lists for the reviewer, and where the full plan is>
```

## The closing message

```markdown
**Result** <the outcome in one sentence>
**Proven** <whether it is proven and by what, with the exact tester and review verdicts>
**Weak** <what is weak or was not checked>
**Your move** <the one thing the operator does next, in plain words>

**Details**
- Why: <issue link, and each operator decision that departs from the issue>
- Findings: <one line per review and tester finding, applied or dropped with the reason, or none>
- Checks: <the test guide's operator checks spelled out, with their commands>
- Status: <pull request link and merge state>
- Files: <where the file list is, normally the pull request>
```

A halt or a blocked exit uses the closing shape. **Result** states the blocker and its diagnosis, and **Your move** opens with the recommendation.

The tracker close-out comment has a different reader and survives cleanup. It opens with the same summary, keeps the full detail below it and has no limit on the whole. List each changed file with its role in one line, state what a local file would tell the reader instead of pointing at a local path, and add the retro lines last.

## Evidence

Preserve actual review and tester verdicts and uncertainty. The operator can reopen any finding from its line. Link evidence near the claim it supports and retain unchanged originals with their producers. Missing evidence stays unproven. Never infer approval, regrade a tester or claim later cleanup has happened. At close-out, cite evidence that survives cleanup.

Record each fact once. A continuing procedure carries its results into the eventual handoff instead of producing another report. This guidance changes no workflow action or permission.

When an autonomous run stops for testing acceptance or at a halt, the message goes in that same response and before the request. A completion notice, a bare list of receipt paths or only an invitation to test does not satisfy this, and the operator should never have to ask for the report.

Render it from the notes, Git state and the producer receipts that already exist. Do not create another report file, copy full producer logs, add a phase or a milestone table, or repeat a report the operator already received. If an authorized amendment or replacement review makes the run continue, replace the stale facts and give one refreshed report at the next handoff rather than appending a second history.
