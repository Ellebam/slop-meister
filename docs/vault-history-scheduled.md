# Scheduled vault history

[Vault history](vault-version-control.md) · [All documentation](README.md)

## Scheduled history

The installed [commit job](../plots/vault/bin/vault-commit.sh) runs at 08:00 and 20:00. It stages the vault, applies a deletion guard, logs a non-blocking lint result and writes a daily `git bundle --all` into `Backups/` beside the real vault folder, so a mirrored parent can carry the history while the vault holds nothing Git-shaped. Without separate storage or sync, this bundle remains on the same disk. The job replaces it only when the repository holds every commit the bundle ends on, so a rebuilt repository never overwrites a longer history.

The launchd file and the applet exist on the Mac only. On Linux `vault-commit.timer` runs the same job at the same hours, and `systemctl --user list-timers` shows its next run. On both platforms the bundle follows the configured real vault folder. Whether that parent folder is synchronized depends on the operator's sync configuration.

| File | Purpose |
|---|---|
| `~/.vault-git/bin/slopmeister-vault` | Stable launcher for direct Markdown access, named commits, lint, initialization, separate retros and explicit legacy-log recovery and optional bounded read-only Obsidian calls. |
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

## When the job stops

The job sends its existing failure messages during the same run. On Linux it uses `notify-send --urgency=critical` through the existing desktop notification service. The user's systemd session must have access to that desktop's session bus. On the Mac it keeps the existing `osascript` notification. `VAULT_NOTIFY=0` suppresses notifications for scratch runs. `SKIPPED`, `add failed`, `commit failed`, `bundle kept` and `bundle failed` still write their cause to the log.

`bin/slopmeister workstation doctor` reports `vault-history` as a problem when the bundle is missing or older than two days. The job writes the bundle once a day, at the end of a run that worked, so an old bundle means its runs fail. Read `~/.vault-git/vault-commit.log` for the cause. Git and the lock helper write their own message directly above the job's line.

| Log line | Fix |
|---|---|
| `NO ACCESS to the vault` | On the Mac, [give the applet access](vault-history-macos.md#give-the-applet-access). On Linux, check that the vault folder and its `_system/` folder exist and are readable. The notification's applet advice applies only to the Mac. |
| `SKIPPED, <n> deletions` | Inspect them with `task vault:status`. Restore the files, or commit intended deletions by name with `task vault:commit`. For deletions already committed on the other host and received by sync, use the check below. |
| `add failed`, `commit failed` | Read Git's message above the line. Remove a stale `~/.vault-git/obsidian.git/index.lock` once no Git process uses the repository. |
| `bundle kept` | The repository lacks history that the bundle holds. Move the repository aside, then [recover from the bundle](vault-version-control.md#recover-after-loss). When the bundle itself is damaged, Git's message above the line says so or `git bundle list-heads <bundle>` prints nothing. Move the bundle aside instead, and the next run writes a new one. |
| `bundle failed` | Read Git's message above the line. Check that `Backups/` beside the vault is writable. |
| `vault transaction busy` | Another vault commit held the lease. The next run retries. |
| `no repository`, `no vault lock helper` | Run the doctor and follow `vault-repository` or `home-install`. |
| No line at 08:00 or 20:00 | Follow `launchd:local.vault-commit` in the doctor, on Linux `vault-sweep`. |

When the other host already committed a cleanup, sync can deliver more deletions than this host's guard allows. Keep the guard enabled. Read the other host's committed tree with `vaultgit rev-parse HEAD` and `vaultgit ls-tree -r HEAD`. For each proposed deletion, confirm that the path is absent from that tree and deleted here. For any changed or new file included in the repair, compare its `git hash-object --no-filters -- <file>` result with the committed blob identifier. A local deletion list alone does not prove that the other host committed it. An old bundle may not contain the cleanup.

Leave mismatches and files another session is writing untouched. Refresh the comparison and this host's `vaultgit status --porcelain --untracked-files=all -- <path>...` immediately before the repair. Show the operator the exact vault-relative path list and command, then obtain the operator's order. Run `~/.vault-git/bin/slopmeister-vault commit "Record synced vault cleanup" -- <path>...` with only those checked paths. Never name a directory or sweep the vault. Check the resulting commit and named-path status. The next scheduled run should report `committed` or `nothing to commit` and write the daily bundle when it is due. Confirm both results in the log.
