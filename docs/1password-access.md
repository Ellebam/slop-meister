# Secret requests in two tiers

An agent asks for secrets with `op run`. On macOS and Ubuntu the home install puts Slopmeister's own `op` at `~/.local/bin/op`. [Workstation setup](../src/skills/workstation/SKILL.md) puts `~/.local/bin` first on every shell's `PATH`, and the launcher marks each session with `SLOPMEISTER_SECRET_BROKER=1`. In a marked session this `op` uses two local 1Password service-account tokens. It reads the references of an `op run`, takes the tier from the vault each one names and starts the real `op run` with that tier's token. The real `op` resolves and masks. Unmarked, in the operator's own terminals, it is the real `op`. No service runs for this on either machine.

Selected [service actions](service-actions.md) keep their existing in-app native approval and service-account access. They acquire no Home Assistant decision and no desktop 1Password prompt.

## Tiers

| | Tier one | Tier two |
|---|---|---|
| Holds | Routine credentials with limited impact | Production, customer and business credentials |
| Vaults | The vaults the tier-one account lists | The vaults the tier-two account lists beyond tier one |
| Needs | The operator's task | The operator's word for the command, then their approval in Home Assistant |
| Account rights | Read | Read and write |

Vault names live with the accounts, not in this repository. `~/.config/slopmeister/op/tiers.json` on each machine holds the names each token listed at setup. The tier-two account also reads the tier-one vaults, so a request that names both tiers is one tier-two request. A vault in neither list is refused with its name, and only the desktop route reaches it. That includes the built-in Personal vault, which no service account can read.

## Request

```bash
op run --env-file=secrets/example.env -- <the command>
```

`op run` reads its `--env-file` files like the real command and every variable in the environment whose value is an `op://` reference. It keeps literal variables literal. A reference is `op://vault/item/field`, with an optional section and query such as `?ssh-format=openssh`. The files are read once. The real `op` receives the literals and references through the environment and no file, so it resolves exactly what was read. A value that the real `op` would trim into a reference is refused. The command never sees the token. The exit code is the command's. A line without references runs the command directly.

Every flag other than `--env-file` is refused, `--no-masking` included. An inherited `OP_RUN_NO_MASKING` or 1Password Connect setting is dropped before the real `op` starts. An env file that sets one of them, `OP_SERVICE_ACCOUNT_TOKEN` or this program's own route variables is refused.

`op read`, `op item get`, `op item share`, `op document get` and `op inject` are refused by this `op` whatever flags surround them, also in the plural spellings `items` and `documents`, and denied by the permission rules. Item sharing is refused because its link exposes a copy of the secret. Every other subcommand, such as `op --version` or `op whoami`, passes to the real `op` next on `PATH`. `op run` behind a global flag is refused too, so put nothing before `run`.

## Tier two

```bash
SECRET_ASK_REASON="<what the command does and why>" op tier-two -- op run --env-file=secrets/ssh.env -- <the command>
```

Tier two has two layers, and both are required.

The first layer is the operator's word. A plain `op run` on a tier-two reference releases nothing and names the form `op tier-two -- <command>`. That form is a `needs_intent` rule in both tools, so it runs only when the operator's own message orders that command. It sets the route for its process tree, so an `op run` inside a Task target needs no change. For a project target that already wraps `op run`, use `SECRET_ASK_REASON="<one line>" op tier-two -- task <target>`.

The second layer is the approval. Each tier-two `op run` sends one question to Home Assistant. Its text starts with the reason from `SECRET_ASK_REASON`, the session and the host, then the exact command, the references and the directory. The session is the containing repository's directory name. The reason is required and shown as one line. Without it the request is refused and nothing is sent. The command prints `op run: request <id> waits for Home Assistant approval` on stderr and waits up to ten minutes, so give the tool call a ten-minute timeout. Only Approve for this request's own ID starts the real `op run`. Deny prints `denied`, ten minutes of silence print `timed out`, and both exit 1. A wait that was killed asks again on the next run. A press for a request nobody waits for releases nothing.

`op tier-two` and `op desktop` must be the outermost command. Below an `op run` or another route word they are refused, so the allowed `op run` prefix cannot carry them past the rule.

## Desktop route

```bash
op desktop -- <the command>
```

The operator can order this in any running session, for either tier and for a vault in no tier. Every `op run` below it goes unread to the real `op` with the 1Password desktop app and the operator's biometrics. It uses no token and no Home Assistant, so it works when Home Assistant is down and on a machine without token files. It is a `needs_intent` rule like tier two. Agents never choose it. When `op run` reports that Home Assistant did not take the question, or that a vault is in no tier, stop and tell the operator.

## Home Assistant route

`~/.config/slopmeister/op/home-assistant.json` holds `ask_url`, `answer_url` and `token`. The [host guide](../host/README.md#home-assistant-approval-route) owns the Linux Home Assistant deployment, the route and its credential. Secret resolution runs locally on either supported workstation. No Linux broker is required.

- The question is one `POST` to `ask_url` with the JSON fields `id`, `title` and `message`. The `id` is 32 random hex characters. A redirect is refused.
- The answer is one `GET` to `answer_url` with the token as bearer credential. It returns JSON with a map `decisions` from request ID to `approved` or `denied`, at the top level or under `attributes` as a Home Assistant state carries it.
- Home Assistant records the first press of the operator's own user within ten minutes of the question, and nothing else writes a decision.
- The credential can send a question and read answers. Home Assistant must refuse it for every service that operates a device.

## Set up a machine

Choose a custom vault that holds the two service-account tokens and nothing else. No service account may read this token vault, including CI readers. Only the operator's own login reaches it to set up a machine and to change a token. Give tier one read access to its selected vaults. Give tier two the intended read and write access, including read access to all tier-one vaults.

Prepare the two private reference files outside the checkout. Copy [op-setup.env.example](../examples/op-setup.env.example) to `~/.config/slopmeister/op-setup.env` and [op-approval.env.example](../examples/op-approval.env.example) to `~/.config/slopmeister/op-approval.env`. Set mode `0600` on both files. Replace every example reference with your own item and field names. Set `SLOPMEISTER_OP_TOKEN_VAULT` to the exact name of the token vault. The approval file references the two HTTPS addresses and the narrow route token created by the host guide. These files hold references and the vault name, never credential values.

```bash
task op:setup
task op:approval
```

The operator runs both in their own terminal on the target machine, where `op` is the real one and the desktop app asks. In a launched session they run only under operator-ordered `op desktop`. These targets need working desktop integration on that machine. They do not provision an unattended machine without an operator login or transfer credentials between machines.

`op:setup` reads both tokens, checks each by listing its vault names and writes `tier-one.token`, `tier-two.token` and `tiers.json`. `op:approval` writes `home-assistant.json`. The directory `~/.config/slopmeister/op` has mode `0700` and each file mode `0600`. The output names the vaults of each tier and ends with `OP_SETUP_PASS`, and it never holds a value. A missing value, a rejected token or a token that lists the token vault prints `OP_SETUP_FAIL` with the reason and writes nothing.

To rotate a token, replace it in the token vault, run `task op:setup` on each machine and revoke the old token in 1Password. 1Password cannot change the vaults or rights of an existing service account, so a changed tier needs a new account and the same steps.

The machine-side program is `~/.local/bin/op` with `~/.local/lib/slopmeister-op`, installed by `task home:install` and checked by `task check`'s drift report.

## Limits

This is a guardrail for cooperative agents, not a security boundary.

- An agent runs as the operator's user. An agent that goes after a token file can read it, and then needs neither the operator's word nor an approval. The Home Assistant approval is a second factor only for a request that passes through this `op`.
- The rules of both tools match command text. A route word inside `sh -c`, a script or a Task target is invisible to them, and the route itself is an environment variable an agent could set by hand. Then only the Home Assistant approval remains for tier two, and the desktop prompt for the desktop route.
- The tier-two account can write to its vaults. Nothing here offers item writes, and the rules keep `op item create`, `edit` and `delete` behind the operator's word.
- Masking is the real `op`'s and textual. A value a command transforms, encodes or splits is not recognised. Masking hides values from the tool output. It does not stop the command from writing or sending them, so the operator judges the command before approving.
- The question in Home Assistant shows what this program read. Root, Docker administration and a compromised Home Assistant administrator can forge an approval, which is the hosts' existing accepted risk.

## Prove the route

Use one throwaway item per tier, an env file naming each and a command that prints a marker only when its variable is set. With operator authorization, use fresh launched sessions of both tools on each configured workstation to verify these results. Static tests use stand-ins and do not access a real account or service.

1. A tier-one `op run` prints the marker with `<concealed by 1Password>` and no phone prompt, and `${OP_SERVICE_ACCOUNT_TOKEN:-absent}` in the command prints `absent`.
2. A plain tier-two `op run` exits 1 and names `op tier-two`. Under `op tier-two` the tool asks for the operator's word, then the phone shows the references, the command, the reason, the host and the session. Check Approve, Deny, the ten-minute expiry and a second press.
3. With the Home Assistant route unavailable to the test session, operator-ordered `op desktop -- op run ...` resolves both items through the desktop app. Do not stop a live service for this check.
4. A device service call with the route's credential is refused.
5. The value-printing forms are refused in both spellings.

[Testing](testing.md) names the synthetic and native suites. Tests cannot prove real device delivery.
