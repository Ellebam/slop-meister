# Phone access on macOS and Ubuntu

Both phone routes require the operator's signed-in apps and an available workstation. Complete [workstation setup](../src/skills/workstation/SKILL.md) first. Pair [Orca Mobile](orca.md#steps-the-settings-file-cannot-hold) only when selecting that route. On macOS a launchd agent keeps `claude remote-control` running in the checkout. Ubuntu uses the user service described below. The Claude app lists the workstation and opens a plain session on it. That session starts the dispatcher in Orca, and the dispatcher does the rest. This route needs no VPN, open port or screen sharing. Orca Mobile is a second route from anywhere after [Orca onboarding](orca.md), over the tailnet with Orca Relay as its fallback.

## The pieces

| Path | Role |
|---|---|
| `plots/home/launchd/local.claude-remote-control.plist.tmpl` | The agent's one source. `$HOME` is substituted at install time. |
| `~/Library/LaunchAgents/local.claude-remote-control.plist` | The installed agent, written and loaded by `task home:install`, compared by `task check`. It runs `claude remote-control` in `~/dev/slop-meister` at login, and `KeepAlive` starts it again whenever it exits, at most once a minute. |

The server connects outwards to the Anthropic API over TLS and accepts only the claude.ai account signed in here. It exits after roughly ten minutes without network, which is why launchd restarts it. Its output goes to `/dev/null`, which keeps launchd from copying the server's terminal output to disk. It does not make a phone conversation private, Claude writes its own session transcripts under `~/.claude/projects/` as it does for every session, so treat a phone session exactly like one at the desk. Read its state from `launchctl print`, and pass `--debug-file` to a hand-started server when a run needs diagnosis.

## One-time setup

1. `claude` once in the checkout, to accept the workspace trust dialog.
2. `claude remote-control` once in the checkout, answer `y` to `Enable Remote Control?`, then stop it. The agent inherits that answer.
3. `task home:install -- Library/LaunchAgents/local.claude-remote-control.plist`, which writes the agent and loads it.
4. `launchctl print gui/$(id -u)/local.claude-remote-control | grep -E "state|last exit"`, which must say `state = running`.
5. Install the Claude app, sign in with the same account, and confirm this Mac appears.
6. Sitting at the Mac, open a session from the phone and have it run the `--open` command below. Confirm the Orca terminal opens without a prompt on the screen, then close that terminal if you do not need it.

The shipped phone-service templates use `~/.local/bin/claude` and the neutral checkout default `~/dev/slop-meister`. Keep that layout or update the owning template before installing it. If either moves, launchd keeps failing to spawn it every minute and says so only in `launchctl print`, because the output goes to `/dev/null`. Check that print first whenever the Mac stops appearing on the phone.

After a Claude CLI update, a running launchd job may still use the previous binary even while `launchctl print` says `state = running`. If the phone app reports `failed to start session`, first check the job and the current Claude login. When no phone session is active, restart only this agent from the Mac with `launchctl kickstart -k gui/$(id -u)/local.claude-remote-control`, then verify it is running and retry. The restart disconnects sessions using that phone route, so coordinate it with their users.

Do not run `task home:install` from a phone session. Installing a changed agent reloads it, which ends the session you are typing in. The entry point itself returns within a minute.

## On Linux

Linux uses one systemd user unit in place of the launchd agent. The rest of this document applies with these differences.

| Mac | Linux |
|---|---|
| `plots/home/launchd/local.claude-remote-control.plist.tmpl` | `plots/home/systemd/claude-remote-control.service` |
| `~/Library/LaunchAgents/local.claude-remote-control.plist` | `~/.config/systemd/user/claude-remote-control.service` |
| `launchctl print gui/$(id -u)/local.claude-remote-control` | `systemctl --user status claude-remote-control.service` |
| `launchctl kickstart -k gui/$(id -u)/local.claude-remote-control` | `systemctl --user restart claude-remote-control.service` |

`task home:install -- .config/systemd/user/claude-remote-control.service` writes the unit, enables it, restarts it and turns on lingering with `loginctl enable-linger`. Lingering starts the user's units at boot, so the Claude app lists the machine after a reboot without a login. Orca needs a desktop login, so Orca Mobile and the dispatcher return only after one.

The install skips an unchanged unit file. When one of its steps failed, run `systemctl --user enable --now claude-remote-control.service` and `loginctl enable-linger` by hand. The doctor reports the unit as `systemd:claude-remote-control`, which is `ok` only when the unit is active and enabled, and lingering as `linger`.

For multiple workstations, follow [remote dispatch](remote-dispatch.md). It owns machine selection, distinct dispatcher names and remote recovery.

## Start a dispatcher from the phone

From Orca Mobile, open the Slopmeister workspace and run its **Claude dispatcher** or **Codex dispatcher** Quick Command. Each opens a new Orca terminal that runs `task dispatch` with a fixed name. The Codex dispatcher runs standalone, and Orca reports its agent status after the first turn.

From a Claude app session opened through `local.claude-remote-control`, ask it to run this command in the Slopmeister checkout. `--open` creates a separate Orca terminal, leaving the Claude app session available:

```bash
task dispatch -- --open claude phone-claude
```

Use `codex phone-codex` in place of `claude phone-claude` to open a Codex dispatcher. If Orca is unreachable, `--open` stops without opening anything, and the `workstation` skill diagnoses Orca. If Orca does not confirm the created terminal's handle, inspect Orca before retrying because the command may already be running.

The name refuses a second dispatcher: `task dispatch` checks for a live process carrying it and stops with `a live process already carries dispatcher name phone-claude`. The refusal proves a process carries the name, not that it is responsive. Inspect it in Orca and close a stale terminal before retrying. Wait for the first terminal to appear before asking again, since requests made within a few seconds can both pass the process check. The launcher starts a closed Orca with a minimal environment so the remote Claude session's variables do not reach every new Orca tab.

## Orca Mobile's two routes

The phone reaches Orca over the tailnet while the iPhone's Tailscale VPN is on, and over Orca Relay otherwise, provided the pairing was made with Orca Relay as [Orca onboarding](orca.md) describes. A LAN pairing has no Relay, and the phone then loses the Mac whenever the tailnet is off. The operator's network configuration owns tailnet policy, enrollment and VPN routing. Keep its recovery instructions in the owning context. If Orca Mobile reaches neither route, Orca is closed or signed out on the Mac, reopen it and read `bin/slopmeister workstation doctor`.

Orca's phone route and HA's approval notifications are separate. Follow the [host guide](../host/README.md#home-assistant-and-private-https) for Tailscale certificates, HA proxy trust and companion server URLs. Verify each configured route from the phone with Wi-Fi off. A working Orca session does not prove approval delivery.

## What is recoverable, and what is not

| State | The phone reaches | What it takes |
|---|---|---|
| Running, screen locked | Everything | Nothing. The agent and the login keychain keep working. |
| Network lost | Nothing while it lasts | Nothing. The server exits after about ten minutes and launchd starts it again when the network returns. |
| Logged out, or after a reboot | Nothing on the Mac, the Claude route on Linux | A login at the machine. The Mac's user agents do not run at the login window, and Orca needs a desktop session on both systems. |
| After a power cut, FileVault locked | Nothing | The disk unlock at the Mac. macOS 26 can unlock FileVault over SSH, which needs Remote Login enabled and the Mac reachable, neither of which this setup installs. |
| Claude login expired | Nothing through Claude | Reach the Mac through a Codex dispatcher in Orca Mobile instead, see below. |

Keep the machine awake while agents work. The [agent-machine contract](agent-hosts.md#the-contract) covers that prerequisite.

## When one tool's login dies

The two tools hold separate logins and separate routes to the phone, so either one recovers the other.

- Claude's login is dead: run the **Codex dispatcher** Quick Command from Orca Mobile and have it run `claude auth login`. Open the printed URL on the phone and paste the code back.
- Codex's login is dead: from a Claude session, run `codex login --device-auth` and enter the short code on the phone.

Log a tool out only when no session of that tool is running here, because a logout cuts all of them at once.
