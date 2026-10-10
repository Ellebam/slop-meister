# Project secrets through 1Password

Owning repositories retain their operational commands and credential references. Slopmeister can also deliver checked-in fixed provider consumers for explicitly selected plot/action combinations, using private runtime profiles outside the repository. In a launched session on either machine, `op run` goes to the [approval broker](1password-access.md), which resolves the named references after a Home Assistant decision and hands them once to the agent's own command. It offers no secret-value API to the agent beyond that command's environment. See [selected service read and write actions](service-actions.md).

## Desktop integration and fallback

Install the 1Password desktop app and CLI on the workstation. The operator signs in, unlocks the app and enables its CLI integration in Settings, Developer. In an ordinary operator terminal, `op --version` checks the CLI and `op whoami` checks the account. These commands do not retrieve secret values.

Slopmeister's `op` forwards ordinary operator-terminal commands to the vendor CLI next on `PATH`. Launched agent sessions use the broker. If it is unreachable, the operator can authorize one exact vendor-CLI command, including the environment file and consumer. Use `type -a op` to distinguish the installed shim from the real CLI, then name the real absolute path:

```text
/absolute/path/to/vendor/op run --env-file=secrets/example.env -- <fixed-consumer>
```

Approve that command in the desktop app. There is no new route setting and no automatic fallback. Keep the broker marker and shim intact. The [request contract](1password-access.md#when-the-broker-is-unreachable) owns when an agent may use this route. The [host guide](../host/README.md#broker-credentials-and-first-approval) owns the separate broker service account.

## Set up a project

1. Inspect the project's Taskfile and consumers before adding another mechanism. Existing helpers do not authorize direct reads or unmasked output.
2. Select a dedicated project vault and document each required field in the project. Automated item names use `CAPS_WITH_UNDERSCORES`. Field labels may remain lowercase. References such as `op://project-prod/SERVICE_TOKEN/credential` may be committed. Values belong in 1Password.
3. Where explicitly authorized, use a fixed placeholder bootstrap with projected metadata and suppressed diagnostics. Preserve existing entries. Creation permission does not authorize reading their values or changing them.
4. Implement one fixed Taskfile target per operation. Use literal reference files, inject only the required secrets through `op run`, and invoke a fixed consumer without an arbitrary command tail.
5. Test with synthetic secrets before real access. Verify that output, errors, arguments and temporary files cannot expose the values. Reject unresolved placeholders before network access. Then prove the exact authorized operation with real access.

Secret values must never appear in source, issues, task notes, logs, screenshots or client assets. Do not use `op read`, item/document retrieval, `op inject`, raw metadata output, environment dumps or `--no-masking`. A wrapper containing a forbidden command is still forbidden. The narrowly declared exception is internal document retrieval by a delivered fixed service-action consumer after operator authorization and native approval review, under that fresh session's explicit action policy. Codex's automatic reviewer may make that approval decision. Do not describe it as operator approval. This grants no direct retrieval command or arbitrary wrapper. Output masking does not replace control over what a consumer prints.

SSH consumers require a trusted host key and isolated configuration. Keep keys in a private agent or pipe, clean up owned processes, and avoid inherited forwarding or shared SSH connections. Provider consumers use fixed HTTPS endpoints and suppress raw API responses and diagnostics.

The operator-authorized [dedicated Mac-to-agent-host key](remote-dispatch.md#access) is an exception to keeping SSH private keys only in an agent or pipe. Its private half is saved in 1Password and an owner-only Mac file. Public-key installation does not copy the private half to agent-host or weaken the native approval rules.

## Current boundary

Each owning repository documents its Taskfile targets and access requirements for both tools. Separately declared Slopmeister actions use fixed templates and private profiles as described above. A placeholder scaffold is preparation, not proof that credentials work or that a deployment is ready.

This integration does not change global permissions or promise fewer prompts. The [permission contract](../src/permissions.toml) owns the command rules. Operating-system consent, agent command approval and 1Password authorization are separate boundaries.

## macOS app-data consent

The macOS prompt saying that an app, such as Orca, wants to access data from other apps is separate from 1Password's authorization popup. It is the `kTCCServiceSystemPolicyAppData` consent, requested by `sandboxd` when a process opens a file inside another application's protected container. The prompt names the responsible application, not the process that opened the file.

Every `op` process checks the 1Password desktop app's settings at `~/Library/Group Containers/2BUA8C4S2C.com.1password/Library/Application Support/1Password/Data/settings/settings.json` when it starts, even with `OP_BIOMETRIC_UNLOCK_ENABLED=false` and a service-account token. The unified log shows `AUTHREQ_ATTRIBUTION` lines with `accessing={TCCDProcess: identifier=com.1password.op` and requester `com.apple.sandboxd`. Record log events and visible prompts separately:

```bash
/usr/bin/log show --last 10m --predicate 'process == "tccd" AND eventMessage CONTAINS "AUTHREQ_ATTRIBUTION" AND eventMessage CONTAINS "accessing={TCCDProcess: identifier=com.1password.op" AND eventMessage CONTAINS "com.apple.sandboxd"' --style compact
```

Selected [service actions](service-actions.md) need no desktop integration, so on macOS their consumer runs `op` with `HOME=/var/empty`, the system's empty read-only folder, and keeps `op`'s own settings through `XDG_CONFIG_HOME`. `op` then finds no container to check and macOS never asks. No machine setup is needed. Linux uses the operator's home with desktop integration disabled and no desktop fallback.

Repository `op run` targets use the desktop integration and still read the desktop app's data, so they remain subject to macOS privacy policy. A Taskfile allow rule does not replace it. Full Disk Access covers other protected data as well and is not an implicit setup step for another app. Do not edit the privacy database, re-sign binaries or disable system protections to suppress a prompt.

The [official 1Password MCP server](https://www.1password.dev/environments/mcp-server) is another supported integration, focused on Environments and local `.env` mounts. It returns names rather than secret values. It is not a replacement command runner for the existing item-reference `op run` targets, and its documentation does not prove that those CLI targets avoid macOS prompts. The chosen approval broker and its limits are documented in [secret requests](1password-access.md). The vendor MCP route does not replace it.
