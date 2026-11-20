# Fact review

Step 5 of [glean](SKILL.md). The other tool traces every claim of the recap to a saved source before the note is written.

## A session of its own

The review runner keeps one result per launcher task and mode. A second review in the same task replays the first result and checks nothing. Run the fact review only in a glean session whose task holds no review result, such as the one the weekly job starts. When the operator asks for glean in any other session, or for a second run, start a new glean session through [plot-session](../plot-session/SKILL.md) from the Slopmeister main checkout, with an unused task name, then report its name and stop.

```bash
bin/slopmeister plot-session . slopmeister slopmeister-glean-<YYYYMMDD> < plots/home/launchd/glean-kickoff.md
```

When the operator names another Monday, pass a copy of that kickoff in the scratch directory that names the week instead.

## The review

Save the output of every source read in glean's steps 1, 2 and 4 to a file in the Git-ignored scratch directory. Write the page data of glean's step 6 as JSON next to them. Before writing the note, run [cross-tool-review](../cross-tool-review/SKILL.md) once as an ad-hoc plan-mode review, with `--read-dir` for the scratch directory, the minimum set of approved source directories. The prompt names the JSON, the source files, the week bounds and each plot's read route, never your judgement. It asks the reviewer to trace every opening sentence, headline, Done and Next line, `waiting_on`, figure, number and link to a quoted source, and to report each claim it cannot trace.

Verify and prune the findings as that skill says, then apply them. Correct each claim from its source, remove it or mark its source `not read`. Never publish a claim the review could not trace. A failed or replayed review is no review, so publish nothing and name that blocker. End the Summary with `Fact review: <tool>, <claims> claims checked, <changed> fixed or removed.`
