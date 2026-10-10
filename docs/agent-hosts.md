# Agent machines

Slopmeister supports agent workstations on macOS and Ubuntu. One workstation is enough. The optional Home Assistant, broker and Grove layer needs Linux, and its pinned Grove binary is x86-64. Each machine owns the sessions it runs. The installer and doctor implement the platform-specific parts of this contract.

[Overview](../README.md) · [All documentation](README.md)

## The contract

`bin/slopmeister workstation doctor` checks local prerequisites without changing them. Logins, phone pairing and real approval delivery need separate operator checks.

| Behaviour | Why |
|---|---|
| Claude Code and Codex are installed and signed in | Each plot can use either tool. |
| `jq` is installed | The common Claude hooks use it for skill tracking and the status line. |
| The home installation matches the reviewed Slopmeister checkout | Machines share configuration sources without sharing live sessions. |
| The launcher opens workers and the dispatcher in the local Orca runtime | One path delivers fixed configuration, kickoff evidence and issue claims. |
| Active agents are protected from idle sleep | Sleep interrupts running workers. |
| Configured phone routes recover after their process exits | Remote access should not depend on one live terminal. |
| Secret requests follow the configured approval route | The operator sees the exact references and command before release. |
| The vault is available as local files | Reading a cloud placeholder does not prove that a note is empty. |
| Vault history is initialized before agents edit notes | A local edit remains recoverable. Read-only onboarding can use a plain vault. |
| Configured Linux Drive sync refuses excessive deletions | A mistaken deletion must not spread unchecked. Sync is optional. |

Google Drive for desktop has no deletion limit. The Linux sync guard cannot prevent a deletion already accepted by another client. Phone pairing appears only on the phone, and checking the 1Password unlock state can raise the prompt being tested.

## Ownership

The operator owns the operating system, hardening, desktop login, tailnet enrollment and packages that need root. The [workstation skill](../src/skills/workstation/SKILL.md) owns supported user-level tooling and diagnosis. `task home:install` installs Slopmeister's user configuration. With no entry names it installs all entries, including optional jobs. The workstation procedure selects the entries for the requested setup. A second provisioning system must not duplicate that installer or its drift checks.

Home installation refuses symbolic links at selected destinations or their parents below the selected home. It also checks backup destinations that the install will write. The complete selection is checked before any file changes. Diff and drift report these links as unsafe even when their content matches. Resolve them deliberately before retrying. Unselected links do not block unrelated named installs.

The operator performs all account logins and installs credentials. Provisioning must preserve the separation between the agent account, approval-service credentials and root-owned service code. Root and Docker administration can bypass ordinary file permissions, so those permissions do not isolate a hostile administrator.

## Vault storage and history

A plain local vault passes the vault checks without Git history, rclone or Drive. Initialize [vault history](vault-version-control.md#enable-history-before-editing) before an agent changes notes. Drive sync is optional and encouraged for a copy on another machine. The supported sync setup uses Google Drive for desktop on macOS and `rclone bisync` on Linux. Both expose the vault at `~/.slopmeister/vault`. The Mac mirrors My Drive because shared drives remain streamed. Linux keeps rclone's login in its own protected file so scheduled sync does not depend on an unlocked password-manager app. [Document access](drive-access.md#sync-on-linux) owns the setup.

Each machine keeps independent Git history outside the synced vault. Histories never merge. Syncing a bare repository would permit concurrent metadata writes, while merging a shared history could alter notes during file synchronization. The Mac's history bundle can travel with Drive without putting Git metadata in the vault. [Vault version control](vault-version-control.md) owns commits, bundles, conflict recovery and lint.

## Remote sessions

Orca runs on each machine and owns the sessions executed there. A dispatcher may launch and inspect a configured remote host through SSH. Session state does not move between dispatchers. The operator's request and plot context select the executing machine. A backlog request without a plot uses only the dispatcher's configured plot.

[Remote dispatch](remote-dispatch.md) owns access, launch, status and recovery. [Phone access](phone-access.md) and [Orca](orca.md) own the two phone routes. Keep actual host names, keys, addresses and account details in local configuration and the owning context.

The Claude phone route is optional. Its installed launchd or systemd entry enables its doctor checks, including a broken entry that needs repair. An absent entry is not required by the home-install check. Repairs name only missing or changed required entries, so they do not enable declined integrations. On Linux, any configured history timer, Drive timer or phone route retains the lingering check.

## Secret approval service

The [host guide](../host/README.md) owns deployment, service-account bootstrap, credentials and Tailscale Serve. The approval broker runs on Linux under its own service account. Root owns its installed code. The operator enters its protected bootstrap credentials outside the agent's readable configuration. The Mac can approve requests and reach that broker through its dedicated SSH route without holding broker credentials.

[Secret requests](1password-access.md) owns `op run`, delivery, trust limits and the operator-ordered desktop fallback when the broker is unreachable. Selected service actions retain their separate native approval and credential route.

## Grove

Grove serves Bloom pages from a Linux agent host through private tailnet HTTPS on port 8443. Slopmeister owns the visual skill, worktree publication choice, client and shared receive/cleanup code. The host runs the confined Caddy reader, protected runtime and cleanup timer.

A plot declares `[target] bloom = "tailnet"` to permit publication. The default is `local`. The publisher reads the page's owning worktree state, even when another session invokes it. Prepared worktrees keep their saved choice until a fresh preparation.

The installed `/usr/local/bin/grove receive` accepts bounded UTF-8 HTML on stdin and prints one HTTPS URL with a random 128-bit filename. Both platform clients use this intake, so naming and retention have one owner. Linux calls it locally. Mac calls it through the pinned SSH route in `~/.ssh/slopmeister-remote.conf`. Mac settings at `~/.config/slopmeister/grove.json` name the explicit SSH alias as `host` and the expected HTTPS origin as `base_url`. The host's root-owned `/etc/slopmeister/grove.json` names `directory` and `base_url`.

The [host guide](../host/README.md#grove-operation-and-recovery) owns the confined server, reviewed runtime installation, timer, HTTPS route and live checks. It preserves Home Assistant and unrelated routes.

`grove cleanup` removes pages older than seven days, then the oldest pages until managed HTML totals at most 64 MiB. This bounds page bytes, not all disk use. Publication cleans under the same lock. The hourly timer runs as the page owner. Interrupted-copy files are removed under the lock. Unsupported entries stay untouched and cause a diagnostic after ordinary cleanup. Publication refuses that state and returns the local path. Run `/usr/local/bin/grove cleanup` on the host to diagnose it, then resolve only entries you own. The worktree copy stays ignored and uncommitted. Unavailable hosting preserves it and reports the cause.
