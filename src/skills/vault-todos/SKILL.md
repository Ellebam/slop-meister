---
name: vault-todos
description: Roll, clean up, and add tasks in this vault's To-Do files, on explicit operator request only.
---

# Vault Todos

Run this only when the operator explicitly names this skill or asks for a task to be added or managed in so many words. The words "todo" or "task" merely appearing in a discussion are not a trigger, and open points from project work go to the owning ticket's README, never into `To-Do/`, per the vault's `To-Do/README.md`.

Read the vault's `To-Do/README.md` for task-file routing. The helper's keys are the task file names under `To-Do/` without `.md`, so a new task file needs no helper change. It refuses an unknown key and names the available ones. Tasks use Obsidian Tasks syntax, `- [ ] Description 📅 YYYY-MM-DD`. Write to the files directly, never through an agent framework's internal task tool.

## Arguments

An optional inline-todo string, fields separated by `;`, tasks within a field by `,`, keys case-insensitive:

```
work: Review the draft, file the report; personal: Book an appointment
```

With no arguments, run roll and cleanup only and skip the add step. With arguments, roll and clean the named fields' files too. When in doubt, roll and clean every file, and add tasks only where specified.

## Procedure

Determine today's date, `TODAY`.

1. Roll overdue to today. In each `## Active` section, every unchecked `- [ ]` task dated before `TODAY` gets its `📅` date set to `TODAY`. Exception, a line carrying a `🔁` recurrence marker keeps its date, those are future-dated by design. Tasks dated `TODAY` or later stay untouched.
2. Clean up. Any `- [x]` task under `## Active` moves to the top of `## Done` as one block with the indented lines directly under it, keeping its `📅` and `✅` dates. Tasks moved in one run go in newest-first. Existing `## Done` lines stay as they are. Do not reformat or re-sort them.
3. Add new todos, only when the argument string provides them. Append each task to the top of that field's `## Active` as `- [ ] <Description> 📅 TODAY`, preserving the casing as written. Priority markers (`⏫` high, `🔼` medium) only when the task text asks for them.
4. Report per field, in chat: how many rolled, how many moved to Done, which tasks were added. Flag any task that keeps getting rolled day after day, it is usually blocked or too big for a checkbox.

## Helper

Use dry-run first unless the operator explicitly asked to update files. From the prepared repository worktree or directory session, pass the vault root explicitly. Root discovery requires `_system/` and `To-Do/`, including when searching upward from a nested directory.

{{TOOL:codex}}
```bash
python3 .agents/skills/vault-todos/scripts/vault_todos.py --help
python3 .agents/skills/vault-todos/scripts/vault_todos.py --root "/absolute/path/to/vault" --fields self personal
python3 .agents/skills/vault-todos/scripts/vault_todos.py --root "/absolute/path/to/vault" --add "self: Review the draft" --apply
```
{{/TOOL}}
{{TOOL:claude}}
```bash
python3 .claude/skills/vault-todos/scripts/vault_todos.py --help
python3 .claude/skills/vault-todos/scripts/vault_todos.py --root "/absolute/path/to/vault" --fields self personal
python3 .claude/skills/vault-todos/scripts/vault_todos.py --root "/absolute/path/to/vault" --add "self: Review the draft" --apply
```
{{/TOOL}}
