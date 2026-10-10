# Secret requests through Home Assistant approval

Home Assistant approval is the recommended route for agent secret requests. Deploy its Linux services through the [host guide](../host/README.md), which owns service-account setup, credentials, HTTPS and companion registration. On macOS and Ubuntu, the home install puts Slopmeister's `op` at `~/.local/bin/op`. Put `~/.local/bin` first on the shell's `PATH` during [workstation setup](../src/skills/workstation/SKILL.md). Worker and dispatcher launchers mark each session with `SLOPMEISTER_SECRET_BROKER=1`. In a marked session `op run` goes to the approval broker on the Linux agent host instead of the desktop app. Unmarked, in the operator's own terminals, it is the real `op`. Home Assistant shows the operator the references, the exact command, the reason, the host, the session and the directory. Approve releases the values once to that waiting agent. Deny or ten minutes without a decision releases nothing. The same command works on the Mac, through the dedicated SSH route of [remote dispatch](remote-dispatch.md), and no broker or broker credential exists there.

Selected [service actions](service-actions.md) keep their existing in-app native approval and service-account access. They do not acquire a Home Assistant decision or a desktop 1Password prompt.

## Request

```bash
op run --env-file=secrets/example.env -- <the command>
SECRET_ASK_REASON="Deploy the Home Assistant host" op run --env-file=secrets/ssh.env -- <the command>
```

`op run` reads its `--env-file` files like the real command, every variable in the environment whose value is an `op://` reference, and keeps literal variables literal. A marked session refuses a command with no secret reference and exits 2. Run that command directly so its native approval rules apply. A reference is `op://vault/item/field`, with an optional section and query such as `?ssh-format=openssh`. `SECRET_ASK_REASON` is optional and appears in the notification as the reason. The session is the containing repository's directory name. Task targets that wrap `op run` use the same route.

The command prints `secret-ask: request <id> waits for Home Assistant approval` on stderr, then waits up to ten minutes. After Approve the command runs here, as the agent, in the current directory, with the agent's own environment plus the values, stdin attached. Every value is masked in stdout and stderr as `<concealed by 1Password>`, line by line, so a multi-line key is masked too. The exit code is the command's. Give the tool call a ten-minute timeout. When the tool times out first, run the same `op run` again: an identical command in the same directory with the same references reattaches to the pending or approved request and costs no second approval.

Deny prints `secret-ask: request <id> denied` and exits 1. Ten minutes without a decision, or without the agent collecting an approval, print `timed out`. A reference the broker's account cannot read prints `failed`, and the audit log names the variable, never a value. A broker restart prints `interrupted`, nothing was released, run the command again. `--no-masking` is refused.

`op read`, `op item get`, `op item share`, `op document get` and `op inject` are refused by this `op` whatever flags surround them, and denied by the permission rules. Item sharing is refused because its link exposes a copy of the secret. Every other subcommand, such as `op --version` or `op whoami`, passes to the real `op` next on `PATH`. `op run` behind a global flag is refused too, so put nothing before `run`.

## When the broker is unreachable

When neither the broker socket nor the SSH route answers, `op run` exits nonzero and names the step, for example `the SSH route <alias> gave no result`. This also covers a workstation whose broker has not been configured. Only then can the operator order the [desktop route](1password.md#desktop-integration-and-fallback) for one exact command through the real binary. Agents never choose it, and while the broker answers no session on either machine is told to use the desktop prompt.

## Trust and limits

The broker runs on the Linux agent host under its own service account. Its 1Password service account can read only the custom vaults granted to it and cannot read the built-in Personal vault. A required reference outside that grant fails. The machine-side files are `~/.local/bin/op` and `~/.local/lib/slopmeister-op`, installed by `task home:install` and checked by `task check`'s drift report. The operator's approval of each request is the security layer: nothing else reviews the command or the references. The broker never runs the command. After Approve it resolves each reference with `op read` as the service account, keeps the values in memory until the requesting account collects them once, and drops them. Delivery is at most once: a reply that never reaches its client is taken back, but a client that dies after receiving it has consumed the approval, and the rerun then shows `delivered` and needs a new request. The audit log, the request history and the journal hold references, commands and decisions, never values or approval tokens. Only the configured agent account can submit or collect, checked on the socket's peer credentials. The Mac reaches the broker as that account over SSH, so the same check holds.

Approval validates the operator's event context and a private random action token, distinct from the public request ID. The first valid decision wins. A stale notification cannot approve a completed or expired request. Root, Docker administration and a compromised Home Assistant administrator can bypass this boundary, so this is not an isolation boundary against those administrators.

Masking is textual. A value a command transforms, encodes or splits across lines is not recognised. Masking hides values from the tool output, it does not stop the command from writing or sending them, so the operator judges the command before approving.

## Prove the route

Use a throwaway item in a custom vault, an env file naming it, and a command that prints a marker only when its variable is set. In fresh launched sessions of both tools on each configured workstation, verify Approve, Deny and the ten-minute expiry, the notification text on phone and Mac, body taps and the host view, and that a rerun reattaches. Scan the broker's `audit.log`, `requests.json` and journal for the throwaway value through private input, never by pasting it into command arguments. [Testing](testing.md) names the synthetic and native suites. Tests cannot prove real device delivery.
