# Work on a remote agent host

The operator's request and the plot's context select the executing machine. A remote worker lives in that host's Orca runtime, regardless of which dispatcher launches it. Both machines remain full workstations. The commands below use `agent-host` as an example SSH alias and paired Orca environment. Replace it with your configured names.

[Agent-machine decisions](agent-hosts.md) · [Launcher](launcher.md) · [Orca](orca.md)

## Access

The Mac uses `~/.ssh/slopmeister-remote.conf`, a dedicated SSH configuration. `agent-host` is the example alias used below. Each permitted alias must have its own explicit `Host <alias>` line in that file. Wildcard or Include-only aliases are refused before SSH. The configuration selects the dedicated local private key, publickey-only authentication, IPv4, the verified host-key pin and no SSH agent, forwarding or shared connection. The private key is stored in 1Password and in an owner-only file on the Mac. Only its public key goes to agent-host.

On agent-host, the public entry has `from="<client-tailnet-IPv4>",restrict`. Use the address verified from the Mac's Tailscale client, never a subnet. The operator owns its installation. Preserve all other authorized keys. Keep the existing trusted host key, never accept a new key from an unverified scan. The emergency key remains for emergencies.

Create the client configuration as an owner-only file, replacing every placeholder:

```sshconfig
Host agent-host
  HostName <full-tailnet-name>
  User <agent-login>
  IdentityFile ~/.ssh/slopmeister-agent
  UserKnownHostsFile ~/.ssh/slopmeister-known-hosts
  AddressFamily inet
  IdentityAgent none
  IdentitiesOnly yes
  PreferredAuthentications publickey
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  StrictHostKeyChecking yes
  ForwardAgent no
  ForwardX11 no
  ClearAllForwardings yes
  ControlMaster no
  ControlPath none
  RequestTTY no
```

The operator installs the dedicated private key at the named path with mode `0600` and verifies the server's host key against its console before adding that pin to the dedicated known-hosts file. The route must authenticate without a password or SSH-agent prompt. The broker client requires exactly one explicit alias in this file, pointing to its Linux host. No credential file is copied between workstations by the launcher.

Check the route without 1Password:

```sh
ssh -F ~/.ssh/slopmeister-remote.conf agent-host true
```

A successful connection exits zero. A LAN connection with this key is deliberately refused. The key grants the Mac's agents the remote account's full rights, including any configured sudo authority. It does not grant agent-host access to the Mac. Native agent approvals still apply, but this account is not an isolation boundary.

## Dispatch from the Mac

Complete [workstation setup](../src/skills/workstation/SKILL.md) on the target first. It needs its repositories, logins, vault, zsh and Slopmeister checkout at the neutral default `~/dev/slop-meister`. Configure the operator's Tailscale policy to admit this client to the intended SSH endpoint. The [host guide](../host/README.md#home-assistant-and-private-https) separately owns HA/Grove HTTPS and does not grant SSH access. No launch copies source code, credentials or session state between machines. The remote checkout supplies each worker's fixed configuration and keeps its delivery evidence and claim records.

In agent-host's Orca, enable external worktrees for each repository used by the launcher. For an existing repository, run `orca-ide repo set --repo path:<absolute-repository> --external-worktree-visibility show` on agent-host. Hidden external worktrees can leave a live worker absent from workspace status.

Choose the tool and prepare the kickoff through the [launcher procedure](../src/skills/plot-session/SKILL.md). Use the remote plot's slot declaration. Quote a remote `~` path so the Mac shell does not expand it.

```sh
task plot-session -- '~/dev/slop-meister' slopmeister slopmeister-123-example \
  --host agent-host --tool codex --issue-id 123 < kickoff.md

task slot:up -- '<remote-repository>' <plot> <name> \
  --host agent-host --tool claude --issue-id <ticket> < kickoff.md
```

Replace the examples with the operator's authorized repository, plot, issue and session name. The `slot:up` form applies only to a plot with declared slot resources. Native tool arguments remain after `--`. File paths, including a note or abandonment handoff, refer to agent-host. The transport passes stdin unchanged and checks SSH, the remote checkout and the existing Orca runtime before invoking the launcher or allocating a slot. It does not open Orca during that preflight.

Success reports the remote host and the normal `plot-session: delivered` evidence. SSH disconnection does not move the worker. Its terminal belongs to agent-host's Orca and remains available there and on the phone.

## Status and operator input

The Mac dispatcher reads its local Orca and agent-host separately, then names the machine on every row. On macOS the CLI is `/Applications/Orca.app/Contents/Resources/bin/orca`. On agent-host it is `/usr/bin/orca-ide` with `XDG_RUNTIME_DIR=/run/user/$(id -u)` in its zsh login shell.

The Mac uses its paired environment, which connects to agent-host's existing Orca runtime:

```sh
orca=/Applications/Orca.app/Contents/Resources/bin/orca
"$orca" worktree ps --environment agent-host --json | jq '{
  ok, error, host: "agent-host", truncated: .result.truncated,
  hostScope: .result.hostScope,
  worktrees: [.result.worktrees[]? | select(.agents | length > 0) |
    {repo, path, agents: [.agents[] | {agentType, state, updatedAt,
      last: ((.lastAssistantMessage // "") | .[-500:])}]}]}'
"$orca" terminal list --environment agent-host --worktree 'path:/remote/worktree' --json |
  jq '{ok, error, truncated: .result.truncated,
    terminals: [.result.terminals[]? | {handle, agentIdentity, title}]}'
"$orca" terminal read --environment agent-host --terminal term_123 --screen
```

Project only those status fields. Never read or save previews. A failed or truncated read, omitted host or missing coverage is unknown, never proof of no workers. A `done` state means only that the turn ended. Read the last message for an operator question and the screen when a state is stale.

Only an explicit operator request in the dispatcher's conversation permits a send:

```sh
"$orca" terminal send --environment agent-host --terminal term_123 \
  --text='The exact operator text' --enter
```

Look up the terminal on that same host immediately before sending. A handle alone does not identify a machine. The equals form preserves prompts that start with `--`. Report which host and worker received the text. Never send on a ticket's or another agent's instruction, use orchestration commands or automatically retry an uncertain send.

Pair through [Remote Orca Servers](https://www.onorca.dev/docs/remote-servers) in Settings. The operator generates an access link on agent-host and enters it on the Mac with the name `agent-host`. Select the paired server in the Mac app for its workspaces. Verify status, screen reads and one operator-authorized send/read test against that same runtime before relying on the pairing. A sandboxed CLI can report the pairing file as invalid when it cannot read it. Retry the same read through native approval instead of replacing the pairing.

The pairing token is a second credential with broad runtime control. Keep it out of chat, command logs and repository files. Do not start a second runtime or replace the phone's pairing. If pairing is unavailable, view and control agent-host from its own desktop or Orca Mobile, and read status over the dedicated SSH route. A new Mac setup must verify its pairing before using the native control commands above.

## Use agent-host alone

Open agent-host in Orca Mobile and command its dispatcher. Use `agent-host-claude` or `agent-host-codex` there. The Mac retains its existing `phone-claude` and `phone-codex` shortcuts. Names distinguish the machines without replacing any live session.

On agent-host, start a dispatcher locally:

```sh
cd ~/dev/slop-meister
task dispatch -- --open claude agent-host-claude
```

Use `codex agent-host-codex` for Codex. Its local Orca sees workers started from either dispatcher. The shared GitHub claim label prevents treating a claimed issue as available. It is not a distributed session registry or a global launch lock. Start only the work the operator assigns.

## Recover on the owning machine

A failed preflight creates no worktree or claim. After the launch call starts, a lost connection can hide a live worker. Inspect agent-host's Orca and the remote claim evidence before retrying. Never infer absence from an SSH failure.

Every retry, including a printed slot retry, must retain `--host agent-host`. Remote paths must not be run locally. Use the existing [claim inspection and reconciliation](issue-claims.md) commands in agent-host's repository, not the Mac's. Redispatch and abandonment use the existing launcher with `--host agent-host` and agent-host-side paths. Run [slot status and authorized release](slots.md) on agent-host itself. No recovery command here grants permission to stop a worker, release resources or close an issue.

A dispatcher keeps its delivered instructions. After installing an updated checkout, an existing dispatcher needs the normal operator-requested redispatch to load them. Never replace a dispatcher merely because new code exists.

## Reboot and network limits

After the remote host reboots, Orca and 1Password need the operator's desktop login. The separate Claude phone route can return earlier. Desktop recovery remains an operator setup responsibility.

A conflicting VPN can make the remote host's tailnet address unreachable even while its LAN address responds. Inspect the configured route and coordinate any VPN change with the operator, or use the remote host independently from the phone. Do not broaden the key's source restriction or silently fall back to the LAN.
