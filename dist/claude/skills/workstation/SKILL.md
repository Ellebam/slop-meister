---
description: "Set up this Mac or Linux machine, diagnose a failed launch, agent CLI, Orca, login or system permission, and keep Claude Code, Codex, Orca and the installed tools current. Use it whenever one of those fails, when the operator says onboard me or set up this machine, and after an update."
---

# Workstation

Use this procedure from clone to dispatcher, or enter at Check for an existing installation. Both agent subscriptions and Orca are required. macOS and Ubuntu support the clients. Home Assistant approvals, the broker and Grove need Linux. Keep machine facts and credentials outside this public checkout.

Run repository commands from `~/dev/slop-meister`. Resolve document paths below from that checkout, not from the source, symlink or copied skill directory. Reuse an existing checkout instead of cloning over it. Confirm the machine, vault location, optional Drive sync and access to a Linux approval host. Google Drive is encouraged but optional. Use existing authorization. Before a home install, vault initialization, update or deployment without that authorization, show the exact targets and effects and obtain the operator's approval. Linux packages requiring root belong to the operator. Never run `sudo` there. Logins, device pairing and privacy consent also belong to the operator.

## Prepare the tools

On macOS, the operator installs [Homebrew](https://brew.sh), the 1Password desktop app, Tailscale and [Orca](https://onorca.dev). With setup authorized, install the command-line prerequisites:

```bash
brew install git go-task uv gh glab ripgrep python@3.14 shellcheck jq
brew install --cask 1password-cli
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

On Ubuntu, have the operator install Git, `gh`, `glab`, ripgrep, zsh, lsof, shellcheck, jq, curl, OpenSSL, Python 3.14 with venv support, the 1Password app and CLI, Tailscale and Orca's package. Ensure `python3` is at least 3.14 and `/usr/bin/systemd-inhibit` is present. Orca's executable is `/usr/bin/orca-ide`, not the GNOME screen reader `/usr/bin/orca`. The platform contract is in `docs/agent-hosts.md`. Install the user-level tools after setup is authorized:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
sh -c "$(curl -fsSL https://taskfile.dev/install.sh)" -- -d -b ~/.local/bin
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Merge `export PATH="$HOME/.local/bin:$PATH"` into `~/.zshenv` once, preserving its other settings. The launcher uses a zsh login shell even when the account uses another shell. On macOS, also put `$(brew --prefix python@3.14)/libexec/bin` on that path so `python3` selects the supported interpreter. Verify `python3 --version`, `task --version`, `uv --version`, `~/.local/bin/claude --version` and `~/.local/bin/codex --version` from a fresh terminal. Resolve a Python version failure before running Slopmeister.

The operator signs in through `claude auth login`, `~/.local/bin/codex login` and `gh auth login` in their own terminal. Complete the tools' workspace trust prompts. GitLab users follow `docs/gitlab.md`: prepare `~/.config/slopmeister/glab.env` with their two reference variables and mode `0600`, then use `task glab:login` through the authorized secret route. Inspect existing Git identity, then have the operator choose their name and email if absent. Do not copy another user's identity, create login fixtures or report an untested login as working.

## Clone and check

For a new checkout:

```bash
git clone https://github.com/Ellebam/slop-meister.git ~/dev/slop-meister
cd ~/dev/slop-meister
task tools
bin/slopmeister render --check
```

`task tools` creates the locked development environment. The committed renders supply both tools' instructions and skills. Start `claude` or `codex` here and say "onboard me". Invoke `/workstation` or `$workstation` if discovery did not select this skill.

For an existing installation, run the checks below first and repair the reported gaps instead of repeating setup.

## Prepare the vault

Use an existing local Markdown vault, or copy `examples/vault/` to an absent destination outside the checkout. Never overwrite an existing vault. Use `~/.slopmeister/vault` as the directory or as a link to the real folder. `SLOPMEISTER_VAULT` selects another location. If Drive is selected, follow `docs/drive-access.md` and complete the first mirror or sync before initializing history. On Linux this needs rclone 1.74.2 or newer, installed by the operator from [rclone's packages](https://rclone.org/downloads/).

Run `bin/slopmeister workstation doctor --vault <absolute-vault>`. A plain vault needs `_system/`, Markdown notes and readable local content. It does not need Drive or history to be inspected. Before tailoring notes or allowing agent note edits, obtain the intended initialization authority and run `task vault:init -- <absolute-vault>`. This creates the external history. Keep Git metadata out of the vault. Follow `docs/vault-version-control.md` for initialization, scheduled backup, first-run consent and recovery. After initialization, tailor the context and document conventions in the vault, not in this repository.

## Install the chosen home entries

Run `task home:diff`. Read the current entry names in `slopmeister/workstation/manifest.py`. Prepare `task home:install -- <entry>...` with the common runtime entries and the chosen platform entries. Use explicit names so declined integrations stay off. Do not use the no-argument form or `--all` during selective onboarding. The installer backs up replacements.

The common install includes agent instructions, hooks, the Codex context setting, vault runtime and masked `op` runtime:

```bash
task home:install -- \
  .claude/CLAUDE.md .codex/AGENTS.md .codex/config.toml \
  .claude/skill-tracker-hook.sh .claude/skill-tracker-tool-hook.sh \
  .claude/statusline-command.sh \
  .vault-git/bin/vaultgit .vault-git/bin/vault-lock.py \
  .vault-git/bin/slopmeister-vault .local/bin/slopmeister-vault \
  .local/bin/op \
  .local/lib/slopmeister-op/slopmeister/__init__.py \
  .local/lib/slopmeister-op/slopmeister/session/__init__.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_run.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_env.py \
  .local/lib/slopmeister-op/slopmeister/session/secret_transport.py \
  .local/lib/slopmeister-op/slopmeister/session/remote_ssh.py \
  .vault-git/lib/slopmeister_vault/__init__.py \
  .vault-git/lib/slopmeister_vault/__main__.py \
  .vault-git/lib/slopmeister_vault/repository.py \
  .vault-git/lib/slopmeister_vault/lint.py \
  .vault-git/lib/slopmeister_vault/conflicts.py \
  .vault-git/lib/slopmeister_vault/obsidian.py \
  .vault-git/lib/slopmeister_vault/retro.py \
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

Orca's managed settings are a separate choice. Follow `docs/orca.md` for the exact entry, hooks, repository registration and phone pairing. Installing its macOS settings requires Orca closed, which ends its sessions. Arrange that install from outside Orca. Linux settings are applied in Orca's UI. Install other named entries while Orca remains open. Do not reload the phone service from a session that depends on it.

The live allow rules in `~/.claude/settings.json` and `~/.codex/rules/default.rules` belong to the operator. Report missing rules from the templates under `plots/home/` and have the operator apply them. Never print their whole live files. Preserve `~/.codex/config.toml` except the installer's managed context setting.

## Secrets and optional Linux services

Recommend Home Assistant approval when a Linux host and a 1Password service account are available. Follow `host/README.md` for the optional Ansible tools, private inventory/settings, reviewed deployments, separate broker identity, root-owned code and operator-only token bootstrap. The operator enrolls the machines and phone in Tailscale, enables MagicDNS and HTTPS certificates, and merges the example's narrow policy grants. Preserve unrelated routes. The host guide owns deployment commands and verification.

Both secret routes are described in `docs/1password-access.md`. In launched sessions, masked `op run --env-file=<file> -- <command>` requests Home Assistant approval. The broker needs read access to the selected custom 1Password vaults. Tokens never enter the checkout, chat or agent-readable files. Complete the guide's real Approve, Deny and expiry checks with the operator.

The existing desktop integration is the second route, including a workstation without the optional broker. The operator unlocks 1Password and enables CLI integration in Settings, Developer. Linux also needs system authentication and a running PolKit agent, as [1Password's app integration guide](https://www.1password.dev/cli/app-integration) explains. When the broker is unreachable, only the operator can authorize the real 1Password binary for one exact command. Follow `docs/1password.md` and the documented fallback. Do not introduce a route setting, clear the launcher marker or silently bypass the broker. Selected service actions retain their separate native approval and private-profile setup. See `docs/service-actions.md`.

Grove is optional Linux hosting for Bloom pages. Follow `host/README.md` and the Grove section of `docs/agent-hosts.md`. Enable publication only for plots with the intended permission. Follow `docs/remote-dispatch.md` for the dedicated SSH route from a macOS client to the Linux services. Keep host aliases and access facts in private settings and the vault.

## Phone access and dispatch

Choose either or both phone routes in `docs/phone-access.md`. The Claude app uses the named phone-service entry above, after interactive Remote Control consent. Orca Mobile uses the pairing steps in Orca setup, with Relay and the optional faster tailnet path. Verify the phone away from Wi-Fi and record what remains unproven. Desktop login is still needed for Orca on either system.

Open Orca and add `~/dev/slop-meister` as a repository through its UI. Create `~/.slopmeister/sessions/` if absent and register it as a folder, as the Orca guide requires for directory sessions. Run Check and resolve launcher requirements before starting a dispatcher. A pending optional device check is not a verified feature. From an Orca terminal in the checkout:

```bash
task dispatch -- claude slopmeister-dispatcher
```

Use `codex` instead of `claude` for a Codex dispatcher. From another terminal or the Claude phone session, use `task dispatch -- --open claude slopmeister-dispatcher`. Confirm the dispatcher starts in the intended Orca workspace and answers a read-only request. Issue dispatch needs a separate operator request. `docs/session-walkthrough.md` explains the subsequent worker, testing and finalize steps. To add a real plot from the neutral examples, follow Onboard a project in `docs/context-layer.md`.

## Check and repair

Run `bin/slopmeister workstation doctor`, `codex doctor --json` and `claude doctor`. For a failed Codex launch, run its doctor in the affected workspace. Slopmeister reports `name`, `status`, `evidence` and `fix`. Explain each non-`ok` result with its evidence. `unknown` means the check could not answer. Do not manufacture account state to clear a result. Rechecking and `task tools` need no additional permission.

If the doctor errors or contradicts observed behavior, read `slopmeister/workstation/doctor.py`, repeat its reads and diagnose the actual error. Propose the smallest corrected check or owning-document repair. After any fix, rerun the checks and report changed results and remaining operator checks.

## Updates

Updates arrive by pulling this repository and reinstalling the selected entries. On a clean checkout, inspect incoming changes, obtain any missing update authority, use `git pull --ff-only`, run `task tools`, check renders and inspect `task home:diff`. Reinstall only the intended names, preserving optional choices.

Check `brew outdated --json` on macOS or `apt list --upgradable` on Ubuntu, plus Codex's `updates.status` and Claude's update report. Update only named tools with their updater: `brew upgrade <formula>`, `codex update` or `claude update`. Linux system-package updates belong to the operator. Orca and other desktop apps use their own updater. A failed launch after an update returns to Check. OpenCode remains an optional client, see `docs/opencode.md`.
