# Install the chosen home entries

[All documentation](README.md) · [Global agent configuration](architecture.md#global-agent-configuration)

The workstation procedure follows this page at its home install step.

Run `task home:diff`. Read the current entry names in `slopmeister/workstation/manifest.py`. Prepare `task home:install -- <entry>...` with the common runtime entries and the chosen platform entries. Use explicit names so declined integrations stay off. Do not use the no-argument form or `--all` during selective onboarding. The installer backs up replacements.

The common install includes agent instructions, hooks, the Codex context setting, vault runtime and masked `op` runtime:

```bash
task home:install -- \
  .claude/CLAUDE.md .codex/AGENTS.md .codex/config.toml \
  .claude/skill-tracker-hook.sh .claude/skill-tracker-tool-hook.sh \
  .claude/statusline-command.sh .claude/notes-after-compaction.sh \
  .vault-git/bin/vaultgit .vault-git/bin/vault-lock.py \
  .vault-git/bin/slopmeister-vault .local/bin/slopmeister-vault \
  .local/bin/op .local/bin/slopmeister-prompt .codex/hooks.json \
  .local/lib/slopmeister-op/slopmeister/session/prompt_record.py \
  .local/lib/slopmeister-op/slopmeister/session/memory_guard.py \
  .local/lib/slopmeister-op/slopmeister/__init__.py \
  .local/lib/slopmeister-op/slopmeister/session/__init__.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_run.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_env.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_tier.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_approval.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_metadata.py \
  .local/lib/slopmeister-op/slopmeister/session/launch_identity.py \
  .vault-git/lib/slopmeister_vault/__init__.py \
  .vault-git/lib/slopmeister_vault/__main__.py \
  .vault-git/lib/slopmeister_vault/repository.py \
  .vault-git/lib/slopmeister_vault/environment.py \
  .vault-git/lib/slopmeister_vault/initialization.py \
  .vault-git/lib/slopmeister_vault/links.py \
  .vault-git/lib/slopmeister_vault/lint.py \
  .vault-git/lib/slopmeister_vault/conflicts.py \
  .vault-git/lib/slopmeister_vault/obsidian.py \
  .vault-git/lib/slopmeister_vault/retro_legacy.py \
  .vault-git/lib/slopmeister_vault/exclude
```

Add these groups only at their setup step through the same named-entry command. Paths are relative to the home directory.

| Group | Entries |
|---|---|
| History after initialization | `.vault-git/bin/vault-commit.sh`, `.vault-git/obsidian.git/info/exclude` |
| History on macOS | `.vault-git/VaultCommit.app`, `Library/LaunchAgents/local.vault-commit.plist` |
| History on Linux | `.config/systemd/user/vault-commit.service`, `.config/systemd/user/vault-commit.timer` |
| Drive on Linux, only when selected | `.local/bin/slopmeister-drive-sync`, `.config/systemd/user/drive-sync-vault.service`, `.config/systemd/user/drive-sync-vault.timer`, `.config/systemd/user/drive-sync-documents.service`, `.config/systemd/user/drive-sync-documents.timer` |
| Claude phone route on macOS | `Library/LaunchAgents/local.claude-remote-control.plist` |
| Claude phone route on Linux | `.config/systemd/user/claude-remote-control.service` |

With Drive declined, omit all five Drive entries and rclone. With the Claude phone route declined, omit its platform entry. The doctor checks configured services and keeps both choices optional. Keep configured but broken integrations visible and repair them. Do not remove installed integration files to make the doctor green. Initialize history before its installation group. Verify the first scheduled history bundle through the history document, including an explicitly authorized first run if needed.

Orca's managed settings are a separate choice. Follow `docs/orca.md` for the exact entry, hooks, repository registration and phone pairing. Open Orca on macOS for the installer to apply supported settings through its local runtime. Linux settings are applied in Orca's UI. Install other named entries while Orca remains open. Do not reload the phone service from a session that depends on it.

`task home:diff` reports pending changes and policy status. Never print live settings or saved approvals. On the operator's order, `task home:install -- .claude/settings.json .codex/rules/permissions.rules` applies central denials and ask-first rules with private backups. Installing `.claude/settings.json` or `.codex/config.toml` also disables that tool's memory. Name this effect before asking. Codex configuration is operator-owned except the top-level keys and `features.memories` of `plots/home/codex/config.toml.tmpl`. Existing allows, other settings and Codex's `default.rules` stay intact. Session-only allows stay in launched sessions. Global agent configuration in `docs/architecture.md` owns the boundaries.

The vault is the only memory. The doctor's `home-install` result flags switch drift in normal homes. Its memory results check populated stores, active relocated roots and Orca's separate Codex runtime home without exposing memory text. Switches in active relocated Claude homes and secondary Codex homes must be explicitly false. Unreadable input is `unknown`. Orca mirrors normal Codex configuration but can retain runtime edits or stall, so verify its copy. Finish any ordered migration before requesting switch-off or store removal. Never delete a store to make the doctor pass.

Codex memory can generate private `SKILL.md` procedures linked from `MEMORY.md`. Slopmeister's delivered skills, listed in `docs/skills.md`, come from this repository. Disabling private memory preserves delivered skills and built-in tools.

Codex initializes its v1 database even with memory off. The doctor checks saved outputs, jobs and consolidation progress in a bounded private snapshot, including committed WAL data. Initialization rows alone are empty state. Live files stay unchanged. A changing or unreadable database is `unknown`.

## Optional weekly sessions

Both jobs require a working local Slopmeister launch, a declared plot and your selected repository. A recap uses the plot’s vault, session census and available forge reads. A dependency update uses Claude and the project’s documented update and test commands. Each launch consumes model usage. Review the [glean procedure](../src/skills/glean/SKILL.md) and [dependency update instructions](weekly-sessions.md#weekly-dependency-updates) first.

On macOS, create `~/.config/slopmeister/glean.json` for a recap or `~/.config/slopmeister/weekly.json` for dependency updates. Set the file mode to `0600`. Use absolute paths to your trusted Slopmeister checkout and target repository. For example, replace the sample paths and plot below with your own.

```json
{"checkout":"/Users/demo/dev/slop-meister","repository":"/Users/demo/dev/shop","plot":"example-app"}
```

Review the proposed changes with `task home:diff`. Install the helper and only the job you selected.

```sh
task home:install -- .local/bin/slopmeister-weekly Library/LaunchAgents/local.glean.plist
```

For updates, select `Library/LaunchAgents/local.weekly.plist` instead. The recap starts Sunday at 20:30 local time and updates Monday at 08:00. Both use a dated session name. Remove your chosen JSON file to pause future launches. A missing file starts nothing. Linux installs neither timer. To run once on either platform, use the commands in the [launcher guide](weekly-sessions.md#weekly-dependency-updates).
