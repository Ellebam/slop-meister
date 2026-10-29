# Task summary

Use this guidance for the `sow` message, freeform opening and closing, testing handoff, halt, blocked exit, harvest report and tracker closing comment.

## The operator summary

The operator is the first reader. They read on a phone, between many sessions, and must decide in under a minute. Open every such message with a summary that stands alone, and put nothing before it.

- Use plain words and the operator's own term for each existing thing. Say what exists today, give one real example of the problem before any fork, and say what the user gets.
- The summary has no file path, line number, command, command output, commit hash, code, function name, API name, backticks, procedure or step name, and no internal term the operator did not use first. Explain a technical term you cannot avoid in the same sentence. Put implementation identifiers under Details even when the ticket uses them.
- Keep the summary within 150 words and the whole message within 350 words. Aim for about 100 summary words. Check the exact draft locally. Count whitespace-separated words before Details and in the whole message, and reject summary backticks. Shorten Goal and Details first, keeping Plan cuts and New answers. Copy the checked draft verbatim into the final message.
- What does not fit moves to the pull request, the notes file or a linked receipt, and the message says in one line where it is. Chat is not the archive. Move evidence, never drop it.
- A blocker, a failed proof or a non-clean merge state is the first line of the summary.
- Review and tester verdicts keep their exact wording.

Reviewer detail follows the summary under **Details**. The operator can stop reading before it.

For one or two open operator decisions, keep each recommendation and the pros and cons per option in chat. Use short option lines under Details when needed. Cut background before decision content to meet the word limits. For three or more, follow [Bloom's decision-page form](../bloom/SKILL.md#decision-pages) by standing request. Your call directs the operator to the page link and one numbered line per decision under Details. Put the options and exact publication text on the page.

## The opening message

```markdown
**Goal** <what the task achieves for its user, in your own words>
**Plan** <smallest option first, list the cut items by name and why, then what you will do>
**New** <every new rule, process, command, credential, schema, setup step, document, test, file kind or recurring record. For each, name what it replaces or deletes, or say "nothing can go because <reason>". Name the existing tool tried and why it fails. Cut unanswered items. Otherwise "Nothing new.">
**Your call** <real forks only, each with its options and one recommendation, or "There is no open choice. Reply go to approve the plan.">
**Risk** <the main thing that could go wrong>
**Proof:** <proof depth based on what the change touches>

**Details**
<short lists for the reviewer, what you read, what you build, the proof, what you leave out and where the full plan is>
```

## The closing message

```markdown
**Result** <the outcome in one sentence>
**Proven** <open with "In the real system" or "Local only", then say by what, with the exact tester and review verdicts>
**Weak** <what is weak or was not checked>
**Your move** <the one thing the operator does next, in plain words>

**Details**
- This work follows <issue link>. <Explain each operator decision that departs from the issue.>
- I <applied or dropped> <review or tester finding> because <reason>. <Use one bullet per finding, or write "There were no findings.">
- Run <operator-check command from the test guide>. Expect <result>.
- The pull request is <link>. Its merge state is <state>.
- The changed files are listed in <location, normally the pull request>.
```

A halt or a blocked exit uses the closing shape. **Result** states the blocker and its diagnosis, and **Your move** opens with the recommendation.

The tracker closing comment has a different reader and survives cleanup. It opens with the same summary, keeps the full detail below it and has no limit on the whole. List each changed file with its role in one line, state what a local file would tell the reader instead of pointing at a local path, and add the three retro lines last: went well, went wrong including every operator intervention and any step that changed no decision, worth changing. No taxonomy, score or counter.

## Evidence

Preserve actual review and tester verdicts and uncertainty. The operator can reopen any finding from its line. Link evidence near the claim it supports and retain unchanged originals with their producers. Missing evidence stays unproven. Never infer approval, regrade a tester or claim later cleanup has happened. At harvest, cite evidence that survives cleanup.

Record each fact once, from the notes, Git state and existing producer receipts. Carry results into the handoff, not another report file, copied logs, phase or milestone table. At testing acceptance or a halt, give the report in the same response before the request. A completion notice, receipt list or test invitation is insufficient. After an authorized amendment or replacement review, replace stale facts and refresh the next handoff instead of repeating history. This guidance changes no workflow action or permission.
