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

The command commits only those literal paths, preserving another session's staged files. It refuses a named directory, which would commit every changed note inside it. It commits the whole named file, so close-out checks first-touch cleanliness and the last-write digest before including a path. Earlier foreign or unknown changes exclude that note from automatic commits and consolidation. It prints the commit stat. A failed add or commit returns nonzero, names the failed phase and paths, and leaves the Markdown and Git index dirty for inspection and recovery. `task vault:commit` is the repository convenience form; installed `slopmeister-vault commit` is the same contract from any worktree or directory session. A session commits its recorded paths when it hands back finished work, not only at finalize, so the delivered session settings allow `slopmeister-vault commit` without an approval question. That exception covers the `commit` subcommand under that exact name on `PATH`, nothing else.

| Exit | Meaning |
|---|---|
| `0` | Named changes committed. |
| `1` | Nothing to commit, a helper is missing or Git failed. |
| `2` | Missing message, paths or `--` separator. |
| `75` | The commit lease is busy. |

Manual named commits, the scheduled sweep and the one shared retro transaction use `~/.vault-git/obsidian.git/slopmeister-coordination/commit.lock`. The operating system owns that short lease and releases it on process exit or crash. Ordinary transactions hold it only for validation, staging and commit. Retro holds it across materialization, read, replay, append, verification and named commit so simultaneous close-outs cannot lose bytes. Ordinary vault reading and editing remain outside it. A busy manual transaction refuses immediately. The scheduled job skips that run.

Status and log tasks use `~/.vault-git/bin/vaultgit`. `slopmeister-vault lint` prints vault-wide counts. Add `--area <vault-relative folder>` to resolve that folder's wikilinks and relative Markdown links against the vault. Local and cross-note heading fragments must resolve by decoded heading text or ordinary Markdown slug. Unsupported block references and nested heading paths are reported. Frontmatter `status: published` marks a live-page-owned mirror. Its unresolved `protected links` do not fail area lint but remain in vault-wide counts. Add `--shallow` to leave the folder's subfolders out, which close-out uses for a field folder whose project and ticket folders are areas of their own. Plots requiring [groom](../src/skills/groom/SKILL.md) maintain content before review or handback, then close-out verifies it without repairs. Other plots run area lint before and after close-out housekeeping. `SLOPMEISTER_VAULT` points the command at another vault, which is how `tests/integration/vault/test_lint.py` uses a disposable one.

`slopmeister-vault retro` is the narrow automatic-consolidation exception for the shared append-only retro log. It appends and verifies the regular Markdown file directly under the existing lease, commits only that named note and removes replayed spills only after the committed blob contains their entries. A `dataless` placeholder note is refused, never read as empty. When append succeeds but consolidation fails, the Markdown remains dirty and the existing spill queue retains the entry; stderr names both the note to inspect and the spill. Ordinary notes keep the manual named-commit rule above.

Quoted Markdown link titles are excluded from destination lookup. Area lint reads locally available regular Markdown files and never follows note symlinks; confirm the dataless check above prints nothing before treating zero as complete coverage. Zero lint counts still require a separate check that retained notes remain reachable through the area's navigation.

## Scheduled history

The installed [commit job](../plots/vault/bin/vault-commit.sh) runs at 08:00 and 20:00. It stages the vault, applies a deletion guard, logs a non-blocking lint result and writes a daily `git bundle --all` into `Backups/` beside the real vault folder, so a mirrored parent can carry the history while the vault holds nothing Git-shaped. Without separate storage or sync, this bundle remains on the same disk. The job replaces it only when the repository holds every commit the bundle ends on, so a rebuilt repository never overwrites a longer history.

The launchd file and the applet exist on the Mac only. On Linux `vault-commit.timer` runs the same job at the same hours, and `systemctl --user list-timers` shows its next run. Its bundle lands beside the vault folder, outside every synced folder, so only the Mac's bundle reaches Drive.

| File | Purpose |
|---|---|
| `~/.vault-git/bin/slopmeister-vault` | Stable launcher for direct Markdown access, named commits, lint, initialization, consolidated retro append and optional bounded read-only Obsidian calls. |
| `~/.vault-git/lib/slopmeister_vault/` | Exact reviewed standard-library runtime copied by the workstation installer. |
| `~/.vault-git/bin/vaultgit` | Raw Git recovery wrapper with its work tree at `~/.slopmeister/vault`. |
| `~/.vault-git/bin/vault-commit.sh` | Installed job script. |
| `~/.vault-git/bin/vault-lock.py` | Shared process-owned commit lease. |
| `~/Library/LaunchAgents/local.vault-commit.plist` | Launchd job, label `local.vault-commit`, from the [template](../plots/home/launchd/local.vault-commit.plist.tmpl). |
| `~/.vault-git/VaultCommit.app` | Applet through which launchd runs the script. |
| `~/.vault-git/vault-commit.log` | Job log, including the messages of Git and the lock helper. |
| `~/.vault-git/launchd.out`, `~/.vault-git/launchd.err` | Launchd output. |
| `My Drive/Backups/vault-history.bundle` | Recovery bundle, in the folder that holds the real vault. |

> [!WARNING]
> The scheduled job refuses a commit deleting more than 25 files or 5 percent of tracked files. Check the log and the vault before treating a large deletion as intentional.

## Merge a conflict copy

`task vault:lint` counts conflict copies and prints the merge steps. The base is a committed version of the note from before the edits of both files, taken from the history of the machine that merges. `git merge-file <note> <base> <copy>` then joins both edits and marks only those that overlap. A base that already holds one side's edit makes the merge revert that edit without a mark. When unsure take an older version, which only marks more overlaps. For the append-only retro log add `--union`, both machines append at the end and every entry stays. Then remove the copy and commit by name.

## When the job stops

`bin/slopmeister workstation doctor` reports `vault-history` as a problem when the bundle is missing or older than two days. The job writes the bundle once a day, at the end of a run that worked, so an old bundle means its runs fail. Read `~/.vault-git/vault-commit.log` for the cause. Git and the lock helper write their own message directly above the job's line.

| Log line | Fix |
|---|---|
| `NO ACCESS to the vault` | [Give the applet access](#give-the-applet-access). |
| `SKIPPED, <n> deletions` | Inspect them with `task vault:status`. Restore the files, or commit intended deletions by name with `task vault:commit`. |
| `add failed`, `commit failed` | Read Git's message above the line. Remove a stale `~/.vault-git/obsidian.git/index.lock` once no Git process uses the repository. |
| `bundle kept` | The repository lacks history that the bundle holds. Move the repository aside, then [recover from the bundle](#recover-after-loss). When the bundle itself is damaged, Git's message above the line says so or `git bundle list-heads <bundle>` prints nothing. Move the bundle aside instead, and the next run writes a new one. |
| `bundle failed` | Read Git's message above the line. Check that `Backups/` beside the vault is writable. |
| `vault transaction busy` | Another vault commit held the lease. The next run retries. |
| `no repository`, `no vault lock helper` | Run the doctor and follow `vault-repository` or `home-install`. |
| No line at 08:00 or 20:00 | Follow `launchd:local.vault-commit` in the doctor, on Linux `vault-sweep`. |

## Give the applet access

macOS file-access consent belongs to the applet. If the job cannot list the vault it logs `NO ACCESS` and stops, rather than reporting an empty tree as a successful run.

1. Run the named history installs above when installation is intended. Installing the changed launchd entry reloads that job.
2. If the applet is missing, the install builds it, `task home:install -- .vault-git/VaultCommit.app` builds it alone.
3. Allow the first-run consent dialog. If dismissed, add `VaultCommit.app` under System Settings → Privacy and Security → Full Disk Access.

Inspect the job without running it:

```bash
launchctl print "gui/$(id -u)/local.vault-commit"
```

To request an immediate scheduled commit:

```bash
launchctl kickstart "gui/$(id -u)/local.vault-commit"
```

The [installer](../slopmeister/workstation/install.py) leaves an existing applet untouched because rebuilding changes its identity and revokes its consent. A failed build is reported while the rest of installation continues. The manual build command is:

```bash
osacompile -o ~/.vault-git/VaultCommit.app \
  -e 'do shell script "/bin/bash " & quoted form of (POSIX path of (path to home folder)) & ".vault-git/bin/vault-commit.sh"'
```

## Recover after loss

With a surviving bundle:

```text
task vault:init -- --from-bundle <bundle>
```

Then install the [history entries](#enable-history-before-editing). Without a bundle, `task vault:init` creates a fresh baseline. The package initializer requires `_system/` in the vault and refuses a vault containing `.git`.

It returns untouched while any `~/.vault-git/obsidian.git` directory exists. A corrupt remnant must therefore be handled explicitly before rebuilding. Preserve it for diagnosis before deciding to remove it.
