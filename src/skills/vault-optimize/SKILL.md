---
name: vault-optimize
description: Audit and debloat this vault, read-only by default. Broken links, orphans, tag and status drift, size, and session-memory-shaped content. Safe to run often, scoped or vault-wide.
---

# Vault Optimize

A hygiene and debloat pass built to run often. The default is a read-only audit that changes nothing and ends in an itemised proposal list, so invoking it is always safe. Edits happen only afterwards, on the items the operator picked.

## Invocation

Invoke it by name with an optional scope, `/vault-optimize [scope]` on Claude Code, `$vault-optimize [scope]` on Codex, or in words. The scope is a vault path, field, project or ticket folder. No scope means vault-wide. This audit covers more than one session's own work area. Groom maintains that area during work in plots that require groom. Harvest verifies groom maintenance in every plot.

## Safety rules

- The audit is read-only. Nothing is edited, moved or deleted while it runs.
- Every finding becomes a per-item proposal naming the file, the finding, and what the fix would do. A collapse or deletion proposal also shows what would survive, and corrections and 🛑 gates always survive.
- Apply only the items the operator picked, as a separate step after the report, and commit the touched paths first so the pass is reversible, `slopmeister-vault commit "<one line>" -- <path>...`, named paths only because other sessions hold half-written notes in the same tree, per `docs/vault-version-control.md`.
- Never retrofit tags vault-wide unless explicitly requested. MOC retirement is always a proposal.
- Verify discovery claims with direct reads or `ls` before reporting them.

## What the audit checks

1. Broken links and orphans, via the commands below.
2. Index and status drift. README frontmatter is canonical, `_INDEX.md` rows and visible status headings mirror it, and disagreements get a repair proposal.
3. Tag drift against `_system/TAG_TAXONOMY.md`.
4. Session-memory-shaped content, the debloat core. The charter is `_system/guidelines/documentation.md`, section "The vault is not your memory". Look for `research/` notes narrating a session's process instead of stating validated findings, superseded parallel drafts of the same deliverable, per-session duplicates of an existing note, orphaned handoff or scaffolding files, WORKLOG entries grown into transcripts, restatements of sources that are already linked, and meta-apparatus (registers, queues, banners) around the session's own work product. For closed tickets and withdrawn tracks, propose the collapse to outcome plus pointer.
5. Size. The largest files and the attachment weight inside the scope, because a vault size problem is almost always an attachment problem.

## Audit commands

The Markdown filesystem is authoritative. The following optional read-only Obsidian index queries enrich a whole-vault audit when the app is available; their failure never blocks direct file checks or makes the audit clean.

Run from the prepared workspace. Set `VAULT_SCOPE` to the absolute vault folder requested for the audit, or the vault root for a whole-vault audit, in the same shell invocation as the filesystem audit below. Shell variables from an earlier tool call may not persist. Filesystem commands must use that path, never the workspace's current directory.

```bash
slopmeister-vault obsidian -- vault=obsidian unresolved verbose   # broken links and referrer
slopmeister-vault obsidian -- vault=obsidian unresolved total     # number to track over time
slopmeister-vault obsidian -- vault=obsidian orphans | grep '\.md$'  # unlinked markdown
slopmeister-vault obsidian -- vault=obsidian tags counts sort=count  # tag census
```

```bash
if [[ ${VAULT_SCOPE-} != /* || ! -d ${VAULT_SCOPE-} ]]; then
    printf '%s\n' 'Set VAULT_SCOPE to an existing absolute vault folder.' >&2
    exit 2
fi
grep -rlE '^\|.*\[\[[^]]*[^\\]\|[^]]*\]\]' --include="*.md" -- "${VAULT_SCOPE%/}/"  # unescaped alias pipe in a table row
```

The trailing slash makes the audit follow a symlinked scope root. Grep exit 0 means matches, exit 1 means clean, and any other exit or error output means the audit did not complete.

The adapter supplies closed stdin and preserves status: 2 refuses a non-read-only operation, 124 terminates a timed-out process group and 127 means Obsidian is unavailable. Continue with the filesystem checks after any optional adapter failure. The full retrieval contract and its traps are `_system/guidelines/retrieval.md`.

## Report

One line per finding, grouped by category, each with its proposal. Close with the trend numbers, unresolved links, markdown orphans, and scope size, so repeated runs show whether the vault is getting leaner. Structural non-defects (WORKLOGs, dated `comms/` drafts, templates and To-Do files are unlinked by convention, and the leaf-name tag collisions are intended) are not findings.
