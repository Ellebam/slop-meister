# Set up secret access

[Secret requests and limits](1password-access.md) · [Host route](../host/README.md#home-assistant-approval-route)

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

