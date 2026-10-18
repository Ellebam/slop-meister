---
description: "Close-out: verify the task's vault maintenance, record the retro and tracker report, and remove its notes. Operator-invoked, before finalize cleanup. Not a merge or task close."
disable-model-invocation: true
---

# Close-out

Run only on the operator's instruction, directly at a freeform handback or through finalize. Complete these duties before finalize removes the worktree. A pause keeps the notes and runs no close-out. Stop only for the record states duty 1 names.

Write one retro entry per finished task, using the notes to retain earlier sessions' lessons. A re-ticketed task records its entry when that ticket finalizes.

Five duties, in this order.

## 1. The vault area this session worked in

A session that opened or edited vault notes for its work verifies the area's consolidation, leanness and indexing using the Slopmeister-delivered instructions and the area's knowledge and documentation conventions. Ordinary authorized vault-document changes already keep their owning route and direct references consistent before each handoff. A session that never opened a vault note has nothing to do here and says so in one line. That line is not available to a session whose record, its own reads and writes, or the native session shows vault access, and a record holding only navigation notes ends this duty with one explicit line naming those notes and stating that no substantive note was opened. A vault-wide audit is `vault-optimize`, a separate operation the operator asks for by name, never this duty.

The area comes from the record the session kept in its notes file as it worked, under a heading of its choosing such as `## Vault area` which no script reads, one line per note it opened for the work, `<vault-relative path>, explored` or `<vault-relative path>, edited, first-touch <state>, sha256 <digest>` with the first-touch state recorded before the first write, `clean`, `absent`, `dirty` or `unknown`, and the digest of the note as the session last wrote it, `shasum -a 256`, refreshed after every write. A transitional `<vault-relative path>, first-touch <state>` means ownership was recorded but the write did not complete. It is a usable scope record, but because it has no completion digest, leave the note unchanged, never commit it and name it in the handoff. Hits from a vault-wide search the session never opened are not recorded, an incidental search does not make the vault the area. Shared navigation notes, such as the root or collection indexes, create no area and cannot widen one. Derive the area from the substantive notes the session worked on. Each such note's nearest owning folder is the area, a ticket folder, a field folder or a `_system` subfolder, never the vault root, and notes in unrelated folders form separate areas handled one after the other. A field folder's project and ticket folders are separate areas, so a field folder is linted with `--shallow` and each such folder a recorded note sits in is linted as its own area. The navigation that keeps an area coherent belongs to it, the folder's own `_INDEX.md` or `README.md` and the direct parent row that points at the folder, nothing further up. Before any vault write, check the record against what this session actually did. A missing `explored` line never stops this duty, and neither does a missing notes file in a session that made no vault write. The session builds those lines from its own read history, states them in one line and continues. This duty stops for an operator answer in three states, and nothing is written until the answer arrives and is entered into the record, a note this session created or edited that has no first-touch record, a recorded path that does not exist and was not removed by this session, and a resumed session whose earlier read history is not available while its record is missing, empty or unparseable. A changed digest is not one of them, that note stays as it is under the rule below. Ask the operator which folders and notes the session worked in, then continue from the corrected record.

Before any write or commit, apply the operator's read-only instruction or narrower restriction. Report the housekeeping it excludes and leave that content unchanged. If the whole area is read-only, stop this duty here.

A finding this session saves belongs in the vault only when it is verified or operator-confirmed, demonstrably useful to future work, unavailable from a source that can be linked instead, and durable enough to remain accurate. Corrections, decisions with their reasoning and costly discoveries belong in their canonical note. Use source pointers for changing values and readily retrievable facts. Do not save new session narratives or hypotheses as durable knowledge. Existing notes are governed by the consolidation and preservation rules below, not pruned by this admission test.

For a plot requiring `groom`, verify the affected document list in `## Plan` or the freeform session notes against its completed content. Missing entries or unmet actions stop without content edits. Its maintenance was completed before review or the freeform handback. Keep the ledger, ownership, lint and eligible commit checks below, but skip the consolidation writes. Report the documents changed or a justified `none`.

Then, in this order. Check the first-touch state recorded before each edit and recompute its last-write digest. A note that was already dirty, has unknown first-touch state or no longer matches its digest stays exactly as it is, is never committed by this session, and is named in the handoff. A matching digest alone does not establish ownership of earlier changes. Before a consolidation write to an unedited note, check `~/.vault-git/bin/vaultgit status --porcelain --untracked-files=all -- <path>` and leave any staged, unstaged or untracked content alone. Commit only the eligible area paths this session edited that still show a change, an earlier milestone commit leaves the rest clean, with `slopmeister-vault commit "<one line>" -- <path>...`, named paths only, so every step that follows is reversible through `~/.vault-git/bin/vaultgit`. Run `slopmeister-vault lint --area <folder>`, with `--shallow` where the area rule above calls for it, and keep its output.

Only plots that do not require `groom` perform the following consolidation. Save qualifying findings in their canonical notes, then consolidate. Duplicated knowledge moves into its canonical home and the duplicate goes. Superseded material shrinks to its outcome plus a pointer. Disposable session material, scratch, hypothesis trees, scaffolding and drafts nobody will read again, is removed. Links and index rows are repaired so every row resolves and nothing the area keeps is left orphaned. Corrections and 🛑 gates survive every collapse, decisions keep their reasoning, evidence a pending review still needs stays byte for byte, a note keeps its status because housekeeping changes no ticket status, and a file carrying changes this session did not make is not touched.

Run the area lint again. Zero on every count except `protected links` is required to call the area clean. That count holds the unresolved links in published page mirrors, which the live page owns. Leave those links unchanged and name the count in the handoff. If other protected content prevents a clean area, leave it unchanged and report each remaining defect with its path and protection reason as blocked housekeeping. In plots requiring `groom`, report unmet maintenance and stop without repair. Other plots fix remaining in-scope defects, then commit only eligible housekeeping paths. Do not waive lint or claim full consolidation while such a defect remains. Summarize the area outcome and protected blockers in the handoff, retaining the exact lint results in evidence.

No vault-wide sweep, the area is the folders the record names and nothing beyond. For plots that do not require `groom`, ordinary housekeeping inside it needs no approval list, the operator authorized it by typing this procedure. `slopmeister-vault lint` without an area stays the global regression count for the record, it proves nothing about the area.

## 2. The retro entry

Three free-text lines, went well, went wrong including every operator intervention and any step that changed no decision, worth changing. No taxonomy, no score, no counter. Three fields beside them, repository, tool and model.

The entry goes to the cross-project log in the vault, `_system/retro-log.md`, through the installed Slopmeister vault command, which works from any directory without an editor process. The command holds the existing single shared commit lease across its direct append and Git commit before it reports success.

```bash
printf '%s\n' '<went well>' '<went wrong>' '<worth changing>' \
  | slopmeister-vault retro --repo <repository> --task '<task identifier>' \
      --title '<task title>' --tool '<Claude Code or Codex>' --model <model>
```

A finalize re-run skips this duty when the log already carries this task's heading. The command deletes replayed spills only after Git contains their entries. When the own entry cannot be verified and committed, any appended Markdown remains dirty, the existing spill queue retains the input and the command exits 1 naming the note and spill for the next agent. Record those paths in notes, summarize the next action in the handoff, and do not retry by hand. The next close-out on this machine with vault access replays every spill before its own entry.

A project that keeps its own retro log appends the same entry to both, its own log in that log's shape and the vault log through the installed command, and its plot says where the project's log is. A freeform session, research, debugging, a one-off audit, gets its entry when the operator types this procedure at its end, the three lines describe the session that happened.

## 3. The comment or the report

Where we own the tracker, post one comment using the [task summary](../execute-plan/task-summary.md), including the existing retro lines and how to see the result. Report the state known at this point, without claiming that later cleanup has happened. Where we do not own the tracker, the same content is the report to the operator, who carries it into the field's system.

For GitHub, require the project's existing commit and shipping allow permissions and pin the comment to the explicit repository and issue, using the saved launcher association where present. Invoking close-out, directly or through finalize, authorizes this prescribed comment without another permission question. It authorizes no new issue selection, extra progress comments or claim release. A pause does not run close-out and retains its claim.

## 4. The notes file

Before deleting notes, retain otherwise-lost recovery records outside the worktree until resolved: unanswered questions, spill/attempt paths and each live process's exact start command, working directory, environment and port. Keep these records private, redacting secrets in commands and environment values. Reuse existing evidence when available. Delete `<TASK-ID>-NOTES.md` and other root notes carrying this task's identifier, record the deletions and leave other files alone.

## 5. The handoff

Use the [task summary](../execute-plan/task-summary.md), retaining unanswered questions and unresolved recovery or housekeeping. When the worth-changing line names a concrete tooling defect, use the owning project's context to locate its tracker. Include an existing issue reference or a one-line proposed title in the handoff, and file nothing. Keep exact recovery records in files and cite surviving evidence. Finalize delivers the handoff once cleanup is known, or before a slot session's self-cleanup with that cleanup reported as pending. The self-cleanup closes a slot session. The dispatcher or operator closes any other session.

## Rules

- Never write to the canonical log while testing, the fixture goes to a dedicated note the test removes.
- Never create anything git-shaped in the vault.
- No merge, no ticket close, no status change here, those are finalize's and need the operator.
- Every finished task, no exceptions, a task that finalizes without an entry is the blind spot this procedure exists to remove.

## Arguments

$TASK_DESCRIPTION
