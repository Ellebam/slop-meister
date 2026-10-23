# Save and recover vault notes

The Markdown notes are ordinary local files. Drive sync is optional. Obsidian is the preferred editor, but correctness and history do not depend on it. Their Git repository stays outside the vault, at `~/.vault-git/obsidian.git`.

[Overview](../README.md) · [All documentation](README.md) · [Context and ownership](context-layer.md)

> [!IMPORTANT]
> Keep Git metadata out of the vault, including `.git`, `.gitignore` and gitfiles. The `vaultgit` wrapper supplies the external Git directory and vault work tree. Excludes come from the installed [runtime source](../slopmeister/vault/runtime/exclude).

## Where the vault lives

Every tool finds the vault at `~/.slopmeister/vault`. `SLOPMEISTER_VAULT` overrides it for a command or session, and the doctor's `--vault` selects a read-only inspection target. A local directory or a link to one is valid. All notes must be readable locally.

For a first read-only check from the checkout:

```bash
bin/slopmeister workstation doctor --vault examples/vault
```

Inspect the returned `vault` and `vault-local` rows. An overall exit zero is not an assertion that every unrelated tool or login is ready. On a fresh machine this check requires neither Drive nor vault Git history. Once a history repository or commit job exists, the doctor also checks history. Installed Linux sync commands or units enable the Drive checks, including rclone. Partial or broken configured integrations remain errors.

Use the [workstation procedure](../src/skills/workstation/SKILL.md) to copy the example into a new local vault without replacing an existing one. Before agents edit that vault, enable history below. For optional mirroring and cloud-backed recovery, follow [Drive setup](drive-access.md).

On macOS, `find ~/.slopmeister/vault/ -flags +dataless` must print nothing. The trailing slash enters a symlink. On either platform the doctor's `vault-local` row checks local readability. If using Obsidian's optional CLI, pass the vault name registered in that app.

To move the vault, copy it and repeat `rsync -a --checksum --dry-run --itemize-changes <old>/ <new>/` until it prints nothing. Update the local path only while no prepared session is active or paused. Prepared sessions keep their old fixed grants, so resume through a fresh preparation after the move.

## Enable history before editing

Configure your Git name and email, then run `task vault:init`. It commits the initial notes into `~/.vault-git/obsidian.git` and leaves the vault free of Git metadata. For an existing history, use [recovery](#recover-after-loss) instead. The installed runtime and wrappers come from workstation setup.

Install the shared history entries after initialization:

```bash
task home:install -- .vault-git/bin/vault-commit.sh .vault-git/obsidian.git/info/exclude
```

On macOS, install `.vault-git/VaultCommit.app` and `Library/LaunchAgents/local.vault-commit.plist` through the same named-entry command, then complete [applet consent](#give-the-applet-access). On Ubuntu:

```bash
task home:install -- .config/systemd/user/vault-commit.service .config/systemd/user/vault-commit.timer
systemctl --user start vault-commit.service
```

The job creates the first recovery bundle. On macOS, use the immediate-job command below after consent. Check the log and `vault-history` result before treating backup as ready. A fresh baseline protects subsequent edits, but it cannot restore history from before initialization.

## Everyday commands

```bash
task vault:status
task vault:log
task vault:lint
```

Optional Obsidian index queries use the installed read-only boundary:

```text
slopmeister-vault obsidian -- vault=<registered-name> search query='<keywords>'
```

It accepts only read-only search, link, property, orphan, tag and open operations, terminates their process group on timeout and never retries. Exact reads, writes, lint and commits use the Markdown filesystem directly.

To commit work, name the exact vault-relative paths:

```text
task vault:commit -- "One line message" -- <vault-relative path>...
```

The command commits only those literal paths, preserving another session's staged files. It refuses a named directory, which would commit every changed note inside it. It commits the whole named file, so session maintenance checks first-touch cleanliness and the last-write digest before including a path. Earlier foreign or unknown changes exclude that note from automatic commits and consolidation. It prints the commit stat. A failed add or commit returns nonzero, names the failed phase and paths, and leaves the Markdown and Git index dirty for inspection and recovery. `task vault:commit` is the repository convenience form; installed `slopmeister-vault commit` is the same contract from any worktree or directory session. A session commits its recorded paths when it hands back finished work, not only at harvest or finalize, so the delivered session settings allow `slopmeister-vault commit` without an approval question. That exception covers the `commit` subcommand under that exact name on `PATH`, nothing else.

| Exit | Meaning |
|---|---|
| `0` | Named changes committed. |
| `1` | Nothing to commit, a helper is missing or Git failed. |
| `2` | Missing message, paths or `--` separator. |
| `75` | The commit lease is busy. |

Manual named commits, the scheduled sweep and retro commits share `~/.vault-git/obsidian.git/slopmeister-coordination/commit.lock`. The holder keeps the lock until its owned writer processes stop, including cancellation and the default 300-second execution deadline. A timeout returns `124`; cancellation reports a nonzero status. Inspect partial writes before retrying. Ordinary reading and editing stay outside the lock. Busy manual commits refuse immediately, the scheduled job skips that run, and a new retro waits up to 60 seconds for its named commit. Explicit legacy append holds the lock across read, replay, append and commit.

Status and log tasks use `~/.vault-git/bin/vaultgit`. `slopmeister-vault lint` prints vault-wide counts. Add `--area <vault-relative folder>` to resolve that folder's wikilinks and relative Markdown links against the vault. Local and cross-note heading fragments must resolve by decoded heading text or ordinary Markdown slug. Unsupported block references and nested heading paths are reported. Frontmatter `status: published` marks a live-page-owned mirror. Its unresolved `protected links` do not fail area lint but remain in vault-wide counts. Add `--shallow` to leave the folder's subfolders out, which close-out uses for a field folder whose project and ticket folders are areas of their own. Plots requiring [groom](../src/skills/groom/SKILL.md) maintain content before review or handback, then finalize and close-out verify it without repairs. Direct harvest can finish authorized routine document gaps through groom. Run area lint after maintenance and retain protected findings. `SLOPMEISTER_VAULT` points the command at another vault, which is how `tests/integration/vault/test_lint.py` uses a disposable one.

### Session retros and legacy logs

Without `--note`, `slopmeister-vault retro` creates a separate UTF-8 note under `_system/retros/` with private file permissions and a unique filename. It commits only that file. Concurrent sessions do not append to the same note. Harvest uses the session name and checks for an existing entry before retrying. If the commit fails, keep the returned path and recover with an ordinary named commit. Do not run retro again merely to recover that file.

`slopmeister-vault retro-count` prints normalized repository names and counts from the new collection. URLs, owner/name forms and worktree paths normalize to the repository name. It excludes index notes, conflict copies and numbered duplicates whose base file exists. Historical log entries are not included.

Explicit `--note _system/retro-log.md` retains the legacy append, deduplication and spill-replay behavior used by close-out. A custom note requires its own `RETRO_SPILL_DIR`. `RETRO_FORBID_NOTE` still refuses the named target. Failed legacy consolidation retains the Markdown and spill; successful replay deletes a spill only after Git contains its entry. Default new-note calls report pending legacy spills but do not replay or migrate them. Recover that queue with an explicitly selected original note and spill directory. A dataless legacy note is refused, never treated as empty.

### Runtime overrides

`SLOPMEISTER_VAULT`, `VAULT_GIT_DIR`, `VAULT_LOCK`, `VAULTGIT` and `SLOPMEISTER_VAULT_LAUNCHER` remain supported. The runtime resolves the selected paths before lock re-entry and preserves them. XDG state selection and the legacy spill overrides remain available. Child commands discard Python and Git startup injection variables while retaining the selected public paths and Git author identity. The installed launcher uses isolated Python and suppresses shell startup injection. No command installs or migrates a vault automatically.

Quoted Markdown link titles are excluded from destination lookup. Area lint reads locally available regular Markdown files and never follows note symlinks; confirm the dataless check above prints nothing before treating zero as complete coverage. Zero lint counts still require a separate check that retained notes remain reachable through the area's navigation.

## Scheduled history

See [the schedule, installed files and failure recovery](vault-history-scheduled.md).

## Merge a conflict copy

`task vault:lint` counts conflict copies and prints the merge steps. The base is a committed version of the note from before the edits of both files, taken from the history of the machine that merges. `git merge-file <note> <base> <copy>` then joins both edits and marks only those that overlap. A base that already holds one side's edit makes the merge revert that edit without a mark. When unsure take an older version, which only marks more overlaps. For the append-only retro log add `--union`, both machines append at the end and every entry stays. Then remove the copy and commit by name. Lint also reports numbered copy candidates such as `note (1).md` when `note.md` exists. Compare them and keep both until reviewed; a matching filename is not deletion authority.

## When the job stops

Use the [job diagnostics](vault-history-scheduled.md#when-the-job-stops) before retrying.

## Give the applet access

Follow [macOS applet consent](vault-history-macos.md#give-the-applet-access).

## Recover after loss

With a surviving bundle:

```text
task vault:init -- --from-bundle <bundle>
```

Then install the [history entries](#enable-history-before-editing). Without a bundle, `task vault:init` creates a fresh baseline. The package initializer requires `_system/` in the vault and refuses a vault containing `.git`.

It returns untouched while any `~/.vault-git/obsidian.git` directory exists. A corrupt remnant must therefore be handled explicitly before rebuilding. Preserve it for diagnosis before deciding to remove it.
